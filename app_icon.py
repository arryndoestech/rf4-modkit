"""The toolkit's window / taskbar icon: assets/app_icon.png (256 px, transparent) and
assets/app_icon.ico (16..256 px, for Windows title bars and shortcuts), shipped with the
toolkit -- no game file is read.

    import app_icon
    app_icon.prepare()          # before tk.Tk(): Windows then shows our icon in the taskbar
    root = tk.Tk()
    app_icon.apply(root)        # this window and every Toplevel opened after it
"""
from __future__ import annotations

import pathlib
import sys

ASSETS = pathlib.Path(__file__).resolve().parent / "assets"
PNG = ASSETS / "app_icon.png"
ICO = ASSETS / "app_icon.ico"
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


def image():
    """The icon as a square RGBA PIL image, or None (no Pillow / file missing)."""
    try:
        from PIL import Image
        return Image.open(PNG).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None


def apply(root) -> bool:
    """Set the icon on `root` and, as the default, on every later Toplevel. True when set."""
    ok = False
    if sys.platform == "win32" and ICO.is_file():
        try:                                # Windows picks the right size per place from the .ico
            root.iconbitmap(default=str(ICO))
            ok = True
        except Exception:  # noqa: BLE001
            pass
    im = image()
    if im is None:
        return ok
    try:
        from PIL import Image, ImageTk
        photos = [ImageTk.PhotoImage(im.resize((s, s), Image.LANCZOS), master=root) for s in SIZES]
        root.iconphoto(True, *photos)
    except Exception:  # noqa: BLE001 - no Tk image support: the .ico (or the default icon)
        return ok
    _photos[:] = photos
    return True
