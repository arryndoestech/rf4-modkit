r"""
gen.py -- RF4S `Gen*.bin` monster-encounter tables (the dungeon/field spawn lists).

The `Gen*.bin` files (690 of them in bundleMain) are the per-area monster-generator
tables: `GenField##` for the overworld and `GenA##`..`GenQ##` for dungeon areas.
They are selected at runtime by `g_encounterArchiveTable` (RF4S.exe+0x4DB1E0, keyed
by zone) and loaded whole by `nsFileArchive_Load`; the consumers are
`Encounter_TickMonsterSpawnSlots` (+0x1E6240: weighted gate pick + gate position
pick), `Encounter_SpawnMonsterFromTemplate` (+0x1E5990) and
`Map_LoadAndUnpackMonsterSpawnTables` (+0x1E7F20: copies the gate's five sub-blocks
into the behaviour task). Re-verified 2026-09-19 against those three functions plus
`MonsterBehavior_BindFallback` (+0x1E8140), which BUILDS the same structures for a gate
without a table and so pins the roster record layout exactly.

Container = an `NLCL` archive (version 6..8, non-flat). Every shipped file holds at
most ONE pattern (268 of the 690 are empty). Layout, offsets absolute from file start:

    +0x00 "NLCL"  +0x04 u32 BCD build date  +0x08/+0x0C reserved (0)  +0x10 u32 version
    +0x14 u32 byte_size (end of the NLCL chunk; the build-tool footer follows)
    +0x18 u32 pattern_count      +0x1C u32[pattern_count] pattern offsets

  pattern @P:  u32 entry_count, then entry_count x 24-byte ENTRIES:
    +0  u16 gate_kind   actor placed by the encounter (359 "Gate" .. 390 elemental gates).
                        Encounter_SpawnMonsterFromTemplate sends kinds 48..277 down a
                        path that stores through a NULL pointer (instant crash); every
                        other kind goes through Actor_SpawnAtPos.
    +2  u16 weight      relative pick weight among the pattern's entries (summed in a u16)
    +4  u32 -> hdr      16 B: {u32 1; u16 param_a; u8 count_min; u8 count_max;
                        u16 spawn_delay; u16 flag; u32 0}  (hdr+4..+15 copied into the
                        behaviour task by the unpacker; Companion_TickAI +0x1E7870 reads
                        the copy).
                        param_a = the GATE'S LEVEL: Encounter_TickMonsterSpawnSlots
                        levels the gate to param_a * (prince rank + 1) + 100 * rank - 1
                        (0 = leave the actor's own level), and Companion_AcquireTarget
                        levels each monster up to the gate when it is 16+ below. The
                        fallback builder stores the same formula's result here.
                        count_min/count_max = monsters kept alive per gate (the tick
                        spawns while fewer than count_max are engaged, at least
                        count_min at once; the engaged array holds 10; hard mode caps
                        max at 4). spawn_delay = the respawn timer base in frames: first
                        wave delay = spawn_delay + rand(0..127) (-32 above 32), between
                        waves (spawn_delay + rand(0..63)) / 2 with a floor of 48.
                        flag low byte != 0: the spawned gate gets actor state bits 0x24
                        (as when the player has status 0x40000); flag high byte != 0
                        (value 256 in 16 shipped entries) enables the leader-report path.
    +8  u32 -> gate positions  {u32 n; n x (u16 x, u16 y)}   sub-units, tile = >>3;
                        Encounter_TickMonsterSpawnSlots picks one at random for the gate
                        (n = 0 reads the dword after the count as a position)
    +12 u32 -> monster positions {u32 m; m x (u16 x, u16 y, u32 radius)}  the monster
                        appears at (x, y) + a random offset up to `radius` sub-units
                        (only the low u16 is read), retried up to 64 times until the
                        ATTR cell has bit 0x01 or 0x20 (Companion_TickAnimation)
    +16 u32 -> roster   {u32 N; N x RECORD}   RECORD = {u16 monster_id; u16 pick_weight;
                        u32 K; u32 pos_weight[K]}
                        pick_weight = the monster's relative chance within the roster
                        (Companion_TickMovement +0x1E8650 sums the u16 at record+2 and
                        picks by it -- this is NOT a level). pos_weight[k] = chance of
                        spawning at monster
                        position k; only the LOW BYTE is read and the bytes are summed
                        in a u8 (Companion_TickAnimation).
                        STRIDE: every consumer steps through the roster with the FIXED
                        stride 8 + 4*K0, K0 = the FIRST record's K (Companion_AcquireTarget,
                        _TickMovement, _TickAnimation); only the unpacker's copy size is
                        also N * (12 + 4*K0). So every record except the last must have
                        K == K0, or the later records are read at the wrong offsets.
                        K should equal m: the unpacker "clamps" by rewriting the cached
                        archive after its copy (record 0's K, or m), so a mismatch reads
                        positions past the table on this load and shifts the stride on
                        the next one. The fallback writes K = 1, pos_weight = 1.
    +20 u32 -> roster (alternate)   picked instead of +16 for (100 - p)% of the monsters,
                        p = 70 (05-10h) / 55 (11-16h) / 45 (17-22h) / 30 (night); always
                        the same block as +16 in shipped data

Sub-blocks are SHARED freely between entries (a pattern's gates usually share the
position tables and often the roster). After byte_size comes the generic NLCL footer:
16-byte descriptors {0, object_offset, ref_count, ref_list_offset} for the root (24)
and every referenced block in ascending offset order, then the reference lists (the
absolute positions of every field that stores that offset). The engine never reads
the footer, but this module regenerates it so the files stay canonical.

This module parses the whole file into objects, lets you retune AND restructure it
(add/remove gates, monsters, positions; share or copy blocks) and rebuilds the file
with recomputed offsets and footer. Unmodified files rebuild byte-for-byte (all 690).

CORRECTION 2026-09-19: an earlier version assumed a fixed 24-byte roster record and
misread every roster whose K is not 4 (e.g. GenA01 gate 1: Orc Archer pick weight 0
instead of 20). Record size on disk is 8 + 4*K; the game reads with K0's stride.
CORRECTION 2026-09-24: the record's high u16 is the monster's PICK WEIGHT, not a level
(shipped values are 5 or 10 in ~70% of records); the gate level is hdr.param_a.
Encounter_TickMonsterSpawnSlots spawns one gate PER PATTERN into the spawn task's
2-slot gate array (the counter is not bounds-checked), so keep <= 2 patterns (every
shipped file has 0 or 1).
"""
from __future__ import annotations

