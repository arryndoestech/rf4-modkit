r"""
modelwrite.py -- geometry WRITER for RF4S `.model` files (companion of model.py, which reads them).

Two edits:
  * `transform_shape`  -- move / scale / rotate the vertices of one shape in place. Counts stay
    the same; only that shape's position / normal bytes and its bounding box / radius change.
  * `import_obj`       -- replace one shape's geometry from a Wavefront OBJ (the format
    model.to_obj exports) with ANY vertex / index count. The memory pool is rebuilt and
    everything that depends on its size moves with it.
Both go through `rebuild`, which with no changes reproduces every shipped mesh .model byte for
byte (verified on all 912, selftest test_model_import).

What the loader needs (read 2026-09-24 by OFFLINE disassembly of RF4S.exe on disk -- the IDA
session was unavailable, so the RVAs without a name below are unnamed there; the file side
checked on all 912 mesh .model files):

  Relocation. GfxCTR_Model_BuildFromResource (RF4S.exe+0x1B52C0) calls
  BFRES_EnsureRelocationFixed (+0x3CD5D0) -> BFRES_GetRelocationTableStart (+0x3CA9B0: 'R'
  magic -> u32 at +0x10) -> BFRES_FixupRelocationPointers (+0x3CAA00). That adds ONE base
  (`RLT - RLT[+4]`) to every non-zero u64 slot the entries list and asserts each slot lies
  before the table. Section positions / sizes are never read. So after moving data, every
  slot that points at moved data must be rewritten, and every slot must stay below the _RLT.

  File layout (the five _RLT sections, identical in every shipped file):
      [0, P)            main block (RES header, MESH, VRTX, SHAP, SKEL, MATL, strings)
      [P, P+s1)         section 1: all index buffers, shape order, each 8-aligned
      [P+s1, T)         section 2: all vertex buffers, VRTX order, each 8-aligned, padded
                        so that T (the end of the pool) is 0x1000-aligned
      [T, T+0x120..)    section 3: zero-filled runtime memory (nn::gfx MemoryPool objects)
      [.., RLT)         section 4: the embedded files (BNTX textures, FSHA shaders), each with
                        its own _RLT and pointers RELATIVE to its own start
      [RLT, end)        the outer _RLT
  RES+0x90 -> memory-pool info {u32 property 0x22, u32 pool size = T - P, u64 -> pool} (the
  pool setup, RF4S.exe+0x3D1A10, copies all three). RES+0x98 -> embedded-file table {u64 ->
  file, u32 size}. No relocation slot lies at or past P, and nothing in the main block stores a
  non-relocated offset past the pool, so growing / shrinking the pool = shift [T, RLT) by a
  multiple of 0x1000 and add the shift to every slot whose target is >= T.

  Vertex buffers. ResVertex setup (RF4S.exe+0x3DFF00) walks VRTX+0x55 buffers from pool offset
  VRTX+0x50; buffer b's size is the u64 at VRTX+0x38 -> [b * 0x10] and the next buffer starts
  at the 8-aligned end of the previous one. The draw (Scene_SubmitDrawList +0x1B9430 ->
  RenderMesh_SubmitVertexBlob +0x3C4480) uploads `size` bytes as `size / stride` vertices
  (stride at VRTX+0x40 -> [b * 0x10]). VRTX+0x58 (vertex count) is kept equal to that.
  Attribute formats / offsets are untouched, so the attribute layout stays valid.

  Index buffers. ResMesh setup (RF4S.exe+0x3CDF00) creates the index buffer from pool offset
  mesh+0x20 with the size in the u64 at mesh+0x18 -> [0]. The draw (RF4S.exe+0x3CDDB0, called
  by Scene_SubmitDrawList with every submesh of the shape's mesh) draws
  `((sub[last].offset - sub[first].offset) >> format) + sub[last].count` indices from
  sub[first].offset, primitive mesh+0x24, format mesh+0x28 (element size 1 << format: 2 = u32,
  the only one shipped; RF4S.exe+0x3C30D0), base vertex mesh+0x30. So the SUBMESH table (mesh+0
  -> {u32 byte offset, u32 index count}[u16 at mesh+0x34]) is what sets the drawn count; mesh+0x2C
  is kept equal. Every shipped shape has 1 mesh (no LOD) with 1 submesh covering it.

  Bounds. SHAP+0x40 -> {centre xyz, half-extent xyz} x (1 shape + 1 per submesh), SHAP+0x48 ->
  radius (one float per mesh). For rigid shapes (skin 0 / 1: 2,406 shipped) the box is the AABB
  of the RAW `_p0` values (buffer space) and the radius the largest distance from its centre to
  a raw position -- both reproduced exactly. For smooth-skinned shapes (skin 2..4: 299) the
  shipped boxes do not follow from the bind-pose positions (they look like animated-pose
  bounds); for those the old box is kept and only grown to cover new positions. No bounding
  test was found on the draw path (Scene_SubmitDrawList draws every shape it is given), so the
  bounds are kept consistent rather than known to matter.

OBJ conventions (model.to_obj): `v` in MODEL space (rigid shapes moved by their bone, skin-1
vertices by the bone in `_i0`), `vn` in model space, `vt` with V flipped (vt = 1 - v).
Import maps them back: an OBJ vertex identical to an exported one keeps its original bytes
(so an unmodified export re-imports byte-identically); any other vertex copies its non-geometry
attributes (`_c0`, `_i0`, `_w0`, ...) from the NEAREST original vertex of the shape and gets
its position / normal / UV from the OBJ, taken back into that vertex's own frame (the shape's
bone for skin 0, the `_i0` bone for skin 1, model space for skin 2+). So skinning weights are
TRANSFERRED from the closest original vertex -- fine for reshaping a part, not a substitute
for real weight painting.

Verified statically only (no in-game test): the pointer walk the loader does (every slot below
the _RLT, every target inside the file), model.parse / texture.bntx_info / res_container on the
result, byte-identical no-op rebuilds, and renders of re-imported models.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

from . import model as _model


class ModelWriteError(Exception):
    pass


POOL_ALIGN = 8            # every index / vertex buffer inside the pool
POOL_END_ALIGN = 0x1000   # the pool ends (and section 3 starts) on a 4 KiB boundary
_RLT_HDR = 0x10
_RLT_SEC = 0x18


def _u16(d, o):
    return struct.unpack_from("<H", d, o)[0]


def _u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def _u64(d, o):
    return struct.unpack_from("<Q", d, o)[0]


def _align(v, a):
    return (v + a - 1) // a * a


# --------------------------------------------------------------------------- #
# relocation table
# --------------------------------------------------------------------------- #
def relocation_slots(data):
    """[(slot offset, target offset)] of every non-zero pointer the outer _RLT lists, walked
    exactly like BFRES_FixupRelocationPointers (RF4S.exe+0x3CAA00): entry = {u32 slot, u16
    struct count, u8 offset count, u8 padding count}, slot(i, j) = slot + 8 * (i + j *
    (offsets + padding)). Raises ModelWriteError where the loader would assert (a slot at or
    past the table) or a target falls outside the file."""
    n = len(data)
    rlt = _u32(data, 0x10)
    if rlt + _RLT_HDR > n or data[rlt:rlt + 4] != b"_RLT":
        raise ModelWriteError("no _RLT at the offset in RES+0x10")
    if _u32(data, rlt + 4) & 0x7FFFFFFF != rlt:
        raise ModelWriteError(f"_RLT self offset 0x{_u32(data, rlt + 4):X} != 0x{rlt:X}")
    nsec = _u32(data, rlt + 8)
    entries = rlt + _RLT_HDR + _RLT_SEC * nsec
    out = []
    for s in range(nsec):
        so = rlt + _RLT_HDR + _RLT_SEC * s
        first, count = _u32(data, so + 16), _u32(data, so + 20)
        for e in range(first, first + count):
            eo = entries + 8 * e
            if eo + 8 > n:
                raise ModelWriteError(f"_RLT entry {e} beyond the file")
            slot, nst, noff, npad = _u32(data, eo), _u16(data, eo + 4), data[eo + 6], data[eo + 7]
            for j in range(nst):
                for i in range(noff):
                    sl = slot + 8 * (i + j * (noff + npad))
                    if sl >= rlt:
                        raise ModelWriteError(f"relocation slot 0x{sl:X} not before the _RLT (0x{rlt:X})")
                    t = _u64(data, sl)
                    if t:
                        if t > n:
                            raise ModelWriteError(f"slot 0x{sl:X} points at 0x{t:X}, past the file")
                        out.append((sl, t))
    return out


def _sections(data):
    rlt = _u32(data, 0x10)
    nsec = _u32(data, rlt + 8)
    return rlt, [list(struct.unpack_from("<QIIII", data, rlt + _RLT_HDR + _RLT_SEC * s))
                 for s in range(nsec)]


# --------------------------------------------------------------------------- #
# layout
# --------------------------------------------------------------------------- #
@dataclass
class ShapeLayout:
    index: int
    shap: int                   # SHAP block offset
    vrtx: int                   # VRTX block offset
    mesh: int                   # mesh struct (0x38)
    submesh: int                # submesh table
    n_submesh: int
    bbox: int                   # bounding boxes (6 floats each)
    radius: int                 # bounding radius
    skin: int
    index_format: int
    index_offset: int           # in the pool
    index_count: int
    vertex_offset: int          # in the pool (first buffer)
    vertex_count: int
    buffers: list = field(default_factory=list)   # [(size-info offset, stride-info offset, size, stride)]


@dataclass
class Layout:
    pool: int                   # file offset of the pool (P)
    pool_info: int              # RES+0x90 target
    pool_end: int               # T = start of section 3
    rlt: int
    shapes: list
    vrtx_order: list            # VRTX offsets in VRTX-array order


def layout(data):
    """Where every pool-related field of a mesh .model lives. Refuses layouts that differ
    from the shipped one (anything this module could not rewrite safely)."""
    if not _model.is_mesh(data):
        raise ModelWriteError("not a mesh .model")
    rlt, secs = _sections(data)
    if len(secs) != 5:
        raise ModelWriteError(f"_RLT has {len(secs)} sections (every shipped .model has 5)")
    if _u16(data, 0xBC) != 1:
        raise ModelWriteError("more than one model block (the loader asserts on exactly one)")
    pinfo = _u64(data, 0x90)
    P = _u64(data, pinfo + 8)
    T = P + _u32(data, pinfo + 4)
    if not (P == secs[1][1] and secs[2][1] == P + secs[1][2] and T == secs[2][1] + secs[2][2]
            and secs[3][1] == T and T % POOL_END_ALIGN == 0):
        raise ModelWriteError("memory pool / relocation sections are not laid out as in the shipped files")
    M = _u64(data, 0x28)
    n_vb, n_sh = _u16(data, M + 0x68), _u16(data, M + 0x6A)
    vrtx = [_u64(data, M + 0x28) + 0x60 * i for i in range(n_vb)]
    shapes = []
    for i in range(n_sh):
        s = _u64(data, M + 0x30) + 0x70 * i
        if data[s:s + 4] != b"SHAP":
            raise ModelWriteError(f"shape {i}: no SHAP block")
        if data[s + 0x67] != 1:
            raise ModelWriteError(f"shape {i}: {data[s + 0x67]} meshes (LODs); only 1 is supported")
        v = _u64(data, s + 0x18)
        mesh = _u64(data, s + 0x20)
        bufs = []
        for b in range(data[v + 0x55]):
            si = _u64(data, v + 0x38) + 0x10 * b
            st = _u64(data, v + 0x40) + 0x10 * b
            bufs.append((si, st, _u64(data, si), _u32(data, st)))
        shapes.append(ShapeLayout(
            i, s, v, mesh, _u64(data, mesh), _u16(data, mesh + 0x34), _u64(data, s + 0x40),
            _u64(data, s + 0x48), data[s + 0x66], _u32(data, mesh + 0x28), _u32(data, mesh + 0x20),
            _u32(data, mesh + 0x2C), _u32(data, v + 0x50), _u32(data, v + 0x58), bufs))
    return Layout(P, pinfo, T, rlt, shapes, vrtx)


# --------------------------------------------------------------------------- #
# rebuild
# --------------------------------------------------------------------------- #
@dataclass
class ShapeGeometry:
    """New geometry for one shape: raw vertex records (the shape's own stride and attribute
    layout, one buffer) and a triangle-list index array. `bbox` = (centre, half extent) and
    `radius` override the computed bounds."""
    vertices: bytes
    indices: list
    bbox: tuple | None = None
    radius: float | None = None


def rebuild(data, geometry=None):
    """Rebuild the memory pool with `geometry` ({shape index: ShapeGeometry}) replacing those
    shapes' buffers, and fix every size / count / offset / pointer that depends on it. With no
    geometry the result equals the input byte for byte (shipped files)."""
    geometry = geometry or {}
    L = layout(data)
    P, T = L.pool, L.pool_end
    by_vrtx = {sh.vrtx: sh for sh in L.shapes}
    out = bytearray(data[:P])

    # ---- index region (section 1), shape order
    pool = bytearray()
    ioffs = {}
    for sh in L.shapes:
        pool += b"\0" * (_align(len(pool), POOL_ALIGN) - len(pool))
        ioffs[sh.index] = len(pool)
        g = geometry.get(sh.index)
        if g is None:
            esz = 1 << sh.index_format
            a = P + sh.index_offset
            pool += data[a:a + esz * sh.index_count]
        else:
            if sh.index_format != 2:
                raise ModelWriteError(f"shape {sh.index}: index format {sh.index_format} (only u32 is written)")
            pool += struct.pack("<%dI" % len(g.indices), *g.indices)
    pool += b"\0" * (_align(len(pool), POOL_ALIGN) - len(pool))
    s1 = len(pool)

    # ---- vertex region (section 2), VRTX order
    voffs = {}
    for v in L.vrtx_order:
        sh = by_vrtx.get(v)
        pool += b"\0" * (_align(len(pool), POOL_ALIGN) - len(pool))
        voffs[v] = len(pool)
        g = geometry.get(sh.index) if sh else None
        if g is None:
            off = _u32(data, v + 0x50)
            for b in range(data[v + 0x55]):
                si = _u64(data, v + 0x38) + 0x10 * b
                size = _u64(data, si)
                pool += data[P + off:P + off + size]
                off = _align(off + size, POOL_ALIGN)
                pool += b"\0" * (_align(len(pool), POOL_ALIGN) - len(pool))
        else:
            if len(sh.buffers) != 1:
                raise ModelWriteError(f"shape {sh.index}: {len(sh.buffers)} vertex buffers (only 1 is written)")
            pool += g.vertices
    pool += b"\0" * (_align(P + len(pool), POOL_END_ALIGN) - (P + len(pool)))
    new_T = P + len(pool)
    delta = new_T - T
    out += pool
    tail_start = len(out)
    out += data[T:]
    new_rlt = L.rlt + delta

    # ---- header: file sizes, _RLT offset
    struct.pack_into("<I", out, 0x0C, len(out))
    struct.pack_into("<I", out, 0x1C, len(out))
    struct.pack_into("<I", out, 0x10, new_rlt)
    struct.pack_into("<I", out, new_rlt + 4, (_u32(data, L.rlt + 4) & 0x80000000) | new_rlt)
    # memory-pool info: size
    struct.pack_into("<I", out, L.pool_info + 4, new_T - P)
    # relocation: shift every slot pointing past the pool; sections 1..4
    if delta:
        for sl, t in relocation_slots(data):
            if t >= T:
                struct.pack_into("<Q", out, sl, t + delta)
    so = new_rlt + _RLT_HDR
    struct.pack_into("<I", out, so + _RLT_SEC * 1 + 12, s1)
    struct.pack_into("<I", out, so + _RLT_SEC * 2 + 8, P + s1)
    struct.pack_into("<I", out, so + _RLT_SEC * 2 + 12, new_T - (P + s1))
    for s in (3, 4):
        struct.pack_into("<I", out, so + _RLT_SEC * s + 8, _u32(data, L.rlt + _RLT_HDR + _RLT_SEC * s + 8) + delta)
    assert tail_start == new_T

    # ---- per shape
    for sh in L.shapes:
        struct.pack_into("<I", out, sh.mesh + 0x20, ioffs[sh.index])
        struct.pack_into("<I", out, sh.vrtx + 0x50, voffs[sh.vrtx])
        g = geometry.get(sh.index)
        if g is None:
            continue
        n_idx = len(g.indices)
        stride = sh.buffers[0][3]
        if len(g.vertices) % stride:
            raise ModelWriteError(f"shape {sh.index}: vertex bytes not a multiple of the stride {stride}")
        nv = len(g.vertices) // stride
        struct.pack_into("<I", out, sh.mesh + 0x2C, n_idx)
        struct.pack_into("<Q", out, _u64(out, sh.mesh + 0x18), n_idx * 4)       # index buffer size
        if sh.n_submesh < 1:
            raise ModelWriteError(f"shape {sh.index}: no submesh")
        struct.pack_into("<II", out, sh.submesh, 0, n_idx)
        for k in range(1, sh.n_submesh):          # extra submeshes (none shipped): empty at the end
            struct.pack_into("<II", out, sh.submesh + 8 * k, n_idx * 4, 0)
        struct.pack_into("<Q", out, sh.buffers[0][0], len(g.vertices))           # vertex buffer size
        struct.pack_into("<I", out, sh.vrtx + 0x58, nv)
        if g.bbox is not None:
            c, e = g.bbox
            for k in range(1 + sh.n_submesh):
                struct.pack_into("<6f", out, sh.bbox + 0x18 * k, *c, *e)
        if g.radius is not None:
            struct.pack_into("<f", out, sh.radius, g.radius)
    return bytes(out)


def validate(data):
    """Problems a loader would trip over ([] = none): the relocation walk, pool bookkeeping,
    per-shape buffers inside the pool and index values inside the vertex count."""
    probs = []
    try:
        relocation_slots(data)
        L = layout(data)
    except (ModelWriteError, struct.error, IndexError) as e:
        return [str(e)]
    if _u32(data, 0x0C) != len(data) or _u32(data, 0x1C) != len(data):
        probs.append("file size fields != file size")
    pool_size = L.pool_end - L.pool
    for sh in L.shapes:
        esz = 1 << sh.index_format
        if sh.index_offset % POOL_ALIGN or sh.index_offset + esz * sh.index_count > pool_size:
            probs.append(f"shape {sh.index}: index buffer outside the pool / misaligned")
        if _u64(data, _u64(data, sh.mesh + 0x18)) != esz * sh.index_count:
            probs.append(f"shape {sh.index}: index buffer size != count")
        so, sc = struct.unpack_from("<II", data, sh.submesh)
        if so != 0 or sc != sh.index_count:
            probs.append(f"shape {sh.index}: submesh 0 does not cover the index buffer")
        off = sh.vertex_offset
        for si, st, size, stride in sh.buffers:
            if off % POOL_ALIGN or off + size > pool_size:
                probs.append(f"shape {sh.index}: vertex buffer outside the pool / misaligned")
            if stride and size != stride * sh.vertex_count:
                probs.append(f"shape {sh.index}: vertex buffer size != count * stride")
            off = _align(off + size, POOL_ALIGN)
        if sh.index_format == 2 and sh.index_count:
            a = L.pool + sh.index_offset
            if a + 4 * sh.index_count <= len(data):
                if max(struct.unpack_from("<%dI" % sh.index_count, data, a)) >= sh.vertex_count:
                    probs.append(f"shape {sh.index}: index past the vertex count")
    return probs


# --------------------------------------------------------------------------- #
# vertex records
# --------------------------------------------------------------------------- #
def _vertex_format(data, sh):
    """[(name, struct fmt, offset)] of a shape's attributes, and the stride."""
    if len(sh.buffers) != 1:
        raise ModelWriteError(f"shape {sh.index}: {len(sh.buffers)} vertex buffers (only 1 is supported)")
    v = sh.vrtx
    attrs = []
    for a in range(data[v + 0x54]):
        ao = _u64(data, v + 0x10) + 0x10 * a
        no = _u64(data, ao)
        name = data[no + 2:no + 2 + _u16(data, no)].decode("utf-8", "replace")
        fmt = _u32(data, ao + 8)
        comps, scal = _model._COMPONENTS.get(fmt >> 8), _model._SCALAR.get(fmt & 0xFF)
        attrs.append((name, ("<%d%s" % (comps, scal)) if comps and scal else None, _u16(data, ao + 0xC)))
    return attrs, sh.buffers[0][3]


