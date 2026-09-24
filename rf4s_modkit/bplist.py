r"""
bplist.py -- Muteki binary-plist reader and writer.

RF4S `.mbundle`, `.minterface`, `Manifest.plist`, and most `.plist` assets are
Apple binary plists with TWO Muteki-specific deviations (verified against
Bplist_ParseFile @ RF4S.exe+0x266EF0 and Bplist_ReadObject @ +0x266860):

  1. The trailer is 26 bytes, not Apple's 32 (no 5-byte pad, no sortVersion byte).
  2. The trailer's `top_object` field is a DIRECT FILE OFFSET (root is parsed at
     `top_object + 8`), not an index into the offset table.

Additionally, dict entries always use 4-byte big-endian object refs regardless of
the trailer's `object_ref_size` (the 0xD branch of Bplist_ReadObject hard-codes
`* 4`). Arrays honour `object_ref_size`.

The offset table holds ABSOLUTE file offsets (entry 0 == 8, right after the magic).
The root object is conventionally the last object in the file, and
`top_object == root_absolute_offset - 8`.

This module round-trips: `loads(dumps(x)) == x` for every shipped plist, and the
serialiser reproduces the exact conventions the game's parser expects.

Object model used by this module (Python <-> bplist):
    None              <-> null  (0x00)
    bool              <-> true/false (0x09 / 0x08)
    int               <-> integer (0x1n)
    float             <-> real, 8-byte double (0x23)
    str               <-> ASCII (0x5n) if pure-ASCII else UTF-16BE (0x6n)
    bytes/bytearray   <-> data blob (0x4n)
    list              <-> array (0xAn)
    dict              <-> dictionary (0xDn)   (keys must be str)

For huge archives (.mbundle) where you do not want to copy every data blob into
RAM, use `Bplist(data)` directly and read with `lazy_data=True`: data objects come
back as `DataRef(offset, size)` slices instead of `bytes`.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"bplist00"
TRAILER_LEN = 26


class BplistError(Exception):
    pass


@dataclass(frozen=True)
class DataRef:
    """A lazily-read data blob: bytes live at data[offset:offset+size]."""
    offset: int
    size: int

    def read(self, data: bytes) -> bytes:
        return bytes(data[self.offset:self.offset + self.size])


# --------------------------------------------------------------------------- #
# Reader
# --------------------------------------------------------------------------- #
class Bplist:
    """Low-level reader over a binary-plist byte buffer."""

    def __init__(self, data: bytes):
        if data[:8] != MAGIC:
            raise BplistError(f"not a binary plist (magic={data[:8]!r})")
        self.data = data
        t = data[-TRAILER_LEN:]
        self.offset_size = t[0]
        self.ref_size = t[1]
        self.num_objects = struct.unpack_from(">Q", t, 2)[0]
        self.top_object = struct.unpack_from(">Q", t, 10)[0]
        self.offset_table_offset = struct.unpack_from(">Q", t, 18)[0]
        os_ = self.offset_size
        base = self.offset_table_offset
        self.offsets = [
            int.from_bytes(data[base + i * os_: base + (i + 1) * os_], "big")
            for i in range(self.num_objects)
        ]
        self._cache: dict[int, object] = {}

    def _read_at(self, pos: int, lazy_data: bool):
        buf = self.data
        marker = buf[pos]
        pos += 1
        hi, lo = marker >> 4, marker & 0xF

        if hi == 0:
            return {0x0: None, 0x8: False, 0x9: True}.get(lo, None), pos
        if hi == 1:                                   # integer (big-endian)
            n = 1 << lo
            # Apple convention: only the 8-byte width is signed (two's complement);
            # narrower widths are always unsigned. The writer mirrors this.
            return int.from_bytes(buf[pos:pos + n], "big", signed=(n == 8)), pos + n
        if hi == 2:                                   # real
            n = 1 << lo
            fmt = ">f" if n == 4 else ">d"
            return struct.unpack_from(fmt, buf, pos)[0], pos + n

        # Length-carrying types. lo == 0xF means an inline int holds the count.
        if lo == 0xF:
            cm = buf[pos]; pos += 1
            n = 1 << (cm & 0xF)
            count = int.from_bytes(buf[pos:pos + n], "big"); pos += n
        else:
            count = lo

        if hi == 4:                                   # data blob
            ref = DataRef(pos, count)
            return (ref if lazy_data else ref.read(buf)), pos + count
        if hi == 5:                                   # ASCII string
            return buf[pos:pos + count].decode("ascii", "replace"), pos + count
        if hi == 6:                                   # UTF-16BE string (count = chars)
            return buf[pos:pos + 2 * count].decode("utf-16-be", "replace"), pos + 2 * count
        if hi == 8:                                   # UID (unsupported by game)
            return ("UID", int.from_bytes(buf[pos:pos + count + 1], "big")), pos + count + 1
        if hi == 0xA or hi == 0xC:                    # array / set
            rs = self.ref_size
            items = []
            for _ in range(count):
                idx = int.from_bytes(buf[pos:pos + rs], "big"); pos += rs
                items.append(self._resolve(idx, lazy_data))
            return items, pos
        if hi == 0xD:                                 # dict (refs ALWAYS 4 bytes)
            keys, vals = [], []
            for _ in range(count):
                idx = int.from_bytes(buf[pos:pos + 4], "big"); pos += 4
                keys.append(self._resolve(idx, lazy_data))
            for _ in range(count):
                idx = int.from_bytes(buf[pos:pos + 4], "big"); pos += 4
                vals.append(self._resolve(idx, lazy_data))
            return dict(zip(keys, vals)), pos
        raise BplistError(f"unknown marker {marker:#04x} at {pos - 1:#x}")

    def _resolve(self, idx: int, lazy_data: bool):
        if idx in self._cache:
            return self._cache[idx]
        val, _ = self._read_at(self.offsets[idx], lazy_data)
        self._cache[idx] = val
        return val

    def root(self, lazy_data: bool = False):
        """Return the root object. Root lives at top_object + 8 (Muteki quirk)."""
        val, _ = self._read_at(self.top_object + 8, lazy_data)
        return val


def loads(data: bytes, lazy_data: bool = False):
    """Parse a binary plist into Python objects."""
    return Bplist(data).root(lazy_data=lazy_data)


def load(path, lazy_data: bool = False):
    import pathlib
    return loads(pathlib.Path(path).read_bytes(), lazy_data=lazy_data)


# --------------------------------------------------------------------------- #
# Writer
# --------------------------------------------------------------------------- #
def _int_marker(value: int) -> bytes:
    """Encode an integer object (marker + big-endian body)."""
    if value < 0:
        # Apple stores negatives as 8-byte two's complement.
        return b"\x13" + struct.pack(">q", value)
    for n, code in ((1, 0x10), (2, 0x11), (4, 0x12), (8, 0x13)):
        if value < (1 << (8 * n)):
            # An 8-byte body is decoded SIGNED (see _read_at), so a value with the top
            # bit set (>= 2**63) would round-trip negative. Apple stores those as a
            # 16-byte body (read unsigned) -- do the same so the round-trip is exact.
            if n == 8 and value >= (1 << 63):
                break
            return bytes([code]) + value.to_bytes(n, "big")
    if value < (1 << 128):
        return b"\x14" + value.to_bytes(16, "big")      # 16-byte int (read unsigned)
    raise BplistError(f"integer too large: {value}")


def _length_prefix(hi_nibble: int, count: int) -> bytes:
    """Marker byte for a length-carrying type, with inline int if count >= 15."""
    if count < 0xF:
        return bytes([(hi_nibble << 4) | count])
    return bytes([(hi_nibble << 4) | 0xF]) + _int_marker(count)


class BplistWriter:
    """
    Serialise a Python object tree into a Muteki binary plist.

    Usage:
        w = BplistWriter(root_obj)
        blob = w.build()
        # After build(), w.data_offsets maps id(bytes_value) -> absolute payload
        # offset, useful when you need a Manifest TOC pointing at embedded blobs.

    Containers (dict/list) are deduped by identity; scalars are emitted once per
    occurrence. Refs are resolved by re-deriving the object graph in build(), so
    Python's interning of small ints/strings is irrelevant to correctness.
    """

    def __init__(self, root):
        self.root = root
        self.data_offsets: dict[int, int] = {}  # id(bytes) -> payload offset

    def build(self, ref_size: int = 4) -> bytes:
        """
        Produce the bplist bytes. `ref_size` is the array object-ref width (default
        4, always safe). dict refs are always 4 bytes regardless (Muteki quirk).

        One clean pass: flatten the tree recording, for each node, the child node
        indices it references; then emit objects, the offset table, and the trailer.
        """
        nodes: list[object] = []
        index_of_container: dict[int, int] = {}
        # child_refs[node_index] = list of child node indices (for containers)
        child_refs: list[list[int]] = []

        def visit(obj) -> int:
            if isinstance(obj, (dict, list)) and id(obj) in index_of_container:
                return index_of_container[id(obj)]
            idx = len(nodes)
            nodes.append(obj)
            child_refs.append([])
            if isinstance(obj, (dict, list)):
                index_of_container[id(obj)] = idx
            if isinstance(obj, dict):
                key_idx = [visit(k) for k in obj.keys()]
                val_idx = [visit(v) for v in obj.values()]
                child_refs[idx] = key_idx + val_idx
            elif isinstance(obj, list):
                child_refs[idx] = [visit(v) for v in obj]
            return idx

        root_idx = visit(self.root)
        num = len(nodes)

        # Emit objects, recording offsets. Object region starts at offset 8.
        body = bytearray()
        offsets = [0] * num
        self.data_offsets = {}
        for i, obj in enumerate(nodes):
            offsets[i] = 8 + len(body)
            if isinstance(obj, dict):
                head = _length_prefix(0xD, len(obj))
                refs = child_refs[i]
                n = len(obj)
                kbytes = b"".join(r.to_bytes(4, "big") for r in refs[:n])
                vbytes = b"".join(r.to_bytes(4, "big") for r in refs[n:])
                body += head + kbytes + vbytes
            elif isinstance(obj, list):
                head = _length_prefix(0xA, len(obj))
                rbytes = b"".join(r.to_bytes(ref_size, "big") for r in child_refs[i])
                body += head + rbytes
            elif isinstance(obj, (bytes, bytearray)):
                bb = bytes(obj)
                head = _length_prefix(0x4, len(bb))
                self.data_offsets[id(obj)] = offsets[i] + len(head)
                body += head + bb
            else:
                body += self._encode_one_scalar(obj)

        object_region_end = 8 + len(body)
        ot_offset = object_region_end
        max_off = max(offsets) if offsets else 8
        offset_size = 1
        for cand in (1, 2, 4, 8):
            if max(max_off, ot_offset) < (1 << (8 * cand)):
                offset_size = cand
                break
        else:
            offset_size = 8

        out = bytearray(MAGIC)
        out += body
        for off in offsets:
            out += off.to_bytes(offset_size, "big")
        trailer = bytes([offset_size, ref_size]) \
            + struct.pack(">Q", num) \
            + struct.pack(">Q", offsets[root_idx] - 8) \
            + struct.pack(">Q", ot_offset)
        out += trailer
        return bytes(out)

    @staticmethod
    def _encode_one_scalar(v) -> bytes:
        if v is None:
            return b"\x00"
        if isinstance(v, bool):
            return b"\x09" if v else b"\x08"
        if isinstance(v, int):
            return _int_marker(v)
        if isinstance(v, float):
            return b"\x23" + struct.pack(">d", v)
        if isinstance(v, str):
            try:
                a = v.encode("ascii")
                return _length_prefix(0x5, len(a)) + a
            except UnicodeEncodeError:
                u = v.encode("utf-16-be")
                return _length_prefix(0x6, len(u) // 2) + u
        raise BplistError(f"cannot serialise scalar {type(v).__name__}")


def dumps(obj, ref_size: int = 4) -> bytes:
    """Serialise a Python object tree into a Muteki binary plist."""
    return BplistWriter(obj).build(ref_size)


def dump(obj, path, ref_size: int = 4) -> None:
    import pathlib
    pathlib.Path(path).write_bytes(dumps(obj, ref_size=ref_size))


# --------------------------------------------------------------------------- #
# JSON bridge (for hand-editing) ---------------------------------------------#
# --------------------------------------------------------------------------- #
def to_jsonable(obj):
    """Convert a parsed plist into JSON-safe Python (bytes -> {'__data_b64__':...})."""
    import base64
    if isinstance(obj, DataRef):
        raise BplistError("to_jsonable needs eager data; parse with lazy_data=False")
    if isinstance(obj, (bytes, bytearray)):
        return {"__data_b64__": base64.b64encode(bytes(obj)).decode("ascii")}
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    return obj


def from_jsonable(obj):
    """Inverse of to_jsonable: turn {'__data_b64__':...} back into bytes."""
    import base64
    if isinstance(obj, dict):
        if set(obj.keys()) == {"__data_b64__"}:
            return base64.b64decode(obj["__data_b64__"])
        return {k: from_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [from_jsonable(v) for v in obj]
    return obj
