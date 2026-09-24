"""rf4s_modkit/asatk.py -- decoder for the attack-move timeline files (`as_atk_*.bin`, 690 of them,
archive ids 243..932 = rom:/as/).

Each attack move (weapon combo step, charge, skill, tool swing, monster or boss attack) is a flat
stream of **(opcode:u32, operand:u32) little-endian pairs**, no header, terminated by (66, 0).
Once loaded by Actor_BeginAttackOrSkill (RF4S.exe+0x1610C0) the bytes are bound to the actor's
AnimBindCtx (Actor_BindAnimArchiveToWidget +0xAB340) and pumped once per frame by the actor
pre-tick Actor_PreTickFrameCleanupAndDecay (+0x9FC90) through g_animEventOpHandlerTable
(+0x4BB7F0, 66 slots). Op 0 blocks the pump until the animation clock reaches its frame; every
other op fires immediately and the pump continues with the next pair in the same frame; op 66
deactivates the stream. Ops 62/63 chain into another move (their optional parameter pair is
op 64, which has no handler of its own).

Opcode meanings below were verified against every handler on 2026-09-17 (all tagged V); the
older data-inferred table (HIT_WIN/VEL_FWD/EFFECT on op 45) was wrong in several places and is
gone. Full write-up: docs/28-attack-move-timelines.md.

Editing (2026-09-19): `disassemble` emits a canonical `<mnemonic> <operand>` listing that
`assemble` turns back into bytes (byte-exact for all 690 shipped files, including the two
that carry one pair after END); `set_event` / `insert_event` / `insert_at_frame` /
`delete_event` edit the Event list and `build` serialises it; `validate` reports what the
pump would trip over. The corpus has no headers or padding: every file is 8-byte pairs.

Operand kinds:
  frame   animation frame number (plain integer)
  q12     signed 20.12 fixed point (4096 = 1.0)
  angle   u16 angle, 0x10000 = full turn (printed in degrees)
  onoff   flag: 0 = off, non-zero = on
  sfx     sound id 0x0100xxxx
  effkind effect kind (-1 = the actor's own attack effect, 0 = tool/weapon-element table)
  action  action task id (Action_TriggerAttacker)
  tool    tool kind (1 hoe, 2 seed, 3 can, 4 fertilizer, 5 hand, 7 axe, 8 hammer, 9 sickle/cut)
  int     plain integer
"""
from __future__ import annotations

import struct
from collections import Counter, namedtuple

END_OP = 66
CHAIN_PARAM_OP = 64

