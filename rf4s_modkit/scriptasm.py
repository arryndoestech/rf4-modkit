r"""scriptasm.py -- assembler for RF4S Script-VM cutscene bytecode (rf3.mc banks).

`script.py` decodes rf3.mc; this module is the inverse: it turns a readable listing
(the same shape `script.scene_listing` prints) back into bytecode, and it compiles
the RPN expression language, so a modder can author whole scene bodies -- branches,
flag writes, choices, calls -- instead of only literal-argument beats.

Engine ground truth (IDB, RF4S.exe; all verified 2026-09-19):

* `Script_VMStep` (+0x23EF60) executes one statement per call. Control opcodes
  (> 0xFFF0) are inline: END 0xFFFF (the real return; `Script_Opcode_FFFF_EndAndCleanup`
  +0x23EBA0), FRAME 0xFFF1 `[op][n]` (frame setup: reserves n operand slots), CALL 0xFFFE
  `[op][pc]`, BR_END 0xFFFD `[op][expr]`, DIALOG 0xFFFC `[op][line:u32]`, EVAL 0xFFFB
  `[op][expr]` (just evaluates the expression -- the assignment operator inside it does
  the store), JMP 0xFFFA, BR_NZ 0xFFF9 / BR_Z 0xFFF8 `[op][expr][pc]`, SWITCH 0xFFF7 /
  SWITCH_CLAMP 0xFFF6 `[op][expr][n][n pcs]`, PROMPT_CHOICE_FORCED 0xFFF5 `[op][n][n pcs]
  [n u32 items]`, PROMPT_CHOICE 0xFFF4 `[op][n][n+1 pcs][n u32 items]` (pc[0] = the
  CANCEL slot, taken only for a negative pick -- the UI's cancel key instead moves the
  cursor to the last option, so shipped menus repeat the last target there; the listing
  writes `CANCEL -> x` only when it differs from that, and leaving it out assembles the
  last option's target; at most
  `script.MAX_CHOICE_OPTIONS` = 128 options, 4 rows on screen; see script.choice_problems),
  JMP_RAND 0xFFF3 `[op][n][n pcs]`, JMP_WEIGHTED 0xFFF2 `[op][n][n pcs][n weight exprs]`.
  Everything <= 0xFFF0 is an action: `[op][argc][argc x u16 expr offset]`, and
  `Script_PrepActionArgs` (+0x23EE10) evaluates each offset with
  `Script_EvalExpressionOrVar` and pushes (value, kind) pairs.
* `Script_EvalExpressionOrVar` (+0x23EA10): the first byte of an operand decides. Tags
  1, 2, 6, 7..0x10, 0x14..0x1A enter the RPN evaluator (kind 0); tag 3 = a u32 constant
  handed over with kind 2, written tag3(N), 4 = the same with kind 3, written tag4(N). No
  variable is read. In a character slot tag3 is an actor id and in a location slot tag4 is a
  map id: actor(Name) / map(MAP_NAME) assemble to the same bytes, and the listing shows them
  in the statement's comment -- handlers only read the value, see script.actor_leaf_text --
  5 = u16 literal (kind 7), 0x11 null,
  0x12 zero, 0x13 self (kinds 4/5/6). Those "leaf" forms have no terminator.
* `Script_EvalExpressionBytecode` (+0x23E1C0): postfix stream, 0x00 terminates. Pushes:
  0x01 int32, 0x02 packed game-flag variable (u32: bit_offset | (width-1) << 12 with the
  vanilla MYCF header masks 0xFFFE0FFF / 0x0000F000 / 0x00010000; the whole shipped
  corpus never sets the sign bit), 0x06 varArray[u16], 0x07..0x10 reg0..reg9, 0x14 0,
  0x15 -1, 0x16 1, 0x17 u8, 0x18 s8, 0x19 u16, 0x1A s16. Operators 0x80+n: 1 neg,
  2 not, 3 * 4 / 5 % 6 + 7 - 8 < 9 > 10 <= 11 >= 12 == 13 != 14 && 15 ||, and
  16..23 the compound assignments = *= /= %= += -= &&= ||= which write the result back
  through `Script_StackSlot_StoreInt32Back` (+0x23E0A0) into the LEFT operand: a packed
  variable (game flag), a varArray slot or a register. The first-pushed operand is the
  left one (`a - b`, `a < b`).

The listing language (one statement per line, `;` comments, labels `name:`):

    L0:                                  ; label on its own line or before a statement
        FRAME 2
        SetSpeaker(Nancy, Left, 3, 0)    ; action: name(args) -- mnemonic | technical name | opN
        DIALOG #8709
        BR_Z (REG_WIFE_ID == 11) -> L1   ; condition in parentheses, target label or 0xPC
        EVAL (FLG_EV_DONE = 1)          ; write a game flag
        GivePlayerItem(258, reg0 + 1, 0) ; args: int, expression, name, regN, arr[N], @0xOFF
        CALL 0x1234                      ; absolute targets address existing code in the bank
        PROMPT_CHOICE #123 -> L3, #124 -> L4   ; cancel = the last option (CANCEL -> x optional)
        JMP_WEIGHTED (3) -> L1, (1) -> L2
        SWITCH (reg1) -> L1, L2, L3
        JMP_RAND L1, L2, L3
    L1:
        END

Actions are always written `Name(arg, ...)` (`Name()` without arguments); control
statements are keywords, with the condition or value in parentheses and targets after `->`
(the plain `JMP`, `CALL` and `JMP_RAND` list theirs directly). The assembler also reads an
action written without the call brackets (`Name 1, 2`).

Addresses printed by the disassembler (`0123:` after the label) are ignored, so a
listing can be pasted back verbatim. `.raw <hex>` emits bytes verbatim (when they are
whole statements, an rf3.mc edit relinks their addresses like any other statement's --
bankrelink.BankModel.listing_items).
"""
from __future__ import annotations

import re
import struct
from collections import OrderedDict

try:
    from . import script
    from . import opcode_meta as meta
except ImportError:                                   # loaded as loose modules
    import script
    import opcode_meta as meta


class AsmError(script.ScriptError):
    """Assembly / expression-compile error (a ScriptError subclass)."""


# ---- expression compiler ----------------------------------------------------------------
_BIN_OPS = {"*": 3, "/": 4, "%": 5, "+": 6, "-": 7, "<": 8, ">": 9, "<=": 10, ">=": 11,
            "==": 12, "!=": 13, "&&": 14, "||": 15}
_ASG_OPS = {"=": 16, "*=": 17, "/=": 18, "%=": 19, "+=": 20, "-=": 21, "&&=": 22, "||=": 23}
_PREC = [("||",), ("&&",), ("==", "!="), ("<", ">", "<=", ">="), ("+", "-"), ("*", "/", "%")]

_TOK_RE = re.compile(r"""\s*(?:
    (?P<var>var:0[xX][0-9A-Fa-f]+)
  | (?P<at>@0[xX][0-9A-Fa-f]+)
  | (?P<num>0[xX][0-9A-Fa-f]+|\d+)
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*(?:@\d+)?)
  | (?P<op>\|\|=|&&=|\|\||&&|==|!=|<=|>=|\*=|/=|%=|\+=|-=|[-+*/%<>=!()\[\]:])
  )""", re.X)

