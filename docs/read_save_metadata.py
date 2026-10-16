from argparse import ArgumentParser
from dataclasses import asdict, dataclass, field
from io import TextIOWrapper
from pathlib import Path
from sys import stderr, stdout
from datetime import datetime, timezone
from typing import Any
from parse_decompressed_payload import Chunk, ParsedPayload, parse_decompressed_payload

@dataclass
class SaveMetadata:
    type: int
    number: int
    timestamp: int
    map: str
    serialized_info: str
    serialized_info_2: str
    undetermined_1: int
    undetermined_2: int
    skalitz_burnt: bool
    dlc_count: int
    dlcs: list[tuple[int, str]] = field(default_factory=list)

    def timestamp_to_date(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)

    def props(self) -> dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:
        return f"Save no. {self.number}" + "\n" + "\n".join(" " * 2 + ln for ln in [
            f"Type: {self.type}",
            f"Timestamp: {self.timestamp} ({self.timestamp_to_date()})",
            f"Game level/map: {self.map}",
            f"Serialized info: {self.serialized_info}",
            f"Serialized info 2: {self.serialized_info_2}",
            f"Undetermined value 1: {self.undetermined_1}",
            f"Undetermined value 2: {self.undetermined_2}",
            f"Is Skalitz burnt?: {self.skalitz_burnt}",
            f"{self.dlc_count} DLCs installed:",
            *[f"  - {dlc_id}: {dlc_title}" for dlc_id, dlc_title in self.dlcs]
        ])

def parse_next_strings(b: bytes, count: int) -> tuple[list[str], int]:
    strings: list[str] = []
    offset = 0

    while len(strings) < count:
        if (next_nul := b.find(b"\0", offset)) == -1:
            raise ValueError(f"Could not find {count} successive NUL-terminated strings.")

        cstring = b[offset:next_nul+1]
        strings.append(cstring.rstrip(b"\0").decode(encoding="utf8", errors="replace"))
        offset = next_nul+1

    return strings, offset

def parse_bool(data: bytes) -> bool:
    if len(data) != 1:
        raise ValueError("A boolean must be on a single byte.")

    if int.from_bytes(data) not in (0, 1):
        raise ValueError(f"A boolean byte must not contain any '1' bit apart from the least significant one. Allowed values are 00000000 and 00000001, got {data[0]:08b}.")

    return bool.from_bytes(data)

def parse_chunk_13(chunk: Chunk) -> SaveMetadata:
    assert chunk.type_id == 13

    if chunk.children or chunk.byte_content is None:
        raise ValueError("Chunk 13 was not parsed correctly!")

    save_type = int.from_bytes(chunk.byte_content[0:4], byteorder="little", signed=False)
    save_number = int.from_bytes(chunk.byte_content[4:8], byteorder="little", signed=False)
    timestamp = int.from_bytes(chunk.byte_content[8:16], byteorder="little", signed=True)
    offset = 16
    [game_map, serialized_info, serialized_info_2], blen = parse_next_strings(chunk.byte_content[offset:], 3)
    offset += blen
    undetermined_1 = int.from_bytes(chunk.byte_content[offset:offset+4], byteorder="little", signed=False)
    offset += 4
    undetermined_2 = int.from_bytes(chunk.byte_content[offset:offset+4], byteorder="little", signed=False)
    offset += 4
    skalitz_burnt = parse_bool(chunk.byte_content[offset:offset+1])
    offset += 1
    dlc_count = int.from_bytes(chunk.byte_content[offset:offset+2], byteorder="little", signed=False)
    offset += 2

    dlcs: list[tuple[int, str]] = []
    while len(dlcs) < dlc_count:
        if len(chunk.byte_content[offset:]) < 5:  # DLC id (4 bytes) + one NUL byte at least
            raise ValueError("Cannot parse correctly the list of DLCs.")

        dlc_id = int.from_bytes(chunk.byte_content[offset:offset+4], byteorder="little", signed=False)
        offset += 4
        [dlc_title], blen = parse_next_strings(chunk.byte_content[offset:], 1)
        offset += blen
        dlcs.append((dlc_id, dlc_title))

    if offset != len(chunk.byte_content):
        print(f"Warning: chunk 13 has {len(chunk.byte_content)} bytes, expected {offset}.", file=stderr)

    return SaveMetadata(save_type, save_number, timestamp, game_map, serialized_info, serialized_info_2, undetermined_1, undetermined_2, skalitz_burnt, dlc_count, dlcs)

