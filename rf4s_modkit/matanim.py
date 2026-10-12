r"""
matanim.py -- reader, evaluator and writer for RF4S `.bfmat` material animations (FRES / FMAA).

A `.bfmat` binds to a model's materials BY NAME. Most sit next to the `.model` they animate
(ANIM_DUNG_A02.bfmat -> ANIM_DUNG_A02.model, BM_00.bfmat -> BM_00.model); the rest are found
by material name (`owners` in the table at the end of this docstring). Like `.model` blocks,
the FMAA block carries a 16-byte header (magic + 12 zero bytes), so every field sits 8 bytes
later than in the public nn::g3d layout. Every offset below is an absolute file offset
(pointers are file-relative; the loader's relocation pass fixes them up).

File layout (all 59 shipped files follow it; `build` writes it byte for byte):

    FRES header (0xD0)  +0x10 u32 -> file-name chars  +0x16 u16 _STR offset  +0x18 u32 _RLT
         offset  +0x1C u32 file size  +0x20 -> file name  +0x48 -> FMAA  +0x50 -> FMAA dict
         +0xB0 -> string pool  +0xB8 u64 pool size  +0xC0 u16 FMAA count (always 1)
    FMAA (0x78)  +0x10 name ('temp')  +0x18 path  +0x28 -> bind indices (u16 per material)
         +0x30 -> material anims (0x40 each)  +0x38 -> texture pointers (runtime, zeros)
         +0x40 -> texture names  +0x58 -> texture descriptor slots (runtime, all 0xFF)
         +0x60 u32 flags (bit 2 = loop)  +0x64 u16 material-anim count  +0x66 u16 curve count
         +0x68 u32 frame count  +0x6C u32 baked size  +0x70 u16 param curves + constants
         +0x72 u16 texture-pattern count  +0x74 u16 visibility count  +0x76 u16 texture count
    FMAA dict   {u32 0, u32 count} + (count + 1) nodes {u32 bit, u16 left, u16 right, name}
    material anim (0x40)  +0x00 name (the material it binds to)  +0x08 -> param-anim infos
         (0x18 each)  +0x10 -> pattern-anim infos (0x10 each)  +0x18 -> curves (0x30 each)
         +0x20 -> constants ({u32 offset, u32 value})  +0x28 u16 first param curve (file-wide
         curve index, 0xFFFF = none)  +0x2A u16 first pattern curve (file-wide)  +0x2C/+0x2E/
         +0x30 visibility curve / curve / constant (all 0xFFFF)  +0x32 u16 param-anim count
         +0x34 u16 pattern-anim count  +0x36 u16 constant count  +0x38 u16 curve count
    param-anim info (0x18)  +0x00 name (shader parameter)  +0x08 u16 first curve  +0x0A u16
         float curves  +0x0C u16 int curves  +0x0E u16 first constant  +0x10 u16 constants
         +0x12 u16 0xFFFF (runtime bind slot)
    pattern-anim info (0x10)  +0x00 name (the material SAMPLER, '_a0' = albedoTex0)  +0x08 u16
         curve (material-local, 0xFFFF = constant)  +0x0A u16 constant  +0x0C u8 0xFF
    then per material: param infos, pattern infos, constants, curves, and each curve's frame
    and key arrays (8-aligned); then _STR (u16-length-prefixed strings, the empty one first)
    and _RLT (pointer relocation runs, see `_rlt_entries`).

Curves are the nn::g3d AnimCurve, evaluated as AnimChannel_SampleAsFloat (RF4S.exe+0x3DF9F0)
does: +0 -> frames, +8 -> keys, +0x10 u16 flags (bits 0-1 frame type f32 / s16 x1/32 / u8,
bits 2-3 key type 32-bit / s16 / s8, bits 4-6 curve type: 0 cubic, 1 linear, 2 baked float,
4 step int, 5 baked int, 6 step bool, 7 baked bool; bits 8-9 pre- and 12-13 post-wrap: clamp /
repeat / mirror / repeat-with-offset), +0x12 u16 key count, +0x14 u32 byte offset into the
parameter, +0x18 f32 start frame, +0x1C end frame, +0x20 f32 scale, +0x24 f32 offset, +0x28
f32 wrap delta. Float value = poly(t) * scale + offset, poly = k0 + k1 t + k2 t^2 + k3 t^3 for
cubic keys (AnimCurve_SampleCubic_KeyS8, +0x3DF510), t = (frame - f0) / (f1 - f0) between the
two keys the seek (+0x3DF2A0 for u8 frames) lands on. Integer curves (AnimChannel_SampleAsInt,
RF4S.exe+0x3DFB80) read +0x24 as an s32 offset and +0x28 as an s32 wrap delta, wrap the
frame the same way and dispatch through the table at RF4S.exe+0x4A85F0: step int
(RF4S.exe+0x3DF8D0) returns key[i] of the key AnimCurve_FindKeyPairCached (+0x3DFD00) finds
(the last key whose frame <= the frame), baked int (+0x3DF990) key[int(frame) - int(start)].

Parameters the shipped files animate:
    texsrt0 (49 anims, 43 files)  [mode, sx, sy, rot, tx, ty] (u32 + 5 f32); the mode is a constant.
        Mode 0 -> 2x3 UV matrix through TexSrt_BuildMatrix2x3_PivotA (RF4S.exe+0x3E0BA0),
        mode 1 through _PivotB (+0x3E0A50); see `texsrt_matrix`.
    opacity (46 anims, 12 files)  rateOpacityData, a vec4 in rf4cmv (`id="opacity" default="1 1 1 1"`);
        the files animate .r/.g/.b (offsets 0/4/8) with cubic curves. The vertex shader folds
        clamp(opacity.r, 0, 1) into the light colour's alpha (Rf4LightSetCiombineColor) and
        the fragment shader multiplies the albedo alpha by it BEFORE the 1/255 discard, so
        it fades the whole material (level_up / skill_up text, font_* banners, anim_com*).
    Texture patterns (29 anims, 15 files) swap the texture of a sampler: the int curve's value
    is an index into the FMAA texture-name array.

How the engine plays them (offline disassembly of RF4S.exe; the IDB was not reachable):
  * Actor_BindMaterialAnimation (RF4S.exe+0x1B6770) takes the FRES's first FMAA, creates the
    N3DMaterialAnimationObject, binds it (vslot 004, RF4S.exe+0x3CEBD0: each material anim's
    name through Dic_LookupNameIndex in the model's material dict; misses stay unbound, e.g.
    BM_00's 'eye_R' -- BM_00.model has only 'eye_L') and resolves the texture names in
    RenderResource_InstantiateAndBindNamedRefs (RF4S.exe+0x1C04A0) against the actor's own
    model's texture dict (a missing name asserts). Per material (+0x3CF700) each param anim
    name is looked up in the ResMaterial shader-param dict (+0x60) and each pattern anim name
    in its SAMPLER dict (+0x50) -> sampler index; the texture array index = sampler index.
  * Calculate (vslot 001, RF4S.exe+0x3CEE40) samples param curves (RenderResource_Sample-
    AnimChannelsToTypedBuffer, +0x3D47E0) and pattern curves (+0x3D4BE0 / +0x3D4AE0, one
    AnimChannel_SampleAsInt per bound pattern) into one result slot per curve; ApplyTo
    (vslot 002, +0x3CE920 -> +0x3CE630) writes param values at their byte offsets and, for
    a pattern, clamps the index to [0, texture count - 1] (a constant pattern is not clamped)
    and sets that texture on the sampler (+0x3D5FD0).
  * Ticking (Sprite_Tick3DAnimations_Type1, RF4S.exe+0x1BAD90): frame += rate; when frame >=
    int(end) it wraps by subtracting end -- ALWAYS, the FMAA loop flag is not consulted, and
    a frame equal to the frame count is never shown (BM_02's key 4 at frame 34, the one
    naming a texture BM_02.model lacks, never plays). A rate of 0 skips the tick entirely.
    The bind stores rate = the frame controller's step and frame = 1.0; Actor_SpawnByCharId
    (RF4S.exe+0x15C4E5 / +0x15C547) zeroes the rate for some character ids right after the
    bind (their animation never ticks, so the material keeps the model's own texture) and
    one post-tick hook (RF4S.exe+0x162B50) sets it to 1.0 while the actor moves, 0.0 when
    it stops. The preview (`play_frame`) plays at rate 1 from frame 0.

Which model each file belongs to (material names; * = same stem):
    ANIM_*/MOBJ_* water, lava, light shafts -> ANIM_*.model* / mobj_pond*.model; BM_*,
    M43_*, efc_death01, efc_tornado, level_up, skill_up, font_order -> the .model of the same
    stem (and the _deu/_fra variants for the text); anim_com01..10 -> SYS_MENU_ANIME_01..10;
    efc_emight01 -> efc_emight.model; font_start / font_finish -> efc_start*/efc_finish*.

`build(anim)` re-encodes a parsed file (all 59 rebuild byte for byte); `to_json` / `from_json`
give an editable dump, `retime` scales the playback speed.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field


class MatAnimError(Exception):
    pass


# curve types (flags bits 4-6)
CUBIC, LINEAR, BAKED_FLOAT, STEP_INT, BAKED_INT, STEP_BOOL, BAKED_BOOL = 0, 1, 2, 4, 5, 6, 7
_INT_TYPES = (STEP_INT, BAKED_INT, STEP_BOOL, BAKED_BOOL)
_PER_KEY = {CUBIC: 4, LINEAR: 2}


@dataclass
class Curve:
    flags: int
    target: int                  # byte offset inside the animated parameter
    start: float
    end: float
    scale: float                 # int curves: raw s32 (unused, 0)
    offset: float                # int curves: s32
    delta: float                 # int curves: s32
    frames: list
    keys: list                   # [(k0, k1, k2, k3)] cubic, [(v, d)] linear, [v] baked / int
    pad: int = 0                 # +0x2C

    @property
    def frame_type(self):
        return self.flags & 3

    @property
    def key_type(self):
        return (self.flags >> 2) & 3

    @property
    def curve_type(self):
        return (self.flags >> 4) & 7

    @property
    def is_int(self):
        return self.curve_type in _INT_TYPES

    def _wrap(self, frame):
        """(frame inside [start, end], repeat-with-offset cycles) as both samplers wrap it."""
        f0, f1 = self.start, self.end
        cycles = 0
        if (frame < f0 or frame > f1) and f1 > f0:
            before = frame < f0
            mode = (self.flags >> (8 if before else 12)) & 3
            if mode == 0:
                return (f0 if before else f1), 0
            dist = (f0 - frame) if before else (frame - f1)
            n = int(dist / (f1 - f0))
            rem = dist - n * (f1 - f0)
            forward = True
            if mode == 3:
                cycles = -(n + 1) if before else (n + 1)
            elif mode == 2:
                forward = (n & 1) != 0
            frame = (rem + f0) if forward != before else (f1 - rem)
        return frame, cycles

    def evaluate(self, frame):
        """The curve's value at `frame`: a float for float curves (AnimChannel_SampleAsFloat),
        an int for int / bool curves (AnimChannel_SampleAsInt)."""
        frame, cycles = self._wrap(frame)
        if self.is_int:
            return int(self._sample_int(frame)) + int(self.offset) + cycles * int(self.delta)
        return self._sample(frame) * self.scale + self.offset + cycles * self.delta

    def _seek(self, frame):
        fr = self.frames
        i = 0
        while i + 1 < len(fr) and fr[i + 1] <= frame:
            i += 1
        return i

    def _sample_int(self, frame):
        if not self.keys:
            return 0
        ct = self.curve_type
        if ct in (BAKED_INT, BAKED_BOOL):
            i = max(0, min(len(self.keys) - 1, int(frame) - int(self.start)))
        else:
            i = min(self._seek(frame), len(self.keys) - 1)
        return self.keys[i]

    def _sample(self, frame):
        fr = self.frames
        if not fr:
            return 0.0
        if self.curve_type == BAKED_FLOAT:              # one key per frame
            i = max(0, min(len(self.keys) - 1, int(frame - self.start)))
            j = min(len(self.keys) - 1, i + 1)
            t = frame - self.start - i
            return self.keys[i] + (self.keys[j] - self.keys[i]) * t
        i = self._seek(frame)
        k0 = fr[i]
        k1 = fr[i + 1] if i + 1 < len(fr) else k0 + 1.0
        t = (frame - k0) / (k1 - k0) if k1 != k0 else 0.0
        key = self.keys[min(i, len(self.keys) - 1)]
        if self.curve_type == CUBIC:
            a, b, c, d = key
            return a + t * (b + t * (c + t * d))
        v, dv = key
        return v + dv * t


@dataclass
class ParamAnim:
    name: str
    curves: list                 # float curves, then int curves
    constants: list              # [(byte offset, raw u32)]
    int_curves: int = 0
    bind: int = 0xFFFF           # +0x12 (runtime slot, 0xFFFF in files)
    pad: int = 0                 # +0x14

    def value(self, frame, base=None):
        """The animated parameter as a list of 32-bit slots (floats; slot 0 of a texsrt is the
        integer mode) at `frame`, starting from `base` (defaults: texsrt identity, opacity
        1 1 1 1)."""
        if base is None:
            if self.name.startswith("texsrt"):
                base = [0, 1.0, 1.0, 0.0, 0.0, 0.0]
            elif self.name == "opacity":
                base = [1.0, 1.0, 1.0, 1.0]
            else:
                base = []
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
class PatternAnim:
    """A texture-pattern anim: the texture (index into MatAnimFile.textures) bound to the
    material sampler `name` ('_a0' = albedoTex0) at each frame."""
    name: str
    curve: Curve | None          # int curve (None = constant pattern)
    constant: int | None = None  # texture index of a constant pattern
    bind: int = 0xFF             # +0x0C (runtime slot)
    pad: bytes = b"\0\0\0"

    def index(self, frame, texture_count=None):
        """The texture index at `frame`, clamped the way ApplyTo clamps a curve's value."""
        if self.curve is None:
            return int(self.constant or 0)
        i = int(self.curve.evaluate(frame))
        if texture_count:
            i = max(0, min(texture_count - 1, i))
        return max(0, i)