# Leaf-only operand forms (handled by Script_EvalExpressionOrVar without the RPN VM).
LEAF_TAGS = (3, 4, 5, 0x11, 0x12, 0x13)        # whole-operand leaves: no RPN terminator is read
_LEAF_WORDS = {"null": b"\x11", "zero": b"\x12", "self": b"\x13",
               # the same leaves spelled as the add / sub / set mode of the ops that read an
               # argument's kind (opcode_meta.MODE_ARG_SLOTS)
               "add": b"\x11", "sub": b"\x12", "set": b"\x13"}


def _tokenize(text):
    pos = 0
    out = []
    s = text.strip()
    while pos < len(s):
        m = _TOK_RE.match(s, pos)
        if not m or m.end() == pos:
            raise AsmError("bad expression syntax near %r in %r" % (s[pos:pos + 12], s))
        pos = m.end()
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
    return out


class _Parser:
    def __init__(self, tokens, resolver):
        self.toks = tokens
        self.i = 0
        self.resolver = resolver

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self, kind=None, val=None):
        k, v = self.peek()
        if k is None or (kind and k != kind) or (val is not None and v != val):
            raise AsmError("expected %s in expression, got %r" % (val or kind, v))
        self.i += 1
        return v

    # assignment is the lowest level and right-associative
    def parse_assign(self):
        left = self.parse_bin(0)
        k, v = self.peek()
        if k == "op" and v in _ASG_OPS:
            self.i += 1
            right = self.parse_assign()
            if left[0] not in ("pvar", "reg", "arr"):
                raise AsmError("left side of %r must be a game flag, regN or arr[N]" % v)
            return ("asg", _ASG_OPS[v], left, right)
        return left

    def parse_bin(self, level):
        if level >= len(_PREC):
            return self.parse_unary()
        node = self.parse_bin(level + 1)
        while True:
            k, v = self.peek()
            if k == "op" and v in _PREC[level]:
                self.i += 1
                rhs = self.parse_bin(level + 1)
                node = ("bin", _BIN_OPS[v], node, rhs)
            else:
                return node

    def parse_unary(self):
        k, v = self.peek()
        if k == "op" and v == "-":
            self.i += 1
            node = self.parse_unary()
            if node[0] == "int":
                return ("int", -node[1])
            return ("un", 1, node)
        if k == "op" and v == "!":
            self.i += 1
            return ("un", 2, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        k, v = self.peek()
        if k is None:
            raise AsmError("unexpected end of expression")
        if k == "op" and v == "(":
            self.i += 1
            node = self.parse_assign()
            self.take("op", ")")
            return node
        if k == "num":
            self.i += 1
            return ("int", _int_in(v, 0, 0xFFFFFFFF, None, "number"))
        if k == "var":
            self.i += 1
            return ("pvar", int(v[4:], 16))
        if k == "at":
            raise AsmError("@0xOFFSET (reuse an existing expression) is only valid as a whole operand")
        if k == "id":
            self.i += 1
            low = v.lower()
            m = re.fullmatch(r"reg(\d)", low)
            if m:
                return ("reg", int(m.group(1)))
            if low == "arr":
                self.take("op", "[")
                idx = self.take("num")
                self.take("op", "]")
                return ("arr", _int_in(idx, 0, 0xFFFF, None, "arr[] index"))
            if low in ("tag3", "tag4", "actor", "map", "u16") or low in _LEAF_WORDS:
                raise AsmError("%s is a leaf-only operand form; it cannot be combined with "
                               "operators" % v)
            enc = self.resolver(v) if self.resolver else None
            if enc is None:
                raise AsmError("unknown variable %r (use an emdeb.bin FLG_/REG_ name, "
                               "var:0xNNNN, regN or arr[N])" % v)
            return ("pvar", int(enc))
        raise AsmError("unexpected token %r in expression" % v)


def int_literal_bytes(v):
    """RPN push of the integer `v` (no terminator), encoded the way the game's own compiler
    does it (every literal in the shipped rf3.mc): the signed form first -- s8 for -128..127,
    u8 only for 128..255, s16 for -32768..32767, u16 only for 32768..65535 -- else int32."""
    if v == 0:
        return b"\x14"
    if v == -1:
        return b"\x15"
    if v == 1:
        return b"\x16"
    if -128 <= v <= 127:
        return b"\x18" + struct.pack("<b", v)
    if 0 <= v <= 255:
        return bytes([0x17, v])
    if -32768 <= v <= 32767:
        return b"\x1A" + struct.pack("<h", v)
    if 0 <= v <= 0xFFFF:
        return b"\x19" + struct.pack("<H", v)
    if -0x80000000 <= v <= 0x7FFFFFFF:
        return b"\x01" + struct.pack("<i", v)
    if 0 <= v <= 0xFFFFFFFF:
        return b"\x01" + struct.pack("<I", v)
    raise AsmError("literal %d does not fit an int32" % v)


def _emit(node, out):
    kind = node[0]
    if kind == "int":
        out += int_literal_bytes(node[1])
    elif kind == "reg":
        out.append(7 + node[1])
    elif kind == "arr":
        out += b"\x06" + struct.pack("<H", node[1] & 0xFFFF)
    elif kind == "pvar":
        out += b"\x02" + struct.pack("<I", node[1] & 0xFFFFFFFF)
    elif kind == "un":
        _emit(node[2], out)
        out.append(0x80 + node[1])
    elif kind in ("bin", "asg"):
        _emit(node[2], out)
        _emit(node[3], out)
        out.append(0x80 + node[1])
    else:
        raise AsmError("internal: bad node %r" % (node,))


def parse_expr(text, resolver=None):
    """Parse an infix expression into an AST (for validation / tooling)."""
    toks = _tokenize(text)
    if not toks:
        raise AsmError("empty expression")
    p = _Parser(toks, resolver)
    node = p.parse_assign()
    if p.i != len(toks):
        raise AsmError("trailing tokens in expression %r: %r" % (text, toks[p.i:]))
    return node


_LEAF_RE = re.compile(r"^\s*tag([34])\s*\(\s*(0[xX][0-9A-Fa-f]+|\d+)\s*\)\s*$", re.I)
# Named forms of the same two leaves (see script.actor_leaf_text): actor(Forte) / actor(4) /
# actor(player) = tag 3, map(MAP_CITY_00) / map(24) = tag 4.
_NAMED_LEAF_RE = re.compile(r"^\s*(actor|map)\s*\(\s*([^()]*?)\s*\)\s*$", re.I)
_U16_RE = re.compile(r"^\s*u16\s*\(\s*(0[xX][0-9A-Fa-f]+|\d+)\s*\)\s*$", re.I)


def asm_expr(text, resolver=None):
    """Compile an operand expression to bytes (terminator included for RPN streams).

    `resolver(name) -> packed enc | None` maps symbolic variable names (emdeb.bin
    FLG_/REG_ names, NAMED_SCRIPT_VARS) to their packed encoding; see `make_resolver`.
    Whole-operand leaf forms: `tag3(N)` / `tag4(N)` (u32 constants the handler gets with
    kind 2 / 3), `actor(Name|N)` (= `tag3(N)`, a character id), `map(MAP_NAME|N)`
    (= `tag4(N)`, a map id), `u16(N)`, `null`, `zero`,
    `self` (no terminator, exactly what the engine's leaf reader expects)."""
    s = text.strip()
    if _outer_parens(s):
        s = s[1:-1].strip()
    low = s.lower()
    if low in _LEAF_WORDS:
        return _LEAF_WORDS[low]
    m = _LEAF_RE.match(s)
    if m:
        tag = int(m.group(1))
        return bytes([tag]) + struct.pack("<I", _int_in(m.group(2), 0, 0xFFFFFFFF, None, "tag%d" % tag))
    m = _NAMED_LEAF_RE.match(s)
    if m:
        from . import script as _script
        kind, arg = m.group(1).lower(), m.group(2)
        if kind == "actor":
            n = _script.actor_leaf_value(arg)
            if n is None:
                raise AsmError("actor(%s): unknown or ambiguous character name -- use a unique "
                               "name (Forte, Xiao Pai, player) or the numeric id, e.g. actor(27) "
                               "for one of the Travelers" % arg)
            if not (0 <= n <= 0xFFFFFFFF):
                raise AsmError("actor(%s): id out of the u32 range" % arg)
            return b"\x03" + struct.pack("<I", n)
        n = _script.map_leaf_value(arg)
        if n is None:
            raise AsmError("map(%s): unknown map -- use a MAP_* file name (MAP_CITY_00) or the "
                           "numeric map id" % arg)
        if not (0 <= n <= 0xFFFFFFFF):
            raise AsmError("map(%s): id out of the u32 range" % arg)
        return b"\x04" + struct.pack("<I", n)
    m = _U16_RE.match(s)
    if m:
        return b"\x05" + struct.pack("<H", _int_in(m.group(1), 0, 0xFFFF, None, "u16()"))
    node = parse_expr(s, resolver)
    out = bytearray()
    _emit(node, out)
    out.append(0)
    return bytes(out)


def _outer_parens(s):
    if len(s) < 2 or s[0] != "(" or s[-1] != ")":
        return False
    depth = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i == len(s) - 1
    return False


def make_resolver(container, emf_table=None, extra=None):
    """Build a name -> packed-encoding resolver for `asm_expr`.

    Accepts emdeb.bin variable names (via `emf_table.get(name)`, width from the table --
    the corpus encodes every variable exactly as (bit_offset, emdeb width, unsigned)),
    `NAME@bit` (as the with_offset disassembly prints), NAMED_SCRIPT_VARS names, and
    any `extra` {name: enc} dict."""
    named = {v: k for k, v in getattr(meta, "NAMED_SCRIPT_VARS", {}).items()}

    def resolve(name):
        if extra and name in extra:
            return extra[name]
        base, _, bit = name.partition("@")
        if bit.isdigit() and emf_table is not None:
            v = emf_table.by_offset(int(bit))
            if v is not None and v.bit_offset == int(bit):
                return container.pack_var(v.bit_offset, v.bit_width)
            return None
        if emf_table is not None:
            try:
                v = emf_table.get(base)
            except Exception:
                v = None
            if v is not None:
                return container.pack_var(v.bit_offset, v.bit_width)
        if base in named:
            return container.pack_var(named[base], 1)
        return None
    return resolve


# ---- listing assembler ------------------------------------------------------------------
_CONTROL_NAMES = {"END": 0xFFFF, "RET": 0xFFFF, "FRAME": 0xFFF1, "CALL": 0xFFFE,
                  "RET_NZ": 0xFFFD, "BR_END": 0xFFFD, "DIALOG": 0xFFFC, "EVAL": 0xFFFB,
                  "JMP": 0xFFFA, "BR_NZ": 0xFFF9, "BR_Z": 0xFFF8, "SWITCH": 0xFFF7,
                  "SWITCH_CLAMP": 0xFFF6, "PROMPT_CHOICE_FORCED": 0xFFF5, "PROMPT_CHOICE": 0xFFF4,
                  "JMP_RAND": 0xFFF3, "JMP_WEIGHTED": 0xFFF2}

_TECH_BY_NAME = None


def op_from_any(name):
    """Opcode number from a mnemonic, technical name, `opN`, or a number; None if unknown."""
    s = name.strip()
    if not s:
        return None
    if s.lstrip("-").isdigit() or s.lower().startswith("0x"):
        v = int(s, 0)
        return v if 0 <= v < 0xFFF0 else None
    m = re.fullmatch(r"op(\d+)", s, re.I)
    if m:
        return int(m.group(1))
    op = script.op_from_name(s)
    if op is not None:
        return op
    # `Name_N`: listing_name's spelling for an opcode that shares its mnemonic (or technical
    # name) with others -- valid when op N really carries that name
    m = re.fullmatch(r"(.+)_(\d+)", s)
    if m:
        n = int(m.group(2))
        if 0 <= n < script.DISPATCHABLE_ACTION_OPS and m.group(1).lower() in (
                (script.opcode_mnemonic(n) or "").lower(), (script.opcode_name(n) or "").lower()):
            return n
    global _TECH_BY_NAME
    if _TECH_BY_NAME is None:
        _TECH_BY_NAME = {}
        for o in range(script.DISPATCHABLE_ACTION_OPS):
            nm = script.opcode_name(o)
            if nm and nm.lower() not in _TECH_BY_NAME:
                _TECH_BY_NAME[nm.lower()] = o
        for o, full in script.OPCODE_NAMES.items():
            if full and full.lower() not in _TECH_BY_NAME:
                _TECH_BY_NAME[full.lower()] = o
    return _TECH_BY_NAME.get(s.lower())


def listing_name(op):
    """The name `scene_listing` prints for an action opcode: the mnemonic when it maps
    back to exactly this op, else the technical name; when several opcodes share the name
    (handler aliases such as 218/219) the others print as `Name_N`, and only nameless ops
    fall back to `opN`. An op with opcode arguments (SetSpeaker) prints its family name;
    action_line puts those arguments first. Always re-assemblable."""
    m = script.opcode_mnemonic(op)
    if meta.OPCODE_ARGS.get(op):
        return m
    if m == "nop":                                  # NOP_OP is `nop`, the other stubs nop_N
        return "nop" if op == meta.NOP_OP else "nop_%d" % op
    if m and op_from_any(m) == op:
        return m
    t = script.opcode_name(op)
    if t and op_from_any(t) == op:
        return t
    for nm in (m, t):
        if nm and not nm.startswith("(") and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nm)                 and not re.fullmatch(r"op\d+", nm) and op_from_any("%s_%d" % (nm, op)) == op:
            return "%s_%d" % (nm, op)
    return "op%d" % op