def _records(data, L, sh):
    stride = sh.buffers[0][3]
    a = L.pool + sh.vertex_offset
    return [bytes(data[a + k * stride:a + (k + 1) * stride]) for k in range(sh.vertex_count)]


def _get(rec, attrs, name):
    for n, f, o in attrs:
        if n == name and f:
            return struct.unpack_from(f, rec, o)
    return None


def _put(rec, attrs, name, vals):
    for n, f, o in attrs:
        if n == name:
            if f is None or f[-1] != "f":
                raise ModelWriteError(f"attribute {name} is not float (format not writable)")
            k = int(f[1:-1])
            vals = (list(vals) + [0.0] * k)[:k]
            struct.pack_into(f, rec, o, *vals)
            return True
    return False


# 3x3 / 4x4 helpers (row-major, column vectors, as model.py)
def _lin(m):
    return [row[:3] for row in m[:3]]


def _inv3(a):
    (a0, a1, a2), (b0, b1, b2), (c0, c1, c2) = a
    det = a0 * (b1 * c2 - b2 * c1) - a1 * (b0 * c2 - b2 * c0) + a2 * (b0 * c1 - b1 * c0)
    if abs(det) < 1e-20:
        raise ModelWriteError("singular bone / transform matrix")
    k = 1.0 / det
    return [[(b1 * c2 - b2 * c1) * k, (a2 * c1 - a1 * c2) * k, (a1 * b2 - a2 * b1) * k],
            [(b2 * c0 - b0 * c2) * k, (a0 * c2 - a2 * c0) * k, (a2 * b0 - a0 * b2) * k],
            [(b0 * c1 - b1 * c0) * k, (a1 * c0 - a0 * c1) * k, (a0 * b1 - a1 * b0) * k]]


