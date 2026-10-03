"""Summarise KCD saves and show what changed between them.

For each save: header (type, number, date, quest, location, play time), in-game clock, game
build, mods, and whether every engine section parses. Then, across saves:
module layout, chunk paths that appear only in some saves, and between
consecutive saves: layers switched on/off, statistics that changed, active
dynamic events. Saves are ordered by date ("switch" saves have a number outside
the global counter).

Usage: python compare_saves.py SAVE.whs [SAVE.whs ...]
"""
import argparse
import collections
import struct
import sys
from pathlib import Path

from build_field_names import chunks, count_typed_value_hashes
from inspect_save import KNOWN_LEAVES, PREFIXED_LISTS, SAVE_TYPES, child, children, cstrings, game_clock, is_chunk_list
from whs_decompress import decompress

STAT_INT32, STAT_FLOAT64, STAT_FLAGGED_FLOAT64, STAT_STRING = 14223, 14224, 14232, 14238
STAT_WORLD_TIMES = {14230, 14234, 14235}  # WorldTime types: chunk [26852] holding u8 flag + u64 in-game milliseconds


def chunk_paths(buf: bytes, start: int, end: int, prefix: str = "") -> set[str]:
    """Paths of nested chunk ids ("500/502/29462/5499"), descending into bodies that parse as chunk lists."""
    paths = set()
    for chunk_id, s, e in chunks(buf, start, end):
        path = f"{prefix}/{chunk_id}" if prefix else str(chunk_id)
        paths.add(path)
        list_start = s + PREFIXED_LISTS.get(chunk_id, 0)
        if chunk_id not in KNOWN_LEAVES and e - list_start >= 6 and is_chunk_list(buf, list_start, e):
            paths |= chunk_paths(buf, list_start, e, path)
    return paths