def _strip_comment(line):
    """Drop a `;` comment that is outside double quotes."""
    q = False
    for i, ch in enumerate(line):
        if ch == '"':
            q = not q
        elif ch == ";" and not q:
            return line[:i]
    return line


def _split_top(s, seps=","):
    """Split `s` at top-level separator characters (outside (), [] and quotes)."""
    parts, depth, q, cur = [], 0, False, []
    for ch in s:
        if ch == '"':
            q = not q
        if not q:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            elif ch in seps and depth == 0:
                parts.append("".join(cur).strip())
                cur = []
                continue
        cur.append(ch)
    tail = "".join(cur).strip()
    if tail or parts:
        parts.append(tail)
    return [p for p in parts if p != ""]


def _take_paren(s):
    """Return (inner, rest) for a leading balanced '(...)' group in s (after optional
    'cond='/'val='/'sel=' prefixes)."""
    s = s.strip()
    s = re.sub(r"^(cond|val|sel|value|weight)\s*=\s*", "", s)
    if not s.startswith("("):
        raise AsmError("expected a parenthesised expression, got %r" % s)
    depth = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return s[1:i], s[i + 1:].strip()
    raise AsmError("unbalanced parentheses in %r" % s)


class _Stmt:
    __slots__ = ("line_no", "text", "code", "fixups", "label", "size")

    def __init__(self, line_no, text):
        self.line_no = line_no
        self.text = text
        self.code = bytearray()
        self.fixups = []          # (offset_in_code, kind, payload)  kind: 'label'|'expr'|'abs'
        self.label = None
        self.size = 0


