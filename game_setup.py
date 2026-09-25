"""
First-run / "Game folder..." window: pick the game copy every tool uses, or make one.

Mods are written into the game's Bundle folder, so a copy of the game is recommended (the
window says so once) but any install is accepted. This window
  * lets the user pick an install or copy (the folder with RF4S.exe and Bundle),
  * or copies an install to a new folder (the original is only read),
  * unpacks the .mbundle archives (the map editor and the cross-file lookups read the
    unpacked files): straight into a new copy, or in place with delete-as-you-go,
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

COPY_NAME = "Rune Factory 4 Special"


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
               "Couldn't find the game."
        ttk.Label(f, text=head, font=("TkDefaultFont", 10, "bold"), justify="left").pack(anchor="w")
        ttk.Label(f, justify="left", wraplength=520, text=(
            "\nEvery tool in the toolkit reads and writes this game folder. You can switch to "
            "another one, or make a new copy of the game (about 5 GB of disk space)."
            if current else
            "\nModding changes the game's files, so it's best to work on a copy of the game "
            "and keep your Steam install as it is.\n\n"
            "Choose the game folder (the one with RF4S.exe in it), or let the toolkit make a "
            "copy for you. A copy takes about 5 GB of disk space.")).pack(anchor="w")
        ttk.Label(f, foreground="#555", wraplength=520, justify="left", text=(
            "\nWhere is the game? In Steam: Library → right-click Rune Factory 4 Special "
            "→ Manage → Browse local files. That opens the game folder (the one with "
            "RF4S.exe), which is the folder to choose, or the one to copy from.")).pack(anchor="w")
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(16, 0))
        ttk.Button(b, text="Choose another folder..." if current else "Choose the game folder...",
                   command=self.pick).pack(side="left")
        ttk.Button(b, text="Make a copy for me...", command=self.copy).pack(side="left", padx=8)
        if current and not gamepaths.is_unpacked(current):
            ttk.Button(b, text="Unpack the game files...",
                       command=lambda: self._offer_unpack(current)).pack(side="left")
        ttk.Button(b, text="Close" if current else "Skip for now",
                   command=w.destroy).pack(side="right")
        if not current:
            ttk.Label(f, foreground="#777", wraplength=520, justify="left", text=(
                "You can also skip this for now and choose the game later with "
                "Game folder... in the toolbar.")
            ).pack(anchor="w", pady=(10, 0))
        w.update_idletasks()
        w.grab_set()
        w.focus_force()

    # ---- pick a game folder --------------------------------------------------------- #
    def pick(self):
        d = filedialog.askdirectory(parent=self.win, title="The game folder (the one with RF4S.exe and Bundle)")
        if not d:
            return
        b = gamepaths.as_bundle_dir(d)
        why = gamepaths.problem(b)
        if why:
            messagebox.showerror("Game folder", f"Can't use {d}:\n{why}.", parent=self.win)
            return
        self._save(b)

    # ---- copy an install ------------------------------------------------------------ #
    def copy(self, source=None):
        """Copy a game folder. The .mbundle archives are not copied: they are unpacked
        straight from the original into the copy's Bundle folder (the game runs from those
        folders), so the copy needs no room for both."""
        if source is None:
            d = filedialog.askdirectory(parent=self.win, title="The game to copy (the folder with "
                                        "RF4S.exe)")
            if not d:
                return
            source = d
        sb = gamepaths.as_bundle_dir(source)
        why = gamepaths.problem(sb)
        if why:
            messagebox.showerror("Copy the game", f"Can't copy {source}:\n{why}.", parent=self.win)
            return
        source = sb.parent
        man = mbundle.Manifest(sb / "Manifest.plist")
        packed = [n for n in man.bundle_names() if (sb / n).is_file()]
        to_unpack = packed                              # every archive, voices included
        size, count = _tree_size(source)
        dest_parent = filedialog.askdirectory(parent=self.win, title=f"Where to put the copy "
                                              f"({_human(size)})")
        if not dest_parent:
            return
        dest = pathlib.Path(dest_parent) / COPY_NAME
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
        if not messagebox.askyesno("Make a copy", f"The copy takes {_human(size)} of disk space "
                                   f"({_human(free)} free there).\n\nCopy the game to\n{dest}?",
                                   parent=self.win):
            return
        arch_size = {n: (sb / n).stat().st_size for n in to_unpack}
        skip = {sb / n for n in to_unpack}

        def work(report):
            # 1. the archives are whole (a cut-short download or a damaged file)
            for k, n in enumerate(packed):
                report(k / max(len(packed), 1), f"Checking the game's archives: {n}")
                bad = mbundle.check_archive(sb / n, man)
                if bad:
                    raise RuntimeError(f"the game's files look damaged ({bad}). In Steam: "
                                       "right-click the game > Properties > Installed Files > "
                                       "Verify integrity of game files, then try again")
            # 2. every other file, size-checked
            done = n_files = 0
            for dirpath, _dirs, files in os.walk(source):
                rel = pathlib.Path(dirpath).relative_to(source)
                (dest / rel).mkdir(parents=True, exist_ok=True)
                for fn in files:
                    src = pathlib.Path(dirpath) / fn
                    if src in skip:
                        continue
                    out = dest / rel / fn
                    shutil.copy2(src, out)
                    sz = src.stat().st_size
                    if out.stat().st_size != sz:
                        raise RuntimeError(f"{rel / fn} was not copied completely")
                    n_files += 1
                    done += sz
                    if n_files % 20 == 0:
                        report(done / max(size, 1), f"Copying files ({_human(done)} of {_human(size)})")
            # 3. the archives, unpacked straight from the original
            base = done
            finished = {}

            def prog(bn, k):
                total = max(len(man.files(bn)), 1)
                cur = base + sum(arch_size[x] for x in finished) + arch_size.get(bn, 0) * k / total
                report(cur / max(size, 1), f"Unpacking {bn} into the copy ({k:,} / {total:,} files)")
            for bn in to_unpack:
                prog(bn, 0)
                res = mbundle.unpack(source, _OneBundle(man, bn), voice="both", progress=prog,
                                     dest=dest / "Bundle")
                w, k = res.get(bn, (0, 0))
                if w + k != len(man.files(bn)):
                    raise RuntimeError(f"{bn} was not unpacked completely ({w + k:,} of "
                                       f"{len(man.files(bn)):,} files)")
                finished[bn] = True
            # 4. the result is a complete game folder
            miss = gamepaths.missing(dest / "Bundle")
            if miss:
                raise RuntimeError("the copy is missing " + ", ".join(miss))

        ok, err = _run_with_progress(self.win, "Copying the game", work)
        if not ok:
            messagebox.showerror("Copy the game", f"The copy stopped: {err}.\n\n{dest} holds what "
                                 "was copied so far; delete it and try again.", parent=self.win)
            return
        self._save(gamepaths.as_bundle_dir(dest), copied=True)

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
        msg = f"Using the game in\n{b.parent}"
        if copied:
            msg += "\n\nStart the game from RF4S.exe in that folder to try your mods."
        messagebox.showinfo("Game folder", msg, parent=self.win)
        self.win.destroy()

    def _offer_unpack(self, b):
        """Unpack a folder's archives in place; offer to delete each one as soon as it is
        unpacked, so at most one archive's worth of extra space is used at a time."""
        try:
            man = mbundle.Manifest(b / "Manifest.plist")
            names = [n for n in man.bundle_names() if (b / n).is_file()
                     and n in gamepaths.still_packed(b)]
        except Exception:  # noqa: BLE001
            return
        if not names:
            return
        sizes = {n: (b / n).stat().st_size for n in names}
        total, largest = sum(sizes.values()), max(sizes.values())
        ans = messagebox.askyesnocancel("Unpack the game files", (
            "The map editor and the name lookups read the game's files unpacked "
            f"(about {_human(total)}, a few minutes). The game runs the same with them.\n\n"
            "Delete each archive once it is unpacked?\n\n"
            f"Yes: unpack and delete the archives - needs only about {_human(largest)} free "
            "while it works, and the folder stays the same size.\n"
            f"No: unpack and keep the archives - needs {_human(total)} more.\n"
            "Cancel: don't unpack now."),
            parent=self.win)
        if ans is None:
            return
        need = largest if ans else total
        if shutil.disk_usage(b).free < need * 1.05:
            messagebox.showerror("Unpack", f"Not enough space: unpacking needs {_human(need)} free.",
                                 parent=self.win)
            return
        bad = [m for m in (mbundle.check_archive(b / n, man) for n in names) if m]
        if bad:
            messagebox.showerror("Unpack", "The game's files look damaged:\n" + "\n".join(bad),
                                 parent=self.win)
            return

        def work(report):
            finished = {}

            def prog(bn, k):
                total_files = max(len(man.files(bn)), 1)
                cur = sum(sizes[x] for x in finished) + sizes.get(bn, 0) * k / total_files
                report(cur / max(total, 1), f"Unpacking {bn} ({k:,} / {total_files:,} files)")
            for bn in names:
                prog(bn, 0)
                res = mbundle.unpack(b, _OneBundle(man, bn), voice="both", progress=prog,
                                     delete_packed=bool(ans))
                w, k = res.get(bn, (0, 0))
                if w + k != len(man.files(bn)):
                    raise RuntimeError(f"{bn} was not unpacked completely")
                finished[bn] = True

        ok, err = _run_with_progress(self.win, "Unpacking the game files", work)
        if not ok:
            messagebox.showerror("Unpack", f"Unpacking stopped:\n{err}\n\nRun it again later from "
                                 "Game folder... (it resumes).", parent=self.win)


class _OneBundle:
    """A Manifest view that lists just one bundle, so unpack() handles one archive per call
    (per-archive progress, and delete-as-you-go)."""

    def __init__(self, man, name):
        self._man, self._name = man, name

    def bundle_names(self):
        return [self._name]

    def __getattr__(self, attr):
        return getattr(self._man, attr)


def run(parent, current=None) -> bool:
    """Show the window (modal). True when a game folder was saved."""
    s = _Setup(parent, current)
    parent.wait_window(s.win)
    return s.saved

