r"""
shaderarchive.py -- RF4S shaders: which source the PC build compiles, and tools for both kinds.

RF4S ships two sets of shader source. Only one of them ever reaches the GPU on PC.

1. **Loose Muteki GLSL files (these are the ones the game compiles).** `bundleMuteki` holds
   `<name>_v.glsl` / `<name>_f.glsl` / `<name>_discard_f.glsl` programs plus `*.glsl.inc`
   include files. The exe calls glShaderSource / glCompileShader / glCreateProgram in exactly
   one place, MCShader_ctor_base (RF4S.exe+0x28B360). It compiles a vertex shader and a
   fragment shader, each first passed through MCShader_PreprocessSource (RF4S.exe+0x27CCE0).
   The source comes from the loader at RF4S.exe+0x27EB10, which formats "%s_v.glsl",
   "%s_f.glsl" or (with the discard flag) "%s_discard_f.glsl", resolves the name through
   MageEngine_ResolveResourcePath and opens it with MFFile_Open. That is the same by-name
   `Bundle\**` file index every other asset uses, so a loose file in `Bundle\00_mods\` wins
   (see `rf4mod install`). Callers by program name:
     * mtk_body / mtk_item / mtk_billboard: every g3d model draw. RF4S.exe+0x3C4720 picks one
       from the vertex-attribute mask the vertex-state setup (RF4S.exe+0x3CA2E0) derived from
       the `_p0/_u0.._u3/_i0/_w0` attribute names. A mask with blend indices (_i0) or bit 3
       gives mtk_body (loaded with mask 0x319). Exactly {_p0, _u0} (0x11) gives mtk_item.
       Anything else gives mtk_billboard (0x17). The vertex-buffer bind path (RF4S.exe+0x3C2E30)
       binds that program whenever no other program is current.
     * mtk_text: text/UI passes (MageApplication_RenderScreen and RF4S.exe+0x1B1030).
     * mtk_color: VideoColorImageView (RF4S.exe+0x3C2950). yuv420 / yuv444: movie frames
       (Cutscene_RenderVideoFrameWithOverlay).
     * mtk_%04x (mtk_0001 / 0011 / 0015 / 0017): Renderer_GetOrCreateShaderProgram
       (RF4S.exe+0x27C870) for immediate-mode draws, keyed by vertex mask (+ "_discard").
       If mask 1 or 0x11 fails to load, the exe falls back to built-in flat/textured shaders.
   MCShader_PreprocessSource skips // and /* */ comments. It replaces each `#include <x>` line
   with the recursively preprocessed file x (MFFileManager_BuildPath + MFFile_Open, logging
   "could not find include" on a miss). A `#version` above 330 is rewritten to
   `330` + `#extension GL_ARB_gpu_shader_fp64 : enable`. It also inserts one `#define K V`
   line after `#version` for every entry of a global dictionary (RF4S.exe .data, built empty
   by a static ctor). No code in the exe adds to that dictionary, so in practice nothing is
   prepended. Mask variants are separate files, not macros. `preprocess()` below repeats
   this pass.
   **No shader cache**: glew32 imports only Create/Shader/Compile/Attach/Link/Use and the
   info-log calls. There is no glProgramBinary / glGetProgramBinary and no cache file, so
   everything is compiled again from source on each launch. Edited files take effect on
   the next start.
   The `*.hlsl` / `*.hlsl.inc` twins are dead data. The exe has no D3D shader path, and no
   string in it names an .hlsl file. (yuv444 exists only as .hlsl, so its GL load logs
   "Unable to load vertex shader source" and fails.)

2. **nn::g3d shader archives `bundleMain\*.bfsha` (FSHA): loaded, but their GLSL is never
   compiled.** nsObj3d_Init (RF4S.exe+0x1B2FA0) opens `rom:/%s.bfsha` and sets up every
   shading-model program through RF4S.exe+0x3CE060. That routine tries the code types
   (binary / intermediate / source) through the port's nn::gfx Shader shim initialiser
   RF4S.exe+0x3D52A0, which is `mov byte [rcx],1; xor eax,eax; ret`: a stub that reports
   success without looking at the code. Uniform and sampler lookups (RF4S.exe+0x3D5100)
   resolve against the bound Muteki MCShader (names such as `i_Position`, `i_Color`,
   `Tex*`, `Mat*`). The archive therefore still matters for its *metadata*: shading-model
   names that .model materials reference, options and choices, sampler, uniform-block and
   attribute names. **Editing its GLSL text changes nothing in the PC game**, so this module
   reads and extracts it (for reference, and for porting effects into the loose files) but
   deliberately has no archive writer.

FSHA layout (version 7.0.3; all pointers are file-absolute u64s listed in the trailing
`_RLT` relocation table; strings live in `_STR` as u16 length + bytes + NUL):

    +0x00 'FSHA    '  +0x08 u32 version  +0x0C BOM  +0x10 u32 name(+2)  +0x16 u16 first block
    +0x18 u32 _RLT offset  +0x1C u32 file size
    +0x20 -> archive (0x38):  +0x00 name  +0x08 path  +0x10 -> shading models (0xE8 each)
          +0x18 -> model dict  +0x40 u16 model count
    shading model (0xE8): +0x00 name  +0x08/+0x10 static options + dict
          +0x18/+0x20 dynamic options + dict  +0x28/+0x30 attribs  +0x38/+0x40 samplers
          +0x48/+0x50 uniform blocks  +0x78 -> programs  +0x88 -> archive
          +0x98 -> embedded BNSH  +0xD4 u16 static-option count  +0xD6 u16 dynamic count
          +0xD8 u16 program count
    option (0x28): +0x00 name  +0x08 -> choice dict (_DIC)  +0x18 u8 choice count
          +0x19 u8 default choice
    program: +0x18 -> BNSH variation (file-absolute)
    BNSH (embedded nn::gfx ResShaderFile): 0x20-byte header ('BNSH', +0x16 u16 first block,
          +0x18 u32 own _RLT, +0x1C u32 size); its pointers are relative to the BNSH start.
          grsc +0x1C u32 variation count  +0x20 -> variations (0x40 each: source program,
          intermediate program, binary program, parent)
          program: +0x00 u8 flags, u8 code type (3 = SourceArray, 0 = binary)
                   +0x08.. -> per-stage code [vertex, hull, domain, geometry, pixel, compute]
          SourceArray code: u32 piece count, -> u32 sizes[], -> char* pieces[]
                   (every shipped stage is 3 pieces: "#version 430\n", the baked option
                   #defines, the body; each NUL-terminated, 8-byte aligned, not shared
                   between stages or models)
          binary program: code type 0, format 0x8E21, zlib-compressed Switch GPU binaries.
"""
from __future__ import annotations

