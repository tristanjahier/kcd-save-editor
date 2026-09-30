"""Display everything that is known about one KCD save.

Default output: container, header, mods,
engine data (metadata and sections), modules, all statistics, souls, dynamic
events, script tables and small known structures. Big lists are on request:
  --section NAME   dump a typed section (Timer, TerrainState, GameState...) as a tree
  --layers         list all layer states
  --souls          list all soul names
  --tree DEPTH     print the chunk tree down to DEPTH levels
  --lang LANGUAGE  translate quest/objective/location keys (e.g. French, English)

Usage: python inspect_save.py SAVE.whs [options]
"""
import argparse
import collections
import datetime
import re
import struct
import sys
import zipfile
import zlib
from pathlib import Path

from build_field_names import DEFAULT_DLL, DEFAULT_KSY, chunks, read_enum
from whs_decompress import decompress

GAME_DIR = DEFAULT_DLL.parents[2]
SAVE_TYPES = {0: "permanent", 1: "autosave", 2: "manual", 5: "exit", 6: "switch"}
KNOWN_LEAVES = {1101}  # 12-byte struct that can look like two empty chunks
# Bodies made of a small prefix followed by chunks: chunk id -> prefix size
PREFIXED_LISTS = {3002: 4, 13609: 4, 29452: 4, 5498: 4, 4446: 16, 778: 16}
# English labels from the game (Libs/Tables/rpg/statistic.xml + text_ui_soul.xml); hidden ones keep their internal name
KNOWN_STATS = {7: "Food eaten", 37: "World time passed (h), not the clock", 50: "Time slept (h)",
               55: "Intimidation successes", 61: "CurrentStarvingTime (h, hidden)",
               62: "CurrentOvereatTime (h, hidden)", 81: "Time played in playline (h)",
               89: "CurrentProperDietTime (h, hidden)",
               96: "CurrentMainQuest (hidden)", 97: "LastStatLevelUp (hidden)", 98: "LastSkillLevelUp (hidden)"}
TYPED_NAMES = {0x02: "str", 0x03: "bool", 0x04: "f32", 0x05: "Vec2", 0x06: "Vec3", 0x07: "Quat", 0x08: "Ang3",
               0x09: "s8", 0x0A: "s16", 0x0B: "s32", 0x0C: "s64", 0x0D: "u8", 0x0E: "u16", 0x0F: "u32",
               0x10: "u64", 0x11: "script", 0x12: "time"}
TYPED_FORMATS = {0x03: "<B", 0x04: "<f", 0x05: "<2f", 0x06: "<3f", 0x07: "<4f", 0x08: "<3f", 0x09: "<b",
                 0x0A: "<h", 0x0B: "<i", 0x0C: "<q", 0x0D: "<B", 0x0E: "<H", 0x0F: "<I", 0x10: "<Q", 0x12: "<q"}


# ------------------------------------------------------------------ chunk helpers

def children(buf: bytes, start: int, end: int) -> dict[int, list[tuple[int, int]]]:
    """Chunk id -> list of (body_start, body_end) for the chunks of buf[start:end]."""
    out = collections.defaultdict(list)
    for chunk_id, s, e in chunks(buf, start, end):
        out[chunk_id].append((s, e))
    return out


def child(buf: bytes, start: int, end: int, *path: int) -> tuple[int, int]:
    for chunk_id in path:
        start, end = children(buf, start, end)[chunk_id][0]
    return start, end


def game_clock(buf: bytes, start: int, end: int) -> str:
    """In-game clock of module [29463] buf[start:end]: chunk [13617] starts with u64 ms since midnight of day 0."""
    ms = struct.unpack_from("<Q", buf, child(buf, start, end, 13617)[0])[0]
    return f"day {ms // 86_400_000}, {ms // 3_600_000 % 24:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d}"


def cstrings(buf: bytes, pos: int, count: int) -> tuple[list[str], int]:
    out = []
    for _ in range(count):
        nul = buf.index(b"\0", pos)
        out.append(buf[pos:nul].decode("utf-8", "replace"))
        pos = nul + 1
    return out, pos


def is_chunk_list(buf: bytes, start: int, end: int) -> bool:
    pos = start
    while pos < end:
        if pos + 6 > end:
            return False
        pos += 6 + struct.unpack_from("<I", buf, pos + 2)[0]
    return pos == end and end > start


# ------------------------------------------------------------------ names from the spec and the game

