r"""
model.py -- geometry reader for RF4S `.model` files (meshes, skeleton, materials).

A `.model` is a `RES\0` container around a Switch nn::g3d model whose blocks carry
renamed tags and a 16-byte header (magic + 12 zero bytes) instead of the 8-byte one of
stock BFRES, so every field sits 8 bytes later than in the public FMDL/FVTX/FSHP/FSKL/FMAT
layouts. Every offset below is an absolute file offset (the loader's relocation pass,
BFRES_EnsureRelocationFixed, turns them into pointers). Laid out against the shipped files
2026-09-24 (all 912 mesh-bearing .model files parse; the other 212 .model files are UI
screen layouts -- calendar, shop, camp menu ... -- with no mesh block, see `is_mesh`):

    RES+0x28  u64 -> MESH
    MESH+0x20 -> SKEL       +0x28 -> VRTX[]   +0x30 -> SHAP[]   +0x40 -> MATL[]
    MESH+0x68 u16 vertex-buffer count, +0x6A shape count, +0x6C material count
    MESH+0x80 u32 memory pool = [all index buffers][all vertex buffers]

    VRTX (0x60)  +0x10 -> attributes (0x10 each: u64 name, u32 format, u16 offset,
                 u16 buffer), +0x38 -> {u32 size}[per buffer, 0x10 apart],
                 +0x40 -> {u32 stride}[per buffer, 0x10 apart], +0x50 u32 buffer offset
                 in the pool, +0x54 u8 attribute count, +0x55 u8 buffer count,
                 +0x58 u32 vertex count, +0x5C u8 skin influences per vertex
    SHAP (0x70)  +0x10 name, +0x18 -> VRTX, +0x20 -> mesh (0x38: +0x20 u32 index
                 offset in the pool, +0x24 primitive (3 = triangle list), +0x28 index
                 format (2 = u32), +0x2C index count), +0x40 -> bounding box,
                 +0x5C u16 index, +0x5E u16 material, +0x60 u16 bone, +0x62 u16 vertex
                 buffer, +0x66 u8 skin influences
    SKEL         +0x18 -> bones (0x60 each: u64 name, +0x28 u16 index, +0x2A u16 parent
                 (0xFFFF = root), +0x34 u32 flags (bit 12 = Euler XYZ rotation, set on all
                 7,935 shipped bones), +0x38 scale xyz, rotation xyz(w), translation xyz),
                 +0x20 -> u16 matrix-to-bone table (smooth then rigid matrices; a vertex's
                 `_i0` values index it), +0x28 -> inverse bind matrices (3x4 f32 row-major,
                 0x30 each, one per smooth matrix; the skin-matrix builder RF4S.exe+0x3D8650
                 multiplies world[matrix_to_bone[k]] by entry k), +0x4C u16 bone count,
                 +0x4E u16 smooth-matrix count, +0x50 u16 rigid-matrix count
    Skinning: smooth (skin 2+) vertices are stored in bind-pose model space, rigid and
    single-influence ones in their bone's space (all shipped skin-1 vertices index rigid
    matrices). Set `Model.pose` (skelanim.pose_bones) to deform them; see skin_palette.
    MATL (0xB8)  +0x10 name, +0x28 -> shader assign ({archive, model} names), +0x38 ->
                 texture names (u64 each), +0x70 -> user data (0x40 each: u64 name, u64 data,
                 u32 count, u8 type 0 int / 1 float / 2 string), +0xA8 u8 texture count,
                 +0xB2 u16 user-data count

Attribute formats: the low byte is the scalar type (0x05 float32, 0x03 uint32) and the
high byte the component count (0x14 = 1, 0x17 = 2, 0x18 = 3, 0x19 = 4). Names follow the
g3d convention: `_p0` position, `_n0` normal, `_u0` UV, `_c0` colour, `_i0` bone indices,
`_w0` bone weights.

Material user data read by the game: `DrawOrder`, `BlendType`, `CombineType`,
`CombineColor00` (GfxCTR_Model_BuildFromResource, RF4S.exe+0x1B52C0) and `po` on the
map over-models, whose value becomes the mesh's depth as po * 1.5 - 0.3 (Map_SpawnEntity,
RF4S.exe+0x194140).

Blending: the loader keeps `BlendType` only when it is 0..4 (anything else -> 0), and
Scene_SubmitDrawList (RF4S.exe+0x1B9430) binds one of five blend states by it. The states
are built at boot by NN_AllocAndRegisterDefaultConfigBlocks5 (RF4S.exe+0x1C4690) through
GfxCTR_ConvertBlendState (+0x3CA210), as nn::gfx (source, destination) factors:
    0 blending off                    1 SrcAlpha, 1-SrcAlpha (normal alpha)
    2 SrcAlpha, One (additive glow)   3 One, One (pure additive)   4 One, Zero
Effect layers such as the ANIM_DUNG_* light shafts and water sheets are BlendType 2: an
opaque-looking stripe or caustic texture ADDED onto the scene. Their UVs run far outside
0..1 (up to 20 repeats), so the texture tiles. The `.bfmat` next to them is an FMAA
material animation of the `texsrt0` shader parameter (a U or V scroll, see matanim.py).

Shading on PC: the GLSL inside the .bfsha archives is NOT compiled; the game compiles the
loose Muteki programs in bundleMuteki (mtk_body / mtk_item / mtk_billboard, see
shaderarchive.py). The program is picked from the vertex attributes the material's shading
model lists (rf4cmv body / costume: _p0 _i0 _i1 _w0 _w1 _u0 _u1; lighting adds _n0; none
lists `_c0`), intersected with the shape's buffer (RF4S.exe+0x1BF5F0 -> selector +0x3C4720):
    mtk_body   a skinned shape (_i0) or a `lighting` material with normals: alpha is
               ROUNDED -- discarded below 0.5, else drawn opaque
    mtk_item   everything else (static props, map cards, BM_* bosses, ANIM_DUNG_*): the
               texture alpha is kept, only alpha <= 0.1 is discarded
The vertex colour `_c0` never reaches a model draw (no shading model binds it; mtk_body's
source even notes the converted data carries 0.0 there -- 222 shapes such as the BM_*
bosses store pure black), so it is ignored. Costume vs body only chooses that attribute
list, which is the same for both, so it does not change the program or the alpha test.

Map over-models (`MAP_*.model`): every card is a flat quad in the model's XZ plane,
rigidly bound to its own bone (skin 0) whose translation places it. Model units ARE map
sub-units (8 per ATTR tile): X runs with the map's X and Z with the map's Y, so
`overmodel_cards()` gives each card's footprint on the tile grid directly.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

from . import texture


class ModelError(Exception):
    pass


# fragment alpha tests of the two Muteki model programs (bundleMuteki mtk_body_f / mtk_item_f)
BODY_ALPHA_CUT = 0.5          # mtk_body: alpha rounded -> discarded below 0.5, else opaque
ITEM_ALPHA_CUT = 0.1          # mtk_item: discarded at alpha <= 0.1, else kept as is


def shape_program(model, shape):
    """'body' or 'item': the Muteki program the PC game draws `shape` with (see the notes)."""
    vb = model.vertex_buffers[shape.vertex_buffer]
    names = {a.name for a in vb.attributes}
    mt = model.materials[shape.material] if 0 <= shape.material < len(model.materials) else None
    if "_i0" in names or (mt is not None and mt.shading == "lighting" and "_n0" in names):
        return "body"
    return "item"

_COMPONENTS = {0x14: 1, 0x17: 2, 0x18: 3, 0x19: 4}
_SCALAR = {0x05: "f", 0x03: "I"}


@dataclass
class Attribute:
    name: str
    format: int
    offset: int
    buffer: int

    @property
    def components(self):
        return _COMPONENTS.get(self.format >> 8)

    @property
    def scalar(self):
        return _SCALAR.get(self.format & 0xFF)


@dataclass
class VertexBuffer:
    index: int
    count: int
    skin: int
    attributes: list
    data: dict = field(default_factory=dict)     # attribute name -> [tuple, ...]


@dataclass
class Shape:
    index: int
    name: str
    material: int
    bone: int
    vertex_buffer: int
    skin: int
    primitive: int
    indices: list


@dataclass
class Bone:
    index: int
    name: str
    parent: int                  # -1 = root
    scale: tuple
    rotation: tuple              # Euler XYZ radians (or a quaternion when euler is False)
    translation: tuple
    euler: bool = True


@dataclass
class Material:
    index: int
    name: str
    textures: list               # texture names (resolved against the embedded BNTX)
    shader: tuple                # (archive, model) names, e.g. ('rf4cmv', 'body')
    user_data: dict              # name -> list of values

    @property
    def shading(self):
        """The rf4cmv shading model: 'body' (alpha as is), 'costume' (punch-out) or 'lighting'."""
        return self.shader[1] if len(self.shader) > 1 else ""

    @property
    def blend_type(self):
        """0..4 as the loader keeps it (GfxCTR_Model_BuildFromResource: missing or > 4 -> 0)."""
        v = self.user_data.get("BlendType")
        v = v[0] if v and isinstance(v[0], int) else 0
        return v if 0 <= v <= 4 else 0


@dataclass
class Model:
    vertex_buffers: list
    shapes: list
    bones: list
    materials: list
    textures: list               # texture.bntx_info() dicts of the embedded BNTX
    data: bytes = field(repr=False, default=b"")
    matrix_to_bone: list = field(default_factory=list)   # skinning matrix index -> bone
    smooth_count: int = 0        # SKEL +0x4E: the first N skinning matrices are smooth
    inverse_bind: list = field(default_factory=list)     # SKEL +0x28: 4x4 per smooth matrix
    # pose hook: a list of Bone (same order as `bones`, e.g. skelanim.pose_bones()) that
    # replaces the bind pose in bone_matrix / shape_vertices while set; None = bind pose
    pose: list | None = field(default=None, repr=False)

    # ---- transforms ------------------------------------------------------ #
    def bone_matrix(self, i):
        """Bone `i`'s model-space 4x4 matrix (row-major, column vectors), posed by
        `self.pose` when set."""
        bones = self.pose if self.pose is not None else self.bones
        m = _identity()
        seen = 0
        while 0 <= i < len(bones) and seen < len(bones):
            m = _mul(_local(bones[i]), m)
            i = bones[i].parent
            seen += 1
        return m

    def skin_palette(self):
        """The skinning matrices the game uploads (the skin-matrix builder at
        RF4S.exe+0x3D8650): smooth matrix k = world[matrix_to_bone[k]] * inverse_bind[k],
        rigid matrices = world[bone]. At the bind pose the smooth ones are identity."""
        world = world_matrices(self.pose if self.pose is not None else self.bones)
        out = []
        for k, b in enumerate(self.matrix_to_bone):
            w = world[b] if 0 <= b < len(world) else _identity()
            out.append(_mul(w, self.inverse_bind[k]) if k < min(self.smooth_count, len(self.inverse_bind)) else w)
        return out

    def shape_vertices(self, shape):
        """[(x, y, z)] of a shape's vertices in model space. Rigid shapes (skin 0) are
        moved by their bone; skinned shapes (1+) by the skinning palette (`skin_palette`)
        through `_i0` / `_w0` (linear blend skinning; smooth-skinned vertices are stored
        in bind-pose model space, so an unposed model returns them as stored)."""
        vb = self.vertex_buffers[shape.vertex_buffer]
        pos = vb.data.get("_p0", [])
        if self.pose is not None and shape.skin >= 1 and "_i0" in vb.data and self.matrix_to_bone:
            pal = self.skin_palette()
            n = len(pal)
            wts = vb.data.get("_w0")
            out = []
            for k, (p, ix) in enumerate(zip(pos, vb.data["_i0"])):
                if shape.skin == 1 or wts is None:
                    m = pal[ix[0]] if ix[0] < n else _identity()
                    out.append(_apply(m, p))
                    continue
                w = wts[k]
                x = y = z = 0.0
                for j in range(min(shape.skin, len(ix), len(w))):
                    if w[j] == 0.0 or ix[j] >= n:
                        continue
                    q = _apply(pal[ix[j]], p)
                    x += w[j] * q[0]
                    y += w[j] * q[1]
                    z += w[j] * q[2]
                out.append((x, y, z))
            return out
        if shape.skin == 0:
            m = self.bone_matrix(shape.bone)
            return [_apply(m, p) for p in pos]
        if shape.skin == 1 and "_i0" in vb.data:
            cache = {}
            out = []
            m2b = self.matrix_to_bone
            for p, ix in zip(pos, vb.data["_i0"]):
                b = m2b[ix[0]] if ix[0] < len(m2b) else ix[0]
                if b not in cache:
                    cache[b] = self.bone_matrix(b)
                out.append(_apply(cache[b], p))
            return out
        return [tuple(p[:3]) for p in pos]

    def texture_index(self, name):
        for t in self.textures:
            if t["name"] == name:
                return t["index"]
        return None

    def material_texture(self, material, decode=True):
        """(texture name, PIL image | None) of a material's first texture."""
        mat = self.materials[material] if 0 <= material < len(self.materials) else None
        if mat is None or not mat.textures:
            return None, None
        name = mat.textures[0]
        ti = self.texture_index(name)
        if ti is None or not decode:
            return name, None
        try:
            return name, texture.decode_bntx(self.data, ti)
        except Exception:
            return name, None


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def is_mesh(data):
    """True when `data` is a .model with a mesh block (False for the UI screen layouts)."""
    if data[:4] != b"RES\x00" or len(data) < 0x30:
        return False
    m = struct.unpack_from("<Q", data, 0x28)[0]
    return data[m:m + 4] == b"MESH"


