"""rf3.mc (MYCF) cutscene / event Script-VM bytecode.

RF4's cutscenes and scripted NPC events are *compiled bytecode* run by the engine's
Script VM (`Script_VMStep`). The whole game's script logic lives in one file,
`rom:/script/rf3.mc` (archive 15209), a `MYCF` container. Dialogue *text* is separate,
in the per-locale `rf3mc.<locale>` TEXT archives (use `textdb` for those).

This module parses the MYCF container, walks the bytecode, and disassembles each scene
into a readable listing (opcode names + resolved dialogue). It is *structure-preserving*:
`Container.build()` re-emits the original bytes exactly, so edits round-trip byte-perfect.

Container layout (see project_rf4s_script_vm memory for the full RE):
  header(9 u32) | section-table-1 (248 primary banks) | section-table-2 (872 tail banks)
              | region-B (global index) | primary bank data | tail bank data
Each *bank* is a <=64 KB self-contained unit; the VM PC is a u16 within the bank.
A bank carries a *type table* (u16 @ bank+4*type+2 -> entry-list offset); each entry is
`5*size+4` bytes and its `event_id` (u16 @ entry+2) is the code PC of one scene.

Bytecode = u16 tokens. op > 0xFFF0 are control flow (Script_VMStep, RF4S.exe+0x23EF60);
everything else is an *action* opcode indexing g_sceneActionHandlerTable (702 slots, see
DISPATCHABLE_ACTION_OPS; names in script_opcodes.json).
"""
from __future__ import annotations
import json
import re
import struct
from collections import OrderedDict

from .refdata import refdata_path

MAGIC = b"MYCF"

# ---- opcode name table (dumped from g_scriptVMOpDispatchTable_400slots) -------------
with open(refdata_path("script_opcodes.json"), "r", encoding="utf-8") as _f:
    OPCODE_NAMES = {int(k): v for k, v in json.load(_f).items()}


def _strip_op_name(nm):
    for pre in ("Script_VMOp_", "ScriptVM_Op_", "ScriptVMOp_", "rf3sScriptExecExtCmd_"):
        if nm.startswith(pre):
            return nm[len(pre):]
    return nm


# Precomputed: opcode_name() is called once per decoded statement (tens of millions of
# times in corpus sweeps) — the per-call prefix-strip was a measurable share of decode.
_OPCODE_NAME = {k: _strip_op_name(v) for k, v in OPCODE_NAMES.items() if v}


def opcode_name(op):
    nm = _OPCODE_NAME.get(op)
    return nm if nm is not None else "op%d" % op


# ---- cutscene-author friendly layer (opcode_meta) -----------------------------------
# opcode_name(op) returns the technical IDA-symbol name (RE ground truth). The functions
# below add the author-facing mnemonic / description / arg names for the editor UI.
try:
    from . import opcode_meta as meta
except ImportError:                                   # loaded as a loose module
    import opcode_meta as meta


def opcode_mnemonic(op):
    """Short cutscene-author mnemonic (e.g. 'WarpPlayer'). Falls back to 'opN'."""
    return meta.mnemonic(op)


def scene_summary(sc):
    """A short one-line summary of a scene by its first meaningful op, for the editor's scene
    list when the scene carries no dialogue (so a control/action-only scene isn't a blank row).
    Returns e.g. '-> FadeScreen', '-> SWITCH', '(FRAME)', or '' for an empty scene."""
    stmts = list(sc.stmts.values())
    act = next((s for s in stmts if s.op < 0xFFF0), None)
    if act is not None:
        return "-> " + opcode_mnemonic(act.op)
    nonterm = next((s for s in stmts if s.mnem not in ("FRAME", "RET")), None)
    if nonterm is not None:
        return "-> " + nonterm.mnem
    if stmts:
        return "(" + stmts[0].mnem + ")"
    return ""


def op_from_name(name):
    """Opcode number for a curated mnemonic (case-insensitive), or None. Lets the editor
    accept an op by name (e.g. 'GivePlayerItem') instead of a raw number."""
    return meta.op_from_mnemonic(name)


def find_ops(query, limit=12):
    """Search opcodes by a substring of the mnemonic (or description). Returns
    [(op, mnemonic), ...] for op discovery / 'did you mean' suggestions."""
    return meta.find_ops(query, limit)


def render_action(op, arg_strs):
    """Value-decoded 'Name(decoded args)' for enum-arg opcodes (e.g. GetPlayerVariable),
    or None to use the default name(args) rendering. See opcode_meta.render_action."""
    return meta.render_action(op, arg_strs)


def opcode_arg_names(op):
    """Positional argument names for an action opcode (meta, then ARG_HINTS)."""
    names = meta.arg_names(op)
    return names if names else ARG_HINTS.get(op, [])


def opcode_tooltip(op, arg_values=None):
    """Multi-line hover-tooltip text for an action opcode (see opcode_meta.tooltip)."""
    return meta.tooltip(op, arg_values=arg_values)


def opcode_prototype(op):
    """C-style signature string, e.g. 'SetSpeaker(character, side, face, trigger1, trigger2, trigger3)'."""
    return meta.prototype(op)


def opcode_arg_hint(op, i):
    """Brief explanation of argument i of opcode op (by its name), or None."""
    return meta.arg_hint(op, i)


def opcode_arg_hint_by_name(name):
    """Brief explanation for a bare argument name (e.g. 'target'), or None."""
    return meta.arg_hint_by_name(name)


def enum_arg_choices(op, arg_index):
    """List of (int_value, short_label, description) for an enum-valued arg
    (e.g. TriggerWorldInteractionAction arg 0). Empty when the arg is not a
    known enum. Editors can use this to render a picker instead of a bare
    number field."""
    return meta.enum_arg_choices(op, arg_index)


def enum_arg_label(op, arg_index, value):
    """Short label for a value of an enum-valued arg (e.g. 'Trigger_SaveMenu'),
    or None if the arg is not an enum or the value isn't in the enum."""
    return meta.enum_arg_label(op, arg_index, value)


def enum_arg_description(op, arg_index, value):
    """Long description for a value of an enum-valued arg, or None."""
    return meta.enum_arg_description(op, arg_index, value)


def opcode_describe(op):
    """One-line description of what an action opcode does."""
    return meta.describe(op)


def opcode_category(op):
    return meta.category(op)


# ---- portrait-line (dialogue) helpers ------------------------------------------------
PORTRAIT_SPEAKERS = meta.PORTRAIT_SPEAKERS
PORTRAIT_SPEAKER_TAGS = meta.PORTRAIT_SPEAKER_TAGS


def portrait_speaker_slot(op):
    """(speaker_slot, parity/side) for a portrait-line opcode 16..75, else None."""
    return meta.portrait_speaker_slot(op)


def portrait_speaker_name(op):
    """Character name a portrait-line opcode speaks as, else None."""
    return meta.portrait_speaker_name(op)


def portrait_speaker_tag(op):
    """Identifier-safe speaker tag (e.g. 'Vishnal', 'MC') for the SetSpeaker$<tag>
    mnemonic; None if not a portrait op."""
    return meta.portrait_speaker_tag(op)


def portrait_opcode(slot, side=0):
    """Opcode for a portrait line: speaker `slot` (0..29) on `side` (0=left, 1=right)."""
    if not (0 <= slot <= 29):
        raise ScriptError("portrait speaker slot %d out of range (0..29)" % slot)
    return 16 + slot * 2 + (1 if side else 0)


def is_portrait_op(op):
    return 16 <= op <= 75


PORTRAIT_EMOTES = meta.PORTRAIT_EMOTES


def portrait_emote_name(emote_id):
    """Default-row mood name for a SetSpeaker emote/mood id (186..192), else None."""
    return meta.portrait_emote_name(emote_id)


def control_tooltip(mnem):
    """Hover-tooltip text for a control opcode (keyed by its mnemonic)."""
    return meta.control_tooltip(mnem)


# control opcodes (>= 0xFFF0) handled inline by Script_VMStep
CONTROL = {
    0xFFFF: "RET", 0xFFFE: "CALL", 0xFFFD: "RET_NZ", 0xFFFC: "DIALOG",
    0xFFFB: "EVAL", 0xFFFA: "JMP", 0xFFF9: "BR_NZ", 0xFFF8: "BR_Z",
    0xFFF7: "SWITCH", 0xFFF6: "SWITCH_CLAMP", 0xFFF5: "PROMPT_CHOICE_FORCED", 0xFFF4: "PROMPT_CHOICE",
    0xFFF3: "JMP_RAND", 0xFFF2: "JMP_WEIGHTED", 0xFFF1: "FRAME",
}


class ScriptError(Exception):
    pass


class Statement:
    """One decoded bytecode statement."""
    __slots__ = ("pc", "op", "mnem", "size", "args", "code_targets",
                 "expr_refs", "dialog_id", "items", "falls_through", "terminator")

    def __init__(self, pc, op, mnem, size, args=(), code_targets=(),
                 expr_refs=(), dialog_id=None, items=(),
                 falls_through=True, terminator=False):
        self.pc = pc
        self.op = op
        self.mnem = mnem
        self.size = size
        self.args = list(args)
        self.code_targets = list(code_targets)
        self.expr_refs = list(expr_refs)
        self.dialog_id = dialog_id
        # PROMPT_CHOICE / PROMPT_CHOICE_FORCED inline u32 items — direct values, NOT expression
        # offsets. For PROMPT_CHOICE these are string ids in rf3mc.<locale>.
        self.items = list(items)
        self.falls_through = falls_through
        self.terminator = terminator


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0] if 0 <= o <= len(b) - 2 else None


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0] if 0 <= o <= len(b) - 4 else None


def eval_expr(buf, off):
    """Statically evaluate the RPN expression at byte offset `off` in a bank.

    Action-op arguments are not literals -- each is a u16 offset to a little postfix
    expression in the bank's data pool (Script_EvalExpressionBytecode). Most are a
    single push-immediate, so they resolve to a small int. Returns (value, ok); ok is
    False when the expression needs runtime state (a variable or a typed operand).

    Arithmetic is the engine's (Script_EvalExpressionBytecode, RF4S.exe+0x23E1C0): int32
    values that wrap, C division/remainder that truncate toward zero, x/0 = INT_MAX for
    x > 0, INT_MIN for x < 0 and 0 for 0, and x%0 = 0. A tag byte the evaluator has no
    case for (anything but the pushes, operators 0x80..0x97 and the 0x00 terminator --
    including 3/4/5/0x11..0x13 after the first byte) makes it return without producing
    a value, so that is reported as not static (ok=False). Tag 5 (u16) and 0x11..0x13
    are only meaningful as the WHOLE operand (Script_EvalExpressionOrVar, RF4S.exe+0x23EA10)."""
    n = len(buf)
    if 0 <= off < n:
        t0 = buf[off]
        if t0 == 5:                          # leaf u16 literal (OrVar kind 7)
            v = _u16(buf, off + 1)
            return (v, True) if v is not None else (None, False)
        if t0 in (3, 4, 0x11, 0x12, 0x13):  # typed constants / null / zero / self leaves
            return (None, False)
    stack = []
    p = off
    for _ in range(128):
        if not (0 <= p < n):
            return (None, False)
        t = buf[p]
        if t == 0x14:                       # push 0
            stack.append(0); p += 1
        elif t == 0x15:                     # push -1
            stack.append(-1); p += 1
        elif t == 0x16:                     # push 1
            stack.append(1); p += 1
        elif t == 0x17:                     # push u8 imm
            if p + 1 >= n:
                return (None, False)
            stack.append(buf[p + 1]); p += 2
        elif t == 0x18:                     # push s8 imm
            if p + 1 >= n:
                return (None, False)
            stack.append(struct.unpack_from("<b", buf, p + 1)[0]); p += 2
        elif 7 <= t <= 0x10:                # VM register read reg0..reg9 -> runtime
            return (None, False)            # (Script_StackSlot_NormalizeToInt32 case 7..16)
        elif t == 0x19:                     # push u16 literal (unsigned)
            if p + 2 >= n:
                return (None, False)
            stack.append(struct.unpack_from("<H", buf, p + 1)[0]); p += 3
        elif t == 0x1A:                     # push s16 literal (signed)
            if p + 2 >= n:
                return (None, False)
            stack.append(struct.unpack_from("<h", buf, p + 1)[0]); p += 3
        elif t == 1:                        # push int32 literal (type-1 slot, pass-through)
            if p + 4 >= n:
                return (None, False)
            stack.append(struct.unpack_from("<i", buf, p + 1)[0]); p += 5
        elif t == 2:                        # packed variable reference -> runtime
            return (None, False)            # (NormalizeToInt32 case 2: bit-packed var id)
        elif t == 6:                        # var-array fetch -> runtime
            return (None, False)
        elif 0x80 <= t <= 0x97:             # operator (token - 128)
            op = t - 128
            if op == 0:
                p += 1
            elif op == 1:
                if not stack:
                    return (None, False)
                stack[-1] = _i32(-stack[-1]); p += 1
            elif op == 2:
                if not stack:
                    return (None, False)
                stack[-1] = int(stack[-1] == 0); p += 1
            elif 3 <= op <= 15:
                if len(stack) < 2:
                    return (None, False)
                b = stack.pop(); a = stack.pop()
                stack.append(_expr_binop(op, a, b)); p += 1
            else:                           # compound-assign (16..23) -> runtime
                return (None, False)
        elif t == 0:                        # terminator
            return (stack[-1] if stack else None, True)
        else:                               # no evaluator case: returns without a value
            return (None, False)
    return (None, False)                    # unterminated / runaway stream


def _i32(v):
    """Wrap to a signed 32-bit int (the evaluator's value slots are int32)."""
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def _c_div(a, b):
    """C/x86 idiv: truncates toward zero. Engine x/0: INT_MAX (x>0), INT_MIN (x<0), 0 (x==0)."""
    if b == 0:
        return 0x7FFFFFFF if a > 0 else (-0x80000000 if a < 0 else 0)
    q = abs(a) // abs(b)
    return _i32(q if (a < 0) == (b < 0) else -q)


def _c_mod(a, b):
    """C remainder (sign of the dividend); the engine returns 0 for x%0."""
    if b == 0:
        return 0
    return _i32(a - b * int(_c_div(a, b)))


def _expr_binop(op, a, b):
    """One binary operator of Script_EvalExpressionBytecode (a = first-pushed/left)."""
    if op == 3:
        return _i32(a * b)
    if op == 4:
        return _c_div(a, b)
    if op == 5:
        return _c_mod(a, b)
    if op == 6:
        return _i32(a + b)
    if op == 7:
        return _i32(a - b)
    return {8: int(a < b), 9: int(a > b), 10: int(a <= b), 11: int(a >= b),
            12: int(a == b), 13: int(a != b), 14: int(bool(a) and bool(b)),
            15: int(bool(a) or bool(b))}[op]


# RPN expression operators (token byte - 0x80). Mirrors Script_EvalExpressionBytecode
# (RF4S.exe+0x23E1C0): unary neg/not, binary arith/compare/logic, plus the
# compound-assign variants 16..23 that write the result back into the target variable.
_EXPR_BINOP = {3: "*", 4: "/", 5: "%", 6: "+", 7: "-", 8: "<", 9: ">",
               10: "<=", 11: ">=", 12: "==", 13: "!=", 14: "&&", 15: "||"}
_EXPR_ASSIGN = {16: "=", 17: "*=", 18: "/=", 19: "%=", 20: "+=", 21: "-=",
                22: "&&=", 23: "||="}

# Optional callback fn(enc:int) -> name(str|None) that renders a token-0x02 packed
# variable ref as its emdeb.bin FLG_/REG_ name (see install_emflags_var_resolver).
# None => disasm_expr falls back to the raw `var:0xNN` form. Module-global so every
# disasm_expr / arg_repr call site picks it up once installed.
_packed_var_resolver = None


def set_packed_var_resolver(fn):
    """Install (or clear, with None) the packed-variable name resolver used by
    disasm_expr for token-0x02 operands."""
    global _packed_var_resolver
    _packed_var_resolver = fn


def install_emflags_var_resolver(container, emf_table, with_offset=False):
    """Wire disasm_expr to render packed vars as emdeb.bin names, using `container`'s
    header masks + an EmFlagTable-like object (needs `.by_offset(bit)` -> obj with
    `.name`). Returns the installed resolver. Unknown offsets stay `var:0xNN`.
    If `with_offset`, names are suffixed `@bit` for disambiguation."""
    def resolve(enc):
        bit_off, width, signed = container.unpack_var(enc)
        v = emf_table.by_offset(bit_off)
        if v is None:
            return None
        # The name stands for (offset, emdeb width, unsigned) -- that is what the assembler
        # re-encodes it as (scriptasm.make_resolver). A ref with another width or the sign
        # bit (none in the shipped corpus) keeps its raw var:0x form so it round-trips.
        if width != getattr(v, "bit_width", width) or signed:
            return None
        return ("%s@%d" % (v.name, bit_off)) if with_offset else v.name
    set_packed_var_resolver(resolve)
    return resolve


def _outer_parens_match(s):
    """True if s is fully wrapped by one matching outer '(' .. ')' pair."""
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


# ---- typed-constant leaves (tags 3 / 4) ----------------------------------------------
# The engine calls tags 3/4 "local"/"global" variable references (Script_EvalExpressionOrVar,
# RF4S.exe+0x23EA10, reports kind 2 / kind 3), but NOTHING dereferences them:
# Script_PrepActionArgs (RF4S.exe+0x23EE10) pushes every argument as a raw (value, kind) pair
# and the action handlers read only the value slot (checked 2026-09-23 on ops 107, 227, 246,
# 266, 318, 332, 443, 628). A tag-3/4 leaf is therefore just the constant N; the tag is the
# script compiler's note of which symbol table N came from. What N MEANS is decided by the
# argument slot, not by the tag -- so the listing only names it where the slot is known:
#   * tag 3 in a character slot -> actor(Name). Character ids are the rf3TxtNpc space the
#     handlers branch on (0 = player, 1..47 villagers/travelers/soldiers, 48+ monsters).
#     82% of the 20,776 tag-3 argument uses sit in registered char-id slots; the rest are
#     NPC lists, camera targets -- and a few that are NOT characters (op 629 loads sub-event
#     ids 107..143 compared with REG_SUBEV_NOW; quest-request kinds; op 543's item id).
#   * tag 4 in a location slot -> map(MAP_NAME): the schedule ops 227/228 (compared with the
#     NPC actor's +84 current-map field, Npc_GetCurrentScheduleId RF4S.exe+0x227230 --
#     the player branch uses field_54), 246 (written to NPC +188, the same field
#     Npc_GetCurrentScheduleId falls back to) and 266/267.
#   * anything else stays tag3(N) / tag4(N), in decimal.
# 56,119 tag-3/4 argument leaves in rf3.mc, none with bits above 16 set. scriptasm accepts
# actor(Name|N), map(MAP_NAME|N) and tag3(N) / tag4(N) -- all to the same bytes. The listing
# (scriptasm.operand_text) always writes the raw tag3 / tag4 form, since actor / map are our own
# reading of the slot, and puts the named form in the statement's comment.
_ACTOR_NAMES = None          # id -> display name (the game's rf3TxtNpc, see gamenames)
_ACTOR_GEN = None
_ACTOR_UNIQUE = None         # normalised unique name -> id


