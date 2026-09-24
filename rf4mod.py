#!/usr/bin/env python3
r"""
rf4mod -- the Rune Factory 4 Special modding command-line toolkit.

One dispatcher over the rf4s_modkit library. Covers every asset format that ships
in the .mbundle archives: identify, unpack/repack bundles, edit UI plists, edit
text catalogs, decode/encode textures, inspect/rebuild maps, disassemble/assemble
AI scripts, edit .strings, and inspect NN containers.

Run `rf4mod <group> -h` for per-group help. Start with:

    rf4mod selftest                       # verify the toolkit against your bundles
    rf4mod ident <file>                   # what is this file?
    rf4mod bundle list bundlePatch1.mbundle
    rf4mod text show bundleMain.mbundle/rf3mc.eng --range 0:20

Install methods (see docs/15-modding-toolkit.md):
  * loose file  -> `rf4mod install` (recommended; no repack)
  * in place    -> `rf4mod bundle patch` (same-or-smaller size)
  * repack      -> `rf4mod bundle add` / `rebuild` (updates Manifest.plist)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rf4s_modkit import (  # noqa: E402
    ident, bplist, mbundle, textdb, texture, rf4m, aibn, strings_file, res_container, gen, nlcl,
    mobj_types, script, emscript, asatk,
)

# Reference name tables are VENDORED in modding/refdata/ (self-contained share);
# a full workspace's tools/ copies act as fallbacks (rf4s_modkit.refdata).
from rf4s_modkit.refdata import refdata_path as _refdata_path
ACTOR_NAMES = _refdata_path("rf4s_actor_names.json")
ITEM_NAMES = _refdata_path("rf4s_item_names.json")

# Repo root = two levels up from tools/modding/. Bundle dir + extracted dir.
REPO = pathlib.Path(__file__).resolve().parent.parent.parent
BUNDLE_DIR = REPO / "Bundle"
# Extraction root: support both Bundle/extracted/<bundle>/... and a flat
# Bundle/<bundle>/... layout (the toolkit unpacks to either).
EXTRACTED = (BUNDLE_DIR / "extracted") if (BUNDLE_DIR / "extracted").is_dir() else BUNDLE_DIR
DEFAULT_MANIFEST = BUNDLE_DIR / "Manifest.plist"


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _resolve(path_arg: str) -> pathlib.Path:
    """Resolve a file argument: absolute, cwd-relative, under Bundle/extracted (any
    depth), or under Bundle/. Bare filenames are searched recursively in the
    extracted tree."""
    p = pathlib.Path(path_arg)
    if p.is_file():
        return p
    for base in (EXTRACTED, BUNDLE_DIR):
        cand = base / path_arg
        if cand.is_file():
            return cand
    # Bare name (no path separators): recursive search in the extracted tree. Try the
    # name as given and with a .bin suffix (most param/asset files are *.bin).
    if "/" not in path_arg and "\\" not in path_arg and EXTRACTED.is_dir():
        for pat in (path_arg, path_arg + ".bin") if not path_arg.endswith(".bin") else (path_arg,):
            matches = list(EXTRACTED.rglob(pat))
            if matches:
                return matches[0]
    return p  # let the caller raise a clear error


def _resolve_bundle(path_arg: str) -> pathlib.Path:
    p = pathlib.Path(path_arg)
    if p.is_file():
        return p
    cand = BUNDLE_DIR / path_arg
    if cand.is_file():
        return cand
    return p


def _manifest(arg: str | None) -> mbundle.Manifest:
    path = pathlib.Path(arg) if arg else DEFAULT_MANIFEST
    if not path.is_file():
        sys.exit(f"error: manifest not found: {path} (pass --manifest)")
    return mbundle.Manifest(path)


# --------------------------------------------------------------------------- #
# ident
# --------------------------------------------------------------------------- #
def cmd_ident(a):
    for f in a.files:
        p = _resolve(f)
        if not p.is_file():
            print(f"{f}: NOT FOUND")
            continue
        with open(p, "rb") as fh:
            head = fh.read(0x4000)
        ft = ident.identify(head, filename=p.name)
        print(f"{p.name}: {ft}")


# --------------------------------------------------------------------------- #
# bundle
# --------------------------------------------------------------------------- #
def cmd_bundle_list(a):
    man = _manifest(a.manifest) if a.use_manifest else None
    b = mbundle.Bundle(_resolve_bundle(a.bundle), manifest=man)
    names = b.names()
    if a.filter:
        names = [n for n in names if a.filter.lower() in n.lower()]
    for n in names:
        off, size = b.info(n)
        print(f"{size:>12}  @0x{off:<10x}  {n}")
    print(f"\n{len(names)} entr{'y' if len(names)==1 else 'ies'}"
          + (f" (filtered from {len(b)})" if a.filter else ""))


def cmd_bundle_extract(a):
    man = _manifest(a.manifest) if a.use_manifest else None
    b = mbundle.Bundle(_resolve_bundle(a.bundle), manifest=man)
    out = pathlib.Path(a.out) if a.out else pathlib.Path(pathlib.Path(a.name).name)
    b.extract(a.name, out)
    print(f"extracted {a.name} -> {out}")


def cmd_bundle_extract_all(a):
    man = _manifest(a.manifest) if a.use_manifest else None
    b = mbundle.Bundle(_resolve_bundle(a.bundle), manifest=man)
    out = pathlib.Path(a.out)
    n = b.extract_all(out, prefix=a.prefix or "",
                      progress=lambda k: print(f"  ...{k} files", end="\r"))
    print(f"\nextracted {n} files -> {out}")


def cmd_bundle_find(a):
    man = _manifest(a.manifest)
    bn, meta = man.find_file(a.name)
    if bn is None:
        print(f"{a.name}: not found in any bundle")
    else:
        print(f"{a.name}: in {bn} (size={meta['size']}, offset={meta['offset']})")


def cmd_bundle_patch(a):
    man = _manifest(a.manifest)
    bundle = _resolve_bundle(a.bundle)
    new_bytes = pathlib.Path(a.file).read_bytes()
    mbundle.patch_inplace(bundle, man, a.name, new_bytes)
    man.save()
    print(f"patched {a.name} in {bundle.name} ({len(new_bytes)} bytes) + updated manifest")


def cmd_bundle_add(a):
    man = _manifest(a.manifest)
    bundle = _resolve_bundle(a.bundle)
    new_bytes = pathlib.Path(a.file).read_bytes()
    res = mbundle.append_repack(bundle, man, {a.name: new_bytes})
    man.save()
    e = res[a.name]
    print(f"appended {a.name} to {bundle.name} (size={e['size']}, offset={e['offset']}) "
          f"+ updated manifest")


def cmd_bundle_rebuild(a):
    man = _manifest(a.manifest) if a.manifest or a.name else None
    out = pathlib.Path(a.out)
    toc = mbundle.rebuild_from_dir(a.dir, out, man, a.name)
    if man is not None:
        man.save()
    print(f"rebuilt {out} from {a.dir}: {len(toc)} files"
          + (f" + updated manifest entry {a.name!r}" if man is not None else ""))


def cmd_install(a):
    root = pathlib.Path(a.game_root)
    dest = mbundle.install_loose(root, a.name, a.file)
    print(f"installed loose file -> {dest}")
    print("  (the engine loads loose files ahead of the bundles -- no repack needed)")


# --------------------------------------------------------------------------- #
# plist (bplist <-> json)
# --------------------------------------------------------------------------- #
def cmd_plist_decode(a):
    obj = bplist.load(_resolve(a.file))
    out = json.dumps(bplist.to_jsonable(obj), ensure_ascii=False, indent=1)
    if a.out:
        pathlib.Path(a.out).write_text(out, encoding="utf-8")
        print(f"decoded {a.file} -> {a.out}")
    else:
        print(out)


def cmd_plist_encode(a):
    data = json.loads(pathlib.Path(a.json).read_text(encoding="utf-8"))
    obj = bplist.from_jsonable(data)
    pathlib.Path(a.out).write_bytes(bplist.dumps(obj))
    print(f"encoded {a.json} -> {a.out}")


# --------------------------------------------------------------------------- #
# text (TEXT archives)
# --------------------------------------------------------------------------- #
def cmd_text_show(a):
    arc = textdb.TextArchive.load(_resolve(a.file))
    lo, hi = 0, len(arc)
    if a.range:
        parts = a.range.split(":")
        lo = int(parts[0]) if parts[0] else 0
        hi = int(parts[1]) if len(parts) > 1 and parts[1] else len(arc)
    for i in range(lo, min(hi, len(arc))):
        print(f"{i:>6}  {arc.text(i, a.enc)!r}")
    print(f"\n{len(arc)} entries total")


def cmd_text_decode(a):
    out = textdb.to_json(_resolve(a.file), a.out, a.enc)
    if a.out:
        print(f"decoded {a.file} -> {a.out}")
    else:
        print(out)


def cmd_text_encode(a):
    n = textdb.from_json(a.json, a.out, a.enc)
    print(f"encoded {n} strings -> {a.out}")


def cmd_text_add(a):
    arc = textdb.TextArchive.load(_resolve(a.file))
    pad_to = getattr(a, "pad_to", None)
    if pad_to is not None and len(arc) < pad_to:
        # align to a shared id across locales (rf3mc.eng ships 1 line longer than the others, so a
        # bare append gives mismatched ids) -- pad the shorter archive with empty lines first.
        arc.entries.extend([b""] * (pad_to - len(arc)))
    new_id = len(arc)                                  # a new line's id == the (padded) length
    arc.entries.append(a.text.encode(a.enc))
    arc.save(a.out)
    print(f"appended line as id {new_id} -> {a.out}   "
          f"(retarget/insert a DIALOG to line {new_id})")


# --------------------------------------------------------------------------- #
# texture
# --------------------------------------------------------------------------- #
def cmd_texture_info(a):
    data = _resolve(a.file).read_bytes()
    print(f"{a.file}: " + texture.describe(data).replace("\n", "\n  "))


def cmd_texture_decode(a):
    try:
        out = texture.decode_to_png(_resolve(a.file), a.out, frame=a.frame, strip=a.strip)
    except texture.TextureError as e:
        sys.exit(f"error: {e}")
    what = "all frames as a strip" if a.strip else f"frame {a.frame}"
    print(f"decoded {a.file} ({what}) -> {out}")


def cmd_texture_encode(a):
    tmpl = _resolve(a.template).read_bytes()
    pngs = a.png if len(a.png) > 1 else a.png[0]
    try:
        blob = texture.encode_into(tmpl, pngs, frame=a.frame, strip=a.strip, fmt=a.fmt)
    except texture.TextureError as e:
        sys.exit(f"error: {e}")
    pathlib.Path(a.out).write_bytes(blob)
    info = texture.parse(blob)
    fmts = sorted({f["fmt_name"] for f in info["frame_list"]})
    print(f"encoded {', '.join(a.png)} into template {a.template} -> {a.out}  "
          f"({'/'.join(fmts)} {info['width']}x{info['height']}, {info['frames']} frame(s), "
          f"{len(blob):,} bytes; {_size_note(len(tmpl), len(blob))})")


def _size_note(before: int, after: int) -> str:
    """Whether a re-encoded file can go back in place with `bundle patch`."""
    if after == before:
        return "same size as the original -> bundle patch-able in place"
    if after < before:
        return f"{before - after:,} B smaller -> bundle patch-able in place"
    return f"grown by {after - before:,} B -> needs a loose override or bundle repack"


# --------------------------------------------------------------------------- #
# map ground art: stitched atlas <-> per-tile .texture files
# --------------------------------------------------------------------------- #
def _ground_ctx(a):
    """(mapground, map_name, reader, aspect, folder) for `map ground-*`: the tiles and
    the .rf4m (for the ATTR aspect) live in --dir, or wherever <MAP>.rf4m / the ground
    set's tile 0 resolves in the extracted tree."""
    from rf4s_modkit import mapground
    name = a.map[:-5] if a.map.lower().endswith(".rf4m") else a.map
    folder = pathlib.Path(a.dir) if a.dir else None
    rf = None
    if folder is None:
        cand = _resolve(name + ".rf4m")
        if cand.is_file():
            folder, rf = cand.parent, cand
        else:
            ent = mapground.texture_set_for(name)
            cand = _resolve(mapground.tile_name(ent[0] if ent else name, 0, 0))
            if cand.is_file():
                folder = cand.parent
    if folder is None or not folder.is_dir():
        sys.exit(f"error: cannot locate {name}.rf4m or its ground tiles (pass --dir)")
    if rf is None and (folder / f"{name}.rf4m").is_file():
        rf = folder / f"{name}.rf4m"
    aspect = None
    if rf is not None:
        g = rf4m.Rf4mMap.load(rf).attr_grid()
        if g:
            aspect = (g[0], g[1])
    reader = lambda fn, d=folder: (d / fn).read_bytes() if (d / fn).is_file() else None
    return mapground, name, reader, aspect, folder


def cmd_map_ground_export(a):
    mapground, name, reader, aspect, folder = _ground_ctx(a)
    if a.composite:
        res = mapground.stitch_composite(reader, name, aspect=aspect)
    else:
        res = mapground.stitch(reader, name, a.layer, aspect=aspect)
    if res is None:
        sys.exit(f"error: {name} has no ground atlas for layer {a.layer} in {folder}")
    img, cols, rows = res
    img.save(a.out)
    lay = mapground.tile_layout(reader, name, a.layer, aspect)
    extent = f"ATTR {aspect[0]}x{aspect[1]} -> {aspect[0] * 24}x{aspect[1] * 24} px" if aspect else "ATTR unknown"
    print(f"{name}: {'composite' if a.composite else f'layer {a.layer}'} = texture set "
          f"{lay['set'] if lay else '?'} ({cols}x{rows} tiles, {extent}) -> {a.out} "
          f"{img.size[0]}x{img.size[1]}" + ("" if a.composite else
                                             "   [edit, then: map ground-import]"))


def cmd_map_ground_import(a):
    mapground, name, reader, aspect, folder = _ground_ctx(a)
    from PIL import Image
    img = Image.open(a.png)
    img.load()
    try:
        tiles = mapground.unstitch(reader, name, img, a.layer, aspect, fmt=a.fmt)
    except (ValueError, texture.TextureError) as e:
        sys.exit(f"error: {e}")
    outdir = pathlib.Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    same = 0
    for fn, blob in tiles:
        (outdir / fn).write_bytes(blob)
        orig = reader(fn)
        same += 1 if orig is not None and len(blob) <= len(orig) else 0
    print(f"{name}: layer {a.layer} -> {len(tiles)} tile(s) {tiles[0][0]} .. {tiles[-1][0]} "
          f"written to {outdir}  ({same}/{len(tiles)} same size or smaller than the originals -> "
          f"bundle patch-able in place; install as loose overrides otherwise; the set name, not "
          f"the map name, is what the game loads)")


# --------------------------------------------------------------------------- #
# map (.rf4m)
# --------------------------------------------------------------------------- #
def cmd_map_info(a):
    m = rf4m.Rf4mMap.load(_resolve(a.file))
    print(f"{a.file}: {m.summary()}")
    grid = m.attr_grid()
    if grid:
        print(f"  ATTR grid: {grid[0]}x{grid[1]} cells")
    for c in m.chunks:
        print(f"    {c.tag.decode('latin1'):5} {len(c.payload):>8} B   "
              f"{rf4m.CHUNK_DESC.get(c.tag,'')}")
    # header chunks, decoded the way Map_LoadById / Map_PostLoad read them
    g = m.mgrp()
    if g is not None:
        print(f"\n  MGRP 0x{g:X}: {rf4m.mgrp_notes(g)}")
    msea = m.get_ints("MSEA")
    if msea:
        print(f"  MSEA {msea[0]} (season tag; not read by the game)")
    tints = ", ".join(f"{slot} {'default %d,%d,%d' % d if c is None else '%d,%d,%d' % c}"
                      for slot, c, d in zip(rf4m.MLIG_SLOTS, m.mlig_colors(), rf4m.MLIG_DEFAULTS))
    print(f"  MLIG tints: {tints}")
    nl = len(m.find(b"MTXN"))
    print(f"  display layers: {nl} MTXN chunk(s) -> "
          f"{ {0: 'NO ground drawn', 1: 'ground only', 2: 'ground + overlay'}.get(nl, 'only 2 used') }")
    objs = m.decode_mobj()
    if objs:
        from collections import Counter
        from rf4s_modkit import mobj_params
        recs = m.mobj_records()
        cats = Counter(o["category"] for o in objs)
        print(f"\n  MOBJ placed entities: {len(objs)}  ({dict(cats)})")
        print(f"    {'#':>3}  {'type':>5}  {'map_obj sprite':<26}  {'interaction':<9}  "
              f"{'f13':>5}  {'pos(x,y)':>12}  scale")
        n_inter = 0
        for i, o in enumerate(objs):
            tid = o["type_id"] & 0xFFFF
            f13 = recs[i][13]
            sprite = o.get("name") or mobj_types.mobj_display_name(tid) or "(no sprite)"
            note = mobj_types.mobj_note(tid)
            if note:
                sprite = f"{sprite} ({note})"
            cat, _lab, marker = mobj_params.interaction_class(tid)
            if mobj_params.is_interactible(tid, f13):
                n_inter += 1
            print(f"    {i:>3}  {o['type_id']:>5}  {sprite:<26.26}  "
                  f"{cat + ('*' if marker else ''):<9}  {('' if f13 == -1 else f13):>5}  "
                  f"{('('+str(o['pos_x'])+','+str(o['pos_y'])+')'):>12}  {o['scale']:>5.2f}")
        print(f"    {n_inter} interactible(s).  interaction* = shows the floating marker + "
              "opens a dialog (like NPCs).")
        print("    Interactibles are stored AS these MOBJ records; f13 = state/event/flag id\n"
              "          (-1 = none). Dialog text is script-driven, not in the .rf4m. NPCs are\n"
              "          placed by the schedule system, not the map file.")
    # MAPJ warps -> destination by name; building/shop entrances carry a signboard.
    warps = m.decode_mapj()
    if warps:
        from rf4s_modkit import map_names
        print(f"\n  MAPJ warps / building entrances: {len(warps)}")
        for j, w in enumerate(warps):
            nm, is_bld = map_names.describe_destination(w["dest_map"])
            tag = "  <-- BUILDING/shop entrance (signboard)" if is_bld else ""
            x0, y0, x1, y1 = w["zone_tiles"]
            extra = f"  arrive tile {w['dest_tile']}"
            if w["facing_deg"]:
                extra += f" facing {w['facing_deg']} deg"
            if w["disable_flag"] != -1:
                extra += f"  OFF while scene flag {w['disable_flag']} is set"
            print(f"    warp {j}  zone tiles ({x0},{y0})-({x1},{y1})  ->  map {w['dest_map']} = "
                  f"{nm or '(unknown)'}{extra}{tag}")
        print("    Signboards ('Bell Hotel 10:00-22:00') aren't MOBJ; each building entrance is a\n"
              "          warp to an interior room, and the sign shows that room's name. The GUI map\n"
              "          editor's 'dests' layer labels each zone with where it leads.")


def _ground_reader_for(path: pathlib.Path, dirarg=None, name=None):
    """(reader, map_name) for a .rf4m: the ground tiles live next to it (or in --dir).

    The map NAME picks the texture set, so it must be the real map name -- a working copy
    called `test.rf4m` resolves to nothing. `name` (from --map) overrides the file stem;
    without it the stem is used and a mismatch shows up as the "no ground atlas found"
    warning rather than silently passing."""
    name = (name or path.stem)
    if name.lower().endswith(".rf4m"):
        name = name[:-5]
    folder = pathlib.Path(dirarg) if dirarg else path.parent
    if not folder.is_dir():
        return None, name
    return (lambda fn, d=folder: (d / fn).read_bytes() if (d / fn).is_file() else None), name


def cmd_map_validate(a):
    """Check a .rf4m against the loader's rules (Map_LoadById): unknown tags, missing
    MGRP/ATTR/MTXN, pointer-array capacities, one record per chunk, sprite band, warps,
    and the ground atlas against the ATTR grid (tile count, engine slot ceiling, edges)."""
    from rf4s_modkit import map_names
    path = _resolve(a.file)
    m = rf4m.Rf4mMap.load(path)
    known = {i for i in range(map_names.map_count() + 1) if map_names.map_file(i)}
    reader, name = ((None, None) if getattr(a, "no_ground", False)
                    else _ground_reader_for(path, a.dir, a.map))
    findings = m.validate(known_maps=known, ground_reader=reader, map_name=name)
    if not findings:
        extra = "" if reader else "  [ground atlas NOT checked: pass --dir]"
        print(f"{a.file}: OK (no loader problems found){extra}")
        return
    for line in findings:
        print(f"  {line}")
    n_err = sum(1 for s in findings if s.startswith("ERROR"))
    print(f"{a.file}: {len(findings)} finding(s), {n_err} fatal")
    if n_err:
        sys.exit(1)


def cmd_map_resize_attr(a):
    """Resize a map's ATTR grid and print every derived artefact the resize invalidates.

    The ATTR grid is the only thing the engine sizes a map from, so changing it silently
    redefines the ground-atlas tile grid (cols = ceil(24*W/512)), the world extent and
    whether the placed entities and warp zones are still on the map."""
    path = _resolve(a.file)
    m = rf4m.Rf4mMap.load(path)
    reader, name = _ground_reader_for(path, a.dir, a.map)
    try:
        ox, oy = (int(v) for v in a.origin.split(",")) if a.origin else (0, 0)
    except ValueError:
        sys.exit("error: --origin takes two integers, e.g. --origin 4,4")
    try:
        rep = m.resize_attr_grid(a.width, a.height, fill=int(a.fill, 0), origin=(ox, oy),
                                 shift_entities=not a.no_shift, ground_reader=reader,
                                 map_name=name, dry_run=a.dry_run)
    except rf4m.Rf4mError as e:
        sys.exit(f"error: {e}")
    ow, oh = rep["old_size"]
    nw, nh = rep["new_size"]
    c = rep["cells"]
    print(f"{a.file}: ATTR {ow}x{oh} -> {nw}x{nh} at origin ({ox},{oy})  "
          f"[{'DRY RUN' if a.dry_run else 'applied'}]")
    print(f"  cells: {c['kept']} kept, {c['dropped']} dropped ({c['dropped_nonzero']} non-zero), "
          f"{c['added']} new = {c['fill']:#x}")
    print(f"  extent: {rep['extent_px']['old'][0]}x{rep['extent_px']['old'][1]} -> "
          f"{rep['extent_px']['new'][0]}x{rep['extent_px']['new'][1]} px;  ground tiles: "
          f"{rep['atlas']['old_grid'][0]}x{rep['atlas']['old_grid'][1]} -> "
          f"{rep['atlas']['new_grid'][0]}x{rep['atlas']['new_grid'][1]}"
          + ("  (COLUMN COUNT CHANGED -> every tile index moves)" if rep["atlas"]["reindexed"] else ""))
    if rep["moved"]["mobj"] or rep["moved"]["mapj"]:
        print(f"  shifted with the terrain: {len(rep['moved']['mobj'])} MOBJ, "
              f"{len(rep['moved']['mapj'])} MAPJ")
    if not reader:
        print("  (ground atlas not checked: no tiles next to the .rf4m -- pass --dir)")
    print("\n  DERIVED ARTEFACTS TO FIX:" if rep["todo"] else "\n  Nothing derived needs fixing.")
    for t in rep["todo"]:
        print(f"    * {t}")
    if rep["findings"]:
        print("\n  validate() at the new size:")
        for line in rep["findings"]:
            print(f"    {line}")
    if a.dry_run:
        print("\n  nothing written (--dry-run)")
        return
    out = pathlib.Path(a.out) if a.out else path
    m.save(out)
    print(f"\n  wrote {out}")
    if any(line.startswith("ERROR") for line in rep["findings"]):
        sys.exit(1)


