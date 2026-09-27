r"""
meshimport.py -- glTF / GLB meshes back into an RF4S `.model` (the way back from Blender).

`import_glb(data, path)` reads every mesh of a .glb / .gltf -- as `gltf.export_glb` (Export for
Blender) writes it, or as Blender's own glTF exporter writes it after editing -- matches each to
the model's shape of the same name and rebuilds those shapes' vertex / index buffers through
`modelwrite.rebuild` (any vertex / triangle count). Unlike the OBJ path the bone weights come
from the file (JOINTS_n / WEIGHTS_n): weight painting in Blender reaches the game.

What a vertex record can hold (all 2,705 shipped shapes, 2026-09-27): `_p0` / `_n0` float3,
`_u0` float2, optional `_c0` float3/4 (ignored by the game, see model.py), and for skinned
shapes `_i0` uint32 x N + `_w0` float32 x N with N = the shape's skin count (SHAP+0x66 = VRTX
+0x5C; 1, 2, 3 or 4). So weights are stored as float32 -- nothing to quantise -- and:
  * skin 0  -- no weights; the shape rides its bone (SHAP+0x60). Weights in the file are
               ignored (the report counts vertices weighted to another bone).
  * skin 1  -- `_i0` = ONE rigid matrix (index >= SKEL+0x4E into the matrix-to-bone table,
               true for all 373 shipped skin-1 shapes); the vertex is stored in that bone's
               space. The heaviest influence wins.
  * skin 2+ -- `_i0` = N smooth matrices (index < SKEL+0x4E, all 299 shipped), `_w0` their
               weights, the vertex in bind-pose model space. The N heaviest influences are
               kept and renormalised to sum 1 (every shipped vertex sums to 1), sorted
               heaviest first; unused slots repeat slot 0's index with weight 0 (the shipped
               convention: 100,248 unused slots, all of them).
A bone can only be used when it HAS the right kind of matrix: the bone record's u16 at +0x2C
(smooth matrix, -1 = none) / +0x2E (rigid matrix) -- consistent with the matrix-to-bone table
on all 7,935 shipped bones, 3,104 of which have neither. Adding a matrix would mean growing the
SKEL tables and renumbering every rigid `_i0` of the model, which this module does not do: an
influence on a bone without one moves to its nearest ANCESTOR that has one (named in the
report), exactly what the game would show if the missing bone never moved on its own.

The "palette" is the model-wide matrix-to-bone table, not a per-shape list: the skinning
shader indexes the palette the skin-matrix builder (RF4S.exe+0x3D8650) fills for every smooth
and rigid matrix of the skeleton. SHAP+0x28 -> u16[SHAP+0x64] lists the bones a shape's
vertices use (sorted; equal to the used set on all 672 shipped skinned shapes). No instruction
of RF4S.exe reads SHAP+0x64 as a word (offline capstone scan of .text for every [reg+0x64]
16-bit operand, 2026-09-27: the hits are crop / combat / font / animation-binding fields), so
the list is informational; it is rewritten in place when the new set fits its old length and
otherwise left as is (reported).

Frames (the same as the OBJ path, modelwrite._Frames): skin 0 = the shape bone's space, skin 1
= the `_i0` bone's space, skin 2+ = model space. glTF positions are taken into model space
first: skinned meshes by their joints (sum w * inv(A) * world(joint) * inverseBind(joint) * p,
A = the node the skeleton hangs from -- Blender's armature object, identity in our own files;
joint matrices within 1e-4 of identity are taken as identity, which they are whenever the rest
pose was not edited), other meshes by their node's world matrix (relative to A as well).
When the model is known, a joint named like one of its bones takes that BONE's bind world
matrix instead of the file's node: Blender's armatures cannot hold a rest scale (36 shipped
bones have one, e.g. efc_tornado's 1.25 / 0.8, wI_Fist*'s mirrored -0.674), so its glTF
export writes those bones unscaled and the IBMs to match, and only the game's own matrix
brings such a mesh back where Blender shows it (posed at the imported file's pose).

Round trips. A vertex whose model-space position (within 1e-5 of the model's size), UV (1e-5),
normal (dot >= 0.9995) and weights (same bones, within 2e-3) match an original vertex of the
shape keeps that vertex's original bytes; when EVERY vertex matches and the triangles are the
original ones (in any order, any rotation), the shape is left untouched. So an unmodified
Export for Blender file re-imports byte-identically (all 912 mesh .model files), and so does a
Blender 5.2 import -> export round trip, whose positions move by ~1e-5 and normals by ~1e-4
(float noise of its Z-up conversion) and whose vertex order changes: 55 of 61 sampled models
(every 15th) came back byte-identical; in the other 6 Blender re-split a few triangles or, under
a non-uniformly scaled bone, re-derived the normals, and the renders (front and top, 256 px)
are pixel-identical (selftest test_model_glb_import / test_model_glb_blender). Other vertices are built fresh: non-geometry
attributes (`_c0`) copied from the nearest original vertex, then position / normal / UV /
weights from the file. Identical records are shared (the index buffer references them once).

Statically verified only (no in-game test): see modelwrite.py for the loader's pool / buffer
rules this relies on.
"""
from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass, field