class Save:
    def __init__(self, path: Path):
        self.path = path
        data = path.read_bytes()
        self.payload, self.md5_ok, _ = decompress(data) if path.suffix.lower() == ".whs" else (data, None, 0)
        p = self.payload
        top = children(p, 4, len(p))
        header = children(p, *top[501][0])
        s, _ = header[13][0]
        self.save_type, self.number, self.unix_time = struct.unpack_from("<IIQ", p, s)
        (self.level, description, self.title), _ = cstrings(p, s + 16, 3)
        fields = description.split("|")
        self.quest, self.objective, self.location, self.date, self.play_hours = fields[2], fields[3], fields[4], fields[6], fields[7]
        self.num_mods = struct.unpack_from("<I", p, header[14][0][0])[0] if 14 in header else 0
        # saves made inside a DLC level hold the number of the "switch" save that has the main world
        self.switch_save = struct.unpack_from("<I", p, header[17][0][0])[0] if 17 in header else None

        body_start, body_end = top[500][0]
        body = children(p, body_start, body_end)
        self.metadata, self.sections = {}, {}
        for chunk_id, s, e in chunks(p, *body[503][0]):
            nul = p.index(b"\0", s)
            name = p[s:nul].decode()
            if chunk_id == 8359:
                self.metadata[name] = p[nul + 1:e - 1].decode()
            elif chunk_id == 8360:
                self.metadata[name] = struct.unpack_from("<i", p, nul + 1)[0]
            elif chunk_id == 8361:
                try:
                    count_typed_value_hashes(p, nul + 1, e, collections.Counter())
                    self.sections[name] = "ok"
                except (ValueError, IndexError, struct.error) as err:
                    self.sections[name] = f"PARSE ERROR: {err}"

        self.layers = {}
        for _, s, e in chunks(p, *child(p, *body[507][0], 29443, 3010)):
            nul = p.index(b"\0", s)
            self.layers[p[s:nul].decode()] = p[nul + 1]

        modules_start, modules_end = body[502][0]
        self.modules = [(chunk_id, e - s) for chunk_id, s, e in chunks(p, modules_start, modules_end)]
        self.clock = game_clock(p, *child(p, modules_start, modules_end, 29463))
        self.stats = {}
        for _, s, e in chunks(p, *child(p, modules_start, modules_end, 29463, 13615)):
            key = struct.unpack_from("<I", p, s)[0]
            self.stats[key] = self.stat_value(s + 4, e)
        self.events = []
        for chunk_id, s, e in chunks(p, *child(p, modules_start, modules_end, 29462)):
            if chunk_id == 5499:
                name_s, name_e = children(p, s, e)[4981][0]
                self.events.append(p[name_s:name_e].rstrip(b"\0").decode())
        self.paths = chunk_paths(p, 4, len(p))

    def stat_value(self, start: int, end: int):
        if start >= end:
            return None
        value_id, size = struct.unpack_from("<HI", self.payload, start)
        s = start + 6
        if value_id == STAT_INT32:
            return struct.unpack_from("<i", self.payload, s)[0]
        if value_id == STAT_FLOAT64:
            return round(struct.unpack_from("<d", self.payload, s)[0], 3)
        if value_id == STAT_FLAGGED_FLOAT64:
            return round(struct.unpack_from("<d", self.payload, s + 1)[0], 3)
        if value_id in STAT_WORLD_TIMES:
            return round(struct.unpack_from("<Q", self.payload, s + 7)[0] / 3_600_000, 3)  # in-game hours
        if value_id == STAT_STRING:
            return self.payload[s:s + size].rstrip(b"\0").decode("utf-8", "replace")
        return self.payload[s:s + size].hex()  # other kinds: compared as raw bytes

    def summary(self) -> str:
        bad = {name: status for name, status in self.sections.items() if status != "ok"}
        dlc = f" (DLC level, main world in switch save #{self.switch_save})" if self.switch_save is not None else ""
        return (f"{self.path.name}: {SAVE_TYPES.get(self.save_type, self.save_type)} #{self.number}, {self.date}, "
                f"{self.quest} / {self.objective or '-'} @ {self.location}, play {self.play_hours} h, clock {self.clock}\n"
                f"    level {self.level}{dlc}, build {self.metadata.get('build')}, version {self.metadata.get('version')}, mods {self.num_mods}, "
                f"MD5 {'-' if self.md5_ok is None else 'OK' if self.md5_ok else 'MISMATCH'}, "
                f"engine sections {'all parse' if not bad else bad}, {len(self.layers)} layers "
                f"({sum(self.layers.values())} on), events {self.events or '-'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("saves", nargs="+", type=Path, help=".whs saves (or .payload.bin files)")
    args = parser.parse_args()

    saves = sorted((Save(path) for path in args.saves), key=lambda save: (save.unix_time, save.number))
    print("==== saves (by date)")
    for save in saves:
        print(save.summary())

    print("\n==== [502] modules (size in bytes, '-' = absent)")
    module_ids = list(dict.fromkeys(m for save in saves for m, _ in save.modules))
    print(f"{'module':>7} " + " ".join(f"{s.number:>9}" for s in saves))
    for module_id in module_ids:
        print(f"{module_id:>7} " + " ".join(f"{dict(s.modules).get(module_id, '-'):>9}" for s in saves))
    shared = set.intersection(*(set(m for m, _ in s.modules) for s in saves))
    print("modules not in every save:", [m for m in module_ids if m not in shared] or "none")
    orders = {tuple(m for m, _ in s.modules if m in shared) for s in saves}
    print("order of the other modules:", "same in all saves" if len(orders) == 1 else "DIFFERS")

    print("\n==== chunk paths not present in every save")
    all_paths = set().union(*(s.paths for s in saves))
    partial = sorted(p for p in all_paths if not all(p in s.paths for s in saves))
    for path in partial:
        print(f"  {path}: in {[s.number for s in saves if path in s.paths]}")
    if not partial:
        print("  none")

    for old, new in zip(saves, saves[1:]):
        print(f"\n==== #{old.number} -> #{new.number}")
        if old.level != new.level:  # a DLC level has its own, much smaller set of layers
            print(f"layers: not comparable (level {old.level} -> {new.level})")
        else:
            on = [n for n in new.layers if new.layers[n] and not old.layers.get(n)]
            off = [n for n in new.layers if old.layers.get(n) and not new.layers[n]]
            print(f"layers: +{len(on)} on {on}\n        -{len(off)} off {off}")
        print("stats changed:")
        for key in sorted(set(old.stats) | set(new.stats)):
            a, b = old.stats.get(key), new.stats.get(key)
            if a != b:
                delta = f" ({b - a:+,})" if isinstance(a, int) and isinstance(b, int) else f" ({b - a:+,.3f})" if isinstance(a, (int, float)) and isinstance(b, (int, float)) else ""
                print(f"  #{key}: {a} -> {b}{delta}" if max(len(str(a)), len(str(b))) < 60 else f"  #{key}: <raw value changed>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