@dataclass
class MaterialAnim:
    name: str
    params: list
    patterns: list = field(default_factory=list)
    vis: tuple = (0xFFFF, 0xFFFF, 0xFFFF)   # +0x2C, +0x2E, +0x30
    pad: bytes = b"\0" * 6                    # +0x3A

    @property
    def texture_patterns(self):
        return len(self.patterns)

    def curves(self):
        """All curves in file order: param curves (param by param), then pattern curves."""
        return [c for p in self.params for c in p.curves] + \
               [p.curve for p in self.patterns if p.curve is not None]


@dataclass
class MatAnimFile:
    name: str                    # FMAA name ('temp' in every shipped file)
    frame_count: int
    flags: int
    materials: list = field(default_factory=list)
    textures: list = field(default_factory=list)   # FMAA texture-name array (patterns index it)
    file_name: str = ""          # the FRES name, e.g. 'BM_00.bfmat'
    path: str = ""
    header: bytes = b"\x01\x02\x08\x00\xff\xfe\x03\x00"   # FRES +0x08 (version, BOM, alignment)
    bind_indices: list = field(default_factory=list)       # u16 per material (0xFFFF)
    strings: list = field(default_factory=list)            # string-pool order (kept on rebuild)
    baked_size: int = 0                                    # as read (build recomputes it)

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

    def opacity(self, material_name, frame):
        """clamp(opacity.r, 0, 1) of a material at `frame` (what the shader multiplies the
        albedo alpha by), or None when the material has no animated opacity."""
        m = self.material(material_name)
        p = next((q for q in m.params if q.name == "opacity"), None) if m else None
        return max(0.0, min(1.0, float(p.value(frame)[0]))) if p else None

    def pattern_textures(self, material_name, frame):
        """{sampler name: texture name} the material's texture patterns pick at `frame`."""
        m = self.material(material_name)
        out = {}
        for p in (m.patterns if m else []):
            i = p.index(frame, len(self.textures))
            if 0 <= i < len(self.textures):
                out[p.name] = self.textures[i]
        return out

    def play_frame(self, tick):
        """The frame the game shows `tick` ticks into playback: the material animation always
        wraps at int(frame count), whatever the loop flag (Sprite_Tick3DAnimations_Type1)."""
        n = int(self.frame_count)
        return tick % n if n > 0 else 0.0

    @property
    def curve_count(self):
        return sum(len(m.curves()) for m in self.materials)


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #
_FFMT = {0: (4, "f"), 1: (2, "h"), 2: (1, "B")}
_KFMT_F = {0: (4, "f"), 1: (2, "h"), 2: (1, "b")}
_KFMT_I = {0: (4, "i"), 1: (2, "h"), 2: (1, "b")}