def _t3(a):
    return [[a[c][r] for c in range(3)] for r in range(3)]


def _mv3(a, v):
    return tuple(a[r][0] * v[0] + a[r][1] * v[1] + a[r][2] * v[2] for r in range(3))


def _inv4(m):
    """Inverse of an affine 4x4."""
    li = _inv3(_lin(m))
    t = _mv3(li, (m[0][3], m[1][3], m[2][3]))
    return [li[0] + [-t[0]], li[1] + [-t[1]], li[2] + [-t[2]], [0.0, 0.0, 0.0, 1.0]]


def _norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v) if n > 1e-20 else tuple(v)


class _Frames:
    """Per-vertex frame of a shape: raw buffer values <-> model space (the same mapping
    model.shape_vertices uses for positions; normals by the inverse transpose)."""

    def __init__(self, m, shape, attrs):
        self.m, self.shape, self.attrs = m, shape, attrs
        self.cache = {}

    def matrix_for(self, rec):
        sh = self.shape
        if sh.skin == 0:
            b = sh.bone
        elif sh.skin == 1:
            ix = _get(rec, self.attrs, "_i0")
            if ix is None:
                return None
            m2b = self.m.matrix_to_bone
            b = m2b[ix[0]] if ix[0] < len(m2b) else ix[0]
        else:
            return None                             # smooth skin: stored in model space
        hit = self.cache.get(b)
        if hit is None:
            M = self.m.bone_matrix(b)
            L3 = _lin(M)
            hit = self.cache[b] = (M, _inv4(M), _t3(_inv3(L3)), _t3(L3))
        return hit

    def to_model(self, rec, p, n):
        f = self.matrix_for(rec)
        if f is None:
            return tuple(p), (tuple(n) if n is not None else None)
        M, _Mi, Nm, _Ni = f
        return _model._apply(M, p), (_norm(_mv3(Nm, n)) if n is not None else None)

    def from_model(self, rec, p, n):
        f = self.matrix_for(rec)
        if f is None:
            return tuple(p), (tuple(n) if n is not None else None)
        _M, Mi, _Nm, Ni = f
        return _model._apply(Mi, p), (_norm(_mv3(Ni, n)) if n is not None else None)


