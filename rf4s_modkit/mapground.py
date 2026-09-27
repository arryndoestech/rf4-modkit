"""Stitch a map's pre-rendered ground texture atlas into one top-down image.

A map's ground texture is a tile atlas of ``.texture`` (BC7 BNTX) files named
``<SET>_<LNN>.texture``.  **CRUCIAL:** ``<SET>`` is the map's ground-texture set,
which is **usually NOT the same-named set** — it comes from the game's
``g_mapResourceTable[4*mapId + 1]`` (only 121/872 maps are name-matched; e.g.
``MAP_FIELD_13``'s ground is ``MAP_FIELD_10``, ``MAP_FIELD_03``'s is ``MAP_FIELD_203``).
:func:`texture_set_for` / :func:`resolve_base` consult the dumped mapping
(``map_texture_sets.json``) to pick the right set; loading by map name was wrong for
~750 maps.  ``L`` = **draw layer** (the thousands digit) and ``NN`` = tile index
``0..N-1`` (contiguous):

* layer ``0`` (``00xx``) = the **ground/floor** — a fully opaque top-down render.
* layer ``1`` (``10xx``) = an **overlay drawn on top** of the ground (tree canopy
  / foliage / tall objects that occlude the player) — mostly transparent, with
  content only where things overhang.  There is no layer 2: the game builds at most
  two display layers (Map_SpawnEntity, RF4S.exe+0x194140, loads the first MTXN chunk's
  layer from ``g_mapResourceTable[4*mapId + 1]`` and every later chunk's from ``[+2]``),
  and no shipped tile has a layer digit above 1.

The overlay is its OWN archive id (``[+2]``, 0 = no overlay), shipped per map in
``refdata/rf4s_exe_map_resources.json`` (:mod:`rf4s_modkit.mapres`). It is often not the
ground set's ``_1000`` tiles: ``MAP_FIELD_01``'s ground is ``MAP_FIELD_201`` but its overlay
is ``MAP_FIELD_01_1000``, ``MAP_FIELD_03``..``05`` draw ``MAP_FIELD_07_1000`` (121 maps
differ), and ``MAP_DUNG_I04`` / ``I08`` draw no overlay although their ground sets ship one.
:func:`overlay_for` resolves it; only a map name the game's table does not list falls back
to the ground set's ``_1000`` tiles.

The in-game look is layers alpha-composited bottom-up (:func:`stitch_composite`).
NOTE: the layer digit is **not** a season — seasons are separate ``.rf4m`` files
(``MAP_*_SUMMER/_AUTUMN/_WINTER``) which carry no atlas of their own and reuse the
base map's textures (see :func:`resolve_base`).

Tiles are placed in **screen-space row-major**: tile ``i`` goes to ``(col = i % C,
row = i // C)`` where ``C`` is the column count of the screen grid.  Tile 0 = top-left,
tile ``C-1`` = top-right, tile ``N-1`` = bottom-right.  Verified against the game
(user-confirmed for FIELD_01).

The stitched atlas is reconciled with the **real map extent** (``ATTR_W·24 × ATTR_H·24``
px, 24 px/ATTR tile) in one of two ways when ``aspect`` is supplied, depending on how
far the atlas overshoots it:

* **Sub-tile overshoot** (< 512 px on *both* axes) → the surplus is padding from
  rounding the tile grid up, so :func:`stitch` **crops** to the real extent
  (MAP_CITY_06 78×75: 2048×2048 → 1872×1800).
* **Whole-tile-or-more overshoot** on an axis → the atlas legitimately covers *more*
  than ``ATTR·24``; the engine renders the whole atlas scaled (possibly non-uniformly)
  to the map's world bounds, so :func:`stitch` **keeps it whole** and the caller
  resizes it to the ATTR grid — which lines the extents up exactly (MAP_FIELD_03 51×42:
  atlas 2176×1152, the ATTR walkable mask lands on the textured paths only when scaled,
  never when cropped). Same for MAP_FIELD_04 (2048×2048).

**Important about tile dimensions.** :func:`rf4s_modkit.texture.decode_to_image`
applies ``ROTATE_90`` after decoding to put the tile in its in-game orientation, so a
parsed-512×64 tile returns as a 64×512 PIL image.  This module uses the
**post-rotation** image sizes for layout — those give consistent row heights and
column widths in a single row-major grid (using the parser's pre-rotation dims would
not).  ``C`` is recovered from the narrow-width tiles: they sit at the end of each row
(indices ``C-1, 2C-1, …``), so ``C = first_narrow_width_index + 1``; if no narrow-W,
fall back to ``C = count(narrow-height tiles)`` (the bottom row); if neither, use the
ATTR aspect hint.

Verified by reconstruction against MAP_FIELD_01 (4 cols × 4 rows), MAP_FIELD_03
(5 cols × 3 rows) and MAP_DUNG_A04 (5 cols × 4 rows), with the ATTR walkable mask
overlaid to confirm alignment.  Not every map ships an atlas: some dungeons (e.g. A09/A10)
have none and town atlases are mostly sky.  :func:`stitch`/:func:`stitch_composite`
return ``None`` when no atlas can be resolved.

Format is BC7, so decoding needs ``texture2ddecoder`` + ``Pillow`` (same optional
deps as :mod:`rf4s_modkit.texture`).
"""
from __future__ import annotations