def parse(data, *, decode_vertices=True):
    """Parse a .model's meshes, skeleton and materials. Raises ModelError for anything
    that is not a mesh-bearing .model."""
    if not is_mesh(data):
        raise ModelError("not a mesh .model (UI screen layouts share the extension)")
    n = len(data)
    u8 = lambda o: data[o]
    u16 = lambda o: struct.unpack_from("<H", data, o)[0]
    u32 = lambda o: struct.unpack_from("<I", data, o)[0]
    u64 = lambda o: struct.unpack_from("<Q", data, o)[0]

    def name(off):
        if not 0 < off < n - 2:
            return ""
        k = u16(off)
        return data[off + 2:off + 2 + k].decode("utf-8", "replace")

    M = u64(0x28)
    n_vb, n_sh, n_mat = u16(M + 0x68), u16(M + 0x6A), u16(M + 0x6C)
    pool = u32(M + 0x80)

    vbs = []
    for i in range(n_vb):
        v = u64(M + 0x28) + 0x60 * i
        if data[v:v + 4] != b"VRTX":
            raise ModelError(f"vertex buffer {i}: no VRTX at 0x{v:X}")
        n_attr, n_buf = u8(v + 0x54), u8(v + 0x55)
        count = u32(v + 0x58)
        attrs = []
        for a in range(n_attr):
            ao = u64(v + 0x10) + 0x10 * a
            attrs.append(Attribute(name(u64(ao)), u32(ao + 8), u16(ao + 0xC), u16(ao + 0xE)))
        vb = VertexBuffer(i, count, u8(v + 0x5C), attrs)
        if decode_vertices:
            base = pool + u32(v + 0x50)
            starts, strides = [], []
            off = base
            for b in range(n_buf):
                starts.append(off)
                strides.append(u32(u64(v + 0x40) + 0x10 * b))
                off += u32(u64(v + 0x38) + 0x10 * b)
            for at in attrs:
                comps, scalar = at.components, at.scalar
                if comps is None or scalar is None or at.buffer >= n_buf:
                    continue
                fmt = "<%d%s" % (comps, scalar)
                st, stride = starts[at.buffer], strides[at.buffer]
                vb.data[at.name] = [struct.unpack_from(fmt, data, st + k * stride + at.offset)
                                    for k in range(count)]
        vbs.append(vb)

    shapes = []
    for i in range(n_sh):
        s = u64(M + 0x30) + 0x70 * i
        if data[s:s + 4] != b"SHAP":
            raise ModelError(f"shape {i}: no SHAP at 0x{s:X}")
        mesh = u64(s + 0x20)
        prim, ifmt, icount = u32(mesh + 0x24), u32(mesh + 0x28), u32(mesh + 0x2C)
        isize = {0: 1, 1: 2, 2: 4}.get(ifmt, 4)
        ioff = pool + u32(mesh + 0x20)
        code = {1: "B", 2: "H", 4: "I"}[isize]
        idx = list(struct.unpack_from("<%d%s" % (icount, code), data, ioff)) if decode_vertices else []
        shapes.append(Shape(u16(s + 0x5C), name(u64(s + 0x10)), u16(s + 0x5E), u16(s + 0x60),
                            u16(s + 0x62), u8(s + 0x66), prim, idx))

    bones, m2b, inv, n_smooth = [], [], [], 0
    S = u64(M + 0x20)
    if data[S:S + 4] == b"SKEL":
        n_smooth = u16(S + 0x4E)
        nmtx = n_smooth + u16(S + 0x50)
        if u64(S + 0x20) and nmtx:
            m2b = list(struct.unpack_from("<%dH" % nmtx, data, u64(S + 0x20)))
        if u64(S + 0x28) and n_smooth:
            for k in range(n_smooth):
                f = struct.unpack_from("<12f", data, u64(S + 0x28) + 0x30 * k)
                inv.append([list(f[0:4]), list(f[4:8]), list(f[8:12]), [0.0, 0.0, 0.0, 1.0]])
        for b in range(u16(S + 0x4C)):
            o = u64(S + 0x18) + 0x60 * b
            f = struct.unpack_from("<10f", data, o + 0x38)
            parent = u16(o + 0x2A)
            euler = bool(u32(o + 0x34) & 0x1000)
            bones.append(Bone(u16(o + 0x28), name(u64(o)), -1 if parent == 0xFFFF else parent,
                              f[0:3], f[3:6] if euler else f[3:7], f[7:10], euler))

    mats = []
    for i in range(n_mat):
        m = u64(M + 0x40) + 0xB8 * i
        if data[m:m + 4] != b"MATL":
            raise ModelError(f"material {i}: no MATL at 0x{m:X}")
        ntex = u8(m + 0xA8)
        texs = [name(u64(u64(m + 0x38) + 8 * k)) for k in range(ntex)] if u64(m + 0x38) else []
        sa = u64(m + 0x28)
        shader = (name(u64(sa)), name(u64(sa + 8))) if 0 < sa < n - 16 else ("", "")
        ud = {}
        for k in range(u16(m + 0xB2)):
            e = u64(m + 0x70) + 0x40 * k
            cnt, typ = u32(e + 0x10), u8(e + 0x14)
            p = u64(e + 8)
            if typ == 1:
                vals = list(struct.unpack_from("<%df" % cnt, data, p))
            elif typ == 0:
                vals = list(struct.unpack_from("<%di" % cnt, data, p))
            else:
                vals = [name(u64(p + 8 * j)) for j in range(cnt)]
            ud[name(u64(e))] = vals
        mats.append(Material(i, name(u64(m + 0x10)), texs, shader, ud))

    return Model(vbs, shapes, bones, mats, texture.bntx_info(data), data, m2b, n_smooth, inv)


