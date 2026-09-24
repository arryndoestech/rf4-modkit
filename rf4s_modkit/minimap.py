r"""
minimap.py -- which `mini_map_*.texture` the HUD minimap draws for a map, where the map sits
on that picture, and the save-state swaps the game applies on top.

The game does NOT pick the minimap by map name. `rf3MapMiniPos.bin` (nsFileArchive id 11839,
an NLCL table of 873 x 52-byte records indexed by MAP ID) gives every map a "sheet" number;
the picture is resource `12199 + sheet`, and the exe's resource-path table (RF4S.exe+0x57AD30,
one 256-byte path per id) turns that into `rom:/map_mini/<name>.bntx` -- the PC bundle stores
the same basename as `<name>.texture`. 104 sheets exist (ids 12199..12302): 88 static
pictures, then 16 `mini_map_rnd_*` room tiles used only to compose the Sharance Maze picture.

Verified against RF4S.exe (RVAs; the IDB used for the trace was rebased to 0x7ff7c1dc0000):

  MiniMap_BuildInitialIcons      +0x139160  loads 11839, table = data + 28 (minimap work +56)
  Minimap_BuildForMap(mapId)     +0x13B3F0  sheet = rec[0]; resource = 12199 + sheet; the swaps
                                            in VARIANT_RULES; fog-of-war reveal
  sub_7FF7C1EFB2E0               +0x13B2E0  reveal blit(tex, buf, x=rec[3], y=rec[4],
                                            w=rec[5], h=rec[6]) -- x/y travel in xmm2/xmm3,
                                            which is why a decompiler only shows w/h
  sub_7FF7C1EFC480(roomId)       +0x13C480  reveal refresh when the sheet did not change
  Minimap_UpdateNpcIcons         +0x13C680  icon px = rec[1] + ((rec[7] * (world_x >> 12)) >> 12)
                                            (y: rec[2] / rec[8]); NPCs inside a building are
                                            drawn on sheet rec[10] at (rec[11], rec[12]),
                                            4 px apart per rec[9] slot
  Minimap_BuildLocationNameLabel +0x138DB0  the name band -- see map_names.label_note()

Record layout (13 x s32 -- also the `rf3MapMiniPos` schema in nlcl.py):

  [0]  sheet                    SHEET_TEXTURES index; resource id = ARCHIVE_ID_BASE + sheet
  [1]  origin_x   [2] origin_y  where the map's world origin lands on the picture, in DRAWN
                                (half-scale) pixels -- the 512-px texture is drawn at 0.5
  [3]  reveal_x   [4] reveal_y  fog-of-war rectangle uncovered once the map is visited
  [5]  reveal_w   [6] reveal_h  (w or h zero = no fog: towns, interiors, blanks)
  [7]  scale_x    [8] scale_y   Q12 fixed point, drawn px per world unit; world coordinates
                                are 20.12 fixed, so `(scale * (world >> 12)) >> 12`
  [9]  icon_slot                stacking slot of an interior's NPC icons on the parent sheet
  [10] parent_sheet             sheet that shows this interior's NPCs (73 = none)
  [11] icon_x     [12] icon_y   where those icons go on the parent sheet

Fog of war: the picture is cleared on load, then every VISITED map sharing the sheet has its
reveal rectangle re-uploaded from a CPU copy of the texture (visited bits live in a runtime
bitset, one per map id, plus one "sheet complete" bit per sheet at 872 + sheet). Newlywed-mode
saves (g_saveConfigFlags & 0x40) skip the fog entirely.

Sheet values of 73 or above 87 all draw `mini_map_99_dummy` (blank). That is how the "???"
dungeon (maps 527..540) stays blank although `mini_map_11_dung_i` exists -- nothing references
sheet 27. Sharance Maze floors (442..453) are composed at runtime from the `mini_map_rnd_*`
tiles into 99_dummy / 99_dummy2 (double-buffered), so their table value (110) is never drawn.

The per-map table is vendored as `map_minimap.json`; refresh it from your bundle with
`gen_map_names_json.py` (or :func:`bake`). Map id <-> `MAP_*` file names live in
map_names.py (`map_overmodels.json` key order = the game's g_mapResourceTable order).
"""
from __future__ import annotations