def _bounds(positions):
    """(centre, half extent), radius of raw positions -- the rule every shipped rigid shape
    follows (float32-rounded box from the double min/max, radius = farthest vertex)."""
    f32 = lambda v: struct.unpack("<f", struct.pack("<f", v))[0]
    if not positions:
        return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)), 0.0
    lo = [min(p[k] for p in positions) for k in range(3)]
    hi = [max(p[k] for p in positions) for k in range(3)]
    c = tuple(f32((a + b) / 2) for a, b in zip(lo, hi))
    e = tuple(f32((b - a) / 2) for a, b in zip(lo, hi))
    r = max(math.sqrt(sum((p[k] - c[k]) ** 2 for k in range(3))) for p in positions)
    return (c, e), f32(r)


def _shape_bounds(data, sh, positions, old_affine=None):
    """Bounds for rewritten raw positions: exact rule for rigid shapes; for smooth-skinned
    ones the old box (optionally moved by `old_affine`) grown to cover the new positions."""
    if sh.skin < 2:
        return _bounds(positions)
    oc = struct.unpack_from("<3f", data, sh.bbox)
    oe = struct.unpack_from("<3f", data, sh.bbox + 12)
    orad = struct.unpack_from("<f", data, sh.radius)[0]
    corners = [tuple(oc[k] + sx * oe[k] for k, sx in enumerate(s))
               for s in [(a, b, c) for a in (-1, 1) for b in (-1, 1) for c in (-1, 1)]]
    if old_affine is not None:
        corners = [_model._apply(old_affine, p) for p in corners]
        sc = max(math.sqrt(sum(_lin(old_affine)[r][k] ** 2 for r in range(3))) for k in range(3))
        orad *= sc
    box, rad = _bounds(list(corners) + list(positions))
    return box, max(rad, orad) if old_affine is not None else max(rad, _bounds(corners)[1])