def _norm_leaf_name(name):
    return " ".join(str(name).replace("_", " ").split()).lower()


def _actor_tables():
    global _ACTOR_NAMES, _ACTOR_UNIQUE, _ACTOR_GEN
    from . import gamenames
    gen = gamenames.generation()
    if _ACTOR_NAMES is None or _ACTOR_GEN != gen:
        _ACTOR_GEN = gen
        names = dict(gamenames.table("characters"))
        counts = {}
        for v in names.values():
            counts[_norm_leaf_name(v)] = counts.get(_norm_leaf_name(v), 0) + 1
        uniq = {_norm_leaf_name(v): k for k, v in names.items()
                if k != 0 and counts[_norm_leaf_name(v)] == 1}
        # a name shared with alternate forms outside the character range (Clorica 2 / 308,
        # Ventuswill 21 / 235 / 982) belongs to its one id below 48, the id space the
        # character handlers use; names shared inside the range (Traveler, Soldier) stay numeric
        low = {}
        for k, v in names.items():
            if 0 < k < 48:
                low.setdefault(_norm_leaf_name(v), []).append(k)
        for nm, ids in low.items():
            if len(ids) == 1 and nm not in uniq:
                uniq[nm] = ids[0]
        for alias in ("player", "lest", "frey", "lest/frey"):
            uniq[alias] = 0
        _ACTOR_NAMES, _ACTOR_UNIQUE = names, uniq
    return _ACTOR_NAMES, _ACTOR_UNIQUE


def actor_leaf_text(n):
    """Listing form of a tag-3 leaf: actor(Forte), actor(player), or actor(27) when the
    name is shared (Traveler, Soldier, ...) or unknown -- always re-assemblable."""
    names, uniq = _actor_tables()
    if n == 0:
        return "actor(player)"
    nm = names.get(n)
    if nm and uniq.get(_norm_leaf_name(nm)) == n:
        return "actor(%s)" % nm
    return "actor(%d)" % n


def actor_leaf_value(text):
    """Inverse of actor_leaf_text's argument: a unique name, 'player' or a number -> id,
    or None when the name is unknown or ambiguous."""
    t = str(text).strip()
    try:
        return int(t, 0)
    except ValueError:
        return _actor_tables()[1].get(_norm_leaf_name(t))


def map_leaf_text(n):
    """Listing form of a tag-4 leaf: map(MAP_CITY_00), or map(N) when N has no map file."""
    try:
        from . import map_names
        nm = map_names.map_file(n) if n <= 0xFFFF else None
    except Exception:
        nm = None
    return "map(%s)" % nm if nm else "map(%d)" % n


def map_leaf_value(text):
    t = str(text).strip()
    try:
        return int(t, 0)
    except ValueError:
        try:
            from . import map_names
            return map_names.map_id_for_file(t)
        except Exception:
            return None


def leaf_description(tag, n):
    """One-line human description of a tag-3/4 leaf, for tooltips."""
    if tag == 3:
        names = _actor_tables()[0]
        who = "the player" if n == 0 else (names.get(n) or "unnamed")
        return "actor %d = %s (tag-3 constant; the handler receives %d)" % (n, who, n)
    try:
        from . import map_names
        friendly = map_names.map_name(n)
    except Exception:
        friendly = None
    return "map %d = %s%s (tag-4 constant; the handler receives %d)" % (
        n, map_leaf_text(n)[4:-1], (" \"%s\"" % friendly) if friendly else "", n)


def disasm_expr(buf, off, _maxtok=512):
    """Disassemble the RPN condition/value expression at byte offset `off` into a
    readable infix string. Mirrors the engine's postfix evaluator
    Script_EvalExpressionBytecode (RF4S.exe+0x23E1C0) and the leaf handler
    Script_EvalExpressionOrVar (RF4S.exe+0x23EA10).

    Leaves: int literals, packed variables (var:0xNN), VM registers (reg0..reg9),
    var-array loads (arr[..]), local/global vars. Operators build parenthesised
    infix. Returns (text, size_in_bytes); text is '?' for an empty/invalid stream."""
    n = len(buf)
    if not (0 <= off < n):
        return ("?", 0)
    # Leading simple tags are resolved by Script_EvalExpressionOrVar without entering
    # the postfix evaluator -- handle them as single leaves.
    t0 = buf[off]
    if t0 == 3:
        return ("tag3(%d)" % (_u32(buf, off + 1) or 0), 5)
    if t0 == 4:
        return ("tag4(%d)" % (_u32(buf, off + 1) or 0), 5)
    if t0 == 5:
        return (str(_u16(buf, off + 1) or 0), 3)
    if t0 == 0x11:
        return ("null", 1)
    if t0 == 0x12:
        return ("0", 1)
    if t0 == 0x13:
        return ("self", 1)
    # Otherwise it is a postfix token stream terminated by 0x00.
    st = []
    p = off
    for _ in range(_maxtok):
        if not (0 <= p < n):
            break
        t = buf[p]
        if t == 0x00:                                 # END
            p += 1
            break
        if t == 0x01:                                 # push int32 literal
            v = _u32(buf, p + 1) or 0
            st.append(str(v - 0x100000000 if v >= 0x80000000 else v)); p += 5
        elif t == 0x02:                               # push packed variable ref
            enc = _u32(buf, p + 1) or 0
            nm = _packed_var_resolver(enc) if _packed_var_resolver else None
            st.append(nm if nm else "var:0x%X" % enc); p += 5
        elif t == 0x06:                               # var_array[idx] fetch
            st.append("arr[0x%X]" % (_u16(buf, p + 1) or 0)); p += 3
        elif 0x07 <= t <= 0x10:                       # VM register reg0..reg9
            st.append("reg%d" % (t - 7)); p += 1
        elif t == 0x14:
            st.append("0"); p += 1
        elif t == 0x15:
            st.append("-1"); p += 1
        elif t == 0x16:
            st.append("1"); p += 1
        elif t == 0x17:                               # u8 imm
            st.append(str(buf[p + 1] if p + 1 < n else 0)); p += 2
        elif t == 0x18:                               # s8 imm
            st.append(str(struct.unpack_from("<b", buf, p + 1)[0] if p + 1 < n else 0)); p += 2
        elif t == 0x19:                               # u16 imm
            st.append(str(_u16(buf, p + 1) or 0)); p += 3
        elif t == 0x1A:                               # s16 imm
            st.append(str(struct.unpack_from("<h", buf, p + 1)[0] if p + 2 < n else 0)); p += 3
        elif t >= 0x80:
            op = t - 0x80
            if op == 0:                               # nop
                p += 1
            elif op == 1:                             # unary neg
                a = st.pop() if st else "?"
                st.append("-(%s)" % a); p += 1
            elif op == 2:                             # logical not
                a = st.pop() if st else "?"
                st.append("!(%s)" % a); p += 1
            elif op in _EXPR_BINOP:                   # binary a OP b (a=below, b=top)
                b = st.pop() if st else "?"
                a = st.pop() if st else "?"
                st.append("(%s %s %s)" % (a, _EXPR_BINOP[op], b)); p += 1
            elif op in _EXPR_ASSIGN:                  # compound-assign, writes back to a
                b = st.pop() if st else "?"
                a = st.pop() if st else "?"
                st.append("(%s %s %s)" % (a, _EXPR_ASSIGN[op], b)); p += 1
            else:
                break                                 # unexpected operator -> stop
        else:
            break                                     # unknown tag -> stop
    text = st[-1] if st else "?"
    if _outer_parens_match(text):
        text = text[1:-1]                             # drop one redundant outer paren pair
    return (text, p - off)


def expr_literals(buf, off, _maxtok=512):
    """Return the in-place-editable integer literals in the RPN expression at `off`.

    A list of (literal_offset, current_value, byte_width) in stream order. Each offset
    points at a literal TAG byte that `Bank.set_expr_value` can patch in place: tags
    0x17/0x18 (1-byte u8/s8 immediate) and 0x19/0x1A (2-byte u16/s16). Fixed pushes
    (0/-1/1), variables, VM registers and array loads carry no range-editable literal and
    are skipped. The walk mirrors `disasm_expr` exactly, so the offsets it yields line up
    with the literals shown in the disassembly -- this is what lets the editor expose a
    control-op guard/value expression (a BR_Z threshold, an EVAL value) for editing, not
    just display."""
    n = len(buf)
    out = []
    if not (0 <= off < n):
        return out
    if buf[off] in (3, 4, 5, 0x11, 0x12, 0x13):       # leading single leaf -> no postfix literal
        return out                                    # (tag3/tag4/OrVar-u16/null/0/self)
    p = off
    for _ in range(_maxtok):
        if not (0 <= p < n):
            break
        t = buf[p]
        if t == 0x00:                                 # END terminator
            break
        if t == 0x01:                                 # int32 literal (not set_expr_value-editable)
            p += 5
        elif t == 0x02:                               # packed variable ref
            p += 5
        elif t == 0x06:                               # arr[idx] fetch
            p += 3
        elif 0x07 <= t <= 0x10:                       # reg0..reg9
            p += 1
        elif t in (0x14, 0x15, 0x16):                 # fixed push 0 / -1 / 1
            p += 1
        elif t == 0x17:                               # u8 imm  -- editable
            out.append((p, buf[p + 1] if p + 1 < n else 0, 1)); p += 2
        elif t == 0x18:                               # s8 imm  -- editable
            v = struct.unpack_from("<b", buf, p + 1)[0] if p + 1 < n else 0
            out.append((p, v, 1)); p += 2
        elif t == 0x19:                               # u16 imm -- editable
            out.append((p, _u16(buf, p + 1) or 0, 2)); p += 3
        elif t == 0x1A:                               # s16 imm -- editable
            v = struct.unpack_from("<h", buf, p + 1)[0] if p + 2 < n else 0
            out.append((p, v, 2)); p += 3
        elif t >= 0x80:                               # operator token
            p += 1
        else:
            break                                     # unknown tag -> stop
    return out


def expr_var_refs(buf, off, _maxtok=512):
    """Return the packed-variable (token 0x02) references in the RPN expression at `off`.

    A list of (offset, enc) in stream order; `enc` is the raw u32 the packed-var resolver
    decodes to an emdeb.bin `FLG_`/`REG_` name. Walks the WHOLE expression (same token walk
    as `disasm_expr` / `expr_literals`), so it catches var refs nested after other tokens --
    e.g. the `FLG_Y` in `(REG_X == 5 && FLG_Y)` -- not just a leading one. Tokens 3/4
    (`actor(..)` / `map(..)`, the engine's "local/global var" tags) are typed constants,
    not variables, and are NOT included."""
    n = len(buf)
    out = []
    if not (0 <= off < n):
        return out
    if buf[off] in (3, 4, 5, 0x11, 0x12, 0x13):       # leading single leaf -> no postfix 0x02
        return out
    p = off
    for _ in range(_maxtok):
        if not (0 <= p < n):
            break
        t = buf[p]
        if t == 0x00:                                 # END terminator
            break
        if t == 0x02:                                 # packed variable ref
            out.append((p, _u32(buf, p + 1) or 0)); p += 5
        elif t == 0x01:                               # int32 literal
            p += 5
        elif t == 0x06:                               # arr[idx] fetch
            p += 3
        elif 0x07 <= t <= 0x10:                       # reg0..reg9
            p += 1
        elif t in (0x14, 0x15, 0x16):                 # fixed push 0 / -1 / 1
            p += 1
        elif t in (0x17, 0x18):                       # u8 / s8 imm
            p += 2
        elif t in (0x19, 0x1A):                       # u16 / s16 imm
            p += 3
        elif t >= 0x80:                               # operator token
            p += 1
        else:
            break                                     # unknown tag -> stop
    return out


# Tag-4 slots verified as MAP ids (see the typed-constant note above). For the variadic
# schedule queries every argument from index 1 on is a candidate map.
_MAP_LEAF_SLOTS = {(246, 1), (266, 1), (267, 1)}
_MAP_LEAF_VARIADIC = {227: 1, 228: 1}
# Tag-3 slots that are characters but carry a non-character label or no registry entry.
# 318: SetPackedGameFlag's id is a char id (bit 1007 + char = gift given on that NPC's
# birthday; NpcAi_OnReceivedThrownItem_AdvanceProgressAndDispatchReaction sets the same bit).
_ACTOR_LEAF_EXTRA = {(318, 0)}
_ACTOR_LABEL_WORDS = ("npc", "actor", "char id", "shopkeeper", "participant")
_NOT_ACTOR_WORDS = ("count", "item", "line", "content", "flag", "index", "kind", "value", "ctx",
                    "child", "monster", "event")


def _table_arg(op, ai):
    """opcode_table.json's entry for argument `ai` of `op` (trailing variadic args repeat the
    last one), or None when the op has no table row or no such argument."""
    row = meta.table_row(op)
    if not row or not row["args"]:
        return None
    args = row["args"]
    if ai < len(args):
        return args[ai]
    last = args[-1]
    txt = " ".join(str(last.get(k) or "") for k in ("name", "type", "values")).lower()
    if "..." in txt or "…" in txt or re.search(r"one or more|zero or more|variable|argc", txt):
        return last
    return None


def leaf_slot_kind(op, ai):
    """'actor', 'map' or None: what a tag-3 / tag-4 constant in argument `ai` of opcode
    `op` means. None = unknown slot (rendered as the raw tag3(N) / tag4(N) form)."""
    if op is None or ai is None:
        return None
    if (op, ai) in _MAP_LEAF_SLOTS or (op in _MAP_LEAF_VARIADIC and ai >= _MAP_LEAF_VARIADIC[op]):
        return "map"
    if (op, ai) in _ACTOR_LEAF_EXTRA:
        return "actor"
    reg = meta.ENUM_ARG_VALUES.get((op, ai))
    if reg is not None and (reg is meta.CHAR_IDS or reg is meta._CHAR_IDS_NPC):
        return "actor"
    arg = _table_arg(op, ai)
    if arg is not None:                          # opcode_table.json: decide by the arg's type
        typ = (arg.get("type") or "").lower()
        if re.search(r"\bmap ids?\b", typ):
            return "map"
        what = typ + " " + (arg.get("name") or "").lower()
        if "char id" in typ or (any(w in what for w in _ACTOR_LABEL_WORDS + ("character", "speaker", "villager"))
                                and not any(w in typ for w in _NOT_ACTOR_WORDS)):
            return "actor"
        return None
    names = opcode_arg_names(op) or []
    if ai < len(names):
        label = names[ai]
    elif names and ("…" in names[-1] or "variadic" in names[-1].lower()):
        label = names[-1]                        # trailing variadic args repeat the last one
    else:
        return None
    low = label.lower()
    if any(w in low for w in _ACTOR_LABEL_WORDS) and not any(w in low for w in _NOT_ACTOR_WORDS):
        return "actor"
    return None


def _zero_is_not_player(op, ai):
    """True where the slot documents 0 as something other than the player (all NPCs,
    the current one, ...): the no-0 char registry, or a '0 = all'-style label."""
    if meta.ENUM_ARG_VALUES.get((op, ai)) is meta._CHAR_IDS_NPC:
        return True
    arg = _table_arg(op, ai)
    if arg is not None:
        return bool(re.search(r"\b0\s*=\s*(all|every|the current|current|count|input|any|none)",
                              (arg.get("values") or "").lower()))
    names = opcode_arg_names(op) or []
    low = (names[ai] if ai < len(names) else (names[-1] if names else "")).lower().replace(" ", "")
    return any(z in low for z in ("0=all", "0=current", "0=count", "0=input", "0=any", "0=none"))


def arg_repr(buf, off, op=None, ai=None):
    """Human-readable form of an action-op argument (an expression offset): the
    resolved value when static, else the decoded infix expression, else `expr@0xNNNN`.
    With the statement's `op` and the argument index `ai`, a tag-3/4 constant in a known
    slot is named: actor(Forte), map(MAP_CITY_00) (see leaf_slot_kind)."""
    if (op is not None and 0 <= off < len(buf) and buf[off] in (0x11, 0x12, 0x13)
            and (op, ai) in meta.MODE_ARG_SLOTS):
        # the handler reads this argument's token KIND as its add / sub / set mode
        return meta.MODE_LEAF_WORDS[buf[off]]
    if op is not None and 0 <= off < len(buf) and buf[off] in (3, 4):
        kind = leaf_slot_kind(op, ai)
        n = _u32(buf, off + 1) or 0
        if buf[off] == 3 and kind == "actor":
            if n == 0 and _zero_is_not_player(op, ai):
                return "actor(0)"
            return actor_leaf_text(n)
        if buf[off] == 4 and kind == "map":
            return map_leaf_text(n)
    v, ok = eval_expr(buf, off)
    if ok and v is not None:
        return ("0x%X" % v) if v > 9999 else str(v)   # hex for big packed positives; decimal else
    txt, _ = disasm_expr(buf, off)
    return txt if txt and txt != "?" else ("expr@0x%04x" % off)



# Script ops that address GameFlags ZONE 2 directly (every handler adds the buffer's
# zone2_base = 4096; op 318 adds a further 1007). Verified 2026-09-23 in the handlers.
ZONE2_FLAG_OPS = {318: 1007, 443: 0, 444: 0, 445: 0}


