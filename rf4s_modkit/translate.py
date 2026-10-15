"""translate.py -- the state of dialogue lines in another language, and CSV for translators.

A line's state in a target language (`line_state`):

  missing       the line id is past the end of that language's rf3mc.<locale> (the game shows
                line 0 there, "Are you turning in for the night?")
  filler        the "[deu TBD]" placeholder the editor writes when a new line is padded into
                every language
  untranslated  the same text as the source language -- only for lines that are new or whose
                source text changed since the original game (the shipped German and French keep
                ~2,100 lines identical to English on purpose: names, set phrases). Without the
                original files every identical line counts.
  codes         the value slots (＠数字０＠, ＠キャラ０＠, ＠アイテム０＠ ...: numbers and names the
                script fills in) differ from the source line's -- the translation drops or adds
                one. Particles and the player-name tokens a language adds are not compared
                (Korean and Japanese use them freely; 0.3% of shipped CJK lines differ anyway).
  long          more rows than the box shows, or rows longer than the game's text ever is
                (scenelint.text_problems)

CSV (`export_csv` / `read_csv`): one row per line -- id, where it is used, source text, target
text, state -- UTF-8 with a BOM so spreadsheet programs read it; line breaks stay inside the cell.
"""
from __future__ import annotations

import csv
import io
import re

from . import scenelint, textlint

FILLER_RE = re.compile(r"^\[[a-z]{3} TBD\]$")
STATES = ("missing", "filler", "untranslated", "codes", "long")
STATE_TEXT = {"missing": "missing", "filler": "placeholder", "untranslated": "same as source",
              "codes": "value codes differ", "long": "too long"}


def _slots(text):
    return {(t.kind, t.slot) for t in textlint.tokens(text or "") if t.kind is not None}


def line_state(src, tgt, orig_src=None, orig_tgt=None, have_original=False):
    """[(state, message)] of one line: `src` / `tgt` = its text in the source / target
    language now (tgt None = the id is missing there); `orig_src` / `orig_tgt` = the same in
    the original game files (None = the line is new, or no originals). Empty = fine."""
    out = []
    if tgt is None:
        return [("missing", "not in this language: the game shows line 0 instead")]
    if FILLER_RE.match(tgt.strip()):
        return [("filler", "still the placeholder %s" % tgt.strip())]
    if src is not None and tgt == src and sum(ch.isalpha() for ch in src) >= 2:
        game_did_it = have_original and orig_src == src and orig_tgt == tgt
        if not game_did_it:
            out.append(("untranslated", "the same text as the source language"))
    if src is not None and _slots(src) != _slots(tgt):
        miss = sorted(_slots(src) - _slots(tgt))
        extra = sorted(_slots(tgt) - _slots(src))
        parts = []
        if miss:
            parts.append("drops %d value code(s) the source has" % len(miss))
        if extra:
            parts.append("has %d the source does not" % len(extra))
        out.append(("codes", "; ".join(parts)))
    for m in scenelint.text_problems(tgt):
        out.append(("long", m))
    return out


def scene_line_ids(stmts):
    """The dialogue and menu-option line ids of a scene, in address order, once each."""
    seen, out = set(), []
    for st in sorted(stmts, key=lambda s: s.pc):
        ids = [st.dialog_id] if st.mnem == "DIALOG" else (
            list(st.items or []) if st.mnem in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED") else [])
        for lid in ids:
            if lid is not None and lid not in seen:
                seen.add(lid)
                out.append(lid)
    return out


def rows(ids, src_text, tgt_text, where=None, orig_src_text=None, orig_tgt_text=None):
    """[(id, where, source, target, [(state, message)])] for `ids`: *_text are callables
    id -> text or None (None for a missing id); orig_* the original game's (None: no originals)."""
    have = orig_src_text is not None and orig_tgt_text is not None
    out = []
    for lid in ids:
        s, t = src_text(lid), tgt_text(lid)
        os_ = orig_src_text(lid) if have else None
        ot = orig_tgt_text(lid) if have else None
        out.append((lid, (where or {}).get(lid, ""), s, t, line_state(s, t, os_, ot, have)))
    return out


def export_csv(row_list, src_loc, tgt_loc):
    """CSV text (with a BOM) of rows(): id, used in, source, target, state."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["id", "used in", src_loc, tgt_loc, "state"])
    for lid, where, s, t, states in row_list:
        w.writerow([lid, where, s or "", "" if t is None else t,
                    "; ".join(STATE_TEXT[k] for k, _m in states)])
    return "﻿" + buf.getvalue()


def read_csv(text, tgt_loc=None):
    """{id: target text} from a CSV export_csv wrote (and a translator filled in). The target
    column is the one named `tgt_loc`, else the fourth. Rows with an empty target are skipped."""
    text = text.lstrip("﻿")
    rd = csv.reader(io.StringIO(text))
    head = next(rd, None)
    if not head or not head[0].strip().lower() == "id":
        raise ValueError("not a translation CSV: the first column must be 'id'")
    col = head.index(tgt_loc) if tgt_loc and tgt_loc in head else 3
    out = {}
    for n, row in enumerate(rd, 2):
        if not row or not row[0].strip():
            continue
        try:
            lid = int(row[0])
        except ValueError:
            raise ValueError("row %d: %r is not a line id" % (n, row[0]))
        if col < len(row) and row[col] != "":
            out[lid] = row[col].replace("\r\n", "\n")
    return out
