"""
bankrelink.py -- rebuild an rf3.mc bank from a parsed model, recomputing every address.

The editor's inserts append new code and trampoline into it; this module is the other
way: parse the whole bank into a model, let edits change the model, and lay the bank out
again from scratch, so every code address and expression offset is recomputed.

Bank layout (all 1121 shipped banks):

    type table   table_slots x {u16 count; u16 list_offset}       (74 slots = 296 B)
    code         statements back to back, even-sized, starting right after the table
    entry lists  per type, {u16 size; u16 event_pc; size x {u8 tag; i32 key}}
    pool         one expression per operand, in the order the code references them;
                 no sharing and no dedup. A single-leaf operand (tags 3/4/5/0x11-0x13)
                 is followed by a 00 byte the engine never reads -- kept for byte-exactness.

Every code address in a bank lives in one of these fields (checked against RF4S.exe):

  * control-flow targets: CALL/JMP, BR_Z/BR_NZ, SWITCH_EQ/GE, JMP_IND, RAND_BR,
    PROMPT_CHOICE(_FORCED) (Script_VMStep, RF4S.exe+0x23EF60);
  * the type table's list offsets and each entry's event_pc (Npc_FindNextActionEntryOfType,
    RF4S.exe+0x23DE30; the pc is copied into the VM's pc field when the scene starts).
Action arguments are always expression offsets: no action takes a code address (op 4 is
a wait, Script_VMOp_WaitPlain RF4S.exe+0x1FABC0). Entry keys are values, not pcs: type 15's
"previous event" keys are decimal event ids (100..3900), not addresses. Nothing outside
the bank points into it (the header's pair at byte 12 is just the global bank).

Code nobody reaches (a RET after a RET, a JMP after a JMP, one orphaned choice body in
tail bank 188 whose opcode word was overwritten by a RET) is kept in place: dead statements are
relinked like live ones, and bytes that do not decode are carried verbatim.
"""
from __future__ import annotations

import struct

from . import script

LEAF_TAGS = (3, 4, 5, 0x11, 0x12, 0x13)          # = scriptasm.LEAF_TAGS


class RelinkError(script.ScriptError):
    pass


def expr_size(buf, off):
    """Bytes an operand occupies in the pool, including the unread 00 after a leaf."""
    _t, ln = script.disasm_expr(buf, off)
    if ln <= 0:
        raise RelinkError("bad expression at 0x%04x" % off)
    if buf[off] in LEAF_TAGS and off + ln < len(buf) and buf[off + ln] == 0:
        ln += 1
    return ln


def fields(st):
    """[(byte offset in the statement, 'pc' | 'expr')] for every u16 address field."""
    op, n = st.op, None
    if op < 0xFFF0:
        return [(4 + 2 * i, "expr") for i in range(len(st.args))]
    if op in (0xFFFE, 0xFFFA):
        return [(2, "pc")]
    if op in (0xFFFD, 0xFFFB):
        return [(2, "expr")]
    if op in (0xFFF8, 0xFFF9):
        return [(2, "expr"), (4, "pc")]
    if op in (0xFFF6, 0xFFF7):
        return [(2, "expr")] + [(6 + 2 * k, "pc") for k in range(len(st.code_targets))]
    if op == 0xFFF3:
        return [(4 + 2 * k, "pc") for k in range(len(st.code_targets))]
    if op == 0xFFF2:
        n = len(st.code_targets)
        return [(4 + 2 * k, "pc") for k in range(n)] + [(4 + 2 * n + 2 * k, "expr") for k in range(n)]
    if op in (0xFFF4, 0xFFF5):
        return [(4 + 2 * k, "pc") for k in range(len(st.code_targets))]
    return []                                     # RET, FRAME, DIALOG


class Stmt:
    """One statement: its bytes with the address fields zeroed, plus what they point at."""
    __slots__ = ("old_pc", "raw", "targets", "exprs", "fields", "op")

    def __init__(self, old_pc, raw, op, flds, targets, exprs):
        self.old_pc = old_pc
        self.raw = bytearray(raw)
        self.op = op
        self.fields = flds                        # [(offset, kind)]
        self.targets = targets                    # old pcs, one per 'pc' field
        self.exprs = exprs                        # expression bytes, one per 'expr' field


class Raw:
    """Bytes in the code region that do not decode (dead data); carried verbatim."""
    __slots__ = ("old_pc", "raw")

    def __init__(self, old_pc, raw):
        self.old_pc = old_pc
        self.raw = bytes(raw)


