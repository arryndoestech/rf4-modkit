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

import copy
import json
import pathlib

TOOLKIT = pathlib.Path(__file__).resolve().parent.parent      # the folder holding rf4mod.py
# the placeholder returned while no game is chosen: '<' and '>' can't be in a Windows file
# name, so nothing is ever found under it and nothing can be written there
NO_GAME_BUNDLE = TOOLKIT / "<no game folder chosen>" / "Bundle"


def settings_path() -> pathlib.Path:
    """The toolkit's settings: settings.json in the toolkit's own folder."""
    return TOOLKIT / "settings.json"


_settings_cache = None      # (path, mtime_ns, size, parsed): lists ask per row, re-read on change


def _load_settings() -> dict:
    """The settings as a fresh dict (callers may change it). Parsed once and kept while the
    file is unchanged: big lists ask for a setting per row."""
    global _settings_cache
    p = settings_path()
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
        if _settings_cache is None or _settings_cache[:3] != key:
            _settings_cache = key + (json.loads(p.read_text(encoding="utf-8")),)
        return copy.deepcopy(_settings_cache[3])
    except (OSError, ValueError):
        return {}


def _store_settings(d: dict) -> None:
    global _settings_cache
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1), encoding="utf-8")
    _settings_cache = None                  # same mtime tick + same size must not serve the old


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
PREVIOUS_DIR = "Previous"           # <backups>/Previous/<same folder>/<name>.<date_time>
DEFAULT_PREVIOUS = 0                # previous versions kept per file (settings "backup_previous")


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


SAVE_TO_MODS_SETTING = "save_to_mods"      # Options -> General: saves go to Bundle/00_mods


def save_to_mods() -> bool:
    """Whether saves of game files go to Bundle/00_mods/<name> instead of over the copy the
    game loads now (setting "save_to_mods", off by default): the game's own files stay as
    they are, and the mod is exactly what is in 00_mods."""
    return bool(get_setting(SAVE_TO_MODS_SETTING, False))


def save_targets(names) -> dict | None:
    """Where each game file is SAVED: game_targets (the copy the game loads now), except that
    with save_to_mods() on a file the game loads from outside Bundle/00_mods is written to
    Bundle/00_mods/<name> instead (a copy already in 00_mods is the one the game loads, so
    it is written over). write_game_file moves the game's own loose copy there on the first
    save (adopt_into_mods), so only one copy stays; other same-named copies outside 00_mods
    are hidden by it anyway, so they are not listed under None. Use game_targets to READ."""
    t = game_targets(names)
    if t is None or not save_to_mods():
        return t
    from . import mbundle
    b = find_bundle_dir()
    mods = b / mbundle.MOD_FOLDER
    for n in names:
        if mods not in t[n].parents:
            t[n] = mods / n
        others = [o for o in t[None].get(n, []) if mods in o.parents or o.name != n]
        if others:
            t[None][n] = others
        else:
            t[None].pop(n, None)
    return t


def adopt_into_mods(target) -> bool:
    """With save_to_mods() on, before the FIRST save of Bundle/00_mods/<name>: move the game's
    own loose copy of <name> (the one it loads now, outside 00_mods) there, so the game folder
    keeps one copy of the file instead of an override plus a hidden original. True when a
    file was moved (the caller then backs it up as the original: write_game_file does)."""
    target = pathlib.Path(target)
    if not save_to_mods() or target.exists():
        return False
    from . import mbundle
    b = find_bundle_dir()
    if b is None:
        return False
    mods = b / mbundle.MOD_FOLDER
    if target.parent != mods:
        return False
    hits = mbundle.loose_index(b).get(target.name) or []
    if not hits or mods in (b / hits[0]).parents:
        return False
    src = b / hits[0]
    if not src.is_file():
        return False
    mods.mkdir(parents=True, exist_ok=True)
    src.replace(target)
    return True


def save_path_for(path) -> pathlib.Path:
    """Where a write over `path` should go: Bundle/00_mods/<name> when save_to_mods() is on and
    `path` is a game file outside 00_mods, else `path` itself (the command-line tool's default
    output, the editors' 'write over this file')."""
    path = pathlib.Path(path)
    if not save_to_mods():
        return path
    from . import mbundle
    b = find_bundle_dir()
    if b is None:
        return path
    try:
        rel = path.resolve().relative_to(b.resolve())
    except ValueError:
        return path                                 # not a game file: a file opened from disk
    if rel.parts and rel.parts[0] == mbundle.MOD_FOLDER:
        return path
    return b / mbundle.MOD_FOLDER / path.name


# ---- backups (settings: backup_originals, backup_previous, backup_dir) -------------------- #
def backup_root() -> pathlib.Path | None:
    """The backup folder: the setting "backup_dir", else <game>/ModdingBackup; None without a
    game folder."""
    custom = get_setting("backup_dir")
    if custom:
        return pathlib.Path(custom)
    b = find_bundle_dir()
    return b.parent / BACKUP_DIR if b is not None else None


