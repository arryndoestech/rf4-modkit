"""script_explorer.py -- GUI for browsing and editing RF4 cutscene / event scripts.

RF4's cutscenes are compiled Script-VM bytecode in `rom:/script/rf3.mc` (a MYCF
container), with dialogue text in the per-locale `rf3mc.<locale>` TEXT archives.
This window lets you:

  * search scenes by what they say, or browse a bank,
  * read a scene's disassembly with dialogue resolved inline,
  * click any statement to edit it:
      - DIALOG -> rewrite the line's text, or retarget it to a different line id,
      - SetSpeaker -> change who speaks and which side the portrait sits on,
      - action -> change its arguments (named + tooltipped per op),
  * insert new statements after the selection in full listing syntax (actions by
    name, DIALOG #id, BR_Z/STORE with FLG_/REG_ names, labels, choices...) or
    delete a statement (both byte-safe: a trampoline jump carries the rewrite),
  * Source tab: the whole scene as an editable, re-assemblable listing
    (rf4s_modkit.scriptasm) -- Check it, then Assemble & replace the scene,
  * Entries tab: the bank's type table (its scene TRIGGERS): mint a brand-new
    scene under an action type with its matcher keys (or from a catalogue
    recipe; a yellow note says when the new entry would shadow / replace the
    bank's existing scene of that type), re-key or remove one,
  * Event Manager window: em.bin entries -- besides the in-place value edits,
    add / remove whole conditions and actions from text
    (`Hour >= 6 AND (12 > Hour OR FLG_RAINBOW == 1)`, `FLG_X = 1`, `CALL EV_FOO`),
  * 'Add line' can pad every other rf3mc.<locale> with the new line, so its id
    is in range in every locale,
  * save the edited rf3.mc / rf3mc.<locale>(s) as loose files (or install them).

Same-length edits round-trip byte-perfectly (see rf4s_modkit.script). Structural
edits append to the bank and repoint (nothing existing moves).

--- Script-VM quick reference (what the ops mean; engine-verified, 2026-08) ------

  Pacing      Wait (op 2) pauses in 1/12000 s units: 200 units = 1 frame, so
              6000 = 0.5 s, 12000 = 1 s. Fades (op 334/335) use the SAME literals
              at /100 -> 6000 = 1 s as a fade. Don't normalise one to the other.
  Speakers    A SetSpeaker* op (16..75) names the portrait + side for the NEXT
              lines and PERSISTS until the next speaker op or EndDialogue (92);
              its small args (< 0x1F0) pick the portrait FACE FRAME (emotion),
              larger args are VOICE ids fired with the line. SetSpeakerVoice
              (op 10) = name plate WITHOUT a portrait (off-screen voices).
  Camera      SetCameraTarget (190) pans at arg2/100 tiles per frame; pair with
              WaitCameraAtMark (195) to hold the scene until the pan lands.
              SetCameraPosition (186) with snap=1 is the instant cut.
  Actors      EventSpawnNpc (153) takes (char id, EVENT KEY, x, y, deg): the KEY
              is the scene-local handle every later move/face/anim/query op
              addresses. Facing args are DEGREES throughout (x181 internally).
              Movers pair with their arrival barriers (160->164, 133->129).
  Choices     PROMPT_CHOICE branches on the picked row. reg0 gets the picked
              option's ORIGINAL index only when the prompt was STAGED (visibility
              mask 610/612 or ArmChoiceOption 615 + DIALOG queue); an unstaged
              prompt leaves reg0 untouched -- scenes park query results there
              across Yes/No prompts on purpose.
  Registers   reg0..reg9 are flat scratch (SetRegisters 628, query ops write
              them, SWITCH_EQ dispatches on them); NOT saved across CALL.

Ctrl-hover any statement for its per-op tooltip (mnemonic, argument names, and
the verified behaviour notes come from rf4s_modkit.opcode_meta).

Run standalone:  python script_explorer.py
Or open it from rf4mod_gui's "Cutscenes" button.
"""
from __future__ import annotations

import pathlib
import re
import sys
import tkinter as tk
from collections import Counter, OrderedDict
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter import font as tkfont

from rf4s_modkit import script, textdb, mbundle, emscript, scriptasm

# Action-type names + key decoding for the Entries tab (a sibling module; may be absent or
# half-written, in which case the tab falls back to "type N" and raw (tag, value) keys).
try:
    from rf4s_modkit import entry_types as _entry_types
except Exception:                                   # noqa: BLE001 -- never let it kill the GUI
    _entry_types = None

LOCALES = ["eng", "jpn", "deu", "fra", "kor", "twn", "chn"]

# The listing grammar in a nutshell (Source tab "Syntax help", the Insert / New-scene
# dialogs). The full language is documented in rf4s_modkit/scriptasm.py.
SOURCE_SYNTAX_HELP = (
    "Listing syntax -- one statement per line, `;` starts a comment, `Lx:` is a label, the\n"
    "`0123:` address prefixes the disassembler prints are ignored (paste listings back verbatim):\n"
    "  FRAME 0                          frame setup (reserve N operand slots; scenes start with it)\n"
    "  DIALOG #8709                     show rf3mc line 8709 (speaker = the last SetSpeaker*)\n"
    "  SetSpeakerNancy 3, 0             action: mnemonic | technical name | opN | number, then args\n"
    "  GiveItem 258, (reg0 + 1), 0      args: int, (expr), enum name, regN, arr[N], @0xOFF (reuse)\n"
    "  BR_Z (REG_WIFE_ID == 11) -> L1   jump when the condition is FALSE (BR_NZ: when TRUE)\n"
    "  STORE (FLG_EV_DONE = 1)          write a flag / register / arr[N]  (= += -= *= /= %= &&= ||=)\n"
    "  CALL L2  /  JMP L2  /  CALL 0x1234    labels in the listing; 0xPC = existing code in the bank\n"
    "  PROMPT_CHOICE CANCEL->L2, #123->L3, #124->L4      choice menu (PROMPT_CHOICE_FORCED: no cancel)\n"
    "  SWITCH_EQ (reg1) -> L1, L2, L3  /  RAND_BR (3)->L1, (1)->L2  /  JMP_IND -> L1, L2\n"
    "  BR_END (cond)  /  .raw <hex>  /  END     -- a listing that can fall off its end gets END added"
)

INSERT_PROMPT = ("Statements to insert AFTER the selected one (full listing syntax, one per line):\n"
                 "  GiveItem 258, 1, 0           STORE (FLG_EV_DONE = 1)\n"
                 "  BR_Z (REG_WIFE_ID == 11) -> L1  /  DIALOG #5  /  L1:\n"
                 "Names: an opcode mnemonic (GiveItem, SetSpeakerMC) or a number; FLG_/REG_ variable "
                 "names come from emdeb.bin. Ctrl-Enter = OK.")

# Hover help for the controls of the modal listing / New-scene dialogs (built per call, so
# attached inline from this table rather than via the CONTROL_HELP loop).
DIALOG_CONTROL_HELP = {
    "listing_ok": "Validate the listing with the assembler (errors show below, with the line "
                  "number) and, when it is clean, apply it.",
    "listing_cancel": "Close without changing anything.",
    "listing_help": "Show / hide the listing grammar cheat-sheet.",
    "ns_type": "The action type (type-table slot) the new scene is registered under -- it decides "
               "WHEN the engine starts the scene (talk, map enter, item use, festival phase, ...). "
               "The count shows how many entries the bank already has of that type.",
    "ns_keys": "The entry's matcher keys, comma-separated: `5, -1` (plain values; -1 = wildcard) or "
               "`(tag, value)` pairs for a non-1 tag. Prefilled with the key count this type "
               "expects (or that the bank's existing entries of it carry).",
    "ns_position": "Where the entry goes in the type's list: append (last) or first. Matchers take "
                   "the FIRST match in list order; the type-6/7 tick dispatchers take the LAST.",
    "ns_recipe": "Start from a catalogue RECIPE: picking one selects its action type and prefills "
                 "the keys from the type's key spec; the recipe text (which bank, which keys, what "
                 "the body must do) shows under the picker and in this tooltip.",
    # --- Event Manager: Add condition… / Add action… dialogs ---
    "emc_which": "Which condition of the entry receives the expressions: A (EvalCondA, op 371 -- "
                 "the entry's main gate) or B (EvalCondB, op 372).",
    "emc_slot": "The OR-slot: 'new' appends another OR-slot (any true slot makes the condition "
                "true); an existing slot number ANDs the new groups onto that slot.",
    "emc_text": "The expressions, in the condition grammar shown by Syntax help (a OP b / TRUE / "
                "FALSE / [!]condA(entry), joined by AND / OR). Parsed before it is applied; errors "
                "show here, inline.",
    "emc_ok": "Parse the text and add it to the entry (em.bin is re-laid out in memory; Save "
              "em.bin… writes it).",
    "ema_stream": "main = the entry's action stream (op 373 / when its condition holds), alt = its "
                  "alt stream (op 374).",
    "ema_position": "append = after the stream's last action, first = before its first one "
                    "(actions run in list order).",
    "ema_text": "One action in the action grammar shown by Syntax help (CALL entry, T = V, T += V, "
                "…, or OP T V). Parsed before it is applied; errors show here, inline.",
    "ema_ok": "Parse the text and add the action to the stream (em.bin is re-laid out in memory; "
              "Save em.bin… writes it).",
    "em_check": "Parse the text without applying it: shows the decoded expressions / action "
                "(green) or the parse error (red).",
    "em_help": "Show / hide the grammar cheat-sheet.",
}


def entry_keys_text(subs):
    """Keys as the New-scene / Re-key fields accept them: `5, -1` for plain (tag 1) keys,
    `(tag, value)` pairs for anything else. `subs` items are (tag, value) pairs (as
    EntryRecord.subs) or bare ints (tag 1, as parse_entry_keys returns them)."""
    parts = []
    for s in subs:
        tag, v = s if isinstance(s, (tuple, list)) else (1, s)
        parts.append(str(v) if tag == 1 else "(%d, %d)" % (tag, v))
    return ", ".join(parts)


def parse_entry_keys(text):
    """Parse an entry's keys from text: a comma list of ints (`5, -1`, tag 1) and/or
    `(tag, value)` pairs (`(2, 100)`). Empty text -> no keys. Raises ValueError."""
    out = []
    for tok in re.findall(r"\([^)]*\)|[^,\s()]+", text or ""):
        if tok.startswith("("):
            parts = [p.strip() for p in tok[1:-1].split(",") if p.strip()]
            try:
                if len(parts) == 1:
                    out.append(int(parts[0], 0))
                elif len(parts) == 2:
                    tag, val = int(parts[0], 0), int(parts[1], 0)
                    if not (0 <= tag <= 255):
                        raise ValueError("key tag %d must be 0..255" % tag)
                    out.append((tag, val))
                else:
                    raise ValueError("a key pair is (tag, value); got %r" % tok)
            except ValueError as e:
                raise ValueError("bad key %r: %s" % (tok, e))
        else:
            try:
                out.append(int(tok, 0))
            except ValueError:
                raise ValueError("bad key %r -- keys are integers (`5, -1`) or `(tag, value)` "
                                 "pairs" % tok)
    return out


def _type_label(type_id):
    """'type N  Name' from entry_types when available, else 'type N'."""
    if _entry_types is not None:
        try:
            nm = _entry_types.type_name(type_id)
            if isinstance(nm, str) and nm.strip() and nm.strip() != str(type_id):
                return "type %d  %s" % (type_id, nm.strip())
        except Exception:
            pass
    return "type %d" % type_id


def _type_summary(type_id):
    """One-line 'when it fires' summary of an action type (entry_types), else ''."""
    if _entry_types is not None:
        try:
            info = getattr(_entry_types, "ENTRY_TYPES", {}).get(type_id) or {}
            s = info.get("summary") or ""
            if isinstance(s, str):
                return s.strip()
        except Exception:
            pass
    return ""


def _type_key_names(type_id):
    """The key names the type's matcher compares (entry_types 'keys'), else None."""
    if _entry_types is not None:
        try:
            info = getattr(_entry_types, "ENTRY_TYPES", {}).get(type_id) or {}
            keys = info.get("keys")
            if isinstance(keys, (list, tuple)):
                return list(keys)
        except Exception:
            pass
    return None


def _describe_keys(type_id, subs):
    """Decoded keys of an entry (entry_types.describe_entry), else the raw key list."""
    if _entry_types is not None:
        try:
            s = _entry_types.describe_entry(type_id, list(subs))
            if isinstance(s, str) and s.strip():
                return s.strip()
        except Exception:
            pass
    return entry_keys_text(subs) or "(no keys)"

def _type_recipe(type_id):
    """The catalogue's `recipe` text for an action type (how a scene of that type is set up:
    which bank, which keys, what the body must do), else ''. The field is being added by a
    concurrent RE pass, so it may be absent."""
    if _entry_types is not None:
        try:
            info = getattr(_entry_types, "ENTRY_TYPES", {}).get(type_id) or {}
            r = info.get("recipe") or ""
            if isinstance(r, str):
                return r.strip()
        except Exception:
            pass
    return ""


def recipe_types():
    """[(type_id, name, recipe_text)] for every catalogue type that carries a `recipe`
    field, by type id. Empty while the catalogue has none (the New-scene dialog then hides
    its recipe picker)."""
    out = []
    if _entry_types is None:
        return out
    try:
        for t in sorted(getattr(_entry_types, "ENTRY_TYPES", {})):
            r = _type_recipe(t)
            if r:
                lab = _type_label(t)
                out.append((int(t), lab.split("  ", 1)[1] if "  " in lab else lab, r))
    except Exception:
        return []
    return out


# Words of the catalogue `bank` field -> the Bank.kind they dispatch from. Covers both the
# enumerated form ('global' | 'primary' | 'tail' | 'primary:224+npc' | 'primary:subevent' |
# 'primary:story' | 'mixed') and the older free text ('tail (slot 2)', 'primary: canonical
# char id', 'slot 1 (post-event modes 1/2) or slot 2 (mode 0)').
_BANK_KIND_WORDS = (("global", "global"), ("primary", "primary"), ("tail", "tail"),
                    ("slot 0", "global"), ("slot 1", "primary"), ("slot 2", "tail"))


def _type_bank_text(type_id):
    """The catalogue's `bank` field for a type, verbatim ('' when absent)."""
    if _entry_types is not None:
        try:
            b = (getattr(_entry_types, "ENTRY_TYPES", {}).get(type_id) or {}).get("bank")
            if isinstance(b, str):
                return b.strip()
        except Exception:
            pass
    return ""


def _type_bank_kinds(type_id):
    """The set of Bank.kind values ({'global', 'primary', 'tail'}) the catalogue says the
    engine looks this type up in, or None when the catalogue does not say."""
    s = _type_bank_text(type_id).lower()
    if not s:
        return None
    if s == "mixed":
        return {"global", "primary", "tail"}
    kinds = {k for w, k in _BANK_KIND_WORDS if w in s}
    return kinds or None


MAP_ENTER_TYPE = 7      # MapEnterScene: the map-bank scene run on map entry (last entry wins)


def map_enter_type():
    """The action type a map's ENTER scene is registered under -- the catalogue type named
    MapEnterScene when the catalogue has it, else the engine-verified id 7 (tail bank of
    the entered map, game-event handler 24, the LAST entry wins)."""
    if _entry_types is not None:
        try:
            for t, info in getattr(_entry_types, "ENTRY_TYPES", {}).items():
                if (info or {}).get("name") == "MapEnterScene":
                    return int(t)
        except Exception:
            pass
    return MAP_ENTER_TYPE


# The Event Manager text grammars (rf4s_modkit.emscript.EmScript.parse_condition_spec /
# parse_action_spec), shown as help in the Add condition… / Add action… dialogs.
EM_CONDITION_SYNTAX_HELP = (
    "Condition text -- ONE OR-slot's expression list (parse_condition_spec grammar):\n"
    "  Hour >= 6 AND (12 > Hour OR FLG_RAINBOW == 1) AND !condA(EV_DATE_APPO)\n"
    "  groups are joined by AND; terms inside a group by OR (parenthesise the group)\n"
    "  term     a OP b  (OP: == != > >= < <=)  |  TRUE  |  FALSE  |  condA(entry) / !condB(entry)\n"
    "  operand  12 / 0x10 literal · -3 or s:N signed · Hour / q:Hour / q:3 query · REG_/FLG_\n"
    "           emdeb variable name · flag@BIT/WIDTH raw flag ref · entry = its name or #id\n"
    "  slot     'new' opens another OR-slot (slots are ORed: any true slot = condition true);\n"
    "           an existing slot number ANDs the new groups onto that slot"
)

EM_ACTION_SYNTAX_HELP = (
    "Action text -- ONE action (parse_action_spec grammar):\n"
    "  CALL EV_FOO                run that entry's main actions (entry = its name or #id)\n"
    "  FLG_X = 1   REG_Y += 2     also T -= V, T *= V, T /= V, T %= V, T = (V == 0) (SET_EQ_ZERO)\n"
    "  MAX_S REG_Y 5              explicit form OP T V, OP in SET ADD SUB MUL_S MUL_U DIV_S DIV_U\n"
    "                             MOD_S MOD_U MAX_S MAX_U MIN_S MIN_U SET_EQ_ZERO (_S/_U = signedness)\n"
    "  T = an emdeb variable (FLG_/REG_ name) or flag@BIT/W (or q:N); V = literal / query / variable\n"
    "  stream: main = the entry's actions (op 373 / condition true), alt = its alt actions (op 374)"
)

# Hover-tooltip help for the editor's edit-panel controls, so each button/field is
# self-explanatory (the disassembly has its own richer Ctrl-hover tooltips; these cover the
# controls a modder clicks). Keyed by the widget's attribute name so they attach data-driven;
# a selftest asserts every listed control exists and carries non-empty help.
CONTROL_HELP = {
    # --- toolbar / search ---
    "open_btn": "Open a rf3.mc cutscene container to browse and edit its scenes.",
    "loc_combo": "Switch the dialogue locale (eng/jpn/deu/fra/kor/twn/chn); text edits apply to the "
                 "shown locale. A DIALOG line id is shared across locales.",
    "save_script_btn": "Save the edited rf3.mc as a loose file (byte-exact; unchanged bytes round-trip).",
    "save_text_btn": "Save the edited dialogue archive (rf3mc.<locale>) as a loose file.",
    "install_btn": "Install the edited rf3.mc / dialogue into a game .mbundle — repacks and repoints "
                   "the manifest so the game loads your version.",
    "em_btn": "Open the Event Manager: view + edit the em.bin conditions ('plays when') and flag/var "
              "effects that scenes bridge to.",
    "xref_btn": "Who calls this? List every CALL / JMP / branch / choice in the bank that targets "
                "the selected statement (or the scene's entry when nothing is selected), plus the "
                "scene's type-table dispatch when the engine can start it directly. Double-click a "
                "result to jump to the calling statement.",
    "find_btn": "Search every scene by the selected mode (also: press Enter in the search box).",
    "search_mode_combo": "What to search: dialogue text, EMF entry name, speaker, or opcode "
                         "name/number.",
    "list_bank_btn": "List every scene in the given bank number.",
    # --- edit panel ---
    "line_ent": "The rf3mc line id used by Retarget / Apply text. Type a choice option's #id here "
                "to edit its text.",
    "retarget_btn": "Point the selected DIALOG at a different rf3mc line id (from the line id box).",
    "add_line_btn": "Append the text box as a NEW dialogue line in the current locale (id prefilled) "
                    "— for new beats or missing translations.",
    "pad_locales_chk": "With 'Add line': also append the new line to every OTHER rf3mc.<locale> "
                       "archive the loaded source can supply (same text; a shorter archive is "
                       "padded with '[<locale> TBD]' lines first), so the new line id exists in "
                       "every locale instead of being out of range there. The padded archives are "
                       "marked unsaved and written by Save dialogue… / Install to game… (translate "
                       "them via the Locale switch + Apply text).",
    "apply_text_btn": "Save the text box to the selected DIALOG's line — or, with no DIALOG "
                      "selected, to the line id box's line (e.g. a choice option).",
    "spk_combo": "Who speaks the following dialogue line(s) (for the selected SetSpeaker). The "
                 "speaker PERSISTS across consecutive DIALOG lines until the next SetSpeaker or "
                 "EndDialogue (op 92) — one speaker op can carry a whole multi-line speech.",
    "spk_side_combo": "Which side the speaker's portrait shows on.",
    "spk_btn": "Rewrite the selected SetSpeaker to the chosen speaker + side (byte-exact).",
    "val_arg_spin": "Which argument to edit (0-based). For a control op (BR_Z / STORE / RAND_BR), "
                    "which literal in its guard/value expression.",
    "val_ent": "The new integer value to write.",
    "set_val_btn": "Write the value into the chosen arg / control-op literal, in place (byte-safe; "
                   "auto-repoints a variable or fixed-push arg to a fresh literal if needed). On a "
                   "PROMPT_CHOICE, arg# = which option and value = the rf3mc line id that option "
                   "shows (retarget a choice's text, e.g. to a line just added with 'text add').",
    "enum_combo": "Pick a named value (item / character / effect / room / …); copies its id into "
                  "the value box — you still click Set value to apply.",
    "undo_btn": "Undo the last script or dialogue edit (Ctrl+Z in the disassembly / scene list). "
                "Every edit is undoable; undoing back to the saved state clears the unsaved marker.",
    "redo_btn": "Redo the last undone edit (Ctrl+Y).",
    "args_ent": "Every argument of the selected action in listing syntax, comma-separated: "
                "numbers, actor(Forte) / map(MAP_CITY_00), (FLG_X + 1) expressions, enum names, "
                "or @0xNNNN to point at an existing expression.",
    "apply_args_btn": "Apply the argument list: unchanged args are left alone, a new value is "
                      "patched in place when it fits, otherwise a fresh expression is appended and "
                      "the arg repointed at it.",
    "ins_dlg_btn": "Insert a new DIALOG statement right after the selected one (byte-safe trampoline).",
    "ins_act_btn": "Insert one or more statements after the selected one, in full listing syntax: "
                   "an action by name or number ('GiveItem 258, 1, 0'), DIALOG #id, "
                   "BR_Z (FLG_X) -> L1 / STORE (FLG_X = 1) with emdeb.bin variable names, labels, "
                   "choices… Validated by the assembler before it is applied (byte-safe trampoline).",
    "del_stmt_btn": "Delete the selected statement (byte-safe; the trampoline skips over it).",
    # --- Source tab (editable listing <-> assembler) ---
    "src_reload_btn": "Discard the edits in the Source box and regenerate the listing from the "
                      "scene's current bytecode.",
    "src_check_btn": "Assemble the Source box without applying it: reports the region size, or the "
                     "first error with its line number (the line is highlighted).",
    "src_apply_btn": "Assemble the Source box and make the scene play it: the new body is appended "
                     "to the bank and the scene's entry jumps to it (the trigger is unchanged, the "
                     "old body becomes dead bytes, nothing else moves). Marks rf3.mc unsaved.",
    "src_help_btn": "Show / hide the listing grammar cheat-sheet above the Source box.",
    # --- Entries tab (the bank's type table = scene triggers) ---
    "ent_new_btn": "Mint a brand-new scene in the listed bank: pick the action type (WHEN it "
                   "fires), its matcher keys, write the body as a listing; it is assembled, "
                   "appended and registered in the type table, then opened.",
    "ent_open_btn": "Open the selected entry's scene in the Disassembly / Source tabs (same as "
                    "double-clicking the row).",
    "ent_rekey_btn": "Change the selected entry's matcher keys (comma list, e.g. '5, -1' or "
                     "'(2, 100)'); same-length re-keys are patched in place.",
    "ent_remove_btn": "Unregister the selected entry so its trigger no longer fires (the scene's "
                      "code stays as dead bytes; other entries keep their order).",
    "ent_refresh_btn": "Re-read the listed bank's type table (after edits made elsewhere).",
}

