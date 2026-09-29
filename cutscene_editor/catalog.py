"""The trigger-type catalogue (entry_types) as the editor uses it, bank naming, the
listing / Event Manager grammar cheat-sheets, and the caller (xref) lookup."""
from __future__ import annotations

import re

from rf4s_modkit import map_names, script

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
    "  DIALOG #8709                     show rf3mc line 8709 (speaker = the last SetSpeaker)\n"
    "  SetSpeaker(Nancy, Left, 3, 0)    action: name(args) -- mnemonic | technical name | opN\n"
    "  GivePlayerItem(258, reg0 + 1, 0) args: int, expression, enum name, regN, arr[N], @0xOFF (reuse)\n"
    "  BR_Z (REG_WIFE_ID == 11) -> L1   jump when the condition is FALSE (BR_NZ: when TRUE)\n"
    "  EVAL (FLG_EV_DONE = 1)          write a flag / register / arr[N]  (= += -= *= /= %= &&= ||=)\n"
    "  CALL L2  /  JMP L2  /  CALL 0x1234    labels in the listing; 0xPC = existing code in the bank\n"
    "  PROMPT_CHOICE CANCEL -> L2, #123 -> L3, #124 -> L4   choice menu (PROMPT_CHOICE_FORCED: no cancel)\n"
    "  SWITCH (reg1) -> L1, L2, L3  /  JMP_WEIGHTED (3) -> L1, (1) -> L2  /  JMP_RAND L1, L2\n"
    "  BR_END (cond)  /  .raw <hex>  /  END     -- a listing that can fall off its end gets END added"
)

INSERT_PROMPT = ("Statements to insert AFTER the selected one (full listing syntax, one per line):\n"
                 "  GivePlayerItem(258, 1, 0)    EVAL (FLG_EV_DONE = 1)\n"
                 "  BR_Z (REG_WIFE_ID == 11) -> L1  /  DIALOG #5  /  L1:\n"
                 "Names: an opcode mnemonic (GivePlayerItem, SetSpeaker) or a number; FLG_/REG_ variable "
                 "names come from emdeb.bin. Ctrl-Enter = OK.")

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


def type_label(type_id):
    """'type N  Name' from entry_types when available, else 'type N'."""
    if _entry_types is not None:
        try:
            nm = _entry_types.type_name(type_id)
            if isinstance(nm, str) and nm.strip() and nm.strip() != str(type_id):
                return "type %d  %s" % (type_id, nm.strip())
        except Exception:
            pass
    return "type %d" % type_id


def type_summary(type_id):
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


def type_key_names(type_id):
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


def key_problems(type_id, subs):
    """entry_types.key_problems (keys that can never match, e.g. -1 for type 2), or []."""
    if _entry_types is None:
        return []
    try:
        return list(_entry_types.key_problems(type_id, list(subs)))
    except Exception:
        return []


def describe_keys(type_id, subs):
    """Decoded keys of an entry (entry_types.describe_entry), else the raw key list."""
    if _entry_types is not None:
        try:
            s = _entry_types.describe_entry(type_id, list(subs))
            if isinstance(s, str) and s.strip():
                return s.strip()
        except Exception:
            pass
    return entry_keys_text(subs) or "(no keys)"

def type_recipe(type_id):
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
            r = type_recipe(t)
            if r:
                lab = type_label(t)
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


def type_bank_text(type_id):
    """The catalogue's `bank` field for a type, verbatim ('' when absent)."""
    if _entry_types is not None:
        try:
            b = (getattr(_entry_types, "ENTRY_TYPES", {}).get(type_id) or {}).get("bank")
            if isinstance(b, str):
                return b.strip()
        except Exception:
            pass
    return ""


def type_bank_kinds(type_id):
    """The set of Bank.kind values ({'global', 'primary', 'tail'}) the catalogue says the
    engine looks this type up in, or None when the catalogue does not say."""
    s = type_bank_text(type_id).lower()
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



# --------------------------------------------------------------------------- #
# bank naming
# --------------------------------------------------------------------------- #
CHARACTER_BANKS = range(0, 48)          # primary bank = the character's own script bank
VILLAGER_BANKS = range(224, 272)        # primary 224 + char id = villager behaviour scenes
QUEST_DEFAULT_BANK = 210                # the sub-event bank used when no quest is active
EMPTY_BANK_BYTES = 296                  # a bank holding nothing but an empty type table


def _char(i):
    names = getattr(_entry_types, "CHAR_NAMES", {}) if _entry_types is not None else {}
    return names.get(i) or f"character {i}"


def bank_group(bank):
    """Which browser group a bank belongs to."""
    if bank.kind == "tail":
        return "maps"
    if bank.kind == "global":
        return "global"
    if bank.index in CHARACTER_BANKS:
        return "characters"
    if bank.index in VILLAGER_BANKS:
        return "villagers"
    return "subevents"


GROUP_TITLES = (("maps", "Maps"), ("characters", "Characters"),
                ("villagers", "Villager behaviour"), ("subevents", "Sub-events & quests"),
                ("global", "Opening / global"))


def bank_title(bank):
    """A readable name for a bank: 'Map 274 · MAP_DUNG_A04 (Yokmir Forest)',
    'Nancy', 'Villager behaviour · Forte', 'Sub-event 118', 'Opening / global'."""
    if bank.kind == "tail":
        fn = map_names.map_file(bank.index) or f"map {bank.index}"
        place = map_names.describe_destination(bank.index)[0]
        return f"Map {bank.index} · {fn}" + (f" ({place})" if place else "")
    if bank.kind == "global":
        return "Opening / global"
    i = bank.index
    if i in CHARACTER_BANKS:
        return f"{_char(i)}  (bank {i})"
    if i in VILLAGER_BANKS:
        return f"Villager behaviour · {_char(i - 224)}  (bank {i})"
    if i == QUEST_DEFAULT_BANK:
        return f"Quests (default sub-event bank {i})"
    return f"Sub-event bank {i}"


def bank_is_empty(bank):
    """True for a bank with no registered scene (most map banks)."""
    if len(bank.data) <= EMPTY_BANK_BYTES:
        return True
    try:
        return not bank.type_table_full()
    except Exception:
        return False