def parse_chunk_16(chunk: Chunk) -> bytes:
    assert chunk.type_id == 16

    if chunk.children or chunk.byte_content is None:
        raise ValueError("Chunk 16 was not parsed correctly!")

    return chunk.byte_content

def parse_chunk_17(chunk: Chunk) -> int:
    assert chunk.type_id == 17

    if chunk.children or chunk.byte_content is None:
        raise ValueError("Chunk 17 was not parsed correctly!")

    if len(chunk.byte_content) != 4:
        print(f"Warning: chunk 17 has {len(chunk.byte_content)} bytes, expected 4.", file=stderr)

    return int.from_bytes(chunk.byte_content, byteorder="little", signed=False)

@dataclass
class Mod:
    folder: str
    name: str
    description: str
    author: str
    version: str
    version_2: str

    def __str__(self) -> str:
        return "\n".join(f"{k}: {v}" for k, v in asdict(self).items())

def parse_chunk_14(chunk: Chunk) -> list[Mod]:
    assert chunk.type_id == 14

    if chunk.children or chunk.byte_content is None:
        raise ValueError("Chunk 14 was not parsed correctly!")

    mod_count = int.from_bytes(chunk.byte_content[:4], byteorder="little", signed=False)

    mods: list[Mod] = []
    offset = 4

    while len(mods) < mod_count:
        if len(chunk.byte_content[offset:]) < 6:  # 6 NUL bytes per mod
            raise ValueError("Cannot parse correctly the list of mods.")

        strings, blen = parse_next_strings(chunk.byte_content[offset:], 6)
        offset += blen
        mods.append(Mod(*strings))

    if offset != len(chunk.byte_content):
        print(f"Warning: chunk 14 has {len(chunk.byte_content)} bytes, expected {offset}.", file=stderr)

    return mods


# ================================================================

if isinstance(stdout, TextIOWrapper):
    stdout.reconfigure(encoding="utf-8")

parser = ArgumentParser()
parser.add_argument("payload")
args = parser.parse_args()
payload_path = Path(args.payload).resolve()

if not payload_path.is_file():
    print("Input decompressed payload file does not exist!", file=stderr)
    exit(1)

payload: ParsedPayload = parse_decompressed_payload(payload_path)

root_chunk_501 = payload.chunks[0]

if root_chunk_501.type_id != 501:
    print("Root chunk 501 not found!", file=stderr)
    exit(1)

chunk_13 = root_chunk_501.find_child_by_type(13)

if chunk_13 is None:
    print("Chunk 13 not found!", file=stderr)
    exit(1)

save_metadata: SaveMetadata = parse_chunk_13(chunk_13)
print(save_metadata)

chunk_16 = root_chunk_501.find_child_by_type(16)

if chunk_16 is None:
    print("Chunk 16 not found!", file=stderr)
    exit(1)

print()
print(f"Chunk 16: {parse_chunk_16(chunk_16).hex(" ")}")

chunk_17 = root_chunk_501.find_child_by_type(17)

if chunk_17:
    switch_save_number: int = parse_chunk_17(chunk_17)
    print()
    print(f"Switch number: {switch_save_number}")

chunk_14 = root_chunk_501.find_child_by_type(14)

if chunk_14:
    mods: list[Mod] = parse_chunk_14(chunk_14)

    print()
    print(f"{len(mods)} mods:")
    for i, mod in enumerate(mods, start=1):
        print(f"{i}:")
        print("\n".join(" "*2 + ln for ln in str(mod).splitlines()))
