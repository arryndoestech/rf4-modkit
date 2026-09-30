r"""
search_items.py -- RF4S `SI_*.bin` "search-item spot" tables (daily ground pickups).

`SI_DUNG_*.bin`, `SI_FIELD_*.bin`, `SI_CITY_*.bin` (288 files in bundleMain) are
per-map tables of "search spots": candidate positions where the engine may place a
visible ground item each day -- the random pickups you find lying around town,
fields and dungeons. (They are not "interact-to-rummage" spots: the
IDA-verified consumer shows they are spawned as ordinary visible item drops.)

Engine chain (IDA-verified 2026-06-10)
--------------------------------------
- `GameSystems_Init` spawns the long-lived task **`search_item_mng`**.
- Its tick `SearchItemMng_TickRollAndSpawnDailySpots` (RF4S.exe+0x231E80) reacts to
  "needs roll": `archive_id = g_searchItemArchiveByMapId[map_id]` (+0x4DD260; 870 u32
  slots, map ids >= 870 never roll; 305 non-zero covering archive ids 14878..15165;
  the room's BASE id, so seasonal variants share their base map's file), then
  `nsFileArchive_Load`, `SearchItem_RollSpotsAndSpawnFromArchive` (+0x231FF0), release.
  The game picks the file by MAP ID, not by name (rf4s_modkit.exesidecars ships the
  table): MAP_CITY_05 loads SI_CITY_06.bin, MAP_CITY_06 none, MAP_FIELD_A0/A2/A3 load
  SI_FIELD_101/103/104.bin, and SI_DUNG_E45.bin is never loaded. A map whose entry is 0
  never gets search items, whatever file is saved for it.
- "needs roll" is set on map entry by Scene_FinalizeMajorTransition (RF4S.exe+0x14117C)
  only once the story has reached step 39 (g_storyProgressFlag9bit >= 39, no search
  items before that), and then only on HALF the visits (a 50 % gameplay-RNG roll per
  entry; the losing half sets the map's done-today bit: nothing that visit, and at most
  one item on a later visit that day). So a freshly edited spot table shows nothing on
  about half the visits.
- Roll algorithm (deterministic per day via `Calendar_DerivedDailyRandStream`;
  sleeping rerolls):

      chance = spot_count            # low byte
      spawned = per_map_already_rolled_bit   # 0 or 1
      for i, spot in enumerate(spots):
          if spawned >= 2: break
          if DailyRand(chance, stream=i) == 0:     # 1-in-chance per spot
              chance -= 1
              total = sum(entry.weight_byte) & 0xFF   # u8 sum -- WRAPS mod 256!
              roll  = DailyRand(total, stream=i+2)
              pick first entry where cumulative weight > roll
              spawn Item_SpawnVisualTask((entry & 0x7FF) | 0x800)
                  at Q12 world pos ((x-4) << 12, (y-8) << 12)
              spawned += 1

  So at most **2 items per map per day**; the per-map "already rolled today" bit
  (in the manager's work buffer) reduces that to 1 once set.

  Counter widths (from the disassembly): the spot index and the entry index are
  u8 registers compared against the u32 counts, and `chance` / both weight sums are
  u8. Consequences for edited files:
    * a pool with more than 255 entries HANGS the game the first time a spot using it
      wins its chance roll (the u8 entry counter wraps before reaching the count);
    * spot index 253 or higher can HANG the game: Calendar_DerivedDailyRandStream
      (+0x2321D0) steps its generator (u8 stream + 1) times with a u8 counter, so stream
      255 means 256 steps the counter never reaches -- an endless loop. The item pick
      of spot i uses stream (i + 2) & 0xFF (`lea edx,[rdi+2]` at +0x2320C1), so spot 253
      hangs as soon as it wins its chance roll; spot 255's own chance roll (stream 255)
      hangs whenever the loop reaches it. Safe maximum: 253 spots (indices 0..252).
      (Past 255 spots the u8 spot index also wraps and the chance is the count's low
      byte, but the hang comes first.);
    * a pool whose weight bytes sum to 0 (mod 256) never yields an item, but the spot
      still consumes one decrement of `chance`.
  See `SearchItemFile.validate()`.

File layout
-----------

    +0x00..+0x1C  NLCL header (28 B):
        +0x00  "NLCL"
        +0x04  u32 build_date (BCD, 0x20201119 in all 288 files)
        +0x08  8 reserved zeros
        +0x10  u32 version (always 2 for SI files)
        +0x14  u32 byte_size  -- size of the NLCL chunk (not the file size)
        +0x18  u32 spot_count

    +0x1C..+(0x1C + 8*spot_count)  Spot records (8 B each):
        +0  u16 x  -- in SUB-UNITS (1 tile = 8 sub-units; tile = x >> 3)
        +2  u16 y  -- sub-units. Engine spawns at Q12 ((x-4)<<12, (y-8)<<12).
        +4  u32 drop_pool_offset  -- ABSOLUTE file offset of a drop pool
                                     (engine resolves base+offset manually)

    Drop pools (multiple spots may share one; every stock file has exactly ONE):
        +0   u32 entry_count
        +4   u32[entry_count] entries:
                 bits 0..10  = item_id   (engine masks & 0x7FF, then | 0x800)
                 bits 16..23 = weight    (relative; cumulative-sum pick)
                 bits 11..15 and 24..31 are IGNORED by the engine
        Engine quirk: total weight is summed in a u8 -- pools whose weights sum
        past 255 wrap mod 256 and skew the distribution (worst case the first
        entry always wins). NO stock pool triggers this (max stock total is
        <= 255); it is a latent engine bug that only bites edited files.
        Keep totals <= 255 when authoring.

    After byte_size: the generic **NLCL footer** -- a serialized-object
    cross-reference table emitted by the build tool, IGNORED by the engine
    (consumers resolve internal offsets manually; corrupt entries ship in
    SI_CITY_00 with no in-game effect). Present on ALL 1062 NLCL files:

        repeated 16-byte descriptors {u32 0; u32 object_offset; u32 ref_count;
                                      u32 ref_list_offset (absolute, or 0)}
        then the ref lists: each is ref_count u32s = absolute offsets of every
        u32 field inside the chunk whose stored value == object_offset.

        First descriptor is always {0, 24, 0, 0} = the root record array at +24
        (nothing inside the chunk points to it). For an SI file with one pool at
        `rec_end` shared by N spots, the second descriptor is
        {0, rec_end, N, byte_size+32} and the list holds {0x20 + 8*i} -- the
        file offsets of each spot record's drop_pool_offset field.

    Validated: 1062/1062 NLCL files (SI + Gen + rf3 params) parse under this
    footer scheme with every listed reference resolving to its target. The
    engine never walks the table -- IDA-verified consumers (Gen's
    `Map_LoadAndUnpackMonsterSpawnTables`, SI's roll function) resolve internal
    offsets manually as `base + offset` -- so an inconsistent footer (e.g. from
    a hand-edit that duplicates a record without regenerating the list) is
    harmless. `build()` regenerates the footer canonically. Round-trip is
    byte-perfect on all 288 pristine SI files (verified before local edits).
"""
from __future__ import annotations