def chunk_names(ksy_text: str) -> dict[int, str]:
    """The chunk_id and header_chunk_id enums of the ksy: id -> name (the two sets of ids don't overlap)."""
    names = {}
    for enum, next_enum in (("chunk_id", "header_chunk_id"), ("header_chunk_id", "save_type")):
        block = ksy_text[ksy_text.index(f"\n  {enum}:"):ksy_text.index(f"\n  {next_enum}:")]
        prefix = "header_" if enum == "header_chunk_id" else ""
        names.update({int(m.group(1)): prefix + m.group(2) for m in re.finditer(r"^\s+(\d+): (\w+)$", block, re.M)})
    return names


def read_pak_entries(pak: Path, wanted: set[str]) -> dict[str, bytes]:
    """Read entries from a CryEngine .pak (zip whose local headers may use '\\', which zipfile rejects)."""
    raw = pak.read_bytes()
    out = {}
    with zipfile.ZipFile(pak) as z:
        for info in z.infolist():
            if info.filename.lower() in wanted:
                name_len, extra_len = struct.unpack_from("<HH", raw, info.header_offset + 26)
                start = info.header_offset + 30 + name_len + extra_len
                data = raw[start:start + info.compress_size]
                out[info.filename.lower()] = zlib.decompress(data, -15) if info.compress_type == zipfile.ZIP_DEFLATED else data
    return out


def localization(game_dir: Path, language: str) -> dict[str, str]:
    """Localization key -> text, from <game>/Localization/<language>_xml.pak (empty if not found)."""
    pak = game_dir / "Localization" / f"{language}_xml.pak"
    if not pak.exists():
        return {}
    texts = {}
    for data in read_pak_entries(pak, {"text_ui_quest.xml", "text_ui_menus.xml"}).values():
        for key, english, translated in re.findall(
                r"<Row>\s*<Cell>([^<]*)</Cell>\s*<Cell>([^<]*)</Cell>\s*<Cell>([^<]*)</Cell>", data.decode("utf-8", "replace")):
            texts[key] = translated or english
    return texts


# ------------------------------------------------------------------ value formatting

def fmt_float(x: float) -> str:
    return f"{x:.6g}"


def script_value(buf: bytes, pos: int, is_key: bool = False, depth: int = 0) -> tuple[str, int]:
    """Render a script value compactly; returns (text, next position)."""
    kind = buf[pos]
    if kind == 1:
        return "nil", pos + 1
    if kind == 2:
        return ("true" if buf[pos + 1] else "false"), pos + 2
    if kind == 3:
        return f"handle({struct.unpack_from('<Q', buf, pos + 1)[0]:#x})", pos + 9
    if kind == 4:
        return (str(struct.unpack_from("<i", buf, pos + 1)[0]) if is_key
                else fmt_float(struct.unpack_from("<f", buf, pos + 1)[0])), pos + 5
    if kind == 5:
        n = struct.unpack_from("<H", buf, pos + 1)[0]
        return repr(buf[pos + 3:pos + 3 + n].decode("utf-8", "replace")), pos + 3 + n
    if kind == 9:
        return "vec(" + ", ".join(map(fmt_float, struct.unpack_from("<3f", buf, pos + 1))) + ")", pos + 13
    if kind == 6:
        num_pairs = struct.unpack_from("<I", buf, pos + 2)[0]
        pos += 6
        items = []
        for _ in range(num_pairs):
            key, pos = script_value(buf, pos, True, depth + 1)
            value, pos = script_value(buf, pos, False, depth + 1)
            items.append(f"{key.strip(chr(39))}={value}")
        text = "{" + ", ".join(items) + "}"
        return (text if len(text) <= 300 or depth else text[:300] + "...}"), pos
    raise ValueError(f"unknown script value kind {kind} at {pos:#x}")


