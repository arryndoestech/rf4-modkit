r"""
skelanim.py -- reader + evaluator for RF4S `.bfskl` skeletal animations (FRES / FSKA).

Despite the extension a `.bfskl` holds no skeleton: it is a FRES container around ONE nn::g3d
skeletal animation (FSKA) that binds to a `.model`'s skeleton by bone NAME. Like the `.model`
and `.bfmat` blocks, FSKA carries a 16-byte header (magic + 12 bytes), so fields sit 8 bytes
later than in the public layout. Offsets below are absolute file offsets; the game relocates
the file in place, so the same offsets are what the runtime reads (the N3D skeletal animation
object's SetResource at RF4S.exe+0x3CD060 reads FSKA +0x30 / +0x48 / +0x4C / +0x50 / +0x58).

    FRES +0x38 -> FSKA            (all 2,001 shipped files hold exactly one)
    FSKA +0x10 name   +0x18 path   +0x20 bind skeleton (0 in the file)   +0x28 -> u16 bind
         table (one per bone anim, 0xFFFF in the file; runtime cache)   +0x30 -> bone anims
         (0x28 each)   +0x38 user data   +0x40 user-data dict
         +0x48 u32 flags: bit 0 baked curves, bit 2 LOOP (SetResource passes (flags >> 2) & 1
               to the frame controller: loop wraps [0, frameCount), one-time clamps),
               bits 8-9 scale mode (1 = standard), bits 12-14 rotation mode (0 quaternion,
               1 Euler XYZ; ApplyTo RF4S.exe+0x3CC710 jumps on (flags >> 12) & 7)
         +0x4C u32 frame count   +0x50 u32 curve count (all bone anims)   +0x54 u32 baked
         size   +0x58 u16 bone-anim count   +0x5A u16 user-data count
    bone anim (0x28)  +0x00 name (the model bone it drives)  +0x08 -> curves (0x30 each, the
         matanim.py AnimCurve)  +0x10 -> base values  +0x18 u32 flags  +0x1C u8 first rotate
         curve  +0x1D u8 first translate curve  +0x1E u8 curve count  +0x1F u8 float index
         of the base translation  +0x20 u32 first curve in the anim-wide curve list
    bone-anim flags: bit 3 base scale, 4 base rotate, 5 base translate (the base block holds
         scale xyz, rotate xyzw, translate xyz in that order, each only when its bit is set);
         bits 6-8 scale xyz, 9-12 rotate xyzw, 13-15 translate xyz are animated by a curve;
         bits 23-27 are copied to the result as transform hints.

Evaluation (the N3D skeletal animation object, vslots at RF4S.exe+0x3CCDC0 / +0x3CCB50):
  * The result initialiser RF4S.exe+0x3D4350 fills each bone anim's result -- {u32 flags,
    scale xyz, translate xyz, pad, rotate xyzw} (0x30 B) -- from the base values; a
    component with no base value takes the bone's bind value (model bone +0x38 / +0x44 /
    +0x54) when Bind's init pass (RF4S.exe+0x3CAC70) passes the bound bone, identity when
    ClearResult (vslot 0) passes none.
  * Calculate (vslot 1) then samples every curve with AnimChannel_SampleAsFloat
    (RF4S.exe+0x3DF9F0, see matanim.Curve) and stores it at the curve's target byte offset
    in that result (FskaBoneAnim_EvaluateCurvesAndBase RF4S.exe+0x3D4240 / _ApplyBaseValues
    +0x3D4140): +0x04 scale, +0x10 translate, +0x20 rotate. So local SRT = base values
    overlaid with the animated channels.
  * Four Calculate variants exist, chosen by two runtime bits of the object (+0x74 bits 5-6,
    cleared by Bind RF4S.exe+0x3CC800; a byte scan of .text found no instruction that sets
    them): variant 0 (RF4S.exe+0x3CB340) is the plain overlay above and is what this module
    implements (the shipped walk / run cycles pose correctly with it, unmirrored). Variants 1-3 (+0x3CB470, +0x3CB650, Fska_EvaluateBoneAnims
    +0x3CBD30) additionally rotate the translation by a per-bone quaternion and mirror
    (negate rotate y/z and translate x) for bones whose flags lack 0x700000.
  * Bind (RF4S.exe+0x3CC800) looks every bone-anim name up in the model skeleton's bone
    dictionary (Dic_LookupNameIndex); unmatched bone anims are skipped, model bones no anim
    drives keep their bind pose.
  * Rotation: every shipped file is Euler XYZ (flag 0x1000), the same convention as the
    model's bones (model._local: R = Rz * Ry * Rx); a quaternion file would carry xyzw.
  * Timing: the frame controller (RF4S.exe+0x3C5E70) starts at frame 0 with step 1.0 and
    runs to frameCount, so one animation frame per game tick (60 ticks/s) unless the
    caller changes the step. The loop policy (RF4S.exe+0x3C5E90) wraps with floor; the
    one-time policy (+0x3C5F30) clamps. Every shipped curve is cubic, f32 frames + keys.
  * All 2,001 files are curve data (flag bit 0 never set) and loop in 678 / play once in
    1,323. ApplyTo (Euler, RF4S.exe+0x3CC610) writes scale, builds the rotation matrix
    from the Euler angles and sets the translation of each bound bone's local transform;
    the skeleton then composes world = parent * local (model.world_matrices) and the skin
    matrices (model.Model.skin_palette).

Model selection: the archive path table (RF4S.exe .rdata, 256-byte UTF-16 rows) lists the
human motion banks as rom:/mot/00/00W_*.bfskl (ids 14255..14496) and 00_*.bfskl (14497..
14738), 242 rows each in the same order, so a script motion ordinal n (1-based) is row n-1
of the actor's bank (op 289's ordinal 240 -> 00_470_dakko.bfskl). Monsters use rom:/mons/
<skeleton stem>_NN.bfskl, where the skeleton stem comes from refdata/char_models.json
('skeleton', e.g. M24_3 plays M24_0_*).
"""
from __future__ import annotations

