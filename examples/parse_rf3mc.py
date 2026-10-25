"""Minimal stand-alone rf3.mc reader (no toolkit imports): banks, scene triggers, statements.

    python parse_rf3mc.py path/to/rf3.mc [container bank number]

The toolkit's rf4s_modkit/script.py does all of this and more (names, listings, editing);
this file is the format in ~150 lines for anyone writing their own tool.
"""
import struct
import sys

CONTROL = {0xFFFF: "RET", 0xFFFE: "CALL", 0xFFFD: "RET_NZ", 0xFFFC: "DIALOG", 0xFFFB: "EVAL",
           0xFFFA: "JMP", 0xFFF9: "BR_NZ", 0xFFF8: "BR_Z", 0xFFF7: "SWITCH",
           0xFFF6: "SWITCH_CLAMP", 0xFFF5: "PROMPT_CHOICE_FORCED", 0xFFF4: "PROMPT_CHOICE",
           0xFFF3: "JMP_RAND", 0xFFF2: "JMP_WEIGHTED", 0xFFF1: "FRAME"}


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def read_container(data):
    """[(kind, index, bank bytes)]: primary 0..247, tail 0..871 (index = map id), global."""
    assert data[:4] == b"MYCF" and u32(data, 4) == 0 and u32(data, 8) == 0x10001
    g_off, g_size, n1, t1, n2, t2 = (u32(data, 12 + 4 * i) for i in range(6))
    banks = []
    for kind, n, table in (("primary", n1, t1), ("tail", n2, t2)):
        for i in range(n):
            off, size = u32(data, table + 8 * i), u32(data, table + 8 * i + 4)
            banks.append((kind, i, data[off:off + size]))
    banks.append(("global", 0, data[g_off:g_off + g_size]))
    return banks


def triggers(bank, slots=74):
    """{type: [(scene pc, [(tag, key), ...])]} from the bank's type table."""
    out = {}
    for t in range(slots):
        count, lst = u16(bank, 4 * t), u16(bank, 4 * t + 2)
        o, recs = lst, []
        for _ in range(count):
            n, pc = u16(bank, o), u16(bank, o + 2)
            keys = [(bank[o + 4 + 5 * k], struct.unpack_from("<i", bank, o + 5 + 5 * k)[0])
                    for k in range(n)]
            recs.append((pc, keys))
            o += 4 + 5 * n
        if recs:
            out[t] = recs
    return out


def statement(b, pc):
    """(name, size, targets, operand offsets, extra) of the statement at pc."""
    op = u16(b, pc)
    if op < 0xFFF0:                                     # action: [op][argc][argc expr offsets]
        argc = u16(b, pc + 2)
        return "op%d" % op, 4 + 2 * argc, [], [u16(b, pc + 4 + 2 * i) for i in range(argc)], None
    name = CONTROL[op]
    if name == "RET":
        return name, 2, [], [], None
    if name in ("CALL", "JMP"):
        return name, 4, [u16(b, pc + 2)], [], None
    if name == "FRAME":
        return name, 4, [], [], u16(b, pc + 2)          # stack words reserved
    if name in ("RET_NZ", "EVAL"):
        return name, 4, [], [u16(b, pc + 2)], None
    if name == "DIALOG":
        return name, 6, [], [], u32(b, pc + 2)          # rf3mc.<locale> line id
    if name in ("BR_Z", "BR_NZ"):
        return name, 6, [u16(b, pc + 4)], [u16(b, pc + 2)], None
    if name in ("SWITCH", "SWITCH_CLAMP"):              # [op][expr][n][n targets]
        n = u16(b, pc + 4)
        return name, 2 * (n + 3), [u16(b, pc + 6 + 2 * i) for i in range(n)], [u16(b, pc + 2)], None
    if name == "JMP_RAND":                              # [op][n][n targets]
        n = u16(b, pc + 2)
        return name, 4 + 2 * n, [u16(b, pc + 4 + 2 * i) for i in range(n)], [], None
    if name == "JMP_WEIGHTED":                          # [op][n][n targets][n weight exprs]
        n = u16(b, pc + 2)
        return (name, 4 + 4 * n, [u16(b, pc + 4 + 2 * i) for i in range(n)],
                [u16(b, pc + 4 + 2 * n + 2 * i) for i in range(n)], None)
    n = u16(b, pc + 2)                                  # menus: [op][n][targets][n u32 line ids]
    nt = n + 1 if name == "PROMPT_CHOICE" else n        # PROMPT_CHOICE: target 0 = cancel
    items = [u32(b, pc + 4 + 2 * nt + 4 * i) for i in range(n)]
    return name, 4 + 2 * nt + 4 * n, [u16(b, pc + 4 + 2 * i) for i in range(nt)], [], items


