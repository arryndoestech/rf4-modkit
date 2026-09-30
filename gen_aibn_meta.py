#!/usr/bin/env python3
"""Regenerate refdata/aibn_meta.json (AIBN opcode + scripted-action metadata) from the
verified opcode record file docs/monster_ai_opcodes.json.

    python gen_aibn_meta.py <path/to/monster_ai_opcodes.json>
"""
import json, re, sys, os

_CUTS = (" (", ";", ":", ", ", " matched ", " compared ", " passed ", " stored ", " written ", " added to ", " read ")

def short(meaning, units=""):
    """Short operand label for annotations: the meaning up to the first qualifier."""
    cut = len(meaning)
    for c in _CUTS:
        i = meaning.find(c)
        if i > 0:
            cut = min(cut, i)
    label = meaning[:cut].strip()
    if label.startswith("index into g_npcScriptedActionTable"):
        return "scripted action slot"
    if label.startswith("read but not used"):
        return "unused"
    if label[:1].isdigit() or label.startswith("0 "):      # "0 = clear, nonzero = set ..." style meanings
        return "flag" if units == "flag" else "value"
    return label[:36]

_STALE = (" (chapter name misleading)", " (chapter/IDB name misleading)", " (IDB comment wrong)", " (IDB name misleading)")

def clean(text):
    for t in _STALE:
        text = text.replace(t, "")
    return text

def main(src_path):
    src = json.load(open(src_path, encoding="utf-8"))
    ops, sas = {}, {}
    for r in src:
        rec = {"ida_name": r["name"], "rva": r["rva"], "arity": r["arity"],
               "operands": [{"i": o["i"], "label": short(o["meaning"], o["units"]), "meaning": o["meaning"], "units": o["units"]}
                            for o in r.get("operands", [])],
               "effect": clean(r["effect"]), "status": r["status"]}
        if "census_uses" in r:
            rec["uses"] = r["census_uses"]
        if "value_ranges" in r:
            rec["value_ranges"] = r["value_ranges"]
        if r["op"].startswith("sa"):
            users = r.get("census_files", [])
            rec["users"] = users if isinstance(users, list) else []
            if isinstance(users, int):
                rec["user_count"] = users
            sas[str(r["slot"])] = rec
        else:
            a, b = r["op"].split("-") if "-" in r["op"] else (r["op"], r["op"])
            for op in range(int(a, 16), int(b, 16) + 1):
                ops["0x%02X" % op] = rec
    ops["0x93"] = {"ida_name": "(OR connector token, consumed by MonsterScript_StepCommandList)", "rva": "0x1CA1B0",
                   "arity": 0, "operands": [], "status": "verified",
                   "effect": "OR connector between two conditions: when the condition before it is true the runner jumps straight to the next action opcode (MonsterScript_FindNextActionOp, id < 0x5D); when false the next condition is evaluated."}
    ops["0x94"] = {"ida_name": "(AND connector token, consumed by MonsterScript_StepCommandList)", "rva": "0x1CA1B0",
                   "arity": 0, "operands": [], "status": "verified",
                   "effect": "AND connector between two conditions: when the condition before it is true the next condition is evaluated; when false MonsterScript_SkipConditionalBlock leaves the block (else-pending bit 0x20000000 set)."}
    out = {"_source": "verified 2026-09-17 from the RF4S.exe IDB handlers; regenerate with gen_aibn_meta.py",
           "opcodes": ops, "scripted_actions": sas}
    dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "refdata", "aibn_meta.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", dst, len(ops), "opcodes,", len(sas), "scripted actions")

if __name__ == "__main__":
    main(sys.argv[1])
