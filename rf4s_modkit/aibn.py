r"""
aibn.py -- RF4S `AIBN` monster/NPC behaviour-script disassemble + assemble.

The `AI_*.bin` files are behaviour programs run by the monster-script VM
(MonsterScript_StepCommandList / RunnerTick) which dispatches each opcode through
g_monsterScriptOpcodeTable (RF4S.exe+0x4D9A00). All opcodes 0x00-0x92 are named in
the IDB; the mnemonics below are the IDB names as re-read on 2026-09-17 (every handler
verified from pseudocode: 0x14 backs away, 0x16 blink-teleports, 0x1E sidesteps, 0x2D waits,
0x93/0x94 are the OR/AND connectors of condition chains). Operand meanings, units and the
scripted-action table live in aibn_meta.py / aibn_meta.json. See docs/10-monster-ai-vm.md.

Container:
    +0x00  "AIBN"          (0x4E424941 LE)
    +0x04  u32 file size    (== filesize on every shipped file)
    +0x08  u32[] token stream

Token rule (validated: walks all 242 files, 0 boundary violations):
    A token is an OPCODE iff (tok & 0x80000000) and (tok & 0x7FFFFFFF) <= 0x94.
      ids 0x00..0x92 dispatched; 0x93 OR / 0x94 AND connectors are consumed by the
      condition-chain stepper and never dispatched.
    Every other token is an OPERAND:
      0x95/0x96/0x97 -> comparators == <= >= ; 0xFFFFxxxx -> negative literal;
      0xFFFFFFFF -> sentinel; 10000..10009 -> registers r0..r9.

Each opcode consumes a fixed number of operand tokens (ARITY), except movement /
action opcodes (VAR_OPS) which read up to N operands and stop at the next opcode --
mirroring the handlers (shipped files always supply the full N).

Two text forms, both byte-exact round-trips of the token stream:

  * **pretty** (default) -- reads like a small language. Verified structure of every
    shipped script makes it lossless:

        sub 100:                       0x07 100  (subroutine entry; `call 100` targets it)
        290:                           0x05 290  (label; `goto 290` targets it)
        on_tick:                       0x09      (per-tick pre-emption section)
        loop {  ...  }                 0x10 ... 0x11
        if (A <= 5 && B(1) || C) {     0x0C cond [0x94 cond]* [0x93 cond]*
        } else if (D) {                0x0F cond...
        } else {                       0x0D
        }                              0x0E
        end / return / restart / yield 0x12 / 0x08 / 0x0A / 0x03
        goto N / call N                0x04 N / 0x06 N
        WaitFrames(8)                  0x01 0x41 8   -- an action opcode (0x13..0x47) is always
                                                     preceded by 0x01 "begin action"; the call
                                                     form implies it, `!WaitFrames(8)` omits it,
                                                     a bare `begin` line is a lone 0x01
        SetCooldownTimerA(180)         0x59 180      -- 0x48..0x5C never carry the 0x01
        r1 += 5 / r2 = 3 / r1 <= 4     0x49 5 / 0x52 3 / 0x6B <= 4
        . 123                          orphan operand token
    Conditions drop their `If` prefix (and a trailing `Cmp` when they take a comparator):
    `DistanceToTarget <= 110`, `RandomChance(50)`, `ActorIsNpcKind`. A comparator slot that
    holds a non-comparator token (always-true) prints as `cmp.always`.

  * **flat** -- one `OpName [operands]` line per statement, every structural token explicit
    (`BlockOpen`, `RuleSeparator`, `LabelMarker.0x7 100`, ...). `assemble()` accepts both
    forms (and the pre-2026-09-17 mnemonics via ALIASES), strips `# ...` comments, and
    ignores indentation.
"""
from __future__ import annotations

import pathlib
import re
import struct
from collections import Counter

MAGIC = b"AIBN"
HI = 0x80000000
MASK = 0x7FFFFFFF
SENTINEL = 0xFFFFFFFF
MAX_OPCODE = 0x94
REG_BASE = 10000
REG_COUNT = 10

