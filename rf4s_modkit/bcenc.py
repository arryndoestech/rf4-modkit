r"""
bcenc.py -- BC1 / BC3 / BC7 block-compression ENCODERS (pure Python, numpy-accelerated).

Why: the engine uploads the block formats untouched (MCTexture_GLUpload, RF4S.exe+0x2A34F0:
PIXL/BRTI code 0x1A01 -> glCompressedTexImage2D(GL_COMPRESSED_RGBA_S3TC_DXT1_EXT 33777),
0x1C01 -> DXT5 33779, 0x2001 -> GL_COMPRESSED_RGBA_BPTC_UNORM 36492; level 0 only, no
mip levels, raster-order blocks, no swizzle -- see texture.py). Re-encoding a replaced
image in the template's own block format keeps the payload at its ORIGINAL size, so a
.texture stays eligible for `rf4mod bundle patch` (same-or-smaller in-place install) and
a BNTX texture embedded in a .model can be swapped in place without touching the container.

Block layouts (all little-endian, bit 0 = LSB of byte 0, verified bit-for-bit against
texture2ddecoder, the decoder the toolkit uses; its palette arithmetic is the D3D reference
one: 565 expands as (v<<3)|(v>>2) / (v<<2)|(v>>4), the 1/3-2/3 and 1/7..6/7 lerps use
truncating integer division):

  BC1  8 B: u16 c0 (RGB565), u16 c1, u32 indices (2 bits/pixel, pixel 0 lowest).
       c0 > c1: palette c0, c1, (2c0+c1)/3, (c0+2c1)/3.  c0 <= c1: c0, c1, (c0+c1)/2,
       transparent black.  This encoder uses the 3-colour mode only when a block holds a
       pixel with alpha < 128 (1-bit alpha "only when needed"); otherwise 4-colour mode,
       and it never emits index 3 with c0 == c1 (decoders disagree on that corner).
       (texture2ddecoder returns OPAQUE black for the transparent index; the GPU format
       the engine uploads, DXT1 33777, returns alpha 0 -- decode_bc1_block below does too.)
  BC3 16 B: u8 a0, u8 a1, 48-bit alpha indices (3 bits/pixel), then a BC1 colour block.
       a0 > a1: 8-level palette a0, a1, (6a0+a1)/7 .. (a0+6a1)/7;  a0 <= a1: 6-level
       a0, a1, (4a0+a1)/5 .. (a0+4a1)/5, 0, 255.  The colour block is always written with
       c0 > c1 (or c0 == c1 with index 0 only) because texture2ddecoder applies the BC1
       3-colour rule inside BC3 while GPUs do not.
  BC7 16 B, mode 6: mode bits 0000001 (bit 6 set), R0 R1 G0 G1 B0 B1 A0 A1 at 7 bits
       each (bits 7..62), P0 (bit 63), P1 (bit 64), then 4-bit indices with the anchor
       pixel 0 holding 3 bits (bits 65..67), pixels 1..15 at 64+4i.
       Endpoint = (e7 << 1) | p; colour = ((64-w)*e0 + w*e1 + 32) >> 6 with the weights
       0,4,9,13,17,21,26,30,34,38,43,47,51,55,60,64.  If pixel 0 needs an index >= 8 the
       endpoints (and p-bits) are swapped and every index becomes 15-i (the weight table
       is symmetric, so the palette is unchanged).
  BC7 mode 5: mode bits 000001 (bit 5), rotation 2 bits (0), R0 R1 G0 G1 B0 B1 at 7 bits
       (expanded (e7<<1)|(e7>>6)), A0 A1 at 8 bits, 2-bit colour indices (anchor pixel 0 =
       1 bit) then 2-bit alpha indices (anchor 1 bit); weights 0,21,43,64.

Encoder: every block is fitted in BOTH mode 6 (one 4-D line through the RGBA cloud,
16 levels) and mode 5 (an RGB line with 4 levels plus its own 4-level alpha ramp) and the
lower squared error wins -- mode 6 carries gradients, mode 5 carries alpha edges (a
sprite outline is a colour ramp AND an alpha step, which one line cannot follow).  Flat
blocks always take mode 5: mode 6 cannot represent a flat colour that has both a 0 and a
255 channel (opaque black, pure red, ...) because the p-bit forces one parity on all four
channels of an endpoint, and 0 needs an even endpoint while 255 needs an odd one; mode 5
has no p-bits, with weight 21 every value 0..255 equals ((43*e0 + 21*e1 + 32) >> 6) for
some pair of the 128 expanded 7-bit values, and its alpha endpoints are 8-bit, so every
flat RGBA block round-trips EXACTLY through the reference decoder.

Fitting per 4x4 block: principal axis of the pixel cloud (power iteration on the
covariance), endpoints at the extreme projections, nearest-palette index assignment by
projection, then two rounds of least-squares endpoint refit from the assigned indices;
BC7 mode 6 tries all four p-bit combinations each round.  numpy (when installed) runs the
whole image as one batch (a 512x512 BC7 tile in about a second, BC3/BC1 well under);
without numpy the same algorithm runs block by block in pure Python (tens of seconds for
512x512, dependency-free).  Images whose width/height are not multiples of 4 are
edge-replicated to the block grid, as the loaders expect ceil(w/4)*ceil(h/4) blocks.

Reference decoders for the three formats (modes 5 and 6 only for BC7 -- the modes this
encoder emits) are included so tests can prove the packing bit-exact against
texture2ddecoder and so the module is usable without it.
"""
from __future__ import annotations

import struct

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:      # pragma: no cover - exercised on machines without numpy
    np = None
    HAS_NUMPY = False

BC7_WEIGHTS4 = (0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64)
BC7_WEIGHTS2 = (0, 21, 43, 64)
_G7 = tuple(((q << 1) | (q >> 6)) for q in range(128))   # mode-5 7-bit endpoint expansion
BLOCK_BYTES = {"bc1": 8, "bc3": 16, "bc7": 16}


class BCEncodeError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Block grid helpers
# --------------------------------------------------------------------------- #
def block_grid(w: int, h: int) -> tuple:
    """(blocks across, blocks down) for a w x h image."""
    return (w + 3) // 4, (h + 3) // 4