class BankModel:
    def __init__(self):
        self.table = b""                          # raw table words (offsets re-patched)
        self.slots = {}                           # type -> (count, old list offset)
        self.code = []                            # [Stmt | Raw]
        self.lists = []                           # [(old offset, [(size_word, old event_pc, subs bytes)])]

    # ---- parse ------------------------------------------------------------------ #
    @classmethod
    def parse(cls, bank):
        d = bytes(bank.data)
        n = len(d)
        m = cls()
        tt = bank.type_table_full()
        tend = 4 * bank.table_slots
        m.table = d[:tend]
        m.slots = dict(tt)
        starts = sorted(set(off for _c, off in tt.values()))
        if not starts:
            if tend != n:
                raise RelinkError("bank %d: no entry lists but %d bytes after the table" % (bank.index, n - tend))
            return m
        list_of = {}
        for t, (cnt, off) in tt.items():
            recs = bank.entries(off, cnt)
            list_of.setdefault(off, recs if len(recs) >= len(list_of.get(off, ())) else list_of[off])
        code_end = starts[0]
        # anchors: every pc the flow disassembler reaches, to resync after bad bytes
        reach = set()
        for sc in script.disassemble_bank(bank):
            reach |= set(sc.stmts)
        pool_refs = []
        pc = tend
        while pc < code_end:
            st = script.decode_statement(d, pc)
            if st is None or pc + st.size > code_end:
                nxt = min((p for p in reach if pc < p < code_end), default=code_end)
                m.code.append(Raw(pc, d[pc:nxt]))
                pc = nxt
                continue
            flds = fields(st)
            tg, ex = [], []
            for fo, kind in flds:
                v = struct.unpack_from("<H", d, pc + fo)[0]
                (tg if kind == "pc" else ex).append(v)
            m.code.append(Stmt(pc, d[pc:pc + st.size], st.op, flds, tg, ex))
            pool_refs += ex
            pc += st.size
        # entry lists: contiguous, in offset order, ending where the pool begins
        cur = code_end
        for off in starts:
            if off != cur:
                raise RelinkError("bank %d: entry list at 0x%04x, expected 0x%04x" % (bank.index, off, cur))
            recs = []
            for eo, size, eid in list_of[off]:
                recs.append((size, eid, d[eo + 4:eo + 4 + 5 * size]))
                cur = eo + 4 + 5 * size
            m.lists.append((off, recs))
        pool0 = cur
        # the pool: one expression per reference, in reference order
        p = pool0
        for s in m.code:
            if isinstance(s, Raw):
                continue
            ex = []
            for v in s.exprs:
                if v != p:
                    raise RelinkError("bank %d: operand of 0x%04x at 0x%04x, pool is at 0x%04x"
                                      % (bank.index, s.old_pc, v, p))
                ln = expr_size(d, v)
                ex.append(d[v:v + ln])
                p += ln
            s.exprs = ex
        if p != n:
            raise RelinkError("bank %d: pool ends at 0x%04x, bank at 0x%04x" % (bank.index, p, n))
        return m

    # ---- build ------------------------------------------------------------------ #
    def build(self):
        out = bytearray(self.table)
        if not self.lists:
            return bytes(out)
        newpc = {}
        pc = len(out)
        for s in self.code:
            newpc[s.old_pc] = pc
            pc += len(s.raw)
        if pc > 0xFFFF:
            raise RelinkError("code runs past 64 KB")
        newlist = {}
        lp = pc
        for off, recs in self.lists:
            newlist[off] = lp
            lp += sum(4 + len(b) for _s, _e, b in recs)
        pool = bytearray()
        pool0 = lp

        def pc_of(old, what):
            if old not in newpc:
                raise RelinkError("%s 0x%04x is not a statement start" % (what, old))
            return newpc[old]

        for s in self.code:
            if isinstance(s, Raw):
                out += s.raw
                continue
            raw = bytearray(s.raw)
            ti = ei = 0
            for fo, kind in s.fields:
                if kind == "pc":
                    v = pc_of(s.targets[ti], "target of 0x%04x" % s.old_pc)
                    ti += 1
                else:
                    v = pool0 + len(pool)
                    pool += s.exprs[ei]
                    ei += 1
                if v > 0xFFFF:
                    raise RelinkError("address 0x%X past 64 KB" % v)
                struct.pack_into("<H", raw, fo, v)
            out += raw
        for off, recs in self.lists:
            for size, eid, subs in recs:
                out += struct.pack("<HH", size, pc_of(eid, "event pc"))
                out += subs
        out += pool
        for t, (cnt, off) in self.slots.items():
            struct.pack_into("<HH", out, 4 * t, cnt, newlist[off])
        if len(out) > 0xFFFF + 1:
            raise RelinkError("bank would be %d bytes (64 KB max)" % len(out))
        return bytes(out)


def relink(bank):
    """Parse and rebuild `bank`; returns the new bytes (identical when nothing changed)."""
    return BankModel.parse(bank).build()