OPCODES = {
    0x00: 'StatementBlock', 0x01: 'RuleSeparator', 0x02: 'BlockStopOnTrue',
    0x03: 'YieldFrame', 0x04: 'Goto', 0x05: 'LabelMarker', 0x06: 'CallSubroutine',
    0x07: 'LabelMarker', 0x08: 'Return', 0x09: 'LoopStartMarker',
    0x0A: 'ResetToScriptStart', 0x0B: 'RestoreCheckpointIfGrabbed', 0x0C: 'BlockOpen',
    0x0D: 'ElseAdvance', 0x0E: 'BlockClose', 0x0F: 'ElseBlock', 0x10: 'LoopStartMarker',
    0x11: 'LoopEnd', 0x12: 'OnScriptEnd', 0x13: 'ChaseTarget', 0x14: 'BackAwayFromTarget',
    0x15: 'RandomWalkInRoom', 0x16: 'BlinkTeleportNearTarget', 0x17: 'StrafeOrbitAroundLeader',
    0x18: 'MoveToLeader', 0x19: 'KiteAwayFromLeaderFacing', 0x1A: 'WalkAtAngleOffsetFromTarget',
    0x1B: 'WalkInRandomBiasedDirection', 0x1C: 'StrafeLeftOrRightOfLeader',
    0x1D: 'ThrustInFacingDir', 0x1E: 'SidestepAroundTarget', 0x1F: 'AmbushPlayerNearWall',
    0x20: 'AmbushLeaderNearWall', 0x21: 'ChaseCombatTarget',
    0x22: 'TurnToFaceCombatTargetSmoothly', 0x23: 'MoveToOffsetPastCombatTarget',
    0x24: 'MoveToMapRelativeTile', 0x25: 'AcquireTargetInFovAndApproach',
    0x26: 'InvokeScriptedAction', 0x27: 'TurnToFaceTarget', 0x28: 'TurnToFaceLeaderWithDuration',
    0x29: 'SpinByRelativeAngle', 0x2A: 'TurnByRandomOffset', 0x2B: 'TurnToAbsoluteAngle',
    0x2C: 'BeginActionWait', 0x2D: 'BeginAttackWithSkillWait', 0x2E: 'SnapFaceAndBeginAction',
    0x2F: 'SnapFaceLeader3OpAndBeginAction', 0x30: 'SnapFaceWithSpreadAndBeginAction',
    0x31: 'SnapFaceWithSpread3OpAndAction', 0x32: 'BeginActionSyncedWithTarget',
    0x33: 'UserMathErrorFunction', 0x34: 'BeginSkillEffectAnimWait', 0x35: 'WaitUntilTargetDistanceGe',
    0x36: 'AttachHeldItemByCategory', 0x37: 'UseOrReleaseHeldItem', 0x38: 'YieldOneFrame',
    0x39: 'SetActorFlag800000', 0x3A: 'SetActorTurningFlag', 0x3B: 'SetWidgetFloatParam384',
    0x3C: 'SetVelocityFromFacing', 0x3D: 'SetVelocityStrafe', 0x3E: 'SetRunSpeedScaleQ12',
    0x3F: 'SetRunAccelScaleQ12', 0x40: 'SetScriptedTargetTile', 0x41: 'WaitFrames',
    0x42: 'SpawnDoppelgangerIfWild', 0x43: 'PlayAnimThenRestoreIdle', 0x44: 'PlaySfxAtActorPos',
    0x45: 'PlaySfxGlobal', 0x46: 'ClearCtxBit5', 0x47: 'ScriptResetState',
    0x48: 'RegAddImm', 0x49: 'RegAddImm', 0x4A: 'RegAddImm', 0x4B: 'RegAddImm',
    0x4C: 'RegAddImm', 0x4D: 'RegAddImm', 0x4E: 'RegAddImm', 0x4F: 'RegAddImm',
    0x50: 'RegSetImm', 0x51: 'RegSetImm', 0x52: 'RegSetImm', 0x53: 'RegSetImm',
    0x54: 'RegSetImm', 0x55: 'RegSetImm', 0x56: 'RegSetImm', 0x57: 'RegSetImm',
    0x58: 'SetTickCounter', 0x59: 'SetCooldownTimerA', 0x5A: 'SetCooldownTimerB',
    0x5B: 'SetCooldownTimerC', 0x5C: 'TriggerKnockdown', 0x5D: 'IfDistanceToTarget',
    0x5E: 'IfDistanceToCombatTarget', 0x5F: 'IfRandomChance', 0x60: 'IfActorHpPercent',
    0x61: 'IfTargetHpPercent', 0x62: 'IfRuleCounterGe', 0x63: 'IfCtxBit5',
    0x64: 'IfTickCounterCmp', 0x65: 'IfCooldownTimerACmp', 0x66: 'IfCooldownTimerBCmp',
    0x67: 'IfCooldownTimerCCmp', 0x68: 'IfAnimWidgetFlag8', 0x69: 'IfBusyRecoveredOrCollFlag800',
    0x6A: 'IfRegCmpImm', 0x6B: 'IfRegCmpImm', 0x6C: 'IfRegCmpImm', 0x6D: 'IfRegCmpImm',
    0x6E: 'IfRegCmpImm', 0x6F: 'IfRegCmpImm', 0x70: 'IfRegCmpImm', 0x71: 'IfRegCmpImm',
    0x72: 'IfCtxBit13ConsumeAndAck', 0x73: 'IfActionInProgressCmp', 0x74: 'IfActorIsNpcKind',
    0x75: 'IfHasLeaderTarget', 0x76: 'IfLeaderBusy', 0x77: 'IfHasCombatTarget',
    0x78: 'IfCombatTargetBusy', 0x79: 'IfCombatTargetHasItem', 0x7A: 'IfActorTaskFlag4000',
    0x7B: 'IfAnimFrameCmp', 0x7C: 'IfLeaderActionInRange9to12', 0x7D: 'IfWarpAnimInProgress',
    0x7E: 'IfTileBlockedAndNotRuleEntered', 0x7F: 'IfActorCurrentActionLe2', 0x80: 'IfScriptLocked',
    0x81: 'IfCheatModeActiveForMonster', 0x82: 'IfActorTaskFlag400', 0x83: 'IfFlgRainbow',
    0x84: 'AlwaysTrue', 0x85: 'IfControlledPlayerActive', 0x86: 'IfActorOrTargetControlFlag4',
    0x87: 'IfActorOrTargetControlFlag2', 0x88: 'IfHeldItemKindSet', 0x89: 'IfTargetValidAndReady',
    0x8A: 'IfStoryProgressLe76', 0x8B: 'IfHeldItemCategory', 0x8C: 'IfRegWifeIdCmp',
    0x8D: 'IfActorLevelCmp', 0x8E: 'IfKillAggregateCmp', 0x8F: 'IfActorCurrentActionCmp',
    0x90: 'IfEntityField338Cmp', 0x91: 'IfEntityField340Cmp', 0x92: 'IfEntityField342Cmp',
    0x93: 'OrConnector', 0x94: 'AndConnector',
}
# Mnemonics used by disassemblies written before the 2026-09-17 handler re-read. The assembler
# still accepts them (they map to the same opcode ids); new disassemblies use the names above.
ALIASES = {
    'TickAI': 0x14, 'Wander': 0x16, 'MoveToTargetPosition': 0x1E, 'StartActionImmediately': 0x2D,
    'BeginActionVariant': 0x34, 'PlayDialogActionWithNpcKind': 0x37, 'SetCtxField66': 0x3E,
    'SetCtxField68': 0x3F, 'SetCombatParam': 0x42, 'BeginActionThenTeleport': 0x43,
    'SetCtxField98': 0x58, 'SetActorField490': 0x59, 'SetActorField492': 0x5A,
    'SetActorField494': 0x5B, 'IfCtxField98Cmp': 0x64, 'IfActorField490Cmp': 0x65,
    'IfActorField492Cmp': 0x66, 'IfActorField494Cmp': 0x67, 'IfCtxBit6OrActorSub232Flag800': 0x69,
    'IfCurrentActionCmpOrGrabbed': 0x73, 'IfWidgetFloat392Cmp': 0x7B, 'IfActorControlFlag80000': 0x7D,
    'IfGameFlag45B': 0x83, 'IfEntityField178NotZero': 0x88, 'StepOneTokenAndCheckEnd': 0x8A,
    'IfGameFlagC6Cmp': 0x8C, 'IfMyNpcIdWithAgeShift': 0x8D, 'SkipToActions': 0x93, 'Connector': 0x94,
}
CMP = {0x95: '==', 0x96: '<=', 0x97: '>='}
CMP_REV = {'==': 0x95, '<=': 0x96, '>=': 0x97}

