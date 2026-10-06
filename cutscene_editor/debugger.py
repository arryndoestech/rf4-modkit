"""The Script debugger panel: attach to the running game, watch its Script VMs, set
breakpoints on statements, pause / continue / step (rf4s_modkit.scriptdbg does the work).

The panel docks below the editor's tabs or floats in its own window (the Dock / Undock
button; the choice is remembered). Switching rebuilds the widgets in the new place: the
attachment, the breakpoints and paused scripts carry over.

A breakpoint is toggled on the Script tab's selected statement (F9 or the right-click menu)
or here. When a VM stops at one, the editor opens that scene and marks the statement.
"""
from __future__ import annotations

import atexit
import tkinter as tk
from tkinter import ttk

from guiutil import Tip, err_text, hint

from rf4s_modkit import script

POLL_MS = 60
DOCK_HEIGHT = 280


def _sync_rows(tree, rows):
    """Make `tree` show `rows` ({iid: values}, in order) touching only what changed, so the
    selection and the scroll position stay."""
    have = tree.get_children()
    for iid in have:
        if iid not in rows:
            tree.delete(iid)
    for i, (iid, vals) in enumerate(rows.items()):
        vals = tuple(str(v) for v in vals)
        if not tree.exists(iid):
            tree.insert("", i, iid=iid, values=vals)
            continue
        if tuple(str(v) for v in tree.item(iid, "values")) != vals:
            tree.item(iid, values=vals)
        if tree.index(iid) != i:
            tree.move(iid, "", i)


