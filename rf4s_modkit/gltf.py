"""
gltf.py -- a rigged RF4S model and its motions to and from glTF 2.0, for animating in Blender.

`export_glb(model, path, anim=None)` writes ONE binary .glb: the skeleton as a node tree (each
node named after its bone, its local T / R / S = the bone's bind values, the rotation as a
quaternion), every shape as a skinned mesh in the bind pose (positions, normals, UVs, JOINTS_0 /
WEIGHTS_0), the embedded textures as PNG materials, and optionally `.bfskl` motions (one, or a
list: each becomes its own glTF animation -- a Blender action -- named after the motion)
sampled at every game frame (60 per second).

`import_animation(path, model, template=None)` reads a glTF / GLB animation back (as Blender
exports it: node-local translation / rotation / scale channels) and builds a
`skelanim.SkelAnimFile`: each channel is sampled at every game frame, rotations are converted
to the game's Euler XYZ (R = Rz * Ry * Rx) and unwrapped, components that never change become
base values, the rest become cubic curves with as few keys as keep the motion within a small
tolerance. `skelanim.build()` then writes the .bfskl.

Conventions shared with model.py / skelanim.py:
  * units are the model's own; +Y is up in both (Blender's importer / exporter convert to and
    from its Z-up themselves);
  * rigid shapes (skin 0) follow their shape bone, skin-1 vertices the bone their `_i0`
    matrix maps to (matrix_to_bone), smooth vertices (skin 2+) up to four `_i0` / `_w0`
    influences through the same table; everything is exported in bind-pose model space, so
    each joint's inverse bind matrix is the inverse of its bind world matrix;
  * a bone the imported animation does not drive keeps its bind pose in the game (bone anims
    bind by name), so only animated bones are written.
"""
from __future__ import annotations

import io
import json
import math
import pathlib
import struct

from . import model as _model
from . import skelanim, texture

FPS = 60.0                       # the game advances one animation frame per tick (60 / s)
MAGIC = 0x46546C67               # "glTF"


class GltfError(Exception):
    pass


# --------------------------------------------------------------------------- #
# rotation helpers (R = Rz * Ry * Rx, model._local)
# --------------------------------------------------------------------------- #
def euler_to_quat(rx, ry, rz):
    """(x, y, z, w) of R = Rz * Ry * Rx."""
    cx, sx = math.cos(rx / 2), math.sin(rx / 2)
    cy, sy = math.cos(ry / 2), math.sin(ry / 2)
    cz, sz = math.cos(rz / 2), math.sin(rz / 2)
    # q = qz * qy * qx
    w = cz * cy * cx + sz * sy * sx
    x = cz * cy * sx - sz * sy * cx
    y = cz * sy * cx + sz * cy * sx
    z = sz * cy * cx - cz * sy * sx
    return (x, y, z, w)