import json
import pathlib

ARCHIVE_ID_BASE = 12199          # nsFileArchive id of mini_map_00_city
ARCHIVE_ID_MINIPOS = 11839       # rom:/map/rf3MapMiniPos.bin
DUMMY_SHEET = 73                 # mini_map_99_dummy  -- the blank picture
DUMMY2_SHEET = 74                # mini_map_99_dummy2 -- the maze's second buffer
LAST_STATIC_SHEET = 87           # mini_map_dung_q04 = resource 0x2FFE, the code's upper bound
MAZE_TILE_SHEETS = range(88, 104)
MAZE_MAP_IDS = range(442, 454)   # Sharance Maze floors: picture composed at runtime
RECORD_SIZE = 52
RECORD_FIELDS = ("sheet", "origin_x", "origin_y", "reveal_x", "reveal_y", "reveal_w",
                 "reveal_h", "scale_x", "scale_y", "icon_slot", "parent_sheet", "icon_x",
                 "icon_y")

# Resource ids 12199..12302 in archive order (dumped from the exe's path table).
SHEET_TEXTURES = (
    "mini_map_00_city", "mini_map_00_city_1", "mini_map_00_city_2",                # 0
    "mini_map_00_city_3", "mini_map_01_dung_a", "mini_map_02_dung_b",              # 3
    "mini_map_02_dung_b_1", "mini_map_03_dung_c_0", "mini_map_03_dung_c_1",        # 6
    "mini_map_04_dung_d_0", "mini_map_05_dung_e_0", "mini_map_05_dung_e_1",        # 9
    "mini_map_05_dung_e_2", "mini_map_05_dung_e_3", "mini_map_07_dung_g_0",        # 12
    "mini_map_07_dung_g_1", "mini_map_07_dung_g_2", "mini_map_08_dung_h_0",        # 15
    "mini_map_08_dung_h_1", "mini_map_09_dung_j_0", "mini_map_09_dung_j_1",        # 18
    "mini_map_09_dung_j_2", "mini_map_10_dung_k_0", "mini_map_10_dung_k_1",        # 21
    "mini_map_10_dung_k_2", "mini_map_10_dung_k_3", "mini_map_10_dung_k_4",        # 24
    "mini_map_11_dung_i", "mini_map_11_dung_l_0", "mini_map_11_dung_l_1",          # 27
    "mini_map_11_dung_l_2", "mini_map_30_farm", "mini_map_30_farm_1",              # 30
    "mini_map_30_farm_2", "mini_map_30_farm_3", "mini_map_30_farm_4",              # 33
    "mini_map_50_f_room", "mini_map_50_f_room_0", "mini_map_50_f_room_0_1",        # 36
    "mini_map_50_f_room_0_2", "mini_map_50_f_room_0_3", "mini_map_50_f_room_0_4",  # 39
    "mini_map_50_f_room_0_5", "mini_map_50_f_room_1", "mini_map_50_f_room_sk_0",   # 42
    "mini_map_50_f_room_sk_0_1", "mini_map_50_f_room_sk_0_2", "mini_map_50_f_room_sk_0_3",  # 45
    "mini_map_50_f_room_sk_0_4", "mini_map_50_f_room_sk_0_5", "mini_map_51_room_01",        # 48
    "mini_map_52_room_02", "mini_map_53_room_03", "mini_map_54_room_04",           # 51
    "mini_map_55_room_05", "mini_map_56_room_06", "mini_map_57_room_07",           # 54
    "mini_map_58_room_09", "mini_map_59_room_10", "mini_map_59_room_13",           # 57
    "mini_map_59_room_14", "mini_map_60_m_room", "mini_map_60_m_room_1",           # 60
    "mini_map_60_m_room_2", "mini_map_60_m_room_3", "mini_map_60_m_room_4",        # 63
    "mini_map_70_field", "mini_map_70_field_1", "mini_map_70_field_2",             # 66
    "mini_map_70_field_3", "mini_map_71_field", "mini_map_72_field",               # 69
    "mini_map_72_field_1", "mini_map_99_dummy", "mini_map_99_dummy2",              # 72
    "mini_map_dung_m01", "mini_map_dung_m02", "mini_map_dung_m03",                 # 75
    "mini_map_dung_m04", "mini_map_dung_m05", "mini_map_dung_m06",                 # 78
    "mini_map_dung_n01", "mini_map_dung_o01", "mini_map_dung_p01",                 # 81
    "mini_map_dung_q01", "mini_map_dung_q02", "mini_map_dung_q03",                 # 84
    "mini_map_dung_q04", "mini_map_rnd_00", "mini_map_rnd_10",                     # 87
    "mini_map_rnd_11", "mini_map_rnd_12", "mini_map_rnd_13",                       # 90
    "mini_map_rnd_20", "mini_map_rnd_21", "mini_map_rnd_22",                       # 93
    "mini_map_rnd_23", "mini_map_rnd_24", "mini_map_rnd_25",                       # 96
    "mini_map_rnd_30", "mini_map_rnd_31", "mini_map_rnd_32",                       # 99
    "mini_map_rnd_33", "mini_map_rnd_40",                                          # 102
)
assert len(SHEET_TEXTURES) == 104 and SHEET_TEXTURES[DUMMY_SHEET] == "mini_map_99_dummy"