# op -> (mnemonic, arg_kind, confidence, description)
OPCODES = {
    0:  ("FRAME",      "frame",   "V", "wait until the animation clock reaches this frame (events after it fire there)"),
    1:  ("SEEK_ANIM",  "frame",   "V", "seek the 3D model animation to this frame"),
    2:  ("ANIM_SPEED", "q12",     "V", ">0: multiply the model timescale by arg; <=0: restore it"),
    3:  ("DASH",       "q12",     "V", "velocity along facing (units/frame; negative = recoil)"),
    4:  ("STRAFE",     "q12",     "V", "velocity perpendicular to facing"),
    5:  ("MOTION_LOCK","onoff",   "V", "stats flag 0x4: no friction, movement input ignored"),
    6:  ("TURN",       "angle",   "V", "facing += arg"),
    7:  ("FACE_TARGET","int",     "V", "face the lock-on / script target"),
    8:  ("FACE_TARGET_PLUS", "angle", "V", "face the last target, then add arg"),
    9:  ("FACE_ANCHOR","int",     "V", "face the map anchor point"),
    10: ("HITBOX",     "onoff",   "V", "1 = ARM: new hit serial, AttackInfo filled from weapon+stats; 0 = disarm"),
    11: ("HIT_DIR",    "angle",   "V", "swing direction = facing + arg"),
    12: ("REACH",      "q12",     "V", "hit reach = arg x (36 x weapon reach scale, +50% Art of Attack)"),
    13: ("ARC",        "q12",     "V", "hit arc = arg x (0x4000 (90 deg) x weapon arc scale)"),
    14: ("KB_SPEED",   "q12",     "V", "knockback speed = arg x (6.0 x stats+56)"),
    15: ("KB_POWER",   "q12",     "V", "knockback strength = arg x (30 + 30 x stats+60), max 127"),
    16: ("BASE_ATK",   "q12",     "V", "base damage = arg x buffed ATK (MATK if magic)"),
    17: ("DMG_MULT",   "q12",     "V", "damage multiplier (motion value)"),
    18: ("LAUNCH_ADD", "int",     "V", "airborne launch add = -1536 x arg >> 12"),
    19: ("HUNGER",     "q12",     "V", "hunger drain = stats hunger drain x arg"),
    20: ("REACH_RAW",  "int",     "V", "hit reach = arg"),
    21: ("ARC_RAW",    "angle",   "V", "hit arc = arg (0 = full circle)"),
    22: ("KB_SPEED_X16","int",    "V", "knockback speed = arg x 16"),
    23: ("KB_POWER_RAW","int",    "V", "knockback strength = min(arg, 127)"),
    24: ("LAUNCH",     "q12",     "V", "vertical launch velocity = -arg"),
    25: ("BASE_ATK_RAW","int",    "V", "base damage = arg"),
    26: ("LAUNCH_ADD_X16","int",  "V", "airborne launch add = arg x 16"),
    27: ("HUNGER_RAW", "int",     "V", "hunger drain = arg"),
    28: ("CLEAR_ELEM", "onoff",   "V", "clear the seven element bits of the attack flags"),
    29: ("ATK_FLAGS",  "int",     "V", "attack flags |= arg (0x4000 = element of the highest elemental stat; 0x40000000 = never crit; 0x1000 = raw knockback)"),
    30: ("PROC_POISON","q12",     "V", "poison proc chance"),
    31: ("PROC_SEAL",  "q12",     "V", "seal proc chance"),
    32: ("PROC_PARA",  "q12",     "V", "paralysis proc chance"),
    33: ("PROC_SLEEP", "q12",     "V", "sleep proc chance"),
    34: ("PROC_FATIGUE","q12",    "V", "fatigue proc chance"),
    35: ("PROC_COLD",  "q12",     "V", "cold proc chance"),
    36: ("PROC_FAINT", "q12",     "V", "faint proc chance"),
    37: ("HP_DRAIN",   "q12",     "V", "HP drain chance"),
    38: ("W410_CHARGE","q12",     "V", "weapon item 410 only: reach as op 12 plus charge track"),
    39: ("COMBO_WIN",  "onoff",   "V", "player: next-action input window"),
    40: ("COMBO_WIN_ONHIT","onoff","V", "player: next-action window only if the swing connected"),
    41: ("DASH_WIN",   "onoff",   "V", "player: dash-cancel input window"),
    42: ("ACTION",     "action",  "V", "spawn action task at the actor (Action_TriggerAttacker)"),
    43: ("EFFECT",     "effkind", "V", "Effect_ApplyByKindAndSpawn: -1 own attack effect, 0 tool/weapon table, else literal kind"),
    44: ("TOOL_KIND",  "tool",    "V", "player: pending tool action for the facing tile"),
    45: ("SFX",        "sfx",     "V", "play sound at the actor"),
    46: ("FLAG_1",     "onoff",   "V", "stats flag 0x1 (active-swing marker)"),
    47: ("FLAG_40",    "onoff",   "V", "stats flag 0x40 (dual blades)"),
    48: ("SUPER_ARMOR","onoff",   "V", "stats flag 0x2: no knockback while set (also clears 0x40000)"),
    49: ("GUARD",      "onoff",   "V", "stats flag 0x8: incoming hits blocked"),
    50: ("INVULN",     "onoff",   "V", "stats flag 0x20: incoming hits miss"),
    51: ("SHAKE",      "int",     "V", "screen shake kind (-1..4)"),
    52: ("NODE_FLAG4", "onoff",   "V", "scene node flag 0x4"),
    53: ("BUSY_TIMER", "frame",   "V", "actor busy timer = max(current, arg)"),
    54: ("STUN_TIMER", "frame",   "V", "actor hit-stun timer = max(current, arg)"),
    55: ("CANCEL_WIN", "onoff",   "V", "stats flag 0x200: direction input jumps to the chain marker"),
    56: ("RAW_KB",     "onoff",   "V", "stats flag 0x400: this actor takes raw knockback"),
    57: ("ACTOR_4000", "onoff",   "V", "actor control flag 0x4000"),
    58: ("STUN_IMMUNE","onoff",   "V", "actor control flag 0x1000: hit-stun timer forced to 0"),
    59: ("ALT_REACH",  "int",     "V", "collision box override (0 = restore body radius)"),
    60: ("HASTE_TINT", "int",     "V", "flicker_b = 1200 frames (attack anims 1.25x while it runs)"),
    61: ("TINT",       "int",     "V", "flicker_a = 1800 frames"),
    62: ("CHAIN",      "int",     "V", "chain into skill arg (anim offset from a following op 64 pair, else arg)"),
    63: ("CHAIN_ONHIT","int",     "V", "as CHAIN, only if the swing connected"),
    64: ("CHAIN_ANIM", "int",     "V", "parameter pair of CHAIN: animation offset (no handler)"),
    65: ("REACH_FORCE","int",     "V", "hit reach x= force level from stagger bits (0 atk bits, 1 double hit)"),
    66: ("END",        "int",     "V", "end of stream"),
}

