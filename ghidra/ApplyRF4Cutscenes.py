# Apply an RF4 cutscene "listing plan" to an imported rf3.mc.
# @author rf4s toolkit
# @category RF4
#
# WORKFLOW
#   1. Import rf3.mc into your Ghidra project as a RAW binary:
#        File > Import File... > rf3.mc
#        Format: Raw Binary, Language: DATA:LE:64:default, base address 0x0.
#        Say NO to auto-analysis (there is nothing x86 in it).
#   2. Generate a plan on the CPython side (from tools/modding):
#        python ghidra/gen_ghidra_plan.py --banks 210,211
#   3. Open the imported rf3.mc program, run this script from the Script Manager,
#      and pick the plan JSON when prompted.
#
# WHAT YOU GET
#   * a label at every bank, scene entry and branch target
#   * a PLATE comment at each scene entry (type, size, decode status)
#   * an EOL comment on every statement: the toolkit's friendly disassembly,
#     with English dialogue inlined on DIALOG lines
#   * real memory REFERENCES for every CALL / JMP / branch / choice target —
#     Ghidra's XREF pane, "References To", and jump-to-reference all work,
#     so "who calls this scene" is one keypress like in machine code.
#
# Re-running with a plan for other banks is additive. Jython 2.7 — keep py2 syntax.

import json

from ghidra.program.model.symbol import RefType, SourceType
from ghidra.program.model.listing import CodeUnit

PLAN_KINDS = {
    "call":   RefType.UNCONDITIONAL_CALL,
    "jump":   RefType.UNCONDITIONAL_JUMP,
    "branch": RefType.CONDITIONAL_JUMP,
}


def addr(off):
    return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(off)


def main():
    f = askFile("RF4 cutscene plan JSON (gen_ghidra_plan.py output)", "Apply")
    fh = open(f.getAbsolutePath(), "rb")
    try:
        plan = json.loads(fh.read().decode("utf-8"))
    finally:
        fh.close()

    st = currentProgram.getSymbolTable()
    listing = currentProgram.getListing()
    refmgr = currentProgram.getReferenceManager()
    mem_max = currentProgram.getMaxAddress().getOffset()

    total_stmts = 0
    total_refs = 0
    for bank in plan["banks"]:
        base = bank["file_off"]
        if base + bank["size"] - 1 > mem_max:
            println("bank %d lies outside the program (base 0x%x) - wrong import base? skipped"
                    % (bank["pos"], base))
            continue
        monitor.setMessage("bank %d (%d statements)" % (bank["pos"], len(bank["stmts"])))

        st.createLabel(addr(base), bank["label"], SourceType.USER_DEFINED)

        # labels first, so references immediately render with names
        for pc_s, name in bank["labels"].items():
            st.createLabel(addr(base + int(pc_s)), str(name), SourceType.USER_DEFINED)

        for sc in bank["scenes"]:
            a = addr(base + sc["entry"])
            typ = ("type %d" % sc["type"]) if sc["type"] >= 0 else "discovered"
            plate = ("RF4 cutscene scene  --  bank %d (%s), %s, %d statements%s"
                     % (bank["pos"], bank["kind"], typ, sc["stmts"],
                        "" if sc["ok"] else "  [PARTIAL DECODE]"))
            old = listing.getComment(CodeUnit.PLATE_COMMENT, a)
            if old is None or plate not in old:
                listing.setComment(a, CodeUnit.PLATE_COMMENT,
                                   plate if old is None else old + "\n" + plate)

        for row in bank["stmts"]:
            pc, size, text, refs = row[0], row[1], row[2], row[3]
            a = addr(base + pc)
            listing.setComment(a, CodeUnit.EOL_COMMENT, str(text))
            for tgt, kind in refs:
                refmgr.addMemoryReference(a, addr(base + tgt),
                                          PLAN_KINDS.get(kind, RefType.CONDITIONAL_JUMP),
                                          SourceType.USER_DEFINED, 0)
                total_refs += 1
            total_stmts += 1
            if monitor.isCancelled():
                println("cancelled")
                return

    println("applied: %d statements commented, %d references, %d bank(s)"
            % (total_stmts, total_refs, len(plan["banks"])))
    println("tip: navigate with 'G' to a scene label, XREF pane shows callers;")
    println("     select a loc_/scene_ label and press Ctrl+Shift+F for all references.")


main()
