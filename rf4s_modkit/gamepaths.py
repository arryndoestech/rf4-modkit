"""
Where the game copy is -- the one lookup every tool uses.

Mods are written into the game's Bundle folder, so working on a copy of the game is
recommended, but any install works. The Bundle folder -- the one holding Manifest.plist --
is found in this order:

  1. the folder saved in the toolkit's settings (the GUI asks for it once, or
     `rf4mod.py game <folder>` sets it);
  2. the nearest Bundle folder above the toolkit (the toolkit unpacked anywhere inside
     the game copy: <game>\\tools\\modding, <game>\\rf4s-modkit, <game>\\rf4s-modkit\\rf4s-modkit);
  3. the RF4S_BUNDLE environment variable.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

TOOLKIT = pathlib.Path(__file__).resolve().parent.parent      # the folder holding rf4mod.py
ENV_VAR = "RF4S_BUNDLE"
SEARCH_UP = 4                                                 # parent levels searched in step 2
# where step 2 looked before this module existed (<toolkit>\..\..\Bundle); used as the
# placeholder path when nothing is found, so callers keep working with "not there"
LEGACY_BUNDLE = TOOLKIT.parent.parent / "Bundle"


def settings_path() -> pathlib.Path:
    if sys.platform == "win32":
        base = pathlib.Path(os.environ.get("APPDATA") or pathlib.Path.home() / "AppData" / "Roaming")
        return base / "RF4S Modding Toolkit" / "settings.json"
    base = pathlib.Path(os.environ.get("XDG_CONFIG_HOME") or pathlib.Path.home() / ".config")
    return base / "rf4s-modkit" / "settings.json"


def _load_settings() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _store_settings(d: dict) -> None:
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1), encoding="utf-8")


# ---- checks ------------------------------------------------------------------------ #
def as_bundle_dir(path) -> pathlib.Path | None:
    """The Bundle folder for `path` = the game folder, its Bundle folder, Manifest.plist or
    RF4S.exe; None when there is no Manifest.plist there."""
    if not path:
        return None
    p = pathlib.Path(path).expanduser()
    if p.is_file():
        p = p.parent
    for c in (p, p / "Bundle"):
        if (c / "Manifest.plist").is_file():
            return c.resolve()
    return None


def has_game_files(bundle_dir) -> bool:
    """Manifest.plist plus the game's data: packed .mbundle archives or unpacked folders."""
    b = pathlib.Path(bundle_dir)
    return (b / "Manifest.plist").is_file() and (
        any(b.glob("*.mbundle")) or (b / "bundleMain").is_dir() or (b / "extracted").is_dir())


def is_unpacked(bundle_dir) -> bool:
    """True when the archives are also unpacked into folders (the map editor, cross-file
    lookups and the cutscene editor's names read those)."""
    b = pathlib.Path(bundle_dir)
    return (b / "bundleMain").is_dir() or (b / "extracted").is_dir()


def problem(bundle_dir) -> str | None:
    """Why this Bundle folder can't be used, or None when it is fine."""
    if bundle_dir is None:
        return "no Manifest.plist there -- pick the game folder (the one with RF4S.exe and Bundle)"
    if not has_game_files(bundle_dir):
        return "Manifest.plist is there but none of the game's .mbundle archives"
    return None


# ---- lookup ------------------------------------------------------------------------ #
def candidates() -> list[tuple[str, pathlib.Path]]:
    """(where it came from, Bundle folder) in lookup order, only ones that exist."""
    out = []
    saved = as_bundle_dir(_load_settings().get("bundle_dir"))
    if saved:
        out.append(("saved setting", saved))
    for up in list(TOOLKIT.parents)[:SEARCH_UP]:
        b = as_bundle_dir(up / "Bundle")
        if b:
            out.append(("found above the toolkit", b))
            break
    env = as_bundle_dir(os.environ.get(ENV_VAR))
    if env:
        out.append((ENV_VAR, env))
    return out


_cached = False
_found: pathlib.Path | None = None


def find_bundle_dir(refresh: bool = False) -> pathlib.Path | None:
    """The first usable Bundle folder (see the module docstring), or None."""
    global _cached, _found
    if refresh or not _cached:
        _found = next((b for _src, b in candidates() if problem(b) is None), None)
        _cached = True
    return _found


def bundle_dir() -> pathlib.Path:
    """find_bundle_dir(), or the old default path (which then simply doesn't exist)."""
    return find_bundle_dir() or LEGACY_BUNDLE


def extracted_dir(bdir=None) -> pathlib.Path:
    """Root of the unpacked files: <Bundle>/extracted if present, else <Bundle> itself
    (unpacked bundles sit next to the archives as <Bundle>/bundleMain/ ...)."""
    b = pathlib.Path(bdir) if bdir else bundle_dir()
    return (b / "extracted") if (b / "extracted").is_dir() else b


def game_file(*parts) -> pathlib.Path:
    """A path inside the Bundle folder, e.g. game_file('bundleMain', 'em.bin')."""
    return bundle_dir().joinpath(*parts)


def save(path) -> pathlib.Path:
    """Remember a game copy for every tool. Raises ValueError when it can't be used."""
    b = as_bundle_dir(path)
    why = problem(b)
    if why:
        raise ValueError(why)
    d = _load_settings()
    d["bundle_dir"] = str(b)
    _store_settings(d)
    find_bundle_dir(refresh=True)
    return b


def get_setting(key, default=None):
    return _load_settings().get(key, default)


def set_setting(key, value) -> None:
    d = _load_settings()
    d[key] = value
    _store_settings(d)


def forget() -> None:
    d = _load_settings()
    d.pop("bundle_dir", None)
    _store_settings(d)
    find_bundle_dir(refresh=True)