# Variable-arity handlers (verified 2026-09-17): they read up to N operand tokens and stop at the
# first opcode token; shipped files always supply the full N. 0x15 reads exactly 3 (fixed).
VAR_OPS = {
    0x13, 0x14, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x21,
    0x22, 0x23, 0x24, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x30,
    0x31, 0x32, 0x34, 0x35, 0x36, 0x39, 0x3A, 0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x43,
    0x44, 0x45,
}
ARITY = {
    0x04: 1, 0x05: 1, 0x06: 1, 0x07: 1, 0x15: 3, 0x16: 2,
    0x41: 1, 0x42: 1, 0x58: 1, 0x59: 1, 0x5A: 1, 0x5B: 1, 0x5C: 1,
    0x5D: 2, 0x5E: 2, 0x5F: 1, 0x60: 2, 0x61: 2, 0x62: 1, 0x63: 1,
    0x64: 2, 0x65: 2, 0x66: 2, 0x67: 2, 0x72: 1, 0x73: 2, 0x75: 1,
    0x77: 1, 0x7B: 2, 0x80: 1, 0x81: 1,
    0x8B: 2, 0x8C: 2, 0x8D: 2, 0x8E: 2, 0x8F: 2, 0x90: 2, 0x91: 2, 0x92: 2,
}
ARITY.update({o: 1 for o in range(0x48, 0x58)})
ARITY.update({o: 2 for o in range(0x6A, 0x72)})