import pathlib
import struct

MAGIC = b"NLCL"
HEADER_SIZE = 28
MONSTER_LO, MONSTER_HI = 48, 254   # living-monster id range (bestiary)
ENTRY_SIZE = 24
HDR_SIZE = 16
GATE_KIND_LO, GATE_KIND_HI = 359, 390   # the Gate actor family
# Encounter_SpawnMonsterFromTemplate (RF4S.exe+0x1E5990): kinds 48..277 take a branch
# that writes the spawned actor through a NULL pointer -> crash on the first spawn.
CRASH_KIND_LO, CRASH_KIND_HI = 48, 0x115
MAX_PATTERNS = 2            # gate slots in the encounter spawn task
MAX_ENGAGED = 10            # engaged-monster slots per gate (Companion_TickAI)
MAX_INDEX7 = 128            # roster / monster-position indices are kept in 7 bits


class GenError(Exception):
    pass


# --------------------------------------------------------------------------- #
# block objects (shared by identity between entries)
# --------------------------------------------------------------------------- #
class Hdr:
    """The 16-byte per-gate header block."""
    __slots__ = ("count", "param_a", "count_min", "count_max", "spawn_delay", "flag", "reserved",
                 "orig_off")

    def __init__(self, count=1, param_a=0, count_min=1, count_max=1, spawn_delay=250, flag=1,
                 reserved=0, orig_off=None):
        self.count, self.param_a = count, param_a
        self.count_min, self.count_max = count_min, count_max
        self.spawn_delay, self.flag, self.reserved = spawn_delay, flag, reserved
        self.orig_off = orig_off

    @classmethod
    def parse(cls, d: bytes, off: int) -> "Hdr":
        count, pa, cmin, cmax, pb, flag, reserved = struct.unpack_from("<IHBBHHI", d, off)
        return cls(count, pa, cmin, cmax, pb, flag, reserved, off)

    def pack(self) -> bytes:
        return struct.pack("<IHBBHHI", self.count & 0xFFFFFFFF, self.param_a & 0xFFFF,
                           self.count_min & 0xFF, self.count_max & 0xFF, self.spawn_delay & 0xFFFF,
                           self.flag & 0xFFFF, self.reserved & 0xFFFFFFFF)

    def size(self) -> int:
        return HDR_SIZE

    def copy(self) -> "Hdr":
        return Hdr(self.count, self.param_a, self.count_min, self.count_max, self.spawn_delay,
                   self.flag, self.reserved)