ENDS = ("RET", "JMP", "SWITCH_CLAMP", "JMP_RAND", "JMP_WEIGHTED",
        "PROMPT_CHOICE", "PROMPT_CHOICE_FORCED")


def walk(b, entry):
    """Every statement reachable from a scene's entry pc: {pc: statement(...)}."""
    seen, todo = {}, [entry]
    while todo:
        pc = todo.pop()
        while pc not in seen and pc + 2 <= len(b):
            st = seen[pc] = statement(b, pc)
            todo += st[2]                               # every branch / call target
            if st[0] in ENDS:
                break
            pc += st[1]
    return seen


def expr(b, off):
    """One operand expression as a list of tokens (stops at the 00 terminator)."""
    out = []
    while True:
        t = b[off]
        if t in (0x03, 0x04, 0x05, 0x11, 0x12, 0x13) and not out:   # single leaf, no RPN
            v = {0x05: u16(b, off + 1) if t == 0x05 else None}.get(t)
            return [("tag%d" % t, u32(b, off + 1) if t in (3, 4) else v)]
        if t == 0x00:
            return out
        if t in (0x14, 0x15, 0x16):
            out.append(("int", {0x14: 0, 0x15: -1, 0x16: 1}[t])); off += 1
        elif t in (0x17, 0x18):
            out.append(("int", struct.unpack_from("<B" if t == 0x17 else "<b", b, off + 1)[0])); off += 2
        elif t in (0x19, 0x1A):
            out.append(("int", struct.unpack_from("<H" if t == 0x19 else "<h", b, off + 1)[0])); off += 3
        elif t == 0x01:
            out.append(("int", struct.unpack_from("<i", b, off + 1)[0])); off += 5
        elif t == 0x02:
            out.append(("var", u32(b, off + 1))); off += 5                  # packed game flag
        elif t == 0x06:
            out.append(("arr", u16(b, off + 1))); off += 3
        elif 0x07 <= t <= 0x10:
            out.append(("reg%d" % (t - 7), None)); off += 1
        elif t >= 0x80:
            out.append(("op", t - 0x80)); off += 1
        else:
            raise ValueError("unknown expression tag 0x%02x at 0x%x" % (t, off))


if __name__ == "__main__":
    data = open(sys.argv[1], "rb").read()
    banks = read_container(data)
    print(len(banks), "banks;", sum(len(r) for _k, _i, b in banks for r in triggers(b).values()),
          "triggers")
    kind, idx, b = banks[int(sys.argv[2]) if len(sys.argv) > 2 else 19]
    for t, recs in triggers(b).items():
        for pc, keys in recs[:1]:
            print("%s %d  type %d  scene @0x%04x  keys %s" % (kind, idx, t, pc, keys))
            for spc, (name, size, targets, ops, extra) in sorted(walk(b, pc).items())[:8]:
                args = [expr(b, o) for o in ops]
                print("    0x%04x  %-12s %s %s %s" % (spc, name, args or "",
                                                     targets and ["0x%04x" % x for x in targets] or "",
                                                     "" if extra is None else extra))
            break
