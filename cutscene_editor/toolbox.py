"""The cutscene editor's Reference window and Instruction picker.

Reference (toolbar "Reference"): searchable lists of what a scene can name --
  * Flags & variables: emdeb.bin's FLG_ / REG_ / EV_ variables (name, bit id, width, value
    range, Japanese label) and the recovered zone-2 bits (emflags.ZONE2_BLOCKS);
  * Functions: the instructions a person has verified in game (opcode_table.json
    `human_verified`), with everything the table knows about each;
  * Characters, Maps, Items: the ids and the listing form an argument takes.

Instruction picker (toolbar "Instruction…", the Inspector's Add before / Add after, the Script
view's right-click menu, the Insert key): every instruction by category, a form with one
field per argument (character / map / item / flag / enum pickers where the table knows the
type), a live listing preview that can also be edited by hand, and Insert before / after the
selected statement. The preview is plain listing text, so everything goes through the same
assembler as the Source tab.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from guiutil import FilterCombo, Tip, later
from guiutil import err_text
from rf4s_modkit import opcode_meta as meta
from rf4s_modkit import script, scriptasm

PLACEHOLDER = ("(unbound)", "(unused)", "nop", "invalid")
CONTROL_GROUP = "Flow & dialogue (control)"
CONTROL_ORDER = ("DIALOG", "EVAL", "BR_Z", "BR_NZ", "JMP", "CALL", "RET", "RET_NZ", "PROMPT_CHOICE",
                 "PROMPT_CHOICE_FORCED", "SWITCH", "SWITCH_CLAMP", "JMP_RAND", "JMP_WEIGHTED", "FRAME")
CONTROL_HELP = {
    "DIALOG": "Show one line of dialogue (spoken by the last SetSpeaker before it). Pick an "
              "existing line, or use 'New line…' to write a new one.",
    "EVAL": "Set a flag / register: `VAR = value`, or change it (`+=`, `-=`, …).",
    "BR_Z": "Jump to the target when the condition is FALSE (skip the next part unless …).",
    "BR_NZ": "Jump to the target when the condition is TRUE.",
    "JMP": "Always continue at the target.",
    "CALL": "Run the code at the target as a subroutine; its RET comes back here.",
    "RET": "End the scene (or return from a CALL).",
    "RET_NZ": "End the scene (or return from a CALL) when the condition is TRUE.",
    "PROMPT_CHOICE": "A choice menu: each option is a dialogue line and where it goes; Cancel "
                     "(B button) goes to the cancel target.",
    "PROMPT_CHOICE_FORCED": "A choice menu that cannot be cancelled.",
    "SWITCH": "Jump to target number N, where N is the selector's value (0 = the first).",
    "SWITCH_CLAMP": "Like SWITCH, but values past the end use the last target.",
    "JMP_RAND": "Jump to one of the targets at random.",
    "JMP_WEIGHTED": "Jump to one of the targets at random, each with its own weight.",
    "FRAME": "Reserve N stack words for the scene or subroutine. Not needed by hand: the "
             "editor adds or raises it by itself when an argument is a nested expression "
             "(e.g. reg0 + 1) evaluated while other arguments are on the stack.",
}


# ---- data ------------------------------------------------------------------------------ #
_CACHE = {}


_NAME_KEYS = ("chars", "maps", "items")        # built from the game's names (gamenames)


def _cached(key, fn):
    if key in _NAME_KEYS:                       # a saved name file / 00_mods change rebuilds them
        from rf4s_modkit import gamenames
        gen = gamenames.generation()
        if _CACHE.get("_names_gen") != gen:
            for k in _NAME_KEYS:
                _CACHE.pop(k, None)
            _CACHE["_names_gen"] = gen
    if key not in _CACHE:
        try:
            _CACHE[key] = fn()
        except Exception:  # noqa: BLE001 -- a missing table just leaves the list empty
            _CACHE[key] = []
    return _CACHE[key]


def character_choices():
    """[(display, listing token)] for every character id, e.g. ('Forte  (4)', 'actor(Forte)')."""
    def build():
        names, _u = script._actor_tables()
        return [("%s  (%d)" % (names[i], i), script.actor_leaf_text(i)) for i in sorted(names)]
    return _cached("chars", build)


def map_choices():
    def build():
        from rf4s_modkit import map_names
        out = []
        for i in range(map_names.map_count()):
            f = map_names.map_file(i)
            if f:
                nm = map_names.map_name(i) or ""
                out.append(("%s  %s  (%d)" % (f, nm, i), script.map_leaf_text(i)))
        return out
    return _cached("maps", build)


def item_choices():
    def build():
        from rf4s_modkit import gamenames
        d = gamenames.table("items")
        return [("%s  (%d)" % (v, k), str(k)) for k, v in sorted(d.items()) if v]
    return _cached("items", build)


def flag_rows(doc):
    """[(name, kind, id text, width, values, description, token)] -- emdeb's variables, then
    the recovered zone-2 bits."""
    from rf4s_modkit import emflags
    tbl = getattr(doc, "emf_vars", None)
    if tbl is None:
        tbl = _cached("emf", emflags.EmFlagTable.load)
    rows = []
    for v in getattr(tbl, "variables", []):
        w = v.bit_width
        rng = "0 / 1" if w == 1 else "0 – %d" % ((1 << w) - 1)
        kind = {"FLG": "flag", "REG": "value", "EV": "event"}.get(v.kind, v.kind or "")
        desc = (v.jp_name or "") + ("  (your variable)" if v.extra else "")
        rows.append((v.name, kind, str(v.bit_offset), str(w), rng, desc, v.name))
    for lo, hi, name, detail in emflags.ZONE2_BLOCKS:
        ids = str(emflags.ZONE2_BASE + lo) if lo == hi else "%d – %d" % (emflags.ZONE2_BASE + lo, emflags.ZONE2_BASE + hi)
        rows.append(("zone 2: " + name, "zone-2 bit", ids, "1", "0 / 1",
                     detail + "  (ops 318 / 443 / 445 and map objects, not an EVAL variable)",
                     "flag@%d/1" % (emflags.ZONE2_BASE + lo)))
    return rows


def variable_choices(doc):
    """[(display, token)] for EVAL / condition pickers: the emdeb variables and the registers."""
    out = [("reg%d  (VM register)" % i, "reg%d" % i) for i in range(10)]
    for name, kind, bid, w, rng, desc, tok in flag_rows(doc):
        if kind != "zone-2 bit":
            out.append(("%s  %s" % (name, desc[:40]), tok))
    return out


def verified_ops():
    """Action ops and control mnemonics marked human-verified in opcode_table.json."""
    acts = [int(k) for k, r in meta.TABLE["actions"].items() if r.get("human_verified")]
    ctl = [r["mnemonic"] for r in meta.TABLE["control"].values() if r.get("human_verified")]
    return sorted(acts), ctl


def op_info_text(op):
    """Everything opcode_table.json knows about an action op, as plain text."""
    r = meta.table_row(op) or {}
    L = [meta.prototype(op), ""]
    fam = meta.OPCODE_ARGS.get(op)
    if fam:
        L.append("opcode %d = %s" % (op, ", ".join("%s %s" % (a["name"], a["value"]) for a in fam)))
    L.append("category: %s    opcode: %d (0x%03X)    %s" % (
        meta.category_label(op), op, op, "✓ verified in game" if r.get("human_verified") else "not yet verified in game"))
    L += ["", meta.describe(op) or ""]
    args = r.get("args") or []
    if fam or args:
        L += ["", "Arguments:"]
        for a in fam or ():
            L.append("  %s (in the opcode): %s" % (a["name"], a["values"]))
        for i, a in enumerate(args):
            L.append("  %d. %s — %s%s   [%s]" % (i, a["name"], a.get("type") or "",
                                               (": " + a["values"]) if a.get("values") else "",
                                               "✓ verified" if a.get("human_verified") else "not verified"))
            for v, e in (a.get("value_names") or {}).items():
                L.append("       %s = %s%s%s" % (v, e["name"], ("  " + e["text"]) if e.get("text") else "",
                                                 "  ✓" if e.get("human_verified") else "  (untested)"))
            for te in a.get("tests") or ():
                L.append("       tested %s: %s -> %s" % (te["date"], te["call"], te["observed"]))
    for k, lab in (("returns", "Returns"), ("blocking", "Blocks"), ("side_effects", "Side effects")):
        if r.get(k):
            L += ["", "%s: %s" % (lab, r[k])]
    ex = r.get("example")
    if ex:
        L += ["", "Example (bank %d):" % ex["bank"]] + ex["lines"]
    return "\n".join(L)


def control_info_text(mnem):
    r = next((x for x in meta.TABLE["control"].values() if x["mnemonic"] == mnem), {})
    L = [r.get("prototype") or mnem, "", CONTROL_HELP.get(mnem, ""), "", r.get("description") or ""]
    ex = r.get("example")
    if ex:
        L += ["", "Example (bank %d):" % ex["bank"]] + ex["lines"]
    return "\n".join(L)


# ---- widgets --------------------------------------------------------------------------- #
class _Filtered(ttk.Frame):
    """A filter box over a Treeview: every typed word must appear in the row."""

    def __init__(self, parent, columns, widths, rows, on_select=None, on_activate=None, height=18):
        super().__init__(parent)
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 4))
        ttk.Label(top, text="Filter").pack(side="left")
        self.q = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.q)
        e.pack(side="left", fill="x", expand=True, padx=4)
        self.count = ttk.Label(top, foreground="#888")
        self.count.pack(side="right")
        f = ttk.Frame(self)
        f.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(f, columns=columns, show="headings", height=height)
        for c, w in zip(columns, widths):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, stretch=(w >= 200), anchor="w")
        sb = ttk.Scrollbar(f, command=self.tree.yview)
        self.tree.config(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.rows = rows
        self._pending = None
        self.q.trace_add("write", lambda *_a: self._schedule())
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda _e: on_select(self.selected()))
        if on_activate:
            self.tree.bind("<Double-Button-1>", lambda _e: on_activate(self.selected()))
            self.tree.bind("<Return>", lambda _e: on_activate(self.selected()))
        self.entry = e
        self.fill()

    def _schedule(self):
        if self._pending is not None:
            self.after_cancel(self._pending)
        self._pending = later(self, self.fill, 150)

    def fill(self):
        self._pending = None
        self.tree.delete(*self.tree.get_children())
        words = self.q.get().lower().split()
        n = 0
        for i, r in enumerate(self.rows):
            shown = r[:len(self.tree["columns"])]
            if words:
                low = " ".join(str(x) for x in r).lower()
                if not all(w in low for w in words):
                    continue
            self.tree.insert("", "end", iid=str(i), values=shown)
            n += 1
            if n >= 3000:
                break
        self.count.config(text="%d shown%s" % (n, " (first 3000)" if n >= 3000 else ""))

    def selected(self):
        s = self.tree.selection()
        return self.rows[int(s[0])] if s else None


class ReferenceWindow:
    """Searchable reference lists (one window per editor)."""

    TABS = ("Flags & variables", "Functions", "Text codes", "Characters", "Maps", "Items")

    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.frame)
        self.win.title("Cutscene Editor — Reference")
        self.win.geometry("1000x640")
        self.nb = ttk.Notebook(self.win)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.status = ttk.Label(self.win, foreground="#888")
        self.status.pack(fill="x", padx=8, pady=(0, 6))
        self._flags()
        self._functions()
        self._text_codes()
        self._simple("Characters", ("character", "use as"), (420, 300), character_choices(),
                     "Character ids: arguments typed 'char id' take actor(Name) (or the number).")
        self._simple("Maps", ("map", "use as"), (520, 300), map_choices(),
                     "Map ids: arguments typed 'map id' take map(MAP_FILE) (or the number).")
        self._simple("Items", ("item", "use as"), (520, 120), item_choices(),
                     "Item ids: arguments typed 'item id' take the number.")

    def show(self, tab=None):
        self.win.deiconify()
        self.win.lift()
        if tab in self.TABS:
            self.nb.select(self.TABS.index(tab))

    def copy(self, text, what=""):
        if not text:
            return
        self.win.clipboard_clear()
        self.win.clipboard_append(text)
        self.status.config(text="copied %s%s" % (text, ("  (" + what + ")") if what else ""))

    def _flags(self):
        f = ttk.Frame(self.nb, padding=6)
        self.nb.add(f, text=self.TABS[0])
        ttk.Label(f, foreground="#666", wraplength=940, justify="left", text=(
            "emdeb.bin's variables: FLG_ = a 1-bit flag, REG_ = a number, EV_ = an event slot. "
            "id = the bit offset in the game-flags store, width = bits. Use the name in a "
            "condition or EVAL: BR_Z (FLG_X == 1) -> …, EVAL (REG_Y = 3). Zone-2 rows are the "
            "recovered bits past emdeb's names. Double-click = copy the name.")).pack(anchor="w", pady=(0, 4))
        rows = flag_rows(self.app.doc)
        t = _Filtered(f, ("name", "kind", "id", "width", "values", "description"),
                      (260, 70, 90, 50, 80, 380), rows,
                      on_activate=lambda r: r and self.copy(r[6], r[0]))
        t.pack(fill="both", expand=True)
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(4, 0))
        ttk.Button(b, text="Copy name", command=lambda: t.selected() and self.copy(t.selected()[6])).pack(side="left")

    def _functions(self):
        f = ttk.Frame(self.nb, padding=6)
        self.nb.add(f, text=self.TABS[1])
        acts, ctl = verified_ops()
        ttk.Label(f, foreground="#666", wraplength=940, justify="left", text=(
            "Instructions a person has checked in game (%d so far). Mark more with "
            "\"human_verified\": true in rf4s_modkit/opcode_table.json. Every instruction, "
            "verified or not, is in the Instruction picker." % (len(acts) + len(ctl)))).pack(anchor="w", pady=(0, 4))
        rows = []
        for m in ctl:
            rows.append((m, "control", CONTROL_HELP.get(m, ""), ("ctl", m)))
        for op in acts:
            rows.append((meta.prototype(op), "0x%03X  (%d)" % (op, op), meta.describe(op) or "", ("op", op)))
        pw = ttk.PanedWindow(f, orient="vertical")
        pw.pack(fill="both", expand=True)
        top = ttk.Frame(pw)
        det = tk.Text(pw, height=12, wrap="word", font=("Consolas", 9))
        t = _Filtered(top, ("function", "opcode", "what it does"), (380, 110, 440), rows,
                      on_select=lambda r: self._show_fn(det, r),
                      on_activate=lambda r: r and self.app.ask_insert_instruction(preset=r[3]), height=10)
        t.pack(fill="both", expand=True)
        pw.add(top, weight=1)
        pw.add(det, weight=1)
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(4, 0))
        ttk.Button(b, text="Insert this instruction…",
                   command=lambda: t.selected() and self.app.ask_insert_instruction(preset=t.selected()[3])).pack(side="left")

    def _text_codes(self):
        """The codes a dialogue line can contain (textlint.token_reference)."""
        from rf4s_modkit import textlint
        f = ttk.Frame(self.nb, padding=6)
        self.nb.add(f, text="Text codes")
        ttk.Label(f, foreground="#666", wraplength=940, justify="left", text=(
            "Codes inside dialogue text. The game swaps a ＠…＠ code for a value when it shows the "
            "line. Text can't read the script's registers, so a code reads a text slot instead: "
            "a small table per kind of value (numbers, characters, items, places …), 32 slots "
            "each. The script fills slot n before the line, e.g. SetVar3(0, reg0) and then "
            "\"Gained ＠０＠G!\" shows the number in number slot 0. The \"filled by\" column "
            "names the instructions that write the slot; a slot keeps its value until something "
            "writes it again. <n> is one character: 0-9 or ０-９, then Ａ-Ｖ = 10-31. "
            "Colours, raise / lower and button icons can't be typed: the editors write them as "
            "backslash escapes (\\red, \\btn(a) ...), a real backslash as \\\\. "
            "Double-click = copy the code.")).pack(anchor="w", pady=(0, 4))
        rows = [(code, group, shows, setby or "—", code.replace("<n>", "０"))
                for code, group, shows, setby, _k in textlint.token_reference()]
        t = _Filtered(f, ("code", "group", "shows", "filled by"), (200, 90, 520, 150), rows,
                      on_activate=lambda r: r and self.copy(r[4], r[0]))
        t.pack(fill="both", expand=True)
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(4, 0))
        ttk.Button(b, text="Copy code", command=lambda: t.selected() and self.copy(t.selected()[4])).pack(side="left")

    @staticmethod
    def _show_fn(det, r):
        det.config(state="normal")
        det.delete("1.0", "end")
        if r:
            kind, key = r[3]
            det.insert("1.0", op_info_text(key) if kind == "op" else control_info_text(key))
        det.config(state="disabled")

    def _simple(self, title, cols, widths, choices, note):
        f = ttk.Frame(self.nb, padding=6)
        self.nb.add(f, text=title)
        ttk.Label(f, foreground="#666", text=note + " Double-click = copy.").pack(anchor="w", pady=(0, 4))
        t = _Filtered(f, cols, widths, list(choices), on_activate=lambda r: r and self.copy(r[1]))
        t.pack(fill="both", expand=True)


# ---- the instruction picker ------------------------------------------------------------ #
def _arg_spec(op, i, a):
    """(kind, [(display, token)], default token) of argument `i` of action `op`."""
    ch = script.enum_arg_choices(op, i)
    if ch:
        opts = [("%s  %s" % (v, lab), meta.value_name(op, i, v) or str(v)) for v, lab, _d in ch]
        return "enum", opts, opts[0][1]
    k = script.leaf_slot_kind(op, i)
    if k == "actor":
        return "actor", character_choices(), "actor(player)"
    if k == "map":
        opts = map_choices()
        return "map", opts, opts[0][1] if opts else "0"
    typ = (a.get("type") or "").lower()
    if "item id" in typ:
        return "item", item_choices(), "0"
    if typ in ("bool", "0/1", "flag"):
        return "enum", [("0  no / off", "0"), ("1  yes / on", "1")], "0"
    return "text", [], "0"


def coordinate_pairs(args):
    """[(i_x, i_y)] of absolute map-position argument pairs: an argument named x followed by
    one named y, not a relative offset. Script coordinates are 1/8-tile units (sub-units):
    the handlers store value << 12 as the actor's world position (e.g. SpawnEventActor,
    RF4S.exe+0x213660), and a live read of the game matches the map at 8 per tile."""
    out = []
    for i in range(len(args) - 1):
        a, b = args[i], args[i + 1]
        if (a.get("name") or "").lower() == "x" and (b.get("name") or "").lower() == "y":
            typ = ((a.get("type") or "") + " " + (b.get("type") or "")).lower()
            if "offset" not in typ:
                out.append((i, i + 1))
    return out


def map_arg_index(op, args):
    """Index of `op`'s map argument (a map() leaf slot or an argument named 'map'), or None."""
    for i, a in enumerate(args):
        if script.leaf_slot_kind(op, i) == "map" or (a.get("name") or "").lower() == "map":
            return i
    return None


