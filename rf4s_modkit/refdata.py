"""refdata.py -- resolver for the bundled reference-data files.

The modding folder is SELF-CONTAINED for sharing: the name tables it needs
(char_names.json, monster_species.json, char_models.json,
rf4s_actor_names.json, rf4s_item_names.json) are vendored in
tools/modding/refdata/. A full workspace's legacy locations
(tools/rf4_refdata/ and tools/) are still honoured as fallbacks so the two
copies can't drift silently apart in this repo -- the vendored copy wins.

GAME DATA is never bundled: Bundle/ (the extracted bundleMain with maps,
textures, em.bin/emdeb.bin) must always be supplied by the user from their
own copy of the game.
"""
from __future__ import annotations

import pathlib

_MODDING = pathlib.Path(__file__).resolve().parent.parent   # tools/modding/
_TOOLS = _MODDING.parent                                    # tools/ (may not exist in a share)


def refdata_path(name: str) -> pathlib.Path:
    """Path to a reference-data file: vendored refdata/ first, then the legacy
    workspace locations. Returns the canonical vendored path (possibly absent)
    when nothing is found, so callers keep their own is_file()/except guards."""
    candidates = (
        _MODDING / "refdata" / name,
        _TOOLS / "rf4_refdata" / name,
        _TOOLS / name,
    )
    for p in candidates:
        try:
            if p.is_file():
                return p
        except OSError:
            pass
    return candidates[0]