from . import gltf as _gltf
from . import model as _model
from . import modelwrite as _mw


class MeshImportError(Exception):
    pass


POS_EPS_REL = 1e-5            # of the model's bounding-box diagonal
UV_EPS = 1e-5
NORMAL_DOT = 0.9995
WEIGHT_EPS = 2e-3
IDENTITY_EPS = 1e-4           # a joint matrix this close to identity is identity


# --------------------------------------------------------------------------- #
# reading glTF meshes into model space
# --------------------------------------------------------------------------- #
@dataclass
class GltfMesh:
    """One glTF mesh node, all its triangle primitives joined, in the model's space."""
    name: str                   # node name (Blender: the object name)
    mesh_name: str
    positions: list             # [(x, y, z)] model space
    normals: list | None        # [(x, y, z)] model space, unit
    uvs: list | None            # [(u, v)] buffer convention (as TEXCOORD_0: v = 0 at the top)
    colors: list | None         # [(r, g, b, a)] COLOR_0
    weights: list | None        # [{bone name: weight}] (None: an unskinned mesh)
    triangles: list             # [(a, b, c)]
    materials: list = field(default_factory=list)   # material names of the primitives
    skipped_primitives: int = 0                      # points / lines


def _node_local(nd):
    if "matrix" in nd:
        m = nd["matrix"]
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    t = nd.get("translation", (0.0, 0.0, 0.0))
    q = nd.get("rotation", (0.0, 0.0, 0.0, 1.0))
    s = nd.get("scale", (1.0, 1.0, 1.0))
    r = _gltf.quat_to_matrix(q)
    return [[r[0][0] * s[0], r[0][1] * s[1], r[0][2] * s[2], t[0]],
            [r[1][0] * s[0], r[1][1] * s[1], r[1][2] * s[2], t[1]],
            [r[2][0] * s[0], r[2][1] * s[1], r[2][2] * s[2], t[2]],
            [0.0, 0.0, 0.0, 1.0]]


def _node_worlds(gl):
    nodes = gl.get("nodes", [])
    parent = {}
    for i, nd in enumerate(nodes):
        for c in nd.get("children", []):
            parent[c] = i
    out = [None] * len(nodes)

    def get(i, depth=0):
        if out[i] is None:
            loc = _node_local(nodes[i])
            p = parent.get(i)
            out[i] = _model._mul(get(p, depth + 1), loc) if p is not None and depth < len(nodes) else loc
        return out[i]
    for i in range(len(nodes)):
        get(i)
    return out, parent


def _near_identity(m):
    return all(abs(m[r][c] - (1.0 if r == c else 0.0)) < IDENTITY_EPS for r in range(3) for c in range(4))


def _skin_root_frame(gl, worlds, parent, skin):
    """World matrix of the node the skin's joint tree hangs from (identity when none)."""
    js = set(skin.get("joints", []))
    for j in skin.get("joints", []):
        p = parent.get(j)
        if p is None or p not in js:
            return worlds[p] if p is not None else _model._identity()
    return _model._identity()


