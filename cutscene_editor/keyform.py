"""The keys of one trigger as a form: one labelled field per key with a picker that fits it
(a map, a character, an item, an em.bin condition, a festival, a flag, a date), an "any"
box where -1 means any, the area keys as one box with Select… (drag it on the map), and Add / Remove
for the keys a trigger can list several of. Used by the Triggers pane (TriggerDetail) and
the New scene dialog. The wording comes from entry_types (label / help / pick per key)."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from guiutil import FilterCombo, Tip
from rf4s_modkit import entry_types, script

from . import catalog

BOX = ("x1", "y1", "x2", "y2")
_NUM_END = re.compile(r"\((-?\d+)\)\s*$")


# ---- picker values: [(display, value)] ------------------------------------------- #
def _maps():
    from . import toolbox
    return [(d, script.map_leaf_value(t[4:-1])) for d, t in toolbox.map_choices()]


def _characters(lo=0, hi=None):
    from rf4s_modkit import gamenames
    d = gamenames.table("characters")
    return [("%s  (%d)" % (v, k), k) for k, v in sorted(d.items())
            if v and k >= lo and (hi is None or k <= hi)]


def _items():
    from . import toolbox
    return [(d, int(t)) for d, t in toolbox.item_choices()]


def _conditions(em):
    if em is None:
        return []
    try:
        from rf4s_modkit import emtext
    except ImportError:
        emtext = None
    out = []
    for i in range(len(em.entries)):
        nm = em.names.entry_name(i) or ""
        txt = (emtext.entry_text(nm) if emtext else "") or ""
        out.append(("%d  %s%s" % (i, nm, ("  — " + txt) if txt else ""), i))
    return out


def _festivals():
    return [("%s  (%d)" % (entry_types.FESTIVAL_NAMES.get(i, "unused id"), i), i) for i in range(1, 26)]


def _flags(doc):
    emf = getattr(doc, "emf_vars", None)
    c = getattr(doc, "container", None)
    if emf is None or c is None:
        return []
    out = []
    for v in getattr(emf, "variables", []):
        try:
            enc = c.pack_var(v.bit_offset, v.bit_width)
        except script.ScriptError:
            continue
        out.append(("%s  (%d bit%s)" % (v.name, v.bit_width, "" if v.bit_width == 1 else "s"), enc))
    return out


def _dates():
    out = [("%s %d  (%d)" % (s, d + 1, i * 30 + d), i * 30 + d)
           for i, s in enumerate(entry_types.SEASONS) for d in range(30)]
    for fes, name in sorted(entry_types.FESTIVAL_NAMES.items()):
        for before in range(0, 8):
            v = entry_types.date_value(0, festival=fes, days_before=before)
            out.append(("%s  (%d)" % (entry_types.date_text(v), v), v))
    return out


def flag_name(doc, value):
    """The FLG_/REG_ name of a packed flag reference, or None."""
    emf, c = getattr(doc, "emf_vars", None), getattr(doc, "container", None)
    if emf is None or c is None:
        return None
    try:
        off, _w, _s = c.unpack_var(value)
        v = emf.by_offset(off)
    except Exception:  # noqa: BLE001 -- a value that is no flag reference: no name
        return None
    return v.name if v is not None else None


def names_for(app):
    """The name lookups entry_types.value_text / explain_keys take."""
    from rf4s_modkit import gamenames
    from rf4s_modkit.map_names import map_name
    em = app.doc.em

    def cond(v):
        try:
            return em.names.entry_name(v) if em is not None and 0 <= v < len(em.entries) else None
        except Exception:  # noqa: BLE001
            return None
    return {"map": map_name, "npc": lambda v: gamenames.name("characters", v),
            "item": lambda v: gamenames.name("items", v), "condition": cond,
            "flag": lambda v: flag_name(app.doc, v)}


class _Field:
    """One key field: its spec, the StringVar, the "any" BooleanVar, display -> value."""

    def __init__(self, spec, label, choices):
        self.spec, self.label = spec, label
        self.choices = choices                 # [(display, value)] or None (typed number)
        self.var = tk.StringVar()
        self.any = tk.BooleanVar(value=False)
        self.widget = None

    def show(self, value):
        if self.spec.get("any") and value == -1:
            self.any.set(True)
            self.var.set("")
            return
        self.any.set(False)
        if self.choices:
            hit = next((d for d, v in self.choices if v == value), None)
            self.var.set(hit if hit is not None else str(value))
        else:
            self.var.set(str(value))

    def value(self):
        if self.spec.get("any") and self.any.get():
            return -1
        t = self.var.get().strip()
        if self.choices:
            hit = next((v for d, v in self.choices if d == t), None)
            if hit is not None:
                return hit
            m = _NUM_END.search(t)
            if m:
                return int(m.group(1))
        tok = t.split()[0] if t else ""
        try:
            return int(tok, 0)
        except ValueError:
            raise ValueError("%s: %s" % (self.label, "pick a value" if not t else "%r is not a number" % t))


class KeyForm(ttk.Frame):
    """The key fields of a `type_id` trigger in `bank`, filled from `subs` ([(tag, value)];
    None = a new trigger's defaults). values() -> [(tag, value)]; on_change() after every edit."""

    def __init__(self, parent, app, bank, type_id, subs=None, on_change=None, wrap=330):
        # on_change(enter): after every edit; enter=True when it was Enter in a field
        super().__init__(parent)
        self.app, self.bank, self.type_id = app, bank, type_id
        self.on_change = on_change or (lambda enter=False: None)
        self.wrap = wrap
        self.orig = [tuple(s) for s in subs] if subs is not None else None
        self.box = None                     # [x, y, width, height] StringVars
        self.fields = []                    # [_Field] (the box is not one)
        self._choice_cache = {}
        self.set_keys(subs if subs is not None else self.default_keys())

    # ---- what the type takes ---------------------------------------------------------- #
    def specs(self):
        return entry_types.key_form(self.type_id)

    def _fixed_and_list(self):
        """(the keys at a fixed index, in order; the repeating "n+" spec or None)."""
        specs = self.specs() or []
        fixed = sorted((s for s in specs if isinstance(s["index"], int)), key=lambda s: s["index"])
        rep = next((s for s in specs if not isinstance(s["index"], int)), None)
        return fixed, rep

    def default_keys(self):
        """A new trigger's keys: -1 where that means any, this bank's map / character where
        the key asks for one, else 0; one value for a list key (two for a monster pair)."""
        specs = self.specs()
        if specs is None:                   # uncatalogued: as many as the bank's others have
            try:
                recs = self.bank.entry_records(self.type_id)
            except Exception:  # noqa: BLE001
                recs = []
            return [(t, 0) for t, _v in recs[0].subs] if recs else []
        fixed, rep = self._fixed_and_list()
        out = [(s.get("tag", 1), self._default(s)) for s in fixed]
        if rep is not None:
            if rep.get("many") == "pairs":
                out += [(1, -1), (1, -1)]
            else:
                out.append((rep.get("tag", 1), self._default(rep)))
        return out

    def _default(self, s):
        pick = s.get("pick")
        if pick == "map" and self.bank.kind == "tail":
            return self.bank.index
        if pick == "npc" and self.bank.kind == "primary" and 0 < self.bank.index < 48 \
                and s.get("many") != "all":
            return self.bank.index
        return -1 if s.get("any") else 0

    def _choices(self, pick, spec):
        key = pick if pick != "choice" else ("choice", id(spec))
        if key in self._choice_cache:
            return self._choice_cache[key]
        doc = self.app.doc
        if pick == "map":
            out = _maps()
            if self.type_id == 68:
                out = [("any map  (0)", 0)] + out
        elif pick == "npc":
            out = _characters()
            if spec.get("many") == "all":           # town-event scenes: the spouse / child flags
                special = [("the child", entry_types.CHILD_FLAG)]
                if spec.get("any") != "the spouse":     # (63 / 64: 'any' already is the spouse)
                    special.insert(0, ("the spouse", entry_types.SPOUSE_FLAG))
                out = special + out
            if self.type_id == 27:
                out = [("the spouse  (0)", 0)] + [c for c in out if c[1] != 0]
        elif pick == "monster":
            out = _characters(48, 253)
        elif pick == "item":
            out = _items()
        elif pick == "condition":
            out = _conditions(doc.em)
            if self.type_id in (67, 71):            # 0 = no condition there
                out = [("0  (none)", 0)] + [c for c in out if c[1] != 0]
        elif pick == "festival":
            out = _festivals()
        elif pick == "flag":
            out = _flags(doc)
        elif pick == "date":
            out = _dates()
        elif pick == "choice":
            out = [("%s  (%d)" % (t, v), v) for v, t in spec.get("options") or ()]
        else:
            out = None
        self._choice_cache[key] = out
        return out

    # ---- layout ------------------------------------------------------------------------ #
    def set_keys(self, subs):
        """Lay the form out again for these keys."""
        for w in self.winfo_children():
            w.destroy()
        self.fields, self.box = [], None
        self.columnconfigure(1, weight=1)
        subs = [tuple(s) if isinstance(s, (tuple, list)) else (1, s) for s in subs]
        self._layout = []                   # [(kind, payload)] in key order: field / box
        self.row = 0
        specs = self.specs()
        if specs is not None and not specs:
            self._note("This trigger type has no keys: the scene plays whenever its event "
                       "happens (see the type's description).")
            return
        if specs is None:
            self._note("The keys of this trigger type are not known; they are shown as numbers.")
            for k, (_t, v) in enumerate(subs):
                self._add_field({"index": k, "name": "key %d" % k, "pick": "number", "any": ""},
                                "Key %d" % (k + 1), v, removable=True)
            self._add_button("+ Add a key", lambda: self._grow({"pick": "number"}))
            return
        fixed, rep = self._fixed_and_list()
        names = [s["name"] for s in fixed]
        box_at = names.index("x1") if all(n in names for n in BOX) else None
        i = 0
        while i < len(fixed):
            s = fixed[i]
            if box_at is not None and i == box_at:
                vals = [subs[s2["index"]][1] if s2["index"] < len(subs) else 0 for s2 in fixed[i:i + 4]]
                self._add_box(vals)
                i += 4
                continue
            v = subs[s["index"]][1] if s["index"] < len(subs) else self._default(s)
            self._add_field(s, s.get("label") or s["name"], v)
            i += 1
        if rep is None:
            return
        start = int(str(rep["index"]).rstrip("+"))
        rest = [v for _t, v in subs[start:]]
        label = rep.get("label") or rep["name"]
        if rep.get("many") == "pairs":
            if not rest:
                rest = [-1, -1]
            if len(rest) % 2:
                rest.append(-1)
            for j in range(0, len(rest), 2):
                self._add_field(dict(rep, pick="monster"), label, rest[j], removable=len(rest) > 2, pair=True)
                self._add_field(dict(rep, pick="condition", label="only when", any="always",
                                     help="An em.bin condition for this monster; 'always' = none."),
                                "  only when", rest[j + 1])
            self._add_button("+ Add another monster", lambda: self._grow(rep, pair=True))
            return
        if not rest:
            rest = [self._default(rep)]
        for j, v in enumerate(rest):
            self._add_field(rep, label if j == 0 else "  " + ("and" if rep.get("many") == "all" else "or"),
                            v, removable=len(rest) > 1, help_once=j == 0)
        self._add_button("+ Add another %s" % (rep.get("noun") or "value"), lambda: self._grow(rep))

    def _note(self, text):
        ttk.Label(self, text=text, foreground="#777", wraplength=self.wrap, justify="left").grid(
            row=self.row, column=0, columnspan=3, sticky="w", pady=2)
        self.row += 1

    def _help(self, text):
        if text:
            ttk.Label(self, text=text, foreground="#777", font=("Segoe UI", 8), wraplength=self.wrap,
                      justify="left").grid(row=self.row, column=0, columnspan=3, sticky="w", pady=(0, 4))
            self.row += 1

    def _add_field(self, spec, label, value, removable=False, pair=False, help_once=True):
        pick = spec.get("pick") or "number"
        f = _Field(spec, label.strip(), self._choices(pick, spec))
        f.show(value)
        ttk.Label(self, text=label).grid(row=self.row, column=0, sticky="nw", padx=(0, 6), pady=2)
        cell = ttk.Frame(self)
        cell.grid(row=self.row, column=1, sticky="we", pady=2)
        if f.choices is not None:
            w = FilterCombo(cell, [d for d, _v in f.choices], on_pick=lambda _t: self._changed(),
                            width=34, textvariable=f.var)
        else:
            w = ttk.Entry(cell, textvariable=f.var, width=12)
        w.pack(side="left")
        w.bind("<Return>", lambda _e: self._changed(enter=True))
        f.widget = w
        if spec.get("any"):
            cb = ttk.Checkbutton(cell, text=spec["any"], variable=f.any,
                                 command=lambda: (self._sync_any(f), self._changed()))
            cb.pack(side="left", padx=(6, 0))
            self._sync_any(f)
        if removable:
            rb = ttk.Button(cell, text="✕", width=3, command=lambda: self._shrink(f, pair))
            rb.pack(side="left", padx=(6, 0))
            Tip(rb, "Remove this value" + (" and its condition" if pair else ""))
        mean = None
        if pick in ("date", "number") and spec.get("name") in ("date", "warp_event", "code"):
            mean = ttk.Label(cell, foreground="#2a6a8a", font=("Segoe UI", 8))
            mean.pack(side="left", padx=(6, 0))
        f.meaning = mean
        f.var.trace_add("write", lambda *_a: self._changed())
        self.row += 1
        if help_once:
            self._help(spec.get("help") or "")
        self.fields.append(f)
        self._layout.append(("field", f))
        self._update_meaning(f)
        return f

    def _add_box(self, vals):
        x1, y1, x2, y2 = vals
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
        ttk.Label(self, text="Area").grid(row=self.row, column=0, sticky="nw", padx=(0, 6), pady=2)
        cell = ttk.Frame(self)
        cell.grid(row=self.row, column=1, sticky="we", pady=2)
        self.box = []
        for lab, v in zip(("x", "y", "width", "height"), (x1, y1, x2 - x1, y2 - y1)):
            ttk.Label(cell, text=lab).pack(side="left", padx=(0, 2))
            var = tk.StringVar(value=str(v))
            e = ttk.Entry(cell, textvariable=var, width=6)
            e.pack(side="left", padx=(0, 8))
            e.bind("<Return>", lambda _e: self._changed(enter=True))
            var.trace_add("write", lambda *_a: self._changed())
            self.box.append(var)
        self.row += 1
        b = ttk.Button(self, text="📍 Select…", command=self.draw_box)
        b.grid(row=self.row, column=1, sticky="w", pady=(0, 2))
        Tip(b, "Drag the trigger area on the map (1/8-tile units). The map's other trigger "
               "areas show dashed.")
        self.box_button = b
        self.row += 1
        self._help("The rectangle the player walks into, in 1/8-tile units (8 per tile, like positions).")
        self._layout.append(("box", None))

    def _add_button(self, text, cmd):
        b = ttk.Button(self, text=text, command=cmd)
        b.grid(row=self.row, column=1, sticky="w", pady=(2, 4))
        self.row += 1
        self.add_button = b

    def _sync_any(self, f):
        try:
            f.widget.configure(state="disabled" if f.any.get() else "normal")
        except tk.TclError:
            pass

    def _update_meaning(self, f):
        if getattr(f, "meaning", None) is None:
            return
        try:
            v = f.value()
        except ValueError:
            f.meaning.config(text="")
            return
        nm = f.spec.get("name")
        if nm == "date":
            txt = entry_types.date_text(v)
        elif nm == "warp_event":
            txt = ("from the town event's bank" if 1000 <= v <= 1099 else
                   "from the story bank" if 100 <= v <= 999 else "from the arrival map's bank")
        elif nm == "code" and self.type_id == 53 and v > 0:
            skill, lvl = divmod(v - 1, 4)
            txt = "weapon skill %d, level %s" % (skill, {0: "5", 1: "10", 3: "20"}.get(lvl, "?"))
        else:
            txt = ""
        f.meaning.config(text=("= " + txt) if txt else "")

    # ---- edits ------------------------------------------------------------------------- #
    def _changed(self, enter=False):
        for f in self.fields:
            self._update_meaning(f)
        self.on_change(enter)

    def _grow(self, spec, pair=False):
        try:
            subs = self.values()
        except ValueError:
            subs = self._raw_values()
        if pair:
            subs += [(1, -1), (1, -1)]
        else:
            subs.append((spec.get("tag", 1), self._default(spec) if spec.get("name") else 0))
        self.set_keys(subs)
        self._changed()

    def _shrink(self, f, pair=False):
        subs = self._raw_values()
        k = self._index_of(f)
        del subs[k:k + (2 if pair else 1)]
        self.set_keys(subs)
        self._changed()

    def _index_of(self, f):
        k = 0
        for kind, p in self._layout:
            if kind == "box":
                k += 4
                continue
            if p is f:
                return k
            k += 1
        return k

    def _raw_values(self):
        """The keys as they stand, unreadable fields as 0 (for re-laying out the form)."""
        out = []
        for kind, p in self._layout:
            if kind == "box":
                out += [(1, 0)] * 4
                try:
                    out[-4:] = [(1, v) for v in self._box_corners()]
                except ValueError:
                    pass
                continue
            try:
                out.append((self._tag(len(out), p, p.value()), p.value()))
            except ValueError:
                out.append((p.spec.get("tag", 1), 0))
        return out

    # ---- values ------------------------------------------------------------------------ #
    def _box_corners(self):
        x, y, w, h = (int(v.get().strip(), 0) for v in self.box)
        if w < 0 or h < 0:
            raise ValueError("Area: width and height must be 0 or more")
        return x, y, x + w, y + h

    def _tag(self, k, f, value):
        """The tag key `k` is written with: the original one while its value is unchanged,
        2 for the spouse / child (packed flag references), else the key's own tag."""
        if self.orig is not None and k < len(self.orig) and self.orig[k][1] == value:
            return self.orig[k][0]
        if f.spec.get("pick") == "npc" and value in (entry_types.SPOUSE_FLAG, entry_types.CHILD_FLAG):
            return 2
        if self.orig is not None and k < len(self.orig) and f.spec.get("pick") == "number" \
                and self.specs() is None:
            return self.orig[k][0]
        return f.spec.get("tag", 1)

    def values(self):
        """[(tag, value)] (raises ValueError naming the field)."""
        out = []
        for kind, p in self._layout:
            if kind == "box":
                try:
                    corners = self._box_corners()
                except ValueError as e:
                    raise ValueError(str(e) if "Area" in str(e) else "Area: x, y, width and height are numbers")
                out += [(self.orig[len(out)][0] if self.orig and len(out) < len(self.orig) else 1, v)
                        for v in corners]
                continue
            v = p.value()
            out.append((self._tag(len(out), p, v), v))
        return out

    def map_id(self):
        """(map id the area is on, why it is fixed or None, note) for Select…."""
        mapf = next((f for f in self.fields if f.spec.get("pick") == "map"), None)
        if mapf is not None:
            try:
                v = mapf.value()
            except ValueError:
                v = None
            if v not in (None, -1, 0):
                return v, "the trigger's map key says which map the area is on", None
            return None, None, "choose the map the trigger is for (it goes into the map key)"
        if self.bank.kind == "tail":
            return self.bank.index, "the trigger is in this map's event bank", None
        return None, None, "this bank is not tied to one map: choose the map the area is on"

    def draw_box(self):
        from . import toolbox
        if self.box is None:
            return None
        try:
            cur = self._box_corners()
        except ValueError:
            cur = None
        cur = cur if cur and any(cur) else None
        mid, lock, note = self.map_id()
        mapf = next((f for f in self.fields if f.spec.get("pick") == "map"), None)

        def done(x1, y1, x2, y2, _mid):
            for var, val in zip(self.box, (x1, y1, x2 - x1, y2 - y1)):
                var.set(str(val))
            if mapf is not None and lock is None and _mid is not None:
                mapf.show(_mid)
        top = self.winfo_toplevel()
        grabbed = str(top.grab_current() or "") == str(top)
        if grabbed:
            top.grab_release()                  # the picker takes the clicks meanwhile
        pk = toolbox.MapBoxPicker(self, mid, cur, done, lock=lock, note=note)
        if grabbed:
            def back(e=None):
                if e is not None and e.widget is not pk.win:
                    return
                try:
                    if top.winfo_exists():
                        top.grab_set()
                except tk.TclError:
                    pass
            pk.win.bind("<Destroy>", back, add="+")
            try:
                pk.win.grab_set()
            except tk.TclError:
                pass
        self.picker = pk
        return pk


def describe(app, type_id, subs):
    """A trigger's keys in words for the Triggers list (catalog.describe_keys's fallback)."""
    try:
        return entry_types.explain_keys(type_id, list(subs), names_for(app))
    except Exception:  # noqa: BLE001 -- never let a label break the list
        return catalog.describe_keys(type_id, subs)
