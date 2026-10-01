"""Modal prompts (listing, spec, new scene, new dialogue line, line picker) and the
callers window. Every prompt validates before it closes and shows errors inline."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from guiutil import FilterCombo, ScrollFrame, Tip, hint, later

from . import catalog
from .inspector import speaker_choices

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


_THUMBS = {}


def face_thumbnail(reader, file_name, size=64):
    """A Tk image of a portrait face texture, cropped to its visible part (cached)."""
    key = (file_name, size)
    if key in _THUMBS:
        return _THUMBS[key]
    img = None
    try:
        from PIL import Image, ImageTk
        from rf4s_modkit import texture
        raw = reader(file_name + ".texture") if reader else None
        if raw:
            im = texture.decode_to_image(raw).convert("RGBA")
            box = im.getbbox()
            if box:
                im = im.crop(box)
            im.thumbnail((size, size))
            bg = Image.new("RGBA", (size, size), (64, 64, 78, 255))
            bg.alpha_composite(im, ((size - im.width) // 2, (size - im.height) // 2))
            img = ImageTk.PhotoImage(bg)
    except Exception:  # noqa: BLE001 - a missing / odd texture just shows no picture
        img = None
    _THUMBS[key] = img
    return img


class FacePicker:
    """The portrait face of a speaker cue (rf4s_modkit.portraits): a button with the current
    face's picture; clicking it opens every face of that speaker as pictures to choose from.
    Story mode shows these classic faces. `set_slot` picks the speaker, `value()` is the face id,
    `set_value(id)` shows an existing one."""

    def __init__(self, parent, on_change=None, reader=None):
        from rf4s_modkit import portraits as pt
        self.pt = pt
        self.reader = reader
        self.on_change = on_change
        self.slot = None
        self._value = 0
        self.frame = ttk.Frame(parent)
        self.btn = ttk.Button(self.frame, text="(pick a speaker)", compound="left", command=self.choose)
        self.btn.pack(side="left")
        Tip(self.btn, "The face the portrait shows for the following lines. Click to see them all.")

    # -- state -------------------------------------------------------------------------- #
    def set_slot(self, slot):
        self.slot = slot
        if slot is None or not self.pt.has_portrait(slot):
            self.btn.config(state="disabled", text="(no portrait)" if slot is not None else
                            "(pick a speaker)", image="")
            return
        self.btn.config(state="normal")
        self._show()

    def value(self):
        return self._value if self.slot is not None and self.pt.has_portrait(self.slot) else 0

    def set_value(self, face_id):
        if face_id is None:
            return False
        self._value = int(face_id)
        if self.slot is not None:
            self._show()
        return self.slot is not None and self.pt.face_file(self.slot, self._value) is not None

    def _show(self):
        pt, v = self.pt, self._value
        lab = pt.label(self.slot, v) or str(v)
        f = pt.face_file(self.slot, v)
        img = face_thumbnail(self.reader, f, 40) if f else None
        self.btn.config(text="  %s  (%d)" % (lab, v), image=img or "")
        self.btn._img = img

    # -- chooser ------------------------------------------------------------------------ #
    def choose(self):
        if self.slot is None or not self.pt.has_portrait(self.slot):
            return
        pt = self.pt
        win = tk.Toplevel(self.frame)
        win.title("Pick a face")
        win.transient(self.frame.winfo_toplevel())
        cols, cell_w, cell_h = 8, 86, 96
        faces = pt.faces(self.slot)
        ttk.Label(win, text="Story-mode faces (the first six are the same moods for everyone). "
                            "Click one.", foreground="#555", padding=(6, 6, 6, 2)).pack(anchor="w")
        bottom = ttk.Frame(win, padding=6)
        bottom.pack(side="bottom", fill="x")
        ttk.Button(bottom, text="Cancel", command=win.destroy).pack(side="right")
        # only the face buttons scroll; the heading and Cancel stay put
        rows = (len(faces) + cols - 1) // cols
        sf = ScrollFrame(win, width=cols * cell_w + 8)
        sf.canvas.configure(height=min(rows, 5) * cell_h)
        sf.pack(fill="both", expand=True, padx=6)
        win._imgs = []
        for k, (fid, f, mood) in enumerate(faces):
            img = face_thumbnail(self.reader, f, 64)
            win._imgs.append(img)
            cap = "%d  %s" % (fid, mood) if mood else str(fid)
            b = tk.Button(sf.body, text=cap, image=img or "", compound="top", width=76,
                          relief="sunken" if fid == self._value else "raised",
                          command=lambda fid=fid: self._picked(win, fid))
            b.grid(row=k // cols, column=k % cols, padx=2, pady=2)
            Tip(b, "%s\nface id %d" % (f, fid))
        sf.bind_wheel_tree()
        win.grab_set()

    def _picked(self, win, fid):
        win.destroy()
        changed = fid != self._value
        self._value = fid
        self._show()
        if changed and self.on_change:
            self.on_change(fid)


def box_thumbnail(reader, style, w=150, h=44):
    """A Tk image of a message-box style: the top edge of talk_win<n> with its tail (cached)."""
    key = ("box", style, w, h)
    if key in _THUMBS:
        return _THUMBS[key]
    img = None
    try:
        from PIL import Image, ImageTk
        from rf4s_modkit import texture

        def load(n):
            raw = reader(n + ".texture") if reader else None
            return texture.decode_to_image(raw).convert("RGBA") if raw else None
        bg = Image.new("RGBA", (w, h), (64, 64, 78, 255))
        tail = load("talk_hige%d" % (0 if style == 4 else style))
        if style != 4:
            win = load("talk_win%d" % style)
            if win is not None:
                box = win.getbbox() or (0, 0, win.width, win.height)
                edge = win.crop((box[0] + 100, box[1], box[0] + 300, box[1] + 60))
                edge.thumbnail((w - 30, h - 4))
                bg.alpha_composite(edge, (2, 2))
        if tail is not None:
            tb = tail.getbbox()
            if tb:
                tail = tail.crop(tb)
            tail.thumbnail((26, h - 6))
            bg.alpha_composite(tail, (w - 28, 3))
        img = ImageTk.PhotoImage(bg)
    except Exception:  # noqa: BLE001 - a missing texture just shows no picture
        img = None
    _THUMBS[key] = img
    return img


class BoxStylePicker:
    """The message-box style (ops 93-97): a button with the current style's picture; clicking
    it shows the styles as pictures. `allow` = the styles offered (ops 94-97 can't express
    style 4), `keep` adds a 'keep the current box' choice (value None)."""

    def __init__(self, parent, on_change=None, reader=None, allow=(0, 1, 2, 3, 4), keep=False):
        from rf4s_modkit import opcode_meta
        self.names = opcode_meta.BOX_STYLES
        self.reader = reader
        self.on_change = on_change
        self.allow = tuple(allow)
        self.keep = keep
        self._value = None if keep else 0
        self.frame = ttk.Frame(parent)
        self.btn = ttk.Button(self.frame, compound="left", command=self.choose)
        self.btn.pack(side="left")
        Tip(self.btn, "The style of the message box for the following lines. Click to see them. "
                      "The tail points at the speaker's side and only shows while that side has "
                      "a portrait, so give a thought line a speaker, not narration.")
        self._show()

    def value(self):
        return self._value

    def set_value(self, style):
        self._value = style
        self._show()

    def _caption(self, style):
        if style is None:
            return "(keep the current box)"
        nm, desc = self.names.get(style, ("style %d" % style, ""))
        return "%s  (%d)" % (nm, style)

    def _show(self):
        img = box_thumbnail(self.reader, self._value, 90, 26) if self._value is not None else None
        self.btn.config(text="  " + self._caption(self._value), image=img or "")
        self.btn._img = img

    def choose(self):
        win = tk.Toplevel(self.frame)
        win.title("Pick a box style")
        win.transient(self.frame.winfo_toplevel())
        body = ttk.Frame(win, padding=6)
        body.pack(fill="both", expand=True)
        win._imgs = []
        opts = ([None] if self.keep else []) + list(self.allow)
        for k, style in enumerate(opts):
            img = box_thumbnail(self.reader, style) if style is not None else None
            win._imgs.append(img)
            desc = self.names.get(style, ("", ""))[1] if style is not None else \
                "Don't change the box; the style set earlier stays."
            b = tk.Button(body, text=self._caption(style), image=img or "", compound="top",
                          width=160, relief="sunken" if style == self._value else "raised",
                          command=lambda s=style: self._picked(win, s))
            b.grid(row=0, column=k, padx=3, pady=3, sticky="n")
            Tip(b, desc)
        ttk.Button(body, text="Cancel", command=win.destroy).grid(row=1, column=len(opts) - 1,
                                                                  sticky="e", pady=(6, 0))
        win.grab_set()

    def _picked(self, win, style):
        win.destroy()
        changed = style != self._value
        self._value = style
        self._show()
        if changed and self.on_change:
            self.on_change(style)


class DialogueForm:
    """A new dialogue line's fields, placed in `parent` (a frame): an optional speaker change
    (with its side and the portrait's face), the message-box style and the text. The
    Instruction picker shows it for DIALOG. value() -> (spec, error): spec = {'speaker':
    (slot, side) | None, 'face': face id, 'box': box style | None, 'text': str}."""

    KEEP = "(keep the current speaker)"

    def __init__(self, parent, default_speaker=None, reader=None, on_change=None):
        frm = self.frame = ttk.Frame(parent)
        ttk.Label(frm, text="Speaker").grid(row=0, column=0, sticky="w")
        choices = speaker_choices()
        self.spk = FilterCombo(frm, [self.KEEP] + choices, None, width=32)
        self.spk.var.set(self.KEEP if default_speaker is None else choices[default_speaker])
        self.spk.grid(row=0, column=1, sticky="we", padx=4)
        Tip(self.spk, "Pick a speaker to insert a SetSpeaker before the line, or keep the one "
                      "already speaking.")
        self.side = tk.StringVar(value="left")
        sr = ttk.Frame(frm)
        sr.grid(row=1, column=1, sticky="w", padx=4)
        for sd in ("left", "right"):
            r_ = ttk.Radiobutton(sr, text=sd, value=sd, variable=self.side)
            r_.pack(side="left", padx=(0, 6))
            Tip(r_, "Which side of the screen the new speaker's portrait stands on.")
        ttk.Label(frm, text="Face").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.face = FacePicker(frm, reader=reader)
        self.face.frame.grid(row=2, column=1, sticky="w", padx=4, pady=(4, 0))
        self.spk._on_pick = lambda _t: self.face.set_slot(self._slot())
        self.spk.var.trace_add("write", lambda *_a: self.face.set_slot(self._slot()))
        self.face.set_slot(self._slot())
        ttk.Label(frm, text="Box style").grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.box = BoxStylePicker(frm, reader=reader, keep=True)
        self.box.frame.grid(row=3, column=1, sticky="w", padx=4, pady=(4, 0))
        ttk.Label(frm, text="Text").grid(row=4, column=0, sticky="nw", pady=(6, 0))
        self.txt = tk.Text(frm, height=4, width=60, wrap="word", font=("Segoe UI", 10), undo=True)
        self.txt.grid(row=4, column=1, sticky="nsew", padx=4, pady=(6, 0))
        import text_tab
        im = text_tab.insert_menu(frm, self.txt)
        im.grid(row=4, column=2, sticky="nw", pady=(6, 0))
        Tip(im, "Put a colour, a raise / lower, a button icon or a ＠ code at the cursor (written "
                "as backslash escapes: \\red, \\btn(a) ...).")
        hint(frm, "The text becomes a new line in every locale (the others get it untranslated "
                  "until you edit them). The face applies when you pick a speaker.", wrap=460).grid(
            row=5, column=1, sticky="w", padx=4)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(4, weight=1)
        if on_change is not None:
            self.txt.bind("<<Modified>>", lambda _e: (self.txt.edit_modified(False), on_change()))
            self.spk.var.trace_add("write", lambda *_a: on_change())
            self.side.trace_add("write", lambda *_a: on_change())

    def _slot(self):
        choice = self.spk.var.get().split()
        return int(choice[0]) if choice and choice[0].isdigit() else None

    def set_text(self, text):
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", text)

    def value(self):
        """(spec, None) for the filled form, or (None, what is wrong)."""
        from rf4s_modkit import textesc
        try:
            t = textesc.from_edit(self.txt.get("1.0", "end-1c"))  # \red, \btn(a) ... -> characters
        except textesc.EscapeError as e:
            return None, str(e)
        if not t.strip():
            return None, "type the line's text"
        slot = self._slot()
        s = (slot, 1 if self.side.get() == "right" else 0) if slot is not None else None
        return {"speaker": s, "face": self.face.value() if s is not None else 0,
                "box": self.box.value(), "text": t}, None


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
        refresh_note()

    def refresh_note(*_a):
        """The shadow note plus any key that can never match (e.g. -1 for type 2)."""
        t = cur_type()
        if t is None:
            return
        at = 0 if pv.get() == "first" else None
        parts = [app.shadow_note(bank, t, at)]
        clash = None
        try:
            subs = catalog.parse_entry_keys(kv.get())
            parts += catalog.key_problems(t, subs, app.doc.em)
            clash, warns, _elsewhere = app.doc.container.entry_key_conflicts(bank, t, subs, at)
            parts += warns
        except ValueError:
            pass
        note.config(text="\n".join(p for p in parts if p))
        err.config(text=clash or "")
    type_cb._on_pick = lambda _t: on_type()
    pos.bind("<<ComboboxSelected>>", on_type)
    kv.trace_add("write", refresh_note)

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
        clash = app.doc.container.entry_key_conflicts(bank, t, k, 0 if pv.get() == "first" else None)[0]
        if clash:
            err.config(text=clash)
            return "break"
        text = body.get("1.0", "end-1c")
        if not text.strip():
            text = "RET"                         # an empty scene
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
                  % (mnem, from_pc, entry, "type %d" % atype if atype >= 0 else "unreached"))
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
