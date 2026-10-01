"""emtext.py -- em.bin (Event Manager) in plain English: labels, value names, sentences and
checks for the Event Manager window and `rf4mod em`.

What the words rest on:
  * entry and query names/labels: emdeb.bin (the debug name table that ships next to em.bin);
    the English descriptions below are translations of its Japanese labels.
  * character names: the romanised names in emdeb (VIZNAR, KEEL, DAG, ...) are the town roster
    in order -- Script_QueryGameState (RF4S.exe+0x1D64D0) reads LOVE_<x> as
    Npc_GetFriendshipLevel(query_id - 13), so LOVE_VIZNAR (14) is char 1 = Vishnal and
    LOVE_SYELZA (34) char 21 = Ventuswill (refdata/char_names.json).
  * query values: Season = the calendar's season (0 Spring .. 3 Winter), Day = the calendar
    day, Party/Party2 = the companions' char ids, PLAYER_MAP = the player's map id (all read in
    Script_QueryGameState). Queries 0 PlayerHP, 1 Weather, 2 WeatherTomorrow and 5 Second have
    NO case in that switch: they always read 0 in RF4S.
  * condition / action semantics: CondScript_EvalEntry (+0x23BDB0) and
    EMF_DispatchActionOpcode (+0x23C390), see emscript's module docstring.
"""
from __future__ import annotations

import re

# ---- characters -------------------------------------------------------------------- #
CHARS = {
    "VIZNAR": "Vishnal", "CLORICA": "Clorica", "CLO": "Clorica", "VOLCANON": "Volkanon",
    "FORTE": "Forte", "KEEL": "Kiel", "BADO": "Bado", "MARGUERITE": "Margaret",
    "DIRUS": "Dylas", "ARTHUR": "Arthur", "POKORINU": "Porcoline", "SYAOPAI": "Xiao Pai",
    "RINFA": "Lin Fa", "KOHAKU": "Amber", "ELMINATA": "Illuminata", "DAG": "Doug",
    "BLOSSOM": "Blossom", "DOLCE": "Dolce", "DOL": "Dolce", "JONES": "Jones",
    "NANCY": "Nancy", "LEON": "Leon", "SYELZA": "Ventuswill", "CHILD": "your child",
    "WIFE": "your spouse",
}


def char_name(cid):
    """A character id's English name (the game's rf3TxtNpc; 0 = the player)."""
    from .emflags import _char_name
    return _char_name(int(cid))


