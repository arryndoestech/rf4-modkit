"""rf4s_modkit/aibn_meta.py -- author-facing metadata for the AIBN monster/NPC behaviour-script opcodes.

A display layer over ``aibn.py``: per opcode the IDB handler name and RVA, the verified operand
count, a label / full meaning / unit per operand, a one-paragraph mechanical effect, and the
census usage count; plus the 35-entry scripted-action table reached through opcode 0x26.
Everything comes from ``refdata/aibn_meta.json`` (every handler read from RF4S.exe
pseudocode on 2026-09-17). Nothing here is guessed from the data files alone.

Units used by the operand records:
  units     world units (world_x >> 12; 8 units = one collision cell)
  frames    ticks (the VM runs monsters every other frame, NPCs every frame)
  deg       degrees; the handler multiplies by 181 (65536 = 360 deg)
  q16       raw u16 angle (16384 = 90 deg, 32768 = 180 deg, 49152 = -90 deg)
  Q12       20.12 fixed point (4096 = 1.0; HP fractions: 2048 = 50 %)
  percent   0..100 (IfRandomChance)
  cmp       comparator token (== <= >=)
  id / label / register / flag / count / shift / unused   as named
"""
from __future__ import annotations

import json

from .refdata import refdata_path

with open(refdata_path("aibn_meta.json"), encoding="utf-8") as _f:
    _DATA = json.load(_f)

OPCODES: dict[int, dict] = {int(k, 16): v for k, v in _DATA["opcodes"].items()}
SCRIPTED_ACTIONS: dict[int, dict] = {int(k): v for k, v in _DATA["scripted_actions"].items()}


def record(opid: int) -> dict | None:
    return OPCODES.get(opid)


def ida_name(opid: int) -> str:
    r = OPCODES.get(opid)
    return r["ida_name"] if r else f"slot_{opid:02X}"


def effect(opid: int) -> str:
    r = OPCODES.get(opid)
    return r["effect"] if r else ""


def operands(opid: int) -> list[dict]:
    r = OPCODES.get(opid)
    return r["operands"] if r else []


def first_sentence(text: str, limit: int = 160) -> str:
    s = text.split(". ")[0].strip()
    return s if len(s) <= limit else s[:limit - 1] + "…"


def format_value(units: str, value: int) -> str:
    """Render one operand value with its unit for annotations (raw value kept where it matters)."""
    if units == "q16":
        deg = ((value & 0xFFFF) * 360.0) / 65536.0
        if value == 0xFFFF:
            return "0xFFFF (random dir)"
        return f"{value} ({deg:.0f} deg)"
    if units == "deg":
        return f"{value} deg"
    if units == "Q12":
        from .nlcl import format_value
        return f"{value} ({format_value(value, 12)})"
    if units == "percent":
        return f"{value} %"
    if units in ("frames", "units", "count", "shift"):
        return f"{value} {units}"
    return str(value)


def annotate(opid: int, operand_values: list, rendered: list[str]) -> str:
    """Comment text for one disassembled statement: `label=value unit, ...` (+ scripted action name)."""
    r = OPCODES.get(opid)
    if not r:
        return ""
    parts = []
    for o in r["operands"]:
        i = o["i"]
        if i >= len(rendered):
            break
        val = operand_values[i]
        units = o["units"]
        if units == "cmp" or not isinstance(val, int):
            continue
        parts.append(f"{o['label']} = {format_value(units, val)}")
    if opid == 0x26 and operand_values and isinstance(operand_values[0], int):
        sa = SCRIPTED_ACTIONS.get(operand_values[0])
        if sa:
            parts.append(f"sa{operand_values[0]} {sa['ida_name']}: {first_sentence(sa['effect'], 90)}")
    return " | ".join(parts)


def describe(opid: int) -> str:
    """Multi-line reference text for one opcode."""
    r = OPCODES.get(opid)
    if not r:
        return f"0x{opid:02X}: no metadata"
    lines = [f"0x{opid:02X} {r['ida_name']} (RF4S.exe+{r['rva']})  arity {r['arity']}  [{r['status']}]"
             + (f"  uses {r['uses']}" if "uses" in r else "")]
    for o in r["operands"]:
        lines.append(f"  op{o['i']}: {o['meaning']} [{o['units']}]")
    lines.append("  " + r["effect"])
    if "value_ranges" in r:
        lines.append("  shipped values: " + json.dumps(r["value_ranges"], ensure_ascii=False)[:200])
    return "\n".join(lines)


def describe_action(slot: int) -> str:
    sa = SCRIPTED_ACTIONS.get(slot)
    if not sa:
        return f"scripted action {slot}: no metadata"
    users = sa.get("users") or []
    users_txt = ", ".join(users[:6]) if users else (f"{sa['user_count']} files" if sa.get("user_count") else "")
    return (f"sa{slot} {sa['ida_name']} (RF4S.exe+{sa['rva']}) [{sa['status']}]\n  {sa['effect']}"
            + (f"\n  users: {users_txt}" if users_txt else ""))