def load(path):
    with open(path, "rb") as fh:
        return parse(fh.read())


# --------------------------------------------------------------------------- #
# matrices (4x4, row-major, column vectors)
# --------------------------------------------------------------------------- #
def _identity():
    return [[1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]


def _mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def _apply(m, p):
    x, y, z = p[0], p[1], p[2]
    return (m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
            m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
            m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3])


def world_matrices(bones):
    """Model-space 4x4 matrices of every bone in a list of Bone (parents resolved once)."""
    out = [None] * len(bones)

    def get(i, depth=0):
        if out[i] is None:
            p = bones[i].parent
            loc = _local(bones[i])
            out[i] = _mul(get(p, depth + 1), loc) if 0 <= p < len(bones) and p != i and depth < len(bones) else loc
        return out[i]
    for i in range(len(bones)):
        get(i)
    return out


def _local(b):
    """Bone local matrix T * R * S (R = Rz * Ry * Rx for Euler XYZ)."""
    sx, sy, sz = b.scale
    if b.euler:
        rx, ry, rz = b.rotation[:3]
        cx, sxr, cy, syr, cz, szr = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
        r = [[cy * cz, sxr * syr * cz - cx * szr, cx * syr * cz + sxr * szr],
             [cy * szr, sxr * syr * szr + cx * cz, cx * syr * szr - sxr * cz],
             [-syr, sxr * cy, cx * cy]]
    else:
        x, y, z, w = b.rotation
        r = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
             [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
             [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    tx, ty, tz = b.translation
    return [[r[0][0] * sx, r[0][1] * sy, r[0][2] * sz, tx],
            [r[1][0] * sx, r[1][1] * sy, r[1][2] * sz, ty],
            [r[2][0] * sx, r[2][1] * sy, r[2][2] * sz, tz],
            [0.0, 0.0, 0.0, 1.0]]


# --------------------------------------------------------------------------- #
# map over-models
# --------------------------------------------------------------------------- #
@dataclass
class Card:
    """One over-model card, in map sub-units (8 per tile)."""
    shape: int
    name: str
    texture: str
    triangles: list              # [((x, y), (u, v)) x 3, ...]
    bounds: tuple                # (x0, y0, x1, y1)
    po: float | None
    draw_order: int | None


def overmodel_cards(model):
    """The cards of a map over-model as they lie on the map: model X -> map X, model Z
    -> map Y, both in sub-units. Cards are listed in shape order."""
    out = []
    for sh in model.shapes:
        vb = model.vertex_buffers[sh.vertex_buffer]
        pos = model.shape_vertices(sh)
        uv = vb.data.get("_u0") or [(0.0, 0.0)] * len(pos)
        tris = []
        for k in range(0, len(sh.indices) - 2, 3):
            tri = []
            for j in sh.indices[k:k + 3]:
                if j >= len(pos):
                    break
                tri.append(((pos[j][0], pos[j][2]), (uv[j][0], uv[j][1])))
            if len(tri) == 3:
                tris.append(tri)
        if not tris:
            continue
        xs = [p[0] for t in tris for p, _uv in t]
        ys = [p[1] for t in tris for p, _uv in t]
        mat = model.materials[sh.material] if sh.material < len(model.materials) else None
        ud = mat.user_data if mat else {}
        out.append(Card(sh.index, sh.name, mat.textures[0] if mat and mat.textures else "",
                        tris, (min(xs), min(ys), max(xs), max(ys)),
                        (ud.get("po") or [None])[0], (ud.get("DrawOrder") or [None])[0]))
    return out


def render_overmodel(model, width_px, height_px, px_per_unit, *, textures=None):
    """Draw a map over-model top-down onto a transparent RGBA image of the given size:
    each card's texture mapped through its UVs (one affine warp per triangle, UVs wrap).
    `px_per_unit` = pixels per sub-unit (cell pixels / 8). `textures` optionally caches
    {texture name: PIL image} across calls."""
    from PIL import Image, ImageChops, ImageDraw
    img = Image.new("RGBA", (max(1, int(width_px)), max(1, int(height_px))), (0, 0, 0, 0))
    textures = {} if textures is None else textures
    for card in overmodel_cards(model):
        if card.texture not in textures:
            ti = model.texture_index(card.texture)
            try:
                tex = texture.decode_bntx(model.data, ti) if ti is not None else None
            except Exception:
                tex = None
            textures[card.texture] = tex.convert("RGBA") if tex is not None else None
        tex = textures[card.texture]
        if tex is None:
            continue
        for tri in card.triangles:
            dst = [(p[0] * px_per_unit, p[1] * px_per_unit) for p, _uv in tri]
            src_img, src = _wrapped_source(tex, [uv for _p, uv in tri])
            x0, y0 = int(math.floor(min(p[0] for p in dst))), int(math.floor(min(p[1] for p in dst)))
            x1, y1 = int(math.ceil(max(p[0] for p in dst))), int(math.ceil(max(p[1] for p in dst)))
            if x1 <= x0 or y1 <= y0:
                continue
            coeffs = _affine_dst_to_src(dst, src, x0, y0)
            if coeffs is None:
                continue
            patch = src_img.transform((x1 - x0, y1 - y0), Image.AFFINE, coeffs, resample=Image.BILINEAR)
            mask = Image.new("L", patch.size, 0)
            ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in dst], fill=255)
            patch.putalpha(ImageChops.multiply(patch.getchannel("A"), mask))
            _paste_clipped(img, patch, x0, y0)
    return img