def flag_arg_note(buf, off, op, ai):
    """Zone-2 label for the flag-id argument (arg 0) of ops 318/443/444/445 when it is a
    constant, e.g. 'NPC daily greeting done: char 5 Kiel (zone-2 1042, abs 5138)'; else None."""
    if op not in ZONE2_FLAG_OPS or ai != 0 or not (0 <= off < len(buf)):
        return None
    if buf[off] in (3, 4):
        v = _u32(buf, off + 1) or 0
    else:
        v, ok = eval_expr(buf, off)
        if not ok or v is None:
            return None
    try:
        from . import emflags
        return emflags.zone2_text(ZONE2_FLAG_OPS[op] + int(v))
    except Exception:
        return None


def stmt_arg_strs(buf, st):
    """arg_repr for every argument of statement `st`, with its slot context."""
    return [arg_repr(buf, x, st.op, i) for i, x in enumerate(st.args)]


def leaf_tooltip(buf, off, op=None, ai=None):
    """Hover text for an argument that is a tag-3/4 constant, else None."""
    if not (0 <= off < len(buf)) or buf[off] not in (3, 4):
        return None
    tag, n = buf[off], _u32(buf, off + 1) or 0
    kind = leaf_slot_kind(op, ai)
    if (tag, kind) in ((3, "actor"), (4, "map")):
        return leaf_description(tag, n)
    return ("typed constant %d (tag %d, written tag%d(%d)). The handler receives the number %d; "
            "this argument slot has no verified meaning, so it is not named."
            % (n, tag, tag, n, n))

def arg_is_settable(buf, off):
    """True if the expression at `off` is a single immediate whose value can be set in
    place (Bank.set_expr_value): a u8/s8/u16/s16 push, or a tag-3/4 typed constant
    (tag3(N) / tag4(N), read as actor(..) / map(..) -- a u32 the handler receives as-is)."""
    if not (0 <= off < len(buf)):
        return False
    return buf[off] in (0x17, 0x18, 0x19, 0x1A, 0x03, 0x04)


def arg_constant(buf, off):
    """(value, ok) for an action argument: eval_expr's static value, or the number a
    tag-3/4 typed constant hands the handler (Script_PrepActionArgs never dereferences
    them -- see the typed-constant note above). ok=False for genuinely runtime args."""
    v, ok = eval_expr(buf, off)
    if ok:
        return v, True
    if 0 <= off < len(buf) and buf[off] in (3, 4):
        return _u32(buf, off + 1) or 0, True
    return None, False


# Per-opcode argument hints for the common cutscene/dialogue ops. Keyed by opcode
# index; value is a short list naming each positional arg. Sourced from the handler
# decompiles + the project_rf4s_script_vm opcode catalogue. Not exhaustive -- it
# covers what shows up in dialogue scenes most often.
ARG_HINTS = {
    0:   ["npc id", "amount"],                 # SetNpcFriendshipWithJitter
    9:   [],                                    # HealPartyHPFull
    10:  ["shift (0=full,1=half,2=qtr)"],       # HealPartyHPByShift
    16:  ["quest/event flag id", "(value)"],    # SetPackedGameFlag
    17:  ["npc id", "emote id"],                # SetNpcEmoteByte
    19:  ["npc id"],                            # GetNpcEmoteByte
    20:  ["npc id", "mood id"],                 # SetNpcMoodByte
    22:  ["npc id"],                            # GetNpcMoodByte
    23:  [],                                    # GetPlayerLumber
    32:  ["fade kind", "duration"],             # BeginDualScreenFadeWithKindAndDuration
    33:  ["fade kind"],                         # BeginDualScreenFadeKindOnly
    34:  ["R", "G", "B", "duration"],           # SetFadeColorRGBOverDuration
    55:  ["kind7 index (dialogue: portrait slot)", "value (dialogue: face)"],  # WriteVarArrayKind7
    56:  ["kind7 index"],                       # ReadVarArrayKind7
    77:  ["bgm id (-1 = restore)"],             # PlayBGMOrRestore
    83:  ["sfx id"],                            # PlaySfxById
    91:  ["freeze (0/1)"],                      # SetPlayerScriptedFreeze
    92:  ["tile x", "tile y"],                  # TeleportPlayerToTile
    93:  ["facing deg", "pose"],                # TurnPlayerToAngle
    144: ["weather id"],                        # Script_Action_SetWeather
}


def linearize(scene):
    """Return [(pc, Statement)] in execution order, following unconditional JMPs
    transparently so jumped-to blocks read inline (in play order). Stops at
    RET (0xFFFF) or a revisit; conditional branches are emitted and the fall-through path
    is followed."""
    out, seen = [], set()
    pc = scene.entry_pc
    while pc is not None and pc in scene.stmts and pc not in seen:
        seen.add(pc)
        st = scene.stmts[pc]
        if st.mnem == "JMP" and st.code_targets and st.code_targets[0] in scene.stmts:
            pc = st.code_targets[0]
            continue
        out.append((pc, st))
        if st.terminator:
            break
        if st.falls_through:
            pc = pc + st.size
        elif st.code_targets:
            pc = st.code_targets[0]
        else:
            break
    return out


def scene_labels(scene):
    """Assign labels (L0, L1, ...) to the intra-scene branch/call targets, so the
    disassembly can read 'JMP L2' / 'L2: ...' instead of raw offsets."""
    targets = sorted({t for st in scene.stmts.values()
                      for t in st.code_targets if t is not None and t in scene.stmts})
    return {pc: "L%d" % i for i, pc in enumerate(targets)}


def decode_statement(buf, pc):
    """Decode one statement at byte offset `pc` in bank buffer `buf`. Return Statement or None."""
    op = _u16(buf, pc)
    if op is None:
        return None
    if op < 0xFFF0:                                   # action opcode
        if op >= DISPATCHABLE_ACTION_OPS:             # past the engine's handler table
            return None
        cnt = _u16(buf, pc + 2)
        if cnt is None or cnt > 64:
            return None
        size = 2 * (cnt + 2)
        if pc + size > len(buf):
            return None
        args = [_u16(buf, pc + 4 + 2 * i) for i in range(cnt)]
        return Statement(pc, op, opcode_name(op), size, args=args)
    mn = CONTROL.get(op)
    if mn is None:
        return None
    if op == 0xFFFF:
        return Statement(pc, op, "RET", 2, falls_through=False, terminator=True)
    if op == 0xFFF1:                                  # FRAME: op + u16 local-slot count
        # NOT a return (the old "RET" reading was wrong — corrected 2026-08-06, see
        # the Script_VMStep IDB comment): 0xFFF1 is
        # FRAME SETUP. Script_VMStep sets frame base = stack top, reserves n operand
        # slots for locals (n = u16 at +2, always even: locals are value/kind pairs),
        # then PC += 4 and execution FALLS THROUGH. The real return is RET (0xFFFF).
        # the count is a DIRECT value, so it rides in `items` (args = expression offsets)
        n = _u16(buf, pc + 2)
        return Statement(pc, op, "FRAME", 4, items=[n] if n is not None else [])
    if op == 0xFFFE:                                  # CALL target
        t = _u16(buf, pc + 2)
        return Statement(pc, op, "CALL", 4, code_targets=[t] if t is not None else [])
    if op == 0xFFFA:                                  # JMP (unconditional)
        t = _u16(buf, pc + 2)
        return Statement(pc, op, "JMP", 4, code_targets=[t] if t is not None else [],
                         falls_through=False)
    if op == 0xFFFD:                                  # cond-end: expr ref
        return Statement(pc, op, "RET_NZ", 4, expr_refs=[_u16(buf, pc + 2)])
    if op == 0xFFFB:                                  # EVAL var: expr ref
        return Statement(pc, op, "EVAL", 4, expr_refs=[_u16(buf, pc + 2)])
    if op == 0xFFFC:                                  # show dialogue line (u32 id)
        return Statement(pc, op, "DIALOG", 6, dialog_id=_u32(buf, pc + 2))
    if op in (0xFFF8, 0xFFF9):                        # BR_Z / BR_NZ: expr@+2 target@+4
        return Statement(pc, op, mn, 6, expr_refs=[_u16(buf, pc + 2)],
                         code_targets=[_u16(buf, pc + 4)])
    if op in (0xFFF6, 0xFFF7):                        # switch jump table
        cnt = _u16(buf, pc + 4)
        if cnt is None or cnt > 256:
            return None
        tg = [_u16(buf, pc + 6 + 2 * k) for k in range(cnt)]
        size = 2 * (cnt + 3)
        if op == 0xFFF6:                              # SWITCH_CLAMP: always jumps (never falls
            # through). IDA-verified (Script_VMStep 0xFFF6): selector>=n jumps to the word
            # at pc+2*(n+2), which is exactly target[n-1] -- there is NO separate default
            # slot, so the n case targets are the whole table (same layout as SWITCH).
            return Statement(pc, op, "SWITCH_CLAMP", size, expr_refs=[_u16(buf, pc + 2)],
                             code_targets=tg, falls_through=False)
        return Statement(pc, op, "SWITCH", size, expr_refs=[_u16(buf, pc + 2)],
                         code_targets=tg)
    if op == 0xFFF3:                                  # JMP_RAND (random of N targets)
        cnt = _u16(buf, pc + 2)
        if cnt is None or cnt > 256:
            return None
        tg = [_u16(buf, pc + 4 + 2 * k) for k in range(cnt)]
        return Statement(pc, op, "JMP_RAND", 4 + 2 * cnt, code_targets=tg, falls_through=False)
    if op == 0xFFF2:                                  # weighted-random branch
        n = _u16(buf, pc + 2)
        if n is None or n > 256:
            return None
        tg = [_u16(buf, pc + 4 + 2 * k) for k in range(n)]
        er = [_u16(buf, pc + 4 + 2 * n + 2 * k) for k in range(n)]
        return Statement(pc, op, "JMP_WEIGHTED", 4 + 4 * n, code_targets=tg, expr_refs=er,
                         falls_through=False)
    if op in (0xFFF4, 0xFFF5):                        # PROMPT_CHOICE / PROMPT_CHOICE_FORCED
        # Layout (IDA-verified from Script_VMStep case 0xFFF4/0xFFF5):
        #   0xFFF5 PROMPT_CHOICE_FORCED : [op][N][N u16 targets][N u32 items]; size 6N+4;
        #     no cancel branch; jump = targets[pick]. Same choice UI as PROMPT_CHOICE
        #     but the player CANNOT dismiss/cancel -- one of the N items must be picked.
        #   0xFFF4 PROMPT_CHOICE        : [op][N][N+1 u16 targets][N u32 items]; size 6N+6;
        #     targets[0] = CANCEL branch, targets[1..N] = per-choice branch;
        #     the extra target is the source of the +2-byte gap between the target
        #     block and the item block (item offset = pc + 2N + 6, not 2N + 4).
        # In both cases the op never falls through: it always jumps to some target.
        # Cap 256 (matches the SWITCH tables): the shipped corpus tops out at n=99 —
        # bank 210 @27900, Eliza's 99-option request-recap menu (98 story requests +
        # Quit), which the old n>64 cap silently rejected.
        n = _u16(buf, pc + 2)
        if n is None or n > 256:
            return None
        has_cancel = (op == 0xFFF4)
        n_targets = n + 1 if has_cancel else n
        size = 6 * n + (6 if has_cancel else 4)
        if pc + size > len(buf):
            return None
        tg = [_u16(buf, pc + 4 + 2 * k) for k in range(n_targets)]
        # PROMPT_CHOICE items start after the target block; leaves a 2-byte gap for
        # the extra cancel target (item offset = pc + 2N + 6 vs
        # PROMPT_CHOICE_FORCED's pc + 2N + 4). u32 stride either way.
        items_off = pc + 2 * n + (6 if has_cancel else 4)
        items = [_u32(buf, items_off + 4 * k) for k in range(n)]
        return Statement(pc, op, mn, size,
                         code_targets=[t for t in tg if t is not None],
                         items=[it for it in items if it is not None],
                         falls_through=False)
    return None


def statement_operands(buf, st):
    """[(label, bytes)] -- the operands of statement `st` as stored: for an action, each
    argument's expression bytes (the statement holds only their offsets); for a control op,
    its fields in order (a branch target, a line id, a choice count, its targets and line
    ids ...) with a condition / value given as its expression bytes."""
    pc = st.pc

    def word(off, n=2):
        return bytes(buf[off:off + n])

    def expr(off):
        if off is None or not 0 <= off < len(buf):
            return b""
        _t, size = disasm_expr(buf, off)
        return bytes(buf[off:off + size])
    if st.op < 0xFFF0:
        return [("arg %d" % i, expr(off)) for i, off in enumerate(st.args)]
    m, er, tg = st.mnem, list(st.expr_refs or []), list(st.code_targets or [])
    if m in ("EVAL", "RET_NZ"):
        return [("value" if m == "EVAL" else "condition", expr(er[0] if er else None))]
    if m == "DIALOG":
        return [("line id", word(pc + 2, 4))]
    if m in ("BR_Z", "BR_NZ"):
        return [("condition", expr(er[0] if er else None)), ("target", word(pc + 4))]
    if m == "FRAME":
        return [("slots", word(pc + 2))]
    if m in ("CALL", "JMP"):
        return [("target", word(pc + 2))]
    if m in ("SWITCH", "SWITCH_CLAMP"):
        return ([("value", expr(er[0] if er else None)), ("count", word(pc + 4))]
                + [("case %d" % k, word(pc + 6 + 2 * k)) for k in range(len(tg))])
    if m == "JMP_RAND":
        return [("count", word(pc + 2))] + [("target %d" % k, word(pc + 4 + 2 * k)) for k in range(len(tg))]
    if m == "JMP_WEIGHTED":
        n = len(tg)
        return ([("count", word(pc + 2))] + [("target %d" % k, word(pc + 4 + 2 * k)) for k in range(n)]
                + [("weight %d" % k, expr(er[k] if k < len(er) else None)) for k in range(n)])
    if m in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED"):
        n = len(st.items or [])
        nt = n + 1 if m == "PROMPT_CHOICE" else n
        items_off = pc + 2 * n + (6 if m == "PROMPT_CHOICE" else 4)
        out = [("count", word(pc + 2))]
        out += [("cancel" if (m == "PROMPT_CHOICE" and k == 0) else
                 "target %d" % (k - (1 if m == "PROMPT_CHOICE" else 0)), word(pc + 4 + 2 * k)) for k in range(nt)]
        out += [("option %d line" % k, word(items_off + 4 * k, 4)) for k in range(n)]
        return out
    return []                                          # RET and other operand-less ops


# ---- container ---------------------------------------------------------------------
def _listing_of(specs):
    """Listing text for `specs` (listing text is the only statement format)."""
    if isinstance(specs, str):
        return specs
    raise ScriptError("statements must be listing text (e.g. 'DIALOG #12'), not %s"
                      % type(specs).__name__)


# The action-opcode dispatch table g_sceneActionHandlerTable (RF4S.exe+0x4DB790) holds
# exactly 702 entries: slot 702 is not a function pointer, the corpus's highest action
# opcode is 701, and SceneAction_DispatchTableWithCleanup (RF4S.exe+0x1F4AC0) indexes it
# with NO bounds check -- it only tests whether the slot is null. So an action opcode >= 702
# makes the engine call whatever follows the table. script_opcodes.json still carries 763
# name slots (702..762 are blanks plus a few names that belong to a different table), which
# is why the decoder used to accept them.
DISPATCHABLE_ACTION_OPS = 702

# PROMPT_CHOICE(_FORCED) row cap. Script_VMStep pushes every option id through the host's
# show-line callback; Dialogue_HandleScriptActionShowLine (RF4S.exe+0x1F43B0) appends it to
# the 512-byte g_scriptedEventStateBuffer_512B only while the row count is < 0x80, so options
# past 128 are silently dropped (their targets are unreachable) and, with a visibility mask,
# their mask test reads past the 128-bit mask at scene +244.
MAX_CHOICE_OPTIONS = 128
CHOICE_VISIBLE_ROWS = 4          # ChoiceDialog_TickStateMachine state 3: min(rows, 4) sprites

# Every shipped bank carries a 74-slot type table (types 0..73; 296 bytes; an unused
# tail bank is exactly those 296 zero bytes). The slot count is MYCF header word 14
# (byte 56, value 0x4A): SceneState_ParseMycfHeaderAndInstallReaders (RF4S.exe+0x23DAB0)
# keeps it at scene-state +184 and the entry matchers check `+184 > type` before
# indexing the table. Container hands the header value to its banks (Bank.slots_hint);
# this constant is the default for a bank parsed on its own. The parser additionally
# stops where the first entry list / entry pc begins, so code words that follow the
# table are never read as slots.
TYPE_TABLE_SLOTS = 74


