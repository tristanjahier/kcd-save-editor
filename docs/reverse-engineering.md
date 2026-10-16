# Reverse-engineering the binary format of Kingdom Come: Deliverance save files

> [!NOTE]
> This document was not written by an AI, and it is also not based on the findings of any AI, as opposed to [the initial research notes](initial-ai-research/reverse-engineering.md). AI was only used to proofread it and review the methodology.
> This guide follows my journey as a reverse-engineering beginner.
> It is not a final specification of the format of Kingdom Come: Deliverance saves. Instead, it justifies, step by step, how I came to understand the binary format.
> In the rest of the guide, "we" invites you, the reader, to follow the investigation with me.
>
> This project is not affiliated with or endorsed by Warhorse Studios, Deep Silver or Crytek. Kingdom Come: Deliverance and CryEngine are trademarks of their respective owners.

This guide bases its investigation on a sample of over a dozen actual save files made on the Windows version of Kingdom Come: Deliverance (the first one) version 1.9.6+.

Saved games are `.whs` files located at `%USERPROFILE%\Saved Games\kingdomcome\saves\playline<N>`.

## 1. Inspecting the game engine source code

Our first lead is the game engine. Game engines may offer tools to serialize the state of the game world, and in the case of an open-world game like Kingdom Come: Deliverance, it could be useful to save the state of hundreds of NPCs (their locations, statistics and inventories), the contents of chests, the progress of quests and objectives, the items dropped on the ground, etc.

It is publicly known that Kingdom Come: Deliverance was built on CryEngine. The game's [Wikipedia page (English)](https://en.wikipedia.org/wiki/Kingdom_Come:_Deliverance) reports that [Warhorse Studios licensed CryEngine 3 to develop their first game](https://www.cryengine.com/news/view/warhorse-studios-licensed-cryengine-reg-to-develop-rpg).

