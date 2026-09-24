"""Modal prompts (listing, spec, new scene, new dialogue line, line picker) and the
callers window. Every prompt validates before it closes and shows errors inline."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from guiutil import FilterCombo, Tip, hint, later

from . import catalog
from .inspector import SPEAKER_CHOICES

DARK = dict(bg="#15151b", fg="#dcdce4", insertbackground="#dcdce4")


def _modal(parent, title):
    win = tk.Toplevel(parent)
    win.title(title)
    try:
        win.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass
    return win


def _run(win, focus):
    win.bind("<Escape>", lambda _e: win.destroy())
    focus.focus_set()
    try:
        win.grab_set()
    except tk.TclError:
        pass
    win.wait_window()


def ask_listing(parent, title, prompt, check, initial=""):
    """Multi-line listing prompt. `check(text)` returns an error string or None; OK only
    closes on a listing that assembles. Returns the text or None."""
    win = _modal(parent, title)
    ttk.Label(win, text=prompt, justify="left", font=("Segoe UI", 9)).pack(anchor="w", padx=8, pady=(8, 2))
    help_lbl = tk.Label(win, text=catalog.SOURCE_SYNTAX_HELP, justify="left", anchor="w",
                        font=("Consolas", 8), bg="#1b1b22", fg="#e6e6ee", padx=6, pady=4)
    body = ttk.Frame(win)
    body.pack(fill="both", expand=True, padx=8)
    txt = tk.Text(body, height=9, width=84, font=("Consolas", 10), undo=True, **DARK)
    txt.pack(fill="both", expand=True)
    txt.insert("1.0", initial or "")
    err = ttk.Label(win, text="", foreground="#b02020", wraplength=640, justify="left")
    err.pack(fill="x", padx=8, pady=(2, 0))
    out = {"text": None}
    shown = {"help": False}

    def ok(_e=None):
        t = txt.get("1.0", "end-1c")
        if not t.strip():
            err.config(text="type at least one statement (or Cancel)")
            return "break"
        e = check(t)
        if e:
            err.config(text=e)
            return "break"
        out["text"] = t
        win.destroy()

    def toggle():
        (help_lbl.pack_forget() if shown["help"] else help_lbl.pack(fill="x", padx=8, pady=(0, 4), before=body))
        shown["help"] = not shown["help"]
    bb = ttk.Frame(win)
    bb.pack(fill="x", padx=8, pady=6)
    ttk.Button(bb, text="Insert", command=ok).pack(side="right", padx=2)
    ttk.Button(bb, text="Cancel", command=win.destroy).pack(side="right", padx=2)
    ttk.Button(bb, text="Syntax help", command=toggle).pack(side="left")
    hint(bb, "Ctrl+Enter inserts").pack(side="left", padx=8)
    win.bind("<Control-Return>", ok)
    _run(win, txt)
    return out["text"]


def ask_spec(parent, title, prompt, validate, initial=""):
    """One-field prompt whose OK runs `validate(text)` first (errors inline)."""
    win = _modal(parent, title)
    ttk.Label(win, text=prompt, justify="left", wraplength=640, font=("Segoe UI", 9)).pack(
        anchor="w", padx=8, pady=(8, 4))
    txt = tk.Text(win, height=3, width=78, font=("Consolas", 10), undo=True, **DARK)
    txt.pack(fill="both", expand=True, padx=8)
    txt.insert("1.0", initial or "")
    err = ttk.Label(win, text="", foreground="#b02020", wraplength=640, justify="left")
    err.pack(fill="x", padx=8, pady=(2, 0))
    out = {"text": None}

    def ok(_e=None):
        t = txt.get("1.0", "end-1c").strip()
        if not t:
            err.config(text="type a spec (or Cancel)")
            return "break"
        try:
            validate(t)
        except Exception as ex:  # noqa: BLE001 - shown inline
            err.config(text=str(ex))
            return "break"
        out["text"] = t
        win.destroy()
    bb = ttk.Frame(win)
    bb.pack(fill="x", padx=8, pady=6)
    ttk.Button(bb, text="OK", command=ok).pack(side="right", padx=2)
    ttk.Button(bb, text="Cancel", command=win.destroy).pack(side="right", padx=2)
    win.bind("<Control-Return>", ok)
    _run(win, txt)
    return out["text"]


def ask_dialogue(parent, default_speaker=None):
    """'Add a dialogue line': optional speaker change + the text. Returns
    {'speaker': (slot, side) | None, 'text': str} or None."""
    win = _modal(parent, "Add a dialogue line")
    frm = ttk.Frame(win, padding=8)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="Speaker").grid(row=0, column=0, sticky="w")
    spk = FilterCombo(frm, ["(keep the current speaker)"] + SPEAKER_CHOICES, None, width=32)
    spk.var.set("(keep the current speaker)" if default_speaker is None else SPEAKER_CHOICES[default_speaker])
    spk.grid(row=0, column=1, sticky="we", padx=4)
    Tip(spk, "Pick a speaker to insert a SetSpeaker before the line, or keep the one already "
             "speaking.")
    side = tk.StringVar(value="left")
    sr = ttk.Frame(frm)
    sr.grid(row=1, column=1, sticky="w", padx=4)
    for s in ("left", "right"):
        ttk.Radiobutton(sr, text=s, value=s, variable=side).pack(side="left", padx=(0, 6))
    ttk.Label(frm, text="Text").grid(row=2, column=0, sticky="nw", pady=(6, 0))
    txt = tk.Text(frm, height=5, width=60, wrap="word", font=("Segoe UI", 10), undo=True)
    txt.grid(row=2, column=1, sticky="nsew", padx=4, pady=(6, 0))
    hint(frm, "The text becomes a new line in every locale (the others get it untranslated until "
              "you edit them).", wrap=460).grid(row=3, column=1, sticky="w", padx=4)
    frm.columnconfigure(1, weight=1)
    frm.rowconfigure(2, weight=1)
    err = ttk.Label(frm, text="", foreground="#b02020")
    err.grid(row=4, column=1, sticky="w")
    out = {}

    def ok(_e=None):
        t = txt.get("1.0", "end-1c")
        if not t.strip():
            err.config(text="type the line's text")
            return "break"
        choice = spk.var.get().split()
        s = None
        if choice and choice[0].isdigit():
            s = (int(choice[0]), 1 if side.get() == "right" else 0)
        out.update(speaker=s, text=t)
        win.destroy()
    bb = ttk.Frame(frm)
    bb.grid(row=5, column=0, columnspan=2, sticky="we", pady=(6, 0))
    ttk.Button(bb, text="Add line", command=ok).pack(side="right", padx=2)
    ttk.Button(bb, text="Cancel", command=win.destroy).pack(side="right", padx=2)
    win.bind("<Control-Return>", ok)
    _run(win, txt)
    return out or None


def pick_line(parent, doc):
    """Search the current locale's dialogue for a line; returns its id or None."""
    win = _modal(parent, "Find a dialogue line")
    win.geometry("720x460")
    top = ttk.Frame(win)
    top.pack(fill="x", padx=6, pady=6)
    ttk.Label(top, text="Contains").pack(side="left")
    q = tk.StringVar()
    e = ttk.Entry(top, textvariable=q)
    e.pack(side="left", fill="x", expand=True, padx=4)
    info = ttk.Label(win, text="type at least 2 characters, or a line id", foreground="#666")
    info.pack(anchor="w", padx=8)
    f = ttk.Frame(win)
    f.pack(fill="both", expand=True, padx=6, pady=4)
    lb = tk.Listbox(f, font=("Segoe UI", 9))
    sb = ttk.Scrollbar(f, command=lb.yview)
    lb.config(yscrollcommand=sb.set)
    lb.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    ids = []
    out = {"id": None}
    arc = doc.textarc
    cache = []                                  # [(id, lower text, text)], built once
    pending = {"id": None}

    def schedule(*_a):
        if pending["id"] is not None:
            win.after_cancel(pending["id"])
        pending["id"] = later(win, refill, 250)

    def refill(*_a):
        pending["id"] = None
        lb.delete(0, "end")
        ids.clear()
        s = q.get().strip()
        if arc is None:
            return
        if not cache:
            for i in range(len(arc)):
                t = doc.text(i) or ""
                cache.append((i, t.lower(), t))
        if s.isdigit():
            n = int(s)
            if 0 <= n < len(arc):
                ids.append(n)
                lb.insert("end", "#%d  %s" % (n, (doc.text(n) or "").replace("\n", " ⏎ ")))
            return
        if len(s) < 2:
            return
        sl = s.lower()
        for i, low, t in cache:
            if sl in low:
                ids.append(i)
                lb.insert("end", "#%d  %s" % (i, t.replace("\n", " ⏎ ")[:140]))
                if len(ids) >= 400:
                    break
        info.config(text="%d match%s%s" % (len(ids), "" if len(ids) == 1 else "es",
                                          " (first 400)" if len(ids) >= 400 else ""))

    def ok(_e=None):
        s = lb.curselection()
        if s:
            out["id"] = ids[s[0]]
            win.destroy()
    q.trace_add("write", schedule)
    lb.bind("<Double-Button-1>", ok)
    lb.bind("<Return>", ok)
    bb = ttk.Frame(win)
    bb.pack(fill="x", padx=6, pady=6)
    ttk.Button(bb, text="Use this line", command=ok).pack(side="right")
    ttk.Button(bb, text="Cancel", command=win.destroy).pack(side="right", padx=4)
    _run(win, e)
    return out["id"]


