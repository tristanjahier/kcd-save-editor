"""Name the hashed fields of KCD saves, using the game's own code.

Typed values in a save only store a 32-bit FNV-1 hash of their field name. The
names are string literals in the game's WHGame.dll: this tool hashes every
string of the DLL, keeps the ones whose hash occurs in the given saves, and
writes them into the `field_name` enum of kcd_save_payload.ksy. Names
already in the enum are kept, so it can be re-run on new saves or after a game
update.

Usage: python build_field_names.py SAVE.whs [SAVE.whs ...] [--dll PATH/TO/WHGame.dll]
"""
import argparse
import collections
import itertools
import keyword
import re
import struct
import sys
from pathlib import Path

from whs_decompress import decompress

DEFAULT_DLL = Path("C:/Program Files (x86)/Steam/steamapps/common/KingdomComeDeliverance/Bin/Win64/WHGame.dll")
DEFAULT_KSY = Path(__file__).with_name("kcd_save_payload.ksy")
BEGIN_MARKER = "  # BEGIN field_name"
END_MARKER = "  # END field_name"
ENTRY = re.compile(r'^\s+0x([0-9a-f]{8}): \{id: ([a-z][a-z0-9_]*), doc: "((?:[^"\\]|\\.)*)"\}(.*)$')

# Payload bytes of the fixed-size typed values and script values, by type code (see the ksy enums).
TYPED_VALUE_SIZES = {0x00: 0, 0x03: 1, 0x04: 4, 0x05: 8, 0x06: 12, 0x07: 16, 0x08: 12, 0x09: 1,
                     0x0A: 2, 0x0B: 4, 0x0C: 8, 0x0D: 1, 0x0E: 2, 0x0F: 4, 0x10: 8, 0x12: 8}
SCRIPT_VALUE_SIZES = {1: 0, 2: 1, 3: 8, 4: 4, 9: 12}

# Words that would break the code generated from the ksy in some languages.
RESERVED = set(keyword.kwlist) | {
    "bool", "case", "catch", "char", "class", "const", "default", "delete", "double", "enum", "extern",
    "float", "function", "goto", "int", "interface", "let", "long", "namespace", "new", "null",
    "operator", "package", "private", "protected", "public", "short", "signed", "sizeof", "static",
    "string", "struct", "super", "switch", "template", "this", "throw", "true", "false", "typeof",
    "union", "unsigned", "var", "virtual", "void", "volatile"}


def fnv1(name: bytes) -> int:
    h = 0x811C9DC5
    for byte in name:
        h = ((h * 0x01000193) & 0xFFFFFFFF) ^ byte
    return h


# ------------------------------------------------------------------ hashes used by the saves

def chunks(buf: bytes, start: int, end: int):
    """Yield (id, body_start, body_end) for each chunk of buf[start:end]."""
    pos = start
    while pos + 6 <= end:
        chunk_id, size = struct.unpack_from("<HI", buf, pos)
        yield chunk_id, pos + 6, pos + 6 + size
        pos += 6 + size


def skip_script_value(buf: bytes, pos: int) -> int:
    kind = buf[pos]
    if kind in SCRIPT_VALUE_SIZES:
        return pos + 1 + SCRIPT_VALUE_SIZES[kind]
    if kind == 5:  # string
        return pos + 3 + struct.unpack_from("<H", buf, pos + 1)[0]
    if kind == 6:  # table: u1, u4 pair count, key/value pairs
        num_pairs = struct.unpack_from("<I", buf, pos + 2)[0]
        pos += 6
        for _ in range(2 * num_pairs):
            pos = skip_script_value(buf, pos)
        return pos
    raise ValueError(f"unknown script value kind {kind} at {pos:#x}")


def count_typed_value_hashes(buf: bytes, pos: int, end: int, counts: collections.Counter) -> None:
    """Count the name hashes of the typed values in buf[pos:end]; fails unless they fill it exactly, every group closed."""
    depth = 0
    while pos < end:
        kind = buf[pos]
        if kind == 0x01:  # end of group, no name
            depth -= 1
            if depth < 0:
                raise ValueError(f"end of group without a beginning at {pos:#x}")
            pos += 1
            continue
        counts[struct.unpack_from("<I", buf, pos + 1)[0]] += 1
        pos += 5
        if kind == 0x00:  # begin group, no value
            depth += 1
        elif kind == 0x02:  # string
            pos += 2 + struct.unpack_from("<H", buf, pos)[0]
        elif kind == 0x11:  # script value
            pos = skip_script_value(buf, pos)
        elif kind in TYPED_VALUE_SIZES:
            pos += TYPED_VALUE_SIZES[kind]
        else:
            raise ValueError(f"unknown typed value type {kind:#x} at {pos - 5:#x}")
    if pos != end:
        raise ValueError(f"last value ends at {pos:#x}, past the end {end:#x}")
    if depth:
        raise ValueError(f"{depth} group(s) not closed at {end:#x}")


