"""emscript.py -- em.bin (``EMF_``) Event Manager archive: conditions + actions.

The Event Manager is the game's *trigger layer*: 272 named entries, each holding up
to two CONDITION programs (A and B) and up to two ACTION programs (main and alt).
Cutscene scripts (rf3.mc), the NPC AI, the daily tick and the request-box all ask it
"is entry N true right now?" / "fire entry N's actions".

Every structural fact in this module was verified against RF4S.exe decompiles
(2026-07-04 session):

  loader / context     g_emfContext (RF4S.exe+0x9EC7B8):
                         +0  Script_QueryGameState   (resolves 'query' operands)
                         +16 GameFlags_ReadField     (resolves 'flag' operands)
                         +24 GameFlags_WriteField    (action writes land here)
                         +40 em.bin data, +48 size
  header               CondScript_EvalNamedConditionA/B (+0x23B6A0/+0x23B7E0):
                         magic 'EMF_' (0x5F464D45, LE or BE), u32 entry_count @+12,
                         u32 entry_table_off @+16
  entry record (24 B)  +0/+4  condition-A (or_slot_count, block_off)
                       +8/+12 condition-B (or_slot_count, block_off)
                       +16    main action block off   (EMF_DispatchEntry)
                       +20    alt  action block off   (EMF_DispatchAltActionStream)
  condition semantics  CondScript_EvalEntry (+0x23BDB0): OR over 8-byte slots
                       (count, stream_off); within a slot the expr opcode HIGH BIT
                       means "OR with next expr" -- consecutive hi-bit exprs plus one
                       final clear-bit expr form an OR-group; groups AND together.
  expr opcodes         CondScript_EvalExpr (+0x23BEC0), op = byte & 0x7F:
                       0 TRUE, 1 FALSE, 2/3 CondA(id u16/u32), 4/5 NOT CondA,
                       6/7 CondB, 8/9 NOT CondB; else (op & 0x70):
                       0x10 ==, 0x20 !=, 0x30 >, 0x40 >= (signed if either
                       operand is type-1 or a signed flag ref).
  cmp operands         CondScript_ReadComparisonOperands (+0x23C1A0):
                       type1 = (op>>2)&3, type2 = op&3;
                       type 0 u32 literal / 1 signed u32 literal / 2 u16 query id
                       (Script_QueryGameState case) / 3 flag ref: one byte
                       (sign<<7 | size_code<<5 | width-1) + bit_offset in
                       1/2/3/4 bytes (size_code 0..3), resolved against the
                       emdeb.bin variable table (see emflags.py).
  action stream        EMF_RunActionStream (+0x23C320): block = (u32 count,
                       u32 stream_off).  EMF_DispatchActionOpcode (+0x23C390),
                       high nibble: 0x00/0x10 CALL entry (u16/u32; main stream
                       recurses into MAIN, alt stream into ALT), 0x20 SET,
                       0x30 ADD, 0x40 SUB, 0x50/0x60 MUL s/u, 0x70/0x80 DIV s/u,
                       0x90/0xA0 MOD s/u, 0xB0/0xC0 MAX s/u, 0xD0/0xE0 MIN s/u,
                       0xF0 SET_EQ_ZERO.  The opcode byte doubles as the operand
                       descriptor (EMF_DecodeOperandPair +0x23CDB0): target mode =
                       (b>>2)&3 (0/1 = 4-byte unused field, 2 = u16 handle,
                       3 = flag ref), value type = b&3 (same encoding as cmp).

Names come from the DEBUG build ``emdeb.bin`` (same archive id, ships next to
em.bin): 272 entry names at header (u32[9] count, u32[10] off) as 16-byte
(en_len, en_off, jp_len, jp_off) records with ABSOLUTE string offsets, and 218
query names at (u32[3], u32[4]) as 20-byte records (extra flags dword).

Editing (2026-07-05 in-place, 2026-09-19 structural): value edits patch fixed-width
fields in place (set_operand_value / set_cmp_operator / set_action_op / set_call_entry
/ set_cond_ref); STRUCTURAL edits (add_entry / clear_entry / delete_entry,
add_condition / remove_condition, add_action / remove_action, the parse_*_spec
mini-language) rebuild the whole container through serialize(), which re-emits the
stock section order byte-exact. What the engine requires of the result was re-read
2026-09-19 in CondScript_EvalNamedConditionA (RF4S.exe+0x23B6A0), EMF_DispatchEntry
(+0x23B920) and the loader CondScript_LoadSceneSpecAndDispatchEntry (+0x1D5E10):
size >= 20, magic, entry_id < u32@+12, table @+16 -- see the layout note on EmScript.
"""

from __future__ import annotations

import os
import re
import struct
from collections import OrderedDict

from . import emflags

MAGIC_LE = b"EMF_"

CMP_NAMES = {0x10: "==", 0x20: "!=", 0x30: ">", 0x40: ">="}
ACTION_NAMES = {
    0x00: "CALL", 0x10: "CALL", 0x20: "SET", 0x30: "ADD", 0x40: "SUB",
    0x50: "MUL_S", 0x60: "MUL_U", 0x70: "DIV_S", 0x80: "DIV_U",
    0x90: "MOD_S", 0xA0: "MOD_U", 0xB0: "MAX_S", 0xC0: "MAX_U",
    0xD0: "MIN_S", 0xE0: "MIN_U", 0xF0: "SET_EQ_ZERO",
}

# Human-readable one-liners for every action opcode + comparison operator. The action
# mnemonics are terse assembly-style tokens (the `_S`/`_U` suffix = signed / unsigned
# arithmetic), so these power the GUI op-picker hint + `em` docs. `t` = the action target
# (a REG_/flag), `v` = the operand value; conditions read left (op1) vs right (op2).
OP_HELP = {
    # arithmetic actions (t = target register/flag, v = operand)
    "CALL": "run another em entry's actions, then continue",
    "SET": "t = v   (overwrite the target with the value)",
    "ADD": "t = t + v",
    "SUB": "t = t - v",
    "MUL_S": "t = t * v   (signed multiply)",
    "MUL_U": "t = t * v   (unsigned multiply)",
    "DIV_S": "t = t / v   (signed divide)",
    "DIV_U": "t = t / v   (unsigned divide)",
    "MOD_S": "t = t % v   (signed remainder)",
    "MOD_U": "t = t % v   (unsigned remainder)",
    "MAX_S": "t = max(t, v)   (signed)",
    "MAX_U": "t = max(t, v)   (unsigned)",
    "MIN_S": "t = min(t, v)   (signed)",
    "MIN_U": "t = min(t, v)   (unsigned)",
    "SET_EQ_ZERO": "t = (v == 0) ? 1 : 0   (boolean 'is the value zero')",
    # comparison operators (condition is true when left <op> right holds)
    "==": "condition true when the two operands are equal",
    "!=": "condition true when the operands differ",
    ">": "condition true when left > right",
    ">=": "condition true when left >= right",
}