import json
import pathlib
import re
import struct
import zlib
from dataclasses import dataclass, field

STAGES = ("vertex", "hull", "domain", "geometry", "pixel", "compute")
STAGE_EXT = {"vertex": "vert", "hull": "tesc", "domain": "tese", "geometry": "geom",
             "pixel": "frag", "compute": "comp"}


class ShaderArchiveError(ValueError):
    pass


def _u16(d, o): return struct.unpack_from("<H", d, o)[0]
def _u32(d, o): return struct.unpack_from("<I", d, o)[0]
def _u64(d, o): return struct.unpack_from("<Q", d, o)[0]


def _str(d, o):
    if not o:
        return ""
    n = _u16(d, o)
    return d[o + 2:o + 2 + n].decode("utf-8", "replace")


def relocation_pointers(d: bytes, base: int = 0) -> list:
    """Every pointer slot listed in an NX binary file's _RLT (offsets relative to `base`)."""
    off = base + _u32(d, base + 0x18)
    if d[off:off + 4] != b"_RLT":
        raise ShaderArchiveError(f"no _RLT at 0x{off:X}")
    nsec = _u32(d, off + 8)
    p = off + 0x10
    nent = 0
    for _ in range(nsec):
        nent += _u32(d, p + 0x14)
        p += 0x18
    out = []
    for _ in range(nent):
        eoff, arr, rel, pad = struct.unpack_from("<IHBB", d, p)
        p += 8
        for a in range(arr):
            for r in range(rel):
                out.append(eoff + (a * (rel + pad) + r) * 8)
    return out


def _dict_keys(d, o):
    """Names in a ResDic: u32 magic (0 in these files, '_DIC' in others), u32 count, then
    (count+1) 16-byte nodes {u32 ref bit, u16 left, u16 right, -> key}; node 0 is the root."""
    if not o or d[o:o + 4] not in (b"_DIC", bytes(4)):
        return []
    n = _u32(d, o + 4)
    return [_str(d, _u64(d, o + 8 + 16 * i + 8)) for i in range(1, n + 1)]