CryEngine 3 is a proprietary engine, its code is not public, and in 2026 it is hard to find any resources for that version anyway. CryEngine was open-sourced ("source-available" to be accurate) as of version 5, though, and it is possible that the game serialization/save code did not change. The source code of CryEngine 5 used to be public on GitHub, but as of 2026 the repository is no longer freely accessible. Instead, [you need to create a cryengine.com account and a GitHub account, then request access to the source code](https://github.com/CRYTEK/CRYENGINE_ReadMe).

---

From now on, we will consider that we have been granted access to the source code of CryEngine 5 on GitHub. The reference version is 5.7.1 (the only one Crytek still distributes as of October 2026).

> [!IMPORTANT]
> The CryEngine code excerpts quoted in this guide are copyrighted by Crytek GmbH. They are kept short, limited to the relevant lines, and quoted only to explain the save format. The full source code is only available from Crytek, as described above.

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

### 1.1. Decoding the SFileHeader structure

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


### 1.2. Unraveling the rest of the save loading logic

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

#### 1.2.1. The "node buffer"

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

#### 1.2.2. The "string tables"

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

#### 1.2.3. The "attribute set table"

Next, line 269 reads the "table of attribute sets":
```cpp
m_tableAttrSets.ReadFromFile(*this, pOSSaveReader, fileHeader);
```

`m_tableAttrSets` is an instance of `CAttrSetTableReader`. Digging into its `ReadFromFile` method:
1. It gets its `m_numAttrs` by reading the next `sizeof(uint8) * m_numAttrSets` bytes through `CReader::ReadDataFromFile`. It is a table of the number of attributes per set (source: line 20 in `XMLCPB_AttrSetTableReader.cpp`).
2. It gets its `m_setAddrs` by reading the next `sizeof(FlatAddr16) * m_numAttrSets` bytes through `CReader::ReadDataFromFile`. It is a table of the addresses of attribute sets (source: method `GetHeaderAttr`, lines 32-41 in `XMLCPB_AttrSetTableReader.cpp`).
3. It uses its buffer reader (`SBufferReader`) to read the next `m_sizeAttrSets` bytes which are the "attribute sets" data.

#### 1.2.4. The "node address table"

Next, line 270:
```cpp
CreateNodeAddressTables();
```

This method parses each node from `CReader`'s buffer using `CNodeLiveReader` just to get the address of the next one (presumably because nodes are variable-length and need to be parsed in order to tell where they start and end). Those addresses are stored in `m_nodesAddrTable`. Node objects are just discarded.

Finally, `CReader::ReadBinaryFile` "activates" the root node (we do not know what it means, and that is probably unimportant at that step), and "touches" the file to mark it as the most recent loaded savegame (could be used for the "Continue" button in the main menu).

#### 1.2.5. Conclusion

All the data-loading steps described above depend on fields (`m_sizeNodes`, `m_numNodes`, `m_numAttrSets`, `m_sizeAttrSets` etc.) that are all zeros in the save files of our sample. It would mean that, according to CryEngine's savegame loading code, those save files should be empty apart from their 64-byte footer, which is obviously untrue because they typically weigh more than 5 MiB and they are recognized by the game. So it looks like KCD does not strictly comply with CryEngine's XMLCPB save format, or maybe just not this one from version 5.7.

### 1.3. Too much for zlib blocks 🐇

So, we cannot use most of the footer's data to decode the rest of the binary save file... which is annoying. Yet the presence of the footer in all tested KCD saves hints that we are on the right track.

All the data-loading functions that we studied earlier rely on `CReader::ReadDataFromFile` to get their bytes before interpreting them. In particular, if enabled it decompresses the payload block by block using zlib. This processing step is independent of any later cutting and interpretation of the bytes, so we can try to work it out first.

Let's assume that zlib compression is indeed enabled in KCD, and look at what `CReader::ReadDataFromZLibBuffer` does in that case. At lines 173-174, we can see that it expects to find a header structure (`SZLibBlockHeader`, defined in `XMLCPB_Common.h` at lines 90-95) at the start of a compressed block:
```cpp
SZLibBlockHeader blockHeader;
ReadDataFromFileInternal(pOSSaveReader, &blockHeader, sizeof(blockHeader));
```

Using the same rules that we detailed in §1.1, we can compute that `SZLibBlockHeader` takes 8 bytes in memory (2 x uint32, alignment of 4). If KCD saves are compressed like CryEngine does, we should find `m_compressedSize` at offset 0 and `m_uncompressedSize` at offset 4.

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

### 1.4. Trying to read the payload as a node buffer anyway

Now that we know that KCD save files are a sequence of compressed zlib blocks (except for the footer), the natural thing to do is to decompress the whole payload and to analyze it.

For brevity we will not go into detail on the Python implementation, but the [`read_zlib_blocks.py`](read_zlib_blocks.py) script has a `--decompress` option that will create a new file next to the input save file, named after it with a `.decompressed.bin` extension, and containing all decompressed bytes, without the file footer.

Let's take for example this dump of the first 192 bytes of a decompressed save payload (offsets are decimal):
```
    | 00 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31
----+------------------------------------------------------------------------------------------------
 00 | 14 00 00 00 F5 01 4E 01 00 00 0D 00 3E 01 00 00 00 00 00 00 01 00 00 00 10 64 70 67 00 00 00 00 
 32 | 72 61 74 61 6A 65 00 30 7C 31 7C 40 73 75 62 63 68 61 70 74 65 72 5F 32 39 38 5F 6E 61 6D 65 7C 
 64 | 40 6F 62 6A 65 63 74 69 76 65 5F 53 61 76 65 6E 61 6D 65 5F 31 7C 40 6C 6F 63 61 74 69 6F 6E 5F 
 96 | 53 6B 61 6C 69 63 65 7C 31 37 33 35 34 31 38 38 39 36 7C 32 38 2F 31 32 2F 32 30 32 34 20 32 31 
128 | 3A 34 38 7C 30 2E 30 35 36 38 38 32 7C 00 40 73 75 62 63 68 61 70 74 65 72 5F 32 39 38 5F 6E 61
160 | 6D 65 7C 40 6F 62 6A 65 63 74 69 76 65 5F 53 61 76 65 6E 61 6D 65 5F 31 00 C8 00 00 00 C8 00 00
```

Inspecting this decompressed payload in a hexadecimal viewer immediately shows a lot of readable strings (decoded as ANSI characters). For example, this sequence of 153 bytes starting at offset 32:
```
rataje�0|1|@subchapter_298_name|@objective_Savename_1|@location_Skalice|1735418896|28/12/2024 21:48|0.056882|�@subchapter_298_name|@objective_Savename_1�
```

Let's break it down:
- "rataje" is the Czech name for Rattay.
- "0" and "1" look like booleans.
- "@subchapter_298_name", "@objective_Savename_1" and "@location_Skalice" look like localized string IDs.
- "28/12/2024 21:48" is definitely a date.
- 1735418896 is a big integer that could be a timestamp. A quick check confirms that it is a UNIX timestamp of the date above.
- "0.056882" is a decimal number (represented as a string!).
- The pipe separators "|" hint at a string-encoded data structure.

We are definitely on track!

---

In §1.2.1 we saw that CryEngine expects the first "section" of the payload to be the "node buffer". But it does not parse the data on its own just yet. It does that after loading all data, in `CReader::CreateNodeAddressTables` (line 437). Inside, the most interesting part is the construction of a `CNodeLiveReader` object, and the call to its method `ActivateFromCompact`.

In `Code/CryEngine/CryAction/Serialization/XMLCPBin/Reader/XMLCPB_NodeLiveReader.cpp` at line 190 we can see that the code expects once again a header for each node. Here, it is the first 2 bytes, decoded as a `uint16`. The next lines suggest that this header is actually holding multiple flags that can be read with bit masking. Looking up those bit masks brings us back to `XMLCPB_Common.h`, at lines 177-225. There, a comment suggests that `CNodeLiveWriter::Compact` has an understandable description of the format of those nodes.

`CNodeLiveWriter::Compact` can be found at lines 267-450 in `Code/CryEngine/CryAction/Serialization/XMLCPBin/Writer/XMLCPB_NodeLiveWriter.cpp`, and the aforementioned comment is right above.

It says for the header:
```
2 bytes  -> header, split into:
    15 -> 1 = has attrs
    14 -> 1 = children are right before
    13 ->    -| 0-2 number of children. 3 = more than 2 children
    12 ->    -|
    11 ->  -|
    10 ->  -| 2 bits high for the attrSet id
    -> 10 bits  (9-0)  -> Tag ID
```

It means that the bit of weight 2^15 (that we will call bit15 from now on) is a boolean flag for "has attributes". Bit14 is a flag for "its children are right before". Bit13 and bit12 hold a number: it is the number of children, capped to 3. The next 2 lines – and it is really confusing – actually describe a different bit span: bit11 and bit10 hold the 2 most significant bits of the "attribute set ID". And the last 10 bits, bit9 to bit0, hold the "tag ID".

In our example we find bytes `14 00` at offset 0. They decode as `0x0014` (little-endian):
```
00000000 00010100
```

This would decode as:
- the node does not have attributes;
- its children are NOT before it;
- it has 0 children;
- 00 are the two most significant bits of its attribute set ID (which tells us nothing as-is);
- its tag ID is 20.

This is entirely possible. We cannot conclude from that header alone.

The same comment describes a couple of other byte spans, which are absent when the node has no children nor attributes, and in the end says:
```
[...]  -> attr data
```

What is that attribute data? It is compacted at lines 428-431 in `XMLCPB_NodeLiveWriter.cpp`:
```cpp
for (int a = 0; a < m_attrs.size(); ++a)
{
    m_attrs[a].Compact();
}
```

A simple loop over all attributes of the node, calling `Compact` on each one. The implementation of `CAttrWriter::Compact` is in `Code/CryEngine/CryAction/Serialization/XMLCPBin/Writer/XMLCPB_AttrWriter.cpp` at lines 396-540.

The code teaches us that "string" attributes (`case DT_STR` line 414) are not actually stored in compacted nodes. Only the string ID is encoded. There is an exception for strings longer than 1024 characters (see `CAttrWriter::Set` at lines 70-75) which are stored as raw data (`case DT_RAWDATA` line 528): the bytes are stored inline, prefixed by a `uint32` holding the size of the span. It means that our "node buffer" should rarely contain text, and if so, it should be encoded as raw data.

Yet, the readable string mentioned earlier (`rataje�0|1|@subchapter_298_name|...`) was found only 32 bytes into the payload. The longest run of readable characters is `0|1|@subchapter_298_name|@objective_Savename_1|@location_Skalice|1735418896|28/12/2024 21:48|0.056882|`, so only 102 characters, and the four preceding bytes (as `uint32`) do not decode as a valid size for this string either. We could also consider that the string starts at `rataje` instead, but the 4 preceding bytes decode as 0, which is also not the size of the string. This seems contradictory with it being part of the node buffer.

This string is long and meaningful, so we can also drop the hypothesis that those bytes decode to readable text by chance.

Finally, if we consider the case where this text is contained in a larger raw data attribute, we should find a node header declaring that it has attributes. As we saw earlier, it would mean that we should find a span of 2 bytes whose most significant bit is 1 in little-endian order. Said differently, we should find a 2-byte span ranging from `?? 80` to `?? FF`, where `?` can be any hex digit. In our example, the only byte that is between `80` and `FF` that we could find before the string starts is `F5`, at offset 4. For `F5` to be the most significant byte of the node header, it would mean that the header starts with `00 F5`, at offset 3. This leaves only 3 bytes before it. In our example the first 2 bytes are `14 00`, meaning that this first node has no children and no attributes. Therefore the first node stops at 2 bytes. This leaves only 1 byte before offset 3, and as we said, a node header takes at least 2 bytes, so this is a contradiction. We can conclude that the text we see cannot be part of a node attribute.

If this text is not part of the node buffer, it means that the node buffer takes at most 32 bytes in our example. Since each node takes at least 2 bytes, we have room for at most 16 nodes. This is highly unlikely.

So... again, a dead end. It strongly suggests that Kingdom Come: Deliverance only uses the envelope of CryEngine's XMLCPB save format (the 64-byte footer and the zlib blocks). We must change our approach.

## 2. Inspecting the raw bytes

If the game engine's source code cannot explain the payload, we have to do it the hard way: inspect the raw bytes and try to make sense of them.

For reference, we will work on the same example as before:
```
    | 00 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31
----+------------------------------------------------------------------------------------------------
 00 | 14 00 00 00 F5 01 4E 01 00 00 0D 00 3E 01 00 00 00 00 00 00 01 00 00 00 10 64 70 67 00 00 00 00 
 32 | 72 61 74 61 6A 65 00 30 7C 31 7C 40 73 75 62 63 68 61 70 74 65 72 5F 32 39 38 5F 6E 61 6D 65 7C 
 64 | 40 6F 62 6A 65 63 74 69 76 65 5F 53 61 76 65 6E 61 6D 65 5F 31 7C 40 6C 6F 63 61 74 69 6F 6E 5F 
 96 | 53 6B 61 6C 69 63 65 7C 31 37 33 35 34 31 38 38 39 36 7C 32 38 2F 31 32 2F 32 30 32 34 20 32 31 
128 | 3A 34 38 7C 30 2E 30 35 36 38 38 32 7C 00 40 73 75 62 63 68 61 70 74 65 72 5F 32 39 38 5F 6E 61
160 | 6D 65 7C 40 6F 62 6A 65 63 74 69 76 65 5F 53 61 76 65 6E 61 6D 65 5F 31 00 C8 00 00 00 C8 00 00
```

Here is some context about the save that our example payload is extracted from. Context is super important because for a savegame, we should probably find traces of the save timestamp, the in-game location, how many hours have been played etc.

- saved on 2024-12-28 at 21:48 (Europe/Paris);
- language setting: French;
- total playtime: a couple of minutes (it is the first automatic save of the game after the intro);
- location is Skalitz (English), or Skalice (French, Czech);
- in-game time: day 1, 10am.

At this point we don't have many clues except that some readable text starts at offset 32 (line 2). However, there are a few rules to consider:

- Integers are usually stored on 1, 2, 4 or 8 bytes, respectively as `int8`/`uint8`, `int16`/`uint16`, `int32`/`uint32` and `int64`/`uint64`.
- Numeric IDs and counters tend to be rather small numbers. As humans, we rarely manipulate huge numbers, for example 4,294,967,295 which is the largest value a `uint32` can hold. This is definitely not a hard rule though.
- Byte offsets, sizes and timestamps are exceptions to the previous point. Our example decompressed payload is 25+ MiB long; its last offset is 26,715,956. A contemporary timestamp is greater than 1,700,000,000 seconds, or 1,700,000,000,000 milliseconds (which does not fit in 32 bits).
- A consequence of numbers tending to be rather small is that the most significant bytes of **positive** integers are often `00`. In little-endian, which is the convention we've seen everywhere so far, it means that their last bytes are zeros. For example, `26 1C 00 00` as a `uint32` is 7206. For **negative** integers, which are represented as signed integers with [two's complement](https://en.wikipedia.org/wiki/Two%27s_complement), they tend to be `FF`. For example, `EC F6 FF FF` as an `int32` is -2324.
- Strings are usually a variable-length chain of bytes ending with a `NUL` character (`00`).
- When data structures are plain copies of C or C++ objects they can include padding, as described in §1.1.

### 2.1. Carving out the general layout

We can try selecting arbitrary byte spans and look at what they decode to. We can start cutting everything into 4-byte spans:

| Offset (dec) | Bytes         | Observations                             |
| -----------: | ------------- | :--------------------------------------- |
|            0 | `14 00 00 00` | Looks like a small positive integer: 20. |
|            4 | `F5 01 4E 01` | Could be 21,889,525. |
|            8 | `00 00 0D 00` | Could be 851,968. |
|           12 | `3E 01 00 00` | Looks like a small positive integer: 318. |
|           16 | `00 00 00 00` | Could be 0. Could be padding. |
|           20 | `01 00 00 00` | Could be 1. Or could be a boolean on one byte. The zeros could also be padding. |
|           24 | `10 64 70 67` | Could be 1,735,418,896. It is a huge number, but it does look a lot like a contemporary timestamp in seconds. |
|           28 | `00 00 00 00` | Could be 0. Could be padding. |
|           32 | `72 61 74 61` | Decodes to "rata", which are the first 4 characters of "rataje". |

Offset 32 is the start of 3 NUL-terminated coherent strings: `"rataje"`, `"0|1|@subchapter_298_name|@objective_Savename_1|@location_Skalice|1735418896|28/12/2024 21:48|0.056882|"` and `"@subchapter_298_name|@objective_Savename_1"`. As we already said earlier, these strings are meaningful, they are readable and make a lot of sense in the game context and in general. Therefore, we can say for sure that span [32-184] is a sequence of 3 strings.

Let's then focus on the bytes before.

The small integers look like good interpretations but... that's all. Nothing to conclude yet.

The most interesting one is the timestamp at [24-27]. It decodes to `1735418896` or `2024-12-28 20:48:16`. Well well well... this is literally the date at which the reference save was created, in UTC. The timestamp also appears in the following text, and the date too, as "28/12/2024 21:48", which is the local time.

Now let's cut the payload into 2-byte spans instead, stopping at the timestamp we just pinned down:

| Offset (dec) | Bytes   | Observations                             |
| -----------: | ------- | :--------------------------------------- |
|            0 | `14 00` | 20                                       |
|            2 | `00 00` | 0. Padding?                              |
|            4 | `F5 01` | 501                                      |
|            6 | `4E 01` | 334                                      |
|            8 | `00 00` | 0. Padding?                              |
|           10 | `0D 00` | 13                                       |
|           12 | `3E 01` | 318                                      |
|           14 | `00 00` | 0. Padding?                              |
|           16 | `00 00` | 0. Padding?                              |
|           18 | `00 00` | 0. Padding?                              |
|           20 | `01 00` | 1                                        |
|           22 | `00 00` | 0. Padding?                              |

However, nothing guarantees that the cutting must be regular. It makes exhaustive exploration complex (for a human at least). Fortunately, we don't have that many bytes to sort because we know that at offset 24 we have a timestamp, therefore we must find a layout that looks fitting, and that stops exactly where the timestamp starts.

Remembering the rules we listed before, two zero bytes in a row are often the sign of a small integer on 4 bytes. If we mix this with the objective of prioritizing small integers, we could then organize the first 24 bytes like that:

| Offset (dec) | Bytes         | Observations                             |
| -----------: | ------------- | :--------------------------------------- |
|            0 | `14 00 00 00` | 20                                       |
|            4 | `F5 01`       | 501                                      |
|            6 | `4E 01 00 00` | 334                                      |
|           10 | `0D 00`       | 13                                       |
|           12 | `3E 01 00 00` | 318                                      |
|           16 | `00 00 00 00` | 0                                        |
|           20 | `01 00 00 00` | 1                                        |

That might be overfitting, but what could those numbers mean?

They could be IDs, they could be offsets, they could be sizes but they could also just be game counters. Given the size of the payload, `uint16` values are less likely to be offsets, because they could not point too far in the file (max value of a `uint16` is 65,535).

Here follow a few tests. "Offset" here means specifically "absolute offset, relative to the start". "size" will be tested as "a span of N bytes starting immediately after the size declaration".

| What is tested?  | Observations |
| ---------------- | ------------ |
| 20 as an offset  | Offset 20 is our "1" value. Nothing to conclude. |
| 20 as a size     | Lands on the timestamp at offset 24. It looks fitting. |
| 501 as a size    | Lands in the middle of a string: `"burnt_farms_01_rataje_north_burnt"`, impossible because a string is one coherent structure. |
| 334 as an offset | Lands right after a string. Plausible. |
| 334 as a size    | Lands on offset 344. Possible. Nothing stands out at first glance. |
| 13 as a size     | Lands in the middle of the timestamp at offset 25. Invalid. |
| 318 as an offset | Lands in the middle of a string: `"Le lot des femmes"`. Invalid.
| 318 as a size    | Lands right after a string. Plausible. |

20 (`14 00 00 00`, offset 0) could be a header's size. And the next 20 bytes would be the header's contents. That fits with the beginning of the timestamp.

We can rule out the two `uint16` (501 and 13) as sizes, as they cover no coherent span.

What about 334 and 318?

If both are sizes, then they cannot describe two different and consecutive spans, as the 318-byte span would be entirely contained within the 334-byte span. Instead, this would be possible if they describe nested structures. However there would then be a 10-byte gap to explain after the 318-byte span and before the end of the 334-byte span:
```
10 00 04 00 00 00 01 00 00 00
```

We shall naively try to apply the same pattern, which fits in size:
```
10 00  | 04 00 00 00 | 01 00 00 00
uint16 |    uint32   |     ???
```

`10 00` decodes to 16. `04 00 00 00` decodes to 4. And there are exactly 4 bytes left before the end of the 334-byte span, which fits the "size" meaning.

Note that this is incompatible with two other hypotheses: "20 is the size of a header" and "334 is an offset". But this potential pattern looks more promising, because it repeats and leads us further.

At this point, testing by hand in a basic hexadecimal viewer can start to feel cumbersome. Fortunately, a lot of tools exist to ease the work of reverse engineers.

[ImHex](https://github.com/WerWolv/ImHex) is one of them. It allows us to declare patterns with [its domain-specific language](https://docs.werwolv.net/pattern-language), and see them matched in real-time in its hexadecimal viewer.

Here is an ImHex pattern that matches the structure that we may have uncovered:
```hexpat
import std.mem;

struct UndeterminedPattern {
    u16 thing;
    u32 size;
    std::mem::Bytes<size> content;
};

UndeterminedPattern my_pattern[while($ + 6 <= std::mem::size())] @ 0x04;
```

`u16 thing` is our undetermined `uint16`. `u32 size` is the following `uint32` that we identified as "size". `std::mem::Bytes<size> content` covers the undetermined content that comes after. The last line declares that the pattern starts at offset 4 (`@ 0x04`), and that it shall be repeated while the current offset has not exceeded the 6th-to-last byte of the payload. Note that this script does not cover nested structures.

**Running this pattern with ImHex on the decompressed payload shows that it repeats 3 times and the last match finishes exactly one byte before the end.** And the trailing byte is `FF`.

It seems to fit, but the best way to confirm that we have actually found a real pattern is to test it on other save files.

| Save Name                | Pattern Matches                                                                           | Leading Bytes | Trailing Bytes | 
| ------------------------ | ----------------------------------------------------------------------------------------- | ------------- | :------------: |
| permanent001 (reference) | 3 matches. (thing: 501; size: 334), (thing: 500; size: 26,715,600), (thing: 509; size: 0) | `14 00 00 00` | `FF`           |
| permanent004             | 3 matches. (thing: 501; size: 334), (thing: 500; size: 26,645,788), (thing: 509; size: 0) | `14 00 00 00` | `C8`           |
| permanent011             | 3 matches. (thing: 501; size: 333), (thing: 500; size: 26,218,464), (thing: 509; size: 0) | `14 00 00 00` | `00`           |
| permanent013             | 3 matches. (thing: 501; size: 347), (thing: 500; size: 26,321,604), (thing: 509; size: 0) | `14 00 00 00` | `00`           |
| save508                  | 3 matches. (thing: 501; size: 273), (thing: 500; size: 31,734,077), (thing: 509; size: 0) | `14 00 00 00` | `00`           |
| save669                  | 3 matches. (thing: 501; size: 281), (thing: 500; size: 31,838,512), (thing: 509; size: 0) | `14 00 00 00` | `BE`           |
| switch51141              | 3 matches. (thing: 501; size: 281), (thing: 500; size: 31,638,195), (thing: 509; size: 0) | `14 00 00 00` | `00`           |

Those results are rich! Here are the takeaways:

1. The tested pattern works on 7 save files of 3 different types (what those types are is still unknown).
2. There are always 3 consecutive spans starting exactly at offset 4 and finishing at the second-to-last offset.
3. The "things" never change, at a given position.
4. The sizes are always of the same magnitude, at a given position.
5. The last match's size is always zero.
6. The four leading bytes are always the same.
7. The trailing byte seems not to follow any obvious pattern.

With all this evidence we can say confidently that we actually found a real pattern in the binary layout.

The fact that "things" are stable makes one think that it is a kind of identifier for the span.

The thing-509 span could be an unused item, or a marker for the end of the payload.

Now we need to test whether this pattern nests or not. The first instance we spotted (thing: 501; size: 334) at offset 4 seemed to have two similar consecutive child patterns: (thing: 13; size: 318) and (thing: 16; size: 4).

```hexpat
import std.mem;

fn pattern_fits(u128 offset, u128 limit) {
    if (offset + 6 > limit)
        return false;
        
    u32 size = std::mem::read_unsigned(offset + 2, 4);
    return offset + 6 + size <= limit;
};
  
struct UndeterminedPattern {
    u16 thing;
    u32 size;
    UndeterminedPattern children[while(pattern_fits($, addressof(this) + 6 + size))];
    
    if ($ < addressof(this) + 6 + size) {
        std::mem::Bytes<addressof(this) + 6 + size - $> rest;
    }
};

UndeterminedPattern my_pattern[while($ + 6 <= std::mem::size())] @ 0x04;
```

There are three changes:

1. `UndeterminedPattern children[while(pattern_fits($, addressof(this) + 6 + size))];` replaces the former `content`. It introduces pattern recursion. Children are parsed as long as `pattern_fits` returns `true`.
2. function `pattern_fits` checks that a candidate child pattern would fit within its parent's limits.
3. `rest` covers the remainder that could not be parsed as children.

If we run that modified script on the decompressed payload with ImHex again, it shows that the pattern is indeed recursive. The parsed tree is immense.

- The first root span, (thing: 501; size: 334), has only two direct descendants: the two that we already identified: (thing: 13; size: 318) and (thing: 16; size: 4).
- The second root span, (thing: 500; size: 26,715,600), has 3 children: (thing: 507; size: 32,812), (thing: 503; size: 7,415,945) and (thing: 502; size: 19,266,825). They have many descendants of their own, which we won't detail.
- The third root span, (thing: 509; size: 0), has no children, which is normal because it has a size of zero.

All non-empty spans in the first 3 levels of the tree have either children or a "rest" (remainder bytes) but not both, which means that children add up exactly to their parent's size. That is a good sign because it means that the apparent nesting was not a stroke of luck. Take the second root span for example, which announces a size of 26,715,600 bytes: its 3 children announce sizes of 32,812, 7,415,945 and 19,266,825 respectively. With the 6 bytes of each header, they add up exactly to their parent's size: (6 + 32,812) + (6 + 7,415,945) + (6 + 19,266,825) = 26,715,600. That is highly unlikely by chance.

Deeper in the tree (under the second root span), some spans have both children and a rest. Most of them are parents of (thing: 0; size: 0). For example, at offset 0x72BC11 (7519249), span (thing: 778; size: 96) has one child (thing: 0; size: 0), and 90 more bytes as "rest". The remaining cases are parents of (thing: N>0; size: 0).

Given that zero bytes are very common in a binary payload (zero values, high bytes of very small integers, padding), those empty spans (2 bytes of whatever plus 4 zero bytes) are likely accidental matches.

Now we must test that on multiple other saves as well:

| Save Name                | Results                                                                                   |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| permanent001 (reference) | Described above. 6,051 spans with both children and rest, mostly (thing: 778).            |
| permanent004             | Nesting pattern holds. Children of 2nd root span fit its size exactly: 3x6 + 32,812 + 7,444,102 + 19,168,856 = 26,645,788. 6,043 spans with both children and rest, mostly (thing: 778). |
| permanent011             | Nesting pattern holds. Children of 2nd root span fit its size exactly: 3x6 + 32,812 + 6,890,077 + 19,295,557 = 26,218,464. 5,753 spans with both children and rest, mostly (thing: 778). |
| permanent013             | Nesting pattern holds. Children of 2nd root span fit its size exactly: 3x6 + 32,812 + 6,855,885 + 19,432,889 = 26,321,604. 5,765 spans with both children and rest, mostly (thing: 778). |
| save508                  | Nesting pattern holds. Children of 2nd root span fit its size exactly: 3x6 + 32,812 + 8,298,184 + 23,403,063 = 31,734,077. 5,761 spans with both children and rest, mostly (thing: 778). |
| save669                  | Nesting pattern holds. Children of 2nd root span fit its size exactly: 3x6 + 32,812 + 8,217,480 + 23,588,202 = 31,838,512. 5,928 spans with both children and rest, mostly (thing: 778). |
| switch51141              | Nesting pattern holds. Children of 2nd root span fit its size exactly: 3x6 + 32,812 + 8,183,235 + 23,422,130 = 31,638,195. 5,920 spans with both children and rest, mostly (thing: 778). |

Note: numbers concerning spans with both children and rest can be retrieved using [jq](https://jqlang.org/) on an export of ImHex results in JSON:
```sh
imhex --pl format -i mysave.decompressed.bin -p pattern.hexpat -f json -o mysave.decompressed.json
jq '[.. | objects | select((.children | length) > 0 and has("rest"))] | length' mysave.decompressed.json
jq '[.. | objects | select((.children | length) > 0 and has("rest")) | .thing] | group_by(.) | map({thing: .[0], count: length}) | sort_by(-.count) | .[]' mysave.decompressed.json
```

We can conclude confidently that this pattern is actually nested, and covers the vast majority of the payload, even though we still need to explain those empty spans and those that have both children and rest.

Another interesting result is that the "thing" field is not unique: its value can be shared by multiple spans, even as siblings. Here is a jq query to group spans by thing and count (only when >1):
```sh
jq '[.. | objects | select(has("thing")) | .thing] | group_by(.) | map({thing: .[0], count: length}) | map(select(.count > 1)) | sort_by(-.count) | .[]' mysave.decompressed.json
```

If the "thing" field looks like an identifier but is not unique, then it is more like a class, a category or a type.

**The structure we uncovered is actually a well-known one: [Type-Length-Value](https://en.wikipedia.org/wiki/Type%E2%80%93length%E2%80%93value) (or Tag-Length-Value).** Generic data container formats like [IFF](https://en.wikipedia.org/wiki/Interchange_File_Format) and [RIFF](https://en.wikipedia.org/wiki/Resource_Interchange_File_Format) use this structure too. Those two formats call the byte spans "chunks", and they can be nested.

_From now on, for consistency, we will then call the spans matching this pattern "chunks", their class "type", and their size "length"._

Here is the updated ImHex pattern:
```hexpat
import std.mem;

fn chunk_fits(u128 offset, u128 limit) {
    if (offset + 6 > limit)
        return false;
        
    u32 length = std::mem::read_unsigned(offset + 2, 4);
    return offset + 6 + length <= limit;
};
  
struct Chunk {
    u16 type;
    u32 length;
    Chunk children[while(chunk_fits($, addressof(this) + 6 + length))];
    
    if ($ < addressof(this) + 6 + length) {
        std::mem::Bytes<addressof(this) + 6 + length - $> rest;
    }
};

Chunk my_pattern[while($ + 6 <= std::mem::size())] @ 0x04;
```

A refined, ready-to-use Python script that parses the chunk tree from a decompressed payload is available in [`parse_decompressed_payload.py`](parse_decompressed_payload.py).

And here is the binary layout of the decompressed payload as we understand it so far:
```
# legend (in addition to the footer's grammar):
# .<label> as a byte span size references the <label> field in the same type, which must come earlier and be an unsigned integer.

chunk :=
    [      2 | type: unsigned integer]
    [      4 | length: unsigned integer]
    [.length | value: chunk{1..*} or bytes]

payload :=
    [4 | undetermined1: unsigned integer]  # the 4 leading bytes
    [? | chunks: chunk{3}]  # the 3 root chunks that we found every time
    [1 | undetermined2: bytes]  # the trailing byte
```

What remains to be figured out:

- whether type 0 and/or length 0 are valid chunks;
- how to read chunk values when they are not nested chunks;
- whether child chunks can cohabit with other data, and whether those children must come first or not;
- what `undetermined1` and `undetermined2` are for.

### 2.2. Decoding the first chunk

We got the general layout right. Now let's get back to the first root chunk we inspected (type: 501), and in particular its first child (type: 13).

#### 2.2.1. The save timestamp

We already settled that span [24-27] is a timestamp. Additionally, in all sample saves, the next 4 bytes are always all zeros. We supposed that it could be a 0 value as a `uint32`, or padding.

There is another possible interpretation: those are the high bytes of a 64-bit timestamp. Indeed, timestamps were traditionally stored using a _signed integer on 32 bits_ (`time_t`), which cannot store [a date beyond 2038-01-19 03:14:07 UTC](https://en.wikipedia.org/wiki/Year_2038_problem) (2^31 - 1 seconds). In modern days, as this date is not very far anymore, developers prefer representing timestamps on 64 bits. [MSVC's documentation says that by default it is a 64-bit signed integer](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/time-time32-time64?view=msvc-140).

There is actually a decisive test that we can do quite easily:

1. change the date in Windows' settings past 2038-01-19 03:14:07 UTC;
2. launch KCD and load a sample game;
3. save;
4. quit the game and inspect this save to see if the 8 bytes decode to the correct date.

If we do it, we see that the game works normally, and that the save appears with its correct date (year 2039) in the loading menu, meaning that the game supports it well.

However, any date up to 2106-02-07 06:28:15 UTC can be stored on just 32 bits if it is read as an unsigned integer. The better proof would be to set the date past that limit, and see if the 4 next bytes actually change. 

It may not be possible to set the date to 2126 in Windows' date & time settings, though it can be done via a PowerShell command run in administrator mode:
```pwsh
Set-Date -Date ([datetime]::new(2126, 6, 15, 10, 0, 0, [DateTimeKind]::Utc).ToLocalTime())
```

Using the same test protocol, we can demonstrate that the game still runs normally, creates a save on the date set, and that inspecting its decompressed payload shows a value on more than 4 bytes, which translates correctly to the date set. For example: `54 8F 47 26 01 00 00 00` which decodes as "2126-06-15 10:00:52 UTC".

We proved that span [24-31] is a single 64-bit timestamp.

Caveat: setting a date prior to 1970-01-01 systematically crashes the game, so we cannot test how the game handles negative timestamps.

#### 2.2.2. The two leading integers

In chunk (type: 13), before the timestamp there are 8 bytes ([16-23]) that look like two 32-bit integers.

Let's check their values in our sample saves:

| Save Name                | Bytes [16-19]     | Bytes [20-23]         |
| ------------------------ | ----------------- | --------------------- |
| permanent001 (reference) | `00 00 00 00` (0) | `01 00 00 00` (1)     |
| permanent004             | `00 00 00 00` (0) | `04 00 00 00` (4)     |
| permanent011             | `00 00 00 00` (0) | `0B 00 00 00` (11)    |
| permanent013             | `00 00 00 00` (0) | `0D 00 00 00` (13)    |
| save508                  | `02 00 00 00` (2) | `FC 01 00 00` (508)   |
| save669                  | `02 00 00 00` (2) | `9D 02 00 00` (669)   |
| switch51141              | `06 00 00 00` (6) | `C5 C7 00 00` (51141) |

For bytes [20-23], the results are obvious: it is the save number.

For bytes [16-19], it looks like each naming scheme has its own number. We should verify that on other saves including all known naming schemes:

| Save Name   | Bytes [16-19]     | Bytes [20-23]         |
| ----------- | ----------------- | --------------------- |
| save573     | `02 00 00 00` (2) | `3D 02 00 00` (573)   |
| autosave692 | `01 00 00 00` (1) | `B4 02 00 00` (692)   |
| autosave694 | `01 00 00 00` (1) | `B6 02 00 00` (694)   |
| exit        | `05 00 00 00` (5) | `A6 02 00 00` (678)   |


It confirms that each save naming scheme is bound to a different number.

Using the game as a source of truth, and inspecting the save entries in the game menu, we can determine what those naming schemes stand for:

| Naming Scheme | Scheme code  | Description                                                                           |
| :------------ | :----------: | :------------------------------------------------------------------------------------ |
| permanentNNN  | 0            | Automatic saves at important moments of the main story line. Those seem to never be deleted, as their name suggests. |
| autosaveNNN   | 1            | Automatic saves made during side quests and secondary objectives, or, oddly enough, manual saves made by sleeping in a bed or on a pallet. |
| saveNNN       | 2            | Manual saves, made by drinking a Saviour Schnapps.                                    |
| exit          | 5            | A save made when the player clicks "Save & Quit" in the main menu. Overwritten on each new "Save & Quit". The save number is not part of the file name, confirming that there is only one "exit" save at a time. |
| switchNNNNN   | 6            | Trickier, because it does not appear in-game. But by comparing its creation time and the immediate next save, we can determine that it is created just before entering the story of Theresa in Skalitz (DLC 4 "A Woman's Lot"). Its save number does not follow the rest. |

Those naming schemes indicate in fact different types of saves. In our samples, codes 3 and 4 never appeared.

Conclusion: span [16-19] is the **save type code**, and span [20-23] is the **save number**.

#### 2.2.3. The strings

Next in chunk (type: 13), starting at offset 32, we have the NUL-terminated strings that we already mentioned in §1.4:

| Save | Decoded strings |
| --- | --- |
| permanent001 | <ol><li>rataje</li><li>0\|1\|@subchapter_298_name\|@objective_Savename_1\|@location_Skalice\|1735418896\|28/12/2024 21:48\|0.056882\|</li><li>@subchapter_298_name\|@objective_Savename_1</li></ol> |
| permanent004 | <ol><li>rataje</li><li>0\|4\|@subchapter_313_name\|@objective_Savename_1\|@location_Skalice\|1735498563\|29/12/2024 19:56\|3.119182\|</li><li>@subchapter_313_name\|@objective_Savename_1</li></ol> |
| permanent011 | <ol><li>rataje</li><li>0\|11\|@subchapter_370_name\|@objective_Savename_1\|@location_Rovne\|1735511361\|29/12/2024 23:29\|4.558275\|</li><li>@subchapter_370_name\|@objective_Savename_1</li></ol> |
| permanent013 | <ol><li>rataje</li><li>0\|13\|@subchapter_382_name\|@objective_39219_Savename\|@location_Mlyn_Rataje\|1735515642\|30/12/2024 00:40\|5.747488\|</li><li>@subchapter_382_name\|@objective_39219_Savename</li></ol> |
| save508 | <ol><li>rataje</li><li>2\|508\|@subchapter_586_name\|\|@ui_countryside\|1755694805\|20/08/2025 15:00\|136.540985\|</li><li>_(empty)_</li></ol> |
| save646 | <ol><li>rataje_dlc4</li><li>2\|646\|@subchapter_672_name\|\|@ui_countryside\|1757799018\|13/09/2025 23:30\|169.340225\|</li><li>_(empty)_</li></ol> |
| autosave692 | <ol><li>rataje</li><li>1\|692\|@subchapter_348_name\|\|@location_pribyslavice_newHomes\|1758050379\|16/09/2025 21:19\|185.985489\|</li><li>_(empty)_</li></ol> |
| autosave694 | <ol><li>rataje</li><li>1\|694\|@subchapter_348_name\|\|@location_Ledecko\|1758053283\|16/09/2025 22:08\|186.115067\|</li><li>_(empty)_</li></ol> |
| autosave786 | <ol><li>rataje</li><li>1\|786\|@subchapter_588_name\|@objective_36861_Savename\|@location_Mlyn_Rataje\|1769450839\|26/01/2026 19:07\|203.192307\|</li><li>@subchapter_588_name\|@objective_36861_Savename</li></ol> |
| switch51141 | <ol><li>rataje</li><li>6\|51141\|@subchapter_385_name\|\|@location_Mlyn_Rataje\|1757695927\|12/09/2025 18:52\|163.495087\|</li><li>_(empty)_</li></ol> |
| exit | <ol><li>rataje</li><li>5\|678\|@subchapter_348_name\|\|@location_Rataje\|1757978362\|16/09/2025 01:19\|181.004288\|</li><li>_(empty)_</li></ol> |

The first string is always "rataje" in all sample saves, except in saves made during the story of Theresa, where it is "rataje_dlc4". So it is very probably the name of the game level/map.

The second string is a vertical-bar-separated data structure. We need to break it down again and compare the values between different saves:

| Save         | 1 | 2     | 3                    | 4                         | 5                               | 6          | 7                | 8          |
| ------------ | - | ----: | -------------------- | ------------------------- | ------------------------------- | ---------- | ---------------- | ---------: |
| permanent001 | 0 |     1 | @subchapter_298_name | @objective_Savename_1     | @location_Skalice               | 1735418896 | 28/12/2024 21:48 | 0.056882   |
| permanent004 | 0 |     4 | @subchapter_313_name | @objective_Savename_1     | @location_Skalice               | 1735498563 | 29/12/2024 19:56 | 3.119182   |
| permanent011 | 0 |    11 | @subchapter_370_name | @objective_Savename_1     | @location_Rovne                 | 1735511361 | 29/12/2024 23:29 | 4.558275   |
| permanent013 | 0 |    13 | @subchapter_382_name | @objective_39219_Savename | @location_Mlyn_Rataje           | 1735515642 | 30/12/2024 00:40 | 5.747488   |
| save508      | 2 |   508 | @subchapter_586_name |                           | @ui_countryside                 | 1755694805 | 20/08/2025 15:00 | 136.540985 |
| save646      | 2 |   646 | @subchapter_672_name |                           | @ui_countryside                 | 1757799018 | 13/09/2025 23:30 | 169.340225 |
| autosave692  | 1 |   692 | @subchapter_348_name |                           | @location_pribyslavice_newHomes | 1758050379 | 16/09/2025 21:19 | 185.985489 |
| autosave694  | 1 |   694 | @subchapter_348_name |                           | @location_Ledecko               | 1758053283 | 16/09/2025 22:08 | 186.115067 |
| autosave786  | 1 |   786 | @subchapter_588_name | @objective_36861_Savename | @location_Mlyn_Rataje           | 1769450839 | 26/01/2026 19:07 | 203.192307 |
| switch51141  | 6 | 51141 | @subchapter_385_name |                           | @location_Mlyn_Rataje           | 1757695927 | 12/09/2025 18:52 | 163.495087 |
| exit         | 5 |   678 | @subchapter_348_name |                           | @location_Rataje                | 1757978362 | 16/09/2025 01:19 | 181.004288 |

Interpretations are quite easy:

1. The save type code that we uncovered in the previous section.
2. The save number that we also uncovered in the previous section.
3. A localized string key for the current "subchapter", probably the quest.
4. A localized string key for the current quest objective. Sometimes empty.
5. A localized string key for the current location.
6. The save timestamp.
7. The save timestamp as local date & time.
8. This one is ever growing with the save number (except the switch save). A quick check in game will reveal that it is the number of hours played.

Note that there is always a vertical bar after the last element, but none at the beginning. This might just be a quirk of the format, or a sign that a 9th element exists but is always empty.

Caveat: the timestamp in field 6 very likely goes through a 32-bit signed integer before serialization, because in the saves dated 2039 and 2126 (see §2.2.1) it reads -2092824325 (1903-09-07) and 642223956 (1990-05-09), respectively, when it should have been 2202142971 (2039-10-13) and 4937191252 (2126-06-15).

The third string is always present, but it is sometimes empty, consisting of just a NUL byte. When it is not empty, it simply repeats fields 3 and 4 from the second string. This one would probably require further investigation to be understood.

#### 2.2.4. The other strings

Next in chunk (type: 13) we can spot other NUL-terminated strings: `Tr��sors du pass��`, `L'essor du ph��nix`, `Les Galantes Aventures du Courtois Hans Capon`, `Mauvaise troupe`, `Le lot des femmes`. These happen to be all of Kingdom Come: Deliverance's playable DLCs, in French. The replacement characters indicate that they do not decode properly in ASCII; they must be decoded in UTF-8:

- Trésors du passé (Treasures of the Past)
- L'essor du phénix (From the Ashes)
- Les Galantes Aventures du Courtois Hans Capon (The Amorous Adventures of Bold Sir Hans Capon)
- Mauvaise troupe (Band of Bastards)
- Le lot des femmes (A Woman's Lot)

Before those DLC strings, there are always exactly 15 bytes:

| Save         | Bytes                                          |
| ------------ | ---------------------------------------------- |
| permanent001 | `C8 00 00 00 C8 00 00 00 00 05 00 01 00 00 00` |
| permanent004 | `C8 00 00 00 C8 00 00 00 01 05 00 01 00 00 00` |
| permanent011 | `C8 00 00 00 C8 00 00 00 01 05 00 01 00 00 00` |
| permanent013 | `C8 00 00 00 C8 00 00 00 01 05 00 01 00 00 00` |
| save508      | `C8 00 00 00 C8 00 00 00 01 05 00 01 00 00 00` |
| save646      | `C8 00 00 00 C8 00 00 00 01 05 00 01 00 00 00` |
| autosave692  | `C8 00 00 00 C8 00 00 00 01 05 00 01 00 00 00` |
| autosave694  | `C8 00 00 00 C8 00 00 00 01 05 00 01 00 00 00` |
| switch51141  | `C8 00 00 00 C8 00 00 00 01 05 00 01 00 00 00` |
| exit         | `C8 00 00 00 C8 00 00 00 01 05 00 01 00 00 00` |

They are all identical except for the first one where its 9th byte is `00` instead of `01`.

The DLC strings themselves are separated by other undetermined bytes, in that order:

- Trésors du passé
- `04 00 00 00`
- L'essor du phénix
- `08 00 00 00`
- Les Galantes Aventures du Courtois Hans Capon
- `09 00 00 00`
- Mauvaise troupe
- `0A 00 00 00`
- Le lot des femmes

The chunk terminates exactly after the last string. With hindsight, it probably means that the last 4 bytes of the 15-byte prefix should be associated with the first DLC title instead: `01 00 00 00` and "Trésors du passé".

Those separator byte spans are always 4 bytes, which looks like a 32-bit integer. They are surely not sizes, since they never correspond to the number of characters, nor bytes, of the string they precede. Also NUL-terminated strings typically do not need a size prefix. They could be IDs of the DLCs. A quick check on other saves shows that they never change, which strengthens that hypothesis.

What could be the first 11 bytes then?

`C8 00 00 00` as a 32-bit integer is 200. Twice. Still cryptic.

The fact that the 9th byte changes from `00` to `01`, but not its surrounding bytes, hints that it might be a boolean. The save where this byte is `00`, permanent001, is the only one of our samples that takes place before the village of Skalitz is attacked by the Cumans, so it could be a flag for that.

And the last two bytes, `05 00`, could simply be a 16-bit integer: 5, exactly the number of DLCs listed afterwards. DLCs can be installed individually, so a field containing the number of DLCs that follow would make sense. In fact, starting a new playline with one of the DLCs uninstalled confirms that the 16-bit integer is indeed the number of DLCs, and that the list contains only the currently installed DLCs.

#### 2.2.5. Summary of chunk (type: 13)

All things put together, here is the provisional shape of chunk (type: 13) in an informal grammar, as we understand it so far:

```
# legend (in addition to previous grammars):
# repeated group of byte spans: ( <span 1> <span 2> ... ){cardinality}
# .<label> as cardinality references the <label> field in the same type, which must come earlier and be an unsigned integer.
# primitive type string: NUL-terminated string (encoding can be specified in parentheses).

save-info := 
    [4 | save_type: unsigned integer]
    [4 | save_number: unsigned integer]
    [8 | timestamp: signed integer]
    [? | map: string]
    [? | serialized_info: string]
    [? | serialized_info_2: string]
    [4 | undetermined_1: unsigned integer]
    [4 | undetermined_2: unsigned integer]
    [1 | skalitz_burnt: boolean]  # provisional meaning
    [2 | dlc_count: unsigned integer]
    (
        [4 | dlc_id: unsigned integer]
        [? | dlc_title: string(utf8)]  # localized
    ){.dlc_count}
```

Note: it is the only chunk of type 13 across the whole payload.

#### 2.2.6. The little sibling (type: 16)

Across all sample saves, its length is always 4 bytes and its value `01 00 00 00`. It is the only chunk of type 16 across the whole payload.

A constant value tells us nothing about its meaning.

#### 2.2.7. The secret sibling (type: 17)

`save646` is our only sample from Theresa's story (DLC 4 "A Woman's Lot"), but the observations stated below hold for all the saves of that story that we could produce and check.

In `save646` there is an additional child under root chunk (type: 501): chunk (type: 17; length: 4). Its value is a 4-byte integer, `C5 C7 00 00`, which decodes to 51141. It is exactly the number of the latest "switch" save at that time.

Saves of Theresa's story are typically much smaller than the others, suggesting that they do not contain the state of the main storyline. When the player enters her storyline, no visible new entry appears in the loading menu. Yet, after finishing the DLC, the state of the main storyline is restored exactly as it was, even if the game was closed and restarted in between. So the main storyline must be stored somewhere.

A safe conclusion is that, when entering Theresa's story, the game creates a special "switch" save holding the state of the main storyline. That "switch" save's number is then referenced in DLC-specific saves, in chunk (type: 17), in order to restore the main storyline seamlessly after finishing the DLC.

#### 2.2.8. The new sibling (type: 14)

All saves created while the game has loaded mods have a special chunk (type: 14) to hold mod information. We do not need to go into too much detail for this one, as the layout is pretty obvious, and as no new knowledge is required to parse the bytes.

The first 4 bytes are a `uint32` holding the number of registered mods.

Then it is a series of NUL-terminated strings for each mod in that order:

1. the name of the mod folder
2. the mod name
3. the description
4. the author
5. the version
6. the version (again)

Fields 2 to 5 come from the `mod.manifest`.

Note: once a mod has been registered in a save, it will never disappear from subsequent saves, even if it has been uninstalled since. Also, each new version of a preexisting mod simply appends to the end of the list. In this regard it acts as a history of mods rather than a list of the mods loaded when the game was saved.

Caveat: in rare and abnormal circumstances, all these strings but the mod folder name can be empty and then consist of just a NUL character. When a folder exists in the game's Mods directory it is seen as a mod by the game, even if it is empty, as long as it is declared in `mod_order.txt` or this file does not exist.

#### 2.2.9. Conclusion

The root chunk (type: 501) is present in all saves. It consists of:

- Chunk (type: 13): Save information: number, type, timestamp, game level/map, the DLCs installed etc.
- Chunk (type: 16): Undetermined meaning.
- _OPTIONAL_ Chunk (type: 17): Present only when the save is from Theresa's storyline. Its value is the number of the "switch" save from the main storyline.
- _OPTIONAL_ Chunk (type: 14): Present when mods have been installed. It lists information about the registered mods.

A refined, ready-to-use Python script that reads the root chunk (type: 501) from a decompressed payload is available in [`read_save_metadata.py`](read_save_metadata.py).
