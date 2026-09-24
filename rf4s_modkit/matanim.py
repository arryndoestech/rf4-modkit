r"""
matanim.py -- reader + evaluator for RF4S `.bfmat` material animations (FRES / FMAA).

A `.bfmat` sits next to the `.model` it animates (ANIM_DUNG_A02.bfmat -> ANIM_DUNG_A02.model)
and binds to that model's materials by name. Like `.model` blocks, the FMAA block carries a
16-byte header (magic + 12 zero bytes), so every field sits 8 bytes later than in the public
nn::g3d layout. Every offset below is an absolute file offset (pointers are file-relative).

    FMAA +0x10 name   +0x18 path   +0x30 -> material-anim array (0x40 each)
         +0x60 u32 flags (bit 2 = loop play policy, set on every scrolling layer)
         +0x64 u16 material-anim count   +0x68 u32 frame count
    material anim (0x40)  +0x00 name (the material it binds to)  +0x08 -> param-anim infos
         (0x18 each)  +0x18 -> curves (0x30 each)  +0x20 -> constants ({u32 offset, u32 value})
         +0x32 u16 param-anim count  +0x34 u16 texture-pattern count
         +0x36 u16 constant count    +0x38 u16 curve count
    param-anim info (0x18)  +0x00 name (shader parameter, e.g. 'texsrt0')  +0x08 u16 first
         curve  +0x0A u16 float curves  +0x0C u16 int curves  +0x0E u16 first constant
         +0x10 u16 constants

Curves are the nn::g3d AnimCurve, evaluated as AnimChannel_SampleAsFloat (RF4S.exe+0x3DF9F0)
does: +0 -> frames, +8 -> keys, +0x10 u16 flags (bits 0-1 frame type f32 / s16 x1/32 / u8,
bits 2-3 key type f32 / s16 / s8, bits 4-6 curve type cubic / linear / baked, bits 8-9 pre-
and 12-13 post-wrap: clamp / repeat / mirror / repeat-with-offset), +0x12 u16 key count,
+0x14 u32 byte offset into the parameter, +0x18 f32 start frame, +0x1C end frame, +0x20 f32
scale, +0x24 f32 offset, +0x28 f32 wrap delta. value = poly(t) * scale + offset, with
poly = k0 + k1 t + k2 t^2 + k3 t^3 for cubic keys (AnimCurve_SampleCubic_KeyS8, +0x3DF510)
and t = (frame - f0) / (f1 - f0) between the two keys the seek (+0x3DF2A0 for u8 frames)
lands on.

The one animated parameter in the shipped files is `texsrt0`, laid out [mode, sx, sy, rot,
tx, ty] (u32 + 5 f32). Mode 0 turns it into a 2x3 UV matrix through
TexSrt_BuildMatrix2x3_PivotA (RF4S.exe+0x3E0BA0), mode 1 through _PivotB (+0x3E0A50); see
`texsrt_matrix`. The game plays the animation at 1.0 frame per tick (Actor_BindMaterialAnimation,
RF4S.exe+0x1B6770, resets the speed to 1.0f). Texture-pattern animations (the BM_* eye and
emblem swaps) are listed but not evaluated here.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field


class MatAnimError(Exception):
    pass


@dataclass
class Curve:
    flags: int
    target: int                  # byte offset inside the animated parameter
    start: float
    end: float
    scale: float
    offset: float
    delta: float
    frames: list
    keys: list                   # [(k0, k1, k2, k3)] cubic, [(v, d)] linear, [v] baked

    @property
    def frame_type(self):
        return self.flags & 3

    @property
    def key_type(self):
        return (self.flags >> 2) & 3

    @property
    def curve_type(self):
        return (self.flags >> 4) & 7

    def evaluate(self, frame):
        """The curve's value at `frame`, wrapped the way AnimChannel_SampleAsFloat wraps it."""
        f0, f1 = self.start, self.end
        add = 0.0
        if (frame < f0 or frame > f1) and f1 > f0:
            before = frame < f0
            mode = (self.flags >> (8 if before else 12)) & 3
            if mode == 0:
                frame = f0 if before else f1
            else:
                dist = (f0 - frame) if before else (frame - f1)
                n = int(dist / (f1 - f0))
                rem = dist - n * (f1 - f0)
                forward = True
                if mode == 3:
                    add = (n + 1) * self.delta * (-1.0 if before else 1.0)
                elif mode == 2:
                    forward = (n & 1) != 0
                frame = (rem + f0) if forward != before else (f1 - rem)
        return self._sample(frame) * self.scale + self.offset + add

    def _sample(self, frame):
        fr = self.frames
        if not fr:
            return 0.0
        if self.curve_type == 2:                        # baked: one key per frame
            i = max(0, min(len(self.keys) - 1, int(frame - self.start)))
            j = min(len(self.keys) - 1, i + 1)
            t = frame - self.start - i
            return self.keys[i] + (self.keys[j] - self.keys[i]) * t
        i = 0
        while i + 1 < len(fr) and fr[i + 1] <= frame:
            i += 1
        k0 = fr[i]
        k1 = fr[i + 1] if i + 1 < len(fr) else k0 + 1.0
        t = (frame - k0) / (k1 - k0) if k1 != k0 else 0.0
        key = self.keys[min(i, len(self.keys) - 1)]
        if self.curve_type == 0:
            a, b, c, d = key
            return a + t * (b + t * (c + t * d))
        v, dv = key
        return v + dv * t