@dataclass
class SourcePiece:
    offset: int          # absolute file offset of the text
    size: int            # length field (bytes, no NUL)
    size_field: int      # absolute offset of the u32 length
    ptr_field: int       # absolute offset of the u64 pointer (BNSH-relative value)
    text: bytes


@dataclass
class Stage:
    stage: str
    pieces: list

    @property
    def source(self) -> bytes:
        """The full stage source as glShaderSource(count=len(pieces)) would join it."""
        return b"".join(p.text for p in self.pieces)

    @property
    def prologue(self) -> bytes:
        """Everything before the body: the #version line + the baked option #defines."""
        return b"".join(p.text for p in self.pieces[:-1])

    @property
    def body(self) -> bytes:
        return self.pieces[-1].text if self.pieces else b""


@dataclass
class Variation:
    index: int
    offset: int
    source_stages: list = field(default_factory=list)
    binary_stages: list = field(default_factory=list)   # (stage, compressed size, raw size)


@dataclass
class Option:
    name: str
    choices: list
    default: int
    dynamic: bool


@dataclass
class ShadingModel:
    index: int
    name: str
    offset: int
    static_options: list
    dynamic_options: list
    program_count: int
    samplers: list
    uniform_blocks: list
    attribs: list
    bnsh_offset: int
    bnsh_size: int
    variations: list

    def stage(self, stage="vertex", variation=0) -> Stage:
        for s in self.variations[variation].source_stages:
            if s.stage == stage:
                return s
        raise KeyError(f"{self.name}: no {stage} source in variation {variation}")