# ---- entries ----------------------------------------------------------------------- #
_ENTRY_TEXT = {
    "EVENT_NONE": "No event (placeholder)",
    "EVENT_BGM_FES": "Festival music",
    "OPENING_EV_FIN": "Turns on the flags for the finished opening",
    "EVM_OP_MY_ROOM": "Indoor trap trigger check (opening)",
    "EVM_OP_FRAM": "Farm trap trigger check (opening)",
    "EVM_OP_FRAM_CENTER": "Farm-centre trap trigger check (opening)",
    "EVM_OP_CASTLE": "Castle hall trap trigger check (opening)",
    "EV_BOSS_SP_DEAD": "The spring boss is defeated",
    "SYELZA_READY": "Ventuswill is present",
    "EM_DUNG_B17_TRAP_CHECK": "Trap before the temple boss",
    "EM_CITY_WEST_TRAP_CHECK": "West district trap check",
    "EM_D_CITY_WEST_TRAP_CHECK": "Ghost: west district",
    "EM_D_CITY_EAST_TRAP_CHECK": "Ghost: east district",
    "EM_D_CITY_NORTH_TRAP_CHECK": "Ghost: north district",
    "EM_D_DUNG_C03_DOOR_CLOSE": "Mansion: the south door closes",
    "EM_E_MY_ROOM_TRAP_CHECK": "Trap in front of the diary",
    "EM_E_DUNG_A03_TRAP_CHECK": "Forest 03 trap",
    "EM_EV_GHOST_END_CHECK": "Ghost event: flag check",
    "EM_EV_DRAGON_ATTACK_BATTLE_CHECK": "A battle is going on in the square",
    "EM_J_DUNG_J06_HIDE_ROAD": "The hidden passage hasn't been used yet",
    "EM_E_DUNG_K06_TRAP_CHECK": "The switch wall can be closed",
    "EM_L_DUNG_L13_WOLF_NEAR": "Approaching the Silver Wolf",
    "EM_L_DUNG_L04_BATTLE": "The all-out fight with the imperial soldiers",
    "EM_BOSS_A_RETURN_MATCH_CHECK": "Forest boss: rematch available",
    "EM_G_SCENARIO_CHECK": "Dungeon G is being explored",
    "EM_BOSS_B_RETURN_MATCH_CHECK": "Temple boss: rematch available",
    "EM_RS1500_SCENARIO_CHECK": "A Rune Sphere is being placed",
    "EV_BOSS_C_RETURN_MATCH_CHECK": "Mansion boss: rematch available",
    "EM_RS2100_SCENARIO_CHECK": "A Rune Sphere is being placed",
    "EM_BOSS_G_RETURN_MATCH_CHECK": "Dead Tree: rematch available",
    "EM_BOSS_B11_RETURN_MATCH_CHECK": "Chimera: rematch available",
    "EM_BOSS_H_RETURN_MATCH_CHECK": "Ancient Bone: rematch available",
    "EM_BOSS_D18_RETURN_MATCH_CHECK": "Fox boss: rematch available",
    "EM_BOSS_D02_RETURN_MATCH_CHECK": "Pharaoh: rematch available",
    "EM_BOSS_J_RETURN_MATCH_CHECK": "Boss J (プロテクローン): rematch available",
    "EM_BOSS_K_RETURN_MATCH_CHECK": "Boss K (フレクザィード): rematch available",
    "EM_BOSS_L_RETURN_MATCH_CHECK": "Boss L (アクナビート): rematch available",
    "ORB_PARTY_CHECK": "Orb event: party check",
    "FIRST_TALK_TUNA": "First talk with トゥーナ",
    "FIRST_TALK_GAZI": "First talk with ガジ",
    "EV_ROOM_04A_FST_END": "The flower shop's first event is over",
    "EV_DAG_SILENT": "Doug's silent period (“…”)",
    "EV_OP_SHIP_BATTLE": "Opening airship battle",
    "EV_IS_GIWAKU": "Suspicion talk",
    "EV_ENDING_MUSIC": "Play the ending song",
    "EV_PROPOSE_DISABLE": "A ring can't be accepted",
    "EV_RING_ADOPT": "A second or later ring",
    "EV_SUBEV_INIT": "Reset the sub-events",
    "EV_QUEST_INIT": "Reset the quests",
    "EV_BATH_SHOP_A": "Bath house open (A)", "EV_BATH_SHOP_B": "Bath house open (B)",
    "EV_ZAKKA_SHOP_A": "General store open (A)", "EV_ZAKKA_SHOP_B": "General store open (B)",
    "EV_FLOWER_SHOP_A": "Flower shop open (A)", "EV_FLOWER_SHOP_B": "Flower shop open (B)",
    "EV_WEAPON_SHOP": "Blacksmith open",
    "EV_RESTAURANT_SHOP": "Restaurant open",
    "EV_HOSPITAL_SHOP_A": "Clinic open (A)", "EV_HOSPITAL_SHOP_B": "Clinic open (B)",
    "EV_TRADE_SHOP": "Arthur's trading post open",
    "EV_RESTAURANT_ONLY_SHOP": "Restaurant open (cooking only)",
    "EV_DRUG_ONLY_SHOP": "Clinic open (medicine only)",
    "EV_CMN_DAYTIME": "Daytime", "EV_CMN_EVENING": "Evening", "EV_CMN_NIGHT": "Night",
    "EV_PLAYER_BIRTH": "The player's birthday",
    "EV_PLAYER_IS_SICK": "The player has a status ailment",
    "EV_WIFE_MORNING_EVENT": "Spouse's morning event",
    "EV_EXCLAMATION": "Exclamation (EX) talk",
    "EV_DATE_APPO": "Reminder talk before a date",
    "EV_DATE_FES_APPO": "A festival date is promised",
    "EV_DATE_APPO_TODAY": "The date is today",
    "EV_DATE_FES_APPO_TODAY": "The festival date is today",
    "EV_DATE_START": "Date start talk (“Did you wait?”)",
    "EV_DATE_START_FES": "Festival date start talk (“Did you wait?”)",
    "EV_DATE_COOKIE_WAIT": "The cookie hasn't been handed over yet",
    "EV_DATE_FINISH": "Reset after a date",
    "EV_DATE_MISS": "Grumpy after a missed date",
    "EV_JEERING": "Teasing",
    "EV_CONCEPTION_ASK": "Asking about having a baby",
    "EV_CONCEPTION_EVENT": "Pregnancy event",
    "EV_CHILD_TYPE_SET": "Decide the child's gender",
    "EV_CHILD_BIRTH": "Childbirth",
    "EV_ESCAPE_MISS": "Failed escape situation",
    "EV_CHILD_BIRTHDAY": "The child's birthday",
    "EV_CHILD_ME_BIRTHDAY": "The child's birthday",
    "EV_IS_MARRIGE_TODAY": "Wedding anniversary",
    "EV_DOLCE_SUBEV09_AFTER_DAY": "The day after Dolce's sub-event 09",
    "EV_DOLCE_SUBEV_09_AFTER_SYAO": "The day after sub-event 09 (Xiao Pai and Dolce)",
    "EV_PRINCE_NAVI": "Guide to the prince signboard",
    "EV_FOREST_NAVI": "Guide to the forest dungeon",
    "EV_NIGHT_STONE_START": "Night stone: it has been darkened",
    "EV_NIGHT_STONE_END": "Night stone: it hasn't been darkened",
    "EV_HUTAGO_NOT_CLEAR": "The twin rocks aren't cleared",
    "EV_MYSHOP": "Your own shop",
    "EV_BRIDGE_FIELD_98": "Bridge (field 98)",
    "EV_IS_MAN": "The player is male",
    "EV_IS_WOMAN": "The player is female",
    "EV_RQ_SHIP_GOLD": "Shipped 1,000,000 G or more",
    "EV_RQ_SKILL_WEAPON_LV": "A weapon skill is level 15 or higher",
    "EV_RQ_SKILL_MAGIC_LV": "A magic skill is level 15 or higher",
    "EV_MAP_HIGH": "A high place",
    "EV_MAP_DARK": "A dark place",
    "EV_FIRECAST": "Explaining the good-harvest forecast",
    "EV_SUBEV_COM_06": "Everyday event 06: the secret of getting along",
    "EV_SUBEV_COM_14": "Everyday event 14: turn the flag on",
    "EV_SUBEV_COM_49": "Everyday event 49: epilogue 1",
    "EV_SUBEV_MRG_DUM1": "Family event placeholder 1",
    "EV_SUBEV_MRG_DUM2": "Family event placeholder 2",
    "EV_SUBEV_COM_01_PARTYCHECK": "Everyday event 01: party check",
    "EV_SUBEV_COM_10_RES": "Everyday event 10 (restaurant)",
    "EV_SUBEV_COM_10_ZAK": "Everyday event 10 (general store)",
    "EV_SUBEV_COM_14_A": "Everyday event 14: north district – the lost traveller",
    "EV_SUBEV_COM_14_B": "Everyday event 14: west district – picking up litter",
    "EV_SUBEV_COM_14_C": "Everyday event 14: east district – Margaret",
    "EV_SUBEV_DAG_MARRIAGE_Night": "Doug (married): alone at night",
    "EV_SUBEV_CLO_IN_PARTY": "Clorica is in the party",
    "EV_SUBEV_DOL_IN_PARTY": "Dolce is in the party",
    "SUBEV_MAX": "End marker (sub-event count)",
}