OPEN_OPS = {0x0C, 0x10}
CLOSE_OPS = {0x0E, 0x11}
ELSE_OPS = {0x0F, 0x0D}
CONNECTORS = {0x93, 0x94}
COND_OPS = set(range(0x5D, 0x93))
# condition opcodes whose first operand is a comparator token (verified operand records)
CMP_COND_OPS = {0x5D, 0x5E, 0x60, 0x61, 0x64, 0x65, 0x66, 0x67, 0x73, 0x7B,
                0x8B, 0x8C, 0x8D, 0x8E, 0x8F, 0x90, 0x91, 0x92} | set(range(0x6A, 0x72))
# opcodes that every shipped script precedes with 0x01 "begin action" (census over all 242
# files: 12993 of 12993 markers sit directly before one of these; 0x48..0x5C never carry one)
ACTION_OPS = set(range(0x13, 0x48))
REG_ADD, REG_SET, REG_CMP = 0x48, 0x50, 0x6A

# Name -> first opcode id (for the assembler; ambiguous names like RegAddImm map to
# their base id 0x48 etc.).
NAME_TO_OP = {}
for _id, _nm in OPCODES.items():
    NAME_TO_OP.setdefault(_nm, _id)
for _nm, _id in ALIASES.items():
    NAME_TO_OP.setdefault(_nm, _id)


def _cond_name(opid: int) -> str:
    """Expression name of a condition opcode: `If` prefix dropped, trailing `Cmp` dropped for
    comparator conditions, registers as rN."""
    if REG_CMP <= opid < REG_CMP + 8:
        return f"r{opid - REG_CMP}"
    name = OPCODES[opid]
    if name.startswith("If"):
        name = name[2:]
    if opid in CMP_COND_OPS and name.endswith("Cmp"):
        name = name[:-3]
    return name


COND_NAME = {op: _cond_name(op) for op in COND_OPS}
COND_NAME_TO_OP = {}
for _op, _nm in COND_NAME.items():
    if not _nm.startswith("r"):
        assert _nm not in COND_NAME_TO_OP, _nm
        COND_NAME_TO_OP[_nm] = _op


class AibnError(Exception):
    pass


def is_opcode(tok: int) -> bool:
    return bool(tok & HI) and (tok & MASK) <= MAX_OPCODE and tok != SENTINEL


def opname(opid: int) -> str:
    return OPCODES.get(opid, f"OP_{opid:02X}")


# --------------------------------------------------------------------------- #
# Token-level I/O (byte-exact round-trip primitive)
# --------------------------------------------------------------------------- #
def load_tokens(data: bytes) -> list[int]:
    if data[:4] != MAGIC:
        raise AibnError(f"bad magic {data[:4]!r}")
    body = data[8:]
    body = body[: len(body) - (len(body) % 4)]
    return list(struct.unpack(f"<{len(body)//4}I", body))


