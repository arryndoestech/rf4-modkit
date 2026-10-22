"""Rendering: the ground texture (decoded off the UI thread), the ATTR fill, and the
overlay primitives shared by the canvas and the PNG export.

The overlays are produced once as plain primitives (`Prim`) per group; `view.MapView`
turns them into canvas items and `render_image()` draws the very same list with PIL, so
an exported PNG is exactly what the canvas shows (minus the selection)."""
from __future__ import annotations

import queue
import threading
from collections import OrderedDict

from rf4s_modkit import (collisionstamp, flagstate, gen, map_names, mapground, mobj_meshes, mobj_types,
                         model, spritequad, texture)

from . import attrs, ui

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:           # the editor still runs, with a plain-rectangle ATTR view
    HAS_PIL = False

# Overlay groups, bottom to top.
GROUPS = ("under", "stamp", "grid", "region", "warp", "ent", "si", "gate", "spawn", "dest", "sel")
# canvas stacking, bottom to top: the ground texture ("bg"), the ATTR fill + cell edges
# ("attr"), the sprites ("under", drawn as the game draws them, above the fill so the
# objects stay visible), then every other overlay group
STACK = ("bg", "attr", "under") + tuple(g for g in GROUPS if g != "under")

SEL_COLOR = "#00e5ff"
WARP_COLOR = "#ffd040"
BORDER_COLOR = "#ff3030"        # the outline of every sprite ("sprite borders")
SI_COLOR = "#ffe000"
GATE_COLOR = "#ff8c1a"
GATE_HIDDEN_COLOR = "#9a9a9a"            # an invisible gate (spawner): gray G
MPOS_COLOR = "#ff5aa0"
SPAWN_COLOR = "#c060ff"
REGION_COLOR = "#40d0c0"      # the event script's player areas (PlayerRegionTrigger)
STAMP_COLOR = "#ff40c0"          # the collision the objects stamp into ATTR at load: blocks the player
STAMP_WALK_COLOR = "#40e080"     # ... the stamp makes the tile walkable (the airship gangway)
STAMP_MARK_COLOR = "#a8a8b4"     # ... stamped, walking unchanged (a tree's canopy ring: marker only)
HANDLES = ("nw", "n", "ne", "w", "e", "sw", "s", "se")


class Prim:
    """One drawable: kind in rect / oval / poly / line / text / sprite (an object's sprite
    filling its xy rectangle, as the game draws it). `key` is the
    selection key the item hit-tests to (None = decoration only)."""
    __slots__ = ("kind", "xy", "opt", "key")

    def __init__(self, kind, xy, key=None, **opt):
        self.kind, self.xy, self.key, self.opt = kind, xy, key, opt