def _prim_triangles(prim, idx, n):
    mode = prim.get("mode", 4)
    if idx is None:
        idx = list(range(n))
    idx = [int(i) for i in idx]
    if mode == 4:
        return [tuple(idx[k:k + 3]) for k in range(0, len(idx) - 2, 3)]
    if mode == 5:
        return [(idx[k], idx[k + 1], idx[k + 2]) if k % 2 == 0 else (idx[k + 1], idx[k], idx[k + 2])
                for k in range(len(idx) - 2)]
    if mode == 6:
        return [(idx[0], idx[k], idx[k + 1]) for k in range(1, len(idx) - 1)]
    return None


def read_meshes(path, model=None):
    """[GltfMesh] of every mesh node of a glTF / GLB (a path, or read_gltf's (json, buffers)).
    With `model`, a joint named like one of its bones is placed by that bone's bind world
    matrix instead of the file's rest pose (see the module notes: Blender cannot keep a
    bone's rest scale)."""
    gl, bufs = path if isinstance(path, tuple) else _gltf.read_gltf(path)
    game = {}
    if model is not None:
        wm = _model.world_matrices(model.bones)
        game = {b.name: wm[b.index] for b in model.bones}
    worlds, parent = _node_worlds(gl)
    nodes = gl.get("nodes", [])
    skins = gl.get("skins", [])
    mats = gl.get("materials", [])
    default_frame = _skin_root_frame(gl, worlds, parent, skins[0]) if skins else _model._identity()
    out = []
    for ni, nd in enumerate(nodes):
        if "mesh" not in nd:
            continue
        me = gl["meshes"][nd["mesh"]]
        skin = skins[nd["skin"]] if "skin" in nd and nd["skin"] < len(skins) else None
        A = _skin_root_frame(gl, worlds, parent, skin) if skin else default_frame
        Ai = _mw._inv4(A)
        if skin:
            joints = skin.get("joints", [])
            ibm = (_gltf.read_accessor(gl, bufs, skin["inverseBindMatrices"])
                   if "inverseBindMatrices" in skin else [None] * len(joints))
            jm, jname = [], []
            for j, b in zip(joints, ibm):
                B = [[b[c * 4 + r] for c in range(4)] for r in range(4)] if b else _model._identity()
                nm = nodes[j].get("name")
                W = game[nm] if nm in game else _model._mul(Ai, worlds[j])
                m = _model._mul(W, B)
                jm.append(None if _near_identity(m) else m)
                jname.append(nodes[j].get("name") or f"node{j}")
        else:
            M = _model._mul(Ai, worlds[ni])
            node_m = None if _near_identity(M) else M
        pos, nrm, uv, col, wts, tris, mnames = [], [], [], [], [], [], []
        has_n = has_uv = has_col = True
        skipped = 0
        for prim in me.get("primitives", []):
            at = prim.get("attributes", {})
            if "POSITION" not in at:
                continue
            for a in at.values():
                if "sparse" in gl["accessors"][a]:
                    raise MeshImportError(f"mesh {me.get('name')!r}: sparse accessors are not supported")
            P = _gltf.read_accessor(gl, bufs, at["POSITION"])
            idx = _gltf.read_accessor(gl, bufs, prim["indices"]) if "indices" in prim else None
            t = _prim_triangles(prim, idx, len(P))
            if t is None:
                skipped += 1
                continue
            base = len(pos)
            N = _gltf.read_accessor(gl, bufs, at["NORMAL"]) if "NORMAL" in at else None
            T = _gltf.read_accessor(gl, bufs, at["TEXCOORD_0"]) if "TEXCOORD_0" in at else None
            C = _gltf.read_accessor(gl, bufs, at["COLOR_0"]) if "COLOR_0" in at else None
            has_n &= N is not None
            has_uv &= T is not None
            has_col &= C is not None
            W = None
            if skin:
                sets = []
                k = 0
                while f"JOINTS_{k}" in at and f"WEIGHTS_{k}" in at:
                    sets.append((_gltf.read_accessor(gl, bufs, at[f"JOINTS_{k}"]),
                                 _gltf.read_accessor(gl, bufs, at[f"WEIGHTS_{k}"])))
                    k += 1
                if sets:
                    W = []
                    for v in range(len(P)):
                        d = {}
                        for J, Wt in sets:
                            for j, w in zip(J[v], Wt[v]):
                                if w > 0 and 0 <= int(j) < len(jname):
                                    d[int(j)] = d.get(int(j), 0.0) + float(w)
                        W.append(d)
            for v in range(len(P)):
                p = P[v]
                n = N[v] if N is not None else None
                if skin and W is not None and W[v]:
                    tot = sum(W[v].values())
                    mats_ = [(jm[j], w / tot) for j, w in W[v].items()]
                    if any(m is not None for m, _w in mats_):
                        acc = [[sum(w * (m[r][c] if m is not None else (1.0 if r == c else 0.0))
                                    for m, w in mats_) for c in range(4)] for r in range(4)]
                        p = _model._apply(acc, p)
                        if n is not None:
                            n = _mw._norm(_mw._mv3(_mw._t3(_mw._inv3(_mw._lin(acc))), n))
                elif not skin and node_m is not None:
                    p = _model._apply(node_m, p)
                    if n is not None:
                        n = _mw._norm(_mw._mv3(_mw._t3(_mw._inv3(_mw._lin(node_m))), n))
                pos.append(tuple(float(x) for x in p[:3]))
                nrm.append(tuple(float(x) for x in n[:3]) if n is not None else None)
                uv.append(tuple(T[v][:2]) if T is not None else None)
                col.append((tuple(C[v]) + (1.0,))[:4] if C is not None else None)
                if skin:
                    wts.append({jname[j]: w for j, w in W[v].items()} if W is not None else {})
            tris += [(a + base, b + base, c + base) for a, b, c in t]
            mi = prim.get("material")
            mnames.append(mats[mi].get("name", f"material{mi}") if mi is not None and mi < len(mats) else None)
        if not tris:
            continue
        out.append(GltfMesh(nd.get("name") or me.get("name") or f"mesh{ni}", me.get("name") or "",
                            pos, nrm if has_n else None, uv if has_uv else None,
                            col if has_col else None, wts if skin else None, tris, mnames, skipped))
    return out


