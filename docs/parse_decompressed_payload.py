from argparse import ArgumentParser
from io import SEEK_SET, TextIOWrapper
from sys import stderr, stdout
from pathlib import Path
from dataclasses import dataclass, field
from typing import Self

CHUNK_HEADER_SIZE = 6  # in bytes

@dataclass
class Chunk:
    offset: int
    """The offset of the first byte of the chunk (header)"""
    type_id: int
    """The type of the chunk"""
    length: int
    """The length of the chunk's content (excluding its header), in bytes"""
    parent: Self|None = field(compare=False)
    """The chunk's parent"""
    children: list[Self] = field(default_factory=list, compare=False, repr=False)
    """The chunk's children"""
    byte_content: bytes|None = field(default=None, repr=False)
    """The unparsed payload's bytes"""

    def end(self) -> int:
        """Exclusive, last byte offset + 1"""
        return self.offset + CHUNK_HEADER_SIZE + self.length

    def is_root(self) -> bool:
        return not self.parent

    def is_leaf(self) -> bool:
        return not self.children

    def branch_depth(self) -> int:
        if not self.children:
            return 0

        return max(child.branch_depth() for child in self.children) + 1

    def find_child_by_type(self, type_id: int) -> Self | None:
        return next((child for child in self.children if child.type_id == type_id), None)

    def get_children_by_type(self, type_id: int) -> list[Self]:
        return [child for child in self.children if child.type_id == type_id]

    def __str__(self) -> str:
        return f"[\033[36m{hex(self.offset)}\033[0m | type: \033[93m{self.type_id}\033[0m | length: {self.length} | children: {len(self.children)}]"

@dataclass
class ParsedPayload:
    chunks: list[Chunk]
    """All the chunks parsed from the payload."""
    leading_bytes: bytes
    """The four leading bytes before the first root chunk."""
    trailing_bytes: bytes
    """The trailing bytes after the last root chunk."""
    warnings: list[str] = field(default_factory=list)
    """Non-blocking errors."""

    def roots(self) -> list[Chunk]:
        return [chunk for chunk in self.chunks if chunk.is_root()]

    def max_depth(self) -> int:
        return max((chunk.branch_depth() for chunk in self.roots()), default=0)

def parse_chunk_header(header_bytes: bytes) -> tuple[int, int]:
    chunk_type_id = int.from_bytes(header_bytes[:2], byteorder="little", signed=False)
    chunk_length = int.from_bytes(header_bytes[2:], byteorder="little", signed=False)
    return chunk_type_id, chunk_length

def decode_ascii_strings(data: bytes) -> list[str]:
    """Render bytes as strings split on NUL; printable ASCII bytes as their char, others as the replacement character �."""
    string = ""

    for byte in data:
        if 0x20 <= byte < 0x7F or byte == 0x00:
            string += chr(byte)
        else:
            string += "\ufffd"

    return [s for s in string.split(chr(0x00)) if s != ""]  # split strings on null char

def parse_decompressed_payload(filepath: Path) -> ParsedPayload:
    file_size = filepath.stat().st_size
    chunks: list[Chunk] = list()
    last_chunk_end = 4

    with filepath.open("rb") as file:
        leading_bytes = file.read(4)  # we don't know what it is yet

        offset: int  # the current offset we're at ; tied to the iteration, can differ from the file reader's cursor
        chunk_stack = list()

        # Stop scanning when there is no room left for a chunk header to be found.
        while (offset := file.tell()) <= (file_size - CHUNK_HEADER_SIZE):
            current_chunk = chunk_stack[-1] if chunk_stack else None  # the chunk that we are currently exploring

            # If we reached the end of the chunk, there is nothing left to see.
            if current_chunk and offset == current_chunk.end():
                chunk_stack.pop()
                continue

            chunk_type_id, chunk_length = parse_chunk_header(file.read(CHUNK_HEADER_SIZE))
            chunk_end = offset + CHUNK_HEADER_SIZE + chunk_length

            # If it seems like the data is NOT a valid chunk header.
            if current_chunk and chunk_end > current_chunk.end():
                file.seek(offset, SEEK_SET)
                chunk_stack.pop()
                leaf_bytes = file.read(current_chunk.end() - offset)
                current_chunk.byte_content = leaf_bytes
                continue

            chunk = Chunk(offset=offset, type_id=chunk_type_id, length=chunk_length, parent=current_chunk)
            chunk_stack.append(chunk)

            if current_chunk:
                current_chunk.children.append(chunk)

            chunks.append(chunk)
            last_chunk_end = max(last_chunk_end, chunk_end)

        file.seek(last_chunk_end, SEEK_SET)
        trailing_size = file_size - last_chunk_end
        trailing_bytes = file.read(trailing_size) if trailing_size > 0 else bytes()

    warnings: list[str] = []

    if trailing_size > 1:
        warnings.append("Last chunk's declared length leaves more than one trailing byte!")
    elif trailing_size == 0:
        warnings.append("Last chunk's declared length leaves no trailing bytes!")
    elif trailing_size < 0:
        warnings.append("Last chunk's declared length overlaps the end!")

    return ParsedPayload(chunks, leading_bytes, trailing_bytes, warnings)

