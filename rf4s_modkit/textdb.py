r"""
textdb.py -- RF4S `TEXT` string-archive read / write.

The `TEXT` format is the game's universal string table. It is used both by the
big localized catalogs that ship as bundle files (`rf3mc.eng`, `rf3mc.jpn`, ...,
the prime translation targets) AND by the per-subsystem string archives loaded by
numeric id through `nsFileArchive` (item names id 16356, item descriptions 16360,
NPC/monster names 16369, dialogue, quest text, skill names, ...).

Layout (verified against the corpus and the loader, Text_CopyArchiveEntry @
RF4S.exe+0x241310 via Text_LoadStringFromArchive @ +0x232290):

    +0x00  char[4]  "TEXT"
    +0x04  u32      entry_count
    +0x08  entry_count x { u32 length; u32 offset }   # offset ABSOLUTE from file start,
                                                       # length EXCLUDES the NUL terminator
    +...   string blobs, each NUL-terminated, stored consecutively

The game copies exactly `length` bytes from `offset` and appends its own NUL, so the
stored terminator is never read and no alignment is required; an index >= entry_count
silently falls back to entry 0. Most archives end each string with one NUL, but 31
shipped .jpn/.kor/.twn catalogs use two (`\0\0`); `parse` records the width in
`terminator` and `build` reuses it, so every shipped archive rebuilds byte-exact.

Strings are byte-faithful on read; decode with whatever encoding the locale uses
(English/European = UTF-8/ASCII; Japanese/Chinese/Korean = UTF-8 in the PC port).
Rebuild is exact: empty entries (length 0) and shared/duplicate strings are
preserved structurally.

A companion `MYCF` index file (`rf3.mc`) maps symbolic keys to indices, but
translating in place keeps the same count/order, so the index needs no changes.
"""
from __future__ import annotations

import pathlib
import struct

MAGIC = b"TEXT"


class TextDbError(Exception):
    pass


class TextArchive:
    """A parsed TEXT archive. `entries` is a list of raw `bytes` (no NUL).
    `terminator` is the NUL count written after each string (1, or 2 in some CJK
    catalogs; the game ignores it)."""

    def __init__(self, entries: list[bytes], terminator: int = 1):
        # Guard the easy footgun: passing RAW archive bytes (or a str) instead of a list of
        # per-line entries. `list(b"...")` silently yields a list of ints, so text() would return
        # garbage with no error. Point the caller at the real parsers instead.
        if isinstance(entries, (bytes, bytearray, str)):
            raise TextDbError(
                "TextArchive() takes a list of per-line `bytes`, not raw archive data -- "
                "use TextArchive.parse(data) or TextArchive.load(path) to parse a TEXT archive.")
        self.entries: list[bytes] = list(entries)
        self.terminator = terminator

    # ---- parsing --------------------------------------------------------- #
    @classmethod
    def parse(cls, data: bytes) -> "TextArchive":
        if data[:4] != MAGIC:
            raise TextDbError(f"not a TEXT archive (magic={data[:4]!r})")
        if len(data) < 8:                             # 4-byte magic + 4-byte entry count
            raise TextDbError(f"truncated TEXT archive: {len(data)} bytes, need >= 8 for the header")
        count = struct.unpack_from("<I", data, 4)[0]
        if count > (len(data) // 8):
            raise TextDbError(f"implausible entry_count {count} for {len(data)}-byte file")
        # the whole offset table in one unpack, the entries in one pass (113,000 lines per
        # language: the per-line struct calls were most of the time)
        table = struct.unpack_from("<%dI" % (2 * count), data, 8)
        lens, offs = table[0::2], table[1::2]
        n = len(data)
        for i, (length, offset) in enumerate(zip(lens, offs)):
            if offset + length > n and (offset or length):
                raise TextDbError(f"entry {i} runs past EOF (off={offset}, len={length})")
        entries = [data[o:o + ln] if (o or ln) else b"" for ln, o in zip(lens, offs)]
        spans = [(o, ln) for ln, o in zip(lens, offs) if ln]
        return cls(entries, terminator=cls._detect_terminator(data, spans))

    @staticmethod
    def _detect_terminator(data: bytes, spans) -> int:
        """2 when every stored string is followed by exactly two NULs, else 1."""
        if not spans:
            return 1
        if any(a >= b for a, b in zip(spans, spans[1:])):    # the game's files: already in order
            spans = sorted(set(spans))
        nexts = [o for o, _ln in spans[1:]] + [len(data)]
        for (off, ln), nxt in zip(spans, nexts):
            end = off + ln
            if nxt - end != 2 or data[end:end + 2] != b"\x00\x00":
                return 1
        return 2

    @classmethod
    def load(cls, path) -> "TextArchive":
        return cls.parse(pathlib.Path(path).read_bytes())

    # ---- views ----------------------------------------------------------- #
    def __len__(self):
        return len(self.entries)

    def text(self, index: int, encoding: str = "utf-8") -> str:
        return self.entries[index].decode(encoding, "replace")

    def texts(self, encoding: str = "utf-8") -> list[str]:
        return [e.decode(encoding, "replace") for e in self.entries]

    def set_text(self, index: int, value: str, encoding: str = "utf-8"):
        self.entries[index] = value.encode(encoding)

    def append_text(self, value: str, encoding: str = "utf-8") -> int:
        """Append a NEW dialogue line to the archive and return its line id (index).

        Lets the editor author brand-new dialogue text (for new cutscene beats or a locale
        that is missing a line), not just rewrite existing lines. build() serialises the new
        entry into the offset table like any other. The returned id can then be used as a
        DIALOG's line id (retarget an inserted beat to it)."""
        self.entries.append(value.encode(encoding))
        return len(self.entries) - 1

    # ---- rebuild --------------------------------------------------------- #
    def build(self) -> bytes:
        """Serialise back to a valid TEXT archive."""
        count = len(self.entries)
        table_size = count * 8
        strdata_start = 8 + table_size
        table = bytearray()
        blob = bytearray()
        for e in self.entries:
            if e == b"":
                # Mirror the empty-entry convention (length 0). Point at strdata
                # start to stay in-bounds; the game keys off length 0.
                table += struct.pack("<II", 0, strdata_start)
                continue
            off = strdata_start + len(blob)
            table += struct.pack("<II", len(e), off)
            blob += e + b"\x00" * self.terminator
        return MAGIC + struct.pack("<I", count) + bytes(table) + bytes(blob)

    def save(self, path):
        pathlib.Path(path).write_bytes(self.build())


# ---- convenience JSON bridge for bulk translation ------------------------ #
def to_json(path_in, path_out=None, encoding: str = "utf-8"):
    """Dump a TEXT archive to a JSON list of strings (for editing)."""
    import json
    arc = TextArchive.load(path_in)
    out = json.dumps(arc.texts(encoding), ensure_ascii=False, indent=1)
    if path_out:
        pathlib.Path(path_out).write_text(out, encoding="utf-8")
    return out


def from_json(json_path, out_text_path, encoding: str = "utf-8"):
    """Rebuild a TEXT archive from a JSON list of strings."""
    import json
    items = json.loads(pathlib.Path(json_path).read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise TextDbError("JSON root must be a list of strings")
    arc = TextArchive([s.encode(encoding) for s in items])
    arc.save(out_text_path)
    return len(items)