# --------------------------------------------------------------------------- #
# in-place transform
# --------------------------------------------------------------------------- #
def euler_matrix(rx, ry, rz):
    """Rotation Rz * Ry * Rx (radians), as the bones use."""
    b = _model.Bone(0, "", -1, (1.0, 1.0, 1.0), (rx, ry, rz), (0.0, 0.0, 0.0), True)
    return _model._local(b)


def transform_matrix(scale=None, offset=None, rotate=None, pivot=(0.0, 0.0, 0.0)):
    """4x4 model-space transform: about `pivot`, scale then rotate (Euler XYZ degrees), then
    translate by `offset`."""
    if scale is None:
        scale = (1.0, 1.0, 1.0)
    elif isinstance(scale, (int, float)):
        scale = (float(scale),) * 3
    rot = tuple(math.radians(v) for v in (rotate or (0.0, 0.0, 0.0)))
    R = euler_matrix(*rot)
    S = [[scale[0], 0, 0, 0], [0, scale[1], 0, 0], [0, 0, scale[2], 0], [0, 0, 0, 1.0]]
    px, py, pz = pivot
    ox, oy, oz = offset or (0.0, 0.0, 0.0)
    Tp = [[1, 0, 0, px + ox], [0, 1, 0, py + oy], [0, 0, 1, pz + oz], [0, 0, 0, 1.0]]
    Tn = [[1, 0, 0, -px], [0, 1, 0, -py], [0, 0, 1, -pz], [0, 0, 0, 1.0]]
    return _model._mul(Tp, _model._mul(R, _model._mul(S, Tn)))


