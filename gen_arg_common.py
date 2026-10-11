"""Regenerate refdata/script_arg_common.json: for every action opcode the shipped rf3.mc
uses, the constant values each argument takes most often, with how many statements pass
them.

The cutscene editor's instruction form starts each argument at the game's most common
value (WalkActorTo speed 100, FadeScreen to black over 6000 = 1 s, ...) instead of 0, and
offers the other common values in the argument's list.

Run it on an UNMODIFIED rf3.mc (the game's own, or the copy the cutscene editor keeps in
<game>/ModdingBackup):

    python gen_arg_common.py [path/to/rf3.mc]
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

from rf4s_modkit import script
from rf4s_modkit.refdata import refdata_path

from gen_arg_counts import default_source

OUT = refdata_path("script_arg_common.json")
TOP = 8                 # values kept per argument


def common(container) -> dict[int, list[list[list[int]]]]:
    """{op: [[[value, uses], ...] per argument]} -- constants only (an expression, a
    register or a variable is not a value the form can offer)."""
    seen = set()
    per = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for bank in container.banks:
        for sc in script.disassemble_bank(bank):
            for pc, st in sc.stmts.items():
                if st.op >= 0xFFF0 or (id(bank), pc) in seen:
                    continue
                seen.add((id(bank), pc))
                for i, off in enumerate(st.args):
                    v, ok = script.arg_constant(bank.data, off)
                    if ok and v is not None:
                        per[st.op][i][v] += 1
    out = {}
    for op in sorted(per):
        n = max(per[op]) + 1
        out[op] = [[[v, c] for v, c in sorted(per[op][i].items(), key=lambda kv: (-kv[1], kv[0]))[:TOP]]
                   for i in range(n)]
    return out


def main(argv) -> int:
    src = pathlib.Path(argv[1]) if len(argv) > 1 else default_source()
    if src is None or not src.is_file():
        print("no rf3.mc found -- pass the path of an unmodified one")
        return 1
    c = script.Container.load(src)
    table = common(c)
    about = ("the constant values each action argument takes most often in the shipped "
             "rf3.mc, as [value, statements] (gen_arg_common.py); ops missing here are not "
             "used by the game")
    rows = ",\n".join('  "%d": %s' % (op, json.dumps(args, separators=(",", ":")))
                      for op, args in table.items())
    OUT.write_text('{\n "about": %s,\n "ops": {\n%s\n }\n}\n' % (json.dumps(about), rows),
                   encoding="utf-8")
    print("wrote %s (%d opcodes, from %s)" % (OUT, len(table), src))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