import json
import math
import pathlib
import struct
from dataclasses import dataclass, field

from .matanim import Curve, MatAnimError, _curve


class SkelAnimError(Exception):
    pass


# bone-anim flags
BASE_SCALE, BASE_ROTATE, BASE_TRANSLATE = 0x08, 0x10, 0x20
CURVE_SCALE, CURVE_ROTATE, CURVE_TRANSLATE = 0x1C0, 0x1E00, 0xE000
# FSKA flags
FLAG_BAKED, FLAG_LOOP = 0x1, 0x4
ROT_QUATERNION, ROT_EULER_XYZ = 0, 1

# curve target byte offset in the 0x30-byte result -> (component, index)
_TARGETS = {0x04: ("s", 0), 0x08: ("s", 1), 0x0C: ("s", 2),
            0x10: ("t", 0), 0x14: ("t", 1), 0x18: ("t", 2),
            0x20: ("r", 0), 0x24: ("r", 1), 0x28: ("r", 2), 0x2C: ("r", 3)}


@dataclass
class BoneAnim:
    index: int
    name: str
    flags: int
    base_scale: tuple | None
    base_rotate: tuple | None        # 4 floats (Euler xyz + unused w, or a quaternion)
    base_translate: tuple | None
    curves: list                     # matanim.Curve, .target = byte offset in the result
    first_rotate: int = 0
    first_translate: int = 0
    first_curve: int = 0

    def animated(self):
        """'s', 'r', 't' letters of the channels a curve drives."""
        return "".join(sorted({_TARGETS.get(c.target, ("?", 0))[0] for c in self.curves}))

    def srt(self, frame, bind=None):
        """(scale xyz, rotate xyz[w], translate xyz) at `frame`: base values overlaid by the
        curves; components with no base value come from `bind` (a model.Bone) or identity."""
        s = list(self.base_scale or (bind.scale if bind is not None else (1.0, 1.0, 1.0)))
        if self.base_rotate is not None:
            r = list(self.base_rotate)
        elif bind is not None:
            r = list(bind.rotation) + [1.0] * (4 - len(bind.rotation))
        else:
            r = [0.0, 0.0, 0.0, 1.0]
        t = list(self.base_translate or (bind.translation if bind is not None else (0.0, 0.0, 0.0)))
        comp = {"s": s, "r": r, "t": t}
        for c in self.curves:
            k = _TARGETS.get(c.target)
            if k:
                comp[k[0]][k[1]] = c.evaluate(frame)
        return tuple(s), tuple(r), tuple(t)