class Bank:
    """One MYCF bank: a <=64 KB self-contained bytecode unit."""
    def __init__(self, index, kind, file_off, data):
        self.index = index            # bank index within its table
        self.kind = kind              # 'primary' or 'tail'
        self.file_off = file_off      # absolute offset in rf3.mc (for reference)
        self.data = data              # the bank bytes (bytearray)

    def type_table_full(self):
        """Return {type: (count, list_offset)} for the bank's used action types.

        Engine-faithful layout (Npc_FindNextActionEntryOfType RF4S.exe+0x23DE30 and its
        callers, e.g. Scene_TickDispatchType6NpcEvent reading `u16 @ 4*6` as the type-6
        entry COUNT): the bank starts with a table of 4-byte slots, one per action type,
        `u16 count @ 4*t` and `u16 list_offset @ 4*t+2` (0 = unused). The engine indexes
        it directly by type with no bound, so the table's extent is only implied: it
        ends where the first entry list or code byte begins (normally 74 slots = 296
        bytes; an empty bank is exactly that). This parser shrinks the bound as it goes
        (every list offset / event pc seen is past the table) and stops at the first
        slot that cannot be a real list, so code words that happen to follow the table
        are never read as slots. The old heuristic ignored the count word and walked
        into the NEXT type's list, mis-attributing entries."""
        d = self.data
        n = len(d)
        limit = min(n, 4 * getattr(self, "slots_hint", TYPE_TABLE_SLOTS))
        t = 0
        out = OrderedDict()
        while 4 * t + 4 <= limit:
            cnt, off = struct.unpack_from("<HH", d, 4 * t)
            if off:
                floor = 4 * (t + 1)                        # lists/code lie past this slot
                lim = off
                ok = floor <= off < n
                cur = off
                if ok:
                    for _ in range(cnt):
                        if cur + 4 > n:
                            ok = False
                            break
                        sz, eid = struct.unpack_from("<HH", d, cur)
                        if eid >= n or eid < floor:
                            ok = False
                            break
                        lim = min(lim, eid)
                        cur += 5 * sz + 4
                    if cur > n:
                        ok = False
                if not ok:
                    break                                  # past the table: a code word
                limit = min(limit, lim)
                if 4 * t + 4 <= limit:
                    out[t] = (cnt, off)
            t += 1
        self._table_end = limit
        return out

    @property
    def table_slots(self):
        """Number of 4-byte type slots the bank's table can hold (types 0..slots-1)."""
        if not hasattr(self, "_table_end"):
            self.type_table_full()
        return self._table_end // 4

    def type_table(self, max_types=None):
        """Return {type: entry_list_offset} for non-empty action types (see
        type_table_full for the count word)."""
        out = OrderedDict()
        for t, (cnt, off) in self.type_table_full().items():
            if max_types is None or t < max_types:
                out[t] = off
        return out

    def entries(self, list_off, count=None):
        """Walk an entry list: return [(entry_off, size, event_id)].

        With `count` (the type table's count word) exactly that many records are read
        -- the engine's walk. Without it the legacy heuristic is used: accept records
        while event_id is an even, non-zero PC before the list and the size word is
        small (kept for tooling that has no count; it can over-walk into the next
        type's list)."""
        n = len(self.data)
        cur = list_off
        out = []
        if count is not None:
            for i in range(count):
                if cur + 4 > n:
                    raise ScriptError("entry list @0x%04x record %d runs past the bank" % (list_off, i))
                size = _u16(self.data, cur)
                eid = _u16(self.data, cur + 2)
                out.append((cur, size, eid))
                cur += 5 * size + 4
            return out
        for _ in range(4096):
            if cur + 4 > n:
                break
            size = _u16(self.data, cur)
            eid = _u16(self.data, cur + 2)
            if size is None or eid is None:
                break
            if not (0 < eid < list_off and eid % 2 == 0 and size <= 8):
                break
            out.append((cur, size, eid))
            cur += 5 * size + 4
        return out

    def scene_entries(self):
        """All (type, event_id) scene entry points in this bank (count-exact)."""
        eps = []
        for t, (cnt, off) in self.type_table_full().items():
            for (_, _, eid) in self.entries(off, cnt):
                eps.append((t, eid))
        return eps

    def entry_records(self, type_id):
        """The decoded entries of one action type: [EntryRecord] in list order.

        An entry is `{u16 size; u16 event_id; size x {u8 tag; i32 value}}`
        (Npc_ReadActionEntrySubBytes RF4S.exe+0x23F7B0 reads record k at
        entry+4+5k: tag byte, then the i32). The sub-records are the entry's KEYS --
        what the type's matcher compares against the runtime situation (player hit
        filter, item id, festival phase, ...; see entry_types.py); -1 is a wildcard in
        every matcher seen. event_id is the scene's code pc."""
        tt = self.type_table_full()
        if type_id not in tt:
            return []
        cnt, off = tt[type_id]
        out = []
        for i, (eo, size, eid) in enumerate(self.entries(off, cnt)):
            subs = []
            for k in range(size):
                p = eo + 4 + 5 * k
                if p + 5 > len(self.data):
                    raise ScriptError("entry %d of type %d runs past the bank" % (i, type_id))
                subs.append((self.data[p], struct.unpack_from("<i", self.data, p + 1)[0]))
            out.append(EntryRecord(i, eo, eid, subs))
        return out


    # ---- in-place editing (same length -> byte-perfect round-trip) -------------
    def set_dialog_id(self, pc, new_id):
        """Retarget a DIALOG (0xFFFC) statement at `pc` to a different dialogue line id."""
        if _u16(self.data, pc) != 0xFFFC:
            raise ScriptError("no DIALOG at 0x%04x in bank %d" % (pc, self.index))
        struct.pack_into("<I", self.data, pc + 2, new_id & 0xFFFFFFFF)

    def set_action_arg(self, pc, index, value):
        """Set arg `index` (u16) of the action statement at `pc`.
        NOTE: an arg is a u16 *offset* to an expression -- this repoints it to a
        different expression. To change the VALUE an immediate arg yields, use
        set_action_arg_value()."""
        op = _u16(self.data, pc)
        if op is None or op >= 0xFFF0:
            raise ScriptError("not an action opcode at 0x%04x" % pc)
        cnt = _u16(self.data, pc + 2)
        if cnt is None or index >= cnt:
            raise ScriptError("arg %d out of range (argcount %s)" % (index, cnt))
        if pc + 4 + 2 * index + 2 > len(self.data):
            raise ScriptError("arg %d offset past EOF at 0x%04x" % (index, pc))
        struct.pack_into("<H", self.data, pc + 4 + 2 * index, value & 0xFFFF)

    def set_action_arg_value(self, pc, index, value):
        """Set the literal VALUE that action arg `index` yields, by patching the
        immediate byte(s) of the expression it points to (same length, in place).
        Works only when that arg is a simple immediate (the common case, e.g. a
        dialogue face id). Raises with an explanation otherwise."""
        op = _u16(self.data, pc)
        if op is None or op >= 0xFFF0:
            raise ScriptError("not an action statement at 0x%04x in bank %d" % (pc, self.index))
        cnt = _u16(self.data, pc + 2)
        if cnt is None or index >= cnt:
            raise ScriptError("arg %d out of range (argcount %s) at 0x%04x"
                              % (index, cnt, pc))
        off = _u16(self.data, pc + 4 + 2 * index)
        if off is None or off >= len(self.data):
            raise ScriptError("arg %d expression offset out of range at 0x%04x" % (index, pc))
        self.set_expr_value(off, value)

    def set_expr_value(self, off, value):
        """Patch a single-immediate expression at `off` to yield `value`, in place.
        2-byte immediates (u8/s8) accept -128..255; 3-byte (u16) accept 0..65535."""
        if off is None or not (0 <= off < len(self.data)):
            raise ScriptError("expression offset 0x%s out of range in bank %d"
                              % ("%04x" % off if off is not None else "None", self.index))
        t = self.data[off]
        if t in (0x17, 0x18):                       # 2-byte: u8 (0x17) / s8 (0x18)
            if not (-128 <= value <= 255):
                raise ScriptError("value %d needs more than 1 byte; this immediate is 1 byte "
                                  "(range -128..255). Use an arg whose expression is u16." % value)
            # Keep the existing tag when the value fits it (1-byte diff); switch only
            # when the sign forces it.
            if t == 0x18 and value > 127:
                self.data[off] = 0x17                # s8 -> u8 (needs the high range)
            elif t == 0x17 and value < 0:
                self.data[off] = 0x18                # u8 -> s8 (needs negatives)
            struct.pack_into("<b" if self.data[off] == 0x18 else "<B", self.data, off + 1, value)
        elif t in (0x19, 0x1A):                     # 3-byte 16-bit literal: u16 (0x19)/s16 (0x1A)
            if not (-32768 <= value <= 65535):
                raise ScriptError("value %d out of 16-bit range (-32768..65535)" % value)
            # Keep the tag when the value fits it; switch only when the sign forces it
            # (the engine reads 0x19 unsigned, 0x1A signed -- see decode_statement).
            if self.data[off] == 0x1A and value > 32767:
                self.data[off] = 0x19               # s16 -> u16 (needs the high range)
            elif self.data[off] == 0x19 and value < 0:
                self.data[off] = 0x1A               # u16 -> s16 (needs negatives)
            struct.pack_into("<h" if self.data[off] == 0x1A else "<H", self.data, off + 1, value)
        elif t in (0x03, 0x04):                     # typed constant (actor(..) / map(..))
            if not (0 <= value <= 0xFFFFFFFF):
                raise ScriptError("value %d out of range for a typed constant (0..2^32-1)" % value)
            struct.pack_into("<I", self.data, off + 1, value)   # keep the tag: same bytes size
        elif t in (0x14, 0x15, 0x16):
            raise ScriptError("this arg is a fixed %d push (1 byte) — not range-editable in "
                              "place; repoint it to another expression instead"
                              % {0x14: 0, 0x15: -1, 0x16: 1}[t])
        else:
            raise ScriptError("expr@0x%04x (tag 0x%02x) is a variable or computed expression, "
                              "not a literal value to set" % (off, t))

    def set_choice_item(self, pc, index, string_id):
        """Retarget PROMPT_CHOICE / PROMPT_CHOICE_FORCED option `index` to a different rf3mc
        string id (which dialogue line that choice option displays), in place (u32, same
        length). The analog of set_dialog for a choice's option text -- point an option at
        another existing line (e.g. one just appended with `text add`) without touching the
        original. Editing the branch TARGETS is a separate, structural op (not this)."""
        op = _u16(self.data, pc)
        if op not in (0xFFF4, 0xFFF5):
            raise ScriptError("statement at 0x%04x in bank %d is not a PROMPT_CHOICE "
                              "(op 0x%s) -- choice-item edit needs op 0xFFF4/0xFFF5"
                              % (pc, self.index, "%04x" % op if op is not None else "None"))
        n = _u16(self.data, pc + 2)
        if n is None or not (0 <= index < n):
            raise ScriptError("choice option %d out of range (this PROMPT_CHOICE has %s "
                              "option(s)) at 0x%04x" % (index, n, pc))
        # item block starts after the u16 target block: N targets for FORCED (0xFFF5),
        # N+1 for cancelable PROMPT_CHOICE (0xFFF4) -- mirrors decode_statement's items_off.
        items_off = pc + 2 * n + (6 if op == 0xFFF4 else 4)
        slot = items_off + 4 * index
        if slot + 4 > len(self.data):
            raise ScriptError("choice item %d runs past the bank end at 0x%04x" % (index, pc))
        if not (0 <= string_id <= 0xFFFFFFFF):
            raise ScriptError("string id %d out of u32 range" % string_id)
        struct.pack_into("<I", self.data, slot, string_id)

    # Offset (from the statement pc) of the FIRST u16 branch target, per control op. The target
    # block is then target[k] @ base + 2*k. Derived directly from decode_statement's layouts:
    # CALL/JMP have one target right after the op; BR_Z/BR_NZ put it after the guard-expr ref@+2;
    # SWITCH after selector@+2 and count@+4; JMP_RAND/JMP_WEIGHTED/PROMPT_CHOICE after count@+2.
    _BRANCH_TARGET_BASE = {
        0xFFFE: 2, 0xFFFA: 2,           # CALL, JMP        (single target @ +2)
        0xFFF8: 4, 0xFFF9: 4,           # BR_Z, BR_NZ      (@ +4, after expr@+2)
        0xFFF6: 6, 0xFFF7: 6,           # SWITCH_CLAMP/EQ     (@ +6, after selector@+2 + count@+4)
        0xFFF3: 4, 0xFFF2: 4,           # JMP_RAND, JMP_WEIGHTED (@ +4, after count@+2)
        0xFFF4: 4, 0xFFF5: 4,           # PROMPT_CHOICE(+cancel[0]) / _FORCED (@ +4)
    }

    def set_branch_target(self, pc, index, new_target, valid_targets=None):
        """Repoint branch/jump/choice target `index` to another statement pc (u16, in place) --
        the flow-control analog of set_choice_item (which retargets a choice's TEXT; this retargets
        where it GOES). Works on CALL/JMP/BR_Z/BR_NZ/SWITCH/SWITCH_CLAMP/JMP_RAND/JMP_WEIGHTED/
        PROMPT_CHOICE[_FORCED]. For PROMPT_CHOICE (0xFFF4) target[0] = the CANCEL branch and
        target[1..N] = the per-option branches. If `valid_targets` is given (the set of real
        statement pcs in the scene), the new target MUST be one of them -- this is what keeps the
        edit crash-safe, so callers should pass the disassembled scene's statement pcs."""
        op = _u16(self.data, pc)
        base = self._BRANCH_TARGET_BASE.get(op)
        if base is None:
            raise ScriptError("statement at 0x%04x in bank %d (op 0x%s) is not a branch/jump/"
                              "choice op -- nothing to retarget"
                              % (pc, self.index, "%04x" % op if op is not None else "None"))
        st = decode_statement(self.data, pc)
        ntargets = len(st.code_targets) if (st and st.code_targets) else 0
        if not (0 <= index < ntargets):
            raise ScriptError("target %d out of range (this %s has %d target(s)) at 0x%04x"
                              % (index, st.mnem if st else "op", ntargets, pc))
        if not (0 <= new_target <= 0xFFFF):
            raise ScriptError("target pc %d out of u16 range" % new_target)
        if valid_targets is not None and new_target not in valid_targets:
            raise ScriptError("target 0x%04x is not a statement start in this scene -- retargeting "
                              "to a mid-statement/invalid pc would crash the VM; pass a pc from the "
                              "disassembly" % new_target)
        slot = pc + base + 2 * index
        if slot + 2 > len(self.data):
            raise ScriptError("target %d runs past the bank end at 0x%04x" % (index, pc))
        struct.pack_into("<H", self.data, slot, new_target)

    def set_action_opcode(self, pc, new_op):
        """Change the opcode of the action statement at `pc`, in place (same length).
        The arg-count word (pc+2) is untouched, so this is only valid when `new_op`
        takes the SAME number of args as the current opcode. The main use is swapping a
        SetSpeaker's speaker/side (opcodes 16..75 all share the 2-arg-ish encoding)."""
        op = _u16(self.data, pc)
        if op is None or op >= 0xFFF0:
            raise ScriptError("not an action opcode at 0x%04x" % pc)
        if not (0 <= new_op < 0xFFF0):
            raise ScriptError("0x%04x is not an action opcode" % new_op)
        struct.pack_into("<H", self.data, pc, new_op & 0xFFFF)


class EntryRecord:
    """One type-table entry: index in its list, byte offset, scene pc, keys [(tag, value)]."""
    __slots__ = ("index", "offset", "event_id", "subs")

    def __init__(self, index, offset, event_id, subs):
        self.index = index
        self.offset = offset
        self.event_id = event_id
        self.subs = list(subs)

    @property
    def size(self):
        return 4 + 5 * len(self.subs)

    def encode(self):
        return encode_entry(self.event_id, self.subs)

    def __repr__(self):
        return "EntryRecord(#%d @0x%04x pc=0x%04x keys=%r)" % (self.index, self.offset,
                                                              self.event_id, self.subs)


def encode_entry(event_id, subs):
    """Bytes of one entry record. `subs` items are ints (tag 1 = plain value) or
    (tag, value) pairs."""
    out = bytearray(struct.pack("<HH", len(subs), event_id & 0xFFFF))
    for s in subs:
        if isinstance(s, (tuple, list)):
            tag, val = s
        else:
            tag, val = 1, s
        if not (0 <= int(tag) <= 255):
            raise ScriptError("trigger key tag %r out of range" % (tag,))
        out += bytes([int(tag)]) + struct.pack("<i", int(val))
    return bytes(out)


# A bank's bytecode is addressed with u16 offsets (code targets, expression offsets), so
# no bank can grow past 64 KiB. See Container.bank_space.
BANK_ADDRESS_LIMIT = 0x10000