TOOL_KINDS = {1: "hoe", 2: "seed", 3: "can", 4: "fertilizer", 5: "hand", 7: "axe", 8: "hammer", 9: "sickle/cut"}

Event = namedtuple("Event", "index op arg")


def opname(op: int) -> str:
    if op in OPCODES:
        return OPCODES[op][0]
    return f"OP{op}"


def _s32(u: int) -> int:
    return struct.unpack("<i", struct.pack("<I", u & 0xFFFFFFFF))[0]


def fmt_arg(op: int, arg: int) -> str:
    kind = OPCODES.get(op, (None, "int"))[1]
    s = _s32(arg)
    if kind == "frame":
        return f"frame={arg}"
    if kind == "q12":
        return f"{s / 4096:.3f}"
    if kind == "angle":
        return f"{s} ({(s & 0xFFFF) * 360 / 65536:.0f} deg)"
    if kind == "sfx":
        return f"sfx=0x{arg:08X}"
    if kind == "effkind":
        return {-1: "own-effect", 0: "tool/weapon-table"}.get(s, f"kind={s}")
    if kind == "action":
        return f"action={arg}"
    if kind == "tool":
        return f"{arg} ({TOOL_KINDS.get(arg, '?')})"
    if kind == "onoff":
        return {0: "OFF", 1: "ON"}.get(arg, str(arg))
    return str(s)


def parse(data: bytes, stop_at_end: bool = True) -> list[Event]:
    """Return the list of Events. Stops after the first END (op 66) by default."""
    out = []
    n = len(data) // 8
    for i in range(n):
        op, arg = struct.unpack_from("<II", data, i * 8)
        out.append(Event(i, op, arg))
        if stop_at_end and op == END_OP:
            break
    return out


def census(data: bytes) -> Counter:
    return Counter(e.op for e in parse(data, stop_at_end=False))


def render(data: bytes) -> str:
    """Human-readable timeline grouped by FRAME marker. `setup:` = events before the
    first FRAME (they fire on the first pumped frame)."""
    events = parse(data)
    lines = []
    cur = "setup"
    buf = []

    def flush():
        if not buf:
            return
        head = f"@{cur}" if cur == "setup" else f"@frame {cur}"
        lines.append(head)
        for e in buf:
            mn = opname(e.op)
            conf = OPCODES.get(e.op, (None, None, " "))[2]
            lines.append(f"    op{e.op:<3d} {mn:<16s} {fmt_arg(e.op, e.arg):<22s} [{conf}]")

    for e in events:
        if e.op == 0:
            flush()
            buf = []
            cur = e.arg
        elif e.op == END_OP:
            flush()
            buf = []
            lines.append("@END")
        else:
            buf.append(e)
    flush()
    return "\n".join(lines)


def summary(data: bytes) -> dict:
    events = parse(data)
    frames = [e.arg for e in events if e.op == 0]
    chains = []
    for k, e in enumerate(events):
        if e.op in (62, 63):
            nxt = events[k + 1] if k + 1 < len(events) else None
            anim = nxt.arg if nxt is not None and nxt.op == CHAIN_PARAM_OP else e.arg
            chains.append({"op": e.op, "skill": _s32(e.arg), "anim_offset": _s32(anim), "on_hit_only": e.op == 63})
    windows = _hit_windows(events)
    return {
        "pairs": len(events),
        "first_frame": frames[0] if frames else None,
        "last_frame": frames[-1] if frames else None,
        "n_frame_markers": len(frames),
        "hit_windows": windows,
        "hit_window": windows,   # legacy key kept for older callers and selftest.py
        "effects": [_s32(e.arg) for e in events if e.op == 43],
        "actions": [e.arg for e in events if e.op == 42],
        "sounds": [f"0x{e.arg:08X}" for e in events if e.op == 45],
        "damage_mult": [round(_s32(e.arg) / 4096, 3) for e in events if e.op == 17],
        "dash": [round(_s32(e.arg) / 4096, 3) for e in events if e.op == 3],
        "tool_kind": [e.arg for e in events if e.op == 44],
        "chains": chains,
        "opcodes": sorted({e.op for e in events}),
    }


