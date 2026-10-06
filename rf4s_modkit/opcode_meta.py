"""Cutscene-author-facing metadata for the Script-VM opcodes.

This is a *non-destructive display layer* over the raw opcode table. The exact
IDA-symbol names stay in ``script_opcodes.json`` (the RE ground truth); this module
adds, per opcode:

  * a short **mnemonic** an author actually thinks in (``WarpPlayer``, ``FadeScreen``),
  * a **category** for grouping,
  * a one-line **description** of what it does,
  * **argument names** so a tooltip can label each positional arg.

Everything is derived from the already-verified handler behaviour -- no new guessing.
Opcodes not curated here fall back to a humanized form of their technical name, so
*every* opcode still yields a usable tooltip.

Two families are generated from the technical names rather than hand-listed:
  * the 16 indexable var-array kinds (``Write/ReadVarArrayKindN``) -> ``SetVarN/GetVarN``
    (kind 7 is special-cased to portrait/face, per the dialogue renderer),
  * the ``NoOp<NN>_StubReturn0`` no-ops -> ``nop`` (does nothing on PC).
"""
import json
import re

from .refdata import refdata_path

with open(refdata_path("script_opcodes.json"), encoding="utf-8") as _f:
    TECHNICAL = {int(k): v for k, v in json.load(_f).items()}

# ---- categories -------------------------------------------------------------------
CATEGORIES = {
    "dialogue":  "Dialogue & portraits",
    "screen":    "Camera / screen",
    "actor":     "Actors & player",
    "companion": "Companions & party",
    "flag":      "Flags & variables",
    "audio":     "Audio",
    "time":      "Time & calendar",
    "item":      "Items, rewards, economy",
    "effect":    "Effects & world",
    "quest":     "Quests",
    "flow":      "Scene flow / control",
    "query":     "Queries",
    "noop":      "No-op (PC-port stub)",
    "misc":      "Other",
}

# ---- control opcodes (>= 0xFFF0, keyed by the mnemonic Script emits) ---------------
CONTROL = {
    "RET":       ("flow", "Return-or-end -- the VM's real RETURN instruction (IDA-verified: "
                          "Script_Opcode_FFFF_EndAndCleanup, RF4S.exe+0x23EBA0). Discards the "
                          "current frame's locals, then: inside a CALLed subroutine it pops the "
                          "saved PC and resumes right after the CALL; at the top level (frame "
                          "base 0) it ends the scene (task state 1 READY). So `CALL -> Lx ... "
                          "Lx: ... RET` is a subroutine, and only a top-level RET terminates "
                          "the script. (Displayed as END before 2026-09-01.)"),
    "FRAME":     ("flow", "Frame setup (it does NOT return): sets the frame base to the "
                          "operand-stack top and reserves N stack words, then falls through. The "
                          "words are the expression evaluator's spill room: a nested expression "
                          "used as a non-last action argument needs N >= 2*(depth-1). Verified in "
                          "game 2026-09-29 (it is not a locals reservation); the editor sizes it."),
    "CALL":      ("flow", "Call a subroutine: push the caller's frame base and the return PC "
                          "onto the operand stack, then jump. The subroutine comes back here "
                          "when it executes RET (the VM's return)."),
    "JMP":       ("flow", "Unconditional jump."),
    "BR_Z":      ("flow", "Branch if the guard expression is 0 (false)."),
    "BR_NZ":     ("flow", "Branch if the guard expression is non-zero (true)."),
    "RET_NZ":    ("flow", "Conditional RET (early-exit guard): evaluate the guard expression -- "
                          "if it is nonzero/true, do exactly what RET does (return from a CALLed "
                          "subroutine, or end the scene at top level); otherwise fall through to "
                          "the next statement. Never emitted in shipped scripts. IDA-verified "
                          "(Script_VMStep case 0xFFFD -> Script_EvalExpressionOrVar, then "
                          "Script_Opcode_FFFF_EndAndCleanup when true)."),
    "EVAL":     ("flag", "Evaluate an expression and store it into a variable."),
    "DIALOG":    ("dialogue", "Show a dialogue line (by text id). The current SPEAKER (set by a "
                          "SetSpeaker* portrait op, SetSpeakerVoice op 10, or nothing = "
                          "narration) PERSISTS across consecutive DIALOG lines until the next "
                          "speaker op or EndDialogue (op 92) — 917 shipped scenes rely on "
                          "back-to-back lines under one speaker. If an SetNextChoiceDescription (op 615) "
                          "precedes this line, it does NOT display: it queues as a choice "
                          "option for a later PROMPT_CHOICE instead."),
    "SWITCH": ("flow", "Indexed jump table: evaluate the selector expression, then jump to "
                          "targets[value] when 0 <= value < N -- a DENSE 0..N-1 index, not a set of "
                          "per-case compare values. The comparison is UNSIGNED, so a negative "
                          "selector (like reg0 = -1 after a cancelled prompt) falls through to the "
                          "next statement, same as any >= N value. The canonical use is dispatching "
                          "a choice result: `SWITCH (reg0)` after a staged PROMPT_CHOICE jumps "
                          "to the picked option's branch. Layout: [op][selector-expr][N]"
                          "[N u16 targets]. IDA-verified (Script_VMStep case 0xFFF7, "
                          "RF4S.exe+0x23EF60)."),
    "SWITCH_CLAMP": ("flow", "Indexed jump table, always-branch variant of SWITCH: jump to "
                          "targets[value] when value < N, and CLAMP an out-of-range value (>= N, "
                          "including negatives -- the compare is unsigned) to the last target "
                          "(targets[N-1]) rather than falling through -- so it never falls "
                          "through. Same [op][selector-expr][N][N u16 targets] layout as "
                          "SWITCH. Used exactly once in the whole game. IDA-verified "
                          "(Script_VMStep case 0xFFF6)."),
    "JMP_RAND":   ("flow", "Uniform-random jump: pick one of the N targets at random (each 1/N) and "
                          "jump to it -- the UNWEIGHTED sibling of JMP_WEIGHTED. Takes no operand (the "
                          "target table is the only data); the pick is an RNG roll in [0, N) via the "
                          "same VM RNG (reader-vtable +56) that JMP_WEIGHTED rolls its weighted pick with. "
                          "Layout: [op][N][N u16 targets]. IDA-verified (Script_VMStep case 0xFFF3)."),
    "JMP_WEIGHTED":   ("flow", "Weighted-random branch: pick one of N targets at random, each weighted by "
                          "an expression. Every case's weight is evaluated fresh (so a weight can "
                          "depend on game state), the weights are summed, then an RNG roll in "
                          "[0, total) selects a target -- case i fires with probability "
                          "weight[i] / sum(weights) (weight 0 = never taken). The editable literals "
                          "on this op ARE those per-target weights, so raising one tilts the odds "
                          "toward its branch. Layout: [op][N][N u16 targets][N u16 weight-exprs]; "
                          "size 4N+4. IDA-verified (Script_VMStep case 0xFFF2 -> "
                          "Script_Opcode_FFF2_ExecPrim, RF4S.exe+0x23EC40)."),
    "PROMPT_CHOICE_FORCED": ("flow",
                          "Present a choice menu with NO cancel key -- one of the N options "
                          "must be picked (the cancel key does nothing). Same UI as "
                          "PROMPT_CHOICE: each option is a full u32 rf3mc.<locale> text id "
                          "(no flag bits; an id past the archive shows entry 0), 4 rows on "
                          "screen with a wrap-around scrolling list, at most 128 options "
                          "(the rest are silently dropped); option text goes through the "
                          "normal ＠ substitution pass. Branches to targets[picked VISIBLE "
                          "ROW]. reg0 is written ONLY when a visibility mask is set (ops "
                          "610/611/612): then only flagged options appear, reg0 = the picked "
                          "option's ORIGINAL index, the mask is cleared, and the shipped "
                          "idiom is all targets -> one label + SWITCH on reg0. A mask "
                          "whose set bits all lie past option N-1 opens an EMPTY menu that "
                          "crashes on confirm (divide by zero); an all-zero mask shows every "
                          "option. An unmasked prompt leaves reg0 UNTOUCHED -- shipped scenes "
                          "carry a GetPlayerPosition result in reg0/reg1 across a Yes/No "
                          "prompt (the deck-fight chase). CalcChoicePrescroll (613) sets the "
                          "initially highlighted row. Layout: [op][N][N u16 targets][N u32 "
                          "items]; size 6N+4. IDA-verified 2026-09-24 (Script_VMStep case "
                          "0xFFF5, SceneEvent_FinalizeAndPickFromBitmap, "
                          "ChoiceDialog_TickStateMachine)."),
    "PROMPT_CHOICE": ("flow", "Present a choice menu whose cancel key jumps the cursor to the "
                              "LAST option (and picks it when already there) -- so make the "
                              "last option the 'never mind' one. The picked row's target is "
                              "taken as for PROMPT_CHOICE_FORCED (same UI, 128-option cap, "
                              "4 visible rows, visibility-mask and reg0 rules). The CANCEL "
                              "slot (target[0]) is only used for a NEGATIVE pick, which the "
                              "menu never produces: 890 of the 891 shipped menus just repeat "
                              "the last option's target there. Layout: [op][N][cancel u16][N "
                              "u16 targets][N u32 items]; size = 6N+6. IDA-verified "
                              "2026-09-24 (Script_VMStep case 0xFFF4, "
                              "ChoiceDialog_ConfirmViaScrollArrow, "
                              "SceneEvent_FinalizeAndPickFromBitmap)."),
}

# ---- curated action-opcode metadata: op -> (mnemonic, category, description, [args]) ----
# args names label each positional argument for the tooltip.
# NOTE: keys here are the OLD (+302-shifted) indices; they get shifted to the real
# action ids below. See the _M assembly after this dict.
# the date-state lifecycle, shared by ops 280 / 281
_DATE_LIFE = "Lifecycle (traced 2026-09-25): the invitation scene sets 1 when the NPC accepts ('I would love to accompany you!') or 5 when they decline ('I have work to do tomorrow'); Day_UpdateNpcDailyFlags (RF4S.exe+0x227AE0) turns 1 into 2 at the daily rollover, clears 5, and treats a 2 that is still 2 as a stood-up date (stood-up mark 1-3, back to 0, em.bin EV_DATE_FINISH); Npc_TryDateInvitation_NightFinale does the same at 18:00/22:00; the date-day talk sets 3 when the date starts; leaving the party with 3 or 4 ends the date (Companion_SyncToScene: back to 0 + EV_DATE_FINISH)."

_M_OLDBASE = {
    # --- dialogue / portraits / emotes ---
    19:  ("GetEmote", "query", "Read an NPC's current emote id.", ["npc id"]),
    22:  ("GetMood", "query", "Read an NPC's current mood id.", ["npc id"]),
    # --- screen / camera / fade ---
    32:  ("FadeScreen", "screen",
          "Fade both screens. arg0 = signed target (sign = colour: - black / + white; |v|/16 = "
          "opacity; -16 = to black). arg1 = duration (frames = arg1/100). See op 334 for full "
          "detail. (This OLDBASE entry is shadowed by the real op-334 entry below.)",
          ["fade target (-16 = black, +16 = white)", "duration (frames = arg1/100)"]),
    33:  ("FadeScreenQuick", "screen", "Fade both screens (kind only, default duration).", ["fade kind"]),
    34:  ("SetFadeColor", "screen", "Set the fade colour, ramped over a duration.", ["R", "G", "B", "duration"]),
    35:  ("WaitForFade", "screen", "Block the scene until the current fade completes.", []),
    354: ("SetMapFadeAlpha", "screen", "Set the map-fade alpha target (channel 0). arg0 = alpha x10000 (clamped 0..1); arg1 = snap flag (1 = jump current to target, 0 = interpolate).", ["alpha (x10000)", "snap (0/1)"]),
    355: ("SetMapFadeChannel1", "screen", "Set map-fade channel 1's target value (a 0..1 scalar = value/10000) with a snap flag (arg1: 1 = jump current straight to target, 0 = interpolate). The channel-1 sibling of op656 SetMapFadeAlpha (channel 0); despite the old 'SetMapFadeColor' name the handler reads a single scalar + snap, NOT an RGB triple -- channel 1's exact visual role (second fade layer / colour-blend / mode) is unconfirmed.", ["value (x10000)", "snap (0/1)"]),
    380: ("SetSceneFlag400", "flow", "Set a scene flag word (mode 3).", ["value"]),
    385: ("RebuildMinimap", "screen", "Rebuild the minimap for the active context.", []),
    386: ("ToggleMinimap", "screen", "Show/hide the minimap and queue a fade.", ["visible"]),
    # --- flags & variables ---
    16:  ("SetFlag", "flag", "Set a packed story/quest/event flag.", ["flag id", "(value)"]),
    142: ("SetFlagBitIfCond", "flag", "Set a game-flag bit, gated by a condition script.", ["flag id", "value"]),
    143: ("GetFlagBit", "query", "Read a single game-flag bit.", ["flag id"]),
    # --- audio ---
    77:  ("PlayMusic", "audio", "Play a BGM track, or restore the map's default (-1).", ["bgm id (-1=restore)"]),
    83:  ("PlaySound", "audio", "Play a sound effect by id.", ["sfx id"]),
    84:  ("StopVoices", "audio", "Stop all active voice slots.", []),
    88:  ("StopVoiceId", "audio", "Stop the voice matching an id.", ["voice id"]),
    90:  ("PlayVoicedSound", "audio", "Play a sound effect via a dedicated voice slot.", ["sfx id"]),
    # --- player / actors ---
    7:   ("IsFrey", "query", "Writes 1 to reg0 when playing as Frey (female protagonist), 0 for "
         "Lest. The scripts pick gendered lines/animations by branching on reg0 right after.", []),
    27:  ("IsPosing", "query", "1 if an actor's scripted pose is active.", ["actor"]),
    91:  ("FreezePlayer", "actor", "Lock or release player input.", ["freeze (0/1)"]),
    92:  ("WarpPlayer", "actor", "Teleport the player to a map tile.", ["tile x", "tile y"]),
    97:  ("GetPlayerSubstate", "query", "Read the player's substate id.", []),
    358: ("SetActorStatusFlag", "actor",
          "Set/clear the target actor's stats.status_flags bit 0x20 by char id (for char id 239 it "
          "toggles bit 0x10000 instead). No stat recompute. arg0 = char id (0=player, 1..47=NPC, "
          ">=48=event actor via calendar-event mng), arg1 = 0 to clear / non-zero to set. NOTE: "
          "distinct from op 661 SetActorStatFlagRecompute (bit 0x20000 + stat recompute + HP clamp).",
          ["char id (0=player, <48=NPC, >=48=event)", "on (0=clear, else set)"]),
    363: ("SetActorFacing", "actor", "Set an actor's facing angle by char id.", ["char id", "deg"]),
    # --- NPC streaming / placement ---
    191: ("GetNpcFacingMode", "query", "Read a scene NPC's scripted-facing mode bits.", ["npc id"]),
    # --- companions ---
    193: ("WarpCompanion", "companion", "Teleport companion(s) to a tile.", ["slot", "tile x", "tile y"]),
    194: ("MoveCompanion", "companion", "Move a companion toward a tile (choreographed, with facing).",
          ["slot", "tile x", "tile y", "facing deg", "speed", "run"]),
    195: ("MoveCompanionNF", "companion", "Move a companion toward a tile (no facing change).",
          ["slot", "tile x", "tile y", "speed", "run"]),
    196: ("MoveCompanionRel", "companion", "Move a companion relative to its current tile (with facing).",
          ["slot", "dx", "dy", "facing deg", "speed", "run"]),
    198: ("SetCompanionPose", "companion", "Set a companion's facing angle and pose.", ["slot", "facing deg", "pose"]),
    199: ("CompanionFaceTarget", "companion", "Turn a companion to face a target actor, set pose.", ["slot", "target", "pose"]),
    204: ("WarpMonstersToPlayer", "companion", "Teleport all companion monsters to the player.", []),
    # --- time / calendar ---
    3:   ("GetHour", "time", "Read the current calendar hour.", []),
    4:   ("GetDay", "time", "Read the current calendar day.", []),
    6:   ("GetDateSnapshot", "time", "Read a full calendar snapshot.", []),
    335: ("SaveCalendarSnapshot", "time", "Save a calendar snapshot.", []),
    # --- items / rewards / economy ---
    23:  ("GetLumber", "item", "Read the player's lumber count.", []),
    24:  ("AddLumber", "item", "Add to (or subtract from) the player's lumber.", ["amount"]),
    155: ("ShowRewardPopup", "item", "Show a reward popup for up to 4 items.", ["item0", "item1", "item2", "item3"]),
    156: ("ShowQuestReward", "item", "Show the NPC quest-reward popup.", []),
    161: ("DropItem", "item", "Drop a single item at the player.", ["item id"]),
    337: ("GetPrincePoints", "item", "Read the current prince points.", []),
    338: ("AddPrincePoints", "item", "Add prince points.", ["amount"]),
    339: ("GetTourists", "item", "Read the current tourist count.", []),
    340: ("AddTourists", "item", "Add tourists.", ["amount"]),
    # --- effects / world ---
    108: ("TameEventNpc", "effect", "Tame the calendar-event NPC/monster.", []),
    144: ("SetWeather", "effect", "Set the current weather.", ["weather id"]),
    145: ("GetWeather", "query", "Read the current weather.", []),
    # --- scene flow (kept close to technical -- no clean author verb) ---
    257: ("ReturnToTownPrompt", "flow", "Spawn the return-to-town prompt and pause the VM.", []),
}

# CRITICAL FIX (2026-07-03, live-confirmed): the curated table above + the old
# script_opcodes.json were authored against the WRONG table base -- built from
# RF4S.exe+0x4DC100, which is g_sceneActionHandlerTable[302], NOT the table's start.
# The REAL script-action table is g_sceneActionHandlerTable @ RF4S.exe+0x4DB790, and the
# VM dispatches table[action_id] directly (Script_VMStep -> SceneAction_DispatchTableWithCleanup).
# So every curated entry belongs at index +302, and the LOW action ids (0..~40) are the
# DIALOGUE / speech-bubble handlers (which the old table mislabeled as SetFlag/calendar/etc).
# script_opcodes.json is rebuilt to the real table; here we shift the curated overlay and add
# the low dialogue ops. (Live proof: action 16 = the bathhouse gag's portrait face/emote line.)
_M_LOW = {
    10: ("SetSpeakerVoice", "dialogue",
         "Set the speaker for the following DIALOG line(s) to a NAMED VOICE: name plate only, "
         "NO portrait ('no portrait dispatch' — the handler's own contract). This is how "
         "off-screen and un-introduced characters speak — the opening's captain monologue "
         "(name string 738) and the stowaway bandits' whispers (392) both talk through it. "
         "arg0 = the NAME-PLATE string id: an entry of the character-name archive (the same "
         "list as char_names.json -- 21 Ventuswill, 236 Ethelwill, 392 '???', 738 Joyful "
         "Captain; not an rf3mc line id), shown through Dialogue_LoadAndShowText(archive, id, 2) "
         "and latched at task+108 so repeating it is free. arg1 = the TEXT BLIP, the tick sound "
         "played while the line types out (Dialogue_SetTickChimeSfxId; no voice acting is "
         "involved; the typewriter, Sprite_TickTypewriterDripText RF4S.exe+0x246AD0, plays it on every "
         "4th character and restarts the count at each line break): 0 = male blip (sfx 16785916 = "
         "SE_WORDS_M.wav), 1 = female blip (16785917 = SE_WORDS_F.ogg), 2 = monster / animal blip "
         "(16785918 = SE_WORDS_O.wav; Buffamoo, Fiergaenger), 3 = dragon blip (16785975 = "
         "SE_WORDS_D.wav; Ventuswill in dragon form, Ancient Bone) -- names from "
         "common_audio_data.bdat, the files sit in bundleMain; 4+ = the PLAYER's own blip -- male for Lest's model "
         "(model 1217 = NPC_PLAYER_00), female for Frey's (1233 = NPC_PLAYER_01), male again when "
         "neither and player control flag 0x8000000 is set. Shipped uses: 651x 0, 170x 1, "
         "5x 2, 105x 3 (931 in all). IDA-verified (Script_VMOp_SetSpeakerVoice, "
         "RF4S.exe+0x20A240).",
         ["name string id (name archive)", "text blip (0 male, 1 female, 2 monster, 3 dragon, 4+ player's)"]),
}
# actions 16..75 are ALL one handler Script_VMOp_SetSpeaker (RF4S.exe+0x207F70) --
# the PORTRAIT dialogue line. The OPCODE NUMBER is a parameter: the handler reads it back
# from sceneCtx+260 and computes  speaker_slot = (op-16)>>1  (0..29) and  parity = op&1.
# speaker_slot indexes g_gameGlobalsSlotTable (the character/state directory) to pick WHO
# speaks: slot 0 = the protagonist/main character, higher slots = NPCs (e.g. 19 = Nancy).
# So two consecutive opcodes (2N+16, 2N+17) are the same speaker with a parity sub-variant.
# The script args are the portrait content: arg1=face/expression; arg2/arg3=trigger ids
# (emote bubble 186-192, e.g. 190='!'/191='?', OR a voice-line sfx id >= 0x1F0 played via
# the NPC-variant remap -- NOT a target actor). The handler (Script_VMOp_SetSpeaker,
# shared by all of 16-75) reads the SPEAKER from the opcode via ctx+260: line_id=(op-16)>>1,
# side=op&1. (Live-proven: op16 face 4 = open-mouth surprise for the MC in both the bathhouse
# gag and the intro "Really?!" line; op54/55 = Nancy neutral/laughing in the intro wake-up scene.)
# portrait speaker_slot -> character. Slots 0..21 = the fixed main villagers, matching the
# engine name roster Npc_GetDisplayName (archive 16369): VERIFIED slot 0 = player (save name,
# default "Lest"), 17 = Dolce, 19 = Nancy (live). 22/23 = the marriage Son/Daughter (DYNAMIC:
# DispatchFromDescriptor re-reads them from GameFlags 5-bit @0xFE; child dialogue confirms).
#
# **The portrait-slot numbering DIVERGES from the name roster past 23** (found 2026-07-03,
# user-caught). Roster (archive 16369) has 24=Barrett/25=Raven/26=Trupin/27+=Traveler, but the
# PORTRAIT system reuses the high slots for GUEST speakers whose NAME is set per-scene by a
# `*<name>` directive dialogue line (NOT the portrait op -- guest SetSpeakers carry no char
# ref). Verified from the game's own *name tags + dialogue content:
#   24 = Pico    (Dolce's companion; ALL 75 banks of slot-24 lines are Pico's "milady" speech)
#   27 = Barrett (*Barrett name-tag; user-confirmed "...get along well with that dragon?")
#   28 = Raven   (*Raven name-tag)
# 25/26/29 have no name-tag line; their NAME PLATE comes from the handler itself (verified
# 2026-09-24): Script_VMOp_SetSpeaker (RF4S.exe+0x207F70, the shared handler of ops
# 16..75) maps the slot (op-16)>>1 to the rf3TxtNpc name entry it passes to
# Dialogue_LoadAndShowText -- 24 -> 309 Pico, 25 -> 149 Soldier, 26 -> 239 Ethelberd,
# 27 -> 24 Barrett, 28 -> 25 Raven, every other slot unchanged (so 29 -> 29 Traveler). That
# matches the corpus: slot 25 is the airship bandits, slot 26 the Rune-Sphere villain. The
# portrait ART stays indexed by the slot. A nearby `*<name>` line can still rename a guest.
PORTRAIT_SPEAKERS = [
    "Lest/Frey", "Vishnal", "Clorica", "Volkanon", "Forte", "Kiel", "Bado", "Margaret",
    "Dylas", "Arthur", "Porcoline", "Xiao Pai", "Lin Fa", "Amber", "Illuminata", "Doug",
    "Blossom", "Dolce", "Jones", "Nancy", "Leon", "Ventuswill", "Son", "Daughter",
    "Pico", "Soldier", "Ethelberd", "Barrett", "Raven", "Traveler",
]
# Identifier-safe tag per slot, used to build the `SetSpeaker$<tag>` mnemonic. Slot 0 =
# "MC" (the player / main character, whose real name is the save name). Spaces/slashes
# stripped so the tag is a clean suffix.
PORTRAIT_SPEAKER_TAGS = [
    "MC", "Vishnal", "Clorica", "Volkanon", "Forte", "Kiel", "Bado", "Margaret",
    "Dylas", "Arthur", "Porcoline", "XiaoPai", "LinFa", "Amber", "Illuminata", "Doug",
    "Blossom", "Dolce", "Jones", "Nancy", "Leon", "Ventuswill", "Son", "Daughter",
    "Pico", "Soldier", "Ethelberd", "Barrett", "Raven", "Traveler",
]


def portrait_speaker_slot(op):
    """For a portrait-line opcode (16..75) return (speaker_slot, parity); else None.
    speaker_slot IS the NPC id: it indexes g_gameGlobalsSlotTable (0 = the player).
    parity (op&1) selects the portrait SIDE / bubble slot (+horizontal flip)."""
    if 16 <= op <= 75:
        return ((op - 16) >> 1, op & 1)
    return None


def speaker_plate(slot):
    """The name-archive entry (rf3TxtNpc row) the game shows for speaker `slot`: the slot
    itself, except the slots the speaker handler remaps (RF4S.exe+0x207F70)."""
    return _SPEAKER_PLATE_REMAP.get(slot, slot)


def speaker_name(slot):
    """Display name of speaker `slot` 0..29, from the game's name archive (so a renamed
    character shows renamed); 'Lest/Frey' for the player slot 0."""
    if slot == 0:
        return PORTRAIT_SPEAKERS[0]
    try:
        from . import gamenames
        nm = gamenames.name("characters", speaker_plate(slot))
    except Exception:
        nm = None
    if nm:
        return nm
    return PORTRAIT_SPEAKERS[slot] if 0 <= slot < len(PORTRAIT_SPEAKERS) else "slot %d" % slot


def portrait_speaker_name(op):
    """Character name for a portrait-line opcode (16..75), else None."""
    sp = portrait_speaker_slot(op)
    if sp is None:
        return None
    return speaker_name(sp[0])


# name-plate archive entries of the slots the speaker handler remaps (RF4S.exe+0x207F70)
_SPEAKER_PLATE_REMAP = {}


def portrait_speaker_tag(op):
    """Identifier-safe speaker tag for a portrait-line opcode (16..75), e.g. 'Vishnal'
    / 'MC'. Used to form the `SetSpeaker$<tag>` mnemonic. None if not a portrait op."""
    sp = portrait_speaker_slot(op)
    if sp is None:
        return None
    slot = sp[0]
    if 0 <= slot < len(PORTRAIT_SPEAKER_TAGS):
        return PORTRAIT_SPEAKER_TAGS[slot]
    return "slot%d" % slot


# SetSpeaker arg2 = mood/expression id. The common vocabulary in shipped scripts is 186..192
# (measured across ~211k dialogue ops). g_emotePortrait_emoteToStringIdTable (RF4S.exe+0x4DA670)
# maps them to named mood categories -- ROW 0 shown here. NOTE: the mapping is *row/kind-
# dependent* (EmotePortrait_ResolveSpriteRow(kind) picks the row), so a given id can render a
# different mood in a different scene: the earlier LIVE read saw 190='!'/191='?' (surprise /
# troubled) where row 0 has 190=sadness/191=smile. Treat these as the default-row meaning, and
# verify in-game for a specific scene. (JP -> EN below.)
PORTRAIT_EMOTES = {
    # Cross-checked 2026-07-07 against bank 252 tail44 scene@0x0898 pc@0x1f1e --
    # an `＊Emote Bubble` sampler menu whose labels ('＊Blush' / '＊Teary Eyes' /
    # '＊Angry' / '＊Sweat' / '＊!') pin down what each id renders as when set
    # from a SetSpeaker's arg 1. Values are the row-0 dominant meaning; the
    # actual sprite is picked by EmotePortrait_ResolveSpriteRow(kind).
    186: "blush",    # ＊Blush (also 25 pairings with '＊Blushing' in the face-check menu)
    187: "teary",    # ＊Teary Eyes (previously mislabelled 'SP2' -- SP2 is a Special
                     # FACE frame at id 254; this is the teary-eyed EMOTE bubble)
    188: "sweat",    # ＊Sweat (was '通常/normal'; row-0 rendering IS a small sweat drop)
    189: "angry",    # ＊Angry / 怒り -- drawn as a small white puff (seen in game 2026-10-01)
    190: "!",        # ＊! (was '哀しみ/sad'; the row-0 sprite is the exclamation-mark bubble)
    191: "?",        # seen in game 2026-10-01 (was 'smile', the row-0 table's 笑顔)
    192: "!?",       # seen in game 2026-10-01 (was 'surprise', the row-0 table's 驚き)
}
# All seven were checked on the player's portrait on 2026-10-01 (SetSpeaker(MC, Left, 0, id)):
# 186 blush, 187 teardrop, 188 sweat drop, 189 white puff, 190 !, 191 ?, 192 !?.
# other mood categories that exist in the table (row/variant dependent): 照れ bashful,
# 喜ぶ joy, 楽しい happy, 頬染め blush, 困る troubled/'?'.

# FACE FRAME (portrait arg1) -> canonical mood name. Derived 2026-07-07 from
# bank 292 @0x0ed2's dev face-check menu, which iterates 27 characters through
# the same 8 canonical faces + dialog captions. Higher face ids (6..46) are
# labelled '＊Test' in the dev menu and are per-character variant frames without
# a global name; 254/255 are the two Special/SP frames.
FACE_FRAMES = {
    0: "normal",   1: "angry",   2: "sad",       3: "laugh",
    4: "surprise", 5: "blush",
    254: "SP2",    255: "SP1",
}


def portrait_emote_name(emote_id):
    """Default-row mood name for a SetSpeaker emote/mood id (186..192), else None.
    Row/kind-dependent -- see PORTRAIT_EMOTES caveat."""
    return PORTRAIT_EMOTES.get(emote_id)


def face_frame_name(face_id):
    """Canonical mood name for a portrait face-frame id (0..5, 254, 255), else None.
    Ids 6..46 are per-character variant frames with no global name (dev menu labels
    them '＊Test'); use the raw id there."""
    return FACE_FRAMES.get(face_id)


_SPEAKER_PLATE_REMAP.update({24: 309, 25: 149, 26: 239, 27: 24, 28: 25})
for _op in range(16, 76):
    _slot, _par = ((_op - 16) >> 1, _op & 1)
    _who = PORTRAIT_SPEAKERS[_slot] if _slot < len(PORTRAIT_SPEAKERS) else "slot %d" % _slot
    _tag = PORTRAIT_SPEAKER_TAGS[_slot] if _slot < len(PORTRAIT_SPEAKER_TAGS) else "slot%d" % _slot
    _side = "left" if _par == 0 else "right"
    if _slot == 0:
        _who += " (player)"
        _plate = ("with the player's saved name (Dialogue_LoadAndShowText id 0 -> "
                  "Save_GetPlayerNameOrDefault; '???' before main-scenario progress 2)")
    elif _slot in _SPEAKER_PLATE_REMAP:
        _plate = "= name-archive entry %d (slot remap)" % _SPEAKER_PLATE_REMAP[_slot]
    else:
        _plate = "= name-archive entry %d" % _slot
    if _slot in (22, 23):
        _plate += "; the portrait/chime resolve slot 22/23 to REG_CHILD_ID"
    _M_LOW[_op] = ("SetSpeaker" + _tag, "dialogue",
                   "Speaker cue for the following DIALOG line(s): speaker slot %d = %s (slot = "
                   "(op-16)>>1), %s side (op & 1), shows that character's E-mote portrait and, "
                   "when the slot differs from the latched host+108, loads the name plate %s; "
                   "also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text "
                   "and persists until the next speaker op / EndDialogue. arg0 = expression: < "
                   "1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable), "
                   "1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock "
                   "alternate expressions of the character's current outfit row "
                   "(g_emotePortraitKindRows; EmotePortrait_Show then uses entries 1192 / 1224). "
                   "arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via "
                   "Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued "
                   "on the portrait (the first two non-voice ids are kept; 0 = none)."
                   % (_slot, _who, _side, _plate),
                   ["face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)",
                    "emote icon (186-192) or voice sfx id (>=0x1F0)",
                    "emote icon or voice sfx id 2", "emote icon or voice sfx id 3 (rare)"])
_M = {op + 302: meta for op, meta in _M_OLDBASE.items()}
_M.update(_M_LOW)
# op 0 is a genuine in-stream NO-OP / padding token, NOT a dead slot. Its dispatch entry is the
# shared ICF-folded return-0 stub (so it does nothing at runtime), but shipped cutscenes emit it
# 420x -- interspersed mid-scene (verified against the corpus: 410 mid / 10 leading / 0 trailing,
# 4 bytes, no operands). Curate it explicitly so it does not fall through to the "(unbound)"
# handler-name rule below, whose "the game's scripts never emit it" text is false for op 0.

# ---- author-friendly aliases for verbose high-frequency dialogue ops (IDA-verified) ----
# These keep the accurate technical name in script_opcodes.json but give the editor a
# short mnemonic. op 92 = ScriptVMOp_DialogueTeardownBubblesAndCommit_NoArgs (+0x2031... ),
# op 94-97 = ScriptVMOp_SetDialogueSpeakerEmoteFromActorField260 (emote = actor[+260]-94).
_M.update({
    92: ("EndDialogue", "dialogue",
         "Close both speaker bubbles and commit the dialogue state -- the end of a spoken "
         "exchange. ALSO CLEARS THE SPEAKER (sceneCtx+108 = -1): the next DIALOG without a "
         "new SetSpeaker is narration again (plain box, no name/portrait). Returns to the "
         "scene controller when no other event is in flight. The #2 most-used action op "
         "(10,564 uses) -- every dialogue beat ends with one.", []),
})
for _op, _nm in ((94, "SetBoxNormal"), (95, "SetBoxShout"), (96, "SetBoxThought"), (97, "SetBoxTrembling")):
    _M[_op] = (_nm, "dialogue", "Set the dialogue box style (see the full entry below).", [])

# ---- Event Manager (em.bin / EMF_) bridge ops -- IDA-verified 2026-07-04 ----------
# The one arg is an em.bin ENTRY id (0..271; names in emdeb.bin, see emscript.py).
# The disassembler appends the entry name automatically (script.EMF_ENTRY_OPS).
_M.update({
    371: ("EvalCondScriptA", "query",
          "Evaluate em.bin entry [id]'s condition A (Event Manager trigger check); "
          "bool result goes to the VM query register. E.g. EV_DATE_APPO, "
          "EM_BOSS_*_RETURN_MATCH_CHECK.", ["em entry id"]),
    372: ("EvalCondScriptB", "query",
          "Evaluate em.bin entry [id]'s condition B (the entry's alternate/negated "
          "variant, e.g. EV_CMN_DAYTIME's B = 'not daytime').", ["em entry id"]),
    373: ("DispatchCondScriptEntry", "flag",
          "Run em.bin entry [id]'s MAIN action stream (GameFlags writes; CALLs "
          "recurse into other entries' main streams). E.g. EV_SUBEV_INIT resets "
          "all sub-event flags.", ["em entry id"]),
    374: ("CondScriptDispatchAltAction", "flag",
          "Run em.bin entry [id]'s ALT action stream. Date scenes end with "
          "entry 80 EV_DATE_FINISH (clears FLG_DATE_FES_NOW / FLG_KOKUHAKU_NOW / "
          "REG_DATE_MAP).", ["em entry id"]),
    444: ("SetFlagBitIfCond", "flag",
          "Set/clear GameFlags bit [flag id] from em.bin entry [entry id]'s "
          "condition A: cond TRUE -> clear the bit, FALSE -> set it (inverse!). The flag id "
          "is ZONE-2 RELATIVE (absolute bit 4096 + id; Script_VMOp_SetGameFlagBitGatedByCondScript "
          "adds the buffer's zone2_base), like ops 443/445 -- not an emdeb/emflags name.",
          ["flag id", "em entry id"]),
})

# ---- scene-VM ops decoded 2026-07-05 (used in rf3.mc; previously raw sub_ fallbacks) ----
_M.update({
    147: ("RestoreDefaultEquip", "actor",
          "Restore the player's default weapon and switch to idle -- undoes a scripted "
          "op-146 equip. No args.", []),
    148: ("QueryPlayerFlag40000", "query",
          "Query -> VM query register: 1 if the player has status/accessory-effect flag "
          "0x40000, else 0.", []),
    282: ("QueryNpcPresent", "query",
          "Query -> VM query register: 1 if NPC [npc index]'s actor is spawned and not "
          "hidden (actor+568 & 0x20000000 clear), else 0.", ["npc index"]),
})

# ---- dev-menu ops decoded 2026-07-07 from bank 252 @0x462a ("*oSleep/*oSave/..." menu) ---
# The 34-choice dev menu in bank 252 and its dupe in bank 292 name each branch's target,
# so we can put the right author label + description on the underlying opcode.
_M.update({
    204: ("Sleep_TickBed", "flow",
          "Start the go-to-bed / sleep-to-next-day sequence (dev menu 'Sleep' branch "
          "calls this with [1]). Fades the world out, advances the day, and returns.",
          ["mode"]),
    334: ("FadeScreen", "screen",
          "Fade both screens (dual-screen, 3DS legacy) via two FadeTask_Init calls -- channel A "
          "(screen overlay) + channel B (scene tint). arg0 = signed fade TARGET: its SIGN picks "
          "the overlay colour (negative -> BLACK, positive -> WHITE) and |arg0|/16 = the target "
          "opacity (16 = fully opaque, 8 = half). Corpus: -16 = fade to black (dominant; used by "
          "Return-to-Title) and +16 = fade to white. arg1 = DURATION: the fade animates over "
          "arg1/100 frames (6000 -> 60 frames ~= 1s at 60fps; 18000 -> ~3s; 0 or <100 -> "
          "immediate). NOTE: arg1 is NOT milliseconds -- effective frames = arg1/100 (verified via "
          "FadeTask_Init(target_alpha, frame_count, channel)). Resolved by static analysis.",
          ["fade target (sign: - = to black, + = to white; |v|/16 = opacity; -16 = black, +16 = white)",
           "duration (frames = arg1/100; 6000 ~= 1s, 0 = immediate)"]),
    337: ("WaitForFade", "flow",
          "Block the scene until the current dual-screen fade started by FadeScreen (op 334) "
          "completes.", []),
    375: ("OpenMenu", "flow",
          "Fire a World_DispatchInteractionEvent by action id (see the "
          "TriggerWorldInteractionAction picker for the full list). Common ids: "
          "1 = Save menu, 2 = Load menu (dev-menu ONLY -- crashes mid-gameplay), "
          "3 = Message Board, 11 = Calendar, 12 = Storage, 23 = Fridge, 25 = "
          "BackupSaveNow (autosave), 45 = Bookshelf, 53 = Shipping Bin, 54 = Safe, "
          "55 = Wardrobe, 56 = Toolbox, 58 = Forge, 71 = Crafting.",
          ["action id"]),
    445: ("GetFlagBit", "query",
          "Query -> VM query register: 1 if game-flag bit [flag id] is set, else 0. "
          "The id is ZONE-2 RELATIVE: the handler tests absolute bit 4096 + id (it adds the "
          "buffer's zone2_base), the same numbering as ops 443/444 and MOBJ f13 -- NOT the "
          "emdeb/emflags (zone-1) table. Known blocks: emflags.ZONE2_BLOCKS.",
          ["flag id"]),
    697: ("ReturnToTitle", "flow",
          "Kick off the return-to-title sequence via app relaunch. Dev menu uses this "
          "after FadeScreen(16, 1500) + WaitForFade. No args.", []),
})

# ---- cutscene-beat + fade + audio ops decoded 2026-07-07 (from bank 292 @0x0878 test menu) ---
# Bank 292 @0x0878 is the 25-choice ＊Confirm Motion / ＊Ackna Battle / ... test menu; each
# branch fires WarpToMap (op 332) with a distinct (map, x, y, event id) tuple.
_M.update({
    335: ("FadeScreenToClear", "screen",
          "Fade the screen overlay back toward CLEAR (target alpha 0 = fully transparent, "
          "revealing the scene) over arg0/100 frames -- the reveal counterpart of op 334 "
          "FadeScreen. Re-launches the current dual-screen fade task on both channels toward "
          "alpha 0 via FadeTask_Init(0.0, arg0/100, channel), keeping the current overlay colour. "
          "CORRECTION: earlier called 'FadeChangeKindOnly' with a 'kind' arg -- verified the single "
          "arg is the DURATION (feeds FadeTask_Init's frame_count) and the target is always clear, "
          "NOT a kind selector. Corpus arg values (6000/12000/18000...) match op334's durations.",
          ["duration (frames = arg0/100; 6000 ~= 1s)"]),
})

# ---- ops from bank 21 NPC-debug scene (2026-07-07) ----
# 6 more high-frequency uncurated ops named by RE'ing their handlers.
_M.update({
    217: ("ApplyFriendshipDelta", "actor",
          "Modify an NPC's friendship XP or absolute friendship. **3 args**: "
          "npc_id, mode, xp_or_value. The mode is arg1's TOKEN KIND, not its value "
          "(ScriptVM_Op_ApplyFriendshipDeltaToNpc, RF4S.exe+0x1FD2B0, reads the kind slot at "
          "idx-4): a `null` leaf = kind 4 = **ADD** (`Npc_AddFriendshipXpAndProcessLevelUp(npc, +xp)`), "
          "`zero` = kind 5 = **SUBTRACT** (`... , -xp)`), `self` = kind 6 = **SET absolute** "
          "(`Npc_SetFriendshipPointsAbsoluteAndCheckMaxAchievement(npc, value)`); listings print "
          "them add / sub / set. All 283 shipped uses are add. npc_id >= 48 is ignored. "
          "**Special: npc_id == 22 → dynamically resolves to the CHILD NPC id** "
          "via `GameFlags_ReadField(0, GF_REG_CHILD_ID, 5)`. That confirms slot "
          "22 = Son is the runtime child-actor slot (paired with slot 23 = Daughter). "
          "The developers' '＊Date' test branch adds 99999999 xp (instant max friendship).",
          ["npc id", "mode (add / sub / set = the null / zero / self leaf)", "xp/value"]),
    387: ("PlaySfxWithNpcRemap", "audio",
          "Play SFX by id, applying an NPC-variant remap (calls "
          "`Sfx_PlayByIdWithNpcVariantRemap(sfx_id)`). **The IDA name "
          "`QueueDispatchEffect` is misleading -- this is actually an SFX play "
          "op, not an effects dispatcher.** The 'variant remap' picks a "
          "per-NPC voice / footstep variant when the same base sfx id is used "
          "across characters.",
          ["sfx id"]),
})

# ---- ops audited 2026-07-07 against IDA dispatch table (g_sceneActionHandlerTable) ----
# Full 763-slot table cross-checked; 711 already matched. Renames picked up + all
# 12 previously-anonymous sub_ handlers RE'd and named. Total: 763/763 named.
_M.update({
    1:   ("SetDialogueSuppressed", "dialogue",
          "1 makes every following DIALOG skip its line, 0 shows lines again: bit 3 (0x8) of "
          "the scene control word at ctx+120, read by the DIALOG handler. Turning it on while a "
          "box is still open freezes the scene; see refdata/opcode_table.json.",
          ["suppressed"]),
    215: ("ClearNpcStoryFlag", "flag",
          "Mirror of op 214 `SetNpcStoryFlag`: clears the 'NPC has appeared' "
          "flag bit `981 + arg` for one NPC. Uses the same NPC slot bounds "
          "(1..47) and same flag bit formula, just AND-NOT instead of OR.",
          ["npc id"]),
    216: ("QueryNpcInCurrentArea", "query",
          "Query -> VM register: `Npc_IsInCurrentArea(npc_id)` -- 1 if the "
          "given NPC's actor is spawned in the currently-loaded room/area, "
          "else 0. Distinct from op 282 `QueryNpcPresent` which checks the "
          "spawn+visible actor+568 flag.",
          ["npc id"]),
    232: ("QueryNpcProbeStateAt7300", "query",
          "Query -> VM register: 1 if the NPC is hidden, else 0 (the handler "
          "Script_VMOp_HasNpcGreetedToday returns Npc_IsDailyGreetingDone(npc_id), RF4S.exe+0x227300; "
          "the query counterpart of SkipNpcDailyGreeting). Only fires for npc id < 48.",
          ["npc id"]),
    245: ("QueryGiftAffinity", "query",
          "Query -> VM register: "
          "`Npc_GetGiftAffinityHashByItemAndCharId(npc_id, {item_id & 0x7FF})`. "
          "Returns the NPC's gift-affinity hash for the given item -- values "
          "like 'loved / liked / disliked / hated' as per rf3PresentNpc (see "
          "the gift preferences memory). item_id is masked to 11 bits (0..2047).",
          ["npc id", "item id"]),
    295: ("ApplyNpcScheduleAndClearMaskBit", "actor",
          "Applies an NPC's schedule for a given calendar day: "
          "`NpcSchedule_ResetParsePlanAndApplyCalendar(npc_id, day_arg)` + "
          "clears bit `1 << npc_id` in the scene ctx's schedule-dirty mask "
          "at [+352]. Takes 2 args (npc_id, day_of_week_or_offset).",
          ["npc id", "day arg"]),
    301: ("ApplyNpcScheduleForToday", "actor",
          "Recompute today's schedule for the given NPC: reads the NPC's "
          "cached daily state at npc[+17], overrides with "
          "`Schedule_GetNpcStateForToday(npc_id)` if the npc[+228] override "
          "bit 1 is clear, then applies via "
          "`NpcSchedule_ResetParsePlanAndApplyCalendar`. Distinct from op 298 "
          "which applies a PENDING plan.",
          ["npc id"]),
    433: ("QueryFishSizeRecords", "query",
          "Query the player's caught-fish size records for the given fish id. Writes "
          "TWO results: the BIGGEST recorded size (FishRecord_GetBestSize) to query "
          "register 0 (ctx+64), and the SMALLEST recorded size (FishRecord_GetSmallestSize) "
          "to query register 1 (ctx+68). Confirmed by decompile -- an earlier label mis-guessed "
          "this as a craft-record query, but both results are fish-size records (biggest + smallest).",
          ["fish id"]),
    698: ("SetShopkeeperMessage", "dialogue",
          "Set the active shop's shopkeeper message/greeting line to `arg`. "
          "Writes arg (a message index) into the 10-bit packed GameFlag field "
          "3006 = REG_JUSTM_MESSAGE (so the chosen greeting persists), then "
          "FMenu_SetShopMessageTextFromArchive(arg): loads locale text archive 15206 "
          "(0x3B66), copies entry[arg] (clamped to <360) into the shop's "
          "dialogue-text sprite and reveals it with the typewriter effect. "
          "CORRECTION: this is NOT an achievement. The raw handler id 39870 "
          "decodes (via GameFlags_WriteField) to packed-flag id 3006, width 10 -- "
          "and 3006 is not among the ~30 named-achievement switch cases, so it "
          "falls through to a plain packed-flag write. The IDA name "
          "`WriteJustmMessageRegAndCallback` is accurate (Justm = the shopkeeper "
          "message register). Corpus: bank 292 @0x0e7e sets arg=244.",
          ["shopkeeper message index (0-359, indexes locale text archive 15206)"]),
})

# ---- ops decoded 2026-07-07 from bank 292 @0x0888 (dev flag-toggle test menu) ----
_M.update({
    214: ("SetNpcStoryFlag", "flag",
          "Set the 'NPC has appeared in story' flag for NPC(s). "
          "**arg == 0**: sets the flag for **all NPCs 1..23** (bulk unlock). "
          "**arg != 0**: sets the flag for just that NPC. "
          "Flag address = GameFlags bit `arg + 981` (so NPC #1 = flag 982, etc.). "
          "Distinct from op 233's flag range. Used by the dev 'Boy'/'Girl' name-entry "
          "path to bulk-set all NPCs to visible after switching gender.",
          ["npc id (0 = all)"]),
})

# op 379 PlayMusic already has a decent mnemonic from the fallback -- override with a
# proper curated description.
_M[379] = ("PlayMusic", "audio",
    "Switch background music with a crossfade. **arg = -1 restores the contextual BGM** "
    "(clears the scripted-BGM marker bit 0x10000000 at ctx+116, calls "
    "Scene_ApplyContextualBGM). Otherwise starts BGM #arg via BGM_SwitchWithCrossfade and "
    "sets the scripted-BGM marker so the contextual picker won't override it. Also sets the "
    "'first scripted BGM played' game-flag (packed id 1072, via GameFlags_WritePacked_OrAchievement) -- an "
    "internal milestone flag, not a Steam achievement. Special case: `arg == 16777332` triggers "
    "an additional Sfx_ApplyVoiceVolume with category-bias 45.",
    ["bgm id (or -1 = restore)"])

# ---- camera ops decoded 2026-07-11 (ops 186-203; handlers RF4S.exe+0x20b150..0x20c2f0) ----
# All camera anchors are stored as Q12 world coords (arg tiles << 12) in g_scriptMarkAnchorPosQ12;
# most first set receiver flag 0x40000 ("script touched the camera this frame"). Player-lock
# helpers Player_SetActorFlag1ForAllPlayers / Player_SetActorFlag4ForAllPlayers stop the player drifting while the camera is scripted.
_M.update({
    186: ("SetCameraPosition", "screen",
          "Set the camera ANCHOR at world tile (x, y) (g_scriptMarkAnchorPosQ12, clamped to "
          "the map's camera bounds). arg2 non-zero additionally SNAPS the live camera to the "
          "anchor immediately (writes g_cameraPosQ12 + the map task's scroll origin) — the "
          "instant-cut variant; arg2 = 0 leaves the camera to ease there. The opening parks "
          "its vista with (353, 0, snap=1). Coords are tiles (stored as Q12). IDA-verified "
          "2026-08-10.",
          ["x (tiles)", "y (tiles)", "snap camera now (0/1)"]),
    187: ("ReattachCameraToActor", "screen",
          "Re-attach the camera rig to the player(s) and optionally recenter on an actor. "
          "BLOCKING: holds the scene until it settles. arg0 = actor scene-slot to center on "
          "(0 = player); arg1 != 0 also hard-snaps the anchor + player pos to that actor. "
          "Near-duplicate of op 191 (ResetCameraToActor).",
          ["actor slot (0=player)", "snap position (0/1)"]),
    189: ("ResetCameraToPlayer", "screen",
          "Reset the camera rig to the player and re-attach it (single- or co-op). arg != 0 "
          "also hard-snaps the camera anchor + map scroll origin to the player's current tile. "
          "Use after teleporting the player to kill the follow lag.",
          ["snap (0/1)"]),
    190: ("SetCameraTarget", "screen",
          "PAN the camera to world tile (x, y): sets the anchor (clamped to camera bounds) and "
          "starts a constant-velocity pan toward it. Also locks player movement (flags 1+4) so "
          "the shot holds. arg2 = the PAN SPEED: speed×4096/100 Q12, capped 0xF000 — i.e. "
          "arg2/100 tiles per frame, max 15 (shipped scenes use 50-400 = 0.5..4 tiles/frame; "
          "the opening's deck pans use 200 = 2 tiles/frame). Follow with "
          "WaitCameraAtMark (op 195) to HOLD the scene until the pan arrives — that "
          "pairing is what paces the between-line camera sweeps. IDA-verified 2026-08-10 "
          "(Camera_ComputeDistanceVectorToTarget; the old 'zoom/distance' label was wrong — "
          "zoom is op 202).",
          ["x (tiles)", "y (tiles)", "pan speed (/100 tiles per frame, cap 15)"]),
    194: ("FocusCameraOnPlayer", "screen",
          "Ease the camera onto the player and BLOCK the scene for a few frames while it "
          "settles. No args. Handy to 'return to the hero' between cutscene shots.",
          []),
    197: ("ShakeCamera", "screen",
          "Shake / jitter the screen (PlayerEffect_RequestJitterByKind -> tick "
          "PlayerEffect_TickJitterByKind). arg0 = jitter KIND 1-6 (a shake pattern; the value is "
          "also a priority -- a running shake only escalates to a HIGHER kind, never a lower one): "
          "1 = light 12-step jitter, 2 = medium 12-step signed jitter, 3 = short sharp 4-step "
          "jitter, 4 = long 22-step jitter, 5 = heavy 22-step jitter (2x amplitude), 6 = rotational "
          "rumble (sin-cos with decay). kind 0 resets/stops the shake. arg1 = duration in frames. "
          "Used for impacts, quakes, explosions.",
          ["kind (1-6, 0=stop)", "duration"]),
    199: ("SetCameraTargetActor", "screen",
          "Pan the camera to an actor chosen by scene-slot (same 0..0x2F slot space as dialogue "
          "speakers; slot 0 / empty slot falls back to the player). Anchors on the actor's world "
          "position and recomputes the follow vector; locks player movement. arg1 = the same "
          "PAN-SPEED channel as SetCameraTarget (op 190): arg1/100 tiles per frame, cap 15 "
          "(shipped scenes use ~100-400).",
          ["actor slot", "pan speed (/100 tiles per frame)"]),
    202: ("SetCameraZoom", "screen",
          "Set camera zoom / pull-back distance. arg1 == 0 -> set the camera distance field to "
          "(arg0 - 1500) px (smaller arg0 = closer). arg1 != 0 -> reset the camera to its "
          "default rig instead.",
          ["zoom (distance = arg-1500 px)", "reset (0=set zoom, 1=reset)"]),
    203: ("RotatePlayerToInputDir", "actor",
          "Turn the player to face the current input/stick direction (uses the active input "
          "context's facing; 0xFFFF = keep current facing when input is suppressed). arg selects "
          "an instant vs. eased turn.",
          ["immediate (0=ease, 1=instant)"]),
})


# ---- actor choreography decoded 2026-07-11 (ops 77-142; move/turn/anim primitives) ----
# Shared conventions (IDA-verified): arg0 = actor char id (0 = player, 1..47 = villager NPC,
# 48..0x2F cap; >=0x30 usually bails). Positions are TILES (stored internally <<12 = Q12).
# Facing angles are DEGREES (move cmds convert via *181 -> u16 where 65536 = 360 deg).
# The "relative offset" move family builds a move command and differs only by move-kind +
# whether it faces / locks / interrupts the actor's AI (see per-op notes).
_M.update({
    99: ("TeleportActor", "actor",
         "Instantly warp an actor to a tile. arg0 = actor (char id, 0 = player). arg1/arg2 = "
         "destination X/Y in tiles. The player is snapped to the ground; an NPC is streamed "
         "in if needed. No walk animation — use the Move* ops for a visible walk.",
         ["actor (char id, 0=player)", "x (tiles)", "y (tiles)"]),
    107: ("TurnActorToFaceTarget", "actor",
          "Rotate one actor to look at another — the workhorse for 'actors face each other "
          "before dialogue'. arg0 = turner (0 = player, 1..47 = villager, >=48 = monster). "
          "arg1 = look-at target (same encoding). arg2 = mode: 0 = snap instantly, non-zero "
          "= ease/lerp toward it.",
          ["turner (char id, 0=player)", "look-at target (char id)", "mode (0=snap, else ease)"]),
    115: ("MoveActorByOffset_LockAI", "actor",
          "Walk an actor by a RELATIVE tile offset, then LOCK its AI so nothing interrupts "
          "the pose (used when actors slide into staged cutscene positions and must hold). "
          "Faces the given angle. args: actor (0=player), dx, dy (tiles), facing degrees, "
          "speed, jump flag.",
          ["actor (char id, 0=player)", "dx (tiles)", "dy (tiles)", "facing (degrees)", "speed", "jump (0/1)"]),
    123: ("MoveActorByOffset", "actor",
          "Basic cutscene walk: move an actor by a RELATIVE tile offset and face the given "
          "angle (no AI changes). args: actor (0=player), dx, dy (tiles), facing degrees, "
          "speed, jump flag.",
          ["actor (char id, 0=player)", "dx (tiles)", "dy (tiles)", "facing (degrees)", "speed", "jump (0/1)"]),
    142: ("MoveSceneActorToTile", "actor",
          "Move the scene-controlled actor (the player) to an ABSOLUTE tile, with facing. "
          "arg0/arg1 = X/Y tiles, arg2 = facing degrees, arg3 = speed, arg4 = run flag "
          "(0 = walk, non-zero = run). No char-id arg — always the scene's own actor.",
          ["x (tiles)", "y (tiles)", "facing (degrees)", "speed", "run (0/1)"]),
})


# ---- actor effects / triggers / rotation decoded 2026-07-11 (ops 83-151, second pass) ----
_M.update({
    139: ("ApplyEffectToActor", "effect",
          "Apply an Effect (damage / heal / status / VFX) to an actor via "
          "Effect_ApplyByKindAndSpawn — the scripted-effect entry point. arg0 = actor "
          "(char id, 0 = player). arg1 = effect kind id (dispatched by g_effectKindSpawnTable "
          "to spawn the visual + apply the gameplay effect). Used for scripted magic, "
          "sparkles, heals, and status in cutscenes.",
          ["actor (char id, 0=player)", "effect kind id"]),
    144: ("MoveSceneActorStraight", "actor",
          "Move the scene-controlled actor (the player) in a straight line to an ABSOLUTE "
          "tile, KEEPING its current facing (no turn). arg0/arg1 = X/Y tiles, arg2 = speed, "
          "arg3 = run flag (0 = walk, non-zero = run). Like op 142 but without a facing arg.",
          ["x (tiles)", "y (tiles)", "speed", "run (0/1)"]),
    150: ("TriggerActionAtPos", "effect",
          "Spawn a scripted Action (effect/task) at a world tile via Action_TriggerActor "
          "(g_actionConstructorTable dispatch — the 'Action 0xNN' family). arg0 = action id. "
          "arg1/arg2 = X/Y tiles. Action ids 65 and 105 auto-target the player's position "
          "instead of the passed tile.",
          ["action id", "x (tiles)", "y (tiles)"]),
})


# ---- actor 'wait-for' query ops decoded 2026-07-11 (81-152) — used in cutscene wait-loops ----
# These write a boolean to the VM query register (read via a following BR_Z/BR_NZ). The common
# cutscene idiom is: start a Move/Turn/Anim, then loop on the matching Query until it reports done.
_M.update({
    131: ("QueryActorBeyondRange", "query",
          "1 while the actor is FARTHER than [range] tiles from its target marker (the "
          "player checks a global target position; an NPC checks its own move target); 0 "
          "once within range. arg0 = actor (char id, 0 = player), arg1 = range in tiles. "
          "Wait-until-arrived predicate. (Handler is named 'InRange' but returns 1 when far.)",
          ["actor (char id, 0=player)", "range (tiles)"]),
    135: ("QueryActorTilePosition", "query",
          "Read an actor's current tile position: writes X and Y (tiles) to the VM output "
          "slots for a following read. arg0 = actor (char id, 0 = player). Falls back to the "
          "NPC's backup position if its actor isn't spawned.",
          ["actor (char id, 0=player)"]),
    145: ("QueryPlayerTurnBusy", "query",
          "1 while the player is still turning / settling their facing (or in a scripted-busy "
          "state); 0 when idle. No args. Wait for the player's turn to finish before the next "
          "beat.",
          []),
})


# ---- calendar-event-actor family decoded 2026-07-11 (ops 153-182) ------------------
# "Event actors" are the festival / parade / cutscene NPCs registered in g_calendarEventMng
# (a 32-slot registry, 40-byte stride). EventSpawnNpc (op 153) adds one keyed by its char id; the
# later ops address a spawned actor by that same char id ("event key" = arg0). Positions are
# tiles (Q12); facings are degrees (×181 -> u16). This is how a scene choreographs its own
# temporary cast without touching the persistent world NPCs.
_M.update({
    153: ("EventSpawnNpc", "actor",
          "Spawn (or reposition) an event/cutscene NPC in the calendar-event registry. "
          "arg0 = the CHAR id (which character/model — record WORD1); arg1 = the EVENT KEY "
          "(a scene-local handle — record WORD0, what every later move/face/anim/query op "
          "addresses); arg2/arg3 = X/Y tiles; arg4 = facing degrees (×181 -> u16). If the "
          "key is already registered the op just updates position + facing; otherwise it "
          "claims a new slot (32 max, pending-placement bit set for the streamer). The deck "
          "opening spawns char 324 'Barrel' ×7, 331 'Captain', 31 Traveler this way (331 and "
          "31 share field model NPC_TRAVELER_M2 — rf3NpcParam+272 is 321 for both; the model "
          "resolves as chr-TOC[+272 + 933], or mons-TOC[+272 + 12584] for monster-body chars, "
          "per Actor_RecomputeAllStats). ARG ORDER IDA-VERIFIED 2026-08-17 (the old 'scene "
          "id, char id' labels were swapped): Script_VMOp_SpawnEventActor "
          "matches records on arg1 and stores arg0 as the char word.",
          ["char id (model)", "event key (scene-local handle)", "x (tiles)", "y (tiles)",
           "facing (degrees)"]),
    160: ("EventNpcWalkToTile", "actor",
          "Walk/run a spawned event NPC to an ABSOLUTE tile (updates an in-progress move or "
          "starts a new one). arg0 = event key, arg1/arg2 = X/Y tiles, arg3 = speed "
          "coefficient (scaled by the NPC's walk/run base speed), arg4 = run flag "
          "(0 = walk, non-zero = run).",
          ["event key", "x (tiles)", "y (tiles)", "speed", "run (0/1)"]),
    167: ("EventActorPlayAnim", "actor",
          "Play an animation on a spawned event actor. arg0 = event key, arg1 = "
          "anim id, arg2 = loop flag (non-zero = keep repeating). Pair with "
          "QueryEventActorAnimBusy (op 169) to wait for a one-shot anim to finish.",
          ["event key", "anim id", "loop (0/1)"]),
    171: ("SetEventActorAlpha", "actor",
          "Fade a spawned event actor: arg1 = alpha percent 0..100 (packed into the sprite's "
          "5-bit alpha). arg1 == 0 HIDES the actor (sets its hide flag). arg0 = event key "
          "(char id). Used for ghost/translucent/fade-in-out cutscene effects.",
          ["event key", "alpha % (0-100, 0=hide)"]),
    180: ("KillEventActor", "actor",
          "Kill a spawned event actor with the full death sequence — knockout flags, a "
          "downward knockback impulse, the death-pose animation, and the fall-physics tick. "
          "arg0 = event key. For scripted deaths in cutscenes (e.g. a boss "
          "collapsing).",
          ["event key"]),
    182: ("QueryEventActorTilePosition", "query",
          "Read a spawned event actor's current tile position: writes X and Y (tiles) to the "
          "VM output slots for a following read. arg0 = event key. The event-actor "
          "counterpart of QueryActorTilePosition (op 135).",
          ["event key"]),
})


# ---- calendar-event-actor + map-atmosphere ops decoded 2026-07-11 (2nd pass: 154-181) ----
_M.update({
    154: ("EventSpawnNpcVariant", "actor",
          "Spawn an event/cutscene NPC that carries a pose/scene VARIANT index — always "
          "claims a NEW registry slot (unlike op 153 which updates in place). arg0 = char id "
          "(which character/model), arg1 = event key (the scene-local handle later ops "
          "address — same char/key order as op 153), arg2/arg3 = X/Y tiles, arg4 = facing "
          "degrees, arg5 = reserved (pass 0), arg6 = variant index (stored as index-1). Use "
          "for staged NPCs with an alternate pose/outfit variant.",
          ["char id (model)", "event key (scene-local handle)", "x (tiles)", "y (tiles)",
           "facing (degrees)", "(reserved, 0)", "variant index"]),
    158: ("SetMapAmbientColor", "screen",
          "Set the map's ambient RGB tint (mood / time-of-day lighting) — writes the three "
          "internal colour triples. arg0/arg1/arg2 = R/G/B (0-255). arg3 = apply now "
          "(non-zero forces an immediate palette reload; 0 defers to the next map tick).",
          ["R (0-255)", "G (0-255)", "B (0-255)", "apply now (0/1)"]),
    159: ("SwapMapPalette", "screen",
          "Swap the current map to its staged alternate palette bank (day/night, weather, or "
          "a magic/mood shift) by copying the staging colours over the active ones. arg0 = "
          "apply now (non-zero = immediate palette reload; 0 = deferred).",
          ["apply now (0/1)"]),
    166: ("ApplyEffectToEventActor", "effect",
          "Apply an Effect (damage / heal / status / VFX) to a spawned event actor via "
          "Effect_ApplyByKindAndSpawn — the event-actor twin of op 139. arg0 = event key "
          "(char id), arg1 = effect kind id.",
          ["event key", "effect kind id"]),
    181: ("TurnEventActorIntoNpc", "actor",
          "Cleanly despawn a spawned event actor — NO death animation (contrast op 180 "
          "KillEventActor). arg0 = event key. Runs the canonical companion-dismiss "
          "reset and decrements the event-companion count; the player can't be dismissed.",
          ["event key"]),
})


# ---- calendar-event-actor family, 3rd pass 2026-07-11 (155-183) --------------------
_M.update({
    165: ("TriggerActionAtEventActor", "effect",
          "Spawn a scripted Action (VFX / SFX / trigger) at a spawned event actor's position "
          "via Action_TriggerAttacker. arg0 = event key, arg1 = action id. The "
          "event-actor counterpart of TriggerActionAtPos (op 150).",
          ["event key", "action id"]),
    179: ("QueryEventActorTurning", "query",
          "1 while a spawned event actor is still turning toward its target facing "
          "(target != current); 0 once settled. arg0 = event key. Wait-for-turn "
          "predicate — the event-actor twin of WaitActorAuxYaw (op 113).",
          ["event key"]),
})


# ---- calendar-event-actor family, 4th pass 2026-07-11 (157-177) --------------------
_M.update({
    157: ("SpawnMapEntity", "effect",
          "Spawn a map entity, dispatched by TYPE ID to the right spawner — the central "
          "script-side object-placement op (handler ScriptVMOp_SpawnMapEntityByTypeIdDispatchTable). "
          "arg0 = entity type id: <20 → special trigger (treasure/quest item, Map_HandleSpecialTriggerEntity), "
          "20-195 → placed game object 'pg_mobj' (Actor_AllocTask 65 → MapObj_SetupActorByTypeId), "
          "196-335 → interactive object (door/stove/lift, Map_SpawnInteractiveObject), "
          "336+ → decoration/scenery (MapDecoration_Spawn). arg1/arg2 = position, arg3 = facing "
          "(passed as DEGREES, handler multiplies by 182 = 65536/360 → u16 angle), arg4 = sub-param "
          "(handler multiplies by 40). args5-9 = up to 5 optional EXTRA placement params copied into "
          "the entity's setup struct; their meaning is ENTITY-TYPE-SPECIFIC (flags, linked ids, "
          "size, etc.). Dynamic prop/decor placement from a scene.",
          ["entity type id", "param 1 (x/pos)", "param 2 (y/pos)", "facing (degrees)",
           "sub-param (x40)", "extra 5 (type-specific)", "extra 6 (type-specific)",
           "flag 7 (0/1, type-specific)", "flag 8 (0/1, type-specific)", "extra 9 (type-specific)"]),
    164: ("QueryEventActorMoving", "query",
          "1 while a spawned event actor is still walking OR turning; 0 once it has both "
          "arrived and settled its facing. arg0 = event key. The COMBINED wait "
          "predicate — op 179 checks only turning, this also checks arrival.",
          ["event key"]),
    177: ("EventActorEnterIdle", "actor",
          "Return a spawned event actor to its idle state, loading the default idle animation "
          "for its entity type. arg0 = event key. Use to reset an actor after a "
          "scripted anim/pose.",
          ["event key"]),
})


# ---- calendar-event-actor family, 5th pass 2026-07-11 (156-184) — completes 153-184 ----
_M.update({
    156: ("UnregisterEventActor", "actor",
          "Remove a spawned event actor from the calendar-event registry, matching on BOTH "
          "char id and event key; frees its slot on the next sweep. arg0 = char id, arg1 = "
          "event key. Registry-level cleanup — no death animation and no dismiss reset "
          "(contrast KillEventActor op 180 / TurnEventActorIntoNpc op 181). Use when a scene ends.",
          ["char id", "event key"]),
    168: ("EventActorResyncAnimFrame", "actor",
          "Force a spawned event actor to re-sync its animation frame from its widget after a "
          "state swap (fixes a one-frame visual pop when the anim state changes). arg0 = event "
          "key (char id). Low-level; pair with an anim change if you see a flicker.",
          ["event key"]),
})


# ---- dialogue speaker/emote ops decoded 2026-07-11 (93, 98) ------------------------
_M.update({
    93: ("SetDialogueBoxStyle", "dialogue",
         "Set the dialogue box style from an argument (the general form of ops 94-97, and the "
         "only way to get style 4). " + 'It sets the MESSAGE-BOX STYLE, not a face (verified 2026-09-25: Dialogue_SetSpeakerEmoteAndRetargetPortrait RF4S.exe+0x234E20 stores it at dialogue task +160; Dialogue_RetargetPortraitAndBubble +0x2380B0 then shows window art talk_win<n> (archive 15851+n) and tail talk_hige<n> (15846+n); Dialogue_SetTimingState +0x238350 adds the effect). 0 = normal box, 1 = shout (jagged box; everything shakes for 10 frames and the screen flashes), 2 = thought (cloud box with a bubble-trail tail; the box floats for ~1 s -- it does not delay the line), 3 = trembling (wavy box; a 10-frame sideways shake), 4 = tail only (no box). 5-7 would read unrelated textures. Lasts until changed or the dialogue box closes. The tail points at the side of the last speaker cue (an even SetSpeaker op = left, odd = right) and only shows while a portrait is up on that side for a named character: narration and SetSpeakerVoice name plates get no tail (DialogueBox_TickStateMachine +0x235BF0).',
         ["box style (0 normal, 1 shout, 2 thought, 3 trembling, 4 tail only)"]),
})


# ---- NPC visibility / animation / cutscene-teardown ops decoded 2026-07-11 (230-254) ----
_M.update({
    233: ("SkipNpcDailyGreeting", "actor",
          "Hide an NPC — make it invisible/despawned and set its hidden state bit. arg0 = npc "
          "(char id). Removes the NPC from the scene; pair with a schedule refresh or "
          "SetNpcVisibleFlag to bring it back.",
          ["npc (char id)"]),
    248: ("SetNpcVisibleFlag", "actor",
          "Toggle an NPC's visibility/interaction suppression bit (record +52 bit 0x800). "
          "arg0 = npc (char id), arg1 = visible: non-zero clears the suppress bit (NPC shown "
          "/ interactive), 0 sets it (suppressed).",
          ["npc (char id)", "visible (0=suppressed)"]),
    252: ("SetActorAnimSpeedScale", "actor",
          "Set an actor's animation speed multiplier. arg0 = actor (char id, 0 = player), "
          "arg1 = speed percent (÷100: 100 = normal, 50 = slow-mo, 200 = fast). The regular-"
          "actor twin of SetEventActorAnimSpeed (op 170).",
          ["actor (char id, 0=player)", "speed % (100 = 1.0×)"]),
    254: ("SetActorAnimFrameDirect", "actor",
          "Snap an actor to a specific animation FRAME with no interpolation — a freeze-frame "
          "/ posed shot. arg0 = actor (char id, 0 = player), arg1 = frame number. Combine "
          "with speed scale 0 (op 252) to hold a pose.",
          ["actor (char id, 0=player)", "frame number"]),
})


# ---- NPC streaming / dialogue-lock / status ops decoded 2026-07-11 (225-256) --------
_M.update({
    225: ("StreamInNpc", "actor",
          "Bring an NPC into the scene (load its actor into rendering + activate it). arg0 = "
          "npc (char id, <48). arg1 = mode: non-zero force-streams the NPC (full load), 0 "
          "just re-applies its schedule state without streaming. Use before an NPC is needed "
          "on screen. To also place it, use StreamInNpcAtPos (op 246).",
          ["npc (char id)", "mode (0=refresh, 1=force load)"]),
    243: ("EndDialogueLock", "dialogue",
          "End the dialogue lock — release the player-input / scene lock held during a "
          "conversation and hand control back to the player. arg0 = 0 performs the release "
          "(non-zero is a no-op). Use to close out a conversation.",
          ["mode (0 = end lock)"]),
    250: ("SyncActorAnimFrame", "actor",
          "Force an actor to re-sync its animation frame from its widget after a programmatic "
          "state change (fixes a one-frame pose pop). arg0 = actor (char id, 0 = player). The "
          "regular-actor twin of EventActorResyncAnimFrame (op 168).",
          ["actor (char id, 0=player)"]),
})


# ---- NPC friendship / current-interaction / schedule ops decoded 2026-07-11 (218-271) ----
_M.update({
    218: ("QueryNpcFriendshipLevel", "query",
          "Read an NPC's friendship LEVEL (not raw points) into the VM output slot. arg0 = "
          "npc (char id); 0 uses the NPC the player is currently talking to. -1 if the NPC "
          "isn't found.",
          ["npc (char id, 0=current)"]),
    262: ("QueryCurrentInteractionNpc", "query",
          "Read the char id of the NPC the player is currently talking to / interacting with "
          "into the VM output slot (0xFFFF if none). Use to branch a shared script on which "
          "NPC triggered it.",
          []),
})


# ---- NPC state query ops decoded 2026-07-11 (226-280) — dialogue-branch gates --------
_M.update({
    232: ("QueryNpcHidden", "query",
          "Read whether an NPC is hidden (1 = hidden, 0 = visible) into the VM output. arg0 = "
          "npc (char id). The query counterpart to SkipNpcDailyGreeting (op 233).",
          ["npc (char id)"]),
    273: ("QueryNpcPresent", "query",
          "Read whether an NPC is 'present' — its record's present-in-town bit (0x400000), "
          "i.e. currently around/available — into the VM output. arg0 = npc (char id); arg0 = "
          "0 instead returns the COUNT of villagers (1..23) currently present.",
          ["npc (char id, 0=count all)"]),
    280: ("QueryNpcFacing", "query",
          "Read an NPC's facing direction as a 3-bit octant index (0..7, from record +55) "
          "into the VM output. arg0 = npc (char id). Branch on which way an NPC is looking.",
          ["npc (char id)"]),
})


# ---- NPC schedule / grouping / eligibility query ops decoded 2026-07-11 (227-269) ----
_M.update({
    227: ("QueryNpcScheduleIsOneOf", "query",
          "Read 1 iff an NPC's current schedule id matches ANY id in the provided list. "
          "arg0 = npc (char id); 0 tests the PLAYER's scene/menu-state field instead, 22 "
          "tests the current child id (game flag). arg1 = list count, then that many "
          "schedule ids. Multi-value 'what is this NPC doing' branch.",
          ["npc (char id, 0=player)", "count", "schedule id …"]),
    240: ("QueryNpcGroupPresentNearby", "query",
          "Read 1 iff a GROUP of NPCs are all present, available, and clustered within a "
          "distance of the primary one — the gate for group conversations/events (e.g. the "
          "required characters are gathered). arg0 = max distance (tiles), arg1 = count of "
          "extra NPCs, arg2 = primary npc (char id), then that many more npc ids.",
          ["max distance (tiles)", "count", "primary npc", "other npc …"]),
})


# ---- NPC lock / engage / talk-gesture ops decoded 2026-07-11 (222-289) --------------
_M.update({
    222: ("LockNpcPose", "actor",
          "Freeze an NPC's facing/pose for a cutscene: snapshots its current facing and sets "
          "the pose-locked + action-pending flags so it holds still and won't turn on its "
          "own. arg0 = npc (char id).",
          ["npc (char id)"]),
    223: ("SetNpcEngaged", "actor",
          "Pull an NPC out of (or back into) its daily schedule so it can take part in a "
          "scene. arg0 = npc (char id), arg1 = engaged: non-zero pauses the NPC's routine "
          "('engaged'), 0 releases it back to its schedule. Refreshes its schedule state "
          "immediately.",
          ["npc (char id)", "engaged (0=release, 1=engage)"]),
    289: ("TriggerActorTalkAnim", "dialogue",
          "Start an actor's visible 'talking' gesture (animation 240) and its talk-indicator "
          "overlay — the speaking animation to sync with a dialogue line. arg0 = actor "
          "(char id, 0 = player). For the player it also begins a scripted-talk interaction "
          "(auto-stops walking).",
          ["actor (char id, 0=player)"]),
})


# ---- NPC outfit + marriage/family story ops decoded 2026-07-11 (287-292) ------------
_M.update({
    290: ("FireFamilyEventAchievements", "actor",
          "Write a packed marriage/family-status game-flag (packed id 4391 -> value 2; IDA "
          "names this 'set wife status 2') and run the family birthday/anniversary milestone "
          "check for today: compares the current date to the spouse's and children's birthdays "
          "and the wedding anniversary, setting the matching family-milestone game-flags. NOTE: "
          "these go through GameFlags_WritePacked_OrAchievement (packed game-flags), NOT the ~30 real Steam "
          "achievements -- so 4391 is a game-flag write, not an achievement unlock. No args. "
          "Used in anniversary/birthday cutscenes.",
          []),
    292: ("CommitMarriage", "actor",
          "The climax of a marriage scene: permanently record the player's spouse (the NPC "
          "chosen earlier via game flags), set the married-NPC save flag + marriage save-"
          "config bit, fire the four marriage achievements, and stage the announcement text. "
          "No args — the spouse is read from GameFlags.",
          []),
})


# ---- NPC schedule-reset / jitter ops decoded 2026-07-11 (293-303) -------------------
_M.update({
    293: ("ResetNpcDailySchedule", "actor",
          "Reset an NPC's daily schedule AND its AI to a state, putting it back on its normal "
          "routine and clearing any scene reservation for it. arg0 = npc (char id), arg1 = "
          "state, or -1 to auto-compute today's schedule state. Heavier than op 296 (also "
          "resets AI). Use at scene end to hand an NPC back to normal life.",
          ["npc (char id)", "state (-1 = auto)"]),
    295: ("ResetNpcScheduleWithState", "actor",
          "Reset an NPC's schedule to an EXPLICIT state — re-parses its schedule plan and "
          "applies the calendar, then clears its scene reservation. arg0 = npc (char id), "
          "arg1 = state. Like op 293 but always uses the given state (no auto-compute).",
          ["npc (char id)", "state"]),
    296: ("ApplyNpcScheduleState", "actor",
          "Apply a schedule STATE to an NPC (its position/pose for that state) and clear its "
          "scene reservation. arg0 = npc (char id), arg1 = state, or -1 to auto-compute "
          "today's. Lighter than op 293 — does not reset the NPC's AI.",
          ["npc (char id)", "state (-1 = auto)"]),
    302: ("SetNpcFriendshipJittered", "actor",
          "Write a randomized value to a per-NPC record field (+212): roughly 0.75×..1.1× the "
          "given value, varied by the shared RNG. arg0 = npc (char id), arg1 = base value. "
          "The handler treats +212 as a friendship-related field; the jitter gives NPCs "
          "slightly different values.",
          ["npc (char id)", "base value"]),
})


# ---- NPC/companion state-query + mount ops decoded 2026-07-11 (255-284) -------------
_M.update({
    282: ("QueryNpcActorPresent", "query",
          "Read whether an NPC's LIVE actor is spawned and visible in the current scene (its "
          "actor exists and the hidden bit is clear) into the VM output. arg0 = npc (char "
          "id). Distinct from QueryNpcPresent (op 273), which checks the town-roster flag.",
          ["npc (char id)"]),
    284: ("MountActor", "actor",
          "Mount an actor onto a rideable partner, or dismount. arg0 = actor (char id, 0 = "
          "player). arg1 = mount event key: 0 dismounts (drops to the ground), non-zero looks "
          "up the ride partner in the event registry by that key and starts the mount "
          "transition. Used for scripted riding (e.g. climbing onto a tamed monster).",
          ["actor (char id, 0=player)", "mount event key (0=dismount)"]),
})


# ---- NPC dialogue-wellness + schedule-place/pending ops decoded 2026-07-11 (260-299) ----
_M.update({
    281: ("SetNpcDateState", "actor",
          "Set an NPC's DATE STATE (3 bits at npc record +55; read by QueryNpcDateState, op 280, "
          "and em.bin's DATE_STATE query): 0 no date, 1 a date is promised for tomorrow, 2 the "
          "date is today, 3 on the date, 4 the date went well, 5 turned you down today. arg0 = npc "
          "(char id), arg1 = the state. Setting 4 also AWARDS friendship (up to the next level on "
          "the first date, otherwise +55). " + _DATE_LIFE,
          ["npc (char id)", "date state"]),
    298: ("ApplyPendingNpcPlan", "actor",
          "Apply an NPC's PENDING schedule plan for today — re-parses and applies its "
          "calendar-computed schedule, clears its scene reservation, and refreshes the "
          "story-progress cache. arg0 = npc (char id). Like op 296 but also snapshots story "
          "progress.",
          ["npc (char id)"]),
})


# ---- NPC seen/comment/flag + schedule-refresh + scene-state ops decoded 2026-07-11 (235-301) ----
_M.update({
    285: ("SetSceneReadyFlag", "flow",
          "Set a scene-state control bit (scene state +72 bit 0x1) when arg0 is 0 — a "
          "low-level 'wait / ready' marker the scene loop checks. arg0 = mode (0 sets it).",
          ["mode (0 = set flag)"]),
    301: ("RefreshNpcScheduleForToday", "actor",
          "Refresh an NPC's daily schedule for TODAY — computes its current-day state and "
          "re-parses/applies its schedule plan. arg0 = npc (char id). Like op 298 but does "
          "not clear the scene reservation or snapshot story progress.",
          ["npc (char id)"]),
})


# ---- NPC quest-gate / positioning / misc-query ops decoded 2026-07-11 (238-286) -----
_M.update({
    238: ("QueryQuestNpcsAvailable", "quest",
          "Read 1 iff a primary NPC and all listed NPCs are available (not busy / sleeping / "
          "already in an event) AND within a distance of the primary — the quest-event group "
          "gate. arg0 = max distance, arg1 = count of extra NPCs, arg2 = primary npc (char "
          "id), then that many more. Like op 240 but also requires the NPCs aren't already "
          "mid-event.",
          ["max distance", "count", "primary npc", "other npc …"]),
    247: ("QueryTileFacingTarget", "query",
          "Compute the tile one step in front of target B along the line from A to B — where "
          "A should stand to be adjacent to and facing B. Writes X and Y (tiles) to the VM "
          "output slots. arg0 = actor A (char id, 0 = player), arg1 = target B (char id). If "
          "already adjacent, returns A's own tile. Used to line NPCs up for a conversation.",
          ["actor A (char id, 0=player)", "target B (char id, 0=player)"]),
    278: ("QueryNpcFavoriteItem", "query",
          "Read one of an NPC's favorite/loved gift item ids (rolled) into the VM output. "
          "arg0 = npc (char id). Used to hint or pre-fill a gift in a scene.",
          ["npc (char id)"]),
    286: ("SetActorStateBitsLow16", "actor",
          "Set the LOW 16 bits of an actor's state bitfield (a short-form state code — walk / "
          "run / hit / talk, etc.), preserving the high status/animation flags. arg0 = actor "
          "(char id, 0 = player), arg1 = the new low-16 value. Advanced / low-level.",
          ["actor (char id, 0=player)", "state (low 16 bits)"]),
})


# ---- last NPC-block query ops decoded 2026-07-11 (220-288) — completes 214-303 -------
_M.update({
})


# ---- party heal/restore + NPC emote/outfit ops decoded 2026-07-11 (311-328) ---------
_M.update({
    311: ("HealPartyFull", "companion",
          "Fully heal the party — restores the player and both active companions to max HP. "
          "No args. Post-battle / rescue recovery scenes.",
          []),
    313: ("RestorePlayerRP", "actor",
          "Fully restore the player's RP (Rune Points) to max. No args.",
          []),
    314: ("CurePartyStatus", "companion",
          "Cure the standard status conditions on the whole party (player + both companions): "
          "poison, paralysis, sleep, seal, and cold. Fatigue and faint are NOT cleared. No "
          "args. For medicine / recovery scenes.",
          []),
})


# ---- NPC visibility/mood/outfit + player pose + greeting ops decoded 2026-07-11 (315-396) ----
_M.update({
    315: ("QueueNpcGreetingEvent", "actor",
          "Find the NPC standing near tile (x, y) — within ~16 tiles and in the active input "
          "context — and queue a greeting / wave interaction event with them. arg0/arg1 = X/Y "
          "tiles. Sets that NPC as the interaction subject.",
          ["x (tiles)", "y (tiles)"]),
})


# ---- player resource modify + give-item ops decoded 2026-07-11 (417-424) ------------
# (op 416 QueryPlayerVariable — the read counterpart — is curated via _STAT_QUERY_OPS below.)
_M.update({
    417: ("ModifyPlayerResource", "item",
          "Grant or take a player resource (Script_VMOp_ModifyPlayerResourceByCharCodeOp, "
          "RF4S.exe+0x20D640). arg0 = resource char-code: 'd'(100)=gold (caps at 2,000,000,000; "
          "reaching 10M unlocks achievement 810), 'f'(102)=the player's level (base_stats.level), "
          "'g'(103)=fodder (add/sub go through MonsterFarm_AddFodderToBin, set writes the bin), "
          "'i'(105)=stone, 'j'(106)=compost (both cap 50,000); any other code does nothing -- "
          "the developers' '＊All Skills: Level 50' cheat passes the skill ids 0..39 and is a "
          "no-op in the shipped game. arg1 = the mode, taken from the argument's TOKEN KIND "
          "(the handler reads the kind slot at idx-4, not the value): `null` = add, `zero` = "
          "subtract, `self` = set; listings print them add / sub / set. arg2 = amount. "
          "Subtracting gold plays the coin-clink SFX. The 'pay 1000 gold' (`100, sub, 1000`) / "
          "'here's a reward' (`100, add, N`) op.",
          ["resource code (d=gold,f=level,g=fodder,i=stone,j=compost)",
           "mode (add / sub / set = the null / zero / self leaf)", "amount"]),
})


# ---- scripted item-visual + single reward-popup ops decoded 2026-07-11 (453-459) ----
_M.update({
    453: ("DropStagedItem", "item",
          "Drop the pre-staged item (set up earlier in the scene) onto the ground at the "
          "player's tile. No args — it reads the staged item record. Used when an item should "
          "'appear on the ground' at the player's feet.",
          []),
    454: ("SpawnItemVisual", "item",
          "Spawn a floating item-display visual at a tile (one of 3 scripted slots). arg0 = "
          "item id, arg1/arg2 = X/Y tiles ( -1, -1 = the player's tile ). For showing items "
          "floating in a scene — gift choices, item reveals. Clear them with op 455.",
          ["item id", "x (tiles, -1=player)", "y (tiles, -1=player)"]),
    455: ("DespawnItemVisuals", "item",
          "Despawn all the floating item-display visuals spawned by SpawnItemVisual (op 454). "
          "No args. Cleanup at the end of an item-reveal scene.",
          []),
    459: ("ShowRewardPopupAtPos", "item",
          "Show a single-item reward popup ('You got [item]!') at a specific world TILE, with "
          "the reward jingle, and mark the item as discovered. arg0 = item id, arg1/arg2 = "
          "X/Y tiles. Unlike ShowRewardPopup (op 457), this places the popup at a chosen tile "
          "rather than on the player.",
          ["item id", "x (tiles)", "y (tiles)"]),
})


# ---- calendar advance/pause ops decoded 2026-07-11 (465-469) — time-skip cutscenes ---
_M.update({
    465: ("SetCalendarPauseFlag", "time",
          "Halt or resume in-game time during a scene — sets the scene's calendar-pause "
          "control flag from arg0's low bit (1 = the scene controls time). Use to freeze the "
          "clock for a cutscene, then release it.",
          ["pause (bit 0)"]),
})


# ---- companion / party-sync ops decoded 2026-07-11 (477-490) ------------------------
_M.update({
    487: ("QueryCurrentNpcInParty", "query",
          "Read 1 iff the NPC the player is currently talking to is in the active party (one "
          "of the two companion slots). No args. Branch on 'is this NPC traveling with me'.",
          []),
    488: ("SetCompanionScriptedPresence", "companion",
          "Lock or release BOTH companions' AI for cutscene control. arg0 = 0 puts them in "
          "scripted-presence mode (the scene drives them); non-zero releases them back to "
          "normal AI (and resets their behaviour). The companion counterpart of SetNpcEngaged "
          "(op 223).",
          ["mode (0=lock for scene, else release)"]),
})


# ---- monster-farm / dex / dev-mode ops decoded 2026-07-11 (401-622) -----------------
_M.update({
    609: ("RollRandomPointInRadiusAroundCenter", "misc",
          "Roll a random tile point within a radius around a center: a Q12 polar roll (MMIX RNG "
          "angle + radius factor) writes the resulting tile-space point to the VM output slots "
          "(x at +64, y at +68) for a following read. Used to scatter monster spawns / "
          "placements around a target tile.",
          ["center x", "center y", "radius"]),
    596: ("RollUniformIntegerLessThanN", "misc",
          "Roll a uniform random integer in [0, N) via the MMIX RNG (N = 0 yields 0); the result "
          "is written to the VM output slot (ctx+64) for a following read.",
          ["N (exclusive upper bound)"]),
    597: ("RollShopCategoryItemReturnId", "item",
          "Roll a random item id from a shop category table (Item_RollRandomIdInCategory) and "
          "write it to the VM output slot for a following read.",
          ["shop category"]),
    631: ("RollSeededHashByMode16", "misc",
          "Deterministic NAME-seeded roll (NOT an RNG draw): hashes the bytes of a string chosen "
          "by `mode` (0 = player name, 1 = farm name, 2-5 = the RF1-4 town names "
          "Kardia/Alvarna/Sharance/Norad, 6-15 = a per-farm-monster name) via an MMIX mix, then "
          "returns a value in [0, modulus) at the VM output slot. Same name -> same result across "
          "reloads.",
          ["mode (0=player,1=farm,2-5=RF town,6-15=farm monster)", "modulus"]),
    632: ("RollSeededDailyRandom", "misc",
          "Roll a DAILY-seeded random integer: uses the calendar/date daily RNG, NOT the "
          "save-scummable global PRNG -- so it is reload-safe but date-dependent (same day -> same "
          "result). mode 0 = uniform [0, max); mode 1 = uniform [0, 101) (the arg is mixed in as a "
          "seed offset). Result written to the VM output slot.",
          ["mode (0=[0,max), 1=[0,101))", "max"]),
    691: ("RollProductSeries", "misc",
          "Multiply a series of N factors together (N = 0 yields 1), cap the product at "
          "999,999,999, and write it to the VM output slot. Despite the 'Roll' name this is a "
          "deterministic product, NOT an RNG draw. arg0 = N (factor count), followed by N factor "
          "values.",
          ["N (factor count)", "factors (variadic)"]),
    621: ("SetDifficulty", "flag",
          "Set the game DIFFICULTY (the Special-edition Easy/Normal/Hard/Hell option; the old "
          "'SetDevMode' name was wrong). arg0 = mode: 0 = Easy (g_globalGameStateFlags bit "
          "0x4000), 1 = Normal (clears 0xC000), 2 = Hard AND Hell (bit 0x8000 — the script "
          "distinguishes Hell with a separate packed-flag EVAL, the engine bit is the same). "
          "Modes 0/1 also write packed GameFlag 3005 = 0. Bit 0x8000 gates monster bonus-level "
          "tiers, extra per-level stat gains, and lethal status/environment damage; 0x4000 "
          "skips a faint penalty. Used by the difficulty-change dialog (bank 71 tail @0x12a6).",
          ["mode (0=Easy, 1=Normal, 2=Hard/Hell)"]),
    622: ("QueryDifficulty", "query",
          "Read the current difficulty into the VM output (counterpart of op 621): 0 = Easy, "
          "1 = Normal, 2 = Hard or Hell (indistinguishable at the engine level). No args.",
          []),
})

# ---- hold/take/consume item + crafted-flag ops decoded 2026-07-11 (425-616) ---------
_M.update({
    430: ("ConsumeHeldItem", "item",
          "Consume / use up N of the item the player is currently holding. arg0 = count. For "
          "'the player uses the item' cutscene moments.",
          ["count"]),
})

# ---- can-interact / pending-interaction / action-trigger ops decoded 2026-07-11 (369-634) ----
_M.update({
    634: ("SetActionTriggerByte", "flow",
          "Set one of the scene's 3 action-trigger bytes (ctx state, index 0-2). arg0 = index "
          "(0-2), arg1 = value. Low-level scene flag used to gate scripted actions; read back "
          "with GetActionTriggerByte (op 635).",
          ["index (0-2)", "value"]),
})

# ---- inventory-space / item-attr query ops decoded 2026-07-11 (418-456) -------------
_M.update({
    419: ("QueryFirstFreeSlot", "query",
          "Read the index of the first free slot in the backpack (or equip-extras) into the "
          "VM output, or -1 if none free. No args. Used before placing an item.",
          []),
    420: ("QueryBackpackFreeSlots", "query",
          "Read 1 iff the player's backpack has at least [N] free slots into the VM output — "
          "the 'do you have room for N more items?' check before granting items. arg0 = N.",
          ["min free slots"]),
    438: ("QueryHasItemOfCategory", "query",
          "Read 1 iff the player holds any item of a given CATEGORY (weapon class, food, seed, "
          "etc — the item-metadata category byte) into the VM output. arg0 = category id. For "
          "'do you have any [type]?' dialogue gates.",
          ["category id"]),
})

# ---- kill-count / tame / companion-monster-data ops decoded 2026-07-11 (407-411) ----
_M.update({
    407: ("QueryActiveKillCount", "query",
          "Read the count of monsters still alive in the active kill-aggregate list into the "
          "VM output — how many enemies are still standing. No args. For boss/battle scenes "
          "gating on 'defeat all the monsters' progress.",
          []),
    410: ("TameEventMonster", "effect",
          "Tame a spawned event-actor monster and add it to the player's monster farm (queues "
          "the tame-success event). arg0 = event key. For a cutscene that 'gifts' "
          "the player a tamed / bonded monster.",
          ["event key"]),
})

# ---- splash / player-moved / cancel-path-or-equip ops decoded 2026-07-11 (185-207) --
_M.update({
    185: ("PlayActorSplash", "actor",
          "Play a 'splash into water' animation on an actor — a squish/stretch bobble with "
          "the splash sound and 3 ripple effects. arg0 = actor (char id; 0 = player, 48+ = "
          "event actor). For scenes where a character jumps or falls into water.",
          ["actor (char id, 0=player)"]),
    195: ("WaitCameraAtMark", "query",
          "BARRIER: block the scene until the CAMERA has arrived at the mark anchor set by "
          "SetCameraPosition/SetCameraTarget (ops 186/190) — per-axis |camera − anchor| <= "
          "2048 Q12 = half a tile (Chebyshev). No args. This is what paces every scripted "
          "camera sweep: `SetCameraTarget(x, y, speed); WaitCameraAtMark()` holds until the "
          "pan lands. (The IDB comparison is against g_cameraPosQ12, the CAMERA, not the "
          "player.)",
          []),
})

# ---- actor facing-byte / spin / low-level motion-field ops decoded 2026-07-11 (84-106) ----
_M.update({
})

# ---- reaction-flow + present-item ops decoded 2026-07-11 (2-210) --------------------
# Ops 2/3/4 are ACTION-op flow helpers: when the scene is in the pending-reaction state
# (ctx+112 == 4), they redirect the VM to a target pc (ctx+120 = target, ctx+112 = 2).
# Distinct from the control-op jumps (JMP/BR_*); these run inside quest/dialogue reactions.
_M.update({
    2: ("Wait", "flow",
        "WAIT — pause the scene for a scripted duration. The one argument is a TIME in script "
        "units: 200 units = 1 frame, so 12000 = 1 second, 6000 = 0.5 s, 3000 = 0.25 s (the "
        "corpus's four most common values are exactly these). Any value 1..200 yields exactly "
        "one frame — `Wait(1)` is the idiomatic single-frame yield. This is the single most "
        "common pacing op (5,529 uses). Two traps, both engine-verified: the argument's "
        "expression KIND must be 0 (a computed expression — a plain literal is silently "
        "ignored, which is why the compiler always emits waits as expressions), and there must "
        "be EXACTLY one argument. IDA-verified as the wait primitive (vm[+120] = units, "
        "state -> WAITING; RF4S.exe+0x1FAB50).",
        ["duration (units; 200 = 1 frame, 12000 = 1 s)"]),
    3: ("WaitReset", "flow",
        "Wait variant that also RESETS the quest-reaction state first (op 2's sibling handler; "
        "1 use in the whole opening chain). Same duration units as Wait.",
        ["duration (units; 200 = 1 frame)"]),
    4: ("WaitPlain", "flow",
        "Wait like op 2 but WITHOUT advancing the quest-reaction state: a non-zero duration "
        "sets the wait counter and puts the running VM into the waiting state "
        "(Script_VMOp_WaitPlain, RF4S.exe+0x1FABC0 -- the same body as Wait minus the "
        "reaction call). Not a jump: the arg is a duration, never a code address. "
        "Same units as Wait.",
        ["duration (units; 200 = 1 frame)"]),
    210: ("AttachItemVisual", "item",
          "Make a character visibly HOLD UP / present an item — the 'Vishnal hands you a "
          "sword' / 'Doug presents the trophy' op. arg0 = holder (char id, 0 = player), arg1 "
          "= item id, arg2 = variant/charge, arg3 = level/quality. If the player is already "
          "holding something, the item is dropped at their feet instead. Writes 1 (held) / "
          "0 (dropped) to the VM output. Consumes the pending-interaction record (for a "
          "just-crafted / just-gifted item's attributes).",
          ["holder (char id, 0=player)", "item id", "variant", "level"]),
})

# ---- NPC bubble + stop-anim + player-position ops decoded 2026-07-11 (5-213) --------
_M.update({
    213: ("GetPlayerPosition", "query",
          "Read the player's current tile position into the VM output — X to output slot 0, "
          "Y to slot 1, and a 'valid' flag (1) to slot 2. No args. Reference the player's "
          "location in a scene.",
          []),
})

# ---- shipping / tile-effect / dex / backpack query ops decoded 2026-07-11 (649-700) --
_M.update({
    649: ("QueryShippingBoxGold", "query",
          "Read the total gold value of everything currently in the shipping box into the VM "
          "output (capped at 999,999,999). No args. For shipping-total dialogue.",
          []),
    677: ("SpawnEffectObjectAtPos", "effect",
          "Spawn a special class-2050 tile object — a floating harvest-notification-style "
          "effect actor — at a tile. arg0/arg1 = X/Y tiles. For scripted visual effects.",
          ["x (tiles)", "y (tiles)"]),
    700: ("QueryBackpackHasItem", "query",
          "Read 1 iff the player's backpack holds at least [min qty] of an item at [min "
          "quality] or better. arg0 = item id, arg1 = min quantity, arg2 = min quality. The "
          "'do you have X?' check for quest turn-ins and dialogue gates.",
          ["item id", "min quantity", "min quality"]),
})

# ---- player skill / currency ops decoded 2026-07-11 (675-701) -----------------------
_M.update({
    675: ("ConvertMedalsToGold", "item",
          "Convert all of the player's Rune Medals to gold at 20 gold per medal, clearing the "
          "medal count. Writes the gold gained to the VM output. No args. For a medal-exchange "
          "NPC.",
          []),
    679: ("IncrementPlayerSkillLevel", "item",
          "Increment a player skill's level by 1. arg0 = skill index (0-39; see the skill id "
          "table). A scripted skill bump (e.g. a training-event reward).",
          ["skill index (0-39)"]),
    701: ("SetPlayerSkillXp", "item",
          "Set a player skill's XP directly. arg0 = skill index (0-39), arg1 = XP value. "
          "Scripted skill-XP set.",
          ["skill index (0-39)", "xp value"]),
})

# ---- cutscene video + global-scratch + config-by-idx ops decoded 2026-07-11 (683-686) ----
_M.update({
})

# ---- story / combat / marriage / inventory ops decoded 2026-07-11 (651-696) ---------
_M.update({
    651: ("AdvanceStoryProgress", "flag",
          "Advance the main story-progress flag to a new value — MONOTONIC: it only moves "
          "forward, never regresses, and unlocks the matching story achievement. arg0 = the "
          "new story-progress value (0..511, GF_REG_MAIN_SCENARIO). THE op that marks a story "
          "milestone at the end of a plot cutscene.",
          ["story progress value"]),
    680: ("ApplyAttackToPlayer", "actor",
          "Apply a combat attack entry (from the attack database) to the player — scripted "
          "damage / knockback / status, as if the player were hit by that attack. arg0 = "
          "attack id. For cutscene moments where the player takes a hit (boss intro, ambush).",
          ["attack id"]),
})

# ---- misc query/trigger ops decoded 2026-07-11 (619-648) ----------------------------
_M.update({
    628: ("SetRegisters", "flag",
          "Load the VM REGISTER FILE reg0..reg9 (ctx+64..+100) from up to 10 argument values "
          "— reg[i] = arg[i]. These are the registers expressions read back via the reg "
          "tokens, SWITCH selectors dispatch on, and camera/position ops consume "
          "(GetPlayerPosition writes reg0/reg1; a staged PROMPT_CHOICE writes the pick to "
          "reg0). This op is how a script seeds them explicitly (1,825 uses). Registers are "
          "flat scratch — NOT saved across CALL — so consume them before the next op that "
          "writes reg0.",
          ["reg0 value", "reg1 value", "…up to reg9"]),
})

# ---- tile-object ops decoded 2026-07-11 (587-589) — placed scene collectibles --------
_M.update({
})

# ---- choice-menu visibility + minimap-marker ops decoded 2026-07-11 (595-615) -------
# The scene keeps a 128-bit "choice visible" mask at ctx+244 that gates which options the
# next PROMPT_CHOICE (0xFFF4) menu actually shows — the runtime way to grey out / hide
# dialogue choices the player shouldn't be able to pick.
_M.update({
    595: ("SetMinimapMarker", "screen",
          "Place or clear a quest-target marker on the minimap. arg0 = npc (char id) to mark "
          "— the marker points the player at that NPC — or -1 to clear the marker. Guides the "
          "player to a quest NPC.",
          ["npc (char id, -1=clear)"]),
    610: ("SetChoiceVisibleMask", "dialogue",
          "REBUILD the scene's choice-visibility mask from a list of booleans — zeroes mask "
          "dword 0 (choices 0..31; dwords 1-3 are untouched), then sets bit i when arg i is "
          "non-zero. Each bit gates whether option i appears in the next PROMPT_CHOICE, and "
          "the picked VISIBLE ROW maps back through the set bits to the option's ORIGINAL "
          "index in reg0 (that's what the SWITCH after a staged prompt dispatches on). "
          "Sets reg0 = 1 if any of the 128 mask bits is set, else 0. Only 32 args are "
          "meaningful: arg i >= 32 wraps onto bit i-32 (the shift is mod 32). IDA-verified "
          "2026-08-17 / 2026-09-24 (Script_VMOp_SetSceneChoiceVisibleMaskFromArgs).",
          ["choice 0 visible", "choice 1 visible", "…"]),
    611: ("ClearChoiceVisibleRange", "dialogue",
          "Clear COUNT choice-visibility bits starting at START (hide those choices; dword 0 "
          "only, i.e. options 0..31). arg0 = start bit, arg1 = count — NOT a from/to pair "
          "(IDA-verified 2026-08-17: clears bits [start, start+count)). Sets reg0 = 1 if any "
          "bit anywhere is still set, else 0. CAUTION: a mask cleared to all-zero means "
          "'no mask' -- the next prompt shows EVERY option (there is no way to hide all). "
          "Companion to SetChoiceVisibleMask (op 610).",
          ["start index", "count"]),
    612: ("SetChoiceVisibleBit", "dialogue",
          "Show or hide a SINGLE choice by index in the scene's choice-visibility mask. arg0 = "
          "choice index (0-127), arg1 = visible (1) / hidden (0). Sets reg0 = 1 if any "
          "choice is still visible, else 0 — scripts branch on 'is anything left to offer'. "
          "The next PROMPT_CHOICE presents only flagged options (jumping to target[visible "
          "row]) and puts the picked option's ORIGINAL index in reg0; the prompt then CLEARS "
          "the whole mask. The shipped idiom sets bit i for every option (1 or a flag "
          "expression), points all targets at one label and SWITCH_EQs on reg0. A mask with "
          "bits set only past the menu's last option opens an EMPTY menu that crashes on "
          "confirm. Bit 5 on a 4-option menu is harmless.",
          ["choice index (0-127)", "visible (0/1)"]),
    613: ("CalcChoicePrescroll", "dialogue",
          "Pick the row the next choice menu opens on (see the curated entry further down, "
          "which is the one in effect).",
          ["option index"]),
    615: ("SetNextChoiceDescription", "dialogue",
          "ARM the next DIALOG as a choice ROW DESCRIPTION: instead of displaying, that "
          "DIALOG's line is QUEUED (44-byte record in the global g_dialoguePendingLineQueue, "
          "128 slots) with up to 3 values (args past 3 are ignored; 0 = not stored), gated "
          "on the row's visibility bit when a mask is set. Shape: [SetNextChoiceDescription(v..); "
          "DIALOG line] x N, in row order, any time before the menu (often a separate "
          "scene). While the menu is open, the line queued for the HIGHLIGHTED visible row "
          "is shown in the dialogue box (on open and on every cursor move), and its values "
          "are written to element 0 of var arrays kind 4 / 5 / 6 (arg1 / arg2 / arg3 -- the "
          "SetVar4/5/6 arrays that the ＠ text tokens read) -- so the description can show "
          "per-row numbers. The "
          "menu's own option text still comes from the PROMPT_CHOICE ids; the queue is "
          "emptied when the menu closes. 1,839 uses (1,834 followed by their DIALOG). "
          "IDA-verified 2026-09-24 (Script_VMOp_SetNextChoiceDescription, "
          "deferred path of Dialogue_HandleScriptActionShowLine, "
          "ChoiceDialog_CommitSelectionAndDispatchActions).",
          ["value 1 (-> SetVar4 slot 0)", "value 2 (-> SetVar5 slot 0)",
           "value 3 (-> SetVar6 slot 0)"]),
})

# ---- scene-staging / NPC-list / bubble-flavor ops decoded 2026-07-11 (474-560) ------
_M.update({
    560: ("StageSceneNpcs", "flow",
          "At cutscene start, stage the scene's NPCs + companions and expose the 4 "
          "participating NPC ids into the VM output slots (so the script can reference them). "
          "Marks the villagers as 'in scene'. No args. A scene-setup op.",
          []),
})

# ---- quest-request lifecycle ops decoded 2026-07-11 (507-536) ---------------------
_M.update({
    520: ("PostQuestGoalNumber", "quest",
          "Post a request-box GOAL-NUMBER quest (slot kind 8): an objective with NO target "
          "item where the player must reach a number — a skill level, an upgrade level, a "
          "tamed-monster count, a craft count. arg0 = the goal number shown to the player "
          "(display only: completion is checked by the request scene itself via query ops / "
          "em conditions, never by slot progress); further args = LITERAL reward item ids "
          "written verbatim into reward_items[0..3] (stops at the first 0; no category "
          "roll). Also binds the posted slot to the script task's reward-template pointer "
          "(task+136) so the accept/complete/reward-popup ops that follow read this quest. "
          "All 6 retail uses are Eliza tutorial requests in bank 210, e.g. (20,3000) = "
          "'Raise Skill Levels!' (any skill >= 20), (15,1052 Rush Attack) = 'Upgrade "
          "Weapons!', (5,0) = 'Befriend Monsters!'. IDA-verified 2026-09-01: the literals are "
          "the REWARDS, not alternate objective items.",
          ["goal number (level/count to reach)", "reward item ids (variadic, literal)"]),
    530: ("CommitQuestAcceptance", "quest",
          "Commit the player's acceptance of the offered quest — moves it from 'preview' to "
          "an active daily request on the NPC. The second step of the two-step accept "
          "(preview → commit).",
          []),
})

# ---- remaining companion move/invuln/query ops decoded 2026-07-11 (494-504) ---------
_M.update({
    499: ("MoveCompanionRelNF", "companion",
          "Move a companion (or both, slot=2) by a RELATIVE tile offset WITHOUT changing its "
          "facing — the no-facing variant of MoveCompanionRel (op 498). arg0 = slot (0/1, "
          "2=both), arg1/arg2 = dx/dy tiles, arg3 = speed, arg4 = run flag (0=walk).",
          ["slot (0/1, 2=both)", "dx (tiles)", "dy (tiles)", "speed", "run (0/1)"]),
    504: ("QueryPartyMemberTileY", "query",
          "Read a party member's Y tile coordinate into the VM output. arg0 = companion slot "
          "(0 = companion 1, 1 = companion 2; -1 = the player). Pairs with the char-id query "
          "(op 481).",
          ["slot (0/1 companion, -1=player)"]),
})

# --- NPC schedule queries / pose gate / equip-extras / weapon-skill grant / consume-any ---
# Verified against the live handler table (RF4S.exe+0x4DB790): real opcode numbers, NOT the
# _M_OLDBASE +302 offset space. 338/339 read an NPC's daily itinerary slot; 398 gates the
# alternate-pose menu; 426/427/428 are inventory/skill plumbing used by quest & dev scripts.
_M.update({
    427: ("MaxWeaponSkills", "actor",
          "Set the player's six weapon skills (Sword, Long Sword, Spear, Axe/Hammer, Dual Blade, "
          "Glove) all to level 30 and refresh the weapon-skill rank-unlock bits — a scripted/dev "
          "mastery grant (e.g. a New Game+ starter). Takes no arguments.",
          []),
})

# --- dialogue-box descriptor writers ---------------------------------------------------------
# These write into the shared dialogue state block (g_gameGlobalsSlotTable slots 3/9), which the
# speech-box loaders/state-machine read every frame. IDA handlers renamed accordingly; verified
# by tracing Dialogue_LoadAndShowText / Dialogue_LoadEventLineWithPortrait / DialogueBox_TickStateMachine.
#   entries[9] = active line descriptor: LOWORD=text entry index/kind, BYTE2=speaker side
#                (2 = secondary/right nameplate), BYTE3 = per-frame hold countdown.
#   entries[3] = auto-advance timer: HIDWORD=mode (0 off / 1 auto-by-length / N fixed frames), LODWORD=timer.
_M.update({
    623: ("SetDialogueAutoAdvance", "dialogue",
          "Set how the current dialogue line auto-advances (the timing mode). 0 = no auto-advance "
          "(wait for the player to press confirm); 1 = auto-compute a reading timer from the text "
          "length (~7*(len/3)+30 frames); any other N = dismiss the line after exactly N frames. "
          "Lets a scripted line time out on its own.",
          ["mode (0=off, 1=auto, N=frames)"]),
})

# --- scene-context word reads (scene-local state; exact meaning is per-scene) ------------------
# a1 = the running script/scene context. These read raw context words into the VM output; the
# fields are shared with NPC-position / control-flow ops but carry no fixed global meaning.
_M.update({
    658: ("GetDefeatPosition", "query",
          "Read the scene context's word pair at offsets +112 and +114 into the two VM outputs "
          "(main + second): the tile of the most recently defeated monster, written by game event 1 "
          "(RF4S.exe+0x1F2040) after each monster death.",
          []),
})

# --- scripted weapon / story milestone / scene scratch + shuffle buffer (561-586 range) --------
# Decompiled + verified from the live handler table. 563/564 are a swap pair; 566 advances the
# main scenario; 571/572 are a scene-local scratch store/read; 574/575 are a random-permutation
# generator + reader that scripts use to shuffle NPC/event order.
_M.update({
    563: ("EquipScriptedWeapon", "item",
          "Temporarily arm the player with a specific weapon for a scripted scene (tutorials, "
          "cutscenes). Backs up whatever is in the mainhand slot, then force-equips arg0's item "
          "id there and refreshes the HUD. Pair with RemoveScriptedWeapon (op 564) to restore the "
          "player's real weapon afterwards.",
          ["weapon item id"]),
    564: ("RemoveScriptedWeapon", "item",
          "Undo EquipScriptedWeapon (op 563): restore the mainhand weapon that was backed up when "
          "the scripted weapon was equipped, and refresh the HUD. Takes no arguments.",
          []),
    571: ("SetSceneScratch", "flag",
          "Store a scene-local scratch byte + word for the current scene. arg0 = byte (scene+541), "
          "arg1 = word (scene+544). Free scratch space a scene script can stash small state in; "
          "read the byte back with GetSceneScratchByte (op 572).",
          ["byte value", "word value"]),
    572: ("GetSceneScratchByte", "query",
          "Read the scene-local scratch byte (scene+541) set by SetSceneScratch (op 571) into the "
          "VM output. Takes no arguments.",
          []),
    574: ("ShuffleSceneBuffer", "flow",
          "Fill the scene's shuffle buffer with a random permutation of [0 .. arg0-1] (arg0 capped "
          "at 64), using the save-scummable MMIX RNG (Fisher-Yates). Scripts use this to randomize "
          "order — e.g. pick NPCs/events in a random sequence. Read entries back with "
          "GetShuffleValue (op 575).",
          ["count (1-64)"]),
    575: ("GetShuffleValue", "query",
          "Read entry [arg0] of the scene shuffle buffer built by ShuffleSceneBuffer (op 574) into "
          "the VM output — the arg0-th value of the random permutation.",
          ["index"]),
})

# --- scene-load NPC refresh / calendar & request queries / held-item + fish-record (561-586) ---
# Decompiled + verified. 562 resyncs NPC positions; 567/570 feed reminder dialogue; 580 is a
# multi-output held-item tooltip query; 581/582 track the biggest-fish record.
_M.update({
    562: ("RefreshSceneNpcs", "actor",
          "Snap every NPC to their current scheduled position and unblock the cutscene VM. Call "
          "after a scene load or map change so NPCs appear where their daily schedule says they "
          "should be right now. Takes no arguments.",
          []),
    570: ("GetTodaysRequestNpc", "query",
          "Read the char id of the NPC who has an active daily request/order posted today into the "
          "VM output (0 if none). Lets a script point the player at today's request-giver.",
          []),
    582: ("GetFishRecord", "query",
          "Read the saved 'largest fish caught' size rank into the VM output. Read-only counterpart "
          "to CheckFishRecord (op 581).",
          []),
})

# --- scene-event roster / festival contest ops (561-579) --------------------------------------
# Decompiled + verified. Readers pull scene-local state (bytes/NPCs/event fields) into the VM
# outputs; 569/573 additionally roll & rank the festival contest. All operate on g_currentScene.
_M.update({
    561: ("GetSceneStateBytes", "query",
          "Read the current scene's four state-machine bytes (scene+540..+543) into the first four "
          "VM outputs. Scene-local status bytes a scene script can inspect (byte +541 is the "
          "SetSceneScratch byte).",
          []),
    568: ("GetSceneNpc", "query",
          "Read a scene NPC's char id into the main VM output — arg0 <= 0 selects the scene's "
          "primary NPC, arg0 1-7 selects the scene family/participant NPC list. The second output "
          "gets the scene's 'refresh queued' dirty bit.",
          ["index (<=0 = primary, 1-7 = family)"]),
    576: ("GetSceneEventNpc", "query",
          "Read the NPC/actor id of scene event #arg0 into the VM output (from the 40-byte-stride "
          "scene event-actor registry at scene+172).",
          ["event index"]),
    579: ("GetSceneEventFlags", "query",
          "Read the scene's event-state triplet into three VM outputs: a word at scene+546, a byte "
          "at scene+543, and a word at scene+548. Scene-event bookkeeping fields.",
          []),
    573: ("GetFestivalPlacements", "query",
          "Compute the final festival-contest placements (Festival_ComputeAndRecordPlacements), then "
          "read the top four events' (score, entry) pairs into the first eight VM outputs "
          "(ctx+64..+92). Drives the contest-results cutscene that shows the winners. "
          "(Recategorized flow->query: it writes 8 result registers, so it is a data-returning query.)",
          []),
    578: ("SpawnEventMonsters", "effect",
          "Spawn and initialise the monster-roster participants for the current scene event (e.g. "
          "a monster contest / event where farm monsters take part). Takes no arguments.",
          []),
})

# --- item / inventory query ops (conditional-dialogue gates) -----------------------------------
# Decompiled + verified. Scripts use these to branch dialogue on what the player owns / an item's
# stats. All resolve the item from g_itemDatabase and write results to the VM output(s).
_M.update({
    434: ("GetItemSellPrice", "query",
          "Read an item's base gold value — a single unit at quality 0 — into the VM output. arg0 "
          "= item id. Use it to show or compute a price in a scripted menu.",
          ["item id"]),
    435: ("GetItemBuyPrice", "query",
          "Read an item's base BUY price into the VM output (the metadata buy-price field, the "
          "amount a shop charges before any modifier). arg0 = item id. Contrast GetItemSellPrice "
          "(op 434), which is the SELL value.",
          ["item id"]),
    436: ("IsItemStackable", "query",
          "Read 1 if the item can stack (its metadata stack field is > 1), else 0. arg0 = item id.",
          ["item id"]),
})

# --- tile-object (placed map object) ops (588-594) ---------------------------------------------
# Decompiled + verified. Tile objects are the 64-slot map-entity registry (g_mapEntityRegistry_
# 64slots); the 'active' state is the sign bit of each record's first word. Scripts use these to
# place/pick up/query throwable ground objects (e.g. the request box, festival props).
_M.update({
    589: ("PlayerPickUpObject", "actor",
          "Make the player pick up / carry the scene's target object: snaps the player to the "
          "ground if airborne, places the object one tile away, and starts the carry. The 'come "
          "pick this up' cutscene op. Takes no arguments.",
          []),
    591: ("ClearAllTileObjects", "effect",
          "Clear the active flag of every placed tile object (mass reset of the 61 map-object "
          "records) and zero their state. Takes no arguments.",
          []),
    594: ("CommitGrabbedObject", "actor",
          "If the player is holding a grabbed object that is flagged throwable, commit it into the "
          "bag. A pickup-convenience op. Takes no arguments.",
          []),
})

# --- child-NPC records / weather transition / NPC state byte (448-475) --------------------------
# Decompiled + verified. Child friendship records = g_guestNpcStateTable, 8-byte (4x int16) per
# child, indexed (childId-24) for child NPCs 24..47. Weather flags live on g_weather.
_M.update({
    473: ("RollChildDailyPref", "query",
          "Roll-once-and-remember a child NPC's daily random preference in [0, range). The first "
          "call this session rolls it (MMIX RNG) and stores it in the record; later calls return "
          "the stored value, so it stays stable across save reloads. arg0 = child char id (24-47), "
          "arg1 = range.",
          ["child (char id 24-47)", "range"]),
    448: ("SetWeatherTransition", "time",
          "Set the weather-transition flag — whether the weather is currently mid-change. arg0 = "
          "0 (settled) or non-zero (transitioning). Read it back with GetWeatherTransition (op 449).",
          ["transitioning (0/1)"]),
    449: ("GetWeatherTransition", "time",
          "Read the weather-transition flag into the VM output (1 while the weather is mid-change, "
          "else 0). Takes no arguments.",
          []),
    450: ("GetWeatherStreak", "time",
          "Read the weather streak / cycle-position counter into the VM output (how far through "
          "the current weather cycle; defaults to 30 when no weather task is active). Takes no "
          "arguments.",
          []),
})

# --- party-member query / companion scene-sync ops (481-489) -----------------------------------
# Decompiled + verified. Party members = the task pointers next to g_playerTask (companion 1/2).
# Companion_SyncToScene(slot) pulls a companion into the current scene; the sync mode is set via
# bits of the qword at RF4S.exe+0xE9B300 (bit0 = force full sync, bit1 = secondary flag).
_M.update({
    481: ("GetPartyMemberId", "query",
          "Read a party member's identity field (task +8) by slot into the VM output: arg0 = 0 for "
          "companion 1, 1 for companion 2. Returns 0 if that slot is empty. Used to branch "
          "dialogue on who is currently in the party.",
          ["slot (0=companion 1, 1=companion 2)"]),
})

# --- dungeon 'throw'/delivery queue + RNG-advance ops (524-552) --------------------------------
# Decompiled + verified. The 'general throw' queue is up to 20 item-count entries (24B stride, in
# g_npcDailyRequestArray +350 region) used during dungeon scenes to track item-gather sub-goals.
# Entry state byte: 1 = pending, 2 = active. 524/548 are duplicate opcodes.
_M.update({
    527: ("AdvanceRng", "misc",
          "Advance the shared MMIX RNG by up to 4 rolls WITHOUT using the results — an RNG warm-up "
          "/ desync op. Each variadic arg is a shop-category id whose roll is performed and then "
          "discarded, shifting the random sequence for following rolls.",
          ["category ids (0-4, variadic)"]),
})

# --- monster-roster / kill-tame counts / request-box quest pipeline / npc-achievement (403-558) -
# Decompiled + verified. 403/404 were mislabeled 'Fishing' -> they query the MONSTER ROSTER
# (MonsterRoster_FindActiveSlotByMonsterIdAndInputCtx) for monster ids 1-3; IDA + json renamed.
_M.update({
    408: ("CountLivingEnemies", "query",
          "Count the living monsters on the field EXCLUDING the two boss char ids (141/142) into "
          "the VM output. The 'kill all the trash before the boss appears' gate.",
          []),
    557: ("SetNpcRecognitionFlags", "flag",
          "Write a per-NPC packed game-flag (base id 1451 + npc id) = [arg0] for each npc id in "
          "the variadic list (an npc id of 0 falls back to the married partner). These are the 23 "
          "per-NPC recognition flags (1451-1473); like op290/op698 they go through "
          "GameFlags_WritePacked_OrAchievement -- a graded packed-flag write, NOT one of the ~30 named Steam "
          "achievements.",
          ["value", "npc ids (variadic)"]),
})

# --- actor stat/status setters (triple-target) + shop-selection clears (653-664) ---------------
# Decompiled + verified. The stat setters resolve their target through the standard triple-target
# char-id lookup: 0 = player, 1-47 = NPC record array, >=48 = calendar-event actor. Shop clears
# write a 'no selection' sentinel (-1) into the current shop task's work buffer.
_M.update({
    661: ("SetActorStatFlagRecompute", "actor",
          "Toggle stats.status_flags bit 0x20000 on the target AND recompute its stats; clearing it "
          "also clamps current HP down to the new max HP. arg0 = char id (0=player, <48=NPC, "
          ">=48=event actor), arg1 = 0 to clear / non-zero to set. A scripted stat-affecting status "
          "toggle. NOTE: distinct from op 660 SetActorStatusFlag (a different handler that toggles "
          "the plain status bit 0x20, or 0x10000 for char 239, with NO stat recompute).",
          ["char id (0=player, <48=NPC, >=48=event)", "on (0=clear, else set)"]),
    653: ("ShowLumberCounter", "screen",
          "Make the lumber counter in the screen corner slide in and show the player's current "
          "amount (sets the popup's last shown amount to -1). Takes no arguments.",
          []),
    654: ("ShowStoneCounter", "screen",
          "Make the material stone counter in the screen corner slide in and show the player's "
          "current amount (sets the popup's last shown amount to -1). Takes no arguments.",
          []),
    655: ("ShowPrincePointCounter", "screen",
          "Make the Prince Points counter in the screen corner slide in and show the player's "
          "current amount (sets the popup's last shown amount to -1). Takes no arguments.",
          []),
})

# --- black-screen / dialogue-box state / choice result / farm-monster / species (412-440) -------
# Decompiled + verified. 412 confirmed by its debug string 'rf3sScriptExecExtCmd_BlackScreen'.
# 413/415 write dialogue-box state fields (game-globals slots 8 / flags-slot 4).
_M.update({
    412: ("BlackScreen", "screen",
          "Fade the screen to / from a solid black overlay (spawns the black-overlay object, then "
          "drives g_currentFadeTask via FadeTask_Init). arg0 = DIRECTION: 1 = fade TO black, "
          "0 = fade FROM black (reveal). arg1 = DURATION in frames (e.g. 15/30/60/180 = "
          "0.25/0.5/1/3 s at 60fps; a negative value such as -1 = instant). Handler "
          "rf3sScriptExecExtCmd_BlackScreen. CORRECTION: earlier curation wrongly said 'takes no "
          "arguments' -- the handler reads two (argbuf[-3]=direction, [-5]=duration).",
          ["direction (1 = to black, 0 = from black / reveal)", "duration (frames; <0 = instant)"]),
    414: ("GetChoiceIndexAndItem", "query",
          "Read the last scripted item-selection result into TWO VM outputs: query register 0 = "
          "the choice slot index (0-7, extracted from scene-ctx +116 bits 6-8), register 1 = the "
          "associated item id (11-bit, from ctx+40 field +380). DISTINCT from ConsumeInteractionResult (ops 377/378) -- eResult "
          "(op 377/378 = Script_VMOp_ConsumeChoiceCommitResult, a different handler) -- this one "
          "(Script_VMOp_GetScriptChoiceIndexAndItemId) returns the index+item pair for an "
          "item-pick menu, not the committed PROMPT_CHOICE value.",
          []),
    415: ("SetDialogueFlag4Bit2", "dialogue",
          "Set or clear dialogue-box control bit 0x4 in the dialogue flags word: arg0 == 0 sets the "
          "bit, non-zero clears it. A low-level dialogue-box toggle.",
          ["cond (0=set bit, else clear)"]),
    439: ("ReleaseFarmMonster", "effect",
          "Release the scene's target farm monster: clear its farm-table entry, play the release "
          "effect, remove the actor, and decrement the tamed-monster count. Used when a monster "
          "leaves the farm during a scene. Takes no arguments.",
          []),
})

# --- calendar-event-actor facing / scripted movement / map refresh / item-hand (105-209) --------
# Decompiled + verified. Several are core cutscene primitives (face/move/give-item). 105 is stubbed.
_M.update({
    105: ("QueryCalendarEventStub", "query",
          "Always writes 0 to the VM output — the intended calendar-event lookup is stubbed on the "
          "PC port (the search over the event registry runs but its result is discarded). Treat as "
          "returning 0.",
          []),
    205: ("RefreshMapTiles", "effect",
          "Force a full refresh of the current map's tiles — mark every tile dirty and recompute "
          "its visibility/attribute flags, then flag the player for refresh. Call after a scripted "
          "map or tile-attribute change so it redraws. Takes no arguments.",
          []),
})

# --- npc alt-move / player-effect wait / scene-control bits / hardcoded item check (91-370) ------
# Decompiled + verified. Scene-bit ops write scene-local scratch flags; 198 blocks the VM.
_M.update({
    198: ("WaitForPlayerEffect", "flow",
          "Block the cutscene VM until the current player effect/animation task finishes running. "
          "Takes no arguments.",
          []),
    91: ("SetSceneBit", "flow",
          "Set or clear bit [arg0] of the scene's local bit-field (scene context +404): arg1 non-"
          "zero sets the bit, zero clears it. Scene-local scratch flags for a scene script's own "
          "bookkeeping.",
          ["bit index", "on (0/1)"]),
    201: ("SetCameraFlag", "screen",
          "Set or clear bit 0x40 of the camera control/state flags (the global read by all the "
          "camera code — follow, zoom, cinematic). arg0 non-zero sets, zero clears. A camera-"
          "behaviour toggle used alongside the SetCamera* ops.",
          ["on (0/1)"]),
    370: ("SetSceneStateBit1", "flow",
          "Set scene-state flag bit 1 (scene context +120) — a scene-local marker a scene script "
          "sets for its own logic. Takes no arguments.",
          []),
    310: ("QueryPlayerIsLest", "query",
          "Read 1 if the player is Lest (the MALE protagonist), else 0 (Frey / female). "
          "CORRECTION: not an item check. Reads the actor's voice-marker u16 at task +0x220 "
          "and tests == 1217. That field is the voice marker (voice-family base + per-character "
          "offset), set by Player_SetCharacterVariantLestOrFrey / Player_TransformToCharacterById; "
          "the code documents 1217 = Lest, 1233 = Frey. So this is the standard "
          "player-gender / protagonist branch used to fork dialogue between the male and female "
          "hero. No args.",
          []),
})

# --- sfx housekeeping / monster-farm / festival rewards / calendar set / daily visitor (384-534) -
# Decompiled + verified. 461 pairs with 462 (suppress-jingle → reward roll).
_M.update({
    467: ("SetTime", "time",
          "Set or advance the in-game CLOCK (hour:minute). arg0 = HOUR (cal_inner +8), arg1 = "
          "MINUTE (cal_inner +4), arg2 = 0 to ADD them as a delta or non-zero to SET them "
          "absolutely. Definitive field map from Calendar_NormalizeTimeCarry: cal_inner = [+0 "
          "Q12sec, +4 minute, +8 hour, +12 day, +16 season, +20 year]. The DAY/season/year fields "
          "(+12/+16/+20) are PRESERVED -- these ops do NOT take a date arg; the date advances only "
          "when the hour overflows 24 (-> day) or day overflows 30 (-> season). Normalizes overflow "
          "and refreshes the clock/weather UI. Shipped scenes: arg0 = an hour (12/23), arg1 = 0, "
          "arg2 = 1. Unlike op 466 SkipToTime this supports absolute-set + a full year-tier UI "
          "refresh. (Was mislabeled SetDate/day+month.)",
          ["hour", "minute", "absolute (0=add, else set)"]),
    534: ("GetDailyVisitor", "query",
          "Read the daily traveling-visitor (Sakura merchant) data by mode into the VM outputs: "
          "0/1 = an offer category, 2 = npc id + wanted item + price tier, 3 = alt wanted item + "
          "quantity, 9 = the four discount bits, 10 = the packed want-quest id. arg0 = mode.",
          ["mode (0,1,2,3,9,10)"]),
})

# --- final gap sweep: crop/input/pickup/forecast/economy/my-shop/tile queries (432-690) ----------
# Decompiled + verified. Completes author-facing curation of every emitted opcode.
_M.update({
    441: ("QueryConfirmButton", "query",
          "Read 1 if the CONFIRM / advance button is currently down, else 0. Tests "
          "g_inputState_HighBits bit 41 (0x20000000000) -- the same bit "
          "DialogueBox_TickState4_ShowText OR's with the keyboard/analog inputs to ADVANCE "
          "dialogue, so it's the primary confirm/action button. Used in cutscenes to detect the "
          "player pressing confirm (e.g. to advance or skip). No args.",
          []),
    442: ("QueryStickInputActive", "query",
          "Read 1 if the analog stick / d-pad is currently engaged, else 0. Tests byte 5 of "
          "g_inputState_StickInput (non-zero = stick pushed/tilted); the dialogue input path uses "
          "the same byte to gate its stick-magnitude checks. No args.",
          []),
    633: ("ResetActionEventId", "flow",
          "Clear the last-dispatched action-event id (resets the action-trigger bookkeeping). Takes "
          "no arguments.",
          []),
    635: ("GetActionTriggerByte", "query",
          "Read action-trigger byte [arg0] (index clamped 0-2, from the scene's 3-byte trigger "
          "array) into the VM output. The read counterpart of SetActionTriggerByte (op 634).",
          ["index (0-2)"]),
    659: ("MyShopAction", "misc",
          "Dispatch a 'My Shop' (Sakura tourist-shop) sub-action chosen by arg0: 0 = has any item "
          "for sale, 1 = pick a visitor's desired item, 2 = compute a barter sale price, 3 = read "
          "sale totals, 4 = check the new-record flag, 5 = start the tourist spawner, 6 = stop it "
          "(also runs during map cleanup), 7 = commit a sale (gold + records + tourist count), 8 = "
          "roll a price variation. Later args and outputs are subcase-specific.",
          ["subcase (0-8)", "subcase args (variadic)"]),
    674: ("GetRuneMedals", "query",
          "Read the player's rune-medal count into the VM output. Takes no arguments.",
          []),
    678: ("WallOffTileRect", "effect",
          "Turn every tile of a rectangle of the current map into WALL: each cell becomes "
          "cell & 0xFFFEFE70 | 0x2 (the walking bits cleared, then 0x2 set -- the bit that "
          "blocks the player, monsters and NPCs), clipped to the grid "
          "(Script_VMOp_ResetTileAttribFlagsInRectTo2, re-read 2026-09-27). Lasts until the "
          "map is loaded again. arg0/arg1 = x/y, arg2/arg3 = width/height, all in fine units "
          "(sub-units, >>3 = tiles).",
          ["x (fine)", "y (fine)", "width (fine)", "height (fine)"]),
})

# --- weather setter/getter enriched (real ops 446/447; picker wired via ENUM_ARG_VALUES) --------
_M.update({
    446: ("SetWeather", "effect",
          "Set the current weather. arg0 = weather code (0 Sunny, 1 Rain, 2 Snow, 3 Typhoon, 4 "
          "Blizzard, 5 Cloudy, 6 Rooney, 7 Rain-weak, 8 Snow-weak; 0 also clears scripted weather; "
          "-1 restores the previous weather). arg1 = if non-zero, run the seasonal promoter so the "
          "code is adjusted for the current season (e.g. Rain->Snow in winter). The editor offers "
          "a weather picker for arg0.",
          ["weather code", "apply seasonal conversion (0/1)"]),
    447: ("GetWeather", "query",
          "Read the current weather code into the VM output (see SetWeather / op 446 for the code "
          "values 0-8). Takes no arguments.",
          []),
    336: ("SetFadeColor", "screen",
          "Set the screen fade/tint colour, R/G/B each 0-255, applied to both screen channels "
          "(top + bottom). arg3 = duration in frames: 0 snaps the colour immediately, > 0 animates "
          "the fade task toward it (per-frame delta). Pair with FadeScreen (op 334) to fade in/out "
          "through a chosen colour.",
          ["R (0-255)", "G (0-255)", "B (0-255)", "duration (frames)"]),
})


def _strip_prefix(tech):
    for pre in ("Script_VMOp_", "ScriptAction_", "rf3sScriptExecExtCmd_",
                "ScriptVM_Op_", "ScriptVMOp_", "Script_"):
        if tech.startswith(pre):
            return tech[len(pre):]
    return tech


def _humanize(tech):
    """'SetActorOutfitVariant' -> 'Set actor outfit variant'."""
    s = _strip_prefix(tech)
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Za-z])(?=[0-9])", " ", s)
    return s.replace("_", " ").strip()


# Keyword -> category, most-specific first. Used only for opcodes NOT hand-curated in
# _M, so an author still gets sane grouping in the editor's category filter. Read-only
# opcodes (Query/Get/Is/Has/Count/Are) collapse to "query" -- the established home for
# reads (25:1 in the curated set) -- EXCEPT time/item/quest reads, which curated entries
# keep with their subject, so we mirror that here.
_CAT_KEYWORDS = (
    ("screen",    ("Camera", "Fade", "Minimap", "MapColor", "MapPalette", "MapFade",
                   "Greyscale", "Tint", "Alpha", "Letterbox", "Jitter", "Zoom",
                   "BlackScreen")),
    ("dialogue",  ("Bubble", "Emote", "Mood", "Portrait", "Dialogue", "Speaker",
                   "AreaInfoLine", "Choice", "Justm", "Admire", "Talk", "ScriptedLine")),
    ("quest",     ("Quest", "RequestBox", "QuestRequest", "Request")),
    ("companion", ("Companion", "Party", "BothCompanion")),
    ("audio",     ("Bgm", "BGM", "Sfx", "Voice", "Music", "Sound", "SoLoud", "Volume")),
    ("time",      ("Calendar", "Weather", "Forecast", "Birthday", "DayOfWeek", "Season",
                   "Sleep", "Minute", "Hour", "MonthAndDay")),
    ("item",      ("Item", "Reward", "Loot", "Ship", "Backpack", "Inventory", "Craft",
                   "Drop", "Gold", "Lumber", "Currency", "Medal", "Shop", "Roll",
                   "Turnip", "Flower", "Mineral", "Ring", "Product", "Price", "Prince",
                   "Tourist", "Rank", "TownDevelopment", "Fish", "Skill", "Throw",
                   "Weapon", "Equip")),
    ("effect",    ("Effect", "TileObject", "MapEntity", "TileAttrib", "TileTemplate",
                   "MapTile", "Spawn", "Particle", "Splash", "Video", "MonsterFarm",
                   "Tame", "Dungeon", "SakuraEvent")),
    ("flow",      ("Jump", "Branch", "Reaction", "SceneBit", "SceneControl",
                   "PendingInteraction", "Settle", "ActionTrigger", "ActionEventId",
                   "ScriptState")),
    ("flag",      ("GameFlag", "VarArray", "SceneFlag", "StoryFlag", "SaveConfig",
                   "DevMode", "Cheat", "Flag", "Story", "CtxOutArray", "GlobalDword",
                   "SetEntries")),
    ("actor",     ("Npc", "Actor", "Player", "Monster", "Mount", "Friendship",
                   "Schedule", "Marriage", "Wife", "Child", "Farm", "Entity", "Move")),
)


def _infer_category(tech):
    readonly = bool(re.search(r"(?:^|_)(?:Query|Get|Is|Has|Count|Are)", tech))
    for cat, subs in _CAT_KEYWORDS:
        if any(k in tech for k in subs):
            if readonly and cat not in ("time", "item", "quest"):
                return "query"
            return cat
    return "query" if readonly else "misc"


# ---- build the full table from curated + generated + fallback ---------------------
# op -> {"m": mnemonic, "c": category, "d": description, "a": [arg names]}
META = {}


def _add(op, m, c, d, a):
    META[op] = {"m": m, "c": c, "d": d, "a": list(a)}


# ---- opcode review 2026-09-26 -------------------------------------------------------------
# Every action handler in the dispatch table (RF4S.exe+0x4DB790) re-read against its code;
# these entries replace the earlier text for the ops whose name, description or arguments
# the review corrected. Applied before META is built, so the arg-label driven pickers below
# see the corrected labels.
_M.update({
    0: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    5: ('ShowPortrait', 'dialogue',
        "Show or update a character's E-mote portrait (no name plate, no text-blip change, no emote icon, no voice). arg0 = character id (0 = player), arg1 = expression (<1000 = that character's face index, 1000..1927 = raw expression entry, 255/254 = special reset values), arg2 = side (0 / 1). Returns busy while a screen fade runs.",
        ['character id (0=player)', 'expression (face index; 1000+ = raw entry)', 'side (0/1)']),
    6: ('ShowPortraitWithEmote', 'dialogue',
        "Show or update a character's E-mote portrait by character id, optionally with an emote icon or a voice clip; does not touch the name plate or text blip. arg0 = character id (0 = player), arg1 = side (0/1), arg2 = expression (<1000 = face index, 1000..1927 = raw expression entry), arg3 = trigger: >= 0x1F0 plays that voice/sfx through Sfx_PlayByIdWithNpcVariantRemap, otherwise an emote-icon id (186..192) queued on the portrait (0 = none). Busy while a fade runs.",
        ['character id (0=player)', 'side (0/1)', 'expression (face index; 1000+ = raw entry)', 'emote icon (186-192) or voice sfx id (>=0x1F0)']),
    7: ('ShowPortraitWithEmote', 'dialogue',
        "Show or update a character's E-mote portrait by character id, optionally with an emote icon or a voice clip; does not touch the name plate or text blip. arg0 = character id (0 = player), arg1 = side (0/1), arg2 = expression (<1000 = face index, 1000..1927 = raw expression entry), arg3 = trigger: >= 0x1F0 plays that voice/sfx through Sfx_PlayByIdWithNpcVariantRemap, otherwise an emote-icon id (186..192) queued on the portrait (0 = none). Busy while a fade runs.",
        ['character id (0=player)', 'side (0/1)', 'expression (face index; 1000+ = raw entry)', 'emote icon (186-192) or voice sfx id (>=0x1F0)']),
    8: ('SetSpeakerName', 'dialogue',
        "Set the message-box NAME PLATE (and the matching text blip) for the following DIALOG lines; shows no text and no portrait. arg0 = name id: 0 = the player's own saved name with the player's blip ('???' instead before main-scenario progress 2 or in state 0x401000), 1..26 = that villager's name (22/23 = the child names from the prebuilt child-name buffer, not the archive) (chime class from Dialogue_PickChimeClassForSpeaker, g_lastDialogueEmoteId from the NPC's byte +57), 27..47 = an event participant resolved at run time via g_eventNpcParticipants (27-33 / 41-47 also show its portrait, Dialogue_LoadEventLineWithPortrait), >= 48 = any entry of the task's name archive, 0xFFFF = the '???' placeholder. Latched at host+108 (repeating the same id does nothing); also clears the name-hide bit (entries[4] bit 0) except on the 0xFFFF path.",
        ["name id (0 = player's own name, 1-26 villager, 27-47 event participant, >=48 name-archive entry, 0xFFFF '???')"]),
    9: ('SetSpeakerName', 'dialogue',
        "Set the message-box NAME PLATE (and the matching text blip) for the following DIALOG lines; shows no text and no portrait. arg0 = name id: 0 = the player's own saved name with the player's blip ('???' instead before main-scenario progress 2 or in state 0x401000), 1..26 = that villager's name (22/23 = the child names from the prebuilt child-name buffer, not the archive) (chime class from Dialogue_PickChimeClassForSpeaker, g_lastDialogueEmoteId from the NPC's byte +57), 27..47 = an event participant resolved at run time via g_eventNpcParticipants (27-33 / 41-47 also show its portrait, Dialogue_LoadEventLineWithPortrait), >= 48 = any entry of the task's name archive, 0xFFFF = the '???' placeholder. Latched at host+108 (repeating the same id does nothing); also clears the name-hide bit (entries[4] bit 0) except on the 0xFFFF path.",
        ["name id (0 = player's own name, 1-26 villager, 27-47 event participant, >=48 name-archive entry, 0xFFFF '???')"]),
    11: ('SetSpeakerNameVisible', 'dialogue',
        "Show or hide the speaker name label for the following DIALOG lines: arg0 == 0 sets the name-hide bit (g_gameGlobalsSlotTable entries[4] bit 0), any non-zero value clears it; DialogueBox_SpawnBubbleAndSpeakerNameSprites and Dialogue_LoadAndShowText copy the bit into the name-label sprite's hidden flag. Every Dialogue_LoadAndShowText call clears the bit again (it sets it only for name id 0xFFFF), so a later speaker cue that loads a new name re-shows the label.",
        ['name label (0 = hide, non-zero = show)']),
    12: ('SetSpeakerById', 'dialogue',
        'Speaker cue by CHARACTER ID (the generic form of ops 16-75, without emote/voice triggers): arg0 = speaker char id (portrait + name plate + text blip; name via Dialogue_RemapBubbleLineId24To28, 24..28 -> 309/149/239/24/25), arg1 = face index compacted to a class (0-1 -> 0, 2-4 -> 1, 5-8 -> 2, 9-11 -> 3, 12-15 -> 4, 16-18 -> 1, 19 -> 5, >= 20 passed through raw), arg2 = side (0/1; also the side for Dialogue_LoadAndShowText). Clears host+864; busy while a fade runs.',
        ['speaker (char id, 0=player)', 'face (compacted to 0-5)', 'side (0/1)']),
    13: ('SetSpeakerById', 'dialogue',
        'Speaker cue by CHARACTER ID (the generic form of ops 16-75, without emote/voice triggers): arg0 = speaker char id (portrait + name plate + text blip; name via Dialogue_RemapBubbleLineId24To28, 24..28 -> 309/149/239/24/25), arg1 = face index compacted to a class (0-1 -> 0, 2-4 -> 1, 5-8 -> 2, 9-11 -> 3, 12-15 -> 4, 16-18 -> 1, 19 -> 5, >= 20 passed through raw), arg2 = side (0/1; also the side for Dialogue_LoadAndShowText). Clears host+864; busy while a fade runs.',
        ['speaker (char id, 0=player)', 'face (compacted to 0-5)', 'side (0/1)']),
    14: ('SetSpeakerByIdWithEmote', 'dialogue',
        "Speaker cue by CHARACTER ID (runtime-selectable form of ops 16-75): arg0 = speaker char id (name plate via Dialogue_LoadAndShowText when it differs from host+108, text blip via Dialogue_PickChimeClassForSpeaker, portrait; with save-config flag 0x40, ids >= 30 are first mapped through g_npcEmotePsbTable), arg1 = side (0 left / 1 right; passed both to the portrait descriptor and as Dialogue_LoadAndShowText's side), arg2 = expression (<1000 face index, 1000..1927 raw expression entry), arg3 = emote icon 186-192 (queued on the portrait) or a voice sfx id >= 0x1F0 (played). Busy while a fade runs.",
        ['speaker (char id, 0=player)', 'side (0/1)', 'expression (face index; 1000+ = raw entry)', 'emote icon (186-192) or voice sfx id (>=0x1F0)']),
    15: ('SetSpeakerByIdWithEmote', 'dialogue',
        "Speaker cue by CHARACTER ID (runtime-selectable form of ops 16-75): arg0 = speaker char id (name plate via Dialogue_LoadAndShowText when it differs from host+108, text blip via Dialogue_PickChimeClassForSpeaker, portrait; with save-config flag 0x40, ids >= 30 are first mapped through g_npcEmotePsbTable), arg1 = side (0 left / 1 right; passed both to the portrait descriptor and as Dialogue_LoadAndShowText's side), arg2 = expression (<1000 face index, 1000..1927 raw expression entry), arg3 = emote icon 186-192 (queued on the portrait) or a voice sfx id >= 0x1F0 (played). Busy while a fade runs.",
        ['speaker (char id, 0=player)', 'side (0/1)', 'expression (face index; 1000+ = raw entry)', 'emote icon (186-192) or voice sfx id (>=0x1F0)']),
    76: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    77: ('SlidePortraitToX', 'actor',
        'Slide a speaker PORTRAIT horizontally to an absolute screen x. arg0 = character id of the portrait (must be one of the two on-screen portraits, else no-op), arg1 = target screen x (pixels; written to portrait +94, start = current x; bit 15 of the value clears the direction byte +99), arg2 = slide speed (same Q12 conversion as the move ops, x25). Does not wait; pair with op 81.',
        ['portrait character id', 'target screen x (pixels)', 'slide speed']),
    78: ('SlidePortraitToX', 'actor',
        'Slide a speaker PORTRAIT horizontally to an absolute screen x. arg0 = character id of the portrait (must be one of the two on-screen portraits, else no-op), arg1 = target screen x (pixels; written to portrait +94, start = current x; bit 15 of the value clears the direction byte +99), arg2 = slide speed (same Q12 conversion as the move ops, x25). Does not wait; pair with op 81.',
        ['portrait character id', 'target screen x (pixels)', 'slide speed']),
    79: ('SlidePortraitBy', 'actor',
        "Slide a speaker PORTRAIT horizontally by a relative amount. arg0 = character id of an on-screen portrait (else no-op), arg1 = signed x delta in pixels added to the portrait's target x (+94; sign sets the direction byte +99), arg2 = slide speed (Q12 conversion x25 -> +88). Starts the slide (state 0xC) and returns immediately; op 81 waits for it.",
        ['portrait character id', 'x delta (pixels, signed)', 'slide speed']),
    80: ('SlidePortraitBy', 'actor',
        "Slide a speaker PORTRAIT horizontally by a relative amount. arg0 = character id of an on-screen portrait (else no-op), arg1 = signed x delta in pixels added to the portrait's target x (+94; sign sets the direction byte +99), arg2 = slide speed (Q12 conversion x25 -> +88). Starts the slide (state 0xC) and returns immediately; op 81 waits for it.",
        ['portrait character id', 'x delta (pixels, signed)', 'slide speed']),
    81: ('WaitPortraitSettled', 'query',
        "Block the script while the given speaker portrait is still animating (sliding in/out or moving: portrait state (+42 & 0x7C) != 0x10); continue once it has settled. arg0 = portrait character id; if no on-screen portrait matches, it does not block. Nothing is written to a VM register - the result is the handler's busy flag.",
        ['portrait character id']),
    82: ('WaitPortraitSettled', 'query',
        "Block the script while the given speaker portrait is still animating (sliding in/out or moving: portrait state (+42 & 0x7C) != 0x10); continue once it has settled. arg0 = portrait character id; if no on-screen portrait matches, it does not block. Nothing is written to a VM register - the result is the handler's busy flag.",
        ['portrait character id']),
    83: ('ClosePortraits', 'dialogue',
        'Dismiss speaker PORTRAIT(s) and block until the dismissal animation is done. arg0: 0 = the side-0 portrait (host+88), 1 = the side-1 portrait (host+96), any other value = both. Each is sent EmotePortrait_ShowOrSlideOut(p, 0) (slide off to x -64 or 464) and the slot pointer cleared; the op keeps returning busy while g_emotePortraitActiveByScreen / the portrait slot table still shows one active.',
        ['which (0 = side-0 portrait, 1 = side-1 portrait, other = both)']),
    84: ('SetPortraitField62', 'actor',
        'Portrait tweak: if arg2 != 0 and a portrait with char id arg0 is on screen, write arg1 to field +62 of the SIDE-0 portrait (host+88) - note it always writes the host+88 portrait, not the matched one. +62 is initialised to 100 by EmotePortrait_Init; no reader was found. With arg2 = 0 (every shipped use) the op does nothing.',
        ['portrait character id', 'value (u16; default 100)', 'apply (0 = do nothing)']),
    85: ('SetPortraitTargetY', 'actor',
        'Move a speaker PORTRAIT vertically: sets its target screen y (+56); each frame its y eases 1/4 of the remaining distance toward it. 0 disables the easing (y stays where it is). arg0 = portrait character id (else no-op), arg1 = target y (pixels, signed).',
        ['portrait character id', 'target screen y (pixels; 0 = hold)']),
    86: ('SetPortraitTargetY', 'actor',
        'Move a speaker PORTRAIT vertically: sets its target screen y (+56); each frame its y eases 1/4 of the remaining distance toward it. 0 disables the easing (y stays where it is). arg0 = portrait character id (else no-op), arg1 = target y (pixels, signed).',
        ['portrait character id', 'target screen y (pixels; 0 = hold)']),
    87: ('JoltPortraitY', 'actor',
        'Give a speaker PORTRAIT a vertical jolt: sets its extra y offset (+60), which EmotePortrait_SetPosition adds to the drawn y and EmotePortrait_TickTask halves toward 0 every frame (a hop / drop that springs back). arg0 = portrait character id (else no-op), arg1 = offset in pixels (signed).',
        ['portrait character id', 'y jolt (pixels, signed; decays by half per frame)']),
    88: ('JoltPortraitY', 'actor',
        'Give a speaker PORTRAIT a vertical jolt: sets its extra y offset (+60), which EmotePortrait_SetPosition adds to the drawn y and EmotePortrait_TickTask halves toward 0 every frame (a hop / drop that springs back). arg0 = portrait character id (else no-op), arg1 = offset in pixels (signed).',
        ['portrait character id', 'y jolt (pixels, signed; decays by half per frame)']),
    89: ('SetPortraitTremble', 'actor',
        "Make a speaker PORTRAIT tremble: writes the tremble mask +66 = 127 >> n for n in 1..254 (the portrait's y flips by the +58 amplitude, 1 px by default, whenever (phase & mask) == 0, so n = 6 flips every 2 frames, n = 3 every 16); n = 0 (or 255) writes 0xFF = tremble off. arg0 = portrait character id (else no-op).",
        ['portrait character id', 'tremble level n (0 = off; larger = faster, 6 = every other frame)']),
    90: ('SetPortraitTremble', 'actor',
        "Make a speaker PORTRAIT tremble: writes the tremble mask +66 = 127 >> n for n in 1..254 (the portrait's y flips by the +58 amplitude, 1 px by default, whenever (phase & mask) == 0, so n = 6 flips every 2 frames, n = 3 every 16); n = 0 (or 255) writes 0xFF = tremble off. arg0 = portrait character id (else no-op).",
        ['portrait character id', 'tremble level n (0 = off; larger = faster, 6 = every other frame)']),
    98: ('ShakeDialogueBox', 'dialogue',
        "Shake the message box for N frames: writes the dialogue task's shake counter (+161, u8). DialogueBox_TickStateMachine offsets the box, name and text by the byte_7FF753E5E1D0 dx/dy pattern while the counter is non-zero and decrements it each frame (horizontal only while box style 3 is active). This is the same counter the shout/trembling styles arm with 10. The argument is truncated to a byte; any box-style op resets it to 0.",
        ['frames (u8; value & 0xFF)']),
    100: ('TeleportActor', 'actor',
        'Instantly warp an actor to a tile. arg0 = actor (char id, 0 = player). arg1/arg2 = destination X/Y in tiles. The player is snapped to the ground; an NPC is streamed in if needed. No walk animation — use the Move* ops for a visible walk.',
        ['actor (char id, 0=player)', 'x (tiles)', 'y (tiles)']),
    101: ('PlaceActorAndFace', 'actor',
        'Teleport an actor to a tile AND set its facing. arg0 = actor (0 = player, 1..47 NPC; >= 48 = no-op), arg1/arg2 = x/y tiles (as op 99: marks host+352, streams the NPC in, snaps the player to the ground), arg3 = facing in degrees (x181; player: facing_b + g_playerFacingDirty; NPC: target yaw +158 with ease shift +160 = 0, i.e. instant). There is no face-only mode: with fewer than 3 args the handler returns busy and the statement blocks forever; with exactly 3 the facing is taken from an uninitialised local.',
        ['actor (char id, 0=player)', 'x (tiles)', 'y (tiles)', 'facing (degrees)']),
    102: ('PlaceActorAndFace', 'actor',
        'Teleport an actor to a tile AND set its facing. arg0 = actor (0 = player, 1..47 NPC; >= 48 = no-op), arg1/arg2 = x/y tiles (as op 99: marks host+352, streams the NPC in, snaps the player to the ground), arg3 = facing in degrees (x181; player: facing_b + g_playerFacingDirty; NPC: target yaw +158 with ease shift +160 = 0, i.e. instant). There is no face-only mode: with fewer than 3 args the handler returns busy and the statement blocks forever; with exactly 3 the facing is taken from an uninitialised local.',
        ['actor (char id, 0=player)', 'x (tiles)', 'y (tiles)', 'facing (degrees)']),
    103: ('TurnActorToAngle', 'actor',
        'Turn an actor toward a compass facing. arg0 = actor (0 = player, 1..47 NPC; >= 48 or argc < 3 = no-op), arg1 = facing in degrees (x181 -> u16), arg2 = turn ease shift: each frame the facing moves (remaining >> shift) toward the target, so 0 = instant snap, 2 = a quarter per frame (NPC: actor+158 target / +160 shift, npc+20 |= 0x800 when shift != 0; player: facing_b + field_A0 = shift, g_playerFacingDirty).',
        ['actor (char id, 0=player)', 'facing (degrees)', 'ease shift (0 = snap; 2 = 1/4 per frame)']),
    104: ('TurnActorToAngle', 'actor',
        'Turn an actor toward a compass facing. arg0 = actor (0 = player, 1..47 NPC; >= 48 or argc < 3 = no-op), arg1 = facing in degrees (x181 -> u16), arg2 = turn ease shift: each frame the facing moves (remaining >> shift) toward the target, so 0 = instant snap, 2 = a quarter per frame (NPC: actor+158 target / +160 shift, npc+20 |= 0x800 when shift != 0; player: facing_b + field_A0 = shift, g_playerFacingDirty).',
        ['actor (char id, 0=player)', 'facing (degrees)', 'ease shift (0 = snap; 2 = 1/4 per frame)']),
    106: ('RotateActorInPlace', 'actor',
        "Spin an NPC in place: every frame adds arg1 degrees (x181) to its current and target facing (and to its held entity's facing at actor+240 -> +186), blocking until this has run arg2 times (a single global step counter, reset to 0 on completion). arg0 must be an NPC id 1..47: id 0 dereferences a null actor (crash), >= 48 is a no-op; with fewer than 3 args the op blocks forever.",
        ['npc (char id 1-47; not the player)', 'degrees per frame (signed)', 'frame count']),
    108: ('TurnActorToFaceTarget', 'actor',
        "Rotate one actor to look at another — the workhorse for 'actors face each other before dialogue'. arg0 = turner (0 = player, 1..47 = villager, >=48 = monster). arg1 = look-at target (same encoding). arg2 = mode: 0 = snap instantly, non-zero = ease/lerp toward it.",
        ['turner (char id, 0=player)', 'look-at target (char id)', 'mode (0=snap, else ease)']),
    109: ('TurnActorToFaceTarget', 'actor',
        "Rotate one actor to look at another — the workhorse for 'actors face each other before dialogue'. arg0 = turner (0 = player, 1..47 = villager, >=48 = monster). arg1 = look-at target (same encoding). arg2 = mode: 0 = snap instantly, non-zero = ease/lerp toward it.",
        ['turner (char id, 0=player)', 'look-at target (char id)', 'mode (0=snap, else ease)']),
    110: ('FaceEventActor', 'actor',
        'Turn an actor (0 = player, 1..47 NPC; >= 48 = no-op) to face an EVENT ACTOR looked up by id in g_calendarEventMng (the monster / event-bound actor ids such as 100, 200, 300). arg2 is the same turn ease shift as op 107 (0 = snap, 2 = quarter per frame), not an animation.',
        ['actor (char id, 0=player)', 'event-actor id (g_calendarEventMng record id)', 'ease shift (0 = snap)']),
    111: ('SetActorAuxYaw', 'actor',
        "Set the TARGET of an actor's secondary yaw pair (actor+0xD8; current value at +0xD6), not its body facing: arg1 degrees x181. Actor_IntegrateMotionAndFacing eases +0xD6 toward it with the actor's ease shift (+160), so it is not an instant snap. arg0 = actor (0 = player, 1..47 NPC; >= 48 = no-op); needs 2 args.",
        ['actor (char id, 0=player)', 'secondary yaw target (degrees)']),
    112: ('SetActorAuxYaw', 'actor',
        "Set the TARGET of an actor's secondary yaw pair (actor+0xD8; current value at +0xD6), not its body facing: arg1 degrees x181. Actor_IntegrateMotionAndFacing eases +0xD6 toward it with the actor's ease shift (+160), so it is not an instant snap. arg0 = actor (0 = player, 1..47 NPC; >= 48 = no-op); needs 2 args.",
        ['actor (char id, 0=player)', 'secondary yaw target (degrees)']),
    113: ('WaitActorAuxYaw', 'query',
        "Block while the actor's secondary yaw (actor+0xD6) has not reached the target set by op 111 (+0xD8); continue when equal, or at once for ids >= 48 / missing actors. Nothing is written to a VM register - the result is the handler's busy flag.",
        ['actor (char id, 0=player)']),
    114: ('WaitActorAuxYaw', 'query',
        "Block while the actor's secondary yaw (actor+0xD6) has not reached the target set by op 111 (+0xD8); continue when equal, or at once for ids >= 48 / missing actors. Nothing is written to a VM register - the result is the handler's busy flag.",
        ['actor (char id, 0=player)']),
    116: ('MoveActorToTile_LockAI', 'actor',
        "Walk an actor to an ABSOLUTE tile position, then LOCK its AI (npc+568 |= 0x10) so nothing interrupts the staged pose — used when actors slide into cutscene positions and must hold. Args 1/2 are absolute tiles, not offsets: the move command stores x<<12 / y<<12 RAW with no world-position anchor added, on both the NPC and player/scene paths (ops 115-118 are the absolute family; 123-128 are the relative one). args: actor (0 = player), x, y (tiles), facing degrees (x181 -> u16 rotation), speed, jump flag (non-zero = jump/run, 1.2x speed multiplier).",
        ['actor (char id, 0=player)', 'x (tiles, absolute)', 'y (tiles, absolute)', 'facing (degrees)', 'speed', 'jump (0/1)']),
    117: ('MoveActorToPosFaceTravel', 'actor',
        "Move an actor to an ABSOLUTE tile (x,y). Move-command mode byte = 0, so the actor turns to face its direction of travel (there is simply no final-facing argument); afterwards sets actor.control_flags(+0x238) bit 0x10, the same 'scene-controlled' bit the dispatcher sets on every NPC when a cutscene starts. Speed = (arg*167773>>12) x 1.2 when jump != 0.",
        ['actor (char id <48)', 'x (tiles, absolute)', 'y (tiles, absolute)', 'speed', 'jump (0/1)']),
    118: ('MoveActorToPosFaceTravel', 'actor',
        "Move an actor to an ABSOLUTE tile (x,y). Move-command mode byte = 0, so the actor turns to face its direction of travel (there is simply no final-facing argument); afterwards sets actor.control_flags(+0x238) bit 0x10, the same 'scene-controlled' bit the dispatcher sets on every NPC when a cutscene starts. Speed = (arg*167773>>12) x 1.2 when jump != 0.",
        ['actor (char id <48)', 'x (tiles, absolute)', 'y (tiles, absolute)', 'speed', 'jump (0/1)']),
    119: ('MoveActorToTileKeepFacing', 'actor',
        'Move an NPC to an ABSOLUTE tile while KEEPING its current facing (side-step / back-pedal): move-command mode byte = 2, which Npc_StartMoveTowards turns into control_flags 0x20000 (no auto-face). Afterwards sets control_flags bit 0x10 (scene-controlled), exactly like op 117. jump/run flag != 0 multiplies speed by 1.2 and sets the jump bit 0x800000.',
        ['npc (char id <48)', 'x (tiles, absolute)', 'y (tiles, absolute)', 'speed', 'jump (0/1)']),
    120: ('MoveActorToTileKeepFacing', 'actor',
        'Move an NPC to an ABSOLUTE tile while KEEPING its current facing (side-step / back-pedal): move-command mode byte = 2, which Npc_StartMoveTowards turns into control_flags 0x20000 (no auto-face). Afterwards sets control_flags bit 0x10 (scene-controlled), exactly like op 117. jump/run flag != 0 multiplies speed by 1.2 and sets the jump bit 0x800000.',
        ['npc (char id <48)', 'x (tiles, absolute)', 'y (tiles, absolute)', 'speed', 'jump (0/1)']),
    121: ('MoveNpcToPosKeepAnim', 'actor',
        'Move an NPC to an ABSOLUTE tile WITHOUT resetting its animation: cmd mode byte = 8, which makes Npc_StartMoveTowards skip Npc_FinalizeTeleportAndNotify (the reset-to-idle/walk-anim routine), so whatever clip PlayActorAnim started keeps playing while the actor glides. No jump flag (byte0 = 0); speed = arg*167773>>12 (same scale as a non-jump walk). Sets control_flags 0x10 afterwards.',
        ['npc (char id <48)', 'x (tiles, absolute)', 'y (tiles, absolute)', 'speed']),
    122: ('MoveNpcToPosKeepAnim', 'actor',
        'Move an NPC to an ABSOLUTE tile WITHOUT resetting its animation: cmd mode byte = 8, which makes Npc_StartMoveTowards skip Npc_FinalizeTeleportAndNotify (the reset-to-idle/walk-anim routine), so whatever clip PlayActorAnim started keeps playing while the actor glides. No jump flag (byte0 = 0); speed = arg*167773>>12 (same scale as a non-jump walk). Sets control_flags 0x10 afterwards.',
        ['npc (char id <48)', 'x (tiles, absolute)', 'y (tiles, absolute)', 'speed']),
    124: ('MoveActorByOffset', 'actor',
        'Basic cutscene walk: move an actor by a RELATIVE tile offset and face the given angle (no AI changes). args: actor (0=player), dx, dy (tiles), facing degrees, speed, jump flag.',
        ['actor (char id, 0=player)', 'dx (tiles)', 'dy (tiles)', 'facing (degrees)', 'speed', 'jump (0/1)']),
    125: ('MoveActorByOffsetFaceTravel', 'actor',
        "Move an actor by a RELATIVE tile offset, turning to face the direction of travel (mode 0, no end-facing arg). NPC path first clears control_flags bit 0x4 (the 'hidden' bit op 141 sets) and actor+0xB4 bits 0x10C, then Npc_StartMoveTowards; actor 0 = player via the scene mover (mode 0, or 8 when ctx+72 bit 0 is set). 5 args, no facing.",
        ['actor (char id, 0=player)', 'dx (tiles)', 'dy (tiles)', 'speed', 'jump (0/1)']),
    126: ('MoveActorByOffsetFaceTravel', 'actor',
        "Move an actor by a RELATIVE tile offset, turning to face the direction of travel (mode 0, no end-facing arg). NPC path first clears control_flags bit 0x4 (the 'hidden' bit op 141 sets) and actor+0xB4 bits 0x10C, then Npc_StartMoveTowards; actor 0 = player via the scene mover (mode 0, or 8 when ctx+72 bit 0 is set). 5 args, no facing.",
        ['actor (char id, 0=player)', 'dx (tiles)', 'dy (tiles)', 'speed', 'jump (0/1)']),
    127: ('MoveActorByOffsetKeepFacing', 'actor',
        'Move an actor by a RELATIVE tile offset while KEEPING its current facing (side-step / back-pedal). NPC path mode 2 (-> control_flags 0x20000); player path via the scene mover with mode 4 (-> player control_flags 0x20000) or 12. 5 args, no facing; jump flag x1.2 speed.',
        ['actor (char id, 0=player)', 'dx (tiles)', 'dy (tiles)', 'speed', 'jump (0/1)']),
    128: ('MoveActorByOffsetKeepFacing', 'actor',
        'Move an actor by a RELATIVE tile offset while KEEPING its current facing (side-step / back-pedal). NPC path mode 2 (-> control_flags 0x20000); player path via the scene mover with mode 4 (-> player control_flags 0x20000) or 12. 5 args, no facing; jump flag x1.2 speed.',
        ['actor (char id, 0=player)', 'dx (tiles)', 'dy (tiles)', 'speed', 'jump (0/1)']),
    129: ('QueryActorMoveBusy', 'query',
        'Blocking predicate: returns 1 (op re-runs next frame) while the NPC still has an active move command (npc+20 bit 0x8, set by Npc_StartMoveTowards) or a pending turn (npc+20 bit 0x800 with actor facing +0x9C != target +0x9E); 0 when done or actor absent. Actor 0 delegates to QueryPlayerTurnBusy (player scripted-move lock 0x10000 / pending turn). It does NOT look at animation state. Only arg0 is read.',
        ['actor (char id, 0=player)', 'ignored actor … (not read)']),
    130: ('QueryActorMoveBusy', 'query',
        'Blocking predicate: returns 1 (op re-runs next frame) while the NPC still has an active move command (npc+20 bit 0x8, set by Npc_StartMoveTowards) or a pending turn (npc+20 bit 0x800 with actor facing +0x9C != target +0x9E); 0 when done or actor absent. Actor 0 delegates to QueryPlayerTurnBusy (player scripted-move lock 0x10000 / pending turn). It does NOT look at animation state. Only arg0 is read.',
        ['actor (char id, 0=player)', 'ignored actor … (not read)']),
    132: ('QueryActorBeyondRange', 'query',
        "1 while the actor is FARTHER than [range] tiles from its target marker (the player checks a global target position; an NPC checks its own move target); 0 once within range. arg0 = actor (char id, 0 = player), arg1 = range in tiles. Wait-until-arrived predicate. (Handler is named 'InRange' but returns 1 when far.)",
        ['actor (char id, 0=player)', 'range (tiles)']),
    133: ('PlayActorAnim', 'actor',
        "Play an animation on an actor. arg1 = anim id; id 1 is special: instead of a clip it calls the actor's own behaviour callback (actor+0x48), i.e. hands the actor back to its default idle/AI (for the player it may begin a scripted talk interaction). arg2 != 0 sets scene_node flag 0x4 = LOOP the clip (the engine sets the same bit on idle anims); 0 clears it for NPCs (plays once, op 137 can wait for its end); on the player path 0 leaves the bit unchanged (the player branch only ever sets it). Player: begins a scripted-talk interaction first if not already in one.",
        ['actor (char id, 0=player)', 'anim id (1 = resume default behaviour)', 'loop (0/1; 0 clears the bit for NPCs only)']),
    134: ('PlayActorAnim', 'actor',
        "Play an animation on an actor. arg1 = anim id; id 1 is special: instead of a clip it calls the actor's own behaviour callback (actor+0x48), i.e. hands the actor back to its default idle/AI (for the player it may begin a scripted talk interaction). arg2 != 0 sets scene_node flag 0x4 = LOOP the clip (the engine sets the same bit on idle anims); 0 clears it for NPCs (plays once, op 137 can wait for its end); on the player path 0 leaves the bit unchanged (the player branch only ever sets it). Player: begins a scripted-talk interaction first if not already in one.",
        ['actor (char id, 0=player)', 'anim id (1 = resume default behaviour)', 'loop (0/1; 0 clears the bit for NPCs only)']),
    136: ('QueryActorTilePosition', 'query',
        "Read an actor's current tile position: writes X and Y (tiles) to the VM output slots for a following read. arg0 = actor (char id, 0 = player). Falls back to the NPC's backup position if its actor isn't spawned.",
        ['actor (char id, 0=player)']),
    137: ('QueryActorAnimBusy', 'query',
        "Blocking predicate: returns 1 (re-run next frame) while the NPC exists, has an actor, and its scene node's 'anim finished' flag (node+8 bit 0x8) is still clear, i.e. waits for the current non-looping clip to end. Returns 0 at once if the NPC or its actor is missing.",
        ['npc (char id <48)']),
    138: ('QueryActorAnimBusy', 'query',
        "Blocking predicate: returns 1 (re-run next frame) while the NPC exists, has an actor, and its scene node's 'anim finished' flag (node+8 bit 0x8) is still clear, i.e. waits for the current non-looping clip to end. Returns 0 at once if the NPC or its actor is missing.",
        ['npc (char id <48)']),
    140: ('ApplyEffectToActor', 'effect',
        'Apply an Effect (damage / heal / status / VFX) to an actor via Effect_ApplyByKindAndSpawn — the scripted-effect entry point. arg0 = actor (char id, 0 = player). arg1 = effect kind id (dispatched by g_effectKindSpawnTable to spawn the visual + apply the gameplay effect). Used for scripted magic, sparkles, heals, and status in cutscenes.',
        ['actor (char id, 0=player)', 'effect kind id']),
    141: ('SetActorOpacity', 'actor',
        'Show/hide an actor. arg1 == 0 sets control_flags(+0x238) bit 0x4 (hidden); arg1 != 0 clears that bit and sets the model opacity to arg1 percent (SceneNode_SetAlpha(node, arg1*0.01)).',
        ['actor (char id <48, 0=player)', 'opacity percent (0 = hide)']),
    143: ('MoveSceneActorToTileFaceTravel', 'actor',
        'Move the scene-controlled actor (the player) to an ABSOLUTE tile, facing the direction of travel (mode 0, no end-facing, no keep-facing). arg2 = speed (x40.96, x1.2 when running), arg3 = run flag.',
        ['x (tiles)', 'y (tiles)', 'speed', 'run (0/1)']),
    146: ('EquipItemToPlayer', 'actor',
        "Scripted equip: if the player's current held/equip slot passes Inventory_CanStackOrMerge, writes item (id & 0x7FF | 0x800) into the player's equip slot record (actor_inner+0x2A0+984 -> +72), calls Player_OnEquipChanged, then Player_BeginScriptedTalkAndIdle(1).",
        ['item id']),
    149: ('PlayerScriptedTalkAnim', 'dialogue',
        "Put the player into scripted-talk mode (if not already) and play an anim on the player. arg0 = anim id (-1 -> 187; 1 = return to default behaviour instead of a clip). arg1 != 0 sets the player's scene_node flag 0x4 = loop the clip; arg1 == 0 leaves the bit unchanged (it is never cleared here). Also clears scene ctx+116 bit 0x8000000, which re-arms the wait in op 152.",
        ['anim id (-1 = 187, 1 = back to default)', 'loop (non-zero sets the loop bit; 0 leaves it unchanged)']),
    151: ('TriggerActionOnActor', 'effect',
        'Spawn an Action (g_actionConstructorTable id - the same id space as op 150/165, not an as_atk attack timeline) parented to an actor and placed at its position (payload flag byte +20 bit 0 set). arg0 = action id, arg1 = actor (0 = player, 1..47 NPC).',
        ['action id', 'actor (char id, 0=player)']),
    152: ('QueryPlayerAnimBusy', 'query',
        "Blocking predicate (player twin of op 137): returns 1 (re-run next frame) while scene ctx+116 bit 0x8000000 is clear AND the player's scene_node 'anim finished' bit 0x8 is clear, i.e. waits until the clip started by op 149 / op 133 on the player has ended. No args; writes nothing to registers.",
        []),
    155: ('EventSpawnNpcEx', 'actor',
        "Always appends a new event-actor record like op 154 (char arg0, key arg1, x, y, facing deg). Record WORD5 = 0x8000 | (arg5 & 1) << 14 - only bit 0 of arg5 matters and bit 15 is always set; record +16 = float(arg6) * 0.01. What reads WORD5 bits 14/15 and the +16 float was not traced, so 'follow speed' is unconfirmed.",
        ['char id (model)', 'event key', 'x (tiles)', 'y (tiles)', 'facing (degrees)', 'flag (bit 0 only)', 'scalar % (stored x0.01)']),
    161: ('EventNpcWalkToTileKeepFacing', 'actor',
        "Same as op 160 (walk/run an event actor to an absolute tile) but first sets the actor's control_flags bit 0x20000, which suppresses auto-facing toward the movement direction - the actor side-steps / back-pedals keeping its current facing.",
        ['event key', 'x (tiles)', 'y (tiles)', 'speed', 'run (0/1)']),
    162: ('SetEventActorFacing', 'actor',
        "Set a spawned EVENT actor's target facing. arg0 = event key (not a monster/char id), arg1 = degrees (x181), arg2 = turn easing shift stored at actor+0xA0: each frame facing moves by (remaining >> shift), so 0 = snap, 1 = half the gap per frame, 2 = quarter (smoother). Sets record flag 0x8 (turn pending) for op 164.",
        ['event key', 'facing (degrees)', 'turn ease (0 = snap, higher = slower)']),
    163: ('FaceEventActorTowardTarget', 'actor',
        'Turn a spawned event actor to look at a roster actor. arg0 = event key (the one that turns), arg1 = look-at target (0 = player, 1..47 = NPC; values >= 48 are NOT supported - the handler uses an uninitialised pointer), arg2 = turn easing shift (0 = snap, n = 1/2^n of the remaining angle per frame).',
        ['event key', 'look-at target (0=player, 1-47 NPC)', 'turn ease (0 = snap, higher = slower)']),
    169: ('QueryEventActorAnimBusy', 'query',
        "Blocking predicate: returns 1 (re-run next frame) while the keyed event actor is missing or its scene_node 'anim finished' bit (node+8 bit 0x8) is clear - i.e. waits for the one-shot clip started by op 167 to end.",
        ['event key']),
    170: ('SetEventActorAnimSpeed', 'actor',
        "Set a spawned event actor's ANIMATION playback speed: model node (actor+0x20) +0x180 float = arg1 * 0.01 (100 = normal, 50 = half, 0 = frozen pose). Movement speed is not affected.",
        ['event key', 'anim speed % (100 = normal, 0 = freeze)']),
    172: ('ShowEventActorEmote', 'actor',
        'Show an emote/balloon icon over a spawned event actor. arg1 = icon subtype (0 = clear). Stores it at actor+0x140 and, unless the same icon (>=16) is already shown, spawns Action 143 (ActionConstructor_EmotionIcon) at the actor with subtype arg1 and plays a matching SFX for ids 4/5, 6/8 and 14.',
        ['event key', 'emote icon id (0 = clear)']),
    173: ('SetEventActorInScriptFlag', 'actor',
        "Set bit 0x80 of the event ACTOR's +0x234 flags (not the record). The only reader is monster AI opcode 0x80 (MonsterScript_Op80_IfScriptLocked), which treats the actor as 'in script/cutscene' and takes its scripted branch. arg0 = event key.",
        ['event key']),
    174: ('AddActorHeightOffset', 'actor',
        "Add arg1 << 12 to the actor's height offset (actor+0x50, a position component integrated alongside x/y in Actor_IntegrateMotionAndFacing; NEGATIVE = up). Unless render_state_flags bit 0x4 is set the result is clamped to <= 0, so the actor cannot be pushed below its ground height. Target: 0 = player, 1..47 NPC, > 48 = event key (48 itself fails).",
        ['actor (0=player, 1-47 NPC, >48 event key)', 'height delta (negative = up)']),
    175: ('SetEventActorCollideRadius', 'actor',
        "Set a spawned event actor's collision radius: u16 at actor+0xAC (Actor_t.collide_radius) = arg1.",
        ['event key', 'collision radius']),
    176: ('SetEventActorScale', 'actor',
        "Set a spawned event actor's uniform model scale: scale_x/y/z (actor+0x88/+0x8C/+0x90) = arg1 * 167773 >> 12, i.e. percent -> Q12 (100 = 4096 = 1.0, 50 = half size).",
        ['event key', 'scale % (100 = normal)']),
    178: ('SetEventActorTurnAngle', 'actor',
        "Set the target of an event actor's SECONDARY rotation (u16 at actor+0xD8 = 181*deg); Actor_IntegrateMotionAndFacing eases the current value at +0xD6 toward it using the same +0xA0 shift as facing. This is the angle pair op 113 WaitActorAuxYaw and op 179 test - NOT the movement facing (+0x9C/+0x9E) that ops 162/163/164 use.",
        ['event key', 'angle (degrees)']),
    183: ('SetActorAIScript', 'actor',
        "Replace an actor's monster-AI (AIBN) script. arg1 = AI script id: written to stats->ai_script_id (+0x54), the old script ctx gets flag 0x1000, and MonsterScript_SpawnTaskAndLoadScript starts a new AI task loading archive (id+1). arg1 = -1 instead sets the current script ctx flag 0x40000000 (the flag Npc_FinalizeTeleportAndNotify clears) without loading anything. Target: 0 = player, 1..47 NPC, >= 48 event key.",
        ['actor (0=player, 1-47 NPC, 48+ event key)', 'AI script id (-1 = suspend current)']),
    184: ('SetActorIgnoredByMonsters', 'actor',
        "Set/clear bit 0x10000000 of the actor's status_equip_flags (+0x10). Monster AI skips an actor with this bit when picking or validating a target, and Combat_ComputeDamage branches on it in the element-bonus step. arg1 != 0 sets, 0 clears. Target: 0 = player, 1..47 NPC, >= 48 event key.",
        ['actor (0=player, 1-47 NPC, 48+ event key)', 'set (0/1)']),
    188: ('HoldCameraInPlace', 'screen',
        "Detach the camera from following (player camera flag 4) and make its current position its target, so it stops where it is. arg != 0: target = current camera position exactly (plus map scroll origin). arg == 0: commit the current position through Camera_CommitTargetAndClampToBounds (clamped into the map's camera bounds). Nothing here reads the player's position.",
        ['exact (1 = hold exactly, 0 = clamp into bounds)']),
    191: ('ResetCameraToActor', 'screen',
        'Re-attach the camera and center it on an actor (0 = player, 1..47 NPC). arg1 = 0 -> hard-snap target+position to the actor; -1 -> attach only; any other value is the ease SPEED (x40.96, same /100-tiles-per-frame channel as op 190). Blocks ~4 frames (ctx+26 counter) before continuing.',
        ['actor (0=player, 1-47 NPC)', 'speed (/100 tiles per frame; 0 = snap, -1 = attach only)']),
    192: ('ResetCameraToActor', 'screen',
        'Re-attach the camera and center it on an actor (0 = player, 1..47 NPC). arg1 = 0 -> hard-snap target+position to the actor; -1 -> attach only; any other value is the ease SPEED (x40.96, same /100-tiles-per-frame channel as op 190). Blocks ~4 frames (ctx+26 counter) before continuing.',
        ['actor (0=player, 1-47 NPC)', 'speed (/100 tiles per frame; 0 = snap, -1 = attach only)']),
    193: ('SetCameraTargetToCurrentPosition', 'screen',
        "Make the camera's current position its target (no player involved). arg = 0: target = position exactly (and map scroll origin), then recompute the pan vector. arg != 0: commit the position through the bounds clamp, then (unless arg == -1) recompute the pan vector with speed arg (x40.96, /100 tiles per frame) - i.e. ease back inside the map bounds.",
        ['speed (0 = hold exactly, -1 = clamp only, else /100 tiles per frame)']),
    196: ('QueryCameraBeyondRangeOfTarget', 'query',
        'Blocking predicate: 1 while the CAMERA position is more than arg tiles from its target on X or Y, 0 once within range - a range-parameterised op 195. The player position is not read.',
        ['range (tiles)']),
    200: ('SetCameraTargetActor', 'screen',
        "Pan the camera to an actor chosen by scene-slot (same 0..0x2F slot space as dialogue speakers; slot 0 / empty slot falls back to the player). Anchors on the actor's world position and recomputes the follow vector; locks player movement. arg1 = the same PAN-SPEED channel as SetCameraTarget (op 190): arg1/100 tiles per frame, cap 15 (shipped scenes use ~100-400).",
        ['actor slot', 'pan speed (/100 tiles per frame)']),
    206: ('SetActorHeldItem', 'actor',
        "Set what an actor holds. NPC (arg0 1..47): arg1 = item id -> Npc_ClearActivePathTarget(actor, item|0x8000) which, as the id is negative as int16, calls Actor_EquipStartingItemByNpcParam and puts that item's model in the NPC's hand; arg1 = 1 -> passes 0 (re-apply the NPC's configured equipment when it is in equipped mode, else clear); arg1 = 0 -> destroys the three held-item models (actor inner +248/+256/+264) and zeroes the held ids +180/+182/+184. Player (arg0 = 0): arg1 = item id -> add to bag if absent (applying the pending-interaction record) and equip it as the main weapon; arg1 = 0 -> unequip the weapon to the bag and re-apply the other equipment.",
        ['actor (0=player, 1-47 NPC)', 'item id (0 = remove; NPC: 1 = default equipment)']),
    207: ('SetActorHeldItem', 'actor',
        "Set what an actor holds. NPC (arg0 1..47): arg1 = item id -> Npc_ClearActivePathTarget(actor, item|0x8000) which, as the id is negative as int16, calls Actor_EquipStartingItemByNpcParam and puts that item's model in the NPC's hand; arg1 = 1 -> passes 0 (re-apply the NPC's configured equipment when it is in equipped mode, else clear); arg1 = 0 -> destroys the three held-item models (actor inner +248/+256/+264) and zeroes the held ids +180/+182/+184. Player (arg0 = 0): arg1 = item id -> add to bag if absent (applying the pending-interaction record) and equip it as the main weapon; arg1 = 0 -> unequip the weapon to the bag and re-apply the other equipment.",
        ['actor (0=player, 1-47 NPC)', 'item id (0 = remove; NPC: 1 = default equipment)']),
    208: ('HandOrDropItem', 'actor',
        "**Cutscene 'NPC hands you a gift' primitive.** Spawns an item visual and attaches it to either an NPC's hand or the player. **arg 0 = target**: 0 = give to player (either attach to hand OR drop on ground if player has status 0x4000 / secondary_mod in the 'item-blocked' range 1..0x453 — plays Sfx 0x100226D + fires Action_TriggerActor(0x13)). >0 = NPC slot index (looked up via g_gameGlobalsSlotTable), then `Item_SpawnVisualTask` + `Npc_AttachHeldItem`. **arg 1 = item_id** masked to 11 bits (0..2047). The item metadata is loaded from `g_itemDatabase` (recipe metadata copied via 5-byte stride).",
        ['target npc (0=player)', 'item id']),
    209: ('HandOrDropItem', 'item',
        "**Cutscene 'NPC hands you a gift' primitive.** Spawns an item visual and attaches it to either an NPC's hand or the player. **arg 0 = target**: 0 = give to player (either attach to hand OR drop on ground if player has status 0x4000 / secondary_mod in the 'item-blocked' range 1..0x453 — plays Sfx 0x100226D + fires Action_TriggerActor(0x13)). >0 = NPC slot index (looked up via g_gameGlobalsSlotTable), then `Item_SpawnVisualTask` + `Npc_AttachHeldItem`. **arg 1 = item_id** masked to 11 bits (0..2047). The item metadata is loaded from `g_itemDatabase` (recipe metadata copied via 5-byte stride).",
        ['target npc (0=player)', 'item id']),
    211: ('ShowActorEmote', 'actor',
        'Show an emote/balloon icon over an actor (0 = player, -1 = current interaction NPC, 1..47 NPC). arg1 = icon id (0 = clear). Stored at actor+0x140; unless the same icon (>= 16) is already up, spawns Action 143 (ActionConstructor_EmotionIcon, subtype = icon) at the actor and plays an SFX for icons 4/5, 6/8 and 14. NPCs whose control_flags hidden bit 0x4 is set are skipped. No animation or outfit is touched.',
        ['actor (0=player, -1=current NPC, 1-47 NPC)', 'emote icon id (0 = clear)']),
    212: ('ShowActorEmote', 'actor',
        'Show an emote/balloon icon over an actor (0 = player, -1 = current interaction NPC, 1..47 NPC). arg1 = icon id (0 = clear). Stored at actor+0x140; unless the same icon (>= 16) is already up, spawns Action 143 (ActionConstructor_EmotionIcon, subtype = icon) at the actor and plays an SFX for icons 4/5, 6/8 and 14. NPCs whose control_flags hidden bit 0x4 is set are skipped. No animation or outfit is touched.',
        ['actor (0=player, -1=current NPC, 1-47 NPC)', 'emote icon id (0 = clear)']),
    219: ('QueryNpcFriendshipLevel', 'query',
        "Read an NPC's friendship LEVEL (not raw points) into the VM output slot. arg0 = npc (char id); 0 uses the NPC the player is currently talking to. -1 if the NPC isn't found.",
        ['npc (char id, 0=current)']),
    220: ('QueryAllNpcsFriendship', 'query',
        'reg0 = 1 if every story-available villager 1..23 (mask gated by story progress 0x3C/0x63/0x8B/0xD1, the EMFE_SYELZA_READY condition, plus the current child from GameFlags) has friendship level >= arg1. arg0 must be 0: with a non-zero arg0 the handler (bug) evaluates Npc_GetFriendshipLevel(arg1) >= arg1, i.e. it looks up the NPC whose id equals the target level.',
        ['0 (non-zero is broken)', 'target level']),
    221: ('AdjustCurrentNpcFriendship', 'actor',
        "Adjust the current interaction NPC's friendship. The mode is arg0's token KIND (like op 217's arg1), not its value: null leaf (kind 4) = add XP, zero leaf (kind 5) = subtract XP, self leaf (kind 6) = set points absolutely. arg1 = amount.",
        ['mode (add / sub / set = null / zero / self leaf)', 'xp/value']),
    224: ('SetNpcEngaged', 'actor',
        "Pull an NPC out of (or back into) its daily schedule so it can take part in a scene. arg0 = npc (char id), arg1 = engaged: non-zero pauses the NPC's routine ('engaged'), 0 releases it back to its schedule. Refreshes its schedule state immediately.",
        ['npc (char id)', 'engaged (0=release, 1=engage)']),
    226: ('QueryNpcScheduleId', 'query',
        "reg0 = the NPC's current schedule id (Npc_GetCurrentScheduleId), rounded down to a multiple of 4 when < 0x40. arg0 = 0 instead returns the current ROOM id (g_currentRoomId; -1 while input is suppressed or the main task's flag 2 is set).",
        ['npc (char id, 0 = current room id)']),
    228: ('QueryNpcScheduleIsOneOf', 'query',
        "Read 1 iff an NPC's current schedule id matches ANY id in the list. arg0 = npc (char id; 0 tests the PLAYER's scene/menu-state field, 22 the current child id). args[1..] = the schedule ids - there is NO count argument: the 'count' is the statement's own packed arg-count slot (the handler at RF4S.exe+0x1FD9F0 reads it from the encoding, confirmed 2026-09-01).",
        ['npc (char id, 0=player, 22=current child)', 'schedule id …']),
    229: ('QueryNpcAvailableFlagClear', 'query',
        "reg0 = 1 if bit 0x40 of the NPC record's u16 at +20 is clear. The mechanics are certain; what bit 0x40 means (the 'available' label) is not established, and the handler has no null check on the record.",
        ['npc id']),
    230: ('SetSceneCast', 'flow',
        'Scene-cast setup. For every villager 1..23 NOT named in args 1..n and for ALL eight entries of the event participant list (the args exempt only villagers) (and not in companion/equipped mode, actor+16 bit 0x200): record +48 bits 28/29 = mode, and actor control_flags bits 0x4 (hidden) and 0x20 = mode (with mode != 0 it also clears the emote at +0x140 and sets +0x23C bit 0x20). So mode 1 HIDES everyone except the listed participants and mode 0 un-hides them. Also sets ctx+116 bit 29 = mode, calls Npc_RefreshFromSchedule for those same NPCs when their ctx+352 placement-mask bit is set (listed villagers are never refreshed), and clears that mask.',
        ['mode (1 = hide non-participants, 0 = show all)', 'kept villager id … (1-23; the event-participant list is always processed)']),
    231: ('SetSceneCast', 'flow',
        'Scene-cast setup. For every villager 1..23 NOT named in args 1..n and for ALL eight entries of the event participant list (the args exempt only villagers) (and not in companion/equipped mode, actor+16 bit 0x200): record +48 bits 28/29 = mode, and actor control_flags bits 0x4 (hidden) and 0x20 = mode (with mode != 0 it also clears the emote at +0x140 and sets +0x23C bit 0x20). So mode 1 HIDES everyone except the listed participants and mode 0 un-hides them. Also sets ctx+116 bit 29 = mode, calls Npc_RefreshFromSchedule for those same NPCs when their ctx+352 placement-mask bit is set (listed villagers are never refreshed), and clears that mask.',
        ['mode (1 = hide non-participants, 0 = show all)', 'kept villager id … (1-23; the event-participant list is always processed)']),
    234: ('SkipNpcDailyGreeting', 'actor',
        'Hide an NPC — make it invisible/despawned and set its hidden state bit. arg0 = npc (char id). Removes the NPC from the scene; pair with a schedule refresh or SetNpcVisibleFlag to bring it back.',
        ['npc (char id <48)', '(unused — handler reads only 1 arg; corpus passes 2)']),
    235: ('QueryNpcSeenToggle', 'query',
        "Query (reg0) whether an NPC is eligible for a once-per-toggle interaction with the script's own actor: NPC and the calling actor (host+32) must not be in actor state 13/25, the NPC must pass Npc_IsInCurrentArea, and it must be within 48 distance units of the calling actor. On success it TOGGLES bit 0x100000 of the CALLING actor's npc record+48 and returns 1 if that bit was clear before (0 if it was set). Equivalent to op 236 with range fixed at 48.",
        ['npc (char id)']),
    236: ('QueryNpcInteractEligible', 'query',
        "Same as op 235 but with an explicit range: reg0 = 1 iff the NPC and the calling actor are free (state not 13/25), the NPC exists, the NPC is within arg1 distance of the calling actor (0 = no range check), and bit 0x100000 on the calling actor's record+48 was clear before this call (the bit is toggled every successful call).",
        ['npc (char id)', 'range (distance units, 0 = unlimited)']),
    237: ('QueryNpcPairInteraction', 'query',
        "Advance and read a 2-bit hysteresis state (bits 21-22 of the calling actor's npc record+48) for two NPCs relative to the script's own actor: each NPC is 'close' if it and the calling actor are not in state 13/25 and it is within arg2 distance of the CALLING actor (arg2 = 0 treats both as close). reg0 = the next state of a fixed 0->1->2->3->0 sequence: from 0: both close -> 1, only A -> 2, only B -> 3, neither -> 0; from 1: A close -> 2, else B close -> 3, else 0; from 2: B close -> 3, else 0; from 3: always 0 (arg2 = 0 marks both as close, so the value simply cycles). A non-zero GF_REG_FESTA forces a would-be 2/3 to 0. Both NPCs must pass Npc_IsInCurrentArea (villager game-flag bit 981+id / child table), else reg0 is not written.",
        ['npc A (char id)', 'npc B (char id)', 'range to the calling actor']),
    239: ('QueryQuestNpcsAvailable', 'quest',
        "Read 1 iff a primary NPC and all listed NPCs are available (not busy/sleeping schedule codes 13/25, not already mid-event, not inaccessible) AND each listed NPC is within a max distance of the primary — the quest-event group gate. arg0 = max distance, arg1 = primary npc (char id, <48), arg2+ = the other npc ids (their count is implied by the arg count — there is no explicit count arg). Writes 1/0 to reg0. Like op 240 but also requires the NPCs aren't already mid-event.",
        ['max distance', 'primary npc', 'other npc …']),
    241: ('QueryNpcGroupPresentNearby', 'query',
        "Read 1 into reg0 iff a group of NPCs are all present and available (actor state != 13/25, not busy/inaccessible) and each within arg0 distance of the primary. arg0 = max distance, arg1 = primary npc (char id), remaining args = the other npc char ids -- there is NO count argument: the handler derives the group size from the statement's own arg count. The dominant 2-arg form (distance, npc) degenerates to a single-NPC 'present & available' check (self-distance 0). 5-arg form = primary + 3 others.",
        ['max distance', 'primary npc (char id)', 'other npc …']),
    242: ('ContinueNormalTalk', 'flow',
        "If the script host has an actor (host+32), OR bit 0x200 into host+116 (g_sceneControlFlags). When the scene ends, NpcAi_PerFrameTick (RF4S.exe+0x1F0677) bumps the talk step and runs the NPC's talk handler again (RF4S.exe+0x1F6930), so the next kind of talk plays.",
        []),
    244: ('NpcShowItem', 'actor',
        "Make an NPC hold up the item it is carrying: needs the NPC's model to hold an item (+304 -> +178 in 1..1107). If the NPC's actor state is 20 it instead puts the item away and returns to idle (Npc_ResetActorPostTeleport + Npc_FinalizeTeleportAndNotify); otherwise it starts the show-item action (actor state 19, anim archive base+18, tick NpcAction_TickItemShow).",
        ['npc (char id, 1-47)']),
    246: ('StreamInNpcAtPos', 'actor',
        "Stream an NPC into a given map and place it at a tile with no walk-on: sets the NPC actor's map id (actor+84, via Actor_SetFacingDirection which is misnamed) and record+188 to arg1, runs the schedule spawn/place, writes X/Y (tiles<<12) to actor+88/+92 and record+192/+196, stops its anim if not moving, then (for npc != 0) drops any held item and restores its idle pose.",
        ['npc (char id, <48)', 'map id', 'x (tiles)', 'y (tiles)']),
    249: ('SetNpcVisibleFlag', 'actor',
        "Toggle an NPC's visibility/interaction suppression bit (record +52 bit 0x800). arg0 = npc (char id), arg1 = visible: non-zero clears the suppress bit (NPC shown / interactive), 0 sets it (suppressed).",
        ['npc (char id)', 'visible (0=suppressed)']),
    251: ('SyncActorAnimFrame', 'actor',
        'Force an actor to re-sync its animation frame from its widget after a programmatic state change (fixes a one-frame pose pop). arg0 = actor (char id, 0 = player). The regular-actor twin of EventActorResyncAnimFrame (op 168).',
        ['actor (char id, 0=player)']),
    253: ('SetActorAnimSpeedScale', 'actor',
        "Set an actor's animation speed multiplier. arg0 = actor (char id, 0 = player), arg1 = speed percent (÷100: 100 = normal, 50 = slow-mo, 200 = fast). The regular-actor twin of SetEventActorAnimSpeed (op 170).",
        ['actor (char id, 0=player)', 'speed % (100 = 1.0×)']),
    255: ('QueryActorAilmentState', 'query',
        "Read an actor's status-ailment bits (actor+180, the same word op 256 sets) as two codes. reg0: 1 if bit 0x08 set, else 4 if only bit 0x10 (fatigue) is set, 2 if 0x10 plus others or any other ailment bit, 3 if no ailment and HP <= half max, else 0. reg1: 115 if bit 0x01, 116 if 0x04, 117 if 0x02, 118 if 0x20 (cold), else 0. arg0 = 0: the player; non-zero: the companion whose char id matches the current interaction NPC.",
        ['target (0 = player, else the companion being talked to)']),
    256: ('SetActorStatusConditions', 'actor',
        'Set or clear status-ailment bits on actor+180. arg0: 0 = player, 2 = companion 1, 3 = companion 2, anything else = the companion matching the current interaction NPC. arg1: 0 = clear 0x2F (every ailment except fatigue 0x10), 1 = set 0x2F (poison/seal/paralysis/sleep + cold, not fatigue), 2 = set 0x20 (cold), 3 = clear 0x0F, 4 = clear 0x30 (fatigue + cold).',
        ['target (0 = player, 2/3 = companion slot, else talking companion)', 'op (0 clear 0x2F, 1 set 0x2F, 2 set cold, 3 clear 0x0F, 4 clear fatigue+cold)']),
    257: ('QueryAllNpcsEligibleForComment', 'query',
        "reg0 = 1 iff EVERY listed NPC can deliver an ambient comment: exists, not busy/inaccessible, actor state not 13/25/208, per-villager gate flag (bit 862+id) clear for ids < 24, and extra gates for id 7 (GF_FLG_MARGUERITE_VOICE_OFF) and 15 (GF_FLG_DAG_SUBEV_STOP). An arg of 0 means the player's spouse (GF_REG_WIFE_ID); ids >= 0x30 are skipped. Variadic, no count arg.",
        ['npc id … (0 = spouse)']),
    258: ('QueryAllNpcsEligibleForComment', 'query',
        "reg0 = 1 iff EVERY listed NPC can deliver an ambient comment: exists, not busy/inaccessible, actor state not 13/25/208, per-villager gate flag (bit 862+id) clear for ids < 24, and extra gates for id 7 (GF_FLG_MARGUERITE_VOICE_OFF) and 15 (GF_FLG_DAG_SUBEV_STOP). An arg of 0 means the player's spouse (GF_REG_WIFE_ID); ids >= 0x30 are skipped. Variadic, no count arg.",
        ['npc id … (0 = spouse)']),
    259: ('PickRandomVillagers', 'query',
        "Pick arg0 distinct random villagers (from the 23 roster ids) and write their char ids to reg0..reg(arg0-1) (max 10). Args 1.. are char ids to EXCLUDE (built into a bitmask); the roster also drops NPCs gated by story progress, the spouse's/child state, record+52 bit 0x1000, the per-villager gate flags (862+id) and festival-day rules. If GF_REG_FESTA > 17 nothing is picked (outputs 0).",
        ['count to pick (<=10 written)', 'excluded npc id …']),
    260: ('QueryActorHpWellness', 'query',
        "Read the script host actor's (host+32) HP state into reg0: 2 = HP is 0, 1 = HP <= half max, 0 = otherwise. No args.",
        []),
    261: ('SetNpcParticipationFlag', 'actor',
        'Set bit 0x80000000 in npc record+52 (meaning not established). arg0 = 0: all villagers 1..23. Otherwise every arg is an npc char id (variadic, no count arg) and each gets the bit.',
        ['npc id … (arg0 = 0 = all villagers 1-23)']),
    263: ('ResetNpcToIdle', 'actor',
        "Reset an NPC's scripted action: destroy the item/prop it is holding (actor+264 task, model+178 cleared), restore its idle animation and idle tick (Npc_FinalizeTeleportAndNotify), and clear its movement target (actor+112/+120). Does not move the NPC.",
        ['npc (char id, 1-47)']),
    264: ('ResetNpcToIdle', 'actor',
        "Reset an NPC's scripted action: destroy the item/prop it is holding (actor+264 task, model+178 cleared), restore its idle animation and idle tick (Npc_FinalizeTeleportAndNotify), and clear its movement target (actor+112/+120). Does not move the NPC.",
        ['npc (char id, 1-47)']),
    265: ('QueryPlayerOrCompanionDowned', 'query',
        "reg0: arg0 != 0 -> 1 if the player's task tick is Player_DeathTickCallback (player down); arg0 == 0 -> 1 if either companion has stats hp_curr == 0 and actor state 11 (knocked out).",
        ['mode (non-zero = player, 0 = companions)']),
    266: ('SetOrClearNpcSchedule', 'actor',
        "Pin an NPC to a scripted spot, or release it. Always writes the scripted-placement record: record+220 = {x, y, map id, facing}, record+228 = {2*sched kind | 1 (active), sub kind, state}, +232 = 0. arg5 != 0 then applies it (Npc_ApplyScheduleState(npc, 18)); arg5 == 0 instead resets the NPC's schedule working state (+17 = 18, frees the path buffers at +112/+120, clears flag bits) without clearing the record's active bit.",
        ['npc (char id)', 'map id', 'x (tiles)', 'y (tiles)', 'facing (degrees, stored as deg*181>>8)', 'apply (0 = release)', 'sched kind', 'sub kind', 'state']),
    267: ('SetOrClearNpcSchedule', 'actor',
        "Pin an NPC to a scripted spot, or release it. Always writes the scripted-placement record: record+220 = {x, y, map id, facing}, record+228 = {2*sched kind | 1 (active), sub kind, state}, +232 = 0. arg5 != 0 then applies it (Npc_ApplyScheduleState(npc, 18)); arg5 == 0 instead resets the NPC's schedule working state (+17 = 18, frees the path buffers at +112/+120, clears flag bits) without clearing the record's active bit.",
        ['npc (char id)', 'map id', 'x (tiles)', 'y (tiles)', 'facing (degrees, stored as deg*181>>8)', 'apply (0 = release)', 'sched kind', 'sub kind', 'state']),
    268: ('QueryNpcArrivedAtSchedule', 'query',
        'reg0 = 1 iff every listed NPC has reached its scripted/scheduled spot and is available (Npc_IsAtScheduledSpotAndAvailable: record+228 bit 0 set, not busy, not festival-substituted, waypoint index at the end). Variadic, every arg is an npc id, no count. arg0 = 0 switches mode: scan villagers 1..23 with record+228 bit 0 set and return 1 iff NONE of them is in place.',
        ['npc id … (arg0 = 0 = all-villager mode)']),
    269: ('QueryNpcArrivedAtSchedule', 'query',
        'reg0 = 1 iff every listed NPC has reached its scripted/scheduled spot and is available (Npc_IsAtScheduledSpotAndAvailable: record+228 bit 0 set, not busy, not festival-substituted, waypoint index at the end). Variadic, every arg is an npc id, no count. arg0 = 0 switches mode: scan villagers 1..23 with record+228 bit 0 set and return 1 iff NONE of them is in place.',
        ['npc id … (arg0 = 0 = all-villager mode)']),
    270: ('ReleaseNpcScriptedPlacement', 'actor',
        "Hand an NPC pinned by a script (record+228 bit 0) back to its schedule for today: clears the pin; if the in-conversation bit (record+52 0x1000) was set it ends the conversation and ALWAYS does the full Npc_ResetDailyScheduleAndAi; otherwise arg1 == 0 applies today's state in place (Npc_ApplyScheduleState) while arg1 != 0 does the full schedule+AI reset (skipped when the NPC is flagged record+48 bit 0x10 and its current schedule map is walkable). Does nothing if the NPC is not pinned.",
        ['npc (char id)', 'full reset (0 = apply state only)']),
    271: ('ReleaseNpcScriptedPlacement', 'actor',
        "Hand an NPC pinned by a script (record+228 bit 0) back to its schedule for today: clears the pin; if the in-conversation bit (record+52 0x1000) was set it ends the conversation and ALWAYS does the full Npc_ResetDailyScheduleAndAi; otherwise arg1 == 0 applies today's state in place (Npc_ApplyScheduleState) while arg1 != 0 does the full schedule+AI reset (skipped when the NPC is flagged record+48 bit 0x10 and its current schedule map is walkable). Does nothing if the NPC is not pinned.",
        ['npc (char id)', 'full reset (0 = apply state only)']),
    272: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    274: ('QueryNpcPresent', 'query',
        "Read whether a villager is 'present' — record bit 0x400000 (bit 22 of record+52, present-in-town) — into the VM output. arg0 = villager id, valid only for 1-23 (the handler requires id < 24; other ids yield 0). arg0 = 0 instead returns the COUNT of villagers (1-23) currently present.",
        ['npc (villager id <24; 0 = count all present)']),
    275: ('SetNpcPresenceState', 'actor',
        "Set or clear an NPC's town-presence state. arg1 == -1 clears the NPC's bit (1<<npc) in g_sys_npcPresenceBits, any other value sets it. Independently, record+52 bit 0x400000 (the present flag op 273 reads) is set to (arg1 == 1), so it is CLEARED for every value other than 1. When arg1 == 1 it also sets record+52 bits 0x300 (clearing 0x400), copies record+52 bit 0x80 into byte +16, and writes 0 to packed game-flag 768.",
        ['npc (char id)', 'mode (1 = present, -1 = absent, other = presence-mask bit only, clears the present flag)']),
    276: ('QueryNpcHeldItem', 'query',
        'reg0 = the item id the NPC is currently holding (actor+304 -> +178, valid range 1..1107), else 0.',
        ['npc (char id, 1-47)']),
    277: ('QueryNpcHeldItem', 'query',
        'reg0 = the item id the NPC is currently holding (actor+304 -> +178, valid range 1..1107), else 0.',
        ['npc (char id, 1-47)']),
    279: ('QueryNpcFavoriteItem', 'query',
        "Read one of an NPC's favorite/loved gift item ids (rolled) into the VM output. arg0 = npc (char id). Used to hint or pre-fill a gift in a scene.",
        ['npc (char id)']),
    283: ('QueryDateCompanionId', 'query',
        'reg0 = char id of the party companion (companion slot 1 or 2, char id < 48) whose date state (npc record+52 bits 24-26, the op 280/281 field) is non-zero, else 0. A companion with no date state is not returned.',
        []),
    287: ('SetNpcOutfit', 'actor',
        "Set an NPC's outfit variant (Actor_ApplyNpcOutfitVariant loads model file + variant). arg1: 0 = default (clears record+52 bits 0x60), 1 = variant 1 / pajamas (sets 0x40), 2 or 4 = variant 2 / swimsuit (sets 0x20), 3 = variant 3 applied without record bits (not persistent). Bits 0x20/0x40 in the record make variants 1-2 persist.",
        ['npc (char id)', 'outfit (0 default, 1 pajamas, 2 swimsuit, 3 variant 3 not persisted)']),
    288: ('QueryNpcOutfit', 'query',
        "reg0 = the NPC's current outfit variant (actor+488: 0 default, 1 pajamas, 2 swimsuit, 3 ...), 0 if unresolvable.",
        ['npc (char id)']),
    291: ('SpawnChildEventRecords', 'actor',
        'Add at most ONE child record to the calendar-event/placement registry (g_eventActorMng, cap 32): only when GF_REG_CHILD_NUM != 0 (count clamped to 1). Record = {key 512, type 302 or 303 (by child variant flag 287), arg0, arg1, random word, active bit}.',
        ['value stored at record+4 (u16)', 'value stored at record+6 (u16)']),
    294: ('ResetNpcDailySchedule', 'actor',
        "Put an NPC back on a daily-schedule state. arg0 = npc (char id), arg1 = state. Two distinct paths: arg1 != -1 -> Npc_ResetDailyScheduleAndAi(npc, state) (resets schedule AND AI) and returns WITHOUT touching the scene reservation; arg1 == -1 -> recompute today's state (record +17, or Schedule_GetNpcStateForToday when the computed bit +228&1 is clear), apply via Npc_ApplyScheduleState, and clear this scene's placed-actor/reservation bit (ctx+352 bit npc). Heavier than op 296; use at scene end to hand an NPC back to normal life.",
        ['npc (char id)', 'state (-1 = auto)']),
    297: ('ApplyNpcScheduleState', 'actor',
        "Apply a schedule STATE to an NPC (its position/pose for that state) and clear its scene reservation. arg0 = npc (char id), arg1 = state, or -1 to auto-compute today's. Lighter than op 293 — does not reset the NPC's AI.",
        ['npc (char id)', 'state (-1 = auto)']),
    299: ('ApplyPendingNpcPlan', 'actor',
        "Apply an NPC's PENDING schedule plan for today — re-parses and applies its calendar-computed schedule, clears its scene reservation, and refreshes the story-progress cache. arg0 = npc (char id). Like op 296 but also snapshots story progress.",
        ['npc (char id)']),
    300: ('ResetAllNpcSchedules', 'time',
        "Reset every villager (1..23) and every current event participant to today's schedule state with a full schedule+AI reset (Npc_ResetDailyScheduleAndAi), skipping NPCs mid-event (actor+16 bit 0x200) or already flagged; marks each reset NPC with record+48 bit 0x1000. The calendar is not touched. No args.",
        []),
    303: ('SetNpcActionDelay', 'actor',
        "Make an NPC wait before its next scheduled AI action: writes a jittered countdown into the NPC's schedule-wait timer (record +212). Value = uniform [0.75*arg1, 1.125*arg1) via the shared MMIX RNG; if 3/4*arg1 <= 0 nothing is written. NpcSchedule_Tick decrements it once per tick and performs the next schedule action when it hits 0; starting a move/interaction clears it. Does NOT touch friendship (2026-08 analysis). arg0 = npc (char id), arg1 = base wait (ticks).",
        ['npc (char id)', 'base wait (ticks, jittered 0.75x-1.125x)']),
    304: ('GetYear', 'time',
        'reg0 = the calendar YEAR (cal_inner+20). No args.',
        []),
    307: ('GetHourMinute', 'time',
        'reg0 = current HOUR (cal_inner+8, 0-23), reg1 = current MINUTE (cal_inner+4). No args.',
        []),
    312: ('HealPartyByShift', 'companion',
        'Set party HP to a fraction of max. arg0 >= 0: player HEALS hp_max >> arg0; each companion is first damaged by its full hp_max and then healed hp_max >> arg0, i.e. its HP is SET to hp_max >> arg0 (flags two HUD entries for redraw). arg0 < 0: player HP is SET to hp_max >> -arg0 (full heal, then damage max - max>>n); companions untouched.',
        ['shift (>= 0: player +max>>n, companions = max>>n; < 0: player = max>>-n)']),
    316: ('SetNpcVisible', 'dialogue',
        'Show or hide a scene NPC.',
        ['npc id', 'visible']),
    317: ('SetNpcVisible', 'actor',
        'Show or hide a scene NPC.',
        ['npc id', 'visible']),
    319: ('SetEmote', 'dialogue',
        "Set an NPC's facial-expression / emote byte (record +57), switching its portrait face (happy/sad/angry/etc) -- e.g. mid-dialogue. Ops 319 and 320 share this handler. NOT an emote icon over the actor (that is op 211/212 ShowActorEmote).",
        ['npc id', 'emote id']),
    320: ('SetEmote', 'dialogue',
        "Set an NPC's facial-expression / emote byte (record +57), switching its portrait face (happy/sad/angry/etc) -- e.g. mid-dialogue. Ops 319 and 320 share this handler. NOT an emote icon over the actor (that is op 211/212 ShowActorEmote).",
        ['npc id', 'emote id']),
    322: ('SetMood', 'dialogue',
        "Set an NPC's MOOD byte (record +56) -- a per-NPC temperament/mood state. Distinct from the displayed facial expression / emote byte (record +57, op319 SetEmote); unlike SetEmote this does NOT update g_lastDialogueEmoteId. Same handler as op323.",
        ['npc id', 'mood id']),
    323: ('SetMood', 'dialogue',
        "Set an NPC's MOOD byte (record +56) -- a per-NPC temperament/mood state. Distinct from the displayed facial expression / emote byte (record +57, op319 SetEmote); unlike SetEmote this does NOT update g_lastDialogueEmoteId. Same handler as op323.",
        ['npc id', 'mood id']),
    327: ('EndActorTransformAndSetOutfit', 'actor',
        "arg0 = actor (0 = player, 48-255 ignored). arg1 == 255: if the actor is character-changed (status_equip_flags bit 0x8 set, 0x400 clear) spawn a 'char_change' task back to its own character (Actor_SpawnCharacterChangeTransformTask(actor, 0)). Other arg1: if both bits 0x408 are set, revert the same way first; then arg1 == 3 applies outfit variant 3. Player target also calls Player_BeginScriptedTalkAndIdle(1).",
        ['actor (char id, 0 = player)', 'mode (255 = end transform, 3 = outfit variant 3, other = revert only)']),
    328: ('EndActorTransformAndSetOutfit', 'actor',
        "arg0 = actor (0 = player, 48-255 ignored). arg1 == 255: if the actor is character-changed (status_equip_flags bit 0x8 set, 0x400 clear) spawn a 'char_change' task back to its own character (Actor_SpawnCharacterChangeTransformTask(actor, 0)). Other arg1: if both bits 0x408 are set, revert the same way first; then arg1 == 3 applies outfit variant 3. Player target also calls Player_BeginScriptedTalkAndIdle(1).",
        ['actor (char id, 0 = player)', 'mode (255 = end transform, 3 = outfit variant 3, other = revert only)']),
    330: ('SetActorOutfitDirect', 'actor',
        "Directly set an actor's outfit/costume variant with NO transition animation (an instant swap). arg0 = actor (char id, 0 = player), arg1 = outfit variant id. The lightweight version of EndActorTransformAndSetOutfit (op 328).",
        ['actor (char id, 0=player)', 'outfit variant']),
    331: ('SetActorOutfitDirect', 'actor',
        "Directly set an actor's outfit/costume variant with NO transition animation (an instant swap). arg0 = actor (char id, 0 = player), arg1 = outfit variant id. The lightweight version of EndActorTransformAndSetOutfit (op 328).",
        ['actor (char id, 0=player)', 'outfit variant']),
    332: ('WarpToMap', 'flow',
        'Request a map transition for the script host: host+60/+62/+64/+66 = map id, x, y, arrival event id; sets host+56 bit 0x80. The event id also sets host+57 bit 0 (1000-1099) or bit 1 (100-999). Clears dialogue-lock state like op 243 and, when the event id is non-zero, prunes queued events of types 20/24/28/30. NpcAi_FinalizeEventAndPostTick later consumes it: starts the scene transition to (map, x, y) and, if the event id is non-zero, sets host+56 bit 0x40 and packed flag 1018.',
        ['map id', 'x (tiles)', 'y (tiles)', 'arrival event id (0 = none)']),
    333: ('WarpToMapInSubEvent', 'flow',
        'Same as op 332 (map, x, y, arrival event id) but afterwards forces host+57 to bit 0 only and stores GF_REG_SUBEV_NOW (low 7 bits) into host+58.',
        ['map id', 'x (tiles)', 'y (tiles)', 'arrival event id (0 = none)']),
    338: ('QueryNpcOnPlayerMap', 'query',
        "reg0 = 1 iff the NPC's current map (Npc_GetCurrentScheduleId: actor+84, or record+188 when not spawned) equals the player's current map (player actor+84); reg1 = the NPC's map id, plus the season index for outdoor maps < 0x40. arg0 = 0 means the spouse (GF_REG_WIFE_ID).",
        ['npc (char id, 0 = spouse)']),
    339: ('GetNpcCurrentMap', 'query',
        "reg0 = the NPC's current map id (actor+84, or record+188 when not spawned, 0xFFFFFFFF if unresolvable), plus the season index for outdoor maps < 0x40.",
        ['npc (char id)']),
    351: ('SetVar4', 'flag',
        'Write `value` into global script-variable bank 4 (52 u32 slots) at [index]; index > 51 is ignored. The value is clamped as UNSIGNED to 999,999,999, so any negative value is stored as 999999999. Bank 4 is engine-global (not per-scene), is also written by the choice-commit system and is read by dialogue-text substitution codes; read back with GetVar4.',
        ['index (0-51)', 'value (clamped to 999999999)']),
    353: ('SetVar5', 'flag',
        'Write `value` into global script-variable bank 5 (52 u32 slots) at [index]; index > 51 is ignored and the value is clamped as UNSIGNED to 999,999,999 (negatives become 999999999). Engine-global bank, also written by choice commit and read by dialogue-text substitution codes; read back with GetVar5.',
        ['index (0-51)', 'value (clamped to 999999999)']),
    355: ('SetVar6', 'flag',
        'Write `value` into global script-variable bank 6 (52 u32 slots) at [index]; index > 51 is ignored and the value is clamped as UNSIGNED to 999,999,999 (negatives become 999999999). Engine-global bank, also written by choice commit and read by dialogue-text substitution codes; read back with GetVar6.',
        ['index (0-51)', 'value (clamped to 999999999)']),
    357: ('SetVar7', 'dialogue',
        'Write `value` into global script-variable bank 7 (52 u32 slots) at [index]; index > 51 is ignored and the value is clamped as UNSIGNED to 999,999,999 (negatives become 999999999). Shipped scripts use it to stage numbers (e.g. prices from GetPrinceOrderCost) for dialogue-text substitution; bank 7 is also the slot the choice-commit system writes. Read back with GetVar7.',
        ['index (0-51)', 'value (clamped to 999999999)']),
    359: ('SetVar8', 'flag',
        "Write `value` into global script-variable bank 8 (16 u32 slots) at [index]; index >= 16 is ignored, no value clamp. Special values: -1 stores companion 1's farm-table record index (signed u16 at actor+0x1E6, the index op 411 uses into g_MonsterFarmTable; -1 when the monster has no record) and -2 companion 2's (0 when that companion slot is empty). Read back with GetVar8; also read by dialogue-text substitution codes.",
        ['index (0-15)', "value (-1 = companion 1 farm-table record index, -2 = companion 2's)"]),
    361: ('SetVar9', 'flag',
        'Write `value` into global script-variable bank 9 (16 u32 slots) at [index]; index >= 16 ignored. value -1 is replaced by the calendar date code (day + 100*season) of the festival currently in progress (GameFlag REG_FESTA), when one is set. Bank 9 has no VM reader op; it is consumed by dialogue-text substitution codes and by NpcAi_ResolveVillagerBehavior.',
        ['index (0-15)', "value (-1 = current festival's date code)"]),
    362: ('GetFestivalDate', 'query',
        'Look up festival #arg1 in the calendar table (archive 16340, rf3TxtCalendar_split2_1.bin: 4-byte records {npc, season, day, festival}) by the FESTIVAL byte (record byte 3). reg0 = season (0-3), reg1 = day, and bank-9 var [arg0] = day + 100*season. If not found the outputs are uninitialised stack bytes.',
        ['bank-9 slot (0-15)', 'festival id']),
    363: ('GetNpcBirthday', 'query',
        "Get character #arg1's birthday: arg1 != 0 looks up the calendar table (archive 16340) by the NPC byte (record byte 0); arg1 = 0 reads the player's birthday from GameFlags REG_PLAYER_BIRTH_SEASON/DAY. reg0 = season (0-3), reg1 = day; bank-0 var [arg0] = season + 616 (a text-substitution id for the season name) and bank-3 var [arg0] = day.",
        ['var slot (bank 0 index 0-15, bank 3 index 0-51)', 'npc id (0 = player)']),
    364: ('SetVar10', 'flag',
        'Write `value` into global script-variable bank 10 at [index] (index < 16, no value clamp). Bank 10 has no VM reader op; it is read directly by dialogue-text substitution codes.',
        ['index (0-15)', 'value']),
    365: ('SetVar15', 'flag',
        'Write `value` into global script-variable bank 15 at [index] (index < 16, no clamp). Bank 15 has no VM reader op; it feeds dialogue-text substitution codes (corpus writes ids like 23, 161-165 right before a dialogue line).',
        ['index (0-15)', 'value']),
    366: ('SetVar13And14', 'flag',
        'bank13[arg1] = arg0 (0 is replaced by 0x3B49); then each further arg k (k >= 2) is written to bank14[arg1 + k - 2] (both banks 16 slots, out-of-range writes dropped). The common 3-arg form SetVar13And14(0, idx, v) puts v in bank 14 (read back with GetVar14) and the sentinel in bank 13; the 11/12-arg forms bulk-fill bank 14.',
        ['bank-13 value (0 -> 0x3B49)', 'index', 'bank-14 values…']),
    369: ('TryMountPlayerOnHostActor', 'query',
        "Try to mount the player on the script's host actor (host+32, e.g. a farm monster). reg1 = 0 if the player is mid-action (render_state_flags & 0x1E) else 1; reg0 = 0 when mid-action, 2 when the player already has status 0x4000 (mounted/carrying), otherwise the result of Player_BeginMountTransitionAndInstallTickAndAnchor - which actually starts the mount. Takes no script args (the corpus passes one ignored literal).",
        ['(ignored)']),
    376: ('BeginShopkeeperInteraction', 'flow',
        "Open an NPC's shop/service interaction (action id arg1, stored at host+25) via World_DispatchInteractionEvent, after computing a per-NPC interaction kind and a weekday check: arg0 (NPC) maps to a kind override and a weekday (e.g. 8 Dylas -> kind 23 if FLG_DIRUS_FRIENDLY, 13 -> 25 if packed flag 875, 15 -> 24 if EV_DAG_SILENT, 25 -> kind 21 / sub 28, 22/23/unknown -> 26). If today's (day-1)%6 equals that weekday g_interactionDailyEligible = 1, otherwise 0 plus a deterministic ~1/63 daily roll seeded by arg1 and the calendar. Blocks until the interaction finishes. The third argument is not read.",
        ['npc id', 'action id (75-89 in the corpus)', '(ignored)']),
    377: ('ConsumeInteractionResult', 'query',
        'If host+116 bit 24 (interaction result pending) is set, reg0 = (host+116 >> 22) & 3 and bit 24 is cleared; otherwise reg0 is untouched. The pending bit is set by World_DispatchInteractionEvent for action ids 3, 43 and 44 (which also set host+164 = 1/2/3 and clear bits 22-23) and cleared at the start of every other world interaction.',
        []),
    378: ('ConsumeInteractionResult', 'query',
        'If host+116 bit 24 (interaction result pending) is set, reg0 = (host+116 >> 22) & 3 and bit 24 is cleared; otherwise reg0 is untouched. The pending bit is set by World_DispatchInteractionEvent for action ids 3, 43 and 44 (which also set host+164 = 1/2/3 and clear bits 22-23) and cleared at the start of every other world interaction.',
        []),
    380: ('StopMusic', 'audio',
        'Stop the current BGM immediately (no fade): BGM_SwitchWithCrossfade(-1, arg/100) takes its negative-id branch, which calls Sfx_StopChannelVoice and ignores the fade argument. Also sets the scripted-BGM marker (host+116 bit 0x10000000) so the contextual BGM does not restart until PlayMusic -1.',
        ['(ignored; corpus passes 0-18000)']),
    381: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    382: ('FadeMusicVolume', 'audio',
        'Fade the BGM channel volume. arg0 != -1: remember the current BGM volume in host+264 and ramp the BGM (Sfx_GetVoiceSlotByChannel(-1)) to arg0/100 of the category volume over arg1 ticks. arg0 = -1: ramp back to the remembered volume over arg1 and clear host+264 to -1.0.',
        ['volume percent (-1 = restore)', 'fade duration']),
    383: ('SetMusicLock', 'audio',
        'Set/clear the BGM lock byte (sound-task ctx +9). While set, Scene_ApplyContextualBGM does nothing, so the scripted track keeps playing across map changes and the 06:00/21:00 hour rolls instead of being replaced by the area music.',
        ['lock (0/1)']),
    384: ('ResetMusicResumePositions', 'audio',
        'Zero the five per-class BGM resume positions (sound-task ctx +72..+91), so the next village/dungeon/story/title/jingle track started by BGM_SwitchWithCrossfade plays from the beginning instead of resuming.',
        []),
    388: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    389: ('SetPooledVoiceVolume', 'audio',
        "Set a voice-pool slot's volume to arg0/100 immediately: Sfx_FindOrPreemptVoice picks a slot (a free one if any, else the lowest-priority / shortest-remaining playing voice) and Sfx_ApplyDistanceAttenuation(slot, arg0/100, 0) applies it. The argument IS read.",
        ['volume percent']),
    391: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    395: ('SetPlayerFacingAndPose', 'actor',
        "Snap the player's facing to arg0 degrees (facing = deg * 181) and set the player byte at +0xA0 to arg1 (a pose/stance byte, 0-3 in the corpus); marks g_playerFacingDirty. Ops 395 and 396 share this handler.",
        ['facing (degrees)', 'pose byte']),
    396: ('SetPlayerFacingAndPose', 'actor',
        "Snap the player's facing to arg0 degrees (facing = deg * 181) and set the player byte at +0xA0 to arg1 (a pose/stance byte, 0-3 in the corpus); marks g_playerFacingDirty. Ops 395 and 396 share this handler.",
        ['facing (degrees)', 'pose byte']),
    397: ('SetPartyOutfit', 'actor',
        'Change the outfit of the player and both companions. Outfit ids follow the fashion flags: 0 normal, 1 pajamas, 2 swimsuit, 3 wedding, 4 bath (4 also sets player control bit 0). Player: Actor_ApplyNpcOutfitVariant(player, arg). Companions with char id < 24: 1 persists the pajama bit (NPC state +52 bit 0x40), 2 or 4 persists the swimsuit bit (0x20), 0 clears both, 3 applies the wedding outfit without persisting. Returns the previous outfit ids: reg0 = player, reg1/reg2 = companion 1/2 (0 when absent).',
        ['outfit id (0 normal, 1 pajamas, 2 swimsuit, 3 wedding, 4 bath)']),
    398: ('BuildOutfitChoiceMask', 'query',
        'Build the choice-visibility mask (host+244) for an outfit menu: bit 0 = player is not in the normal outfit, bit i (1-15) = fashion flag 728+i (GF_FLG_FASHION_PAJAMA .. _COLOR07) unlocked and not the outfit currently worn. arg0 != 0 inverts the mask; a non-zero mask gets bit 0x10000; bit 4 (bath) is always cleared. reg0 = mask != 0.',
        ['invert (0/1)']),
    400: ('SetPlayerMale', 'actor',
        "Switch the player between Lest (arg != 0: model NPC_PLAYER_00, control bit 0x8000000, scale 4096) and Frey (arg = 0: NPC_PLAYER_01, scale 3904) via Player_SetCharacterVariantLestOrFrey, refresh the game-globals slot ids, then RESET the player name to the default for that gender (text archive 16369 rf3TxtNpc entry 0 'Lest' / entry 599 'Frey').",
        ['male (1 = Lest, 0 = Frey)']),
    401: ('SendMonsterToFarmArea', 'effect',
        'Send the barn monster this script belongs to (host+32) out to work farm area arg0: 1-3 = that area, -1 (0xFF) = a weighted-random free area, 0 = recall (clears the area bits 0x600 and the seed-planting order 0x40000). Sets record flags bits 9-10 = area plus 0x2000 and spawns its farm-worker task. Does nothing if the monster is already assigned to that area, is flagged 0x100, or the global at RF4S.exe+0xE3CB30 has id 0xFFFF.',
        ['farm area (1-3, -1 = random free, 0 = recall)']),
    402: ('RecallFarmMonster', 'effect',
        "Stop a barn monster's field work. arg0 = -1: the script's own monster (host+32) via MonsterFarm_PickAreaAndSpawn(.., 1, 0), whose area-0 path clears the area bits 0x600 and the seed-planting order 0x40000. Otherwise arg0 is a g_MonsterFarmTable index and only its area bits 0x600 are cleared.",
        ["farm record index (-1 = this script's monster)"]),
    403: ('GetFreeFarmAreas', 'query',
        'For farm areas 1-3 of the farm the player is on (current room mapped to its farm-field id), reg0/reg1/reg2 = 1 if no worker monster is assigned to that area, else 0. No args.',
        []),
    404: ('GetOccupiedFarmAreas', 'query',
        'For farm areas 1-3 of the farm field given by arg0, reg0/reg1/reg2 = 1 if a worker monster is assigned to that area. arg0 is a room/field id: 4-23 used directly, barn rooms 77-126 map to field 4 + 4*((room-77)/10), anything else to 4; a negative value means the current room.',
        ['farm field / room id (-1 = current)']),
    405: ('SetFarmMonsterPlantOrder', 'effect',
        "Set or clear record flag bit 18 (0x40000) of a barn monster: arg0 = g_MonsterFarmTable index, or -1 for the monster this script belongs to (host+32); arg1 = 1 set / 0 clear. Bit 18 is the 'also plant seeds' work order: the farm-worker state machine goes to the seed-planting phase only when it is set. It is a standing order (not daily), cleared when the monster is recalled.",
        ["farm record index (-1 = this script's monster)", 'plant seeds (0/1)']),
    406: ('GetFarmMonsterPlantOrder', 'query',
        "reg0 = bit 18 (the 'also plant seeds' work order) of the g_MonsterFarmTable record whose worker task is this script's host subject (host+32); 0 if the subject is not a barn monster. No args. Counterpart of op 405.",
        []),
    409: ('CountTamedFarmMonsters', 'query',
        'Count the occupied slots of the 200-entry monster table (record flag 0x1000 = slot holds a tamed monster), i.e. how many monsters the player owns; cache it at g_farmMonsterMng+250 and return it in reg0.',
        []),
    411: ('QueryCompanionMonsterData', 'query',
        "Multi-purpose monster query, arg1 = kind. Kinds 0-4 read party slot arg0 (0 = companion 1, 1 = companion 2) stats: 0 = 4 dwords (+60/+68/+72/+76) into reg0-3, 1 and 2 = eight s16 stat blocks (+136.., +152..), 3 = eight dwords (+100..), 4 = monster fields plus reg6 = level and reg7 = affinity of its farm record. 5 = for farm areas 1-3 on this farm, reg0-2 = the working monster's record index (0xFFFF if none). 6 = plant-seeds order bit of record arg0. 7 = barn workload count (ceil(owned/4) + owned monsters with order bits 0x40000/0x20000 + owned monsters working an area). 8 = for this script's monster: reg0 = state (1 working an area, 2 flag 0x100, 3 out in the roster, 0 otherwise), reg1 = affinity, reg2 = 1, reg3 = area. 9 = this script's monster: reg0 = level, reg1 = affinity. 10 = record arg0: reg0 = level, reg1 = affinity.",
        ['companion slot / farm record index', 'query kind (0-10)']),
    413: ('SetDialogueBoxY', 'dialogue',
        "Override the dialogue box's Y position: game-globals slot 8 = arg0; when non-zero DialogueBox_TickStateMachine uses it instead of the default 110 (0x6E) for the box layouts that take a fixed Y. Cleared by Dialogue_OnHudDestroy when the dialogue HUD closes.",
        ['y position (0 = default 110)']),
    416: ('QueryPlayerVariable', 'query',
        "reg0 = a player value selected by an ASCII code: 'd'(100) gold, 'f'(102) player level (base_stats.level + 1), 'g'(103) fodder in the barn bin (g_farmMonsterMng+252), 'h'(104) level of skill arg1, 'i'(105) stone, 'j'(106) compost, 'k'(107) highest level among the 40 skills; any other code 0-39 = that skill's level. Other codes leave reg0 = 0.",
        ['variable code', "skill id (only for 'h')"]),
    418: ('QueryBackpackHasRoom', 'query',
        'reg0 = 1 if the backpack has at least one EMPTY slot within its current capacity (15/30/45/60 from Inventory_GetPageSlotCount), else 0. No args.',
        []),
    421: ('SetNextItemAttributes', 'flow',
        "Stage attributes for the NEXT item a script creates (GivePlayerItem, SpawnItemAtPos, ForcePlayerHoldItem, the NPC hand/attach-item ops; DropItem/DropItemStack do not read it): arg0 overrides the item's level byte (+4), arg1 sets the 3-bit 'crafted' field (bits 1-3 of the flags word +2), and args 2-7 fill the six u16 ingredient/material item-id slots (+6..+17, e.g. a dish's ingredients). The record is consumed and cleared by the first such op.",
        ['level byte', 'crafted bits (0-7)', 'ingredient item ids (up to 6)']),
    422: ('SetNextItemAttributesPacked', 'flow',
        'Alternate staging form (marker 2): byte+4 = arg0, byte+6 = arg1, arg2 and args 3-5 packed as 10-bit fields. No consumer applies a marker-2 record - every item op only applies marker 1 and then clears the record - so in the shipped exe this op has no lasting effect beyond discarding any staged op-421 attributes.',
        ['byte +4', 'byte +6', '10-bit fields…']),
    423: ('GivePlayerItem', 'item',
        "Give the player item arg0 x arg1 at quality/level arg2 (stored as arg2-1 in each quality byte; 9 bytes for stackables, 1 otherwise), applying any attributes staged by op 421. Tries the backpack, then the rune-ability page; reg0 = 1 if it went into one of them. If both are full: when the player is already carrying something (status 0x4000 or a held item) the item is dropped at the player's feet with the drop jingle, otherwise the player holds it up in their hands. Ops 423 and 424 share this handler.",
        ['item id', 'count', 'quality (1-10)']),
    424: ('GivePlayerItem', 'item',
        "Give the player item arg0 x arg1 at quality/level arg2 (stored as arg2-1 in each quality byte; 9 bytes for stackables, 1 otherwise), applying any attributes staged by op 421. Tries the backpack, then the rune-ability page; reg0 = 1 if it went into one of them. If both are full: when the player is already carrying something (status 0x4000 or a held item) the item is dropped at the player's feet with the drop jingle, otherwise the player holds it up in their hands. Ops 423 and 424 share this handler.",
        ['item id', 'count', 'quality (1-10)']),
    425: ('ForcePlayerHoldItem', 'item',
        "Put an item straight into the player's hands (equipment record 0, the carried item) with the SE_HOLD jingle: arg0 = item id, arg1 = count, arg2 = quality (> 10 treated as 1). Staged op-421 attributes are applied. arg0 = 0 instead uses up the currently held stack (up to 15 decrements until empty).",
        ['item id (0 = consume held)', 'count', 'quality']),
    426: ('IsPlayerHoldingItem', 'query',
        "reg0 = 1 if the player's carried-item slot (record 0 of the equipment block, g_itemDatabase->ptr_00 + 24) holds an item. No args.",
        []),
    428: ('TakeItem', 'item',
        "Remove arg1 (5-bit, max 31) of item arg0 from every player container in order: backpack (60), the carried item (decremented up to count times), equipment records 1-10, storage, weapon rack, closet, tool box, shipping box, fridge, bookshelf, rune page. A stack larger than the demand is reduced and the op stops; a stack equal to the demand is cleared and the op stops; a stack SMALLER than the demand is cleared and the scan continues with the full, undiminished demand. arg2 >= 0 restricts removal to copies whose level byte is 0; -1 = any level. The 'delivered' item effect, g_lastRemovedItemIdForScript and Player_ClearCarriedRecordsMatching only run when the scan reaches the end without an early stop.",
        ['item id', 'count (max 31)', 'level filter (-1 = any, >= 0 = level-1 copies only)']),
    429: ('TakeItemFromBackpack', 'item',
        'Same removal loop as op 428 but only over the 60 backpack slots, then the carried item (decremented up to count times if its id matches). arg2 >= 0 only removes level-byte-0 copies (-1 = any). A stack equal to the demand is cleared and the scan stops; only a smaller stack is cleared and followed by further removals with the full demand. Writes no result register.',
        ['item id', 'count (max 31)', 'level filter (-1 = any)']),
    431: ('HasItem', 'query',
        "reg0 = 1 if the backpack (60 slots), the carried item or equipment record 1 holds item arg0 with count >= arg1 and level byte + 1 >= arg2 (0 or -1 = any level). reg2 (not reg1) = bit 0 of the matched slot's flags byte (+2).",
        ['item id', 'min count', 'min quality (<= 0 = any)']),
    432: ('CheckCropPlantable', 'query',
        "Look up seed item arg0's crop row (item metadata data_10 -> rf3CropParam row, 108 bytes) - no tile is inspected. reg0 = 1 if the current season's bit is set in the row's season mask (high nibble of the word at +104), or if arg0 == 39 and it is spring; reg1 = sum of the row's first four bytes (the growth-stage lengths); reg2 = item metadata byte +4 (category); reg3 = item metadata flag (data_10+4 bit 3).",
        ['seed item id']),
    437: ('IsItemInCategoryList', 'query',
        'reg0 = 1 if item arg0 appears in item-category list (arg1 - 0x8100) of rf3PresentCategory.bin (archive 14850, 21 lists of item ids). The list index is computed as u16(arg1 + 0x7F00), so scripts pass 0x8100 + list index (33024 + k).',
        ['item id', 'category list (0x8100 + index)']),
    440: ('GetNpcSpecies', 'query',
        'reg0 = the signed 16-bit field at +292 of rf3NpcParam record arg0 (archive 14812, 308-byte records). The field is 0 for all 48 villager records and 161-726 for monster records, shared by colour variants.',
        ['char id']),
    443: ('SetFlagBit', 'flag',
        'Set (arg1 != 0) or clear (arg1 = 0) GameFlags bit zone2_base + arg0 (zone-2 relative id). Only two args are read; shipped statements pass four, and the ignored third arg is 1 in about 40% of them, the fourth always 0.',
        ['flag id (zone-2 relative)', 'value (0 = clear, else set)', '(ignored)', '(ignored)']),
    451: ('GetDayOfWeek', 'time',
        'reg0 = (day - 1) % 6 where day is the calendar day-of-season field (cal_inner +12, 0 treated as 1); range 0-5.',
        []),
    452: ('SpawnItemAtPos', 'item',
        'Spawn item arg0 in the world at tile (arg3, arg4) via Item_SpawnAtPositionAsDropOrVisual, as a pickup when arg5 != 0 or a visual-only prop when 0. arg1 is the QUALITY (clamped to 1-10, stored as arg1-1) and arg2 the COUNT (packed << 11). Staged op-421 attributes are applied.',
        ['item id', 'quality (1-10)', 'count', 'x tile', 'y tile', 'as pickup (0 = visual, 1 = pickup)']),
    456: ('QueryEquippedItemAttr', 'query',
        "reg0 = item id of the player's equipment record picked by arg0 (0 -> record 1 weapon/tool, 1 -> record 2 shield, 2 -> record 4, 3 -> record 5, 4 -> record 6 boots, 5 -> record 3), reg1 = attribute arg1: 0-8 = the nine 10-bit enchantment ids (Item_GetEnchantmentSlotId), 9 = Item_AggregateUpgradeAttrA, 10 = Item_AggregateUpgradeAttrB, 11 = Item_GetUpgradeBoundItemId, 12 = payload byte +6, 13 = bits 10-19 of dword +8, 14 = bits 0-9 of dword +8; other values leave reg1 unchanged. A selector outside 0-5 dereferences null.",
        ['equip selector (0-5)', 'attribute (0-14)']),
    460: ('AddRewardItem', 'item',
        "Put an item into reward-popup slot arg0 (RewardSlot_AddToInventoryAndQueuePopup): arg1 = item id, arg2 = QUALITY (clamped to 1-10, stored as arg2-1), arg3 = COUNT (clamped to 1-9). Sets the item's discovered bit.",
        ['reward slot', 'item id', 'quality (1-10)', 'count (1-9)']),
    461: ('SuppressRewardJingle', 'audio',
        'Set host+120 bit 0x40, which silences the jingle of every later reward popup from this script host (ops 457, 458, 459, 462); the reward ops only test the bit and never clear it.',
        []),
    462: ('GrantFestivalRewards', 'item',
        "Open a reward popup (jingle 0x10000E9 unless op 461 was used) and fill up to 4 reward slots from (item, count) ARG PAIRS: even args pick the item - 9997 (0x270D) a random shop-available item among ids 111-114, 9998 (0x270E) a Item_RollRandomIdInCategory roll over 13 categories, 9999 (0x270F) Loot_RollGenericFromTable, 10000 (0x2710) Loot_RollQuestSpecificFromTable (with a price-based stack when a request is active), anything else a literal item id - and each following odd arg sets that slot's count. At most 8 args are read.",
        ['item/token 1', 'count 1', 'item/token 2', 'count 2', 'item/token 3', 'count 3', 'item/token 4', 'count 4']),
    464: ('DropItemStack', 'item',
        'Drop item arg0 at the player: arg1 = QUALITY (0 treated as 1, stored as arg1-1), arg2 = COUNT (packed << 11). Plays the drop jingle 0x100226D and action 0x13.',
        ['item id', 'quality', 'count']),
    466: ('SkipToTime', 'time',
        'Advance the clock and run the sleep fast-forward (Calendar_FastForwardForSleep). arg2 != 0: target mode - hours += (arg0 - hour) mod 24 and minutes += arg1 - minute when arg1 > minute. arg2 = 0: relative mode - hours += arg0, minutes += arg1. Quirks of target mode: when arg0 equals the current hour the CURRENT hour count is added, when arg1 equals the current minute the current minute is added, and when arg1 is below the current minute (current - arg1) minutes are added.',
        ['hour (target, or delta when arg2 = 0)', 'minute (target, or delta when arg2 = 0)', 'target mode (1) / delta mode (0)']),
    468: ('FastForwardCalendar', 'time',
        "Advance the calendar's year / season / day and run the sleep fast-forward (Calendar_FastForwardForSleep) plus a schedule refresh. Takes 4 args, not 5: arg0 = year, arg1 = season, arg2 = day, arg3 = mode. mode != 0 adds arg0/1/2 to year/season/day as deltas; mode 0 adds |arg0 - current year| and |arg2 - current day| (so reaches the target only when it is ahead; an equal value doubles the field) and adds arg1 to the season. It never touches hour; it also adds the current seconds and minute to themselves (doubles them) before normalising.",
        ['year (delta or target)', 'season (delta)', 'day (delta or target)', 'mode (0 = move toward target, non-zero = add deltas)']),
    469: ('SetOrAddCalendarDate', 'time',
        'Set or add the calendar year / season / day in one call, then run the sleep fast-forward and refresh the clock/weather HUD. arg3 = mode: non-zero sets the three fields directly, 0 adds them (if the added day lands on 0 it becomes day 30 of the previous season). Hour/minute are kept.',
        ['year', 'season (0-3)', 'day (1-30)', 'absolute (0 = add, non-zero = set)']),
    470: ('GetGuestNpcVariant', 'query',
        "Return byte +1 of the per-NPC record for char ids 24-47 (g_guestNpcStateTable, 8 bytes per id) in reg0. That byte is not friendship: Town_BuildDailyGuestNpcRoster writes 4/5/6 for ids 24/25/26 and a random appearance/variant value for guest ids 27-47, and Dialogue_ProcessLineDirective passes it to Dialogue_LoadEventLineWithPortrait as the guest's variant. Out-of-range id reads through a null pointer (no guard).",
        ['npc (char id 24-47)']),
    471: ('GetChildFriendPoints', 'query',
        'Return the raw friendship word (+4) of the record for char id 24-47 in reg0 (0 if out of range). The value is level*4 + a 2-bit progress count: Npc_GetFriendshipLevel returns word>>2 (cap 10000) and Npc_GetFriendshipLevelBase returns word&3 for these ids.',
        ['npc (char id 24-47)']),
    472: ('SetGuestNpcSubVariant', 'actor',
        "Write byte +2 of the per-NPC record for char id 24-47 (ignored if value >= 65). That byte is the guest's second dialogue/portrait variant: Town_BuildDailyGuestNpcRoster rolls it in [0,65) each day and Dialogue_ProcessLineDirective passes it to Dialogue_LoadEventLineWithPortrait.",
        ['npc (char id 24-47)', 'variant (0-64)']),
    474: ('SetGuestRosterGate', 'actor',
        "Write arg0 to the header byte of the daily guest-NPC roster (RF4S.exe data at the IDB label g_currentEventParticipantNpcList_8u16; initialised to 100, and Town_BuildDailyGuestNpcRoster spawns no guests when it is 0). If arg1 != 0, also clear the roster's 'already built' bit (header word bit 0x2) so the next roster build runs again.",
        ['roster gate value (0 = no guests)', 'force rebuild (0/1)']),
    475: ('SetNpcStateByte', 'actor',
        "Write arg1 to byte +58 (0x3A) of the NPC's record (g_gameGlobalsSlotTable entry) for char id < 48. What the byte means is not established. The 'relationship/state-machine' label has no support. An invalid id or missing table writes to address 0x3A (deliberate crash).",
        ['npc (char id, <48)', 'value']),
    476: ('RecruitNpcToParty', 'actor',
        "Add an NPC to the player's party. If the NPC has no actor yet, stream it in (Npc_StreamInById) and place it at the player's position. Then Companion_AddOrSyncWithMarriageTrigger puts it in a free companion slot (Npc_RecruitAsCompanionAndStateClean -> Companion_FinalizeInPartyAllocStatsAndGauge: party slot, friendship gauge, equipment/stats). If both slots are full, companion 1 is dismissed first, and a date with them ends (EV_DATE_FINISH). No-op if the NPC is already a companion.",
        ['npc (char id)']),
    477: ('RecruitNpcToParty', 'actor',
        "Add an NPC to the player's party. If the NPC has no actor yet, stream it in (Npc_StreamInById) and place it at the player's position. Then Companion_AddOrSyncWithMarriageTrigger puts it in a free companion slot (Npc_RecruitAsCompanionAndStateClean -> Companion_FinalizeInPartyAllocStatsAndGauge: party slot, friendship gauge, equipment/stats). If both slots are full, companion 1 is dismissed first, and a date with them ends (EV_DATE_FINISH). No-op if the NPC is already a companion.",
        ['npc (char id)']),
    478: ('RecruitNpcToPartyHeld', 'actor',
        "Same as RecruitNpcToParty (stream in at the player's position if needed via Npc_RequestStreamInViaController + Npc_SetSlotWorldPosition, then add to a companion slot), then set (arg1 != 0) or clear bit 0x40000000 of the NPC record +52. That bit is the scene-held flag: Friendship_QueueFirstNpcEncounterEvent skips NPCs that have it, and Companion_DismissNpcAndRestoreSchedule clears it.",
        ['npc (char id)', 'held (0/1)']),
    479: ('RecruitNpcToPartyHeld', 'actor',
        "Same as RecruitNpcToParty (stream in at the player's position if needed via Npc_RequestStreamInViaController + Npc_SetSlotWorldPosition, then add to a companion slot), then set (arg1 != 0) or clear bit 0x40000000 of the NPC record +52. That bit is the scene-held flag: Friendship_QueueFirstNpcEncounterEvent skips NPCs that have it, and Companion_DismissNpcAndRestoreSchedule clears it.",
        ['npc (char id)', 'held (0/1)']),
    480: ('RecruitHostNpcToParty', 'actor',
        "If there is a current interaction NPC (char id != 0xFFFF), add the script host's actor (host+32, i.e. the NPC whose script is running) to the party via Companion_AddOrSyncWithMarriageTrigger. That call dismisses companion 1 if both slots are full and ends a date with them. No args.",
        []),
    482: ('GetPartyMemberId', 'query',
        "Read a party member's identity field (task +8) by slot into the VM output: arg0 = 0 for companion 1, 1 for companion 2. Returns 0 if that slot is empty. Used to branch dialogue on who is currently in the party.",
        ['slot (0=companion 1, 1=companion 2)']),
    483: ('DismissBothCompanions', 'companion',
        'Dismiss both companions from the party. For each slot, Companion_SyncToScene kills its AI script and gauge. An NPC goes back to its schedule (Companion_DismissNpcAndRestoreSchedule), staying on the current map if its schedule has a spot here, else warping out with the departure effect (action 0x8C). A date in state 3/4 ends (EV_DATE_FINISH). A tamed monster is recalled to the farm (MonsterFarm_RecallCompanionAndRehome). No args.',
        []),
    484: ('DismissBothCompanionsQuiet', 'companion',
        "Dismiss both companions like op 483, but first set dismiss-mode bit 0x1, which suppresses the departure effect (Action_TriggerAttacker 0x8C at the companion's position) for NPCs and recalled monsters. No args.",
        []),
    485: ('DismissBothCompanionsEx', 'companion',
        "Dismiss both companions with options. arg0 != 0 sets mode bit 0x2: the NPC is always sent back to its schedule, skipping the 'stay on this map' path. arg1 != 0 sets bit 0x1: no departure effect.",
        ['force return to schedule (0/1)', 'no departure effect (0/1)']),
    486: ('DismissCompanionByCharId', 'companion',
        "Dismiss the one companion whose char id matches arg0 (no-op if none), with the same two mode flags as op 485. arg0 = 0 matches the script host's actor; arg0 = 22 is replaced by GameFlag REG_CHILD_ID (5 bits), not the spouse.",
        ['char id (0 = host actor, 22 = REG_CHILD_ID)', 'force return to schedule (0/1)', 'no departure effect (0/1)']),
    489: ('SetCompanionsSceneHeld', 'companion',
        "Set (arg0 == 0) or clear (arg0 != 0) the scene-held bit 0x40000000 of both companions' NPC records. When clearing at night (hour < 6 or > 18), queue companion event kind 2 for companion slots 1 and 2 through Friendship_QueueFirstNpcEncounterEvent. That call skips the spouse, NPCs still held, NPCs with friendship level >= 7, NPCs with a date state, and runs only when REG_SUBEV_NOW is 0. This is the late-night companion check, not a first meeting.",
        ['release (0 = hold, else release and run the night check)']),
    490: ('QueryDatePartnerAtDateSpot', 'query',
        "reg0 = 1 if your date is here: a companion (or, when companion slot 0 is empty, the script host's actor) with char id < 24, NPC date state 3 (record +52 bits 24-26 == 3, on a date), standing on the map stored in GameFlag REG_DATE_MAP. If that NPC was found through a companion slot, it also writes packed flag / achievement 771. Returns 0 when FLG_NEXT_IS_MAPJUMP_EVENT is set. No args.",
        []),
    491: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    492: ('FaceNpcToPlayer', 'actor',
        "Set the script host NPC's scripted-facing mode (bits 16-17 of the dword at [actor+304]+448, read back by op 493) to arg0. Mode 1 also gives the NPC a stand point 96 world units from the player, on the line toward the NPC (written to [actor+296]+194/196), so it walks up and faces the player. Any other mode clears that stand point. Acts only on the host actor (host+32).",
        ['mode (0 = off, 1 = stand in front of player, 2 = mode 2 without stand point)']),
    494: ('SetCompanionVisible', 'companion',
        'Show or hide the companions. arg1 == 0 sets control_flags (+0x238) bit 0x4 (hidden, the same bit op 141 SetActorOpacity uses) on companion slot arg0 (0/1; >= 2 = both); non-zero clears it (shown; unlike op 141 no opacity is applied). The companion move/pose ops (496-501) clear the same bit and op 503 skips hidden companions. Nothing here affects damage.',
        ['slot (0/1, >=2 = both)', 'visible (0 = hide, else show)']),
    502: ('WaitCompanionSettled', 'query',
        'Blocking wait: while the selected companion(s) are still moving (record +20 bit 0x8) or still turning (record +20 bit 0x800 with actor +158 != +156), the handler returns 1, so the op re-runs next tick. Otherwise it returns 0 and the script continues. Writes no register.',
        ['slot (0/1, 2 = both)']),
    503: ('ShowCompanionEmote', 'companion',
        'Show an emote icon over a companion (companion form of op 211 ShowActorEmote). For companion slot arg0 (0/1, 2 = both) whose actor is not hidden (control_flags bit 0x4 clear), Npc_StopAnimAndClearOutfitOverride(actor, arg1) stores arg1 at actor+0x140 and, unless the same icon (>= 16) is already up, spawns Action 143 (ActionConstructor_EmotionIcon, subtype = icon) and plays an SFX for icons 4/5, 6/8 and 14; arg1 = 0 clears the icon. Then clears control_flags bit 0x4 and field_B4 bits 0x10C. No animation or outfit is touched.',
        ['slot (0 = companion 1, 1 = companion 2, 2 = both)', 'emote icon id (0 = clear)']),
    505: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    507: ('PopulateSlayRequest', 'quest',
        "Post a kind-1 (slay monsters) request into the host NPC's request record (char id < 24, else record 0). arg0 = monster char id (0 = DailyVisitor_PickWantedItem: weighted pick of 48..199, 1-in-16 chance of the 200..253 boss band, story-gated). arg1 = kill count (0 = random 1-4; forced to 1 for ids 200..253). Each further arg is a reward CATEGORY: Item_RollRandomIdInCategory rolls one reward item per arg into rewards[0..3] (-1 skips). The record is written only if not already posted (status bit 0x2), except record 0. Status becomes posted + fresh (0x4002). reg0 = 1 if a target existed.",
        ['monster char id (0 = random)', 'kill count (0 = random 1-4)', 'reward category … (up to 4, -1 = none)']),
    508: ('PopulateQuestKind2RandomRewards', 'quest',
        "Post a kind-2 request into the host NPC's record (char id < 24, else record 0; skipped if already posted, except record 0): +2 = arg0 item, +5 = arg1, +4 = arg2 (count). Each further arg is a reward category: Item_RollRandomIdInCategory rolls up to 4 reward items (re-rolling up to 64 times so a reward never equals the target item) into rewards[0..3]. No register result. The preview op (532) returns target / count / rewards / param in reg0 / reg1 / reg2-4 / reg5.",
        ['target item id', 'param byte (+5; corpus: an NPC char id local / REG_CHILD_ID)', 'count (+4)', 'reward category … (up to 4)']),
    509: ('PopulateQuestKind2RandomRewards', 'quest',
        "Post a kind-2 request into the host NPC's record (char id < 24, else record 0; skipped if already posted, except record 0): +2 = arg0 item, +5 = arg1, +4 = arg2 (count). Each further arg is a reward category: Item_RollRandomIdInCategory rolls up to 4 reward items (re-rolling up to 64 times so a reward never equals the target item) into rewards[0..3]. No register result. The preview op (532) returns target / count / rewards / param in reg0 / reg1 / reg2-4 / reg5.",
        ['target item id', 'param byte (+5; corpus: an NPC char id local / REG_CHILD_ID)', 'count (+4)', 'reward category … (up to 4)']),
    510: ('PopulateQuestKind2LiteralRewards', 'quest',
        'Post a kind-2 request like op 508, but the trailing args are literal reward item ids copied verbatim into rewards[0..3] (no roll, no stop on 0).',
        ['target item id', 'param byte (+5)', 'count (+4)', 'reward item id … (first 4 kept)']),
    511: ('PopulateQuestKind3RandomRewards', 'quest',
        "Post a kind-3 request into the host NPC's record: +6 = arg0, +8 = arg1 (two u16s, presumably two items; +2 target stays 0), +4 = arg2, +5 = arg3. Each extra arg (from arg4) is a reward category rolled into rewards[1..3]. The loop index is off by one, so rewards[0] stays 0 and a 4th category is dropped.",
        ['item A (+6)', 'item B (+8)', 'count (+4)', 'param byte (+5)', 'reward category … (up to 3)']),
    512: ('PopulateQuestKind3RandomRewards', 'quest',
        "Post a kind-3 request into the host NPC's record: +6 = arg0, +8 = arg1 (two u16s, presumably two items; +2 target stays 0), +4 = arg2, +5 = arg3. Each extra arg (from arg4) is a reward category rolled into rewards[1..3]. The loop index is off by one, so rewards[0] stays 0 and a 4th category is dropped.",
        ['item A (+6)', 'item B (+8)', 'count (+4)', 'param byte (+5)', 'reward category … (up to 3)']),
    513: ('PopulateQuestKind4RandomRewards', 'quest',
        "Post a kind-4 request into the host NPC's record: +2 = arg0 item, +5 = arg1, +4 = arg2 (count). Each further arg is a reward category rolled once into rewards[0..3] (no re-roll). The 'chained' seed feedback is dead: every iteration re-reads its own arg.",
        ['target item id', 'param byte (+5)', 'count (+4)', 'reward category …']),
    514: ('PopulateQuestKind4RandomRewards', 'quest',
        "Post a kind-4 request into the host NPC's record: +2 = arg0 item, +5 = arg1, +4 = arg2 (count). Each further arg is a reward category rolled once into rewards[0..3] (no re-roll). The 'chained' seed feedback is dead: every iteration re-reads its own arg.",
        ['target item id', 'param byte (+5)', 'count (+4)', 'reward category …']),
    515: ('PopulateQuestKind4LiteralRewards', 'quest',
        'Post a kind-4 request with count forced to 1: +2 = arg0 item, +5 = arg1. arg2 is never read (the literal loop starts at index 3). From arg3 on, literal reward item ids go verbatim into rewards[0..3].',
        ['target item id', 'param byte (+5)', '(ignored)', 'reward item id …']),
    516: ('PostBoardQuestKind5', 'quest',
        'Overwrite request record 0 (the board record, whoever the host NPC is) with a kind-5 entry: +5 = arg0, +10 = host char id, state 1, status reset to posted (0x2). No target item, count or rewards.',
        ['param byte (+5)']),
    517: ('PostBoardQuestKind5', 'quest',
        'Overwrite request record 0 (the board record, whoever the host NPC is) with a kind-5 entry: +5 = arg0, +10 = host char id, state 1, status reset to posted (0x2). No target item, count or rewards.',
        ['param byte (+5)']),
    518: ('PostBoardQuestKind6', 'quest',
        'Overwrite request record 0 (the board record) with a kind-6 entry: +5 = arg0, +4 = arg1 (count/goal), no target item and no rewards.',
        ['param byte (+5)', 'count (+4)']),
    519: ('PostBoardCraftQuest', 'quest',
        "Overwrite request record 0 with a kind-7 (craft) entry: +8 = arg0 craft category, +2 = arg1 item, +5 = arg2, +4 = arg3. Then load that category's craft data and, if the item has a recipe, return its up to 6 non-zero ingredient ids in reg1..reg6 and their count in reg0.",
        ['craft category', 'item id', 'param byte (+5)', 'count (+4)']),
    521: ('PopulateQuestKind9LiteralRewards', 'quest',
        "Post a kind-9 request into the host NPC's record (else record 0): +2 = arg0 item. Literal reward item ids from arg1 go into rewards[0..3] (stop at the first 0). The record pointer is bound to the script task (task+136) so the following accept/complete/reward ops use it.",
        ['target item id', 'reward item id … (0 ends)']),
    522: ('PopulateQuestKind10RandomRewards', 'quest',
        "Post a kind-10 request (no target, count or param) into the host NPC's record (else record 0) and bind it to the script task (task+136). Each arg is a reward category rolled into rewards[0..3]; a 0 category stops the list.",
        ['reward category … (0 ends)']),
    523: ('PopulateQuestKind10LiteralRewards', 'quest',
        "Post a kind-10 request (no target) into the host NPC's record (else record 0), bind it to the script task (task+136), and copy the literal reward item ids (0 ends) into rewards[0..3].",
        ['reward item id … (0 ends)']),
    524: ('NopCompleteSubEventGoals', 'flow',
        'No-op as opcode 524. The shared handler only acts when the current opcode is >= 537; op 548 is the working form (sets every active sub-event goal to state 2, complete).',
        []),
    525: ('QuestOnComplete', 'quest',
        'Complete the quest bound to the script task (task+136): RQ clear count +1, write the quest id to a packed flag, queue companion event 10, Quest_OnComplete_TriggerNpcReactions (friendship). A villager request (record npc != 0) adds prince points (category 7). A board request adds category-6 points, bumps REG_RQ_COUNT, or sets the per-insert flag (2684 + REG_INSERT_NOW) when REG_INSERT_NOW is set; for board quest ids 33-36 it instead clears daily-visitor discount bit 0-3, and decrements REG_REM_QUEST_COUNT. The record is then zeroed and marked done (0x8001). No items are given here; the reward popup op does that.',
        []),
    526: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    528: ('QueryQuestRewardItem', 'quest',
        'reg0 = reward item idx (0-3) of request record [arg0] (the 24-byte request record of char id arg0; 0 = the board record). An index >= 4 returns 1. The record index is not range-checked.',
        ['request record (char id < 24, 0 = board)', 'reward index (0-3)']),
    529: ('ClearAllRequestRecords', 'quest',
        "Zero all 24 request records (576 bytes: the board record and every villager's request, including status bits). No args.",
        []),
    531: ('ClearBoardRequest', 'quest',
        'Dispatch em.bin alt action EV_SUBEV_COM_52, zero request record 0 (the board record, all 24 bytes), and set scene control flags (& 0xFF3EFFFF | 0x800000). No args.',
        []),
    532: ('QueryNpcQuestPreview', 'quest',
        "If the interaction NPC's request record (char id < 24, else record 0) is posted (status 0x2): reg0 = target item (+2), reg1 = count (+4), reg2..reg4 = rewards[0..2], reg5 = param byte (+5), reg6 = accepted (status bit 0x4). Otherwise reg6 = 0 and the other registers are unchanged.",
        []),
    533: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    535: ('QueryQuestRemainingByItem', 'quest',
        'reg0 = max(0, count - progress) of the first request record whose target equals arg0 (0 if its state is 2). Bug: the loop bound is an uninitialised stack byte (the unused home slot of the 2nd argument), so the number of records searched is undefined.',
        ['item id']),
    536: ('StartReservedSubEvent', 'quest',
        "If no sub-event is running (REG_SUBEV_NOW == 0) and one is reserved (REG_SUBEV_RSV != 0): move RSV into NOW and clear RSV. Set request-array flag 0x4, dispatch em.bin EV_SUBEV_INIT and the sub-event's own entry (id + 118, for ids 25..143), clear scene flag 0x200000, zero two more 9-bit registers (packed 0x80B4 / 0x80BD), and register SubEvent_AdvanceNowTimer in a free calendar callback slot (index kept for op 549). No args.",
        []),
    537: ('QueueSubEventGoalKind2', 'quest',
        'Queue-mode alias of op 508. Because the opcode is >= 537, the handler does not touch the NPC request record. If a sub-event is running (REG_SUBEV_NOW != 0) and fewer than 20 entries are queued, it appends a 24-byte kind-2 entry {+2 item = arg0, +5 = arg1, +4 count = arg2, +10 host char id, state 1 = active} to the sub-event goal queue (count at request-array byte 3, entries at RF4S.exe data 0xE9AF0C). Reward args are ignored in this mode.',
        ['target item id', 'param byte (+5)', 'count (+4)']),
    538: ('QueueSubEventGoalKind2', 'quest',
        'Queue-mode alias of op 508. Because the opcode is >= 537, the handler does not touch the NPC request record. If a sub-event is running (REG_SUBEV_NOW != 0) and fewer than 20 entries are queued, it appends a 24-byte kind-2 entry {+2 item = arg0, +5 = arg1, +4 count = arg2, +10 host char id, state 1 = active} to the sub-event goal queue (count at request-array byte 3, entries at RF4S.exe data 0xE9AF0C). Reward args are ignored in this mode.',
        ['target item id', 'param byte (+5)', 'count (+4)']),
    539: ('QueueSubEventGoalKind3', 'quest',
        'Queue-mode alias of op 511: append an active kind-3 entry {+6 = arg0, +8 = arg1, +4 = arg2, +5 = arg3, +10 host} to the sub-event goal queue when REG_SUBEV_NOW != 0 (max 20). No reward rolls.',
        ['item A (+6)', 'item B (+8)', 'count (+4)', 'param byte (+5)']),
    540: ('QueueSubEventGoalKind3', 'quest',
        'Queue-mode alias of op 511: append an active kind-3 entry {+6 = arg0, +8 = arg1, +4 = arg2, +5 = arg3, +10 host} to the sub-event goal queue when REG_SUBEV_NOW != 0 (max 20). No reward rolls.',
        ['item A (+6)', 'item B (+8)', 'count (+4)', 'param byte (+5)']),
    541: ('QueueSubEventGoalKind4', 'quest',
        'Queue-mode alias of op 513: append an active kind-4 entry {+2 item = arg0, +5 = arg1, +4 count = arg2, +10 host} to the sub-event goal queue when REG_SUBEV_NOW != 0 (max 20). No reward rolls.',
        ['target item id', 'param byte (+5)', 'count (+4)']),
    542: ('QueueSubEventGoalKind4', 'quest',
        'Queue-mode alias of op 513: append an active kind-4 entry {+2 item = arg0, +5 = arg1, +4 count = arg2, +10 host} to the sub-event goal queue when REG_SUBEV_NOW != 0 (max 20). No reward rolls.',
        ['target item id', 'param byte (+5)', 'count (+4)']),
    543: ('QueueSubEventGoalKind5', 'quest',
        'Queue-mode alias of op 516: append an active kind-5 entry {+5 = arg0, +10 host char id} to the sub-event goal queue when REG_SUBEV_NOW != 0 (max 20). Record 0 is not touched.',
        ['param byte (+5)']),
    544: ('QueueSubEventGoalKind5', 'quest',
        'Queue-mode alias of op 516: append an active kind-5 entry {+5 = arg0, +10 host char id} to the sub-event goal queue when REG_SUBEV_NOW != 0 (max 20). Record 0 is not touched.',
        ['param byte (+5)']),
    545: ('QueueSubEventGoalKind6', 'quest',
        'Queue-mode alias of op 518: append an active kind-6 entry {+5 = arg0, +4 = arg1} to the sub-event goal queue when REG_SUBEV_NOW != 0.',
        ['param byte (+5)', 'count (+4)']),
    546: ('QueueSubEventCraftGoal', 'quest',
        'Queue-mode alias of op 519: append an active kind-7 craft entry {+8 craft category = arg0, +2 item = arg1, +5 = arg2, +4 = arg3} to the sub-event goal queue when REG_SUBEV_NOW != 0. The recipe lookup still runs: ingredients go to reg1..reg6, count to reg0.',
        ['craft category', 'item id', 'param byte (+5)', 'count (+4)']),
    547: ('QueueSubEventGoalKind10', 'quest',
        'Queue-mode alias of op 522: append an empty active kind-10 entry (only the host char id) to the sub-event goal queue when REG_SUBEV_NOW != 0. The category args are ignored and the task binding is not made.',
        ['(ignored) …']),
    548: ('CompleteAllSubEventGoals', 'flow',
        "Set every sub-event goal-queue entry in state 1 (active) to state 2. State 2 is 'complete' for these records: op 552 then reports 0 remaining, and NpcAi_AdvanceQuestProgressAndScheduleReaction uses 2 for completed kill requests. Only this opcode does anything; op 524 (same handler) is a no-op. No args.",
        []),
    549: ('FinishCurrentSubEvent', 'quest',
        'End the running town sub-event (only if REG_SUBEV_NOW != 0). Set its done bit (flag 1224 + id), store the id in the 9-bit register at 0x80AB, clear REG_SUBEV_NOW and flag 334, dispatch em.bin EV_SUBEV_INIT, and clear request-array flag 0x4. Also roll flag 5785 = 1/2 and refresh NPC 1-23 schedules. Wipe the sub-event goal queue and 32 bytes after it, and clear per-NPC sub-event record bits and flags (1427+i, 863-885 blocks) for ids 1-31. Add category-5 prince points (unless save bit 0x40) and unregister the SubEvent_AdvanceNowTimer calendar callback that op 536 installed. No args.',
        []),
    550: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    551: ('ResetSubEventGoals', 'flow',
        'Clear the sub-event goal queue: entry count = 0 and all 20 x 24-byte entries zeroed. No args.',
        []),
    552: ('GetSubEventGoalRemaining', 'query',
        "reg0 = max(0, count - progress) of the first sub-event goal-queue entry whose target item equals arg0 (0 if that entry's state is 2 or none matches).",
        ['item id']),
    553: ('SetNpcSubEventFlag', 'actor',
        'Set (arg0 != 0) or clear bit 0x800000 of record +52 for each listed NPC (char id < 48). If the list is empty or contains a 0, the bit is applied to all villagers 1-23 instead. FinishCurrentSubEvent (op 549) clears the same bit for everyone, so it is a sub-event participation marker; no reader was located, so what the bit gates is unproven (hence the neutral name).',
        ['set (0 = clear, else set)', 'npc char id … (0 or none = all villagers 1-23)']),
    554: ('SetNpcSubEventFlag', 'actor',
        'Set (arg0 != 0) or clear bit 0x800000 of record +52 for each listed NPC (char id < 48). If the list is empty or contains a 0, the bit is applied to all villagers 1-23 instead. FinishCurrentSubEvent (op 549) clears the same bit for everyone, so it is a sub-event participation marker; no reader was located, so what the bit gates is unproven (hence the neutral name).',
        ['set (0 = clear, else set)', 'npc char id … (0 or none = all villagers 1-23)']),
    555: ('SetNpcAttentionRadius', 'dialogue',
        "Set the NPC's attention radius (record +26, stored as a byte zero-extended into the word) and run Npc_BroadcastBubbleProximityHandshake. For every villager with a non-zero +26, that routine flags each other villager on the same map with record +48 bit 0x20 when it is within +26 tile units (octagonal distance) and is not itself radiating, muted (+20 bit 0x40) or busy (+228 bit 0x1). 0 turns it off. It is a distance, not a bubble variant.",
        ['npc (char id)', 'radius (tile units, 0-255; 0 = off)']),
    556: ('SetNpcAttentionRadius', 'dialogue',
        "Set the NPC's attention radius (record +26, stored as a byte zero-extended into the word) and run Npc_BroadcastBubbleProximityHandshake. For every villager with a non-zero +26, that routine flags each other villager on the same map with record +48 bit 0x20 when it is within +26 tile units (octagonal distance) and is not itself radiating, muted (+20 bit 0x40) or busy (+228 bit 0x1). 0 turns it off. It is a distance, not a bubble variant.",
        ['npc (char id)', 'radius (tile units, 0-255; 0 = off)']),
    558: ('SetNpcRecognitionFlags', 'flag',
        "Write a per-NPC packed game-flag (base id 1451 + npc id) = [arg0] for each npc id in the variadic list (an npc id of 0 falls back to the married partner). These are the 23 per-NPC recognition flags (1451-1473); like op290/op698 they go through GameFlags_WritePacked_OrAchievement -- a graded packed-flag write, NOT one of the ~30 named Steam achievements.",
        ['value', 'npc ids (variadic)']),
    565: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    566: ('RecordFestivalPlacement', 'flag',
        "Record the player's placement in a festival contest. If placement is 1-3, broadcast it to the NPCs (Memory_BroadcastEventToNpcsAndApplyPlayerEffect(festival, placement)). Then read that festival's 2-bit best-placement field (packed ids 4876-4904; 0 counts as 4) and store the new placement if it is better, i.e. lower. The ids are packed game-flag fields, not achievements or story steps.",
        ['placement (1-3)', 'festival id (REG_FESTA value: 6, 8-17)']),
    567: ('GetTomorrowsCalendarEvent', 'query',
        "reg0 = the calendar event id scheduled for tomorrow, if that event is enabled (bit id set in the calendar-event enable bitmap, dword g_effectAppliedBits+4); else 0. The date is taken as tomorrow only when the hour is 6-23 (before 6:00 it uses today's date). The id comes from the 4-byte records of archive 16340 (season, day -> event id).",
        []),
    569: ('RankFestivalContestants', 'query',
        "Rank three roster NPCs plus the player for the active festival (REG_FESTA). Scene_BuildNpcRoster picks 3 NPCs and Festival_RollContestCompetitorScores rolls each one's two score parts. The player is the 4th entry (id 0), scored with arg0/arg1. The entries are sorted by the sum of the parts (ties nudged down by 1), and the top three (id, part A, part B) go to reg0..reg8.",
        ['player score part A', 'player score part B']),
    577: ('GetFestivalResults', 'query',
        "For places 1-4 of the current scene event (u16 ids at scene+376, values at scene+384): reg(2i+1) = id, reg(2i+2) = value. When the id is 0 (the player) and scene+533 bit 0x8 is clear, it broadcasts the player's placement i+1 to the NPCs (Memory_BroadcastEventToNpcsAndApplyPlayerEffect(event, i+1)). reg0 = the event's calendar date (season*100 + day) from archive 16340. There is no computed score.",
        []),
    580: ('GetGivenItemStats', 'query',
        "Read stats of the item slot stored at g_currentSceneContext+356, which is the item last thrown or handed to an NPC (written by Throw_DispatchToNpcWithQuestGiftCheck), not the item in the player's hand. For ids 132-317 (equipment), Item_ComputeEffectiveStats gives: reg0 = slot flag bit 0, reg1 = u16 slot+18, reg2 = (slot+2 >> 1) & 7, reg3/reg4 = two stat percentages clamped to +/-100. For other items: reg0 = flag bit 0, reg1 = (dword slot+8 >> 10) & 0x3FF, reg2 = u8 slot+6, reg3 = the craft record's level byte (>99 -> 1). reg5 = item id in both cases.",
        []),
    581: ('CheckFishRecord', 'query',
        'Compare arg0 with the saved fish record (high dword of g_fishCaughtBitfield). If arg0 is larger, store it and set reg0 = 0 (new record). Otherwise reg0 = 1 on a tie and 2 if smaller. reg1 = the previous record.',
        ['fish size rank']),
    583: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    584: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    585: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    586: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    587: ('PlaceFurniture', 'item',
        'Place a furniture tile object (id [arg0], in the tile-object id space, not the item table) in room [arg1] at tile (arg2, arg3). Only allowed if that room has fewer than 16 active objects; id 328 is exempt and instead upgrades an existing 327 record in place. arg1 = -1 means the current room; tile -1 = default position. If placed in the current room (and id != 328), plays sfx 0x100226D and action 0x13 at the tile (or at the player). reg0 = 1 if placed, else 0.',
        ['furniture/tile-object id', 'room id (-1 = current room)', 'tile x (-1 = default/player)', 'tile y (-1 = default/player)']),
    588: ('IsFurniturePlaced', 'query',
        'Query whether a furniture tile object with id [arg0] is active anywhere, in any room (it scans all 64 registry slots). reg0 = 1 if found, else 0.',
        ['furniture/tile-object id']),
    590: ('BreakFurniture', 'item',
        'Break the host furniture object: dirt-cloud puff, drop item 1022 (Lumber) and item 1023 (Material Stone) at its position, free its tile-object registry slot and destroy the object. Takes no arguments.',
        []),
    592: ('CanPlaceFurnitureInRoom', 'query',
        'Query whether room [arg0] can take another furniture tile object: reg0 = 1 when fewer than 16 are active in that room. arg0 = 0 means the current room.',
        ['room id (0 = current room)']),
    593: ('PickRandomPlacedFurniture', 'effect',
        'From a list of candidate furniture ids, gather those that have an active tile object in the current room and pick one at random. The pick is weighted by the id value itself (the ids are passed to MMIX_WeightedRandomPick as weights), and repeating an id raises its odds. Only 1 roll in 8 picks anything: 7/8 of the time reg0 = 0. reg0 = the picked id, or 0.',
        ['candidate furniture ids (variadic)']),
    598: ('RollRandomItemMatchingDisplayName', 'item',
        'Roll a random item among all items whose display-name string id == arg0 (items sharing a name) that pass Item_IsInRandomItemPool (the story/unlock gate); reg0 = the pick. If none pass, reg0 = the matching item with the lowest unlock threshold (data_28), or 82 if nothing matches.',
        ['display-name string id']),
    599: ('RollRandomDishItem', 'item',
        'Pick one of shop categories 5-11 uniformly (item ids 134-299, the cooked-dish range, Trout Sashimi..Turnip Heaven) and roll an unlocked item from it with Item_RollRandomIdInCategory; reg0 = item id. No args.',
        []),
    600: ('RollRandomEquipmentItem', 'item',
        'Pick one of 16 fixed shop categories uniformly (15-19, 24-26 weapons; 33 shields; 34 accessories; 35 headgear; 36 shoes; 37 armor; 48/49 skill and spell items; 57 the 318-327 bread range) and roll an unlocked item from it; reg0 = item id. No args.',
        []),
    601: ('RollRandomFurItem', 'item',
        'Roll a random unlocked item from {814, 815, 816, 879, 939} (Fur S/M/L, Wooly Furball, Quality Puffy Fur); reg0 = item id. If none passes Item_IsInRandomItemPool, falls back to the lowest-threshold member (default 814). No args.',
        []),
    602: ('RollRandomMedicineOrFailedDish', 'item',
        'Roll a random unlocked item from ids 115-119, 123, 131-133 (Antidote Potion, Para-Gone, Roundoff, Cold Medicine, Formuade, Heavy Spice, Object X, Failed Dish, Disastrous Dish); reg0 = item id, fallback 132 (Failed Dish). No args.',
        []),
    603: ('RollRandomGrassItem', 'item',
        'Roll a random unlocked item from ids 71-81 (Medicinal Herb, Antidote Grass and the colored grasses); reg0 = item id, fallback = the lowest-threshold member (initially 71). No args.',
        []),
    604: ('RollRandomIngredientItem', 'item',
        'Roll a random unlocked item from the fixed set {5, 33, 37, 38, 123, 294, 301, 304, 305, 306, 313} (Pink Melon, Leek, Hot-Hot Fruit, Giant Hot-Hot Fruit, Heavy Spice, Relax Tea Leaves, Chocolate, Milk S/M/L, Honey); reg0 = item id, default 301 (Chocolate). No args.',
        []),
    605: ('RollRandomSeasoningItem', 'item',
        'Roll a random unlocked seasoning/cooking-base item: ids 123-126, 270, 271, 302, 310, 314-317 (Heavy Spice, Sweet Powder, Sour Drop, Mixed Herbs, Ketchup, Butter, Wine, Mayonnaise, Flour, Oil, Curry Powder, Rice Flour); reg0 = item id, default 314 (Flour). No args.',
        []),
    607: ('RollRandomFlowerSeedItem', 'item',
        'Roll a random unlocked flower seed: ids 758, 759, 765, 771, 773-785 (Moondrop, Toyherb, Pink Cat, Charm Blue, Cherry Grass ... White Crystal Seeds; vegetable seeds in 758-785 are excluded); reg0 = item id, default 759 (Toyherb Seeds). No args.',
        []),
    608: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    614: ('SetDialogueBoxMode', 'dialogue',
        'Set the dialogue-box mode byte (byte 2 of g_gameGlobalsSlotTable.entries[9]). 2 = narration: no speaker-name label, no text blips; 0 = normal; 1 = the menu-style dialogue layout (every shipped use; FMenu_*, EmotePortrait_SpawnPositioned, Dialogue_SpawnHud and ChoiceDialog code pick different widget offsets when the byte is 1). (The existing description is right; only the name is misleading.)',
        ['mode (0 = normal, 1 = menu-style dialogue layout, 2 = narration)']),
    616: ('QueryAndSetCraftedFlag', 'item',
        "Test-and-set the 'has been crafted' flag. For an item id: looks up its craft record (Item_FindCraftDataRecordForItemId); reg0 = the OLD bit at zone2 + craft_id + 1062, then the bit is set (reg0 = 0 and nothing is set if the item has no craft record). For 100000: the handler sets flag zone2+1403 BEFORE reading it, so reg0 is always 1 (when a save is loaded).",
        ['item id (100000 = misc-craft flag)']),
    617: ('ShowStaffCredits', 'effect',
        "Start the staff-credits task (task name 'staff', tick ItemPickupIcon_Tick_StateMachine). Mode 0 sets work+166 |= 0x10, mode 1 |= 0x18, modes 2 and 3 switch the tick to ItemPickupIcon_Tick_ScrollAndSpawn (the handler treats 2 and 3 identically). If the credits task already exists, it sets that task's work byte +172 = 1 (a finish/advance signal) only when host+312 is that task, and clears host+312.",
        ['mode (0, 1 = fade variants; 2/3 = scrolling credits)']),
    618: ('WaitStaffCreditsDone', 'query',
        "Block while the staff-credits task (from op 617) is running: the handler returns 1 while the task's tick is one of the two credits ticks, so the VM re-runs the op every step; it returns 0 (continues) once the task is gone. reg0 is not written. No args.",
        []),
    619: ('QueryNpcAcceptsPartyInvite', 'query',
        'Decide whether the current interaction NPC agrees to go out with the player (party invite). reg0 = 1 accept, 0 decline. Declines if: (char < 24) their flag 1451+id is set, or they are tied up in the reserved sub-event; (char 24/25) g_saveConfigFlags bit 6 is set; friendship level < 7 and the hour is outside 6..17; Ventuswill (char 21) before story progress 0x1FF; Doug (char 15) before 0x1A4. Otherwise the answer is cached for the day in npc_record+48 bits 26-27: roll accept with (95 + level/2)% if friendship >= 3, never below 3; Forte (4) always accepts.',
        []),
    620: ('MarkSpouseCleared', 'actor',
        'Record that the given NPC was married (spouse cleared): reports flag/achievement 16582 with the NPC id, sets g_saveConfigFlags bit 1, sets bit [id] in g_sys_spouseClearedBits (rf4_sys.sav), then runs Marriage_FinalizeOnceAndBroadcastWedding.',
        ['spouse char id']),
    624: ('SetDialogueHoldFrames', 'dialogue',
        "Lock out the player's advance input for N dialogue-box frames: sets a byte countdown that DialogueBox_TickStateMachine decrements every tick; while it is nonzero, DialogueBox_TickState5 ignores the confirm/skip buttons. Stops a line from being skipped too fast.",
        ['frames (0-255)']),
    625: ('EnterSharanceMazeStage', 'effect',
        "Start a Sharance Maze challenge stage (0 Garden of Light, 1 Smoldering Prominence, 2 Deepwater Shrine, 3 Dragon Ruins, 4 Challenge to Fantasy, 5 Banquet of Nightmares). Sets g_currentBossState_modeFlag = stage, remembers the current room and the player's tile for the return trip (Dungeon_BeginArea), then writes scene-context fields +0x3C = 442, +0x3E/+0x40 = 0x120, +0x42 = 0 and sets +0x38 bit 0x80. The script warps with the next op.",
        ['maze stage (0-5)']),
    626: ('GetMazeStageClearedBit', 'query',
        "reg0 = bit [arg0] of g_playerInventoryFlags_word. Bits 0-5 are the Sharance Maze stages cleared (0 Garden of Light ... 5 Banquet of Nightmares): the maze menu shows stage i+1 only if bit i is set, and bit 5 gates the 'You completed the Banquet of Nightmares' trophy text.",
        ['maze stage bit (0-5)']),
    627: ('JumpToRandomDate', 'time',
        "Move the calendar to a random date in the current year: keeps the time of day (seconds/minute/hour) and the year, sets day = random 1..30 and season = random 0..3, normalizes, then runs Calendar_FastForwardForSleep to the new target with the per-minute callbacks suppressed. Afterwards clears the player's field_B4 and sets game-main work+8 bit 1. No args.",
        []),
    629: ('SetRegisters', 'flag',
        'Load the VM REGISTER FILE reg0..reg9 (ctx+64..+100) from up to 10 argument values — reg[i] = arg[i]. These are the registers expressions read back via the reg tokens, SWITCH selectors dispatch on, and camera/position ops consume (GetPlayerPosition writes reg0/reg1; a staged PROMPT_CHOICE writes the pick to reg0). This op is how a script seeds them explicitly (1,825 uses). Registers are flat scratch — NOT saved across CALL — so consume them before the next op that writes reg0.',
        ['reg0 value', 'reg1 value', '…up to reg9']),
    630: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    636: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    638: ('GetHarvestReport', 'query',
        "Fill reg0..reg3 with the item ids of the weekly harvest report: reg0 = this week's bumper crop, reg1 = this week's poor crop, reg2/reg3 = next week's bumper/poor crop (the calendar advanced 6 days). Each value is the u16 at +96 of crop-kind record 38..78 in the current map's tile/crop table, chosen by the date-seeded daily RNG. No args.",
        []),
    643: ('ApplyPrinceOrder', 'effect',
        'Buy and apply Prince Point order [arg0] (sub-index arg1: festival id, license/NPC variant, etc.). Orders 32-50 need and deduct all four costs (PP, lumber, material stone, gold); every other order deducts only PP = GetCost(id, sub). If unaffordable nothing changes. reg0 = 1 if the order was paid and applied, else 0.',
        ['order id', 'sub-index / variant']),
    644: ('GetPrinceOrderState', 'query',
        'reg0 = the state of Prince Point order [arg0]: for ids 0-2 and 29, bit [arg1] of the applied-order bitsets; for shop/license orders (10-28), the unlock bit (12 returns the 2-bit Cooking Bread tier); for storage orders (31+), the current upgrade level read from GameFlags.',
        ['order id', 'sub-index / bit (usually 0)']),
    645: ('PromotePrinceRank', 'item',
        "Promote the prince rank for every tier whose tourist threshold is reached (it can jump several ranks, up to 5), add each tier's gold reward to player gold (clamped to 2e9; sets flag 810 once gold >= 10,000,000). Outputs: reg0 = 1 if promoted, reg1 = the new rank, reg2 = the gold reward. No args.",
        []),
    646: ('GetPrinceRank', 'query',
        'Read the current prince rank into reg1 (NOT reg0; this handler writes vm+68). No args.',
        []),
    647: ('GetPrinceOrderCost', 'query',
        'reg0 = the cost of Prince Point order [arg0]. arg1 is the currency (0 PP, 1 lumber, 2 material stone, 3 gold) for the multi-currency orders (storage 31-38, room/farm expansion 39/40, barns 41-50). For orders with sub-variants it is the sub-index instead: order 0 = festival id (g_ppOrderFestivalCostBySub), order 29 = airship sub (0/1).',
        ['order id', 'currency (0 PP/1 lumber/2 stone/3 gold) or sub-index']),
    648: ('GetShippingCompletionPercent', 'query',
        'reg0 = shipping-list completion percent: the number of distinct shippable items ever shipped divided by the number of distinct shippable items, times 100, truncated and clamped to 100. Uses the ALL category (index 0) of the sale-records cache. No args.',
        []),
    650: ('GetLifetimeShippedGold', 'query',
        'reg0 = total gold earned from shipping over the whole save, all categories (sale-records category 0 = the ALL aggregate), capped at 2,000,000,000. No args.',
        []),
    652: ('GetPreviousMapId', 'query',
        'reg0 = scene-context word +348, which Map_OnEnter_QueueMapEvents sets to the previous g_lastInteractionActionId (the value it also writes to REG_PREV_MAPID) on each scene transition, i.e. the map the player came from. No args.',
        []),
    662: ('SetActorArmorBreak', 'actor',
        "Set (arg1 != 0) or clear bit 0x4000 of Actor_t.control_flags (+568) on the actor with char id [arg0] (0 player, <48 NPC, >=48 event actor). Requires the actor to have a stats block. What the bit means is unknown: its writers include Npc_BuildCharNpcActorTask, Actor_SpawnByCharId, Npc_SpawnCharEventActor, Actor_ResetToTameAndLeaveParty, Player_BeginThrowAction, the boss ultimate-attack action and op 664; it is cleared in Player_OnHitCancelInteractionAndCinematic, Quest_OnReactionDispatched_AdvanceState and others. Nothing supports 'armor break'.",
        ['char id', 'value']),
    663: ('MakeActorUntameable', 'actor',
        "Set the target actor's tame base (stats+0xDA) to 0, which makes the monster impossible to tame: MonsterTame_RollAttemptWithItem returns -1 when stats+218 == 0. arg0 = char id (0 player, <48 NPC, >=48 event actor, the usual case: event monsters 100-105/300).",
        ['char id (0=player, <48=NPC, >=48=event)']),
    664: ('LockActorMaxSp', 'actor',
        'On the target actor (char id: 0 player, <48 NPC, >=48 event actor), set stats+0xDC and stats+0xDE to -1 (IDB field names ai_sight_range / ai_fov_width), set control_flags (+568) bit 0x4000 (see op 662), and clear bit 0x800 of dword +40 of the object at actor field_108+32. Nothing here touches SP/RP.',
        ['char id (0=player, <48=NPC, >=48=event)']),
    676: ('GetMedalGoldRate', 'query',
        'reg0 = 20, the Rune Medal -> gold exchange rate that op 675 applies. The shipped use shows it in the exchange dialogue next to the medal count. No args.',
        []),
    681: ('RollBreadRecipe', 'item',
        "Roll the recipe the player learns from a recipe bread: arg0 = the bread item id (318/319 Medicine Bread(+), 320/321 Cooking Bread(+), 322/323 Weapon Bread(+), 324/325 Accessory Bread(+), 326/327 Farming Bread(+)). The pool is built from that bread's crafting-data archives, with weight 80 for the plain bread and 100 for the '+' version; Cooking Bread's pool depends on which kitchen utensils exist (or on unlock bit 23). reg0 = the rolled recipe's item id (0 if none).",
        ['bread item id (318-327)']),
    683: ('PlayCutsceneVideo', 'screen',
        "Play full-motion video [arg0] (Cutscene_PlayVideoById). If a dialogue box is still open (or a scripted event / dialogue-slot mismatch blocks it), the op instead nudges the dialogue to close (state 6 -> 7), tears down the two bubble slots, and returns 1 so the VM retries the op next step. The video therefore starts only once no dialogue is up; the dialogue is never 'advanced' as an alternative outcome.",
        ['video id']),
    684: ('IsProjectorSceneUnlocked', 'query',
        "reg0 = unlock bit [arg0] of the system-save scene-memory bitset: bits 0-26 from g_sys_scriptFlagBits0_26, bits 27-58 from g_sys_scriptFlagBits27_58 (bit arg0-27). Used by the Projector memory-playback menu to show which scenes ('Opening', 'Opening 2', 'Enter Vishnal', ...) can be replayed.",
        ['scene index (0-58)']),
    685: ('SetFreeLookCameraMode', 'flag',
        "Set the free-look camera control word (dword_...02E4) that ActionTask_TickFreeLookCamera reads every tick: nonzero lets the stick/d-pad drive the free-look camera; 2 (or higher) makes the camera exit (sfx 0x100223F, word reset to 0, task switched to ActionTask_TickPausedNoInputContext); 3 pauses it the same way without the reset. 0 = the tick's default branch.",
        ['mode (0, 1, 2 = exit, 3 = pause)']),
    686: ('GetFreeLookCameraMode', 'query',
        'reg0 = the free-look camera control word (see op 685); ActionTask_TickFreeLookCamera resets it to 0 when the camera exits, so scripts can poll for that. No args.',
        []),
    689: ('RespawnRoomFurnitureVisuals', 'effect',
        "Re-spawn the visual tasks of every active furniture/tile object in the player's current room/context (the one held by the player is skipped). A redraw of placed furniture; no monsters are involved. No args.",
        []),
    690: ('GetNpcGivenHat', 'query',
        "For NPC [arg0]: reg0 = npc_record+252 dword (nonzero while the NPC has / wears a headgear the player gave them), reg1 = that headgear's item id = 676 + npc_record+256 byte (0 if none; 677+ = Silver Hairpin, Gold Hairpin, Fancy Hat, ...). arg0 = 0 gives 0/0.",
        ['npc char id']),
    692: ('FinishPendingDate', 'actor',
        'Find the first NPC (ids 1-23) whose date state (npc_record+52 bits 24-26) is 1 or 2 (a date promised or scheduled today). If found: write packed flag/achievement 34346 = 0, reset that date state to 0, and dispatch em.bin entry 80 (EMFE_EV_DATE_FINISH, the post-date reset). No-op if no NPC has a pending date. No args.',
        []),
    693: ('nop', 'noop',
        'No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.',
        []),
    695: ('QuerySpouseClearedBit', 'query',
        'Intended: reg0 = bit [arg0] of g_sys_spouseClearedBits (rf4_sys.sav; set by op 620). Actual code (bug): reg0 = g_sys_spouseClearedBits & ((1 << arg0) != 0) = g_sys_spouseClearedBits & 1, so it reads only bit 0 whatever arg0 is (practically always 0).',
        ['spouse char id (ignored, see bug)']),
    696: ('RemoveItemFromBackpack', 'item',
        "Take [arg1] of item [arg0] from the backpack (60 slots). A slot matches if its id == arg0 and its flag bit (+2 bit 0) is set; with arg2 >= 0 it must also have level byte (+4) == 0 (arg2's value itself is not compared; -1 = any level). The first slot holding more than the count is reduced and the op ends. A slot holding <= count is emptied, and the search continues with the FULL count again (the remaining count is never reduced), so a split stack can lose more than asked. If nothing ended the search and the held item matches, it decrements the held stack up to count times and clears the carried records.",
        ['item id', 'count', 'level filter (-1 = any, >=0 = level-0 slots only)']),
    699: ('SetNarrationModeIf', 'dialogue',
        'If arg0 != 0, set the dialogue-box mode byte (the byte op 614 writes) to 2 = narration (no speaker-name label, muted text blips); if arg0 == 0, leave it unchanged. (The existing description is right; only the name is misleading.)',
        ['enable (nonzero = narration mode)']),
})

for _op, (_m, _c, _d, _a) in _M.items():
    _add(_op, _m, _c, _d, _a)

for _op, _tech in TECHNICAL.items():
    if _op in META:
        continue
    # var-array family: Write/ReadVarArrayKindN
    _mk = re.search(r"VarArrayKind(\d+)", _tech)
    if _mk:
        _n = int(_mk.group(1))
        _write = _tech.startswith("Script_VMOp_Write") or "Write" in _tech
        if _n == 7:                                   # kind 7 = dialogue portrait/face
            if _write:
                _add(_op, "SetPortrait", "dialogue",
                     "Set an NPC's dialogue portrait/face (kind-7 var array).",
                     ["portrait slot", "face id"])
            else:
                _add(_op, "GetPortrait", "query",
                     "Read an NPC's dialogue portrait/face (kind-7 var array).", ["portrait slot"])
        elif _write:
            _add(_op, "SetVar%d" % _n, "flag",
                 ("Write `value` into global script-variable bank %d at [index]. These banks are "
                  "ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the "
                  "rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible "
                  "to later scenes and SHARES storage with the choice-commit system (a committed "
                  "PROMPT_CHOICE writes its follow-up param into the same slots via the same "
                  "lookup). These slots also feed NPC villager-behavior AI and dialogue-text "
                  "substitution codes (a text code reads a stored slot, else falls back to a "
                  "default), so SetVar reaches beyond scene branching. Read it back with GetVar%d "
                  "(into reg0). IDA-verified: %s.") % (_n, _n, _tech),
                 ["index", "value"])
        else:
            _add(_op, "GetVar%d" % _n, "query",
                 ("Read global script-variable bank %d at [index] into reg0 -- the paired reader for "
                  "SetVar%d. Engine-global state (kinds 0-3 in the game-globals slot table, the rest "
                  "in dedicated arrays), shared with the choice-commit system, so it can read back a "
                  "value that an earlier scene or a committed choice stored. IDA-verified: %s.")
                 % (_n, _n, _tech),
                 ["index"])
        continue
    # no-op stubs: NoOp<NN>_StubReturn0
    if _tech.startswith("Script_VMOp_NoOp") and _tech.endswith("_StubReturn0"):
        _add(_op, "nop", "noop",
             "No-op stub -- the VM decodes the args then does nothing on the PC port "
             "(was likely a 3DS-era op). Safe to keep or delete.", [])
        continue
    if _tech.startswith("Script_VMOp_Invalid") and "Null" in _tech:
        _add(_op, "invalid", "noop",
             "Unused opcode -- the dispatch slot is null (no handler). Should not appear.", [])
    # empty handler slot: no symbol bound in the IDB -> opcode is never emitted
    if not _tech:
        _add(_op, "(unused)", "noop",
             "Empty dispatch slot -- no handler is bound to this opcode in the binary, "
             "so the game's scripts never emit it. Reserved / removed in the PC port.", [])
        continue
    # quest-request populate family: PopulateQuestRequestKind<N><shape>
    # These runtime ops fill the current NPC's daily quest-request slot with a randomized
    # "bring/craft/defeat" request built from template KIND N. The handler name
    # encodes the kind + the specifics (RandomCats / LiteralAlternates / TwoItems / Backref …).
    _qk = re.search(r"PopulateQuestRequestKind(\d+)(\w*)", _tech)
    if _qk:
        _n = int(_qk.group(1))
        _shape = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", _qk.group(2)).strip()
        _d = ("Populate the current NPC's daily quest-request slot using request template "
              "KIND %d" % _n)
        _d += (" (%s)." % _shape) if _shape else "."
        # Literal variants store the alternate objective items VERBATIM from args (no category
        # roll -- IDA-confirmed on op 510: "no Item_RollRandomIdInCategory call"); the others
        # roll from categories (and some shapes -- SimpleNoAlts/TwoArgsNoItem -- carry no alts).
        if "Literal" in _qk.group(2):
            _d += (" A runtime quest generator whose alternate objective items are the EXPLICIT "
                   "literal item ids passed as args (stored verbatim — NO random category roll).")
        else:
            _d += (" A runtime quest generator: rolls the objective item(s)/counts from the "
                   "request template (plus alternate items from categories where this shape has "
                   "them). Args are template-specific (item ids and category ids).")
        # keep the handler's shape suffix in the mnemonic (WithRandomCats / WithLiteralAlternates
        # / ChainedRandom / Backref… ) -- different shapes are DIFFERENT handlers doing different
        # things, so collapsing them all to "PopulateQuestKind<N>" made distinct ops indistinguishable
        # in the disassembly (e.g. op 509 random-cats vs op 510 literal-alternates both read "Kind2").
        _add(_op, "PopulateQuestKind%d%s" % (_n, _qk.group(2)), "quest", _d, [])
        continue
    # loot / random roll family: Roll*, LootRoll*, ShopRoll* — roll a value (usually an item
    # id) via the RNG and write it to the VM output for a following read.
    _stripped_for_roll = _strip_prefix(_tech)
    if _stripped_for_roll.startswith(("Roll", "LootRoll", "ShopRoll")):
        _add(_op, _stripped_for_roll, "item",
             _humanize(_tech) + ". Rolls a value via the RNG (usually a random item id, "
             "sometimes an integer or position) and writes the result to the VM output slot "
             "for a following read — used to generate reward / treasure / shop contents.", [])
        continue
    # NPC schedule/idle BEHAVIOR handlers (ops 738-762): these take an NPC AI-behavior state
    # block, NOT the script-VM (ctx, stack) — they are dispatched by the NPC AI tick from the
    # NPC's current schedule action-kind (0..24) and are NOT emitted by cutscene scripts. They
    # just occupy the tail of the shared g_sceneActionHandlerTable.
    if _tech.startswith("NpcAction") or _tech == "Npc_TickWanderBehavior":
        _km = re.search(r"Kind(\d+)", _tech)
        _kind = (" (schedule kind %s)" % _km.group(1)) if _km else ""
        _add(_op, _strip_prefix(_tech), "actor",
             _humanize(_tech).replace("Npc Action ", "").replace("Kind ", "kind ") + _kind +
             ". An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is "
             "NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the "
             "script VM context) and won't appear in rf3.mc. Listed for completeness because "
             "it shares the tail of the scene action-handler table.", [])
        continue
    # save-config settings-flag family: {Query,Set}SaveConfigBit<N>
    _scb = re.search(r"(Query|Set)SaveConfigBit(\d+)", _tech)
    if _scb:
        _is_q = _scb.group(1) == "Query"
        _bit = _scb.group(2)
        if _is_q:
            _add(_op, "QuerySaveConfigBit%s" % _bit, "query",
                 "Read save-config settings flag bit %s (g_saveConfigFlags) into the VM output."
                 % _bit, [])
        else:
            _add(_op, "SetSaveConfigBit%s" % _bit, "flag",
                 "Set save-config settings flag bit %s of g_saveConfigFlags." % _bit, [])
        continue
    # fallback: humanized technical name + keyword-inferred category
    _mnem = _strip_prefix(_tech) or ("op%d" % _op)
    _add(_op, _mnem, _infer_category(_tech), _humanize(_tech) + ".", [])


# ---- public helpers ---------------------------------------------------------------
def technical(op):
    return TECHNICAL.get(op, "op%d" % op)


def mnemonic(op):
    e = META.get(op)
    return e["m"] if e else ("op%d" % op)


def category(op):
    e = META.get(op)
    return e["c"] if e else "misc"


def describe(op):
    e = META.get(op)
    return e["d"] if e else _humanize(technical(op)) + "."


def arg_names(op):
    e = META.get(op)
    return list(e["a"]) if e else []


# Brief per-argument explanations, keyed by the (lower-cased) argument NAME. Arg names
# are reused across many opcodes, so one table explains most of them. Used by the
# Alt-hover tooltip in the cutscene editor.
ARG_HINTS = {
    "face frame": "portrait face/expression frame (0 = neutral, 4 = open-mouth surprise)",
    "emote/mood": "emote icon over the portrait: 186 blush, 187 teardrop, 188 sweat drop, 189 white "
                  "puff (angry), 190 '!', 191 '?', 192 '!?'; 0 = none; 0x1000000+n = a voice clip",
    "target": "target actor reference (0x0100_00xx handle); 0 = the current speaker",
    "em entry id": "em.bin Event Manager entry id (0..271; named in emdeb.bin)",
    "flag id": "GameFlags bit id -- ENGINE base-relative (flag_id + g_gameFlagsBuffer[0]), "
               "not an emflags/emdeb offset",
    "value": "the value to store (an id or a number; what it means depends on the slot's use)",
    "index": "slot index into the (engine-global) script-variable bank",
    "portrait slot": "which on-screen portrait slot to update",
    "portrait id": "portrait/face id to show",
    "face id": "portrait face/expression id",
    "speaker": "speaker slot (indexes g_gameGlobalsSlotTable; 0 = the player)",
    "speaker/line id": "packed speaker + dialogue-line token",
    "line id": "dialogue line id into rf3mc.<locale>",
    "sub": "sub-token / secondary index for the bubble",
    "param": "extra bubble parameter (PSB-emote capable)",
    "mode (0 sets the bit)": "toggle: arg == 0 sets the dialogue-state bit, else clears it",
    "item id": "item id (rf3ItemList index)",
    "sfx id": "sound-effect id",
    "bgm id": "background-music track id",
    "map id": "destination map id (rf4s_rooms.csv)",
    "npc id": "character / NPC id",
    "action id": "OpenMenu menu id (see WORLD_INTERACTION_ACTIONS: 1=Save, "
                 "2=Load, 3=MessageBoard, 11=Calendar, 12=Storage, 23=Fridge, 25=BackupSaveNow, "
                 "45=Bookshelf, 53=ShippingBin, 54=WeaponBox, 55=Closet, 56=FarmToolBox, "
                 "58=Forge_ShortSword, 71=Craft_Accessory)",
    "kind": "fade kind (16 = fade to black; other values: fade colour / direction)",
    "duration_ms": "fade length in milliseconds",
    "mode": "opcode-specific mode selector (see the action id list on the tooltip)",
    "mode (1/-1)": "1 = add/set, -1 = remove/clear",
    "shopkeeper npc": "NPC id (usually a tag3(N) constant) of the shopkeeper you're "
                      "talking to. Selects the day-off + shop-kind override. Vanilla ids: "
                      "6=Bado, 8=Dylas, 9=Arthur, 10=Porcoline, 11=Xiao Pai, 12=Lin Fa, "
                      "13=Amber, 14=Illuminata, 15=Doug, 16=Blossom, 17=Dolce, 18=Jones, "
                      "19=Nancy, 22=Son, 23=Daughter, 25=? -- other/anon NPCs fall into "
                      "the default (day 6 / kind 26) case",
    "shop id": "shop dispatch id (75-89 in vanilla) -- see WORLD_INTERACTION_ACTIONS. "
               "75=WeaponFarmTool, 76=Accessory, 77=ExcavatedEquipment, 78=Hospital, "
               "79=Flower, 80=FlowerExpanded, 81=General, 82=GeneralExpanded, 83=Ability, "
               "84=Magic, 85=Jewel, 86=SakuTuner, 87=Yue, 88=Restaurant, 89=FishMarket",
    "actor ctx": "actor / scene context reference (usually a `tag4(...)` constant holding an "
                 "actor slot pointer or a scene handle)",
    "duration (frames = arg0/100; 6000 ~= 1s)": "FadeScreenToClear / FadeScreen: animation "
                   "length. Effective frames = value / 100 (6000 -> 60 frames ~= 1s at 60fps; "
                   "0 or <100 -> immediate). NOT milliseconds.",
    "bgm id (or -1 = restore)": "BGM track id (-1 = clear scripted BGM and restore "
                                "contextual). Special id 16777332 gets extra volume-bias",
    "enable": "0 = disable / off, non-zero = enable / on",
    "target npc (0=player)": "NPC slot index for the receiver; 0 = give to the player character",
    "item id": "item id (rf3ItemList index); masked to 11 bits (0..2047)",
    "op kind (4=add, 5=sub, 6=set)": "4=add xp, 5=subtract xp, 6=set friendship points absolute",
    "xp/value": "friendship XP delta (op kind 4/5) or absolute FP value (op kind 6)",
    "kind9 slot": "var-array kind 9 write index (0..15)",
    "kind0 slot": "var-array kind 0 write index (0..15)",
    "event id (0=player birthday)": "calendar-event archive record id (0 falls back to the player's own birthday from GameFlags)",
    "sfx id": "sound effect id (rf3 audio bank index)",
}


def arg_hint(op, i):
    """Brief explanation of argument `i` of opcode `op` (by its name), or None."""
    names = arg_names(op)
    if 0 <= i < len(names):
        return ARG_HINTS.get(names[i].lower())
    return None


def arg_hint_by_name(name):
    """Brief explanation for a bare argument name (e.g. 'target'), or None."""
    return ARG_HINTS.get(name.lower()) if name else None


def prototype(op):
    """C-style signature string, e.g. 'SetSpeakerDylas(face frame, emote/mood, target)'.

    Each arg name is shortened to its leading token (the text before any ' (' qualifier)
    so the one-line signature stays readable even when the full per-arg label carries extra
    detail (e.g. 'fade target (sign: - = to black ...)' shows as just 'fade target'). The
    full labels are still used verbatim in the per-arg tooltip lines and the picker rows.
    """
    def _short(nm):
        s = nm.split(" (")[0].strip()
        return s or nm
    lead = [a["name"] for a in OPCODE_ARGS.get(op, ())]
    return "%s(%s)" % (mnemonic(op), ", ".join(lead + [_short(n) for n in arg_names(op)]))


_OP_BY_MNEMONIC = None

#: The one no-op authors see: `nop` assembles to it and the editor lists only it. Op 388 is a
#: shipped no-op that takes no arguments (4 bytes; the game uses it 4 times, and 381 the same way 9
#: times); op 693, the most used one (131x), always carries 1-2 arguments, so a bare `nop` cannot be
#: it. The other no-op slots (NO_OP_ALIASES) still disassemble, as nop_N, so banks round-trip
#: byte-exact.
NOP_OP = 388
NO_OP_ALIASES = (0, 76, 272, 381, 391, 491, 505, 526, 533, 550, 565, 583, 584, 585, 586,
                 608, 630, 636, 693)


def op_from_mnemonic(name):
    """Reverse lookup: opcode number for a curated mnemonic (case-insensitive), or None.

    Lets the editor accept an opcode by NAME instead of a raw number. Placeholder names
    ((unbound)/(unused)/invalid) are excluded; `nop` is NOP_OP. For aliased mnemonics (e.g. SetSpeakerMC
    on ops 16 & 17, or the 73 same-name pairs) it returns the LOWEST matching op, which is
    unambiguous because aliases share one handler.
    """
    global _OP_BY_MNEMONIC
    if _OP_BY_MNEMONIC is None:
        _skip = {"(unbound)", "(unused)", "nop", "invalid"}
        _OP_BY_MNEMONIC = {}
        for _o in range(763):
            _m = mnemonic(_o)
            if _m and _m not in _skip:
                _OP_BY_MNEMONIC.setdefault(_m.lower(), _o)   # keep the lowest op for aliases
        _OP_BY_MNEMONIC["nop"] = NOP_OP
    return _OP_BY_MNEMONIC.get((name or "").strip().lower())


def find_ops(query, limit=12):
    """Search opcodes by a case-insensitive substring of the mnemonic (or, if that finds
    nothing, the description). Returns [(op, mnemonic), ...] deduped to the lowest op per
    mnemonic. Powers op discovery / 'did you mean' suggestions when authoring by name."""
    q = (query or "").strip().lower()
    if not q:
        return []
    skip = {"(unbound)", "(unused)", "nop", "invalid"}
    seen, by_mnem = set(), []
    for _o in range(763):
        _m = mnemonic(_o)
        if _o == NOP_OP and q in _m.lower():
            seen.add(_m.lower())
            by_mnem.append((_o, _m))
        elif _m and _m not in skip and q in _m.lower() and _m.lower() not in seen:
            seen.add(_m.lower())
            by_mnem.append((_o, _m))
    if by_mnem:
        return by_mnem[:limit]
    # fall back to a description search when no name matched
    out = []
    for _o in range(763):
        _m = mnemonic(_o)
        if _m and _m not in skip and q in (describe(_o) or "").lower() and _m.lower() not in seen:
            seen.add(_m.lower())
            out.append((_o, _m))
            if len(out) >= limit:
                break
    return out


def category_label(op):
    return CATEGORIES.get(category(op), "Other")


def tooltip(op, arg_values=None):
    """Multi-line tooltip text for an action opcode.

    ``arg_values`` (optional) is a list of already-rendered argument values; when
    given, each is shown next to its name."""
    e = META.get(op)
    mn = mnemonic(op)
    lines = ["%s   [op %d - %s]" % (mn, op, category_label(op))]
    lines.append(describe(op))
    names = arg_names(op)
    vals = list(arg_values) if arg_values is not None else None
    n = max(len(names), len(vals) if vals is not None else 0)
    for i in range(n):
        nm = names[i] if i < len(names) else "arg%d" % i
        if vals is not None and i < len(vals):
            lines.append("  %d. %s = %s" % (i, nm, vals[i]))
        else:
            lines.append("  %d. %s" % (i, nm))
    tech = technical(op)
    if tech != mn and not tech.startswith("op"):
        lines.append("(%s)" % tech)
    return "\n".join(lines)


# ---- value-decoded display for enum-arg opcodes ------------------------------------
# QueryPlayerStatByCharCode switches on its 1st arg (an ASCII letter) to pick which player
# variable to read; for the skill case the 2nd arg is the skill id. IDA-verified from
# Script_VMOp_QueryPlayerStatByCharCode (RF4S.exe+0x20D4B0).
PLAYER_VAR_BY_CHARCODE = {
    100: "Gold", 102: "Level", 103: "Fodder",   # 102 level, 103 fodder in the barn bin (seen in game 2026-10-01)
    104: "Skill", 105: "Stone", 106: "Compost", 107: "MaxSkillLevel",
}
# Name tables that come from the game's text files (gamenames: the copy the game loads, else
# the toolkit's built-in list) are built on first use, so importing this module reads nothing.
def _lazy(build):
    from .gamenames import Lazy
    return Lazy(build)


def reload_game_names():
    """Re-read the game's name files (after the game folder or a text file changed)."""
    from . import gamenames
    gamenames.reload()


def _names(kind):
    from . import gamenames
    return gamenames.table(kind)


# 40-slot skill table (rf3TxtSkill_split2_1.eng); id -> name, matching skill_array indexing.
def skill_name(i):
    return _names("skills").get(i) or "skill#%d" % i


_STAT_QUERY_OPS = {_op for _op, _t in TECHNICAL.items() if "QueryPlayerStatByCharCode" in _t}

# Author-facing name + arg labels for the query op (overrides the humanized fallback).


# ---- OpenMenu dispatch table (op 375) -------------------------------------------
# id -> (short label shown in the picker, one-line description).
# Checked id by id against the exe on 2026-10-01: World_DispatchInteractionEvent
# (RF4S.exe+0x1F75B0) maps the id to a trigger; most triggers call Script_RunAction(n),
# and Script_DispatchAction (RF4S.exe+0x4CCF0) switches on n to build the screen:
#   n 1-8   rf4StorageTask with a container type (Inventory_GetContainerByTypeId,
#           RF4S.exe+0x6BE60; screen titles = rf3TxtMenuCommon lines 12-21)
#   n 9     rf4FieldMenu (notebook), n 10 QuestMenu, n 11-28 rf4NameEntryTask
#           (prompt per NameEntry_LoadDefaultByContext, RF4S.exe+0x3A180),
#   n 29/56 rf4CalendarTask, n 31 rf4ShopTask, n 32-55 CraftStationMenuTask.
# Labels name the screen the player sees; the cooking / forge / crafting labels are the
# choice lines the shipped scripts put in front of each id.
WORLD_INTERACTION_ACTIONS = {
    1:  ("Save",                    "The diary / save menu."),
    2:  ("Load",                    "Load menu (title-screen slot picker). WARNING: only safe "
                                    "from a dev-menu / title context -- loading mid-gameplay "
                                    "leaves NPC AI state stale and crashes."),
    3:  ("MessageBoard",            "The request notebook (QuestMenu), message-board mode."),
    4:  ("NameEntry_Hero",          "'Enter your name' for the main character, prefilled with the "
                                    "current name. The opening follows it with 90 (birthday)."),
    5:  ("NameEntry_Farm",          "'Enter the farm's name' (prefilled 'Selphia')."),
    6:  ("NameEntry_Field1",        "'Enter the field's name' for the first extra field (prefilled "
                                    "'Kardia'). Used by prince order 40."),
    7:  ("NameEntry_Field2",        "'Enter the field's name' for the second extra field (prefilled "
                                    "'Alvarna'). Used by prince order 40."),
    8:  ("NameEntry_Field3",        "'Enter the field's name' for the third extra field (prefilled "
                                    "'Sharance'). Used by prince order 40."),
    9:  ("NameEntry_Field4",        "'Enter the field's name' for the fourth extra field (prefilled "
                                    "'Norad'). Used by prince order 40."),
    10: ("ShippingHistory",         "The notebook (rf4FieldMenu) on the shipping records "
                                    "('Look at sale records.' at the shipping bin)."),
    11: ("Calendar",                "The calendar screen."),
    12: ("Storage",                 "The 'Storage' container screen (the storage trunk)."),
    14: ("Chemistry",               "Chemistry Set crafting ('Mix some medicine.')."),
    16: ("Cooking",                 "Cooking without a tool -- the Homemade recipes "
                                    "('Cook something simple.')."),
    17: ("Cook_FryingPan",          "Cooking with the frying pan."),
    18: ("Cook_Pot",                "Cooking with the pot."),
    19: ("Cook_Oven",               "Cooking with the oven."),
    20: ("Cook_Mixer",              "Cooking with the mixer."),
    21: ("Cook_Steamer",            "Cooking with the steamer."),
    22: ("Cook_Knife",              "Cooking with the knife."),
    23: ("Fridge",                  "The 'Fridge' container screen."),
    24: ("(nothing)",               "Opens nothing in RF4S (the trigger is an empty function). The "
                                    "developers' menu still lists it as the monster management "
                                    "screen."),
    25: ("BackupSaveNow",           "Writes a backup save immediately (rf3BackupSaveDataBuild); no screen."),
    26: ("BackupSaveNow",           "Same as 25."),
    27: ("(nothing)",               "Clears the pending id; no screen."),
    28: ("NameEntry_BarnA",         "'Enter the barn's name' for barn A (the {Barn0} template)."),
    29: ("NameEntry_BarnB",         "'Enter the barn's name' for barn B ({Barn1})."),
    30: ("NameEntry_BarnC",         "'Enter the barn's name' for barn C ({Barn2})."),
    31: ("NameEntry_BarnD",         "'Enter the barn's name' for barn D ({Barn3})."),
    32: ("NameEntry_BarnE",         "'Enter the barn's name' for barn E ({Barn4})."),
    33: ("NameEntry_BarnF",         "'Enter the barn's name' for barn F ({Barn5})."),
    34: ("NameEntry_BarnG",         "'Enter the barn's name' for barn G ({Barn6})."),
    35: ("NameEntry_BarnH",         "'Enter the barn's name' for barn H ({Barn7})."),
    36: ("NameEntry_BarnI",         "'Enter the barn's name' for barn I ({Barn8})."),
    37: ("NameEntry_BarnJ",         "'Enter the barn's name' for barn J ({Barn9})."),
    38: ("NameEntry_Child0",        "'Enter your child's name' for child slot 0. Fails silently "
                                    "when there is no child."),
    39: ("NameEntry_Child1",        "'Enter your child's name' for child slot 1."),
    40: ("NameEntry_Child2",        "'Enter your child's name' for child slot 2."),
    41: ("NameEntry_Child3",        "'Enter your child's name' for child slot 3."),
    42: ("NameEntry_Child4",        "'Enter your child's name' for child slot 4."),
    43: ("Posts",                   "The request notebook (QuestMenu), posts mode."),
    44: ("RequestNotebook(mode 3)", "The request notebook (QuestMenu) in a third mode; no shipped "
                                    "script uses it."),
    45: ("Bookshelf",               "The 'Bookshelf' container screen, with the Rune Ability page "
                                    "on the left instead of the backpack."),
    51: ("NameEntry_TamedMonster",  "'Enter the monster's name' for the monster just tamed (runs "
                                    "from the tame event)."),
    52: ("(nothing)",               "Zeroes a word in the game state; no screen."),
    53: ("ShippingBin",             "The 'Shipping Box' container screen. Afterwards the op sets "
                                    "packed flag 2594 if item 29 or 30 was shipped."),
    54: ("WeaponBox",               "The 'Weapon Box' container screen (the safe furniture: "
                                    "'It's my safe.')."),
    55: ("Closet",                  "The 'Closet' container screen (the wardrobe furniture)."),
    56: ("FarmToolBox",             "The 'Farm Tool Box' container screen (the toolbox furniture)."),
    57: ("NameEntry_FarmMonster",   "'Enter the monster's name' for the farm monster the player is "
                                    "talking to ('Change name.')."),
    58: ("Forge_ShortSword",        "Forge: short swords ('Short Sword.')."),
    59: ("Forge_LongSword",         "Forge: long swords ('Long Sword.')."),
    60: ("Forge_Spear",             "Forge: spears ('Spear.')."),
    61: ("Forge_AxeHammer",         "Forge: axes and hammers ('Axe or Hammer.')."),
    62: ("Forge_Axe",               "Forge, station kind 13 -- by the recipe-category order the "
                                    "'Axe' list; no shipped script uses it."),
    63: ("Forge_DualBlades",        "Forge: dual blades ('Dual Blades.')."),
    64: ("Forge_Fist",              "Forge: gloves ('Gloves.')."),
    65: ("Forge_Staff",             "Forge: staffs ('Staff.')."),
    66: ("Forge_FarmTool",          "Forge: farm tools ('Make a tool.')."),
    67: ("Craft_Armor",             "Crafting table: armor ('Make armor.')."),
    68: ("Craft_Shield",            "Crafting table: shields ('Make shields.')."),
    69: ("Craft_Headgear",          "Crafting table: headgear ('Make headgear.')."),
    70: ("Craft_Shoes",             "Crafting table: shoes ('Make shoes.')."),
    71: ("Craft_Accessory",         "Crafting table: accessories ('Make accessories.')."),
    72: ("Forge_UpgradeWeapon",     "Forge: upgrade a weapon ('Upgrade a weapon.')."),
    73: ("Craft_UpgradeArmor",      "Crafting table: upgrade armor ('Upgrade armor.')."),
    74: ("ShopBox",                 "The 'Shop Box' container screen (the player's shop)."),
    75: ("Shop_WeaponFarmTool",     "Weapon / Farm Tool shop (Bado). The stock tier follows the "
                                    "story progress."),
    76: ("Shop_Accessory",          "Accessory shop (Bado)."),
    77: ("Shop_ExcavatedEquipment", "Equipment shop -- 'Excavated Things' (Bado)."),
    78: ("Shop_HospitalMedicine",   "Hospital -- medicine counter (Jones, Nancy, Dolce)."),
    79: ("Shop_Flower",             "Flower shop, basic stock (Amber / Illuminata, 'Seeds & "
                                    "Nutrients, please.' before prince order 11 'Lumi's Flower "
                                    "Shop'). Shop lists 26/27 (27 -> 28 at prince rank 3+)."),
    80: ("Shop_FlowerExpanded",     "Flower shop after prince order 11: lists 26/27 plus 29 "
                                    "(30 at prince rank 3-4, 31 at rank 5)."),
    81: ("Shop_General",            "General store, basic stock (Doug / Blossom, 'Show me seeds & "
                                    "groceries.' before prince order 14 'Blossom's Groceries'). "
                                    "Shop lists 19/20 plus 21 (22 at prince rank 2+)."),
    82: ("Shop_GeneralExpanded",    "General store after prince order 14: lists 19/20, 21 or 22 "
                                    "and 23 (24 at prince rank 3-4, 25 at rank 5). Not furniture -- "
                                    "Blossom's furniture is the separate 'Show me furniture.' menu."),
    83: ("Shop_Ability",            "Ability shop ('Got any Rune Abilities?')."),
    84: ("Shop_Magic",              "Magic shop ('Can I see some Magic?')."),
    85: ("Shop_Jewel",              "Jewel shop ('Can you show me some gems?')."),
    86: ("Shop_SakuTuner",          "Saku's shop -- Tuner (Raven)."),
    87: ("Shop_Yue",                "Yue's shop (Arthur)."),
    88: ("Shop_Restaurant",         "Restaurant (Porcoline, Dylas)."),
    89: ("Shop_FishMarket",         "Fish market ('I'd like to see some fish.')."),
    90: ("BirthdayEntry",           "The 'Enter your birthday.' screen (the calendar in picker "
                                    "mode). The opening runs it right after 4."),
    200: ("InheritSave",            "The save-data inheritance screen: pick a save, then 'transfer "
                                    "items, levels, skill levels and monsters from the saved data?' "
                                    "(your current items are lost). Any id without its own case "
                                    "(13, 15, 46-50, 91+) opens it; the shipped script uses 200 for "
                                    "prince order 96."),
}

# op number for TriggerWorldInteractionAction (looked up once at import time)
_TRIGGER_WORLD_INTERACTION_OP = next(
    (_op for _op, _t in TECHNICAL.items()
     if _t == "Script_VMOp_TriggerWorldInteractionAction"),
    None,
)

# Shopkeeper NPC ids for op 376 arg 0. Derived from the Script_VMOp_BeginCalendarContextualInteraction
# switch (RF4S.exe+0x211C20) + PORTRAIT_SPEAKERS slot correspondence + observed corpus usage.
# Vanilla script never passes a LITERAL for this arg (always a tag3 constant), so the enum picker
# is mostly documentation -- but it also makes the tooltip and future-mod authoring easier.
SHOPKEEPER_NPCS = {
    0:  ("Anonymous",           "Fallback / non-shopkeeper NPC -> day 6 (Sat), kind 22"),
    6:  ("Bado",                "Weapon / Farm Tool / Accessory / Excavated Equipment / Forge -> day 0 (Sun)"),
    8:  ("Dylas",               "Restaurant server -> day 0 (Sun); kind 23 when GF_FLG_DIRUS_FRIENDLY set"),
    9:  ("Arthur",              "-> day 0 (Sun)"),
    10: ("Porcoline",           "Restaurant chef -> day 0 (Sun)"),
    11: ("Xiao Pai",            "Restaurant / inn -> day 6 (Sat)"),
    12: ("Lin Fa",              "Restaurant / inn -> day 6 (Sat)"),
    13: ("Amber",               "Flower shop -> day 5 (Fri); kind 25 when GameFlag 875 packed"),
    14: ("Illuminata",          "Flower shop -> day 5 (Fri)"),
    15: ("Doug",                "General store -> day 5 (Fri); kind 24 when Scene condition 0x2D true"),
    16: ("Blossom",             "General store -> day 5 (Fri)"),
    17: ("Dolce",               "-> day 1 (Mon)"),
    18: ("Jones",               "Hospital -> day 1 (Mon)"),
    19: ("Nancy",               "Hospital -> day 1 (Mon)"),
    22: ("Son",                 "Married-couple child -> day 6 (Sat) via kind 26 fallback"),
    23: ("Daughter",            "Married-couple child -> day 6 (Sat) via kind 26 fallback"),
    25: ("Guest25",             "-> day 6 (Sat), kind 21 override with sub-arg forced to 28"),
}

# Festival IDs from bank 292 @0x0840's `＊ｏBean Festival` dev menu (33 choices, one
# EVAL per branch reveals the exact id going into reg0 or reg2).
#
# reg0 (competitive festival "wins" -- 7 IDs, victory-flag toggle):
COMPETITIVE_FESTIVALS = {
    1: ("Bean Festival",         "Bean-toss competition (Feb)"),
    2: ("Eating Competition",    "Speed-eat contest"),
    3: ("De-Fluffing",           "Wooly de-fluffing competition"),
    4: ("Target Practice",       "Ranged/archery target contest"),
    5: ("Snowball Fight",        "Winter snowball competition"),
    6: ("Quiz Contest",          "Trivia quiz competition"),
    7: ("Buddy Contest",         "Pair/pet 'Pet' competition"),
}
# reg2 (calendar / 'eve' festival day-of-year events -- 25 IDs). This is the
# scheduling side: what happens ON that festival day. The 7 competitive
# festivals appear as ids 1..7 mirroring COMPETITIVE_FESTIVALS, then 8..25
# extend to the non-competitive seasonal + holiday events.
CALENDAR_FESTIVALS = {
    1:  ("Bean Toss",            "Eve/day of the bean-toss competition"),
    2:  ("Eating Contest",       "Eve/day of the eating contest"),
    3:  ("De-Fluffing",          "Eve/day of the de-fluffing contest"),
    4:  ("Target Shot",          "Eve/day of the target-shot contest"),
    5:  ("Snowball Fight",       "Eve/day of the snowball fight"),
    6:  ("Quiz",                 "Eve/day of the quiz contest"),
    7:  ("Pet",                  "Eve/day of the buddy/pet contest"),
    8:  ("Fishing Frenzy Contest",   "Fishing tournament (frenzy)"),
    9:  ("Big Catch Contest",        "Biggest-fish contest"),
    10: ("Squid Catch Contest",      "Squid-catch tournament"),
    11: ("Fish Variety Contest",     "Most fish species caught contest"),
    12: ("Spring Harvest",           "Spring-crop harvest festival"),
    13: ("Summer Harvest",           "Summer-crop harvest festival"),
    14: ("Autumn Harvest",           "Autumn-crop harvest festival"),
    15: ("Winter Harvest",           "Winter-crop harvest festival"),
    16: ("Cooking Contest",          "Best-dish cooking competition"),
    17: ("Handicraft Contest",       "Best-crafted-item competition"),
    18: ("New Year's",                "New Year's Day festival"),
    19: ("Beach Day",                 "Beach outing / summer swimming event"),
    # 20 unused in dev menu (skipped between 19 and 21)
    21: ("New Year's Eve",             "New Year's Eve celebration"),
    22: ("Firefly Festival",           "Summer firefly viewing"),
    23: ("Valentine",                  "Valentine's Day (Feb 14 in RF calendar)"),
    24: ("White Day",                  "White Day (chocolate returns)"),
    25: ("Christmas Eve",              "Christmas Eve"),
}

# Warp-charm item IDs from the ＊Yokmir Forest / ＊Selphia Plain / ... dev menu
# (bank 252 tail scene@0x21e pc@0x38a0). Each branch is `GivePlayerItem(<charm_id>, 1, 1)`,
# revealing which item id is the warp charm for which dungeon. Useful for adding
# custom warp items or for a debug 'teleport to X' mod.
WARP_CHARM_ITEMS = {
    362: "Yokmir Forest",       539: "Selphia Plain",
    329: "Water Ruins",         349: "Selphia Plain: West",
    430: "Obsidian Manor",      367: "Yokmir Cave",
    331: "Autumn Road",         476: "Delirium Lava Ruins",
    332: "Sercerezo Hill",      334: "Idra Cave",
    404: "Maya Road",           336: "Sechs Territory",
    330: "Floating Empire",     389: "Leon Karnak",
    374: "Rune Prana 1",        369: "Rune Prana 2",
    392: "Rune Prana 3",        395: "Rune Prana 4",
    377: "Rune Prana 5",        381: "Rune Prana 6",
    388: "Rune Prana Depths",
    348: "Sharance 1",          354: "Sharance 2",
    416: "Sharance 3",          357: "Sharance 4",
    368: "Sharance (Infinite)",
}


def warp_charm_target(item_id):
    """Dungeon name for a warp-charm item id, or None if it's not a warp charm."""
    return WARP_CHARM_ITEMS.get(item_id)


# ITEM-ID category ranges. From bank 252 tail44 pc@0x44da's `＊One-handed Sword`
# menu — each branch STOREs (reg1, reg2) = (start, end) of a contiguous item-id
# range and CALLs a shared "GivePlayerItem for i in [reg1, reg2)" loop. So the entire
# item-id space is partitioned by category, and the item ids in each range are
# usable-only-as-that-category. Half-open: [start, end). Verified 2026-07-07.
ITEM_CATEGORY_RANGES = {
    "OneHandedSword":  (328, 362),   # 34 items
    "TwoHandedSword":  (362, 396),   # 34 items
    "Spear":           (396, 429),   # 33 items
    "Hammer":          (429, 452),   # 23 items
    "Axe":             (452, 472),   # 20 items
    "Staff":           (472, 508),   # 36 items
    "TwinSwords":      (508, 539),   # 31 items
    "Fists":           (539, 559),   # 20 items
    "Tools":           (559, 589),   # 30 items -- farming tools
    "Shields":         (589, 607),   # 18 items
    "Accessories":     (607, 677),   # 70 items -- LARGEST category
    "Hats":            (677, 709),   # 32 items
    "Shoes":           (709, 731),   # 22 items
    "Armor":           (731, 750),   # 19 items
}


def item_category(item_id):
    """Category name for an item id (e.g. 'OneHandedSword'), or None if
    out-of-range. Verified against the vanilla debug 'give item by category'
    menu."""
    for name, (lo, hi) in ITEM_CATEGORY_RANGES.items():
        if lo <= item_id < hi:
            return name
    return None


# CONSUMABLE / CROP / MATERIAL item-id ranges. From bank 262 tail's per-cook-tool
# and per-material spawn menus (@0x091c, @0x11de, @0x1670). These narrow ranges
# hint at first-N-of-category being the "basic" variants (e.g. veggies 1-6 are
# the earliest crops; ores 818-823 are the low-tier metals).
CONSUMABLE_ITEM_RANGES = {
    "Vegetables":        (1, 48),      # crops -- rough end
    "Mushrooms":         (48, 55),     # 48-54
    "Fruits":            (55, 63),     # Strawberry, Apple, Grape, ...
    "Flowers":           (63, 132),    # Flowers start at 63; upper bound approx
    "CookingOthers":     (132, 134),   # Butter/Cheese-like misc
    "Condiments":        (304, 328),   # Sugar, Salt, ... up to end (OneHandedSword starts 328)
    "OreMaterials":      (818, 887),   # Iron/Bronze/Silver/Gold/Platinum/Rune-metal ores, etc.
}
COOKING_RECIPE_RANGES = {
    "BareHands":  (286, 304),          # cookable with no tool (aligns near Condiments)
    "Knife":      (134, 159),          # Sashimi-like
    "FryingPan":  (159, 211),          # Fried dishes (up to Pot start)
    "Pot":        (211, 239),          # Stews / soups (up to Oven start)
    "Oven":       (239, 258),          # Baked (up to Mixer start)
    "Mixer":      (258, 275),          # Blended (up to Steamer start)
    "Steamer":    (275, 286),          # Steamed
    "CookingOthers": (300, 304),       # Misc cooked
}

# Special "important items" (dev menu allows deleting these): key story items
IMPORTANT_ITEMS = {
    669:  "Important Item (669)",
    670:  "Important Item (670)",
    1024: "Important Item (1024)",
}


def consumable_category(item_id):
    """Category for a consumable/crop/material item id, or None."""
    for name, (lo, hi) in CONSUMABLE_ITEM_RANGES.items():
        if lo <= item_id < hi:
            return name
    return None


def cooking_recipe_category(item_id):
    """Cooking-tool category for a recipe item id, or None."""
    for name, (lo, hi) in COOKING_RECIPE_RANGES.items():
        if lo <= item_id < hi:
            return name
    return None


# NPC IDs (bank 4 tail44 pc@0x5788 Vishnal-story-arc menu confirmed these match
# the PORTRAIT_SPEAKERS slot numbers -- previously suspected but now definitive:
# each NPC branch fires `EVAL var:0x40C6 = <slot>` matching PORTRAIT_SPEAKERS).
# So var:0x40C6 is a GENERIC 'currently-focused NPC' variable, not
# monster-dex-specific; renamed accordingly.
#
# Also each NPC branch fires SetPlayerMale(gender), so this maps to
# which protagonist (Lest=1/Boy or Frey=0/Girl) can marry each NPC:
NPC_MARRIAGE_PARTNER_OF = {
    # NPC slot -> protagonist gender that can marry them (SetPlayerMale arg)
    1:  ("Vishnal",  "Frey"),     # slot 1 = Vishnal; marries Frey (F)
    2:  ("Clorica",  "Lest"),     # marries Lest (M)
    4:  ("Forte",    "Lest"),
    5:  ("Kiel",     "Frey"),
    7:  ("Margaret", "Lest"),
    8:  ("Dylas",    "Frey"),
    9:  ("Arthur",   "Frey"),
    11: ("Xiao Pai", "Lest"),
    13: ("Amber",    "Lest"),
    15: ("Doug",     "Frey"),
    17: ("Dolce",    "Lest"),
    20: ("Leon",     "Frey"),
}
# NPC SETTLEMENT SIDE-EVENT IDs (values of var:0x8099 for each NPC's settlement
# arc). Same source scene. These are contiguous ids 132..143, one per NPC.
NPC_SETTLEMENT_EVENT_IDS = {
    132: "Vishnal_Settlement",
    133: "Clorica_Settlement",
    134: "Forte_Settlement",
    135: "Kiel_Settlement",
    136: "Margaret_Settlement",
    137: "Dylas_Settlement",
    138: "Arthur_Settlement",
    139: "XiaoPai_Settlement",
    140: "Amber_Settlement",
    141: "Doug_Settlement",
    142: "Dolce_Settlement",
    143: "Leon_Settlement",
}


# NPC / player MOTION animation-id ranges. From bank 252 tail44 pc@0x6b04's
# `＊M_AMAZE〜M_FLOWER02` motion-sampler menu. Each EVAL-range is (reg0, reg1)
# = [start_anim, end_anim) for a run of consecutive anim ids the QA menu will
# cycle through. Also cross-checked against bank 308 tail's Motion Categories.
#
# The MOTION_TYPE_RANGES are anim ids for a specific CATEGORY (Basic/Attack/Daily);
# the WEAPON_ATTACK_ANIM_RANGES are per-weapon attack anim ids.
MOTION_TYPE_RANGES = {
    "Basic":            (1, 14),     # Basic Motion (13 anims)
    "Attack":           (14, 28),    # Attack Motion (14 anims)
    "Daily":            (28, 38),    # Daily Motion (~10 anims, dev menu increments reg1)
    "StandardTypesSweep":  (14, 35), # 'Watch All Standard Types'
    "FarmingTypesSweep":   (35, 57), # 'Watch All Farming Types'
}
WEAPON_ATTACK_ANIM_RANGES = {
    "Saber":         (57, 75),       # 18 anims
    "Broadsword":    (75, 93),       # 18 anims
    "Spear":         (93, 109),      # 16 anims
    "Staff":         (109, 120),     # 11 anims
    "Axe":           (120, 135),     # 15 anims
    "TwinBlades":    (135, 159),     # 24 anims
    "Fist":          (159, 187),     # 28 anims
}
# Named-motion-set entry points (M_XXX groups). Each dev-menu branch invokes
# a sequence of BeginPlayerScriptedTalkWithAnim(anim_id, 0) starting at these
# base anim ids -- the exact anim-id -> M_ name mapping isn't in the menu but
# the base anim id tells you where each M_ prefix group starts in the anim table.
NAMED_MOTION_ENTRY = {
    197: "M_AMAZE",     198: "M_FLOWER02",
    206: "M_JUMP",      207: "M_THINK",
    213: "M_ORDER",     214: "M_CLEAN",
    220: "M_YES",       221: "M_YAWN",
    227: "M_LOOK",      228: "M_ROLL",
    232: "M_SMILE_EZEL", 233: "M_DMG_DONW",
}


def motion_range_for_anim(anim_id):
    """Category name for an animation id, or None. Combines MOTION_TYPE_RANGES
    (Basic/Attack/Daily) and WEAPON_ATTACK_ANIM_RANGES (per-weapon)."""
    for name, (lo, hi) in list(MOTION_TYPE_RANGES.items()):
        if lo <= anim_id < hi:
            return name
    for name, (lo, hi) in WEAPON_ATTACK_ANIM_RANGES.items():
        if lo <= anim_id < hi:
            return f"{name}Attack"
    return NAMED_MOTION_ENTRY.get(anim_id)


# Story checkpoint IDs (var:0x8000 = the main-plot progression counter).
# From bank 292 tail44 scene@0x023c prompt@0x032a `＊Debug Start` menu -- each
# branch writes var:0x8000 to a specific value. These are the QA fast-forward
# points; every ScriptedBeat in the QA test menu also STOREs var:0x8000 to a
# specific number right before firing.
STORY_CHECKPOINTS = {
    # Debug-Start menu values (bank 292 tail44 pc@0x032a) -- 7 canonical fast-forwards
    0:   "Opening (post-OP done)",
    70:  "After Amber settlement arc",
    100: "After Dylas settlement arc",
    141: "After Dolce settlement arc",
    209: "After Leon settlement arc (also 'Everyone's Settlement')",
    431: "Beginning of Epilogue",
    511: "After All Clear",
    # Story-arc drill-down menus (bank 4 tail scene@0x5758 sub-menus at
    # @0x5f64/@0x5fd6/@0x6062/@0x60e2/@0x6186) -- fine-grained mid-arc checkpoints
    1:   "Opening",
    5:   "Looking into the Journal",
    10:  "Field Tutorial",
    39:  "After the field, in front of Ventuswill",
    # 40..96 = Vishnal/Amber castle+forest arc (Story arc @0x5fd6 + Dylas @0x6062)
    40:  "Castle Gates, Forte",
    41:  "Forest, in front of the entrance",
    42:  "Forest, In front of the gate",
    44:  "Forest, sudden butterflies",
    46:  "Forest, before the map battle",
    50:  "Forest, before the boss battle",
    52:  "Forest, Rematch with the boss battle",
    55:  "After the hospital, before reporting",
    59:  "Hospital, before Amber wakes up",
    60:  "Venti, right before the nightly talk",
    71:  "Cursed Voice, Mushroom Road",
    74:  "Ruins",
    76:  "Before Doug's Entrance at the Ruins",
    80:  "Solving the Ruins",
    82:  "Pressed both switches in the Ruins",
    85:  "Rematch with Raiden",
    88:  "Before Dylas Disappears from the Hospital",
    96:  "Before Dylas Wakes Up at the Hospital",
    # 100..130 = Pico/Mansion arc
    101: "Pico waits at the plaza",
    104: "Pico waits at the mansion",
    108: "Before Locked In at the Mansion Entrance",
    113: "Before the Ghost of the Mansion Hall",
    114: "Disappearing candle at the Mansion",
    115: "Pico at the Mansion Garden",
    116: "Pico at the Garden",
    118: "Before the monsters jump in",
    124: "Pico's 'Just a bit more'",
    126: "Pico before the Mansion Boss",
    130: "Rematch with Mansion Boss",
    # 141..170 = Chipsqueek / rune-sphere / Rafflesia arc
    142: "Before spotting Chipsqueek in the town",
    144: "Before spotting Chipsqueek at the castle",
    145: "Before spotting near the forest entrance",
    146: "Before spotting at the forest entrance",
    147: "Before spotting at the forest map 1",
    148: "Before falling off the forest cliff",
    149: "Before picking up the rune sphere",
    151: "Before spotting Chipsqueek at the castle 2",
    152: "Before spotting at the boss map",
    155: "Rematch with Dead Tree",
    156: "Outside of Ruins entrance",
    157: "Before the Ruins Chimera",
    158: "Rematch with Ruins Chimera",
    160: "Before setting the rune sphere",
    161: "After placement, before obtaining info",
    163: "Before spotting a large stump",
    164: "Before the Delirium entrance",
    165: "Before arriving to 2nd floor of Delirium",
    166: "Before battling Rafflesia",
    167: "Rematch with Rafflesia",
    169: "Before placing rune sphere at the Manor",
    # The later story-arc sub-menus of the same debug menu (tail bank 4, scene 0x0218:
    # @0x62d6 Forest of Beginnings, @0x6302/@0x6322 Dragon Space + plaza, @0x6366 Idra,
    # @0x63aa Autumn Road / Maya Road, @0x641e Imperial Territory, @0x64ae Floating Empire,
    # @0x654e Leon Karnak / memories) -- `rf4mod script dev-menus` lists them
    172: 'Before Venti and Doug at the Dragon Space',
    175: 'Before Bullet at the inn',
    176: 'Before warning about the Gate battle',
    177: 'Before the Gate battle',
    192: 'After the entrance of the Forest of Beginnings',
    204: 'Before the Sarcophagus battle',
    210: 'Before talking with Venti and the 4 memories',
    240: 'Before the Castle gate event',
    244: 'Before the fight at the plaza',
    252: 'After the battle, going to the Dragon Space',
    269: 'Hospital, before obtaining info from Doug',
    270: 'Before Idra Cave',
    271: 'Before B1 of Idra',
    272: 'Before the Idra boss',
    274: 'Rematch with the Idra boss',
    300: 'Before spotting Imperial soldier at Autumn Road',
    301: 'Before the bridge is destroyed',
    302: 'Bridge destroyed and talking with Arthur',
    304: 'Before the entrance to Maya Road',
    306: 'Before the explanation of the hole in Maya Road',
    308: 'before Wall Switch 2 at Maya Road',
    309: 'Before boss at Maya Road',
    320: 'Rematch with boss at Maya Road',
    330: 'Outside the bridge of the national border',
    332: 'Start of the Imperial Territory / Before battle against 3 Imperial soldiers / Rematch with 3 Imperial soldiers',
    333: 'Before Akuna battle at Imperial Territory',
    334: 'Rematch with Akuna at Imperial Territory',
    364: 'Before going to Floating Empire Castle with airship',
    368: 'Rematch of airship battle 1',
    369: 'Rematch of airship battle 2',
    370: 'Rematch of airship battle 3',
    372: 'Before battle with Ethelberd',
    390: 'Rematch with Ethelberd',
    398: 'Rematch after Enhanced State',
    442: 'Before Leon Karnak entrance',
    444: 'Before battle with Right and Left Statues',
    446: 'Before battle with Sarcophagus',
    448: 'Memory 1, before Map M11',
    450: 'Memory 2, before Map M25',
    452: 'Memory 3, before Map M35',
    454: 'Memory 4, before Map M48',
    456: 'Memory 5, before Map M64',
    458: 'Memory 5, before Map M83',
    460: 'Before Last Boss',
    464: 'Before setting Rune Sphere N39',
    468: 'Revive Venti, before Dragon Space',
}


def story_checkpoint_name(v):
    return STORY_CHECKPOINTS.get(v)


# Named game-state variables (EVAL var:0xNNNN) discovered from the QA menus.
# These aren't opcodes; they're the meanings of specific `var:` addresses used
# by the script's EVAL / conditional-branch machinery. Recorded here so a
# script editor can auto-annotate `var:0x8000 = 511` as `MAIN_STORY_CHECKPOINT
# = "After All Clear"` and so on. From bank 252 tail44 menus + bank 292.
NAMED_SCRIPT_VARS = {
    0x0033: "venti_down_flag_sub",       # Venti Down Limit ON=1 branch
    0x043B: "bado_shop_visited",         # set to 1 when Bado shop is first opened
    0x0478: "ventuswill_cool_talk_flag", # set to 1 during Venti's cool-talk scene
    0x0494: "credit_roll_special_char",  # Special Character Settings for Credit Roll ON
    0x03F8: "doug_hospitalized_limit",   # ON/OFF toggle
    0x03F9: "venti_down_limit",          # ON/OFF toggle (also STOREd with 0x33)
    0x1127: "pregnancy_phase",           # Pregnancy Reveal / Birth Event
    0x2131: "pregnancy_status_arg",      # Pregnancy Status branch
    0x5129: "pregnancy_day",             # Pregnancy day-counter
    0x20DC: "pregnancy_cleanup_flag",    # Cleared to 0 on reveal/birth
    0x40C6: "current_focused_npc",       # 'currently-focused NPC slot' -- SAME
                                         # numeric as PORTRAIT_SPEAKERS. Bank 4 tail
                                         # story-arc menu confirms values 1..20 match
                                         # NPC slots (1=Vishnal, 2=Clorica, 4=Forte,
                                         # 5=Kiel, 7=Margaret, 8=Dylas, 9=Arthur,
                                         # 11=Xiao Pai, 13=Amber, 15=Doug, 17=Dolce,
                                         # 20=Leon). Also used as
                                         # UnlockMonsterDexEntryAchievement's arg --
                                         # dev menu passes a monster id there too
    0x40FE: "child_gender",              # 22 = Male (Son), 23 = Female (Daughter)
                                         # -- SAME NUMERIC as portrait speaker slots
    0x0A20: "eliza_requirement_flag_0",  # Eliza's Requirement Success Flag (1 of 3)
    0x0A21: "eliza_requirement_flag_1",  # (2 of 3)
    0x0A22: "eliza_requirement_flag_2",  # (3 of 3)
    0x0B3D: "cooked_rainbow_trout_flag", # Cooked Rainbow Trout dishes before
    0x0B3E: "cooked_lamp_squid_flag",    # Cooked Lamp Squid dishes before
    0x0B3F: "cooked_blowfish_flag",      # Cooked Blowfish dishes before
    0x13DE: "backpack_expansion_level",  # Expand Backpack -> 3
    0x71C2: "generic_flag_change",       # from '＊Change Flag' dev branch
    0x6AF:  "quest_progress_partial",    # written near CommitMarriageToSpouseAndFireAchievements
    0x8000: "MAIN_STORY_CHECKPOINT",     # THE main plot progression counter --
                                         # see STORY_CHECKPOINTS + doc/21 R.S. IX
    0x8099: "current_side_event_id",     # 'Execute Side Event' -> 55
    0x80A2: "side_events_unlock_flag",   # 'Unlock Side Events' -> 0
    0x8103: "post_marriage_flow_flag",   # written by After All Clear branch
    0x8620: "current_date_event_id",     # written by bank 21 NPC-debug ＊Date branch
                                         # (EVAL var:0x8620 = 500 = 'Date active')
                                         # High 0x8XXX range like 0x8000 = MAIN_STORY_CHECKPOINT
                                         # -- looks like a peer 'date sub-plot state' tracker
}


def named_var(addr):
    """Return the human name for a script `var:0xNNNN` address, or None."""
    return NAMED_SCRIPT_VARS.get(addr)


def install_named_var_resolver(script_module, container=None, chain_after=None):
    """Install a packed-variable resolver on `script_module` (i.e.
    `rf4s_modkit.script`) that renders `var:0xNN` references as their
    NAMED_SCRIPT_VARS name when known. Falls back to `chain_after` (another
    resolver) if provided; otherwise disasm_expr's default `var:0x%X` form.

    Pass `container` to unpack `enc` via `container.unpack_var(enc)` so the
    resolver looks up by the true bit_offset. When `container` is None (fine
    for most quick jobs), we look up by the raw `enc` value -- this happens
    to work because vanilla NAMED_SCRIPT_VARS keys are already the bit-offset
    values with width=1 (which encodes as bit_offset for the common shift
    values in rf3.mc).
    """
    def resolve(enc):
        # First try the raw-enc key (matches the current default display).
        nm = NAMED_SCRIPT_VARS.get(enc)
        if nm:
            return nm
        # If a container is supplied, also try the true bit_offset.
        if container is not None:
            bit_off, _w, _s = container.unpack_var(enc)
            nm = NAMED_SCRIPT_VARS.get(bit_off)
            if nm:
                return nm
        if chain_after is not None:
            return chain_after(enc)
        return None
    script_module.set_packed_var_resolver(resolve)
    return resolve


# Staff-credits driver modes (op 617, IDA-verified against bank 252 @0x462a dev menu).
STAFF_SPAWN_MODES = {
    0: ("Fade (long)",          "Long fade overlay (dev menu 'Staff Fade')."),
    1: ("Fade (short)",         "Short fade overlay (dev menu 'Staff Fade (Short)')."),
    2: ("Credits (bottom)",     "Scrolling staff-credits screen anchored to the bottom "
                                "screen (dev menu 'Staff Credits Screen (Bottom)')."),
    3: ("Credits (top)",        "Scrolling staff-credits screen anchored to the top "
                                "screen (dev menu 'Staff Credits Screen (Top)')."),
}

# Weather codes (op 446 SetWeather arg 0). IDA-verified from Weather_PromoteRollToWeatherCode
# + the debug-menu strings ("Weather Count:Typhoon/Rooney[%02d]") + the boot-time weather-archive
# map. These are the FINAL weather_code values written to g_weather->weather_code.
WEATHER_CODES = {
    -1: ("(restore previous)", "Restore the weather that was active before the last scripted "
                               "SetWeather (reads the saved previous-weather byte)."),
    0:  ("Sunny",       "Clear / fine weather — the default. Passing 0 also CLEARS any scripted "
                        "weather (resets the transition flag)."),
    1:  ("Rain",        "Rain. Becomes Snow (2) in winter; forced on inside rain-event rooms."),
    2:  ("Snow",        "Snow — the winter form of Rain."),
    3:  ("Typhoon",     "Typhoon / storm. Becomes Blizzard (4) in winter."),
    4:  ("Blizzard",    "Blizzard — the winter form of Typhoon."),
    5:  ("Cloudy",      "Cloudy (XSEED internal name 'Clowdy'; applies a custom sky-tint shader)."),
    6:  ("Rooney",      "A special snow-based weather event (archive 1898), normally reachable "
                        "only via scripted events — useful for cutscenes."),
    7:  ("Rain (weak)", "Light rain. Becomes weak Snow (8) in winter."),
    8:  ("Snow (weak)", "Light snow — the winter form of weak rain."),
}

# Screen-shake / jitter kinds (op 197 ShakeCamera arg 0). IDA-verified from the case dispatch in
# PlayerEffect_TickJitterByKind (kind 1-6 = internal cases 0-5); the value is ALSO a priority --
# a running shake only escalates to a higher kind. kind 0 stops/resets the shake.
SHAKE_KINDS = {
    0: ("Stop",              "Stop / reset any active screen shake."),
    1: ("Light jitter",      "Gentle 12-step positional jitter (smallest amplitude)."),
    2: ("Medium jitter",     "12-step signed jitter (bidirectional, larger amplitude)."),
    3: ("Short sharp jitter","Quick 4-step signed jitter -- a brief snap (impacts/hits)."),
    4: ("Long jitter",       "22-step signed jitter -- a longer sustained shake."),
    5: ("Heavy jitter",      "22-step jitter at 2x amplitude -- the strongest table shake "
                             "(quakes/explosions)."),
    6: ("Rotational rumble", "Angular sin-cos shake with decay -- a smooth rotating rumble that "
                             "eases out."),
}

# Table of (op, arg_index) -> enum-value dict. Extend when more opcodes get enum
# metadata; the editor picks up new entries automatically via enum_arg_choices().
ENUM_ARG_VALUES = {}
if _TRIGGER_WORLD_INTERACTION_OP is not None:
    ENUM_ARG_VALUES[(_TRIGGER_WORLD_INTERACTION_OP, 0)] = WORLD_INTERACTION_ACTIONS
# BeginShopkeeperInteraction (op 376) dispatches into the same World action-id
# space as op 375, but its arg 1 is specifically a SHOP dispatch id: all 192 vanilla
# call sites pass ids 75-89 (the Shop_* actions), and passing a non-shop action
# (Save/Load/NameEntry/...) would not open a shop. So the picker is scoped to just
# the shop subrange rather than the full 83-action table, which would mislead. Arg 0
# (shopkeeper NPC) gets its own small enum of the switch cases.
# the shopkeepers' names come from the game (a mod may rename them); the notes stay ours
ENUM_ARG_VALUES[(376, 0)] = _lazy(lambda: {
    _k: (((_names("characters").get(_k) if _k else None) or _l), _d)
    for _k, (_l, _d) in SHOPKEEPER_NPCS.items()})
ENUM_ARG_VALUES[(376, 1)] = {_k: _v for _k, _v in WORLD_INTERACTION_ACTIONS.items()
                             if 75 <= _k <= 89}
ENUM_ARG_VALUES[(617, 0)] = STAFF_SPAWN_MODES
ENUM_ARG_VALUES[(446, 0)] = WEATHER_CODES         # SetWeather weather code
ENUM_ARG_VALUES[(197, 0)] = SHAKE_KINDS            # ShakeCamera jitter kind (1-6, 0=stop)

# Character ids (0-26 named; 0 = the player). This is the NPC record-array index used by the
# many "char id (0=player, 1-47=NPC)" opcode args. Names are the game's rf3TxtNpc archive
# (index == char_id). Ids 27-40 are generic 'Traveler', 41-47 'Soldier', 48+ = event/monster
# actors -- type the raw id for those (they stay numeric).
def _char_name(i):
    nm = _names("characters").get(i)
    if i == 0:
        return "Lest/Frey" if nm in (None, "Lest") else nm     # the player (the save's gender)
    return nm


CHAR_IDS = _lazy(lambda: {
    _i: (_char_name(_i), ("The player character (char id 0)." if _i == 0
                          else "Character '%s' (char id %d)." % (_char_name(_i), _i)))
    for _i in range(27) if _char_name(_i)})
# Ops whose selected arg is a plain char-id selector in the 0-47 NPC space (0=player). Excludes
# ops with overloaded char args (338 0=spouse, 486 0=scene-actor/22=spouse, child ops 24-47).
_CHAR_ID_ARG_OPS = [(110, 0), (121, 0), (122, 0), (209, 0), (339, 0), (440, 0),
                    (475, 0), (479, 0), (661, 0), (663, 0), (664, 0), (690, 0)]
for _cop, _cai in _CHAR_ID_ARG_OPS:
    ENUM_ARG_VALUES[(_cop, _cai)] = CHAR_IDS

# Auto-extend the character decoder to EVERY plain char-id / npc-id arg (~150 actor/npc ops) so
# the disassembly shows names throughout ("SlidePortraitToX(19=Nancy,...)", "SkipNpcDailyGreeting(8=Dylas)").
# Uses CHAR_IDS (0=player Lest/Frey) normally, or the no-0 variant where the label says 0 means
# something else (all/current/count/input/-1). SKIPS: child ops (24-47 = the player's children, a
# different id table), monster args (48+ species space), event-key, spouse-default, and variadic /
# index args -- decoding those with the villager roster would be WRONG.
_CHAR_IDS_NPC = _lazy(lambda: {_k: _v for _k, _v in CHAR_IDS.items() if _k != 0})
for _cop2, _cmeta in META.items():
    for _cai2, _clbl in enumerate(_cmeta["a"]):
        if (_cop2, _cai2) in ENUM_ARG_VALUES:
            continue
        _cl = _clbl.lower()
        if "char id" not in _cl and _cl != "npc id":
            continue
        if any(_x in _cl for _x in ("child", "monster", "event", "spouse", "index",
                                    "variadic", "ids", "…")):
            continue
        if any(_z in _cl for _z in ("0=all", "0=current", "0=count", "0=input", "-1=")):
            ENUM_ARG_VALUES[(_cop2, _cai2)] = _CHAR_IDS_NPC
        else:
            ENUM_ARG_VALUES[(_cop2, _cai2)] = CHAR_IDS

# ---- FULL character roster with resolved field models (event-spawn ops) --------------------
# The event-actor spawn ops (153/154/155) and registry cleanup (156) take char ids from the FULL
# 0..391 rf3NpcParam space (cutscene cast like 331 Captain / 324 Barrel / 235 Ventuswill), so the
# 0-26 villager picker the auto-extend loop wires is far too small AND the id decides the MODEL.
# Engine resolution (Actor_RecomputeAllStats, RF4S.exe+0xAD440, IDA-verified 2026-08-18):
#   model_toc = rf3NpcParam[+272] + (12584 if 48 <= rf3NpcParam[+256] <= 253 else 933)
# where 933 = the rom:/chr block and 12584 = the rom:/mons block of the engine's baked filename
# TOC (RF4S.exe .rdata +0x57AD30, 18179 x 256B UTF-16). refdata/char_models.json is
# generated from exactly that data (names from char_names.json); loaded here so the disassembly
# and picker show "331=Captain [NPC_TRAVELER_M2]" instead of a bare number.
def _load_char_models():
    import json as _json
    import pathlib as _pathlib
    try:
        from .refdata import refdata_path as _rp
        _p = _rp("char_models.json")
        _d = _json.loads(_p.read_text(encoding="utf-8"))
        return {int(_k): _v for _k, _v in _d.items() if not _k.startswith("_")}
    except Exception:
        return {}


def _event_char_ids():
    """Every rf3NpcParam row (392; names from the game's rf3TxtNpc, index == char id), with
    its field model where it has one."""
    models = _load_char_models()
    names = {k: v for k, v in _names("characters").items() if k < 392}   # rf3NpcParam rows
    out = {}
    for ci in sorted(set(models) | set(names)):
        cm = models.get(ci, {})
        nm = (_char_name(ci) if ci == 0 else names.get(ci)) or cm.get("name") or ("char#%d" % ci)
        mdl = cm.get("model")
        if mdl:
            lbl = "%s [%s]" % (nm, mdl)
            dsc = ("Character '%s' (char id %d). Field model %s/%s (rf3NpcParam+272 = %d)."
                   % (nm, ci, cm.get("kind", "chr"), mdl, cm.get("model_index", -1)))
        else:
            # no model: spawned it is an invisible actor. 269/270 'Search' are the cutscene
            # MARKERS -- EventSpawnNpc 269 is the most-spawned char (314 uses): a point that
            # FaceEventActor / move ops then target by its event key
            lbl = "%s (no model)" % nm
            dsc = ("Character '%s' (char id %d). No field model (rf3NpcParam+272 = -1): it spawns "
                   "invisible, as a marker other actors face or walk to by its event key."
                   % (nm, ci))
        out[ci] = (lbl, dsc)
    return out


EVENT_CHAR_IDS = _lazy(_event_char_ids)
# Spawn ops 153/154/155 arg0 + registry cleanup 156 arg0 address the full roster (overrides the
# villager-only dict the auto-extend loop assigned from the "char id" label).
for _eco in ((153, 0), (154, 0), (155, 0), (156, 0)):
    ENUM_ARG_VALUES[_eco] = EVENT_CHAR_IDS


def _map_entity_types():
    """SpawnMapEntity (op 157) arg0: the map object type ids, named like the map editor names
    a .rf4m MOBJ (the op builds the same record)."""
    from . import mobj_types
    out = {}
    for tid in range(1024):
        nm = mobj_types.mobj_display_name(tid)
        if nm:
            out[tid] = (nm, "Map object type %d: %s." % (tid, mobj_types.mobj_label(tid)))
    return out


ENUM_ARG_VALUES[(157, 0)] = _lazy(_map_entity_types)

# op 10 SetSpeakerVoice: arg0 = a name-plate id in the character-name archive (the full list,
# up to ~1000 -- the soldiers / customers / '???' plates sit above the 392 rf3NpcParam rows),
# arg1 = the text-blip class (Script_VMOp_SetSpeakerVoice, RF4S.exe+0x20A240)
_NAME_PLATES = _lazy(lambda: {_k: (_v, "Name plate '%s' (name archive entry %d)." % (_v, _k))
                              for _k, _v in _names("characters").items()})
ENUM_ARG_VALUES[(10, 0)] = _NAME_PLATES
TEXT_BLIPS = {
    0: ("male blip", "SE_WORDS_M.wav (sfx 16785916): the male blip (soldiers, travellers, Ethelwill)."),
    1: ("female blip", "SE_WORDS_F.ogg (sfx 16785917): the female blip ('???', Trupin, Eliza, Frey)."),
    2: ("monster blip", "SE_WORDS_O.wav (sfx 16785918): the monster / animal blip (Buffamoo, Fiergaenger)."),
    3: ("dragon blip", "SE_WORDS_D.wav (sfx 16785975): the dragon blip (Ventuswill's dragon form, Ancient Bone)."),
    4: ("player's blip", "Any value >= 4: the player's own blip -- male for Lest, female for Frey."),
}
ENUM_ARG_VALUES[(10, 1)] = TEXT_BLIPS

# op 437 IsItemInCategoryList arg1 is LABELLED "npc (char id)", so the auto-extend loop wired CHAR_IDS to
# it -- but the corpus proves token position 1 always holds a present-CATEGORY ref (0x8100+cat,
# observed 0x8101..0x8114 = categories 1-20 of gift archive 14850), NEVER a char id. The handler
# (Script_VMOp_QueryItemInNpcOfferListArchive14850) reads the real npc_id indirectly from the
# shared arg stack (argbuf[cursor-5]), not this bytecode token. A villager picker here never
# decodes and its dropdown would let an author write a wrong value, so drop it (leave it raw). The
# label/semantics (npc vs category, front-vs-back arg mapping) are left unresolved -- only the
# demonstrably-wrong picker is removed.
ENUM_ARG_VALUES.pop((437, 1), None)

# Town-development / Prince-Points effect ids (ApplyPrinceOrder 643, GetPrinceOrderState 644, GetPrinceOrderCost
# 647 -- all take effect_id at arg0). Shop unlocks (0x0A-0x17) + crafting licenses (0x18-0x1C) are
# user-confirmed from live PP-menu play; home upgrades (0x1F-0x26) are code-confirmed by the
# GF_REG_STORAGE_*_LV register names in Effects_GetCostForCurrency. Other effect ids (statbuffs,
# marriage flags, gold, weather) exist but stay numeric.
EFFECT_IDS = {
    0x0A: ("Blossom's Furniture", "Unlock Blossom's Furniture shop."),
    0x0B: ("Lumi's Flower Shop",  "Unlock Lumi's Flower Shop."),
    0x0C: ("Cooking Bread tier",  "Advance the 'Cooking Bread' unlock tier (750 PP, then 1500 PP)."),
    0x0D: ("Furniture Shop",      "Unlock the Furniture Shop (1000 PP)."),
    0x0E: ("Blossom's Groceries", "Unlock Blossom's Groceries (500 PP)."),
    0x0F: ("Bado's Accessories",  "Unlock Bado's Accessories (500 PP)."),
    0x10: ("Bado's Bargain Sale", "Unlock Bado's Bargain Sale (2000 PP)."),
    0x11: ("Clothing Shop",       "Unlock the Clothing Shop (800 PP)."),
    0x12: ("Fish Market",         "Unlock the Fish Market (2000 PP)."),
    0x13: ("Jewelry Shop",        "Unlock the Jewelry Shop (2000 PP)."),
    0x14: ("Magic Shop",          "Unlock the Magic Shop (2500 PP)."),
    0x15: ("Ability Shop",        "Unlock the Ability Shop (2500 PP)."),
    0x16: ("Business License",    "Unlock the Business License (1000 PP)."),
    0x17: ("Nationalize Baths",   "Nationalize the bathhouse (35000 PP)."),
    0x18: ("Forging License",     "Grant the Forging crafting license."),
    0x19: ("Chemistry License",   "Grant the Chemistry crafting license."),
    0x1A: ("Crafting License",    "Grant the Crafting license."),
    0x1B: ("EZ Cooking License",  "Grant the EZ Cooking license."),
    0x1C: ("Pro Cooking License", "Grant the Pro Cooking license."),
    0x1D: ("Effect-applied flag", "Set (ApplyPrinceOrder) or read (GetPrinceOrderState) a save-persisted "
                                  "effect-applied bit chosen by the sub-index (arg1): "
                                  "Effects_DispatchById case 29 does g_effectAppliedBits word2 |= "
                                  "1<<sub-index, Effects_QueryById reads that bit. A general "
                                  "scriptable/persistent flag (sub-index is 0 in every shipped "
                                  "scene), distinct from the prince-point shop/upgrade unlocks."),
    0x1F: ("Rucksack upgrade",    "Backpack / rucksack capacity upgrade (tier)."),
    0x20: ("Fridge upgrade",      "Fridge capacity upgrade (tier)."),
    0x21: ("Storage upgrade",     "Storage capacity upgrade (tier)."),
    0x22: ("Bookshelf upgrade",   "Bookshelf capacity upgrade (tier)."),
    0x23: ("Weapon Rack upgrade", "Weapon rack capacity upgrade (tier)."),
    0x24: ("Farm Tool Box upgrade","Farm tool box capacity upgrade (tier)."),
    0x25: ("Closet upgrade",      "Closet capacity upgrade (tier)."),
    0x26: ("Shipping Box upgrade","Shipping box capacity upgrade (tier)."),
}
for _eop in (643, 644, 647):
    ENUM_ARG_VALUES[(_eop, 0)] = EFFECT_IDS

# Companion slot selector (arg0 of the companion-choreography ops). Verified from op496
# MoveCompanion: slot 0 = companion 1 only, 1 = companion 2 only, 2 = both (the handler
# special-cases slot==2 to iterate slots 0..1). Not wired to op504 (uses -1=player) or
# 481/482 (only 0/1, no 'both').
COMPANION_SLOTS = {
    0: ("Companion 1", "The first companion (partner slot 1) only."),
    1: ("Companion 2", "The second companion (partner slot 2) only."),
    2: ("Both",        "Both companions (applies the action to slots 0 and 1)."),
}
for _cs in (494, 495, 496, 497, 498, 499, 500, 501, 502, 503):
    ENUM_ARG_VALUES[(_cs, 0)] = COMPANION_SLOTS

# Item-id -> name value-decoder, from the game's item-name archive (rf3TxtItem; the built-in
# list without a game folder). Auto-wired to every opcode arg whose label is an item-id selector,
# so the editor shows item names and value-decodes them ("GivePlayerItem(258=Pineapple Juice)").
# ~33 item args across the give/take/ship/query ops.
if True:
    # Empty description: the label IS the item name and the id is already shown in the picker row,
    # so a desc would just repeat both -- keep the 1108-entry dropdown clean ("258 - Pineapple Juice").
    ITEM_IDS = _lazy(lambda: {_i: (_nm, "") for _i, _nm in _names("items").items()})
    for _iop, _imeta in META.items():
        for _iai, _ilbl in enumerate(_imeta["a"]):
            _l = _ilbl.lower()
            if (_l == "item id" or _l.startswith("item id")
                    or _l in ("seed item id", "weapon item id")) and (_iop, _iai) not in ENUM_ARG_VALUES:
                ENUM_ARG_VALUES[(_iop, _iai)] = ITEM_IDS
    # ShowRewardPopup (op457) lists up to 4 reward ITEM ids; its labels are item0..item3, which
    # don't match the 'item id' auto-wire above. Corpus-verified item ids (e.g. 646=Dew Pendant),
    # so wire all four slots explicitly.
    for _rp_i in range(4):
        if (457, _rp_i) not in ENUM_ARG_VALUES:
            ENUM_ARG_VALUES[(457, _rp_i)] = ITEM_IDS

# Skill ids (0-37 named; 38/39 are unused 'Dummy' slots). Built from skill_name(). Wired to the
# skill-leveling ops. (op416 QueryPlayerVariable's skill arg is already value-decoded by the
# dedicated stat-query render path, so it is left alone.)
SKILL_IDS = _lazy(lambda: {_s: (skill_name(_s), "Player skill '%s' (skill %d)." % (skill_name(_s), _s))
                           for _s in range(38)})
ENUM_ARG_VALUES[(679, 0)] = SKILL_IDS      # IncrementPlayerSkillLevel
ENUM_ARG_VALUES[(701, 0)] = SKILL_IDS      # SetPlayerSkillXp

# NPC outfit variants (op287 SetNpcOutfit arg1 — the label documents the 0-3 mapping).
OUTFITS = {
    0: ("Default",  "The NPC's default/normal outfit."),
    1: ("Pajamas",  "Pajamas / sleepwear."),
    2: ("Swimsuit", "Swimsuit (record+52 bit 0x20); 4 selects it too."),
    3: ("Variant 3", "Outfit variant 3, applied without the record bits (not kept across loads)."),
}
ENUM_ARG_VALUES[(287, 1)] = OUTFITS
# op330/331 SetActorOutfitDirect (aliases) call the SAME Actor_ApplyNpcOutfitVariant(actor, variant)
# as op287, so arg1 is the same 0-3 outfit-variant space -- verified by decompile. (Was earlier
# left unwired as a 'raw unverified variant'; now confirmed.)
ENUM_ARG_VALUES[(330, 1)] = OUTFITS
ENUM_ARG_VALUES[(331, 1)] = OUTFITS

# Player-variable selector (op416 QueryPlayerVariable arg0 = an ASCII char-code). Built from
# PLAYER_VAR_BY_CHARCODE so it stays in sync. (render_action already value-decodes this op via the
# dedicated stat-query path; this just adds the dropdown so authors can pick 'Gold' etc.)
PLAYER_VARS = {_pc: (PLAYER_VAR_BY_CHARCODE[_pc],
                     "Player variable '%s' (char-code %d = '%s')."
                     % (PLAYER_VAR_BY_CHARCODE[_pc], _pc, chr(_pc)))
               for _pc in PLAYER_VAR_BY_CHARCODE}
ENUM_ARG_VALUES[(416, 0)] = PLAYER_VARS

# Dialogue box style (op93 SetDialogueBoxStyle arg0). The byte is
# stored as the portrait VARIANT (task+160 -> portrait sprite 15851+variant), the same variant
# space as the live-verified canonical face frames -- so 0-5 reuse FACE_FRAMES names; 6/7 are
# unnamed extra frames (stay raw).
# (verified 2026-09-25: it is the message-box style, see op 93's description; the old face
# names were wrong)
BOX_STYLES = {0: ("normal box", "The normal message box."),
              1: ("shout", "Jagged box; it shakes and the screen flashes."),
              2: ("thought", "Cloud box with a bubble-trail tail; it floats for about a second."),
              3: ("trembling", "Wavy box; it shakes sideways."),
              4: ("tail only", "No box, just the speech tail.")}
ENUM_ARG_VALUES[(93, 0)] = BOX_STYLES

# An NPC's date state (npc record +55 & 7): op 281 SetNpcDateState writes it, op 280 and
# em.bin's DATE_STATE query read it -- the lifecycle is in op 281's description.
DATE_STATES = {0: ("no date", "No date with this NPC."),
               1: ("date promised", "They accepted an invitation: the date is tomorrow."),
               2: ("date today", "The date is today (1 becomes 2 at the daily rollover). Still 2 at "
                                 "18:00 / 22:00 or the next rollover = stood up."),
               3: ("on the date", "The date has started: they are with you. It ends when they leave "
                                  "your party."),
               4: ("date went well", "Setting it awards friendship; it ends when they leave your party."),
               5: ("turned you down", "They declined today's invitation; cleared at the next rollover.")}
ENUM_ARG_VALUES[(281, 1)] = DATE_STATES

# Skill sub-arg of QueryPlayerVariable (op416 arg1 = the skill id, used when arg0 selects 'Skill').
# render_action already value-decodes it via the stat-query path; this just adds the dropdown.
ENUM_ARG_VALUES[(416, 1)] = SKILL_IDS

# Map name decoder (map id -> the game's rf3TxtMapName row; placeholder rows left out).
ROOM_IDS = _lazy(lambda: {_r: (_rn, "") for _r, _rn in _names("maps").items()
                          if not _rn.startswith("BLANK")})
ENUM_ARG_VALUES[(291, 1)] = ROOM_IDS


def enum_arg_choices(op, arg_index):
    """List of (int_value, short_label, description) for an enum-value argument.

    Returns [] for args that aren't a known enum. When the return value is
    non-empty, the editor is expected to present a picker instead of a bare
    number field. Values are sorted."""
    tbl = ENUM_ARG_VALUES.get((op, arg_index))
    if not tbl:
        return []
    return [(v, tbl[v][0], tbl[v][1]) for v in sorted(tbl)]


def enum_arg_label(op, arg_index, value):
    """Short label for an enum-value arg (e.g. 'Trigger_SaveMenu'), or None."""
    tbl = ENUM_ARG_VALUES.get((op, arg_index))
    if not tbl or value not in tbl:
        return None
    return tbl[value][0]


def enum_arg_description(op, arg_index, value):
    """Long description for an enum-value arg, or None."""
    tbl = ENUM_ARG_VALUES.get((op, arg_index))
    if not tbl or value not in tbl:
        return None
    return tbl[value][1]


def _lit_int(s):
    return s if isinstance(s, int) else int(str(s).strip(), 0)


def render_action(op, arg_strs):
    """Value-decoded 'Mnemonic(decoded, ...)' display for enum-arg opcodes, or None to fall
    back to the default name(args) rendering. `arg_strs` = the already-VALUE-rendered
    positional args (arg_repr output), not raw operand offsets."""
    if op in _STAT_QUERY_OPS:
        try:
            code = _lit_int(arg_strs[0])
        except (ValueError, IndexError, TypeError):
            return None                          # non-literal (expression) arg -> default
        if code == 104 or code <= 39:            # skill-based ('h', or a bare skill index)
            if code != 104:
                return "%s(Skill, %s)" % (mnemonic(op), skill_name(code))
            try:
                return "%s(Skill, %s)" % (mnemonic(op), skill_name(_lit_int(arg_strs[1])))
            except (ValueError, TypeError):      # a register / expression: show it as written
                return "%s(Skill, %s)" % (mnemonic(op), arg_strs[1])
            except IndexError:
                return "%s(Skill, ?)" % mnemonic(op)
        return "%s(%s)" % (mnemonic(op), PLAYER_VAR_BY_CHARCODE.get(code, "code%d" % code))
    # Portrait / SetSpeaker ops (16..75): resolve face-frame + emote-id numerics to canonical
    # mood names (the character and side come from the opcode: op = 16 + 2*character + side). So
    # `SetSpeaker(Vishnal, Right, 1, 189)` (op 19) renders as `SetSpeaker(Vishnal, Right, angry, angry)`.
    if 16 <= op <= 75:
        decorated = []
        for i, raw in enumerate(arg_strs):
            try:
                v = _lit_int(raw)
            except (ValueError, TypeError):
                decorated.append(raw)
                continue
            if i == 0:                            # face: the speaker's own portrait table
                name = None
                try:
                    from . import portraits as _pt
                    slot = (op - 16) >> 1
                    name = _pt.label(slot, v) if _pt.has_portrait(slot) else None
                except ImportError:
                    pass
                name = name or face_frame_name(v)
                decorated.append(name if name else str(v))
            elif i == 1:                          # emote / mood
                if v == 0:
                    decorated.append("0")         # 0 = no emote; leave numeric
                else:
                    name = portrait_emote_name(v)
                    decorated.append(name if name else str(v))
            else:                                 # target actor ref
                decorated.append(raw)
        return "%s(%s)" % (mnemonic(op), ", ".join(opcode_arg_labels(op) + decorated))
    # Auto-annotate any op that has an enum registry entry: OpenMenu(3=MessageBoard),
    # ShowStaffCredits(2=Credits (bottom)), etc. Falls back to the default rendering
    # if the argument is a non-literal expression or the value isn't in the enum.
    enum_hits = [(i, ENUM_ARG_VALUES[(op, i)]) for i in range(len(arg_strs))
                 if (op, i) in ENUM_ARG_VALUES]
    if enum_hits:
        decorated = list(arg_strs)
        changed = False
        for i, tbl in enum_hits:
            try:
                v = _lit_int(arg_strs[i])
            except (ValueError, TypeError):
                continue
            entry = tbl.get(v)
            if entry and v in VALUE_NAMES.get((op, i), ()):
                decorated[i] = entry[0]              # a source name: the listing writes it too
                changed = True
            elif entry:
                decorated[i] = "%s=%s" % (arg_strs[i], entry[0])
                changed = True
        if changed:
            return "%s(%s)" % (mnemonic(op), ", ".join(decorated))
    return None


def control_tooltip(mnem):
    """Tooltip text for a control opcode (keyed by the mnemonic Script emits)."""
    info = CONTROL.get(mnem)
    if not info:
        return mnem
    cat, desc = info
    return "%s   [control - %s]\n%s" % (mnem, CATEGORIES.get(cat, "control"), desc)

# ---- 2026-09-01 full opcode audit (8-agent IDB verification sweep) ----------------
# Every bound opcode was re-checked against its IDB handler (decompile + function
# comment) and the shipped rf3.mc corpus (arg-count histograms + in-context reads).
# These entries override earlier metadata. Applied AFTER the generated fallbacks on purpose -
# explicit verified knowledge wins.
_AUDIT_2026_09_01 = {
    3: ('WaitReset', 'flow',
        "End the current quest-reaction beat and wait: signals the scene controller idle (sceneCtx+872->child[+24][+116] = 1, the same write EndDialogue does), advances the quest-reaction dispatch state (Quest_OnReactionDispatched_AdvanceState), then - if the script task is in run-state 4 - writes arg0 into the task's wait field (+120, state 4->2), i.e. the same duration mechanism as Wait. Same units as Wait (200 = 1 frame); retail passes durations like 1 (minimal yield) or 6000 (30 frames). 267 retail uses, always 1 arg.",
        ['duration (units; 200 = 1 frame)']),
    94: ('SetBoxNormal', 'dialogue',
        "Dialogue box style 0: the normal box. Ops 94-97 = styles 0-3, the style is the opcode (op - 94); op 93 takes it as an argument. " + 'It sets the MESSAGE-BOX STYLE, not a face (verified 2026-09-25: Dialogue_SetSpeakerEmoteAndRetargetPortrait RF4S.exe+0x234E20 stores it at dialogue task +160; Dialogue_RetargetPortraitAndBubble +0x2380B0 then shows window art talk_win<n> (archive 15851+n) and tail talk_hige<n> (15846+n); Dialogue_SetTimingState +0x238350 adds the effect). 0 = normal box, 1 = shout (jagged box; everything shakes for 10 frames and the screen flashes), 2 = thought (cloud box with a bubble-trail tail; the box floats for ~1 s -- it does not delay the line), 3 = trembling (wavy box; a 10-frame sideways shake), 4 = tail only (no box). 5-7 would read unrelated textures. Lasts until changed or the dialogue box closes. The tail points at the side of the last speaker cue (an even SetSpeaker op = left, odd = right) and only shows while a portrait is up on that side for a named character: narration and SetSpeakerVoice name plates get no tail (DialogueBox_TickStateMachine +0x235BF0).',
        []),
    95: ('SetBoxShout', 'dialogue',
        "Dialogue box style 1: shout -- a jagged box that shakes, with a screen flash. Ops 94-97 = styles 0-3 (op - 94); op 93 takes the style as an argument. " + 'It sets the MESSAGE-BOX STYLE, not a face (verified 2026-09-25: Dialogue_SetSpeakerEmoteAndRetargetPortrait RF4S.exe+0x234E20 stores it at dialogue task +160; Dialogue_RetargetPortraitAndBubble +0x2380B0 then shows window art talk_win<n> (archive 15851+n) and tail talk_hige<n> (15846+n); Dialogue_SetTimingState +0x238350 adds the effect). 0 = normal box, 1 = shout (jagged box; everything shakes for 10 frames and the screen flashes), 2 = thought (cloud box with a bubble-trail tail; the box floats for ~1 s -- it does not delay the line), 3 = trembling (wavy box; a 10-frame sideways shake), 4 = tail only (no box). 5-7 would read unrelated textures. Lasts until changed or the dialogue box closes. The tail points at the side of the last speaker cue (an even SetSpeaker op = left, odd = right) and only shows while a portrait is up on that side for a named character: narration and SetSpeakerVoice name plates get no tail (DialogueBox_TickStateMachine +0x235BF0).',
        []),
    96: ('SetBoxThought', 'dialogue',
        "Dialogue box style 2: thought -- a cloud box with a bubble-trail tail pointing at the speaker; the box floats for about a second. Ops 94-97 = styles 0-3 (op - 94); op 93 takes the style as an argument. " + 'It sets the MESSAGE-BOX STYLE, not a face (verified 2026-09-25: Dialogue_SetSpeakerEmoteAndRetargetPortrait RF4S.exe+0x234E20 stores it at dialogue task +160; Dialogue_RetargetPortraitAndBubble +0x2380B0 then shows window art talk_win<n> (archive 15851+n) and tail talk_hige<n> (15846+n); Dialogue_SetTimingState +0x238350 adds the effect). 0 = normal box, 1 = shout (jagged box; everything shakes for 10 frames and the screen flashes), 2 = thought (cloud box with a bubble-trail tail; the box floats for ~1 s -- it does not delay the line), 3 = trembling (wavy box; a 10-frame sideways shake), 4 = tail only (no box). 5-7 would read unrelated textures. Lasts until changed or the dialogue box closes. The tail points at the side of the last speaker cue (an even SetSpeaker op = left, odd = right) and only shows while a portrait is up on that side for a named character: narration and SetSpeakerVoice name plates get no tail (DialogueBox_TickStateMachine +0x235BF0).',
        []),
    97: ('SetBoxTrembling', 'dialogue',
        "Dialogue box style 3: trembling -- a wavy box that shakes sideways. Ops 94-97 = styles 0-3 (op - 94); op 93 takes the style as an argument. " + 'It sets the MESSAGE-BOX STYLE, not a face (verified 2026-09-25: Dialogue_SetSpeakerEmoteAndRetargetPortrait RF4S.exe+0x234E20 stores it at dialogue task +160; Dialogue_RetargetPortraitAndBubble +0x2380B0 then shows window art talk_win<n> (archive 15851+n) and tail talk_hige<n> (15846+n); Dialogue_SetTimingState +0x238350 adds the effect). 0 = normal box, 1 = shout (jagged box; everything shakes for 10 frames and the screen flashes), 2 = thought (cloud box with a bubble-trail tail; the box floats for ~1 s -- it does not delay the line), 3 = trembling (wavy box; a 10-frame sideways shake), 4 = tail only (no box). 5-7 would read unrelated textures. Lasts until changed or the dialogue box closes. The tail points at the side of the last speaker cue (an even SetSpeaker op = left, odd = right) and only shows while a portrait is up on that side for a named character: narration and SetSpeakerVoice name plates get no tail (DialogueBox_TickStateMachine +0x235BF0).',
        []),
    105: ('QueryCalendarEventStub', 'query',
        'Always writes 0 to the VM output — the intended calendar-event lookup is stubbed on the PC port (for arg >= 0x30 the search over g_calendarEventMng runs but its result is discarded). arg0 = event id (consumed by the arg decoder). Treat as returning 0.',
        ['event id (consumed; result discarded)']),
    115: ('MoveActorToTile_LockAI', 'actor',
        "Walk an actor to an ABSOLUTE tile position, then LOCK its AI (npc+568 |= 0x10) so nothing interrupts the staged pose — used when actors slide into cutscene positions and must hold. Args 1/2 are absolute tiles, not offsets: the move command stores x<<12 / y<<12 RAW with no world-position anchor added, on both the NPC and player/scene paths (ops 115-118 are the absolute family; 123-128 are the relative one). args: actor (0 = player), x, y (tiles), facing degrees (x181 -> u16 rotation), speed, jump flag (non-zero = jump/run, 1.2x speed multiplier).",
        ['actor (char id, 0=player)', 'x (tiles, absolute)', 'y (tiles, absolute)', 'facing (degrees)', 'speed', 'jump (0/1)']),
    131: ('QueryActorBeyondRange', 'query',
        "1 while the actor is FARTHER than [range] tiles from its target marker (the player checks a global target position; an NPC checks its own move target); 0 once within range. arg0 = actor (char id, 0 = player), arg1 = range in tiles. Wait-until-arrived predicate. (Handler is named 'InRange' but returns 1 when far.)",
        ['actor (char id, 0=player)', 'range (tiles)']),
    154: ('EventSpawnNpcVariant', 'actor',
        "Spawn an event/cutscene NPC that carries a pose/scene VARIANT index — always claims a NEW registry slot (unlike op 153 which updates in place). arg0 = char id (which character/model; ids 254-266 are filtered = no-op), arg1 = event key (the scene-local handle later ops address), arg2/arg3 = X/Y tiles, arg4 = facing degrees (x181 -> u16), arg5 = variant index (stored as index-1 in the entry's high dword; 0 -> 0). Entry WORD5 is hardwired to 0 by the engine — there is NO reserved 7th argument. Use for staged NPCs with an alternate pose/outfit variant.",
        ['char id (model)', 'event key (scene-local handle)', 'x (tiles)', 'y (tiles)', 'facing (degrees)', 'variant index']),
    157: ('SpawnMapEntity', 'effect',
        "Spawn a map entity, dispatched by TYPE ID to the right spawner — the central script-side object-placement op (handler ScriptVMOp_SpawnMapEntityByTypeIdDispatchTable). arg0 = entity type id: <20 → special trigger (treasure/quest item, Map_HandleSpecialTriggerEntity), 20-195 → placed game object 'pg_mobj' (Actor_AllocTask 65 → MapObj_SetupActorByTypeId), 196-335 → interactive object (door/stove/lift, Map_SpawnInteractiveObject), 336+ → decoration/scenery (MapDecoration_Spawn). arg1/arg2 = position, arg3 = facing (passed as DEGREES, handler multiplies by 182 = 65536/360 → u16 angle), arg4 = sub-param (handler multiplies by 40). args5-9 = up to 5 optional EXTRA placement params copied into the entity's setup struct; their meaning is ENTITY-TYPE-SPECIFIC (flags, linked ids, size, etc.). Dynamic prop/decor placement from a scene.",
        ['entity type id', 'param 1 (x/pos)', 'param 2 (y/pos)', 'facing (degrees)', 'sub-param (x40)', 'extra 5 (type-specific)', 'extra 6 (type-specific)', 'flag 7 (0/1, type-specific)', 'flag 8 (0/1, type-specific)', 'extra 9 (type-specific)', 'extra 10 (type-specific)']),
    177: ('EventActorEnterIdle', 'actor',
        'Return a spawned event actor to its idle state, loading the default idle animation for its entity type. arg0 = event key. Use to reset an actor after a scripted anim/pose.',
        ['event key', '(unused — handler reads only 1 arg; shipped scripts pass 2)']),
    194: ('FocusCameraOnPlayer', 'screen',
        "Snap/commit the camera target onto the player (Camera_CommitTargetAndClampToBounds + distance-vector recompute, sets camera flag 0x40000) and BLOCK the scene for 3 frames while it settles. The engine reads NO arguments, but every shipped statement passes one (e.g. FocusCameraOnPlayer(400) in the corpus) — a vestigial ease-speed the RF4S handler ignores. Handy to 'return to the hero' between cutscene shots.",
        ['(ignored — engine reads no args)']),
    201: ('SetCameraSettleMode', 'screen',
        "Enable/disable the camera's SETTLE (soft-landing) mode — bit 0x40 of the camera state flags. When set, once the camera is within ~12 frames' worth of travel of its target its velocity decays 0.8125x per frame down to a 0.125 floor, giving a decelerating arrival instead of a constant-velocity stop. Effective on scripted pans (the follow camera rewrites its speed every frame, overwriting the decay). arg0 non-zero sets, 0 clears. Resolved 2026-08-25 via Widget_TickTransformEaseTowardTargets bit-0x40 arm.",
        ['settle on (0/1)']),
    203: ('SetCameraMapBounds', 'actor',
        "Recompute and re-apply the camera's per-map clamp bounds and zoom for the current map — NOT a player rotation. The handler calls Camera_SetBoundsForMap(active input-context/map id, flag), passing 0xFFFF while input is suppressed; that callee sets the script/follow camera's centre clamp from the map's tile dims and re-applies the small-map zoom. arg: 0 = write the camera distance directly onto the player's camera rig (flag=1 path); non-zero = apply via Camera_SetDistanceAndZoomFactor (flag=0 path). Used after scripted camera moves/zooms to restore the normal map camera.",
        ['mode (0=direct distance write, else standard zoom apply)']),
    204: ('SleepInBed', 'flow',
        "Run the go-to-bed / sleep-to-next-day sequence. arg0 != 0 (retail always 1): the full blocking cinematic FSM - bed anim + voice line, spouse/child walk to the bedside, fade to black, Player_SleepInBed (save snapshot + Day_OnAdvance day rollover), position restore, fade back in, morning BGM/weather; pressing the skip button fast-forwards the fades. arg0 == 0: calls Player_SleepInBed immediately with no cinematic. Dev menu 'Sleep' passes [1].",
        ['cinematic (1=full sequence, 0=instant day advance)']),
    233: ('SkipNpcDailyGreeting', 'actor',
        'Hide an NPC — make it invisible/despawned and set its hidden state bit. arg0 = npc (char id). Removes the NPC from the scene; pair with a schedule refresh or SetNpcVisibleFlag to bring it back.',
        ['npc (char id <48)', '(unused — handler reads only 1 arg; corpus passes 2)']),
    238: ('QueryQuestNpcsAvailable', 'quest',
        "Read 1 iff a primary NPC and all listed NPCs are available (not busy/sleeping schedule codes 13/25, not already mid-event, not inaccessible) AND each listed NPC is within a max distance of the primary — the quest-event group gate. arg0 = max distance, arg1 = primary npc (char id, <48), arg2+ = the other npc ids (their count is implied by the arg count — there is no explicit count arg). Writes 1/0 to reg0. Like op 240 but also requires the NPCs aren't already mid-event.",
        ['max distance', 'primary npc', 'other npc …']),
    240: ('QueryNpcGroupPresentNearby', 'query',
        "Read 1 into reg0 iff a group of NPCs are all present and available (actor state != 13/25, not busy/inaccessible) and each within arg0 distance of the primary. arg0 = max distance, arg1 = primary npc (char id), remaining args = the other npc char ids -- there is NO count argument: the handler derives the group size from the statement's own arg count. The dominant 2-arg form (distance, npc) degenerates to a single-NPC 'present & available' check (self-distance 0). 5-arg form = primary + 3 others.",
        ['max distance', 'primary npc (char id)', 'other npc …']),
    273: ('QueryNpcPresent', 'query',
        "Read whether a villager is 'present' — record bit 0x400000 (bit 22 of record+52, present-in-town) — into the VM output. arg0 = villager id, valid only for 1-23 (the handler requires id < 24; other ids yield 0). arg0 = 0 instead returns the COUNT of villagers (1-23) currently present.",
        ['npc (villager id <24; 0 = count all present)']),
    280: ('QueryNpcDateState', 'query',
        "Read an NPC's DATE STATE (npc record +55 & 7) into reg0 -- NOT a facing direction: 0 no date, 1 a date is promised for tomorrow, 2 the date is today, 3 on the date, 4 the date went well, 5 turned you down today (6/7 unused). arg0 = npc (char id); yields 0 if the NPC can't be resolved. Same read as Npc_GetDateState, which backs em.bin's DATE_STATE query (124) and the SUBEV_ENABLE_* gates (a sub-event may start at 0 or 5, i.e. with no date pending). Set by op 281 SetNpcDateState. " + _DATE_LIFE,
        ['npc (char id)']),
    285: ('SetSceneReadyFlag', 'flow',
        "Set a scene-state control bit (scene state +72 bit 0x1) when arg0 is 0 — a low-level 'wait / ready' marker the scene loop checks. arg0 = mode (0 sets it).",
        ['mode (0 = set flag)', '(ignored by handler)']),
    290: ('PostFamilyMilestones', 'actor',
        "Write the packed marriage/family-status game-flag (packed id 4391 -> value 2) and run the family birthday/anniversary milestone check for today: compares the current date to the spouse's and children's birthdays and the wedding anniversary, setting the matching family-milestone game-flags. These go through GameFlags_WritePacked_OrAchievement (packed game-flags), NOT Steam achievements. No args. Used in anniversary/birthday cutscenes.",
        []),
    293: ('ResetNpcDailySchedule', 'actor',
        "Put an NPC back on a daily-schedule state. arg0 = npc (char id), arg1 = state. Two distinct paths: arg1 != -1 -> Npc_ResetDailyScheduleAndAi(npc, state) (resets schedule AND AI) and returns WITHOUT touching the scene reservation; arg1 == -1 -> recompute today's state (record +17, or Schedule_GetNpcStateForToday when the computed bit +228&1 is clear), apply via Npc_ApplyScheduleState, and clear this scene's placed-actor/reservation bit (ctx+352 bit npc). Heavier than op 296; use at scene end to hand an NPC back to normal life.",
        ['npc (char id)', 'state (-1 = auto)']),
    302: ('SetNpcActionDelay', 'actor',
        "Make an NPC wait before its next scheduled AI action: writes a jittered countdown into the NPC's schedule-wait timer (record +212). Value = uniform [0.75*arg1, 1.125*arg1) via the shared MMIX RNG; if 3/4*arg1 <= 0 nothing is written. NpcSchedule_Tick decrements it once per tick and performs the next schedule action when it hits 0; starting a move/interaction clears it. Does NOT touch friendship (2026-08 analysis). arg0 = npc (char id), arg1 = base wait (ticks).",
        ['npc (char id)', 'base wait (ticks, jittered 0.75x-1.125x)']),
    305: ('GetSeason', 'time',
        'Read the current calendar SEASON index into the VM output — NOT the hour. The handler reads cal_inner+16, and the verified calendar layout (from the SetTime handler and Calendar_NormalizeTimeCarry) is [+0 sec, +4 minute, +8 hour, +12 day, +16 season, +20 year]: the real hour lives at +8. Season is 0-3 (Spring..Winter). No args.',
        []),
    308: ('GetDateSnapshot', 'time',
        "Read a full calendar snapshot into 5 VM outputs: reg0 = minute, reg1 = hour, reg2 = day, reg3 = month/week, reg4 = season (ctx+64..+80, from g_calendarTask.data_64[104]). No args. Used by dialogue scripts to gate lines by time ('is it night?', 'is it spring?').",
        []),
    318: ('SetFlag', 'flag',
        "Set GameFlags zone-2 bit 4096 + 1007 + id (only sets, never clears). Every shipped call (150) passes a character id as actor(..), so this is the 'birthday gift given' bit of that NPC -- the same bit NpcAi_OnReceivedThrownItem sets when the player gives a gift on the NPC's birthday, and the one Calendar_IsEventActive tests for birthday rows (verified 2026-09-23).",
        ['npc (char id) -- sets the birthday-gift-given bit 1007 + id']),
    326: ('ModifyLumber', 'item',
        "Modify the player's lumber. The operation is taken from arg0's TOKEN KIND (the handler reads the kind slot at idx-2; arg0's value is ignored): kind 4 = add (cap 50000), 5 = subtract (clamp 0), 6 = set (stricter 9999 cap). arg1 = amount. Corpus always passes 2 args; bank 6's building-cost path runs it between ModifyPlayerResource calls to deduct lumber, so 'Add' was misleading — it also subtracts and sets.",
        ['mode arg (op from token kind: 4=add, 5=sub, 6=set; value unused)', 'amount']),
    358: ('GetVar7', 'query',
        "Read global script-variable bank 7 at [index] into reg0 (g_scriptVarArrayKind7_52u32, a 52-entry u32 array). Identical shape to GetVar0/GetVar3 — the handler is a plain kind-7 var-array read with nothing portrait-specific in it; the old 'GetPortrait' name asserted semantics the code doesn't show. Only 16 corpus uses, all in bank 60 (the order/dev-menu bank).",
        ['index']),
    387: ('PlaySfxWithNpcRemap', 'audio',
        'Play a sound/voice by id, applying the per-NPC variant remap (calls Sfx_PlayByIdWithNpcVariantRemap): the remap picks a per-character voice/footstep variant when the same base sfx id is shared across characters (char-variant +5 remap windows; id 0 stops all menu audio; routes by id range to Sfx_PlayById or Player_PlayVoiceLine_VariantRemapped). Same callee the SetSpeaker* ops use for args >= 0x1F0 — which is why those args are voice ids. Companion op 385 plays a raw id without remapping.',
        ['sfx / voice id']),
    393: ('FreezePlayer', 'actor',
        'Lock or release player input (scripted freeze). INVERTED sense: arg0 == 0 FREEZES the player (sets control_flags bit 4, scene-node word bit 1, and the input-disabled bit 0x20000000 on actor_inner); arg0 != 0 releases all three. Shipped scenes open with FreezePlayer(0) and close with FreezePlayer(1).',
        ['release (0=freeze, nonzero=unfreeze)']),
    419: ('QueryBackpackHasFreeSlot', 'query',
        'Write 1 to the VM output if the backpack has any free slot, else 0 — a BOOLEAN, not a slot index. Walks the first 60 backpack slots looking for an empty/placeholder entry (slot kind < 0x800 or item id 0); if all are full it falls back to checking the special equip-extras slot (g_itemDatabase.ptr_00[+24]). No args. Used before placing an item.',
        []),
    493: ('GetNpcFacingMode', 'query',
        "Read the CURRENT scene NPC's scripted-facing mode bits (low 2 bits of the facing-mode word at scene_npc+304 -> +450) into the VM output. Takes NO arguments — it always targets the scene's own NPC record (sceneCtx+32), writing 0 if there is none. Counterpart of the mode setter (op 492 family).",
        []),
    559: ('StartFestivalContest', 'flow',
        "Start a festival contest mini-event: spawns the SceneEvent lifecycle task (SceneEvent_TickLifecycleStateMachine) and BLOCKS the VM (ctx+116 |= 0x10000) until the contest ends. arg0 = contest subtype -> task+4: 1=ONI, 2=EAT (eating contest), 3=MOKO, 4=MATO (target shooting), 5=YUKI, 6=QUIZ, 7=PET. Backs up the packed festival-status register (REG_FES_STATUS) into the task, restored when the contest completes. The old 'return-to-town prompt' reading was wrong.",
        ['contest (1=oni,2=eat,3=moko,4=mato,5=yuki,6=quiz,7=pet)']),
    578: ('SpawnEventMonsters', 'effect',
        'Spawn and initialise the monster-roster participants for the current scene event (e.g. a monster contest / event where farm monsters take part). Takes no arguments.',
        []),
    606: ('RollThreeFlowerItemsAvoidDup', 'item',
        'Roll a 3-flower gift choice: writes item 63 (fixed first option) plus two distinct random flower/plant items to the THREE VM outputs reg0/reg1/reg2 (ctx+64/+68/+72). Candidates are item ids 63-70 and 84-109 that pass the shop filter (up to 40 collected); the two rolled picks avoid id 63 and each other (retry-capped, falling back to 65/67), using the global MMIX PRNG. No args. Used by the flower-choice gift dialogue.',
        []),
    613: ('CalcChoicePrescroll', 'dialogue',
        "Pick the row the NEXT choice menu opens on (the default highlight). arg0 = a row index, stored in the GLOBAL g_choiceDialogPrescrollCount (not a VM register); when the menu builds its rows it moves the cursor down that many times (wrapping past the last row) and then zeroes it. The handler means to subtract the HIDDEN options below arg0 (clear bits of mask dword 0), but it only counts the options the current prompt has already queued (scene +243), which is 0 whenever a script can run this op -- so in practice the value is arg0 unchanged, i.e. a VISIBLE-row index; subtract hidden options yourself. Shipped use (8x): the menu reopens on the option picked last time (arg = a register). Call right before PROMPT_CHOICE. IDA-verified 2026-09-24 (Script_VMOp_CalcChoiceDialogPrescrollFromVisibleMask, ChoiceDialog_TickStateMachine state 3).",
        ['option index']),
    656: ('SetMapScrollSpeedX', 'screen',
        "Set the map's X-axis tile UV-SCROLL velocity target — NOT a fade alpha (IDB corrected 2026-08-08: work_buffer[254] is scroll velocity). arg0 = speed x10000 (e.g. -200 -> -0.02/frame; drives the scrolling-cloud sky on the airship deck and couples to the propeller flipbook rate), arg1 = snap flag (1 = jump current to target, 0 = ease toward it at 0.002-0.05/frame). Non-zero speed also enables repeat-wrap on layer-0 tiles. The next slot (op 657) is the Y channel.",
        ['scroll speed X (x10000)', 'snap (0/1)']),
    657: ('SetMapScrollSpeedY', 'screen',
        "Set the target Y-axis scroll speed of the map's tile UV scrolling (the auto-scrolling texture layer): target = value/10000, stored in the map task's work buffer (float slots 257=target, 259=prev; eased toward the target by MapTask_Tick, consumed by the tile-scroll/time-tint renderer). arg1 = snap flag: non-zero jumps the current value (slot 255) straight to the target, 0 eases. Y twin of op 656 (X axis). NOT a fade op — the old 'map fade channel 1' reading was wrong. Unused in the shipped corpus.",
        ['speed (x10000)', 'snap (0=ease, 1=jump)']),
    682: ('SetSceneFlag400', 'flow',
        "Set the scene context's +400 tristate field: arg must be 0, 1, or 2 and is written directly (scene+400 = arg). Purpose of the field is unconfirmed — likely a fade-direction or scene-phase indicator. One argument; single corpus use (bank 223).",
        ['phase (0/1/2)']),
    691: ('MultiplyValues', 'misc',
        "Multiply a series of N factors together (N = 0 yields 1), cap the product at 999,999,999, and write it to the VM output (reg0). A deterministic arithmetic product - there is NO RNG involved (the old 'Roll' name was misleading). arg0 = N (factor count), followed by N factor values.",
        ['N (factor count)', 'factors (variadic)']),
}
for _op, (_m, _c, _d, _a) in _AUDIT_2026_09_01.items():
    _add(_op, _m, _c, _d, _a)

# ---- 2026-09-01 addendum: engine tiebreaks -----------------------------------------
# A second handler-by-handler read found places where the AUDITED reference above was
# wrong. Each entry below is confirmed against the engine's decompiled handler;
# RF4S.exe+RVA in the descriptions.
_AUDIT_2026_09_01B = {
    202: ("SetCameraZoom", "screen",
          "Set the camera zoom / pull-back distance: the engine stores (arg0 - 1500) in the "
          "player camera struct (+68 target). arg1 != 0 SNAPS (writes current +64 AND target "
          "+68); arg1 == 0 eases (target only, view drifts to the new framing). Both paths "
          "apply the zoom - the old 'arg1 = reset to default rig' reading was wrong "
          "(IDB-corrected 2026-08-25; re-confirmed 2026-09-01). "
          "Magnification = 1 + arg0/1800.",
          ["zoom (distance = arg-1500)", "snap (0=ease to it, 1=jump)"]),
    227: ("QueryNpcScheduleIsOneOf", "query",
          "Read 1 iff an NPC's current schedule id matches ANY id in the list. arg0 = npc "
          "(char id; 0 tests the PLAYER's scene/menu-state field, 22 the current child id). "
          "args[1..] = the schedule ids - there is NO count argument: the 'count' is the "
          "statement's own packed arg-count slot (the handler at RF4S.exe+0x1FD9F0 reads it from "
          "the encoding, confirmed 2026-09-01).",
          ["npc (char id, 0=player, 22=current child)", "schedule id …"]),
    286: ("ShakeActor", "actor",
          "Start an actor TREMBLE: arg1 (low 16 bits) is a shake-frames countdown written "
          "into the actor's state word's low half - each tick offsets the sprite through a "
          "jitter table until it runs out. The high word (a separate blink/flash timer) is "
          "preserved. The old 'set state bitfield low16' reading described the store, not "
          "the effect. arg0 = actor (char id, 0 = player; ids >= 0x30 resolve to nothing).",
          ["actor (char id, 0=player)", "shake duration (frames)"]),
    289: ("CarryBaby", "actor",
          "Family-scene beat: the target actor picks up the newest child. Anim ordinal 240 "
          "resolves to 00_470_dakko.bfskl (the baby-CARRY pose, not a 'talking gesture'), "
          "and the gated callee spawns a task literally named 'baby' (MCModel 4*flag+1167) "
          "held by the actor. The gate reads GF_REG_CHILD_NUM then bit 287+(num-1) - the "
          "per-child variant flag choosing which baby model rides along. (Old "
          "'TriggerActorTalkAnim + talk indicator' reading retired 2026-09-01.)",
          ["actor (char id, 0=player)"]),
    308: ("GetDateSnapshot", "time",
          "Read a full calendar snapshot into 5 VM outputs: reg0 = YEAR (+20), reg1 = SEASON "
          "(+16), reg2 = day (+12), reg3 = hour (+8), reg4 = minute (+4) - the verified "
          "cal_inner field order (the same offsets that proved op 305 returns the season). "
          "An earlier note listing minute..season order parroted stale IDB labels. No args.",
          []),
    691: ("MultiplyValues", "misc",
          "Multiply ALL the statement's args together, cap the product at 999,999,999, and "
          "write it to reg0. Deterministic - no RNG (the old 'Roll' name was wrong). There "
          "is NO separate count argument: the count is the statement's own packed arg-count "
          "slot, every script arg is a factor, and an EMPTY call yields 0, not 1 "
          "(RF4S.exe+0x21FC40; confirmed 2026-09-01).",
          ["factors (variadic; every arg is one factor)"]),
}
for _op, (_m, _c, _d, _a) in _AUDIT_2026_09_01B.items():
    _add(_op, _m, _c, _d, _a)

# Alias siblings of audited ops (same handler, "Alias of op N" descs) must carry the
# corrected arg labels too — the audit fixed the primary of each pair:
for _alias, _primary in ((239, 238), (241, 240), (228, 227)):
    META[_alias]["a"] = list(META[_primary]["a"])

# The enum-picker wiring above ran against pre-audit arg hints; drop any picker whose
# arg index the audit removed (e.g. op 493 turned out to take no arguments).
for _k in [k for k in ENUM_ARG_VALUES
           if (k[0] in _AUDIT_2026_09_01 or k[0] in _AUDIT_2026_09_01B)
           and k[1] >= len(META[k[0]]["a"])]:
    del ENUM_ARG_VALUES[_k]

# --- handler-verified fixups (2026-09-24) -------------------------------------------------------
# Ops that share one handler in g_sceneActionHandlerTable (RF4S.exe+0x4DB790) take the same
# arguments; fill the unlabelled siblings from the labelled one. Handlers:
# Script_VMOp_PopulateQuestRequestKind2WithRandomCats RF4S.exe+0x216250 (508/509/537/538),
# ..Kind4ChainedRandom RF4S.exe+0x216B20 (513/514/541/542), ..Kind5SimpleNoAlts
# RF4S.exe+0x2170A0 (516/517/543/544).
for _group in ((509, 508, 537, 538), (541, 513, 514, 542), (517, 516, 543, 544)):
    for _o in _group[1:]:
        if _o in META and not META[_o]["a"]:
            META[_o]["a"] = list(META[_group[0]]["a"])
# Script_VMOp_PopulateQuestRequestKind2WithLiteralAlternates (RF4S.exe+0x216570): arg0 item,
# args 1/2 = template bytes 4/5, args 3.. = literal alternate item ids (only the first 4 kept).
# Script_VMOp_PopulateQuestRequestKind9BackrefLiteralAlts (RF4S.exe+0x2178D0): arg0 item, then
# literal alternates; a 0 ends the list, only the first 4 are kept.

# SpawnMapEntity (ScriptVMOp_SpawnMapEntityByTypeIdDispatchTable, RF4S.exe+0x213E20): 5 fixed
# args, then the extras are copied into a 6-dword stack buffer with NO upper bound on the loop
# (index 5 .. argc-1). The shipped corpus passes 11 (170 uses) or 6 (3 uses), so there are SIX
# extras, and more than 11 args overwrite the handler's stack frame.
META[157]["a"] = ["entity type id", "param 1 (x/pos)", "param 2 (y/pos)", "facing (degrees)",
                  "sub-param (x40)", "extra 5 (type-specific)", "extra 6 (type-specific)",
                  "flag 7 (0/1, type-specific)", "flag 8 (0/1, type-specific)",
                  "extra 9 (type-specific)", "extra 10 (type-specific)"]
META[157]["d"] = META[157]["d"].replace(
    "args5-9 = up to 5 optional EXTRA placement params",
    "args 5-10 = up to 6 optional EXTRA placement params (the handler copies them into a "
    "6-slot buffer without a bound check: never pass more than 11 args)")

# Hard per-op argument caps where passing more corrupts memory in the handler. The assembler
# refuses listings that exceed them (scriptasm.Assembler._action).
ARG_LIMITS = {
    157: (11, "ScriptVMOp_SpawnMapEntityByTypeIdDispatchTable (RF4S.exe+0x213E20) copies args "
              "5.. into a 6-slot stack buffer with no bound check"),
}


# (op, arg index) slots whose handler reads the argument's token KIND as an add/sub/set
# mode (Script_PrepActionArgs pushes (value, kind) pairs; these handlers read the kind):
# ApplyFriendshipDelta arg1 (RF4S.exe+0x1FD2B0), ModifyLumber arg0 (+0x2040A0),
# ModifyPlayerResource arg1 (+0x20D640). The leaves null / zero / self carry kinds 4 / 5 / 6
# (Script_EvalExpressionOrVar, +0x23EA10), i.e. add / subtract / set.
MODE_ARG_SLOTS = {(217, 1), (326, 0), (417, 1)}
MODE_LEAF_WORDS = {0x11: "add", 0x12: "sub", 0x13: "set"}


def arg_limit(op):
    """(max_args, reason) for an op whose handler overflows past that many args, else None."""
    return ARG_LIMITS.get(op)


# The fewest / most arguments each op passes in the shipped rf3.mc (refdata/
# script_arg_counts.json, gen_arg_counts.py). Handlers take the count the statement carries
# and read a missing argument as stack garbage: op 93 with no argument
# (ScriptVMOp_SetDialogueSpeakerEmoteByArg, RF4S.exe+0x2031D0) passes an uninitialised byte
# as the box style, and the box disappears.
_ARG_RANGES = None


def arg_range(op):
    """(fewest, most) arguments the shipped game passes to `op`, or None when the game never
    uses it (or the table is missing)."""
    global _ARG_RANGES
    if _ARG_RANGES is None:
        import json
        try:
            from .refdata import refdata_path
        except ImportError:                               # imported as a top-level module
            from rf4s_modkit.refdata import refdata_path
        try:
            raw = json.loads(refdata_path("script_arg_counts.json").read_text(encoding="utf-8"))["ops"]
            _ARG_RANGES = {int(k): (int(v[0]), int(v[1])) for k, v in raw.items()}
        except (OSError, ValueError, KeyError):
            _ARG_RANGES = {}
    return _ARG_RANGES.get(op)


def arg_count_problem(op, n):
    """Why `n` arguments is wrong for `op` (outside what the shipped game passes), or None."""
    r = arg_range(op)
    if r is None or r[0] <= n <= r[1]:
        return None
    want = ("%d" % r[0]) if r[0] == r[1] else ("%d to %d" % r)
    names = arg_names(op)
    what = (" (%s)" % ", ".join(names[:r[1]])) if names and r[1] else ""
    row = table_row(op)
    opt = row.get("optional_args_from") if row else None
    if n > r[1]:
        why = "the shipped game never passes more"
    elif opt is not None and n >= opt:          # the handler copes; only the shipped form differs
        why = "the shipped game always passes at least %d" % r[0]
    else:
        why = "the game reads a missing argument as leftover memory"
    return ("%s (op %d) takes %s argument%s%s, not %d -- %s"
            % (mnemonic(op), op, want, "" if r[1] == 1 else "s", what, n, why))


def arg_value_problem(op, index, value):
    """Why `value` for argument `index` of `op` is known to break the game (the table's
    per-argument `refuse_values`: {"192": "reason"}), or None. The friendly editors refuse
    it; the Source tab and non-strict assembly allow it."""
    a = arg_row(op, index)
    why = ((a or {}).get("refuse_values") or {}).get(str(value))
    if not why:
        return None
    return "%s (op %d) %s = %d: %s" % (mnemonic(op), op, a.get("name") or ("argument %d" % index), value, why)


# --- sound-id annotations (2026-09-24) ----------------------------------------------------------
# PlaySound (385) and PlayVoicedSound (392, after Sfx_FindOrPreemptVoice) call Sfx_PlayById
# (RF4S.exe+0x19B6F0) -> Sfx_StartSoundInSlot -> Sfx_PlaySoundWithDedupAndVoiceKill, which
# resolves the id with SoundCache_Get; PlaySfxWithNpcRemap (387) goes through
# Sfx_PlayByIdWithNpcVariantRemap to the same player; StopVoiceId (390) matches the playing
# slot's sound id (Sfx_StopVoiceIfMatchingTargetIdCallback). Label = the audio file name from
# the game's own common/voice_en tables (soundtable.SOUND_LABELS), read lazily on first use;
# the mapping is empty (no label, bare number) when the bundle isn't available.
try:
    from .soundtable import SOUND_LABELS as _SOUND_LABELS
except ImportError:                                   # imported as a top-level module
    try:
        from rf4s_modkit.soundtable import SOUND_LABELS as _SOUND_LABELS
    except ImportError:
        _SOUND_LABELS = None
if _SOUND_LABELS is not None:
    for _sk in ((385, 0), (387, 0), (390, 0), (392, 0)):
        ENUM_ARG_VALUES.setdefault(_sk, _SOUND_LABELS)

# op 11 SetSpeakerNameVisible: bit 0 of the dialogue flags word = (arg == 0) -> the speaker-name
# label's hide bit (see the op 11 description)
ENUM_ARG_VALUES.setdefault((11, 0), {
    0: ("hide name", "Hide the speaker-name label for the following lines (narration, inner voice, sound words)."),
    1: ("show name", "Show the speaker-name label again (normal spoken lines)."),
})

# ---- opcode review 2026-09-26: pickers for the corrected argument labels -----------------
# The auto-wiring above keys on "char id" in a label; these corrected labels name the same
# character ids in other words (portrait ops 77-90 match a character against the two
# portraits; 163/206/207/211/212/228 take 0 = player, 1-47 NPC).
for _k in [(_o, 0) for _o in range(77, 91) if _o != 83] + [(163, 1), (206, 0), (207, 0),
                                                           (211, 0), (212, 0), (228, 0)]:
    ENUM_ARG_VALUES[_k] = CHAR_IDS
# 0 means "all villagers" / "count all" / "the current room", not the player
for _k in ((226, 0), (261, 0), (268, 0), (269, 0), (274, 0)):
    ENUM_ARG_VALUES[_k] = _CHAR_IDS_NPC
# not villager ids: guest-roster ids 24-47 (470-472), request record 0 = the board (528),
# a raw u16 stored at record+6 (291)
for _k in ((470, 0), (471, 0), (472, 0), (528, 0), (291, 1)):
    ENUM_ARG_VALUES.pop(_k, None)


# ---- opcode table (review 2026-09-27) ------------------------------------------------------
# opcode_table.json is the single source for every action op's mnemonic, category,
# description and argument labels, and for the control instructions' names: all 702 handlers
# re-read against RF4S.exe and the shipped rf3.mc, then a naming pass (Get = register query,
# Is/Has = boolean query, Wait = blocks, verb first; true aliases share a name). It is applied
# LAST so it wins over the text above; the pickers wired above stay keyed by (op, arg index).
# Each row also carries returns / blocking / details / evidence and the human_verified flag
# (OPCODE_TABLE.md is generated from it by gen_opcode_table.py).
with open(refdata_path("opcode_table.json"), encoding="utf-8") as _f:
    TABLE = json.load(_f)


def _arg_label(a):
    v = (a.get("values") or "").strip()
    return "%s (%s)" % (a["name"], v) if v and v.lower() not in ("any", "-") else a["name"]


for _k, _r in TABLE["actions"].items():
    META[int(_k)] = {"m": _r["mnemonic"], "c": _r["category"], "d": _r["description"],
                     "a": [_arg_label(_a) for _a in _r["args"]]}
_OP_BY_MNEMONIC = None
CONTROL_NAMES = {int(_r["code"]): _r["mnemonic"] for _r in TABLE["control"].values()}
CONTROL = {_r["mnemonic"]: (_r["category"], _r["description"]) for _r in TABLE["control"].values()}


def table_row(op):
    """The opcode_table.json row of an action op (dict), or None."""
    return TABLE["actions"].get(str(op))


# Argument value names: an argument whose value is a code (ModifyPlayerResource's resource,
# ShowActorEmote's icon) lists its codes in the table as
#   "value_names": {"100": {"name": "gold", "text": "...", "human_verified": true}, ...}
# The name is what a listing writes and the assembler reads (ModifyPlayerResource(gold, add,
# 1234)), and it replaces any built-in picker table of that argument. Each argument also has
# its own human_verified flag and a `tests` log of the in-game tests that exercised it (see
# optest.py): an op can be verified while some of its arguments are not.
VALUE_NAMES = {}                                   # (op, arg index) -> {value: name}
for _k, _r in TABLE["actions"].items():
    for _i, _a in enumerate(_r["args"]):
        _vn = _a.get("value_names")
        if _vn:
            VALUE_NAMES[(int(_k), _i)] = {int(_v, 0): _e["name"] for _v, _e in _vn.items()}
            ENUM_ARG_VALUES[(int(_k), _i)] = {int(_v, 0): (_e["name"], _e.get("text") or "")
                                              for _v, _e in _vn.items()}


def value_name(op, arg_index, value):
    """The table's source name for `value` of argument `arg_index` of `op`, or None."""
    return VALUE_NAMES.get((op, arg_index), {}).get(value)


def arg_row(op, arg_index):
    """The opcode_table.json entry of one argument (dict), or None."""
    r = table_row(op)
    return r["args"][arg_index] if r and 0 <= arg_index < len(r["args"]) else None


def arg_verified(op, arg_index):
    """True when a person confirmed this argument's meaning in game."""
    a = arg_row(op, arg_index)
    return bool(a and a.get("human_verified"))


# Opcode arguments: an instruction family whose leading arguments are encoded in the opcode
# itself, e.g. SetSpeaker(character, side, face, ...) = ops 16..75 with
# opcode = 16 + 2*character + side (one handler, RF4S.exe+0x207F70, decodes both). A row's
# `opcode_args` lists those arguments with this opcode's value; the listing prints them in
# front of the stored arguments and the assembler picks the opcode from them.
OPCODE_ARGS = {int(_k): _r["opcode_args"] for _k, _r in TABLE["actions"].items() if _r.get("opcode_args")}
_FAMILY = {}                                       # mnemonic (lower) -> {(raw, ...): op}
for _o, _oa in OPCODE_ARGS.items():
    _FAMILY.setdefault(META[_o]["m"].lower(), {})[tuple(_a["raw"] for _a in _oa)] = _o


def opcode_arg_values(op):
    """Names of the opcode-encoded arguments of `op` (e.g. ['Forte', 'Right']), or []."""
    return [a["value"] for a in OPCODE_ARGS.get(op, ())]


def opcode_arg_raws(op):
    """The numbers of the opcode-encoded arguments of `op` (e.g. ['4', '1']): what a listing
    writes, since the names are ours."""
    return [str(a["raw"]) for a in OPCODE_ARGS.get(op, ())]


def opcode_arg_labels(op):
    """Display names of the opcode-encoded arguments, for comments: the speaker as the game
    names it now (speaker_name), 'MC' for the player."""
    out = []
    for a in OPCODE_ARGS.get(op, ()):
        if a["name"] == "character":
            out.append("MC" if a["raw"] == 0 else speaker_name(a["raw"]))
        else:
            out.append(a["value"])
    return out


def opcode_arg_count(name):
    """How many leading arguments of mnemonic `name` are encoded in the opcode (0 if none)."""
    fam = _FAMILY.get((name or "").strip().lower())
    return len(next(iter(fam))) if fam else 0


def op_from_opcode_args(name, texts):
    """The opcode of family `name` whose opcode arguments are `texts` (each a value name,
    case-insensitive, or its number). Raises ValueError naming the accepted values."""
    fam = _FAMILY.get(name.strip().lower())
    if not fam:
        raise ValueError("%s has no opcode arguments" % name)
    any_op = next(iter(fam.values()))
    specs = OPCODE_ARGS[any_op]
    if len(texts) < len(specs):
        raise ValueError("%s needs %s first" % (name, ", ".join(s["name"] for s in specs)))
    raws = []
    for i, (spec, txt) in enumerate(zip(specs, texts)):
        want = txt.strip()
        seen = {}
        for o in fam.values():
            a = OPCODE_ARGS[o][i]
            seen[a["value"].lower()] = a["raw"]
            seen[str(a["raw"])] = a["raw"]
        if want.lower() not in seen:
            raise ValueError("%s: %s %r is not one of: %s" % (name, spec["name"], want, spec["values"]))
        raws.append(seen[want.lower()])
    op = fam.get(tuple(raws))
    if op is None:
        raise ValueError("%s: no opcode for %s" % (name, ", ".join(texts[:len(specs)])))
    return op


def returns(op):
    """What an action op writes to the VM registers (text), or None."""
    r = table_row(op)
    return r["returns"] if r else None


def blocking(op):
    """Whether / until when an action op blocks the script (text)."""
    r = table_row(op)
    return r["blocking"] if r else None


def human_verified(op):
    r = table_row(op)
    return bool(r and r.get("human_verified"))