class ShaderArchive:
    """Read-only parse of an RF4S .bfsha (FSHA with embedded BNSH GLSL source arrays)."""

    def __init__(self, data: bytes, name: str = ""):
        d = bytes(data)
        if d[:8] != b"FSHA    ":
            raise ShaderArchiveError("not an FSHA shader archive")
        self.data = d
        self.version = _u32(d, 8)
        self.file_size = _u32(d, 0x1C)
        if self.file_size != len(d):
            raise ShaderArchiveError(f"header size 0x{self.file_size:X} != file 0x{len(d):X}")
        arch = _u64(d, 0x20)
        self.name = _str(d, _u64(d, arch)) or name
        self.pointers = relocation_pointers(d)
        models_at = _u64(d, arch + 0x10)
        count = _u16(d, arch + 0x40)
        self.models = [self._model(i, models_at + i * 0xE8) for i in range(count)]

    # -- parsing ---------------------------------------------------------------------------
    def _options(self, arr, n, dynamic):
        d = self.data
        out = []
        for i in range(n):
            o = arr + i * 0x28
            out.append(Option(_str(d, _u64(d, o)), _dict_keys(d, _u64(d, o + 8)),
                              d[o + 0x19], dynamic))
        return out

    def _model(self, index, m) -> ShadingModel:
        d = self.data
        n_static, n_dyn, n_prog = _u16(d, m + 0xD4), _u16(d, m + 0xD6), _u16(d, m + 0xD8)
        bnsh = _u64(d, m + 0x98)
        variations, bsize = [], 0
        if bnsh:
            if d[bnsh:bnsh + 4] != b"BNSH":
                raise ShaderArchiveError(f"model {index}: no BNSH at 0x{bnsh:X}")
            bsize = _u32(d, bnsh + 0x1C)
            variations = self._variations(bnsh)
        return ShadingModel(
            index, _str(d, _u64(d, m)), m,
            self._options(_u64(d, m + 0x08), n_static, False),
            self._options(_u64(d, m + 0x18), n_dyn, True),
            n_prog, _dict_keys(d, _u64(d, m + 0x40)), _dict_keys(d, _u64(d, m + 0x50)),
            _dict_keys(d, _u64(d, m + 0x30)), bnsh, bsize, variations)

    def _variations(self, B):
        d = self.data
        g = B + _u16(d, B + 0x16)
        if d[g:g + 4] != b"grsc":
            raise ShaderArchiveError(f"BNSH at 0x{B:X}: no grsc block")
        out = []
        va = B + _u64(d, g + 0x20)
        for v in range(_u32(d, g + 0x1C)):
            V = va + v * 0x40
            var = Variation(v, V)
            src, _il, binp = _u64(d, V), _u64(d, V + 8), _u64(d, V + 0x10)
            if src:
                P = B + src
                for si, st in enumerate(STAGES):
                    c = _u64(d, P + 8 + 8 * si)
                    if not c:
                        continue
                    C = B + c
                    if d[P + 1] != 3:
                        raise ShaderArchiveError(f"variation 0x{V:X}: code type {d[P + 1]} "
                                                 "is not SourceArray")
                    cnt, sizes, ptrs = _u32(d, C), B + _u64(d, C + 8), B + _u64(d, C + 0x10)
                    pieces = []
                    for k in range(cnt):
                        at, n = B + _u64(d, ptrs + 8 * k), _u32(d, sizes + 4 * k)
                        pieces.append(SourcePiece(at, n, sizes + 4 * k, ptrs + 8 * k,
                                                  d[at:at + n]))
                    var.source_stages.append(Stage(st, pieces))
            if binp:
                P = B + binp
                for si, st in enumerate(STAGES):
                    c = _u64(d, P + 8 + 8 * si)
                    if c:
                        C = B + c
                        var.binary_stages.append((st, _u32(d, C), _u32(d, C + 4)))
            out.append(var)
        return out

    # -- queries ---------------------------------------------------------------------------
    def model(self, name) -> ShadingModel:
        for m in self.models:
            if m.name == name or str(m.index) == str(name):
                return m
        raise KeyError(f"{self.name}: no shading model {name!r} "
                       f"(have {', '.join(m.name for m in self.models)})")

    def sections(self):
        """Yield (model, variation, stage) for every GLSL source section."""
        for m in self.models:
            for v in m.variations:
                for s in v.source_stages:
                    yield m, v, s

    def summary(self) -> dict:
        return {
            "archive": self.name, "version": "%d.%d.%d" % (self.version >> 16,
                                                           (self.version >> 8) & 0xFF,
                                                           self.version & 0xFF),
            "size": len(self.data), "relocated_pointers": len(self.pointers),
            "models": [{
                "name": m.name, "programs": m.program_count,
                "static_options": {o.name: o.choices for o in m.static_options},
                "dynamic_options": {o.name: o.choices for o in m.dynamic_options},
                "samplers": m.samplers, "uniform_blocks": m.uniform_blocks,
                "attribs": m.attribs, "bnsh": f"0x{m.bnsh_offset:X}+0x{m.bnsh_size:X}",
                "variations": [{
                    "sources": {s.stage: [{"offset": f"0x{p.offset:X}", "size": p.size}
                                          for p in s.pieces] for s in v.source_stages},
                    "switch_binaries": {st: {"zlib": c, "raw": r}
                                        for st, c, r in v.binary_stages},
                } for v in m.variations],
            } for m in self.models],
        }

    def switch_binary(self, model, stage="vertex", variation=0) -> bytes:
        """Decompressed Switch GPU binary of one stage (not used by the PC build)."""
        m = self.model(model)
        B = m.bnsh_offset
        d = self.data
        V = m.variations[variation].offset
        P = B + _u64(d, V + 0x10)
        C = B + _u64(d, P + 8 + 8 * STAGES.index(stage))
        csize, at = _u32(d, C), B + _u64(d, C + 8)
        return zlib.decompress(d[at:at + csize])

    def extract(self, out_dir, with_prologue=True) -> list:
        """Write every source section to out_dir/<archive>/<model>[_vN].<stage-ext>.glsl
        (+ index.json with offsets). Returns the written paths."""
        root = pathlib.Path(out_dir) / self.name
        root.mkdir(parents=True, exist_ok=True)
        written = []
        for m, v, s in self.sections():
            tag = m.name + (f"_v{v.index}" if len(m.variations) > 1 else "")
            p = root / f"{tag}.{STAGE_EXT[s.stage]}.glsl"
            p.write_bytes(s.source if with_prologue else s.body)
            written.append(p)
        (root / "index.json").write_text(json.dumps(self.summary(), indent=1), "utf-8")
        written.append(root / "index.json")
        return written


def load(path) -> ShaderArchive:
    p = pathlib.Path(path)
    return ShaderArchive(p.read_bytes(), p.stem)