# The swaps Minimap_BuildForMap applies AFTER the table lookup, keyed by the table's sheet.
# Each entry: (sheet drawn, condition). Conditions name the game state the way the exe tests
# it: REG_* = emdeb registers read with GameFlags_ReadField; "scene flag N" = REGION-B scene
# bit N (absolute GameFlags bit 4096 + N -- the per-save event space MOBJ f13 uses, which
# emdeb does not name); "PP 0xNNNN" = a bit of g_princePointMenuState.unlocks_bitfield (a
# Prince/Princess Point order). Barn rules use {reg} for the barn's own register.
VARIANT_RULES = {
    0: (  # Selphia town
        (0, "scene flag 73 set, PP 0x20000 clear"),
        (1, "scene flag 73 set, PP 0x20000 set"),
        (2, "scene flag 73 clear, PP 0x20000 clear"),
        (3, "scene flag 73 clear, PP 0x20000 set"),
    ),
    5: (  # Water Ruins
        (5, "REG_MAIN_SCENARIO < 0x52"),
        (6, "REG_MAIN_SCENARIO >= 0x52"),
    ),
    31: tuple((31 + lv, f"REG_FARM_LV == {lv}") for lv in range(5)),
    37: (tuple((37 + lv, f"REG_MYROOM == {lv} (Story mode)") for lv in range(6))
         + tuple((44 + lv, f"REG_MYROOM == {lv} (Newlywed mode: g_saveConfigFlags & 0x40)")
                 for lv in range(6))),
    61: tuple((60 + lv, "{reg} == %d" % lv) for lv in range(1, 6)),   # lv 0 would hit sheet 60
    66: (  # Selphia Plain west / castle-gate side
        (66, "scene flag 70 set, PP 0x4000 clear"),
        (67, "scene flag 70 set, PP 0x4000 set"),
        (68, "scene flag 70 clear, PP 0x4000 clear"),
        (69, "scene flag 70 clear, PP 0x4000 set"),
    ),
    71: (  # Autumn Road side
        (71, "scene flag 134 set"),
        (72, "scene flag 134 clear"),
    ),
}
BARN_MAP_IDS = range(77, 127)      # 5 barns x (L, R) x 5 rooms; (id-77)//5 = half-barn index

_HERE = pathlib.Path(__file__).resolve().parent
_TABLE_JSON = _HERE / "map_minimap.json"
_RECORDS = None