def quat_to_matrix(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def quat_to_euler(q, prev=None):
    """Euler XYZ (R = Rz * Ry * Rx) of a quaternion; with `prev` the one of the two equivalent
    solutions nearest to it, each angle unwrapped by whole turns (smooth curves)."""
    r = quat_to_matrix(q)
    sy = max(-1.0, min(1.0, -r[2][0]))
    ry = math.asin(sy)
    if abs(math.cos(ry)) > 1e-6:
        rx = math.atan2(r[2][1], r[2][2])
        rz = math.atan2(r[1][0], r[0][0])
    else:                                     # gimbal lock: put it all in x
        rx = math.atan2(-r[1][2], r[1][1])
        rz = 0.0
    cands = [(rx, ry, rz), (rx + math.pi, math.pi - ry, rz + math.pi)]
    if prev is None:
        return cands[0]

    def near(a, p):
        return a + round((p - a) / (2 * math.pi)) * 2 * math.pi
    best = None
    for c in cands:
        u = tuple(near(a, p) for a, p in zip(c, prev))
        d = sum(abs(a - p) for a, p in zip(u, prev))
        if best is None or d < best[0]:
            best = (d, u)
    return best[1]


def _inverse(m):
    """Inverse of a 4x4 affine matrix (row-major, column vectors)."""
    a = [row[:3] for row in m[:3]]
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
           - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    if abs(det) < 1e-20:
        return _model._identity()
    inv = [[(a[(c + 1) % 3][(r + 1) % 3] * a[(c + 2) % 3][(r + 2) % 3]
             - a[(c + 1) % 3][(r + 2) % 3] * a[(c + 2) % 3][(r + 1) % 3]) / det for c in range(3)]
           for r in range(3)]
    t = [m[0][3], m[1][3], m[2][3]]
    it = [-sum(inv[r][k] * t[k] for k in range(3)) for r in range(3)]
    return [inv[0] + [it[0]], inv[1] + [it[1]], inv[2] + [it[2]], [0.0, 0.0, 0.0, 1.0]]


# --------------------------------------------------------------------------- #
# GLB writing
# --------------------------------------------------------------------------- #
class _Bin:
    def __init__(self):
        self.buf = bytearray()
        self.views = []
        self.accessors = []

    def view(self, data, target=None):
        while len(self.buf) % 4:
            self.buf += b"\0"
        v = {"buffer": 0, "byteOffset": len(self.buf), "byteLength": len(data)}
        if target:
            v["target"] = target
        self.buf += data
        self.views.append(v)
        return len(self.views) - 1

    def accessor(self, values, kind, comp=5126, target=None, minmax=False, normalized=False):
        """values = list of tuples (or scalars for SCALAR)."""
        n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[kind]
        flat = [x for v in values for x in (v if isinstance(v, (tuple, list)) else (v,))]
        fmt = {5126: "f", 5123: "H", 5121: "B", 5125: "I"}[comp]
        data = struct.pack("<%d%s" % (len(flat), fmt), *flat)
        acc = {"bufferView": self.view(data, target), "componentType": comp,
               "count": len(values), "type": kind}
        if normalized:
            acc["normalized"] = True
        if minmax and values:
            cols = [[v[i] if n > 1 else v for v in values] for i in range(n)]
            acc["min"] = [min(c) for c in cols]
            acc["max"] = [max(c) for c in cols]
        self.accessors.append(acc)
        return len(self.accessors) - 1


def _col_major(m):
    return [m[r][c] for c in range(4) for r in range(4)]


def _vertex_joints(model, sh, vb):
    """[(joints 4, weights 4)] per vertex (joint index = bone index)."""
    n = len(vb.data.get("_p0", []))
    m2b = model.matrix_to_bone
    ix = vb.data.get("_i0")
    wts = vb.data.get("_w0")
    out = []
    for k in range(n):
        if sh.skin == 0 or not ix:
            j, w = [max(0, sh.bone), 0, 0, 0], [1.0, 0.0, 0.0, 0.0]
        elif sh.skin == 1 or not wts:
            b = m2b[ix[k][0]] if ix[k][0] < len(m2b) else ix[k][0]
            j, w = [max(0, b), 0, 0, 0], [1.0, 0.0, 0.0, 0.0]
        else:
            pairs = []
            for q in range(min(sh.skin, len(ix[k]), len(wts[k]), 4)):
                if wts[k][q] > 0:
                    b = m2b[ix[k][q]] if ix[k][q] < len(m2b) else ix[k][q]
                    pairs.append((max(0, b), wts[k][q]))
            tot = sum(p[1] for p in pairs) or 1.0
            pairs = (pairs + [(0, 0.0)] * 4)[:4]
            j = [p[0] for p in pairs]
            w = [p[1] / tot for p in pairs]
        out.append((j, w))
    return out


def export_glb(model, path=None, anim=None, name="model"):
    """Write (or return, when `path` is None) a .glb of `model` in its bind pose with its
    skeleton, skin and textures, plus `anim` (a skelanim.SkelAnimFile, or a list of them) as
    animations."""
    saved = model.pose
    model.pose = None
    try:
        return _export(model, path, anim, name)
    finally:
        model.pose = saved


def _export(model, path, anim, name):
    b = _Bin()
    bones = model.bones
    nodes, meshes, materials, textures, images, samplers = [], [], [], [], [], []
    for bn in bones:
        nd = {"name": bn.name,
              "translation": [float(v) for v in bn.translation],
              "rotation": list(euler_to_quat(*bn.rotation[:3]) if bn.euler else bn.rotation[:4]),
              "scale": [float(v) for v in bn.scale]}
        nodes.append(nd)
    for i, bn in enumerate(bones):
        if 0 <= bn.parent < len(bones) and bn.parent != i:
            nodes[bn.parent].setdefault("children", []).append(i)
    roots = [i for i, bn in enumerate(bones) if not (0 <= bn.parent < len(bones)) or bn.parent == i]
    world = _model.world_matrices(bones)
    skin_idx = None
    if bones:
        ibm = b.accessor([tuple(_col_major(_inverse(w))) for w in world], "MAT4")
        skin_idx = 0
    # materials / textures
    tex_of = {}
    for t in model.textures:
        try:
            im = texture.decode_bntx(model.data, t["index"])
        except Exception:  # noqa: BLE001 - an unreadable texture: untextured material
            im = None
        if im is None:
            continue
        bio = io.BytesIO()
        im.convert("RGBA").save(bio, "PNG")
        images.append({"name": t["name"], "mimeType": "image/png", "bufferView": b.view(bio.getvalue())})
        textures.append({"source": len(images) - 1, "sampler": 0})
        tex_of[t["name"]] = len(textures) - 1
    if textures:
        samplers.append({"wrapS": 10497, "wrapT": 10497, "magFilter": 9729, "minFilter": 9729})
    for mt in model.materials:
        m = {"name": mt.name or f"mat{mt.index}", "doubleSided": True,
             "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0}}
        if mt.textures and mt.textures[0] in tex_of:
            m["pbrMetallicRoughness"]["baseColorTexture"] = {"index": tex_of[mt.textures[0]]}
        m["alphaMode"] = "MASK" if mt.shading != "body" else "OPAQUE"
        if m["alphaMode"] == "MASK":
            m["alphaCutoff"] = 0.5
        materials.append(m)
    # meshes (one node each, skinned)
    mesh_nodes = []
    for sh in model.shapes:
        vb = model.vertex_buffers[sh.vertex_buffer]
        pos = model.shape_vertices(sh)
        if not pos or not sh.indices:
            continue
        attrs = {"POSITION": b.accessor([tuple(p[:3]) for p in pos], "VEC3", target=34962, minmax=True)}
        nrm = _model._model_space_normals(model, sh, vb.data.get("_n0"))
        if nrm and len(nrm) == len(pos):
            attrs["NORMAL"] = b.accessor([tuple(n[:3]) for n in nrm], "VEC3", target=34962)
        uv = vb.data.get("_u0")
        if uv and len(uv) == len(pos):
            attrs["TEXCOORD_0"] = b.accessor([(t[0], t[1]) for t in uv], "VEC2", target=34962)
        if skin_idx is not None:
            jw = _vertex_joints(model, sh, vb)
            attrs["JOINTS_0"] = b.accessor([tuple(j) for j, _w in jw], "VEC4", comp=5123, target=34962)
            attrs["WEIGHTS_0"] = b.accessor([tuple(w) for _j, w in jw], "VEC4", target=34962)
        prim = {"attributes": attrs,
                "indices": b.accessor(list(sh.indices), "SCALAR", comp=5125, target=34963),
                "mode": 4}
        if 0 <= sh.material < len(materials):
            prim["material"] = sh.material
        meshes.append({"name": sh.name or f"shape{sh.index}", "primitives": [prim]})
        nd = {"name": sh.name or f"shape{sh.index}", "mesh": len(meshes) - 1}
        if skin_idx is not None:
            nd["skin"] = skin_idx
        nodes.append(nd)
        mesh_nodes.append(len(nodes) - 1)
    gl = {"asset": {"version": "2.0", "generator": "rf4s_modkit.gltf"},
          "scene": 0, "scenes": [{"name": name, "nodes": roots + mesh_nodes}],
          "nodes": nodes, "meshes": meshes}
    if skin_idx is not None:
        gl["skins"] = [{"name": "skeleton", "joints": list(range(len(bones))),
                        "inverseBindMatrices": ibm, "skeleton": roots[0] if roots else 0}]
    if materials:
        gl["materials"] = materials
    if textures:
        gl["textures"], gl["images"], gl["samplers"] = textures, images, samplers
    anims = [] if anim is None else [anim] if isinstance(anim, skelanim.SkelAnimFile) else list(anim)
    if anims:
        gl["animations"] = [_animation_json(b, model, a) for a in anims]
    gl["bufferViews"], gl["accessors"] = b.views, b.accessors
    while len(b.buf) % 4:
        b.buf += b"\0"
    gl["buffers"] = [{"byteLength": len(b.buf)}]
    blob = _glb(gl, bytes(b.buf))
    if path is not None:
        pathlib.Path(path).write_bytes(blob)
    return blob


def _animation_json(b, model, anim):
    """A glTF animation of `anim`: every bone it drives, sampled at every game frame."""
    n = int(anim.frame_count)
    frames = list(range(n + 1)) if n > 0 else [0]
    times = b.accessor([f / FPS for f in frames], "SCALAR", minmax=True)
    channels, samplers = [], []
    for i, bn in enumerate(model.bones):
        ba = anim.bone(bn.name)
        if ba is None:
            continue
        ts, rs, ss = [], [], []
        for f in frames:
            s, r, t = ba.srt(anim.wrap(f) if f < n or not anim.loops else float(n), bn)
            ts.append(tuple(t))
            rs.append(euler_to_quat(*r[:3]) if anim.euler else tuple(r[:4]))
            ss.append(tuple(s))
        for path_, vals, kind in (("translation", ts, "VEC3"), ("rotation", rs, "VEC4"), ("scale", ss, "VEC3")):
            out = b.accessor(vals, kind)
            samplers.append({"input": times, "output": out, "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": i, "path": path_}})
    return {"name": anim.name, "channels": channels, "samplers": samplers,
            "extras": {"rf4s_frames": n, "rf4s_loop": bool(anim.loops)}}


def _glb(gl, binary):
    js = json.dumps(gl, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (struct.pack("<III", MAGIC, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(binary), 0x004E4942) + binary)


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #
def read_gltf(path):
    """(json dict, [buffer bytes]) of a .glb or a .gltf (+ its .bin / data URIs)."""
    p = pathlib.Path(path)
    raw = p.read_bytes()
    bins = []
    if raw[:4] == b"glTF":
        _magic, _ver, total = struct.unpack_from("<III", raw, 0)
        o, gl = 12, None
        while o + 8 <= min(total, len(raw)):
            ln, kind = struct.unpack_from("<II", raw, o)
            chunk = raw[o + 8:o + 8 + ln]
            if kind == 0x4E4F534A:
                gl = json.loads(chunk.decode("utf-8"))
            elif kind == 0x004E4942:
                bins.append(chunk)
            o += 8 + ln
        if gl is None:
            raise GltfError("no JSON chunk in the .glb")
    else:
        gl = json.loads(raw.decode("utf-8"))
    buffers = []
    for i, bf in enumerate(gl.get("buffers", [])):
        uri = bf.get("uri")
        if uri is None:
            buffers.append(bins[i] if i < len(bins) else (bins[0] if bins else b""))
        elif uri.startswith("data:"):
            import base64
            buffers.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            from urllib.parse import unquote
            buffers.append((p.parent / unquote(uri)).read_bytes())
    return gl, buffers


_COMP = {5120: ("b", 1, 127.0), 5121: ("B", 1, 255.0), 5122: ("h", 2, 32767.0),
         5123: ("H", 2, 65535.0), 5125: ("I", 4, None), 5126: ("f", 4, None)}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_accessor(gl, buffers, idx):
    """[tuple] (or [float] for SCALAR) of accessor `idx` (normalized ints -> floats)."""
    acc = gl["accessors"][idx]
    fmt, size, norm = _COMP[acc["componentType"]]
    n = _NCOMP[acc["type"]]
    count = acc["count"]
    if "bufferView" not in acc:
        vals = [0.0] * (count * n)
    else:
        bv = gl["bufferViews"][acc["bufferView"]]
        data = buffers[bv.get("buffer", 0)]
        base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = bv.get("byteStride") or size * n
        vals = []
        for k in range(count):
            vals += struct.unpack_from("<%d%s" % (n, fmt), data, base + k * stride)
    if acc.get("normalized") and norm:
        vals = [max(v / norm, -1.0) for v in vals]
    if n == 1:
        return [float(v) for v in vals]
    return [tuple(float(x) for x in vals[k * n:(k + 1) * n]) for k in range(count)]


def list_animations(path):
    """[(index, name, duration in seconds, channel count)] of a glTF / GLB file."""
    gl, bufs = read_gltf(path)
    out = []
    for i, a in enumerate(gl.get("animations", [])):
        dur = 0.0
        for s in a.get("samplers", []):
            acc = gl["accessors"][s["input"]]
            if "max" in acc:
                dur = max(dur, float(acc["max"][0]))
            else:
                t = read_accessor(gl, bufs, s["input"])
                dur = max(dur, max(t) if t else 0.0)
        out.append((i, a.get("name") or f"animation {i}", dur, len(a.get("channels", []))))
    return out


def _sample(times, values, interp, t):
    """The channel value at time t (LINEAR lerp / slerp for quaternions, STEP, CUBICSPLINE)."""
    n = len(times)
    cubic = interp == "CUBICSPLINE"

    def val(i):
        return values[3 * i + 1] if cubic else values[i]
    if n == 0:
        return None
    if t <= times[0] or n == 1:
        return val(0)
    if t >= times[-1]:
        return val(n - 1)
    lo, hi = 0, n - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if times[mid] <= t:
            lo = mid
        else:
            hi = mid
    t0, t1 = times[lo], times[hi]
    u = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
    a, bv = val(lo), val(hi)
    if interp == "STEP":
        return a
    if cubic:
        dt = t1 - t0
        m0 = values[3 * lo + 2]
        m1 = values[3 * hi]
        h00, h10 = 2 * u ** 3 - 3 * u ** 2 + 1, u ** 3 - 2 * u ** 2 + u
        h01, h11 = -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2
        return tuple(h00 * a[k] + h10 * dt * m0[k] + h01 * bv[k] + h11 * dt * m1[k] for k in range(len(a)))
    if len(a) == 4:                             # quaternion: slerp
        return _slerp(a, bv, u)
    return tuple(a[k] + (bv[k] - a[k]) * u for k in range(len(a)))


def _slerp(a, b, u):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0:
        b, d = tuple(-x for x in b), -d
    if d > 0.9995:
        q = tuple(x + (y - x) * u for x, y in zip(a, b))
    else:
        th = math.acos(min(1.0, d))
        s = math.sin(th)
        wa, wb = math.sin((1 - u) * th) / s, math.sin(u * th) / s
        q = tuple(wa * x + wb * y for x, y in zip(a, b))
    n = math.sqrt(sum(x * x for x in q)) or 1.0
    return tuple(x / n for x in q)


# tolerances for dropping keys: rotation (radians), scale (factor), translation (a fraction of
# the model's size -- the same visual precision on a big boss and a small prop). A round trip
# with no tolerance is exact; these keep a motion within ~0.05 % of the model's size.
TOL = {"r": 0.0002, "s": 0.0002, "t_rel": 0.0002}


def _extent(model):
    """The model's size: the diagonal of its bind-pose bounding box (1.0 when empty)."""
    pts = [p for sh in model.shapes for p in model.shape_vertices(sh)]
    if not pts:
        return 1.0
    lo = [min(p[k] for p in pts) for k in range(3)]
    hi = [max(p[k] for p in pts) for k in range(3)]
    return math.sqrt(sum((h - l) ** 2 for h, l in zip(hi, lo))) or 1.0


def _fit_curve(vals, tol):
    """Cubic keys ([(frame, (c0, c1, c2, c3))]) reproducing per-frame `vals` within `tol`:
    Hermite segments with the samples' own slopes, greedily as long as they stay close."""
    n = len(vals)
    if n == 1:
        return [(0, (vals[0], 0.0, 0.0, 0.0))]
    d = [0.0] * n
    for i in range(n):
        if 0 < i < n - 1:
            d[i] = (vals[i + 1] - vals[i - 1]) / 2.0
        elif i == 0:
            d[i] = vals[1] - vals[0]
        else:
            d[i] = vals[-1] - vals[-2]

    def seg(a, b):
        L = b - a
        p0, p1, m0, m1 = vals[a], vals[b], d[a] * L, d[b] * L
        return (p0, m0, 3 * (p1 - p0) - 2 * m0 - m1, 2 * (p0 - p1) + m0 + m1)

    def ok(a, b):
        c = seg(a, b)
        L = b - a
        for k in range(a + 1, b):
            t = (k - a) / L
            if abs(c[0] + t * (c[1] + t * (c[2] + t * c[3])) - vals[k]) > tol:
                return False
        return True
    keys, a = [], 0
    while a < n - 1:
        b = a + 1
        while b + 1 < n and ok(a, b + 1):
            b += 1
        keys.append((a, seg(a, b)))
        a = b
    keys.append((n - 1, (vals[-1], 0.0, 0.0, 0.0)))
    return keys


def import_animation(path, model, template=None, animation=0, name=None, loop=None):
    """A skelanim.SkelAnimFile built from animation `animation` (index or name) of a glTF /
    GLB file, for `model`'s skeleton. `template` (the .bfskl it replaces) supplies the name,
    file name and loop flag unless `name` / `loop` are given."""
    from .matanim import Curve
    gl, bufs = read_gltf(path)
    anims = gl.get("animations", [])
    if not anims:
        raise GltfError("the file has no animation")
    if isinstance(animation, str):
        hit = [a for a in anims if a.get("name") == animation]
        if not hit:
            raise GltfError(f"no animation named {animation!r}")
        an = hit[0]
    else:
        an = anims[animation]
    nodes = gl.get("nodes", [])
    by_bone = {bn.name: bn for bn in model.bones}
    chans = {}                                  # bone name -> {path: (times, values, interp)}
    dur = 0.0
    for ch in an.get("channels", []):
        tgt = ch.get("target", {})
        ni = tgt.get("node")
        if ni is None or ni >= len(nodes) or tgt.get("path") not in ("translation", "rotation", "scale"):
            continue
        bname = nodes[ni].get("name")
        if bname not in by_bone:
            continue
        smp = an["samplers"][ch["sampler"]]
        times = read_accessor(gl, bufs, smp["input"])
        values = read_accessor(gl, bufs, smp["output"])
        chans.setdefault(bname, {})[tgt["path"]] = (times, values, smp.get("interpolation", "LINEAR"))
        if times:
            dur = max(dur, times[-1])
    if not chans:
        raise GltfError("the animation drives none of this model's bones (the glTF node names must "
                        "match the bone names, as Export for Blender writes them)")
    extras = an.get("extras") or {}
    n = int(round(dur * FPS))
    # Blender exports whole frames of ITS frame rate (24 by default), so a 72-frame motion
    # comes back as 70 (1.1667 s): within ~3 game frames of the replaced motion, keep its
    # length (the extras tag survives our own files, not Blender's)
    want = extras.get("rf4s_frames") if isinstance(extras.get("rf4s_frames"), int) else (
        int(template.frame_count) if template is not None else None)
    if want is not None and abs(want - n) <= 3:
        n = want
    n = max(1, n)
    loops = loop if loop is not None else (template.loops if template is not None
                                           else bool(extras.get("rf4s_loop", True)))
    end_t = n / FPS
    flags = (skelanim.ROT_EULER_XYZ << 12) | 0x100 | (skelanim.FLAG_LOOP if loops else 0)
    out = skelanim.SkelAnimFile(name or (template.name if template else pathlib.Path(path).stem),
                                "", flags, n, 0, 0)
    out.file_name = template.file_name if template is not None else out.name
    saved, model.pose = model.pose, None
    try:
        tol = {"r": TOL["r"], "s": TOL["s"], "t": max(1e-5, TOL["t_rel"] * _extent(model))}
    finally:
        model.pose = saved
    first = 0
    for bn in model.bones:
        cs = chans.get(bn.name)
        if not cs:
            continue
        rest_r = euler_to_quat(*bn.rotation[:3]) if bn.euler else tuple(bn.rotation[:4])
        series = {k: [] for k in ("s0", "s1", "s2", "r0", "r1", "r2", "t0", "t1", "t2")}
        prev = None
        def at(path_, t, rest):
            if path_ not in cs:
                return rest
            times, values, interp = cs[path_]
            last = times[-1] if times else 0.0
            if loops and times and t > last + 1e-6 and end_t > last:
                # a looping motion whose file stops short of the loop end: blend the last
                # key back to the first over the missing tail, so the wrap stays smooth
                u = (t - last) / (end_t - last)
                a0, a1 = _sample(times, values, interp, last), _sample(times, values, interp, times[0])
                if len(a0) == 4:
                    return _slerp(a0, a1, u)
                return tuple(x + (y - x) * u for x, y in zip(a0, a1))
            return _sample(times, values, interp, t)
        for f in range(n + 1):
            t = f / FPS
            tr = at("translation", t, tuple(bn.translation))
            q = at("rotation", t, rest_r)
            sc = at("scale", t, tuple(bn.scale))
            e = quat_to_euler(q, prev)
            prev = e
            for k in range(3):
                series[f"s{k}"].append(float(sc[k]))
                series[f"r{k}"].append(float(e[k]))
                series[f"t{k}"].append(float(tr[k]))
        bflags = skelanim.BASE_ROTATE | skelanim.BASE_TRANSLATE
        base_s = tuple(v[0] for v in (series["s0"], series["s1"], series["s2"]))
        if any(abs(x - 1.0) > 1e-6 for x in base_s) or any(
                max(series[f"s{k}"]) - min(series[f"s{k}"]) > tol["s"] for k in range(3)):
            bflags |= skelanim.BASE_SCALE
        curves = []
        for comp, bits, offs in (("s", 0x40, 0x04), ("r", 0x200, 0x20), ("t", 0x2000, 0x10)):
            if comp == "s" and not bflags & skelanim.BASE_SCALE:
                continue
            for k in range(3):
                vals = series[f"{comp}{k}"]
                if max(vals) - min(vals) <= tol[comp]:
                    continue
                keys = _fit_curve(vals, tol[comp])
                curves.append(Curve(0, offs + 4 * k, 0.0, float(n), 1.0, 0.0, 0.0,
                                    [float(f) for f, _c in keys], [tuple(c) for _f, c in keys]))
                bflags |= bits << k
        # the game's order: scale, rotate, translate curves (by target)
        curves.sort(key=lambda c: (0 if c.target < 0x10 else (1 if c.target >= 0x20 else 2), c.target))
        ba = skelanim.BoneAnim(len(out.bones), bn.name, bflags,
                               base_s if bflags & skelanim.BASE_SCALE else None,
                               (series["r0"][0], series["r1"][0], series["r2"][0], 1.0),
                               (series["t0"][0], series["t1"][0], series["t2"][0]),
                               curves, 0, 0, first)
        first += len(curves)
        out.bones.append(ba)
    # bones of the replaced file this model does not have (a motion file can be shared by
    # several models, e.g. M24_3 plays M24_0's): keep their motion as it was
    if template is not None:
        have = {bb.name for bb in out.bones}
        for tb in template.bones:
            if tb.name in have or tb.name in by_bone:
                continue
            out.bones.append(skelanim.BoneAnim(len(out.bones), tb.name, tb.flags, tb.base_scale,
                                               tb.base_rotate, tb.base_translate, list(tb.curves),
                                               0, 0, first))
            first += len(tb.curves)
    out.curve_count = first
    return out
