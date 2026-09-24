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
payload in the map task work buffer and never copies it:

    MSEA  1 x u32   season tag of this file (0 spring/none, 1 summer, 2 autumn,
                    3 winter; 4 on the farm-house / barn / system rooms). Stored but
                    NO runtime reader was found (255-function sweep of the map task).
    MGRP  1 x u32   map group bitfield -- READ. bits 0..3 = fixed season for this
                    map's ambience (bit0 spring .. bit3 winter; Map_LoadById turns them
                    into work[15] = 0..3, -1 = follow the calendar): petals/leaves/
                    light motes, ambient sfx, BGM variant. bit 4 = no weather effects
                    (dungeons/interiors). bits 5..25 = ONE-HOT area group (5 Selphia,
                    6 rooms, 7 farm, 8 fields, 9 DUNG_A ... 25 DUNG_O/P) -> BGM track
                    and minimap sheet group. A map WITHOUT an MGRP chunk crashes the
                    loader (it dereferences the pointer unconditionally).
    MLIG  3 x u32   tile tint colours for DAY / EVENING / NIGHT, one dword each as
                    0x00BBGGRR (only the low 24 bits are read; a zero triplet means
                    "engine default": day 255,255,255, evening 247,214,197, night
                    148,214,247 or 181,214,214 on snow maps). Every shipped map stores
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
                    2nd = overlay set [+2]); the dword value itself is never read.
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
ENGINE_MAX_CHUNKS = {b"MAPJ": 10, b"PALD": 6, b"MOBJ": 40, b"MTXN": 6}
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
# whose g_mapTypeAttribTable entry has bit 0x10 (snow biome).
MLIG_SLOTS = ("day", "evening", "night")
MLIG_DEFAULTS = ((255, 255, 255), (247, 214, 197), (148, 214, 247))
# MGRP bit meanings (Map_LoadById, WeatherTask_Tick, Scene_ApplyContextualBGM,
# Minimap_BuildForMap). bits 5..25 are the one-hot area group.
MGRP_SEASON_BITS = {0x1: "spring", 0x2: "summer", 0x4: "autumn", 0x8: "winter"}
MGRP_NO_WEATHER = 0x10
MGRP_GROUP_NAMES = {
    5: "Selphia town", 6: "interior rooms", 7: "farm", 8: "fields / outskirts",
    9: "DUNG_A", 10: "DUNG_B", 11: "DUNG_C", 12: "DUNG_D", 13: "DUNG_E", 14: "DUNG_F",
    15: "DUNG_G", 16: "DUNG_H", 17: "DUNG_I", 18: "DUNG_J", 19: "DUNG_K", 20: "DUNG_L",
    21: "DUNG_M", 22: "farm-house rooms", 23: "farm-house / barn rooms", 25: "DUNG_O / DUNG_P",
}


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
    if len(groups) > 1:
        parts.append("WARNING: more than one group bit (the game uses the lowest)")
    return ", ".join(parts)


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
        MOBJ parameter records (types 9..19, which carry no position) and records sitting
        at (0,0) are left alone, matching how `validate()` reads them. MAPJ *arrival*
        coordinates are NOT touched: they are positions in the destination map.

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
            if 9 <= tid <= 19 or not (rec[14] or rec[15]):
                continue                       # parameter record / positionless
            px, py = rec[14], rec[15]
            if shift_entities and (sx or sy):
                px, py = px + sx, py + sy
                moved_mobj.append(i)
                if not dry_run:
                    vals = list(rec)
                    vals[14], vals[15] = px, py
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
        if reindexed:
            todo.append(
                f"GROUND ATLAS MUST BE RE-LAID-OUT: the tile grid goes {old_grid[0]}x"
                f"{old_grid[1]} -> {new_grid[0]}x{new_grid[1]}, and because tiles are indexed "
                f"row-major (tile i at column i % cols) a change of COLUMN count moves every "
                f"existing tile to a different screen cell -- the atlas cannot just be extended. "
                f"Export the stitched layer BEFORE the resize (the exporter takes its aspect "
                f"from the .rf4m's ATTR), then re-import it against the resized map: "
                f"`map ground-export <MAP> -o old.png --layer L` -> resize -> "
                f"`map ground-import <MAP> old.png -o tiles/ --layer L`")
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
                            f"re-encode them at the new size (ground-import does this for you)")
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
        if (new_w, new_h) != (w, h):
            todo.append("minimap: rf3MapMiniPos.bin holds this map's origin/scale/reveal "
                        "rectangle in WORLD units (record fields 1-8), so the HUD minimap and "
                        "its fog-of-war box no longer match the new extent -- rescale that "
                        "record too (see rf4s_modkit.minimap)")
            todo.append("other maps that warp INTO this one carry the arrival position in their "
                        "own MAPJ records (fields 6/7); those are not visible from this file and "
                        "need checking by hand if the content moved")
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
    def validate(self, known_maps=None, *, ground_reader=None, map_name=None) -> list[str]:
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
        ATTR alone and needs neither."""
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
        if not counts[b"MTXN"]:
            errs.append("no MTXN chunk: the loader spawns one display layer per MTXN chunk, "
                        "so the ground textures would never be drawn")
        elif counts[b"MTXN"] > 2:
            warns.append(f"{counts[b'MTXN']} MTXN chunks: only two display layers exist "
                         f"(ground, overlay); the extra chunks spawn duplicate overlay layers")
        if not counts[b"MLIG"]:
            warns.append("no MLIG chunk: Map_PostLoad skips the tint setup, so the day/evening/"
                         "night tints stay 0 (black tiles) unless type-12 records set them")
        if not counts[b"MSEA"]:
            warns.append("no MSEA chunk (nothing reads it, but every shipped map has one)")
        # 3. fixed-size pointer arrays in the map task work buffer
        for tag, cap in ENGINE_MAX_CHUNKS.items():
            n = counts[tag]
            if n > cap:
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
        for i, rec in enumerate(self.mobj_records()):
            tid = rec[0] & 0xFFFF
            name = mobj_types.mobj_display_name(tid) or f"type {tid}"
            if rec[0] != tid:
                warns.append(f"MOBJ #{i}: type {rec[0]} has bits above 16 set; the game "
                             f"dispatches on {tid}")
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
            if grid and not (9 <= tid <= 19) and (rec[14] or rec[15]):
                tx, ty = rec[14] >> 3, rec[15] >> 3
                if not (0 <= tx < W and 0 <= ty < H):
                    warns.append(f"MOBJ #{i} ({name}) at tile ({tx},{ty}) is outside the "
                                 f"{W}x{H} grid")
        # 6. warps
        for i, rec in enumerate(self.mapj_records()):
            zx, zy, zw, zh = rec[1:5]
            if zw <= 0 or zh <= 0:
                warns.append(f"warp #{i}: degenerate zone size {zw}x{zh} sub-units")
            if grid and (zx < 0 or zy < 0 or (zx >> 3) >= W or (zy >> 3) >= H):
                warns.append(f"warp #{i}: zone origin tile ({zx >> 3},{zy >> 3}) is outside "
                             f"the {W}x{H} grid")
            if known_maps is not None and rec[5] not in known_maps:
                errs.append(f"warp #{i}: destination map id {rec[5]} is not a known map")
            if rec[6] < 0 or rec[7] < 0:
                warns.append(f"warp #{i}: negative arrival position ({rec[6]},{rec[7]})")
            # Cutscene_StartDeathSequence keeps the arrival as 16-bit words and
            # Scene_FinalizeMajorTransition sign-extends x/y (movsx) before << 12
            if rec[6] > 0x7FFF or rec[7] > 0x7FFF:
                errs.append(f"warp #{i}: arrival ({rec[6]},{rec[7]}) does not fit the signed "
                            f"16-bit words the transition stores it in (max 32767 sub-units "
                            f"= tile 4095); the player lands at a wrapped position")
            if not (0 <= rec[5] <= 0xFFFF):
                errs.append(f"warp #{i}: destination map id {rec[5]} is stored as a u16 by "
                            f"the transition and wraps")
            if zh > 0xFFFF:
                warns.append(f"warp #{i}: zone height {zh} is truncated to 16 bits by "
                             f"Widget_SetCollisionBox's caller")
            if not (0 <= rec[8] < 360):
                warns.append(f"warp #{i}: arrival facing {rec[8]} is not 0..359 degrees")
            if rec[0] != -1 and not (0 <= rec[0] <= 0x7FFF):
                warns.append(f"warp #{i}: disable-flag {rec[0]} is read as a 16-bit id "
                             f"(-1 = none)")
        # 7. ground-texture atlas vs the ATTR grid
        if grid:
            errs2, warns2 = self._atlas_findings(W, H, ground_reader, map_name)
            errs += errs2
            warns += warns2
        return [f"ERROR: {e}" for e in errs] + [f"WARN: {w}" for w in warns]

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
            # hole in one is often intentional. Three shipped overlays trip the geometry
            # checks (MAP_CITY_07, MAP_DUNG_A01, MAP_DUNG_I04) -- see mapground.atlas_audit.
            ovl = ("" if ly == 0 else "  (layer %d is the overlay and mostly transparent, so "
                                      "this may be intentional -- 3 shipped overlays do it)" % ly)
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
                             f"are never drawn (4 shipped overlay atlases do this too, so it is "
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
        # NOT file_size-8. (docs/09 §2's "file_size - 8" is wrong; see docs/15.)
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
