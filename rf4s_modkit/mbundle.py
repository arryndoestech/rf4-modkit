r"""
mbundle.py -- RF4S `.mbundle` archive read / extract / patch / repack.

A `.mbundle` is a Muteki binary plist whose root is a dict
`{ "relative/filename": <data blob>, ... }` (see bplist.py). Six ship with the
game: bundleMain (4.7 GB), bundleMuteki, bundlePatch1, bundlePatch2,
bundleVoiceEN, bundleVoiceJP.

How the game finds files (verified in IDA):

  * `Manifest.plist` = `{ "bundles": [ {bundleName, files}, ... ] }`; `files` maps
    each filename to `{ "size": N, "offset": M }`. At boot
    `BundleManager_LoadManifest` (RF4S.exe+0x3E5D10) opens every listed bundle via
    `MFBundle_Open(path, 0, 0, filesDict)` (+0x258790) -- the `preloadedTOC` path --
    so the runtime reads each file's {size, offset} FROM THE MANIFEST
    (MFDictionary_GetIntOrDefault, missing key = 0), not from the bundle's own
    embedded bplist TOC. `bundleName` is resolved as a path, so it must carry the
    `.mbundle` extension. (A manifest whose `bundles` is not an array is read as the
    old `{name: filesDict}` layout.)
  * `MFBundle_OpenEntry` (+0x258630) then just seeks to `offset` and reads `size`
    bytes out of the .mbundle. No alignment, no checksum, no hash.
  * File resolution (`MFFileManager::fileExistsAtPath`, vtable slot 052 ->
    +0x256570, via MFFileManager_ResolvePathThroughMounts +0x2557D0) walks the mount
    list in order and takes the FIRST match. `BundleManager_Mount` (+0x256E60)
    appends, and LoadManifest mounts the loose-directory filesystems first and then
    the bundles in manifest order -- so a loose file shadows every bundle, and an
    earlier bundle shadows a later one.
  * WHICH loose folders: the shipped game mounts two -- the storage folder
    (%APPDATA%/Rune Factory 4 Special) and `Bundle/**` (the game log prints
    "Application Root Path: Bundle/**"; the plain game folder is only mounted in a
    mode the shipped game does not use). A root ending in `**` is indexed ONCE at
    startup, recursively, by bare file name (MFFileSystemExtension_Standard vslot 078
    builds name -> path from MFBundle vslot 066's sorted pre-order walk; lookups try
    the full path, then the name, vslot 063). So a file anywhere under Bundle/ --
    any sub-folder -- overrides the packed copy after a game restart; a file next to
    RF4S.exe does NOT. A missing .mbundle is simply not mounted ("could not find
    bundle"), which is why a fully extracted Bundle/<bundleName>/ tree runs too.
    When two loose files share a name, the index is filled from the end of the
    sorted walk, so the path that sorts FIRST wins (the log shows bundleVoiceEN's
    clips replacing bundleVoiceJP's) -- hence install_loose's `00_mods` folder.

Practical consequences for this module:

  * To change a file, you must keep the Manifest entry in sync. The bundle's own
    embedded bplist TOC is ignored at runtime when a manifest entry exists.
  * `patch_inplace`  -- overwrite bytes when the new size <= old size. O(1) write,
    updates the manifest size. Safest for quick tweaks.
  * `append_repack`  -- append new/replacement blobs at the end of the .mbundle and
    repoint the manifest. O(size of changes), works even on the 4.7 GB bundle; the
    embedded TOC is re-emitted after the blobs so the bundle stays a valid bplist.
  * `rebuild_from_dir` -- write a brand-new clean .mbundle + matching manifest TOC
    from a directory tree. O(total size); use for small bundles. A NEW manifest
    entry goes first in `bundles` so its files win over the stock bundles.

But the recommended install method for most mods is LOOSE FILES (see
install_loose), which needs no bundle/manifest edits at all.
"""
from __future__ import annotations

import mmap
import os
import pathlib
import shutil
import struct

from . import bplist