class Assembler:
    """Assemble a listing into a region that will live at in-bank offset `base`."""

    def __init__(self, resolver=None, enum_names=True, strict=True):
        self.resolver = resolver
        self.enum_names = enum_names
        # strict=False accepts what the shipped file contains but a modder should not
        # write (argument counts the handler misreads, argument values that crash the
        # game, >128 choice options): used when a whole bank is reassembled from its own
        # listing (bankrelink) and by the editor's Source tab, which allows anything the
        # bytecode can express
        self.strict = strict

    # -- operands --
    def operand(self, text, op=None, index=None):
        """Return ('expr', bytes) or ('abs', offset) for one operand."""
        s = text.strip()
        if s.startswith("@"):
            return ("abs", _int_in(s[1:], 0, 0xFFFF, None, "@offset"))
        m = re.fullmatch(r"raw\(\s*([0-9A-Fa-f]+)\s*\)", s)
        if m and len(m.group(1)) % 2 == 0:       # verbatim operand bytes (terminator included)
            return ("expr", bytes.fromhex(m.group(1)))
        if re.fullmatch(r"-?\d+", s) or re.fullmatch(r"-?0[xX][0-9A-Fa-f]+", s):
            return ("expr", int_literal_bytes(_int_in(s, -0x80000000, 0xFFFFFFFF, None, "literal"))
                    + b"\x00")
        if op is not None and index is not None and self.enum_names and re.fullmatch(r"[A-Za-z_][\w()]*", s):
            v = _enum_value(op, index, s)
            if v is not None:
                return ("expr", int_literal_bytes(v) + b"\x00")
        b = asm_expr(s, self.resolver)
        if b[0] in LEAF_TAGS:
            b += b"\x00"                      # the byte the compiler writes after a leaf (never read)
        return ("expr", b)

    # -- statements --
    def parse_line(self, line_no, raw, st):
        body = raw.strip()
        if body.startswith(".raw"):
            hexs = body[4:].replace(" ", "").replace("_", "")
            try:
                st.code += bytes.fromhex(hexs)
            except ValueError:
                raise AsmError("line %d: bad .raw hex" % line_no)
            return
        m = re.match(r"^([A-Za-z_][\w$]*|\d+)\s*(.*)$", body)
        if not m:
            raise AsmError("line %d: cannot parse statement %r" % (line_no, body))
        head, rest = m.group(1), m.group(2).strip()
        up = head.upper()
        if up in _CONTROL_NAMES:
            self._control(line_no, up, rest, st)
        else:
            self._action(line_no, head, rest, st)

    def _targets(self, s):
        return [t.strip() for t in _split_top(s, ",|") if t.strip()]

    def _target_fixup(self, st, tgt):
        tgt = tgt.strip()
        if re.fullmatch(r"0[xX][0-9A-Fa-f]+|\d+", tgt):
            st.fixups.append((len(st.code), "abs", int(tgt, 0)))
        else:
            st.fixups.append((len(st.code), "label", tgt))
        st.code += b"\x00\x00"

    def _expr_fixup(self, st, operand):
        kind, payload = operand
        st.fixups.append((len(st.code), "expr" if kind == "expr" else "abs", payload))
        st.code += b"\x00\x00"

    def _control(self, line_no, name, rest, st):
        op = _CONTROL_NAMES[name]
        st.code += struct.pack("<H", op)
        if op == 0xFFFF:
            if rest:
                raise AsmError("line %d: END takes no operands" % line_no)
        elif op == 0xFFF1:
            n = _int_in(rest or "0", 0, 0xFFFF, line_no, "FRAME slot count")
            st.code += struct.pack("<H", n)
        elif op == 0xFFFC:
            lid = rest.lstrip("#").strip()
            if not lid:
                raise AsmError("line %d: DIALOG needs a line id" % line_no)
            st.code += struct.pack("<I", _int_in(lid, 0, 0xFFFFFFFF, line_no, "DIALOG line id"))
        elif op in (0xFFFE, 0xFFFA):
            if not rest:
                raise AsmError("line %d: %s needs a target" % (line_no, name))
            self._target_fixup(st, rest.lstrip("-> ").strip())
        elif op in (0xFFFD, 0xFFFB):
            inner, tail = _take_paren(rest)
            if tail:
                raise AsmError("line %d: unexpected %r after expression" % (line_no, tail))
            self._expr_fixup(st, self.operand(inner))
        elif op in (0xFFF8, 0xFFF9):
            inner, tail = _take_paren(rest)
            if not tail.startswith("->"):
                raise AsmError("line %d: %s needs '-> target'" % (line_no, name))
            self._expr_fixup(st, self.operand(inner))
            self._target_fixup(st, tail[2:].strip())
        elif op in (0xFFF7, 0xFFF6):
            inner, tail = _take_paren(rest)
            if not tail.startswith("->"):
                raise AsmError("line %d: %s needs '-> t1, t2, ...'" % (line_no, name))
            tg = self._targets(tail[2:])
            if op == 0xFFF6 and not tg:
                # Script_VMStep 0xFFF6 jumps to the word at pc+2*(n+2) when the selector is
                # >= n: with n = 0 that is the count word itself (a jump to pc 0).
                raise AsmError("line %d: SWITCH_CLAMP needs at least one target" % line_no)
            self._expr_fixup(st, self.operand(inner))
            st.code += struct.pack("<H", len(tg))
            for t in tg:
                self._target_fixup(st, t)
        elif op == 0xFFF3:
            tg = self._targets(rest.lstrip("-> ").strip() if rest.startswith("->") else rest)
            if not tg:
                # Script_VMStep 0xFFF3: n <= 1 always takes the word at pc+4 -- with n = 0
                # that is the next statement's opcode, used as a pc.
                raise AsmError("line %d: JMP_RAND needs at least one target" % line_no)
            st.code += struct.pack("<H", len(tg))
            for t in tg:
                self._target_fixup(st, t)
        elif op == 0xFFF2:
            items = self._targets(rest)
            pairs = []
            for it in items:
                inner, tail = _take_paren(it)
                if not tail.startswith("->"):
                    raise AsmError("line %d: JMP_WEIGHTED items look like '(weight) -> target'" % line_no)
                pairs.append((inner, tail[2:].strip()))
            if not pairs:
                # Script_Opcode_FFF2_ExecPrim always jumps to the word at pc+4+2*pick; with
                # no cases that is past the statement.
                raise AsmError("line %d: JMP_WEIGHTED needs at least one (weight) -> target" % line_no)
            st.code += struct.pack("<H", len(pairs))
            for _, t in pairs:
                self._target_fixup(st, t)
            for w, _ in pairs:
                self._expr_fixup(st, self.operand(w))
        elif op in (0xFFF4, 0xFFF5):
            items = self._targets(rest)
            cancel = None
            choices = []
            for it in items:
                left, _, tgt = it.partition("->")
                left = left.strip()
                tgt = tgt.strip()
                if not tgt:
                    raise AsmError("line %d: choice items look like '#id -> target'" % line_no)
                if left.upper() == "CANCEL":
                    cancel = tgt
                else:
                    if not left.startswith("#"):
                        raise AsmError("line %d: choice item id must be '#<string id>' (got %r)"
                                       % (line_no, left))
                    choices.append((_int_in(left[1:], 0, 0xFFFFFFFF, line_no, "choice string id"), tgt))
            if op == 0xFFF4 and cancel is None and choices:
                # the slot the game never takes (the cancel key picks the LAST option):
                # fill it the way every shipped menu does
                cancel = choices[-1][1]
            if op == 0xFFF5 and cancel is not None:
                raise AsmError("line %d: PROMPT_CHOICE_FORCED has no cancel branch" % line_no)
            if not choices:
                raise AsmError("line %d: a choice needs at least one option" % line_no)
            if self.strict and len(choices) > script.MAX_CHOICE_OPTIONS:
                # Dialogue_HandleScriptActionShowLine queues at most 0x80 rows; the rest are
                # silently dropped (unreachable targets, out-of-range mask reads).
                raise AsmError("line %d: %d choice options -- the game shows at most %d (the "
                               "rest are silently dropped); split it into several menus "
                               "chained by a 'More...' option"
                               % (line_no, len(choices), script.MAX_CHOICE_OPTIONS))
            st.code += struct.pack("<H", len(choices))
            if cancel is not None:
                self._target_fixup(st, cancel)
            for _, t in choices:
                self._target_fixup(st, t)
            for sid, _ in choices:
                st.code += struct.pack("<I", sid)

    def _action(self, line_no, head, rest, st):
        n_opargs = meta.opcode_arg_count(head)
        op = meta.op_from_mnemonic(head) if n_opargs else op_from_any(head)   # family: set below
        if op is None:
            hits = list(script.find_ops(head))
            if not hits:                                   # substring miss: try close spellings
                import difflib
                names = {}
                for o in range(script.DISPATCHABLE_ACTION_OPS):
                    for nm in (script.opcode_mnemonic(o), script.opcode_name(o)):
                        if nm and nm not in names and not nm.startswith("(") and nm != "nop":
                            names[nm] = o
                for nm in difflib.get_close_matches(head, list(names), n=6, cutoff=0.6):
                    hits.append((names[nm], nm))
            sug = (" -- did you mean: " + ", ".join("%s (op %d)" % (m, o) for o, m in hits[:6])) if hits else ""
            raise AsmError("line %d: unknown opcode %r%s" % (line_no, head, sug))
        if self.strict and op >= script.DISPATCHABLE_ACTION_OPS:
            raise AsmError("line %d: opcode %d has no handler -- the engine's dispatch table is "
                           "%d slots (0..%d) and it is indexed without a bounds check, so this "
                           "would call past the end of it"
                           % (line_no, op, script.DISPATCHABLE_ACTION_OPS,
                              script.DISPATCHABLE_ACTION_OPS - 1))
        args_txt = rest
        # `Name(a, b)` call syntax: the WHOLE remainder is one balanced paren group.
        # `Name (expr), b` bare syntax: the first group is just the first argument.
        if args_txt.startswith("(") and _outer_parens(args_txt.strip()):
            args_txt = args_txt.strip()[1:-1]
        args = _split_top(args_txt) if args_txt.strip() else []
        if n_opargs:                        # SetSpeaker(character, side, ...): opcode arguments
            try:
                op = meta.op_from_opcode_args(head, args)
            except ValueError as e:
                raise AsmError("line %d: %s" % (line_no, e))
            args = args[n_opargs:]
        if len(args) > 64:
            raise AsmError("line %d: too many arguments (%d)" % (line_no, len(args)))
        lim = meta.arg_limit(op) if hasattr(meta, "arg_limit") else None
        if self.strict and lim is not None and len(args) > lim[0]:
            raise AsmError("line %d: op %d takes at most %d arguments (%d given): %s"
                           % (line_no, op, lim[0], len(args), lim[1]))
        bad = meta.arg_count_problem(op, len(args)) if self.strict else None
        if bad:
            raise AsmError("line %d: %s" % (line_no, bad))
        if self.strict:
            for i, a in enumerate(args):
                v = literal_value(a, op, i, self.enum_names)
                bad = meta.arg_value_problem(op, i, v) if v is not None else None
                if bad:
                    raise AsmError("line %d: %s" % (line_no, bad))
        st.code += struct.pack("<HH", op, len(args))
        for i, a in enumerate(args):
            self._expr_fixup(st, self.operand(a, op, i))

    # -- whole listing --
    def parse(self, text):
        """Parse a listing into statements without laying it out: (stmts [_Stmt], labels
        {name: _Stmt}, trailing [label names with no statement after them]). Each _Stmt
        carries its bytes with the address fields zeroed and `fixups` naming what goes
        there. `bankrelink.BankModel.listing_items` turns these into relinkable
        statements; `assemble` lays them out as one region."""
        stmts = []
        pending_labels = []
        labels = OrderedDict()
        lines = text.splitlines()
        # names referenced as targets: a lone 4-hex-digit prefix that is never referenced
        # is a pasted disassembly ADDRESS, otherwise it is a label.
        refs = set(re.findall(r"(?:->|\bCALL\b|\bJMP\b|\bJMP_RAND\b|,)\s*([A-Za-z_0-9]\w*)", text))
        for ln, raw in enumerate(lines, 1):
            line = _strip_comment(raw).strip()
            if not line:
                continue
            while True:
                m = re.match(r"^([A-Za-z_]\w*|[0-9A-Fa-f]{4})\s*:(?!:)\s*(.*)$", line)
                if not m:
                    break
                tok, line = m.group(1), m.group(2)
                if re.fullmatch(r"[0-9A-Fa-f]{4}", tok) and tok not in refs and tok not in labels:
                    continue                                  # disassembly address, ignore
                if tok in labels or tok in pending_labels:
                    raise AsmError("line %d: duplicate label %r" % (ln, tok))
                pending_labels.append(tok)
            if not line:
                continue
            st = _Stmt(ln, line)
            try:
                self.parse_line(ln, line, st)
            except AsmError:
                raise
            except (ValueError, struct.error, OverflowError) as e:
                raise AsmError("line %d: %s (%s)" % (ln, e, line.strip()))
            for lb in pending_labels:
                labels[lb] = st
            pending_labels = []
            stmts.append(st)
        return stmts, labels, pending_labels

    def assemble(self, text, base, fallthrough_to=None, auto_end=True):
        """Assemble `text` for in-bank offset `base`. Returns (bytes, labels{name: pc}).
        If the last statement can fall through, a `JMP fallthrough_to` (or END when
        `fallthrough_to` is None and `auto_end`) is appended so the region never runs
        into the expression pool. This is the listing CHECK (sizes, labels, lint); edits to
        rf3.mc go through `script.Container`, which relinks the whole bank."""
        stmts, labels, pending_labels = self.parse(text)
        off = 0
        for st in stmts:
            st.size = len(st.code)
            st.label = off
            off += st.size
        # terminator if the listing can fall off its end
        needs_term = True
        if stmts:
            last = stmts[-1]
            if last.code[:2] in (b"\xff\xff", b"\xfa\xff", b"\xf6\xff", b"\xf5\xff", b"\xf4\xff",
                                 b"\xf3\xff", b"\xf2\xff"):
                needs_term = False
        term = _Stmt(0, "<terminator>")
        if needs_term or pending_labels:
            if fallthrough_to is None:
                if not auto_end:
                    raise AsmError("listing must end with END/JMP/etc.")
                term.code += b"\xff\xff"
            else:
                term.code += b"\xfa\xff"
                term.fixups.append((2, "abs", int(fallthrough_to)))
                term.code += b"\x00\x00"
            term.size = len(term.code)
            term.label = off
            off += term.size
            for lb in pending_labels:
                labels[lb] = term
            stmts.append(term)
        code_len = off
        # expression pool (dedup)
        pool = bytearray()
        pool_off = {}
        for st in stmts:
            for (fo, kind, payload) in st.fixups:
                if kind == "expr":
                    if payload not in pool_off:
                        pool_off[payload] = code_len + len(pool)
                        pool += payload
        total = code_len + len(pool)
        if base + total > 0x10000:
            raise AsmError("region would end at 0x%X: a bank is capped at 64 KB -- the new body "
                           "(%d bytes) is appended at 0x%04X, and only %d bytes are left in this bank. "
                           "In a full bank, edit in place instead (Set value, the args row, dialogue "
                           "text), or move the content into a scene in a smaller bank"
                           % (base + total, total, base, max(0, 0x10000 - base)))
        out = bytearray()
        for st in stmts:
            out += st.code
        label_pcs = {name: base + st.label for name, st in labels.items()}
        for st in stmts:
            for (fo, kind, payload) in st.fixups:
                at = st.label + fo
                if kind == "expr":
                    val = base + pool_off[payload]
                elif kind == "abs":
                    val = int(payload)
                else:
                    if payload not in label_pcs:
                        raise AsmError("undefined label %r (line %d)" % (payload, st.line_no))
                    val = label_pcs[payload]
                if not (0 <= val <= 0xFFFF):
                    raise AsmError("target/offset 0x%X out of the 16-bit bank space" % val)
                struct.pack_into("<H", out, at, val)
        out += pool
        return bytes(out), label_pcs