def dump_typed_values(buf: bytes, pos: int, end: int, names: dict[int, str], max_depth: int, limit: int) -> None:
    depth, printed = 0, 0
    while pos < end:
        kind = buf[pos]
        if kind == 0x01:
            depth -= 1
            pos += 1
            continue
        h = struct.unpack_from("<I", buf, pos + 1)[0]
        name = names.get(h, f"#{h:08x}")
        pos += 5
        if kind == 0x00:
            text = f"{name}:"
            depth += 1
        elif kind == 0x02:
            n = struct.unpack_from("<H", buf, pos)[0]
            text = f"{name} (str) = {buf[pos + 2:pos + 2 + n].decode('utf-8', 'replace')!r}"
            pos += 2 + n
        elif kind == 0x11:
            value, pos = script_value(buf, pos)
            text = f"{name} (script) = {value}"
        elif kind in TYPED_FORMATS:
            values = struct.unpack_from(TYPED_FORMATS[kind], buf, pos)
            pos += struct.calcsize(TYPED_FORMATS[kind])
            shown = ", ".join(fmt_float(v) if isinstance(v, float) else str(v) for v in values)
            text = f"{name} ({TYPED_NAMES[kind]}) = {shown if len(values) == 1 else '(' + shown + ')'}"
        else:
            raise ValueError(f"unknown typed value type {kind:#x} at {pos - 5:#x}")
        shown_depth = depth - 1 if kind == 0x00 else depth
        if shown_depth <= max_depth:
            if printed >= limit:
                print(f"    ... (stopped after {limit} lines, use --limit)")
                return
            print("    " + "  " * shown_depth + text)
            printed += 1


# ------------------------------------------------------------------ report