# --------------------------------------------------------------------------- #
# matching meshes to shapes
# --------------------------------------------------------------------------- #
_SUFFIX = re.compile(r"\.\d{3,}$")


def match_shapes(m, meshes):
    """({shape index: GltfMesh}, [unmatched GltfMesh]): a mesh goes to the shape named like
    its node (Export for Blender names both node and mesh after the shape), else like its mesh,
    else -- when that name is unique -- like its node name without Blender's '.001' suffix."""
    names = {(sh.name or f"shape{sh.index}"): sh.index for sh in m.shapes}
    plan, rest = {}, []
    for me in meshes:
        si = names.get(me.name)
        if si is None or si in plan:
            si = names.get(me.mesh_name) if names.get(me.mesh_name) not in plan else None
        if si is None:
            rest.append(me)
        else:
            plan[si] = me
    left = []
    for me in rest:
        base = _SUFFIX.sub("", me.name)
        si = names.get(base)
        if si is not None and si not in plan and sum(_SUFFIX.sub("", x.name) == base for x in rest) == 1:
            plan[si] = me
        else:
            left.append(me)
    return plan, left


# --------------------------------------------------------------------------- #
# building the vertex records
# --------------------------------------------------------------------------- #
def _bone_matrices(data, m):
    """({bone: smooth matrix}, {bone: rigid matrix}) from the bone records (+0x2C / +0x2E)."""
    M = _mw._u64(data, 0x28)
    S = _mw._u64(data, M + 0x20)
    smooth, rigid = {}, {}
    if data[S:S + 4] != b"SKEL":
        return smooth, rigid
    base = _mw._u64(data, S + 0x18)
    for b in range(len(m.bones)):
        sm, rg = struct.unpack_from("<hh", data, base + 0x60 * b + 0x2C)
        if sm >= 0:
            smooth[b] = sm
        if rg >= 0:
            rigid[b] = rg
    return smooth, rigid