# Hover-tooltip help for the Event Manager (em.bin) editor's controls (built lazily in
# _open_em_browser, so attached inline there rather than via the CONTROL_HELP loop).
EM_CONTROL_HELP = {
    "field": "Pick which condition or action of this em entry to edit — each comparison (its "
             "threshold + operator) and each arithmetic action (its value + op).",
    "value": "The new value for the selected condition threshold / action value (byte-safe, in place).",
    "op": "The operator: a comparison (==, !=, >, >=) for a condition, or the arithmetic op "
          "(SET / ADD / SUB / MUL / DIV / MOD / MIN / MAX / SET_EQ_ZERO) for an action. The "
          "_S / _U suffix selects signed vs unsigned arithmetic. The line under the picker "
          "explains the currently-selected operator.",
    "apply": "Apply the value / operator change to the selected condition or action (in place).",
    "save": "Save the edited em.bin as a loose override file.",
    "add_entry": "Append a NEW em entry (empty, or a clone of the selected entry's conditions + "
                 "actions) and bump the header count so the engine evaluates it. Its id is the old "
                 "entry count; the name you give is in-memory only (emdeb.bin is not rewritten).",
    "remove_entry": "Physically delete the selected entry: every later entry moves down one id "
                    "(internal condA/B refs and CALLs are renumbered; rf3.mc bridge ops are NOT). "
                    "If other entries reference it you are offered to clear it in place instead "
                    "(keeps ids stable).",
    # --- structural editing (round 2): whole conditions / actions ---
    "struct": "Pick a STRUCTURAL element of the selected entry for Remove condition / Remove "
              "action: a whole OR-slot of condition A/B, one expression inside a slot, or one "
              "main/alt action (CALLs and condA/B references included -- unlike the value picker "
              "above). Add condition… / Add action… take text instead.",
    "add_condition": "Add expressions to condition A or B of the selected entry from text in the "
                     "parse_condition_spec grammar (`Hour >= 6 AND (12 > Hour OR FLG_RAINBOW == 1)`), "
                     "into a new OR-slot or ANDed onto an existing one. Parsed before it is "
                     "applied; em.bin is re-laid out in memory (Save em.bin… writes it).",
    "remove_condition": "Remove the OR-slot or the single expression picked in the structure box "
                        "from the selected entry (the previous OR-group member closes the group; "
                        "an emptied slot disappears).",
    "add_action": "Add one action to the selected entry's main or alt stream from text in the "
                  "parse_action_spec grammar (`FLG_X = 1`, `REG_Y += 2`, `CALL EV_FOO`), appended "
                  "or first. Parsed before it is applied.",
    "remove_action": "Remove the main/alt action picked in the structure box from the selected "
                     "entry.",
}


def collect_xrefs(bank, target_pc):
    """Reverse control-flow lookup: every statement in `bank` whose CALL/JMP/branch/
    switch/choice targets `target_pc`. Returns [(scene_entry_pc, action_type, from_pc,
    mnem)] sorted by site, deduped by from_pc (post-FRAME, discovered scenes overlap
    their parents, so the same site can appear in several scenes — typed scenes are
    yielded first by disassemble_bank and win the attribution). Targets in the MYCF
    bytecode are bank-local u16 pcs, so the caller graph never crosses banks."""
    rows, seen = [], set()
    for sc in script.disassemble_bank(bank, discover=True):
        for pc, st in sc.stmts.items():
            if pc in seen or target_pc not in st.code_targets:
                continue
            seen.add(pc)
            rows.append((sc.entry_pc, sc.action_type, pc, st.mnem))
    rows.sort(key=lambda r: (r[0], r[2]))
    return rows


