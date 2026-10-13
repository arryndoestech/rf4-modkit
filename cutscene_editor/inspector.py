"""The Inspector: a form for the selected statement.

    dialogue   the line's text (edit in place), its speaker, the line id (retarget / new
               line), and the same line in the other locales
    speaker    who speaks + which side, and the face / emote / voice arguments
    action     one row per argument: its name, the value in listing syntax, a picker when
               the argument has named values, and what the value means
    condition  the decoded condition with its literals editable, and the jump targets
    choice     each option's text, line id and target

Fields commit on Enter or when they lose focus, as one undo step, only when the value
changed. The explanation of the statement (the Alt-hover text) is shown at the bottom."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from guiutil import FilterCombo, ScrollFrame, Tip, commit_entry, hint, section, set_text, to_int
from rf4s_modkit import script, scriptasm, textesc, textlint

from .render import CHOICE_OPS, SceneText

def speaker_choices():
    """'N  name' for every speaker slot, named as the game names the character now."""
    return ["%d  %s" % (i, "MC (%s)" % script.meta.speaker_name(0) if i == 0 else script.meta.speaker_name(i))
            for i in range(len(script.PORTRAIT_SPEAKERS))]


class Inspector(ScrollFrame):
    def __init__(self, parent, app):
        super().__init__(parent, width=360)
        self.app = app
        self.key = None
        b = self.body
        self.title = ttk.Label(b, font=("Segoe UI", 11, "bold"), wraplength=340, justify="left")
        self.title.pack(anchor="w", padx=6, pady=(6, 0))
        self.sub = ttk.Label(b, font=("Segoe UI", 8), foreground="#666", wraplength=340, justify="left")
        self.sub.pack(anchor="w", padx=6)
        self.desc = ttk.Label(b, font=("Segoe UI", 9), wraplength=340, justify="left")
        self.desc.pack(anchor="w", fill="x", padx=6, pady=(2, 4))
        self.form = ttk.Frame(b)
        self.form.pack(fill="x")
        # actions for any selected statement
        self.actions = ttk.Frame(b)
        self.actions.pack(fill="x", padx=6, pady=(8, 2))
        # (adding instructions, dialogue lines and statements: right-click in the script)
        self.del_btn = ttk.Button(self.actions, text="Delete", width=7, command=app.delete_selected)
        Tip(self.del_btn, "Skip this statement (the scene jumps over it; byte-safe). Del key.")
        self.callers_btn = ttk.Button(self.actions, text="Xrefs…", width=9, command=app.show_callers)
        Tip(self.callers_btn, "Every CALL / jump / branch / choice in this bank that leads to the "
                              "selected statement or label (X; also in the toolbar).")
        self._pack_actions(label=False)
        self.explain_box = section(b, "Description")
        self.explain = tk.Text(self.explain_box, height=12, wrap="word", font=("Consolas", 8),
                               relief="flat", bg="#f4f4f6")
        self.explain.pack(fill="both", expand=True)
        self.explain.configure(state="disabled")
        self.bind_wheel_tree()
        self.show(None)

    def _pack_actions(self, label):
        """Delete / Xrefs…; a label gets Xrefs… only (labels can't be deleted)."""
        for w in (self.del_btn, self.callers_btn):
            w.pack_forget()
        shown = (self.callers_btn,) if label else (self.del_btn, self.callers_btn)
        for i, w in enumerate(shown):
            w.pack(side="left", padx=(0 if i == 0 else 4, 0))

    # ---- building the form for a selection ------------------------------------ #
    def _clear(self):
        for w in self.form.winfo_children():
            w.destroy()

    def show(self, key):
        self.key = key
        self._clear()
        app = self.app
        st = app.stmt(key[0]) if key else None
        if st is None:
            self._show_scene()
            return
        txt = SceneText(app.doc, app.bank, app.scene)
        self.actions.pack(fill="x", padx=6, pady=(8, 2), after=self.form)
        label = key[1] == app.LABEL
        self._pack_actions(label)
        if label:
            self._label_form(st, txt)
            self.explain_box.pack_forget()
            self.app.retag(self.form)
            return
        if st.mnem == "DIALOG":
            self._dialog_form(st, txt)
        elif script.is_portrait_op(st.op):
            self._speaker_form(st, txt)
        elif st.op < 0xFFF0:
            self._action_form(st, txt)
        elif st.mnem in CHOICE_OPS:
            self._choice_form(st, txt, key[1])
        else:
            self._control_form(st, txt)
        set_text(self.explain, txt.explain(st))
        self.explain_box.pack(fill="x", padx=4, pady=(4, 2), after=self.actions)
        self.bind_wheel_tree(self.form)
        self.app.retag(self.form)

    def _label_form(self, st, txt):
        name = txt.target(st.pc)
        self.title.config(text="Label %s" % name)
        self.sub.config(text="marks @0x%04x -- a place jumps, branches and choices lead to" % st.pc)
        self.desc.config(text="Adding after it (right-click) puts new lines here: they play first "
                              "on every path that reaches %s. To add after the statement below it "
                              "instead, select that statement." % name)

    def _header(self, title, st, desc):
        self.title.config(text=title)
        self.sub.config(text="statement @0x%04x · %s · %d bytes" % (st.pc, st.mnem, st.size))
        d = (desc or "").strip().split(". ")[0].rstrip(".")
        self.desc.config(text=(d[:220] + "…") if len(d) > 220 else d)

    def _show_scene(self):
        app = self.app
        self.actions.pack_forget()
        self.explain_box.pack_forget()
        if app.scene is None:
            self.title.config(text="No scene open")
            self.sub.config(text="")
            self.desc.config(text="Pick a scene in the browser, or search for what someone says.")
            return
        sc = app.scene
        self.title.config(text="Scene @0x%04x" % sc.entry_pc)
        self.sub.config(text="%d statements" % len(sc.stmts))
        self.desc.config(text="Click a line to edit it. Up/Down move between lines, Enter edits the "
                              "selected one, Del removes it. Hold Alt over a line for everything "
                              "known about it. The Source tab edits the whole scene as text.")

    # ---- dialogue ---------------------------------------------------------------- #
    def _dialog_form(self, st, txt):
        app, f = self.app, self.form
        lid = st.dialog_id
        spk = app.speaker_before(st.pc)
        self._header("Dialogue line #%d" % lid, st, "Shows one line of dialogue and waits for the player")
        ttk.Label(f, text="Spoken by: " + (spk or "(narration — no SetSpeaker before it)"),
                  foreground="#555").pack(anchor="w", padx=8)
        trow = ttk.Frame(f)
        trow.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(trow, text="Text (%s)" % app.doc.locale).pack(side="left")
        box = tk.Text(f, height=5, wrap="word", font=("Segoe UI", 10), undo=True)
        box.pack(fill="x", padx=8)
        cur = app.doc.text(lid)
        box.insert("1.0", textesc.to_edit(cur or ""))      # colours / icons as \red, \btn(a) ...
        box.edit_modified(False)
        check = ttk.Label(f, text="", wraplength=330, justify="left")
        check.pack(anchor="w", padx=8)
        colours = {"error": "#c0392b", "warning": "#b9770e", "info": "#666"}

        def recheck(_e=None):
            bad = textesc.check(box.get("1.0", "end-1c"))
            if bad is not None:
                check.config(text="• error: %s" % bad, foreground=colours["error"])
                return
            issues = textlint.lint(textesc.from_edit(box.get("1.0", "end-1c")), slots=app.scene_slots())
            if not issues:
                check.config(text="")
                return
            worst = issues[0].level
            for lvl in ("error", "warning"):
                if any(x.level == lvl for x in issues):
                    worst = lvl
                    break
            check.config(text=textlint.format_issues(issues, limit=4), foreground=colours[worst])
        box.bind("<KeyRelease>", recheck, add="+")
        recheck()
        import text_tab
        im = text_tab.insert_menu(trow, box, after=recheck)
        im.pack(side="right")
        Tip(im, "Put a colour, a raise / lower, a button icon or a ＠ code at the cursor. Characters "
                "that can't be typed are written as backslash escapes (\\red, \\btn(a) ...); a "
                "real backslash is \\\\.")

        def commit(_e=None):
            try:
                new = textesc.from_edit(box.get("1.0", "end-1c"))
            except textesc.EscapeError:
                recheck()                                   # shows the error; nothing is changed
                return "break" if _e is not None and _e.keysym == "Return" else None
            if app.doc.text(lid) is not None and new != app.doc.text(lid):
                app.set_text(lid, new)
            return "break" if _e is not None and _e.keysym == "Return" else None
        box._commit = commit
        box.bind("<FocusOut>", commit)
        box.bind("<Control-Return>", commit)
        self.primary = box
        if cur is None:
            hint(f, "This line id has no text in %s. Retarget the line, or switch locale." % app.doc.locale,
                 wrap=330).pack(anchor="w", padx=8)
        hint(f, "Edits apply when you leave the box (or Ctrl+Enter). Other scenes that show the same "
                "line change too.", wrap=330).pack(anchor="w", padx=8)
        r = ttk.Frame(f)
        r.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(r, text="Line id").pack(side="left")
        v = tk.StringVar(value=str(lid))
        e = commit_entry(r, v, lambda: (to_int(v.get()) is not None and to_int(v.get()) != lid
                                        and app.retarget(st.pc, to_int(v.get()))), width=8)
        e.pack(side="left", padx=4)
        Tip(e, "Point this DIALOG at another line (Enter). The text box then shows that line.")
        b = ttk.Button(r, text="Find a line…", command=lambda: app.pick_line(lambda n: app.retarget(st.pc, n)))
        b.pack(side="left", padx=2)
        Tip(b, "Search the dialogue archive for an existing line and point this DIALOG at it.")
        b2 = ttk.Button(r, text="As new line", command=lambda: app.detach_line(st.pc, box.get("1.0", "end-1c")))
        b2.pack(side="left", padx=2)
        Tip(b2, "Save the text box as a NEW line (added to every locale) and point this DIALOG at "
                "it, so other scenes sharing the old line keep their text.")
        tr = ttk.Frame(f)
        tr.pack(fill="x", padx=8, pady=(6, 0))
        out = ttk.Label(f, font=("Segoe UI", 8), wraplength=330, justify="left", foreground="#333")

        def translations():
            lines = []
            for loc, arc in sorted(app.doc.other_locales().items()):
                try:
                    t = arc.text(lid)
                except Exception:
                    t = None
                lines.append("%s: %s" % (loc, (t or "(missing)").replace("\n", " ⏎ ")))
            out.config(text="\n".join(lines) or "(no other locale in this source)")
            out.pack(anchor="w", padx=8)
        tb = ttk.Button(tr, text="Show other locales", command=translations)
        tb.pack(side="left")
        Tip(tb, "Show this line in every other rf3mc.<locale> (same line id).")

    # ---- speaker ------------------------------------------------------------------- #
    def _speaker_form(self, st, txt):
        app, f = self.app, self.form
        name, side, _c = txt.speaker_of(st)
        slot, par = script.portrait_speaker_slot(st.op)
        self._header("%s speaks (%s)" % (name, side), st,
                     "Sets who speaks the following lines and on which side their portrait shows; "
                     "it lasts until the next speaker op or EndDialogue")
        r = ttk.Frame(f)
        r.pack(fill="x", padx=8, pady=(4, 0))
        ttk.Label(r, text="Speaker").pack(side="left")
        choices = speaker_choices()
        combo = FilterCombo(r, choices, None, width=26)
        combo.var.set(choices[slot] if slot < len(choices) else str(slot))
        combo.pack(side="left", padx=4, fill="x", expand=True)
        Tip(combo, "Who speaks the next lines (type to filter); applied at once.")
        sv = tk.StringVar(value=side)

        def apply(*_a):
            s = to_int((combo.var.get().split() or ["x"])[0])
            if s is None:
                return
            new_side = 1 if sv.get() == "right" else 0
            if (s, new_side) != (slot, par):
                app.set_speaker(st.pc, s, new_side)
        combo._on_pick = lambda _t: apply()
        sr = ttk.Frame(f)
        sr.pack(fill="x", padx=8, pady=(4, 0))
        ttk.Label(sr, text="Portrait side").pack(side="left")
        for s in ("left", "right"):
            rb = ttk.Radiobutton(sr, text=s, value=s, variable=sv, command=apply)
            rb.pack(side="left", padx=4)
            Tip(rb, "Which side of the dialogue box the portrait shows on.")
        self.primary = combo
        hint(f, "The speaker is part of the opcode, so changing it keeps the arguments below.",
             wrap=330).pack(anchor="w", padx=8, pady=(2, 0))
        if st.args:
            fr = ttk.Frame(f)
            fr.pack(fill="x", padx=8, pady=(6, 0))
            ttk.Label(fr, text="Face").pack(side="left")
            from .dialogs import FacePicker
            cur = script.static_arg(app.bank, st, 0)
            fp = FacePicker(fr, on_change=lambda v: v != cur and app.set_arg(st.pc, 0, str(v)),
                            reader=app.doc.reader)
            fp.frame.pack(side="left", padx=4)
            fp.set_slot(slot)
            if cur is not None:
                fp.set_value(cur)
        self._arg_rows(st, txt)

    # ---- action -------------------------------------------------------------------- #
    def _action_form(self, st, txt):
        from . import argspec as _argspec
        desc = script.opcode_describe(st.op) or ""
        self._header(script.opcode_mnemonic(st.op), st, _argspec.clean_help(desc) or desc)
        bad = [script.meta.arg_count_problem(st.op, len(st.args))]
        bad += [script.meta.arg_value_problem(st.op, i, v) for i, v in
                ((i, script.static_arg(self.app.bank, st, i)) for i in range(len(st.args))) if v is not None]
        for why in filter(None, bad):  # only the Source tab can write these; Save asks first
            ttk.Label(self.form, text="⚠ " + why + ". Save will ask before keeping it.",
                      foreground="#b00020", wraplength=330, justify="left").pack(anchor="w", padx=8, pady=(4, 0))
        if 93 <= st.op <= 97:                       # the message-box style
            app = self.app
            from .dialogs import BoxStylePicker
            r = ttk.Frame(self.form)
            r.pack(fill="x", padx=8, pady=(6, 0))
            ttk.Label(r, text="Box style").pack(side="left")
            if st.op == 93:
                cur = script.static_arg(app.bank, st, 0) if st.args else None
                bp = BoxStylePicker(r, reader=app.doc.reader,
                                    on_change=lambda v: app.set_arg(st.pc, 0, str(v)))
                if cur is not None:
                    bp.set_value(cur)
            else:
                bp = BoxStylePicker(r, reader=app.doc.reader, allow=(0, 1, 2, 3),
                                    on_change=lambda v: app.set_opcode(st.pc, 94 + v))
                bp.set_value(st.op - 94)
                hint(self.form, "Tail only (4) needs SetDialogueBoxStyle (op 93).",
                     wrap=330).pack(anchor="w", padx=8)
            bp.frame.pack(side="left", padx=4)
            ok, note = app.tail_note(st.pc)
            if note:
                ttk.Label(self.form, text=("" if ok else "⚠ ") + note, wraplength=330, justify="left",
                          foreground="#555" if ok else "#b36200").pack(anchor="w", padx=8, pady=(4, 0))
        self._arg_rows(st, txt)
        emf = txt.emf_hint(st)
        if emf:
            box = section(self.form, "Event Manager")
            ttk.Label(box, text=emf, font=("Segoe UI", 8), wraplength=320, justify="left").pack(anchor="w")
            ttk.Button(box, text="Open the Event Manager", command=self.app.open_event_manager).pack(anchor="w", pady=(4, 0))

    def _arg_rows(self, st, txt):
        """One control per argument: a list (named / common values, characters, maps, items;
        type into it too) where the argument has values to pick, else a text box -- filled
        with the listing form (actor(Forte), not tag3(4)). Below it only what the control
        doesn't already say: the value's meaning, the help, the flag a leaf names."""
        app, f = self.app, self.form
        if not st.args:
            hint(f, "(this action takes no arguments)").pack(anchor="w", padx=8, pady=4)
            self.primary = None
            return
        box = section(f, "Arguments")
        buf = app.bank.data
        vals = txt.arg_strs(st)
        self.primary = None
        from . import argspec
        for i, off in enumerate(st.args):
            v = vals[i] if i < len(vals) else ""
            nm, hint_txt = txt.arg_name(st.op, i, v)
            sp = argspec.spec(st.op, i)
            by_value = nm in ("target", "voice sfx id", "emote/mood")   # SetSpeaker names these by value
            if not by_value:
                nm, hint_txt = sp.label, sp.help
            if script.meta.arg_verified(st.op, i):
                nm += " ✓"
            lab = ttk.Label(box, text=nm, anchor="w", font=("Segoe UI", 9, "bold"))
            lab.pack(anchor="w", pady=(6, 0))
            row = ttk.Frame(box)
            row.pack(fill="x", padx=(8, 0))
            Tip(lab, (argspec.clean_help(sp.raw_help) or sp.help or nm)
                + ("\n\n✓ = verified in game" if nm.endswith("✓") else ""))
            raw = scriptasm.call_arg(scriptasm.operand_text(buf, off, st.op, i))
            named = script.arg_repr(buf, off, st.op, i)
            # a tag3 / tag4 constant reads as the actor / map it names (it assembles to the same)
            text = named if raw.startswith("tag") and named.startswith(("actor(", "map(")) else raw
            num, is_const = script.arg_constant(buf, off)
            opts = [] if (by_value or sp.kind == "face") else list(sp.options)
            notes = []
            if opts:
                disp = next((d for d, t in opts if t in (raw, named, text)), None)
                if disp is None and is_const:
                    disp = next((d for d, _t in opts if to_int(d.split()[0]) == num), None)

                def commit(t, i=i, sp=sp):
                    t = (t or "").strip()
                    return bool(t) and app.set_arg(st.pc, i, sp.token(t))
                pick = FilterCombo(row, [d for d, _t in opts], commit, width=30)
                pick.var.set(disp if disp is not None else text)
                shown = pick.var.get()

                def settle(pick=pick, commit=commit, sp=sp, opts=dict(opts), shown=shown):
                    """Losing focus (or Ctrl+S) keeps a typed value like a text box does: a
                    listed value, a number or a time applies; half-typed filter text is put back."""
                    t = pick.var.get().strip()
                    if t == shown:
                        return
                    if t in opts or re.fullmatch(r"-?(0x[0-9A-Fa-f]+|\d+)", t) or (
                            sp.unit is not None and sp.unit.parse(t) is not None):
                        commit(t)
                    else:
                        pick.var.set(shown)

                def away(_e=None, pick=pick, settle=settle):
                    def check():                       # still inside (its drop-down list): wait
                        try:
                            f = pick.focus_get()
                        except (KeyError, tk.TclError):
                            f = None
                        if f is None or not str(f).startswith(str(pick)):
                            settle()
                    pick.after(30, check)
                pick.bind("<FocusOut>", away, add="+")
                pick._commit = settle                  # flush_edits (Ctrl+S, switching scene)
                pick.pack(side="left", fill="x", expand=True)
                Tip(pick, "Pick a value (type to filter), or type one -- a number, an expression"
                          + (", or seconds (1.5 s)" if sp.unit is not None else "") + " -- and press Enter.")
                ctl = pick
                if disp is None:                     # an expression / unlisted value: say what it is
                    m = sp.note(text) or (("= " + txt.value_label(st.op, i, v, nm)) if txt.value_label(st.op, i, v, nm) else None)
                    if m:
                        notes.append(m)
            else:
                var = tk.StringVar(value=text)
                e = commit_entry(row, var, lambda i=i, var=var, sp=sp: app.set_arg(st.pc, i, sp.token(var.get())),
                                 width=14)
                e.pack(side="left", fill="x", expand=True)
                Tip(e, "A number, actor(Forte), map(MAP_CITY_00), (FLG_X + 1), a named value"
                       + (", seconds (1.5 s)" if sp.unit is not None else "") + ". Enter applies.")
                ctl = e
                lbl = txt.value_label(st.op, i, v, nm)
                m = ("= " + lbl) if lbl else sp.note(text)
                if m:
                    notes.append(m)
                if sp.kind == "face" and script.portrait_speaker_slot(st.op) is None:
                    self._face_picker(box, st, i, var)
                elif not by_value:
                    self._typed_picker(box, st, i, var)
            if self.primary is None:
                self.primary = ctl
            notes += [n for n in txt.arg_notes(st, i) if not n.startswith("= ")]   # flag notes
            if hint_txt:
                short = hint_txt.split("; ")[0].split(". ")[0].rstrip(".")
                notes.append(short + ("…" if len(short) < len(hint_txt.rstrip(".")) else ""))
            if notes:
                ttk.Label(box, text="\n".join(notes), font=("Segoe UI", 8), foreground="#2a6a8a",
                          wraplength=280, justify="left").pack(anchor="w", padx=(8, 0))

        self._map_button(box, st, buf)

    def _face_picker(self, box, st, i, var):
        """The portrait face as pictures: the speaker the opcode names (SetSpeaker family)
        or the character argument (ShowPortrait, ids 0-23)."""
        from . import argspec
        from .dialogs import FacePicker
        src = argspec.portrait_slot_of_arg(st.op, i)
        slot = None
        if src == "op":
            slot = script.portrait_speaker_slot(st.op)[0]
        elif isinstance(src, int) and src < len(st.args):
            c = script.static_arg(self.app.bank, st, src)
            slot = c if c is not None and 0 <= c <= 23 else None
        if slot is None:
            return
        fp = FacePicker(box, on_change=lambda v: self.app.set_arg(st.pc, i, str(v)), reader=self.app.doc.reader)
        fp.set_slot(slot)
        try:
            fp.set_value(int(var.get().strip(), 0))
        except ValueError:
            pass
        fp.frame.pack(anchor="w", padx=(8, 0), pady=(2, 0))

    def _typed_picker(self, box, st, i, var):
        """A character / map / item picker under an argument the table types as one."""
        from . import toolbox
        r = script.meta.table_row(st.op) or {}
        args = r.get("args") or []
        a = args[i] if i < len(args) else (args[-1] if args else {"name": ""})
        kind, opts, _d = toolbox._arg_spec(st.op, i, a)
        if kind not in ("actor", "map", "item") or not opts:
            return
        tok = dict(opts)
        # the entry holds the raw tag3(N) / tag4(N); the picker lists the named form
        named = script.arg_repr(self.app.bank.data, st.args[i], st.op, i) if i < len(st.args) else ""
        cur = next((d for d, t in opts if t in (var.get().strip(), named)), "")
        pick = FilterCombo(box, [d for d, _t in opts],
                           lambda d, i=i: d in tok and self.app.set_arg(st.pc, i, tok[d]), width=34)
        pick.var.set(cur)
        pick.pack(fill="x", padx=(8, 0))
        Tip(pick, "Pick a %s (type to filter); it is applied at once." % {
            "actor": "character", "map": "map", "item": "item"}[kind])

    def _map_button(self, box, st, buf):
        """'Pick on map…' for an x / y argument pair (SpawnEventActor, moves, warps, …)."""
        from . import toolbox
        r = script.meta.table_row(st.op) or {}
        pairs = [(ix, iy) for ix, iy in toolbox.coordinate_pairs(r.get("args") or [])
                 if iy < len(st.args)]
        if not pairs:
            return
        ix, iy = pairs[0]
        app = self.app

        def cur(i):
            if i is None or i >= len(st.args):
                return None
            t = scriptasm.call_arg(scriptasm.operand_text(buf, st.args[i], st.op, i))
            if t.startswith("map(") and t.endswith(")"):
                return script.map_leaf_value(t[4:-1])
            v, ok = script.arg_constant(buf, st.args[i])
            return v if ok else None

        def open_picker():
            mid, lock, note, mi = toolbox.position_map(st.op, r.get("args") or [], cur, app.bank)

            ctx = (app.bank_pos, app.scene.entry_pc if app.scene is not None else None, st.pc, st.op)

            def done(x, y, chosen):
                cur_st = app.stmt(ctx[2])
                if (app.bank_pos, app.scene.entry_pc if app.scene is not None else None) != ctx[:2] \
                        or cur_st is None or cur_st.op != ctx[3]:
                    app.status("The scene changed since Pick on the map opened: nothing was set")
                    return
                app.set_arg(st.pc, ix, str(x))
                app.set_arg(st.pc, iy, str(y))
                if mi is not None and mid is None and chosen is not None and mi < len(st.args):
                    app.set_arg(st.pc, mi, script.map_leaf_text(chosen)
                                if script.leaf_slot_kind(st.op, mi) == "map" else str(chosen))
            return toolbox.MapPointPicker(box, mid, cur(ix), cur(iy), done, lock=lock, note=note)
        b = ttk.Button(box, text="📍 Pick x / y on the map…", command=open_picker)
        b.pack(anchor="w", padx=(8, 0), pady=(6, 0))
        Tip(b, "Show the map and click the new position (1/8-tile units). The map is the one "
               "the instruction runs on: its map argument, else this bank's map; only a scene "
               "not tied to a map lets you choose.")

    # ---- condition / flow ------------------------------------------------------------ #
    def _control_form(self, st, txt):
        app, f = self.app, self.form
        words = {"BR_Z": "Jump when the condition is FALSE", "BR_NZ": "Jump when the condition is TRUE",
                 "JMP": "Jump", "CALL": "Call a subroutine, then continue here",
                 "EVAL": "Write a flag, register or variable", "FRAME": "Scene setup",
                 "SWITCH": "Jump by value", "SWITCH_CLAMP": "Jump by threshold",
                 "JMP_WEIGHTED": "Jump to a random target, by weight", "JMP_RAND": "Jump to a random target",
                 "RET": "Return", "RET_NZ": "Return when the condition is TRUE"}
        desc = script.control_tooltip(st.mnem) or ""
        desc = desc.split("\n", 1)[1] if "\n" in desc else desc
        self._header(words.get(st.mnem, st.mnem), st, desc)
        exprs = txt.expr_texts(st)
        self.primary = None
        if exprs:
            box = section(f, {"EVAL": "Value", "SWITCH": "Picks by the value of",
                              "SWITCH_CLAMP": "Picks by the value of",
                              "JMP_WEIGHTED": "Weights"}.get(st.mnem, "Condition"))
            for x in (exprs if st.mnem != "JMP_WEIGHTED" else ()):    # weights: in the table below
                ttk.Label(box, text=x, font=("Consolas", 9), wraplength=320, justify="left").pack(anchor="w")
            lits = []
            for e in st.expr_refs or ():
                if e is not None:
                    lits.extend(script.expr_literals(app.bank.data, e))
            for k, (off, val, _w) in enumerate(lits):
                r = ttk.Frame(box)
                r.pack(fill="x", pady=(3, 0))
                ttk.Label(r, text=("weight %d" if st.mnem == "JMP_WEIGHTED" else "number %d") % (k + 1),
                          width=10).pack(side="left")
                var = tk.StringVar(value=str(val))
                e = commit_entry(r, var, lambda k=k, var=var, val=val: (to_int(var.get()) is not None
                                                                     and to_int(var.get()) != val
                                                                     and app.set_literal(st.pc, k, to_int(var.get()))),
                                 width=10)
                e.pack(side="left")
                Tip(e, "Change this number in the expression (Enter applies).")
                if self.primary is None:
                    self.primary = e
            if st.mnem == "JMP_WEIGHTED":
                note = "Change a weight here (Enter applies). Use Edit (F2) for a weight that reads game state."
            elif st.mnem in ("SWITCH", "SWITCH_CLAMP"):
                note = ("Change a number here (Enter applies). To change what it reads, use Edit "
                        "(F2).") if lits else ""   # e.g. reg0: nothing to edit
            else:
                note = ("Change a number here (Enter applies). To change the condition itself, use "
                        "Edit (F2).")
            if note:
                hint(box, note, wrap=320).pack(anchor="w", pady=(4, 0))
        if st.mnem in ("SWITCH", "SWITCH_CLAMP", "JMP_RAND", "JMP_WEIGHTED"):
            self._jump_table(st, txt)
            return
        tg = [t for t in st.code_targets if t is not None]
        if tg:
            box = section(f, "Goes to")
            for t in tg:
                ttk.Button(box, text="%s  (0x%04x)" % (txt.target(t), t),
                           command=lambda t=t: app.goto(t)).pack(anchor="w", pady=1)

    # ---- jump tables: SWITCH, SWITCH_CLAMP, JMP_RAND, JMP_WEIGHTED ------------------------ #
    def _target_text(self, txt, t, width=44):
        """'L3 · FadeScreen(-16, 6000)': the target's label and the statement it starts with."""
        if t is None:
            return "?"
        first = self._first_words(txt, script.decode_statement(self.app.bank.data, t))
        s = "%s · %s" % (txt.target(t), first) if first else txt.target(t)
        return s if len(s) <= width else s[:width - 1] + "…"

    @staticmethod
    def _first_words(txt, st):
        """A statement in a few plain words (flow in words, actions as the Script tab names
        them): the preview on a jump-table button."""
        if st is None:
            return ""
        m, x = st.mnem, txt.expr_texts(st)
        x0 = x[0] if x else "?"
        tgt = txt.target(st.code_targets[0]) if st.code_targets else "?"
        try:
            words = {"BR_Z": lambda: "if not %s → %s" % (x0, tgt),
                     "BR_NZ": lambda: "if %s → %s" % (x0, tgt),
                     "EVAL": lambda: x0.strip("()"),
                     "CALL": lambda: "call %s" % tgt,
                     "JMP": lambda: "jump to %s" % tgt,
                     "RET": lambda: "return",
                     "RET_NZ": lambda: "return if %s" % x0,
                     "FRAME": lambda: "scene setup",
                     "DIALOG": lambda: "“%s”" % " ".join(
                         (txt.dlg(st.dialog_id) or "#%s" % st.dialog_id).split()),
                     "SWITCH": lambda: "switch on %s" % x0, "SWITCH_CLAMP": lambda: "switch on %s" % x0,
                     "JMP_RAND": lambda: "random jump", "JMP_WEIGHTED": lambda: "weighted random jump",
                     "PROMPT_CHOICE": lambda: "choice menu", "PROMPT_CHOICE_FORCED": lambda: "choice menu"}.get(m)
            return words() if words else txt.code_line(st)[7:].strip()
        except Exception:  # noqa: BLE001 -- a preview only
            return ""

    def _choice_before(self, st, txt):
        """{reg0 value: option text} when a SWITCH on reg0 follows a choice menu that writes
        reg0 (a visibility mask before it); {} otherwise."""
        if txt.expr_texts(st)[:1] != ["reg0"] or self.app.scene is None:
            return {}
        before = [s for s in sorted(self.app.scene.stmts.values(), key=lambda s: s.pc)
                  if s.pc < st.pc and s.mnem in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED")]
        if not before or txt.choice_results(before[-1]) is None:
            return {}
        out = {}
        for k, item, _t in txt.choice_options(before[-1]):
            line = self.app.doc.text(item)
            if line is not None:
                line = line.replace("\n", " ")
                out[k] = "“%s”" % (line if len(line) <= 28 else line[:27] + "…")
        return out

    def _jump_table(self, st, txt):
        """'Goes to' as a table: which value (or chance) leads to which target, each target
        a button with its first statement; values sharing a target on one row."""
        app, m = self.app, st.mnem
        tg = list(st.code_targets)
        n = len(tg)
        rows = []                                   # (left text, note, target)
        if m in ("SWITCH", "SWITCH_CLAMP"):
            title = "Goes to — by value"
            opts = self._choice_before(st, txt)
            order, vals = [], {}
            for k, t in enumerate(tg):              # values sharing a target: one row
                if t not in vals:
                    order.append(t)
                vals.setdefault(t, []).append(k)
            for t in order:
                ks = vals[t]
                last = m == "SWITCH_CLAMP" and ks[-1] == n - 1
                left = "= " + ", ".join(str(k) for k in ks) + (" or more" if last else "")
                note = ", ".join(opts[k] for k in ks if k in opts)
                if last:
                    note = (note + "  " if note else "") + "(negative values too)"
                rows.append((left, note, t))
            if m == "SWITCH":
                rows.append(("other values", "anything else, negative too: carries on below",
                             st.pc + st.size))
        elif m == "JMP_RAND":
            title = "Goes to — at random"
            rows = [("1 in %d" % n, "", t) for t in tg]
        else:                                       # JMP_WEIGHTED
            title = "Goes to — at random, by weight"
            buf = app.bank.data
            ws = []
            for e in st.expr_refs or ():
                v, ok = script.eval_expr(buf, e) if e is not None else (None, False)
                ws.append((script.disasm_expr(buf, e)[0] if e is not None else "?", v if ok else None))
            total = sum(v for _x, v in ws if v is not None) if all(v is not None for _x, v in ws) else None
            for k, t in enumerate(tg):
                x, v = ws[k] if k < len(ws) else ("?", None)
                pct = ("  %d%%" % round(100 * v / total)) if total and v is not None else ""
                rows.append(("weight %s" % x, pct.strip(), t))
            if total is None:
                rows.append(("", "a weight reads game state: the chances change in play", None))
        box = section(self.form, title)
        box.columnconfigure(2, weight=1)
        for r, (left, note, t) in enumerate(rows):
            if left:
                ttk.Label(box, text=left, font=("Consolas", 9)).grid(row=2 * r, column=0, sticky="w", padx=(0, 6))
            if t is not None:
                b = ttk.Button(box, text="→ " + self._target_text(txt, t),
                               command=lambda t=t: app.goto(t))
                b.grid(row=2 * r, column=1, columnspan=2, sticky="w", pady=1)
                Tip(b, "Go to 0x%04x" % t)
            if note:
                ttk.Label(box, text=note, foreground="#777", wraplength=300, justify="left").grid(
                    row=2 * r + 1, column=1, columnspan=2, sticky="w", pady=(0, 3))

    # ---- choice ------------------------------------------------------------------------- #
    def _choice_form(self, st, txt, option):
        app, f = self.app, self.form
        self._header("Choice (%d options)" % len(st.items or ()), st,
                     "Shows a choice menu and jumps to the picked option's target")
        self.primary = None
        res = txt.choice_results(st)
        if res is not None:
            hint(f, "A visibility mask is set right before this menu, so picking an option also "
                    "writes its number (counted from 0, hidden options included) to reg0 -- "
                    "scenes then usually SWITCH on reg0. Without a mask reg0 is left as it was.",
                 wrap=340).pack(anchor="w", padx=8, pady=(4, 0))
        for k, item, tgt in txt.choice_options(st):
            box = section(f, "Option %d" % (k + 1) + txt.reg0_text(res, k)
                          + ("  (selected)" if option == k else ""))
            tv = tk.StringVar(value=textesc.to_edit(app.doc.text(item) or ""))

            def commit_option(item=item, tv=tv):
                if app.doc.text(item) is None:
                    return False
                try:
                    new = textesc.from_edit(tv.get())   # \red, \btn(a) ... -> the game's codes
                except textesc.EscapeError as ex:
                    app.status("Option text: %s" % ex)
                    return False
                return new != app.doc.text(item) and app.set_text(item, new)
            e = commit_entry(box, tv, commit_option, width=40)
            e.pack(fill="x")
            Tip(e, "This option's text (Enter applies; it edits the line everywhere it is used).")
            if option == k or (option is None and self.primary is None):
                self.primary = e
            r = ttk.Frame(box)
            r.pack(fill="x", pady=(2, 0))
            ttk.Label(r, text="line id").pack(side="left")
            iv = tk.StringVar(value=str(item))
            ie = commit_entry(r, iv, lambda k=k, iv=iv, item=item: (to_int(iv.get()) is not None
                                                                   and to_int(iv.get()) != item
                                                                   and app.set_choice_item(st.pc, k, to_int(iv.get()))),
                              width=8)
            ie.pack(side="left", padx=4)
            Tip(ie, "Point this option at another dialogue line (Enter).")
            gb = ttk.Button(r, text="→ " + txt.target(tgt), command=lambda t=tgt: app.goto(t))
            gb.pack(side="right")
            Tip(gb, "Jump to where the scene continues when this option is picked.")

    # ---- focus -------------------------------------------------------------------------- #
    def focus_primary(self):
        w = getattr(self, "primary", None)
        if w is not None:
            try:
                w.focus_set()
                if isinstance(w, tk.Text):
                    w.mark_set("insert", "end-1c")
            except tk.TclError:
                pass