def _int_in(text, lo, hi, line_no, what):
    """int(text, 0) range-checked into lo..hi, else a clean AsmError (never a silent mask)."""
    where = ("line %d: " % line_no) if line_no is not None else ""
    t = str(text).strip()
    try:
        v = int(t, 0)
    except ValueError:
        try:
            v = int(t, 10)                         # '08': decimal with a leading zero
        except ValueError:
            raise AsmError("%s%s: %r is not a number" % (where, what, text))
    if not (lo <= v <= hi):
        raise AsmError("%s%s %d out of range (%d..%d)" % (where, what, v, lo, hi))
    return v


def _enum_value(op, index, name):
    """Value for an enum-name argument (opcode_meta.ENUM_ARG_VALUES), or None."""
    table = getattr(meta, "ENUM_ARG_VALUES", {}).get((op, index))
    if table:
        for v, entry in table.items():
            nm = entry[0] if isinstance(entry, (tuple, list)) else entry
            if isinstance(nm, str) and nm.lower() == name.lower():
                return v
    if 16 <= op <= 75:
        if index == 0:
            # the six moods every portrait shares (face ids 0..5, portraits.py), SP1/SP2
            story = {"normal": 0, "angry": 1, "crying": 2, "smile": 3, "surprised": 4, "shy": 5,
                     "sp1": 255, "sp2": 254}
            if name.lower() in story:
                return story[name.lower()]
            for v, nm in getattr(meta, "FACE_FRAMES", {}).items():
                lab = nm[0] if isinstance(nm, (tuple, list)) else nm
                if isinstance(lab, str) and lab.lower() == name.lower():
                    return v
        if index == 1:
            for v, nm in getattr(meta, "PORTRAIT_EMOTES", {}).items():
                lab = nm[0] if isinstance(nm, (tuple, list)) else nm
                if isinstance(lab, str) and lab.lower() == name.lower():
                    return v
    return None