# ---- the whole bank as text ------------------------------------------------------------ #
#
#   .table 74                        ; the type table's slot count
#   .slot 6 3 list_4f2a              ; type, entry count, list label (one per used type)
#   L_0128:                          ; a label on every pc something points at
#       FRAME 2                      ; statements in the scriptasm listing language
#       BR_Z (REG_WIFE_ID == 11) -> L_0140
#   .raw 0200761368...               ; bytes in the code region that do not decode
#   list_4f2a:
#   .entry L_0128 1:-1 2:5           ; event pc, then the {tag:key} records
#
# Operands print as scriptasm.operand_text; the few that text cannot reproduce byte for byte
# print as raw(<hex>). The pool is not in the listing: it is rebuilt from the operands in
# reference order, exactly as the game's compiler laid it out.

def _operand_text(asm, buf, off, want, op=None, index=None):
    from . import scriptasm
    txt = scriptasm.operand_text(buf, off, op, index)
    try:
        kind, got = asm.operand(txt, op, index)
    except Exception:  # noqa: BLE001 - any text that does not come back is written raw
        kind, got = None, None
    return txt if kind == "expr" and got == want else "raw(%s)" % want.hex()


def _paren(t):
    from . import scriptasm
    return t if t.startswith("(") and scriptasm._outer_parens(t) else "(%s)" % t