# ==========================================================================================
# Loose Muteki GLSL (what the PC build compiles)
# ==========================================================================================

# program -> (who loads it, vertex mask the exe passes).  Evidence in the module docstring.
MUTEKI_PROGRAMS = {
    "mtk_body": ("g3d models with blend indices (skinned); RF4S.exe+0x3C4720", 0x319),
    "mtk_item": ("g3d models with exactly position+uv0 attributes; RF4S.exe+0x3C4720", 0x11),
    "mtk_billboard": ("every other g3d model vertex layout; RF4S.exe+0x3C4720", 0x17),
    "mtk_text": ("text / UI passes (MageApplication_RenderScreen, RF4S.exe+0x1B1030)", 0x11),
    "mtk_color": ("VideoColorImageView (RF4S.exe+0x3C2950)", 0x11),
    "yuv420": ("movie frames (Cutscene_RenderVideoFrameWithOverlay)", None),
    "yuv444": ("movie frames (RF4S.exe+0x36C2D0); ships as .hlsl only -> fails to load", None),
    "mtk_0001": ("immediate-mode draws, mask 0x0001 (Renderer_GetOrCreateShaderProgram)", 0x1),
    "mtk_0011": ("immediate-mode draws, mask 0x0011", 0x11),
    "mtk_0015": ("immediate-mode draws, mask 0x0015", 0x15),
    "mtk_0017": ("immediate-mode draws, mask 0x0017", 0x17),
}

_BOM = b"\xef\xbb\xbf"


class ShaderIndex:
    """By-name index of loose shader files under one or more roots. Like the game's Bundle
    index, when a name exists more than once the path that sorts first wins, so pass the
    override folder first (or rely on `00_mods` sorting first under Bundle)."""

    EXTS = (".glsl", ".inc", ".hlsl")

    def __init__(self, *roots):
        self.files = {}
        for root in roots:
            root = pathlib.Path(root)
            if root.is_file():
                self.files.setdefault(root.name.lower(), root)
                continue
            if not root.is_dir():
                continue
            for p in sorted(root.rglob("*"), key=lambda q: str(q).lower()):
                if p.suffix.lower() in self.EXTS and p.is_file():
                    self.files.setdefault(p.name.lower(), p)

    def get(self, name):
        return self.files.get(name.lower())

    def read(self, name) -> bytes | None:
        p = self.get(name)
        return p.read_bytes() if p else None

    def programs(self) -> dict:
        """program name -> {'vertex','fragment','discard_fragment': path or None}."""
        names = set()
        for n in self.files:
            m = re.match(r"(.+?)_(v|f|discard_f)\.glsl$", n)
            if m:
                names.add(m.group(1))
        names |= set(MUTEKI_PROGRAMS)
        return {n: {"vertex": self.get(f"{n}_v.glsl"), "fragment": self.get(f"{n}_f.glsl"),
                    "discard_fragment": self.get(f"{n}_discard_f.glsl")}
                for n in sorted(names)}


_INCLUDE = re.compile(rb"#include")
_FP64 = b"330\n#extension GL_ARB_gpu_shader_fp64 : enable"


