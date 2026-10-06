"""The toolkit's window / taskbar icon: assets/app_icon.png (256 px, transparent) and
assets/app_icon.ico (16..256 px, each size made from the full-size artwork), shipped with the
toolkit -- no game file is read.

    import app_icon
    app_icon.prepare()          # before tk.Tk(): Windows then shows our icon in the taskbar
    root = tk.Tk()
    app_icon.apply(root)        # this window and every Toplevel opened after it

Windows: the toolkit is not DPI-aware, so on a scaled screen (e.g. 200 %) Windows asks Tk for
32 px icons and stretches them -- blurry. apply() therefore loads the .ico at the screen's REAL
pixel sizes (big = 32 x scale, small = 16 x scale) and gives them to each window with
WM_SETICON, so Windows shrinks a sharp icon instead of enlarging a small one.
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
_hicons = {}                           # (big, small) px -> (HICON big, HICON small), kept alive


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


def screen_scale() -> float:
    """The primary screen's scaling (1.0 = 100 %, 2.0 = 200 %); 1.0 when unknown."""
    try:
        import ctypes
        return max(1.0, ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0)
    except Exception:  # noqa: BLE001
        return 1.0


def _icons_for_scale():
    """(HICON big, HICON small) loaded from the .ico at the real pixel sizes, or None."""
    import ctypes
    from ctypes import wintypes
    s = screen_scale()
    big, small = round(32 * s), round(16 * s)
    if (big, small) in _hicons:
        return _hicons[(big, small)]
    user32 = ctypes.windll.user32
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
    hb = user32.LoadImageW(None, str(ICO), IMAGE_ICON, big, big, LR_LOADFROMFILE)
    hs = user32.LoadImageW(None, str(ICO), IMAGE_ICON, small, small, LR_LOADFROMFILE)
    if not hb or not hs:
        return None
    _hicons[(big, small)] = (hb, hs)
    return hb, hs


def _set_native(win) -> bool:
    """WM_SETICON the sharp icons on one Tk window (its top-level frame). True when set."""
    try:
        import ctypes
        icons = _icons_for_scale()
        if icons is None:
            return False
        hwnd = int(win.wm_frame(), 16)
        WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1
        send = ctypes.windll.user32.SendMessageW
        send.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
        send(hwnd, WM_SETICON, ICON_BIG, icons[0])
        send(hwnd, WM_SETICON, ICON_SMALL, icons[1])
        return True
    except Exception:  # noqa: BLE001 - the Tk icon stays
        return False


def apply(root) -> bool:
    """Set the icon on `root` and, as the default, on every later Toplevel. True when set."""
    if sys.platform == "win32" and ICO.is_file():
        try:
            root.iconbitmap(default=str(ICO))           # every window, before it is mapped
        except Exception:  # noqa: BLE001
            pass
        _set_native(root)               # the .ico default above already counts as set

        def mapped(e):
            w = e.widget
            if w is w.winfo_toplevel():
                _set_native(w)
        for cls in ("Tk", "Toplevel"):                   # every window as it appears
            root.bind_class(cls, "<Map>", mapped, add="+")
        return True
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
