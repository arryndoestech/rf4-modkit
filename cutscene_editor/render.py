"""Turning a scene into text: the readable "story" rows, the technical listing lines, the
Alt-hover explanation of a statement, and the Overview breakdown. Pure functions of the
document + bank + scene (no widgets), so the view, the tests and the tooltips share them."""
from __future__ import annotations

from collections import Counter, OrderedDict

from rf4s_modkit import script

from . import catalog

CONTROL_PROTOS = {
    "CALL": "CALL(target)", "JMP": "JMP(target)",
    "BR_Z": "BR_Z(cond_expr, target)", "BR_NZ": "BR_NZ(cond_expr, target)",
    "RET_NZ": "RET_NZ(cond_expr)", "EVAL": "EVAL(var_expr)",
    "FRAME": "FRAME(local_slots)", "RET": "RET()",
    "SWITCH": "SWITCH(sel, n, target[n])", "SWITCH_CLAMP": "SWITCH_CLAMP(sel, n, target[n])",
    "PROMPT_CHOICE_FORCED": "PROMPT_CHOICE_FORCED(n, target[n], items[n])",
    "PROMPT_CHOICE": "PROMPT_CHOICE(n, cancel_target, target[n], items[n])",
    "JMP_RAND": "JMP_RAND(n, target[n])", "JMP_WEIGHTED": "JMP_WEIGHTED(n, target[n], weight[n])",
}
FLAG_OPS = {318: "SetPackedGameFlag", 443: "SetGameFlagBit",
            444: "SetGameFlagBitIfCond", 445: "QueryGameFlagBit"}
CHOICE_OPS = ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED")
FIGURE_SPACE = " "             # as wide as a digit, so hex columns line up in any font
SPEAKER_COLORS = ("#ffb4a8", "#9fd8ff", "#c8b4ff", "#a8f0b8", "#ffd88a", "#ffa8d8",
                  "#8af0e8", "#e8c89a", "#b8c8ff", "#f0f08a")


class Row:
    """One line of the story view. `key` = (pc, option) for a selectable statement row
    (option = the choice option index on a choice's option rows, else None)."""
    __slots__ = ("segs", "key", "st")

    def __init__(self, segs, key=None, st=None):
        self.segs, self.key, self.st = segs, key, st