def preprocess(text: bytes, index: ShaderIndex, defines=None, missing=None, _depth=0) -> bytes:
    """Reconstruction of MCShader_PreprocessSource (RF4S.exe+0x27CCE0): `#include <x>` lines
    are replaced by the preprocessed file x, `#version` > 330 becomes 330 + the fp64
    extension, comments are skipped, and `defines` (the exe's dictionary: empty in practice)
    are inserted as `#define K V` lines after the #version line. Missing includes are left
    in place and appended to `missing` (the exe logs a warning and does the same)."""
    if _depth > 32:
        raise ShaderArchiveError("#include nesting deeper than 32 (cycle?)")
    s = text[3:] if text.startswith(_BOM) else text
    if defines:
        v = s.find(b"#version")
        if v >= 0:
            nl = s.find(b"\n", v)
            nl = len(s) if nl < 0 else nl + 1
            s = s[:nl] + b"".join(b"#define %s %s\n" % (k.encode(), str(val).encode())
                                  for k, val in defines.items()) + s[nl:]
    out = bytearray()
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == 0x2F and i + 1 < n and s[i + 1] == 0x2F:            # // comment
            j = s.find(b"\n", i)
            j = n if j < 0 else j
            out += s[i:j]
            i = j
        elif c == 0x2F and i + 1 < n and s[i + 1] == 0x2A:          # /* comment */
            j = s.find(b"*/", i + 2)
            j = n if j < 0 else j + 2
            out += s[i:j]
            i = j
        elif c == 0x23 and s.startswith(b"#include", i):
            j = s.find(b"\n", i)
            j = n if j < 0 else j
            line = s[i:j]
            a, b = line.find(b"<"), line.find(b">")
            name = line[a + 1:b].decode("utf-8", "replace") if 0 <= a < b else ""
            inc = index.read(name) if name else None
            if inc is None:
                if missing is not None:
                    missing.append(name or line.decode("utf-8", "replace"))
                out += line
            else:
                out += preprocess(inc, index, None, missing, _depth + 1)
            i = j
        elif c == 0x23 and s.startswith(b"#version", i):
            j = s.find(b"\n", i)
            j = n if j < 0 else j
            line = s[i:j]
            m = re.match(rb"#version\s+(\d+)", line)
            if m and int(m.group(1)) > 330:
                sp = line.find(b" ")
                out += line[:sp + 1] + _FP64
            else:
                out += line
            i = j
        else:
            out.append(c)
            i += 1
    return bytes(out)


def expand_program(name, index: ShaderIndex, discard=False) -> dict:
    """{'vertex': bytes, 'fragment': bytes, 'missing': [...]} as the game hands them to GL."""
    miss = []
    vs = index.read(f"{name}_v.glsl")
    fs = index.read(f"{name}_discard_f.glsl" if discard else f"{name}_f.glsl")
    if vs is None or fs is None:
        raise KeyError(f"{name}: need {name}_v.glsl and "
                       f"{name}_{'discard_' if discard else ''}f.glsl (not found)")
    return {"vertex": preprocess(vs, index, missing=miss),
            "fragment": preprocess(fs, index, missing=miss), "missing": miss}


def validate_source(name: str, text: bytes, index: ShaderIndex) -> list:
    """Static checks for an edited loose shader file. Returns a list of problems ([] = ok)."""
    probs = []
    try:
        text.decode("utf-8")
    except UnicodeDecodeError as e:
        probs.append(f"not valid UTF-8: {e}")
    if b"\x00" in text:
        probs.append("contains NUL bytes (glShaderSource gets a C string: text after it is lost)")
    miss = []
    full = preprocess(text, index, missing=miss)
    for m in miss:
        probs.append(f"#include <{m}> not found (the game logs a warning and compiles without it)")
    low = name.lower()
    if low.endswith(".glsl") and not low.endswith(".inc"):
        if b"#version" not in full:
            probs.append("no #version line")
        if not re.search(rb"void\s+main\s*\(", full):
            probs.append("no main() function")
    if low.endswith(".hlsl") or low.endswith(".hlsl.inc"):
        probs.append("HLSL files are never loaded by the PC build: edit the .glsl twin instead")
    if low.endswith(".bfsha"):
        probs.append("the PC build never compiles .bfsha GLSL (nn::gfx shader init is a stub)")
    return probs


def replace_loose(name: str, edited, out_dir, index: ShaderIndex) -> tuple:
    """Validate an edited loose shader `name` (e.g. 'mtk_body_f.glsl' or 'rf4lib.glsl.inc')
    and write it to out_dir/name for `rf4mod install`. Returns (path, problems)."""
    if index.get(name) is None and not name.lower().endswith((".glsl", ".inc")):
        raise KeyError(f"{name}: not a loose shader file name")
    text = pathlib.Path(edited).read_bytes() if not isinstance(edited, (bytes, bytearray)) \
        else bytes(edited)
    orig = index.read(name)
    if orig is not None and orig.startswith(_BOM) and not text.startswith(_BOM):
        text = _BOM + text            # keep the shipped files' UTF-8 BOM convention
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # validate with the edited text shadowing the original (includes resolve against it too)
    tmp_index = ShaderIndex()
    tmp_index.files = dict(index.files)
    dest = out / pathlib.Path(name).name
    dest.write_bytes(text)
    tmp_index.files[dest.name.lower()] = dest
    return dest, validate_source(name, text, tmp_index)
