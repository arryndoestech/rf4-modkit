r"""
texture.py -- RF4S `.texture` (NN RES, BNTX-derived) decode -> PNG and encode.

Container (every one of the 13,366 shipped .texture files, all magic `RES\0`;
offsets verified against the loader, see below):

    file header
      +0x0C u32 file size            +0x10 u32 _RLT offset  (BFRES_GetRelocationTableStart,
      +0x14 u32 string table (TEXT)                          RF4S.exe+0x3CA9B0: 'R' magic -> +0x10)
      +0x18 u32 name string offset   +0x1C u32 file size
    texture container @ +0x20 (BNTX TextureContainer layout)
      +0x24 u32 texture (frame) count      +0x28 u64 -> array of u64 PIXL offsets (always 0x198)
      +0x30 u64 -> DESC block              +0x38 u64 -> _DIC name dictionary
      +0x40 u64 -> memory-pool scratch (0x58)   +0x48 u64 pool ptr (runtime)   +0x50 u32 pool base
    one PIXL block per frame (BRTI layout; block size 0x390 with user data, 0x2A8 without)
      +0x10 u8 flags, u8 dim, u16 tileMode, u16 swizzle, u16 mipCount (== 1 in every shipped file)
      +0x1C u32 format code   +0x24 u32 width   +0x28 u32 height   +0x50 u32 imageSize (level 0)
      +0x60 u64 -> name (u16 len + chars)   +0x68 u64 -> container (0x20)
      +0x70 u64 -> mip pointer table (at PIXL+0x2A0): entry 0 = file offset of the level-0 data
      +0x78 u64 -> user data (TextureCoordinator / PolygonVertexes -- sprite UV rect and quad,
                  per-sprite values that do NOT follow from the dimensions; never rewritten here)
    DESC block: magic, u32 0, u64 block size (= 0x10 + all frame payloads); payload at DESC+0x10
    _RLT trailer: magic, u32 own offset, u32 section count, sections (0x18 each), entries (8 each)

Loader path (RF4S.exe RVAs): SpriteResourceRegistry_AcquireSlotForBfres (+0x1BE270) takes
the frame count from the _DIC count and calls the per-PIXL initialiser (+0x3C6000) for
every entry of the pointer array; that computes the pixel offset as
`poolBase + (mip0ptr - DESCptr) - 16` into the memory pool that +0x3C6130 installs over the
DESC payload (buffer = DESC+0x10, size = DESC.size - 16), then MGTexture_LoadFromPIXL
(+0x3D2230) reads format (PIXL+0x1C), width (+0x24) and height (+0x28), maps the code with
PIXL_FormatToMCTexFormat (+0x3D25B0) and uploads level 0 only through
MGTexture_CreateFromBuffer -> MGTexture_LoadFromData -> MCTexture_GLUpload (+0x2A34F0):
code 0x2001 (BC7) -> glCompressedTexImage2D(GL_COMPRESSED_RGBA_BPTC_UNORM, w, h, w*h bytes),
code 0x0B01 (RGBA8) -> glTexImage2D(GL_RGBA, GL_UNSIGNED_BYTE, w*h*4 bytes). Nothing reads
mipCount, imageSize or the mip pointers beyond entry 0. Sprite_BindFrameTexture (+0x1B7D90)
indexes the same pointer array with the frame index and takes each frame's size from its own
PIXL, so flipbook frames may differ in size (8x12d00.texture: 10x 64x32 + 32x16 + 64x32).

Relocation: BFRES_FixupRelocationPointers (+0x3CAA00) computes the image base as
`RLT - RLT[+4]` and adds it to every non-zero u64 slot listed by the entries (the DESC
pointer at +0x30 and each frame's mip pointer are among them). Section position/size and
the header file-size fields are not read by the fixup, but they are kept consistent.

Decoding (BC1/2/3/BC7) uses the optional `texture2ddecoder` package; raw color formats
(RGBA8 / RGBA4444 / ABGR1555 / GL_RED) are decoded natively. Decoded images are rotated
90deg CCW to match in-game orientation (the atlas is stored sideways -- see docs/09 s3 on
the UV swap); encode applies the inverse rotation so decode->edit->encode is
orientation-stable.

Encode: `encode_into` accepts ANY shipped .texture as template. The default (fmt=None or
"keep") re-encodes every replaced frame in the template frame's OWN format: BC7 / BC3 / BC1
through the bcenc encoders (same payload size, so the file keeps its size and stays
eligible for the in-place `rf4mod bundle patch`), raw formats natively; BC2 / ASTC frames
(none shipped) fall back to RGBA8. fmt="BC7"|"BC3"|"BC1"|"RGBA8"|raw name forces a format
(RGBA8 = code 0x0B01, 4 B/px, the same code the 112 shipped RGBA8 textures use -- 4x the
size of BC7). The container is rebuilt around the payload: DESC size, file sizes, _RLT
offset, the _RLT self-offset/section size, and every frame's format/imageSize/mip pointer.
Frames not replaced keep their original bytes and format, so a flipbook can mix formats.
Dimensions must match the template frame (the sprite UV/quad user data is per-sprite).

BNTX inside .model: `bntx_info` walks the embedded container's BRTI pointer array (all
offsets relative to the BNTX start), `decode_bntx` decodes one texture, `bntx_replace`
splices a same-size re-encoded payload over the original level-0 bytes (see docs/09 s4).
"""
from __future__ import annotations