import json
import os
import re
import threading
from collections import OrderedDict

from . import texture as _tex

LAYERS = (0, 1)          # ground, overlay: the only display layers the game builds
FULL_TILE = 512
PX_PER_ATTR_TILE = 24    # Map_SpawnEntity: NROWS = ceil(24 * ATTR_W / 512) → 24 px / ATTR tile
# Hard ceiling on cols*rows. Map_SpawnEntity keeps ONE widget pointer per atlas tile
# in its 888-byte map_disp work buffer, packed from +8 upward (Map_DestroyEntity,
# RF4S.exe+0x1948B0, frees exactly work[808]*work[812] of them starting at +8). The
# next field is the decoration-model pointer at +776, so the array holds
# (776 - 8) / 8 = 96 tiles; tile 96 overwrites that pointer, 97 the task pointer at
# +784 and 98 the archive id at +792. Nothing bounds-checks the loop. The biggest
# shipped map needs 30 tiles (MAP_ROOM_25/26, 128x96), so only a grown map can hit it.
# Verified 2026-09-23 against Map_SpawnEntity (RF4S.exe+0x194140) + Map_DestroyEntity.
MAX_TILE_SLOTS = 96
_SEASON_SUFFIX = re.compile(r"_(SPRING|SUMMER|AUTUMN|FALL|WINTER)$", re.I)

# --- Decoded-tile LRU cache --------------------------------------------------
# BC7 tile decode is slow (~16 ms/tile) and GIL-bound, so cache decoded tiles by
# filename. Maps that SHARE a texture set reuse them: seasonal variants (resolve to
# the same base set), the H-dungeon family (shares the MAP_DUNG_H02 stage tiles),
# remapped field groups, and any map re-stitched after the ground LRU evicted it.
# Thread-safe: the dict is locked, but read+decode run OUTSIDE the lock (mbundle.read
# opens a fresh handle per call, so concurrent reads are safe). Cached images are
# treated as read-only (stitch only pastes them).
_TILE_CACHE = OrderedDict()
_TILE_CACHE_MAX = 128          # ~100 MB worst case (512² RGBA tiles; edge tiles smaller)
_TILE_LOCK = threading.Lock()


def _decode_tile_cached(reader, fname):
    """Decode one tile by filename via the shared LRU. Returns an RGBA PIL.Image, or
    None if the file doesn't exist (used as the stitch loop's stop condition)."""
    with _TILE_LOCK:
        im = _TILE_CACHE.get(fname)
        if im is not None:
            _TILE_CACHE.move_to_end(fname)
            return im
    b = reader(fname)
    if b is None:
        return None
    im = _tex.decode_to_image(b)
    if im.mode != "RGBA":
        im = im.convert("RGBA")

    with _TILE_LOCK:
        _TILE_CACHE[fname] = im
        _TILE_CACHE.move_to_end(fname)
        while len(_TILE_CACHE) > _TILE_CACHE_MAX:
            _TILE_CACHE.popitem(last=False)
    return im


def _decode_many(blobs):
    """Decode tile byte strings to RGBA images (in order)."""
    out = []
    for b in blobs:
        im = _tex.decode_to_image(b)
        out.append(im if im.mode == "RGBA" else im.convert("RGBA"))
    return out


def _decode_tiles(reader, names):
    """Decoded RGBA images for `names` (a layer's consecutive tiles), via the shared LRU;
    cache misses are read first, then decoded."""
    out = [None] * len(names)
    miss_i, miss_b = [], []
    for i, fn in enumerate(names):
        with _TILE_LOCK:
            im = _TILE_CACHE.get(fn)
            if im is not None:
                _TILE_CACHE.move_to_end(fn)
        if im is not None:
            out[i] = im
            continue
        b = reader(fn)
        if b is None:
            continue
        miss_i.append(i); miss_b.append(b)
    for i, im in zip(miss_i, _decode_many(miss_b)):
        out[i] = im
        with _TILE_LOCK:
            _TILE_CACHE[names[i]] = im
            _TILE_CACHE.move_to_end(names[i])
            while len(_TILE_CACHE) > _TILE_CACHE_MAX:
                _TILE_CACHE.popitem(last=False)
    return out