class MbundleError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Manifest.plist
# --------------------------------------------------------------------------- #
class Manifest:
    """Wrapper over Manifest.plist with per-bundle TOC editing."""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.root = bplist.load(self.path)            # eager: no data blobs in manifest
        if not isinstance(self.root, dict) or "bundles" not in self.root:
            raise MbundleError(f"{self.path} is not a recognised Manifest.plist")

    @property
    def bundles(self) -> list:
        return self.root["bundles"]

    def bundle_names(self) -> list[str]:
        return [b.get("bundleName", "?") for b in self.bundles]

    def bundle_entry(self, bundle_name: str) -> dict:
        for b in self.bundles:
            if b.get("bundleName") == bundle_name:
                return b
        raise MbundleError(f"bundle {bundle_name!r} not in manifest "
                           f"(have: {', '.join(self.bundle_names())})")

    def files(self, bundle_name: str) -> dict:
        """The {name: {size, offset}} dict for one bundle."""
        return self.bundle_entry(bundle_name)["files"]

    def find_file(self, filename: str):
        """Return (bundle_name, {size, offset}) for the first bundle holding filename."""
        for b in self.bundles:
            f = b.get("files", {})
            if filename in f:
                return b.get("bundleName"), f[filename]
        return None, None

    def set_entry(self, bundle_name: str, filename: str, size: int, offset: int):
        self.files(bundle_name)[filename] = {"size": int(size), "offset": int(offset)}

    def save(self, out_path=None):
        out = pathlib.Path(out_path) if out_path else self.path
        out.write_bytes(bplist.dumps(self.root))
        return out


# --------------------------------------------------------------------------- #
# Bundle
# --------------------------------------------------------------------------- #
class Bundle:
    """
    Read access to one .mbundle. Filenames + sizes/offsets come from the bundle's
    own embedded bplist TOC by default, or from a Manifest (authoritative at
    runtime) if you pass one.
    """

    def __init__(self, path, manifest: "Manifest | None" = None):
        self.path = pathlib.Path(path)
        self.manifest = manifest
        self._toc: dict[str, tuple[int, int]] = {}     # name -> (offset, size)
        if manifest is not None:
            files = manifest.files(self.path.name)
            for name, meta in files.items():
                self._toc[name] = (int(meta["offset"]), int(meta["size"]))
        else:
            # Memory-map instead of read_bytes(): bundleMain is 4.7 GB and only its TOC
            # objects are touched (data blobs come back as lazy DataRefs).
            with open(self.path, "rb") as f, \
                    mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
                root = bplist.loads(data, lazy_data=True)
            if not isinstance(root, dict):
                raise MbundleError(f"{self.path} root is {type(root).__name__}, expected dict")
            for name, val in root.items():
                if isinstance(val, bplist.DataRef):
                    self._toc[name] = (val.offset, val.size)

    def __len__(self):
        return len(self._toc)

    def names(self) -> list[str]:
        return list(self._toc.keys())

    def info(self, name: str) -> tuple[int, int]:
        """Return (offset, size) for one entry."""
        if name not in self._toc:
            raise MbundleError(f"{name!r} not in {self.path.name}")
        return self._toc[name]

    def read(self, name: str) -> bytes:
        off, size = self.info(name)
        with open(self.path, "rb") as f:
            f.seek(off)
            return f.read(size)

    def extract(self, name: str, out_path) -> pathlib.Path:
        out = pathlib.Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(self.read(name))
        return out

    def extract_all(self, out_dir, prefix: str = "", progress=None) -> int:
        out_dir = pathlib.Path(out_dir)
        n = 0
        with open(self.path, "rb") as f:
            for name, (off, size) in self._toc.items():
                safe = name.replace("\\", "/").lstrip("/")
                if prefix and not safe.startswith(prefix):
                    continue
                dest = _safe_join(out_dir, safe)
                dest.parent.mkdir(parents=True, exist_ok=True)
                f.seek(off)
                dest.write_bytes(f.read(size))
                n += 1
                if progress and n % 500 == 0:
                    progress(n)
        return n


def _safe_join(root: pathlib.Path, rel: str) -> pathlib.Path:
    """root/rel, refusing a bundle-relative name that climbs out of root ('..', drive)."""
    dest = root / rel
    r = root.resolve()
    d = dest.resolve()
    if d != r and r not in d.parents:
        raise MbundleError(f"refusing path {rel!r}: it escapes {root}")
    return dest


