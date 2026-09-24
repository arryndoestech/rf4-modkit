"""Catalogue of the rf3.mc action-entry TYPES (the per-bank "type table").

Every rf3.mc bank (global / 248 primary / 872 tail) starts with a type table of
74 slots (u16 count, u16 list_off per slot; the slot count is header word 14 of
the MYCF header, byte 56, read by SceneState_ParseMycfHeaderAndInstallReaders
RF4S.exe+0x23DAB0 into sceneCtx+184).  Each list entry is
``{u16 size; u16 event_id; size x {u8 tag; i32 value}}``: event_id is the code
PC of the scene inside the same bank, the 5-byte sub-records are the entry's
KEYS.  This module names each type, says which runtime value every key index is
compared against, how the winning entry is chosen and what consumes the chosen
event_id.  Evidence is cited as IDB function names plus RF4S.exe+RVA.

Bank slots (sceneCtx+200/+208/+216, built by ScriptTask_FirstTimeInit
RF4S.exe+0x1EE060 with modes 0/1/2):
  slot 0 = the global bank,
  slot 1 = one PRIMARY bank, re-loaded on demand by
           Npc_QueryHasPendingActionForActor RF4S.exe+0x23F9C0 with an index
           that is either a canonical NPC char id (0..47; 23->22, 27..33->27,
           34..40->34, 41..47->41), 224 + canonical id (the villagers' second
           bank), a sub-event id (REG_SUBEV_NOW / quest id, 48..210), or a
           story-chapter bank 211..224 (NpcAi_CheckSpecialEventCondition
           RF4S.exe+0x1FEAB0),
  slot 2 = the TAIL bank of the current map (index = map id).
NpcAi_ApplyMovement RF4S.exe+0x1F60C0 (mode = bank slot, event_id = PC) is the
consumer for almost every type: it points the NPC script state machine at the
chosen PC (33060 = "no scene" sentinel).

Sub-record tags seen in the corpus: 0x01 plain int, 0x02 packed game-flag
reference (bit offset & 0xFFFE0FFF, width (v>>12)+1), 0x03 NPC char id,
0x04 map id.  Map ids below 64 are canonicalised with ``id & ~3`` wherever they
are compared (player actor field_54 holds the current map id).

Only the standard library is used; nothing here imports other toolkit modules.
"""

from __future__ import annotations

SENTINEL_NONE = 33060          # event_id meaning "no scene"
TYPE_TABLE_SLOTS = 74          # MYCF header word 14 (byte 56) in the shipped rf3.mc

TAG_NAMES = {
    0x01: "int",
    0x02: "flagvar",     # packed game-flag reference
    0x03: "npc",         # NPC char id
    0x04: "map",         # map id
    0x11: "type4",       # normalised 4 by Npc_ReadActionEntrySubBytes, unseen in corpus
    0x12: "type5",
    0x13: "type6",
}

BANK_SLOTS = {0: "global", 1: "primary", 2: "tail"}

# Character ids 0..47 (== the primary bank index of that character's script bank; 0 = the
# player). Taken from the shipped rf3TxtNpc name list (vendored refdata/char_names.json).
# The hand-written table this replaces had 24 Pico / 27 Barrett / 28 Raven, which is wrong:
# rf3TxtNpc and the banks' own dialogue agree on 24 Barrett (bank 24 = the gear check),
# 25 Raven, 26 Mistress Trupin (bank 26 = "My name is Trupin"), 27..40 Traveler,
# 41..47 Soldier (checked 2026-09-23). Pico is id 309, outside this space.
_CHAR_NAMES_FALLBACK = {
    0: "Lest/Frey", 1: "Vishnal", 2: "Clorica", 3: "Volkanon", 4: "Forte", 5: "Kiel",
    6: "Bado", 7: "Margaret", 8: "Dylas", 9: "Arthur", 10: "Porcoline", 11: "Xiao Pai",
    12: "Lin Fa", 13: "Amber", 14: "Illuminata", 15: "Doug", 16: "Blossom", 17: "Dolce",
    18: "Jones", 19: "Nancy", 20: "Leon", 21: "Ventuswill", 22: "Son", 23: "Daughter",
    24: "Barrett", 25: "Raven", 26: "Mistress Trupin",
}


def _load_char_names():
    try:
        import json
        from .refdata import refdata_path
        with open(refdata_path("char_names.json"), encoding="utf-8") as f:
            d = {int(k): v for k, v in json.load(f).items() if 0 < int(k) < 48 and v}
        d[0] = "Lest/Frey"
        return d if len(d) >= 27 else dict(_CHAR_NAMES_FALLBACK)
    except Exception:
        return dict(_CHAR_NAMES_FALLBACK)


CHAR_NAMES = _load_char_names()

_APPLY0 = ("NpcAi_ApplyMovement (RF4S.exe+0x1F60C0) with bank slot 0: the Script VM "
           "runs the scene at event_id in the global bank")
_APPLY1 = ("NpcAi_ApplyMovement (RF4S.exe+0x1F60C0) with bank slot 1: the Script VM "
           "runs the scene at event_id in the loaded primary bank")
_KICK2 = ("direct NpcAi_StepScriptActionStateMachine kick (state +112 = 4) with bank "
          "slot 2: the Script VM runs the scene at event_id in the map's tail bank")
_COLLECT = ("appended as a 24-byte record to g_npcActionEntryArray_12x24 (max 12); "
            "NpcActionEntry_ResolveActiveForPlayerPos (RF4S.exe+0x2205C0) later picks "
            "the record whose step matches, whose box contains the player and whose "
            "required NPCs are present, and Trigger_PollPlayerProximityAndQueueEvent "
            "(RF4S.exe+0x1F0920) queues it as a game event")