# --------------------------------------------------------------------------- #
# ground texture
# --------------------------------------------------------------------------- #
class GroundLoader:
    """Decodes + stitches ground atlases on one worker thread (BC7 decode is GIL-bound;
    one thread also keeps bundle reads serial) and keeps an LRU of the results, so a
    map's ATTR and objects show at once and the texture fills in."""

    CACHE_MAX = 8

    def __init__(self, tk_widget, on_ready):
        self._w = tk_widget
        self._on_ready = on_ready          # on_ready(key) on the UI thread
        self.reader = None
        self.cache = OrderedDict()
        self.generation = 0
        self._req = queue.Queue()
        self._res = queue.Queue()
        self._worker = None
        self._pending = 0
        self._polling = False

    def reset(self):
        """Forget every decoded ground and drop in-flight work (reader changed)."""
        self.cache.clear()
        self.generation += 1

    def suspend(self):
        """Drop queued / in-flight decodes (the host hid the editor)."""
        self.generation += 1

    @staticmethod
    def decode(reader, base, sel, w, h, scenery=False):
        """PIL RGBA for (map base, 'off' | 'all' | '<layer> ...', scenery) or None: the
        ground atlas, with the map's over-model scenery drawn on top when `scenery`.
        Pure: thread-safe."""
        img = None
        if sel != "off":
            try:
                if sel == "all":
                    res = mapground.stitch_composite(reader, base, aspect=(w, h))
                else:
                    res = mapground.stitch(reader, base, int(sel.split()[0]), aspect=(w, h))
                img = res[0].convert("RGBA") if res else None
            except Exception:
                img = None
        if scenery:
            size = img.size if img is not None else (w * mapground.PX_PER_ATTR_TILE,
                                                     h * mapground.PX_PER_ATTR_TILE)
            sc = scenery_image(reader, base, w, size)
            if sc is not None:
                img = sc if img is None else Image.alpha_composite(img, sc)
        return img

    def get(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def has(self, key):
        return key in self.cache

    def put(self, key, img):
        self.cache[key] = img
        self.cache.move_to_end(key)
        while len(self.cache) > self.CACHE_MAX:
            self.cache.popitem(last=False)

    def get_blocking(self, base, sel, w, h, scenery=False):
        key = (base, sel, scenery, w, h)          # the stitch is laid out for the grid size
        if key not in self.cache:
            self.put(key, self.decode(self.reader, base, sel, w, h, scenery))
        return self.get(key)

    def request(self, base, sel, w, h, scenery=False):
        key = (base, sel, scenery, w, h)
        if not (HAS_PIL and self.reader) or (sel == "off" and not scenery) or key in self.cache:
            return
        if self._worker is None:
            self._worker = threading.Thread(target=self._loop, daemon=True)
            self._worker.start()
        self._pending += 1
        self._req.put((self.reader, base, sel, w, h, scenery, self.generation))
        if not self._polling:
            self._polling = True
            ui.later(self._w, self._poll, 25)

    def _loop(self):
        while True:
            reader, base, sel, w, h, scenery, gen = self._req.get()
            img = None if gen != self.generation else self.decode(reader, base, sel, w, h, scenery)
            self._res.put(((base, sel, scenery, w, h), img, gen))

    def _poll(self):
        ready = []
        try:
            while True:
                key, img, gen = self._res.get_nowait()
                self._pending = max(0, self._pending - 1)
                if gen == self.generation:
                    self.put(key, img)
                    ready.append(key)
        except queue.Empty:
            pass
        for key in ready:
            self._on_ready(key)
        if self._pending > 0:
            ui.later(self._w, self._poll, 25)
        else:
            self._polling = False


_SCENERY = OrderedDict()          # over-model set name -> parsed model.Model | None


def scenery_model(reader, base):
    """The parsed over-model (`g_mapResourceTable[+3]`) of a map, or None (no over-model,
    not found, or only empty placeholder cards)."""
    setname = mapground.overmodel_for(base) if base else None
    if not setname or reader is None:
        return None
    if setname not in _SCENERY:
        m = None
        try:
            blob = reader(setname + ".model")
            if blob is not None and model.is_mesh(blob):
                m = model.parse(blob)
        except Exception:
            m = None
        _SCENERY[setname] = m
        while len(_SCENERY) > 16:
            _SCENERY.popitem(last=False)
    _SCENERY.move_to_end(setname)
    return _SCENERY[setname]


def scenery_image(reader, base, w, size):
    """The map's over-model drawn top-down at `size` (the ground image's size for a
    `w`-tile-wide map), transparent where it has no card; None when there is none."""
    m = scenery_model(reader, base)
    if m is None:
        return None
    try:
        px_per_unit = size[0] / (w * 8.0)
        img = model.render_overmodel(m, size[0], size[1], px_per_unit)
    except Exception:
        return None
    return img if img.getchannel("A").getbbox() else None


# --------------------------------------------------------------------------- #
# background = ground texture + ATTR fill + ATTR edges
# --------------------------------------------------------------------------- #
class Background:
    """Builds and caches the background image; it is rebuilt only when the grid, the
    zoom, the texture or a background setting changes -- not on selection or overlay
    changes."""

    def __init__(self):
        self._key = None
        self._img = None
        self._scaled = (None, None, None)       # (source image, size, scaled RGBA)

    def invalidate(self):
        self._key = None

    def layers(self, grid, colors, cp, ground, *, attr_on, alpha, edges_on, attr_version,
               under=False, dim=0):
        """(ground, attr): the scaled ground texture and the ATTR fill + cell edges as a
        separate RGBA layer (either may be None); the sprites are drawn above
        both. The fill takes the ATTR opacity when anything lies beneath it (the
        ground, or sprites when `under`); otherwise it is opaque. `dim` (0..100 %) darkens
        the ground so the objects on it stand out. Callers must not draw on the images."""
        if not HAS_PIL or grid is None:
            return None, None
        below = ground is not None or under
        dim = max(0, min(100, int(dim)))
        key = (attr_version, len(colors), cp, id(ground), attr_on, alpha if below else 255,
               edges_on, below, dim)
        if key == self._key:
            return self._img
        w, h, cells = grid
        base = None
        if ground is not None:
            src, size, scaled = self._scaled
            if src is not ground or size != (w * cp, h * cp):
                scaled = ground.resize((w * cp, h * cp), Image.BILINEAR).convert("RGBA")
                self._scaled = (ground, (w * cp, h * cp), scaled)
            base = scaled
            if dim:                         # darker ground: every channel x (1 - dim)
                f = (100 - dim) / 100
                r, g, b, a = base.split()
                base = Image.merge("RGBA", [ch.point(lambda v: int(v * f)) for ch in (r, g, b)] + [a])
        top = None
        if attr_on:
            idx = self._index_image(w, h, cells, colors)
            fill = idx.convert("RGBA")
            fill.putalpha(max(0, min(255, int(alpha))) if below else 255)
            top = fill.resize((w * cp, h * cp), Image.NEAREST)
            if edges_on and cp >= 2:
                top = self._edges(top, idx, w, h, cp, over_texture=ground is not None)
        self._key, self._img = key, (base, top)
        return base, top

    def image(self, grid, colors, cp, ground, **kw):
        """The two layers composited into one RGBA image, or None when nothing is enabled."""
        base, top = self.layers(grid, colors, cp, ground, **kw)
        if base is None or top is None:
            return base if top is None else top
        return Image.alpha_composite(base, top)

    @staticmethod
    def _index_image(w, h, cells, colors):
        """'P' image: one pixel per cell, palette = the value colours."""
        lut, pal = {}, []
        for v, rgb in colors.items():
            if len(lut) >= 255:
                break
            lut[v] = len(lut)
            pal.extend(rgb)
        floor = len(lut)
        pal.extend(attrs.ATTR_FLOOR)
        im = Image.frombytes("P", (w, h), bytes(lut.get(c, floor) for c in cells))
        im.putpalette(pal + [0] * (768 - len(pal)))
        return im

    @staticmethod
    def _edges(base, idx, w, h, cp, *, over_texture):
        """A thin line on every boundary between cells of different value. Built with
        whole-image operations (no per-cell drawing), so it costs a few ms."""
        color = (255, 255, 0, 230) if over_texture else (0, 0, 0, 200)
        lw = max(1, cp // 6) if over_texture else 1
        # the palette indices as grey levels, so equal values compare equal
        L = Image.frombytes("L", (w, h), idx.tobytes())
        shift = (lw + 1) // 2           # centre the line on the cell boundary
        mask = Image.new("L", (w * cp, h * cp), 0)
        if w > 1:
            d = ImageChops.difference(L.crop((0, 0, w - 1, h)), L.crop((1, 0, w, h)))
            d = d.point(lambda v: 255 if v else 0).resize(((w - 1) * cp, h * cp), Image.NEAREST)
            row = bytes(255 if (x % cp) >= cp - lw else 0 for x in range((w - 1) * cp))
            stripe = Image.frombytes("L", ((w - 1) * cp, 1), row).resize(((w - 1) * cp, h * cp), Image.NEAREST)
            mask.paste(ImageChops.multiply(d, stripe), (shift, 0))
        if h > 1:
            d = ImageChops.difference(L.crop((0, 0, w, h - 1)), L.crop((0, 1, w, h)))
            d = d.point(lambda v: 255 if v else 0).resize((w * cp, (h - 1) * cp), Image.NEAREST)
            col = bytes(255 if (y % cp) >= cp - lw else 0 for y in range((h - 1) * cp))
            stripe = Image.frombytes("L", (1, (h - 1) * cp), col).resize((w * cp, (h - 1) * cp), Image.NEAREST)
            m2 = Image.new("L", (w * cp, h * cp), 0)
            m2.paste(ImageChops.multiply(d, stripe), (0, shift))
            mask = ImageChops.lighter(mask, m2)
        out = base.copy()
        out.paste(Image.new("RGBA", out.size, color), (0, 0), mask)
        return out


# --------------------------------------------------------------------------- #
# object sprites
# --------------------------------------------------------------------------- #
def _glow_mirror(img, quad):
    """Sprite_ApplyEffect_Glow: the texture is one corner of the picture; the game mirrors
    it into all four around the object and doubles the sprite's size."""
    return spritequad.glow_mirrored(img), tuple(v * 2 for v in quad)


def _as_additive(img):
    """An additively blended sprite (blend state 2: dst + src * a) as an ordinary alpha
    sprite the canvas can draw: each pixel's brightness becomes its opacity, its colour is
    brightened to match -- dark parts vanish, bright parts light the ground up, as in the game."""
    r, g, b, a = img.split()
    peak = ImageChops.lighter(ImageChops.lighter(r, g), b)
    alpha = ImageChops.multiply(peak, a)
    try:
        import numpy as np
        rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
        pk = np.maximum(rgb.max(axis=2, keepdims=True), 1.0)
        rgb = (rgb * (255.0 / pk)).clip(0, 255).astype(np.uint8)
        out = Image.fromarray(rgb, "RGB").convert("RGBA")
    except ImportError:                     # without numpy: keep the colours as they are
        out = img.convert("RGBA")
    out.putalpha(alpha)
    return out


# the monster gate's layer strengths and the orb under them, fitted to an in-game screenshot
# of the Yokmir Forest gate (see _gate_image)
GATE_GAINS = {"efc_whirl2": 0.3, "efc_lite": 0.3, "efc_gate01L": 2.5}
GATE_SHADE = (35, 45, 75, 230)


def _gate_image(data, gains=None):
    """The monster gate as the game shows it: EFC_00_GATEA's six quads (all centred, facing
    the camera, 2 model units per sub-unit), each texture times its material's
    CombineColor00 added onto the scene (BlendType 2 / 3 -- SrcAlpha, One / One, One), the
    quarter glow efc_lite mirrored into a round one; under them the actor's drop shadow, a
    navy orb. Layer strengths (GATE_GAINS) and the orb (GATE_SHADE) are fitted to an in-game
    screenshot of the Yokmir Forest gate -- a dark blue orb, orange and teal streaks out to
    its rim, a small bright centre; the layers pulse in the game, this is one moment.
    Returns (RGBA, quad in sprite px) or None without numpy."""
    try:
        import numpy as np
    except ImportError:
        return None
    from PIL import ImageDraw, ImageFilter
    m = model.parse(data)
    shapes = []
    for sh in m.shapes:
        mat = m.materials[sh.material]
        name = mat.textures[0] if mat.textures else None
        if name is None:
            continue
        pts = m.shape_vertices(sh)
        half = max(abs(v[0]) for v in pts)
        tex = texture.decode_bntx(m.data, m.texture_index(name)).convert("RGBA")
        if name == "efc_lite":                 # stored as the corner of a round glow
            w, h = tex.size
            whole = Image.new("RGBA", (w * 2, h * 2))
            whole.paste(tex, (0, h))
            whole.paste(tex.transpose(Image.FLIP_LEFT_RIGHT), (w, h))
            whole.paste(tex.transpose(Image.FLIP_TOP_BOTTOM), (0, 0))
            whole.paste(tex.transpose(Image.ROTATE_180), (w, 0))
            tex = whole
        uv = m.vertex_buffers[sh.vertex_buffer].data.get("_u0") or [(0, 0)]
        if uv[0][0] > 0.5:                     # this quad's U runs right to left
            tex = tex.transpose(Image.FLIP_LEFT_RIGHT)
        k = (gains or GATE_GAINS).get(name, 1.0)
        col = [c * k for c in mat.user_data.get("CombineColor00", [1, 1, 1])[:3]]
        shapes.append((mat.user_data.get("DrawOrder", [0])[0], pts[0][2], half, tex, col))
    if not shapes:
        return None
    R = max(s[2] for s in shapes)
    size = int(2 * R) + 2                      # 1 px per model unit
    acc = np.zeros((size, size, 3), np.float32)
    for _order, _z, half, tex, col in sorted(shapes, key=lambda s: (s[0], s[1])):
        d = max(1, int(2 * half))
        t = np.asarray(tex.resize((d, d), Image.BILINEAR), np.float32) / 255
        o = (size - d) // 2
        acc[o:o + d, o:o + d] += t[..., :3] * np.asarray(col, np.float32) * t[..., 3:4]
    glow = _as_additive(Image.fromarray((acc.clip(0, 1) * 255).astype(np.uint8), "RGB").convert("RGBA"))
    shadow = Image.new("L", (size, size), 0)
    r = size * 0.38
    ImageDraw.Draw(shadow).ellipse((size / 2 - r, size / 2 - r, size / 2 + r, size / 2 + r),
                                   fill=GATE_SHADE[3])
    shadow = shadow.filter(ImageFilter.GaussianBlur(size * 0.012))
    img = Image.new("RGBA", (size, size), GATE_SHADE[:3] + (0,))
    img.putalpha(shadow)
    img = Image.alpha_composite(img, glow)
    # drawn 10 % under the model's own size: the composite's soft outer layers read larger
    # than the orb the game shows (user comparison with the Yokmir Forest gate)
    q = spritequad.PX_PER_SUBUNIT / MODEL_UNITS_PER_SUBUNIT * size / 2 * 0.9
    return img, (-q, -q, q, q)


def _whole_frame(data, frame):
    """A texture without sprite placement data (propeller_ship_02): the whole frame,
    centred on the object at its own size."""
    img = texture.decode_to_image(data, frame=frame)
    if img is None:
        return None
    w, h = img.size
    return img.convert("RGBA"), (-w / 2, -h / 2, w / 2, h / 2)


# Model units per map sub-unit for objects drawn from a .model: the four fishing spots round
# MAP_DUNG_J03's pond (34..48 sub-units out, fish scattered 16 further) stay on its water only
# at 2 (the pond's rim then sits 64 sub-units out), and an in-game screenshot shows the chest
# a bit wider than the 32-sub-unit crate beside it (68 units / 2 = 34).
MODEL_UNITS_PER_SUBUNIT = 2.0


# the random wood / stone spawns (forage types 3 / 4) roll one of three things each day; the
# editor draws the smallest: the Branch (kind 3; else Stump 4, Broken Stump 5) and the Stone
# (kind 1; else Rock 2, Clay Stone 22)
POOL_SPAWN_SHOWN = {3: 3, 4: 1}


class Sprites:
    """A placed object's sprite as the game draws it: the texture's TextureCoordinator
    crop, sized and offset by its PolygonVertexes quad (rf4s_modkit.spritequad)."""

    def __init__(self):
        self.reader = None
        self.cell = None                   # (tile x, tile y) -> ATTR of the map drawn (overlay)
        self._ore_cfg = None               # MapOre_Rate rows, read once per reader
        self._src = {}                     # (texture name, frame) -> (RGBA, quad) | None
        self._scaled = OrderedDict()

    def reset(self):
        self._src.clear()
        self._scaled.clear()
        self._ore_cfg = None

    def source(self, o):
        """(texture name, frame, quad) for a decoded MOBJ entry, or None."""
        r = self.reader
        p = o.get("params", ())
        mdl = mobj_types.mobj_model(p) if p else None
        if mdl and r is not None:
            return self._model_source(*mdl)
        name = mobj_types.mobj_texture(p) if p else o.get("name")
        if p and (p[0] & 0xFFFF) < 9:          # forage: the gatherable it grows, when fixed
            name = self._forage_sprite(p)
        if p and (p[0] & 0xFFFF) == 35:        # one-time item pickup: the dropped item's icon
            name = self._pickup_sprite(p)
        if name == "fish" and len(p) > 15:     # the fish differs on water and on sand
            attr = self.cell(p[14] >> 3, p[15] >> 3) if self.cell else None
            name = mobj_types.fish_texture(0x8 if attr is None else attr)
        if r is None or not name:
            return None
        fn = name + ".texture"
        frame = p[7] if len(p) > 7 and p[7] > 0 else 0
        tid = p[0] & 0xFFFF if p else 0
        tint = mobj_types.mobj_tint(tid) if p else None
        glow = bool(p) and mobj_types.mobj_glow(p)
        additive = tid in mobj_types.MOBJ_ADDITIVE
        mesh = mobj_meshes.mesh_for(p) if tid in (70, 71, 72) else None
        if tint or glow or additive:
            fn += "@fx"                      # its own cache entry
        if mesh:                             # one entry per mesh (kind), not per texture
            fn += f"@mesh{tid}.{p[8] if len(p) > 8 else 0}"
            frame = 0
        key = (fn, frame)
        if key not in self._src:
            got = None
            data = r(fn.split("@", 1)[0])
            if data is not None:
                try:
                    if mesh:
                        got = mobj_meshes.rasterize_cached(data, mesh[1], mesh[2],
                                                           mirror=tid == 71)
                    else:
                        if frame >= texture.frame_count(data):
                            frame = 0
                        got = spritequad.sprite_image(data, frame) or _whole_frame(data, frame)
                    if got and tint:
                        *rgb, a = got[0].split()
                        rgb = [ch.point(lambda v, f=f: int(v * f)) for ch, f in zip(rgb, tint)]
                        got = (Image.merge("RGBA", (*rgb, a)), got[1])
                    if got and glow:
                        got = _glow_mirror(*got)
                    if got and additive:
                        got = (_as_additive(got[0]), got[1])
                except Exception:
                    got = None
            self._src[key] = got
        got = self._src[key]
        return (fn, key[1], got[1]) if got else None

    def image(self, o):
        """The object's sprite as a PIL image at its own size (mirrored like the game draws
        it), or None when it has none."""
        src = self.source(o)
        got = self._src.get((src[0], src[1])) if src else None
        if not got:
            return None
        return got[0].transpose(Image.FLIP_LEFT_RIGHT) if spritequad.mirrored(o) else got[0]

    def gate_source(self):
        """(key, 0, quad) for a monster gate, or None: every Gate actor kind (359..390)
        takes model 754 = mons/EFC_00_GATEA from rf3NpcParam -- six camera-facing quads
        added onto the scene over the actor's drop shadow (see _gate_image)."""
        key = ("EFC_00_GATEA.model@gate", 0)
        if self.reader is None:                 # nothing to read from yet: don't remember "none"
            return None
        if key not in self._src:
            got = None
            data = self.reader("EFC_00_GATEA.model")
            if data is not None:
                try:
                    got = _gate_image(data)
                except Exception:
                    got = None
            self._src[key] = got
        got = self._src[key]
        return (key[0], 0, got[1]) if got else None

    def _forage_sprite(self, p):
        """The crop_NNN sprite a forage spawn grows (MapEntity_ResolveSpriteArchiveId: archive
        1366 + gatherable kind), when the record fixes it: an ore spawn (type 0) its
        MapOre_Rate config's rock (f10; not when f11 rolls a config each day), the rune
        flower (1, kind 23), the rune crystal (2, kind 24), type 8 the kind in f10. The wood
        and stone spawns (3 / 4) roll one of three things each day and are drawn as the
        smallest (POOL_SPAWN_SHOWN: Branch / Stone). The herb pools (5..7) grow a different
        thing each day: None, the marker stays."""
        from rf4s_modkit import mobj_params
        tid = p[0] & 0xFFFF
        w = lambda k: p[k] if len(p) > k else 0
        kind = None
        if tid == 0 and not w(11):
            if self._ore_cfg is None:
                from . import data
                self._ore_cfg = data.ore_configs(self.reader) if self.reader else []
            cfg = self._ore_cfg
            if 0 <= (w(10) & 0xFF) < len(cfg):
                kind = cfg[w(10) & 0xFF][0]
        elif tid in (1, 2):
            kind = 22 + tid
        elif tid in POOL_SPAWN_SHOWN:
            kind = POOL_SPAWN_SHOWN[tid]
        elif tid == 8:
            kind = w(10) & 0x7F
        return mobj_params.gather_kind_sprite(kind) if kind is not None else None

    @staticmethod
    def _pickup_sprite(p):
        """The item icon a one-time pickup (type 35) drops: item 48 (a Mushroom) for f9 = 0;
        for the random kinds 1 / 2 the first of their items is drawn, like the wood / stone
        pools. None for kind 3 (no fixed item: the marker stays)."""
        from rf4s_modkit import mobj_params
        items = mobj_params.PICKUP_KIND_ITEMS.get(p[9] if len(p) > 9 else 0)
        return mobj_params.item_icon_texture(items[0]) if items else None

    def _model_source(self, name, view, px_per_unit=2.0):
        """(key, 0, quad) for an object the game draws as a 3D model: the .model rendered
        once from `view`, its quad in sprite pixels around the object, which stands at the
        model's origin. MODEL_UNITS_PER_SUBUNIT model units make one map sub-unit."""
        fn = f"{name}.model@{view}"
        key = (fn, 0)
        if key not in self._src:
            got = None
            data = self.reader(name + ".model")
            if data is not None:
                try:
                    m = model.parse(data)
                    tris = model._triangles(m, model.VIEWS[view])
                    pts = [q for t in tris for q in t[1]]
                    if pts:
                        x0, y0 = min(q[0] for q in pts), min(q[1] for q in pts)
                        x1, y1 = max(q[0] for q in pts), max(q[1] for q in pts)
                        span = max(x1 - x0, y1 - y0, 1e-6)
                        size = int(span * px_per_unit) + 4
                        img = model.render(m, view, size)
                        k = (size - 4) / span        # render()'s own fit, 2 px margin
                        q = spritequad.PX_PER_SUBUNIT / MODEL_UNITS_PER_SUBUNIT
                        got = (img, (q * (x0 - 2 / k), q * (y0 - 2 / k),
                                     q * (x0 + (img.width - 2) / k), q * (y0 + (img.height - 2) / k)))
                except Exception:
                    got = None
            self._src[key] = got
        got = self._src[key]
        return (fn, 0, got[1]) if got else None

    @staticmethod
    def z_key(o):
        """Draw order: the room mesh (72) under everything, then the water (71), the ponds
        (60) and the light shafts (70), then the sprites in the game's depth order (the fish
        swim on top of the ponds)."""
        tid = o["type_id"] & 0xFFFF
        return ({72: 0, 71: 1, 60: 1, 70: 1}.get(tid, 2), spritequad.z_key(o))

    def pil(self, fn, frame, w, h, mirror):
        """The sprite resized to w x h canvas pixels (mirrored when asked)."""
        key = (fn, frame, w, h, mirror)
        if key in self._scaled:
            self._scaled.move_to_end(key)
            return self._scaled[key]
        got = self._src.get((fn, frame))
        if not got:
            return None
        im = got[0].resize((max(1, w), max(1, h)), Image.BILINEAR)
        if mirror:
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        self._scaled[key] = im
        while len(self._scaled) > 256:
            self._scaled.popitem(last=False)
        return im


# --------------------------------------------------------------------------- #
# overlay primitives
# --------------------------------------------------------------------------- #
def warp_rect_px(rec, cp):
    """Canvas rectangle of a MAPJ zone (at least one tile)."""
    x0, y0 = (rec[1] >> 3) * cp, (rec[2] >> 3) * cp
    x1, y1 = ((rec[1] + rec[3]) >> 3) * cp, ((rec[2] + rec[4]) >> 3) * cp
    return x0, y0, max(x1, x0 + cp), max(y1, y0 + cp)


RUNTIME_WALL_COLOR = "#ff7050"


# what the editor tells a modder about the game's own warps / walls (tooltip, Objects tab)
HARDCODED_NOTE = ("Built into the game, not stored in this map: its position, size, destination "
                  "and when it appears are fixed, so it is shown but cannot be moved, resized or "
                  "removed.")


def runtime_spawns(doc):
    """[(tile rect (x0, y0, x1, y1) exclusive, spawn dict, tip text)] of the warps and walls
    the game adds to this map at load (rf4s_modkit.mapres.runtime_spawns: the farm, its fields,
    the farmhouse, the barns and two town maps) -- not in the .rf4m, drawn read-only."""
    from rf4s_modkit import mapres
    from . import data
    mid = data.base_map_id(doc.base) if doc is not None and doc.base else None
    out = []
    for s in mapres.runtime_spawns(mid) if mid is not None else ():
        if s["kind"] == "warp":
            x0, y0, x1, y1 = s["box"]
            rect = (x0 >> 3, y0 >> 3, max((x1 >> 3), (x0 >> 3) + 1), max((y1 >> 3), (y0 >> 3) + 1))
            dest = map_names.map_file(s["dest"]) or f"map {s['dest']}"
            place = map_names.map_name(s["dest"])
            tip = (f"warp to {dest}" + (f" ({place})" if place else "")
                   + f", arriving at ({s['arrive'][0]}, {s['arrive'][1]})")
            fix = ("To keep players out, paint walls (ATTR 0x2) over its zone; the room it leads "
                   "to is an ordinary map you can edit; a warp of your own can go anywhere.")
        else:
            cells = mapres.wall_cells(s["box"])
            if cells is None:
                continue
            rect = (cells[0], cells[1], cells[2] + 1, cells[3] + 1)
            tip = "wall: these tiles are set to blocked (ATTR 0x2) and a fence / door sprite is drawn"
            fix = "Paths around it can be painted; the wall itself stays."
        out.append((rect, s, f"{tip}\nAppears when {s['when']}.\n{HARDCODED_NOTE}\n{fix}"))
    return out


def handle_points(rect):
    x0, y0, x1, y1 = rect
    mx, my = (x0 + x1) // 2, (y0 + y1) // 2
    return {"nw": (x0, y0), "n": (mx, y0), "ne": (x1, y0), "w": (x0, my), "e": (x1, my),
            "sw": (x0, y1), "s": (mx, y1), "se": (x1, y1)}


def entity_visible(o, layers):
    """Whether the layers show this record: every placed record, (0, 0) included (the game
    spawns it there); only the positionless map parameters 9..19 are never drawn."""
    cat = o["category"]
    key = "trigger" if cat in attrs.TRIGGER_KINDS else cat
    return layers.get(key, True) and cat != "mapparam"


_STAMPS = [None, None]          # [key, stamps] for the last document / flag snapshot asked


def object_stamps(doc, flags):
    """collisionstamp.stamps for the document's MOBJ records and grid, cached until the
    records, the grid or the flag snapshot change."""
    key = (id(doc), id(doc.objs), doc.attr_version, id(flags))
    if _STAMPS[0] != key:
        W, H, _ = doc.grid
        _STAMPS[:] = [key, collisionstamp.stamps(doc.map.mobj_records(), W, H, flags)]
    return _STAMPS[1]


def stamps_at(doc, flags, t):
    """[(record index, mode, bits)] of the stamps covering tile `t`."""
    return [(i, mode, cells[t]) for i, mode, cells in object_stamps(doc, flags) if t in cells]


def stamp_runs(cells):
    """{(tx, ty): bits} -> [(tx0, tx1, ty)] horizontal runs of stamped tiles (fewer canvas
    items than one per tile)."""
    rows = {}
    for tx, ty in cells:
        rows.setdefault(ty, []).append(tx)
    out = []
    for ty, xs in rows.items():
        xs.sort()
        a = b = xs[0]
        for x in xs[1:]:
            if x == b + 1:
                b = x
                continue
            out.append((a, b, ty))
            a = b = x
        out.append((a, b, ty))
    return out


def _sprite_rect(o, src, cp):
    """Canvas rectangle a sprite covers (src = Sprites.source(o))."""
    x0, y0, x1, y1 = (v * cp / 8 for v in spritequad.world_rect(o, src[2]))
    return int(x0), int(y0), int(x1), int(y1)


LABEL_HALO = "#000"     # the outline drawn around every name label's letters


def label_size(cp):
    """Name-label font size (pt) for a zoom of `cp` px per tile: 7 pt while zoomed out (up to
    about 6 px, where small text is fine), growing steadily to 10 pt at 16 px so labels are
    readable there, then more slowly, up to 13 pt."""
    if cp <= 6:
        return 7
    if cp <= 16:
        return round(7 + (cp - 6) * 0.3)
    return min(13, round(10 + (cp - 16) / 4))


def label(x, y, below, text, fill, size, key=None):
    """A name label centred above (x, y): outlined in LABEL_HALO so it reads on any ground,
    and moved to `below` (the point under its object) by the renderer when there is no room
    above the map's top edge."""
    return Prim("text", (x, y), key=key, text=text, fill=fill, size=size, anchor="s",
                halo=LABEL_HALO, below=below)


def gate_on_map(doc, x, y):
    """True when a gate position (sub-units) lies on the map. Encounter_TickMonsterSpawnSlots
    picks one of a gate's positions at random and spawns the Gate actor there with no tile
    check -- gates on non-walkable tiles show in the game (the shipped maps hold 100+) --
    so the one the game can never show is one off the map."""
    W, H = doc.grid[0], doc.grid[1]
    return 0 <= x >> 3 < W and 0 <= y >> 3 < H


def gate_visible(doc, users):
    """True when a gate position belongs to a VISIBLE gate: Encounter_TickMonsterSpawnSlots
    gives the spawned Gate actor state bits 0x24 and hides its scene node when the entry's
    header flag has a low byte (700 of the shipped 1224 entries -- invisible spawners: the
    monsters come, no gate is drawn or can be hit). `users` = [(pattern, entry)]."""
    pats = doc.gen.patterns
    return any(not (pats[pi][ei].hdr.flag & 0xFF) for pi, ei in users)


def gate_sprite_shown(st, doc, x, y, users):
    """Whether a gate position is drawn as the Gate actor (with a small orange "G" on top): a
    visible gate, on the map, with the sprites and "draw gates" layers on and the gate model
    at hand."""
    return (bool(st.layers.get("sprites")) and st.layers.get("gate_art", True) and HAS_PIL
            and gate_on_map(doc, x, y)
            and gate_visible(doc, users)
            and getattr(st, "sprites", None) is not None and st.sprites.gate_source() is not None)


def gate_paths(doc, cp):
    """The routes of the gates that move (gen.gate_motion), under their markers: a gliding
    gate's loop through its positions in list order (dashed, arrows show the direction), a
    teleporting gate's jumps between every two of its positions (dotted). One set of lines
    per position table (the Rune Prana gates of one room share theirs)."""
    out, done = [], set()
    c = lambda x, y: ((x >> 3) * cp + cp // 2, (y >> 3) * cp + cp // 2)
    for _pi, _ei, e in doc.gen.all_entries():
        how = gen.gate_motion(e)
        pts = [c(x, y) for x, y in e.gate_pos.points]
        for kind in sorted(how):
            key = (id(e.gate_pos), kind)
            if key in done:
                continue
            done.add(key)
            if kind == "glide":
                legs = list(zip(pts, pts[1:] + pts[:1])) if len(pts) > 2 else [(pts[0], pts[1])]
                for a, b in legs:
                    if a != b:
                        out.append(Prim("line", (*a, *b), fill=GATE_COLOR, width=2, dash=(6, 4),
                                        arrow="last" if len(pts) > 2 else "both"))
            else:
                seen = set()
                for i, a in enumerate(pts):
                    for b in pts[i + 1:]:
                        if a != b and (a, b) not in seen:
                            seen.add((a, b))
                            out.append(Prim("line", (*a, *b), fill=GATE_COLOR, width=1, dash=(2, 4)))
    return out


def overlay(group, st):
    """Primitives of one overlay group. `st` is the view state: doc, cp, layers (dict of
    bool), sel (selection key or None), active_gate (Entry | None), spawns, sprites."""
    doc, cp, L = st.doc, st.cp, st.layers
    if doc is None or doc.grid is None:
        return []
    W, H, _ = doc.grid
    if getattr(st, "sprites", None) is not None:
        st.sprites.cell = doc.cell         # sprites that depend on the ground (the fish)
    out = []
    small = max(7, cp // 3)                # text inside a marker (spot number, gate "G")
    lsize = label_size(cp)                 # name labels above objects / NPCs
    if group == "grid":
        if L.get("grid") and cp >= 4:
            for x in range(W + 1):
                out.append(Prim("line", (x * cp, 0, x * cp, H * cp), fill="#2a2a30"))
            for y in range(H + 1):
                out.append(Prim("line", (0, y * cp, W * cp, y * cp), fill="#2a2a30"))
    elif group == "stamp":
        # the collision the interactive objects stamp into ATTR when the room loads (not in
        # the file): a hatched fill per tile, outlined, for the flag snapshot shown
        if L.get("stamps", True):
            # coloured by what the stamp does to the player's walking there: magenta = the
            # object blocks it (tree trunks, rocks, the invisible wall), green = the object
            # opens it (the gangway lays a path over walls), grey = marked only, walking
            # unchanged (a tree's canopy ring: the 0x8000000 footprint marker)
            player = attrs.ACTOR_MASKS[0][1]
            colour = {"blocks": STAMP_COLOR, "opens": STAMP_WALK_COLOR, "marks": STAMP_MARK_COLOR}
            for _i, mode, cells in object_stamps(doc, getattr(st, "flags", None)):
                parts = {"blocks": {}, "opens": {}, "marks": {}}
                for t, bits in cells.items():
                    parts[collisionstamp.effect(doc.cell(*t), mode, bits, player)][t] = bits
                for part, col in ((parts[k], colour[k]) for k in ("marks", "blocks", "opens")):
                    for x0, x1, ty in stamp_runs(part) if part else ():
                        out.append(Prim("rect", (x0 * cp, ty * cp, (x1 + 1) * cp, (ty + 1) * cp),
                                        fill=col, stipple="gray25", outline=col,
                                        width=1 if cp >= 6 else 0))
    elif group == "warp":
        if L.get("mapj"):
            # the game's own runtime warps / walls first (dashed, no key: never selected)
            for (x0, y0, x1, y1), s, _tip in runtime_spawns(doc):
                warp = s["kind"] == "warp"
                out.append(Prim("rect", (x0 * cp, y0 * cp, x1 * cp, y1 * cp),
                                outline=WARP_COLOR if warp else RUNTIME_WALL_COLOR, width=2,
                                dash=(6, 4) if warp else (2, 3)))
            for j, rec in enumerate(doc.map.mapj_records()):
                out.append(Prim("rect", warp_rect_px(rec, cp), key=("warp", j),
                                outline=WARP_COLOR, width=2))
    elif group == "under":
        if L.get("sprites") and HAS_PIL:
            flags = getattr(st, "flags", None)
            for i in sorted(range(len(doc.objs)), key=lambda k: Sprites.z_key(doc.objs[k])):
                o = doc.objs[i]         # the game's depth order: larger z drawn later
                if not entity_visible(o, L) or flagstate.hidden(o, flags):
                    continue
                src = st.sprites.source(o)
                if src is not None:
                    out.append(Prim("sprite", _sprite_rect(o, src, cp), key=("mobj", i), fn=src[0],
                                    frame=src[1], mirror=spritequad.mirrored(o)))
            # the monster gates (Gen*.bin gate positions) the game can show, as it draws the
            # Gate actor, under a smaller "G" marker (see gate_sprite_shown)
            if L.get("gates") and doc.gen is not None:
                gsrc = st.sprites.gate_source()
                for kind, off, x, y, users in doc.gate_points():
                    if kind == "gpos" and gsrc is not None and gate_sprite_shown(st, doc, x, y, users):
                        o = {"type_id": 0, "pos_x": x, "pos_y": y, "params": ()}
                        out.append(Prim("sprite", _sprite_rect(o, gsrc, cp), key=("gpos", off),
                                        fn=gsrc[0], frame=0, mirror=False))
    elif group == "ent":
        r = max(3, cp // 2 + 1)
        sprites_on = L.get("sprites") and HAS_PIL
        labels_on = L.get("labels")
        flags = getattr(st, "flags", None)
        for i, o in enumerate(doc.objs):
            if not entity_visible(o, L):
                continue
            cx, cy = (o["pos_x"] >> 3) * cp, (o["pos_y"] >> 3) * cp
            tid = o["type_id"] & 0xFFFF
            gone = flagstate.hidden_reason(o, flags)
            src = st.sprites.source(o) if sprites_on else None
            if src is not None:             # the sprite itself is in the "under" group
                rect = _sprite_rect(o, src, cp)
                if gone:
                    out.append(Prim("rect", rect, key=("mobj", i), outline="#9a9aa8", width=1,
                                    dash=(4, 3)))
                elif L.get("sprite_borders", True):   # the sprite's extent (also for invisible walls)
                    out.append(Prim("rect", rect, key=("mobj", i), outline=BORDER_COLOR, width=1))
                if labels_on:
                    nm = mobj_types.mobj_display_name(tid) or o["category"]
                    mx = (rect[0] + rect[2]) // 2
                    out.append(label(mx, rect[1] - 1, (mx, rect[3] + 1),
                                     nm + (f" ({gone})" if gone else ""), "#ffe000", lsize))
                continue
            if gone:
                out.append(Prim("oval", (cx - r, cy - r, cx + r, cy + r), key=("mobj", i),
                                outline="#9a9aa8", width=1, dash=(2, 2)))
            else:
                out.append(Prim("oval", (cx - r, cy - r, cx + r, cy + r), key=("mobj", i),
                                fill=attrs.CAT_COLOR.get(o["category"], "#fff"), outline="#000"))
            if labels_on:
                nm = mobj_types.mobj_display_name(tid) or o["category"]
                out.append(label(cx, cy - r - 1, (cx, cy + r + 1),
                                 nm + (f" ({gone})" if gone else ""), "#ffe000", lsize))
    elif group == "si":
        if L.get("si") and doc.si is not None:
            sr = max(5, cp // 2 + 3)
            for i, sp in enumerate(doc.si.spots):
                cx, cy = sp.tile_x * cp + cp // 2, sp.tile_y * cp + cp // 2
                out.append(Prim("oval", (cx - sr - 1, cy - sr - 1, cx + sr + 1, cy + sr + 1),
                                outline="#ffffff", width=2))
                out.append(Prim("oval", (cx - sr, cy - sr, cx + sr, cy + sr), key=("si", i),
                                fill=SI_COLOR, outline="#a06000", width=2))
                out.append(Prim("text", (cx, cy), key=("si", i), text=str(i), fill="#000",
                                size=small, anchor="center"))
    elif group == "gate":
        if L.get("gates") and doc.gen is not None:
            gr = max(6, cp // 2 + 2)
            active = st.active_gate
            out += gate_paths(doc, cp)
            for kind, off, x, y, users in doc.gate_points():
                tx, ty = x >> 3, y >> 3
                if not (0 <= tx < W and 0 <= ty < H):
                    continue
                cx, cy = tx * cp + cp // 2, ty * cp + cp // 2
                # the active gate's points, outlined white while it is being worked on
                mine = (active is not None and getattr(st, "gate_focus", False)
                        and any(doc.gen.patterns[pi][ei] is active for pi, ei in users))
                if kind == "mpos":
                    rr = 5 if mine else 4
                    out.append(Prim("oval", (cx - rr, cy - rr, cx + rr, cy + rr), key=(kind, off),
                                    fill=MPOS_COLOR, outline="#fff" if mine else "#000",
                                    width=2 if mine else 1))
                else:
                    # orange G = a visible gate, gray G = an invisible spawner (no gate is drawn
                    # or can be hit); over the drawn gate the G is smaller so the orb shows
                    seen = gate_visible(doc, users)
                    g = max(5, gr * 2 // 3) if gate_sprite_shown(st, doc, x, y, users) else gr
                    out.append(Prim("poly", (cx, cy - g, cx + g, cy, cx, cy + g, cx - g, cy),
                                    key=(kind, off), fill=GATE_COLOR if seen else GATE_HIDDEN_COLOR,
                                    outline="#fff" if mine else "#000", width=2))
                    out.append(Prim("text", (cx, cy), key=(kind, off), text="G", fill="#000",
                                    size=small, anchor="center", bold=True))
    elif group == "region":
        # the player areas the map's event script watches: outline only, so the objects
        # inside stay clickable; the label names the em.bin condition
        if L.get("regions"):
            for i, rg in enumerate(getattr(st, "regions", None) or ()):
                x0, y0 = (rg["x0"] >> 3) * cp, (rg["y0"] >> 3) * cp
                x1, y1 = ((rg["x1"] >> 3) + 1) * cp, ((rg["y1"] >> 3) + 1) * cp
                out.append(Prim("rect", (x0, y0, x1, y1), key=("region", i), outline=REGION_COLOR,
                                width=2, dash=(8, 4)))
                out.append(label((x0 + x1) // 2, y0 - 2, ((x0 + x1) // 2, y1 + 2),
                                 rg.get("label") or rg["cond_name"] or "script area", REGION_COLOR, lsize,
                                 key=("region", i)))
    elif group == "spawn":
        if L.get("spawns"):
            sr = max(4, cp // 2)
            for i, sp in enumerate(st.spawns or ()):
                cx, cy = (sp["x"] >> 3) * cp + cp // 2, (sp["y"] >> 3) * cp + cp // 2
                shape = "rect" if sp.get("kind") == "entity" else "oval"   # object / actor
                out.append(Prim(shape, (cx - sr, cy - sr, cx + sr, cy + sr), key=("spawn", i),
                                fill=SPAWN_COLOR, outline="#2a0640"))
                out.append(label(cx, cy - sr - 1, (cx, cy + sr + 1), sp["name"], "#e6b3ff", lsize,
                                 key=("spawn", i)))
    elif group == "dest":
        if L.get("dest"):
            for rec in doc.map.mapj_records():
                name, _bld = map_names.describe_destination(rec[5])
                if not name:
                    continue
                x0, y0, x1, y1 = warp_rect_px(rec, cp)
                out.append(label((x0 + x1) // 2, y0 - 2, ((x0 + x1) // 2, y1 + 2), name, WARP_COLOR,
                                 label_size(cp) + 1))
    elif group == "sel":
        out += _selection(st)
    return out


def _selection(st):
    """The selection frame of every selected object (a multi-selection: all of them; the
    resize handles only for a lone selected warp)."""
    multi = getattr(st, "multi", ()) or ()
    if len(multi) > 1:
        out = []
        for key in multi:
            out += _selection_one(st, tuple(key), handles=False)
        return out
    return _selection_one(st, st.sel, handles=True)


def _selection_one(st, sel, handles=True):
    doc, cp = st.doc, st.cp
    if sel is None:
        return []
    kind, k = sel
    out = []
    if kind == "mobj" and k < len(doc.objs):
        o = doc.objs[k]
        src = (st.sprites.source(o) if st.layers.get("sprites") and HAS_PIL
               and entity_visible(o, st.layers) else None)
        if src is not None:                 # a frame around the sprite
            x0, y0, x1, y1 = _sprite_rect(o, src, cp)
            out.append(Prim("rect", (x0 - 3, y0 - 3, x1 + 3, y1 + 3), outline="#002b33", width=1))
            out.append(Prim("rect", (x0 - 1, y0 - 1, x1 + 1, y1 + 1), outline=SEL_COLOR, width=3))
        elif o["category"] != "mapparam":
            cx, cy = (o["pos_x"] >> 3) * cp, (o["pos_y"] >> 3) * cp
            rr = max(6, cp // 2 + 4)
            out.append(Prim("oval", (cx - rr, cy - rr, cx + rr, cy + rr), outline=SEL_COLOR, width=3))
    elif kind == "warp":
        recs = doc.map.mapj_records()
        if k < len(recs):
            rect = warp_rect_px(recs[k], cp)
            out.append(Prim("rect", rect, outline=SEL_COLOR, width=3))
            hs = max(3, cp // 2)
            for mode, (hx, hy) in (handle_points(rect).items() if handles else ()):
                out.append(Prim("rect", (hx - hs, hy - hs, hx + hs, hy + hs), key=("handle", mode),
                                fill=SEL_COLOR, outline="#002b33"))
    elif kind == "si" and doc.si is not None and k < len(doc.si.spots):
        sp = doc.si.spots[k]
        sr = max(5, cp // 2 + 3) + 5
        cx, cy = sp.tile_x * cp + cp // 2, sp.tile_y * cp + cp // 2
        out.append(Prim("oval", (cx - sr, cy - sr, cx + sr, cy + sr), outline=SEL_COLOR, width=3))
    elif kind in ("gpos", "mpos"):
        for pk, off, x, y, users in doc.gate_points():
            if (pk, off) == sel:
                if pk == "gpos" and gate_sprite_shown(st, doc, x, y, users):   # round the gate
                    o = {"type_id": 0, "pos_x": x, "pos_y": y, "params": ()}
                    out.append(Prim("oval", _sprite_rect(o, st.sprites.gate_source(), cp),
                                    outline=SEL_COLOR, width=3))
                    continue
                gr = max(6, cp // 2 + 2) + 5
                cx, cy = (x >> 3) * cp + cp // 2, (y >> 3) * cp + cp // 2
                out.append(Prim("oval", (cx - gr, cy - gr, cx + gr, cy + gr), outline=SEL_COLOR, width=3))
    return out


# --------------------------------------------------------------------------- #
# PNG export
# --------------------------------------------------------------------------- #
_FONTS = {}


def _font(size, bold=False):
    key = (size, bold)
    if key not in _FONTS:
        f = None
        for name in (("segoeuib.ttf",) if bold else ()) + ("segoeui.ttf", "DejaVuSans.ttf"):
            try:
                f = ImageFont.truetype(name, size)
                break
            except Exception:
                continue
        if f is None:
            try:
                f = ImageFont.load_default(size)
            except Exception:
                f = ImageFont.load_default()
        _FONTS[key] = f
    return _FONTS[key]


def _rgb(spec):
    s = spec.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return tuple(int(s[k:k + 2], 16) for k in (0, 2, 4))


_PIL_ANCHOR = {"center": "mm", "s": "ms", "n": "mt", "w": "lm", "e": "rm"}


def _place_label(dr, xy, o, font, anchor, size, stroke):
    """((x, y), anchor) for a label in a W x H image: under its object (o['below']) when it
    would stick out above the top edge, and shifted in from the left / right edges."""
    sw = stroke.get("stroke_width", 0)               # textbbox takes the width, not the colour
    x0, y0, x1, _y1 = dr.textbbox(xy, o["text"], font=font, anchor=anchor, stroke_width=sw)
    if y0 < 0 and o.get("below"):
        xy, anchor = o["below"], {"ms": "mt"}.get(anchor, anchor)
        x0, y0, x1, _y1 = dr.textbbox(xy, o["text"], font=font, anchor=anchor, stroke_width=sw)
    dx = -x0 if x0 < 0 else (size[0] - x1 if x1 > size[0] else 0)
    if dx and x1 - x0 <= size[0]:
        xy = (xy[0] + dx, xy[1])
    return xy, anchor


def draw_prims(img, prims, sprites=None):
    """Draw overlay primitives onto a PIL RGBA image (the export twin of the canvas)."""
    dr = ImageDraw.Draw(img)
    for p in prims:
        o = p.opt
        fill = _rgb(o["fill"]) if o.get("fill") else None
        outline = _rgb(o["outline"]) if o.get("outline") else None
        wd = o.get("width", 1)
        if p.kind == "line":
            dr.line(p.xy, fill=fill, width=wd)
        elif p.kind == "rect" and o.get("stipple"):
            # a hatched canvas fill: a see-through fill here, then the outline
            layer = Image.new("RGBA", img.size)
            ImageDraw.Draw(layer).rectangle(p.xy, fill=fill + (80,))
            img.alpha_composite(layer)
            dr = ImageDraw.Draw(img)
            if wd:
                dr.rectangle(p.xy, outline=outline, width=wd)
        elif p.kind == "rect":
            dr.rectangle(p.xy, fill=fill, outline=outline, width=wd)
        elif p.kind == "oval":
            dr.ellipse(p.xy, fill=fill, outline=outline, width=wd)
        elif p.kind == "poly":
            pts = list(zip(p.xy[0::2], p.xy[1::2]))
            dr.polygon(pts, fill=fill, outline=outline)
        elif p.kind == "text":
            font = _font(int(o.get("size", 8) * 4 / 3), o.get("bold", False))
            anchor = _PIL_ANCHOR.get(o.get("anchor", "center"), "mm")
            halo = o.get("halo")
            stroke = {"stroke_width": 1, "stroke_fill": _rgb(halo)} if halo else {}
            try:
                xy, anchor = _place_label(dr, p.xy, o, font, anchor, img.size, stroke)
                dr.text(xy, o["text"], fill=fill, font=font, anchor=anchor, **stroke)
            except (TypeError, ValueError):       # bitmap font: no anchor / stroke support
                dr.text(p.xy, o["text"], fill=fill, font=font)
        elif p.kind == "sprite" and sprites is not None:
            x0, y0, x1, y1 = p.xy
            sp = sprites.pil(o["fn"], o["frame"], x1 - x0, y1 - y0, o["mirror"])
            if sp is not None:
                layer = Image.new("RGBA", img.size)
                layer.paste(sp, (x0, y0))       # paste clips a sprite hanging off the map
                img.alpha_composite(layer)
                dr = ImageDraw.Draw(img)
    return img
