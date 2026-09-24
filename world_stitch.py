"""world_stitch.py -- stitch the RF4S game world into PNG posters from MAPJ warps.

Every map's MAPJ records give (warp zone rect in THIS map, destination map id,
landing position in the TARGET map). Each warp therefore pins the two maps
together on a shared plane:

    origin[B] = origin[A] + warp_center_tiles(A) - landing_tiles(B)

The tool builds that constraint graph over the base (non-seasonal) .rf4m maps,
solves each connected component by spanning-tree placement + Gauss-Seidel
relaxation (with outlier-edge pruning), then pastes each map's GROUND-TEXTURE
composite (mapground.stitch_composite -- no ATTR fill, no overlays, alpha kept)
at a common px-per-tile scale.

Measured on the shipped data: warp reciprocity |d_AB + d_BA| has median 1.9
tiles across 707 reciprocal pairs, so the plane assumption holds well; the few
teleport-style outliers are pruned by residual.

Usage:
    python world_stitch.py                        # overworld (CITY+FARM+FIELD), 8 px/tile
    python world_stitch.py --families DUNG        # dungeon clusters
    python world_stitch.py --px 12 --min-comp 4   # bigger scale, skip tiny clusters
    python world_stitch.py --out C:/some/dir

Outputs into --out (default tools/modding/world_out):
    world_<family-set>_<N>.png   one per connected component (largest first)
    world_<family-set>_<N>.json  placements: {map: {x,y,w,h}} in tiles
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rf4s_modkit import rf4m, mapground  # noqa: E402

from PIL import Image

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
BUNDLE = REPO / "Bundle"
ROOMS_CSV = [
    REPO / "tools" / "rf4s_rooms.csv",
    pathlib.Path.home() / ".claude" / "projects" / "C--Users-arryn-Documents"
    / "memory" / "rf4s_rooms.csv",
]
SEASON = re.compile(r"_(SUMMER|AUTUMN|WINTER)$")
Image.MAX_IMAGE_PIXELS = None            # world posters are legitimately huge


def load_rooms():
    for p in ROOMS_CSV:
        if p.is_file():
            out = {}
            for row in csv.DictReader(p.open(encoding="utf-8", errors="replace")):
                try:
                    out[int(row["mapId"])] = row["name"]
                except (KeyError, ValueError):
                    pass
            return out
    raise SystemExit("rf4s_rooms.csv not found")


def make_reader():
    dirs = [d for d in BUNDLE.iterdir() if d.is_dir()]
    # bundleMain first (bulk of textures live there)
    dirs.sort(key=lambda d: (d.name != "bundleMain", d.name))

    def reader(name):
        for d in dirs:
            p = d / name
            if p.is_file():
                return p.read_bytes()
        return None
    return reader


def family(name):
    return name.split("_")[1] if "_" in name else name


def collect(maps_dir, id2name, families):
    """Parse base maps -> grids {name:(w,h)}, ATTR cells, constraint edges."""
    grids, cells, mapj = {}, {}, {}
    for p in sorted(maps_dir.glob("MAP_*.rf4m")):
        stem = p.name[:-5]
        if stem.endswith(".rf4m") or SEASON.search(stem):
            continue                     # seasonal variant / stray double-ext file
        try:
            m = rf4m.Rf4mMap.parse(p.read_bytes())
        except Exception:
            continue
        g = m.attr_grid()
        if not g:
            continue
        grids[stem] = (g[0], g[1])
        cells[stem] = g[2]
        mapj[stem] = m.mapj_records()

    keep = {n for n in grids if not families or family(n) in families}
    raw = defaultdict(list)              # (A,B) -> [offset(B relative to A) in tiles]
    for a in keep:
        for rec in mapj[a]:
            x, y, w, h = rec[1], rec[2], rec[3], rec[4]
            dn = id2name.get(rec[5])
            b = SEASON.sub("", dn) if dn else None
            if b is None or b == a or b not in keep:
                continue
            cx, cy = (x + w / 2) / 8.0, (y + h / 2) / 8.0
            raw[(a, b)].append((cx - rec[6] / 8.0, cy - rec[7] / 8.0))
    # one undirected constraint per pair: mean of A->B and reversed B->A offsets
    cons = {}
    for (a, b), offs in raw.items():
        if (b, a) in cons or (a, b) in cons:
            continue
        vals = list(offs)
        for ox, oy in raw.get((b, a), ()):
            vals.append((-ox, -oy))
        cons[(a, b)] = (sum(v[0] for v in vals) / len(vals),
                        sum(v[1] for v in vals) / len(vals))
    return grids, cells, keep, cons


def components(nodes, cons):
    adj = defaultdict(set)
    for a, b in cons:
        adj[a].add(b); adj[b].add(a)
    seen, comps = set(), []
    for n in sorted(nodes):
        if n in seen:
            continue
        stack, comp = [n], []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x); comp.append(x)
            stack += [y for y in adj[x] if y not in seen]
        comps.append(sorted(comp))
    comps.sort(key=len, reverse=True)
    return comps


def solve(comp, cons, grids, prune_tiles=20.0, rounds=3):
    """Positions (tile origins) for one component; prunes outlier constraints."""
    comp = set(comp)
    edges = {k: v for k, v in cons.items() if k[0] in comp and k[1] in comp}
    for _ in range(rounds):
        # BFS spanning-tree seed from the largest map
        root = max(comp, key=lambda n: grids[n][0] * grids[n][1])
        pos = {root: (0.0, 0.0)}
        adj = defaultdict(list)
        for (a, b), (ox, oy) in edges.items():
            adj[a].append((b, ox, oy))
            adj[b].append((a, -ox, -oy))
        queue = [root]
        while queue:
            a = queue.pop(0)
            for b, ox, oy in adj[a]:
                if b not in pos:
                    pos[b] = (pos[a][0] + ox, pos[a][1] + oy)
                    queue.append(b)
        placed = set(pos)
        # Gauss-Seidel relaxation over all constraints
        for _ in range(200):
            moved = 0.0
            for a in placed:
                tx = ty = n = 0
                for b, ox, oy in adj[a]:
                    if b in pos:
                        tx += pos[b][0] - ox; ty += pos[b][1] - oy; n += 1
                if n:
                    nx, ny = tx / n, ty / n
                    moved = max(moved, abs(nx - pos[a][0]) + abs(ny - pos[a][1]))
                    pos[a] = (nx, ny)
            if moved < 0.01:
                break
        # prune the worst inconsistent edges and re-solve
        bad = []
        for (a, b), (ox, oy) in edges.items():
            if a in pos and b in pos:
                r = abs(pos[b][0] - pos[a][0] - ox) + abs(pos[b][1] - pos[a][1] - oy)
                if r > prune_tiles:
                    bad.append((a, b))
        if not bad:
            break
        for k in bad:
            del edges[k]
        # keep only what stays reachable from root
        comp = set(components(comp, edges)[0]) if edges else {root}
    return pos


def _owned_mask(cells, w, h, px, dilate=1):
    """L-mode mask of the map's OWNED tiles (ATTR != 0 = playable / in-map),
    dilated by `dilate` tiles so cliff faces on the ownership boundary stay with
    their map, scaled to px/tile."""
    from PIL import ImageFilter
    m = Image.new("L", (w, h), 0)
    p = m.load()
    for y in range(h):
        row = y * w
        for x in range(w):
            if cells[row + x]:
                p[x, y] = 255
    if dilate:
        m = m.filter(ImageFilter.MaxFilter(2 * dilate + 1))
    return m.resize((w * px, h * px), Image.NEAREST)


def render(comp_pos, grids, cells, reader, px, out_png, quiet=False):
    """Two-pass paste so overlapping neighbours don't paint over each other:

    Adjacent RF4 maps intentionally duplicate a strip of the neighbour's
    scenery beyond their playable border, and warp landing points sit a few
    tiles inside the destination -- so correctly-placed neighbours OVERLAP.
    Pass 1 draws every map masked to the tiles it owns (ATTR != 0), largest
    first; pass 2 lets the decorative fringes fill only still-empty canvas.
    """
    from PIL import ImageChops
    xs0 = min(p[0] for p in comp_pos.values())
    ys0 = min(p[1] for p in comp_pos.values())
    xs1 = max(comp_pos[n][0] + grids[n][0] for n in comp_pos)
    ys1 = max(comp_pos[n][1] + grids[n][1] for n in comp_pos)
    W, H = int(round((xs1 - xs0) * px)), int(round((ys1 - ys0) * px))
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    order = sorted(comp_pos, key=lambda n: grids[n][0] * grids[n][1], reverse=True)
    ok = miss = 0
    imgs = {}
    for i, name in enumerate(order):
        w, h = grids[name]
        res = mapground.stitch_composite(reader, name, aspect=(w, h))
        if res is None:
            miss += 1
            continue
        img = res[0]
        if img.size != (w * px, h * px):
            img = img.resize((w * px, h * px), Image.LANCZOS)
        imgs[name] = img
        ox = int(round((comp_pos[name][0] - xs0) * px))
        oy = int(round((comp_pos[name][1] - ys0) * px))
        owned = ImageChops.multiply(img.getchannel("A"),
                                    _owned_mask(cells[name], w, h, px))
        canvas.paste(img, (ox, oy), owned)          # pass 1: owned tiles only
        ok += 1
        if not quiet:
            print("  [%3d/%3d] %-24s at (%6d,%6d)" % (i + 1, len(order), name, ox, oy))
    # pass 2: decorative fringes -- only where the canvas is still empty
    for name, img in imgs.items():
        w, h = grids[name]
        ox = int(round((comp_pos[name][0] - xs0) * px))
        oy = int(round((comp_pos[name][1] - ys0) * px))
        hole = canvas.crop((ox, oy, ox + w * px, oy + h * px)).getchannel("A")
        empty = hole.point(lambda a: 255 if a == 0 else 0)
        canvas.paste(img, (ox, oy), ImageChops.multiply(img.getchannel("A"), empty))
    canvas.save(out_png)
    return W, H, ok, miss


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--families", default="CITY,FARM,FIELD",
                    help="map-name families to include (comma list, e.g. CITY,FARM,FIELD or DUNG); "
                         "'all' = every family")
    ap.add_argument("--px", type=int, default=8, help="pixels per ATTR tile (native art is 24)")
    ap.add_argument("--min-comp", type=int, default=2, help="skip components smaller than this")
    ap.add_argument("--max-comps", type=int, default=12, help="render at most N components")
    ap.add_argument("--prune", type=float, default=20.0, help="drop warp constraints with residual > N tiles")
    ap.add_argument("--out", default=str(pathlib.Path(__file__).parent / "world_out"))
    a = ap.parse_args(argv)

    fams = None if a.families.lower() == "all" else {f.strip().upper() for f in a.families.split(",")}
    tag = "all" if fams is None else "-".join(sorted(fams)).lower()
    outdir = pathlib.Path(a.out); outdir.mkdir(parents=True, exist_ok=True)

    id2name = load_rooms()
    reader = make_reader()
    grids, cells, keep, cons = collect(BUNDLE / "bundleMain", id2name, fams)
    comps = [c for c in components(keep, cons) if len(c) >= a.min_comp]
    print("maps: %d in families %s   constraints: %d   components >=%d maps: %d"
          % (len(keep), tag, len(cons), a.min_comp, len(comps)))

    for i, comp in enumerate(comps[:a.max_comps]):
        pos = solve(comp, cons, grids, prune_tiles=a.prune)
        png = outdir / ("world_%s_%02d.png" % (tag, i))
        print("component %d: %d maps -> %s" % (i, len(pos), png.name))
        W, H, ok, miss = render(pos, grids, cells, reader, a.px, png)
        xs0 = min(p[0] for p in pos.values()); ys0 = min(p[1] for p in pos.values())
        js = {n: {"x": round(pos[n][0] - xs0, 2), "y": round(pos[n][1] - ys0, 2),
                  "w": grids[n][0], "h": grids[n][1]} for n in pos}
        (outdir / (png.stem + ".json")).write_text(json.dumps(js, indent=1))
        print("  -> %dx%d px, %d maps drawn, %d without texture" % (W, H, ok, miss))


if __name__ == "__main__":
    main()