class CutsceneExplorer:
    """Browse + edit cutscene scripts. Builds into `parent` (a Toplevel or frame)."""

    def __init__(self, parent, reader=None, status_fn=None, focus_bank=None, focus_entry=None,
                 focus_pc=None):
        self.parent = parent
        self.reader = reader                      # reader(name)->bytes|None (by basename)
        self._focus_bank = focus_bank             # optional bank index to open on straight away
        self._focus_entry = focus_entry           # optional scene entry_pc to pre-select
        self._focus_pc = focus_pc                 # optional statement pc to scroll to + highlight
        self.status_fn = status_fn
        self.container = None                     # script.Container (rf3.mc)
        self._emf_vars = None                     # emflags.EmFlagTable (emdeb.bin var names)
        self.textarc = None                       # textdb.TextArchive (rf3mc.<locale>)
        self.locale = "eng"
        self.script_dirty = False
        self.text_dirty = False
        self._sibling_arcs = {}                   # locale -> TextArchive of the OTHER locales
        self._sibling_dirty = set()               # ...those with unsaved edits (Add line padding)
        self._sibling_missing = set()             # ...those the reader could not supply
        self._results = []                        # [(bank, Scene)]
        self._scene = None                        # currently displayed Scene
        self._bank = None                         # its Bank
        self._disp = {}                           # text-line number -> (pc, Statement)
        self._labels = {}                         # pc -> "Ln" branch-target labels
        self._sel = None                          # (pc, Statement)
        self._ctrl_lits = []                      # control-op expr literals: [(off,val,width)]
        self._em = None                           # emscript.EmScript (lazy; False = unavailable)
        # Undo / redo for every script + dialogue edit (see _recorded). Each step stores only
        # what changed: the header/table region plus the banks whose bytes differ, and the
        # dialogue lines that differ per locale -- a few KB, not the 4.7 MB file.
        self._undo_steps, self._redo_steps = [], []
        self._rec_depth = 0
        for _name in self._RECORDED:
            setattr(self, _name, self._recorded(getattr(self, _name), _name))
        self._build()
        self._bind_undo_keys(self.text, self.scene_list)
        if isinstance(parent, (tk.Tk, tk.Toplevel)):
            parent.protocol("WM_DELETE_WINDOW", self._on_close)
        if self.reader is not None:
            self._load_all()
        if self._focus_bank is not None:
            self.show_bank(self._focus_bank, self._focus_entry)
            if self._focus_pc is not None:
                self.parent.after_idle(lambda: self._scroll_to_pc(self._focus_pc))

    # ---- undo / redo ------------------------------------------------------- #
    # Handlers that change rf3.mc or a dialogue archive. Each is wrapped once at startup:
    # the OUTERMOST call records one undo step (nested calls, e.g. _set_value ->
    # _set_ctrl_literal, stay one step), and a call that ends with the same bytes records
    # nothing and restores the unsaved flags -- so a no-op Apply no longer marks the file
    # as modified.
    _RECORDED = ("_set_value", "_set_ctrl_literal", "_set_speaker", "_restructure",
                 "_source_apply", "_entries_add", "_entries_remove", "_entries_set_keys",
                 "_apply_text", "_add_line", "_retarget", "_apply_args", "_insert_listing")
    UNDO_LIMIT = 60

    def _recorded(self, fn, name):
        def wrapper(*a, **k):
            if self._rec_depth or self.container is None:
                return fn(*a, **k)
            before = self._capture()
            self._rec_depth += 1
            try:
                return fn(*a, **k)
            finally:
                self._rec_depth -= 1
                self._finish_step(name, before)
        wrapper.__name__ = name
        return wrapper

    def _dirty_locales(self):
        d = set(self._sibling_dirty)
        if self.text_dirty:
            d.add(self.locale)
        return d

    def _archives(self):
        out = dict(self._sibling_arcs)
        if self.textarc is not None:
            out[self.locale] = self.textarc
        return out

    def _capture(self):
        c = self.container
        order = sorted(range(len(c.banks)), key=lambda i: c.banks[i].file_off)
        head = bytes(c.data[:c.banks[order[0]].file_off]) if order else bytes(c.data)
        return {"container": c, "head": head, "order": order,
                "banks": [bytes(b.data) for b in c.banks],
                "texts": {loc: list(arc.entries) for loc, arc in self._archives().items()},
                "script_dirty": self.script_dirty, "dirty_locales": self._dirty_locales()}

    @staticmethod
    def _text_delta(eb, ea):
        """(len_before, {i: line_before}, len_after, {i: line_after}) or None if equal."""
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

    def _finish_step(self, name, before):
        """Compare the state after a recorded handler with `before`; push one undo step."""
        if self.container is not before["container"]:
            return                              # a new rf3.mc was opened: not an edit
        after = self._capture()
        mc = None
        changed = {i for i, (x, y) in enumerate(zip(before["banks"], after["banks"])) if x != y}
        if changed or before["head"] != after["head"] or before["order"] != after["order"]:
            mc = {"head": (before["head"], after["head"]), "order": (before["order"], after["order"]),
                  "banks": {i: (before["banks"][i], after["banks"][i]) for i in changed}}
        texts = {}
        for loc in set(before["texts"]) | set(after["texts"]):
            eb = before["texts"].get(loc)
            ea = after["texts"].get(loc)
            if eb is None:                      # archive loaded during the edit (Add line
                eb = self._pristine_entries(loc)  # pads other locales): its prior state
            if ea is None or eb is None:
                continue
            d = self._text_delta(eb, ea)
            if d is not None:
                texts[loc] = d
        if mc is None and not texts:
            # nothing actually changed: undo the "unsaved" flag the handler just set
            self.script_dirty = before["script_dirty"]
            self._set_dirty_locales(before["dirty_locales"])
            self._refresh_undo_buttons()
            return
        view = None
        if self._bank is not None and self._scene is not None:
            view = (self._bank.index, self._scene.entry_pc)
        self._undo_steps.append({
            "label": name.strip("_").replace("_", " "), "mc": mc, "texts": texts, "view": view,
            "script_dirty": (before["script_dirty"], self.script_dirty),
            "dirty_locales": (set(before["dirty_locales"]), self._dirty_locales())})
        if len(self._undo_steps) > self.UNDO_LIMIT:
            self._undo_steps.pop(0)
        self._redo_steps.clear()
        self._refresh_undo_buttons()

    def _pristine_entries(self, loc):
        data = self.reader(f"rf3mc.{loc}") if self.reader else None
        if not data:
            return None
        try:
            return list(textdb.TextArchive.parse(data).entries)
        except Exception:
            return None

    def _set_dirty_locales(self, locs):
        self.text_dirty = self.locale in locs
        self._sibling_dirty = set(locs) - {self.locale}

    def _apply_step(self, step, side):
        """Put the state of one side (0 = before, 1 = after) of `step` back in place."""
        mc = step["mc"]
        if mc is not None:
            c = self.container
            banks = [bytes(b.data) for b in c.banks]
            for i, pair in mc["banks"].items():
                banks[i] = pair[side]
            data = mc["head"][side] + b"".join(banks[i] for i in mc["order"][side])
            self.container = script.Container(data)
            self._install_var_resolver()
        arcs = self._archives()
        for loc, (lb, bd, la, ad) in step["texts"].items():
            arc = arcs.get(loc)
            if arc is None:
                continue
            n, d = (lb, bd) if side == 0 else (la, ad)
            ents = arc.entries[:n] + [b""] * max(0, n - len(arc.entries))
            for i, v in d.items():
                if i < n:
                    ents[i] = v
            arc.entries[:] = ents
        self.script_dirty = step["script_dirty"][side]
        self._set_dirty_locales(step["dirty_locales"][side])
        # re-open the scene the step was made in (bank objects were rebuilt)
        if step["view"] is not None and self.container is not None:
            bi, entry = step["view"]
            self._bank = self._scene = self._sel = None
            self.show_bank(bi, entry)
        elif self._scene is not None:
            self._render_scene()

    def _undo(self, _e=None):
        if not self._undo_steps:
            self._status("nothing to undo" + self._dirty_tag()); return "break"
        step = self._undo_steps.pop()
        self._apply_step(step, 0)
        self._redo_steps.append(step)
        self._refresh_undo_buttons()
        self._status(f"undid: {step['label']}{self._dirty_tag()}")
        return "break"

    def _redo(self, _e=None):
        if not self._redo_steps:
            self._status("nothing to redo" + self._dirty_tag()); return "break"
        step = self._redo_steps.pop()
        self._apply_step(step, 1)
        self._undo_steps.append(step)
        self._refresh_undo_buttons()
        self._status(f"redid: {step['label']}{self._dirty_tag()}")
        return "break"

    def _refresh_undo_buttons(self):
        for btn, stack in ((getattr(self, "undo_btn", None), self._undo_steps),
                           (getattr(self, "redo_btn", None), self._redo_steps)):
            if btn is not None:
                try:
                    btn.config(state=("normal" if stack else "disabled"))
                except tk.TclError:
                    pass

    def _mark_saved(self, mc=False, locales=()):
        """After a save, every OTHER point in the history differs from what is on disk:
        make undo/redo report those files as unsaved (never under-report)."""
        for step in self._undo_steps + self._redo_steps:
            if mc:
                step["script_dirty"] = (True, True)
            for loc in locales:
                for side in (0, 1):
                    step["dirty_locales"][side].add(loc)

    def _reset_history(self):
        self._undo_steps.clear(); self._redo_steps.clear()
        self._refresh_undo_buttons()

    # ---- unsaved changes ------------------------------------------------- #
    def unsaved(self):
        out = []
        if self.script_dirty:
            out.append("rf3.mc")
        out += [f"rf3mc.{loc}" for loc in sorted(self._dirty_locales())]
        return out

    def confirm_discard(self, action="continue"):
        """Ask before throwing away unsaved script / dialogue edits. True = proceed."""
        parts = self.unsaved()
        if not parts:
            return True
        ans = messagebox.askyesnocancel(
            "Unsaved changes", f"Unsaved changes to {', '.join(parts)}.\n\nSave before you "
            f"{action}?\n(Yes = save, No = discard, Cancel = stay here)", parent=self.parent)
        if ans is None:
            return False
        if ans:
            if self.script_dirty and not self._save_script():
                return False
            if self._dirty_locales() and not self._save_text():
                return False
        return True

    def _on_close(self):
        if self.confirm_discard("close the cutscene editor"):
            self.parent.destroy()

    # ---- status ---------------------------------------------------------- #
    def _status(self, s, note=False):
        """Set the status line; `note=True` colours it yellow (an advisory such as the
        entry-shadow note after a New scene)."""
        if self.status_fn:
            self.status_fn(s)
        if hasattr(self, "status"):
            try:
                self.status.config(text=s, foreground=("#8a6d00" if note else ""))
            except tk.TclError:
                self.status.config(text=s)

    def _dirty_tag(self):
        d = []
        if self.script_dirty:
            d.append("rf3.mc*")
        if self.text_dirty:
            d.append(f"rf3mc.{self.locale}*")
        d += [f"rf3mc.{loc}*" for loc in sorted(self._sibling_dirty) if loc != self.locale]
        return ("  [unsaved: " + ", ".join(d) + "]") if d else ""

    # ---- widgets --------------------------------------------------------- #
    def _build(self):
        bar = ttk.Frame(self.parent); bar.pack(fill="x")
        self.open_btn = ttk.Button(bar, text="Open rf3.mc…", command=self._open_script_file)
        self.open_btn.pack(side="left", padx=2, pady=3)
        ttk.Label(bar, text="Locale:").pack(side="left", padx=(8, 0))
        self.loc_var = tk.StringVar(value=self.locale)
        self.loc_combo = ttk.Combobox(bar, textvariable=self.loc_var, values=LOCALES,
                                      width=6, state="readonly")
        self.loc_combo.pack(side="left", padx=2)
        self.loc_combo.bind("<<ComboboxSelected>>", lambda _e: self._switch_locale())
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        self.save_script_btn = ttk.Button(bar, text="Save rf3.mc…", command=self._save_script)
        self.save_script_btn.pack(side="left", padx=2)
        self.save_text_btn = ttk.Button(bar, text="Save dialogue…", command=self._save_text)
        self.save_text_btn.pack(side="left", padx=2)
        self.install_btn = ttk.Button(bar, text="Install to game…", command=self._install)
        self.install_btn.pack(side="left", padx=2)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        self.undo_btn = ttk.Button(bar, text="Undo", width=6, command=self._undo, state="disabled")
        self.undo_btn.pack(side="left", padx=2)
        self.redo_btn = ttk.Button(bar, text="Redo", width=6, command=self._redo, state="disabled")
        self.redo_btn.pack(side="left", padx=2)
        self.em_btn = ttk.Button(bar, text="Event Mgr…", command=self._open_em_browser)
        self.em_btn.pack(side="left", padx=2)
        self.xref_btn = ttk.Button(bar, text="Xrefs", command=self._show_xrefs)
        self.xref_btn.pack(side="left", padx=2)
        self.status = ttk.Label(bar, text="", anchor="e"); self.status.pack(side="right", padx=8)

        from guiutil import Paned
        paned = Paned(self.parent, orient="horizontal"); paned.pack(fill="both", expand=True)

        # ---- left: search / browse + scene list ----
        left = ttk.Frame(paned); paned.add(left, weight=0, minsize=180)
        sf = ttk.Frame(left); sf.pack(fill="x", padx=4, pady=4)
        self.search_var = tk.StringVar()
        ent = ttk.Entry(sf, textvariable=self.search_var)
        ent.pack(side="left", fill="x", expand=True)
        ent.bind("<Return>", lambda _e: self._search())
        self.find_btn = ttk.Button(sf, text="Find", command=self._search)
        self.find_btn.pack(side="left", padx=2)
        sf2 = ttk.Frame(left); sf2.pack(fill="x", padx=4)
        ttk.Label(sf2, text="in:").pack(side="left")
        self.search_mode = tk.StringVar(value="dialogue")
        self.search_mode_combo = ttk.Combobox(sf2, textvariable=self.search_mode, width=12,
                     state="readonly", values=["dialogue", "EMF entry", "speaker", "opcode"])
        self.search_mode_combo.pack(side="left", padx=2)
        bf = ttk.Frame(left); bf.pack(fill="x", padx=4)
        ttk.Label(bf, text="or bank #:").pack(side="left")
        self.bank_var = tk.StringVar(value="1")
        ttk.Entry(bf, textvariable=self.bank_var, width=6).pack(side="left", padx=2)
        self.list_bank_btn = ttk.Button(bf, text="List bank", command=self._list_bank)
        self.list_bank_btn.pack(side="left", padx=2)
        lf = ttk.Frame(left); lf.pack(fill="both", expand=True, padx=4, pady=4)
        sb = ttk.Scrollbar(lf); sb.pack(side="right", fill="y")
        self.scene_list = tk.Listbox(lf, yscrollcommand=sb.set, exportselection=False)
        self.scene_list.pack(side="left", fill="both", expand=True)
        sb.config(command=self.scene_list.yview)
        self.scene_list.bind("<<ListboxSelect>>", lambda _e: self._on_scene_pick())

        # ---- right: (Disassembly | Analysis) tabs + statement editor ----
        right = Paned(paned, orient="vertical"); paned.add(right, weight=5)
        topnb = ttk.Notebook(right); right.add(topnb, weight=4)
        dframe = ttk.Frame(topnb); topnb.add(dframe, text="Disassembly")
        dsb = ttk.Scrollbar(dframe); dsb.pack(side="right", fill="y")
        self.text = tk.Text(dframe, wrap="none", font=("Consolas", 10), yscrollcommand=dsb.set,
                            bg="#101014", fg="#d8d8e0", insertbackground="#d8d8e0",
                            state="disabled", height=20)
        self.text.pack(side="left", fill="both", expand=True)
        dsb.config(command=self.text.yview)
        self.text.tag_configure("sel", background="#003b46")
        self.text.tag_configure("dlg", foreground="#86d0ff")
        self.text.tag_configure("hdr", foreground="#9a9aa6")
        self.text.tag_configure("lbl", foreground="#ffb454")   # branch-target labels (L0, L1, ...)
        self.text.tag_configure("pcfocus", background="#5a4a00")   # jumped-to line (spawn-marker click)
        self.text.bind("<Button-1>", self._on_disasm_click)
        self.text.bind("<Motion>", self._on_disasm_hover)
        self.text.bind("<Leave>", self._on_disasm_leave)
        self._tip = None
        self._tip_line = None        # (display line, ctrl?) currently shown
        self._tip_st = None          # Statement under the mouse (for a later Ctrl press)
        self._tip_xy = None          # screen pos for the tooltip
        self._tip_hover_ln = None    # display line under the mouse
        self._in_disasm = False      # mouse currently over a statement line?
        # Toggle plain<->rich the instant Ctrl is pressed/released, even with the
        # mouse held still. Bound on the toplevel so it fires wherever focus is;
        # add="+" so we don't clobber other Ctrl bindings.
        top = self.parent.winfo_toplevel()
        for seq in ("<KeyPress-Control_L>", "<KeyPress-Control_R>"):
            top.bind(seq, lambda _e: self._on_ctrl_toggle(True), add="+")
        for seq in ("<KeyRelease-Control_L>", "<KeyRelease-Control_R>"):
            top.bind(seq, lambda _e: self._on_ctrl_toggle(False), add="+")
        # Analysis tab: read-only structured breakdown of the selected scene
        aframe = ttk.Frame(topnb); topnb.add(aframe, text="Analysis")
        asb = ttk.Scrollbar(aframe); asb.pack(side="right", fill="y")
        self.analysis = tk.Text(aframe, wrap="word", font=("Consolas", 9),
                                bg="#101014", fg="#d8d8e0", state="disabled",
                                yscrollcommand=asb.set)
        self.analysis.pack(side="left", fill="both", expand=True)
        asb.config(command=self.analysis.yview)
        for tag, col in (("h", "#ffd479"), ("k", "#9a9aa6"), ("dlg", "#86d0ff"),
                         ("emf", "#7fd6a0"), ("flag", "#e08fd0"), ("warn", "#e0a060")):
            self.analysis.tag_configure(tag, foreground=col)
        self.analysis.tag_configure("hdr", foreground="#ffd479", font=("Consolas", 10, "bold"))
        self._topnb = topnb

        # Source tab: the scene as a re-assemblable listing (scriptasm.scene_listing). Edit
        # it, Check it, then "Assemble & replace scene": the new body is appended to the bank
        # and the scene's entry statement becomes a JMP to it (the trigger is untouched, the
        # old body is dead bytes, nothing else moves).
        sframe = ttk.Frame(topnb); topnb.add(sframe, text="Source")
        sbar = ttk.Frame(sframe); sbar.pack(fill="x", padx=2, pady=2)
        self.src_reload_btn = ttk.Button(sbar, text="Reload from scene", command=self._source_reload)
        self.src_reload_btn.pack(side="left", padx=2)
        self.src_check_btn = ttk.Button(sbar, text="Check", command=self._source_check)
        self.src_check_btn.pack(side="left", padx=2)
        self.src_apply_btn = ttk.Button(sbar, text="Assemble & replace scene",
                                        command=self._source_apply)
        self.src_apply_btn.pack(side="left", padx=2)
        self.src_help_btn = ttk.Button(sbar, text="Syntax help", command=self._source_toggle_help)
        self.src_help_btn.pack(side="left", padx=(10, 2))
        self.src_status = ttk.Label(sframe, text="(open a scene to see its listing)", anchor="w",
                                    justify="left", font=("Segoe UI", 8), foreground="#0d5f8f",
                                    wraplength=760)
        self.src_status.pack(fill="x", padx=4)
        self.src_help_lbl = tk.Label(sframe, text=SOURCE_SYNTAX_HELP, justify="left", anchor="w",
                                     font=("Consolas", 8), bg="#1b1b22", fg="#e6e6ee", padx=6, pady=4)
        self._source_help_shown = False            # packed above the editor on demand
        self._source_editor_frame = ttk.Frame(sframe)
        self._source_editor_frame.pack(fill="both", expand=True)
        ssb = ttk.Scrollbar(self._source_editor_frame); ssb.pack(side="right", fill="y")
        self.source = tk.Text(self._source_editor_frame, wrap="none", font=("Consolas", 10),
                              undo=True, bg="#101014", fg="#d8d8e0", insertbackground="#d8d8e0",
                              yscrollcommand=ssb.set, height=20)
        self.source.pack(side="left", fill="both", expand=True)
        ssb.config(command=self.source.yview)
        self.source.tag_configure("err", background="#5a1a1a")
        self._source_key = None                    # (bank identity, entry_pc) the text came from

        # Entries tab: the listed bank's type table -- its scene TRIGGERS. One node per action
        # type, one row per entry (index, scene pc, matcher keys). Mint / re-key / remove here.
        self._entries_tab = ttk.Frame(topnb); topnb.add(self._entries_tab, text="Entries")
        ebar = ttk.Frame(self._entries_tab); ebar.pack(fill="x", padx=2, pady=2)
        self.ent_new_btn = ttk.Button(ebar, text="New scene…", command=self._entries_new_scene)
        self.ent_new_btn.pack(side="left", padx=2)
        self.ent_open_btn = ttk.Button(ebar, text="Open scene", command=self._entries_open)
        self.ent_open_btn.pack(side="left", padx=2)
        self.ent_rekey_btn = ttk.Button(ebar, text="Re-key…", command=self._entries_rekey)
        self.ent_rekey_btn.pack(side="left", padx=2)
        self.ent_remove_btn = ttk.Button(ebar, text="Remove entry", command=self._entries_remove)
        self.ent_remove_btn.pack(side="left", padx=2)
        self.ent_refresh_btn = ttk.Button(ebar, text="Refresh", command=self._entries_refresh)
        self.ent_refresh_btn.pack(side="left", padx=(10, 2))
        self.ent_lbl = ttk.Label(self._entries_tab, text="(list a bank or open a scene to see its triggers)",
                                 anchor="w", justify="left", font=("Segoe UI", 8),
                                 foreground="#0d5f8f", wraplength=760)
        self.ent_lbl.pack(fill="x", padx=4)
        etf = ttk.Frame(self._entries_tab); etf.pack(fill="both", expand=True)
        esb = ttk.Scrollbar(etf); esb.pack(side="right", fill="y")
        self.entries_tree = ttk.Treeview(etf, columns=("pc", "keys"), yscrollcommand=esb.set,
                                         selectmode="browse")
        self.entries_tree.heading("#0", text="action type / entry")
        self.entries_tree.heading("pc", text="scene pc")
        self.entries_tree.heading("keys", text="keys (what the type's matcher compares; -1 = any)")
        self.entries_tree.column("#0", width=250, anchor="w", stretch=False)
        self.entries_tree.column("pc", width=80, anchor="w", stretch=False)
        self.entries_tree.column("keys", width=440, anchor="w")
        self.entries_tree.pack(side="left", fill="both", expand=True)
        esb.config(command=self.entries_tree.yview)
        self.entries_tree.bind("<Double-Button-1>", lambda _e: self._entries_open())
        self.entries_tree.bind("<Return>", lambda _e: self._entries_open())
        ttk.Label(self._entries_tab, foreground="#888", font=("Segoe UI", 7), anchor="w",
                  text="double-click / Enter on an entry row opens its scene · New scene… mints a "
                       "scene under a type · Remove unregisters (code stays)").pack(fill="x", padx=4)
        self._entries_bank = None                  # Bank whose table is shown
        self._entries_rows = {}                    # tree iid -> (type_id, EntryRecord|None)

        ed = ttk.LabelFrame(right, text="Selected statement"); right.add(ed, weight=0)
        self.sel_lbl = ttk.Label(ed, text="(click a statement above)", font=("Consolas", 9),
                                 justify="left")
        self.sel_lbl.grid(row=0, column=0, columnspan=4, sticky="w", padx=4, pady=2)
        # dialogue row
        ttk.Label(ed, text="line id").grid(row=1, column=0, sticky="e", padx=2)
        self.line_var = tk.StringVar()
        self.line_ent = ttk.Entry(ed, textvariable=self.line_var, width=8)
        self.line_ent.grid(row=1, column=1, sticky="w")
        self.retarget_btn = ttk.Button(ed, text="Retarget DIALOG", command=self._retarget)
        self.retarget_btn.grid(row=1, column=2, padx=2)
        # append the text box as a BRAND-NEW dialogue line (for new beats / missing translations);
        # always available while a text archive is loaded (does not need a DIALOG selected).
        self.add_line_btn = ttk.Button(ed, text="Add line", command=self._add_line)
        self.add_line_btn.grid(row=1, column=3, padx=2)
        # ...and pad every OTHER locale archive with the same line, so the new id is in range
        # everywhere (an id past a locale's end shows no text there). Default on; greyed once
        # 'Add line' finds no sibling rf3mc.<locale> in the source.
        self.pad_locales_var = tk.BooleanVar(value=True)
        self.pad_locales_chk = ttk.Checkbutton(ed, text="also pad other locales",
                                               variable=self.pad_locales_var)
        self.pad_locales_chk.grid(row=1, column=4, sticky="w", padx=(6, 2))
        ttk.Label(ed, text="text").grid(row=2, column=0, sticky="ne", padx=2)
        self.text_box = tk.Text(ed, height=3, width=44, wrap="word", font=("Segoe UI", 9))
        self.text_box.grid(row=2, column=1, columnspan=2, sticky="we", padx=2, pady=2)
        self.apply_text_btn = ttk.Button(ed, text="Apply text", command=self._apply_text)
        self.apply_text_btn.grid(row=2, column=3, padx=2)
        # action: per-arg hints
        self.hint_lbl = ttk.Label(ed, text="", font=("Segoe UI", 8), foreground="#0d5f8f",
                                  justify="left", wraplength=460)
        self.hint_lbl.grid(row=3, column=0, columnspan=4, sticky="w", padx=4)
        # portrait-line speaker/side picker (opcodes 16..75 -> who speaks + which side)
        self._spk_values = ["%d %s" % (i, t) if t == n else "%d %s (%s)" % (i, t, n)
                            for i, (t, n) in enumerate(zip(script.PORTRAIT_SPEAKER_TAGS,
                                                           script.PORTRAIT_SPEAKERS))]
        self.spk_f = ttk.Frame(ed); self.spk_f.grid(row=4, column=0, columnspan=4, sticky="w", padx=2, pady=2)
        ttk.Label(self.spk_f, text="speaker").pack(side="left")
        self.spk_var = tk.StringVar()
        self.spk_combo = ttk.Combobox(self.spk_f, textvariable=self.spk_var,
                                       values=self._spk_values, width=17, state="readonly")
        self.spk_combo.pack(side="left", padx=2)
        ttk.Label(self.spk_f, text="side").pack(side="left", padx=(6, 0))
        self.spk_side = tk.StringVar(value="left")
        self.spk_side_combo = ttk.Combobox(self.spk_f, textvariable=self.spk_side,
                                           values=["left", "right"], width=6, state="readonly")
        self.spk_side_combo.pack(side="left", padx=2)
        self.spk_btn = ttk.Button(self.spk_f, text="Set speaker", command=self._set_speaker)
        self.spk_btn.pack(side="left", padx=4)
        # action: set a value (patches the immediate the arg points to, in place)
        sv = ttk.Frame(ed); sv.grid(row=5, column=0, columnspan=4, sticky="w", padx=2, pady=2)
        ttk.Label(sv, text="set value  arg#").pack(side="left")
        self.val_arg = tk.StringVar(value="0")
        self.val_arg_spin = ttk.Spinbox(sv, from_=0, to=9, width=3, textvariable=self.val_arg,
                                        command=self._val_arg_changed)
        self.val_arg_spin.pack(side="left", padx=2)
        ttk.Label(sv, text="=").pack(side="left")
        self.val_var = tk.StringVar()
        self.val_ent = ttk.Entry(sv, textvariable=self.val_var, width=8)
        self.val_ent.pack(side="left", padx=2)
        self.set_val_btn = ttk.Button(sv, text="Set value", command=self._set_value)
        self.set_val_btn.pack(side="left", padx=2)
        # Enum picker: for args that have a known enum (e.g.
        # TriggerWorldInteractionAction arg 0), populate a searchable combobox.
        # Picking a row copies its integer into val_var; the user still confirms
        # by clicking "Set value" so nothing gets patched by accident.
        self.enum_var = tk.StringVar()
        self.enum_combo = ttk.Combobox(sv, textvariable=self.enum_var, width=44,
                                       state="disabled")
        self.enum_combo.pack(side="left", padx=(6, 2))
        self.enum_combo.bind("<<ComboboxSelected>>", self._enum_choice_picked)
        # Map from combobox display string -> int value (for picker->val_var).
        self._enum_lookup = {}
        # action: every argument in listing syntax (the same text the Source view uses)
        ttk.Label(ed, text="args").grid(row=6, column=0, sticky="e", padx=2)
        self.args_var = tk.StringVar()
        self.args_ent = ttk.Entry(ed, textvariable=self.args_var, width=40)
        self.args_ent.grid(row=6, column=1, columnspan=2, sticky="we", padx=2)
        self.args_ent.bind("<Return>", lambda _e: self._apply_args())
        self.apply_args_btn = ttk.Button(ed, text="Apply args", command=self._apply_args)
        self.apply_args_btn.grid(row=6, column=3, padx=2)
        ed.columnconfigure(1, weight=1)
        ttk.Label(ed, foreground="#888", font=("Segoe UI", 7), justify="left", wraplength=460,
                  text="DIALOG: edit the text (any length) or retarget the line id. SetSpeaker: pick "
                       "the speaker + side. Action args are EXPRESSION POINTERS into the data pool — "
                       "'set value' edits the immediate an arg points to (e.g. dial a face id); 'Repoint' "
                       "aims an arg at a different expression. Branch targets show as L0/L1… "
                       "Same-length edits round-trip exactly.").grid(
            row=7, column=0, columnspan=4, sticky="w", padx=4, pady=(2, 4))
        # structural editing (insert/delete beats — appends + redirects flow)
        struct_f = ttk.Frame(ed); struct_f.grid(row=8, column=0, columnspan=4, sticky="w", padx=4, pady=(2, 4))
        ttk.Label(struct_f, text="structure:").pack(side="left")
        self.ins_dlg_btn = ttk.Button(struct_f, text="+ dialogue after", command=self._insert_dialogue)
        self.ins_dlg_btn.pack(side="left", padx=2)
        self.ins_act_btn = ttk.Button(struct_f, text="+ action after", command=self._insert_action)
        self.ins_act_btn.pack(side="left", padx=2)
        self.del_stmt_btn = ttk.Button(struct_f, text="delete this", command=self._delete_stmt)
        self.del_stmt_btn.pack(side="left", padx=2)
        # hover tooltips on every edit-panel control (data-driven from CONTROL_HELP), so each
        # button/field explains itself -- the disassembly already has its own Ctrl-hover tooltips.
        for _ck, _ctext in CONTROL_HELP.items():
            _cw = getattr(self, _ck, None)
            if _cw is not None:
                self._attach_tip(_cw, _ctext)
        self._set_editor_enabled(False)

    # ---- load ------------------------------------------------------------ #
    def _bind_undo_keys(self, *widgets):
        for w in widgets:
            try:
                w.bind("<Control-z>", self._undo)
                w.bind("<Control-y>", self._redo)
                w.bind("<Control-Shift-Z>", self._redo)
            except (tk.TclError, AttributeError):
                pass

    def _load_all(self):
        raw = self.reader("rf3.mc") if self.reader else None
        if not raw:
            self._status("rf3.mc not found in the loaded source — Open rf3.mc… or open the Manifest.")
            return
        try:
            self.container = script.Container(raw)
        except Exception as e:
            messagebox.showerror("rf3.mc", f"Could not parse rf3.mc: {e}"); return
        self._install_var_resolver()
        self._load_text(self.locale)
        # (No script.coverage() here: disassembling all 1121 banks just to print a scene
        # count took ~4.3 s of the editor's ~4.8 s startup, on every open.)
        self._status(f"rf3.mc: {len(self.container.banks)} banks. List a bank or search dialogue — "
                     f"Ctrl-hover an opcode for its name, args & description.")

    def _load_text(self, locale):
        """Make `locale` the shown dialogue archive: the copy cached by an earlier locale
        switch / 'Add line' padding (with its unsaved edits) when there is one, else the
        reader's."""
        self.textarc = None
        if locale in self._sibling_arcs:
            self.textarc = self._sibling_arcs.pop(locale)
        else:
            data = self.reader(f"rf3mc.{locale}") if self.reader else None
            if data:
                try:
                    self.textarc = textdb.TextArchive.parse(data)
                except Exception:
                    self.textarc = None
        self.locale = locale

    def _install_var_resolver(self):
        """Wire disasm_expr so packed condition variables render as their emdeb.bin
        FLG_/REG_ names (e.g. `REG_WIFE_ID == 11`). Best-effort: silently keeps the
        raw `var:0xNN` form if emdeb.bin can't be located."""
        self._emf_vars = None
        script.set_packed_var_resolver(None)
        if self.container is None:
            return
        try:
            from rf4s_modkit.emflags import EmFlagTable
            data = self.reader("emdeb.bin") if self.reader else None
            emf = EmFlagTable.parse(data) if data else EmFlagTable.load()
            script.install_emflags_var_resolver(self.container, emf)
            self._emf_vars = emf
        except Exception:
            self._emf_vars = None
        # ...and the same names for the ASSEMBLER (Source tab, Insert, New scene), so
        # `BR_Z (REG_WIFE_ID == 11)` / `STORE (FLG_X = 1)` assemble. Best effort too.
        try:
            self.container.install_asm_resolver(self._emf_vars)
        except Exception:
            pass

    def _expr_vars(self, expr_off):
        """[(name, bit_offset, width, packed_enc)] for every emdeb.bin packed variable
        referenced by the expression at `expr_off` in the current bank (for the tooltip
        legend). Empty if the resolver/emdeb table isn't available."""
        if self.container is None or self._emf_vars is None or self._bank is None:
            return []
        d = self._bank.data
        n = len(d)
        p = expr_off
        out = []
        for _ in range(64):
            if not (0 <= p < n) or d[p] == 0:
                break
            t = d[p]
            if t == 0x02:
                enc = int.from_bytes(d[p + 1:p + 5], "little")
                bo, w, _sg = self.container.unpack_var(enc)
                v = self._emf_vars.by_offset(bo)
                out.append((v.name if v else "var:0x%X" % enc, bo, w, enc))
                p += 5
            elif t == 0x01:
                p += 5
            elif t in (0x17, 0x18):
                p += 2
            elif t in (0x19, 0x1A, 0x06):
                p += 3
            elif 0x07 <= t <= 0x10 or t in (0x14, 0x15, 0x16):
                p += 1
            elif t >= 0x80:
                p += 1
            else:
                break
        return out

    def _switch_locale(self):
        loc = self.loc_var.get()
        if loc == self.locale:
            return
        # The archive being left stays cached WITH its unsaved edits (Save dialogue… / Install
        # to game… write every edited locale), so switching discards nothing.
        if self.textarc is not None:
            self._sibling_arcs[self.locale] = self.textarc
            if self.text_dirty:
                self._sibling_dirty.add(self.locale)
        self._load_text(loc)
        self.text_dirty = loc in self._sibling_dirty
        self._sibling_dirty.discard(loc)
        if self._scene is not None:
            self._render_scene()
        self._status(f"Locale -> {loc}" + ("" if self.textarc is not None else
                                            f"  (rf3mc.{loc} is not in this source)")
                     + self._dirty_tag())

    def _dlg(self, line_id):
        if self.textarc is None or line_id is None:
            return None
        try:
            return self.textarc.text(line_id)
        except Exception:
            return None

    def _open_script_file(self):
        if not self.confirm_discard("open another rf3.mc"):
            return
        f = filedialog.askopenfilename(title="Open rf3.mc", filetypes=[("MYCF script", "*.mc"), ("All", "*.*")])
        if not f:
            return
        raw = pathlib.Path(f).read_bytes()
        try:
            self.container = script.Container(raw)
        except Exception as e:
            messagebox.showerror("rf3.mc", str(e)); return
        self._install_var_resolver()
        # try to find a sibling rf3mc.<locale>
        sib = pathlib.Path(f).parent
        self.reader = self.reader or (lambda n, d=sib: (d / n).read_bytes() if (d / n).is_file() else None)
        self._sibling_arcs.clear(); self._sibling_dirty.clear(); self._sibling_missing.clear()
        self._load_text(self.locale)
        self.text_dirty = False
        try:
            self.pad_locales_chk.config(state="normal")
        except tk.TclError:
            pass
        self.script_dirty = False
        self._reset_history()
        self._status(f"Opened {pathlib.Path(f).name}: {len(self.container.banks)} banks")

    # ---- search / browse ------------------------------------------------- #
    def _search(self):
        if self.container is None:
            return
        q = self.search_var.get().strip()
        if not q:
            return
        mode = self.search_mode.get()
        try:
            self.parent.config(cursor="watch"); self.parent.update()
        except tk.TclError:
            pass
        try:
            if mode == "dialogue":
                if self.textarc is None:
                    messagebox.showinfo("No dialogue",
                                        f"rf3mc.{self.locale} not loaded — can't search text.")
                    return
                self._status(f"Searching dialogue for {q!r}…")
                hits = script.find_scenes_with_dialog(self.container, q, self._dlg)
                self._results = [(bk, sc) for bk, sc, _ids in hits]
                self._fill_scene_list(lambda n: f"{n} scene(s) say {q!r}")
            else:
                self._search_structural(mode, q)
        finally:
            try:
                self.parent.config(cursor="")
            except tk.TclError:
                pass

    def _search_structural(self, mode, q):
        """Find scenes by EMF entry name / speaker / opcode (not dialogue text)."""
        ql = q.lower()
        try:                              # opcode mode also accepts a numeric opcode ("92", "0x5c")
            qnum = int(q, 0)
        except ValueError:
            qnum = None
        em = self._em_get() if mode == "EMF entry" else None
        results = []
        seen = set()                 # (bank, entry_pc) -- discovered scenes overlap heavily
        for bk, sc in script.iter_scenes(self.container):
            key = (bk.index, sc.entry_pc)
            if key in seen:
                continue
            hit = False
            for pc, st in sc.stmts.items():
                if mode == "EMF entry":
                    if st.op in script.EMF_ENTRY_OPS and st.args and em:
                        ai = script.EMF_ENTRY_OPS[st.op]
                        if ai < len(st.args):
                            try:
                                nm = em.names.entry_name(int(script.arg_repr(bk.data, st.args[ai])))
                            except (ValueError, TypeError):
                                nm = None
                            if nm and ql in nm.lower():
                                hit = True; break
                elif mode == "speaker":
                    if script.is_portrait_op(st.op):
                        nm = script.portrait_speaker_name(st.op) or ""
                        if ql in nm.lower():
                            hit = True; break
                elif mode == "opcode":
                    if st.op < 0xFFF0:
                        if qnum is not None and st.op == qnum:
                            hit = True; break
                        if ql and (ql in script.opcode_mnemonic(st.op).lower()
                                   or ql in script.opcode_name(st.op).lower()):
                            hit = True; break
            if hit:
                seen.add(key)
                results.append((bk, sc))
        self._results = results
        self._fill_scene_list(f"{len(results)} scene(s) match {mode} {q!r}")

    def show_bank(self, index, entry_pc=None):
        """Focus the scene list on a specific bank (public entry point, e.g. the map
        editor's 'Events on this map' -> tail[mapId]). If `entry_pc` is given, the scene
        starting there is pre-selected and opened."""
        if self.container is None or not (0 <= index < len(self.container.banks)):
            return False
        bank = self.container.banks[index]
        try:
            self.bank_var.set(str(index))
        except tk.TclError:
            pass
        self._results = [(bank, sc) for sc in script.disassemble_bank(bank)]
        self._fill_scene_list(lambda n: f"bank {index} ({bank.kind}): {n} scenes")
        self._entries_show(bank)
        pick = 0
        if entry_pc is not None:
            pick = next((i for i, (_b, sc) in enumerate(self._results)
                         if sc.entry_pc == entry_pc), 0)
        if self._results:                      # open a scene so the pane isn't blank
            self.scene_list.selection_clear(0, "end")
            self.scene_list.selection_set(pick)
            self.scene_list.see(pick)
            self._on_scene_pick()
        else:                                  # nothing to show: the Entries tab is where a
            try:                               # first scene gets minted (New scene…)
                self._topnb.select(self._entries_tab)
            except tk.TclError:
                pass
            self._status(f"bank {index} ({bank.kind}) has no scenes — Entries tab: New scene… "
                         f"mints the first one{self._dirty_tag()}")
        return True

    # ---- xrefs: who calls / jumps here ----------------------------------- #
    def _show_xrefs(self):
        """List every statement in the current bank whose control flow targets the
        SELECTED statement (or, with nothing selected, the current scene's entry) —
        CALL/JMP/BR_*/SWITCH/PROMPT sites — plus the scene's own type-table dispatch
        row when the target is a registered entry. Double-click a row to jump to the
        calling statement. Targets are bank-local u16 pcs, so the graph is per-bank."""
        if self._bank is None or self._scene is None:
            self._status("open a scene first, then Xrefs")
            return
        target = self._sel[0] if self._sel else self._scene.entry_pc
        rows = collect_xrefs(self._bank, target)
        # engine-dispatch origin: a typed scene starting at the target is reachable
        # from the type table (event-driven), not just from other scenes.
        dispatch = [sc for sc in script.disassemble_bank(self._bank)
                    if sc.entry_pc == target and sc.action_type >= 0]
        cpos = self.container.banks.index(self._bank) if self.container else -1

        win = tk.Toplevel(self.parent)
        win.title("Xrefs to 0x%04x  (bank %d)" % (target, cpos))
        win.geometry("640x360")
        hdr = "%d caller site(s)" % len(rows)
        if dispatch:
            hdr += "  ·  also engine-dispatched: type-table type %s" % (
                ", ".join(str(sc.action_type) for sc in dispatch))
        ttk.Label(win, text=hdr, anchor="w").pack(fill="x", padx=6, pady=4)
        fr = ttk.Frame(win); fr.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        sb = ttk.Scrollbar(fr); sb.pack(side="right", fill="y")
        lb = tk.Listbox(fr, yscrollcommand=sb.set, font=("Consolas", 10))
        lb.pack(side="left", fill="both", expand=True)
        sb.config(command=lb.yview)
        for entry_pc, atype, from_pc, mnem in rows:
            styp = "type %d" % atype if atype >= 0 else "discovered"
            lb.insert("end", "%-12s @0x%04x   in scene @0x%04x (%s)"
                      % (mnem, from_pc, entry_pc, styp))
        if not rows:
            lb.insert("end", "(no in-bank callers — engine dispatch or data-driven entry)")

        def _jump(_e=None):
            s = lb.curselection()
            if not s or s[0] >= len(rows):
                return
            entry_pc, _atype, from_pc, _m = rows[s[0]]
            if cpos >= 0 and self.show_bank(cpos, entry_pc=entry_pc):
                self.parent.after_idle(lambda: self._scroll_to_pc(from_pc))
        lb.bind("<Double-Button-1>", _jump)
        ttk.Label(win, text="double-click a row to jump to the calling statement",
                  foreground="#888", anchor="w").pack(fill="x", padx=6, pady=(0, 4))

    def _scroll_to_pc(self, pc):
        """Scroll the disassembly to the statement at `pc` and highlight its line — used when a
        map-editor NPC-spawn marker jumps here. `_disp` maps text-line -> (pc, Statement)."""
        line = next((ln for ln, (p, _st) in self._disp.items() if p == pc), None)
        if line is None:
            return
        try:
            self.text.see("%d.0" % line)
            self.text.tag_remove("pcfocus", "1.0", "end")
            self.text.tag_add("pcfocus", "%d.0" % line, "%d.end" % line)
        except tk.TclError:
            pass

    def _list_bank(self):
        if self.container is None:
            return
        try:
            bi = int(self.bank_var.get(), 0)
            bank = self.container.banks[bi]
        except (ValueError, IndexError):
            messagebox.showinfo("Bank", "Enter a valid bank number (0..%d)."
                                % (len(self.container.banks) - 1 if self.container else 0))
            return
        self._results = [(bank, sc) for sc in script.disassemble_bank(bank)]
        self._fill_scene_list(lambda n: f"bank {bi}: {n} scenes")
        self._entries_show(bank)

    def _fill_scene_list(self, status):
        # Sort scenes by (bank index, entry_pc) so the list reads in-bank in
        # ascending @0x offset order. disassemble_bank() yields scenes grouped
        # by action_type (via the bank's type table) which interleaves offsets;
        # sorting here makes the presentation order match the bytecode layout
        # without changing the raw disassembly.
        self._results.sort(key=lambda bk_sc: (bk_sc[0].index, bk_sc[1].entry_pc))
        # A bank's type table can register the same bytecode offset under several
        # event-ids/action-types, so disassemble_bank()/iter_scenes() yield the
        # identical scene more than once -- that is what produced duplicate rows in
        # dialogue search. Collapse scenes that share a (bank, entry_pc) to one row.
        deduped, seen = [], set()
        for bk, sc in self._results:
            key = (bk.index, sc.entry_pc)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((bk, sc))
        self._results = deduped
        self.scene_list.delete(0, "end")
        for bk, sc in self._results:
            preview = ""
            for st in sc.stmts.values():
                if st.mnem == "DIALOG":
                    t = self._dlg(st.dialog_id)
                    if t:
                        preview = t.splitlines()[0][:38]
                        break
            if not preview:                              # no dialogue -- summarise by the first
                preview = script.scene_summary(sc)       # meaningful op so the row isn't blank
            flag = "" if sc.ok else " [partial]"
            self.scene_list.insert("end", f"b{bk.index} @0x{sc.entry_pc:04x} ({len(sc.stmts)}){flag}  {preview}")
        # `status` may be a callable(count)->str so the reported count reflects the
        # de-duplicated rows actually shown, not the raw pre-dedup hit count.
        if callable(status):
            status = status(len(self._results))
        self._status(status)

    def _on_scene_pick(self):
        s = self.scene_list.curselection()
        if not s:
            return
        self._bank, self._scene = self._results[s[0]]
        self._render_scene()

    # ---- render + select ------------------------------------------------- #
    def _insert_label_col(self, pc):
        """Insert the fixed-width branch-label column for `pc` ('L1234:' max = 6
        chars + 1 separator space), colored via the 'lbl' tag. Empty when the pc
        is not a branch target, so every statement body starts at column 8."""
        lbl = self._labels.get(pc, "")
        self.text.insert("end", "%-7s" % ((lbl + ":") if lbl else ""), "lbl")

    def _fmt_stmt(self, st):
        # NOTE: the branch-target label is NOT part of this string — _render_scene
        # inserts it as its own fixed-width column (tag "lbl") so it gets its own
        # color and can never run into the address ("L6306f56:" bug).
        head = f"{st.pc:04x}:  "
        if st.mnem == "DIALOG":
            raw_t = self._dlg(st.dialog_id)
            if raw_t is None:                            # id not resolvable in this locale --
                # flag it instead of a silent blank: a bad retarget, a mismatched bundle, or a
                # line missing in the current locale (vs a present-but-empty line, which is "").
                why = "not in this locale" if self.textarc is not None else "text not loaded"
                return f"{head}DIALOG #{st.dialog_id}  [no text: {why}]"
            t = raw_t.replace("\n", " / ")
            return f"{head}DIALOG #{st.dialog_id}  \"{t[:70]}\""
        if st.op < 0xFFF0:
            arg_strs = (script.stmt_arg_strs(self._bank.data, st) if st.args else [])
            note = ""
            # (SetSpeaker$<tag> ops carry their speaker name in the mnemonic already,
            # and render_action prepends the side (left/right) + face/emote mood names
            # as pretty leading args -- no ';left'/';right' comment needed.)
            if st.op in script.EMF_ENTRY_OPS:
                ai = script.EMF_ENTRY_OPS[st.op]
                if ai < len(st.args):
                    try:
                        nm = script.emf_entry_name(
                            int(script.arg_repr(self._bank.data, st.args[ai])))
                        if nm:
                            note += f"   ; {nm}"
                    except (ValueError, TypeError):
                        pass
            # value-decoded display, e.g. QueryPlayerVariable(Skill, Mining)
            special = script.render_action(st.op, arg_strs)
            body = special or f"{script.opcode_mnemonic(st.op)}({', '.join(arg_strs)})"
            return f"{head}{body}{note}"
        cond = ""
        if st.expr_refs:                                 # show the actual condition/value
            kw = "val" if st.mnem in ("STORE",) else "cond"
            parts = []
            for e in st.expr_refs:
                if e is None:
                    continue
                txt, _ = script.disasm_expr(self._bank.data, e)
                parts.append(txt)
            if parts:
                cond = f"  {kw}=({', '.join(parts)})"
        # PROMPT_CHOICE / PROMPT_CHOICE_FORCED: pretty-print with cancel branch, per-choice
        # targets, and choice text resolved via rf3mc.<locale> when available.
        # PROMPT_CHOICE layout: target[0]=CANCEL, target[1..N]=choice[0..N-1].
        if st.mnem == "PROMPT_CHOICE" and st.items:
            parts = []
            if st.code_targets:
                parts.append(f"CANCEL->{self._labels.get(st.code_targets[0], '0x%04x' % st.code_targets[0])}")
            for k, item in enumerate(st.items):
                tgt = st.code_targets[k + 1] if k + 1 < len(st.code_targets) else None
                tgt_txt = self._labels.get(tgt, "0x%04x" % tgt) if tgt is not None else "?"
                txt = (self._dlg(item) or "").replace("\n", " / ")
                if txt:
                    parts.append(f'"{txt[:60]}"->{tgt_txt}')
                else:
                    parts.append(f"#{item}->{tgt_txt}")
            return f"{head}PROMPT_CHOICE{cond}  " + " | ".join(parts)
        if st.mnem == "PROMPT_CHOICE_FORCED" and st.items:
            parts = []
            for k, item in enumerate(st.items):
                tgt = st.code_targets[k] if k < len(st.code_targets) else None
                tgt_txt = self._labels.get(tgt, "0x%04x" % tgt) if tgt is not None else "?"
                txt = (self._dlg(item) or "").replace("\n", " / ")
                if txt:
                    parts.append(f'"{txt[:60]}"->{tgt_txt}')
                else:
                    parts.append(f"#{item}->{tgt_txt}")
            return f"{head}PROMPT_CHOICE_FORCED{cond}  " + " | ".join(parts)
        tg = ", ".join(self._labels.get(t, "0x%04x" % t) for t in st.code_targets if t is not None)
        extra = f" {st.items[0]}" if st.mnem == "FRAME" and st.items else ""  # local-slot count
        return f"{head}{st.mnem}{extra}{cond}{(' -> ' + tg) if tg else ''}"

    def _render_scene(self):
        sc = self._scene
        self._disp = {}
        self._labels = script.scene_labels(sc)
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        typ = "discovered" if sc.action_type < 0 else f"type {sc.action_type}"
        hdr = (f"; bank {sc.bank_index} ({sc.kind})  {typ}  "
               f"entry @0x{sc.entry_pc:04x}  {len(sc.stmts)} statements"
               + ("" if sc.ok else f"   [PARTIAL: {sc.error}]"))
        self.text.insert("end", hdr + "\n", "hdr")
        ln = 1
        # --- "plays when" gates: EvalCondA/B(entry) -> BR_Z guards read as the
        #     trigger condition for the branch that follows. Shown up top so the
        #     scene reads "fires when <emdeb.bin condition>" before its body.
        gates = [t for t in self._scene_em_triggers(sc) if t["kind"] == "gate"]
        if gates:
            self.text.insert("end", "; Event-Manager gate(s) — the guarded branch:\n", "hdr"); ln += 1
            for t in gates:
                which = "b" if t["op"] == 372 else "a"
                cond = self._em_cond_text(t["entry_obj"], which) or "(condition unavailable)"
                self.text.insert("end", ";   %s %s  %s\n" % (t["name"], t["verb"], cond[:170]), "dlg")
                ln += 1
        lin = script.linearize(sc)
        shown = {pc for pc, _ in lin}
        for pc, st in lin:                      # execution order (trampolines inlined)
            ln += 1
            tag = "dlg" if st.mnem == "DIALOG" else ()
            self._insert_label_col(pc)
            self.text.insert("end", self._fmt_stmt(st) + "\n", tag)
            self._disp[ln] = (pc, st)
        rest = [(pc, st) for pc, st in sc.stmts.items() if pc not in shown]
        if rest:
            ln += 1
            self.text.insert("end", "; --- other branches / paths ---\n", "hdr")
            for pc, st in rest:
                ln += 1
                tag = "dlg" if st.mnem == "DIALOG" else ()
                self._insert_label_col(pc)
                self.text.insert("end", self._fmt_stmt(st) + "\n", tag)
                self._disp[ln] = (pc, st)
        self.text.config(state="disabled")
        self._sel = None
        self._set_editor_enabled(False)
        self.sel_lbl.config(text="(click a statement above)")
        self._render_analysis(sc)
        self._source_load()                         # Source tab follows the selected scene
        if self._bank is not self._entries_bank:    # Entries tab follows the scene's bank
            self._entries_show(self._bank)
        self._status(f"bank {sc.bank_index} @0x{sc.entry_pc:04x} · "
                     f"Ctrl-hover an opcode for details{self._dirty_tag()}")

    # ---- scene analysis (structured breakdown of all decoded knowledge) --- #
    # script ops that carry a raw GameFlags bit id (base-relative in-engine, so we
    # show the raw id, not an emflags name -- those don't line up 1:1).
    _FLAG_OPS = {318: "SetPackedGameFlag", 443: "SetGameFlagBit",
                 444: "SetGameFlagBitIfCond", 445: "QueryGameFlagBit"}

    def _render_analysis(self, sc):
        A = self.analysis
        A.config(state="normal")
        A.delete("1.0", "end")

        def put(s, tag=()):
            A.insert("end", s, tag)

        typ = "discovered" if sc.action_type < 0 else "type %d" % sc.action_type
        put("Scene  bank %d (%s)  %s  entry @0x%04x\n" % (sc.bank_index, sc.kind, typ, sc.entry_pc), "hdr")
        put("%d statements%s\n\n" % (len(sc.stmts), "" if sc.ok else "   [PARTIAL: %s]" % sc.error), "k")

        stmts = list(sc.stmts.items())
        # --- speakers ---
        spk = OrderedDict()
        for _pc, st in stmts:
            if script.is_portrait_op(st.op):
                nm = script.portrait_speaker_tag(st.op) or "?"
                side = "R" if script.portrait_speaker_slot(st.op)[1] else "L"
                spk["%s (%s)" % (nm, side)] = spk.get("%s (%s)" % (nm, side), 0) + 1
        if spk:
            put("Speakers\n", "h")
            for k, n in spk.items():
                put("  %-22s x%d\n" % (k, n), "k")
            put("\n")

        # --- dialogue transcript ---
        lines = [(pc, st.dialog_id) for pc, st in stmts if st.mnem == "DIALOG"]
        if lines:
            put("Dialogue  (%d lines)\n" % len(lines), "h")
            cur = None
            for pc, lid in lines:
                # prefix each line with the most recent speaker before it
                sp = None
                for p2, st2 in stmts:
                    if p2 > pc:
                        break
                    if script.is_portrait_op(st2.op):
                        sp = script.portrait_speaker_tag(st2.op)
                if sp != cur:
                    cur = sp
                    put("  %s:\n" % (sp or "(narration)"), "k")
                txt = (self._dlg(lid) or "").replace("\n", " ")
                put("    #%-6d %s\n" % (lid, txt[:90]), "dlg")
            put("\n")

        # --- Event Manager triggers (bridge ops -> named entries + decoded cond/action) ---
        em = self._em_get()
        trigs = self._scene_em_triggers(sc)
        if trigs:
            gates = sum(1 for t in trigs if t["kind"] == "gate")
            hdr = "Event Manager triggers  (%d" % len(trigs)
            hdr += ", %d gate%s)\n" % (gates, "" if gates == 1 else "s") if gates else ")\n"
            put(hdr, "h")
            label = {"gate": "GATE plays-when", "set": "set flag if cond", "run": "run actions"}
            for t in trigs:
                st_op = t["op"]
                lab = label[t["kind"]]
                if t["kind"] == "run":
                    lab = "run alt-actions" if st_op == 374 else "run actions"
                put("  @0x%04x %-18s %s\n" % (t["pc"], lab, t["name"]), "emf")
                e = t["entry_obj"]
                if e is None:
                    continue
                if t["kind"] in ("gate", "set"):
                    which = "b" if st_op == 372 else "a"
                    cond = self._em_cond_text(e, which)
                    if cond:
                        put("      %s: %s\n" % (t["verb"], cond[:220]), "k")
                else:
                    acts = e.actions if st_op == 373 else e.alt_actions
                    for a in (acts or [])[:6]:
                        put("      do:   %s\n" % a.pretty(em.names), "flag")
            put("\n")

        # --- direct flag / variable ops ---
        flagops = [(pc, st) for pc, st in stmts if st.op in self._FLAG_OPS]
        varops = [(pc, st) for pc, st in stmts
                  if "VarArray" in script.opcode_name(st.op) and "Write" in script.opcode_name(st.op)]
        if flagops or varops:
            put("Flags / variables written\n", "h")
            for pc, st in flagops:
                vals = ", ".join((script.stmt_arg_strs(self._bank.data, st) if st.args else []))
                put("  @0x%04x %-20s (%s)\n" % (pc, self._FLAG_OPS[st.op], vals), "flag")
            for pc, st in varops:
                vals = ", ".join((script.stmt_arg_strs(self._bank.data, st) if st.args else []))
                put("  @0x%04x %-20s (%s)\n" % (pc, script.opcode_mnemonic(st.op), vals), "flag")
            if flagops:
                put("  (flag ids are engine base-relative -- not emflags names)\n", "warn")
            put("\n")

        # --- control-flow shape ---
        from collections import Counter
        cf = Counter()
        for _pc, st in stmts:
            if st.op >= 0xFFF0:
                cf[st.mnem] += 1
            elif st.op in (75, 76):                 # ConsumeChoiceCommitResult (choice menu)
                cf["CHOICE"] += 1
        if cf:
            put("Control flow\n", "h")
            put("  " + "  ".join("%s x%d" % (k, v) for k, v in sorted(cf.items())) + "\n", "k")
        A.config(state="disabled")

    # ---- hover tooltip (explains the opcode + its args) ------------------ #
    # The tooltip is Ctrl-gated: it only appears while Ctrl is held and the mouse
    # is over a statement. Motion keeps track of what's under the pointer so a
    # later Ctrl press can show it with the mouse held still.
    def _on_disasm_hover(self, e):
        if not getattr(self, "_disp", None):
            return
        ln = int(self.text.index("@%d,%d" % (e.x, e.y)).split(".")[0])
        entry = self._disp.get(ln)
        if not entry:
            self._in_disasm = False
            self._hide_tip()
            return
        pc, st = entry
        self._in_disasm = True
        self._tip_st = st
        self._tip_hover_ln = ln
        self._tip_xy = (e.x_root + 16, e.y_root + 20)
        if not (e.state & 0x0004):                      # Ctrl not held -> no tooltip
            self._hide_tip()
            return
        if self._tip_line == (ln, True):
            return                                      # already showing this line
        self._tip_line = (ln, True)
        self._show_tip(*self._tip_xy, self._rich_tip_text(st))

    def _on_disasm_leave(self, *_):
        self._in_disasm = False
        self._hide_tip()

    def _on_ctrl_toggle(self, ctrl):
        """Ctrl pressed/released -> show/hide the rich tooltip for whatever the mouse
        is currently over, without waiting for the pointer to move."""
        if not ctrl:                                    # released -> hide
            self._hide_tip()
            return
        if not self._in_disasm or self._tip_st is None or self._tip_xy is None:
            return                                      # not over a statement
        if self._tip_line == (self._tip_hover_ln, True):
            return                                      # already showing it
        self._tip_line = (self._tip_hover_ln, True)
        self._show_tip(self._tip_xy[0], self._tip_xy[1],
                       self._rich_tip_text(self._tip_st))

    def _rich_tip_text(self, st):
        """Detailed Ctrl-hover tooltip: prototype, per-argument explanation, and what
        the instruction does -- built from opcode_meta + the decoded flag/EMF/speaker data."""
        # --- DIALOG (a control op with its own shape) ---
        if st.mnem == "DIALOG":
            t = (self._dlg(st.dialog_id) or "").strip()
            out = ["DIALOG(line id)", "",
                   "Show one dialogue line and wait for the player to advance. The speaker "
                   "and portrait come from the preceding SetSpeaker.", "",
                   "Arguments:",
                   "  line id = %d  — index into rf3mc.<locale>" % st.dialog_id]
            if t:
                out.append('    "%s"' % t.replace("\n", " "))
            return "\n".join(out)
        # --- other control ops ---
        if st.op >= 0xFFF0:
            proto = {"CALL": "CALL(target)", "JMP": "JMP(target)",
                     "BR_Z": "BR_Z(cond_expr, target)", "BR_NZ": "BR_NZ(cond_expr, target)",
                     "BR_RET": "BR_RET(cond_expr)", "STORE": "STORE(var_expr)",
                     "FRAME": "FRAME(local_slots)", "RET": "RET()",
                     "SWITCH_EQ": "SWITCH_EQ(sel, n, target[n])",
                     "SWITCH_GE": "SWITCH_GE(sel, n, target[n])",
                     "PROMPT_CHOICE_FORCED": "PROMPT_CHOICE_FORCED(n, target[n], items[n])",
                     "PROMPT_CHOICE": "PROMPT_CHOICE(n, cancel_target, target[n], items[n])",
                     "JMP_IND": "JMP_IND(n, target[n])",
                     "RAND_BR": "RAND_BR(n, target[n], weight[n])"}.get(st.mnem, st.mnem + "()")
            desc = script.control_tooltip(st.mnem)
            tg = [self._labels.get(t, "0x%04x" % t) for t in st.code_targets if t is not None]
            out = [proto, "", desc]
            if st.expr_refs:                             # decode the condition/value expr
                kw = "value" if st.mnem == "STORE" else "condition"
                legend = []
                for e in st.expr_refs:
                    if e is None:
                        continue
                    txt, _ = script.disasm_expr(self._bank.data, e)
                    out += ["", "%s (expr@0x%04x):" % (kw, e), "    " + txt]
                    legend += self._expr_vars(e)
                if legend:                               # emdeb.bin variable details
                    out += ["", "variables (g_gameFlagsBuffer):"]
                    for name, bo, w, enc in legend:
                        kind = "flag" if w == 1 else "%d-bit reg" % w
                        out.append("    %s  — bit %d, %s  (packed 0x%X)" % (name, bo, kind, enc))
            if getattr(st, "items", None):               # PROMPT_CHOICE options: surface the line
                # id of each choice so the author can edit its text (type the #id in the line#
                # field, then Apply text) -- choice items aren't standalone DIALOG statements.
                out += ["", "choices (edit text: type the #id in line# + Apply text):"]
                _cancel = (st.mnem == "PROMPT_CHOICE")
                if _cancel and st.code_targets:
                    out.append("    CANCEL -> %s" % self._labels.get(
                        st.code_targets[0], "0x%04x" % st.code_targets[0]))
                for _k, _item in enumerate(st.items):
                    _ti = _k + 1 if _cancel else _k
                    _tgt = st.code_targets[_ti] if _ti < len(st.code_targets) else None
                    _tt = self._labels.get(_tgt, "0x%04x" % _tgt) if _tgt is not None else "?"
                    _ctxt = (self._dlg(_item) or "").replace("\n", " / ")
                    _lbl = ('"%s" ' % _ctxt[:44]) if _ctxt else ""
                    out.append("    #%d %s-> %s" % (_item, _lbl, _tt))
            if tg:
                out += ["", "targets: " + ", ".join(tg)]
            return "\n".join(out)
        # --- action op: prototype + per-arg + what it does ---
        op = st.op
        out = [script.opcode_prototype(op), "", script.opcode_describe(op)]
        # speaker cue: decode who/side/emote
        sp = script.portrait_speaker_slot(op)
        if sp is not None:
            out.append("Speaker: %s   Side: %s"
                       % (script.portrait_speaker_name(op), "left" if sp[1] == 0 else "right"))
        out.append("")
        out.append("Arguments:")
        vals = (script.stmt_arg_strs(self._bank.data, st) if st.args else [])
        names = script.opcode_arg_names(op)
        if not vals:
            out.append("  (none)")
        for i, v in enumerate(vals):
            nm = names[i] if i < len(names) else "arg%d" % i
            hint = script.opcode_arg_hint(op, i)
            # SetSpeaker args after the face are positional-flexible: pick the label
            # from the VALUE (target handle vs emote vs voice sfx) so 2-arg cues aren't
            # mislabelled "emote/mood" when they're really the target.
            if sp is not None and i >= 1:
                try:
                    iv = int(v, 0) if isinstance(v, str) else int(v)
                except ValueError:
                    iv = None
                if iv is not None:
                    if iv >= 0x1000000:
                        nm, hint = "target", script.opcode_arg_hint_by_name("target")
                    elif iv >= 0x1F0:
                        nm, hint = "voice sfx id", "plays a voice line instead of an emote"
                    elif iv:
                        nm, hint = "emote/mood", script.opcode_arg_hint_by_name("emote/mood")
            line = "  %s = %s" % (nm, v)
            if nm.lower() == "emote/mood":            # decode emote id -> mood name inline
                try:
                    em = script.portrait_emote_name(int(v, 0) if isinstance(v, str) else int(v))
                    if em:
                        line += "  (%s)" % em
                except (ValueError, TypeError):
                    pass
            else:                                     # decode enum-picker args (item/char/room/
                try:                                  # skill/outfit/effect ids) -> readable name
                    lbl = script.enum_arg_label(op, i, int(v, 0) if isinstance(v, str) else int(v))
                    if lbl:
                        line += "  (%s)" % lbl
                except (ValueError, TypeError):
                    pass
            out.append(line)
            # tag-3/4 constants (actor(..) / map(..) / localvar[N] / globalvar[N]): say what
            # the number is -- or that this slot has no verified meaning (script.leaf_tooltip)
            if i < len(st.args) and st.args[i] is not None:
                leaf = script.leaf_tooltip(self._bank.data, st.args[i], op, i)
                if leaf:
                    out.append("      = %s" % leaf)
                fnote = script.flag_arg_note(self._bank.data, st.args[i], op, i)
                if fnote:
                    out.append("      flag: %s" % fnote)
            if hint:
                out.append("      — %s" % hint)
        # EMF bridge ops: resolve the referenced entry name
        if op in script.EMF_ENTRY_OPS:
            ai = script.EMF_ENTRY_OPS[op]
            if ai < len(st.args):
                try:
                    nm = script.emf_entry_name(int(vals[ai]))
                    if nm:
                        out.append("")
                        out.append("Event Manager entry: %s" % nm)
                except (ValueError, TypeError):
                    pass
        tech = script.opcode_name(op)
        out.append("")
        out.append("op %d · %s" % (op, tech))
        return "\n".join(out)

    def _attach_tip(self, widget, text):
        """Attach a plain hover tooltip to an edit-panel control (button / field / combobox),
        reusing the same popup as the disassembly Ctrl-hover -- so the editor's actions are
        self-explanatory on hover, not only via the README. `text` may be a callable that
        returns the text at hover time (the New-scene recipe picker's current recipe)."""
        widget.bind("<Enter>", lambda e, t=text: self._show_tip(e.x_root + 14, e.y_root + 18,
                                                              t() if callable(t) else t),
                    add="+")
        widget.bind("<Leave>", self._hide_tip, add="+")

    def _show_tip(self, x, y, text):
        if self._tip is None:
            self._tip = tk.Toplevel(self.parent)
            self._tip.wm_overrideredirect(True)
            try:
                self._tip.attributes("-topmost", True)
            except tk.TclError:
                pass
            self._tip_lbl = tk.Label(self._tip, justify="left", anchor="w",
                                     bg="#1b1b22", fg="#e6e6ee", font=("Segoe UI", 9),
                                     relief="solid", borderwidth=1, padx=8, pady=6)
            # word-wrap long lines at ~100 characters. Segoe UI is proportional, so
            # measure the pixel width of 100 chars of representative prose.
            sample = ("the quick brown fox jumps over the lazy dog " * 3)[:100]
            self._tip_lbl.config(wraplength=tkfont.Font(font=self._tip_lbl["font"]).measure(sample))
            self._tip_lbl.pack()
        self._tip_lbl.config(text=text)
        self._tip.wm_geometry("+%d+%d" % (x, y))
        self._tip.deiconify()

    def _hide_tip(self, *_):
        self._tip_line = None
        if self._tip is not None:
            self._tip.withdraw()

    def _on_disasm_click(self, e):
        idx = self.text.index("@%d,%d" % (e.x, e.y))
        ln = int(idx.split(".")[0])
        if ln not in self._disp:
            return
        pc, st = self._disp[ln]
        self._sel = (pc, st)
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", f"{ln}.0", f"{ln}.end")
        self._populate_editor(pc, st)

    # ---- editor ---------------------------------------------------------- #
    def _set_editor_enabled(self, on, *, dialogue=False, action=False, portrait=False, expr=False):
        st_d = "normal" if (on and dialogue) else "disabled"
        st_a = "normal" if (on and action) else "disabled"
        # value-edit row (arg#/value/Set-value): action args OR a control-op guard/value
        # literal (BR_Z threshold, STORE value). args-CSV + enum picker stay action-only.
        st_v = "normal" if (on and (action or expr)) else "disabled"
        self.line_ent.config(state=st_d)
        self.retarget_btn.config(state=st_d)
        self.apply_text_btn.config(state=st_d)
        self.text_box.config(state=("normal" if (on and dialogue) else "disabled"))
        self.args_ent.config(state=st_a)
        self.apply_args_btn.config(state=st_a)
        self.val_arg_spin.config(state=("readonly" if (on and (action or expr)) else "disabled"))
        self.val_ent.config(state=st_v)
        self.set_val_btn.config(state=st_v)
        # Enum picker follows the "set value" row's enabled/disabled state; its
        # actual values (and visibility of usable rows) is refreshed by
        # _val_arg_changed when an action statement is selected.
        if not (on and action):
            self.enum_combo.config(values=(), state="disabled")
            self.enum_var.set("")
            self._enum_lookup = {}
        st_p = "readonly" if (on and portrait) else "disabled"
        self.spk_combo.config(state=st_p)
        self.spk_side_combo.config(state=st_p)
        self.spk_btn.config(state=("normal" if (on and portrait) else "disabled"))
        st_sel = "normal" if on else "disabled"        # structural ops: any selected stmt
        self.ins_dlg_btn.config(state=st_sel)
        self.ins_act_btn.config(state=st_sel)
        self.del_stmt_btn.config(state=st_sel)

    def _populate_editor(self, pc, st):
        disp = script.opcode_mnemonic(st.op) if st.op < 0xFFF0 else st.mnem
        lbl = f"bank {self._bank.index}  pc 0x{pc:04x}  {disp}"
        if st.op < 0xFFF0 and st.args:
            vals = ", ".join((script.stmt_arg_strs(self._bank.data, st) if st.args else []))
            lbl += f"  →  ({vals})"
        # one-line "what it does" so the op's purpose is visible on selection (not only via
        # Ctrl-hover): first sentence of the curated description, trimmed to stay compact.
        if st.op < 0xFFF0:
            _d = script.opcode_describe(st.op) or ""
        else:
            _d = script.control_tooltip(st.mnem) or ""   # "MNEM [cat]\n<desc>" -> keep the desc
            _d = _d.split("\n", 1)[1] if "\n" in _d else _d
        _d = _d.strip().split(". ")[0].rstrip(".")
        if _d:
            lbl += "\n" + (_d if len(_d) <= 150 else _d[:149] + "…")
        if st.expr_refs:                                # decode the condition/value expr
            kw = "val" if st.mnem == "STORE" else "cond"
            for e in st.expr_refs:
                if e is None:
                    continue
                txt, _ = script.disasm_expr(self._bank.data, e)
                lbl += f"\n{kw} @0x{e:04x}:  {txt}"
        if st.code_targets:                             # branch destinations -> pcs for `set-target`
            _tt = [f"[{k}]→0x{t:04x}" for k, t in enumerate(st.code_targets)]
            _shown = "  ".join(_tt[:10]) + ("  …" if len(_tt) > 10 else "")
            _note = " (0=cancel)" if st.op == 0xFFF4 else ""   # PROMPT_CHOICE: target[0] is cancel
            lbl += f"\ntargets{_note}:  {_shown}"
        raw = bytes(self._bank.data[pc:pc + st.size])   # exact on-disk bytes of this statement
        lbl += f"\nraw ({st.size} B):  {raw.hex(' ')}"
        self.sel_lbl.config(text=lbl)
        is_dlg = (st.mnem == "DIALOG")
        is_act = (st.op < 0xFFF0 and bool(st.args))
        is_portrait = script.is_portrait_op(st.op)
        # Control-op guard/value expressions (BR_Z/BR_NZ/BR_RET threshold, STORE value,
        # SWITCH selector) carry editable integer literals too -- collect them so the same
        # value-edit row can rewrite them in place (arg# = literal index into this list).
        self._ctrl_lits = []
        if st.op >= 0xFFF0 and getattr(st, "expr_refs", None):
            for e in st.expr_refs:
                if e is not None:
                    self._ctrl_lits.extend(script.expr_literals(self._bank.data, e))
        # PROMPT_CHOICE options are editable via the value row too (arg# = option, value = line id)
        is_choice = st.op in (0xFFF4, 0xFFF5)
        is_expr = bool(self._ctrl_lits) or is_choice
        self._set_editor_enabled(True, dialogue=is_dlg, action=is_act,
                                 portrait=is_portrait, expr=is_expr)
        if is_choice:
            _items = getattr(st, "items", []) or []
            self.val_arg_spin.config(to=max(0, len(_items) - 1))
            self.val_arg.set("0")
            self.hint_lbl.config(
                text="choice options (arg# = option, value = new rf3mc line id):  "
                     + "  ·  ".join(f"[{i}]→{it}" for i, it in enumerate(_items)))
        if is_portrait:
            slot, par = script.portrait_speaker_slot(st.op)
            self.spk_var.set(self._spk_values[slot] if slot < len(self._spk_values) else str(slot))
            self.spk_side.set("left" if par == 0 else "right")
        else:
            self.spk_var.set("")
        if is_dlg:
            self.line_var.set(str(st.dialog_id))
            self.text_box.config(state="normal")
            self.text_box.delete("1.0", "end")
            self.text_box.insert("1.0", self._dlg(st.dialog_id) or "")
        else:
            self.line_var.set("")
            self.text_box.config(state="normal"); self.text_box.delete("1.0", "end")
            self.text_box.config(state="disabled")
        # action: arg hints + the value spinbox range
        if is_act:
            hints = script.opcode_arg_names(st.op)
            if hints:
                txt = "args: " + "  ·  ".join(f"{i}={h}" for i, h in enumerate(hints))
                if is_portrait:
                    txt += ("\nemote/mood ids 186-192: 188 normal · 189 anger · 190 sad · "
                            "191 smile · 192 surprise  (row/kind-dependent; !/? in some scenes)")
                emf = self._emf_hint(st)
                if emf:
                    txt += "\n" + emf
                self.hint_lbl.config(text=txt)
            else:
                self.hint_lbl.config(text="")
            self.val_arg_spin.config(to=max(0, len(st.args) - 1))
            self.val_arg.set("0")
            self._val_arg_changed()
        elif is_expr:
            # control-op guard/value expr: arg# selects which literal (in stream order)
            kw = "value" if st.mnem == "STORE" else "threshold"
            n = len(self._ctrl_lits)
            self.hint_lbl.config(
                text=f"{st.mnem} {kw}: {n} editable literal%s in the guard/value expression — "
                     "arg# picks which (in reading order); Set value rewrites it in place."
                     % ("" if n == 1 else "s"))
            self.val_arg_spin.config(to=max(0, n - 1))
            self.val_arg.set("0")
            self._val_arg_changed()
        else:
            self.hint_lbl.config(text="")
            self.val_var.set("")
        self.args_var.set(", ".join(scriptasm.operand_text(self._bank.data, a, st.op, i)
                                    for i, a in enumerate(st.args)) if st.op < 0xFFF0 else "")

    def _val_arg_changed(self):
        """Pre-fill the value field with the chosen arg's current resolved value.
        Also (re)populate the enum picker when the selected arg has a known
        enum table -- e.g. TriggerWorldInteractionAction arg 0 becomes a
        dropdown of every dispatch id + its handler."""
        # Control-op guard/value expression: arg# picks a literal from self._ctrl_lits;
        # prefill its current value and enable Set-value. No enum picker for these.
        if self._sel and self._sel[1].op >= 0xFFF0 and self._ctrl_lits:
            self.enum_combo.config(values=(), state="disabled")
            self.enum_var.set(""); self._enum_lookup = {}
            try:
                i = int(self.val_arg.get())
            except ValueError:
                return
            if 0 <= i < len(self._ctrl_lits):
                self.val_var.set(str(self._ctrl_lits[i][1]))
                self.set_val_btn.config(state="normal")
            else:
                self.val_var.set(""); self.set_val_btn.config(state="disabled")
            return
        if not (self._sel and self._sel[1].op < 0xFFF0):
            return
        st = self._sel[1]
        try:
            i = int(self.val_arg.get())
        except ValueError:
            return
        current_val = None
        settable = False
        if 0 <= i < len(st.args):
            off = st.args[i]
            # arg_constant also reads actor(..) / map(..) typed constants, so their value
            # prefills and Set value patches them in place (keeping the tag) instead of
            # repointing the arg at a fresh plain literal.
            v, ok = script.arg_constant(self._bank.data, off)
            settable = script.arg_is_settable(self._bank.data, off)
            if ok and v is not None:
                current_val = v
            self.val_var.set(str(v) if (ok and v is not None) else "")
        # Enum picker: (op, arg_index) may resolve to a table like
        # WORLD_INTERACTION_ACTIONS. Empty list -> hide the picker.
        choices = script.enum_arg_choices(st.op, i)
        # "Set value" enablement: the base condition is "the arg is a
        # single-immediate the in-place patch can rewrite". For enum-valued
        # args we also allow it when the arg currently uses a non-editable
        # token (fixed push, computed expr, ...) because the container's
        # `set_action_arg_value_or_repoint` fallback will auto-append a fresh
        # literal expression and repoint the arg word at it.
        self.set_val_btn.config(
            state=("normal" if (settable or choices) else "disabled"))
        self._enum_lookup = {}
        if choices:
            display = []
            selected_display = ""
            for val, label, desc in choices:
                s = f"{val:>3} - {label}   ({desc})" if desc else f"{val:>3} - {label}"
                display.append(s)
                self._enum_lookup[s] = val
                if val == current_val:
                    selected_display = s
            self.enum_combo.config(values=display, state="readonly")
            self.enum_var.set(selected_display)
        else:
            self.enum_combo.config(values=(), state="disabled")
            self.enum_var.set("")

    def _enum_choice_picked(self, _event=None):
        """User picked a row in the enum dropdown -- copy its integer value
        into the val_var entry so a subsequent 'Set value' click patches the
        bytecode. The picker never patches on its own; the user still has to
        confirm."""
        picked = self._enum_lookup.get(self.enum_var.get())
        if picked is not None:
            self.val_var.set(str(picked))

    def _set_value(self):
        # PROMPT_CHOICE / PROMPT_CHOICE_FORCED: arg# = which option, value = the new rf3mc line
        # id that option displays (the choice analog of Retarget for a DIALOG). Handled before
        # the control-literal path because a choice's items are direct u32s, not expr literals.
        if self._sel and self._sel[1].op in (0xFFF4, 0xFFF5):
            pc, st = self._sel
            try:
                i = int(self.val_arg.get()); v = int(self.val_var.get(), 0)
            except ValueError:
                messagebox.showinfo("Set value", "option# and value must be integers."); return
            try:
                self._bank.set_choice_item(pc, i, v)
            except Exception as e:
                messagebox.showerror("Set value", str(e)); return
            self.script_dirty = True
            self._scene = script.disassemble_scene(self._bank, self._scene.action_type,
                                                   self._scene.entry_pc)
            self._render_scene()
            self._status(f"{st.mnem} @0x{pc:04x} option{i} → line id {v}{self._dirty_tag()}")
            return
        # Control-op guard/value expr (BR_Z threshold, STORE value): rewrite the chosen
        # literal in place via set_expr_value. Handled separately from action-op args.
        if self._sel and self._sel[1].op >= 0xFFF0 and self._ctrl_lits:
            self._set_ctrl_literal()
            return
        if not self._need(self._sel and self._sel[1].op < 0xFFF0, "Select an action statement."):
            return
        pc, st = self._sel
        try:
            i = int(self.val_arg.get()); v = int(self.val_var.get(), 0)
        except ValueError:
            messagebox.showinfo("Set value", "arg# and value must be integers."); return
        try:
            # Use the container-level helper so args pointing at a fixed 0/-1/1
            # push (or a too-narrow u8) get auto-repointed to a freshly-appended
            # literal expression instead of failing.
            result = self.container.set_action_arg_value_or_repoint(self._bank, pc, i, v)
        except Exception as e:
            messagebox.showerror("Set value", str(e)); return
        if result and result[0] == "unchanged":
            self._status(f"{st.mnem} @0x{pc:04x} arg{i} is already {v} — nothing changed"
                         f"{self._dirty_tag()}")
            return
        self.script_dirty = True
        self._scene = script.disassemble_scene(self._bank, self._scene.action_type, self._scene.entry_pc)
        self._render_scene()
        extra = ""
        if result and result[0] == "repointed":
            extra = f"  (repointed to new expr @0x{result[1]:04x})"
        self._status(f"{st.mnem} @0x{pc:04x} arg{i} = {v}{extra}{self._dirty_tag()}")

    def _set_ctrl_literal(self):
        """Rewrite one integer literal inside a control-op guard/value expression
        (BR_Z/BR_NZ/BR_RET threshold, STORE value, SWITCH selector). arg# selects which
        literal (index into self._ctrl_lits, populated on selection). Byte-safe: the patch
        only rewrites the immediate in place (flipping the tag's sign when forced), never
        re-lays-out the bank -- so branch targets and every other offset are untouched."""
        pc, st = self._sel
        try:
            i = int(self.val_arg.get()); v = int(self.val_var.get(), 0)
        except ValueError:
            messagebox.showinfo("Set value", "arg# and value must be integers."); return
        if not (0 <= i < len(self._ctrl_lits)):
            messagebox.showinfo("Set value", "literal index out of range for this expression.")
            return
        off = self._ctrl_lits[i][0]
        try:
            self._bank.set_expr_value(off, v)
        except Exception as e:
            messagebox.showerror("Set value", str(e)); return
        self.script_dirty = True
        self._scene = script.disassemble_scene(self._bank, self._scene.action_type, self._scene.entry_pc)
        self._render_scene()
        self._status(f"{st.mnem} @0x{pc:04x} expr literal #{i} = {v}{self._dirty_tag()}")

    def _set_speaker(self):
        """Repoint a SetSpeaker to a different speaker/side by rewriting its opcode
        (16..75). Same length -> byte-perfect. arg values (face/emote/target) are kept."""
        if not self._need(self._sel and script.is_portrait_op(self._sel[1].op),
                          "Select a SetSpeaker statement first."):
            return
        pc, st = self._sel
        try:
            slot = int(self.spk_var.get().split()[0])
        except (ValueError, IndexError):
            messagebox.showinfo("Set speaker", "Pick a speaker from the list."); return
        side = 1 if self.spk_side.get() == "right" else 0
        try:
            self._bank.set_action_opcode(pc, script.portrait_opcode(slot, side))
        except Exception as e:
            messagebox.showerror("Set speaker", str(e)); return
        self.script_dirty = True
        self._scene = script.disassemble_scene(self._bank, self._scene.action_type, self._scene.entry_pc)
        self._render_scene()
        name = script.PORTRAIT_SPEAKERS[slot] if slot < len(script.PORTRAIT_SPEAKERS) else str(slot)
        self._status(f"portrait @0x{pc:04x} -> {name} ({self.spk_side.get()}){self._dirty_tag()}")

    # ---- Event Manager (em.bin) integration ------------------------------- #
    def _em_get(self):
        """Lazy-load the decoded em.bin. Prefers the bundle reader (em.bin + emdeb.bin,
        consistent with the packed-var resolver); falls back to on-disk auto-find.
        Cached as False when unavailable."""
        if self._em is None:
            try:
                from rf4s_modkit import emscript
                em_data = self.reader("em.bin") if self.reader else None
                dbg_data = self.reader("emdeb.bin") if self.reader else None
                if em_data and dbg_data:
                    self._em = emscript.EmScript.parse(em_data, emscript.EmNames.parse(dbg_data))
                else:
                    self._em = emscript.EmScript.load()
            except Exception:
                self._em = False
        return self._em or None

    def _scene_em_triggers(self, sc):
        """Decode the scene's Event-Manager bridge ops into structured trigger records.
        Each: {pc, op, entry, name, entry_obj, kind}. kind is:
          'gate' -- EvalCondA/B (371/372) whose result immediately feeds a BR_Z/BR_NZ,
                    i.e. a real "plays only when <entry condition>" guard;
          'set'  -- 444 (set flag if entry condition holds);
          'run'  -- 373/374 (dispatch the entry's main / alt action stream)."""
        em = self._em_get()
        stmts = sorted(sc.stmts.items())
        out = []
        for i, (pc, st) in enumerate(stmts):
            if st.op not in script.EMF_ENTRY_OPS:
                continue
            ai = script.EMF_ENTRY_OPS[st.op]
            eid = None
            if ai < len(st.args):
                try:
                    eid = int(script.arg_repr(self._bank.data, st.args[ai]))
                except (ValueError, TypeError):
                    eid = None
            name = (em.names.entry_name(eid) if (em and eid is not None) else None) or ("#%s" % eid)
            e = em.entries[eid] if (em and eid is not None and 0 <= eid < len(em.entries)) else None
            nxt = stmts[i + 1][1] if i + 1 < len(stmts) else None
            is_gate = st.op in (371, 372) and nxt is not None and nxt.mnem in ("BR_Z", "BR_NZ")
            kind = "gate" if is_gate else ("set" if st.op == 444 else "run")
            # BR_Z skips when the condition is false -> branch plays WHEN true.
            # BR_NZ skips when true -> branch plays UNLESS true.
            verb = "plays when" if (is_gate and nxt.mnem == "BR_Z") else \
                   ("plays unless" if is_gate else "when")
            out.append({"pc": pc, "op": st.op, "entry": eid, "name": name,
                        "entry_obj": e, "kind": kind, "verb": verb})
        return out

    def _em_cond_text(self, e, which="a"):
        """One-line decoded condition (A or B) of an em.bin entry, FLG_/REG_ names."""
        em = self._em_get()
        if not (em and e):
            return ""
        slots = e.cond_b if which == "b" else e.cond_a
        if not slots:
            return ""
        return "  ".join(ln.strip() for ln in e.pretty_condition(em.names, which, "").splitlines())

    _EM_ARITH_OPS = ["SET", "ADD", "SUB", "MUL_S", "MUL_U", "DIV_S", "DIV_U",
                     "MOD_S", "MOD_U", "MAX_S", "MAX_U", "MIN_S", "MIN_U", "SET_EQ_ZERO"]

    def _em_editable_fields(self, e):
        """Editable elements of an em.bin entry for the GUI: each comparison (its
        literal operand + operator) and each arithmetic action (its value + op).
        Returns list of dicts {label, expr|action, operand, val, op, ops}."""
        em = self._em_get()
        if em is None:
            return []
        fields = []
        for which, slots in (("A", e.cond_a), ("B", e.cond_b)):
            for si, exprs in enumerate(slots or []):
                for xi, x in enumerate(exprs):
                    if x.kind != "cmp":
                        continue
                    lit = (x.op2 if (x.op2 and x.op2.kind in ("lit", "slit")) else
                           (x.op1 if (x.op1 and x.op1.kind in ("lit", "slit")) else None))
                    fields.append({"label": "cond%s[%d.%d]  %s" % (which, si, xi, x.pretty(em.names)),
                                   "expr": x, "action": None, "operand": lit,
                                   "val": (lit.value if lit else None), "op": x.cmp,
                                   "ops": ["==", "!=", ">", ">="]})
        for area, acts in (("main", e.actions), ("alt", e.alt_actions)):
            for ai, a in enumerate(acts or []):
                if a.name == "CALL":
                    continue
                v = a.value
                fields.append({"label": "%s[%d]  %s" % (area, ai, a.pretty(em.names)),
                               "expr": None, "action": a,
                               "operand": (v if (v and v.kind in ("lit", "slit", "query")) else None),
                               "val": (v.value if v else None), "op": a.name,
                               "ops": self._EM_ARITH_OPS})
        return fields

    def _emf_hint(self, st):
        """For a CondScript bridge op, a short decoded summary of the referenced entry."""
        if st.op not in script.EMF_ENTRY_OPS or self._bank is None:
            return None
        ai = script.EMF_ENTRY_OPS[st.op]
        if ai >= len(st.args):
            return None
        em = self._em_get()
        if em is None:
            return None
        try:
            e = em.entries[int(script.arg_repr(self._bank.data, st.args[ai]))]
        except (ValueError, IndexError, TypeError):
            return None
        parts = [f"em entry {e.idx} {e.name}"]
        which = "b" if st.op == 372 else "a"
        slots = e.cond_b if which == "b" else e.cond_a
        if st.op in (371, 372, 444) and slots:
            cond = e.pretty_condition(em.names, which, "").replace("\n", " ")
            parts.append("cond: " + (cond[:170] + "…" if len(cond) > 170 else cond))
        if st.op == 373 and e.actions:
            parts.append("actions: " + "; ".join(a.pretty(em.names) for a in e.actions[:4])
                         + ("; …" if len(e.actions) > 4 else ""))
        if st.op == 374 and e.alt_actions:
            parts.append("alt: " + "; ".join(a.pretty(em.names) for a in e.alt_actions[:4])
                         + ("; …" if len(e.alt_actions) > 4 else ""))
        return "\n".join(parts)

    def _open_em_browser(self):
        """Browser for the 272 named Event Manager entries + 218 game-state queries."""
        em = self._em_get()
        if em is None:
            messagebox.showerror("Event Manager",
                                 "em.bin / emdeb.bin not found in the game bundle.")
            return
        win = tk.Toplevel(self.parent)
        win.title("Event Manager (em.bin) — %d entries" % len(em.entries))
        win.geometry("980x560")
        nb = ttk.Notebook(win); nb.pack(fill="both", expand=True)

        # --- entries tab ---
        tab = ttk.Frame(nb); nb.add(tab, text="Entries")
        top = ttk.Frame(tab); top.pack(fill="x")
        ttk.Label(top, text="Filter:").pack(side="left", padx=4)
        flt = tk.StringVar()
        ttk.Entry(top, textvariable=flt, width=28).pack(side="left", pady=3)
        info = ttk.Label(top, text="matches name, JP label and decoded body  ·  "
                                   "A=cond A · B=cond B · !=actions · ~=alt actions",
                         foreground="#666")
        info.pack(side="left", padx=10)
        pane = ttk.Panedwindow(tab, orient="horizontal"); pane.pack(fill="both", expand=True)
        lf = ttk.Frame(pane); pane.add(lf, weight=1)
        lb = tk.Listbox(lf, font=("Consolas", 9), exportselection=False)
        lsb = ttk.Scrollbar(lf, command=lb.yview); lb.config(yscrollcommand=lsb.set)
        lb.pack(side="left", fill="both", expand=True); lsb.pack(side="left", fill="y")
        rf = ttk.Frame(pane); pane.add(rf, weight=2)
        detail = tk.Text(rf, font=("Consolas", 9), wrap="word", state="disabled", height=16)
        detail.pack(fill="both", expand=True)
        # "used by" scenes as a clickable list -> jump into the main editor
        ttk.Label(rf, text="used by rf3.mc scenes (double-click to open):",
                  foreground="#888").pack(anchor="w", padx=2)
        uf = ttk.Frame(rf); uf.pack(fill="x")
        uses_lb = tk.Listbox(uf, font=("Consolas", 9), height=7, exportselection=False)
        usb = ttk.Scrollbar(uf, command=uses_lb.yview); uses_lb.config(yscrollcommand=usb.set)
        uses_lb.pack(side="left", fill="both", expand=True); usb.pack(side="left", fill="y")
        shown = []
        use_sites = []
        edit_fields = []

        # --- in-place edit panel: change a condition threshold/operator or action value ---
        ef = ttk.LabelFrame(rf, text="Edit condition / action  (byte-safe, in place)")
        ef.pack(fill="x", pady=3)
        field_cb = ttk.Combobox(ef, state="readonly", width=54)
        field_cb.grid(row=0, column=0, columnspan=5, sticky="we", padx=3, pady=2)
        ttk.Label(ef, text="value:").grid(row=1, column=0, sticky="e")
        val_var = tk.StringVar(); val_ent = ttk.Entry(ef, textvariable=val_var, width=12)
        val_ent.grid(row=1, column=1, sticky="w")
        ttk.Label(ef, text="op:").grid(row=1, column=2, sticky="e", padx=(8, 0))
        op_var = tk.StringVar()
        op_cb = ttk.Combobox(ef, textvariable=op_var, state="readonly", width=11)
        op_cb.grid(row=1, column=3, sticky="w")
        ef.columnconfigure(1, weight=1)
        # live one-line explanation of the currently-selected operator (SET/ADD/MUL_S/…, ==/>=/…)
        op_desc = ttk.Label(ef, text="", foreground="#556", font=("Segoe UI", 8), wraplength=560)
        op_desc.grid(row=2, column=0, columnspan=5, sticky="w", padx=5)

        def _refresh_op_desc(*_):
            op_desc.config(text=emscript.OP_HELP.get(op_var.get(), ""))

        def on_field(*_):
            i = field_cb.current()
            if 0 <= i < len(edit_fields):
                fd = edit_fields[i]
                val_var.set("" if fd["val"] is None else str(fd["val"]))
                op_cb.config(values=fd["ops"]); op_var.set(fd["op"] or "")
                val_ent.config(state=("normal" if fd["operand"] is not None else "disabled"))
                _refresh_op_desc()

        def apply_edit():
            i = field_cb.current()
            if not (0 <= i < len(edit_fields)):
                return
            fd = edit_fields[i]
            try:
                if fd["operand"] is not None and val_var.get().strip() != "":
                    em.set_operand_value(fd["operand"], int(val_var.get(), 0))
                if op_var.get() and op_var.get() != fd["op"]:
                    if fd["expr"] is not None:
                        em.set_cmp_operator(fd["expr"], op_var.get())
                    else:
                        em.set_action_op(fd["action"], op_var.get())
            except Exception as ex:
                messagebox.showerror("Edit em.bin", str(ex)); return
            self._em_dirty = True
            pick()                                   # re-decode + rebuild the field list
            self._status("em.bin edited (unsaved) — use Save em.bin… to write")

        def save_em():
            if not getattr(self, "_em_dirty", False):
                messagebox.showinfo("Save em.bin", "No em.bin edits to save."); return
            f = filedialog.asksaveasfilename(title="Save em.bin", defaultextension=".bin",
                                             initialfile="em.bin")
            if not f:
                return
            pathlib.Path(f).write_bytes(em.build())
            self._status("saved em.bin -> %s" % f)

        _apply_btn = ttk.Button(ef, text="Apply", command=apply_edit)
        _apply_btn.grid(row=1, column=4, padx=3)
        _save_em_btn = ttk.Button(ef, text="Save em.bin…", command=save_em)
        _save_em_btn.grid(row=3, column=0, columnspan=5, sticky="we", padx=3, pady=2)
        field_cb.bind("<<ComboboxSelected>>", on_field)
        op_cb.bind("<<ComboboxSelected>>", _refresh_op_desc)
        # hover tooltips on the em-editor controls (built lazily here, so attached inline)
        self._attach_tip(field_cb, EM_CONTROL_HELP["field"])
        self._attach_tip(val_ent, EM_CONTROL_HELP["value"])
        self._attach_tip(op_cb, EM_CONTROL_HELP["op"])
        self._attach_tip(_apply_btn, EM_CONTROL_HELP["apply"])
        self._attach_tip(_save_em_btn, EM_CONTROL_HELP["save"])

        # Filter over each entry's DECODED text, not just its name: that is what makes
        # "which entries read this flag/query" answerable (type IS_WBED, REG_WIFE_ID,
        # LOVE_, a JP label, or an entry number). format_entry's header carries the name
        # and JP label, so one haystack covers all three. 272 entries -> build once.
        bodies = {e.idx: em.format_entry(e).upper() for e in em.entries}

        def rebuild_bodies():
            # structural edits relayout em.bin: every Entry object is rebuilt, so re-decode
            bodies.clear()
            bodies.update({e.idx: em.format_entry(e).upper() for e in em.entries})

        def _selected_entry():
            s = lb.curselection()
            return shown[s[0]] if (s and s[0] < len(shown)) else None

        def _clear_detail():
            detail.config(state="normal"); detail.delete("1.0", "end"); detail.config(state="disabled")
            uses_lb.delete(0, "end"); use_sites.clear()
            edit_fields[:] = []
            field_cb.config(values=[]); field_cb.set(""); val_var.set(""); op_var.set("")

        def add_entry():
            """Append a NEW em entry (a clone of the selected one, or empty) -- EmScript.add_entry
            bumps the header count so the engine evaluates it; the id is the old entry count."""
            src = _selected_entry()
            clone = None
            if src is not None and messagebox.askyesno(
                    "Add entry",
                    "Clone entry %d %s (its conditions + actions) into the new entry?\n"
                    "No = an empty entry (no conditions -> FALSE, no actions)."
                    % (src.idx, src.name or "")):
                clone = src.idx
            name = simpledialog.askstring(
                "Add entry",
                "Name for the new entry (in-memory only: emdeb.bin is not rewritten, so a "
                "reloaded file shows it unnamed -- refer to it by id). Leave blank for none.",
                parent=win)
            if name is None:
                return None
            try:
                new_idx = em.add_entry(clone=clone, name=name.strip())
            except Exception as ex:
                messagebox.showerror("Add entry", str(ex)); return None
            self._em_dirty = True
            rebuild_bodies()
            win.title("Event Manager (em.bin) — %d entries" % len(em.entries))
            flt.set("")                             # (trace -> fill) so the new row is visible
            fill()
            lb.selection_clear(0, "end"); lb.selection_set("end"); lb.see("end"); pick()
            self._status("em.bin: added entry %d%s (unsaved) — Save em.bin… to write it"
                         % (new_idx, (" " + name.strip()) if name.strip() else ""))
            return new_idx

        def remove_entry():
            """Physically delete the selected entry (later ids shift down, internal refs are
            renumbered). If other entries reference it, offer clear_entry instead (ids stable)."""
            e = _selected_entry()
            if e is None:
                messagebox.showinfo("Remove entry", "Select an entry first."); return None
            if not messagebox.askyesno(
                    "Remove entry",
                    "Physically delete entry %d %s?\nEvery later entry moves down one id (internal "
                    "condA/B refs and CALLs are renumbered; rf3.mc bridge ops that name entries by "
                    "number are NOT — re-check them with Xrefs / `rf4mod em xref`)."
                    % (e.idx, e.name or "(unnamed)")):
                return None
            how = "deleted"
            try:
                em.delete_entry(e.idx)
            except ValueError as ex:                # referenced by other entries
                if not messagebox.askyesno(
                        "Remove entry",
                        "%s\n\nClear it in place instead? (keeps every id stable; the entry then "
                        "evaluates FALSE and does nothing)" % ex):
                    return None
                try:
                    em.clear_entry(e.idx)
                except Exception as ex2:
                    messagebox.showerror("Remove entry", str(ex2)); return None
                how = "cleared"
            except Exception as ex:
                messagebox.showerror("Remove entry", str(ex)); return None
            self._em_dirty = True
            rebuild_bodies()
            win.title("Event Manager (em.bin) — %d entries" % len(em.entries))
            fill()
            _clear_detail()
            self._status("em.bin: entry %d %s (unsaved) — Save em.bin… to write it" % (e.idx, how))
            return how

        _add_entry_btn = ttk.Button(top, text="Add entry", command=add_entry)
        _remove_entry_btn = ttk.Button(top, text="Remove entry", command=remove_entry)
        _remove_entry_btn.pack(side="right", padx=3)
        _add_entry_btn.pack(side="right", padx=3)
        self._attach_tip(_add_entry_btn, EM_CONTROL_HELP["add_entry"])
        self._attach_tip(_remove_entry_btn, EM_CONTROL_HELP["remove_entry"])
        # automation / headless-test hook: the window's live handlers + list (closures above)
        # --- structural editing: whole conditions / actions (not just their values) ---------
        sf = ttk.LabelFrame(rf, text="Add / remove whole conditions + actions")
        sf.pack(fill="x", pady=3)
        # (em-editor controls are LOCAL vars tipped inline from EM_CONTROL_HELP -- the
        # convention the selftest enforces; the handlers are exposed via self._em_browser.)
        struct_items = []                       # parallel to struct_cb's values
        struct_cb = ttk.Combobox(sf, state="readonly", width=54)
        struct_cb.grid(row=0, column=0, columnspan=4, sticky="we", padx=3, pady=2)
        sf.columnconfigure(0, weight=1)
        _add_cond_btn = ttk.Button(sf, text="Add condition…")
        _rm_cond_btn = ttk.Button(sf, text="Remove condition")
        _add_act_btn = ttk.Button(sf, text="Add action…")
        _rm_act_btn = ttk.Button(sf, text="Remove action")
        for _c, _w in enumerate((_add_cond_btn, _rm_cond_btn, _add_act_btn, _rm_act_btn)):
            _w.grid(row=1, column=_c, sticky="we", padx=2, pady=2)
        self._attach_tip(struct_cb, EM_CONTROL_HELP["struct"])
        self._attach_tip(_add_cond_btn, EM_CONTROL_HELP["add_condition"])
        self._attach_tip(_rm_cond_btn, EM_CONTROL_HELP["remove_condition"])
        self._attach_tip(_add_act_btn, EM_CONTROL_HELP["add_action"])
        self._attach_tip(_rm_act_btn, EM_CONTROL_HELP["remove_action"])

        def _refresh_struct(e=None):
            """Fill the structure picker from the selected entry (slots, expressions, actions)."""
            struct_items[:] = []
            labels = []
            if e is not None:
                nm = getattr(em, "names", None)
                for which, slots in (("a", e.cond_a or []), ("b", e.cond_b or [])):
                    for si, exprs in enumerate(slots):
                        labels.append("cond %s · slot %d  (whole OR-slot, %d expr)"
                                      % (which.upper(), si, len(exprs)))
                        struct_items.append(("cond", which, si, None))
                        for xi, x in enumerate(exprs):
                            try:
                                txt = x.pretty(nm)
                            except Exception:
                                txt = repr(x)
                            labels.append("   cond %s · slot %d · expr %d:  %s"
                                          % (which.upper(), si, xi, txt))
                            struct_items.append(("cond", which, si, xi))
                for stream, acts in (("main", e.actions or []), ("alt", e.alt_actions or [])):
                    for ai, act in enumerate(acts):
                        try:
                            txt = act.pretty(nm)
                        except Exception:
                            txt = repr(act)
                        labels.append("action %s · #%d:  %s" % (stream, ai, txt))
                        struct_items.append(("act", stream, ai, None))
            struct_cb.config(values=labels)
            struct_cb.set(labels[0] if labels else "")

        def _struct_sel():
            i = struct_cb.current()
            return struct_items[i] if 0 <= i < len(struct_items) else None

        def _after_struct_edit(e, what):
            self._em_dirty = True
            rebuild_bodies()
            fill()
            for k, row in enumerate(shown):
                if row.idx == e.idx:
                    lb.selection_clear(0, "end"); lb.selection_set(k); lb.see(k); pick()
                    break
            self._status("em.bin: %s on entry %d (unsaved) — Save em.bin… to write it"
                         % (what, e.idx))

        def add_condition():
            """Add condition terms (parse_condition_spec grammar) as a new OR-slot, or ANDed
            onto an existing one."""
            e = _selected_entry()
            if e is None:
                messagebox.showinfo("Add condition", "Select an entry first."); return None
            nslots = len((e.cond_a if True else None) or [])
            spec = self._ask_spec(
                "Add condition",
                "Condition terms for entry %d %s.\nGrammar: OR-groups joined by AND, terms by OR — "
                "`Hour >= 6 AND (12 > Hour OR FLG_RAINBOW == 1) AND !condA(EV_DATE_APPO)`.\n"
                "Operands: a number, a query name (Hour, Season), an emdeb variable (REG_/FLG_, "
                "including your own from emdeb_extra.json), or flag@BIT/WIDTH.\n"
                "Prefix a line with `B:` to target condition B, and `slot=N ` to AND the terms "
                "onto existing OR-slot N instead of opening a new one."
                % (e.idx, e.name or ""),
                lambda text: self._em_parse_condition(em, e, text))
            if not spec:
                return None
            try:                                  # (the dialog validated it; be safe anyway)
                which, slot, exprs = self._em_parse_condition(em, e, spec)
            except Exception as ex:
                messagebox.showerror("Add condition", str(ex)); return None
            try:
                used = em.add_condition(e.idx, which, exprs, slot=slot)
            except Exception as ex:
                messagebox.showerror("Add condition", str(ex)); return None
            _after_struct_edit(e, "condition %s slot %d +%d term(s)" % (which.upper(), used, len(exprs)))
            return used

        def remove_condition():
            sel = _struct_sel()
            e = _selected_entry()
            if e is None or sel is None or sel[0] != "cond":
                messagebox.showinfo("Remove condition",
                                    "Pick a condition slot or expression in the structure box first.")
                return None
            _, which, slot, expr = sel
            what = ("whole OR-slot %d" % slot) if expr is None else ("expression %d of slot %d" % (expr, slot))
            if not messagebox.askyesno("Remove condition",
                                       "Remove %s from condition %s of entry %d?"
                                       % (what, which.upper(), e.idx)):
                return None
            try:
                em.remove_condition(e.idx, which, slot, expr)
            except Exception as ex:
                messagebox.showerror("Remove condition", str(ex)); return None
            _after_struct_edit(e, "removed condition %s %s" % (which.upper(), what))
            return True

        def add_action():
            """Append an action (parse_action_spec grammar) to the main or alt stream."""
            e = _selected_entry()
            if e is None:
                messagebox.showinfo("Add action", "Select an entry first."); return None
            spec = self._ask_spec(
                "Add action",
                "Action for entry %d %s.\nGrammar: `FLG_X = 1`, `REG_Y += 2`, `REG_Y = (FLG_Z == 0)`, "
                "`CALL EV_FOO`, or the explicit `OP target value` (SET/ADD/SUB/MUL_S/DIV_S/MOD_S/"
                "MIN_S/MAX_S/SET_EQ_ZERO).\nPrefix with `alt:` to append to the ALT stream instead "
                "of the main one." % (e.idx, e.name or ""),
                lambda text: self._em_parse_action(em, text))
            if not spec:
                return None
            try:                                  # (the dialog validated it; be safe anyway)
                stream, action = self._em_parse_action(em, spec)
            except Exception as ex:
                messagebox.showerror("Add action", str(ex)); return None
            try:
                em.add_action(e.idx, stream, action)
            except Exception as ex:
                messagebox.showerror("Add action", str(ex)); return None
            _after_struct_edit(e, "added %s action" % stream)
            return stream

        def remove_action():
            sel = _struct_sel()
            e = _selected_entry()
            if e is None or sel is None or sel[0] != "act":
                messagebox.showinfo("Remove action", "Pick an action in the structure box first.")
                return None
            _, stream, index, _x = sel
            if not messagebox.askyesno("Remove action",
                                       "Remove %s action #%d of entry %d?" % (stream, index, e.idx)):
                return None
            try:
                em.remove_action(e.idx, stream, index)
            except Exception as ex:
                messagebox.showerror("Remove action", str(ex)); return None
            _after_struct_edit(e, "removed %s action #%d" % (stream, index))
            return True

        _add_cond_btn.config(command=add_condition)
        _rm_cond_btn.config(command=remove_condition)
        _add_act_btn.config(command=add_action)
        _rm_act_btn.config(command=remove_action)

        self._em_browser = {"win": win, "list": lb, "shown": shown, "add_entry": add_entry,
                            "remove_entry": remove_entry, "save": save_em, "em": em,
                            "add_condition": add_condition, "remove_condition": remove_condition,
                            "add_action": add_action, "remove_action": remove_action,
                            "struct_items": struct_items, "refresh_struct": _refresh_struct,
                            "struct": struct_cb}

        def fill(*_):
            q = flt.get().upper()
            lb.delete(0, "end"); shown.clear()
            for e in em.entries:
                if q and q not in bodies[e.idx]:
                    continue
                marks = "".join(m for m, has in (("A", e.cond_a), ("B", e.cond_b),
                                                 ("!", e.actions), ("~", e.alt_actions)) if has)
                lb.insert("end", f"{e.idx:3d} {marks:<4} {e.name or '(unnamed)'}")
                shown.append(e)

        def pick(_ev=None):
            s = lb.curselection()
            if not s:
                return
            e = shown[s[0]]
            detail.config(state="normal"); detail.delete("1.0", "end")
            detail.insert("1.0", em.format_entry(e)); detail.config(state="disabled")
            uses_lb.delete(0, "end"); use_sites.clear()
            for bk, sc, pc, st in self._emf_uses(e.idx):
                uses_lb.insert("end", "bank %3d  scene@0x%04x  0x%04x  %s"
                               % (bk.index, sc.entry_pc, pc, script.opcode_mnemonic(st.op)))
                use_sites.append((bk.index, sc.entry_pc))
            edit_fields[:] = self._em_editable_fields(e)   # populate the edit picker
            _refresh_struct(e)                             # ...and the structural picker
            field_cb.config(values=[fd["label"][:64] for fd in edit_fields])
            if edit_fields:
                field_cb.current(0); on_field()
            else:
                field_cb.set(""); val_var.set(""); op_var.set("")

        def jump(_ev=None):
            s = uses_lb.curselection()
            if not s:
                return
            bidx, entry_pc = use_sites[s[0]]
            self.show_bank(bidx, entry_pc)          # focus the main editor on that scene

        flt.trace_add("write", fill)
        lb.bind("<<ListboxSelect>>", pick)
        uses_lb.bind("<Double-Button-1>", jump)
        uses_lb.bind("<Return>", jump)
        fill()

        # --- queries tab ---
        qtab = ttk.Frame(nb); nb.add(qtab, text="Queries (Script_QueryGameState)")
        qlb = tk.Listbox(qtab, font=("Consolas", 9))
        qsb = ttk.Scrollbar(qtab, command=qlb.yview); qlb.config(yscrollcommand=qsb.set)
        qlb.pack(side="left", fill="both", expand=True); qsb.pack(side="left", fill="y")
        for i, (en, jp) in enumerate(em.names.query_names):
            qlb.insert("end", f"{i:3d}  {en}" + (f"  —  {jp}" if jp else ""))

    def _emf_uses(self, entry_idx):
        """All (bank, scene, pc, stmt) in the loaded rf3.mc that reference entry_idx.
        The full scan (~800 banks) runs once and is cached; edits invalidate it lazily
        via the container identity check."""
        cache = getattr(self, "_emf_xref_cache", None)
        if cache is None or cache[0] is not self.container:
            uses = {}
            seen = set()          # (bank, pc) -- discovered scenes overlap; dedup sites
            if self.container is not None:
                for bk in self.container.banks:
                    for sc in script.disassemble_bank(bk):
                        for pc, st in sc.stmts.items():
                            if st.op not in script.EMF_ENTRY_OPS:
                                continue
                            ai = script.EMF_ENTRY_OPS[st.op]
                            if ai >= len(st.args):
                                continue
                            key = (bk.index, pc)
                            if key in seen:
                                continue
                            seen.add(key)
                            try:
                                eid = int(script.arg_repr(bk.data, st.args[ai]))
                            except (ValueError, TypeError):
                                continue
                            uses.setdefault(eid, []).append((bk, sc, pc, st))
            cache = (self.container, uses)
            self._emf_xref_cache = cache
        return cache[1].get(entry_idx, [])

    # ---- generic validated prompt (em condition / action specs) ---------- #
    def _ask_spec(self, title, prompt, validate, initial=""):
        """Modal one-field prompt whose OK runs `validate(text)` first and shows whatever
        it raises inline (never a modal), so what comes back is text that parses. Returns
        the text or None. Headless tests monkeypatch this and call the handlers directly."""
        win = tk.Toplevel(self.parent)
        win.title(title)
        try:
            win.transient(self.parent.winfo_toplevel())
        except tk.TclError:
            pass
        ttk.Label(win, text=prompt, justify="left", wraplength=640,
                  font=("Segoe UI", 9)).pack(anchor="w", padx=8, pady=(8, 4))
        body = ttk.Frame(win); body.pack(fill="both", expand=True, padx=8)
        txt = tk.Text(body, height=3, width=76, font=("Consolas", 10), undo=True,
                      bg="#101014", fg="#d8d8e0", insertbackground="#d8d8e0")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", initial or "")
        err = ttk.Label(win, text="", foreground="#b02020", wraplength=640, justify="left")
        err.pack(fill="x", padx=8, pady=(2, 0))
        out = {"text": None}

        def ok(_e=None):
            t = txt.get("1.0", "end-1c").strip()
            if not t:
                err.config(text="type a spec (or Cancel)"); return
            try:
                validate(t)
            except Exception as ex:
                err.config(text=str(ex)); return
            out["text"] = t
            win.destroy()

        bb = ttk.Frame(win); bb.pack(fill="x", padx=8, pady=6)
        ttk.Button(bb, text="OK", command=ok).pack(side="right", padx=2)
        ttk.Button(bb, text="Cancel", command=win.destroy).pack(side="right", padx=2)
        win.bind("<Escape>", lambda _e: win.destroy())
        win.bind("<Control-Return>", ok)
        txt.focus_set()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        win.wait_window()
        return out["text"]

    @staticmethod
    def _em_parse_condition(em, entry, text):
        """('a'|'b', slot|None, [Expr]) from a condition spec, with the editor's two
        prefixes: a leading `B:` targets condition B, `slot=N ` ANDs onto OR-slot N.
        Raises ValueError on anything the em grammar rejects (shown inline by _ask_spec)."""
        t = (text or "").strip()
        which = "a"
        if t[:2].lower() == "b:":
            which, t = "b", t[2:].strip()
        elif t[:2].lower() == "a:":
            t = t[2:].strip()
        slot = None
        m = re.match(r"slot\s*=\s*(\d+)\s+(.*)$", t, re.I)
        if m:
            slot, t = int(m.group(1)), m.group(2).strip()
            slots = (entry.cond_a if which == "a" else entry.cond_b) or []
            if not (0 <= slot <= len(slots)):
                raise ValueError("condition %s has %d OR-slot(s); slot=%d is out of range "
                                 "(omit slot= to open a new one)" % (which.upper(), len(slots), slot))
        if not t:
            raise ValueError("no condition terms")
        return which, slot, em.parse_condition_spec(t)

    @staticmethod
    def _em_parse_action(em, text):
        """('main'|'alt', Action) from an action spec; a leading `alt:` picks the alt stream."""
        t = (text or "").strip()
        stream = "main"
        if t[:4].lower() == "alt:":
            stream, t = "alt", t[4:].strip()
        elif t[:5].lower() == "main:":
            t = t[5:].strip()
        if not t:
            raise ValueError("no action")
        return stream, em.parse_action_spec(t)

    # ---- structural editing (insert / delete beats) ---------------------- #
    def _shadow_note(self, bank, type_id, position=None):
        """Warning text (or '') for registering a new `type_id` entry at `position`: the
        type's dispatcher may run only the LAST entry (so the new scene replaces the map's
        existing one) or take the FIRST match. Delegates to the library so the CLI and the
        editor say the same thing."""
        try:
            return self.container.entry_shadow_note(bank, type_id, position) or ""
        except Exception:
            return ""

    def _restructure(self, fn, status):
        if not self._need(self._sel, "Click a statement first (the new beat goes after it)."):
            return
        try:
            fn(self._sel[0])
        except Exception as e:
            messagebox.showerror("Structural edit", str(e)); return
        self.script_dirty = True
        self._scene = script.disassemble_scene(self._bank, self._scene.action_type, self._scene.entry_pc)
        self._render_scene()
        self._status(status + self._dirty_tag())

    def _insert_dialogue(self):
        lid = simpledialog.askinteger("Insert dialogue", "Dialogue line id:",
                                      parent=self.parent, minvalue=0)
        if lid is None:
            return
        self._restructure(lambda pc: self.container.insert_after(self._bank, pc, [("dialog", lid)]),
                          f"inserted DIALOG #{lid}")

    def _insert_action(self):
        """Insert one or more statements after the selected one, written in full listing
        syntax (actions by name / number, DIALOG #id, BR_Z / STORE with emdeb.bin FLG_/REG_
        names, labels, choices, ...). The dialog validates with the assembler; the insert is
        a byte-safe trampoline (nothing existing moves). The legacy `GiveItem 258 1 0`
        space-separated form still assembles."""
        if not self._need(self._sel, "Click a statement first (the new beats go after it)."):
            return
        text = self._ask_listing("Insert statements", INSERT_PROMPT)
        if text is None:
            return
        self._insert_listing(text)

    def _insert_listing(self, text):
        """Insert listing `text` right after the selected statement. Validated first: the
        error shown carries the line number and the assembler's 'did you mean' suggestions.
        Returns True when the insert was applied."""
        if not self._need(self._sel, "Click a statement first (the new beats go after it)."):
            return False
        if not (text or "").strip():
            self._status("nothing to insert (empty listing)")
            return False
        _region, _labels, err = self._assemble_check(text)
        if err:
            messagebox.showinfo("Insert statements", err)
            return False
        n = self._count_statements(text)
        self._restructure(lambda pc: self.container.insert_after(self._bank, pc, text),
                          "inserted %d statement%s" % (n, "" if n == 1 else "s"))
        return True

    @staticmethod
    def _count_statements(text):
        """Number of statements in a listing (labels, comments and blank lines excluded)."""
        n = 0
        for raw in (text or "").splitlines():
            s = raw.split(";", 1)[0].strip()
            for _ in range(4):                      # peel `label:` / `0123:` prefixes
                s2 = re.sub(r"^(?:[A-Za-z_]\w*|[0-9A-Fa-f]{4})\s*:(?!:)\s*", "", s)
                if s2 == s:
                    break
                s = s2
            if s:
                n += 1
        return n

    def _assemble_check(self, text, base=None):
        """Assemble `text` WITHOUT applying it. Returns (region_bytes, labels, None), or
        (None, None, error_text) -- the error carries the line number and the assembler's
        'did you mean' suggestions (plus a fuzzy-match fallback for typos the substring
        search misses), so it can be shown as-is. `base` defaults to the end of the current
        bank (where an append would land), so the 64 KB cap check is real."""
        if base is None:
            base = len(self._bank.data) if self._bank is not None else 0
        resolver = self.container.asm_resolver if self.container is not None else None
        try:
            region, labels = scriptasm.assemble(text, base, resolver=resolver)
        except script.ScriptError as e:
            return None, None, self._with_op_suggestions(str(e))
        except Exception as e:                      # int() on garbage, struct overflow, ...
            return None, None, "%s: %s" % (type(e).__name__, e)
        return region, labels, None

    _op_name_pool = None                            # [(lower name, display, op)] lazily built

    @classmethod
    def _with_op_suggestions(cls, msg):
        """Append 'did you mean: …' to an `unknown opcode 'X'` error that has none: the
        assembler's own suggestions come from a substring search (script.find_ops), which
        misses plain typos (GiveItm); difflib over every mnemonic / technical name catches
        those."""
        m = re.search(r"unknown opcode '([^']+)'", msg or "")
        if not m or "did you mean" in msg:
            return msg
        if cls._op_name_pool is None:
            pool = {}
            for o in range(763):
                for nm in (script.opcode_mnemonic(o), script.opcode_name(o)):
                    if nm and not re.fullmatch(r"op\d+", nm) and nm.lower() not in pool:
                        pool[nm.lower()] = (nm, o)
            cls._op_name_pool = pool
        import difflib
        hits = difflib.get_close_matches(m.group(1).lower(), list(cls._op_name_pool), n=6, cutoff=0.6)
        if not hits:
            return msg
        return msg + " -- did you mean: " + ", ".join(
            "%s (op %d)" % cls._op_name_pool[h] for h in hits)

    def _ask_listing(self, title, prompt, initial=""):
        """Modal multi-line listing prompt: a Text box + OK / Cancel / Syntax help. OK runs the
        assembler first and shows any error inline (no modal), so what comes back is a listing
        that assembles. Returns the text, or None when cancelled. (Headless tests monkeypatch
        this method and call the *_listing handlers directly.)"""
        win = tk.Toplevel(self.parent)
        win.title(title)
        try:
            win.transient(self.parent.winfo_toplevel())
        except tk.TclError:
            pass
        ttk.Label(win, text=prompt, justify="left", font=("Segoe UI", 9)).pack(
            anchor="w", padx=8, pady=(8, 2))
        help_lbl = tk.Label(win, text=SOURCE_SYNTAX_HELP, justify="left", anchor="w",
                            font=("Consolas", 8), bg="#1b1b22", fg="#e6e6ee", padx=6, pady=4)
        body = ttk.Frame(win); body.pack(fill="both", expand=True, padx=8)
        sb = ttk.Scrollbar(body); sb.pack(side="right", fill="y")
        txt = tk.Text(body, height=8, width=80, font=("Consolas", 10), undo=True,
                      bg="#101014", fg="#d8d8e0", insertbackground="#d8d8e0", yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)
        txt.insert("1.0", initial or "")
        err = ttk.Label(win, text="", foreground="#b02020", wraplength=640, justify="left")
        err.pack(fill="x", padx=8, pady=(2, 0))
        out = {"text": None}
        shown = {"help": False}

        def ok(_e=None):
            t = txt.get("1.0", "end-1c")
            if not t.strip():
                err.config(text="type at least one statement (or Cancel)"); return
            _r, _l, e = self._assemble_check(t)
            if e:
                err.config(text=e); return
            out["text"] = t
            win.destroy()

        def toggle_help():
            if shown["help"]:
                help_lbl.pack_forget()
            else:
                help_lbl.pack(fill="x", padx=8, pady=(0, 4), before=body)
            shown["help"] = not shown["help"]

        bb = ttk.Frame(win); bb.pack(fill="x", padx=8, pady=6)
        ok_btn = ttk.Button(bb, text="OK", command=ok); ok_btn.pack(side="right", padx=2)
        cancel_btn = ttk.Button(bb, text="Cancel", command=win.destroy)
        cancel_btn.pack(side="right", padx=2)
        help_btn = ttk.Button(bb, text="Syntax help", command=toggle_help); help_btn.pack(side="left")
        self._attach_tip(ok_btn, DIALOG_CONTROL_HELP["listing_ok"])
        self._attach_tip(cancel_btn, DIALOG_CONTROL_HELP["listing_cancel"])
        self._attach_tip(help_btn, DIALOG_CONTROL_HELP["listing_help"])
        win.bind("<Escape>", lambda _e: win.destroy())
        win.bind("<Control-Return>", ok)
        txt.focus_set()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        win.wait_window()
        return out["text"]

    # ---- Source tab: the scene as an editable listing <-> assembler ------- #
    def _source_set_status(self, msg, kind="info"):
        col = {"info": "#0d5f8f", "ok": "#1d7a3a", "err": "#b02020"}.get(kind, "#0d5f8f")
        self.src_status.config(text=msg, foreground=col)

    def _scene_source_text(self):
        """The current scene as a re-assemblable listing (dialogue text as comments). A leading
        `JMP Lx` whose label is the very next statement -- the trampoline an earlier 'Assemble &
        replace' / insert left at the entry -- is dropped, so repeated round trips don't stack
        indirections. (A JMP that skips over other statements is kept: it is real flow.)"""
        bank_no = self.container.banks.index(self._bank) if self.container is not None else None
        txt = scriptasm.scene_listing(self._scene, self._bank, dialog=self._dlg, bank_no=bank_no)
        lines = txt.split("\n")
        for i, ln in enumerate(lines):
            s = ln.strip()
            if not s or s.startswith(";"):
                continue
            m = re.match(r"^(?:[0-9a-fA-F]{4}:\s*)?JMP\s+([A-Za-z_]\w*)\s*(?:;.*)?$", s)
            if m:
                nxt = next((l2.strip() for l2 in lines[i + 1:] if l2.strip()), "")
                if nxt == m.group(1) + ":":
                    del lines[i]
            break
        return "\n".join(lines)

    def _source_load(self, force=False):
        """(Re)fill the Source box from the selected scene. Hand edits to the SAME scene's
        listing survive a re-render (e.g. after an edit-panel patch) unless `force`; picking a
        different scene always reloads."""
        if self._scene is None or self._bank is None or self.container is None:
            self.source.delete("1.0", "end")
            self.source.edit_modified(False)
            self._source_key = None
            self._source_set_status("(open a scene to see its listing)")
            return
        key = (id(self._bank), self._scene.entry_pc)
        edited = bool(self.source.edit_modified())
        if not force and key == self._source_key and edited:
            self._source_set_status("listing edited by hand — Check / Assemble & replace applies it; "
                                    "Reload from scene discards it")
            return
        note = "  (hand edits of the previous scene's listing were discarded)" \
            if (edited and self._source_key is not None and key != self._source_key) else ""
        self.source.delete("1.0", "end")
        self.source.insert("1.0", self._scene_source_text())
        self.source.edit_reset()
        self.source.edit_modified(False)
        self.source.tag_remove("err", "1.0", "end")
        self._source_key = key
        n = len(self._scene.stmts)
        self._source_set_status("%d statement%s — edit, Check, then Assemble & replace scene%s"
                                % (n, "" if n == 1 else "s", note))

    def _source_reload(self):
        if self._scene is None:
            self._status("open a scene first"); return
        self._source_load(force=True)

    def _source_mark_error(self, msg):
        """Highlight the `line N` an assembler error names (and scroll to it)."""
        self.source.tag_remove("err", "1.0", "end")
        m = re.search(r"line (\d+)", msg or "")
        if m:
            ln = int(m.group(1))
            self.source.tag_add("err", "%d.0" % ln, "%d.end" % ln)
            self.source.see("%d.0" % ln)

    def _source_check(self):
        """Assemble the Source box without applying it; report size or the first error."""
        if self._scene is None or self.container is None:
            self._status("open a scene first, then Check its Source"); return None
        text = self.source.get("1.0", "end-1c")
        if not text.strip():
            self._source_set_status("nothing to check (empty listing)", "err"); return None
        region, labels, err = self._assemble_check(text)
        if err:
            self._source_mark_error(err)
            self._source_set_status("error: " + err, "err")
            return None
        self.source.tag_remove("err", "1.0", "end")
        n = self._count_statements(text)
        self._source_set_status("OK — %d statement%s assemble to %d bytes (%d label%s); Assemble & "
                                "replace scene applies it" % (n, "" if n == 1 else "s", len(region),
                                                              len(labels), "" if len(labels) == 1 else "s"),
                                "ok")
        return region

    def _source_apply(self):
        """Assemble the Source box and make the scene play it: `rewrite_scene` appends the new
        body and trampolines the scene's entry statement to it (the trigger is unchanged, the
        old body is dead bytes, nothing else moves)."""
        if self._scene is None or self._bank is None or self.container is None:
            self._status("open a scene first, then Assemble & replace its Source"); return False
        text = self.source.get("1.0", "end-1c")
        if not text.strip():
            self._source_set_status("nothing to assemble (empty listing)", "err"); return False
        if text.strip() == self._scene_source_text().strip():
            # identical to the scene as it is: re-assembling would only append a second
            # copy of the body (the bank grows toward its 64 KB cap for nothing)
            self._source_set_status("listing unchanged — nothing to assemble", "info")
            return False
        region, _labels, err = self._assemble_check(text)
        if err:
            self._source_mark_error(err)
            self._source_set_status("error: " + err, "err")
            return False
        entry_pc = self._scene.entry_pc
        try:
            base = self.container.rewrite_scene(self._bank, entry_pc, text)
        except Exception as e:
            messagebox.showerror("Assemble & replace scene", str(e)); return False
        self.script_dirty = True
        self._scene = script.disassemble_scene(self._bank, self._scene.action_type, entry_pc)
        self._render_scene()                        # re-disassemble + Analysis + Entries
        self._source_load(force=True)               # the listing now reflects the new body
        self._source_set_status("assembled %d bytes @0x%04x — the scene's entry @0x%04x now jumps "
                                "to the new body" % (len(region), base, entry_pc), "ok")
        self._status("scene @0x%04x replaced (%d B appended @0x%04x)%s"
                     % (entry_pc, len(region), base, self._dirty_tag()))
        return True

    def _source_toggle_help(self):
        if self._source_help_shown:
            self.src_help_lbl.pack_forget()
        else:
            self.src_help_lbl.pack(fill="x", padx=4, pady=(0, 2), before=self._source_editor_frame)
        self._source_help_shown = not self._source_help_shown

    # ---- Entries tab: the bank's type table (scene triggers) --------------- #
    def _entries_show(self, bank):
        """Point the Entries tab at `bank` and (re)build its type-table tree."""
        self._entries_bank = bank
        self._entries_refresh()

    def _entries_refresh(self):
        tree = self.entries_tree
        tree.delete(*tree.get_children())
        self._entries_rows = {}
        bank = self._entries_bank
        if bank is None or self.container is None:
            self.ent_lbl.config(text="(list a bank or open a scene to see its triggers)")
            return
        cpos = self.container.banks.index(bank)
        try:
            tt = bank.type_table_full()
        except Exception as e:
            self.ent_lbl.config(text="bank %d: type table unreadable (%s)" % (cpos, e))
            return
        total = 0
        for t, (cnt, _off) in tt.items():
            note = ""
            try:
                recs = bank.entry_records(t)
            except script.ScriptError as e:
                recs, note = [], "  [%s]" % e
            node = tree.insert("", "end", text="%s  (%d)%s" % (_type_label(t), cnt, note),
                               values=("", _type_summary(t)), open=True)
            self._entries_rows[node] = (t, None)
            for r in recs:
                dead = "" if script.decode_statement(bank.data, r.event_id) else "  [no code]"
                iid = tree.insert(node, "end", text="  #%d" % r.index,
                                  values=("0x%04x%s" % (r.event_id, dead), _describe_keys(t, r.subs)))
                self._entries_rows[iid] = (t, r)
                total += 1
        self.ent_lbl.config(
            text="bank %d (%s): %d action type%s, %d entr%s · %d type slots (0..%d)%s"
                 % (cpos, bank.kind, len(tt), "" if len(tt) == 1 else "s", total,
                    "y" if total == 1 else "ies", bank.table_slots, bank.table_slots - 1,
                    "   · empty table — New scene… registers the first trigger" if not tt else ""))

    def _entries_selected(self):
        """(type_id, EntryRecord) of the selected entry row; (type_id, None) on a type node;
        (None, None) with nothing selected."""
        sel = self.entries_tree.selection()
        if not sel or sel[0] not in self._entries_rows:
            return None, None
        return self._entries_rows[sel[0]]

    def _entries_open(self):
        if self.container is None or self._entries_bank is None:
            self._status("list a bank first (bank # + List bank)"); return False
        _t, r = self._entries_selected()
        if r is None:
            self._status("select an entry row (not the type node) to open its scene"); return False
        cpos = self.container.banks.index(self._entries_bank)
        ok = self.show_bank(cpos, entry_pc=r.event_id)
        if ok:
            try:
                self._topnb.select(0)               # Disassembly tab
            except tk.TclError:
                pass
        return ok

    def _default_keys_text(self, bank, type_id):
        """Wildcard keys shaped like the type's matcher expects: entry_types' key list when
        known, else the key count of the bank's existing entries of that type."""
        names = _type_key_names(type_id)
        n = len(names) if names is not None else None
        if n is None:
            try:
                recs = bank.entry_records(type_id)
            except Exception:
                recs = []
            if recs:
                n = len(recs[0].subs)
        return ", ".join(["-1"] * n) if n else ""

    def _new_scene_template(self):
        """Minimal body for a new scene: FRAME 0 / DIALOG #<line> / END, with the line id
        from the line-id box (e.g. one just added with 'Add line'), else the current
        scene's first line, else 0."""
        lid = None
        try:
            lid = int(self.line_var.get(), 0)
        except (ValueError, TypeError):
            pass
        if lid is None and self._scene is not None:
            lid = next((st.dialog_id for st in self._scene.stmts.values() if st.mnem == "DIALOG"),
                       None)
        return "FRAME 0\nDIALOG #%d\nEND\n" % (lid if lid is not None else 0)

    def _entries_new_scene(self):
        """'New scene…': dialog, then _entries_add."""
        if self.container is None:
            self._status("open rf3.mc first"); return None
        bank = self._entries_bank or self._bank
        if bank is None:
            self._status("list a bank first (bank # + List bank), then New scene…"); return None
        return self._new_scene_via_dialog(bank)

    def _new_scene_via_dialog(self, bank, default_type=None):
        spec = self._ask_new_scene(bank, default_type=default_type)
        if not spec:
            return None
        return self._entries_add(bank, spec["type_id"], spec["keys"], spec["body"], spec["position"])

    def open_new_scene_dialog(self, bank_index, default_type=None):
        """Public entry point (the map editor's 'New scene on this map…'): list container
        bank `bank_index` (its Entries tab) and run the New-scene dialog there with
        `default_type` preselected -- None picks map_enter_type() (MapEnterScene, type 7)
        for a tail bank, else the dialog's own default. Returns (event_pc, index) or None."""
        if self.container is None:
            self._status("open rf3.mc first"); return None
        if not (0 <= bank_index < len(self.container.banks)):
            self._status("rf3.mc has no bank %d" % bank_index); return None
        bank = self.container.banks[bank_index]
        if self._entries_bank is not bank:
            self.show_bank(bank_index)
        try:
            self._topnb.select(self._entries_tab)
        except tk.TclError:
            pass
        if default_type is None and bank.kind == "tail":
            default_type = map_enter_type()
        return self._new_scene_via_dialog(bank, default_type)

    def _entries_add(self, bank, type_id, keys, body, position=None):
        """Mint a scene in `bank`: assemble `body`, append it, register it under `type_id` with
        `keys` (text like `5, -1` / `(2, 100)`, or a list) at `position` ('append' / 'first' /
        an index), then open it. Returns (event_pc, index) or None (error already shown)."""
        if self.container is None:
            self._status("open rf3.mc first"); return None
        try:
            subs = parse_entry_keys(keys) if isinstance(keys, str) else list(keys or ())
        except ValueError as e:
            messagebox.showinfo("New scene", str(e)); return None
        if not (body or "").strip():
            messagebox.showinfo("New scene", "The body needs at least one statement, e.g.\n"
                                             "  FRAME 0\n  DIALOG #123\n  END")
            return None
        _region, _labels, err = self._assemble_check(body, base=len(bank.data))
        if err:
            messagebox.showinfo("New scene", err); return None
        pos = None
        if position not in (None, "", "append", "last"):
            pos = 0 if position == "first" else int(position)
        note = self._shadow_note(bank, int(type_id), pos)    # judged on the list BEFORE the add
        try:
            event_pc, idx = self.container.add_entry(bank, int(type_id), subs, listing=body,
                                                     position=pos)
        except Exception as e:
            messagebox.showerror("New scene", str(e)); return None
        self.script_dirty = True
        self._emf_xref_cache = None                 # the scene set changed
        cpos = self.container.banks.index(bank)
        self.show_bank(cpos, entry_pc=event_pc)
        msg = ("new scene @0x%04x registered as %s entry #%d%s"
               % (event_pc, _type_label(int(type_id)), idx, self._dirty_tag()))
        self._status(msg + (("   ⚠ " + note) if note else ""), note=bool(note))
        return event_pc, idx

    def _ask_new_scene(self, bank, default_type=None):
        """Modal 'New scene' dialog for `bank`: action type, matcher keys, list position and
        the body listing; keys + body are validated inline. Returns {type_id, keys, body,
        position} or None. (Headless tests call _entries_add directly.)"""
        cpos = self.container.banks.index(bank)
        tt = bank.type_table_full()
        win = tk.Toplevel(self.parent)
        win.title("New scene — bank %d (%s)" % (cpos, bank.kind))
        try:
            win.transient(self.parent.winfo_toplevel())
        except tk.TclError:
            pass
        frm = ttk.Frame(win); frm.pack(fill="both", expand=True, padx=8, pady=8)

        def choice_text(t):
            lab = _type_label(t)
            nm = lab.split("  ", 1)[1] if "  " in lab else ""
            cnt = tt[t][0] if t in tt else 0
            return "%-3d %s%s" % (t, nm, ("   (%d entr%s)" % (cnt, "y" if cnt == 1 else "ies"))
                                  if cnt else "")

        ttk.Label(frm, text="action type:").grid(row=0, column=0, sticky="e", padx=2, pady=2)
        type_var = tk.StringVar()
        type_cb = ttk.Combobox(frm, textvariable=type_var, state="readonly", width=52,
                               values=[choice_text(t) for t in range(bank.table_slots)])
        type_cb.grid(row=0, column=1, sticky="we", padx=2, pady=2)
        type_summary = ttk.Label(frm, text="", foreground="#556", font=("Segoe UI", 8),
                                 wraplength=540, justify="left")
        type_summary.grid(row=1, column=1, sticky="w", padx=2)
        ttk.Label(frm, text="keys:").grid(row=2, column=0, sticky="e", padx=2, pady=2)
        keys_var = tk.StringVar()
        keys_ent = ttk.Entry(frm, textvariable=keys_var, width=54)
        keys_ent.grid(row=2, column=1, sticky="we", padx=2, pady=2)
        keys_hint = ttk.Label(frm, text="", foreground="#556", font=("Segoe UI", 8),
                              wraplength=540, justify="left")
        keys_hint.grid(row=3, column=1, sticky="w", padx=2)
        ttk.Label(frm, text="position:").grid(row=4, column=0, sticky="e", padx=2, pady=2)
        pos_var = tk.StringVar(value="append")
        pos_cb = ttk.Combobox(frm, textvariable=pos_var, values=["append", "first"],
                              state="readonly", width=10)
        pos_cb.grid(row=4, column=1, sticky="w", padx=2, pady=2)
        ttk.Label(frm, text="body:").grid(row=5, column=0, sticky="ne", padx=2, pady=2)
        bf = ttk.Frame(frm); bf.grid(row=5, column=1, sticky="nsew", padx=2, pady=2)
        bsb = ttk.Scrollbar(bf); bsb.pack(side="right", fill="y")
        body = tk.Text(bf, height=10, width=74, font=("Consolas", 10), undo=True,
                       bg="#101014", fg="#d8d8e0", insertbackground="#d8d8e0",
                       yscrollcommand=bsb.set)
        body.pack(side="left", fill="both", expand=True)
        bsb.config(command=body.yview)
        body.insert("1.0", self._new_scene_template())
        err = ttk.Label(frm, text="", foreground="#b02020", wraplength=600, justify="left")
        err.grid(row=6, column=0, columnspan=2, sticky="w", padx=2)
        help_lbl = tk.Label(frm, text=SOURCE_SYNTAX_HELP, justify="left", anchor="w",
                            font=("Consolas", 8), bg="#1b1b22", fg="#e6e6ee", padx=6, pady=4)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(5, weight=1)
        out = {}
        shown = {"help": False}

        def key_names_text(names):
            parts = []
            for k in names:
                if isinstance(k, dict):
                    parts.append(str(k.get("name") or k.get("key") or k))
                elif isinstance(k, (tuple, list)) and k:
                    parts.append(str(k[0]))
                else:
                    parts.append(str(k))
            return ", ".join(parts)

        def on_type(*_):
            try:
                t = int(type_var.get().split()[0])
            except (ValueError, IndexError):
                return
            type_summary.config(text=_type_summary(t))
            keys_var.set(self._default_keys_text(bank, t))
            names = _type_key_names(t)
            keys_hint.config(text=("this type's keys: " + (key_names_text(names) or "(none)"))
                             if names is not None else
                             "key count mirrors the bank's existing entries of this type "
                             "(-1 = wildcard); `(tag, value)` for a non-1 tag")

        def ok(_e=None):
            try:
                t = int(type_var.get().split()[0])
            except (ValueError, IndexError):
                err.config(text="pick an action type"); return
            try:
                keys = parse_entry_keys(keys_var.get())
            except ValueError as ex:
                err.config(text=str(ex)); return
            text = body.get("1.0", "end-1c")
            if not text.strip():
                err.config(text="the body needs at least one statement (FRAME 0 / DIALOG #id / END)")
                return
            _r, _l, e = self._assemble_check(text, base=len(bank.data))
            if e:
                err.config(text=e); return
            out.update(type_id=t, keys=keys, body=text, position=pos_var.get())
            win.destroy()

        def toggle_help():
            if shown["help"]:
                help_lbl.grid_remove()
            else:
                help_lbl.grid(row=7, column=0, columnspan=2, sticky="we", padx=2, pady=(4, 0))
            shown["help"] = not shown["help"]

        bb = ttk.Frame(frm); bb.grid(row=8, column=0, columnspan=2, sticky="we", pady=(6, 0))
        ok_btn = ttk.Button(bb, text="Create scene", command=ok); ok_btn.pack(side="right", padx=2)
        cancel_btn = ttk.Button(bb, text="Cancel", command=win.destroy)
        cancel_btn.pack(side="right", padx=2)
        help_btn = ttk.Button(bb, text="Syntax help", command=toggle_help); help_btn.pack(side="left")
        self._attach_tip(type_cb, DIALOG_CONTROL_HELP["ns_type"])
        self._attach_tip(keys_ent, DIALOG_CONTROL_HELP["ns_keys"])
        self._attach_tip(pos_cb, DIALOG_CONTROL_HELP["ns_position"])
        self._attach_tip(ok_btn, DIALOG_CONTROL_HELP["listing_ok"])
        self._attach_tip(cancel_btn, DIALOG_CONTROL_HELP["listing_cancel"])
        self._attach_tip(help_btn, DIALOG_CONTROL_HELP["listing_help"])
        type_cb.bind("<<ComboboxSelected>>", on_type)
        if default_type is None:
            _t, _r = self._entries_selected()
            if _t is not None:
                default_type = _t
            elif bank is self._bank and self._scene is not None and self._scene.action_type >= 0:
                default_type = self._scene.action_type
            else:
                default_type = next(iter(tt), 0)
        type_cb.current(max(0, min(int(default_type), bank.table_slots - 1)))
        on_type()
        win.bind("<Escape>", lambda _e: win.destroy())
        win.bind("<Control-Return>", ok)
        body.focus_set()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        win.wait_window()
        return out or None

    def _entries_remove(self):
        bank = self._entries_bank
        if bank is None or self.container is None:
            self._status("list a bank first (bank # + List bank)"); return False
        t, r = self._entries_selected()
        if r is None:
            self._status("select an entry row (not the type node) to remove it"); return False
        if not messagebox.askyesno(
                "Remove entry",
                "Unregister %s entry #%d (scene @0x%04x)?\nIts trigger stops firing; the scene's "
                "code stays in the bank as dead bytes." % (_type_label(t), r.index, r.event_id)):
            return False
        try:
            self.container.remove_entry(bank, t, r.index)
        except Exception as e:
            messagebox.showerror("Remove entry", str(e)); return False
        self.script_dirty = True
        self._emf_xref_cache = None
        cpos = self.container.banks.index(bank)
        if self._bank is bank:                      # the scene list shows this bank: re-list it
            self.show_bank(cpos, entry_pc=self._scene.entry_pc if self._scene else None)
        else:
            self._entries_refresh()
        self._status("removed %s entry #%d (scene @0x%04x) from bank %d%s"
                     % (_type_label(t), r.index, r.event_id, cpos, self._dirty_tag()))
        return True

    def _entries_rekey(self):
        bank = self._entries_bank
        if bank is None or self.container is None:
            self._status("list a bank first (bank # + List bank)"); return False
        t, r = self._entries_selected()
        if r is None:
            self._status("select an entry row (not the type node) to re-key it"); return False
        s = simpledialog.askstring(
            "Re-key entry",
            "Keys for %s entry #%d (scene @0x%04x) — a comma list: `5, -1` (-1 = wildcard) or "
            "`(tag, value)` pairs for a non-1 tag:" % (_type_label(t), r.index, r.event_id),
            initialvalue=entry_keys_text(r.subs), parent=self.parent)
        if s is None:
            return False
        return self._entries_set_keys(t, r.index, s)

    def _entries_set_keys(self, type_id, index, keys):
        """Apply new keys (text or list) to entry `index` of `type_id` in the listed bank."""
        bank = self._entries_bank
        if bank is None or self.container is None:
            self._status("list a bank first"); return False
        try:
            subs = parse_entry_keys(keys) if isinstance(keys, str) else list(keys or ())
        except ValueError as e:
            messagebox.showinfo("Re-key entry", str(e)); return False
        try:
            self.container.set_entry(bank, type_id, index, subs=subs)
        except Exception as e:
            messagebox.showerror("Re-key entry", str(e)); return False
        self.script_dirty = True
        self._entries_refresh()
        self._status("%s entry #%d keys -> %s%s" % (_type_label(type_id), index,
                                                    entry_keys_text(subs) or "(none)",
                                                    self._dirty_tag()))
        return True

    def _delete_stmt(self):
        if not self._sel:
            messagebox.showinfo("Delete", "Click a statement first."); return
        if not messagebox.askyesno("Delete", "Skip this statement (the scene jumps over it)?"):
            return
        self._restructure(lambda pc: self.container.delete_statement(self._bank, pc),
                          "deleted statement")

    def _need(self, cond, msg):
        if not cond:
            messagebox.showinfo("Cutscene editor", msg)
        return cond

    def _apply_text(self):
        if not self._need(self.textarc is not None, f"rf3mc.{self.locale} is not loaded."):
            return
        # Edit the SELECTED DIALOG's line; or, when no DIALOG is selected, the line # typed in the
        # line# field. The latter is how an author edits a PROMPT_CHOICE option's text -- choice
        # items are embedded rf3mc line ids (shown in the choice's Ctrl-hover tooltip), not
        # standalone DIALOG statements, so they have no other edit path.
        if self._sel and self._sel[1].mnem == "DIALOG":
            lid = self._sel[1].dialog_id
        else:
            try:
                lid = int(self.line_var.get(), 0)
            except (ValueError, TypeError):
                lid = None
            if not self._need(lid is not None,
                              "Select a DIALOG, or type a line # (e.g. a choice option's id) to edit."):
                return
        new = self.text_box.get("1.0", "end-1c")
        if self._dlg(lid) == new:
            self._status(f"line #{lid} unchanged{self._dirty_tag()}")
            return
        try:
            self.textarc.set_text(lid, new)
        except Exception as e:
            messagebox.showerror("Apply text", str(e)); return
        self.text_dirty = True
        self._render_scene()
        self._status(f"line #{lid} rewritten{self._dirty_tag()}")

    def _sibling_archives(self):
        """{locale: TextArchive} for every OTHER rf3mc.<locale> the reader can supply -- each
        is read and parsed once, then cached (edits to it persist until Save dialogue… /
        Install to game… write it, or a locale switch shows it)."""
        if self.reader is not None:
            for loc in LOCALES:
                if loc == self.locale or loc in self._sibling_arcs or loc in self._sibling_missing:
                    continue
                try:
                    data = self.reader(f"rf3mc.{loc}")
                    arc = textdb.TextArchive.parse(data) if data else None
                except Exception:
                    arc = None
                if arc is None:
                    self._sibling_missing.add(loc)
                else:
                    self._sibling_arcs[loc] = arc
        return {loc: arc for loc, arc in self._sibling_arcs.items() if loc != self.locale}

    def _pad_sibling_locales(self, nid, text):
        """Make line id `nid` exist in every sibling locale archive: append `text` when the
        sibling's next id IS `nid` (the shipped archives all have the same line count), fill a
        shorter archive up to it with `[<locale> TBD]` lines first, and leave one that already
        has the id alone. Touched archives are marked unsaved. Returns [(locale, what)] with
        what in 'appended' / 'padded' / 'had'."""
        out = []
        for loc, arc in sorted(self._sibling_archives().items()):
            if len(arc) > nid:
                out.append((loc, "had")); continue
            gap = 0
            while len(arc) < nid:
                arc.append_text("[%s TBD]" % loc); gap += 1
            arc.append_text(text)
            self._sibling_dirty.add(loc)
            out.append((loc, "padded" if gap else "appended"))
        return out

    def _add_line(self):
        """Append the text box as a brand-new dialogue line and prefill its new id, so the
        author can then Retarget or Insert a DIALOG to reference it. With 'also pad other
        locales' on, the same line is appended to every sibling rf3mc.<locale> the source can
        supply, so the id is in range in every locale (translate it later via the Locale
        switch + Apply text)."""
        if not self._need(self.textarc is not None, f"rf3mc.{self.locale} is not loaded."):
            return
        new = self.text_box.get("1.0", "end-1c")
        if not new.strip():
            messagebox.showinfo("Add line", "Type the new dialogue text in the text box first.")
            return
        nid = self.textarc.append_text(new)
        self.text_dirty = True
        self.line_var.set(str(nid))                     # prefill so Retarget/Insert can use the new id
        where = ""
        if self.pad_locales_var.get():
            padded = self._pad_sibling_locales(nid, new)
            touched = [loc for loc, how in padded if how != "had"]
            if touched:
                where = " (also in " + ", ".join(touched) + ")"
            elif not padded:
                where = " (no other rf3mc.<locale> in this source to pad)"
                try:
                    self.pad_locales_chk.config(state="disabled")
                except tk.TclError:
                    pass
        self._status(f"added new line #{nid}{where} — Retarget or Insert a DIALOG to use it"
                     f"{self._dirty_tag()}")

    def _retarget(self):
        if not self._need(self._sel and self._sel[1].mnem == "DIALOG", "Select a DIALOG statement."):
            return
        try:
            new_id = int(self.line_var.get(), 0)
        except ValueError:
            messagebox.showinfo("Retarget", "Enter a numeric line id."); return
        pc = self._sel[0]
        try:
            self._bank.set_dialog_id(pc, new_id)
        except Exception as e:
            messagebox.showerror("Retarget", str(e)); return
        self.script_dirty = True
        # re-disassemble this scene so the new line text shows
        self._scene = script.disassemble_scene(self._bank, self._scene.action_type, self._scene.entry_pc)
        self._render_scene()
        self._status(f"DIALOG @0x{pc:04x} -> line #{new_id}{self._dirty_tag()}")

    def _apply_args(self):
        """Apply the args row. It shows each argument in listing syntax (what the Source view
        and the assembler use), so a value is typed as a value: `5`, `actor(Forte)`,
        `map(MAP_CITY_00)`, `(FLG_X + 1)`, an enum name, or `@0xNNNN` to point the arg at an
        existing expression. Untouched args are left byte-identical; a changed one is
        patched in place when the new expression has the same length, otherwise appended
        and the arg repointed. (The row used to show and write raw expression OFFSETS, so
        typing a value like 5 silently pointed the arg at byte 5 of the bank.)"""
        if not self._need(self._sel and self._sel[1].op < 0xFFF0, "Select an action statement."):
            return
        pc, st = self._sel
        buf = self._bank.data
        parts = scriptasm._split_top(self.args_var.get())
        if not self._need(len(parts) == len(st.args),
                          f"This statement has {len(st.args)} arg(s); you gave {len(parts)}. "
                          "The arg count can't change here — use Insert… / Source for that."):
            return
        asm = scriptasm.Assembler(resolver=getattr(self.container, "asm_resolver", None))
        plan = []
        for i, (txt, off) in enumerate(zip(parts, st.args)):
            if txt == scriptasm.operand_text(buf, off, st.op, i):
                continue                                    # untouched
            try:
                kind, val = asm.operand(txt, st.op, i)
            except Exception as e:  # noqa: BLE001 - AsmError / ValueError from a bad operand
                messagebox.showerror("Apply args", f"arg {i}: {e}"); return
            if kind == "abs":
                if not (0 <= val < len(buf)) or script.disasm_expr(buf, val)[0] in ("?", ""):
                    messagebox.showerror("Apply args", f"arg {i}: @0x{val:04x} is not an "
                                                       f"expression in this bank"); return
                if val != off:
                    plan.append((i, "abs", val))
            elif bytes(buf[off:off + len(val)]) != val:
                plan.append((i, "expr", val))
        if not plan:
            self._status(f"{st.mnem} @0x{pc:04x}: args unchanged{self._dirty_tag()}")
            return
        try:
            for i, kind, val in plan:
                if kind == "abs":
                    self._bank.set_action_arg(pc, i, val)
                    continue
                off = st.args[i]
                if script.disasm_expr(buf, off)[1] == len(val):
                    buf[off:off + len(val)] = val            # same size: in place
                else:
                    new_off = self.container.grow_bank(self._bank, val)
                    self._bank.set_action_arg(pc, i, new_off)
                    buf = self._bank.data
        except Exception as e:  # noqa: BLE001 - e.g. the bank hit its 64 KB cap
            messagebox.showerror("Apply args", str(e)); return
        self.script_dirty = True
        self._scene = script.disassemble_scene(self._bank, self._scene.action_type, self._scene.entry_pc)
        self._render_scene()
        self._status(f"{st.mnem} @0x{pc:04x}: {len(plan)} arg(s) set{self._dirty_tag()}")

    # ---- save / install -------------------------------------------------- #
    def _save_script(self):
        if not self._need(self.container is not None, "No rf3.mc loaded."):
            return False
        f = filedialog.asksaveasfilename(title="Save rf3.mc", defaultextension=".mc",
                                         initialfile="rf3.mc")
        if not f:
            return False
        try:
            pathlib.Path(f).write_bytes(self.container.build())
        except Exception as e:  # noqa: BLE001 - e.g. a bank over the load buffer, or a locked file
            messagebox.showerror("Save rf3.mc", str(e)); return False
        self.script_dirty = False
        self._mark_saved(mc=True)
        self._status(f"saved rf3.mc -> {f}{self._dirty_tag()}")
        return True

    def _save_text(self):
        """Save the shown locale's archive as a loose file; every OTHER locale with unsaved
        edits (padded by 'Add line', or edited before a locale switch) is written next to it
        under its own rf3mc.<locale> name, so the line ids stay aligned across locales."""
        if not self._need(self.textarc is not None, f"rf3mc.{self.locale} not loaded."):
            return False
        f = filedialog.asksaveasfilename(title=f"Save rf3mc.{self.locale}",
                                         initialfile=f"rf3mc.{self.locale}")
        if not f:
            return False
        saved_locales = self._dirty_locales() | {self.locale}
        pathlib.Path(f).write_bytes(self.textarc.build())
        self.text_dirty = False
        written = [pathlib.Path(f).name]
        for loc in sorted(self._sibling_dirty):
            arc = self._sibling_arcs.get(loc)
            if arc is None or loc == self.locale:
                continue
            p = pathlib.Path(f).parent / f"rf3mc.{loc}"
            p.write_bytes(arc.build())
            written.append(p.name)
        self._sibling_dirty.clear()
        self._mark_saved(locales=saved_locales)
        self._status(f"saved {', '.join(written)} -> {pathlib.Path(f).parent}{self._dirty_tag()}")
        return True

    def _install(self):
        """Install the edited rf3.mc (and edited dialogue, if any) as loose-file
        overrides under a chosen game root. `install_loose` copies from a path and
        uses the bundle-relative name, so we stage temp files first."""
        if not self._need(self.container is not None, "No rf3.mc loaded."):
            return
        root = filedialog.askdirectory(title="Game root (loose files install under it)")
        if not root:
            return
        import tempfile
        stage = pathlib.Path(tempfile.mkdtemp())
        done = []
        try:
            sp = stage / "rf3.mc"; sp.write_bytes(self.container.build())
            mbundle.install_loose(pathlib.Path(root), "rf3.mc", str(sp)); done.append("rf3.mc")
            if self.textarc is not None and self.text_dirty:
                tp = stage / f"rf3mc.{self.locale}"; tp.write_bytes(self.textarc.build())
                mbundle.install_loose(pathlib.Path(root), f"rf3mc.{self.locale}", str(tp))
                done.append(f"rf3mc.{self.locale}")
            for loc in sorted(self._sibling_dirty):     # locales padded / edited off-screen
                arc = self._sibling_arcs.get(loc)
                if arc is None or loc == self.locale:
                    continue
                tp = stage / f"rf3mc.{loc}"; tp.write_bytes(arc.build())
                mbundle.install_loose(pathlib.Path(root), f"rf3mc.{loc}", str(tp))
                done.append(f"rf3mc.{loc}")
        except Exception as e:
            messagebox.showerror("Install", str(e)); return
        self._mark_saved(mc=True, locales=self._dirty_locales())
        self.script_dirty = self.text_dirty = False
        self._sibling_dirty.clear()
        messagebox.showinfo("Install", "Installed loose override(s): " + ", ".join(done) +
                            "\n(the engine loads loose files ahead of the bundles, so no repack is needed).")
        self._status("installed " + ", ".join(done))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = tk.Tk()
    root.title("RF4S Cutscene Editor")
    root.geometry("1180x780")
    reader = None
    if argv:
        d = pathlib.Path(argv[0])
        if d.is_dir():
            reader = lambda n, d=d: (d / n).read_bytes() if (d / n).is_file() else None
    CutsceneExplorer(root, reader=reader)
    root.mainloop()


if __name__ == "__main__":
    main()