_ENTRY_PATTERNS = (
    (r"EV_(\w+?)_LIVE", lambda c: "%s lives in town" % c),
    (r"EV_SKILL_(\w+?)_B", lambda c: "%s praises your skills (2)" % c),
    (r"EV_SKILL_(\w+)", lambda c: "%s praises your skills" % c),
    (r"EV_FIRST_TALK_AFTER_(\w+)", lambda c: "After the first talk with %s" % c),
    (r"EV_LOVE_TALK_(\w+)", lambda c: "%s's love-level milestone talk" % c),
    (r"EV_SUBEV_MRG_(\d+)", None),
    (r"EV_SUBEV_MRG_(\w+)", lambda c: "Marriage event: %s" % c),
    (r"EV_SUBEV_(\w+?)_JUST_MARRIED", lambda c: "Newlyweds: %s" % c),
)


def entry_text(name):
    """An English description of an entry, from its emdeb name (translated labels)."""
    if not name:
        return ""
    if name in _ENTRY_TEXT:
        return _ENTRY_TEXT[name]
    m = re.fullmatch(r"EV_SUBEV_COM_(\d+)", name)
    if m:
        return "Everyday event %s" % m.group(1)
    m = re.fullmatch(r"EV_SUBEV_MRG_(\d+)", name)
    if m:
        return "Family event %s" % m.group(1)
    for pat, fn in _ENTRY_PATTERNS:
        m = re.fullmatch(pat, name)
        if m and fn is not None and m.group(1) in CHARS:
            return fn(CHARS[m.group(1)])
    return ""


