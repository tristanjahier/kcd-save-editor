# Reverse-engineering the binary format of Kingdom Come: Deliverance save files

This guide was written using a sample of over a dozen actual save files made on the Windows version of Kingdom Come: Deliverance (the first one) version 1.9.6+.

Saved games are `.whs` files located at `%USERPROFILE%\Saved Games\kingdomcome\saves\playline<N>`.

## The game engine

Our first lead is the game engine. Game engines may offer tools to serialize the state of the game world, and in the case of an open-world game like Kingdom Come: Deliverance, it could be useful to save the state of hundreds of NPCs (their locations, statistics and inventories), the contents of chests, the progress of quests and objectives, the items dropped on the ground, etc.

It is publicly known that Kingdom Come: Deliverance was built on CryEngine. The game's [Wikipedia page (English)](https://en.wikipedia.org/wiki/Kingdom_Come:_Deliverance) reports that [Warhorse Studios licensed CryEngine 3 to develop their first game](https://www.cryengine.com/news/view/warhorse-studios-licensed-cryengine-reg-to-develop-rpg).

CryEngine 3 is a proprietary engine, its code is not public, and in 2026 it is hard to find any resources for that version anyway. CryEngine was open-sourced ("source-available" to be accurate) as of version 5, though, and it is possible that the game serialization/save code did not change. The source code of CryEngine 5 used to be public on GitHub, but as of 2026 the repository is no longer freely accessible. Instead, [you need to create a cryengine.com account and a GitHub account, then request access to the source code](https://github.com/CRYTEK/CRYENGINE_ReadMe).

### Inspecting its source code

From now on, we will consider that we have been granted access to the source code of CryEngine 5 on GitHub. The reference version is 5.7.1 (the only one Crytek still distributes as of October 2026).

A quick search on file paths containing "save" inside `Code/CryEngine/` returns many results. One file and three directories stand out:
- `Code/CryEngine/CryAction/ISaveGame.h`
- `Code/CryEngine/CryAction/PlayerProfiles/`
- `Code/CryEngine/CryAction/Serialization/`
- `Code/CryEngine/CrySystem/PlatformOS/`

`Code/CryEngine/CryAction/ISaveGame.h` is the C++ interface for a structure holding the game data to be written to a save file.

`Code/CryEngine/CryAction/PlayerProfiles/` obviously contains implementations for player profiles, which seem to own game saving capabilities (methods `CreateSaveGameEnumerator`, `CreateSaveGame`, `CreateLoadGame` and `DeleteSaveGame` in class `CPlayerProfile`).

`Code/CryEngine/CryAction/Serialization/` in particular is promising because it contains multiple instances of the string "savegame", which is standard vocabulary for saved game files; and "serialization" which also points towards transforming game objects into another representation. `CXmlSaveGame` is an implementation of interface `ISaveGame`, which is the type of object returned by `CPlayerProfile::CreateSaveGame` (mentioned above). The subdirectory `XMLCPBin/` contains helpers to read and write a binary format named "XML ComPressed Binary", and file `XMLCPBin/XMLCPB_Common.h` specifically mentions that the main purpose of this format is for "savegame/loadgame processes".

`Code/CryEngine/CrySystem/PlatformOS/` seems to contain components to encapsulate interfacing with the platform's operating system (like Windows on a PC).

Let's look at `Code/CryEngine/CryAction/Serialization/XMLCPBin/Reader/XMLCPB_Reader.cpp`, in particular the method `CReader::ReadBinaryFile` (lines 228-295):

```cpp
bool CReader::ReadBinaryFile(const char* pFileName)
{
    ...
}
```

Lines 246-248 show that a struct named `SFileHeader` can be found at the very end of the binary stream, suggesting that, despite its name, it is a footer.
```cpp
SFileHeader fileHeader;
pOSSaveReader->Seek(-int(sizeof(fileHeader)), IPlatformOS::ISaveReader::ESM_END);
ReadDataFromFileInternal(pOSSaveReader, &fileHeader, sizeof(fileHeader));
```

Internally `ReadDataFromFileInternal` calls `pOSSaveReader->ReadBytes(pDst, numBytes)`. `pOSSaveReader` is an `IPlatformOS::ISaveReaderPtr`, which is a macro-defined smart-pointer for struct `ISaveReader` (for reference, it is defined in `Code/CryEngine/CryCommon/CryCore/Platform/IPlatformOS.h` at line 554: `DECLARE_SHARED_POINTERS(ISaveReader)`). The codebase provides only two implementations of `IPlatformOS::ISaveReader`: `CSaveReader_CryPak` and `CSaveReader_Memory`. To find which one is behind `pOSSaveReader`, we need to look at how it was created:
```cpp
IPlatformOS::ISaveReaderPtr pOSSaveReader = gEnv->pSystem->GetPlatformOS()->SaveGetReader(pFileName);
```

`GetPlatformOS` returns an implementation of interface `IPlatformOS`. `CPlatformOS_PC` is the only implementation in the codebase ([console implementations are only available to registered console developers](https://www.cryengine.com/docs/static/engines/cryengine-5/categories/23756813/pages/23306665)), and as we are targeting PC/Windows save files, we can safely assume that this is the right implementation. `CPlatformOS_PC::SaveGetReader` creates and returns a `CSaveReader_CryPak` object.

After this cat-and-mouse game, we can finally read the implementation of `ReadBytes`. In `Code/CryEngine/CrySystem/PlatformOS/SaveReaderWriter_CryPak.cpp` at line 260 we can see that it literally just copies its bytes (from its `m_data` member) into the memory of `data`, without any kind of transformation. An important caveat however: class `CSaveReader_CryPak` decrypts the file if necessary (see its parent constructor at lines 76-135), meaning that if the save file is encrypted, its bytes will not be readable as-is.

Since `data` points to `fileHeader`, we can conclude that, unless the save file is encrypted, the footer is just a plain memory copy of the struct `SFileHeader`.

#### Decoding the SFileHeader structure

`SFileHeader` is defined at `Code/CryEngine/CryAction/Serialization/XMLCPBin/XMLCPB_Common.h:53`. We need to compute `sizeof(SFileHeader)` so that we can find the position where the footer starts, in order to examine those bytes in a hexadecimal editor.

First member is `static const uint FILETYPECHECK = 'PBX0'`, but it is static and is not stored in each instance, so we can ignore it.

Second member is the constructor (`SFileHeader()`). Like any function, it is not duplicated for each instance, so we can ignore it too. _Caveat: [the presence of any virtual function would have changed the structure layout](https://www.learncpp.com/cpp-tutorial/the-virtual-table/)._

Third member is `struct SStringTable`, which is a nested type declaration, so it does not take any space in the instance's memory either.

Fourth member is:
```cpp
uint32 m_fileTypeCheck;
```

`uint32` is not a standard C++ type. We can find its definition in `Code/CryEngine/CryCommon/CryCore/BaseTypes.h` at line 56:
```cpp
typedef uint uint32;
```

In turn, `uint` is defined in the same file at line 21:
```cpp
typedef unsigned int uint;
```

What is the size of an unsigned int? It depends on the platform, and especially the compiler. However, there is a compile-time assertion at line 57 that settles it:
```cpp
static_assert(sizeof(uint32) == 4, "Wrong type size!");
```

So in CryEngine, `uint32` MUST BE 4 bytes (32 bits). Which means `m_fileTypeCheck` takes the first 4 bytes in memory.

Next comes:
```cpp
#ifdef XMLCPB_CHECK_FILE_INTEGRITY
enum { MD5_SIGNATURE_SIZE = 16 };
char m_MD5Signature[MD5_SIGNATURE_SIZE];  // it uses the MD5 algorithm for the integrity check.
#endif
```

It is guarded by `#ifdef XMLCPB_CHECK_FILE_INTEGRITY`, but this macro is defined above in the same file if `CRY_PLATFORM_WINDOWS` (lines 29-31). Windows being the platform we target, we know these members are present. `enum { MD5_SIGNATURE_SIZE = 16 }` is only a declaration, so we ignore it. `char m_MD5Signature[MD5_SIGNATURE_SIZE]` is an array of 16 `char`, each of exactly 1 byte, for a total of 16 bytes.

Next members are:
```cpp
SStringTable m_tags;
SStringTable m_attrNames;
SStringTable m_strData;
```

3 instances of the nested type `SStringTable` that we skipped earlier:
```cpp
struct SStringTable
{
    uint32 m_numStrings;
    uint32 m_sizeStringData;
};
```

We already settled that `uint32` is 4 bytes, so an `SStringTable` type is 2 x 4 = 8 bytes. Therefore `m_tags`, `m_attrNames` and `m_strData` take 3 x 8 = 24 bytes.

Next come 4 `uint32` members for a total of 4 x 4 = 16 bytes.
```cpp
uint32 m_numAttrSets;
uint32 m_sizeAttrSets;
uint32 m_sizeNodes;
uint32 m_numNodes;
```

Last we have:
```cpp
bool m_hasInternalError;
```

A boolean only requires one bit to be encoded, but as computer memory is addressed in whole bytes, not bits, a boolean takes at least one byte in memory. How many bytes is not enforced by the C++ standard: it depends on the compiler. For a CryEngine game on Windows, we can assume it was compiled with Microsoft Visual C++ (MSVC). [In every version since v14 (2015) at least, a boolean is stored on 1 byte](https://learn.microsoft.com/en-us/cpp/cpp/data-type-ranges?view=msvc-140). In practice `true` is stored as `00000001` in binary.

In total an instance of `SFileHeader` takes 4 + 16 + 24 + 16 + 1 = 61 bytes. **Or does it?**

Data in memory is "aligned". Without going into too much detail, that is a crucial requirement for efficient memory access by the processor (read more on [Wikipedia](https://en.wikipedia.org/wiki/Data_structure_alignment)).

Each primitive type has a given alignment requirement: [https://learn.microsoft.com/en-us/cpp/cpp/alignment-cpp-declarations?view=msvc-140](https://learn.microsoft.com/en-us/cpp/cpp/alignment-cpp-declarations?view=msvc-140).

The alignment of a structure is the maximum alignment of any individual member, and the alignment of an array is the same as the alignment of one of the elements of the array: [https://learn.microsoft.com/en-us/cpp/build/x64-software-conventions?view=msvc-140#x64-aggregate-and-union-layout](https://learn.microsoft.com/en-us/cpp/build/x64-software-conventions?view=msvc-140#x64-aggregate-and-union-layout). KCD is a 64-bit program: the x64 conventions of MSVC therefore apply.

For each data member's address to be a multiple of its type's alignment, the compiler inserts "padding" (unused bytes) between members when needed.

_Caveat: the structure layout can also be altered by "packing". A `#pragma pack(1)` directive or the `/Zp1` compiler option, for example, removes all padding. There is no `#pragma pack` directive in `Code/CryEngine/CryAction/Serialization/XMLCPBin/XMLCPB_Common.h`, but we cannot tell which compiler options were used. Therefore we will assume default packing (which is sensible) and advance. If save files disprove our assumption, we can always backtrack and test a different configuration. Reverse engineering is a trial-and-error process._ 

The first data member (`m_fileTypeCheck`) is automatically aligned because it is at offset 0, so we do not need to worry about it.

Next is the MD5 signature char array. Its alignment is the alignment of a `char`, 1 byte. Its address offset is 4 (after the first 4 bytes of `m_fileTypeCheck`). 4 is a multiple of 1, so no padding is needed before it.

Next is `m_tags`, which is an instance of `struct SStringTable`. Its alignment is then the alignment of `uint32`, that is `unsigned int` ([unsigned does not affect size and alignment](https://eel.is/c++draft/basic.fundamental#3)), so its alignment is 4 bytes. Its offset is 20 (4 + 16). 20 is a multiple of 4, so no padding is needed.

Next are `m_attrNames` and `m_strData`, also instances of `SStringTable`. We already found that the alignment of `SStringTable` is 4 bytes, and its size is 4 + 4 = 8. Each new member starts 8 bytes after the previous one, so its offset stays a multiple of 4 by construction. Their offsets are respectively 28 and 36, both multiples of 4. Alignment is preserved, so no padding is needed.

Next come the 4 `uint32` members: `m_numAttrSets`, `m_sizeAttrSets`, `m_sizeNodes`, `m_numNodes`. The "default" offset for `m_numAttrSets` is 44. Its alignment is 4 bytes. 44 is a multiple of 4. No padding is needed. As the size of a `uint32` is a multiple of its alignment, queuing those 4 members in memory will preserve alignment naturally. We do not need to compute that for each of them.

Last data member is `m_hasInternalError`. It is a bool so its alignment requirement is 1. Its default offset would be 44 + 4 x 4 = 60. 60 is a multiple of 1. No padding is needed before it.

Finally, we need to introduce another rule: ["Structure size must be an integral multiple of its alignment, which may require padding after the last member."](https://learn.microsoft.com/en-us/cpp/build/x64-software-conventions?view=msvc-140#x64-aggregate-and-union-layout). It is required for the memory-alignment property to be preserved in arrays.

Alignment of `SFileHeader` is 4 bytes (the largest alignment among its members), and its members add up to 61 bytes. 61 is NOT a multiple of 4. The smallest aligned size that would fit is 64 bytes. Therefore the compiler adds a padding of 3 bytes at the end of the structure. **`sizeof(SFileHeader)` should then be 64 bytes (assuming default packing).**

Now, back to this piece of code: it says the last 64 bytes of our save file should be a memory copy of `SFileHeader`.
```cpp
SFileHeader fileHeader;
pOSSaveReader->Seek(-int(sizeof(fileHeader)), IPlatformOS::ISaveReader::ESM_END);
ReadDataFromFileInternal(pOSSaveReader, &fileHeader, sizeof(fileHeader));
```

We can write a Python script that selects only the last 64 bytes of a given file:
```python
from argparse import ArgumentParser
from io import SEEK_END

parser = ArgumentParser()
parser.add_argument("savefile")
args = parser.parse_args()

with open(args.savefile, "rb") as file:
    file.seek(-64, SEEK_END)
    footer_bytes = file.read(64)

print(footer_bytes.hex(" "))
```

With the work we have done (sizes and alignment), we also know exactly how to cut this byte stream!

The first 4 bytes are the value of `m_fileTypeCheck`:
```python
m_fileTypeCheck = footer_bytes[:4]
print(f"m_fileTypeCheck = {m_fileTypeCheck}")
```

Run on an actual KCD save file, it prints:
```
m_fileTypeCheck = b'0XBP'
```

`b'0XBP'` is the Python representation of a bytes object: it decodes every byte as the matching ASCII character (when printable). And `'0XBP'` looks suspiciously similar to the default value of `m_fileTypeCheck`, as defined in the constructor of `SFileHeader`:
```cpp
static const uint FILETYPECHECK = 'PBX0';

SFileHeader()
{
    memset(this, 0, sizeof(*this));
    m_fileTypeCheck = FILETYPECHECK;
}
```

`'0XBP'` is `'PBX0'` backwards, and this is not a coincidence. It could be explained by the fact that this multicharacter literal is actually stored as a `uint32` ([MSVC encodes the leftmost character in the most significant byte](https://learn.microsoft.com/en-us/cpp/cpp/string-and-character-literals-cpp?view=msvc-140#microsoft-specific)), and then numbers are stored in memory in little-endian byte order on x86-64 platforms. This means that the most significant byte of the number is stored as the last byte. Said differently, bytes are in reverse order.

This is already strong evidence that we are on the right track to extract and decode the footer from a save file, because it would be very unlikely to find these bytes at that specific position by chance.

Next should be `m_MD5Signature`, a 16-byte array. Array elements are simply concatenated in memory. Since we know that it is an MD5 hash, we won't display each array element separately, because that would not make sense. It is customary to display a hash in its hexadecimal form:
```python
m_MD5Signature = footer_bytes[4:4+16]
print(f"m_MD5Signature = {m_MD5Signature.hex()}")
```

Next is `m_tags`, an instance of `SStringTable`. This structure has no alignment padding, so it is just its 2 members `m_numStrings` and `m_sizeStringData` concatenated in memory. Both look like normal numbers (a count and a size), so they are displayed as such. (And we decode them in little-endian byte order!)
```python
m_tags = footer_bytes[20:20+8]
m_tags_m_numStrings = int.from_bytes(m_tags[:4], byteorder="little", signed=False)
m_tags_m_sizeStringData = int.from_bytes(m_tags[4:], byteorder="little", signed=False)
print(f"m_tags = {{m_numStrings: {m_tags_m_numStrings}, m_sizeStringData: {m_tags_m_sizeStringData}}}")
```

Then we can duplicate that logic for `m_attrNames` and `m_strData`:
```python
m_attrNames = footer_bytes[28:28+8]
m_attrNames_m_numStrings = int.from_bytes(m_attrNames[:4], byteorder="little", signed=False)
m_attrNames_m_sizeStringData = int.from_bytes(m_attrNames[4:], byteorder="little", signed=False)
print(f"m_attrNames = {{m_numStrings: {m_attrNames_m_numStrings}, m_sizeStringData: {m_attrNames_m_sizeStringData}}}")

m_strData = footer_bytes[36:36+8]
m_strData_m_numStrings = int.from_bytes(m_strData[:4], byteorder="little", signed=False)
m_strData_m_sizeStringData = int.from_bytes(m_strData[4:], byteorder="little", signed=False)
print(f"m_strData = {{m_numStrings: {m_strData_m_numStrings}, m_sizeStringData: {m_strData_m_sizeStringData}}}")
```

Next we have those 4 `uint32`:
```cpp
uint32 m_numAttrSets;
uint32 m_sizeAttrSets;
uint32 m_sizeNodes;
uint32 m_numNodes;
```

Again, these are plain whole numbers:
```python
m_numAttrSets = footer_bytes[44:44+4]
print(f"m_numAttrSets = {int.from_bytes(m_numAttrSets, byteorder='little', signed=False)}")
m_sizeAttrSets = footer_bytes[48:48+4]
print(f"m_sizeAttrSets = {int.from_bytes(m_sizeAttrSets, byteorder='little', signed=False)}")
m_sizeNodes = footer_bytes[52:52+4]
print(f"m_sizeNodes = {int.from_bytes(m_sizeNodes, byteorder='little', signed=False)}")
m_numNodes = footer_bytes[56:56+4]
print(f"m_numNodes = {int.from_bytes(m_numNodes, byteorder='little', signed=False)}")
```

And finally we have the boolean `m_hasInternalError`. It is a single byte, so we do not have to worry about endianness.
```python
m_hasInternalError = footer_bytes[60:60+1]
print(f"m_hasInternalError = {bool.from_bytes(m_hasInternalError)}")
```

Let's not forget the last 3 bytes, which are just padding. They should all be zero because the constructor of `SFileHeader` ensures that.
```python
trailing_padding = footer_bytes[61:61+3]
print(f"trailing padding = {trailing_padding.hex(' ')}")
```

Everything put together will give an output similar to this:
```
m_fileTypeCheck = b'0XBP'
m_MD5Signature = 5d139adcdb1cc97b232fbb66df415c45
m_tags = {m_numStrings: 0, m_sizeStringData: 0}
m_attrNames = {m_numStrings: 0, m_sizeStringData: 0}
m_strData = {m_numStrings: 0, m_sizeStringData: 0}
m_numAttrSets = 0
m_sizeAttrSets = 0
m_sizeNodes = 0
m_numNodes = 0
m_hasInternalError = False
trailing padding = 00 00 00
```

In conclusion, even though the fields after the MD5 signature are all zero (which tells us very little about whether we decoded them correctly), we have 2 strong markers:
1. the first member decoded to '0XBP' in every tested save file;
2. at the MD5 signature address, non-zero bytes *typically* fill the whole span, without a leading or a trailing sequence of zeros. Also their values change drastically from one save to another in a seemingly chaotic fashion (like noise), which is an important property of a hash.

That is evidence that the last 64 bytes of a KCD save file follow the `SFileHeader` data structure, at least partly. Also, finding `b'0XBP'` exactly 64 bytes before the end of the file confirms that the footer structure is exactly 64 bytes long, and therefore that the default-packing assumption holds. And last, we can also conclude that KCD saves are not encrypted, at least not the footer.

Here is the binary layout of the footer, in an informal grammar, as we understand it so far:
```
# legend:
# byte span: [<size in bytes> | <label>: <primitive or defined type>]
# padding: [<size in bytes> | ...]
# type definition: <type name> := (<byte span> | <padding>){1..*}
# integer byte order is little-endian

string-table :=
    [4 | numStrings: unsigned integer]
    [4 | sizeStringData: unsigned integer]

footer :=
    [ 4 | fileTypeCheck: unsigned integer]  # expected value: 0x50425830 (1346525232), stored as bytes 30 58 42 50 ("0XBP")
    [16 | MD5Signature: bytes]
    [ 8 | tags: string-table]
    [ 8 | attrNames: string-table]
    [ 8 | strData: string-table]
    [ 4 | numAttrSets: unsigned integer]
    [ 4 | sizeAttrSets: unsigned integer]
    [ 4 | sizeNodes: unsigned integer]
    [ 4 | numNodes: unsigned integer]
    [ 1 | hasInternalError: boolean]
    [ 3 | ...]
```

A refined, ready-to-use version of the script above is available in [`read_footer.py`](read_footer.py).


#### Decoding the rest of the save loading logic

Now back to the `CReader::ReadBinaryFile` function in `Code/CryEngine/CryAction/Serialization/XMLCPBin/Reader/XMLCPB_Reader.cpp`.

Lines 249-251 show that the save bytes' integrity is verified. This verification only happens on Windows (see lines 29-31 in `XMLCPB_Common.h`).
```cpp
#ifdef XMLCPB_CHECK_FILE_INTEGRITY
    m_errorReading = CheckFileCorruption(pOSSaveReader, fileHeader, m_totalSize);
#endif
```

In `CheckFileCorruption` (lines 304-354), we can see that:
1. First it checks  the size of the save. It must be more than the size of the footer (`SFileHeader`, 64 bytes).
2. Then the MD5 signature is computed on all the save's bytes (after decryption, if any), including the footer, but with the MD5 signature's 16 bytes all zeroed. If this hash is not byte-for-byte equal to the hash embedded in the footer, it fails.

At line 253 it moves the cursor to the beginning of the file again.

Then, at lines 255-259, it verifies that the `m_fileTypeCheck` member of the decoded `SFileHeader` is equal to its default value, `'PBX0'`, otherwise it aborts reading. It confirms that `'PBX0'` is an identity marker of the footer, and that we MUST find it every time.

##### The "nodes buffer"

Continuing forward, lines 263-265 fill a buffer via the "buffer reader" (`SBufferReader m_buffer`):
```cpp
m_nodesDataSize = fileHeader.m_sizeNodes;
m_numNodes = fileHeader.m_numNodes;
m_buffer.ReadFromFile(*this, pOSSaveReader, fileHeader.m_sizeNodes);
```

Digging into `SBufferReader::ReadFromFile`, we can see that it allocates new memory for its buffer using its `m_pHeap` member. The constructor of `CReader` shows that this pointer is shared between those two objects. After allocating memory it calls back `CReader::ReadDataFromFile` with a pointer to the start of its newly allocated buffer.

`CReader::ReadDataFromFile` checks the engine's CVar `g_XMLCPBUseExtraZLibCompression`:
- If enabled it will decompress blocks of bytes using zlib until the next `m_sizeNodes` bytes are all decompressed. Each block has a header (`SZLibBlockHeader`), which carries information about its size and whether it is compressed or not. Raw or decompressed data is stored in an intermediate buffer named `m_pZLibBuffer`. Header bytes are not copied over.
- If disabled, bytes are copied as-is in memory via `ReadDataFromFileInternal`, which we already analyzed earlier.

Note: `g_XMLCPBUseExtraZLibCompression` is enabled by default, as seen in `Code/CryEngine/CryAction/CryActionCVars.cpp` at line 60.

In the end, the raw or decompressed data is stored in `SBufferReader::m_pBuffer`. This buffer holds something called "nodes", even though we don't know what it is yet.

##### The "string tables"

Immediately after, lines 266-268 read the 3 "string tables" mentioned in `SFileHeader`, of type `CStringTableReader`.
```cpp
m_tableTags.ReadFromFile(*this, pOSSaveReader, fileHeader.m_tags);
m_tableAttrNames.ReadFromFile(*this, pOSSaveReader, fileHeader.m_attrNames);
m_tableStrData.ReadFromFile(*this, pOSSaveReader, fileHeader.m_strData);
```

`m_tableTags` is an instance of `CStringTableReader`. Digging into its `ReadFromFile` method:
1. It allocates new memory to house the `m_numStrings` string addresses.
2. It gets those string addresses (`FlatAddr`) by reading the next `sizeof(FlatAddr) * m_numStrings` bytes through `CReader::ReadDataFromFile`.
3. It appears to swap byte order for all string addresses. But reading lines 256-282 in `XMLCPB_Common.h` shows that it actually does nothing at all.
4. It uses its buffer reader (`SBufferReader`) to allocate memory in the heap for those "strings" data, then hands off to `CReader::ReadDataFromFile` again to read the next `m_sizeStringData` bytes.

The same applies for `m_tableAttrNames` and `m_tableStrData`.

##### The "attribute sets table"

Next, line 269 reads the "table of attribute sets":
```cpp
m_tableAttrSets.ReadFromFile(*this, pOSSaveReader, fileHeader);
```

`m_tableAttrSets` is an instance of `CAttrSetTableReader`. Digging into its `ReadFromFile` method:
1. It gets its `m_numAttrs` by reading the next `sizeof(uint8) * m_numAttrSets` bytes through `CReader::ReadDataFromFile`. It is a table of the number of attributes per set (source: line 20 in `XMLCPB_AttrSetTableReader.cpp`).
2. It gets its `m_setAddrs` by reading the next `sizeof(FlatAddr16) * m_numAttrSets` bytes through `CReader::ReadDataFromFile`. It is a table of the addresses of attribute sets (source: method `GetHeaderAttr`, lines 32-41 in `XMLCPB_AttrSetTableReader.cpp`).
3. It uses its buffer reader (`SBufferReader`) to read the next `m_sizeAttrSets` bytes which are the "attribute sets" data.

##### The "node addresses table"

Next, line 270:
```cpp
CreateNodeAddressTables();
```

This method parses each node from `CReader`'s buffer using `CNodeLiveReader` just to get the address of the next one (presumably because nodes are variable-length and need to be parsed in order to tell where they start and end). Those addresses are stored in `m_nodesAddrTable`. Node objects are just discarded.

Finally, `CReader::ReadBinaryFile` "activates" the root node (we do not know what it means, and that is probably unimportant at that step), and "touches" the file to mark it as the most recent loaded savegame (could be used for the "Continue" button in the main menu).

##### Conclusion

All the data-loading steps described above depend on fields (`m_sizeNodes`, `m_numNodes`, `m_numAttrSets`, `m_sizeAttrSets` etc.) that are all zeros in the save files of our sample. It would mean that, according to CryEngine's savegame loading code, those save files should be empty apart from their 64-byte footer, which is obviously untrue because they typically weigh more than 5 MiB and they are recognized by the game. So it looks like KCD does not strictly comply with CryEngine's XMLCPB save format, or maybe just not this one from version 5.7.

#### Decoding the rest of the binary

So, we cannot use most of the footer's data to decode the rest of the binary save file... which is annoying. Yet the presence of the footer in all tested KCD saves hints that we are on the right track.

All the data-loading functions that we studied earlier rely on `CReader::ReadDataFromFile` to get their bytes before interpreting them. In particular, if enabled it decompresses the payload block by block using zlib. This processing step is independent of any later cutting and interpretation of the bytes, so we can try to work it out first.

Let's assume that zlib compression is indeed enabled in KCD, and look at what `CReader::ReadDataFromZLibBuffer` does in that case. At lines 173-174, we can see that it expects to find a header structure (`SZLibBlockHeader`, defined in `XMLCPB_Common.h` at lines 90-95) at the start of a compressed block:
```cpp
SZLibBlockHeader blockHeader;
ReadDataFromFileInternal(pOSSaveReader, &blockHeader, sizeof(blockHeader));
```

Using the same rules that we detailed in the first part of this guide, we can compute that `SZLibBlockHeader` takes 8 bytes in memory (2 x uint32, alignment of 4). If KCD saves are compressed like CryEngine does, we should find `m_compressedSize` at offset 0 and `m_uncompressedSize` at offset 4.

In an example save:
- `m_compressedSize`: `D0 20 00 00`, which translates as `8400` in uint32 little-endian.
- `m_uncompressedSize`: `00 80 00 00`, which translates as `32768` in uint32 little-endian.

To interpret those values, we need to move forward in `CReader::ReadDataFromZLibBuffer`, at line 177:
```cpp
bool isCompressedData = blockHeader.m_compressedSize != SZLibBlockHeader::NO_ZLIB_USED;
```

It means that the following block data is raw (uncompressed) if `m_compressedSize` equals `0xffffffff`.

In our example that is not the case. So we can expect the block to span 8400 bytes after its header. And after those 8400 bytes, we should find another block header structure. That second block header would be:
- `m_compressedSize`: `71 1B 00 00`, which translates as `7025` in uint32 little-endian.
- `m_uncompressedSize`: `00 80 00 00`, which translates as `32768` in uint32 little-endian.

That is fitting! The fact that `m_uncompressedSize` would always be 32768 would be very coherent: one would split the raw payload into blocks of the same size before compressing them, so the compressed size could vary but the uncompressed size would always be the same by design, apart from the trailing block.

Following the same logic three more times gives comparable and consistent results, with `m_uncompressedSize` always equal to `00 80 00 00`. But it could still be chance. However, line 50 in `XMLCPB_Common.h` defines the `XMLCPB_ZLIB_BUFFER_SIZE` constant as 32768. We will not go into detail about it, but we can find evidence in `CReader` that it is the maximum size of a decompressed block. This makes chance unlikely.

This Python script automates finding these block headers:
```python
from argparse import ArgumentParser
from io import SEEK_SET
import os

FOOTER_SIZE = 64  # in bytes
ZLIB_BLOCK_HEADER_SIZE = 8  # in bytes
NO_ZLIB_USED_FLAG = 0xffffffff

parser = ArgumentParser()
parser.add_argument("savefile")
args = parser.parse_args()

file_size = os.stat(args.savefile).st_size
offset: int = 0  # the next block offset
block_i: int = 0

with open(args.savefile, "rb") as file:
    while offset <= (file_size - FOOTER_SIZE - ZLIB_BLOCK_HEADER_SIZE):
        file.seek(offset, SEEK_SET)
        block_header_bytes = file.read(ZLIB_BLOCK_HEADER_SIZE)
        compressed_size = int.from_bytes(block_header_bytes[:4], byteorder="little", signed=False)
        uncompressed_size = int.from_bytes(block_header_bytes[4:], byteorder="little", signed=False)
        block_size = compressed_size if compressed_size != NO_ZLIB_USED_FLAG else uncompressed_size

        print(f"Block {block_i}, offset {hex(offset)}")
        print(f"  m_compressedSize = {compressed_size}")
        print(f"  m_uncompressedSize = {uncompressed_size}")

        offset += ZLIB_BLOCK_HEADER_SIZE + block_size
        block_i += 1
```

The crucial question we must answer now is: do those bytes actually decompress correctly using zlib?

First, let's check how CryEngine decompresses them, at line 186:
```cpp
bool ok = gEnv->pSystem->DecompressDataBlock(m_pZLibCompressedBuffer, blockHeader.m_compressedSize, m_pZLibBuffer, uncompressedLength);
```

It calls `CSystem::DecompressDataBlock`, which in turn calls zlib's `uncompress` function. In Python, the equivalent is `zlib.decompress()`.

We can modify the Python script like so:
```python
import zlib
...

with open(args.savefile, "rb") as file:
    while offset <= (file_size - FOOTER_SIZE - ZLIB_BLOCK_HEADER_SIZE):
        ...

        print(f"Block {block_i}, offset {hex(offset)}")
        print(f"  m_compressedSize = {compressed_size}")
        print(f"  m_uncompressedSize = {uncompressed_size}")

        if compressed_size != NO_ZLIB_USED_FLAG:
            try:
                decompressed_bytes = zlib.decompress(file.read(block_size))
                print("  zlib decompression OK")
                if len(decompressed_bytes) != uncompressed_size:
                    print("  \033[31mDeclared uncompressed size does not check out\033[0m")
            except zlib.error as e:
                print(f"  \033[31mzlib decompression failed! {e}\033[0m")

        offset += ZLIB_BLOCK_HEADER_SIZE + block_size
        block_i += 1
```

It checks that blocks decompress without errors using zlib, and that their decompressed size equals what was declared in the header.

We should also add this check at the end, to ensure that the last block finishes exactly where the file footer starts.
```python
with open(args.savefile, "rb") as file:
    while offset <= (file_size - FOOTER_SIZE - ZLIB_BLOCK_HEADER_SIZE):
        ...

    if offset < (file_size - FOOTER_SIZE):
        print("\033[31mLast block's declared size leaves a few trailing bytes before the footer!\033[0m")
    elif offset > (file_size - FOOTER_SIZE):
        print("\033[31mLast block's declared size overlaps the footer!\033[0m")
```

If we run this script on our sample saves, it finds no errors at all. We now have the proof that the rest of the binary payload consists of blocks of zlib-compressed data, as described in CryEngine's code.

*Note: inspecting each zlib block shows that all of them start with those 2 bytes: `78 5E` (if compressed). It is a strong marker of zlib, as it is a header that tells the compression mode ([see Wikipedia's List of file signatures](https://en.wikipedia.org/wiki/List_of_file_signatures), and [RFC 1950 section 2.2 "Data format"](https://www.rfc-editor.org/info/rfc1950/#section-2)).*

A refined, ready-to-use version of the script above is available in [`read_zlib_blocks.py`](read_zlib_blocks.py).