def _usable(m, b, table):
    """`b` or its nearest ancestor present in `table` (None when no ancestor is)."""
    seen = 0
    while 0 <= b < len(m.bones) and seen <= len(m.bones):
        if b in table:
            return b
        b = m.bones[b].parent
        seen += 1
    return None


def _write(rec, attrs, name, vals):
    for n, f, o in attrs:
        if n == name and f:
            k = int(f[1:-1])
            vals = (list(vals) + [vals[-1] if f[-1] != "f" else 0.0] * k)[:k]
            if f[-1] == "I":
                vals = [int(v) for v in vals]
            struct.pack_into(f, rec, o, *vals)
            return True
    return False


@dataclass
class ShapeReport:
    shape: int
    name: str
    mesh: str
    vertices: int = 0
    triangles: int = 0
    kept: int = 0               # vertices that kept their original bytes
    unchanged: bool = False
    moved_influences: dict = field(default_factory=dict)   # bone name -> ancestor it went to
    dropped_influences: int = 0     # vertices with more influences than the format stores
    ignored_weights: int = 0        # skin-0 vertices weighted to another bone
    notes: list = field(default_factory=list)

    def text(self):
        if self.unchanged:
            return f"shape {self.shape} {self.name}: unchanged"
        s = (f"shape {self.shape} {self.name} <- {self.mesh}: {self.vertices} vertices "
             f"({self.kept} original), {self.triangles} triangles")
        extra = []
        if self.moved_influences:
            extra.append("weights moved to an ancestor with a skinning matrix: "
                         + ", ".join(f"{a} -> {b}" for a, b in sorted(self.moved_influences.items())))
        if self.dropped_influences:
            extra.append(f"{self.dropped_influences} vertices had more bone influences than the shape "
                         f"stores; the heaviest were kept")
        if self.ignored_weights:
            extra.append(f"{self.ignored_weights} vertices weighted to other bones (this shape is rigid: "
                         f"it follows its own bone)")
        return s + "".join("\n    " + e for e in extra + self.notes)


