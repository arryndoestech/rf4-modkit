"""Rendering: the ground texture (decoded off the UI thread), the ATTR fill, and the
overlay primitives shared by the canvas and the PNG export.

The overlays are produced once as plain primitives (`Prim`) per group; `view.MapView`
turns them into canvas items and `render_image()` draws the very same list with PIL, so
an exported PNG is exactly what the canvas shows (minus the selection)."""
from __future__ import annotations

import queue
import threading
from collections import OrderedDict

from rf4s_modkit import (flagstate, map_names, mapground, mobj_meshes, mobj_types, model,
                         spritequad, texture)

from . import attrs, ui

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:           # the editor still runs, with a plain-rectangle ATTR view
    HAS_PIL = False

# Overlay groups, bottom to top.
GROUPS = ("under", "lift", "grid", "warp", "ent", "si", "gate", "spawn", "dest", "sel")
# canvas stacking, bottom to top: the ground texture ("bg"), the sprites ("under",
# drawn as the game draws them, so they sit on the ground), the ATTR fill + cell edges
# ("attr"), the selected object's sprite again ("lift", so it shines through the fill), then
# every other overlay group
STACK = ("bg", "under", "attr", "lift") + tuple(g for g in GROUPS if g not in ("under", "lift"))

SEL_COLOR = "#00e5ff"
WARP_COLOR = "#ffd040"
BORDER_COLOR = "#ff3030"        # the outline of every sprite ("sprite borders")
SI_COLOR = "#ffe000"
GATE_COLOR = "#ff8c1a"
MPOS_COLOR = "#ff5aa0"
SPAWN_COLOR = "#c060ff"
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
        key = (base, sel, scenery)
        if key not in self.cache:
            self.put(key, self.decode(self.reader, base, sel, w, h, scenery))
        return self.get(key)

    def request(self, base, sel, w, h, scenery=False):
        key = (base, sel, scenery)
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
            self._res.put(((base, sel, scenery), img, gen))

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
               under=False):
        """(ground, attr): the scaled ground texture and the ATTR fill + cell edges as a
        separate RGBA layer (either may be None), so the sprites can be drawn
        between them. The fill takes the ATTR opacity when anything lies beneath it (the
        ground, or sprites when `under`); otherwise it is opaque. Callers must not draw on
        the images."""
        if not HAS_PIL or grid is None:
            return None, None
        below = ground is not None or under
        key = (attr_version, len(colors), cp, id(ground), attr_on, alpha if below else 255,
               edges_on, below)
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
    w, h = img.size
    whole = Image.new("RGBA", (w * 2, h * 2))
    whole.paste(img, (0, 0))
    whole.paste(img.transpose(Image.FLIP_LEFT_RIGHT), (w, 0))
    whole.paste(img.transpose(Image.FLIP_TOP_BOTTOM), (0, h))
    whole.paste(img.transpose(Image.ROTATE_180), (w, h))
    return whole, tuple(v * 2 for v in quad)


def _whole_frame(data, frame):
    """A texture without sprite placement data (propeller_ship_02): the whole frame,
    centred on the object at its own size."""
    img = texture.decode_to_image(data, frame=frame)
    if img is None:
        return None
    w, h = img.size
    return img.convert("RGBA"), (-w / 2, -h / 2, w / 2, h / 2)


class Sprites:
    """A placed object's sprite as the game draws it: the texture's TextureCoordinator
    crop, sized and offset by its PolygonVertexes quad (rf4s_modkit.spritequad)."""

    def __init__(self):
        self.reader = None
        self._src = {}                     # (texture name, frame) -> (RGBA, quad) | None
        self._scaled = OrderedDict()

    def reset(self):
        self._src.clear()
        self._scaled.clear()

    def source(self, o):
        """(texture name, frame, quad) for a decoded MOBJ entry, or None."""
        r = self.reader
        p = o.get("params", ())
        name = mobj_types.mobj_texture(p) if p else o.get("name")
        if r is None or not name:
            return None
        fn = name + ".texture"
        frame = p[7] if len(p) > 7 and p[7] > 0 else 0
        tid = p[0] & 0xFFFF if p else 0
        tint = mobj_types.mobj_tint(tid) if p else None
        glow = bool(p) and mobj_types.mobj_glow(p)
        mesh = mobj_meshes.mesh_for(p) if tid in (70, 72) else None
        if tint or glow:
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
                        got = mobj_meshes.rasterize(texture.decode_to_image(data, rotate=False),
                                                    mesh[1], mesh[2])
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
                except Exception:
                    got = None
            self._src[key] = got
        got = self._src[key]
        return (fn, key[1], got[1]) if got else None

    @staticmethod
    def z_key(o):
        """Draw order: the room mesh (72) under everything, the light shafts (70) over it,
        then the sprites in the game's depth order."""
        tid = o["type_id"] & 0xFFFF
        return (0 if tid == 72 else 1 if tid == 70 else 2, spritequad.z_key(o))

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


def handle_points(rect):
    x0, y0, x1, y1 = rect
    mx, my = (x0 + x1) // 2, (y0 + y1) // 2
    return {"nw": (x0, y0), "n": (mx, y0), "ne": (x1, y0), "w": (x0, my), "e": (x1, my),
            "sw": (x0, y1), "s": (mx, y1), "se": (x1, y1)}