class PosTable:
    """Gate positions: {u32 n; n x (u16 x, u16 y)}, sub-units (tile = value >> 3)."""
    __slots__ = ("points", "orig_off")
    RECORD = 4

    def __init__(self, points=None, orig_off=None):
        self.points = list(points or [])       # [(x, y), ...]
        self.orig_off = orig_off

    @classmethod
    def parse(cls, d: bytes, off: int) -> "PosTable":
        n = struct.unpack_from("<I", d, off)[0]
        if n > 4096 or off + 4 + 4 * n > len(d):
            raise GenError(f"gate position table at {off} claims {n} points")
        pts = [struct.unpack_from("<HH", d, off + 4 + 4 * i) for i in range(n)]
        return cls(pts, off)

    def pack(self) -> bytes:
        out = struct.pack("<I", len(self.points))
        for x, y in self.points:
            out += struct.pack("<HH", int(x) & 0xFFFF, int(y) & 0xFFFF)
        return out

    def size(self) -> int:
        return 4 + 4 * len(self.points)

    def copy(self) -> "PosTable":
        return PosTable(list(self.points))


class MonPosTable:
    """Monster spawn points: {u32 m; m x (u16 x, u16 y, u32 extra)}. `extra` is the
    scatter radius in sub-units (low u16 read by Companion_TickAnimation)."""
    __slots__ = ("points", "orig_off")
    RECORD = 8

    def __init__(self, points=None, orig_off=None):
        self.points = list(points or [])       # [(x, y, extra), ...]
        self.orig_off = orig_off

    @classmethod
    def parse(cls, d: bytes, off: int) -> "MonPosTable":
        n = struct.unpack_from("<I", d, off)[0]
        if n > 4096 or off + 4 + 8 * n > len(d):
            raise GenError(f"monster position table at {off} claims {n} points")
        pts = [struct.unpack_from("<HHI", d, off + 4 + 8 * i) for i in range(n)]
        return cls(pts, off)

    def pack(self) -> bytes:
        out = struct.pack("<I", len(self.points))
        for x, y, extra in self.points:
            out += struct.pack("<HHI", int(x) & 0xFFFF, int(y) & 0xFFFF, int(extra) & 0xFFFFFFFF)
        return out

    def size(self) -> int:
        return 4 + 8 * len(self.points)

    def copy(self) -> "MonPosTable":
        return MonPosTable(list(self.points))


class Spawn:
    """One roster record -> a monster the gate can generate.

    `monster_id` low 16 bits of the packed dword; `pick_weight` the high 16 = the
    monster's PICK WEIGHT within the roster (the game never reads it as a level, see the
    module docstring); `weights` = the K per-monster-position weights (low byte read)."""
    __slots__ = ("monster_id", "pick_weight", "weights", "rec_off")

    def __init__(self, monster_id, pick_weight, weights=None, rec_off=None):
        self.monster_id = monster_id & 0xFFFF
        self.pick_weight = pick_weight & 0xFFFF
        self.weights = list(weights or [])
        self.rec_off = rec_off        # absolute offset of the record (after parse/build)

    @property
    def packed(self) -> int:
        return (self.pick_weight << 16) | self.monster_id

    def size(self) -> int:
        return 8 + 4 * len(self.weights)


class Roster:
    """{u32 N; N x Spawn}"""
    __slots__ = ("spawns", "orig_off")

    def __init__(self, spawns=None, orig_off=None):
        self.spawns = list(spawns or [])
        self.orig_off = orig_off

    @classmethod
    def parse(cls, d: bytes, off: int) -> "Roster":
        n = struct.unpack_from("<I", d, off)[0]
        if n > 4096:
            raise GenError(f"roster at {off} claims {n} records")
        pos = off + 4
        spawns = []
        for _ in range(n):
            if pos + 8 > len(d):
                raise GenError(f"roster at {off} runs past the end of the file")
            packed, k = struct.unpack_from("<II", d, pos)
            if k > 1024 or pos + 8 + 4 * k > len(d):
                raise GenError(f"roster record at {pos} claims {k} weights")
            weights = list(struct.unpack_from(f"<{k}I", d, pos + 8))
            spawns.append(Spawn(packed & 0xFFFF, packed >> 16, weights, pos))
            pos += 8 + 4 * k
        return cls(spawns, off)

    def pack(self) -> bytes:
        out = struct.pack("<I", len(self.spawns))
        for s in self.spawns:
            out += struct.pack("<II", s.packed, len(s.weights))
            out += struct.pack(f"<{len(s.weights)}I", *[int(w) & 0xFFFFFFFF for w in s.weights])
        return out

    def size(self) -> int:
        return 4 + sum(s.size() for s in self.spawns)

    def copy(self) -> "Roster":
        return Roster([Spawn(s.monster_id, s.pick_weight, list(s.weights)) for s in self.spawns])