def shape_geometry_from_mesh(data, shape, mesh, m=None, L=None):
    """(ShapeGeometry or None when the mesh reproduces the shape, ShapeReport) for one
    shape from a GltfMesh (see the module notes)."""
    m = m or _model.parse(data)
    L = L or _mw.layout(data)
    si = _mw.resolve_shape(m, shape)
    sh, shp = L.shapes[si], m.shapes[si]
    rep = ShapeReport(si, shp.name, mesh.name)
    attrs, stride = _mw._vertex_format(data, sh)
    names = {a[0]: a for a in attrs}
    if "_p0" not in names or names["_p0"][1] is None or names["_p0"][1][-1] != "f":
        raise MeshImportError(f"shape {si}: no float _p0 attribute")
    if sh.index_format != 2 or shp.primitive != 3:
        raise MeshImportError(f"shape {si}: not a u32 triangle list")
    recs = _mw._records(data, L, sh)
    if not recs:
        raise MeshImportError(f"shape {si} has no vertices to take the attribute defaults from")
    skin = shp.skin
    vb = m.vertex_buffers[shp.vertex_buffer]
    if skin >= 1 and "_i0" not in names:
        raise MeshImportError(f"shape {si}: skin {skin} but no _i0 attribute")
    smooth, rigid = _bone_matrices(data, m)
    by_name = {b.name: b.index for b in m.bones}
    # the original vertices as Export for Blender writes them
    saved, m.pose = m.pose, None
    try:
        o_pos = m.shape_vertices(shp)
        o_nrm = _model._model_space_normals(m, shp, vb.data.get("_n0"))
        size = _gltf._extent(m)
    finally:
        m.pose = saved
    o_uv = vb.data.get("_u0")
    # as Export for Blender stores them (float32), so an unmodified vertex compares exactly
    o_pos = [_f32(p) for p in o_pos]
    o_nrm = [_f32(n[:3]) for n in o_nrm] if o_nrm else o_nrm
    o_uv = [_f32(t[:2]) for t in o_uv] if o_uv else o_uv
    o_w = []
    for js, ws in _gltf._vertex_joints(m, shp, vb):
        d = {}
        for j, w in zip(js, ws):                # a matrix may appear twice (BM_00): add up
            if w > 0:
                d[j] = d.get(j, 0.0) + w
        o_w.append(d)
    eps = max(1e-6, POS_EPS_REL * size)

    # per imported vertex: {bone: weight} as it will be stored (None = copy from the nearest)
    def stored_weights(wmap):
        if wmap is None or not wmap:
            return None
        acc = {}
        for bname, w in wmap.items():
            b = by_name.get(bname)
            if b is None:
                raise MeshImportError(f"mesh {mesh.name!r}: bone {bname!r} is not in the model's skeleton")
            acc[b] = acc.get(b, 0.0) + w
        if skin == 0:
            if any(b != shp.bone and w > 1e-3 for b, w in acc.items()):
                rep.ignored_weights += 1
            return {shp.bone: 1.0}
        table = rigid if skin == 1 else smooth
        moved = {}
        for b, w in acc.items():
            u = _usable(m, b, table)
            if u is None:
                raise MeshImportError(
                    f"mesh {mesh.name!r}: bone {m.bones[b].name!r} has no "
                    f"{'rigid' if skin == 1 else 'smooth'} skinning matrix and no ancestor has one")
            if u != b:
                rep.moved_influences[m.bones[b].name] = m.bones[u].name
            moved[u] = moved.get(u, 0.0) + w
        top = sorted(moved.items(), key=lambda kv: (-kv[1], kv[0]))
        n = 1 if skin == 1 else skin
        if len(top) > n:
            rep.dropped_influences += 1
        top = top[:n]
        tot = sum(w for _b, w in top) or 1.0
        if skin == 1:
            return {top[0][0]: 1.0}
        return {b: w / tot for b, w in top}

    nv = len(mesh.positions)
    wts = [stored_weights(mesh.weights[k]) if mesh.weights is not None else None for k in range(nv)]

    # match imported vertices to original ones
    try:
        import numpy as np
    except ImportError:
        np = None
    match = [None] * nv

    def best(k, cands):
        # the closest original that passes every tolerance; on a tie the same slot (an
        # unmodified export keeps its vertex order, and identical records stay apart)
        top = None
        for o, d2 in cands:
            sc = _vertex_score(mesh, k, wts[k], o, o_uv, o_nrm, o_w, skin)
            if sc is None:
                continue
            sc += d2 / (eps * eps)
            if top is None or sc < top[0] or (sc == top[0] and o == k):
                top = (sc, o)
        return top[1] if top else None
    if np is not None:
        O = np.asarray(o_pos, np.float64)
        Q = np.asarray(mesh.positions, np.float64)
        for c0 in range(0, nv, 1024):
            d = ((Q[c0:c0 + 1024, None, :] - O[None, :, :]) ** 2).sum(axis=2)
            for r, row in enumerate(d):
                idx = np.nonzero(row <= eps * eps)[0]
                match[c0 + r] = best(c0 + r, zip(idx.tolist(), row[idx].tolist()))
    else:
        for k in range(nv):
            d2 = [sum((mesh.positions[k][j] - o_pos[o][j]) ** 2 for j in range(3)) for o in range(len(o_pos))]
            match[k] = best(k, [(o, x) for o, x in enumerate(d2) if x <= eps * eps])
    orig_idx = list(shp.indices)
    if all(x is not None for x in match):
        # compared by record bytes: identical original records (duplicates) are interchangeable
        rid = {}
        key = [rid.setdefault(bytes(r), len(rid)) for r in recs]
        mapped = [tuple(key[match[i]] for i in t) for t in mesh.triangles]
        if sorted(_canon(t) for t in mapped) == sorted(_canon(tuple(key[i] for i in orig_idx[k:k + 3]))
                                                      for k in range(0, len(orig_idx) - 2, 3)):
            rep.unchanged = True
            rep.vertices, rep.triangles, rep.kept = len(recs), len(orig_idx) // 3, len(recs)
            return None, rep

    # build the records
    fr = _mw._Frames(m, shp, attrs)
    need = [k for k in range(nv) if match[k] is None]
    near = dict(zip(need, _mw._nearest(o_pos, [mesh.positions[k] for k in need]))) if need else {}
    face_n = None
    if mesh.normals is None and "_n0" in names:
        face_n = _mw._face_normals([(p, None, None) for p in mesh.positions], mesh.triangles)
    blob = bytearray()
    raw = []
    seen = {}
    remap = []
    ppos = names["_p0"][2]
    for k in range(nv):
        if match[k] is not None:
            rec = bytes(recs[match[k]])
            rep.kept += 1
        else:
            r = bytearray(recs[near[k]])
            w = wts[k]
            if w is not None and skin >= 1:
                top = sorted(w.items(), key=lambda kv: (-kv[1], kv[0]))
                table = rigid if skin == 1 else smooth
                ix = [table[b] for b, _w in top]
                _write(r, attrs, "_i0", ix + [ix[0]] * (max(1, skin) - len(ix)))
                if skin >= 2:
                    ws = [struct.unpack("<f", struct.pack("<f", x))[0] for _b, x in top]
                    _write(r, attrs, "_w0", ws + [0.0] * (skin - len(ws)))
            n = mesh.normals[k] if mesh.normals is not None else (face_n[k] if face_n else None)
            pl, nl = fr.from_model(r, mesh.positions[k], n)
            _mw._put(r, attrs, "_p0", pl)
            if nl is not None and "_n0" in names:
                _mw._put(r, attrs, "_n0", nl)
            if mesh.uvs is not None and "_u0" in names:
                _mw._put(r, attrs, "_u0", mesh.uvs[k])
            if mesh.colors is not None and "_c0" in names and names["_c0"][1] and names["_c0"][1][-1] == "f":
                _mw._put(r, attrs, "_c0", mesh.colors[k])
            rec = bytes(r)
        hit = seen.get(rec)
        if hit is None:
            hit = seen[rec] = len(raw)
            blob += rec
            raw.append(struct.unpack_from("<3f", rec, ppos))
        remap.append(hit)
    idx = [remap[i] for t in mesh.triangles for i in t]
    if not idx:
        raise MeshImportError(f"mesh {mesh.name!r} has no triangles")
    box, rad = _mw._shape_bounds(data, sh, raw)
    g = _mw.ShapeGeometry(bytes(blob), idx, box, rad)
    rep.vertices, rep.triangles = len(raw), len(idx) // 3
    if len(set(mesh.materials)) > 1:
        rep.notes.append(f"the mesh has {len(set(mesh.materials))} materials; the shape draws all of it "
                         f"with its own material")
    return g, rep