class Container:
    """Parsed rf3.mc MYCF container. Structure-preserving (build() == original)."""
    def __init__(self, data):
        self.data = bytearray(data)
        if bytes(self.data[:4]) != MAGIC:
            raise ScriptError("not a MYCF container (bad magic %r)" % bytes(self.data[:4]))
        if len(self.data) < 48:                       # 9-int header (36B) + 3 var-mask ints (12B)
            raise ScriptError("truncated MYCF container: %d bytes, need >= 48 for the header"
                              % len(self.data))
        h = struct.unpack_from("<9I", self.data, 0)
        # SceneState_ParseMycfHeaderAndInstallReaders (RF4S.exe+0x23DAB0): header word 1
        # non-zero selects BIG-endian readers for the whole file, and word 2 must be
        # 0x10001 or the scene system never initialises (ScriptTask_FirstTimeInit,
        # RF4S.exe+0x1EE060, tears the scene state down). This parser is little-endian only.
        if h[1] != 0:
            raise ScriptError("big-endian MYCF (header word 1 = 0x%X) is not supported" % h[1])
        if h[2] != 0x10001:
            raise ScriptError("MYCF version 0x%X: the engine only loads version 0x10001" % h[2])
        self.ver = h[2]
        self.regionB_end = h[3]
        self.regionB_size = h[4]
        self.n_primary = h[5]
        self.table1_off = h[6]
        self.n_tail = h[7]
        self.table2_off = h[8]
        # Packed-variable encoding masks (MYCF header words 9/10/11 = bytes 36/40/44).
        # A token-0x02 expression operand packs (bit_offset, width-1, sign) into one
        # u32; the VM (SceneState_ReadGameFlagField -> PackedFlags_ReadField_MSBFirst,
        # RF4S.exe+0x241210) reads `width` bits at `bit_offset` from g_gameFlagsBuffer
        # -- the SAME buffer emdeb.bin / emflags names. So a packed ref resolves to a
        # FLG_/REG_ variable. Shifts = ctz(mask) (SceneState_ParseMycfHeaderAndInstallReaders, RF4S.exe+0x23DAB0, does the same).
        m = struct.unpack_from("<3I", self.data, 36)
        self.var_off_mask = m[0]
        self.var_off_shift = (m[0] & -m[0]).bit_length() - 1 if m[0] else 0
        self.var_wid_mask = m[1]
        self.var_wid_shift = (m[1] & -m[1]).bit_length() - 1 if m[1] else 0
        self.var_sign_mask = m[2]
        # Header word 14 (byte 56) = per-bank type-table slot count (0x4A = 74 in the
        # shipped file); the loader keeps it at scene-state +184 and the matchers bound
        # the action type by it. Kept for the banks' table parser (Bank.slots_hint).
        self.type_table_slots = struct.unpack_from("<I", self.data, 56)[0] if len(self.data) >= 60 else TYPE_TABLE_SLOTS
        if not (1 <= self.type_table_slots <= 4096):
            self.type_table_slots = TYPE_TABLE_SLOTS
        self.banks = []
        self._load_banks()
        for b in self.banks:
            b.slots_hint = self.type_table_slots

    def unpack_var(self, enc):
        """Decode a token-0x02 packed variable ref (u32) into (bit_offset, width,
        sign). `bit_offset` indexes g_gameFlagsBuffer and equals the emdeb.bin /
        emflags bit_offset, so `emflags.by_offset(bit_offset)` gives the FLG_/REG_
        name. Engine-faithful: mirrors Script_StackSlot_NormalizeToInt32 case 2."""
        bit_off = (enc & self.var_off_mask) >> self.var_off_shift
        width = ((enc & self.var_wid_mask) >> self.var_wid_shift) + 1
        return bit_off, width, bool(enc & self.var_sign_mask)

    def pack_var(self, bit_offset, width, sign=False):
        """Inverse of unpack_var: the u32 a token-0x02 operand carries for the game-flag
        field at `bit_offset` (emdeb.bin offset) of `width` bits. Uses this container's
        header masks; the shipped corpus encodes every variable as (offset, emdeb width,
        unsigned)."""
        if width < 1 or ((width - 1) << self.var_wid_shift) & ~self.var_wid_mask:
            raise ScriptError("packed-variable width %d does not fit the header mask" % width)
        if (bit_offset << self.var_off_shift) & ~self.var_off_mask:
            raise ScriptError("packed-variable bit offset %d does not fit the header mask" % bit_offset)
        enc = ((bit_offset << self.var_off_shift) & self.var_off_mask) | \
              (((width - 1) << self.var_wid_shift) & self.var_wid_mask)
        if sign:
            enc |= self.var_sign_mask
        return enc

    # Name -> packed-encoding resolver used when assembling listing text (see
    # scriptasm.make_resolver). None = symbolic variable names are rejected.
    asm_resolver = None

    def set_asm_resolver(self, fn):
        self.asm_resolver = fn

    def install_asm_resolver(self, emf_table=None):
        """Wire the assembler to emdeb.bin names (best effort: loads the bundled
        emdeb.bin when `emf_table` is None). Returns the resolver or None."""
        try:
            from . import scriptasm
            if emf_table is None:
                from .emflags import EmFlagTable
                emf_table = EmFlagTable.load()
        except Exception:
            emf_table = None
        try:
            from . import scriptasm
            self.asm_resolver = scriptasm.make_resolver(self, emf_table)
        except Exception:
            self.asm_resolver = None
        return self.asm_resolver

    def _load_banks(self):
        d = self.data
        n = len(d)
        # A corrupt / truncated container (valid header but bad section tables) must fail with a
        # clean ScriptError, not a raw struct.error or MemoryError. Validate the tables fit the
        # buffer before walking them -- this also rejects an absurd n_primary/n_tail count.
        if (self.table1_off + 8 * self.n_primary > n) or (self.table2_off + 8 * self.n_tail > n):
            raise ScriptError(
                "corrupt MYCF: section table out of range "
                "(n_primary=%d@0x%x, n_tail=%d@0x%x, size=%d)"
                % (self.n_primary, self.table1_off, self.n_tail, self.table2_off, n))
        for i in range(self.n_primary):
            slot = self.table1_off + 8 * i
            off, sz = struct.unpack_from("<II", d, slot)
            if off + sz > n:
                raise ScriptError("corrupt MYCF: primary bank %d runs past EOF (off=%d sz=%d)"
                                  % (i, off, sz))
            b = Bank(i, "primary", off, d[off:off + sz]); b.slot = slot
            self.banks.append(b)
        for i in range(self.n_tail):
            slot = self.table2_off + 8 * i
            off, sz = struct.unpack_from("<II", d, slot)
            if off + sz > n:
                raise ScriptError("corrupt MYCF: tail bank %d runs past EOF (off=%d sz=%d)"
                                  % (i, off, sz))
            b = Bank(i, "tail", off, d[off:off + sz]); b.slot = slot
            self.banks.append(b)
        # The "global" / opening-cutscene bank: addressed directly by header [3]=off,
        # [4]=size (a (u32 off, u32 size) pair at byte 12), NOT via a section table.
        # It holds the game's earliest content (dialogue line ids 0..~1305). Treat it
        # as a normal bank (slot = byte 12 so set_bank_bytes' table fixup handles it too).
        goff, gsz = struct.unpack_from("<II", d, 12)
        if goff and gsz and goff + gsz <= len(d):
            gb = Bank(len(self.banks), "global", goff, d[goff:goff + gsz])
            gb.slot = 12
            self.banks.append(gb)

    # MYCF header words 12 (byte 48) and 13 (byte 52) are the LARGEST primary / tail bank
    # in the file, and word 4 (byte 16) is the global bank's size. They are not statistics
    # (statically re-verified in RF4S.exe 2026-09-27):
    #   * SceneState_ParseMycfHeaderAndInstallReaders (RF4S.exe+0x23DAB0) keeps them at
    #     SceneState +124 / +140 / +156;
    #   * ScriptTask_FirstTimeInit (RF4S.exe+0x1EE060) passes them to MycfBankSlot_Create
    #     (RF4S.exe+0x23F950) -- its only caller -- which allocates ONE buffer of
    #     `max_size + 32` per bank kind for the whole session (SceneState_AlignedAllocWith-
    #     Semaphore RF4S.exe+0x1F4240: aligned_malloc, no cap of its own);
    #   * MycfBankSlot_LoadBank (RF4S.exe+0x23F9C0) reads the bank's (offset, size) pair
    #     from the section table (the header pair at byte 12 for the global bank) and
    #     copies `size` bytes into that buffer through SceneState_CopyFromArchive15209
    #     (RF4S.exe+0x1F42B0: memcpy out of the whole loaded rf3.mc, archive id 15209) --
    #     no check against the buffer anywhere.
    # Growing a bank past the recorded maximum without raising it makes the engine copy
    # more bytes than the buffer holds -- a heap overflow, not a clean failure. So every
    # rebuild re-derives them (set_bank_bytes), and build() refuses a file that would
    # overflow. The only hard limit is then the u16 addressing (BANK_ADDRESS_LIMIT).
    # (Verified against the shipped file: word 12 == max primary bank == 60651, word 13 ==
    # max tail bank == 65318, word 4 == 54681.)
    _MAX_SIZE_WORD = {"primary": 48, "tail": 52}

    def _sync_max_bank_size(self, bank=None):
        """Raise the header's max-bank-size word for `bank`'s kind (or every kind) when a
        bank now exceeds it. Returns the list of (kind, old, new) that changed."""
        kinds = [bank.kind] if bank is not None else list(self._MAX_SIZE_WORD)
        changed = []
        for kind in kinds:
            off = self._MAX_SIZE_WORD.get(kind)
            if off is None:                            # the global bank's size IS its word 4,
                continue                               # already written via its section slot
            biggest = max((len(b.data) for b in self.banks if b.kind == kind), default=0)
            cur = struct.unpack_from("<I", self.data, off)[0]
            if biggest > cur:
                struct.pack_into("<I", self.data, off, biggest)
                changed.append((kind, cur, biggest))
        return changed

    def max_bank_size(self, kind):
        """The header's recorded maximum size for `kind` ('primary' / 'tail' / 'global') --
        the size of the engine's reusable load buffer for that bank kind."""
        if kind == "global":
            return struct.unpack_from("<I", self.data, 16)[0]
        off = self._MAX_SIZE_WORD.get(kind)
        if off is None:
            raise ScriptError("unknown bank kind %r" % (kind,))
        return struct.unpack_from("<I", self.data, off)[0]

    def bank_space(self, bank):
        """Room left in one bank: {'used', 'limit', 'free', 'buffer'}. The hard limit is
        BANK_ADDRESS_LIMIT (65,536 bytes): every branch / CALL target and expression offset
        in the bytecode is a u16 (Script_VMStep RF4S.exe+0x23EF60, Script_EvalExpressionOrVar
        +0x23EA10 index the bank with 16-bit offsets), and set_bank_bytes refuses to pass it.
        'buffer' is the header's load-buffer size for the bank's kind (MycfBankSlot_LoadBank
        +0x23F9C0 copies into it); set_bank_bytes raises it automatically, so it is not a limit.
        Dialogue text is not counted: it lives in rf3mc.<locale>, not in the bank."""
        if isinstance(bank, int):
            bank = self.banks[bank]
        used = len(bank.data)
        try:
            buf = self.max_bank_size(bank.kind)
        except ScriptError:
            buf = None
        return {"used": used, "limit": BANK_ADDRESS_LIMIT,
                "free": max(0, BANK_ADDRESS_LIMIT - used), "buffer": buf}

    def validate_bank_sizes(self):
        """[] when every bank fits the buffer the engine will allocate for it, else one
        message per offender (a heap overflow in the game, so build() refuses)."""
        out = []
        for kind in ("primary", "tail", "global"):
            cap = self.max_bank_size(kind)
            for b in self.banks:
                if b.kind == kind and len(b.data) > cap:
                    out.append("%s bank %d is %d bytes but the header's load buffer for %s banks "
                               "is %d (the engine would copy past it)"
                               % (kind, b.index, len(b.data), kind, cap))
        return out

    # ---- structural editing: every edit rebuilds the bank (bankrelink) ---------------
    #
    # Structural edits (insert / delete / replace a scene / wider operands / entry lists)
    # parse the whole bank into a bankrelink.BankModel, change the model and lay the bank
    # out again, so the edit sits in place: every branch target, entry pc, list offset and
    # operand offset is recomputed, nothing is appended after the pool, and replaced code
    # does not linger as dead bytes. Same-length patches (Bank.set_dialog_id,
    # set_expr_value, set_branch_target, ...) stay in place and keep the layout.
    #
    # The bank's pcs change with every such edit: `last_relink` = {container bank
    # position: {pc before: pc after}} of the last edit (composed when one call relinks
    # the same bank twice) lets a viewer follow its scene and selection; edit methods
    # return pcs in the rebuilt bank.
    #
    # Limits (statically verified in RF4S.exe, 2026-09-27): a bank is addressed with u16
    # offsets -- Script_VMStep (RF4S.exe+0x23EF60) reads the opcode at buf[LOWORD(pc)] and
    # every branch target / operand offset with read_u16, and the type table's list offsets
    # and entry pcs are u16 too -- so a bank must stay within BANK_ADDRESS_LIMIT (65,536
    # bytes); set_bank_bytes refuses more. The load buffers are not a limit: see
    # _sync_max_bank_size.
    last_relink = None
    untrampolined = None             # {position: folds} of banks an edit or normalize_banks
                                     # rebuilt out of an older toolkit's trampolines

    def set_bank_bytes(self, bank, new):
        """Replace `bank`'s bytes with `new` (any length) and repack the container: the
        banks after it move, both section tables and the global bank's header pair are
        rewritten, and the header's load-buffer words are raised when needed. The Bank
        object stays the same (its data is replaced in place)."""
        if isinstance(bank, int):
            bank = self.banks[bank]
        new = bytes(new)
        if len(new) > BANK_ADDRESS_LIMIT:
            from . import bankrelink
            raise ScriptError("%s bank %d: %s" % (bank.kind, bank.index, bankrelink.too_big(len(new))))
        start = bank.file_off
        end = start + len(bank.data)
        delta = len(new) - len(bank.data)
        self.data[start:end] = new
        for b in self.banks:
            # `b is not bank`: a zero-length bank at the splice point keeps its place when it
            # is the one being written; other banks at or after the old end move by delta.
            if b is not bank and b.file_off >= end and delta:
                b.file_off += delta
                struct.pack_into("<II", self.data, b.slot, b.file_off, len(b.data))
        struct.pack_into("<II", self.data, bank.slot, start, len(new))
        bank.data[:] = new
        if hasattr(bank, "_table_end"):
            del bank._table_end
        self._sync_max_bank_size(bank)

    def _relink(self, bank, edit):
        """Run `edit(model)` on `bank`'s BankModel and write the rebuilt bank back. Returns
        (model, edit's result); `model.pc_of(key)` gives a key's pc in the new bank."""
        from . import bankrelink
        if isinstance(bank, int):
            bank = self.banks[bank]
        m = bankrelink.BankModel.parse_any(bank)
        result = edit(m)
        try:
            self.last_frames = m.ensure_frames()           # FRAME sizes the edited code needs
            new = m.build()
        except bankrelink.RelinkError as e:
            raise ScriptError("%s bank %d: %s" % (bank.kind, bank.index, e))
        self.set_bank_bytes(bank, new)
        pos = next(i for i, b in enumerate(self.banks) if b is bank)
        if m.folded or m.mode != "canonical":          # an older toolkit's trampolines, undone
            self.untrampolined = dict(self.untrampolined or {})
            self.untrampolined[pos] = self.untrampolined.get(pos, 0) + m.folded
        pm = m.pc_map()
        lr = self.last_relink if isinstance(self.last_relink, dict) else {}
        if pos in lr:                                  # compose with an earlier relink
            pm = {a: pm[b] for a, b in lr[pos].items() if b in pm}
        lr = dict(lr)
        lr[pos] = pm
        self.last_relink = lr
        # where each statement ITSELF went (no redirects: after an insert before X, jumps to X
        # land on the new code -- last_relink -- but X is still X, a few bytes on); a deleted
        # statement has no entry. The debugger's breakpoints follow this one.
        own = {s.old_pc: m.newpc[s.old_pc] for s in m.code
               if s.old_pc < m.FIRST_NEW_KEY and s.old_pc in (m.newpc or {})}
        lm = self.last_moves if isinstance(self.last_moves, dict) else {}
        if pos in lm:                                  # compose with an earlier relink
            own = {a: own[b] for a, b in lm[pos].items() if b in own}
        lm = dict(lm)
        lm[pos] = own
        self.last_moves = lm
        return m, result

    last_moves = None

    last_frames = None

    def ensure_frames(self, bank):
        """Rebuild `bank` when a routine's FRAME is too small for its code (see
        bankrelink.BankModel.ensure_frames); returns the changes, [] when none was needed."""
        from . import bankrelink
        if isinstance(bank, int):
            bank = self.banks[bank]
        m = bankrelink.BankModel.parse_any(bank)
        if not any(m.frame_need(r) for r in m.routine_roots()):
            return []
        m2, _r = self._relink(bank, lambda m: None)
        return self.last_frames or []

    def _pc(self, m, key):
        pc = m.pc_of(key) if key is not None else None
        if pc is None and key is not None:
            raise ScriptError("internal: statement 0x%x vanished in the rebuild" % key)
        return pc

    def trampolined_banks(self):
        """Container positions of the banks an earlier toolkit version edited by
        trampolining (not in the compiler layout, or holding a jump-over-a-deleted-
        statement); normalize_banks() rebuilds them. Parses every bank (~2 s)."""
        from . import bankrelink
        out = []
        for i, b in enumerate(self.banks):
            try:
                m = bankrelink.BankModel.parse(b)
            except bankrelink.RelinkError:
                out.append(i)
                continue
            if m.fold():
                out.append(i)
        return out

    def normalize_banks(self, positions=None):
        """Rebuild trampolined banks in place (default: every one trampolined_banks()
        finds). Execution is unchanged: the appended blocks move back where their jumps
        were, skipped statements and code / operands / lists nothing reaches are dropped.
        Returns [(position, folds, mode)]."""
        if positions is None:
            positions = self.trampolined_banks()
        out = []
        for pos in positions:
            m, _r = self._relink(pos, lambda m: None)
            out.append((pos, m.folded, m.mode))
        return out

    @staticmethod
    def _literal_expr_bytes(v):
        """Bytes of an RPN expression that evaluates to the integer `v` (+terminator),
        encoded like the game's compiler (scriptasm.int_literal_bytes)."""
        if not -32768 <= v <= 0xFFFF:
            raise ScriptError("literal %d out of range for a script expression" % v)
        from . import scriptasm
        return scriptasm.int_literal_bytes(v) + b"\x00"

    def assemble(self, bank, text, fallthrough_to=None, strict=True):
        """Assemble listing `text` after the bank's last statement and return its pc in
        the rebuilt bank. It ends with END, or with a JMP to `fallthrough_to` (a pc).
        Nothing references it until `add_entry(..., event_pc=)` / a branch does; use
        `add_entry(..., listing=text)` to register it in one step."""
        m, key = self._relink(bank, lambda m: m.append_code(text, self.asm_resolver, fallthrough_to, strict=strict))
        return self._pc(m, key)

    def insert_before(self, bank, pc, specs, strict=True):
        """Insert statements (listing text) just before the statement at `pc`: every path
        that reached `pc` -- the statement above falling through, every branch, call and
        entry to it -- runs them first. Returns the new statements' first pc."""
        m, key = self._relink(bank, lambda m: m.insert_before(pc, _listing_of(specs), self.asm_resolver, strict=strict))
        return self._pc(m, key)

    def insert_after(self, bank, pc, specs, strict=True):
        """Insert statements right after the statement at `pc` (which must fall through);
        branches to the statement that followed it still skip them. Returns the new
        statements' first pc."""
        m, key = self._relink(bank, lambda m: m.insert_after(pc, _listing_of(specs), self.asm_resolver, strict=strict))
        return self._pc(m, key)

    def rewrite_scene(self, bank, entry_pc, specs, strict=True):
        """Replace the scene at `entry_pc` with `specs` (listing text; END is added when it
        can fall off its end). The trigger is unchanged: the new body sits where the old
        entry was and everything that pointed at the entry points at it; old statements
        nothing reaches any more are dropped, ones shared with other scenes stay. This is
        how you author a 'new' cutscene by repurposing an existing trigger. Returns the
        scene's new entry pc."""
        m, key = self._relink(bank, lambda m: m.replace_scene(entry_pc, _listing_of(specs), self.asm_resolver, strict=strict))
        return self._pc(m, key)

    def delete_statement(self, bank, pc):
        """Remove the statement at `pc` (it must fall through); whatever pointed at it now
        points at the statement after it. Returns that statement's new pc."""
        if isinstance(bank, int):
            bank = self.banks[bank]
        st = decode_statement(bank.data, pc)
        if st is None:
            raise ScriptError("no statement at 0x%04x" % pc)
        if not st.falls_through or st.terminator:
            # Removing a statement that never falls through would send the VM into whatever
            # statement follows it (another branch's code, the next scene).
            raise ScriptError("%s at 0x%04x never falls through; deleting it would run the "
                              "statement after it -- retarget it (set_branch_target) instead" % (st.mnem, pc))
        m, _r = self._relink(bank, lambda m: m.delete(pc))
        return m.pc_of(pc)

    def set_action_arg_expr(self, bank, pc, index, expr):
        """Action arg `index` at `pc` evaluates the expression bytes `expr` (terminator
        included; the unread 00 after a leaf too). Patched in place when the old
        expression has the same size, else the bank is rebuilt around the new one.
        Returns ('unchanged' | 'in_place' | 'rebuilt', the arg's expression offset)."""
        from . import bankrelink
        if isinstance(bank, int):
            bank = self.banks[bank]
        expr = bytes(expr)
        op, cnt = _u16(bank.data, pc), _u16(bank.data, pc + 2)
        if op is None or op >= 0xFFF0:
            raise ScriptError("not an action statement at 0x%04x" % pc)
        if cnt is None or not 0 <= index < cnt:
            raise ScriptError("arg %d out of range (argcount %s) at 0x%04x" % (index, cnt, pc))
        off = _u16(bank.data, pc + 4 + 2 * index)
        try:
            size = bankrelink.expr_size(bank.data, off)
        except Exception:  # noqa: BLE001 - an operand that does not decode
            size = None
        if size is not None and bytes(bank.data[off:off + size]) == expr:
            return ("unchanged", off)
        if size == len(expr):
            bank.data[off:off + size] = expr
            self.ensure_frames(bank)                   # a deeper expression may need a bigger FRAME
            return ("in_place", off)
        m, _r = self._relink(bank, lambda m: m.set_operand(pc, index, expr))
        npc = m.pc_of(pc)
        return ("rebuilt", _u16(bank.data, npc + 4 + 2 * index))

    def set_arg_value(self, bank, pc, index, value):
        """Set the value that action arg `index` yields at statement `pc`: the literal is
        patched in place when its width allows (`Bank.set_action_arg_value`), otherwise the
        arg gets a fresh literal expression and the bank is rebuilt around it.

        Returns one of:
          * ('unchanged', off)  - the arg already yields `value`; nothing was written
          * ('in_place', off)   - the existing expression at `off` was patched
          * ('rebuilt', off)    - the arg now has its own literal at `off` in the rebuilt bank
        """
        if isinstance(bank, int):
            bank = self.banks[bank]
        cnt = _u16(bank.data, pc + 2)
        if cnt is None or index >= cnt:
            raise ScriptError("arg %d out of range" % index)
        old_off = _u16(bank.data, pc + 4 + 2 * index)
        if old_off is not None:
            cur, ok = arg_constant(bank.data, old_off)
            if ok and cur == value:
                return ("unchanged", old_off)
        try:
            bank.set_action_arg_value(pc, index, value)
            return ("in_place", old_off)
        except ScriptError:
            # a fixed 0/-1/1 push, a u8 too small, a variable, ...: give the arg its own literal
            pass
        return self.set_action_arg_expr(bank, pc, index, self._literal_expr_bytes(value))

    # ---- type-table entries (triggers): mint / remove / re-key a scene registration ----
    def _set_entry_list(self, bank, type_id, records, listing=None):
        """Replace the entry list of `type_id` with `records` ([(event pc or key, subs)]),
        rebuilding the bank; with `listing`, that text is assembled first and a record
        whose event is None points at it. Returns the model."""
        if isinstance(bank, int):
            bank = self.banks[bank]
        if type_id < 0 or type_id >= bank.table_slots:
            raise ScriptError("%s bank %d's type table has %d slots (types 0..%d); type %d cannot "
                              "be registered here" % (bank.kind, bank.index, bank.table_slots,
                                                      bank.table_slots - 1, type_id))
        blobs = [(eid, encode_entry(0, subs)[4:]) for eid, subs in records]

        def edit(m):
            key = m.append_code(listing, self.asm_resolver) if listing is not None else None
            m.set_records(type_id, [(key if eid is None else eid, b) for eid, b in blobs])
            return key
        return self._relink(bank, edit)

    def add_entry(self, bank, type_id, subs=(), event_pc=None, listing=None, position=None):
        """Register a NEW scene trigger: add an entry to the bank's `type_id` list.

        `subs` = the entry's keys (ints, or (tag, value) pairs; -1 = wildcard), matched
        by that type's engine matcher (entry_types.py). The scene
        body is either an existing pc (`event_pc`) or assembled from `listing` text
        (placed after the bank's last statement; END is added when it can fall off its
        end). `position` = index in the list (default: append; matchers take the FIRST
        match in list order, the type-6/7 tick dispatchers take the LAST entry).
        Returns (event_pc in the rebuilt bank, index)."""
        if isinstance(bank, int):
            bank = self.banks[bank]
        if (event_pc is None) == (listing is None):
            raise ScriptError("add_entry needs exactly one of event_pc / listing")
        if listing is None and (event_pc % 2 or decode_statement(bank.data, event_pc) is None):
            raise ScriptError("event_pc 0x%04x is not a decodable statement" % event_pc)
        recs = [(r.event_id, r.subs) for r in bank.entry_records(type_id)] if type_id in \
            bank.type_table_full() else []
        idx = len(recs) if position is None else max(0, min(int(position), len(recs)))
        recs.insert(idx, (event_pc, list(subs)))
        m, key = self._set_entry_list(bank, type_id, recs, listing)
        return self._pc(m, key if listing is not None else event_pc), idx

    def entry_shadow_note(self, bank, type_id, position=None):
        """Advice string (or None) for registering a new `type_id` entry at `position`
        in `bank`: warns when the type's dispatcher runs only the LAST entry (a new
        appended entry silently replaces the map's existing scene of that type) or
        takes the FIRST match (a new first entry can shadow the old ones). Uses the
        entry_types catalogue when available."""
        if isinstance(bank, int):
            bank = self.banks[bank]
        recs = bank.entry_records(type_id)
        if not recs:
            return None
        try:
            from . import entry_types
            sel = (entry_types.ENTRY_TYPES.get(type_id) or {}).get("select", "")
            name = entry_types.type_name(type_id)
        except Exception:
            sel, name = "", "type %d" % type_id
        n = len(recs)
        if sel == "last" and (position is None or position >= n):
            return ("%s runs only the LAST trigger: the new scene replaces the existing one at pc "
                    "0x%04x (CALL 0x%04x from the new body to keep it)" % (name, recs[-1].event_id,
                                                                            recs[-1].event_id))
        if sel == "last":
            return "%s runs only the LAST trigger: a scene inserted at index %d will never run" % (name, position)
        keyless = False
        try:
            keyless = not (entry_types.ENTRY_TYPES.get(type_id) or {}).get("keys")
        except Exception:
            pass
        if sel.startswith("first") and keyless and (position is None or position >= 1):
            return ("%s runs only the FIRST entry: the new scene will never run (the one at pc "
                    "0x%04x does); insert it at index 0 to replace it" % (name, recs[0].event_id))
        if sel.startswith("first") and position == 0:
            return ("%s takes the FIRST matching entry: the new entry at index 0 is checked before the "
                    "%d existing ones (wildcard keys would shadow them)" % (name, n))
        return None

    def entry_key_conflicts(self, bank, type_id, subs, position=None, editing=None):
        """Registering `subs` as a `type_id` entry of `bank` at `position` (None = append),
        or giving entry `editing` these keys: (error or None, [warnings], [other bank
        positions with the same type-2 keys]).

        Error: a type whose dispatcher takes the FIRST matching entry already has an entry
        with exactly these keys that it checks first -- the new one could never run. A
        duplicate checked AFTER the new one is a warning (that scene stops running: the
        deliberate way to replace a scene). Type 2 (ActorInteractScene) is looked up in the
        tail bank, then the primary, then the global bank: the same key in a bank of the
        other level shadows one way or the other, which is a warning naming those banks."""
        if isinstance(bank, int):
            bank = self.banks[bank]
        subs = [tuple(s) if isinstance(s, (tuple, list)) else (1, s) for s in subs]
        try:
            from . import entry_types
            sel = (entry_types.ENTRY_TYPES.get(type_id) or {}).get("select", "")
            name = entry_types.type_name(type_id)
            bad = entry_types.key_errors(type_id, subs)   # keys no entry can use (32-bit, type 2)
        except ImportError:
            sel, name, bad = "", "type %d" % type_id, []
        if bad:
            return "; ".join(bad), [], []
        recs = bank.entry_records(type_id)
        same = [r.index for r in recs if r.index != editing and [tuple(s) for s in r.subs] == subs]
        err, warns, elsewhere = None, [], []
        if same and sel.startswith("first"):
            at = editing if editing is not None else (len(recs) if position is None else position)
            before = [i for i in same if i < at]
            after = [i for i in same if i >= at]
            if before:
                err = ("%s trigger #%d already has exactly these keys and is checked first: this scene "
                       "would never run -- pick other keys (or put it first to replace that one)"
                       % (name, before[0]))
            elif after:
                warns.append("%s trigger #%d has the same keys and is now checked after this one: that "
                             "scene stops running" % (name, after[0] + (0 if editing is not None else 1)))
        if type_id == 2 and subs:
            rank = {"tail": 0, "primary": 1, "global": 2}      # the lookup order: lower wins
            mine = rank.get(bank.kind, 1)
            wins, loses = [], []
            for pos, b in enumerate(self.banks):
                if b is bank or b.kind == bank.kind:
                    continue
                if any([tuple(s) for s in r.subs] == subs for r in b.entry_records(2)):
                    elsewhere.append(pos)
                    (loses if rank.get(b.kind, 1) < mine else wins).append(b.kind)
            if loses:
                warns.append("%d %s bank(s) use this key too: where they are loaded, theirs runs "
                             "instead of this scene" % (len(loses), " / ".join(sorted(set(loses)))))
            if wins:
                warns.append("the %s bank(s) use this key too: where this bank is loaded, this scene "
                             "runs instead of theirs" % " / ".join(sorted(set(wins))))
        return err, warns, elsewhere

    def remove_entry(self, bank, type_id, index):
        """Unregister the `index`-th entry of `type_id` (other entries keep their order;
        the scene's code stays -- other code may still use it). Returns (event pc, subs)
        as they were."""
        if isinstance(bank, int):
            bank = self.banks[bank]
        recs = [(r.event_id, r.subs) for r in bank.entry_records(type_id)]
        if not (0 <= index < len(recs)):
            raise ScriptError("type %d has %d triggers; no index %d" % (type_id, len(recs), index))
        removed = recs.pop(index)
        self._set_entry_list(bank, type_id, recs)
        return removed

    def set_entry(self, bank, type_id, index, subs=None, event_pc=None):
        """Re-key an entry (new `subs`) and/or repoint it at another scene pc. A same-size
        record is patched in place; otherwise the bank is rebuilt."""
        if isinstance(bank, int):
            bank = self.banks[bank]
        recs = [(r.event_id, r.subs) for r in bank.entry_records(type_id)]
        if not (0 <= index < len(recs)):
            raise ScriptError("type %d has %d triggers; no index %d" % (type_id, len(recs), index))
        eid, old_subs = recs[index]
        if event_pc is not None:
            if event_pc % 2 or decode_statement(bank.data, event_pc) is None:
                raise ScriptError("event_pc 0x%04x is not a decodable statement" % event_pc)
            eid = event_pc
        if subs is not None:
            old_subs = list(subs)
        new_rec = (eid, old_subs)
        if encode_entry(*new_rec) == encode_entry(*recs[index]):
            return
        rec = bank.entry_records(type_id)[index]
        blob = encode_entry(*new_rec)
        if len(blob) == rec.size:
            bank.data[rec.offset:rec.offset + rec.size] = blob
            return
        recs[index] = new_rec
        self._set_entry_list(bank, type_id, recs)

    def build(self):
        """Re-emit the file. Bank data is written back at its recorded offset so any
        in-place statement edits (same length) round-trip byte-perfect. Refuses to emit a
        file whose banks outgrew the header's load buffers (see _sync_max_bank_size)."""
        self._sync_max_bank_size()
        bad = self.validate_bank_sizes()
        if bad:
            raise ScriptError("; ".join(bad))
        out = bytearray(self.data)
        for b in self.banks:
            out[b.file_off:b.file_off + len(b.data)] = b.data
        return bytes(out)

    # convenience
    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            return cls(f.read())

    def save(self, path):
        with open(path, "wb") as f:
            f.write(self.build())


