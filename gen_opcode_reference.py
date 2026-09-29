#!/usr/bin/env python3
"""Generate CUTSCENE_OPCODES.md -- a complete, greppable reference for the reverse-engineered
rf3.mc cutscene Script VM opcodes, built entirely from rf4s_modkit/opcode_meta.py.

This is the GUI-free companion to the editor's hover tooltips: run it to (re)produce a browsable
markdown reference grouped by category, with each op's mnemonic, argument signature, technical
(IDA) handler name, and full description. Re-run after any opcode_meta change to refresh it.

    python gen_opcode_reference.py            # writes CUTSCENE_OPCODES.md + opcodes_list.csv

Two outputs, both from opcode_meta: CUTSCENE_OPCODES.md (grouped, rich) and opcodes_list.csv
(flat: op_dec, op_hex, mnemonic, category, prototype, description -- spreadsheet/grep friendly).
"""
import os
from rf4s_modkit import opcode_meta as om

N_OPS = 763
# category -> display order (matches the editor's category buckets)
CAT_ORDER = ["dialogue", "screen", "actor", "companion", "flag", "audio", "time",
             "item", "effect", "quest", "flow", "query", "misc", "noop"]
# noop placeholders that carry no author meaning -- collapsed into a single summary line
PLACEHOLDERS = {"(unbound)", "(unused)", "invalid"}