def _blocks_py(rgba: bytes, w: int, h: int) -> list:
    """List of blocks; each block = 16 (r, g, b, a) tuples in raster order inside the
    block (pixel i = column i % 4, row i // 4). Edge pixels are replicated to pad."""
    if len(rgba) < w * h * 4:
        raise BCEncodeError(f"rgba buffer too small for {w}x{h}: {len(rgba)} < {w * h * 4}")
    bw, bh = block_grid(w, h)
    out = []
    for by in range(bh):
        for bx in range(bw):
            blk = []
            for py in range(4):
                y = min(by * 4 + py, h - 1)
                for px in range(4):
                    x = min(bx * 4 + px, w - 1)
                    o = (y * w + x) * 4
                    blk.append((rgba[o], rgba[o + 1], rgba[o + 2], rgba[o + 3]))
            out.append(blk)
    return out


def _blocks_np(rgba: bytes, w: int, h: int):
    """(N, 16, 4) float64 array of blocks (same order/padding as _blocks_py)."""
    if len(rgba) < w * h * 4:
        raise BCEncodeError(f"rgba buffer too small for {w}x{h}: {len(rgba)} < {w * h * 4}")
    a = np.frombuffer(rgba, dtype=np.uint8)[:w * h * 4].reshape(h, w, 4)
    bw, bh = block_grid(w, h)
    if (bw * 4, bh * 4) != (w, h):
        a = np.pad(a, ((0, bh * 4 - h), (0, bw * 4 - w), (0, 0)), mode="edge")
    return a.reshape(bh, 4, bw, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bw * bh, 16, 4).astype(np.float64)


# --------------------------------------------------------------------------- #
# Bit packing (Python ints; used by the pure path and the decoders)
# --------------------------------------------------------------------------- #
def _pack_bc7_mode6(q0, q1, p0, p1, idx) -> bytes:
    bits = 1 << 6
    pos = 7
    for ch in range(4):
        bits |= (q0[ch] & 0x7F) << pos
        pos += 7
        bits |= (q1[ch] & 0x7F) << pos
        pos += 7
    bits |= (p0 & 1) << 63
    bits |= (p1 & 1) << 64
    bits |= (idx[0] & 7) << 65
    for i in range(1, 16):
        bits |= (idx[i] & 15) << (64 + 4 * i)
    return bits.to_bytes(16, "little")


def _pack_bc7_mode5(e0, e1, a0, a1, cidx, aidx) -> bytes:
    bits = 1 << 5                      # mode 5, rotation 0 (bits 6-7 clear)
    pos = 8
    for ch in range(3):
        bits |= (e0[ch] & 0x7F) << pos
        pos += 7
        bits |= (e1[ch] & 0x7F) << pos
        pos += 7
    bits |= (a0 & 0xFF) << 50
    bits |= (a1 & 0xFF) << 58
    bits |= (cidx[0] & 1) << 66
    for i in range(1, 16):
        bits |= (cidx[i] & 3) << (65 + 2 * i)
    bits |= (aidx[0] & 1) << 97
    for i in range(1, 16):
        bits |= (aidx[i] & 3) << (96 + 2 * i)
    return bits.to_bytes(16, "little")


def _pack_bc1(c0: int, c1: int, idx) -> bytes:
    bits = 0
    for i in range(16):
        bits |= (idx[i] & 3) << (2 * i)
    return struct.pack("<HHI", c0, c1, bits)


def _pack_bc3_alpha(a0: int, a1: int, idx) -> bytes:
    bits = 0
    for i in range(16):
        bits |= (idx[i] & 7) << (3 * i)
    return struct.pack("<BB", a0, a1) + bits.to_bytes(6, "little")


# --------------------------------------------------------------------------- #
# Palette arithmetic (shared by encoders and reference decoders)
# --------------------------------------------------------------------------- #
def _expand565(c: int) -> tuple:
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _quant565(r: float, g: float, b: float) -> int:
    r5 = min(31, max(0, int(r * 31 / 255 + 0.5)))
    g6 = min(63, max(0, int(g * 63 / 255 + 0.5)))
    b5 = min(31, max(0, int(b * 31 / 255 + 0.5)))
    return (r5 << 11) | (g6 << 5) | b5