# --------------------------------------------------------------------------- #
# Canonical text form, assembler and edit operations (2026-09-19)
# --------------------------------------------------------------------------- #
class AsatkError(ValueError):
    pass


_MNEMONIC_TO_OP = {v[0]: k for k, v in OPCODES.items()}


def op_from_name(name) -> int:
    """'HITBOX' / 'hitbox' / 'op10' / '10' -> 10."""
    if isinstance(name, int):
        return name
    s = str(name).strip()
    u = s.upper()
    if u in _MNEMONIC_TO_OP:
        return _MNEMONIC_TO_OP[u]
    if u.startswith("OP") and u[2:].isdigit():
        return int(u[2:])
    if s.isdigit():
        return int(s)
    raise AsatkError(f"unknown opcode {name!r} (use a mnemonic from `asatk ops`, opN or a number)")


def parse_operand(text) -> int:
    """Operand text -> u32: signed decimal, 0x hex, `1.5q` (Q12 = 6144) or `90deg` (u16 angle)."""
    if isinstance(text, int):
        return text & 0xFFFFFFFF
    s = str(text).strip().lower()
    try:
        if s.endswith("q"):
            return int(round(float(s[:-1]) * 4096)) & 0xFFFFFFFF
        if s.endswith("deg"):
            return int(round(float(s[:-3]) * 65536 / 360)) & 0xFFFFFFFF
        return int(s, 0) & 0xFFFFFFFF
    except ValueError:
        raise AsatkError(f"bad operand {text!r} (signed int, 0x hex, 1.5q or 90deg)") from None


def build(events) -> bytes:
    """Serialise Events (or (op, arg) pairs) back to the on-disk stream."""
    out = bytearray()
    for e in events:
        op, arg = (e.op, e.arg) if hasattr(e, "op") else (e[0], e[1])
        out += struct.pack("<II", op & 0xFFFFFFFF, arg & 0xFFFFFFFF)
    return bytes(out)


def _reindex(events) -> list[Event]:
    return [Event(i, e.op, e.arg) for i, e in enumerate(events)]


def disassemble(data: bytes) -> str:
    """Canonical, re-assemblable listing: one `<mnemonic> <operand>` per line for EVERY
    pair in the file (two shipped files carry one pair after END; it is kept), the
    decoded meaning as a trailing comment. `assemble(disassemble(x)) == x`."""
    out = ["; as_atk timeline -- one event per line: <mnemonic | opN> <operand>  ; comment",
           "; operand = signed int, 0x hex, `1.5q` (Q12 fixed point) or `90deg` (u16 angle)",
           "; FRAME n waits for animation frame n; END ends the stream. `asatk ops` lists opcodes."]
    for e in parse(data, stop_at_end=False):
        kind = OPCODES.get(e.op, (None, "int"))[1]
        val = f"0x{e.arg:08X}" if kind == "sfx" else str(_s32(e.arg))
        out.append(f"{opname(e.op):<18s} {val:<12s} ; #{e.index:<3d} {fmt_arg(e.op, e.arg)}")
    return "\n".join(out) + "\n"