def assemble(text, base, resolver=None, fallthrough_to=None, auto_end=True, strict=True):
    """Module-level convenience: see Assembler.assemble."""
    return Assembler(resolver, strict=strict).assemble(text, base, fallthrough_to, auto_end)


def literal_value(text, op=None, index=None, enum_names=True):
    """The number an operand's text stands for when it is a plain literal or a value name
    of that argument, else None (expressions, registers, flags)."""
    s = (text or "").strip()
    try:
        if re.fullmatch(r"-?\d+", s) or re.fullmatch(r"-?0[xX][0-9A-Fa-f]+", s):
            return int(s, 0)
    except ValueError:
        return None
    if enum_names and op is not None and index is not None and re.fullmatch(r"[A-Za-z_][\w()]*", s):
        return _enum_value(op, index, s)
    return None


def lint_listing(text, base=0x1000, resolver=None, text_count=None):
    """Assemble `text` and run the engine-behaviour checks on the result (currently the
    PROMPT_CHOICE checks, script.choice_problems, and the SetDialogueSuppressed checks,
    script.dialogue_suppress_problems). Raises AsmError like `assemble`;
    returns [(pc, 'error'|'warning', message)]. The statements are decoded back linearly
    from `base` up to the first expression-pool byte."""
    region, _labels = assemble(text, base, resolver=resolver)
    buf = bytes(base) + region
    stmts, pc, pool = [], base, len(buf)
    while pc < min(pool, len(buf)):
        st = script.decode_statement(buf, pc)
        if st is None or st.size <= 0:
            break
        stmts.append(st)
        for off in list(st.args) + list(st.expr_refs):
            if off is not None and base <= off < pool:
                pool = off
        pc += st.size
    return script.choice_problems(buf, stmts, text_count) + script.dialogue_suppress_problems(buf, stmts)


