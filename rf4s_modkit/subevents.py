"""subevents.py -- the town events ("sub-events"): which rf3.mc bank and em.bin entry belong
together, the diary's title for each, who takes part and what starts it.

Slot i (0..95) is em.bin entry 166 + i (condition A = when it can be picked) and primary bank
48 + i (its scenes). At day change DailyRequest_QueueTomorrowVisitor (RF4S.exe+0x1EDAB0)
reserves one: REG_SUBEV_RSV = 48 + i. Script op 536 StartReservedSubEvent makes it the running
one (REG_SUBEV_NOW = RSV; nothing else in the exe sets NOW outside the title screen's Newlywed
mode). The bank's own scenes call op 536:

* SubEventMapScene (type 39): entering the keyed map -- Map_OnEnter_QueueMapEvents queues game
  event kind 20, whose handler loads bank NOW (else RSV, unless REG_DATE_MAP is set) and runs
  the type-39 entry keyed with the entered map;
* SubEventReaction (type 27), priority 0: talking to the keyed NPC while the event is only
  reserved (Subev_ResolveActiveForNpcReaction picks priority 1 once it runs).

Participants: the em.bin queries SUBEV_ENABLE_<npc> (194..214 = villagers 1..21, 215 = the
child, 216 = the spouse) in the entry's condition. Re-evaluating the picked entry records
them (Script_QueryGameState ORs 1 << npc into a mask), and companions among them are sent
home (game event kind 2 -> their type-21 CompanionLeavesParty scene).

The diary's "Town Events" option (global bank, SWITCH (REG_SUBEV_NOW - 48)) prints
"[Current Event]\\n<title>" for the running event; diary_titles() reads those titles from the
shipped scene, so they follow the loaded dialogue language and any edit of the diary lines.
"""
from __future__ import annotations

from . import map_names, script

FIRST_BANK = 48
FIRST_ENTRY = 166
COUNT = 96
QUERY_ENABLE_FIRST = 194          # SUBEV_ENABLE_<char 1..21>
QUERY_ENABLE_CHILD = 215
QUERY_ENABLE_SPOUSE = 216
START_MNEMONIC = "StartReservedSubEvent"
TYPE_MAP_SCENE = 39
TYPE_REACTION = 27
TYPE_MORNING = 62


def slot_of_bank(index):
    """0..95 for a town-event bank index (48..143), else None."""
    return index - FIRST_BANK if FIRST_BANK <= index < FIRST_BANK + COUNT else None


def bank_of_entry(entry_id):
    """The bank index of em.bin entry `entry_id` (166..261), else None."""
    return entry_id - FIRST_ENTRY + FIRST_BANK if FIRST_ENTRY <= entry_id < FIRST_ENTRY + COUNT else None


def entry_of_bank(index):
    """The em.bin entry id of town-event bank `index`, else None."""
    s = slot_of_bank(index)
    return None if s is None else FIRST_ENTRY + s


def is_subevent_bank(bank):
    return getattr(bank, "kind", None) == "primary" and slot_of_bank(bank.index) is not None


def _char_name(cid):
    try:
        from . import entry_types
        return getattr(entry_types, "CHAR_NAMES", {}).get(cid) or "character %d" % cid
    except Exception:  # noqa: BLE001
        return "character %d" % cid


def participants(em, entry_id):
    """Who the event involves, from the SUBEV_ENABLE_* queries in its condition A (every way):
    [(char id, name)] with char id 0 for the spouse and -1 for the child, in condition order."""
    try:
        e = em.entries[entry_id]
    except (IndexError, KeyError, AttributeError, TypeError):
        return []
    out = []
    for way in getattr(e, "cond_a", None) or []:
        for x in way:
            for o in (getattr(x, "op1", None), getattr(x, "op2", None)):
                if o is None or getattr(o, "kind", None) != "query":
                    continue
                q = o.value
                if QUERY_ENABLE_FIRST <= q < QUERY_ENABLE_CHILD:
                    who = (q - QUERY_ENABLE_FIRST + 1, _char_name(q - QUERY_ENABLE_FIRST + 1))
                elif q == QUERY_ENABLE_CHILD:
                    who = (-1, "your child")
                elif q == QUERY_ENABLE_SPOUSE:
                    who = (0, "your spouse")
                else:
                    continue
                if who not in out:
                    out.append(who)
    return out