class Entry:
    """One pattern entry = a gate placement (kind + weight) + its five sub-blocks."""
    __slots__ = ("gate_kind", "weight", "hdr", "gate_pos", "mon_pos", "roster", "roster_alt",
                 "off", "subtable_offsets")

    def __init__(self, gate_kind, weight, hdr, gate_pos, mon_pos, roster, roster_alt=None):
        self.gate_kind = gate_kind & 0xFFFF
        self.weight = weight & 0xFFFF
        self.hdr, self.gate_pos, self.mon_pos = hdr, gate_pos, mon_pos
        self.roster = roster
        self.roster_alt = roster if roster_alt is None else roster_alt
        self.off = None                  # absolute offset of the entry (after parse/build)
        self.subtable_offsets = ()       # (hdr, gate_pos, mon_pos, roster, roster_alt)

    @property
    def spawns(self):
        return self.roster.spawns

    def blocks(self):
        return (self.hdr, self.gate_pos, self.mon_pos, self.roster, self.roster_alt)


# --------------------------------------------------------------------------- #
# the table
# --------------------------------------------------------------------------- #
class GenTable:
    def __init__(self, data: bytes):
        if data[:4] != MAGIC:
            raise GenError(f"not an NLCL table (magic={data[:4]!r})")
        self.build_date = struct.unpack_from("<I", data, 4)[0]
        self.reserved = struct.unpack_from("<II", data, 8)
        self.version = struct.unpack_from("<I", data, 16)[0]
        self.patterns: list[list[Entry]] = []
        self._blocks = []            # every distinct block object, in original file order
        self._parse(bytes(data))
        self.data = bytearray(self.build())   # canonical bytes (== input for stock files)

    # ---- parsing --------------------------------------------------------- #
    def _parse(self, d: bytes):
        n = len(d)
        u32 = lambda o: struct.unpack_from("<I", d, o)[0]
        pcount = u32(24)
        if pcount > 64 or 28 + 4 * pcount > n:
            raise GenError(f"implausible pattern_count {pcount}")
        by_off: dict[int, object] = {}
        parsers = (Hdr.parse, PosTable.parse, MonPosTable.parse, Roster.parse, Roster.parse)

        def block(off, kind_idx):
            if off in by_off:
                return by_off[off]
            if not (28 <= off < n):
                raise GenError(f"sub-block offset {off} outside the file")
            obj = parsers[kind_idx](d, off)
            by_off[off] = obj
            self._blocks.append(obj)
            return obj

        for i in range(pcount):
            P = u32(28 + 4 * i)
            if P + 4 > n:
                raise GenError(f"pattern {i} offset {P} outside the file")
            ecount = u32(P)
            if ecount > 4096 or P + 4 + ENTRY_SIZE * ecount > n:
                raise GenError(f"pattern {i} claims {ecount} entries")
            entries = []
            for e in range(ecount):
                o = P + 4 + ENTRY_SIZE * e
                kind, weight = struct.unpack_from("<HH", d, o)
                offs = struct.unpack_from("<5I", d, o + 4)
                objs = [block(off, k) for k, off in enumerate(offs)]
                ent = Entry(kind, weight, objs[0], objs[1], objs[2], objs[3], objs[4])
                ent.off = o
                ent.subtable_offsets = tuple(offs)
                entries.append(ent)
            self.patterns.append(entries)
        # keep the blocks in file order so a rebuild reproduces the file
        self._blocks.sort(key=lambda b: b.orig_off)

    @classmethod
    def load(cls, path) -> "GenTable":
        return cls(pathlib.Path(path).read_bytes())

    # ---- queries --------------------------------------------------------- #
    def all_entries(self):
        for pi, entries in enumerate(self.patterns):
            for ei, e in enumerate(entries):
                yield pi, ei, e

    def roster(self, monsters_only: bool = True):
        """Aggregate {monster_id: total_count} across the file's rosters (each shared
        roster block counted once per entry that uses it, as the game would spawn it)."""
        from collections import Counter
        c = Counter()
        for _pi, _ei, e in self.all_entries():
            for s in e.spawns:
                if monsters_only and not (MONSTER_LO <= s.monster_id <= MONSTER_HI):
                    continue
                c[s.monster_id] += 1
        return c

    def _all_blocks(self):
        """Distinct blocks in emission order: original blocks in file order, new ones
        (no orig_off) appended in first-use order."""
        seen, out = set(), []
        for b in self._blocks:
            if id(b) not in seen and b.orig_off is not None:
                seen.add(id(b)); out.append(b)
        for _pi, _ei, e in self.all_entries():
            for b in e.blocks():
                if id(b) not in seen:
                    seen.add(id(b)); out.append(b)
        # drop blocks nothing references any more (removed gates)
        live = {id(b) for _pi, _ei, e in self.all_entries() for b in e.blocks()}
        return [b for b in out if id(b) in live]

    # ---- retuning (same-size, in place) --------------------------------- #
    def set_gate_kind(self, pi, ei, kind):
        self.patterns[pi][ei].gate_kind = kind & 0xFFFF
        self._sync()

    def set_weight(self, pi, ei, weight):
        self.patterns[pi][ei].weight = weight & 0xFFFF
        self._sync()

    def set_spawn_monster(self, spawn: Spawn, monster_id: int):
        """Replace a spawn record's monster id (keeps the pick weight)."""
        spawn.monster_id = monster_id & 0xFFFF
        self._sync()

    def set_spawn_pick_weight(self, spawn: Spawn, pick_weight: int):
        """Set the record's high u16 = the monster's pick weight in the roster."""
        spawn.pick_weight = pick_weight & 0xFFFF
        self._sync()

    def set_spawn_weights(self, spawn: Spawn, weights):
        """Set the per-monster-position weights (K values). K should equal the number of
        monster positions of every gate using the roster, and every record must keep
        record 0's K (the game reads the roster with record 0's stride) -- see validate()."""
        spawn.weights = [int(w) & 0xFFFFFFFF for w in weights]
        self._sync()

    def set_hdr(self, e: Entry, count_min=None, count_max=None, spawn_delay=None, param_a=None,
                flag=None):
        h = e.hdr
        if count_min is not None: h.count_min = count_min & 0xFF
        if count_max is not None: h.count_max = count_max & 0xFF
        if spawn_delay is not None: h.spawn_delay = spawn_delay & 0xFFFF
        if param_a is not None: h.param_a = param_a & 0xFFFF
        if flag is not None: h.flag = flag & 0xFFFF
        self._sync()

    # ---- positions (for the map overlay) -------------------------------- #
    def gate_positions(self, e: Entry) -> list:
        """Map positions where this gate's actor can be placed (sub-units; >>3 = tile)."""
        return [(x, y) for x, y in e.gate_pos.points]

    def monster_positions(self, e: Entry) -> list:
        """Map positions where the gate's monsters spawn (sub-units; >>3 = tile)."""
        return [(x, y) for x, y, _extra in e.mon_pos.points]

    def gate_positions_off(self, e: Entry) -> list:
        """[(rec_off, x, y), ...] -- rec_off identifies the point for set_position()."""
        base = self._offset_of(e.gate_pos) + 4
        return [(base + 4 * i, x, y) for i, (x, y) in enumerate(e.gate_pos.points)]

    def monster_positions_off(self, e: Entry) -> list:
        base = self._offset_of(e.mon_pos) + 4
        return [(base + 8 * i, x, y) for i, (x, y, _ex) in enumerate(e.mon_pos.points)]

    def set_position(self, rec_off: int, x: int, y: int):
        """Move a gate or monster position identified by the rec_off returned from
        gate_positions_off() / monster_positions_off()."""
        for b in self._all_blocks():
            if isinstance(b, PosTable):
                base = self._offset_of(b) + 4
                i = (rec_off - base) // 4
                if 0 <= i < len(b.points) and base + 4 * i == rec_off:
                    b.points[i] = (int(x) & 0xFFFF, int(y) & 0xFFFF)
                    self._sync(); return
            elif isinstance(b, MonPosTable):
                base = self._offset_of(b) + 4
                i = (rec_off - base) // 8
                if 0 <= i < len(b.points) and base + 8 * i == rec_off:
                    _x, _y, extra = b.points[i]
                    b.points[i] = (int(x) & 0xFFFF, int(y) & 0xFFFF, extra)
                    self._sync(); return
        raise GenError(f"no position record at offset {rec_off}")

    # ---- restructuring -------------------------------------------------- #
    def add_entry(self, pi: int, gate_kind: int, weight: int, clone: Entry | None = None,
                  share: bool = True, gate_pos=None, mon_pos=None) -> Entry:
        """Append a gate entry to pattern `pi` (created if the file is empty).
        With `clone`, the new gate reuses that entry's blocks (shared, so later edits
        affect both) or, with share=False, private copies of them. Without a clone,
        fresh blocks are created from `gate_pos` [(x, y)] and `mon_pos` [(x, y)] with an
        empty roster. Returns the new entry."""
        while len(self.patterns) <= pi:
            self.patterns.append([])
        if clone is not None:
            if share:
                ent = Entry(gate_kind, weight, clone.hdr, clone.gate_pos, clone.mon_pos,
                            clone.roster, clone.roster_alt)
            else:
                roster = clone.roster.copy()
                alt = roster if clone.roster_alt is clone.roster else clone.roster_alt.copy()
                ent = Entry(gate_kind, weight, clone.hdr.copy(), clone.gate_pos.copy(),
                            clone.mon_pos.copy(), roster, alt)
        else:
            gp = PosTable([(int(x) & 0xFFFF, int(y) & 0xFFFF) for x, y in (gate_pos or [])])
            mp = MonPosTable([(int(p[0]) & 0xFFFF, int(p[1]) & 0xFFFF,
                               int(p[2]) & 0xFFFFFFFF if len(p) > 2 else 0)
                              for p in (mon_pos or [])])
            ent = Entry(gate_kind, weight, Hdr(), gp, mp, Roster())
        self.patterns[pi].append(ent)
        self._sync()
        return ent

    def remove_entry(self, pi: int, ei: int) -> Entry:
        ent = self.patterns[pi].pop(ei)
        self._sync()
        return ent

    def add_spawn(self, e: Entry, monster_id: int, pick_weight: int, weights=None) -> Spawn:
        """Add a monster to the gate's roster. `pick_weight` is the record's high u16 = the
        monster's pick weight within the roster (5 or 10 is typical). `weights` defaults to
        one weight of 10 per monster position
        (K = number of monster positions), matching the stock files."""
        if weights is None:
            weights = [10] * max(1, len(e.mon_pos.points))
        s = Spawn(monster_id, pick_weight, weights)
        e.roster.spawns.append(s)
        self._sync()
        return s

    def remove_spawn(self, e: Entry, index: int) -> Spawn:
        s = e.roster.spawns.pop(index)
        self._sync()
        return s

    def add_gate_position(self, e: Entry, x: int, y: int):
        e.gate_pos.points.append((int(x) & 0xFFFF, int(y) & 0xFFFF))
        self._sync()

    def remove_gate_position(self, e: Entry, index: int):
        e.gate_pos.points.pop(index)
        self._sync()

    def add_monster_position(self, e: Entry, x: int, y: int, extra: int = 0, weight: int = 10):
        """Add a monster spawn point; every roster record using this gate's monster
        positions gets one more weight (K stays equal to the point count)."""
        e.mon_pos.points.append((int(x) & 0xFFFF, int(y) & 0xFFFF, int(extra) & 0xFFFFFFFF))
        for r in self._rosters_using(e.mon_pos):
            for s in r.spawns:
                s.weights.append(int(weight))
        self._sync()

    def remove_monster_position(self, e: Entry, index: int):
        e.mon_pos.points.pop(index)
        for r in self._rosters_using(e.mon_pos):
            for s in r.spawns:
                if index < len(s.weights):
                    s.weights.pop(index)
        self._sync()

    def _rosters_using(self, mon_pos):
        out, seen = [], set()
        for _pi, _ei, ent in self.all_entries():
            if ent.mon_pos is mon_pos:
                for r in (ent.roster, ent.roster_alt):
                    if id(r) not in seen:
                        seen.add(id(r)); out.append(r)
        return out

    def unshare(self, e: Entry, which=("hdr", "gate_pos", "mon_pos", "roster")):
        """Give entry `e` private copies of the named blocks so edits no longer affect
        the other gates sharing them."""
        for name in which:
            b = getattr(e, name)
            if name == "roster":
                same_alt = e.roster_alt is e.roster
                e.roster = b.copy()
                if same_alt:
                    e.roster_alt = e.roster
            else:
                setattr(e, name, b.copy())
        self._sync()

    # ---- consistency checks ---------------------------------------------- #
    def validate(self) -> list[str]:
        """Problems the game would trip over, checked against Encounter_TickMonster-
        SpawnSlots, Encounter_SpawnMonsterFromTemplate, Map_LoadAndUnpackMonsterSpawn-
        Tables and the Companion_* consumers. Lines starting 'ERROR: ' crash, hang or
        corrupt memory; the rest load but misbehave."""
        out = []
        err = lambda m: out.append("ERROR: " + m)
        if len(self.patterns) > MAX_PATTERNS:
            err(f"{len(self.patterns)} patterns: each spawns one gate into the spawn task's "
                f"{MAX_PATTERNS}-slot gate array, unchecked -- the extra gates overwrite the "
                f"monster slots behind it")
        for pi, entries in enumerate(self.patterns):
            wsum = sum(e.weight for e in entries)
            if entries and wsum == 0:
                out.append(f"pattern {pi}: every gate has weight 0, nothing can be picked")
            elif wsum > 0xFFFF:
                out.append(f"pattern {pi}: gate weights sum to {wsum}; the tick sums them in a "
                           f"u16 ({wsum & 0xFFFF}), which skews the pick")
            for ei, e in enumerate(entries):
                tag = f"pattern {pi} gate {ei}"
                if CRASH_KIND_LO <= e.gate_kind <= CRASH_KIND_HI:
                    err(f"{tag}: kind {e.gate_kind} is in 48..277, which Encounter_Spawn"
                        f"MonsterFromTemplate spawns through a NULL pointer (crash); use a "
                        f"Gate actor (359..390)")
                elif not (GATE_KIND_LO <= e.gate_kind <= GATE_KIND_HI):
                    out.append(f"{tag}: kind {e.gate_kind} is not a Gate actor (359..390)")
                h = e.hdr
                if h.count_min > MAX_ENGAGED:
                    out.append(f"{tag}: count_min {h.count_min} > {MAX_ENGAGED} (the engaged-"
                               f"monster slots) -- the gate never spawns a wave")
                elif h.count_min > h.count_max:
                    out.append(f"{tag}: count_min {h.count_min} > count_max {h.count_max}")
                if h.count_max > MAX_ENGAGED:
                    out.append(f"{tag}: count_max {h.count_max} is capped at {MAX_ENGAGED}")
                if not e.gate_pos.points:
                    out.append(f"{tag}: no gate positions -- the tick still picks index 0 and "
                               f"reads the dword after the count (the next block) as the gate "
                               f"position (GenN03 ships like this)")
                m = len(e.mon_pos.points)
                if not m:
                    out.append(f"{tag}: no monster positions")
                elif m > MAX_INDEX7:
                    out.append(f"{tag}: {m} monster positions, but the picked index is kept "
                               f"in 7 bits (only the first {MAX_INDEX7} are reachable)")
                for rname, ro in (("roster", e.roster), ("alt roster", e.roster_alt)):
                    if rname == "alt roster" and ro is e.roster:
                        continue
                    self._validate_roster(f"{tag} {rname}", ro, m, err, out)
        return out

    @staticmethod
    def _validate_roster(tag, roster, m, err, out):
        sp = roster.spawns
        if not sp:
            err(f"{tag}: empty -- the consumers still read record 0 (past the block) as "
                f"the monster to spawn")
            return
        if len(sp) > MAX_INDEX7:
            out.append(f"{tag}: {len(sp)} records, but the picked index is kept in 7 bits "
                       f"(only the first {MAX_INDEX7} are reachable)")
        k0 = len(sp[0].weights)
        bad = [i for i, s in enumerate(sp[:-1]) if len(s.weights) != k0]
        if bad:
            err(f"{tag}: records {bad} have K != {k0} (record 0's): the game steps through "
                f"the roster with the fixed stride 8 + 4*K0, so every record after the first "
                f"mismatch is read at the wrong offset (give every record the same K)")
        if len(sp[-1].weights) > k0 + len(sp) - 1:
            out.append(f"{tag}: the last record's {len(sp[-1].weights)} weights run past the "
                       f"unpacker's copy (N * (12 + 4*K0) bytes); the tail reads uninitialised "
                       f"memory")
        if sum(s.pick_weight for s in sp) == 0:
            out.append(f"{tag}: every pick_weight is 0, so no monster is ever picked")
        for si, s in enumerate(sp):
            k = len(s.weights)
            if m and k != m:
                (err if k > m else out.append)(
                    f"{tag} monster {si}: {k} position weights but {m} monster positions -- "
                    + ("the pick can land past the position table (garbage spawn point)"
                       if k > m else "the unpacker then shrinks the cached position count")
                    + "; keep K == monster positions")
            if not (MONSTER_LO <= s.monster_id <= MONSTER_HI):
                out.append(f"{tag} monster {si}: id {s.monster_id} is not a bestiary "
                           f"monster (48..254)")
            lb = sum(w & 0xFF for w in s.weights)
            if k and lb == 0:
                out.append(f"{tag} monster {si}: position weights are all 0 (low byte), so "
                           f"its spawn point is never picked")
            elif lb > 0xFF:
                out.append(f"{tag} monster {si}: position weights sum to {lb}; the game sums "
                           f"the low bytes in a u8 ({lb & 0xFF}) -- keep the total <= 255")
            if any(w > 0xFF for w in s.weights):
                out.append(f"{tag} monster {si}: a position weight above 255 -- only the "
                           f"low byte is read")

    # ---- rebuild --------------------------------------------------------- #
    def _layout(self):
        """Assign offsets: header, pattern offset table, pattern arrays, blocks."""
        pos = HEADER_SIZE + 4 * len(self.patterns)
        pat_off = []
        for entries in self.patterns:
            pat_off.append(pos)
            pos += 4 + ENTRY_SIZE * len(entries)
        blocks = self._all_blocks()
        block_off = {}
        for b in blocks:
            block_off[id(b)] = pos
            pos += b.size()
        return pat_off, blocks, block_off, pos

    def _offset_of(self, b) -> int:
        _po, _blocks, block_off, _end = self._layout()
        return block_off[id(b)]

    def _sync(self):
        """Refresh the canonical bytes plus every cached offset after an edit."""
        self.data = bytearray(self.build())

    def build(self) -> bytes:
        pat_off, blocks, block_off, byte_size = self._layout()
        out = bytearray()
        out += MAGIC + struct.pack("<I", self.build_date) + struct.pack("<II", *self.reserved)
        out += struct.pack("<III", self.version, byte_size, len(self.patterns))
        out += struct.pack(f"<{len(pat_off)}I", *pat_off)
        refs: dict[int, list[int]] = {}      # target offset -> field positions
        for i, po in enumerate(pat_off):
            refs.setdefault(po, []).append(HEADER_SIZE + 4 * i)
        for pi, entries in enumerate(self.patterns):
            out += struct.pack("<I", len(entries))
            for ei, e in enumerate(entries):
                o = pat_off[pi] + 4 + ENTRY_SIZE * ei
                e.off = o
                offs = tuple(block_off[id(b)] for b in e.blocks())
                e.subtable_offsets = offs
                out += struct.pack("<HH", e.gate_kind, e.weight)
                out += struct.pack("<5I", *offs)
                for k, off in enumerate(offs):
                    refs.setdefault(off, []).append(o + 4 + 4 * k)
        for b in blocks:
            assert len(out) == block_off[id(b)]
            if isinstance(b, Roster):
                pos = len(out) + 4
                for s in b.spawns:
                    s.rec_off = pos
                    pos += s.size()
            out += b.pack()
        assert len(out) == byte_size
        # footer: root + one descriptor per referenced object, ascending, then the lists
        targets = sorted(refs)
        n_desc = 1 + len(targets)
        lp = byte_size + 16 * n_desc
        out += struct.pack("<IIII", 0, 24, 0, 0)
        for t in targets:
            lst = sorted(refs[t])
            out += struct.pack("<IIII", 0, t, len(lst), lp)
            lp += 4 * len(lst)
        for t in targets:
            out += struct.pack(f"<{len(refs[t])}I", *sorted(refs[t]))
        return bytes(out)

    def save(self, path):
        pathlib.Path(path).write_bytes(self.build())

    # ---- human summary --------------------------------------------------- #
    def summary(self, name_fn=None) -> str:
        name_fn = name_fn or (lambda i: "")
        lines = [f"NLCL encounter table  (build {self.build_date:#x})  "
                 f"{len(self.patterns)} pattern(s)"]
        for pi, entries in enumerate(self.patterns):
            lines.append(f"  pattern {pi}: {len(entries)} gate entr"
                         f"{'y' if len(entries)==1 else 'ies'}")
            for ei, e in enumerate(entries):
                gk = name_fn(e.gate_kind)
                h = e.hdr
                lines.append(f"    [{ei}] gate {e.gate_kind}"
                             f"{' ('+gk+')' if gk else ''}  weight {e.weight}  "
                             f"keeps {h.count_min}-{h.count_max} alive, respawn base {h.spawn_delay} f"
                             f"{', gate level ' + str(h.param_a) if h.param_a else ''}"
                             f"  ({len(e.gate_pos.points)} gate pos, "
                             f"{len(e.mon_pos.points)} monster pos)")
                for si, s in enumerate(e.spawns):
                    if not (MONSTER_LO <= s.monster_id <= MONSTER_HI):
                        continue
                    mn = name_fn(s.monster_id)
                    lines.append(f"         [{si}] {s.monster_id}"
                                 f"{' ('+mn+')' if mn else ''}  pick weight {s.pick_weight}  "
                                 f"position weights {s.weights}")
        roster = self.roster()
        if roster:
            top = ", ".join(f"{name_fn(i) or i}" for i, _ in roster.most_common())
            lines.append(f"  roster: {top}")
        probs = self.validate()
        for p in probs:
            lines.append(f"  ! {p}")
        return "\n".join(lines)


# ---- actor-name helper ---------------------------------------------------- #
def load_actor_names(path):
    """Load rf4s_actor_names.json -> {id:int -> name}. Returns a lookup fn."""
    import json
    d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    table = {int(k): v for k, v in d.items()}
    return lambda i: table.get(i, "")