def bank_listing(bank, resolver=None):
    """The whole bank as text (see above); assemble_bank(text) rebuilds it."""
    from . import scriptasm
    d = bytes(bank.data)
    m = BankModel.parse(bank)
    asm = scriptasm.Assembler(resolver, strict=False)
    targets = set()
    for s in m.code:
        if isinstance(s, Stmt):
            targets |= set(s.targets)
    for _off, recs in m.lists:
        targets |= set(e for _s, e, _b in recs)
    lab = lambda pc: "L_%04x" % pc           # noqa: E731
    out = [".table %d" % (len(m.table) // 4)]
    used = bytearray(m.table)
    for t, (cnt, off) in m.slots.items():
        out.append(".slot %d %d list_%04x" % (t, cnt, off))
        used[4 * t:4 * t + 4] = b"\0\0\0\0"
    for t in range(len(used) // 4):         # table words no used slot explains (none shipped)
        if used[4 * t:4 * t + 4] != b"\0\0\0\0":
            out.append(".tword %d %s" % (t, used[4 * t:4 * t + 4].hex()))
    for s in m.code:
        if s.old_pc in targets:
            out.append("%s:" % lab(s.old_pc))
        if isinstance(s, Raw):
            out.append(".raw %s" % s.raw.hex())
            continue
        st = script.decode_statement(d, s.old_pc)
        ex = iter(zip([v for (fo, k) in s.fields if k == "expr" for v in [struct.unpack_from("<H", d, s.old_pc + fo)[0]]], s.exprs))
        tg = [lab(t) for t in s.targets]
        op = st.op
        if op < 0xFFF0:
            args = [_operand_text(asm, d, o, w, op, i) for i, (o, w) in enumerate(ex)]
            line = scriptasm.action_text(scriptasm.listing_name(op), args)
        elif op == 0xFFFF:
            line = "END"
        elif op == 0xFFF1:
            line = "FRAME %d" % st.items[0]
        elif op == 0xFFFC:
            line = "DIALOG #%d" % st.dialog_id
        elif op in (0xFFFE, 0xFFFA):
            line = "%s %s" % (st.mnem, tg[0])
        elif op in (0xFFFD, 0xFFFB):
            o, w = next(ex)
            line = "%s %s" % (st.mnem, _paren(_operand_text(asm, d, o, w)))
        elif op in (0xFFF8, 0xFFF9):
            o, w = next(ex)
            line = "%s %s -> %s" % (st.mnem, _paren(_operand_text(asm, d, o, w)), tg[0])
        elif op in (0xFFF6, 0xFFF7):
            o, w = next(ex)
            line = "%s %s -> %s" % (st.mnem, _paren(_operand_text(asm, d, o, w)), ", ".join(tg))
        elif op == 0xFFF3:
            line = "JMP_IND %s" % ", ".join(tg)
        elif op == 0xFFF2:
            ws = [_paren(_operand_text(asm, d, o, w)) for o, w in ex]
            line = "RAND_BR " + ", ".join("%s -> %s" % (w, t) for w, t in zip(ws, tg))
        elif op == 0xFFF4:
            line = "PROMPT_CHOICE CANCEL -> %s" % tg[0] + "".join(
                ", #%d -> %s" % (it, t) for it, t in zip(st.items, tg[1:]))
        elif op == 0xFFF5:
            line = "PROMPT_CHOICE_FORCED " + ", ".join("#%d -> %s" % (it, t) for it, t in zip(st.items, tg))
        else:
            raise RelinkError("no listing form for 0x%04x" % op)
        out.append("    " + line)
    for off, recs in m.lists:
        out.append("list_%04x:" % off)
        for size, eid, subs in recs:
            keys = " ".join("%d:%d" % (subs[5 * k], struct.unpack_from("<i", subs, 5 * k + 1)[0])
                            for k in range(size))
            out.append(".entry %s%s" % (lab(eid), (" " + keys) if keys else ""))
    return "\n".join(out) + "\n"


def assemble_bank(text, resolver=None, strict=False):
    """Bytes of the bank described by `text` (a bank_listing, possibly edited)."""
    import re
    from . import scriptasm
    asm = scriptasm.Assembler(resolver, strict=strict)
    slots_n = None
    slots = []                                # (type, count, list label)
    twords = {}
    code = []                                 # _Stmt, in order
    lists = []                                # (label, [(pc label, [(tag, key)])])
    labels = {}                               # name -> ("code", _Stmt) | ("list", index)
    pending = []
    for ln, raw in enumerate(text.splitlines(), 1):
        line = scriptasm._strip_comment(raw).strip()
        while True:
            mm = re.match(r"^([A-Za-z_]\w*)\s*:(?!:)\s*(.*)$", line)
            if not mm:
                break
            if mm.group(1) in labels or mm.group(1) in pending:
                raise RelinkError("line %d: duplicate label %r" % (ln, mm.group(1)))
            pending.append(mm.group(1))
            line = mm.group(2).strip()
        if not line:
            continue
        try:
            if line.startswith(".table"):
                slots_n = int(line.split()[1])
            elif line.startswith(".slot"):
                _k, t, cnt, lb = line.split()
                slots.append((int(t), int(cnt), lb))
            elif line.startswith(".tword"):
                _k, t, hx = line.split()
                twords[int(t)] = bytes.fromhex(hx)
            elif line.startswith(".entry"):
                parts = line.split()
                if pending:                   # a label in front of an entry starts a list
                    for lb in pending:
                        labels[lb] = ("list", len(lists))
                    lists.append((pending[0], []))
                    pending = []
                if not lists:
                    raise RelinkError("line %d: .entry before any list label" % ln)
                keys = []
                for kv in parts[2:]:
                    tg, _c, v = kv.partition(":")
                    keys.append((int(tg, 0), int(v, 0)))
                lists[-1][1].append((parts[1], keys, ln))
            else:
                if lists:
                    raise RelinkError("line %d: code after the entry lists" % ln)
                st = scriptasm._Stmt(ln, line)
                asm.parse_line(ln, line, st)
                for lb in pending:
                    labels[lb] = ("code", st)
                pending = []
                code.append(st)
        except (ValueError, IndexError, struct.error) as e:
            raise RelinkError("line %d: %s" % (ln, e))
    if pending:                               # a label with nothing after it: an empty list
        for lb in pending:
            labels[lb] = ("list", len(lists))
        lists.append((pending[0], []))
    if slots_n is None:
        raise RelinkError("missing .table")
    out = bytearray(4 * slots_n)
    for t, w in twords.items():
        out[4 * t:4 * t + 4] = w
    if not slots and not code and not lists:
        return bytes(out)
    pc = len(out)
    for st in code:
        st.label = pc
        pc += len(st.code)
    list_at = []
    for _lb, recs in lists:
        list_at.append(pc)
        pc += sum(4 + 5 * len(keys) for _e, keys, _l in recs)
    pool0 = pc
    pool = bytearray()

    def code_pc(name, where):
        k = labels.get(name)
        if k is None or k[0] != "code":
            if re.fullmatch(r"0[xX][0-9A-Fa-f]+|\d+", name):
                return int(name, 0)
            raise RelinkError("%s: undefined label %r" % (where, name))
        return k[1].label

    for st in code:
        buf = st.code
        for fo, kind, payload in st.fixups:
            if kind == "expr":
                v = pool0 + len(pool)
                pool += payload
            elif kind == "abs":
                v = int(payload)
            else:
                v = code_pc(payload, "line %d" % st.line_no)
            if v > 0xFFFF:
                raise RelinkError("line %d: address 0x%X past 64 KB" % (st.line_no, v))
            struct.pack_into("<H", buf, fo, v)
        out += buf
    for _lb, recs in lists:
        for eid, keys, ln in recs:
            out += struct.pack("<HH", len(keys), code_pc(eid, "line %d" % ln))
            for tg, v in keys:
                out += struct.pack("<Bi", tg, v)
    out += pool
    for t, cnt, lb in slots:
        k = labels.get(lb)
        if k is None or k[0] != "list":
            raise RelinkError(".slot %d: %r is not an entry-list label" % (t, lb))
        struct.pack_into("<HH", out, 4 * t, cnt, list_at[k[1]])
    if len(out) > 0x10000:
        raise RelinkError("bank would be %d bytes (64 KB max)" % len(out))
    return bytes(out)
