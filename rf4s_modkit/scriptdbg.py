"""A script-level debugger for the RUNNING game: the Script VMs, their registers and stack,
breakpoints, pause / continue / step -- without a native debugger and without touching the exe.

How the game runs a script (RF4S.exe, verified in the IDB):
  * NpcAi_StepScriptActionStateMachine drives each ScriptVMContext_t every frame by its
    state (+0x70): 2 = waiting (a countdown at +0x78 = field_120, decremented by 200 per
    frame), 3 = replay the statement that blocked last frame (opcode cached at +0x7C),
    4 = step statements with Script_VMStep (RF4S.exe+0x23EF60) until one returns non-zero
    (yield), 1 = idle, 5 = halted (stack error).
  * JMP never yields (Script_VMStep returns 0), so a JMP to itself would spin inside one
    frame and hang the game -- a breakpoint has to yield.
  * WaitPlain (op 4) with a literal: 'vm+120 = value, vm+112 = 2' and nothing else -- no
    register, no flag, no quest-reaction latch (Wait, op 2, has one).
  * An action statement moves pc past itself BEFORE it runs (its arguments go on the VM
    stack). One that blocks (a prompt, a choice, dialogue: the handler returns non-zero)
    leaves the VM in state 3 with pc already at the NEXT statement; the game replays the
    cached opcode with the stacked arguments every frame until it is done, then drops them.
    So a state-2 VM (a countdown) stands exactly at a statement start; a state-3 VM does not
    stand anywhere the debugger can hold it; a state-1 VM's pc is left over from its last
    run (starting it would run whatever follows its end).
  * Expression tag 1 pushes an i32 literal (Script_EvalExpressionBytecode: kind 1, like the
    u16 / s16 tags 0x19 / 0x1A, 5 bytes).

A breakpoint at (bank, pc) is therefore:
    bank[pc]      JMP stub                 (4 bytes over the statement's first 4)
    stub - 6      01 <i32 PARK_UNITS> 00   the literal the WaitPlain reads
    stub          WaitPlain(PARK_UNITS)     the VM parks here (state 2), registers untouched
    stub + 6      <copy of the statement>   what `continue` runs
                  JMP pc + size             back to where the program goes on
The debugger keeps a held VM's countdown topped up to PARK_UNITS (about 30 s), so it stays
until Continue / Step -- and if the debugger dies, the script goes on by itself after that.
The statement copy behaves like the original: targets and expression offsets are absolute,
a CALL returns into the stub and its JMP goes back, a blocking op replays at the copy.
A RET is 2 bytes: no breakpoint fits, so no script can be halted at one (Step says so).

The debugger works on the code the GAME runs: breakpoints come from the editor in its terms,
and one whose statement differs in the game (an edit not yet saved + reloaded in game) waits
("pending") until the game has the same bytes there. Stubs go after the game's copy of the
bank, and move when a reload in game makes the bank longer.

The stubs live in the slot buffer after the bank's code. Like hot reload, each slot the
debugger touches gets its own 64 KiB buffer (the VM reads code through slot +16 on every
step, so swapping the buffer pointer with the same bytes is safe); pcs are u16, so a bank
needs its data + stubs to fit below 0x10000. Nothing is freed: a VM may still be inside a
stub.

The game copies a bank in again from its resident rf3.mc whenever it loads it (a map
change), and a MapEnterScene starts in that same frame -- long before the next poll could
patch the slot. So the debugger also swaps the resident file (the hot-reload way: the
archive cache entry's data pointer) for a copy in which every bank with a breakpoint is
moved to the end, carrying its JMPs and its stubs (its table entry / the header's global
bank words point there, the header's max bank sizes grow to match): a fresh load is patched
already. The copy is rebuilt when the breakpoints change and when someone else (a hot
reload) replaces the file; Detach puts the game's file back.

Pausing a VM that is not at a breakpoint is only possible while the script itself waits
(state 2): the debugger tops its countdown up and gives the rest back on Continue. Idle
(state 1), blocked (state 3) and halted VMs are refused -- turning those into a countdown
would start stale code or skip the blocked statement with its arguments left on the stack
(an event that never ends: no warps, no player control). Step works from a held VM only,
whose pc is a statement start.

Game time stops while any VM is held: the calendar ticks only while g_calendarTask (+0xB0 ->
the calendar) byte +0x3C is 1 -- script op 163 (SetCalendarPauseFlagFromBit0) clears it,
NpcAi_FinalizeEventAndPostTick sets it back when an event ends, and every time-skip op saves
it, sets 1 and restores it. The debugger clears it while it holds a VM (keeping it clear if
the game sets it meanwhile) and puts the old value back when nothing is held any more.

A debugger that dies without detaching (killed, crashed) would leave the clock stopped and
its patches in: while attached it keeps a recovery note (RECOVERY_NAME, next to the
toolkit's settings) of everything it changed, and the next attach to the same game undoes
what is left (recover()). Hot reload reads the note too and refuses while a script is
stopped. The note is also the lock: a second debugger on the same game is refused while
the note's owner process lives (two would take each other's patched rf3.mc for the game's
own and keep reinstalling it).
"""
from __future__ import annotations

import json
import os
import struct
import time

from . import hotreload, script

VM_STATES = {0: "free", 1: "idle", 2: "waiting", 3: "in a statement (prompt, dialogue ...)", 4: "running", 5: "halted"}
VM_OFF = dict(slot=0x20, stack=0x28, stack_cap=0x30, stack_top=0x34, pc=0x3C, regs=0x40,
              frame_base=0x6C, state=0x70, halted=0x74, wait=0x78)
WAIT_PLAIN = 4                      # WaitPlain(value): park with no side effect
FRAME_UNITS = 200                   # the countdown drops by this per frame (NpcAi_PerFrameTick)
PARK_UNITS = FRAME_UNITS * 60 * 30  # ~30 s at 60 fps: the stub's literal and the hold top-up
HOLD = PARK_UNITS
LIT_SIZE = 6                        # 01 <i32> 00
STUB_ALIGN = 16
BANK_LIMIT = 0x10000
RET_OP = 0xFFFF
RVA_CALENDAR_TASK = 0xE96008        # g_calendarTask (pointer)
CAL_INNER, CAL_RUNNING = 0xB0, 0x3C # task -> calendar; its "time runs" byte
RECOVERY_NAME = "scriptdbg-recovery.json"


class DebugError(Exception):
    pass


def recovery_path():
    from . import gamepaths
    return gamepaths.settings_path().parent / RECOVERY_NAME


