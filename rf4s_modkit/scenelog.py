"""Log which scene code the RUNNING game executes, and check it against what the editor shows.

The cutscene editor lists the scenes a bank registers, the subroutines they call and the
unreached code (script.unreached); a static audit (selftest: visibility audit) shows those
views hold every statement that can run. Code the exe starts at a fixed address would still
be missed by that, so this watches the game itself: it polls the Script VMs of the running
RF4S.exe (the same process access as hotreload.py: g_currentSceneContext -> the SceneState,
its global / primary / tail bank slots at +200 / +208 / +216 and its VM list at +0x70; each
VM keeps its state at +0x70, its bank slot at +0x20 and its pc at +0x3C) and records every
(bank, pc) a running VM is at.

Reading only: nothing is written and the game is never suspended. Polling cannot see every
statement (the VM runs several per frame), so the log is evidence, not a complete trace --
but it does catch every scene START it sees and any code the editor would not show.

Each recorded pc is classified against the rf3.mc on disk (the one the game loads):
  shown        a statement of a scene the bank list shows (registered, or real unreached)
  unreached    shown, but in an 'unreached' row -- the game DID run it (worth a look: that
               code is started by something the bank's own tables don't list)
  not shown    no view shows a statement there -- this is what the log exists to find
  torn         the pc is not a statement start in the file: a read that raced the game
               (or a file on disk that differs from the game's); only reported when seen
               more than once
"""
from __future__ import annotations

import json
import time

from . import hotreload, script

RUNNING_STATES = (2, 3, 4)          # waiting / blocked mid-op / started (hotreload.BUSY_VM_STATES)


class SceneLog:
    """Poll the game and collect {(bank position, pc): samples}; starts = the first pc each
    VM was seen at after it (re)started."""

    def __init__(self, pid=None, container=None):
        self.g = hotreload._Game(pid)
        self.c = container
        self.samples = {}                # (bank pos, pc) -> times seen
        self.starts = []                 # [(time, bank pos, pc)] scene starts seen
        self.bank_differs = set()        # banks whose bytes in the game differ from the file
        self._running = {}               # vm address -> was running last poll
        self._checked_banks = set()

    # the game's slots -> the file's bank positions (global = the container's last bank)
    def _bank_pos(self, mode, bi):
        c = self.c
        if mode == 0:
            return next((i for i, b in enumerate(c.banks) if b.kind == "global"), None)
        if mode == 1:
            return bi if 0 <= bi < c.n_primary else None
        return c.n_primary + bi if 0 <= bi < c.n_tail else None

    def poll(self):
        g = self.g
        sc = g.scene()
        if not sc:
            return 0
        slot_bank = {}
        for _name, s, mode, bi, buf, size, loaded in g.slots(sc):
            if s and loaded:
                pos = self._bank_pos(mode, bi)
                slot_bank[s] = pos
                if pos is not None and pos not in self._checked_banks and size:
                    self._checked_banks.add(pos)
                    try:
                        if bytes(g.read(buf, size)) != bytes(self.c.banks[pos].data[:size]):
                            self.bank_differs.add(pos)
                    except Exception:  # noqa: BLE001 -- a race; checked again next time
                        self._checked_banks.discard(pos)
        n = 0
        for vm, state, _halted, slot, pc in g.vms(sc):
            run = state in RUNNING_STATES
            pos = slot_bank.get(slot)
            if run and pos is not None:
                key = (pos, pc)
                self.samples[key] = self.samples.get(key, 0) + 1
                if not self._running.get(vm):
                    self.starts.append((time.time(), pos, pc))
                n += 1
            self._running[vm] = run
        return n

    def run(self, seconds=None, interval=0.002, on_start=None, stop=None):
        """Poll until `seconds` pass, `stop()` returns True, or Ctrl+C; on_start(pos, pc) is
        called for each scene start as it is seen."""
        t_end = time.time() + seconds if seconds else None
        seen = len(self.starts)
        try:
            while (t_end is None or time.time() < t_end) and not (stop and stop()):
                try:
                    self.poll()
                except hotreload.HotReloadError:
                    raise
                except Exception:  # noqa: BLE001 -- a read that raced the game: try again
                    pass
                if on_start is not None:
                    for _t, pos, pc in self.starts[seen:]:
                        on_start(pos, pc)
                seen = len(self.starts)
                time.sleep(interval)
        except KeyboardInterrupt:
            pass

    # ---- the check -------------------------------------------------------------------- #
    def classify(self):
        """{(bank pos, pc): 'shown' | 'unreached' | 'not shown' | 'torn'} for every sample."""
        out, cache = {}, {}
        for (pos, pc), _n in self.samples.items():
            if pos not in cache:
                bank = self.c.banks[pos]
                scenes = script.disassemble_bank(bank)
                real = script.unreached(scenes)
                reg = set()
                for sc in scenes:
                    if sc.action_type >= 0:
                        reg |= set(sc.stmts)
                unr = set()
                for sc, _own in real:
                    unr |= set(sc.stmts)
                starts = set()
                for sc in scenes:
                    starts |= set(sc.stmts)
                cache[pos] = (reg, unr - reg, starts)
            reg, unr, starts = cache[pos]
            if pc in reg:
                out[(pos, pc)] = "shown"
            elif pc in unr:
                out[(pos, pc)] = "unreached"
            elif pc in starts:
                out[(pos, pc)] = "not shown"      # a statement, but only in a skipped stub
            else:
                out[(pos, pc)] = "torn" if script.decode_statement(self.c.banks[pos].data, pc) is None \
                    else "not shown"
        return out

    def report(self):
        """A readable summary (list of lines)."""
        cls = self.classify()
        by = {}
        for k, v in cls.items():
            by.setdefault(v, []).append(k)
        lines = ["%d distinct (bank, pc) seen in %d samples, %d scene start(s)"
                 % (len(self.samples), sum(self.samples.values()), len(self.starts))]
        for kind in ("shown", "unreached", "not shown", "torn"):
            ks = sorted(by.get(kind, ()))
            if kind == "torn":
                ks = [k for k in ks if self.samples[k] > 1]
            lines.append("  %-10s %d" % (kind, len(ks)))
            if kind in ("unreached", "not shown", "torn"):
                for pos, pc in ks[:40]:
                    lines.append("      bank %d @%04x  (%d sample%s)" % (pos, pc, self.samples[(pos, pc)],
                                                                        "" if self.samples[(pos, pc)] == 1 else "s"))
        if self.bank_differs:
            lines.append("  note: the game's copy of bank(s) %s differs from the rf3.mc on disk "
                         "(a hot reload or an unsaved edit?) -- their pcs may not match the file"
                         % ", ".join(str(b) for b in sorted(self.bank_differs)))
        return lines

    def to_json(self):
        cls = self.classify()
        return {"samples": [{"bank": p, "pc": pc, "n": n, "class": cls[(p, pc)]}
                            for (p, pc), n in sorted(self.samples.items())],
                "starts": [{"t": t, "bank": p, "pc": pc} for t, p, pc in self.starts],
                "bank_differs": sorted(self.bank_differs)}

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, indent=1)