# --------------------------------------------------------------------------- #
# the vendored per-map table
# --------------------------------------------------------------------------- #
def _records() -> list:
    global _RECORDS
    if _RECORDS is None:
        try:
            _RECORDS = json.loads(_TABLE_JSON.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _RECORDS = []
    return _RECORDS


def table_available() -> bool:
    """True when map_minimap.json is vendored (bake it with gen_map_names_json.py)."""
    return bool(_records())


def map_count() -> int:
    return len(_records())


def raw_record(map_id: int) -> list | None:
    """The 13 raw dwords of a map's rf3MapMiniPos record (see RECORD_FIELDS), or None."""
    recs = _records()
    mid = int(map_id) & 0xFFFF
    return list(recs[mid]) if 0 <= mid < len(recs) else None


def record(map_id: int) -> dict | None:
    """Decoded record: sheet, origin (x, y), reveal (x, y, w, h) or None, scale_q12 (x, y),
    icon_slot, parent_sheet (None when the table says 73 = none) and icon (x, y) or None."""
    r = raw_record(map_id)
    if r is None:
        return None
    has_parent = r[10] != DUMMY_SHEET
    return {
        "sheet": r[0],
        "origin": (r[1], r[2]),
        "reveal": (r[3], r[4], r[5], r[6]) if (r[5] and r[6]) else None,
        "scale_q12": (r[7], r[8]),
        "icon_slot": r[9],
        "parent_sheet": r[10] if has_parent else None,
        "icon": (r[11], r[12]) if has_parent else None,
    }


# --------------------------------------------------------------------------- #
# sheet -> texture
# --------------------------------------------------------------------------- #
def texture_for_sheet(sheet: int) -> str | None:
    """Texture basename for a raw sheet number (no clamping), or None when out of range."""
    return SHEET_TEXTURES[sheet] if 0 <= sheet < len(SHEET_TEXTURES) else None


def sheet_for_texture(name: str) -> int | None:
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if base.lower().endswith((".texture", ".bntx")):
        base = base.rsplit(".", 1)[0]
    try:
        return SHEET_TEXTURES.index(base)
    except ValueError:
        return None


def sheet(map_id: int) -> int | None:
    """The map's raw table sheet value."""
    r = raw_record(map_id)
    return r[0] if r is not None else None


def effective_sheet(map_id: int) -> int | None:
    """The sheet actually drawn before any variant swap: 73 (blank) when the table says 73
    or anything above 87 -- exactly `if (id == 12272 || id > 0x2FFE) id = 12272`."""
    s = sheet(map_id)
    if s is None:
        return None
    return DUMMY_SHEET if (s == DUMMY_SHEET or s > LAST_STATIC_SHEET) else s


def texture(map_id: int) -> str | None:
    """Basename of the picture the HUD draws for the map in the default state
    (e.g. 'mini_map_00_city'); 'mini_map_99_dummy' for blank maps and maze floors."""
    s = effective_sheet(map_id)
    return texture_for_sheet(s) if s is not None else None


def archive_id(map_id: int) -> int | None:
    """nsFileArchive resource id of that picture (12199 + effective sheet)."""
    s = effective_sheet(map_id)
    return ARCHIVE_ID_BASE + s if s is not None else None


def is_composed(map_id: int) -> bool:
    """Sharance Maze floors: the picture is built at runtime from the rnd tiles."""
    return int(map_id) in MAZE_MAP_IDS


def is_blank(map_id: int) -> bool:
    """Draws the blank dummy picture and is not a maze floor."""
    return effective_sheet(map_id) == DUMMY_SHEET and not is_composed(map_id)


def maps_on_sheet(sheet_no: int) -> list[int]:
    """Every map id whose raw table value is `sheet_no`."""
    return [i for i, r in enumerate(_records()) if r[0] == sheet_no]


def sheets_in_use() -> dict[int, list[int]]:
    """raw sheet -> map ids (60 sheets on a stock table)."""
    out: dict[int, list[int]] = {}
    for i, r in enumerate(_records()):
        out.setdefault(r[0], []).append(i)
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- #
# state-dependent swaps
# --------------------------------------------------------------------------- #
def barn_register(map_id: int) -> str | None:
    """emdeb register holding the barn level that picks a barn room's picture:
    REG_MON_HOUSE<n>_<L|R>_LV with n = (id-77)//10 and L/R = ((id-77)//5) & 1."""
    mid = int(map_id)
    if mid not in BARN_MAP_IDS:
        return None
    half = (mid - 77) // 5
    return f"REG_MON_HOUSE{half // 2}_{'L' if half % 2 == 0 else 'R'}_LV"


def variants(map_id: int) -> list[dict]:
    """All pictures the map can show, as {sheet, texture, when} dicts (the default-state
    picture included). Empty when the map's sheet has no swap rule."""
    s = effective_sheet(map_id)
    rules = VARIANT_RULES.get(s) if s is not None else None
    if not rules:
        return []
    reg = barn_register(map_id) or "REG_MON_HOUSE<n>_<L|R>_LV"
    return [{"sheet": sh, "texture": texture_for_sheet(sh), "when": cond.format(reg=reg)}
            for sh, cond in rules]


# --------------------------------------------------------------------------- #
# placement helpers
# --------------------------------------------------------------------------- #
def pos_to_sheet(map_id: int, x: int, y: int) -> tuple[int, int] | None:
    """Drawn-pixel position on the sheet for a map position given in MOBJ/MAPJ sub-units
    (world >> 12; tile = sub-unit >> 3) -- the icon math of Minimap_UpdateNpcIcons.
    Multiply by 2 for pixels in the 512-px texture."""
    r = raw_record(map_id)
    if r is None:
        return None
    return (r[1] + ((r[7] * int(x)) >> 12), r[2] + ((r[8] * int(y)) >> 12))


def world_to_sheet(map_id: int, world_x: int, world_y: int) -> tuple[int, int] | None:
    """Same as :func:`pos_to_sheet` for 20.12 fixed-point world coordinates."""
    return pos_to_sheet(map_id, int(world_x) >> 12, int(world_y) >> 12)


def texture_path(name_or_map_id, root) -> pathlib.Path | None:
    """Locate `<sheet>.texture` under an extracted-bundle root. Accepts a texture basename
    or a map id (resolved through :func:`texture`)."""
    if isinstance(name_or_map_id, int):
        name = texture(name_or_map_id)
    else:
        name = str(name_or_map_id).rsplit(".", 1)[0] if str(name_or_map_id).endswith(".texture") \
            else str(name_or_map_id)
    if not name:
        return None
    root = pathlib.Path(root)
    direct = root / f"{name}.texture"
    if direct.is_file():
        return direct
    hits = list(root.rglob(f"{name}.texture"))
    return hits[0] if hits else None


# --------------------------------------------------------------------------- #
# vendoring
# --------------------------------------------------------------------------- #
def bake(minipos_bin, out_path=None) -> int:
    """Re-vendor map_minimap.json from a game `rf3MapMiniPos.bin` (NLCL, 873 x 52 B).
    Returns the record count. Resets the in-memory cache."""
    global _RECORDS
    from . import nlcl
    t = nlcl.NlclTable.load(pathlib.Path(minipos_bin))
    if t.record_size != RECORD_SIZE:
        raise nlcl.NlclError(f"{minipos_bin}: record size {t.record_size}, expected {RECORD_SIZE}")
    rows = [[t.get(i, 4 * k, "s32") for k in range(13)] for i in range(t.entry_count)]
    out = pathlib.Path(out_path) if out_path else _TABLE_JSON
    body = ",\n".join("  " + json.dumps(r) for r in rows)
    out.write_text("[\n" + body + "\n]\n", encoding="utf-8")
    _RECORDS = None
    return len(rows)
