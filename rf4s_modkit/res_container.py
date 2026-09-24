r"""
res_container.py -- structural inspector for Nintendo NN containers used by RF4S.

Covers the resource families that the PC port loads VERBATIM and only runs a
pointer-fixup over (BFRES_FixupRelocationPointers, RF4S.exe+0x1CAA00):

    .model   RES\0 wrapper around BFRES  (GfxCTR::Model)
    .texture RES\0 / BNTX                 (handled fully by texture.py)
    .bfskl   FRES                          skeleton / skeletal animation
    .bfmat   FRES                          material
    .bfmts   FRES                          material set
    .bfsha   FSHA                          shader archive
    .psbData PSB\0                         M2 Emote scripted data
    .emtbytes PSB\0                        M2 Emote animation bytes

Full mesh/skeleton/material parsing is out of scope (it is stock NN BFRES -- use
the community BFRES documentation / Switch-Toolbox for that). What this module
DOES provide for modding is: identify the exact container, locate the relocation
table, enumerate the 4-char sub-block tags present, and report sizes -- enough to
validate that a replacement file is the right type and shape before you inject it
via a loose file or bundle repack.

Relocation-table start (verified, BFRES_GetRelocationTableStart +0x1CA9B0):
  header[0] == 'R' (RES\0)  -> offset stored at +0x10
  otherwise (FRES/BNTX/...)  -> offset stored at +0x18
"""
from __future__ import annotations

import pathlib
import struct
import re

KNOWN_MAGICS = {
    b"RES\x00": "RES (NN resource container; .model or .texture)",
    b"BNTX": "BNTX (NN texture)",
    b"FRES": "FRES (NN BFRES; .bfskl/.bfmat/.bfmts)",
    b"FSHA": "FSHA (NN BFRES shader; .bfsha)",
    b"PSB\x00": "PSB (M2 Emote scripted data; .psbData/.emtbytes)",
}

# Common NN BFRES sub-block tags worth surfacing.
_SUBTAGS = [b"FMDL", b"FSKL", b"FVTX", b"FSHP", b"FMAT", b"FSKA", b"FSHU",
            b"FTXP", b"FVIS", b"FSCN", b"FMAA", b"BNTX", b"PIXL", b"DESC",
            b"TEXT", b"_DIC", b"_RLT", b"STRG", b"GRSN", b"GRSC"]


class ResError(Exception):
    pass


def identify_magic(data: bytes) -> str | None:
    for magic, desc in KNOWN_MAGICS.items():
        if data[:len(magic)] == magic:
            return desc
    return None


def inspect(data: bytes) -> dict:
    """Return a structural summary of an NN container."""
    magic = identify_magic(data)
    if magic is None:
        raise ResError(f"not a known NN container (magic={data[:4]!r})")
    is_res = data[0:1] == b"R"
    reloc_field = 0x10 if is_res else 0x18
    reloc_off = None
    if len(data) >= reloc_field + 4:
        reloc_off = struct.unpack_from("<I", data, reloc_field)[0]

    # Enumerate which known sub-block tags appear, with first offset + count.
    found = {}
    for tag in _SUBTAGS:
        idx = data.find(tag)
        if idx >= 0:
            cnt = len(re.findall(re.escape(tag), data))
            found[tag.decode("latin1").rstrip("\x00")] = {"first_off": idx, "count": cnt}

    return {
        "magic": magic,
        "size": len(data),
        "reloc_table_field": reloc_field,
        "reloc_table_offset": reloc_off,
        "subblocks": found,
    }


def load(path) -> dict:
    return inspect(pathlib.Path(path).read_bytes())


def summary(data: bytes) -> str:
    info = inspect(data)
    tags = ", ".join(f"{k}x{v['count']}" for k, v in info["subblocks"].items()) or "(none)"
    rel = info["reloc_table_offset"]
    rel_s = f"0x{rel:X}" if rel is not None else "?"
    return (f"{info['magic']}\n"
            f"  size            : {info['size']:,} bytes\n"
            f"  reloc table @   : {rel_s}  (offset field +0x{info['reloc_table_field']:X})\n"
            f"  sub-blocks      : {tags}")
