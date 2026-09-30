# How the KCD save format was reverse engineered

**Disclaimer:** the initial reverse-engineering work was done by an AI, in particular reading CryEngine's source code (to be exact: Lumberyard's) for reference and cutting the bytes into coherent structures. This guide was also written by that AI, to record everything it had learned. The format was then refined and widened over many (many!) iterations: I created new saves and playlines under controlled conditions and ran other tests in the game (reading values in its menus, provoking events, etc.), then fed my observations to that AI. Comparing saves that differed in a single known way helped clarify the meaning of many extracted values.

*A guide for developers who have never reverse engineered a binary format.*

*Kingdom Come: Deliverance* (KCD, Warhorse Studios, 2018) stores each saved game in an undocumented `.whs` file of 5 to 7 MB in the main open world. This guide shows how that format was worked out, with the goal of making the method reusable on other formats: how to recognize structure in raw bytes, how to test a guess rigorously, and where to find ground truth.

The work had one lucky break: KCD runs on CryEngine, and CryEngine's source code is public (as Amazon Lumberyard). The guide is organized accordingly:

- **[Refresher: byte order and floating-point numbers](#refresher-byte-order-and-floating-point-numbers),** because a hex dump makes little sense without them.
- **[Patterns in a hex dump](#patterns-worth-recognizing-in-a-hex-dump)** and **[the method in one page](#the-method-in-one-page):** the toolbox, in condensed form.
- **[Part 1: the CryEngine shell](#part-1-the-cryengine-shell).** The file's outer layer, and part of its content, matched line by line against the engine's source code.
- **[Part 2: what is specific to KCD](#part-2-reverse-engineering-what-is-specific-to-kcd).** Warhorse's own data, with no public source: a playbook of the techniques that decoded it.
- **[Part 3: format reference](#part-3-format-reference).** The whole format, as understood today, in simple pseudo-code.

The examples come from 8 reference saves of one playthrough, made with game versions 1.9.6 and 1.9.8 ([list](#reference-values)): all the bytes shown come from them, and the snippets print what they give on those 8. The format itself was checked on **all the saves of that playthrough**, Theresa's DLC level included. In-game tests added a few fresh saves, named where they are used.

---

## Contents

- [What you need](#what-you-need)
- [Refresher: byte order and floating-point numbers](#refresher-byte-order-and-floating-point-numbers)
- [Conventions](#conventions)
- [Patterns worth recognizing in a hex dump](#patterns-worth-recognizing-in-a-hex-dump)
- [The method in one page](#the-method-in-one-page)
- [The format at a glance](#the-format-at-a-glance)
- [Part 1: the CryEngine shell](#part-1-the-cryengine-shell)
  - [1.1 First look at the bytes](#11-first-look-at-the-bytes)
  - [1.2 Walking the blocks](#12-walking-the-blocks)
  - [1.3 The 64-byte footer and its MD5](#13-the-64-byte-footer-and-its-md5)
  - [1.4 Finding the writer in CryEngine's code](#14-finding-the-writer-in-cryengines-code)
  - [1.5 Reproducing the compression exactly](#15-reproducing-the-compression-exactly)
  - [1.6 KCD only kept the envelope](#16-kcd-only-kept-the-envelope)
  - [1.7 Engine metadata and sections](#17-engine-metadata-and-sections)
  - [1.8 Typed values and hashed names](#18-typed-values-and-hashed-names)
  - [1.9 GameState: CryEngine's entity data](#19-gamestate-cryengines-entity-data)
- [Part 2: what is specific to KCD](#part-2-reverse-engineering-what-is-specific-to-kcd)
  - [2.1 Guess a framing, then demand an exact fit](#21-guess-a-framing-then-demand-an-exact-fit)
  - [2.2 Look for a small header in front of a list](#22-look-for-a-small-header-in-front-of-a-list)
  - [2.3 Extend the rules until everything parses](#23-extend-the-rules-until-everything-parses)
  - [2.4 Use text as landmarks](#24-use-text-as-landmarks)
  - [2.5 Compare files](#25-compare-files)
  - [2.6 Ask the user of the program](#26-ask-the-user-of-the-program)
  - [2.7 Search for a known value in every encoding](#27-search-for-a-known-value-in-every-encoding)
  - [2.8 Reason about counters](#28-reason-about-counters)
  - [2.9 Recover hashed names from the program binary](#29-recover-hashed-names-from-the-program-binary)
  - [2.10 Mine the program's own files](#210-mine-the-programs-own-files)
  - [2.11 Validate with a second, strict reader](#211-validate-with-a-second-strict-reader)
- [Part 3: format reference](#part-3-format-reference)
- [Lessons learned](#lessons-learned)
- [Still unknown](#still-unknown)
- [Tools in this repository](#tools-in-this-repository)
- [Terms](#terms)
- [References](#references)

---

## What you need

- **The save files.** On Windows: `Saved Games\kingdomcome\saves\playline0` in your user folder.
- **A hex viewer.** The examples use `xxd` (shipped with Git for Windows, Linux and macOS). A hex editor such as [HxD](https://mh-nexus.de/en/hxd/) helps too: its *data inspector* decodes the bytes under the cursor as every integer and float type at once.
- **Python 3.** The snippets use only the standard library and build on each other: run them in order, in one session, from a folder holding the saves. [§2.8](#28-reason-about-counters) reads every save in it, so the outputs shown need the 8 reference saves alone.
- **Optional: the game installation**, for the field names ([§2.9](#29-recover-hashed-names-from-the-program-binary), used from [§1.9](#19-gamestate-cryengines-entity-data) on) and the translations ([§2.10](#210-mine-the-programs-own-files)). The snippets assume Steam's default folder, `C:\Program Files (x86)\Steam\steamapps\common\KingdomComeDeliverance`: adjust the paths if yours differs.
- **Optional: Perl**, to check the compression settings ([§1.5](#15-reproducing-the-compression-exactly)).

**The snippets, in order.** Each one uses those before it. Part 1 comes first for clarity, but from §1.7 on it shows what part 2's tools print: the chunk parser of §2.1 and, in §1.9, the field names of §2.9.

| Section | Adds |
|---|---|
| [Refresher](#refresher-byte-order-and-floating-point-numbers) | `struct` examples |
| [§1.2](#12-walking-the-blocks) | `read_whs()`: a save's bytes and its payload |
| [§1.3](#13-the-64-byte-footer-and-its-md5) | the MD5 check |
| [§1.8](#18-typed-values-and-hashed-names) | `fnv1()`, `walk()`: typed values |
| [§2.1](#21-guess-a-framing-then-demand-an-exact-fit) | `parse_chunks()`, `children()`, `node()`: the chunk tree |
| [§2.2](#22-look-for-a-small-header-in-front-of-a-list) | `header_candidates()` |
| [§2.5](#25-compare-files) | `layers()` |
| [§2.7](#27-search-for-a-known-value-in-every-encoding) | `find_number()`, `locate()` |
| [§2.8](#28-reason-about-counters) | `stats()` |
| [§2.9](#29-recover-hashed-names-from-the-program-binary) | `names`, `sections_of()`, `dump()` (needs the game) |
| [§2.10](#210-mine-the-programs-own-files) | `read_pak_file()` (needs the game) |
| [§2.11](#211-validate-with-a-second-strict-reader) | `Reader`, a building block for a strict reader |

---

## Refresher: byte order and floating-point numbers

### Byte order (endianness)

A multi-byte number can be stored most significant byte first (**big-endian**) or least significant byte first (**little-endian**). The same four bytes give very different numbers depending on the convention:

```
bytes in the file         d0 20 00 00
read as little-endian     0x000020d0  =          8,400
read as big-endian        0xd0200000  =  3,491,758,080
```

x86 processors are little-endian, and so is ARM as used in practice, so PC games write little-endian almost everywhere. Big-endian is common in network protocols ("network byte order") and in some file formats such as PNG and Java class files. Everything in KCD saves is little-endian.

A quick way to tell in a hex dump: most numbers in a file are small. In little-endian, a small `u32` has its zero bytes *after* the significant ones (`d0 20 00 00`). In big-endian, they come *before* (`00 00 20 d0`).

### Floating-point numbers (IEEE 754)

Numbers with a fractional part are almost always stored in the IEEE 754 format:

```
f32 (4 bytes):  1 sign bit | 8 exponent bits  | 23 mantissa bits
f64 (8 bytes):  1 sign bit | 11 exponent bits | 52 mantissa bits

value = (-1)^sign × 1.mantissa × 2^(exponent − bias)        bias: 127 for f32, 1023 for f64
```

Three `f32` values from the saves, as stored (little-endian) and decoded:

| Bytes in the file | Bits | Sign | Exponent | Mantissa | Value |
|---|---|---|---|---|---|
| `00 00 80 3f` | `0x3f800000` | 0 | 127 → 2⁰ | 1.0 | **1.0** |
| `00 00 50 40` | `0x40500000` | 0 | 128 → 2¹ | 1.625 | **3.25** |
| `00 00 b4 c2` | `0xc2b40000` | 1 | 133 → 2⁶ | 1.40625 | **−90.0** |

The practical consequence for reading a dump: **the most significant byte of a float (the last one, in little-endian) gives away its sign and order of magnitude.** It holds the sign bit and the top 7 bits of the exponent:

| Last byte of an `f32` | Value range |
|---|---|
| `3c` | 0.0078 to 0.031 |
| `3d` | 0.031 to 0.125 |
| `3e` | 0.125 to 0.5 |
| `3f` | 0.5 to 2 |
| `40` | 2 to 8 |
| `41` | 8 to 32 |
| `42` | 32 to 128 |
| `43` | 128 to 512 |
| `44` | 512 to 2,048 |
| `45` | 2,048 to 8,192 |
| `46`, `47` | 8,192 to 131,072 |
| `bc` to `c7` | the same ranges, negative |

So twelve bytes ending in `45`, `45` and `42` are very likely three floats of a few thousand, a few thousand and a few tens. In a save, `c9 c3 09 45 26 1f 33 45 20 98 9f 42` is indeed a position in the game world: (2204.24, 2865.95, 79.80).

An `f64` works the same way, with its sign and exponent in the last two bytes. The play time stored as `2a de a7 c5 4f 11 61 40` ends in `61 40`, so the exponent is `0x406` = 1030, i.e. 2⁷: a value between 128 and 256. It is 136.54098780428586.

Precision matters when comparing values. An `f32` holds about 7 significant digits, an `f64` about 16. The same play time converted to `f32` becomes 136.540985107..., which explains a detail of [§2.7](#27-search-for-a-known-value-in-every-encoding).

In Python, `struct` decodes both orders and both float sizes:

```python
import struct

raw = bytes.fromhex("d0200000")
print(struct.unpack("<I", raw)[0], struct.unpack(">I", raw)[0])  # 8400 3491758080 ("<" little-endian, ">" big-endian)

def f32_fields(raw4):
    """Sign, exponent and mantissa fields of a little-endian f32."""
    bits = struct.unpack("<I", raw4)[0]
    return bits >> 31, (bits >> 23) & 0xFF, bits & 0x7FFFFF

for hex_bytes in ("0000803f", "00005040", "0000b4c2"):
    raw = bytes.fromhex(hex_bytes)
    print(struct.unpack("<f", raw)[0], f32_fields(raw))
# 1.0 (0, 127, 0)
# 3.25 (0, 128, 5242880)
# -90.0 (1, 133, 3407872)
```

---

## Conventions

This notation is used throughout the guide:

| Notation | Meaning |
|---|---|
| `u8`, `u16`, `u32`, `u64` | unsigned integers of 1, 2, 4 and 8 bytes, little-endian |
| `s8`, `s16`, `s32`, `s64` | signed integers of the same sizes |
| `f32`, `f64` | IEEE 754 floats of 4 and 8 bytes |
| `cstr` | NUL-terminated UTF-8 text |
| `str16` | a `u16` length, then that many bytes of text (no NUL) |
| `byte[n]` | `n` raw bytes |
| `guid` | a 16-byte identifier |
| `X × n` | `n` items of kind `X`, one after the other |
| `[id]` | a chunk (see below) with this id |
| `#` | a comment |

A **chunk** is the building block of KCD's format: a `u16` id, a `u32` size, then `size` bytes of body. The body holds values or more chunks. This "tag-length-value" design lets a reader skip chunks it doesn't understand:

```
┌──────┬──────────┬───────────────────────────────────────────┐
│ id   │ size     │ body: `size` bytes                        │
│ u16  │ u32      │ values, or more chunks                    │
└──────┴──────────┴───────────────────────────────────────────┘
```

Chunk ids are numbers. The chunk names in this guide (`header`, `body`...) describe what was learned about their content; the saves don't store them.

---

## Patterns worth recognizing in a hex dump

Unknown data is rarely random. These patterns come up constantly, and all of them appear in KCD saves:

| You see | It often means |
|---|---|
| `78 01`, `78 5e`, `78 9c` or `78 da`, followed by noise | a zlib stream |
| a large region of uniform noise | compressed or encrypted data |
| `xx 00 00 00`, `xx xx 00 00` | a small little-endian `u32`: a size, count, id, type or version |
| a `u32` equal to the number of bytes left in a region | a size field, i.e. a nested structure |
| a `u32` equal to the number of items that follow | a count field |
| printable bytes ending with `00` | a C string (`cstr`) |
| a `u16`/`u32` equal to the length of the text right after it | a length-prefixed string |
| 4 bytes ending with `3c`–`47` or `bc`–`c7` | a plausible `f32` (see the [refresher](#floating-point-numbers-ieee-754)) |
| 8 bytes whose last byte is `3f` or `40` (`bf` or `c0` if negative) | a plausible `f64` between about 0.00003 and 131,072 |
| 16 random-looking bytes | an MD5, a GUID or a key |
| 4 random-looking bytes inside known structure | a hash or an id |
| a readable word, reversed (`0XBP`) | a multi-character constant or magic number written little-endian |
| the same byte pattern at regular intervals | an array of fixed-size records |

---

## The method in one page

Every discovery in this guide followed the same loop:

```
  observe the bytes ──► make a guess ──► write a strict parser for it ──► run it on every file
         ▲                                                                      │
         └──────────────── it failed somewhere: look there, refine ◄─────────────┘
```

**Not all evidence is equal.** From strongest to weakest:

1. **An exact fit over a large amount of data.** A parser consumes megabytes and stops exactly on the last byte. Wrong guesses don't survive this.
2. **Arithmetic that works out.** Declared sizes and counts match what follows, to the byte.
3. **Consistency across files.** The same rule holds in every sample.
4. **Plausible values.** Floats with sensible magnitudes, dates in the right year, counts that only grow.
5. **A single match in a single place.** Often a coincidence.

**Ground truth comes from outside the bytes:**

- the source code of any public component (here, the engine);
- strings inside the program binary (here, the field names of [§2.9](#29-recover-hashed-names-from-the-program-binary));
- the program's data files (here, translations and configuration);
- what the program displays, and what its user knows ([§2.6](#26-ask-the-user-of-the-program));
- controlled experiments: two files that differ by a single action ([§2.5](#25-compare-files)).

---

## The format at a glance

This is the destination; every piece is explained later.

**On disk**, the file is a series of compressed blocks followed by a footer:

```
.whs file
┌─────────┬─────────┬─────────┬─────┬─────────┬──────────────────┐
│ block 1 │ block 2 │ block 3 │ ... │ block N │ footer, 64 bytes │
└─────────┴─────────┴─────────┴─────┴─────────┴──────────────────┘

each block
┌─────────────────┬───────────────────┬──────────────────────────────────┐
│ compressed size │ uncompressed size │ zlib data                        │
│ u32             │ u32               │ ("compressed size" bytes)        │
└─────────────────┴───────────────────┴──────────────────────────────────┘

footer
┌─────────────┬──────────────────────────────┬────────────────────┐
│ "0XBP"      │ MD5 of the file              │ 44 zero bytes      │
│ 4 bytes     │ 16 bytes                     │                    │
└─────────────┴──────────────────────────────┴────────────────────┘
```

**Decompressed and joined**, the blocks form the **payload** (25 to 35 MB in the main open world):

```
block 1 data ──zlib──►  32,768 bytes ─┐
block 2 data ──zlib──►  32,768 bytes  ├──►  payload
   ...                                │
block N data ──zlib──►  the rest ─────┘
```

**The payload** is a tree of chunks:

```
u32 20
[501] header ─────────── save type and number, date, quest, location, play time, DLCs
│  ├─ [13] save info
│  ├─ [16] unknown (always 1)
│  ├─ [14] list of mods (only when mods are enabled)
│  └─ [17] number of the "switch" save holding the main open world state (only present inside a DLC level)
[500] body
│  ├─ [507] preload ────── on/off state of the level's "layers" (groups of world objects)
│  ├─ [503] engine ─────── CryEngine data: metadata, then sections (Timer ... GameState)
│  └─ [502] KCD modules ── Warhorse's data: characters, statistics, scripts, events, ...
[509] end marker (empty)
1 trailing byte (unknown, varies)
```

---

# Part 1: the CryEngine shell

## 1.1 First look at the bytes

```
$ xxd permanent001.whs | head -1
00000000: d020 0000 0080 0000 785e 9d5d 4993 24cb  . ......x^.]I.$.
```

Using the [patterns](#patterns-worth-recognizing-in-a-hex-dump):

- **`78 5e` at offset 8 is a zlib header** ([RFC 1950](https://www.rfc-editor.org/rfc/rfc1950): deflate, 32 KiB window, "fast" level). What follows looks like noise.
- **The 8 bytes before it are two small little-endian `u32`:** 8,400 and 32,768. 32,768 is 32 KiB, a classic buffer size.
- **Guess:** each block is `u32 compressed size`, `u32 uncompressed size`, then the zlib data.

## 1.2 Walking the blocks

The guess is tested on the whole file. If it's right, the blocks must decompress to the announced sizes and follow each other seamlessly.

```python
import zlib

def read_whs(path):
    """Return (file bytes, payload) of a .whs save."""
    data = open(path, "rb").read()
    footer_pos = len(data) - 64
    payload, pos = bytearray(), 0
    while pos < footer_pos:
        compressed_size, uncompressed_size = struct.unpack_from("<II", data, pos)
        block = zlib.decompress(data[pos + 8:pos + 8 + compressed_size])
        assert len(block) == uncompressed_size
        payload += block
        pos += 8 + compressed_size
    assert pos == footer_pos  # the blocks end exactly where a 64-byte trailer starts
    return data, bytes(payload)

data, payload = read_whs("permanent001.whs")
print(len(payload))  # 26715957
```

The guess holds: **816 blocks**, all decompressing to 32,768 bytes except the last. They end exactly 64 bytes before the end of the file, so there is a trailer. (This version already knows about it. The first attempt simply failed there, on a "block header" that made no sense.)

## 1.3 The 64-byte footer and its MD5

```
30 58 42 50 3a c2 30 c1 2e d9 ee 97 46 35 94 fe   0XBP:.0.....F5..
a7 55 73 48 00 00 00 00 00 00 00 00 00 00 00 00   .UsH............
00 00 00 00 ...                                   (44 zero bytes in total)
```

It holds a 4-byte magic `0XBP`, 16 random-looking bytes (an MD5, per the patterns table), then zeros. An MD5 of what? Trying the natural candidates is cheap:

```python
import hashlib

footer_pos = len(data) - 64
stored = data[footer_pos + 4:footer_pos + 20]
candidates = {
    "compressed blocks": data[:footer_pos],
    "decompressed payload": payload,
    "whole file, digest zeroed": data[:footer_pos + 4] + bytes(16) + data[footer_pos + 20:],
}
for label, blob in candidates.items():
    print(label, hashlib.md5(blob).digest() == stored)
# only "whole file, digest zeroed" prints True
```

**The footer holds the MD5 of the entire file, computed with the 16 digest bytes set to zero.** "Hash the whole file with the digest field zeroed" is a common convention for embedded checksums, so it's worth trying early.

## 1.4 Finding the writer in CryEngine's code

KCD runs on CryEngine, whose source is public in Amazon's fork [Lumberyard](https://github.com/aws/lumberyard). Searching it for code that writes "a size header before each compressed block" leads to **XMLCPB** ("XML ComPressed Binary"), CryEngine's save-game writer (`CryAction/Serialization/XMLCPBin/`). The excerpts below are shortened (`...` marks a cut), and some comments are ours; the links show the original code.

**Block size** ([`XMLCPB_Common.h`, line 59](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/XMLCPBin/XMLCPB_Common.h#L59)):

```cpp
static uint32 const XMLCPB_ZLIB_BUFFER_SIZE = 32 * 1024;// size for the buffer used in the zlib compression
```

**Block header** ([`XMLCPB_Common.h`, lines 103-112](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/XMLCPBin/XMLCPB_Common.h#L103-L112)):

```cpp
// saved in the file before every compressed block
struct SZLibBlockHeader
{
    enum
    {
        NO_ZLIB_USED = 0xffffffff
    };
    uint32 m_compressedSize; // when it is = NO_ZLIB_USED, the data is raw, without zlib compression (this should happen only very rarely)
    uint32 m_uncompressedSize;
};
```

**Block writing** ([`XMLCPB_ZLibCompressor.cpp`, lines 170-186](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/XMLCPBin/Writer/XMLCPB_ZLibCompressor.cpp#L170-L186)):

```cpp
bool compressionOk = gEnv->pSystem->CompressDataBlock(block->m_pZLibBuffer, block->m_ZLibBufferSizeUsed, pZLibCompressedBuffer, compressedLength);

SZLibBlockHeader zlibHeader;
zlibHeader.m_compressedSize = compressionOk ? compressedLength : SZLibBlockHeader::NO_ZLIB_USED;
zlibHeader.m_uncompressedSize = block->m_ZLibBufferSizeUsed;
...
pFile->Write(&zlibHeader, sizeof(SZLibBlockHeader));
if (compressionOk)
{
    pFile->Write(pZLibCompressedBuffer, compressedLength);
}
```

**The footer**, which the code calls a header but writes last ([`XMLCPB_ZLibCompressor.h`, line 54](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/XMLCPBin/Writer/XMLCPB_ZLibCompressor.h#L54)):

```cpp
SFileHeader m_fileHeader; // actually a footer
```

Its layout ([`XMLCPB_Common.h`, lines 63-100](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/XMLCPBin/XMLCPB_Common.h#L63-L100)):

```cpp
struct SFileHeader
{
    static const uint FILETYPECHECK = 'PBX0';

    SFileHeader()
    {
        memset(this, 0, sizeof(*this));
        m_fileTypeCheck = FILETYPECHECK;
    }
    ...
    uint32 m_fileTypeCheck;                          //  4 bytes: the magic number
    char   m_MD5Signature[MD5_SIGNATURE_SIZE];       // 16 bytes: the MD5
    SStringTable m_tags;                             //  8 bytes  \
    SStringTable m_attrNames;                        //  8 bytes   |
    SStringTable m_strData;                          //  8 bytes   | 41 bytes of table counters,
    uint32 m_numAttrSets;                            //  4 bytes   | all zero in KCD saves,
    uint32 m_sizeAttrSets;                           //  4 bytes   | then padding up to 64
    uint32 m_sizeNodes;                              //  4 bytes   |
    uint32 m_numNodes;                               //  4 bytes   |
    bool   m_hasInternalError;                       //  1 byte   /
};
```

**The MD5** ([`XMLCPB_ZLibCompressor.cpp`, lines 59-66](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/XMLCPBin/Writer/XMLCPB_ZLibCompressor.cpp#L59-L66) and [lines 81-87](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/XMLCPBin/Writer/XMLCPB_ZLibCompressor.cpp#L81-L87)):

```cpp
bool Write(void* pSrc, uint32 numBytes)
{
    m_pICompressor->MD5Update(&m_MD5Context, (const char*)pSrc, numBytes);   // every byte written...
    ...
}

void Finish()
{
    // ...then the footer, whose MD5 field is still zero (memset in the constructor)
    m_pICompressor->MD5Update(&m_MD5Context, (const char*)(&m_pCompressor->m_fileHeader), sizeof(m_pCompressor->m_fileHeader));
    m_pICompressor->MD5Final(&m_MD5Context, m_pCompressor->m_fileHeader.m_MD5Signature);
```

Every observation is explained:

| Observed | Explained by |
|---|---|
| Blocks decompress to 32,768 bytes | `XMLCPB_ZLIB_BUFFER_SIZE = 32 * 1024` |
| Two `u32` before each zlib block | `SZLibBlockHeader` |
| A 64-byte trailer | `SFileHeader`, "actually a footer": 61 bytes of fields, padded to 64 |
| The magic `0XBP` | `FILETYPECHECK = 'PBX0'`, see below |
| MD5 of the file with the digest zeroed | every write feeds the MD5, then the footer while its digest is still zero |

**Why `'PBX0'` is stored as `0XBP`.** `'PBX0'` is a C++ multi-character literal. With Microsoft's compiler its value is `0x50425830`, `P` being the most significant byte (the value is implementation-defined, see [cppreference](https://en.cppreference.com/w/cpp/language/character_literal)). Written as a little-endian `u32`, the bytes come out in reverse order: `30 58 42 50`, i.e. `0XBP`. A reversed word in a dump is a strong hint of this.

**Is the MD5 checked?** Unknown. It is only compiled in on PC ([`#ifdef WIN32`, line 38](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/XMLCPBin/XMLCPB_Common.h#L38)), and the public reader only checks the magic number ([`XMLCPB_Reader.cpp`, line 212](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/XMLCPBin/Reader/XMLCPB_Reader.cpp#L212)). An editor should recompute it anyway.

## 1.5 Reproducing the compression exactly

The writer calls `CompressDataBlock` without a level, so it gets the default, **3** ([`ISystem.h`, line 1621](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CryCommon/ISystem.h#L1621)). That's consistent with the `78 5e` header, which zlib uses for levels 2 to 5:

```cpp
virtual bool CompressDataBlock(const void* input, size_t inputSize, void* output, size_t& outputSize, int level = 3) = 0;
```

Recompressing every decompressed block at level 3 reproduces **every block of every save byte for byte**, so an editor can write exactly what the game writes.

The comparison needs classic zlib. Python 3.14 on Windows bundles zlib-ng (`zlib.ZLIB_VERSION` ends with `zlib-ng`), whose output is valid but different. The check was done with Perl's `Compress::Raw::Zlib` (bundled with Git for Windows). This script recompresses every block of a save and compares the result with the stored block:

```perl
use Compress::Raw::Zlib;
open(my $fh, "<:raw", $ARGV[0]) or die "$ARGV[0]: $!"; local $/; my $data = <$fh>;
my ($pos, $same, $total) = (0, 0, 0);
while ($pos < length($data) - 64) {
    my ($size) = unpack("V", substr($data, $pos, 4));    # compressed size (little-endian u32)
    my $stored = substr($data, $pos + 8, $size);
    my ($inflater) = Compress::Raw::Zlib::Inflate->new();
    my ($in, $raw) = ($stored, "");
    $inflater->inflate($in, $raw);
    my ($d) = Compress::Raw::Zlib::Deflate->new(-Level => 3, -WindowBits => 15, -MemLevel => 8, -AppendOutput => 1);
    my $out = "";
    $d->deflate($raw, $out);
    $d->flush($out);
    $same++ if $out eq $stored;
    $total++;
    $pos += 8 + $size;
}
print "$ARGV[0]: $same of $total blocks identical\n";
```

```
$ perl recompress.pl permanent001.whs
permanent001.whs: 816 of 816 blocks identical
```

## 1.6 KCD only kept the envelope

In CryEngine's own format, the footer's counters describe a tree of XML-like nodes. In KCD saves they are **all zero**, and the payload doesn't look like CryEngine's node data at all:

```
14 00 00 00 f5 01 4e 01 00 00 0d 00 3e 01 00 00 00 00 00 00 01 00 00 00 10 64 70 67 ...
```

Warhorse kept CryEngine's compressed envelope and MD5, and wrote **its own format** inside, which [part 2](#part-2-reverse-engineering-what-is-specific-to-kcd) decodes. One branch of it, however, is CryEngine data again.

## 1.7 Engine metadata and sections

Once the payload's chunk structure was known ([§2.1](#21-guess-a-framing-then-demand-an-exact-fit)), chunk `[503]` read like this:

```
f7 01 | 89 28 71 00                   chunk 503, 7,415,945 bytes, containing:
   a8 20 | 0c 00 00 00                chunk 8360, 12 bytes:
      76 65 72 73 69 6f 6e 00            "version"
      22 00 00 00                        34
   a7 20 | 0d 00 00 00                chunk 8359, 13 bytes:
      6c 65 76 65 6c 00                  "level"
      72 61 74 61 6a 65 00               "rataje"
   ...
```

That is names paired with values, in three chunk kinds: name + text (8359), name + integer (8360), and name + a block of data (8361). CryEngine's save-game interface has exactly these three operations ([`ISaveGame.h`, lines 26-30](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CryCommon/ISaveGame.h#L26-L30)):

```cpp
// set some basic meta-data
virtual void AddMetadata(const char* tag, const char* value) = 0;   // -> chunk 8359
virtual void AddMetadata(const char* tag, int value) = 0;           // -> chunk 8360
// create a serializer for some data section
virtual TSerialize AddSection(const char* section) = 0;             // -> chunk 8361
```

The engine writes the metadata in exactly the order found in every save ([`GameSerialize.cpp`, lines 1013-1038](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/GameSerialize.cpp#L1013-L1038)):

```cpp
savEnv.m_pSaveGame->AddMetadata(SAVEGAME_VERSION_TAG, SAVEGAME_VERSION_VALUE);
savEnv.m_pSaveGame->AddMetadata(SAVEGAME_LEVEL_TAG, levelName);
savEnv.m_pSaveGame->AddMetadata(SAVEGAME_GAMERULES_TAG, ...);
// save some useful information for debugging - should not be relied upon in loading
const SFileVersion& fileVersion = GetISystem()->GetFileVersion();
...
savEnv.m_pSaveGame->AddMetadata(SAVEGAME_BUILD_TAG, tmpbuf);
int bitSize = sizeof(char*) * 8;
savEnv.m_pSaveGame->AddMetadata("Bit", bitSize);
...
savEnv.m_pSaveGame->AddMetadata(SAVEGAME_TIME_TAG, timeString.c_str());
```

| In the save | Explained by the code |
|---|---|
| `version` = 34 | CryEngine has 32 ([line 66](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/GameSerialize.cpp#L66)): KCD's engine uses another version of the format |
| `Bit` = 64 | `sizeof(char*) * 8`: a 64-bit build |
| `build` = `"1.9.7.0"` on a 1.9.8 game | the executable's version resource, which "should not be relied upon" ([§2.10](#210-mine-the-programs-own-files)) |
| Sections `Timer`, `TerrainState`, `GameState`, ... | the sections added by [`SaveEngineSystems`](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/GameSerialize.cpp#L1044) and [`SaveEntities`](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/GameSerialize.cpp#L1087) (KCD's engine also has `GameTokens`, `FlowSystem` and `MatFX`) |

## 1.8 Typed values and hashed names

Inside a section, engine code saves values with `ser.Value("name", value)` and nests them with `BeginGroup`/`EndGroup`. A small section, `Timer`:

```
a9 20 | 20 00 00 00                                chunk 8361, 32 bytes:
54 69 6d 65 72 00                                     "Timer"
0c | 4e 8d e5 a0 | 3f 8f e5 e4 00 00 00 00            code 0c, 4 bytes, an 8-byte value: 3,840,249,663
0c | c6 bf be 7e | 80 96 98 00 00 00 00 00            code 0c, 4 bytes, an 8-byte value: 10,000,000
```

The code that writes it ([`Timer.cpp`, lines 535-543](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CrySystem/Timer.cpp#L535-L543)):

```cpp
void CTimer::Serialize(TSerialize ser)
{
    if (ser.IsWriting())
    {
        int64 currentGameTime = m_lLastTime + m_lOffsetTime;
        ser.Value("curTime", currentGameTime);
        ser.Value("ticksPerSecond", m_lTicksPerSec);
    }
```

Two values in the code, two in the save, and 10,000,000 is a plausible tick rate. So each value is **a type code, 4 bytes standing for the name, then the value**.

### Cracking the name encoding

4 random-looking bytes where a name should be: a 32-bit hash, most likely. The source says which names to expect, so we can run the common 32-bit hash functions on `curTime` and `ticksPerSecond` and see which one reproduces the observed bytes. This is a **known-plaintext** test:

```python
def fnv1(name: bytes) -> int:
    """32-bit FNV-1: multiply, then XOR."""
    h = 0x811C9DC5
    for byte in name:
        h = ((h * 0x01000193) & 0xFFFFFFFF) ^ byte
    return h

def fnv1a(name: bytes) -> int:
    """32-bit FNV-1a: XOR, then multiply."""
    h = 0x811C9DC5
    for byte in name:
        h = ((h ^ byte) * 0x01000193) & 0xFFFFFFFF
    return h

def djb2(name: bytes) -> int:
    h = 5381
    for byte in name:
        h = (h * 33 + byte) & 0xFFFFFFFF
    return h

observed = {0xA0E58D4E, 0x7EBEBFC6}  # "4e 8d e5 a0" and "c6 bf be 7e" read as little-endian u32
for hash_function in (zlib.crc32, fnv1, fnv1a, djb2):
    print(hash_function.__name__, {hash_function(n) for n in (b"curTime", b"ticksPerSecond")} == observed)
# only fnv1 prints True
```

Field names are **case-sensitive 32-bit [FNV-1](http://www.isthe.com/chongo/tech/comp/fnv/) hashes**. The names themselves are never stored; [§2.9](#29-recover-hashed-names-from-the-program-binary) recovers them anyway.

### The type codes

CryEngine lists the serializable types in a fixed order ([`SerializationTypes.h`, lines 15-33](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CryCommon/SerializationTypes.h#L15-L33)):

```cpp
SERIALIZATION_TYPE(bool)
SERIALIZATION_TYPE(float)
SERIALIZATION_TYPE(double)
SERIALIZATION_TYPE(Vec2)
SERIALIZATION_TYPE(Vec3)
...
SERIALIZATION_TYPE(uint64)
SERIALIZATION_TYPE(ScriptAnyValue) // not for network - only for save games
SERIALIZATION_TYPE(CTimeValue)
...
```

KCD's codes follow this list from 3 on, **minus `double`**, which KCD's engine doesn't have. Codes 0, 1 and 2 are "begin group", "end group" and "string". The full table is in [part 3](#type-codes).

This was verified, not assumed. The 7.4 MB `GameState` section was parsed with the codes known so far. At each unknown code, the following bytes revealed its size: `06` was followed by 12 bytes forming three plausible `f32` (a `Vec3`). Once the pattern matched the engine's list, the remaining codes were predicted from it, and **the whole section parsed to its last byte**: about 180,000 groups and 13,000 script values, all groups closed. Four of the predicted codes (`05`, `09`, `0a` and `0e`) never occur in any save, so their sizes rest on the engine's list alone.

The parser only steps over values, collects the name hashes and checks that groups nest, which is enough to prove the rules:

```python
SIZES = {0x03: 1, 0x04: 4, 0x05: 8, 0x06: 12, 0x07: 16, 0x08: 12, 0x09: 1, 0x0A: 2,
         0x0B: 4, 0x0C: 8, 0x0D: 1, 0x0E: 2, 0x0F: 4, 0x10: 8, 0x12: 8}   # value size per type code
SCRIPT_SIZES = {1: 0, 2: 1, 3: 8, 4: 4, 9: 12}   # script value size per kind: nil, boolean, handle, number, vector

def skip_script_value(buf, pos):
    """Step over one script (Lua) value; see part 3."""
    kind = buf[pos]
    if kind == 5:  # str16
        return pos + 3 + struct.unpack_from("<H", buf, pos + 1)[0]
    if kind == 6:  # table: u8, u32 pair count, then key/value pairs
        pairs = struct.unpack_from("<I", buf, pos + 2)[0]
        pos += 6
        for _ in range(2 * pairs):
            pos = skip_script_value(buf, pos)
        return pos
    if kind not in SCRIPT_SIZES:
        raise ValueError(f"unknown script value kind {kind} at {pos:#x}")
    return pos + 1 + SCRIPT_SIZES[kind]

def walk(buf, pos, end):
    """Name hashes of all typed values in buf[pos:end]; fails on anything unexpected."""
    hashes, depth = [], 0
    while pos < end:
        code = buf[pos]
        if code == 0x01:  # end of group: no name, no value
            depth -= 1
            if depth < 0:
                raise ValueError(f"end of group without a beginning at {pos:#x}")
            pos += 1
            continue
        hashes.append(struct.unpack_from("<I", buf, pos + 1)[0])
        pos += 5
        if code == 0x00:  # begin group: a name, no value
            depth += 1
        elif code == 0x02:
            pos += 2 + struct.unpack_from("<H", buf, pos)[0]
        elif code == 0x11:
            pos = skip_script_value(buf, pos)
        elif code in SIZES:
            pos += SIZES[code]
        else:
            raise ValueError(f"unknown type code {code:#x} at {pos - 5:#x}")
    assert pos == end and depth == 0  # the exact-fit test: every byte used, every group closed
    return hashes
```

### Script values

Code `11` is a value of the game's Lua scripts. Its first byte follows CryEngine's `ScriptAnyType` enum ([`IScriptSystem.h`, lines 110-123](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CryCommon/IScriptSystem.h#L110-L123)):

```cpp
enum ScriptAnyType
{
    ANY_ANY = 0,
    ANY_TNIL,        // 1
    ANY_TBOOLEAN,    // 2
    ANY_THANDLE,     // 3
    ANY_TNUMBER,     // 4
    ANY_TSTRING,     // 5
    ANY_TTABLE,      // 6
    ANY_TFUNCTION,   // 7
    ANY_TUSERDATA,   // 8
    ANY_TVECTOR,     // 9
    ANY_COUNT,
};
```

The enum gives the numbers; the byte layout came from examples. A table with three entries:

```
06                          table
05                          always 5 (meaning unknown)
03 00 00 00                 3 key/value pairs
05 0a 00 "scriptSave"       key: str16
06 05 00 00 00 00           value: an empty table
05 0d 00 "ignoredCorpse"    key
02 00                       value: boolean false
05 09 00 "inventory" ...    key, then its value
```

Numbers are `f32`, with one exception found through the float refresher's trick: some table keys are `01 00 00 00`, `02 00 00 00`... As `f32` they would be tiny subnormals (last byte `00`), which is implausible. They only occur as keys numbered 1 to n: list indices stored as `s32`.

**Time values** (code `12`) are `s64` in units of `TIMEVALUE_PRECISION = 100000` per second ([`TimeValue.h`, line 23](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CryCommon/TimeValue.h#L23)).

## 1.9 GameState: CryEngine's entity data

With the names recovered ([§2.9](#29-recover-hashed-names-from-the-program-binary)), the biggest section, `GameState`, reads like the engine code that writes it. It lists the **entities**, i.e. the objects of the world. Its start in `autosave798.whs`, as printed by the `dump()` function of §2.9:

```
BasicEntityData:
  BasicEntity:
    id (u32) = 99889
    beguid (u64) = 8598495808729642234        <- added by Warhorse
    flags (u32) = 17039378
    flags2 (u32) = 1
    flagsEx (u32) = 128                       <- added by Warhorse
    aiObjectID (u32) = 0
    pos (Vec3) = (0.0, 0.0, 0.0)
    name (str) = 'hunting_sword_3   345'
    class (str) = 'PickableItem'
    archetype (str) = ''
    parent (u32) = 0
    bepguid (u64) = 0                         <- added by Warhorse
```

The engine code that writes these fields, in the same order ([`GameSerializeHelpers.h`, lines 145-191](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/GameSerializeHelpers.h#L145-L191)):

```cpp
ser.Value("id", id);
ser.Value("flags", flags);
ser.Value("flags2", flags2);
ser.Value("aiObjectID", aiObjectId);
...
    ser.Value("pos", pos);
    if (ser.IsReading() || !rot.IsIdentity())
        ser.Value("rot", rot);                    // only when the object is rotated
    if (ser.IsReading() || !scale.IsEquivalent(Vec3(1.0f, 1.0f, 1.0f)))
        ser.Value("scl", scale);                  // only when the object is scaled
...
    ser.Value("name", name);
    ser.Value("class", className);
    ser.Value("archetype", archetype);
ser.Value("parent", parentEntity);
```

Two takeaways:

- **Records have no fixed field list.** Conditional fields like `rot` and `scl` come and go, so a reader must follow the type codes rather than assume a layout.
- **Engine conventions explain odd names.** `i` is always a group, and one of the most frequent names: 18,756 times in `permanent001`, and 26,700 to 31,200 times in the later reference saves, where it ranks first to fourth. The engine's container macro writes the container's `"Size"`, then each element as a group `"i"` holding a value `"v"` ([`ISerialize.h`, lines 637-669](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CryCommon/ISerialize.h#L637-L669)). The saves use the same names without the `Size`: every `i` is one of the 36 elements of a `bloodZone` group, holding a `u8` `v`. `Size` itself only appears as `0`, in six empty containers.

The rest of `GameState` follows the engine's calls group by group:

| Group | Written by |
|---|---|
| `BasicEntityData` (one `BasicEntity` per object) | [`SaveEntities`](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/GameSerialize.cpp#L1098) |
| `EntityPoolManager_Bookmarks` | [line 1215](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/GameSerialize.cpp#L1215), then [`EntityPoolManager.cpp`](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryEntitySystem/EntityPoolManager.cpp#L411) |
| `NormalEntityData` | [line 1219](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/GameSerialize.cpp#L1219) |
| `BreakableObjects` | [line 1238](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/GameSerialize.cpp#L1238), then [`ActionGame.cpp`](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/ActionGame.cpp#L4456) |
| `Timers`, `ScriptTimers`, `Layers` | [`CEntitySystem::Serialize`](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryEntitySystem/EntitySystem.cpp#L2844-L2910) |
| `ExtraEntityData` | [line 1267](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/GameSerialize.cpp#L1267) |
| `IGame`, the game's own part (nearly empty in KCD) | [line 1392](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/GameSerialize.cpp#L1392) |

---

# Part 2: reverse engineering what is specific to KCD

The engine source covered the envelope and chunk `[503]`. The rest is Warhorse's code, with no public source: the header, the layers, and the modules of chunk `[502]`, nearly three quarters of the payload. Here are the techniques that decoded them, as a reusable playbook.

## 2.1 Guess a framing, then demand an exact fit

**Use it when** you see small integers that could be ids and sizes. The payload starts like this:

```
14 00 00 00                  u32: 20
f5 01 | 4e 01 00 00          u16 501, u32 334
   0d 00 | 3e 01 00 00       u16 13, u32 318
      ... 318 bytes ...
   10 00 | 04 00 00 00       u16 16, u32 4
      01 00 00 00
f4 01 | d0 a5 97 01          u16 500, u32 26,715,600
```

**How.** Guess `u16 id, u32 size, body`, the chunk design from the [conventions](#conventions). Then write a parser that accepts a region only if the chunks **tile it exactly**, ending on its last byte:

```python
def parse_chunks(buf, start, end):
    """[(id, body start, body end)] if buf[start:end] is exactly a series of chunks, else None."""
    chunks, pos = [], start
    while pos < end:
        if pos + 6 > end:
            return None
        chunk_id, size = struct.unpack_from("<HI", buf, pos)
        if pos + 6 + size > end:
            return None
        chunks.append((chunk_id, pos + 6, pos + 6 + size))
        pos += 6 + size
    return chunks

def children(buf, start, end):
    """{id: (body start, body end)} if buf[start:end] is exactly a series of chunks with distinct ids."""
    chunks = parse_chunks(buf, start, end)
    if chunks is None:
        raise ValueError(f"bytes {start:#x} to {end:#x} are not a series of chunks")
    by_id = {chunk_id: (s, e) for chunk_id, s, e in chunks}
    if len(by_id) < len(chunks):
        raise ValueError(f"bytes {start:#x} to {end:#x} repeat a chunk id")
    return by_id

root = children(payload, 4, len(payload) - 1)  # after the leading u32, before the single trailing byte
print({chunk_id: e - s for chunk_id, (s, e) in root.items()})  # {501: 334, 500: 26715600, 509: 0}
```

With the leading `u32` and one trailing byte, these three chunks cover all 26,715,957 bytes. The trailing byte showed up on the first attempt, which parsed up to `len(payload)` and failed with a single byte left, too short for a chunk header. Applied recursively ("does this body also parse exactly as chunks?"), the same test separates **containers** from **leaves** and draws the first map of the tree.

Once the map is known, a path of ids leads to any chunk, in any save:

```python
def node(buf, *path):
    """(body start, body end) of the chunk at a path of ids from the root, e.g. node(payload, 500, 503)."""
    start, end = 4, len(buf) - 1
    for chunk_id in path:
        start, end = children(buf, start, end)[chunk_id]
    return start, end

start, end = node(payload, 500, 503)
print(end - start)  # 7415945: the engine data of §1.7
```

**Pitfalls.** Small regions fit by accident. Chunk `[1101]` holds 12 zero bytes, which parse "exactly" as two empty chunks with id 0. Another save showed the truth: the same chunk held `01 00 00 00 00 00 40 40 00 00 00 00`, i.e. `1`, `3.0f`, `0`, a small struct. And "id 0 means junk" isn't a safe rule either, because id 0 is legitimate elsewhere (inside `[1000]`). Only more samples decide.

**In KCD:** the whole payload is a chunk tree, and this test found its skeleton.

## 2.2 Look for a small header in front of a list

**Use it when** a body looks opaque but contains chunk-like patterns a few bytes in.

**How.** Try header sizes from 1 to 16 bytes, keep those after which the rest parses exactly as chunks, and check whether a `u32` in the header equals the number of chunks:

```python
def header_candidates(buf, start, end, max_header=16):
    """(header size, chunk count, header offsets holding that count) for each header size that fits."""
    for size in range(1, max_header + 1):
        chunks = parse_chunks(buf, start + size, end)
        if chunks:
            counts = [i for i in range(size - 3) if struct.unpack_from("<I", buf, start + i)[0] == len(chunks)]
            yield size, len(chunks), counts

print(next(header_candidates(payload, *node(payload, 500, 502, 29443, 3002))))
# (4, 5765, [0]): a u32 count, then exactly 5,765 chunks
```

**Pitfalls.** Only trust strong signals: a count field that matches, or a 16-byte header repeated inside the first child (a GUID). Fits with odd ids or a count that doesn't match were coincidences. Check every accepted layout on all samples.

**In KCD:** a list of 5,765 records, and the list of characters (called "souls" in KCD): 2,661 records, each starting with its GUID. All the soul records of all the saves fit.

## 2.3 Extend the rules until everything parses

**Use it** continuously: this is the loop from [the method](#the-method-in-one-page), applied to every structure.

**How.** Parse with the current rules. At the first failure, look at the bytes, add the smallest rule that explains them, and repeat until every byte of every sample is explained.

**Pitfalls.** Some rules only show up in later samples. Keep re-running on all files.

**In KCD:** the script value *handle* (kind 3) is absent from the first save and appears 402 times in a later one. It must be 8 bytes, the only size after which the next bytes fall back into the familiar "end group, begin group" pattern. The type codes of [§1.8](#the-type-codes) were found the same way.

## 2.4 Use text as landmarks

**Use it when** the data contains readable strings: they are the easiest things to find in a dump, and the bytes before them reveal the framing.

**How.** Look at what precedes a string: an id, a length, a size that covers the string plus a little more.

```
2b 02 | 0f 00 00 00 | 5f 6d 61 74 75 73 5f 66 72 69 63 65 6b 00 | 00
id 555  size 15       "_matus_fricek" + NUL (14 bytes)            1 more byte: 0 or 1
```

A size of 15 for a 14-byte string means one extra byte. Here chunk 555 is a **layer**, a named group of world objects the game switches on or off, and the extra byte is its state. Each save of the main world has 927 of them.

**Size arithmetic proves layouts cheaply.** The script-name table `[2100]` is `u8`, then (`u16` index, `cstr`) entries numbered 0 to n-1, then a final `u16` equal to n. In one save: 1 + 204,667 + 2 = 204,670 bytes, exactly the chunk's size.

**In KCD:** the layers, the header (three strings, including a `|`-separated description), the DLC list, the mod list, and the script-name tables.

## 2.5 Compare files

**Use it when** you have several samples. What stays the same confirms the structure; what changes carries meaning.

**How.** Diff structures and values between files, ideally files that differ by a single known action. The repository's `compare_saves.py` automates this. For instance, the states of the layers ([§2.4](#24-use-text-as-landmarks)) in the first two saves:

```python
def layers(buf):
    """{layer name: 0 or 1}, from the preload chunk."""
    states = {}
    for _, s, e in parse_chunks(buf, *node(buf, 500, 507, 29443, 3010)):
        name_end = buf.index(b"\0", s)
        states[buf[s:name_end].decode()] = buf[name_end + 1]
    return states

_, save508 = read_whs("save508.whs")
before, after = layers(payload), layers(save508)
print(sum(before[n] < after[n] for n in before), "on,", sum(before[n] > after[n] for n in before), "off")
# 84 on, 19 off
```

**Pitfalls.** Between two files far apart in time, everything changes. Pairs close in time are far more informative.

**In KCD:**

| Comparison | What it revealed |
|---|---|
| `permanent001` vs `save508` | The same chunk tree down to each soul's chunks, apart from optional chunks: `[5499]` (see below) and `[4872]` in some souls. So the structure is stable. The first two header `u32` are 0 and 1, then 2 and 508, matching the file names: **save type** and **save number**. The `u32` after the Unix time is always 0: the time is a `u64`. |
| `exit.whs` (no number in its name) | Type 5, number 678. Sorted by date, the numbers of all saves increase regardless of type: **one global save counter** (except "switch" saves, below). |
| Layers over time | 103 layers changed state between the first two saves (84 on, 19 off), consistent with story progress. Chunk `[5499]` exists exactly while its `event_…` layer is on, in all the saves. |
| `autosave769` vs `autosave770` (11 minutes apart; a side quest starts) | Besides clocks, play time and many objects of the world (items, containers...), the decoded data shows: the header's quest and objective fields (the objective becomes `@objective_Savename_1`), 6 quest layers (5 on, 1 off), statistics #7 and #55 (+1 each), 5 new NPCs in `GameState` (such as `revelation_pavel_z_kolina`), and 4 cows fewer among the souls. |
| `autosave798` (the first reference save made with mods) | A new header chunk `[14]`: the mod list. |
| `autosave798` vs `autosave799` (1.4 minutes of play apart, game 1.9.6 vs 1.9.8) | The only structural difference is a new 5-byte module `[29464]`: what the game update added. |
| `switch51141`, `save646`, `save669` (before, inside and after Theresa's part of A Woman's Lot) | A new save type 6 in `switch51141`, whose number is outside the global counter. `save646` is on level `rataje_dlc4` and holds only Theresa's small world (49 layers, 246 souls), plus a new header chunk `[17]` = 51141. `save669`, back in the main world, continues the switch save's world, but its statistics kept the DLC's progress. |
| `permanent001` of two playthroughs (the same moment: the prologue's first quest) | The same level `rataje`, the same 62 layers on and the same 2,661 soul names. The prologue is the main world with other layers on (`q_skalitz_normal` instead of `q_skalitz_burned`), and a new game starts with a fixed set of souls. Besides play time, only statistics #37, #96 and #97 differ. |
| Reload a save made before the DLC, enter the DLC again | Two new files at once: `switch03227` (type 6, level `rataje`), then `autosave800` (level `rataje_dlc4`) with `[17]` = 3227. This proved in one step what the old saves only made likely. |

## 2.6 Ask the user of the program

**Use it when** a value has a visible counterpart: something shown in a menu, a known event, a setting.

**How.** Ask what the program displays, and compare with the candidate field.

**In KCD**, one sentence from the player often settled a question:

| The player said | It settled |
|---|---|
| "136.5h is this save's play time in the menu." | The description's last field is **hours played**, not in-game days. |
| "It should be 185.4h." (the save holds 185.476) | The menu **truncates** to one decimal. |
| "Permanent saves are labeled *quest started*." And an autosave had the same label. | The label comes from the objective key `@objective_Savename_1`, not the save type. |
| "This one was made by sleeping in a bed at an inn." | Sleep saves are ordinary autosaves. |
| "The game version is 1.9.8." (the save says `1.9.7.0`) | `build` is not the game version ([§2.10](#210-mine-the-programs-own-files)). |
| "The village isn't burnt yet in the prologue." | Not a separate map (the level is `rataje`) but layers: `q_skalitz_normal` is on, `q_skalitz_burned` off. |
| "The clock says 10 am in both first saves." | Statistic #37 (10 h in one, 0 in the other) isn't the clock. A search for 10 hours found it in chunk `[13617]` ([§2.7](#27-search-for-a-known-value-in-every-encoding)). |
| "In autosave799, the clock says 16:23." | `[13617]` holds day 199, 16:22:53: right to the minute. |
| "The Statistics tab shows *World time passed* at 156.4 days." (the save's #37 holds 156.356 days) | #37 is that value: the tab shows it in days, rounded to one decimal. |
| "I played the DLC over several sessions." | The main world had to be reloaded from a file: the "switch" save. |
| "I slept 8 hours in a bed between these two saves." | The 32-minute jump of the clock's counters comes from the fast-forwarded night, not from play ([§2.8](#28-reason-about-counters)). |

## 2.7 Search for a known value in every encoding

**Use it when** you know a value the file must contain (displayed by the program, or computable), but not where or how it's stored.

**How.** Scan for it in every plausible encoding (integers, `f32`, `f64`), at every byte offset, with a tolerance for floats:

```python
import array

def find_number(buf, target, tolerance=1e-6):
    """(type, offset, value) wherever target is stored as an f32 or f64, at any alignment."""
    hits = []
    for code, size in (("f", 4), ("d", 8)):
        for shift in range(size):
            usable = (len(buf) - shift) // size * size
            values = array.array(code, buf[shift:shift + usable])
            hits += [(code, shift + i * size, v) for i, v in enumerate(values)
                     if abs(v - target) <= abs(target) * tolerance]
    return hits

_, save508 = read_whs("save508.whs")
print(find_number(save508, 136.540985))  # [('d', 22832605, 136.54098780428586)]: exactly one f64
```

To see which structure holds a hit, go down the chunk tree:

```python
def locate(buf, offset):
    """Ids of the chunks holding offset, from the root down, as far as the bodies parse as chunks."""
    path, start, end = [], 4, len(buf) - 1
    while True:
        hits = [c for c in parse_chunks(buf, start, end) or [] if c[1] <= offset < c[2]]
        if not hits:
            return path
        chunk_id, start, end = hits[0]
        path.append(chunk_id)

print(locate(save508, 22832605))  # [500, 502, 29463, 13615, 6008]
```

Like the test of §2.1, `locate` can descend into a leaf whose bytes happen to parse as chunks: check its answer against the bytes.

**Pitfalls.** Small integers match everywhere by coincidence. Prefer distinctive values (like this float), and confirm the location in other files.

**In KCD:** the header shows the play time as text (`136.540985`). The scan found a single `f64` inside a list of 183 records keyed 1 to 183: KCD's **statistics table** (`[13615]`), play time being statistic #81. The [float refresher](#floating-point-numbers-ieee-754) explains the text: the header prints the `f64` converted to `f32` with 6 decimals, hence `136.540985` rather than the rounded `f64`, `136.540988`.

The same method found the **in-game clock**. The player saw 10:00 in the first save of two playthroughs, whose statistic #37 read 10 hours in one and 0 in the other. Encoding 10 hours as `f32`, `f64`, seconds, milliseconds and CryEngine's `CTimeValue`, then keeping the locations common to both saves, left one candidate: chunk `[13617]`, starting with 36,000,000 as a `u64`, i.e. milliseconds since midnight of day 0. A save holding day 199, 16:22:53 then showed 16:23 in the game.

## 2.8 Reason about counters

**Use it when** you have unnamed numeric fields across several files: their behavior over time identifies them.

**How.** Order the files chronologically and look at how each value evolves: monotonic or not, rate of growth, ratios and invariants between fields. Here, the numbers of the statistics table (laid out in [part 3](#statistics)), for every save in date order:

```python
import glob

STAT_FORMATS = {14223: "<i", 14224: "<d", 14232: "<Bd", 14229: "<I", 14236: "<I", 14237: "<I",
                14230: "<6xBQ", 14234: "<6xBQ", 14235: "<6xBQ"}   # "6x" skips the header of the inner chunk [26852]

def stats(buf):
    """{key: number} for the statistics that hold one number."""
    numbers = {}
    for _, s, e in parse_chunks(buf, *node(buf, 500, 502, 29463, 13615)):
        key, value = struct.unpack_from("<I", buf, s)[0], parse_chunks(buf, s + 4, e)
        if value and value[0][0] in STAT_FORMATS:
            chunk_id, vs, ve = value[0]
            numbers[key] = struct.unpack(STAT_FORMATS[chunk_id], buf[vs:ve])[-1]
    return numbers

def save_time(buf):
    return struct.unpack_from("<Q", buf, node(buf, 501, 13)[0] + 8)[0]  # the header's unix_time

by_time = {}
for path in glob.glob("*.whs"):
    _, buf = read_whs(path)
    by_time[save_time(buf)] = stats(buf)
history = [by_time[t] for t in sorted(by_time)]
last = history[-1]
print(len(last), [k for k in last if any(b[k] < a[k] for a, b in zip(history, history[1:]))])  # 142 [89]
print(round(last[50] / last[37], 2), round((last[37] - last[50]) / 3_600_000 / last[81], 1))  # 0.31 16.4
```

**In KCD**, with the statistics table:

- **The table is cumulative, apart from three statistics that reset.** Of the 142 statistics that hold a number, three decrease from time to time in date order: #61, #62 and #89 (across the reference saves, only #89 does, hence the `[89]` above). All the statistics also go back where an older save was reloaded.
- **#37 looks like total in-game time, in milliseconds.** It grows much faster over periods that include sleeping, as a game clock would. It isn't the clock itself, though ([§2.7](#27-search-for-a-known-value-in-every-encoding)).
- **#50 looks like time slept.** It is consistently about a third of #37 (8 hours per in-game day). Awake, in-game time runs about 16 times faster than real play time: 15.8 to 16.4 in-game hours per hour played in every reference save after the prologue, and about 23 counting sleep.
- **#89 looks like the time since some recurring event, because it resets.** It runs on #37's clock: between two saves #37 and #89 grew by the same amount, and #37 − #89 stays constant across the last four saves.
- **#55 seemed to count quests started.** It rarely changes, and it went up by one exactly when a quest started. The game's table later showed otherwise: #55 is `ThreatsSucceded`, "Intimidation successes", so that +1 was a coincidence ([§2.10](#210-mine-the-programs-own-files)).

**The clock's two counters.** Besides the clock, chunk `[13617]` holds two unknown counters in milliseconds that grow roughly like the play time but drift from it: behind it early in the playthrough, 1.44 times it after 204 hours. Relating them to known values settled what they are. A cheat mod's console command saves at once, without opening a menu, so a few such saves cut the play into precise intervals, and each interval was compared with #81 and with the clock:

| Interval | #81 (real time) | In-game clock | Clock ÷ 15 | Counter B | Counter A |
|---|---|---|---|---|---|
| Load a save, walk to a bed, save | 20.5 s | +303 s | 20.2 s | 20.2 s | 23.6 s |
| Wait by the bed, save | 47.8 s | +707 s | 47.1 s | 47.1 s | 47.1 s |
| Sleep 8 hours (the game saves on waking) | 63.8 s | +8.06 h | 1,933.8 s | 1,933.8 s | 1,933.8 s |
| Walk a few steps, save | 6.8 s | +92 s | 6.2 s | 6.2 s | 6.2 s |

In every interval, the counters grew by the in-game time divided by 15, the constant stored in the same chunk, except counter A across the load (see below). They measure world time at normal speed, and 15.0 is very likely the time scale: 15 in-game seconds per real second. This explains the drift:

- **When the world stops, they stop,** while #81 keeps counting. In another test, 5 minutes in the pause menu added 5 minutes to #81 but only 1.7 and 3.1 seconds to the counters. Each save also costs them about half a second (0.7 s for the main world's saves, 0.5 s for the smaller ones of the prologue), probably the time spent writing it.
- **When the world is fast-forwarded, they race ahead:** 8 hours of sleep took 64 real seconds but added 32 minutes to them. A playthrough full of nights ends up well ahead of its play time.
- **The two counters differ only around loading:** counter A gained 1.4 to 3.4 seconds on B across each of three loads, so it seems to also count loading time.

Two points remain open: at the start of the prologue, where the clock is frozen at 10:00, the counters still grow with the play time; and at 204 hours, counter B holds 294 hours where the clock ÷ 15 gives 320, so some clock jumps aren't counted.

## 2.9 Recover hashed names from the program binary

**Use it when** a format stores hashes of strings (field names, asset names...) instead of the strings.

**How.** The strings are usually literals in the program that writes them (`ser.Value("pos", ...)`), so they sit in its binary. Extract every printable string from the binary, hash each one with the known function, and keep the matches:

```python
import re

dll = open(r"C:\Program Files (x86)\Steam\steamapps\common\KingdomComeDeliverance\Bin\Win64\WHGame.dll", "rb").read()
texts = set(re.findall(rb"[\x20-\x7e]{1,128}", dll))    # every printable run
candidates = texts | {w for t in texts for w in re.findall(rb"[A-Za-z_][A-Za-z0-9_.]*", t)}
names = {fnv1(c): c.decode() for c in candidates}

def sections_of(buf):
    """{section name: (start, end) of its typed values}, from the engine data [503]."""
    sections = {}
    for chunk_id, s, e in parse_chunks(buf, *node(buf, 500, 503)):
        if chunk_id == 8361:                               # a section: cstr name, then typed values
            name_end = buf.index(b"\0", s)
            sections[buf[s:name_end].decode()] = (name_end + 1, e)
    return sections

sections = sections_of(payload)
used = set(walk(payload, *sections["GameState"]))
recovered = {h: names[h] for h in used if h in names}
print(len(recovered), "of", len(used))  # 244 of 246 in this save
```

With the names, a section reads as text. This prints the start of `autosave798`'s `GameState`, shown in [§1.9](#19-gamestate-cryengines-entity-data):

```python
TYPES = {0x03: ("bool", "<B"), 0x04: ("float", "<f"), 0x05: ("Vec2", "<2f"), 0x06: ("Vec3", "<3f"),
         0x07: ("Quat", "<4f"), 0x08: ("Ang3", "<3f"), 0x09: ("s8", "<b"), 0x0A: ("s16", "<h"),
         0x0B: ("s32", "<i"), 0x0C: ("s64", "<q"), 0x0D: ("u8", "<B"), 0x0E: ("u16", "<H"),
         0x0F: ("u32", "<I"), 0x10: ("u64", "<Q"), 0x12: ("time", "<q")}

def dump(buf, pos, end, limit=20):
    """Print the first `limit` typed values of buf[pos:end], with their names, indented by group."""
    depth = 0
    while pos < end and limit > 0:
        code = buf[pos]
        if code == 0x01:                                   # end of group
            depth, pos = depth - 1, pos + 1
            continue
        name_hash = struct.unpack_from("<I", buf, pos + 1)[0]
        name = names.get(name_hash, f"{name_hash:#010x}")
        pos, limit, indent = pos + 5, limit - 1, "  " * depth
        if code == 0x00:
            print(f"{indent}{name}:")
            depth += 1
        elif code == 0x02:
            size = struct.unpack_from("<H", buf, pos)[0]
            print(f"{indent}{name} (str) = {buf[pos + 2:pos + 2 + size].decode()!r}")
            pos += 2 + size
        elif code == 0x11:
            print(f"{indent}{name} (script value)")
            pos = skip_script_value(buf, pos)
        else:
            kind, fmt = TYPES[code]
            value = struct.unpack_from(fmt, buf, pos)
            print(f"{indent}{name} ({kind}) = {value[0] if len(value) == 1 else value}")
            pos += struct.calcsize(fmt)

_, save798 = read_whs("autosave798.whs")
dump(save798, *sections_of(save798)["GameState"], limit=14)  # the dump of §1.9
```

**Pitfalls:**

- **Hash whole strings as well as words.** Some names are dotted member paths, such as `colliderSize.Min` or `m_ledgeBlending.m_qtTargetLocation.q`, which a word scan cuts apart.
- **Mind short names.** A scan with a minimum length, like the Unix command-line tool `strings` (4 characters by default), misses one-letter names such as `i` and `q`. The pattern above accepts single characters; otherwise, brute-force every name of one to three characters.
- **Estimate false positives.** Here, ~290,000 candidates against ~270 hashes in a 2³² space predicts about 0.02 accidental matches. Also check that the stored types agree with the names (`….q` is a quaternion, `….t` a vector).
- **The file itself rarely helps.** Hashing every string found in the saves recovers only 26 of the 272 names (~10%), by coincidence.

**In KCD:** 270 of the 272 hashed names were recovered from `WHGame.dll`, covering over 99.7% of all values. The last two, `0x51D7C884` and `0x51D7C882`, differ only in their last byte. FNV-1 ends by XOR-ing the last character into the hash, so they are almost certainly two names that differ only in their final character (two characters whose codes differ by XOR `06`, such as `2` and `4`). `build_field_names.py` repeats the search, for instance after a game update.

## 2.10 Mine the program's own files

**Use it when** the file references things by key or id: the program's data files often hold the other half.

**In KCD:**

- **Localization keys.** The header stores keys such as `@subchapter_650_name`. Their texts are in `Localization/<Language>_xml.pak`, plain zip archives. The game's other archives, such as `Data/Tables.pak`, have a CryEngine quirk: their local file headers use `\` where the central directory uses `/`, and Python's `zipfile` refuses the mismatch. Reading entries through their local header works for both kinds:

  ```python
  import zipfile

  def read_pak_file(pak_path, entry_name):
      """Read one entry of a CryEngine .pak via its local header (zipfile rejects the name mismatch)."""
      raw = open(pak_path, "rb").read()
      with zipfile.ZipFile(pak_path) as pak:
          info = pak.getinfo(entry_name)
      name_len, extra_len = struct.unpack_from("<HH", raw, info.header_offset + 26)
      start = info.header_offset + 30 + name_len + extra_len
      body = raw[start:start + info.compress_size]
      return zlib.decompress(body, -15) if info.compress_type == zipfile.ZIP_DEFLATED else body

  pak = r"C:\Program Files (x86)\Steam\steamapps\common\KingdomComeDeliverance\Localization\French_xml.pak"
  xml = read_pak_file(pak, "text_ui_quest.xml").decode("utf-8")
  print(re.search(r"<Cell>objective_Savename_1</Cell><Cell>(.*?)</Cell><Cell>(.*?)</Cell>", xml).groups())
  # ('Quest started', 'Quête lancée')
  ```

- **Statistic definitions.** `Data/Tables.pak` holds `Libs/Tables/rpg/statistic.xml`, the game's list of its 183 statistics: id, name, type, display group and a label key. It names #37 `TimeIngame`, of type `WorldTime`, and its label key `stat_time_ingame` reads "World time passed" in the English localization's `text_ui_soul.xml`: the name of a line of the in-game Statistics tab, where the player confirmed the value ([§2.6](#26-ask-the-user-of-the-program)).
- **Version numbers.** A 1.9.8 game writes `build = "1.9.7.0"`. The executable's version resource says `1.9.7.0`: it wasn't bumped when patch 1.9.8 rebuilt the executable, and the engine copies it into saves through `GetFileVersion()`. The menu's version comes from `wh_sys_version = "1.9.8"` in `system.cfg`, which saves don't record. The game's `kcd.log` shows both, as `FileVersion: 1.9.7.0` and `Displayed build info: 1.9.8-…`.

## 2.11 Validate with a second, strict reader

**Use it** at the end, and whenever the description changes.

**How.** Write the complete description as a separate, strict reader that rejects anything unexpected, and run it on every sample. Check that:

- **every byte is consumed:** parsing ends exactly at the end of each file;
- **every group is closed:** each "begin group" has its "end group";
- **every count matches:** each declared count equals the items that follow;
- **every constant holds:** each "always" of [part 3](#part-3-format-reference), such as the leading 20, the two 200s, the 927 layers of the main world or the 183 statistics;
- **every order holds:** chunks come in the order part 3 lists them;
- **redundant values agree:** the header's play time equals statistic #81, and each soul's GUID is repeated in its identity;
- **all text is valid:** every string decodes as strict UTF-8.

A small cursor class keeps such a reader close to part 3's notation:

```python
class Reader:
    """Strict sequential reader of buf[pos:end]."""
    def __init__(self, buf, pos, end):
        self.buf, self.pos, self.end = buf, pos, end

    def read(self, fmt):
        """Values of a struct format, e.g. read("<IIQ") for u32, u32, u64."""
        if self.pos + struct.calcsize(fmt) > self.end:
            raise ValueError(f"read past the end at {self.pos:#x}")
        values = struct.unpack_from(fmt, self.buf, self.pos)
        self.pos += struct.calcsize(fmt)
        return values[0] if len(values) == 1 else values

    def cstr(self):
        nul = self.buf.index(b"\0", self.pos, self.end)
        text, self.pos = self.buf[self.pos:nul].decode("utf-8"), nul + 1   # strict UTF-8
        return text

    def chunk(self, expected_id):
        """Reader of the next chunk's body, which must have this id."""
        chunk_id, size = self.read("<HI")
        if chunk_id != expected_id or self.pos + size > self.end:
            raise ValueError(f"expected chunk [{expected_id}] at {self.pos - 6:#x}, found [{chunk_id}] of {size} bytes")
        self.pos += size
        return Reader(self.buf, self.pos - size, self.pos)

    def done(self):
        if self.pos != self.end:
            raise ValueError(f"{self.end - self.pos} unexpected bytes at {self.pos:#x}")

r = Reader(payload, 0, len(payload))
assert r.read("<I") == 20
info = r.chunk(501).chunk(13)                              # Header, then its SaveInfo
save_type, save_number, unix_time = info.read("<IIQ")
level, description, title = info.cstr(), info.cstr(), info.cstr()
assert info.read("<II") == (200, 200)
unknown_flag, dlc_count = info.read("<BH")
dlcs = [(info.read("<I"), info.cstr()) for _ in range(dlc_count)]
info.done()
print(save_type, save_number, level, [dlc_id for dlc_id, _ in dlcs])  # 0 1 rataje [1, 4, 8, 9, 10]
```

**In KCD:** all the saves passed, about a million values each. This step also exposes bugs in the quick scripts written along the way: one had reported "nested records" in the statistics table, which were really that script reading past the end of a record.

---

# Part 3: format reference

The whole format as understood today, using the [conventions](#conventions). Structure and field names describe what was learned about their content; those still unexplained start with "unknown". None of them come from the game's code or data files or from CryEngine's source, and the saves don't store them. Chunks are listed in file order. "Never seen" marks what is expected (from CryEngine's source, for instance) but absent from all the saves.

### The file

```
File
    blocks              Block × (as many as fit until 64 bytes remain)
    footer              Footer

Block
    compressed_size     u32         # 0xFFFFFFFF: stored uncompressed (never seen)
    uncompressed_size   u32         # 32768 for every block but the last
    data                byte[compressed_size]       # zlib, level 3;
                                                    # byte[uncompressed_size], raw, if stored uncompressed

Footer                              # 64 bytes
    magic               byte[4]     # "0XBP" ('PBX0' as a little-endian u32)
    md5                 byte[16]    # MD5 of the whole file, computed with these 16 bytes zeroed
    unused              byte[44]    # zeros
```

### The payload

The payload is every `Block.data`, decompressed and concatenated.

```
Payload
    unknown             u32         # always 20
    header              [501] Header
    body                [500] Body
    end_marker          [509]       # empty
    trailing_byte       u8          # varies from save to save; unknown (see "Still unknown")
```

### Header

```
Header = chunks:
    [13] SaveInfo
    [16] u32                        # always 1
    [14] ModList                    # only when mods are enabled
    [17] u32                        # only inside a DLC level: number of the "switch" save (see "DLC levels")

SaveInfo
    save_type           u32         # see "Save types"
    save_number         u32         # one counter shared by all save types, except "switch" saves
    unix_time           u64         # seconds since 1970-01-01 UTC
    level               cstr        # "rataje" (main open world, prologue included) or "rataje_dlc4" (Theresa's part of A Woman's Lot)
    description         cstr        # "type|number|quest|objective|location|unix time|dd/mm/yyyy hh:mm|play hours|"
    title               cstr        # "quest|objective" on permanent saves and on autosaves that have an objective, empty otherwise
    unknown_a           u32         # always 200
    unknown_b           u32         # always 200
    unknown_flag        u8          # 0 at the start of a new game, 1 at some later point, already during the prologue
    dlc_count           u16
    dlcs                Dlc × dlc_count

Dlc
    dlc_id              u32         # 1, 4, 8, 9, 10
    name                cstr        # already translated, e.g. "Trésors du passé"

ModList
    mod_count           u32
    mods                Mod × mod_count

Mod
    folder              cstr
    name                cstr
    description         cstr
    author              cstr
    version             cstr
    version_again       cstr        # same as version
```

Quest, objective and location are localization keys (`@subchapter_631_name`, `@objective_Savename_1`, `@location_Sazava`). The play time is statistic #81 converted to `f32` and printed with 6 decimals; the menu truncates it to one decimal. The description's date and time are local, whereas `unix_time` is UTC.

#### Save types

| Value | Type | File name |
|---|---|---|
| 0 | permanent: automatic save when a main quest starts, with no limit on their number | `permanent001.whs` ... |
| 1 | autosave, including sleep saves and side-quest starts; the game keeps the last 100 | `autosave689.whs` ... |
| 2 | manual save (Saviour Schnapps) | `save508.whs` ... |
| 5 | save and quit | `exit.whs` (always the same name) |
| 6 | switch: save of the main world, just before entering a DLC level (see below); its number is not from the global counter | `switch51141.whs`, `switch03227.whs` |
| 3, 4 | never seen | |

#### DLC levels

Theresa's part of A Woman's Lot is played in a separate, small level, `rataje_dlc4` (49 layers and about 250 souls, mostly named `q_theresa_…`). Entering it:

1. writes a **switch** save (type 6) of the main world, on level `rataje`;
2. then plays the DLC; its saves hold only the DLC's world, plus header chunk `[17]`: the switch save's number;
3. when the DLC ends, the game restores the main world from the switch save.

**Statistics** are the exception: they belong to the playthrough, not to a world, so the DLC's progress (play time, in-game time, counters) carries over to the restored main world. The clock is not: each level has its own (Theresa's starts at 08:00 on day 0), and the main world's comes back with the switch save.

### Body

```
Body = chunks:
    [507] Preload
    [503] EngineData
    [502] Modules

Preload = [29443] = [3010] = LayerState × n        # 927 in the main world, 49 in rataje_dlc4; same id as a module below (chunks 3002 to 3012)

LayerState = [555]:
    name                cstr        # e.g. "burnt_farms_01_rataje_north_burnt"
    enabled             u8          # 0 or 1
```

### Engine data

```
EngineData = chunks, each one of:
    [8359]  name cstr, value cstr   # text metadata: level, gameRules, build, checkPointName, saveTime
    [8360]  name cstr, value s32    # integer metadata: version (34), Bit (64)
    [8361]  name cstr, values TypedValue × (until the end of the chunk)
                                    # sections: Timer, TerrainState, GameTokens, ViewSystem,
                                    #           FlowSystem, MatFX, GameState

TypedValue
    type                u8          # see "Type codes"
    name_hash           u32         # FNV-1 of the field name; absent when type = 01
    value               ...         # depends on the type
```

Type `00` opens a **group**: the values that follow belong to it, up to the matching type `01`. Groups nest.

```
00 <hash of "BasicEntity">        begin group "BasicEntity"
   0f <hash of "id">  u32         value "id"
   06 <hash of "pos"> f32 × 3     value "pos"
   ...
01                                end group
```

#### Type codes

| Code | Type | Value | Code | Type | Value |
|---|---|---|---|---|---|
| `00` | begin group | (none) | `0a` | int16 | `s16`, never seen |
| `01` | end group (no name either) | (none) | `0b` | int32 | `s32` |
| `02` | string | `str16` | `0c` | int64 | `s64` |
| `03` | bool | `u8` | `0d` | uint8 | `u8` |
| `04` | float | `f32` | `0e` | uint16 | `u16`, never seen |
| `05` | Vec2 | `f32 × 2`, never seen | `0f` | uint32 | `u32` |
| `06` | Vec3 | `f32 × 3` | `10` | uint64 | `u64` |
| `07` | Quat (rotation) | `f32 × 4` | `11` | script value | `ScriptValue` |
| `08` | Ang3 (angles) | `f32 × 3` | `12` | time | `s64`, 1/100,000 s |
| `09` | int8 | `s8`, never seen | `13`, `14` | never seen | |

#### Script value layout

```
ScriptValue
    kind                u8
    then, depending on kind:
        1  nil                  (nothing)   # never seen
        2  boolean              u8
        3  handle               u64         # low half: an id, 3 distinct ones in all saves (see "Still unknown");
                                            # high half always 0x0B000000
        4  number               f32         # as a table key, always an s32 list index (1, 2, 3, ...)
        5  string               str16
        6  table                u8 (always 5), u32 pair_count,
                                then pair_count × (key ScriptValue, value ScriptValue)
        9  vector               f32 × 3     # expected from CryEngine, never seen
```

#### Field names

FNV-1 hashes ([§1.8](#cracking-the-name-encoding)). 270 of the 272 names used by all the saves are known; examples:

| Hash | Name |
|---|---|
| `0xA0E58D4E` | `curTime` |
| `0x407759E5` | `pos` |
| `0xC2ABDB30` | `BasicEntity` |
| `0x050C5D76` | `i` |
| `0x31AFD5A5` | `beguid` |

`build_field_names.py` rebuilds the full dictionary from the game's `WHGame.dll`.

### KCD modules

Chunk `[502]` holds one chunk per game module, always in this order:

```
Modules = chunks:
    [8080]  unknown
    [8081]  unknown
    [29451] = chunks:
        [1000]  PositionedRecord × n        # each one inside a chunk [0]
        [1001] = chunks:
            [1100]  byte[32]                # unknown
            [1101]  u32, f32, byte[4]       # zero in most saves; set in about one in five, of every type;
                                            # the last 4 bytes read as plausible f32 (0.7, -0.017...) where set
            [1102]  f32                     # -1.0
    [29443] = chunks:
        [3003]  GuidRecord × n              # each one inside a chunk [778]
        [3002]  u32 count, then count × [7782] (unknown content)
        [3008], [3009], [3011], [3012]      # unknown
    [29463] = chunks:
        [13611]                             # unknown
        [13609] u32 count, then count × [4446] Soul
        [13617] WorldClock
        [13612], [13613], [13614]           # unknown
        [13615] StatRecord × 183            # the statistics table, each one inside a chunk [6008]
        [13616]                             # unknown
    [29447] empty
    [29455] unknown
    [29459] unknown
    [29462] = chunks:
        [5498] × 85                         # u32 slot number, then a chunk [487] (unknown)
        [5499] ActiveEvent × n              # only while a dynamic event is running
    [29464] byte[5]                         # added by game update 1.9.7 or 1.9.8; unknown
    [29445], [29444], [29458], [29442]      # unknown
    [29452] ScriptState

PositionedRecord                            # 32 bytes, meaning unknown
    position            f32 × 3
    unknown_float       f32                 # 3.25 most often; also 0.05 and multiples of 0.25 up to 3.0
    unknown             u32 × 4

WorldClock                                  # 34 bytes
    clock               u64                 # in-game date and time: ms since midnight of day 0; a new game starts at 10:00
    unknown_counter_a   u64                 # world time at normal speed, in ms: grows by the in-game
                                            # time elapsed ÷ unknown_float, so it stops during pauses
                                            # and saves and races ahead during sleep; seems to also
                                            # count loading (§2.8)
    unknown_float       f32                 # always 15.0; probably the time scale: in-game seconds per real second (§2.8)
    unknown_flag_a      u8                  # 1 in a single save
    unknown_hours       f32                 # 12.0, 7.5 or 0.0 at various stages of the game
    unknown_flag_b      u8                  # 1 early in the game and in Theresa's level
    unknown_counter_b   u64                 # like unknown_counter_a, minus loading time (probably)

GuidRecord
    guid                guid
    chunks              [1584], then sometimes [1585]       # unknown content

Soul                                        # a character or an animal; a new game's souls all stay, even after death;
                                            # events and animals add souls that come and go
    guid                guid
    chunks              [4866] SoulIdentity, sometimes [4856], then [4858], [4869], [4860], sometimes [4872]

SoulIdentity
    guid                guid                # the same as the soul's
    name                cstr                # e.g. "rych_stepan", "_Sheep18"
    unknown             byte[8]

ActiveEvent = chunks:
    [4979]  u32
    [4980]  u32
    [4981]  cstr                            # the event's name, e.g. "event_rat_city"
    [4984]  byte[8]
    [4983]  f32

ScriptState
    unknown             u32                 # always 0
    chunks              [3214] ScriptNames, then 11 more chunks (unknown content)

ScriptNames = chunks:
    [2100]  StringTable                     # about 12,000 names used by the scripts
    [2101]  StringTable                     # 1,528 script type names, identical in all saves
    [2102]  unknown

StringTable
    unknown             u8                  # always 0
    entries             (index u16, text cstr) × n      # index = 0, 1, 2, ...
    count               u16                 # = n
```

#### Statistics

```
StatRecord
    key                 u32                 # 1 to 183
    value               (optional) one chunk, depending on its id:
        [14223]  s32                                        # IntegerSum
        [14224]  f64                                        # DecimalSum
        [14225]  u32 count, then count × guid               # DistinctGuid
        [14226]  u32 count, then count × u32                # DistinctUint
        [14227]  empty                                      # IntegerProxy
        [14228]  empty                                      # DecimalProxy
        [14229]  u32                                        # IntegerMaxProxy
        [14230]  chunk [26852]: u8 flag, then u64 (ms)      # WorldTime
        [14232]  u8 flag, then f64                          # PlayTime
        [14234]  chunk [26852]: u8 flag, then u64 (ms)      # WorldTimeSampling
        [14235]  chunk [26852]: u8 flag, then u64 (ms)      # WorldTimeResetSampling
        [14236]  u32                                        # Script
        [14237]  u32                                        # Quest
        [14238]  cstr                                       # String
        [14239]  empty                                      # SoulLevel
        [14242]  empty                                      # SoulDerivStat
```

Each value chunk id stands for one statistic type of the game's `statistic.xml` ([§2.10](#210-mine-the-programs-own-files)), named in the comments: the `type` of all 183 statistics matches the chunk id of their value.

| Key | Meaning |
|---|---|
| 1 | `TotalTimePlayed`, "Total time played": global, so its record in the save has no value. Kept in Steam's stats for the game (`Steam\appcache\stats\UserGameStats_<user>_379430.bin`, stat 2, `f32` hours). Counts nearly all the time the game runs, main menu included |
| 81 | `TimePlayed`, "Time played in playline": play time in hours (`f64`), shown in the load menu truncated to one decimal |
| 37 | `TimeIngame`, "World time passed" in the Statistics tab (shown in days, rounded to one decimal): in-game time elapsed, in milliseconds, time skips included, pauses excluded; not the clock (see `WorldClock`) |
| 50 | `TimeSlept`, "Time slept": in-game time spent sleeping, in milliseconds |
| 61, 62, 89 | `CurrentStarvingTime`, `CurrentOvereatTime`, `CurrentProperDietTime` (hidden, no label): in-game time, in milliseconds, that resets from time to time (type `WorldTimeResetSampling`) |
| 55 | `ThreatsSucceded`, "Intimidation successes" |
| 96, 97, 98 | `CurrentMainQuest`, `LastStatLevelUp`, `LastSkillLevelUp` (hidden, text); #97 is already set at the start |
| others | named in the game's `statistic.xml` ([§2.10](#210-mine-the-programs-own-files)); the numbers only go up during a playthrough |

A new game's #37 can count a clock jump during its setup:

| New game started from | Level involved | #37 counts | Times seen |
|---|---|---|---|
| The main menu, after a fresh launch | Most recent save in the main world, or no save at all | 0 h | 5 |
| The pause menu of a game in progress | That game in the main world, prologue included | 1 h | 3 |
| The pause menu of a game in progress | That game in Theresa's DLC level | 10 h | 2 |
| The main menu, after a fresh launch | Most recent save in Theresa's DLC level | 10 h | 3 |

Statistics keep counting inside a DLC level, and the switch save doesn't restore them ([DLC levels](#dlc-levels)).

### Reference values

The 8 reference saves, in date order. A parser can be checked against these values, file by file:

| Save | Game | Type | Number | Blocks | Payload bytes | Souls | `[2100]` names | Play time (h) |
|---|---|---|---|---|---|---|---|---|
| `permanent001` | 1.9.6 | 0 | 1 | 816 | 26,715,957 | 2,661 | 11,937 | 0.057 |
| `save508` | 1.9.6 | 2 | 508 | 969 | 31,734,373 | 2,714 | 12,124 | 136.541 |
| `exit` | 1.9.6 | 5 | 678 | 988 | 32,369,092 | 2,696 | 12,156 | 181.004 |
| `autosave689` | 1.9.6 | 1 | 689 | 989 | 32,405,701 | 2,701 | 12,113 | 185.476 |
| `autosave769` | 1.9.6 | 1 | 769 | 1,008 | 33,016,116 | 2,698 | 12,052 | 199.488 |
| `autosave770` | 1.9.6 | 1 | 770 | 1,010 | 33,089,294 | 2,694 | 12,100 | 199.671 |
| `autosave798` | 1.9.6 | 1 | 798 | 1,041 | 34,093,768 | 2,694 | 11,998 | 204.023 |
| `autosave799` | 1.9.8 | 1 | 799 | 1,028 | 33,673,789 | 2,695 | 12,017 | 204.046 |

---

## Lessons learned

- **An exact fit is the strongest evidence.** Rules that consume megabytes up to the last byte are right; a rule that "fits" 12 bytes proves nothing.
- **Coincidences are everywhere at 16 bits.** When searching for a small number (such as the save number 508), random data matches in many places. Only trust matches that are unique and repeat across files.
- **Distrust your own tools.** When something looks strange, re-check with a stricter reader before believing it.
- **Labels can mislead.** `build` is not the game version, and the menu truncates what the file stores at full precision.
- **Know your libraries.** Since 3.14, Python on Windows ships zlib-ng, whose output is valid but not byte-identical to classic zlib. Python's `zipfile` rejects some of the game's archives (`Data/Tables.pak`), whose file names use `\` in one place and `/` in another.
- **A statistic is not a state.** #37 matched the clock in one save; the same moment of another playthrough showed 0, and the clock was stored elsewhere.
- **Provoke the event instead of hunting for it.** Several comparisons of old saves only made the switch save's role likely; reloading a save and entering the DLC again proved it with two fresh files.
- **Explain a constant through its neighbors.** The `15.0` stored in every save meant nothing alone; once the two counters next to it were measured against the clock, it turned out to be the ratio between them.
- **Use source code for the vocabulary and the bytes for the grammar.** The engine said which names and types to expect; only the bytes said how Warhorse encoded them.

## Still unknown

- The `u32 20` at the start of the payload, the two `200` values in the header, and the meaning of the header's `unknown_flag`.
- The trailing byte, which varies from save to save (probably uninitialized memory).
- The byte `05` at the start of every script table.
- What script handles refer to. Nearly all hold `0x04680F84` in their low half; the few others hold `0x0128375B` or `0x0313F220`. None of these is an entity id of `GameState`, and all three recur in modules `[29444]` and `[29452]`.
- Two field names, `0x51D7C884` and `0x51D7C882`, used in all the saves; [§2.9](#29-recover-hashed-names-from-the-program-binary) gives a lead.
- Most modules marked "unknown" in [part 3](#kcd-modules).
- Whether the game rejects a save with a wrong MD5.
- How "switch" save numbers are chosen: 51141 and 3227 don't come from the global counter.
- The other fields of `[13617]`: a value of 12.0, 7.5 or 0.0 with two flags.
- Why the counters of `[13617]` fall behind the clock over a playthrough: at 204 hours of play, the clock ÷ 15 gives 320 hours but counter B holds 294, so about 380 in-game hours passed without being counted (fast travel or scripted time skips, perhaps). And why they still grow at the start of the prologue, where the clock is frozen at 10:00.
- Why a new game's #37 counts 10 hours of its setup whenever Theresa's DLC level was involved, and 0 or 1 hour otherwise.
- Where hardcore mode is recorded: there is a `hardcore_mode` layer and a script variable `isHardcoreModeActive` whose value is presumably in the undecoded script data. A save from a hardcore game would settle it.

## Tools in this repository

| File | What it does |
|---|---|
| [`inspect_save.py`](../inspect_save.py) | Shows everything known about one save; options `--section`, `--layers`, `--souls`, `--tree`, `--lang` |
| [`compare_saves.py`](../compare_saves.py) | Shows what changed between saves: modules, chunks, layers, statistics |
| [`whs_decompress.py`](../whs_decompress.py) | Writes a save's decompressed payload to a file and checks its MD5 |
| [`build_field_names.py`](../build_field_names.py) | Rebuilds the field-name dictionary from the game's `WHGame.dll` |

## Terms

- **Chunk:** an id, a size and a body; bodies can hold more chunks ("tag-length-value").
- **Container / leaf:** a chunk whose body is more chunks, or one whose body is values.
- **Entity:** an object of the game world (character, item, door, ...), in CryEngine's vocabulary.
- **Exact fit:** a description that accounts for every byte of the data, no more, no less.
- **Known-plaintext test:** identifying a function by comparing its known input with its observed output.
- **Layer:** a named group of world objects the game switches on or off.
- **Magic number:** fixed bytes that identify a format (here `0XBP`).
- **Payload:** the save's content once decompressed.
- **Section:** one of the named blocks of engine data (`Timer`, `GameState`...).
- **Soul:** KCD's name for a character or an animal and its data.
- **Typed value:** one saved value: type code, name hash, value.

## References

- CryEngine source code in Amazon Lumberyard: <https://github.com/aws/lumberyard>
  - Compressed save writer: [`XMLCPB_Common.h`](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/XMLCPBin/XMLCPB_Common.h), [`XMLCPB_ZLibCompressor.cpp`](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/XMLCPBin/Writer/XMLCPB_ZLibCompressor.cpp), [`XMLCPB_ZLibCompressor.h`](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/XMLCPBin/Writer/XMLCPB_ZLibCompressor.h), [`XMLCPB_Reader.cpp`](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/XMLCPBin/Reader/XMLCPB_Reader.cpp)
  - Save games: [`ISaveGame.h`](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CryCommon/ISaveGame.h), [`GameSerialize.cpp`](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/GameSerialize.cpp), [`GameSerializeHelpers.h`](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryAction/Serialization/GameSerializeHelpers.h), [`EntitySystem.cpp`](https://github.com/aws/lumberyard/blob/master/dev/Gems/CryLegacy/Code/Source/CryEntitySystem/EntitySystem.cpp)
  - Value serialization: [`ISerialize.h`](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CryCommon/ISerialize.h), [`SerializationTypes.h`](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CryCommon/SerializationTypes.h), [`IScriptSystem.h`](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CryCommon/IScriptSystem.h), [`TimeValue.h`](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CryCommon/TimeValue.h), [`Timer.cpp`](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CrySystem/Timer.cpp), [`ISystem.h`](https://github.com/aws/lumberyard/blob/master/dev/Code/CryEngine/CryCommon/ISystem.h)
- zlib format, RFC 1950: <https://www.rfc-editor.org/rfc/rfc1950>
- IEEE 754 floating point: <https://en.wikipedia.org/wiki/IEEE_754>
- FNV hash: <http://www.isthe.com/chongo/tech/comp/fnv/>
- C++ multi-character literals: <https://en.cppreference.com/w/cpp/language/character_literal>
- HxD hex editor: <https://mh-nexus.de/en/hxd/>
