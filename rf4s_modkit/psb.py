r"""
psb.py -- E-mote PSB reader / texture tool for the RF4S character portraits.

WHAT SHIPS (bundleMain, 130 files, all PSB version 4)
-----------------------------------------------------
  66 x .psbData   the portraits the PC game loads.  RF4S.exe names 64 of them as
                  "rom:/emote/<NN_NAME[_OUTFIT]>.psbData" (strings at RF4S.exe+0x4E69B8..
                  +0x4E7348); B_FORTE.psbData and PLAYER_W_SMALL.psbData are in the bundle
                  manifest but not named by the exe (inferred: unused).  One RGBA8 atlas.
  64 x .emtbytes  the SAME E-mote models (identical name table, string table and tree --
                  checked after the text repair below) with the atlas stored as
                  "ASTC_8BPP" (ASTC 4x4 blocks, 8 bpp) and the PSB header XOR-encrypted.
                  RF4S.exe contains no "emtbytes" string: the PC build never loads them
                  (a console-format leftover).  Readable here; not re-encodable (no ASTC
                  encoder), and there is no reason to -- edit the .psbData.

  RF4S.exe imports only EmoteCreate from emotedriver.dll (IAT RF4S.exe+0x4438F8); the rest
  of the E-mote API is reached through the IEmoteDevice / IEmotePlayer vtables, and the
  PSB is parsed inside the driver.  Everything below the header is therefore byte
  analysis of the shipped files (all 130 parse with this reader).

PSB LAYOUT (v4; verified on all 130 files)
------------------------------------------
  +0x00 'PSB\0'   +0x04 u16 version (4)   +0x06 u16 header-encrypt flag
  +0x08 12 x u32: off_encrypt, off_names, off_strings, off_strings_data,
                  off_chunk_offsets, off_chunk_lengths, off_chunk_data, off_root,
                  checksum, off_extra_offsets, off_extra_lengths, off_extra_data
  checksum = adler32 over the 11 other header u32s (the 8 before it, then the 3 after)
           -- verified on every file.
  header encryption (flag 1, the .emtbytes): the 48 bytes at +0x08 are XORed with an
  XorShift128 stream seeded (123456789, 362436069, 521288629, KEY), 4 LE bytes per step.
  KEY = 0x1DBD775C, recovered by known plaintext (off_encrypt == 0x38) and confirmed by
  all 64 .emtbytes decrypting to consistent offsets and parsing.  The body is not
  encrypted.  (The key is not stored as a literal in RF4S.exe or emotedriver.dll.)

  Values (type byte + payload): 1 null, 2/3 false/true, 4 int 0, 5..0xC int of 1..8 bytes
  (LE signed), 0xD..0x14 packed uint array (count width t-0xC, count, element-width byte,
  elements), 0x15..0x18 string index, 0x19..0x1C chunk (resource) index, 0x1D float 0,
  0x1E float32, 0x1F float64, 0x20 list (offset array + base), 0x21 object (name-index
  array, offset array, base), 0x22..0x25 extra-chunk index.  Names are a trie of three
  arrays (charset, tree, leaf index).

  Chunk 0 is the one texture atlas (source/tex/texture/pixel).  Extra chunks hold the
  mesh-deformer "rawMeshList" payloads (384/640 bytes each).

  RGBA8 pixel order is R,G,B,A (verified: matches the .emtbytes ASTC decode of the same
  atlas to a mean abs error of 0.004/255; the BGRA reading is off by ~6/255).

TEXT ENCODING
-------------
  Every non-ASCII string / name in the .psbData is DOUBLE-encoded (UTF-8 -> read as
  cp1252 -> UTF-8 again); the .emtbytes hold the clean UTF-8.  RF4S.exe carries the very
  same double-encoded bytes for the timeline labels it plays (e.g. RF4S.exe+0x4E6520 =
  "通常"), and the driver matches labels byte-for-byte -- so NEVER re-encode those
  strings when editing.  `repair_text` gives a readable form for display / JSON only.

HOW THE GAME PICKS PORTRAIT + EXPRESSION (RF4S.exe+0x1D8730; offline disassembly of
RF4S.exe on disk, not yet cross-checked in the IDB)
--------------------------------------------------------------------------------
  * file: the path table at RF4S.exe+0x4D9FE0 = 6 path pointers per character row
    (row 0/1 = player M/W, NPC row = id+1): columns 0 base, 1 SP1 variant, 2 swimsuit,
    3 pajama, 4 wedding, 5 SP2 variant.  A second table at RF4S.exe+0x9EB130 lists
    {character, column, path} for the eight SP files.
  * expression: an id < 1000 is first mapped through the character's u16 table
    (pointer array RF4S.exe+0x4DA670, 4-byte entries); the result (1000..1927) minus 1000
    indexes the face x gesture table at RF4S.exe+0xDAE3C0: 29 face rows x 32 gesture columns of
    (face timeline label, gesture timeline label).  The player's timelines are switched
    only when the label differs from the one playing.  For every character the first six
    ids map to rows 0..5 with gesture 0, i.e. opcode_meta.FACE_FRAMES 0..5 =
    FACE_TIMELINES[0..5] ("通常" normal ... "照れ" blush) + "差分用_waiting_loop".
    Ids 1192 / 1224 are the SP1 / SP2 rows (and select column 1 / 5 files).
"""
from __future__ import annotations