# ---------------------------------------------------------------------------
# operand / expression model
# ---------------------------------------------------------------------------

class Operand(object):
    """One comparison/action operand.

    kind: 'lit' (u32), 'slit' (signed u32), 'query' (u16 id into the
    Script_QueryGameState table), 'flag' (GameFlags variable ref), 'none'
    (action target modes 0/1 -- 4 raw bytes, unused by the engine).
    """

    __slots__ = ("kind", "value", "width", "sign", "pos", "nbytes")

    def __init__(self, kind, value, width=0, sign=0, pos=None, nbytes=0):
        self.kind = kind
        self.value = value
        self.width = width
        self.sign = sign
        self.pos = pos            # byte offset of this operand's immediate in the file
        self.nbytes = nbytes      # total encoded length (for in-place editing)

    def pretty(self, names):
        if self.kind == "flag":
            v = names.flag_at(self.value)
            if v is not None and v.bit_offset == self.value and v.bit_width == self.width:
                return v.name
            if v is not None:
                return "%s@%+d/w%d" % (v.name, self.value - v.bit_offset, self.width)
            return "FLAG[bit 0x%X w%d]" % (self.value, self.width)
        if self.kind == "query":
            q = names.query_name(self.value)
            return q if q else "QUERY[%d]" % self.value
        if self.kind == "slit":
            return str(struct.unpack("<i", struct.pack("<I", self.value & 0xFFFFFFFF))[0])
        return str(self.value)


class Expr(object):
    """One condition expression. op_byte keeps the raw byte (incl. OR-next bit)."""

    __slots__ = ("op_byte", "kind", "cmp", "ref", "op1", "op2", "pos")

    def __init__(self, op_byte, kind, cmp=None, ref=None, op1=None, op2=None, pos=None):
        self.op_byte = op_byte
        self.kind = kind        # 'true','false','cond_a','not_cond_a','cond_b','not_cond_b','cmp'
        self.cmp = cmp          # comparison operator string for kind == 'cmp'
        self.ref = ref          # entry id for cond_a/b kinds
        self.op1 = op1
        self.op2 = op2
        self.pos = pos          # byte offset of this expr's opcode byte in the file

    @property
    def or_next(self):
        return bool(self.op_byte & 0x80)

    def pretty(self, names):
        if self.kind == "true":
            return "TRUE"
        if self.kind == "false":
            return "FALSE"
        if self.kind in ("cond_a", "not_cond_a", "cond_b", "not_cond_b"):
            neg = "!" if self.kind.startswith("not_") else ""
            var = "A" if self.kind.endswith("_a") else "B"
            nm = names.entry_name(self.ref)
            tgt = nm if nm else "#%d" % self.ref
            return "%scond%s(%s)" % (neg, var, tgt)
        return "%s %s %s" % (self.op1.pretty(names), self.cmp, self.op2.pretty(names))


class Action(object):
    __slots__ = ("op", "name", "entry", "target", "value", "pos", "op_byte")

    def __init__(self, op, name, entry=None, target=None, value=None, pos=None, op_byte=None):
        self.op = op            # high nibble
        self.name = name
        self.entry = entry      # for CALL
        self.target = target    # Operand ('flag'/'query'/'none'; a 'none' target keeps its
                                #          raw mode bit 0/1 in .width so it re-emits verbatim)
        self.value = value      # Operand
        self.pos = pos          # byte offset of this action's opcode byte in the file
        self.op_byte = op_byte  # raw opcode byte as parsed (None for a freshly built action)

    def pretty(self, names):
        if self.name == "CALL":
            nm = names.entry_name(self.entry)
            return "CALL %s" % (nm if nm else "#%d" % self.entry)
        t = self.target.pretty(names) if self.target else "?"
        v = self.value.pretty(names) if self.value else "?"
        if self.name == "SET":
            return "%s = %s" % (t, v)
        if self.name == "SET_EQ_ZERO":
            return "%s = (%s == 0)" % (t, v)
        return "%s = %s(%s, %s)" % (t, self.name, t, v)


class Entry(object):
    __slots__ = ("idx", "name", "jp", "cond_a", "cond_b", "actions", "alt_actions")

    def __init__(self, idx, name, jp, cond_a, cond_b, actions, alt_actions):
        self.idx = idx
        self.name = name
        self.jp = jp
        self.cond_a = cond_a          # list[slot] ; slot = list[Expr] -- ORed slots
        self.cond_b = cond_b
        self.actions = actions        # list[Action] (main stream)
        self.alt_actions = alt_actions

    def pretty_condition(self, names, which="a", indent="  "):
        slots = self.cond_a if which == "a" else self.cond_b
        if not slots:
            return indent + "(none)"
        out = []
        for si, exprs in enumerate(slots):
            groups, cur = [], []
            for e in exprs:
                cur.append(e.pretty(names))
                if not e.or_next:
                    groups.append(" OR ".join(cur) if len(cur) > 1
                                  else cur[0])
                    cur = []
            if cur:                                   # malformed tail (never seen)
                groups.append(" OR ".join(cur))
            groups = ["(%s)" % g if " OR " in g else g for g in groups]
            out.append(indent + ("OR " if si else "   ") + " AND ".join(groups))
        return "\n".join(out)


# ---------------------------------------------------------------------------
# emdeb.bin name tables (entries + queries)
# ---------------------------------------------------------------------------