class SceneText:
    def __init__(self, doc, bank, scene):
        self.doc, self.bank, self.scene = doc, bank, scene
        self.labels = script.scene_labels(scene) if scene is not None else {}

    # ---- small helpers ------------------------------------------------------ #
    def live_only(self, line_id):
        """True for a line only the running game has (any document without that notion: no)."""
        f = getattr(self.doc, "live_only", None)
        return bool(f and f(line_id))

    def dlg(self, line_id):
        """A line's text as the editor shows it: colours / icons as \\red, \\btn(a) ..."""
        from rf4s_modkit import textesc
        t = self.doc.text(line_id)
        return textesc.to_edit(t) if t is not None else None

    def target(self, t):
        return self.labels.get(t, "0x%04x" % t) if t is not None else "?"

    def arg_strs(self, st):
        return script.stmt_arg_strs(self.bank.data, st) if st.args else []

    def expr_texts(self, st):
        out = []
        for e in st.expr_refs or ():
            if e is not None:
                out.append(script.disasm_expr(self.bank.data, e)[0])
        return out

    def emf_name(self, st):
        if st.op in script.EMF_ENTRY_OPS:
            ai = script.EMF_ENTRY_OPS[st.op]
            if ai < len(st.args):
                try:
                    return script.emf_entry_name(int(script.arg_repr(self.bank.data, st.args[ai])))
                except (ValueError, TypeError):
                    return None
        return None

    def choice_results(self, st):
        """script.choice_results for a choice of this scene: None (reg0 untouched: no mask
        before it) or [(option index, shown True / False / None)]."""
        try:
            stmts = list(self.scene.stmts.values())
            idx = next(i for i, s in enumerate(stmts) if s.pc == st.pc)
            return script.choice_results(self.bank.data, stmts, idx)
        except Exception:  # noqa: BLE001 -- display aid only
            return None

    @staticmethod
    def reg0_text(results, k):
        """' (reg0 = k)' for a masked menu's option k ('hidden' when the mask hides it)."""
        if results is None or k >= len(results):
            return ""
        return "  (reg0 = %d%s)" % (k, ", hidden" if results[k][1] is False else "")

    def choice_options(self, st):
        """[(option index, line id, target pc)] of a PROMPT_CHOICE(_FORCED)."""
        cancel = st.mnem == "PROMPT_CHOICE"
        out = []
        for k, item in enumerate(st.items or ()):
            ti = k + 1 if cancel else k
            out.append((k, item, st.code_targets[ti] if ti < len(st.code_targets) else None))
        return out

    # ---- the technical listing line (the old disassembly) ------------------------ #
    def code_line(self, st):
        head = f"{st.pc:04x}:  "
        if st.mnem == "DIALOG":
            t = self.dlg(st.dialog_id)
            if t is None:
                return f"{head}DIALOG #{st.dialog_id}  [no text in this locale]"
            live = "  [running game only]" if self.live_only(st.dialog_id) else ""
            return f"{head}DIALOG #{st.dialog_id}  \"{t.replace(chr(10), ' / ')[:70]}\"{live}"
        if st.op < 0xFFF0:
            args = self.arg_strs(st)
            nm = self.emf_name(st)
            body = script.render_action(st.op, args) or f"{script.opcode_mnemonic(st.op)}({', '.join(args)})"
            return f"{head}{body}" + (f"   ; {nm}" if nm else "")
        exprs = self.expr_texts(st)
        cond = f"  {'val' if st.mnem == 'EVAL' else 'cond'}=({', '.join(exprs)})" if exprs else ""
        if st.mnem in CHOICE_OPS and st.items:
            parts = []
            opts = self.choice_options(st)
            if (st.mnem == "PROMPT_CHOICE" and st.code_targets and opts
                    and st.code_targets[0] != opts[-1][2]):   # the never-taken slot, if unusual
                parts.append(f"CANCEL->{self.target(st.code_targets[0])}")
            res = self.choice_results(st)
            for k, item, tgt in self.choice_options(st):
                txt = (self.dlg(item) or "").replace("\n", " / ")
                parts.append((f'"{txt[:60]}"' if txt else f"#{item}") + f"->{self.target(tgt)}"
                             + self.reg0_text(res, k).replace("  ", " "))
            return f"{head}{st.mnem}{cond}  " + " | ".join(parts)
        tg = ", ".join(self.target(t) for t in st.code_targets if t is not None)
        extra = f" {st.items[0]}" if st.mnem == "FRAME" and st.items else ""
        return f"{head}{st.mnem}{extra}{cond}{(' -> ' + tg) if tg else ''}"

    # ---- who speaks each line ---------------------------------------------------------- #
    def line_speakers(self):
        """{DIALOG pc: display name} for the lines whose speaker is certain (set on every
        path to the line, through CALLs -- script.dialog_speakers); other lines have none."""
        key = (id(self.scene), id(self.bank))
        if getattr(self, "_spk_key", None) != key:
            try:
                raw = script.dialog_speakers(self.scene, self.bank)
            except Exception:  # noqa: BLE001 - a display aid only
                raw = {}
            mc = script.portrait_speaker_tag(16) or "MC"
            self._spk = {pc: (mc if nm == "player" else nm) for pc, nm in raw.items()}
            self._spk_key = key
        return self._spk

    def speaker_colour(self, name):
        names = [script.meta.speaker_name(i) for i in range(len(script.meta.PORTRAIT_SPEAKERS))]
        if name in (script.portrait_speaker_tag(16), "MC", "player"):
            return SPEAKER_COLORS[0]
        if name in names:
            return SPEAKER_COLORS[names.index(name) % len(SPEAKER_COLORS)]
        return "#d8d8d8"                        # name plates (SetSpeakerVoice)

    def nameplate_of(self, st):
        """(name, blip label) of a SetSpeakerVoice (op 10) statement."""
        args = self.arg_strs(st)
        name = blip = None
        try:
            name = script.meta.enum_arg_label(10, 0, int(args[0], 0)) if args else None
        except (ValueError, TypeError):
            pass
        try:
            b = int(args[1], 0) if len(args) > 1 else None
            blip = script.meta.enum_arg_label(10, 1, min(b, 4)) if b is not None else None
        except (ValueError, TypeError):
            pass
        return name or (args[0] if args else "?"), blip

    # ---- the story view ------------------------------------------------------------ #
    def speaker_of(self, st):
        """(name, side, colour) of a SetSpeaker op."""
        slot, par = script.portrait_speaker_slot(st.op)
        name = ("MC" if slot == 0 else script.portrait_speaker_name(st.op)) or "?"
        return name, ("right" if par else "left"), SPEAKER_COLORS[slot % len(SPEAKER_COLORS)]

    def speaker_mood(self, st):
        """Face / emote / voice words of a SetSpeaker's args (as render_action shows them)."""
        args = self.arg_strs(st)
        words = []
        for i, v in enumerate(args[:3]):
            try:
                iv = int(v, 0)
            except (ValueError, TypeError):
                continue
            if i == 0:
                continue                           # the face frame number
            if iv >= 0x1000000:
                continue                           # a target handle
            if iv >= 0x1F0:
                words.append("voice %d" % iv)
            elif iv:
                words.append(script.portrait_emote_name(iv) or "emote %d" % iv)
        return words

    @staticmethod
    def raw_op(st):
        """'0x005  ' -- the raw opcode the statement is stored as, in hex (control ops as
        their 0xFFFx token), padded to one width, for the 'opcodes' toggle."""
        s = "0x%04X" % st.op if st.op >= 0xFFF0 else "0x%03X" % st.op
        return s + FIGURE_SPACE * (8 - len(s))         # digit-wide: lines up in proportional text too

    def file_offset_seg(self, pc):
        """The statement's byte offset in rf3.mc (the bank's start + pc; it follows edits, so
        it is where the statement will be in the saved file)."""
        return ("%06x  " % (self.bank.file_off + pc), "addr")

    OPERAND_TAGS = 6                    # colours the operands cycle through (view.py: opd0..5)

    OPERAND_PAD_MAX = 48                # the operand column is padded to its widest row, up to this

    def operand_segs(self, st):
        """The statement's operands in hex, one group per operand and one colour each, for the
        column after the opcode: ['170500 ', '021c00000000 ']. [] when it has none (RET) or
        there is no bank to read them from."""
        if self.bank is None:
            return []
        return [(bytes(data).hex() + FIGURE_SPACE, "opd%d" % (i % self.OPERAND_TAGS))
                for i, (_label, data) in enumerate(script.statement_operands(self.bank.data, st))]

    def operand_legend(self, st):
        """'arg 0 = 17 05 00' lines naming each operand (the Alt-hover explanation); [] without
        a bank (a statement explained on its own)."""
        if self.bank is None:
            return []
        return ["%s = %s" % (label, " ".join("%02x" % b for b in data) or "(none)")
                for label, data in script.statement_operands(self.bank.data, st)]

    @classmethod
    def add_operands(cls, rows, segs_of):
        """Put each statement's operands into its first row (key (pc, None)) right after the
        leading address / opcode columns, padded to one width (up to OPERAND_PAD_MAX) so the
        statement text keeps lining up."""
        done, picked = set(), []
        for r in rows:
            k = r.key
            if r.st is not None and k is not None and k[1] is None and k[0] not in done:
                done.add(k[0])
                picked.append((r, segs_of(r.st)))
        width = min(max((sum(len(s) for s, _t in segs) for _r, segs in picked), default=0),
                    cls.OPERAND_PAD_MAX)
        for r, segs in picked:
            segs = list(segs)
            used = sum(len(s) for s, _t in segs)
            if used < width:                    # digit-wide spaces, in the opcode's font
                segs.append((FIGURE_SPACE * (width - used), "opc"))
            tags = [t for _s, t in r.segs]
            if "opc" in tags:                   # right after the opcode: "0x005  op1 op2 ..."
                at = len(tags) - tags[::-1].index("opc")
            else:                               # else just before the statement itself
                at = next((i for i, t in enumerate(tags) if t not in ("addr", "lbl")), len(tags))
            r.segs = list(r.segs[:at]) + segs + list(r.segs[at:])
        return rows

    def xref_note(self, pc):
        """'  · 3 xrefs' for a label: how many statements of the bank lead to `pc`."""
        return "  · %d xref%s" % (self.xref_count(pc), "" if self.xref_count(pc) == 1 else "s")

    def xref_count(self, pc):
        from .catalog import xref_counts
        return xref_counts(self.bank).get(pc, 0) if self.bank is not None else 0

    def xref_tag(self, pc):
        """The note's tag: a link (click: the one caller, or the Xrefs window) when anything
        leads there, else dimmed text."""
        return "xreflink" if self.xref_count(pc) else "dim"

    def story_rows(self, show_addr=False, show_ops=False, show_file_off=False, show_operands=False,
                   show_xrefs=False):
        sc = self.scene
        rows = []

        def addr(pc, st=None, cont=False):
            segs = [self.file_offset_seg(pc)] if show_file_off else []
            if show_addr:
                segs.append(("%04x  " % pc, "addr"))
            if show_ops and st is not None:
                segs.append((FIGURE_SPACE * 8, "opc") if cont else (self.raw_op(st), "opc"))
            return segs

        # when it plays: trigger entries pointing at the scene + Event Manager gates
        trig = self.triggers()
        for t in trig:
            rows.append(Row([("▶ plays on  ", "hdr"), (t, "hdrv")]))
        for g in (x for x in self.em_triggers() if x["kind"] == "gate"):
            cond = self.em_cond_text(g["entry_obj"], "b" if g["op"] == 372 else "a")
            rows.append(Row([("▶ %s %s  " % (g["verb"], g["name"]), "hdr"), (cond or "(condition unavailable)", "hdrv")]))
        if not sc.ok:
            rows.append(Row([("⚠ partial disassembly: %s" % sc.error, "warn")]))
        if rows:
            rows.append(Row([("", None)]))
        lin = script.linearize(sc)
        shown = {pc for pc, _ in lin}
        rest = [(pc, st) for pc, st in sc.stmts.items() if pc not in shown]
        speaker = None
        for part, seq in (("main", lin), ("rest", rest)):
            if part == "rest" and seq:
                rows.append(Row([("", None)]))
                rows.append(Row([("── other branches / paths ──", "hdr")]))
            for k, (pc, st) in enumerate(seq):
                if pc in self.labels:                   # selectable: add beats at the label
                    rows.append(Row([("%s:" % self.labels[pc], "lbl")]
                                    + ([("  · ", "dim"), (self.xref_note(pc)[len("  · "):], self.xref_tag(pc))]
                                       if show_xrefs else []),
                                    (pc, "label"), st))
                speaker = self._story_stmt(rows, pc, st, addr, speaker)
                # each statement is shown once, so a path that runs on into one shown
                # elsewhere ends the way a path reads: a shared RET as 'return', other
                # shared code as 'go to L2' (what a JMP there would say)
                to = self.path_end(sc, pc, st, seq[k + 1][0] if k + 1 < len(seq) else None)
                if to is not None:
                    tst = sc.stmts.get(to)
                    end = ("return" if tst is not None and tst.mnem == "RET"
                           else "go to %s" % self.target(to))
                    rows.append(Row(addr(to, tst) + [("    ", None), (end, "flow")]))
        if show_operands:
            self.add_operands(rows, self.operand_segs)
        return rows

    @staticmethod
    def path_end(sc, pc, st, nxt):
        """The views show the main path, then the other branches, each statement once. When
        `st` runs on (falls through) to a statement that is not `nxt`, the row shown after it,
        return where it goes (past any JMPs, which the main path reads inline) -- the view then
        ends the path there; else None (it runs into `nxt`, branches, or ends the path)."""
        if st.terminator or not st.falls_through or st.mnem == "JMP":
            return None
        raw = to = pc + st.size
        seen = set()
        while to in sc.stmts and sc.stmts[to].mnem == "JMP" and to not in seen:
            seen.add(to)
            to = (sc.stmts[to].code_targets or [None])[0]
        return None if nxt in (raw, to) else to

    def _story_stmt(self, rows, pc, st, addr, speaker):
        key = (pc, None)
        ind = [("    ", None)]
        if st.mnem == "DIALOG":
            txt = self.dlg(st.dialog_id)
            who = self.line_speakers().get(pc)       # only a CERTAIN speaker is shown
            body = [("“%s”" % txt.replace("\n", " ⏎ "), "dlg")] if txt is not None else \
                   [("#%d  [no text in this locale]" % st.dialog_id, "warn")]
            if txt is not None and self.live_only(st.dialog_id):
                body.append(("  [running game only]", "warn"))
            head =[(who + ": ", ("spk", self.speaker_colour(who)))] if who else []
            rows.append(Row(addr(pc, st) + ind + head + body, key, st))
            return speaker
        if st.op == 10:                                  # SetSpeakerVoice: a name plate
            name, blip = self.nameplate_of(st)
            rows.append(Row(addr(pc, st) + ind + [("🗨 ", "dim"), (name, ("cue", self.speaker_colour(name))),
                                               ("  · name plate%s" % ((" · " + blip) if blip else ""), "dim")],
                            key, st))
            return (name, "plate", self.speaker_colour(name))
        if script.is_portrait_op(st.op):
            name, side, col = self.speaker_of(st)
            mood = self.speaker_mood(st)
            rows.append(Row(addr(pc, st) + ind + [("🗨 ", "dim"), (name, ("cue", col)),
                                               ("  · %s%s" % (side, (" · " + ", ".join(mood)) if mood else ""), "dim")],
                            key, st))
            return (name, side, col)
        if st.op == 92:                                  # EndDialogue closes the speaker
            rows.append(Row(addr(pc, st) + ind + [("▸ end of dialogue", "act")], key, st))
            return None
        if st.op < 0xFFF0:
            args = self.arg_strs(st)
            body = script.render_action(st.op, args) or f"{script.opcode_mnemonic(st.op)}({', '.join(args)})"
            nm = self.emf_name(st)
            rows.append(Row(addr(pc, st) + ind + [("▸ " + body, "act")] + ([("   ; " + nm, "emf")] if nm else []),
                            key, st))
            return speaker
        exprs = self.expr_texts(st)
        cond = ", ".join(exprs)
        m = st.mnem
        tg = [self.target(t) for t in st.code_targets if t is not None]
        if m == "FRAME":
            n = (st.items or [0])[0]
            segs = [("· reserve %d stack word%s for expressions" % (n, "" if n == 1 else "s"), "dim")]
        elif m == "BR_Z":
            segs = [("if not ", "flow"), ("(%s)" % cond, "cond"), (" → go to %s" % ", ".join(tg), "flow")]
        elif m == "BR_NZ":
            segs = [("if ", "flow"), ("(%s)" % cond, "cond"), (" → go to %s" % ", ".join(tg), "flow")]
        elif m == "JMP":
            segs = [("go to %s" % ", ".join(tg), "flow")]
        elif m == "CALL":
            segs = [("call %s" % ", ".join(tg), "flow")]
        elif m == "RET":
            segs = [("return", "flow")]
        elif m == "EVAL":
            segs = [("set ", "flow"), (cond, "cond")]
        elif m in CHOICE_OPS:
            head = "choice"
            opts = self.choice_options(st)
            if (m == "PROMPT_CHOICE" and st.code_targets and opts
                    and st.code_targets[0] != opts[-1][2]):     # the never-taken slot, if unusual
                head += " (cancel slot → %s, never taken)" % self.target(st.code_targets[0])
            res = self.choice_results(st)
            if res is not None:
                head += " — the pick goes to reg0"
            rows.append(Row(addr(pc, st) + ind + [(head + ":", "flow")], key, st))
            for k, item, tgt in opts:
                txt = self.dlg(item)
                rows.append(Row(addr(pc, st, cont=True) + ind + [("      ▹ ", "flow"),
                                                   (("“%s”" % txt.replace("\n", " ⏎ ")) if txt is not None else "#%d" % item, "dlg"),
                                                   ("  → %s%s" % (self.target(tgt), self.reg0_text(res, k)), "flow")],
                                (pc, k), st))
            return speaker
        elif m in ("SWITCH", "SWITCH_CLAMP"):         # one line per case, like a menu's options
            rows.append(Row(addr(pc, st) + ind + [("switch ", "flow"), ("(%s)" % cond, "cond"),
                                                   (":", "flow")], key, st))
            n = len(tg)
            for k, t in enumerate(tg):
                val = ("≥ %d" if m == "SWITCH_CLAMP" and k == n - 1 else "= %d") % k
                rows.append(Row(addr(pc, st, cont=True) + ind + [("      %-5s → %s" % (val, t), "flow")],
                                (pc, k), st))
            if m == "SWITCH":
                rows.append(Row(addr(pc, st, cont=True) + ind + [("      other values: carry on below", "dim")],
                                (pc, n), st))
            return speaker
        elif m == "JMP_WEIGHTED":
            w = st.items or []
            segs = [("random: " + ", ".join("%s → %s" % (w[k] if k < len(w) else "?", t)
                                            for k, t in enumerate(tg)), "flow")]
        else:
            segs = [(self.code_line(st)[7:], "flow")]
        rows.append(Row(addr(pc, st) + ind + segs, key, st))
        return speaker

    # ---- when the scene plays ------------------------------------------------------ #
    def triggers(self):
        """'type 7 MapEnterScene (keys)' for each type-table entry that starts the scene."""
        out = []
        try:
            tt = self.bank.type_table_full()
        except Exception:
            return out
        for t in tt:
            try:
                recs = self.bank.entry_records(t)
            except Exception:
                continue
            for r in recs:
                if r.event_id == self.scene.entry_pc:
                    out.append("%s  #%d  %s" % (catalog.type_label(t), r.index, catalog.describe_keys(t, r.subs)))
        return out

    def em_triggers(self):
        """The scene's Event Manager bridge ops: {pc, op, entry, name, entry_obj, kind, verb};
        kind 'gate' (EvalCondA/B feeding a branch), 'set' (op 444) or 'run' (373/374)."""
        em = self.doc.em
        stmts = sorted(self.scene.stmts.items())
        out = []
        for i, (pc, st) in enumerate(stmts):
            if st.op not in script.EMF_ENTRY_OPS:
                continue
            ai = script.EMF_ENTRY_OPS[st.op]
            eid = None
            if ai < len(st.args):
                try:
                    eid = int(script.arg_repr(self.bank.data, st.args[ai]))
                except (ValueError, TypeError):
                    eid = None
            name = (em.names.entry_name(eid) if (em and eid is not None) else None) or "#%s" % eid
            e = em.entries[eid] if (em and eid is not None and 0 <= eid < len(em.entries)) else None
            nxt = stmts[i + 1][1] if i + 1 < len(stmts) else None
            gate = st.op in (371, 372) and nxt is not None and nxt.mnem in ("BR_Z", "BR_NZ")
            kind = "gate" if gate else ("set" if st.op == 444 else "run")
            verb = ("plays when" if nxt.mnem == "BR_Z" else "plays unless") if gate else "when"
            out.append({"pc": pc, "op": st.op, "entry": eid, "name": name, "entry_obj": e,
                        "kind": kind, "verb": verb})
        return out

    def em_cond_text(self, e, which="a"):
        em = self.doc.em
        if not (em and e):
            return ""
        slots = e.cond_b if which == "b" else e.cond_a
        if not slots:
            return ""
        return "  ".join(ln.strip() for ln in e.pretty_condition(em.names, which, "").splitlines())

    def emf_hint(self, st):
        """Decoded summary of the Event Manager entry a bridge op names."""
        em = self.doc.em
        if st.op not in script.EMF_ENTRY_OPS or em is None:
            return None
        ai = script.EMF_ENTRY_OPS[st.op]
        if ai >= len(st.args):
            return None
        try:
            e = em.entries[int(script.arg_repr(self.bank.data, st.args[ai]))]
        except (ValueError, IndexError, TypeError):
            return None
        parts = [f"Event Manager entry {e.idx} {e.name}"]
        which = "b" if st.op == 372 else "a"
        if st.op in (371, 372, 444) and (e.cond_b if which == "b" else e.cond_a):
            cond = e.pretty_condition(em.names, which, "").replace("\n", " ")
            parts.append("condition: " + (cond[:200] + "…" if len(cond) > 200 else cond))
        acts = e.actions if st.op == 373 else e.alt_actions if st.op == 374 else None
        if acts:
            parts.append("does: " + "; ".join(a.pretty(em.names) for a in acts[:4]) + ("; …" if len(acts) > 4 else ""))
        return "\n".join(parts)

    # ---- the Alt-hover explanation -------------------------------------------------- #
    def expr_vars(self, expr_off):
        """[(name, bit offset, width, packed)] for each emdeb variable in an expression."""
        doc = self.doc
        if doc.container is None or doc.emf_vars is None:
            return []
        d = self.bank.data
        n, p, out = len(d), expr_off, []
        for _ in range(64):
            if not (0 <= p < n) or d[p] == 0:
                break
            t = d[p]
            if t == 0x02:
                enc = int.from_bytes(d[p + 1:p + 5], "little")
                bo, w, _s = doc.container.unpack_var(enc)
                v = doc.emf_vars.by_offset(bo)
                out.append((v.name if v else "var:0x%X" % enc, bo, w, enc))
                p += 5
            elif t == 0x01:
                p += 5
            elif t in (0x17, 0x18):
                p += 2
            elif t in (0x19, 0x1A, 0x06):
                p += 3
            elif 0x07 <= t <= 0x10 or t in (0x14, 0x15, 0x16) or t >= 0x80:
                p += 1
            else:
                break
        return out

    def explain(self, st):
        """Full explanation of a statement: prototype, every argument decoded, what it does."""
        if st.mnem == "DIALOG":
            t = (self.dlg(st.dialog_id) or "").strip()
            out = ["DIALOG(line id)", "",
                   "Shows one dialogue line and waits for the player. The speaker and portrait "
                   "come from the last SetSpeaker before it.", "",
                   "  line id = %d  (rf3mc.<locale>)" % st.dialog_id]
            if t:
                out.append('    "%s"' % t.replace("\n", " "))
            out += ["", "operand (hex, as stored): " + "; ".join(self.operand_legend(st))]
            return "\n".join(out)
        if st.op >= 0xFFF0:
            out = [CONTROL_PROTOS.get(st.mnem, st.mnem + "()"), "", script.control_tooltip(st.mnem) or ""]
            legend = []
            for e in st.expr_refs or ():
                if e is None:
                    continue
                out += ["", "%s (expr @0x%04x):" % ("value" if st.mnem == "EVAL" else "condition", e),
                        "    " + script.disasm_expr(self.bank.data, e)[0]]
                legend += self.expr_vars(e)
            if legend:
                out += ["", "variables:"]
                for name, bo, w, enc in legend:
                    out.append("    %s — bit %d, %s (packed 0x%X)" % (name, bo, "flag" if w == 1 else "%d-bit" % w, enc))
            if st.mnem in CHOICE_OPS and st.items:
                out += ["", "options:"]
                opts = self.choice_options(st)
                if (st.mnem == "PROMPT_CHOICE" and st.code_targets and opts
                        and st.code_targets[0] != opts[-1][2]):
                    out.append("    CANCEL -> %s (never taken)" % self.target(st.code_targets[0]))
                for _k, item, tgt in self.choice_options(st):
                    txt = (self.dlg(item) or "").replace("\n", " / ")
                    out.append("    #%d %s-> %s" % (item, ('"%s" ' % txt[:44]) if txt else "", self.target(tgt)))
            tg = [self.target(t) for t in st.code_targets if t is not None]
            if tg:
                out += ["", "targets: " + ", ".join(tg)]
            leg = self.operand_legend(st)
            if leg:
                out += ["", "operands (hex, as stored):"] + ["    " + x for x in leg]
            return "\n".join(out)
        op = st.op
        from .argspec import clean_help
        desc = script.opcode_describe(op) or ""
        out = [script.opcode_prototype(op), "", clean_help(desc) or desc]
        sp = script.portrait_speaker_slot(op)
        if sp is not None:
            out.append("Speaker: %s   Side: %s" % (script.portrait_speaker_name(op), "left" if sp[1] == 0 else "right"))
        out += ["", "Arguments:"]
        vals = self.arg_strs(st)
        if not vals:
            out.append("  (none)")
        for i, v in enumerate(vals):
            nm, hint = self.arg_name(op, i, v)
            line = "  %s = %s" % (nm, v)
            lbl = self.value_label(op, i, v, nm)
            if lbl:
                line += "  (%s)" % lbl
            out.append(line)
            for extra in self.arg_notes(st, i):
                out.append("      " + extra)
            if hint:
                out.append("      — %s" % hint)
        nm = self.emf_name(st)
        if nm:
            out += ["", "Event Manager entry: %s" % nm]
        out += ["", "op %d · %s" % (op, script.opcode_name(op))]
        leg = self.operand_legend(st)
        if leg:
            out += ["", "Operands (hex, as stored):"] + ["  " + x for x in leg]
        return "\n".join(out)

    def arg_name(self, op, i, value=None):
        """(name, hint) of argument i. SetSpeaker args after the face are named by value:
        a target handle, a voice id or an emote."""
        names = script.opcode_arg_names(op)
        nm = names[i] if i < len(names) else "arg%d" % i
        hint = script.opcode_arg_hint(op, i)
        if script.portrait_speaker_slot(op) is not None and i >= 1 and value is not None:
            try:
                iv = int(value, 0) if isinstance(value, str) else int(value)
            except ValueError:
                iv = None
            if iv is not None:
                if iv >= 0x1000000:
                    nm, hint = "target", script.opcode_arg_hint_by_name("target")
                elif iv >= 0x1F0:
                    nm, hint = "voice sfx id", "plays a voice line instead of an emote"
                elif iv:
                    nm, hint = "emote/mood", script.opcode_arg_hint_by_name("emote/mood")
        return nm, hint

    @staticmethod
    def value_label(op, i, v, nm=""):
        try:
            iv = int(v, 0) if isinstance(v, str) else int(v)
        except (ValueError, TypeError):
            return None
        if nm.lower() == "emote/mood":
            return script.portrait_emote_name(iv)
        return script.enum_arg_label(op, i, iv)

    def arg_notes(self, st, i):
        out = []
        if i < len(st.args) and st.args[i] is not None:
            leaf = script.leaf_tooltip(self.bank.data, st.args[i], st.op, i)
            if leaf:
                out.append("= %s" % leaf)
            fnote = script.flag_arg_note(self.bank.data, st.args[i], st.op, i)
            if fnote:
                out.append("flag: %s" % fnote)
        return out

    # ---- the Overview tab -------------------------------------------------------------- #
    def problems(self):
        """[(pc, level, message)]: every engine-behaviour check on the scene
        (rf4s_modkit.scenelint), its lines checked in every language the source has."""
        from rf4s_modkit import scenelint
        from .catalog import LOCALES
        texts = {}
        for loc in LOCALES:
            arc = self.doc.archive(loc) if hasattr(self.doc, "archive") else None
            if arc is not None:
                texts[loc] = scenelint.TextSource(lambda i, a=arc: a.text(i), len(arc))
        stmts = self.scene.stmts
        stmts = list(stmts.values()) if isinstance(stmts, dict) else list(stmts)
        try:
            return scenelint.scene_problems(self.bank.data, stmts, texts)
        except Exception:  # noqa: BLE001 -- the checks never block viewing a scene
            return []

    def overview(self):
        """[(text, tag)] segments: checks, speakers, transcript, Event Manager triggers, flags
        written, control-flow shape."""
        sc = self.scene
        out = []

        def put(s, tag=None):
            out.append((s, tag))
        typ = "discovered" if sc.action_type < 0 else catalog.type_label(sc.action_type)
        put("%s · scene @0x%04x · %s\n" % (catalog.bank_title(self.bank), sc.entry_pc, typ), "h1")
        put("%d statements%s\n\n" % (len(sc.stmts), "" if sc.ok else "   [PARTIAL: %s]" % sc.error), "k")
        probs = self.problems()
        if probs:
            put("Checks (%d)\n" % len(probs), "h")
            for pc, lvl, msg in probs:
                put("  @0x%04x  %s: %s\n" % (pc, lvl, msg), "warn")
            put("\n")
        stmts = list(sc.stmts.items())
        spk = OrderedDict()
        for _pc, st in stmts:
            if script.is_portrait_op(st.op):
                name, side, _c = self.speaker_of(st)
                key = "%s (%s)" % (name, side)
                spk[key] = spk.get(key, 0) + 1
            elif st.op == 10:
                key = "%s (name plate)" % self.nameplate_of(st)[0]
                spk[key] = spk.get(key, 0) + 1
        if spk:
            put("Speakers\n", "h")
            for k, n in spk.items():
                put("  %-24s ×%d\n" % (k, n), "k")
            put("\n")
        lines = [(pc, st.dialog_id) for pc, st in stmts if st.mnem == "DIALOG"]
        if lines:
            put("Dialogue (%d lines)\n" % len(lines), "h")
            cur = object()
            who = self.line_speakers()
            for pc, lid in lines:
                sp = who.get(pc)
                if sp != cur:
                    cur = sp
                    put("  %s:\n" % (sp or "(no speaker set in this scene)"), "k")
                put("    #%-6d %s\n" % (lid, (self.dlg(lid) or "").replace("\n", " ")[:110]), "dlg")
            put("\n")
        trigs = self.em_triggers()
        if trigs:
            put("Event Manager (%d)\n" % len(trigs), "h")
            label = {"gate": "gate: plays when", "set": "set flag if", "run": "runs actions of"}
            em = self.doc.em
            for t in trigs:
                lab = "runs alt actions of" if (t["kind"] == "run" and t["op"] == 374) else label[t["kind"]]
                put("  @0x%04x  %s %s\n" % (t["pc"], lab, t["name"]), "emf")
                e = t["entry_obj"]
                if e is None:
                    continue
                if t["kind"] in ("gate", "set"):
                    cond = self.em_cond_text(e, "b" if t["op"] == 372 else "a")
                    if cond:
                        put("      %s\n" % cond[:220], "k")
                else:
                    for a in ((e.actions if t["op"] == 373 else e.alt_actions) or [])[:6]:
                        put("      do: %s\n" % a.pretty(em.names), "flag")
            put("\n")
        flagops = [(pc, st) for pc, st in stmts if st.op in FLAG_OPS]
        varops = [(pc, st) for pc, st in stmts
                  if "VarArray" in script.opcode_name(st.op) and "Write" in script.opcode_name(st.op)]
        if flagops or varops:
            put("Flags / variables written\n", "h")
            for pc, st in flagops:
                put("  @0x%04x %-20s (%s)\n" % (pc, FLAG_OPS[st.op], ", ".join(self.arg_strs(st))), "flag")
            for pc, st in varops:
                put("  @0x%04x %-20s (%s)\n" % (pc, script.opcode_mnemonic(st.op), ", ".join(self.arg_strs(st))), "flag")
            put("\n")
        cf = Counter()
        for _pc, st in stmts:
            if st.op >= 0xFFF0:
                cf[st.mnem] += 1
        if cf:
            put("Control flow\n", "h")
            put("  " + "  ".join("%s ×%d" % kv for kv in sorted(cf.items())) + "\n", "k")
        return out


def scene_preview(doc, sc):
    """A one-line preview of a scene for lists: its first dialogue line, else a summary."""
    for st in sc.stmts.values():
        if st.mnem == "DIALOG":
            t = doc.text(st.dialog_id)
            if t:
                return t.splitlines()[0][:60]
    return script.scene_summary(sc)