@dataclass
class SkelAnimFile:
    name: str
    path: str
    flags: int
    frame_count: int
    curve_count: int
    baked_size: int
    bones: list = field(default_factory=list)
    data: bytes = field(repr=False, default=b"")
    file_name: str = ""                                       # FRES +0x20 (the file's stem)
    strings: list = field(default_factory=list)               # string-pool order (kept on rebuild)

    @property
    def loops(self):
        return bool(self.flags & FLAG_LOOP)

    @property
    def baked(self):
        return bool(self.flags & FLAG_BAKED)

    @property
    def rotation_mode(self):
        return (self.flags >> 12) & 7

    @property
    def euler(self):
        return self.rotation_mode == ROT_EULER_XYZ

    @property
    def scale_mode(self):
        return (self.flags >> 8) & 3

    def bone(self, name):
        for b in self.bones:
            if b.name == name:
                return b
        return None

    def wrap(self, frame):
        """The frame the game's frame controller would show: loop wraps [0, frameCount),
        one-time clamps to [0, frameCount]."""
        n = float(self.frame_count)
        if n <= 0:
            return 0.0
        if self.loops:
            return frame - math.floor(frame / n) * n
        return min(max(frame, 0.0), n)

    def local_srt(self, bone_name, frame, bind=None):
        b = self.bone(bone_name)
        return b.srt(self.wrap(frame), bind) if b else None


def parse(data):
    if data[:4] != b"FRES":
        raise SkelAnimError("not a FRES file")
    n = len(data)
    u8 = lambda o: data[o]
    u16 = lambda o: struct.unpack_from("<H", data, o)[0]
    u32 = lambda o: struct.unpack_from("<I", data, o)[0]
    u64 = lambda o: struct.unpack_from("<Q", data, o)[0]

    def name(off):
        return data[off + 2:off + 2 + u16(off)].decode("utf-8", "replace") if 0 < off < n - 2 else ""

    a = u64(0x38)
    if not 0 < a < n - 0x60 or data[a:a + 4] != b"FSKA":
        a = data.find(b"FSKA")
        if a < 0:
            raise SkelAnimError("no FSKA (skeletal animation) block")
    flags = u32(a + 0x48)
    out = SkelAnimFile(name(u64(a + 0x10)), name(u64(a + 0x18)), flags, u32(a + 0x4C),
                       u32(a + 0x50), u32(a + 0x54), data=data)
    arr = u64(a + 0x30)
    for i in range(u16(a + 0x58)):
        o = arr + 0x28 * i
        bf = u32(o + 0x18)
        ncurve = u8(o + 0x1E)
        base = u64(o + 0x10)
        vals = []
        if base:
            k = 3 * bool(bf & BASE_SCALE) + 4 * bool(bf & BASE_ROTATE) + 3 * bool(bf & BASE_TRANSLATE)
            vals = list(struct.unpack_from("<%df" % k, data, base))
        p = 0
        bs = br = bt = None
        if bf & BASE_SCALE:
            bs, p = tuple(vals[p:p + 3]), p + 3
        if bf & BASE_ROTATE:
            br, p = tuple(vals[p:p + 4]), p + 4
        if bf & BASE_TRANSLATE:
            bt = tuple(vals[p:p + 3])
        try:
            curves = [_curve(data, u64(o + 8) + 0x30 * j) for j in range(ncurve)]
        except (MatAnimError, struct.error) as e:
            raise SkelAnimError(f"bone anim {i}: {e}") from None
        out.bones.append(BoneAnim(i, name(u64(o)), bf, bs, br, bt, curves,
                                  u8(o + 0x1C), u8(o + 0x1D), u32(o + 0x20)))
    out.file_name = name(u64(0x20))
    st = a + u32(a + 4)                       # FSKA +0x04 = the distance to the string pool
    if not (0 < st < n - 0x14 and data[st:st + 4] == b"_STR"):
        st = data.find(b"_STR")
    if st >= 0:
        cnt, o, strs = u32(st + 0x10), st + 0x14, []
        for _ in range(cnt + 1):
            ln = u16(o)
            strs.append(data[o + 2:o + 2 + ln].decode("utf-8", "replace"))
            o += 2 + ln + 1
            o += o & 1
        out.strings = strs[1:]
    return out


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #
FRES_VERSION = bytes.fromhex("01020800fffe0300")      # every shipped .bfskl