def used_hashes(payload: bytes) -> collections.Counter:
    """Count the field-name hashes used by the engine sections (body 500 > 503 > 8361) of a payload."""
    counts = collections.Counter()
    for chunk_id, start, end in chunks(payload, 4, len(payload)):
        if chunk_id != 500:
            continue
        for section_list_id, list_start, list_end in chunks(payload, start, end):
            if section_list_id != 503:
                continue
            for entry_id, entry_start, entry_end in chunks(payload, list_start, list_end):
                if entry_id == 8361:
                    values_start = payload.index(b"\0", entry_start) + 1  # skip the section name
                    count_typed_value_hashes(payload, values_start, entry_end, counts)
    return counts


# ------------------------------------------------------------------ candidate names from the DLL

def dll_candidates(dll: bytes) -> set[bytes]:
    """Every printable string of the DLL (ASCII and UTF-16), its dotted paths and its identifiers."""
    strings = set(re.findall(rb"[\x20-\x7e]{1,128}", dll))
    strings |= {s.decode("utf-16-le").encode("ascii") for s in re.findall(rb"(?:[\x20-\x7e]\x00){1,128}", dll)}
    candidates = set(strings)
    for s in strings:
        candidates.update(re.findall(rb"[A-Za-z_][A-Za-z0-9_.]*", s))  # e.g. "colliderSize.Min"
        candidates.update(re.findall(rb"[A-Za-z_][A-Za-z0-9_]*", s))
    candidates |= {c[2:] for c in candidates if c.startswith(b"m_")}
    candidates.discard(b"")
    return candidates


def short_names(max_len: int = 3):
    """All identifiers up to max_len characters (names like "i" or "q" are too short to find as strings)."""
    alphabet = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
    for length in range(1, max_len + 1):
        for chars in itertools.product(alphabet, repeat=length):
            yield bytes(chars)


# ------------------------------------------------------------------ ksy enum

def enum_id(name: str) -> str:
    """camelCase / dotted name -> Kaitai identifier (lowercase snake_case)."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    if not s or not s[0].isalpha():
        s = "n_" + s
    return s + "_" if s in RESERVED else s


def read_enum(ksy_text: str) -> dict[int, tuple[str, str, str]]:
    """Entries of the generated block: hash -> (enum id, original name, trailing comment)."""
    begin, end = ksy_text.index(BEGIN_MARKER), ksy_text.index(END_MARKER)
    entries = {}
    for line in ksy_text[begin:end].splitlines():
        m = ENTRY.match(line)
        if m:
            name = m.group(3).replace('\\"', '"').replace("\\\\", "\\")
            entries[int(m.group(1), 16)] = (m.group(2), name, m.group(4).strip())
    return entries


def write_enum(ksy_text: str, entries: dict[int, tuple[str, str, str]]) -> str:
    lines = [BEGIN_MARKER + ": generated by build_field_names.py from the game's WHGame.dll, do not edit by hand",
             "  field_name:" if entries else "  field_name: {}"]
    for h, (ident, name, comment) in sorted(entries.items(), key=lambda e: (e[1][0], e[0])):
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'    0x{h:08x}: {{id: {ident}, doc: "{escaped}"}}' + (f"  {comment}" if comment else ""))
    begin = ksy_text.index(BEGIN_MARKER)
    end = ksy_text.index("\n", ksy_text.index(END_MARKER))
    return ksy_text[:begin] + "\n".join(lines) + "\n" + ksy_text[ksy_text.index(END_MARKER):end] + ksy_text[end:]


# ------------------------------------------------------------------ main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("saves", nargs="+", type=Path, help=".whs saves (or .payload.bin files)")
    parser.add_argument("--dll", type=Path, default=DEFAULT_DLL, help=f"the game's WHGame.dll (default: {DEFAULT_DLL})")
    parser.add_argument("--ksy", type=Path, default=DEFAULT_KSY, help=f"spec to update (default: {DEFAULT_KSY})")
    args = parser.parse_args()

    counts = collections.Counter()
    for save in args.saves:
        data = save.read_bytes()
        payload = decompress(data)[0] if save.suffix.lower() == ".whs" else data
        counts.update(used_hashes(payload))

    ksy_text = args.ksy.read_text(encoding="utf-8")
    entries = read_enum(ksy_text)
    targets = {h for h in counts if h not in entries}

    found = {}
    for candidate in dll_candidates(args.dll.read_bytes()):
        h = fnv1(candidate)
        if h in targets:
            found.setdefault(h, (candidate.decode("ascii"), ""))
    for candidate in short_names():
        h = fnv1(candidate)
        if h in targets and h not in found:
            found[h] = (candidate.decode("ascii"), "# short name found by brute force, not as a string in the DLL")

    taken = {ident for ident, _, _ in entries.values()}
    # names already in snake_case first, so that "pos" keeps the plain id and "Pos" gets a suffix
    for h, (name, comment) in sorted(found.items(), key=lambda e: (enum_id(e[1][0]) != e[1][0], e[1][0])):
        ident = enum_id(name)
        if ident in taken:
            ident = f"{ident}_{h:08x}"
        taken.add(ident)
        entries[h] = (ident, name, comment)

    args.ksy.write_text(write_enum(ksy_text, entries), encoding="utf-8")
    unknown = sorted((h for h in counts if h not in entries), key=lambda h: -counts[h])
    print(f"{len(counts)} field names used by the saves: {len(found)} newly named, "
          f"{len(entries)} in the enum, {len(unknown)} still unknown")
    for h in unknown:
        print(f"  unknown 0x{h:08x} ({counts[h]:,} uses)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