def resolve_shape(m, shape):
    """Shape index from an index or a name."""
    if isinstance(shape, int) or (isinstance(shape, str) and shape.lstrip("-").isdigit()):
        i = int(shape)
        if not 0 <= i < len(m.shapes):
            raise ModelWriteError(f"shape index {i} out of range (model has {len(m.shapes)})")
        return i
    hits = [s.index for s in m.shapes if s.name == shape]
    if not hits:
        raise ModelWriteError(f"no shape named {shape!r} (see `rf4mod res model-info`)")
    return hits[0]


def shape_center(m, shape):
    """Model-space AABB centre of a shape."""
    pts = m.shape_vertices(m.shapes[shape])
    return tuple((min(p[k] for p in pts) + max(p[k] for p in pts)) / 2 for k in range(3)) if pts else (0.0,) * 3


def transform_shape(data, shape, *, matrix=None, scale=None, offset=None, rotate=None, pivot="center"):
    """Apply a model-space transform to one shape's vertices IN PLACE (same counts, same file
    size; only that shape's `_p0` / `_n0` bytes and bounds change). `shape` = index or name;
    `matrix` (4x4) or scale / offset / rotate (degrees, Euler XYZ) about `pivot` ("center" =
    the shape's model-space box centre, "origin", or an (x, y, z))."""
    m = _model.parse(data)
    si = resolve_shape(m, shape)
    L = layout(data)
    sh = L.shapes[si]
    if matrix is None:
        if pivot == "center":
            pivot = shape_center(m, si)
        elif pivot == "origin":
            pivot = (0.0, 0.0, 0.0)
        matrix = transform_matrix(scale, offset, rotate, tuple(pivot))
    N = _t3(_inv3(_lin(matrix)))
    attrs, stride = _vertex_format(data, sh)
    fr = _Frames(m, m.shapes[si], attrs)
    out = bytearray(data)
    base = L.pool + sh.vertex_offset
    raw = []
    for k, rec in enumerate(_records(data, L, sh)):
        r = bytearray(rec)
        p, n = _get(rec, attrs, "_p0"), _get(rec, attrs, "_n0")
        if p is None:
            raise ModelWriteError(f"shape {si}: no float _p0 attribute")
        pm, nm = fr.to_model(rec, p[:3], n[:3] if n else None)
        pm = _model._apply(matrix, pm)
        nm = _norm(_mv3(N, nm)) if nm is not None else None
        pl, nl = fr.from_model(rec, pm, nm)
        _put(r, attrs, "_p0", pl)
        if nl is not None:
            _put(r, attrs, "_n0", nl)
        out[base + k * stride:base + (k + 1) * stride] = r
        raw.append(struct.unpack_from("<3f", r, [o for nme, f, o in attrs if nme == "_p0"][0]))
    (c, e), rad = _shape_bounds(data, sh, raw, matrix if sh.skin >= 2 else None)
    for k in range(1 + sh.n_submesh):
        struct.pack_into("<6f", out, sh.bbox + 0x18 * k, *c, *e)
    struct.pack_into("<f", out, sh.radius, rad)
    return bytes(out)


# --------------------------------------------------------------------------- #
# OBJ import
# --------------------------------------------------------------------------- #
@dataclass
class ObjMesh:
    name: str
    vertices: list              # [(pos, uv | None, normal | None)] in model space, uv = buffer UV
    triangles: list             # [(a, b, c)] into vertices
    from_v_order: bool          # True when vertices are the object's `v` lines in order


