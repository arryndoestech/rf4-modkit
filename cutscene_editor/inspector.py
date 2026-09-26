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

import tkinter as tk
from tkinter import ttk

from guiutil import FilterCombo, ScrollFrame, Tip, commit_entry, hint, section, set_text, to_int
from rf4s_modkit import script, scriptasm, textlint

from .render import CHOICE_OPS, SceneText

SPEAKER_CHOICES = ["%d  %s" % (i, t if t == n else "%s (%s)" % (t, n))
                   for i, (t, n) in enumerate(zip(script.PORTRAIT_SPEAKER_TAGS, script.PORTRAIT_SPEAKERS))]


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
        def add_menu(text, before):
            mb = ttk.Menubutton(self.actions, text=text)
            m = tk.Menu(mb, tearoff=False)
            m.add_command(label="Dialogue line…", command=lambda: app.ask_insert_dialogue(before))
            m.add_command(label="Statements (listing)…", command=lambda: app.ask_insert_listing(before))
            mb["menu"] = m
            return mb
        self.before_mb = add_menu("Add before", True)
        Tip(self.before_mb, "Insert new beats just before the selected statement: every path that "
                            "reaches it -- the line above, and every jump to it -- runs them first. "
                            "Nothing existing moves: the statement becomes a jump to the new code.")
        self.after_mb = add_menu("Add after", False)
        self.after_tip = Tip(self.after_mb, "")
        self.del_btn = ttk.Button(self.actions, text="Delete", width=7, command=app.delete_selected)
        Tip(self.del_btn, "Skip this statement (the scene jumps over it; byte-safe). Del key.")
        self.callers_btn = ttk.Button(self.actions, text="Callers…", width=9, command=app.show_callers)
        Tip(self.callers_btn, "Every CALL / jump / branch / choice in this bank that leads to the "
                              "selected statement or label (or to the scene when nothing is selected).")
        self._pack_actions(label=False)
        self.explain_box = section(b, "What it does")
        self.explain = tk.Text(self.explain_box, height=12, wrap="word", font=("Consolas", 8),
                               relief="flat", bg="#f4f4f6")
        self.explain.pack(fill="both", expand=True)
        self.explain.configure(state="disabled")
        self.bind_wheel_tree()
        self.show(None)

    AFTER_TIP = ("Insert new beats right after the selected statement. Nothing existing moves: "
                 "the statement becomes a jump to the new code, which jumps back.")
    AFTER_LABEL_TIP = ("Insert new beats at this label: they run first on every path that reaches "
                       "it -- each jump to the label and the line above falling through.")

    def _pack_actions(self, label):
        """Add before / Add after / Delete / Callers…; a label gets Add after + Callers… only."""
        for w in (self.before_mb, self.after_mb, self.del_btn, self.callers_btn):
            w.pack_forget()
        shown = (self.after_mb, self.callers_btn) if label else \
                (self.before_mb, self.after_mb, self.del_btn, self.callers_btn)
        for i, w in enumerate(shown):
            w.pack(side="left", padx=(0 if i == 0 else 4, 0))
        self.after_tip.text = self.AFTER_LABEL_TIP if label else self.AFTER_TIP

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
        self.desc.config(text="Add after puts new lines here: they play first on every path that "
                              "reaches %s. To add after the statement below it instead, select "
                              "that statement." % name)

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
        ttk.Label(f, text="Text (%s)" % app.doc.locale).pack(anchor="w", padx=8, pady=(6, 0))
        box = tk.Text(f, height=5, wrap="word", font=("Segoe UI", 10), undo=True)
        box.pack(fill="x", padx=8)
        cur = app.doc.text(lid)
        box.insert("1.0", cur or "")
        box.edit_modified(False)
        check = ttk.Label(f, text="", wraplength=330, justify="left")
        check.pack(anchor="w", padx=8)
        colours = {"error": "#c0392b", "warning": "#b9770e", "info": "#666"}

        def recheck(_e=None):
            issues = textlint.lint(box.get("1.0", "end-1c"), slots=app.scene_slots())
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

        def commit(_e=None):
            new = box.get("1.0", "end-1c")
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
        combo = FilterCombo(r, SPEAKER_CHOICES, None, width=26)
        combo.var.set(SPEAKER_CHOICES[slot] if slot < len(SPEAKER_CHOICES) else str(slot))
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
        self._header(script.opcode_mnemonic(st.op), st, script.opcode_describe(st.op))
        bad = script.meta.arg_count_problem(st.op, len(st.args))
        if bad:                  # the game would read a missing argument as leftover memory
            ttk.Label(self.form, text="⚠ " + bad + ". Save refuses this; delete the statement "
                      "or add it again with the right arguments.", foreground="#b00020",
                      wraplength=330, justify="left").pack(anchor="w", padx=8, pady=(4, 0))
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
        app, f = self.app, self.form
        if not st.args:
            hint(f, "(this action takes no arguments)").pack(anchor="w", padx=8, pady=4)
            self.primary = None
            return
        box = section(f, "Arguments")
        buf = app.bank.data
        vals = txt.arg_strs(st)
        self.primary = None
        for i, off in enumerate(st.args):
            v = vals[i] if i < len(vals) else ""
            nm, hint_txt = txt.arg_name(st.op, i, v)
            row = ttk.Frame(box)
            row.pack(fill="x", pady=(3, 0))
            ttk.Label(row, text=nm, width=16, anchor="w", wraplength=112, justify="left").pack(side="left")
            var = tk.StringVar(value=scriptasm.call_arg(scriptasm.operand_text(buf, off, st.op, i)))
            e = commit_entry(row, var, lambda i=i, var=var: app.set_arg(st.pc, i, var.get()), width=14)
            e.pack(side="left", fill="x", expand=True)
            Tip(e, "Listing syntax: a number, actor(Forte), map(MAP_CITY_00), (FLG_X + 1), a "
                   "named value, or @0xNNNN to point at an existing expression. Enter applies.")
            if self.primary is None:
                self.primary = e
            choices = script.enum_arg_choices(st.op, i)
            notes = []
            lbl = txt.value_label(st.op, i, v, nm)
            if lbl:
                notes.append("= " + lbl)
            notes += txt.arg_notes(st, i)
            if hint_txt:
                notes.append(hint_txt)
            if choices:
                labels = ["%d  %s" % (val, lab) + (("  (%s)" % d) if d else "") for val, lab, d in choices]
                pick = FilterCombo(box, labels, lambda t, i=i: to_int(t.split()[0]) is not None
                                   and app.set_arg(st.pc, i, t.split()[0]), width=34)
                num, ok = script.arg_constant(buf, off)
                cur = next((s for s, (val, _l, _d) in zip(labels, choices) if ok and val == num), "")
                pick.var.set(cur)
                pick.pack(fill="x", padx=(110, 0))
                Tip(pick, "Pick a named value (type to filter); it is applied at once.")
            if notes:
                ttk.Label(box, text="\n".join(notes), font=("Segoe UI", 8), foreground="#2a6a8a",
                          wraplength=320, justify="left").pack(anchor="w", padx=(110, 0))

    # ---- condition / flow ------------------------------------------------------------ #
    def _control_form(self, st, txt):
        app, f = self.app, self.form
        words = {"BR_Z": "Jump when the condition is FALSE", "BR_NZ": "Jump when the condition is TRUE",
                 "JMP": "Jump", "CALL": "Call a subroutine, then continue here",
                 "STORE": "Write a flag, register or variable", "FRAME": "Scene setup",
                 "SWITCH_EQ": "Jump by value", "SWITCH_GE": "Jump by threshold",
                 "RAND_BR": "Jump to a random target", "RET": "Return"}
        desc = script.control_tooltip(st.mnem) or ""
        desc = desc.split("\n", 1)[1] if "\n" in desc else desc
        self._header(words.get(st.mnem, st.mnem), st, desc)
        exprs = txt.expr_texts(st)
        self.primary = None
        if exprs:
            box = section(f, "Value" if st.mnem == "STORE" else "Condition")
            for x in exprs:
                ttk.Label(box, text=x, font=("Consolas", 9), wraplength=320, justify="left").pack(anchor="w")
            lits = []
            for e in st.expr_refs or ():
                if e is not None:
                    lits.extend(script.expr_literals(app.bank.data, e))
            for k, (off, val, _w) in enumerate(lits):
                r = ttk.Frame(box)
                r.pack(fill="x", pady=(3, 0))
                ttk.Label(r, text="number %d" % (k + 1), width=10).pack(side="left")
                var = tk.StringVar(value=str(val))
                e = commit_entry(r, var, lambda k=k, var=var, val=val: (to_int(var.get()) is not None
                                                                     and to_int(var.get()) != val
                                                                     and app.set_literal(st.pc, k, to_int(var.get()))),
                                 width=10)
                e.pack(side="left")
                Tip(e, "Change this number in the expression (Enter applies).")
                if self.primary is None:
                    self.primary = e
            hint(box, "Numbers in the expression can be changed here. To change the condition "
                      "itself, edit the scene in the Source tab.", wrap=320).pack(anchor="w", pady=(4, 0))
        tg = [t for t in st.code_targets if t is not None]
        if tg:
            box = section(f, "Goes to")
            for t in tg:
                ttk.Button(box, text="%s  (0x%04x)" % (txt.target(t), t),
                           command=lambda t=t: app.goto(t)).pack(anchor="w", pady=1)

    # ---- choice ------------------------------------------------------------------------- #
    def _choice_form(self, st, txt, option):
        app, f = self.app, self.form
        self._header("Choice (%d options)" % len(st.items or ()), st,
                     "Shows a choice menu and jumps to the picked option's target")
        if st.mnem == "PROMPT_CHOICE" and st.code_targets:
            r = ttk.Frame(f)
            r.pack(fill="x", padx=8, pady=(4, 0))
            ttk.Label(r, text="Cancel slot (unused by the game)").pack(side="left")
            t0 = st.code_targets[0]
            cb = ttk.Button(r, text=txt.target(t0), command=lambda: app.goto(t0))
            cb.pack(side="left", padx=4)
            Tip(cb, "The CANCEL slot. The game never takes it: the cancel key moves the cursor "
                    "to the LAST option (and picks it if already there), so the last option "
                    "is the real cancel. Shipped menus repeat the last option's target here.")
        self.primary = None
        for k, item, tgt in txt.choice_options(st):
            box = section(f, "Option %d" % (k + 1) + ("  (selected)" if option == k else ""))
            tv = tk.StringVar(value=(app.doc.text(item) or ""))
            e = commit_entry(box, tv, lambda item=item, tv=tv: (app.doc.text(item) is not None
                                                                and tv.get() != app.doc.text(item)
                                                                and app.set_text(item, tv.get())), width=40)
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