def build(anim):
    """Encode a SkelAnimFile as .bfskl bytes in the shipped layout (a parsed shipped file
    comes back byte for byte -- verified on all 2,001, selftest test_skelanim_write):

        FRES header (0xD0): +0x10 u32 -> file-name chars, +0x16 u16 0xD0, +0x18 u32 _RLT,
            +0x1C u32 size, +0x20 -> file name, +0x38 -> FSKA, +0x40 -> FSKA dict,
            +0xB0 -> "", +0xB8 u32 pool size, +0xBE u16 FSKA count (1)
        FSKA (0x60): +0x04 / +0x08 u32 distance to _STR, +0x10 name, +0x18 path, +0x28 ->
            bind table, +0x30 -> bone anims, +0x48 flags, +0x4C frames, +0x50 curves,
            +0x54 baked size, +0x58 u16 bone anims
        a one-entry name dict, the u16 bind table (0xFFFF), the bone anims (0x28 each:
            name, -> curves, -> base values, flags, u8 3S / 3S+3R / curves / 3S+4R -- the
            float index of the base rotate / translate --, u32 first curve), then per bone its
            base values, curve records (0x30, as .bfmat) and each curve's frames and keys
            (8-aligned), the _STR pool and the _RLT (the .bfmat writer's parts)."""
    from . import matanim as _ma
    for b in anim.bones:
        for c in b.curves:
            if not _ma._fits(c):
                c.flags &= ~3                       # promote the frames to f32
    w = _ma._Writer()
    regions = {}
    fname = anim.file_name or anim.name
    used = [fname, anim.name, anim.path] + [b.name for b in anim.bones]
    seen, order = set(), []
    used_set = set(used)
    for s in list(anim.strings) + used:
        if s and s in used_set and s not in seen:
            seen.add(s)
            order.append(s)
    # --- FRES header ---
    w.raw(b"FRES    " + FRES_VERSION)
    w.raw(b"\0" * 16)                                # +0x10..+0x1F patched at the end
    for k in range(19):                              # +0x20..+0xB0: 19 pointer slots
        w.ptr({0: ("str", fname), 3: "fska", 4: "fdict", 18: ("str", "")}.get(k))
    w.raw(b"\0" * 8)                                 # +0xB8 pool size (patched), +0xBE count
    w.raw(b"\0" * 16)
    struct.pack_into("<H", w.buf, 0xBE, 1)
    # --- FSKA ---
    regions["fska"] = fska = w.at()
    w.raw(b"FSKA" + b"\0" * 12)                      # +0x04 / +0x08 patched
    w.ptr(("str", anim.name))
    w.ptr(("str", anim.path))
    w.ptr(None)                                      # bind skeleton (runtime)
    w.ptr("bind")
    w.ptr("bones")
    w.ptr(None)                                      # user data
    w.ptr(None)                                      # user-data dict
    all_curves = [c for b in anim.bones for c in b.curves]
    baked = sum(_ma._baked_size(c) for c in all_curves)
    w.raw(struct.pack("<IIIIHHI", anim.flags, int(anim.frame_count), len(all_curves), baked,
                      len(anim.bones), 0, 0))
    # --- FSKA dict (one entry) ---
    regions["fdict"] = w.at()
    w.raw(struct.pack("<II", 0, 1))
    w.raw(struct.pack("<IHH", 0xFFFFFFFF, 1, 0))
    w.ptr(("str", ""))
    w.raw(struct.pack("<IHH", _ma._dict_bit(anim.name), 0, 1))
    w.ptr(("str", anim.name))
    # --- bind table, bone anims ---
    regions["bind"] = w.at()
    w.raw(b"\xff\xff" * len(anim.bones))
    w.pad()
    regions["bones"] = w.at()
    first = 0
    for i, b in enumerate(anim.bones):
        S, R = bool(b.flags & BASE_SCALE), bool(b.flags & BASE_ROTATE)
        w.ptr(("str", b.name))
        w.ptr(("curves", i) if b.curves else None)
        w.ptr(("base", i) if b.flags & (BASE_SCALE | BASE_ROTATE | BASE_TRANSLATE) else None)
        w.raw(struct.pack("<IBBBBII", b.flags, 3 * S, 3 * S + 3 * R, len(b.curves), 3 * S + 4 * R,
                          first, 0))
        first += len(b.curves)
    # --- per bone: base values, curve records, frames + keys ---
    for i, b in enumerate(anim.bones):
        vals = []
        if b.flags & BASE_SCALE:
            vals += list(b.base_scale)
        if b.flags & BASE_ROTATE:
            vals += list(b.base_rotate)
        if b.flags & BASE_TRANSLATE:
            vals += list(b.base_translate)
        if vals:
            w.pad()
            regions[("base", i)] = w.at()
            w.raw(struct.pack("<%df" % len(vals), *vals))
        if b.curves:
            w.pad()
            regions[("curves", i)] = w.at()
            for j, c in enumerate(b.curves):
                w.ptr(("frames", i, j))
                w.ptr(("keys", i, j))
                w.raw(struct.pack("<HHI", c.flags, len(c.frames), c.target))
                w.raw(struct.pack("<ff", c.start, c.end))
                w.raw(struct.pack("<fffI", c.scale, c.offset, c.delta, c.pad))
            for j, c in enumerate(b.curves):
                w.pad()
                regions[("frames", i, j)] = w.at()
                w.raw(_ma._encode_frames(c))
                w.pad()
                regions[("keys", i, j)] = w.at()
                w.raw(_ma._encode_keys(c))
    # --- string pool ---
    w.pad()
    st = w.at()
    w.raw(b"_STR" + b"\0" * 12 + struct.pack("<I", len(order)))
    sref = {"": w.at()}
    w.raw(b"\0\0\0\0")
    for s in order:
        sref[s] = w.at()
        bb = s.encode("utf-8")
        w.raw(struct.pack("<H", len(bb)) + bb + b"\0")
        w.pad(2)
    str_end = w.at()
    w.pad()
    rlt = w.at()
    for slot, tgt in w.ptrs:
        if tgt is None:
            continue
        v = sref[tgt[1]] if isinstance(tgt, tuple) and tgt[0] == "str" else regions[tgt]
        struct.pack_into("<Q", w.buf, slot, v)
    struct.pack_into("<Q", w.buf, st + 8, rlt - st)
    struct.pack_into("<II", w.buf, fska + 4, st - fska, st - fska)
    struct.pack_into("<I", w.buf, 0xB8, str_end - st)
    # --- relocation table ---
    ents = _ma._rlt_entries(w.slots)
    w.raw(b"_RLT" + struct.pack("<III", rlt, 5, 0))
    w.raw(struct.pack("<QIIII", 0, 0, str_end, 0, len(ents)))
    for _ in range(4):
        w.raw(struct.pack("<QIIII", 0, str_end, 0, len(ents), 0))
    for pos, sc, oc, pc in ents:
        w.raw(struct.pack("<IHBB", pos, sc, oc, pc))
    struct.pack_into("<IHHII", w.buf, 0x10, sref[fname] + 2, 0, 0xD0, rlt, len(w.buf))
    return bytes(w.buf)