def _quant7(v: float) -> int:
    """7-bit mode-5 endpoint whose expansion is nearest to v."""
    qa = min(127, max(0, int(v // 2)))
    qb = min(127, qa + 1)
    return qb if abs(_G7[qb] - v) < abs(_G7[qa] - v) else qa


def _bc1_palette(c0: int, c1: int) -> list:
    """[(r,g,b,a) x4] as the D3D reference (and the GPU) decode them."""
    p0, p1 = _expand565(c0), _expand565(c1)
    if c0 > c1:
        p2 = tuple((2 * x + y) // 3 for x, y in zip(p0, p1))
        p3 = tuple((x + 2 * y) // 3 for x, y in zip(p0, p1))
        return [p0 + (255,), p1 + (255,), p2 + (255,), p3 + (255,)]
    p2 = tuple((x + y) // 2 for x, y in zip(p0, p1))
    return [p0 + (255,), p1 + (255,), p2 + (255,), (0, 0, 0, 0)]


def _bc3_alpha_palette(a0: int, a1: int) -> list:
    if a0 > a1:
        return [a0, a1] + [((6 - k) * a0 + (k + 1) * a1) // 7 for k in range(6)]
    return [a0, a1] + [((4 - k) * a0 + (k + 1) * a1) // 5 for k in range(4)] + [0, 255]


def _bc7_lerp(e0: int, e1: int, w: int) -> int:
    return ((64 - w) * e0 + w * e1 + 32) >> 6


_M5_PAIRS = None


def _mode5_pairs() -> dict:
    """value 0..255 -> (q0, q1) 7-bit endpoints with ((43*G7[q0] + 21*G7[q1] + 32) >> 6)
    == value (weight 21 = colour index 1). Every value is reachable (checked in selftest)."""
    global _M5_PAIRS
    if _M5_PAIRS is None:
        tbl = {}
        for q0, e0 in enumerate(_G7):
            for q1, e1 in enumerate(_G7):
                v = (43 * e0 + 21 * e1 + 32) >> 6
                if v not in tbl:
                    tbl[v] = (q0, q1)
        _M5_PAIRS = tbl
    return _M5_PAIRS


def bc7_flat_block(r: int, g: int, b: int, a: int) -> bytes:
    """A BC7 (mode 5) block whose 16 pixels decode EXACTLY to (r, g, b, a)."""
    tbl = _mode5_pairs()
    e0 = [tbl[c][0] for c in (r, g, b)]
    e1 = [tbl[c][1] for c in (r, g, b)]
    return _pack_bc7_mode5(e0, e1, a, a, [1] * 16, [0] * 16)


# --------------------------------------------------------------------------- #
# Pure-Python per-block encoders
# --------------------------------------------------------------------------- #
def _principal_axis(pts, dims):
    """(mean, unit axis) of a list of equal-length tuples via power iteration."""
    n = len(pts)
    mean = [sum(p[k] for p in pts) / n for k in range(dims)]
    cov = [[0.0] * dims for _ in range(dims)]
    for p in pts:
        d = [p[k] - mean[k] for k in range(dims)]
        for i in range(dims):
            di = d[i]
            if di:
                row = cov[i]
                for j in range(dims):
                    row[j] += di * d[j]
    v = [1.0] * dims
    for _ in range(8):
        nv = [sum(cov[i][j] * v[j] for j in range(dims)) for i in range(dims)]
        nrm = sum(x * x for x in nv) ** 0.5
        if nrm < 1e-9:
            break
        v = [x / nrm for x in nv]
    return mean, v


def _axis_endpoints(pts, dims):
    mean, axis = _principal_axis(pts, dims)
    ts = [sum((p[k] - mean[k]) * axis[k] for k in range(dims)) for p in pts]
    tmin, tmax = min(ts), max(ts)
    e0 = [min(255.0, max(0.0, mean[k] + tmin * axis[k])) for k in range(dims)]
    e1 = [min(255.0, max(0.0, mean[k] + tmax * axis[k])) for k in range(dims)]
    return e0, e1


def _nearest_on_line(px, r0, r1, weights, dims):
    """Index (into `weights`) of the palette entry nearest each pixel, by projection on
    the r0->r1 segment; returns (indices, squared error)."""
    d = [r1[k] - r0[k] for k in range(dims)]
    dd = sum(x * x for x in d)
    pal = [tuple(_bc7_lerp(r0[k], r1[k], w) for k in range(dims)) for w in weights]
    last = len(weights) - 1
    mids = [(weights[i] + weights[i + 1]) / 2.0 for i in range(last)]
    idx, err = [], 0
    for p in px:
        k = 0
        if dd:
            t = sum((p[j] - r0[j]) * d[j] for j in range(dims)) / dd * 64.0
            while k < last and mids[k] < t:
                k += 1
        q = pal[k]
        idx.append(k)
        err += sum((p[j] - q[j]) ** 2 for j in range(dims))
    return idx, err


def _ls_refit(px, weights, dims, e0, e1):
    """Least-squares endpoints for fixed per-pixel (alpha, beta) lerp weights; falls back
    to (e0, e1) when the system is singular (all pixels on one index)."""
    a11 = a12 = a22 = 0.0
    r1 = [0.0] * dims
    r2 = [0.0] * dims
    for p, (a, b) in zip(px, weights):
        a11 += a * a
        a12 += a * b
        a22 += b * b
        for k in range(dims):
            r1[k] += a * p[k]
            r2[k] += b * p[k]
    det = a11 * a22 - a12 * a12
    if det <= 1e-8:
        return e0, e1
    n0 = [min(255.0, max(0.0, (a22 * r1[k] - a12 * r2[k]) / det)) for k in range(dims)]
    n1 = [min(255.0, max(0.0, (a11 * r2[k] - a12 * r1[k]) / det)) for k in range(dims)]
    return n0, n1


def _bc7_mode6_py(px):
    """(err, packed block) for the best mode-6 fit of 16 (r,g,b,a) pixels."""
    e0, e1 = _axis_endpoints(px, 4)
    best = None
    for it in range(3):
        for p0 in (0, 1):
            q0 = [min(127, max(0, int((e0[k] - p0) / 2 + 0.5))) for k in range(4)]
            r0 = tuple(2 * q + p0 for q in q0)
            for p1 in (0, 1):
                q1 = [min(127, max(0, int((e1[k] - p1) / 2 + 0.5))) for k in range(4)]
                r1 = tuple(2 * q + p1 for q in q1)
                idx, err = _nearest_on_line(px, r0, r1, BC7_WEIGHTS4, 4)
                if best is None or err < best[0]:
                    best = (err, q0, q1, p0, p1, idx)
        if it < 2:
            wts = [((64 - BC7_WEIGHTS4[i]) / 64.0, BC7_WEIGHTS4[i] / 64.0) for i in best[5]]
            e0, e1 = _ls_refit(px, wts, 4, e0, e1)
    err, q0, q1, p0, p1, idx = best
    if idx[0] >= 8:
        q0, q1, p0, p1 = q1, q0, p1, p0
        idx = [15 - i for i in idx]
    return err, _pack_bc7_mode6(q0, q1, p0, p1, idx)


def _bc7_mode5_py(px):
    """(err, packed block) for the best mode-5 fit (RGB line + separate alpha ramp)."""
    rgb = [p[:3] for p in px]
    al = [(p[3],) for p in px]
    e0, e1 = _axis_endpoints(rgb, 3)
    bestc = None
    for it in range(3):
        q0 = [_quant7(v) for v in e0]
        q1 = [_quant7(v) for v in e1]
        r0 = tuple(_G7[q] for q in q0)
        r1 = tuple(_G7[q] for q in q1)
        idx, err = _nearest_on_line(rgb, r0, r1, BC7_WEIGHTS2, 3)
        if bestc is None or err < bestc[0]:
            bestc = (err, q0, q1, idx)
        if it < 2:
            wts = [((64 - BC7_WEIGHTS2[i]) / 64.0, BC7_WEIGHTS2[i] / 64.0) for i in idx]
            e0, e1 = _ls_refit(rgb, wts, 3, e0, e1)
    amin, amax = min(a[0] for a in al), max(a[0] for a in al)
    besta = None
    a0, a1 = float(amin), float(amax)
    for it in range(2):
        ia0, ia1 = int(a0 + 0.5), int(a1 + 0.5)
        idx, err = _nearest_on_line(al, (ia0,), (ia1,), BC7_WEIGHTS2, 1)
        if besta is None or err < besta[0]:
            besta = (err, ia0, ia1, idx)
        if it == 0:
            wts = [((64 - BC7_WEIGHTS2[i]) / 64.0, BC7_WEIGHTS2[i] / 64.0) for i in idx]
            (a0,), (a1,) = _ls_refit(al, wts, 1, [a0], [a1])
    errc, q0, q1, cidx = bestc
    erra, ia0, ia1, aidx = besta
    if cidx[0] >= 2:
        q0, q1 = q1, q0
        cidx = [3 - i for i in cidx]
    if aidx[0] >= 2:
        ia0, ia1 = ia1, ia0
        aidx = [3 - i for i in aidx]
    return errc + erra, _pack_bc7_mode5(q0, q1, ia0, ia1, cidx, aidx)


def _bc7_block_py(px) -> bytes:
    first = px[0]
    if all(p == first for p in px):
        return bc7_flat_block(*first)
    e6, b6 = _bc7_mode6_py(px)
    if e6 == 0:
        return b6
    e5, b5 = _bc7_mode5_py(px)
    return b5 if e5 < e6 else b6


def _bc1_colour_py(px, mask, three: bool):
    """(c0, c1, idx) for one block. px: 16 (r,g,b,a); mask: pixels that count; three:
    3-colour + transparent mode (masked-out pixels get index 3)."""
    pts = [p[:3] for p, m in zip(px, mask) if m]
    if not pts:
        return 0, 0, [3] * 16
    e0, e1 = _axis_endpoints(pts, 3)
    best = None
    for it in range(3):
        c0, c1 = _quant565(*e0), _quant565(*e1)
        if (not three and c0 < c1) or (three and c0 > c1):
            c0, c1 = c1, c0
        pal = _bc1_palette(c0, c1)
        ncand = 3 if three else (1 if c0 == c1 else 4)
        idx, err, wts = [], 0.0, []
        for p, m in zip(px, mask):
            if not m:
                idx.append(3)
                wts.append((0.0, 0.0))
                continue
            bi, be = 0, None
            for c in range(ncand):
                q = pal[c]
                e = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2
                if be is None or e < be:
                    bi, be = c, e
            idx.append(bi)
            err += be
            wts.append(((1.0, 0.0), (0.0, 1.0), ((0.5, 0.5) if three else (2 / 3, 1 / 3)), (1 / 3, 2 / 3))[bi])
        if best is None or err < best[0]:
            best = (err, c0, c1, idx)
        if it < 2:
            e0, e1 = _ls_refit([p[:3] for p in px], wts, 3, e0, e1)
    return best[1], best[2], best[3]


def _bc3_alpha_py(alphas):
    amin, amax = min(alphas), max(alphas)
    best = None
    for a0, a1 in _bc3_alpha_candidates(alphas, amin, amax):
        pal = _bc3_alpha_palette(a0, a1)
        idx, err = [], 0
        for a in alphas:
            bi, be = 0, None
            for c, q in enumerate(pal):
                e = (a - q) ** 2
                if be is None or e < be:
                    bi, be = c, e
            idx.append(bi)
            err += be
        if best is None or err < best[0]:
            best = (err, a0, a1, idx)
        if err == 0:
            break
    return best[1], best[2], best[3]


def _bc3_alpha_candidates(alphas, amin, amax):
    """(a0, a1) endpoint pairs to try: the 6-level mode on the values that are not 0/255
    (they are free in that mode), the 8-level mode on the full range, and an 8-level
    least-squares refit of the range."""
    inner = [a for a in alphas if 0 < a < 255]
    yield (min(inner), max(inner)) if inner else (0, 0)          # a0 <= a1: 6-level mode
    if amax > amin:
        yield amax, amin                                          # a0 > a1: 8-level mode
        pal = _bc3_alpha_palette(amax, amin)
        wts = []
        for a in alphas:
            k = min(range(8), key=lambda c: abs(a - pal[c]))
            f = (1.0, 0.0) if k == 0 else (0.0, 1.0) if k == 1 else ((7 - k) / 7.0, (k - 1) / 7.0)
            wts.append(f)
        n0, n1 = _ls_refit([(a,) for a in alphas], wts, 1, [float(amax)], [float(amin)])
        a0, a1 = int(n0[0] + 0.5), int(n1[0] + 0.5)
        if a0 > a1:
            yield a0, a1


def _bc1_block_py(px) -> bytes:
    three = any(p[3] < 128 for p in px)
    mask = [p[3] >= 128 for p in px] if three else [True] * 16
    c0, c1, idx = _bc1_colour_py(px, mask, three)
    return _pack_bc1(c0, c1, idx)


def _bc3_block_py(px) -> bytes:
    a0, a1, aidx = _bc3_alpha_py([p[3] for p in px])
    c0, c1, cidx = _bc1_colour_py(px, [True] * 16, False)
    return _pack_bc3_alpha(a0, a1, aidx) + _pack_bc1(c0, c1, cidx)


# --------------------------------------------------------------------------- #
# numpy batch encoders
# --------------------------------------------------------------------------- #
def _axis_np(c):
    """Unit principal axis of centred points c (N, P, D) by power iteration."""
    cov = np.einsum("npi,npj->nij", c, c)
    v = np.ones((c.shape[0], c.shape[2]))
    for _ in range(8):
        v = np.einsum("nij,nj->ni", cov, v)
        nrm = np.sqrt((v * v).sum(1, keepdims=True))
        v = np.where(nrm > 1e-12, v / np.where(nrm > 1e-12, nrm, 1.0), 1.0)
    return v


def _axis_endpoints_np(pts, mask=None):
    """Endpoints (N,D) at the extreme projections of pts (N,P,D) on the principal axis;
    mask (N,P) limits the pixels that count."""
    if mask is None:
        mean = pts.mean(1)
        c = pts - mean[:, None, :]
    else:
        cnt = np.maximum(mask.sum(1), 1)
        mean = (pts * mask[:, :, None]).sum(1) / cnt[:, None]
        c = (pts - mean[:, None, :]) * mask[:, :, None]
    v = _axis_np(c)
    t = np.einsum("npk,nk->np", c, v)
    if mask is not None:
        tmin = np.where(mask, t, np.inf).min(1)
        tmax = np.where(mask, t, -np.inf).max(1)
        tmin = np.where(np.isfinite(tmin), tmin, 0.0)
        tmax = np.where(np.isfinite(tmax), tmax, 0.0)
    else:
        tmin, tmax = t.min(1), t.max(1)
    e0 = np.clip(mean + tmin[:, None] * v, 0, 255)
    e1 = np.clip(mean + tmax[:, None] * v, 0, 255)
    return e0, e1


def _refit_np(px, a, b, e0, e1):
    """Batched least-squares endpoints for lerp weights a (toward e0) and b (toward e1),
    both (N, P); keeps e0/e1 where the normal matrix is singular."""
    a11, a12, a22 = (a * a).sum(1), (a * b).sum(1), (b * b).sum(1)
    r1 = np.einsum("np,npk->nk", a, px)
    r2 = np.einsum("np,npk->nk", b, px)
    det = a11 * a22 - a12 * a12
    ok = det > 1e-8
    dets = np.where(ok, det, 1.0)[:, None]
    n0 = np.clip((a22[:, None] * r1 - a12[:, None] * r2) / dets, 0, 255)
    n1 = np.clip((a11[:, None] * r2 - a12[:, None] * r1) / dets, 0, 255)
    return np.where(ok[:, None], n0, e0), np.where(ok[:, None], n1, e1)


def _assign_np(px, r0, r1, W):
    """Nearest palette index per pixel by projection on the r0->r1 segment (palette
    entries lie on it at W/64). px (N,P,D), r0/r1 (N,D) integer-valued, W 1-D weights.
    Returns (idx (N,P), err (N,))."""
    mid = (W[1:] + W[:-1]) / 2.0
    d = r1 - r0
    dd = (d * d).sum(1)
    t = (np.einsum("npk,nk->np", px, d) - (r0 * d).sum(1)[:, None]) / np.where(dd > 0, dd, 1.0)[:, None]
    k = np.searchsorted(mid, np.clip(t * 64.0, 0.0, 64.0))
    k = np.where(dd[:, None] > 0, k, 0)
    wk = W.astype(np.int64)[k]                                                      # (N,P)
    r0i = r0.astype(np.int64)
    r1i = r1.astype(np.int64)
    pal = ((64 - wk)[:, :, None] * r0i[:, None, :] + wk[:, :, None] * r1i[:, None, :] + 32) >> 6
    diff = px - pal
    return k, np.einsum("npk,npk->n", diff, diff)


_W4A = None
_W2A = None


def _weights_np():
    global _W4A, _W2A
    if _W4A is None:
        _W4A = np.array(BC7_WEIGHTS4, dtype=np.float64)
        _W2A = np.array(BC7_WEIGHTS2, dtype=np.float64)
    return _W4A, _W2A


def _bc7_mode6_np(px):
    """Fit mode-6 blocks for px (N,16,4). Returns (q0, q1, p0, p1, idx, err)."""
    N = px.shape[0]
    W4, _ = _weights_np()
    e0, e1 = _axis_endpoints_np(px)
    best_err = np.full(N, np.inf)
    bq0 = np.zeros((N, 4)); bq1 = np.zeros((N, 4))
    bp0 = np.zeros(N, dtype=np.int64); bp1 = np.zeros(N, dtype=np.int64)
    bidx = np.zeros((N, 16), dtype=np.int64)
    for it in range(3):
        for p0 in (0, 1):
            q0 = np.clip(np.floor((e0 - p0) / 2 + 0.5), 0, 127)
            r0 = 2 * q0 + p0
            for p1 in (0, 1):
                q1 = np.clip(np.floor((e1 - p1) / 2 + 0.5), 0, 127)
                r1 = 2 * q1 + p1
                idx, err = _assign_np(px, r0, r1, W4)
                better = err < best_err
                if better.any():
                    best_err = np.where(better, err, best_err)
                    bq0[better] = q0[better]; bq1[better] = q1[better]
                    bp0[better] = p0; bp1[better] = p1
                    bidx[better] = idx[better]
        if it < 2:
            wv = W4[bidx]
            e0, e1 = _refit_np(px, (64 - wv) / 64.0, wv / 64.0, e0, e1)
    swap = bidx[:, 0] >= 8
    q0 = np.where(swap[:, None], bq1, bq0).astype(np.int64)
    q1 = np.where(swap[:, None], bq0, bq1).astype(np.int64)
    p0 = np.where(swap, bp1, bp0)
    p1 = np.where(swap, bp0, bp1)
    idx = np.where(swap[:, None], 15 - bidx, bidx)
    return q0, q1, p0, p1, idx, best_err


def _quant7_np(e):
    G = np.array(_G7, dtype=np.float64)
    qa = np.clip(np.floor(e / 2), 0, 127).astype(np.int64)
    qb = np.minimum(qa + 1, 127)
    q = np.where(np.abs(G[qb] - e) < np.abs(G[qa] - e), qb, qa)
    return q, G[q]


def _bc7_mode5_np(px):
    """Fit mode-5 blocks (rotation 0). Returns (q0, q1, a0, a1, cidx, aidx, err)."""
    N = px.shape[0]
    _, W2 = _weights_np()
    rgb = px[:, :, :3]
    al = px[:, :, 3:4]
    e0, e1 = _axis_endpoints_np(rgb)
    best_err = np.full(N, np.inf)
    bq0 = np.zeros((N, 3), dtype=np.int64); bq1 = np.zeros((N, 3), dtype=np.int64)
    bidx = np.zeros((N, 16), dtype=np.int64)
    for it in range(3):
        q0, r0 = _quant7_np(e0)
        q1, r1 = _quant7_np(e1)
        idx, err = _assign_np(rgb, r0, r1, W2)
        better = err < best_err
        if better.any():
            best_err = np.where(better, err, best_err)
            bq0[better] = q0[better]; bq1[better] = q1[better]; bidx[better] = idx[better]
        if it < 2:
            wv = W2[idx]
            e0, e1 = _refit_np(rgb, (64 - wv) / 64.0, wv / 64.0, e0, e1)
    a0 = al[:, :, 0].min(1)[:, None]
    a1 = al[:, :, 0].max(1)[:, None]
    besta = np.full(N, np.inf)
    ba0 = np.zeros(N, dtype=np.int64); ba1 = np.zeros(N, dtype=np.int64)
    baidx = np.zeros((N, 16), dtype=np.int64)
    for it in range(2):
        ia0, ia1 = np.floor(a0 + 0.5), np.floor(a1 + 0.5)
        aidx, aerr = _assign_np(al, ia0, ia1, W2)
        better = aerr < besta
        if better.any():
            besta = np.where(better, aerr, besta)
            ba0[better] = ia0[better, 0]; ba1[better] = ia1[better, 0]; baidx[better] = aidx[better]
        if it == 0:
            wv = W2[aidx]
            a0, a1 = _refit_np(al, (64 - wv) / 64.0, wv / 64.0, a0, a1)
    swap = bidx[:, 0] >= 2
    q0 = np.where(swap[:, None], bq1, bq0)
    q1 = np.where(swap[:, None], bq0, bq1)
    cidx = np.where(swap[:, None], 3 - bidx, bidx)
    aswap = baidx[:, 0] >= 2
    a0i = np.where(aswap, ba1, ba0)
    a1i = np.where(aswap, ba0, ba1)
    aidx = np.where(aswap[:, None], 3 - baidx, baidx)
    return q0, q1, a0i, a1i, cidx, aidx, best_err + besta


def _bc7_pack6_np(q0, q1, p0, p1, idx):
    u = np.uint64
    N = q0.shape[0]
    lo = np.full(N, 64, dtype=np.uint64)
    q0 = q0.astype(np.uint64); q1 = q1.astype(np.uint64); idx = idx.astype(np.uint64)
    pos = 7
    for ch in range(4):
        lo |= q0[:, ch] << u(pos); pos += 7
        lo |= q1[:, ch] << u(pos); pos += 7
    lo |= p0.astype(np.uint64) << u(63)
    hi = p1.astype(np.uint64)
    hi |= idx[:, 0] << u(1)
    for i in range(1, 16):
        hi |= idx[:, i] << u(4 * i)
    return lo, hi


def _bc7_pack5_np(q0, q1, a0, a1, cidx, aidx):
    u = np.uint64
    N = q0.shape[0]
    lo = np.full(N, 32, dtype=np.uint64)
    q0 = q0.astype(np.uint64); q1 = q1.astype(np.uint64)
    cidx = cidx.astype(np.uint64); aidx = aidx.astype(np.uint64)
    a0 = a0.astype(np.uint64); a1 = a1.astype(np.uint64)
    pos = 8
    for ch in range(3):
        lo |= q0[:, ch] << u(pos); pos += 7
        lo |= q1[:, ch] << u(pos); pos += 7
    lo |= a0 << u(50)
    lo |= (a1 & u(0x3F)) << u(58)          # A1 straddles the 64-bit boundary (bits 58..65)
    hi = a1 >> u(6)
    hi |= cidx[:, 0] << u(2)               # bit 66
    for i in range(1, 16):
        hi |= cidx[:, i] << u(1 + 2 * i)   # bit 65 + 2i
    hi |= aidx[:, 0] << u(33)              # bit 97
    for i in range(1, 16):
        hi |= aidx[:, i] << u(32 + 2 * i)  # bit 96 + 2i
    return lo, hi


def _bc7_np(px) -> bytes:
    N = px.shape[0]
    flat = (px == px[:, :1, :]).all(axis=(1, 2))
    lo = np.zeros(N, dtype=np.uint64)
    hi = np.zeros(N, dtype=np.uint64)
    nf = np.nonzero(~flat)[0]
    if len(nf):
        sub = px[nf]
        q0, q1, p0, p1, idx, err6 = _bc7_mode6_np(sub)
        lo6, hi6 = _bc7_pack6_np(q0, q1, p0, p1, idx)
        c0, c1, a0, a1, cidx, aidx, err5 = _bc7_mode5_np(sub)
        lo5, hi5 = _bc7_pack5_np(c0, c1, a0, a1, cidx, aidx)
        use5 = err5 < err6
        lo[nf] = np.where(use5, lo5, lo6)
        hi[nf] = np.where(use5, hi5, hi6)
    fl = np.nonzero(flat)[0]
    if len(fl):
        cache = {}
        for i in fl.tolist():
            col = tuple(int(x) for x in px[i, 0])
            blk = cache.get(col)
            if blk is None:
                blk = cache[col] = struct.unpack("<QQ", bc7_flat_block(*col))
            lo[i], hi[i] = blk
    return np.stack([lo, hi], axis=1).astype("<u8").tobytes()


def _quant565_np(e):
    """e (N,3) float -> (code (N,) int64, reconstructed (N,3) int64)."""
    r5 = np.clip(np.floor(e[:, 0] * 31 / 255 + 0.5), 0, 31).astype(np.int64)
    g6 = np.clip(np.floor(e[:, 1] * 63 / 255 + 0.5), 0, 63).astype(np.int64)
    b5 = np.clip(np.floor(e[:, 2] * 31 / 255 + 0.5), 0, 31).astype(np.int64)
    code = (r5 << 11) | (g6 << 5) | b5
    rec = np.stack([(r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2)], 1)
    return code, rec


def _bc1_colour_np(rgb, mask, three):
    """rgb (N,16,3) float, mask (N,16) bool, three (N,) bool -> (c0, c1, idx)."""
    N = rgb.shape[0]
    e0, e1 = _axis_endpoints_np(rgb, mask)
    best_err = np.full(N, np.inf)
    bc0 = np.zeros(N, dtype=np.int64); bc1 = np.zeros(N, dtype=np.int64)
    bidx = np.zeros((N, 16), dtype=np.int64)
    A4 = np.array([1.0, 0.0, 2 / 3, 1 / 3]); B4 = np.array([0.0, 1.0, 1 / 3, 2 / 3])
    A3 = np.array([1.0, 0.0, 0.5, 0.0]); B3 = np.array([0.0, 1.0, 0.5, 0.0])
    for it in range(3):
        c0, r0 = _quant565_np(e0)
        c1, r1 = _quant565_np(e1)
        swap = (~three & (c0 < c1)) | (three & (c0 > c1))
        c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
        r0, r1 = np.where(swap[:, None], r1, r0), np.where(swap[:, None], r0, r1)
        p2four = (2 * r0 + r1) // 3
        p3four = (r0 + 2 * r1) // 3
        p2three = (r0 + r1) // 2
        pal = np.stack([r0, r1, np.where(three[:, None], p2three, p2four), p3four], 1).astype(np.float64)  # (N,4,3)
        e = ((rgb[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(3)                                     # (N,16,4)
        e[three, :, 3] = np.inf                                   # index 3 = transparent in 3-colour mode
        single = ~three & (c0 == c1)
        e[single, :, 1:] = np.inf                                 # c0 == c1: index 0 only
        idx = e.argmin(2)
        err = (np.take_along_axis(e, idx[:, :, None], 2)[:, :, 0] * mask).sum(1)
        better = err < best_err
        best_err = np.where(better, err, best_err)
        bc0[better] = c0[better]; bc1[better] = c1[better]; bidx[better] = idx[better]
        if it < 2:
            a = np.where(three[:, None], A3[idx], A4[idx]) * mask
            b = np.where(three[:, None], B3[idx], B4[idx]) * mask
            e0, e1 = _refit_np(rgb, a, b, e0, e1)
    bidx = np.where(mask, bidx, 3)
    return bc0, bc1, bidx


def _bc1_pack_np(c0, c1, idx):
    """(N, 8) uint8 array of BC1 blocks."""
    u = np.uint64
    bits = np.zeros(c0.shape[0], dtype=np.uint64)
    idx = idx.astype(np.uint64)
    for i in range(16):
        bits |= idx[:, i] << u(2 * i)
    out = np.empty((c0.shape[0], 8), dtype=np.uint8)
    out[:, 0:2] = c0.astype("<u2")[:, None].view(np.uint8)
    out[:, 2:4] = c1.astype("<u2")[:, None].view(np.uint8)
    out[:, 4:8] = bits.astype("<u4")[:, None].view(np.uint8)
    return out


def _bc1_np(px) -> bytes:
    three = (px[:, :, 3] < 128).any(1)
    mask = np.where(three[:, None], px[:, :, 3] >= 128, True)
    c0, c1, idx = _bc1_colour_np(px[:, :, :3], mask, three)
    return _bc1_pack_np(c0, c1, idx).tobytes()


def _bc3_alpha_np(al):
    """al (N,16) float -> (a0, a1, idx (N,16))."""
    N = al.shape[0]
    amin, amax = al.min(1), al.max(1)
    inner_mask = (al > 0) & (al < 255)
    has_inner = inner_mask.any(1)
    imin = np.where(has_inner, np.where(inner_mask, al, np.inf).min(1), 0.0)
    imax = np.where(has_inner, np.where(inner_mask, al, -np.inf).max(1), 0.0)
    best_err = np.full(N, np.inf)
    ba0 = np.zeros(N, dtype=np.int64); ba1 = np.zeros(N, dtype=np.int64)
    bidx = np.zeros((N, 16), dtype=np.int64)

    def evaluate(a0, a1):
        nonlocal best_err
        a0 = a0.astype(np.int64); a1 = a1.astype(np.int64)
        eight = a0 > a1
        pal8 = np.stack([a0, a1] + [((6 - k) * a0 + (k + 1) * a1) // 7 for k in range(6)], 1)
        pal6 = np.stack([a0, a1] + [((4 - k) * a0 + (k + 1) * a1) // 5 for k in range(4)]
                        + [np.zeros(N, dtype=np.int64), np.full(N, 255, dtype=np.int64)], 1)
        pal = np.where(eight[:, None], pal8, pal6).astype(np.float64)               # (N,8)
        e = (al[:, :, None] - pal[:, None, :]) ** 2                                  # (N,16,8)
        idx = e.argmin(2)
        err = np.take_along_axis(e, idx[:, :, None], 2)[:, :, 0].sum(1)
        better = err < best_err
        best_err = np.where(better, err, best_err)
        ba0[better] = a0[better]; ba1[better] = a1[better]; bidx[better] = idx[better]
        return idx

    evaluate(imin, imax)                       # 6-level mode (0/255 come free)
    idx8 = evaluate(amax, amin)                # 8-level mode over the full range
    k = idx8.astype(np.float64)
    a = np.where(idx8 == 0, 1.0, np.where(idx8 == 1, 0.0, (7 - k) / 7.0))
    b = np.where(idx8 == 0, 0.0, np.where(idx8 == 1, 1.0, (k - 1) / 7.0))
    n0, n1 = _refit_np(al[:, :, None], a, b, amax[:, None], amin[:, None])
    r0 = np.floor(n0[:, 0] + 0.5); r1 = np.floor(n1[:, 0] + 0.5)
    ok = r0 > r1
    evaluate(np.where(ok, r0, amax), np.where(ok, r1, amin))
    return ba0, ba1, bidx


def _bc3_np(px) -> bytes:
    N = px.shape[0]
    a0, a1, aidx = _bc3_alpha_np(px[:, :, 3])
    c0, c1, cidx = _bc1_colour_np(px[:, :, :3], np.ones((N, 16), dtype=bool), np.zeros(N, dtype=bool))
    u = np.uint64
    abits = np.zeros(N, dtype=np.uint64)
    aidx = aidx.astype(np.uint64)
    for i in range(16):
        abits |= aidx[:, i] << u(3 * i)
    out = np.empty((N, 16), dtype=np.uint8)
    out[:, 0] = a0
    out[:, 1] = a1
    out[:, 2:8] = abits.astype("<u8")[:, None].view(np.uint8)[:, :6]
    out[:, 8:16] = _bc1_pack_np(c0, c1, cidx)
    return out.tobytes()


# --------------------------------------------------------------------------- #
# Public encode API
# --------------------------------------------------------------------------- #
def encode(kind: str, rgba: bytes, w: int, h: int, *, use_numpy: bool | None = None) -> bytes:
    """Encode a w x h RGBA8 buffer (row-major, 4 B/px) to `kind` ("bc1" | "bc3" | "bc7")
    blocks in raster order: ceil(w/4)*ceil(h/4) blocks of 8 (BC1) or 16 bytes.
    use_numpy=None picks numpy when available."""
    kind = kind.lower()
    if kind not in BLOCK_BYTES:
        raise BCEncodeError(f"no encoder for {kind!r} (have {', '.join(BLOCK_BYTES)})")
    if w <= 0 or h <= 0:
        raise BCEncodeError("empty image")
    if use_numpy is None:
        use_numpy = HAS_NUMPY
    if use_numpy and not HAS_NUMPY:
        raise BCEncodeError("numpy is not installed")
    if use_numpy:
        px = _blocks_np(rgba, w, h)
        return {"bc7": _bc7_np, "bc3": _bc3_np, "bc1": _bc1_np}[kind](px)
    fn = {"bc7": _bc7_block_py, "bc3": _bc3_block_py, "bc1": _bc1_block_py}[kind]
    return b"".join(fn(blk) for blk in _blocks_py(rgba, w, h))


def encode_bc7(rgba: bytes, w: int, h: int, **kw) -> bytes:
    return encode("bc7", rgba, w, h, **kw)


def encode_bc3(rgba: bytes, w: int, h: int, **kw) -> bytes:
    return encode("bc3", rgba, w, h, **kw)


def encode_bc1(rgba: bytes, w: int, h: int, **kw) -> bytes:
    return encode("bc1", rgba, w, h, **kw)


def encode_image(kind: str, img, **kw) -> bytes:
    """Encode a PIL Image (converted to RGBA)."""
    img = img.convert("RGBA")
    return encode(kind, img.tobytes("raw", "RGBA"), img.size[0], img.size[1], **kw)


# --------------------------------------------------------------------------- #
# Reference decoders (RGBA8 out); pure Python, for verification and numpy-free use
# --------------------------------------------------------------------------- #
def decode_bc7_block(block: bytes) -> list:
    """16 (r,g,b,a) tuples. Supports modes 5 and 6 (this encoder's output)."""
    v = int.from_bytes(block, "little")
    mode = 0
    while mode < 8 and not (v >> mode) & 1:
        mode += 1
    if mode == 6:
        pos = 7
        e0, e1 = [0] * 4, [0] * 4
        for ch in range(4):
            e0[ch] = (v >> pos) & 0x7F; pos += 7
            e1[ch] = (v >> pos) & 0x7F; pos += 7
        p0 = (v >> 63) & 1
        p1 = (v >> 64) & 1
        e0 = [(x << 1) | p0 for x in e0]
        e1 = [(x << 1) | p1 for x in e1]
        idx = [(v >> 65) & 7] + [(v >> (64 + 4 * i)) & 15 for i in range(1, 16)]
        return [tuple(_bc7_lerp(e0[k], e1[k], BC7_WEIGHTS4[i]) for k in range(4)) for i in idx]
    if mode == 5:
        rot = (v >> 6) & 3
        pos = 8
        e0, e1 = [0] * 3, [0] * 3
        for ch in range(3):
            e0[ch] = _G7[(v >> pos) & 0x7F]; pos += 7
            e1[ch] = _G7[(v >> pos) & 0x7F]; pos += 7
        a0 = (v >> 50) & 0xFF
        a1 = (v >> 58) & 0xFF
        cidx = [(v >> 66) & 1] + [(v >> (65 + 2 * i)) & 3 for i in range(1, 16)]
        aidx = [(v >> 97) & 1] + [(v >> (96 + 2 * i)) & 3 for i in range(1, 16)]
        out = []
        for ci, ai in zip(cidx, aidx):
            px = [_bc7_lerp(e0[k], e1[k], BC7_WEIGHTS2[ci]) for k in range(3)]
            px.append(_bc7_lerp(a0, a1, BC7_WEIGHTS2[ai]))
            if rot:                                   # rotation swaps alpha with channel rot-1
                px[rot - 1], px[3] = px[3], px[rot - 1]
            out.append(tuple(px))
        return out
    raise BCEncodeError(f"BC7 mode {mode} is not produced by this encoder (decoder covers 5/6 only)")


def decode_bc1_block(block: bytes) -> list:
    c0, c1, bits = struct.unpack_from("<HHI", block)
    pal = _bc1_palette(c0, c1)
    return [pal[(bits >> (2 * i)) & 3] for i in range(16)]


def decode_bc3_block(block: bytes) -> list:
    a0, a1 = block[0], block[1]
    abits = int.from_bytes(block[2:8], "little")
    apal = _bc3_alpha_palette(a0, a1)
    col = decode_bc1_block(block[8:16])
    return [(c[0], c[1], c[2], apal[(abits >> (3 * i)) & 7]) for i, c in enumerate(col)]


def decode(kind: str, blocks: bytes, w: int, h: int) -> bytes:
    """Decode blocks to a w x h RGBA8 buffer (padding pixels dropped)."""
    kind = kind.lower()
    fn = {"bc7": decode_bc7_block, "bc3": decode_bc3_block, "bc1": decode_bc1_block}[kind]
    bs = BLOCK_BYTES[kind]
    bw, bh = block_grid(w, h)
    if len(blocks) < bw * bh * bs:
        raise BCEncodeError(f"need {bw * bh * bs} bytes of {kind} blocks, have {len(blocks)}")
    out = bytearray(w * h * 4)
    for by in range(bh):
        for bx in range(bw):
            px = fn(blocks[(by * bw + bx) * bs:(by * bw + bx + 1) * bs])
            for i, p in enumerate(px):
                x, y = bx * 4 + (i & 3), by * 4 + (i >> 2)
                if x < w and y < h:
                    o = (y * w + x) * 4
                    out[o:o + 4] = bytes(p)
    return bytes(out)