def operand_text(buf, off, op=None, ai=None):
    """Assembler-ready text for the operand at `off`: a bare int for static literals,
    `(expr)` for runtime expressions, leaf forms verbatim, or `@0xOFF` when the bytes
    cannot be rendered (the assembler then reuses them in place). With the statement's
    opcode `op` and argument index `ai`, a tag-3/4 constant in a known slot is written
    raw, as tag3(N) / tag4(N): actor(Name) / map(MAP_NAME) are our reading of the slot
    (script.leaf_slot_kind), so the listing's comment shows them. Value names (opcode_table
    `value_names`) likewise stay numbers here and appear in the comment."""
    if off is None or not (0 <= off < len(buf)):
        return "@0x%04x" % (off or 0)
    t = buf[off]
    if t in (0x11, 0x12, 0x13) and (op, ai) in script.meta.MODE_ARG_SLOTS:
        return script.meta.MODE_LEAF_WORDS[t]
    if t in (3, 4, 5, 0x11, 0x12, 0x13):
        txt, _ = script.disasm_expr(buf, off)
        if t == 5:
            return "u16(%s)" % txt
        if t == 0x12:
            return "zero"
        return txt
    v, ok = script.eval_expr(buf, off)
    if ok and v is not None and buf[off] in (0x01, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A):
        # a single-literal stream renders as the plain int; folded arithmetic keeps its text
        end = off + len(int_literal_bytes(v))
        if end < len(buf) and buf[end] == 0 or (end < len(buf) and _single_literal(buf, off)):
            return str(v)
    txt, _ = script.disasm_expr(buf, off)
    if not txt or txt == "?":
        return "@0x%04x" % off
    return "(%s)" % txt


def call_arg(text):
    """An operand as it appears inside an action's call brackets: an expression loses its
    own outer brackets there (`Give(258, reg0 + 1)`), since the commas already separate
    the arguments."""
    t = text.strip()
    return t[1:-1].strip() if _outer_parens(t) else t


def action_text(name, args):
    """The one listing form of an action: `Name(arg, arg)`, `Name()` without arguments."""
    return "%s(%s)" % (name, ", ".join(call_arg(a) for a in args))


def action_line(op, args):
    """The listing line of action `op` with operand texts `args`: its listing name, and the
    opcode-encoded arguments in front, as numbers (SetSpeaker(4, 1, 3, 0) for op 25: Forte,
    Right -- the names are ours, so they go in the comment)."""
    return action_text(listing_name(op), meta.opcode_arg_raws(op) + list(args))


def _single_literal(buf, off):
    t = buf[off]
    size = {0x14: 1, 0x15: 1, 0x16: 1, 0x17: 2, 0x18: 2, 0x19: 3, 0x1A: 3, 0x01: 5}.get(t)
    return size is not None and off + size < len(buf) and buf[off + size] == 0


def scene_listing(scene, bank, dialog=None, friendly=True, show_addr=True, comments=True,
                  bank_no=None, own=None):
    """Render a Scene as a re-assemblable listing (see the module docstring).

    Labels are emitted for every intra-scene branch/call target; targets outside the
    scene stay absolute (`0xNNNN`, e.g. shared CALL bodies). `dialog(line_id) -> str`
    adds the dialogue text as a comment. Statements are listed in pc order; when the
    scene's entry is not its lowest statement (a CALLed body placed before it), the
    listing starts with `JMP ENTRY` so that assembling it yields a region whose first
    byte IS the scene start. `bank_no` = the container bank index for the header."""
    buf = bank.data
    labels = dict(script.scene_labels(scene))
    if own is not None:                     # only the scene's own code; shared code by address
        labels = {pc: lab for pc, lab in labels.items() if pc in own}
    lines = []
    typ = "discovered" if scene.action_type < 0 else "type %d" % scene.action_type
    where = "bank %d (%s)" % (scene.bank_index, scene.kind)
    if bank_no is not None:
        where = "container bank %d = %s" % (bank_no, where)
    lines.append("; %s %s  entry @0x%04x  %d stmts%s" % (
        where, typ, scene.entry_pc, len(scene.stmts),
        "" if scene.ok else "  [PARTIAL: %s]" % scene.error))

    def tgt(t):
        if t is None:
            return "0x0000"
        return labels.get(t, "0x%04x" % t)

    first_pc = next((pc for pc in scene.stmts if own is None or pc in own), None)
    if first_pc is not None and first_pc != scene.entry_pc and scene.entry_pc in scene.stmts:
        if scene.entry_pc not in labels:
            labels[scene.entry_pc] = "ENTRY"
        lines.append("    JMP %s" % labels[scene.entry_pc] +
                     "                                   ; entry is not the lowest statement")

    try:
        speakers = script.dialog_speakers(scene, bank) if comments else {}
    except Exception:  # noqa: BLE001 - a comment aid; never break the listing
        speakers = {}
    for pc, st in scene.stmts.items():
        if own is not None and pc not in own:
            continue
        if pc in labels:
            lines.append("%s:" % labels[pc])
        addr = ("%04x: " % pc) if show_addr else ""
        note = ""
        if st.mnem == "DIALOG":
            body = "DIALOG #%d" % st.dialog_id
            if comments and dialog is not None:
                try:
                    s = dialog(st.dialog_id)
                    if s:
                        note = '"%s"' % s.replace("\n", "\\n").replace('"', "'")
                except Exception:
                    pass
            if pc in speakers:
                who = speakers[pc]
                who = {"player": "MC", "narration": "Narration"}.get(who, who)
                note = ("%s: %s" % (who, note)).rstrip()
        elif st.op < 0xFFF0:
            args = [operand_text(buf, a, st.op, i) for i, a in enumerate(st.args)]
            body = action_line(st.op, args) if friendly else action_text("op%d" % st.op, args)
            if comments:
                pretty = None
                try:
                    arg_strs = script.stmt_arg_strs(buf, st)
                    pretty = script.render_action(st.op, arg_strs)
                    if pretty is None and friendly and any(a.startswith("tag") for a in args):
                        # a tag3 / tag4 constant: show it as the actor / map it names
                        pretty = action_line(st.op, [n if a.startswith("tag") else a
                                                     for a, n in zip(args, arg_strs)])
                except Exception:
                    pretty = None
                bits = []
                if pretty and pretty.replace(" ", "") != body.replace(" ", ""):
                    bits.append(pretty)             # only when it says more than the statement
                if st.op in script.EMF_ENTRY_OPS:
                    ai = script.EMF_ENTRY_OPS[st.op]
                    if ai < len(st.args):
                        try:
                            nm = script.emf_entry_name(int(script.arg_repr(buf, st.args[ai])))
                            if nm:
                                bits.append(nm)
                        except (ValueError, TypeError):
                            pass
                note = "  ".join(bits)
        else:
            mn = st.mnem
            body = _control_body(buf, st, tgt)
            if mn in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED") and comments:
                note = _choice_note(st.items, dialog, _choice_results(scene, bank, pc))
        line = "    %s%s" % (addr, body)
        if comments and script.MAIN_SCENARIO_NAME in body:
            cps = _checkpoint_note(body)
            note = "  ".join(x for x in (note, cps) if x)
        if note:
            line = "%-52s ; %s" % (line, note)
        lines.append(line)
        nxt = pc + st.size
        if own is not None and st.falls_through and not st.terminator and nxt not in own:
            lines.append("    JMP 0x%04x" % nxt)    # it runs on into shared code: say so
    return "\n".join(lines)