def keep_originals() -> bool:
    """Save a game file's original (the first time it is overwritten)? Setting "backup_originals",
    off by default (Options -> Advanced)."""
    return bool(get_setting("backup_originals", False))


def keep_previous() -> int:
    """How many previous versions of each game file to keep (0 = none). Setting "backup_previous"."""
    try:
        return max(0, int(get_setting("backup_previous", DEFAULT_PREVIOUS)))
    except (TypeError, ValueError):
        return DEFAULT_PREVIOUS


def _game_rel(target) -> pathlib.Path | None:
    """A game-folder file's path relative to the game folder (Bundle/...), else None."""
    b = find_bundle_dir()
    if b is None:
        return None
    try:
        return pathlib.Path(target).resolve().relative_to(b.parent.resolve())
    except ValueError:
        return None


def backup_path(target) -> pathlib.Path | None:
    """Where the original of a game-folder file is kept (<backups>/<same path>), or None for a
    file outside the game folder."""
    rel, root = _game_rel(target), backup_root()
    return root / rel if rel is not None and root is not None else None


def previous_versions(target) -> list[pathlib.Path]:
    """The kept previous versions of a game-folder file, newest first
    (<backups>/Previous/<same folder>/<name>.<YYYY-MM-DD_HHMMSS_mmm>)."""
    rel, root = _game_rel(target), backup_root()
    if rel is None or root is None:
        return []
    d = root / PREVIOUS_DIR / rel.parent
    if not d.is_dir():
        return []
    name = rel.name + "."
    return sorted((f for f in d.iterdir() if f.is_file() and f.name.startswith(name)
                   and f.name[len(name):][:1].isdigit()), key=lambda f: f.name, reverse=True)


def _keep_previous_copy(target, keep):
    """Copy the current `target` into the previous versions and drop the oldest beyond `keep`."""
    import datetime
    import shutil
    rel, root = _game_rel(target), backup_root()
    if rel is None or root is None:
        return None
    d = root / PREVIOUS_DIR / rel.parent
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")[:-3]   # (ms: names sort in save order)
    dest = d / ("%s.%s" % (rel.name, stamp))
    n = 1
    while dest.exists():                          # two saves in one second
        n += 1
        dest = d / ("%s.%s-%d" % (rel.name, stamp, n))
    shutil.copy2(target, dest)
    for old in previous_versions(target)[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
    return dest


def backup_before_write(target, force_original=False) -> pathlib.Path | None:
    """Before a game-folder file is overwritten: keep its original the first time (when
    keep_originals(), or `force_original` for an action whose Restore needs it), and the current
    file as a previous version (keep_previous() of them, the oldest dropped). Returns the
    original's path when it was saved now, else None."""
    import shutil
    target = pathlib.Path(target)
    if not target.is_file():
        return None
    made = None
    dest = backup_path(target)
    if (keep_originals() or force_original) and dest is not None and not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)
        made = dest
    keep = keep_previous()
    if keep:
        _keep_previous_copy(target, keep)
    return made


def write_game_file(target, blob, force_original=False) -> pathlib.Path | None:
    """Overwrite `target` with `blob` (through a temporary file, so a failed write never
    leaves half a file), backing it up first (backup_before_write). The original's backup
    path when one was made now, else None."""
    target = pathlib.Path(target)
    moved = adopt_into_mods(target)         # 00_mods mode: the game's copy moves, kept as original
    backup = backup_before_write(target, force_original or moved)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".saving")
    tmp.write_bytes(blob)
    tmp.replace(target)
    return backup


def backed_up_files() -> dict:
    """{game file path: {"original": path or None, "previous": [paths, newest first]}} for
    every file with a backup, found by walking the backup folder."""
    root = backup_root()
    b = find_bundle_dir()
    if root is None or b is None or not root.is_dir():
        return {}
    game = b.parent
    out = {}
    prev_root = root / PREVIOUS_DIR
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        try:
            rel = f.relative_to(prev_root)
        except ValueError:
            rel = None
        if rel is None:                            # an original: <backups>/<same path>
            t = game / f.relative_to(root)
            out.setdefault(t, {"original": None, "previous": []})["original"] = f
            continue
        name, sep, stamp = rel.name.rpartition(".")
        if not sep or not stamp[:1].isdigit():
            continue
        t = game / rel.parent / name
        out.setdefault(t, {"original": None, "previous": []})
    for t, e in out.items():
        e["previous"] = previous_versions(t)
    return out


def restore_version(target, source) -> None:
    """Put a backed-up version back over a game file. The file as it is now is kept as a
    previous version first (when previous versions are on), so a restore can be undone."""
    import shutil
    target, source = pathlib.Path(target), pathlib.Path(source)
    if not source.is_file():
        raise OSError("%s is gone" % source)
    blob = source.read_bytes()
    if target.is_file() and keep_previous():
        _keep_previous_copy(target, keep_previous())
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".saving")
    tmp.write_bytes(blob)
    tmp.replace(target)
    shutil.copystat(source, target)


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