class DebuggerPanel:
    def __init__(self, app):
        self.app = app
        self.dbg = None
        self._after = None
        self._stopped = set()           # VM addresses already announced as stopped
        self._vms = []
        self._scene_cache = {}          # (bank, container id) -> the bank's listed scenes
        self.freeze = tk.BooleanVar(master=app.frame, value=True)
        self.docked = app.debugger_docked_setting()
        self.win = None                 # the Toplevel while floating
        self.body = None                # the panel's frame (in the dock or the Toplevel)
        self.visible = False
        app.frame.bind("<Destroy>", self._frame_destroyed, add="+")

    # ---- where the panel lives --------------------------------------------------------- #
    def show(self):
        if self.body is None or not self.body.winfo_exists():
            self._place()
        elif self.docked:
            self.app.dock_debugger(self.body)
        else:
            self.win.deiconify()
            self.win.lift()
        self.visible = True

    def set_docked(self, on):
        if on == self.docked and self.body is not None:
            return
        sel = self.vm_tree.selection() if self.body is not None else ()
        self._unplace()
        self.docked = on
        self.app.set_debugger_docked_setting(on)
        self._place()
        self._refill(sel)

    def _place(self):
        app = self.app
        if self.docked:
            self.body = ttk.Frame(app.debug_dock_parent())
            self._build_ui(self.body, docked=True)
            app.dock_debugger(self.body)
        else:
            w = self.win = tk.Toplevel(app.frame)
            w.title("Cutscene Editor — Script debugger")
            w.geometry("980x620")
            w.protocol("WM_DELETE_WINDOW", self.close)
            self.body = ttk.Frame(w)
            self.body.pack(fill="both", expand=True)
            self._build_ui(self.body, docked=False)
        self.visible = True
        self._refill(())

    def _unplace(self):
        if self.body is None:
            return
        if self.docked:
            self.app.undock_debugger(self.body)
            self.body.destroy()
        elif self.win is not None:
            self.win.destroy()
        self.body = self.win = None

    def _refill(self, sel):
        self.refresh_bps()
        if self.dbg is not None:
            self.attach_btn.config(text="Detach")
            self.status.config(text="attached to RF4S.exe (pid %d)" % self.dbg.g.pid, foreground="#080")
            self._fill_vms()
            if sel and self.vm_tree.exists(sel[0]):
                self.vm_tree.selection_set(sel[0])

    def _build_ui(self, w, docked):
        top = ttk.Frame(w, padding=(4, 2) if docked else 4)
        top.pack(fill="x")
        if docked:
            ttk.Label(top, text="🐞 Script debugger", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.attach_btn = ttk.Button(top, text="Attach to the game", command=self.toggle_attach)
        self.attach_btn.pack(side="left")
        Tip(self.attach_btn, "Connect to the running RF4S.exe (its memory, no native debugger). "
                             "Detach takes every breakpoint out and lets paused scripts go on.")
        if docked:
            xb = ttk.Button(top, text="✕", width=3, command=self.close)
            xb.pack(side="right")
            Tip(xb, "Close the debugger (detaches from the game).")
        db = ttk.Button(top, text="Dock ⤓" if not docked else "Undock ⧉", width=9,
                        command=lambda: self.set_docked(not docked))
        db.pack(side="right", padx=(4, 0))
        Tip(db, "Put the debugger in its own window" if docked else
                "Put the debugger back in the editor, below the tabs")
        cb = ttk.Checkbutton(top, text="Stop game time while a script is stopped", variable=self.freeze,
                             command=self._freeze_changed)
        cb.pack(side="right", padx=4)
        Tip(cb, "While a script waits at a breakpoint or is paused, the in-game clock stands "
                "still (the game's own calendar pause); it runs again on Continue / Detach.")
        self.clock = ttk.Label(top, text="", foreground="#58f")
        self.clock.pack(side="right", padx=8)
        # packed after the right-hand controls so it only gets the space left between them;
        # a long message wraps onto more lines instead of pushing the buttons off the window
        self.status = ttk.Label(top, text="not attached", foreground="#888", width=1, anchor="w")
        self.status.pack(side="left", padx=8, fill="x", expand=True)
        self.status.bind("<Configure>", lambda e: e.widget.config(wraplength=max(e.width - 4, 40)))
        about = ("Breakpoints stop a script just before the statement runs: the script waits there "
                 "until Continue or Step. Only game time stands still -- the rest of the world keeps "
                 "running (you may be able to walk around, monsters move, the camera and music go on). "
                 "Toggle one on the Script tab's selected statement with F9 (not on a RET: a script "
                 "cannot be halted there). A breakpoint on code the game does not run yet waits until "
                 "you save + Reload in game.")
        if docked:
            Tip(self.status, about)
        else:
            hint(w, about, wrap=940).pack(anchor="w", padx=6)
        pw = ttk.PanedWindow(w, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=4, pady=(0, 4) if docked else 4)
        # the scripts and the breakpoints share one tabbed pane; the selected VM beside it
        self.lists = nb = ttk.Notebook(pw)
        pw.add(nb, weight=3)
        vmf, bpf = ttk.Frame(nb, padding=2), ttk.Frame(nb, padding=2)
        nb.add(vmf, text="Script VMs")
        nb.add(bpf, text="Breakpoints")
        self.vm_tree = ttk.Treeview(vmf, columns=("state", "where", "pc"), show="headings",
                                    height=5 if docked else 12)
        for col, lab, wd in (("state", "state", 150), ("where", "bank / scene", 330), ("pc", "pc", 60)):
            self.vm_tree.heading(col, text=lab)
            self.vm_tree.column(col, width=wd, anchor="w", stretch=col == "where")
        bb = ttk.Frame(vmf)
        bb.pack(fill="x", pady=(2, 0), side="bottom")
        self.vm_tree.pack(fill="both", expand=True)
        self.vm_tree.bind("<<TreeviewSelect>>", lambda _e: self._show_vm())
        self.vm_btns = {}
        for text, cmd, tip in (("Pause", self.pause, "Hold the selected script where it is. Only "
                                                     "while it waits (a countdown): an idle script has "
                                                     "nothing to hold, and one waiting for a prompt / "
                                                     "choice / dialogue is inside a statement -- set a "
                                                     "breakpoint after it instead."),
                               ("Continue", self.cont, "Let the selected (stopped) script go on."),
                               ("Step", lambda: self.step(True), "Run one statement (a CALL runs whole) "
                                                                 "and stop at the next."),
                               ("Step into", lambda: self.step(False), "Like Step, but stop inside "
                                                                       "a CALLed subroutine."),
                               ("Show in editor", self.show_in_editor, "Open the statement the "
                                                                        "script stands at.")):
            b = ttk.Button(bb, text=text, command=cmd)
            b.pack(side="left", padx=2)
            Tip(b, tip)
            self.vm_btns[text] = b
        self.bp_tree =ttk.Treeview(bpf, columns=("where", "stmt", "hits"), show="headings",
                                    height=5 if docked else 12)
        for col, lab, wd in (("where", "bank @pc", 160), ("stmt", "statement", 300), ("hits", "hits", 50)):
            self.bp_tree.heading(col, text=lab)
            self.bp_tree.column(col, width=wd, anchor="w", stretch=col == "stmt")
        bb2 = ttk.Frame(bpf)
        bb2.pack(fill="x", pady=(2, 0), side="bottom")
        self.bp_tree.pack(fill="both", expand=True)
        self.bp_tree.bind("<Double-Button-1>", lambda _e: self._goto_bp())
        for text, cmd, tip in (("Toggle on selected statement (F9)", self.app.toggle_breakpoint,
                                "Add or remove a breakpoint on the statement selected in the Script tab."),
                               ("Remove", self.remove_bp, "Remove the selected breakpoint."),
                               ("Remove all", self.remove_all, "Remove every breakpoint.")):
            b = ttk.Button(bb2, text=text, command=cmd)
            b.pack(side="left", padx=2)
            Tip(b, tip)
        # the game variables (FLG_ / REG_) the selected script's scene uses, live
        varf = ttk.Frame(nb, padding=2)
        nb.add(varf, text="Variables")
        self.var_tree = ttk.Treeview(varf, columns=("name", "value", "where", "first"), show="headings",
                                     height=5 if docked else 12)
        for col, lab, wd in (("name", "variable", 240), ("value", "value", 80),
                             ("where", "bits", 130), ("first", "used at", 70)):
            self.var_tree.heading(col, text=lab)
            self.var_tree.column(col, width=wd, anchor="w", stretch=col == "name")
        vb = ttk.Frame(varf)
        vb.pack(fill="x", pady=(2, 0), side="bottom")
        self.var_tree.pack(fill="both", expand=True)
        # double-clicks counted here, not by Tk: Tk reports a 3rd quick click as another
        # double-click, which flipped a flag straight back; here clicks 2, 4, 6 ... are
        self.var_tree.bind("<Button-1>", self._var_click, add="+")
        self._clicks = (0, 0, 0, 0, None)     # (count, time, x, y, row)
        self.var_tree.bind("<Return>", lambda _e: self.set_var())
        self.var_tree.bind("<F2>", lambda _e: self.set_var())
        self._var_edit = None
        Tip(self.var_tree, "Every game variable (FLG_ / REG_) the selected script's scene reads or "
                           "writes, with its value in the game right now. ▶ = the statement the "
                           "script stands at uses it. Double-click the value (or Enter / F2): a "
                           "1-bit flag flips on / off, a number is edited in place (Enter sets it, "
                           "Esc cancels); double-click elsewhere: the first statement using it.")
        for text, cmd, tip in (("Set value…", self.set_var,
                                "Change the selected variable in the running game (a 1-bit flag "
                                "flips on / off)."),
                               ("Set any variable…", lambda: self.set_var(any_var=True),
                                "Change any FLG_ / REG_ variable in the running game, not only the "
                                "ones this scene uses (type to filter the names).")):
            b = ttk.Button(vb, text=text, command=cmd)
            b.pack(side="left", padx=2)
            Tip(b, tip + " A plain memory write: it takes effect at once, and the game's own "
                         "side effects of setting it (achievements) do not run.")
        # the text slots its dialogue codes (＠アイテム０＠, ＠キャラ１＠ ...) print, live
        slotf = ttk.Frame(nb, padding=2)
        nb.add(slotf, text="Text slots")
        self.slot_tree = ttk.Treeview(slotf, columns=("code", "value", "shows", "use", "first"),
                                      show="headings", height=5 if docked else 12)
        for col, lab, wd in (("code", "code", 150), ("value", "value", 80), ("shows", "shows", 200),
                             ("use", "in this scene", 110), ("first", "used at", 70)):
            self.slot_tree.heading(col, text=lab)
            self.slot_tree.column(col, width=wd, anchor="w", stretch=col == "shows")
        self.slot_tree.pack(fill="both", expand=True)
        self.slot_tree.bind("<Double-Button-1>", lambda _e: self._goto_slot())
        Tip(self.slot_tree, "The text slots the ＠…＠ codes in the selected script's dialogue print "
                            "(＠アイテム０＠ = item slot 0, ＠キャラ１＠ = character slot 1, ＠金２＠ = gold "
                            "slot 2 ...) and the ones its SetVar statements fill, with the value in the game "
                            "right now. They are shared by every scene: a slot this scene shows but never "
                            "sets prints what an earlier scene left in it. ▶ = the statement the script "
                            "stands at uses it. Double-click: the first statement using it.")
        right = ttk.Frame(pw, padding=(6, 0))
        pw.add(right, weight=2)
        ttk.Label(right, text="Selected VM", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        dsb = ttk.Scrollbar(right, orient="vertical")
        dsb.pack(side="right", fill="y")
        self.detail = tk.Text(right, width=44, height=8 if docked else 30, font=("Consolas", 9),
                              state="disabled", bg="#15151b", fg="#dcdce4", yscrollcommand=dsb.set,
                              selectbackground="#3a5a8a", inactiveselectbackground="#3a5a8a")
        dsb.config(command=self.detail.yview)
        self._detail_text = None
        self.detail.pack(fill="both", expand=True)

    # ---- attach / poll ---------------------------------------------------------------- #
    def toggle_attach(self):
        if self.dbg is not None:
            self.detach()
            return
        from rf4s_modkit import hotreload, scriptdbg
        if self.app.doc.container is None:
            self.status.config(text="open rf3.mc first", foreground="#b00")
            return
        try:
            # several games running: ask which (the Reload-in-game chooser; the pick is
            # remembered while that game runs, so Reload in game uses the same one)
            pid = hotreload.pick_process(lambda procs: self.app._choose_game(
                procs, "Which one should the script debugger attach to?"))
            if pid is None:
                self.status.config(text="attach cancelled", foreground="#888")
                return
            self.dbg = scriptdbg.ScriptDebugger(self.app.doc.container, pid)
        except Exception as e:  # noqa: BLE001 -- not running, access denied, unknown build
            self.status.config(text="cannot attach: %s" % err_text(e), foreground="#b00")
            self.dbg = None
            return
        self.dbg.user = set(self.app.breakpoints)   # placed in the game each poll
        self.dbg.freeze_clock = self.freeze.get()
        self.attach_btn.config(text="Detach")
        self.status.config(text="attached to %s (pid %d)" % ("RF4S.exe", self.dbg.g.pid), foreground="#080")
        if self.dbg.recovered:
            self.status.config(text="attached; an earlier debugger had not detached -- undone: %s"
                                    % "; ".join(self.dbg.recovered), foreground="#b60")
        atexit.register(self._at_exit)          # closing the program detaches too
        if self.app._refresh_live_text():       # test lines only this game has
            self.app.refresh_scene()
        self._tick()

    def detach(self):
        if self._after is not None:
            try:
                self.app.frame.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        left = []
        dbg, self.dbg = self.dbg, None
        if dbg is not None:
            try:
                left = dbg.detach()
            except Exception as e:  # noqa: BLE001 -- the game may be gone
                left = [err_text(e)]
        try:
            atexit.unregister(self._at_exit)
        except Exception:  # noqa: BLE001
            pass
        self._stopped.clear()
        self.app.debug_current = None
        if self.app.doc.live_lines:             # they came from that game
            self.app.doc.live_lines = {}
            try:
                self.app.refresh_scene()
            except tk.TclError:
                pass
        try:
            self.app.mark_debug()
            self.attach_btn.config(text="Attach to the game")
            if left:
                self.status.config(text="detached -- not everything could be undone (the next "
                                        "attach finishes it): " + "; ".join(left), foreground="#b60")
            else:
                self.status.config(text="detached: the game is as it was", foreground="#888")
            self.clock.config(text="")
        except (tk.TclError, AttributeError):
            pass                                # the window is being closed

    def _at_exit(self):
        """The program ends without the editor having detached (no Destroy event): detach
        now, so the game is left as it was."""
        dbg, self.dbg = self.dbg, None
        if dbg is not None:
            try:
                dbg.detach()
            except Exception:  # noqa: BLE001 -- nothing to report to at exit
                pass

    def _freeze_changed(self):
        if self.dbg is not None:
            self.dbg.freeze_clock = self.freeze.get()

    def close(self):
        """Close the panel (docked: the pane goes away; floating: the window); detaches."""
        self.detach()
        self._unplace()
        self.visible = False

    def _frame_destroyed(self, e):
        if e.widget is self.app.frame:          # the editor closes: let the game go on
            self.detach()

    def _tick(self):
        self._after = None
        if self.dbg is None:
            return
        try:
            if self.app.doc.container is not None:
                self.dbg.c = self.app.doc.container     # undo / redo / reload replace it
            self.dbg.user = set(self.app.breakpoints)
            self._vms = self.dbg.poll()
            pend = set(self.dbg.user_pending)
            if pend != self.app.pending_breakpoints:    # the Script tab shows them dimmed
                self.app.pending_breakpoints = pend
                self.app.mark_debug()
        except Exception as e:  # noqa: BLE001 -- the game closed, a race, ...
            self.status.config(text="lost the game: %s" % err_text(e), foreground="#b00")
            self.detach()
            return
        self._fill_vms()
        self._announce()
        self.clock.config(text="⏸ game time stopped" if self.dbg.clock_frozen else "")
        if self.dbg.mismatch:
            self.status.config(text="attached -- the game runs a different copy of bank(s) %s than "
                                    "the editor shows: save + Reload in game" %
                                    ", ".join(str(b) for b in sorted(self.dbg.mismatch)),
                               foreground="#b60")
        self._after = self.app.frame.after(POLL_MS, self._tick)

    # ---- the lists ----------------------------------------------------------------------- #
    def _where(self, vm):
        from .catalog import bank_title
        if vm.bank is None:
            return "(no bank)"
        return bank_title(self.app.doc.container.banks[vm.bank])

    def _fill_vms(self):
        t = self.vm_tree
        sel = t.selection()
        keep = sel[0] if sel else None
        # rows are updated in place (no flicker, the selection stays)
        rows = {}
        for v in self._vms:
            pc = self.dbg.logical_pc(v)
            state = ("⏸ stopped at breakpoint" if v.addr in self.dbg.parked else
                     "⏸ paused" if v.addr in self.dbg.held else v.state_name())
            dk = self._doc_key(v.bank, pc) if pc is not None and v.bank is not None else None
            shown = "?" if pc is None else ("%04x" % pc if dk is None or dk[1] == pc
                                           else "%04x (game %04x)" % (dk[1], pc))
            rows[str(v.addr)] = (state, self._where(v), shown)
        _sync_rows(t, rows)
        stopped = sum(1 for v in self._vms if v.addr in self.dbg.held)
        self.lists.tab(0, text="Script VMs (%d%s)" % (len(rows), ", %d stopped" % stopped if stopped else ""))
        if keep and t.exists(keep):
            t.selection_set(keep)
        elif self._vms:
            t.selection_set(str(self._vms[0].addr))
        self._show_vm()

    def _selected_vm(self):
        s = self.vm_tree.selection()
        return next((v for v in self._vms if str(v.addr) == s[0]), None) if s else None

    # ---- what the script stands at: the statement, its values, the scene's variables ---- #
    def _code(self, bank):
        """The bank's code as the GAME runs it (the editor's while the game's is unknown)."""
        if bank is None:
            return None
        g = self.dbg.game_bank(bank) if self.dbg is not None else None
        return g if g is not None else bytes(self.app.doc.container.banks[bank].data)

    def _var_name(self, enc):
        c = self.app.doc.container
        off, width, _signed = c.unpack_var(enc)
        emf = getattr(self.app.doc, "emf_vars", None)
        var = emf.by_offset(off) if emf is not None else None
        return var.name if var is not None else "var@%d:%d" % (off, width)

    def _live(self, v, code, off):
        """(expression text, live value text) of the expression at `off`."""
        from rf4s_modkit import scriptdbg
        txt, _ = script.disasm_expr(code, off)
        val, ok = scriptdbg.eval_live(code, off, v.regs, self.dbg.read_var)
        return (txt if txt and txt != "?" else "expr@0x%04x" % off), (str(val) if ok else "?")

    def _statement_lines(self, v, code, st):
        """The statement the script stands at, as the Script tab names it, with the live
        value of every argument / condition and the dialogue text."""
        name = st.mnem if st.op >= 0xFFF0 else script.opcode_mnemonic(st.op)
        out = ["statement @%04x  %s" % (st.pc, name)]
        if st.mnem == "DIALOG":
            text = self.app.doc.text(st.dialog_id) if st.dialog_id is not None else None
            out.append("  line %s: %s" % (st.dialog_id, (text or "(no text)").replace("\n", " / ")))
        for ai, off in enumerate(st.args if st.op < 0xFFF0 else []):
            named = script.arg_repr(code, off, st.op, ai)
            txt, val = self._live(v, code, off)
            shown = named if named == txt else "%s  [%s]" % (named, txt)
            out.append("  arg %d: %s = %s" % (ai + 1, shown, val))
        for off in getattr(st, "expr_refs", None) or []:
            if off is None:
                continue
            txt, val = self._live(v, code, off)
            line = "  %s = %s" % (txt, val)
            if st.mnem in ("BR_Z", "BR_NZ") and val != "?" and st.code_targets:
                jumps = (int(val) == 0) == (st.mnem == "BR_Z")
                line += "   -> %s" % ("jumps to %04x" % st.code_targets[0] if jumps else "goes on to %04x" % (st.pc + st.size))
                out.append(line)
                return out
            out.append(line)
        if st.code_targets:
            out.append("  -> " + ", ".join("%04x" % t for t in st.code_targets if t is not None))
        return out

    def _scene_of(self, bank, pc):
        """The listed scene holding `pc` (cached per bank)."""
        from .browser import scene_rows
        key = (bank, id(self.app.doc.container))
        rows = self._scene_cache.get(key)
        if rows is None:
            rows = self._scene_cache[key] = scene_rows(self.app.doc.container.banks[bank])
        return next((s for s in rows if pc in s.stmts), None)

    def _fill_vars(self, v):
        """The Variables tab: every FLG_ / REG_ the selected script's scene reads or writes,
        with its live value (▶ = the statement it stands at uses it)."""
        rows = {}
        if v is not None and self.dbg is not None and v.bank is not None:
            dk = self._doc_key(v.bank, self.dbg.logical_pc(v))
            pc = dk[1] if dk else None
            code = bytes(self.app.doc.container.banks[v.bank].data)   # the scene's offsets are the editor's
            sc = self._scene_of(v.bank, pc) if pc is not None else None
            here = set()
            encs = {}
            for spc, st in sorted((sc.stmts.items() if sc is not None else [])):
                for off in list(st.args if st.op < 0xFFF0 else []) + list(getattr(st, "expr_refs", None) or []):
                    if off is None:
                        continue
                    for _p, enc in script.expr_var_refs(code, off):
                        encs.setdefault(enc, spc)
                        if spc == pc:
                            here.add(enc)
            c = self.app.doc.container
            for enc, first in sorted(encs.items(), key=lambda kv: self._var_name(kv[0])):
                off, width, _s = c.unpack_var(enc)
                val = self.dbg.read_var(enc)
                rows[str(enc)] = (("▶ " if enc in here else "") + self._var_name(enc),
                                  self.var_text(val, width), "bit %d, %d wide" % (off, width),
                                  "@%04x" % first)
        _sync_rows(self.var_tree, rows)
        self._place_var_edit()
        self.lists.tab(2, text="Variables (%d)" % len(rows))

    def _slot_uses(self, bank_pos, sc, here_pc):
        """{(kind, slot): [first pc, set, shown, here]} for the scene's SetVar writes and the
        ＠ codes of its dialogue lines and choice options (constant slots only)."""
        from rf4s_modkit import textlint
        bank = self.app.doc.container.banks[bank_pos]
        uses = {}

        def use(key, spc, what):
            u = uses.setdefault(key, [spc, False, False, False])
            u[1 if what == "set" else 2] = True
            u[3] = u[3] or spc == here_pc
        for spc, st in sorted(sc.stmts.items()):
            if st.op == 366:                          # SetTextSlotEntries(archive, slot, entries...)
                slot = script.static_arg(bank, st, 1)
                if slot is not None:
                    for k in range(max(1, len(st.args) - 2)):
                        use((13, slot + k), spc, "set")
            elif st.op in textlint.SETVAR_KINDS:
                slot = script.static_arg(bank, st, 0) if st.args else None
                kinds = (0, 3) if st.op == 363 else textlint.SETVAR_KINDS[st.op]   # GetNpcBirthday
                if slot is not None:
                    for k in kinds:
                        use((k, 0 if k == 10 else slot), spc, "set")
            texts = []
            if st.mnem == "DIALOG":
                texts.append(self.app.doc.text(st.dialog_id))
            for i in getattr(st, "items", None) or ():
                texts.append(self.app.doc.text(i))
            for t in texts:
                for tok in textlint.tokens(t or ""):
                    if tok.text == textlint.slot_code(10, 0):      # the child: kind 10, no digit
                        use((10, 0), spc, "shown")
                    elif tok.kind is not None:
                        k = 13 if tok.kind == 14 else tok.kind
                        use((k, tok.slot or 0), spc, "shown")
        return uses

    @staticmethod
    def _slot_shows(kind, val):
        """What a slot value prints, in words ('' when it is just the number)."""
        try:
            if kind == 0:
                if val == 0:
                    return "the player's name"
                from rf4s_modkit import gamenames
                return gamenames.name("characters", val) or ""
            if kind in (1, 11):
                from rf4s_modkit import gamenames
                return gamenames.name("items", val) or ""
            if kind == 2:
                from rf4s_modkit.map_names import map_name
                return map_name(val) or ""
            if kind == 9:
                from rf4s_modkit import emtext
                season, day = divmod(val, 100)
                return "%s %d" % (emtext.SEASONS[season], day) if season in emtext.SEASONS else ""
            if kind == 15:
                return "button icon U+%04X" % (0xE000 + val)
        except Exception:  # noqa: BLE001 -- a name lookup is a display aid only
            pass
        return ""

    def _fill_slots(self, v):
        """The Text slots tab: the slots the selected script's scene sets or shows, live."""
        from rf4s_modkit import textlint
        rows = {}
        if v is not None and self.dbg is not None and v.bank is not None:
            dk = self._doc_key(v.bank, self.dbg.logical_pc(v))
            pc = dk[1] if dk else None
            sc = self._scene_of(v.bank, pc) if pc is not None else None
            if sc is not None:
                from rf4s_modkit.scriptdbg import TEXT_SLOT_COUNTS
                live = self.dbg.text_slots()
                for (kind, slot), (first, sets, shown, here) in sorted(self._slot_uses(v.bank, sc, pc).items()):
                    if slot >= TEXT_SLOT_COUNTS.get(kind, 0):
                        continue                             # past the bank: the game ignores it
                    vals = live.get(kind) if live is not None else None
                    if vals is None:
                        value, shows = "?", ""
                    elif kind == 13:
                        arc = vals[slot]
                        line = (live.get(14) or [0] * 16)[slot]
                        value, shows = "%d / %d" % (arc, line), "text archive %d, line %d" % (arc or 15177, line)
                    else:
                        value, shows = vals[slot], self._slot_shows(kind, vals[slot])
                    rows["%d:%d" % (kind, slot)] = (
                        ("▶ " if here else "") + textlint.slot_code(kind, slot), value, shows,
                        "set + shown" if sets and shown else ("set" if sets else "shown, not set"),
                        "@%04x" % first)
        _sync_rows(self.slot_tree, rows)
        self.lists.tab(3, text="Text slots (%d)" % len(rows))

    def _goto_slot(self):
        s = self.slot_tree.selection()
        v = self._selected_vm()
        if s and v is not None and v.bank is not None:
            first = self.slot_tree.item(s[0], "values")[4]
            self.app.show_statement(v.bank, int(str(first).lstrip("@"), 16))

    def _goto_var(self):
        s = self.var_tree.selection()
        v = self._selected_vm()
        if s and v is not None and v.bank is not None:
            first = self.var_tree.item(s[0], "values")[3]
            self.app.show_statement(v.bank, int(str(first).lstrip("@"), 16))

    @staticmethod
    def _double_click_ms():
        try:
            import ctypes
            return int(ctypes.windll.user32.GetDoubleClickTime()) or 500
        except Exception:  # noqa: BLE001 -- not Windows
            return 500

    def _var_click(self, e):
        """Count the clicks of a quick series on one row; every second one is a double-click
        (the value column: edit / flip it; elsewhere: the first statement using it)."""
        row = self.var_tree.identify_row(e.y)
        n, t, x, y, last = self._clicks
        quick = (row and row == last and 0 <= e.time - t <= self._double_click_ms()
                 and abs(e.x - x) <= 4 and abs(e.y - y) <= 4)
        n = n + 1 if quick else 1
        self._clicks = (n, e.time, e.x, e.y, row)
        if n % 2:
            return
        self.var_tree.selection_set(row)          # the press may not have selected it yet
        act = self.set_var if self.var_tree.identify_column(e.x) == "#2" else self._goto_var
        # after the Treeview's own press handling, which takes the focus (it would close an
        # entry opened here at once)
        self.var_tree.after_idle(act)

    def _var_choices(self):
        """{name: packed ref} of every named FLG_ / REG_ variable."""
        emf = getattr(self.app.doc, "emf_vars", None)
        c = self.app.doc.container
        out = {}
        for var in (emf.variables if emf is not None else ()):
            try:
                out[var.name] = c.pack_var(var.bit_offset, max(1, var.bit_width))
            except Exception:  # noqa: BLE001 -- a field the header masks cannot address
                pass
        return out

    def set_var(self, any_var=False):
        """Change a game variable in the running game: the selected Variables row in place
        (its value cell becomes an entry), or (any_var) any named FLG_ / REG_ variable through
        a dialog with a name picker."""
        from . import dialogs
        if self.dbg is None:
            self.status.config(text="attach to the game first", foreground="#b00")
            return
        if not any_var:
            s = self.var_tree.selection()
            if not s:
                self.status.config(text="select a variable first (or use Set any variable…)",
                                   foreground="#b00")
                return
            self.edit_var_inline(s[0])
            return
        got = dialogs.ask_variable_value(self.body, self, self._var_choices())
        if got is not None:
            name, val = got
            width = self.app.doc.container.unpack_var(self._var_choices()[name])[1]
            self.status.config(text=("%s is %s in the game" if width == 1 else "%s = %s in the game")
                               % (name, self.var_text(val, width)), foreground="#080")
            self._show_vm()

    # ---- in-place editing of a Variables value ---------------------------------------- #
    @staticmethod
    def var_text(val, width):
        """A variable's value as the list shows it: on / off for a 1-bit flag."""
        if val is None:
            return "?"
        return ("on" if val else "off") if width == 1 else val

    def toggle_var(self, enc):
        """Flip a 1-bit variable in the game."""
        name = self._var_name(enc)
        cur = self.dbg.read_var(enc)
        try:
            back = self.dbg.write_var(enc, 0 if cur else 1)
        except Exception as ex:  # noqa: BLE001 -- shown in the status line
            self.status.config(text="%s: %s" % (name, err_text(ex)), foreground="#b00")
            return
        self.status.config(text="%s is %s in the game" % (name, self.var_text(back, 1)), foreground="#080")
        self._show_vm()

    def edit_var_inline(self, iid):
        """Turn the row's value cell into an entry (blue, the value selected): Enter writes
        it to the game, Esc or clicking elsewhere cancels. A 1-bit flag just flips."""
        self.cancel_var_edit()
        enc = int(iid)
        _off, width, signed = self.app.doc.container.unpack_var(enc)
        if width == 1:
            self.toggle_var(enc)
            return
        t = self.var_tree
        t.see(iid)
        t.update_idletasks()
        box = t.bbox(iid, "#2")
        if not box:
            return
        lo, hi = self.dbg.var_range(width, signed)
        e = tk.Entry(t, relief="flat", bd=0, highlightthickness=1, highlightcolor="#2f6fd6",
                     highlightbackground="#2f6fd6", bg="#dbe7ff", fg="#000",
                     selectbackground="#2f6fd6", selectforeground="#fff", insertbackground="#000")
        e.insert(0, t.set(iid, "value"))
        e.select_range(0, "end")
        e.icursor("end")
        e.place(x=box[0], y=box[1], width=box[2], height=box[3])
        e.focus_set()
        e.bind("<Return>", lambda _e: self._commit_var_edit() or "break")
        e.bind("<KP_Enter>", lambda _e: self._commit_var_edit() or "break")
        e.bind("<Escape>", lambda _e: self.cancel_var_edit() or "break")
        e.bind("<FocusOut>", lambda _e: self.cancel_var_edit())
        self._var_edit = (iid, e)
        self.status.config(text="%s: type a value %d..%d, Enter sets it in the game, Esc cancels"
                                % (self._var_name(enc), lo, hi), foreground="#2f6fd6")

    def cancel_var_edit(self):
        ed, self._var_edit = getattr(self, "_var_edit", None), None
        if ed is not None:
            try:
                ed[1].destroy()
            except tk.TclError:
                pass

    def _commit_var_edit(self):
        from guiutil import to_int
        ed = getattr(self, "_var_edit", None)
        if ed is None or self.dbg is None:
            self.cancel_var_edit()
            return
        iid, e = ed
        enc, name = int(iid), self._var_name(int(iid))
        v = to_int(e.get())
        if v is None:
            self.status.config(text="%s: type a whole number (0x.. for hex)" % name, foreground="#b00")
            return
        try:
            back = self.dbg.write_var(enc, v)
        except Exception as ex:  # noqa: BLE001 -- shown in the status line, the entry stays
            self.status.config(text="%s: %s" % (name, err_text(ex)), foreground="#b00")
            return
        self.cancel_var_edit()
        self.var_tree.focus_set()
        self.status.config(text="%s = %s in the game" % (name, v if back is None else back), foreground="#080")
        self._show_vm()

    def _place_var_edit(self):
        """Keep the entry on its row while the list refreshes; the row gone or scrolled out
        of view: cancel."""
        ed = getattr(self, "_var_edit", None)
        if ed is None:
            return
        iid, e = ed
        box = self.var_tree.bbox(iid, "#2") if self.var_tree.exists(iid) else ""
        if not box:
            self.cancel_var_edit()
        else:
            e.place_configure(x=box[0], y=box[1], width=box[2], height=box[3])

    def _show_vm(self):
        v = self._selected_vm()
        self._update_buttons(v)
        try:
            self._fill_vars(v)
        except Exception as e:  # noqa: BLE001 -- a read racing the game; the next poll retries
            self.lists.tab(2, text="Variables (?)")
            self.app.status("variables: %s" % err_text(e))
        try:
            self._fill_slots(v)
        except Exception as e:  # noqa: BLE001 -- same: the next poll retries
            self.lists.tab(3, text="Text slots (?)")
            self.app.status("text slots: %s" % err_text(e))
        d = self.detail
        lines = []
        if v is not None and self.dbg is not None:
            pc = self.dbg.logical_pc(v)
            lines = ["VM        0x%X" % v.addr, "state     %s" % v.state_name(),
                     "bank      %s" % self._where(v), "pc        %s" % ("%04x" % pc if pc is not None else "?")]
            code = self._code(v.bank)
            st = script.decode_statement(code, pc) if code is not None and pc is not None else None
            if st is not None:
                lines += [""] + self._statement_lines(v, code, st)
            lines += ["", "registers"] + ["  reg%d = %d" % (i, r) for i, r in enumerate(v.regs)]
            lines += ["", "frame base %d   stack top %d   wait %d" % (v.frame_base, v.stack_top, v.wait),
                      "", "stack (kind, value), top last"]
            pairs = [(v.stack[i], v.stack[i + 1]) for i in range(0, len(v.stack) - 1, 2)]
            skip = max(0, len(pairs) - 64)            # the top 64 pairs are plenty to read
            if skip:
                lines.append("  ... %d deeper pairs not shown" % skip)
            lines += ["  %3d: (%d, %d)%s" % (i * 2, k, val, "   <- frame" if i * 2 == v.frame_base else "")
                      for i, (k, val) in enumerate(pairs) if i >= skip] or ["  (empty)"]
        text = "\n".join(lines)
        if text == self._detail_text:
            return                              # unchanged: keep the scroll and the selection
        self._detail_text = text
        top = d.yview()[0]
        try:
            sel = (d.index("sel.first"), d.index("sel.last"))
        except tk.TclError:
            sel = None
        d.config(state="normal")
        d.delete("1.0", "end")
        d.insert("1.0", text)
        d.config(state="disabled")
        d.yview_moveto(top)
        if sel:
            d.tag_add("sel", *sel)

    def _announce(self):
        """A VM that just stopped at a breakpoint: show it in the editor."""
        for v in self._vms:
            if v.addr in self.dbg.parked and v.addr not in self._stopped:
                self._stopped.add(v.addr)
                self.lists.select(0)
                self.vm_tree.selection_set(str(v.addr))
                self.show_in_editor(v)
        self._stopped &= set(self.dbg.parked)
        cur = next((self._doc_key(*self.dbg.parked[v.addr]) for v in self._vms if v.addr in self.dbg.parked), None)
        if cur != self.app.debug_current:
            self.app.debug_current = cur
            self.app.mark_debug()
        self.refresh_bps()

    def refresh_bps(self):
        if self.body is None:
            return
        c = self.app.doc.container
        rows = {}
        for bank, pc in sorted(self.app.breakpoints):
            st = script.decode_statement(c.banks[bank].data, pc) if c is not None else None
            name = "" if st is None else (st.mnem if st.op >= 0xFFF0 else script.opcode_mnemonic(st.op))
            bp, why = self.dbg.user_state(bank, pc) if self.dbg is not None else (None, None)
            if why:
                name += "   (waits: %s)" % why
            elif bp is not None and bp.pc != pc:
                name += "   (in the game at %04x until you save + Reload in game)" % bp.pc
            rows["%d:%d" % (bank, pc)] = ("bank %d @%04x" % (bank, pc), name, bp.hits if bp else "")
        _sync_rows(self.bp_tree, rows)
        self.lists.tab(1, text="Breakpoints (%d)" % len(rows))

    # ---- controls -------------------------------------------------------------------------- #
    def _update_buttons(self, v):
        """Only offer what is safe for the selected VM's state."""
        d = self.dbg
        pause_ok = v is not None and d is not None and v.addr not in d.held and d.why_not_pause(v) is None
        held = v is not None and d is not None and d.why_not_step(v) is None
        for name, ok in (("Pause", pause_ok), ("Continue", held), ("Step", held), ("Step into", held),
                         ("Show in editor", v is not None and d is not None and v.bank is not None)):
            b = self.vm_btns.get(name)
            if b is not None:
                b.state(["!disabled"] if ok else ["disabled"])

    def pause(self):
        v = self._selected_vm()
        if v is None or self.dbg is None:
            return
        try:
            self.dbg.pause(v)
        except Exception as e:  # noqa: BLE001
            self.status.config(text=err_text(e), foreground="#b00")

    def cont(self):
        v = self._selected_vm()
        if v is None or self.dbg is None:
            return
        why = self.dbg.why_not_step(v)
        if why:
            self.status.config(text="cannot continue this script: " + why, foreground="#b00")
            return
        self.dbg.resume(v)
        self._stopped.discard(v.addr)

    def step(self, over):
        v = self._selected_vm()
        if v is None or self.dbg is None:
            return
        try:
            note = self.dbg.step(v, over=over)
            self._stopped.discard(v.addr)
        except Exception as e:  # noqa: BLE001
            self.status.config(text="step: %s" % err_text(e), foreground="#b00")
            return
        if note:
            self.status.config(text="step: " + note, foreground="#b60")

    def _doc_key(self, bank, gpc):
        """(bank, the editor's pc) of the game's statement at `gpc` (None when the editor no
        longer has that statement)."""
        dpc = self.dbg.to_doc(bank, gpc) if self.dbg is not None else gpc
        return None if dpc is None else (bank, dpc)

    def show_in_editor(self, v=None):
        v = v or self._selected_vm()
        if v is None or self.dbg is None or v.bank is None:
            return
        key = self._doc_key(v.bank, self.dbg.logical_pc(v))
        if key is None:
            self.status.config(text="the script stands at a statement the editor no longer has "
                                    "(an unsaved edit removed or changed it)", foreground="#b60")
            return
        self.app.show_statement(*key)

    def _goto_bp(self):
        s = self.bp_tree.selection()
        if s:
            bank, pc = (int(x) for x in s[0].split(":"))
            self.app.show_statement(bank, pc)

    def remove_bp(self):
        s = self.bp_tree.selection()
        if s:
            bank, pc = (int(x) for x in s[0].split(":"))
            self.app.set_breakpoint(bank, pc, False)

    def remove_all(self):
        for bank, pc in list(self.app.breakpoints):
            self.app.set_breakpoint(bank, pc, False)

    # the editor calls these when its breakpoint set changes
    def breakpoint_added(self, bank, pc):
        if self.dbg is not None:
            self.dbg.user = set(self.app.breakpoints)   # placed in the game on the next poll
        self.refresh_bps()

    def breakpoint_removed(self, bank, pc):
        if self.dbg is not None:
            self.dbg.user = set(self.app.breakpoints)
        self.refresh_bps()
