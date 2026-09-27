"""The toolkit's window / taskbar icon: the unused 77th trophy (COLLECTION_76, MOBJ type 326),
read from the user's own game copy -- the toolkit ships no game art. Once decoded it is kept
as a PNG next to settings.json, so later starts need no game read; with no game copy and no
cached PNG the windows keep Tk's default icon.

    import app_icon
    app_icon.prepare()          # before tk.Tk(): Windows then shows our icon in the taskbar
    root = tk.Tk()
    app_icon.apply(root)        # this window and every Toplevel opened after it
"""
from __future__ import annotations

import pathlib
import sys

from rf4s_modkit import gamepaths

TEXTURE = "COLLECTION_76.texture"      # rom:/map_obj/COLLECTION_76, archive 17868
BUNDLE = "bundleMain"
APP_ID = "RF4SModdingToolkit"          # taskbar grouping id (Windows)
SIZES = (16, 24, 32, 48, 64, 128, 256)

_photos = []                           # PhotoImages must outlive the call


def prepare():
    """Give the process its own taskbar identity (Windows): without it the taskbar groups the
    windows under python.exe and shows Python's icon whatever the window icon is."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001 - older Windows / no shell32: the default grouping
        pass


def cache_path() -> pathlib.Path:
    return gamepaths.settings_path().with_name("toolkit_icon.png")


def _texture_bytes():
    """COLLECTION_76.texture from the game copy: an unpacked file, else the archive."""
    try:
        bdir = gamepaths.find_bundle_dir()
    except Exception:  # noqa: BLE001
        bdir = None
    if bdir is None:
        return None
    for folder in (gamepaths.extracted_dir(bdir) / BUNDLE, bdir / BUNDLE, bdir / "extracted" / BUNDLE):
        p = folder / TEXTURE
        if p.is_file():
            return p.read_bytes()
    try:
        from rf4s_modkit import mbundle
        man = mbundle.Manifest(bdir / "Manifest.plist")
        name, _meta = man.find_file(TEXTURE)
        if name:
            return mbundle.Bundle(bdir / name, man).read(TEXTURE)
    except Exception:  # noqa: BLE001 - no manifest / archive: no icon
        pass
    return None


def image():
    """The icon as a square RGBA PIL image (trimmed, centred), or None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    cp = cache_path()
    if cp.is_file():
        try:
            return Image.open(cp).convert("RGBA")
        except OSError:
            pass
    data = _texture_bytes()
    if data is None:
        return None
    try:
        from rf4s_modkit import spritequad, texture
        got = spritequad.sprite_image(data, 0)
        im = got[0] if got else texture.decode_to_image(data, frame=0)
        if im is None:
            return None
        im = im.convert("RGBA")
    except Exception:  # noqa: BLE001 - an unreadable texture: no icon
        return None
    box = im.getbbox()
    if box:
        im = im.crop(box)
    side = max(im.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        sq.save(cp)
    except OSError:
        pass                                # a read-only settings folder: decode next time
    return sq


def apply(root) -> bool:
    """Set the icon on `root` and, as the default, on every later Toplevel. True when set."""
    im = image()
    if im is None:
        return False
    try:
        from PIL import Image, ImageTk
        photos = [ImageTk.PhotoImage(im.resize((s, s), Image.LANCZOS), master=root) for s in SIZES]
        root.iconphoto(True, *photos)
    except Exception:  # noqa: BLE001 - no Tk image support: the default icon
        return False
    _photos[:] = photos
    return True
