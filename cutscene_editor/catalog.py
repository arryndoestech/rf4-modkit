"""The trigger-type catalogue (entry_types) as the editor uses it, bank naming, the
listing / Event Manager grammar cheat-sheets, and the caller (xref) lookup."""
from __future__ import annotations

import re

from rf4s_modkit import map_names, script, subevents

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
    "  FRAME 2                          reserve stack room for nested argument expressions (added\n"
    "                                   and sized by itself when the code needs it; optional)\n"
    "  DIALOG #8709                     show rf3mc line 8709 (speaker = the last SetSpeaker)\n"
    "  SetSpeaker(Nancy, Left, 3, 0)    action: name(args) -- mnemonic | technical name | opN\n"
    "  GivePlayerItem(258, reg0 + 1, 0) args: int, expression, enum name, regN, arr[N], @0xOFF (reuse)\n"
    "  BR_Z (REG_WIFE_ID == 11) -> L1   jump when the condition is FALSE (BR_NZ: when TRUE)\n"
    "  EVAL (FLG_EV_DONE = 1)          write a flag / register / arr[N]  (= += -= *= /= %= &&= ||=)\n"
    "  CALL L2  /  JMP L2  /  CALL 0x1234    labels in the listing; 0xPC = existing code in the bank\n"
    "  PROMPT_CHOICE #123 -> L3, #124 -> L4   choice menu; cancel picks the last option (PROMPT_CHOICE_FORCED: can't cancel)\n"
    "  SWITCH (reg1) -> L1, L2, L3  /  JMP_WEIGHTED (3) -> L1, (1) -> L2  /  JMP_RAND L1, L2\n"
    "  BR_END (cond)  /  .raw <hex>  /  END     -- a listing that can fall off its end gets END added"
)

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


def key_problems(type_id, subs, em=None):
    """entry_types.key_problems (a -1 that is no wildcard, an id that does not exist: a map, a
    character, an em.bin entry of `em` -- the open one), or []."""
    if _entry_types is None:
        return []
    try:
        return list(_entry_types.key_problems(type_id, list(subs), **key_context(em)))
    except Exception:
        return []