import json
import pathlib
import struct
import zlib

MAGIC = b"PSB\x00"
HEADER_KEY = 0x1DBD775C
_XS_SEED = (123456789, 362436069, 521288629)
_M = 0xFFFFFFFF

HEADER_FIELDS = ("off_encrypt", "off_names", "off_strings", "off_strings_data",
                 "off_chunk_offsets", "off_chunk_lengths", "off_chunk_data", "off_root",
                 "checksum", "off_extra_offsets", "off_extra_lengths", "off_extra_data")

# RF4S.exe+0xDAE3C0 rows (face timeline label) and columns (gesture timeline label).
FACE_TIMELINES = (
    "通常", "怒り", "哀しみ", "笑顔", "驚き", "照れ", "SP1", "SP2",
    "喜ぶ00", "喜ぶ01", "喜ぶ02", "怒る00", "怒る01", "怒る02", "哀しい00", "哀しい01",
    "哀しい02", "楽しい00", "楽しい01", "楽しい02", "頬染め00", "頬染め01", "頬染め02",
    "驚き00", "驚き01", "驚き02", "困る00", "困る01", "困る02")
FACE_TIMELINES_EN = (
    "normal", "angry", "sad", "smile", "surprise", "blush", "SP1", "SP2",
    "joy00", "joy01", "joy02", "anger00", "anger01", "anger02", "sad00", "sad01",
    "sad02", "fun00", "fun01", "fun02", "flush00", "flush01", "flush02",
    "surprise00", "surprise01", "surprise02", "troubled00", "troubled01", "troubled02")
GESTURE_TIMELINES = (
    "差分用_waiting_loop", "差分用_waiting_loop2", "差分用_waiting_loop3", "右向き会話",
    "左向き会話", "うん", "うんうん", "ok", "いやいや", "いやいや2", "ためいき", "がっかり",
    "疑問", "わくわく", "笑い", "にっこり", "にっこり2", "びっくり", "びっくり2", "右向き",
    "左向き", "仰ぎ", "うつむき", "ぷんぷん", "ひく", "悩み", "ぶりっこ", "はじらい",
    "はじらい2", "わなわな", "戸惑い", "ごきげん")
OUTFIT_COLUMNS = ("base", "SP1", "swimsuit", "pajama", "wedding", "SP2")


class PSBError(Exception):
    pass


def _xorshift_bytes(key: int):
    x, y, z, w = (*_XS_SEED, key & _M)
    while True:
        t = (x ^ (x << 11)) & _M
        x, y, z = y, z, w
        w = (w ^ (w >> 19) ^ t ^ (t >> 8)) & _M
        for i in range(4):
            yield (w >> (8 * i)) & 0xFF


def _xor_header(raw: bytes, key: int) -> bytes:
    g = _xorshift_bytes(key)
    return bytes(b ^ next(g) for b in raw)


def header_checksum(fields) -> int:
    """adler32 of the header u32s other than the checksum itself (verified, all files)."""
    b = struct.pack("<12I", *fields)
    return zlib.adler32(b[0x24:0x30], zlib.adler32(b[:0x20]))


