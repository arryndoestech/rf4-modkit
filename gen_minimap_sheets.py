#!/usr/bin/env python3
"""Render every minimap sheet with its rf3MapMiniPos placement data drawn on top.

Writes one PNG per static sheet (sheet_NNN_<texture>.png, all 88) plus a README.md index into
  docs/minimap_sheets/        --labels ids    technical view: boxes labelled with the map id
  docs/minimap_sheets_named/  --labels names  boxes labelled with the in-game name from
                                              docs/map_names.json; maps sharing a name are
                                              numbered <name>_01..N in map-id order, and
                                              labels.csv / labels.json map every label back
                                              to its map id, file and sheet
  --clean                                     vanilla picture + room labels only: no boxes, dots,
                                              legend strip or interior markers; each label is
                                              centred on its room (reveal rect, else map extent)
Needs your bundle (mini_map_*.texture + MAP_*.rf4m under Bundle/) and Pillow + texture2ddecoder.

Legend of the technical view -- table coordinates are half-texture pixels; the 512-px texture
is drawn at <zoom>x, so table values are multiplied by 2 * zoom:
  green box + label   reveal rect (dwords 3..6): fog-of-war region uncovered once the map is visited
  red dot             origin (dwords 1..2): where the map's tile (0, 0) lands on the sheet
  orange box          map extent: origin + scale (dwords 7..8) x the map's ATTR size in sub-units
  blue circle + label NPC-icon spot (dwords 11..12) of interiors whose parent sheet (dword 10) is
                      this sheet; stacked labels for rooms sharing one spot
Variant sheets (farm / room / barn levels, story and flag swaps) have no rows of their own: they
are drawn with their base sheet's rows and labelled with the swap condition.

Run:  python gen_minimap_sheets.py                                  # ids, boxed, 1024 px
      python gen_minimap_sheets.py --labels names --clean --zoom 4  # names only, 2048 px
      options: [--labels ids|names] [--names docs/map_names.json] [--out DIR] [--zoom N] [--clean]
"""
import argparse
import csv
import json
import pathlib
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rf4s_modkit import map_names, minimap, rf4m, texture  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent.parent      # tools/modding/../..
DOCS = REPO / "docs"
BUNDLE_DIR = REPO / "Bundle"
EXTRACTED = (BUNDLE_DIR / "extracted") if (BUNDLE_DIR / "extracted").is_dir() else BUNDLE_DIR

GREEN, RED, ORANGE, BLUE = (40, 230, 40, 255), (255, 40, 40, 255), (255, 150, 0, 255), (40, 160, 255, 255)
YELLOW, WHITE, BLACK = (255, 240, 0, 255), (255, 255, 255, 255), (0, 0, 0, 255)
LEGEND_H = 78
PLACEHOLDER_PREFIXES = ("BLANK", "Room: Dummy", "Forest: Dummy", "Temple: Dummy", "Ruin: Dummy")


def id_ranges(ids):
    out, s, p = [], None, None
    for i in ids:
        if s is None:
            s = p = i
        elif i == p + 1:
            p = i
        else:
            out.append((s, p)); s = p = i
    if s is not None:
        out.append((s, p))
    return ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in out)


def base_sheet_of(sheet):
    """(base sheet, condition) for a variant sheet, else (None, None)."""
    for base, rules in minimap.VARIANT_RULES.items():
        for sh, cond in rules:
            if sh == sheet and sh != base:
                return base, cond
    return None, None


def load_fonts(label_px):
    from PIL import ImageFont
    try:
        return ImageFont.truetype("arial.ttf", label_px), ImageFont.truetype("arialbd.ttf", 16)
    except OSError:
        f = ImageFont.load_default()
        return f, f


def outlined_text(draw, xy, text, fill, font, width=1):
    x, y = xy
    for dx in range(-width, width + 1):
        for dy in range(-width, width + 1):
            if dx or dy:
                draw.text((x + dx, y + dy), text, fill=BLACK, font=font)
    draw.text((x, y), text, fill=fill, font=font)


def wrap_to_width(draw, text, font, max_w, max_lines=3):
    """Greedy word wrap; a single word wider than the box is left to overflow."""
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if cur and draw.textlength(cand, font=font) > max_w:
            lines.append(cur); cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    return lines


def centered_text(draw, box, text, fill, font, line_h, outline):
    """Word-wrapped label centred in box = (x0, y0, x1, y1) output pixels."""
    x0, y0, x1, y1 = box
    lines = wrap_to_width(draw, text, font, max(1, x1 - x0 - 4), max_lines=6)
    block_h = line_h * len(lines)
    y = (y0 + y1) / 2 - block_h / 2
    for line in lines:
        tw = draw.textlength(line, font=font)
        outlined_text(draw, ((x0 + x1) / 2 - tw / 2, y), line, fill, font, outline)
        y += line_h