@dataclass
class ParamAnim:
    name: str
    curves: list
    constants: list              # [(byte offset, raw u32)]
    int_curves: int = 0

    def value(self, frame, base=None):
        """The animated parameter as a list of 32-bit slots (floats; slot 0 of a texsrt is the
        integer mode) at `frame`, starting from `base` (defaults: texsrt identity)."""
        if base is None:
            base = [0, 1.0, 1.0, 0.0, 0.0, 0.0] if self.name.startswith("texsrt") else []
        v = list(base)
        width = max([len(v)] + [c.target // 4 + 1 for c in self.curves]
                    + [o // 4 + 1 for o, _ in self.constants])
        v += [0.0] * (width - len(v))
        for off, raw in self.constants:
            v[off // 4] = raw if off == 0 and self.name.startswith("texsrt") else \
                struct.unpack("<f", struct.pack("<I", raw))[0]
        for c in self.curves:
            v[c.target // 4] = c.evaluate(frame)
        return v


@dataclass
class MaterialAnim:
    name: str
    params: list
    texture_patterns: int = 0


@dataclass
class MatAnimFile:
    name: str
    frame_count: int
    flags: int
    materials: list = field(default_factory=list)

    @property
    def loops(self):
        return bool(self.flags & 4)

    def material(self, name):
        for m in self.materials:
            if m.name == name:
                return m
        return None

    def uv_matrix(self, material_name, frame, param="texsrt0"):
        """The 2x3 UV matrix (see `texsrt_matrix`) of a material at `frame`, or None when
        the material has no such animated parameter."""
        m = self.material(material_name)
        p = next((q for q in m.params if q.name == param), None) if m else None
        return texsrt_matrix(p.value(frame)) if p else None


def _curve(data, o):
    n = len(data)
    u16 = lambda x: struct.unpack_from("<H", data, x)[0]
    u32 = lambda x: struct.unpack_from("<I", data, x)[0]
    u64 = lambda x: struct.unpack_from("<Q", data, x)[0]
    f32 = lambda x: struct.unpack_from("<f", data, x)[0]
    flags, count = u16(o + 16), u16(o + 18)
    fp, kp = u64(o), u64(o + 8)
    ftype, ktype, ctype = flags & 3, (flags >> 2) & 3, (flags >> 4) & 7
    if not (0 < fp < n and 0 < kp < n) or ktype == 3 or ctype > 3:
        raise MatAnimError(f"curve at 0x{o:X}: unsupported flags 0x{flags:X}")
    fsize, ffmt = {0: (4, "f"), 1: (2, "h"), 2: (1, "B")}[ftype]
    frames = [struct.unpack_from("<" + ffmt, data, fp + fsize * i)[0] for i in range(count)]
    if ftype == 1:
        frames = [x / 32.0 for x in frames]
    ksize, kfmt = {0: (4, "f"), 1: (2, "h"), 2: (1, "b")}[ktype]
    per = {0: 4, 1: 2, 2: 1, 3: 1}[ctype]
    nkeys = count if ctype != 2 else int(f32(o + 28) - f32(o + 24)) + 1
    raw = [struct.unpack_from("<" + kfmt, data, kp + ksize * i)[0] for i in range(nkeys * per)]
    keys = [tuple(raw[i * per:(i + 1) * per]) for i in range(nkeys)] if per > 1 else raw
    return Curve(flags, u32(o + 20), f32(o + 24), f32(o + 28), f32(o + 32), f32(o + 36),
                 f32(o + 40), [float(x) for x in frames], keys)


def parse(data):
    if data[:4] != b"FRES":
        raise MatAnimError("not a FRES file")
    a = data.find(b"FMAA")
    if a < 0:
        raise MatAnimError("no FMAA (material animation) block")
    n = len(data)
    u16 = lambda x: struct.unpack_from("<H", data, x)[0]
    u32 = lambda x: struct.unpack_from("<I", data, x)[0]
    u64 = lambda x: struct.unpack_from("<Q", data, x)[0]

    def name(off):
        return data[off + 2:off + 2 + u16(off)].decode("utf-8", "replace") if 0 < off < n - 2 else ""

    out = MatAnimFile(name(u64(a + 0x10)), u32(a + 0x68), u32(a + 0x60))
    for mi in range(u16(a + 0x64)):
        m = u64(a + 0x30) + 0x40 * mi
        pinfo, curves, consts = u64(m + 8), u64(m + 0x18), u64(m + 0x20)
        n_param, n_pat = u16(m + 0x32), u16(m + 0x34)
        params = []
        for k in range(n_param):
            pi = pinfo + 0x18 * k
            c0, nf, ni, k0, nk = (u16(pi + 8 + 2 * j) for j in range(5))
            cv = [_curve(data, curves + 0x30 * (c0 + j)) for j in range(nf)]
            ks = [(u32(consts + 8 * (k0 + j)), u32(consts + 8 * (k0 + j) + 4)) for j in range(nk)] if consts else []
            params.append(ParamAnim(name(u64(pi)), cv, ks, ni))
        out.materials.append(MaterialAnim(name(u64(m)), params, n_pat))
    return out


def load(path):
    with open(path, "rb") as fh:
        return parse(fh.read())


def texsrt_matrix(srt):
    """2x3 UV matrix ((a, c, e), (b, d, f)) with u' = a u + c v + e, v' = b u + d v + f,
    built from a texsrt [mode, sx, sy, rot, tx, ty] the way TexSrt_BuildMatrix2x3ByMode
    (RF4S.exe+0x3E0B50) does. The builders write [m0..m5] = [cos sx, -sin sy, sin sx,
    cos sy, e, f]; m0..m3 are read as the columns (m0, m1), (m2, m3). With no rotation
    mode 0 gives u' = sx (u - tx), v' = sy (v + ty - 1) + 1."""
    mode = int(srt[0]) if srt else 0
    sx, sy, rot, tx, ty = (list(srt[1:6]) + [1.0, 1.0, 0.0, 0.0, 0.0][len(srt[1:6]):])[:5]
    ang = int(rot * 1000000.0) / 1000000.0
    s, c = math.sin(ang), math.cos(ang)
    m0, m1, m2, m3 = c * sx, -s * sy, s * sx, c * sy
    if mode == 1:
        e = (ty - 0.5) * (sx * s) - (tx + 0.5) * (sx * c) + 0.5
        f = (ty - 0.5) * (c * sy) + (tx + 0.5) * (s * sy) + 0.5
    else:
        k = s * 0.5 - 0.5
        e = ((c * -0.5 - k) - tx) * sx
        f = ((c * -0.5 + k) + ty) * sy + 1.0
    return ((m0, m2, e), (m1, m3, f))


def apply_uv(mtx, u, v):
    (a, c, e), (b, d, f) = mtx
    return a * u + c * v + e, b * u + d * v + f


def companion_path(model_path):
    """The `.bfmat` next to a `.model` (same stem), or None."""
    import pathlib
    p = pathlib.Path(model_path).with_suffix(".bfmat")
    return p if p.is_file() else None