def build():
    # group ops by category, skipping pure placeholders (but keeping emitted 'nop' stubs)
    by_cat = {c: [] for c in CAT_ORDER}
    placeholder_ops = []
    for op in range(N_OPS):
        mn = om.mnemonic(op)
        if not mn:
            continue
        if mn in PLACEHOLDERS:
            placeholder_ops.append(op)
            continue
        cat = om.category(op)
        by_cat.setdefault(cat, []).append(op)

    named = sum(len(v) for v in by_cat.values())
    lines = [
        "# RF4S Cutscene Opcode Reference",
        "",
        "Reverse-engineered `rf3.mc` cutscene Script VM opcodes "
        "(`g_sceneActionHandlerTable`, RF4S.exe+0x4DB790, 763 slots).",
        "",
        f"Auto-generated from `rf4s_modkit/opcode_meta.py` by `gen_opcode_reference.py` — "
        f"**{named}** named opcodes across {sum(1 for v in by_cat.values() if v)} categories "
        f"(plus {len(placeholder_ops)} reserved/unused slots), the control-flow opcodes, the "
        "expression grammar, and the **em.bin** Event-Manager opcodes scenes bridge to. Do not edit "
        "by hand; re-run the generator to refresh. This is the GUI-free companion to the editor's "
        "Alt-hover tooltips.",
        "",
        "## Contents",
        "",
    ]
    for c in CAT_ORDER:
        if by_cat.get(c):
            lines.append(f"- [{om.category_label(_first_op(by_cat[c]))}](#{_anchor(c)}) "
                         f"({len(by_cat[c])} ops)")
    lines.append(f"- [Control opcodes (flow backbone)](#control-opcodes-flow-backbone) "
                 f"({len(om.CONTROL)} ops)")
    lines.append("- [Expression operands (argument encoding)]"
                 "(#expression-operands-argument-encoding)")
    lines.append("- [Event Manager (em.bin) opcodes](#event-manager-embin-opcodes)")
    lines.append("- [Opcode index (by number)](#opcode-index-by-number)")
    lines.append("")

    for c in CAT_ORDER:
        ops = by_cat.get(c)
        if not ops:
            continue
        lines.append(f"## {om.category_label(ops[0])}")
        lines.append("")
        for op in ops:
            proto = om.prototype(op)                       # concise signature
            tech = om.technical(op) or ""
            desc = (om.describe(op) or "").strip()
            args = om.arg_names(op)
            lines.append(f"### `op {op}` — {proto}")
            if om.OPCODE_ARGS.get(op):                     # SetSpeaker: arguments in the opcode
                lines.append("*opcode arguments:* " + ", ".join(
                    "%s = %s (%s)" % (a["name"], a["value"], a["encoding"]) for a in om.OPCODE_ARGS[op]))
            if tech:
                lines.append(f"*handler:* `{tech}`")
            if desc:
                lines.append("")
                lines.append(desc)
            if args:
                lines.append("")
                lines.append("Args:")
                for i, a in enumerate(args):
                    lines.append(f"  {i}. {a}")
                    # enum-picker values, so the reference is a true GUI-free companion: list the
                    # small dispatch/mode enums (world-interaction actions, effects, shake kinds,
                    # weather, companions, ...) in full; for large id-spaces (items/rooms) just note
                    # the count -- listing 1000+ ids would be noise, and the arg name says what it is.
                    choices = om.enum_arg_choices(op, i)
                    if choices:
                        if len(choices) <= 90:
                            for val, label, _d in choices:
                                lines.append(f"     - `{val}` = {label}")
                        else:
                            lines.append(f"     - *(enum: {len(choices)} values — use the "
                                         f"in-editor picker or the id database)*")
            lines.append("")

    # control opcodes (0xFFF0-0xFFFF) -- the flow backbone; NOT in the 763-slot action table, so
    # they don't come from the by_cat grouping. Sourced from the decoder's opcode->mnemonic map
    # (script.CONTROL) + the curated tooltips (opcode_meta.CONTROL). Essential to reading a scene.
    try:
        from rf4s_modkit import script as _script
        ctrl_map = _script.CONTROL
    except Exception:
        ctrl_map = {}
    if ctrl_map:
        lines.append("## Control opcodes (flow backbone)")
        lines.append("")
        lines.append("These are the VM's control-flow tokens (opcode >= `0xFFF0`), handled inline by "
                     "`Script_VMStep` rather than via the action-dispatch table. They structure every "
                     "scene: dialogue, branches, choices, calls, and the scene end.")
        lines.append("")
        for opv in sorted(ctrl_map, reverse=True):        # 0xFFFF down to 0xFFF1
            mn = ctrl_map[opv]
            meta = om.CONTROL.get(mn)
            if not meta:
                continue
            lines.append(f"### `0x{opv:04X}` — {mn}")
            lines.append("")
            lines.append(meta[1])
            lines.append("")

    # expression-operand grammar: action-op args + control guards are little RPN expressions -- the
    # last piece for reading a disassembly (what `reg0` / `var:0xNN` / `(a += 1)` mean). Operators
    # come straight from the decoder's tables (script._EXPR_BINOP / _EXPR_ASSIGN).
    try:
        _bo = " ".join("`%s`" % o for o in _script._EXPR_BINOP.values())
        _as = " ".join("`%s`" % o for o in _script._EXPR_ASSIGN.values())
    except Exception:
        _bo = None
    if _bo:
        lines.append("## Expression operands (argument encoding)")
        lines.append("")
        lines.append("Action-op arguments and control-op guard/value expressions are not raw "
                     "integers -- each is a little postfix (RPN) expression evaluated by "
                     "`Script_EvalExpressionBytecode`. Most resolve to a single literal, but they can "
                     "be variables, VM registers, or arithmetic. Leaf operands:")
        lines.append("")
        lines.append("- **int literal** — a constant (u8 / s8 / u16 / s16 / int32).")
        lines.append("- **`FLG_`/`REG_` name** (e.g. `REG_WIFE_ID`) — a packed game-flag / register "
                     "reference (an emdeb.bin variable); shown as `var:0xNN` when the name table is "
                     "unavailable.")
        lines.append("- **`reg0`..`reg9`** — the VM's scratch registers. A query op writes its result "
                     "to `reg0` (the ctx result slot); a following op / branch reads it.")
        lines.append("- **`arr[0xNN]`** — a scene var-array load; **`self`**, **`null`**, **`0`** — "
                     "fixed leaves.")
        lines.append("- **`actor(Name)`** / **`map(MAP_NAME)`** (raw form **`localvar[N]`** / "
                     "**`globalvar[N]`**) — typed CONSTANTS, not variables: the handler receives the "
                     "number N (`Script_PrepActionArgs` never dereferences them). The listing names "
                     "them only where the argument slot is known — a character id in actor slots, a "
                     "map id in the schedule ops — and keeps `localvar[N]`/`globalvar[N]` elsewhere.")
        lines.append("")
        lines.append(f"Operators build parenthesised infix — binary {_bo}; unary negate and "
                     f"logical-not; and the compound-assign forms {_as} (which write the result back "
                     "into the target variable, e.g. `REG_X += 1`).")
        lines.append("")

    # Event Manager (em.bin / EMF) opcodes: scenes BRIDGE to em.bin entries (via the CondScript/EMF
    # bridge ops 371-374 + 444) for their "plays when" conditions and flag/variable effects. Those
    # entries are their OWN little bytecode -- a system SEPARATE from the rf3.mc VM above, fully
    # reversed in rf4s_modkit/emscript.py. Documenting it here makes this a complete reference for the
    # whole cutscene system: the editor's Event Manager decodes + edits exactly these opcodes.
    try:
        from rf4s_modkit import emscript as _ems
        _cmp, _act = _ems.CMP_NAMES, _ems.ACTION_NAMES
    except Exception:
        _cmp = None
    if _cmp:
        lines.append("## Event Manager (em.bin) opcodes")
        lines.append("")
        try:
            from rf4s_modkit import script as _scr
            _bridge_ops = sorted(_scr.EMF_ENTRY_OPS)
        except Exception:
            _bridge_ops = [371, 372, 373, 374, 444]
        _bridge_txt = ", ".join("`%s` (%d)" % (om.mnemonic(o) or ("op%d" % o), o)
                                for o in _bridge_ops)
        lines.append("Scenes bridge to **em.bin** Event-Manager entries via the bridge action "
                     "opcodes " + _bridge_txt + " (each listed in the opcode index) — the "
                     "`EvalCondScript*` pair test an entry's conditions, the `*DispatchCondScript*` "
                     "/ `*DispatchAltAction` pair run its main / alt action stream, and "
                     "`SetFlagBitIfCond` sets a flag when an entry's condition holds — for their "
                     "*plays-when* conditions and their flag / variable effects. Each entry is its "
                     "own little bytecode — a system SEPARATE from the rf3.mc VM above — decoded by "
                     "`rf4s_modkit/emscript.py` and shown/edited in the toolkit's Event Manager. "
                     "Names come from the debug `emdeb.bin` (shipped alongside em.bin).")
        lines.append("")
        lines.append("**Condition expression opcodes** — `op = byte & 0x7F`; the high bit means "
                     "\"OR with the next expr\", so consecutive high-bit exprs form an OR-group and "
                     "the groups AND together (`CondScript_EvalEntry`, RF4S.exe+0x23BDB0):")
        lines.append("")
        lines.append("- `0` **TRUE**, `1` **FALSE** — constant guards.")
        lines.append("- `2`/`3` **CondA**(id) and `4`/`5` **NOT CondA** — test named condition A "
                     "(entry id as u16 / u32).")
        lines.append("- `6`/`7` **CondB** and `8`/`9` **NOT CondB** — test named condition B.")
        _cmpdesc = {"==": "equal", "!=": "not-equal", ">": "greater", ">=": "greater-or-equal"}
        lines.append("- comparison of two operands: "
                     + ", ".join("`0x%02X` %s (%s)" % (k, v, _cmpdesc.get(v, ""))
                                 for k, v in sorted(_cmp.items()))
                     + " — signed when either operand is a signed literal or signed flag ref.")
        lines.append("")
        lines.append("**Comparison operand types** — `type1 = (op>>2)&3`, `type2 = op&3` "
                     "(`CondScript_ReadComparisonOperands`, RF4S.exe+0x23C1A0):")
        lines.append("")
        lines.append("- `0` u32 literal · `1` signed u32 literal · `2` **query id** (a "
                     "`Script_QueryGameState` id — a live game-state read, shown by its `emdeb.bin` "
                     "query name) · `3` **flag ref** (an `emdeb.bin` `FLG_`/`REG_` variable: packed "
                     "sign / size / width + bit-offset). Query ids and flag refs both resolve to "
                     "their debug names in the editor.")
        lines.append("")
        lines.append("**Action opcodes** — high nibble selects the op; the byte's low bits describe "
                     "the operand (target mode `(b>>2)&3`, value type `b&3` = same encoding as a "
                     "comparison operand; result is `target OP value`, target-first — no reverse-sub, "
                     "unlike the rf3.mc expression VM) (`EMF_DispatchActionOpcode`, RF4S.exe+0x23C390):")
        lines.append("")
        _actdesc = {
            "CALL": "invoke another em entry (main stream → its MAIN block, alt stream → its ALT; "
                    "`0x00` = u16 entry id, `0x10` = u32)",
            "SET": "target = value", "ADD": "target += value", "SUB": "target -= value",
            "MUL_S": "target *= value (signed)", "MUL_U": "target *= value (unsigned)",
            "DIV_S": "target /= value (signed)", "DIV_U": "target /= value (unsigned)",
            "MOD_S": "target %= value (signed)", "MOD_U": "target %= value (unsigned)",
            "MAX_S": "target = max(target, value) (signed)", "MAX_U": "target = max (unsigned)",
            "MIN_S": "target = min(target, value) (signed)", "MIN_U": "target = min (unsigned)",
            "SET_EQ_ZERO": "target = (value == 0)"}
        _call_done = False
        for nib in sorted(_act):
            nm = _act[nib]
            if nm == "CALL":
                if _call_done:
                    continue
                _call_done = True
                lines.append("- `0x00`/`0x10` **CALL** — %s." % _actdesc["CALL"])
            else:
                lines.append("- `0x%02X` **%s** — %s." % (nib, nm, _actdesc.get(nm, "")))
        lines.append("")

    if placeholder_ops:
        lines.append("## Reserved / unused slots")
        lines.append("")
        lines.append("These dispatch-table slots carry no author-facing opcode (reserved, "
                     "removed in the PC port, or table padding):")
        lines.append("")
        lines.append(", ".join(str(o) for o in placeholder_ops))
        lines.append("")

    # numeric index: by-number lookup (complements the by-category sections). Disassemblies show op
    # NUMBERS, so this is the natural way to look one up; the sorted layout also reveals the handler
    # table's subsystem ranges. 3 named ops per row for compactness.
    named_ops = sorted(o for ops in by_cat.values() for o in ops)
    if named_ops:
        lines.append("## Opcode index (by number)")
        lines.append("")
        lines.append("Every named action opcode by number (reserved slots omitted; see above).")
        lines.append("")
        lines.append("| op | mnemonic | op | mnemonic | op | mnemonic |")
        lines.append("|---:|:--|---:|:--|---:|:--|")
        for i in range(0, len(named_ops), 3):
            cells = []
            for o in named_ops[i:i + 3]:
                cells.append(f"{o} | `{om.mnemonic(o)}`")
            while len(cells) < 3:
                cells.append(" | ")
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


