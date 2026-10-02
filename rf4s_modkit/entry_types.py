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
           MycfBankSlot_LoadBank RF4S.exe+0x23F9C0 with an index
           that is either a canonical NPC char id (0..47; 23->22, 27..33->27,
           34..40->34, 41..47->41), 224 + canonical id (the villagers' second
           bank), a sub-event id (REG_SUBEV_NOW / quest id, 48..210), or a
           story-chapter bank 211..224 (NpcAi_CheckSpecialEventCondition
           RF4S.exe+0x1FEAB0),
  slot 2 = the TAIL bank of the current map (index = map id).
NpcAi_StartEventScriptAtPc RF4S.exe+0x1F60C0 (mode = bank slot, event_id = PC) is the
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
# player). Read from the game's rf3TxtNpc name list (gamenames; the built-in list without one).
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
    from . import gamenames
    d = {k: v for k, v in gamenames.table("characters").items() if 0 < k < 48 and v}
    d[0] = "Lest/Frey"
    return d if len(d) >= 27 else dict(_CHAR_NAMES_FALLBACK)


def _lazy_char_names():
    from .gamenames import Lazy
    return Lazy(_load_char_names)


CHAR_NAMES = _lazy_char_names()

_APPLY0 = ("NpcAi_StartEventScriptAtPc (RF4S.exe+0x1F60C0) with bank slot 0: the Script VM "
           "runs the scene at event_id in the global bank")
