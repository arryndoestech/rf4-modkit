r"""
matedit.py -- the material settings of an RF4S `.model` the game actually reads, edited in place.

Read from RF4S.exe 2026-09-27 (IDA, read-only; the file side on all 2,557 materials of the 912
mesh .model files):

  Texture wrap. Every shipped material has exactly one sampler (MATL+0xA8 = 1). The material
  setup (RF4S.exe+0x3E0560) initialises sampler i (6 bytes at MATL+0x40 -> [6 i]) from the 4
  bytes at MATL+0x48 -> [4 i] (+0x3CA860: byte 0 = 1, bytes 2..5 = those 4 bytes), and the
  texture bind (Renderer_BindTextureSlotWithReplacement, +0x3C3B00) takes the sampler's bytes 2
  and 3 -- the file's bytes 0 and 1 -- as the S and T wrap modes (through the identity table at
  +0x4A7168 into the texture object, whose GL upload at +0x2A32A0 maps them with the table at
  +0x551238): 0 GL_REPEAT, 1 GL_MIRRORED_REPEAT, 2 GL_CLAMP_TO_EDGE, 3 GL_CLAMP_TO_BORDER,
  4 GL_MIRROR_CLAMP_TO_EDGE (nn::gfx TextureAddressMode order). Shipped: clamp/clamp 1,469,
  repeat/repeat 1,006, mirror/mirror 54, mirror/repeat 20, clamp/repeat 7. The filter is not
  taken from the file (the texture object picks linear / mipmapped itself).

  User data (GfxCTR_Model_BuildFromResource, +0x1B52C0; each only when the entry is an int --
  type byte 0 -- except CombineColor00, a float3):
    DrawOrder   0..3 (else 0): the draw pass bucket; Scene_SubmitDrawList (+0x1B9430) draws
                bucket 0, 1, 2, 3 in that order.
    BlendType   0..4 (else 0): the blend state (see model.py: 0 off, 1 alpha, 2 additive
                SrcAlpha/One, 3 One/One, 4 One/Zero).
    CombineType 0..4 (else 0): Scene_BuildAxisVec4FromMode (+0x1C08C0) turns it into the
                shader's CombineColor = (x, y, 0, w): 0 -> (1,0,0, scene flag), 1 -> (1,0,0,1),
                2 and 3 -> (0,1,0,0), else (1,0,0,0). rf4lib.glsl.inc (bundleMuteki) then draws
                pixel = albedo * (diffuse + emission) * x + (diffuse + emission) * y, and lights
                the diffuse by w. So 0 / 1 / 4 = the texture (1 lit), 2 / 3 = a flat colour
                (the texture only supplies alpha).
    CombineColor00  3 floats: the diffuse colour of that flat colour (colorDiffuseCPP).
  Only 339 materials carry these entries (322 without CombineColor00); the rest have none or
  only the map over-models' `po`. Adding an entry means growing the material block, which this
  module does not do: a setting the material lacks is reported, not added.

Statically verified only (no in-game test).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import model as _model


class MatEditError(Exception):
    pass


WRAP_MODES = ("repeat", "mirror", "clamp", "border", "mirror-clamp")
USER_INTS = {"DrawOrder": 3, "BlendType": 4, "CombineType": 4}      # name -> largest value kept


def _u16(d, o):
    return struct.unpack_from("<H", d, o)[0]


def _u64(d, o):
    return struct.unpack_from("<Q", d, o)[0]


def _name(d, off):
    return d[off + 2:off + 2 + _u16(d, off)].decode("utf-8", "replace") if 0 < off < len(d) - 2 else ""


@dataclass
class MaterialSettings:
    index: int
    name: str
    texture: str
    wrap: tuple                 # (u, v) as 0..4, None when the material has no sampler
    user: dict = field(default_factory=dict)      # DrawOrder / BlendType / CombineType / CombineColor00
    wrap_at: int | None = None                    # file offset of the 4 sampler bytes
    user_at: dict = field(default_factory=dict)   # name -> (file offset of the values, type, count)

    def text(self):
        w = (f"wrap {WRAP_MODES[self.wrap[0]] if self.wrap[0] < 5 else self.wrap[0]}/"
             f"{WRAP_MODES[self.wrap[1]] if self.wrap[1] < 5 else self.wrap[1]}") if self.wrap else "no sampler"
        u = ", ".join(f"{k}={v}" for k, v in self.user.items())
        return f"{self.index:3} {self.name:<24} {self.texture or '(no texture)':<24} {w}" + (f"  {u}" if u else "")


def materials(data):
    """[MaterialSettings] of every material of a mesh .model."""
    if not _model.is_mesh(data):
        raise MatEditError("not a mesh .model")
    M = _u64(data, 0x28)
    out = []
    for i in range(_u16(data, M + 0x6C)):
        mt = _u64(data, M + 0x40) + 0xB8 * i
        if data[mt:mt + 4] != b"MATL":
            raise MatEditError(f"material {i}: no MATL block")
        tex = _name(data, _u64(data, _u64(data, mt + 0x38))) if data[mt + 0xA8] and _u64(data, mt + 0x38) else ""
        wrap = wrap_at = None
        if data[mt + 0xA8] and _u64(data, mt + 0x48):
            wrap_at = _u64(data, mt + 0x48)
            wrap = (data[wrap_at], data[wrap_at + 1])
        s = MaterialSettings(i, _name(data, _u64(data, mt + 0x10)), tex, wrap, wrap_at=wrap_at)
        for k in range(_u16(data, mt + 0xB2)):
            e = _u64(data, mt + 0x70) + 0x40 * k
            nm = _name(data, _u64(data, e))
            cnt, typ, p = struct.unpack_from("<I", data, e + 0x10)[0], data[e + 0x14], _u64(data, e + 8)
            if nm in USER_INTS and typ == 0 and cnt >= 1:
                s.user[nm] = struct.unpack_from("<i", data, p)[0]
                s.user_at[nm] = (p, typ, cnt)
            elif nm == "CombineColor00" and typ == 1 and cnt >= 3:
                s.user[nm] = tuple(round(v, 6) for v in struct.unpack_from("<3f", data, p))
                s.user_at[nm] = (p, typ, cnt)
        out.append(s)
    return out


def resolve_material(data, material):
    mats = materials(data)
    if isinstance(material, int) or (isinstance(material, str) and material.isdigit()):
        i = int(material)
        if not 0 <= i < len(mats):
            raise MatEditError(f"material index {i} out of range (model has {len(mats)})")
        return mats[i]
    hits = [m for m in mats if m.name == material]
    if not hits:
        raise MatEditError(f"no material named {material!r} (has: {[m.name for m in mats]})")
    return hits[0]


def _wrap_value(v):
    if isinstance(v, int):
        if not 0 <= v <= 4:
            raise MatEditError(f"wrap mode {v} is not 0..4")
        return v
    if v not in WRAP_MODES:
        raise MatEditError(f"wrap mode {v!r} is not one of {', '.join(WRAP_MODES)}")
    return WRAP_MODES.index(v)


def set_material(data, material, *, wrap_u=None, wrap_v=None, draw_order=None, blend=None,
                 combine=None, combine_color=None):
    """New file bytes with one material's settings changed IN PLACE (same size). `material` =
    index or name; wrap modes as 0..4 or a WRAP_MODES name. A user-data setting the material
    does not carry raises MatEditError (it cannot be added in place)."""
    s = resolve_material(data, material)
    others = {o for m in materials(data) if m.index != s.index
              for o in [m.wrap_at] + [v[0] for v in m.user_at.values()] if o is not None}
    if s.wrap_at in others or any(v[0] in others for v in s.user_at.values()):
        raise MatEditError(f"material {s.name} shares its settings data with another material "
                           f"(never in the shipped files); editing it would change both")
    out = bytearray(data)
    if wrap_u is not None or wrap_v is not None:
        if s.wrap_at is None:
            raise MatEditError(f"material {s.name}: no sampler")
        if wrap_u is not None:
            out[s.wrap_at] = _wrap_value(wrap_u)
        if wrap_v is not None:
            out[s.wrap_at + 1] = _wrap_value(wrap_v)
    for key, val in (("DrawOrder", draw_order), ("BlendType", blend), ("CombineType", combine)):
        if val is None:
            continue
        if key not in s.user_at:
            raise MatEditError(f"material {s.name} has no {key} entry (only materials that carry one "
                               f"can be changed; adding one would grow the file)")
        if not 0 <= int(val) <= USER_INTS[key]:
            raise MatEditError(f"{key} must be 0..{USER_INTS[key]} (the game reads anything else as 0)")
        struct.pack_into("<i", out, s.user_at[key][0], int(val))
    if combine_color is not None:
        if "CombineColor00" not in s.user_at:
            raise MatEditError(f"material {s.name} has no CombineColor00 entry")
        c = tuple(float(x) for x in combine_color)
        if len(c) != 3:
            raise MatEditError("CombineColor00 takes 3 numbers (r, g, b; 0..1)")
        struct.pack_into("<3f", out, s.user_at["CombineColor00"][0], *c)
    return bytes(out)
