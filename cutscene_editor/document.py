"""The editing model: rf3.mc (the Script-VM banks), the rf3mc.<locale> dialogue archives
and em.bin (the Event Manager), with ONE undo history across all of them and byte-exact
"unsaved" tracking.

    with doc.edit("Set speaker", view):
        bank.set_action_opcode(pc, op)

An edit records only what changed: the banks whose bytes differ (plus the header region
when a bank moved or grew), the dialogue lines that differ per locale, and em.bin's bytes
when it changed -- a few KB per step, not the 4.7 MB container. An edit that changes
nothing records nothing; a failed edit restores everything and re-raises.
"""
from __future__ import annotations

import pathlib
from contextlib import contextmanager

from rf4s_modkit import script, textdb

from .catalog import LOCALES

UNDO_DEPTH = 80


class ScriptDocument:
    def __init__(self, reader=None):
        self.reader = reader                   # reader(basename) -> bytes | None
        self.container = None
        self.locale = "eng"
        self.arcs = {}                         # locale -> TextArchive (loaded on demand)
        self._missing = set()                  # locales the reader cannot supply
        self._em = None                        # emscript.EmScript | False (unavailable)
        self.emf_vars = None                   # emflags.EmFlagTable (FLG_/REG_ names)
        self.undo_stack, self.redo_stack = [], []
        self._saved_mc = None
        self._saved_text = {}                  # locale -> entries as loaded / saved
        self._saved_em = None
        self._listeners = []
        self._depth = 0
        self.path = None                       # file the container came from (Open…)

    # ---- loading ------------------------------------------------------------ #
    def load_from_reader(self):
        raw = self.reader("rf3.mc") if self.reader else None
        if not raw:
            return False
        self._install(script.Container(raw))
        return True

    def load_file(self, path):
        p = pathlib.Path(path)
        c = script.Container(p.read_bytes())
        folder = p.parent
        base = self.reader

        def reader(n, d=folder, base=base):
            f = d / n
            if f.is_file():
                return f.read_bytes()
            return base(n) if base else None
        self.reader = reader
        self.arcs.clear()
        self._missing.clear()
        self._saved_text.clear()
        self._em = None
        self.path = p
        self._install(c)

    def reload_from_disk(self):
        """Read rf3.mc again from where it came from (the opened file, else the game
        source), and drop the cached dialogue and em.bin so they are re-read too. Unsaved
        edits and the undo history are discarded. False when the file is not there."""
        if self.path is not None:
            raw = self.path.read_bytes() if self.path.is_file() else None
        else:
            raw = self.reader("rf3.mc") if self.reader else None
        if not raw:
            return False
        c = script.Container(raw)
        self.arcs.clear()
        self._missing.clear()
        self._saved_text.clear()
        self._em = None
        self._saved_em = None
        self._install(c)
        return True

    def _install(self, container):
        self.container = container
        self._saved_mc = container.build()
        self._saved_banks = [bytes(b.data) for b in container.banks]
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._install_resolvers()

    def _install_resolvers(self):
        """FLG_/REG_ names for packed variables, in the disassembly and the assembler."""
        self.emf_vars = None
        script.set_packed_var_resolver(None)
        if self.container is None:
            return
        try:
            from rf4s_modkit.emflags import EmFlagTable
            data = self.reader("emdeb.bin") if self.reader else None
            emf = EmFlagTable.parse(data) if data else EmFlagTable.load()
            script.install_emflags_var_resolver(self.container, emf)
            self.emf_vars = emf
        except Exception:
            self.emf_vars = None
        try:
            self.container.install_asm_resolver(self.emf_vars)
        except Exception:
            pass

    # ---- dialogue archives ---------------------------------------------------- #
    def archive(self, locale=None):
        """The rf3mc.<locale> archive (loaded and cached on first use), or None."""
        loc = locale or self.locale
        if loc not in self.arcs and loc not in self._missing:
            data = self.reader(f"rf3mc.{loc}") if self.reader else None
            try:
                arc = textdb.TextArchive.parse(data) if data else None
            except Exception:
                arc = None
            if arc is None:
                self._missing.add(loc)
            else:
                self.arcs[loc] = arc
                self._saved_text[loc] = list(arc.entries)
        return self.arcs.get(loc)

    @property
    def textarc(self):
        return self.archive(self.locale)

    def text(self, line_id, locale=None):
        arc = self.archive(locale)
        if arc is None or line_id is None:
            return None
        try:
            return arc.text(line_id)
        except Exception:
            return None

    def other_locales(self):
        """{locale: archive} for every other locale the source can supply."""
        return {loc: a for loc in LOCALES if loc != self.locale
                for a in [self.archive(loc)] if a is not None}

    def add_line(self, text, pad_locales=True):
        """Append `text` as a new line of the current locale; with `pad_locales`, give
        every other locale the same id (appended text, '[<loc> TBD]' filler for a shorter
        archive) so it is in range everywhere. Returns (new id, [locales touched])."""
        arc = self.textarc
        nid = arc.append_text(text)
        touched = []
        if pad_locales:
            for loc, other in sorted(self.other_locales().items()):
                if len(other) > nid:
                    continue
                while len(other) < nid:
                    other.append_text("[%s TBD]" % loc)
                other.append_text(text)
                touched.append(loc)
        return nid, touched

    # ---- Event Manager ---------------------------------------------------------- #
    @property
    def em(self):
        """The decoded em.bin (None when em.bin / emdeb.bin cannot be found)."""
        if self._em is None:
            try:
                from rf4s_modkit import emscript
                em_data = self.reader("em.bin") if self.reader else None
                dbg = self.reader("emdeb.bin") if self.reader else None
                if em_data and dbg:
                    self._em = emscript.EmScript.parse(em_data, emscript.EmNames.parse(dbg))
                else:
                    self._em = emscript.EmScript.load()
                self._saved_em = self._em.build()
            except Exception:
                self._em = False
        return self._em or None

    # ---- listeners ---------------------------------------------------------------- #
    def subscribe(self, fn):
        self._listeners.append(fn)

    def notify(self, what="edit"):
        for fn in list(self._listeners):
            fn(what)

    # ---- transactions --------------------------------------------------------------- #
    def _capture(self):
        c = self.container
        order = sorted(range(len(c.banks)), key=lambda i: c.banks[i].file_off)
        head = bytes(c.data[:c.banks[order[0]].file_off]) if order else bytes(c.data)
        return {"container": c, "head": head, "order": order,
                "banks": [bytes(b.data) for b in c.banks],
                "texts": {loc: list(a.entries) for loc, a in self.arcs.items()},
                "em": self._em.build() if self._em else None}

    @staticmethod
    def _text_delta(eb, ea):
        if eb == ea:
            return None
        bd, ad = {}, {}
        for i in range(max(len(eb), len(ea))):
            x = eb[i] if i < len(eb) else None
            y = ea[i] if i < len(ea) else None
            if x != y:
                if x is not None:
                    bd[i] = x
                if y is not None:
                    ad[i] = y
        return (len(eb), bd, len(ea), ad)

    @contextmanager
    def edit(self, label, view=None):
        """One undoable edit. `view` = (bank position, scene entry pc) to reopen on undo."""
        if self._depth or self.container is None:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        before = self._capture()
        self._depth += 1
        try:
            yield
        except BaseException:
            self._depth -= 1
            self._restore(before)
            raise
        self._depth -= 1
        step = self._diff(label, before, view)
        if step is not None:
            self.undo_stack.append(step)
            del self.undo_stack[:-UNDO_DEPTH]
            self.redo_stack.clear()
        self.notify("edit")

    def _diff(self, label, before, view):
        if self.container is not before["container"]:
            return None
        after = self._capture()
        mc = None
        changed = {i for i, (x, y) in enumerate(zip(before["banks"], after["banks"])) if x != y}
        if changed or before["head"] != after["head"] or before["order"] != after["order"]:
            mc = {"head": (before["head"], after["head"]), "order": (before["order"], after["order"]),
                  "banks": {i: (before["banks"][i], after["banks"][i]) for i in changed}}
        texts = {}
        for loc, ea in after["texts"].items():
            eb = before["texts"].get(loc)
            if eb is None:                          # loaded during the edit (Add line padding)
                eb = self._saved_text.get(loc)
            if eb is None:
                continue
            d = self._text_delta(eb, ea)
            if d is not None:
                texts[loc] = d
        em = None
        em_before = before["em"] if before["em"] is not None else self._saved_em
        if after["em"] is not None and em_before != after["em"]:
            em = (em_before, after["em"])
        if mc is None and not texts and em is None:
            return None
        return {"label": label, "mc": mc, "texts": texts, "em": em, "view": view}

    def _restore(self, snap):
        """Put a captured snapshot back (a failed edit)."""
        c = self.container
        for b, data in zip(c.banks, snap["banks"]):
            if bytes(b.data) != data:
                self._rebuild_from(snap["head"], snap["banks"], snap["order"])
                break
        for loc, ents in snap["texts"].items():
            if loc in self.arcs:
                self.arcs[loc].entries[:] = ents
        if snap["em"] is not None and self._em and self._em.build() != snap["em"]:
            self._set_em_bytes(snap["em"])

    def _rebuild_from(self, head, banks, order):
        self.container = script.Container(head + b"".join(banks[i] for i in order))
        self._install_resolvers()

    def _set_em_bytes(self, blob):
        from rf4s_modkit import emscript
        self._em = emscript.EmScript.parse(blob, self._em.names)

    def _apply(self, step, side):
        mc = step["mc"]
        if mc is not None:
            banks = [bytes(b.data) for b in self.container.banks]
            for i, pair in mc["banks"].items():
                banks[i] = pair[side]
            self._rebuild_from(mc["head"][side], banks, mc["order"][side])
        for loc, (lb, bd, la, ad) in step["texts"].items():
            arc = self.arcs.get(loc)
            if arc is None:
                continue
            n, d = (lb, bd) if side == 0 else (la, ad)
            ents = arc.entries[:n] + [b""] * max(0, n - len(arc.entries))
            for i, v in d.items():
                if i < n:
                    ents[i] = v
            arc.entries[:] = ents
        if step["em"] is not None and self._em:
            self._set_em_bytes(step["em"][side])
        self.notify("undo")

    def undo(self):
        if not self.undo_stack:
            return None
        step = self.undo_stack.pop()
        self._apply(step, 0)
        self.redo_stack.append(step)
        return step

    def redo(self):
        if not self.redo_stack:
            return None
        step = self.redo_stack.pop()
        self._apply(step, 1)
        self.undo_stack.append(step)
        return step

    # ---- unsaved state ----------------------------------------------------------------- #
    def script_dirty(self):
        return self.container is not None and self.container.build() != self._saved_mc

    def changed_banks(self):
        """Positions of the banks whose bytes differ from the last load / save."""
        if self.container is None:
            return []
        old = getattr(self, "_saved_banks", [])
        return [i for i, b in enumerate(self.container.banks)
                if i >= len(old) or bytes(b.data) != old[i]]

    def dirty_locales(self):
        return sorted(loc for loc, a in self.arcs.items() if list(a.entries) != self._saved_text.get(loc))

    def em_dirty(self):
        return bool(self._em) and self._em.build() != self._saved_em

    def dirty_parts(self):
        out = ["rf3.mc"] if self.script_dirty() else []
        out += [f"rf3mc.{loc}" for loc in self.dirty_locales()]
        if self.em_dirty():
            out.append("em.bin")
        return out

    def mark_saved(self, script_=False, locales=(), em=False):
        if script_ and self.container is not None:
            self._saved_mc = self.container.build()
            self._saved_banks = [bytes(b.data) for b in self.container.banks]
        for loc in locales:
            if loc in self.arcs:
                self._saved_text[loc] = list(self.arcs[loc].entries)
        if em and self._em:
            self._saved_em = self._em.build()

    # ---- banks ------------------------------------------------------------------------- #
    def bank_pos(self, bank):
        """Container position of a bank object (what show_bank and the tree use)."""
        for i, b in enumerate(self.container.banks):
            if b is bank:
                return i
        return self.container.banks.index(bank)