_APPLY1 = ("NpcAi_StartEventScriptAtPc (RF4S.exe+0x1F60C0) with bank slot 1: the Script VM "
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
        "matcher": "Npc_LookupActionEntryByPlayerHitFilter (RF4S.exe+0x220DA0) driven by the unnamed function at RF4S.exe+0x220CD0",
        "confidence": "verified",
        "notes": "The IDB name says 'hit filter' but field_54 is the current map id: the same '& ~3 below 0x40' canonicalisation Map_OnEnter_QueueMapEvents applies to map ids, and the corpus keys are maps (64 Castle: Dragon Room, 65 Your Room, 66 Butler's Room ...). A -1 entry writes the event id but the scan continues, so an exact match later in the list overrides it.",
    },
    2: {
        "name": "ActorInteractScene",
        "summary": "Scene run when the player interacts with a spawned event actor (keyed by its EVENT KEY, the SpawnEventActor key) or with an unregistered special actor of id >= 254 (keyed by its id), and the boss-defeat / field-object scenes queued as game event kind 27 (keys 1025+); probed in the tail bank, then the primary bank, then the global bank.",
        "bank": "tail (slot 2), primary (slot 1), global (slot 0) - probed in that order by NpcAi_ResolveMonsterBehavior",
        "keys": [
            {"index": "0+", "name": "key", "meaning": "the interacted actor's event key when it is a registered event actor (EventActor_GetKeyOfActor RF4S.exe+0x1D3540), else its id (actor +8); for game event kind 27 (NpcAi_TickEventMovementOrFinalize) the queued descriptor word +6 = 1024 + a code: 1/3/6 from Boss_BeginDefeatSequence (RF4S.exe+0x1A8020), 4 from ScriptedAction34 (RF4S.exe+0x1957F0), the interacted object's byte +577 from Player_TickFieldInteraction (RF4S.exe+0x166770)", "wildcard": False},
        ],
        "select": "first",
        "consumer": "NpcAi_StartEventScriptAtPc with the slot that matched (NpcAi_ResolveMonsterBehavior RF4S.exe+0x1F9610 returns the slot in *a3); game event kind 27 (NpcAi_TickEventMovementOrFinalize RF4S.exe+0x1F3070) probes slot 1 first when NpcAi_CheckSpecialEventCondition passes, then slot 2, and kicks the state machine with the slot that matched",
        "matcher": "NpcAi_FindActionEntryByTargetForType2 (RF4S.exe+0x221EC0)",
        "confidence": "verified",
        "notes": "NpcAi_TickOne (RF4S.exe+0x1F6930) sends registered event actors (EventActor_FindRecordByActor RF4S.exe+0x1D35C0 finds their g_calendarEventMng record; wild ones are refused earlier by the talk gate, see op 181 TurnEventActorIntoNpc) and actors of id >= 0xFE to NpcAi_ResolveMonsterBehavior (+0x1F9610), which takes the key described above; key 400 additionally routes through a type-27 lookup in bank 210. Verified 2026-09-28 in game: an event actor spawned with key 1000 in the Dragon Room runs tail bank 308's type-2 entry keyed 1000, one with key 200 (no entry) runs nothing. Corrected 2026-09-28: this was read as an 'actor kind id'. Corrected 2026-09-29: type 2 also holds the boss-defeat scenes keyed 1025+ (dungeon tail banks), queued as game event kind 27 by Boss_BeginDefeatSequence, ScriptedAction34 and Player_TickFieldInteraction (also GameEventQueue_PushKind27TwoArg RF4S.exe+0x1EF330); kind 27 probes slot 1 before slot 2 (the old text said it kicked slot 2 directly).",
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
        "name": "GiftReaction",
        "summary": "The NPC's gift-reaction scene, run when the player gives it an item that no type-50 special-item entry claimed.",
        "bank": "primary: canonical char id of the NPC",
        "keys": [
            {"index": "0+", "name": "item", "meaning": "given item id (slot word & 0x7FF); every shipped entry is -1, so one scene handles every gift", "wildcard": True},
        ],
        "select": "first",
        "consumer": "NpcAi_OnReceivedThrownItem_AdvanceProgressAndDispatchReaction (RF4S.exe+0x1F1730, game event kind 5): Item_UseOnActor + stack decrement (only when the reaction-style bits ctx+116 & 0x1C0 are non-zero and != 0x180 and the item is not 676), then " + _APPLY1,
        "matcher": "Event_QueryThrowReactionFallback (RF4S.exe+0x221120), probed after type 50 in the same canonical bank",
        "confidence": "verified",
        "notes": "The entry is the NPC's whole gift reaction: bank 3's scene (pc 1384) holds the 'Giving rubbish...' refusal, the thank-you line that names the item and the ring refusal. Corrected 2026-09-29: this type was named ThrowFallback and read as a generic fallback for a thrown item.",
    },
    5: {
        "name": "ThrowAtEventActor",
        "summary": "Item thrown at a spawned event actor on a map (crop offerings), matched by the actor's event key; consumes the stack.",
        "bank": "tail (slot 2) first, then the sub-event bank in slot 1 (NpcAi_CheckThrownItemFallbackCondition RF4S.exe+0x1FEA40 loads REG_SUBEV_NOW)",
        "keys": [
            {"index": 0, "name": "event_key", "meaning": "the target actor's event key = word 0 of its g_calendarEventMng record (EventActor_GetKeyOfActor RF4S.exe+0x1D3540 returns that word; the SpawnEventActor key, 100/101 in the corpus); 0 when the target is not an event actor", "wildcard": False},
            {"index": 1, "name": "consume", "meaning": "how many units of the thrown stack to consume (-1 = 9, 0 = none)", "wildcard": False},
            {"index": "2+", "name": "item", "meaning": "thrown item id; -1 matches any item but keeps scanning for an exact match", "wildcard": True},
        ],
        "select": "first",
        "consumer": "Player_DecrementItemStackAfterUse x consume + Quest_OnNonGiftItemConsumed, then NpcAi_StartEventScriptAtPc with the slot that matched (2 or 1)",
        "matcher": "Event_MatchThrownItemActionEntryAndConsume (RF4S.exe+0x222600) via Event_QueryByItemThrowAndPriority (RF4S.exe+0x222510)",
        "confidence": "verified",
        "notes": "Corpus: 5 tail banks (Sechs Territory, Rune Prana), items 2..47 are crops (2 King Cabbage .. 47 Golden Tyrant Turnip). The keys pair with type 2 in the same tail bank: in bank 814 the type-2 entry keyed 100 asks 'Offer unto me one X' and the type-5 entry keyed 100 consumes the crop and unregisters the actor (UnregisterEventActor(300, 100)). Corrected 2026-09-29: key 0 was read as an unresolved 'event kind'; it is the target's event key.",
    },
    6: {
        "name": "MapEnterScene",
        "summary": "Map-bank scene with no keys; every type-6 entry is walked and the last one runs.",
        "bank": "tail (slot 2)",
        "keys": [],
        "select": "last",
        "consumer": _KICK2,
        "matcher": "Scene_TickDispatchType6NpcEvent (RF4S.exe+0x1F2C00)",
        "confidence": "verified",
        "notes": "The scene of the map the player walks INTO (type 7 is the one of the map they left). Runs on entering the map: Scene_FinalizeMajorTransition (RF4S.exe+0x140ECC picks the area music first) calls Map_OnEnter_QueueMapEvents (+0x1EE7C0), which queues game event 24 with the map id; event 24 = Scene_TickDispatchType6NpcEvent (g_npcAiEventKindDispatchTable_34 +0x4DB680). The event runs on a later frame, so the scene starts after the music was picked; music changed by the scene comes back when it ends unless FLG_BGM_NOT_RETURN = 1. Corrected 2026-09-29: this note said handler 23 / the every-morning event (kind 23 is a different handler).",
    },
    7: {
        "name": "MapLeaveScene",
        "summary": "Map-bank scene of the map the player just LEFT, run as the next map loads; no keys, the first entry runs.",
        "bank": "tail (slot 2)",
        "keys": [],
        "select": "first",
        "consumer": _KICK2,
        "matcher": "Npc_TickScriptActionDispatch (RF4S.exe+0x1EEE10), wrapper at RF4S.exe+0x1F2E50 = handler 25",
        "confidence": "verified",
        "notes": "Map_OnEnter_QueueMapEvents (RF4S.exe+0x1EE7C0) first moves the previous map id into g_currentSceneTargetNpcId, then queues game event 25 (this type, handler RF4S.exe+0x1F2E50) before event 24 (type 6, the entered map). The handler loads the tail bank of g_currentSceneTargetNpcId -- the map that was LEFT -- and runs its first type-7 entry. Every shipped one (45) undoes something the map set up: boss rooms clear barrier flag 99, MAP_FIELD_25 restores the Night Stone's ambient colour, MAP_FIELD_27 resets the ten FLG_HUTAGO_* puzzle flags, MAP_CITY_06 closes the player's shop (MyShopAction 6). Corrected 2026-09-29: this type was named MapEnterScene and described as 'run on map entry, last entry wins, handler 24'.",
    },
    8: {
        "name": "DailyMorningReset",
        "summary": "Global scene run every morning (game event kind 12, queued when FLG_EVERY_MORNING_EXEC is set) that resets the daily flags.",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "first",
        "consumer": _APPLY0 + " on the scene context (flag 1 = step immediately)",
        "matcher": "NpcAi_ProbeMovementFromType8ActionOnSceneContext (RF4S.exe+0x1F3CC0), game event kind 12",
        "confidence": "verified",
        "notes": "Game event kind 12 is queued by NpcAi_PerFrameTick (around RF4S.exe+0x1F04C7) together with kind 23 (type 62) when FLG_EVERY_MORNING_EXEC is set. The single entry (PC 31360) clears the festival, boss-respawn and daily flags and rolls REG_DAY_RANDOM. Corrected 2026-09-29: this type was the placeholder GlobalScene8, numbered old handler number 11, one too low with an untraced queuer.",
    },
    9: {
        "name": "FishingCatch",
        "summary": "Global scene shown after a fish is caught; result buffer gets item id / catch info / new-catch flag.",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "last",
        "consumer": _APPLY0 + "; Fishing_ProcessCatch writes +64 item id, +68 catch info, +72 new-catch, +76/+80/+84 size flags",
        "matcher": "Fishing_ProcessCatch (RF4S.exe+0x1F39F0), game event kind 13",
        "confidence": "verified",
        "notes": "",
    },
    10: {
        "name": "MonsterTamed",
        "summary": "Global scene run after the player tames a monster (game event kind 9); it opens name entry for the new monster.",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "last",
        "consumer": _APPLY0,
        "matcher": "NpcAi_ProbeMovementFromType10Action (RF4S.exe+0x1F7160), game event kind 9",
        "confidence": "verified",
        "notes": "Game event kind 9 is queued only by MonsterFarm_OnTameSuccessQueueEvent (RF4S.exe+0x1F1450) after MonsterFarm_RegisterTamedMonster returns 2; its callers are MonsterTame_TickReactionAndFinalize (RF4S.exe+0x1DE8A0) and Script_VMOp_TameEventMonster (RF4S.exe+0x212FA0). The single entry (PC 33088) runs OpenMenu(51) = name entry for the monster just tamed. Corrected 2026-09-29: this type was the placeholder GlobalScene10, numbered old handler number 8, one too low.",
    },
    11: {
        "name": "BarnFullMessage",
        "summary": "Global-bank entry with no keys (PC 33106) whose scene says the barn is full or that there is no barn yet; no reader found, so what runs it is unknown.",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "unknown",
        "consumer": "unknown",
        "matcher": "none found: no caller of Npc_FindNextActionEntryOfType / Npc_ReadActionEntrySubBytes / Npc_ReadActionEntryId (nor Event_QueryByKindNpcAndStoryChapter) walks type 11, and no inline reader of the type-11 slot (count at table offset 0x2C, list offset at 0x2E) was found in RF4S.exe+0x1E0000..0x240000",
        "confidence": "unknown",
        "notes": "Named from the scene's text only: PC 33106 prints 'The barn is full.' or 'I don't have a barn yet.' depending on reg0. Corrected 2026-09-29: the old reader search looked for table offset 0x2E, which is the slot's list offset; its count is at 0x2C (4 * 11).",
    },
    13: {
        "name": "MonsterInteract",
        "summary": "Global scene for interacting with an ordinary monster/pet actor (id 0x30..0xFD) that is not a spawned event actor (event actors use type 2, keyed by their event key).",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "first",
        "consumer": _APPLY0 + " (NpcAi_TickOne clears actor flags 0x24 first)",
        "matcher": "NpcAi_TickOne (RF4S.exe+0x1F6930), game event kind 4",
        "confidence": "verified",
        "notes": "Gated by the monster's map id (actor +0x54) equal to the player's (Player_GetActor at RF4S.exe+0x1F6981, compare at RF4S.exe+0x1F6B02): the monster must be on the player's map. The single entry (PC 31924) is the tamed-monster menu (take along / field chores / change name / send back). Corrected 2026-09-29: the gate was read as actor +84 against an unidentified second actor.",
    },
    15: {
        "name": "WarpArrivalScene",
        "summary": "Scene run after a scripted warp lands on its map, keyed by the event number the WarpToMap op passed.",
        "bank": "slot 1 (the active sub-event bank for mode 1, the story bank for mode 2) or slot 2 (the arrival map's tail bank, mode 0)",
        "keys": [
            {"index": "0+", "name": "warp_event", "meaning": "the WarpToMap op's event number (npc_event_ctx u16 +66, cleared after use); 1000..1099 = mode 1 (slot 1, sub-event bank), 100..999 = mode 2 (slot 1 only), any other value = mode 0 (tail bank)", "wildcard": False},
        ],
        "select": "first",
        "consumer": "mode 0: " + _KICK2 + "; modes 1/2: " + _APPLY1 + " (mode 1 also flags both companions)",
        "matcher": "Event_QueryFollowupByPrevId (RF4S.exe+0x220EF0) from NpcAi_OnPostCutsceneFade_DispatchFollowupEvent (RF4S.exe+0x1F31F0), game event kind 28",
        "confidence": "verified",
        "notes": "ctx+66 is written only by the WarpToMap op (RF4S.exe+0x20AC90), which also sets the mode byte ctx+57 (1 for 1000..1099, 2 for 100..999, else 0); Map_OnEnter_QueueMapEvents (RF4S.exe+0x1EEAFC) queues game event kind 28 when ctx+66 is non-zero. Corpus: sub-event banks use 1000..1099 (165 entries), story banks 100..999 (115), tail banks other numbers (48); the 25 tail-bank entries keyed 100..999 are unreachable (mode 2 probes slot 1 only). Corrected 2026-09-29: this type was named FollowupByPrevId and read as a follow-up keyed by the finished scene's id, old handler number 27, one too low.",
    },
    16: {
        "name": "RevivalReaction",
        "summary": "Map scene after the player is revived (KO); last entry wins, companions are teleported.",
        "bank": "tail (slot 2)",
        "keys": [],
        "select": "last",
        "consumer": _KICK2 + "; then both companion actors are moved to the respawn spot",
        "matcher": "OnRevival_DispatchNpcReactionAndTeleportCompanions (RF4S.exe+0x1F37E0), game event kind 3",
        "confidence": "verified",
        "notes": "Only tail bank 132 has one.",
    },
    17: {
        "name": "MonsterDefeatedScene",
        "summary": "Map scene run 72 frames after a monster is defeated on the map, chosen by (monster id, em condition) pairs.",
        "bank": "tail (slot 2)",
        "keys": [
            {"index": "0+", "name": "pair", "meaning": "even index k: monster id compared with descriptor word[1] (the defeated monster's id); odd index k+1: em.bin condition for that key (-1 = always). A -1 key is a default that keeps scanning the entry for an exact key", "wildcard": True},
        ],
        "select": "first",
        "consumer": _KICK2 + "; NpcAi_BeginScriptedEventFromRequestDescriptor stores descriptor words 3/2 into ctx+112/+114",
        "matcher": "NpcAi_ResolveActionEntryType17 (RF4S.exe+0x222190) from NpcAi_BeginScriptedEventFromRequestDescriptor (RF4S.exe+0x1F2040), game event kind 1",
        "confidence": "verified",
        "notes": "Reward_LogActorEventAndAwardPP (RF4S.exe+0x1F1330, called on defeat / tame) fills a 16-slot ring at ctx+672 {actor id, delay 72 frames (0 when FLG_DEFEAT_TIME_0), x, y}; Quest_TickDailyTimersAndQueueEvents (RF4S.exe+0x1FA420) counts each slot down and queues game event kind 15 (type 37) then kind 1 (this type) with word 1 = the monster id. Corpus keys 104..249 are monster ids; e.g. tail bank 272 key 228 sets FLG_DUNG_A_BOSS_RE and clears flag 99. Corrected 2026-09-29: this type was named RequestedScene (old handler number 0, one too low) and its keys were read as untraced request keys.",
    },
    19: {
        "name": "FirstMeetingTalk",
        "summary": "Villager introduction line run the first time the player talks to the NPC (once REG_MAIN_SCENARIO is past 39).",
        "bank": "primary: canonical char id",
        "keys": [],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "NpcAi_ResolveVillagerBehavior (RF4S.exe+0x1F7E00), direct Npc_FindNextActionEntryOfType call at RF4S.exe+0x1F8250",
        "confidence": "verified",
        "notes": "Gate at RF4S.exe+0x1F815D: !Npc_IsMetFlagSet(id) (RF4S.exe+0x2271B0, zone-2 met bit 981 + id; the children go through g_guestNpcStateTable) and REG_MAIN_SCENARIO > 39; the branch then sets met bit 981 + id and also grants the daily first-talk bonus. Bank 4's entry is Forte's introduction ('I feel an unfamiliar presence'). Corrected 2026-09-29: this type was named AbsentTalk and read as 'the NPC is not in the current area' (the met-bit test carried the IDB name Npc_IsInCurrentArea).",
    },
    20: {
        "name": "AccompanyingTalk",
        "summary": "Line of an NPC that is accompanying the player (actor flag 0x200: party member or date), used when the player talks to it and nothing more specific matched.",
        "bank": "primary: canonical char id",
        "keys": [],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "Npc_FindNextActionOperand_FromSubList80_Type20 (RF4S.exe+0x221050) from NpcAi_ResolveVillagerBehavior",
        "confidence": "likely",
        "notes": "Reached only when actor +16 & 0x200 is set (the guest branch and the villager fallback in NpcAi_ResolveVillagerBehavior). Bank 4 says 'I will protect you' / 'invite me again'; bank 24 finishes a date (EV_DATE_FINISH, SetNpcDateState). The setter of the 0x200 flag was not located, so 'accompanying' is read from the scenes. Corrected 2026-09-29: this type was named DefaultTalk and read as a general fallback line also used by the busy/quest fallbacks.",
    },
    21: {
        "name": "CompanionLeavesParty",
        "summary": "Scene in which a companion takes its leave for the evening and leaves the party (game event kind 2, queued at 19:00).",
        "bank": "primary: canonical id of the descriptor's char id (word +2)",
        "keys": [],
        "select": "last",
        "consumer": _APPLY1 + " (mode 1, step immediately)",
        "matcher": "NpcAi_TryApplyFollowMovementIfNoActiveBlockers (RF4S.exe+0x1F2190), game event kind 2",
        "confidence": "verified",
        "notes": "Game event kind 2 is queued by CompanionParty_QueueLeaveEvent (RF4S.exe+0x1F5400), called from Calendar_TimeAdvance (RF4S.exe+0x85630) when the hour crosses 19 for each companion slot that is not the spouse and has friendship < 7, and from DailyRequest_QueueTomorrowVisitor (RF4S.exe+0x1EDAB0); it runs only when REG_SUBEV_NOW == 0. Bank 1's scene: 'as I have work to do tomorrow, I shall take my leave' + DismissCompanionByCharId(1). Skipped while a kill aggregate or calendar event has state bit 0x800, while the player is being thrown, or at story flag 248. Corrected 2026-09-29: this type was named FollowPlayer and read as a 'follow the player' scene (old handler number 1, one too low).",
    },
    22: {
        "name": "DailyGreeting",
        "summary": "First-talk-of-the-day greeting chosen by time of day (0 = 06-09h, 1 = 10-17h, 2 = otherwise).",
        "bank": "primary: 224 + canonical char id",
        "keys": [
            {"index": "0+", "name": "timeslot", "meaning": "0 morning (calendar hour 6..9), 1 daytime (10..17), 2 evening/night", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + "; Npc_SetDailyGreetingDone(id) marks the greeting as done and scene flag 0x200 is set",
        "matcher": "Npc_FindActionOperand_FromSubList88_Type22_WithSubBytePredicate (RF4S.exe+0x221290) from NpcAi_ResolveVillagerBehavior step 0",
        "confidence": "verified",
        "notes": "Every villager second bank (225..247) has exactly the keys 0, 1, 2.",
    },
    23: {
        "name": "FestivalTalkBefore",
        "summary": "Festival line before the festival opens (REG_FES_STATUS 0); key = festival id.",
        "bank": "primary: the NPC's own bank (slot 1) - or slot 2 (map bank) from NpcAi_PerFrameTick",
        "keys": [
            {"index": "0+", "name": "festival", "meaning": "festival id: REG_FESTA (5-bit) when a festival is pending, else Calendar_LookupEventBySeasonAndDay for tomorrow after 06:00", "wildcard": False},
        ],
        "select": "first",
        "consumer": _APPLY1 + " (NpcAi_PerFrameTick variant: slot 2 with key = byte 5 of the qword at RF4S.exe+0xE3CBB0)",
        "matcher": "NpcActionEntry_ResolveForFestivalPhase (RF4S.exe+0x221400) from Npc_DispatchPendingOrDateGatedEvent (RF4S.exe+0x1F94E0)",
        "confidence": "verified",
        "notes": "Type = 23 + phase. The phase comes from GF_REG_FES_STATUS (2 bits) or scene byte +533 >> 4 when its bit 3 is set: 0 = before the opening hour, 1 = running, 2 = over (NpcAi_PerFrameTick writes 1 and 2), 3 = the eve (Npc_DispatchPendingOrDateGatedEvent writes 3 at RF4S.exe+0x1F95D4 before it looks up tomorrow's festival). Corrected 2026-09-29: types 23..26 were named FestivalTalk0..3 without the meaning of the phases.",
    },
    27: {
        "name": "SubEventReaction",
        "summary": "Sub-event / quest reaction matched by (priority, char id), 0 in the char list meaning the spouse; the two global-bank entries are the request-completed banners.",
        "bank": "primary: sub-event bank (REG_SUBEV_NOW, Npc_GetCurrentQuestId or 210), or the global bank for the request-completed banner (game event kind 10)",
        "keys": [
            {"index": 0, "name": "priority", "meaning": "reaction priority/kind 0..3 (Quest_GetGeneralReceivingPriorityByEntry, 2 = gift priority, reward event id, 3 = SUBEV_AFTER/QUEST_AFTER); -1 = matches regardless of the char list", "wildcard": True},
            {"index": "1+", "name": "npc", "meaning": "char id list (tag 3); 0 is replaced by REG_WIFE_ID when the caller passes a non-zero bank SLOT argument; 23 (Daughter) is remapped to 22", "wildcard": False},
        ],
        "select": "first",
        "consumer": _APPLY1 + "; the global variant's handler (game event kind 10) also plays SFX 0x100226D and calls Combat_ApplyAttackEntry(player, 0xAC)",
        "matcher": "NpcActionEntry_ResolveByKeyPairWithWifeId (RF4S.exe+0x2216C0) via Event_QueryGiftReactionByPriority (RF4S.exe+0x2215D0), Subev_ResolveActiveForNpcReaction (RF4S.exe+0x1FA750), NpcAi_ResolveMonsterBehavior (bank 210, key2 = 210) and NpcAi_ProbeAndTriggerScriptedAttackOnPlayerType27 (RF4S.exe+0x1F7270, game event kind 10, global bank, key1 = descriptor word +2, key2 = 0)",
        "confidence": "verified",
        "notes": "Match rule: (sub0 == priority and any sub_i == char) or sub0 == -1. Corpus: 1034 entries in 152 sub-event banks (48..) plus 2 in the global bank: 'Request Completed!' (key 0 = 0) and 'Event Cleared!' (key 0 = 1). Game event kind 10 is queued by Quest_OnComplete (RF4S.exe+0x218060) with word 1 = 0. Corrected 2026-09-29: the global variant was read as a scripted attack on the player (it is the completion banner), and the spouse substitution is switched by the bank slot argument, not the bank index.",
    },
    28: {
        "name": "SubEventNpcLine",
        "summary": "Sub-event line of an NPC that is accompanying the player, keyed by its canonical char id.",
        "bank": "primary: sub-event bank (loaded by NpcAi_CheckThrownItemFallbackCondition = REG_SUBEV_NOW)",
        "keys": [
            {"index": 0, "name": "npc", "meaning": "canonical char id of the NPC (tag 3)", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + " (sets g_sceneAuxControlFlags 0x1000)",
        "matcher": "Npc_PredicateMatchSubBytesAndCommitEventId (RF4S.exe+0x2202B0) via Event_QueryByKindNpcAndStoryChapter(kind 0x1C) (RF4S.exe+0x222AB0), call site RF4S.exe+0x1F8618",
        "confidence": "verified",
        "notes": "Expected key list is [char id, 0]; entries have one key. Only queried when the talking NPC has actor flag 0x200 (accompanying the player), so it is the companion's sub-event line (e.g. 'Let's head to the lake together'). Corrected 2026-09-29: the summary did not say the lookup needs the 0x200 flag.",
    },
    30: {
        "name": "StoryProgressTalk",
        "summary": "Villager line gated by a main-scenario range [lo, hi]; friendship word +6 remembers the last fired hi, but an equal hi still passes, so the same range can fire again.",
        "bank": "primary: 224 + canonical char id",
        "keys": [
            {"index": 0, "name": "chapter_lo", "meaning": "lowest REG_MAIN_SCENARIO value (9-bit) that matches", "wildcard": False},
            {"index": 1, "name": "chapter_hi", "meaning": "highest matching value (0 = same as lo); also must be >= the NPC's last fired hi (equal passes)", "wildcard": False},
        ],
        "select": "first",
        "consumer": _APPLY1 + "; sets friendship flag 0x10000000 and stores hi into the entry's word +6",
        "matcher": "NpcAi_FindActionEntryOfType30GatedByFlagAndNpcStat (RF4S.exe+0x221820)",
        "confidence": "likely",
        "notes": "Corrected 2026-09-29: this was described as firing once per range; the gate at RF4S.exe+0x221820 is last_hi <= hi, so the same range passes again. No reader of the friendship flag 0x10000000 was found, so whether something else stops a repeat is unresolved.",
    },
    31: {
        "name": "DateTalk",
        "summary": "Line for a calendar date: absolute day-of-year, or n-1 days before a festival.",
        "bank": "primary: canonical char id",
        "keys": [
            {"index": "0+", "name": "date", "meaning": "value <= 120: day-of-year = day + 30*season compared with today; value > 120: (n << 8) | festival_id means (n-1) days before that festival (dates from archive 16340, with the >90/<=30 year-wrap rule); -1 is read unsigned (> 120, festival branch) and never matches", "wildcard": False},
        ],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "the unnamed function at RF4S.exe+0x221D20, from NpcAi_ResolveVillagerBehavior step 10 (call RF4S.exe+0x1F901E)",
        "confidence": "verified",
        "notes": "Corpus: 29/59/89/116 = season ends, 257.. = festival day, 513.. = the day before. Corrected 2026-09-29: -1 was listed as a wildcard; the compare is unsigned, so -1 takes the festival branch and can never match.",
    },
    32: {
        "name": "TalkLineTier1",
        "summary": "Regular talk line, relationship tier 1 (acquaintance); key = per-NPC line index.",
        "bank": "primary: 224 + canonical char id (NpcAi_ResolveVillagerBehavior reloads slot 1 with v7 + 224 at RF4S.exe+0x1F933B right before the lookup)",
        "keys": [
            {"index": "0+", "name": "line", "meaning": "line index = (Npc_ComputeRelationshipTier key) & 0x7F, i.e. the talk counter in byte +16 of the NPC's friendship entry", "wildcard": False},
        ],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "Npc_FindTalkLineEventByTierKey (RF4S.exe+0x222020); tier from Npc_ComputeRelationshipTier (RF4S.exe+0x228CE0): type = 32 + tier - 1",
        "confidence": "verified",
        "notes": "Tier 2 = friendship level > 3 and stage bits >= 0x100, tier 3 = flag 0x400000 (dating), tier 4 = REG_WIFE_ID == id; when the player is married to anyone (REG_WIFE_ID != 0) and the tier lookup missed, type 36 is probed with key 640 (absent from the corpus). Types 34/35 also exist as empty stubs in the banks of Volkanon, Blossom, Ventuswill and the children, among others. Corrected 2026-09-29: the counter was attributed to the actor; it is byte +16 of the friendship entry.",
    },
    37: {
        "name": "QuestProgressReaction",
        "summary": "Global scene when a monster defeat advances a kill-count request: progress milestone (1) or completed (2).",
        "bank": "global (slot 0)",
        "keys": [
            {"index": "0+", "name": "milestone", "meaning": "1 = progress milestone (count 1 or a multiple of 5), 2 = completed (Quest_LookupRewardEventIdByTemplateId)", "wildcard": False},
        ],
        "select": "first",
        "consumer": _APPLY0 + "; result buffer +64 template id, +68 progress, +72 remaining",
        "matcher": "NpcAi_AdvanceQuestProgressAndScheduleReaction (RF4S.exe+0x1F23F0), game event kind 15",
        "confidence": "verified",
        "notes": "Game event kind 15 is queued by Quest_TickDailyTimersAndQueueEvents (RF4S.exe+0x1FA420) 72 frames after Reward_LogActorEventAndAwardPP logged the defeat (the same ring also queues kind 1 = type 17), with word 1 = the monster id; the handler advances the kill-count requests for that monster. Scenes: \"That's N of 'em\" / \"That's all N\". Corrected 2026-09-29: the trigger was not recorded and the handler was numbered 14.",
    },
    38: {
        "name": "ItemReceiptReaction",
        "summary": "Quest/general item-receipt reaction keyed by the receiving NPC's char id.",
        "bank": "primary: when ctx+116 & 0x30 == 0x10 the requester's quest bank (Npc_GetCurrentQuestId) or 210 when it has none; otherwise (0x20) the REG_SUBEV_NOW sub-event bank",
        "keys": [
            {"index": "0+", "name": "npc", "meaning": "char id of the NPC that received the item (tag 3)", "wildcard": True},
        ],
        "select": "first",
        "consumer": "NpcAi_OnReceivedThrownItem_AdvanceProgressAndDispatchReaction (RF4S.exe+0x1F1730): consumes the gift units, then " + _APPLY1,
        "matcher": "Event_QueryGeneralReactionByPriority (RF4S.exe+0x2223A0)",
        "confidence": "verified",
        "notes": "Used when the receiving priority is not 2 (priority 2 goes to type 27). Bank 210 holds one entry per villager 1..23. The bank is chosen in NpcAi_OnReceivedThrownItem_AdvanceProgressAndDispatchReaction (RF4S.exe+0x1F1730, game event kind 5) from the reaction-style bits ctx+116 & 0x30. Corrected 2026-09-29: the bank was given as the quest bank or 210 only; with style 0x20 it is the REG_SUBEV_NOW bank.",
    },
    39: {
        "name": "SubEventMapScene",
        "summary": "Sub-event scene run when the player enters a map, keyed by the entered map id.",
        "bank": "primary: REG_SUBEV_NOW (or REG_SUBEV_RSV when DATE_MAP is clear)",
        "keys": [
            {"index": 0, "name": "map", "meaning": "id of the ENTERED map (tag 4): Map_OnEnter_QueueMapEvents queues game event kind 20 with the entered map (RF4S.exe+0x1EEBF8), read back from the event descriptor word +2", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + " (mode 1, step immediately)",
        "matcher": "Npc_PredicateMatchSubBytesAndCommitEventId via Event_QueryByKindNpcAndStoryChapter(kind 0x27) from NpcAi_TryApplyMovementFromStoryFlagAndEventQuery (RF4S.exe+0x1F2940), game event kind 20",
        "confidence": "verified",
        "notes": "Descriptor word +6 must be 0. Corrected 2026-09-29: the handler was numbered 19 and the summary did not say which map (the entered one) the key is compared with.",
    },
    40: {
        "name": "SubEventMapLeaveScene",
        "summary": "Sub-event scene run when the player leaves a map, keyed by the map that was left; sets ctx flag 0x400 before running.",
        "bank": "primary: REG_SUBEV_NOW",
        "keys": [
            {"index": 0, "name": "map", "meaning": "id of the map just LEFT (tag 4): Map_OnEnter_QueueMapEvents queues game event kind 21 with g_currentSceneTargetNpcId = the previous map (RF4S.exe+0x1EEA89), read back from the event descriptor word +2", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + " (mode 1, step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x28) from NpcAi_ProbeMovementFromEventKind40_SetBit400_GatedByRequestor (RF4S.exe+0x1F3430), game event kind 21",
        "confidence": "verified",
        "notes": "Corrected 2026-09-29: this type was named SubEventMapSceneB and described as a map-ENTRY scene (old handler number 20, one too low); kind 21 carries the previous map (set at RF4S.exe+0x1EE8C7), not the entered one.",
    },
    43: {
        "name": "SwimsuitTalk",
        "summary": "Villager line for when the player wears a swimsuit in summer, one of three variants chosen by the day of the season.",
        "bank": "primary: canonical char id",
        "keys": [
            {"index": 0, "name": "variant", "meaning": "day of the season % 3 (dword +12 of the calendar struct at g_calendarTask+176)", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "Npc_PredicateMatchSubBytesAndCommitEventId at RF4S.exe+0x1F911E (NpcAi_ResolveVillagerBehavior step 11); gate: the season getter at RF4S.exe+0x19C2F0 (calendar struct +16) == 1 (summer) and actor +488 == 2 (outfit)",
        "confidence": "likely",
        "notes": "The lines are about the player's swimsuit ('You look lovely in that swimsuit'), so actor +488 == 2 is read as the swimsuit outfit from the dialogue; the writer was not traced. Corrected 2026-09-29: this type was named SummerVariantTalk with the +176 struct and actor +488 unresolved.",
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
        "bank": "primary: canonical char id (the copies in the villagers' second banks are never loaded for this lookup)",
        "keys": [
            {"index": "0+", "name": "condition", "meaning": "em.bin named condition id; -1 is NOT a default: CondScript_EvalNamedConditionA (RF4S.exe+0x23B6A0) bounds-checks the id unsigned and returns false", "wildcard": False},
        ],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "NpcAi_ResolveActionEntryType45 (RF4S.exe+0x221BB0) from NpcAi_TickOne (RF4S.exe+0x1F6930, event participants) and NpcAi_ResolveVillagerBehavior step 2",
        "confidence": "verified",
        "notes": "The 46 entries keyed only -1 (banks 1..23 and 225..247) never fire. Both readers load the NPC's canonical-id bank, so the banks 225..247 are never in slot 1 for a type-45 query. Corrected 2026-09-29: -1 was treated as a default, and the villager second banks (224 + id) were listed as a bank this type is read from.",
    },
    46: {
        "name": "InviteMenuTalk",
        "summary": "Scene run for the NPC the player is talking to when the player opens the invite menu (go out together / date / festival date).",
        "bank": "primary: canonical id of g_currentInteractionNpc",
        "keys": [],
        "select": "first",
        "consumer": _APPLY1 + " on the scene context (mode 1, step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 46 + ((g_sceneControlFlags >> 21) & 1)) at RF4S.exe+0x1F08CA in NpcAi_PerFrameTick",
        "confidence": "likely",
        "notes": "Size-0 entries commit unconditionally in Npc_PredicateMatchSubBytesAndCommitEventId. Run when scene control bit 0x100000 is set with bit 21 clear; bit 21 (0x200000) selects type 47 instead. The meaning is read from the scenes (the invite menu with its go-out / date / festival-date choices). Corrected 2026-09-29: this type was named InteractionScene46 with the control bits unresolved.",
    },
    48: {
        "name": "GlobalScene48",
        "summary": "Global-bank scene, no keys, last entry.",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "last",
        "consumer": _APPLY0 + " (step immediately)",
        "matcher": "NpcAi_ProbeAndApplyMovementFromType48Action (RF4S.exe+0x1F7050), game event kind 8",
        "confidence": "verified",
        "notes": "Single entry at PC 34020: the greeting reminder ('Gotta start off on the right foot with a proper greeting.'). What queues game event kind 8 was not found.",
    },
    49: {
        "name": "RecipeBreadLearned",
        "summary": "Global scene run after the player eats a recipe bread, saying which recipe was learned (or that none was).",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "last",
        "consumer": _APPLY0 + "; +64 = item id, +68 = recipe category (archives 14826..14847)",
        "matcher": "Player_OnEatFood_LoadAnimAndBindRecipeCategory (RF4S.exe+0x1F6C10), game event kind 6",
        "confidence": "verified",
        "notes": "Game event kind 6 is queued by Item_UseOnActor. The scene only covers recipe-bread results ('I can cook X now' / 'didn't learn anything'). Corrected 2026-09-29: this type was named EatFood (too broad) with old handler number 5, one too low.",
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
        "consumer": "NpcAi_OnReceivedThrownItem_AdvanceProgressAndDispatchReaction (RF4S.exe+0x1F1730): " + _APPLY1 + "; Throw_DispatchToNpcWithQuestGiftCheck (RF4S.exe+0x1F0E90) uses the same query with a5 = 0 as an 'interesting item' probe",
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
        "name": "SkillMoveOrPortalNotice",
        "summary": "Global message scene keyed by a code: a weapon skill reaching level 5/10/20 (a new move learned) or the player stepping on a grown dungeon-portal tile.",
        "bank": "global (slot 0)",
        "keys": [
            {"index": 0, "name": "code", "meaning": "descriptor byte +2, queued by Skill_OnRankUnlock (RF4S.exe+0x1F5E50): 4 * skill + 1/2/4 when weapon skill 0..5 reaches level 5/10/20 (from Player_gainEXP), 25..27 from Player_TickFieldInteraction (RF4S.exe+0x167531) for a grown dungeon-portal tile (sub 0x55); code 3 is a bare RET", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY0 + " (step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x35) from NpcAi_ProbeMovementFromEventKind53 (RF4S.exe+0x1F73A0), game event kind 11",
        "confidence": "verified",
        "notes": "Weapon codes print 'learned a Short Sword Dash attack'-style messages; codes 25..27 ask 'sound like monkey... Go in?' and warp with WarpToMap 442. Corrected 2026-09-29: this type was named GlobalRequestKind with the codes unresolved (old handler number 10, one too low).",
    },
    54: {
        "name": "SoilInspectMessage",
        "summary": "Global message scene that reports a field tile's soil quality, fatigue, crop item and level.",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "last",
        "consumer": _APPLY0 + "; result buffer +64 = 445 + ctx byte +323 (soil-quality name), +68 = 451 + ctx byte +324 (fatigue name), +72 = ctx byte +326 (item), +76 = ctx byte +325 (level)",
        "matcher": "GameEvent_RunSoilInspectScene (RF4S.exe+0x1F2780), game event kind 16",
        "confidence": "verified",
        "notes": "The single scene (global PC 0x89B4) prints reg0 (char names 445..450 = 'Soil quality: Good / Normal / Bad / Very Bad / Very Good / Superior'), reg1 (451.. = 'Fatigue: Low / Medium / High'), the item reg2 and the level reg3; nothing walks. What queues game event kind 16 was not found. Corrected 2026-09-29: this type was named WalkToTarget and read as walking the NPC to tile coordinates (old handler number 15, one too low).",
    },
    56: {
        "name": "PrologueTutorialPrompt",
        "summary": "Prologue tutorial prompt ('I need to equip this' / 'Press X to eat Y') run while the story flag is 9.",
        "bank": "primary: story bank 211+ (NpcAi_CheckSpecialEventCondition)",
        "keys": [
            {"index": 0, "name": "ctx329", "meaning": "npc_event_ctx byte +329 (0 in the corpus)", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + " (mode 1, step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 56 + descriptor byte +2) from NpcAi_ProbeMovementFromEventKindByPredicate (RF4S.exe+0x1F73F0), game event kind 18",
        "confidence": "likely",
        "notes": "Game event kind 18 is queued while the story flag == 9 (prologue) by Inventory_OnContextMenuConfirm, Player_ProcessInput, Quest_QueueDailyVisitReminderEvent (descriptor byte = a1 != 10) and Player_TickConsumeHeldItemAndApplyEffect (0x10012, byte 1 -> type 57). Only story bank 211 has types 56 and 57 (one entry each). Corrected 2026-09-29: types 56/57 were named SpecialEventKind56/57 (old handler number 17, one too low).",
    },
    60: {
        "name": "DailyTopicTalk",
        "summary": "Villager line about today's randomly rolled topic (1..10); marked done per topic.",
        "bank": "primary: 224 + canonical char id",
        "keys": [
            {"index": 0, "name": "topic", "meaning": "low byte of the qword at RF4S.exe+0xE9B308, rolled daily by Day_UpdateNpcDailyFlags (RF4S.exe+0x227AE0); topic 10 additionally needs EMFE_SYELZA_READY", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + "; done-bit (1 << (topic-1)) set in the same qword",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x3C) at RF4S.exe+0x1F929D (NpcAi_ResolveVillagerBehavior step 13)",
        "confidence": "likely",
        "notes": "Each villager second bank has the keys 1..10.",
    },
    62: {
        "name": "SubEventMorningScene",
        "summary": "Key-less scene of the active sub-event bank run every morning (game event kind 23, queued together with the daily reset).",
        "bank": "primary: REG_SUBEV_NOW",
        "keys": [],
        "select": "first",
        "consumer": _APPLY1 + " (mode 1, step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x3E) from NpcAi_ProbeMovementFromEventKind62_GatedByCurrentRequestor (RF4S.exe+0x1F2B50), game event kind 23",
        "confidence": "verified",
        "notes": "Game event kind 23 is queued daily by NpcAi_PerFrameTick when FLG_EVERY_MORNING_EXEC is set, right after kind 12 (type 8). Sample: primary bank 48's entry (pc 0x1bc) advances the sub-event step and rewrites an NPC schedule. Corrected 2026-09-29: this type was named SubEventDefault without its trigger (old handler number 22, one too low).",
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
        "matcher": "NpcActionEntry_ParseAndAppendKind3WithWifeId (RF4S.exe+0x222F90) from Npc_CollectTalkDialogueEntries (RF4S.exe+0x220A90)",
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
        "matcher": "Npc_DialogueEntryCollect_PushIfTriggerMatchesAndScanConditionBits (RF4S.exe+0x220870) from Npc_CollectTalkDialogueEntries (RF4S.exe+0x220A90)",
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
        "matcher": "NpcActionEntry_ParseAndAppendIfSubevActive (RF4S.exe+0x222D30) from Npc_CollectTalkDialogueEntries (RF4S.exe+0x220A90)",
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
        "matcher": "Event_QueryByNpcAndPriority (RF4S.exe+0x222BB0) from NpcAi_TickEventPriorityCascade (RF4S.exe+0x1F2E60), game event kind 26",
        "confidence": "verified",
        "notes": "Not a caller of Npc_FindNextActionEntryOfType (walks through Npc_ReadActionEntrySubBytes). Corpus flags 29122/32768/400 etc., maps 160 Airship, 272 Yokmir Forest ...",
    },
    69: {
        "name": "StoryMapScene",
        "summary": "Story scene run when the player enters a map at a main-scenario chapter, looked up in the chapter's story bank (special-event condition must hold).",
        "bank": "primary: the chapter's story bank 211+, loaded by NpcAi_CheckSpecialEventCondition (RF4S.exe+0x1FEAB0) right before the query (copies in map banks are never read)",
        "keys": [
            {"index": 0, "name": "map", "meaning": "id of the ENTERED map (tag 4): Map_OnEnter_QueueMapEvents queues game event kind 30 with the entered map, read back from the event descriptor word +2", "wildcard": True},
            {"index": 1, "name": "chapter", "meaning": "REG_MAIN_SCENARIO (9-bit) value", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1 + " (mode 1, step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x45) from NpcAi_EventKind30_ApplyChapterEventMovement (RF4S.exe+0x1F34F0), game event kind 30",
        "confidence": "verified",
        "notes": "The tail-bank copies in the corpus are unreachable: the reader queries slot 1 only. Corrected 2026-09-29: the bank was given as 'whatever slot 1 holds, or tail' and the handler was numbered 29.",
    },
    70: {
        "name": "StoryMapLeaveScene",
        "summary": "Story scene run when the player leaves a map, keyed by the map that was left and the chapter, looked up in the chapter's story bank (211 + threshold index).",
        "bank": "primary: the chapter's story bank (211 + the index picked by g_storyChapterToEventActionIdThresholds_14u32)",
        "keys": [
            {"index": 0, "name": "map", "meaning": "id of the map just LEFT (tag 4): game event kind 31 is queued with g_currentSceneTargetNpcId = the previous map (RF4S.exe+0x1EEAA1), read back from the event descriptor word +2", "wildcard": True},
            {"index": 1, "name": "chapter", "meaning": "REG_MAIN_SCENARIO value", "wildcard": True},
        ],
        "select": "first",
        "consumer": "direct state-machine kick with bank slot 1 (NpcAi_CheckAndDispatchStoryEventByChapter validates ctx+8->+24->+208)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x46) from NpcAi_CheckAndDispatchStoryEventByChapter (RF4S.exe+0x1F3590), game event kind 31",
        "confidence": "verified",
        "notes": "Corpus maps: 309 Obsidian Mansion, 160 Airship, 347 Leon Karnak, 348 Floating Empire. The copies in tail bank 347 are unreachable (the query uses slot 1 only). Corrected 2026-09-29: this type was named StoryMapEnterScene and read as keyed by the entered map (old handler number 30, one too low); kind 31 carries the previous map.",
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
        "matcher": "inline loop in Map_OnEnter_QueueMapEvents (RF4S.exe+0x1EE7C0, reads at RF4S.exe+0x1EECB0..0x1EEDBE)",
        "confidence": "likely",
        "notes": "Key 0 is compared with the entered map; queued at RF4S.exe+0x1F0A92. The tail-bank copy in the corpus is unreachable (the reader uses slot 1 only). Corrected 2026-09-29: the unreachable tail copy was not noted.",
    },
    72: {
        "name": "StoryChapterTalk",
        "summary": "Story-bank line keyed by (char id, main-scenario chapter).",
        "bank": "primary: the chapter's story bank 211+, loaded by NpcAi_CheckSpecialEventCondition right before the query (copies in map banks are never read)",
        "keys": [
            {"index": 0, "name": "npc", "meaning": "char id of the talking NPC", "wildcard": True},
            {"index": 1, "name": "chapter", "meaning": "REG_MAIN_SCENARIO value", "wildcard": True},
        ],
        "select": "first",
        "consumer": _APPLY1,
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x48) at RF4S.exe+0x1F800E and RF4S.exe+0x1F89AD in NpcAi_ResolveVillagerBehavior",
        "confidence": "verified",
        "notes": "Corpus: banks 211..222 plus 3 tail banks; e.g. bank 211 has (3 Volkanon, chapters 4/5/6/8). The tail-bank copies are unreachable (the lookups use slot 1 only). Corrected 2026-09-29: the bank was given as 'whatever slot 1 holds'; both call sites load the chapter's story bank first.",
    },
    73: {
        "name": "FurnitureLimitPrompt",
        "summary": "Global prompt shown when the player tries to place a piece of furniture while 16 or more are already placed ('can't fit any more furniture... return this?').",
        "bank": "global (slot 0)",
        "keys": [],
        "select": "first",
        "consumer": _APPLY0 + " (step immediately)",
        "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x49) from NpcAi_ProbeMovementFromEventKind73 (RF4S.exe+0x1F33E0), game event kind 29",
        "confidence": "verified",
        "notes": "Game event kind 29 is queued by Player_TickThrowAction_BranchOnHeldFlagsAndScene (RF4S.exe+0x1729A7) when the held flags have 0x200000 and TileObject_CountActiveInContext(-1, 0) >= 16 (plus SFX 0x1002241). The scene (global PC 0x8AF0) ends in CommitGrabbedObject. Corrected 2026-09-29: this type was the placeholder GlobalScene73, said to be queued as kind 28 by the map-entry cascade (kind 28 is the warp-arrival event of type 15).",
    },
}

# Types that share a matcher with a catalogued sibling: copy and adjust.
def _sibling(src, name, summary, **over):
    d = dict(ENTRY_TYPES[src])
    d["keys"] = [dict(k) for k in d["keys"]]
    d.update({"name": name, "summary": summary})
    d.update(over)
    return d

ENTRY_TYPES[24] = _sibling(23, "FestivalTalkDuring", "Festival line while the festival is running (REG_FES_STATUS 1); key = festival id.")
ENTRY_TYPES[25] = _sibling(23, "FestivalTalkAfter", "Festival line after the festival is over (REG_FES_STATUS 2); key = festival id.")
ENTRY_TYPES[26] = _sibling(23, "FestivalTalkEve", "Festival line on the eve of a festival (REG_FES_STATUS 3, set while tomorrow's festival is looked up); key = festival id.")
ENTRY_TYPES[33] = _sibling(32, "TalkLineTier2", "Regular talk line, relationship tier 2 (friend); key = per-NPC line index.")
ENTRY_TYPES[34] = _sibling(32, "TalkLineTier3", "Regular talk line, relationship tier 3 (lover); key = per-NPC line index.")
ENTRY_TYPES[35] = _sibling(32, "TalkLineTier4", "Regular talk line, relationship tier 4 (spouse); key = per-NPC line index.")
ENTRY_TYPES[36] = _sibling(32, "TalkLineSpouseExtra", "Extra line list probed with key 640 ((5<<7)|0, line 0) whenever the player is married and the tier lookup missed; absent from the shipped corpus.",
                            confidence="likely", notes="Code-only: Npc_FindTalkLineEventByTierKey(key 0x280) at RF4S.exe+0x1F9419, probed whenever REG_WIFE_ID != 0 (married to anyone, not only to this NPC) and the tier lookup missed; line key 0. Corrected 2026-09-29: this was described as spouse-only.")
ENTRY_TYPES[47] = _sibling(46, "NpcJoinOfferTalk", "Scene in which the NPC the player is talking to offers to join the party (run when scene control bit 21, 0x200000, is set).",
                            notes="Size-0 entries commit unconditionally in Npc_PredicateMatchSubBytesAndCommitEventId. Bank 1's scene: 'should you have no plans... join me?', then RecruitHostNpcToParty. Corrected 2026-09-29: this type was named InteractionScene47 with the control bit unresolved.")
ENTRY_TYPES[57] = _sibling(56, "PrologueTutorialPromptB", "Second prologue tutorial prompt (type 56 + descriptor byte 1), queued by Player_TickConsumeHeldItemAndApplyEffect while the story flag is 9.")
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
    "matcher": "Npc_PredicateMatchSubBytesAndCommitEventId from NpcAi_ProbeAndApplyMovementWithCustomTypeByte (RF4S.exe+0x1F6F40), game event kind 7",
    "confidence": "likely", "notes": "Skipped while the player is dead (Player_DeathTickCallback).",
}
ENTRY_TYPES[55] = {
    "name": "GlobalScene55", "summary": "Key-less global scene (code-only, absent from the corpus).",
    "bank": "global (slot 0)", "keys": [], "select": "first", "consumer": _APPLY0 + " (step immediately)",
    "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x37) from NpcAi_ProbeMovementFromEventKind55 (RF4S.exe+0x1F28F0), game event kind 17",
    "confidence": "likely", "notes": "Expected keys [0, 0].",
}
ENTRY_TYPES[58] = {
    "name": "VolkanonPrologueTalk", "summary": "Tail-bank scene run when the player talks to Volkanon during the prologue (story flag 9), turning him toward the player (code-only).",
    "bank": "tail (slot 2)",
    "keys": [{"index": 0, "name": "ctx329", "meaning": "npc_event_ctx byte +329", "wildcard": True}],
    "select": "first", "consumer": "Npc_QueueReactionEventAndTurnTowardPlayer(3) then " + _KICK2,
    "matcher": "Event_QueryByKindNpcAndStoryChapter(kind 0x3A) from NpcAi_TriggerScriptedEventKind58_ForceVolkanonReact (RF4S.exe+0x1F7470), game event kind 19",
    "confidence": "likely", "notes": "Game event kind 19 is queued by Npc_OnInteract_QueueEventByStoryGate (RF4S.exe+0x1F4170) when the talked-to NPC is char 3 (Volkanon) and the story flag == 9. Corrected 2026-09-29: this type was named MapSpecialEventKind58 without its trigger (old handler number 18, one too low).",
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


EVENT_KEY_MIN, EVENT_KEY_MAX = 48, 0xFFFF       # see key_errors / key_problems


def key_errors(type_id, subs):
    """Keys that make an entry impossible (refused by the editor and the CLI): a value that
    does not fit the file's signed 32-bit key field, and for type 2 (ActorInteractScene) any
    key no event actor can carry. Verified 2026-10-01 in RF4S.exe: SpawnEventActor and every
    key-addressed op keep only the low 16 bits of the key (stored as a u16 in the event-actor
    table), EventActor_GetKeyOfActor (+0x1D3540) returns it zero-extended, and
    NpcAi_FindActionEntryByTargetForType2 (+0x221EC0) compares it with the entry's i32 key by
    plain int equality -- so -1 and anything outside 0..65535 never match (spawning with -1
    stores 65535: write 65535). 0 is what UnregisterEventActor writes into a removed record's
    key, and the spawn lookup matches the first record with key 0, so it is refused too."""
    out = []
    for k, sub in enumerate(subs or ()):
        v = sub[1] if isinstance(sub, (tuple, list)) else sub
        try:
            v = int(v)
        except (TypeError, ValueError):
            continue
        if not -0x80000000 <= v <= 0x7FFFFFFF:
            out.append("key %d = %d does not fit: keys are signed 32-bit (-2147483648..2147483647)" % (k, v))
        elif type_id == 2 and v == -1:
            out.append("key 0 is -1: %s compares the event actor's key exactly and event keys are "
                       "0..65535, so this entry never runs (spawning with -1 stores 65535 -- but the "
                       "actor ops then cannot address it: use a key from %d to %d)"
                       % (type_name(2), EVENT_KEY_MIN, EVENT_KEY_MAX))
        elif type_id == 2 and not 0 < v <= EVENT_KEY_MAX:
            out.append("key %d = %d can never match: event keys are stored as unsigned 16-bit, and 0 "
                       "marks a removed event actor -- use a key from %d to %d"
                       % (k, v, EVENT_KEY_MIN, EVENT_KEY_MAX))
    return out


# value ranges of the typed keys (warnings: an id that does not exist matches nothing)
_NPC_PACKED = (16582, 16638)                        # "read the NPC id from that packed game flag"


def key_problems(type_id, subs, em_count=None, map_ok=None, char_ok=None):
    """Warnings (list of str) for the keys `subs` (ints, or (tag, value) pairs) of a new or
    changed `type_id` entry. Entry keys are signed 32-bit, and -1 only means "any" where the
    type's matcher skips it (the catalogue's per-key `wildcard`). Type 2 (ActorInteractScene)
    compares exactly against a spawned event actor's key, which the event manager keeps as
    an UNSIGNED 16-bit word (EventActor_GetKeyOfActor RF4S.exe+0x1D3540): -1 or any value
    outside 0..65535 can never match an event actor, and 0 is the key of an empty /
    unregistered record."""
    out = []
    spec = ENTRY_TYPES.get(type_id)
    if em_count is None:
        em_count = 272                                   # the shipped em.bin
    for k, sub in enumerate(subs or ()):
        v = sub[1] if isinstance(sub, (tuple, list)) else sub
        try:
            v = int(v)
        except (TypeError, ValueError):
            continue
        ks = key_spec(type_id, k)
        kname = (ks or {}).get("name", "key %d" % k)
        wild = bool((ks or {}).get("wildcard", False))
        if type_id == 2:
            if 0 < v < EVENT_KEY_MIN:
                out.append("key %d = %d: an event actor with this key talks fine, but ops that take an "
                           "actor read 1..47 as a villager id, so they cannot address it -- keys %d..%d "
                           "work everywhere (the game uses 100..1500)" % (k, v, EVENT_KEY_MIN, EVENT_KEY_MAX))
            continue
        if v == -1:
            if spec is not None and ks is not None and not wild and kname != "npc":
                out.append("key %d (%s) is -1, but %s compares it exactly (no wildcard): it only "
                           "matches the value -1" % (k, kname, type_name(type_id)))
            continue
        if kname == "npc" and v not in _NPC_PACKED and (v < 0 or (char_ok is not None and not char_ok(v))):
            out.append("key %d (npc) = %d is not a character the game has (or 16582 / 16638 = read the "
                       "id from that packed flag)" % (k, v))
        elif kname == "item" and not 0 <= v <= 0x7FF:
            out.append("key %d (item) = %d is not an item id: the game compares the slot's 11-bit id "
                       "(0..2047)" % (k, v))
        elif kname == "condition" and not 0 <= v < em_count:
            out.append("key %d (condition) = %d is not an em.bin entry (0..%d)" % (k, v, em_count - 1))
        elif kname == "topic" and not 1 <= v <= 10:
            out.append("key %d (topic) = %d: the daily gossip topic is 1..10" % (k, v))
        elif kname == "festival" and not 0 <= v <= 31:
            out.append("key %d (festival) = %d: festival ids are 5-bit (0..31)" % (k, v))
        elif kname == "map" and v != 0 and map_ok is not None and not map_ok(v):
            out.append("key %d (map) = %d is not a map the game has" % (k, v))
    return out


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
    4: "The NPC's gift reaction: runs for every gift the player gives it that no type-50 "
       "entry claimed. Bank: that NPC's primary bank (canonical char id). Keys: the item "
       "ids (-1 = any item; every shipped entry is -1). First match wins, so put a "
       "specific item BEFORE the -1 entry.",
    6: "Map scene with no keys. Bank: the map's tail bank (n_primary + map id). WARNING: "
       "only the LAST type-6 entry runs, so appending one replaces the map's current "
       "scene -- CALL the old entry pc from your body if you want to keep it.",
    7: "The map's LEAVE scene: no keys, runs as the next map loads, after the player "
       "left this map. Bank: the map's tail bank (n_primary + map id). Only the FIRST "
       "type-7 entry runs, so a new entry must go before the existing one to replace "
       "it (and CALL the old entry pc from your body if you want to keep it). Use it to "
       "undo what the map set up (flags, lighting, the shop).",
    9: "Global scene run when a fish is caught; no keys, global bank. Only the LAST "
       "entry runs, and the shipped file has exactly one, so a new entry replaces it.",
    15: "Scene that plays when a scripted warp (WarpToMap with an event number) lands. "
        "The number picks the bank: 1000..1099 -> the active sub-event bank, 100..999 -> "
        "the story bank in slot 1, any other number -> the arrival map's tail bank. One "
        "key = that event number. First match wins, so numbers must be unique within the "
        "list.",
    22: "First greeting of the day, chosen by time of day. Bank: 224 + canonical char id. "
        "One key = time slot (0 = 06-09h, 1 = 10-17h, 2 = otherwise; -1 = any). First "
        "match wins.",
    30: "Talk line gated by main-scenario progress. Bank: 224 + canonical char id. Keys: "
        "chapter_lo, chapter_hi (inclusive range of REG_MAIN_SCENARIO). The last fired hi "
        "is remembered, but an equal hi still passes, so the same range can fire again. "
        "First match wins, so put narrower ranges before wider ones.",
    49: "Global scene run after the player eats a recipe bread (what was learned); no keys, "
        "global bank. Only the LAST entry runs and the shipped file has one, so a new entry "
        "replaces it.",
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
    """The action type a map's ENTER scene is registered under (MapEnterScene, type 6)."""
    for t, info in ENTRY_TYPES.items():
        if (info or {}).get("name") == "MapEnterScene":
            return int(t)
    return 6