def build(tokens: list[int]) -> bytes:
    """Serialise a token list to a valid AIBN file (recomputes the size word)."""
    body = struct.pack(f"<{len(tokens)}I", *[t & 0xFFFFFFFF for t in tokens])
    size = 8 + len(body)
    return MAGIC + struct.pack("<I", size) + body


# --------------------------------------------------------------------------- #
# Disassembly
# --------------------------------------------------------------------------- #
def fmt_operand(tok: int) -> str:
    if tok == SENTINEL:
        return "NULL"
    if tok & HI:
        idv = tok & MASK
        if idv in CMP:
            return CMP[idv]
        if idv in (0x93, 0x94):
            return "cmp.always"
        return str(tok - 0x100000000)
    if REG_BASE <= tok < REG_BASE + REG_COUNT:
        return f"r{tok - REG_BASE}"
    return str(tok)


def walk_statements(tokens: list[int]):
    """Yield (index, opcode_id|None, [operand_tokens]) per statement."""
    i, n = 0, len(tokens)
    while i < n:
        tok = tokens[i]
        if not is_opcode(tok):
            yield i, None, [tok]
            i += 1
            continue
        opid = tok & MASK
        if opid in CONNECTORS:
            yield i, opid, []
            i += 1
        elif opid in VAR_OPS:
            j = i + 1
            while j < n and not is_opcode(tokens[j]):
                j += 1
            yield i, opid, tokens[i + 1:j]
            i = j
        else:
            ar = ARITY.get(opid, 0)
            yield i, opid, tokens[i + 1:i + 1 + ar]
            i += 1 + ar


def _op_label(opid: int) -> str:
    """Flat-style opcode mnemonic. Ambiguous names (e.g. RegAddImm 0x48..0x4F) get a `.0xNN`
    suffix so the exact id -- which selects the register/variant -- round-trips."""
    name = OPCODES.get(opid)
    if name is None:
        return f"OP_{opid:02X}"
    if NAME_TO_OP.get(name) != opid:
        return f"{name}.{opid:#x}"
    return name


def _operand_values(ops: list[int]) -> list:
    """Operand tokens as annotation-friendly values: signed ints, 'rN' for registers, None for
    comparator / sentinel tokens."""
    out = []
    for tok in ops:
        if tok == SENTINEL or (tok & HI):
            out.append(None)
        elif REG_BASE <= tok < REG_BASE + REG_COUNT:
            out.append(f"r{tok - REG_BASE}")
        else:
            out.append(tok if tok < 0x80000000 else tok - 0x100000000)
    return out


def _flat_line(opid: int, ops: list[int]) -> str:
    line = _op_label(opid)
    if ops:
        line += " " + " ".join(fmt_operand(o) for o in ops)
    return line


def _cond_text(opid: int, ops: list[int]) -> str:
    """One condition as an expression: `Name <cmp> value`, `Name(args)` or `Name`."""
    name = COND_NAME.get(opid) or opname(opid)
    rendered = [fmt_operand(o) for o in ops]
    if opid in CMP_COND_OPS and ops and (ops[0] & HI) and ((ops[0] & MASK) in CMP or (ops[0] & MASK) in CONNECTORS):
        return name + " " + " ".join(rendered)
    if not ops:
        return name
    return name + "(" + ", ".join(rendered) + ")"


def _call_text(opid: int, ops: list[int]) -> str:
    name = OPCODES.get(opid)
    if name is None:
        return _flat_line(opid, ops)
    return name + "(" + ", ".join(fmt_operand(o) for o in ops) + ")"


def _annotation(meta, opid: int, ops: list[int]) -> str:
    if meta is None or opid < 0x13 or (REG_ADD <= opid < 0x58) or (REG_CMP <= opid < REG_CMP + 8):
        return ""
    return meta.annotate(opid, _operand_values(ops), [fmt_operand(o) for o in ops])


def _collect_chain(sts, k):
    """Condition chain starting at statement k: [(connector_op|None, opid, ops)], next index."""
    chain = []
    if k < len(sts) and sts[k][1] in COND_OPS:
        chain.append((None, sts[k][1], sts[k][2]))
        k += 1
        while k + 1 < len(sts) and sts[k][1] in CONNECTORS and sts[k + 1][1] in COND_OPS:
            chain.append((sts[k][1], sts[k + 1][1], sts[k + 1][2]))
            k += 2
    return chain, k