def _key_count(ct, count, start, end):
    """Number of key units a curve stores."""
    if ct in (BAKED_FLOAT, BAKED_INT, BAKED_BOOL):
        return int(end - start) + 1
    return count


def _curve(data, o):
    n = len(data)
    u16 = lambda x: struct.unpack_from("<H", data, x)[0]
    u32 = lambda x: struct.unpack_from("<I", data, x)[0]
    u64 = lambda x: struct.unpack_from("<Q", data, x)[0]
    f32 = lambda x: struct.unpack_from("<f", data, x)[0]
    flags, count = u16(o + 16), u16(o + 18)
    fp, kp = u64(o), u64(o + 8)
    ftype, ktype, ctype = flags & 3, (flags >> 2) & 3, (flags >> 4) & 7
    if not (0 < fp < n and 0 < kp < n) or ftype == 3 or ktype == 3 or ctype == 3:
        raise MatAnimError(f"curve at 0x{o:X}: unsupported flags 0x{flags:X}")
    fsize, ffmt = _FFMT[ftype]
    frames = [struct.unpack_from("<" + ffmt, data, fp + fsize * i)[0] for i in range(count)]
    if ftype == 1:
        frames = [x / 32.0 for x in frames]
    start, end = f32(o + 24), f32(o + 28)
    nkeys = _key_count(ctype, count, start, end)
    if ctype in (STEP_BOOL, BAKED_BOOL):
        words = struct.unpack_from("<%dI" % ((nkeys + 31) // 32), data, kp)
        keys = [(words[i >> 5] >> (i & 31)) & 1 for i in range(nkeys)]
    else:
        ksize, kfmt = (_KFMT_I if ctype in _INT_TYPES else _KFMT_F)[ktype]
        per = _PER_KEY.get(ctype, 1)
        raw = list(struct.unpack_from("<%d%s" % (nkeys * per, kfmt), data, kp))
        keys = [tuple(raw[i * per:(i + 1) * per]) for i in range(nkeys)] if per > 1 else raw
    if ctype in _INT_TYPES:
        sc, of, de = struct.unpack_from("<iii", data, o + 32)
    else:
        sc, of, de = f32(o + 32), f32(o + 36), f32(o + 40)
    return Curve(flags, u32(o + 20), start, end, sc, of, de,
                 [float(x) for x in frames], keys, u32(o + 44))


def parse(data):
    if data[:4] != b"FRES":
        raise MatAnimError("not a FRES file")
    a = struct.unpack_from("<Q", data, 0x48)[0] if len(data) >= 0x50 else 0
    if data[a:a + 4] != b"FMAA":
        a = data.find(b"FMAA")
    if a < 0:
        raise MatAnimError("no FMAA (material animation) block")
    n = len(data)
    u8 = lambda x: data[x]
    u16 = lambda x: struct.unpack_from("<H", data, x)[0]
    u32 = lambda x: struct.unpack_from("<I", data, x)[0]
    u64 = lambda x: struct.unpack_from("<Q", data, x)[0]

    def name(off):
        return data[off + 2:off + 2 + u16(off)].decode("utf-8", "replace") if 0 < off < n - 2 else ""

    out = MatAnimFile(name(u64(a + 0x10)), u32(a + 0x68), u32(a + 0x60))
    out.file_name = name(u64(0x20))
    out.path = name(u64(a + 0x18))
    out.header = bytes(data[8:16])
    out.baked_size = u32(a + 0x6C)
    nmat, ntex = u16(a + 0x64), u16(a + 0x76)
    bi = u64(a + 0x28)
    out.bind_indices = list(struct.unpack_from("<%dH" % nmat, data, bi)) if bi and nmat else []
    tn = u64(a + 0x40)
    out.textures = [name(u64(tn + 8 * i)) for i in range(ntex)] if tn else []
    for mi in range(nmat):
        m = u64(a + 0x30) + 0x40 * mi
        pinfo, pats, curves, consts = u64(m + 8), u64(m + 0x10), u64(m + 0x18), u64(m + 0x20)
        n_param, n_pat, n_const = u16(m + 0x32), u16(m + 0x34), u16(m + 0x36)
        ctab = [(u32(consts + 8 * j), u32(consts + 8 * j + 4)) for j in range(n_const)] if consts else []
        params = []
        for k in range(n_param):
            pi = pinfo + 0x18 * k
            c0, nf, ni, k0, nk = (u16(pi + 8 + 2 * j) for j in range(5))
            cv = [_curve(data, curves + 0x30 * (c0 + j)) for j in range(nf + ni)]
            params.append(ParamAnim(name(u64(pi)), cv, ctab[k0:k0 + nk], ni, u16(pi + 0x12), u32(pi + 0x14)))
        patterns = []
        for k in range(n_pat):
            q = pats + 0x10 * k
            ci, kc = u16(q + 8), u16(q + 0xA)
            cv = _curve(data, curves + 0x30 * ci) if ci != 0xFFFF else None
            const = struct.unpack("<i", struct.pack("<I", ctab[kc][1]))[0] if cv is None and kc < len(ctab) else None
            patterns.append(PatternAnim(name(u64(q)), cv, const, u8(q + 0xC), bytes(data[q + 0xD:q + 0x10])))
        out.materials.append(MaterialAnim(name(u64(m)), params, patterns,
                                          (u16(m + 0x2C), u16(m + 0x2E), u16(m + 0x30)),
                                          bytes(data[m + 0x3A:m + 0x40])))
    st = u16(0x16)
    if data[st:st + 4] == b"_STR":
        cnt = u32(st + 0x10)
        o = st + 0x14
        strs = []
        for _ in range(cnt + 1):
            ln = u16(o)
            strs.append(data[o + 2:o + 2 + ln].decode("utf-8", "replace"))
            o += 2 + ln + 1
            o += o & 1
        out.strings = strs[1:]
    return out


def load(path):
    with open(path, "rb") as fh:
        return parse(fh.read())


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #
def _align(x, a=8):
    return (x + a - 1) // a * a


def _baked_size(c):
    """The runtime bake-buffer size nn::g3d reserves for one curve (FMAA +0x6C is the sum;
    fitted to all 59 shipped files): float curves align8(4 * (frames + 1)) + 24, int
    curves align8(4 * frames) + 16, frames = int(end - start) + 1."""
    n = int(c.end - c.start) + 1
    if c.is_int:
        return _align(4 * n) + 16
    return _align(4 * (n + 1)) + 24


def _encode_frames(c):
    ft = c.frame_type
    if ft == 1:
        return struct.pack("<%dh" % len(c.frames), *[int(round(f * 32)) for f in c.frames])
    if ft == 2:
        return struct.pack("<%dB" % len(c.frames), *[int(round(f)) for f in c.frames])
    return struct.pack("<%df" % len(c.frames), *c.frames)


def _encode_keys(c):
    ct, kt = c.curve_type, c.key_type
    if ct in (STEP_BOOL, BAKED_BOOL):
        words = [0] * ((len(c.keys) + 31) // 32)
        for i, b in enumerate(c.keys):
            if b:
                words[i >> 5] |= 1 << (i & 31)
        return struct.pack("<%dI" % len(words), *words)
    flat = [x for k in c.keys for x in (k if isinstance(k, (tuple, list)) else (k,))]
    fmt = (_KFMT_I if ct in _INT_TYPES else _KFMT_F)[kt][1]
    if fmt != "f":
        flat = [int(round(x)) for x in flat]
    return struct.pack("<%d%s" % (len(flat), fmt), *flat)


def _fits(c):
    """True when the curve's frames are representable in its stored frame type."""
    ft = c.frame_type
    if ft == 2:
        return all(float(f).is_integer() and 0 <= f <= 255 for f in c.frames)
    if ft == 1:
        return all(float(f * 32).is_integer() and -32768 <= f * 32 <= 32767 for f in c.frames)
    return True


class _Writer:
    def __init__(self):
        self.buf = bytearray()
        self.ptrs = []           # (slot offset, target key) -- resolved after layout
        self.slots = []          # every pointer slot (null ones included) for the RLT

    def at(self):
        return len(self.buf)

    def pad(self, a=8):
        self.buf += b"\0" * (_align(len(self.buf), a) - len(self.buf))

    def raw(self, b):
        self.buf += b

    def ptr(self, target):
        """A u64 pointer slot to `target` (a region key, ('str', s) or None = null)."""
        self.slots.append(self.at())
        self.ptrs.append((self.at(), target))
        self.buf += b"\0" * 8


def _rlt_entries(slots):
    """Encode pointer slots as {pos, struct count, offset count, padding count} runs the way
    the shipped files do: maximal runs of adjacent slots, then each run joined with the later
    runs of the same length that repeat at a constant stride."""
    slots = sorted(set(slots))
    runs = []
    for s in slots:
        if runs and runs[-1][0] + 8 * runs[-1][1] == s and runs[-1][1] < 255:
            runs[-1][1] += 1
        else:
            runs.append([s, 1])
    used = [False] * len(runs)
    by_pos = {r[0]: i for i, r in enumerate(runs)}
    out = []
    for i, (pos, cnt) in enumerate(runs):
        if used[i]:
            continue
        used[i] = True
        sc, stride = 1, None
        nxt = next((j for j in range(i + 1, len(runs)) if not used[j] and runs[j][1] == cnt), None)
        if nxt is not None:
            stride = runs[nxt][0] - pos
            if not (stride % 8 == 0 and 0 <= stride // 8 - cnt <= 255):
                stride = None
        while stride:
            j = by_pos.get(pos + sc * stride)
            if j is None or used[j] or runs[j][1] != cnt or sc >= 0xFFFF:
                break
            used[j] = True
            sc += 1
        pc = (stride // 8 - cnt) if sc > 1 else 0
        out.append((pos, sc, cnt, pc))
    return out


def _dict_bit(key):
    """The Patricia-trie bit of a one-entry nn dict: the lowest set bit, counted from the
    string's last byte."""
    b = key.encode("utf-8")
    for i in range(len(b) * 8):
        if (b[len(b) - 1 - (i >> 3)] >> (i & 7)) & 1:
            return i
    return 0


def build(anim):
    """Encode a MatAnimFile as .bfmat bytes (the layout of the shipped files; a parsed
    shipped file comes back byte for byte)."""
    for m in anim.materials:
        for c in m.curves():
            if not _fits(c):
                c.flags &= ~3                       # promote the frames to f32
    w = _Writer()
    mats = anim.materials
    nmat, ntex = len(mats), len(anim.textures)
    regions = {}

    # used strings, in the source pool order, new ones appended
    used = [anim.file_name, anim.name, anim.path] + [m.name for m in mats] + \
           [p.name for m in mats for p in m.params] + [p.name for m in mats for p in m.patterns] + \
           list(anim.textures)
    seen = set()
    order = []
    for s in list(anim.strings) + used:
        if s and s in set(used) and s not in seen:
            seen.add(s)
            order.append(s)

    # --- FRES header ---
    w.raw(b"FRES    " + bytes(anim.header[:8]).ljust(8, b"\0"))
    w.raw(b"\0" * 16)                                # +0x10..+0x1F patched at the end
    for k in range(19):                              # +0x20..+0xB0: 19 pointer slots
        w.ptr({0: ("str", anim.file_name), 5: "fmaa", 6: "fdict", 18: ("str", "")}.get(k))
    w.raw(b"\0" * 8)                                 # +0xB8 pool size (patched)
    w.raw(struct.pack("<H", 1) + b"\0" * 14)         # +0xC0 FMAA count
    # --- FMAA ---
    regions["fmaa"] = w.at()
    w.raw(b"FMAA" + b"\0" * 12)
    w.ptr(("str", anim.name))
    w.ptr(("str", anim.path))
    w.ptr(None)                                      # bind model
    w.ptr("bind")
    w.ptr("mats")
    w.ptr("texptr" if ntex else None)
    w.ptr("texname" if ntex else None)
    w.raw(b"\0" * 8)                                 # +0x48 user data (not relocated)
    w.ptr(None)                                      # +0x50 user-data dict
    w.ptr("texbind" if ntex else None)
    all_curves = [c for m in mats for c in m.curves()]
    n_pc = sum(len(p.curves) + len(p.constants) for m in mats for p in m.params)
    n_pat = sum(len(m.patterns) for m in mats)
    baked = sum(_baked_size(c) for c in all_curves)
    w.raw(struct.pack("<IHHIIHHHH", anim.flags, nmat, len(all_curves), int(anim.frame_count),
                      baked, n_pc, n_pat, 0, ntex))
    # --- FMAA dict (one entry) ---
    regions["fdict"] = w.at()
    w.raw(struct.pack("<II", 0, 1))
    w.raw(struct.pack("<IHH", 0xFFFFFFFF, 1, 0))
    w.ptr(("str", ""))
    w.raw(struct.pack("<IHH", _dict_bit(anim.name), 0, 1))
    w.ptr(("str", anim.name))
    # --- bind indices, material anims ---
    regions["bind"] = w.at()
    bind = list(anim.bind_indices) + [0xFFFF] * (nmat - len(anim.bind_indices))
    w.raw(struct.pack("<%dH" % nmat, *bind[:nmat]))
    w.pad()
    regions["mats"] = w.at()
    gcurve = 0
    for i, m in enumerate(mats):
        np_c = sum(len(p.curves) for p in m.params)
        npat_c = sum(1 for p in m.patterns if p.curve is not None)
        consts = [kv for p in m.params for kv in p.constants]
        pconsts = [p for p in m.patterns if p.curve is None]
        w.ptr(("str", m.name))
        w.ptr(("pinfo", i) if m.params else None)
        w.ptr(("pat", i) if m.patterns else None)
        w.ptr(("curves", i) if (np_c + npat_c) else None)
        w.ptr(("consts", i) if (consts or pconsts) else None)
        w.raw(struct.pack("<HH", gcurve if np_c else 0xFFFF, gcurve + np_c if npat_c else 0xFFFF))
        w.raw(struct.pack("<HHH", *m.vis))
        w.raw(struct.pack("<HHHH", len(m.params), len(m.patterns), len(consts) + len(pconsts),
                          np_c + npat_c))
        w.raw(bytes(m.pad[:6]).ljust(6, b"\0"))
        gcurve += np_c + npat_c
    if ntex:
        regions["texbind"] = w.at()
        w.raw(b"\xff" * (8 * ntex))
        regions["texptr"] = w.at()
        w.raw(b"\0" * (8 * ntex))
        regions["texname"] = w.at()
        for t in anim.textures:
            w.ptr(("str", t))
    # --- per material: infos, constants, curves, curve data ---
    for i, m in enumerate(mats):
        consts = [kv for p in m.params for kv in p.constants]
        if m.params:
            w.pad()
            regions[("pinfo", i)] = w.at()
            c0 = k0 = 0
            for p in m.params:
                w.ptr(("str", p.name))
                w.raw(struct.pack("<HHHHHHI", c0, len(p.curves) - p.int_curves, p.int_curves,
                                  k0, len(p.constants), p.bind, p.pad))
                c0 += len(p.curves)
                k0 += len(p.constants)
        np_c = sum(len(p.curves) for p in m.params)
        if m.patterns:
            w.pad()
            regions[("pat", i)] = w.at()
            ci, kc = np_c, len(consts)
            for p in m.patterns:
                w.ptr(("str", p.name))
                if p.curve is not None:
                    w.raw(struct.pack("<HHB", ci, 0xFFFF, p.bind))
                    ci += 1
                else:
                    w.raw(struct.pack("<HHB", 0xFFFF, kc, p.bind))
                    kc += 1
                w.raw(bytes(p.pad[:3]).ljust(3, b"\0"))
        pconsts = [(0, p.constant & 0xFFFFFFFF) for p in m.patterns if p.curve is None]
        if consts or pconsts:
            w.pad()
            regions[("consts", i)] = w.at()
            for off, val in consts + pconsts:
                w.raw(struct.pack("<II", off, val & 0xFFFFFFFF))
        cv = m.curves()
        if cv:
            w.pad()
            regions[("curves", i)] = w.at()
            for j, c in enumerate(cv):
                w.ptr(("frames", i, j))
                w.ptr(("keys", i, j))
                w.raw(struct.pack("<HHI", c.flags, len(c.frames), c.target))
                w.raw(struct.pack("<ff", c.start, c.end))
                if c.is_int:
                    w.raw(struct.pack("<iiiI", int(c.scale), int(c.offset), int(c.delta), c.pad))
                else:
                    w.raw(struct.pack("<fffI", c.scale, c.offset, c.delta, c.pad))
            for j, c in enumerate(cv):
                w.pad()
                regions[("frames", i, j)] = w.at()
                w.raw(_encode_frames(c))
                w.pad()
                regions[("keys", i, j)] = w.at()
                w.raw(_encode_keys(c))
    # --- string pool ---
    w.pad()
    st = w.at()
    w.raw(b"_STR" + b"\0" * 12 + struct.pack("<I", len(order)))
    sref = {"": w.at()}
    w.raw(b"\0\0\0\0")
    for s in order:
        sref[s] = w.at()
        b = s.encode("utf-8")
        w.raw(struct.pack("<H", len(b)) + b + b"\0")
        w.pad(2)
    str_end = w.at()
    w.pad()
    rlt = w.at()
    # resolve pointers
    for slot, tgt in w.ptrs:
        if tgt is None:
            continue
        v = sref[tgt[1]] if isinstance(tgt, tuple) and tgt[0] == "str" else regions[tgt]
        struct.pack_into("<Q", w.buf, slot, v)
    struct.pack_into("<Q", w.buf, st + 8, rlt - st)
    struct.pack_into("<Q", w.buf, 0xB8, str_end - st)
    # --- relocation table ---
    ents = _rlt_entries(w.slots)
    w.raw(b"_RLT" + struct.pack("<III", rlt, 5, 0))
    w.raw(struct.pack("<QIIII", 0, 0, str_end, 0, len(ents)))
    for _ in range(4):
        w.raw(struct.pack("<QIIII", 0, str_end, 0, len(ents), 0))
    for pos, sc, oc, pc in ents:
        w.raw(struct.pack("<IHBB", pos, sc, oc, pc))
    if st > 0xFFFF:
        raise MatAnimError("the animation is too large: its string pool would start past 64 KiB "
                           "(the file header keeps that offset in 16 bits) -- use fewer keys")
    struct.pack_into("<IHHII", w.buf, 0x10, sref[anim.file_name] + 2, 0, st, rlt, len(w.buf))
    return bytes(w.buf)


def save(anim, path):
    with open(path, "wb") as fh:
        fh.write(build(anim))


# --------------------------------------------------------------------------- #
# editing
# --------------------------------------------------------------------------- #
def retime(anim, speed):
    """Play `anim` about `speed` times as fast (2.0 = twice as fast, 0.5 = half): the frame
    count becomes round(frame count / speed) and every key frame and curve range is scaled
    by the same exact ratio, so a curve that ended on the last frame still does (no hitch at
    the wrap). Cubic / linear keys are per segment (t = 0..1), so their values stay; frames
    that no longer fit the stored u8 / fixed-point frame type are promoted to f32 by `build`."""
    if speed <= 0:
        raise MatAnimError("speed must be > 0")
    old = max(1, int(anim.frame_count))
    new = max(1, int(round(old / speed)))
    k = new / old
    for m in anim.materials:
        for c in m.curves():
            if c.curve_type in (BAKED_FLOAT, BAKED_INT, BAKED_BOOL):
                raise MatAnimError(f"{m.name}: baked curves cannot be retimed")
            c.frames = [f * k for f in c.frames]
            c.start, c.end = c.start * k, c.end * k
    anim.frame_count = new
    return anim


def _curve_json(c):
    return {"flags": c.flags, "target": c.target, "start": c.start, "end": c.end,
            "scale": c.scale, "offset": c.offset, "delta": c.delta, "pad": c.pad,
            "frames": c.frames, "keys": [list(k) if isinstance(k, tuple) else k for k in c.keys]}


def _curve_from(d):
    per = _PER_KEY.get((d["flags"] >> 4) & 7, 1)
    keys = [tuple(k) for k in d["keys"]] if per > 1 else list(d["keys"])
    return Curve(int(d["flags"]), int(d["target"]), float(d["start"]), float(d["end"]),
                 d.get("scale", 1.0), d.get("offset", 0.0), d.get("delta", 0.0),
                 [float(f) for f in d["frames"]], keys, int(d.get("pad", 0)))


def to_json(anim):
    """An editable dict of the whole file (`from_json` + `build` restore it byte for byte).
    Curve keys are raw: value = poly(key) * scale + offset (float curves); for texture
    patterns the key is the index into `textures`."""
    return {
        "file_name": anim.file_name, "name": anim.name, "path": anim.path,
        "flags": anim.flags, "loop": anim.loops, "frame_count": anim.frame_count,
        "header": anim.header.hex(), "bind_indices": anim.bind_indices,
        "strings": anim.strings, "textures": anim.textures,
        "materials": [{
            "name": m.name, "vis": list(m.vis), "pad": m.pad.hex(),
            "params": [{"name": p.name, "int_curves": p.int_curves, "bind": p.bind, "pad": p.pad,
                        "constants": [list(kv) for kv in p.constants],
                        "curves": [_curve_json(c) for c in p.curves]} for p in m.params],
            "patterns": [{"sampler": p.name, "bind": p.bind, "pad": p.pad.hex(),
                          "constant": p.constant,
                          "curve": _curve_json(p.curve) if p.curve is not None else None}
                         for p in m.patterns]} for m in anim.materials]}


def from_json(d):
    anim = MatAnimFile(d["name"], int(d["frame_count"]), int(d["flags"]))
    if "loop" in d:
        anim.flags = (anim.flags | 4) if d["loop"] else (anim.flags & ~4)
    anim.file_name = d.get("file_name", "")
    anim.path = d.get("path", "")
    anim.header = bytes.fromhex(d.get("header", "01020800fffe0300"))
    anim.bind_indices = list(d.get("bind_indices", []))
    anim.strings = list(d.get("strings", []))
    anim.textures = list(d.get("textures", []))
    for m in d["materials"]:
        params = [ParamAnim(p["name"], [_curve_from(c) for c in p["curves"]],
                            [tuple(kv) for kv in p.get("constants", [])], int(p.get("int_curves", 0)),
                            int(p.get("bind", 0xFFFF)), int(p.get("pad", 0))) for p in m.get("params", [])]
        pats = [PatternAnim(p["sampler"], _curve_from(p["curve"]) if p.get("curve") else None,
                            p.get("constant"), int(p.get("bind", 0xFF)),
                            bytes.fromhex(p.get("pad", "000000"))) for p in m.get("patterns", [])]
        anim.materials.append(MaterialAnim(m["name"], params, pats,
                                           tuple(m.get("vis", (0xFFFF,) * 3)),
                                           bytes.fromhex(m.get("pad", "00" * 6))))
    return anim


_CTYPE = {CUBIC: "cubic", LINEAR: "linear", BAKED_FLOAT: "baked", STEP_INT: "step-int",
          BAKED_INT: "baked-int", STEP_BOOL: "step-bool", BAKED_BOOL: "baked-bool"}


def describe(anim):
    """A readable listing: materials, animated parameters, texture patterns and curves."""
    lines = [f"{anim.file_name or '(unnamed)'}: FMAA {anim.name!r}, {anim.frame_count} frames "
             f"({'loop flag' if anim.loops else 'no loop flag'}; the game always wraps), "
             f"{len(anim.materials)} material anims, {anim.curve_count} curves"]
    if anim.textures:
        lines.append("  textures: " + ", ".join(f"{i}={t}" for i, t in enumerate(anim.textures)))

    def cdesc(c):
        pts = ", ".join(f"{f:g}:{k if not isinstance(k, tuple) else '(' + ','.join(f'{x:g}' for x in k) + ')'}"
                        for f, k in list(zip(c.frames, c.keys))[:8])
        more = " ..." if len(c.frames) > 8 else ""
        sc = "" if c.is_int else f" x{c.scale:g} +{c.offset:g}"
        return (f"@{c.target:<2} {_CTYPE.get(c.curve_type, c.curve_type):<9} frames {c.start:g}..{c.end:g}"
                f" {len(c.frames)} keys{sc}  [{pts}{more}]")
    for m in anim.materials:
        lines.append(f"  material {m.name}")
        for p in m.params:
            ks = "".join(f" const@{o}=0x{v:X}" for o, v in p.constants)
            lines.append(f"    param {p.name}:{ks}")
            for c in p.curves:
                lines.append("      " + cdesc(c))
        for p in m.patterns:
            if p.curve is None:
                lines.append(f"    pattern {p.name}: constant texture {p.constant}")
            else:
                seq = []
                for f, k in zip(p.curve.frames, p.curve.keys):
                    t = anim.textures[k] if 0 <= k < len(anim.textures) else "?"
                    seq.append(f"{f:g}:{t}")
                lines.append(f"    pattern {p.name}: " + ", ".join(seq))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# UV transform
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# binding to a model
# --------------------------------------------------------------------------- #
def material_samplers(model, material_index):
    """The sampler names of a `model.Model` material in sampler-index order (the MATL
    sampler dict at +0x50, the one the pattern bind looks names up in; texture i of the
    material feeds sampler i)."""
    data = model.data
    try:
        u64 = lambda o: struct.unpack_from("<Q", data, o)[0]
        M = u64(0x28)
        m = u64(M + 0x40) + 0xB8 * material_index
        dic = u64(m + 0x50)
        if not (0 < dic < len(data)):
            return []
        cnt = struct.unpack_from("<I", data, dic + 4)[0]
        out = []
        for j in range(cnt):
            s = u64(dic + 8 + 0x10 * (j + 1) + 8)
            ln = struct.unpack_from("<H", data, s)[0]
            out.append(data[s + 2:s + 2 + ln].decode("utf-8", "replace"))
        return out
    except (struct.error, IndexError):
        return []


def material_state(model, anim, frame):
    """What the animation does to each bound material at `frame` (the frame is wrapped
    at the frame count as the game's tick does): {material index: {'uv': 2x3 matrix,
    'texture': texture name for the albedo sampler, 'opacity': float}} (keys only when
    animated). A pattern texture the model's BNTX lacks is skipped (the game asserts on
    it), so the material keeps its own texture."""
    out = {}
    if anim is None:
        return out
    frame = anim.play_frame(frame)
    names = {t["name"] for t in model.textures}
    for mt in model.materials:
        ma = anim.material(mt.name)
        if ma is None:
            continue
        st = {}
        mtx = anim.uv_matrix(mt.name, frame)
        if mtx is not None:
            st["uv"] = mtx
        op = anim.opacity(mt.name, frame)
        if op is not None:
            st["opacity"] = op
        if ma.patterns:
            samplers = material_samplers(model, mt.index)
            for smp, tex in anim.pattern_textures(mt.name, frame).items():
                slot = samplers.index(smp) if smp in samplers else None
                if slot == 0 and tex in names:          # the preview draws albedoTex0 only
                    st["texture"] = tex
        if st:
            out[mt.index] = st
    return out


def companion_stems(model_stem):
    """Candidate `.bfmat` stems for a `.model` stem, best first: the same stem, then the
    shipped files whose material names the model carries (see the module notes)."""
    import re
    s = model_stem
    out = [s]
    base = re.sub(r"_(deu|fra)$", "", s, flags=re.I)
    out.append(base)
    m = re.match(r"SYS_MENU_ANIME_(\d+)$", base, re.I)
    if m:
        out.append(f"anim_com{m.group(1)}")
    low = base.lower()
    extra = {"efc_emight": "efc_emight01", "efc_start": "font_start", "efc_finish": "font_finish",
             "mobj_pond": "MOBJ_POND", "mobj_pond_lava": "MOBJ_POND_LAVA"}
    if low in extra:
        out.append(extra[low])
    seen, res = set(), []
    for c in out:
        if c.lower() not in seen:
            seen.add(c.lower())
            res.append(c)
    return res


def companion_path(model_path):
    """The `.bfmat` for a `.model` in the same folder (same stem, or one of
    `companion_stems`), or None."""
    import pathlib
    p = pathlib.Path(model_path)
    try:
        names = {q.name.lower(): q for q in p.parent.glob("*.bfmat")}
    except OSError:
        names = {}
    for stem in companion_stems(p.stem):
        q = names.get((stem + ".bfmat").lower())
        if q is not None:
            return q
    return None


def binds(anim, model):
    """True when `anim` animates at least one of `model`'s materials."""
    names = {mt.name for mt in model.materials}
    return any(ma.name in names and (ma.params or ma.patterns) for ma in anim.materials)
