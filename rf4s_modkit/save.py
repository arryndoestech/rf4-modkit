"""rf4s_modkit/save.py -- RF4S per-slot save file (rf4_sNN.sav) reader / editor.

The on-disk save is a flat 140,424-byte binary. A single **CRC-32 (zlib/IEEE)** over
`file[4 : 4+140196]` is stored at `file[0]` (`Save_ComputeChecksum`, IDA-verified poly
0xEDB88320; no nested checksums). Editing = patch bytes anywhere in the body, then
`build()` recomputes that CRC so the game accepts the save.

The **GameFlags** bitfield region at `file+0x1E8C4` is name-addressable via the emdeb.bin
variable table (`emflags`): 1822 named `FLG_`/`REG_` story / unlock / relationship flags.
Multi-bit registers are **MSB-first** (IDA-verified GameFlags_ReadField; live-checked:
REG_CHILD_ID reads 23=Daughter).

A CRC mismatch is NOT reported by the game: rf3BackupLoadDataBuild (RF4S.exe+0x822E0) zeroes the
whole 0x223A8-byte slot buffer (u32 crc + the 140196-byte body) and the slot shows as EMPTY.
The 224 bytes past file[4+140196] are outside the CRC.

Region map (community map from the 3DS save; only the header clock and GameFlags offsets are
verified on the PC file, see SCALARS):
    +0x00000 HEADER (84B): crc, difficulty, clock, gender, materials, money
    +0x00054 BTLSTATS      +0x05964 SKILLS      +0x05AA4 ITEMS      +0x18EA4 FARMS
    +0x1BDB0 BARN MONSTERS +0x1DB10 VILLAGER FRIENDSHIP (23x44B)
    +0x1E8C4 GAMEFLAGS     +0x20694 princePoints +0x20698 tourists
"""
from __future__ import annotations

import struct
import zlib

SAVE_SIZE = 140424
CRC_DATA_START = 4
CRC_DATA_LEN = 140196          # zlib.crc32(file[4 : 4+140196]) -> file[0]
GAMEFLAGS_OFF = 0x1E8C4
SEASONS = ("Spring", "Summer", "Autumn", "Winter")

# Named scalar fields: (file offset, struct format). Header clock verified vs a real
# PC save (rf4_s08: day 9 / Spring / year 1). NOTE: the HenryEx region-map offsets for
# princePoints/tourists/etc. are for the 3DS save and are SHIFTED on the 140424-byte PC
# save (they read garbage), so only the verified header clock is exposed by name here.
# Everything else is reachable via get_u32/set_u32(offset) + the named GameFlags API.
SCALARS = {
    "day":    (0x14, "<I"),
    "season": (0x18, "<I"),      # 0 Spring / 1 Summer / 2 Autumn / 3 Winter
    "year":   (0x1C, "<I"),
}


class SaveError(Exception):
    pass


class SaveFile:
    """A parsed, editable RF4S per-slot save. Edits mutate self.data; build() re-CRCs."""

    def __init__(self, data):
        self.data = bytearray(data)
        # Must span the full CRC region (file[4:4+140196]) or computed_crc()/build() would
        # silently CRC a short buffer and write a wrong-but-no-error checksum. A real slot
        # save is exactly SAVE_SIZE; anything shorter is truncated/corrupt.
        if len(self.data) < SAVE_SIZE:
            raise SaveError("too small (%d bytes; expected %d) to be an rf4_sNN.sav slot save"
                            % (len(self.data), SAVE_SIZE))
        self._emf = None

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            return cls(f.read())

    def save(self, path):
        with open(path, "wb") as f:
            f.write(self.build())

    # ---- integrity -----------------------------------------------------------
    def stored_crc(self):
        return struct.unpack_from("<I", self.data, 0)[0]

    def computed_crc(self):
        return zlib.crc32(bytes(self.data[CRC_DATA_START:CRC_DATA_START + CRC_DATA_LEN])) & 0xFFFFFFFF

    def crc_ok(self):
        return self.stored_crc() == self.computed_crc()

    def build(self):
        """Recompute the body CRC-32 and return the (game-acceptable) save bytes."""
        struct.pack_into("<I", self.data, 0, self.computed_crc())
        return bytes(self.data)

    # ---- scalar / raw fields -------------------------------------------------
    def get(self, name):
        off, fmt = SCALARS[name]
        return struct.unpack_from(fmt, self.data, off)[0]

    def set(self, name, value):
        off, fmt = SCALARS[name]
        value = int(value)
        if name == "season" and not (0 <= value <= 3):
            raise SaveError(f"season {value} out of range (0 Spring .. 3 Winter)")
        try:
            struct.pack_into(fmt, self.data, off, value)
        except struct.error as e:
            raise SaveError(f"{name} = {value}: {e}") from None
        return self

    def get_u32(self, off):
        return struct.unpack_from("<I", self.data, off)[0]

    def set_u32(self, off, value):
        struct.pack_into("<I", self.data, off, int(value) & 0xFFFFFFFF)
        return self

    # ---- named GameFlags (via emdeb.bin variable table) ----------------------
    def _flags(self):
        if self._emf is None:
            from . import emflags
            self._emf = emflags.EmFlagTable.load()
        return self._emf

    def flag(self, name, emf=None):
        """Read a named FLG_/REG_ variable from the GameFlags region (MSB-first multi-bit)."""
        emf = emf or self._flags()
        return emf.read_value(self.data[GAMEFLAGS_OFF:], name)

    def set_flag(self, name, value, emf=None):
        """Write a named FLG_/REG_ variable into the GameFlags region (MSB-first)."""
        emf = emf or self._flags()
        emf.write_value(memoryview(self.data)[GAMEFLAGS_OFF:], name, int(value))
        return self

    def find_flags(self, substr, emf=None):
        """[(name, current_value, width)] for every flag whose name contains `substr`."""
        emf = emf or self._flags()
        return [(v.name, emf.read_value(self.data[GAMEFLAGS_OFF:], v), v.bit_width)
                for v in emf.find(substr)]

    # ---- summary -------------------------------------------------------------
    def summary(self):
        s = self.get("season")
        return {
            "size": len(self.data),
            "crc_ok": self.crc_ok(),
            "day": self.get("day"),
            "season": SEASONS[s] if s < 4 else s,
            "year": self.get("year"),
        }
