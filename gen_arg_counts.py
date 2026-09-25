"""Regenerate refdata/script_arg_counts.json: for every action opcode the shipped rf3.mc
uses, the fewest and most arguments any of its statements pass.

The script VM hands a handler whatever argument count the statement carries; a handler that
reads an argument the statement does not have gets stack garbage instead (op 93
SetDialogueBoxStyle with no argument shows a random box style -- usually no box at all). The
assembler and the cutscene editor's Save refuse counts outside the shipped range.

Run it on an UNMODIFIED rf3.mc (the game's own, or the copy the cutscene editor keeps in
<game>/ModdingBackup):

    python gen_arg_counts.py [path/to/rf3.mc]
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

from rf4s_modkit import gamepaths, script
from rf4s_modkit.refdata import refdata_path

OUT = refdata_path("script_arg_counts.json")


def default_source() -> pathlib.Path | None:
    b = gamepaths.find_bundle_dir()
    if b is None:
        return None
    backup = b.parent / "ModdingBackup" / "Bundle" / "bundlePatch1" / "rf3.mc"
    if backup.is_file():                          # the original, before the editor saved over it
        return backup
    p = b / "bundlePatch1" / "rf3.mc"
    return p if p.is_file() else None


def counts(container) -> dict[int, tuple[int, int]]:
    seen, per_op = set(), collections.defaultdict(set)
    for bank in container.banks:
        for sc in script.disassemble_bank(bank):
            for pc, st in sc.stmts.items():
                if st.op < 0xFFF0 and (id(bank), pc) not in seen:
                    seen.add((id(bank), pc))
                    per_op[st.op].add(len(st.args))
    return {op: (min(n), max(n)) for op, n in sorted(per_op.items())}


def main(argv) -> int:
    src = pathlib.Path(argv[1]) if len(argv) > 1 else default_source()
    if src is None or not src.is_file():
        print("no rf3.mc found -- pass the path of an unmodified one")
        return 1
    c = script.Container.load(src)
    ranges = counts(c)
    about = ("fewest / most arguments each action opcode passes in the shipped rf3.mc "
             "(gen_arg_counts.py); ops missing here are not used by the game")
    rows = ",\n".join('  "%d": [%d, %d]' % (op, lo, hi) for op, (lo, hi) in ranges.items())
    OUT.write_text('{\n "about": %s,\n "ops": {\n%s\n }\n}\n' % (json.dumps(about), rows),
                   encoding="utf-8")
    print("wrote %s (%d opcodes, from %s)" % (OUT, len(ranges), src))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