# --------------------------------------------------------------------------- #
# Mutating operations (require a Manifest to stay runtime-correct)
# --------------------------------------------------------------------------- #
def patch_inplace(bundle_path, manifest: Manifest, filename: str, new_bytes: bytes,
                  *, allow_grow=False) -> dict:
    """
    Overwrite an existing file's bytes in place. The default refuses to grow the
    file; allow_grow=True permits it only when the grown span overlaps no other
    manifest entry of this bundle (e.g. the last file, or one followed by padding).
    The embedded bplist TOC keeps the old size (the runtime only reads the manifest).

    Returns the new manifest entry. Updates `manifest` in memory -- call
    manifest.save() to persist.
    """
    bundle_path = pathlib.Path(bundle_path)
    bname = bundle_path.name
    files = manifest.files(bname)
    if filename not in files:
        raise MbundleError(f"{filename!r} not in {bname}; use append_repack to add it")
    old = files[filename]
    old_off, old_size = int(old["offset"]), int(old["size"])
    if len(new_bytes) > old_size:
        if not allow_grow:
            raise MbundleError(
                f"new size {len(new_bytes)} > old size {old_size} for {filename!r}; "
                f"use append_repack (in-place can only shrink-or-equal)")
        end = old_off + len(new_bytes)
        for other, meta in files.items():
            o_off, o_size = int(meta["offset"]), int(meta["size"])
            if other != filename and o_size and o_off < end and o_off + o_size > old_off:
                raise MbundleError(f"growing {filename!r} to {len(new_bytes)} bytes would "
                                   f"overwrite {other!r}; use append_repack")
    with open(bundle_path, "r+b") as f:
        f.seek(old_off)
        f.write(new_bytes)
    manifest.set_entry(bname, filename, len(new_bytes), old_off)
    return files[filename]


def append_repack(bundle_path, manifest: Manifest, replacements: dict,
                  *, align: int = 16) -> dict:
    """
    Append modified/new files to the END of the .mbundle and repoint the manifest.
    `replacements` = {filename: bytes}. Works on any bundle size (only the new data
    and the TOC are written; the old blobs stay where they are).

    Each blob is written as a bplist data object, followed by a fresh root dict,
    offset table and trailer, so the file stays a valid bplist whose EMBEDDED TOC
    matches the manifest (a plain append would leave the trailer inside the last
    blob, and the bundle could no longer be listed without --use-manifest). Old
    TOC/trailer bytes become unreferenced slack. If the bundle is not a bplist with
    a dict root, the blobs are appended raw as before (manifest-only).

    Returns {filename: {size, offset}} for the appended entries. Updates `manifest`
    in memory -- call manifest.save() to persist.
    """
    bundle_path = pathlib.Path(bundle_path)
    bname = bundle_path.name
    manifest.files(bname)                  # raises MbundleError if the bundle is not listed
    toc = _read_embedded_toc(bundle_path)
    written = {}
    new_objs: list[tuple[int, str, int]] = []     # (value-object offset, name, payload offset)
    with open(bundle_path, "r+b") as f:
        f.seek(0, 2)
        for name, blob in replacements.items():
            head = bplist._length_prefix(0x4, len(blob)) if toc is not None else b""
            cur = f.tell()
            payload = cur + len(head)
            if align > 1 and payload % align:
                pad = align - (payload % align)
                f.write(b"\x00" * pad)
                cur += pad
                payload += pad
            f.write(head)
            f.write(blob)
            new_objs.append((cur, name, payload))
            manifest.set_entry(bname, name, len(blob), payload)
            written[name] = {"size": len(blob), "offset": payload}
        if toc is not None:
            _append_toc(f, toc, new_objs)
    return written


def _read_embedded_toc(bundle_path: pathlib.Path):
    """(offsets, ref_size, [(name, key_idx, val_idx)]) of a bundle's embedded root dict,
    or None when the file is not a bplist with a dict root."""
    try:
        with open(bundle_path, "rb") as f, \
                mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            bp = bplist.Bplist(data)
            pos = bp.top_object + 8
            marker = data[pos]
            if marker >> 4 != 0xD:
                return None
            pos += 1
            count = marker & 0xF
            if count == 0xF:
                n = 1 << (data[pos] & 0xF)
                count = int.from_bytes(data[pos + 1:pos + 1 + n], "big")
                pos += 1 + n
            krefs = [int.from_bytes(data[pos + 4 * i:pos + 4 * i + 4], "big") for i in range(count)]
            pos += 4 * count
            vrefs = [int.from_bytes(data[pos + 4 * i:pos + 4 * i + 4], "big") for i in range(count)]
            entries = [(bp._resolve(k, True), k, v) for k, v in zip(krefs, vrefs)]
            return list(bp.offsets), bp.ref_size, entries
    except (bplist.BplistError, ValueError, IndexError, struct.error, OSError):
        return None