def position_map(op, args, arg_value, bank):
    """(map id | None, lock reason | None, note, map arg index | None) for picking an x / y of
    `op`. The position is on the map the op names (its map argument) when it has one, else
    on the map the scene runs on: a map's own (tail) bank runs on that map, so it is fixed;
    a primary / global bank is not tied to a map, so the user chooses. `arg_value(i)` gives
    argument i's constant (int) or None when it is not a constant."""
    mi = map_arg_index(op, args)
    if mi is not None:
        mid = arg_value(mi)
        if mid is not None:
            return mid, "this instruction's map argument (%s) says which map the position is on; "\
                        "change that argument to use another map" % args[mi]["name"], "", mi
        return None, None, ("the map argument is not set to a map yet: the map you choose here is "
                            "written into it"), mi
    if bank is not None and bank.kind == "tail":
        return bank.index, ("the scene is in this map's event bank, so the instruction runs on "
                            "this map"), "", None
    return None, None, ("this scene is not tied to one map (a %s bank): choose the map it will run "
                        "on" % (bank.kind if bank is not None else "script")), None


class MapPointPicker:
    """Click a point on a rendered map: returns sub-unit (1/8 tile) x, y to `on_pick`."""

    def __init__(self, parent, map_id, x, y, on_pick, lock=None, note=None):
        """`lock` = why the map is fixed (the op runs on the scene's map, or takes it from a
        map argument): the map cannot be changed here. Without it the map can be chosen, and
        `note` says what the choice means."""
        from map_editor.view import MapView
        self.on_pick = on_pick
        self.map_id = None
        self.win = tk.Toplevel(parent)
        self.win.title(self.TITLE)
        self.win.geometry("1000x760")
        top = ttk.Frame(self.win)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Label(top, text="Map").pack(side="left")
        maps = map_choices()
        self._map_tok = {d: t for d, t in maps}
        self.map_cb = FilterCombo(top, [d for d, _t in maps], on_pick=self._map_picked, width=60)
        self.map_cb.pack(side="left", padx=4)
        self.locked = bool(lock and map_id is not None)
        if self.locked:
            self.map_cb.state(["disabled"])
        why = ("fixed: " + lock) if self.locked else (note or "")
        if why:
            ttk.Label(self.win, text=why, foreground="#2a6a8a" if self.locked else "#8a5a00",
                      wraplength=960, justify="left").pack(anchor="w", padx=8, before=None)
        self.grid_var = tk.BooleanVar(value=MapPointPicker.show_grid)
        gc = ttk.Checkbutton(top, text="grid", variable=self.grid_var, command=self._grid)
        gc.pack(side="left", padx=(8, 0))
        Tip(gc, "Tile grid lines (one square = one tile = 8 units; drawn from 4 px per tile up, "
                "so zoom in if they don't show).")
        self.readout = ttk.Label(top, foreground="#555")
        self.readout.pack(side="left", padx=8)
        ttk.Label(self.win, foreground="#666", text=self.HELP).pack(anchor="w", padx=8)
        self.view = MapView(self.win, on_hover_tile=None)
        self.view.pack(fill="both", expand=True, padx=6, pady=4)
        self.view.on_zoom = self._draw
        c = self.view.canvas
        c.bind("<Button-1>", self._click)
        c.bind("<Double-Button-1>", lambda e: (self._click(e), self._use()))
        c.bind("<Motion>", self._hover, add="+")
        bb = ttk.Frame(self.win)
        bb.pack(fill="x", padx=6, pady=6)
        ttk.Button(bb, text="Cancel", command=self.win.destroy).pack(side="right")
        ttk.Button(bb, text=self.USE_TEXT, command=self._use).pack(side="right", padx=4)
        self.pt = (x, y) if x is not None and y is not None else None
        if map_id is not None:
            self.load(map_id)

    show_grid = False                   # remembered for the session
    TITLE = "Pick a position on the map"
    USE_TEXT = "Use this position"
    HELP = ("Click = place the point · double-click = use it and close · wheel = zoom · "
            "middle-drag = pan. Values are in 1/8 tiles (8 per tile), as the script stores "
            "them; the white markers are this map's scripted NPC spawns.")

    def _grid(self):
        MapPointPicker.show_grid = on = bool(self.grid_var.get())
        self.view.st.layers["grid"] = on
        if self.view.doc is not None:
            self.view.invalidate("grid")

    def _map_picked(self, disp):
        tok = self._map_tok.get(disp)
        mid = script.map_leaf_value(tok[4:-1]) if tok else None
        if mid is not None:
            self.load(mid)

    def load(self, mid):
        from map_editor import data
        from map_editor.document import MapDocument
        from rf4s_modkit import rf4m
        name = data.rooms_by_id().get(mid)
        hit = data.find_extracted("%s.rf4m" % name) if name else None
        if hit is None:
            self.readout.config(text="map %s is not in the extracted game files" % mid)
            return False
        self.map_id = mid
        disp = next((d for d, t in map_choices() if t == script.map_leaf_text(mid)), name)
        self.map_cb.var.set(disp)
        v = self.view
        v.set_reader(data.folder_reader(hit.parent))
        v.set_doc(MapDocument(rf4m.Rf4mMap.load(hit), name, load_sidecars=False))
        v.st.layers["attr"] = False
        v.st.layers["grid"] = bool(self.grid_var.get())
        try:
            v.st.spawns = data.script_spawns(v.doc.base)[1]
            v.st.layers["spawns"] = True
            v.invalidate("spawn")
        except Exception:  # noqa: BLE001 -- the spawn overlay is only context
            pass
        v.request_ground()
        at = (self.pt[0] // 8, self.pt[1] // 8) if self.pt else None
        v.open_view(at=at)
        later(self.win, self._draw, 50)
        return True

    # The marker carries the view's "preview" tag: MapView._restack raises that group last
    # after every redraw (ground arriving, hover, zoom), so the map never covers it.
    MARK_TAGS = ("pickpt", "preview")

    def _draw(self):
        c = self.view.canvas
        c.delete("pickpt")
        if self.pt and self.view.doc is not None:
            cp = self.view.cp
            x, y = self.pt[0] * cp / 8.0, self.pt[1] * cp / 8.0
            r = max(6, cp // 2)
            c.create_oval(x - r, y - r, x + r, y + r, outline="#ff3050", width=2, tags=self.MARK_TAGS)
            c.create_line(x - r - 4, y, x + r + 4, y, fill="#ff3050", width=2, tags=self.MARK_TAGS)
            c.create_line(x, y - r - 4, x, y + r + 4, fill="#ff3050", width=2, tags=self.MARK_TAGS)
            c.tag_raise("pickpt")
        self._readout()

    def _readout(self, pointer=None):
        """'picked: x, y (tile) · pointer: x, y (tile)' -- both update live."""
        parts = []
        if self.pt:
            parts.append("picked: x = %d, y = %d  (tile %d, %d)" % (
                self.pt[0], self.pt[1], self.pt[0] // 8, self.pt[1] // 8))
        if pointer is not None:
            parts.append("pointer: x = %d, y = %d  (tile %d, %d)" % (
                pointer[0], pointer[1], pointer[0] // 8, pointer[1] // 8))
        self.readout.config(text="    ·    ".join(parts))

    def _hover(self, e):
        if self.view.doc is None:
            return
        self._readout(self.view.subunit_at(e))

    def _click(self, e):
        if self.view.doc is None:
            return
        self.pt = self.view.subunit_at(e)
        self._draw()
        self._readout(self.pt)

    def _use(self):
        if self.pt:
            self.on_pick(self.pt[0], self.pt[1], self.map_id)
            self.win.destroy()


class MapBoxPicker(MapPointPicker):
    """Drag a box on a rendered map: returns sub-unit x1, y1, x2, y2 (normalised) to `on_pick`."""

    TITLE = "Draw a box on the map"
    USE_TEXT = "Use this box"
    HELP = ("Drag = draw the box · wheel = zoom · middle-drag = pan. Values are in 1/8 tiles "
            "(8 per tile), the units trigger boxes compare the player's position in.")

    def __init__(self, parent, map_id, box, on_pick, lock=None, note=None):
        self.box = self._norm(box) if box else None
        self._start = None
        super().__init__(parent, map_id, None, None, on_pick, lock=lock, note=note)
        c = self.view.canvas
        c.bind("<Button-1>", self._press)
        c.bind("<B1-Motion>", self._drag)
        c.bind("<ButtonRelease-1>", self._release)
        c.unbind("<Double-Button-1>")

    @staticmethod
    def _norm(b):
        x1, y1, x2, y2 = b
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)

    def load(self, mid):
        ok = super().load(mid)
        if ok and self.box:
            x1, y1, x2, y2 = self.box
            v = self.view
            later(self.win, lambda: v.center_on((x1 + x2) / 16.0, (y1 + y2) / 16.0), 80)
        return ok

    def _draw(self):
        c = self.view.canvas
        c.delete("pickpt")
        if self.box and self.view.doc is not None:
            cp = self.view.cp
            x1, y1, x2, y2 = (v * cp / 8.0 for v in self.box)
            c.create_rectangle(x1, y1, x2, y2, outline="#ff3050", width=2, tags=self.MARK_TAGS)
            c.create_rectangle(x1, y1, x2, y2, outline="", fill="#ff3050", stipple="gray25",
                               tags=self.MARK_TAGS)
            c.tag_raise("pickpt")
        self._readout()

    def _readout(self, pointer=None):
        parts = []
        if self.box:
            x1, y1, x2, y2 = self.box
            parts.append("box: x = %d, y = %d, w = %d, h = %d  (tiles %d, %d – %d, %d)" % (
                x1, y1, x2 - x1, y2 - y1, x1 // 8, y1 // 8, x2 // 8, y2 // 8))
        if pointer is not None:
            parts.append("pointer: x = %d, y = %d" % pointer)
        self.readout.config(text="    ·    ".join(parts))

    def _press(self, e):
        if self.view.doc is None:
            return
        self._start = self.view.subunit_at(e)
        self.box = self._start + self._start
        self._draw()

    def _drag(self, e):
        if self._start is None or self.view.doc is None:
            return
        self.box = self._norm(self._start + self.view.subunit_at(e))
        self._draw()
        self._readout(self.view.subunit_at(e))

    def _release(self, e):
        self._drag(e)
        self._start = None

    def _use(self):
        if self.box:
            self.on_pick(*self.box, self.map_id)
            self.win.destroy()


class _Field:
    """One labelled input: an editable, filterable combobox (display -> token) or an entry."""

    def __init__(self, parent, row, label, hint, options, default, on_change, width=46):
        self.row = row
        self.opts = dict(options)
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 6), pady=2)
        self.var = tk.StringVar()
        if options:
            w = FilterCombo(parent, [d for d, _t in options], on_pick=lambda _t: on_change(), width=width,
                            textvariable=self.var)
            disp = next((d for d, t in options if t == default), default)
            self.var.set(disp)
        else:
            w = ttk.Entry(parent, textvariable=self.var, width=width + 3)
            self.var.set(default)
        w.grid(row=row, column=1, sticky="we", pady=2)
        self.widget = w
        if hint:
            ttk.Label(parent, text=hint, foreground="#777", wraplength=380, justify="left",
                      font=("Segoe UI", 8)).grid(row=row + 1, column=1, sticky="w")
        self.var.trace_add("write", lambda *_a: on_change())

    def token(self):
        v = self.var.get().strip()
        return self.opts.get(v, v)


class InstructionPicker:
    """Pick any instruction, fill in its arguments, preview the listing, insert it."""

    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.frame)
        self.win.title("Cutscene Editor — Add an instruction")
        self.win.geometry("1150x700")
        self.key = None                 # ("op", n) | ("ctl", mnemonic)
        self.fields = []
        self.rows = []                  # repeating rows (targets / choice options)
        self.manual = False
        self._pending = None
        pw = ttk.PanedWindow(self.win, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=6, pady=6)
        left = ttk.Frame(pw)
        pw.add(left, weight=1)
        top = ttk.Frame(left)
        top.pack(fill="x")
        ttk.Label(top, text="Search").pack(side="left")
        self.q = tk.StringVar()
        se = ttk.Entry(top, textvariable=self.q)
        se.pack(side="left", fill="x", expand=True, padx=4)
        self.only_ver = tk.BooleanVar(value=False)
        ttk.Checkbutton(left, text="only instructions verified in game", variable=self.only_ver,
                        command=self.fill_tree).pack(anchor="w")
        tf = ttk.Frame(left)
        tf.pack(fill="both", expand=True, pady=(4, 0))
        self.tree = ttk.Treeview(tf, columns=("op", "v"), show="tree headings")
        self.tree.heading("#0", text="instruction")
        self.tree.heading("op", text="opcode")
        self.tree.heading("v", text="✓")
        self.tree.column("#0", width=250)
        self.tree.column("op", width=80, anchor="w")
        self.tree.column("v", width=24, anchor="center")
        sb = ttk.Scrollbar(tf, command=self.tree.yview)
        self.tree.config(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._picked)
        self.q.trace_add("write", lambda *_a: self._schedule_tree())

        right = ttk.Frame(pw, padding=(8, 0))
        pw.add(right, weight=2)
        self.title = ttk.Label(right, font=("Segoe UI", 11, "bold"))
        self.title.pack(anchor="w")
        self.desc = ttk.Label(right, wraplength=680, justify="left", foreground="#444")
        self.desc.pack(anchor="w", pady=(2, 6))
        self.form = ttk.Frame(right)
        self.form.pack(fill="x")
        self.form.columnconfigure(1, weight=1)
        ttk.Separator(right).pack(fill="x", pady=6)
        ph = ttk.Frame(right)
        ph.pack(fill="x")
        ttk.Label(ph, text="Listing (what gets inserted — you can also edit it by hand):").pack(side="left")
        self.rebuild_btn = ttk.Button(ph, text="Rebuild from the form", command=self._rebuild)
        self.preview = tk.Text(right, height=7, font=("Consolas", 10), wrap="none", undo=True)
        self.preview.pack(fill="both", expand=True)
        self.preview.bind("<Key>", self._typed)
        self.check_lbl = ttk.Label(right, wraplength=680, justify="left")
        self.check_lbl.pack(anchor="w", pady=(4, 0))
        bb = ttk.Frame(right)
        bb.pack(fill="x", pady=(6, 0))
        self.where = tk.StringVar(value="after")
        ttk.Radiobutton(bb, text="after the selected statement", value="after", variable=self.where).pack(side="left")
        ttk.Radiobutton(bb, text="before it", value="before", variable=self.where).pack(side="left", padx=6)
        ttk.Button(bb, text="Close", command=self.win.withdraw).pack(side="right")
        ib = ttk.Button(bb, text="Insert", command=self.insert)
        ib.pack(side="right", padx=4)
        Tip(ib, "Insert the listing at the selected statement of the open scene (Ctrl+Enter). "
                "The window stays open, so you can add several in a row; each lands after the "
                "one before it.")
        sb2 = ttk.Button(bb, text="Whole scene in the Source tab", command=self._source_tab)
        sb2.pack(side="right", padx=4)
        Tip(sb2, "Prefer typing? The Source tab has the whole scene as editable listing text.")
        self.win.bind("<Control-Return>", lambda _e: (self.insert(), "break")[1])
        self.win.protocol("WM_DELETE_WINDOW", self.win.withdraw)
        self._tree_pending = None
        self.fill_tree()

    # ---- the list ---------------------------------------------------------------- #
    def _schedule_tree(self):
        if self._tree_pending is not None:
            self.win.after_cancel(self._tree_pending)
        self._tree_pending = later(self.win, self.fill_tree, 150)

    def entries(self):
        """[(group, iid, text, opcode text, verified, search text)] -- control instructions,
        then every named action op by category (a family such as SetSpeaker once)."""
        out = []
        for m in CONTROL_ORDER:
            r = next((x for x in meta.TABLE["control"].values() if x["mnemonic"] == m), {})
            out.append((CONTROL_GROUP, "ctl:" + m, m, r.get("op_hex", ""), bool(r.get("human_verified")),
                        "%s %s %s" % (m, CONTROL_HELP.get(m, ""), r.get("description", ""))))
        seen_fam = set()
        for op in range(script.DISPATCHABLE_ACTION_OPS):
            m = meta.mnemonic(op)
            if not m or m.startswith("(") or m in PLACEHOLDER:
                continue
            fam = meta.OPCODE_ARGS.get(op)
            if fam:
                if m in seen_fam:
                    continue
                seen_fam.add(m)
                ops = [o for o in meta.OPCODE_ARGS if meta.mnemonic(o) == m]
                optxt = "%d–%d" % (min(ops), max(ops))
                ver = all(meta.human_verified(o) for o in ops)
            else:
                optxt = "0x%03X" % op
                ver = meta.human_verified(op)
            out.append((meta.category_label(op), "op:%d" % op, m, optxt, ver,
                        "%s %d %s" % (m, op, meta.describe(op) or "")))
        return out

    def fill_tree(self):
        self._tree_pending = None
        self.tree.delete(*self.tree.get_children())
        words = self.q.get().lower().split()
        groups = {}
        n = 0
        for grp, iid, text, optxt, ver, hay in self.entries():
            if self.only_ver.get() and not ver:
                continue
            if words and not all(w in hay.lower() for w in words):
                continue
            if grp not in groups:
                groups[grp] = self.tree.insert("", "end", iid="grp:" + grp, text=grp, open=bool(words))
            self.tree.insert(groups[grp], "end", iid=iid, text=text, values=(optxt, "✓" if ver else ""))
            n += 1
        if CONTROL_GROUP in groups and not words:
            self.tree.item(groups[CONTROL_GROUP], open=True)
        return n

    def _picked(self, _e=None):
        s = self.tree.selection()
        if not s or s[0].startswith("grp:"):
            return
        kind, _, key = s[0].partition(":")
        self.set_instruction((kind, int(key) if kind == "op" else key))

    def preset(self, key):
        """Show instruction `key` (('op', n) or ('ctl', mnemonic)) and select it in the list."""
        self.q.set("")
        self.fill_tree()
        iid = "%s:%s" % key
        if key[0] == "op" and meta.OPCODE_ARGS.get(key[1]):
            first = min(o for o in meta.OPCODE_ARGS if meta.mnemonic(o) == meta.mnemonic(key[1]))
            iid = "op:%d" % first
        if self.tree.exists(iid):
            self.tree.see(iid)
            self.tree.selection_set(iid)
        self.set_instruction(key)

    # ---- the form ---------------------------------------------------------------- #
    def set_instruction(self, key):
        self.key = key
        self.manual = False
        self.rebuild_btn.pack_forget()
        for w in self.form.winfo_children():
            w.destroy()
        self.fields = []
        self.rows = []
        if key[0] == "op":
            self._action_form(key[1])
        else:
            self._control_form(key[1])
        self._rebuild()

    def _add(self, label, hint, options, default, width=46):
        f = _Field(self.form, 2 * len(self.fields) + 10, label, hint, options, default, self._changed, width)
        self.fields.append(f)
        return f

    def _action_form(self, op):
        r = meta.table_row(op) or {}
        fam = meta.OPCODE_ARGS.get(op)
        m = meta.mnemonic(op)
        self.title.config(text=meta.prototype(op))
        ver = "✓ verified in game" if (meta.human_verified(op) if not fam else all(
            meta.human_verified(o) for o in meta.OPCODE_ARGS if meta.mnemonic(o) == m)) else "not yet verified in game"
        self.desc.config(text="%s\n%s · %s" % (meta.describe(op) or "", meta.category_label(op), ver))
        self.op_fields = []
        self.fam_fields = []
        if fam:
            ops = [o for o in meta.OPCODE_ARGS if meta.mnemonic(o) == m]
            for i, a in enumerate(fam):
                vals = []
                for o in sorted(ops):
                    v = meta.OPCODE_ARGS[o][i]["value"]
                    if v not in vals:
                        vals.append(v)
                self.fam_fields.append(self._add(a["name"], "encoded in the opcode (%s)" % a["encoding"],
                                                 [(v, v) for v in vals], a["value"], width=30))
        self.args = r.get("args") or [{"name": n} for n in meta.arg_names(op)]
        # how many arguments: the shipped game's fewest / most (meta.arg_range: a missing one
        # is read as leftover memory), else the table's optional_args_from; the last named
        # argument repeats for a variadic op
        rng = meta.arg_range(op)
        n_args = len(self.args)
        self.opt_from = rng[0] if rng else r.get("optional_args_from")
        if self.opt_from is None:
            self.opt_from = n_args
        lim = meta.arg_limit(op)
        self.max_args = min(x for x in ((rng[1] if rng else None), (lim[0] if lim else None),
                                        (None if (r.get("size") or [0, 0])[1] is None else n_args), 64)
                            if x is not None)
        self.max_args = max(self.max_args, self.opt_from, n_args if (r.get("size") or [0, 0])[1] is not None else 0)
        self.op = op
        for i in range(max(self.opt_from, min(n_args, self.max_args))):
            self._op_field(i)
        if self.max_args > len(self.op_fields):
            self.more_btn = ttk.Button(self.form, text="＋ another argument", command=self._more)
            self.more_btn.grid(row=900, column=1, sticky="w", pady=4)
        for ix, iy in coordinate_pairs(self.args):
            if iy < len(self.op_fields):
                b = ttk.Button(self.form, text="📍 Pick on map…",
                               command=lambda ix=ix, iy=iy: self.pick_on_map(ix, iy))
                b.grid(row=self.op_fields[ix].row, column=2, rowspan=2, sticky="nw", padx=4)
                Tip(b, "Click the position on the map instead of typing x and y (1/8-tile units).")
        if not self.op_fields and not fam and self.max_args == 0:
            ttk.Label(self.form, text="(no arguments)", foreground="#777").grid(row=10, column=1, sticky="w")

    def _op_field(self, i):
        """The form field of argument i (the last named argument repeats past the list)."""
        op = self.op
        a = self.args[min(i, len(self.args) - 1)] if self.args else {"name": "arg"}
        kind, opts, default = _arg_spec(op, i, a)
        hint = ((a.get("type") or "") + (": " + a["values"] if a.get("values") else ""))[:300]
        hint = ("✓ verified in game. " if a.get("human_verified") else "not verified in game. ") + hint
        label = a["name"] if i < len(self.args) else "%s #%d" % (a["name"], i - len(self.args) + 2)
        if i >= self.opt_from:
            label += " (optional)"
            default = ""
            hint = "leave empty to leave it out. " + hint
        self.op_fields.append(self._add(label, hint, opts, default))

    def _field_value(self, i):
        """Argument i's value as an int (map(MAP_X) / actor(...) leaves resolved), or None."""
        if i >= len(self.op_fields):
            return None
        t = self.op_fields[i].token()
        if t.startswith("map(") and t.endswith(")"):
            return script.map_leaf_value(t[4:-1])
        try:
            return int(t, 0)
        except ValueError:
            return None

    def position_map(self):
        """(map id, lock, note, map arg index): see position_map()."""
        return position_map(self.op, self.args, self._field_value, getattr(self.app, "bank", None))

    def scene_map_id(self):
        return self.position_map()[0]

    def pick_on_map(self, ix, iy):
        mid, lock, note, mi = self.position_map()

        def done(x, y, chosen):
            self.op_fields[ix].var.set(str(x))
            self.op_fields[iy].var.set(str(y))
            if mi is not None and mid is None and chosen is not None and mi < len(self.op_fields):
                self.op_fields[mi].var.set(script.map_leaf_text(chosen)
                                           if script.leaf_slot_kind(self.op, mi) == "map" else str(chosen))
        self._map_picker = MapPointPicker(self.win, mid, self._field_value(ix), self._field_value(iy),
                                          done, lock=lock, note=note)
        return self._map_picker

    def _more(self):
        self._op_field(len(self.op_fields))
        if len(self.op_fields) >= self.max_args:
            self.more_btn.grid_remove()
        self._changed()

    def _targets(self):
        """[(display, token)] for jump targets: the open scene's statements (0xPC)."""
        app = self.app
        out = []
        sc = getattr(app, "scene", None)
        if sc is None:
            return out
        labels = script.scene_labels(sc)
        for pc, st in sc.stmts.items():
            if st.mnem == "DIALOG":
                t = (app.doc.text(st.dialog_id) or "").replace("\n", " ")[:50]
                what = 'DIALOG "%s"' % t
            elif st.op < 0xFFF0:
                what = meta.mnemonic(st.op)
            else:
                what = st.mnem
            lab = labels.get(pc)
            out.append(("0x%04x  %s%s" % (pc, (lab + ": ") if lab else "", what), "0x%04x" % pc))
        return out

    def _cond(self, prefix="condition"):
        vars_ = variable_choices(self.app.doc)
        self.c_left = self._add(prefix + ": variable", "a flag / register name, or any expression",
                                vars_, vars_[10][1] if len(vars_) > 10 else "reg0")
        self.c_cmp = self._add("compare", "", [(c, c) for c in ("==", "!=", ">", ">=", "<", "<=", "(is non-zero)")],
                               "==", width=14)
        self.c_right = self._add("value", "", [], "1", width=14)

    def _cond_text(self):
        cmp = self.c_cmp.token()
        if cmp == "(is non-zero)":
            return "(%s)" % self.c_left.token()
        return "(%s %s %s)" % (self.c_left.token(), cmp, self.c_right.token())

    def _control_form(self, m):
        r = next((x for x in meta.TABLE["control"].values() if x["mnemonic"] == m), {})
        self.title.config(text=r.get("prototype") or m)
        self.desc.config(text=CONTROL_HELP.get(m, ""))
        tg = self._targets()
        tdef = tg[0][1] if tg else "0x0000"
        if m == "DIALOG":
            self.line = self._add("line id", "the dialogue line (#id) in rf3mc.<locale>", [], "0", width=14)
            b = ttk.Frame(self.form)
            b.grid(row=99, column=1, sticky="w", pady=4)
            ttk.Button(b, text="Find a line…", command=self._find_line).pack(side="left")
            nb = ttk.Button(b, text="New line… (speaker + text)", command=self._new_line)
            nb.pack(side="left", padx=4)
            Tip(nb, "Write a new line with its speaker, face and box style (the Add dialogue line "
                    "form); it is inserted straight away.")
            self.line_txt = ttk.Label(self.form, foreground="#555", wraplength=520, justify="left")
            self.line_txt.grid(row=100, column=1, sticky="w")
        elif m == "EVAL":
            vars_ = variable_choices(self.app.doc)
            self.e_var = self._add("variable", "flag / register to change", vars_, vars_[10][1] if len(vars_) > 10 else "reg0")
            self.e_op = self._add("operation", "", [(o, o) for o in ("=", "+=", "-=", "*=", "/=", "%=", "&&=", "||=")], "=", width=14)
            self.e_val = self._add("value", "a number or an expression", [], "1", width=20)
        elif m in ("BR_Z", "BR_NZ", "RET_NZ"):
            self._cond()
            if m != "RET_NZ":
                self.t1 = self._add("target", "where to jump (a statement of this scene)", tg, tdef)
        elif m in ("JMP", "CALL"):
            self.t1 = self._add("target", "a statement of this scene", tg, tdef)
        elif m == "FRAME":
            self.n = self._add("stack words", "an even number; the editor sizes it by itself", [], "2", width=14)
        elif m in ("SWITCH", "SWITCH_CLAMP"):
            vars_ = variable_choices(self.app.doc)
            self.sel_f = self._add("selector", "the value that picks the target", vars_, "reg0")
            self._rows_ui("targets (0, 1, 2, …)", [("target", tg, tdef)], 2)
        elif m == "JMP_RAND":
            self._rows_ui("targets", [("target", tg, tdef)], 2)
        elif m == "JMP_WEIGHTED":
            self._rows_ui("weighted targets", [("weight", [], "1"), ("target", tg, tdef)], 2)
        elif m in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED"):
            if m == "PROMPT_CHOICE":
                self.cancel = self._add("cancel target", "where B / Cancel goes", tg, tdef)
            self._rows_ui("options (line id → target)", [("line id", [], "0"), ("target", tg, tdef)], 2)
        else:
            ttk.Label(self.form, text="(no operands)", foreground="#777").grid(row=10, column=1, sticky="w")

    def _rows_ui(self, title, cols, n):
        box = ttk.LabelFrame(self.form, text=title, padding=4)
        box.grid(row=200, column=0, columnspan=2, sticky="we", pady=4)
        self._rows_box, self._rows_cols = box, cols
        ttk.Button(box, text="＋ add", command=self._add_row).pack(anchor="w")
        for _ in range(n):
            self._add_row(render=False)

    def _add_row(self, render=True):
        f = ttk.Frame(self._rows_box)
        f.pack(fill="x", pady=1, before=self._rows_box.winfo_children()[0])
        row = []
        for label, opts, default in self._rows_cols:
            ttk.Label(f, text=label).pack(side="left", padx=(4, 2))
            var = tk.StringVar()
            if opts:
                w = FilterCombo(f, [d for d, _t in opts], on_pick=lambda _t: self._changed(),
                                width=34, textvariable=var)
                var.set(next((d for d, t in opts if t == default), default))
            else:
                w = ttk.Entry(f, textvariable=var, width=8)
                var.set(default)
            w.pack(side="left")
            var.trace_add("write", lambda *_a: self._changed())
            row.append((var, dict(opts)))
        rm = ttk.Button(f, text="✕", width=3)
        rm.pack(side="left", padx=4)
        entry = (f, row)
        rm.config(command=lambda: self._del_row(entry))
        self.rows.append(entry)
        if render:
            self._changed()

    def _del_row(self, entry):
        if entry in self.rows and len(self.rows) > 1:
            self.rows.remove(entry)
            entry[0].destroy()
            self._changed()

    def _row_tokens(self):
        return [[opts.get(v.get().strip(), v.get().strip()) for v, opts in row] for _f, row in self.rows]

    # ---- the listing ------------------------------------------------------------- #
    def listing(self):
        """The listing text of the form as filled in."""
        kind, key = self.key
        if kind == "op":
            op = key
            if self.fam_fields:
                op = meta.op_from_opcode_args(meta.mnemonic(key), [f.token() for f in self.fam_fields])
            args = [f.token() for f in self.op_fields]
            last = min(self.opt_from, len(args))       # optional args: up to the last one given
            for i in range(last, len(args)):
                if args[i]:
                    last = i + 1
            rng = meta.arg_range(op)                   # a family member may need more (SetSpeaker)
            last = max(last, min(rng[0], len(args)) if rng else 0)
            return scriptasm.action_line(op, [a or "0" for a in args[:last]])
        m = key
        if m == "DIALOG":
            return "DIALOG #%s" % self.line.token()
        if m == "EVAL":
            return "EVAL (%s %s %s)" % (self.e_var.token(), self.e_op.token(), self.e_val.token())
        if m in ("BR_Z", "BR_NZ"):
            return "%s %s -> %s" % (m, self._cond_text(), self.t1.token())
        if m == "RET_NZ":
            return "RET_NZ %s" % self._cond_text()
        if m in ("JMP", "CALL"):
            return "%s %s" % (m, self.t1.token())
        if m == "FRAME":
            return "FRAME %s" % self.n.token()
        rows = self._row_tokens()
        if m in ("SWITCH", "SWITCH_CLAMP"):
            return "%s (%s) -> %s" % (m, self.sel_f.token(), ", ".join(r[0] for r in rows))
        if m == "JMP_RAND":
            return "JMP_RAND " + ", ".join(r[0] for r in rows)
        if m == "JMP_WEIGHTED":
            return "JMP_WEIGHTED " + ", ".join("(%s) -> %s" % (w, t) for w, t in rows)
        if m == "PROMPT_CHOICE":
            return "PROMPT_CHOICE CANCEL -> %s, " % self.cancel.token() + ", ".join(
                "#%s -> %s" % (i, t) for i, t in rows)
        if m == "PROMPT_CHOICE_FORCED":
            return "PROMPT_CHOICE_FORCED " + ", ".join("#%s -> %s" % (i, t) for i, t in rows)
        return m

    def _changed(self):
        if self._pending is not None:
            self.win.after_cancel(self._pending)
        self._pending = later(self.win, self._rebuild_if_auto, 120)

    def _rebuild_if_auto(self):
        self._pending = None
        if not self.manual:
            self._rebuild()

    def _rebuild(self):
        self.manual = False
        self.rebuild_btn.pack_forget()
        try:
            text = self.listing() if self.key else ""
        except Exception as e:  # noqa: BLE001 -- e.g. an opcode argument that names nothing
            text = ""
            self.check_lbl.config(text="✗ %s" % err_text(e), foreground="#b00")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        if getattr(self, "line_txt", None) is not None and self.key == ("ctl", "DIALOG"):
            try:
                t = self.app.doc.text(int(self.line.token().lstrip("#")))
            except (ValueError, TypeError):
                t = None
            try:
                self.line_txt.config(text=('"%s"' % t) if t else "(no such line in this locale)")
            except tk.TclError:
                pass
        self.check()

    def _typed(self, _e=None):
        if not self.manual:
            self.manual = True
            self.rebuild_btn.pack(side="right")
        later(self.win, self.check, 50)

    def text(self):
        return self.preview.get("1.0", "end").strip()

    def check(self):
        text = self.text()
        if not text:
            return False
        err = self.app.assemble_check(text)[2] if self.app.doc.container is not None else "no rf3.mc loaded"
        self.check_lbl.config(text=("✗ " + err) if err else "✓ assembles", foreground="#b00" if err else "#080")
        return not err

    # ---- actions ----------------------------------------------------------------- #
    def insert(self):
        if not self.check():
            return False
        before = self.where.get() == "before"
        w = self.app._insert_where(before)
        if w is None:
            self.check_lbl.config(text="select a statement in the Script view first (the new "
                                       "instruction goes after / before it)", foreground="#b00")
            return False
        pc, before = w
        ok = self.app.insert_before(pc, self.text()) if before else self.app.insert_after(pc, self.text())
        if ok:
            self.check_lbl.config(text="✓ inserted — select another statement or insert again "
                                       "(it goes after the new one)", foreground="#080")
            self.where.set("after")
        return ok

    def _find_line(self):
        from . import dialogs
        i = dialogs.pick_line(self.win, self.app.doc)
        if i is not None:
            self.line.var.set(str(i))

    def _new_line(self):
        before = self.where.get() == "before"
        self.app.ask_insert_dialogue(before)

    def _source_tab(self):
        try:
            self.app.nb.select(self.app.nb.index(self.app.source))
            self.app.frame.winfo_toplevel().lift()
        except (tk.TclError, AttributeError):
            pass

    def show(self, preset=None, before=None):
        self.win.deiconify()
        self.win.lift()
        if before is not None:
            self.where.set("before" if before else "after")
        if preset is not None:
            self.preset(preset)
        elif self.key is None:
            self.preset(("ctl", "DIALOG"))