def cmd_map_params(a):
    """Show what each MOBJ record field means, per type. Either --type <id> for one type,
    or a .rf4m file to annotate every placed record with its parameter meanings."""
    from rf4s_modkit import mobj_params
    SZ = mobj_params.SIZE_NAME
    if a.type_id is not None:
        tid = int(a.type_id, 0) & 0xFFFF
        role, rows = mobj_params.describe(tid)
        nm = mobj_types.mobj_name(tid) or mobj_params.name_for(tid) or "(no sprite)"
        print(f"type {tid} [{nm}]  lane: {mobj_params.lane_for(tid)[0]}\n  {role}")
        for f, sz, mean in rows:
            print(f"    f{f:<2} {SZ[sz]:<3} = {mean}")
        if not rows:
            print("    (position + type only — no tunable per-instance params)")
        return
    if not a.file:
        sys.exit("error: give a .rf4m file or --type <id>")
    m = rf4m.Rf4mMap.load(_resolve(a.file))
    for i, rec in enumerate(m.mobj_records()):
        tid = rec[0] & 0xFFFF
        role, rows = mobj_params.describe(tid)
        nm = mobj_types.mobj_name(tid) or "-"
        print(f"#{i:>3}  type {tid:>3} [{nm}]  {role}")
        for f, sz, mean in rows:
            # show only the low `sz` bytes the game actually reads
            val = rec[f] & ((1 << (8 * sz)) - 1)
            print(f"        f{f:<2} {SZ[sz]:<3} = {val:<8}  ({mean})")


def cmd_map_set(a):
    """Edit MOBJ record fields and write a new .rf4m. e.g.
    rf4mod map set MAP_DUNG_A04.rf4m 20 f0=48 f6=6144 f14=500 f15=500 -o out.rf4m"""
    m = rf4m.Rf4mMap.load(_resolve(a.file))
    rec = list(m.mobj_records()[a.index])
    for assign in a.fields:
        if "=" not in assign:
            sys.exit(f"bad field assignment {assign!r}; expected fN=VALUE")
        key, val = assign.split("=", 1)
        fi = int(key[1:]) if key.lower().startswith("f") else int(key)
        if not (0 <= fi < 16):
            sys.exit(f"field index out of range: {fi}")
        rec[fi] = int(val, 0)
    m.set_mobj_record(a.index, rec)
    out = pathlib.Path(a.out) if a.out else _resolve(a.file)
    out.write_bytes(m.build())
    print(f"set MOBJ #{a.index} -> {rec}")
    print(f"wrote {out}")


def cmd_map_attr(a):
    m = rf4m.Rf4mMap.load(_resolve(a.file))
    grid = m.attr_grid()
    if not grid:
        sys.exit("no ATTR chunk in this map")
    w, h, cells = grid
    if a.out and a.out.endswith(".png"):
        try:
            from PIL import Image
        except ImportError:
            sys.exit("PNG output needs Pillow")
        used = sorted(set(cells))
        lut = {v: int(255 * i / max(1, len(used) - 1)) for i, v in enumerate(used)}
        img = Image.frombytes("L", (w, h), bytes(lut[c] for c in cells))
        img.save(a.out)
        print(f"wrote {w}x{h} ATTR heatmap -> {a.out}")
    elif a.out:
        rows = ["\n".join(",".join(str(cells[y * w + x]) for x in range(w)) for y in range(h))]
        pathlib.Path(a.out).write_text(rows[0], encoding="utf-8")
        print(f"wrote {w}x{h} ATTR CSV -> {a.out}")
    else:
        from collections import Counter
        print(f"ATTR {w}x{h}, distinct cell values: {dict(Counter(cells))}")


# --------------------------------------------------------------------------- #
# ai (AIBN)
# --------------------------------------------------------------------------- #
def _resolve_ai(arg: str) -> pathlib.Path:
    p = _resolve(arg)
    if p.is_file():
        return p
    s = arg.lower().removeprefix("ai_").removesuffix(".bin")
    matches = sorted(EXTRACTED.rglob(f"AI_*{s}*.bin"))
    exact = [m for m in matches if m.stem.lower() == f"ai_{s}"]
    if exact:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        sys.exit(f"'{arg}' ambiguous: {', '.join(m.name for m in matches[:10])}")
    sys.exit(f"no AI script matching '{arg}'")


def cmd_ai_disasm(a):
    toks = aibn.load_tokens(_resolve_ai(a.target).read_bytes())
    if a.stats:
        c = aibn.stats(toks)
        for opid, n in c.most_common():
            print(f"0x{opid:02X} {aibn.opname(opid):<32} {n}")
        print(f"\n{sum(c.values())} statements, {len(toks)} tokens")
    elif a.raw:
        for i, t in enumerate(toks):
            kind = "op" if aibn.is_opcode(t) else "  "
            val = aibn.opname(t & aibn.MASK) if aibn.is_opcode(t) else aibn.fmt_operand(t)
            print(f"{i:>4}  0x{8+i*4:06X}  {t:08X}  {kind}  {val}")
    else:
        _utf8_stdout()
        print(aibn.disassemble(toks, annotate=a.annotate, style="flat" if a.flat else "pretty"))


def cmd_ai_ops(a):
    """Verified opcode reference (aibn_meta): one opcode, or the whole table."""
    from rf4s_modkit import aibn_meta
    _utf8_stdout()
    if a.opcode:
        opid = aibn.NAME_TO_OP.get(a.opcode)
        if opid is None:
            opid = int(a.opcode, 0)
        print(aibn_meta.describe(opid))
        return
    print("AIBN opcodes (verified 2026-09-17 from the RF4S.exe handlers; 'var<=N' = reads up to N operands)\n")
    for opid in sorted(aibn_meta.OPCODES):
        r = aibn_meta.OPCODES[opid]
        ar = r["arity"]
        ops = "; ".join(f"op{o['i']} {o['label']} [{o['units']}]" for o in r["operands"])
        uses = r.get("uses", "")
        print(f"  0x{opid:02X} {aibn.opname(opid):<30} arity {str(ar):<7} {ops}")
        print(f"       {aibn_meta.first_sentence(r['effect'])}" + (f"  (uses: {uses})" if uses != "" else ""))


def cmd_ai_actions(a):
    """The 35-entry scripted-action table reached through opcode 0x26."""
    from rf4s_modkit import aibn_meta
    _utf8_stdout()
    if a.slot is not None:
        print(aibn_meta.describe_action(a.slot))
        return
    for slot in sorted(aibn_meta.SCRIPTED_ACTIONS):
        sa = aibn_meta.SCRIPTED_ACTIONS[slot]
        print(f"  sa{slot:<3d} {sa['ida_name']:<58s} [{sa['status']}]  {aibn_meta.first_sentence(sa['effect'], 110)}")


def cmd_ai_asm(a):
    text = pathlib.Path(a.file).read_text(encoding="utf-8")
    toks = aibn.assemble(text)
    pathlib.Path(a.out).write_bytes(aibn.build(toks))
    print(f"assembled {a.file} -> {a.out} ({len(toks)} tokens)")


def cmd_ai_tokens(a):
    """Dump raw tokens as JSON (the guaranteed-exact edit primitive)."""
    toks = aibn.load_tokens(_resolve_ai(a.target).read_bytes())
    print(json.dumps(toks))


def _resolve_asatk(arg: str) -> pathlib.Path:
    p = _resolve(arg)
    if p.is_file():
        return p
    s = arg.lower().removeprefix("as_atk_").removesuffix(".bin")
    matches = sorted(EXTRACTED.rglob(f"as_atk_*{s}*.bin"))
    exact = [m for m in matches if m.stem.lower() == f"as_atk_{s}"]
    if exact:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    return p


def cmd_asatk_dump(a):
    """Canonical `<mnemonic> <operand>` listing (raw operands) -- edit it and `asatk asm` it."""
    _utf8_stdout()
    print(asatk.disassemble(_resolve_asatk(a.target).read_bytes()), end="")


def _asatk_write(events, a, src):
    blob = asatk.build(events)
    out = pathlib.Path(a.out) if a.out else src
    out.write_bytes(blob)
    for w in asatk.validate(events):
        print(f"  warning: {w}")
    print(f"wrote {out}  ({len(events)} events)")


def cmd_asatk_asm(a):
    """Assemble a listing (as written by `asatk dump`) into an as_atk_*.bin."""
    text = pathlib.Path(a.text).read_text(encoding="utf-8")
    blob = asatk.assemble(text)
    events = asatk.parse(blob, stop_at_end=False)
    _asatk_write(events, a, pathlib.Path(a.out) if a.out else pathlib.Path(a.text).with_suffix(".bin"))


def cmd_asatk_set(a):
    src = _resolve_asatk(a.target)
    events = asatk.parse(src.read_bytes(), stop_at_end=False)
    events = asatk.set_event(events, a.index, a.op, a.arg)
    _asatk_write(events, a, src)


def cmd_asatk_insert(a):
    src = _resolve_asatk(a.target)
    events = asatk.parse(src.read_bytes(), stop_at_end=False)
    if a.frame is not None:
        events = asatk.insert_at_frame(events, a.frame, a.op, a.arg)
    else:
        if a.index is None:
            sys.exit("give --index N (position in the stream) or --frame F (animation frame)")
        events = asatk.insert_event(events, a.index, a.op, a.arg)
    _asatk_write(events, a, src)


def cmd_asatk_delete(a):
    src = _resolve_asatk(a.target)
    events = asatk.parse(src.read_bytes(), stop_at_end=False)
    events = asatk.delete_event(events, a.index)
    _asatk_write(events, a, src)


def cmd_asatk_show(a):
    _utf8_stdout()
    print(asatk.render(_resolve_asatk(a.target).read_bytes()))


def cmd_asatk_summary(a):
    print(json.dumps(asatk.summary(_resolve_asatk(a.target).read_bytes()), indent=1))


def cmd_asatk_ops(a):
    print("as_atk timeline opcodes  (V=IDA-verified, D=data-inferred)\n")
    for op in sorted(asatk.OPCODES):
        mn, kind, conf, desc = asatk.OPCODES[op]
        print(f"  op{op:<3d} [{conf}] {mn:<10s} arg:{kind:<6s} {desc}")


def cmd_skill_curve(a):
    from rf4s_modkit import skillcurve
    p = _resolve(a.file)
    print(skillcurve.render(p.read_bytes(), upto=a.upto))


# ---- str: rf3ItemStrengthening (forge materials, dish ingredients, tier rows) ---------- #

def _str_table(a):
    from rf4s_modkit import strengthening
    p = _resolve(getattr(a, "file", None) or "rf3ItemStrengthening.bin")
    if not p.is_file():
        raise SystemExit(f"rf3ItemStrengthening.bin not found ({p}); pass the file explicitly")
    return p, strengthening.StrengtheningTable.load(p)


def _str_id(target: str, names: dict) -> int:
    if target.isdigit():
        return int(target)
    low = target.lower()
    hits = [i for i, n in names.items() if n.lower() == low]
    if not hits:
        hits = [i for i, n in names.items() if low in n.lower()]
    if not hits:
        raise SystemExit(f"no item named {target!r}")
    if len(hits) > 1:
        raise SystemExit(f"{target!r} is ambiguous: " + ", ".join(f"{i} {names[i]}" for i in sorted(hits)[:12]))
    return hits[0]


def _str_category_fn():
    """item id -> rf3ItemList category (byte +4), or None if the list is not extracted."""
    p = _resolve("rf3ItemList.bin")
    if not p.is_file():
        return None
    t = nlcl.NlclTable.load(p)
    return lambda i: t.get(i, 4, "u8") if 0 <= i < t.entry_count else None


def cmd_str_show(a):
    from rf4s_modkit import strengthening
    p, t = _str_table(a)
    names = strengthening.load_item_names()
    for target in a.item:
        print(t.render(_str_id(target, names), names))
        print()


def cmd_str_list(a):
    from rf4s_modkit import strengthening
    p, t = _str_table(a)
    names = strengthening.load_item_names()
    print(t.render_list(names, nonzero=not a.all, field=a.field, group=a.group,
                        flag=a.flag, limit=a.limit))


def cmd_str_flags(a):
    from rf4s_modkit import strengthening
    p, t = _str_table(a)
    print(t.flag_report(strengthening.load_item_names(), _str_category_fn()))


def cmd_str_specials(a):
    from rf4s_modkit import strengthening
    p, t = _str_table(a)
    print(t.render_specials(strengthening.load_item_names()))


def cmd_str_fields(a):
    from rf4s_modkit import strengthening
    print(strengthening.render_field_reference())


def cmd_str_dump(a):
    from rf4s_modkit import strengthening
    p, t = _str_table(a)
    names = strengthening.load_item_names()
    text = t.to_json(names, nonzero=not a.all) if a.json else t.to_csv(names)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
        print(f"dumped {len(t)} records -> {a.out}")
    else:
        print(text)


def cmd_str_set(a):
    from rf4s_modkit import strengthening
    p, t = _str_table(a)
    names = strengthening.load_item_names()
    rid = _str_id(a.item, names)
    for assign in a.set:
        key, val = assign.split("=", 1)
        t.set(rid, key, int(val, 0))
    out = pathlib.Path(a.out) if a.out else p
    t.save(out)
    print(f"#{rid} {t.label(rid, names)}: " + ", ".join(a.set) + f" -> {out}")


CHAR_NAMES = _refdata_path("char_names.json")


def _char_names():
    if CHAR_NAMES.is_file():
        return {int(k): v for k, v in json.loads(CHAR_NAMES.read_text(encoding="utf-8")).items()}
    return {}   # refdata_path already tried every layout


def _item_name_fn():
    if ITEM_NAMES.is_file():
        names = json.loads(ITEM_NAMES.read_text(encoding="utf-8"))
        return lambda i: names.get(str(i), "")
    return None


def _gift_file(target: str) -> tuple[pathlib.Path, int]:
    """Resolve a gift target: file path, bare stem, number (1..27), or character name."""
    p = _resolve(target)
    if p.is_file():
        num = int(p.stem[13:15]) if p.stem[13:15].isdigit() else 0
        return p, num
    if target.isdigit():
        num = int(target)
    else:  # character name -> file number (only chars 1..27 have gift tables; names can
           # collide with alternate ids like 308, so restrict to the gift range)
        cn = {v.lower(): k for k, v in _char_names().items() if 1 <= k <= 27}
        num = cn.get(target.lower(), 0)
    if num:
        cand = _resolve(f"rf3PresentNpc{num:02d}.bin")
        if cand.is_file():
            return cand, num
    return p, 0


def _gift_categories():
    """Load rf3PresentCategory (archive 14850) -> the 21 shared cross-ref item groups, or None."""
    from rf4s_modkit import gifts
    p = _resolve("rf3PresentCategory.bin")
    return gifts.load_categories(p.read_bytes()) if p.is_file() else None


def _npc_id(token: str) -> int:
    """NPC id (0..47) from a number or a character name (refdata char_names.json)."""
    s = str(token).strip()
    if s.lstrip("+").isdigit() or s.lower().startswith("0x"):
        return int(s, 0)
    cn = {v.lower(): k for k, v in _char_names().items() if 0 <= k < 48}
    if s.lower() in cn:
        return cn[s.lower()]
    sys.exit(f"error: unknown NPC {token!r} (use an id 0..47 or a character name)")


def _write_out(a, p: pathlib.Path, data: bytes) -> pathlib.Path:
    """-o/--out or overwrite the resolved file (the convention of `param set` / `str set`)."""
    out = pathlib.Path(a.out) if getattr(a, "out", None) else p
    out.write_bytes(data)
    return out


def _schedule_file(a) -> pathlib.Path:
    p = _resolve(a.file) if getattr(a, "file", None) else _resolve("rf3Schedule.bin")
    if not p.is_file():
        sys.exit("error: rf3Schedule.bin not found (pass --file)")
    return p


def _schedule_spots():
    """rf3ScheduleID.bin spots (for resolving slice kinds to rooms), or None when absent."""
    from rf4s_modkit import schedule
    p = _resolve("rf3ScheduleID.bin")
    return schedule.load_spots(p.read_bytes()) if p.is_file() else None


def _schedule_report(sc, npc: int, state: int, spots) -> None:
    from rf4s_modkit import schedule, map_names
    lst = sc.get(npc, state) or []
    who = _char_names().get(npc, "")
    print(f"npc {npc} {who} state {state} ({schedule.STATE_NAMES.get(state, '?')}): {len(lst)} stops")
    for k, s in enumerate(lst):
        fl = "  [random depart]" if s.flags & 1 else ""
        print(f"    {k:>2}  {schedule.slot_to_time(s.slot)}  spot {s.spot:>3}  "
              f"{schedule.describe_kind(s.spot, spots, map_names.map_name)}{fl}")


def cmd_schedule_show(a):
    from rf4s_modkit import schedule, map_names
    _utf8_stdout()
    p = _schedule_file(a)
    data = p.read_bytes()
    spots = _schedule_spots()
    npc = _npc_id(a.npc) if a.npc is not None else None
    state = schedule.state_code(a.state) if a.state is not None else None
    if a.id is not None:                     # legacy: the Nth schedule in file order
        cells = schedule.Schedule.parse(data).ordered_cells()
        i = int(a.id, 0)
        if not (0 <= i < len(cells)):
            sys.exit(f"error: schedule {i} out of range (0..{len(cells) - 1})")
        (npc, state), _lst = cells[i]
    limit = None if (npc is not None or state is not None) else a.limit
    print(schedule.render(data, name_fn=map_names.map_name, limit=limit, spots=spots,
                          npc_name_fn=lambda n: _char_names().get(n, ""),
                          only_npc=npc, only_state=state))


def cmd_schedule_decode(a):
    from rf4s_modkit import schedule, map_names
    p = _schedule_file(a)
    sc = schedule.Schedule.parse(p.read_bytes())
    text = sc.dumps(spots=None if a.bare else _schedule_spots(), name_fn=map_names.map_name)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
        print(f"decoded {p.name}: {len(sc.cells)} schedules -> {a.out}")
    else:
        _utf8_stdout()
        print(text)


def cmd_schedule_encode(a):
    from rf4s_modkit import schedule
    src = pathlib.Path(a.json)
    sc = schedule.Schedule.loads(src.read_text(encoding="utf-8"))
    out = pathlib.Path(a.out) if a.out else src.with_suffix(".bin")
    out.write_bytes(sc.build())
    print(f"encoded {len(sc.cells)} schedules, {sum(len(v) for v in sc.cells.values())} slices -> {out}")


def cmd_schedule_set(a):
    from rf4s_modkit import schedule
    _utf8_stdout()
    p = _schedule_file(a)
    sc = schedule.Schedule.parse(p.read_bytes())
    npc, state = _npc_id(a.npc), schedule.state_code(a.state)
    try:
        sc.set_slice(npc, state, int(a.index, 0),
                     slot=None if a.time is None else schedule.time_to_slot(a.time),
                     flags=None if a.flags is None else int(a.flags, 0),
                     spot=None if a.spot is None else int(a.spot, 0))
    except schedule.ScheduleError as e:
        sys.exit(f"error: {e}")
    out = _write_out(a, p, sc.build())
    _schedule_report(sc, npc, state, _schedule_spots())
    print(f"wrote {out}")


def cmd_schedule_add(a):
    from rf4s_modkit import schedule
    _utf8_stdout()
    p = _schedule_file(a)
    sc = schedule.Schedule.parse(p.read_bytes())
    npc, state = _npc_id(a.npc), schedule.state_code(a.state)
    try:
        k = sc.add_slice(npc, state, schedule.time_to_slot(a.time), int(a.spot, 0), int(a.flags, 0))
    except schedule.ScheduleError as e:
        sys.exit(f"error: {e}")
    out = _write_out(a, p, sc.build())
    print(f"inserted stop #{k}")
    _schedule_report(sc, npc, state, _schedule_spots())
    print(f"wrote {out}")


def cmd_schedule_remove(a):
    from rf4s_modkit import schedule
    _utf8_stdout()
    p = _schedule_file(a)
    sc = schedule.Schedule.parse(p.read_bytes())
    npc, state = _npc_id(a.npc), schedule.state_code(a.state)
    try:
        gone = sc.remove_slice(npc, state, int(a.index, 0))
    except schedule.ScheduleError as e:
        sys.exit(f"error: {e}")
    out = _write_out(a, p, sc.build())
    print(f"removed {schedule.slot_to_time(gone.slot)} spot {gone.spot}")
    _schedule_report(sc, npc, state, _schedule_spots())
    print(f"wrote {out}")


def cmd_schedule_spots(a):
    from rf4s_modkit import schedule, map_names
    _utf8_stdout()
    spots = _schedule_spots()
    if not spots:
        sys.exit("error: rf3ScheduleID.bin not found")
    kinds = [int(a.kind, 0)] if a.kind is not None else range(schedule.MAX_KIND + 1)
    for k in kinds:
        recs = schedule.kind_records(k)
        print(f"spot kind {k}: records {recs.start}..{recs.stop - 1}")
        for r in recs:
            s = spots[r]
            print(f"    rec {r:>4}  room {s.room:>3} {map_names.map_name(s.room) or '':<28} "
                  f"@{s.x},{s.y}  facing {s.facing:>3}  action {s.action:>2}  wander {s.wander:>2}  "
                  f"weight {s.weight}  flags {s.flags:#x}")