def _append_toc(f, toc, new_objs) -> None:
    """Write new key strings, a new root dict, offset table and trailer at f's end."""
    offsets, ref_size, entries = toc
    offsets = list(offsets)
    order = [name for name, _k, _v in entries]
    refs = {name: (k, v) for name, k, v in entries}
    for obj_off, name, _payload in new_objs:
        v_idx = len(offsets)
        offsets.append(obj_off)
        if name in refs:
            refs[name] = (refs[name][0], v_idx)
        else:
            f.seek(0, 2)
            k_idx = len(offsets)
            offsets.append(f.tell())
            f.write(bplist.BplistWriter._encode_one_scalar(name))
            refs[name] = (k_idx, v_idx)
            order.append(name)
    f.seek(0, 2)
    root_off = f.tell()
    offsets.append(root_off)
    f.write(bplist._length_prefix(0xD, len(order)))
    f.write(b"".join(refs[n][0].to_bytes(4, "big") for n in order))
    f.write(b"".join(refs[n][1].to_bytes(4, "big") for n in order))
    ot_off = f.tell()
    # 4-byte offsets unless the table sits past 0x3FFFFFFF (bundleMain is 4.7 GB) -- the
    # same rule as the engine's writer; the game reads every width other than 4 as u64.
    osz = 8 if ot_off > 0x3FFFFFFF else 4
    f.write(b"".join(o.to_bytes(osz, "big") for o in offsets))
    f.write(bytes([osz, ref_size]) + struct.pack(">QQQ", len(offsets), root_off - 8, ot_off))


def rebuild_from_dir(src_dir, out_bundle, manifest: "Manifest | None" = None,
                     bundle_name: "str | None" = None) -> dict:
    """
    Build a fresh, clean .mbundle from every file under src_dir (recursively).
    Filenames are stored relative to src_dir with forward slashes. Produces a
    self-consistent embedded bplist TOC, and -- if a Manifest + bundle_name are
    given -- replaces that bundle's manifest TOC with fresh {size, offset} entries
    (call manifest.save() to persist). `bundle_name` is the manifest `bundleName`,
    i.e. the bundle's file name with its `.mbundle` extension. A bundle not yet in
    the manifest is inserted FIRST, because the game mounts bundles in manifest
    order and takes the first match (see the module docstring) -- appended last, its
    files would stay shadowed by bundleMain's copies.

    Returns {filename: {size, offset}}.
    """
    src_dir = pathlib.Path(src_dir)
    out_bundle = pathlib.Path(out_bundle)
    root: dict[str, bytes] = {}
    for p in sorted(src_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(src_dir).as_posix()
            root[rel] = p.read_bytes()

    writer = bplist.BplistWriter(root)
    blob = writer.build()
    out_bundle.write_bytes(blob)

    # Recover each file's payload offset from the writer (id-keyed). Empty files all share
    # id(b"") (CPython interns the empty-bytes singleton), so the id lookup would return one
    # arbitrary shared offset for all of them; harmless (size 0 = the runtime reads no bytes)
    # but misleading, so give empties a fixed in-bounds offset instead of the collided one.
    toc = {}
    for rel, data_bytes in root.items():
        off = writer.data_offsets[id(data_bytes)] if data_bytes else 8
        toc[rel] = {"size": len(data_bytes), "offset": off}

    if manifest is not None and bundle_name is not None:
        entry = None
        for b in manifest.bundles:
            if b.get("bundleName") == bundle_name:
                entry = b
                break
        if entry is None:
            entry = {"bundleName": bundle_name, "files": {}}
            manifest.bundles.insert(0, entry)
        entry["files"] = dict(toc)
    return toc


# --------------------------------------------------------------------------- #
# Loose-file install (recommended, no bundle/manifest edits)
# --------------------------------------------------------------------------- #
MOD_FOLDER = "00_mods"


def bundle_dir(game_root) -> pathlib.Path:
    """The game's Bundle folder for a game root OR the Bundle folder itself (the one
    holding Manifest.plist)."""
    p = pathlib.Path(game_root)
    if (p / "Manifest.plist").is_file() and not (p / "Bundle").is_dir():
        return p
    return p / "Bundle"


def install_loose(game_root, filename: str, src_file, *, folder: str = MOD_FOLDER) -> pathlib.Path:
    """
    Install a modded asset as a LOOSE FILE the engine loads instead of the packed
    copy: <Bundle>/<folder>/<filename>, i.e. `Bundle/00_mods/rf3.mc` by default
    (see the module notes: the game indexes every file under Bundle/ by name at
    startup, ahead of the .mbundle archives -- except the packed patch bundles, which are
    mounted first: see patch_shadows). `00_mods` sorts before the
    `bundle*` folders of a fully extracted game, so it also wins over an extracted
    original. Restart the game to pick it up; delete the folder to uninstall.
    `game_root` may be the game folder or its Bundle folder. Returns the path written.
    """
    base = bundle_dir(game_root) / folder
    safe = filename.replace("\\", "/").lstrip("/")
    dest = _safe_join(base, safe)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_file, dest)
    return dest