def tile_cache_clear():
    """Drop all cached decoded tiles (e.g. after repacking textures)."""
    with _TILE_LOCK:
        _TILE_CACHE.clear()


def tile_cache_size():
    with _TILE_LOCK:
        return len(_TILE_CACHE)

# Authoritative map -> ground-texture-set mapping, dumped from g_mapResourceTable
# (RF4S.exe+0x9F9D10): the ground texture for a map is g_mapResourceTable[4*mapId + 1],
# NOT the same-named .texture set. Only 121/872 maps happen to be name-matched; the
# rest point at a *different* texture set (e.g. MAP_FIELD_13 -> MAP_FIELD_10,
# MAP_FIELD_03 -> MAP_FIELD_203, MAP_DUNG_E01 -> MAP_DUNG_E02_UV). Loading by name
# was wrong for ~750 maps. Value = [texture_set_name, is_static_single_sprite].
_TEXMAP = None


def _texmap():
    global _TEXMAP
    if _TEXMAP is None:
        try:
            p = os.path.join(os.path.dirname(__file__), "map_texture_sets.json")
            with open(p, encoding="utf-8") as f:
                _TEXMAP = json.load(f)
        except Exception:
            _TEXMAP = {}
    return _TEXMAP


def texture_set_for(map_name: str):
    """Return (texture_set_name, is_static) for a map, or None if unknown.
    `is_static` marks a single full-screen sprite ("_UV" maps) rather than a tile grid."""
    ent = _texmap().get(map_name)
    if ent is None and _SEASON_SUFFIX.search(map_name):
        ent = _texmap().get(_SEASON_SUFFIX.sub("", map_name))
    return (ent[0], bool(ent[1])) if ent else None


_OVERMODELS = None


def _overmodels():
    global _OVERMODELS
    if _OVERMODELS is None:
        try:
            p = os.path.join(os.path.dirname(__file__), "map_overmodels.json")
            with open(p, encoding="utf-8") as f:
                _OVERMODELS = json.load(f)
        except Exception:
            _OVERMODELS = {}
    return _OVERMODELS


def overmodel_for(map_name: str):
    """Return the over-model texture-set name for a map — the ``MAP_*.model``
    billboard from ``g_mapResourceTable[4*mapId + 3]`` (a pre-rendered 3D scenery
    card: stairs/fences/structures, drawn over the 2D ground) — or ``None`` if the
    map has no over-model. The file is ``<set>.model``: flat textured cards placed by
    their bones in map sub-units, so they DO line up with the ATTR grid -- see
    :func:`rf4s_modkit.model.overmodel_cards` / ``render_overmodel``. Heavily SHARED
    by backdrop (e.g. ``MAP_FIELD_43``'s is reused by 164 maps; many are an
    empty/transparent placeholder = no decoration).

    **Placement (Map_SpawnEntity, RF4S.exe+0x194140, read 2026-09-21).** The map
    carries NO position for it: the archive id is loaded, built with
    ``GfxCTR_Model_BuildFromResource`` and drawn as one whole model under a FIXED
    rotation of 270 degrees (``Math_DegToRad(270.0)`` about one axis, 0 about the
    other two) -- *not* a random rotation, as an earlier revision of this note said.
    The only spatial data read out of the file is a per-mesh material parameter named
    ``"po"``, whose float becomes that mesh's depth as ``po * 1.5 - 0.3``; the minimum
    over all meshes is stored as the model's own depth. So where the scenery sits is
    baked into the model's geometry (each card's bone translation, in map sub-units),
    and cannot be moved by editing map data."""
    om = _overmodels()
    if map_name in om:
        return om[map_name]
    if _SEASON_SUFFIX.search(map_name):
        return om.get(_SEASON_SUFFIX.sub("", map_name))
    return None


def tile_name(map_name: str, layer: int, idx: int) -> str:
    """Filename of one atlas tile, e.g. ``MAP_FIELD_01_1003.texture``."""
    return "%s_%04d.texture" % (map_name, layer * 1000 + idx)


def single_name(set_name: str) -> str:
    """Filename of a single-sprite ("_UV") texture set, e.g. ``MAP_DUNG_E02_UV.texture``.

    Static maps (the procedural E/H dungeons, ROOM_25/26, …) render ONE full-screen
    background quad instead of a tile grid, so their set has no ``_NNNN`` suffix."""
    return "%s.texture" % set_name


def _set_present(reader, set_name: str) -> bool:
    """Does this texture set exist in the bundle — tiled (``_0000``) or single sprite?"""
    return reader(tile_name(set_name, 0, 0)) is not None or reader(single_name(set_name)) is not None