# ---- disassembly -------------------------------------------------------------------
class Scene:
    """A disassembled scene: an entry PC and its reachable statements (pc -> Statement)."""
    def __init__(self, bank_index, kind, action_type, entry_pc):
        self.bank_index = bank_index
        self.kind = kind
        self.action_type = action_type
        self.entry_pc = entry_pc
        self.stmts = OrderedDict()     # pc -> Statement (sorted by pc on finish)
        self.ok = True
        self.error = None

    def covered(self):
        return sum(s.size for s in self.stmts.values())


def disassemble_scene(bank, action_type, entry_pc):
    """Flow-follow from entry_pc, decoding all reachable statements."""
    sc = Scene(bank.index, bank.kind, action_type, entry_pc)
    buf = bank.data
    seen = set()
    stack = [entry_pc]
    while stack:
        pc = stack.pop()
        if pc in seen:
            continue
        seen.add(pc)
        if pc is None or pc < 0 or pc >= len(buf):
            sc.ok = False
            sc.error = "oob pc %s" % pc
            continue
        st = decode_statement(buf, pc)
        if st is None:
            sc.ok = False
            sc.error = "bad opcode 0x%04x @ %d" % (_u16(buf, pc) or -1, pc)
            continue
        sc.stmts[pc] = st
        for t in st.code_targets:
            if t is not None:
                stack.append(t)
        if st.falls_through and not st.terminator:
            stack.append(pc + st.size)
    sc.stmts = OrderedDict(sorted(sc.stmts.items()))
    return sc


def disassemble_bank(bank, discover=True):
    """Return list[Scene] for every scene in the bank.

    Scenes come from two sources: (1) the bank's type-table entry lists (the
    per-bank registry), and (2) when ``discover`` is set, a gap-fill pass that
    finds clean scenes in the code region that no type-table entry reaches.
    Source (2) is needed because some scenes are registered only in the global
    scene index (MYCF region B), not the bank's local type table -- without it,
    e.g. the "I was about to call you over." cutscene is invisible to search."""
    scenes = []
    seen = set()
    for (t, eid) in bank.scene_entries():
        sc = disassemble_scene(bank, t, eid)
        # A real scene entry points into the bytecode region, past the 256-byte
        # type-table header (64 slots x 4 B). A declared entry that lands inside
        # the header AND fails to decode is a spurious event-id record produced by
        # the entry-list heuristic, not a scene -- drop it (never drop a scene that
        # decodes cleanly).
        if not sc.ok and eid is not None and eid < 256:
            continue
        scenes.append(sc)
        seen.add(eid)
    if not discover:
        return scenes
    d = bank.data
    tt = bank.type_table()
    code_end = min(tt.values()) if tt else len(d)        # entry/expr pool starts here
    covered = set()
    for sc in scenes:
        covered |= set(sc.stmts.keys())
    # Candidate scene starts: offset 0, plus the byte after every RET/0xFFFF (2 bytes) in
    # the code region — a routine always begins on such a boundary. The word after a
    # FRAME op (0xFFF1, 4 bytes) is kept as a candidate too: FRAME falls through, so
    # these are normally already covered by the routine that contains the FRAME, and
    # the candidate only matters when that routine's start was missed.
    cands = [0]
    for off in range(0, code_end - 2, 2):
        w = _u16(d, off)
        if w == 0xFFFF:
            cands.append(off + 2)
        elif w == 0xFFF1:
            cands.append(off + 4)
    # `failed` records every pc a FAILED candidate walk touched. A later candidate
    # starting on such a pc would re-walk a suffix of the same flow into (usually)
    # the same bad opcode, so those retries are suppressed. This is a heuristic —
    # in principle a suffix could avoid the bad branch — but it is corpus-verified
    # identical (2026-09-01: full-container discovery census byte-for-byte equal
    # with and without the suppression) and it removes the post-FRAME cost blowup
    # where junk regions spawned thousands of deep failing walks per bank.
    failed = set()
    for st_off in cands:
        if st_off >= code_end or st_off in covered or st_off in seen or st_off in failed:
            continue
        sc = disassemble_scene(bank, -1, st_off)         # -1 = discovered (no type)
        if sc.ok and sc.stmts:
            scenes.append(sc)
            covered |= set(sc.stmts.keys())
            seen.add(st_off)
        else:
            failed |= set(sc.stmts.keys())
            failed.add(st_off)
    # Gap pass: code no scene covers whose start is not after a RET / FRAME -- the very start
    # of the code area (just past the type table, byte 296) or code after a JMP. A subroutine
    # whose last CALL was deleted ends up like that. Only walks that hold something real (an
    # action, a line, a call, a menu) count: the compiler leaves thousands of lone
    # unreachable RETs / JMPs after jumps, and 12 real pieces hide this way in the shipped game.
    cov = bytearray(code_end)
    for sc in scenes:
        for pc, st in sc.stmts.items():
            cov[pc:min(pc + st.size, code_end)] = b"\x01" * max(0, min(pc + st.size, code_end) - pc)
    bank.type_table_full()
    off = getattr(bank, "_table_end", 0)
    while off < code_end:
        if cov[off]:
            off += 1
            continue
        start = off
        while off < code_end and not cov[off]:
            off += 1
        if start % 2 or start in seen or start in failed:
            continue
        sc = disassemble_scene(bank, -1, start)
        if not (sc.ok and sc.stmts):
            continue
        if any(st.op < 0xFFF0 or st.mnem in ("DIALOG", "CALL", "PROMPT_CHOICE", "PROMPT_CHOICE_FORCED")
               for st in sc.stmts.values()):
            scenes.append(sc)
            seen.add(start)
        for pc, st in sc.stmts.items():
            cov[pc:min(pc + st.size, code_end)] = b"\x01" * max(0, min(pc + st.size, code_end) - pc)
    return scenes


def is_real_statement(st):
    """An action, a dialogue line, a CALL or a menu -- not just flow (RET / JMP / FRAME ...)."""
    return st.op < 0xFFF0 or st.mnem in ("DIALOG", "CALL", "PROMPT_CHOICE", "PROMPT_CHOICE_FORCED")


def unreached(scenes):
    """[(scene, own pcs)] for the unregistered (discovered) scenes of one bank, judged by their
    OWN code: the statements no registered scene reaches (nor an earlier row). A discovered
    walk follows its jumps into code a registered scene already runs (MAP_F_ROOM_00's lone
    `JMP` at 0x01aa leads into the whole Prince Points menu), so a row whose own code holds
    nothing real (is_real_statement) is left out; its bytes stay where they are. `scenes` =
    disassemble_bank(bank)."""
    covered = set()
    for sc in scenes:
        if sc.action_type >= 0:
            covered |= set(sc.stmts)
    out = []
    for sc in scenes:
        if sc.action_type >= 0:
            continue
        own = [pc for pc in sc.stmts if pc not in covered]
        if any(is_real_statement(sc.stmts[pc]) for pc in own):
            out.append((sc, own))
            covered |= set(own)
    return out


