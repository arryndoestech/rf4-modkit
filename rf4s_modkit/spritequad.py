"""
spritequad.py -- where the game draws a placed map sprite, at its true size.

Every map_obj .texture frame carries two user-data arrays (PIXL +0x78, see texture.py):

* ``TextureCoordinator`` -- 8 floats, four (u, v) corners of the part of the frame that is
  drawn (e.g. 0.25..1 x 0.25..1 when the art sits in a corner of a padded power-of-two
  sheet).
* ``PolygonVertexes`` -- 4 floats (x0, y0, x1, y1): the quad, in quad units, relative to the
  sprite's position. ``Sprite_BuildQuadVertices`` (RF4S.exe+0x1B7900) reads them as the
  corners when the sprite's data-type byte (+976) is 1, which both MapDecoration_Spawn
  (+0x142D30) and Map_SpawnInteractiveObject (+0x143760) set; neither sets the "centre" render
  flags (MCSprite_Init leaves +880 = 0x1E803), so the offsets are used as stored.

Units: the spawners scale the quad by f6/4096/3, the same /3 the ground atlas is drawn with,
so one quad unit at f6 = 4096 is one pixel of ``mapground`` output (PX_PER_ATTR_TILE = 24 px
per 8-sub-unit tile, i.e. 3 px per sub-unit). Checked on MAP_CITY_04: the Dragon Lake bridge
(quad -192..192 x -384..384 at sub (376, 250)) lands exactly on the painted cliff and the
gate door on the gateway.

Orientation: frames are stored sideways; texture.decode_to_image rotates them 90 deg CCW, so
the drawn part of the decoded image is x = (1 - v) * H and y = W - u * W. The quad's x axis
is the map's x; its y axis runs down the map (only two shipped placed textures have
off-centre quads, both at a map edge, so the y sign is not independently confirmed).
"""
from __future__ import annotations

import struct

from . import texture

PX_PER_SUBUNIT = 3          # mapground pixels per map sub-unit (24 per 8-sub-unit tile)
SCALE_ONE = 4096            # MOBJ f6 value for 1:1


def _u64(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def frame_userdata(data: bytes, frame: int = 0) -> dict:
    """{'size': (w, h) stored, name: tuple-of-values, ...} for one frame's PIXL user data.
    Float arrays (type 1) come back as floats, the rest as ints; empty dict if none."""
    info = texture.parse(data)
    frames = info["frame_list"]
    if not frames:
        return {}
    fr = frames[min(max(frame, 0), len(frames) - 1)]
    p = fr["pixl_off"]
    if p < 0 or p + 0x80 > len(data):
        return {}
    out = {"size": (fr["width"], fr["height"])}
    ud = _u64(data, p + 0x78)
    if not ud or ud + 0x18 > len(data):
        return out
    # the entries sit 0x40 apart: {u64 name -> (u16 len, chars), u64 data, u32 count, u32 type}
    off = ud
    while off + 0x18 <= len(data):
        namep, datap, cnt, typ = struct.unpack_from("<QQII", data, off)
        if not (0 < namep < len(data) - 2 and 0 < datap < len(data)) or not 0 < cnt <= 256:
            break
        n = struct.unpack_from("<H", data, namep)[0]
        name = data[namep + 2:namep + 2 + n].decode("ascii", "replace")
        if not name.isidentifier() or datap + 4 * cnt > len(data):
            break
        out[name] = struct.unpack_from("<%d%s" % (cnt, "f" if typ == 1 else "i"), data, datap)
        off += 0x40
    return out


def placement(data: bytes, frame: int = 0):
    """(crop, quad) for one frame, or None when the frame has no PolygonVertexes.
    crop = (l, t, r, b) in the DECODED (rotated) image; quad = (x0, y0, x1, y1) in quad units
    relative to the sprite position (map x right, y down)."""
    u = frame_userdata(data, frame)
    pv = u.get("PolygonVertexes")
    if not pv or len(pv) < 4:
        return None
    W, H = u["size"]
    tc = u.get("TextureCoordinator")
    if tc and len(tc) >= 8:
        us, vs = tc[0::2], tc[1::2]
        crop = (round((1 - max(vs)) * H), round(W - max(us) * W),
                round((1 - min(vs)) * H), round(W - min(us) * W))
    else:
        crop = (0, 0, H, W)
    x0, y0, x1, y1 = pv[:4]
    return crop, (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def sprite_image(data: bytes, frame: int = 0):
    """(RGBA PIL image of the drawn part, quad) or None. The image is not yet scaled to
    the quad; callers resize it to (quad width, quad height) x their own scale."""
    pl = placement(data, frame)
    if pl is None:
        return None
    crop, quad = pl
    img = texture.decode_to_image(data, frame=frame)
    if img is None:
        return None
    img = img.convert("RGBA")
    l, t, r, b = crop
    if r > l and b > t:
        img = img.crop((l, t, min(r, img.width), min(b, img.height)))
    return img, quad


def world_rect(obj: dict, quad) -> tuple:
    """Sub-unit rectangle (x0, y0, x1, y1) a placed MOBJ's sprite covers on the map.
    obj is an Rf4mMap.decode_mobj() entry (pos_x/pos_y sub-units, params[6] = f6 scale)."""
    f6 = obj["params"][6] if len(obj.get("params", ())) > 6 else SCALE_ONE
    s = abs(f6 or SCALE_ONE) / SCALE_ONE / PX_PER_SUBUNIT
    x0, y0, x1, y1 = quad
    return (obj["pos_x"] + x0 * s, obj["pos_y"] + y0 * s,
            obj["pos_x"] + x1 * s, obj["pos_y"] + y1 * s)


def mirrored(obj: dict) -> bool:
    """Negative f6 mirrors the sprite horizontally."""
    p = obj.get("params", ())
    return len(p) > 6 and p[6] < 0


def z_key(obj: dict) -> int:
    """The spawners' depth key, z = 2*(f8 + f15) + 4096 (larger = drawn later / in front)."""
    p = obj.get("params", ())
    f8 = p[8] if len(p) > 8 else 0
    return 2 * (f8 + obj["pos_y"]) + 4096