import pathlib
import struct

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import texture2ddecoder
    HAS_BC = True
except ImportError:
    HAS_BC = False

from . import bcenc

MAGIC_RES = b"RES\x00"

# PIXL format code -> (name, bytes/px hint, decode-kind). Verified from
# PIXL_FormatToMCTexFormat (RF4S.exe+0x3D25B0). Only 0x2001 (BC7) and 0x0B01 (RGBA8)
# occur in the shipped corpus; the others are accepted by the loader.
PIXL_FMT_MAP = {
    513:  ("GL_RED_8bpp", 1, "raw"),
    769:  ("RGBA4444",    2, "raw"),
    1281: ("ABGR1555",    2, "raw"),
    2817: ("RGBA8",       4, "raw"),
    2819: ("RGBA8",       4, "raw"),
    5127: ("DEPTH",       4, "raw"),
    6657: ("BC1",         1, "bc1"),
    6913: ("BC2",         1, "bc2"),
    7169: ("BC3",         1, "bc3"),
    8193: ("BC7",         1, "bc7"),
    11521: ("ASTC_4x4",   1, "astc4"),
    12545: ("ASTC_6x6",   1, "astc6"),
}
# Inverse, for choosing a format code when encoding.
_NAME_TO_CODE = {"RGBA8": 2817, "RGBA4444": 769, "ABGR1555": 1281, "GL_RED_8bpp": 513}
RAW_FORMATS = tuple(_NAME_TO_CODE)
BC_KINDS = ("bc1", "bc2", "bc3", "bc7")
# Block formats the toolkit can WRITE (rf4s_modkit.bcenc) -> PIXL/BRTI code.
_BLOCK_TO_CODE = {"BC7": 8193, "BC3": 7169, "BC1": 6657}
_BLOCK_TO_KIND = {"BC7": "bc7", "BC3": "bc3", "BC1": "bc1"}
BLOCK_FORMATS = tuple(_BLOCK_TO_CODE)
# `fmt` values accepted by encode_into / bntx_replace (and the CLI --fmt choices).
ENCODE_FORMATS = ("keep",) + BLOCK_FORMATS + RAW_FORMATS

# Fixed container offsets (see module docstring).
_HDR_FILE_SIZE = 0x0C
_HDR_RLT = 0x10
_HDR_NAME = 0x18
_HDR_FILE_SIZE2 = 0x1C
_CNT_COUNT = 0x24
_CNT_ARRAY = 0x28
_CNT_DESC = 0x30
_CNT_DIC = 0x38
_PIXL_MIPS = 0x16
_PIXL_FMT = 0x1C
_PIXL_W = 0x24
_PIXL_H = 0x28
_PIXL_IMGSZ = 0x50
_PIXL_NAME = 0x60
_PIXL_MIPPTR = 0x70
_DESC_HDR = 0x10
_RLT_SECTIONS = 0x10
_RLT_SECTION_SIZE = 0x18