def repair_text(s: str) -> str:
    """Undo the .psbData double encoding for display; returns `s` unchanged if it is not
    double-encoded (plain ASCII, or the clean UTF-8 of the .emtbytes)."""
    if s.isascii():
        return s
    try:
        raw = bytes(ord(c) if ord(c) < 256 else c.encode("cp1252")[0] for c in s)
        return raw.decode("utf-8")
    except (UnicodeError, ValueError):
        return s


def _dec(b: bytes) -> str:
    return b.decode("utf-8", "surrogateescape")


class Res:
    """A resource reference inside the tree (chunk or extra chunk)."""
    __slots__ = ("index", "extra")

    def __init__(self, index, extra=False):
        self.index, self.extra = index, extra

    def __repr__(self):
        return f"<{'xres' if self.extra else 'res'} {self.index}>"


class PSB:
    def __init__(self, data: bytes, key: int = HEADER_KEY):
        if data[:4] != MAGIC:
            raise PSBError(f"not a PSB (magic={data[:4]!r})")
        self.data = data
        self.version, self.encrypted = struct.unpack_from("<HH", data, 4)
        if self.version < 3:
            raise PSBError(f"PSB version {self.version} not supported (RF4S ships v4)")
        raw = data[8:0x38]
        if self.encrypted:
            raw = _xor_header(raw, key)
        self.h = dict(zip(HEADER_FIELDS, struct.unpack("<12I", raw)))
        vals = list(self.h.values())
        self.checksum_ok = header_checksum(vals) == self.h["checksum"]
        if not self.checksum_ok:
            raise PSBError("header checksum mismatch (wrong key, or corrupt header)")
        self.names = [_dec(n) for n in self._load_names()]
        so, _ = self._arr(self.h["off_strings"])
        base = self.h["off_strings_data"]
        self.strings = [_dec(self._cstr(base + o)) for o in so]
        self.chunk_offsets, _ = self._arr(self.h["off_chunk_offsets"])
        self.chunk_lengths, _ = self._arr(self.h["off_chunk_lengths"])
        self.extra_offsets, _ = self._arr(self.h["off_extra_offsets"])
        self.extra_lengths, _ = self._arr(self.h["off_extra_lengths"])
        self.root = self.value(self.h["off_root"])

    # ---- low level -------------------------------------------------------
    def _cstr(self, o):
        return self.data[o:self.data.index(b"\0", o)]

    def _uint(self, o, n):
        return int.from_bytes(self.data[o:o + n], "little")

    def _arr(self, o):
        d = self.data
        t = d[o]
        if not 0xD <= t <= 0x14:
            raise PSBError(f"expected packed array at 0x{o:X}, got type 0x{t:X}")
        n = t - 0xC
        cnt = self._uint(o + 1, n)
        o += 1 + n
        e = d[o] - 0xC
        o += 1
        return [self._uint(o + e * i, e) for i in range(cnt)], o + e * cnt

    def _load_names(self):
        cs, o = self._arr(self.h["off_names"])
        tree, o = self._arr(o)
        leaves, _ = self._arr(o)
        out = []
        for idx in leaves:
            chars = []
            ch = tree[idx]
            while ch:
                code = tree[ch]
                chars.append(ch - cs[code])
                ch = code
            out.append(bytes(reversed(chars)))
        return out

    def value(self, o):
        d = self.data
        t = d[o]
        if t == 1:
            return None
        if t in (2, 3):
            return t == 3
        if t == 4:
            return 0
        if 5 <= t <= 0xC:
            return int.from_bytes(d[o + 1:o + t - 3], "little", signed=True)
        if 0xD <= t <= 0x14:
            return self._arr(o)[0]
        if 0x15 <= t <= 0x18:
            return self.strings[self._uint(o + 1, t - 0x14)]
        if 0x19 <= t <= 0x1C:
            return Res(self._uint(o + 1, t - 0x18))
        if t == 0x1D:
            return 0.0
        if t == 0x1E:
            return _f32(struct.unpack_from("<f", d, o + 1)[0])
        if t == 0x1F:
            return struct.unpack_from("<d", d, o + 1)[0]
        if t == 0x20:
            offs, b = self._arr(o + 1)
            return [self.value(b + x) for x in offs]
        if t == 0x21:
            ns, p = self._arr(o + 1)
            offs, b = self._arr(p)
            return {self.names[n]: self.value(b + x) for n, x in zip(ns, offs)}
        if 0x22 <= t <= 0x25:
            return Res(self._uint(o + 1, t - 0x21), extra=True)
        raise PSBError(f"unknown PSB value type 0x{t:X} at 0x{o:X}")

    # ---- resources -------------------------------------------------------
    def chunk_span(self, res: Res):
        if res.extra:
            return (self.h["off_extra_data"] + self.extra_offsets[res.index],
                    self.extra_lengths[res.index])
        return self.h["off_chunk_data"] + self.chunk_offsets[res.index], self.chunk_lengths[res.index]

    def chunk(self, res: Res) -> bytes:
        o, n = self.chunk_span(res)
        return self.data[o:o + n]

    # ---- textures --------------------------------------------------------
    def textures(self):
        """[{source, type, width, height, res, offset, length, icons}] for every atlas."""
        out = []
        src = self.root.get("source") if isinstance(self.root, dict) else None
        for sname, s in (src or {}).items():
            t = s.get("texture") if isinstance(s, dict) else None
            if not isinstance(t, dict) or not isinstance(t.get("pixel"), Res):
                continue
            off, ln = self.chunk_span(t["pixel"])
            out.append({"source": sname, "type": t.get("type"), "width": t.get("width"),
                        "height": t.get("height"), "res": t["pixel"], "offset": off,
                        "length": ln, "icons": s.get("icon") or {}})
        return out

    def timelines(self):
        md = self.root.get("metadata") or {}
        return [tl.get("label") for tl in md.get("timelineControl") or [] if isinstance(tl, dict)]


