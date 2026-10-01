"""varuses.py -- where each named variable (emdeb.bin's FLG_ / REG_ / EV_) is read and written.

Two places name them:

* rf3.mc: a token-0x02 packed variable inside an RPN expression -- a branch condition, an
  EVAL, a SWITCH value or an action's argument. The expression is walked like the engine's
  evaluator (Script_EvalExpressionBytecode, RF4S.exe+0x23E1C0): `=` (operator 0x90) WRITES
  its left operand without reading it, the compound assignments 0x91..0x97 (`*=`, `+=` ...)
  read and write it, every other use reads.
* em.bin: a flag operand of a condition (read) or of an action -- SET / SET_EQ_ZERO write the
  target, the arithmetic ones (ADD, MAX_S ...) read and write it, the value operand is read.

A variable is keyed by (bit offset, width): that is what both files store, so a script's
`REG_X` and an em.bin action on REG_X meet under one key.

Not covered: action ops that touch a named register inside their handler (e.g. op 536 moves
REG_SUBEV_RSV into REG_SUBEV_NOW) -- the scripts do not name the variable there, the op does.
The unnamed zone-2 bits (ops 318 / 443-445, map objects) are flagusers.py's subject."""
from __future__ import annotations

from . import script

READ, WRITE, READ_WRITE = "read", "write", "read+write"

_ASSIGN = 0x90                      # `=`
_COMPOUND = range(0x91, 0x98)       # *= /= %= += -= &&= ||=
_UNARY = (0x81, 0x82)               # neg, not
_BINARY = range(0x83, 0x90)         # arithmetic, comparisons, && ||


def expr_var_access(buf, off, _maxtok=512):
    """[(enc, access)] for the packed variables of the RPN expression at `off`, in stream
    order (enc = the token-0x02 u32; access READ / WRITE / READ_WRITE)."""
    n = len(buf)
    if not (0 <= off < n) or buf[off] in (3, 4, 5, 0x11, 0x12, 0x13):
        return []                     # a single leaf: a constant, never a variable
    refs = []                         # [enc, access]
    stack = []                        # index into refs for a variable operand, else None
    p = off
    for _ in range(_maxtok):
        if not (0 <= p < n):
            break
        t = buf[p]
        if t == 0x00:
            break
        if t == 0x02:
            refs.append([int.from_bytes(buf[p + 1:p + 5], "little"), READ])
            stack.append(len(refs) - 1)
            p += 5
        elif t == 0x01:
            stack.append(None); p += 5
        elif t == 0x06:
            stack.append(None); p += 3
        elif 0x07 <= t <= 0x10 or t in (0x14, 0x15, 0x16):
            stack.append(None); p += 1
        elif t in (0x17, 0x18):
            stack.append(None); p += 2
        elif t in (0x19, 0x1A):
            stack.append(None); p += 3
        elif t == 0x80:
            p += 1
        elif t in _UNARY:
            if stack:
                stack.pop()
            stack.append(None); p += 1
        elif t in _BINARY or t == _ASSIGN or t in _COMPOUND:
            stack.pop() if stack else None
            lhs = stack.pop() if stack else None
            if lhs is not None and t == _ASSIGN:
                refs[lhs][1] = WRITE
            elif lhs is not None and t in _COMPOUND:
                refs[lhs][1] = READ_WRITE
            stack.append(None); p += 1
        else:
            break
    return [(e, a) for e, a in refs]


def statement_var_access(buf, st):
    """[(enc, access)] over every expression of statement `st` (its arguments, or a control
    op's condition / value)."""
    offs = list(st.args) if st.op < 0xFFF0 else []
    offs += [e for e in (getattr(st, "expr_refs", None) or []) if e is not None]
    out = []
    for off in offs:
        if off is not None:
            out += expr_var_access(buf, off)
    return out


def bank_uses(bank):
    """[(enc, access, scene entry pc, statement pc, statement)] for one bank -- every
    statement once, attributed to the first scene that reaches it."""
    out, seen = [], set()
    buf = bank.data
    for sc in script.disassemble_bank(bank):
        for pc, st in sc.stmts.items():
            if pc in seen:
                continue
            seen.add(pc)
            for enc, acc in statement_var_access(buf, st):
                out.append((enc, acc, sc.entry_pc, pc, st))
    return out


def em_uses(em):
    """[(bit offset, width, access, entry index, where)] for em.bin: where = 'condition A',
    'condition B', 'action' or 'alt action'."""
    out = []
    for e in em.entries:
        for which, slots in (("condition A", e.cond_a), ("condition B", e.cond_b)):
            for exprs in slots or ():
                for x in exprs:
                    if x.kind == "cmp":
                        for o in (x.op1, x.op2):
                            if o is not None and o.kind == "flag":
                                out.append((o.value, o.width, READ, e.idx, which))
        for which, acts in (("action", e.actions), ("alt action", e.alt_actions)):
            for a in acts or ():
                if a.target is not None and a.target.kind == "flag":
                    acc = WRITE if a.name in ("SET", "SET_EQ_ZERO") else READ_WRITE
                    out.append((a.target.value, a.target.width, acc, e.idx, which))
                if a.value is not None and a.value.kind == "flag":
                    out.append((a.value.value, a.value.width, READ, e.idx, which))
    return out


def var_name(table, bit_offset, width):
    """The emdeb name of (bit offset, width), or 'var@offset/width' when nothing matches it
    exactly (a field inside a variable, or no emdeb.bin)."""
    v = table.by_offset(bit_offset) if table is not None else None
    if v is not None and v.bit_offset == bit_offset and v.bit_width == width:
        return v.name
    return "var@%d/%d" % (bit_offset, width)