class TextureError(Exception):
    pass


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _u64(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def payload_size(fmt_code: int, w: int, h: int) -> int:
    """Level-0 payload bytes of a w x h image in PIXL format `fmt_code` (matches the
    upload sizes in MCTexture_GLUpload: BC1 8 B / 4x4 block, BC2/3/7 16 B, raw w*h*bpp)."""
    fmt_name, bpp, kind = PIXL_FMT_MAP.get(fmt_code, (None, 1, "unknown"))
    if kind in BC_KINDS:
        bpb = 8 if kind == "bc1" else 16
        return ((w + 3) // 4) * ((h + 3) // 4) * bpb
    if kind in ("astc4", "astc6"):
        blk = 4 if kind == "astc4" else 6
        return ((w + blk - 1) // blk) * ((h + blk - 1) // blk) * 16
    return w * h * bpp


def _name_at(data: bytes, off: int) -> str:
    if off <= 0 or off + 2 > len(data):
        return ""
    n = _u16(data, off)
    return data[off + 2:off + 2 + n].decode("utf-8", "replace")


def _walk_container(data: bytes) -> dict | None:
    """Follow the container pointers exactly as the loader does. Returns None when
    the pointers do not check out (then `parse` falls back to a magic scan)."""
    n = len(data)
    if n < 0x60:
        return None
    count = _u32(data, _CNT_COUNT)
    arr = _u64(data, _CNT_ARRAY)
    desc = _u64(data, _CNT_DESC)
    dic = _u64(data, _CNT_DIC)
    rlt = _u32(data, _HDR_RLT)
    if not (0 < count <= 4096 and arr + 8 * count <= n and desc + _DESC_HDR <= n
            and data[desc:desc + 4] == b"DESC"):
        return None
    if dic + 8 <= n and data[dic:dic + 4] == b"_DIC":
        dic_count = _u32(data, dic + 4)
        if dic_count != count:
            return None            # the engine trusts the _DIC count; a mismatch = not ours
    frames = []
    for k in range(count):
        px = _u64(data, arr + 8 * k)
        if px + 0x80 > n or data[px:px + 4] != b"PIXL":
            return None
        fmt_code = _u32(data, px + _PIXL_FMT)
        w, h = _u32(data, px + _PIXL_W), _u32(data, px + _PIXL_H)
        mipptr = _u64(data, px + _PIXL_MIPPTR)
        if mipptr + 8 > n:
            return None
        data_off = _u64(data, mipptr)
        fmt_name, bpp, kind = PIXL_FMT_MAP.get(fmt_code, (f"UNK_0x{fmt_code:X}", 0, "unknown"))
        frames.append({
            "index": k, "name": _name_at(data, _u64(data, px + _PIXL_NAME)),
            "pixl_off": px, "fmt_code": fmt_code, "fmt_name": fmt_name, "kind": kind,
            "width": w, "height": h, "mips": _u16(data, px + _PIXL_MIPS),
            "image_size": _u32(data, px + _PIXL_IMGSZ),
            "mipptr_off": mipptr, "data_off": data_off,
            "size": payload_size(fmt_code, w, h),
        })
    return {
        "frame_list": frames, "desc_off": desc, "dic_off": dic,
        "desc_size": _u64(data, desc + 8) if desc + 16 <= n else 0,
        "rlt_off": rlt, "rlt_ok": rlt + 4 <= n and data[rlt:rlt + 4] == b"_RLT",
        "file_size": _u32(data, _HDR_FILE_SIZE),
        "name": data[_u32(data, _HDR_NAME):].split(b"\0", 1)[0].decode("utf-8", "replace")
        if _u32(data, _HDR_NAME) < n else "",
    }


def parse(data: bytes) -> dict:
    """Metadata of a .texture. Top-level keys describe frame 0 (fmt_code, fmt_name, kind,
    width, height, pixel_off) for backward compatibility; `frames` is the frame count and
    `frame_list` holds one dict per frame (index, name, pixl_off, fmt_code, fmt_name, kind,
    width, height, mips, data_off, size). `container` is True when the pointer walk
    succeeded (required for encoding)."""
    if data[:4] != MAGIC_RES:
        raise TextureError(f"not a RES texture (magic={data[:4]!r})")
    walk = _walk_container(data)
    if walk is None:
        # Legacy magic scan (pre-2026-09 behaviour): first PIXL body + DESC payload.
        pixl = data.find(b"PIXL")
        desc = data.find(b"DESC")
        if pixl < 0 or desc < 0:
            raise TextureError("missing PIXL/DESC chunk (not a texture container?)")
        base = pixl + 0x10
        fmt_code = _u32(data, base + 12)
        width, height = _u32(data, base + 20), _u32(data, base + 24)
        fmt_name, bpp, kind = PIXL_FMT_MAP.get(fmt_code, (f"UNK_0x{fmt_code:X}", 0, "unknown"))
        fr = {"index": 0, "name": "", "pixl_off": pixl, "fmt_code": fmt_code,
              "fmt_name": fmt_name, "kind": kind, "width": width, "height": height,
              "mips": 1, "image_size": 0, "mipptr_off": -1, "data_off": desc + _DESC_HDR,
              "size": payload_size(fmt_code, width, height)}
        walk = {"frame_list": [fr], "desc_off": desc, "dic_off": -1, "desc_size": 0,
                "rlt_off": -1, "rlt_ok": False, "file_size": len(data), "name": ""}
        container = False
    else:
        container = True
    frames = walk["frame_list"]
    # Only frames whose payload is physically present are usable.
    usable = [f for f in frames if f["size"] > 0 and f["data_off"] + f["size"] <= len(data)]
    if not usable:
        usable = frames[:1]
    f0 = usable[0]
    info = {
        "fmt_code": f0["fmt_code"], "fmt_name": f0["fmt_name"], "kind": f0["kind"],
        "width": f0["width"], "height": f0["height"],
        "pixel_off": f0["data_off"],
        "frames": len(usable), "frames_declared": len(frames),
        "frame_list": usable, "container": container,
        "mips": max(f["mips"] for f in usable),
    }
    info.update({k: walk[k] for k in ("desc_off", "dic_off", "desc_size", "rlt_off",
                                       "rlt_ok", "file_size", "name")})
    return info


def _payload_size(info: dict) -> int:
    """Level-0 payload bytes of frame 0 (kept for callers of the old helper)."""
    return payload_size(info["fmt_code"], info["width"], info["height"])


def frame_count(data: bytes, info: dict | None = None) -> int:
    """Number of frames (sub-textures) in a .texture: the container's texture count,
    limited to frames whose payload is physically present. Static sheets report 1;
    confetti.texture holds 15 8x8 BC7 cells; 8x12d00.texture holds 12 frames of
    mixed sizes (the engine indexes them via the pointer array, see module docstring)."""
    if info is None:
        info = parse(data)
    return info["frames"]


def _decode_frame(data: bytes, fr: dict):
    """Decode one frame dict (from parse()['frame_list']) to a PIL image in STORAGE
    orientation (no rotation). None for unsupported formats."""
    w, h, kind, fmt = fr["width"], fr["height"], fr["kind"], fr["fmt_name"]
    nbytes, off = fr["size"], fr["data_off"]
    raw = data[off:off + nbytes]
    if len(raw) < nbytes:
        raise TextureError(f"pixel data truncated: need {nbytes}, have {len(raw)}")
    if kind in BC_KINDS:
        if not HAS_BC:
            raise TextureError("block-compressed decode needs: pip install texture2ddecoder")
        fn = {"bc1": texture2ddecoder.decode_bc1,
              "bc2": getattr(texture2ddecoder, "decode_bc2", texture2ddecoder.decode_bc3),
              "bc3": texture2ddecoder.decode_bc3,
              "bc7": texture2ddecoder.decode_bc7}[kind]
        rgba = fn(raw, w, h)
        return Image.frombytes("RGBA", (w, h), bytes(rgba), "raw", "BGRA")
    if fmt == "RGBA8":
        return Image.frombytes("RGBA", (w, h), raw[:w * h * 4], "raw", "RGBA")
    if fmt == "RGBA4444":
        return _decode_rgba4444(raw, w, h)
    if fmt == "ABGR1555":
        return _decode_abgr1555(raw, w, h)
    if fmt == "GL_RED_8bpp":
        return Image.frombytes("L", (w, h), raw[:w * h])
    return None


def decode_to_image(data: bytes, *, rotate: bool = True, frame: int = 0):
    """Decode one frame of a .texture to a PIL RGBA/L Image (None if format
    unsupported). `frame` indexes the flipbook (see frame_count); 0 = the only
    frame of a static texture."""
    if not HAS_PIL:
        raise TextureError("Pillow required: pip install Pillow")
    info = parse(data)
    frame = max(0, int(frame))
    if frame >= info["frames"]:
        raise TextureError(f"frame {frame} out of range (texture has {info['frames']})")
    img = _decode_frame(data, info["frame_list"][frame])
    if img is None:
        return None
    return img.transpose(Image.ROTATE_90) if rotate else img


# --- Standard Nintendo BNTX (used by .model "over-model" billboards) ------------
# DISTINCT from the .texture PIXL/DESC format above. A map's over-model
# (g_mapResourceTable[+3], rom:/map_overmodel/MAP_*.bfres, stored as MAP_*.model)
# is a RES\0 wrapper around a standard BNTX. RF4's map over-models are ALL
# LINEAR (tileMode=1) BC3, so no Switch block-linear deswizzle is needed.
# Unlike the rotated ground atlas, these are upright (no ROTATE_90).
_BNTX_FMT_KIND = {0x1A: "bc1", 0x1B: "bc2", 0x1C: "bc3", 0x1D: "bc4",
                  0x1E: "bc5", 0x20: "bc7", 0x0B: "rgba8"}


def bntx_textures(data: bytes) -> list:
    """Ordered (BRTI_off, BRTD_off) pairs for each texture in a BNTX/.model blob."""
    bn = data.find(b"BNTX")
    if bn < 0:
        return []
    brtis, i = [], bn
    while True:
        i = data.find(b"BRTI", i)
        if i < 0:
            break
        brtis.append(i)
        i += 4
    brtds, j = [], bn
    while True:
        j = data.find(b"BRTD", j)
        if j < 0:
            break
        brtds.append(j)
        j += 4
    return [(brtis[k], brtds[k] if k < len(brtds) else (brtds[0] if brtds else -1))
            for k in range(len(brtis))]


def bntx_info(data: bytes) -> list:
    """Per-texture metadata of the BNTX embedded in a .model (or a bare BNTX), walked
    the way the container is laid out: BNTX+0x24 texture count, BNTX+0x28 -> u64[count]
    BRTI offsets, every pointer RELATIVE to the BNTX start (the BNTX carries its own
    _RLT at BNTX+0x18; the outer RES _RLT only lists the two embedded-file slots).
    One dict per texture: index, name, width, height, fmt_code, fmt_name, kind, tile,
    mips, image_size (BRTI+0x50), brti_off, data_off (absolute file offset of level 0
    = BNTX + mip table[0]), size (payload bytes from format x dimensions -- equals
    image_size in all 1,805 textures of the 910 shipped .model files). Falls back to a
    BRTI magic scan when the pointer walk fails."""
    bn = data.find(b"BNTX")
    n = len(data)
    if bn < 0 or bn + 0x58 > n:
        return []
    count = _u32(data, bn + 0x24)
    arr = bn + _u64(data, bn + 0x28)
    brtis = []
    if 0 < count <= 4096 and arr + 8 * count <= n:
        for k in range(count):
            b = bn + _u64(data, arr + 8 * k)
            if b + 0x80 > n or data[b:b + 4] != b"BRTI":
                brtis = []
                break
            brtis.append(b)
    if not brtis:
        brtis = [b for b, _d in bntx_textures(data) if b + 0x80 <= n]
    out = []
    for k, b in enumerate(brtis):
        fmt_code = _u32(data, b + _PIXL_FMT)
        w, h = _u32(data, b + _PIXL_W), _u32(data, b + _PIXL_H)
        fmt_name, _bpp, kind = PIXL_FMT_MAP.get(fmt_code, (f"UNK_0x{fmt_code:X}", 0, "unknown"))
        mipptr = bn + _u64(data, b + _PIXL_MIPPTR)
        data_off = bn + _u64(data, mipptr) if 0 <= mipptr <= n - 8 else -1
        noff = bn + _u64(data, b + _PIXL_NAME)
        out.append({
            "index": k, "name": _name_at(data, noff) if 0 < noff < n else "",
            "width": w, "height": h, "fmt_code": fmt_code, "fmt_name": fmt_name, "kind": kind,
            "tile": _u16(data, b + 0x12), "mips": _u16(data, b + _PIXL_MIPS),
            "image_size": _u32(data, b + _PIXL_IMGSZ), "brti_off": b, "data_off": data_off,
            "size": payload_size(fmt_code, w, h),
        })
    return out


def decode_bntx(data: bytes, index: int = 0):
    """Decode one texture of a standard BNTX (e.g. a .model over-model billboard)
    to a PIL RGBA Image. Returns None if unsupported. Linear (tileMode=1) only --
    sufficient for every RF4 .model texture (1,805 of them); raises on swizzled input.
    Upright: unlike the .texture atlas no rotation is applied."""
    if not HAS_PIL:
        raise TextureError("Pillow required: pip install Pillow")
    infos = bntx_info(data)
    if not infos or index >= len(infos):
        return None
    t = infos[index]
    if t["tile"] != 1:
        raise TextureError(f"swizzled BNTX (tileMode={t['tile']}) not supported")
    w, h, imgsz, off = t["width"], t["height"], t["image_size"], t["data_off"]
    if off < 0 or off + imgsz > len(data):
        return None
    raw = data[off: off + imgsz]
    fr = dict(t, data_off=off, size=imgsz if imgsz else t["size"])
    try:
        return _decode_frame(data, fr)
    except TextureError:
        raise
    except Exception:
        return None


def bntx_replace(data: bytes, index: int, png, *, fmt: str | None = None) -> bytes:
    """Replace texture `index` of the BNTX embedded in a .model IN PLACE and return the
    new file bytes. `png` (path or PIL Image, upright) must have the texture's own
    dimensions. fmt None/"keep" re-encodes in the texture's own format (BC1/BC3/BC7 via
    bcenc, the raw formats natively); another format is accepted only when its payload
    is exactly the same size (BC3 <-> BC7), and then the BRTI format code (+0x1C) is
    rewritten as well. The new level-0 bytes overwrite the old ones at data_off; the
    mip pointer, image size, mip count, name, _DIC and both relocation tables are left
    untouched (nothing else is read for the upload -- docs/09 s4)."""
    if not HAS_PIL:
        raise TextureError("Pillow required: pip install Pillow")
    infos = bntx_info(data)
    if not infos:
        raise TextureError("no BNTX texture container in this file")
    if not 0 <= index < len(infos):
        raise TextureError(f"texture index {index} out of range (file has {len(infos)})")
    t = infos[index]
    images = _as_images(png)
    if len(images) != 1:
        raise TextureError("bntx_replace takes exactly one image")
    im = images[0].convert("RGBA")
    if im.size != (t["width"], t["height"]):
        raise TextureError(f"image is {im.size}, texture {index} ({t['name']}) is "
                           f"{t['width']}x{t['height']}; dimensions must match")
    if t["data_off"] < 0 or t["data_off"] + t["image_size"] > len(data):
        raise TextureError(f"texture {index}: level-0 data outside the file")
    target = _resolve_target(t["fmt_name"], t["kind"], fmt)
    code, payload = _encode_frame(im, target)
    if len(payload) != t["image_size"]:
        raise TextureError(
            f"{target} payload is {len(payload):,} B but texture {index} holds {t['image_size']:,} B "
            f"({t['fmt_name']}); .model textures are replaced in place, so the format must keep "
            f"the payload size (leave fmt at 'keep', or BC3 <-> BC7)")
    out = bytearray(data)
    out[t["data_off"]:t["data_off"] + len(payload)] = payload
    if code != t["fmt_code"]:
        struct.pack_into("<I", out, t["brti_off"] + _PIXL_FMT, code)
    return bytes(out)


def bntx_list(data: bytes) -> list:
    """Per-texture metadata for a BNTX/.model blob: list of dicts
    {index, name, w, h, fmt_code, fmt_name}. Name from BRTI+0x60 (u16 len +
    chars). Metadata only — safe without Pillow/texture2ddecoder."""
    bn = data.find(b"BNTX")
    if bn < 0:
        return []
    out = []
    for i, (brti, _brtd) in enumerate(bntx_textures(data)):
        if brti + 0x78 > len(data):
            continue
        fmt = struct.unpack_from("<I", data, brti + 0x1C)[0]
        w = struct.unpack_from("<I", data, brti + 0x24)[0]
        h = struct.unpack_from("<I", data, brti + 0x28)[0]
        noff = bn + struct.unpack_from("<Q", data, brti + 0x60)[0]
        nm = "?"
        if 0 <= noff <= len(data) - 2:
            nl = struct.unpack_from("<H", data, noff)[0]
            nm = data[noff + 2: noff + 2 + nl].decode("latin1", "replace")
        out.append({"index": i, "name": nm, "w": w, "h": h, "fmt_code": fmt,
                    "fmt_name": _BNTX_FMT_KIND.get(fmt >> 8, f"0x{fmt:04x}")})
    return out


def _decode_rgba4444(raw, w, h):
    out = bytearray(w * h * 4)
    for i in range(w * h):
        v = raw[2 * i] | (raw[2 * i + 1] << 8)
        r, g, b, a = (v >> 12) & 0xF, (v >> 8) & 0xF, (v >> 4) & 0xF, v & 0xF
        out[4 * i:4 * i + 4] = bytes((r * 17, g * 17, b * 17, a * 17))
    return Image.frombytes("RGBA", (w, h), bytes(out))


def _decode_abgr1555(raw, w, h):
    out = bytearray(w * h * 4)
    for i in range(w * h):
        v = raw[2 * i] | (raw[2 * i + 1] << 8)
        r, g, b, a = v & 0x1F, (v >> 5) & 0x1F, (v >> 10) & 0x1F, (v >> 15) & 1
        out[4 * i] = (r << 3) | (r >> 2)
        out[4 * i + 1] = (g << 3) | (g >> 2)
        out[4 * i + 2] = (b << 3) | (b >> 2)
        out[4 * i + 3] = 0xFF if a else 0x00
    return Image.frombytes("RGBA", (w, h), bytes(out))


def decode_frames(data: bytes, *, rotate: bool = True) -> list:
    """Decode every flipbook frame (list of PIL Images; single-element for
    static textures). Frames that fail to decode are skipped."""
    info = parse(data)
    out = []
    for i in range(info["frames"]):
        try:
            im = decode_to_image(data, rotate=rotate, frame=i)
        except TextureError:
            break
        if im is not None:
            out.append(im)
    return out


def strip_boxes(info: dict, *, rotate: bool = True) -> tuple:
    """Layout of the frame STRIP used by decode_strip / encode_into(strip=True):
    frames side by side left-to-right in index order, top-aligned, each at its
    decoded (post-rotation) size. Returns ((W, H), [(x, y, w, h), ...])."""
    boxes, x, hmax = [], 0, 0
    for fr in info["frame_list"]:
        w, h = (fr["height"], fr["width"]) if rotate else (fr["width"], fr["height"])
        boxes.append((x, 0, w, h))
        x += w
        hmax = max(hmax, h)
    return (x, hmax), boxes


def decode_strip(data: bytes, *, rotate: bool = True):
    """All frames as one horizontal strip image (see strip_boxes). Returns
    (PIL RGBA Image, boxes). For a static texture this is just the image."""
    if not HAS_PIL:
        raise TextureError("Pillow required: pip install Pillow")
    info = parse(data)
    (W, H), boxes = strip_boxes(info, rotate=rotate)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for i, (x, y, w, h) in enumerate(boxes):
        im = decode_to_image(data, rotate=rotate, frame=i)
        if im is None:
            raise TextureError(f"unsupported format {info['frame_list'][i]['fmt_name']}")
        canvas.paste(im.convert("RGBA"), (x, y))
    return canvas, boxes


def decode_to_png(in_path, out_path=None, *, frame: int = 0, strip: bool = False) -> pathlib.Path:
    """Decode a .texture file to PNG (frame `frame`, or every frame as a strip)."""
    data = pathlib.Path(in_path).read_bytes()
    if strip:
        img = decode_strip(data)[0]
    else:
        img = decode_to_image(data, frame=frame)
    if img is None:
        info = parse(data)
        raise TextureError(f"unsupported format {info['fmt_name']} (0x{info['fmt_code']:X})")
    out = pathlib.Path(out_path) if out_path else pathlib.Path(in_path).with_suffix(".png")
    img.convert("RGBA").save(out)
    return out


def relocation_slots(data: bytes) -> list:
    """Walk the _RLT exactly like BFRES_FixupRelocationPointers (RF4S.exe+0x3CAA00):
    image base = RLT - RLT[+4]; entries follow the 16-byte header and the 24-byte
    sections; entry = {u32 slot, u16 structCount, u8 offsetCount, u8 paddingCount};
    slot(i, j) = slot + 8*(i + j*(offsetCount+paddingCount)). Returns
    [(slot_offset, target_offset), ...] for every non-zero pointer the loader would
    rebase. Raises TextureError on anything the loader asserts on (a slot at or
    past the table) or a target outside the file -- so a rewritten container that
    passes this check relocates cleanly in the engine."""
    info = parse(data)
    rlt = info["rlt_off"]
    if not info["rlt_ok"]:
        raise TextureError("no _RLT trailer")
    if (_u32(data, rlt + 4) & 0x7FFFFFFF) != rlt:
        raise TextureError(f"_RLT self offset 0x{_u32(data, rlt + 4):x} != 0x{rlt:x}")
    nsec = _u32(data, rlt + 8)
    entries = rlt + _RLT_SECTIONS + _RLT_SECTION_SIZE * nsec
    out = []
    for s in range(nsec):
        so = rlt + _RLT_SECTIONS + _RLT_SECTION_SIZE * s
        first, count = _u32(data, so + 16), _u32(data, so + 20)
        for e in range(first, first + count):
            eo = entries + 8 * e
            if eo + 8 > len(data):
                raise TextureError(f"_RLT entry {e} beyond file")
            slot, nstruct = _u32(data, eo), _u16(data, eo + 4)
            noff, npad = data[eo + 6], data[eo + 7]
            for j in range(nstruct):
                for i in range(noff):
                    so_ = slot + 8 * (i + j * (noff + npad))
                    if so_ >= rlt:
                        raise TextureError(f"_RLT slot 0x{so_:x} not before the table (0x{rlt:x})")
                    tgt = _u64(data, so_)
                    if tgt:
                        if tgt > len(data):
                            raise TextureError(f"slot 0x{so_:x} points at 0x{tgt:x} beyond the file")
                        out.append((so_, tgt))
    return out


def describe(data: bytes) -> str:
    """Multi-line human summary (used by `rf4mod texture info` and the GUI)."""
    info = parse(data)
    lines = [f"{info['fmt_name']} (code 0x{info['fmt_code']:X})  {info['width']}x{info['height']}"
             f"  frames={info['frames']}  mips={info['mips']}  pixels@0x{info['pixel_off']:x}"]
    if info["container"]:
        lines.append(f"container: name={info['name']!r}  DESC@0x{info['desc_off']:x} "
                     f"(size 0x{info['desc_size']:x})  _RLT@0x{info['rlt_off']:x}"
                     f"{'' if info['rlt_ok'] else ' (MISSING)'}  file size field "
                     f"{info['file_size']} ({'ok' if info['file_size'] == len(data) else 'MISMATCH'})")
    else:
        lines.append("container: pointer walk failed -- legacy magic scan (not encodable)")
    if info["frames"] > 1 or info["mips"] > 1:
        for fr in info["frame_list"]:
            lines.append(f"  frame {fr['index']:2d}: {fr['name'] or '?':32s} {fr['fmt_name']:9s} "
                         f"{fr['width']}x{fr['height']}  mips={fr['mips']}  "
                         f"data@0x{fr['data_off']:x} ({fr['size']} B)")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Encode
# --------------------------------------------------------------------------- #
def _encode_raw(img, fmt_name: str) -> bytes:
    img = img.convert("RGBA")
    px = img.tobytes("raw", "RGBA")
    w, h = img.size
    if fmt_name == "RGBA8":
        return px
    if fmt_name == "RGBA4444":
        out = bytearray(w * h * 2)
        for i in range(w * h):
            r, g, b, a = px[4 * i:4 * i + 4]
            v = ((r >> 4) << 12) | ((g >> 4) << 8) | ((b >> 4) << 4) | (a >> 4)
            out[2 * i] = v & 0xFF
            out[2 * i + 1] = (v >> 8) & 0xFF
        return bytes(out)
    if fmt_name == "ABGR1555":
        out = bytearray(w * h * 2)
        for i in range(w * h):
            r, g, b, a = px[4 * i:4 * i + 4]
            v = (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10) | ((1 if a >= 128 else 0) << 15)
            out[2 * i] = v & 0xFF
            out[2 * i + 1] = (v >> 8) & 0xFF
        return bytes(out)
    if fmt_name == "GL_RED_8bpp":
        return img.convert("L").tobytes()
    raise TextureError(f"cannot raw-encode format {fmt_name}")


def _resolve_target(fmt_name: str, kind: str, fmt: str | None) -> str:
    """Storage format name for a replaced frame: `fmt` if forced, else the frame's own
    format when the toolkit can write it (BC7/BC3/BC1 + the raw formats), else RGBA8."""
    if fmt is None or fmt == "keep":
        if kind in _BLOCK_TO_KIND.values():
            return fmt_name
        if fmt_name in _NAME_TO_CODE:
            return fmt_name
        return "RGBA8"
    if fmt in _BLOCK_TO_CODE or fmt in _NAME_TO_CODE:
        return fmt
    raise TextureError(f"fmt must be one of {ENCODE_FORMATS}, not {fmt!r}")


def _encode_frame(im, target: str) -> tuple:
    """(format code, payload bytes) for a PIL image in storage orientation."""
    if target in _BLOCK_TO_CODE:
        return _BLOCK_TO_CODE[target], bcenc.encode_image(_BLOCK_TO_KIND[target], im)
    return _NAME_TO_CODE[target], _encode_raw(im, target)


def _as_images(png) -> list:
    """Normalise the `png` argument of encode_into to a list of PIL Images."""
    if isinstance(png, (list, tuple)):
        out = []
        for p in png:
            out.extend(_as_images(p))
        return out
    if hasattr(png, "size") and hasattr(png, "mode"):   # a PIL Image
        return [png]
    img = Image.open(png)
    img.load()
    return [img]


def encode_into(template: bytes, png, *, rotate: bool = True, frame: int | None = None,
                strip: bool = False, fmt: str | None = None) -> bytes:
    """
    Produce a new .texture by replacing the pixels of `template` (ANY shipped .texture)
    with `png`. Returns the new .texture bytes.

    png    -- a PNG path, a PIL Image, or a list of them (one per frame, in frame order).
    frame  -- replace only this frame index of a flipbook (png = one image).
    strip  -- png is one image holding every frame side by side, as decode_strip lays
              them out (frames left-to-right, top-aligned, decoded sizes).
    fmt    -- storage format for the replaced frames: None / "keep" (default) re-encodes
              each frame in its template frame's own format (BC7 / BC3 / BC1 through
              bcenc -- same payload size -- or the raw format; BC2 / ASTC -> RGBA8); or
              force "BC7" / "BC3" / "BC1" / "RGBA8" / "RGBA4444" / "ABGR1555" / "GL_RED_8bpp".
    rotate -- undo the decoder's 90deg CCW rotation (images are in in-game orientation).

    Each image must have its template frame's dimensions (after un-rotation). Frames
    not replaced keep their original bytes and format. The container is rebuilt for
    the new payload size (see module docstring for the fields the loader reads); with
    the default it comes out the same size as the template (bundle-patchable in place).
    """
    if not HAS_PIL:
        raise TextureError("Pillow required: pip install Pillow")
    info = parse(template)
    if not info["container"] or not info["rlt_ok"]:
        raise TextureError("template container could not be walked (no _RLT / bad pointers); "
                           "only shipped-layout .texture files can be re-encoded")
    if fmt is not None and fmt not in ENCODE_FORMATS:
        raise TextureError(f"fmt must be one of {ENCODE_FORMATS}, not {fmt!r}")
    if info["frames"] != info["frames_declared"]:
        raise TextureError(f"template declares {info['frames_declared']} frames but only "
                           f"{info['frames']} are physically present (truncated file)")
    frames = info["frame_list"]
    nfr = len(frames)

    # ---- which frames get which image ----
    images = _as_images(png)
    new = {}
    if strip:
        if len(images) != 1:
            raise TextureError("strip=True takes exactly one image")
        (W, H), boxes = strip_boxes(info, rotate=rotate)
        im = images[0]
        if im.size != (W, H):
            raise TextureError(f"strip is {im.size}, template strip layout is {(W, H)} "
                               f"({nfr} frame(s))")
        for i, (x, y, w, h) in enumerate(boxes):
            new[i] = im.crop((x, y, x + w, y + h))
    elif frame is not None:
        if len(images) != 1:
            raise TextureError("frame=N takes exactly one image")
        if not 0 <= frame < nfr:
            raise TextureError(f"frame {frame} out of range (template has {nfr})")
        new[frame] = images[0]
    else:
        if len(images) == 1 and nfr > 1:
            raise TextureError(f"template has {nfr} frames: pass one image per frame, "
                               f"frame=N to replace a single frame, or strip=True")
        if len(images) != nfr:
            raise TextureError(f"{len(images)} image(s) for a {nfr}-frame template")
        for i, im in enumerate(images):
            new[i] = im

    # ---- per-frame payloads ----
    payloads = []          # (fmt_code, bytes) in frame order
    for fr in frames:
        i = fr["index"]
        if i not in new:
            payloads.append((fr["fmt_code"], template[fr["data_off"]:fr["data_off"] + fr["size"]]))
            continue
        im = new[i]
        if rotate:
            im = im.transpose(Image.ROTATE_270)   # inverse of decode's ROTATE_90
        if im.size != (fr["width"], fr["height"]):
            shown = (fr["height"], fr["width"]) if rotate else (fr["width"], fr["height"])
            raise TextureError(
                f"frame {i}: image is {new[i].size}, template frame is {shown} (as decoded); "
                f"dimensions must match -- the sprite UV/quad data is per-sprite")
        payloads.append(_encode_frame(im, _resolve_target(fr["fmt_name"], fr["kind"], fmt)))

    return _rebuild(template, info, payloads)


def _rebuild(template: bytes, info: dict, payloads: list) -> bytes:
    """Rewrite the container around new per-frame payloads (frame order)."""
    desc = info["desc_off"]
    rlt = info["rlt_off"]
    frames = info["frame_list"]
    body = bytearray(template[:desc + _DESC_HDR])
    # Frame payloads are stored back to back (as shipped); the block is padded to a
    # 16-byte multiple so the _RLT keeps the alignment every shipped file has.
    offsets, blob = [], bytearray()
    for _code, pb in payloads:
        offsets.append(len(blob))
        blob += pb
    if len(blob) % 16:
        blob += b"\0" * (16 - len(blob) % 16)
    new_rlt_off = desc + _DESC_HDR + len(blob)
    trailer = bytearray(template[rlt:])
    out = body + blob + trailer
    # header: file sizes + _RLT offset
    struct.pack_into("<I", out, _HDR_FILE_SIZE, len(out))
    struct.pack_into("<I", out, _HDR_RLT, new_rlt_off)
    struct.pack_into("<I", out, _HDR_FILE_SIZE2, len(out))
    # DESC block size = header + payload (this is the memory-pool size, +0x3C6130)
    struct.pack_into("<Q", out, desc + 8, _DESC_HDR + len(blob))
    # _RLT: self offset (the fixup derives the image base from it), data-section size
    struct.pack_into("<I", out, new_rlt_off + 4, new_rlt_off)
    nsec = _u32(out, new_rlt_off + 8)
    for s in range(min(nsec, 16)):
        so = new_rlt_off + _RLT_SECTIONS + _RLT_SECTION_SIZE * s
        if so + _RLT_SECTION_SIZE > len(out):
            break
        if _u32(out, so + 8) == desc:                     # section covering the DESC block
            struct.pack_into("<I", out, so + 12, _DESC_HDR + len(blob))
    # per-frame PIXL: format, level-0 size, single mip level, data pointer
    for fr, (code, pb), rel in zip(frames, payloads, offsets):
        px = fr["pixl_off"]
        struct.pack_into("<H", out, px + _PIXL_MIPS, 1)
        struct.pack_into("<I", out, px + _PIXL_FMT, code)
        struct.pack_into("<I", out, px + _PIXL_IMGSZ, len(pb))
        struct.pack_into("<Q", out, fr["mipptr_off"], desc + _DESC_HDR + rel)
        for m in range(1, fr["mips"]):                   # drop extra mip pointers (never shipped)
            mo = fr["mipptr_off"] + 8 * m
            if mo + 8 <= desc:
                struct.pack_into("<Q", out, mo, 0)
    return bytes(out)