def _f32(v):
    """Shortest decimal that round-trips the float32 (keeps JSON readable)."""
    packed = struct.pack("<f", v)
    for p in range(6, 10):
        c = float(f"{v:.{p}g}")
        if struct.pack("<f", c) == packed:
            return c
    return v


def load(path) -> PSB:
    return PSB(pathlib.Path(path).read_bytes())


# ---- pixel formats ------------------------------------------------------------
def _bytes_per_texture(tex):
    w, h, fmt = tex["width"], tex["height"], tex["type"]
    if fmt == "RGBA8":
        return w * h * 4
    if fmt == "ASTC_8BPP":
        return ((w + 3) // 4) * ((h + 3) // 4) * 16
    return None


def decode_texture(psb: PSB, tex):
    """Atlas -> PIL RGBA image.  RGBA8 (R,G,B,A) natively; ASTC_8BPP (ASTC 4x4) needs
    the optional texture2ddecoder package."""
    from PIL import Image
    raw = psb.chunk(tex["res"])
    w, h, fmt = tex["width"], tex["height"], tex["type"]
    if _bytes_per_texture(tex) != len(raw):
        raise PSBError(f"{fmt} {w}x{h}: chunk is {len(raw)} bytes, expected {_bytes_per_texture(tex)}")
    if fmt == "RGBA8":
        return Image.frombytes("RGBA", (w, h), raw)
    if fmt == "ASTC_8BPP":
        try:
            import texture2ddecoder
        except ImportError as e:
            raise PSBError("ASTC decode needs: pip install texture2ddecoder") from e
        bgra = texture2ddecoder.decode_astc(raw, w, h, 4, 4)
        return Image.frombytes("RGBA", (w, h), bgra, "raw", "BGRA")
    raise PSBError(f"unsupported E-mote texture type {fmt!r}")


def icon_images(psb: PSB, tex, atlas=None):
    """{icon name: cropped PIL image} for the atlas' named parts (source/<src>/icon)."""
    atlas = atlas or decode_texture(psb, tex)
    out = {}
    for name, ic in tex["icons"].items():
        if not isinstance(ic, dict):
            continue
        x, y = int(round(ic.get("left", 0))), int(round(ic.get("top", 0)))
        out[name] = atlas.crop((x, y, x + int(ic.get("width", 0)), y + int(ic.get("height", 0))))
    return out


def replace_texture(psb: PSB, tex, image) -> bytes:
    """New file bytes with the atlas pixels replaced by `image` (same size).  Only the
    chunk bytes change -- header, tables, tree and checksum stay byte-identical."""
    if tex["type"] != "RGBA8":
        raise PSBError(f"replace needs an RGBA8 atlas (the .psbData); this one is {tex['type']} "
                       "-- the game does not load .emtbytes, edit the matching .psbData")
    im = image.convert("RGBA")
    if im.size != (tex["width"], tex["height"]):
        raise PSBError(f"image is {im.size[0]}x{im.size[1]}, atlas is "
                       f"{tex['width']}x{tex['height']} (must match: the part coordinates "
                       "in source/*/icon are absolute pixels)")
    raw = im.tobytes()
    off, ln = tex["offset"], tex["length"]
    assert len(raw) == ln
    d = psb.data
    return d[:off] + raw + d[off + ln:]


# ---- JSON view -----------------------------------------------------------------
_ROOT = object()


def to_jsonable(psb: PSB, v=_ROOT, repair=True):
    """Tree -> JSON-able data.  Resources become {"$res": i, "size": n} ({"$xres": ...}
    for extra chunks).  With repair=True strings/keys are shown un-double-encoded."""
    v = psb.root if v is _ROOT else v
    fx = repair_text if repair else (lambda s: s)
    if isinstance(v, dict):
        return {fx(k): to_jsonable(psb, x, repair) for k, x in v.items()}
    if isinstance(v, list):
        return [to_jsonable(psb, x, repair) for x in v]
    if isinstance(v, Res):
        return {("$xres" if v.extra else "$res"): v.index, "size": psb.chunk_span(v)[1]}
    if isinstance(v, str):
        return fx(v)
    return v


def summary(psb: PSB, name: str = "") -> str:
    h = psb.h
    lines = [f"E-mote PSB v{psb.version}{'  (header XOR-encrypted, key 0x%08X)' % HEADER_KEY if psb.encrypted else ''}"
             + (f"  {name}" if name else ""),
             f"  size        : {len(psb.data):,} bytes   checksum ok: {psb.checksum_ok}",
             f"  names/strings/chunks/extra: {len(psb.names)} / {len(psb.strings)} / "
             f"{len(psb.chunk_offsets)} / {len(psb.extra_offsets)}",
             "  header      : " + ", ".join(f"{k}=0x{v:X}" for k, v in h.items() if k != "checksum")]
    r = psb.root if isinstance(psb.root, dict) else {}
    md = r.get("metadata") or {}
    ss = r.get("screenSize") or {}
    lines.append(f"  spec={r.get('spec')!r} version={r.get('version')} screen={ss.get('width')}x{ss.get('height')}"
                 f" objects={len(r.get('object') or {})}")
    for t in psb.textures():
        lines.append(f"  texture     : source '{t['source']}' {t['type']} {t['width']}x{t['height']}"
                     f" @0x{t['offset']:X} ({t['length']:,} B), {len(t['icons'])} parts")
    tls = [repair_text(x) for x in psb.timelines() if isinstance(x, str)]
    if tls:
        played = [f for f in FACE_TIMELINES if f in tls]
        lines.append(f"  timelines   : {len(tls)}; game face rows present: {len(played)}/{len(FACE_TIMELINES)}"
                     f"; gestures present: {sum(g in tls for g in GESTURE_TIMELINES)}/{len(GESTURE_TIMELINES)}")
        lines.append("  face frames : " + ", ".join(
            f"{i}={FACE_TIMELINES[i]}({FACE_TIMELINES_EN[i]}){'' if FACE_TIMELINES[i] in tls else ' MISSING'}"
            for i in range(6)))
    vl = md.get("variableList") or []
    if vl:
        labels = []
        for x in vl:
            if isinstance(x, dict) and isinstance(x.get("label"), str) and repair_text(x["label"]) not in labels:
                labels.append(repair_text(x["label"]))
        lines.append(f"  variables   : {', '.join(labels)}")
    return "\n".join(lines)


def dump_json(psb: PSB, out_path, repair=True, resources_dir=None):
    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(to_jsonable(psb, repair=repair), ensure_ascii=False, indent=1),
                        encoding="utf-8")
    written = [out_path]
    if resources_dir:
        rd = pathlib.Path(resources_dir)
        rd.mkdir(parents=True, exist_ok=True)
        for i in range(len(psb.chunk_offsets)):
            p = rd / f"res_{i:04d}.bin"
            p.write_bytes(psb.chunk(Res(i)))
            written.append(p)
        for i in range(len(psb.extra_offsets)):
            p = rd / f"xres_{i:04d}.bin"
            p.write_bytes(psb.chunk(Res(i, True)))
            written.append(p)
    return written