def iter_scenes(container, discover=True):
    """Yield every Scene in the container (all banks, all entry points)."""
    for bk in container.banks:
        for sc in disassemble_bank(bk, discover=discover):
            yield bk, sc


# ---- who speaks each DIALOG line -------------------------------------------------------
# A DIALOG carries only the text id; the speaker is whatever speaker op ran last, and it
# persists across lines until the next speaker op or EndDialogue (op 92). Speaker ops: the
# portrait cues 16..75 (slot = (op - 16) // 2, opcode_meta.portrait_speaker_slot) and
# SetSpeakerVoice (op 10: a name plate from the character-name archive, arg0).
_SPEAKER_UNKNOWN = object()          # no speaker established, or paths disagree
_SPEAKER_IN = object()               # "whatever the caller had" (routine summaries)
_SPEAKER_CLEAR_OPS = {92}            # EndDialogue clears the speaker
_SPEAKER_OPAQUE_OPS = set()          # (every speaker-related op is now modelled below)
# Ops 8/9, 12/13 and 14/15 also set the name plate: each loads name-archive entry arg0 into
# the message box (Dialogue_LoadAndShowText with the task's name archive, latched at task+108
# -- the same path SetSpeakerVoice takes): Dialogue_ProcessLineDirective RF4S.exe+0x209DF0
# (1..26 and >= 48 = that name, 0 = clear, 27..47 = event participant, resolved at run time),
# Script_VMOp_SetSpeakerById +0x207A70 (id remapped by
# Dialogue_RemapBubbleLineId24To28: 24->309, 25->149, 26->239, 27->24, 28->25),
# Script_VMOp_SetSpeakerByIdWithEmote +0x207CE0 (id used as is).
# Ops 6/7 (Script_VMOp_ShowPortraitWithEmote +0x207900) only float a bubble over an actor and leave
# the message-box speaker alone.
_BUBBLE_ID_REMAP = {24: 309, 25: 149, 26: 239, 27: 24, 28: 25}
# Narration mode: ops 614 (Script_VMOp_SetDialogueSpeakerSideByte RF4S.exe+0x21C740, value 2)
# and 699 (Script_VMOp_SetDialogueSecondarySpeakerIfNonzero +0x220250, any non-zero arg) set
# byte 2 of the dialogue mode word g_gameGlobalsSlotTable.entries[9] to 2; with it the box
# hides the speaker-name label (DialogueBox_SpawnBubbleAndSpeakerNameSprites) and the
# typewriter mutes the text blips (Sprite_TickTypewriterDripText). The HUD teardown resets it.
SPEAKER_NARRATION = "narration"


def _speaker_const_arg(bank, st, i=0):
    """Static integer value of argument `i` (a literal, or a tag-3/4 leaf's constant), else None."""
    if i >= len(st.args):
        return None
    off = st.args[i]
    buf = bank.data
    if 0 <= off < len(buf) and buf[off] in (3, 4):
        return _u32(buf, off + 1)
    v, ok = eval_expr(buf, off)
    return v if ok else None


def static_arg(bank, st, i=0):
    """Static integer value of statement argument `i` (a literal, or a tag-3/4 leaf's
    constant), or None when it is computed at run time."""
    if i >= len(st.args):
        return None
    return _speaker_const_arg(bank, st, i)

def _name_plate(n):
    nm = meta.enum_arg_label(10, 0, n) if n is not None else None
    return nm if nm else _SPEAKER_UNKNOWN


def _speaker_of(bank, st):
    """(changes, name) for one statement: changes=False leaves the speaker as it is."""
    op = st.op
    if 16 <= op <= 75:
        slot = meta.portrait_speaker_slot(op)
        if slot and slot[0] < len(getattr(meta, "PORTRAIT_SPEAKERS", [])):
            return True, ("player" if slot[0] == 0 else meta.speaker_name(slot[0]))
        return True, _SPEAKER_UNKNOWN
    if op == 10:
        if st.args:
            v, ok = eval_expr(bank.data, st.args[0])
            if ok and v is not None:
                nm = meta.enum_arg_label(10, 0, v)
                return True, (nm if nm else _SPEAKER_UNKNOWN)
        return True, _SPEAKER_UNKNOWN
    if op in (8, 9):
        v = _speaker_const_arg(bank, st)
        if v is not None and (1 <= v <= 26 or 48 <= v < 0xFFFF):
            return True, _name_plate(v)
        return True, _SPEAKER_UNKNOWN                      # 0 clears; 27..47 run time
    if op == 699:
        v = _speaker_const_arg(bank, st)
        if v is None:
            return True, _SPEAKER_UNKNOWN
        return (True, SPEAKER_NARRATION) if v else (False, None)
    if op == 614:
        v = _speaker_const_arg(bank, st)
        return True, (SPEAKER_NARRATION if v == 2 else _SPEAKER_UNKNOWN)
    if op in (12, 13, 14, 15):
        v = _speaker_const_arg(bank, st)
        if v:
            return True, _name_plate(_BUBBLE_ID_REMAP.get(v, v) if op in (12, 13) else v)
        return True, _SPEAKER_UNKNOWN
    if op in _SPEAKER_CLEAR_OPS or op in _SPEAKER_OPAQUE_OPS:
        return True, _SPEAKER_UNKNOWN
    return False, None


def dialog_speakers(scene, bank):
    """{DIALOG pc: speaker name} for the lines whose speaker is certain: every path that
    reaches the line set the same speaker first -- through branches, into CALLed routines
    of the same scene and back out of them. A line inside a routine that does not set the
    speaker itself takes its callers' speaker, and only when all of them agree. Lines with
    no speaker op before them, or with paths that disagree, are left out (their speaker
    comes from outside the scene: the game, or code that is not in this scene)."""
    stmts = scene.stmts

    def merge(a, b):
        if a is None:
            return b
        if b is None or a is b or a == b:
            return a
        return _SPEAKER_UNKNOWN

    # routine key None = the scene entry; else the CALL target pc
    before = {}                      # (routine, pc) -> state before the statement
    exits = {}                       # routine -> exit state (relative to _SPEAKER_IN)
    call_sites = {}                  # routine -> [(caller routine, state at the call)]
    done = set()

    def run(routine, entry, state_in, depth):
        work = [(entry, state_in)]
        exit_state = None
        guard = 0
        while work and guard < 50000:
            guard += 1
            pc, st_in = work.pop()
            st = stmts.get(pc)
            if st is None:
                continue
            key = (routine, pc)
            old = before.get(key)
            new = merge(old, st_in)
            if old is not None and (new is old or new == old):
                continue
            before[key] = new
            cur = new
            if st.mnem == "CALL" and st.code_targets:
                tgt = st.code_targets[0]
                if tgt in stmts and depth < 12:
                    call_sites.setdefault(tgt, []).append((routine, cur))
                    if tgt not in done:
                        done.add(tgt)
                        exits[tgt] = None                # recursion guard
                        exits[tgt] = run(tgt, tgt, _SPEAKER_IN, depth + 1)
                    out = exits.get(tgt)
                    cur = _SPEAKER_UNKNOWN if out is None else (cur if out is _SPEAKER_IN else out)
                else:
                    cur = _SPEAKER_UNKNOWN
                work.append((pc + st.size, cur))
                continue
            changes, nm = _speaker_of(bank, st)
            if changes:
                cur = nm
            if st.mnem in ("END", "RET"):
                exit_state = merge(exit_state, cur)
                continue
            for t in st.code_targets:
                if t is not None:
                    work.append((t, cur))
            if st.falls_through and not st.terminator:
                work.append((pc + st.size, cur))
        return exit_state if exit_state is not None else _SPEAKER_UNKNOWN

    run(None, scene.entry_pc, _SPEAKER_UNKNOWN, 0)

    resolving = set()

    def routine_input(routine):
        """The speaker every caller of `routine` passes in (merged), or _SPEAKER_UNKNOWN."""
        if routine is None:
            return _SPEAKER_UNKNOWN
        if routine in resolving:
            return _SPEAKER_UNKNOWN
        resolving.add(routine)
        acc = None
        for caller, st_in in call_sites.get(routine, []):
            acc = merge(acc, resolve(caller, st_in))
        resolving.discard(routine)
        return _SPEAKER_UNKNOWN if acc is None else acc

    def resolve(routine, state):
        return routine_input(routine) if state is _SPEAKER_IN else state

    out = {}
    for (routine, pc), state in before.items():
        st = stmts.get(pc)
        if st is None or st.mnem != "DIALOG":
            continue
        name = resolve(routine, state)
        prev = out.get(pc, None)
        if pc in out and prev != name:
            out[pc] = _SPEAKER_UNKNOWN              # the same line reached with two speakers
        else:
            out[pc] = name
    return {pc: nm for pc, nm in out.items() if isinstance(nm, str)}


def statement_text_ids(st):
    """The dialogue line ids a statement shows: a DIALOG's line, or the option lines of a
    choice menu (PROMPT_CHOICE / PROMPT_CHOICE_FORCED items). Empty for anything else."""
    if st.mnem == "DIALOG":
        return [st.dialog_id] if st.dialog_id is not None else []
    if st.mnem in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED"):
        return list(st.items)
    return []


def find_scenes_with_dialog(container, substring, dialog):
    """Find scenes whose dialogue -- DIALOG lines and choice-menu options -- contains
    `substring` (case-insensitive). `dialog` = callable(line_id)->str. Returns list of
    (bank, Scene, [line_ids])."""
    sub = substring.lower()
    hits = []
    for bk, sc in iter_scenes(container):
        ids = []
        for st in sc.stmts.values():
            for i in statement_text_ids(st):
                try:
                    s = dialog(i)
                except Exception:
                    s = None
                if s and sub in s.lower():
                    ids.append(i)
        if ids:
            hits.append((bk, sc, ids))
    return hits


def dev_menus(container, dialog, banks=None):
    """The developers' test menus left in rf3.mc: PROMPT_CHOICE statements whose items are
    '＊'-prefixed debug strings ('＊Hand Over Recipe', '＊Firefly Festival', '＊Invite', ...).
    Every marriage candidate's primary bank carries the same three (events, festivals,
    dates) and the villager banks a greetings one; each item jumps to a routine that plays
    that event's dialogue for this NPC -- a labelled index of the bank's lines (the
    gameplay effect itself, e.g. the item a 'Hand Over Item' gives, runs in the exe, not
    here). Returns [(bank, scene, menu Statement, [(item text, target pc, first line id)])];
    the menu's CANCEL branch is left out."""
    out = []
    sel = container.banks if banks is None else [container.banks[i] for i in banks]
    for bk in sel:
        for sc in disassemble_bank(bk):
            for st in sc.stmts.values():
                if st.mnem not in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED") or not st.items:
                    continue
                names = []
                for i in st.items:
                    try:
                        names.append(dialog(i) or "")
                    except Exception:
                        names.append("")
                if sum(1 for n in names if n.startswith("\uff0a")) < 2:
                    continue
                targets = st.code_targets[1:] if st.mnem == "PROMPT_CHOICE" else st.code_targets
                rows = []
                for nm, tgt in zip(names, targets):
                    first, seen, pc = None, 0, tgt
                    while pc in sc.stmts and seen < 64 and first is None:  # first DIALOG, following CALLs
                        s2 = sc.stmts[pc]
                        if s2.mnem == "DIALOG":
                            first = s2.dialog_id
                        elif s2.mnem == "CALL" and s2.code_targets:
                            pc = s2.code_targets[0]; seen += 1; continue
                        elif not s2.falls_through or s2.terminator:
                            break
                        pc += s2.size; seen += 1
                    rows.append((nm, tgt, first))
                out.append((bk, sc, st, rows))
    return out


def _const_arg(buf, off):
    """Integer value of a static action argument, else None."""
    try:
        return int(arg_repr(buf, off))
    except (TypeError, ValueError):
        return None


def _code_touches_mask(by_pc, start, _depth=0):
    """True when the code reached from `start` (following jumps and nested CALLs, within the
    decoded statements `by_pc`) runs a choice-visibility-mask op (610 / 611 / 612)."""
    seen, stack = set(), [start]
    while stack:
        pc = stack.pop()
        if pc in seen or pc not in by_pc:
            continue
        seen.add(pc)
        st = by_pc[pc]
        if st.op in (610, 611, 612):
            return True
        if st.mnem == "CALL":
            if _depth < 8 and st.code_targets and _code_touches_mask(by_pc, st.code_targets[0], _depth + 1):
                return True
        else:
            stack.extend(t for t in st.code_targets if t is not None)
        if st.falls_through and not st.terminator:
            stack.append(pc + st.size)
    return False


def _static_choice_mask(buf, stmts, idx, joins, detail=None):
    """Visibility-mask bits the ops right before stmts[idx] leave KNOWN: {bit: 0/1}.

    Walks back over the straight-line run of action statements (stopping at a control op or
    a branch target), then replays ops 610/611/612 forward the way the handlers do:
    610 (Script_VMOp_SetSceneChoiceVisibleMaskFromArgs) zeroes mask dword 0 and sets bit
    i (shl wraps at 32) for every non-zero arg i; 611 (..ClearSceneChoiceVisibleMaskRange)
    clears bits [start, start+count) of dword 0; 612 (..ToggleSceneChoiceVisibleBit) sets or
    clears one bit of the 128 (dword index clamped to 3). A non-static arg makes the bits it
    touches unknown. Returns (known, touched) -- touched False when no mask op was seen.
    `detail` (a dict) gets 'dynamic' = the bits a 612 in the run sets from a run-time value
    and 'opaque' = True when bits came from somewhere this can't follow (a helper, a
    non-constant bit index or 610 / 611 argument, an earlier path)."""
    if detail is not None:
        detail.update(dynamic=set(), opaque=False)
    run = []
    if stmts[idx].pc in joins:                        # reached from elsewhere too
        return {}, False
    j = idx - 1
    while j >= 0:
        s = stmts[j]
        # control ops that don't touch the mask are stepped over (the shipped idiom often
        # sets the bits, then CALLs a helper or shows a line, then prompts)
        if (s.op >= 0xFFF0 and s.mnem not in ("CALL", "DIALOG", "EVAL", "FRAME")) \
                or s.pc + s.size != stmts[j + 1].pc:
            break
        run.append(s)
        if s.pc in joins:
            break
        j -= 1
    known, touched = {}, False
    # A menu pick clears the whole mask (SceneEvent_FinalizeAndPickFromBitmap RF4S.exe+0x1F49C0
    # zeroes +244..+260), so when no path back from the start of this run sets a bit since the
    # scene start or the previous menu, every bit the run leaves alone is 0: setting bits 0 and 2
    # only hides option 1 (seen in game 2026-10-02).
    if run and not _mask_set_on_a_path(stmts, j + 1):
        known = {b: 0 for b in range(128)}
    elif detail is not None:
        detail["opaque"] = True
    by_pc = None
    for s in reversed(run):
        if s.mnem == "CALL":
            # a helper that sets the mask itself (the shipped menus often do): the bits are
            # then not known statically, but reg0 does get the pick
            if by_pc is None:
                by_pc = {x.pc: x for x in stmts}
            if s.code_targets and _code_touches_mask(by_pc, s.code_targets[0]):
                touched = True
                known = {}
                if detail is not None:
                    detail["opaque"] = True
            continue
        vals = [_const_arg(buf, a) for a in s.args]
        if s.op == 610:
            touched = True
            for b in range(32):
                known[b] = 0
            for i, v in enumerate(vals):
                b = i & 31
                if v is None:
                    known.pop(b, None)
                    if detail is not None:
                        detail["opaque"] = True
                elif v:
                    known[b] = 1
        elif s.op == 611:
            touched = True
            st_, cnt = (vals + [None, None])[:2]
            if st_ is None or cnt is None:
                for b in range(32):
                    known.pop(b, None)
                if detail is not None:
                    detail["opaque"] = True
            else:
                for k in range(min(cnt, 32)):
                    known[(st_ + k) & 31] = 0
        elif s.op == 612:
            touched = True
            bit, val = (vals + [None, None])[:2]
            if bit is None:
                known = {}
                if detail is not None:
                    detail["opaque"] = True
            else:
                b = min(bit >> 5, 3) * 32 + (bit & 31)
                if val is None:
                    known.pop(b, None)
                    if detail is not None:
                        detail["dynamic"].add(b)
                else:
                    known[b] = 1 if val else 0
                    if detail is not None:
                        detail["dynamic"].discard(b)
    return known, touched


def _mask_set_on_a_path(stmts, idx):
    """True when some path back from the choice at stmts[idx] -- through jumps, branches and
    their rejoin points, up to the scene start or an earlier choice (a choice clears the mask)
    -- runs a visibility-mask op, directly or in a CALLed helper. The shipped shop menus set
    the mask, branch to one of three helpers, rejoin, then prompt."""
    by_pc = {x.pc: x for x in stmts}
    preds = {}
    for x in stmts:
        if x.falls_through and not x.terminator and x.pc + x.size in by_pc:
            preds.setdefault(x.pc + x.size, []).append(x.pc)
        if x.mnem != "CALL":
            for t in x.code_targets:
                if t is not None:
                    preds.setdefault(t, []).append(x.pc)
    seen, stack = set(), list(preds.get(stmts[idx].pc, ()))
    while stack:
        pc = stack.pop()
        if pc in seen:
            continue
        seen.add(pc)
        st = by_pc[pc]
        if st.op in (610, 611, 612):
            return True
        if st.mnem in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED"):
            continue                      # that menu consumed (cleared) any earlier mask
        if st.mnem == "CALL" and st.code_targets and _code_touches_mask(by_pc, st.code_targets[0]):
            return True
        stack.extend(preds.get(pc, ()))
    return False