def _start_op():
    for o in range(script.DISPATCHABLE_ACTION_OPS):
        if script.opcode_mnemonic(o) == START_MNEMONIC:
            return o
    return None


_START_CACHE = {}


def starters(bank):
    """[(type, EntryRecord)] of the bank's trigger entries whose scene (with the subroutines
    it calls) runs StartReservedSubEvent -- what starts the event. Cached on the bank bytes."""
    key = (id(bank), bytes(bank.data))
    hit = _START_CACHE.get(key)
    if hit is not None:
        return hit
    op = _start_op()
    out = []
    try:
        tt = bank.type_table_full()
    except Exception:  # noqa: BLE001
        tt = {}
    for typ in tt:
        try:
            recs = bank.entry_records(typ)
        except Exception:  # noqa: BLE001
            continue
        for r in recs:
            try:
                sc = script.disassemble_scene(bank, typ, r.event_id)
            except Exception:  # noqa: BLE001
                continue
            if any(st.op == op for st in sc.stmts.values()):
                out.append((typ, r))
    if len(_START_CACHE) > 400:
        _START_CACHE.clear()
    _START_CACHE[key] = out
    return out


def _key_value(subs, i):
    if i >= len(subs):
        return None
    s = subs[i]
    return s[1] if isinstance(s, (tuple, list)) else s


def describe_start(typ, rec):
    """How the player sets off a starting entry: 'entering Selphia: Town Square',
    'talking to Porcoline', 'the next morning' or the raw type."""
    subs = list(getattr(rec, "subs", None) or [])
    if typ == TYPE_MAP_SCENE:
        m = _key_value(subs, 0)
        if m is None or m <= 0:
            return "entering any map"
        return "entering %s" % (map_names.map_name(m) or "map %d" % m)
    if typ == TYPE_REACTION:
        npcs = [_key_value(subs, i) for i in range(1, len(subs))]
        names = ["your spouse" if n == 0 else _char_name(n) for n in npcs if n is not None and n >= 0]
        return "talking to " + (" or ".join(names) if names else "anyone")
    if typ == TYPE_MORNING:
        return "the next morning"
    return "entry type %d" % typ


def diary_titles(container, text):
    """{bank index: title} from the diary's "Town Events" list: the global-bank SWITCH with the
    most cases that open with a DIALOG; case k describes bank 48 + k. `text` = line id -> str
    (the loaded language). Cases with no line (events the diary never names) are left out."""
    best = None
    for bank in getattr(container, "banks", []):
        if getattr(bank, "kind", None) != "global":
            continue
        try:
            scenes = script.disassemble_bank(bank)
        except Exception:  # noqa: BLE001
            continue
        seen = set()
        for sc in scenes:
            for pc, st in sc.stmts.items():
                if pc in seen or st.mnem not in ("SWITCH", "SWITCH_CLAMP") or len(st.code_targets) < 64:
                    continue
                seen.add(pc)
                firsts = []
                for t in st.code_targets:
                    s = script.decode_statement(bank.data, t)
                    firsts.append(s.dialog_id if s is not None and s.mnem == "DIALOG" else None)
                n = sum(1 for f in firsts if f is not None)
                if best is None or n > best[0]:
                    best = (n, firsts)
    out = {}
    if best is None or best[0] < 32:
        return out
    for k, line in enumerate(best[1]):
        if line is None or k >= COUNT:
            continue
        try:
            s = text(line)
        except Exception:  # noqa: BLE001
            s = None
        if s:
            title = s.split("\n", 1)[-1].strip()
            if title:
                out[FIRST_BANK + k] = title
    return out