def cmd_gift_show(a):
    from rf4s_modkit import gifts
    _utf8_stdout()
    p, num = _gift_file(a.target)
    if not p.is_file():
        sys.exit(f"error: no gift table for '{a.target}'")
    who = _char_names().get(num, "?")
    print(f"# {p.name}  = char {num} {who}  (archive {14850 + num})")
    print(gifts.render(p.read_bytes(), name_fn=_item_name_fn(), categories=_gift_categories()))


def cmd_gift_categories(a):
    from rf4s_modkit import gifts
    _utf8_stdout()
    cats = _gift_categories()
    if not cats:
        sys.exit("error: rf3PresentCategory.bin not found")
    nf = _item_name_fn() or (lambda i: str(i))
    print(f"# rf3PresentCategory (archive 14850): {len(cats)} shared gift categories")
    for idx, grp in enumerate(cats):
        ids = gifts.category_items(idx, cats)
        print(f"cat {idx:>2} ({len(ids)}): " + ", ".join(nf(i) or str(i) for i in ids))


def cmd_gift_monster(a):
    from rf4s_modkit import montame
    _utf8_stdout()
    p = _resolve("rf3MonsterPresent.bin")
    if not p.is_file():
        sys.exit("error: rf3MonsterPresent.bin not found")
    nf = _item_name_fn() or (lambda i: str(i))
    data = p.read_bytes()
    sp_fn = None
    if a.species is not None:
        sid = int(a.species, 0)
        pr = montame.prefs(data, sid)
        who = _char_names().get(sid, "")
        print(f"species {sid} {who}: " +
              (", ".join(f"{nf(i) or i} (+{b} tame)" for i, b in pr) or "(no preferences)"))
    else:
        print(montame.render(data, name_fn=lambda i: nf(i) or str(i),
                             species_name_fn=lambda s: _char_names().get(s, "")))


def cmd_gift_list(a):
    from rf4s_modkit import gifts
    _utf8_stdout()
    chars, nf = _char_names(), _item_name_fn()
    for num in range(1, 28):
        p = _resolve(f"rf3PresentNpc{num:02d}.bin")
        if not p.is_file():
            continue
        g = gifts.parse(p.read_bytes())
        loved = [(nf(e.value) if nf else e.value) for e in g[0]["loved"] if e.kind == "item"] if g else []
        print(f"{num:>2} {chars.get(num, '?'):<16} loves: {', '.join(map(str, loved)) or '(none)'}")


def _gift_item_id(token: str) -> int:
    from rf4s_modkit import strengthening
    return _str_id(token, strengthening.load_item_names())


def _gift_target(token: str) -> tuple[str, int]:
    """'cat:N' -> cross-ref to gift category N ; 'range:N' -> item-id range tag N
    (see `gift categories` / gifts.ITEM_RANGE_TABLE) ; anything else = item id or item name."""
    low = token.lower()
    for pre, kind in (("cat:", "xref"), ("category:", "xref"), ("xref:", "xref"), ("range:", "category")):
        if low.startswith(pre):
            return kind, int(token[len(pre):], 0)
    return "item", _gift_item_id(token)


def _gift_table(a):
    from rf4s_modkit import gifts
    p, num = _gift_file(a.npc)
    if not p.is_file():
        sys.exit(f"error: no gift table for '{a.npc}'")
    return p, num, gifts.GiftTable.parse(p.read_bytes())


def _gift_report(p, num, t, out, target=None) -> None:
    from rf4s_modkit import gifts
    nf = _item_name_fn() or (lambda i: "")
    print(f"# {p.name} = char {num} {_char_names().get(num, '?')}: "
          + ", ".join(f"{tier} {len(t.tier(tier))}" for tier in gifts.TIERS))
    if target is not None:
        kind, val = target
        hits = t.find(kind, val)
        label = (f"{val} {nf(val)}".strip() if kind == "item" else f"{kind} #{val}")
        if hits:
            for _g, tier, k in hits:
                e = t.tier(tier)[k]
                fp = gifts.entry_fp(e, tier)
                sig = "  (signature/hated)" if tier == "disliked" and e.code == gifts.SIGNATURE_DISLIKE_CODE else ""
                print(f"  {label}: {tier} #{k}, code {e.code:#06x} = {fp:+d} FP{sig}")
        else:
            print(f"  {label}: neutral (+{gifts.NEUTRAL_FP} FP, unlisted)")
    print(f"wrote {out}")


def cmd_gift_set(a):
    """Move an item (or a cat:/range: target) to loved / liked / disliked / neutral."""
    from rf4s_modkit import gifts
    _utf8_stdout()
    p, num, t = _gift_table(a)
    kind, val = _gift_target(a.item)
    tier = a.tier.lower()
    if tier not in ("loved", "liked", "disliked", "neutral"):
        sys.exit("error: tier must be loved, liked, disliked or neutral")
    try:
        if tier == "neutral":
            n = t.remove(kind, val, a.group)
            if not n:
                print("(target was not listed; nothing removed)")
        elif kind == "item":
            t.set_item(val, tier, fp=a.fp, signature=a.signature, group=a.group)
        else:
            if tier == "disliked":
                code = gifts.SIGNATURE_DISLIKE_CODE if a.signature else gifts.GENERIC_DISLIKE_CODE
            else:
                code = gifts.DEFAULT_FP[tier] if a.fp is None else a.fp
            t.add(tier, gifts.Entry(kind, val, code), a.group)
        out = _write_out(a, p, t.build())
    except gifts.GiftError as e:
        sys.exit(f"error: {e}")
    _gift_report(p, num, t, out, (kind, val))


def cmd_gift_remove(a):
    a.tier = "neutral"
    a.fp = None
    a.signature = False
    cmd_gift_set(a)


def cmd_gift_signature(a):
    """Make an item the NPC's ONE signature/hated dislike (-10 FP, unique dialogue)."""
    from rf4s_modkit import gifts
    _utf8_stdout()
    p, num, t = _gift_table(a)
    item = _gift_item_id(a.item)
    try:
        t.set_signature(item, group=a.group, demote_others=not a.keep_others)
        out = _write_out(a, p, t.build())
    except gifts.GiftError as e:
        sys.exit(f"error: {e}")
    _gift_report(p, num, t, out, ("item", item))


def _montame_file(a):
    p = _resolve(a.file) if getattr(a, "file", None) else _resolve("rf3MonsterPresent.bin")
    if not p.is_file():
        sys.exit("error: rf3MonsterPresent.bin not found")
    return p


def _species_id(token: str) -> int:
    """Monster species id 48..253 from a number or a monster name (refdata char_names.json)."""
    s = str(token).strip()
    if s.lstrip("+").isdigit() or s.lower().startswith("0x"):
        return int(s, 0)
    hits = sorted(k for k, v in _char_names().items() if v.lower() == s.lower() and 48 <= k <= 253)
    if not hits:
        sys.exit(f"error: unknown species {token!r} (use an id 48..253 or a monster name)")
    return hits[0]


def _montame_report(buf, sid, out) -> None:
    from rf4s_modkit import montame
    nf = _item_name_fn() or (lambda i: "")
    who = _char_names().get(sid, "")
    print(f"species {sid} {who}: " + ", ".join(
        f"slot {k}: {'(empty)' if not item else f'{item} {nf(item)}'.strip()}"
        + (f" +{bonus}" if item else "") for k, (item, bonus) in enumerate(montame.slots(buf, sid))))
    print(f"wrote {out}")


def cmd_gift_monster_set(a):
    """Set one of a species' 4 tame-food slots (slot 'auto' = its existing slot or the first free)."""
    from rf4s_modkit import montame
    _utf8_stdout()
    p = _montame_file(a)
    buf = bytearray(p.read_bytes())
    sid = _species_id(a.species)
    item = _gift_item_id(a.item)
    try:
        if str(a.slot).lower() == "auto":
            k = montame.set_item(buf, sid, item, int(a.bonus, 0))
        else:
            k = int(a.slot, 0)
            montame.set_pref(buf, sid, k, item, int(a.bonus, 0))
    except (IndexError, ValueError) as e:
        sys.exit(f"error: {e}")
    out = _write_out(a, p, bytes(buf))
    print(f"slot {k} set")
    _montame_report(buf, sid, out)


def cmd_gift_monster_clear(a):
    """Empty a tame-food slot (or every slot holding --item)."""
    from rf4s_modkit import montame
    _utf8_stdout()
    p = _montame_file(a)
    buf = bytearray(p.read_bytes())
    sid = _species_id(a.species)
    try:
        if a.slot.lower() == "item":
            if not montame.remove_item(buf, sid, _gift_item_id(a.item)):
                sys.exit("error: that item is not in any slot of this species")
        else:
            montame.clear_pref(buf, sid, int(a.slot, 0))
    except (IndexError, ValueError) as e:
        sys.exit(f"error: {e}")
    out = _write_out(a, p, bytes(buf))
    _montame_report(buf, sid, out)


# --- route (rf3route.bin TRCS nav graph + rf3RouteResult.bin next-hop matrix) --
def _route_graph(a):
    from rf4s_modkit import route
    p = _resolve(a.file) if getattr(a, "file", None) else _resolve("rf3route.bin")
    if not p.is_file():
        sys.exit("error: rf3route.bin not found")
    return p, route.RouteGraph.parse(p.read_bytes())


def _route_result(a, graph):
    from rf4s_modkit import route
    p = _resolve(a.result) if getattr(a, "result", None) else _resolve("rf3RouteResult.bin")
    if not p.is_file():
        sys.exit("error: rf3RouteResult.bin not found")
    return p, route.RouteResult.parse(p.read_bytes(), node_count=len(graph.nodes))


def _route_node(token: str, graph) -> int:
    """node id, or 'room:k' / 'room' (its first node)."""
    from rf4s_modkit import route
    s = str(token)
    if s.lower().startswith("room:") or ":" in s:
        body = s.split(":", 1)[1] if s.lower().startswith("room:") else s
        room, _, k = body.partition(":")
        try:
            return graph.node_index(int(room, 0), int(k or "0", 0))
        except route.RouteError as e:
            sys.exit(f"error: {e}")
    return int(s, 0)


def cmd_route_info(a):
    from rf4s_modkit import route, map_names
    _utf8_stdout()
    p, g = _route_graph(a)
    print(route.describe(g, name_fn=map_names.map_name))


def cmd_route_decode(a):
    from rf4s_modkit import map_names
    p, g = _route_graph(a)
    text = g.dumps(name_fn=map_names.map_name)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
        print(f"decoded {p.name}: {len(g.nodes)} nodes / {len(g.edges)} edges -> {a.out}")
    else:
        _utf8_stdout()
        print(text)


def cmd_route_encode(a):
    from rf4s_modkit import route
    src = pathlib.Path(a.json)
    try:
        g = route.RouteGraph.from_json(json.loads(src.read_text(encoding="utf-8")))
        data = g.build()
    except route.RouteError as e:
        sys.exit(f"error: {e}")
    out = pathlib.Path(a.out) if a.out else src.with_suffix(".bin")
    out.write_bytes(data)
    print(f"encoded {len(g.nodes)} nodes / {len(g.edges)} edges -> {out}")
    if a.result:
        rr = route.RouteResult.compute(g)
        pathlib.Path(a.result).write_bytes(rr.build())
        print(f"regenerated next-hop matrix -> {a.result} ({rr.rows} x {rr.stride} B)")


def cmd_route_path(a):
    from rf4s_modkit import route, map_names
    _utf8_stdout()
    p, g = _route_graph(a)
    rp, rr = _route_result(a, g)
    src, dst = _route_node(a.src, g), _route_node(a.dst, g)
    try:
        hops, cost = rr.path(g, src, dst)
    except route.RouteError as e:
        sys.exit(f"error: {e}")
    print(f"path {src} -> {dst}: {len(hops) - 1} hops, total cost {cost}")
    for n, c in hops:
        nd = g.nodes[n]
        print(f"    node {n:>3}  room {nd.room:>3} {map_names.map_name(nd.room) or '':<28} @{nd.x},{nd.y}"
              + (f"  (+{c})" if c else ""))


def cmd_route_rebuild_result(a):
    from rf4s_modkit import route
    p, g = _route_graph(a)
    rr = route.RouteResult.compute(g)
    out = pathlib.Path(a.out) if a.out else _resolve("rf3RouteResult.bin")
    out.write_bytes(rr.build())
    print(f"next-hop matrix for {len(g.nodes)} nodes -> {out} ({rr.rows} x {rr.stride} B; "
          f"shortest total cost, lowest edge index on ties)")


# --- monster (rf3NpcParam.bin template DB, archive 14812) --------------------
def _monster_file(arg):
    return _resolve(arg) if arg else _resolve("rf3NpcParam.bin")


def _monster_id(token, species):
    """id number, or monster name -> char_id (None if unresolvable)."""
    if token is None:
        return None
    s = str(token)
    if s.lstrip("+").isdigit() or s.lower().startswith("0x"):
        return int(s, 0)
    low = s.lower()
    for cid, info in species.items():
        if (info.get("name", "") or "").lower() == low:
            return cid
    return None


def cmd_monster_show(a):
    from rf4s_modkit import monster
    _utf8_stdout()
    p = _monster_file(a.file)
    if not p.is_file():
        sys.exit(f"error: {p} not found")
    t = nlcl.NlclTable.load(p)
    sp, inm = monster.load_species(), monster.load_item_names()
    cid = _monster_id(a.who, sp)
    if cid is None:
        sys.exit(f"error: unknown monster '{a.who}' (give a char_id number or exact name)")
    print(monster.render(t, cid, sp, inm))


def cmd_monster_list(a):
    from rf4s_modkit import monster
    _utf8_stdout()
    t = nlcl.NlclTable.load(_monster_file(a.file))
    lo, hi = 48, 253
    if a.range:
        lo, hi = (int(x) for x in a.range.split("-"))
    print(monster.render_list(t, monster.load_species(), lo, hi))


def cmd_monster_free(a):
    from rf4s_modkit import monster
    t = nlcl.NlclTable.load(_monster_file(a.file))
    ids = monster.free_slots(t)
    print("cut/unused field-monster ids (data-only new monster, no EXE patch): "
          + ", ".join(map(str, ids)))


def cmd_monster_set(a):
    from rf4s_modkit import monster
    _utf8_stdout()
    p = _monster_file(a.file)
    t = nlcl.NlclTable.load(p)
    sp = monster.load_species()
    cid = _monster_id(a.record, sp)
    if cid is None:
        sys.exit(f"error: unknown monster '{a.record}'")
    for assign in a.set:
        key, val = assign.split("=", 1)
        monster.set_field(t, cid, key.strip(), int(val, 0))
    out = pathlib.Path(a.out) if a.out else p
    monster.save(t, out)
    print(monster.render(t, cid, sp, monster.load_item_names()))
    print(f"wrote {out}")


def cmd_monster_clone(a):
    from rf4s_modkit import monster
    _utf8_stdout()
    p = _monster_file(a.file)
    t = nlcl.NlclTable.load(p)
    monster.clone_record(t, a.src, a.dst)
    out = pathlib.Path(a.out) if a.out else p
    monster.save(t, out)
    print(f"cloned monster template {a.src} -> slot {a.dst}")
    print(monster.render(t, a.dst, monster.load_species(), monster.load_item_names()))
    print(f"wrote {out}")