# ---------------------------------------------------------------------------
# The catalogue.
#   keys[].index : int, or "k+" for a key spec that applies to every index >= k
#   select       : "first" | "last" | "all" | "first_exact_else_last_wildcard"
#   confidence   : "verified" (matcher + key source read in the exe, corpus agrees)
#                  "likely"   (mechanics verified, meaning of the key inferred)
#                  "unknown"  (no reader located / meaning unresolved)
# ---------------------------------------------------------------------------
ENTRY_TYPES = {
    0: {
        "name": "MapTalk",
        "summary": "Talk line chosen by the map the player is on (guest banks 24-47 and the villagers' second bank 224+id).",
        "bank": "primary: 224+canonical id (villagers, ResolveVillagerBehavior step 5) or the guest's own bank",
        "keys": [
            {"index": "0+", "name": "map", "meaning": "map id (tag 4) compared with the player's current map (actor field_54; ids < 64 use id & ~3)", "wildcard": True},
        ],
        "select": "first_exact_else_last_wildcard",
        "consumer": _APPLY1,
        "matcher": "Npc_LookupActionEntryByPlayerHitFilter (RF4S.exe+0x220DA0) driven by sub_7FF7BEB10CD0 (RF4S.exe+0x220CD0)",
        "confidence": "verified",
        "notes": "The IDB name says 'hit filter' but field_54 is the current map id: the same '& ~3 below 0x40' canonicalisation Npc_OnTalkAction_QueueDialogueCascade applies to map ids, and the corpus keys are maps (64 Castle: Dragon Room, 65 Your Room, 66 Butler's Room ...). A -1 entry writes the event id but the scan continues, so an exact match later in the list overrides it.",
    },
    2: {
        "name": "ActorKindScene",
        "summary": "Scene keyed by an actor kind id (map objects / special actors); probed in the tail bank, then the primary bank, then the global bank.",
        "bank": "tail (slot 2), primary (slot 1), global (slot 0) - probed in that order by NpcAi_ResolveMonsterBehavior",
        "keys": [
            {"index": "0+", "name": "actor_kind", "meaning": "actor kind id (actor +8) of the thing interacted with, or the event descriptor's target word (+6) in NpcAi_TickEventMovementOrFinalize", "wildcard": False},
        ],
        "select": "first",
        "consumer": "NpcAi_ApplyMovement with the slot that matched (NpcAi_ResolveMonsterBehavior RF4S.exe+0x1F9610 returns the slot in *a3); NpcAi_TickEventMovementOrFinalize (RF4S.exe+0x1F3070) kicks slot 2 directly",
        "matcher": "NpcAi_FindActionEntryByTargetForType2 (RF4S.exe+0x221EC0)",
        "confidence": "likely",
        "notes": "Called for actors with kind >= 0xFE or status-blocked monsters (NpcAi_TickOne RF4S.exe+0x1F6930); kind 400 additionally routes through a type-27 lookup in bank 210. Corpus keys 100..2435 (global bank: 2373..2388) are not map or NPC ids; the exact id space is the actor '+8' kind field.",
    },
    3: {
        "name": "PlayerRegionTrigger",
        "summary": "Map scene fired when the player stands inside a rectangle (optionally gated by an em condition).",
        "bank": "tail (slot 2)",
        "keys": [
            {"index": 0, "name": "x1", "meaning": "box corner x (world units = Q12 >> 12); corners are min/max-normalised", "wildcard": False},
            {"index": 1, "name": "y1", "meaning": "box corner y", "wildcard": False},
            {"index": 2, "name": "x2", "meaning": "box corner x", "wildcard": False},
            {"index": 3, "name": "y2", "meaning": "box corner y", "wildcard": False},
            {"index": 4, "name": "condition", "meaning": "em.bin condition id evaluated by CondScript_EvalNamedConditionA; -1 = unconditional", "wildcard": True},
        ],
        "select": "first",
        "consumer": "Trigger_PollPlayerProximityAndQueueEvent (RF4S.exe+0x1F0920) queues game-event kind 14 with the event id; g_lastDispatchedActionEventId blocks re-firing the same scene while the player stays inside",
        "matcher": "NpcAi_FindActionEntryOfType3InBoundingBox (RF4S.exe+0x2203E0)",
        "confidence": "verified",
        "notes": "Not a caller of Npc_FindNextActionEntryOfType: it walks the list through Npc_ReadActionEntrySubBytes/Npc_ReadActionEntryId with an iter-state {bank, 3, idx}.",
    },
    4: {
        "name": "ThrowFallback",
        "summary": "Generic reaction to an item thrown at the NPC when nothing more specific matched.",
        "bank": "primary: canonical char id of the NPC",
        "keys": [
            {"index": "0+", "name": "item", "meaning": "thrown item id (slot word & 0x7FF); every shipped entry is -1", "wildcard": True},
        ],
        "select": "first",
        "consumer": "NpcAi_OnReceivedThrownItem_AdvanceProgressAndDispatchReaction (RF4S.exe+0x1F1730): Item_UseOnActor + stack decrement, then " + _APPLY1,
        "matcher": "Event_QueryThrowReactionFallback (RF4S.exe+0x221120)",
        "confidence": "verified",
        "notes": "",
    },
    5: {
        "name": "ThrowAtEventActor",
        "summary": "Item thrown at a calendar-event actor on a map (crop offerings); consumes the stack.",
        "bank": "tail (slot 2) first, then the sub-event bank in slot 1 (NpcAi_CheckThrownItemFallbackCondition RF4S.exe+0x1FEA40 loads REG_SUBEV_NOW)",
        "keys": [
            {"index": 0, "name": "event_kind", "meaning": "word 0 of the target's g_calendarEventMng record (100/101 in the corpus); 0 when the target is not a calendar-event actor", "wildcard": False},
            {"index": 1, "name": "consume", "meaning": "how many units of the thrown stack to consume (-1 = 9, 0 = none)", "wildcard": False},
            {"index": "2+", "name": "item", "meaning": "thrown item id; -1 matches any item but keeps scanning for an exact match", "wildcard": True},
        ],
        "select": "first",
        "consumer": "Player_DecrementItemStackAfterUse x consume + Quest_OnNonGiftItemConsumed, then NpcAi_ApplyMovement with the slot that matched (2 or 1)",
        "matcher": "Event_MatchThrownItemActionEntryAndConsume (RF4S.exe+0x222600) via Event_QueryByItemThrowAndPriority (RF4S.exe+0x222510)",
        "confidence": "likely",
        "notes": "Corpus: 5 tail banks (Sechs Territory, Rune Prana), items 2..47 are crops (2 King Cabbage .. 47 Golden Tyrant Turnip). The meaning of record word 0 (100/101) was not resolved.",
    },
    6: {
        "name": "MapSceneAll",
        "summary": "Map-bank scene with no keys; every type-6 entry is walked and the last one runs.",
        "bank": "tail (slot 2)",
        "keys": [],
        "select": "last",
        "consumer": _KICK2,
        "matcher": "Scene_TickDispatchType6NpcEvent (RF4S.exe+0x1F2C00)",
        "confidence": "verified",
        "notes": "Handler 23 of the game-event handler table (RF4S.exe+0x4DB688); NpcAi_PerFrameTick queues kind 23 on the every-morning flag.",
    },
    7: {
        "name": "MapEnterScene",
        "summary": "Map-bank scene run on map entry; no keys, last entry wins.",
        "bank": "tail (slot 2)",
        "keys": [],
        "select": "last",
        "consumer": _KICK2,
        "matcher": "Npc_TickScriptActionDispatch (RF4S.exe+0x1EEE10), wrapper at RF4S.exe+0x1F2E50 = handler 24",
        "confidence": "verified",
        "notes": "Npc_OnTalkAction_QueueDialogueCascade (RF4S.exe+0x1EE7C0) loads the tail bank of the entered map and queues event kind 24 with the map id.",
    },
    8: {
        "name": "GlobalScene8",
        "summary": "Global-bank scene, no keys, first entry.",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "first",
        "consumer": _APPLY0 + " on the scene context (flag 1 = step immediately)",
        "matcher": "NpcAi_ProbeMovementFromType8ActionOnSceneContext (RF4S.exe+0x1F3CC0), handler 11",
        "confidence": "verified",
        "notes": "What queues handler 11 was not traced; single entry at PC 31360.",
    },
    9: {
        "name": "FishingCatch",
        "summary": "Global scene shown after a fish is caught; result buffer gets item id / catch info / new-catch flag.",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "last",
        "consumer": _APPLY0 + "; Fishing_ProcessCatch writes +64 item id, +68 catch info, +72 new-catch, +76/+80/+84 size flags",
        "matcher": "Fishing_ProcessCatch (RF4S.exe+0x1F39F0), handler 12",
        "confidence": "verified",
        "notes": "",
    },
    10: {
        "name": "GlobalScene10",
        "summary": "Global-bank scene, no keys, last entry.",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "last",
        "consumer": _APPLY0,
        "matcher": "NpcAi_ProbeMovementFromType10Action (RF4S.exe+0x1F7160), handler 8",
        "confidence": "verified",
        "notes": "Purpose not traced (single entry at PC 33088).",
    },
    11: {
        "name": "Unknown11",
        "summary": "Global-bank entry with no keys (PC 33106); no reader found.",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "unknown",
        "consumer": "unknown",
        "matcher": "none found: no caller of Npc_FindNextActionEntryOfType / Npc_ReadActionEntrySubBytes / Npc_ReadActionEntryId walks type 11, and no inline reader of table offset 0x2E was found in the NPC-AI ranges",
        "confidence": "unknown",
        "notes": "",
    },
    13: {
        "name": "MonsterInteract",
        "summary": "Global scene for interacting with an ordinary monster/pet actor (kind 0x30..0xFD, not status-blocked).",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "first",
        "consumer": _APPLY0 + " (NpcAi_TickOne clears actor flags 0x24 first)",
        "matcher": "NpcAi_TickOne (RF4S.exe+0x1F6930), handler 3",
        "confidence": "likely",
        "notes": "Gated by actor +84 equality with a second actor (register lost in decompile); single entry at PC 31924.",
    },
    15: {
        "name": "FollowupByPrevId",
        "summary": "Chained scene after a cutscene fade: keyed by the finished scene's logical id.",
        "bank": "slot 1 (post-event modes 1/2) or slot 2 (mode 0)",
        "keys": [
            {"index": "0+", "name": "prev_event", "meaning": "logical id of the scene that just ended (npc_event_ctx u16 +66, cleared after use)", "wildcard": False},
        ],
        "select": "first",
        "consumer": "mode 0: " + _KICK2 + "; modes 1/2: " + _APPLY1 + " (mode 1 also flags both companions)",
        "matcher": "Event_QueryFollowupByPrevId (RF4S.exe+0x220EF0) from NpcAi_OnPostCutsceneFade_DispatchFollowupEvent (RF4S.exe+0x1F31F0), handler 27",
        "confidence": "verified",
        "notes": "Corpus keys 100..3900 (1000..1005, 1300 ...) form their own id space; who writes ctx+66 was not traced (probably the scene script).",
    },
    16: {
        "name": "RevivalReaction",
        "summary": "Map scene after the player is revived (KO); last entry wins, companions are teleported.",
        "bank": "tail (slot 2)",
        "keys": [],
        "select": "last",
        "consumer": _KICK2 + "; then both companion actors are moved to the respawn spot",
        "matcher": "OnRevival_DispatchNpcReactionAndTeleportCompanions (RF4S.exe+0x1F37E0), handler 2",
        "confidence": "verified",
        "notes": "Only tail bank 132 has one.",
    },
    17: {
        "name": "RequestedScene",
        "summary": "Map scene selected by a queued request: (key, em condition) pairs, first passing pair wins.",
        "bank": "tail (slot 2)",
        "keys": [
            {"index": "0+", "name": "pair", "meaning": "even index k: request key compared with descriptor word[1]; odd index k+1: em.bin condition for that key (-1 = always). A -1 key is a default that keeps scanning the entry for an exact key", "wildcard": True},
        ],
        "select": "first",
        "consumer": _KICK2 + "; NpcAi_BeginScriptedEventFromRequestDescriptor stores descriptor words 3/2 into ctx+112/+114",
        "matcher": "NpcAi_ResolveActionEntryType17 (RF4S.exe+0x222190) from NpcAi_BeginScriptedEventFromRequestDescriptor (RF4S.exe+0x1F2040), handler 0",
        "confidence": "likely",
        "notes": "Corpus keys 104..249 (tag 1) are not map ids (checked against map_names); they are probably actor/boss kind ids raised by whatever queues handler 0 - not traced.",
    },
    19: {
        "name": "AbsentTalk",
        "summary": "Villager line used when the NPC is not in the current area (first entry).",
        "bank": "primary: canonical char id",
        "keys": [],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "NpcAi_ResolveVillagerBehavior (RF4S.exe+0x1F7E00), direct Npc_FindNextActionEntryOfType call at RF4S.exe+0x1F8250",
        "confidence": "likely",
        "notes": "Taken when !Npc_IsInCurrentArea(id); also grants the daily first-talk bonus.",
    },
    20: {
        "name": "DefaultTalk",
        "summary": "Villager fallback line (first entry), used by guests with the 0x200 actor flag and by the busy/quest fallbacks.",
        "bank": "primary: canonical char id",
        "keys": [],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "Npc_FindNextActionOperand_FromSubList80_Type20 (RF4S.exe+0x221050) from NpcAi_ResolveVillagerBehavior",
        "confidence": "likely",
        "notes": "",
    },
    21: {
        "name": "FollowPlayer",
        "summary": "Companion 'follow the player' scene; all entries walked, last wins.",
        "bank": "primary: canonical id of the descriptor's char id (word +2)",
        "keys": [],
        "select": "last",
        "consumer": _APPLY1 + " (mode 1, step immediately)",
        "matcher": "NpcAi_TryApplyFollowMovementIfNoActiveBlockers (RF4S.exe+0x1F2190), handler 1",
        "confidence": "verified",
        "notes": "Skipped while a kill aggregate or calendar event has state bit 0x800, while the player is being thrown, or at story flag 248.",
    },
    22: {
        "name": "DailyGreeting",
        "summary": "First-talk-of-the-day greeting chosen by time of day (0 = 06-09h, 1 = 10-17h, 2 = otherwise).",
        "bank": "primary: 224 + canonical char id",
        "keys": [
            {"index": "0+", "name": "timeslot", "meaning": "0 morning (calendar hour 6..9), 1 daytime (10..17), 2 evening/night", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + "; Npc_SetHiddenFlag(id) marks the greeting as done and scene flag 0x200 is set",
        "matcher": "Npc_FindActionOperand_FromSubList88_Type22_WithSubBytePredicate (RF4S.exe+0x221290) from NpcAi_ResolveVillagerBehavior step 0",
        "confidence": "verified",
        "notes": "Every villager second bank (225..247) has exactly the keys 0, 1, 2.",
    },
    23: {
        "name": "FestivalTalk0",
        "summary": "Festival line for festival phase 0 (type = 23 + REG_FES_STATUS); key = festival id.",
        "bank": "primary: the NPC's own bank (slot 1) - or slot 2 (map bank) from NpcAi_PerFrameTick",
        "keys": [
            {"index": "0+", "name": "festival", "meaning": "festival id: REG_FESTA (5-bit) when a festival is pending, else Calendar_LookupEventBySeasonAndDay for tomorrow after 06:00", "wildcard": False},
        ],
        "select": "first",
        "consumer": _APPLY1 + " (NpcAi_PerFrameTick variant: slot 2 with key = byte 5 of qword_7FF7BF72CBB0)",
        "matcher": "NpcActionEntry_ResolveForFestivalPhase (RF4S.exe+0x221400) from Npc_DispatchPendingOrDateGatedEvent (RF4S.exe+0x1F94E0)",
        "confidence": "verified",
        "notes": "Phase comes from GF_REG_FES_STATUS (2 bits) or scene byte +533 >> 4 when its bit 3 is set.",
    },
    27: {
        "name": "SubEventReaction",
        "summary": "Sub-event / quest reaction: entry matches (priority, char id); 0 in the char list means the spouse.",
        "bank": "primary: sub-event bank (REG_SUBEV_NOW, Npc_GetCurrentQuestId or 210), or the global bank for the scripted-attack variant",
        "keys": [
            {"index": 0, "name": "priority", "meaning": "reaction priority/kind 0..3 (Quest_GetGeneralReceivingPriorityByEntry, 2 = gift priority, reward event id, 3 = SUBEV_AFTER/QUEST_AFTER); -1 = matches regardless of the char list", "wildcard": True},
            {"index": "1+", "name": "npc", "meaning": "char id list (tag 3); 0 is replaced by REG_WIFE_ID when the caller passes a non-zero bank index; 23 (Daughter) is remapped to 22", "wildcard": False},
        ],
        "select": "first",
        "consumer": _APPLY1 + "; the attack variant plays SFX 0x100226D and Combat_ApplyAttackEntry(player, 0xAC)",
        "matcher": "NpcActionEntry_ResolveByKeyPairWithWifeId (RF4S.exe+0x2216C0) via Event_QueryGiftReactionByPriority (RF4S.exe+0x2215D0), Subev_ResolveActiveForNpcReaction (RF4S.exe+0x1FA750), NpcAi_ResolveMonsterBehavior (bank 210, key2 = 210) and NpcAi_ProbeAndTriggerScriptedAttackOnPlayerType27 (RF4S.exe+0x1F7270, global bank, key1 = descriptor word +2, key2 = 0)",
        "confidence": "verified",
        "notes": "Match rule: (sub0 == priority and any sub_i == char) or sub0 == -1. Corpus: 1034 entries in 152 sub-event banks (48..) plus 2 in the global bank.",
    },
    28: {
        "name": "SubEventNpcLine",
        "summary": "Sub-event line keyed by the talking NPC's canonical char id.",
        "bank": "primary: sub-event bank (loaded by NpcAi_CheckThrownItemFallbackCondition = REG_SUBEV_NOW)",
        "keys": [
            {"index": 0, "name": "npc", "meaning": "canonical char id of the NPC (tag 3)", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + " (sets g_sceneAuxControlFlags 0x1000)",
        "matcher": "Npc_PredicateMatchSubBytesAndCommitEventId (RF4S.exe+0x2202B0) via Event_QueryByKindNpcAndStoryChapter(kind 0x1C) (RF4S.exe+0x222AB0), call site RF4S.exe+0x1F8618",
        "confidence": "verified",
        "notes": "Expected key list is [char id, 0]; entries have one key.",
    },
    30: {
        "name": "StoryProgressTalk",
        "summary": "Line gated by a main-scenario range [lo, hi]; fires once per range (friendship word +6 remembers the last hi).",
        "bank": "primary: 224 + canonical char id",
        "keys": [
            {"index": 0, "name": "chapter_lo", "meaning": "lowest REG_MAIN_SCENARIO value (9-bit) that matches", "wildcard": False},
            {"index": 1, "name": "chapter_hi", "meaning": "highest matching value (0 = same as lo); also must be >= the NPC's last fired hi", "wildcard": False},
        ],
        "select": "first",
        "consumer": _APPLY1 + "; sets friendship flag 0x10000000 and stores hi into the entry's word +6",
        "matcher": "NpcAi_FindActionEntryOfType30GatedByFlagAndNpcStat (RF4S.exe+0x221820)",
        "confidence": "verified",
        "notes": "",
    },
    31: {
        "name": "DateTalk",
        "summary": "Line for a calendar date: absolute day-of-year, or n-1 days before a festival.",
        "bank": "primary: canonical char id",
        "keys": [
            {"index": "0+", "name": "date", "meaning": "value <= 120: day-of-year = day + 30*season compared with today; value > 120: (n << 8) | festival_id means (n-1) days before that festival (dates from archive 16340, with the >90/<=30 year-wrap rule)", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "sub_7FF7BEB11D20 (RF4S.exe+0x221D20) from NpcAi_ResolveVillagerBehavior step 10 (call RF4S.exe+0x1F901E)",
        "confidence": "verified",
        "notes": "Corpus: 29/59/89/116 = season ends, 257.. = festival day, 513.. = the day before.",
    },
    32: {
        "name": "TalkLineTier1",
        "summary": "Regular talk line, relationship tier 1 (acquaintance); key = per-NPC line index.",
        "bank": "primary: 224 + canonical char id (NpcAi_ResolveVillagerBehavior reloads slot 1 with v7 + 224 at RF4S.exe+0x1F933B right before the lookup)",
        "keys": [
            {"index": "0+", "name": "line", "meaning": "line index = (Npc_ComputeRelationshipTier key) & 0x7F, i.e. the NPC's actor byte +16 talk counter", "wildcard": False},
        ],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "Npc_FindTalkLineEventByTierKey (RF4S.exe+0x222020); tier from Npc_ComputeRelationshipTier (RF4S.exe+0x228CE0): type = 32 + tier - 1",
        "confidence": "verified",
        "notes": "Tier 2 = friendship level > 3 and stage bits >= 0x100, tier 3 = flag 0x400000 (dating), tier 4 = REG_WIFE_ID == id; key 640 (tier 5) probes type 36 for spouses (absent from the corpus).",
    },
    37: {
        "name": "QuestProgressReaction",
        "summary": "Global scene when quest progress hits a milestone (1) or completes (2).",
        "bank": "global (slot 0)",
        "keys": [
            {"index": "0+", "name": "milestone", "meaning": "1 = progress milestone (count 1 or a multiple of 5), 2 = completed (Quest_LookupRewardEventIdByTemplateId)", "wildcard": False},
        ],
        "select": "first",
        "consumer": _APPLY0 + "; result buffer +64 template id, +68 progress, +72 remaining",
        "matcher": "NpcAi_AdvanceQuestProgressAndScheduleReaction (RF4S.exe+0x1F23F0), handler 14",
        "confidence": "verified",
        "notes": "",
    },
    38: {
        "name": "ItemReceiptReaction",
        "summary": "Quest/general item-receipt reaction keyed by the receiving NPC's char id.",
        "bank": "primary: quest bank (Npc_GetCurrentQuestId) or 210 when none",
        "keys": [
            {"index": "0+", "name": "npc", "meaning": "char id of the NPC that received the item (tag 3)", "wildcard": True},
        ],
        "select": "first",
        "consumer": "NpcAi_OnReceivedThrownItem: consumes the gift units, then " + _APPLY1,
        "matcher": "Event_QueryGeneralReactionByPriority (RF4S.exe+0x2223A0)",
        "confidence": "verified",
        "notes": "Used when the receiving priority is not 2 (priority 2 goes to type 27). Bank 210 holds one entry per villager 1..23.",
    },
    39: {
        "name": "SubEventMapScene",
        "summary": "Sub-event scene triggered on a map (key = map id).",
        "bank": "primary: REG_SUBEV_NOW (or REG_SUBEV_RSV when DATE_MAP is clear)",
        "keys": [
            {"index": 0, "name": "map", "meaning": "map id (tag 4) from the event descriptor word +2", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + " (mode 1, step immediately)",
        "matcher": "Npc_PredicateMatchSubBytesAndCommitEventId via Event_QueryByKindNpcAndStoryChapter(kind 0x27) from NpcAi_TryApplyMovementFromStoryFlagAndEventQuery (RF4S.exe+0x1F2940), handler 19",
        "confidence": "verified",
        "notes": "Descriptor word +6 must be 0.",
    },
    40: {
        "name": "SubEventMapSceneB",
        "summary": "Sub-event scene on map entry (key = map id); sets ctx flag 0x400 before running.",
        "bank": "primary: REG_SUBEV_NOW",
        "keys": [
            {"index": 0, "name": "map", "meaning": "map id (tag 4) from the event descriptor word +2 (Npc_OnTalkAction_QueueDialogueCascade queues kind 20 with the entered map)", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + " (mode 1, step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x28) from NpcAi_ProbeMovementFromEventKind40_SetBit400_GatedByRequestor (RF4S.exe+0x1F3430), handler 20",
        "confidence": "verified",
        "notes": "",
    },
    43: {
        "name": "SummerVariantTalk",
        "summary": "Villager line chosen by a rotating variant (value % 3) in summer while the actor's word +488 == 2.",
        "bank": "primary: canonical char id",
        "keys": [
            {"index": 0, "name": "variant", "meaning": "(dword +12 of the struct at g_calendarTask+176) % 3", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "Npc_PredicateMatchSubBytesAndCommitEventId at RF4S.exe+0x1F911E (NpcAi_ResolveVillagerBehavior step 11); gate sub_7FF7BEA8C2F0 (RF4S.exe+0x19C2F0) == 1 (calendar season) and actor +488 == 2",
        "confidence": "likely",
        "notes": "Mechanics verified; what actor +488 == 2 and the +176 struct mean was not resolved.",
    },
    44: {
        "name": "ConditionTalk44",
        "summary": "Villager line selected by em.bin conditions: first entry with a passing condition (or -1).",
        "bank": "primary: canonical char id",
        "keys": [
            {"index": "0+", "name": "condition", "meaning": "em.bin named condition id (CondScript_EvalNamedConditionA); -1 = default", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "NpcAi_ResolveActionEntryType44 (RF4S.exe+0x221A20), NpcAi_ResolveVillagerBehavior step 14",
        "confidence": "verified",
        "notes": "",
    },
    45: {
        "name": "ConditionTalk45",
        "summary": "Condition-selected line/scene (em.bin conditions), also used for NPCs taking part in the active event.",
        "bank": "primary: canonical char id (or 224+id for the villager second banks that also carry it)",
        "keys": [
            {"index": "0+", "name": "condition", "meaning": "em.bin named condition id; the corpus uses -1 as a default although the matcher has no explicit -1 test (CondScript_EvalNamedConditionA(-1) behaviour not checked)", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "NpcAi_ResolveActionEntryType45 (RF4S.exe+0x221BB0) from NpcAi_TickOne (event participants) and NpcAi_ResolveVillagerBehavior step 2",
        "confidence": "verified",
        "notes": "",
    },
    46: {
        "name": "InteractionScene46",
        "summary": "Key-less scene run by NpcAi_PerFrameTick for the current interaction NPC when scene control bit 0x100000/0x200000 is set (bit 21 clear -> 46).",
        "bank": "primary: canonical id of g_currentInteractionNpc",
        "keys": [],
        "select": "first",
        "consumer": _APPLY1 + " on the scene context (mode 1, step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 46 + ((g_sceneControlFlags >> 21) & 1)) at RF4S.exe+0x1F08CA in NpcAi_PerFrameTick",
        "confidence": "likely",
        "notes": "Size-0 entries commit unconditionally in Npc_PredicateMatchSubBytesAndCommitEventId. The meaning of control bits 0x100000/0x200000 was not resolved.",
    },
    48: {
        "name": "GlobalScene48",
        "summary": "Global-bank scene, no keys, last entry.",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "last",
        "consumer": _APPLY0 + " (step immediately)",
        "matcher": "NpcAi_ProbeAndApplyMovementFromType48Action (RF4S.exe+0x1F7050), handler 7",
        "confidence": "verified",
        "notes": "Purpose not traced (single entry at PC 34020).",
    },
    49: {
        "name": "EatFood",
        "summary": "Global scene played when the player eats; result buffer gets item id and recipe category.",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "last",
        "consumer": _APPLY0 + "; +64 = item id, +68 = recipe category (archives 14826..14847)",
        "matcher": "Player_OnEatFood_LoadAnimAndBindRecipeCategory (RF4S.exe+0x1F6C10), handler 5",
        "confidence": "verified",
        "notes": "",
    },
    50: {
        "name": "ThrowSpecialItem",
        "summary": "Reaction to a specific thrown item (condition, consume count, item list); Engagement Ring in the shipped data.",
        "bank": "primary: canonical char id",
        "keys": [
            {"index": 0, "name": "condition", "meaning": "em.bin condition id; -1 = none", "wildcard": True},
            {"index": 1, "name": "consume", "meaning": "units to consume when the caller asks for consumption (a5 != 0); -1 = the numeric value of EMFE_EV_KOHAKU_LIVE", "wildcard": True},
            {"index": "2+", "name": "item", "meaning": "thrown item id (slot word & 0x7FF)", "wildcard": True},
        ],
        "select": "first",
        "consumer": "NpcAi_OnReceivedThrownItem: " + _APPLY1 + "; Throw_DispatchToNpcWithQuestGiftCheck (RF4S.exe+0x1F0E90) uses the same query with a5 = 0 as an 'interesting item' probe",
        "matcher": "Npc_ResolveThrownItemActionEntry (RF4S.exe+0x2228A0) via Event_QueryThrowReactionInteresting (RF4S.exe+0x2227B0)",
        "confidence": "verified",
        "notes": "Corpus: item 676 = Engagement Ring in the guest banks 24..27, 34, 41.",
    },
    51: {
        "name": "LongAbsenceTalk",
        "summary": "Line after a long time without talking; key = 1 if the NPC is the spouse.",
        "bank": "primary: canonical char id",
        "keys": [
            {"index": 0, "name": "is_spouse", "meaning": "1 when REG_WIFE_ID == canonical char id, else 0", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + "; falls back to the tier talk line when nothing matches",
        "matcher": "Npc_PredicateMatchSubBytesAndCommitEventId at RF4S.exe+0x1F874E (NpcAi_ResolveVillagerBehavior, Npc_ConsumeNoTalkStreakAndQueryLongAbsence gate)",
        "confidence": "verified",
        "notes": "",
    },
    53: {
        "name": "GlobalRequestKind",
        "summary": "Global scene keyed by a small request code (1..27) from the event descriptor byte +2.",
        "bank": "global (slot 0)",
        "keys": [
            {"index": 0, "name": "code", "meaning": "descriptor byte +2 (1..27 in the corpus); meaning of the codes not resolved", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY0 + " (step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x35) from NpcAi_ProbeMovementFromEventKind53 (RF4S.exe+0x1F73A0), handler 10",
        "confidence": "likely",
        "notes": "",
    },
    54: {
        "name": "WalkToTarget",
        "summary": "Global scene that walks the NPC to encoded tile coordinates (ctx bytes +323..+326); last entry.",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "last",
        "consumer": _APPLY0 + "; result buffer +64/+68 = tile + 445/451, +72/+76 from ctx +326/+325",
        "matcher": "NpcAi_TickWalkToActionType54Targets (RF4S.exe+0x1F2780), handler 15",
        "confidence": "verified",
        "notes": "",
    },
    56: {
        "name": "SpecialEventKind56",
        "summary": "Story-bank scene of dynamic kind 56 + descriptor byte, keyed by the context byte +329.",
        "bank": "primary: story bank 211+ (NpcAi_CheckSpecialEventCondition)",
        "keys": [
            {"index": 0, "name": "ctx329", "meaning": "npc_event_ctx byte +329 (0 in the corpus)", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + " (mode 1, step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 56 + descriptor byte +2) from NpcAi_ProbeMovementFromEventKindByPredicate (RF4S.exe+0x1F73F0), handler 17",
        "confidence": "likely",
        "notes": "Only story bank 211 has types 56 and 57 (one entry each).",
    },
    60: {
        "name": "DailyTopicTalk",
        "summary": "Villager line about today's randomly rolled topic (1..10); marked done per topic.",
        "bank": "primary: 224 + canonical char id",
        "keys": [
            {"index": 0, "name": "topic", "meaning": "low byte of qword_7FF7BF78B308, rolled daily by Day_UpdateNpcDailyFlags (RF4S.exe+0x227AE0); topic 10 additionally needs EMFE_SYELZA_READY", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + "; done-bit (1 << (topic-1)) set in the same qword",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x3C) at RF4S.exe+0x1F929D (NpcAi_ResolveVillagerBehavior step 13)",
        "confidence": "likely",
        "notes": "Each villager second bank has the keys 1..10.",
    },
    62: {
        "name": "SubEventDefault",
        "summary": "Key-less scene of the active sub-event bank.",
        "bank": "primary: REG_SUBEV_NOW",
        "keys": [],
        "select": "first",
        "consumer": _APPLY1 + " (mode 1, step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x3E) from NpcAi_ProbeMovementFromEventKind62_GatedByCurrentRequestor (RF4S.exe+0x1F2B50), handler 22",
        "confidence": "verified",
        "notes": "",
    },
    63: {
        "name": "SubEventParticipantsScene",
        "summary": "Sub-event scene collected on map entry: step, map, and the NPCs that must be present (record kind 3, no box).",
        "bank": "primary: sub-event bank (REG_SUBEV_NOW / REG_SUBEV_RSV)",
        "keys": [
            {"index": 0, "name": "step", "meaning": "sub-event step: collected when REG_SUBEV_U8A <= step, resolved when == REG_SUBEV_U8A (or -1)", "wildcard": True},
            {"index": 1, "name": "map", "meaning": "map id (tag 4) == the entered map (canonical)", "wildcard": False},
            {"index": "2+", "name": "npc", "meaning": "required NPC char id (tag 3) -> bit in the record's condition mask; -1 = REG_WIFE_ID; 16582/16638 = read the NPC id from that packed game flag", "wildcard": True},
        ],
        "select": "all",
        "consumer": _COLLECT,
        "matcher": "NpcActionEntry_ParseAndAppendKind3WithWifeId (RF4S.exe+0x222F90) from sub_7FF7BEB10A90 (RF4S.exe+0x220A90)",
        "confidence": "likely",
        "notes": "Kinds 1..3 require every masked NPC (bits 1..23) to pass Npc_IsAtScheduledSpotAndAvailable. Collection order 65, 66, 67, 63, 64 fixes the priority inside the 12-record array.",
    },
    65: {
        "name": "SubEventRegionScene",
        "summary": "Sub-event scene collected on map entry with a trigger box and required NPCs (record kind 1).",
        "bank": "primary: sub-event bank (REG_SUBEV_NOW / REG_SUBEV_RSV)",
        "keys": [
            {"index": 0, "name": "map", "meaning": "map id (tag 4) == the entered map (canonical)", "wildcard": False},
            {"index": 1, "name": "step", "meaning": "sub-event step stored at record +0; must equal REG_SUBEV_U8A (or -1) when resolved", "wildcard": True},
            {"index": 2, "name": "x1", "meaning": "trigger box x1 (player world >> 12)", "wildcard": False},
            {"index": 3, "name": "y1", "meaning": "trigger box y1", "wildcard": False},
            {"index": 4, "name": "x2", "meaning": "trigger box x2", "wildcard": False},
            {"index": 5, "name": "y2", "meaning": "trigger box y2", "wildcard": False},
            {"index": "6+", "name": "npc", "meaning": "required NPC char id (tag 3); 16582/16638 = read the id from that packed game flag", "wildcard": False},
        ],
        "select": "all",
        "consumer": _COLLECT,
        "matcher": "Npc_DialogueEntryCollect_PushIfTriggerMatchesAndScanConditionBits (RF4S.exe+0x220870) from sub_7FF7BEB10A90 (RF4S.exe+0x220A90)",
        "confidence": "likely",
        "notes": "The IDB comment calls sub 0 a 'trigger kind'; it is the map id (tag 4, values 24 Field, 28 Airship Way, 143 Ste-Coquille Manor 2F ...).",
    },
    67: {
        "name": "SubEventRegionSceneB",
        "summary": "Sub-event scene collected on map entry with step gate, em condition, trigger box and required NPCs (record kind 2).",
        "bank": "primary: sub-event bank",
        "keys": [
            {"index": 0, "name": "map", "meaning": "map id (tag 4) == the entered map", "wildcard": False},
            {"index": 1, "name": "step", "meaning": "sub-event step: collected when REG_SUBEV_U8A <= step, resolved when == REG_SUBEV_U8A", "wildcard": True},
            {"index": 2, "name": "condition", "meaning": "em.bin condition id stored at record +16 (0 = none), evaluated when resolved", "wildcard": False},
            {"index": 3, "name": "x1", "meaning": "trigger box x1", "wildcard": False},
            {"index": 4, "name": "y1", "meaning": "trigger box y1", "wildcard": False},
            {"index": 5, "name": "x2", "meaning": "trigger box x2", "wildcard": False},
            {"index": 6, "name": "y2", "meaning": "trigger box y2", "wildcard": False},
            {"index": "7+", "name": "npc", "meaning": "required NPC char id (tag 3); 16582/16638 = packed game flag", "wildcard": False},
        ],
        "select": "all",
        "consumer": _COLLECT,
        "matcher": "NpcActionEntry_ParseAndAppendIfSubevActive (RF4S.exe+0x222D30) from sub_7FF7BEB10A90",
        "confidence": "likely",
        "notes": "",
    },
    68: {
        "name": "FlagGatedAutoScene",
        "summary": "Auto-triggered scene: on a map (or any), when a packed game flag has a required value.",
        "bank": "primary (story bank 211+ or REG_SUBEV_NOW) first, then tail (slot 2)",
        "keys": [
            {"index": 0, "name": "map", "meaning": "map id (tag 4) compared with the player's map (actor field_54); 0 = any map", "wildcard": False},
            {"index": 1, "name": "flag", "meaning": "packed game-flag reference (tag 2) read with GameFlags_ReadField", "wildcard": False},
            {"index": 2, "name": "value", "meaning": "required value of that flag field", "wildcard": False},
        ],
        "select": "first",
        "consumer": "primary hit: " + _APPLY1 + "; tail hit: " + _KICK2,
        "matcher": "Event_QueryByNpcAndPriority (RF4S.exe+0x222BB0) from NpcAi_TickEventPriorityCascade (RF4S.exe+0x1F2E60), handler 25",
        "confidence": "verified",
        "notes": "Not a caller of Npc_FindNextActionEntryOfType (walks through Npc_ReadActionEntrySubBytes). Corpus flags 29122/32768/400 etc., maps 160 Airship, 272 Yokmir Forest ...",
    },
    69: {
        "name": "StoryMapScene",
        "summary": "Story scene on a map at a main-scenario chapter (special-event condition must hold).",
        "bank": "primary: whatever slot 1 holds (story banks 211+ in the corpus) or tail",
        "keys": [
            {"index": 0, "name": "map", "meaning": "map id (tag 4) from the event descriptor word +2", "wildcard": True},
            {"index": 1, "name": "chapter", "meaning": "REG_MAIN_SCENARIO (9-bit) value", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + " (mode 1, step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x45) from NpcAi_TickOneActor_Step2 (RF4S.exe+0x1F34F0), handler 29",
        "confidence": "verified",
        "notes": "",
    },
    70: {
        "name": "StoryMapEnterScene",
        "summary": "Story scene on entering a map, looked up in the chapter's story bank (211 + threshold index).",
        "bank": "primary: story bank 211..224 selected by g_storyChapterToEventActionIdThresholds_14u32",
        "keys": [
            {"index": 0, "name": "map", "meaning": "map id (tag 4) from the event descriptor word +2 (kind 30 is queued with the entered map)", "wildcard": True},
            {"index": 1, "name": "chapter", "meaning": "REG_MAIN_SCENARIO value", "wildcard": True},
        ],
        "select": "first",
        "consumer": "direct state-machine kick with bank slot 1 (NpcAi_CheckAndDispatchStoryEventByChapter validates ctx+8->+24->+208)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x46) from NpcAi_CheckAndDispatchStoryEventByChapter (RF4S.exe+0x1F3590), handler 30",
        "confidence": "verified",
        "notes": "Corpus maps: 309 Obsidian Mansion, 160 Airship, 347 Leon Karnak, 348 Floating Empire.",
    },
    71: {
        "name": "StoryRegionScene",
        "summary": "Story scene collected on map entry: chapter gate, em condition, trigger box (record kind 4, no NPC list).",
        "bank": "primary: story bank 211+ (NpcAi_CheckSpecialEventCondition)",
        "keys": [
            {"index": 0, "name": "map", "meaning": "map id (tag 4) == the entered map (canonical)", "wildcard": False},
            {"index": 1, "name": "chapter", "meaning": "collected when <= REG_MAIN_SCENARIO or -1; resolved when == REG_MAIN_SCENARIO (or -1)", "wildcard": True},
            {"index": 2, "name": "condition", "meaning": "em.bin condition id at record +16 (0 = none)", "wildcard": False},
            {"index": 3, "name": "x1", "meaning": "trigger box x1", "wildcard": False},
            {"index": 4, "name": "y1", "meaning": "trigger box y1", "wildcard": False},
            {"index": 5, "name": "x2", "meaning": "trigger box x2", "wildcard": False},
            {"index": 6, "name": "y2", "meaning": "trigger box y2", "wildcard": False},
        ],
        "select": "all",
        "consumer": _COLLECT + " (kind 4 records are queued as game-event kind 32)",
        "matcher": "inline loop in Npc_OnTalkAction_QueueDialogueCascade (RF4S.exe+0x1EE7C0, reads at RF4S.exe+0x1EECB0..0x1EEDBE)",
        "confidence": "likely",
        "notes": "",
    },
    72: {
        "name": "StoryChapterTalk",
        "summary": "Story-bank line keyed by (char id, main-scenario chapter).",
        "bank": "primary: story bank 211+ (whatever slot 1 holds when NpcAi_ResolveVillagerBehavior step 1 runs)",
        "keys": [
            {"index": 0, "name": "npc", "meaning": "char id of the talking NPC", "wildcard": True},
            {"index": 1, "name": "chapter", "meaning": "REG_MAIN_SCENARIO value", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x48) at RF4S.exe+0x1F800E and the step-1 call in NpcAi_ResolveVillagerBehavior",
        "confidence": "verified",
        "notes": "Corpus: banks 211..222 plus 3 tail banks; e.g. bank 211 has (3 Volkanon, chapters 4/5/6/8).",
    },
    73: {
        "name": "GlobalScene73",
        "summary": "Key-less global scene (queued as game-event kind 28 by the map-entry cascade when word_7FF7BF72CB52 is set).",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "first",
        "consumer": _APPLY0 + " (step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x49) from NpcAi_ProbeMovementFromEventKind73 (RF4S.exe+0x1F33E0), handler 28",
        "confidence": "verified",
        "notes": "",
    },
}

# Types that share a matcher with a catalogued sibling: copy and adjust.
def _sibling(src, name, summary, **over):
    d = dict(ENTRY_TYPES[src])
    d["keys"] = [dict(k) for k in d["keys"]]
    d.update({"name": name, "summary": summary})
    d.update(over)
    return d

ENTRY_TYPES[24] = _sibling(23, "FestivalTalk1", "Festival line for festival phase 1 (type = 23 + REG_FES_STATUS); key = festival id.")
ENTRY_TYPES[25] = _sibling(23, "FestivalTalk2", "Festival line for festival phase 2 (type = 23 + REG_FES_STATUS); key = festival id.")
ENTRY_TYPES[26] = _sibling(23, "FestivalTalk3", "Festival line for festival phase 3 (type = 23 + REG_FES_STATUS); key = festival id.")
ENTRY_TYPES[33] = _sibling(32, "TalkLineTier2", "Regular talk line, relationship tier 2 (friend); key = per-NPC line index.")
ENTRY_TYPES[34] = _sibling(32, "TalkLineTier3", "Regular talk line, relationship tier 3 (lover); key = per-NPC line index.")
ENTRY_TYPES[35] = _sibling(32, "TalkLineTier4", "Regular talk line, relationship tier 4 (spouse); key = per-NPC line index.")
ENTRY_TYPES[36] = _sibling(32, "TalkLineSpouseExtra", "Spouse-only extra list probed with key 640 ((5<<7)|0); absent from the shipped corpus.",
                            confidence="likely", notes="Code-only: Npc_FindTalkLineEventByTierKey(key 0x280) at RF4S.exe+0x1F9419.")
ENTRY_TYPES[47] = _sibling(46, "InteractionScene47", "Key-less scene run by NpcAi_PerFrameTick for the current interaction NPC when scene control bit 21 (0x200000) is set.")
ENTRY_TYPES[57] = _sibling(56, "SpecialEventKind57", "Story-bank scene of dynamic kind 57 (= 56 + descriptor byte 1), keyed by the context byte +329.")
ENTRY_TYPES[64] = _sibling(63, "SubEventParticipantsSceneB", "Second kind-3 list (collected after type 63): step, map and required NPCs / packed-flag NPC ids.",
                            notes="Corpus: banks 120 and 124 only; -1 (spouse) and 16638 (packed flag) in the NPC list.")
ENTRY_TYPES[66] = _sibling(65, "SubEventRegionSceneC", "Second kind-1 list (collected after type 65): map, step, trigger box, required NPCs.",
                            notes="Corpus: 7 sub-event banks; NPC list holds ids or the packed flags 16582/16638.")

# Code-only types referenced by the exe but absent from the shipped rf3.mc.
ENTRY_TYPES[52] = {
    "name": "CustomTypeByteScene", "summary": "Global scene keyed by the event descriptor byte +2 (code-only, absent from the corpus).",
    "bank": "global (slot 0)",
    "keys": [{"index": 0, "name": "code", "meaning": "descriptor byte +2", "wildcard": True}],
    "select": "first", "consumer": _APPLY0 + " (step immediately)",
    "matcher": "Npc_PredicateMatchSubBytesAndCommitEventId from NpcAi_ProbeAndApplyMovementWithCustomTypeByte (RF4S.exe+0x1F6F40), handler 6",
    "confidence": "likely", "notes": "Skipped while the player is dead (Player_DeathTickCallback).",
}
ENTRY_TYPES[55] = {
    "name": "GlobalScene55", "summary": "Key-less global scene (code-only, absent from the corpus).",
    "bank": "global (slot 0)", "keys": [], "select": "first", "consumer": _APPLY0 + " (step immediately)",
    "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x37) from NpcAi_ProbeMovementFromEventKind55 (RF4S.exe+0x1F28F0), handler 16",
    "confidence": "likely", "notes": "Expected keys [0, 0].",
}
ENTRY_TYPES[58] = {
    "name": "MapSpecialEventKind58", "summary": "Tail-bank scene keyed by the context byte +329, forces Volkanon (char 3) to react (code-only).",
    "bank": "tail (slot 2)",
    "keys": [{"index": 0, "name": "ctx329", "meaning": "npc_event_ctx byte +329", "wildcard": True}],
    "select": "first", "consumer": "Npc_QueueReactionEventAndTurnTowardPlayer(3) then " + _KICK2,
    "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x3A) from NpcAi_TriggerScriptedEventKind58_ForceVolkanonReact (RF4S.exe+0x1F7470), handler 18",
    "confidence": "likely", "notes": "",
}
ENTRY_TYPES[61] = {
    "name": "FriendshipByteTalk", "summary": "Villager line keyed by friendship-entry byte +2 (code-only, absent from the corpus).",
    "bank": "primary: canonical char id",
    "keys": [{"index": 0, "name": "value", "meaning": "g_gameGlobalsSlotTable entry byte +2 of the NPC (non-zero), also written into byte +59", "wildcard": True}],
    "select": "first", "consumer": _APPLY1,
    "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x3D) at RF4S.exe+0x1F91F6 (NpcAi_ResolveVillagerBehavior step 12)",
    "confidence": "likely", "notes": "",
}

CODE_ONLY_TYPES = frozenset({36, 52, 55, 58, 61})


# ---------------------------------------------------------------------------
# Corpus statistics (rf3.mc, bundlePatch1, all 1121 banks; generated by the
# survey parser).  keys[k] = {tags, min, max, distinct, wildcards, n} where
# min/max/distinct ignore -1.
# ---------------------------------------------------------------------------
CORPUS_STATS = {
    0: {'entries': 189, 'banks': {'primary': 29}, 'sizes': {1: 185, 2: 2, 12: 1, 18: 1}, 'keys': {0: {'tags': {4: 189}, 'min': 28, 'max': 303, 'distinct': 20, 'wildcards': 6, 'n': 189}, 1: {'tags': {4: 4}, 'min': 133, 'max': 305, 'distinct': 3, 'wildcards': 0, 'n': 4}, 2: {'tags': {4: 2}, 'min': 179, 'max': 306, 'distinct': 2, 'wildcards': 0, 'n': 2}, 3: {'tags': {4: 2}, 'min': 206, 'max': 307, 'distinct': 2, 'wildcards': 0, 'n': 2}, 4: {'tags': {4: 2}, 'min': 205, 'max': 308, 'distinct': 2, 'wildcards': 0, 'n': 2}, 5: {'tags': {4: 2}, 'min': 228, 'max': 309, 'distinct': 2, 'wildcards': 0, 'n': 2}, 6: {'tags': {4: 2}, 'min': 229, 'max': 310, 'distinct': 2, 'wildcards': 0, 'n': 2}, 7: {'tags': {4: 2}, 'min': 252, 'max': 311, 'distinct': 2, 'wildcards': 0, 'n': 2}, 8: {'tags': {4: 2}, 'min': 256, 'max': 312, 'distinct': 2, 'wildcards': 0, 'n': 2}, 9: {'tags': {4: 2}, 'min': 232, 'max': 313, 'distinct': 2, 'wildcards': 0, 'n': 2}, 10: {'tags': {4: 2}, 'min': 233, 'max': 314, 'distinct': 2, 'wildcards': 0, 'n': 2}, 11: {'tags': {4: 2}, 'min': 258, 'max': 315, 'distinct': 2, 'wildcards': 0, 'n': 2}, 12: {'tags': {4: 1}, 'min': 316, 'max': 316, 'distinct': 1, 'wildcards': 0, 'n': 1}, 13: {'tags': {4: 1}, 'min': 317, 'max': 317, 'distinct': 1, 'wildcards': 0, 'n': 1}, 14: {'tags': {4: 1}, 'min': 318, 'max': 318, 'distinct': 1, 'wildcards': 0, 'n': 1}, 15: {'tags': {4: 1}, 'min': 319, 'max': 319, 'distinct': 1, 'wildcards': 0, 'n': 1}, 16: {'tags': {4: 1}, 'min': 320, 'max': 320, 'distinct': 1, 'wildcards': 0, 'n': 1}, 17: {'tags': {4: 1}, 'min': 321, 'max': 321, 'distinct': 1, 'wildcards': 0, 'n': 1}}},
    2: {'entries': 1098, 'banks': {'global': 1, 'primary': 27, 'tail': 185}, 'sizes': {1: 1098}, 'keys': {0: {'tags': {1: 1098}, 'min': 100, 'max': 2435, 'distinct': 318, 'wildcards': 0, 'n': 1098}}},
    3: {'entries': 39, 'banks': {'tail': 20}, 'sizes': {5: 39}, 'keys': {0: {'tags': {1: 39}, 'min': 56, 'max': 409, 'distinct': 24, 'wildcards': 0, 'n': 39}, 1: {'tags': {1: 39}, 'min': 100, 'max': 456, 'distinct': 21, 'wildcards': 0, 'n': 39}, 2: {'tags': {1: 39}, 'min': 114, 'max': 472, 'distinct': 25, 'wildcards': 0, 'n': 39}, 3: {'tags': {1: 39}, 'min': 160, 'max': 520, 'distinct': 20, 'wildcards': 0, 'n': 39}, 4: {'tags': {1: 39}, 'min': 23, 'max': 129, 'distinct': 10, 'wildcards': 24, 'n': 39}}},
    4: {'entries': 29, 'banks': {'primary': 29}, 'sizes': {1: 29}, 'keys': {0: {'tags': {1: 29}, 'min': None, 'max': None, 'distinct': 0, 'wildcards': 29, 'n': 29}}},
    5: {'entries': 9, 'banks': {'tail': 5}, 'sizes': {3: 9}, 'keys': {0: {'tags': {1: 9}, 'min': 100, 'max': 101, 'distinct': 2, 'wildcards': 0, 'n': 9}, 1: {'tags': {1: 9}, 'min': 1, 'max': 1, 'distinct': 1, 'wildcards': 0, 'n': 9}, 2: {'tags': {1: 9}, 'min': 2, 'max': 47, 'distinct': 8, 'wildcards': 1, 'n': 9}}},
    6: {'entries': 246, 'banks': {'tail': 246}, 'sizes': {0: 246}, 'keys': {}},
    7: {'entries': 45, 'banks': {'tail': 45}, 'sizes': {0: 45}, 'keys': {}},
    8: {'entries': 1, 'banks': {'global': 1}, 'sizes': {0: 1}, 'keys': {}},
    9: {'entries': 1, 'banks': {'global': 1}, 'sizes': {0: 1}, 'keys': {}},
    10: {'entries': 1, 'banks': {'global': 1}, 'sizes': {0: 1}, 'keys': {}},
    11: {'entries': 1, 'banks': {'global': 1}, 'sizes': {0: 1}, 'keys': {}},
    13: {'entries': 1, 'banks': {'global': 1}, 'sizes': {0: 1}, 'keys': {}},
    15: {'entries': 353, 'banks': {'primary': 50, 'tail': 35}, 'sizes': {1: 353}, 'keys': {0: {'tags': {1: 353}, 'min': 100, 'max': 3900, 'distinct': 88, 'wildcards': 0, 'n': 353}}},
    16: {'entries': 1, 'banks': {'tail': 1}, 'sizes': {0: 1}, 'keys': {}},
    17: {'entries': 41, 'banks': {'tail': 33}, 'sizes': {2: 41}, 'keys': {0: {'tags': {1: 41}, 'min': 104, 'max': 249, 'distinct': 40, 'wildcards': 0, 'n': 41}, 1: {'tags': {1: 41}, 'min': 26, 'max': 46, 'distinct': 2, 'wildcards': 36, 'n': 41}}},
    19: {'entries': 26, 'banks': {'primary': 26}, 'sizes': {0: 26}, 'keys': {}},
    20: {'entries': 29, 'banks': {'primary': 29}, 'sizes': {0: 29}, 'keys': {}},
    21: {'entries': 29, 'banks': {'primary': 29}, 'sizes': {0: 29}, 'keys': {}},
    22: {'entries': 69, 'banks': {'primary': 23}, 'sizes': {1: 69}, 'keys': {0: {'tags': {1: 69}, 'min': 0, 'max': 2, 'distinct': 3, 'wildcards': 0, 'n': 69}}},
    23: {'entries': 572, 'banks': {'primary': 23}, 'sizes': {1: 572}, 'keys': {0: {'tags': {1: 572}, 'min': 1, 'max': 25, 'distinct': 25, 'wildcards': 0, 'n': 572}}},
    24: {'entries': 579, 'banks': {'primary': 23, 'tail': 1}, 'sizes': {1: 579}, 'keys': {0: {'tags': {1: 579}, 'min': 1, 'max': 25, 'distinct': 25, 'wildcards': 0, 'n': 579}}},
    25: {'entries': 579, 'banks': {'primary': 23, 'tail': 1}, 'sizes': {1: 579}, 'keys': {0: {'tags': {1: 579}, 'min': 1, 'max': 25, 'distinct': 25, 'wildcards': 0, 'n': 579}}},
    26: {'entries': 549, 'banks': {'primary': 23}, 'sizes': {1: 549}, 'keys': {0: {'tags': {1: 549}, 'min': 1, 'max': 25, 'distinct': 24, 'wildcards': 0, 'n': 549}}},
    27: {'entries': 1034, 'banks': {'global': 1, 'primary': 152}, 'sizes': {2: 1034}, 'keys': {0: {'tags': {1: 1034}, 'min': 0, 'max': 3, 'distinct': 4, 'wildcards': 0, 'n': 1034}, 1: {'tags': {3: 1034}, 'min': 0, 'max': 210, 'distinct': 28, 'wildcards': 0, 'n': 1034}}},
    28: {'entries': 33, 'banks': {'primary': 30}, 'sizes': {1: 33}, 'keys': {0: {'tags': {3: 33}, 'min': 1, 'max': 22, 'distinct': 16, 'wildcards': 0, 'n': 33}}},
    30: {'entries': 527, 'banks': {'primary': 23}, 'sizes': {2: 527}, 'keys': {0: {'tags': {1: 527}, 'min': 42, 'max': 511, 'distinct': 23, 'wildcards': 0, 'n': 527}, 1: {'tags': {1: 527}, 'min': 0, 'max': 512, 'distinct': 18, 'wildcards': 0, 'n': 527}}},
    31: {'entries': 196, 'banks': {'primary': 23}, 'sizes': {1: 196}, 'keys': {0: {'tags': {1: 196}, 'min': 29, 'max': 532, 'distinct': 45, 'wildcards': 0, 'n': 196}}},
    32: {'entries': 397, 'banks': {'primary': 23}, 'sizes': {1: 397}, 'keys': {0: {'tags': {1: 397}, 'min': 1, 'max': 30, 'distinct': 30, 'wildcards': 0, 'n': 397}}},
    33: {'entries': 669, 'banks': {'primary': 23}, 'sizes': {1: 669}, 'keys': {0: {'tags': {1: 669}, 'min': 1, 'max': 39, 'distinct': 39, 'wildcards': 0, 'n': 669}}},
    34: {'entries': 533, 'banks': {'primary': 18}, 'sizes': {1: 533}, 'keys': {0: {'tags': {1: 533}, 'min': 1, 'max': 58, 'distinct': 58, 'wildcards': 0, 'n': 533}}},
    35: {'entries': 724, 'banks': {'primary': 18}, 'sizes': {1: 724}, 'keys': {0: {'tags': {1: 724}, 'min': 1, 'max': 66, 'distinct': 66, 'wildcards': 0, 'n': 724}}},
    37: {'entries': 2, 'banks': {'global': 1}, 'sizes': {1: 2}, 'keys': {0: {'tags': {1: 2}, 'min': 1, 'max': 2, 'distinct': 2, 'wildcards': 0, 'n': 2}}},
    38: {'entries': 28, 'banks': {'primary': 6}, 'sizes': {1: 28}, 'keys': {0: {'tags': {3: 28}, 'min': 1, 'max': 23, 'distinct': 23, 'wildcards': 0, 'n': 28}}},
    39: {'entries': 217, 'banks': {'primary': 72}, 'sizes': {1: 217}, 'keys': {0: {'tags': {4: 217}, 'min': 24, 'max': 860, 'distinct': 74, 'wildcards': 0, 'n': 217}}},
    40: {'entries': 10, 'banks': {'primary': 8}, 'sizes': {1: 10}, 'keys': {0: {'tags': {4: 10}, 'min': 24, 'max': 272, 'distinct': 9, 'wildcards': 0, 'n': 10}}},
    43: {'entries': 69, 'banks': {'primary': 23}, 'sizes': {1: 69}, 'keys': {0: {'tags': {1: 69}, 'min': 0, 'max': 2, 'distinct': 3, 'wildcards': 0, 'n': 69}}},
    44: {'entries': 81, 'banks': {'primary': 23}, 'sizes': {1: 81}, 'keys': {0: {'tags': {1: 81}, 'min': 70, 'max': 164, 'distinct': 39, 'wildcards': 0, 'n': 81}}},
    45: {'entries': 329, 'banks': {'primary': 52}, 'sizes': {1: 329}, 'keys': {0: {'tags': {1: 329}, 'min': 45, 'max': 165, 'distinct': 56, 'wildcards': 46, 'n': 329}}},
    46: {'entries': 29, 'banks': {'primary': 29}, 'sizes': {0: 29}, 'keys': {}},
    47: {'entries': 29, 'banks': {'primary': 29}, 'sizes': {0: 29}, 'keys': {}},
    48: {'entries': 1, 'banks': {'global': 1}, 'sizes': {0: 1}, 'keys': {}},
    49: {'entries': 1, 'banks': {'global': 1}, 'sizes': {0: 1}, 'keys': {}},
    50: {'entries': 6, 'banks': {'primary': 6}, 'sizes': {3: 6}, 'keys': {0: {'tags': {1: 6}, 'min': None, 'max': None, 'distinct': 0, 'wildcards': 6, 'n': 6}, 1: {'tags': {1: 6}, 'min': 0, 'max': 0, 'distinct': 1, 'wildcards': 0, 'n': 6}, 2: {'tags': {1: 6}, 'min': 676, 'max': 676, 'distinct': 1, 'wildcards': 0, 'n': 6}}},
    51: {'entries': 45, 'banks': {'primary': 23}, 'sizes': {1: 45}, 'keys': {0: {'tags': {1: 45}, 'min': 0, 'max': 1, 'distinct': 2, 'wildcards': 0, 'n': 45}}},
    53: {'entries': 27, 'banks': {'global': 1}, 'sizes': {1: 27}, 'keys': {0: {'tags': {1: 27}, 'min': 1, 'max': 27, 'distinct': 27, 'wildcards': 0, 'n': 27}}},
    54: {'entries': 1, 'banks': {'global': 1}, 'sizes': {0: 1}, 'keys': {}},
    56: {'entries': 1, 'banks': {'primary': 1}, 'sizes': {1: 1}, 'keys': {0: {'tags': {1: 1}, 'min': 0, 'max': 0, 'distinct': 1, 'wildcards': 0, 'n': 1}}},
    57: {'entries': 1, 'banks': {'primary': 1}, 'sizes': {1: 1}, 'keys': {0: {'tags': {1: 1}, 'min': 0, 'max': 0, 'distinct': 1, 'wildcards': 0, 'n': 1}}},
    60: {'entries': 230, 'banks': {'primary': 23}, 'sizes': {1: 230}, 'keys': {0: {'tags': {1: 230}, 'min': 1, 'max': 10, 'distinct': 10, 'wildcards': 0, 'n': 230}}},
    62: {'entries': 44, 'banks': {'primary': 44}, 'sizes': {0: 44}, 'keys': {}},
    63: {'entries': 50, 'banks': {'primary': 22}, 'sizes': {3: 9, 4: 29, 5: 8, 6: 3, 7: 1}, 'keys': {0: {'tags': {1: 50}, 'min': 0, 'max': 26, 'distinct': 16, 'wildcards': 0, 'n': 50}, 1: {'tags': {4: 50}, 'min': 24, 'max': 143, 'distinct': 16, 'wildcards': 0, 'n': 50}, 2: {'tags': {3: 50}, 'min': 1, 'max': 20, 'distinct': 16, 'wildcards': 0, 'n': 50}, 3: {'tags': {3: 41}, 'min': 2, 'max': 20, 'distinct': 13, 'wildcards': 0, 'n': 41}, 4: {'tags': {3: 12}, 'min': 2, 'max': 20, 'distinct': 8, 'wildcards': 0, 'n': 12}, 5: {'tags': {3: 4}, 'min': 9, 'max': 17, 'distinct': 3, 'wildcards': 0, 'n': 4}, 6: {'tags': {3: 1}, 'min': 5, 'max': 5, 'distinct': 1, 'wildcards': 0, 'n': 1}}},
    64: {'entries': 7, 'banks': {'primary': 2}, 'sizes': {3: 3, 4: 3, 5: 1}, 'keys': {0: {'tags': {1: 7}, 'min': 2, 'max': 14, 'distinct': 7, 'wildcards': 0, 'n': 7}, 1: {'tags': {4: 7}, 'min': 28, 'max': 64, 'distinct': 4, 'wildcards': 0, 'n': 7}, 2: {'tags': {1: 3, 2: 4}, 'min': 16638, 'max': 16638, 'distinct': 1, 'wildcards': 3, 'n': 7}, 3: {'tags': {2: 3, 1: 1}, 'min': 18, 'max': 16638, 'distinct': 2, 'wildcards': 0, 'n': 4}, 4: {'tags': {1: 1}, 'min': 3, 'max': 3, 'distinct': 1, 'wildcards': 0, 'n': 1}}},
    65: {'entries': 34, 'banks': {'primary': 18}, 'sizes': {7: 16, 8: 9, 9: 4, 10: 3, 11: 2}, 'keys': {0: {'tags': {4: 34}, 'min': 24, 'max': 485, 'distinct': 12, 'wildcards': 0, 'n': 34}, 1: {'tags': {1: 34}, 'min': 1, 'max': 23, 'distinct': 16, 'wildcards': 0, 'n': 34}, 2: {'tags': {1: 34}, 'min': 30, 'max': 1006, 'distinct': 31, 'wildcards': 0, 'n': 34}, 3: {'tags': {1: 34}, 'min': 125, 'max': 486, 'distinct': 27, 'wildcards': 0, 'n': 34}, 4: {'tags': {1: 34}, 'min': 50, 'max': 1150, 'distinct': 30, 'wildcards': 0, 'n': 34}, 5: {'tags': {1: 34}, 'min': 225, 'max': 597, 'distinct': 30, 'wildcards': 0, 'n': 34}, 6: {'tags': {3: 34}, 'min': 0, 'max': 17, 'distinct': 11, 'wildcards': 0, 'n': 34}, 7: {'tags': {3: 18}, 'min': 4, 'max': 19, 'distinct': 10, 'wildcards': 0, 'n': 18}, 8: {'tags': {3: 9}, 'min': 2, 'max': 13, 'distinct': 4, 'wildcards': 0, 'n': 9}, 9: {'tags': {3: 5}, 'min': 1, 'max': 17, 'distinct': 4, 'wildcards': 0, 'n': 5}, 10: {'tags': {3: 2}, 'min': 1, 'max': 3, 'distinct': 2, 'wildcards': 0, 'n': 2}}},
    66: {'entries': 12, 'banks': {'primary': 7}, 'sizes': {7: 4, 8: 8}, 'keys': {0: {'tags': {4: 12}, 'min': 24, 'max': 48, 'distinct': 4, 'wildcards': 0, 'n': 12}, 1: {'tags': {1: 12}, 'min': 1, 'max': 20, 'distinct': 10, 'wildcards': 0, 'n': 12}, 2: {'tags': {1: 12}, 'min': 250, 'max': 1332, 'distinct': 10, 'wildcards': 0, 'n': 12}, 3: {'tags': {1: 12}, 'min': 190, 'max': 508, 'distinct': 7, 'wildcards': 0, 'n': 12}, 4: {'tags': {1: 12}, 'min': 328, 'max': 1424, 'distinct': 10, 'wildcards': 0, 'n': 12}, 5: {'tags': {1: 12}, 'min': 282, 'max': 617, 'distinct': 7, 'wildcards': 0, 'n': 12}, 6: {'tags': {1: 4, 2: 8}, 'min': 4, 'max': 16638, 'distinct': 5, 'wildcards': 0, 'n': 12}, 7: {'tags': {1: 4, 2: 4}, 'min': 3, 'max': 16638, 'distinct': 4, 'wildcards': 0, 'n': 8}}},
    67: {'entries': 17, 'banks': {'primary': 8}, 'sizes': {8: 16, 9: 1}, 'keys': {0: {'tags': {4: 17}, 'min': 24, 'max': 64, 'distinct': 5, 'wildcards': 0, 'n': 17}, 1: {'tags': {1: 17}, 'min': 1, 'max': 21, 'distinct': 10, 'wildcards': 0, 'n': 17}, 2: {'tags': {1: 17}, 'min': 0, 'max': 270, 'distinct': 10, 'wildcards': 0, 'n': 17}, 3: {'tags': {1: 17}, 'min': 63, 'max': 998, 'distinct': 13, 'wildcards': 0, 'n': 17}, 4: {'tags': {1: 17}, 'min': 126, 'max': 470, 'distinct': 13, 'wildcards': 0, 'n': 17}, 5: {'tags': {1: 17}, 'min': 125, 'max': 1250, 'distinct': 13, 'wildcards': 0, 'n': 17}, 6: {'tags': {1: 17}, 'min': 221, 'max': 562, 'distinct': 12, 'wildcards': 0, 'n': 17}, 7: {'tags': {3: 17}, 'min': 0, 'max': 15, 'distinct': 3, 'wildcards': 0, 'n': 17}, 8: {'tags': {3: 1}, 'min': 13, 'max': 13, 'distinct': 1, 'wildcards': 0, 'n': 1}}},
    68: {'entries': 55, 'banks': {'primary': 27, 'tail': 6}, 'sizes': {3: 55}, 'keys': {0: {'tags': {4: 55}, 'min': 0, 'max': 866, 'distinct': 32, 'wildcards': 0, 'n': 55}, 1: {'tags': {2: 55}, 'min': 50, 'max': 32768, 'distinct': 10, 'wildcards': 0, 'n': 55}, 2: {'tags': {1: 55}, 'min': 0, 'max': 398, 'distinct': 32, 'wildcards': 0, 'n': 55}}},
    69: {'entries': 136, 'banks': {'primary': 12, 'tail': 2}, 'sizes': {2: 136}, 'keys': {0: {'tags': {4: 136}, 'min': 4, 'max': 848, 'distinct': 66, 'wildcards': 0, 'n': 136}, 1: {'tags': {1: 136}, 'min': 0, 'max': 468, 'distinct': 110, 'wildcards': 0, 'n': 136}}},
    70: {'entries': 11, 'banks': {'primary': 2, 'tail': 1}, 'sizes': {2: 11}, 'keys': {0: {'tags': {4: 11}, 'min': 160, 'max': 348, 'distinct': 4, 'wildcards': 0, 'n': 11}, 1: {'tags': {1: 11}, 'min': 114, 'max': 398, 'distinct': 5, 'wildcards': 0, 'n': 11}}},
    71: {'entries': 38, 'banks': {'primary': 7, 'tail': 1}, 'sizes': {7: 38}, 'keys': {0: {'tags': {4: 38}, 'min': 4, 'max': 600, 'distinct': 18, 'wildcards': 0, 'n': 38}, 1: {'tags': {1: 38}, 'min': 100, 'max': 204, 'distinct': 8, 'wildcards': 27, 'n': 38}, 2: {'tags': {1: 38}, 'min': 0, 'max': 24, 'distinct': 14, 'wildcards': 0, 'n': 38}, 3: {'tags': {1: 38}, 'min': 5, 'max': 836, 'distinct': 35, 'wildcards': 0, 'n': 38}, 4: {'tags': {1: 38}, 'min': 0, 'max': 562, 'distinct': 27, 'wildcards': 0, 'n': 38}, 5: {'tags': {1: 38}, 'min': 44, 'max': 864, 'distinct': 34, 'wildcards': 0, 'n': 38}, 6: {'tags': {1: 38}, 'min': 70, 'max': 580, 'distinct': 30, 'wildcards': 0, 'n': 38}}},
    72: {'entries': 57, 'banks': {'primary': 11, 'tail': 3}, 'sizes': {2: 57}, 'keys': {0: {'tags': {1: 57}, 'min': 1, 'max': 24, 'distinct': 12, 'wildcards': 0, 'n': 57}, 1: {'tags': {1: 57}, 'min': 4, 'max': 370, 'distinct': 28, 'wildcards': 7, 'n': 57}}},
    73: {'entries': 1, 'banks': {'global': 1}, 'sizes': {0: 1}, 'keys': {}},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
__all__ = [
    "ENTRY_TYPES", "CORPUS_STATS", "CODE_ONLY_TYPES", "CHAR_NAMES", "TAG_NAMES",
    "BANK_SLOTS", "SENTINEL_NONE", "TYPE_TABLE_SLOTS",
    "type_name", "key_spec", "describe_entry", "corpus_types",
]


def corpus_types():
    """Sorted list of the type ids that occur in the shipped rf3.mc."""
    return sorted(CORPUS_STATS)


def type_name(type_id):
    """Short CamelCase name of an action-entry type ("Type<n>" when uncatalogued)."""
    spec = ENTRY_TYPES.get(type_id)
    return spec["name"] if spec else "Type%d" % type_id


def key_spec(type_id, k):
    """Key spec (dict) that applies to sub-record index ``k`` of ``type_id``, or None.

    Explicit integer indexes win over an open-ended "n+" spec; among several
    "n+" specs the one with the largest start that is <= k applies.
    """
    spec = ENTRY_TYPES.get(type_id)
    if not spec:
        return None
    best, best_start = None, -1
    for ks in spec["keys"]:
        idx = ks["index"]
        if isinstance(idx, int):
            if idx == k:
                return ks
            continue
        start = int(str(idx).rstrip("+"))
        if start <= k and start > best_start:
            best, best_start = ks, start
    return best


_PACKED_FLAG_VALUES = (16582, 16638)


def _fmt_flagref(value):
    return "flag#%d/%db" % (value & 0xFFFE0FFF, ((value >> 12) & 0xF) + 1)


def _fmt_date(value):
    if value < 0:
        return "any date"
    if value <= 120:
        return "day %d of season %d" % (value % 30 + 1, value // 30)
    return "%d day(s) before festival %d" % ((value >> 8) - 1, value & 0xFF)


def _fmt_npc(value):
    name = CHAR_NAMES.get(value)
    return "%d(%s)" % (value, name) if name else str(value)


def _fmt_value(type_id, kname, tag, value):
    if kname == "date":
        return _fmt_date(value)
    if tag == 0x02 or value in _PACKED_FLAG_VALUES:
        return _fmt_flagref(value)
    if kname == "npc":
        if value == -1:
            return "spouse" if type_id in (63, 64) else "any"
        return _fmt_npc(value)
    if kname == "timeslot":
        return {0: "morning", 1: "daytime", 2: "evening"}.get(value, str(value))
    if kname == "is_spouse":
        return {0: "not spouse", 1: "spouse"}.get(value, "any" if value == -1 else str(value))
    if kname == "milestone":
        return {1: "progress", 2: "completed"}.get(value, str(value))
    if kname == "condition":
        return "none" if value == -1 else "em#%d" % value
    if kname == "consume":
        return "9 (=-1)" if value == -1 and type_id == 5 else str(value)
    if value == -1:
        return "any"
    return str(value)


def describe_entry(type_id, subs):
    """One-line human description of an entry: ``subs`` = list of (tag, value).

    >>> describe_entry(22, [(1, 0)])
    'DailyGreeting: timeslot morning'
    >>> describe_entry(27, [(1, 2), (3, 3)])
    'SubEventReaction: priority 2, npc 3(Volkanon)'
    """
    name = type_name(type_id)
    if not subs:
        return "%s: (no keys)" % name
    parts = []
    for k, (tag, value) in enumerate(subs):
        ks = key_spec(type_id, k)
        if type_id == 17:                       # (key, condition) pairs
            kname = "key" if k % 2 == 0 else "cond"
            if kname == "cond":
                parts.append("cond %s" % ("always" if value == -1 else "em#%d" % value))
            else:
                parts.append("key %s" % ("any" if value == -1 else str(value)))
            continue
        kname = ks["name"] if ks else "k%d" % k
        txt = _fmt_value(type_id, kname, tag, value)
        if value == -1 and ks is not None and not ks.get("wildcard", False) and txt == "any":
            txt = "-1 (no wildcard for this key)"
        parts.append("%s %s" % (kname, txt))
    return "%s: %s" % (name, ", ".join(parts))


# ---------------------------------------------------------------------------
# Machine-readable bank kind + per-type "how do I register one" recipes
# (added 2026-09-20). Both are DERIVED from the verified fields above -- the
# `bank` prose, `select`, `keys` and `consumer` -- not from new RE claims; the
# per-type evidence and confidence stay exactly as recorded.
# ---------------------------------------------------------------------------
BANK_KINDS = ("global", "tail", "primary:npc", "primary:224+npc",
              "primary:subevent", "primary:story", "mixed")


def _classify_bank(prose):
    """Normalise a type's `bank` prose to one of BANK_KINDS."""
    p = (prose or "").lower()
    has_tail = "tail" in p or "slot 2" in p
    has_prim = "primary" in p or "slot 1" in p
    has_glob = "global" in p or "slot 0" in p
    if sum((has_tail, has_prim, has_glob)) > 1:
        return "mixed"
    if has_glob:
        return "global"
    if has_tail:
        return "tail"
    if "224" in p:
        return "primary:224+npc"
    if "story bank" in p:
        return "primary:story"
    if "sub-event" in p or "subev" in p or "quest bank" in p:
        return "primary:subevent"
    if has_prim:
        return "primary:npc"
    return "mixed"


for _t, _info in ENTRY_TYPES.items():
    _info.setdefault("bank_kind", _classify_bank(_info.get("bank")))
del _t, _info


def bank_kind(type_id):
    """Which bank a scene of this type must live in, as one of BANK_KINDS."""
    return (ENTRY_TYPES.get(type_id) or {}).get("bank_kind", "mixed")


# A recipe is the minimal correct way to register a NEW scene of that type: which
# bank, which keys, and the ordering caveat. `select` == "last" means the engine
# runs only the final entry of the list, so an appended entry SHADOWS the existing
# one -- every such recipe says so.
RECIPES = {
    0: "Talk line picked by where the player is. Bank: the villager's second bank, "
       "224 + canonical char id. One key = map id (-1 = any map, used as the fallback "
       "line). First exact map match wins, else the last wildcard entry, so add the "
       "specific map BEFORE the -1 catch-all (position 0) or it will never be reached.",
    3: "Scene that fires when the player walks into a rectangle. Bank: the map's tail "
       "bank (container index = n_primary + map id). Keys: x1, y1, x2, y2 (corners are "
       "min/max-normalised, so either order works) and an em.bin condition id, -1 for "
       "unconditional. First box that contains the player wins; the engine will not "
       "re-fire the same scene while the player stays inside it.",
    4: "Fallback reaction when an item is thrown at an NPC and nothing more specific "
       "matched. Bank: that NPC's primary bank (canonical char id). Keys: the item ids "
       "(-1 = any item). First match wins.",
    6: "Map scene with no keys. Bank: the map's tail bank (n_primary + map id). WARNING: "
       "only the LAST type-6 entry runs, so appending one replaces the map's current "
       "scene -- CALL the old entry pc from your body if you want to keep it.",
    7: "The map's ENTER scene: no keys, runs when the player arrives. Bank: the map's "
       "tail bank (n_primary + map id). WARNING: only the LAST type-7 entry runs, so "
       "appending one replaces the map's current enter scene -- CALL the old entry pc "
       "from your body if you want to keep it. This is the usual way to add a cutscene "
       "to a map that has none (an unused map bank is 296 zero bytes).",
    9: "Global scene run when a fish is caught; no keys, global bank. Only the LAST "
       "entry runs, and the shipped file has exactly one, so a new entry replaces it.",
    15: "Chained scene: plays after another cutscene finishes fading. Bank: the same "
        "bank as the scene it follows. One key = the finished scene's logical id. First "
        "match wins, so ids must be unique within the list.",
    22: "First greeting of the day, chosen by time of day. Bank: 224 + canonical char id. "
        "One key = time slot (0 = 06-09h, 1 = 10-17h, 2 = otherwise; -1 = any). First "
        "match wins.",
    30: "Talk line gated by main-scenario progress. Bank: 224 + canonical char id. Keys: "
        "chapter_lo, chapter_hi (inclusive range of REG_MAIN_SCENARIO). Fires once per "
        "range. First match wins, so put narrower ranges before wider ones.",
    49: "Global scene run when the player eats; no keys, global bank. Only the LAST entry "
        "runs and the shipped file has one, so a new entry replaces it.",
    50: "Reaction to throwing one specific item at an NPC. Bank: that NPC's primary bank "
        "(canonical char id). Keys: an em.bin condition id (-1 = always), a consume flag, "
        "then the item ids. First match wins.",
    68: "Auto-triggered scene gated by a game flag. Bank: the map's tail bank, or a story / "
        "sub-event primary bank. Keys: map id, game-flag bit id, required value -- pair it "
        "with `em new-var` to get a flag of your own. First match wins.",
    69: "Story scene on a map at a given chapter. Bank: the story bank for that chapter "
        "(primary 211..224). Keys: map id and chapter (-1 = any). First match wins.",
    72: "Chapter-gated talk line. Bank: the story bank (primary 211+). Keys: npc char id "
        "and chapter (-1 = any). First match wins.",
}

for _t, _r in RECIPES.items():
    if _t in ENTRY_TYPES:
        ENTRY_TYPES[_t].setdefault("recipe", _r)
del _t, _r


def recipe(type_id):
    """How to register a new scene of this type, or '' when none is recorded."""
    return (ENTRY_TYPES.get(type_id) or {}).get("recipe", "")


def map_enter_type():
    """The action type a map's ENTER scene is registered under (MapEnterScene)."""
    for t, info in ENTRY_TYPES.items():
        if (info or {}).get("name") == "MapEnterScene":
            return int(t)
    return 7
