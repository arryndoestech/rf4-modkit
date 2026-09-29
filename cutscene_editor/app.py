"""CutsceneExplorer: the cutscene editor window (browser | script view + tabs | Inspector)
and every edit it can make. Hosted standalone (`python script_explorer.py`) and by
rf4mod_gui (Cutscenes button, a map's Events tab, the map editor's NPC-spawn markers).

Host API: CutsceneExplorer(parent, reader=None, status_fn=None, focus_bank=None,
focus_entry=None, focus_pc=None); .show_bank(pos, entry_pc=None);
.open_new_scene_dialog(pos, default_type=None); .open_event_manager();
.confirm_discard(action); .unsaved()."""
from __future__ import annotations

import difflib
import pathlib
import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from guiutil import Paned, Tip, later, shortcut_scope
from guiutil import err_text
from rf4s_modkit import bankrelink, mbundle, script, scriptasm, textlint

from . import catalog, dialogs
from .browser import Browser
from .document import ScriptDocument
from .em_window import EventManagerWindow
from .inspector import Inspector
from .render import SceneText
from .tabs import OverviewTab, SourceTab, TriggersTab, count_statements
from .view import ScriptView

TABS = ("Script", "Source", "Triggers", "Overview")


class CutsceneExplorer:
    def __init__(self, parent, reader=None, status_fn=None, focus_bank=None, focus_entry=None,
                 focus_pc=None):
        self.parent = parent
        self.status_fn = status_fn
        self.doc = ScriptDocument(reader)
        self.doc.subscribe(self._doc_changed)
        self.bank_pos = None
        self.bank = None
        self.scene = None
        self._edited_lines = set()         # (locale, line id) edited this session, re-checked on save
        self.sel = None                      # (pc, option)
        self.pad_locales = tk.BooleanVar(value=True)
        self._em_window = None
        self._em_uses = None
        self._em_bank_uses = {}              # bank pos -> (bank bytes, [(entry id | None, ...)])
        self._build()
        if isinstance(parent, (tk.Tk, tk.Toplevel)):
            parent.protocol("WM_DELETE_WINDOW", self._on_close)
        self._share_with_maps()
        if reader is not None:
            self._load()
        if focus_bank is not None:
            self.show_bank(focus_bank, focus_entry)
            if focus_pc is not None:
                later(self.frame, lambda: self.view.focus_pc(focus_pc))

    # ------------------------------------------------------------------ #
    # layout
    # ------------------------------------------------------------------ #
    def _build(self):
        self.frame = ttk.Frame(self.parent)
        self.frame.pack(fill="both", expand=True)
        self._build_toolbar()
        paned = Paned(self.frame, orient="horizontal")
        paned.pack(fill="both", expand=True)
        self.browser = Browser(paned, self)
        paned.add(self.browser, weight=0, minsize=220, width=330)
        mid = ttk.Frame(paned)
        paned.add(mid, weight=4, minsize=300)
        self.nb = ttk.Notebook(mid)
        self.nb.pack(fill="both", expand=True)
        self.view = ScriptView(self.nb, self)
        self.source = SourceTab(self.nb, self)
        self.triggers = TriggersTab(self.nb, self)
        self.overview = OverviewTab(self.nb, self)
        for w, t in zip((self.view, self.source, self.triggers, self.overview), TABS):
            self.nb.add(w, text=t)
        side = ttk.Frame(paned, width=380)
        side.pack_propagate(False)
        paned.add(side, weight=0, minsize=300, width=380)
        self.inspector = Inspector(side, self)
        self.inspector.pack(fill="both", expand=True)
        # the Triggers tab's entry details share the right-hand slot with the Inspector
        from .tabs import TriggerDetail
        self.trigger_detail = TriggerDetail(side, self, self.triggers)
        self.right_pane = "inspector"
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._tab_changed(), add="+")
        sbar = ttk.Frame(self.frame)
        sbar.pack(fill="x", side="bottom")
        # room left in the open bank (64 KiB of bytecode per bank), refreshed with every status
        self.space_lbl = ttk.Label(sbar, anchor="e", padding=(6, 2), font=("Segoe UI", 8))
        self.space_lbl.pack(side="right")
        self.status_lbl = ttk.Label(sbar, anchor="w", padding=(6, 2), font=("Segoe UI", 8))
        self.status_lbl.pack(side="left", fill="x", expand=True)
        self._bindtag = "CutEd%d" % id(self)
        # Ctrl+S / Z / Y / F anywhere in the editor (guiutil.shortcut_scope: both letter
        # cases for Caps Lock, Shift tells redo from undo, later widgets tagged on focus)
        self._retag = shortcut_scope(self.frame, self._bindtag, [
            ("z", lambda e: self.redo() if e.state & 0x0001 else self.undo()),
            ("y", lambda e: self.redo()),
            ("s", lambda e: self.save_all()),
            ("r", lambda e: self.reload_in_game()),
            ("f", lambda e: self.focus_search())],
            home=lambda: getattr(getattr(self, "view", None), "text", None))   # the Script rows
        self.frame.after(self.NAMES_EVERY_MS, self._watch_names)

    NAMES_EVERY_MS = 1000

    def _watch_names(self):
        """Character / map / item names come from the game's text files (gamenames): when a
        saved file changes them, re-title the bank list and redraw the open scene."""
        try:
            if not self.frame.winfo_exists():
                return
        except tk.TclError:
            return
        from rf4s_modkit import gamenames
        gen = gamenames.generation()
        if getattr(self, "_names_gen", None) is None:
            self._names_gen = gen
        elif gen != self._names_gen:
            self._names_gen = gen
            self.names_changed()
        self.frame.after(self.NAMES_EVERY_MS, self._watch_names)

    def names_changed(self):
        self.browser.relabel()
        if self.scene is not None:
            self.view.render(keep_sel=True)
            self.inspector.show(self.sel)
        self.status("Names updated from the game's text files")

    def retag(self, w=None):
        """Tag `w` (default: the whole editor) for the shortcuts right away. Panels that
        rebuild their widgets -- the Inspector on every selection -- call this; anything
        missed still gets the tag when it takes the focus."""
        self._retag(w)

    def _build_toolbar(self):
        bar = ttk.Frame(self.frame, padding=(2, 2))
        bar.pack(fill="x")
        ob = ttk.Button(bar, text="Open rf3.mc…", command=self.open_file)
        ob.pack(side="left")
        Tip(ob, "Open a rf3.mc cutscene container (its rf3mc.<locale> and em.bin are looked "
                "up next to it, then in the loaded game source).")
        mb = ttk.Menubutton(bar, text="Save")
        m = tk.Menu(mb, tearoff=False)
        m.add_command(label="Save changes into the game folder", accelerator="Ctrl+S", command=self.save_all)
        m.add_command(label="Save + reload scenes in the running game", accelerator="Ctrl+R",
                      command=self.reload_in_game)
        m.add_separator()
        m.add_command(label="Save rf3.mc (scenes) as…", command=self.save_script)
        m.add_command(label="Save dialogue (rf3mc.<locale>) as…", command=self.save_text)
        m.add_command(label="Save em.bin (Event Manager) as…", command=self.save_em)
        m.add_separator()
        m.add_command(label="Install as loose files (Bundle\\00_mods)", command=self.install)
        mb["menu"] = m
        mb.pack(side="left", padx=4)
        Tip(mb, "Save (Ctrl+S) writes the changed files -- rf3.mc (scenes), rf3mc.<locale> "
                "(dialogue), em.bin (Event Manager) -- straight over the ones the game loads from "
                "your game folder, without asking; the first time, the originals are copied to "
                "ModdingBackup in the game folder. 'Save … as…' writes a copy elsewhere instead.")
        self.undo_btn = ttk.Button(bar, text="↶", width=3, command=self.undo)
        self.undo_btn.pack(side="left")
        Tip(self.undo_btn, lambda: self._undo_tip("undo"))
        self.redo_btn = ttk.Button(bar, text="↷", width=3, command=self.redo)
        self.redo_btn.pack(side="left")
        Tip(self.redo_btn, lambda: self._undo_tip("redo"))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Label(bar, text="Locale").pack(side="left")
        self.loc = tk.StringVar(value=self.doc.locale)
        lc = ttk.Combobox(bar, textvariable=self.loc, values=catalog.LOCALES, width=5, state="readonly")
        lc.pack(side="left", padx=4)
        lc.bind("<<ComboboxSelected>>", lambda _e: self.set_locale(self.loc.get()))
        Tip(lc, "Which language's dialogue is shown and edited. Line ids are shared by every locale.")
        pc = ttk.Checkbutton(bar, text="new lines in all locales", variable=self.pad_locales)
        pc.pack(side="left", padx=4)
        Tip(pc, "When a new dialogue line is added, give it the same id in every other locale "
                "(untranslated) so it shows everywhere.")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        self.mode = tk.StringVar(value="story")
        for val, text, tip in (("story", "Story", "Readable: who says what, actions in words, "
                                                   "branches as if / go to."),
                               ("code", "Code", "The technical listing (the disassembly).")):
            rb = ttk.Radiobutton(bar, text=text, value=val, variable=self.mode, style="Toolbutton",
                                 command=self._view_mode)
            rb.pack(side="left")
            Tip(rb, tip)
        self.addr = tk.BooleanVar(value=False)
        ac = ttk.Checkbutton(bar, text="addresses", variable=self.addr, command=self._view_mode)
        ac.pack(side="left", padx=4)
        Tip(ac, "Show each statement's byte address in the story view (the code view always has "
                "labels).")
        self.show_ops = tk.BooleanVar(value=False)
        oc = ttk.Checkbutton(bar, text="opcodes", variable=self.show_ops, command=self._view_mode)
        oc.pack(side="left", padx=4)
        Tip(oc, "Show the raw opcode each statement is stored as, in hex (e.g. 0x005; control "
                "ops as 0xFFFC), in both views.")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        nb = ttk.Button(bar, text="New scene…", command=self.ask_new_scene)
        nb.pack(side="left")
        Tip(nb, "Mint a new scene in the open bank: pick when it plays, its keys and its body.")
        ib = ttk.Button(bar, text="＋ Instruction…", command=lambda: self.ask_insert_instruction())
        ib.pack(side="left", padx=(4, 0))
        Tip(ib, "Add any instruction without typing it: pick it from the list (by category, "
                "searchable), fill in its arguments with pickers (characters, maps, items, "
                "flags, choices), check the listing it makes, and insert it after / before the "
                "selected statement. Also: Insert key, right-click in the script, Add before / "
                "Add after in the Inspector.")
        rl = ttk.Button(bar, text="⟳ Reload in game", command=self.reload_in_game)
        rl.pack(side="left", padx=(0, 4))
        Tip(rl, "Ctrl+R: save, then put rf3.mc into the RUNNING game -- no restart, any size. "
                "Refused while a scene plays (let it finish). The new scenes apply from the next "
                "trigger / talk; a room's own scenes are re-read on use. The dialogue text of "
                "the game's language is swapped in too (the game keeps it in memory); em.bin "
                "still needs a restart.")
        eb = ttk.Button(bar, text="Event Manager…", command=self.open_event_manager)
        eb.pack(side="left", padx=4)
        Tip(eb, "em.bin: the conditions ('plays when') and flag effects scenes bridge to.")
        rb = ttk.Button(bar, text="📖 Reference", command=lambda: self.open_reference())
        rb.pack(side="right", padx=(4, 0))               # packed first on the right: rightmost
        Tip(rb, "Look things up: flags & variables (name, id, description), the functions "
                "verified in game, the codes dialogue text can hold, characters, maps and "
                "items -- with the form an argument takes. Double-click copies.")
        self.dirty_lbl = ttk.Label(bar, foreground="#c60", font=("Segoe UI", 8))
        self.dirty_lbl.pack(side="right", padx=6)

    # ------------------------------------------------------------------ #
    # loading
    # ------------------------------------------------------------------ #
    def _load(self):
        try:
            ok = self.doc.load_from_reader()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("rf3.mc", "Could not read rf3.mc: %s" % err_text(e))
            return
        if not ok:
            self.status("rf3.mc was not found in the loaded source — Open rf3.mc…")
            return
        self.browser.rebuild()
        self.status("rf3.mc: %d banks. Pick a scene on the left or search for a line." % len(self.doc.container.banks))
        self._chrome()

    def open_file(self):
        if not self.confirm_discard("open another rf3.mc"):
            return
        f = filedialog.askopenfilename(title="Open rf3.mc", filetypes=[("MYCF script", "*.mc"), ("All", "*.*")])
        if not f:
            return
        try:
            self.doc.load_file(f)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("rf3.mc", err_text(e))
            return
        self.bank = self.scene = self.bank_pos = None
        self.browser.rebuild()
        self._show_scene()
        self.status("Opened %s: %d banks" % (pathlib.Path(f).name, len(self.doc.container.banks)))

    # ------------------------------------------------------------------ #
    # navigation
    # ------------------------------------------------------------------ #
    def show_bank(self, index, entry_pc=None):
        """Open bank `index` (container position) and its scene at `entry_pc` (or the first)."""
        c = self.doc.container
        if c is None or not 0 <= index < len(c.banks):
            return False
        from .browser import scene_rows
        scenes = scene_rows(c.banks[index])
        if not scenes:
            self.open_bank(index)
            return True
        pick = next((s for s in scenes if s.entry_pc == entry_pc), scenes[0])
        self.open_scene(index, pick.entry_pc)
        return True

    def open_bank(self, pos):
        """Show a bank: its first scene, and its triggers."""
        from .browser import scene_rows
        c = self.doc.container
        scenes = scene_rows(c.banks[pos])
        self.bank_pos, self.bank = pos, c.banks[pos]
        self.triggers.show(pos)
        self.browser.reveal(pos)
        if scenes:
            self.open_scene(pos, scenes[0].entry_pc, reveal=False)
        else:
            self.scene = None
            self._show_scene()
            self.nb.select(TABS.index("Triggers"))
            self.status("%s has no scenes yet — New scene… mints the first one" % catalog.bank_title(self.bank))

    def open_scene(self, pos, entry_pc, *, focus_pc=None, tab=None, reveal=True):
        self.flush_edits()
        c = self.doc.container
        bank = c.banks[pos]
        scenes = [s for s in script.disassemble_bank(bank) if s.entry_pc == entry_pc]
        if scenes:
            sc = next((s for s in scenes if s.action_type >= 0), scenes[0])
        else:
            sc = script.disassemble_scene(bank, -1, entry_pc)
        new_bank = pos != self.bank_pos
        self.bank_pos, self.bank, self.scene = pos, bank, sc
        self.sel = None
        if new_bank or self.triggers.bank_pos != pos:
            self.triggers.show(pos)
        if reveal:
            self.browser.reveal(pos, entry_pc)
        self._show_scene()
        if tab:
            self.nb.select(TABS.index(tab))
        if focus_pc is not None:
            self.view.focus_pc(focus_pc)
        self.status("%s · scene @0x%04x · %d statements" % (catalog.bank_title(bank), entry_pc, len(sc.stmts)))

    def _show_scene(self):
        self.view.render(keep_sel=False)
        self.source.load(force=True)
        self.overview.render()
        self.inspector.show(None)
        self.retag()

    def refresh_scene(self):
        """Re-read the open scene after an edit or undo (bank objects may be new)."""
        if self.bank_pos is None or self.doc.container is None:
            return
        self.bank = self.doc.container.banks[self.bank_pos]
        if self.scene is not None:
            if self.scene.entry_pc >= len(self.bank.data):     # an undone new scene
                self.scene = None
            else:
                self.scene = script.disassemble_scene(self.bank, self.scene.action_type, self.scene.entry_pc)
        self.view.render(keep_sel=True)
        self.source.load()
        self.overview.render()
        self.triggers.refresh()
        self.browser.refresh_bank(self.bank_pos)
        if self.sel is not None and self.stmt(self.sel[0]) is None:
            self.sel = None
        self.inspector.show(self.sel)

    def stmt(self, pc):
        return self.scene.stmts.get(pc) if (self.scene is not None and pc is not None) else None

    def select(self, key):
        self.flush_edits()
        if key is not None and self.stmt(key[0]) is None:
            key = None
        self.sel = key
        self.view.set_selection(key)
        self.inspector.show(key)

    def goto(self, pc):
        """Select the statement at `pc` in the open scene (a branch / choice target)."""
        if self.stmt(pc) is not None:
            self.nb.select(0)
            self.select((pc, None))
        else:
            self.open_scene(self.bank_pos, pc)

    def speaker_before(self, pc):
        """Who speaks a DIALOG: the last SetSpeaker before it in reading order."""
        who = None
        for p, st in script.linearize(self.scene):
            if p == pc:
                return who
            if script.is_portrait_op(st.op):
                name, side, _c = SceneText(self.doc, self.bank, self.scene).speaker_of(st)
                who = "%s (%s, @0x%04x)" % (name, side, p)
            elif st.op == 92:
                who = None
        return who

    def tail_note(self, pc):
        """(ok, text): where the message-box tail points for the first line at or after `pc`.
        The game puts the tail on the side of the last speaker cue (op & 1: 0 left, 1 right)
        and shows it only while a portrait is up on that side for a named character
        (DialogueBox_TickStateMachine, RF4S.exe+0x235BF0), so narration and SetSpeakerVoice
        name plates get none."""
        from rf4s_modkit import portraits
        lin = script.linearize(self.scene)
        idx = next((i for i, (p, _s) in enumerate(lin) if p == pc), None)
        if idx is None:
            return True, ""
        line = next((i for i in range(idx, len(lin)) if lin[i][1].mnem == "DIALOG"), None)
        if line is None:
            return True, "No line follows it in this path."
        for p, st in reversed(lin[:line + 1]):
            if script.is_portrait_op(st.op):
                name, side, _c = SceneText(self.doc, self.bank, self.scene).speaker_of(st)
                slot = (st.op - 16) >> 1
                if not portraits.has_portrait(slot):
                    return False, ("No tail: %s has no portrait (cue @0x%04x)." % (name, p))
                return True, ("The tail points at %s's portrait on the %s (cue @0x%04x)." % (name, side, p))
            if st.op == 10:
                return False, ("No tail: the line's speaker is a SetSpeakerVoice name plate "
                               "(@0x%04x), which has no portrait. Add a SetSpeaker cue before the line." % p)
            if st.op == 92:
                break
        return False, "No tail: no speaker cue before the line (narration). Add a SetSpeaker cue before it."

    def focus_editor(self):
        self.inspector.focus_primary()

    def focus_search(self):
        self.browser.search_entry.focus_set()

    def _tab_changed(self):
        """The Triggers tab shows its entry details in the right-hand pane; the other tabs
        show the Inspector (the selected statement)."""
        try:
            on_triggers = self.nb.select() == str(self.triggers)
        except tk.TclError:
            return
        if on_triggers:
            self.show_trigger(*self.triggers.selected())
        else:
            self._right("inspector")

    def _right(self, which):
        if which == self.right_pane:
            return
        if which == "trigger":
            self.inspector.pack_forget()
            self.trigger_detail.pack(fill="both", expand=True)
        else:
            self.trigger_detail.pack_forget()
            self.inspector.pack(fill="both", expand=True)
        self.right_pane = which

    def triggers_visible(self):
        try:
            return self.nb.select() == str(self.triggers)
        except tk.TclError:
            return False

    def trigger_selected(self, typ, rec):
        """A Triggers-tab row was selected -- by the user, or re-selected when the tab
        refreshes after an edit. Only while the Triggers tab is showing does its detail
        take the right-hand pane; on the other tabs the Inspector keeps it."""
        if self.triggers_visible():
            self.show_trigger(typ, rec)

    def show_trigger(self, typ, rec):
        """Show a trigger type / entry (Triggers tab selection) in the right-hand pane."""
        self.trigger_detail.show(typ, rec)
        self._right("trigger")

    def _view_mode(self):
        self.view.mode = self.mode.get()
        self.view.show_addr = self.addr.get()
        self.view.show_ops = self.show_ops.get()
        self.view.render()

    def set_locale(self, loc):
        self.flush_edits()
        self.doc.locale = loc
        if self.doc.textarc is None:
            self.status("rf3mc.%s is not in this source" % loc)
        self.browser.rebuild()
        if self.bank_pos is not None:
            self.browser.reveal(self.bank_pos, self.scene.entry_pc if self.scene else None)
        self.refresh_scene()

    # ------------------------------------------------------------------ #
    # editing
    # ------------------------------------------------------------------ #
    def apply(self, label, fn, view=None):
        """Run `fn` as one undoable edit and re-read the scene. False if it failed.
        `view` = (bank pos, scene entry) that undo reopens (default: what is open now)."""
        if view is None:
            view = (self.bank_pos, self.scene.entry_pc if self.scene else None)
        steps = list(self.doc.undo_stack)

        def run():
            if self.doc.container is not None:
                self.doc.container.last_relink = None
            fn()
            self._follow_relink()
        try:
            with self.doc.edit(label, view):
                run()
        except Exception as e:  # noqa: BLE001 - the document rolled back; say why
            messagebox.showerror("Not applied", "%s:\n%s" % (label, err_text(e)))
            return False
        if self.doc.undo_stack and (not steps or self.doc.undo_stack[-1] is not steps[-1]):
            self.doc.undo_stack[-1]["view_after"] = (self.bank_pos, self.scene.entry_pc if self.scene else None)
        self.status(label)
        return True

    def _follow_relink(self):
        """A structural edit rebuilt the open bank (Container.last_relink): move the open
        scene and the selection to their new pcs before the views re-read them."""
        c = self.doc.container
        pm = (getattr(c, "last_relink", None) or {}).get(self.bank_pos) if c is not None else None
        if pm is None:
            return
        if self.scene is not None and self.scene.entry_pc in pm:
            self.scene.entry_pc = pm[self.scene.entry_pc]
        if self.sel is not None:
            self.sel = (pm[self.sel[0]], self.sel[1]) if self.sel[0] in pm else None

    def _doc_changed(self, what):
        self._em_uses = None
        self.refresh_scene()
        self._chrome()
        self._maps_pending = self._maps_pending or later(self.frame, self._tell_maps, 150)

    _maps_pending = None

    def _share_with_maps(self):
        """Map views in this program (the map editor's spawn markers, the position picker)
        show this editor's rf3.mc -- edits included, saved or not -- while it is open."""
        try:
            from map_editor import data as map_data
        except ImportError:
            return
        frame = self.frame

        def live():
            try:
                return self.doc.container if frame.winfo_exists() else None
            except tk.TclError:
                return None
        map_data.set_live_script(live)

    def _tell_maps(self):
        self._maps_pending = None
        try:
            from map_editor import data as map_data
        except ImportError:
            return
        map_data.script_changed()

    def flush_edits(self):
        try:
            w = self.frame.focus_get()
        except (KeyError, tk.TclError):
            w = None
        fn = getattr(w, "_commit", None)
        if fn is not None:
            fn()

    # ---- dialogue ---------------------------------------------------------------- #
    def check_text(self, text, what):
        """Check a line the way the game reads it (rf4s_modkit.textlint, docs/48). Errors --
        text the game can crash on -- refuse the edit; warnings let it through, with a note."""
        issues = textlint.lint(text)
        errs = [x for x in issues if x.level == "error"]
        if errs:
            messagebox.showerror("Text the game can't show", "%s:\n\n%s\n\nThe edit was not applied."
                                 % (what, textlint.format_issues(errs)), parent=self.frame)
            return False
        warns = [x for x in issues if x.level == "warning"]
        if warns:
            messagebox.showwarning("Check this text", "%s was changed, but:\n\n%s"
                                   % (what, textlint.format_issues(warns)), parent=self.frame)
        return True

    def scene_slots(self):
        """{kind: slots} the open scene's SetVar opcodes write (for the Inspector's live check)."""
        if self.scene is None or self.bank is None:
            return None
        key = (id(self.scene), id(self.bank))
        if getattr(self, "_slots_key", None) != key:
            try:
                self._slots = textlint.scene_slot_writes(self.scene, self.bank)
            except Exception:  # noqa: BLE001 - a hint only
                self._slots = None
            self._slots_key = key
        return self._slots

    def text_errors(self):
        """[(locale, line id, issue)] for the lines edited this session that would break."""
        out = []
        for loc, lid in sorted(self._edited_lines):
            arc = self.doc.arcs.get(loc) if hasattr(self.doc, "arcs") else None
            if arc is None or not 0 <= lid < len(arc):
                continue
            for x in textlint.errors(arc.text(lid)):
                out.append((loc, lid, x))
        return out

    def arg_count_errors(self):
        """[(bank pos, pc, message)] for statements in the banks changed since the last save
        whose argument count is outside what the shipped game passes (a missing argument is
        read as leftover memory: op 93 without one hides the dialogue box)."""
        out = []
        for pos in self.doc.changed_banks():
            bank = self.doc.container.banks[pos]
            seen = set()
            for sc in script.disassemble_bank(bank):
                for pc, st in sc.stmts.items():
                    if pc in seen or st.op >= 0xFFF0:
                        continue
                    seen.add(pc)
                    why = script.meta.arg_count_problem(st.op, len(st.args))
                    if why:
                        out.append((pos, pc, why))
        return sorted(out)

    def _refuse_broken_text(self, title):
        bad = ["• rf3mc.%s line #%d: %s" % (loc, lid, x.message) for loc, lid, x in self.text_errors()]
        bad += ["• bank %d @0x%04x: %s" % e for e in self.arg_count_errors()]
        if self.doc.em_dirty():                    # em.bin: loops, missing entries, divide by zero
            from rf4s_modkit import emtext
            bad += ["• em.bin #%d: %s" % (idx, msg) for level, idx, _p, msg in emtext.problems(self.doc.em)
                    if level == "error"]
        if not bad:
            return False
        lines = bad[:8] + (["• … and %d more" % (len(bad) - 8)] if len(bad) > 8 else [])
        messagebox.showerror(title, "These would break the game; fix them first:\n\n"
                             + "\n".join(lines), parent=self.frame)
        return True

    def set_text(self, line_id, text):
        arc = self.doc.textarc
        if arc is None:
            self.status("rf3mc.%s is not loaded" % self.doc.locale)
            return False
        if not self.check_text(text, "Line #%d" % line_id):
            return False
        self._edited_lines.add((self.doc.locale, line_id))
        return self.apply("Edit line #%d (%s)" % (line_id, self.doc.locale), lambda: arc.set_text(line_id, text))

    def retarget(self, pc, line_id):
        return self.apply("Point DIALOG @0x%04x at line #%d" % (pc, line_id),
                          lambda: self.bank.set_dialog_id(pc, line_id))

    def add_line(self, text):
        """Append a new dialogue line (in every locale when the toolbar box is ticked)."""
        box = {}
        if not self.check_text(text, "The new line"):
            return None

        def do():
            box["id"], box["locs"] = self.doc.add_line(text, self.pad_locales.get())
        if not self.apply("Add dialogue line", do):
            return None
        self._edited_lines.add((self.doc.locale, box["id"]))
        return box["id"]

    def detach_line(self, pc, text):
        """Save `text` as a new line and point the DIALOG at it (in one step)."""
        if not text.strip():
            self.status("type the line's text first")
            return None
        box = {}
        if not self.check_text(text, "The new line"):
            return None

        def do():
            box["id"], _l = self.doc.add_line(text, self.pad_locales.get())
            self.bank.set_dialog_id(pc, box["id"])
        if self.apply("New line for DIALOG @0x%04x" % pc, do):
            self._edited_lines.add((self.doc.locale, box["id"]))
            return box["id"]
        return None

    def pick_line(self, then):
        lid = dialogs.pick_line(self.frame, self.doc)
        if lid is not None:
            then(lid)

    # ---- actions ------------------------------------------------------------------- #
    def set_speaker(self, pc, slot, side):
        return self.apply("Set speaker @0x%04x" % pc,
                          lambda: self.bank.set_action_opcode(pc, script.portrait_opcode(slot, side)))

    def set_arg(self, pc, index, text):
        """Set one action argument from listing syntax. A plain 16-bit number keeps a typed
        constant (actor(..) / map(..)) typed and is patched in place when it fits; other
        text (and wider numbers) is assembled and patched in place, or the bank is rebuilt around it."""
        st = self.stmt(pc)
        if st is None or index >= len(st.args):
            return False
        buf = self.bank.data
        text = text.strip()
        if scriptasm.call_arg(text) == scriptasm.call_arg(scriptasm.operand_text(buf, st.args[index], st.op, index)):
            return False
        try:
            num = int(text, 0)
        except ValueError:
            num = None
        if num is not None and -0x8000 <= num <= 0xFFFF:     # one literal token (wider: assembled)
            def do():
                self.doc.container.set_arg_value(self.bank, pc, index, num)
            return self.apply("Set %s arg %d" % (script.opcode_mnemonic(st.op), index), do)
        asm = scriptasm.Assembler(resolver=getattr(self.doc.container, "asm_resolver", None))
        try:
            kind, val = asm.operand(text, st.op, index)
        except Exception as e:  # noqa: BLE001 - AsmError / ValueError
            messagebox.showerror("Argument", "arg %d: %s" % (index, err_text(e)))
            return False

        def do():
            b = self.bank
            expr = val
            if kind == "abs":                       # @0xOFF: a copy of that expression
                if not (0 <= val < len(b.data)) or script.disasm_expr(b.data, val)[0] in ("?", ""):
                    raise ValueError("@0x%04x is not an expression in this bank" % val)
                expr = bytes(b.data[val:val + bankrelink.expr_size(b.data, val)])
            # same size: patched in place; otherwise the bank is rebuilt around it
            self.doc.container.set_action_arg_expr(b, pc, index, expr)
        return self.apply("Set %s arg %d" % (script.opcode_mnemonic(st.op), index), do)

    def set_literal(self, pc, k, value):
        st = self.stmt(pc)
        lits = []
        for e in st.expr_refs or ():
            if e is not None:
                lits.extend(script.expr_literals(self.bank.data, e))
        if not 0 <= k < len(lits):
            return False
        off = lits[k][0]
        return self.apply("Set %s number %d = %d" % (st.mnem, k + 1, value),
                          lambda: self.bank.set_expr_value(off, value))

    def set_choice_item(self, pc, k, line_id):
        return self.apply("Choice option %d → line #%d" % (k + 1, line_id),
                          lambda: self.bank.set_choice_item(pc, k, line_id))

    # ---- structure ----------------------------------------------------------------- #
    def assemble_check(self, text, base=None):
        """(region, labels, None) or (None, None, error) without applying anything. The
        region is laid out at a nominal `base`; the real edit relinks the whole bank."""
        if base is None:
            base = 4 * script.TYPE_TABLE_SLOTS
        resolver = self.doc.container.asm_resolver if self.doc.container is not None else None
        try:
            region, labels = scriptasm.assemble(text, base, resolver=resolver)
        except script.ScriptError as e:
            return None, None, self._suggest(str(e))
        except Exception as e:  # noqa: BLE001
            return None, None, "%s: %s" % (type(e).__name__, e)
        return region, labels, None

    _names = None

    @classmethod
    def _suggest(cls, msg):
        """Add 'did you mean' to an unknown-opcode error (fuzzy, catches plain typos)."""
        m = re.search(r"unknown opcode '([^']+)'", msg or "")
        if not m or "did you mean" in msg:
            return msg
        if cls._names is None:
            pool = {}
            for o in range(script.DISPATCHABLE_ACTION_OPS):
                for nm in (script.opcode_mnemonic(o), script.opcode_name(o)):
                    if nm and not re.fullmatch(r"op\d+", nm) and nm.lower() not in pool:
                        pool[nm.lower()] = (nm, o)
            cls._names = pool
        hits = difflib.get_close_matches(m.group(1).lower(), list(cls._names), n=6, cutoff=0.6)
        return msg + (" -- did you mean: " + ", ".join("%s (op %d)" % cls._names[h] for h in hits) if hits else "")

    def insert_after(self, pc, listing):
        return self._insert_listing(pc, listing, before=False)

    def insert_before(self, pc, listing):
        """Insert statements just before `pc`: every path that reaches `pc` (the line above
        falling through, and every jump / branch to it) runs them first."""
        return self._insert_listing(pc, listing, before=True)

    def _insert_listing(self, pc, listing, before):
        err = self.assemble_check(listing)[2]
        if err:
            messagebox.showinfo("Insert", err)
            return False
        n = count_statements(listing)
        ins = self.doc.container.insert_before if before else self.doc.container.insert_after
        box = {}
        ok = self.apply("Insert %d statement%s %s @0x%04x" % (n, "" if n == 1 else "s",
                                                             "before" if before else "after", pc),
                        lambda: box.update(pc=ins(self.bank, pc, listing)))
        if ok:
            self._select_new(box.get("pc"))
        return ok

    def set_opcode(self, pc, op):
        """Change a statement's opcode, keeping its arguments (e.g. ops 94-97, the box style)."""
        st = self.stmt(pc)
        if st is None or st.op == op:
            return False
        return self.apply("%s -> %s @0x%04x" % (script.opcode_mnemonic(st.op), script.opcode_mnemonic(op), pc),
                          lambda: self.bank.set_action_opcode(pc, op))

    def insert_dialogue_after(self, pc, speaker, text, face=0, box_style=None):
        """Add a new line (all locales) and insert [SetSpeaker] + DIALOG after `pc`. `face` is
        the SetSpeaker face id (rf4s_modkit.portraits: the N-th face of the speaker); it needs
        a speaker."""
        return self._insert_dialogue(pc, speaker, text, face, box_style, before=False)

    def insert_dialogue_before(self, pc, speaker, text, face=0, box_style=None):
        """The same, inserted just before `pc` (so also where a label at `pc` points)."""
        return self._insert_dialogue(pc, speaker, text, face, box_style, before=True)

    def _insert_dialogue(self, pc, speaker, text, face, box_style, before):
        box = {}
        if not self.check_text(text, "The new line"):
            return None

        def do():
            nid, _l = self.doc.add_line(text, self.pad_locales.get())
            box["id"] = nid
            specs = []
            if speaker is not None:
                # both sides share one mnemonic, so name the opcode by number; face 0 with no
                # emote (0) is what 47,833 of the shipped speaker cues carry
                specs.append("op%d %d, 0" % (script.portrait_opcode(*speaker), int(face or 0)))
            if box_style is not None:                # the message-box style (ops 94-97 / 93)
                specs.append("op%d" % (94 + box_style) if 0 <= box_style <= 3 else "op93 %d" % box_style)
            specs.append("DIALOG #%d" % nid)
            ins = self.doc.container.insert_before if before else self.doc.container.insert_after
            box["pc"] = ins(self.bank, pc, "\n".join(specs))
        if self.apply("Add dialogue %s @0x%04x" % ("before" if before else "after", pc), do):
            self._edited_lines.add((self.doc.locale, box["id"]))
            self._select_new(box.get("pc"))
            return box["id"]
        return None

    def _select_new(self, pc):
        """After an insert: select the first new statement (its pc in the rebuilt bank)."""
        if pc is not None and self.stmt(pc) is not None:
            self.select((pc, None))

    # a selected label row is (pc, LABEL): adding "after" a label = before its statement
    LABEL = "label"

    def selected_label(self):
        return self.sel is not None and self.sel[1] == self.LABEL

    def _insert_where(self, before):
        """(pc, before) for an insert at the selection, or None (with a status hint)."""
        if self.sel is None:
            self.status("select a statement or a label first")
            return None
        return self.sel[0], (before or self.selected_label())

    def _where_text(self, pc, before):
        if self.selected_label():
            return "at label %s" % script.scene_labels(self.scene).get(pc, "0x%04x" % pc)
        return "%s @0x%04x" % ("before" if before else "after", pc)

    def ask_insert_listing(self, before=False):
        w = self._insert_where(before)
        if w is None:
            return None
        pc, before = w
        text = dialogs.ask_listing(self.frame, "Insert " + self._where_text(pc, before), catalog.INSERT_PROMPT,
                                   lambda t: self.assemble_check(t)[2])
        if not text:
            return None
        return self.insert_before(pc, text) if before else self.insert_after(pc, text)

    _picker = None
    _reference = None

    def ask_insert_instruction(self, before=None, preset=None):
        """The Instruction picker (one per editor): pick any instruction, fill its arguments,
        insert it at the selected statement. `preset` = ('op', n) or ('ctl', mnemonic)."""
        from . import toolbox
        p = self._picker
        try:
            alive = p is not None and bool(p.win.winfo_exists())
        except tk.TclError:
            alive = False
        if not alive:
            p = self._picker = toolbox.InstructionPicker(self)
        p.show(preset=preset, before=before)
        return p

    def open_reference(self, tab=None):
        """The Reference window (one per editor): flags, verified functions, characters, maps, items."""
        from . import toolbox
        r = self._reference
        try:
            alive = r is not None and bool(r.win.winfo_exists())
        except tk.TclError:
            alive = False
        if not alive:
            r = self._reference = toolbox.ReferenceWindow(self)
        r.show(tab)
        return r

    def ask_insert_dialogue(self, before=False):
        w = self._insert_where(before)
        if w is None:
            return None
        pc, before = w
        if self.doc.textarc is None:
            self.status("rf3mc.%s is not loaded" % self.doc.locale)
            return None
        spec = dialogs.ask_dialogue(self.frame, reader=self.doc.reader)
        if not spec:
            return None
        ins = self.insert_dialogue_before if before else self.insert_dialogue_after
        return ins(pc, spec["speaker"], spec["text"], spec.get("face", 0), spec.get("box"))

    def delete_selected(self):
        if self.sel is None:
            return False
        if self.selected_label():
            self.status("a label only marks a jump target -- select a statement to delete it")
            return False
        pc = self.sel[0]
        st = self.stmt(pc)
        name = script.opcode_mnemonic(st.op) if st.op < 0xFFF0 else st.mnem
        ok = self.apply("Delete %s @0x%04x" % (name, pc),
                        lambda: self.doc.container.delete_statement(self.bank, pc))
        if ok:
            self.status("Deleted %s @0x%04x (whatever jumped to it now goes to the next statement; "
                        "Ctrl+Z undoes it)" % (name, pc))
        return ok

    def show_callers(self):
        if self.scene is None:
            return None
        target = self.sel[0] if self.sel else self.scene.entry_pc
        rows = catalog.collect_xrefs(self.bank, target)
        dispatch = sorted({sc.action_type for sc in script.disassemble_bank(self.bank)
                           if sc.entry_pc == target and sc.action_type >= 0})
        return dialogs.callers_window(self.frame, self, rows, dispatch, target)

    # ---- triggers (the type table) --------------------------------------------------- #
    def default_keys_text(self, bank, type_id):
        names = catalog.type_key_names(type_id)
        n = len(names) if names is not None else None
        if n is None:
            try:
                recs = bank.entry_records(type_id)
            except Exception:
                recs = []
            n = len(recs[0].subs) if recs else None
        return ", ".join(["-1"] * n) if n else ""

    def new_scene_template(self):
        """A new scene starts empty. The FRAME its code needs is added / raised by itself on
        every edit (bankrelink.BankModel.ensure_frames), so nobody has to write one."""
        return "RET\n"

    def shadow_note(self, bank, type_id, position=None):
        try:
            return self.doc.container.entry_shadow_note(bank, type_id, position) or ""
        except Exception:
            return ""

    def ask_new_scene(self, default_type=None, pos=None):
        if self.doc.container is None:
            self.status("open rf3.mc first")
            return None
        pos = self.bank_pos if pos is None else pos
        if pos is None:
            self.status("open a bank first (pick one on the left), then New scene…")
            return None
        bank = self.doc.container.banks[pos]
        if default_type is None:
            typ, _r = self.triggers.selected()
            default_type = typ if typ is not None else (
                self.scene.action_type if (self.scene is not None and self.scene.action_type >= 0) else None)
        spec = dialogs.ask_new_scene(self.frame, self, bank, default_type)
        if not spec:
            return None
        return self.add_entry(pos, spec["type_id"], spec["keys"], spec["body"], spec["position"])

    def add_entry(self, pos, type_id, keys, body, position=None):
        """Mint a scene: assemble `body`, append it, register it under `type_id` with `keys`
        at `position` ('append' / 'first' / an index), then open it. (event pc, index) or None."""
        bank = self.doc.container.banks[pos]
        try:
            subs = catalog.parse_entry_keys(keys) if isinstance(keys, str) else list(keys or ())
        except ValueError as e:
            messagebox.showinfo("New scene", err_text(e))
            return None
        if not (body or "").strip():
            body = "RET"                         # an empty scene
        err = self.assemble_check(body)[2]
        if err:
            messagebox.showinfo("New scene", err)
            return None
        at = None if position in (None, "", "append", "last") else (0 if position == "first" else int(position))
        note = self.shadow_note(bank, int(type_id), at)
        box = {}

        def do():
            box["r"] = self.doc.container.add_entry(bank, int(type_id), subs, listing=body, position=at)
        if not self.apply("New %s scene" % catalog.type_label(int(type_id)), do, view=(pos, None)):
            return None
        event_pc, idx = box["r"]
        self.browser.refresh_bank(pos)
        self.open_scene(pos, event_pc)
        warn = "; ".join([note] * bool(note) + catalog.key_problems(int(type_id), subs))
        self.status("new scene @0x%04x registered as %s entry #%d" % (event_pc, catalog.type_label(int(type_id)), idx)
                    + (("   ⚠ " + warn) if warn else ""))
        return event_pc, idx

    def remove_entry(self, pos, type_id, index):
        bank = self.doc.container.banks[pos]
        ok = self.apply("Remove %s entry #%d" % (catalog.type_label(type_id), index),
                        lambda: self.doc.container.remove_entry(bank, type_id, index))
        if ok:
            self.browser.refresh_bank(pos)
        return ok

    def set_entry_keys(self, pos, type_id, index, keys):
        try:
            subs = catalog.parse_entry_keys(keys) if isinstance(keys, str) else list(keys or ())
        except ValueError as e:
            messagebox.showinfo("Keys", err_text(e))
            return False
        bank = self.doc.container.banks[pos]
        ok = self.apply("Keys of %s entry #%d" % (catalog.type_label(type_id), index),
                        lambda: self.doc.container.set_entry(bank, type_id, index, subs=subs))
        warn = catalog.key_problems(type_id, subs)
        if ok and warn:
            self.status("keys changed   ⚠ " + "; ".join(warn))
        return ok

    def open_new_scene_dialog(self, bank_index, default_type=None):
        """Host entry point ('New scene on this map…'): open the bank, then the New scene
        dialog with `default_type` (MapEnterScene for a map bank when None)."""
        c = self.doc.container
        if c is None or not 0 <= bank_index < len(c.banks):
            self.status("rf3.mc has no bank %s" % bank_index)
            return None
        if self.bank_pos != bank_index:
            self.show_bank(bank_index)
        self.nb.select(TABS.index("Triggers"))
        if default_type is None and c.banks[bank_index].kind == "tail":
            default_type = catalog.map_enter_type()
        return self.ask_new_scene(default_type, pos=bank_index)

    # ---- Event Manager ----------------------------------------------------------------- #
    def open_event_manager(self):
        if self.doc.em is None:
            messagebox.showerror("Event Manager", "em.bin / emdeb.bin were not found in the game source.")
            return None
        w = self._em_window
        if w is not None and w.win.winfo_exists():
            w.win.deiconify()
            w.win.lift()
            return w
        self._em_window = EventManagerWindow(self)
        return self._em_window

    def _em_bank_scan(self, pos, bk):
        """[(entry id or None, scene entry, pc, stmt)] for the em bridge ops (371-374, 444) in
        one bank; None = the entry id is computed at run time (a variable, not a number)."""
        out, seen = [], set()
        for sc in script.disassemble_bank(bk):
            for pc, st in sc.stmts.items():
                if st.op not in script.EMF_ENTRY_OPS or pc in seen:
                    continue
                ai = script.EMF_ENTRY_OPS[st.op]
                if ai >= len(st.args):
                    continue
                seen.add(pc)
                try:
                    eid = int(script.arg_repr(bk.data, st.args[ai]))
                except (ValueError, TypeError):
                    eid = None
                out.append((eid, sc.entry_pc, pc, st))
        return out

    def _em_index(self):
        """{entry id or None: [(bank pos, scene entry, pc, stmt)]}. Rebuilt after every edit, but
        a bank is only re-scanned when its bytes changed (a full scan takes seconds; one bank
        a fraction of one), so custom scenes are always counted."""
        if self._em_uses is None:
            uses, cache = {}, self._em_bank_uses
            for pos, bk in enumerate(self.doc.container.banks):
                data = bytes(bk.data)
                hit = cache.get(pos)
                if hit is None or hit[0] != data:
                    hit = cache[pos] = (data, self._em_bank_scan(pos, bk))
                for eid, entry, pc, st in hit[1]:
                    uses.setdefault(eid, []).append((pos, entry, pc, st))
            self._em_uses = uses
        return self._em_uses

    def em_uses(self, entry_idx):
        """[(bank pos, scene entry, pc, stmt)] of every scene op naming em entry `entry_idx`."""
        return self._em_index().get(entry_idx, [])

    def em_dynamic_uses(self):
        """The scene ops whose em entry is computed at run time (a variable): they may use any
        entry, so the Event Manager lists them under every entry's 'Used by'."""
        return self._em_index().get(None, [])

    def em_use_counts(self):
        return {k: len(v) for k, v in self._em_index().items() if k is not None}

    def ask_spec(self, title, prompt, validate, initial=""):
        return dialogs.ask_spec(self.frame, title, prompt, validate, initial)

    # ------------------------------------------------------------------ #
    # undo, saving
    # ------------------------------------------------------------------ #
    def undo(self):
        self.flush_edits()
        step = self.doc.undo()
        self._after_history(step, "Undid")

    def redo(self):
        self.flush_edits()
        step = self.doc.redo()
        self._after_history(step, "Redid")

    def _after_history(self, step, verb):
        if step is None:
            self.status("Nothing to undo" if verb == "Undid" else "Nothing to redo")
            return
        view = step.get("view_after", step.get("view")) if verb == "Redid" else step.get("view")
        c = self.doc.container
        if view and view[0] is not None and c is not None and 0 <= view[0] < len(c.banks):
            here = (self.bank_pos, self.scene.entry_pc if self.scene else None)
            if view[1] is None or view[1] >= len(c.banks[view[0]].data):
                if here[0] != view[0] or self.scene is None:
                    self.show_bank(view[0])
            elif here != tuple(view):
                self.open_scene(view[0], view[1])
        self.status("%s: %s" % (verb, step["label"]))

    def _undo_tip(self, which):
        st = self.doc.undo_stack if which == "undo" else self.doc.redo_stack
        return ("%s: %s  (%s)" % (which.capitalize(), st[-1]["label"], "Ctrl+Z" if which == "undo" else "Ctrl+Y")
                if st else "Nothing to %s" % which)

    def _chrome(self):
        parts = self.doc.dirty_parts()
        self.dirty_lbl.config(text=("● unsaved: " + ", ".join(parts)) if parts else "")
        self.undo_btn.state(["!disabled"] if self.doc.undo_stack else ["disabled"])
        self.redo_btn.state(["!disabled"] if self.doc.redo_stack else ["disabled"])

    def unsaved(self):
        return self.doc.dirty_parts()

    def confirm_discard(self, action="continue"):
        self.flush_edits()
        parts = self.unsaved()
        if not parts:
            return True
        ans = messagebox.askyesnocancel("Unsaved changes", "Unsaved changes to %s.\n\nSave before you %s?\n"
                                        "(Yes = save, No = discard, Cancel = stay here)"
                                        % (", ".join(parts), action), parent=self.parent)
        if ans is None:
            return False
        return self.save_all() if ans else True

    def _on_close(self):
        if self.confirm_discard("close the cutscene editor"):
            self.parent.destroy()

    def save_all(self):
        """Save every changed file. With a game folder set (or a file opened from disk) the
        files are overwritten where they came from, without asking (save_to_game); otherwise
        each one is saved through a file dialog."""
        self.flush_edits()
        if self.source.pending():          # hand edits in the Source tab count only once applied
            ans = messagebox.askyesnocancel(
                "Source tab", "The Source tab has an edited listing that isn't applied to the "
                "scene yet.\n\nApply it before saving?\n(No saves without it; the listing stays "
                "in the Source tab.)", parent=self.frame)
            if ans is None:
                return False
            if ans and not self.source.apply():
                self.nb.select(self.nb.index(self.source))
                return False
        parts = self.unsaved()
        if not parts:
            self.status("Nothing to save")
            return True
        if self.save_targets() is not None:
            return self.save_to_game()
        if "rf3.mc" in parts and not self.save_script():
            return False
        if any(p.startswith("rf3mc.") for p in parts) and not self.save_text():
            return False
        if "em.bin" in parts and not self.save_em():
            return False
        return True

    # ---- saving straight into the game folder ----------------------------------------- #
    from rf4s_modkit.gamepaths import BACKUP_DIR

    def save_targets(self):
        """{file name: path to overwrite} for everything that can change, or None when there
        is nowhere to write without asking. A file opened with Open rf3.mc… is written back
        in place (its rf3mc.<locale> / em.bin too, when they sit next to it). Otherwise each
        file goes over the copy the game loads from the game folder (the Bundle/** winner:
        a Bundle\\00_mods override, else the unpacked original), or into Bundle\\00_mods when
        the game only has it inside a packed .mbundle."""
        from rf4s_modkit import gamepaths
        names = ["rf3.mc", "em.bin"] + ["rf3mc.%s" % loc for loc in set(self.doc.dirty_locales())
                                        | {self.doc.locale}]
        out = {}
        opened = getattr(self.doc, "path", None)
        if opened is not None:
            out["rf3.mc"] = pathlib.Path(opened)
            for n in names[1:]:
                if (pathlib.Path(opened).parent / n).is_file():
                    out[n] = pathlib.Path(opened).parent / n
        bdir = gamepaths.find_bundle_dir()
        if bdir is None:
            return out if opened is not None else None
        idx = mbundle.loose_index(bdir)
        for n in names:
            if n in out:
                continue
            hits = idx.get(n)                      # exact case, like the game's index
            out[n] = (bdir / hits[0]) if hits else (bdir / mbundle.MOD_FOLDER / n)
        return out

    def _backup_once(self, target):
        """Copy the file about to be overwritten to <game>/ModdingBackup/<same path>, once."""
        from rf4s_modkit import gamepaths
        return gamepaths.backup_once(target)

    def save_to_game(self):
        """Overwrite the changed files where they came from, without asking."""
        self.flush_edits()
        if self._refuse_broken_text("Save"):
            return False
        targets = self.save_targets()
        if targets is None:
            return self.save_all()
        blobs = {}
        if self.doc.script_dirty():
            self.rebuild_trampolined_banks()
            blobs["rf3.mc"] = self.doc.container.build()
        for loc in self.doc.dirty_locales():
            blobs["rf3mc.%s" % loc] = self.doc.arcs[loc].build()
        if self.doc.em_dirty():
            blobs["em.bin"] = self.doc.em.build()
        missing = [n for n in blobs if n not in targets]
        if missing:
            messagebox.showerror("Save", "No place to save %s: set the game folder (Game folder… "
                                         "in the main window), or use Save … as…" % ", ".join(missing),
                                 parent=self.frame)
            return False
        written, backed = [], []
        try:
            for name, blob in blobs.items():
                t = targets[name]
                b = self._backup_once(t)
                if b is not None:
                    backed.append(name)
                t.parent.mkdir(parents=True, exist_ok=True)
                tmp = t.with_name(t.name + ".saving")
                tmp.write_bytes(blob)
                tmp.replace(t)
                written.append(str(t))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Save", "Could not write %s:\n%s\n\n(Is the game running with the "
                                         "file open?)" % (name, e), parent=self.frame)
            return False
        if "em.bin" in blobs:
            self._save_em_names()
        self.doc.mark_saved(script_="rf3.mc" in blobs, locales=[n[6:] for n in blobs if n.startswith("rf3mc.")],
                            em="em.bin" in blobs)
        self._chrome()
        note = " (originals of %s kept in %s)" % (", ".join(backed), self.BACKUP_DIR) if backed else ""
        how = []
        if "rf3.mc" in blobs:
            how.append("Ctrl+R puts the scenes into the running game")
        if any(n.startswith("rf3mc.") for n in blobs):
            how.append("the running game reads dialogue fresh for every line")
        if "em.bin" in blobs:
            how.append("em.bin needs a game restart")
        self.status("Saved %s%s -- %s" % (", ".join(written), note, "; ".join(how)))
        return True

    def reload_in_game(self):
        """Save, then swap the saved rf3.mc into the running RF4S.exe (rf4s_modkit.hotreload)."""
        from rf4s_modkit import hotreload
        if self.unsaved() and not self.save_all():
            return False
        targets = self.save_targets() or {}
        path = targets.get("rf3.mc")
        if path is None or not pathlib.Path(path).is_file():
            self.status("Reload: no saved rf3.mc to load (set the game folder or save first)")
            return False
        try:
            pid = hotreload.pick_process(self._choose_game)
        except hotreload.HotReloadError as e:
            self.status("Reload: %s" % err_text(e))
            return False
        if pid is None:
            self.status("Reload cancelled")
            return False
        try:
            self.frame.config(cursor="watch")
            self.frame.update_idletasks()
            r, (loc, t) = hotreload.reload_all(pathlib.Path(path).read_bytes(), pid=pid)
        except hotreload.HotReloadError as e:
            self.status("Reload refused: %s" % err_text(e))
            return False
        finally:
            try:
                self.frame.config(cursor="")
            except tk.TclError:
                pass
        self.status(hotreload.describe(r) + "; " + (hotreload.describe_text(t, loc) if loc else
                    "dialogue text not reloaded: %s (restart the game for text changes)" % t))
        return True

    def _choose_game(self, procs):
        """Several RF4S.exe run: ask which one gets the reload (remembered while it runs)."""
        win = tk.Toplevel(self.frame)
        win.title("Which game?")
        win.transient(self.frame.winfo_toplevel())
        ttk.Label(win, text="%d copies of RF4S.exe are running.\nWhich one should get the "
                            "scenes?" % len(procs),
                  wraplength=520, justify="left").pack(anchor="w", padx=10, pady=(10, 6))
        lb = tk.Listbox(win, height=min(8, len(procs)), width=90, font=("Segoe UI", 9))
        for p in procs:
            lb.insert("end", p.label())
        lb.selection_set(0)
        lb.pack(fill="x", padx=10)
        out = {"p": None}

        def ok(_e=None):
            s = lb.curselection()
            if s:
                out["p"] = procs[s[0]]
            win.destroy()
        bb = ttk.Frame(win)
        bb.pack(fill="x", padx=10, pady=10)
        ttk.Button(bb, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(bb, text="Select", command=ok).pack(side="right", padx=4)
        lb.bind("<Double-Button-1>", ok)
        lb.bind("<Return>", ok)
        win.bind("<Escape>", lambda _e: win.destroy())
        lb.focus_set()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        win.wait_window()
        return out["p"]

    def _save_em_names(self):
        """Keep the names of custom em.bin entries: emdeb.bin (the game's debug name table) is
        never rewritten, so they go to the emdeb_extra.json sidecar next to it."""
        from rf4s_modkit import emflags
        try:
            path = self.doc.em.names.flags.extra_path or emflags.extra_path_default()
            if emflags.save_entry_names(path, self.doc.em.custom_entry_names()):
                self.doc.em.names.flags.extra_path = path
        except (OSError, ValueError) as e:
            self.status("em.bin saved; the custom entry names could not be kept: %s" % err_text(e))

    def save_script(self):
        if self.doc.container is None:
            return False
        self.flush_edits()
        if self._refuse_broken_text("Save rf3.mc"):
            return False
        f = filedialog.asksaveasfilename(title="Save rf3.mc", defaultextension=".mc", initialfile="rf3.mc")
        if not f:
            return False
        self.rebuild_trampolined_banks()
        try:
            pathlib.Path(f).write_bytes(self.doc.container.build())
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Save rf3.mc", err_text(e))
            return False
        self.doc.mark_saved(script_=True)
        self._chrome()
        self.status("Saved %s" % f)
        return True

    def rebuild_trampolined_banks(self):
        """Before rf3.mc is written: banks an older toolkit edited by trampolining (code
        appended past the pool, jumps written over statements) are rebuilt in place --
        same execution, no dead code (Container.normalize_banks) -- as one undoable edit.
        Checked once per opened file (~2 s); edits made in this editor never trampoline."""
        c = self.doc.container
        if c is None or getattr(self.doc, "trampolines_checked", None) is c:
            return []
        self.doc.trampolines_checked = c
        found = c.trampolined_banks()
        if found:
            self.apply("Rebuild %d bank%s edited by an older toolkit (trampolines put back in place)"
                       % (len(found), "" if len(found) == 1 else "s"), lambda: c.normalize_banks(found))
            self.doc.trampolines_checked = self.doc.container
        return found

    def save_text(self):
        """Save the shown locale's dialogue; every other edited locale is written next to it
        under its own rf3mc.<locale> name, so line ids stay aligned."""
        if self.doc.textarc is None:
            messagebox.showinfo("Save dialogue", "rf3mc.%s is not loaded." % self.doc.locale)
            return False
        if self._refuse_broken_text("Save dialogue"):
            return False
        f = filedialog.asksaveasfilename(title="Save rf3mc.%s" % self.doc.locale,
                                         initialfile="rf3mc.%s" % self.doc.locale)
        if not f:
            return False
        folder = pathlib.Path(f).parent
        written = []
        try:
            pathlib.Path(f).write_bytes(self.doc.textarc.build())
            written.append(pathlib.Path(f).name)
            for loc in self.doc.dirty_locales():
                if loc != self.doc.locale:
                    (folder / ("rf3mc.%s" % loc)).write_bytes(self.doc.arcs[loc].build())
                    written.append("rf3mc.%s" % loc)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Save dialogue", err_text(e))
            return False
        self.doc.mark_saved(locales=set(self.doc.dirty_locales()) | {self.doc.locale})
        self._chrome()
        self.status("Saved %s -> %s" % (", ".join(written), folder))
        return True

    def save_em(self):
        em = self.doc.em
        if em is None:
            return False
        if self._refuse_broken_text("Save em.bin"):
            return False
        f = filedialog.asksaveasfilename(title="Save em.bin", defaultextension=".bin", initialfile="em.bin")
        if not f:
            return False
        try:
            pathlib.Path(f).write_bytes(em.build())
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Save em.bin", err_text(e))
            return False
        self._save_em_names()
        self.doc.mark_saved(em=True)
        self._chrome()
        self.status("Saved %s" % f)
        return True

    def install(self):
        """Install every edited file as a loose override under a chosen game root."""
        if self.doc.container is None:
            return False
        if self._refuse_broken_text("Install"):
            return False
        from rf4s_modkit import gamepaths
        root = gamepaths.find_bundle_dir()          # the game copy every tool uses
        if root is None:
            root = filedialog.askdirectory(title="Game folder (overrides go to Bundle\\00_mods)")
            if not root:
                return False
        import tempfile
        files = {"rf3.mc": self.doc.container.build()}
        for loc in self.doc.dirty_locales():
            files["rf3mc.%s" % loc] = self.doc.arcs[loc].build()
        if self.doc.em_dirty():
            files["em.bin"] = self.doc.em.build()
        try:
            # staged in a temporary folder that is removed again, whatever happens
            with tempfile.TemporaryDirectory(prefix="rf4s_install_") as tmp:
                stage = pathlib.Path(tmp)
                for name, blob in files.items():
                    (stage / name).write_bytes(blob)
                    mbundle.install_loose(pathlib.Path(root), name, str(stage / name))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Install", err_text(e))
            return False
        self.doc.mark_saved(script_=True, locales=self.doc.dirty_locales(), em="em.bin" in files)
        self._chrome()
        messagebox.showinfo("Install", "Installed %s into %s.\nRestart the game to load them (it "
                                       "indexes Bundle\\ at startup, ahead of the .mbundle archives); "
                                       "delete the folder to uninstall."
                            % (", ".join(files), mbundle.bundle_dir(root) / mbundle.MOD_FOLDER))
        self.status("Installed " + ", ".join(files))
        return True

    # ---- status ----------------------------------------------------------------------- #
    def status(self, s):
        if self.status_fn:
            self.status_fn(s)
        try:
            self.status_lbl.config(text=s)
        except (tk.TclError, AttributeError):
            pass
        self.update_space()

    def space_text(self):
        """'Bank 18: 9,054 B free of 65,536 (86% used)' for the open bank, or ''."""
        c = self.doc.container if self.doc is not None else None
        pos = getattr(self, "bank_pos", None)
        if c is None or pos is None or not 0 <= pos < len(c.banks):
            return ""
        sp = c.bank_space(c.banks[pos])
        return "Bank %d: %s B free of %s (%d%% used)" % (
            pos, format(sp["free"], ","), format(sp["limit"], ","), round(100 * sp["used"] / sp["limit"]))

    def update_space(self):
        try:
            txt = self.space_text()
            self.space_lbl.config(text=txt, foreground=(
                "#b00020" if txt and self.doc.container.bank_space(self.bank_pos)["free"] < 1024 else ""))
        except (tk.TclError, AttributeError):
            pass

    def busy(self, on):
        try:
            self.frame.config(cursor="watch" if on else "")
            self.frame.update_idletasks()
        except tk.TclError:
            pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = tk.Tk()
    import guiutil
    guiutil.install_error_logging(root)
    guiutil.install_combo_keys(root)
    import guitheme
    guitheme.install(root)                  # light / dark (settings.json)
    root.title("RF4S Cutscene Editor")
    root.geometry("1400x860")
    reader = None
    if argv:
        d = pathlib.Path(argv[0])
        if d.is_dir():
            from map_editor.data import folder_reader
            reader = folder_reader(d)
    if reader is None:
        from map_editor import data
        mc = data.find_extracted("rf3.mc")
        if mc is not None:
            reader = data.folder_reader(mc.parent)
    CutsceneExplorer(root, reader=reader)
    root.mainloop()