def ask_new_scene(parent, app, bank, default_type=None):
    """The New scene dialog: when it plays (action type), its keys, list position and the
    body listing. Returns {type_id, keys, body, position} or None."""
    tt = bank.type_table_full()
    win = _modal(parent, "New scene — %s" % catalog.bank_title(bank))
    frm = ttk.Frame(win, padding=8)
    frm.pack(fill="both", expand=True)

    def choice(t):
        lab = catalog.type_label(t)
        nm = lab.split("  ", 1)[1] if "  " in lab else ""
        cnt = tt[t][0] if t in tt else 0
        return "%-3d %s%s" % (t, nm, ("   (%d already)" % cnt) if cnt else "")
    ttk.Label(frm, text="Plays when").grid(row=0, column=0, sticky="e", padx=2, pady=2)
    tv = tk.StringVar()
    type_cb = FilterCombo(frm, [choice(t) for t in range(bank.table_slots)], None, width=56)
    type_cb.configure(textvariable=tv)
    type_cb.grid(row=0, column=1, sticky="we", padx=2, pady=2)
    Tip(type_cb, "The action type decides WHEN the engine starts the scene: talking to someone, "
                 "entering the map, using an item, a festival phase, …")
    summary = ttk.Label(frm, text="", foreground="#556", font=("Segoe UI", 8), wraplength=560, justify="left")
    summary.grid(row=1, column=1, sticky="w", padx=2)
    ttk.Label(frm, text="Keys").grid(row=2, column=0, sticky="e", padx=2, pady=2)
    kv = tk.StringVar()
    keys = ttk.Entry(frm, textvariable=kv, width=56)
    keys.grid(row=2, column=1, sticky="we", padx=2, pady=2)
    Tip(keys, "What the trigger matches, comma-separated: `5, -1` (-1 = any) or `(tag, value)`.")
    khint = ttk.Label(frm, text="", foreground="#556", font=("Segoe UI", 8), wraplength=560, justify="left")
    khint.grid(row=3, column=1, sticky="w", padx=2)
    ttk.Label(frm, text="Position").grid(row=4, column=0, sticky="e", padx=2, pady=2)
    pv = tk.StringVar(value="append")
    pos = ttk.Combobox(frm, textvariable=pv, values=["append", "first"], state="readonly", width=10)
    pos.grid(row=4, column=1, sticky="w", padx=2, pady=2)
    Tip(pos, "Where in the type's list: most matchers take the FIRST match; the tick "
             "dispatchers (types 6/7) run the LAST entry.")
    ttk.Label(frm, text="Body").grid(row=5, column=0, sticky="ne", padx=2, pady=2)
    body = tk.Text(frm, height=10, width=76, font=("Consolas", 10), undo=True, **DARK)
    body.grid(row=5, column=1, sticky="nsew", padx=2, pady=2)
    body.insert("1.0", app.new_scene_template())
    note = ttk.Label(frm, text="", foreground="#8a6d00", wraplength=600, justify="left")
    note.grid(row=6, column=1, sticky="w", padx=2)
    err = ttk.Label(frm, text="", foreground="#b02020", wraplength=600, justify="left")
    err.grid(row=7, column=1, sticky="w", padx=2)
    frm.columnconfigure(1, weight=1)
    frm.rowconfigure(5, weight=1)
    out = {}

    def cur_type():
        try:
            return int(tv.get().split()[0])
        except (ValueError, IndexError):
            return None

    def on_type(*_a):
        t = cur_type()
        if t is None:
            return
        summary.config(text=catalog.type_summary(t) + ("\n" + catalog.type_recipe(t) if catalog.type_recipe(t) else ""))
        kv.set(app.default_keys_text(bank, t))
        names = catalog.type_key_names(t)
        khint.config(text=("keys: " + ", ".join(str(k.get("name") if isinstance(k, dict) else k) for k in names))
                     if names else "key count mirrors this bank's existing entries of the type")
        note.config(text=app.shadow_note(bank, t, 0 if pv.get() == "first" else None))
    type_cb._on_pick = lambda _t: on_type()
    pos.bind("<<ComboboxSelected>>", on_type)

    def ok(_e=None):
        t = cur_type()
        if t is None:
            err.config(text="pick when it plays (an action type)")
            return "break"
        try:
            k = catalog.parse_entry_keys(kv.get())
        except ValueError as ex:
            err.config(text=str(ex))
            return "break"
        text = body.get("1.0", "end-1c")
        if not text.strip():
            err.config(text="the body needs at least one statement (FRAME 0 / DIALOG #id / END)")
            return "break"
        e = app.assemble_check(text, base=len(bank.data))[2]
        if e:
            err.config(text=e)
            return "break"
        out.update(type_id=t, keys=k, body=text, position=pv.get())
        win.destroy()
    bb = ttk.Frame(frm)
    bb.grid(row=8, column=0, columnspan=2, sticky="we", pady=(6, 0))
    ttk.Button(bb, text="Create scene", command=ok).pack(side="right", padx=2)
    ttk.Button(bb, text="Cancel", command=win.destroy).pack(side="right", padx=2)
    if default_type is None:
        default_type = next(iter(tt), 0)
    tv.set(choice(max(0, min(int(default_type), bank.table_slots - 1))))
    on_type()
    win.bind("<Control-Return>", ok)
    _run(win, body)
    return out or None