def cmd_monster_new(a):
    """End-to-end DATA-ONLY new monster (no EXE patch): clone a base template into a cut
    char_id slot, apply field overrides, name it in the rf3TxtNpc table, optionally add it
    to an encounter table, and package all loose-override files (+ verify each re-parses)."""
    from rf4s_modkit import monster, textdb
    from rf4s_modkit import gen as genmod
    _utf8_stdout()
    outdir = pathlib.Path(a.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    sp, inm = monster.load_species(), monster.load_item_names()

    # 1) template: clone base -> free (or chosen) cut slot, apply overrides
    np = _monster_file(a.npc_param)
    if not np.is_file():
        sys.exit(f"error: {np} not found")
    t = nlcl.NlclTable.load(np)
    src = _monster_id(a.src, sp)
    if src is None:
        sys.exit(f"error: unknown base monster '{a.src}'")
    if a.slot is not None:
        slot = a.slot
    else:
        free = monster.free_slots(t)
        if not free:
            sys.exit("error: no known free cut slot — pass --slot")
        slot = free[0]
    if not (0 <= slot < t.entry_count):   # validate before writing anything (no partial mod)
        sys.exit(f"error: --slot {slot} out of range for rf3NpcParam (0..{t.entry_count - 1})")
    monster.clone_record(t, src, slot)
    for assign in (a.set or []):
        k, v = assign.split("=", 1)
        monster.set_field(t, slot, k.strip(), int(v, 0))
    monster.save(t, outdir / "rf3NpcParam.bin")
    written = ["rf3NpcParam.bin"]

    # 2) name in the rf3TxtNpc name table (index == char_id)
    named = []
    for loc in (a.locales.split(",") if a.locales else ["eng"]):
        cand = _resolve(f"rf3TxtNpc_split2_1.{loc.strip()}")
        if not cand.is_file():
            continue
        arc = textdb.TextArchive.load(cand)
        if slot >= len(arc):          # name table shorter than the slot -> skip (don't crash)
            continue
        arc.set_text(slot, a.name)
        arc.save(outdir / cand.name)
        written.append(cand.name); named.append(loc.strip())

    # 3) optional: add to an encounter (repoint the first spawn found -> new id)
    enc_note = "(skipped)"
    if a.encounter:
        parts = a.encounter.split(":")
        gfile = _resolve(parts[0])
        if not gfile.is_file():
            sys.exit(f"error: encounter file {parts[0]} not found")
        want_gate = int(parts[1]) if len(parts) > 1 else None
        g = genmod.GenTable.load(gfile)
        target = next(((pi, ei, e) for pi, ei, e in g.all_entries()
                       if e.spawns and (want_gate is None or ei == want_gate)), None)
        if target is None:
            sys.exit("error: no spawn slot to repoint in that Gen file")
        pi, ei, e = target
        old = e.spawns[0].monster_id
        g.set_spawn_monster(e.spawns[0], slot)
        g.save(outdir / gfile.name)
        written.append(gfile.name)
        enc_note = f"{gfile.name} gate[{ei}] spawn0: {old} -> {slot}"

    # 4) verify every written file still re-parses with its loader
    problems = []
    for fn in written:
        p = outdir / fn
        try:
            if fn == "rf3NpcParam.bin":
                nlcl.NlclTable.load(p)
            elif fn.startswith("Gen"):
                genmod.GenTable.load(p)
            else:
                textdb.TextArchive.load(p)
        except Exception as e:  # noqa: BLE001 - report any parse failure
            problems.append(f"{fn}: {e}")

    print(f"# New monster '{a.name}'  (char_id {slot}, cloned from {src} "
          f"{monster.species_name(src, sp) or ''})\n")
    print(monster.render(t, slot, {**sp, slot: {"name": a.name}}, inm))
    print("\nnamed locales :", ", ".join(named) or "(none — no rf3TxtNpc found)")
    print("encounter     :", enc_note)
    print("verify        :", "all files re-parse OK" if not problems
          else "FAILED: " + "; ".join(problems))
    print(f"\nwrote {len(written)} loose-override file(s) to {outdir}:")
    for fn in written:
        print("   ", fn)
    print("\ninstall: drop these into your loose-file override folder (loose files win over "
          "the bundle).")


def cmd_skill_family(a):
    from rf4s_modkit import skillcurve
    if a.skill_id is not None:
        sid = int(a.skill_id, 0)
        arc = skillcurve.archive_for_skill(sid)
        print(f"skill {sid} -> XP-curve archive {arc} -> {skillcurve.file_for_skill(sid)}.bin")
        return
    print("skill-id -> XP-curve archive -> file (Skill_GetLevelTable, +0x83E60):")
    fams = {skillcurve.DEFAULT_ARCHIVE: ["default (weapons/magic/Defense/Walking/...)"]}
    for sk, arc in sorted(skillcurve.FAMILY_ARCHIVE.items()):
        fams.setdefault(arc, []).append(str(sk))
    for arc in sorted(fams):
        f = skillcurve.ARCHIVE_FILE.get(arc, "?")
        print(f"  {arc}  {f + '.bin':<28s} skills {', '.join(fams[arc])}")
    print("\n(archive<->file pairing inferred from name-lead + id order; not byte-confirmed)")


def cmd_skill_set(a):
    """Edit a skill XP curve: `skill set FILE LEVEL XP` sets one level's XP-to-next,
    `--scale PCT` multiplies every level (both may be combined; --scale runs first)."""
    from rf4s_modkit import skillcurve
    p = _resolve(a.file)
    buf = bytearray(p.read_bytes())
    if buf[:4] != b"NLCL" or len(buf) < skillcurve.HEADER + 4 * skillcurve.REAL_LEVELS:
        sys.exit(f"{p.name} is not a skill XP curve (rf3ParamSkillExp*.bin)")
    if len(a.level_xp) not in (0, 2):
        sys.exit("give LEVEL XP (two numbers) or nothing with --scale")
    if not a.level_xp and a.scale is None:
        sys.exit("nothing to change: give LEVEL XP and/or --scale PCT")
    before = skillcurve.parse(bytes(buf))
    try:
        if a.scale is not None:
            skillcurve.scale_curve(buf, a.scale)
        if a.level_xp:
            skillcurve.set_level_xp(buf, int(a.level_xp[0], 0), int(a.level_xp[1], 0))
    except (ValueError, IndexError) as e:
        sys.exit(f"skill set: {e}")
    after = skillcurve.parse(bytes(buf))
    out = pathlib.Path(a.out)
    out.write_bytes(bytes(buf))
    changed = [i for i in range(len(after)) if after[i] != before[i]]
    if a.scale is not None:
        print(f"scaled every level by {a.scale:g}%: total XP to level 100 {sum(before)} -> {sum(after)}")
    for lvl in changed[:12]:
        print(f"  level {lvl:>3}: {before[lvl]} -> {after[lvl]}")
    if len(changed) > 12:
        print(f"  ... {len(changed) - 12} more levels changed")
    print(f"cap-bracket table[99] = {after[99]}   (uncapped skills keep paying this past 99)")
    print(f"wrote {out}")


# --------------------------------------------------------------------------- #
# script (rf3.mc cutscene / event Script-VM bytecode)
# --------------------------------------------------------------------------- #
def _dialog_fn(text_arg):
    if not text_arg:
        return None
    ta = textdb.TextArchive.load(_resolve(text_arg))
    return lambda i: ta.text(i)


def cmd_script_info(a):
    c = script.Container(_resolve(a.file).read_bytes())
    sc, clean, stmts, dl = script.coverage(c)
    print(f"MYCF rf3.mc: {len(c.banks)} banks ({c.n_primary} primary + {c.n_tail} tail), ver {c.ver:#x}")
    print(f"scenes={sc}  clean={clean} ({100*clean/sc:.1f}%)  statements={stmts}  dialog-lines={dl}")
    print("round-trip:", "OK" if c.build() == bytes(c.data) else "MISMATCH")


def cmd_script_disasm(a):
    c = script.Container(_resolve(a.file).read_bytes())
    banks = [a.bank] if a.bank is not None else None
    out = script.dump_text(c, dialog=_dialog_fn(a.text), banks=banks, friendly=a.friendly)
    if a.out:
        pathlib.Path(a.out).write_text(out, encoding="utf-8")
        print(f"wrote {a.out} ({out.count(chr(10))} lines)")
    else:
        sys.stdout.buffer.write(out.encode("utf-8", "replace"))
        sys.stdout.buffer.write(b"\n")


def cmd_script_find(a):
    c = script.Container(_resolve(a.file).read_bytes())
    dlg = _dialog_fn(a.text)
    if dlg is None:
        sys.exit("error: --text <rf3mc.locale> is required to search dialogue")
    hits = script.find_scenes_with_dialog(c, a.query, dlg)
    for bk, sc, ids in hits[: a.limit]:
        sys.stdout.buffer.write(
            (f"bank {bk.index} ({bk.kind}) type {sc.action_type} entry 0x{sc.entry_pc:04x}"
             f"  lines={ids}\n").encode("utf-8", "replace"))
    print(f"\n{len(hits)} scene(s) match {a.query!r}")


def cmd_script_set_dialog(a):
    c = script.Container(_resolve(a.file).read_bytes())
    c.banks[a.bank].set_dialog_id(int(a.pc, 0), a.line)
    pathlib.Path(a.out).write_bytes(c.build())
    print(f"bank {a.bank} pc {a.pc} -> dialogue line {a.line}; wrote {a.out}")


def cmd_script_set_arg(a):
    c = script.Container(_resolve(a.file).read_bytes())
    c.banks[a.bank].set_action_arg(int(a.pc, 0), a.index, a.value)
    pathlib.Path(a.out).write_bytes(c.build())
    print(f"bank {a.bank} pc {a.pc} arg[{a.index}] = {a.value}; wrote {a.out}")


def cmd_script_set_val(a):
    c = script.Container(_resolve(a.file).read_bytes())
    bank = c.banks[a.bank]
    pc = int(a.pc, 0)
    st = script.decode_statement(bank.data, pc)
    if st is not None and st.op in (0xFFF4, 0xFFF5):
        # PROMPT_CHOICE / PROMPT_CHOICE_FORCED: --index selects which option to retarget, --value
        # is the new rf3mc string id it displays (the choice analog of set-dialog). These items are
        # direct u32 string ids, not guard/value-expr literals, so they need their own edit path.
        bank.set_choice_item(pc, a.index, a.value)
        print(f"bank {a.bank} pc {a.pc} {st.mnem} option[{a.index}] -> line id {a.value}; wrote {a.out}")
        pathlib.Path(a.out).write_bytes(c.build())
        return
    if st is not None and st.op >= 0xFFF0:
        # control-op guard/value literal (BR_Z threshold, STORE value, RAND_BR weight, ...):
        # --index picks which editable literal in the op's guard/value expression (reading order).
        lits = []
        for e in (getattr(st, "expr_refs", None) or []):
            if e is not None:
                lits.extend(script.expr_literals(bank.data, e))
        if not (0 <= a.index < len(lits)):
            sys.exit(f"error: {st.mnem} @ {a.pc} has {len(lits)} editable literal(s); "
                     f"--index {a.index} out of range")
        bank.set_expr_value(lits[a.index][0], a.value)
        print(f"bank {a.bank} pc {a.pc} {st.mnem} literal[{a.index}] = {a.value}; wrote {a.out}")
    else:
        # In place when the literal's width allows it; otherwise (a fixed 0/-1/1 push, a u8 too
        # small, a variable) a fresh literal expression is appended and the arg repointed -- the
        # same auto-repoint the GUI value row uses, so the CLI never dead-ends on "not editable".
        try:
            how = c.set_action_arg_value_or_repoint(bank, pc, a.index, a.value)
        except script.ScriptError as e:
            sys.exit(f"error: {e}")
        where = {"in_place": "in place", "unchanged": "already that value -- nothing changed"}.get(
            how[0], f"repointed to a new expression @0x{how[1]:04x}")
        print(f"bank {a.bank} pc {a.pc} arg[{a.index}] value = {a.value} ({where}); wrote {a.out}")
    pathlib.Path(a.out).write_bytes(c.build())


def cmd_script_set_target(a):
    c = script.Container(_resolve(a.file).read_bytes())
    bank = c.banks[a.bank]
    pc = int(a.pc, 0)
    target = int(a.target, 0)
    # A branch destination must land on a real statement start. Collect every statement pc in the
    # bank (branches stay in-bank) as the valid set so an invalid/mid-statement target is rejected
    # rather than silently written (which would crash the VM).
    valid = set()
    for scn in script.disassemble_bank(bank, discover=True):
        valid.update(scn.stmts.keys())
    try:
        bank.set_branch_target(pc, a.index, target, valid_targets=valid)
    except script.ScriptError as e:
        sys.exit(f"error: {e}")
    st = script.decode_statement(bank.data, pc)
    print(f"bank {a.bank} pc {a.pc} {st.mnem} target[{a.index}] -> 0x{target:04x}; wrote {a.out}")
    pathlib.Path(a.out).write_bytes(c.build())


def cmd_script_set_speaker(a):
    c = script.Container(_resolve(a.file).read_bytes())
    bank = c.banks[a.bank]
    pc = int(a.pc, 0)
    st = script.decode_statement(bank.data, pc)
    if st is None or not script.is_portrait_op(st.op):
        sys.exit(f"error: bank {a.bank} pc {a.pc} is not a SetSpeaker (portrait) op")
    try:                                              # speaker: slot number OR name
        slot = int(a.speaker)
    except ValueError:
        _names = [s.lower() for s in script.PORTRAIT_SPEAKERS]
        if a.speaker.lower() not in _names:
            sys.exit(f"error: unknown speaker {a.speaker!r}; names: "
                     f"{', '.join(script.PORTRAIT_SPEAKERS)}")
        slot = _names.index(a.speaker.lower())
    if not (0 <= slot < len(script.PORTRAIT_SPEAKERS)):
        sys.exit(f"error: speaker slot {slot} out of range (0-{len(script.PORTRAIT_SPEAKERS) - 1})")
    side = 1 if a.side == "right" else 0
    bank.set_action_opcode(pc, script.portrait_opcode(slot, side))
    pathlib.Path(a.out).write_bytes(c.build())
    print(f"bank {a.bank} pc {a.pc} -> speaker {script.PORTRAIT_SPEAKERS[slot]} "
          f"({a.side}); wrote {a.out}")


def cmd_script_insert(a):
    c = _script_load(a)
    text = _listing_text(a)
    if a.dialogue is not None:
        specs = [("dialog", a.dialogue)]
    elif a.action:
        parts = [int(x, 0) for x in a.action.split()]
        specs = [("action", parts[0], parts[1:])]
    elif text is not None:
        specs = text
    else:
        sys.exit("error: pass --dialogue LINE, --action 'OP ARGS', --stmt 'LINE / LINE' or --listing FILE")
    fn = c.insert_before if a.before else c.insert_after
    try:
        fn(a.bank, int(a.pc, 0), specs)
    except script.ScriptError as e:
        sys.exit(f"error: {e}")
    pathlib.Path(a.out).write_bytes(c.build())
    print(f"inserted {'before' if a.before else 'after'} bank {a.bank} pc {a.pc}; wrote {a.out}")


def cmd_script_delete(a):
    c = script.Container(_resolve(a.file).read_bytes())
    c.delete_statement(a.bank, int(a.pc, 0))
    pathlib.Path(a.out).write_bytes(c.build())
    print(f"deleted (jumped over) bank {a.bank} pc {a.pc}; wrote {a.out}")


def _parse_beats(s):
    specs = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        kind, _, rest = part.partition(":")
        if kind == "d":
            specs.append(("dialog", int(rest, 0)))
        elif kind == "a":
            nums = [int(x, 0) for x in rest.split(",")]
            specs.append(("action", nums[0], nums[1:]))
        else:
            sys.exit(f"bad beat {part!r} (use d:LINE or a:OP,arg,arg)")
    return specs


def cmd_script_rewrite(a):
    c = _script_load(a)
    text = _listing_text(a)
    if text is not None:
        specs = text
        n = sum(1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith(";"))
    elif a.beats:
        specs = _parse_beats(a.beats)
        n = len(specs)
    else:
        sys.exit("error: pass --beats 'd:LINE;a:OP,arg' or --listing FILE")
    try:
        c.rewrite_scene(a.bank, int(a.pc, 0), specs)
    except script.ScriptError as e:
        sys.exit(f"error: {e}")
    pathlib.Path(a.out).write_bytes(c.build())
    print(f"rewrote scene bank {a.bank} entry {a.pc} with {n} statement(s); wrote {a.out}")


def cmd_script_set_text(a):
    ta = textdb.TextArchive.load(_resolve(a.file))
    ta.set_text(a.line, a.text)
    pathlib.Path(a.out).write_bytes(ta.build())
    print(f"line {a.line} set; wrote {a.out}")


# ---- authoring: listings, the assembler, type-table entries (triggers) ----------------
def _script_load(a, resolver=True):
    """Container for `a.file` with the emdeb.bin name resolver installed (best effort) for
    both directions: disassembly renders FLG_/REG_ names, the assembler accepts them."""
    from rf4s_modkit import scriptasm  # noqa: F401  (import check)
    c = script.Container(_resolve(a.file).read_bytes())
    if resolver:
        try:
            from rf4s_modkit.emflags import EmFlagTable
            emf = EmFlagTable.load()
            script.install_emflags_var_resolver(c, emf)
            c.install_asm_resolver(emf)
        except Exception:
            c.install_asm_resolver()
    return c


def _script_dialog_fn(a):
    if getattr(a, "text", None):
        ta = textdb.TextArchive.load(_resolve(a.text))
        return lambda i: ta.text(i) if 0 <= i < len(ta) else None
    return None


def _parse_keys(s):
    """Entry keys from text: '5, -1, 2:0x1234' -> [(1,5), (1,-1), (2,0x1234)]. Items are
    plain ints (tag 1 = value) or tag:value pairs; 'x' or '*' = wildcard (-1)."""
    out = []
    for part in (s or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if part in ("x", "*", "any"):
            out.append((1, -1))
            continue
        if ":" in part:
            tag, _, val = part.partition(":")
            out.append((int(tag, 0), int(val, 0)))
        else:
            out.append((1, int(part, 0)))
    return out


def _entry_line(bank, t, rec):
    try:
        from rf4s_modkit import entry_types
        desc = entry_types.describe_entry(t, rec.subs)
    except Exception:
        desc = ""
    keys = ", ".join(("%d" % v) if tag == 1 else ("%d:%d" % (tag, v)) for (tag, v) in rec.subs)
    return f"    #{rec.index:<3d} pc 0x{rec.event_id:04x}  keys [{keys}]" + (f"  {desc}" if desc else "")


def _type_label(t):
    try:
        from rf4s_modkit import entry_types
        return entry_types.type_name(t)
    except Exception:
        return "type %d" % t


def _type_recipe(t):
    """The catalogue's 'how to register one' recipe for an action type, or ''."""
    try:
        from rf4s_modkit import entry_types
        return entry_types.recipe(t)
    except Exception:
        return ""


def _wrap(text, indent="    ", width=96):
    import textwrap
    return "\n".join(textwrap.wrap(text, width, initial_indent=indent, subsequent_indent=indent))


def _listing_text(a):
    if getattr(a, "listing", None):
        return pathlib.Path(a.listing).read_text(encoding="utf-8")
    if getattr(a, "stmt", None):
        return a.stmt.replace("\\n", "\n").replace(" / ", "\n")
    return None


def cmd_script_listing(a):
    """Re-assemblable listing of one scene (--pc) or every scene of a bank."""
    from rf4s_modkit import scriptasm
    _utf8_stdout()
    c = _script_load(a)
    dlg = _script_dialog_fn(a)
    b = c.banks[a.bank]
    out = []
    if a.pc:
        pc = int(a.pc, 0)
        typ = next((t for (t, e) in b.scene_entries() if e == pc), -1)
        sc = script.disassemble_scene(b, typ, pc)
        out.append(scriptasm.scene_listing(sc, b, dialog=dlg, bank_no=a.bank))
    else:
        for sc in script.disassemble_bank(b, discover=not a.registered_only):
            out.append(scriptasm.scene_listing(sc, b, dialog=dlg, bank_no=a.bank))
            out.append("")
    text = "\n".join(out)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
        print(f"wrote {a.out} ({len(out)} block(s))")
    else:
        print(text)


def cmd_script_asm(a):
    """Assemble a listing: replace a scene's body (--pc) or just append it (--append)."""
    c = _script_load(a)
    text = _listing_text(a)
    if text is None:
        sys.exit("error: pass --listing FILE or --stmt 'LINE / LINE'")
    if a.pc:
        c.rewrite_scene(a.bank, int(a.pc, 0), text)
        what = f"rewrote scene bank {a.bank} entry {a.pc}"
    else:
        base = c.assemble(a.bank, text)
        what = f"appended region at bank {a.bank} pc 0x{base:04x} (not registered; use add-entry)"
    pathlib.Path(a.out).write_bytes(c.build())
    print(f"{what}; wrote {a.out}")


def cmd_script_check(a):
    """Assemble a listing without writing anything (syntax/label/variable check)."""
    from rf4s_modkit import scriptasm
    c = _script_load(a)
    text = _listing_text(a)
    if text is None:
        sys.exit("error: pass --listing FILE or --stmt 'LINE / LINE'")
    try:
        region, labels = scriptasm.assemble(text, 0x1000, resolver=c.asm_resolver)
    except script.ScriptError as e:
        sys.exit(f"error: {e}")
    print(f"ok: {len(region)} bytes, labels {', '.join(f'{k}=0x{v:04x}' for k, v in labels.items()) or '(none)'}")


def cmd_script_expr(a):
    """Compile an expression to bytes (and decode them back), or decode --hex."""
    from rf4s_modkit import scriptasm
    _utf8_stdout()
    c = _script_load(a) if a.file else None
    resolver = c.asm_resolver if c else None
    if a.hex:
        try:
            data = bytes.fromhex(a.hex.replace(" ", ""))
        except ValueError as e:
            sys.exit(f"error: --hex: {e}")
        txt, size = script.disasm_expr(data, 0)
        print(f"{txt}   ({size} bytes)")
        return
    try:
        data = scriptasm.asm_expr(a.expr, resolver)
    except script.ScriptError as e:
        sys.exit(f"error: {e}")
    txt, _ = script.disasm_expr(data, 0)
    print(f"{data.hex()}   ; {txt}   ({len(data)} bytes)")


def cmd_script_entries(a):
    """Dump a bank's type table (the scene triggers) with decoded keys."""
    _utf8_stdout()
    c = _script_load(a, resolver=False)
    banks = [c.banks[a.bank]] if a.bank is not None else c.banks
    for b in banks:
        tt = b.type_table_full()
        if not tt and a.bank is None:
            continue
        gi = c.banks.index(b)
        print(f"container bank {gi} = {b.kind} {b.index}: {len(b.data)} bytes, {b.table_slots}-slot table, "
              f"{sum(cnt for cnt, _ in tt.values())} entries in {len(tt)} type(s)")
        if a.bank is None and not a.verbose:
            continue
        for t, (cnt, off) in tt.items():
            print(f"  type {t} {_type_label(t)}: {cnt} entries @0x{off:04x}")
            for rec in b.entry_records(t):
                print(_entry_line(b, t, rec))
            if a.recipes:
                r = _type_recipe(t)
                if r:
                    print(_wrap("recipe: " + r, indent="      "))


def cmd_script_add_entry(a):
    _utf8_stdout()
    c = _script_load(a)
    keys = _parse_keys(a.keys)
    text = _listing_text(a)
    if (text is None) == (a.pc is None):
        sys.exit("error: pass exactly one of --pc PC (existing scene) or --listing FILE / --stmt")
    # Judged BEFORE the add: does this registration shadow / replace an existing scene?
    try:
        note = c.entry_shadow_note(a.bank, a.type, a.position)
    except Exception:
        note = None
    try:
        pc, idx = c.add_entry(a.bank, a.type, keys, event_pc=int(a.pc, 0) if a.pc else None,
                              listing=text, position=a.position)
    except script.ScriptError as e:
        sys.exit(f"error: {e}")
    pathlib.Path(a.out).write_bytes(c.build())
    print(f"registered type {a.type} {_type_label(a.type)} entry #{idx} -> scene pc 0x{pc:04x} "
          f"in bank {a.bank}; wrote {a.out}")
    if note:
        print("warning: " + note)


def cmd_script_remove_entry(a):
    c = _script_load(a, resolver=False)
    try:
        eid, subs = c.remove_entry(a.bank, a.type, a.index)
    except script.ScriptError as e:
        sys.exit(f"error: {e}")
    pathlib.Path(a.out).write_bytes(c.build())
    print(f"removed type {a.type} entry #{a.index} (pc 0x{eid:04x}) from bank {a.bank}; wrote {a.out}")


def cmd_script_set_entry(a):
    c = _script_load(a, resolver=False)
    keys = _parse_keys(a.keys) if a.keys is not None else None
    try:
        c.set_entry(a.bank, a.type, a.index, subs=keys, event_pc=int(a.pc, 0) if a.pc else None)
    except script.ScriptError as e:
        sys.exit(f"error: {e}")
    pathlib.Path(a.out).write_bytes(c.build())
    rec = c.banks[a.bank].entry_records(a.type)[a.index]
    print(f"type {a.type} entry #{a.index}: pc 0x{rec.event_id:04x} keys {rec.subs}; wrote {a.out}")


# --------------------------------------------------------------------------- #
# em (em.bin Event Manager: named trigger conditions + actions)
# --------------------------------------------------------------------------- #
def _emflags_load(a):
    from rf4s_modkit.emflags import EmFlagTable, find_emdeb, EXTRA_FILENAME
    emdeb = _resolve(a.emdeb) if getattr(a, "emdeb", None) else pathlib.Path(find_emdeb())
    extra = a.extra or str(emdeb.parent / EXTRA_FILENAME)
    return EmFlagTable.load(str(emdeb), extra=extra), extra


def cmd_em_new_var(a):
    """Define a new FLG_/REG_ variable in the sidecar (free bits of the GameFlags store)."""
    _utf8_stdout()
    t, extra = _emflags_load(a)
    try:
        v = t.add_variable(a.name, a.width, a.jp, bit_offset=a.bit)
    except ValueError as e:
        sys.exit(f"error: {e}")
    t.save_extras(extra)
    print(f"{v.name}: bits {v.bit_offset}..{v.bit_offset + v.bit_width - 1} (width {v.bit_width}); "
          f"{t.free_bits} free bits left; wrote {extra}")
    print("use it as `FLG_X == 1` in em conditions, `STORE (FLG_X = 1)` / `BR_Z (FLG_X)` in cutscene "
          "listings; the game never reads the name, only the bits")


def cmd_em_vars(a):
    _utf8_stdout()
    t, extra = _emflags_load(a)
    flt = (a.filter or "").upper()
    rows = t.extras if a.extras_only else t.variables
    n = 0
    for v in rows:
        if flt and flt not in v.name.upper():
            continue
        n += 1
        tag = "  [extra]" if getattr(v, "extra", False) else ""
        print(f"{v.bit_offset:5d} w{v.bit_width:<2d} {v.name}{('  ' + v.jp_name) if v.jp_name else ''}{tag}")
    print(f"{n} variable(s); store {t.total_bits} bits used, {t.free_bits} free"
          + (f"; sidecar {extra}" if t.extras else ""))


def _em_load(a):
    return emscript.EmScript.load(
        _resolve(a.em) if getattr(a, "em", None) else None,
        _resolve(a.emdeb) if getattr(a, "emdeb", None) else None)


def cmd_em_list(a):
    em = _em_load(a)
    flt = (a.filter or "").upper()
    for e in em.entries:
        if flt and flt not in (e.name or "").upper():
            continue
        marks = "".join(m for m, has in (
            ("A", e.cond_a), ("B", e.cond_b), ("!", e.actions), ("~", e.alt_actions)) if has)
        sys.stdout.buffer.write(("%3d  %-4s %s\n" % (e.idx, marks, e.name or "(unnamed)"))
                                .encode("utf-8", "replace"))
    print("\n(A=cond A, B=cond B, !=main actions, ~=alt actions)")


def cmd_em_show(a):
    em = _em_load(a)
    try:
        e = em.get(int(a.entry))
    except ValueError:
        e = em.get(a.entry)
    sys.stdout.buffer.write(em.format_entry(e).encode("utf-8", "replace"))
    sys.stdout.buffer.write(b"\n")


def cmd_em_set(a):
    """Edit a condition or action in place (byte-safe, no relocation) and write em.bin."""
    em = _em_load(a)
    try:
        e = em.get(int(a.entry))
    except ValueError:
        e = em.get(a.entry)
    changed = []
    if a.cond:
        slots = e.cond_a if a.cond == "a" else e.cond_b
        if not slots:
            sys.exit("entry %s has no condition %s" % (e.name, a.cond.upper()))
        try:
            expr = slots[a.slot][a.expr]
        except IndexError:
            sys.exit("cond %s slot %d expr %d out of range" % (a.cond, a.slot, a.expr))
        if a.op is not None:
            em.set_cmp_operator(expr, a.op); changed.append("op=%s" % a.op)
        if a.value is not None:
            op = (expr.op1 if a.operand == 1 else expr.op2) if a.operand else \
                 (expr.op2 if (expr.op2 and expr.op2.kind in ("lit", "slit")) else expr.op1)
            em.set_operand_value(op, int(a.value, 0)); changed.append("value=%s" % a.value)
        if a.entry_ref is not None:
            em.set_cond_ref(expr, int(a.entry_ref, 0)); changed.append("ref=%s" % a.entry_ref)
    elif a.action:
        acts = e.actions if a.action == "main" else e.alt_actions
        try:
            act = acts[a.index]
        except IndexError:
            sys.exit("%s action %d out of range" % (a.action, a.index))
        if a.op is not None:
            em.set_action_op(act, a.op); changed.append("op=%s" % a.op)
        if a.entry_ref is not None:
            em.set_call_entry(act, int(a.entry_ref, 0)); changed.append("call=%s" % a.entry_ref)
        if a.value is not None:
            em.set_operand_value(act.value, int(a.value, 0)); changed.append("value=%s" % a.value)
        if getattr(a, "target", None) is not None:
            # retarget which FLG_/REG_ this action writes (the destination, vs --value = the value
            # it writes). Accept a raw bit offset or an exact emdeb flag name (FLG_*/REG_*).
            if act.target is None:
                sys.exit("action %d is a CALL / has no writable target" % a.index)
            try:
                _off = int(a.target, 0)
            except ValueError:
                _hits = [v for v in em.names.flags.find(a.target) if v.name == a.target]
                if not _hits:
                    _near = ", ".join(v.name for v in em.names.flags.find(a.target)[:6])
                    sys.exit("unknown flag %r; did you mean: %s" % (a.target, _near or "(none)"))
                _off = _hits[0].bit_offset
            em.set_operand_value(act.target, _off); changed.append("target=%s" % a.target)
    else:
        sys.exit("specify --cond {a,b} (with --slot/--expr) or --action {main,alt} (with --index)")
    if not changed:
        sys.exit("nothing to change -- pass --value / --op / --entry-ref / --target")
    out = a.out or (_resolve(a.em) if getattr(a, "em", None) else emscript.find_em())
    pathlib.Path(out).write_bytes(em.build())
    sys.stdout.buffer.write(("em set %s [%d]: %s -> %s\n" %
                             (e.name, e.idx, ", ".join(changed), out)).encode("utf-8", "replace"))


def cmd_em_queries(a):
    em = _em_load(a)
    for i, (en, jp) in enumerate(em.names.query_names):
        sys.stdout.buffer.write(("%3d  %s%s\n" % (i, en, "  " + jp if jp else ""))
                                .encode("utf-8", "replace"))


def cmd_em_xref(a):
    """Scan rf3.mc for the 5 CondScript bridge ops and resolve entry names.
    Reports DISTINCT (bank, pc) sites -- discovered scenes overlap, so raw
    occurrences would double-count."""
    em = _em_load(a)
    c = script.Container(_resolve(a.mc).read_bytes())
    opn = {371: "EvalCondA", 372: "EvalCondB", 373: "DispatchEntry",
           374: "DispatchAltAction", 444: "SetFlagGatedByCond"}
    sites = {}
    for bk, sc in script.iter_scenes(c):
        for pc, st in sc.stmts.items():
            if st.op not in script.EMF_ENTRY_OPS or not st.args:
                continue
            ai = script.EMF_ENTRY_OPS[st.op]
            if ai >= len(st.args):
                continue
            sites.setdefault((bk.index, pc), (sc.entry_pc, st.op,
                                              script.arg_repr(bk.data, st.args[ai])))
    for (bank, pc), (entry_pc, op, rep) in sorted(sites.items()):
        try:
            nm = em.names.entry_name(int(rep)) or "?"
        except ValueError:
            nm = "<dynamic>"
        sys.stdout.buffer.write(
            ("bank %3d scene@%04x %04x  %-18s %-6s %s\n"
             % (bank, entry_pc, pc, opn[op], rep, nm)).encode("utf-8", "replace"))
    print("\n%d distinct bridge-op site(s)" % len(sites))


# ---- em structural edits: add / remove entries, condition terms, actions --------------
def _em_entry(em, key):
    try:
        return em.get(int(key))
    except ValueError:
        try:
            return em.get(key)
        except KeyError:
            sys.exit("unknown em entry %r (id or emdeb name)" % key)


def _em_write(a, em, msg):
    out = a.out or (_resolve(a.em) if getattr(a, "em", None) else emscript.find_em())
    pathlib.Path(out).write_bytes(em.build())
    sys.stdout.buffer.write(("%s -> %s\n" % (msg, out)).encode("utf-8", "replace"))


def _em_print(em, e):
    sys.stdout.buffer.write((em.format_entry(e) + "\n").encode("utf-8", "replace"))


def cmd_em_add(a):
    """Append a NEW entry: cloned from --clone and/or built from --cond-a/--cond-b/--action/
    --alt-action specs (each --cond-* = one OR-slot). Prints its id; the header count is
    bumped so the engine evaluates it (ids >= count are silently FALSE)."""
    em = _em_load(a)
    try:
        idx = em.add_entry(clone=_em_entry(em, a.clone).idx if a.clone else None,
                           name=a.name or "")
        for spec in a.cond_a or []:
            em.add_condition(idx, "a", em.parse_condition_spec(spec))
        for spec in a.cond_b or []:
            em.add_condition(idx, "b", em.parse_condition_spec(spec))
        for spec in a.action or []:
            em.add_action(idx, "main", em.parse_action_spec(spec))
        for spec in a.alt_action or []:
            em.add_action(idx, "alt", em.parse_action_spec(spec))
    except (ValueError, IndexError, KeyError) as e:
        sys.exit("em add: %s" % e)
    _em_print(em, em.get(idx))
    _em_write(a, em, "em add: new entry #%d (%d entries)" % (idx, len(em.entries)))
    print("reference it as condA(#%d) / CALL #%d in em, or by id %d from rf3.mc bridge ops "
          "(script set-val); emdeb.bin is not rewritten, so it lists as (unnamed)" % (idx, idx, idx))


def cmd_em_remove(a):
    """Remove an entry: --blank clears it in place (ids stay stable); otherwise it is
    physically deleted and every later entry moves down one id (internal refs are
    renumbered; rf3.mc bridge ops are NOT -- re-check with `em xref`)."""
    em = _em_load(a)
    e = _em_entry(em, a.entry)
    idx, name = e.idx, e.name
    if a.blank:
        em.clear_entry(idx)
        _em_write(a, em, "em remove --blank: #%d %s now has no conditions/actions" % (idx, name))
        return
    try:
        moved = em.delete_entry(idx, force=a.force)
    except ValueError as ex:
        sys.exit("em remove: %s" % ex)
    _em_write(a, em, "em remove: deleted #%d %s (%d entries left, %d internal ref(s) renumbered)"
              % (idx, name, len(em.entries), moved))
    print("WARNING: entries %d.. moved down one id -- rf3.mc bridge ops (em xref) and the "
          "positional emdeb.bin names past #%d no longer match; `--blank` avoids this" % (idx, idx))


def cmd_em_add_cond(a):
    """Add condition terms: a new OR-slot (default) or ANDed onto --slot N."""
    em = _em_load(a)
    e = _em_entry(em, a.entry)
    try:
        slot = em.add_condition(e.idx, a.cond, em.parse_condition_spec(a.expr), a.slot)
    except (ValueError, IndexError) as ex:
        sys.exit("em add-cond: %s" % ex)
    _em_print(em, em.get(e.idx))
    _em_write(a, em, "em add-cond: #%d %s cond %s slot %d" % (e.idx, e.name, a.cond.upper(), slot))


def cmd_em_remove_cond(a):
    """Remove one expression (--expr) or a whole OR-slot from condition A/B."""
    em = _em_load(a)
    e = _em_entry(em, a.entry)
    try:
        gone = em.remove_condition(e.idx, a.cond, a.slot, a.expr)
    except (ValueError, IndexError) as ex:
        sys.exit("em remove-cond: %s" % ex)
    _em_print(em, em.get(e.idx))
    _em_write(a, em, "em remove-cond: #%d %s cond %s slot %d: removed %s" % (
        e.idx, e.name, a.cond.upper(), a.slot, ", ".join(x.pretty(em.names) for x in gone)))


def cmd_em_add_action(a):
    """Append (or --index insert) an action into the main/alt stream."""
    em = _em_load(a)
    e = _em_entry(em, a.entry)
    try:
        i = em.add_action(e.idx, a.stream, em.parse_action_spec(a.action), a.index)
    except (ValueError, IndexError) as ex:
        sys.exit("em add-action: %s" % ex)
    _em_print(em, em.get(e.idx))
    _em_write(a, em, "em add-action: #%d %s %s action %d" % (e.idx, e.name, a.stream, i))


def cmd_em_remove_action(a):
    em = _em_load(a)
    e = _em_entry(em, a.entry)
    try:
        gone = em.remove_action(e.idx, a.stream, a.index)
    except (ValueError, IndexError) as ex:
        sys.exit("em remove-action: %s" % ex)
    _em_print(em, em.get(e.idx))
    _em_write(a, em, "em remove-action: #%d %s %s action %d (%s)" % (
        e.idx, e.name, a.stream, a.index, gone.pretty(em.names)))


# --------------------------------------------------------------------------- #
# save (rf4_sNN.sav per-slot save editor)
# --------------------------------------------------------------------------- #
def _save_load(a):
    from rf4s_modkit import save
    return save.SaveFile.load(_resolve(a.sav))


def cmd_save_show(a):
    s = _save_load(a)
    for k, v in s.summary().items():
        print("  %-14s %s" % (k, v))


def cmd_save_flag(a):
    s = _save_load(a)
    try:
        print("%s = %d" % (a.name, s.flag(a.name)))
    except KeyError as e:
        sys.exit(str(e))


def cmd_save_find_flags(a):
    s = _save_load(a)
    rows = s.find_flags(a.substr)
    for nm, val, w in rows[:a.limit]:
        print("  %-40s = %-6d (w%d)" % (nm, val, w))
    print("\n%d flag(s) matched%s" % (len(rows), "" if len(rows) <= a.limit else " (truncated)"))


def cmd_save_set_flag(a):
    s = _save_load(a)
    try:
        before = s.flag(a.name)
        s.set_flag(a.name, int(a.value, 0))
    except (KeyError, ValueError) as e:
        sys.exit(str(e))
    out = a.out or _resolve(a.sav)
    pathlib.Path(out).write_bytes(s.build())
    print("save: %s %d -> %d  (crc recomputed) -> %s" % (a.name, before, s.flag(a.name), out))


def cmd_save_get(a):
    s = _save_load(a)
    print("0x%X = %d (0x%X)" % (int(a.offset, 0), s.get_u32(int(a.offset, 0)),
                                s.get_u32(int(a.offset, 0))))


def cmd_save_set(a):
    s = _save_load(a)
    off = int(a.offset, 0)
    before = s.get_u32(off)
    s.set_u32(off, int(a.value, 0))
    out = a.out or _resolve(a.sav)
    pathlib.Path(out).write_bytes(s.build())
    print("save: [0x%X] %d -> %d  (crc recomputed) -> %s" % (off, before, s.get_u32(off), out))


# --------------------------------------------------------------------------- #
# strings (.strings)
# --------------------------------------------------------------------------- #
def cmd_strings_decode(a):
    d = strings_file.load(_resolve(a.file))
    out = json.dumps(d, ensure_ascii=False, indent=1)
    if a.out:
        pathlib.Path(a.out).write_text(out, encoding="utf-8")
        print(f"decoded {a.file} -> {a.out} ({len(d)} keys)")
    else:
        print(out)


def cmd_strings_encode(a):
    d = json.loads(pathlib.Path(a.json).read_text(encoding="utf-8"))
    strings_file.save(d, a.out)
    print(f"encoded {len(d)} keys -> {a.out}")


# --------------------------------------------------------------------------- #
# res (NN containers)
# --------------------------------------------------------------------------- #
def cmd_res_info(a):
    print(res_container.summary(_resolve(a.file).read_bytes()))


def cmd_res_texture_list(a):
    data = _resolve(a.file).read_bytes()
    infos = texture.bntx_info(data)
    if not infos:
        sys.exit(f"error: {a.file} has no BNTX texture container")
    print(f"{a.file}: {len(infos)} texture(s) in the embedded BNTX")
    for t in infos:
        print(f"  {t['index']:3d}  {t['name']:32s} {t['fmt_name']:9s} {t['width']:5d}x{t['height']:<5d} "
              f"{t['image_size']:9,d} B  data@0x{t['data_off']:x}  mips={t['mips']} tile={t['tile']}")


def cmd_res_texture_decode(a):
    data = _resolve(a.file).read_bytes()
    try:
        im = texture.decode_bntx(data, a.index)
    except texture.TextureError as e:
        sys.exit(f"error: {e}")
    if im is None:
        sys.exit(f"error: texture {a.index} of {a.file} cannot be decoded (missing or unsupported format)")
    out = a.out or f"{pathlib.Path(a.file).stem}_{a.index}.png"
    im.convert("RGBA").save(out)
    t = texture.bntx_info(data)[a.index]
    print(f"decoded {a.file} texture {a.index} ({t['name']}, {t['fmt_name']} "
          f"{t['width']}x{t['height']}) -> {out}")


def cmd_res_texture_encode(a):
    data = _resolve(a.file).read_bytes()
    try:
        blob = texture.bntx_replace(data, a.index, a.png, fmt=a.fmt)
    except texture.TextureError as e:
        sys.exit(f"error: {e}")
    pathlib.Path(a.out).write_bytes(blob)
    t = texture.bntx_info(blob)[a.index]
    print(f"replaced texture {a.index} ({t['name']}) of {a.file} from {a.png} -> {a.out}  "
          f"({t['fmt_name']} {t['width']}x{t['height']}, {t['image_size']:,} B payload rewritten "
          f"in place; file {len(blob):,} B, {_size_note(len(data), len(blob))})")


# --------------------------------------------------------------------------- #
# gen (Gen*.bin monster encounter tables)
# --------------------------------------------------------------------------- #
def _names(arg):
    p = pathlib.Path(arg) if arg else ACTOR_NAMES
    if p.is_file():
        return gen.load_actor_names(p)
    return lambda i: ""


def cmd_gen_info(a):
    g = gen.GenTable.load(_resolve(a.file))
    print(g.summary(_names(a.names)))


def cmd_gen_area(a):
    """Aggregate the monster roster across all files of an area, e.g. GenA / GenField."""
    from collections import Counter
    nm = _names(a.names)
    files = sorted(EXTRACTED.rglob(a.prefix + "*.bin"))
    if not files:
        sys.exit(f"no {a.prefix}*.bin files under {EXTRACTED}")
    roster, gates = Counter(), Counter()
    for f in files:
        try:
            g = gen.GenTable.load(f)
        except Exception:   # skip any unparseable/truncated file in the bulk sweep
            continue
        roster.update(g.roster())
        for _pi, _ei, e in g.all_entries():
            gates[e.gate_kind] += 1
    print(f"{a.prefix}: {len(files)} encounter files")
    print("  gates:   " + ", ".join(f"{nm(k) or k}×{c}" for k, c in gates.most_common()))
    print("  monsters:" + ", ".join(f" {nm(i) or i}×{c}" for i, c in roster.most_common()))


def _row_name_fn(stem):
    """Return a fn(item_or_record_id)->label using the schema's name table, if any."""
    sch = nlcl.FIELD_SCHEMAS.get(stem)
    if not sch:
        for pre, s in nlcl.PREFIX_SCHEMAS.items():
            if stem.startswith(pre):
                sch = s
                break
    if sch and sch.get("names") == "item" and ITEM_NAMES.is_file():
        names = json.loads(ITEM_NAMES.read_text(encoding="utf-8"))
        return lambda i: names.get(str(i), "")
    return lambda i: ""


def cmd_param_info(a):
    p = _resolve(a.file)
    t = nlcl.NlclTable.load(p)
    stem = p.stem
    print(t.summary(stem))
    print("  " + t.grow_info(stem)[1])       # is an appended row read by the engine?
    sch = t.schema(stem)
    namefn = _row_name_fn(stem)
    lo, hi = 0, min(t.entry_count, a.limit or 20)
    if sch:
        cols = [f[0] for f in sch["fields"]]
        nf = sch.get("name_field")
        print("  " + "  ".join(["#"] + cols + (["name"] if sch.get("names") else [])))
        for i in range(lo, hi):
            row = t.row(i, stem)
            vals = [str(i)] + [str(row[c]) for c in cols]
            if sch.get("names"):
                vals.append(namefn(row[nf] if nf else i))
            print("  " + "  ".join(vals))
    else:
        print("  (no named schema — showing raw dwords; edit by --off)")
        for i in range(lo, hi):
            print(f"  rec {i}: {t.record_dwords(i)}")
    if t.entry_count > hi:
        print(f"  ... {t.entry_count - hi} more records (use --limit)")


def cmd_param_dump(a):
    p = _resolve(a.file)
    t = nlcl.NlclTable.load(p)
    out = ["index," + ",".join(f"dw{k}" for k in range(t.record_size // 4))]
    for i in range(t.entry_count):
        out.append(str(i) + "," + ",".join(str(v) for v in t.record_dwords(i)))
    text = "\n".join(out)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
        print(f"dumped {t.entry_count} records -> {a.out}")
    else:
        print(text)


def cmd_param_csv(a):
    """The named table view (what `param info` / the GUI grid show) as CSV."""
    p = _resolve(a.file)
    t = nlcl.NlclTable.load(p)
    text = t.to_csv(p.stem, _row_name_fn(p.stem), named=not a.raw)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
        print(f"{p.stem}: {t.entry_count} records x {len(t.csv_columns(p.stem, not a.raw))} columns -> {a.out}")
    else:
        print(text, end="")


def cmd_param_csv_all(a):
    """Every flat NLCL rf3*.bin under the extracted tree (or --dir) -> one CSV each."""
    root = pathlib.Path(a.dir) if a.dir else EXTRACTED
    outdir = pathlib.Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in root.rglob("rf3*.bin") if nlcl.is_flat_nlcl(p.read_bytes()[:32]))
    done, named, skipped = 0, 0, []
    for p in files:
        try:
            t = nlcl.NlclTable.load(p)
        except nlcl.NlclError as e:
            skipped.append(f"{p.name}: {e}")
            continue
        has_schema = t.schema(p.stem) is not None and not a.raw
        text = t.to_csv(p.stem, _row_name_fn(p.stem), named=not a.raw)
        (outdir / (p.stem + ".csv")).write_text(text, encoding="utf-8")
        done += 1
        named += has_schema
    print(f"wrote {done} tables -> {outdir}  ({named} with named columns, {done - named} raw dw0..dwN)")
    for s in skipped:
        print("  skipped " + s)


def cmd_param_get(a):
    p = _resolve(a.file)
    t = nlcl.NlclTable.load(p)
    print(t.row(a.record, p.stem))


def cmd_param_set(a):
    p = _resolve(a.file)
    t = nlcl.NlclTable.load(p)
    stem = p.stem
    for assign in a.set:
        key, val = assign.split("=", 1)
        value = int(val, 0)
        if ":" in key:                       # off:type form, e.g. 12:s32
            off_s, typ = key.split(":", 1)
            t.set(a.record, int(off_s, 0), value, typ)
        elif key.lstrip("+").isdigit() or key.lstrip("+").lower().startswith("0x"):  # bare offset (dec or hex)
            t.set(a.record, int(key, 0), value, "s32")
        else:                                  # named field
            t.set_field(a.record, key, value, stem)
    out = pathlib.Path(a.out) if a.out else p
    out.write_bytes(t.build())
    print(f"rec {a.record}: {t.record_dwords(a.record)}")
    print(f"wrote {out}")


def _param_assign(t, rec, assign, stem):
    """One `name=val | OFF=val | OFF:type=val` assignment (the `param set` grammar)."""
    key, val = assign.split("=", 1)
    value = int(val, 0)
    if ":" in key:
        off_s, typ = key.split(":", 1)
        t.set(rec, int(off_s, 0), value, typ)
    elif key.lstrip("+").isdigit() or key.lstrip("+").lower().startswith("0x"):
        t.set(rec, int(key, 0), value, "s32")
    else:
        t.set_field(rec, key, value, stem)


def cmd_param_add(a):
    """Append (or insert) a row: a copy of record --copy, else an all-zero row; then apply
    --set assignments to it. Rewrites entry_count/byte_size + the NLCL footer."""
    p = _resolve(a.file)
    t = nlcl.NlclTable.load(p)
    stem = p.stem
    rec = t.record(a.copy) if a.copy is not None else None
    try:
        idx = t.insert_record(a.at, rec) if a.at is not None else t.append_record(rec)
        for assign in a.set or []:
            _param_assign(t, idx, assign, stem)
    except nlcl.NlclError as e:
        sys.exit(f"param add: {e}")
    out = pathlib.Path(a.out)
    out.write_bytes(t.build())
    src = f"copy of record {a.copy}" if a.copy is not None else "zero row"
    print(f"{stem}: added record {idx} ({src}) -> {t.entry_count} records x {t.record_size} B, "
          f"byte_size {t.byte_size}")
    print(f"  rec {idx}: {t.row(idx, stem) if t.schema(stem) else t.record_dwords(idx)}")
    if a.at is not None and a.at < t.entry_count - 1:
        print(f"  note: records {a.at + 1}.. moved up by one (row index = id in most tables)")
    print("  " + t.grow_info(stem)[1])
    print(f"wrote {out}")


def cmd_param_remove(a):
    """Delete a row (later rows shift down by one)."""
    p = _resolve(a.file)
    t = nlcl.NlclTable.load(p)
    stem = p.stem
    try:
        old = t.delete_record(a.index)
    except nlcl.NlclError as e:
        sys.exit(f"param remove: {e}")
    out = pathlib.Path(a.out)
    out.write_bytes(t.build())
    print(f"{stem}: removed record {a.index} ({old.hex()}) -> {t.entry_count} records, "
          f"byte_size {t.byte_size}")
    if a.index < t.entry_count:
        print(f"  note: records {a.index + 1}.. moved down by one (row index = id in most "
              f"tables: prefer zeroing a row with `param set` if ids must stay stable)")
    print(f"wrote {out}")


# --------------------------------------------------------------------------- #
# crop — readable front-end over rf3CropParam (season affinity + growth tuning)
# --------------------------------------------------------------------------- #
CROP_FILE = "rf3CropParam"


def _crop_load():
    p = _resolve(CROP_FILE)
    return p, nlcl.NlclTable.load(p)


def _crop_is_planted(row):
    """A real farm crop: has growth stages, or carries a season affinity."""
    return bool(row["stage1"] or row["stage2"] or row["stage3"]
                or (row["season"] & nlcl._CROP_SEASON_MASK))


def cmd_crop_show(a):
    p, t = _crop_load()
    namefn = _row_name_fn(CROP_FILE)
    row = t.row(a.record, p.stem)
    dec = nlcl.crop_season_decode(row["season"])
    print(f"rec {a.record}: {namefn(row['harvest']) or '(unnamed)'}")
    print(f"  stages [{row['stage1']},{row['stage2']},{row['stage3']}]  regrow {row['regrow']}"
          f"  water {row['water']}  grow_cap {row['grow_cap']}")
    print(f"  harvest item {row['harvest']} ({namefn(row['harvest'])})"
          f"   seed item {row['seed']} ({namefn(row['seed'])})")
    print(f"  season: grows-well={dec['grows']}  penalized={dec['penalized']}"
          f"  harvest-by={dec['harvest']}  (raw 0x{row['season']:X})")
    print(f"  growth-rate mults (128=1.0x): size={row['gmul_size']}"
          f"  q1={row['gmul_1']} q2={row['gmul_2']} q3={row['gmul_3']}")


def cmd_crop_list(a):
    p, t = _crop_load()
    namefn = _row_name_fn(CROP_FILE)
    n = 0
    for i in range(t.entry_count):
        row = t.row(i, p.stem)
        if not _crop_is_planted(row):
            continue
        dec = nlcl.crop_season_decode(row["season"])
        print(f"  {i:3d}  {(namefn(row['harvest']) or ''):24s}"
              f"  grows={'/'.join(dec['grows']):20s}  water={row['water']}")
        n += 1
    print(f"  ({n} crops)")


def cmd_crop_season(a):
    p, t = _crop_load()
    seasons = [s.strip().lower() for s in a.set.split(",") if s.strip()]
    bad = [s for s in seasons if s not in nlcl.CROP_SEASONS]
    if bad:
        sys.exit(f"unknown season(s) {bad}; valid: {', '.join(nlcl.CROP_SEASONS)}")
    if not seasons:
        sys.exit("give at least one season, e.g. --set winter  or  --set spring,fall")
    old = t.row(a.record, p.stem)["season"]
    new = nlcl.crop_season_encode(old, seasons, single=not a.all_year)
    t.set_field(a.record, "season", new, p.stem)
    out = pathlib.Path(a.out) if a.out else p
    out.write_bytes(t.build())
    print(f"rec {a.record}: season 0x{old:X} -> 0x{new:X}")
    print(f"  now: {nlcl.crop_season_decode(new)}")
    print(f"wrote {out}")


def cmd_gen_formap(a):
    """Map a map name to its Gen encounter file: MAP_DUNG_X## -> GenX##, MAP_FIELD_## -> GenField##.
    Confirmed by g_encounterArchiveTable (base_selector = the area's first-map room id)."""
    import re
    nm = _names(a.names)
    m = re.search(r"DUNG_([A-Z]+)(\d+)", a.map, re.I) or re.search(r"(FIELD)_?(\d+)", a.map, re.I)
    if not m:
        sys.exit(f"could not parse an area+number from {a.map!r} "
                 f"(expected MAP_DUNG_X## or MAP_FIELD_##)")
    area, num = m.group(1).upper(), int(m.group(2))
    gen_name = (f"GenField{num:02d}.bin" if area == "FIELD" else f"Gen{area}{num:02d}.bin")
    path = _resolve(gen_name)
    if not path.is_file():
        print(f"{a.map} -> {gen_name}  (no such Gen file — this map may have no random "
              f"encounters, or its area reuses another Gen)")
        return
    print(f"{a.map} -> {gen_name}")
    print(gen.GenTable.load(path).summary(nm))


def _gen_write(g, a):
    out = pathlib.Path(a.out) if a.out else _resolve(a.file)
    out.write_bytes(g.build())
    print(g.summary(_names(a.names)))
    print(f"wrote {out}")


def cmd_gen_set(a):
    g = gen.GenTable.load(_resolve(a.file))
    e = g.patterns[a.pattern][a.entry]
    if a.gate is not None:
        g.set_gate_kind(a.pattern, a.entry, a.gate)
    if a.weight is not None:
        g.set_weight(a.pattern, a.entry, a.weight)
    for assign in (a.spawn or []):
        idx, mid = assign.split("=", 1)
        g.set_spawn_monster(e.spawns[int(idx)], int(mid, 0))
    for assign in (a.level or []):
        idx, lvl = assign.split("=", 1)
        g.set_spawn_level(e.spawns[int(idx)], int(lvl, 0))
    for assign in (a.weights or []):
        idx, ws = assign.split("=", 1)
        g.set_spawn_weights(e.spawns[int(idx)], [int(w, 0) for w in ws.split(",")])
    if a.per_spawn:
        lo, _sep, hi = a.per_spawn.partition("-")
        g.set_hdr(e, count_min=int(lo), count_max=int(hi or lo))
    if a.delay is not None:
        g.set_hdr(e, spawn_delay=a.delay)
    _gen_write(g, a)


def cmd_gen_add_gate(a):
    """Append a gate entry cloned from an existing one (--clone IDX): a private copy of
    its positions and roster (or, with --share, the very same blocks) under the given
    kind/weight. Copy-then-retune is the safe way to add an encounter."""
    g = gen.GenTable.load(_resolve(a.file))
    pat = g.patterns[a.pattern] if a.pattern < len(g.patterns) else []
    if not pat:
        sys.exit("this file has no gate to clone (empty encounter table)")
    src = pat[a.clone]
    kind = a.gate if a.gate is not None else src.gate_kind
    weight = a.weight if a.weight is not None else src.weight
    g.add_entry(a.pattern, kind, weight, clone=src, share=a.share)
    _gen_write(g, a)


def cmd_gen_remove_gate(a):
    g = gen.GenTable.load(_resolve(a.file))
    g.remove_entry(a.pattern, a.entry)
    _gen_write(g, a)


def cmd_gen_add_monster(a):
    g = gen.GenTable.load(_resolve(a.file))
    e = g.patterns[a.pattern][a.entry]
    weights = [int(w, 0) for w in a.weights.split(",")] if a.weights else None
    g.add_spawn(e, a.monster, a.level, weights)
    _gen_write(g, a)


def cmd_gen_remove_monster(a):
    g = gen.GenTable.load(_resolve(a.file))
    e = g.patterns[a.pattern][a.entry]
    g.remove_spawn(e, a.index)
    _gen_write(g, a)


def cmd_gen_validate(a):
    g = gen.GenTable.load(_resolve(a.file))
    probs = g.validate()
    for p in probs:
        print("  " + p)
    print(f"{a.file}: {'OK' if not probs else f'{len(probs)} problem(s)'}")
    if probs:
        sys.exit(1)


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #
def cmd_mapview(a):
    """Launch the graphical map explorer (optionally seeded with a map)."""
    import map_editor
    map_editor.main([a.map] if a.map else [])


def cmd_selftest(a):
    import importlib
    st = importlib.import_module("selftest")
    sys.exit(st.run())


# --------------------------------------------------------------------------- #
# argument parser
# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(prog="rf4mod", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="group", required=True)

    # ident
    pi = sub.add_parser("ident", help="identify file type(s) by magic")
    pi.add_argument("files", nargs="+")
    pi.set_defaults(func=cmd_ident)

    # bundle
    pb = sub.add_parser("bundle", help="unpack / repack .mbundle archives")
    bsub = pb.add_subparsers(dest="op", required=True)

    def add_man(sp, default_use=False):
        sp.add_argument("--manifest", help=f"Manifest.plist (default: {DEFAULT_MANIFEST})")
        sp.add_argument("--use-manifest", action="store_true", default=default_use,
                        help="read TOC from manifest instead of the bundle's embedded one")

    b1 = bsub.add_parser("list", help="list bundle contents")
    b1.add_argument("bundle"); b1.add_argument("--filter")
    add_man(b1); b1.set_defaults(func=cmd_bundle_list)

    b2 = bsub.add_parser("extract", help="extract one file")
    b2.add_argument("bundle"); b2.add_argument("name"); b2.add_argument("-o", "--out")
    add_man(b2); b2.set_defaults(func=cmd_bundle_extract)

    b3 = bsub.add_parser("extract-all", help="extract everything")
    b3.add_argument("bundle"); b3.add_argument("-o", "--out", required=True)
    b3.add_argument("--prefix", help="only extract names under this prefix")
    add_man(b3); b3.set_defaults(func=cmd_bundle_extract_all)

    b4 = bsub.add_parser("find", help="which bundle holds a file (manifest)")
    b4.add_argument("name"); b4.add_argument("--manifest")
    b4.set_defaults(func=cmd_bundle_find)

    b5 = bsub.add_parser("patch", help="overwrite a file in place (<= original size)")
    b5.add_argument("bundle"); b5.add_argument("name"); b5.add_argument("file")
    b5.add_argument("--manifest"); b5.set_defaults(func=cmd_bundle_patch)

    b6 = bsub.add_parser("add", help="append/replace a file (any size) via repack")
    b6.add_argument("bundle"); b6.add_argument("name"); b6.add_argument("file")
    b6.add_argument("--manifest"); b6.set_defaults(func=cmd_bundle_add)

    b7 = bsub.add_parser("rebuild", help="build a fresh .mbundle from a directory")
    b7.add_argument("dir"); b7.add_argument("-o", "--out", required=True)
    b7.add_argument("--manifest"); b7.add_argument("--name", help="manifest bundle name to update")
    b7.set_defaults(func=cmd_bundle_rebuild)

    # install
    pin = sub.add_parser("install", help="install a loose-file override (recommended)")
    pin.add_argument("game_root"); pin.add_argument("name"); pin.add_argument("file")
    pin.set_defaults(func=cmd_install)

    # plist
    pp = sub.add_parser("plist", help="bplist (.minterface/.plist) <-> JSON")
    psub = pp.add_subparsers(dest="op", required=True)
    pp1 = psub.add_parser("decode"); pp1.add_argument("file"); pp1.add_argument("-o", "--out")
    pp1.set_defaults(func=cmd_plist_decode)
    pp2 = psub.add_parser("encode"); pp2.add_argument("json"); pp2.add_argument("-o", "--out", required=True)
    pp2.set_defaults(func=cmd_plist_encode)

    # text
    pt = sub.add_parser("text", help="TEXT string archives (item names / dialogue / catalogs)")
    tsub = pt.add_subparsers(dest="op", required=True)
    t0 = tsub.add_parser("show"); t0.add_argument("file"); t0.add_argument("--range")
    t0.add_argument("--enc", default="utf-8"); t0.set_defaults(func=cmd_text_show)
    t1 = tsub.add_parser("decode"); t1.add_argument("file"); t1.add_argument("-o", "--out")
    t1.add_argument("--enc", default="utf-8"); t1.set_defaults(func=cmd_text_decode)
    t2 = tsub.add_parser("encode"); t2.add_argument("json"); t2.add_argument("-o", "--out", required=True)
    t2.add_argument("--enc", default="utf-8"); t2.set_defaults(func=cmd_text_encode)
    t3 = tsub.add_parser("add", help="append a NEW line to a TEXT archive (e.g. a new dialogue line "
                         "for rf3mc.<locale>); prints the new line id for retarget/insert")
    t3.add_argument("file"); t3.add_argument("--text", required=True, help="the new line's text")
    t3.add_argument("--enc", default="utf-8")
    t3.add_argument("--pad-to", type=int, dest="pad_to", metavar="N",
                    help="pad the archive to length N first, so the new line lands at the SAME id "
                         "in every locale (rf3mc.eng is 1 line longer than the others)")
    t3.add_argument("-o", "--out", required=True); t3.set_defaults(func=cmd_text_add)

    # texture
    px = sub.add_parser("texture", help=".texture decode/encode")
    xsub = px.add_subparsers(dest="op", required=True)
    x0 = xsub.add_parser("info", help="format, size, frame/mip list and container offsets")
    x0.add_argument("file"); x0.set_defaults(func=cmd_texture_info)
    x1 = xsub.add_parser("decode", help="decode to PNG (one frame, or every frame as a strip)")
    x1.add_argument("file"); x1.add_argument("-o", "--out")
    x1.add_argument("--frame", type=int, default=0, help="flipbook frame index (default 0)")
    x1.add_argument("--strip", action="store_true",
                    help="all frames side by side in one PNG (re-import with `encode --strip`)")
    x1.set_defaults(func=cmd_texture_decode)
    x2 = xsub.add_parser("encode", help="replace a texture's pixels from PNG(s) -- ANY template; "
                         "by default re-encoded in the template's own format (BC7/BC3/BC1 at the "
                         "same size, raw kept), so the file can go back in place with bundle patch")
    x2.add_argument("template", help="the shipped .texture to re-skin (dimensions must match)")
    x2.add_argument("png", nargs="+", help="one PNG, or one per flipbook frame (in frame order)")
    x2.add_argument("-o", "--out", required=True)
    x2.add_argument("--frame", type=int, help="replace only this flipbook frame (others keep their bytes)")
    x2.add_argument("--strip", action="store_true", help="the single PNG is a `decode --strip` strip")
    x2.add_argument("--fmt", choices=texture.ENCODE_FORMATS,
                    help="storage format: keep (default) = the template frame's own format; or force "
                         "BC7 / BC3 / BC1 / RGBA8 (4x the size of BC7) / RGBA4444 / ABGR1555 / GL_RED_8bpp")
    x2.set_defaults(func=cmd_texture_encode)

    # map
    pm = sub.add_parser("map", help=".rf4m map inspect")
    msub = pm.add_subparsers(dest="op", required=True)
    m0 = msub.add_parser("info"); m0.add_argument("file"); m0.set_defaults(func=cmd_map_info)
    mg0 = msub.add_parser("ground-export", help="stitch a map's ground-atlas layer into one PNG "
                          "(in-game orientation; the texture set is resolved from the map)")
    mg0.add_argument("map", help="map name, e.g. MAP_FIELD_01 (tiles are found next to its .rf4m)")
    mg0.add_argument("-o", "--out", required=True)
    mg0.add_argument("--layer", type=int, default=0, help="draw layer: 0 ground, 1 overlay ... (default 0)")
    mg0.add_argument("--composite", action="store_true", help="all layers composited (view only)")
    mg0.add_argument("--dir", help="folder holding the .rf4m and tiles (default: the extracted tree)")
    mg0.set_defaults(func=cmd_map_ground_export)
    mg1 = msub.add_parser("ground-import", help="split an edited ground-export PNG back into the "
                          "per-tile .texture files (same grid/sizes/rotation; loose-override ready)")
    mg1.add_argument("map"); mg1.add_argument("png", help="the edited ground-export PNG")
    mg1.add_argument("-o", "--out", required=True, help="output folder for <SET>_<LNN>.texture files")
    mg1.add_argument("--layer", type=int, default=0)
    mg1.add_argument("--dir", help="folder holding the .rf4m and tiles (default: the extracted tree)")
    mg1.add_argument("--fmt", choices=texture.ENCODE_FORMATS,
                     help="tile storage format: keep (default) = each tile's own format (BC7 stays "
                          "BC7 at the same size), or BC7 / BC3 / BC1 / RGBA8 / a raw format")
    mg1.set_defaults(func=cmd_map_ground_import)
    m1 = msub.add_parser("attr"); m1.add_argument("file"); m1.add_argument("-o", "--out")
    m1.set_defaults(func=cmd_map_attr)
    m2 = msub.add_parser("set", help="edit MOBJ record fields and write a new .rf4m")
    m2.add_argument("file"); m2.add_argument("index", type=int, help="MOBJ record index")
    m2.add_argument("fields", nargs="+", help="field assignments, e.g. f0=48 f6=6144 f14=500")
    m2.add_argument("-o", "--out", help="output .rf4m (default: overwrite source)")
    m2.set_defaults(func=cmd_map_set)
    m3 = msub.add_parser("params", help="show MOBJ record field meanings (per type or a whole map)")
    m3.add_argument("file", nargs="?", help=".rf4m file (lists each record's params)")
    m3.add_argument("--type", dest="type_id", help="a single type_id to describe (hex/dec)")
    m3.set_defaults(func=cmd_map_params)
    m4 = msub.add_parser("validate", help="check a map against the game loader's rules "
                                          "(exit 1 on a fatal finding)")
    m4.add_argument("file")
    m4.add_argument("--dir", help="folder holding the ground tiles (default: next to the .rf4m); "
                                  "needed to check the atlas against the ATTR grid")
    m4.add_argument("--map", help="real map name for resolving the ground texture set, e.g. MAP_FIELD_01 "
                                 "(default: the file name -- set this when working on a copy)")
    m4.add_argument("--no-ground", action="store_true",
                    help="skip the ground-atlas check (loader rules only)")
    m4.set_defaults(func=cmd_map_validate)
    m5 = msub.add_parser("resize-attr", help="resize the ATTR tile grid and list every derived "
                                             "artefact the resize invalidates")
    m5.add_argument("file")
    m5.add_argument("--width", type=int, required=True, help="new ATTR width in tiles")
    m5.add_argument("--height", type=int, required=True, help="new ATTR height in tiles")
    m5.add_argument("--origin", help="where the old (0,0) lands in the new grid, e.g. 4,4 "
                                     "(pads the left/top and pushes the content right/down)")
    m5.add_argument("--fill", default="0x2",
                    help="cell value for newly added tiles (default 0x2 = the block bit, so "
                         "padding is solid wall; 0 = empty)")
    m5.add_argument("--no-shift", action="store_true",
                    help="do NOT move MOBJ/MAPJ positions with the terrain when --origin is set")
    m5.add_argument("--dir", help="folder holding the ground tiles (default: next to the .rf4m)")
    m5.add_argument("--map", help="real map name for resolving the ground texture set, e.g. MAP_FIELD_01 "
                                 "(default: the file name -- set this when working on a copy)")
    m5.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    m5.add_argument("-o", "--out", help="output .rf4m (default: overwrite source)")
    m5.set_defaults(func=cmd_map_resize_attr)

    # ai
    pa = sub.add_parser("ai", help="AIBN behaviour scripts")
    asub = pa.add_subparsers(dest="op", required=True)
    a0 = asub.add_parser("disasm"); a0.add_argument("target")
    g = a0.add_mutually_exclusive_group()
    g.add_argument("--raw", action="store_true"); g.add_argument("--stats", action="store_true")
    a0.add_argument("-a", "--annotate", action="store_true",
                    help="append verified operand meanings/units (and scripted-action names) as comments")
    a0.add_argument("--flat", action="store_true",
                    help="one opcode per line with every structural token explicit (pre-2026-09-18 form) "
                         "instead of the language-style listing; both forms assemble back byte-exactly")
    a0.set_defaults(func=cmd_ai_disasm)
    a1 = asub.add_parser("asm"); a1.add_argument("file"); a1.add_argument("-o", "--out", required=True)
    a1.set_defaults(func=cmd_ai_asm)
    a2 = asub.add_parser("tokens"); a2.add_argument("target"); a2.set_defaults(func=cmd_ai_tokens)
    a3 = asub.add_parser("ops", help="verified opcode reference (all, or one by id/name)")
    a3.add_argument("opcode", nargs="?"); a3.set_defaults(func=cmd_ai_ops)
    a4 = asub.add_parser("actions", help="the 35 scripted actions invoked by opcode 0x26")
    a4.add_argument("slot", nargs="?", type=int); a4.set_defaults(func=cmd_ai_actions)

    # asatk (as_atk_*.bin attack-move timelines)
    pat = sub.add_parser("asatk", help="as_atk_*.bin attack-move timelines (hitbox/motion events)")
    atsub = pat.add_subparsers(dest="op", required=True)
    at0 = atsub.add_parser("show", help="decode a move into a labelled per-frame timeline")
    at0.add_argument("target"); at0.set_defaults(func=cmd_asatk_show)
    at1 = atsub.add_parser("summary", help="frames / hit-window / effects as JSON")
    at1.add_argument("target"); at1.set_defaults(func=cmd_asatk_summary)
    at2 = atsub.add_parser("ops", help="print the opcode table + confidence")
    at2.set_defaults(func=cmd_asatk_ops)
    at3 = atsub.add_parser("dump", help="canonical re-assemblable listing (raw operands)")
    at3.add_argument("target"); at3.set_defaults(func=cmd_asatk_dump)
    at4 = atsub.add_parser("asm", help="assemble a `dump` listing (edited) into as_atk_*.bin")
    at4.add_argument("text", help="listing file"); at4.add_argument("-o", "--out")
    at4.set_defaults(func=cmd_asatk_asm)
    at5 = atsub.add_parser("set", help="change one event: asatk set as_atk_sword_00 7 --arg 1.5q")
    at5.add_argument("target"); at5.add_argument("index", type=int)
    at5.add_argument("--op", help="new opcode (mnemonic, opN or number)")
    at5.add_argument("--arg", help="new operand (int, 0x hex, 1.5q, 90deg)")
    at5.add_argument("-o", "--out"); at5.set_defaults(func=cmd_asatk_set)
    at6 = atsub.add_parser("insert", help="insert an event at a stream index or at an animation frame")
    at6.add_argument("target"); at6.add_argument("op"); at6.add_argument("arg")
    at6.add_argument("--index", type=int); at6.add_argument("--frame", type=int)
    at6.add_argument("-o", "--out"); at6.set_defaults(func=cmd_asatk_insert)
    at7 = atsub.add_parser("delete", help="delete event INDEX")
    at7.add_argument("target"); at7.add_argument("index", type=int)
    at7.add_argument("-o", "--out"); at7.set_defaults(func=cmd_asatk_delete)

    # skill (XP-per-level curves rf3ParamSkillExp*; growth is via `param dump rf3ParamSkill`)
    psk = sub.add_parser("skill", help="skill XP curves + family->curve map")
    sksub = psk.add_subparsers(dest="op", required=True)
    sk0 = sksub.add_parser("curve", help="decode an XP-per-level curve file")
    sk0.add_argument("file"); sk0.add_argument("--upto", type=int, default=30)
    sk0.set_defaults(func=cmd_skill_curve)
    sk2 = sksub.add_parser("set", help="edit a curve: skill set rf3ParamSkillExp.bin 5 120 -o out.bin | "
                                       "--scale 50 (every level x0.5 = level twice as fast)")
    sk2.add_argument("file"); sk2.add_argument("level_xp", nargs="*", metavar="LEVEL XP",
                                               help="a level (0..99) and its new XP-to-next")
    sk2.add_argument("--scale", type=float, help="percentage applied to every level's XP (100 = unchanged)")
    sk2.add_argument("-o", "--out", required=True); sk2.set_defaults(func=cmd_skill_set)
    sk1 = sksub.add_parser("family", help="which XP-curve archive a skill id uses")
    sk1.add_argument("skill_id", nargs="?", help="skill id (omit to list all)")
    sk1.set_defaults(func=cmd_skill_family)

    # str (rf3ItemStrengthening: forge material rows, dish ingredient bonuses, craft flags)
    pst = sub.add_parser("str", help="forge materials / dish ingredients / craft flags (rf3ItemStrengthening)")
    stsub = pst.add_subparsers(dest="op", required=True)
    st0 = stsub.add_parser("show", help="decode one or more rows by id or item name")
    st0.add_argument("item", nargs="+", help="item id, item name, or tier row 1108..1149")
    st0.add_argument("--file", help="rf3ItemStrengthening.bin (default: auto-locate)")
    st0.set_defaults(func=cmd_str_show)
    st1 = stsub.add_parser("list", help="list rows (nonzero fields by default)")
    st1.add_argument("--field", help="show one field only, e.g. atk, reach_scale, status_word")
    st1.add_argument("--group", help="show one group: core knob attack_proc resist reach heal status fed_buff fed_resist fed_proc element")
    st1.add_argument("--flag", choices=("nonfood", "food"), help="only rows with / without the NON-FOOD marker")
    st1.add_argument("--all", action="store_true", help="include all-zero rows")
    st1.add_argument("--limit", type=int, default=0)
    st1.add_argument("--file")
    st1.set_defaults(func=cmd_str_list)
    st2 = stsub.add_parser("flags", help="status-word histogram + the NON-FOOD marker by item category")
    st2.add_argument("--file")
    st2.set_defaults(func=cmd_str_flags)
    st3 = stsub.add_parser("specials", help="id-keyed forge behaviour (elements, ability bits, multipliers)")
    st3.add_argument("--file")
    st3.set_defaults(func=cmd_str_specials)
    st4 = stsub.add_parser("fields", help="the 74-dword record reference with readers")
    st4.set_defaults(func=cmd_str_fields)
    st5 = stsub.add_parser("dump", help="dump every row as CSV (or --json)")
    st5.add_argument("-o", "--out"); st5.add_argument("--json", action="store_true")
    st5.add_argument("--all", action="store_true", help="json: include zero fields")
    st5.add_argument("--file")
    st5.set_defaults(func=cmd_str_dump)
    st6 = stsub.add_parser("set", help="edit fields of one row: str set 887 atk=500 reach_scale=2048 -o new.bin")
    st6.add_argument("item"); st6.add_argument("set", nargs="+", help="name=value (see `str fields`)")
    st6.add_argument("-o", "--out", help="write here (default: overwrite the resolved file)")
    st6.add_argument("--file")
    st6.set_defaults(func=cmd_str_set)

    # schedule (rf3Schedule NPC daily-routine itineraries + rf3ScheduleID spots)
    psh = sub.add_parser("schedule", help="NPC daily-schedule itineraries (rf3Schedule + rf3ScheduleID)")
    shsub = psh.add_subparsers(dest="op", required=True)
    sh0 = shsub.add_parser("show", help="decode itineraries: per (npc, state) time -> spot -> room")
    sh0.add_argument("file", nargs="?", help="rf3Schedule.bin (default: auto-locate)")
    sh0.add_argument("--npc", help="only this NPC (id 0..47 or name, e.g. Vishnal)")
    sh0.add_argument("--state", help="only this state: 0..17 or weekday0..5 / rain0..5 / festival / festival21 / married / date")
    sh0.add_argument("--id", help="the Nth schedule in file order (legacy)")
    sh0.add_argument("--limit", type=int, default=8, help="max schedules to print (default 8)")
    sh0.set_defaults(func=cmd_schedule_show)
    sh1 = shsub.add_parser("decode", help="rf3Schedule.bin -> JSON (edit, then `schedule encode`)")
    sh1.add_argument("file", nargs="?"); sh1.add_argument("-o", "--out")
    sh1.add_argument("--bare", action="store_true", help="omit the informational 'where' annotations")
    sh1.set_defaults(func=cmd_schedule_decode)
    sh2 = shsub.add_parser("encode", help="JSON -> rf3Schedule.bin (directory sections recomputed)")
    sh2.add_argument("json"); sh2.add_argument("-o", "--out", help="default: <json stem>.bin")
    sh2.set_defaults(func=cmd_schedule_encode)
    sh3 = shsub.add_parser("set", help="edit one stop: schedule set Vishnal weekday0 3 --time 07:30 --spot 26")
    sh3.add_argument("npc"); sh3.add_argument("state"); sh3.add_argument("index", help="stop index (see `show --npc`)")
    sh3.add_argument("--time", help="HH:MM in 15-minute steps (06:00 = day start, 24:00.. allowed)")
    sh3.add_argument("--spot", help="spot kind 0..370 (see `schedule spots K`)")
    sh3.add_argument("--flags", help="bit0 = random departure time")
    sh3.add_argument("--file"); sh3.add_argument("-o", "--out", help="write here (default: overwrite the resolved file)")
    sh3.set_defaults(func=cmd_schedule_set)
    sh4 = shsub.add_parser("add", help="insert a stop (kept in time order; creates the (npc,state) schedule if absent)")
    sh4.add_argument("npc"); sh4.add_argument("state")
    sh4.add_argument("--time", required=True); sh4.add_argument("--spot", required=True)
    sh4.add_argument("--flags", default="0")
    sh4.add_argument("--file"); sh4.add_argument("-o", "--out")
    sh4.set_defaults(func=cmd_schedule_add)
    sh5 = shsub.add_parser("remove", help="delete a stop by index")
    sh5.add_argument("npc"); sh5.add_argument("state"); sh5.add_argument("index")
    sh5.add_argument("--file"); sh5.add_argument("-o", "--out")
    sh5.set_defaults(func=cmd_schedule_remove)
    sh6 = shsub.add_parser("spots", help="list the rf3ScheduleID records a spot kind resolves to")
    sh6.add_argument("kind", nargs="?", help="spot kind (omit for all 371)")
    sh6.set_defaults(func=cmd_schedule_spots)

    # gift (NPC gift-preference tables rf3PresentNpc01..27)
    pgf = sub.add_parser("gift", help="NPC gift preferences (loved/liked/disliked items)")
    gfsub = pgf.add_subparsers(dest="op", required=True)
    gf0 = gfsub.add_parser("show", help="decode an NPC's gift table (char name, stem, or number)")
    gf0.add_argument("target"); gf0.set_defaults(func=cmd_gift_show)
    gf1 = gfsub.add_parser("list", help="one-line loved-items summary for all 27 NPCs")
    gf1.set_defaults(func=cmd_gift_list)
    gf2 = gfsub.add_parser("categories", help="dump the 21 shared gift categories (rf3PresentCategory)")
    gf2.set_defaults(func=cmd_gift_categories)
    gf3 = gfsub.add_parser("monster", help="monster taming-food preferences (rf3MonsterPresent)")
    gf3.add_argument("species", nargs="?", help="species id (omit to list all)")
    gf3.set_defaults(func=cmd_gift_monster)
    gf4 = gfsub.add_parser("set", help="move an item to a tier: gift set Raven Skull loved --fp 20")
    gf4.add_argument("npc", help="character name, file number 1..27, or rf3PresentNpcNN.bin")
    gf4.add_argument("item", help="item id / name, or cat:N (category cross-ref) / range:N (item-id range tag)")
    gf4.add_argument("tier", help="loved | liked | disliked | neutral")
    gf4.add_argument("--fp", type=int, help="friendship points for loved/liked (default 15 / 9)")
    gf4.add_argument("--signature", action="store_true", help="disliked: make it the -10 signature/hated entry")
    gf4.add_argument("--group", type=int, default=0)
    gf4.add_argument("-o", "--out", help="write here (default: overwrite the resolved file)")
    gf4.set_defaults(func=cmd_gift_set)
    gf5 = gfsub.add_parser("add", help="same as `gift set` (item -> tier); kept for symmetry with `remove`")
    gf5.add_argument("npc"); gf5.add_argument("item"); gf5.add_argument("tier")
    gf5.add_argument("--fp", type=int); gf5.add_argument("--signature", action="store_true")
    gf5.add_argument("--group", type=int, default=0); gf5.add_argument("-o", "--out")
    gf5.set_defaults(func=cmd_gift_set)
    gf6 = gfsub.add_parser("remove", help="drop an item/target from every tier (-> neutral, +5 FP)")
    gf6.add_argument("npc"); gf6.add_argument("item")
    gf6.add_argument("--group", type=int, default=0); gf6.add_argument("-o", "--out")
    gf6.set_defaults(func=cmd_gift_remove)
    gf7 = gfsub.add_parser("signature", help="make an item the ONE signature/hated dislike (-10 FP)")
    gf7.add_argument("npc"); gf7.add_argument("item")
    gf7.add_argument("--keep-others", action="store_true", help="do not demote other 0xFFF6 entries to generic (-5)")
    gf7.add_argument("--group", type=int, default=0); gf7.add_argument("-o", "--out")
    gf7.set_defaults(func=cmd_gift_signature)
    gf8 = gfsub.add_parser("monster-set", help="tame food: gift monster-set 52 auto Onigiri 15")
    gf8.add_argument("species", help="species id 48..253 (or name)")
    gf8.add_argument("slot", help="0..3, or auto (existing slot for the item, else first empty)")
    gf8.add_argument("item"); gf8.add_argument("bonus", help="tame bonus added to the roll (u16)")
    gf8.add_argument("--file"); gf8.add_argument("-o", "--out")
    gf8.set_defaults(func=cmd_gift_monster_set)
    gf9 = gfsub.add_parser("monster-clear", help="empty a tame-food slot: gift monster-clear 52 1 | gift monster-clear 52 item --item Onigiri")
    gf9.add_argument("species"); gf9.add_argument("slot", help="0..3, or 'item' with --item")
    gf9.add_argument("--item"); gf9.add_argument("--file"); gf9.add_argument("-o", "--out")
    gf9.set_defaults(func=cmd_gift_monster_clear)

    # route (rf3route.bin TRCS NPC navigation graph + rf3RouteResult.bin next-hop matrix)
    prt = sub.add_parser("route", help="NPC town-navigation graph (rf3route) + next-hop matrix (rf3RouteResult)")
    rtsub = prt.add_subparsers(dest="op", required=True)
    rt0 = rtsub.add_parser("info", help="rooms, nodes (tile coords, jitter) and edges (dest, cost)")
    rt0.add_argument("file", nargs="?", help="rf3route.bin (default: auto-locate)")
    rt0.set_defaults(func=cmd_route_info)
    rt1 = rtsub.add_parser("decode", help="rf3route.bin -> JSON")
    rt1.add_argument("file", nargs="?"); rt1.add_argument("-o", "--out")
    rt1.set_defaults(func=cmd_route_decode)
    rt2 = rtsub.add_parser("encode", help="JSON -> rf3route.bin (room table + running indices regenerated)")
    rt2.add_argument("json"); rt2.add_argument("-o", "--out", help="default: <json stem>.bin")
    rt2.add_argument("--result", help="also regenerate the next-hop matrix into this rf3RouteResult.bin")
    rt2.set_defaults(func=cmd_route_encode)
    rt3 = rtsub.add_parser("path", help="walk the next-hop matrix like the game: route path room:65 room:24")
    rt3.add_argument("src", help="node id or room:ROOM[:k]"); rt3.add_argument("dst")
    rt3.add_argument("--file"); rt3.add_argument("--result", help="rf3RouteResult.bin (default: auto-locate)")
    rt3.set_defaults(func=cmd_route_path)
    rt4 = rtsub.add_parser("rebuild-result", help="recompute rf3RouteResult.bin from the graph (after editing it)")
    rt4.add_argument("--file"); rt4.add_argument("-o", "--out", help="default: overwrite the resolved rf3RouteResult.bin")
    rt4.set_defaults(func=cmd_route_rebuild_result)

    # monster (rf3NpcParam.bin monster/character template DB, archive 14812)
    pmo = sub.add_parser("monster", help="monster/character templates (stats, drops, elements, AI)")
    mosub = pmo.add_subparsers(dest="op", required=True)
    mo0 = mosub.add_parser("show", help="full decoded monster sheet (by char_id or name)")
    mo0.add_argument("who", help="char_id number or exact monster name (e.g. 48 or Orc)")
    mo0.add_argument("--file", help="rf3NpcParam.bin (default: auto-locate)")
    mo0.set_defaults(func=cmd_monster_show)
    mo1 = mosub.add_parser("list", help="one-line-per-monster roster")
    mo1.add_argument("--file"); mo1.add_argument("--range", help="id range LO-HI (default 48-253)")
    mo1.set_defaults(func=cmd_monster_list)
    mo2 = mosub.add_parser("free", help="list cut/unused ids usable for a data-only new monster")
    mo2.add_argument("--file"); mo2.set_defaults(func=cmd_monster_free)
    mo3 = mosub.add_parser("set", help="edit template fields (hp/atk/def/mat/kill_xp/ai_script/"
                                       "model/anim/dropN_id/dropN_pm/elem_*/res_*)")
    mo3.add_argument("record", help="char_id number or exact monster name")
    mo3.add_argument("--set", nargs="+", required=True, metavar="FIELD=VALUE",
                     help="e.g. --set hp=1200 atk=90 drop0_id=95 drop0_pm=200 elem_fire=4096")
    mo3.add_argument("--file"); mo3.add_argument("-o", "--out")
    mo3.set_defaults(func=cmd_monster_set)
    mo4 = mosub.add_parser("clone", help="copy a monster's whole 308-byte template into another slot")
    mo4.add_argument("--src", type=int, required=True, help="source char_id to copy FROM")
    mo4.add_argument("--dst", type=int, required=True, help="target char_id to overwrite")
    mo4.add_argument("--file"); mo4.add_argument("-o", "--out")
    mo4.set_defaults(func=cmd_monster_clone)
    mo5 = mosub.add_parser("new", help="scaffold a DATA-ONLY new monster end-to-end "
                                       "(clone + name + encounter + package)")
    mo5.add_argument("--name", required=True, help="display name for the new monster")
    mo5.add_argument("--from", dest="src", required=True, help="base monster to clone (id or name)")
    mo5.add_argument("--slot", type=int, help="target cut char_id (default: first free, e.g. 179)")
    mo5.add_argument("--set", nargs="+", metavar="FIELD=VALUE",
                     help="field overrides applied after the clone (e.g. hp=1500 atk=120)")
    mo5.add_argument("--encounter", metavar="GENFILE[:GATE]",
                     help="add to an encounter table by repointing a spawn (e.g. GenA01.bin)")
    mo5.add_argument("--locales", help="comma list for the name table (default: eng)")
    mo5.add_argument("--npc-param", dest="npc_param", help="rf3NpcParam.bin (default: auto-locate)")
    mo5.add_argument("--out-dir", dest="out_dir", required=True, help="output folder for the mod files")
    mo5.set_defaults(func=cmd_monster_new)

    # script (rf3.mc cutscene/event bytecode)
    psc = sub.add_parser("script", help="rf3.mc cutscene / event Script-VM bytecode")
    scsub = psc.add_subparsers(dest="op", required=True)
    sc0 = scsub.add_parser("info", help="container summary + coverage")
    sc0.add_argument("file"); sc0.set_defaults(func=cmd_script_info)
    sc1 = scsub.add_parser("disasm", help="disassemble scenes (--text resolves dialogue)")
    sc1.add_argument("file"); sc1.add_argument("--bank", type=int, default=None)
    sc1.add_argument("--text", help="rf3mc.<locale> TEXT archive for dialogue lines")
    sc1.add_argument("--friendly", action="store_true",
                     help="use cutscene-author mnemonics (WarpPlayer) instead of technical names")
    sc1.add_argument("-o", "--out"); sc1.set_defaults(func=cmd_script_disasm)
    sc2 = scsub.add_parser("find", help="find scenes whose dialogue contains TEXT")
    sc2.add_argument("file"); sc2.add_argument("query")
    sc2.add_argument("--text", required=True); sc2.add_argument("--limit", type=int, default=30)
    sc2.set_defaults(func=cmd_script_find)
    sc3 = scsub.add_parser("set-dialog", help="retarget a DIALOG to another line id")
    sc3.add_argument("file"); sc3.add_argument("--bank", type=int, required=True)
    sc3.add_argument("--pc", required=True, help="statement PC (hex ok, e.g. 0x3478)")
    sc3.add_argument("--line", type=int, required=True)
    sc3.add_argument("-o", "--out", required=True); sc3.set_defaults(func=cmd_script_set_dialog)
    sc4 = scsub.add_parser("set-arg", help="repoint an action arg to another expression offset")
    sc4.add_argument("file"); sc4.add_argument("--bank", type=int, required=True)
    sc4.add_argument("--pc", required=True); sc4.add_argument("--index", type=int, required=True)
    sc4.add_argument("--value", type=int, required=True)
    sc4.add_argument("-o", "--out", required=True); sc4.set_defaults(func=cmd_script_set_arg)
    sc6 = scsub.add_parser("set-val", help="set an immediate VALUE in place: an action arg, OR (for "
                           "a control op) the --index-th literal of its guard/value expr "
                           "(STORE value, BR_Z threshold, RAND_BR weight)")
    sc6.add_argument("file"); sc6.add_argument("--bank", type=int, required=True)
    sc6.add_argument("--pc", required=True); sc6.add_argument("--index", type=int, required=True)
    sc6.add_argument("--value", type=int, required=True)
    sc6.add_argument("-o", "--out", required=True); sc6.set_defaults(func=cmd_script_set_val)
    sc6t = scsub.add_parser("set-target", help="retarget a branch/jump/choice destination to "
                            "another statement pc (BR_Z/BR_NZ/JMP/SWITCH/RAND_BR/PROMPT_CHOICE)")
    sc6t.add_argument("file"); sc6t.add_argument("--bank", type=int, required=True)
    sc6t.add_argument("--pc", required=True, help="the branch statement's PC (hex ok)")
    sc6t.add_argument("--index", type=int, required=True,
                      help="which target (0-based; for PROMPT_CHOICE 0=cancel, 1..N=per-option)")
    sc6t.add_argument("--target", required=True, help="destination statement PC (hex ok); must be "
                      "a real statement start in the bank")
    sc6t.add_argument("-o", "--out", required=True); sc6t.set_defaults(func=cmd_script_set_target)
    sc7 = scsub.add_parser("insert", help="insert a new statement (beat) after/before a statement")
    sc7.add_argument("file"); sc7.add_argument("--bank", type=int, required=True)
    sc7.add_argument("--pc", required=True)
    sc7.add_argument("--dialogue", type=int, help="dialogue line id to show")
    sc7.add_argument("--action", help="action op + args, e.g. '55 3 5'")
    sc7.add_argument("--before", action="store_true", help="insert before (default: after)")
    sc7.add_argument("-o", "--out", required=True); sc7.set_defaults(func=cmd_script_insert)
    sc8 = scsub.add_parser("delete", help="delete (jump over) a statement")
    sc8.add_argument("file"); sc8.add_argument("--bank", type=int, required=True)
    sc8.add_argument("--pc", required=True)
    sc8.add_argument("-o", "--out", required=True); sc8.set_defaults(func=cmd_script_delete)
    sc9 = scsub.add_parser("rewrite", help="replace a scene's body (author a cutscene on an existing trigger)")
    sc9.add_argument("file"); sc9.add_argument("--bank", type=int, required=True)
    sc9.add_argument("--pc", required=True, help="scene entry pc")
    sc9.add_argument("--beats", required=True,
                     help="beats: 'd:8709;a:55,3,5;d:66494'  (d:lineid, a:opcode,args)")
    sc9.add_argument("-o", "--out", required=True); sc9.set_defaults(func=cmd_script_rewrite)
    sc11 = scsub.add_parser("set-speaker", help="change who speaks a line (rewrite a SetSpeaker op's "
                            "speaker + side; byte-exact)")
    sc11.add_argument("file"); sc11.add_argument("--bank", type=int, required=True)
    sc11.add_argument("--pc", required=True, help="the SetSpeaker statement PC")
    sc11.add_argument("--speaker", required=True, help="speaker slot (0-29) or name (e.g. Vishnal)")
    sc11.add_argument("--side", choices=("left", "right"), default="left")
    sc11.add_argument("-o", "--out", required=True); sc11.set_defaults(func=cmd_script_set_speaker)
    sc5 = scsub.add_parser("set-text", help="edit a dialogue line in rf3mc.<locale>")
    sc5.add_argument("file"); sc5.add_argument("--line", type=int, required=True)
    sc5.add_argument("--text", required=True, dest="text")
    sc5.add_argument("-o", "--out", required=True); sc5.set_defaults(func=cmd_script_set_text)
    # authoring layer (rf4s_modkit.scriptasm): listings, assembler, triggers
    sc7.add_argument("--stmt", help="listing text to insert (statements separated by ' / ' or "
                     "'\\n'; full syntax: expressions, BR_Z/STORE, labels)")
    sc7.add_argument("--listing", help="file with listing text to insert")
    sc9.add_argument("--listing", help="file with the new body as listing text (instead of --beats)")
    sc9._actions[[i for i, x in enumerate(sc9._actions) if "--beats" in x.option_strings][0]].required = False
    scl = scsub.add_parser("listing", help="re-assemblable listing of a scene (--pc) or a whole bank")
    scl.add_argument("file"); scl.add_argument("--bank", type=int, required=True)
    scl.add_argument("--pc", help="scene entry pc (default: every scene of the bank)")
    scl.add_argument("--text", help="rf3mc.<locale> for dialogue comments")
    scl.add_argument("--registered-only", action="store_true", help="skip discovered scenes")
    scl.add_argument("-o", "--out"); scl.set_defaults(func=cmd_script_listing)
    sca = scsub.add_parser("asm", help="assemble a listing: replace a scene body (--pc) or append it")
    sca.add_argument("file"); sca.add_argument("--bank", type=int, required=True)
    sca.add_argument("--pc", help="scene entry pc to rewrite (omit to only append the region)")
    sca.add_argument("--listing", help="listing file"); sca.add_argument("--stmt", help="inline listing")
    sca.add_argument("-o", "--out", required=True); sca.set_defaults(func=cmd_script_asm)
    scc = scsub.add_parser("check", help="syntax-check a listing (labels, opcodes, variables)")
    scc.add_argument("file", nargs="?", default="rf3.mc")
    scc.add_argument("--listing"); scc.add_argument("--stmt"); scc.set_defaults(func=cmd_script_check)
    sce = scsub.add_parser("expr", help="compile an expression ('REG_WIFE_ID == 11') to bytes, or decode --hex")
    sce.add_argument("expr", nargs="?", default="")
    sce.add_argument("--hex", help="decode these expression bytes instead")
    sce.add_argument("--file", default="rf3.mc", help="rf3.mc (for the header masks / names)")
    sce.set_defaults(func=cmd_script_expr)
    scn = scsub.add_parser("entries", help="dump a bank's type table: the scene triggers and their keys")
    scn.add_argument("file"); scn.add_argument("--bank", type=int, default=None,
                                               help="container bank index (default: summary of all)")
    scn.add_argument("-v", "--verbose", action="store_true")
    scn.add_argument("--recipes", action="store_true",
                     help="also print each type's 'how to register a new scene of this type' recipe")
    scn.set_defaults(func=cmd_script_entries)
    scae = scsub.add_parser("add-entry", help="register a NEW scene trigger (mint a scene from a listing, "
                            "or point a new entry at an existing scene)")
    scae.add_argument("file"); scae.add_argument("--bank", type=int, required=True)
    scae.add_argument("--type", type=int, required=True, help="action type (see `entries`)")
    scae.add_argument("--keys", default="", help="entry keys: '5, -1' or 'tag:value' items; x = wildcard")
    scae.add_argument("--pc", help="existing scene pc to register")
    scae.add_argument("--listing", help="listing file for a new scene body")
    scae.add_argument("--stmt", help="inline listing for a new scene body")
    scae.add_argument("--position", type=int, default=None, help="index in the list (default: append)")
    scae.add_argument("-o", "--out", required=True); scae.set_defaults(func=cmd_script_add_entry)
    scre = scsub.add_parser("remove-entry", help="unregister a scene trigger (its code stays)")
    scre.add_argument("file"); scre.add_argument("--bank", type=int, required=True)
    scre.add_argument("--type", type=int, required=True); scre.add_argument("--index", type=int, required=True)
    scre.add_argument("-o", "--out", required=True); scre.set_defaults(func=cmd_script_remove_entry)
    scse = scsub.add_parser("set-entry", help="re-key a trigger and/or point it at another scene")
    scse.add_argument("file"); scse.add_argument("--bank", type=int, required=True)
    scse.add_argument("--type", type=int, required=True); scse.add_argument("--index", type=int, required=True)
    scse.add_argument("--keys", default=None); scse.add_argument("--pc", default=None)
    scse.add_argument("-o", "--out", required=True); scse.set_defaults(func=cmd_script_set_entry)

    # em (Event Manager)
    pem = sub.add_parser("em", help="em.bin Event Manager (named trigger conditions/actions)")
    emsub = pem.add_subparsers(dest="op", required=True)
    e0 = emsub.add_parser("list", help="list all 272 entries")
    e0.add_argument("--filter", help="substring filter on the entry name")
    e1 = emsub.add_parser("show", help="decode one entry (conditions + actions, by id or name)")
    e1.add_argument("entry")
    e2 = emsub.add_parser("queries", help="list the 218 named game-state queries")
    e3 = emsub.add_parser("xref", help="scan rf3.mc for CondScript bridge ops -> entry names")
    e3.add_argument("mc", nargs="?", default=str(REPO / "Bundle" / "bundlePatch1" / "rf3.mc"))
    e4 = emsub.add_parser("set", help="edit a condition/action in place (byte-safe)")
    e4.add_argument("entry", help="entry id or name (e.g. EV_BOSS_SP_DEAD)")
    e4.add_argument("--cond", choices=("a", "b"), help="target a condition (use --slot/--expr)")
    e4.add_argument("--slot", type=int, default=0, help="condition OR-slot index (default 0)")
    e4.add_argument("--expr", type=int, default=0, help="expr index within the slot (default 0)")
    e4.add_argument("--operand", type=int, choices=(1, 2),
                    help="which cmp operand to set (default: the literal one)")
    e4.add_argument("--action", choices=("main", "alt"), help="target an action (use --index)")
    e4.add_argument("--index", type=int, default=0, help="action index (default 0)")
    e4.add_argument("--value", help="new immediate value (int; 0x.. accepted)")
    e4.add_argument("--op", help="new operator (==,!=,>,>=) or action op (SET/ADD/SUB/...)")
    e4.add_argument("--entry-ref", dest="entry_ref",
                    help="repoint a CALL action / condA-B reference to this entry id")
    e4.add_argument("--target", help="retarget which FLG_/REG_ an action WRITES (its destination, "
                    "vs --value = the value written) -- a flag name (e.g. FLG_SUBEV_A) or bit offset")
    e4.add_argument("-o", "--out", help="output em.bin (default: overwrite --em / auto-found)")
    for _ep in (e0, e1, e2, e3, e4):
        _ep.add_argument("--em", help="path to em.bin (default: auto-find)")
        _ep.add_argument("--emdeb", help="path to emdeb.bin (default: auto-find)")
    e0.set_defaults(func=cmd_em_list); e1.set_defaults(func=cmd_em_show)
    e2.set_defaults(func=cmd_em_queries); e3.set_defaults(func=cmd_em_xref)
    e4.set_defaults(func=cmd_em_set)
    # structural edits (container rebuilt: offsets/counts regenerated, stock rebuilds byte-exact)
    _spec_help = ("condition spec: OR-groups joined by AND, terms by OR, e.g. "
                  "\"Hour >= 6 AND (12 > Hour OR FLG_RAINBOW == 1) AND !condA(EV_DATE_APPO)\"; "
                  "operands: number, query name (Hour), emdeb variable (REG_/FLG_), flag@BIT/W")
    _act_help = ("action spec: \"REG_X = 5\" | \"REG_X += 2\" (-= *= /= %%=) | "
                 "\"FLG_Y = (REG_X == 0)\" | \"MAX_U REG_X 5\" | \"CALL ENTRY\"")
    e5 = emsub.add_parser("add", help="append a NEW entry (clone of --clone and/or from specs); prints its id")
    e5.add_argument("--clone", help="entry id/name to copy conditions + actions from")
    e5.add_argument("--name", help="in-memory label for the printout (emdeb.bin is not rewritten)")
    e5.add_argument("--cond-a", dest="cond_a", action="append", metavar="SPEC", help="one OR-slot of condition A; repeatable. " + _spec_help)
    e5.add_argument("--cond-b", dest="cond_b", action="append", metavar="SPEC", help="one OR-slot of condition B; repeatable")
    e5.add_argument("--action", action="append", metavar="SPEC", help="a main-stream action; repeatable. " + _act_help)
    e5.add_argument("--alt-action", dest="alt_action", action="append", metavar="SPEC", help="an alt-stream action; repeatable")
    e6 = emsub.add_parser("remove", help="delete an entry (later ids shift) or --blank it in place")
    e6.add_argument("entry")
    e6.add_argument("--blank", action="store_true", help="clear conditions/actions but keep the id (safe)")
    e6.add_argument("--force", action="store_true", help="delete even if other entries reference it")
    e7 = emsub.add_parser("add-cond", help="add condition terms to an entry (new OR-slot, or --slot N)")
    e7.add_argument("entry"); e7.add_argument("expr", help=_spec_help)
    e7.add_argument("--cond", choices=("a", "b"), default="a", help="condition A (default) or B")
    e7.add_argument("--slot", type=int, help="AND the terms onto this existing OR-slot (default: a new slot)")
    e8 = emsub.add_parser("remove-cond", help="remove one expression (--expr) or a whole OR-slot")
    e8.add_argument("entry"); e8.add_argument("--cond", choices=("a", "b"), default="a")
    e8.add_argument("--slot", type=int, required=True); e8.add_argument("--expr", type=int)
    e9 = emsub.add_parser("add-action", help="append an action to the main/alt stream")
    e9.add_argument("entry"); e9.add_argument("action", help=_act_help)
    e9.add_argument("--stream", choices=("main", "alt"), default="main")
    e9.add_argument("--index", type=int, help="insert position (default: append)")
    e10 = emsub.add_parser("remove-action", help="remove an action by index")
    e10.add_argument("entry"); e10.add_argument("--index", type=int, required=True)
    e10.add_argument("--stream", choices=("main", "alt"), default="main")
    e11 = emsub.add_parser("new-var", help="define a NEW game-flag variable (FLG_/REG_) in the "
                           "emdeb_extra.json sidecar: free bits of the 4096-bit GameFlags store, "
                           "resolved by every tool (cutscene assembler, em conditions, editors)")
    e11.add_argument("name", help="identifier, e.g. FLG_MY_QUEST_DONE or REG_MY_COUNTER")
    e11.add_argument("--width", type=int, default=1, help="bits (1 = flag; registers 2..32)")
    e11.add_argument("--jp", default="", help="optional Japanese label")
    e11.add_argument("--bit", type=int, default=None, help="explicit bit offset (default: next free)")
    e11.add_argument("--extra", default=None, help="sidecar path (default: <bundle>/emdeb_extra.json)")
    e11.add_argument("--emdeb", help="path to emdeb.bin (default: auto-find)")
    e11.set_defaults(func=cmd_em_new_var)
    e12 = emsub.add_parser("vars", help="list game-flag variables (emdeb.bin + the sidecar extras)")
    e12.add_argument("--filter", default="", help="substring of the name")
    e12.add_argument("--extras-only", action="store_true")
    e12.add_argument("--extra", default=None); e12.add_argument("--emdeb")
    e12.set_defaults(func=cmd_em_vars)
    for _ep in (e5, e6, e7, e8, e9, e10):
        _ep.add_argument("-o", "--out", help="output em.bin (default: overwrite --em / auto-found)")
        _ep.add_argument("--em", help="path to em.bin (default: auto-find)")
        _ep.add_argument("--emdeb", help="path to emdeb.bin (default: auto-find)")
    e5.set_defaults(func=cmd_em_add); e6.set_defaults(func=cmd_em_remove)
    e7.set_defaults(func=cmd_em_add_cond); e8.set_defaults(func=cmd_em_remove_cond)
    e9.set_defaults(func=cmd_em_add_action); e10.set_defaults(func=cmd_em_remove_action)

    # save (rf4_sNN.sav per-slot save editor)
    psv = sub.add_parser("save", help="edit an rf4_sNN.sav save (named GameFlags + CRC)")
    svsub = psv.add_subparsers(dest="op", required=True)
    v0 = svsub.add_parser("show", help="summary (clock + crc validity)")
    v0.add_argument("sav", help="path to rf4_sNN.sav")
    v1 = svsub.add_parser("flag", help="read a named FLG_/REG_ GameFlag")
    v1.add_argument("sav"); v1.add_argument("name")
    v2 = svsub.add_parser("find-flags", help="list named flags matching a substring + values")
    v2.add_argument("sav"); v2.add_argument("substr"); v2.add_argument("--limit", type=int, default=60)
    v3 = svsub.add_parser("set-flag", help="set a named FLG_/REG_ GameFlag (recomputes CRC)")
    v3.add_argument("sav"); v3.add_argument("name"); v3.add_argument("value", help="int (0x.. ok)")
    v3.add_argument("-o", "--out", help="output path (default: overwrite in place)")
    v4 = svsub.add_parser("get", help="read a raw u32 at a byte offset")
    v4.add_argument("sav"); v4.add_argument("offset", help="0x..")
    v5 = svsub.add_parser("set", help="write a raw u32 at a byte offset (recomputes CRC)")
    v5.add_argument("sav"); v5.add_argument("offset"); v5.add_argument("value")
    v5.add_argument("-o", "--out", help="output path (default: overwrite in place)")
    v0.set_defaults(func=cmd_save_show); v1.set_defaults(func=cmd_save_flag)
    v2.set_defaults(func=cmd_save_find_flags); v3.set_defaults(func=cmd_save_set_flag)
    v4.set_defaults(func=cmd_save_get); v5.set_defaults(func=cmd_save_set)

    # strings
    ps = sub.add_parser("strings", help="Apple .strings <-> JSON")
    ssub = ps.add_subparsers(dest="op", required=True)
    s1 = ssub.add_parser("decode"); s1.add_argument("file"); s1.add_argument("-o", "--out")
    s1.set_defaults(func=cmd_strings_decode)
    s2 = ssub.add_parser("encode"); s2.add_argument("json"); s2.add_argument("-o", "--out", required=True)
    s2.set_defaults(func=cmd_strings_encode)

    # res
    pr = sub.add_parser("res", help="inspect NN containers (.model/.bfskl/.bfmat/.bfsha/.psbData); "
                                    "list / decode / replace the textures embedded in a .model")
    rsub = pr.add_subparsers(dest="op", required=True)
    r0 = rsub.add_parser("info"); r0.add_argument("file"); r0.set_defaults(func=cmd_res_info)
    r1 = rsub.add_parser("texture-list", help="list the textures of the BNTX embedded in a .model "
                         "(index, name, format, size)")
    r1.add_argument("file"); r1.set_defaults(func=cmd_res_texture_list)
    r2 = rsub.add_parser("texture-decode", help="decode one embedded texture to PNG (upright)")
    r2.add_argument("file"); r2.add_argument("index", type=int, help="from texture-list")
    r2.add_argument("-o", "--out", help="default <model>_<index>.png")
    r2.set_defaults(func=cmd_res_texture_decode)
    r3 = rsub.add_parser("texture-encode", help="replace one embedded texture from a PNG of the same "
                         "size, re-encoded IN PLACE in its own block format (file size unchanged)")
    r3.add_argument("file"); r3.add_argument("index", type=int, help="from texture-list")
    r3.add_argument("png"); r3.add_argument("-o", "--out", required=True)
    r3.add_argument("--fmt", choices=texture.ENCODE_FORMATS,
                    help="keep (default) = the texture's own format; another format only when its "
                         "payload has the same size (BC3 <-> BC7)")
    r3.set_defaults(func=cmd_res_texture_encode)

    # param (NLCL fixed-record param tables)
    pp2 = sub.add_parser("param", help="NLCL param tables (item/crop/price/recipe/skill/...)")
    psub2 = pp2.add_subparsers(dest="op", required=True)
    q0 = psub2.add_parser("info", help="show a param table (named fields if known)")
    q0.add_argument("file"); q0.add_argument("--limit", type=int, default=20)
    q0.set_defaults(func=cmd_param_info)
    q1 = psub2.add_parser("dump", help="dump every record's dwords as CSV")
    q1.add_argument("file"); q1.add_argument("-o", "--out")
    q1.set_defaults(func=cmd_param_dump)
    q2 = psub2.add_parser("get", help="show one record")
    q2.add_argument("file"); q2.add_argument("record", type=int)
    q2.set_defaults(func=cmd_param_get)
    q3 = psub2.add_parser("set", help="edit fields of a record: name=val | OFF=val | OFF:type=val")
    q3.add_argument("file"); q3.add_argument("record", type=int)
    q3.add_argument("set", nargs="+", help="e.g. sell_price=9999  or  12=9999  or  12:s32=9999")
    q3.add_argument("-o", "--out")
    q3.set_defaults(func=cmd_param_set)
    q4 = psub2.add_parser("csv", help="the named table view (schema columns + item names) as CSV")
    q4.add_argument("file"); q4.add_argument("-o", "--out")
    q4.add_argument("--raw", action="store_true", help="dw0..dwN columns instead of the schema names")
    q4.set_defaults(func=cmd_param_csv)
    q5 = psub2.add_parser("csv-all", help="export EVERY rf3*.bin param table as CSV into a folder")
    q5.add_argument("-o", "--out", required=True, help="output folder (one <stem>.csv per table)")
    q5.add_argument("--dir", help="folder to scan (default: the extracted bundle tree)")
    q5.add_argument("--raw", action="store_true", help="dw0..dwN columns for every table")
    q5.set_defaults(func=cmd_param_csv_all)
    q6 = psub2.add_parser("add", help="append a row (copy of --copy N or zeros) + --set fields: "
                                      "param add rf3ItemList.bin --copy 29 --set sell_price=50 -o out.bin")
    q6.add_argument("file"); q6.add_argument("--copy", type=int, help="record index to duplicate")
    q6.add_argument("--at", type=int, help="insert at this index instead of appending (shifts later rows)")
    q6.add_argument("--set", nargs="+", help="assignments for the new row (param set grammar)")
    q6.add_argument("-o", "--out", required=True); q6.set_defaults(func=cmd_param_add)
    q7 = psub2.add_parser("remove", help="delete a row (later rows shift down by one)")
    q7.add_argument("file"); q7.add_argument("index", type=int)
    q7.add_argument("-o", "--out", required=True); q7.set_defaults(func=cmd_param_remove)

    # crop (readable rf3CropParam front-end: season affinity + growth tuning)
    pc = sub.add_parser("crop", help="crops: readable season affinity + growth tuning (rf3CropParam)")
    csub = pc.add_subparsers(dest="op", required=True)
    c0 = csub.add_parser("list", help="list farm crops with their growing season(s)")
    c0.set_defaults(func=cmd_crop_list)
    c1 = csub.add_parser("show", help="show one crop with decoded season + growth fields")
    c1.add_argument("record", type=int)
    c1.set_defaults(func=cmd_crop_show)
    c2 = csub.add_parser("season", help="reseason a crop by name, e.g. season 40 --set winter")
    c2.add_argument("record", type=int)
    c2.add_argument("--set", required=True, metavar="SEASONS",
                    help="comma list of spring/summer/fall/winter (which season(s) it grows in)")
    c2.add_argument("--all-year", action="store_true",
                    help="don't penalize off-seasons (crop grows in the set seasons AND stays OK elsewhere)")
    c2.add_argument("-o", "--out", help="write here (default: overwrite the resolved file; use a Bundle/ path for a loose override)")
    c2.set_defaults(func=cmd_crop_season)

    # gen (Gen*.bin monster encounter tables)
    pg = sub.add_parser("gen", help="Gen*.bin dungeon/field monster encounter tables")
    gsub = pg.add_subparsers(dest="op", required=True)
    g0 = gsub.add_parser("info", help="show gates + monster roster of one Gen file")
    g0.add_argument("file"); g0.add_argument("--names", help="rf4s_actor_names.json")
    g0.set_defaults(func=cmd_gen_info)
    g1 = gsub.add_parser("area", help="aggregate roster across an area, e.g. GenA / GenField")
    g1.add_argument("prefix"); g1.add_argument("--names")
    g1.set_defaults(func=cmd_gen_area)
    g3 = gsub.add_parser("formap", help="find the Gen file for a map (e.g. MAP_DUNG_A04)")
    g3.add_argument("map"); g3.add_argument("--names")
    g3.set_defaults(func=cmd_gen_formap)
    g2 = gsub.add_parser("set", help="edit a gate entry (kind/weight/spawn) and write a new file")
    g2.add_argument("file"); g2.add_argument("pattern", type=int); g2.add_argument("entry", type=int)
    g2.add_argument("--gate", type=int, help="new gate kind id")
    g2.add_argument("--weight", type=int, help="new weight")
    g2.add_argument("--spawn", action="append", help="spawn edit IDX=MONSTER_ID (repeatable)")
    g2.add_argument("--level", action="append", help="level edit IDX=LEVEL (repeatable)")
    g2.add_argument("--weights", action="append",
                    help="per-monster-position weights IDX=w1,w2,... (repeatable)")
    g2.add_argument("--per-spawn", dest="per_spawn", help="monsters kept alive per gate, e.g. 2-4")
    g2.add_argument("--delay", type=int, help="respawn timer base in frames (hdr spawn_delay)")
    g2.add_argument("--names"); g2.add_argument("-o", "--out")
    g2.set_defaults(func=cmd_gen_set)
    g4 = gsub.add_parser("add-gate", help="append a gate cloned from an existing entry")
    g4.add_argument("file"); g4.add_argument("--pattern", type=int, default=0)
    g4.add_argument("--clone", type=int, default=0, help="entry to copy (default 0)")
    g4.add_argument("--gate", type=int, help="gate kind (default: the clone's)")
    g4.add_argument("--weight", type=int, help="weight (default: the clone's)")
    g4.add_argument("--share", action="store_true",
                    help="reuse the source's position/roster blocks instead of copying them")
    g4.add_argument("--names"); g4.add_argument("-o", "--out")
    g4.set_defaults(func=cmd_gen_add_gate)
    g5 = gsub.add_parser("remove-gate", help="delete a gate entry")
    g5.add_argument("file"); g5.add_argument("pattern", type=int); g5.add_argument("entry", type=int)
    g5.add_argument("--names"); g5.add_argument("-o", "--out")
    g5.set_defaults(func=cmd_gen_remove_gate)
    g6 = gsub.add_parser("add-monster", help="add a monster (id, level) to a gate's roster")
    g6.add_argument("file"); g6.add_argument("pattern", type=int); g6.add_argument("entry", type=int)
    g6.add_argument("monster", type=int); g6.add_argument("level", type=int)
    g6.add_argument("--weights", help="w1,w2,... one per monster position (default 10 each)")
    g6.add_argument("--names"); g6.add_argument("-o", "--out")
    g6.set_defaults(func=cmd_gen_add_monster)
    g7 = gsub.add_parser("remove-monster", help="remove roster entry INDEX from a gate")
    g7.add_argument("file"); g7.add_argument("pattern", type=int); g7.add_argument("entry", type=int)
    g7.add_argument("index", type=int)
    g7.add_argument("--names"); g7.add_argument("-o", "--out")
    g7.set_defaults(func=cmd_gen_remove_monster)
    g8 = gsub.add_parser("validate", help="check a Gen file for things the spawner trips over")
    g8.add_argument("file"); g8.set_defaults(func=cmd_gen_validate)

    # mapview (graphical map explorer)
    pmv = sub.add_parser("mapview", help="launch the interactive map explorer GUI")
    pmv.add_argument("map", nargs="?", help="map name or .rf4m path to open")
    pmv.set_defaults(func=cmd_mapview)

    # selftest
    pst = sub.add_parser("selftest", help="validate the toolkit against your installed bundles")
    pst.set_defaults(func=cmd_selftest)

    return p


def main(argv=None):
    _utf8_stdout()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