def parse_obj(text):
    """[ObjMesh] per `o` / `g` object of an OBJ. Faces are triangulated as fans; corners may
    be v, v/vt, v//vn or v/vt/vn (negative = relative). When every corner uses the same number
    for v, vt and vn (as model.to_obj writes them) the object's vertices keep the `v` order."""
    V, VT, VN = [], [], []
    objs = []
    cur = None

    def new(name):
        o = {"name": name, "faces": [], "v0": len(V)}
        objs.append(o)
        return o
    for ln in text.splitlines():
        t = ln.split()
        if not t or t[0].startswith("#"):
            continue
        k = t[0]
        if k == "v":
            V.append(tuple(float(x) for x in t[1:4]))
        elif k == "vt":
            VT.append(tuple(float(x) for x in (t[1:3] + ["0"])[:2]))
        elif k == "vn":
            VN.append(tuple(float(x) for x in t[1:4]))
        elif k in ("o", "g"):
            name = " ".join(t[1:])
            if k == "g" and cur is not None and not cur["faces"] and cur["name"] == name:
                continue
            if k == "g" and cur is not None and not cur["faces"]:
                cur["name"] = name or cur["name"]
                continue
            cur = new(name)
        elif k == "f":
            if cur is None:
                cur = new("")
            corners = []
            for c in t[1:]:
                parts = (c.split("/") + ["", ""])[:3]
                ids = []
                for j, (s, lst) in enumerate(zip(parts, (V, VT, VN))):
                    if s == "":
                        ids.append(None)
                        continue
                    i = int(s)
                    ids.append(i - 1 if i > 0 else len(lst) + i)
                corners.append(tuple(ids))
            for j in range(1, len(corners) - 1):
                cur["faces"].append((corners[0], corners[j], corners[j + 1]))
    for k, o in enumerate(objs):
        o["v1"] = objs[k + 1]["v0"] if k + 1 < len(objs) else len(V)
    out = []
    for o in objs:
        if not o["faces"]:
            continue
        same = all(c[0] == (c[1] if c[1] is not None else c[0]) == (c[2] if c[2] is not None else c[0])
                   for f in o["faces"] for c in f)
        verts, tris = [], []
        if same:
            lo = min(c[0] for f in o["faces"] for c in f)
            hi = max(c[0] for f in o["faces"] for c in f)
            if o["v0"] <= lo and hi < o["v1"]:      # the object's own `v` block, in order
                lo, hi = o["v0"], o["v1"] - 1
            has_t = any(c[1] is not None for f in o["faces"] for c in f)
            has_n = any(c[2] is not None for f in o["faces"] for c in f)
            for i in range(lo, hi + 1):
                verts.append((V[i], _flip(VT[i]) if has_t and i < len(VT) else None,
                              VN[i] if has_n and i < len(VN) else None))
            tris = [tuple(c[0] - lo for c in f) for f in o["faces"]]
        else:
            seen = {}
            for f in o["faces"]:
                tri = []
                for c in f:
                    if c not in seen:
                        seen[c] = len(verts)
                        verts.append((V[c[0]], _flip(VT[c[1]]) if c[1] is not None else None,
                                      VN[c[2]] if c[2] is not None else None))
                    tri.append(seen[c])
                tris.append(tuple(tri))
        out.append(ObjMesh(o["name"], verts, tris, same))
    return out


def _flip(t):
    return (t[0], 1.0 - t[1])


def _pick_object(objs, m, si, name=None):
    if not objs:
        raise ModelWriteError("the OBJ has no faces")
    if name is not None:
        hits = [o for o in objs if o.name == name]
        if not hits:
            raise ModelWriteError(f"no object {name!r} in the OBJ (has: {[o.name for o in objs]})")
        return hits[0]
    if len(objs) == 1:
        return objs[0]
    sname = m.shapes[si].name or "shape%d" % si
    hits = [o for o in objs if o.name == sname]
    if len(hits) == 1:
        return hits[0]
    if len(objs) == len(m.shapes):
        return objs[si]
    raise ModelWriteError(f"the OBJ has {len(objs)} objects; pass the object name (shape is {sname!r})")


def _nearest(points, queries):
    """Index of the nearest `points` entry for every query."""
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        P = np.asarray(points, np.float64)
        out = []
        for k in range(0, len(queries), 2048):
            Q = np.asarray(queries[k:k + 2048], np.float64)
            d = ((Q[:, None, :] - P[None, :, :]) ** 2).sum(axis=2)
            out += d.argmin(axis=1).tolist()
        return out
    return [min(range(len(points)), key=lambda i: sum((points[i][j] - q[j]) ** 2 for j in range(3)))
            for q in queries]