def choice_results(buf, stmts, idx):
    """What the choice at stmts[idx] writes to reg0. None when no visibility-mask op (610 /
    611 / 612) comes right before it: the game then leaves reg0 UNTOUCHED and only the jump
    target tells the options apart. Otherwise [(option index k, shown)] -- the pick's reg0 is
    k (its ORIGINAL index, SceneEvent_FinalizeAndPickFromBitmap RF4S.exe+0x1F49C0) and shown
    is True / False (the mask shows / hides the option) or None (not known statically)."""
    st = stmts[idx]
    joins = set()
    for s0 in stmts:
        joins.update(t for t in s0.code_targets if t is not None)
    known, touched = _static_choice_mask(buf, stmts, idx, joins)
    if not touched:
        if not _mask_set_on_a_path(stmts, idx):
            return None
        known = {}                        # set further back (branches rejoin): bits unknown
    out = []
    for k in range(min(len(st.items), MAX_CHOICE_OPTIONS)):
        v = known.get(k)
        out.append((k, None if v is None else bool(v)))
    return out


def _first_dialogs_after(stmts, starts):
    """{(pc, line id)} of the first DIALOG on every path from the pcs `starts`, following
    fall-through, jumps, branches and CALLs (into the helper and past it); a path stops at
    its first DIALOG, a menu, or a RET / END."""
    by_pc = {s.pc: s for s in stmts}
    found, seen, stack = set(), set(), [p for p in starts if p is not None]
    while stack:
        pc = stack.pop()
        if pc in seen or pc not in by_pc:
            continue
        seen.add(pc)
        s = by_pc[pc]
        if s.mnem == "DIALOG":
            found.add((s.pc, s.dialog_id))
            continue
        if s.mnem in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED"):
            continue
        stack.extend(t for t in s.code_targets if t is not None)
        if s.falls_through and not s.terminator:
            stack.append(s.pc + s.size)
    return found


def choice_line_freezes(stmts):
    """[(menu pc, [DIALOG pcs], line id)]: menus whose next DIALOG (on some path) shows the
    menu's LAST option line, which freezes the scene. Dialogue_HandleScriptActionShowLine
    (RF4S.exe+0x1F43B0) starts a line only when its id differs from the one it latched last
    (g_currentSceneContext+68); the menu passes every option through it, the last one last,
    and the pick (SceneEvent_FinalizeAndPickFromBitmap) does not clear the latch, so that
    DIALOG never starts and waits forever. Seen in game 2026-10-02 (three menus froze;
    writing -1 to the latch released each); no shipped menu does it."""
    out = []
    for st in stmts:
        if st.mnem not in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED") or not st.items:
            continue
        opt_tg = st.code_targets[1:] if st.mnem == "PROMPT_CHOICE" else list(st.code_targets)
        same = sorted({pc for pc, line in _first_dialogs_after(stmts, opt_tg) if line == st.items[-1]})
        if same:
            out.append((st.pc, same, st.items[-1]))
    return out


def freeze_text(line, dialog_pcs):
    """The warning for a choice_line_freezes hit."""
    return ("DIALOG #%d at %s right after this menu shows the menu's LAST option line: the game "
            "only starts a line whose id differs from the last one it started, and the options "
            "were started last, so this line never starts and the scene freezes (no input). Show "
            "a different line first" % (line, ", ".join("0x%04x" % pc for pc in dialog_pcs)))


SUPPRESS_OP = 1          # SetDialogueSuppressed
END_DIALOGUE_OP = 92     # EndDialogue: closes the box


def _graph(stmts):
    by_pc = {s.pc: s for s in stmts}
    succ, pred = {}, {}
    for s in stmts:
        nxt = [t for t in s.code_targets if t is not None]
        if s.falls_through and not s.terminator:
            nxt.append(s.pc + s.size)
        succ[s.pc] = [t for t in nxt if t in by_pc]
        for t in succ[s.pc]:
            pred.setdefault(t, []).append(s.pc)
    return by_pc, succ, pred


def _suppress_value(buf, st):
    """The literal SetDialogueSuppressed argument (bit 0), or None when it is computed."""
    if not st.args or st.args[0] is None:
        return None
    v, ok = eval_expr(buf, st.args[0])
    return (v & 1) if ok and v is not None else None


def dialogue_suppress_problems(buf, stmts):
    """[(pc, 'warning', message)] for SetDialogueSuppressed (op 1). While it is on, the DIALOG
    handler (Dialogue_HandleScriptActionShowLine, RF4S.exe+0x1F43B0) skips starting each line
    and waits for the open box's finished flag, which the previous line already used: with a
    box still open the scene freezes (in game 2026-10-02); with the box closed (EndDialogue)
    the line is skipped at once. Nothing but the engine's scene reset turns it off."""
    by_pc, succ, pred = _graph(stmts)
    out = []
    for st in stmts:
        if st.op != SUPPRESS_OP or _suppress_value(buf, st) == 0:
            continue
        # is a box open here? (a DIALOG / menu since the last EndDialogue on some path)
        open_box, seen, stack = False, set(), list(pred.get(st.pc, ()))
        while stack and not open_box:
            pc = stack.pop()
            if pc in seen:
                continue
            seen.add(pc)
            x = by_pc[pc]
            if x.op == END_DIALOGUE_OP:
                continue
            if x.mnem in ("DIALOG", "PROMPT_CHOICE", "PROMPT_CHOICE_FORCED"):
                open_box = True
                break
            stack.extend(pred.get(pc, ()))
        # what follows while it is on: a DIALOG before EndDialogue / turning it off, or the end
        hits_dialog, leaks, seen, stack = [], False, set(), list(succ.get(st.pc, ()))
        while stack:
            pc = stack.pop()
            if pc in seen:
                continue
            seen.add(pc)
            x = by_pc[pc]
            if x.op == SUPPRESS_OP and _suppress_value(buf, x) == 0:
                continue
            if x.mnem == "DIALOG":
                hits_dialog.append(pc)
                stack.extend(succ.get(pc, ()))
                continue
            if x.op == END_DIALOGUE_OP:
                stack.extend(succ.get(pc, ()))     # box closed: later lines are only skipped
                continue
            if x.terminator and x.mnem in ("RET", "END"):
                leaks = True
            stack.extend(succ.get(pc, ()))
        first = _first_after_closed(by_pc, succ, st.pc)
        if open_box and first:
            out.append((st.pc, "warning", "SetDialogueSuppressed(1) with a dialogue box still open: "
                        "the next DIALOG (0x%04x) skips its line and waits for the open box to finish "
                        "again, which never happens, so the scene freezes. Call EndDialogue() first"
                        % first))
        if leaks:
            out.append((st.pc, "warning", "SetDialogueSuppressed(1) is still on where the scene ends: "
                        "every later DIALOG in the game stays skipped until the engine resets the "
                        "scene context. Turn it off with SetDialogueSuppressed(0) before the end"))
    return out


def _first_after_closed(by_pc, succ, start):
    """The pc of the first DIALOG reached from `start` before any EndDialogue or
    SetDialogueSuppressed, or None."""
    seen, stack = set(), list(succ.get(start, ()))
    while stack:
        pc = stack.pop()
        if pc in seen:
            continue
        seen.add(pc)
        x = by_pc[pc]
        if x.mnem == "DIALOG":
            return pc
        if x.op in (END_DIALOGUE_OP, SUPPRESS_OP):
            continue
        stack.extend(succ.get(pc, ()))
    return None


def choice_problems(buf, stmts, text_count=None):
    """Static checks on PROMPT_CHOICE / PROMPT_CHOICE_FORCED against how RF4S.exe runs them.

    `stmts` = the pc-ordered Statements of one scene (or of a linearly decoded region),
    `buf` = the bank bytes their expression offsets point into, `text_count` = entries in
    the rf3mc text archive (optional). Returns [(pc, 'error'|'warning', message)].

    Exe facts behind each check (RF4S.exe): Script_VMStep (+0x23EF60) cases 0xFFF4/0xFFF5;
    SceneEvent_FinalizeAndPickFromBitmap (+0x1F49C0) returns the picked VISIBLE row and maps
    it back through the mask bits into reg0; ChoiceDialog_ConfirmSelection (+0x239330)
    divides by the row count; ChoiceDialog_ConfirmViaScrollArrow (+0x239670) is the cancel
    key (it moves the cursor to the LAST row); Text_LoadStringFromArchive (+0x232290) loads
    entry 0 for an out-of-range id."""
    out = [(pc, "warning", freeze_text(line, dpcs)) for pc, dpcs, line in choice_line_freezes(stmts)]
    joins = set()
    for s in stmts:
        joins.update(t for t in s.code_targets if t is not None)
    for idx, st in enumerate(stmts):
        if st.mnem not in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED"):
            continue
        n = len(st.items)
        opt_tg = st.code_targets[1:] if st.mnem == "PROMPT_CHOICE" else list(st.code_targets)
        if n == 0:
            out.append((st.pc, "error", "choice with no options: the menu has zero rows and "
                        "confirming divides by zero (crash)"))
            continue
        if n > MAX_CHOICE_OPTIONS:
            out.append((st.pc, "error", "%d options: the game queues at most %d rows; options "
                        "%d.. are dropped and their targets are unreachable"
                        % (n, MAX_CHOICE_OPTIONS, MAX_CHOICE_OPTIONS)))
        if text_count is not None:
            bad = [i for i in st.items if i >= text_count]
            if bad:
                out.append((st.pc, "error", "option text id(s) %s outside the text archive "
                            "(%d entries): the game shows entry 0 instead"
                            % (", ".join("#%d" % i for i in bad[:6]), text_count)))
        if st.mnem == "PROMPT_CHOICE" and st.code_targets and opt_tg \
                and st.code_targets[0] != opt_tg[-1]:
            out.append((st.pc, "warning", "CANCEL target 0x%04x is not the last option's "
                        "target: the cancel key moves the cursor to the LAST option, and the "
                        "CANCEL slot is never taken (shipped menus repeat the last target "
                        "there)" % st.code_targets[0]))
        known, touched = _static_choice_mask(buf, stmts, idx, joins)
        if not touched:
            continue
        opts = range(min(n, MAX_CHOICE_OPTIONS))
        if any(v == 1 for v in known.values()) and all(known.get(b) == 0 for b in opts):
            out.append((st.pc, "error", "the visibility mask hides every option (bits set only "
                        "past option %d): the menu opens with zero rows and confirming "
                        "divides by zero (crash). An all-zero mask shows every option instead"
                        % (n - 1)))
            continue
        hidden_early = any(known.get(b) == 0 and any(known.get(k) != 0 for k in opts if k > b)
                           for b in opts)
        if hidden_early and any(known.values()) and len(set(opt_tg)) > 1:
            out.append((st.pc, "warning", "masked menu with per-option targets: with a mask "
                        "the game jumps to target[visible row], not target[option] (reg0 = the "
                        "original option index). Point every option at one label and "
                        "SWITCH on reg0 (the shipped idiom)"))
    return out + choice_empty_mask_problems(buf, stmts, joins)


EMPTY_MASK_FIX = ("Put BR_Z (reg0) -> <where to go instead> right before the menu (after the "
                  "last SetChoiceVisibleBit reg0 is 1 when some option is shown, 0 when none "
                  "is), or make one option always shown.")


def choice_empty_mask_problems(buf, stmts, joins=None):
    """Masked menus whose mask can end up EMPTY: [(pc, 'warning', message)].

    An empty mask is the same as no mask (Script_VMStep's option loop queues every row while
    the 128-bit mask at scene+244 is zero), so the hidden options all show; the pick then
    finds no set bit in SceneEvent_FinalizeAndPickFromBitmap (RF4S.exe+0x1F49C0) and reg0 is
    not written -- it keeps the 0 the last SetChoiceVisibleBit (RF4S.exe+0x21C5C0: reg0 =
    'any bit set') left, so a SWITCH (reg0) after the menu takes the first option's branch
    whatever the player picked. Flagged: every option's bit is set from a run-time condition
    or provably cleared, and none is provably set. Menus whose bits come from a helper or an
    earlier path, or that a branch separates from the visibility ops (the BR_Z (reg0) guard),
    are not judged."""
    out = []
    if joins is None:
        joins = set()
        for s0 in stmts:
            joins.update(t for t in s0.code_targets if t is not None)
    for idx, st in enumerate(stmts):
        if st.mnem not in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED") or not st.items:
            continue
        detail = {}
        known, touched = _static_choice_mask(buf, stmts, idx, joins, detail)
        if not touched or detail["opaque"] or any(v == 1 for v in known.values()):
            continue
        opts = range(min(len(st.items), MAX_CHOICE_OPTIONS))
        dyn = [b for b in opts if b in detail["dynamic"]]
        if not all(b in detail["dynamic"] or known.get(b) == 0 for b in opts):
            continue
        if dyn:
            what = ("every option's visibility depends on a condition (option%s %s), so all "
                    "of them can be hidden at once" % ("" if len(dyn) == 1 else "s",
                                                      ", ".join(str(b + 1) for b in dyn[:8])))
        else:
            what = "every option is hidden"
        out.append((st.pc, "warning", "%s. The game then shows EVERY option and does not "
                    "store the pick in reg0 (it stays 0), so a SWITCH (reg0) after the menu "
                    "takes the first option's branch whatever the player picks. %s"
                    % (what[:1].upper() + what[1:], EMPTY_MASK_FIX)))
    return out


def dump_text(container, dialog=None, banks=None, friendly=True):
    """Full disassembly listing for the given banks (default: all).
    Action opcodes use their opcode_table.json names; `friendly=False` shows the
    technical (exe handler) names instead."""
    out = []
    sel = container.banks if banks is None else [container.banks[i] for i in banks]
    for bk in sel:
        scenes = disassemble_bank(bk)
        if not scenes:
            continue
        out.append("\n;========== bank %d (%s) %d scenes ==========" %
                   (bk.index, bk.kind, len(scenes)))
        for sc in scenes:
            out.append(format_scene(sc, dialog=dialog, buf=bk.data, friendly=friendly))
    return "\n".join(out)


def coverage(container):
    """Return (scenes, clean, statements, dialog_lines) over the whole container.
    Uses the type-table registry only (stable, fast metric); the GUI/search use the
    discovery pass on top of this."""
    scenes = clean = stmts = dlg = 0
    for _, sc in iter_scenes(container, discover=False):
        scenes += 1
        stmts += len(sc.stmts)
        dlg += sum(1 for s in sc.stmts.values() if s.mnem == "DIALOG")
        if sc.ok:
            clean += 1
    return scenes, clean, stmts, dlg


# ---- EMF (em.bin) entry-name annotation ---------------------------------------------
# Script VM ops that take an Event Manager entry id (see emscript.py):
#   371 EvalCondScriptA / 372 EvalCondScriptB   -> bool in the VM query register
#   373 DispatchCondScriptEntry                 -> run entry's MAIN action stream
#   374 CondScriptDispatchAltActionByEntryId    -> run entry's ALT action stream
#   444 SetGameFlagBitGatedByCondScript         -> args (flag_id, entry_id)
EMF_ENTRY_OPS = {371: 0, 372: 0, 373: 0, 374: 0, 444: 1}   # op -> arg index of entry id

_emf_names = None


def emf_entry_name(idx):
    """Entry name from emdeb.bin (lazy; None when the bundle isn't available)."""
    global _emf_names
    if _emf_names is None:
        try:
            from . import emscript
            _emf_names = emscript.EmNames.load()
        except Exception:
            _emf_names = False
    if not _emf_names:
        return None
    return _emf_names.entry_name(idx)


def format_scene(scene, dialog=None, show_addr=True, buf=None, friendly=True):
    """Render a Scene as text. `dialog` = optional callable(line_id) -> str.
    Action opcodes use their opcode_table.json names (opcode_mnemonic); `friendly=False`
    shows the technical (exe handler) name instead."""
    lines = []
    typ = "discovered" if scene.action_type < 0 else "type %d" % scene.action_type
    hdr = "; bank %d (%s) %s  entry @0x%04x  %d stmts" % (
        scene.bank_index, scene.kind, typ, scene.entry_pc, len(scene.stmts))
    if not scene.ok:
        hdr += "  [PARTIAL: %s]" % scene.error
    lines.append(hdr)
    labels = scene_labels(scene)

    def tgt(t):
        return labels.get(t, "0x%04x" % t) if t is not None else "?"

    for pc, st in scene.stmts.items():
        # label column is 7 wide: "L1234:" (up to 4-digit labels) + 1 separator space,
        # so the label can never run into the address.
        lbl = (labels[pc] + ":") if pc in labels else ""
        addr = "%-7s%04x: " % (lbl, pc) if show_addr else "%-7s" % lbl
        if st.mnem == "DIALOG":
            txt = ""
            if dialog is not None:
                try:
                    s = dialog(st.dialog_id)
                    if s:
                        txt = "  \"%s\"" % s.replace("\n", "\\n")
                except Exception:
                    pass
            lines.append("%s   DIALOG #%d%s" % (addr, st.dialog_id, txt))
        elif st.op < 0xFFF0:
            arg_strs = (stmt_arg_strs(buf, st) if buf is not None
                        else [str(x) for x in st.args])
            name = opcode_mnemonic(st.op) if friendly else st.mnem
            # SetSpeaker ops carry their speaker name in the mnemonic and their
            # side + face mood + emote mood are prepended by render_action -- no
            # trailing ';left'/';right' note is needed.
            note = ""
            if st.op in EMF_ENTRY_OPS and buf is not None:
                ai = EMF_ENTRY_OPS[st.op]
                if ai < len(st.args):
                    try:
                        nm = emf_entry_name(int(arg_repr(buf, st.args[ai])))
                        if nm:
                            note += "   ; %s" % nm
                    except (ValueError, TypeError):
                        pass
            # value-decoded display (e.g. GetPlayerVariable(Skill, Mining)); values need buf
            special = render_action(st.op, arg_strs) if (friendly and buf is not None) else None
            body = special if special else "%s(%s)" % (name, ", ".join(arg_strs))
            lines.append("%s   %s%s" % (addr, body, note))
        else:
            parts = []
            if st.mnem == "FRAME" and st.items:          # direct local-slot count
                parts.append(str(st.items[0]))
            if st.expr_refs and buf is not None:         # EVAL / BR_Z / BR_NZ / RET_NZ ...
                parts.append("(%s)" % ", ".join(arg_repr(buf, r) for r in st.expr_refs if r is not None))
            if st.code_targets:
                parts.append("-> " + ", ".join(tgt(t) for t in st.code_targets))
            lines.append("%s   %s %s" % (addr, st.mnem, " ".join(parts)))
    return "\n".join(lines)
