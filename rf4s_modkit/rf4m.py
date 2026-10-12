r"""
rf4m.py -- RF4S `.rf4m` compiled-map container read / edit / rebuild.

Layout (verified against Map_LoadById RF4S.exe+0x192820 and Map_LookupChunkType
+0x193040, re-read 2026-09-19):

    +0x00  "MAPD"                       file magic == chunk type 0
    +0x04  u32  total_file_size          (= 8 + chunk-stream length; the loader walks
                                          chunks from +8 up to buffer + this word)
    +0x08  chunk stream:
              tag[4]  u32 payload_size  payload[payload_size]   (repeated)

17 chunk types (0..16): MAPD MSEA MGRP MLIG IMGD ATTR MAPJ PALD PALA SOIL AREA POSD
MOBJ MCHD MCDA NSTX MTXN. Map_LoadById keeps a POINTER to each recognised chunk's
payload in the map task work buffer; only ATTR is also copied (Map_InitImage,
RF4S.exe+0x193110, allocates w*h cells and copies them, values unchanged, and keeps w/h
for the camera and the type-10 parallax record):

    MSEA  1 x u32   season tag of this file (0 spring/none, 1 summer, 2 autumn,
                    3 winter; 4 on the farm-house / barn / system rooms). Stored but
                    NO runtime reader was found (255-function sweep of the map task).
    MGRP  1 x u32   map group bitfield -- READ. bits 0..3 = fixed season for this
                    map's ambience (bit0 spring .. bit3 winter; Map_LoadById turns them
                    into work[15] = 0..3, -1 = follow the calendar): petals/leaves/
                    light motes, ambient sfx, BGM variant. bit 4 = no weather effects
                    (dungeons/interiors). bits 5..25 = area group (5 Selphia,
                    6 rooms, 7 farm, 8 fields, 9 DUNG_A ... 25 DUNG_O/P): the LOWEST
                    set bit gives the zone = bit - 5 (0 below 0x20), which picks the
                    base BGM (RF4S.exe+0x4D5710), the minimap group, the monster-gate
                    zone and the crate loot pool (chestloot.crate_pools). Bit 2
                    (autumn) also sets BGM target mode 2. MAP_F_ROOM_00 adds bits
                    22+23 to group 6: the minimap's room sub-group (lowest of 22+).
                    mgrp_explain() lists all of it. A map WITHOUT an MGRP chunk
                    crashes the loader (it dereferences the pointer unconditionally).
    MLIG  3 x u32   tile tint colours for DAY / EVENING / NIGHT, one dword each as
                    0x00BBGGRR (only the low 24 bits are read; a zero triplet means
                    "engine default": day 255,255,255, evening 247,214,197, night
                    148,214,247, or 181,214,214 on maps whose g_mapTypeAttribTable
                    entry has bit 0x10 -- mapres.night_default). Every shipped map stores
                    0xFF000000 x3 = all defaults; maps tint themselves through the
                    type-12 MOBJ parameter records instead (see mobj_params).
    ATTR  { u32 w; u32 h; u32 cells[w*h] }   collision/attribute grid, row-major.
    MAPJ  9 x i32 per chunk (36 B)  map-transition (warp) zones, one per chunk:
                    [0] disable-flag id (per-map scene bit, -1 = always active; the
                        warp is dead while the flag is SET -- Widget_UpdateBit20FromGameFlag)
                    [1..4] zone x, y, w, h in sub-units (8 per tile)
                    [5] destination map id   [6],[7] arrival x, y (sub-units)
                    [8] arrival facing in DEGREES (0 = keep; x182 -> Q16 angle)
    PALD  512 B per chunk, max 6   no runtime reader found; all-zero in every map.
    MOBJ  16 x i32 per chunk (64 B)  ONE placed-entity record per chunk. Types
                    0..8 forage spawners, 9..19 map PARAMETER records consumed at
                    load by Map_LoadById itself (tint colours, UV scroll, depth, ...),
                    20..195 actors, 196..335 interactive objects, >= 336 decorations.
    MTXN  1 x u32 per chunk, 1 or 2 chunks   the loader spawns ONE map_disp display
                    layer per MTXN chunk (1st = ground textures g_mapResourceTable[+1],
                    every later one = the overlay set [+2], nothing when [+2] is 0) and
                    stores it at work +88 + 8*j; only +88 / +96 are layer slots, so a 3rd
                    chunk writes into the pointers at +104..+128. Every shipped map has 2
                    chunks when it has an overlay id and 1 when it has none (mapres). The
                    dword value itself is never read.
    PALA / SOIL / AREA / POSD / MCHD / MCDA / NSTX: recognised, ignored, absent.
    IMGD: recognised but it has NO slot of its own: the walk's slot pointer is left
          at whatever the previous chunk used, so an IMGD chunk OVERWRITES the pointer
          of the chunk before it (after e.g. MGRP the map's MGRP now points at the IMGD
          payload); as the first slotted chunk it writes through an uninitialised
          stack pointer. Absent from every shipped map -- never add one.

Loader rules that matter for editing (all in Map_LoadById):
  * the walk runs from +8 to file + size word (the MAPD dword, signed); a chunk
    header is read without checking that 8 bytes remain;
  * the chunk walk STOPS at the first tag it does not know (Map_LookupChunkType
    returns 17): anything after an unknown tag is silently dropped;
  * MSEA / MGRP / MLIG / ATTR have ONE pointer slot each: a second chunk of the same
    tag replaces the first, so the game uses the LAST one (the single-chunk accessors
    here read and write that one too);
  * per-tag pointer arrays have fixed capacity and no bounds check except PALD:
    10 MAPJ, 6 PALD, 40 MOBJ, 6 MTXN chunks -- more overflows the next array (see
    ENGINE_MAX_CHUNKS / validate()). A 7th+ PALD gets no slot and, like IMGD,
    re-points the previous chunk's slot;
  * the consumers read exactly one record per chunk (Map_SpawnAllEntities,
    Map_SpawnEntityByCategoryAndIdx), so extra records packed into one chunk are
    never seen by the game;
  * map ids 0..63 are season-swapped: id += calendar season (0 spring .. 3 winter)
    unless the calendar season field is 4, so the four files of an outdoor map are
    consecutive ids and each season is its own .rf4m.

This module reads chunks, lets you replace a chunk's payload or edit ATTR cells,
and rebuilds a byte-valid container (fixing the MAPD size word).
"""
from __future__ import annotations

import pathlib
import re
import struct
from collections import Counter

from . import mobj_types

MAGIC = b"MAPD"

CHUNK_NAMES = [
    b"MAPD", b"MSEA", b"MGRP", b"MLIG", b"IMGD", b"ATTR", b"MAPJ", b"PALD",
    b"PALA", b"SOIL", b"AREA", b"POSD", b"MOBJ", b"MCHD", b"MCDA", b"NSTX", b"MTXN",
]
CHUNK_DESC = {
    b"MAPD": "Map root/envelope",
    b"MSEA": "Season tag (u32: 0 spring/none, 1 summer, 2 autumn, 3 winter, 4 house/barn/system "
            "rooms) -- no runtime reader found",
    b"MGRP": "Map group bitfield (u32: bits 0-3 fixed season, bit 4 no weather, bits 5-25 one-hot "
            "area group -> BGM track / minimap) -- REQUIRED, the loader crashes without it",
    b"MLIG": "Tile tint colours day/evening/night (3 x u32 0x00BBGGRR; 0 = engine default)",
    b"IMGD": "Image data (unused)", b"ATTR": "Tile attribute grid (w,h,cells[])",
    b"MAPJ": "Warp zone, ONE per chunk (9 i32: disable-flag, zone x/y/w/h, dest map, arrival "
            "x/y, arrival facing deg)",
    b"PALD": "Palette data (512 B each, up to 6) -- all zero, no runtime reader found",
    b"PALA": "Palette alt (unused)", b"SOIL": "Soil (unused)",
    b"AREA": "Area (unused)", b"POSD": "Position data (unused)",
    b"MOBJ": "Placed entity, ONE per chunk (16 i32; types 9-19 are load-time map parameters)",
    b"MCHD": "(unused)", b"MCDA": "(unused)", b"NSTX": "(unused)",
    b"MTXN": "Display-layer marker: the loader spawns one map_disp layer per MTXN chunk (1 = ground "
            "only, 2 = ground + overlay); the u32 value is never read",
}