def _control_body(buf, st, tgt):
    """The listing text of control statement `st` (no address, no comment); `tgt(pc)` writes
    a jump target (a label, or 0xPC)."""
    mn = st.mnem
    if mn == "FRAME":
        return "FRAME %d" % (st.items[0] if st.items else 0)
    if mn == "DIALOG":
        return "DIALOG #%d" % st.dialog_id
    if mn in ("CALL", "JMP"):
        return "%s %s" % (mn, tgt(st.code_targets[0] if st.code_targets else None))
    if mn in ("EVAL", "RET_NZ"):
        return "%s %s" % (mn, _cond_text(buf, st.expr_refs[0] if st.expr_refs else None))
    if mn in ("BR_Z", "BR_NZ"):
        return "%s %s -> %s" % (mn, _cond_text(buf, st.expr_refs[0] if st.expr_refs else None),
                                tgt(st.code_targets[0] if st.code_targets else None))
    if mn in ("SWITCH", "SWITCH_CLAMP"):
        return "%s %s -> %s" % (mn, _cond_text(buf, st.expr_refs[0] if st.expr_refs else None),
                                ", ".join(tgt(t) for t in st.code_targets))
    if mn == "JMP_RAND":
        return "JMP_RAND %s" % ", ".join(tgt(t) for t in st.code_targets)
    if mn == "JMP_WEIGHTED":
        return "JMP_WEIGHTED " + ", ".join("%s -> %s" % (_cond_text(buf, e), tgt(t))
                                          for t, e in zip(st.code_targets, st.expr_refs))
    if mn == "PROMPT_CHOICE":
        c0 = st.code_targets[0] if st.code_targets else None
        last = st.code_targets[len(st.items)] if len(st.code_targets) > len(st.items) else None
        # the CANCEL slot is never taken; written only when it isn't the default
        parts = ["CANCEL -> %s" % tgt(c0)] if (c0 != last or not st.items) else []
        for k, item in enumerate(st.items):
            t = st.code_targets[k + 1] if k + 1 < len(st.code_targets) else None
            parts.append("#%d -> %s" % (item, tgt(t)))
        return "PROMPT_CHOICE " + ", ".join(parts)
    if mn == "PROMPT_CHOICE_FORCED":
        parts = []
        for k, item in enumerate(st.items):
            t = st.code_targets[k] if k < len(st.code_targets) else None
            parts.append("#%d -> %s" % (item, tgt(t)))
        return "PROMPT_CHOICE_FORCED " + ", ".join(parts)
    return mn


def statement_text(buf, st):
    """One statement as a listing line with absolute targets (0xPC): what the Edit
    instruction window starts from. Assembles back to the same statement."""
    if st.op < 0xFFF0:
        return action_line(st.op, [operand_text(buf, a, st.op, i) for i, a in enumerate(st.args)])
    return _control_body(buf, st, lambda t: "0x0000" if t is None else "0x%04x" % t)


def _checkpoint_note(body):
    """'270 = Before Idra Cave' for every story-checkpoint literal compared with / stored
    into REG_MAIN_SCENARIO in a statement (names from the developers' story debug menus,
    opcode_meta.STORY_CHECKPOINTS)."""
    out = []
    for v in re.findall(re.escape(script.MAIN_SCENARIO_NAME) + r"\s*(?:==|!=|>=|<=|=|<|>)\s*(\d+)", body):
        nm = script.meta.story_checkpoint_name(int(v))
        if nm and "%s = %s" % (v, nm) not in out:
            out.append("%s = %s" % (v, nm))
    return "; ".join(out)


def _cond_text(buf, off):
    t = operand_text(buf, off)
    if t.startswith("(") or t.startswith("@"):
        return t
    return "(%s)" % t


def _choice_results(scene, bank, pc):
    """script.choice_results for the choice at pc of `scene` (None: reg0 untouched)."""
    try:
        stmts = list(scene.stmts.values())
        idx = next(i for i, s in enumerate(stmts) if s.pc == pc)
        return script.choice_results(bank.data, stmts, idx)
    except Exception:  # noqa: BLE001 -- a comment aid only
        return None


def _choice_note(items, dialog, results=None):
    """The options' text for the listing comment; with `results` (script.choice_results, a
    menu behind a visibility mask) each also says the reg0 its pick writes."""
    if dialog is None and results is None:
        return ""
    out = []
    for k, it in enumerate(items):
        try:
            s = dialog(it) if dialog is not None else None
        except Exception:
            s = None
        txt = ('"%s"' % s.replace("\n", " / ").replace('"', "'")[:40]) if s else "#%d" % it
        if results is not None and k < len(results):
            shown = results[k][1]
            txt += " (reg0=%d%s)" % (k, "" if shown is not False else ", hidden")
        elif not s:
            continue
        out.append(txt)
    return " | ".join(out)


# ---- round-trip helpers (used by the selftest and the GUI) --------------------------------
def scene_signature(scene, buf):
    """A position-independent signature of a scene's statements in pc order:
    [(mnemonic, dialog/items, [operand texts], [target ordinals])]. Two scenes with
    the same signature play the same content."""
    pcs = list(scene.stmts)
    # Leading unconditional jumps into the scene are plumbing, not content: the
    # `JMP ENTRY` scene_listing emits when the entry is not the lowest statement, and
    # the `JMP` an older toolkit's rewrite_scene left at the old entry (possibly both,
    # chained). Drop them so a scene and its re-assembled copy compare equal.
    for _ in range(4):
        if not pcs:
            break
        first = scene.stmts[pcs[0]]
        if (first.mnem == "JMP" and first.code_targets and first.code_targets[0] in scene.stmts
                and first.code_targets[0] != pcs[0]):
            pcs = pcs[1:]
        else:
            break
    order = {pc: i for i, pc in enumerate(pcs)}
    sig = []
    for pc in pcs:
        st = scene.stmts[pc]
        ops = [operand_text(buf, a) for a in (st.args if st.op < 0xFFF0 else st.expr_refs)]
        tg = [order.get(t, "ext:%d" % t) for t in st.code_targets]
        sig.append((st.op, st.dialog_id, tuple(st.items), tuple(ops), tuple(tg)))
    return sig