class EmNames(object):
    """Entry + query name tables from emdeb.bin, plus the emflags variable table."""

    def __init__(self, entry_names, query_names, flags):
        self.entry_names = entry_names    # list[(en, jp)]
        self.query_names = query_names    # list[(en, jp)]
        self.flags = flags                # emflags.EmFlagTable
        self._flag_sorted = sorted(v.bit_offset for v in flags.variables)

    @classmethod
    def parse(cls, emdeb_data, flags=None):
        d = emdeb_data
        if d[:4] != b"EMDb":
            raise ValueError("not an emdeb.bin (EMDb) file")
        hdr = struct.unpack_from("<16I", d, 0)
        q_cnt, q_off = hdr[3], hdr[4]
        e_cnt, e_off = hdr[9], hdr[10]

        def rd(off, ln, jp=False):
            b = d[off:off + ln]
            try:
                return b.decode("cp932" if jp else "ascii")
            except UnicodeDecodeError:
                return b.decode("cp932", "replace")

        entries = []
        for i in range(e_cnt):
            el, eo, jl, jo = struct.unpack_from("<4I", d, e_off + 16 * i)
            entries.append((rd(eo, el), rd(jo, jl, True)))
        queries = []
        for i in range(q_cnt):
            el, eo, jl, jo, _fl = struct.unpack_from("<5I", d, q_off + 20 * i)
            queries.append((rd(eo, el), rd(jo, jl, True)))
        if flags is None:
            flags = emflags.EmFlagTable.parse(d)
        return cls(entries, queries, flags)

    @classmethod
    def load(cls, path=None):
        if path is None:
            path = emflags.find_emdeb()
        with open(path, "rb") as f:
            return cls.parse(f.read())

    def entry_name(self, idx):
        if 0 <= idx < len(self.entry_names):
            return self.entry_names[idx][0]
        return None

    def query_name(self, idx):
        if 0 <= idx < len(self.query_names):
            return self.query_names[idx][0]
        return None

    def flag_at(self, bit_offset):
        """The variable containing bit_offset (exact-start match preferred)."""
        return self.flags.by_offset(bit_offset)


# ---------------------------------------------------------------------------
# em.bin parser
# ---------------------------------------------------------------------------