_MAX_TILED_PX = 4096 * 4096


def _wrapped_source(tex, uvs):
    """(source image, [(x, y)] pixel coords) for an affine paste of a triangle whose UVs may
    leave 0..1: the texture is tiled over the triangle's whole UV range (REPEAT wrap, as the
    game samples it -- e.g. MAP_ROOM_25/26 and the ANIM_DUNG_* effect sheets tile up to 23x)
    and the UVs are shifted into it. Falls back to the plain texture when the tiling would
    exceed ~16 Mpx."""
    tw, th = tex.size
    us, vs = [uv[0] for uv in uvs], [uv[1] for uv in uvs]
    iu0, iv0 = math.floor(min(us)), math.floor(min(vs))
    nu, nv = max(1, math.ceil(max(us)) - iu0), max(1, math.ceil(max(vs)) - iv0)
    if (iu0, iv0, nu, nv) == (0, 0, 1, 1) or nu * nv * tw * th > _MAX_TILED_PX:
        return tex, [(u * tw, v * th) for u, v in zip(us, vs)]
    from PIL import Image
    tiled = Image.new(tex.mode, (tw * nu, th * nv))
    for j in range(nv):
        for i in range(nu):
            tiled.paste(tex, (i * tw, j * th))
    return tiled, [((u - iu0) * tw, (v - iv0) * th) for u, v in zip(us, vs)]