class Inspector:
    def __init__(self, path: Path, texts: dict[str, str]):
        self.path, self.texts = path, texts
        data = path.read_bytes()
        if path.suffix.lower() == ".whs":
            self.payload, self.md5_ok, self.blocks = decompress(data)
        else:
            self.payload, self.md5_ok, self.blocks = data, None, None
        self.file_size = len(data)
        ksy_text = DEFAULT_KSY.read_text(encoding="utf-8")
        self.chunk_names = chunk_names(ksy_text)
        self.field_names = {h: name for h, (_, name, _) in read_enum(ksy_text).items()}
        p = self.payload
        self.top = children(p, 4, len(p))
        self.body = children(p, *self.top[500][0])
        self.modules = children(p, *self.body[502][0])

    def label(self, key: str) -> str:
        text = self.texts.get(key.lstrip("@"))
        return f"{key} ({text})" if text else (key or "-")

    def container(self) -> None:
        print(f"== {self.path.name}")
        if self.blocks is not None:
            print(f"file {self.file_size:,} bytes, {self.blocks} zlib blocks, MD5 {'OK' if self.md5_ok else 'MISMATCH'}, "
                  f"payload {len(self.payload):,} bytes")
        p = self.payload
        print(f"unknown u32 {struct.unpack_from('<I', p, 0)[0]}, top-level chunks "
              f"{[self.chunk_names.get(c, c) for c, _, _ in chunks(p, 4, len(p))]}, trailing byte {p[-1]:#04x}")

    def header(self) -> None:
        p = self.payload
        header = children(p, *self.top[501][0])
        s, _ = header[13][0]
        save_type, number, unix_time = struct.unpack_from("<IIQ", p, s)
        (level, description, title), pos = cstrings(p, s + 16, 3)
        unknown_a, unknown_b, flag, num_dlcs = struct.unpack_from("<IIBH", p, pos)
        dlcs = []
        pos += 11
        for _ in range(num_dlcs):
            dlc_id = struct.unpack_from("<I", p, pos)[0]
            (name,), pos = cstrings(p, pos + 4, 1)
            dlcs.append(f"{dlc_id}: {name}")
        fields = description.split("|")
        when = datetime.datetime.fromtimestamp(unix_time)
        play = float(fields[7])
        print("\n== header")
        print(f"save type   {save_type} ({SAVE_TYPES.get(save_type, 'unknown')}), number {number}")
        print(f"saved       {when:%Y-%m-%d %H:%M:%S} local ({unix_time})")
        print(f"level       {level}")
        print(f"quest       {self.label(fields[2])}")
        print(f"objective   {self.label(fields[3])}")
        print(f"location    {self.label(fields[4])}")
        print(f"play time   {play} h (menu shows {int(play * 10) / 10}h)")
        print(f"clock       {game_clock(p, *self.modules[29463][0])} (in-game, chunk 13617)")
        print(f"title       {title or '-'}")
        print(f"unknown     {unknown_a}, {unknown_b}, unknown_flag {flag}")
        print(f"DLCs        {dlcs}")
        if 17 in header:
            switch_number = struct.unpack_from("<I", p, header[17][0][0])[0]
            print(f"switch save #{switch_number} (made inside a DLC level; the main world is restored from that save)")
        other = [self.chunk_names.get(c, c) for c in header if c not in (13, 14, 17)]
        print(f"other header chunks {other}")
        if 14 in header:
            s, _ = header[14][0]
            num_mods = struct.unpack_from("<I", p, s)[0]
            fields, _ = cstrings(p, s + 4, 6 * num_mods)
            print(f"\n== mods ({num_mods})")
            for i in range(num_mods):
                mod_id, name, _, author, version, _ = fields[6 * i:6 * i + 6]
                print(f"  {name or mod_id} {version} by {author or '?'}  [{mod_id}]")

    def engine(self) -> None:
        p = self.payload
        print("\n== engine data (chunk 503): metadata and sections")
        for chunk_id, s, e in chunks(p, *self.body[503][0]):
            nul = p.index(b"\0", s)
            name = p[s:nul].decode()
            if chunk_id == 8359:
                print(f"  {name} = {p[nul + 1:e - 1].decode()!r}")
            elif chunk_id == 8360:
                print(f"  {name} = {struct.unpack_from('<i', p, nul + 1)[0]}")
            elif chunk_id == 8361:
                print(f"  section {name}: {e - nul - 1:,} bytes")

    def module_table(self) -> None:
        print("\n== modules (chunk 502)")
        for chunk_id, s, e in chunks(self.payload, *self.body[502][0]):
            print(f"  {chunk_id:>6} {self.chunk_names.get(chunk_id, '?'):24s} {e - s:>12,} bytes")

    def statistics(self) -> None:
        p = self.payload
        print("\n== statistics (29463/13615)")
        for _, s, e in chunks(p, *child(p, *self.body[502][0], 29463, 13615)):
            key = struct.unpack_from("<I", p, s)[0]
            value = "(no value)"
            if s + 4 < e:
                value_id, size = struct.unpack_from("<HI", p, s + 4)
                v = s + 10
                if value_id == 14223:
                    value = struct.unpack_from("<i", p, v)[0]
                elif value_id == 14224:
                    value = fmt_float(struct.unpack_from("<d", p, v)[0])
                elif value_id == 14232:
                    value = f"{struct.unpack_from('<d', p, v + 1)[0]:.6f}"
                elif value_id == 14238:
                    value = repr(p[v:v + size].rstrip(b"\0").decode("utf-8", "replace"))
                elif value_id in (14230, 14234, 14235):
                    value = f"{struct.unpack_from('<Q', p, v + 7)[0] / 3_600_000:.3f}"
                elif value_id in (14229, 14236, 14237):
                    value = struct.unpack_from("<I", p, v)[0]
                elif value_id == 14225:
                    value = f"{struct.unpack_from('<I', p, v)[0]} GUIDs"
                elif value_id == 14226:
                    n = struct.unpack_from("<I", p, v)[0]
                    value = list(struct.unpack_from(f"<{n}I", p, v + 4))
                elif size == 0:
                    value = f"(empty, kind {value_id})"
                else:
                    value = f"kind {value_id}: {p[v:v + size].hex()}"
            known = KNOWN_STATS.get(key, "")
            print(f"  #{key:<4} {str(value):>22}  {known}")

    def game_data(self, list_souls: bool) -> None:
        p = self.payload
        modules = self.body[502][0]
        s, e = child(p, *modules, 29463, 13609)
        souls = []
        for _, soul_s, soul_e in chunks(p, s + 4, e):
            for chunk_id, cs, _ in chunks(p, soul_s + 16, soul_e):
                if chunk_id == 4866:
                    souls.append(cstrings(p, cs + 16, 1)[0][0])
        print(f"\n== souls: {len(souls)} (NPCs and animals)")
        if list_souls:
            for name in sorted(souls):
                print(f"  {name}")
        records = struct.unpack_from("<I", p, child(p, *modules, 29443, 3002)[0])[0]
        print(f"records 29443/3002: {records}")

        print("\n== dynamic events (29462)")
        slots = events = 0
        for chunk_id, s, e in chunks(p, *child(p, *modules, 29462)):
            if chunk_id == 5498:
                slots += 1
            elif chunk_id == 5499:
                events += 1
                values = {c: p[cs:ce] for c, cs, ce in chunks(p, s, e)}
                print(f"  active: {values.get(4981, b'').rstrip(bytes(1)).decode()} "
                      f"(4979={struct.unpack_from('<I', values[4979])[0]}, 4980={struct.unpack_from('<I', values[4980])[0]}, "
                      f"4983={fmt_float(struct.unpack_from('<f', values[4983])[0])}, 4984={values[4984].hex()})")
        print(f"  {slots} event slots, {events} active")

        print("\n== module 29451")
        s, e = child(p, *modules, 29451, 1000)
        for _, rs, _ in chunks(p, s, e):
            x, y, z, f = struct.unpack_from("<4f", p, rs)
            unknown = struct.unpack_from("<4I", p, rs + 16)
            print(f"  record at ({x:.1f}, {y:.1f}, {z:.1f}) f={fmt_float(f)} unknown={unknown}")
        s, _ = child(p, *modules, 29451, 1001, 1101)
        a, f, c = struct.unpack_from("<Iff", p, s)  # the last 4 bytes read as a plausible f32
        s, _ = child(p, *modules, 29451, 1001, 1102)
        print(f"  1101 = ({a}, {fmt_float(f)}, {fmt_float(c)}), 1102 = {fmt_float(struct.unpack_from('<f', p, s)[0])}")

        print("\n== script state (29452)")
        s, e = child(p, *modules, 29452)
        sub = children(p, s + 4, e)
        print(f"  sub-chunks {list(sub)}")
        for table_id, label in ((2100, "script identifiers"), (2101, "script type names")):
            ts, te = child(p, *sub[3214][0], table_id)
            print(f"  {label}: {struct.unpack_from('<H', p, te - 2)[0]}")

    def layers(self, list_all: bool) -> None:
        p = self.payload
        states = {}
        for _, s, e in chunks(p, *child(p, *self.body[507][0], 29443, 3010)):
            nul = p.index(b"\0", s)
            states[p[s:nul].decode()] = p[nul + 1]
        print(f"\n== layers: {len(states)}, {sum(states.values())} enabled")
        if list_all:
            for name, on in sorted(states.items()):
                print(f"  {'ON ' if on else 'off'} {name}")

    def section(self, name: str, max_depth: int, limit: int) -> None:
        p = self.payload
        for chunk_id, s, e in chunks(p, *self.body[503][0]):
            nul = p.index(b"\0", s)
            if chunk_id == 8361 and p[s:nul].decode() == name:
                print(f"\n== section {name}")
                dump_typed_values(p, nul + 1, e, self.field_names, max_depth, limit)
                return
        print(f"\nno section named {name!r}")

    def tree(self, max_depth: int) -> None:
        print(f"\n== chunk tree (depth {max_depth})")
        self._tree(4, len(self.payload), 0, max_depth)

    def _tree(self, start: int, end: int, depth: int, max_depth: int) -> None:
        p = self.payload
        groups = []  # consecutive chunks with the same id are grouped
        for chunk_id, s, e in chunks(p, start, end):
            if groups and groups[-1][0] == chunk_id:
                groups[-1][1].append((s, e))
            else:
                groups.append((chunk_id, [(s, e)]))
        for chunk_id, items in groups:
            s, e = items[0]
            count = f" x{len(items)}" if len(items) > 1 else ""
            print(f"  {'  ' * depth}[{chunk_id}] {self.chunk_names.get(chunk_id, '')}{count}  {e - s:,} bytes")
            if depth + 1 >= max_depth or chunk_id in KNOWN_LEAVES:
                continue
            prefix = PREFIXED_LISTS.get(chunk_id, 0)
            if e - s - prefix >= 6 and is_chunk_list(p, s + prefix, e):
                self._tree(s + prefix, e, depth + 1, max_depth)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("save", type=Path, help=".whs save (or .payload.bin file)")
    parser.add_argument("--section", help="dump a typed section: Timer, TerrainState, GameTokens, ViewSystem, "
                                          "FlowSystem, MatFX or GameState")
    parser.add_argument("--max-depth", type=int, default=99, help="group depth shown with --section")
    parser.add_argument("--limit", type=int, default=500, help="maximum lines printed by --section (default 500)")
    parser.add_argument("--layers", action="store_true", help="list all layer states")
    parser.add_argument("--souls", action="store_true", help="list all soul names")
    parser.add_argument("--tree", type=int, metavar="DEPTH", help="print the chunk tree down to DEPTH levels")
    parser.add_argument("--lang", help="translate quest/objective/location keys with the game's text tables "
                                          "in this language (e.g. French, English); off by default")
    parser.add_argument("--game-dir", type=Path, default=GAME_DIR, help=f"game install (default {GAME_DIR})")
    args = parser.parse_args()

    inspector = Inspector(args.save, localization(args.game_dir, args.lang) if args.lang else {})
    inspector.container()
    inspector.header()
    inspector.engine()
    inspector.module_table()
    inspector.layers(args.layers)
    inspector.statistics()
    inspector.game_data(args.souls)
    if args.tree:
        inspector.tree(args.tree)
    if args.section:
        inspector.section(args.section, args.max_depth, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