def resolve_base(reader, map_name: str) -> str:
    """Texture-set name whose atlas to stitch for ``map_name``.

    Uses the authoritative g_mapResourceTable mapping (`texture_set_for`) first — the
    ground texture is frequently a DIFFERENT set than the same-named one. Falls back to
    the old name-match / season-strip heuristic only when the mapping is missing or its
    resolved set isn't present in this bundle."""
    ent = texture_set_for(map_name)
    if ent and _set_present(reader, ent[0]):
        return ent[0]
    # Fallbacks: same-named set, then season-stripped name's mapping / same-named set.
    if _set_present(reader, map_name):
        return map_name
    stripped = _SEASON_SUFFIX.sub("", map_name)
    if stripped != map_name:
        ent2 = texture_set_for(stripped)
        if ent2 and _set_present(reader, ent2[0]):
            return ent2[0]
        if _set_present(reader, stripped):
            return stripped
    return ent[0] if ent else map_name


def _sets_for(reader, map_name: str):
    """``(ground_set, uv_set_or_None)`` for a map's layer 0.

    **Static "_UV" maps** (Floating Empire E*, Delirium Lava Ruins H*, …): the game remaps
    the ``+1`` ground id to a full-screen ``<set>_UV`` skybox, so layer 0 is that one sprite;
    the *aligned* tiled STAGE (the platform you walk on) is the overlay layer, the ``+2`` id
    (e.g. E01 → ``MAP_DUNG_E02_1000``; see :func:`overlay_for`). (Verified: E01's ATTR lands
    exactly on ``MAP_DUNG_E02`` layer 1.) For normal maps there is no ``_UV``."""
    rb = resolve_base(reader, map_name)
    if rb.endswith("_UV"):
        return rb[:-3], rb
    return rb, None


def overlay_for(reader, map_name: str):
    """Texture set whose ``_1NNN`` tiles are the map's overlay (layer 1), or None when the
    game draws no overlay on it. From the game's table (:func:`rf4s_modkit.mapres.overlay_set`,
    g_mapResourceTable ``[+2]``); a map name the table does not list (a renamed copy) falls
    back to the ground set's own ``_1000`` tiles."""
    from . import mapres
    known, ovl = mapres.overlay_set(map_name)
    if known:
        return ovl
    base, _uv = _sets_for(reader, map_name)
    return base if reader(tile_name(base, 1, 0)) is not None else None


def layer_set(reader, map_name: str, layer: int):
    """The texture set a layer's tiles come from: layer 0 = the ground set, layer 1 =
    :func:`overlay_for`; None for a layer the game never builds."""
    if layer == 0:
        return _sets_for(reader, map_name)[0]
    return overlay_for(reader, map_name) if layer == 1 else None


def available_layers(reader, map_name: str) -> list[int]:
    """Draw layers that exist for ``map_name`` (probes tile 0 of each): 0 = ground (for a
    static map the ``_UV`` skybox), 1 = the overlay the game draws (see :func:`overlay_for`)."""
    base, uv = _sets_for(reader, map_name)
    ovl = overlay_for(reader, map_name)
    top = [1] if ovl is not None and reader(tile_name(ovl, 1, 0)) is not None else []
    if uv is not None:
        if reader(single_name(uv)) is not None or reader(single_name(base)) is not None:
            return [0] + top
        return top
    return ([0] if reader(tile_name(base, 0, 0)) else []) + top


def _infer_cols(sizes, aspect=None):
    """Recover the screen column count C from the post-rotation tile sizes.

    FALLBACK heuristic — :func:`stitch` prefers the game-exact :func:`grid_dims`
    (``ceil(24*ATTR_W/512)``) when the ATTR aspect is known; this is used only when
    aspect is absent or the tile count doesn't fit that formula.

    ``sizes`` = list of (W, H) per tile in order.  Returns C such that tile ``i``
    is at screen (col=i%C, row=i//C).  Strategy:
      1. Narrow-width tiles end each row (last column) → C = first_narrow_W + 1.
      2. No narrow-W: narrow-height tiles fill the bottom row → C = #narrow-H.
      3. Neither: use the ATTR aspect hint to pick a near-square factorisation.
    """
    n = len(sizes)
    if n == 0:
        return 1
    maxw = max(w for w, _ in sizes)
    maxh = max(h for _, h in sizes)
    narrow_w = [i for i, (w, _) in enumerate(sizes) if w < maxw]
    narrow_h = [i for i, (_, h) in enumerate(sizes) if h < maxh]
    if narrow_w:
        return narrow_w[0] + 1
    if narrow_h:
        return len(narrow_h)
    target = (aspect[0] / aspect[1]) if aspect and aspect[1] else 1.0
    best = None
    for c in range(1, n + 1):
        if n % c:
            continue
        r = n // c
        score = abs(c / r - target)
        if best is None or score < best[0]:
            best = (score, c)
    return best[1]