# browser groups: (key, title, test(name, idx))
GROUPS = (
    ("custom", "Your entries", lambda n: not entry_text(n)),
    ("time", "Time of day", lambda n: n.startswith("EV_CMN_")),
    ("shops", "Shops", lambda n: n.endswith("_SHOP") or "_SHOP_" in n or n == "EV_MYSHOP"),
    ("dates", "Dates", lambda n: n.startswith("EV_DATE_") or n in ("EV_JEERING", "EV_ESCAPE_MISS")),
    ("family", "Marriage & family",
     lambda n: n.startswith(("EV_SUBEV_MRG_", "EV_CONCEPTION", "EV_CHILD", "EV_WIFE_", "EV_PROPOSE",
                             "EV_RING_", "EV_IS_MARRIGE")) or n.endswith("_JUST_MARRIED")
     or n == "EV_SUBEV_DAG_MARRIAGE_Night"),
    ("love", "Love-level talks", lambda n: n.startswith("EV_LOVE_TALK_")),
    ("praise", "Skill praise", lambda n: n.startswith("EV_SKILL_")),
    ("everyday", "Everyday events",
     lambda n: n.startswith(("EV_SUBEV_COM_", "EV_DOLCE_SUBEV")) or n.endswith("_IN_PARTY")),
    ("people", "Residents & first meetings",
     lambda n: n.endswith("_LIVE") or n.startswith(("EV_FIRST_TALK_AFTER_", "FIRST_TALK_"))
     or n in ("SYELZA_READY", "EV_DAG_SILENT")),
    ("player", "The player", lambda n: n.startswith(("EV_PLAYER_", "EV_IS_", "EV_RQ_", "EV_EXCLAMATION"))),
    ("bosses", "Boss rematches", lambda n: "RETURN_MATCH" in n or n == "EV_BOSS_SP_DEAD"),
    ("dungeons", "Traps & dungeons",
     lambda n: n.startswith(("EM_", "EVM_OP_")) or n in ("ORB_PARTY_CHECK",)),
    ("story", "Story & world", lambda n: bool(n) and n not in ("EVENT_NONE", "SUBEV_MAX")
     and not n.startswith(("EV_SUBEV_INIT", "EV_QUEST_INIT"))),
    ("system", "System", lambda n: True),
)


def entry_group(name):
    n = name or ""
    for key, _title, test in GROUPS:
        if test(n):
            return key
    return "system"


# ---- queries (Script_QueryGameState ids) --------------------------------------------- #
SEASONS = {0: "Spring", 1: "Summer", 2: "Autumn", 3: "Winter"}
WEATHER = {0: "sunny", 1: "rain", 2: "snow", 3: "storm"}         # emdeb's own label for id 1
BOOL = {0: "no", 1: "yes"}
UNHANDLED_QUERIES = {0, 1, 2, 5}      # no case in Script_QueryGameState: always 0 in RF4S

_SKILLS = {
    "SWORD": "Short sword", "LSWORD": "Long sword", "LANCE": "Spear", "AXE": "Axe & hammer",
    "DSWORD": "Dual blades", "FIGHT": "Fist", "FIRE": "Fire", "WATER": "Water", "EARTH": "Earth",
    "WIND": "Wind", "SHINE": "Light", "DARK": "Dark", "LOVE": "Love", "FARM": "Farming",
    "LUMBER": "Logging", "MINING": "Mining", "FISHING": "Fishing", "COOKING": "Cooking",
    "SMITH": "Forging", "MIX": "Chemistry", "DECO": "Crafting", "SEARCH": "Searching",
    "WALK": "Walking", "GROW": "Sleeping", "EAT": "Eating", "GUARD": "Defense",
    "POISON": "Poison resistance", "SEAL": "Seal resistance", "PARALYSIS": "Paralysis resistance",
    "SLEEP": "Sleep resistance", "TIRED": "Fatigue resistance", "SICK": "Cold resistance",
    "DEATH": "Faint resistance", "BATH": "Bathing", "MONSTER": "Taming", "THROW": "Throwing",
    "LEADER": "Leadership", "SHOP": "Shopping",
}
_SHOPS = {"BATH": "the bath house", "FLOWER": "the flower shop", "ZAKKA": "the general store",
          "WEAPON": "the blacksmith", "HOSP": "the clinic", "EAT": "the restaurant",
          "TRADE": "the trading post", "DRUG": "the clinic (medicine only)"}
