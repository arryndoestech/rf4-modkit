"""
flagstate.py -- a snapshot of the game-flag store, and which placed objects it hides.

The store is 6656 bits (832 bytes): zone 1 = bits 0..4095 (the emdeb-named FLG_/REG_
variables), zone 2 = bits 4096..6655 (unnamed scene bits). A slot save keeps a raw copy at
file +0x1E8C4 (save.GAMEFLAGS_OFF); the running game keeps it behind g_gameFlagsBuffer
(RF4S.exe+0xE9E4B0 -> {u32 zone2_base = 4096, u32 zone2_bits = 2560, u64 bits}). Single
bits are plain little-endian bit tests (byte = bit >> 3, mask = 1 << (bit & 7)).

Map objects gate on a ZONE-2 bit in MOBJ f13 (params[13], read as a dword; > 0 = gated):

* decorations (type >= 336, MapDecoration_Spawn RF4S.exe+0x142D30): hidden while the bit
  is set;
* interactive objects (types 196..335, Map_SpawnInteractiveObject +0x143760): hidden while
  (bit set) XOR (f12 & 4) -- f12 bit 2 inverts the gate ("shown only once set").

Both tests run once, when the map loads, so in game a flag change shows on the next visit.
Example: MAP_CITY_04 (Dragon Lake) bridge = decoration f13 73, its wall = object f13 74.
"""
from __future__ import annotations

import pathlib

from . import mobj_types
from .save import GAMEFLAGS_OFF, SAVE_SIZE

BLOB_SIZE = 832
ZONE2_BASE = 4096
ZONE2_BITS = 2560
FLAGS_BUFFER_RVA = 0xE9E4B0          # g_gameFlagsBuffer (pointer to the header)


class FlagState:
    """832-byte flag blob plus a label saying where it came from."""

    def __init__(self, blob: bytes, source: str):
        if len(blob) < BLOB_SIZE:
            raise ValueError("flag blob is %d bytes, expected %d" % (len(blob), BLOB_SIZE))
        self.blob = bytes(blob[:BLOB_SIZE])
        self.source = source

    def bit(self, abs_bit: int) -> bool:
        if not 0 <= abs_bit < BLOB_SIZE * 8:
            return False
        return bool((self.blob[abs_bit >> 3] >> (abs_bit & 7)) & 1)

    def zone2(self, n: int) -> bool:
        return 0 <= n < ZONE2_BITS and self.bit(ZONE2_BASE + n)

    def story(self) -> int:
        """REG_MAIN_SCENARIO (bit 0, width 9, MSB-first)."""
        v = 0
        for i in range(9):
            v = (v << 1) | self.bit(i)
        return v


def from_save(path) -> FlagState:
    data = pathlib.Path(path).read_bytes()
    if len(data) < SAVE_SIZE:
        raise ValueError("%s is not a slot save (%d bytes)" % (path, len(data)))
    return FlagState(data[GAMEFLAGS_OFF:GAMEFLAGS_OFF + BLOB_SIZE],
                     "save " + pathlib.Path(path).name)


def from_running_game(exe_name: str = "RF4S.exe") -> FlagState:
    """Read the live flag store from a running RF4S.exe (Windows, read-only access).
    Raises RuntimeError when the game is not running or the header does not look right
    (a different exe build would put g_gameFlagsBuffer elsewhere)."""
    import ctypes
    import ctypes.wintypes as wt
    import subprocess

    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + exe_name, "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    rows = [l for l in out.splitlines() if l.lower().startswith('"' + exe_name.lower())]
    if not rows:
        raise RuntimeError(exe_name + " is not running")
    pid = int(rows[0].split('","')[1])
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi")
    k32.OpenProcess.restype = wt.HANDLE
    h = k32.OpenProcess(0x0410, False, pid)            # QUERY_INFORMATION | VM_READ
    if not h:
        raise RuntimeError("cannot open %s (pid %d): error %d" % (exe_name, pid, ctypes.get_last_error()))
    try:
        mods = (wt.HMODULE * 1)()
        need = wt.DWORD()
        if not psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 3):
            raise RuntimeError("cannot list %s modules" % exe_name)
        base = mods[0]

        def read(addr, n):
            buf = ctypes.create_string_buffer(n)
            got = ctypes.c_size_t()
            if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
                raise RuntimeError("read at +0x%X failed (error %d)" % (addr - base, ctypes.get_last_error()))
            return buf.raw

        hdr_ptr = int.from_bytes(read(base + FLAGS_BUFFER_RVA, 8), "little")
        if not hdr_ptr:
            raise RuntimeError("the flag store is not allocated yet (title screen?)")
        hdr = read(hdr_ptr, 16)
        zbase = int.from_bytes(hdr[0:4], "little")
        zbits = int.from_bytes(hdr[4:8], "little")
        if (zbase, zbits) != (ZONE2_BASE, ZONE2_BITS):
            raise RuntimeError("unexpected flag header (%d, %d): not the build this reader knows"
                               % (zbase, zbits))
        bits = int.from_bytes(hdr[8:16], "little")
        return FlagState(read(bits, BLOB_SIZE), "running game (pid %d)" % pid)
    finally:
        k32.CloseHandle(h)


def gate(obj: dict):
    """(zone-2 flag, inverted) an object's visibility depends on, or None if ungated."""
    p = obj.get("params", ())
    if len(p) < 14:
        return None
    kind = mobj_types.mobj_kind(obj["type_id"])
    f13 = p[13]
    if kind not in ("decoration", "object") or not 0 < f13 < ZONE2_BITS:
        return None
    inverted = kind == "object" and bool(p[12] & 4)
    return f13, inverted


def hidden(obj: dict, state: FlagState | None) -> bool:
    """True when the game would not draw this object with these flags."""
    g = gate(obj)
    if g is None or state is None:
        return False
    flag, inverted = g
    return state.zone2(flag) != inverted
