#!/usr/bin/env python3
"""Generate out/map_names.json -- the map-id registry: in-game name, .rf4m file, HUD-band
notes and the minimap sheet / placement for every map id.

Sources (refdata/; --bake also refreshes the minimap table from your game):
  * map_names.json       rf3TxtMapName.eng  (nsFileArchive 15183; row = map id + 1)
  * map_overmodels.json  g_mapResourceTable order -> MAP_* file per id
  * map_minimap.json     rf3MapMiniPos.bin  (nsFileArchive 11839) -> minimap sheet + placement
                         (--bake: re-read from Bundle/**/rf3MapMiniPos.bin, or --minipos PATH)

Output: one object per map id, keys are decimal strings "0".."873":
  name         in-game display name (whitespace-trimmed; placeholder rows kept verbatim)
  file         MAP_* .rf4m base name, or null (ids 872/873 have a name but no map)
  label_note   only where the HUD band deviates from `name` (farm/barn names, maze floor,
               the Cliff / Volkanon Bridge swap, hidden '_' rows)
  minimap
    sheet        raw rf3MapMiniPos value
    texture      picture actually drawn in the default state (mini_map_*.texture basename)
    archive_id   nsFileArchive id of that picture (12199 + sheet after clamping)
    blank        true when the blank 99_dummy picture is drawn
    composed     true for Sharance Maze floors (picture built from mini_map_rnd_* at runtime)
    variants     {texture: condition} for sheets the game swaps by save state, else null
    origin       [x, y]  drawn (half-scale) px where the map's world origin sits on the sheet
    scale_q12    [x, y]  Q12 drawn px per world unit (px = origin + (scale * (world>>12)) >> 12)
    reveal       [x, y, w, h] fog-of-war rectangle, or null (no fog)
    npc_parent   {sheet, texture, icon [x, y], slot} for interiors whose NPC icons are drawn
                 on another sheet, else null

Run:  python gen_map_names_json.py [--minipos PATH] [--out PATH] [--bake]
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rf4s_modkit import map_names, minimap  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent / "out"   # generated files (git-ignored)
from rf4s_modkit import gamepaths  # noqa: E402
BUNDLE_DIR = gamepaths.bundle_dir()
EXTRACTED = (BUNDLE_DIR / "extracted") if (BUNDLE_DIR / "extracted").is_dir() else BUNDLE_DIR


def find_minipos():
    """The game's rf3MapMiniPos.bin under the bundle tree (bundleMain wins), or None."""
    if not EXTRACTED.is_dir():
        return None
    hits = sorted(EXTRACTED.rglob("rf3MapMiniPos.bin"),
                  key=lambda p: (0 if "bundleMain" in p.parts else 1, str(p)))
    return hits[0] if hits else None


def entry(map_id: int) -> dict:
    out = {"name": map_names.map_name(map_id), "file": map_names.map_file(map_id)}
    note = map_names.label_note(map_id)
    if note:
        out["label_note"] = note
    rec = minimap.record(map_id)
    if rec is None:
        out["minimap"] = None
        return out
    var = minimap.variants(map_id)
    parent = None
    if rec["parent_sheet"] is not None:
        parent = {"sheet": rec["parent_sheet"],
                  "texture": minimap.texture_for_sheet(rec["parent_sheet"]),
                  "icon": list(rec["icon"]), "slot": rec["icon_slot"]}
    out["minimap"] = {
        "sheet": rec["sheet"],
        "texture": minimap.texture(map_id),
        "archive_id": minimap.archive_id(map_id),
        "blank": minimap.is_blank(map_id),
        "composed": minimap.is_composed(map_id),
        "variants": {v["texture"]: v["when"] for v in var} if var else None,
        "origin": list(rec["origin"]),
        "scale_q12": list(rec["scale_q12"]),
        "reveal": list(rec["reveal"]) if rec["reveal"] else None,
        "npc_parent": parent,
    }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--minipos", help="rf3MapMiniPos.bin to bake into refdata/map_minimap.json "
                                      "(implies --bake)")
    ap.add_argument("--out", help=f"output path (default: {OUT / 'map_names.json'})")
    ap.add_argument("--bake", action="store_true",
                    help="refresh refdata/map_minimap.json from the game's rf3MapMiniPos.bin first "
                         "(an edited file then becomes the shipped table)")
    a = ap.parse_args(argv)

    src = pathlib.Path(a.minipos) if a.minipos else (find_minipos() if a.bake else None)
    if src is not None:
        n = minimap.bake(src)
        print(f"baked refdata/map_minimap.json from {src} ({n} records)")
    elif not minimap.table_available():
        print("warning: no rf3MapMiniPos.bin found and no vendored map_minimap.json -- "
              "minimap fields will be null", file=sys.stderr)

    table = {str(i): entry(i) for i in range(map_names.map_count())}
    out = pathlib.Path(a.out) if a.out else OUT / "map_names.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(table, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sheets = len({e["minimap"]["sheet"] for e in table.values() if e["minimap"]})
    print(f"wrote {out} ({len(table)} map ids, {sheets} minimap sheets in use)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