import pathlib
import struct
from dataclasses import dataclass, field

MAGIC = b"NLCL"
HEADER_SIZE = 28
DEFAULT_BUILD_DATE = 0x20201119
SI_VERSION = 2
MAX_DAILY_SPAWNS = 2          # engine cap per map per day
WEIGHT_SUM_LIMIT = 255        # engine sums weights in a u8 -- avoid exceeding
# Spot i picks its item with Calendar_DerivedDailyRandStream stream (i + 2) & 0xFF, and
# stream 255 loops forever (a u8 step counter that must reach 256): spot 253 hangs when it
# wins its chance roll, spot 255 as soon as the loop reaches it -> at most 253 spots.
MAX_SPOTS = 253
# The weight-sum and pick loops count entries in a u8 (`inc al` / `inc dl` compared with
# the u32 count at +0x2320B3 / +0x2320F1): 255 entries end the loop at 255, 256 never do.
MAX_POOL_ENTRIES = 255


class SearchItemError(Exception):
    pass


@dataclass
class DropEntry:
    item_id: int   # 11 bits used by the engine (& 0x7FF)
    weight: int    # only the LOW BYTE is used by the engine

    def pack(self) -> int:
        if not (0 <= self.item_id <= 0xFFFF and 0 <= self.weight <= 0xFFFF):
            raise SearchItemError(
                f"drop entry out of range: item_id={self.item_id}, weight={self.weight}"
            )
        return self.item_id | (self.weight << 16)

    @classmethod
    def unpack(cls, packed: int) -> "DropEntry":
        return cls(item_id=packed & 0xFFFF, weight=(packed >> 16) & 0xFFFF)

    @property
    def effective_item_id(self) -> int:
        """The item id the engine actually uses (11 bits)."""
        return self.item_id & 0x7FF

    @property
    def effective_weight(self) -> int:
        """The weight byte the engine actually uses."""
        return self.weight & 0xFF