def save(anim, path):
    with open(path, "wb") as fh:
        fh.write(build(anim))


def load(path):
    with open(path, "rb") as fh:
        return parse(fh.read())


# --------------------------------------------------------------------------- #
# posing a model.Model
# --------------------------------------------------------------------------- #
def pose_bones(model, anim, frame):
    """[model.Bone] of `model` posed at `frame`: bones the animation drives (by name) take the
    animated local SRT, the rest keep their bind pose."""
    from . import model as _m
    frame = anim.wrap(frame)
    out = []
    for b in model.bones:
        ba = anim.bone(b.name)
        if ba is None:
            out.append(b)
            continue
        s, r, t = ba.srt(frame, b)
        euler = anim.euler
        out.append(_m.Bone(b.index, b.name, b.parent, s, r[:3] if euler else r[:4], t, euler))
    return out


def pose(model, anim, frame):
    """Model-space 4x4 matrices (model.py convention) of every bone at `frame`."""
    from . import model as _m
    bones = pose_bones(model, anim, frame)
    return _m.world_matrices(bones)


def bound_bones(model, anim):
    """(matched, anim-only, model-only) bone-name lists."""
    mb = {b.name for b in model.bones}
    ab = [b.name for b in anim.bones]
    return ([n for n in ab if n in mb], [n for n in ab if n not in mb],
            [b.name for b in model.bones if b.name not in set(ab)])


# --------------------------------------------------------------------------- #
# finding the animations of a model
# --------------------------------------------------------------------------- #
HUMAN_BANKS = ("00W_", "00_")        # female / male motion banks (rom:/mot/00)


