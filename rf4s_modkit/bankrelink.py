"""
bankrelink.py -- rebuild an rf3.mc bank from a parsed model, recomputing every address.

Every structural script edit goes through here (script.Container._relink: the cutscene
editor, the `rf4mod script` commands): parse the whole bank into a model, let the edit
change the model, and lay the bank out again from scratch, so every code address and
expression offset is recomputed and the edit sits in place -- no code appended after the
pool, no jumps written over statements, no dead copies left behind. Edit results are
reported as pcs in the rebuilt bank (BankModel.pc_of / pc_map).

Older toolkit versions edited by TRAMPOLINING (append [new code][copy of the displaced
statement][JMP back] at the bank's end and overwrite the statement with a JMP there;
"delete" = a JMP over the statement; wider operands / new entry lists appended and
repointed). Such a bank is not in the layout below, so BankModel.parse_any() reads it
with parse_flow() (only what the engine can reach) and fold() moves every appended block
back in place of its JMP; the rebuild is in the compiler layout again and executes the
same (flow_signature() equal for every entry). Verified 2026-09-27: parse_flow + fold on
all 1121 shipped banks folds nothing, keeps every entry's flow signature, and only drops
15,250 bytes of unreachable code; on banks trampolined by the previous toolkit (insert
before / after, nested insert, delete, rewrite, operand repoint, new entry) it folds
exactly the trampolines and every entry's signature is unchanged.

Limits (statically verified in RF4S.exe 2026-09-27, see script.Container._sync_max_bank_size):
a bank is addressed with u16 offsets (Script_VMStep RF4S.exe+0x23EF60 reads the opcode at
buf[LOWORD(pc)] and every target / operand offset with read_u16), so it cannot pass 64 KB;
the engine's per-kind load buffer is sized from header words 4 / 12 / 13 once per session
(MycfBankSlot_Create RF4S.exe+0x23F950) and filled without a bounds check
(MycfBankSlot_LoadBank RF4S.exe+0x23F9C0), so every rebuild raises those words.

Bank layout (all 1121 shipped banks):

    type table   table_slots x {u16 count; u16 list_offset}       (74 slots = 296 B)
    code         statements back to back, even-sized, starting right after the table
    entry lists  per type, {u16 size; u16 event_pc; size x {u8 tag; i32 key}}
    pool         one expression per operand, in the order the code references them;
                 no sharing and no dedup. A single-leaf operand (tags 3/4/5/0x11-0x13)
                 is followed by a 00 byte the engine never reads -- kept for byte-exactness.

Every code address in a bank lives in one of these fields (checked against RF4S.exe):

  * control-flow targets: CALL/JMP, BR_Z/BR_NZ, SWITCH/GE, JMP_RAND, JMP_WEIGHTED,
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
BANK_BYTES = 0x10000                              # = script.BANK_ADDRESS_LIMIT (u16 addressing)


def too_big(n):
    return ("the bank would be %d bytes; a bank is addressed with 16-bit offsets (Script_VMStep "
            "RF4S.exe+0x23EF60), so it cannot pass 64 KB (%d bytes) -- edit in place, or move content "
            "to a scene in a smaller bank" % (n, BANK_BYTES))


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


# ---- FRAME sizing ------------------------------------------------------------------- #
# FRAME N (0xFFF1) sets the frame base to the stack top and reserves N stack words. The
# postfix evaluator (Script_EvalExpressionBytecode RF4S.exe+0x23E1C0) keeps the top of its
# stack in a local and SPILLS the values below it to stack[frame_base + 2*i] (8 bytes = 2
# words each), so an expression of depth d writes 2*(d-1) words there. Script_PrepActionArgs
# (+0x23EE10) evaluates an action's arguments last to first and pushes each (value, kind)
# at the stack top = frame_base + N: an argument evaluated while others are already pushed
# (every one but the last) must not spill past N, or it overwrites them. So a routine needs
# N >= 2*(d-1) for those arguments. Branch conditions push nothing and literals / registers
# (depth 1) never spill. Every shipped routine meets this (the 33,556 without a FRAME need
# none), so the rule changes nothing in a shipped bank.
_DIRECT_LEAVES = (3, 4, 5, 0x11, 0x12, 0x13)          # resolved without the evaluator
_PUSH_SIZES = {0x01: 5, 0x02: 5, 0x06: 3, 0x14: 1, 0x15: 1, 0x16: 1, 0x17: 2, 0x18: 2, 0x19: 3, 0x1A: 3}


def expr_depth(e):
    """Deepest evaluation stack of the expression bytes `e` (0 for a direct leaf)."""
    if not e or e[0] in _DIRECT_LEAVES:
        return 0
    d = mx = 0
    p = 0
    while p < len(e):
        t = e[p]
        if t == 0:
            break
        if t >= 0x80:
            if t - 0x80 not in (0, 1, 2):                 # binary / compound-assign: pop 2 push 1
                d -= 1
            p += 1
        elif 0x07 <= t <= 0x10:                           # reg0..reg9
            d += 1
            p += 1
        elif t in _PUSH_SIZES:
            d += 1
            p += _PUSH_SIZES[t]
        else:
            break
        mx = max(mx, d)
    return mx


def action_frame_need(exprs):
    """Stack words an action with argument expressions `exprs` needs reserved by FRAME."""
    if len(exprs) < 2:
        return 0
    return max([0] + [2 * (expr_depth(e) - 1) for e in exprs[:-1] if expr_depth(e) >= 2])


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
    """One statement: its bytes with the address fields zeroed, plus what they point at.
    `old_pc` is the statement's KEY: its pc in the bank as parsed, or a number >= 0x10000
    for a statement an edit added. Targets hold keys, so build() can relocate them."""
    __slots__ = ("old_pc", "raw", "targets", "exprs", "fields", "op", "falls")

    def __init__(self, old_pc, raw, op, flds, targets, exprs, falls=True):
        self.old_pc = old_pc
        self.raw = bytearray(raw)
        self.op = op
        self.fields = flds                        # [(offset, kind)]
        self.targets = targets                    # keys, one per 'pc' field
        self.exprs = exprs                        # expression bytes, one per 'expr' field
        self.falls = falls                        # execution can continue with the next statement


class Raw:
    """Bytes in the code region that do not decode (dead data); carried verbatim."""
    __slots__ = ("old_pc", "raw")

    def __init__(self, old_pc, raw):
        self.old_pc = old_pc
        self.raw = bytes(raw)


def _falls(st):
    return bool(st.falls_through and not st.terminator)


class BankModel:
    """A bank as statements + entry lists; edits change the model, build() lays it out.

    parse() is the byte-exact reading of a bank in the compiler's layout (every shipped
    bank). A bank an earlier toolkit version edited by TRAMPOLINING (code appended after
    the expression pool and reached by a JMP written over the original statement; skipped
    statements overwritten by a JMP over themselves; operands and entry lists appended and
    repointed) is not in that layout: parse_any() then falls back to parse_flow(), which
    reads only the code the engine can reach (every entry's scene, plus the unregistered
    code the gap-fill scene discovery finds), and fold() moves each trampolined block back
    in place of its JMP. The rebuilt bank is in the compiler layout again."""

    FIRST_NEW_KEY = 0x10000

    def __init__(self):
        self.table = bytearray()                  # raw table words (offsets re-patched)
        self.slots = {}                           # type -> (count, list key)
        self.code = []                            # [Stmt | Raw]
        self.lists = []                           # [(list key, [(size_word, event key, subs bytes)])]
        self.src = b""                            # the bank bytes parsed
        self.mode = "canonical"                   # 'canonical' | 'flow' (see parse_any)
        self.folded = 0                           # trampolines / skip jumps folded back
        self.redirects = {}                       # key -> key its references were moved to
        self.newpc = None                         # key -> pc, set by build()
        self._next_key = self.FIRST_NEW_KEY
        self.data_start = 0x10000                 # flow parse: lowest operand / list offset

    # ---- parse ------------------------------------------------------------------ #
    @classmethod
    def parse(cls, bank):
        d = bytes(bank.data)
        n = len(d)
        m = cls()
        m.src = d
        tt = bank.type_table_full()
        tend = 4 * bank.table_slots
        m.table = bytearray(d[:tend])
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
        reach = None                              # flow-reached pcs, only needed past bad bytes
        pool_refs = []
        pc = tend
        while pc < code_end:
            st = script.decode_statement(d, pc)
            if st is None or pc + st.size > code_end:
                if reach is None:                 # anchors to resync after bytes that do not decode
                    reach = set()
                    for sc in script.disassemble_bank(bank):
                        reach |= set(sc.stmts)
                nxt = min((p for p in reach if pc < p < code_end), default=code_end)
                m.code.append(Raw(pc, d[pc:nxt]))
                pc = nxt
                continue
            flds = fields(st)
            tg, ex = [], []
            for fo, kind in flds:
                v = struct.unpack_from("<H", d, pc + fo)[0]
                (tg if kind == "pc" else ex).append(v)
            m.code.append(Stmt(pc, d[pc:pc + st.size], st.op, flds, tg, ex, _falls(st)))
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

    @classmethod
    def parse_flow(cls, bank):
        """Read a bank that is NOT in the compiler layout (see the class docstring): the
        statements the engine can reach, in pc order; operands and entry lists wherever
        they are. Bytes nothing reaches (a trampolined statement's leftover argument words,
        old entry lists, orphaned operands) are dropped."""
        d = bytes(bank.data)
        n = len(d)
        m = cls()
        m.src = d
        m.mode = "flow"
        tt = bank.type_table_full()
        tend = 4 * bank.table_slots
        m.table = bytearray(d[:tend])
        m.slots = dict(tt)
        lists = {}
        for t, (cnt, off) in tt.items():
            recs = bank.entries(off, cnt)
            if len(recs) >= len(lists.get(off, ())):
                lists[off] = recs
        for off in sorted(lists):
            m.lists.append((off, [(size, eid, d[eo + 4:eo + 4 + 5 * size]) for eo, size, eid in lists[off]]))
        stmts = {}                                    # pc -> decoded statement

        def span_ok(sts):
            for pc, st in sts.items():
                for q in range(pc + 1, pc + st.size):
                    if q in stmts:
                        return False
                for q in range(max(tend, pc - 64), pc):
                    o = stmts.get(q)
                    if o is not None and q + o.size > pc:
                        return False
                if pc < tend or pc + st.size > n:
                    return False
                for fo, kind in fields(st):
                    if kind == "expr":
                        v = struct.unpack_from("<H", d, pc + fo)[0]
                        try:
                            expr_size(d, v)
                        except Exception:  # noqa: BLE001 - any undecodable operand
                            return False
            return True

        scenes = script.disassemble_bank(bank)
        for sc in scenes:                             # registered scenes first: they must decode
            if sc.action_type < 0:
                continue
            if not sc.ok:
                raise RelinkError("bank %d: the scene at 0x%04x does not decode (%s); cannot rebuild"
                                  % (bank.index, sc.entry_pc, sc.error))
            new = {pc: st for pc, st in sc.stmts.items() if pc not in stmts}
            if not span_ok(new):
                raise RelinkError("bank %d: statements of the scene at 0x%04x overlap other code"
                                  % (bank.index, sc.entry_pc))
            stmts.update(new)
        for sc in scenes:                             # unregistered code: keep what is sound
            if sc.action_type >= 0 or not sc.ok:
                continue
            new = {pc: st for pc, st in sc.stmts.items() if pc not in stmts}
            if span_ok(new):
                stmts.update(new)
        data = set(lists)                             # where the data area starts: see fold()
        for pc in sorted(stmts):
            st = stmts[pc]
            flds = fields(st)
            tg, ex = [], []
            for fo, kind in flds:
                v = struct.unpack_from("<H", d, pc + fo)[0]
                if kind == "pc":
                    tg.append(v)
                else:
                    ex.append(d[v:v + expr_size(d, v)])
                    data.add(v)
            m.code.append(Stmt(pc, d[pc:pc + st.size], st.op, flds, tg, ex, _falls(st)))
        m.data_start = min(data, default=n)
        return m

    @classmethod
    def parse_any(cls, bank):
        """parse() when the bank is in the compiler layout, else parse_flow(); then fold()
        whatever an earlier toolkit version trampolined. `mode` / `folded` say what
        happened."""
        try:
            m = cls.parse(bank)
        except RelinkError:
            m = cls.parse_flow(bank)
        m.fold()
        return m

    # ---- keys, references, reachability ----------------------------------------- #
    def new_key(self):
        k = self._next_key
        self._next_key += 1
        return k

    def positions(self):
        return {s.old_pc: i for i, s in enumerate(self.code)}

    def stmt(self, key):
        for s in self.code:
            if s.old_pc == key:
                return s if isinstance(s, Stmt) else None
        return None

    def redirect(self, old, new):
        """Every code reference to `old` (branch targets, entry event pcs) now goes to `new`."""
        for s in self.code:
            if isinstance(s, Stmt) and old in s.targets:
                s.targets = [new if t == old else t for t in s.targets]
        self.lists = [(k, [(sz, new if e == old else e, b) for sz, e, b in recs]) for k, recs in self.lists]
        self.redirects[old] = new

    def ref_count(self, key):
        n = sum(s.targets.count(key) for s in self.code if isinstance(s, Stmt))
        return n + sum(1 for _k, recs in self.lists for _s, e, _b in recs if e == key)

    def entry_keys(self):
        return [e for _k, recs in self.lists for _s, e, _b in recs]

    def reach(self, roots):
        """Keys of the statements execution can reach from `roots` (targets + fall-through)."""
        pos = self.positions()
        seen = set()
        stack = list(roots)
        while stack:
            k = stack.pop()
            if k in seen or k not in pos:
                continue
            s = self.code[pos[k]]
            if not isinstance(s, Stmt):
                continue
            seen.add(k)
            stack += s.targets
            i = pos[k] + 1
            if s.falls and i < len(self.code):
                stack.append(self.code[i].old_pc)
        return seen

    # ---- FRAME sizing ------------------------------------------------------------------ #
    def routine_roots(self):
        """Keys where a routine starts: every entry's scene and every CALL target."""
        roots = set(self.entry_keys())
        for s in self.code:
            if isinstance(s, Stmt) and s.op == 0xFFFE:
                roots.update(t for t in s.targets if t is not None)
        return roots

    def frame_need(self, root):
        """Stack words the routine starting at `root` needs from its FRAME (see
        action_frame_need; CALLed routines have their own frame)."""
        pos = self.positions()
        seen, todo, need = set(), [root], 0
        while todo:
            k = todo.pop()
            if k in seen or k not in pos:
                continue
            s = self.code[pos[k]]
            if not isinstance(s, Stmt):
                continue
            seen.add(k)
            if s.op < 0xFFF0:
                need = max(need, action_frame_need(s.exprs))
            if s.op != 0xFFFE:
                todo += [t for t in s.targets if t is not None]
            i = pos[k] + 1
            if s.falls and i < len(self.code):
                todo.append(self.code[i].old_pc)
        return need

    def ensure_frames(self):
        """Give every routine the FRAME its code needs: a too-small FRAME at its start is
        raised in place, a routine without one gets `FRAME n` inserted at its start (only
        where nothing falls into it -- a FRAME run mid-scene would move the frame base and
        break the final RET). Returns [(root key, old size | None, new size)]."""
        out = []
        pos = self.positions()
        for root in sorted(self.routine_roots()):
            need = self.frame_need(root)
            if not need or root not in pos:
                continue
            i = pos[root]
            s = self.code[i]
            if not isinstance(s, Stmt):
                continue
            if s.op == 0xFFF1:
                have = struct.unpack_from("<H", s.raw, 2)[0]
                if have < need:
                    struct.pack_into("<H", s.raw, 2, need)
                    out.append((root, have, need))
                continue
            prev = self.code[i - 1] if i > 0 else None
            if isinstance(prev, Stmt) and prev.falls:
                raise RelinkError("the code at 0x%04x needs FRAME %d (an argument there is an "
                                  "expression evaluated while other arguments are on the stack), "
                                  "but the statement before it falls into it, so a FRAME cannot "
                                  "be put there -- write FRAME %d at the start of the scene or "
                                  "subroutine it belongs to" % (root, need, need))
            self.insert_before(root, "FRAME %d" % need)
            out.append((root, None, need))
            pos = self.positions()
        return out

    # ---- undoing trampolines ------------------------------------------------------ #
    def fold(self):
        """Put trampolined code back in place (idempotent; returns the number of folds).

        * JMP followed by undecodable bytes and targeting the end of them (a statement an
          earlier toolkit 'deleted' by overwriting it with a jump over itself): both go.
        * In a flow-parsed bank only: a JMP J whose target T lies past the start of the
          data area (the lowest operand / entry-list offset: the old editor appended at the
          bank's end, after the pool), is referenced by J alone and is entered by no
          fall-through: the run of statements from T up to the first one that does not
          fall through replaces J, and a final JMP to the statement now following it is
          dropped. A JMP to the next statement over bytes that are not whole statements (a
          skipped statement's leftover argument words) is dropped too. Shipped JMPs never
          match either rule (checked on every shipped bank by the selftest).
        Nothing here changes what the engine executes; it only restores the layout."""
        n0 = self.folded
        i = 0
        while i + 1 < len(self.code):
            s, r = self.code[i], self.code[i + 1]
            if (isinstance(s, Stmt) and s.op == 0xFFFA and isinstance(r, Raw)
                    and s.targets[0] == r.old_pc + len(r.raw)
                    and i + 2 < len(self.code) and self.code[i + 2].old_pc == s.targets[0]):
                del self.code[i:i + 2]
                self.redirect(s.old_pc, s.targets[0])
                self.folded += 1
                continue
            i += 1
        if self.mode != "flow":
            return self.folded - n0
        changed = True
        while changed:
            changed = False
            pos = self.positions()
            for i, s in enumerate(self.code):
                if not (isinstance(s, Stmt) and s.op == 0xFFFA):
                    continue
                t = s.targets[0]
                j = pos.get(t)
                if j is None:
                    continue
                if j == i + 1 and t > s.old_pc + 4 and not self._whole_statements(s.old_pc + 4, t):
                    del self.code[i]
                    self.redirect(s.old_pc, t)
                    self.folded += 1
                    changed = True
                    break
                prev = self.code[j - 1]
                if (j <= i or t < self.data_start or self.ref_count(t) != 1
                        or (isinstance(prev, Stmt) and prev.falls)):
                    continue
                k = j
                while k < len(self.code) and isinstance(self.code[k], Stmt) and self.code[k].falls:
                    k += 1
                if k >= len(self.code) or not isinstance(self.code[k], Stmt):
                    continue
                chain = self.code[j:k + 1]
                del self.code[j:k + 1]
                self.code[i:i + 1] = chain
                self.redirect(s.old_pc, t)
                last = chain[-1]
                nxt = i + len(chain)
                if (last.op == 0xFFFA and nxt < len(self.code) and last.targets[0] == self.code[nxt].old_pc
                        and self.ref_count(last.old_pc) == 0):
                    del self.code[nxt - 1]
                    self.redirect(last.old_pc, last.targets[0])
                self.folded += 1
                changed = True
                break
        return self.folded - n0

    def _whole_statements(self, a, b):
        """True when src[a:b] decodes as whole statements (shipped code jumping over a dead
        RET, say) rather than a statement's leftover argument bytes."""
        while a < b:
            st = script.decode_statement(self.src, a)
            if st is None or a + st.size > b:
                return False
            a += st.size
        return a == b

    # ---- statements from listing text --------------------------------------------- #
    def listing_items(self, text, resolver=None, tail=None, terminate=None, strict=True):
        """Statements for listing `text` (scriptasm language), keyed with new keys.

        Labels in the text resolve among these statements; an absolute target `0xPC` must
        be a statement of this bank (its key); an `@0xOFF` operand copies the expression
        at OFF. Labels at the very end bind to `tail` (the statement that follows the new
        code) -- or, when `terminate` is given, to an appended terminator: 'end' = END,
        a key = JMP to it; that terminator is added whenever the text can fall off its end."""
        from . import scriptasm
        asm = scriptasm.Assembler(resolver, strict=strict)
        sts, labels, trailing = asm.parse(text)
        keys = {id(st): self.new_key() for st in sts}
        falls_last = True
        if sts:
            d0 = script.decode_statement(bytes(sts[-1].code), 0)
            falls_last = sts[-1].text.startswith(".raw") or d0 is None or _falls(d0)
        term = None
        if terminate is not None and (falls_last or trailing):
            term = scriptasm._Stmt(0, "<terminator>")
            if terminate == "end":
                term.code += b"\xff\xff"
            else:
                term.code += b"\xfa\xff\x00\x00"
                term.fixups.append((2, "key", terminate))
            keys[id(term)] = self.new_key()
            sts = sts + [term]
            for lb in trailing:
                labels[lb] = term
            trailing = []
        valid = {s.old_pc for s in self.code if isinstance(s, Stmt)}
        out = []
        for st in sts:
            key = keys[id(st)]
            raw = bytes(st.code)
            where = "line %d" % st.line_no if st is not term else "the terminator"
            if st.text.startswith(".raw"):
                out += self._raw_items(raw, key, valid)
                continue
            dec = script.decode_statement(raw, 0)
            if dec is None or dec.size != len(raw):
                raise RelinkError("%s: %r does not assemble to one statement" % (where, st.text))
            flds = fields(dec)
            fix = sorted(st.fixups, key=lambda f: f[0])
            if [f[0] for f in fix] != [f[0] for f in flds]:
                raise RelinkError("%s: operand layout of %r not understood" % (where, st.text))
            tg, ex = [], []
            for (fo, kind, payload), (_fo, fk) in zip(fix, flds):
                if fk == "pc":
                    if kind == "key":
                        tg.append(payload)
                    elif kind == "label":
                        if payload in labels:
                            tg.append(keys[id(labels[payload])])
                        elif payload in trailing:
                            if tail is None:
                                raise RelinkError("%s: label %r is at the end of the listing with "
                                                  "nothing after it" % (where, payload))
                            tg.append(tail)
                        else:
                            raise RelinkError("%s: undefined label %r" % (where, payload))
                    elif kind == "abs":
                        v = int(payload)
                        while v not in valid and v in self.redirects:
                            v = self.redirects[v]         # a statement fold() replaced
                        if v not in valid:
                            raise RelinkError("%s: 0x%04x is not a statement start in this bank"
                                              % (where, v))
                        tg.append(v)
                    else:
                        raise RelinkError("%s: expected a code target" % where)
                else:
                    if kind == "expr":
                        ex.append(bytes(payload))
                    elif kind == "abs":
                        v = int(payload)
                        try:
                            ex.append(self.src[v:v + expr_size(self.src, v)])
                        except Exception:  # noqa: BLE001 - IndexError / RelinkError
                            raise RelinkError("%s: @0x%04x is not an expression in this bank" % (where, v))
                    else:
                        raise RelinkError("%s: expected an operand" % where)
            out.append(Stmt(key, raw, dec.op, flds, tg, ex, _falls(dec)))
        return out

    def _raw_items(self, raw, key, valid):
        """A `.raw` line: when its bytes are whole statements, they become statements whose
        address fields are read as this bank's pcs / operand offsets (so they relink like
        any other); otherwise the bytes are carried verbatim (they must not hold addresses)."""
        out, pc, k = [], 0, key
        while pc < len(raw):
            st = script.decode_statement(raw, pc)
            if st is None or pc + st.size > len(raw):
                return [Raw(key, raw)]
            flds = fields(st)
            tg, ex = [], []
            for fo, kind in flds:
                v = struct.unpack_from("<H", raw, pc + fo)[0]
                if kind == "pc":
                    v = self.resolve(v)
                    if v not in valid:
                        return [Raw(key, raw)]
                    tg.append(v)
                else:
                    try:
                        ex.append(self.src[v:v + expr_size(self.src, v)])
                    except Exception:  # noqa: BLE001 - not an operand of this bank
                        return [Raw(key, raw)]
            out.append(Stmt(k, raw[pc:pc + st.size], st.op, flds, tg, ex, _falls(st)))
            pc += st.size
            k = self.new_key()
        return out

    # ---- edits ------------------------------------------------------------------------ #
    def resolve(self, key):
        """`key`, or the key its references were redirected to (a statement fold() or an
        edit replaced)."""
        seen = set()
        while key in self.redirects and key not in seen:
            seen.add(key)
            key = self.redirects[key]
        return key

    def _stmt_at(self, key, what="statement"):
        key = self.resolve(key)
        pos = self.positions()
        i = pos.get(key)
        if i is None or not isinstance(self.code[i], Stmt):
            raise RelinkError("no %s at 0x%04x" % (what, key))
        return i, self.code[i]

    def insert_before(self, key, text, resolver=None, strict=True):
        """New statements run first on every path that reached `key` (its fall-through
        predecessor, every branch / call / entry to it). Returns the first new key."""
        i, s = self._stmt_at(key)
        key = s.old_pc
        items = self.listing_items(text, resolver, tail=key, strict=strict)
        if not items:
            return None
        self.redirect(key, items[0].old_pc)
        self.code[i:i] = items
        return items[0].old_pc

    def insert_after(self, key, text, resolver=None, strict=True):
        """New statements run right after `key` (which must fall through); branches to the
        statement after it still skip them. Returns the first new key."""
        i, s = self._stmt_at(key)
        if not s.falls or i + 1 >= len(self.code) or not isinstance(self.code[i + 1], Stmt):
            raise RelinkError("the statement at 0x%04x never falls through, so statements inserted "
                              "after it would never run -- insert before it, or at the branch target" % key)
        items = self.listing_items(text, resolver, tail=self.code[i + 1].old_pc, strict=strict)
        if not items:
            return None
        self.code[i + 1:i + 1] = items
        return items[0].old_pc

    def replace(self, key, text, resolver=None, strict=True):
        """The statement `key` (which must fall through) becomes the statements of `text`:
        every path that reached it -- the statement above, every branch / call / entry --
        runs the new ones, which fall through to the statement that followed it. Returns
        the first new key."""
        i, s = self._stmt_at(key)
        if not s.falls or i + 1 >= len(self.code) or not isinstance(self.code[i + 1], Stmt):
            raise RelinkError("the statement at 0x%04x never falls through; only a statement "
                              "that continues to the next one can be replaced here" % key)
        items = self.listing_items(text, resolver, tail=self.code[i + 1].old_pc, strict=strict)
        if not items:
            raise RelinkError("nothing to replace 0x%04x with (empty listing)" % key)
        self.code[i:i + 1] = items
        self.redirect(s.old_pc, items[0].old_pc)
        return items[0].old_pc

    def delete(self, key):
        """Remove the statement `key` (which must fall through); what pointed at it now
        points at the statement after it."""
        i, s = self._stmt_at(key)
        if not s.falls or i + 1 >= len(self.code) or not isinstance(self.code[i + 1], Stmt):
            raise RelinkError("the statement at 0x%04x never falls through; deleting it would run "
                              "whatever follows it -- retarget it (set_branch_target) instead" % key)
        nxt = self.code[i + 1].old_pc
        del self.code[i]
        self.redirect(s.old_pc, nxt)

    def replace_scene(self, entry, text, resolver=None, strict=True):
        """The scene at `entry` plays `text` instead: the new body goes where the old entry
        was, everything that pointed at the entry points at the new body, and the old
        statements nothing reaches any more are dropped (statements the old body shared
        with other scenes stay). Returns the new body's first key."""
        i, s = self._stmt_at(entry, "scene entry")
        entry = s.old_pc
        old = self.reach([entry])
        items = self.listing_items(text, resolver, terminate="end", strict=strict)
        if not items:
            raise RelinkError("the new scene body is empty")
        self.redirect(entry, items[0].old_pc)
        self.code[i:i] = items
        self.prune(old)
        return items[0].old_pc

    def prune(self, candidates):
        """Drop the statements in `candidates` that nothing reaches any more: roots are the
        entry lists plus the targets / fall-through of every statement outside `candidates`
        (dead code elsewhere keeps what it points at -- conservative)."""
        roots = set(self.entry_keys())
        for i, s in enumerate(self.code):
            if isinstance(s, Stmt) and s.old_pc not in candidates:
                roots |= set(s.targets)
                if s.falls and i + 1 < len(self.code):
                    roots.add(self.code[i + 1].old_pc)
        live = self.reach(roots)
        gone = [s.old_pc for s in self.code if s.old_pc in candidates and s.old_pc not in live]
        if gone:
            g = set(gone)
            self.code = [s for s in self.code if s.old_pc not in g]
        return gone

    def append_code(self, text, resolver=None, fallthrough_to=None, strict=True):
        """Assemble `text` after the last statement (it ends with END, or a JMP to
        `fallthrough_to`). Returns its first key."""
        if self.code and isinstance(self.code[-1], Stmt) and self.code[-1].falls:
            raise RelinkError("the bank's last statement falls through; cannot append after it")
        items = self.listing_items(text, resolver, terminate="end" if fallthrough_to is None
                                   else self._stmt_at(fallthrough_to)[1].old_pc, strict=strict)
        if not items:
            raise RelinkError("nothing to assemble")
        self.code += items
        return items[0].old_pc

    def set_operand(self, key, index, expr):
        """Operand `index` of statement `key` (action args in order, then control operands)
        becomes the expression bytes `expr` (terminator included)."""
        _i, s = self._stmt_at(key)
        if not 0 <= index < len(s.exprs):
            raise RelinkError("statement at 0x%04x has %d operand(s); no operand %d" % (key, len(s.exprs), index))
        s.exprs[index] = bytes(expr)

    def records(self, type_id):
        """[(event key, subs bytes)] of `type_id`'s entry list (empty when unused)."""
        if type_id not in self.slots:
            return []
        cnt, lk = self.slots[type_id]
        recs = next(r for k, r in self.lists if k == lk)
        return [(e, b) for _s, e, b in recs[:cnt]]

    def set_records(self, type_id, records):
        """Replace `type_id`'s entry list with `records` [(event key, subs bytes)]. Lists no
        slot uses any more are dropped; a list shared with another type is left to it."""
        if not 0 <= type_id < len(self.table) // 4:
            raise RelinkError("type %d is past the bank's %d-slot table" % (type_id, len(self.table) // 4))
        old = self.slots.get(type_id)
        recs = [(len(b) // 5, self.resolve(e), bytes(b)) for e, b in records]
        if not recs:
            self.slots.pop(type_id, None)
            self.table[4 * type_id:4 * type_id + 4] = b"\0\0\0\0"
        else:
            key = self.new_key()
            at = len(self.lists)
            if old is not None:
                at = next(i for i, (k, _r) in enumerate(self.lists) if k == old[1]) + 1
            self.lists.insert(at, (key, recs))
            self.slots[type_id] = (len(recs), key)
        used = {k for _c, k in self.slots.values()}
        self.lists = [(k, r) for k, r in self.lists if k in used]

    # ---- build ------------------------------------------------------------------ #
    def build(self):
        out = bytearray(self.table)
        self.newpc = {}
        if not self.lists and not self.code:
            return bytes(out)
        newpc = self.newpc
        pc = len(out)
        for s in self.code:
            newpc[s.old_pc] = pc
            pc += len(s.raw)
        newlist = {}
        lp = pc
        for off, recs in self.lists:
            newlist[off] = lp
            lp += sum(4 + len(b) for _s, _e, b in recs)
        total = lp + sum(len(x) for s in self.code if isinstance(s, Stmt) for x in s.exprs)
        if total > BANK_BYTES:
            raise RelinkError(too_big(total))
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
                struct.pack_into("<H", raw, fo, v)
            out += raw
        for off, recs in self.lists:
            for size, eid, subs in recs:
                out += struct.pack("<HH", size, pc_of(eid, "event pc"))
                out += subs
        out += pool
        for t, (cnt, off) in self.slots.items():
            struct.pack_into("<HH", out, 4 * t, cnt, newlist[off])
        return bytes(out)

    def pc_of(self, key):
        """A key's pc in the last build(), following redirects (a removed or replaced
        statement maps to what its references now use); None when it is gone."""
        return self.newpc.get(self.resolve(key)) if self.newpc is not None else None

    def pc_map(self):
        """{pc as parsed: pc after build()} for the parsed statements (see pc_of)."""
        keys = {s.old_pc for s in self.code} | set(self.redirects)
        out = {}
        for k in keys:
            if k < self.FIRST_NEW_KEY:
                v = self.pc_of(k)
                if v is not None:
                    out[k] = v
        return out


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


def bank_listing(bank, resolver=None, with_pcs=False):
    """The whole bank as text (see above); assemble_bank(text) rebuilds it. with_pcs=True
    returns (text, pcs): pcs[i] is the statement pc of output line i (None for directives,
    labels and entry lists)."""
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
    pcs = []
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
        pcs += [None] * (len(out) - len(pcs))
        if isinstance(s, Raw):
            out.append(".raw %s" % s.raw.hex())
            continue
        st = script.decode_statement(d, s.old_pc)
        ex = iter(zip([v for (fo, k) in s.fields if k == "expr" for v in [struct.unpack_from("<H", d, s.old_pc + fo)[0]]], s.exprs))
        tg = [lab(t) for t in s.targets]
        op = st.op
        if op < 0xFFF0:
            args = [_operand_text(asm, d, o, w, op, i) for i, (o, w) in enumerate(ex)]
            line = scriptasm.action_line(op, args)
        elif op == 0xFFFF:
            line = "RET"
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
            line = "JMP_RAND %s" % ", ".join(tg)
        elif op == 0xFFF2:
            ws = [_paren(_operand_text(asm, d, o, w)) for o, w in ex]
            line = "JMP_WEIGHTED " + ", ".join("%s -> %s" % (w, t) for w, t in zip(ws, tg))
        elif op == 0xFFF4:
            line = "PROMPT_CHOICE CANCEL -> %s" % tg[0] + "".join(
                ", #%d -> %s" % (it, t) for it, t in zip(st.items, tg[1:]))
        elif op == 0xFFF5:
            line = "PROMPT_CHOICE_FORCED " + ", ".join("#%d -> %s" % (it, t) for it, t in zip(st.items, tg))
        else:
            raise RelinkError("no listing form for 0x%04x" % op)
        out.append("    " + line)
        pcs.append(s.old_pc)
    for off, recs in m.lists:
        out.append("list_%04x:" % off)
        for size, eid, subs in recs:
            keys = " ".join("%d:%d" % (subs[5 * k], struct.unpack_from("<i", subs, 5 * k + 1)[0])
                            for k in range(size))
            out.append(".entry %s%s" % (lab(eid), (" " + keys) if keys else ""))
    text = "\n".join(out) + "\n"
    if with_pcs:
        return text, pcs + [None] * (len(out) - len(pcs))
    return text


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


def flow_signature(bank, entry_pc):
    """What the scene at `entry_pc` executes, independent of layout: statements in
    depth-first order from the entry, unconditional JMPs followed transparently, each as
    (opcode, operand expression bytes, dialog id / choice items / FRAME count, successor
    ordinals). Two banks whose scenes have equal signatures run the same code -- the check
    that a rebuild (or folding an old trampoline) changed nothing but addresses."""
    d = bytes(bank.data)
    order, sig, stack = {}, [], []

    def through(pc):
        seen = set()
        while pc not in seen:
            seen.add(pc)
            st = script.decode_statement(d, pc)
            if st is None or st.mnem != "JMP":
                return pc
            pc = st.code_targets[0]
        return pc

    def visit(pc):
        pc = through(pc)
        if pc not in order:
            order[pc] = len(order)
            stack.append(pc)
        return order[pc]

    visit(entry_pc)
    i = 0
    while i < len(stack):
        pc = stack[i]
        i += 1
        st = script.decode_statement(d, pc)
        if st is None:
            sig.append(("?", pc))
            continue
        ex = []
        for fo, kind in fields(st):
            if kind == "expr":
                v = struct.unpack_from("<H", d, pc + fo)[0]
                ex.append(d[v:v + script.disasm_expr(d, v)[1]])
        succ = [visit(t) for t in st.code_targets]
        if st.falls_through and not st.terminator:
            succ.append(visit(pc + st.size))
        sig.append((st.op, tuple(ex), st.dialog_id, tuple(st.items or ()), tuple(succ)))
    return sig