@dataclass
class DropPool:
    entries: list[DropEntry] = field(default_factory=list)

    def total_weight(self) -> int:
        return sum(e.effective_weight for e in self.entries)

    def engine_total_weight(self) -> int:
        """Total as the engine computes it -- a u8 sum that wraps mod 256."""
        return self.total_weight() & 0xFF

    def engine_chances(self) -> tuple[list[float], float]:
        """(percent per entry, percent of 'nothing spawns') exactly as the game picks.

        SearchItem_RollSpotsAndSpawnFromArchive (RF4S.exe+0x231FF0) keeps BOTH sums in a
        byte: total = sum(weights) & 0xFF, roll = DailyRand(total) (uniform 0..total-1;
        Calendar_DerivedDailyRandStream +0x2321D0 returns 0 for a range of 0), then the
        running sum (also & 0xFF) picks the first entry with roll < running. Up to a total
        of 255 this is weight / total; above it, entries past the wrap can get 0 % and the
        rest shift. 'Nothing' happens only when no running sum ever exceeds the roll."""
        n = len(self.entries)
        total = self.engine_total_weight()
        rolls = range(total) if total else (0,)
        hits = [0] * n
        none = 0
        for roll in rolls:
            run = 0
            for k, e in enumerate(self.entries):
                run = (run + e.effective_weight) & 0xFF
                if roll < run:
                    hits[k] += 1
                    break
            else:
                none += 1
        m = len(rolls)
        return [100.0 * h / m for h in hits], 100.0 * none / m


@dataclass
class SearchSpot:
    x: int   # sub-units (1 tile = 8); tile = x >> 3
    y: int   # sub-units; engine spawns the item at Q12 ((x-4)<<12, (y-8)<<12)
    pool: DropPool

    @property
    def tile_x(self) -> int:
        return self.x >> 3

    @property
    def tile_y(self) -> int:
        return self.y >> 3

    @property
    def packed_pos(self) -> int:
        if not (0 <= self.x <= 0xFFFF and 0 <= self.y <= 0xFFFF):
            raise SearchItemError(f"spot position out of range: ({self.x}, {self.y})")
        return self.x | (self.y << 16)