def entity_visible(o, layers):
    cat = o["category"]
    key = "trigger" if cat in attrs.TRIGGER_KINDS else cat
    return layers.get(key, True) and not (o["pos_x"] == 0 and o["pos_y"] == 0) and cat != "mapparam"


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


def overlay(group, st):
    """Primitives of one overlay group. `st` is the view state: doc, cp, layers (dict of
    bool), sel (selection key or None), active_gate (Entry | None), spawns, sprites."""
    doc, cp, L = st.doc, st.cp, st.layers
    if doc is None or doc.grid is None:
        return []
    W, H, _ = doc.grid
    out = []
    small = max(7, cp // 3)                # text inside a marker (spot number, gate "G")
    lsize = label_size(cp)                 # name labels above objects / NPCs
    if group == "grid":
        if L.get("grid") and cp >= 4:
            for x in range(W + 1):
                out.append(Prim("line", (x * cp, 0, x * cp, H * cp), fill="#2a2a30"))
            for y in range(H + 1):
                out.append(Prim("line", (0, y * cp, W * cp, y * cp), fill="#2a2a30"))
    elif group == "warp":
        if L.get("mapj"):
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
    elif group == "lift":
        # the selected object's sprite once more, above the ATTR fill (no key: the copy in
        # "under" stays the hit, so the pick order does not change)
        sel = st.sel
        if (sel is not None and sel[0] == "mobj" and sel[1] < len(doc.objs) and L.get("sprites")
                and HAS_PIL):
            o = doc.objs[sel[1]]
            if entity_visible(o, L) and not flagstate.hidden(o, getattr(st, "flags", None)):
                src = st.sprites.source(o)
                if src is not None:
                    out.append(Prim("sprite", _sprite_rect(o, src, cp), fn=src[0], frame=src[1],
                                    mirror=spritequad.mirrored(o)))
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
            gone = flagstate.hidden(o, flags)
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
                                     nm + (" (hidden by flag)" if gone else ""), "#ffe000", lsize))
                continue
            if gone:
                out.append(Prim("oval", (cx - r, cy - r, cx + r, cy + r), key=("mobj", i),
                                outline="#9a9aa8", width=1, dash=(2, 2)))
            else:
                out.append(Prim("oval", (cx - r, cy - r, cx + r, cy + r), key=("mobj", i),
                                fill=attrs.CAT_COLOR.get(o["category"], "#fff"), outline="#000"))
            if labels_on:
                nm = mobj_types.mobj_display_name(tid) or o["category"]
                out.append(label(cx, cy - r - 1, (cx, cy + r + 1), nm, "#ffe000", lsize))
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
            for kind, off, x, y, users in doc.gate_points():
                tx, ty = x >> 3, y >> 3
                if not (0 <= tx < W and 0 <= ty < H):
                    continue
                cx, cy = tx * cp + cp // 2, ty * cp + cp // 2
                mine = active is not None and any(doc.gen.patterns[pi][ei] is active
                                                  for pi, ei in users)
                if kind == "mpos":
                    rr = 5 if mine else 4
                    out.append(Prim("oval", (cx - rr, cy - rr, cx + rr, cy + rr), key=(kind, off),
                                    fill=MPOS_COLOR, outline="#fff" if mine else "#000",
                                    width=2 if mine else 1))
                else:
                    out.append(Prim("poly", (cx, cy - gr, cx + gr, cy, cx, cy + gr, cx - gr, cy),
                                    key=(kind, off), fill=GATE_COLOR,
                                    outline="#fff" if mine else "#000", width=2))
                    out.append(Prim("text", (cx, cy), key=(kind, off), text="G", fill="#000",
                                    size=small, anchor="center", bold=True))
    elif group == "spawn":
        if L.get("spawns"):
            sr = max(4, cp // 2)
            for i, sp in enumerate(st.spawns or ()):
                cx, cy = (sp["x"] >> 3) * cp + cp // 2, (sp["y"] >> 3) * cp + cp // 2
                out.append(Prim("oval", (cx - sr, cy - sr, cx + sr, cy + sr), key=("spawn", i),
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
    doc, cp, sel = st.doc, st.cp, st.sel
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
        elif o["pos_x"] or o["pos_y"]:
            cx, cy = (o["pos_x"] >> 3) * cp, (o["pos_y"] >> 3) * cp
            rr = max(6, cp // 2 + 4)
            out.append(Prim("oval", (cx - rr, cy - rr, cx + rr, cy + rr), outline=SEL_COLOR, width=3))
    elif kind == "warp":
        recs = doc.map.mapj_records()
        if k < len(recs):
            rect = warp_rect_px(recs[k], cp)
            out.append(Prim("rect", rect, outline=SEL_COLOR, width=3))
            hs = max(3, cp // 2)
            for mode, (hx, hy) in handle_points(rect).items():
                out.append(Prim("rect", (hx - hs, hy - hs, hx + hs, hy + hs), key=("handle", mode),
                                fill=SEL_COLOR, outline="#002b33"))
    elif kind == "si" and doc.si is not None and k < len(doc.si.spots):
        sp = doc.si.spots[k]
        sr = max(5, cp // 2 + 3) + 5
        cx, cy = sp.tile_x * cp + cp // 2, sp.tile_y * cp + cp // 2
        out.append(Prim("oval", (cx - sr, cy - sr, cx + sr, cy + sr), outline=SEL_COLOR, width=3))
    elif kind in ("gpos", "mpos"):
        for pk, off, x, y, _u in doc.gate_points():
            if (pk, off) == sel:
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