def anims_for_model(model_path, *, refdata_dir=None):
    """Sorted .bfskl paths that animate `model_path` (a .model in an extracted bundle
    folder): <stem>_NN.bfskl, else the char_models.json skeleton stem's set (monster
    variants share their base form's skeleton), else for NPC_* models both human banks."""
    p = pathlib.Path(model_path)
    names = [q.name for q in p.parent.glob("*.bfskl")]
    return [p.parent / n for n in anim_candidates(p.stem, names, refdata_dir=refdata_dir)]


def anim_candidates(model_stem, names, *, refdata_dir=None):
    """The .bfskl basenames among `names` that animate a model with this stem (the rule of
    `anims_for_model`), sorted."""
    bfskl = sorted({n.rsplit("/", 1)[-1] for n in names if n.lower().endswith(".bfskl")})

    def with_prefix(pre):
        return [n for n in bfskl if n.startswith(pre) and n[len(pre):len(pre) + 1].isdigit()]
    found = with_prefix(model_stem + "_")
    if found:
        return found
    skel = _skeleton_stem(model_stem, refdata_dir)
    if skel:
        found = with_prefix(skel + "_")
        if found:
            return found
    if model_stem.upper().startswith("NPC"):
        # the two human banks, then the per-character idle / locomotion extras kept in
        # rom:/mot/01..20 and /50 (00_wait_NN, 16_walk, 50_run ...)
        out = [n for pre in HUMAN_BANKS for n in bfskl if n.startswith(pre) and n[len(pre):len(pre) + 1].isdigit()]
        return out + [n for n in bfskl if n not in out and (n.startswith("00_wait_") or n[:2].isdigit() and n[2:3] == "_" and not n.startswith("00"))]
    return []


_SKEL_CACHE = {}


def _skeleton_stem(model_stem, refdata_dir=None):
    if refdata_dir is None:
        refdata_dir = pathlib.Path(__file__).resolve().parent.parent / "refdata"
    key = str(refdata_dir)
    if key not in _SKEL_CACHE:
        m = {}
        try:
            d = json.loads((pathlib.Path(refdata_dir) / "char_models.json").read_text(encoding="utf-8"))
            for k, v in d.items():
                if isinstance(v, dict) and v.get("skeleton") and v.get("model"):
                    m.setdefault(v["model"], v["skeleton"])
        except (OSError, ValueError):
            pass
        _SKEL_CACHE[key] = m
    sk = _SKEL_CACHE[key].get(model_stem)
    if not sk:
        return None
    s = pathlib.Path(sk).stem
    return s.rsplit("_", 1)[0] if "_" in s and s.rsplit("_", 1)[1].isdigit() else s


# --------------------------------------------------------------------------- #
# dumping
# --------------------------------------------------------------------------- #
def summary(anim):
    rot = {0: "quaternion", 1: "euler XYZ"}.get(anim.rotation_mode, f"mode {anim.rotation_mode}")
    lines = [f"{anim.name}: {anim.frame_count} frames, {'loop' if anim.loops else 'one-time'}, "
             f"{rot}, scale mode {anim.scale_mode}, {'baked' if anim.baked else 'curves'}, "
             f"{len(anim.bones)} bone anims, {anim.curve_count} curves"]
    for b in anim.bones:
        base = "".join(ch for ch, bit in (("S", BASE_SCALE), ("R", BASE_ROTATE), ("T", BASE_TRANSLATE))
                       if b.flags & bit)
        lines.append(f"  {b.index:3} {b.name:<24} base {base or '-':<3} curves {len(b.curves):2} "
                     f"({b.animated() or '-'})")
    return "\n".join(lines)


def to_json(anim):
    def curve(c):
        return {"target": c.target, "flags": c.flags, "start": c.start, "end": c.end,
                "scale": c.scale, "offset": c.offset, "delta": c.delta,
                "frames": c.frames, "keys": [list(k) if isinstance(k, tuple) else k for k in c.keys]}
    return {"name": anim.name, "path": anim.path, "flags": anim.flags,
            "frame_count": anim.frame_count, "loop": anim.loops, "euler": anim.euler,
            "bones": [{"name": b.name, "flags": b.flags, "base_scale": b.base_scale,
                       "base_rotate": b.base_rotate, "base_translate": b.base_translate,
                       "curves": [curve(c) for c in b.curves]} for b in anim.bones]}