class EmScript(object):
    """Parsed em.bin: 272 entries with decoded conditions + actions."""

    def __init__(self, entries, names, data=None, hdr=None, tail=b""):
        if isinstance(entries, (bytes, bytearray, str)):   # footgun: raw bytes, not an entry list
            raise ValueError("EmScript() takes a list of Entry objects, not raw bytes -- "
                             "use EmScript.parse(data, names).")
        self.entries = entries
        self.names = names
        self.data = bytearray(data) if data is not None else None   # mutable, for edits
        self.hdr = bytes(hdr) if hdr is not None else None   # bytes before the entry table (20)
        self.tail = bytes(tail)                              # bytes past the last stream (77 x 0)
        self.by_name = OrderedDict()
        for e in entries:
            if e.name:
                self.by_name.setdefault(e.name, e)

    # -- construction -------------------------------------------------------
    @classmethod
    def parse(cls, data, names):
        if data[:4] != MAGIC_LE:
            raise ValueError("not an em.bin (EMF_) file: %r" % data[:4])
        count = struct.unpack_from("<I", data, 12)[0]
        table = struct.unpack_from("<I", data, 16)[0]

        entries = []
        ends = [table + 24 * count]          # end offsets of every region (for the tail)
        for i in range(count):
            (ca_cnt, ca_off, cb_cnt, cb_off,
             act_off, alt_off) = struct.unpack_from("<6I", data, table + 24 * i)
            nm, jp = (names.entry_names[i] if i < len(names.entry_names)
                      else ("", ""))
            entries.append(Entry(
                i, nm, jp,
                cls._parse_condition(data, ca_off, ca_cnt, ends),
                cls._parse_condition(data, cb_off, cb_cnt, ends),
                cls._parse_actions(data, act_off, ends),
                cls._parse_actions(data, alt_off, ends)))
        end = max(ends)
        return cls(entries, names, data, hdr=data[:table], tail=data[end:])

    @classmethod
    def load(cls, em_path=None, emdeb_path=None):
        if em_path is None:
            em_path = find_em()
        names = EmNames.load(emdeb_path)
        with open(em_path, "rb") as f:
            return cls.parse(f.read(), names)

    # -- conditions ----------------------------------------------------------
    @staticmethod
    def _read_cmp_operand(data, p, t):
        """Returns (Operand, new_pos). t = operand type bits (0..3). Each operand
        records its file position + length so it can be patched in place."""
        if t in (0, 1):
            return Operand("slit" if t == 1 else "lit",
                           struct.unpack_from("<I", data, p)[0], pos=p, nbytes=4), p + 4
        if t == 2:
            return Operand("query", struct.unpack_from("<H", data, p)[0],
                           pos=p, nbytes=2), p + 2
        b = data[p]
        sign, sc, wid = b >> 7, (b >> 5) & 3, (b & 0x1F) + 1
        n = sc + 1
        val = int.from_bytes(data[p + 1:p + 1 + n], "little")
        return Operand("flag", val, wid, sign, pos=p, nbytes=1 + n), p + 1 + n

    @classmethod
    def _parse_condition(cls, data, block_off, slot_count, ends=None):
        """block = slot_count x (u32 expr_count, u32 stream_off). None if absent.
        `ends` (optional list) collects the end offset of every region read."""
        if not block_off or not slot_count:
            return None
        slots = []
        if ends is not None:
            ends.append(block_off + 8 * slot_count)
        for s in range(slot_count):
            n, off = struct.unpack_from("<2I", data, block_off + 8 * s)
            exprs, p = [], off
            for _ in range(n):
                b = data[p]
                op = b & 0x7F
                if op == 0:
                    exprs.append(Expr(b, "true", pos=p)); p += 1
                elif op == 1:
                    exprs.append(Expr(b, "false", pos=p)); p += 1
                elif 2 <= op <= 9:
                    wide = op & 1
                    ref = (struct.unpack_from("<I", data, p + 1)[0] if wide
                           else struct.unpack_from("<H", data, p + 1)[0])
                    kind = {2: "cond_a", 4: "not_cond_a",
                            6: "cond_b", 8: "not_cond_b"}[op & ~1]
                    exprs.append(Expr(b, kind, ref=ref, pos=p))
                    p += 5 if wide else 3
                else:
                    grp = op & 0x70
                    if grp not in CMP_NAMES:
                        raise ValueError("bad expr opcode 0x%02X @0x%X" % (b, p))
                    t1, t2 = (op >> 2) & 3, op & 3
                    o1, q = cls._read_cmp_operand(data, p + 1, t1)
                    o2, q = cls._read_cmp_operand(data, q, t2)
                    exprs.append(Expr(b, "cmp", cmp=CMP_NAMES[grp], op1=o1, op2=o2, pos=p))
                    p = q
            if ends is not None:
                ends.append(p)
            slots.append(exprs)
        return slots

    # -- actions --------------------------------------------------------------
    @classmethod
    def _parse_actions(cls, data, block_off, ends=None):
        """block = (u32 count, u32 stream_off); [] if absent."""
        if not block_off:
            return []
        if ends is not None:
            ends.append(block_off + 8)
        n, off = struct.unpack_from("<2I", data, block_off)
        if not off:
            return []
        out, p = [], off
        for _ in range(n):
            b = data[p]
            hn = b & 0xF0
            if hn == 0x00:
                out.append(Action(hn, "CALL",
                                  entry=struct.unpack_from("<H", data, p + 1)[0], pos=p, op_byte=b))
                p += 3
                continue
            if hn == 0x10:
                out.append(Action(hn, "CALL",
                                  entry=struct.unpack_from("<I", data, p + 1)[0], pos=p, op_byte=b))
                p += 5
                continue
            # arithmetic: opcode byte doubles as the operand descriptor
            tmode, vtype = (b >> 2) & 3, b & 3
            q = p + 1
            if tmode in (0, 1):
                target = Operand("none", struct.unpack_from("<I", data, q)[0], width=tmode,
                                 pos=q, nbytes=4)
                q += 4
            elif tmode == 2:
                target = Operand("query", struct.unpack_from("<H", data, q)[0], pos=q, nbytes=2)
                q += 2
            else:
                tb = data[q]
                sc, wid, sign = (tb >> 5) & 3, (tb & 0x1F) + 1, tb >> 7
                val = int.from_bytes(data[q + 1:q + 2 + sc], "little")
                target = Operand("flag", val, wid, sign, pos=q, nbytes=2 + sc)
                q += 2 + sc
            value, q = cls._read_cmp_operand(data, q, vtype)
            out.append(Action(hn, ACTION_NAMES[hn], target=target, value=value, pos=p, op_byte=b))
            p = q
        if ends is not None:
            ends.append(p)
        return out

    # -- reporting -------------------------------------------------------------
    def get(self, key):
        if isinstance(key, int):
            return self.entries[key]
        return self.by_name[key]

    def format_entry(self, e, names=None):
        names = names or self.names
        lines = ["[%d] %s%s" % (e.idx, e.name or "(unnamed)",
                                 ("  %s" % e.jp) if e.jp else "")]
        if e.cond_a:
            lines.append(" condition A:")
            lines.append(e.pretty_condition(names, "a", "   "))
        if e.cond_b:
            lines.append(" condition B:")
            lines.append(e.pretty_condition(names, "b", "   "))
        if e.actions:
            lines.append(" actions:")
            lines += ["   " + a.pretty(names) for a in e.actions]
        if e.alt_actions:
            lines.append(" alt actions:")
            lines += ["   " + a.pretty(names) for a in e.alt_actions]
        if len(lines) == 1:
            lines.append("  (empty)")
        return "\n".join(lines)

    # every flag operand anywhere (for validation / cross-refs)
    def iter_flag_operands(self):
        for e in self.entries:
            for slots in (e.cond_a, e.cond_b):
                for exprs in slots or ():
                    for x in exprs:
                        if x.kind == "cmp":
                            for o in (x.op1, x.op2):
                                if o.kind == "flag":
                                    yield e, o
            for acts in (e.actions, e.alt_actions):
                for a in acts:
                    for o in (a.target, a.value):
                        if o is not None and o.kind == "flag":
                            yield e, o

    # -- in-place editing (all edits are fixed-width -> no relocation) ---------
    _OP_NIBBLE = {"==": 0x10, "!=": 0x20, ">": 0x30, ">=": 0x40}
    _ACT_NIBBLE = {v: k for k, v in ACTION_NAMES.items() if k not in (0x00, 0x10)}

    def _require_data(self):
        if self.data is None:
            raise ValueError("EmScript has no backing data; build from EmScript.parse(bytes, names)")

    def build(self):
        """Return the (possibly edited) em.bin bytes. Byte-identical to the input
        until an edit is applied (all edits patch fixed-width fields in place)."""
        self._require_data()
        return bytes(self.data)

    def set_operand_value(self, op, value):
        """Patch an operand's immediate in place (same width). lit/slit (u32),
        query (u16), or flag (bit_offset, if it fits the existing value bytes)."""
        self._require_data()
        if op is None or op.pos is None:
            raise ValueError("operand is not editable (no recorded position)")
        d = self.data
        if op.kind in ("lit", "slit"):
            iv = int(value)
            if not (-(1 << 31) <= iv < (1 << 32)):
                raise ValueError("value %d out of 32-bit range" % iv)
            struct.pack_into("<I", d, op.pos, iv & 0xFFFFFFFF)
            op.value = iv & 0xFFFFFFFF
        elif op.kind == "query":
            if not (0 <= int(value) <= 0xFFFF):
                raise ValueError("query id %s out of u16 range" % value)
            struct.pack_into("<H", d, op.pos, int(value))
            op.value = int(value)
        elif op.kind == "flag":
            n = op.nbytes - 1                        # value-byte count (tag + n bytes)
            if not (0 <= int(value) < (1 << (8 * n))):
                raise ValueError("bit offset %s doesn't fit the existing %d value byte(s)"
                                 % (value, n))
            d[op.pos + 1:op.pos + 1 + n] = int(value).to_bytes(n, "little")
            op.value = int(value)
        else:
            raise ValueError("operand kind %r has no editable immediate" % op.kind)
        return op

    def set_cmp_operator(self, expr, op_str):
        """Change a comparison expr's operator (==, !=, >, >=), preserving the
        OR-next bit and both operand-type bits."""
        self._require_data()
        if expr is None or expr.kind != "cmp" or expr.pos is None:
            raise ValueError("expr is not an editable comparison")
        nib = self._OP_NIBBLE.get(op_str)
        if nib is None:
            raise ValueError("operator must be one of %s" % ", ".join(self._OP_NIBBLE))
        nb = (self.data[expr.pos] & 0x8F) | nib      # keep bit7 (OR-next) + bits0-3 (types)
        self.data[expr.pos] = nb
        expr.op_byte, expr.cmp = nb, op_str
        return expr

    def set_action_op(self, action, name):
        """Change an arithmetic action's op (SET/ADD/SUB/MUL_S.../SET_EQ_ZERO),
        preserving the operand descriptor (low nibble). Not for CALL."""
        self._require_data()
        if action is None or action.pos is None or action.name == "CALL":
            raise ValueError("only arithmetic (non-CALL) actions can change op")
        nib = self._ACT_NIBBLE.get(name)
        if nib is None:
            raise ValueError("op must be one of %s" % ", ".join(sorted(self._ACT_NIBBLE)))
        nb = (self.data[action.pos] & 0x0F) | nib
        self.data[action.pos] = nb
        action.op, action.name, action.op_byte = nib, name, nb
        return action

    def set_call_entry(self, action, entry_id):
        """Repoint a CALL action to a different entry id (u16 or u32 in place)."""
        self._require_data()
        if action is None or action.name != "CALL" or action.pos is None:
            raise ValueError("not a CALL action")
        if (self.data[action.pos] & 0xF0) == 0x00:   # u16 entry
            if not (0 <= entry_id <= 0xFFFF):
                raise ValueError("entry id out of u16 range (this CALL is 16-bit)")
            struct.pack_into("<H", self.data, action.pos + 1, entry_id)
        else:                                        # 0x10 u32 entry
            struct.pack_into("<I", self.data, action.pos + 1, entry_id)
        action.entry = entry_id
        return action

    def set_cond_ref(self, expr, entry_id):
        """Repoint a condA/condB reference expr to a different entry id (in place)."""
        self._require_data()
        if (expr is None or expr.pos is None
                or expr.kind not in ("cond_a", "not_cond_a", "cond_b", "not_cond_b")):
            raise ValueError("not an editable condA/condB reference")
        if self.data[expr.pos] & 1:                  # wide (u32)
            struct.pack_into("<I", self.data, expr.pos + 1, entry_id)
        else:
            if not (0 <= entry_id <= 0xFFFF):
                raise ValueError("entry id out of u16 range (this ref is 16-bit)")
            struct.pack_into("<H", self.data, expr.pos + 1, entry_id)
        expr.ref = entry_id
        return expr

    # -- structural editing: rebuild the container --------------------------------
    # Physical layout of the shipped em.bin (mapped 2026-09-19 from the 652 regions the
    # parser touches: zero gaps, zero overlaps, byte-packed, no alignment padding):
    #
    #   header (20)                       'EMF_', u32 file_size, u32 0x00010001, u32 N, u32 20
    #   entry table  24 * N               (condA count/off, condB count/off, main off, alt off)
    #   condition SLOT tables             entry order; per entry condA slots then condB slots
    #   action BLOCKS (8 B each)          entry order; per entry main then alt
    #   condition EXPRESSION streams      entry order; per entry condA slots then condB slots
    #   action streams                    entry order; per entry main then alt
    #   tail (77 x 0x00)                  never addressed; kept verbatim
    #
    # `serialize()` re-emits exactly that order, so an unedited file rebuilds byte-exact
    # (selftest) and every structural edit yields a container the engine reads the same
    # way it reads the stock one. What the ENGINE checks (CondScript_EvalNamedConditionA/B
    # RF4S.exe+0x23B6A0/+0x23B7E0, EMF_DispatchEntry +0x23B920, EMF_DispatchAltActionStream
    # +0x23BA70): archive size >= 20, magic 'EMF_' (LE or BE selects the reader set),
    # entry_id < u32@+12 (so an id past entry_count silently evaluates FALSE / dispatches
    # nothing), table_off = u32@+16 != 0, then the 24-byte record's offsets != 0. Header +4
    # (file size) and +8 are NOT read: the loader CondScript_LoadSceneSpecAndDispatchEntry
    # (+0x1D5E10) takes the size from nsFileArchiveIndexGetFileSize(15207) -- it is kept
    # equal to len(file) anyway. Entry ids are referenced by NUMBER from rf3.mc bridge ops
    # (371..374/444, see `rf4mod em xref`) and by condA/condB refs + CALL actions inside
    # em.bin, so deleting an entry renumbers everything after it: delete_entry() fixes the
    # internal refs and reports them; use clear_entry() to blank an entry id-stably.
    # emdeb.bin (15208) is the debug NAME table only -- it is not loaded by the exe, so a
    # new entry simply shows as "(unnamed)" / #id in the toolkit.

    _REF_KINDS = ("cond_a", "not_cond_a", "cond_b", "not_cond_b")
    _REF_BASE = {("", "a"): 2, ("!", "a"): 4, ("", "b"): 6, ("!", "b"): 8}
    _TYPE_BITS = {"lit": 0, "slit": 1, "query": 2, "flag": 3}
    _ACT_SUGAR = {"=": "SET", "+=": "ADD", "-=": "SUB", "*=": "MUL_S", "/=": "DIV_S", "%=": "MOD_S"}

    @classmethod
    def _pack_operand(cls, o):
        if o.kind in ("lit", "slit", "none"):
            return struct.pack("<I", int(o.value) & 0xFFFFFFFF)
        if o.kind == "query":
            if not (0 <= int(o.value) <= 0xFFFF):
                raise ValueError("query id %r out of u16 range" % (o.value,))
            return struct.pack("<H", int(o.value))
        if o.kind == "flag":
            need = max(1, (int(o.value).bit_length() + 7) // 8)   # stock: always minimal (594/594)
            n = max(need, (o.nbytes - 1) if o.nbytes else 0)
            if n > 4:
                raise ValueError("flag bit offset %r needs more than 4 bytes" % (o.value,))
            if not (1 <= int(o.width) <= 32):
                raise ValueError("flag width %r out of 1..32" % (o.width,))
            tag = ((int(o.sign) & 1) << 7) | ((n - 1) << 5) | ((int(o.width) - 1) & 0x1F)
            return bytes([tag]) + int(o.value).to_bytes(n, "little")
        raise ValueError("operand kind %r cannot be serialized" % (o.kind,))

    @classmethod
    def _pack_expr(cls, x):
        if x.kind == "true":
            return bytes([(x.op_byte & 0x80) | 0x00])
        if x.kind == "false":
            return bytes([(x.op_byte & 0x80) | 0x01])
        if x.kind in cls._REF_KINDS:
            base = cls._REF_BASE[("not_" in x.kind and "!" or "", x.kind[-1])]
            wide = 1 if (x.op_byte & 1) or x.ref > 0xFFFF else 0
            b = (x.op_byte & 0x80) | base | wide
            return bytes([b]) + (struct.pack("<I", x.ref) if wide else struct.pack("<H", x.ref))
        if x.kind != "cmp":
            raise ValueError("unknown expr kind %r" % (x.kind,))
        b = ((x.op_byte & 0x80) | cls._OP_NIBBLE[x.cmp]
             | (cls._TYPE_BITS[x.op1.kind] << 2) | cls._TYPE_BITS[x.op2.kind])
        return bytes([b]) + cls._pack_operand(x.op1) + cls._pack_operand(x.op2)

    @classmethod
    def _pack_action(cls, a):
        if a.name == "CALL":
            if (a.op & 0xF0) == 0x10 or a.entry > 0xFFFF:
                return b"\x10" + struct.pack("<I", a.entry)
            return b"\x00" + struct.pack("<H", a.entry)
        t = a.target
        if t is None or a.value is None:
            raise ValueError("arithmetic action needs a target and a value operand")
        if t.kind == "flag":
            tmode = 3
        elif t.kind == "query":
            tmode = 2
        elif t.kind == "none":
            tmode = int(t.width) & 1          # raw mode 0/1 as parsed
        else:
            raise ValueError("action target must be a flag ref or a query handle, not %r" % (t.kind,))
        b = (a.op & 0xF0) | (tmode << 2) | cls._TYPE_BITS[a.value.kind]
        return bytes([b]) + cls._pack_operand(t) + cls._pack_operand(a.value)

    def serialize(self):
        """Re-emit the whole container from the entry objects in the stock layout order
        (see the layout note above). Header +4 = total size, +12 = entry count."""
        hdr = bytearray(self.hdr if self.hdr else MAGIC_LE + struct.pack("<4I", 0, 0x10001, 0, 20))
        table_off = len(hdr)
        n = len(self.entries)
        for i, e in enumerate(self.entries):
            e.idx = i
        pos = table_off + 24 * n
        slot_off, blk_off, cond_streams, act_streams = {}, {}, {}, {}
        for e in self.entries:                                   # slot tables
            for which, slots in (("a", e.cond_a), ("b", e.cond_b)):
                if slots:
                    slot_off[(e.idx, which)] = pos
                    pos += 8 * len(slots)
        for e in self.entries:                                   # action blocks
            for which, acts in (("main", e.actions), ("alt", e.alt_actions)):
                if acts:
                    blk_off[(e.idx, which)] = pos
                    pos += 8
        for e in self.entries:                                   # condition streams
            for which, slots in (("a", e.cond_a), ("b", e.cond_b)):
                for si, exprs in enumerate(slots or ()):
                    blob = b"".join(self._pack_expr(x) for x in exprs)
                    cond_streams[(e.idx, which, si)] = (pos, blob)
                    pos += len(blob)
        for e in self.entries:                                   # action streams
            for which, acts in (("main", e.actions), ("alt", e.alt_actions)):
                if acts:
                    blob = b"".join(self._pack_action(a) for a in acts)
                    act_streams[(e.idx, which)] = (pos, blob)
                    pos += len(blob)
        out = bytearray(hdr)
        for e in self.entries:
            out += struct.pack("<6I",
                               len(e.cond_a) if e.cond_a else 0, slot_off.get((e.idx, "a"), 0),
                               len(e.cond_b) if e.cond_b else 0, slot_off.get((e.idx, "b"), 0),
                               blk_off.get((e.idx, "main"), 0), blk_off.get((e.idx, "alt"), 0))
        for e in self.entries:
            for which, slots in (("a", e.cond_a), ("b", e.cond_b)):
                for si, exprs in enumerate(slots or ()):
                    out += struct.pack("<2I", len(exprs), cond_streams[(e.idx, which, si)][0])
        for e in self.entries:
            for which, acts in (("main", e.actions), ("alt", e.alt_actions)):
                if acts:
                    out += struct.pack("<2I", len(acts), act_streams[(e.idx, which)][0])
        for e in self.entries:
            for which, slots in (("a", e.cond_a), ("b", e.cond_b)):
                for si, _exprs in enumerate(slots or ()):
                    out += cond_streams[(e.idx, which, si)][1]
        for e in self.entries:
            for which, acts in (("main", e.actions), ("alt", e.alt_actions)):
                if acts:
                    out += act_streams[(e.idx, which)][1]
        out += self.tail
        struct.pack_into("<I", out, 4, len(out))
        struct.pack_into("<I", out, 12, n)
        struct.pack_into("<I", out, 16, table_off)
        return bytes(out)

    def _relayout(self):
        """Rebuild self.data from the entry objects and re-parse, so every Expr/Action/
        Operand position is valid again for the in-place editors. Entry/Expr/Action objects
        held by the caller from before the call are stale afterwards. Names travel with the
        entry objects (emdeb.bin's name table is positional, so after a physical delete the
        shipped emdeb names no longer line up with the ids past the deletion point)."""
        old = list(self.entries)
        fresh = EmScript.parse(self.serialize(), self.names)
        for o, n in zip(old, fresh.entries):
            n.name, n.jp = o.name, o.jp
        self.entries, self.data = fresh.entries, fresh.data
        self.hdr, self.tail = fresh.hdr, fresh.tail
        self.by_name = OrderedDict()
        for e in self.entries:
            if e.name:
                self.by_name.setdefault(e.name, e)

    def _idx(self, key):
        if isinstance(key, Entry):
            return key.idx
        if isinstance(key, int):
            if not (0 <= key < len(self.entries)):
                raise IndexError("entry %d out of range 0..%d" % (key, len(self.entries) - 1))
            return key
        return self.by_name[key].idx

    def refs_to(self, idx):
        """Internal references to entry `idx`: [(entry, 'condA/B slot s expr k' | 'main/alt
        action k')]. External references live in rf3.mc (bridge ops by number)."""
        out = []
        for e in self.entries:
            for which, slots in (("A", e.cond_a), ("B", e.cond_b)):
                for si, exprs in enumerate(slots or ()):
                    for k, x in enumerate(exprs):
                        if x.kind in self._REF_KINDS and x.ref == idx:
                            out.append((e, "cond%s slot %d expr %d" % (which, si, k)))
            for which, acts in (("main", e.actions), ("alt", e.alt_actions)):
                for k, a in enumerate(acts):
                    if a.name == "CALL" and a.entry == idx:
                        out.append((e, "%s action %d" % (which, k)))
        return out

    def clone_entry(self, src):
        """A detached deep copy of an entry's conditions + actions (idx -1, unnamed)."""
        import copy
        e = self.entries[self._idx(src)]
        return Entry(-1, "", "", copy.deepcopy(e.cond_a), copy.deepcopy(e.cond_b),
                     copy.deepcopy(e.actions), copy.deepcopy(e.alt_actions))

    def add_entry(self, entry=None, clone=None, name=""):
        """Append an entry (a clone of `clone`, the given Entry, or an empty one) and return
        its id (= the old entry count; the header count is bumped so the engine will
        evaluate/dispatch it). `name` is an in-memory label only (emdeb.bin is not
        rewritten): a reloaded file shows the entry as "(unnamed)" -- refer to it by id."""
        if entry is None:
            entry = (self.clone_entry(clone) if clone is not None
                     else Entry(-1, "", "", None, None, [], []))
        if name:
            entry.name = name
        self.entries.append(entry)
        self._relayout()
        return len(self.entries) - 1

    def clear_entry(self, key):
        """Blank an entry in place (no conditions -> evaluates FALSE, no actions), keeping
        every other entry id stable."""
        e = self.entries[self._idx(key)]
        e.cond_a, e.cond_b, e.actions, e.alt_actions = None, None, [], []
        self._relayout()
        return e.idx

    def delete_entry(self, key, force=False):
        """Physically remove an entry; every later entry moves down one id. Internal condA/
        condB refs and CALL targets above it are renumbered; refs TO it make this refuse
        unless force=True (they then dangle onto the next entry). rf3.mc bridge ops are not
        touched -- re-check them with `rf4mod em xref`. Returns the renumbered-ref count."""
        idx = self._idx(key)
        refs = self.refs_to(idx)
        if refs and not force:
            raise ValueError("entry %d is referenced by %s -- clear_entry() keeps ids stable, "
                             "or pass force=True" % (idx, ", ".join(
                                 "#%d %s (%s)" % (e.idx, e.name or "", what) for e, what in refs)))
        del self.entries[idx]
        moved = 0
        for e in self.entries:
            for slots in (e.cond_a, e.cond_b):
                for exprs in slots or ():
                    for x in exprs:
                        if x.kind in self._REF_KINDS and x.ref > idx:
                            x.ref -= 1
                            moved += 1
            for acts in (e.actions, e.alt_actions):
                for a in acts:
                    if a.name == "CALL" and a.entry > idx:
                        a.entry -= 1
                        moved += 1
        self._relayout()
        return moved

    def add_condition(self, key, which, exprs, slot=None):
        """Add expressions to condition `which` ('a'/'b') of an entry. `exprs` is a list of
        Expr (from parse_condition_spec, OR-next bits set within OR-groups, last bit clear).
        slot=None (or == slot count) opens a NEW OR-slot; an existing slot index ANDs the
        new groups onto that slot. Returns the slot index."""
        e = self.entries[self._idx(key)]
        exprs = list(exprs)
        if not exprs:
            raise ValueError("no expressions to add")
        if exprs[-1].op_byte & 0x80:
            raise ValueError("an expression list must end with a clear OR-next bit")
        attr = "cond_a" if which == "a" else "cond_b"
        slots = getattr(e, attr) or []
        if slot is None or slot == len(slots):
            slots.append(exprs)
            slot = len(slots) - 1
        else:
            if not (0 <= slot < len(slots)):
                raise IndexError("cond %s slot %d out of range 0..%d" % (which, slot, len(slots)))
            slots[slot].extend(exprs)
        setattr(e, attr, slots)
        self._relayout()
        return slot

    def remove_condition(self, key, which, slot, expr=None):
        """Remove one expression (expr index) or a whole OR-slot (expr=None) from condition
        `which` of an entry. Removing the last expression of an OR-group closes the group
        on its previous member (its OR-next bit is cleared). Returns the removed objects."""
        e = self.entries[self._idx(key)]
        attr = "cond_a" if which == "a" else "cond_b"
        slots = getattr(e, attr)
        if not slots or not (0 <= slot < len(slots)):
            raise IndexError("entry %d has no cond %s slot %d" % (e.idx, which, slot))
        if expr is None:
            removed = slots.pop(slot)
        else:
            xs = slots[slot]
            if not (0 <= expr < len(xs)):
                raise IndexError("cond %s slot %d has no expr %d" % (which, slot, expr))
            x = xs[expr]
            if not x.or_next and expr > 0 and xs[expr - 1].or_next:
                xs[expr - 1].op_byte &= 0x7F          # previous member now ends the OR-group
            removed = [xs.pop(expr)]
            if not xs:
                slots.pop(slot)
        setattr(e, attr, slots or None)
        self._relayout()
        return removed

    def add_action(self, key, stream, action, index=None):
        """Insert an Action (from parse_action_spec) into an entry's main/alt stream at
        `index` (default: append). Returns the index."""
        e = self.entries[self._idx(key)]
        if stream not in ("main", "alt"):
            raise ValueError("stream must be 'main' or 'alt'")
        self._pack_action(action)                    # validate before mutating
        acts = e.actions if stream == "main" else e.alt_actions
        if index is None or index >= len(acts):
            acts.append(action)
            index = len(acts) - 1
        else:
            acts.insert(index, action)
        self._relayout()
        return index

    def remove_action(self, key, stream, index):
        """Remove action `index` from an entry's main/alt stream; returns it."""
        e = self.entries[self._idx(key)]
        acts = e.actions if stream == "main" else e.alt_actions
        if not (0 <= index < len(acts)):
            raise IndexError("entry %d has no %s action %d" % (e.idx, stream, index))
        removed = acts.pop(index)
        self._relayout()
        return removed

    # -- spec mini-language (what `rf4mod em add / add-cond / add-action` accept) ------
    def entry_id(self, tok):
        """'#12' / '12' -> 12; an emdeb entry name -> its id."""
        tok = str(tok).strip()
        if tok.startswith("#"):
            tok = tok[1:]
        if re.fullmatch(r"\d+", tok):
            return int(tok)
        if tok in self.by_name:
            return self.by_name[tok].idx
        raise ValueError("unknown em entry %r" % (tok,))

    def query_id(self, tok):
        tok = str(tok).strip()
        if re.fullmatch(r"\d+", tok):
            return int(tok)
        for i, (en, _jp) in enumerate(self.names.query_names):
            if en == tok:
                return i
        for i, (en, _jp) in enumerate(self.names.query_names):
            if en.lower() == tok.lower():
                return i
        raise ValueError("unknown query %r (see `rf4mod em queries`)" % (tok,))

    def make_operand(self, tok):
        """Operand from text: `12` / `0x10` literal (u32), `-3` or `s:N` signed literal,
        `q:Hour` / `q:3` / a bare query name (e.g. `Hour`, `Season`) -> query id, a bare
        emdeb variable name (`REG_MAIN_SCENARIO`, `FLG_SUBEV_A`) -> flag ref, or
        `flag@BIT/WIDTH` for a raw flag ref."""
        tok = str(tok).strip()
        if not tok:
            raise ValueError("empty operand")
        if tok.startswith("flag@"):
            off, _, w = tok[5:].partition("/")
            off, w = int(off, 0), int(w or "1", 0)
            return Operand("flag", off, w, 0, nbytes=1 + max(1, (off.bit_length() + 7) // 8))
        if tok.startswith("s:"):
            return Operand("slit", int(tok[2:], 0) & 0xFFFFFFFF)
        if tok.startswith("q:"):
            return Operand("query", self.query_id(tok[2:]))
        if re.fullmatch(r"[+-]?(0x[0-9a-fA-F]+|\d+)", tok):
            v = int(tok, 0)
            if not (-(1 << 31) <= v < (1 << 32)):
                raise ValueError("literal %d out of 32-bit range" % v)
            return Operand("slit" if v < 0 else "lit", v & 0xFFFFFFFF)
        v = self.names.flags.get(tok)
        if v is not None:
            return Operand("flag", v.bit_offset, v.bit_width, 0,
                           nbytes=1 + max(1, (v.bit_offset.bit_length() + 7) // 8))
        try:
            return Operand("query", self.query_id(tok))
        except ValueError:
            pass
        near = ", ".join(x.name for x in self.names.flags.find(tok)[:6])
        raise ValueError("unknown operand %r (not a number, query or emdeb variable%s)"
                         % (tok, ("; did you mean: " + near) if near else ""))

    def _parse_term(self, text):
        t = text.strip()
        if t.startswith("(") and t.endswith(")"):
            t = t[1:-1].strip()
        if t.upper() == "TRUE":
            return Expr(0x00, "true")
        if t.upper() == "FALSE":
            return Expr(0x01, "false")
        m = re.fullmatch(r"(!?)\s*cond([AaBb])\s*\((.+)\)", t)
        if m:
            neg, var, ref = m.group(1), m.group(2).lower(), self.entry_id(m.group(3))
            base = self._REF_BASE[(neg, var)]
            kind = ("not_" if neg else "") + "cond_" + var
            return Expr(base | (1 if ref > 0xFFFF else 0), kind, ref=ref)
        m = re.fullmatch(r"(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)", t)
        if not m:
            raise ValueError("cannot parse condition term %r (expected `a OP b`, TRUE, FALSE "
                             "or [!]condA(entry) / [!]condB(entry))" % (text,))
        lhs, op, rhs = m.group(1), m.group(2), m.group(3)
        if op in ("<", "<="):                    # the VM has no < / <=: swap the operands
            lhs, rhs, op = rhs, lhs, {"<": ">", "<=": ">="}[op]
        o1, o2 = self.make_operand(lhs), self.make_operand(rhs)
        b = self._OP_NIBBLE[op] | (self._TYPE_BITS[o1.kind] << 2) | self._TYPE_BITS[o2.kind]
        return Expr(b, "cmp", cmp=op, op1=o1, op2=o2)

    def parse_condition_spec(self, text):
        """One OR-slot's expression list from text: OR-groups joined by ` AND `, terms inside
        a group joined by ` OR ` (optionally parenthesised), e.g.
        `Hour >= 6 AND (12 > Hour OR FLG_RAINBOW == 1) AND !condA(EV_DATE_APPO)`. Terms: `a OP b`
        (OP in == != > >= < <=; operands per make_operand), TRUE, FALSE, [!]condA/B(entry)."""
        exprs = []
        for group in re.split(r"\s+AND\s+", text.strip()):
            g = group.strip()
            if g.startswith("(") and g.endswith(")"):
                g = g[1:-1].strip()
            terms = re.split(r"\s+OR\s+", g)
            for k, term in enumerate(terms):
                x = self._parse_term(term)
                if k < len(terms) - 1:
                    x.op_byte |= 0x80                # OR with the next expr
                exprs.append(x)
        return exprs

    def parse_action_spec(self, text):
        """An Action from text: `CALL entry`, `T = V`, `T += V`, `T -= V`, `T *= V`, `T /= V`,
        `T %= V`, `T = (V == 0)` (SET_EQ_ZERO), or the explicit `OP T V` with OP one of
        SET/ADD/SUB/MUL_S/MUL_U/DIV_S/DIV_U/MOD_S/MOD_U/MAX_S/MAX_U/MIN_S/MIN_U/SET_EQ_ZERO.
        T = an emdeb variable name / flag@BIT/W (or q:N handle); V per make_operand."""
        t = text.strip()
        m = re.fullmatch(r"CALL\s+(\S+)", t, re.I)
        if m:
            ref = self.entry_id(m.group(1))
            return Action(0x10 if ref > 0xFFFF else 0x00, "CALL", entry=ref)
        m = re.fullmatch(r"([A-Z_]+)\s+(\S+)\s+(.+)", t)
        if m and m.group(1).upper() in self._ACT_NIBBLE:
            name, tgt, val = m.group(1).upper(), m.group(2), m.group(3)
        else:
            m = re.fullmatch(r"(\S+)\s*(\+=|-=|\*=|/=|%=|=)\s*(.+)", t)
            if not m:
                raise ValueError("cannot parse action %r" % (text,))
            tgt, sym, val = m.group(1), m.group(2), m.group(3).strip()
            name = self._ACT_SUGAR[sym]
            mz = re.fullmatch(r"\(\s*(.+?)\s*==\s*0\s*\)", val)
            if name == "SET" and mz:
                name, val = "SET_EQ_ZERO", mz.group(1)
        target, value = self.make_operand(tgt), self.make_operand(val)
        if target.kind not in ("flag", "query"):
            raise ValueError("action target %r must be an emdeb variable (FLG_/REG_ name or "
                             "flag@BIT/W)" % (tgt,))
        return Action(self._ACT_NIBBLE[name], name, target=target, value=value)


def find_em():
    """Locate em.bin next to emdeb.bin in the game bundle."""
    cands = [
        r"C:/Users/arryn/Documents/Bundle/bundleMain/em.bin",
        os.path.join(os.path.dirname(__file__), "..", "..", "..",
                     "Bundle", "bundleMain", "em.bin"),
    ]
    for c in cands:
        if os.path.isfile(c):
            return c
    raise FileNotFoundError("em.bin not found; pass an explicit path to EmScript.load()")