def grid_dims(attr_w: int, attr_h: int):
    """Game-EXACT tile-grid size for a map, matching RF4S.exe's ``Map_SpawnEntity``:
    ``cols = ceil(24*ATTR_W/512)``, ``rows = ceil(24*ATTR_H/512)`` (24 px/ATTR tile,
    512 px/atlas tile). The engine places tiles row-major (tile ``i`` at ``col=i%cols``).
    Verified equal to the size-based :func:`_infer_cols` heuristic across every rendered
    layer in the corpus, so :func:`stitch` prefers this exact form when the ATTR aspect
    is known."""
    c = (PX_PER_ATTR_TILE * attr_w + FULL_TILE - 1) // FULL_TILE
    r = (PX_PER_ATTR_TILE * attr_h + FULL_TILE - 1) // FULL_TILE
    return max(1, c), max(1, r)


def tile_files(reader, set_name: str, layer: int) -> list[str]:
    """Tile filenames a set actually ships for one layer, in index order.

    Stops at the first missing index, which is exactly what the shipped data looks
    like: the tiles of a layer occupy CONSECUTIVE archive ids (verified in the id
    table -- ``MAP_FIELD_01_0000``..``_0015`` are ids 8813..8828 and ``_1000``
    follows at 8829), so a hole in the numbering cannot happen in a real set.
    """
    out = []
    idx = 0
    while reader(tile_name(set_name, layer, idx)) is not None:
        out.append(tile_name(set_name, layer, idx))
        idx += 1
    return out


def atlas_audit(reader, map_name: str, attr_w: int, attr_h: int, layers=None) -> list[dict]:
    """Check a map's shipped ground atlas against what the engine will ASK FOR at an
    ATTR grid of ``attr_w x attr_h``. This is the check that makes a resized map safe.

    The tile count is derived from the ATTR grid ALONE -- ``Map_SpawnEntity``
    (``RF4S.exe+0x194140``) computes ``cols x rows`` with :func:`grid_dims` and then
    loops ``i`` over ``cols*rows``, calling ``WidgetSlot_AllocLoadArchiveAndConfigure``,
    which loads ``nsFileArchive_Load(i + base)``. So the atlas is *not* "however many
    tiles happen to exist": asking for more than the set ships walks straight off the
    end of it into the NEXT archive ids, which are the overlay layer's tiles and then
    the next map's set (``MAP_FIELD_01_0015`` = id 8828 is followed by
    ``MAP_FIELD_01_1000`` = 8829). Nothing bounds-checks that.

    Tiles are placed on a FIXED 512-px pitch (the engine positions tile ``i`` at world
    ``(col << 9, -(row << 9))``), so a tile narrower than 512 in a column that is no
    longer the last one leaves a hole, and a last-column tile that does not reach
    ``attr_w * 24`` leaves the map's right edge untextured. Both are checked here,
    because a grid that grows within the same tile count still breaks that way.

    Returns one dict per layer that has tiles::

        {"layer": int, "set": str, "kind": "grid" | "single",
         "cols": int, "rows": int, "need": cols*rows, "have": int,
         "missing": [tile index, ...],   # asked for, not shipped -> wrong archive id
         "extra":   [tile index, ...],   # shipped, never spawned
         "gap_x": [tile index, ...],    # < 512 px wide but no longer in the last column
         "gap_y": [tile index, ...],    # < 512 px tall but no longer in the last row
         "short_x": int, "short_y": int} # px of map extent with no tile, right/bottom

    ``kind == "single"`` is a static ``_UV`` map: the engine forces a 1x1 grid for that
    layer, so it needs exactly one sprite and the geometry checks do not apply.

    Layer 1 is audited against the overlay set the game really loads (:func:`overlay_for`).
    Over the shipped corpus **no map is missing a tile**, so a `missing` entry always means
    the map was edited. Exactly three overlay atlases ship MORE tiles than the formula
    spawns -- ``MAP_DUNG_A01`` (12/9), ``MAP_DUNG_B01`` (25/20) and ``MAP_DUNG_D06`` (21/9)
    (MAP_DUNG_I04 shares A01's ground set but the game draws no overlay on it). Overlay
    layers are mostly transparent, so a gap in one is usually harmless.
    """
    base, uv = _sets_for(reader, map_name)
    cols, rows = grid_dims(attr_w, attr_h)
    ext_x, ext_y = attr_w * PX_PER_ATTR_TILE, attr_h * PX_PER_ATTR_TILE
    probe = available_layers(reader, map_name) if layers is None else list(layers)
    out = []
    for ly in probe:
        if uv is not None and ly == 0:
            set_name = uv if reader(single_name(uv)) is not None else base
            have = 1 if reader(single_name(set_name)) is not None else 0
            out.append({"layer": ly, "set": set_name, "kind": "single",
                        "cols": 1, "rows": 1, "need": 1, "have": have,
                        "missing": [] if have else [0], "extra": [],
                        "gap_x": [], "gap_y": [], "short_x": 0, "short_y": 0})
            continue
        st = layer_set(reader, map_name, ly)
        if st is None:
            continue
        names = tile_files(reader, st, ly)
        if not names:
            if ly == 0 and reader(single_name(base)) is not None:
                out.append({"layer": ly, "set": base, "kind": "single",
                            "cols": 1, "rows": 1, "need": 1, "have": 1,
                            "missing": [], "extra": [], "gap_x": [], "gap_y": [],
                            "short_x": 0, "short_y": 0})
            continue
        have, need = len(names), cols * rows
        # Post-ROTATE_90 sizes (the in-game orientation), from the headers only.
        sizes = []
        for fn in names:
            try:
                info = _tex.parse(reader(fn))
                sizes.append((info["height"], info["width"]))
            except Exception:
                sizes.append((0, 0))
        # Per-TILE geometry. The engine pitches tile i at (col << 9, -(row << 9)) --
        # exactly 512 px apart -- and draws it at its own size, so a tile narrower than
        # 512 that is NOT in the last column leaves a hole to its right in that row.
        # Taking a column's widest tile would mask that, which is precisely the case a
        # resize creates: an old last-column (narrow) tile becomes an interior one.
        gap_x, gap_y = [], []
        short_x = short_y = 0
        for i, (w, h) in enumerate(sizes[:need]):
            c, r = i % cols, i // cols
            if c == cols - 1:
                short_x = max(short_x, ext_x - (c * FULL_TILE + w))
            elif 0 < w < FULL_TILE:
                gap_x.append(i)
            if r == rows - 1:
                short_y = max(short_y, ext_y - (r * FULL_TILE + h))
            elif 0 < h < FULL_TILE:
                gap_y.append(i)
        out.append({
            "layer": ly, "set": st, "kind": "grid", "cols": cols, "rows": rows,
            "need": need, "have": have,
            "missing": list(range(have, need)) if have < need else [],
            "extra": list(range(need, have)) if have > need else [],
            "gap_x": gap_x, "gap_y": gap_y,
            "short_x": max(0, short_x), "short_y": max(0, short_y),
        })
    return out