def _paste_clipped(img, patch, x0, y0):
    cx, cy = max(0, -x0), max(0, -y0)
    if cx >= patch.width or cy >= patch.height:
        return
    img.alpha_composite(patch.crop((cx, cy, patch.width, patch.height)), (max(0, x0), max(0, y0)))


def _affine_dst_to_src(dst, src, ox, oy):
    """Coefficients (a, b, c, d, e, f) with src = (a*x + b*y + c, d*x + e*y + f) for
    destination pixel (x, y) relative to (ox, oy) -- PIL's AFFINE convention."""
    (x0, y0), (x1, y1), (x2, y2) = [(x - ox, y - oy) for x, y in dst]
    det = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if abs(det) < 1e-9:
        return None
    out = []
    for comp in (0, 1):
        s0, s1, s2 = src[0][comp], src[1][comp], src[2][comp]
        a = ((s1 - s0) * (y2 - y0) - (s2 - s0) * (y1 - y0)) / det
        b = ((s2 - s0) * (x1 - x0) - (s1 - s0) * (x2 - x0)) / det
        c = s0 - a * x0 - b * y0
        out += [a, b, c]
    return tuple(out)


_FIELD_COS, _FIELD_SIN = math.cos(math.radians(25)), math.sin(math.radians(25))
VIEWS = {
    # screen x, screen y (down), depth (larger = nearer the viewer)
    "front": lambda p: (p[0], -p[1], p[2]),
    "back": lambda p: (-p[0], -p[1], -p[2]),
    "side": lambda p: (p[2], -p[1], -p[0]),
    "top": lambda p: (p[0], p[2], p[1]),
    # the field camera: the front, looked down on at about 25 degrees (fitted to an in-game
    # screenshot of a treasure chest -- the lid / body seam sits at the same height)
    "field": lambda p: (p[0], -p[1] * _FIELD_COS + p[2] * _FIELD_SIN,
                        p[2] * _FIELD_COS + p[1] * _FIELD_SIN),
}


def _triangles(model, proj, uv_mtx=None):
    """[(depth, [p]*3, [uv]*3 | None, program, material index)] in view space; program =
    shape_program() ('body' / 'item', which decides the alpha test).
    `uv_mtx` optionally maps a material index to a 2x3 UV matrix (a material animation)."""
    tris = []
    for sh in model.shapes:
        vb = model.vertex_buffers[sh.vertex_buffer]
        prog = shape_program(model, sh)
        pos = [proj(p) for p in model.shape_vertices(sh)]
        uv = vb.data.get("_u0")
        mtx = uv_mtx.get(sh.material) if uv_mtx else None
        if uv and mtx:
            (a, c, e), (b, d, f) = mtx
            uv = [(a * t[0] + c * t[1] + e, b * t[0] + d * t[1] + f) for t in uv]
        for k in range(0, len(sh.indices) - 2, 3):
            ids = sh.indices[k:k + 3]
            if any(j >= len(pos) for j in ids):
                continue
            tris.append((sum(pos[j][2] for j in ids) / 3.0, [pos[j] for j in ids],
                         [uv[j] for j in ids] if uv else None, prog, sh.material))
    return tris


def _texture_for(model, material, textures, name=None):
    """Decoded RGBA PIL image of a material's first texture (or of the embedded texture
    `name`, a material animation's texture-pattern pick), cached in `textures`."""
    tex_name = name or model.material_texture(material, decode=False)[0]
    if not tex_name:
        return None
    if tex_name not in textures:
        ti = model.texture_index(tex_name)
        try:
            t = texture.decode_bntx(model.data, ti) if ti is not None else None
        except Exception:
            t = None
        textures[tex_name] = t.convert("RGBA") if t is not None else None
    return textures[tex_name]


def material_uv_matrices(model, anim, frame):
    """{material index: 2x3 UV matrix} for the materials a `matanim.MatAnimFile` animates
    (bound by material name, as the game binds them), at `frame`. The frame wraps at the
    file's frame count whatever its loop flag, as the game's tick wraps it (matanim.py)."""
    if anim is None:
        return {}
    frame = anim.play_frame(frame)
    out = {}
    for mt in model.materials:
        mtx = anim.uv_matrix(mt.name, frame)
        if mtx is not None:
            out[mt.index] = mtx
    return out