_QUERY_TEXT = {
    "PlayerHP": ("Player HP", None), "Weather": ("Today's weather", "weather"),
    "WeatherTomorrow": ("Tomorrow's weather", "weather"), "Hour": ("Hour of the day (0–23)", None),
    "Minute": ("Minute", None), "Second": ("Second", None), "Year": ("Year", None),
    "Season": ("Season", "season"), "Day": ("Day of the month", None),
    "WeekDay": ("Weekday, as the game counts it: (day − 1) mod 6", None),
    "LoveLvCurrent": ("Love level of the person you're talking to (0–10)", None),
    "LovePointCurrent": ("Love points of the person you're talking to", None),
    "Party": ("First companion", "char"), "Party2": ("Second companion", "char"),
    "IS_MAN": ("The player is male", "bool"), "MET_ALL": ("Has met everyone", "bool"),
    "SCENARIO_RAND": ("Random number for story-talk variations", None),
    "CURRENT_BIRTH_TALK_IS_ENABLE": ("A birthday talk is available", "bool"),
    "CURRENT_CHAR_IS_WIFE": ("The person you're talking to is your spouse", "bool"),
    "CURRENT_CHAR_IS_PARTY": ("The person you're talking to is in your party", "bool"),
    "CURRENT_CHAR_IS_PARTNER": ("The person you're talking to is dating you", "bool"),
    "PARTNER_NUM": ("How many people you're dating", None),
    "FMON_COUNT": ("Number of companions (仲間数)", None),
    "CHILD_BIRTH_OK": ("A child can be born", "bool"),
    "CUR_CHR_FLOWER_TALK": ("Flower-fortune flag of the person you're talking to", None),
    "CUR_CHR_TRANS_CHECK": ("Transformation check for the person you're talking to", None),
    "PLAYER_IS_SICK": ("The player can have status-ailment talk", "bool"),
    "PLAYER_IN_MYROOM": ("The player is at home", "bool"),
    "CUR_EXCLAMATION": ("Exclamation (EX) talk", None),
    "DATE_STATE": ("Date state of the person you're talking to", "date"), "PLAYER_MAP": ("The player's current map", "map"),
    "DATE_SUPPO": ("Stood-up-date state", None), "JEERING": ("Teasing talk", None),
    "SKILL_WEAPON": ("Best weapon skill level", None), "SKILL_MAGIC": ("Best magic skill level", None),
    "SKILL_RESIST": ("Best resistance skill level", None),
    "ORDER_SYMBOL": ("An ORDER symbol is present", "bool"),
    "SHIPMENT_GOLD": ("Total shipment value (G)", None),
    "PLAYER_IS_MAN": ("The player is male", "bool"), "PRINCE_RANK": ("Prince rank", None),
    "MYSHOP_CHECK": ("Your own shop's talk is available", "bool"),
    "IS_WBED": ("Owns a double bed", "bool"),
}


def query_info(names, qid, raw=False):
    """(label, value kind or None, note) for a query id. Kinds: 'bool', 'season',
    'weather', 'char', 'map'. `note` flags queries RF4S never answers. `raw` labels it with
    its emdeb name (SUBEV_ENABLE_ARTHUR) instead of the English description."""
    lab, kind, note = _query_info(names, qid)
    if raw:
        en = names.query_name(qid) if names is not None else None
        lab = en or "query %d" % qid
    return lab, kind, note


def _query_info(names, qid):
    en = names.query_name(qid) if names is not None else None
    note = ("RF4S doesn't answer this query: it always reads 0" if qid in UNHANDLED_QUERIES else "")
    if not en:
        return ("query %d" % qid, None, note)
    if en in _QUERY_TEXT:
        lab, kind = _QUERY_TEXT[en]
        return (lab, kind, note)
    for pre, fmt, kind in (("LOVE_", "Love level with %s", None), ("MET_", "Has met %s", "bool"),
                           ("CUR_CHR_NEAR__", "The person you're talking to can chat with %s", "bool"),
                           ("RUNAWAY_", "%s has run away from home", "bool"),
                           ("PARTNER_", "Dating %s", "bool"),
                           ("SUBEV_ENABLE_", "%s is free for a sub-event", "bool")):
        if en.startswith(pre) and en[len(pre):] in CHARS:
            return (fmt % CHARS[en[len(pre):]], kind, note)
    if en.startswith("SKILL_") and en[6:] in _SKILLS:
        return ("%s skill level" % _SKILLS[en[6:]], None, note)
    m = re.fullmatch(r"SHOP_ON_([A-Z]+?)(?:_([AB]))?", en)
    if m and m.group(1) in _SHOPS:
        return ("Someone is at the counter of %s%s" % (_SHOPS[m.group(1)],
                                                      " (%s)" % m.group(2) if m.group(2) else ""),
                "bool", note)
    return (en, None, note)


def value_names(kind):
    """{value: name} for a value kind (None when numbers are all there is)."""
    if kind == "bool":
        return dict(BOOL)
    if kind == "season":
        return dict(SEASONS)
    if kind == "weather":
        return dict(WEATHER)
    if kind == "date":
        from .opcode_meta import DATE_STATES
        return {v: nm for v, (nm, _d) in DATE_STATES.items()}
    if kind == "char":
        out = {}
        for cid in range(0, 30):
            nm = char_name(cid)
            if nm:
                out[cid] = nm
        return out
    return None


