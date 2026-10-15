"""scenelint.py -- the engine-behaviour checks for a scene, in one place.

`scene_problems(buf, stmts, texts=None)` returns [(pc, level, message)], level 'error' (the
game breaks: hangs, never ends) or 'warning' (it misbehaves). Each check was run over every
shipped scene first and only kept where the game's own scripts do not trip it (2026-10-15):

  * the menu checks of script.choice_problems / choice_line_freezes / choice_empty_mask_problems
    and the SetDialogueSuppressed checks of script.dialogue_suppress_problems (in game);
  * a loop that waits for the PLAYER (their position, the stick) with no dialogue, menu or
    scripted player move in it: the player cannot move while any scene runs
    (Player_ProcessInput RF4S.exe+0x16E070 skips input while the high half of the player's
    state_flags is set), so it never ends -- seen in game 2026-10-14; 0 shipped scenes;
  * a loop with no waiting statement and no way out: it runs forever inside one frame and
    the game hangs; 0 shipped scenes;
  * a warp to a map id that has no map file; 0 shipped;
  * dialogue / menu line ids past the end of a language's rf3mc.<locale> (that language shows
    line 0, "Are you turning in for the night?"); 0 shipped;
  * lines with more rows than the box shows (3), or rows longer than the shipped text ever
    uses (80 visible characters, 30 full-width ones), per language.

Effects that outlive the scene (BlackScreen(1), SetMusicLock(1), FreezePlayer(0),
SetCalendarPauseFlag(1)) are NOT warned about: the shipped scenes hand them on to the next
scene or a warp on purpose (92 / 75 / 52 / 8 scenes), so a per-scene check only cries wolf.
"""
from __future__ import annotations

import sys
import unicodedata

from . import script

# statements that wait (the VM stays on them for at least a frame)
WAIT_OPS = {2, 3, 5, 92, 129, 130, 145, 337, 412}
INTERACTIVE = ("DIALOG", "PROMPT_CHOICE", "PROMPT_CHOICE_FORCED")
PLAYER_QUERIES = {213: "GetPlayerPosition", 442: "IsStickInputActive"}
PLAYER_MOVES = {142, 143, 144, 394, 99, 100, 101}       # scripted moves / teleports
ACTOR_POS_OPS = (135, 136)                              # GetActorPosition(0) = the player
WARP_OP = 332
BOX_ROWS = 3
ROW_LATIN = 80
ROW_WIDE = 30


def _waits(st):
    if st.op in WAIT_OPS or st.mnem in INTERACTIVE:
        return True
    if st.op < 0xFFF0:
        b = str((script.meta.table_row(st.op) or {}).get("blocking") or "")
        return b.startswith("yes")
    return False