def _face_normals(verts, tris):
    acc = [[0.0, 0.0, 0.0] for _ in verts]
    for a, b, c in tris:
        pa, pb, pc = verts[a][0], verts[b][0], verts[c][0]
        u = [pb[k] - pa[k] for k in range(3)]
        v = [pc[k] - pa[k] for k in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        for i in (a, b, c):
            for k in range(3):
                acc[i][k] += n[k]
    return [_norm(n) if any(n) else (0.0, 1.0, 0.0) for n in acc]


def shape_geometry_from_obj(data, shape, obj_text, *, object_name=None, keep_exact=True):
    """ShapeGeometry for `shape` built from an OBJ (see the module notes for the frames).
    keep_exact=False rebuilds every vertex from the OBJ values (no byte reuse)."""
    m = _model.parse(data)
    si = resolve_shape(m, shape)
    L = layout(data)
    sh = L.shapes[si]
    attrs, stride = _vertex_format(data, sh)
    names = {a[0]: a for a in attrs}
    for need in ("_p0",):
        if need not in names or names[need][1] is None or names[need][1][-1] != "f":
            raise ModelWriteError(f"shape {si}: no float {need} attribute")
    if sh.index_format != 2 or m.shapes[si].primitive != 3:
        raise ModelWriteError(f"shape {si}: not a u32 triangle list")
    obj = _pick_object(parse_obj(obj_text), m, si, object_name)
    if not obj.triangles:
        raise ModelWriteError("the OBJ object has no triangles")
    recs = _records(data, L, sh)
    if not recs:
        raise ModelWriteError(f"shape {si} has no vertices to take the attribute defaults from")
    fr = _Frames(m, m.shapes[si], attrs)
    # the exported values of the original vertices (parsed back from model.to_obj, so the
    # comparison sees exactly what an unmodified export contains)
    exp = _pick_object(parse_obj(_model.to_obj(m)[0]), m, si,
                       (m.shapes[si].name or "shape%d" % si) if len(m.shapes) > 1 else None)
    exact = {}
    same_slot = set()           # OBJ vertex k is exported vertex k unchanged (keeps duplicates apart)
    if keep_exact and len(exp.vertices) == len(recs):
        for k, (p, t, n) in enumerate(exp.vertices):
            exact.setdefault((p, t, n), k)
        if obj.from_v_order:
            same_slot = {k for k in range(min(len(obj.vertices), len(recs)))
                         if obj.vertices[k] == exp.vertices[k]}
    orig_model = [fr.to_model(r, _get(r, attrs, "_p0")[:3], None)[0] for r in recs]
    normals = None
    if any(n is None for _p, _t, n in obj.vertices) and "_n0" in names:
        normals = _face_normals(obj.vertices, obj.triangles)
    need_near = [k for k, v in enumerate(obj.vertices)
                 if (v[0], v[1], v[2]) not in exact]
    near = dict(zip(need_near, _nearest(orig_model, [obj.vertices[k][0] for k in need_near]))) if need_near else {}
    blob = bytearray()
    raw = []
    kept = 0
    ppos = names["_p0"][2]
    for k, (p, t, n) in enumerate(obj.vertices):
        hit = k if k in same_slot else exact.get((p, t, n))
        if hit is not None:
            rec = bytearray(recs[hit])
            kept += 1
        else:
            rec = bytearray(recs[near[k]])
            if n is None and normals is not None:
                n = normals[k]
            pl, nl = fr.from_model(rec, p, n)
            _put(rec, attrs, "_p0", pl)
            if nl is not None and "_n0" in names:
                _put(rec, attrs, "_n0", nl)
            if t is not None and "_u0" in names:
                _put(rec, attrs, "_u0", t)
        blob += rec
        raw.append(struct.unpack_from("<3f", rec, ppos))
    idx = [i for tri in obj.triangles for i in tri]
    if max(idx) >= len(obj.vertices):
        raise ModelWriteError("face index past the vertex list")
    box, rad = _shape_bounds(data, sh, raw)
    g = ShapeGeometry(bytes(blob), idx, box, rad)
    g.kept = kept
    return g


def import_obj(data, shape, obj_text, *, object_name=None, keep_exact=True):
    """Replace one shape's geometry from OBJ text; returns the new file bytes. When nothing
    changed (an unmodified export) the result is byte-identical to the input. `shape` =
    index or name; `object_name` picks the OBJ object (default: the only one, else the one
    named like the shape, else the shape-index-th of a full-model export)."""
    m = _model.parse(data)
    si = resolve_shape(m, shape)
    g = shape_geometry_from_obj(data, si, obj_text, object_name=object_name, keep_exact=keep_exact)
    L = layout(data)
    sh = L.shapes[si]
    old = bytes(data[L.pool + sh.vertex_offset:L.pool + sh.vertex_offset + sh.buffers[0][2]])
    a = L.pool + sh.index_offset
    old_idx = list(struct.unpack_from("<%dI" % sh.index_count, data, a))
    if g.vertices == old and g.indices == old_idx:
        return bytes(data)
    return rebuild(data, {si: g})


def replace_shape(data, shape, positions, triangles, *, uvs=None, normals=None):
    """Replace a shape's geometry from Python lists (model-space positions, triangle index
    triples, optional UVs in buffer convention and model-space normals) -- import_obj without
    the OBJ text."""
    lines = ["o replaced"] + ["v %r %r %r" % tuple(p) for p in positions]
    if uvs:
        lines += ["vt %r %r" % (u, 1.0 - v) for u, v in uvs]
    if normals:
        lines += ["vn %r %r %r" % tuple(n) for n in normals]
    for tri in triangles:
        a, b, c = (i + 1 for i in tri)
        if uvs and normals:
            lines.append(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}")
        elif uvs:
            lines.append(f"f {a}/{a} {b}/{b} {c}/{c}")
        elif normals:
            lines.append(f"f {a}//{a} {b}//{b} {c}//{c}")
        else:
            lines.append(f"f {a} {b} {c}")
    return import_obj(data, shape, "\n".join(lines) + "\n", object_name="replaced")


def cube_obj(center=(0.0, 0.0, 0.0), size=1.0, name="cube"):
    """OBJ text of an axis-aligned cube (24 vertices with per-face normals and UVs, 12
    triangles) -- a test / placeholder mesh."""
    h = size / 2.0
    cx, cy, cz = center
    faces = [((1, 0, 0), (0, 1, 0), (0, 0, 1)), ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),
             ((0, 1, 0), (0, 0, 1), (1, 0, 0)), ((0, -1, 0), (0, 0, -1), (1, 0, 0)),
             ((0, 0, 1), (0, 1, 0), (-1, 0, 0)), ((0, 0, -1), (0, 1, 0), (1, 0, 0))]
    v, vt, vn, f = [], [], [], []
    for n, up, rt in faces:
        base = len(v)
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            v.append(tuple(c + h * (n[k] + su * rt[k] + sv * up[k]) for k, c in enumerate((cx, cy, cz))))
            vt.append(((su + 1) / 2, (sv + 1) / 2))
            vn.append(n)
        f += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    lines = [f"o {name}"] + ["v %.6f %.6f %.6f" % p for p in v] + ["vt %.6f %.6f" % t for t in vt] \
        + ["vn %.6f %.6f %.6f" % t for t in vn]
    lines += ["f " + " ".join(f"{i + 1}/{i + 1}/{i + 1}" for i in tri) for tri in f]
    return "\n".join(lines) + "\n"
