"""Play a scene of the current map's bank in the RUNNING game now, the way a walk-in box starts
one -- no code of ours runs in the game, only the three writes the game's own box poll makes.

How the game starts a box scene (RF4S.exe, decompiled):
  * Trigger_PollPlayerProximityAndQueueEvent (+0x1F0920) finds the player in a type-3 box and
    writes: the scene's pc to the scene block +0x10, bit 0 of the scene control word +0x78
    (g_sceneAuxControlFlags: "a box fired" -- the poll does nothing while it is set) and
    event kind 14 into the first free slot of the 32-slot event queue at +0x1A0 (8 bytes each,
    the kind in the low u16).
  * NpcAi_TickOneActor (+0x1F3D10) pops the queue only while the scene VM is idle (state 1),
    no map transition runs (g_currentScene) and the scene control word +0x74 has none of
    0x300200; then it calls kind 14's handler, NpcAi_DispatchPendingEventOrFinalize
    (+0x1F5090): it checks the tail slot (the current map's bank: loaded, pc < its size, VM
    byte +134 set, VM idle), starts the scene VM at the pc (state 4) and clears bit 0 again.
    Everything a box scene does around that (holding the player, the end-of-scene clean-up in
    NpcAi_FinalizeEventAndPostTick) is the game's own.
So only scenes of the bank the game has loaded for the map the player stands on can be
started this way; the game rejects a pc past that bank (and finalizes as if nothing ran).

The scene block is the global at hotreload.RVA_SCENE_CONTEXT (g_currentSceneContext is its
first field): +0x08 the scene VM (g_currentSceneNpcAiState), +0x10 the pending pc, +0x74 the
scene control word, +0x78 the aux control word, +0x1A0 the queue.
"""
import struct

from . import hotreload

KIND_BOX_SCENE = 14
OFF_VM, OFF_PC, OFF_CTRL, OFF_AUX, OFF_QUEUE = 0x08, 0x10, 0x74, 0x78, 0x1A0
QUEUE_SLOTS = 32
CTRL_BLOCKING = 0x300200            # NpcAi_TickOneActor waits while any of these is set
AUX_BOX_FIRED = 0x1
VM_STATE, VM_PC, VM_TAIL_ENABLED = 0x70, 0x3C, 134


class PlayError(Exception):
    """Why the scene cannot be started now (a message for the user)."""


def _block(g):
    return g.g_scene                   # the address of the global block, not its first pointer


def game_state(g):
    """What matters for starting a scene: {vm, vm_state, vm_pc, queue (kinds), ctrl, aux,
    tail (bank index of the tail slot or None), tail_size, tail_enabled}."""
    blk = _block(g)
    vm = g.ptr(blk + OFF_VM)
    q = [struct.unpack_from("<H", bytes(g.read(blk + OFF_QUEUE + 8 * i, 2)))[0]
         for i in range(QUEUE_SLOTS)]
    out = dict(vm=vm, vm_state=g.u32(vm + VM_STATE) if vm else None,
               vm_pc=g.u32(vm + VM_PC) if vm else None,
               queue=[k for k in q if k], ctrl=g.u32(blk + OFF_CTRL), aux=g.u32(blk + OFF_AUX),
               tail=None, tail_size=0, tail_enabled=bool(vm and g.u8(vm + VM_TAIL_ENABLED)))
    sc = g.scene()
    if sc:
        for name, s, _mode, bi, _buf, size, loaded in g.slots(sc):
            if name == "tail" and s and loaded:
                out["tail"], out["tail_size"] = bi, size
    return out