@dataclass
class SearchItemFile:
    """Parsed `SI_*.bin`. Spots and pools are decoupled -- multiple spots may share
    a pool via reference identity (every stock file has exactly one pool shared by
    all its spots). `merge_shared_pools()` collapses byte-equal pools before
    serialisation if you've edited individual ones apart."""

    spots: list[SearchSpot] = field(default_factory=list)
    build_date: int = DEFAULT_BUILD_DATE
    version: int = SI_VERSION

    def __post_init__(self):
        # Footgun guard: SearchItemFile(raw_bytes) would silently store bytes as `spots`
        # (dataclass positional). Point the caller at the real parsers.
        if isinstance(self.spots, (bytes, bytearray, str)):
            raise SearchItemError(
                "SearchItemFile() takes a list of SearchSpot, not raw bytes -- "
                "use SearchItemFile.parse(data) or SearchItemFile.load(path).")

    # ---------------- parse ---------------------------------------------- #
    @classmethod
    def parse(cls, data: bytes) -> "SearchItemFile":
        if data[:4] != MAGIC:
            raise SearchItemError(f"not NLCL (magic={data[:4]!r})")
        build_date = struct.unpack_from("<I", data, 4)[0]
        version = struct.unpack_from("<I", data, 16)[0]
        byte_size = struct.unpack_from("<I", data, 20)[0]
        spot_count = struct.unpack_from("<I", data, 24)[0]

        if version != SI_VERSION:
            raise SearchItemError(
                f"unexpected NLCL version {version} (expected {SI_VERSION})"
            )
        if byte_size > len(data):
            raise SearchItemError(f"byte_size {byte_size} exceeds file size {len(data)}")

        pools_by_off: dict[int, DropPool] = {}
        raw_records: list[tuple[int, int]] = []
        for i in range(spot_count):
            off = HEADER_SIZE + i * 8
            pos = struct.unpack_from("<I", data, off)[0]
            poff = struct.unpack_from("<I", data, off + 4)[0]
            raw_records.append((pos, poff))

        for poff in {p for (_, p) in raw_records}:
            if poff + 4 > byte_size:
                raise SearchItemError(f"drop pool offset {poff} past byte_size {byte_size}")
            n = struct.unpack_from("<I", data, poff)[0]
            if poff + 4 + n * 4 > byte_size:      # full entry span, not just the pool header
                raise SearchItemError(
                    f"drop pool at {poff} claims {n} entries running past byte_size {byte_size}")
            entries = []
            for k in range(n):
                packed = struct.unpack_from("<I", data, poff + 4 + k * 4)[0]
                entries.append(DropEntry.unpack(packed))
            pools_by_off[poff] = DropPool(entries=entries)

        spots = [
            SearchSpot(x=pos & 0xFFFF, y=(pos >> 16) & 0xFFFF, pool=pools_by_off[poff])
            for pos, poff in raw_records
        ]
        return cls(spots=spots, build_date=build_date, version=version)

    @classmethod
    def load(cls, path) -> "SearchItemFile":
        return cls.parse(pathlib.Path(path).read_bytes())

    # ---------------- write ---------------------------------------------- #
    def merge_shared_pools(self) -> None:
        """Collapse byte-identical DropPool objects into a single shared instance,
        so the serialiser writes one pool with multiple references."""
        canonical: dict[bytes, DropPool] = {}
        for spot in self.spots:
            key = bytes(_pack_pool_bytes(spot.pool))
            canonical.setdefault(key, spot.pool)
            spot.pool = canonical[key]

    def build(self) -> bytes:
        """Serialise back to the SI_*.bin byte stream (NLCL chunk + footer).

        The footer (the build-tool xref table -- see module docstring) is
        regenerated canonically: one descriptor per unique pool, reference lists
        in record order. The engine ignores it either way."""
        spot_count = len(self.spots)
        records_end = HEADER_SIZE + 8 * spot_count

        pool_offset: dict[int, int] = {}
        pool_refs: dict[int, list[int]] = {}      # pool id -> ref field offsets
        pool_blob = bytearray()
        for i, spot in enumerate(self.spots):
            key = id(spot.pool)
            if key not in pool_offset:
                pool_offset[key] = records_end + len(pool_blob)
                pool_refs[key] = []
                pool_blob += struct.pack("<I", len(spot.pool.entries))
                for e in spot.pool.entries:
                    pool_blob += struct.pack("<I", e.pack())
            pool_refs[key].append(HEADER_SIZE + 8 * i + 4)   # the pool_offset field

        byte_size = records_end + len(pool_blob)

        out = bytearray()
        out += MAGIC
        out += struct.pack("<I", self.build_date)
        out += b"\x00" * 8
        out += struct.pack("<I", self.version)
        out += struct.pack("<I", byte_size)
        out += struct.pack("<I", spot_count)
        for spot in self.spots:
            out += struct.pack("<I", spot.packed_pos)
            out += struct.pack("<I", pool_offset[id(spot.pool)])
        out += pool_blob

        # Footer: root descriptor + one descriptor per pool + ref lists.
        pools_in_order = list(pool_offset.keys())
        n_desc = 1 + len(pools_in_order)
        lists_start = byte_size + 16 * n_desc
        out += struct.pack("<IIII", 0, 24, 0, 0)             # root object at +24
        lp = lists_start
        for key in pools_in_order:
            refs = pool_refs[key]
            out += struct.pack("<IIII", 0, pool_offset[key], len(refs), lp)
            lp += 4 * len(refs)
        for key in pools_in_order:
            for r in pool_refs[key]:
                out += struct.pack("<I", r)
        return bytes(out)

    def save(self, path) -> None:
        pathlib.Path(path).write_bytes(self.build())

    # ---------------- validation ----------------------------------------- #
    def validate(self) -> list[str]:
        """What SearchItem_RollSpotsAndSpawnFromArchive (RF4S.exe+0x231FF0) would trip
        over, as 'ERROR: ...' (hang) / 'WARN: ...' (loads, misbehaves) lines."""
        errs, warns = [], []
        n = len(self.spots)
        if n > MAX_SPOTS:
            errs.append(f"{n} spots: at most {MAX_SPOTS} -- spot #{MAX_SPOTS} (and any after) "
                        f"can HANG the game: its daily random roll uses stream 255, which "
                        f"the game's random-number routine never finishes")
        seen = {}
        for i, sp in enumerate(self.spots):
            seen.setdefault(id(sp.pool), (i, sp.pool))
            if not (0 <= sp.x <= 0xFFFF and 0 <= sp.y <= 0xFFFF):
                errs.append(f"spot {i}: position ({sp.x},{sp.y}) does not fit the u16 fields")
            elif sp.x < 4 or sp.y < 8:
                warns.append(f"spot {i}: the item spawns at ((x-4),(y-8)) sub-units, so "
                             f"({sp.x},{sp.y}) puts it off the map's top/left edge")
        for i, pool in seen.values():
            ne = len(pool.entries)
            tag = f"pool of spot {i}"
            if ne > MAX_POOL_ENTRIES:
                errs.append(f"{tag}: {ne} entries -- the weight-sum loop counts entries in a "
                            f"u8 and never reaches {ne}: the game HANGS when this pool is rolled "
                            f"(max {MAX_POOL_ENTRIES})")
            if ne == 0:
                warns.append(f"{tag}: no entries -- a winning spot spawns nothing but still "
                             f"uses up one step of the daily chance")
                continue
            raw = pool.total_weight()
            if raw > WEIGHT_SUM_LIMIT:
                warns.append(f"{tag}: weight bytes sum to {raw}; the engine sums in a u8 "
                             f"({raw & 0xFF}), which skews or breaks the pick -- keep <= 255")
            chances, nothing = pool.engine_chances()
            if nothing >= 100.0:
                warns.append(f"{tag}: no entry can ever be picked (every running weight sum "
                             f"is 0), so this pool never yields an item")
            elif raw > WEIGHT_SUM_LIMIT:
                dead = [k for k, c in enumerate(chances) if c == 0.0]
                if dead:
                    warns.append(f"{tag}: with the wrapped sums, entr{'y' if len(dead) == 1 else 'ies'} "
                                 f"{', '.join(map(str, dead))} can never drop")
            for k, e in enumerate(pool.entries):
                if e.item_id > 0x7FF:
                    warns.append(f"{tag} entry {k}: item id {e.item_id} -- the engine keeps "
                                 f"only the low 11 bits ({e.effective_item_id})")
                if e.weight > 0xFF:
                    warns.append(f"{tag} entry {k}: weight {e.weight} -- only the low byte "
                                 f"({e.effective_weight}) is read")
        return [f"ERROR: {m}" for m in errs] + [f"WARN: {m}" for m in warns]

    # ---------------- inspection ----------------------------------------- #
    def dump(self, item_names: dict[int, str] | None = None) -> str:
        """Return a human-readable summary string."""
        item_names = item_names or {}
        lines = [f"SearchItemFile  spots={len(self.spots)}  "
                 f"(engine spawns at most {MAX_DAILY_SPAWNS}/day)"]
        seen: dict[int, list[int]] = {}
        for i, spot in enumerate(self.spots):
            seen.setdefault(id(spot.pool), []).append(i)
        for k, indices in seen.items():
            spot = self.spots[indices[0]]
            tag = (f"spots[{','.join(str(i) for i in indices)}]"
                   if len(indices) > 1 else f"spot[{indices[0]}]")
            poslist = ", ".join(
                f"({self.spots[i].x},{self.spots[i].y})=tile({self.spots[i].tile_x},{self.spots[i].tile_y})"
                for i in indices
            )
            lines.append(f"  {tag} @ {poslist}")
            total = spot.pool.engine_total_weight()
            raw_total = spot.pool.total_weight()
            if raw_total > WEIGHT_SUM_LIMIT:
                lines.append(f"      !! weight sum {raw_total} exceeds 255 -- engine "
                             f"wraps to {total}, distribution is skewed")
            chances, _nothing = spot.pool.engine_chances()
            for e, pct in zip(spot.pool.entries, chances):
                nm = item_names.get(e.effective_item_id, f"item_{e.effective_item_id}")
                lines.append(f"      {nm:<24}  w={e.effective_weight:3d}  (~{pct:4.1f}%)")
        lines += [f"  ! {m}" for m in self.validate() if m.startswith("ERROR")]
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _pack_pool_bytes(pool: DropPool) -> bytes:
    """Canonical byte form of a pool (for merge_shared_pools dedup key)."""
    buf = struct.pack("<I", len(pool.entries))
    for e in pool.entries:
        buf += struct.pack("<I", e.pack())
    return buf


