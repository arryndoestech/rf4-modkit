"""
First-run / "Game folder..." window: pick the game copy every tool uses, or make one.

The toolkit only works on a COPY of the game outside Steam's folders (mods are written into
the copy's Bundle folder). This window
  * lets the user pick an existing copy (the folder with RF4S.exe and Bundle),
  * or copies the Steam install to a new folder (read-only on the Steam side),
  * then offers to unpack the .mbundle archives (the map editor and the cross-file
    lookups read the unpacked files),
and saves the choice (rf4s_modkit.gamepaths). run() returns True when a folder was saved.
"""
from __future__ import annotations

import os
import pathlib
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from rf4s_modkit import gamepaths, mbundle

COPY_NAME = "Rune Factory 4 Special (modding copy)"


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _tree_size(root: pathlib.Path) -> tuple[int, int]:
    total = count = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
                count += 1
            except OSError:
                pass
    return total, count


def _run_with_progress(parent, title, work) -> tuple[bool, str]:
    """Run work(report) on a thread under a small progress window; report(fraction or None,
    text). Returns (ok, error text)."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.resizable(False, False)
    win.transient(parent)
    win.protocol("WM_DELETE_WINDOW", lambda: None)          # finish, don't abandon
    lbl = ttk.Label(win, text="Starting...", width=70)
    lbl.pack(padx=14, pady=(14, 6), anchor="w")
    bar = ttk.Progressbar(win, length=460, mode="determinate", maximum=1000)
    bar.pack(padx=14, pady=(0, 14))
    q: queue.Queue = queue.Queue()
    result = {}

    def worker():
        try:
            work(lambda frac, text: q.put((frac, text)))
            result["ok"] = True
        except Exception as e:  # noqa: BLE001 - shown to the user
            result["err"] = str(e)
        q.put(None)

    def poll():
        try:
            while True:
                item = q.get_nowait()
                if item is None:
                    win.grab_release()
                    win.destroy()
                    return
                frac, text = item
                if frac is None:
                    if bar["mode"] != "indeterminate":
                        bar.config(mode="indeterminate")
                        bar.start(15)
                else:
                    if bar["mode"] != "determinate":
                        bar.stop()
                        bar.config(mode="determinate")
                    bar["value"] = frac * 1000
                lbl.config(text=text)
        except queue.Empty:
            pass
        win.after(100, poll)

    threading.Thread(target=worker, daemon=True).start()
    win.after(100, poll)
    win.grab_set()
    parent.wait_window(win)
    return bool(result.get("ok")), result.get("err", "")


class _Setup:
    def __init__(self, parent, current):
        self.parent = parent
        self.saved = False
        w = self.win = tk.Toplevel(parent)
        w.title("RF4S Modding Toolkit - game folder")
        w.resizable(False, False)
        if parent.winfo_viewable():
            w.transient(parent)
        w.protocol("WM_DELETE_WINDOW", w.destroy)
        f = ttk.Frame(w, padding=16)
        f.pack(fill="both", expand=True)
        head = ("Game folder in use:\n    %s" % current.parent) if current else \
               "The toolkit could not find the game."
        ttk.Label(f, text=head, font=("TkDefaultFont", 10, "bold"), justify="left").pack(anchor="w")
        ttk.Label(f, justify="left", wraplength=520, text=(
            "\nThe toolkit works on a COPY of Rune Factory 4 Special, never on the Steam "
            "install: your mods are written into the copy's Bundle folder, and you start the "
            "game from the copy (RF4S.exe in it) to try them.\n\n"
            "Pick your copy (the folder with RF4S.exe and Bundle), or let the toolkit make "
            "one from the Steam install (Steam: right-click the game > Manage > Browse local "
            "files shows where it is). The Steam install itself is only read.")).pack(anchor="w")
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(16, 0))
        ttk.Button(b, text="Use my game copy...", command=self.pick).pack(side="left")
        ttk.Button(b, text="Copy the game from Steam...", command=self.copy).pack(side="left", padx=8)
        if current and not gamepaths.is_unpacked(current):
            ttk.Button(b, text="Unpack the game files...",
                       command=lambda: self._offer_unpack(current)).pack(side="left")
        ttk.Button(b, text="Close" if current else "Skip for now",
                   command=w.destroy).pack(side="right")
        if not current:
            ttk.Label(f, foreground="#777", wraplength=520, justify="left", text=(
                "Skip: the toolkit still opens and Open Manifest... works, but the map "
                "editor and name lookups stay empty until a game folder is set.")
            ).pack(anchor="w", pady=(10, 0))
        w.update_idletasks()
        w.grab_set()
        w.focus_force()

    # ---- pick an existing copy ------------------------------------------------------ #
    def pick(self):
        d = filedialog.askdirectory(parent=self.win, title="Your game copy (the folder with RF4S.exe and Bundle)")
        if not d:
            return
        b = gamepaths.as_bundle_dir(d)
        if b is not None and gamepaths.in_steam_library(b):
            if messagebox.askyesno("Steam install", "That is the Steam install, which the toolkit "
                                   "never writes into.\n\nMake a copy of it now?", parent=self.win):
                self.copy(source=b.parent)
            return
        why = gamepaths.problem(b)
        if why:
            messagebox.showerror("Game folder", f"Can't use {d}:\n{why}.", parent=self.win)
            return
        self._save(b)

    # ---- copy the Steam install --------------------------------------------------- #
    def copy(self, source=None):
        if source is None:
            d = filedialog.askdirectory(parent=self.win, title="The Steam install of Rune Factory 4 "
                                        "Special (the folder with RF4S.exe)")
            if not d:
                return
            b = gamepaths.as_bundle_dir(d)
            if b is None or not gamepaths.has_game_files(b):
                messagebox.showerror("Copy the game", f"{d} does not hold the game "
                                     "(no Bundle\\Manifest.plist).", parent=self.win)
                return
            source = b.parent
        source = pathlib.Path(source)
        size, count = _tree_size(source)
        dest_parent = filedialog.askdirectory(parent=self.win, title=f"Where to put the copy "
                                              f"({_human(size)}) - a folder outside Steam's")
        if not dest_parent:
            return
        dest = pathlib.Path(dest_parent) / COPY_NAME
        if gamepaths.in_steam_library(dest):
            messagebox.showerror("Copy the game", "Pick a place outside Steam's folders.", parent=self.win)
            return
        try:
            dest.resolve().relative_to(source.resolve())
            messagebox.showerror("Copy the game", "Pick a place outside the game folder.", parent=self.win)
            return
        except ValueError:
            pass
        if dest.exists() and any(dest.iterdir()):
            if gamepaths.as_bundle_dir(dest) and messagebox.askyesno(
                    "Copy the game", f"{dest} already holds a copy.\n\nUse it as it is?", parent=self.win):
                self._save(gamepaths.as_bundle_dir(dest))
                return
            messagebox.showerror("Copy the game", f"{dest} already exists and is not empty.", parent=self.win)
            return
        free = shutil.disk_usage(dest_parent).free
        if free < size * 1.05:
            messagebox.showerror("Copy the game", f"Not enough space: the copy needs {_human(size)}, "
                                 f"{_human(free)} free there.", parent=self.win)
            return

        def work(report):
            done = n = 0
            for dirpath, _dirs, files in os.walk(source):
                rel = pathlib.Path(dirpath).relative_to(source)
                (dest / rel).mkdir(parents=True, exist_ok=True)
                for fn in files:
                    src = pathlib.Path(dirpath) / fn
                    shutil.copy2(src, dest / rel / fn)
                    n += 1
                    done += src.stat().st_size
                    if n % 20 == 0 or n == count:
                        report(done / max(size, 1), f"Copying {n:,} / {count:,} files "
                                                    f"({_human(done)} of {_human(size)})")

        ok, err = _run_with_progress(self.win, "Copying the game", work)
        if not ok:
            messagebox.showerror("Copy the game", f"The copy stopped:\n{err}\n\n{dest} holds what "
                                 "was copied so far; delete it and try again.", parent=self.win)
            return
        b = gamepaths.as_bundle_dir(dest)
        if b is None:
            messagebox.showerror("Copy the game", "The copy has no Bundle\\Manifest.plist.", parent=self.win)
            return
        self._save(b, copied=True)

    # ---- save + unpack --------------------------------------------------------------- #
    def _save(self, b, copied=False):
        try:
            b = gamepaths.save(b)
        except ValueError as e:
            messagebox.showerror("Game folder", str(e), parent=self.win)
            return
        self.saved = True
        if not gamepaths.is_unpacked(b):
            self._offer_unpack(b)
        msg = f"Using the game copy in\n{b.parent}"
        if copied:
            msg += "\n\nStart the game from RF4S.exe in that folder to try your mods."
        messagebox.showinfo("Game folder", msg, parent=self.win)
        self.win.destroy()

    def _offer_unpack(self, b):
        try:
            man = mbundle.Manifest(b / "Manifest.plist")
            names = [n for n in man.bundle_names()
                     if n not in mbundle.VOICE_BUNDLES.values() and (b / n).is_file()]
        except Exception:  # noqa: BLE001
            return
        size = sum((b / n).stat().st_size for n in names)
        if not names or not messagebox.askyesno("Unpack the game files", (
                "The map editor and the name lookups read the game's files unpacked.\n\n"
                f"Unpack them now? That writes about {_human(size)} into the copy's Bundle folder "
                "(a few minutes). The game runs the same with them. Voice archives stay packed."),
                parent=self.win):
            return
        if shutil.disk_usage(b).free < size * 1.05:
            messagebox.showerror("Unpack", f"Not enough space: unpacking needs {_human(size)}.", parent=self.win)
            return

        def work(report):
            report(None, "Unpacking...")
            mbundle.unpack(b, man, voice="none",
                           progress=lambda bn, k: report(None, f"Unpacking {bn}: {k:,} files"))

        ok, err = _run_with_progress(self.win, "Unpacking the game files", work)
        if not ok:
            messagebox.showerror("Unpack", f"Unpacking stopped:\n{err}\n\nRun it again later from "
                                 "Game folder... (it resumes).", parent=self.win)


def run(parent, current=None) -> bool:
    """Show the window (modal). True when a game folder was saved."""
    s = _Setup(parent, current)
    parent.wait_window(s.win)
    return s.saved