def _chain_text(chain) -> str:
    parts = []
    for conn, opid, ops in chain:
        if conn is not None:
            parts.append("&&" if conn == 0x94 else "||")
        parts.append(_cond_text(opid, ops))
    return " ".join(parts)


def disassemble_flat(tokens: list[int], annotate: bool = False) -> str:
    """One `OpName [operands]` line per statement, indented by block depth."""
    meta = None
    if annotate:
        from . import aibn_meta as meta
    lines = []
    indent = 0
    for idx, opid, ops in walk_statements(tokens):
        if opid is None:
            lines.append(f"{'  ' * indent}. {fmt_operand(ops[0])}")
            continue
        this_indent = max(0, indent - 1) if (opid in CLOSE_OPS or opid in ELSE_OPS) else indent
        line = "  " * this_indent + _flat_line(opid, ops)
        note = _annotation(meta, opid, ops)
        if note:
            line = f"{line:<44s}  # {note}"
        lines.append(line)
        if opid in OPEN_OPS:
            indent += 1
        elif opid in CLOSE_OPS:
            indent = max(0, indent - 1)
    return "\n".join(lines)


def disassemble_pretty(tokens: list[int], annotate: bool = False) -> str:
    """Language-style listing (see the module docstring); `assemble()` reverses it exactly."""
    meta = None
    if annotate:
        from . import aibn_meta as meta
    sts = list(walk_statements(tokens))
    lines = []
    stack: list[str] = []
    indent = 0

    def emit(text: str, level: int, note: str = ""):
        line = "    " * max(0, level) + text
        if note:
            line = f"{line:<48s}  # {note}"
        lines.append(line)

    i = 0
    while i < len(sts):
        idx, opid, ops = sts[i]
        if opid is None:
            emit(f". {fmt_operand(ops[0])}", indent)
            i += 1
            continue
        if opid == 0x0C:
            chain, j = _collect_chain(sts, i + 1)
            note = " | ".join(n for n in (_annotation(meta, c[1], c[2]) for c in chain) if n)
            emit(f"if ({_chain_text(chain)}) {{", indent, note)
            stack.append("if")
            indent += 1
            i = j
            continue
        if opid == 0x0F:
            chain, j = _collect_chain(sts, i + 1)
            note = " | ".join(n for n in (_annotation(meta, c[1], c[2]) for c in chain) if n)
            if stack and stack[-1] == "if":
                emit(f"}} else if ({_chain_text(chain)}) {{", indent - 1, note)
            else:                                   # unbalanced: explicit form
                emit("ElseBlock", indent)
                for conn, cop, cops in chain:
                    if conn is not None:
                        emit("&&" if conn == 0x94 else "||", indent)
                    emit(_cond_text(cop, cops), indent)
            i = j
            continue
        if opid == 0x0D:
            if stack and stack[-1] == "if":
                emit("} else {", indent - 1)
            else:
                emit("ElseAdvance", indent)
        elif opid == 0x0E:
            if stack and stack[-1] == "if":
                stack.pop()
                indent -= 1
                emit("}", indent)
            else:
                emit("BlockClose", indent)
        elif opid == 0x10:
            emit("loop {", indent)
            stack.append("loop")
            indent += 1
        elif opid == 0x11:
            if stack and stack[-1] == "loop":
                stack.pop()
                indent -= 1
                emit("}", indent)
            else:
                emit("LoopEnd", indent)
        elif opid == 0x07 and len(ops) == 1:
            if lines:
                lines.append("")
            emit(f"sub {fmt_operand(ops[0])}:", 0)
            indent = 1
        elif opid == 0x05 and len(ops) == 1:
            emit(f"{fmt_operand(ops[0])}:", indent)
        elif opid == 0x09:
            if lines:
                lines.append("")
            emit("on_tick:", 0)
            indent = 1
        elif opid == 0x12:
            emit("end", indent)
        elif opid == 0x08:
            emit("return", indent)
        elif opid == 0x0A:
            emit("restart", indent)
        elif opid == 0x03:
            emit("yield", indent)
        elif opid == 0x04 and len(ops) == 1:
            emit(f"goto {fmt_operand(ops[0])}", indent)
        elif opid == 0x06 and len(ops) == 1:
            emit(f"call {fmt_operand(ops[0])}", indent)
        elif opid == 0x01:
            nxt = sts[i + 1] if i + 1 < len(sts) else None
            if nxt is not None and nxt[1] in ACTION_OPS:
                emit(_call_text(nxt[1], nxt[2]), indent, _annotation(meta, nxt[1], nxt[2]))
                i += 2
                continue
            emit("begin", indent)
        elif opid in ACTION_OPS:
            emit("!" + _call_text(opid, ops), indent, _annotation(meta, opid, ops))
        elif REG_ADD <= opid < REG_ADD + 8 and len(ops) == 1:
            emit(f"r{opid - REG_ADD} += {fmt_operand(ops[0])}", indent)
        elif REG_SET <= opid < REG_SET + 8 and len(ops) == 1:
            emit(f"r{opid - REG_SET} = {fmt_operand(ops[0])}", indent)
        elif 0x58 <= opid <= 0x5C:
            emit(_call_text(opid, ops), indent, _annotation(meta, opid, ops))
        elif opid in COND_OPS:
            emit(_cond_text(opid, ops), indent, _annotation(meta, opid, ops))
        elif opid in CONNECTORS:
            emit("&&" if opid == 0x94 else "||", indent)
        else:
            emit(_flat_line(opid, ops), indent)
        i += 1
    return "\n".join(lines)