def parse_nlcl_footer(data: bytes) -> list[tuple[int, int, list[int]]]:
    """Parse the generic NLCL footer of ANY NLCL file (SI, Gen, rf3 params).

    Returns [(object_offset, ref_count, [ref_field_offsets])]. Raises
    SearchItemError if a listed reference does not store its target offset.
    The footer is build-tool metadata; the engine ignores it."""
    if data[:4] != MAGIC:
        raise SearchItemError("not NLCL")
    byte_size = struct.unpack_from("<I", data, 20)[0]
    pos, descs = byte_size, []
    while pos + 16 <= len(data):
        a, tgt, n, lp = struct.unpack_from("<IIII", data, pos)
        if (a != 0 or tgt >= byte_size or (lp and not (byte_size <= lp <= len(data)))
                or (n and lp + 4 * n > len(data))):   # ref list must not run past EOF
            break
        descs.append((tgt, n, lp))
        pos += 16
    out = []
    for tgt, n, lp in descs:
        refs = list(struct.unpack_from(f"<{n}I", data, lp)) if n else []
        for r in refs:
            if struct.unpack_from("<I", data, r)[0] != tgt:
                raise SearchItemError(
                    f"footer ref at {r} stores {struct.unpack_from('<I', data, r)[0]}, "
                    f"expected target {tgt}"
                )
        out.append((tgt, n, refs))
    return out


def load_item_name_table(eng_text_path) -> dict[int, str]:
    """Load `rf3TxtItem_split2_1.eng` as id -> name dict (utility)."""
    from . import textdb
    arc = textdb.TextArchive.load(eng_text_path)
    return {i: e.decode("utf-8", "replace") for i, e in enumerate(arc.entries) if e}
