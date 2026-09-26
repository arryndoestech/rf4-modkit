"""refdata.py -- resolver for the bundled reference-data files.

The modding folder is SELF-CONTAINED for sharing: the name tables it needs
(char_names.json, monster_species.json, char_models.json,
rf4s_actor_names.json, rf4s_item_names.json) are vendored in
tools/modding/refdata/, and only there. So are the small tables that exist only
inside RF4S.exe (portrait_faces.json; rf4s_exe_tables.json = chest loot, crate
pools, area BGM, extracted by gen_exe_tables_json.py): nothing reads the exe
at run time.

GAME DATA is never bundled: Bundle/ (the extracted bundleMain with maps,
textures, em.bin/emdeb.bin) must always be supplied by the user from their
own copy of the game.
"""
from __future__ import annotations

import pathlib

_MODDING = pathlib.Path(__file__).resolve().parent.parent   # tools/modding/


def refdata_path(name: str) -> pathlib.Path:
    """Path to a reference-data file in the toolkit's refdata/ (possibly absent -- callers
    keep their own is_file()/except guards)."""
    return _MODDING / "refdata" / name