def render(model, view="front", size=512, *, background=(0, 0, 0, 0), textures=None,
           anim=None, frame=0.0, box=None, fast=False):
    """A textured preview of the whole model (orthographic, painter's-sorted triangles,
    no lighting) as a PIL RGBA image of at most `size` px on its longer side. Views:
    front / back / side / top. Map over-models are best seen from the top. `anim` (a
    `matanim.MatAnimFile`, e.g. the model's `.bfmat`) scrolls the animated materials' UVs,
    swaps their albedo texture (texture patterns: eye blinks, emblem swaps) and fades them
    (opacity) to `frame` (game frames, 1 per tick).

    With numpy (the normal case) every pixel interpolates its UV, UVs wrap (repeat),
    costume materials punch alpha out at 0.5, and each material blends the way its
    BlendType tells the game to (see the module notes): 2 and 3 are additive, everything
    else is drawn over. Vertex colour is ignored, as in the game. Without numpy it falls
    back to a per-triangle affine paste that wraps UVs and punches out, but does not blend.

    `fast` samples the textures at the nearest texel instead of bilinearly (one lookup per
    pixel instead of four) -- for live playback, where a frame is on screen for 1/60 s.
    `textures` (a dict kept by the caller across frames) also caches the textures' float
    arrays, so an animation does not convert them again for every frame."""
    from PIL import Image
    proj = VIEWS[view]
    textures = {} if textures is None else textures
    tris = _triangles(model, proj, material_uv_matrices(model, anim, frame))
    from . import matanim
    mstate = matanim.material_state(model, anim, frame) if anim is not None else {}
    if not tris:
        return Image.new("RGBA", (size, size), background)
    xs = [p[0] for t in tris for p in t[1]]
    ys = [p[1] for t in tris for p in t[1]]
    # `box` = fixed (x0, y0, x1, y1) in view space (render_skeletal_animation keeps every
    # frame in one box so the character moves instead of being re-fitted)
    x0, y0, x1, y1 = box if box is not None else (min(xs), min(ys), max(xs), max(ys))
    span = max(x1 - x0, y1 - y0, 1e-6)
    k = (size - 4) / span
    w, h = max(1, int((x1 - x0) * k) + 4), max(1, int((y1 - y0) * k) + 4)
    tris.sort(key=lambda t: t[0])

    def place(pts):
        return [((p[0] - x0) * k + 2, (p[1] - y0) * k + 2) for p in pts]
    try:
        import numpy as np
    except ImportError:
        return _render_affine(model, tris, place, w, h, background, textures, mstate)
    return _render_raster(np, model, tris, place, w, h, background, textures, mstate, fast)


def render_animation(model, anim, view="front", size=320, *, step=2, background=(32, 32, 36, 255),
                     textures=None):
    """One loop of a material animation as [PIL RGBA frames], one every `step` game frames
    (the game advances 1 frame per tick at 60 ticks/s, so step 2 = 30 fps). Every frame is
    fitted to the same box, so the geometry stays still while the UVs move."""
    from PIL import Image
    textures = {} if textures is None else textures
    total = max(1, anim.frame_count if anim is not None else 1)
    frames = [render(model, view, size, background=background, textures=textures, anim=anim, frame=f)
              for f in range(0, total, max(1, step))]
    w = max(f.width for f in frames)
    h = max(f.height for f in frames)
    out = []
    for f in frames:
        if f.size != (w, h):
            g = Image.new("RGBA", (w, h), background)
            g.paste(f, (0, 0))
            f = g
        out.append(f)
    return out


def render_skeletal_animation(model, skel, view="front", size=320, *, step=2,
                              background=(32, 32, 36, 255), textures=None, frames=None):
    """One pass of a `skelanim.SkelAnimFile` (a .bfskl bound to this model by bone name) as
    [PIL RGBA frames], one every `step` game frames (1 animation frame per tick at 60/s).
    Rigid shapes follow their bone, skinned shapes are linear-blend skinned through the
    inverse bind matrices (see `skin_palette`). All frames share one view box. `frames`
    optionally lists the exact frames to draw. The model's pose hook is restored after."""
    from . import skelanim
    textures = {} if textures is None else textures
    total = max(1, skel.frame_count)
    todo = list(frames) if frames is not None else list(range(0, total + (0 if skel.loops else 1), max(1, step)))
    proj = VIEWS[view]
    saved = model.pose
    try:
        poses, box = [], None
        for f in todo:
            model.pose = skelanim.pose_bones(model, skel, f)
            pts = [proj(p) for sh in model.shapes for p in model.shape_vertices(sh)]
            poses.append(model.pose)
            if pts:
                b = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
                box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
        out = []
        for pz in poses:
            model.pose = pz
            out.append(render(model, view, size, background=background, textures=textures, box=box))
    finally:
        model.pose = saved
    return out


def save_gif(frames, path, *, step=2):
    """Write render_animation() frames as a looping GIF at the game's speed (60 ticks/s)."""
    rgb = [f.convert("RGB") for f in frames]
    rgb[0].save(path, save_all=True, append_images=rgb[1:], duration=max(20, round(1000 * step / 60)),
                loop=0, optimize=False)