def key_context(em=None):
    """What key_problems checks ids against: the em.bin entry count and the game's maps and
    characters (the names the toolkit reads from the game)."""
    from rf4s_modkit import gamenames
    from rf4s_modkit.map_names import map_name
    return {"em_count": len(em.entries) if em is not None else None,
            "map_ok": lambda v: bool(map_name(v)),
            "char_ok": lambda v: bool(gamenames.name("characters", v))}


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
    """The catalogue's `recipe` text for a trigger type (how a scene of that type is set up:
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


MAP_ENTER_TYPE = 6      # MapEnterScene: the map-bank scene run on entering the map (last entry wins)


def map_enter_type():
    """The trigger type a map's ENTER scene is registered under -- the catalogue type named
    MapEnterScene when the catalogue has it, else the engine-verified id 6 (tail bank of
    the entered map, game-event handler 24, the LAST entry wins). Type 7 is MapLeaveScene:
    the scene of the map the player just left."""
    if _entry_types is not None:
        try:
            for t, info in getattr(_entry_types, "ENTRY_TYPES", {}).items():
                if (info or {}).get("name") == "MapEnterScene":
                    return int(t)
        except Exception:
            pass
    return MAP_ENTER_TYPE


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



_XREF_COUNTS = {}


def xref_counts(bank):
    """{pc: how many statements of `bank` lead there} -- CALLs, jumps, branches, switch /
    random targets and choice options, each site once (what the Xrefs window lists for that
    pc). Cached per bank state."""
    key = (id(bank), len(bank.data), hash(bytes(bank.data)))
    hit = _XREF_COUNTS.get(id(bank))
    if hit is not None and hit[0] == key:
        return hit[1]
    sites = {}
    for sc in script.disassemble_bank(bank, discover=True):
        for pc, st in sc.stmts.items():
            if pc not in sites:
                sites[pc] = {t for t in st.code_targets if t is not None}
    out = {}
    for targets in sites.values():
        for t in targets:
            out[t] = out.get(t, 0) + 1
    _XREF_COUNTS[id(bank)] = (key, out)
    return out


def scene_maps(bank, sc):
    """[(map file, why)] a scene belongs to or names, the most direct first: the bank's own
    map (a tail bank is one map's scripts), the map keys of the triggers that start the
    scene, then the map arguments of its statements. Maps without a .rf4m file are left out."""
    from rf4s_modkit import map_names
    out = {}

    def add(mid, why):
        try:
            f = map_names.map_file(int(mid)) if 0 <= int(mid) <= 0xFFFF else None
        except (TypeError, ValueError):
            f = None
        if f and f not in out:
            out[f] = why
    if bank is None:
        return []
    if bank.kind == "tail":
        add(bank.index, "this bank's map")
    if sc is None:
        return list(out.items())
    for t in bank.type_table_full():
        try:
            recs = bank.entry_records(t)
        except Exception:  # noqa: BLE001 -- a convenience
            continue
        for r in recs:
            if r.event_id == sc.entry_pc:
                for tag, val in r.subs:
                    if tag == 0x04:
                        add(val, "trigger key (type %d)" % t)
    buf = bank.data
    for pc, st in sorted(sc.stmts.items()):
        if st.op >= 0xFFF0:
            continue
        for i, off in enumerate(st.args or ()):
            if script.leaf_slot_kind(st.op, i) != "map":
                continue
            if off < len(buf) and buf[off] in (0x03, 0x04):      # a typed constant
                val = int.from_bytes(bytes(buf[off + 1:off + 5]), "little")
            else:
                val, ok = script.eval_expr(buf, off)
                if not ok:
                    continue
            add(val, "%s @0x%04x" % (script.opcode_mnemonic(st.op), pc))
    return list(out.items())


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
                ("villagers", "Villager behaviour"), ("subevents", "Town events & quests"),
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
    slot = subevents.slot_of_bank(i)
    if slot is not None:
        code, title = _SUBEVENT_NAMES.get(i, (None, None))
        rule = subevents.special_rule(subevents.FIRST_ENTRY + slot)
        return "Town event %s%s  (bank %d)%s" % (code or "slot %d" % slot, " · " + title if title else "", i,
                                                 "  ⚑ " + rule[0] if rule else "")
    return f"Sub-event bank {i}"


# Town events (banks 48..143): {bank index: (em.bin name without EV_SUBEV_, diary title)}, set
# from the open document by refresh_subevent_names() (bank_title has no document of its own).
_SUBEVENT_NAMES = {}
_SUBEVENT_KEY = [None]


def subevent_code(doc, entry_id):
    """'COM_26' / 'MRG_MARGUERITE' for em.bin entry `entry_id`, or None without em.bin."""
    em = getattr(doc, "em", None)
    if em is None:
        return None
    try:
        nm = em.names.entry_name(entry_id)
    except Exception:  # noqa: BLE001
        return None
    if not nm:
        return None
    return nm[len("EV_SUBEV_"):] if nm.startswith("EV_SUBEV_") else nm


def refresh_subevent_names(doc):
    """Recompute the town-event names and diary titles when rf3.mc's global bank, the
    dialogue language or em.bin's entry names changed (cheap otherwise)."""
    c = getattr(doc, "container", None)
    if c is None:
        _SUBEVENT_NAMES.clear()
        _SUBEVENT_KEY[0] = None
        return
    codes = tuple(subevent_code(doc, subevents.FIRST_ENTRY + k) for k in range(subevents.COUNT))
    glob = hash(tuple(bytes(b.data) for b in c.banks if b.kind == "global"))
    key = (id(c), getattr(doc, "locale", None), getattr(doc, "textarc", None) is not None, glob, codes)
    if key == _SUBEVENT_KEY[0]:
        return
    titles = subevents.diary_titles(c, doc.text) if getattr(doc, "textarc", None) is not None else {}
    _SUBEVENT_NAMES.clear()
    for k in range(subevents.COUNT):
        i = subevents.FIRST_BANK + k
        _SUBEVENT_NAMES[i] = (codes[k], titles.get(i))
    _SUBEVENT_KEY[0] = key


def bank_is_empty(bank):
    """True for a bank with no registered scene (most map banks)."""
    if len(bank.data) <= EMPTY_BANK_BYTES:
        return True
    try:
        return not bank.type_table_full()
    except Exception:
        return False
