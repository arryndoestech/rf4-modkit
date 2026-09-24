#!/usr/bin/env python3
"""Render rf3.mc cutscene banks into a Ghidra "listing plan" JSON.

The plan is applied inside Ghidra by ApplyRF4Cutscenes.py (a Jython script in this
folder): rf3.mc is imported as a RAW binary (language DATA:LE:64, no analysis) and the
script turns the plan into labels, plate/EOL comments, and real memory REFERENCES —
so Ghidra's own XREF pane, jump-to-reference, and search work on cutscene bytecode
exactly like they do on machine code.

Usage (from tools/modding):
    python ghidra/gen_ghidra_plan.py --banks 210,211            # specific banks
    python ghidra/gen_ghidra_plan.py --banks 200-260            # a range
    python ghidra/gen_ghidra_plan.py --all                      # every bank (big!)
    python ghidra/gen_ghidra_plan.py --banks 210 --out my.json
Options:
    --mc PATH       rf3.mc (default: the bundlePatch1 copy the toolkit finds)
    --locale eng    dialogue locale to inline into DIALOG comments (rf3mc.<locale>)

A full-corpus plan is ~hundreds of MB and takes Ghidra a while to apply; start with
the banks you are actually reading (the request box lives in bank 210).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from rf4s_modkit import script                       # noqa: E402
from rf4s_modkit.textdb import TextArchive           # noqa: E402

DEFAULT_MC = r"C:/Users/arryn/Documents/Bundle/bundlePatch1/rf3.mc"

# control-flow reference kinds for Ghidra (applied as RefType by the apply script)
_REFKIND = {"CALL": "call", "JMP": "jump"}

# instruction-visible length per statement for the RF4MC language: the part the
# SLEIGH constructors model. Anything beyond it (big arg blocks, switch/choice
# tables) is typed as word data by the apply script so disassembly never walks in.
_MAX_INLINE_ARGS = 16
_CTRL_ILEN = {0xFFFF: 2, 0xFFF1: 4, 0xFFFE: 4, 0xFFFA: 4, 0xFFFB: 4, 0xFFFD: 4,
              0xFFFC: 6, 0xFFF8: 6, 0xFFF9: 6, 0xFFF7: 6, 0xFFF6: 6,
              0xFFF5: 4, 0xFFF4: 4, 0xFFF3: 4, 0xFFF2: 4}


def _inst_len(st):
    if st.op < 0xFFF0:
        argc = (st.size - 4) // 2
        return st.size if argc <= _MAX_INLINE_ARGS else 4
    return _CTRL_ILEN.get(st.op, st.size)


def _find_text(locale):
    for cand in (pathlib.Path(DEFAULT_MC).parent / ("rf3mc.%s" % locale),
                 HERE.parent.parent / ("rf3mc.%s" % locale)):
        if cand.is_file():
            return TextArchive.load(str(cand))
    return None


def _stmt_text(bank, st, dlg):
    if st.mnem == "DIALOG":
        txt = ""
        if dlg is not None:
            try:
                s = dlg.text(st.dialog_id)
                if s:
                    txt = '  "%s"' % s.replace("\n", " / ")[:90]
            except Exception:
                pass
        return "DIALOG #%d%s" % (st.dialog_id, txt)
    if st.op < 0xFFF0:
        args = [script.arg_repr(bank.data, a) for a in st.args]
        special = script.render_action(st.op, args)
        return special if special else "%s(%s)" % (script.opcode_mnemonic(st.op), ", ".join(args))
    extra = " %d" % st.items[0] if st.mnem == "FRAME" and st.items else ""
    return st.mnem + extra


def build_bank_plan(pos, bank, dlg):
    scenes = script.disassemble_bank(bank, discover=True)
    stmts = {}                       # pc -> (size, text, [(target, kind)])
    labels = {}
    scene_rows = []
    for sc in scenes:                # scene-entry labels first, so a CALL to a scene
        styp = ("t%02d" % sc.action_type) if sc.action_type >= 0 else "disc"
        labels.setdefault(sc.entry_pc, "scene_b%04d_%s_%04x" % (pos, styp, sc.entry_pc))
    for sc in scenes:                # typed scenes first: they win the attribution
        scene_rows.append({"entry": sc.entry_pc, "type": sc.action_type,
                           "stmts": len(sc.stmts), "ok": bool(sc.ok)})
        for pc, st in sc.stmts.items():
            if pc in stmts:
                continue
            refs = [[t, _REFKIND.get(st.mnem, "branch")]
                    for t in st.code_targets if t is not None]
            stmts[pc] = (st.size, _stmt_text(bank, st, dlg), refs, _inst_len(st))
            for t in st.code_targets:
                if t is not None:
                    labels.setdefault(t, "loc_b%04d_%04x" % (pos, t))
    # second pass: control ops name their targets in the comment text, so the listing
    # reads "CALL -> scene_b0210_disc_17ce" even before Ghidra resolves the reference
    for pc, (size, text, refs, ilen) in stmts.items():
        if refs and text and "(" not in text and "#" not in text:
            names = ", ".join(labels.get(t, "0x%04x" % t) for t, _k in refs[:6])
            if len(refs) > 6:
                names += ", …(%d)" % len(refs)
            stmts[pc] = (size, "%s -> %s" % (text, names), refs, ilen)
    return {
        "pos": pos, "kind": bank.kind, "index": bank.index,
        "file_off": bank.file_off, "size": len(bank.data),
        "label": "BANK_%04d_%s" % (pos, bank.kind.upper()),
        "scenes": scene_rows,
        "labels": {str(k): v for k, v in labels.items()},
        "stmts": [[pc, s[0], s[1], s[2], s[3]] for pc, s in sorted(stmts.items())],
    }


def parse_banks(spec, nbanks):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return [b for b in out if 0 <= b < nbanks]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mc", default=DEFAULT_MC)
    ap.add_argument("--banks", help="bank positions, e.g. 210,211 or 200-260")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--locale", default="eng")
    ap.add_argument("--out", default=str(HERE / "rf4_cutscene_plan.json"))
    a = ap.parse_args()

    c = script.Container.load(a.mc)
    dlg = _find_text(a.locale)
    if a.all:
        banks = list(range(len(c.banks)))
    elif a.banks:
        banks = parse_banks(a.banks, len(c.banks))
    else:
        ap.error("pass --banks N[,M|A-B] or --all")
    plan = {"source": str(pathlib.Path(a.mc).resolve()),
            "locale": a.locale if dlg is not None else None,
            "banks": [build_bank_plan(p, c.banks[p], dlg) for p in banks]}
    out = pathlib.Path(a.out)
    out.write_text(json.dumps(plan), encoding="utf-8")
    ns = sum(len(b["stmts"]) for b in plan["banks"])
    print("wrote %s  (%d bank(s), %d statements, %d labels)"
          % (out, len(plan["banks"]), ns,
             sum(len(b["labels"]) for b in plan["banks"])))


if __name__ == "__main__":
    main()