def loose_index(game_root) -> dict:
    """{file name, exact case: [paths under Bundle/, the winning one first]} the way the
    game's `Bundle/**` index resolves them (IDB-verified): each folder listing is sorted by raw bytes (case-sensitive: digits <
    upper case < '_' < lower case), sub-folders are walked where they sort, names starting
    with '.' are skipped, and the EARLIEST path of a name wins. Names are keys by their
    exact bytes -- `map_x.rf4m` and `MAP_X.rf4m` are different files to the game, and it
    asks for the exact name, so a copy in another case never overrides anything. Paths are
    relative to the Bundle folder, '/'-separated."""
    root = bundle_dir(game_root)
    out = {}

    def walk(d, rel):
        try:
            names = sorted(os.listdir(d), key=lambda n: n.encode("utf-8", "surrogateescape"))
        except OSError:
            return
        for n in names:
            if n.startswith("."):
                continue
            p = os.path.join(d, n)
            r = n if not rel else rel + "/" + n
            if os.path.isdir(p):
                walk(p, r)
            else:
                out.setdefault(n, []).append(r)
    walk(str(root), "")
    return out


def case_variants(idx, name) -> list:
    """Loose paths whose file name matches `name` except in upper / lower case: files the
    game never loads in place of `name` (its index is case-sensitive)."""
    low = name.lower()
    return [p for n, paths in idx.items() if n != name and n.lower() == low for p in paths]


def overrides(game_root, manifest: "Manifest | None" = None) -> list:
    """Loose files under Bundle/ that replace a packed game file, plus name clashes
    between loose files: [(name, winning path, [other loose paths], bundle or None,
    game name or None)]. With `manifest`, only names the manifest knows are listed and the
    owning bundle is given; the shipped Manifest.plist itself is skipped. A loose file
    whose name matches a game file only when upper / lower case is ignored is listed with
    that game file's exact name as `game name` (the game ignores it: names are
    case-sensitive); otherwise `game name` is None."""
    idx = loose_index(game_root)
    known, known_low = {}, {}
    if manifest is not None:
        for bn in manifest.bundle_names():
            for f in manifest.files(bn):
                base = f.split("/")[-1]
                known.setdefault(base, bn)
                known_low.setdefault(base.lower(), base)
    rows = []
    for name, paths in sorted(idx.items(), key=lambda kv: kv[0].lower()):
        if name == "Manifest.plist":
            continue
        if manifest is not None and name not in known:
            game = known_low.get(name.lower())
            if game is not None:                  # right name, wrong case: never loaded
                rows.append((name, paths[0], paths[1:], known[game], game))
            continue
        rows.append((name, paths[0], paths[1:], known.get(name), None))
    return rows


# The patch bundles are mounted AHEAD of Bundle/** (MageApplication_RegisterAndLoadBundles inserts
# bundlePatch1 then bundlePatch2 at mount index 1, IDB-verified 2026-09-29): final order =
# storage folder, bundlePatch2.mbundle, bundlePatch1.mbundle, Bundle/**, the manifest bundles.
# So while a patch .mbundle exists, no loose file can replace a file it contains.
PATCH_BUNDLES = ("bundlePatch2.mbundle", "bundlePatch1.mbundle")      # mount order


