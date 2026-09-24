"""
rf4s_modkit -- a complete modding toolkit library for Rune Factory 4 Special (PC).

This package provides read AND write support for every asset format that ships in
the RF4S `.mbundle` archives, plus the bundle/manifest plumbing needed to install
mods. It is the engine behind the `rf4mod` command-line tool.

Modules
-------
bplist        Muteki binary-plist reader + writer (the keystone format).
mbundle       .mbundle archive: list / extract / in-place patch / append-repack,
              with Manifest.plist synchronisation.
ident         Magic-based file-type identification for all ~45 bundle extensions.
textdb        TEXT / TEXT8 / NLCL game-data archives (item names, dialogue, etc.).
texture       .texture (RES/BNTX) decode -> PNG and encode (same-size BC7/BC3/BC1 or
              raw/RGBA8), plus the BNTX textures embedded in .model files.
bcenc         BC1 / BC3 / BC7 block encoders (numpy-accelerated, pure-Python fallback).
rf4m          .rf4m map container chunk parse + rebuild.
aibn          AIBN monster/NPC behaviour-script disassemble + assemble.
strings_file  Apple-style .strings localisation file parse + write.
map_names     map id -> in-game name / MAP_* file; HUD location-band rules.
minimap       map id -> mini_map_* picture, save-state swaps, placement (rf3MapMiniPos).
res_container RES\\0 / BFRES / BNTX / PSB generic header walker + identifier.

Everything here is grounded in the RF4S.exe loader code (see docs/09-file-formats.md
and docs/15-modding-toolkit.md). Each module names the IDA function it was verified
against.
"""

__version__ = "1.0.0"

__all__ = [
    "bplist",
    "mbundle",
    "ident",
    "textdb",
    "texture",
    "bcenc",
    "rf4m",
    "aibn",
    "strings_file",
    "res_container",
    "map_names",
    "minimap",
]