def callers_window(parent, app, rows, dispatch, target):
    """List the statements that lead to `target`; double-click jumps there."""
    win = tk.Toplevel(parent)
    win.title("Callers of 0x%04x — %s" % (target, catalog.bank_title(app.bank)))
    win.geometry("680x360")
    hdr = "%d statement(s) lead here" % len(rows)
    if dispatch:
        hdr += "  ·  also started by the engine: " + ", ".join(catalog.type_label(t) for t in dispatch)
    ttk.Label(win, text=hdr, anchor="w").pack(fill="x", padx=6, pady=4)
    f = ttk.Frame(win)
    f.pack(fill="both", expand=True, padx=6)
    lb = tk.Listbox(f, font=("Consolas", 10))
    sb = ttk.Scrollbar(f, command=lb.yview)
    lb.config(yscrollcommand=sb.set)
    lb.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    for entry, atype, from_pc, mnem in rows:
        lb.insert("end", "%-12s @0x%04x  in scene @0x%04x (%s)"
                  % (mnem, from_pc, entry, "type %d" % atype if atype >= 0 else "subroutine"))
    if not rows:
        lb.insert("end", "(nothing in this bank leads here — started by the engine or by data)")

    def jump(_e=None):
        s = lb.curselection()
        if s and s[0] < len(rows):
            entry, _t, from_pc, _m = rows[s[0]]
            app.open_scene(app.bank_pos, entry, focus_pc=from_pc)
    lb.bind("<Double-Button-1>", jump)
    ttk.Label(win, text="double-click to open the calling statement", foreground="#888").pack(anchor="w", padx=6, pady=4)
    return win