def patch_shadows(game_root, manifest: "Manifest | None" = None) -> dict:
    """{file name: patch bundle} for every file a PACKED patch bundle (bundlePatch1/2.mbundle
    present next to Manifest.plist) contains: a loose copy of that name anywhere under Bundle/
    is ignored by the game while that archive exists. Empty on a fully unpacked install."""
    bdir = bundle_dir(game_root)
    if manifest is None:
        mp = bdir / "Manifest.plist"
        if not mp.is_file():
            return {}
        manifest = Manifest(mp)
    out = {}
    names = set(manifest.bundle_names())
    for bn in PATCH_BUNDLES:                    # bundlePatch2 is mounted first, so it wins
        if bn in names and (bdir / bn).is_file():
            for f in manifest.files(bn):
                out.setdefault(f.split("/")[-1], bn)
    return out


VOICE_BUNDLES = {"en": "bundleVoiceEN.mbundle", "jp": "bundleVoiceJP.mbundle"}


def unpack_dir_name(bundle_name: str) -> str:
    """Folder an unpacked bundle goes to: 'bundleMain.mbundle' -> 'bundleMain' (the
    shipped names; anything without the extension gets '<name>.d')."""
    return bundle_name[:-8] if bundle_name.lower().endswith(".mbundle") else bundle_name + ".d"


def check_archive(path, manifest: "Manifest | None" = None) -> str | None:
    """Why an .mbundle can't be used -- its table of contents doesn't parse, or an entry
    (by its own TOC or the manifest's) runs past the end of the file -- or None if it looks
    whole. Reads only the TOC, so it takes a second or two even for bundleMain."""
    p = pathlib.Path(path)
    try:
        size = p.stat().st_size
        spans = list(Bundle(p)._toc.values())                    # the embedded TOC
        if manifest is not None:
            spans += [(int(m["offset"]), int(m["size"])) for m in manifest.files(p.name).values()]
    except Exception as e:  # noqa: BLE001 - any parse failure means a damaged archive
        return f"{p.name}: its table of contents can't be read ({e})"
    end = max((o + s for o, s in spans), default=0)
    if end > size:
        return f"{p.name} is cut short ({size:,} of {end:,} bytes)"
    return None


def unpack(game_root, manifest: "Manifest", *, voice: str = "none", progress=None,
           dest=None, delete_packed: bool = False) -> dict:
    """Extract every .mbundle the manifest lists into <Bundle>/<bundle name>/ (the
    layout the game also runs from). Files already there with the right size are
    kept, so a second run resumes. `voice` = 'none' (default), 'en', 'jp' or 'both':
    the voice bundles share every file name, and extracted, the one that sorts first
    (EN) always wins whatever the voice setting says -- so only one should be
    extracted, or leave both packed. Returns {bundle: (written, kept)}.

    `dest`: the Bundle folder to unpack INTO (default: the game's own) -- e.g. a new copy,
    so its archives never have to be copied. `delete_packed`: delete each .mbundle as soon
    as it is fully unpacked (the game then runs from the folders; the manifest's missing
    archives are skipped), so at most one archive's worth of extra space is used at once.
    Ignored with `dest`: the source archives are only read."""
    root = bundle_dir(game_root)
    in_place = dest is None                   # (the loop below reuses the name `dest`)
    out_root = root if in_place else pathlib.Path(dest)
    want_voice = {"none": set(), "both": set(VOICE_BUNDLES.values()),
                  "en": {VOICE_BUNDLES["en"]}, "jp": {VOICE_BUNDLES["jp"]}}[voice]
    done = {}
    for bn in manifest.bundle_names():
        if bn in VOICE_BUNDLES.values() and bn not in want_voice:
            continue
        src = root / bn
        if not src.is_file():
            continue
        dest_dir = out_root / unpack_dir_name(bn)
        b = Bundle(src, manifest=manifest)
        wrote = kept = 0
        with open(src, "rb") as f:
            for name, (off, size) in b._toc.items():
                dest = _safe_join(dest_dir, name.replace("\\", "/").lstrip("/"))
                if dest.is_file() and dest.stat().st_size == size:
                    kept += 1
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                f.seek(off)
                dest.write_bytes(f.read(size))
                wrote += 1
                if progress and (wrote + kept) % 500 == 0:
                    progress(bn, wrote + kept)
        done[bn] = (wrote, kept)
        if delete_packed and in_place and wrote + kept == len(b._toc):
            src.unlink()                          # fully unpacked: free its space now
    return done