def _render_raster(np, model, tris, place, w, h, background, textures, mstate=None, fast=False):
    from PIL import Image
    out = np.empty((h, w, 4), np.float32)           # straight (non-premultiplied) RGBA
    out[...] = np.asarray(background, np.float32) / 255.0
    # float copies of the textures, kept in the caller's texture cache across frames
    arrays = textures.setdefault(("__float_arrays__",), {})
    sample = _sample_nearest if fast else _sample_repeat
    grey = np.array([150, 150, 160, 255], np.float32) / 255.0
    for _d, pts, uvs, cols, mat in tris:
        (ax, ay), (bx, by), (cx, cy) = place(pts)
        det = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
        if abs(det) < 1e-9:
            continue
        ix0, iy0 = max(0, int(math.floor(min(ax, bx, cx)))), max(0, int(math.floor(min(ay, by, cy))))
        ix1, iy1 = min(w, int(math.ceil(max(ax, bx, cx))) + 1), min(h, int(math.ceil(max(ay, by, cy))) + 1)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        # pixel centres as a row and a column that broadcast (no full meshgrid per triangle)
        gx = np.arange(ix0, ix1, dtype=np.float32)[None, :] + (0.5 - ax)
        gy = np.arange(iy0, iy1, dtype=np.float32)[:, None] + (0.5 - ay)
        l1 = (gx * (cy - ay) - (cx - ax) * gy) / det
        l2 = ((bx - ax) * gy - gx * (by - ay)) / det
        l0 = 1.0 - l1 - l2
        inside = (l0 >= -1e-4) & (l1 >= -1e-4) & (l2 >= -1e-4)
        if not inside.any():
            continue
        lam = (l0[inside], l1[inside], l2[inside])
        st = mstate.get(mat, {}) if mstate else {}
        tex = _texture_for(model, mat, textures, st.get("texture")) if uvs else None
        if tex is not None:
            arr = arrays.get(id(tex))
            if arr is None:
                arr = arrays[id(tex)] = np.asarray(tex, np.float32) / 255.0
            src = sample(np, arr, sum(l * uvs[i][0] for i, l in enumerate(lam)),
                         sum(l * uvs[i][1] for i, l in enumerate(lam)))
        else:
            src = np.tile(grey, (len(lam[0]), 1))
        if "opacity" in st:
            # rf4cmv: albedo.a *= clamp(opacity.r, 0, 1) before the 1/255 discard
            src = src.copy()
            src[:, 3] *= st["opacity"]
        mt = model.materials[mat] if 0 <= mat < len(model.materials) else None
        blend = mt.blend_type if mt is not None else 0
        keep = _alpha_keep(np, cols, src[:, 3])
        if keep is not None:
            if not keep.any():
                continue
            src = src[keep]
            sub = np.zeros_like(inside)
            sub[inside] = keep
            inside = sub
        if cols == "body":
            src[:, 3] = 1.0
        region = out[iy0:iy1, ix0:ix1]
        d = region[inside]
        da, sa = d[:, 3:4], src[:, 3:4]
        if blend in (2, 3):
            # colour = dst + src * (SrcAlpha | One): premultiplied sum, coverage grows with
            # the added light so the preview also reads on a transparent background
            add = src[:, :3] * (sa if blend == 2 else 1.0)
            rgb = d[:, :3] * da + add
            a = np.clip(np.maximum(da, add.max(axis=1, keepdims=True)), 0.0, 1.0)
        else:
            a = sa + da * (1.0 - sa)
            rgb = src[:, :3] * sa + d[:, :3] * da * (1.0 - sa)
        d[:, :3] = np.clip(rgb / np.maximum(a, 1e-6), 0.0, 1.0)
        d[:, 3:4] = a
        region[inside] = d
    return Image.fromarray(np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8), "RGBA")


def _alpha_keep(np, program, alpha):
    """Boolean mask of the fragments the game keeps: mtk_body rounds alpha (keeps >= 0.5),
    mtk_item discards alpha <= 0.1."""
    if program == "body":
        return alpha >= BODY_ALPHA_CUT
    return alpha > ITEM_ALPHA_CUT


def _sample_repeat(np, arr, u, v):
    """Bilinear samples of `arr` (H, W, 4 floats) at UVs with REPEAT wrap (v = 0 is the top row)."""
    th, tw = arr.shape[:2]
    x = np.mod(u, 1.0) * tw - 0.5
    y = np.mod(v, 1.0) * th - 0.5
    xf, yf = np.floor(x), np.floor(y)
    fx, fy = (x - xf)[:, None], (y - yf)[:, None]
    x0, y0 = xf.astype(np.int64) % tw, yf.astype(np.int64) % th
    x1, y1 = (x0 + 1) % tw, (y0 + 1) % th
    top = arr[y0, x0] * (1 - fx) + arr[y0, x1] * fx
    bot = arr[y1, x0] * (1 - fx) + arr[y1, x1] * fx
    return top * (1 - fy) + bot * fy


def _sample_nearest(np, arr, u, v):
    """Nearest-texel samples of `arr` (H, W, 4 floats) at UVs with REPEAT wrap -- the cheap
    sampler render(fast=True) uses for live playback (a copy, so callers may modify it)."""
    th, tw = arr.shape[:2]
    x = (np.mod(u, 1.0) * tw).astype(np.int64) % tw
    y = (np.mod(v, 1.0) * th).astype(np.int64) % th
    return arr[y, x]