def why_not(st, tail_index, pc):
    """None when a scene at `pc` of tail bank `tail_index` can be started now, else why not."""
    if not st["vm"]:
        return "the game has no scene system yet (title screen or loading)"
    if st["tail"] is None:
        return "the game has no map bank loaded (title screen or loading)"
    if st["tail"] != tail_index:
        return "wrong map"
    if st["vm_state"] != 1:
        return "a scene is playing"
    if st["queue"] or st["aux"] & AUX_BOX_FIRED:
        return "the game has events waiting to start"
    if st["ctrl"] & CTRL_BLOCKING:
        return "the game is busy (a talk or a party change is being handled)"
    if not st["tail_enabled"]:
        return "the game does not run map scenes right now"
    if not 0 < pc < st["tail_size"]:
        return "0x%04x is past the bank the game holds (0x%04x bytes)" % (pc, st["tail_size"])
    return None


def start(g, tail_index, pc):
    """Queue the scene at `pc` of the current map's bank, as a walk-in box would (the game
    starts it on its next frame). Raises PlayError when it cannot be started now. Returns the
    state read just before (game_state). The scene VM's pc is set to 0 meanwhile: ran() tells
    whether the game took the scene."""
    g.suspend()
    try:
        st = game_state(g)
        why = why_not(st, tail_index, pc)
        if why:
            raise PlayError(why)
        blk = _block(g)
        # an idle VM's pc is left over from its last run and nothing reads it: 0 marks "not
        # run yet", so a scene that runs to its end within one frame is still seen to have run
        g.write(st["vm"] + VM_PC, struct.pack("<I", 0))
        g.write(blk + OFF_PC, struct.pack("<I", pc))
        g.write(blk + OFF_AUX, struct.pack("<I", st["aux"] | AUX_BOX_FIRED))
        g.write(blk + OFF_QUEUE, struct.pack("<Q", KIND_BOX_SCENE))     # the queue is empty
    finally:
        g.resume()
    return st


def ran(st):
    """After start(): whether the game has run (or is running) the scene, from a later
    game_state: the VM left idle, or its pc moved off the 0 start() wrote."""
    return st["vm_state"] != 1 or bool(st["vm_pc"])


def cancel(g):
    """Take a queued (not yet started) scene back out. True when it was still waiting."""
    g.suspend()
    try:
        blk = _block(g)
        if struct.unpack("<Q", bytes(g.read(blk + OFF_QUEUE, 8)))[0] != KIND_BOX_SCENE:
            return False
        g.write(blk + OFF_QUEUE, b"\0" * 8)
        g.write(blk + OFF_AUX, struct.pack("<I", g.u32(blk + OFF_AUX) & ~AUX_BOX_FIRED))
        return True
    finally:
        g.resume()


def changed_bits(before, after):
    """[(byte index, old, new)] where two flag-store blobs differ."""
    return [(i, a, b) for i, (a, b) in enumerate(zip(before, after)) if a != b]


def changed_variables(emf, before, after):
    """[(name, old, new)] of the named variables whose value differs, then the count of
    changed bits no variable covers."""
    out, covered = [], set()
    diff = {i for i, _a, _b in changed_bits(before, after)}
    if not diff:
        return out, 0
    for v in getattr(emf, "variables", ()) if emf is not None else ():
        lo, hi = v.bit_offset >> 3, (v.bit_offset + v.bit_width - 1) >> 3
        if not any(i in diff for i in range(lo, hi + 1)):
            continue
        old, new = emf.read_value(before, v), emf.read_value(after, v)
        for b in range(v.bit_offset, v.bit_offset + v.bit_width):
            covered.add(b)
        if old != new:
            out.append((v.name, old, new))
    loose = 0
    for i in diff:
        x = before[i] ^ after[i]
        for k in range(8):
            if x >> k & 1 and 8 * i + k not in covered:
                loose += 1
    return out, loose


def restore_flags(g, bits_addr, before):
    """Write back every byte of the flag store that differs from `before` (suspended, from a
    fresh read). Returns how many bytes were put back."""
    g.suspend()
    try:
        now = bytes(g.read(bits_addr, len(before)))
        n = 0
        for i, _a, _b in changed_bits(before, now):
            g.write(bits_addr + i, before[i:i + 1])
            n += 1
        return n
    finally:
        g.resume()