def _first_op(ops):
    return ops[0]


def _anchor(cat):
    # GitHub-style anchor from the category label
    lbl = om.CATEGORIES.get(cat, cat) if hasattr(om, "CATEGORIES") else cat
    return "".join(ch for ch in lbl.lower().replace(" ", "-") if ch.isalnum() or ch == "-")


def build_csv():
    """Return the flat opcode list as CSV text: op_dec, op_hex, mnemonic, handler, category,
    prototype, description -- every action opcode 0..762 plus the control opcodes. `handler` is
    the IDA/RE ground-truth symbol (the dispatch handler for an action op; `Script_VMStep` for the
    inline control ops), so the list is a complete cross-reference back to the binary. A machine-
    readable (spreadsheet / grep) companion to CUTSCENE_OPCODES.md, built from the same opcode_meta
    source so the two never drift. `lineterminator='\\n'` keeps it deterministic for the sync guard."""
    import csv
    import io
    from rf4s_modkit import script as _script
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["op_dec", "op_hex", "mnemonic", "handler", "category", "prototype", "description"])
    for op in range(N_OPS):
        desc = (om.describe(op) or "").replace("\n", " ").strip()
        w.writerow([op, "0x%03X" % op, om.mnemonic(op) or "", om.technical(op) or "",
                    om.category(op) or "", om.prototype(op) or "", desc])
    for opv in sorted(_script.CONTROL, reverse=True):        # control opcodes 0xFFFF..0xFFF1
        mn = _script.CONTROL[opv]
        meta = om.CONTROL.get(mn)
        if not meta:
            continue
        cat, desc = meta
        w.writerow([opv, "0x%04X" % opv, mn, "Script_VMStep", cat, mn + "()",
                    desc.replace("\n", " ").strip()])
    return buf.getvalue()


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    text = build()
    out = os.path.join(here, "CUTSCENE_OPCODES.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {out} ({len(text)} bytes, {text.count(chr(10))} lines)")
    csv_text = build_csv()
    csv_out = os.path.join(here, "opcodes_list.csv")
    with open(csv_out, "w", encoding="utf-8") as f:
        f.write(csv_text)
    print(f"wrote {csv_out} ({csv_text.count(chr(10))} rows)")


if __name__ == "__main__":
    main()