# Map_LoadById's per-tag pointer arrays in the map task work buffer (MapTaskWorkBuf_t):
# 10 MAPJ slots (+152), 6 PALD (+232, the only bounds-checked one), 40 MOBJ (+280),
# 6 MTXN (+600). Only PALD is bounds-checked; the others overflow into the next array.
# MTXN is capped at 2 although its array holds 6: each chunk j also spawns a display layer
# stored at work +88 + 8*j, and only +88 (ground) / +96 (overlay) are layer slots -- a 3rd
# chunk overwrites the pointers at +104..+128 (validate() reports it).
ENGINE_MAX_CHUNKS = {b"MAPJ": 10, b"PALD": 6, b"MOBJ": 40, b"MTXN": 2}
# MAPJ disable flags are scene-flag ids in GameFlags zone 2 (Widget_UpdateBit20FromGameFlag
# RF4S.exe+0x140280 tests bit zone2_base + id of a 2560-bit zone).
MAPJ_FLAG_COUNT = 2560
# Sharance Maze floors: an arrival x/y near an edge is a direction code for the maze walk
# (Scene_FinalizeMajorTransition RF4S.exe+0x1407E0), not a spot.
MAZE_MAP_IDS = range(442, 454)
# ATTR grids under these tile sizes get the auto-centred, zoomed-in camera
# (Camera_SetBoundsForMap RF4S.exe+0x141700: under 416 x 256 sub-units), except maps 148 / 348.
SMALL_MAP_TILES = (52, 32)
# Tags with a single pointer slot in Map_LoadById's switch (a repeat overwrites it, so
# the LAST chunk of the tag is the one the game uses).
SINGLE_SLOT_TAGS = (b"MSEA", b"MGRP", b"MLIG", b"ATTR")
# Chunk types whose switch case assigns no slot and leaves the previous one in place
# (IMGD always; PALD once 6 are stored). Cases 0 and 8..15 (MAPD, PALA..NSTX except
# MOBJ) clear the slot pointer instead, so they are harmless.
_NULL_SLOT_TAGS = (b"MAPD", b"PALA", b"SOIL", b"AREA", b"POSD", b"MCHD", b"MCDA", b"NSTX")
# Highest type_id with a map_obj sprite: archive 17542 + 393 = 17935 is the last
# rom:/map_obj entry (17936 starts the monster icons).
MAX_MAP_OBJ_TYPE_ID = 393
# MAPJ record field names, in on-disk order (see module docstring).
MAPJ_FIELDS = ("disable_flag", "zone_x", "zone_y", "zone_w", "zone_h",
               "dest_map", "dest_x", "dest_y", "facing_deg")
# MLIG tint slots (Map_PostLoad / Map_PaletteReload) and the engine defaults used
# when a slot's low 24 bits are zero. The night default is (181,214,214) on maps
# whose g_mapTypeAttribTable entry has bit 0x10 (indoor rooms,
# caves and most dungeons; see mlig_defaults).
MLIG_SLOTS = ("day", "evening", "night")
MLIG_DEFAULTS = ((255, 255, 255), (247, 214, 197), (148, 214, 247))
# MGRP bit meanings (Map_LoadById, WeatherTask_Tick, Scene_ApplyContextualBGM,
# Minimap_BuildForMap). bits 5..25 are the one-hot area group; bits 26..31 count only when
# 5..25 are all clear (zones 21..26, past the end of the area tables -- see areagroup).
MGRP_SEASON_BITS = {0x1: "spring", 0x2: "summer", 0x4: "autumn", 0x8: "winter"}
MGRP_NO_WEATHER = 0x10
MGRP_GROUP_NAMES = {
    5: "Selphia town", 6: "interior rooms", 7: "farm", 8: "fields / outskirts",
    9: "DUNG_A", 10: "DUNG_B", 11: "DUNG_C", 12: "DUNG_D", 13: "DUNG_E", 14: "DUNG_F",
    15: "DUNG_G", 16: "DUNG_H", 17: "DUNG_I", 18: "DUNG_J", 19: "DUNG_K", 20: "DUNG_L",
    21: "DUNG_M", 22: "farm-house rooms", 23: "farm-house / barn rooms", 25: "DUNG_O / DUNG_P",
}


def mlig_defaults(map_id=None):
    """The three engine-default tints for a map id (MLIG_DEFAULTS, with the night one from
    mapres.night_default: 181,214,214 on maps whose g_mapTypeAttribTable entry has bit 0x10)."""
    if map_id is None:
        return MLIG_DEFAULTS
    from . import mapres
    return MLIG_DEFAULTS[:2] + (mapres.night_default(map_id),)


def mlig_decode(value: int):
    """Tint dword -> (r, g, b), or None when the low 24 bits are zero (= engine default).
    Byte order is R, G, B from the low byte up; the top byte is ignored by the game."""
    v = value & 0xFFFFFF
    if v == 0:
        return None
    return (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)


def mlig_encode(rgb) -> int:
    """(r, g, b) -> tint dword (top byte 0xFF like the shipped files); None -> 0xFF000000
    which the game treats as "use the default"."""
    if rgb is None:
        return 0xFF000000
    r, g, b = (int(x) & 0xFF for x in rgb)
    return 0xFF000000 | (b << 16) | (g << 8) | r


def mgrp_notes(value: int) -> str:
    """Human-readable decode of an MGRP dword."""
    v = value & 0xFFFFFFFF
    parts = []
    seasons = [n for m, n in MGRP_SEASON_BITS.items() if v & m]
    parts.append("season " + "+".join(seasons) if seasons else "season: calendar")
    if v & MGRP_NO_WEATHER:
        parts.append("no weather")
    groups = [b for b in range(5, 32) if v >> b & 1]
    for b in groups:
        parts.append(f"group bit {b} ({MGRP_GROUP_NAMES.get(b, 'unnamed')})")
    if not groups:
        parts.append("no group bit (zone 0, as Selphia town)")
    elif groups[0] >= 26:
        parts.append(f"WARNING: only bits 26-31, so the game uses zone {groups[0] - 5} "
                     f"(past the area tables: no area music)")
    elif len(groups) > 1:
        parts.append("WARNING: more than one group bit (the game uses the lowest)")
    return ", ".join(parts)


# The base BGM of each area group (zone), before Scene_ApplyContextualBGM's per-room / season /
# night / festival rules: g_baseMapBgmByFlagBit RF4S.exe+0x4D5710, 21 u32 sound ids indexed by
# the zone -- shipped in refdata/rf4s_exe_tables.json (chestloot.area_bgm).


def mgrp_bgm(zone):
    """Sound label of the base BGM the game plays in area group `zone` ('SEQ_DGN_B.ogg'),
    from the table shipped in refdata/rf4s_exe_tables.json; None when it is not there."""
    try:
        from . import chestloot, soundtable
        sid = chestloot.area_bgm(zone)
    except Exception:
        return None
    return None if sid is None else (soundtable.sound_label(sid) or f"sound 0x{sid:X}")


def mgrp_explain(value) -> list[str]:
    """What the game does with each part of an MGRP dword, one line per part (verified in the
    exe 2026-09-26: Map_LoadById stores the raw value as the map task's work[16] and the low
    nibble as work[15]; its readers are below)."""
    from . import chestloot
    v = value & 0xFFFFFFFF
    out = []
    seasons = [n for m, n in MGRP_SEASON_BITS.items() if v & m]
    if seasons:
        out.append("bits 0-3, fixed season: " + "+".join(seasons) + " -- the map's ambience "
                   "and BGM variant ignore the calendar (work[15] = the lowest set bit)")
    else:
        out.append("bits 0-3 clear: the season follows the calendar")
    if v & 0x4:
        out.append("bit 2 (autumn) also switches the BGM stream to target mode 2 instead of 1 "
                   "(Scene_ApplyContextualBGM -> BGM_SetTargetMode; what mode 2 changes is not "
                   "traced)")
    if v & MGRP_NO_WEATHER:
        out.append("bit 4, no weather: no rain / snow particles (WeatherTask_Tick); the sound "
                   "task sets its indoor flag from it too (SndTask_Tick)")
    zone = chestloot.zone_of_mgrp(v)
    groups = [b for b in range(5, 26) if v >> b & 1]
    if groups:
        b = groups[0]
        out.append(f"area group: bit {b} ({MGRP_GROUP_NAMES.get(b, 'unnamed')}) = zone {zone}")
    elif zone >= 21:
        # (MGRP & ~0x1F) >> 5, lowest set bit below 26, else 26 (Minimap_BuildForMap
        # RF4S.exe+0x13B3F0, Scene_ApplyContextualBGM RF4S.exe+0x19AFB0)
        out.append(f"no area-group bit 5-25, so bit {zone + 5} counts: zone {zone} -- past the "
                   f"end of the area tables")
    else:
        out.append("no area-group bit: zone 0 (the Selphia town group)")
    bgm = mgrp_bgm(zone)
    if bgm:
        out.append(f"  base BGM {bgm} (then per-room, season, night and festival rules)")
    elif zone >= 21:
        from . import exesidecars
        sid = exesidecars.area_bgm_overrun(zone)
        out.append(f"  no area music: the game reads sound id 0x{(sid or 0):X} past the "
                   f"21-entry BGM table")
    pools = chestloot.crate_pools(zone)
    out.append("  crates roll the " + " / ".join(
        f"{p['label']} ({p['share']:.0%})" if p["share"] < 1 else p["label"] for p in pools) + " pool")
    rows = {21: " (the Cluck-Cluck Nest row: the spawner loads an unrelated archive)",
            22: " (the Demon's Den row: the spawner loads an unrelated archive)"}
    out.append(f"  monster gates read zone {zone}'s entry of the encounter-archive table"
               + rows.get(zone, " (none there)" if zone >= 23 else "")
               + "; the minimap uses the group too")
    extra = groups[1:]
    if extra:
        if zone == 1:
            sub = next((i for i in range(10) if v >> (22 + i) & 1), None)
            out.append(f"bits {', '.join(map(str, extra))} next to the group: with group bit 6 "
                       f"the minimap takes the room sub-group from the lowest of bits 22+ "
                       f"({'bit %d = sub-group %d' % (22 + sub, sub) if sub is not None else 'none'})")
        else:
            out.append(f"bits {', '.join(map(str, extra))} are also set; the game only uses the "
                       "lowest group bit")
    if v >> 26 and groups:
        out.append(f"bits 26-31 (0x{v & 0xFC000000:X}): ignored -- they count only when bits "
                   f"5-25 are all clear")
    return out


_SEASON_RE = re.compile(r"_(SPRING|SUMMER|AUTUMN|FALL|WINTER)$", re.I)   # a seasonal copy's suffix