def value_text(kind, v):
    """A value in words for its kind ('Spring', 'yes', 'Kiel', a map name) or ''."""
    if kind is None:
        return ""
    if kind == "map":
        from .map_names import map_name
        return map_name(int(v)) or ""
    return (value_names(kind) or {}).get(int(v), "")


# ---- variables (emdeb flags / registers) --------------------------------------------- #
def variable_kind(var):
    return "bool" if var is not None and var.bit_width == 1 else None


def variable_label(var):
    """A variable's name plus its Japanese label, as shown in pickers."""
    if var is None:
        return "?"
    return var.name + (("  — " + var.jp_name) if getattr(var, "jp_name", "") else "")


# ---- zone 2: the recovered flags emdeb doesn't name ----------------------------------- #
# em.bin's variable operands carry ABSOLUTE bit ids (CondScript_ResolveOperandValue reads them
# like GameFlags_ReadField), so they can reach zone 2 (absolute 4096 + relative id) -- the
# part of the flag store emdeb.bin names nothing in. emflags.ZONE2_BLOCKS is the recovered map.
def zone2_rel(o):
    """The zone-2 relative id of a 1-bit operand past emdeb's names, or None."""
    from .emflags import ZONE2_BASE
    if o is None or o.kind != "flag" or o.value < ZONE2_BASE:
        return None
    return o.value - ZONE2_BASE


def zone2_choices():
    """[(picker text, operand token)] for the zone-2 bits that have a meaning: the named single
    bits, one entry per character for the per-NPC blocks, per shop-door hour and per recipe.
    The anonymous bands (per-map scene bits, boxes, daily-reset bits) are typed as flag@BIT/1."""
    from .emflags import ZONE2_BASE, ZONE2_BLOCKS
    out = []
    for lo, hi, name, _detail in ZONE2_BLOCKS:
        base = name.split(" (")[0]
        if lo == hi:
            rels = [(lo, base)]
        elif "+ char" in name:
            rels = []
            for rel in range(lo, hi + 1):
                who = char_name(rel - lo) or "char %d" % (rel - lo)
                rels.append((rel, "%s \u00b7 %s" % (base, who)))
        elif "recipe_no" in name:
            rels = [(rel, "%s \u00b7 recipe %d" % (base, rel - 1062)) for rel in range(lo + 1, hi + 1)]
        elif "shop-door" in name:
            rels = [(rel, "%s \u00b7 #%d" % (base, rel - lo)) for rel in range(lo, hi + 1)]
        else:
            continue
        for rel, text in rels:
            out.append(("zone 2 \u00b7 %s  [z%d]" % (text, rel), "flag@%d/1" % (ZONE2_BASE + rel)))
    return out


# ---- operands and sentences ------------------------------------------------------------ #
def operand_kind(names, o):
    """The value kind an operand's value is measured in ('bool', 'season', ...)."""
    if o is None:
        return None
    if o.kind == "query":
        return query_info(names, o.value)[1]
    if o.kind == "flag":
        v = names.flag_at(o.value)
        return "bool" if o.width == 1 else (variable_kind(v) if v is not None and v.bit_offset == o.value else None)
    return None


def operand_text(names, o, kind=None, raw=False):
    """An operand in words: a query's label (its emdeb name with `raw`), a variable's name,
    or a value (named for `kind` when it has names: 'Spring (0)')."""
    if o is None:
        return "?"
    if o.kind == "query":
        return query_info(names, o.value, raw)[0]
    if o.kind == "flag":
        rel = zone2_rel(o)
        v = names.flag_at(o.value)
        if rel is not None and (v is None or v.bit_offset != o.value):
            from .emflags import zone2_text
            return "zone-2 flag " + zone2_text(rel)
        return o.pretty(names)
    if o.kind in ("lit", "slit"):
        v = o.pretty(names)
        nm = value_text(kind, int(v)) if kind else ""
        return ("%s (%s)" % (nm, v)) if nm else v
    return o.pretty(names)


CMP_WORDS = {"==": "is", "!=": "is not", ">": "is more than", ">=": "is at least"}
WORDS_CMP = {v: k for k, v in CMP_WORDS.items()}


