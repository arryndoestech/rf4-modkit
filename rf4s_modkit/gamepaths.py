"""
Where the game copy is -- the one lookup every tool uses.

Mods are written into the game's Bundle folder, so working on a copy of the game is
recommended, but any install works. The Bundle folder -- the one holding Manifest.plist --
is only ever the one the user chose: the folder saved in the toolkit's settings (the GUI
asks for it on the first start, or `rf4mod.py game <folder>` sets it). Nothing is guessed
from where the toolkit sits or from the environment, so a tool can never pick up a game
the user did not mean.
"""
from __future__ import annotations

import json
import pathlib

TOOLKIT = pathlib.Path(__file__).resolve().parent.parent      # the folder holding rf4mod.py
# the placeholder returned while no game is chosen: '<' and '>' can't be in a Windows file
# name, so nothing is ever found under it and nothing can be written there (the old
# <toolkit>/../../Bundle placeholder was a real game folder when the toolkit sat inside one)
NO_GAME_BUNDLE = TOOLKIT / "<no game folder chosen>" / "Bundle"


def settings_path() -> pathlib.Path:
    """The toolkit's settings: settings.json in the toolkit's own folder."""
    return TOOLKIT / "settings.json"


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


def still_packed(bundle_dir) -> list[str]:
    """The archives the manifest lists that are not unpacked into Bundle/<name>/ yet."""
    from . import mbundle
    b = pathlib.Path(bundle_dir)
    if (b / "extracted").is_dir():                       # the older one-folder layout
        return []
    try:
        names = mbundle.Manifest(b / "Manifest.plist").bundle_names()
    except Exception:  # noqa: BLE001
        return [] if (b / "bundleMain").is_dir() else ["bundleMain.mbundle"]
    return [n for n in names if not _has_files(b / mbundle.unpack_dir_name(n))]


def is_unpacked(bundle_dir) -> bool:
    """True when every archive is unpacked into its folder (the map editor, cross-file
    lookups and the cutscene editor's names read those; modders edit files in place)."""
    return not still_packed(bundle_dir)


def _has_files(d: pathlib.Path) -> bool:
    try:
        return d.is_dir() and any(d.iterdir())
    except OSError:
        return False


def missing(bundle_dir) -> list[str]:
    """What a complete game folder has that this one lacks: RF4S.exe next to Bundle, and
    every archive the game's own Manifest.plist lists -- packed (Bundle/<name>.mbundle) or
    unpacked into its folder (Bundle/<name>/). Empty = complete."""
    from . import mbundle
    b = pathlib.Path(bundle_dir)
    out = [] if (b.parent / "RF4S.exe").is_file() else ["RF4S.exe"]
    try:
        names = mbundle.Manifest(b / "Manifest.plist").bundle_names()
    except Exception:  # noqa: BLE001 - a damaged manifest is itself the finding
        return out + ["a readable Bundle\\Manifest.plist"]
    for n in names:
        if not (b / n).is_file() and not _has_files(b / mbundle.unpack_dir_name(n)):
            out.append("Bundle\\" + n)
    return out


def problem(bundle_dir) -> str | None:
    """Why this Bundle folder can't be used, or None when it is fine."""
    if bundle_dir is None:
        return "no Manifest.plist there -- pick the game folder (the one with RF4S.exe and Bundle)"
    miss = missing(bundle_dir)
    if miss:
        return ("missing " + ", ".join(miss[:4]) + (f" and {len(miss) - 4} more" if len(miss) > 4 else "")
                + " -- is the game fully installed?")
    return None


# ---- lookup ------------------------------------------------------------------------ #
def candidates() -> list[tuple[str, pathlib.Path]]:
    """(where it came from, Bundle folder): the saved choice, when it still exists."""
    saved = as_bundle_dir(_load_settings().get("bundle_dir"))
    return [("saved setting", saved)] if saved else []


_cached = False
_found: pathlib.Path | None = None


def find_bundle_dir(refresh: bool = False) -> pathlib.Path | None:
    """The chosen Bundle folder when it is usable (see the module docstring), or None."""
    global _cached, _found
    if refresh or not _cached:
        _found = next((b for _src, b in candidates() if problem(b) is None), None)
        _cached = True
    return _found


def bundle_dir() -> pathlib.Path:
    """find_bundle_dir(), or a placeholder path that does not exist."""
    return find_bundle_dir() or NO_GAME_BUNDLE


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


# ---- writing game files in place ---------------------------------------------------- #
BACKUP_DIR = "ModdingBackup"        # <game>/ModdingBackup/<same path>: originals, kept once


def game_targets(names) -> dict | None:
    """{file name: path} where each (changed) game file must go for the game to load it:
    over the copy the game loads now (the Bundle/** winner: a Bundle/00_mods override, else
    the unpacked original), or Bundle/00_mods/<name> when the game only has it packed. Also
    {name: [other copies]} under the key None: files the game ignores -- same-named ones
    that sort later, and ones whose name differs only in upper / lower case (the game
    matches names exactly). `names` must be the game's exact names. None without a game
    folder."""
    from . import mbundle
    b = find_bundle_dir()
    if b is None:
        return None
    idx = mbundle.loose_index(b)
    out, others = {}, {}
    for n in names:
        hits = idx.get(n) or []                  # exact case: the game's index is case-sensitive
        out[n] = (b / hits[0]) if hits else (b / mbundle.MOD_FOLDER / n)
        extra = hits[1:] + mbundle.case_variants(idx, n)
        if extra:
            others[n] = [b / h for h in extra]
    out[None] = others
    return out


def backup_path(target) -> pathlib.Path | None:
    """Where backup_once keeps the original of a game-folder file
    (<game>/ModdingBackup/<same path>), or None for a file outside the game folder."""
    b = find_bundle_dir()
    if b is None:
        return None
    try:
        rel = pathlib.Path(target).resolve().relative_to(b.parent.resolve())
    except ValueError:
        return None
    return b.parent / BACKUP_DIR / rel


def backup_once(target) -> pathlib.Path | None:
    """Copy a game-folder file that is about to be overwritten to
    <game>/ModdingBackup/<same path>, the first time only (later saves keep that original).
    The backup's path, or None when nothing was copied."""
    import shutil
    target = pathlib.Path(target)
    dest = backup_path(target)
    if dest is None or not target.is_file() or dest.exists():
        return None                                # outside the game folder, or kept already
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, dest)
    return dest


def write_game_file(target, blob) -> pathlib.Path | None:
    """Overwrite `target` with `blob` (through a temporary file, so a failed write never
    leaves half a file), backing the original up once first. The backup path, or None."""
    target = pathlib.Path(target)
    backup = backup_once(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".saving")
    tmp.write_bytes(blob)
    tmp.replace(target)
    return backup


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
