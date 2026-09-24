r"""
mbundle.py -- RF4S `.mbundle` archive read / extract / patch / repack.

A `.mbundle` is a Muteki binary plist whose root is a dict
`{ "relative/filename": <data blob>, ... }` (see bplist.py). Six ship with the
game: bundleMain (4.7 GB), bundleMuteki, bundlePatch1, bundlePatch2,
bundleVoiceEN, bundleVoiceJP.

How the game finds files (verified in IDA -- see docs/15-modding-toolkit.md):

  * `Manifest.plist` holds, per bundle, a `files` dict mapping each filename to
    `{ "size": N, "offset": M }`. At boot `BundleManager_LoadManifest`
    (+0x225D10) opens every bundle via `MFBundle_Open(path, 0, 0, tocDict)` --
    the `preloadedTOC` path -- so the runtime reads each file's {size, offset}
    FROM THE MANIFEST, not from the bundle's own embedded bplist TOC.
  * `MFBundle_OpenEntry` (+0x98630) then just seeks to `offset` and reads `size`
    bytes out of the .mbundle. No alignment, no checksum.
  * File resolution (`MFFileManager::fileExistsAtPath`, vtable slot 052 ->
    +0x96570) iterates the mounted filesystem/bundle list and returns the FIRST
    match. Loose-directory filesystems are mounted ahead of the archives, so a
    loose file on disk shadows the bundled copy.

Practical consequences for this module:

  * To change a file, you must keep the Manifest entry in sync. The bundle's own
    embedded bplist TOC is ignored at runtime when a manifest entry exists.
  * `patch_inplace`  -- overwrite bytes when the new size <= old size. O(1) write,
    updates the manifest size. Safest for quick tweaks.
  * `append_repack`  -- append new/replacement blobs at the end of the .mbundle and
    repoint the manifest. O(size of changes), works even on the 4.7 GB bundle.
  * `rebuild_from_dir` -- write a brand-new clean .mbundle + matching manifest TOC
    from a directory tree. O(total size); use for small bundles.

But the recommended install method for most mods is LOOSE FILES (see
install_loose), which needs no bundle/manifest edits at all.
"""
from __future__ import annotations

import pathlib
import shutil

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
            data = self.path.read_bytes()
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
                dest = out_dir / safe
                dest.parent.mkdir(parents=True, exist_ok=True)
                f.seek(off)
                dest.write_bytes(f.read(size))
                n += 1
                if progress and n % 500 == 0:
                    progress(n)
        return n


# --------------------------------------------------------------------------- #
# Mutating operations (require a Manifest to stay runtime-correct)
# --------------------------------------------------------------------------- #
def patch_inplace(bundle_path, manifest: Manifest, filename: str, new_bytes: bytes,
                  *, allow_grow=False) -> dict:
    """
    Overwrite an existing file's bytes in place. The default refuses to grow the
    file (which would corrupt the bundle); pass allow_grow=False normally.

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
    if len(new_bytes) > old_size and not allow_grow:
        raise MbundleError(
            f"new size {len(new_bytes)} > old size {old_size} for {filename!r}; "
            f"use append_repack (in-place can only shrink-or-equal)")
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
    is written). The bundle's embedded bplist TOC becomes stale but is unused at
    runtime; tools should read this bundle WITH the manifest afterwards.

    Returns {filename: {size, offset}} for the appended entries. Updates `manifest`
    in memory -- call manifest.save() to persist.
    """
    bundle_path = pathlib.Path(bundle_path)
    bname = bundle_path.name
    files = manifest.files(bname)
    written = {}
    with open(bundle_path, "ab") as f:
        for name, blob in replacements.items():
            cur = f.tell()
            if align > 1 and cur % align:
                pad = align - (cur % align)
                f.write(b"\x00" * pad)
                cur += pad
            f.write(blob)
            manifest.set_entry(bname, name, len(blob), cur)
            written[name] = {"size": len(blob), "offset": cur}
    return written


def rebuild_from_dir(src_dir, out_bundle, manifest: "Manifest | None" = None,
                     bundle_name: "str | None" = None) -> dict:
    """
    Build a fresh, clean .mbundle from every file under src_dir (recursively).
    Filenames are stored relative to src_dir with forward slashes. Produces a
    self-consistent embedded bplist TOC, and -- if a Manifest + bundle_name are
    given -- replaces that bundle's manifest TOC with fresh {size, offset} entries
    (call manifest.save() to persist).

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
            manifest.bundles.append(entry)
        entry["files"] = dict(toc)
    return toc


# --------------------------------------------------------------------------- #
# Loose-file install (recommended, no bundle/manifest edits)
# --------------------------------------------------------------------------- #
def install_loose(game_root, filename: str, src_file) -> pathlib.Path:
    """
    Install a modded asset as a LOOSE FILE that the engine will load in preference
    to the bundled copy. The engine mounts loose-directory filesystems ahead of the
    .mbundle archives and takes the first match, so a file at <game_root>/<filename>
    (and, as a fallback, <game_root>/Bundle/<filename>) shadows the packed version.

    `filename` is the bundle-relative path (e.g. "ui/foo.minterface" or just
    "Foo.texture"). Returns the path written.
    """
    game_root = pathlib.Path(game_root)
    safe = filename.replace("\\", "/").lstrip("/")
    dest = game_root / safe
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_file, dest)
    return dest
