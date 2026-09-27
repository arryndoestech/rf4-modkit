r"""
modelgrow.py -- NEW shapes in an RF4S `.model` (the structures around the memory pool grow).

`add_shapes(data, [NewShape(name, template, ...)])` returns a model with extra shapes appended
after the existing ones, each a clone of a template shape's records -- same vertex format,
skin type, bone and (unless another existing one is picked) material -- whose geometry is then
filled like any other shape (modelwrite.rebuild; meshimport.import_glb(new=...) does both).
Existing shapes keep their numbers and every byte of their records.

How the file grows (read from RF4S.exe with IDA, read-only, and the shipped files, 2026-09-27):

  Where the loader finds shapes. MESH+0x30 -> SHAP[] (0x70 each) and MESH+0x28 -> VRTX[] (0x60
  each) are indexed by count (MESH+0x6A shapes, +0x68 vertex buffers: ResModel setup
  RF4S.exe+0x3D46C0 walks both arrays, GfxCTR_Model_AllocAndBuildModelObj +0x1C0130 sizes the
  model object from the counts). Across the 912 mesh files nothing else points INTO those arrays
  but SHAP+0x18 (its VRTX) -- so both arrays are rebuilt, bigger, in new space and MESH+0x28 /
  +0x30 repointed; the old arrays stay behind as unused bytes (still relocated, never read).
  SHAP+0x5C / VRTX+0x56 hold the element's own index, SHAP+0x62 its VRTX index.
  MESH+0x38 -> the shape-name dictionary (_DIC: {u32 0, s32 count} + (count + 1) nodes {s32
  bit, u16 left, u16 right, u64 -> name}); `build_dict` is the patricia-tree builder that
  regenerates all 13,840 dictionaries of the shipped files byte for byte.

  What the loader WRITES into a shape's records (so a clone may not share them): the shape
  setup (+0x3E00B0) initialises, per mesh, the buffer object at mesh+0x10 (56 bytes, first
  byte = state; +0x3CDF00 -> GfxBuffer_InitStorage +0x3C4C40) and the u32 at mesh+0x18 -> [+8];
  the vertex setup (+0x3DFF00) writes, per buffer b, VRTX+0x30 -> [8 b] = VRTX+0x28 -> + 56 b
  (the buffer objects) and VRTX+0x38 -> [0x10 b + 8]. The model object keeps a pointer at
  SHAP+0x50 (0 in every shipped file, filled at run time). A clone gets its own zeroed copies
  of all of these (0x48 bytes per buffer object, as the shipped files lay them out) and its own
  size records, submesh table, bounds and used-bone list; the attribute array / dictionary and
  stride records are read-only and shared with the template. VRTX+0x20 / mesh+0x08 point at the
  memory-pool object at the start of relocation section 3, the same for every VRTX and mesh.

  At most 32 shapes: GfxCTR_Model_BuildFromResource (+0x1B52C0) copies each shape's DrawOrder /
  BlendType / CombineType / CombineColor00 into fixed 32-entry arrays of the model object
  (+540 / +668 / +796 / +924) with no bound check. Shipped maximum: 22.

  Room. The new records are appended at the pool start P (0x1000-aligned in every shipped file)
  and P moves up by whole 0x1000 pages: every relocated pointer at or past P moves with it, as
  do the section positions, the file size and the _RLT offset (the same bookkeeping
  modelwrite.rebuild does for the pool end). The _RLT keeps all its entries and gets new ones
  (one per run of consecutive pointer slots) for the pointers inside the new records, filed
  under the section their targets lie in; BFRES_FixupRelocationPointers (+0x3CAA00) adds the
  same base to every listed slot whatever its section.

Statically verified only (no in-game test): the relocation walk, model.parse / modelwrite
layout / validate, renders, the dictionary builder against every shipped dictionary.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from . import model as _model
from . import modelwrite as _mw

MAX_SHAPES = 32
PAGE = 0x1000
_OBJ = 0x48                   # a runtime buffer object's slot, as laid out in the shipped files


class ModelGrowError(Exception):
    pass


# --------------------------------------------------------------------------- #
# _DIC
# --------------------------------------------------------------------------- #
def _bit(key, i):
    k = i >> 3
    if k >= len(key):
        return 0
    return (key[len(key) - 1 - k] >> (i & 7)) & 1


def _first_diff(a, b):
    for i in range(max(len(a), len(b)) * 8):
        if _bit(a, i) != _bit(b, i):
            return i
    return -1


def build_dict(keys):
    """Nodes [(bit, left, right, key bytes)] of the dictionary of `keys` (node 0 = the root,
    bit -1), in the order the shipped files store them."""
    nodes = [[-1, 0, 0, b""]]
    for key in keys:
        prev, cur = nodes[0], nodes[nodes[0][1]]
        while prev[0] < cur[0]:
            prev = cur
            cur = nodes[cur[2]] if _bit(key, cur[0]) else nodes[cur[1]]
        b = _first_diff(key, cur[3])
        if b < 0:
            raise ModelGrowError(f"duplicate name {key!r}")
        pi, ci = 0, nodes[0][1]
        while nodes[pi][0] < nodes[ci][0] and nodes[ci][0] < b:
            pi = ci
            ci = nodes[ci][2] if _bit(key, nodes[ci][0]) else nodes[ci][1]
        ni = len(nodes)
        node = [b, ci, ni, key] if _bit(key, b) else [b, ni, ci, key]
        nodes.append(node)
        if pi != 0 and _bit(key, nodes[pi][0]):
            nodes[pi][2] = ni
        else:
            nodes[pi][1] = ni
    return [tuple(n) for n in nodes]


def read_dict(data, off):
    """Nodes of the dictionary at `off`, as build_dict returns them."""
    _magic, count = struct.unpack_from("<Ii", data, off)
    out = []
    for i in range(count + 1):
        ref, left, right, kp = struct.unpack_from("<iHHQ", data, off + 8 + 16 * i)
        key = bytes(data[kp + 2:kp + 2 + _mw._u16(data, kp)]) if kp else b""
        out.append((ref, left, right, key))
    return out


# --------------------------------------------------------------------------- #
# growing
# --------------------------------------------------------------------------- #
@dataclass
class NewShape:
    name: str
    template: int               # shape whose records are cloned
    material: int | None = None     # existing material index (default: the template's)
    bone: int | None = None         # shape bone for a rigid clone (default: the template's)


class _Ext:
    """The block appended at the old pool start; pointers recorded for relocation."""

    def __init__(self, base):
        self.base = base
        self.buf = bytearray()
        self.ptrs = []          # [(absolute slot, absolute target, target is old-and-past-P)]

    def put(self, blob, align=8):
        while len(self.buf) % align:
            self.buf.append(0)
        at = self.base + len(self.buf)
        self.buf += blob
        return at

    def ptr(self, slot, target, high=False):
        struct.pack_into("<Q", self.buf, slot - self.base, target)
        self.ptrs.append((slot, target, high))


def _string(name):
    raw = name.encode("utf-8")
    return struct.pack("<H", len(raw)) + raw + b"\0"


def add_shapes(data, news):
    """New file bytes with `news` ([NewShape]) appended as shapes n, n+1, ... (see the module
    notes). Their geometry is a copy of the template's until replaced (modelwrite.rebuild /
    meshimport.shape_geometry_from_mesh)."""
    m = _model.parse(data, decode_vertices=False)
    L = _mw.layout(data)
    if not news:
        return bytes(data)
    n_sh, n_vb = len(m.shapes), len(m.vertex_buffers)
    if n_sh + len(news) > MAX_SHAPES:
        raise ModelGrowError(f"{n_sh} + {len(news)} shapes: the game keeps at most {MAX_SHAPES} per model")
    names = [sh.name for sh in m.shapes]
    for ns in news:
        if not ns.name or ns.name in names:
            raise ModelGrowError(f"shape name {ns.name!r} is empty or already used")
        names.append(ns.name)
        if not 0 <= ns.template < n_sh:
            raise ModelGrowError(f"template shape {ns.template} out of range")
        if ns.material is not None and not 0 <= ns.material < len(m.materials):
            raise ModelGrowError(f"material {ns.material} out of range")
        if ns.bone is not None and not 0 <= ns.bone < len(m.bones):
            raise ModelGrowError(f"bone {ns.bone} out of range")
    u64 = lambda o: _mw._u64(data, o)
    u16 = lambda o: _mw._u16(data, o)
    P = L.pool
    M = u64(0x28)
    old_v, old_s = u64(M + 0x28), u64(M + 0x30)
    x = _Ext(P)

    def copy_ptrs(dst, src, size):
        """Record the relocated pointers of a copied block (the source block's non-zero u64
        slots the _RLT lists)."""
        for so in range(0, size, 8):
            if src + so in slotset:
                t = u64(src + so)
                x.ptrs.append((dst + so, t, t >= P))
    slotset = {s for s, _t in _mw.relocation_slots(data)}

    # ---- per new shape: its own records
    made = []
    for j, ns in enumerate(news):
        t = L.shapes[ns.template]
        tv, tm = t.vrtx, t.mesh
        nbuf = data[tv + 0x55]
        name_at = x.put(_string(ns.name), 2)
        # VRTX clone
        objs = x.put(b"\0" * (_OBJ * nbuf))
        ptrarr = x.put(b"\0" * (8 * nbuf))
        size_at = x.put(bytes(data[u64(tv + 0x38):u64(tv + 0x38) + 0x10 * nbuf]))
        stride_at = x.put(bytes(data[u64(tv + 0x40):u64(tv + 0x40) + 0x10 * nbuf]))
        # mesh clone
        nsub = u16(tm + 0x34)
        sub_at = x.put(bytes(data[u64(tm):u64(tm) + 8 * nsub]))
        mobj = x.put(b"\0" * _OBJ)
        isize = x.put(bytes(data[u64(tm + 0x18):u64(tm + 0x18) + 0x10]))
        mesh_at = x.put(bytes(data[tm:tm + 0x38]))
        for so in range(0, 0x38, 8):
            if tm + so in slotset:
                tgt = u64(tm + so)
                new = {0x00: sub_at, 0x10: mobj, 0x18: isize}.get(so)
                if new is None:
                    x.ptr(mesh_at + so, tgt, tgt >= P)       # the pool object
                else:
                    x.ptr(mesh_at + so, new)
        s = t.shap
        bbox_at = x.put(bytes(data[u64(s + 0x40):u64(s + 0x40) + 0x18 * (1 + nsub)]))
        rad_at = x.put(bytes(data[u64(s + 0x48):u64(s + 0x48) + 4]))
        nsb = u16(s + 0x64)
        sb_at = x.put(bytes(data[u64(s + 0x28):u64(s + 0x28) + 2 * nsb]) if nsb and u64(s + 0x28) else b"")
        made.append((ns, t, name_at, objs, ptrarr, size_at, stride_at, mesh_at, bbox_at, rad_at, sb_at, nsb))

    # ---- the new VRTX array: old ones copied, then the clones
    varr = x.put(b"\0" * (0x60 * (n_vb + len(news))))
    for i in range(n_vb):
        src = old_v + 0x60 * i
        x.buf[varr - P + 0x60 * i:varr - P + 0x60 * (i + 1)] = data[src:src + 0x60]
        copy_ptrs(varr + 0x60 * i, src, 0x60)
    for j, (ns, t, name_at, objs, ptrarr, size_at, stride_at, *_r) in enumerate(made):
        dst, src = varr + 0x60 * (n_vb + j), t.vrtx
        x.buf[dst - P:dst - P + 0x60] = data[src:src + 0x60]
        for so in range(0, 0x60, 8):
            if src + so in slotset:
                tgt = u64(src + so)
                new = {0x28: objs, 0x30: ptrarr, 0x38: size_at, 0x40: stride_at}.get(so)
                if new is None:
                    x.ptr(dst + so, tgt, tgt >= P)           # attributes, their dictionary, the pool object
                else:
                    x.ptr(dst + so, new)
        struct.pack_into("<H", x.buf, dst - P + 0x56, n_vb + j)

    # ---- the new SHAP array
    sarr = x.put(b"\0" * (0x70 * (n_sh + len(news))))
    for i in range(n_sh):
        src = old_s + 0x70 * i
        dst = sarr + 0x70 * i
        x.buf[dst - P:dst - P + 0x70] = data[src:src + 0x70]
        for so in range(0, 0x70, 8):
            if src + so in slotset:
                tgt = u64(src + so)
                if so == 0x18:                               # its VRTX, in the new array
                    tgt = varr + (tgt - old_v)
                    x.ptr(dst + so, tgt)
                else:
                    x.ptr(dst + so, tgt, tgt >= P)
    for j, (ns, t, name_at, objs, ptrarr, size_at, stride_at, mesh_at, bbox_at, rad_at, sb_at, nsb) in enumerate(made):
        src, dst = t.shap, sarr + 0x70 * (n_sh + j)
        x.buf[dst - P:dst - P + 0x70] = data[src:src + 0x70]
        for so in range(0, 0x70, 8):
            if src + so in slotset:
                tgt = u64(src + so)
                new = {0x10: name_at, 0x18: varr + 0x60 * (n_vb + j), 0x20: mesh_at,
                       0x28: sb_at if nsb else None, 0x40: bbox_at, 0x48: rad_at}.get(so)
                if new is None:
                    x.ptr(dst + so, tgt, tgt >= P)
                else:
                    x.ptr(dst + so, new)
        struct.pack_into("<H", x.buf, dst - P + 0x5C, n_sh + j)
        struct.pack_into("<H", x.buf, dst - P + 0x62, n_vb + j)
        if ns.material is not None:
            struct.pack_into("<H", x.buf, dst - P + 0x5E, ns.material)
        if ns.bone is not None:
            struct.pack_into("<H", x.buf, dst - P + 0x60, ns.bone)

    # ---- the shape dictionary
    old_dict = u64(M + 0x38)
    key_at = {}
    for i, nd in enumerate(read_dict(data, old_dict)):
        if i:
            key_at[nd[3]] = u64(old_dict + 8 + 16 * i + 8)
    for ns, _t, name_at, *_r in made:
        key_at[ns.name.encode("utf-8")] = name_at
    keys = [n.encode("utf-8") for n in names]
    nodes = build_dict(keys)
    dic = bytearray(struct.pack("<Ii", _mw._u32(data, old_dict), len(keys)))
    for ref, left, right, _k in nodes:
        dic += struct.pack("<iHHQ", ref, left, right, 0)
    dict_at = x.put(bytes(dic))
    root_key = u64(old_dict + 8 + 8)                         # the root's (empty) name
    x.ptr(dict_at + 8 + 8, root_key, root_key >= P)
    for i, (_ref, _l, _r, k) in enumerate(nodes):
        if i:
            x.ptr(dict_at + 8 + 16 * i + 8, key_at[k])

    # ---- place the block: P moves up by whole pages
    while len(x.buf) % 8:
        x.buf.append(0)
    delta = _mw._align(len(x.buf), PAGE)
    x.buf += b"\0" * (delta - len(x.buf))
    rlt, secs = _mw._sections(data)
    out = bytearray(data[:P]) + x.buf + bytearray(data[P:rlt])
    # existing pointers past P move
    for sl, tgt in _mw.relocation_slots(data):
        if tgt >= P:
            struct.pack_into("<Q", out, sl, tgt + delta)
    for sl, tgt, high in x.ptrs:
        struct.pack_into("<Q", out, sl, tgt + delta if high else tgt)
    # MESH: arrays, dictionary, counts
    struct.pack_into("<Q", out, M + 0x28, varr)
    struct.pack_into("<Q", out, M + 0x30, sarr)
    struct.pack_into("<Q", out, M + 0x38, dict_at)
    struct.pack_into("<H", out, M + 0x68, n_vb + len(news))
    struct.pack_into("<H", out, M + 0x6A, n_sh + len(news))

    # ---- the _RLT: old entries kept, new ones per run of consecutive slots
    nsec = len(secs)
    entries0 = rlt + _mw._RLT_HDR + _mw._RLT_SEC * nsec
    old_entries = [[] for _ in range(nsec)]
    for si, sec in enumerate(secs):
        first, count = sec[3], sec[4]
        for e in range(first, first + count):
            old_entries[si].append(bytes(data[entries0 + 8 * e:entries0 + 8 * e + 8]))
    new_pos = [0] + [sec[1] + delta for sec in secs[1:]]
    new_size = [x.base + len(x.buf)] + [sec[2] for sec in secs[1:]]     # section 0 = the whole main block
    bounds = [(new_pos[i], new_pos[i] + new_size[i]) for i in range(nsec)]

    def section_of(target):
        for i, (a, b) in enumerate(bounds):
            if a <= target < b:
                return i
        return 0
    runs = [[] for _ in range(nsec)]
    for sl, tgt, high in sorted(x.ptrs):
        final = tgt + delta if high else tgt
        if final == 0:
            continue
        si = section_of(final)
        r = runs[si]
        if r and r[-1][0] + 8 * r[-1][1] == sl and r[-1][1] < 255:
            r[-1][1] += 1
        else:
            r.append([sl, 1])
    hdr = bytearray(data[rlt:rlt + _mw._RLT_HDR])
    new_rlt = len(out)
    struct.pack_into("<I", hdr, 4, (_mw._u32(data, rlt + 4) & 0x80000000) | new_rlt)
    sec_blob, ent_blob = bytearray(), bytearray()
    n_ent = 0
    for si, sec in enumerate(secs):
        ents = old_entries[si] + [struct.pack("<IHBB", sl, 1, cnt, 0) for sl, cnt in runs[si]]
        sec_blob += struct.pack("<QIIII", sec[0], new_pos[si], new_size[si], n_ent, len(ents))
        ent_blob += b"".join(ents)
        n_ent += len(ents)
    out += hdr + sec_blob + ent_blob
    struct.pack_into("<I", out, 0x0C, len(out))
    struct.pack_into("<I", out, 0x1C, len(out))
    struct.pack_into("<I", out, 0x10, new_rlt)
    # give the clones their own copy of the template's buffers in the pool
    return _mw.rebuild(bytes(out))