def _sccs(by_pc, succ):
    """Strongly connected components with a cycle (loops), as lists of pcs."""
    index, low, onst, stack, out = {}, {}, set(), [], []
    counter = [0]
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 20000))

    def strong(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        onst.add(v)
        for w in succ.get(v, ()):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in onst:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                onst.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1 or v in succ.get(v, ()):
                out.append(sorted(comp))
    try:
        for v in by_pc:
            if v not in index:
                strong(v)
    finally:
        sys.setrecursionlimit(old)
    return out


def _actor_arg(buf, st):
    if not st.args:
        return None
    off = st.args[0]
    if off is not None and 0 <= off < len(buf) and buf[off] in (3, 4):
        return int.from_bytes(bytes(buf[off + 1:off + 5]), "little")
    v, ok = script.eval_expr(buf, off)
    return v if ok else None


def loop_problems(buf, stmts):
    by_pc, succ, _pred = script._graph(stmts)
    out = []
    for comp in _sccs(by_pc, succ):
        sts = [by_pc[p] for p in comp]
        inside = set(comp)
        exits = any(t not in inside for p in comp for t in succ.get(p, ()))
        has_call = any(s.mnem == "CALL" for s in sts)
        if not any(_waits(s) for s in sts) and not has_call and not exits:
            out.append((comp[0], "error", "This loop never waits and has no way out: it runs forever "
                        "within one frame and the game hangs"))
            continue
        if any(s.mnem in INTERACTIVE for s in sts):
            continue
        asks = [PLAYER_QUERIES[s.op] for s in sts if s.op in PLAYER_QUERIES]
        asks += ["GetActorPosition(player)" for s in sts if s.op in ACTOR_POS_OPS and _actor_arg(buf, s) == 0]
        moves = any(s.op in PLAYER_MOVES for s in sts)
        if asks and _waits_any(sts) and not moves:
            out.append((comp[0], "warning", "This loop waits for the player (%s), but the player can't "
                        "move or press anything while a scene runs, so it never ends and they stay stuck. "
                        "Let the scene end instead (e.g. start a fade and RET; see MAP_FIELD_25's night "
                        "stone boxes)" % ", ".join(sorted(set(asks)))))
    return out


def _waits_any(sts):
    return any(_waits(s) for s in sts)


def warp_problems(buf, stmts):
    from . import map_names
    out = []
    for st in stmts:
        if st.op != WARP_OP or not st.args:
            continue
        mid = _actor_arg(buf, st)
        if mid is not None and not map_names.map_file(mid):
            out.append((st.pc, "warning", "WarpToMap(%d, ...): there is no map with that id" % mid))
    return out


def _visible(row):
    from . import textlint
    toks = textlint.tokens(row)
    for t in sorted(toks, key=lambda t: -t.start):
        row = row[:t.start] + row[t.end:]
    return row


def text_problems(text, where="", locale=None):
    """Rows and row length of one dialogue line, as messages."""
    out = []
    pages = text.split("\x0c")
    for page in pages:
        rows = page.split("\n")
        while len(rows) > 1 and not rows[-1].strip():
            rows.pop()                            # a trailing line break adds no row on screen
        if len(rows) > BOX_ROWS:
            out.append("%s has %d rows; the box shows %d" % (where or "the line", len(rows), BOX_ROWS))
        for r in rows:
            v = _visible(r)
            wide = sum(1 for ch in v if unicodedata.east_asian_width(ch) in ("W", "F"))
            if wide and wide > ROW_WIDE:
                out.append("%s: a row has %d full-width characters (the game's text never goes past %d; "
                           "it may be cut off)" % (where or "the line", wide, ROW_WIDE))
            elif not wide and len(v) > ROW_LATIN:
                out.append("%s: a row has %d characters (the game's text never goes past %d; it may be "
                           "cut off)" % (where or "the line", len(v), ROW_LATIN))
    return out


def line_problems(stmts, texts):
    """`texts` = {locale: callable(line_id) -> text or None, plus its line count as
    texts[locale].count} -- each DIALOG / menu line in every language: missing ids, long rows."""
    out = []
    if not texts:
        return out
    for st in stmts:
        ids = [st.dialog_id] if st.mnem == "DIALOG" else (
            list(st.items or []) if st.mnem in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED") else [])
        for lid in ids:
            if lid is None:
                continue
            missing = [loc for loc, t in texts.items() if lid >= t.count]
            if missing:
                out.append((st.pc, "warning", "line #%d does not exist in rf3mc.%s: %s shows line 0 "
                            "instead (\"Are you turning in for the night?\")"
                            % (lid, "/".join(missing), "that language" if len(missing) == 1 else "those languages")))
            for loc, t in texts.items():
                if lid >= t.count:
                    continue
                s = t(lid)
                if s:
                    for m in text_problems(s, "line #%d (%s)" % (lid, loc)):
                        out.append((st.pc, "warning", m))
    return out


def scene_problems(buf, stmts, texts=None):
    """Every check on a scene's statements (sorted by pc): [(pc, level, message)]."""
    stmts = sorted(stmts, key=lambda s: s.pc)
    out = []
    out += [(pc, "warning", script.freeze_text(line, dp)) for pc, dp, line in script.choice_line_freezes(stmts)]
    out += script.dialogue_suppress_problems(buf, stmts)
    out += script.choice_empty_mask_problems(buf, stmts)
    out += loop_problems(buf, stmts)
    out += warp_problems(buf, stmts)
    out += line_problems(stmts, texts)
    seen, uniq = set(), []
    for p in out:
        if (p[0], p[2]) not in seen:
            seen.add((p[0], p[2]))
            uniq.append(p)
    return uniq


class TextSource:
    """A language's lines for line_problems: call with an id; .count = number of lines."""

    def __init__(self, fn, count):
        self._fn, self.count = fn, count

    def __call__(self, lid):
        try:
            return self._fn(lid)
        except Exception:  # noqa: BLE001
            return None