def expr_text(names, x, entry_label=None, raw=False):
    """One requirement as a sentence. `raw` names queries by their emdeb names (pass an
    `entry_label` that gives entry names to name entries the same way)."""
    lab = entry_label or (lambda i: "#%d" % i)
    if x.kind == "true":
        return "always"
    if x.kind == "false":
        return "never"
    if x.kind == "cond_a":
        return "“%s” is true" % lab(x.ref)
    if x.kind == "not_cond_a":
        return "“%s” is false" % lab(x.ref)
    if x.kind == "cond_b":
        return "“%s” passes its other test (B)" % lab(x.ref)
    if x.kind == "not_cond_b":
        return "“%s” fails its other test (B)" % lab(x.ref)
    a, b, op = x.op1, x.op2, x.cmp
    # the VM has no < / <=: `12 > Hour` is how em.bin writes "Hour < 12" -- read it that way
    flipped = a is not None and b is not None and a.kind in ("lit", "slit") and b.kind not in ("lit", "slit")
    if flipped:
        a, b = b, a
    ka, kb = operand_kind(names, a), operand_kind(names, b)
    left = operand_text(names, a, kb, raw)
    # on/off values read as a statement: "X" / "not: X", "FLG_Y is on" / "is off"
    if ka == "bool" and b is not None and b.kind in ("lit", "slit") and op in ("==", "!=") \
            and int(b.value) in (0, 1):
        truth = (int(b.value) == 1) == (op == "==")
        if a.kind == "flag":
            return "%s is %s" % (left, "on" if truth else "off")
        return left if truth else "not: " + (left if raw else left[:1].lower() + left[1:])
    right = operand_text(names, b, ka, raw)
    words = ({">": "is less than", ">=": "is at most"}.get(op) if flipped else None) or CMP_WORDS.get(op, op)
    return "%s %s %s" % (left, words, right)


ACTION_WORDS = {
    "SET": "set {t} to {v}", "ADD": "add {v} to {t}", "SUB": "subtract {v} from {t}",
    "MUL_S": "multiply {t} by {v}", "MUL_U": "multiply {t} by {v} (unsigned)",
    "DIV_S": "divide {t} by {v}", "DIV_U": "divide {t} by {v} (unsigned)",
    "MOD_S": "set {t} to the remainder of {t} ÷ {v}",
    "MOD_U": "set {t} to the remainder of {t} ÷ {v} (unsigned)",
    "MAX_S": "raise {t} to at least {v}", "MAX_U": "raise {t} to at least {v} (unsigned)",
    "MIN_S": "lower {t} to at most {v}", "MIN_U": "lower {t} to at most {v} (unsigned)",
    "SET_EQ_ZERO": "set {t} to 1 if {v} is 0, else 0",
}
# the operation choices the Inspector offers, in words (the engine's own op names in brackets)
ACTION_CHOICES = [("set to", "SET"), ("add", "ADD"), ("subtract", "SUB"), ("multiply by", "MUL_S"),
                  ("divide by", "DIV_S"), ("remainder of dividing by", "MOD_S"),
                  ("raise to at least", "MAX_S"), ("lower to at most", "MIN_S"),
                  ("set to 1 if the value is 0", "SET_EQ_ZERO"),
                  ("multiply by (unsigned)", "MUL_U"), ("divide by (unsigned)", "DIV_U"),
                  ("remainder (unsigned)", "MOD_U"), ("raise to at least (unsigned)", "MAX_U"),
                  ("lower to at most (unsigned)", "MIN_U")]


def action_text(names, a, entry_label=None, raw=False):
    lab = entry_label or (lambda i: "#%d" % i)
    if a.name == "CALL":
        return "also run the actions of “%s”" % lab(a.entry)
    kind = operand_kind(names, a.target)
    t = operand_text(names, a.target, None, raw)
    if kind == "bool" and a.name == "SET" and a.value is not None and a.value.kind in ("lit", "slit") \
            and int(a.value.value) in (0, 1):
        return "turn %s %s" % (t, "on" if int(a.value.value) else "off")
    v = operand_text(names, a.value, kind, raw)
    return ACTION_WORDS.get(a.name, a.name + " {t} {v}").format(t=t, v=v)


def groups_of(exprs):
    """A slot's expressions as OR-groups: [[(index, Expr), ...], ...] (groups AND together)."""
    out, cur = [], []
    for i, x in enumerate(exprs):
        cur.append((i, x))
        if not x.or_next:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