def disassemble(tokens: list[int], annotate: bool = False, style: str = "pretty") -> str:
    """Textual disassembly. ``style`` = "pretty" (default, language-like) or "flat" (one opcode
    per line). With ``annotate`` every statement gets a trailing ``# label = value unit`` comment
    from the verified opcode metadata (``aibn_meta``); ``assemble`` strips those comments."""
    if style == "flat":
        return disassemble_flat(tokens, annotate)
    return disassemble_pretty(tokens, annotate)


# --------------------------------------------------------------------------- #
# Assembly (text -> tokens). Accepts the pretty and the flat form.
# --------------------------------------------------------------------------- #
def _parse_operand(tok_str: str) -> int:
    s = tok_str.strip()
    if s == "NULL":
        return SENTINEL
    if s in CMP_REV:
        return HI | CMP_REV[s]     # comparators carry the high bit (0x80000095..97)
    if s == "cmp.always":
        return HI | 0x93
    if s.startswith("r") and s[1:].isdigit() and int(s[1:]) < REG_COUNT:
        return REG_BASE + int(s[1:])
    val = int(s, 0)
    if val < 0:
        return val & 0xFFFFFFFF
    return val


def _name_to_op(name: str) -> int:
    if "." in name and name.rsplit(".", 1)[1].lower().startswith("0x"):
        return int(name.rsplit(".", 1)[1], 16)      # disambiguated form, e.g. RegAddImm.0x49
    if name in NAME_TO_OP:
        return NAME_TO_OP[name]
    if name in COND_NAME_TO_OP:
        return COND_NAME_TO_OP[name]
    if name.startswith("OP_"):
        return int(name[3:], 16)
    raise AibnError(f"unknown opcode name {name!r}")


_RE_CALL = re.compile(r"^(!?)([A-Za-z_][A-Za-z0-9_.]*)\((.*)\)$")
_RE_REGSET = re.compile(r"^r(\d)\s*(\+=|=)\s*(\S+)$")
_RE_CMP = re.compile(r"^(r\d|[A-Za-z_][A-Za-z0-9_.]*)\s+(==|<=|>=|cmp\.always)(?:\s+(.*))?$")
_RE_LABEL = re.compile(r"^(-?\d+):$")
_RE_SUB = re.compile(r"^sub\s+(-?\d+):$")
_RE_IF = re.compile(r"^if\s*\((.*)\)\s*\{$")
_RE_ELIF = re.compile(r"^\}\s*else\s+if\s*\((.*)\)\s*\{$")
_RE_GOTO = re.compile(r"^(goto|call)\s+(\S+)$")


def _split_args(s: str) -> list[str]:
    s = s.strip()
    return [a.strip() for a in s.split(",")] if s else []