def assemble(text: str) -> bytes:
    """Text in the `disassemble` form (mnemonics or opN, comments after ';') -> stream bytes.
    Also accepts the `render` style lines (`@frame N`, `@END`, `opNN NAME ...`)."""
    events = []
    for ln_no, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.split(";", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        if low.startswith("@frame"):
            events.append((0, parse_operand(line.split()[1])))
            continue
        if low in ("@end", "end"):
            events.append((END_OP, 0))
            continue
        if low.startswith("@setup"):
            continue
        toks = line.split()
        try:
            op = op_from_name(toks[0])
        except AsatkError as ex:
            raise AsatkError(f"line {ln_no}: {ex}") from None
        # `render` style: "op10  HITBOX  ON  [V]" -> op token then mnemonic then formatted value
        if toks[0].lower().startswith("op") and len(toks) > 1 and toks[1].upper() in _MNEMONIC_TO_OP:
            raise AsatkError(f"line {ln_no}: this is the display listing from `asatk show`; "
                             f"edit the `asatk dump` listing instead (raw operands)")
        if len(toks) > 2:
            raise AsatkError(f"line {ln_no}: expected `<mnemonic> <operand>`, got {line!r}")
        try:
            arg = parse_operand(toks[1]) if len(toks) > 1 else 0
        except AsatkError as ex:
            raise AsatkError(f"line {ln_no}: {ex}") from None
        events.append((op, arg))
    return build(events)


def set_event(events, index: int, op=None, arg=None) -> list[Event]:
    evs = list(events)
    if not 0 <= index < len(evs):
        raise AsatkError(f"event index {index} out of range (0..{len(evs) - 1})")
    e = evs[index]
    evs[index] = Event(index, e.op if op is None else op_from_name(op),
                       e.arg if arg is None else parse_operand(arg))
    return _reindex(evs)


def insert_event(events, index: int, op, arg) -> list[Event]:
    evs = list(events)
    if not 0 <= index <= len(evs):
        raise AsatkError(f"insert index {index} out of range (0..{len(evs)})")
    evs.insert(index, Event(index, op_from_name(op), parse_operand(arg)))
    return _reindex(evs)


def delete_event(events, index: int) -> list[Event]:
    evs = list(events)
    if not 0 <= index < len(evs):
        raise AsatkError(f"event index {index} out of range (0..{len(evs) - 1})")
    del evs[index]
    return _reindex(evs)


def insert_at_frame(events, frame: int, op, arg) -> list[Event]:
    """Insert an event so it fires at animation `frame`: after the last event of that
    frame's group, creating the FRAME marker (in clock order) when the file has none."""
    evs = list(events)
    op, arg = op_from_name(op), parse_operand(arg)
    frame = int(frame)
    end = next((i for i, e in enumerate(evs) if e.op == END_OP), len(evs))
    markers = [(i, e.arg) for i, e in enumerate(evs[:end]) if e.op == 0]
    for k, (i, f) in enumerate(markers):
        if f == frame:
            nxt = markers[k + 1][0] if k + 1 < len(markers) else end
            evs.insert(nxt, Event(0, op, arg))
            return _reindex(evs)
    # no marker for this frame: put a new FRAME group before the first later marker
    pos = next((i for i, f in markers if f > frame), end)
    evs[pos:pos] = [Event(0, 0, frame), Event(0, op, arg)]
    return _reindex(evs)


def validate(events) -> list[str]:
    """Things the pump would trip over: no END, FRAME markers out of order, a HITBOX left
    armed at END, CHAIN_ANIM without a preceding CHAIN, unknown opcodes (the handler
    table has 66 slots; anything above indexes past it)."""
    out = []
    evs = list(events)
    if not any(e.op == END_OP for e in evs):
        out.append("no END (op 66): the pump runs off the end of the stream")
    last, armed = -1, False
    for e in evs:
        if e.op > END_OP:
            out.append(f"#{e.index}: opcode {e.op} has no handler (table has 0..66)")
        if e.op == 0:
            if e.arg < last:
                out.append(f"#{e.index}: FRAME {e.arg} goes backwards (previous {last}); it never fires")
            last = max(last, e.arg)
        elif e.op == 10:
            armed = bool(e.arg)
        elif e.op == CHAIN_PARAM_OP and (e.index == 0 or evs[e.index - 1].op not in (62, 63)):
            out.append(f"#{e.index}: CHAIN_ANIM without a CHAIN/CHAIN_ONHIT right before it")
        elif e.op == END_OP:
            if armed:
                out.append(f"#{e.index}: END with the hitbox still armed (op 10 ON without OFF)")
            break
    return out


def _hit_windows(events):
    """[(arm_frame, disarm_frame)] from HITBOX (op 10) ON/OFF pairs, tracking the FRAME clock."""
    frame, open_f, out = 0, None, []
    for e in events:
        if e.op == 0:
            frame = e.arg
        elif e.op == 10:
            if e.arg:
                open_f = frame
            elif open_f is not None:
                out.append((open_f, frame))
                open_f = None
    if open_f is not None:
        out.append((open_f, None))
    return out