def _f32(t):
    return struct.unpack("<%df" % len(t), struct.pack("<%df" % len(t), *t))


def _canon(t):
    k = t.index(min(t))
    return t[k:] + t[:k]


def _vertex_score(mesh, k, w, o, o_uv, o_nrm, o_w, skin):
    """None when imported vertex k is not original vertex o within the tolerances, else how
    far off it is (0 = identical; each tolerance counts 1)."""
    sc = 0.0
    if mesh.uvs is not None and o_uv is not None:
        du = max(abs(a - b) for a, b in zip(mesh.uvs[k], o_uv[o][:2]))
        if du > UV_EPS:
            return None
        sc += du / UV_EPS
    if mesh.normals is not None and o_nrm is not None:
        dot = sum(a * b for a, b in zip(mesh.normals[k], o_nrm[o][:3]))
        if dot < NORMAL_DOT:
            return None
        sc += max(abs(a - b) for a, b in zip(mesh.normals[k], o_nrm[o][:3])) / 0.03   # 0 when identical
    if w is not None and skin >= 1:
        ow = o_w[o]
        if set(w) != set(ow):
            return None
        dw = max(abs(w[b] - ow[b]) for b in w)
        if dw > WEIGHT_EPS:
            return None
        sc += dw / WEIGHT_EPS
    return sc


