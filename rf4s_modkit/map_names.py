"""Map / location display names -- resolve a map id to its in-game name, tell whether a warp
destination is a *building/shop entrance* (which carries a signboard), map ids <-> `MAP_*`
files, and the cases where the HUD's location band deviates from the static name.

Sources
-------
* `map_names.json`  -- the game's own `rf3TxtMapName.eng` text archive (nsFileArchive
  15183; the ids the code passes, 0x3B51 = 15185, point at the `.jpn` row of the exe's
  path table and MageEngine_OpenLocalizedResource swaps in the active language).
  Index quirk: an entry's index is **map_id + 1** -- index 0 is a "JP" header row.
  Verified live: map 24 -> "Selphia: Airship Way", 136 -> "Bell Hotel Lobby",
  130 -> "Porcoline's Kitchen". Entries are whitespace-trimmed (the game has a trailing
  space on eight "Selphia" rows).
* `map_overmodels.json` -- its key order is the game's `g_mapResourceTable` order, i.e.
  key N is the `MAP_*` file of map id N (872 maps; ids 872/873 have a name but no map).

The HUD band (Minimap_BuildLocationNameLabel, RF4S.exe+0x138DB0) shows
`rf3TxtMapName[map_id + 1]` except:
* farm maps 4..23 (once REG_MAIN_SCENARIO >= 0x27): the player's farm name
  (farm (id-4)>>2) + " " + the static text ("Farm" / "Field");
* barn rooms 77..126: the player's barn name (barn (id-77)//5), no static text at all;
* Sharance Maze floors 442..453: the static text + " %2dF" (boss-tower mode >= 9 uses
  row 443 = "World of Fields" instead);
* map 179 shows row 873 ("Volkanon Bridge") instead of "Cliff" until REGION-B scene
  flag 70 (absolute GameFlags bit 4166) is set;
* a leading "_" hides the band (the 3DS placeholders; PC rows say "BLANK: ROW n").

Why this matters for the map editor: shop/building signboards ("Bell Hotel 10:00-22:00")
are NOT stored in the .rf4m -- they're spawned by the town/shop system. But every building
entrance is a MAPJ warp whose destination is an interior room, and the sign shows that
room's name. So resolving a warp's destination id -> name marks where each sign is.
"""
import json
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
_NAMES = json.loads((_HERE / "map_names.json").read_text(encoding="utf-8"))

# Destinations that are NOT a building sign -- outdoor areas / farm / fields / blanks.
_NON_BUILDING_PREFIXES = ("Selphia:", "Selphia ", "Field", "Farm", "Room: Dummy", "BLANK", "JP")

FARM_MAP_IDS = range(4, 24)        # 5 farms x 4 seasons; HUD prefixes the farm's name
BARN_MAP_IDS = range(77, 127)      # 5 barns x (L, R) x 5 rooms; HUD shows the barn's name
MAZE_MAP_IDS = range(442, 454)     # Sharance Maze floors; HUD appends " %2dF"
CLIFF_MAP_ID = 179                 # "Cliff" ...
BRIDGE_NAME_ROW_MAP_ID = 872       # ... swaps to this row's text ("Volkanon Bridge")
MAZE_ALT_NAME_MAP_ID = 442         # "World of Fields", used for boss-tower mode >= 9

_FILES = None


def map_count() -> int:
    """Number of named map ids (874 on a stock table: 0..873)."""
    return max(len(_NAMES) - 1, 0)


def map_name(map_id):
    """In-game display name for a map id, or '' if unknown/blank."""
    i = (map_id & 0xFFFF) + 1                 # rf3TxtMapName index = map_id + 1
    if 0 <= i < len(_NAMES):
        return _NAMES[i]
    return ""


def is_building_entrance(map_id):
    """True if a warp to `map_id` lands in an interior building/shop (i.e. the entrance
    on the outdoor side carries a signboard), False for town-segment / field / farm exits."""
    n = map_name(map_id)
    if not n:
        return False
    return not any(n.startswith(p) for p in _NON_BUILDING_PREFIXES)


def describe_destination(map_id):
    """(name, is_building) for a warp destination."""
    return map_name(map_id), is_building_entrance(map_id)


# --------------------------------------------------------------------------- #
# map id <-> MAP_* file (g_mapResourceTable order, as vendored in map_overmodels.json)
# --------------------------------------------------------------------------- #
def _files() -> list:
    global _FILES
    if _FILES is None:
        try:
            _FILES = list(json.loads((_HERE / "map_overmodels.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            _FILES = []
    return _FILES


def map_file(map_id):
    """`MAP_*` base name (no extension) of a map id, e.g. 136 -> 'MAP_ROOM_06A';
    None for ids without a map (872, 873) or out of range."""
    files = _files()
    mid = int(map_id) & 0xFFFF
    return files[mid] if 0 <= mid < len(files) else None


def map_id_for_file(name):
    """Map id of a `.rf4m` file name / path / base name (case-insensitive; seasonal
    variants such as MAP_CITY_01_SUMMER are their own ids), or None."""
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    if base.lower().endswith(".rf4m"):
        base = base[:-5]
    base = base.upper()
    for i, f in enumerate(_files()):
        if f.upper() == base:
            return i
    return None


# --------------------------------------------------------------------------- #
# HUD band exceptions (Minimap_BuildLocationNameLabel)
# --------------------------------------------------------------------------- #
def label_note(map_id):
    """One-line note when the HUD's location band does not simply show map_name(map_id);
    None when it does."""
    mid = int(map_id) & 0xFFFF
    name = map_name(mid)
    if mid in FARM_MAP_IDS:
        return (f"HUD band prefixes the player's farm name (farm {(mid - 4) >> 2}) once "
                f"REG_MAIN_SCENARIO >= 0x27: '<farm name> {name}'")
    if mid in BARN_MAP_IDS:
        return (f"HUD band shows the player's barn name (barn {(mid - 77) // 5}) instead of "
                f"'{name}'")
    if mid in MAZE_MAP_IDS:
        note = "HUD band appends the floor as ' %2dF'"
        alt = map_name(MAZE_ALT_NAME_MAP_ID)
        if alt != name:
            note += f"; boss-tower mode >= 9 shows '{alt}' instead of '{name}'"
        return note
    if mid == CLIFF_MAP_ID:
        return (f"HUD band shows '{map_name(BRIDGE_NAME_ROW_MAP_ID)}' (row of map "
                f"{BRIDGE_NAME_ROW_MAP_ID}) until REGION-B scene flag 70 is set, then '{name}'")
    if name.startswith("_"):
        return "leading '_' hides the HUD band"
    return None