def stitch(reader, map_name: str, layer: int = 0, aspect=None):
    """Reconstruct one layer's full image for a map.

    ``reader(filename) -> bytes | None`` supplies tile bytes by name (works for a
    loose directory or a bundle).  ``aspect`` = (tiles_w, tiles_h) of the ATTR grid,
    used only to disambiguate all-full-tile atlases.

    Tiles are placed **row-major in screen space**: tile ``i`` at (col=i%C, row=i//C),
    with ``C`` inferred from the post-rotation tile dimensions (see :func:`_infer_cols`).
    The texture decoder already applies ROTATE_90 to put each tile in its in-game
    orientation, so this module pastes them directly without any further rotation.

    Returns ``(PIL.Image RGBA, cols, rows)`` or ``None`` if the layer has no tiles.
    """
    from PIL import Image

    base, uv = _sets_for(reader, map_name)

    # Static maps: layer 0 is the full-screen <base>_UV skybox (one non-tiled sprite).
    # The walkable STAGE is the overlay layer (layer 1, handled below).
    if uv is not None and layer == 0:
        im = _decode_tile_cached(reader, single_name(uv)) or _decode_tile_cached(reader, single_name(base))
        return (im, 1, 1) if im is not None else None

    st = layer_set(reader, map_name, layer)
    if st is None:
        return None
    names = []
    idx = 0
    while True:
        fn = tile_name(st, layer, idx)
        with _TILE_LOCK:
            cached = fn in _TILE_CACHE
        if not cached and reader(fn) is None:
            break
        names.append(fn)
        idx += 1
    imgs = [im for im in _decode_tiles(reader, names) if im is not None]
    if not imgs:
        # Fallback: a single-sprite set with no tile grid (rare non-static case).
        if layer == 0:
            im = _decode_tile_cached(reader, single_name(base))
            if im is not None:
                return im, 1, 1
        return None

    n = len(imgs)
    sizes = [im.size for im in imgs]   # post-ROTATE_90, the in-game orientation
    # Prefer the game's EXACT grid formula (Map_SpawnEntity: cols = ceil(24*ATTR_W/512))
    # when the ATTR aspect is known and it divides the tile count; otherwise fall back to
    # the size-based heuristic (no aspect supplied, or an atlas whose tile count doesn't
    # fit the formula). This makes the layout deterministically match the engine.
    cols = 0
    if aspect:
        gcols = grid_dims(aspect[0], aspect[1])[0]
        if gcols and n % gcols == 0:
            cols = gcols
    if not cols:
        cols = _infer_cols(sizes, aspect)
    rows = -(-n // cols)       # a short last row (heuristic cols not dividing n) still gets placed

    # Row 0 (indices 0..cols-1) gives the column widths; column 0 (indices 0, cols,
    # 2*cols, …) gives the row heights.  In a well-formed atlas, every other row /
    # column has matching widths / heights (verified across the corpus).
    col_widths = [imgs[c].width for c in range(cols)]
    row_heights = [imgs[r * cols].height for r in range(rows)]
    col_x = [sum(col_widths[:c]) for c in range(cols)]
    row_y = [sum(row_heights[:r]) for r in range(rows)]
    W, H = sum(col_widths), sum(row_heights)

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for i, im in enumerate(imgs):
        c, r = i % cols, i // cols
        canvas.paste(im, (col_x[c], row_y[r]))

    # Reconcile the atlas extent with the real map extent (= ATTR_W·24 × ATTR_H·24).
    # Two distinct cases (the difference matters — see MAP_FIELD_03):
    #   * SUB-TILE OVERSHOOT (< 512 px on BOTH axes): the atlas is the map rounded
    #     up to the 512-px tile grid, so the surplus is off-map padding. Crop it so
    #     the extent equals the map (e.g. MAP_CITY_06 78×75: 2048×2048 → 1872×1800).
    #   * WHOLE-TILE-OR-MORE OVERSHOOT on an axis: the atlas legitimately covers MORE
    #     than ATTR·24 — the engine renders the whole atlas scaled (possibly non-
    #     uniformly) to the map's world bounds. Keep the atlas WHOLE and let the
    #     caller resize it to the ATTR grid, which lines the extents up exactly.
    #     (Verified on MAP_FIELD_03 51×42: atlas 2176×1152, ATTR walkable mask lands
    #     precisely on the textured paths only when scaled, not cropped.)
    # `aspect` here carries the ATTR grid (tiles_w, tiles_h).
    if aspect:
        tw = aspect[0] * PX_PER_ATTR_TILE
        th = aspect[1] * PX_PER_ATTR_TILE
        if 0 <= W - tw < FULL_TILE and 0 <= H - th < FULL_TILE and (tw, th) != (W, H):
            canvas = canvas.crop((0, 0, tw, th))
    return canvas, cols, rows


def tile_layout(reader, map_name: str, layer: int = 0, aspect=None):
    """The exact per-tile geometry :func:`stitch` uses for one layer, WITHOUT decoding
    any pixels (sizes come from the tile headers; a decoded tile is ``h x w`` after the
    decoder's ROTATE_90, which is what stitch lays out).

    Returns ``None`` when the layer has no tiles, else a dict::

        {"set": texture-set name the files belong to (often NOT the map name),
         "kind": "grid" | "single",       # single = a full-screen _UV sprite (1 tile)
         "cols": C, "rows": R,
         "canvas": (W, H),                # the uncropped stitched size
         "crop": (tw, th) | None,         # what stitch crops the canvas to (sub-tile
                                          #   overshoot case) -- None = not cropped
         "tiles": [{"index": i, "name": file, "x": .., "y": .., "w": .., "h": ..}, ...]}

    ``x/y/w/h`` are the tile's box on the (uncropped) canvas in the in-game orientation.
    """
    base, uv = _sets_for(reader, map_name)
    if uv is not None and layer == 0:
        for set_name in (uv, base):
            fn = single_name(set_name)
            b = reader(fn)
            if b is not None:
                info = _tex.parse(b)
                w, h = info["height"], info["width"]          # post-ROTATE_90 size
                return {"set": set_name, "kind": "single", "cols": 1, "rows": 1,
                        "canvas": (w, h), "crop": None,
                        "tiles": [{"index": 0, "name": fn, "x": 0, "y": 0, "w": w, "h": h}]}
        return None
    st = layer_set(reader, map_name, layer)
    if st is None:
        return None
    sizes, names = [], []
    idx = 0
    while True:
        fn = tile_name(st, layer, idx)
        b = reader(fn)
        if b is None:
            break
        info = _tex.parse(b)
        sizes.append((info["height"], info["width"]))       # post-ROTATE_90 size
        names.append(fn)
        idx += 1
    if not sizes:
        if layer == 0:
            fn = single_name(base)
            b = reader(fn)
            if b is not None:
                info = _tex.parse(b)
                w, h = info["height"], info["width"]
                return {"set": base, "kind": "single", "cols": 1, "rows": 1,
                        "canvas": (w, h), "crop": None,
                        "tiles": [{"index": 0, "name": fn, "x": 0, "y": 0, "w": w, "h": h}]}
        return None
    n = len(sizes)
    cols = 0
    if aspect:
        gcols = grid_dims(aspect[0], aspect[1])[0]
        if gcols and n % gcols == 0:
            cols = gcols
    if not cols:
        cols = _infer_cols(sizes, aspect)
    rows = -(-n // cols)       # a short last row (heuristic cols not dividing n) still gets placed
    col_widths = [sizes[c][0] for c in range(cols)]
    row_heights = [sizes[r * cols][1] for r in range(rows)]
    col_x = [sum(col_widths[:c]) for c in range(cols)]
    row_y = [sum(row_heights[:r]) for r in range(rows)]
    W, H = sum(col_widths), sum(row_heights)
    tiles = []
    for i, (w, h) in enumerate(sizes):
        c, r = i % cols, i // cols
        tiles.append({"index": i, "name": names[i], "x": col_x[c], "y": row_y[r], "w": w, "h": h})
    crop = None
    if aspect:
        tw = aspect[0] * PX_PER_ATTR_TILE
        th = aspect[1] * PX_PER_ATTR_TILE
        if 0 <= W - tw < FULL_TILE and 0 <= H - th < FULL_TILE and (tw, th) != (W, H):
            crop = (tw, th)
    return {"set": st, "kind": "grid", "cols": cols, "rows": rows,
            "canvas": (W, H), "crop": crop, "tiles": tiles}


def unstitch(reader, map_name: str, image, layer: int = 0, aspect=None, *, fmt=None):
    """Inverse of :func:`stitch`: split an edited full-layer image back into the
    per-tile ``.texture`` files, using the same grid, tile sizes and rotation stitch
    used, so the files can be installed as loose overrides.

    ``image`` (PIL) must be the size stitch produced for this layer with the same
    ``aspect`` -- either the cropped extent or the full canvas. When it is the cropped
    extent, the cropped-away padding is refilled from the original tiles so the edit
    only touches what the user saw. Each tile is re-encoded with
    :func:`rf4s_modkit.texture.encode_into`: ``fmt`` None / ``"keep"`` keeps the tile's
    own format (BC7 tiles stay BC7 at the same size, so the files can also be
    ``bundle patch``-ed in place); ``"RGBA8"`` / ``"BC7"`` / ``"BC3"`` / ``"BC1"`` / a raw
    name forces one. Returns ``[(filename, bytes), ...]`` in tile order.
    """
    from PIL import Image

    lay = tile_layout(reader, map_name, layer, aspect)
    if lay is None:
        raise ValueError(f"{map_name}: layer {layer} has no atlas")
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    W, H = lay["canvas"]
    if image.size == (W, H):
        canvas = image
    elif lay["crop"] is not None and image.size == lay["crop"]:
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for t in lay["tiles"]:
            src = _decode_tile_cached(reader, t["name"])
            if src is not None:
                canvas.paste(src, (t["x"], t["y"]))
        canvas.paste(image, (0, 0))
    else:
        want = f"{W}x{H}" + (f" or the cropped {lay['crop'][0]}x{lay['crop'][1]}" if lay["crop"] else "")
        raise ValueError(f"{map_name} layer {layer}: image is {image.size[0]}x{image.size[1]}, "
                         f"expected {want} (as `stitch`/ground-export produced it)")
    out = []
    for t in lay["tiles"]:
        tmpl = reader(t["name"])
        if tmpl is None:
            raise ValueError(f"tile {t['name']} disappeared")
        crop = canvas.crop((t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"]))
        out.append((t["name"], _tex.encode_into(tmpl, crop, fmt=fmt)))
    return out


def stitch_composite(reader, map_name: str, aspect=None, layers=None):
    """Full in-game ground = all draw layers alpha-composited bottom-up.

    ``layers`` defaults to every layer that exists (0 = ground, 1 = overlay).  Pass
    e.g. ``layers=[0]`` for the bare floor or ``[1]`` for the overlay alone.

    Returns ``(PIL.Image RGBA, cols, rows)`` or ``None`` if no atlas resolves.
    """
    from PIL import Image

    if layers is None:
        layers = available_layers(reader, map_name)
    ext = (aspect[0] * PX_PER_ATTR_TILE, aspect[1] * PX_PER_ATTR_TILE) if aspect else None
    base = None
    cols = rows = 0
    for ly in layers:
        res = stitch(reader, map_name, ly, aspect)
        if res is None:
            continue
        img, cols, rows = res
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        # Normalise every layer to the ATTR extent first, so mixed-size layers compose
        # in alignment — e.g. a 1024² _UV skybox under a 1536² tiled stage (a static
        # map), or an oversized "scale-case" atlas resized down to the map bounds.
        if ext and img.size != ext:
            img = img.resize(ext, Image.BILINEAR)
        if base is None:
            base = img
        else:
            if img.size != base.size:
                img = img.resize(base.size, Image.BILINEAR)
            base = Image.alpha_composite(base, img)
    if base is None:
        return None
    return base, cols, rows