def _parse_cond(elem: str) -> list[int]:
    """One condition expression -> tokens."""
    elem = elem.strip()
    m = _RE_CMP.match(elem)
    if m and not elem.endswith(")"):
        name, cmp_s, rest = m.group(1), m.group(2), m.group(3)
        if re.fullmatch(r"r\d", name):
            opid = REG_CMP + int(name[1:])
        else:
            opid = _name_to_op(name)
        toks = [HI | opid, _parse_operand(cmp_s)]
        if rest:
            toks += [_parse_operand(p) for p in rest.split()]
        return toks
    m = _RE_CALL.match(elem)
    if m:
        opid = _name_to_op(m.group(2))
        return [HI | opid] + [_parse_operand(a) for a in _split_args(m.group(3))]
    parts = elem.split()
    opid = _name_to_op(parts[0])
    return [HI | opid] + [_parse_operand(p) for p in parts[1:]]


def _parse_chain(text: str) -> list[int]:
    """`c1 && c2 || c3` -> condition tokens with 0x94/0x93 connector tokens between them."""
    toks: list[int] = []
    for piece in re.split(r"\s+(&&|\|\|)\s+", text.strip()):
        if piece == "&&":
            toks.append(HI | 0x94)
        elif piece == "||":
            toks.append(HI | 0x93)
        elif piece.strip():
            toks += _parse_cond(piece)
    return toks


def assemble(text: str) -> list[int]:
    """
    Re-assemble a disassembly (pretty or flat form, as produced by disassemble()) into tokens.
    Indentation and `# comments` are ignored.
    """
    tokens: list[int] = []
    stack: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        for sep in (" #", "\t#"):          # trailing annotation comments
            cut = line.find(sep)
            if cut >= 0:
                line = line[:cut].rstrip()
        if not line:
            continue
        if line.startswith("."):
            tokens.append(_parse_operand(line[1:].strip()))
            continue
        # ---- pretty form ----
        m = _RE_SUB.match(line)
        if m:
            tokens += [HI | 0x07, _parse_operand(m.group(1))]
            continue
        m = _RE_LABEL.match(line)
        if m:
            tokens += [HI | 0x05, _parse_operand(m.group(1))]
            continue
        if line == "on_tick:":
            tokens.append(HI | 0x09)
            continue
        if line == "loop {":
            tokens.append(HI | 0x10)
            stack.append("loop")
            continue
        m = _RE_IF.match(line)
        if m:
            tokens.append(HI | 0x0C)
            tokens += _parse_chain(m.group(1))
            stack.append("if")
            continue
        m = _RE_ELIF.match(line)
        if m:
            tokens.append(HI | 0x0F)
            tokens += _parse_chain(m.group(1))
            continue
        if line == "} else {":
            tokens.append(HI | 0x0D)
            continue
        if line == "}":
            kind = stack.pop() if stack else "if"
            tokens.append(HI | (0x11 if kind == "loop" else 0x0E))
            continue
        simple = {"end": 0x12, "return": 0x08, "restart": 0x0A, "yield": 0x03, "begin": 0x01,
                  "&&": 0x94, "||": 0x93}
        if line in simple:
            tokens.append(HI | simple[line])
            continue
        m = _RE_GOTO.match(line)
        if m:
            tokens += [HI | (0x04 if m.group(1) == "goto" else 0x06), _parse_operand(m.group(2))]
            continue
        m = _RE_REGSET.match(line)
        if m:
            base = REG_ADD if m.group(2) == "+=" else REG_SET
            tokens += [HI | (base + int(m.group(1))), _parse_operand(m.group(3))]
            continue
        m = _RE_CALL.match(line)
        if m:
            bang, name, args = m.groups()
            opid = _name_to_op(name)
            if opid in ACTION_OPS and not bang:
                tokens.append(HI | 0x01)
            tokens.append(HI | opid)
            tokens += [_parse_operand(a) for a in _split_args(args)]
            continue
        m = _RE_CMP.match(line)
        if m:
            tokens += _parse_cond(line)
            continue
        # ---- flat form: `OpName [operands...]` (also bare condition names) ----
        parts = line.split()
        opid = _name_to_op(parts[0])
        tokens.append(HI | opid)
        for p in parts[1:]:
            tokens.append(_parse_operand(p))
    return tokens


def stats(tokens: list[int]) -> Counter:
    c = Counter()
    for _idx, opid, _ops in walk_statements(tokens):
        if opid is not None:
            c[opid] += 1
    return c