def _render_affine(model, tris, place, w, h, background, textures, mstate=None):
    """numpy-free fallback: one affine texture paste per triangle (UVs wrap; no vertex
    colour, no blend modes)."""
    from PIL import Image, ImageChops, ImageDraw
    img = Image.new("RGBA", (w, h), background)
    flat = ImageDraw.Draw(img)
    for _d, pts, uvs, prog, mat in tris:
        dst = place(pts)
        st = mstate.get(mat, {}) if mstate else {}
        tex = _texture_for(model, mat, textures, st.get("texture")) if uvs else None
        if tex is not None and "opacity" in st:
            tex = tex.copy()
            tex.putalpha(tex.getchannel("A").point(lambda a, k=st["opacity"]: int(a * k + 0.5)))
        mt = model.materials[mat] if 0 <= mat < len(model.materials) else None
        if tex is not None and prog == "body":
            cut = int(BODY_ALPHA_CUT * 255 + 0.5)
            tex = tex.copy()
            tex.putalpha(tex.getchannel("A").point(lambda a: 255 if a >= cut else 0))
        elif tex is not None:
            cut = int(ITEM_ALPHA_CUT * 255)
            tex = tex.copy()
            tex.putalpha(tex.getchannel("A").point(lambda a: a if a > cut else 0))
        if tex is None:
            flat.polygon(dst, fill=(150, 150, 160, 255))
            continue
        src_img, src = _wrapped_source(tex, [uv[:2] for uv in uvs])
        bx0, by0 = int(math.floor(min(p[0] for p in dst))), int(math.floor(min(p[1] for p in dst)))
        bx1, by1 = int(math.ceil(max(p[0] for p in dst))), int(math.ceil(max(p[1] for p in dst)))
        if bx1 <= bx0 or by1 <= by0:
            continue
        coeffs = _affine_dst_to_src(dst, src, bx0, by0)
        if coeffs is None:
            continue
        patch = src_img.transform((bx1 - bx0, by1 - by0), Image.AFFINE, coeffs, resample=Image.BILINEAR)
        mask = Image.new("L", patch.size, 0)
        ImageDraw.Draw(mask).polygon([(x - bx0, y - by0) for x, y in dst], fill=255)
        patch.putalpha(ImageChops.multiply(patch.getchannel("A"), mask))
        _paste_clipped(img, patch, bx0, by0)
        flat = ImageDraw.Draw(img)
    return img


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #
def _model_space_normals(model, sh, nrm):
    """`_n0` in model space, in the same (bind-pose) frames as the exported positions: the
    shape's bone for skin 0, the `_i0` bone for skin 1, as stored for smooth skins (inverse
    transpose of the bone's linear part, renormalised). modelwrite.import_obj inverts this."""
    if not nrm or sh.skin >= 2:
        return nrm
    vb = model.vertex_buffers[sh.vertex_buffer]
    m2b = model.matrix_to_bone
    cache = {}

    def nmat(b):
        if b not in cache:
            m = model.bone_matrix(b)
            a = [row[:3] for row in m[:3]]
            c = [[a[(r + 1) % 3][(k + 1) % 3] * a[(r + 2) % 3][(k + 2) % 3]
                  - a[(r + 1) % 3][(k + 2) % 3] * a[(r + 2) % 3][(k + 1) % 3] for k in range(3)]
                 for r in range(3)]                     # cofactors = det * inverse transpose
            if sum(a[0][k] * c[0][k] for k in range(3)) < 0:    # mirrored bone: keep the side
                c = [[-x for x in row] for row in c]
            cache[b] = c
        return cache[b]
    ix = vb.data.get("_i0")
    out = []
    for k, n in enumerate(nrm):
        b = sh.bone if sh.skin == 0 or not ix else (m2b[ix[k][0]] if ix[k][0] < len(m2b) else ix[k][0])
        c = nmat(b)
        v = [c[r][0] * n[0] + c[r][1] * n[1] + c[r][2] * n[2] for r in range(3)]
        ln = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        out.append(tuple(x / ln for x in v) if ln > 1e-20 else tuple(n[:3]))
    return out


def to_obj(model, stem="model"):
    """Wavefront OBJ + MTL text for the whole model (model space; one object per shape,
    one material per g3d material, textures referenced as <texture name>.png)."""
    o = [f"# RF4S .model -> OBJ ({len(model.shapes)} shapes)", f"mtllib {stem}.mtl"]
    base = 1
    for sh in model.shapes:
        vb = model.vertex_buffers[sh.vertex_buffer]
        pos = model.shape_vertices(sh)
        uv = vb.data.get("_u0")
        nrm = _model_space_normals(model, sh, vb.data.get("_n0"))
        o.append(f"o {sh.name or 'shape%d' % sh.index}")
        mat = model.materials[sh.material] if sh.material < len(model.materials) else None
        if mat:
            o.append(f"usemtl {mat.name or 'mat%d' % mat.index}")
        o += ["v %.6f %.6f %.6f" % p for p in pos]
        if uv:
            o += ["vt %.6f %.6f" % (t[0], 1.0 - t[1]) for t in uv]
        if nrm:
            o += ["vn %.6f %.6f %.6f" % tuple(t[:3]) for t in nrm]
        for k in range(0, len(sh.indices) - 2, 3):
            a, b, c = (base + j for j in sh.indices[k:k + 3])
            if uv and nrm:
                o.append(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}")
            elif uv:
                o.append(f"f {a}/{a} {b}/{b} {c}/{c}")
            else:
                o.append(f"f {a} {b} {c}")
        base += len(pos)
    m = []
    for mat in model.materials:
        m.append(f"newmtl {mat.name or 'mat%d' % mat.index}")
        m.append("Kd 1.000 1.000 1.000")
        if mat.textures:
            m.append(f"map_Kd {mat.textures[0]}.png")
            m.append(f"map_d {mat.textures[0]}.png")
    return "\n".join(o) + "\n", "\n".join(m) + "\n"


def export_obj(model, out_dir, stem="model"):
    """Write <stem>.obj, <stem>.mtl and every texture as PNG into out_dir. Returns the
    list of written paths."""
    import pathlib
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    obj, mtl = to_obj(model, stem)
    written = [out / f"{stem}.obj", out / f"{stem}.mtl"]
    written[0].write_text(obj, encoding="utf-8")
    written[1].write_text(mtl, encoding="utf-8")
    for t in model.textures:
        try:
            im = texture.decode_bntx(model.data, t["index"])
        except Exception:
            im = None
        if im is not None:
            p = out / f"{t['name']}.png"
            im.save(p)
            written.append(p)
    return written


def user_data_text(material):
    """'po=18.1, DrawOrder=2' -- a material's user data, floats rounded to float32 precision."""
    def fmt(v):
        return f"{v:.6g}" if isinstance(v, float) else str(v)
    return ", ".join(f"{k}={fmt(v[0]) if len(v) == 1 else '[' + ', '.join(map(fmt, v)) + ']'}"
                     for k, v in material.user_data.items())


def summary(model):
    lines = [f"{len(model.shapes)} shapes, {len(model.vertex_buffers)} vertex buffers, "
             f"{len(model.bones)} bones, {len(model.materials)} materials, "
             f"{len(model.textures)} textures"]
    for sh in model.shapes:
        vb = model.vertex_buffers[sh.vertex_buffer]
        mat = model.materials[sh.material] if sh.material < len(model.materials) else None
        lines.append(f"  {sh.index:3} {sh.name:<14} {vb.count:5} v {len(sh.indices) // 3:5} t  "
                     f"bone {sh.bone:<3} skin {sh.skin}  mat {mat.name if mat else sh.material}")
    return "\n".join(lines)