def display_chunk_subtree(chunk: Chunk, depth: int = 0, max_depth: int|None = None, decode_strings: bool = False):
    print(f"{depth * "  "}{chunk}")

    indent = (depth+1) * "  "

    if chunk.children and chunk.byte_content is not None:
        print(f"{indent}\033[33m-- children don't fill the chunk: possibly accidental --\033[0m")

    if chunk.children and max_depth is not None and depth >= max_depth:
        print(f"{indent}\033[90m-- maximum depth reached: content skipped --\033[0m")
        return

    for child in chunk.children:
        display_chunk_subtree(child, depth+1, max_depth, decode_strings)

    if chunk.byte_content is not None:
        excerpt = chunk.byte_content[:32]
        print(f"{indent}\033[90m-- unparsed content --\033[0m")
        ellipsis = " …" if len(chunk.byte_content) > len(excerpt) else ""
        print(f"{indent}\033[90m{excerpt.hex(" ")}{ellipsis}\033[0m")
        if decode_strings and (strings := decode_ascii_strings(excerpt)):
            print(f"{indent}\033[90m{" ".join(('"'+s+'"' for s in strings))}{ellipsis}\033[0m")

def group_chunks_by_type(chunks: list[Chunk]) -> dict[int, list[Chunk]]:
    groups = {}

    for chunk in chunks:
        groups.setdefault(chunk.type_id, []).append(chunk)

    return groups

# ================================================================

if __name__ == "__main__":
    if isinstance(stdout, TextIOWrapper):
        stdout.reconfigure(encoding="utf-8")

    parser = ArgumentParser()
    parser.add_argument("payload")
    parser.add_argument("--max-depth", type=int, help="maximum depth reachable. 0 is first level. no limit if omitted.")
    parser.add_argument("--decode-strings", action="store_true", help="whether to try to decode bytes into strings")
    parser.add_argument("--count-by-type", action="store_true", help="whether to count chunks by type")
    args = parser.parse_args()
    payload_path = Path(args.payload).resolve()

    if not payload_path.is_file():
        print("Input decompressed payload file does not exist!", file=stderr)
        exit(1)

    payload = parse_decompressed_payload(payload_path)

    for chunk in payload.roots():
        display_chunk_subtree(chunk, max_depth=args.max_depth, decode_strings=args.decode_strings)

    print()
    print(f"{len(payload.chunks):,} chunks scanned. Maximum depth: {payload.max_depth()}. Leading bytes: \033[90m{payload.leading_bytes.hex(" ")}\033[0m. Trailing bytes: \033[90m{payload.trailing_bytes.hex(" ")}\033[0m.")

    for warning in payload.warnings:
        print(f"\033[31m{warning}\033[0m", file=stderr)

    if args.count_by_type:
        print("", "=" * 32, "Breakdown of chunks per type ID (largest first):", sep="\n")

        for type, group in sorted(group_chunks_by_type(payload.chunks).items(), key=lambda g: len(g[1]), reverse=True):
            print(f"- \033[93m{type}\033[0m: {len(group)}")