def _process_alive(pid):
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k32.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def read_recovery(pid=None):
    """The recovery note (a dict) of a debugger attached to game `pid` (any when None)."""
    try:
        note = json.loads(recovery_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if pid is not None and note.get("pid") != pid:
        return None
    return note


def eval_live(buf, off, regs, read_var):
    """Evaluate the expression at `off` the way Script_EvalExpressionBytecode does, with
    the VM's registers (`regs`, 10 ints) and live game variables (`read_var(enc)` -> int or
    None). Returns (value, ok); ok is False where the value cannot be known without running
    it: a compound assignment (it writes), a var-array read (tag 6: no shipped script uses
    one), or an unreadable variable. Leaves 3/4/5/0x11..0x13 are the typed constants."""
    n = len(buf)
    if not 0 <= off < n:
        return None, False
    t0 = buf[off]
    if t0 == 5:
        v = script._u16(buf, off + 1)
        return (v, v is not None)
    if t0 in (3, 4):
        v = script._u32(buf, off + 1)
        return (v, v is not None)
    if t0 in (0x11, 0x12, 0x13):
        return 0, True
    stack, p = [], off
    for _ in range(256):
        if not 0 <= p < n:
            return None, False
        t = buf[p]
        if t == 0:
            return (stack[-1], True) if stack else (None, False)
        if t in (0x14, 0x15, 0x16):
            stack.append({0x14: 0, 0x15: -1, 0x16: 1}[t]); p += 1
        elif t == 0x17:
            stack.append(buf[p + 1]); p += 2
        elif t == 0x18:
            stack.append(struct.unpack_from("<b", buf, p + 1)[0]); p += 2
        elif t == 0x19:
            stack.append(struct.unpack_from("<H", buf, p + 1)[0]); p += 3
        elif t == 0x1A:
            stack.append(struct.unpack_from("<h", buf, p + 1)[0]); p += 3
        elif t == 1:
            stack.append(struct.unpack_from("<i", buf, p + 1)[0]); p += 5
        elif t == 2:
            v = read_var(struct.unpack_from("<I", buf, p + 1)[0])
            if v is None:
                return None, False
            stack.append(v); p += 5
        elif 7 <= t <= 0x10:
            stack.append(regs[t - 7]); p += 1
        elif 0x80 <= t <= 0x8F:
            op = t - 0x80
            if op == 0:
                p += 1
            elif op in (1, 2):
                if not stack:
                    return None, False
                stack[-1] = script._i32(-stack[-1]) if op == 1 else int(stack[-1] == 0); p += 1
            else:
                if len(stack) < 2:
                    return None, False
                b = stack.pop(); a = stack.pop()
                stack.append(script._expr_binop(op, a, b)); p += 1
        else:
            return None, False                  # tag 6, a compound assignment, unknown
    return None, False


def statement_maps(template, game, doc):
    """({game pc: editor pc}, {editor pc: game pc}) between two versions of one bank: the
    game's bytes and the editor's (`template` = the editor's Bank, for its tables' layout).
    Both are parsed with bankrelink (every statement as its bytes with the address fields
    zeroed, plus its expressions: a layout-free signature), and the signature sequences are
    aligned: equal runs map one to one, and so does a run replaced by one of the same length
    (statements edited in place). Inserted / deleted statements have no partner."""
    import copy
    import difflib
    from . import bankrelink

    def model(data):
        b = copy.copy(template)
        b.data = bytearray(data)
        b.__dict__.pop("_table_end", None)
        return bankrelink.BankModel.parse_any(b)

    def sig(s):
        if isinstance(s, bankrelink.Stmt):
            raw = bytearray(s.raw)
            for off, _kind in s.fields:             # jump targets / expression offsets move
                raw[off:off + 2] = b"\0\0"          # with every edit: compare without them
            return bytes(raw), tuple(bytes(e) for e in s.exprs)
        return "raw", bytes(s.raw)

    mg, md = model(game), model(doc)
    a, b = [sig(s) for s in mg.code], [sig(s) for s in md.code]
    g2d = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                g2d[mg.code[i1 + k].old_pc] = md.code[j1 + k].old_pc
    return g2d, {d: g for g, d in g2d.items()}


class VM:
    """One Script VM as read from the game."""
    __slots__ = ("addr", "state", "halted", "slot", "bank", "pc", "regs", "frame_base",
                 "stack_top", "stack", "wait", "at_bp", "held")

    def state_name(self):
        return VM_STATES.get(self.state, "state %d" % self.state)


class Breakpoint:
    __slots__ = ("bank", "pc", "size", "orig", "stub", "temp", "hits", "blob", "pending", "doc_pc")

    def __init__(self, bank, pc, size, orig, temp=False):
        self.bank, self.pc, self.size, self.orig = bank, pc, size, orig
        self.stub = None                # pc of the stub in the bank's address space
        self.blob = b""                 # the literal + stub bytes (rewritten if a bank reload lost them)
        self.temp = temp                # a step's one-shot breakpoint
        self.hits = 0
        self.pending = None             # why it is not in the game (None: it is, or will be next poll)
        self.doc_pc = None              # the editor's pc of its statement (an editor breakpoint)

    @property
    def resume_pc(self):            # where a parked VM stands: after the WaitPlain
        return None if self.stub is None else self.stub + 6


class ScriptDebugger:
    def __init__(self, container, pid=None):
        self.c = container
        self.g = hotreload._Game(pid)
        self.bps = {}                   # (bank, pc) -> Breakpoint
        self.held = set()               # VM addresses the debugger holds (paused)
        self._saved_wait = {}           # VM address -> the countdown it had when paused
        self._released = {}             # VM address -> (pc, countdown) it was let go with
        self.bufs = {}                  # slot address -> our buffer (bytes the bank + stubs)
        self.orig_bufs = {}             # slot address -> (the game's own buffer, ours)
        self.left = []                  # what the last detach could not undo
        self.stub_top = {}              # bank -> next free stub base
        self._stubs = {}                # bank -> [(stub, bp pc, size, end)] every stub written
        self.user = set()               # the editor's breakpoints {(bank, editor pc)} (the GUI sets it)
        self.user_pending = {}          # (bank, editor pc) -> why it is not in the game
        self._maps = {}                 # bank -> (bytes key, statement_maps(...)) cache
        self.slot_bank = {}             # slot address -> bank position (last read)
        self.mismatch = set()           # banks whose game copy differs from the editor's
        self.parked = {}                # VM address -> (bank, pc): the breakpoint it stopped at
        self.freeze_clock = True        # stop game time while a VM is held
        self._res_orig = None           # the resident rf3.mc the game had (the copy's source)
        self._res_base = None           # (pointer, bytes) of it, read once
        self._res_img = None            # our patched copy while installed
        self._res_dirty = True          # the breakpoints changed since the copy was built
        self._res_free = []             # [(pointer, time)]: older copies, freed after a while
        self._clock = None              # (address, old value) while the debugger stops time
        self._note = None               # the recovery note as last written
        self._flags = None              # the game-flag store as read this poll
        other =read_recovery(self.g.pid)
        if other and other.get("base") == self.g.base and other.get("owner") not in (None, os.getpid()) \
                and _process_alive(other["owner"]):
            self.g.close()
            raise DebugError("another script debugger (process %d) is attached to this game: "
                             "detach it first -- two would undo each other's patches"
                             % other["owner"])
        self.recovered = self.recover()  # what an earlier, dead debugger left and was undone
        self._look_at_resident()
        self._write_note()              # from now on: this process owns the game's debugging

    # ---- reading the game ------------------------------------------------------------- #
    def _bank_pos(self, mode, bi):
        c = self.c
        if mode == 0:
            return next((i for i, b in enumerate(c.banks) if b.kind == "global"), None)
        if mode == 1:
            return bi if 0 <= bi < c.n_primary else None
        return c.n_primary + bi if 0 <= bi < c.n_tail else None

    def slots(self):
        """[(name, slot addr, bank pos | None, buf, size, loaded)]."""
        g = self.g
        sc = g.scene()
        if not sc:
            return []
        out = []
        for name, s, mode, bi, buf, size, loaded in g.slots(sc):
            pos = self._bank_pos(mode, bi) if s and loaded else None
            if s:
                self.slot_bank[s] = pos
            out.append((name, s, pos, buf, size, loaded))
        return out

    def vms(self):
        """[VM] of the running scene state, with registers and stack."""
        g = self.g
        sc = g.scene()
        if not sc:
            return []
        slot_bank = {s: pos for _n, s, pos, _b, _z, _l in self.slots()}
        out = []
        for addr, state, halted, slot, pc in g.vms(sc):
            v = VM()
            v.addr, v.state, v.halted, v.slot, v.pc = addr, state, halted, slot, pc
            v.bank = slot_bank.get(slot)
            raw = g.read(addr + VM_OFF["regs"], 40)
            v.regs = list(struct.unpack("<10i", raw))
            v.frame_base = g.u32(addr + VM_OFF["frame_base"])
            v.stack_top = g.u32(addr + VM_OFF["stack_top"])
            v.wait = g.u32(addr + VM_OFF["wait"])
            stk = g.ptr(addr + VM_OFF["stack"])
            n = min(v.stack_top, 4096)
            v.stack = list(struct.unpack("<%di" % n, g.read(stk, 4 * n))) if stk and n else []
            v.at_bp = next((b for b in self.bps.values()
                            if b.bank == v.bank and b.resume_pc == pc and state == 2), None)
            v.held = addr in self.held or v.at_bp is not None
            out.append(v)
        return out

    # ---- game variables (FLG_ / REG_) ----------------------------------------------------- #
    def flags_blob(self):
        """The live game-flag store (flagstate: g_gameFlagsBuffer -> {zone2 base, zone2
        bits, bits pointer}); read once per poll. None before it exists (title screen)."""
        if self._flags is not None:
            return self._flags
        from . import flagstate
        g = self.g
        hdr = g.ptr(g.base + flagstate.FLAGS_BUFFER_RVA)
        if not hdr:
            return None
        zb, zn, bits = struct.unpack("<IIQ", bytes(g.read(hdr, 16)))
        if (zb, zn) != (flagstate.ZONE2_BASE, flagstate.ZONE2_BITS) or not bits:
            return None
        self._flags = bytes(g.read(bits, flagstate.BLOB_SIZE))
        return self._flags

    def read_var(self, enc):
        """The live value of a packed variable reference (a token-0x02 u32): `width` bits
        at `bit_offset`, MSB-first like GameFlags_ReadField, sign-extended when the
        reference's sign bit says so (Script_StackSlot_NormalizeToInt32 case 2)."""
        blob = self.flags_blob()
        if blob is None:
            return None
        off, width, signed = self.c.unpack_var(enc)
        v = 0
        for i in range(width):
            b = off + i
            if (b >> 3) >= len(blob):
                return None
            v = (v << 1) | ((blob[b >> 3] >> (b & 7)) & 1)
        if signed and width and v >> (width - 1):
            v -= 1 << width
        return v

    def game_bank(self, pos):
        """The bytes of bank `pos` in the game's own resident rf3.mc (None before the game
        has loaded it: the title screen)."""
        if self._res_orig is None:
            return None
        base = self._resident_bytes()
        w = struct.unpack_from("<19I", base, 0)
        mode, idx = self._bank_ref(pos)
        if mode == 0:
            o, n = w[3], w[4]
        else:
            o, n = struct.unpack_from("<II", base, (w[6] if mode == 1 else w[8]) + 8 * idx)
        return base[o:o + n]

    # ---- breakpoints -------------------------------------------------------------------- #
    def add_breakpoint(self, bank, pc, temp=False):
        """A breakpoint on the statement at `pc` of the GAME's bank (the editor's while the
        game has not loaded its scripts). The editor's breakpoints come in through `user`
        (editor pcs) and are placed with the statement map (_apply_user)."""
        key = (bank, pc)
        if key in self.bps:
            if not temp:
                self.bps[key].temp = False
            return self.bps[key]
        game = self.game_bank(bank)
        src = game if game is not None else bytes(self.c.banks[bank].data)
        st = script.decode_statement(src, pc)
        if st is None:
            raise DebugError("no statement starts at 0x%04x in bank %d" % (pc, bank))
        if st.op == RET_OP:
            raise DebugError("a script cannot be halted at a RET (0x%04x): it is 2 bytes, too "
                             "short for the breakpoint's jump" % pc)
        if st.size < 4:
            raise DebugError("%s at 0x%04x is only %d bytes: a breakpoint needs 4 (put it on the "
                             "statement before)" % (st.mnem, pc, st.size))
        bp = Breakpoint(bank, pc, st.size, bytes(src[pc:pc + st.size]), temp)
        self._validate(bp, game)
        self.bps[key] = bp
        self._res_dirty = True
        return bp

    def _validate(self, bp, game=None):
        """Set bp.pending (None when the game has the breakpoint's statement) and give an
        installable breakpoint a stub past the game's copy of the bank."""
        game = self.game_bank(bp.bank) if game is None else game
        if game is None:
            bp.pending = "the game has not loaded its scripts yet"
        elif bytes(game[bp.pc:bp.pc + bp.size]) != bp.orig:
            bp.pending = "the game runs another version of this bank: save + Reload in game"
            self.mismatch.add(bp.bank)
        else:
            bp.pending = None
            floor = (len(game) + STUB_ALIGN - 1) // STUB_ALIGN * STUB_ALIGN
            if bp.stub is None or bp.stub - LIT_SIZE < floor:
                self._alloc_stub(bp, floor)

    # ---- the editor's breakpoints -> the game's statements ------------------------------- #
    def pc_maps(self, bank):
        """statement_maps() of `bank` (game vs editor), cached; None when both hold the same
        bytes (the pcs are the same) or the game has not loaded its scripts."""
        game = self.game_bank(bank)
        if game is None:
            return None
        doc = bytes(self.c.banks[bank].data)
        if game == doc:
            return None
        key = (len(game), hash(game), len(doc), hash(doc))
        hit = self._maps.get(bank)
        if hit is None or hit[0] != key:
            hit = self._maps[bank] = (key, statement_maps(self.c.banks[bank], game, doc))
        return hit[1]

    def to_doc(self, bank, pc):
        """The editor's pc of the statement at game pc `pc` (None: the editor has no such
        statement any more)."""
        m = self.pc_maps(bank) if bank is not None and pc is not None else None
        return pc if m is None else m[0].get(pc)

    def to_game(self, bank, pc):
        """The game's pc of the editor's statement at `pc` (None: the game does not have it
        yet -- a new or changed statement not saved + reloaded in game)."""
        m = self.pc_maps(bank)
        return pc if m is None else m[1].get(pc)

    def _apply_user(self):
        """Install the editor's breakpoints (`user`, editor pcs) at their statements' pcs in
        the game -- an unsaved edit that moves a statement does not move it in the game, so
        its breakpoint keeps firing there. One the game has no statement for waits in
        user_pending. Breakpoints added directly (step, tests) are left alone."""
        want, pending = {}, {}
        for bank, dpc in self.user:
            if self.game_bank(bank) is None:
                pending[(bank, dpc)] = "the game has not loaded its scripts yet"
                continue
            gpc = self.to_game(bank, dpc)
            if gpc is None:
                pending[(bank, dpc)] = ("not in the game yet (a new or changed statement): "
                                        "save + Reload in game")
                continue
            want[(bank, gpc)] = dpc
        busy = set(self.parked.values())
        for key in [k for k, b in self.bps.items()
                    if b.doc_pc is not None and not b.temp and k not in want and k not in busy]:
            self.remove_breakpoint(*key)
        for key, dpc in want.items():
            bp = self.bps.get(key)
            if bp is None:
                try:
                    bp = self.add_breakpoint(*key)
                except DebugError as e:
                    pending[(key[0], dpc)] = str(e)
                    continue
            bp.temp, bp.doc_pc = False, dpc
        self.user_pending = pending

    def user_state(self, bank, dpc):
        """(the Breakpoint in the game or None, why it waits or None) of the editor's
        breakpoint (bank, editor pc)."""
        if (bank, dpc) in self.user_pending:
            return None, self.user_pending[(bank, dpc)]
        bp = next((b for b in self.bps.values() if b.bank == bank and b.doc_pc == dpc and not b.temp), None)
        return bp, (bp.pending if bp is not None else None)

    def _alloc_stub(self, bp, floor):
        """Give `bp` its stub (after the game's bank code and earlier stubs) and bytes."""
        top = max(self.stub_top.get(bp.bank, 0), floor)
        stub = top + LIT_SIZE               # the WaitPlain literal, then the stub
        blob = (struct.pack("<BiB", 1, PARK_UNITS, 0)
                + struct.pack("<HHH", WAIT_PLAIN, 1, top)
                + bp.orig + self._jmp(bp.pc + bp.size))
        if top + len(blob) > BANK_LIMIT:
            raise DebugError("bank %d has no room for another breakpoint "
                             "(its code + stubs must stay below 64 KiB)" % bp.bank)
        bp.stub, bp.blob = stub, blob
        end = top + (len(blob) + STUB_ALIGN - 1) // STUB_ALIGN * STUB_ALIGN
        self.stub_top[bp.bank] = end
        # every stub ever written stays in the slot (never freed): a script may still be in
        # one, or return into one (a CALL run from its copy), after its breakpoint is gone --
        # a one-shot Step breakpoint is removed as soon as it is hit. Newer stubs win.
        hist = [h for h in self._stubs.get(bp.bank, [])
                if (h[0] - LIT_SIZE >= end or h[3] <= top)       # not overwritten now
                and h[0] - LIT_SIZE >= floor]                     # not under the (grown) code
        hist.append((stub, bp.pc, bp.size, end))
        self._stubs[bp.bank] = hist

    def _in_stub(self, bank, pc):
        """(breakpoint pc, statement size, where in the stub) when `pc` lies in a stub ever
        written for `bank`: 'wait' (the WaitPlain / parked), 'copy' (the statement copy),
        'back' (the JMP back: the statement ran); None outside every stub."""
        for stub, bpc, size, _end in self._stubs.get(bank, ()):
            if stub - LIT_SIZE <= pc < stub + 6 + size + 4:
                where = "wait" if pc < stub + 6 else "copy" if pc < stub + 6 + size else "back"
                return bpc, size, where
        return None

    def _revalidate(self):
        """The game's rf3.mc changed (a reload in game): check every breakpoint against it
        again; stubs start over after the (maybe longer) banks. One-shot step breakpoints
        and breakpoints a VM is parked on stay as they are."""
        self.mismatch = set()
        self._maps = {}
        busy = set(self.parked.values())
        # the editor's breakpoints are placed again from their editor pcs (_apply_user):
        # the statements may sit elsewhere in the new file
        for key in [k for k, b in self.bps.items() if (b.temp or b.doc_pc is not None) and k not in busy]:
            self.remove_breakpoint(*key)
        for bank in {b.bank for b in self.bps.values()} - {k[0] for k in busy}:
            self.stub_top.pop(bank, None)
        for key, bp in self.bps.items():
            if key in busy:
                continue
            bp.stub = None
            game = self.game_bank(bp.bank)
            src = game if game is not None else bytes(self.c.banks[bp.bank].data)
            st = script.decode_statement(src, bp.pc)
            if st is None or st.size < 4:
                bp.pending = "no statement of 4 bytes or more starts here any more"
                continue
            bp.size, bp.orig = st.size, bytes(src[bp.pc:bp.pc + st.size])
            self._validate(bp)
        self._res_dirty = True

    def remove_breakpoint(self, bank, pc):
        bp = self.bps.pop((bank, pc), None)
        if bp is None:
            return
        self._res_dirty = True
        if bp.stub is None:
            return
        g = self.g
        g.suspend()
        try:
            for _n, s, pos, buf, size, loaded in self.slots():
                if pos == bank and loaded and self.bufs.get(s) == buf:
                    if g.read(buf + pc, 4) == self._jmp(bp.stub):
                        g.write(buf + pc, bp.orig[:4])
        finally:
            g.resume()

    @staticmethod
    def _jmp(target):
        return struct.pack("<HH", 0xFFFA, target & 0xFFFF)

    def _own_buffer(self, s, buf, size):
        """Give slot `s` a 64 KiB buffer of our own (same bytes); return it."""
        g = self.g
        if self.bufs.get(s) == buf:
            return buf
        if g.own_allocation(buf) >= hotreload.SLOT_BUF_SIZE:
            self.bufs[s] = buf                  # hot reload's buffer: big enough already
            return buf
        new = g.alloc(hotreload.SLOT_BUF_SIZE)
        g.write(new, g.read(buf, size))
        g.write(s + 16, struct.pack("<Q", new))
        self.bufs[s] = new
        self.orig_bufs.setdefault(s, (buf, new))   # the game's own buffer: Detach puts it back
        self._write_note()
        return new

    def _give_buffers_back(self, pairs, wait=1.0):
        """Point slots back at the game's own buffers ({slot: (game's buffer, ours)}), with
        the bank's bytes from the game's own rf3.mc, as soon as no script runs debugger
        code (a stub) in them -- waiting up to `wait` s for released scripts to leave their
        stubs. Only slots the scene still lists are touched. Returns {slot: pair} of those
        that keep our buffer (a script still inside a stub; harmless, same code)."""
        g = self.g
        pending = dict(pairs)
        img = hotreload.McImage(self._resident_bytes()) if self._res_orig else None
        t_end = time.time() + wait
        while pending:
            sc = g.scene()
            if not sc or img is None:
                break
            listed = {s: (mode, bi, loaded) for _n, s, mode, bi, _b, _z, loaded in g.slots(sc) if s}
            for s in [s for s in pending if s not in listed]:
                del pending[s]                  # the slot is gone (another scene): nothing to do
            busy = set()
            for _vm, st, _h, slot, pc in g.vms(sc):
                if slot in pending and st in (2, 3, 4):
                    mode, bi, loaded = listed[slot]
                    blob = img.bank_bytes(mode, bi) if loaded else None
                    if blob is None or pc >= len(blob):
                        busy.add(slot)          # running (or parked) in debugger code
            g.suspend()
            try:
                for s, (orig, ours) in list(pending.items()):
                    if s in busy:
                        continue
                    if g.ptr(s + 16) != ours:   # replaced meanwhile (a hot reload): theirs now
                        del pending[s]
                        continue
                    mode, bi, loaded = listed[s]
                    if loaded:
                        blob = img.bank_bytes(mode, bi)
                        if blob is None:
                            continue
                        g.write(orig, blob)
                        g.write(s + 24, struct.pack("<I", len(blob)))
                    g.write(s + 16, struct.pack("<Q", orig))
                    del pending[s]
            finally:
                g.resume()
            if not pending or time.time() > t_end:
                break
            time.sleep(0.05)
        return pending

    def _check_given_back(self, pairs):
        """A game thread paused inside MycfBankSlot_LoadBank finishes its copy (into the
        buffer it had read) after the resume: check the given-back slots hold the bank the
        slot says it holds, and fix any that do not."""
        g = self.g
        sc = g.scene()
        if not sc or not self._res_orig:
            return
        img = hotreload.McImage(self._resident_bytes())
        origs = {orig for orig, _ours in pairs.values()}
        g.suspend()
        try:
            for _n, s, mode, bi, buf, size, loaded in g.slots(sc):
                if s and loaded and buf in origs:
                    blob = img.bank_bytes(mode, bi)
                    if blob is not None and (size != len(blob) or bytes(g.read(buf, len(blob))) != blob):
                        g.write(buf, blob)
                        g.write(s + 24, struct.pack("<I", len(blob)))
        finally:
            g.resume()

    def sync(self):
        """Install the breakpoints of every loaded bank (again, after the game reloaded one),
        keep held VMs held. Called by poll(); returns the VMs."""
        g = self.g
        self._flags = None                      # variables are read fresh each poll
        if self._look_at_resident():
            self._revalidate()
        self._apply_user()
        self._sync_resident()
        vms = self.vms()
        want = {}
        for bp in self.bps.values():
            if bp.pending is None and bp.stub is not None:
                want.setdefault(bp.bank, []).append(bp)
        todo = []
        for _n, s, pos, buf, size, loaded in self.slots():
            if not (loaded and pos in want):
                continue
            for bp in want[pos]:
                if self.bufs.get(s) == buf and g.read(buf + bp.pc, 4) == self._jmp(bp.stub):
                    continue                   # in place
                todo.append((s, pos, buf, size, bp))
        if todo:
            g.suspend()
            try:
                for s, pos, buf, size, bp in todo:
                    cur = g.read(buf + bp.pc, bp.size)
                    ours = cur[:4] == self._jmp(bp.stub) and cur[4:] == bp.orig[4:]
                    if cur != bp.orig and not ours:
                        self.mismatch.add(pos)  # the slot holds other bytes: leave it alone
                        continue
                    buf = self._own_buffer(s, buf, size)
                    base = bp.stub - LIT_SIZE
                    if g.read(buf + base, len(bp.blob)) != bp.blob:
                        # new, or overwritten by a longer bank loaded into this slot meanwhile
                        g.write(buf + base, bp.blob)
                    g.write(buf + bp.pc, self._jmp(bp.stub))
            finally:
                g.resume()
        # hits: count them once, clear one-shot (step) breakpoints, hold every parked VM
        for v in vms:
            rel = self._released.get(v.addr)
            if rel is not None:
                # released by Continue / Step: still where it was let go, and its countdown only
                # went down -> the game has not run it yet. A fresh park sets PARK_UNITS again.
                if v.state == 2 and v.pc == rel[0] and v.wait <= rel[1]:
                    continue
                del self._released[v.addr]
            if v.at_bp is not None and v.addr not in self.held:
                v.at_bp.hits += 1
                self.held.add(v.addr)
                self.parked[v.addr] = (v.at_bp.bank, v.at_bp.pc)
                if v.at_bp.temp:
                    self._clear_temps()
            if v.addr in self.held and v.state != 2:
                # the game moved it on (a scene reset / new event): not ours to hold any more
                self.held.discard(v.addr)
                self.parked.pop(v.addr, None)
                self._saved_wait.pop(v.addr, None)
            elif v.addr in self.held and v.wait < HOLD // 2:
                g.write(v.addr + VM_OFF["wait"], struct.pack("<I", HOLD))
        live = {v.addr for v in vms}
        self.held &= live
        self.parked = {a: p for a, p in self.parked.items() if a in live}
        self._released = {a: r for a, r in self._released.items() if a in live}
        self._set_clock(bool(self.held) and self.freeze_clock)
        self._write_note()
        return vms

    poll = sync

    # ---- the resident file ------------------------------------------------------------ #
    def _bank_ref(self, pos):
        """(mode, index) of a bank position: 0 global / 1 primary / 2 tail."""
        c = self.c
        if c.banks[pos].kind == "global":
            return 0, 0
        return (1, pos) if pos < c.n_primary else (2, pos - c.n_primary)

    def _look_at_resident(self):
        """Note the game's resident rf3.mc; True when it changed since last time."""
        try:
            _entry, ptr, rc = self.g.archive_entry(self.g.mc_id)
        except hotreload.HotReloadError:
            return False
        if not ptr or rc == 0:
            return False                        # the title screen: nothing resident yet
        if ptr == self._res_img:
            return False
        # the game's own (or a hot reload's) file; a hot reload frees our copy itself
        self._res_img = None
        self._res_dirty = True
        if ptr == self._res_orig:
            return False
        self._res_orig = ptr
        return True

    def _sync_resident(self):
        """Keep the game's resident rf3.mc our patched copy while there are breakpoints."""
        g = self.g
        now = time.time()
        for item in [x for x in self._res_free if now - x[1] > 2.0]:
            g.free(item[0])
            self._res_free.remove(item)
        if self._look_at_resident():
            self._revalidate()
        if not self._res_dirty or self._res_orig is None:
            return
        self._res_dirty = False
        live = [bp for bp in self.bps.values() if bp.pending is None and bp.stub is not None]
        if not live:
            self._restore_resident()
            return
        base = self._resident_bytes()
        data = bytearray(base)
        w = list(struct.unpack_from("<19I", data, 0))
        by_bank = {}
        for bp in live:
            by_bank.setdefault(bp.bank, []).append(bp)
        for pos, bps in by_bank.items():
            mode, idx = self._bank_ref(pos)
            if mode == 0:
                t, (o, n) = None, (w[3], w[4])
            else:
                t = (w[6] if mode == 1 else w[8]) + 8 * idx
                o, n = struct.unpack_from("<II", data, t)
            bank = bytearray(base[o:o + n])
            put = False
            for bp in bps:
                if bytes(bank[bp.pc:bp.pc + bp.size]) != bp.orig:
                    continue                    # _validate said otherwise: the next revalidate
                top = bp.stub - LIT_SIZE
                if len(bank) < top + len(bp.blob):
                    bank.extend(bytes(top + len(bp.blob) - len(bank)))
                bank[top:top + len(bp.blob)] = bp.blob
                bank[bp.pc:bp.pc + 4] = self._jmp(bp.stub)
                put = True
            if not put:
                continue
            data.extend(bytes(-len(data) % STUB_ALIGN))
            off = len(data)
            data += bank
            if t is None:
                w[3], w[4] = off, len(bank)
            else:
                struct.pack_into("<II", data, t, off, len(bank))
                k = 12 if mode == 1 else 13
                w[k] = max(w[k], len(bank))
        struct.pack_into("<19I", data, 0, *w)
        img = hotreload.McImage(bytes(data))
        new = g.alloc(len(data) + 64)
        g.write(new, bytes(data))
        self._install_resident(new, img)

    def _resident_bytes(self):
        """The game's own resident rf3.mc (read once per file)."""
        g, ptr = self.g, self._res_orig
        if self._res_base is None or self._res_base[0] != ptr:
            w = struct.unpack("<19I", bytes(g.read(ptr, 76)))
            tables = bytes(g.read(ptr + w[6], 8 * w[5])) + bytes(g.read(ptr + w[8], 8 * w[7]))
            ends = [w[3] + w[4], w[6] + 8 * w[5], w[8] + 8 * w[7]]
            ends += [o + n for o, n in struct.iter_unpack("<II", tables)]
            self._res_base = (ptr, bytes(g.read(ptr, max(ends))))
        return self._res_base[1]

    def _install_resident(self, new, img):
        """Point the archive entry at `new` (suspended): refresh the scene's header cache and
        give every slot a buffer that takes the grown banks."""
        g = self.g
        g.suspend()
        try:
            entry, _ptr, _rc = g.archive_entry(g.mc_id)
            sc = g.scene()
            if sc:
                g.write(sc + 0x78, img.scene_fields())
                for _n, s, _m, _bi, buf, size, _l in g.slots(sc):
                    if s:
                        self._own_buffer(s, buf, size)
            g.write(entry, struct.pack("<Q", new))
        finally:
            g.resume()
        if self._res_img is not None:           # a thread may still copy from it: free later
            self._res_free.append((self._res_img, time.time()))
        self._res_img = new
        self._write_note()

    def _restore_resident(self):
        """Give the game its own rf3.mc back (when it still holds our copy)."""
        if self._res_img is None:
            return
        g = self.g
        g.suspend()
        try:
            entry, ptr, _rc = g.archive_entry(g.mc_id)
            if ptr == self._res_img:
                sc = g.scene()
                if sc:
                    g.write(sc + 0x78, hotreload.McImage(self._resident_bytes()).scene_fields())
                g.write(entry, struct.pack("<Q", self._res_orig))
        finally:
            g.resume()
        self._res_free.append((self._res_img, time.time()))
        self._res_img = None
        self._write_note()

    # ---- the game clock ------------------------------------------------------------------ #
    def _clock_flag(self):
        g = self.g
        task = g.ptr(g.base + RVA_CALENDAR_TASK)
        inner = g.ptr(task + CAL_INNER) if task else 0
        return inner + CAL_RUNNING if inner else None

    def _set_clock(self, frozen):
        """Stop game time (the calendar's 'runs' byte = 0) or give back the old value."""
        g = self.g
        if frozen:
            a = self._clock_flag()
            if a is None:
                return
            if self._clock is None or self._clock[0] != a:
                self._clock = (a, g.u8(a))
                self._write_note()              # before the write: a crash right after is covered
            if g.u8(a) != 0:
                g.write(a, bytes(1))
        elif self._clock is not None:
            a, old = self._clock
            self._clock = None
            try:
                if a == self._clock_flag() and g.u8(a) == 0:
                    g.write(a, bytes([old]))
            except Exception:  # noqa: BLE001 -- the calendar went away (title screen)
                pass
            self._write_note()

    @property
    def clock_frozen(self):
        return self._clock is not None

    def _clear_temps(self):
        for key in [k for k, b in self.bps.items() if b.temp]:
            self.remove_breakpoint(*key)

    # ---- the recovery note ------------------------------------------------------------- #
    def _note_now(self, owner=True):
        installed = [[b.bank, b.pc, b.orig[:4].hex(), b.stub] for b in self.bps.values()
                     if b.pending is None and b.stub is not None]
        return {"pid": self.g.pid, "base": self.g.base, "owner": os.getpid() if owner else None,
                "bufs": {str(s): list(p) for s, p in self.orig_bufs.items()},
                "res_orig": self._res_orig, "res_img": self._res_img,
                "clock": list(self._clock) if self._clock else None,
                "patches": installed,
                "held": {str(a): self._saved_wait.get(a, 0) for a in self.held}}

    def _write_note(self, owner=True):
        note = self._note_now(owner)
        if note == self._note:
            return
        self._note = note
        try:
            p = recovery_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(note), encoding="utf-8")
        except OSError:
            pass

    def _drop_note(self):
        self._note = None
        try:
            recovery_path().unlink()
        except OSError:
            pass

    def recover(self):
        """Undo what a debugger that died while attached to this game left behind (its
        recovery note): the patched rf3.mc, the stopped clock, the breakpoint jumps in the
        slots, held scripts. Returns a list of what was undone ([] when nothing was)."""
        note = read_recovery(self.g.pid)
        if note is None:
            return []
        g, done = self.g, []
        if note.get("base") != g.base:
            self._drop_note()                   # an older run of the game: nothing to undo
            return []
        g.suspend()
        try:
            entry, ptr, _rc = g.archive_entry(g.mc_id)
            if note.get("res_img") and ptr == note["res_img"] and note.get("res_orig"):
                self._res_orig = note["res_orig"]
                sc = g.scene()
                if sc:
                    g.write(sc + 0x78, hotreload.McImage(self._resident_bytes()).scene_fields())
                g.write(entry, struct.pack("<Q", note["res_orig"]))
                done.append("gave the game its own rf3.mc back")
            clk = note.get("clock")
            if clk and g.u8(clk[0]) == 0 and self._clock_flag() == clk[0]:
                g.write(clk[0], bytes([clk[1]]))
                done.append("started game time again")
            sc = g.scene()
            n = 0
            if sc:
                for _n, s, mode, bi, buf, _size, loaded in g.slots(sc):
                    pos = self._bank_pos(mode, bi) if s and loaded else None
                    for bank, pc, orig4, stub in note.get("patches", []):
                        if bank == pos and g.read(buf + pc, 4) == self._jmp(stub):
                            g.write(buf + pc, bytes.fromhex(orig4))
                            n += 1
            if n:
                done.append("took out %d breakpoint jump%s" % (n, "" if n == 1 else "s"))
            m = 0
            live = {vm for vm, *_r in g.vms(sc)} if sc else set()
            for addr, rest in (note.get("held") or {}).items():
                addr = int(addr)
                if addr in live and g.u32(addr + VM_OFF["state"]) == 2:
                    g.write(addr + VM_OFF["wait"], struct.pack("<I", rest))
                    m += 1
            if m:
                done.append("let %d stopped script%s go on" % (m, "" if m == 1 else "s"))
        finally:
            g.resume()
        pairs = {int(s): tuple(p) for s, p in (note.get("bufs") or {}).items()}
        if pairs:
            _e, ptr, _rc = g.archive_entry(g.mc_id)
            self._res_orig = ptr                # the game's own file again (restored above)
            kept = self._give_buffers_back(pairs, wait=0.5)
            time.sleep(0.3)
            self._check_given_back({s: p for s, p in pairs.items() if s not in kept})
            n = len(pairs) - len(kept)
            if n:
                done.append("gave %d slot buffer%s back" % (n, "" if n == 1 else "s"))
            self.orig_bufs = dict(kept)         # still ours: this debugger takes them over
        self._res_orig = None
        self._drop_note()
        return done

    # ---- control ------------------------------------------------------------------------ #
    @staticmethod
    def why_not_pause(vm):
        """None when `vm` can be paused, else why not (a sentence)."""
        if vm.state == 2:
            return None
        return {1: "it is idle: no script runs on it",
                3: "it waits for the game (a prompt, a choice, dialogue ...) inside a statement: "
                   "set a breakpoint on the statement after it instead",
                5: "it halted (a stack error)"}.get(vm.state, "it is %s" % vm.state_name())

    def why_not_step(self, vm):
        """None when `vm` can be stepped / continued, else why not."""
        if vm.addr not in self.held:
            return "it is not stopped (a breakpoint or Pause stops it first)"
        return None

    def pause(self, vm):
        """Hold a VM that waits (state 2) where it is: its countdown is topped up, the rest
        comes back on Continue."""
        why = self.why_not_pause(vm)
        if why:
            raise DebugError("cannot pause this script: " + why)
        g = self.g
        g.suspend()
        try:
            if g.u32(vm.addr + VM_OFF["state"]) != 2:
                raise DebugError("cannot pause this script: it just moved on")
            self._saved_wait[vm.addr] = g.u32(vm.addr + VM_OFF["wait"])
            g.write(vm.addr + VM_OFF["wait"], struct.pack("<I", HOLD))
        finally:
            g.resume()
        self.held.add(vm.addr)
        self._write_note()

    def resume(self, vm, _stepping=False):
        """Let a held VM go on (from a breakpoint: it runs the statement, then goes on; from
        Pause: it finishes the wait it was in)."""
        if vm.addr not in self.held:
            return                              # never touch a VM the debugger does not hold
        self.held.discard(vm.addr)
        self.parked.pop(vm.addr, None)
        rest = self._saved_wait.pop(vm.addr, 0)
        g = self.g
        g.suspend()             # the game decrements this countdown every frame (read-modify-
        try:                    # write): writing while it runs could lose our value
            if g.u32(vm.addr + VM_OFF["state"]) == 2:
                pc = g.u32(vm.addr + VM_OFF["pc"])
                bp = next((b for b in self.bps.values() if b.bank == vm.bank and b.pc == pc
                           and b.stub is not None and b.pending is None), None)
                buf = g.ptr(g.ptr(vm.addr + VM_OFF["slot"]) + 16) if bp is not None else 0
                if bp is not None and buf and g.read(buf + pc, 4) == self._jmp(bp.stub):
                    # it stands ON a breakpointed statement (paused there, or the breakpoint
                    # was set where it stood): going on would run the jump into that very
                    # breakpoint and stop again -- start it in the stub's copy instead
                    pc = bp.resume_pc
                    g.write(vm.addr + VM_OFF["pc"], struct.pack("<I", pc))
                g.write(vm.addr + VM_OFF["wait"], struct.pack("<I", rest))
                # until the game runs it, it looks just like a VM that parked there: not a hit
                self._released[vm.addr] = (pc, rest)
        finally:
            g.resume()
        if not self.held and not _stepping:
            self._set_clock(False)
        self._write_note()

    def step(self, vm, over=True):
        """Run the statement the VM stands at and stop at the next one (every successor
        gets a one-shot breakpoint; `over` = a CALL stops after it returns). Returns a note
        for the user when the script cannot stop at every next statement (a RET), else None."""
        why = self.why_not_step(vm)
        if why:
            raise DebugError("cannot step this script: " + why)
        bank, pc = vm.bank, self.logical_pc(vm)
        if bank is None or pc is None:
            raise DebugError("the VM is not at a statement of a known bank")
        code = self.game_bank(bank)
        code = code if code is not None else bytes(self.c.banks[bank].data)
        st = script.decode_statement(code, pc)
        if st is None:
            raise DebugError("no statement at 0x%04x" % pc)
        nexts = []
        if st.op == RET_OP:
            nexts.append(pc)                    # stands at a RET: where it returns to (below)
        elif st.falls_through and not st.terminator:
            nexts.append(pc + st.size)
        if st.mnem == "CALL":
            if not over and st.code_targets:
                nexts.append(st.code_targets[0])
        else:
            nexts += [t for t in st.code_targets if t is not None]
        stops, lost, ends = 0, [], False
        for t in nexts:
            nx = script.decode_statement(code, t)
            if nx is not None and nx.op == RET_OP:
                # no breakpoint fits a RET: stop where it returns to instead
                try:
                    t = self._return_target(vm, code)
                except DebugError as e:
                    lost.append(str(e))
                    continue
                if t is None:
                    ends = True                 # the script's last RET: it ends there
                    continue
            try:
                self.add_breakpoint(bank, t, temp=True)
                stops += 1
            except DebugError as e:
                lost.append(str(e))
        self.sync()
        self.resume(vm, _stepping=True)       # time stays stopped until the next poll
        if not stops and ends:
            return "the script ends at the RET: there is no next statement to stop at"
        if not stops and not lost:
            return "%s: nothing to stop at next -- the script runs on to the next breakpoint" % st.mnem
        if lost:
            return ("cannot stop at the next statement -- %s -- so the script %s"
                    % ("; ".join(lost), "runs on to the next breakpoint" if not stops
                       else "only stops if it takes another way"))
        return None

    def _return_target(self, vm, code):
        """Where a RET executed in `vm`'s current frame goes: the statement after the CALL
        (Script_Opcode_FFFF_EndAndCleanup: pc = stack[frame_base - 1], frame base =
        stack[frame_base - 2]; frame base 0 = the script ends -> None). A return into a
        breakpoint's stub (the CALL ran from its copy) goes on after the breakpoint's
        statement; a return onto another RET is followed up the next frame."""
        fb, stack = vm.frame_base, vm.stack
        for _ in range(64):
            if fb == 0:
                return None                     # the script's own end
            if fb < 2 or fb - 1 >= len(stack):
                raise DebugError("cannot tell where the RET returns to (the stack does not "
                                 "hold a return address there)")
            ret = stack[fb - 1] & 0xFFFF
            inside = self._in_stub(vm.bank, ret)
            if inside is not None:
                ret = inside[0] + inside[1]      # returns into a stub's copy: its JMP back goes on there
            nx = script.decode_statement(code, ret)
            if nx is None or nx.op != RET_OP:
                return ret
            fb = stack[fb - 2]                  # that RET returns again: the caller's frame
        return None

    def logical_pc(self, vm):
        """The pc in the FILE's terms: a VM parked in a stub stands at its breakpoint."""
        if vm.addr in self.parked:
            return self.parked[vm.addr][1]
        if vm.at_bp is not None:
            return vm.at_bp.pc
        inside = self._in_stub(vm.bank, vm.pc)  # in a stub (also one whose breakpoint is gone)
        if inside is not None:
            bpc, size, where = inside
            # at the JMP back (the statement copy ran): the statement after the original
            return bpc + size if where == "back" else bpc
        return vm.pc

    def detach(self):
        """Put the game back as it was: breakpoint jumps out, held scripts go on (with the
        countdown they had), game time runs, the game's own rf3.mc and slot buffers back
        (the latter once no released script runs debugger code in them), and everything
        the debugger allocated freed. Every step runs even when an earlier one fails;
        whatever could not be undone stays in the recovery note (with no owner, so any
        later attach finishes it). Returns a list of what was left ([] = all restored)."""
        g, errors = self.g, []

        def attempt(fn, *a):
            try:
                return fn(*a)
            except Exception as e:  # noqa: BLE001 -- keep going: undo as much as possible
                errors.append("%s: %s" % (getattr(fn, "__name__", "step"), e))
                return None

        for key in list(self.bps):
            attempt(self.remove_breakpoint, *key)
        for addr in list(self.held):
            attempt(self._let_go, addr)
        self.held.clear()
        self._saved_wait.clear()
        attempt(self._set_clock, False)
        attempt(self._restore_resident)
        pairs = dict(self.orig_bufs)
        kept = attempt(self._give_buffers_back, pairs)
        kept = pairs if kept is None else kept
        time.sleep(0.3)                         # a thread paused mid-copy finishes it
        attempt(self._check_given_back, {s: p for s, p in pairs.items() if s not in kept})
        # free what is ours and no longer used: old rf3.mc copies, given-back buffers
        used = set()
        try:
            sc = g.scene()
            used = {buf for _n, s, _m, _bi, buf, _z, _l in g.slots(sc) if s} if sc else set()
        except Exception as e:  # noqa: BLE001
            errors.append("slots: %s" % e)
        for p, _t in self._res_free:
            attempt(g.free, p)
        self._res_free = []
        for s, (_orig, ours) in pairs.items():
            if s not in kept and ours not in used and not errors:
                attempt(g.free, ours)
        self.orig_bufs = dict(kept)
        left = list(errors)
        if kept:
            left.append("%d slot%s keep%s the debugger's buffer (a script is still inside a "
                        "breakpoint's copy -- same code, harmless; the next attach gives it back)"
                        % (len(kept), "" if len(kept) == 1 else "s", "s" if len(kept) == 1 else ""))
        if left:
            self._write_note(owner=None)        # recoverable by any later attach
        else:
            self._drop_note()
        g.close()
        self.left = left
        return left

    def _let_go(self, addr):
        g = self.g
        if g.u32(addr + VM_OFF["state"]) == 2:
            g.write(addr + VM_OFF["wait"], struct.pack("<I", self._saved_wait.get(addr, 0)))