MIN_ART_COVERAGE = 0.10   # clean style: label a room only if >= 10% of its box has picture art


def art_coverage(alpha, box_units):
    """Fraction of opaque texture pixels under a box given in table units (x0, y0, x1, y1).
    Variant pictures (room / farm levels) only draw the rooms that exist at that level, so
    a row's label belongs on a picture only where the picture has art for it."""
    x0, y0, x1, y1 = [max(0, min(alpha.width, int(v * 2))) for v in box_units]
    if x1 <= x0 or y1 <= y0:
        return 0.0
    hist = alpha.crop((x0, y0, x1, y1)).histogram()
    return sum(hist[33:]) / float((x1 - x0) * (y1 - y0))


def has_placement(mid):
    """A row places something on its sheet only if it has an origin or a sized reveal box;
    dummy rooms with just a scale or a reveal corner would only plot at the sheet's corner."""
    r = minimap.raw_record(mid)
    return bool(r) and bool((r[1] or r[2]) or (r[5] and r[6]))


def is_placeholder(name):
    return not name or name.startswith(PLACEHOLDER_PREFIXES)


def load_names(path):
    """map id -> in-game name from docs/map_names.json (falls back to the vendored table)."""
    try:
        table = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        return {int(k): (v["name"] if isinstance(v, dict) else v) for k, v in table.items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {i: map_names.map_name(i) for i in range(map_names.map_count())}


def build_labels(mode, names):
    """map id -> label. In 'names' mode, maps that share a name (among the maps that appear
    on the sheets, i.e. have placement data) become <name>_01..N in map-id order."""
    if mode == "ids":
        return {i: str(i) for i in range(minimap.map_count())}
    drawn = [i for i in range(minimap.map_count()) if has_placement(i)]
    counts = Counter(names.get(i, "") for i in drawn)
    seen, labels = defaultdict(int), {}
    for i in drawn:
        n = names.get(i, "") or f"map {i}"
        if counts[n] > 1:
            seen[n] += 1
            labels[i] = f"{n}_{seen[n]:02d}"
        else:
            labels[i] = n
    return labels


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--labels", choices=("ids", "names"), default="ids",
                    help="label boxes with map ids (default) or with in-game names")
    ap.add_argument("--names", help=f"map-names registry for --labels names (default: {DOCS / 'map_names.json'})")
    ap.add_argument("--out", help="output folder (default: docs/minimap_sheets or docs/minimap_sheets_named)")
    ap.add_argument("--zoom", type=int, default=2, help="texture zoom factor (default 2 -> 1024 px)")
    ap.add_argument("--clean", action="store_true",
                    help="vanilla picture + centred room labels only (no boxes, dots, legend, interior markers)")
    a = ap.parse_args(argv)
    out_dir = pathlib.Path(a.out) if a.out else DOCS / ("minimap_sheets_named" if a.labels == "names" else "minimap_sheets")
    zoom = max(1, a.zoom)
    k = 2 * zoom                       # table units -> output pixels
    legend_h = 0 if a.clean else LEGEND_H
    label_px = max(12, 5 * zoom)       # 12 px at 2x, 20 px at 4x
    line_h = label_px + 1
    outline = 1 if zoom <= 2 else 2

    from PIL import Image, ImageDraw
    if not minimap.table_available():
        print("rf4s_modkit/map_minimap.json missing -- run gen_map_names_json.py first", file=sys.stderr)
        return 1
    textures = {p.stem: p for p in EXTRACTED.rglob("mini_map_*.texture")}
    maps = {p.stem.upper(): p for p in EXTRACTED.rglob("MAP_*.rf4m")}
    if not textures:
        print(f"no mini_map_*.texture under {EXTRACTED}", file=sys.stderr)
        return 1
    names = load_names(a.names or DOCS / "map_names.json")
    labels = build_labels(a.labels, names)
    font, font_b = load_fonts(label_px)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ATTR grid size per map id (for the scale extent box)
    attr = {}
    for mid in range(minimap.map_count()):
        f = map_names.map_file(mid)
        p = maps.get((f or "").upper())
        if p is None:
            continue
        try:
            g = rf4m.Rf4mMap.load(p).attr_grid()
            if g:
                attr[mid] = (g[0], g[1])
        except Exception:
            pass

    def extent_box(mid):
        """(x0, y0, x1, y1) in table units: origin + scale x ATTR size, or None."""
        raw = minimap.raw_record(mid)
        if mid not in attr or not raw[7] or not raw[8]:
            return None
        aw, ah = attr[mid]
        return (raw[1], raw[2], raw[1] + ((raw[7] * (aw * 8)) >> 12), raw[2] + ((raw[8] * (ah * 8)) >> 12))

    by_sheet = minimap.sheets_in_use()
    index_rows = []
    for sheet in range(minimap.LAST_STATIC_SHEET + 1):
        name = minimap.texture_for_sheet(sheet)
        tex_path = textures.get(name)
        if tex_path is None:
            print(f"  missing texture {name}, skipped")
            continue
        base, cond = base_sheet_of(sheet)
        data_sheet = base if base is not None else sheet
        all_rows = by_sheet.get(data_sheet, [])
        # rows without placement data (seasonal duplicates, dummy rooms: origin/reveal/scale all 0)
        # would only plot a stray dot at (0, 0) -- keep them in the index, don't draw them
        unplaced = [m for m in all_rows if not has_placement(m)]
        rows = [m for m in all_rows if m not in unplaced]
        interiors = [m for m in range(minimap.map_count())
                     if has_placement(m) and minimap.record(m)["parent_sheet"] == data_sheet
                     and minimap.record(m)["icon"] != (0, 0)]

        img = texture.decode_to_image(tex_path.read_bytes()).convert("RGBA")
        alpha = img.getchannel("A")
        w, h = img.size
        img = img.resize((w * zoom, h * zoom), Image.LANCZOS)
        canvas = Image.new("RGBA", (w * zoom, h * zoom + legend_h), (24, 24, 24, 255) if legend_h else (0, 0, 0, 0))
        canvas.paste(img, (0, 0))
        d = ImageDraw.Draw(canvas)

        skipped = 0
        if a.clean:
            # vanilla picture + a label centred on each room; nothing on the blank picture
            if data_sheet != minimap.DUMMY_SHEET:
                groups = defaultdict(list)          # identical boxes (barn rooms) share one label
                for mid in rows:
                    if is_placeholder(names.get(mid, map_names.map_name(mid))):
                        continue
                    r = minimap.record(mid)
                    if r["reveal"]:
                        x, y, rw, rh = r["reveal"]
                        box = (x, y, x + rw, y + rh)
                    else:
                        box = extent_box(mid)
                        if box is None:
                            ox, oy = r["origin"]
                            box = (ox, oy, ox + 40, oy + 10)
                    if art_coverage(alpha, box) < MIN_ART_COVERAGE:
                        skipped += 1          # this level's picture does not draw that room
                        continue
                    groups[box].append(mid)
                for box, mids in groups.items():
                    texts = [labels.get(m, str(m)) for m in mids]
                    bases = {names.get(m, map_names.map_name(m)) for m in mids}
                    if len(mids) > 1 and len(bases) == 1:
                        base_name = bases.pop()
                        suffixes = [t[len(base_name):] or t for t in texts]
                        text = base_name + " " + " ".join(suffixes)
                    else:
                        text = " / ".join(texts)
                    centered_text(d, tuple(v * k for v in box), text, YELLOW, font, line_h, outline)
        else:
            for mid in rows:
                r = minimap.record(mid)
                ox, oy = r["origin"]
                ext = extent_box(mid)
                if ext:
                    d.rectangle([v * k for v in ext], outline=ORANGE, width=1)
                if r["reveal"]:
                    x, y, rw, rh = r["reveal"]
                    d.rectangle([x * k, y * k, (x + rw) * k, (y + rh) * k], outline=GREEN, width=2)
                    for li, line in enumerate(wrap_to_width(d, labels.get(mid, str(mid)), font, rw * k - 6)):
                        outlined_text(d, (x * k + 3, y * k + 2 + line_h * li), line, YELLOW, font, outline)
                d.ellipse([ox * k - 4, oy * k - 4, ox * k + 4, oy * k + 4], fill=RED)
                if not r["reveal"] and data_sheet != minimap.DUMMY_SHEET:
                    outlined_text(d, (ox * k + 6, oy * k - 7), labels.get(mid, str(mid)), RED, font, outline)
            spot_count = Counter()
            for mid in interiors:
                r = minimap.record(mid)
                ix, iy = r["icon"]
                n = spot_count[(ix, iy)]
                spot_count[(ix, iy)] += 1
                d.ellipse([ix * k - 6, iy * k - 6, ix * k + 6, iy * k + 6], outline=BLUE, width=2)
                outlined_text(d, (ix * k + 8, iy * k - 8 + line_h * n), labels.get(mid, str(mid)), BLUE, font, outline)

        shown = sorted({names.get(m, map_names.map_name(m)) for m in rows})
        if legend_h:
            y0 = h * zoom + 6
            if base is not None:
                kind = f"variant of sheet {base} ({minimap.texture_for_sheet(base)}): drawn when {cond}"
            elif not rows and sheet == 27:
                kind = "no map references this sheet"
            elif sheet == minimap.DUMMY_SHEET:
                kind = f"blank picture: {len(all_rows)} rows (placeholders, the '???' dungeon, maze target)"
            else:
                kind = f"{len(rows)} maps: {id_ranges(rows)}"
                if unplaced:
                    kind += f"   (+{len(unplaced)} rows without placement data, not drawn: {id_ranges(unplaced)})"
            d.text((8, y0), f"sheet {sheet}   {name}   resource {minimap.ARCHIVE_ID_BASE + sheet}", fill=WHITE, font=font_b)
            d.text((8, y0 + 22), kind[:150], fill=WHITE, font=font)
            d.text((8, y0 + 40), ("  |  ".join(shown)[:150]) if base is None else
                   "rows of sheet %d: %s" % (base, ("  |  ".join(shown))[:120]), fill=(200, 200, 200, 255), font=font)
            d.text((8, y0 + 58), "green: reveal rect [3..6]   red: origin [1..2]   orange: origin + scale x ATTR size [7..8]"
                                 "   blue: NPC-icon spot of interiors routed here [9..12]", fill=(160, 160, 160, 255), font=font)

        out = out_dir / f"sheet_{sheet:03d}_{name}.png"
        canvas.save(out, optimize=True)
        index_rows.append((sheet, name, base, cond, sorted(all_rows), shown, out.name))
        print(f"  wrote {out.name}  ({len(rows)} rows" + (f", {skipped} labels without art skipped)" if skipped else ")"))

    # index
    lines = ["# Minimap sheets (%s%s)" % ("named" if a.labels == "names" else "annotated",
                                          ", clean" if a.clean else ""), "",
             "One picture per static minimap sheet (`mini_map_*.texture`, resource id 12199 + sheet)%s," %
             ("" if a.clean else ", with the `rf3MapMiniPos.bin` placement rows drawn on top"),
             "generated by `tools/modding/gen_minimap_sheets.py`. The 512-px texture is shown at %dx." % zoom, ""]
    if a.labels == "names":
        lines += ["Rooms are labelled with the in-game name from `docs/map_names.json`. Maps that share a name are",
                  "numbered `<name>_01..N` in map-id order (counted over the maps that appear on the sheets); see",
                  "`labels.csv` / `labels.json` for label -> map id, MAP_* file and sheet.", ""]
    if a.clean:
        lines += ["Clean style: the vanilla picture with each label centred on its room (its fog-of-war rectangle,",
                  "else its map extent). Placeholder rows, the blank picture and the interior/entrance markers are",
                  "left out.", ""]
    else:
        lines += ["Legend: **green** reveal rect (dwords 3..6, fog of war) · **red** origin (dwords 1..2) · **orange** map",
                  "extent = origin + scale (dwords 7..8) x ATTR size · **blue** NPC-icon spot (dwords 11..12) of interiors",
                  "whose parent sheet (dword 10) is this one.", ""]
    lines += ["Variant sheets show their base sheet's rows. The 16 `mini_map_rnd_*` maze tiles (sheets 88..103) are",
              "not per-map and are not rendered.", "",
              "| Sheet | Texture | Resource | Kind | Maps |", "|---:|---|---:|---|---|"]
    for sheet, name, base, cond, all_rows, shown, fname in index_rows:
        if base is not None:
            kind = f"variant of {base}: {cond}"
        elif sheet == minimap.DUMMY_SHEET:
            kind = "blank picture"
        elif not all_rows:
            kind = "unreferenced"
        else:
            kind = "base"
        maps_txt = (f"{id_ranges(all_rows)}: " + ", ".join(shown)) if all_rows else ""
        if len(maps_txt) > 140:
            maps_txt = maps_txt[:137] + "..."
        lines.append(f"| {sheet} | [{name}]({fname}) | {minimap.ARCHIVE_ID_BASE + sheet} | {kind} | {maps_txt} |")
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if a.labels == "names":
        rows_out = []
        for mid in sorted(labels):
            sh = minimap.sheet(mid)
            rows_out.append({"label": labels[mid], "map_id": mid, "name": names.get(mid, ""),
                             "file": map_names.map_file(mid), "sheet": sh,
                             "texture": minimap.texture(mid)})
        with (out_dir / "labels.csv").open("w", newline="", encoding="utf-8") as f:
            wcsv = csv.DictWriter(f, fieldnames=["label", "map_id", "name", "file", "sheet", "texture"])
            wcsv.writeheader(); wcsv.writerows(rows_out)
        (out_dir / "labels.json").write_text(
            json.dumps({r["label"]: {kk: v for kk, v in r.items() if kk != "label"} for r in rows_out},
                       indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        dup = sum(1 for r in rows_out if r["label"] != r["name"])
        print(f"labels: {len(rows_out)} maps, {dup} carry a _NN suffix")
    total = sum(p.stat().st_size for p in out_dir.glob("*.png"))
    print(f"wrote {len(index_rows)} sheets + README.md to {out_dir} ({total / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
