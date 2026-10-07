from argparse import ArgumentParser
from io import SEEK_SET
import zlib
from sys import stderr
from pathlib import Path

FOOTER_SIZE = 64  # in bytes
ZLIB_BLOCK_HEADER_SIZE = 8  # in bytes
NO_ZLIB_USED_FLAG = 0xffffffff

parser = ArgumentParser()
parser.add_argument("savefile")
args = parser.parse_args()
savefile = Path(args.savefile).resolve()

if not savefile.is_file():
    print("Input save file does not exist!", file=stderr)
    exit(1)

file_size = savefile.stat().st_size
offset: int = 0  # the next block offset
block_i: int = 0

with savefile.open("rb") as file:
    while offset <= (file_size - FOOTER_SIZE - ZLIB_BLOCK_HEADER_SIZE):
        file.seek(offset, SEEK_SET)
        block_header_bytes = file.read(ZLIB_BLOCK_HEADER_SIZE)
        compressed_size = int.from_bytes(block_header_bytes[:4], byteorder="little", signed=False)
        uncompressed_size = int.from_bytes(block_header_bytes[4:], byteorder="little", signed=False)
        block_size = compressed_size if compressed_size != NO_ZLIB_USED_FLAG else uncompressed_size

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

    # If everything adds up cleanly, `offset` should be at the footer's first byte.
    if offset < (file_size - FOOTER_SIZE):
        print("\033[31mLast block's declared size leaves a few trailing bytes before the footer!\033[0m")
    elif offset > (file_size - FOOTER_SIZE):
        print("\033[31mLast block's declared size overlaps the footer!\033[0m")
