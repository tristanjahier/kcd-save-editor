"""Decompress Kingdom Come: Deliverance (1) .whs saves into their raw payload.

The payload is what ksy/kcd_save_payload.ksy describes: open it in the Kaitai
Web IDE (https://ide.kaitai.io) together with that spec.

Usage: python whs_decompress.py SAVE.whs [SAVE.whs ...] [-o OUTPUT_DIR]
"""
import argparse
import hashlib
import struct
import sys
import zlib
from pathlib import Path

FOOTER_SIZE = 64
FOOTER_MAGIC = b"0XBP"  # 'PBX0' stored as a little-endian u32
MD5_OFFSET = 4
MD5_SIZE = 16
RAW_BLOCK = 0xFFFFFFFF


def decompress(data: bytes) -> tuple[bytes, bool, int]:
    """Return (payload, md5_ok, block_count) for the content of a .whs file."""
    footer_pos = len(data) - FOOTER_SIZE
    if footer_pos < 0 or data[footer_pos:footer_pos + 4] != FOOTER_MAGIC:
        raise ValueError("no 'PBX0' footer: not a KCD save")

    md5_pos = footer_pos + MD5_OFFSET
    stored_md5 = data[md5_pos:md5_pos + MD5_SIZE]
    computed_md5 = hashlib.md5(data[:md5_pos] + bytes(MD5_SIZE) + data[md5_pos + MD5_SIZE:]).digest()

    payload = bytearray()
    pos = blocks = 0
    while pos < footer_pos:
        len_compressed, len_uncompressed = struct.unpack_from("<II", data, pos)
        pos += 8
        if len_compressed == RAW_BLOCK:
            block = data[pos:pos + len_uncompressed]
            pos += len_uncompressed
        else:
            block = zlib.decompress(data[pos:pos + len_compressed])
            pos += len_compressed
        if len(block) != len_uncompressed:
            raise ValueError(f"block {blocks}: expected {len_uncompressed} bytes, got {len(block)}")
        payload += block
        blocks += 1
    if pos != footer_pos:
        raise ValueError("the last block overlaps the footer")

    return bytes(payload), stored_md5 == computed_md5, blocks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("saves", nargs="+", type=Path, help=".whs files to decompress")
    parser.add_argument("-o", "--output-dir", type=Path, help="where to write the payloads (default: next to each save)")
    args = parser.parse_args()

    failed = False
    for save in args.saves:
        try:
            payload, md5_ok, blocks = decompress(save.read_bytes())
        except (OSError, ValueError, zlib.error) as e:
            print(f"{save}: {e}", file=sys.stderr)
            failed = True
            continue
        out = (args.output_dir or save.parent) / f"{save.stem}.payload.bin"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(payload)
        print(f"{save} -> {out} ({len(payload):,} bytes, {blocks} blocks, MD5 {'OK' if md5_ok else 'MISMATCH'})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