def camera_note(w, h):
    """None for a grid the camera scrolls over normally, else what Camera_SetBoundsForMap
    (RF4S.exe+0x141700) does instead: it clamps the camera centre to 216..8W-216 x
    136..8H-136 sub-units, and a grid under 52 tiles wide or 32 tall is centred on that axis
    and drawn zoomed in (maps 148 and 348 have their own settings)."""
    small = [a for a, v, lim in (("wide", w, SMALL_MAP_TILES[0]), ("tall", h, SMALL_MAP_TILES[1]))
             if v < lim]
    if not small:
        return None
    return (f"the game centres the camera and zooms in on this map (it is under "
            f"{' / '.join(f'{SMALL_MAP_TILES[i]} tiles {a}' for i, a in ((0, 'wide'), (1, 'tall')) if a in small)})")


class Rf4mError(Exception):
    pass


class Chunk:
    __slots__ = ("tag", "payload")

    def __init__(self, tag: bytes, payload: bytes):
        self.tag = tag
        self.payload = payload

    def __repr__(self):
        return f"<Chunk {self.tag.decode('latin1')} {len(self.payload)}B>"


class Rf4mMap:
    """A parsed .rf4m, as an ordered list of chunks."""

    def __init__(self, chunks: list[Chunk]):
        # Guard the footgun: Rf4mMap(raw_bytes) would silently store bytes as `chunks` (broken,
        # no error) instead of parsing. Point the caller at the real parsers.
        if isinstance(chunks, (bytes, bytearray, str)):
            raise Rf4mError("Rf4mMap() takes a list of Chunk objects, not raw map bytes -- "
                            "use Rf4mMap.parse(data) or Rf4mMap.load(path).")
        self.chunks = chunks
        # From parse(): the file's MAPD size word and its real length. The game walks
        # chunks only up to file + size word, so a mismatch hides (or invents) chunks;
        # build() always writes the right word. None for maps built in memory.
        self.declared_size = None
        self.file_size = None

    @classmethod
    def parse(cls, data: bytes) -> "Rf4mMap":
        if data[:4] != MAGIC:
            raise Rf4mError(f"not an .rf4m (magic={data[:4]!r})")
        chunks = []
        pos = 8
        n = len(data)
        while pos + 8 <= n:
            tag = data[pos:pos + 4]
            size = struct.unpack_from("<I", data, pos + 4)[0]
            body = data[pos + 8:pos + 8 + size]
            if len(body) != size:
                raise Rf4mError(f"chunk {tag!r} at {pos:#x} truncated "
                               f"(want {size}, have {len(body)})")
            chunks.append(Chunk(tag, body))
            pos += 8 + size
        m = cls(chunks)
        m.declared_size = struct.unpack_from("<i", data, 4)[0] if n >= 8 else None
        m.file_size = n
        return m

    @classmethod
    def load(cls, path) -> "Rf4mMap":
        return cls.parse(pathlib.Path(path).read_bytes())

    # ---- queries --------------------------------------------------------- #
    def find(self, tag) -> list[Chunk]:
        tag = tag if isinstance(tag, bytes) else tag.encode("ascii")
        return [c for c in self.chunks if c.tag == tag]

    def live_chunk(self, tag) -> Chunk | None:
        """The chunk of `tag` the game actually keeps: the LAST one. Map_LoadById stores a
        single pointer for MSEA/MGRP/MLIG/ATTR and every repeat overwrites it (the
        accessors used to read/write the first one, i.e. a chunk the game ignores)."""
        c = self.find(tag)
        return c[-1] if c else None

    def attr_grid(self):
        """Return (width, height, list[cells]) from the live ATTR chunk, or None when the
        map has no ATTR chunk or it is malformed (shorter than its 8-byte header or than
        the w*h cells the header announces). validate() reports the malformed case; it
        used to crash here instead, on exactly the maps it is meant to diagnose."""
        a = self.live_chunk(b"ATTR")
        if a is None:
            return None
        body = a.payload
        if len(body) < 8:
            return None
        w, h = struct.unpack_from("<II", body, 0)
        if len(body) < 8 + 4 * w * h:
            return None
        cells = list(struct.unpack_from(f"<{w * h}I", body, 8))
        return w, h, cells

    def set_attr_grid(self, width: int, height: int, cells: list[int]):
        if len(cells) != width * height:
            raise Rf4mError(f"cells has {len(cells)}, expected {width*height}")
        body = struct.pack("<II", width, height) + struct.pack(f"<{width*height}I", *cells)
        a = self.live_chunk(b"ATTR")
        if a is not None:
            a.payload = body
        else:
            self.chunks.append(Chunk(b"ATTR", body))

    def records(self, tag, stride: int) -> list[tuple]:
        """Parse every chunk of `tag` as fixed-size i32 records, concatenated.

        Maps store many single-record chunks (e.g. 37 separate MOBJ chunks, one
        64-byte object each), so this aggregates across all chunks of the tag.
        """
        ints_per = stride // 4
        out = []
        for c in self.find(tag):
            body = c.payload
            for i in range(0, len(body) - stride + 1, stride):
                out.append(struct.unpack_from(f"<{ints_per}i", body, i))
        return out

    def mobj_records(self):
        return self.records(b"MOBJ", 64)

    def mapj_records(self):
        return self.records(b"MAPJ", 36)

    def set_record(self, tag, index: int, values, stride: int):
        """Overwrite the `index`-th fixed-size record of `tag` (across all chunks of
        that tag) with `values` (stride//4 signed int32s). Mutates the chunk in
        place; call build()/save() to persist."""
        tag = tag if isinstance(tag, bytes) else tag.encode("ascii")
        ints_per = stride // 4
        vals = [int(v) for v in values]
        if len(vals) != ints_per:
            raise Rf4mError(f"expected {ints_per} ints, got {len(vals)}")
        seen = 0
        for c in self.chunks:
            if c.tag != tag:
                continue
            n = len(c.payload) // stride
            if index < seen + n:
                local = index - seen
                buf = bytearray(c.payload)
                try:
                    struct.pack_into(f"<{ints_per}i", buf, local * stride, *vals)
                except struct.error as e:
                    raise Rf4mError(f"value out of int32 range: {e}")
                c.payload = bytes(buf)
                return
            seen += n
        raise Rf4mError(f"{tag.decode('latin1')} record {index} out of range (have {seen})")

    def set_mobj_record(self, index: int, values):
        """Overwrite MOBJ record `index` with 16 signed int32 field values."""
        self.set_record(b"MOBJ", index, values, 64)

    def add_record(self, tag, values, stride: int) -> int:
        """Append a new one-record chunk of `tag` (stride bytes = stride//4 i32 fields)
        after the last existing chunk of that tag. Returns the new record index."""
        tag = tag if isinstance(tag, bytes) else tag.encode("ascii")
        vals = [int(v) for v in values]
        if len(vals) != stride // 4:
            raise Rf4mError(f"{tag.decode('latin1')} record needs {stride//4} ints, got {len(vals)}")
        payload = struct.pack(f"<{stride//4}i", *vals)
        # Count RECORDS (not chunks) of this tag: the new single-record chunk is inserted
        # after the last existing chunk of `tag`, so its record index = total pre-existing
        # records of `tag`. (Equals chunk count only when every chunk holds one record.)
        last, rec_before = -1, 0
        for i, c in enumerate(self.chunks):
            if c.tag == tag:
                last = i
                rec_before += len(c.payload) // stride
        self.chunks.insert(last + 1 if last >= 0 else len(self.chunks), Chunk(tag, payload))
        return rec_before

    def delete_record(self, tag, index: int, stride: int):
        """Remove the `index`-th fixed-size record of `tag`, counting records across all
        chunks of that tag (matching records()/set_record()/add_record()). If the record's
        chunk holds only that record the chunk is dropped; otherwise the record is spliced
        out and the chunk shrinks. (Previously this counted whole chunks, so on any
        multi-record chunk the index space diverged from the other record methods.)"""
        tag = tag if isinstance(tag, bytes) else tag.encode("ascii")
        seen = 0
        for i, c in enumerate(self.chunks):
            if c.tag != tag:
                continue
            n = len(c.payload) // stride
            if index < seen + n:
                local = index - seen
                buf = c.payload[:local * stride] + c.payload[(local + 1) * stride:]
                if buf:
                    c.payload = buf
                else:
                    del self.chunks[i]
                return
            seen += n
        raise Rf4mError(f"{tag.decode('latin1')} record {index} out of range (have {seen})")

    def add_mobj_record(self, values) -> int:
        return self.add_record(b"MOBJ", values, 64)

    def delete_mobj_record(self, index: int):
        self.delete_record(b"MOBJ", index, 64)

    def add_mapj_record(self, values) -> int:
        """Append a new MAPJ warp record (9 i32, MAPJ_FIELDS: disable flag (-1 = none);
        zone x,y,w,h in sub-units; dest_map, dest_x, dest_y; arrival facing in degrees,
        0 = keep the current facing)."""
        return self.add_record(b"MAPJ", values, 36)

    def delete_mapj_record(self, index: int):
        self.delete_record(b"MAPJ", index, 36)

    def set_mapj_record(self, index: int, values):
        self.set_record(b"MAPJ", index, values, 36)

    # ---- header / scalar chunks ----------------------------------------- #
    def get_ints(self, tag, count=None, signed=True) -> list[int]:
        """Read the live (= last, see live_chunk) chunk of `tag` as a list of int32 (all of
        them, or `count`)."""
        c = self.live_chunk(tag)
        if c is None:
            return []
        body = c.payload
        n = (len(body) // 4) if count is None else count
        if n * 4 > len(body):
            raise Rf4mError(f"{tag!r} chunk holds {len(body)//4} int32(s); requested {n}")
        code = "i" if signed else "I"
        return list(struct.unpack_from(f"<{n}{code}", body, 0))

    def set_ints(self, tag, values, signed=True):
        """Overwrite the live (= last) chunk of `tag` with int32 `values` (creates the
        chunk if absent). The chunk is resized to fit the values."""
        tag = tag if isinstance(tag, bytes) else tag.encode("ascii")
        code = "i" if signed else "I"
        payload = struct.pack(f"<{len(values)}{code}", *[int(v) for v in values])
        c = self.live_chunk(tag)
        if c is not None:
            c.payload = payload
        else:
            self.chunks.append(Chunk(tag, payload))

    # ---- raw chunk ops (edit ANY chunk) ---------------------------------- #
    def set_chunk_payload(self, stream_index: int, payload: bytes):
        self.chunks[stream_index].payload = bytes(payload)

    def add_chunk(self, tag, payload: bytes, at: int | None = None):
        if not isinstance(tag, bytes):
            if not str(tag).isascii():
                raise Rf4mError(f"chunk tag {tag!r} must be ASCII")
            tag = str(tag).encode("ascii")
        if len(tag) != 4:
            raise Rf4mError("chunk tag must be 4 bytes")
        ch = Chunk(tag, bytes(payload))
        self.chunks.insert(len(self.chunks) if at is None else at, ch)

    def delete_chunk(self, stream_index: int):
        del self.chunks[stream_index]

    def set_attr_cell(self, x: int, y: int, value: int):
        """Set one ATTR collision/attribute cell (row-major) to `value`."""
        a = self.live_chunk(b"ATTR")
        if a is None:
            raise Rf4mError("no ATTR chunk")
        body = bytearray(a.payload)
        w, h = struct.unpack_from("<II", body, 0)
        if not (0 <= x < w and 0 <= y < h):
            raise Rf4mError(f"cell ({x},{y}) out of {w}x{h}")
        struct.pack_into("<I", body, 8 + (y * w + x) * 4, value & 0xFFFFFFFF)
        a.payload = bytes(body)

    # ---- resizing the tile grid ----------------------------------------- #
    def resize_attr_grid(self, new_w: int, new_h: int, *, fill: int = 0x2,
                         origin=(0, 0), shift_entities: bool = True,
                         ground_reader=None, map_name=None, dry_run: bool = False) -> dict:
        """Grow or shrink the ATTR grid AND report every derived artefact it invalidates.

        Resizing ATTR is not a local edit: the ATTR grid is the only thing the engine
        sizes the map from, so it silently redefines the ground-atlas tile grid, the
        map's world extent, and whether the placed entities and warp zones are still
        inside it. `validate()` alone will not catch most of that, which is why this
        returns a report rather than just doing the edit.

        `origin` = (ox, oy): where the OLD grid's (0,0) lands in the new one, so a
        positive origin pads the left/top and pushes the content right/down. Cells
        outside the new grid are dropped; cells with no old counterpart get `fill`,
        which defaults to `0x2` (the explicit block bit) so that padding is solid wall
        rather than a walkable void -- pass `fill=0` for plain empty cells.

        With `shift_entities` (default), MOBJ positions and MAPJ zone origins move with
        the content by `origin * 8` sub-units, so nothing drifts relative to the terrain.
        MOBJ parameter records (types 9..19, which carry no position) are left alone; a
        record at (0,0) is a real position and moves like any other. A knock-back vent's
        (type 52) walk-to target f8/f9 moves with it. MAPJ *arrival* coordinates are NOT
        touched: they are positions in the destination map.

        `ground_reader` + `map_name` (see `validate()`) let the report name the exact
        tiles that must be authored. `dry_run=True` computes the whole report and
        changes nothing.

        Returns a dict; `report["todo"]` is the ordered, human-readable derived-artefact
        list and `report["findings"]` is what `validate()` would say at the new size.
        """
        from . import mapground
        grid = self.attr_grid()
        if grid is None:
            raise Rf4mError("no ATTR chunk to resize")
        new_w, new_h = int(new_w), int(new_h)
        if new_w <= 0 or new_h <= 0:
            raise Rf4mError(f"new ATTR grid {new_w}x{new_h} has a zero/negative dimension")
        ox, oy = int(origin[0]), int(origin[1])
        w, h, cells = grid
        fill = int(fill) & 0xFFFFFFFF

        # --- the cells ---------------------------------------------------- #
        out = [fill] * (new_w * new_h)
        kept = dropped = dropped_set = 0
        for y in range(h):
            ny = y + oy
            for x in range(w):
                nx, v = x + ox, cells[y * w + x]
                if 0 <= nx < new_w and 0 <= ny < new_h:
                    out[ny * new_w + nx] = v
                    kept += 1
                else:
                    dropped += 1
                    dropped_set += 1 if v else 0
        added = new_w * new_h - kept

        # --- what the resize does to the ground atlas ---------------------- #
        old_grid = mapground.grid_dims(w, h)
        new_grid = mapground.grid_dims(new_w, new_h)
        reindexed = old_grid[0] != new_grid[0]
        audit = []
        if ground_reader is not None and map_name:
            audit = mapground.atlas_audit(ground_reader, map_name, new_w, new_h)

        # --- entities: what moves, and what ends up off the grid ----------- #
        moved_mobj, moved_mapj, out_mobj, out_mapj = [], [], [], []
        sx, sy = ox * 8, oy * 8
        for i, rec in enumerate(self.mobj_records()):
            tid = rec[0] & 0xFFFF
            if mobj_types.is_positionless(tid):
                continue                       # parameter record: no position
            px, py = rec[14], rec[15]
            if shift_entities and (sx or sy):
                px, py = px + sx, py + sy
                moved_mobj.append(i)
                if not dry_run:
                    vals = list(rec)
                    vals[14], vals[15] = px, py
                    if tid == 52:              # the knock-back target is a spot on this map
                        vals[8], vals[9] = vals[8] + sx, vals[9] + sy
                    self.set_mobj_record(i, vals)
            tx, ty = px >> 3, py >> 3
            if not (0 <= tx < new_w and 0 <= ty < new_h):
                out_mobj.append({"index": i, "type_id": tid,
                                 "name": mobj_types.mobj_display_name(tid) or f"type {tid}",
                                 "tile": (tx, ty)})
        for i, rec in enumerate(self.mapj_records()):
            zx, zy = rec[1], rec[2]
            if shift_entities and (sx or sy):
                zx, zy = zx + sx, zy + sy
                moved_mapj.append(i)
                if not dry_run:
                    vals = list(rec)
                    vals[1], vals[2] = zx, zy
                    self.set_mapj_record(i, vals)
            x0, y0 = zx >> 3, zy >> 3
            x1, y1 = (zx + rec[3]) >> 3, (zy + rec[4]) >> 3
            if not (0 <= x0 < new_w and 0 <= y0 < new_h) or x1 > new_w or y1 > new_h:
                out_mapj.append({"index": i, "zone_tiles": (x0, y0, x1, y1),
                                 "dest_map": rec[5]})

        if not dry_run:
            self.set_attr_grid(new_w, new_h, out)

        # --- the derived-artefact list ------------------------------------- #
        errs, warns = self._atlas_findings(new_w, new_h, ground_reader, map_name)
        PX = mapground.PX_PER_ATTR_TILE
        todo = []
        if (new_w, new_h) != (w, h):
            todo.append(f"map extent changes from {w * PX}x{h * PX} to "
                        f"{new_w * PX}x{new_h * PX} px (ATTR x 24)")
        if (new_w, new_h) != (w, h):
            for i, rec in enumerate(self.mobj_records()):
                if rec[0] & 0xFFFF == 10 and w and h:     # parallax: ratio = f8 / (8 W), f9 / (8 H)
                    todo.append(f"parallax record #{i}: its scroll ratio changes "
                                f"({rec[8] / (8 * w):.3f} -> {rec[8] / (8 * new_w):.3f} across, "
                                f"{rec[9] / (8 * h):.3f} -> {rec[9] / (8 * new_h):.3f} down); to keep "
                                f"it set f8 = {round(rec[8] * new_w / w)}, f9 = {round(rec[9] * new_h / h)}")
        cam_old, cam_new = camera_note(w, h), camera_note(new_w, new_h)
        if (cam_old is None) != (cam_new is None):
            todo.append("camera: " + (f"the grid drops under {SMALL_MAP_TILES[0]} x "
                                      f"{SMALL_MAP_TILES[1]} tiles, so " + cam_new if cam_new else
                                      f"the grid is no longer under {SMALL_MAP_TILES[0]} x "
                                      f"{SMALL_MAP_TILES[1]} tiles, so the camera now scrolls "
                                      f"normally instead of being centred and zoomed in"))
        if reindexed:
            todo.append(
                f"GROUND ATLAS MUST BE RE-LAID-OUT: the tile grid goes {old_grid[0]}x"
                f"{old_grid[1]} -> {new_grid[0]}x{new_grid[1]}, and because tiles are indexed "
                f"row-major (tile i at column i % cols) a change of COLUMN count moves every "
                f"existing tile to a different screen cell -- the atlas cannot just be extended. "
                f"This has to be done by hand: export the layer before the resize (`map "
                f"ground-export`), then author the new {new_grid[0]}x{new_grid[1]} tiles yourself "
                f"(ground-import only re-encodes the tiles the map already has, at their sizes)")
        elif old_grid != new_grid:
            todo.append(f"ground tile grid goes {old_grid[0]}x{old_grid[1]} -> "
                        f"{new_grid[0]}x{new_grid[1]} ({old_grid[0] * old_grid[1]} -> "
                        f"{new_grid[0] * new_grid[1]} tiles); the column count is unchanged, so "
                        f"existing tile indices keep their screen cell")
        for a in audit:
            if a["missing"]:
                m = a["missing"]
                todo.append(f"layer {a['layer']}: author {len(m)} new tile(s) "
                            f"{mapground.tile_name(a['set'], a['layer'], m[0])} .. "
                            f"{mapground.tile_name(a['set'], a['layer'], m[-1])} "
                            f"(otherwise those cells load the next set's archive ids)")
            if a["short_x"] or a["short_y"]:
                todo.append(f"layer {a['layer']}: the last column/row tiles are sized for the old "
                            f"extent and fall {a['short_x']} px short on X, {a['short_y']} px on Y; "
                            f"author them again at the new size (ground-import keeps tile sizes)")
        if out_mobj:
            todo.append(f"{len(out_mobj)} MOBJ record(s) now sit outside the grid: "
                        + ", ".join(f"#{d['index']} {d['name']} at {d['tile']}"
                                    for d in out_mobj[:6])
                        + (" ..." if len(out_mobj) > 6 else ""))
        if out_mapj:
            todo.append(f"{len(out_mapj)} warp zone(s) now sit outside the grid: "
                        + ", ".join(f"#{d['index']} -> map {d['dest_map']}" for d in out_mapj[:6])
                        + (" ..." if len(out_mapj) > 6 else ""))
        if dropped_set:
            todo.append(f"{dropped_set} non-zero ATTR cell(s) were cropped away (authored "
                        f"collision/FX lost -- re-check the new edges)")
        # the HUD minimap (rf3MapMiniPos): origin = picture px of the world origin, scale =
        # picture px per sub-unit (Q12), reveal = a picture-px rectangle. A grown map keeps its
        # placement but the picture paints only the old area; shifted content needs the
        # origin moved back by scale * shift so the painting stays on it.
        mm = None
        if map_name:
            try:
                from . import map_names as _mn, minimap as _mm
                mid = _mn.map_id_for_file(_SEASON_RE.sub("", map_name)) if map_name else None
                mm = _mm.raw_record(mid) if mid is not None else None
            except Exception:
                mm = None
        if (sx or sy) and mm is not None and (mm[7] or mm[8]):
            dx, dy = (mm[7] * sx) >> 12, (mm[8] * sy) >> 12
            todo.append(f"minimap: the content moved by ({sx}, {sy}) sub-units, so this map's "
                        f"rf3MapMiniPos origin must move by ({-dx}, {-dy}) drawn px -- from "
                        f"({mm[1]}, {mm[2]}) to ({mm[1] - dx}, {mm[2] - dy}) -- or the minimap "
                        f"picture and the player's marker drift apart (see rf4s_modkit.minimap)")
        elif sx or sy:
            todo.append("minimap: the content moved, so this map's rf3MapMiniPos origin must move "
                        "back by scale x shift (see rf4s_modkit.minimap)")
        if (new_w > w or new_h > h) and (mm is None or mm[7] or mm[8]):
            todo.append("minimap: the picture only paints the old area -- the new space shows as "
                        "unpainted on the HUD minimap until the picture is redrawn")
        if sx or sy:
            todo.append("other maps that warp INTO this one carry the arrival position in their "
                        "own MAPJ records (fields 6/7), and event scripts place NPCs / the player "
                        "by tile: neither is in this file -- check them by hand, the content moved "
                        f"by ({ox}, {oy}) tiles")
            if map_name:
                fam = mapground._SEASON_SUFFIX.sub("", map_name)
                sibs = [n for n in mapground._texmap()
                        if n != map_name and mapground._SEASON_SUFFIX.sub("", n) == fam]
                if sibs:
                    todo.append(f"seasonal sibling map(s) {', '.join(sorted(sibs))} carry their own "
                                f"ATTR and share this ground atlas; resize them the same way or "
                                f"the seasons will disagree")
        return {
            "applied": not dry_run,
            "old_size": (w, h), "new_size": (new_w, new_h), "origin": (ox, oy),
            "extent_px": {"old": (w * PX, h * PX), "new": (new_w * PX, new_h * PX)},
            "camera": {"old": cam_old, "new": cam_new},
            "cells": {"kept": kept, "dropped": dropped, "added": added,
                      "dropped_nonzero": dropped_set, "fill": fill},
            "atlas": {"old_grid": old_grid, "new_grid": new_grid,
                      "old_need": old_grid[0] * old_grid[1],
                      "new_need": new_grid[0] * new_grid[1],
                      "reindexed": reindexed, "layers": audit},
            "moved": {"mobj": moved_mobj, "mapj": moved_mapj},
            "outside": {"mobj": out_mobj, "mapj": out_mapj},
            "findings": [f"ERROR: {e}" for e in errs] + [f"WARN: {x}" for x in warns],
            "todo": todo,
        }

    # MOBJ record field semantics + the type_id -> spawn category dispatch, verified
    # against Map_SpawnAllEntities (RF4S.exe+0x13FE70) -> Map_SpawnEntityByCategoryAndIdx
    # (+0x13FAB0) -> MapObj_SetupActorByTypeId (+0x147240):
    #   field[0]  = type_id (dispatch category, below)
    #   field[6]  = scale (4096 = 1.0 in 12.12 fixed point)
    #   field[7]  = orientation (65536 = full turn; 0/16384/32768/49152 = quarter turns)
    #   field[14] = X in sub-units (8 per ATTR tile; actor world_x = f14 << 12)
    #   field[15] = Y in sub-units
    #   fields 1-5,8-13 = per-type parameters (meaning depends on the spawn handler)
    # type_id -> spawn class. Verified across all three sprite-loading paths
    # (Map_SpawnEntityByCategoryAndIdx cat 1001 "map_obj_id", Map_SpawnInteractiveObject,
    # MapDecoration_Spawn): EVERY path loads map_obj archive = type_id + 17542. The old
    # "creature" guess for 20..195 was wrong -- that range is the category-1001
    # "map_obj_id" actor path (effects/gimmicks/doors/roads), task id = type_id+1000.
    @staticmethod
    def mobj_category(type_id: int) -> str:
        return mobj_types.mobj_kind(type_id & 0xFFFF)

    def decode_mobj(self) -> list[dict]:
        """Decode every MOBJ record into a structured dict using the verified field
        layout. `category` is the spawn class; `name`/`archive_id` identify the actual
        map_obj sprite the engine loads (archive = type_id + 17542, indexing the
        rom:/map_obj/<NAME>.bntx filename TOC). Triggers (type_id < 20) have no sprite."""
        out = []
        for rec in self.mobj_records():
            tid = rec[0] & 0xFFFF
            out.append({
                "type_id": rec[0],
                "category": mobj_types.mobj_kind(tid),
                "name": mobj_types.mobj_name(tid),          # map_obj sprite name or None
                "archive_id": mobj_types.mobj_archive_id(tid),
                "scale": rec[6] / 4096.0,
                "orientation_deg": (rec[7] % 65536) * 360.0 / 65536.0,
                # pos in SUB-UNITS (8 per ATTR tile): tile = pos>>3. Sprites use the
                # sub-units directly (Map_SpawnInteractiveObject: sprite XY = rec[14]/[15],
                # footprint tile = rec[14]>>3); actors (types 20..195) get the Q12 world
                # position pos << 12 (MapObj_SetupActorByTypeId, RF4S.exe+0x147240).
                "pos_x": rec[14],
                "pos_y": rec[15],
                "params": list(rec),
            })
        return out

    # ---- MAPJ / MLIG / MGRP decoding ------------------------------------ #
    def decode_mapj(self) -> list[dict]:
        """Decode every MAPJ warp record into a dict keyed by MAPJ_FIELDS, plus
        `zone_tiles` (x0, y0, x1, y1), `dest_tile` (x, y) and the raw `params` list.
        Field meanings verified 2026-09-19 against Map_SpawnEntityByCategoryAndIdx
        (category 1000 "m_move_obj": zone box = f1..f4 in sub-units, f0 -> the widget's
        disable flag), Widget_UpdateBit20FromGameFlag (f0 = scene-flag id, -1 = none,
        warp dead while the flag is SET) and Cutscene_StartDeathSequence, the shared
        major-transition entry (f5 = map id, f6/f7 = arrival x/y, f8 = facing in
        degrees, stored x182 as a Q16 angle)."""
        out = []
        for rec in self.mapj_records():
            d = dict(zip(MAPJ_FIELDS, rec))
            d["zone_tiles"] = (rec[1] >> 3, rec[2] >> 3, (rec[1] + rec[3]) >> 3, (rec[2] + rec[4]) >> 3)
            d["dest_tile"] = (rec[6] >> 3, rec[7] >> 3)
            d["params"] = list(rec)
            out.append(d)
        return out

    def mlig_colors(self) -> list:
        """The three MLIG tint colours as [(r,g,b) | None, ...] for day / evening / night
        (None = engine default, see MLIG_DEFAULTS). Missing chunk -> three Nones."""
        vals = self.get_ints("MLIG", signed=False)
        cols = [mlig_decode(v) for v in vals[:3]]
        return cols + [None] * (3 - len(cols))

    def set_mlig_colors(self, colors):
        """Write the MLIG tint triplets from [(r,g,b) | None] x3 (None = default)."""
        cols = list(colors)[:3]
        cols += [None] * (3 - len(cols))
        self.set_ints("MLIG", [mlig_encode(c) for c in cols], signed=False)

    def mgrp(self) -> int | None:
        v = self.get_ints("MGRP", signed=False)
        return v[0] if v else None

    # ---- validation against the loader --------------------------------- #
    def validate(self, known_maps=None, *, ground_reader=None, map_name=None,
                 dest_loader=None) -> list[str]:
        """Check the map against what Map_LoadById and the spawners actually do.

        Returns human-readable lines: `ERROR:` = the game crashes, drops data or shows
        nothing; `WARN:` = loads, but not the way a modder probably expects. Pass the
        set of valid map ids as `known_maps` to also check warp destinations.

        `ground_reader` + `map_name` additionally check the ground-texture ATLAS against
        the ATTR grid (:func:`rf4s_modkit.mapground.atlas_audit`). That check matters
        because the engine derives the tile count from ATTR alone and loads tile `i` as
        archive id `base + i`: a map whose grid outgrew its atlas asks for tiles that
        do not exist and gets the NEXT set's files instead. `ground_reader(filename)
        -> bytes | None` supplies `.texture` files (a loose folder or a bundle);
        `map_name` is the map's name (e.g. `MAP_FIELD_01`), needed because the ground
        set is usually NOT the same-named one. The tile-slot ceiling is checked from
        ATTR alone and needs neither. `map_name` also lets the MTXN count be checked
        against the game's overlay id for the map (rf4s_modkit.mapres).

        `dest_loader(map_id) -> Rf4mMap | None` (optional) supplies warp destinations: each
        warp's arrival is then checked against the destination's grid and warp zones."""
        errs, warns = [], []
        counts = Counter(c.tag for c in self.chunks)
        # 0. the walk bound is the MAPD size word of the file as parsed (build() rewrites
        #    it, so this only fires when validating a file that came off disk)
        if self.declared_size is not None and self.declared_size != self.file_size:
            errs.append(f"MAPD size word is {self.declared_size} but the file is "
                        f"{self.file_size} B: Map_LoadById walks chunks only up to file + "
                        f"size word, so chunks past it are ignored (or garbage past the end "
                        f"is read as chunks). Re-saving through build() fixes the word")
        # 1. the chunk walk stops at the first unknown tag
        for i, c in enumerate(self.chunks):
            if c.tag not in CHUNK_NAMES:
                after = [d.tag.decode("latin1") for d in self.chunks[i + 1:]]
                errs.append(f"chunk #{i} has the unknown tag {c.tag.decode('latin1')!r}: "
                            f"Map_LoadById stops at the first unknown tag, so the "
                            f"{len(after)} chunk(s) after it ({', '.join(after) or 'none'}) "
                            f"are never loaded")
                break
        # 1b. replay the loader's slot assignment: IMGD (and a PALD past the 6th) gets no
        #     slot of its own and re-points whatever slot the previous chunk used; a
        #     repeated single-slot tag replaces the earlier pointer.
        slot_of = None           # (tag, chunk index) whose slot the walk pointer holds
        pald = 0
        seen_single = {}
        for i, c in enumerate(self.chunks):
            if c.tag not in CHUNK_NAMES:
                break
            if c.tag in _NULL_SLOT_TAGS:
                slot_of = ("null", i)
            elif c.tag == b"IMGD" or (c.tag == b"PALD" and pald >= 6):
                what = "an IMGD" if c.tag == b"IMGD" else "a 7th+ PALD"
                if slot_of is None:
                    errs.append(f"chunk #{i}: {what} chunk before any slotted chunk makes "
                                f"Map_LoadById store its payload through an uninitialised "
                                f"pointer (stack garbage -- crash or memory corruption)")
                elif slot_of[0] == b"PALD":
                    warns.append(f"chunk #{i}: {what} chunk gets no slot and replaces the "
                                 f"pointer of PALD chunk #{slot_of[1]} (nothing reads PALD, "
                                 f"so harmless)")
                elif slot_of[0] != "null":
                    errs.append(f"chunk #{i}: {what} chunk gets no slot of its own, so "
                                f"Map_LoadById overwrites the pointer of chunk #{slot_of[1]} "
                                f"({slot_of[0].decode('latin1')}) with this payload -- the "
                                f"game reads this chunk's bytes as that chunk")
            else:
                if c.tag in SINGLE_SLOT_TAGS:
                    if c.tag in seen_single:
                        warns.append(f"chunk #{i}: second {c.tag.decode('latin1')} chunk (first "
                                     f"is #{seen_single[c.tag]}): the loader keeps one pointer, "
                                     f"so the game uses the LAST one (the single-chunk "
                                     f"accessors edit the last one too)")
                    else:
                        seen_single[c.tag] = i
                elif c.tag == b"PALD":
                    pald += 1
                slot_of = (c.tag, i)
        # 2. chunks the loader needs
        if not counts[b"MGRP"]:
            errs.append("no MGRP chunk: Map_LoadById dereferences its pointer unconditionally "
                        "(null-pointer crash on load)")
        elif len(self.live_chunk(b"MGRP").payload) < 4:
            errs.append(f"MGRP chunk is {len(self.live_chunk(b'MGRP').payload)} B; Map_LoadById "
                        f"reads 4 B from it, so the next chunk's header is read as the group bits")
        if counts[b"MLIG"] and len(self.live_chunk(b"MLIG").payload) < 12:
            errs.append(f"MLIG chunk is {len(self.live_chunk(b'MLIG').payload)} B; Map_PostLoad "
                        f"reads three 4-byte tints (12 B), so the next chunk's header is read as "
                        f"tint colours")
        if not counts[b"ATTR"]:
            errs.append("no ATTR chunk: no tile grid (every tile reads as blocked) and no "
                        "ground layer size")
        else:
            body = self.live_chunk(b"ATTR").payload
            if len(body) < 8:
                errs.append("ATTR chunk is shorter than its 8-byte width/height header")
            else:
                w, h = struct.unpack_from("<II", body, 0)
                if len(body) != 8 + 4 * w * h:
                    errs.append(f"ATTR payload is {len(body)} B but a {w}x{h} grid needs "
                                f"{8 + 4 * w * h} B")
                if w == 0 or h == 0:
                    errs.append(f"ATTR grid {w}x{h} has a zero dimension")
        from . import mapres
        own_id = mapres.map_id(map_name) if map_name else None
        ovl = mapres.has_overlay(own_id) if own_id is not None else None
        n_mtxn = counts[b"MTXN"]
        if not n_mtxn:
            errs.append("no MTXN chunk: the loader spawns one display layer per MTXN chunk, "
                        "so the ground textures would never be drawn")
        elif n_mtxn > 2:
            errs.append(f"{n_mtxn} MTXN chunks: the loader spawns a display layer per chunk and "
                        f"stores chunk j's at work +88 + 8*j, but only +88 (ground) and +96 "
                        f"(overlay) are layer slots -- chunks 3+ overwrite the file-buffer, MSEA "
                        f"and MGRP pointers after them and each loads the overlay set again "
                        f"(memory corruption); keep 1 or 2")
        elif n_mtxn == 1 and ovl:
            warns.append("1 MTXN chunk, but the game has an overlay set for this map id "
                         "(g_mapResourceTable +2): the overlay (tree tops, roofs ...) is only "
                         "built by a 2nd MTXN chunk, so it will not be drawn")
        elif n_mtxn == 2 and ovl is False:
            warns.append("2 MTXN chunks, but the game has no overlay set for this map id "
                         "(g_mapResourceTable +2 is 0): the second display layer stays empty")
        if not counts[b"MLIG"]:
            warns.append("no MLIG chunk: Map_PostLoad skips the tint setup, so the day/evening/"
                         "night tints keep whatever the previous map set (0 right after the "
                         "game starts) unless type-12 records set them")
        if not counts[b"MSEA"]:
            warns.append("no MSEA chunk (nothing reads it, but every shipped map has one)")
        # 3. fixed-size pointer arrays in the map task work buffer
        for tag, cap in ENGINE_MAX_CHUNKS.items():
            n = counts[tag]
            if n > cap and tag != b"MTXN":             # MTXN: see section 2
                if tag == b"PALD":
                    warns.append(f"{n} PALD chunks: the engine keeps 6; each extra one "
                                 f"re-points the previous chunk's slot (see the per-chunk "
                                 f"finding)")
                else:
                    errs.append(f"{n} {tag.decode('latin1')} chunks: the loader's pointer array "
                                f"holds {cap} and is not bounds-checked; chunks past it "
                                f"overwrite the next array (memory corruption)")
        # 4. one record per chunk
        for tag, stride in ((b"MOBJ", 64), (b"MAPJ", 36)):
            for i, c in enumerate(self.chunks):
                if c.tag != tag or len(c.payload) == stride:
                    continue
                if len(c.payload) < stride:
                    errs.append(f"chunk #{i} {tag.decode('latin1')} is {len(c.payload)} B; "
                                f"a record needs {stride} B (the game reads past the end)")
                else:
                    warns.append(f"chunk #{i} {tag.decode('latin1')} packs "
                                 f"{len(c.payload) // stride} records; the game reads only "
                                 f"the first (one record per chunk)")
        # 5. placed entities
        grid = self.attr_grid()
        W, H = (grid[0], grid[1]) if grid else (0, 0)
        errs2, warns2 = self._entity_findings(W, H, bool(grid))
        errs += errs2
        warns += warns2
        # 6. warps
        maze = own_id in MAZE_MAP_IDS
        dest_maps = {}

        def dest_map(mid):
            """The destination's .rf4m (this map itself when it warps to its own id)."""
            if mid not in dest_maps:
                if own_id is not None and mid == mapres.base_id(own_id):
                    dest_maps[mid] = self
                else:
                    try:
                        dest_maps[mid] = dest_loader(mid) if dest_loader else None
                    except Exception:  # noqa: BLE001 - an unreadable destination: no check
                        dest_maps[mid] = None
            return dest_maps[mid]

        for i, rec in enumerate(self.mapj_records()):
            zx, zy, zw, zh = rec[1:5]
            dest, ax, ay = rec[5], rec[6], rec[7]
            if zw <= 0 or zh <= 0:
                warns.append(f"warp #{i}: degenerate zone size {zw}x{zh} sub-units")
            if grid and (zx < 0 or zy < 0 or (zx >> 3) >= W or (zy >> 3) >= H):
                warns.append(f"warp #{i}: zone origin tile ({zx >> 3},{zy >> 3}) is outside "
                             f"the {W}x{H} grid")
            if known_maps is not None and dest not in known_maps:
                errs.append(f"warp #{i}: destination map id {dest} is not a known map")
            # Map_LoadById adds the calendar season (0..3) to ANY id below 64 without rounding
            # it down first, so a seasonal (non-base) id loads the wrong file
            if 0 < dest < 64 and dest % 4:
                errs.append(f"warp #{i}: destination {dest} is a seasonal copy; the game adds "
                            f"the calendar season to ids below 64, so it loads map {dest}.."
                            f"{dest + 3} by season (a wrong season, or another map) -- use the "
                            f"base id {dest - dest % 4}; the season follows the calendar")
            # MapTask_Tick only starts the load when id != 0 or both arrival coordinates are set
            if dest == 0 and not (ax and ay):
                errs.append(f"warp #{i}: destination 0 with an arrival coordinate of 0 never "
                            f"loads (MapTask_Tick skips it) and the screen stays faded out")
            elif dest == 0:
                warns.append(f"warp #{i}: destination 0 is MAP_NULL, an empty placeholder map")
            if ax < 0 or ay < 0:
                warns.append(f"warp #{i}: negative arrival position ({ax},{ay})")
            # Cutscene_StartDeathSequence keeps the arrival as 16-bit words and
            # Scene_FinalizeMajorTransition sign-extends x/y (movsx) before << 12
            if ax > 0x7FFF or ay > 0x7FFF:
                errs.append(f"warp #{i}: arrival ({ax},{ay}) does not fit the signed "
                            f"16-bit words the transition stores it in (max 32767 sub-units "
                            f"= tile 4095); the player lands at a wrapped position")
            if not (0 <= dest <= 0xFFFF):
                errs.append(f"warp #{i}: destination map id {dest} is stored as a u16 by "
                            f"the transition and wraps")
            # Widget_SetCollisionBox takes the box corners (-32, -32, w - 32, h - 32) as i16
            for what, v in (("width", zw), ("height", zh)):
                if not (-0x8000 <= v - 32 <= 0x7FFF):
                    warns.append(f"warp #{i}: zone {what} {v} does not fit: Widget_SetCollisionBox "
                                 f"takes the box corners as 16-bit values (max {0x7FFF + 32} "
                                 f"sub-units), so the zone wraps")
            if not (0 <= rec[8] < 360):
                warns.append(f"warp #{i}: arrival facing {rec[8]} is not 0..359 degrees")
            if rec[0] != -1 and not (0 <= rec[0] < MAPJ_FLAG_COUNT):
                errs.append(f"warp #{i}: disable flag {rec[0]} is outside the game's scene flags "
                            f"(0..{MAPJ_FLAG_COUNT - 1}, or -1 = always on): the game tests a bit "
                            f"past the flag zone (another zone's flag or memory after it)")
            # the arrival against the destination map (not on the Sharance Maze floors, where
            # the arrival is a direction code, and only when the destination can be read)
            if maze or not (0 <= dest <= 0xFFFF) or dest == 0:
                continue
            dm = dest_map(mapres.base_id(dest))
            dg = dm.attr_grid() if dm is not None else None
            if dg is None:
                continue
            dw, dh, dcells = dg
            tx, ty = ax >> 3, ay >> 3
            dname = mapres.row(mapres.base_id(dest))
            dname = dname[0] if dname else f"map {dest}"
            if not (0 <= tx < dw and 0 <= ty < dh):
                errs.append(f"warp #{i}: arrival ({ax},{ay}) = tile ({tx},{ty}) is outside "
                            f"{dname}'s {dw}x{dh} grid; outside the grid every tile is a wall, "
                            f"so the player is stuck")
                continue
            if dcells[ty * dw + tx] == 0x2:
                warns.append(f"warp #{i}: arrival tile ({tx},{ty}) in {dname} is a wall (ATTR "
                             f"0x2); the player lands inside it")
            for j, r in enumerate(dm.mapj_records()):
                if r[1] < ax < r[1] + r[3] and r[2] < ay < r[2] + r[4]:
                    warns.append(f"warp #{i}: arrival ({ax},{ay}) lies inside {dname}'s warp #{j} "
                                 f"(to map {r[5]}); the player may be sent on at once")
                    break
        # 7. ground-texture atlas vs the ATTR grid
        if grid:
            errs2, warns2 = self._atlas_findings(W, H, ground_reader, map_name)
            errs += errs2
            warns += warns2
        return [f"ERROR: {e}" for e in errs] + [f"WARN: {w}" for w in warns]

    # the actor types a player has to reach (open, break, pick up, touch, step on): off the
    # grid they can never be used. Other types sit off the grid in shipped maps on purpose
    # (trees / rock walls whose sprite hangs into view, seal-door controllers at x <= 0).
    _REACHED_TYPES = frozenset({24, 25, 35, 42, 44, 45, 46, 52, 53, 58, 63})

    def limit_usage(self) -> list[tuple]:
        """[(key, label, used, cap, over_is_error, what the cap is)] for the game's fixed
        per-map capacities -- what the map editor's limits bar shows. Past a cap the game
        corrupts memory (over_is_error) or misbehaves (see validate())."""
        from . import mobj_params as mp
        tids = [r[0] & 0xFFFF for r in self.mobj_records()]
        n = Counter(c.tag for c in self.chunks)
        return [
            ("mobj", "Objects", n[b"MOBJ"], ENGINE_MAX_CHUNKS[b"MOBJ"], True,
             "Placed objects, map parameters included. The game holds 40; a 41st corrupts memory."),
            ("mapj", "Warps", n[b"MAPJ"], ENGINE_MAX_CHUNKS[b"MAPJ"], True,
             "Warp zones. The game holds 10; an 11th corrupts memory."),
            ("forage", "Forage", sum(1 for t in tids if t <= 8), mp.FORAGE_MAX_SPAWNS, True,
             "Forage spawners (ore rocks, wood, stones, herbs, crops). The game spawns at most 32 "
             "per map."),
            ("doors", "Doors / walls", sum(1 for t in tids if 82 <= t <= 195), mp.DOOR_SLOTS, False,
             "Doors, roads and walls share 4 collision slots: a 5th copies door #0's collision."),
        ]

    def _entity_findings(self, W: int, H: int, has_grid: bool):
        """(errors, warnings) for the MOBJ records (validate() section 5)."""
        from . import mobj_params as mp
        errs, warns = [], []
        recs = self.mobj_records()
        forage = doors = 0
        owners = {}                     # one-shot flag -> [record index]
        for i, rec in enumerate(recs):
            tid = rec[0] & 0xFFFF
            name = mobj_types.mobj_display_name(tid) or f"type {tid}"
            if rec[0] != tid:
                warns.append(f"MOBJ #{i}: type {rec[0]} has bits above 16 set; the spawner "
                             f"dispatches on {tid}"
                             + (", but Map_LoadById compares the FULL value for the load-time "
                                "parameter records (types 9-13, 15, 29), so this record's "
                                "parameter is ignored" if tid in (9, 10, 11, 12, 13, 15, 29) else ""))
            if tid >= mobj_types.FIRST_MAP_OBJ_TYPE and tid > MAX_MAP_OBJ_TYPE_ID:
                errs.append(f"MOBJ #{i}: type {tid} is past the map_obj sprite band "
                            f"(max {MAX_MAP_OBJ_TYPE_ID}); archive {tid + 17542} is not a "
                            f"map object")
            # type-12 tint record: with f12 = 0 Map_LoadById writes RGB to
            # work[230 + 3*f8 ..] with no bounds check -- only slots 0..2 exist
            if tid == 12 and rec[12] == 0 and not (0 <= rec[8] <= 2):
                errs.append(f"MOBJ #{i} (tint_color): slot f8 = {rec[8]} but only 0 day / "
                            f"1 evening / 2 night exist; Map_LoadById indexes the tint array "
                            f"with f8 unchecked and writes past it (memory corruption)")
            # flag ids: every reader adds f13 to the zone-2 base with no bound check
            if mp.reads_flag(tid) and rec[13] != -1 and not 0 <= rec[13] < mp.MOBJ_FLAG_COUNT:
                errs.append(f"MOBJ #{i} ({name}): flag f13 = {rec[13]} is not -1 or 0..2559; "
                            f"the game adds it to the flag store's zone-2 base unchecked and "
                            f"tests a bit past the 832-byte store (a garbage gate; a large "
                            f"negative id reads a wild address and crashes)")
            if tid == 44 and rec[9]:
                off = (rec[9] & 0xFF) - 256 if rec[9] & 0x80 else rec[9] & 0xFF
                if not -128 <= rec[9] <= 127:
                    warns.append(f"MOBJ #{i} (chest): reveal offset f9 = {rec[9]} is kept as "
                                 f"one signed byte ({off})")
                if rec[13] != -1 and not 0 <= rec[13] + off < mp.MOBJ_FLAG_COUNT:
                    errs.append(f"MOBJ #{i} (chest): its reveal flag f13 + f9 = "
                                f"{rec[13] + off} is not 0..2559 (read past the flag store)")
            if tid == 263 and rec[13] < 0:
                errs.append(f"MOBJ #{i} ({name}): found flag f13 = {rec[13]}; this type has no "
                            f"'no flag' value -- it reads the id as a signed 16-bit number, so "
                            f"-1 tests the last zone-1 story bit. Give it a real id 0..2559")
            if mobj_types.mobj_kind(tid) == "object" and tid != 263 and rec[12] & 4 and rec[13] <= 0:
                warns.append(f"MOBJ #{i} ({name}): inverted flag gate (f12 bit 4) with no flag "
                             f"(f13 = {rec[13]}): the game draws it but never stamps its "
                             f"collision")
            if tid <= 8:
                forage += 1
                r = rec[9]
                if (rec[14] - r < 0 or rec[15] - r < 0 or rec[14] + r >= 2048
                        or rec[15] + r >= 1024):
                    errs.append(f"MOBJ #{i} ({name}): position ({rec[14]}, {rec[15]}) with "
                                f"scatter {r} does not fit the forage registry's packed "
                                f"coordinates (x 0..2047, y 0..1023 sub-units): the spawned "
                                f"item lands at a wrapped position")
                if tid == 0 and rec[11] == 0:
                    if (rec[10] & 63) >= mp.MAPORE_RATE_ROWS:
                        errs.append(f"MOBJ #{i} ({name}): ore config f10 = {rec[10]} (the "
                                    f"game uses f10 & 63 = {rec[10] & 63}) is past the "
                                    f"{mp.MAPORE_RATE_ROWS} rows of MapOre_Rate (reads "
                                    f"unrelated data)")
                    elif not 0 <= rec[10] <= 63:
                        warns.append(f"MOBJ #{i} ({name}): ore config f10 = {rec[10]} keeps "
                                     f"only its low 6 bits ({rec[10] & 63})")
            if 82 <= tid <= 195:
                doors += 1
                if rec[13] == 0:
                    warns.append(f"MOBJ #{i} ({name}): toggle flag f13 = 0 leaves its "
                                 f"collision-registry slot free, so the next door / wall "
                                 f"overwrites it")
            fl = mp.one_shot_flag(rec)
            if fl is not None:
                owners.setdefault(fl, []).append(i)
            if (has_grid and tid in self._REACHED_TYPES
                    and not (0 <= rec[14] >> 3 < W and 0 <= rec[15] >> 3 < H)):
                warns.append(f"MOBJ #{i} ({name}) at tile ({rec[14] >> 3},{rec[15] >> 3}) is "
                             f"outside the {W}x{H} grid: the player can never reach it")
        if forage > mp.FORAGE_MAX_SPAWNS:
            errs.append(f"{forage} forage spawners (types 0..8): the game spawns at most "
                        f"{mp.FORAGE_MAX_SPAWNS} per map, the rest never appear")
        if doors > mp.DOOR_SLOTS:
            warns.append(f"{doors} door / road / wall objects (types 82..195): the collision "
                         f"registry has {mp.DOOR_SLOTS} slots, so the 5th and later ones get "
                         f"none and toggle door #0's collision with door #0's flag instead")
        for fl, idx in owners.items():
            if len(idx) < 2:
                continue
            if all(recs[j][0] & 0xFFFF == 47 for j in idx):
                continue                        # a room's seal doors share its "cleared" flag
            for i in idx:
                others = ", ".join(f"#{j} ({mp.ONE_SHOT_FLAG_TYPES[recs[j][0] & 0xFFFF]})"
                                   for j in idx if j != i)
                warns.append(f"MOBJ #{i} ({mp.ONE_SHOT_FLAG_TYPES[recs[i][0] & 0xFFFF]}) "
                             f"shares its one-shot flag {fl} with {others}: whichever is used "
                             f"first sets it for all of them")
        return errs, warns

    def _atlas_findings(self, W: int, H: int, ground_reader=None, map_name=None):
        """(errors, warnings) comparing the ground atlas to a W x H ATTR grid.

        Split out of validate() so `resize_attr_grid` can reuse it. The slot-ceiling
        check is pure ATTR math; everything else needs `ground_reader` + `map_name`."""
        from . import mapground
        errs, warns = [], []
        cols, rows = mapground.grid_dims(W, H)
        need = cols * rows
        if need > mapground.MAX_TILE_SLOTS:
            errs.append(f"ATTR {W}x{H} needs a {cols}x{rows} = {need}-tile ground atlas, but "
                        f"Map_SpawnEntity's work buffer holds {mapground.MAX_TILE_SLOTS} tile "
                        f"pointers (+8 .. +775); tile {mapground.MAX_TILE_SLOTS} overwrites the "
                        f"decoration-model pointer at +776 and the next tiles the task pointer "
                        f"and archive id (memory corruption, no bounds check). Keep "
                        f"ceil(24*W/512) * ceil(24*H/512) <= {mapground.MAX_TILE_SLOTS}")
        if ground_reader is None:
            return errs, warns
        if not map_name:
            warns.append("ground_reader was passed without map_name, so the atlas check was "
                         "skipped (the ground texture set is usually not the same-named one, "
                         "so it cannot be guessed from the file)")
            return errs, warns
        audit = mapground.atlas_audit(ground_reader, map_name, W, H)
        if not audit:
            warns.append(f"no ground atlas found for {map_name} in the supplied reader "
                         f"(set {mapground.resolve_base(ground_reader, map_name)}): the map "
                         f"would draw untextured unless the tiles ship elsewhere")
        for a in audit:
            ly, st = a["layer"], a["set"]
            # Layers above 0 are the overlay (canopy/foliage): mostly transparent, so a
            # hole in one is often intentional. Two shipped overlay sets trip the geometry
            # checks (MAP_CITY_07, drawn on all four seasons, and MAP_DUNG_A01).
            ovl = ("" if ly == 0 else "  (layer %d is the overlay and mostly transparent, so "
                                      "this may be intentional -- the shipped MAP_CITY_07 and "
                                      "MAP_DUNG_A01 overlays do it)" % ly)
            if a["missing"]:
                m = a["missing"]
                errs.append(
                    f"layer {ly} ({st}): ATTR {W}x{H} makes the engine spawn {a['cols']}x"
                    f"{a['rows']} = {a['need']} tiles, but the set ships {a['have']} "
                    f"({mapground.tile_name(st, ly, 0)} .. {mapground.tile_name(st, ly, a['have'] - 1)}). "
                    f"Tiles {m[0]}..{m[-1]} do not exist; the loader asks for archive id base+i "
                    f"regardless, so those {len(m)} grid cells load whatever files follow the set "
                    f"(the next layer's tiles, then the next map's) and draw the wrong art. "
                    f"Add {mapground.tile_name(st, ly, m[0])} .. {mapground.tile_name(st, ly, m[-1])}")
            if a["extra"]:
                warns.append(f"layer {ly} ({st}): {a['have']} tiles shipped but only {a['need']} "
                             f"are spawned at ATTR {W}x{H}; tiles {a['extra'][0]}..{a['extra'][-1]} "
                             f"are never drawn (3 shipped overlay atlases do this too, so it is "
                             f"harmless -- but it usually means the grid shrank)")
            if a["gap_x"]:
                warns.append(f"layer {ly} ({st}): tile(s) {a['gap_x']} are narrower than 512 px "
                             f"but no longer sit in the last column; the engine pitches tiles at "
                             f"exactly 512 px, so each leaves a vertical untextured strip to its "
                             f"right (an old edge tile that the resize turned into an interior one)" + ovl)
            if a["gap_y"]:
                warns.append(f"layer {ly} ({st}): tile(s) {a['gap_y']} are shorter than 512 px but "
                             f"no longer sit in the last row; each leaves a horizontal untextured "
                             f"strip beneath it" + ovl)
            if a["short_x"] or a["short_y"]:
                warns.append(f"layer {ly} ({st}): the atlas stops {a['short_x']} px short on X and "
                             f"{a['short_y']} px short on Y of the map extent "
                             f"({W * mapground.PX_PER_ATTR_TILE}x{H * mapground.PX_PER_ATTR_TILE} px "
                             f"= ATTR x 24); the edge tiles need re-encoding at the larger size" + ovl)
        return errs, warns

    # ---- rebuild --------------------------------------------------------- #
    def build(self) -> bytes:
        stream = bytearray()
        for c in self.chunks:
            stream += c.tag + struct.pack("<I", len(c.payload)) + c.payload
        # The MAPD size word is the TOTAL FILE SIZE (the walk bound
        # `buffer + buffer[4]` in Map_LoadById), i.e. 8 + chunk-stream length --
        # NOT file_size-8.
        return MAGIC + struct.pack("<I", 8 + len(stream)) + bytes(stream)

    def save(self, path):
        pathlib.Path(path).write_bytes(self.build())

    def summary(self) -> str:
        from collections import Counter
        cnt = Counter(c.tag for c in self.chunks)
        parts = []
        for c in self.chunks:
            parts.append(f"{c.tag.decode('latin1')}({len(c.payload)})")
        head = ", ".join(f"{t.decode('latin1')}x{n}" for t, n in cnt.items())
        return head