def _update_skin_bones(out, sh, shp, g, attrs, stride, m, smooth, rigid):
    """Rewrite SHAP+0x28 -> u16[SHAP+0x64] with the bones the new vertices use, in place when
    it fits (returns False when it does not)."""
    if shp.skin < 1:
        return True
    m2b = m.matrix_to_bone
    used = set()
    ix_f = [(f, o) for n, f, o in attrs if n == "_i0"][0]
    w_f = [(f, o) for n, f, o in attrs if n == "_w0"]
    for k in range(len(g.vertices) // stride):
        ix = struct.unpack_from(ix_f[0], g.vertices, k * stride + ix_f[1])
        ws = struct.unpack_from(w_f[0][0], g.vertices, k * stride + w_f[0][1]) if w_f else (1.0,)
        for j in range(max(1, shp.skin) if w_f else 1):
            if j == 0 or (j < len(ws) and ws[j] > 0):
                used.add(m2b[ix[j]] if ix[j] < len(m2b) else ix[j])
    s = sh.shap
    cap = _mw._u16(out, s + 0x64)
    arr = _mw._u64(out, s + 0x28)
    if not arr or len(used) > cap:
        return False
    bones = sorted(used)
    struct.pack_into("<%dH" % len(bones), out, arr, *bones)
    struct.pack_into("<H", out, s + 0x64, len(bones))
    return True


@dataclass
class ImportReport:
    shapes: list                # [ShapeReport] of the matched shapes
    unmatched: list             # names of meshes that match no shape
    kept_shapes: list           # names of shapes the file has no mesh for

    def text(self):
        lines = [r.text() for r in self.shapes]
        if self.unmatched:
            lines.append("meshes with no shape of that name (ignored): " + ", ".join(self.unmatched))
        if self.kept_shapes:
            lines.append("shapes not in the file (kept as they are): " + ", ".join(self.kept_shapes))
        return "\n".join(lines)

    @property
    def changed(self):
        return [r for r in self.shapes if not r.unchanged]


def import_glb(data, path, *, mapping=None):
    """(new .model bytes, ImportReport): the shapes a glTF / GLB's meshes match (by name, see
    match_shapes; `mapping` = {shape index or name: mesh node name} overrides) rebuilt from
    those meshes with their bone weights. The result equals `data` byte for byte when nothing
    changed. `path` may also be read_gltf's (json, buffers) or a list of GltfMesh."""
    m = _model.parse(data)
    L = _mw.layout(data)
    meshes = list(path) if isinstance(path, list) else read_meshes(path, m)
    if mapping:
        by = {me.name: me for me in meshes}
        plan = {}
        for k, v in mapping.items():
            if v not in by:
                raise MeshImportError(f"no mesh {v!r} in the file (has: {sorted(by)})")
            plan[_mw.resolve_shape(m, k)] = by[v]
        used = {id(x) for x in plan.values()}
        rest = [me for me in meshes if id(me) not in used]
    else:
        plan, rest = match_shapes(m, meshes)
    geo, reps = {}, []
    for si in sorted(plan):
        g, rep = shape_geometry_from_mesh(data, si, plan[si], m, L)
        reps.append(rep)
        if g is not None:
            geo[si] = g
    kept = [(sh.name or f"shape{sh.index}") for sh in m.shapes if sh.index not in plan]
    report = ImportReport(reps, [me.name for me in rest], kept)
    if not geo:
        return bytes(data), report
    out = bytearray(_mw.rebuild(data, geo))
    L2 = _mw.layout(bytes(out))
    smooth, rigid = _bone_matrices(data, m)
    for si, g in geo.items():
        attrs, stride = _mw._vertex_format(data, L.shapes[si])
        if not _update_skin_bones(out, L2.shapes[si], m.shapes[si], g, attrs, stride, m, smooth, rigid):
            next(r for r in reps if r.shape == si).notes.append(
                "the shape's used-bone list (SHAP+0x28, not read by the game) is longer than before; "
                "it was left as it was")
    return bytes(out), report
