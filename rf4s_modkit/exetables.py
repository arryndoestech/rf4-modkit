"""exetables.py -- read data tables straight out of the game folder's RF4S.exe.

Some of the game's tables live in the exe, not in any data file (the chest and crate loot,
the per-area BGM). These helpers map an RVA (RF4S.exe+0x...) to a file offset through the PE
section table and read typed arrays from it. The toolkit does NOT read the exe at run time:
gen_exe_tables_json.py extracts the tables once into refdata/rf4s_exe_tables.json (shipped),
and the selftest uses these helpers to check that file against the exe it came from.
"""
from __future__ import annotations

import pathlib
import struct

_CACHE = {}                 # (path, mtime, size) -> bytes


class ExeTableError(Exception):
    pass


def default_exe():
    """RF4S.exe of the selected game folder (next to its Bundle folder), or None."""
    try:
        from . import gamepaths
        b = gamepaths.find_bundle_dir()
    except Exception:
        return None
    p = pathlib.Path(b).parent / "RF4S.exe" if b else None
    return p if p is not None and p.is_file() else None


def exe_bytes(exe=None) -> bytes:
    """The exe's bytes (default: the game folder's), cached until the file changes."""
    p = pathlib.Path(exe) if exe is not None else default_exe()
    if p is None or not p.is_file():
        raise ExeTableError("RF4S.exe not found next to the game's Bundle folder")
    st = p.stat()
    key = (str(p), st.st_mtime_ns, st.st_size)
    if key not in _CACHE:
        _CACHE.clear()
        _CACHE[key] = p.read_bytes()
    return _CACHE[key]


def rva_to_offset(data: bytes, rva: int) -> int:
    """File offset of `rva` in the PE image `data` (through its section table)."""
    if data[:2] != b"MZ":
        raise ExeTableError("not a PE file (no MZ header)")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ExeTableError("not a PE file (no PE signature)")
    nsec, = struct.unpack_from("<H", data, pe + 6)
    opt_size, = struct.unpack_from("<H", data, pe + 20)
    sec = pe + 24 + opt_size
    for i in range(nsec):
        vsize, va, rsize, roff = struct.unpack_from("<IIII", data, sec + 40 * i + 8)
        if va <= rva < va + max(vsize, rsize):
            if rva - va >= rsize:
                raise ExeTableError(f"RVA 0x{rva:X} lies in uninitialised section data")
            return roff + (rva - va)
    raise ExeTableError(f"RVA 0x{rva:X} is in no section")


def read(fmt: str, rva: int, count: int, exe=None) -> tuple:
    """`count` values of struct format `fmt` ('H', 'I', 'i' ...) at RF4S.exe+rva."""
    data = exe_bytes(exe)
    off = rva_to_offset(data, rva)
    size = struct.calcsize("<" + fmt) * count
    if off + size > len(data):
        raise ExeTableError(f"RF4S.exe is too short for {count} x {fmt} at +0x{rva:X}")
    return struct.unpack_from(f"<{count}{fmt}", data, off)