# ---- checks ------------------------------------------------------------------------ #
def problems(em):
    """[(level, entry idx, path, message)] -- level 'error' breaks the game (Save refuses),
    'warning' is almost certainly not what was meant. path = ('expr', which, slot, i) or
    ('act', stream, i) or None."""
    out = []
    n = len(em.entries)
    names = em.names
    from .emflags import GAMEFLAGS_BITS_TOTAL
    total_bits = GAMEFLAGS_BITS_TOTAL          # g_gameFlagsBuffer: zone 1 + zone 2

    def check_operand(e, path, o, what):
        if o is None:
            return
        if o.kind == "query":
            if not 0 <= o.value < len(names.query_names):
                out.append(("error", e.idx, path, "%s: query %d doesn't exist" % (what, o.value)))
            elif o.value in UNHANDLED_QUERIES:
                out.append(("warning", e.idx, path, "%s: %s — %s" % (
                    what, query_info(names, o.value)[0], query_info(names, o.value)[2])))
        elif o.kind == "flag":
            if not 1 <= int(o.width) <= 32:
                out.append(("error", e.idx, path, "%s: variable width %d is outside 1..32" % (what, o.width)))
            if total_bits and o.value + o.width > total_bits:
                out.append(("error", e.idx, path, "%s: bits %d..%d are past the end of the %d-bit game "
                            "flag store (nothing bounds-checks it)" % (what, o.value, o.value + o.width - 1,
                                                                        total_bits)))

    for e in em.entries:
        for which, slots in (("a", e.cond_a), ("b", e.cond_b)):
            for si, xs in enumerate(slots or ()):
                if xs and xs[-1].or_next:
                    out.append(("error", e.idx, ("expr", which, si, len(xs) - 1),
                                "the last requirement of a way is linked with OR to nothing"))
                for xi, x in enumerate(xs):
                    path = ("expr", which, si, xi)
                    if x.kind in ("cond_a", "not_cond_a", "cond_b", "not_cond_b"):
                        if not 0 <= x.ref < n:
                            out.append(("error", e.idx, path, "refers to entry #%d, which doesn't exist "
                                        "(it would always read false)" % x.ref))
                    elif x.kind == "cmp":
                        check_operand(e, path, x.op1, "left side")
                        check_operand(e, path, x.op2, "right side")
                        for var, lit in ((x.op1, x.op2), (x.op2, x.op1)):
                            if var is not None and lit is not None and var.kind == "flag" \
                                    and lit.kind == "lit" and var.width < 32 and not var.sign:
                                top = (1 << int(var.width)) - 1
                                if int(lit.value) > top:
                                    out.append(("warning", e.idx, path, "%s holds at most %d (%d bit%s), "
                                                "so comparing it with %d is never what it looks like"
                                                % (var.pretty(names), top, var.width,
                                                   "" if var.width == 1 else "s", lit.value)))
        for stream, acts in (("main", e.actions), ("alt", e.alt_actions)):
            for ai, a in enumerate(acts or ()):
                path = ("act", stream, ai)
                if a.name == "CALL":
                    if not 0 <= a.entry < n:
                        out.append(("error", e.idx, path, "runs entry #%d, which doesn't exist" % a.entry))
                    continue
                check_operand(e, path, a.target, "target")
                check_operand(e, path, a.value, "value")
                if a.target is not None and a.target.kind != "flag":
                    out.append(("warning", e.idx, path, "the target isn't a variable, so the game "
                                "has nowhere to write the result"))
                if a.name.startswith(("DIV", "MOD")) and a.value is not None \
                        and a.value.kind in ("lit", "slit") and int(a.value.value) == 0:
                    out.append(("error", e.idx, path, "divides by zero"))
    out += _cycles(em)
    return out


def _cycles(em):
    """Loops the engine would follow forever: an entry whose condition (A or B) asks, through
    other entries, for itself -- CondScript_EvalEntry recurses into the referenced entry --
    and CALL chains that come back to the start (main calls main, alt calls alt)."""
    out = []
    n = len(em.entries)
    kinds = {"cond_a": "a", "not_cond_a": "a", "cond_b": "b", "not_cond_b": "b"}
    graph = {}
    for e in em.entries:
        for which, slots in (("a", e.cond_a), ("b", e.cond_b)):
            graph[(e.idx, which)] = [(x.ref, kinds[x.kind]) for xs in slots or () for x in xs
                                     if x.kind in kinds and 0 <= x.ref < n]
        for stream, acts in (("main", e.actions), ("alt", e.alt_actions)):
            graph[(e.idx, stream)] = [(a.entry, stream) for a in acts or ()
                                      if a.name == "CALL" and 0 <= a.entry < n]
    state, stack, reported = {}, [], set()

    def visit(node):
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, ()):
            if state.get(nxt) == 1:
                loop = stack[stack.index(nxt):]
                key = frozenset(loop)
                if key not in reported:
                    reported.add(key)
                    what = "condition loops" if nxt[1] in ("a", "b") else "actions loop"
                    chain = " → ".join("#%d" % k[0] for k in loop + [nxt])
                    out.append(("error", nxt[0], None, "its %s back to itself (%s): the game would "
                                "never finish %s" % (what, chain, "evaluating it" if nxt[1] in ("a", "b")
                                                     else "running them")))
            elif state.get(nxt) is None:
                visit(nxt)
        stack.pop()
        state[node] = 2

    import sys
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 10000))
    try:
        for node in list(graph):
            if state.get(node) is None:
                visit(node)
    finally:
        sys.setrecursionlimit(old)
    return out
