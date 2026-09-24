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
import os
import re

_HERE = os.path.dirname(__file__)
with open(os.path.join(_HERE, "script_opcodes.json"), encoding="utf-8") as _f:
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
    "FRAME":     ("flow", "Frame setup (formerly mislabeled 'RET' -- it does NOT return): sets "
                          "the frame base to the current operand-stack top and reserves "
                          "[local slots] entries for locals (always even -- the stack holds "
                          "value/kind pairs, 2 per local), then execution FALLS THROUGH to the "
                          "next statement. Typically the first statement of a CALLed "
                          "subroutine; the matching return is RET (0xFFFF). IDA-verified: Script_VMStep "
                          "case 0xFFF1, corrected 2026-08-06 (decomp docs/script_vm.md 2.3)."),
    "CALL":      ("flow", "Call a subroutine: push the caller's frame base and the return PC "
                          "onto the operand stack, then jump. The subroutine comes back here "
                          "when it executes RET (the VM's return)."),
    "JMP":       ("flow", "Unconditional jump (trampoline-inserted beats read inline)."),
    "BR_Z":      ("flow", "Branch if the guard expression is 0 (false)."),
    "BR_NZ":     ("flow", "Branch if the guard expression is non-zero (true)."),
    "BR_RET":    ("flow", "Conditional RET (early-exit guard): evaluate the guard expression -- "
                          "if it is nonzero/true, do exactly what RET does (return from a CALLed "
                          "subroutine, or end the scene at top level); otherwise fall through to "
                          "the next statement. Never emitted in shipped scripts. IDA-verified "
                          "(Script_VMStep case 0xFFFD -> Script_EvalExpressionOrVar, then "
                          "Script_Opcode_FFFF_EndAndCleanup when true)."),
    "STORE":     ("flag", "Evaluate an expression and store it into a variable."),
    "DIALOG":    ("dialogue", "Show a dialogue line (by text id). The current SPEAKER (set by a "
                          "SetSpeaker* portrait op, SetSpeakerVoice op 10, or nothing = "
                          "narration) PERSISTS across consecutive DIALOG lines until the next "
                          "speaker op or EndDialogue (op 92) — 917 shipped scenes rely on "
                          "back-to-back lines under one speaker. If an ArmChoiceOption (op 615) "
                          "precedes this line, it does NOT display: it queues as a choice "
                          "option for a later PROMPT_CHOICE instead."),
    "SWITCH_EQ": ("flow", "Indexed jump table: evaluate the selector expression, then jump to "
                          "targets[value] when 0 <= value < N -- a DENSE 0..N-1 index, not a set of "
                          "per-case compare values. The comparison is UNSIGNED, so a negative "
                          "selector (like reg0 = -1 after a cancelled prompt) falls through to the "
                          "next statement, same as any >= N value. The canonical use is dispatching "
                          "a choice result: `SWITCH_EQ (reg0)` after a staged PROMPT_CHOICE jumps "
                          "to the picked option's branch. Layout: [op][selector-expr][N]"
                          "[N u16 targets]. IDA-verified (Script_VMStep case 0xFFF7, "
                          "RF4S.exe+0x23EF60)."),
    "SWITCH_GE": ("flow", "Indexed jump table, always-branch variant of SWITCH_EQ: jump to "
                          "targets[value] when value < N, and CLAMP an out-of-range value (>= N, "
                          "including negatives -- the compare is unsigned) to the last target "
                          "(targets[N-1]) rather than falling through -- so it never falls "
                          "through. Same [op][selector-expr][N][N u16 targets] layout as "
                          "SWITCH_EQ. Used exactly once in the whole game. IDA-verified "
                          "(Script_VMStep case 0xFFF6)."),
    "JMP_IND":   ("flow", "Uniform-random jump: pick one of the N targets at random (each 1/N) and "
                          "jump to it -- the UNWEIGHTED sibling of RAND_BR. Takes no operand (the "
                          "target table is the only data); the pick is an RNG roll in [0, N) via the "
                          "same VM RNG (reader-vtable +56) that RAND_BR rolls its weighted pick with. "
                          "Layout: [op][N][N u16 targets]. IDA-verified (Script_VMStep case 0xFFF3)."),
    "RAND_BR":   ("flow", "Weighted-random branch: pick one of N targets at random, each weighted by "
                          "an expression. Every case's weight is evaluated fresh (so a weight can "
                          "depend on game state), the weights are summed, then an RNG roll in "
                          "[0, total) selects a target -- case i fires with probability "
                          "weight[i] / sum(weights) (weight 0 = never taken). The editable literals "
                          "on this op ARE those per-target weights, so raising one tilts the odds "
                          "toward its branch. Layout: [op][N][N u16 targets][N u16 weight-exprs]; "
                          "size 4N+4. IDA-verified (Script_VMStep case 0xFFF2 -> "
                          "Script_Opcode_FFF2_ExecPrim, RF4S.exe+0x23EC40)."),
    "PROMPT_CHOICE_FORCED": ("flow",
                          "Present a choice dialog the player CANNOT cancel -- one of "
                          "the N u32 items MUST be picked. Same UI as PROMPT_CHOICE "
                          "(each item is an rf3mc.<locale> string id) but with no CANCEL "
                          "target. Branches to targets[picked VISIBLE ROW]. reg0: written "
                          "ONLY when the choice was STAGED (a visibility mask via ops "
                          "610/612, or an ArmChoiceOption 615 queue) -- then reg0 = the "
                          "picked option's ORIGINAL index (mapped through the mask bits), "
                          "and a following SWITCH_EQ on reg0 dispatches it. An UNSTAGED "
                          "prompt leaves reg0 UNTOUCHED -- shipped scenes rely on that to "
                          "carry a GetPlayerPosition result in reg0/reg1 straight across a "
                          "Yes/No prompt into the moves after it (the deck-fight chase). "
                          "Layout: [op][N][N u16 targets][N u32 items]; size 6N+4. "
                          "IDA-re-verified 2026-08-18 "
                          "(SceneEvent_FinalizeAndPickFromBitmap)."),
    "PROMPT_CHOICE": ("flow", "Present a cancellable choice dialog (B backs out). Branches to "
                              "the CANCEL target (index 0) on dismissal, else to the picked "
                              "row's target. reg0 follows the same STAGED-ONLY rule as "
                              "PROMPT_CHOICE_FORCED: a visibility-mask or armed-option prompt "
                              "writes the picked option's ORIGINAL index to reg0 (for the "
                              "following SWITCH_EQ); an unstaged prompt leaves reg0 alone, so "
                              "values parked there by query ops survive the prompt. With a "
                              "staged visibility mask only flagged options appear, and the "
                              "prompt clears the mask (and any armed queue) after the pick. "
                              "Layout: [op][N][N+1 u16 targets: target[0]=cancel, target[1..N]="
                              "per-choice][N u32 items]; size = 6N+6. IDA-verified via "
                              "Script_VMStep case 0xFFF4 + SceneEvent_FinalizeAndPickFromBitmap "
                              "(2026-08-18)."),
}

# ---- curated action-opcode metadata: op -> (mnemonic, category, description, [args]) ----
# args names label each positional argument for the tooltip.
# NOTE: keys here are the OLD (+302-shifted) indices; they get shifted to the real
# action ids below. See the _M assembly after this dict.
_M_OLDBASE = {
    # --- dialogue / portraits / emotes ---
    14:  ("SetNpcVisible", "dialogue", "Show or hide a scene NPC.", ["npc id", "visible"]),
    17:  ("SetEmote", "dialogue", "Set an NPC's facial-expression / emote byte (record +57), switching its portrait face (happy/sad/angry/etc) -- e.g. mid-dialogue. Same handler as op320 SetNpcEmoteByte. NOT a transient emote 'bubble' popup (those are op5/6/7 ShowNpcBubble).", ["npc id", "emote id"]),
    19:  ("GetEmote", "query", "Read an NPC's current emote id.", ["npc id"]),
    20:  ("SetMood", "dialogue", "Set an NPC's MOOD byte (record +56) -- a per-NPC temperament/mood state. Distinct from the displayed facial expression / emote byte (record +57, op319 SetEmote); unlike SetEmote this does NOT update g_lastDialogueEmoteId. Same handler as op323.", ["npc id", "mood id"]),
    22:  ("GetMood", "query", "Read an NPC's current mood id.", ["npc id"]),
    253: ("SetBubbleFlavor", "dialogue", "Set an NPC's dialogue-bubble flavor variant.", ["npc id", "flavor"]),
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
    381: ("PlayVideoOrAdvance", "screen", "Play a pre-rendered cutscene video, or advance dialogue.", ["video id"]),
    # --- flags & variables ---
    16:  ("SetFlag", "flag", "Set a packed story/quest/event flag.", ["flag id", "(value)"]),
    141: ("SetFlagBit", "flag", "Set a single game-flag bit directly.", ["flag id", "value"]),
    142: ("SetFlagBitIfCond", "flag", "Set a game-flag bit, gated by a condition script.", ["flag id", "value"]),
    143: ("GetFlagBit", "query", "Read a single game-flag bit.", ["flag id"]),
    # --- audio ---
    77:  ("PlayMusic", "audio", "Play a BGM track, or restore the map's default (-1).", ["bgm id (-1=restore)"]),
    78:  ("FadeMusic", "audio", "Ramp BGM volume / crossfade.", ["target vol", "duration"]),
    80:  ("SetSfxVolume", "audio",
          "Override the SFX-capture volume for the scene (handler "
          "Script_VMOp_SetSfxCaptureVolumeOverride). arg0 = mode/volume: -1 restores the default "
          "volume; any other value captures the current scaled capture volume. arg1 = distance "
          "attenuation, passed to Sfx_ApplyDistanceAttenuation. (Handler reads two args -- "
          "argbuf[-3]=mode, [-5]=attenuation.)",
          ["mode / volume (-1 = restore default)", "attenuation"]),
    83:  ("PlaySound", "audio", "Play a sound effect by id.", ["sfx id"]),
    84:  ("StopVoices", "audio", "Stop all active voice slots.", []),
    87:  ("FindVoiceSlot", "audio", "Find or preempt a voice slot.", ["voice id"]),
    88:  ("StopVoiceId", "audio", "Stop the voice matching an id.", ["voice id"]),
    90:  ("PlayVoicedSound", "audio", "Play a sound effect via a dedicated voice slot.", ["sfx id"]),
    # --- player / actors ---
    7:   ("IsFrey", "query", "Writes 1 to reg0 when playing as Frey (female protagonist), 0 for "
         "Lest. The scripts pick gendered lines/animations by branching on reg0 right after.", []),
    25:  ("PlayActorTransform", "actor",
          "Alias of op 328 (same handler Script_VMOp_SetActorOutfitVariant): play an animated "
          "outfit/pose CHANGE on an actor via the character-change transform task. arg0 = actor "
          "(char id, 0 = player). arg1 = pose/variant (255 = end/detach pose, 3 = alt outfit).",
          ["actor (char id, 0=player)", "pose/variant (255=end, 3=alt)"]),
    27:  ("IsPosing", "query", "1 if an actor's scripted pose is active.", ["actor"]),
    28:  ("SetOutfitDirect", "actor", "Set an actor's outfit index directly.", ["actor", "outfit"]),
    91:  ("FreezePlayer", "actor", "Lock or release player input.", ["freeze (0/1)"]),
    92:  ("WarpPlayer", "actor", "Teleport the player to a map tile.", ["tile x", "tile y"]),
    93:  ("SetPlayerPose", "actor", "Set the player's facing angle and pose.", ["facing deg", "pose"]),
    95:  ("SetPartyOutfit", "actor", "Set the party outfit variant and sync friendship.", ["variant"]),
    97:  ("GetPlayerSubstate", "query", "Read the player's substate id.", []),
    98:  ("RefreshPlayer", "actor", "Refresh the player actor and apply the default name.", []),
    358: ("SetActorStatusFlag", "actor",
          "Set/clear the target actor's stats.status_flags bit 0x20 by char id (for char id 239 it "
          "toggles bit 0x10000 instead). No stat recompute. arg0 = char id (0=player, 1..47=NPC, "
          ">=48=event actor via calendar-event mng), arg1 = 0 to clear / non-zero to set. NOTE: "
          "distinct from op 661 SetActorStatFlagRecompute (bit 0x20000 + stat recompute + HP clamp).",
          ["char id (0=player, <48=NPC, >=48=event)", "on (0=clear, else set)"]),
    360: ("SetActorArmorBreak", "actor", "Toggle an actor's armor-break bit by char id.", ["char id", "value"]),
    363: ("SetActorFacing", "actor", "Set an actor's facing angle by char id.", ["char id", "deg"]),
    # --- NPC streaming / placement ---
    174: ("SpawnNpc", "actor", "Stream an NPC in at the player's position.", ["npc id"]),
    176: ("SpawnNpcScripted", "actor", "Stream an NPC in at the player. arg1 sets/clears the npc record's bit 30 (0x40000000) 'scripted-presence / cutscene-owned' marker.", ["npc id", "scripted (0/1)"]),
    178: ("WakeSceneNpcChild", "actor", "Wake the scene child of the current interaction NPC.", []),
    190: ("FaceNpcToPlayer", "actor", "Make a scene NPC stand in front of / face the player.", ["mode"]),
    191: ("GetNpcFacingMode", "query", "Read a scene NPC's scripted-facing mode bits.", ["npc id"]),
    # --- companions ---
    181: ("SyncCompanions", "companion", "Sync both companions into the scene.", []),
    193: ("WarpCompanion", "companion", "Teleport companion(s) to a tile.", ["slot", "tile x", "tile y"]),
    194: ("MoveCompanion", "companion", "Move a companion toward a tile (choreographed, with facing).",
          ["slot", "tile x", "tile y", "facing deg", "speed", "run"]),
    195: ("MoveCompanionNF", "companion", "Move a companion toward a tile (no facing change).",
          ["slot", "tile x", "tile y", "speed", "run"]),
    196: ("MoveCompanionRel", "companion", "Move a companion relative to its current tile (with facing).",
          ["slot", "dx", "dy", "facing deg", "speed", "run"]),
    198: ("SetCompanionPose", "companion", "Set a companion's facing angle and pose.", ["slot", "facing deg", "pose"]),
    199: ("CompanionFaceTarget", "companion", "Turn a companion to face a target actor, set pose.", ["slot", "target", "pose"]),
    200: ("IsCompanionMoving", "query", "1 if any companion is still moving/rotating (blocking poll).", ["slot"]),
    201: ("StopCompanionAnim", "companion",
          "Stop the companion's current animation and (per the flag) clear its per-NPC outfit "
          "override; also clears armor-break bit 4 and control-flags 0x10C. Skips companions that "
          "are stunned/frozen (actor+568 bit 4). arg0 = companion slot (0=companion 1, 1=companion "
          "2, 2=both). arg1 = clear mode/flag passed to Npc_StopAnimAndClearOutfitOverride (NOT an "
          "outfit id).",
          ["slot (0=comp1, 1=comp2, 2=both)", "clear mode/flag"]),
    204: ("WarpMonstersToPlayer", "companion", "Teleport all companion monsters to the player.", []),
    # --- time / calendar ---
    2:   ("GetMinute", "time", "Read the current calendar minute.", []),
    3:   ("GetHour", "time", "Read the current calendar hour.", []),
    4:   ("GetDay", "time", "Read the current calendar day.", []),
    5:   ("GetMonthSeason", "time", "Read the current month and season.", []),
    6:   ("GetDateSnapshot", "time", "Read a full calendar snapshot.", []),
    149: ("GetDayOfWeek", "time", "Read the current day of the week.", []),
    164: ("SkipToTime", "time",
          "Fast-forward the clock FORWARD to a target time (hour:minute), rolling into the next "
          "day(s) if the target is earlier than now -- the classic cutscene 'time passes' skip "
          "(FastForwardForSleep). arg0 = target HOUR (cal_inner +8, forward delta mod 24), arg1 = "
          "target MINUTE (cal_inner +4), arg2 = enable (0 = no-op). Definitive field map from "
          "Calendar_NormalizeTimeCarry: cal_inner = [+0 Q12sec, +4 minute, +8 hour, +12 day, +16 "
          "season, +20 year]; hour>24 rolls the day, day>30 rolls the season -- so this sets the "
          "TIME, not the date (date advances only via rollover). Shipped scenes: arg0 = a target "
          "hour (6/8/17/21/22...), arg1 = 0 (on the hour), arg2 = 1. (Was mislabeled SkipToDate/day+month.)",
          ["hour", "minute", "enable (0 = no-op)"]),
    325: ("SleepToMorning", "time", "Advance to the next morning (randomized minute) and unpause.", []),
    335: ("SaveCalendarSnapshot", "time", "Save a calendar snapshot.", []),
    # --- items / rewards / economy ---
    23:  ("GetLumber", "item", "Read the player's lumber count.", []),
    24:  ("AddLumber", "item", "Add to (or subtract from) the player's lumber.", ["amount"]),
    121: ("GiveItem", "item", "Give the player an item (stack + quality).", ["item id", "count", "quality"]),
    123: ("ForceHoldItem", "item", "Force the player to hold an item (or consume it).", ["item id"]),
    126: ("TakeItem", "item", "Remove an item from any container.", ["item id", "count"]),
    150: ("SpawnItemAtTile", "item", "Spawn an item in the world at a map tile -- as a droppable pickup or a visual-only prop, chosen by the last arg (handler Item_SpawnAtPositionAsDropOrVisual). NOT a shipping-bin op despite the old name (real shipping = QueryShippingBoxTotalGold @ op 649). Verified: 28 scene call sites pass (item, count, quality, x_tile, y_tile, drop).", ["item id", "count", "quality", "x tile", "y tile", "as-drop (0=visual, 1=pickup)"]),
    155: ("ShowRewardPopup", "item", "Show a reward popup for up to 4 items.", ["item0", "item1", "item2", "item3"]),
    156: ("ShowQuestReward", "item", "Show the NPC quest-reward popup.", []),
    158: ("AddRewardItem", "item", "Add an item to the reward-slot popup.", ["item id", "count"]),
    161: ("DropItem", "item", "Drop a single item at the player.", ["item id"]),
    162: ("DropItemStack", "item", "Drop a stack of an item at the player (item id, count, quality). Handler packs quality into the slot's high bits, like the item-spawn family.", ["item id", "count", "quality"]),
    337: ("GetPrincePoints", "item", "Read the current prince points.", []),
    338: ("AddPrincePoints", "item", "Add prince points.", ["amount"]),
    339: ("GetTourists", "item", "Read the current tourist count.", []),
    340: ("AddTourists", "item", "Add tourists.", ["amount"]),
    343: ("PromotePrinceRank", "item", "Promote the prince rank if the threshold is reached.", []),
    344: ("GetPrinceRank", "query", "Read the current prince rank.", []),
    # --- effects / world ---
    108: ("TameEventNpc", "effect", "Tame the calendar-event NPC/monster.", []),
    144: ("SetWeather", "effect", "Set the current weather.", ["weather id"]),
    145: ("GetWeather", "query", "Read the current weather.", []),
    341: ("TriggerEffect", "effect",
          "Dispatch a town/prince effect by id (Effects_DispatchById; spends its cost) and write "
          "the returned did-promote flag to the query register. arg1 = sub-index/variant handed to "
          "the dispatcher (commonly a runtime variable; verified read at argbuf[-5]).",
          ["effect id", "sub-index / variant"]),
    342: ("GetEffectState", "query",
          "Query a town/prince effect's state by id (Effects_QueryById) into the query register. "
          "arg1 = sub-index/variant (verified read at argbuf[-5]; usually 0 in shipped scenes).",
          ["effect id", "sub-index / variant"]),
    387: ("ResetMonsterSpawns", "effect", "Reset the monster-spawn tracker for the player.", []),
    # --- scene flow (kept close to technical -- no clean author verb) ---
    30:  ("BeginBeat", "flow", "Begin a scripted scene action (prunes pending UI events).", []),
    31:  ("BeginBeat2", "flow", "Begin a scripted scene action (variant; caches a game-flag value).", []),
    75:  ("GetChoiceResult", "flow", "Consume the committed choice-dialog result.", []),
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
    8:  ("DialogueLine", "dialogue", "Show a dialogue line (portrait speaks; reads speaker/line tokens).", ["speaker/line id"]),
    10: ("SetSpeakerVoice", "dialogue",
         "Set the speaker for the following DIALOG line(s) to a NAMED VOICE: name plate only, "
         "NO portrait ('no portrait dispatch' — the handler's own contract). This is how "
         "off-screen and un-introduced characters speak — the opening's captain monologue "
         "(name string 738) and the stowaway bandits' whispers (392) both talk through it. "
         "arg0 = the NAME-PLATE string id (a name-archive entry, not an rf3mc line id; "
         "latched at sceneCtx+108 so repeats are free); arg1 = the text-tick chime class "
         "(0 = default 16785916, 1 = happy, 2 = excited, 3 = variant). IDA-verified "
         "(NpcBubble_DispatchSimpleScriptedLine, RF4S.exe+0x20A240).",
         ["name string id", "chime/tone (0=default,1=happy,2=excited,3=variant3)"]),
    11: ("SetDialogStateBit", "dialogue", "Dialogue-state toggle: sets bit0 of the dialogue state word "
         "(g_gameGlobalsSlotTable scratch field entries[4]) to (arg==0). Runs before lines (~1584x); "
         "a per-line render/advance mode flag (exact purpose tentative).", ["mode (0 sets the bit)"]),
    12: ("BubbleLineV3", "dialogue", "Show a scripted speech bubble (3 tokens: speaker, index, sub).", ["speaker", "index", "sub"]),
    14: ("BubbleLineV4", "dialogue", "Show a scripted speech bubble (4 tokens; PSB-emote capable).", ["speaker", "index", "sub", "param"]),
}
# actions 16..75 are ALL one handler NpcBubble_DispatchAreaInfoLine (RF4S.exe+0x207F70) --
# the PORTRAIT dialogue line. The OPCODE NUMBER is a parameter: the handler reads it back
# from sceneCtx+260 and computes  speaker_slot = (op-16)>>1  (0..29) and  parity = op&1.
# speaker_slot indexes g_gameGlobalsSlotTable (the character/state directory) to pick WHO
# speaks: slot 0 = the protagonist/main character, higher slots = NPCs (e.g. 19 = Nancy).
# So two consecutive opcodes (2N+16, 2N+17) are the same speaker with a parity sub-variant.
# The script args are the portrait content: arg1=face/expression; arg2/arg3=trigger ids
# (emote bubble 186-192, e.g. 190='!'/191='?', OR a voice-line sfx id >= 0x1F0 played via
# the NPC-variant remap -- NOT a target actor). The handler (NpcBubble_DispatchAreaInfoLine,
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
# 25/26/29 have no name-tag: 25/26 carry the story ANTAGONISTS (secret-weapon banter; the
# Rune-Sphere villain "I can wield the powers of an Earthmate!"), 29 unseen. Left as guestNN?.
# For any guest line, the authoritative name is the nearby `*<name>` line, not this slot label.
PORTRAIT_SPEAKERS = [
    "Lest/Frey", "Vishnal", "Clorica", "Volkanon", "Forte", "Kiel", "Bado", "Margaret",
    "Dylas", "Arthur", "Porcoline", "Xiao Pai", "Lin Fa", "Amber", "Illuminata", "Doug",
    "Blossom", "Dolce", "Jones", "Nancy", "Leon", "Ventuswill", "Son", "Daughter",
    "Pico", "guest25?", "guest26?", "Barrett", "Raven", "guest29?",
]
# Identifier-safe tag per slot, used to build the `SetSpeaker$<tag>` mnemonic. Slot 0 =
# "MC" (the player / main character, whose real name is the save name). Spaces/slashes
# stripped so the tag is a clean suffix; unproven guest slots keep a guestNN tag.
PORTRAIT_SPEAKER_TAGS = [
    "MC", "Vishnal", "Clorica", "Volkanon", "Forte", "Kiel", "Bado", "Margaret",
    "Dylas", "Arthur", "Porcoline", "XiaoPai", "LinFa", "Amber", "Illuminata", "Doug",
    "Blossom", "Dolce", "Jones", "Nancy", "Leon", "Ventuswill", "Son", "Daughter",
    "Pico", "guest25", "guest26", "Barrett", "Raven", "guest29",
]


def portrait_speaker_slot(op):
    """For a portrait-line opcode (16..75) return (speaker_slot, parity); else None.
    speaker_slot IS the NPC id: it indexes g_gameGlobalsSlotTable (0 = the player).
    parity (op&1) selects the portrait SIDE / bubble slot (+horizontal flip)."""
    if 16 <= op <= 75:
        return ((op - 16) >> 1, op & 1)
    return None


def portrait_speaker_name(op):
    """Character name for a portrait-line opcode (16..75), else None."""
    sp = portrait_speaker_slot(op)
    if sp is None:
        return None
    slot = sp[0]
    if 0 <= slot < len(PORTRAIT_SPEAKERS):
        return PORTRAIT_SPEAKERS[slot]
    return "slot %d" % slot


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
# (measured across ~211k dialogue ops). g_npcBubble_emoteToStringIdTable (RF4S.exe+0x4DA670)
# maps them to named mood categories -- ROW 0 shown here. NOTE: the mapping is *row/kind-
# dependent* (NpcBubble_ResolveSpriteRow(kind) picks the row), so a given id can render a
# different mood in a different scene: the earlier LIVE read saw 190='!'/191='?' (surprise /
# troubled) where row 0 has 190=sadness/191=smile. Treat these as the default-row meaning, and
# verify in-game for a specific scene. (JP -> EN below.)
PORTRAIT_EMOTES = {
    # Cross-checked 2026-07-07 against bank 252 tail44 scene@0x0898 pc@0x1f1e --
    # an `＊Emote Bubble` sampler menu whose labels ('＊Blush' / '＊Teary Eyes' /
    # '＊Angry' / '＊Sweat' / '＊!') pin down what each id renders as when set
    # from a SetSpeaker's arg 1. Values are the row-0 dominant meaning; the
    # actual sprite is picked by NpcBubble_ResolveSpriteRow(kind).
    186: "blush",    # ＊Blush (also 25 pairings with '＊Blushing' in the face-check menu)
    187: "teary",    # ＊Teary Eyes (previously mislabelled 'SP2' -- SP2 is a Special
                     # FACE frame at id 254; this is the teary-eyed EMOTE bubble)
    188: "sweat",    # ＊Sweat (was '通常/normal'; row-0 rendering IS a small sweat drop)
    189: "angry",    # ＊Angry / 怒り
    190: "!",        # ＊! (was '哀しみ/sad'; the row-0 sprite is the exclamation-mark bubble)
    191: "smile",    # 笑顔 (also '?' in some rows)
    192: "surprise", # 驚き
}
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


for _op in range(16, 76):
    _slot, _par = ((_op - 16) >> 1, _op & 1)
    _who = PORTRAIT_SPEAKERS[_slot] if _slot < len(PORTRAIT_SPEAKERS) else "slot %d" % _slot
    _tag = PORTRAIT_SPEAKER_TAGS[_slot] if _slot < len(PORTRAIT_SPEAKER_TAGS) else "slot%d" % _slot
    _side = "left" if _par == 0 else "right"
    _M_LOW[_op] = ("SetSpeaker" + _tag, "dialogue",
                   "Speaker cue for the following DIALOG line(s) -- designates the speaker=%s "
                   "(slot %d, from the opcode number), %s side, and their portrait. Carries no "
                   "text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines "
                   "until the next speaker op or EndDialogue (op 92) -- one cue can carry a "
                   "whole multi-line speech (917 shipped scenes do). arg0 = face frame "
                   "(0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character "
                   "extras -- selects <NN>_<NAME>_face_<FFF> portrait art). "
                   "arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: "
                   "188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, "
                   "renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the "
                   "engine's dual-use threshold -- played through the NPC-variant remap). "
                   "NOTE: arg2 is a second trigger id, not a target actor."
                   % (_who, _slot, _side),
                   ["face frame", "emote / voice id", "emote / voice id 2"])
for _lo, _hi in ((9, 8), (13, 12), (15, 14)):   # odd-slot duplicates of even handlers
    _M_LOW[_lo] = _M_LOW[_hi]
_M = {op + 302: meta for op, meta in _M_OLDBASE.items()}
_M.update(_M_LOW)
# op 0 is a genuine in-stream NO-OP / padding token, NOT a dead slot. Its dispatch entry is the
# shared ICF-folded return-0 stub (so it does nothing at runtime), but shipped cutscenes emit it
# 420x -- interspersed mid-scene (verified against the corpus: 410 mid / 10 leading / 0 trailing,
# 4 bytes, no operands). Curate it explicitly so it does not fall through to the "(unbound)"
# handler-name rule below, whose "the game's scripts never emit it" text is false for op 0.
_M[0] = ("nop", "noop",
         "No-op / padding token -- 4 bytes, no operands. Its dispatch slot is the shared return-0 "
         "stub, so it does nothing at runtime. Shipped cutscenes emit it inertly between statements "
         "(interspersed padding / alignment). Harmless to keep or delete.", [])

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
for _op in (94, 95, 96, 97):
    _M[_op] = ("SetSpeakerEmote", "dialogue",
               "Set the current dialogue speaker's facial emote/expression (from the actor's "
               "emote field) and retarget the portrait.", [])

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
    146: ("EquipItemToPlayer", "actor",
          "Scripted equip: force-equips item [item id] into the player's equip slot 1 "
          "(via Player_OnEquipChanged), if it can be held. Pairs with op 147 to restore.",
          ["item id"]),
    147: ("RestoreDefaultEquip", "actor",
          "Restore the player's default weapon and switch to idle -- undoes a scripted "
          "op-146 equip. No args.", []),
    148: ("QueryPlayerFlag40000", "query",
          "Query -> VM query register: 1 if the player has status/accessory-effect flag "
          "0x40000, else 0.", []),
    275: ("SetNpcPresenceState", "actor",
          "Set NPC [npc index] presence/companion state by [mode] (1 = add/set, -1 = "
          "remove/clear): toggles a global NPC-presence bit + the NPC's state bits "
          "(+52 bit 0x400000); on add also writes story flag 768.",
          ["npc index", "mode (1/-1)"]),
    282: ("QueryNpcPresent", "query",
          "Query -> VM query register: 1 if NPC [npc index]'s actor is spawned and not "
          "hidden (actor+568 & 0x20000000 clear), else 0.", ["npc index"]),
    300: ("AdvanceDay", "time",
          "Advance to the next day and reset all NPC schedules + AI "
          "(Day_AdvanceResetAllNpcSchedulesAndAi). No args.", []),
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
    375: ("TriggerWorldAction", "flow",
          "Fire a World_DispatchInteractionEvent by action id (see the "
          "TriggerWorldInteractionAction picker for the full list). Common ids: "
          "1 = Save menu, 2 = Load menu (dev-menu ONLY -- crashes mid-gameplay), "
          "3 = Message Board, 11 = Calendar, 12 = Storage, 23 = Fridge, 25 = "
          "BackupSaveNow (autosave), 45 = Bookshelf, 53 = Shipping Bin, 54 = Safe, "
          "55 = Wardrobe, 56 = Toolbox, 58 = Forge, 71 = Crafting.",
          ["action id"]),
    376: ("BeginShopkeeperInteraction", "flow",
          "**'Try to open shopkeeper NPC's shop, gated by their schedule.'** Same "
          "underlying dispatcher as TriggerWorldAction (op 375, "
          "World_DispatchInteractionEvent) but adds a **day-of-week eligibility "
          "check** on the shopkeeper's schedule first. Corpus proof: **all 192 "
          "vanilla call sites in rf3.mc pass a shop id (kinds 75-89)** — none use "
          "anything else. \\n\\nThe switch on arg 0 dispatches on the SHOPKEEPER's NPC "
          "ID and maps each to their day-off + a kind-override table: "
          "0 (generic/anon) -> kind 22 / day 6 (Sat); "
          "6 (Bado) / 9 (Arthur) / 10 (Porcoline) -> passthrough / day 0 (Sun); "
          "8 (Dylas) -> kind 23 if GF_FLG_DIRUS_FRIENDLY set, else 8 / day 0 (Sun); "
          "11 (Xiao Pai) / 12 (Lin Fa) -> passthrough / day 6 (Sat); "
          "13 (Amber) -> kind 25 if GameFlag 875 packed, else 13 / day 5 (Fri); "
          "14 (Illuminata) -> passthrough / day 5 (Fri); "
          "15 (Doug) -> kind 24 if Scene_EvalConditionByIdA(0x2D) true, else 15 / day 5 (Fri); "
          "16 (Blossom) -> passthrough / day 5 (Fri); "
          "17 (Dolce) / 18 (Jones) / 19 (Nancy) -> passthrough / day 1 (Mon); "
          "22/23 (Son/Daughter) -> kind 26 / day 6 (Sat); "
          "25 -> kind 21 / day 6 (Sat); "
          "default -> kind 26 / day 6 (Sat). \\n\\nDay-of-week check: today = "
          "`(g_calendarTask.cal_inner[+12] - 1) % 6`. If matched -> eligible "
          "(`g_interactionDailyEligible = 1`, `g_interactionDailyRollPassed = 0`). "
          "Else eligible=0 and roll a **deterministic MMIX-LCG (~1/63 chance)** "
          "using (shop_id + 0x4000, g_calendarDailyRandomSeed, calendar-snapshot) "
          "to set DailyRollPassed. The downstream shop task reads those globals "
          "to decide 'shop open normally' vs 'bonus lucky day' vs 'closed today, "
          "show closed-dialog instead'. Then World_DispatchInteractionEvent fires "
          "with arg 1 (shop id) in a1+25. arg 2 = mode (always 0 in vanilla).",
          ["shopkeeper npc", "shop id", "mode"]),
    377: ("GetChoiceResult", "query",
          "Consume and read the last PROMPT_CHOICE result: after a menu commits, this "
          "opcode reads the committed value into the VM query register.", []),
    378: ("GetChoiceResult", "query",
          "Consume and read the last PROMPT_CHOICE result (dupe of op 377).", []),
    445: ("GetFlagBit", "query",
          "Query -> VM query register: 1 if game-flag bit [flag id] is set, else 0. "
          "The id is ZONE-2 RELATIVE: the handler tests absolute bit 4096 + id (it adds the "
          "buffer's zone2_base), the same numbering as ops 443/444 and MOBJ f13 -- NOT the "
          "emdeb/emflags (zone-1) table. Known blocks: emflags.ZONE2_BLOCKS.",
          ["flag id"]),
    617: ("Staff_SpawnScreenOrFade", "effect",
          "Spawn / configure the 'staff' overlay task (reuses the item-pickup icon "
          "framework as a scrollable staff-credits driver). Called 4 times by the dev "
          "menu: 0 = Fade (long), 1 = Fade (short), 2 = Credits screen (bottom), "
          "3 = Credits screen (top).",
          ["mode"]),
    697: ("ReturnToTitle", "flow",
          "Kick off the return-to-title sequence via app relaunch. Dev menu uses this "
          "after FadeScreen(16, 1500) + WaitForFade. No args.", []),
})

# ---- cutscene-beat + fade + audio ops decoded 2026-07-07 (from bank 292 @0x0878 test menu) ---
# Bank 292 @0x0878 is the 25-choice ＊Confirm Motion / ＊Ackna Battle / ... test menu; each
# branch fires PlayScriptedBeat with a distinct (actor_ctx, id1, id2, kind_id) tuple.
_M.update({
    332: ("PlayScriptedBeat", "flow",
          "Launch a **4-param scripted beat / cutscene event** on an actor. Writes the "
          "four u16 args into the action task's config slots (+60..+66) and commits (bit "
          "0x80 at +56). arg3 (`kind_id`) drives a range gate on +57: 1000-1099 -> bit 0 "
          "(credit-roll-scale variant), 100-999 or 1100-4194 -> bit 1 (scripted-event "
          "variant), else -> both clear (normal). Also clears g_gameGlobalsSlotTable entry "
          "4 low nibbles, clears sceneControlFlags bit 0x100000, flags the current "
          "dialogue task, and **prunes any pending g_gameEventQueue events of types 20 / "
          "24 / 28 / 30** (mask 0x41100000 -- the persistent-state event types). Vanilla "
          "use: 'Ackna Battle' fires (globalvar[0x2D5], 403, 453, 0), 'Ending (Plaza 2nd "
          "Run)' fires (globalvar[0x30], 8, 347, 130), 'Credit Roll 3' fires "
          "(globalvar[0x94], -96, 0, 1200), etc.",
          ["actor ctx", "arg1", "arg2", "kind id"]),
    335: ("FadeScreenToClear", "screen",
          "Fade the screen overlay back toward CLEAR (target alpha 0 = fully transparent, "
          "revealing the scene) over arg0/100 frames -- the reveal counterpart of op 334 "
          "FadeScreen. Re-launches the current dual-screen fade task on both channels toward "
          "alpha 0 via FadeTask_Init(0.0, arg0/100, channel), keeping the current overlay colour. "
          "CORRECTION: earlier called 'FadeChangeKindOnly' with a 'kind' arg -- verified the single "
          "arg is the DURATION (feeds FadeTask_Init's frame_count) and the target is always clear, "
          "NOT a kind selector. Corpus arg values (6000/12000/18000...) match op334's durations.",
          ["duration (frames = arg0/100; 6000 ~= 1s)"]),
    383: ("SetSfxDuckingBypass", "audio",
          "Set the SFX-capture / audio-ducking bypass flag on `g_sfxCaptureActive[+9]` "
          "(writes `arg != 0`). Used to **temporarily disable SFX ducking during "
          "cutscenes** so scripted BGM plays at full volume without being auto-lowered by "
          "an active NPC bubble / dialog.",
          ["enable"]),
})

# ---- ops from bank 21 NPC-debug scene (2026-07-07) ----
# 6 more high-frequency uncurated ops named by RE'ing their handlers.
_M.update({
    208: ("HandOrDropItem", "actor",
          "**Cutscene 'NPC hands you a gift' primitive.** Spawns an item visual "
          "and attaches it to either an NPC's hand or the player. "
          "**arg 0 = target**: 0 = give to player (either attach to hand OR "
          "drop on ground if player has status 0x4000 / secondary_mod in the "
          "'item-blocked' range 1..0x453 — plays Sfx 0x100226D + fires "
          "Action_TriggerActor(0x13)). >0 = NPC slot index (looked up via "
          "g_gameGlobalsSlotTable), then `Item_SpawnVisualTask` + "
          "`Npc_AttachHeldItem`. **arg 1 = item_id** masked to 11 bits (0..2047). "
          "The item metadata is loaded from `g_itemDatabase` (recipe metadata "
          "copied via 5-byte stride).",
          ["target npc (0=player)", "item id"]),
    217: ("ApplyFriendshipDelta", "actor",
          "Modify an NPC's friendship XP or absolute friendship. **3 args**: "
          "npc_id, op_kind, xp_or_value. Op-kind dispatch: "
          "**4 = ADD** (`Npc_AddFriendshipXpAndProcessLevelUp(npc, +xp)`); "
          "**5 = SUBTRACT** (`... , -xp)`); "
          "**6 = SET absolute** (`Npc_SetFriendshipPointsAbsoluteAndCheckMaxAchievement(npc, value)`). "
          "**Special: npc_id == 22 → dynamically resolves to the CHILD NPC id** "
          "via `GameFlags_ReadField(0, GF_REG_CHILD_ID, 5)`. That confirms slot "
          "22 = Son is the runtime child-actor slot (paired with slot 23 = Daughter). "
          "Dev-menu debug branch uses this with (npc_id, 6, 99999999) = instant "
          "MAX friendship to unlock date/marriage flow.",
          ["npc id", "op kind (4=add, 5=sub, 6=set)", "xp/value"]),
    242: ("SetSceneFlag0x200", "flow",
          "Set bit 0x200 in the scene ctx's result/control field at [+116] (if ctx+32 "
          "is non-null; +116 is the same field Script_VMStep sets to 1 on halt). In the "
          "corpus (703 uses) it is almost always `BR_Z(guard) -> SetSceneFlag0x200 -> END` "
          "-- set CONDITIONALLY at the very end of a scene branch, right before the scene "
          "ends. So it marks a scene OUTCOME bit the caller reads after the scene returns "
          "(e.g. 'this branch was taken / handled'). The gating guard is usually a per-NPC "
          "sub-event flag (`FLG_SUB_T_*`) or `FLG_JUST_MARRIED_MODE`, so in practice it "
          "flags a marriage / sub-event scene branch as consumed. The exact outcome bit is not "
          "pinned, but it is set at scene-EXIT, not during dialogue -- an earlier 'blocks input "
          "while dialogue is active' guess was wrong, contradicted by the usage pattern.",
          []),
    362: ("GetNpcBirthdayMonthAndDay", "query",
          "Read NPC #arg1's birthday from calendar archive 16340. Format: "
          "archive record = 4 bytes each: [+0]=npc_id, [+1]=month (1..4 = "
          "RF4 season month), [+2]=day, [+3]=unused. Walks records at "
          "archive+28 (count at archive+24) until matching npc_id found. "
          "**Writes** the packed calendar code `day + 100*month` to "
          "var-array-kind-9 at [arg 0], and separately writes month to "
          "ctx[+64] + day to ctx[+68]. Silently defaults to (0, 0) if the "
          "NPC is not in the archive.",
          ["kind9 slot", "npc id"]),
    363: ("GetEventMonthOrBirthFlag", "query",
          "Like op 362 but reads only the MONTH byte from calendar archive "
          "16340 for a given event_id. **Fallback when arg 1 = 0**: reads "
          "player's birth season/day from GameFlags (GF_REG_PLAYER_BIRTH_SEASON "
          "2-bit + GF_REG_PLAYER_BIRTH_DAY 5-bit). "
          "Writes result + **616** (a festival-ID base offset) into var-array-"
          "kind-0 at [arg 0]; also writes day into var-array-kind-3 and "
          "ctx[+64]/[+68]. Used to compute 'this event's festival id' for "
          "downstream lookups.",
          ["kind0 slot", "event id (0=player birthday)"]),
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
    1:   ("SetSceneCtxBit3FromArg", "flow",
          "Copies bit 0 of arg into bit 3 (0x8) of the scene ctx's control field "
          "at +120. `ctx[+120] = (ctx[+120] & ~8) | ((arg & 1) << 3)`. Author use "
          "unknown; likely a scene mode flag toggle.",
          ["value"]),
    173: ("MarkCalendarEventCancelled", "actor",
          "Find the calendar-event record with matching event_id (low-16 match "
          "in `g_calendarEventMng_20wPerRecord`) and OR 0x80 into its +564 "
          "field -- the 'cancelled/expired' flag. Returns 1 if the event id "
          "wasn't found in the current table.",
          ["event id"]),
    193: ("SetCameraAnchorToPlayer", "screen",
          "Anchor the scene camera (handler Script_VMOp_SetCameraAnchorToPlayerOrTarget). "
          "Always sets camera-mode bit 0x40000 on ctx+116, then branches on arg: "
          "(0) anchor the camera to the player -- as a side effect this also "
          "snapshots the player's world position into the script 'mark' "
          "(g_scriptMarkAnchorPosQ12) and writes the tile (x, y) into the current "
          "map task's work_buffer[+11]/[+12]; (non-0) refresh the camera toward "
          "the current target actor. Ends with Camera_ComputeDistanceVectorToTarget. "
          "The mark it records in mode 0 is what QueryPlayerMovedBeyondSnapshot "
          "(op 196) reads to detect whether the player has moved.",
          ["mode (0 = anchor to player + set movement mark, else refresh to target)"]),
    196: ("QueryPlayerMovedBeyondSnapshot", "query",
          "Query -> VM register: 1 if the player's world position has moved "
          "more than `arg << 12` (Q4.12 tiles) from the last op-193 snapshot "
          "in EITHER axis; 0 otherwise. Pair with op 193 as a "
          "'watch for the player leaving a set radius' construct.",
          ["threshold"]),
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
    229: ("QueryNpcAvailableFlagClear", "query",
          "Query -> VM register: 1 if NPC's state word (npc[+20]) bit 0x40 is "
          "CLEAR, else 0. Bit 0x40 is presumably an 'is busy' or 'in scene' "
          "marker; the op returns TRUE when the NPC is FREE. Silently no-ops "
          "for npc id >= 48.",
          ["npc id"]),
    232: ("QueryNpcProbeStateAt7300", "query",
          "Query -> VM register: result of `sub_7FF6F5DD7300(npc_id)` -- an "
          "NPC-state probe helper (not yet fully RE'd; likely queries "
          "friendship / event availability). Only fires for npc id < 48.",
          ["npc id"]),
    245: ("QueryGiftAffinity", "query",
          "Query -> VM register: "
          "`Npc_GetGiftAffinityHashByItemAndCharId(npc_id, {item_id & 0x7FF})`. "
          "Returns the NPC's gift-affinity hash for the given item -- values "
          "like 'loved / liked / disliked / hated' as per rf3PresentNpc (see "
          "the gift preferences memory). item_id is masked to 11 bits (0..2047).",
          ["npc id", "item id"]),
    265: ("QueryPlayerDeadOrCompanionScripted", "query",
          "Dual-mode query -> VM register based on arg: "
          "(arg != 0) writes 1 if the player is currently dead (vtable[+7] == "
          "Player_DeathTickCallback), else 0. "
          "(arg == 0) walks companions 0..1 and writes 1 if any companion has "
          "`companion[+460] == 11` with a null `[+304]` field (a 'scripted "
          "sequence in progress' state), else 0.",
          ["mode"]),
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
    291: ("SpawnCalendarEventByChildNum", "actor",
          "Spawn a special calendar-event record whose count is derived from the "
          "player's current child count (was previously named ...ByGameFlagDC -- "
          "the IDA-clarified name reflects that the switch is on child count, "
          "not a game flag). Used to schedule pregnancy/birth follow-ups.",
          []),
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
          "Shop_SetMessageTextFromArchive(arg): loads locale text archive 15206 "
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
    400: ("SetPlayerLestOrFrey", "actor",
          "Switch the player character between **Lest (male / arg=1)** and "
          "**Frey (female / arg=0)**. Calls `Player_SetCharacterVariantLestOrFrey`, "
          "refreshes equipped sprites + scene state, zeros the save-snapshot scratch, "
          "and reloads the greeting string from archive 16369 (NPC name archive): "
          "arg=1 -> entry 0 (title greeting), arg=0 -> entry 599 (default 'Frey' name). "
          "**Formerly named `RefreshPlayerAndApplyDefaultName` -- the technical name "
          "hides that this is the actual character-swap op**. Dev menu label: 'Boy' / "
          "'Girl'.",
          ["gender (1=Lest/Boy, 0=Frey/Girl)"]),
    693: ("nop", "noop",
          "**No-op stub in the PC port** (ICF-folded `return 0;` with ~379 xrefs "
          "in the binary). Bank 292 @0x0888 fires it with args 2..18, 100/101, 221 as "
          "if toggling dev flags ('Scenario Clear Flag ON', 'Marriage Flag ON', "
          "'Movie flags OFF', ...), but the actual side-effect was stripped. The "
          "dev-menu dialog messages ('Marriage Flag has been set to +ON+') still print, "
          "but nothing happens. Was likely a 3DS-era dev-flag setter. Safe to keep, "
          "delete, or rewrite -- it does nothing on PC.",
          []),
})

# op 379 PlayMusic already has a decent mnemonic from the fallback -- override with a
# proper curated description.
_M[379] = ("PlayMusic", "audio",
    "Switch background music with a crossfade. **arg = -1 restores the contextual BGM** "
    "(clears the scripted-BGM marker bit 0x10000000 at ctx+116, calls "
    "Scene_ApplyContextualBGM). Otherwise starts BGM #arg via BGM_SwitchWithCrossfade and "
    "sets the scripted-BGM marker so the contextual picker won't override it. Also sets the "
    "'first scripted BGM played' game-flag (packed id 1072, via GameFlags_WritePacked) -- an "
    "internal milestone flag, not a Steam achievement. Special case: `arg == 16777332` triggers "
    "an additional Sfx_ApplyVoiceVolume with category-bias 45.",
    ["bgm id (or -1 = restore)"])

# ---- camera ops decoded 2026-07-11 (ops 186-203; handlers RF4S.exe+0x20b150..0x20c2f0) ----
# All camera anchors are stored as Q12 world coords (arg tiles << 12) in g_scriptMarkAnchorPosQ12;
# most first set receiver flag 0x40000 ("script touched the camera this frame"). Player-lock
# helpers Player_SetActorFlag1/4 stop the player drifting while the camera is scripted.
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
    188: ("SnapCameraToPlayer", "screen",
          "Recenter the camera on the player. arg != 0 snaps the anchor to the player's tile "
          "instantly (and updates the map scroll origin); arg == 0 eases the follow vector "
          "toward the player.",
          ["instant (0=ease, 1=snap)"]),
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
    191: ("ResetCameraToActor", "screen",
          "Re-attach the camera to the player(s) and center on an actor. BLOCKING: returns busy "
          "until a ~3-frame settle completes. arg0 = actor scene-slot (0 = player). arg1 = mode: "
          "0 -> hard-snap the anchor to the actor, -1 -> attach only (no recompute), any other "
          "value -> ease toward the actor.",
          ["actor slot (0=player)", "mode (0=snap, -1=attach only, else ease)"]),
    192: ("ResetCameraToActor", "screen",
          "Alias of op 191 (same handler): re-attach + center the camera on an actor, blocking "
          "until a ~3-frame settle completes.",
          ["actor slot (0=player)", "mode (0=snap, -1=attach only, else ease)"]),
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
    200: ("SetCameraTargetActor", "screen",
          "Alias of op 199 (same handler): pan the camera to an actor by scene-slot. arg1 = the "
          "same pan-speed channel as op 199 (shipped scenes use 400-800 here = 4..8 tiles/frame).",
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
    77: ("SetActorFacingAngle", "actor",
         "Point an actor at a target facing angle. arg0 = actor (char id, 0 = player). "
         "arg1 = turn rate/mode written to the motion turn field (high bit 0x8000 = ease "
         "into it instead of snapping). arg2 = target facing angle in degrees. Op 79 is the "
         "same but ADDS to the turn field instead of setting it.",
         ["actor (char id, 0=player)", "turn rate (bit 0x8000 = ease)", "angle (degrees)"]),
    78: ("SetActorFacingAngle", "actor",
         "Alias of op 77 (same handler): set an actor's target facing angle + turn rate.",
         ["actor (char id, 0=player)", "turn rate (bit 0x8000 = ease)", "angle (degrees)"]),
    79: ("SetActorTurnAngle", "actor",
         "Nudge an actor's turn: ADDS arg1 to the motion turn-rate field (op 77 sets it) and "
         "aims the actor at arg2 degrees. arg0 = actor (char id, 0 = player); arg1 high bit "
         "0x8000 = ease vs snap.",
         ["actor (char id, 0=player)", "turn delta (bit 0x8000 = ease)", "angle (degrees)"]),
    80: ("SetActorTurnAngle", "actor",
         "Alias of op 79 (same handler): add to an actor's turn rate + aim it at an angle.",
         ["actor (char id, 0=player)", "turn delta (bit 0x8000 = ease)", "angle (degrees)"]),
    99: ("TeleportActor", "actor",
         "Instantly warp an actor to a tile. arg0 = actor (char id, 0 = player). arg1/arg2 = "
         "destination X/Y in tiles. The player is snapped to the ground; an NPC is streamed "
         "in if needed. No walk animation — use the Move* ops for a visible walk.",
         ["actor (char id, 0=player)", "x (tiles)", "y (tiles)"]),
    100: ("TeleportActor", "actor",
          "Alias of op 99 (same handler): instantly warp an actor to a tile.",
          ["actor (char id, 0=player)", "x (tiles)", "y (tiles)"]),
    107: ("TurnActorToFaceTarget", "actor",
          "Rotate one actor to look at another — the workhorse for 'actors face each other "
          "before dialogue'. arg0 = turner (0 = player, 1..47 = villager, >=48 = monster). "
          "arg1 = look-at target (same encoding). arg2 = mode: 0 = snap instantly, non-zero "
          "= ease/lerp toward it.",
          ["turner (char id, 0=player)", "look-at target (char id)", "mode (0=snap, else ease)"]),
    108: ("TurnActorToFaceTarget", "actor",
          "Alias of op 107 (same handler): turn an actor to face another actor.",
          ["turner (char id, 0=player)", "look-at target (char id)", "mode (0=snap, else ease)"]),
    109: ("TurnActorToFaceTarget", "actor",
          "Alias of op 107 (same handler): turn an actor to face another actor.",
          ["turner (char id, 0=player)", "look-at target (char id)", "mode (0=snap, else ease)"]),
    115: ("MoveActorByOffset_LockAI", "actor",
          "Walk an actor by a RELATIVE tile offset, then LOCK its AI so nothing interrupts "
          "the pose (used when actors slide into staged cutscene positions and must hold). "
          "Faces the given angle. args: actor (0=player), dx, dy (tiles), facing degrees, "
          "speed, jump flag.",
          ["actor (char id, 0=player)", "dx (tiles)", "dy (tiles)", "facing (degrees)", "speed", "jump (0/1)"]),
    116: ("MoveActorByOffset_LockAI", "actor",
          "Alias of op 115 (same handler): relative move + face + lock AI.",
          ["actor (char id, 0=player)", "dx (tiles)", "dy (tiles)", "facing (degrees)", "speed", "jump (0/1)"]),
    117: ("MoveActorByOffset_LockAINoFace", "actor",
          "Like op 115 (relative move + lock AI) but does NOT update the actor's facing — it "
          "keeps whatever direction it had. args: actor (0=player), dx, dy, (facing ignored), "
          "speed, jump flag.",
          ["actor (char id, 0=player)", "dx (tiles)", "dy (tiles)", "facing (ignored)", "speed", "jump (0/1)"]),
    118: ("MoveActorByOffset_LockAINoFace", "actor",
          "Alias of op 117 (same handler): relative move + lock AI, no facing change.",
          ["actor (char id, 0=player)", "dx (tiles)", "dy (tiles)", "facing (ignored)", "speed", "jump (0/1)"]),
    123: ("MoveActorByOffset", "actor",
          "Basic cutscene walk: move an actor by a RELATIVE tile offset and face the given "
          "angle (no AI changes). args: actor (0=player), dx, dy (tiles), facing degrees, "
          "speed, jump flag.",
          ["actor (char id, 0=player)", "dx (tiles)", "dy (tiles)", "facing (degrees)", "speed", "jump (0/1)"]),
    124: ("MoveActorByOffset", "actor",
          "Alias of op 123 (same handler): relative move + face, no AI changes.",
          ["actor (char id, 0=player)", "dx (tiles)", "dy (tiles)", "facing (degrees)", "speed", "jump (0/1)"]),
    125: ("MoveActorByOffset_InterruptAI", "actor",
          "Force-reposition: PRE-CLEARS the actor's AI state, then moves it by a RELATIVE "
          "tile offset (no facing update). Use to yank an actor out of its routine before a "
          "scene. args: actor (0=player), dx, dy, (facing ignored), speed, jump flag.",
          ["actor (char id, 0=player)", "dx (tiles)", "dy (tiles)", "facing (ignored)", "speed", "jump (0/1)"]),
    126: ("MoveActorByOffset_InterruptAI", "actor",
          "Alias of op 125 (same handler): interrupt-AI relative reposition.",
          ["actor (char id, 0=player)", "dx (tiles)", "dy (tiles)", "facing (ignored)", "speed", "jump (0/1)"]),
    127: ("MoveActorByOffset_Continue", "actor",
          "Continuation move: relative tile offset, no facing update, no AI changes — chains "
          "after another Move to extend a walk. args: actor (0=player), dx, dy, (facing "
          "ignored), speed, jump flag.",
          ["actor (char id, 0=player)", "dx (tiles)", "dy (tiles)", "facing (ignored)", "speed", "jump (0/1)"]),
    128: ("MoveActorByOffset_Continue", "actor",
          "Alias of op 127 (same handler): continuation relative move.",
          ["actor (char id, 0=player)", "dx (tiles)", "dy (tiles)", "facing (ignored)", "speed", "jump (0/1)"]),
    119: ("NpcWalkToTile", "actor",
          "Walk an NPC to an ABSOLUTE tile. arg0 = npc char id (<48). arg1/arg2 = target X/Y "
          "in tiles. arg3 = speed coefficient. arg4 = run flag (0 = walk, non-zero = run at "
          "1.2x). Sets the NPC's 'moving' flag; unlike the Move*ByOffset ops this takes an "
          "absolute destination, not a delta.",
          ["npc (char id)", "x (tiles)", "y (tiles)", "speed", "run (0/1)"]),
    120: ("NpcWalkToTile", "actor",
          "Alias of op 119 (same handler): walk an NPC to an absolute tile.",
          ["npc (char id)", "x (tiles)", "y (tiles)", "speed", "run (0/1)"]),
    133: ("PlayActorAnim", "actor",
          "Play an action/animation on an actor. arg0 = actor (char id, 0 = player). arg1 = "
          "anim/action id -- an index into that actor's own animation archive, so the same id "
          "can be a different animation on different characters (no global id->name list); "
          "verify per character. arg2 non-zero marks it as a held scripted pose (and, for the "
          "player, begins a scripted-talk interaction). Pair with QueryActorAnimBusy (op 129) "
          "to wait for it.",
          ["actor (char id, 0=player)", "anim id (per-character archive)", "hold pose (0/1)"]),
    134: ("PlayActorAnim", "actor",
          "Alias of op 133 (same handler): play an action animation on an actor.",
          ["actor (char id, 0=player)", "anim/action id", "hold pose (0/1)"]),
    142: ("MoveSceneActorToTile", "actor",
          "Move the scene-controlled actor (the player) to an ABSOLUTE tile, with facing. "
          "arg0/arg1 = X/Y tiles, arg2 = facing degrees, arg3 = speed, arg4 = run flag "
          "(0 = walk, non-zero = run). No char-id arg — always the scene's own actor.",
          ["x (tiles)", "y (tiles)", "facing (degrees)", "speed", "run (0/1)"]),
})


# ---- actor effects / triggers / rotation decoded 2026-07-11 (ops 83-151, second pass) ----
_M.update({
    83: ("CloseDialogueBubbles", "dialogue",
         "Close the on-screen dialogue bubble(s) and BLOCK the scene until the close "
         "animation finishes. arg selects which: 0 = both speaker bubbles, 1/other = one "
         "side. Use before switching speakers or ending a conversation cleanly.",
         ["which (0=both)"]),
    101: ("PlaceOrFaceActor", "actor",
          "Dual-purpose: with X and Y given, TELEPORT an actor to that tile (like op 99); "
          "with only an actor id + angle, just set its facing. arg0 = actor (char id, "
          "0 = player). arg1/arg2 = X/Y tiles (place mode). arg3 = facing degrees "
          "(face-only mode). Player is re-snapped to the ground on placement.",
          ["actor (char id, 0=player)", "x (tiles)", "y (tiles)", "facing (degrees)"]),
    102: ("PlaceOrFaceActor", "actor",
          "Alias of op 101 (same handler): teleport an actor to a tile, or set its facing.",
          ["actor (char id, 0=player)", "x (tiles)", "y (tiles)", "facing (degrees)"]),
    111: ("SetActorRotationRaw", "actor",
          "Instantly SNAP an actor's facing to an angle — no turn animation, no easing. "
          "arg0 = actor (char id, 0 = player). arg1 = facing degrees (converted ×181 to the "
          "u16 rotation, 65536 = 360°). Contrast op 77 SetActorFacingAngle, which turns via "
          "the motion/ease field.",
          ["actor (char id, 0=player)", "facing (degrees)"]),
    112: ("SetActorRotationRaw", "actor",
          "Alias of op 111 (same handler): instantly snap an actor's facing angle.",
          ["actor (char id, 0=player)", "facing (degrees)"]),
    139: ("ApplyEffectToActor", "effect",
          "Apply an Effect (damage / heal / status / VFX) to an actor via "
          "Effect_ApplyByKindAndSpawn — the scripted-effect entry point. arg0 = actor "
          "(char id, 0 = player). arg1 = effect kind id (dispatched by g_effectKindSpawnTable "
          "to spawn the visual + apply the gameplay effect). Used for scripted magic, "
          "sparkles, heals, and status in cutscenes.",
          ["actor (char id, 0=player)", "effect kind id"]),
    140: ("ApplyEffectToActor", "effect",
          "Alias of op 139 (same handler): apply an effect kind to an actor.",
          ["actor (char id, 0=player)", "effect kind id"]),
    141: ("SetActorInvulnerable", "actor",
          "Toggle an actor's scripted invulnerability guard. arg0 = actor (char id, "
          "0 = player). arg1 has INVERTED polarity: arg1 == 0 turns the guard ON (sets the "
          "armor-guard bit); arg1 != 0 turns it OFF and clears the invuln overlay tint. "
          "Wrap scripted-combat cutscenes so staged actors can't be killed.",
          ["actor (char id, 0=player)", "guard (0 = invulnerable ON, non-zero = OFF)"]),
    144: ("MoveSceneActorStraight", "actor",
          "Move the scene-controlled actor (the player) in a straight line to an ABSOLUTE "
          "tile, KEEPING its current facing (no turn). arg0/arg1 = X/Y tiles, arg2 = speed, "
          "arg3 = run flag (0 = walk, non-zero = run). Like op 142 but without a facing arg.",
          ["x (tiles)", "y (tiles)", "speed", "run (0/1)"]),
    149: ("PlayerScriptedTalkAnim", "dialogue",
          "Put the player into a scripted-talk pose and play an animation on them — for "
          "gestures during dialogue (nod, bow, shrug). arg0 = anim id (-1 = the default "
          "'standard talk' anim 187). arg1 non-zero sets the anim-trigger-active bit.",
          ["anim id (-1 = default talk)", "trigger flag (0/1)"]),
    150: ("TriggerActionAtTile", "effect",
          "Spawn a scripted Action (effect/task) at a world tile via Action_TriggerActor "
          "(g_actionConstructorTable dispatch — the 'Action 0xNN' family). arg0 = action id. "
          "arg1/arg2 = X/Y tiles. Action ids 65 and 105 auto-target the player's position "
          "instead of the passed tile.",
          ["action id", "x (tiles)", "y (tiles)"]),
    151: ("TriggerActorAttack", "effect",
          "Make an actor perform a combat attack move (as_atk timeline) from its current "
          "position, via Action_TriggerAttacker. arg0 = attack id. arg1 = attacker (char id, "
          "0 = player). Used for scripted combat in cutscenes (boss demos, story fights).",
          ["attack id", "attacker (char id, 0=player)"]),
})


# ---- actor 'wait-for' query ops decoded 2026-07-11 (81-152) — used in cutscene wait-loops ----
# These write a boolean to the VM query register (read via a following BR_Z/BR_NZ). The common
# cutscene idiom is: start a Move/Turn/Anim, then loop on the matching Query until it reports done.
_M.update({
    81: ("QueryActorMotionState", "query",
         "1 while the actor is mid-motion — its motion-state code (motion+42 & 0x7C) is NOT "
         "the settled/idle value 0x10; 0 once settled. arg0 = actor (matched against the "
         "scene's two participant slots). Wait-for-move-done predicate.",
         ["actor (char id, 0=player)"]),
    82: ("QueryActorMotionState", "query",
         "Alias of op 81 (same handler): 1 while the actor is mid-motion, 0 when settled.",
         ["actor (char id, 0=player)"]),
    113: ("QueryActorRotating", "query",
          "1 while the actor is still turning toward its target facing (current rotation != "
          "target rotation); 0 once the turn has settled. arg0 = actor (char id, 0 = player). "
          "Pair with SetActorFacingAngle / TurnActorToFaceTarget to wait for the turn.",
          ["actor (char id, 0=player)"]),
    114: ("QueryActorRotating", "query",
          "Alias of op 113 (same handler): 1 while the actor is still turning, 0 when settled.",
          ["actor (char id, 0=player)"]),
    129: ("QueryActorAnimBusy", "query",
          "1 while the actor is still playing its scripted action animation OR turning; 0 "
          "once idle/done. arg0 = actor (char id, 0 = player, which delegates to "
          "QueryPlayerTurnBusy). Pair with PlayActorAnim (op 133) to wait for the anim to "
          "finish. (Handler is named 'AnimDone' but returns busy=1.) ONLY arg0 IS READ: 72 of the 2,072 "
          "shipped statements pass extra actors, but Script_VMOp_QueryNpcAnimDone never looks "
          "past arg0 (verified 2026-09-23), so the wait ends as soon as the FIRST actor is idle. "
          "To wait on several actors, use one statement per actor.",
          ["actor (char id, 0=player)", "ignored actor … (not read by the engine)"]),
    130: ("QueryActorAnimBusy", "query",
          "Alias of op 129 (same handler): 1 while the actor's anim/turn is still playing. "
          "Only arg0 is read; extra actors are ignored.",
          ["actor (char id, 0=player)", "ignored actor … (not read by the engine)"]),
    131: ("QueryActorBeyondRange", "query",
          "1 while the actor is FARTHER than [range] tiles from its target marker (the "
          "player checks a global target position; an NPC checks its own move target); 0 "
          "once within range. arg0 = actor (char id, 0 = player), arg1 = range in tiles. "
          "Wait-until-arrived predicate. (Handler is named 'InRange' but returns 1 when far.)",
          ["actor (char id, 0=player)", "range (tiles)"]),
    132: ("QueryActorBeyondRange", "query",
          "Alias of op 131 (same handler): 1 while the actor is beyond [range] of its target.",
          ["actor (char id, 0=player)", "range (tiles)"]),
    135: ("QueryActorTilePosition", "query",
          "Read an actor's current tile position: writes X and Y (tiles) to the VM output "
          "slots for a following read. arg0 = actor (char id, 0 = player). Falls back to the "
          "NPC's backup position if its actor isn't spawned.",
          ["actor (char id, 0=player)"]),
    136: ("QueryActorTilePosition", "query",
          "Alias of op 135 (same handler): read an actor's tile X/Y into the VM output slots.",
          ["actor (char id, 0=player)"]),
    137: ("QueryNpcLoadedAndActive", "query",
          "1 if the NPC exists, has a live actor, and is NOT in its idle state (i.e. is "
          "currently doing something); 0 otherwise. arg0 = npc (char id, <48). Gate scripted "
          "branches on whether an NPC is present and active.",
          ["npc (char id)"]),
    138: ("QueryNpcLoadedAndActive", "query",
          "Alias of op 137 (same handler): 1 if the NPC is loaded and active.",
          ["npc (char id)"]),
    145: ("QueryPlayerTurnBusy", "query",
          "1 while the player is still turning / settling their facing (or in a scripted-busy "
          "state); 0 when idle. No args. Wait for the player's turn to finish before the next "
          "beat.",
          []),
    152: ("QueryPlayerScriptReady", "query",
          "1 when the player is ready for the next scripted action — no scripted-talk or "
          "scripted-anim is in progress (scene bit 0x8000000 clear and the player's "
          "scripted-anim bit clear); 0 while busy. No args.",
          []),
})


# ---- calendar-event-actor family decoded 2026-07-11 (ops 153-182) ------------------
# "Event actors" are the festival / parade / cutscene NPCs registered in g_calendarEventMng
# (a 32-slot registry, 40-byte stride). SpawnNpc (op 153) adds one keyed by its char id; the
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
          "id, char id' labels were swapped): ScriptVMOp_CalendarEvent_SpawnOrUpdateNpcAtTilePos "
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
          "WaitForEventActorReady (op 169) to wait for a one-shot anim to finish.",
          ["event key", "anim id", "loop (0/1)"]),
    169: ("QueryEventActorReady", "query",
          "1 when the event actor has finished its current action and is ready for the next; "
          "0 while mid-action. arg0 = event key. Also returns 1 if the key isn't "
          "found. Wait-for-action-complete predicate for event actors.",
          ["event key"]),
    171: ("SetEventActorAlpha", "actor",
          "Fade a spawned event actor: arg1 = alpha percent 0..100 (packed into the sprite's "
          "5-bit alpha). arg1 == 0 HIDES the actor (sets its hide flag). arg0 = event key "
          "(char id). Used for ghost/translucent/fade-in-out cutscene effects.",
          ["event key", "alpha % (0-100, 0=hide)"]),
    178: ("SetEventActorTargetFacing", "actor",
          "Set a spawned event actor's TARGET facing angle; the NPC tick interpolates its "
          "current facing toward it (a smooth turn). arg0 = event key, arg1 = "
          "facing degrees (×181 → u16). (The handler's name says 'DirIndex' but the math is "
          "plain degrees, matching every other facing op.)",
          ["event key", "facing (degrees)"]),
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
    163: ("FaceEventActorTowardTarget", "actor",
          "Rotate a spawned event actor to look at another entity — the event-actor twin of "
          "TurnActorToFaceTarget (op 107). arg0 = event key (the actor that turns). "
          "arg1 = look-at target (0 = player, 1..47 = NPC, 48+ = event actor). arg2 = mode "
          "(0 = snap, non-zero = ease/lerp).",
          ["event key", "look-at target (char id)", "mode (0=snap, else ease)"]),
    166: ("ApplyEffectToEventActor", "effect",
          "Apply an Effect (damage / heal / status / VFX) to a spawned event actor via "
          "Effect_ApplyByKindAndSpawn — the event-actor twin of op 139. arg0 = event key "
          "(char id), arg1 = effect kind id.",
          ["event key", "effect kind id"]),
    181: ("DismissEventActor", "actor",
          "Cleanly despawn a spawned event actor — NO death animation (contrast op 180 "
          "KillEventActor). arg0 = event key. Runs the canonical companion-dismiss "
          "reset and decrements the event-companion count; the player can't be dismissed.",
          ["event key"]),
})


# ---- calendar-event-actor family, 3rd pass 2026-07-11 (155-183) --------------------
_M.update({
    155: ("EventSpawnNpcFollower", "actor",
          "Spawn an event NPC that trails at a follow speed — always claims a NEW registry "
          "slot. arg0 = char id (which character/model), arg1 = event key (the scene-local "
          "handle — SAME char/key order as ops 153/154, IDA-verified 2026-08-18: "
          "ScriptVMOp_CalendarEvent_AddNpcWithFollowSpeedAndFlag stores arg0 in the char word "
          "and arg1 in the key word), arg2/arg3 = X/Y tiles, arg4 = facing degrees, arg5 = "
          "behaviour flag byte (packed at record WORD5), arg6 = follow-speed multiplier "
          "(stored as value × 0.01). Use for a companion/tag-along that keeps pace during a "
          "scene.",
          ["char id (model)", "event key (scene-local handle)", "x (tiles)", "y (tiles)",
           "facing (degrees)", "behaviour flag", "follow speed"]),
    165: ("TriggerActionAtEventActor", "effect",
          "Spawn a scripted Action (VFX / SFX / trigger) at a spawned event actor's position "
          "via Action_TriggerAttacker. arg0 = event key, arg1 = action id. The "
          "event-actor counterpart of TriggerActionAtTile (op 150).",
          ["event key", "action id"]),
    174: ("AddActorVerticalVelocity", "actor",
          "Add a vertical velocity impulse to an actor — a scripted hop/jump or a downward "
          "burst. arg0 = target (0 = player, 1..48 = NPC, 48+ = event key). arg1 = velocity "
          "(positive = up). If the actor lacks the jump flag the result is clamped to "
          "non-upward (so it can only fall, not launch).",
          ["actor (0=player, 1-48=NPC, 48+=event key)", "velocity (up if jump-enabled)"]),
    176: ("SetEventActorGreyscale", "actor",
          "Tint a spawned event actor's sprite toward greyscale/monochrome (all three colour "
          "channels set equal). arg0 = event key, arg1 = grey level (scaled ×40.96 "
          "internally; lower = darker/dimmer). For flashbacks, petrification, dark-mood "
          "scenes.",
          ["event key", "grey level (lower = darker)"]),
    179: ("QueryEventActorTurning", "query",
          "1 while a spawned event actor is still turning toward its target facing "
          "(target != current); 0 once settled. arg0 = event key. Wait-for-turn "
          "predicate — the event-actor twin of QueryActorRotating (op 113).",
          ["event key"]),
    183: ("SetEntityLevelAndRespawnAI", "actor",
          "Set an actor's level and re-run its monster behaviour script (respawns its AI at "
          "the new level) with a level-up VFX. arg0 = entity (0 = player, 1..47 = NPC, 48+ = "
          "event key). arg1 = new level, or -1 to play the level-up VFX only without changing "
          "the level. Used for scripted power-ups / boss phase changes.",
          ["entity (0=player, 1-47=NPC, 48+=event key)", "level (-1 = VFX only)"]),
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
    161: ("EventNpcWalkToTilePriority", "actor",
          "Walk a spawned event NPC to an ABSOLUTE tile AND lock it into high-priority "
          "scripted movement (control flag 0x20000) so it ignores AI and player interaction "
          "until the walk finishes — the cutscene-safe version of op 160. arg0 = event key "
          "(char id), arg1/arg2 = X/Y tiles, arg3 = speed, arg4 = run (0/1).",
          ["event key", "x (tiles)", "y (tiles)", "speed", "run (0/1)"]),
    162: ("SetMonsterFacing", "actor",
          "Set a monster's facing to an absolute angle. arg0 = monster (char id), arg1 = "
          "facing degrees (×181 → u16), arg2 = mode (0 = snap, non-zero = ease). (The "
          "handler's name says 'EightDirIndex' but the value is plain degrees, like every "
          "other facing op.)",
          ["monster (char id)", "facing (degrees)", "mode (0=snap, else ease)"]),
    164: ("QueryEventActorMoving", "query",
          "1 while a spawned event actor is still walking OR turning; 0 once it has both "
          "arrived and settled its facing. arg0 = event key. The COMBINED wait "
          "predicate — op 179 checks only turning, this also checks arrival.",
          ["event key"]),
    172: ("EventActorStopAnim", "actor",
          "Stop a spawned event actor's current animation and clear any outfit/costume "
          "override. arg0 = event key, arg1 = anim id to settle to. Event-actor "
          "twin of StopActorAnimAndClearOutfitOverride (ops 211/212).",
          ["event key", "anim id"]),
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
          "(contrast KillEventActor op 180 / DismissEventActor op 181). Use when a scene ends.",
          ["char id", "event key"]),
    168: ("EventActorResyncAnimFrame", "actor",
          "Force a spawned event actor to re-sync its animation frame from its widget after a "
          "state swap (fixes a one-frame visual pop when the anim state changes). arg0 = event "
          "key (char id). Low-level; pair with an anim change if you see a flicker.",
          ["event key"]),
    170: ("SetEventActorSpeedScale", "actor",
          "Set a spawned event actor's move / animation speed multiplier. arg0 = event key "
          "(char id), arg1 = scale percent (÷100 = the multiplier: 100 = normal, 50 = "
          "half-speed slow-mo, 200 = double). For slow-motion or sped-up cutscene moments.",
          ["event key", "scale % (100 = 1.0×)"]),
    175: ("SetEventActorStateWord", "actor",
          "Set a low-level per-actor state word (task field +172) on a spawned event actor. "
          "arg0 = event key, arg1 = value. Engine-internal state used by specific "
          "scripted setups; exact effect depends on the actor.",
          ["event key", "value"]),
    184: ("SetActorScriptedStateBit", "actor",
          "Set or clear an actor's scripted-state bit 0x10000000 in its status/equip "
          "bitfield (inferred to hide the actor during a scene transition). arg0 = target "
          "(0 = player, 1..47 = NPC, 48+ = event key). arg1 = 0 clears the bit, non-zero "
          "sets it.",
          ["actor (0=player, 1-47=NPC, 48+=event key)", "flag (0/1)"]),
})


# ---- dialogue speaker/emote ops decoded 2026-07-11 (93, 98) ------------------------
_M.update({
    93: ("SetDialogueSpeakerEmote", "dialogue",
         "Set the CURRENT dialogue speaker's facial emote/expression and re-target the "
         "portrait to it. arg0 = emote id: a 3-bit field (0..7), of which the game names 0-5 "
         "(0=normal, 1=angry, 2=sad, 3=laugh, 4=surprise, 5=blush -- the picker); 6-7 are valid "
         "field values but have no named portrait. This is the dialogue-portrait expression "
         "(0-7), a DIFFERENT space from op319 SetEmote's per-NPC record+57 emote byte. Use to "
         "change a speaker's expression mid-conversation without re-issuing the SetSpeaker.",
         ["emote id (0-7)"]),
    98: ("SetDialogueField161", "dialogue",
         "Write a byte to field +161 of the current dialogue task. arg0 = value. Low-level "
         "dialogue-display flag; exact effect is engine-internal (only touched by a few "
         "scenes).",
         ["value"]),
})


# ---- NPC visibility / animation / cutscene-teardown ops decoded 2026-07-11 (230-254) ----
_M.update({
    230: ("CutsceneEnd_ReleaseNpcLocks", "flow",
          "END-OF-CUTSCENE teardown: release every NPC AI lock set during the scene, restore "
          "normal AI, refresh schedules, and clear the placed-actor reservation mask — the "
          "counterpart to the AI-locking Move ops. arg0 = release mode (0 = leave locked, "
          "non-zero = restore normal AI), then the participant NPC ids (the handler takes the "
          "count from the argument count itself) (participants are left to finish their own dialogue/anim first). Call this at the "
          "end of any scene that moved or locked NPCs.",
          ["release mode (0=stay locked)", "participant npc id …"]),
    231: ("CutsceneEnd_ReleaseNpcLocks", "flow",
          "Alias of op 230 (same handler): end-of-cutscene NPC-lock release + schedule refresh.",
          ["release mode (0=stay locked)", "participant npc id …"]),
    233: ("HideNpc", "actor",
          "Hide an NPC — make it invisible/despawned and set its hidden state bit. arg0 = npc "
          "(char id). Removes the NPC from the scene; pair with a schedule refresh or "
          "SetNpcVisibleFlag to bring it back.",
          ["npc (char id)"]),
    234: ("HideNpc", "actor",
          "Alias of op 233 (same handler): hide an NPC and set its hidden bit.",
          ["npc (char id)"]),
    248: ("SetNpcVisibleFlag", "actor",
          "Toggle an NPC's visibility/interaction suppression bit (record +52 bit 0x800). "
          "arg0 = npc (char id), arg1 = visible: non-zero clears the suppress bit (NPC shown "
          "/ interactive), 0 sets it (suppressed). Lighter than HideNpc — just flips the flag.",
          ["npc (char id)", "visible (0=suppressed)"]),
    249: ("SetNpcVisibleFlag", "actor",
          "Alias of op 248 (same handler): toggle an NPC's visibility-suppression flag.",
          ["npc (char id)", "visible (0=suppressed)"]),
    252: ("SetActorAnimSpeedScale", "actor",
          "Set an actor's animation speed multiplier. arg0 = actor (char id, 0 = player), "
          "arg1 = speed percent (÷100: 100 = normal, 50 = slow-mo, 200 = fast). The regular-"
          "actor twin of SetEventActorSpeedScale (op 170).",
          ["actor (char id, 0=player)", "speed % (100 = 1.0×)"]),
    253: ("SetActorAnimSpeedScale", "actor",
          "Alias of op 252 (same handler): set an actor's animation speed multiplier.",
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
          "on screen. To also place it, use StreamInNpcAtTile (op 246).",
          ["npc (char id)", "mode (0=refresh, 1=force load)"]),
    246: ("StreamInNpcAtTile", "actor",
          "The 'appear here' action: stream an NPC into the scene AND place it at a tile, with "
          "no walk-on. arg0 = npc (char id, <48), arg1 = stream kind (load filter), arg2/arg3 "
          "= X/Y tiles. Lighter than a full teleport — keeps the NPC's existing AI state.",
          ["npc (char id)", "stream kind", "x (tiles)", "y (tiles)"]),
    243: ("EndDialogueLock", "dialogue",
          "End the dialogue lock — release the player-input / scene lock held during a "
          "conversation and hand control back to the player. arg0 = 0 performs the release "
          "(non-zero is a no-op). Use to close out a conversation.",
          ["mode (0 = end lock)"]),
    256: ("SetActorStatusConditions", "actor",
          "Apply or cure status conditions (poison / paralysis / sleep / seal / fatigue / "
          "cold) on an actor — for story afflictions and cures. arg0 = target (0 = player, "
          "2 = companion 1, 3 = companion 2, else = the current interaction NPC). arg1 = op: "
          "0 = clear all, 1 = afflict (poison+paralysis+sleep+seal+fatigue), 2 = cold only, "
          "3 = clear the standard 4, 4 = clear cold+fatigue.",
          ["target (0=player,2/3=companion,else NPC)", "op (0=clear,1=afflict,2=cold,3/4=cure)"]),
    250: ("SyncActorAnimFrame", "actor",
          "Force an actor to re-sync its animation frame from its widget after a programmatic "
          "state change (fixes a one-frame pose pop). arg0 = actor (char id, 0 = player). The "
          "regular-actor twin of EventActorResyncAnimFrame (op 168).",
          ["actor (char id, 0=player)"]),
    251: ("SyncActorAnimFrame", "actor",
          "Alias of op 250 (same handler): re-sync an actor's animation frame from its widget.",
          ["actor (char id, 0=player)"]),
})


# ---- NPC friendship / current-interaction / schedule ops decoded 2026-07-11 (218-271) ----
_M.update({
    218: ("QueryNpcFriendshipLevel", "query",
          "Read an NPC's friendship LEVEL (not raw points) into the VM output slot. arg0 = "
          "npc (char id); 0 uses the NPC the player is currently talking to. -1 if the NPC "
          "isn't found.",
          ["npc (char id, 0=current)"]),
    219: ("QueryNpcFriendshipLevel", "query",
          "Alias of op 218 (same handler): read an NPC's friendship level into the VM output.",
          ["npc (char id, 0=current)"]),
    221: ("AdjustCurrentNpcFriendship", "actor",
          "Adjust the friendship of the NPC the player is currently talking to "
          "(g_currentInteractionNpc). arg0 = op kind: 4 = add friendship XP, 5 = subtract XP, "
          "6 = set the friendship points absolutely. arg1 = the XP delta (kinds 4/5) or the "
          "absolute value (kind 6). The go-to op for dialogue-choice reactions "
          "(+/- affection).",
          ["op kind (4=add, 5=sub, 6=set)", "xp/value"]),
    262: ("QueryCurrentInteractionNpc", "query",
          "Read the char id of the NPC the player is currently talking to / interacting with "
          "into the VM output slot (0xFFFF if none). Use to branch a shared script on which "
          "NPC triggered it.",
          []),
    263: ("RespawnNpcAtSchedulePos", "actor",
          "Make an NPC reappear at its schedule-computed position after it was moved "
          "off-screen — resets its motion state and fires the 'arrived' event. arg0 = npc "
          "(char id). Used for quest-delivery / scene transitions.",
          ["npc (char id)"]),
    264: ("RespawnNpcAtSchedulePos", "actor",
          "Alias of op 263 (same handler): respawn an NPC at its scheduled position.",
          ["npc (char id)"]),
    270: ("RefreshNpcSchedule", "actor",
          "Refresh an NPC's schedule for TODAY — re-evaluates where it should be for the "
          "current day/time and updates it there. arg0 = npc (char id), arg1 = a mode flag. "
          "Use after a scene displaces NPCs or after advancing time.",
          ["npc (char id)", "mode flag"]),
    271: ("RefreshNpcSchedule", "actor",
          "Alias of op 270 (same handler): refresh an NPC's schedule for today.",
          ["npc (char id)", "mode flag"]),
})


# ---- NPC state query ops decoded 2026-07-11 (226-280) — dialogue-branch gates --------
_M.update({
    226: ("QueryNpcScheduleId", "query",
          "Read an NPC's current schedule id (which scheduled activity it's doing) into the "
          "VM output. arg0 = npc (char id). Quirk: arg0 = 0 returns the current INPUT-CONTEXT "
          "id instead of a schedule. Branch on what an NPC is up to right now.",
          ["npc (char id, 0=input ctx)"]),
    232: ("QueryNpcHidden", "query",
          "Read whether an NPC is hidden (1 = hidden, 0 = visible) into the VM output. arg0 = "
          "npc (char id). The query counterpart to HideNpc (op 233).",
          ["npc (char id)"]),
    273: ("QueryNpcPresent", "query",
          "Read whether an NPC is 'present' — its record's present-in-town bit (0x400000), "
          "i.e. currently around/available — into the VM output. arg0 = npc (char id); arg0 = "
          "0 instead returns the COUNT of villagers (1..23) currently present.",
          ["npc (char id, 0=count all)"]),
    274: ("QueryNpcPresent", "query",
          "Alias of op 273 (same handler): read an NPC's present flag, or the villager "
          "present-count when arg0 = 0.",
          ["npc (char id, 0=count all)"]),
    276: ("QueryNpcModelId", "query",
          "Read an NPC's current model/resource id (the loaded character model) into the VM "
          "output; 0 if none. arg0 = npc (char id). Use to check which model/costume an NPC "
          "is displaying.",
          ["npc (char id)"]),
    277: ("QueryNpcModelId", "query",
          "Alias of op 276 (same handler): read an NPC's current model/resource id.",
          ["npc (char id)"]),
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
    228: ("QueryNpcScheduleIsOneOf", "query",
          "Alias of op 227 (same handler): 1 iff an NPC's schedule matches one of a list.",
          ["npc (char id, 0=player)", "count", "schedule id …"]),
    236: ("QueryNpcInteractEligible", "query",
          "Read whether an NPC is currently eligible to be interacted with (present, loaded, "
          "not busy) into the VM output, and toggle its 'seen' bit. arg0 = npc (char id), "
          "arg1 = mode. Used to gate first-interaction / talk dialogue.",
          ["npc (char id)", "mode"]),
    240: ("QueryNpcGroupPresentNearby", "query",
          "Read 1 iff a GROUP of NPCs are all present, available, and clustered within a "
          "distance of the primary one — the gate for group conversations/events (e.g. the "
          "required characters are gathered). arg0 = max distance (tiles), arg1 = count of "
          "extra NPCs, arg2 = primary npc (char id), then that many more npc ids.",
          ["max distance (tiles)", "count", "primary npc", "other npc …"]),
    241: ("QueryNpcGroupPresentNearby", "query",
          "Alias of op 240 (same handler): 1 iff a group of NPCs are gathered within range.",
          ["max distance (tiles)", "count", "primary npc", "other npc …"]),
    268: ("QueryNpcArrivedAtSchedule", "query",
          "Read 1 iff the given NPC(s) have arrived at their schedule-computed positions and "
          "are available. arg0 = npc (char id); 0 checks that ALL villagers (1..23) are in "
          "place. arg1 = count of extra NPCs, then their ids. Wait-until-NPCs-in-position "
          "predicate before a staged scene.",
          ["npc (char id, 0=all)", "count", "other npc …"]),
    269: ("QueryNpcArrivedAtSchedule", "query",
          "Alias of op 268 (same handler): 1 iff the NPC(s) have arrived at their scheduled "
          "positions.",
          ["npc (char id, 0=all)", "count", "other npc …"]),
})


# ---- NPC lock / engage / talk-gesture ops decoded 2026-07-11 (222-289) --------------
_M.update({
    222: ("LockNpcPose", "actor",
          "Freeze an NPC's facing/pose for a cutscene: snapshots its current facing and sets "
          "the pose-locked + action-pending flags so it holds still and won't turn on its "
          "own. arg0 = npc (char id). Released by ReleaseNpcLocks (op 230).",
          ["npc (char id)"]),
    223: ("SetNpcEngaged", "actor",
          "Pull an NPC out of (or back into) its daily schedule so it can take part in a "
          "scene. arg0 = npc (char id), arg1 = engaged: non-zero pauses the NPC's routine "
          "('engaged'), 0 releases it back to its schedule. Refreshes its schedule state "
          "immediately.",
          ["npc (char id)", "engaged (0=release, 1=engage)"]),
    224: ("SetNpcEngaged", "actor",
          "Alias of op 223 (same handler): pause/resume an NPC's schedule for a scene.",
          ["npc (char id)", "engaged (0=release, 1=engage)"]),
    244: ("NpcShowItem", "actor",
          "Make an NPC play its 'show / hold up an item' gesture — the pose used when an NPC "
          "presents an item to the player (gift, quest reward, discovery). arg0 = npc "
          "(char id).",
          ["npc (char id)"]),
    289: ("TriggerActorTalkAnim", "dialogue",
          "Start an actor's visible 'talking' gesture (animation 240) and its talk-indicator "
          "overlay — the speaking animation to sync with a dialogue line. arg0 = actor "
          "(char id, 0 = player). For the player it also begins a scripted-talk interaction "
          "(auto-stops walking).",
          ["actor (char id, 0=player)"]),
})


# ---- NPC outfit + marriage/family story ops decoded 2026-07-11 (287-292) ------------
_M.update({
    287: ("SetNpcOutfit", "actor",
          "Change an NPC's outfit/costume variant. arg0 = npc (char id), arg1 = variant: "
          "0 = default, 1 = pajamas / bed outfit, 2 = festival / alternate, 3 = swimwear. "
          "Variants 0-2 PERSIST across scene changes (stored in the NPC record); variant 3 "
          "is single-scene only.",
          ["npc (char id)", "outfit (0=default,1=pajamas,2=festival,3=swim)"]),
    290: ("FireFamilyEventAchievements", "actor",
          "Write a packed marriage/family-status game-flag (packed id 4391 -> value 2; IDA "
          "names this 'set wife status 2') and run the family birthday/anniversary milestone "
          "check for today: compares the current date to the spouse's and children's birthdays "
          "and the wedding anniversary, setting the matching family-milestone game-flags. NOTE: "
          "these go through GameFlags_WritePacked (packed game-flags), NOT the ~30 real Steam "
          "achievements -- so 4391 is a game-flag write, not an achievement unlock. No args. "
          "Used in anniversary/birthday cutscenes.",
          []),
    291: ("SpawnChildEventRecords", "actor",
          "Spawn calendar-event records for the player's CHILDREN (count comes from the "
          "child-number game flag). Each record places a child event NPC into the scene "
          "registry. arg0 = char id, arg1 = room id. Used in family / child cutscenes.",
          ["char id", "room id"]),
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
    294: ("ResetNpcDailySchedule", "actor",
          "Alias of op 293 (same handler): reset an NPC's daily schedule + AI.",
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
    297: ("ApplyNpcScheduleState", "actor",
          "Alias of op 296 (same handler): apply a schedule state to an NPC.",
          ["npc (char id)", "state (-1 = auto)"]),
    302: ("SetNpcFriendshipJittered", "actor",
          "Write a randomized value to a per-NPC record field (+212): roughly 0.75×..1.1× the "
          "given value, varied by the shared RNG. arg0 = npc (char id), arg1 = base value. "
          "The handler treats +212 as a friendship-related field; the jitter gives NPCs "
          "slightly different values.",
          ["npc (char id)", "base value"]),
    303: ("SetNpcFriendshipJittered", "actor",
          "Alias of op 302 (same handler): write a jittered value to an NPC record field.",
          ["npc (char id)", "base value"]),
})


# ---- NPC/companion state-query + mount ops decoded 2026-07-11 (255-284) -------------
_M.update({
    255: ("QueryEntityActionStatus", "query",
          "Read an entity's status + action-event codes into TWO VM output slots. arg0 = "
          "entity (char id, 0 = player; else resolved via the current interaction NPC's "
          "companion). Output +64 = status (0 idle / 1 busy / 2 talking / 3 low-HP / 4 "
          "talking-only); output +68 = action-event code (115..118) used to pick a follow-up "
          "dialogue reaction.",
          ["entity (char id, 0=player)"]),
    282: ("QueryNpcActorPresent", "query",
          "Read whether an NPC's LIVE actor is spawned and visible in the current scene (its "
          "actor exists and the hidden bit is clear) into the VM output. arg0 = npc (char "
          "id). Distinct from QueryNpcPresent (op 273), which checks the town-roster flag.",
          ["npc (char id)"]),
    283: ("QueryCompanionNpcId", "query",
          "Read the char id of the player's current NPC companion (the villager following the "
          "player) into the VM output, or 0 if none. Use to branch on who is accompanying the "
          "player during a scene.",
          []),
    284: ("MountActor", "actor",
          "Mount an actor onto a rideable partner, or dismount. arg0 = actor (char id, 0 = "
          "player). arg1 = mount event key: 0 dismounts (drops to the ground), non-zero looks "
          "up the ride partner in the event registry by that key and starts the mount "
          "transition. Used for scripted riding (e.g. climbing onto a tamed monster).",
          ["actor (char id, 0=player)", "mount event key (0=dismount)"]),
})


# ---- NPC dialogue-wellness + schedule-place/pending ops decoded 2026-07-11 (260-299) ----
_M.update({
    260: ("QueryActorHpWellness", "query",
          "Read the current scene subject's HP wellness for a dialogue branch into the VM "
          "output: 0 = healthy (HP > 50%), 1 = low HP (≤ 50%), 2 = no combat stats. No args "
          "(uses the scene's subject actor). Drives 'Are you ok? You look hurt.' reactions.",
          []),
    266: ("SetOrClearNpcSchedule", "actor",
          "Place an NPC at a scripted (location, facing, state) for a scene, OR clear its "
          "schedule entirely. arg0 = npc (char id), arg1 = persist flag, arg2/arg3 = X/Y "
          "tiles, arg4 = facing (0-255), arg5 = apply switch (non-zero = place, 0 = clear "
          "back to normal schedule), arg6 = schedule kind, arg7 = sub-kind, arg8 = state "
          "byte. The heavy 'pin this NPC here' / 'release it' lever.",
          ["npc (char id)", "persist", "x (tiles)", "y (tiles)", "facing (0-255)",
           "apply (0=clear)", "sched kind", "sub kind", "state"]),
    267: ("SetOrClearNpcSchedule", "actor",
          "Alias of op 266 (same handler): pin an NPC to a scripted spot/state, or clear it.",
          ["npc (char id)", "persist", "x (tiles)", "y (tiles)", "facing (0-255)",
           "apply (0=clear)", "sched kind", "sub kind", "state"]),
    281: ("ApplyNpcDateOutcome", "actor",
          "Set an NPC's date/event OUTCOME state (3-bit, into its record). arg0 = npc (char "
          "id), arg1 = outcome state. State 4 = a successful date, which AWARDS friendship XP "
          "(enough to level up on the first date, otherwise +55). Use at the end of a "
          "dating/event scene.",
          ["npc (char id)", "outcome state (4=success)"]),
    298: ("ApplyPendingNpcPlan", "actor",
          "Apply an NPC's PENDING schedule plan for today — re-parses and applies its "
          "calendar-computed schedule, clears its scene reservation, and refreshes the "
          "story-progress cache. arg0 = npc (char id). Like op 296 but also snapshots story "
          "progress.",
          ["npc (char id)"]),
    299: ("ApplyPendingNpcPlan", "actor",
          "Alias of op 298 (same handler): apply an NPC's pending schedule plan for today.",
          ["npc (char id)"]),
})


# ---- NPC seen/comment/flag + schedule-refresh + scene-state ops decoded 2026-07-11 (235-301) ----
_M.update({
    235: ("QueryNpcSeenToggle", "query",
          "Read whether an NPC is interaction-eligible AND toggle its 'seen today' bit into "
          "the VM output. arg0 = npc (char id). Like QueryNpcInteractEligible (op 236) but "
          "with a fixed mode. Used to gate first-encounter dialogue.",
          ["npc (char id)"]),
    257: ("QueryAnyNpcEligibleForComment", "query",
          "Read 1 iff ANY of the listed NPCs is eligible to deliver an ambient 'flavor "
          "comment' — present, not busy, in the current area, and not story-gated. arg0 = "
          "count, then that many npc ids. Fired when the player interacts with something a "
          "nearby NPC might remark on.",
          ["count", "npc id …"]),
    258: ("QueryAnyNpcEligibleForComment", "query",
          "Alias of op 257 (same handler): 1 iff any listed NPC can deliver a flavor comment.",
          ["count", "npc id …"]),
    261: ("SetNpcParticipationFlag", "actor",
          "Set a persistent NPC flag (record +52 bit 0x80000000) — a town-wide event / "
          "ledger participation marker. arg0 = npc (char id); 0 applies it to ALL 23 "
          "villagers. Otherwise arg1 = count and that many npc ids each get the flag.",
          ["npc (char id, 0=all)", "count", "other npc …"]),
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
    239: ("QueryQuestNpcsAvailable", "quest",
          "Alias of op 238 (same handler): 1 iff the quest's NPCs are all free and gathered.",
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
    279: ("QueryNpcFavoriteItem", "query",
          "Alias of op 278 (same handler): read a rolled favorite-gift item id for an NPC.",
          ["npc (char id)"]),
    286: ("SetActorStateBitsLow16", "actor",
          "Set the LOW 16 bits of an actor's state bitfield (a short-form state code — walk / "
          "run / hit / talk, etc.), preserving the high status/animation flags. arg0 = actor "
          "(char id, 0 = player), arg1 = the new low-16 value. Advanced / low-level.",
          ["actor (char id, 0=player)", "state (low 16 bits)"]),
})


# ---- last NPC-block query ops decoded 2026-07-11 (220-288) — completes 214-303 -------
_M.update({
    220: ("QueryAllNpcsFriendship", "query",
          "Read 1 iff an NPC's friendship level meets/exceeds [target]. arg0 = npc (char id), "
          "arg1 = target level. When arg0 = 0, instead checks that ALL story-available "
          "villagers meet the target (gated by story progress + the active festival). Gate "
          "town-wide events on overall affection.",
          ["npc (char id, 0=all available)", "target level"]),
    237: ("QueryNpcPairInteraction", "query",
          "Read whether one NPC can interact with another right now — close enough and hasn't "
          "already interacted with them today. arg0 = subject npc (char id), arg1 = target "
          "npc (char id), arg2 = range. For NPC-to-NPC greeting / pairing events.",
          ["subject npc (char id)", "target npc (char id)", "range"]),
    259: ("QueryNpcRosterPresence", "query",
          "Check which of the listed NPCs are currently rendered in the scene — writes a "
          "present/absent flag (1/0) for each into up to 10 consecutive VM output slots. "
          "arg0 = how many slots to fill, then the npc ids to test. Test which characters "
          "are on-stage before triggering interactions.",
          ["slot count", "npc id …"]),
    288: ("QueryNpcActorStateWord", "query",
          "Read a per-NPC actor state word (actor field +488) into the VM output; 0 if the "
          "NPC isn't loaded. arg0 = npc (char id). The exact meaning is engine-internal (a "
          "16-bit state field a few scripts branch on).",
          ["npc (char id)"]),
    272: ("nop", "noop",
          "Reserved opcode — bound to a shared no-op stub (a SoLoud bus placeholder). Does "
          "nothing and should not appear in real scripts.",
          []),
    381: ("nop", "noop",
          "Stubbed no-op (bound to the shared `return 0;` stub) — a 3DS-era op that does nothing "
          "on the PC port. UNLIKE most stub slots, shipped cutscenes DO still emit it (~15x in "
          "rf3.mc), so seeing it in a scene is normal, not corruption. Safe to keep or delete.",
          []),
    388: ("nop", "noop",
          "Stubbed no-op (bound to the shared `return 0;` stub) — a 3DS-era op that does nothing "
          "on the PC port. Shipped cutscenes still emit it (~5x in rf3.mc), so it is a legitimate "
          "(if inert) statement, not corruption. Safe to keep or delete.",
          []),
})


# ---- party heal/restore + NPC emote/outfit ops decoded 2026-07-11 (311-328) ---------
_M.update({
    311: ("HealPartyFull", "companion",
          "Fully heal the party — restores the player and both active companions to max HP. "
          "No args. Post-battle / rescue recovery scenes.",
          []),
    312: ("HealPartyByShift", "companion",
          "Heal the party (player + both companions) by a fraction of each one's max HP. "
          "arg0 = shift: 0 = full heal, 1 = half max HP, 2 = quarter, and so on "
          "(heal = hp_max >> shift). Partial recovery.",
          ["shift (0=full, 1=½, 2=¼ …)"]),
    313: ("RestorePlayerRP", "actor",
          "Fully restore the player's RP (Rune Points) to max. No args.",
          []),
    314: ("CurePartyStatus", "companion",
          "Cure the standard status conditions on the whole party (player + both companions): "
          "poison, paralysis, sleep, seal, and cold. Fatigue and faint are NOT cleared. No "
          "args. For medicine / recovery scenes.",
          []),
    320: ("SetNpcEmoteByte", "dialogue",
          "Set an NPC's persistent emote / facial-expression byte (record +57) — the "
          "expression it shows (happy / sad / angry …) both in and out of dialogue, and the "
          "last-dialogue-emote global. arg0 = npc (char id), arg1 = emote id. Distinct from "
          "op 93 (which sets the CURRENT dialogue speaker's emote only).",
          ["npc (char id)", "emote id"]),
    328: ("PlayActorTransform", "actor",
          "Play an animated outfit / pose CHANGE on an actor (the character-change transform "
          "task). arg0 = actor (char id, 0 = player). arg1 = pose: 255 = end the pose and "
          "return to idle, 3 = swap to the alternate-outfit asset set; other values begin a "
          "pose (detaching any prior one). For 'character transforms / changes clothes' "
          "moments. Contrast op 287 (SetNpcOutfit — persistent pajamas/festival/swim variants).",
          ["actor (char id, 0=player)", "pose/variant (255=end, 3=alt)"]),
})


# ---- NPC visibility/mood/outfit + player pose + greeting ops decoded 2026-07-11 (315-396) ----
_M.update({
    315: ("QueueNpcGreetingEvent", "actor",
          "Find the NPC standing near tile (x, y) — within ~16 tiles and in the active input "
          "context — and queue a greeting / wave interaction event with them. arg0/arg1 = X/Y "
          "tiles. Sets that NPC as the interaction subject.",
          ["x (tiles)", "y (tiles)"]),
    317: ("SetNpcVisibility", "actor",
          "Show or hide an NPC's LIVE actor immediately by toggling its render-hide bit. "
          "arg0 = npc (char id), arg1 = show (non-zero = show, 0 = hide). More direct than "
          "HideNpc (op 233) and distinct from SetNpcVisibleFlag (op 248, which flips a record "
          "bit).",
          ["npc (char id)", "show (0=hide, 1=show)"]),
    323: ("SetNpcMoodByte", "dialogue",
          "Set an NPC's persistent MOOD byte (record +56) — its temperament/default "
          "expression state, distinct from the emote byte (+57, op 320). arg0 = npc (char "
          "id), arg1 = mood id.",
          ["npc (char id)", "mood id"]),
    331: ("SetActorOutfitDirect", "actor",
          "Directly set an actor's outfit/costume variant with NO transition animation (an "
          "instant swap). arg0 = actor (char id, 0 = player), arg1 = outfit variant id. The "
          "lightweight version of PlayActorTransform (op 328).",
          ["actor (char id, 0=player)", "outfit variant"]),
    396: ("SetPlayerFacingAndPose", "actor",
          "Set the player's facing angle AND pose in one op (instant snap). arg0 = facing "
          "degrees (×181 → u16), arg1 = pose byte. Marks the renderer dirty so the change "
          "shows immediately. Handy for a posed player shot.",
          ["facing (degrees)", "pose"]),
})


# ---- player resource modify + give-item ops decoded 2026-07-11 (417-424) ------------
# (op 416 QueryPlayerVariable — the read counterpart — is curated via _STAT_QUERY_OPS below.)
_M.update({
    417: ("ModifyPlayerResource", "item",
          "Grant or take a player resource. arg0 = resource char-code: 'd'(100)=gold "
          "(caps at 2,000,000,000), 'i'(105)=stone, 'j'(106)=compost (both cap 50,000), "
          "'f'(102)=armor def. arg1 = op: 4 = add, 5 = subtract, 6 = set. arg2 = amount. "
          "Subtracting gold plays the coin-clink SFX. The 'pay 1000 gold' / 'here's a reward' "
          "op.",
          ["resource code (d=gold,i=stone,j=compost,f=def)", "op (4=add,5=sub,6=set)", "amount"]),
    424: ("GivePlayerItem", "item",
          "Give the player an item — the core reward/gift op. arg0 = item id, arg1 = stack "
          "count, arg2 = quality. Plays the pick-up animation and adds it to the backpack (or "
          "rune/ability page); if the bag is full it drops the item at the player's feet with "
          "a jingle instead. Writes success (1/0) to the VM output.",
          ["item id", "stack count", "quality"]),
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
    459: ("ShowRewardPopupAtTile", "item",
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
    468: ("FastForwardCalendar", "time",
          "Fast-forward the in-game calendar and run the sleep update (schedule refresh, crop "
          "growth, etc). arg0 = year/season, arg1 = month, arg2 = day, arg3 = hour, arg4 = "
          "absolute mode (0 = advance by these amounts, non-zero = set directly). The "
          "time-skip op ('…the next morning').",
          ["±year/season", "±month", "±day", "±hour", "absolute (0/1)"]),
    469: ("SetOrAddCalendarDate", "time",
          "Set or advance the calendar's year / month / day in one call, then run the sleep "
          "update and refresh the clock HUD. arg0-2 = the date components, arg3 = absolute "
          "mode (0 = add the amounts, non-zero = set them directly). Coarser than "
          "FastForwardCalendar (op 468) — no hour.",
          ["year/season", "month", "day", "absolute (0/1)"]),
})


# ---- companion / party-sync ops decoded 2026-07-11 (477-490) ------------------------
_M.update({
    477: ("StreamInNpcAtPlayer", "actor",
          "Bring an NPC into the scene at the player's position (streaming it in if needed) "
          "and add/sync it as a companion, with marriage-trigger handling. arg0 = npc (char "
          "id). Use to make an NPC join the player for a scene.",
          ["npc (char id)"]),
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
    490: ("QueryMarriagePartnerInParty", "query",
          "Read 1 iff your marriage candidate is present in the party for a date/proposal "
          "scene (and, if so, unlock the 'met your partner' achievement). No args. Gates the "
          "marriage-scene branch.",
          []),
})


# ---- monster-farm / dex / dev-mode ops decoded 2026-07-11 (401-622) -----------------
_M.update({
    401: ("MonsterFarmSpawn", "effect",
          "Send the current interaction monster to the player's monster farm (picks a farm "
          "area and spawns it there). arg0 = a spawn mode/param. For taming/relocating a "
          "monster you're interacting with.",
          ["spawn param"]),
    405: ("SetMonsterFarmLovedToday", "effect",
          "Set or clear the 'loved today' bit (record flag 0x40000) for a farm monster. arg0 = "
          "the farm monster (-1 = current interaction NPC's monster); arg1 = the bit value "
          "(1 = mark loved/cared-for today, 0 = clear). Affects daily affection/produce. Read "
          "back with op 406.",
          ["farm monster", "loved (0/1)"]),
    406: ("GetMonsterFarmLovedToday", "query",
          "Read whether a farm monster has been 'loved' (cared for) today into the VM output. "
          "arg0 = the farm monster. Counterpart of op 405.",
          ["farm monster"]),
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
          "Roll a random item id from a shop category table (Shop_RollByCategoryFromTable) and "
          "write it to the VM output slot for a following read.",
          ["shop category"]),
    598: ("RollRandomItemMatchingDisplayName", "item",
          "Roll a random item whose display-name string id matches the arg (groups items that "
          "share a name, e.g. all Swords), preferring the cheapest tier; result to the VM output "
          "slot. Used for shop randomization.",
          ["display-name string id"]),
    681: ("LootRollByCategoryForPlayer", "item",
          "Roll a loot item for the player from a category loot table (LootTable_RollByCategory) "
          "and write the item id to the VM output slot for a following read.",
          ["loot category"]),
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
    620: ("UnlockMonsterDex", "actor",
          "Unlock a monster's bestiary / dex entry — sets the dex bit and fires the "
          "first-encounter achievement. arg0 = monster id. Fired the first time a monster is "
          "encountered. Setter counterpart of QueryMonsterDexBit (op 695).",
          ["monster id"]),
    621: ("SetDifficulty", "flag",
          "Set the game DIFFICULTY (the Special-edition Easy/Normal/Hard/Hell option; the old "
          "'SetDevMode' name was wrong). arg0 = mode: 0 = Easy (g_globalGameStateFlags bit "
          "0x4000), 1 = Normal (clears 0xC000), 2 = Hard AND Hell (bit 0x8000 — the script "
          "distinguishes Hell with a separate packed-flag STORE, the engine bit is the same). "
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
    425: ("ForcePlayerHoldItem", "item",
          "Put an item directly in the player's HANDS (held, not in the bag) with the pickup "
          "jingle. arg0 = item id (0 = instead consume/use up the currently-held item), arg1 "
          "= quality, arg2 = stack count. For 'the player holds up what they just made / "
          "received'. Distinct from GivePlayerItem (op 424), which adds to the backpack.",
          ["item id (0=consume held)", "quality", "stack count"]),
    429: ("TakeItemFromBackpack", "item",
          "Remove an item from the player's backpack or equip-extras (a scripted take). arg0 "
          "= item id, further args = count / quality. Used for quest turn-ins and story items "
          "taken from the player.",
          ["item id", "count", "quality"]),
    430: ("ConsumeHeldItem", "item",
          "Consume / use up N of the item the player is currently holding. arg0 = count. For "
          "'the player uses the item' cutscene moments.",
          ["count"]),
    616: ("QueryAndSetCraftedFlag", "item",
          "Read the 'has ever been crafted' flag for an item — returns the OLD value to the "
          "VM output, then marks the item as crafted in the save flags. arg0 = item id "
          "(100000 = a misc-craft sentinel). Gates first-craft dialogue / rewards.",
          ["item id (100000=misc)"]),
})

# ---- can-interact / pending-interaction / action-trigger ops decoded 2026-07-11 (369-634) ----
_M.update({
    369: ("QueryPlayerCanInteract", "query",
          "Read whether the player is free to interact with the current scene actor into the "
          "VM output (slot 1 = 1 if not mid-action). If the player is free and not carry-"
          "blocked, this also begins a mount transition onto that actor. No args.",
          []),
    421: ("SetupPendingInteraction", "flow",
          "Stage a 'pending interaction record' — a scratch buffer that the next item-give / "
          "interaction op (GivePlayerItem, AttachItemVisual) reads to apply extra params "
          "(e.g. a just-crafted item's runes, a specific action). arg0 = action id, arg1 = "
          "flag byte, then up to 6 extra u16 params.",
          ["action id", "flag byte", "extra param …"]),
    422: ("SetupPendingInteractionV2", "flow",
          "Variant of op 421 (distinct handler Script_VMOp_SetupPendingInteractionRecord_Variant2, "
          "same purpose): stage the pending-interaction record for the next item/interaction op.",
          ["action id", "flag byte", "extra param …"]),
    634: ("SetActionTriggerByte", "flow",
          "Set one of the scene's 3 action-trigger bytes (ctx state, index 0-2). arg0 = index "
          "(0-2), arg1 = value. Low-level scene flag used to gate scripted actions; read back "
          "with GetActionTriggerByte (op 635).",
          ["index (0-2)", "value"]),
})

# ---- inventory-space / item-attr query ops decoded 2026-07-11 (418-456) -------------
_M.update({
    418: ("QueryBackpackHasOccupiedSlot", "query",
          "Read 1 iff the player's backpack has at least one occupied slot (holds any item) "
          "into the VM output. No args.",
          []),
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
    456: ("QueryEquippedItemAttr", "query",
          "Read an equipped item's id + a chosen attribute into the VM output (output slot 0 "
          "= item id, slot 1 = attribute value). arg0 = equip slot (0 weapon, 1 shield, 2 "
          "head, 3 body, 4 boots, 5 accessory). arg1 = attribute id: 0-8 = enchant-slot "
          "effects, 9/10 = upgrade attrs, 11 = base item id, 12 = rune-slot count, 13/14 = "
          "rune ids. For upgrade / enchant / appraisal dialogue.",
          ["equip slot (0=weapon..5=accessory)", "attribute id"]),
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
    411: ("QueryCompanionMonsterData", "query",
          "Read player / companion / farm-monster data into the VM output — a multi-purpose "
          "query. arg0 = target index (party member or monster), arg1 = query kind: 0-4 = "
          "party-member stats (base / mods / points / monster fields), 5-10 = farm-monster "
          "roster / flags / census / level / affinity. Sibling of QueryGameState. For "
          "stat-based dialogue and monster-farm scenes.",
          ["target index", "query kind"]),
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
          "pan lands. (The old name 'QueryPlayerMovedFromMark' followed the technical symbol; "
          "the IDB comparison is against g_cameraPosQ12, the CAMERA, not the player.)",
          []),
    206: ("CancelNpcPathOrEquipMainhand", "actor",
          "Dual-purpose. For an NPC (arg0 != 0): cancel its pending path / scripted action so "
          "it stays put for a scene (arg1 = a specific target to cancel, 0 = cancel all). For "
          "the player (arg0 = 0): equip the mainhand weapon = arg1 (0 = unequip), refreshing "
          "stats. Stages the player's loadout ('NPC hands you a sword') or freezes an NPC's "
          "movement.",
          ["npc (char id, 0=player)", "item id / cancel target"]),
    207: ("CancelNpcPathOrEquipMainhand", "actor",
          "Alias of op 206 (same handler): cancel an NPC's path, or equip the player's "
          "mainhand.",
          ["npc (char id, 0=player)", "item id / cancel target"]),
})

# ---- actor facing-byte / spin / low-level motion-field ops decoded 2026-07-11 (84-106) ----
_M.update({
    103: ("TurnActorToAngle", "actor",
          "Turn an actor toward a facing angle in DEGREES (×181 -> the u16 angle; 181×360 ≈ "
          "65536), plus a pitch/mode byte — sets the TARGET facing and the turn-pending flag "
          "(the turn-lerp tick eases toward it; pair with QueryActorAnimBusy op 129 to wait "
          "for the turn). arg0 = actor (char id, 0 = player), arg1 = degrees, arg2 = "
          "pitch/mode. CORPUS-PROVEN degrees: the arg distribution is 0/45/90/135/180/225/"
          "270/315 — compass multiples of 45, never a 0-255 spread (the old 'byte angle' "
          "reading was wrong). Distinct from SetActorFacingAngle (77/78), which writes the "
          "facing instantly.",
          ["actor (char id, 0=player)", "facing (degrees)", "pitch/mode"]),
    104: ("TurnActorToAngle", "actor",
          "Alias of op 103 (same handler): turn an actor toward a target facing in degrees.",
          ["actor (char id, 0=player)", "facing (degrees)", "pitch/mode"]),
    106: ("RotateActorInPlace", "actor",
          "Rotate an actor's facing by [delta] each frame for [total steps] frames — a "
          "spin/turn-in-place animation. BLOCKING until the step count is reached. arg0 = "
          "actor (char id, 0 = player), arg1 = delta (byte per step, ×181), arg2 = total "
          "steps. For 'spin around' moments (dizzy, transformation, celebration).",
          ["actor (char id, 0=player)", "delta (byte/step)", "total steps"]),
    84: ("SetActorMotionField62", "actor",
         "Low-level motion tuning: write a value to an actor's motion-struct field +62 (only "
         "if the 3rd arg is non-zero). arg0 = actor (matched vs the scene's participant "
         "slots), arg1 = value, arg2 = apply flag. Engine-internal motion parameter — rarely "
         "needed directly.",
         ["actor (char id)", "value", "apply (0/1)"]),
    85: ("SetActorMotionField56", "actor",
         "Low-level motion tuning: write a value to an actor's motion-struct field +56. arg0 "
         "= actor, arg1 = value. Engine-internal motion parameter.",
         ["actor (char id)", "value"]),
    86: ("SetActorMotionField56", "actor",
         "Alias of op 85 (same handler): write actor motion field +56.",
         ["actor (char id)", "value"]),
    87: ("SetActorMotionField60", "actor",
         "Low-level motion tuning: write a value to an actor's motion-struct field +60. arg0 "
         "= actor, arg1 = value. Engine-internal motion parameter.",
         ["actor (char id)", "value"]),
    88: ("SetActorMotionField60", "actor",
         "Alias of op 87 (same handler): write actor motion field +60.",
         ["actor (char id)", "value"]),
    89: ("SetActorMotionMask", "actor",
         "Low-level motion tuning: set an actor's motion-state mask. arg0 = actor, arg1 = "
         "mask value. Engine-internal — controls motion-state bits.",
         ["actor (char id)", "mask"]),
    90: ("SetActorMotionMask", "actor",
         "Alias of op 89 (same handler): set an actor's motion-state mask.",
         ["actor (char id)", "mask"]),
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
        "be EXACTLY one argument. The old name 'EndReactionAndJump' described a side call "
        "(Quest_OnReactionDispatched_AdvanceState), not the behaviour — IDA-verified as the "
        "wait primitive (vm[+120] = units, state -> WAITING; RF4S.exe+0x1FAB50).",
        ["duration (units; 200 = 1 frame, 12000 = 1 s)"]),
    3: ("WaitReset", "flow",
        "Wait variant that also RESETS the quest-reaction state first (op 2's sibling handler; "
        "1 use in the whole opening chain). Same duration units as Wait.",
        ["duration (units; 200 = 1 frame)"]),
    4: ("ConditionalJump", "flow",
        "Redirect the VM to a target pc when the scene is in the pending-reaction state "
        "(ctx state 4) — a lightweight conditional jump used inside quest-reaction sequences "
        "(does not advance any quest state). arg0 = target.",
        ["jump target"]),
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
    5: ("ShowNpcBubbleVariant", "dialogue",
        "Show an NPC speech / thought bubble — a variant form of ShowNpcBubble (op 6) that "
        "takes the same descriptor (line id + tokens) with a slightly different layout. "
        "Blocks until any active screen fade completes. args: line id (into rf3mc.<locale>), "
        "sub-token, extra param, and a sfx/emote (>= 0x1F0 plays a voice line, else an emote).",
        ["line id", "sub", "param", "sfx/emote id"]),
    6: ("ShowNpcBubble", "dialogue",
        "Show an NPC speech / thought bubble with a dialogue line — the core bubble op. arg0 "
        "= line id (into rf3mc.<locale>), arg1 = sub-token, arg2 = extra param (PSB-emote "
        "capable), arg3 = sfx/emote (>= 0x1F0 plays a voice line via the NPC-variant remap, "
        "else an emote id). Blocks until any active screen fade completes.",
        ["line id", "sub", "param", "sfx/emote id"]),
    7: ("ShowNpcBubble", "dialogue",
        "Alias of op 6 (same handler): show an NPC speech/thought bubble.",
        ["line id", "sub", "param", "sfx/emote id"]),
    211: ("StopActorAnim", "actor",
          "Stop an actor's current animation cleanly and clear any outfit/costume override "
          "(set by SetNpcOutfit). arg0 = actor (char id; 0 = player, -1 = the current "
          "interaction NPC, 1..47 = NPC). arg1 = anim id to settle to. Use to drop a special "
          "pose/outfit between scene beats.",
          ["actor (char id, 0=player, -1=current)", "anim id"]),
    212: ("StopActorAnim", "actor",
          "Alias of op 211 (same handler): stop an actor's anim + clear its outfit override.",
          ["actor (char id, 0=player, -1=current)", "anim id"]),
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
    677: ("SpawnTileEffectObject", "effect",
          "Spawn a special class-2050 tile object — a floating harvest-notification-style "
          "effect actor — at a tile. arg0/arg1 = X/Y tiles. For scripted visual effects.",
          ["x (tiles)", "y (tiles)"]),
    695: ("QueryMonsterDexBit", "query",
          "Read 1 iff a monster has been recorded in the monster dex (encountered/tamed) into "
          "the VM output. arg0 = monster id. For 'have you seen this monster?' gates.",
          ["monster id"]),
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
    683: ("PlayCutsceneVideo", "screen",
          "Play a pre-rendered full-motion cutscene VIDEO by id (a WebM movie), OR — if a "
          "dialogue is mid-step — advance it to the next step instead. arg0 = video id. The "
          "op that triggers an FMV cutscene.",
          ["video id"]),
    684: ("QuerySaveConfigBitByIdx", "query",
          "Read a save-config settings flag bit by INDEX into the VM output. arg0 = bit index "
          "(0..58, spanning a 27-bit + a 32-bit config word). Generic settings read (distinct "
          "from the g_saveConfigFlags bit ops 666-673).",
          ["config bit index"]),
    685: ("SetGlobalScratch", "flag",
          "Set a general-purpose global scratch dword (persists across scenes within a "
          "session). arg0 = value. Stash a value here and read it back later with "
          "GetGlobalScratch (op 686) to pass data between scripts.",
          ["value"]),
    686: ("GetGlobalScratch", "query",
          "Read the general-purpose global scratch dword (set by op 685) into the VM output. "
          "No args.",
          []),
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
    692: ("OnFirstMarriageAccepted", "actor",
          "Finalize a first marriage acceptance: unlock the marriage achievement, clear the "
          "candidate NPC's proposal state, and trigger the marriage-acceptance follow-up "
          "sequence (CondScript entry 80). No args — fired the moment a proposal is accepted.",
          []),
    696: ("RemoveItemFromBackpack", "item",
          "Remove items from the player — the 'take from player' op (quest turn-in, a story "
          "item being taken). arg0 = item id, arg1 = count, arg2 = quality filter (-1 = any "
          "quality; >=0 = only that quality). Also decrements the held item if it matches.",
          ["item id", "count", "quality (-1=any)"]),
})

# ---- misc query/trigger ops decoded 2026-07-11 (619-648) ----------------------------
_M.update({
    619: ("QueryNpcAdmireResponse", "query",
          "Read the current interaction NPC's 'admire' reaction into the VM output: 0 = "
          "no/reserved, 1 = happy, 2 = excited. Gated by friendship level, story progress, "
          "season, and per-NPC conditions; the result is cached so re-queries stay stable. "
          "Drives confession / gift-admire dialogue branches. No args.",
          []),
    625: ("BeginDungeonArea", "effect",
          "Enter a dungeon area by id — loads the area and installs the in-dungeon input "
          "context (442). arg0 = dungeon area id. A scene-transition op for going into a "
          "dungeon.",
          ["dungeon area id"]),
    628: ("SetRegisters", "flag",
          "Load the VM REGISTER FILE reg0..reg9 (ctx+64..+100) from up to 10 argument values "
          "— reg[i] = arg[i]. These are the registers expressions read back via the reg "
          "tokens, SWITCH_EQ selectors dispatch on, and camera/position ops consume "
          "(GetPlayerPosition writes reg0/reg1; a staged PROMPT_CHOICE writes the pick to "
          "reg0). This op is how a script seeds them explicitly (1,825 uses). Registers are "
          "flat scratch — NOT saved across CALL — so consume them before the next op that "
          "writes reg0.",
          ["reg0 value", "reg1 value", "…up to reg9"]),
    629: ("SetRegisters", "flag",
          "Alias of op 628 (same handler): load reg0..reg9 from up to 10 values.",
          ["reg0 value", "reg1 value", "…up to reg9"]),
    648: ("QueryTownDevelopment", "query",
          "Read the town/shipping development percentage (unique items shipped ÷ total unique "
          "× 100, clamped to 100) into the VM output. For progress-gated dialogue ('the town "
          "is X% developed'). No args.",
          []),
})

# ---- tile-object ops decoded 2026-07-11 (587-589) — placed scene collectibles --------
_M.update({
    587: ("GiveTileObject", "item",
          "Place a 'tile object' — a collectible/scene object that sits on a tile (like a "
          "dropped item the player can walk over to pick up) — with the drop jingle and drop "
          "indicator. arg0 = item id, arg1 = container/context id (-1 = current), arg2/arg3 = "
          "X/Y tiles (-1 = the player's tile). Writes 1 to the VM output if placed (max 16 "
          "active).",
          ["item id", "container id (-1=current)", "x (tiles, -1=player)", "y (tiles, -1=player)"]),
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
          "index in reg0 (that's what the SWITCH_EQ after a staged prompt dispatches on). "
          "Writes 1 to reg0 now if any bit is set. IDA-verified 2026-08-17 "
          "(Script_VMOp_SetSceneChoiceVisibleMaskFromArgs).",
          ["choice 0 visible", "choice 1 visible", "…"]),
    611: ("ClearChoiceVisibleRange", "dialogue",
          "Clear COUNT choice-visibility bits starting at START (hide those choices; dword 0 "
          "only, i.e. options 0..31). arg0 = start bit, arg1 = count — NOT a from/to pair "
          "(IDA-verified 2026-08-17: clears bits [start, start+count)). Writes 1 to reg0 if "
          "any bit anywhere is still set. Companion to SetChoiceVisibleMask (op 610).",
          ["start index", "count"]),
    612: ("SetChoiceVisibleBit", "dialogue",
          "Show or hide a SINGLE choice by index in the scene's choice-visibility mask. arg0 = "
          "choice index (0-127), arg1 = visible (1) / hidden (0). Writes 1 to reg0 if any "
          "choice is still visible — scripts branch on 'is anything left to offer'. The next "
          "PROMPT_CHOICE presents only flagged options and maps the pick back to the original "
          "index in reg0; the prompt then CLEARS the whole mask.",
          ["choice index (0-127)", "visible (0/1)"]),
    613: ("CalcChoicePrescroll", "dialogue",
          "Compute the initial scroll position for the upcoming choice menu from the current "
          "visibility mask (so the list opens scrolled to the first visible option). Writes "
          "the result to the VM output. No args.",
          []),
    615: ("ArmChoiceOption", "dialogue",
          "ARM the next DIALOG statement as a CHOICE OPTION: instead of displaying, that "
          "DIALOG's line is QUEUED into the pending-option list (44-byte record in "
          "g_dialoguePendingLineQueue) together with up to 3 staged follow-up values, gated "
          "on the option's visibility bit. The canonical list shape is "
          "[ArmChoiceOption(v); DIALOG line] × N — then a later PROMPT_CHOICE (often in a "
          "DIFFERENT scene; the queue is global) presents the queued lines. On selection the "
          "picked option's line is ECHOED as the next spoken line and its staged values are "
          "committed to the choice-commit state slots (kinds 4/5/6 — read back via the "
          "GetVar ops or ConsumeChoiceCommitResult). 1,803 uses — the most common choice "
          "idiom; 99.7%% are immediately followed by their DIALOG. IDA-verified 2026-08-17 "
          "(deferred path of Dialogue_HandleScriptActionShowLine + "
          "ChoiceDialog_CommitSelectionAndDispatchActions).",
          ["staged value 1", "staged value 2", "staged value 3"]),
})

# ---- scene-staging / NPC-list / bubble-flavor ops decoded 2026-07-11 (474-560) ------
_M.update({
    474: ("SetEventLeadNpc", "actor",
          "Declare the lead / central NPC of the current scripted event (who is speaking or "
          "the scene focuses on) — writes it to the event participant list. arg0 = npc (char "
          "id), arg1 non-zero also clears a status flag on that slot. Used at scene start.",
          ["npc (char id)", "clear flag (0/1)"]),
    553: ("SetNpcScriptedPresence", "actor",
          "Set or clear the 'presence-locked / scripted' bit (record +52 bit 0x800000) on one "
          "or more NPCs. arg0 = flag (0 = clear, 1 = set), followed by npc ids; with no ids it "
          "applies to all 23 villagers. Locks NPCs into the scene's control.",
          ["flag (0=clear, 1=set)", "npc id …"]),
    554: ("SetNpcScriptedPresence", "actor",
          "Alias of op 553 (same handler): set/clear the scripted-presence bit on NPCs.",
          ["flag (0=clear, 1=set)", "npc id …"]),
    555: ("SetNpcBubbleFlavor", "dialogue",
          "Set an NPC's ambient dialogue-bubble flavor (record +26) — which floating "
          "speech-bubble variant it shows (mood / '!' / '?' etc). arg0 = npc (char id), arg1 "
          "= flavor id. See project_rf4s_dialogue.md.",
          ["npc (char id)", "flavor id"]),
    556: ("SetNpcBubbleFlavor", "dialogue",
          "Alias of op 555 (same handler): set an NPC's dialogue-bubble flavor.",
          ["npc (char id)", "flavor id"]),
    560: ("StageSceneNpcs", "flow",
          "At cutscene start, stage the scene's NPCs + companions and expose the 4 "
          "participating NPC ids into the VM output slots (so the script can reference them). "
          "Marks the villagers as 'in scene'. No args. A scene-setup op.",
          []),
})

# ---- quest-request lifecycle ops decoded 2026-07-11 (507-536) — see docs/23 ---------
_M.update({
    507: ("PopulateNpcQuestRequest", "quest",
          "Fill the current NPC's daily quest-request slot with a 'bring me [item]' request "
          "(into g_npcDailyRequestArray). arg0 = target item id (0 = auto-pick from the daily "
          "wanted list), arg1 = required count (0 = random 1-4), further args = category ids "
          "for alternate acceptable items. Writes success to the VM output. The base runtime "
          "quest generator; the PopulateQuestKindN ops are its templated variants.",
          ["target item id (0=auto)", "count (0=random)", "category alt …"]),
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
          "Weapons!', (5,0) = 'Befriend Monsters!'. IDA-verified 2026-09-01; formerly "
          "'PopulateQuestKind8BackrefLiteralAlts' (the 'alternate objective items' reading "
          "was wrong — the literals are the REWARDS).",
          ["goal number (level/count to reach)", "reward item ids (variadic, literal)"]),
    525: ("QuestOnComplete", "quest",
          "Run the quest-completion handler for the current request — award friendship / "
          "rewards and mark the request done. Fired when the player fulfils an NPC's request.",
          []),
    528: ("QueryQuestRewardItem", "quest",
          "Read the reward item id at a given index of the current quest into the VM output. "
          "arg0 = reward slot index.",
          ["reward index"]),
    529: ("ClearQuestRewardTemplates", "quest",
          "Clear all of the current NPC's staged quest-reward templates. No args. Used when "
          "abandoning or resetting a quest offer.",
          []),
    530: ("CommitQuestAcceptance", "quest",
          "Commit the player's acceptance of the offered quest — moves it from 'preview' to "
          "an active daily request on the NPC. The second step of the two-step accept "
          "(preview → commit).",
          []),
    531: ("QuestSceneTeardown", "quest",
          "Tear down the quest-offer scene and clear its staged rewards. No args. Called when "
          "the request-board / quest dialogue closes.",
          []),
    532: ("QueryNpcQuestPreview", "quest",
          "Read a preview of the current interaction NPC's available quest request into the "
          "VM output (so the dialogue can describe it before the player accepts). No args.",
          []),
    535: ("QueryQuestRemainingByItem", "quest",
          "Read how many of an item are still needed across active quest requests into the VM "
          "output. arg0 = item id. For 'you still owe me N of these' dialogue.",
          ["item id"]),
})

# ---- remaining companion move/invuln/query ops decoded 2026-07-11 (494-504) ---------
_M.update({
    494: ("SetCompanionInvulnerable", "companion",
          "Set or clear a companion's invulnerability guard (control_flags bit 4) — the "
          "companion counterpart of SetActorInvulnerable (op 141). arg0 = companion slot "
          "(0 or 1; >=2 = both). arg1 = 0 sets the guard (invulnerable), non-zero clears it. "
          "Wrap scripted combat so companions can't be downed.",
          ["slot (0/1, >=2=both)", "clear (0=guard on, else off)"]),
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
    338: ("CheckNpcSchedule", "query",
          "Check whether an NPC is currently on its EXPECTED schedule and read that schedule id. "
          "arg0 = NPC char id (0 falls back to the player's spouse via the wife-id game flag). "
          "Writes 1/0 to the main VM output — 1 if the NPC's current schedule id equals the "
          "scene's pre-set expected-schedule field — and the NPC's season-adjusted current "
          "schedule id to the second output. Used to gate dialogue on where an NPC is supposed "
          "to be right now.",
          ["npc (char id, 0=spouse)"]),
    339: ("GetNpcSchedule", "query",
          "Read an NPC's current schedule id (which daily-itinerary slot it is in right now) "
          "into the VM output. arg0 = NPC char id. Schedules below 0x40 are season-adjusted: the "
          "current season index is added unless it is Winter. Lets a script branch on an NPC's "
          "present activity/location.",
          ["npc (char id)"]),
    398: ("QueryUnusedPoses", "query",
          "Read 1 iff the player has any UNUSED unlocked alternate pose available. Scans the 16 "
          "alternate-pose unlock flags (GameFlags 729-744), skips the pose already in use, and "
          "builds an availability bitmask into the scene's choice-visibility field (the same one "
          "op 610's choice menu reads). Used to offer a 'change pose' menu only when there is an "
          "unused pose to switch to. arg0 = invert flag.",
          ["invert (0/1)"]),
    426: ("IsExtrasSlotFull", "query",
          "Read 1 iff the player's equip-extras slot (the single extra/accessory slot at "
          "inventory +24) currently holds at least one of a valid item. Writes the boolean to the "
          "VM output so a script can test whether that slot is occupied before offering to fill "
          "it. Takes no arguments.",
          []),
    427: ("MaxWeaponSkills", "actor",
          "Set the player's six weapon skills (Sword, Long Sword, Spear, Axe/Hammer, Dual Blade, "
          "Glove) all to level 30 and refresh the weapon-skill rank-unlock bits — a scripted/dev "
          "mastery grant (e.g. a New Game+ starter). Takes no arguments.",
          []),
    428: ("TakeItem", "item",
          "Remove (consume) N of an item from ANY of the player's containers — backpack, "
          "equipped-extras, every inventory page, storage, weapon rack, closet, tool box, "
          "shipping bin, fridge, bookshelf, and rune abilities — scanned in priority order until "
          "the demand is met. arg0 = item id, arg1 = count, arg2 = quality filter (when > 0, only "
          "removes copies whose quality byte is 0). Plays the 'item removed' jingle when finished.",
          ["item id", "count", "quality filter (>0=plain only)"]),
})

# --- dialogue-box descriptor writers (formerly mislabeled 'NpcFriendshipEntries' ops) --------
# These write into the shared dialogue state block (g_gameGlobalsSlotTable slots 3/9), which the
# speech-box loaders/state-machine read every frame. IDA handlers renamed accordingly; verified
# by tracing Dialogue_LoadAndShowText / Dialogue_LoadEventLineWithPortrait / DialogueBox_TickStateMachine.
#   entries[9] = active line descriptor: LOWORD=text entry index/kind, BYTE2=speaker side
#                (2 = secondary/right nameplate), BYTE3 = per-frame hold countdown.
#   entries[3] = auto-advance timer: HIDWORD=mode (0 off / 1 auto-by-length / N fixed frames), LODWORD=timer.
_M.update({
    614: ("SetDialogueSpeaker", "dialogue",
          "Set which side speaks the NEXT dialogue line (byte 2 of the active line descriptor). "
          "Value 2 = secondary/right-side speaker: the nameplate + text box render on the right "
          "using the question/choice-bubble widgets and recoloured nameplate. Any other value = "
          "the normal left speaker. Lets a script flip the apparent speaker between two on-screen "
          "characters.",
          ["side (2=right/secondary, else left)"]),
    699: ("SetDialogueSpeakerIf", "dialogue",
          "Conditional form of SetDialogueSpeaker (op 614): if arg0 is non-zero, mark the next "
          "line as spoken by the secondary (right-side) speaker (descriptor byte 2 = 2); if zero, "
          "leave the current speaker side unchanged. Handy for 'if this NPC is present, put the "
          "line on their side'.",
          ["condition (non-zero = right speaker)"]),
    624: ("SetDialogueHoldFrames", "dialogue",
          "Seed the dialogue box's per-frame hold countdown (byte 3 of the line descriptor). The "
          "speech-box state machine decrements it once per frame, so this briefly delays the box "
          "for arg0 frames (0-255). Used to pace a line before it starts advancing.",
          ["frames (0-255)"]),
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
    652: ("GetSceneWord348", "query",
          "Read the scene context's state word at offset +348 into the VM output. A scene-local "
          "scratch/status value whose meaning depends on the individual scene script.",
          []),
    658: ("GetSceneWordPair112", "query",
          "Read the scene context's word pair at offsets +112 and +114 into the two VM outputs "
          "(main + second). These are scene-local coordinate/scratch words also used by the NPC "
          "streaming/respawn ops, so they typically hold a tile (x, y).",
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
    566: ("AdvanceStoryMilestone", "flag",
          "Advance a main-story milestone and unlock its achievement. arg0 = progress level (1-3), "
          "arg1 = story-step id (6-17). Commits the story-progress game flag, broadcasts the story "
          "event to every NPC (updates their reactions), and — if this raises the recorded "
          "progress — unlocks the achievement mapped to that step. The core 'story just advanced' "
          "op for scenario cutscenes.",
          ["progress (1-3)", "story step (6-17)"]),
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
    567: ("GetTomorrowsBirthdayNpc", "query",
          "Read the char id of the NPC whose birthday is TOMORROW into the VM output (0 if none, "
          "or if the reminder for them is already accounted for today). Drives 'don't forget "
          "about X's birthday tomorrow!' reminder dialogue.",
          []),
    570: ("GetTodaysRequestNpc", "query",
          "Read the char id of the NPC who has an active daily request/order posted today into the "
          "VM output (0 if none). Lets a script point the player at today's request-giver.",
          []),
    580: ("GetHeldItemStats", "query",
          "Read the currently-held item's display stats into the VM outputs (6 values starting at "
          "the main output). Weapon/armor: [0] equipped flag, [1] sub-value, [2] equip type, [3] "
          "ATK%, [4] DEF% (percentages clamped to +/-100), [5] item id. Any other item: [0] "
          "equipped flag, [1] craft tier, [2] a byte field, [3] craft level, [5] item id. Used to "
          "render the held-item tooltip inside scripted menus.",
          []),
    581: ("CheckFishRecord", "query",
          "Compare a fish's size rank (arg0) against the saved 'largest fish caught' record and "
          "update the record if it is bigger. Main output = 0 for a new record (and the record is "
          "saved), 2 if it ties the record, 1 if smaller; the previous max is written to the "
          "second output. Drives the 'biggest catch!' fishing dialogue.",
          ["fish size rank"]),
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
    577: ("GetEventParticipants", "query",
          "Read the current calendar event's four participants (npc id + day, into the VM outputs) "
          "and compute the event's score from the calendar-event archive (16340) into the main "
          "output. Empty participant slots are consumed as it scans. Used by festival/event "
          "cutscenes to list who took part and how they scored.",
          []),
    579: ("GetSceneEventFlags", "query",
          "Read the scene's event-state triplet into three VM outputs: a word at scene+546, a byte "
          "at scene+543, and a word at scene+548. Scene-event bookkeeping fields.",
          []),
    569: ("RankFestivalContestants", "query",
          "Roll and rank the top 3 festival-contest competitors (friendship-weighted scores, gated "
          "by the active festival flag) and write their (npc id, score_lo, score_hi) tuples into "
          "the scene result registers (9 dwords at ctx+64..+100) for the contest-results cutscene. "
          "arg0/arg1 tune the roster/scoring. (Recategorized flow->query: returns data to the VM.)",
          ["contest param 0", "contest param 1"]),
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
    431: ("HasItem", "query",
          "Query whether the player owns at least [count] of an item at quality >= [quality], "
          "searching the backpack + equip-extras slot. Main output = 1 if found, else 0; the "
          "second output = a per-slot flag bit of the matched slot. arg2 quality is 1-based (pass "
          "0 to accept any quality). The classic 'do you have N of item X?' dialogue gate.",
          ["item id", "min count", "min quality (0=any)"]),
    434: ("GetItemGoldValue", "query",
          "Read an item's base gold value — a single unit at quality 0 — into the VM output. arg0 "
          "= item id. Use it to show or compute a price in a scripted menu.",
          ["item id"]),
    435: ("GetItemBuyPrice", "query",
          "Read an item's base BUY price into the VM output (the metadata buy-price field, the "
          "amount a shop charges before any modifier). arg0 = item id. Contrast GetItemGoldValue "
          "(op 434), which is the SELL value.",
          ["item id"]),
    436: ("IsItemStackable", "query",
          "Read 1 if the item can stack (its metadata stack field is > 1), else 0. arg0 = item id.",
          ["item id"]),
    437: ("NpcWantsItem", "query",
          "Query whether item [arg0] appears in NPC [arg1]'s offer / present list (the gift-"
          "preference archive 14850). Main output = 1 if the item is in that NPC's list. Used to "
          "gate 'does this NPC want this item?' dialogue.",
          ["item id", "npc (char id)"]),
    626: ("GetInventoryFlagBit", "query",
          "Read bit [arg0] of the player's inventory-flags word into the VM output — a generic "
          "inventory state-bit test (0 or 1).",
          ["bit index"]),
})

# --- tile-object (placed map object) ops (588-594) ---------------------------------------------
# Decompiled + verified. Tile objects are the 64-slot map-entity registry (g_mapEntityRegistry_
# 64slots); the 'active' state is the sign bit of each record's first word. Scripts use these to
# place/pick up/query throwable ground objects (e.g. the request box, festival props).
_M.update({
    588: ("IsTileObjectActive", "query",
          "Query whether a placed map object (tile object) holding item [arg0] is currently active "
          "on the map — searches the 64-slot map-entity registry. Main output = 1 if found, else "
          "0.",
          ["item id"]),
    589: ("PlayerPickUpObject", "actor",
          "Make the player pick up / carry the scene's target object: snaps the player to the "
          "ground if airborne, places the object one tile away, and starts the carry. The 'come "
          "pick this up' cutscene op. Takes no arguments.",
          []),
    590: ("OpenRequestBox", "item",
          "Open the scene's request box: spawn item 1022 (the Box) and item 1023 (the Note) at the "
          "object's position with a dirt-cloud puff, then clear the tile-object slot and destroy "
          "the box actor. This is the 'open Eliza's Request Box' interaction. Takes no arguments.",
          []),
    591: ("ClearAllTileObjects", "effect",
          "Clear the active flag of every placed tile object (mass reset of the 61 map-object "
          "records) and zero their state. Takes no arguments.",
          []),
    592: ("CanPlaceTileObject", "query",
          "Query whether there is room for another tile object matching item [arg0] (pass 0 for "
          "any): main output = 1 when fewer than 16 of them are currently active. The 'can I place "
          "another?' gate.",
          ["item id (0 = any)"]),
    593: ("PickRandomTileObject", "effect",
          "From a variadic list of candidate item ids, randomly pick one that currently has an "
          "active tile object matching the input context (MMIX weighted-random; ~1/8 of the time "
          "it picks nothing). Main output = picked item id, or 0. Used to randomly choose which "
          "placed object to trigger.",
          ["candidate item ids (variadic)"]),
    594: ("CommitGrabbedObject", "actor",
          "If the player is holding a grabbed object that is flagged throwable, commit it into the "
          "bag. A pickup-convenience op. Takes no arguments.",
          []),
})

# --- child-NPC records / weather transition / NPC state byte (448-475) --------------------------
# Decompiled + verified. Child friendship records = g_ChildFriendshipTable, 8-byte (4x int16) per
# child, indexed (childId-24) for child NPCs 24..47. Weather flags live on g_weather.
_M.update({
    470: ("GetChildFriendLevel", "query",
          "Read a child NPC's friendship level (record byte +1) into the VM output. arg0 = child "
          "char id (24-47); out-of-range yields 0.",
          ["child (char id 24-47)"]),
    471: ("GetChildFriendPoints", "query",
          "Read a child NPC's friendship points (the word at record +4) into the VM output. arg0 = "
          "child char id (24-47).",
          ["child (char id 24-47)"]),
    472: ("SetChildGrowthValue", "actor",
          "Write a child NPC's growth/level value (record byte +2, distinct from the friendship-"
          "level byte; capped below 65). arg0 = child char id (24-47), arg1 = value (0-64).",
          ["child (char id 24-47)", "value (0-64)"]),
    473: ("RollChildDailyPref", "query",
          "Roll-once-and-remember a child NPC's daily random preference in [0, range). The first "
          "call this session rolls it (MMIX RNG) and stores it in the record; later calls return "
          "the stored value, so it stays stable across save reloads. arg0 = child char id (24-47), "
          "arg1 = range.",
          ["child (char id 24-47)", "range"]),
    475: ("SetNpcStateByte", "actor",
          "Write a per-NPC state byte (offset +58 in the NPC record array) for npc [arg0] (< 48) — "
          "a relationship/state-machine flag byte. arg1 = value. Invalid npc ids trap as a script "
          "error.",
          ["npc (char id, <48)", "value"]),
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
# bits of qword_7FF6D72AB300 (bit0 = force full sync, bit1 = secondary flag).
_M.update({
    481: ("GetPartyMemberId", "query",
          "Read a party member's identity field (task +8) by slot into the VM output: arg0 = 0 for "
          "companion 1, 1 for companion 2. Returns 0 if that slot is empty. Used to branch "
          "dialogue on who is currently in the party.",
          ["slot (0=companion 1, 1=companion 2)"]),
    482: ("GetPartyMemberId", "query",
          "Read a party member's identity field (task +8) by slot into the VM output (duplicate of "
          "op 481): arg0 = 0 for companion 1, 1 for companion 2. Returns 0 if the slot is empty.",
          ["slot (0=companion 1, 1=companion 2)"]),
    484: ("SyncBothCompanions", "companion",
          "Bring both companions into the current scene with a forced full sync (sets sync bit 0). "
          "Takes no arguments. Use SyncBothCompanionsWithFlags (op 485) when you need finer "
          "control over the sync mode.",
          []),
    485: ("SyncBothCompanionsWithFlags", "companion",
          "Bring both companions into the current scene, configuring the sync mode: arg0 non-zero "
          "sets sync bit 1, arg1 non-zero sets sync bit 0 (force full sync). The general-purpose "
          "companion scene-sync op.",
          ["flag1 (sync bit 1)", "flag2 (force full sync)"]),
    486: ("SyncCompanionByCharId", "companion",
          "Bring the ONE companion whose char id matches [arg0] into the scene, with the same two "
          "sync flags as op 485. arg0 = 0 matches the scene's current actor, arg0 = 22 looks up the "
          "married partner via game flag, otherwise it is a direct char-id match.",
          ["char id (0=scene actor, 22=spouse)", "flag1 (sync bit 1)", "flag2 (force full sync)"]),
    489: ("SetCompanionMetFlag", "companion",
          "Toggle both companions' 'already met / scripted-present' record flag: arg0 == 0 sets it "
          "(mark as met), non-zero clears it — and when cleared outside months 6-18, queues each "
          "companion's first-meeting encounter event. Used at a cutscene's end to control whether "
          "first-time-meeting dialogue fires.",
          ["clear (0=mark met, else clear + maybe queue meeting)"]),
})

# --- dungeon 'throw'/delivery queue + RNG-advance ops (524-552) --------------------------------
# Decompiled + verified. The 'general throw' queue is up to 20 item-count entries (24B stride, in
# g_npcDailyRequestArray +350 region) used during dungeon scenes to track item-gather sub-goals.
# Entry state byte: 1 = pending, 2 = active. 524/548 are duplicate opcodes.
_M.update({
    524: ("CommitThrowQueue", "flow",
          "Promote every pending entry in the dungeon 'throw'/delivery queue from pending to "
          "active, committing a batch of populated entries at once. Only takes effect while in a "
          "dungeon area. Takes no arguments.",
          []),
    548: ("CommitThrowQueue", "flow",
          "Promote every pending entry in the dungeon 'throw'/delivery queue to active (duplicate "
          "of op 524). Only takes effect in a dungeon area. Takes no arguments.",
          []),
    551: ("ResetThrowQueue", "flow",
          "Clear the dungeon 'throw'/delivery queue: reset the entry count to 0 and wipe all 20 "
          "entry templates. Takes no arguments.",
          []),
    552: ("GetThrowQueueRemaining", "query",
          "Read how many more of item [arg0] are still needed by the dungeon 'throw'/delivery "
          "queue (need minus have, floored at 0) into the VM output. The 'how many left to gather?' "
          "check.",
          ["item id"]),
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
    403: ("GetMonsterRosterAbsent", "query",
          "For monster ids 1-3, write to the VM outputs whether each is NOT active in the monster "
          "roster (inverted presence flag, fixed context). Produces three outputs. (Formerly "
          "mislabeled a 'fishing' op.)",
          []),
    404: ("GetMonsterRosterPresent", "query",
          "For monster ids 1-3, write to the VM outputs whether each IS active in the monster "
          "roster within input context [arg0]. Produces three outputs. (Formerly mislabeled a "
          "'fishing' op.)",
          ["input context"]),
    408: ("CountLivingEnemies", "query",
          "Count the living monsters on the field EXCLUDING the two boss char ids (141/142) into "
          "the VM output. The 'kill all the trash before the boss appears' gate.",
          []),
    409: ("CountTamedFarmMonsters", "query",
          "Count farm monsters flagged 'tamed today' (flag bit 0x1000) across all 200 farm slots "
          "into the VM output.",
          []),
    536: ("RequestBoxFirstSubmit", "quest",
          "Run the 'first request-box quest submitted today' pipeline: mark the active request "
          "claimed, unlock the submit achievements, play the shared + per-quest reward scenes, and "
          "schedule tomorrow's request reroll. Does nothing if already submitted today or there is "
          "no active quest. Takes no arguments. Pairs with RequestBoxClaimFinalize (op 549).",
          []),
    549: ("RequestBoxClaimFinalize", "quest",
          "Finalize and clean up the request-box reward claim (counterpart to op 536): set the "
          "completion flags, unlock the reward achievements, dispatch the reward scenes, reset the "
          "throw queue, refresh every NPC's schedule, clear all NPCs' request state, award prince "
          "points, and unregister the reroll callback. Takes no arguments -- the handler "
          "(Script_VMOp_OnRequestBoxQuestClaimedFinalize) reads only the implicit scene state; "
          "the corpus emits it with zero operands (cnt=0 in all occurrences).",
          []),
    557: ("SetNpcRecognitionFlags", "flag",
          "Write a per-NPC packed game-flag (base id 1451 + npc id) = [arg0] for each npc id in "
          "the variadic list (an npc id of 0 falls back to the married partner). These are the 23 "
          "per-NPC recognition flags (1451-1473); like op290/op698 they go through "
          "GameFlags_WritePacked -- a graded packed-flag write, NOT one of the ~30 named Steam "
          "achievements (the old 'UnlockNpcAchievements' name overstated it).",
          ["value", "npc ids (variadic)"]),
    558: ("SetNpcRecognitionFlags", "flag",
          "Write a per-NPC packed game-flag (base id 1451 + npc id) = [arg0] for each npc id in "
          "the variadic list (duplicate of op 557; npc id 0 = the married partner). Per-NPC "
          "recognition flags 1451-1473 via GameFlags_WritePacked -- a packed-flag write, not a "
          "Steam achievement.",
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
    663: ("DisableActorHpRegen", "actor",
          "Set the target actor's HP-regen rate to 0, stopping passive HP recovery. arg0 = char id "
          "(0=player, <48=NPC, >=48=event actor). Used so a scripted actor can't heal itself mid-"
          "battle.",
          ["char id (0=player, <48=NPC, >=48=event)"]),
    664: ("LockActorMaxSp", "actor",
          "Force the target actor to maximum SP/RP (regen set to -1) and set a locked state, also "
          "releasing any companion-AI claim on it. arg0 = char id (0=player, <48=NPC, >=48=event "
          "actor). Freezes an actor in a controlled state for a cutscene.",
          ["char id (0=player, <48=NPC, >=48=event)"]),
    653: ("ClearShopSelectionA", "item",
          "Reset shop selection slot A to 'none' (writes the no-selection sentinel into the current "
          "shop task's work buffer). Takes no arguments.",
          []),
    654: ("ClearShopSelectionB", "item",
          "Reset shop selection slot B to 'none' (no-selection sentinel in the shop work buffer). "
          "Takes no arguments.",
          []),
    655: ("ClearShopSelectionC", "item",
          "Reset shop selection slot C to 'none' (no-selection sentinel in the shop work buffer). "
          "Takes no arguments.",
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
    413: ("SetDialogueState8", "dialogue",
          "Set a low-level dialogue-box auxiliary state value (game-globals slot 8, one of the "
          "aux speaker/line-descriptor fields cleared together with slots 7 and 9 when the "
          "dialogue HUD tears down). arg0 = value.",
          ["value"]),
    414: ("GetChoiceIndexAndItem", "query",
          "Read the last scripted item-selection result into TWO VM outputs: query register 0 = "
          "the choice slot index (0-7, extracted from scene-ctx +116 bits 6-8), register 1 = the "
          "associated item id (11-bit, from ctx+40 field +380). DISTINCT from GetChoiceResult "
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
    440: ("GetNpcSpecies", "query",
          "Read an NPC/monster's species id from the NPC-parameter data (rf3NpcParam) into the VM "
          "output. arg0 = char id. Lets a script tell what species an actor is (e.g. 'is this a "
          "monster?').",
          ["char id"]),
})

# --- calendar-event-actor facing / scripted movement / map refresh / item-hand (105-209) --------
# Decompiled + verified. Several are core cutscene primitives (face/move/give-item). 105 is stubbed.
_M.update({
    105: ("QueryCalendarEventStub", "query",
          "Always writes 0 to the VM output — the intended calendar-event lookup is stubbed on the "
          "PC port (the search over the event registry runs but its result is discarded). Treat as "
          "returning 0.",
          []),
    110: ("FaceEventActor", "actor",
          "Make an actor turn to face a calendar-event-bound actor and start an animation. arg0 = "
          "char id (0=player, 1-47=NPC), arg1 = event key (calendar-event registry lookup), arg2 = "
          "animation id. NPC targets also re-align a paired sibling. The cutscene 'turn to look at "
          "X and react' op.",
          ["char id (0=player, 1-47=NPC)", "event key", "anim id"]),
    143: ("MoveToCoords", "actor",
          "Queue a scripted 'move to tile coordinates' command for the scene's active mover. arg0/"
          "arg1 = target tile x/y, arg2 = distance, arg3 = 0 to walk / non-zero to run (~20% "
          "faster). Choreographs NPC/player movement during a cutscene.",
          ["tile x", "tile y", "distance", "run (0=walk)"]),
    205: ("RefreshMapTiles", "effect",
          "Force a full refresh of the current map's tiles — mark every tile dirty and recompute "
          "its visibility/attribute flags, then flag the player for refresh. Call after a scripted "
          "map or tile-attribute change so it redraws. Takes no arguments.",
          []),
    209: ("GiveOrDropItem", "item",
          "Materialize an item and place it: arg0 = target (0 = the player, 1-47 = an NPC slot), "
          "arg1 = item id. NPCs receive it in-hand; the player holds it, or — if the player can't "
          "hold it — it drops on the ground with a puff. The 'NPC hands you a gift / holds up an "
          "item' cutscene primitive (uses the pending-interaction record for item attributes).",
          ["target (0=player, 1-47=NPC)", "item id"]),
})

# --- npc alt-move / player-effect wait / scene-control bits / hardcoded item check (91-370) ------
# Decompiled + verified. Scene-bit ops write scene-local scratch flags; 198 blocks the VM.
_M.update({
    121: ("NpcMoveAlt", "actor",
          "Start an NPC moving toward tile (arg1, arg2) using the ALTERNATE movement mode (kind "
          "2048 — a dash/special move, distinct from the normal walk/run mover). arg0 = npc char "
          "id (<48), arg3 = speed, arg4 = target parameter. Sets the NPC's 'moving' flag.",
          ["npc (char id <48)", "tile x", "tile y", "speed", "target param"]),
    122: ("NpcMoveAlt", "actor",
          "Start an NPC moving toward a tile using the alternate movement mode (kind 2048), "
          "duplicate of op 121. arg0 = npc char id (<48), arg1/arg2 = tile x/y, arg3 = speed, "
          "arg4 = target parameter.",
          ["npc (char id <48)", "tile x", "tile y", "speed", "target param"]),
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
    384: ("ResetSfxScratch", "audio",
          "Reset the SFX/BGM dispatcher's per-channel scratch state (zeroes ~20 bytes of capture "
          "work vars). Low-level audio housekeeping. Takes no arguments.",
          []),
    402: ("SendMonsterToFarmOrClearFlags", "effect",
          "Dual-purpose monster-farm op: arg0 == -1 sends the current interaction monster to the "
          "farm (if it is a valid monster); any other value is a farm-slot index whose status "
          "flags (bits 0x600) get cleared.",
          ["arg (-1 = send to farm, else farm slot)"]),
    461: ("SuppressRewardJingle", "audio",
          "Suppress the jingle of the NEXT reward popup (sets the scene's suppress bit that the "
          "reward ops check). Pairs with GrantFestivalRewards (op 462). Takes no arguments.",
          []),
    462: ("GrantFestivalRewards", "item",
          "Roll and grant up to 8 festival/event rewards from a reward template and show the reward "
          "popup (with the completion jingle unless silenced by op 461). Each variadic token "
          "chooses a roll strategy: 0x270D festival prize item, 0x270E shop-category roll, 0x270F "
          "generic loot, 0x2710 quest-specific loot; any other value is a literal item id.",
          ["reward tokens (variadic)"]),
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
    432: ("CheckCropPlantable", "query",
          "Check whether a seed can be planted on the tile the player is on, and read tile info. "
          "arg0 = seed item id. Outputs: main = plantable this season (1/0; Turnip Seed [39] is "
          "always plantable in Spring), then the tile's yield/pattern value, the crop sub-type, "
          "and a 'regrowing crop' flag. Gates the 'plant this here?' farming dialogue.",
          ["seed item id"]),
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
    479: ("StreamNpcAtPlayer", "actor",
          "Stream an NPC into the scene at the player's position and sync it as a companion "
          "(handles the marriage trigger). arg0 = npc char id, arg1 = scripted flag: non-zero sets "
          "the NPC's 'owned by cutscene / scripted-presence' record bit, zero clears it. Used to "
          "make an NPC appear beside the player for a scene.",
          ["npc (char id)", "scripted (0/1)"]),
    618: ("IsPickingUpItem", "query",
          "Read 1 if the player is currently mid-item-pickup (the pickup-icon animation task is "
          "active), else 0. Lets a script wait out a pickup before continuing.",
          []),
    633: ("ResetActionEventId", "flow",
          "Clear the last-dispatched action-event id (resets the action-trigger bookkeeping). Takes "
          "no arguments.",
          []),
    635: ("GetActionTriggerByte", "query",
          "Read action-trigger byte [arg0] (index clamped 0-2, from the scene's 3-byte trigger "
          "array) into the VM output. The read counterpart of SetActionTriggerByte (op 634).",
          ["index (0-2)"]),
    638: ("GetForecasts", "query",
          "Roll and read today/tomorrow/day+6 crop & weather forecast icons into four VM outputs "
          "(used by the Prince-Points HUD forecast display). Takes no arguments.",
          []),
    647: ("GetEffectCost", "query",
          "Read the cost of a town/prince development effect in a given currency into the VM "
          "output. arg0 = effect id, arg1 = currency index.",
          ["effect id", "currency index"]),
    650: ("GetLifetimeCropGold", "query",
          "Read the player's lifetime shipped-gold total for shipping category 0 (Crops) into the "
          "VM output (capped at 2,000,000,000). Takes no arguments.",
          []),
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
    676: ("GetConst20", "query",
          "Write the constant 20 to the VM output — a fixed capacity/limit sentinel used by a few "
          "scripts. Takes no arguments.",
          []),
    678: ("ClearTileAttribsInRect", "effect",
          "Clear the tile-attribute flags over a rectangle so the area becomes plain walkable "
          "ground (no special attribute) — used to stage an area for a cutscene. arg0/arg1 = x/y, "
          "arg2/arg3 = width/height, all in fine units (>>3 = tiles).",
          ["x (fine)", "y (fine)", "width (fine)", "height (fine)"]),
    690: ("GetNpcProgressAndProp", "query",
          "Read an NPC's progress/state value (record +252) into the main VM output, and a derived "
          "prop item id (base 676 + an NPC state byte, or 0) into the second output. arg0 = npc "
          "char id.",
          ["npc (char id)"]),
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
    307: ("GetMonthSeason", "time",
          "Read the calendar's month and season into the VM outputs: main output = month, second "
          "output = season (0=Spring, 1=Summer, 2=Fall, 3=Winter). Reads the display-snapshot "
          "calendar struct. Takes no arguments.",
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
        continue
    # null-slot filler: the dispatch table's default/padding entry resolves to an unrelated
    # engine symbol (the SoLoud bus vslot at the table's fill address). Opcode 0 and several
    # tail slots share it -> they are unbound (no real handler), not audio ops.
    if "BusInstance_SoLoud" in _tech or _tech.endswith("__vslot_002"):
        _add(_op, "(unbound)", "noop",
             "Unbound opcode -- the dispatch slot points at the table's default filler (no real "
             "handler), so the game's scripts never emit it. Reserved / removed in the PC port.", [])
        continue
    # empty handler slot: no symbol bound in the IDB -> opcode is never emitted
    if not _tech:
        _add(_op, "(unused)", "noop",
             "Empty dispatch slot -- no handler is bound to this opcode in the binary, "
             "so the game's scripts never emit it. Reserved / removed in the PC port.", [])
        continue
    # quest-request populate family: PopulateQuestRequestKind<N><shape>
    # These runtime ops fill the current NPC's daily quest-request slot with a randomized
    # "bring/craft/defeat" request built from template KIND N (see docs/23). The handler name
    # encodes the kind + the specifics (RandomCats / LiteralAlternates / TwoItems / Backref …).
    _qk = re.search(r"PopulateQuestRequestKind(\d+)(\w*)", _tech)
    if _qk:
        _n = int(_qk.group(1))
        _shape = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", _qk.group(2)).strip()
        _d = ("Populate the current NPC's daily quest-request slot using request template "
              "KIND %d" % _n)
        _d += (" (%s)." % _shape) if _shape else "."
        # Literal variants store the alternate objective items VERBATIM from args (no category
        # roll -- IDA-confirmed on op 510: "no Shop_RollByCategoryFromTable call"); the others
        # roll from categories (and some shapes -- SimpleNoAlts/TwoArgsNoItem -- carry no alts).
        if "Literal" in _qk.group(2):
            _d += (" A runtime quest generator whose alternate objective items are the EXPLICIT "
                   "literal item ids passed as args (stored verbatim — NO random category roll). "
                   "See docs/23.")
        else:
            _d += (" A runtime quest generator: rolls the objective item(s)/counts from the "
                   "request template (plus alternate items from categories where this shape has "
                   "them). See docs/23. Args are template-specific (item ids and category ids).")
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
# Ctrl-hover tooltip in the cutscene editor.
ARG_HINTS = {
    "face frame": "portrait face/expression frame (0 = neutral, 4 = open-mouth surprise)",
    "emote/mood": "speech-bubble emote id 186-192 (188 normal, 189 anger, 190 sad/'!', "
                  "191 smile/'?', 192 surprise); 0 = none",
    "target": "target actor reference (0x0100_00xx handle); 0 = the current speaker",
    "em entry id": "em.bin Event Manager entry id (0..271; named in emdeb.bin)",
    "flag id": "GameFlags bit id -- ENGINE base-relative (flag_id + g_gameFlagsBuffer[0]), "
               "not an emflags/emdeb offset",
    "value": "value to write (0 = clear / false)",
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
    "action id": "TriggerWorldAction dispatch id (see WORLD_INTERACTION_ACTIONS: 1=Save, "
                 "2=Load, 3=MessageBoard, 11=Calendar, 12=Storage, 23=Fridge, 25=BackupSaveNow, "
                 "45=Bookshelf, 53=ShippingBin, 54=Safe, 55=Wardrobe, 56=Toolbox, 58=Forge, 71=Crafting)",
    "kind": "fade kind (16 = fade to black; other values: fade colour / direction)",
    "duration_ms": "fade length in milliseconds",
    "mode": "opcode-specific mode selector (see the action id list on the tooltip)",
    "mode (1/-1)": "1 = add/set, -1 = remove/clear",
    "actor class": "BeginShopkeeperInteraction: shopkeeper NPC id -- routes to a per-NPC "
                   "day-off table (see the mnemonic tooltip). Legacy arg-name; equivalent "
                   "to 'shopkeeper npc'.",
    "shopkeeper npc": "NPC id (usually indirect via localvar[]) of the shopkeeper you're "
                      "talking to. Selects the day-off + shop-kind override. Vanilla ids: "
                      "6=Bado, 8=Dylas, 9=Arthur, 10=Porcoline, 11=Xiao Pai, 12=Lin Fa, "
                      "13=Amber, 14=Illuminata, 15=Doug, 16=Blossom, 17=Dolce, 18=Jones, "
                      "19=Nancy, 22=Son, 23=Daughter, 25=? -- other/anon NPCs fall into "
                      "the default (day 6 / kind 26) case",
    "shop id": "shop dispatch id (75-89 in vanilla) -- see WORLD_INTERACTION_ACTIONS. "
               "75=WeaponFarmTool, 76=Accessory, 77=ExcavatedEquipment, 78=Hospital, "
               "79=Flower(alt), 80=Flower, 81/89=variants, 82=Furniture, 83=Ability, "
               "84=Magic, 85=Jewel, 86=SakuTuner, 87=Yue, 88=Restaurant",
    "actor ctx": "actor / scene context reference (usually `globalvar[...]` holding an "
                 "actor slot pointer or a scene handle)",
    "kind id": "PlayScriptedBeat: numeric routing kind. 1000-1099 -> credit-roll-scale "
               "variant, 100-999 or 1100+ -> scripted-event variant, 0-99 -> normal",
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
    return "%s(%s)" % (mnemonic(op), ", ".join(_short(n) for n in arg_names(op)))


_OP_BY_MNEMONIC = None


def op_from_mnemonic(name):
    """Reverse lookup: opcode number for a curated mnemonic (case-insensitive), or None.

    Lets the editor accept an opcode by NAME instead of a raw number. Placeholder names
    ((unbound)/(unused)/nop/invalid) are excluded. For aliased mnemonics (e.g. SetSpeakerMC
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
        if _m and _m not in skip and q in _m.lower() and _m.lower() not in seen:
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
    100: "Gold", 102: "ArmorDef", 103: "FarmTameCount",
    104: "Skill", 105: "Stone", 106: "Compost", 107: "MaxSkillLevel",
}
# 40-slot skill table (rf3TxtSkill_split2_1.eng); id -> name, matching skill_array indexing.
SKILL_NAMES = [
    "Short Sword", "Long Sword", "Spear", "Axe/Hammer", "Dual Blades", "Fist",
    "Fire", "Water", "Earth", "Wind", "Light", "Dark", "Love",
    "Farming", "Logging", "Mining", "Fishing", "Cooking", "Forging", "Chemistry",
    "Crafting", "Searching", "Walking", "Sleeping", "Eating", "Defense",
    "Resist Poison", "Resist Seals", "Resist Paralysis", "Resist Sleep",
    "Resist Fatigue", "Resist Cold", "Resist Knockout", "Bathing", "Taming",
    "Throwing", "Leadership", "Bartering", "Dummy", "Dummy 2",
]


def skill_name(i):
    return SKILL_NAMES[i] if 0 <= i < len(SKILL_NAMES) else "skill#%d" % i


_STAT_QUERY_OPS = {_op for _op, _t in TECHNICAL.items() if "QueryPlayerStatByCharCode" in _t}

# Author-facing name + arg labels for the query op (overrides the humanized fallback).
for _op in _STAT_QUERY_OPS:
    _add(_op, "QueryPlayerVariable", "query",
         "Read a player variable chosen by an ASCII char-code arg: 'd'(100)=Gold, "
         "'f'(102)=ArmorDef, 'g'(103)=FarmTameCount, 'h'(104)=Skill (2nd arg = skill id), "
         "'i'(105)=Stone, 'j'(106)=Compost, 'k'(107)=MaxSkillLevel; a bare index <=39 reads "
         "that skill's level. Result goes to the scene query slot.", ["variable", "skill id"])


# ---- TriggerWorldInteractionAction dispatch table (op 375) ------------------------
# Reverse-engineered from World_DispatchInteractionEvent at RF4S.exe+0x1F75B0.
# id -> (short label shown in the picker, one-line description)
# Bank 252 @0x462a (dupe @ bank 292 @0x4c64) is a DEV MENU whose 34 choice labels
# name each of these actions unambiguously. Anywhere a row is annotated
# "[dev-menu]" below, the label came straight from the vanilla script text.
# The remaining rows are from the World_DispatchInteractionEvent dispatch at
# RF4S.exe+0x1F75B0 (behaviour was RE'd; naming is best-effort).
WORLD_INTERACTION_ACTIONS = {
    1:  ("Save",                    "Save menu (writes diary/save). [dev-menu]"),
    2:  ("Load",                    "Load menu (title-screen slot picker). WARNING: only safe "
                                    "from a dev-menu / title context -- loading mid-gameplay "
                                    "leaves NPC AI state stale and crashes. [dev-menu]"),
    3:  ("MessageBoard",            "Open the Bulletin Board / Message Board. [dev-menu]"),
    4:  ("NameEntry_Hero",          "Open the software-keyboard to rename the main character (the {Hero} template). "
                                    "In dev-menu use, paired with action 90 as an immediate follow-up. Dispatch goes "
                                    "through the generic name-entry sub-id 11 (rf4NameEntryTask). Gated by "
                                    "g_saveConfigFlags & 0x40 -- dev-only unless the flag is set. [dev-menu]"),
    5:  ("NameEntry_Farm",          "Open the software-keyboard to rename the farm (the {Farm} template). "
                                    "Dispatch through name-entry sub-id 14. [dev-menu]"),
    6:  ("NameEntry(subId=15)",     "Software-keyboard name-entry via sub-id 15 (target unknown; not used by the dev menu)."),
    7:  ("NameEntry(subId=16)",     "Software-keyboard name-entry via sub-id 16 (target unknown)."),
    8:  ("NameEntry(subId=17)",     "Software-keyboard name-entry via sub-id 17 (target unknown)."),
    9:  ("NameEntry(subId=18)",     "Software-keyboard name-entry via sub-id 18 (target unknown)."),
    10: ("ShippingHistory",         "Open the Shipping History screen. [dev-menu]"),
    11: ("Calendar",                "Open the Calendar screen. [dev-menu]"),
    12: ("Storage",                 "Open a Storage / chest UI. [dev-menu]"),
    14: ("Chemistry",               "Open the Chemistry crafting station "
                                    "(fires ScriptAction_39 first, then _32). [dev-menu]"),
    16: ("Cooking",                 "Open Cooking with no specific tool required. [dev-menu]"),
    17: ("Cook_FryingPan",          "Open Cooking at the Frying Pan station. [dev-menu]"),
    18: ("Cook_Pot",                "Open Cooking at the Pot station. [dev-menu]"),
    19: ("Cook_Oven",               "Open Cooking at the Oven station. [dev-menu]"),
    20: ("Cook_Mixer",              "Open Cooking at the Mixer station. [dev-menu]"),
    21: ("Cook_Steamer",            "Open Cooking at the Steamer station. [dev-menu]"),
    22: ("Cook_Knife",              "Open Cooking at the Knife station. [dev-menu]"),
    23: ("Fridge",                  "Open the Fridge (item transfer). [dev-menu]"),
    24: ("MonsterManagement",       "Open the Monster Management screen. [dev-menu] "
                                    "(disp handler previously looked like a nop; the dev "
                                    "menu proves it does open the monster-manage UI.)"),
    25: ("BackupSaveNow",           "Autosave / rf3BackupSaveDataBuild -- writes a backup save immediately."),
    26: ("BackupSaveNow",           "Autosave / rf3BackupSaveDataBuild (same as 25)."),
    27: ("(cleanup only)",          "Clears pending state; no trigger fired."),
    28: ("NameEntry_BarnA",         "Open the software-keyboard to rename shack A (the {Barn0} template). "
                                    "Dispatch through name-entry sub-id 19. [dev-menu]"),
    29: ("NameEntry_BarnB",         "Rename shack B ({Barn1}). Sub-id 20. [dev-menu]"),
    30: ("NameEntry_BarnC",         "Rename shack C ({Barn2}). Sub-id 21. [dev-menu]"),
    31: ("NameEntry_BarnD",         "Rename shack D ({Barn3}). Sub-id 22. [dev-menu]"),
    32: ("NameEntry_BarnE",         "Rename shack E ({Barn4}). Sub-id 23. [dev-menu]"),
    33: ("NameEntry_BarnF",         "Rename shack F ({Barn5}). Sub-id 24. [dev-menu]"),
    34: ("NameEntry_BarnG",         "Rename shack G ({Barn6}). Sub-id 25. [dev-menu]"),
    35: ("NameEntry_BarnH",         "Rename shack H ({Barn7}). Sub-id 26. [dev-menu]"),
    36: ("NameEntry_BarnI",         "Rename shack I ({Barn8}). Sub-id 27. [dev-menu]"),
    37: ("NameEntry_BarnJ",         "Rename shack J ({Barn9}). Sub-id 28. [dev-menu]"),
    38: ("NameEntry_Child0",        "Open the software-keyboard to name the player's child (slot 0). Dev menu label: "
                                    "'Name of child. If there are none, it will stop!' -- fails silently when no "
                                    "child exists. Dispatch through name-entry sub-id 13 with sub166=0. [dev-menu]"),
    39: ("NameEntry_Child1",        "Name child (slot 1). Sub-id 13 with sub166=1."),
    40: ("NameEntry_Child2",        "Name child (slot 2). Sub-id 13 with sub166=2."),
    41: ("NameEntry_Child3",        "Name child (slot 3). Sub-id 13 with sub166=3."),
    42: ("NameEntry_Child4",        "Name child (slot 4). Sub-id 13 with sub166=4."),
    43: ("Posts",                   "Open Posts (subscribed message-board threads). [dev-menu]"),
    44: ("ScriptAction_10(v3)",     "Scripted action 10 (variant +164=3); shares handler with 3/43."),
    45: ("Bookshelf",               "Open the Bookshelf. Gated: dev menu tests game-flag 56 first "
                                    "and only fires this on the true branch. [dev-menu]"),
    51: ("MonsterFarmMenu",         "Open the Monster Farm menu (GenericMenu 12)."),
    52: ("(word write nop)",        "Zeroes word_7FF6F6A44F74; no trigger fired."),
    53: ("ShippingBin",             "Open the Shipping Bin. Also runs a Poison-Mushroom / "
                                    "Toadstool ship-check for achievement 2594. [dev-menu]"),
    54: ("Safe",                    "Open the Safe (money storage). [dev-menu]"),
    55: ("Wardrobe",                "Open the Wardrobe (outfits). [dev-menu]"),
    56: ("Toolbox",                 "Open the Toolbox (tool slot config). [dev-menu]"),
    57: ("MonsterFarm(focused)",    "Focus a specific farm monster, then open the monster-farm menu."),
    58: ("Forge",                   "Open the Forge crafting station. [dev-menu]"),
    59: ("ScriptAction_41",         "Scripted action 41."),
    60: ("ScriptAction_42",         "Scripted action 42."),
    61: ("ScriptAction_43",         "Scripted action 43."),
    62: ("ScriptAction_44",         "Scripted action 44."),
    63: ("ScriptAction_46",         "Scripted action 46."),
    64: ("ScriptAction_47",         "Scripted action 47."),
    65: ("ScriptAction_45",         "Scripted action 45."),
    66: ("ScriptAction_48",         "Scripted action 48."),
    67: ("ScriptAction_53",         "Scripted action 53."),
    68: ("ScriptAction_50",         "Scripted action 50."),
    69: ("ScriptAction_51",         "Scripted action 51."),
    70: ("ScriptAction_52",         "Scripted action 52."),
    71: ("Crafting",                "Open the Crafting station (general crafting bench). [dev-menu]"),
    72: ("ScriptAction_54",         "Scripted action 54."),
    73: ("ScriptAction_55",         "Scripted action 55."),
    74: ("ScriptAction_08",         "Scripted action 08."),
    75: ("Shop_WeaponFarmTool",     "Weapon / Farm Tool shop (Bado's smithy). The dispatch handler still consults "
                                    "g_storyProgressFlag9bit internally to pick the right stock/proprietor tier, "
                                    "but the shop identity itself is fixed. [dev-menu]"),
    76: ("Shop_Accessory",          "Accessory shop. [dev-menu]"),
    77: ("Shop_ExcavatedEquipment", "Equipment shop -- 'Excavated Things' (dungeon/excavated gear). [dev-menu]"),
    78: ("Shop_HospitalMedicine",   "Hospital -- Medicine counter. [dev-menu]"),
    79: ("Shop_Interaction_4F",     "Shop interaction 4F (not in the dev shop menu; specific handler for kind 0x4F)."),
    80: ("Shop_Flower",             "Flower shop. [dev-menu]"),
    81: ("Shop_BaseIds_19_20_a",    "Shop, base ids 19-20 (variant a; not in the dev menu)."),
    82: ("Shop_Furniture",          "Furniture shop. [dev-menu]"),
    83: ("Shop_Ability",            "Ability shop. [dev-menu]"),
    84: ("Shop_Magic",              "Magic shop. [dev-menu]"),
    85: ("Shop_Jewel",              "Jewel shop. [dev-menu]"),
    86: ("Shop_SakuTuner",          "Saku's shop (Tuner). [dev-menu]"),
    87: ("Shop_Yue",                "Yue's shop. [dev-menu]"),
    88: ("Shop_Restaurant",         "Restaurant. [dev-menu]"),
    89: ("Shop_BaseId_57",          "Specific shop, base id 57 (not in the dev menu)."),
    90: ("BirthdayEntry",           "The 'Enter your birthday.' input screen (observed in-game). Dev-menu "
                                    "action paired with 4 (NameEntry_Hero) -- fired immediately after it in the "
                                    "'Enter name of the main character' branch; internally runs ScriptAction_56 "
                                    "with subId=56. [dev-menu]"),
}

# op number for TriggerWorldInteractionAction (looked up once at import time)
_TRIGGER_WORLD_INTERACTION_OP = next(
    (_op for _op, _t in TECHNICAL.items()
     if _t == "Script_VMOp_TriggerWorldInteractionAction"),
    None,
)

# Shopkeeper NPC ids for op 376 arg 0. Derived from the Script_VMOp_BeginCalendarContextualInteraction
# switch (RF4S.exe+0x211C20) + PORTRAIT_SPEAKERS slot correspondence + observed corpus usage.
# Vanilla script never passes a LITERAL for this arg (always localvar[]), so the enum picker
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
    16: ("Blossom",             "Furniture -> day 5 (Fri)"),
    17: ("Dolce",               "-> day 1 (Mon)"),
    18: ("Jones",               "Hospital -> day 1 (Mon)"),
    19: ("Nancy",               "Hospital -> day 1 (Mon)"),
    22: ("Son",                 "Married-couple child -> day 6 (Sat) via kind 26 fallback"),
    23: ("Daughter",            "Married-couple child -> day 6 (Sat) via kind 26 fallback"),
    25: ("Guest25",             "-> day 6 (Sat), kind 21 override with sub-arg forced to 28"),
}

# Festival IDs from bank 292 @0x0840's `＊ｏBean Festival` dev menu (33 choices, one
# STORE per branch reveals the exact id going into reg0 or reg2).
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
# (bank 252 tail scene@0x21e pc@0x38a0). Each branch is `GiveItem(<charm_id>, 1, 1)`,
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
# range and CALLs a shared "GiveItem for i in [reg1, reg2)" loop. So the entire
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
# each NPC branch fires `STORE var:0x40C6 = <slot>` matching PORTRAIT_SPEAKERS).
# So var:0x40C6 is a GENERIC 'currently-focused NPC' variable, not
# monster-dex-specific; renamed accordingly.
#
# Also each NPC branch fires SetPlayerLestOrFrey(gender), so this maps to
# which protagonist (Lest=1/Boy or Frey=0/Girl) can marry each NPC:
NPC_MARRIAGE_PARTNER_OF = {
    # NPC slot -> protagonist gender that can marry them (SetPlayerLestOrFrey arg)
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
# `＊M_AMAZE〜M_FLOWER02` motion-sampler menu. Each STORE-range is (reg0, reg1)
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
# specific number right before firing (see docs/21 "Rosetta Stone IV").
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
}


def story_checkpoint_name(v):
    return STORY_CHECKPOINTS.get(v)


# Named game-state variables (STORE var:0xNNNN) discovered from the QA menus.
# These aren't opcodes; they're the meanings of specific `var:` addresses used
# by the script's STORE / conditional-branch machinery. Recorded here so a
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
                                         # (STORE var:0x8620 = 500 = 'Date active')
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
ENUM_ARG_VALUES[(376, 0)] = SHOPKEEPER_NPCS
ENUM_ARG_VALUES[(376, 1)] = {_k: _v for _k, _v in WORLD_INTERACTION_ACTIONS.items()
                             if 75 <= _k <= 89}
ENUM_ARG_VALUES[(617, 0)] = STAFF_SPAWN_MODES
ENUM_ARG_VALUES[(446, 0)] = WEATHER_CODES         # SetWeather weather code
ENUM_ARG_VALUES[(197, 0)] = SHAKE_KINDS            # ShakeCamera jitter kind (1-6, 0=stop)

# Character ids (0-26 named; 0 = the player Lest/Frey). This is the NPC record-array index used
# by the many "char id (0=player, 1-47=NPC)" opcode args. Names are the authoritative rf3TxtNpc
# archive strings (char_names.json, index == char_id). Ids 27-40 are generic 'Traveler', 41-47
# 'Soldier', 48+ = event/monster actors -- type the raw id for those (they stay numeric).
_CHAR_NAMES = {
    0: "Lest/Frey", 1: "Vishnal", 2: "Clorica", 3: "Volkanon", 4: "Forte", 5: "Kiel",
    6: "Bado", 7: "Margaret", 8: "Dylas", 9: "Arthur", 10: "Porcoline", 11: "Xiao Pai",
    12: "Lin Fa", 13: "Amber", 14: "Illuminata", 15: "Doug", 16: "Blossom", 17: "Dolce",
    18: "Jones", 19: "Nancy", 20: "Leon", 21: "Ventuswill", 22: "Son", 23: "Daughter",
    24: "Barrett", 25: "Raven", 26: "Mistress Trupin",
}
CHAR_IDS = {_i: (_nm, ("The player character (char id 0)." if _i == 0
                       else "Character '%s' (char id %d)." % (_nm, _i)))
            for _i, _nm in _CHAR_NAMES.items()}
# Ops whose selected arg is a plain char-id selector in the 0-47 NPC space (0=player). Excludes
# ops with overloaded char args (338 0=spouse, 486 0=scene-actor/22=spouse, child ops 24-47).
_CHAR_ID_ARG_OPS = [(110, 0), (121, 0), (122, 0), (209, 0), (339, 0), (440, 0),
                    (475, 0), (479, 0), (661, 0), (663, 0), (664, 0), (690, 0)]
for _cop, _cai in _CHAR_ID_ARG_OPS:
    ENUM_ARG_VALUES[(_cop, _cai)] = CHAR_IDS

# Auto-extend the character decoder to EVERY plain char-id / npc-id arg (~150 actor/npc ops) so
# the disassembly shows names throughout ("SetActorFacingAngle(19=Nancy,...)", "HideNpc(8=Dylas)").
# Uses CHAR_IDS (0=player Lest/Frey) normally, or the no-0 variant where the label says 0 means
# something else (all/current/count/input/-1). SKIPS: child ops (24-47 = the player's children, a
# different id table), monster args (48+ species space), event-key, spouse-default, and variadic /
# index args -- decoding those with the villager roster would be WRONG.
_CHAR_IDS_NPC = {_k: _v for _k, _v in CHAR_IDS.items() if _k != 0}
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
# TOC (RF4S.exe .rdata +0x57AD30, 18179 x 256B UTF-16). tools/rf4_refdata/char_models.json is
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


_CHAR_MODELS = _load_char_models()
EVENT_CHAR_IDS = {}
for _ci in sorted(set(_CHAR_MODELS) | set(_CHAR_NAMES)):
    _cm = _CHAR_MODELS.get(_ci, {})
    _nm2 = _cm.get("name") or _CHAR_NAMES.get(_ci) or ("char#%d" % _ci)
    if _ci == 0:
        _nm2 = "Lest/Frey"
    _mdl = _cm.get("model")
    if _mdl:
        _lbl = "%s [%s]" % (_nm2, _mdl)
        _dsc = ("Character '%s' (char id %d). Field model %s/%s (rf3NpcParam+272 = %d)."
                % (_nm2, _ci, _cm.get("kind", "chr"), _mdl, _cm.get("model_index", -1)))
    else:
        _lbl = _nm2
        _dsc = "Character '%s' (char id %d). No field model (rf3NpcParam+272 = -1)." % (_nm2, _ci)
    EVENT_CHAR_IDS[_ci] = (_lbl, _dsc)
# Spawn ops 153/154/155 arg0 + registry cleanup 156 arg0 address the full roster (overrides the
# villager-only dict the auto-extend loop assigned from the "char id" label).
for _eco in ((153, 0), (154, 0), (155, 0), (156, 0)):
    if EVENT_CHAR_IDS:
        ENUM_ARG_VALUES[_eco] = EVENT_CHAR_IDS

# op 437 NpcWantsItem arg1 is LABELLED "npc (char id)", so the auto-extend loop wired CHAR_IDS to
# it -- but the corpus proves token position 1 always holds a present-CATEGORY ref (0x8100+cat,
# observed 0x8101..0x8114 = categories 1-20 of gift archive 14850), NEVER a char id. The handler
# (Script_VMOp_QueryItemInNpcOfferListArchive14850) reads the real npc_id indirectly from the
# shared arg stack (argbuf[cursor-5]), not this bytecode token. A villager picker here never
# decodes and its dropdown would let an author write a wrong value, so drop it (leave it raw). The
# label/semantics (npc vs category, front-vs-back arg mapping) are left unresolved -- only the
# demonstrably-wrong picker is removed. See project_rf4s_script_vm.md.
ENUM_ARG_VALUES.pop((437, 1), None)

# Town-development / Prince-Points effect ids (TriggerEffect 643, GetEffectState 644, GetEffectCost
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
    0x1D: ("Effect-applied flag", "Set (TriggerEffect) or read (GetEffectState) a save-persisted "
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

# Item-id -> name value-decoder, from the authoritative item-name archive (co-located
# item_names.json; a missing file just disables item decoding, gracefully). Auto-wired to every
# opcode arg whose label is an item-id selector, so the editor shows item names and value-decodes
# them ("GiveItem(258=Pineapple Juice)"). ~33 item args across the give/take/ship/query ops.
_ITEM_NAMES = {}
try:
    with open(os.path.join(os.path.dirname(__file__), "item_names.json"), encoding="utf-8") as _itf:
        _ITEM_NAMES = {int(_k): _v for _k, _v in json.load(_itf).items()}
except (OSError, ValueError):
    _ITEM_NAMES = {}
if _ITEM_NAMES:
    # Empty description: the label IS the item name and the id is already shown in the picker row,
    # so a desc would just repeat both -- keep the 1108-entry dropdown clean ("258 - Pineapple Juice").
    ITEM_IDS = {_i: (_nm, "") for _i, _nm in _ITEM_NAMES.items()}
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
SKILL_IDS = {_s: (skill_name(_s), "Player skill '%s' (skill %d)." % (skill_name(_s), _s))
             for _s in range(38)}
ENUM_ARG_VALUES[(679, 0)] = SKILL_IDS      # IncrementPlayerSkillLevel
ENUM_ARG_VALUES[(701, 0)] = SKILL_IDS      # SetPlayerSkillXp

# NPC outfit variants (op287 SetNpcOutfit arg1 — the label documents the 0-3 mapping).
OUTFITS = {
    0: ("Default",  "The NPC's default/normal outfit."),
    1: ("Pajamas",  "Pajamas / sleepwear."),
    2: ("Festival", "Festival outfit."),
    3: ("Swimsuit", "Swimsuit / beach outfit."),
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

# Dialogue-speaker emote/expression (op93 SetDialogueSpeakerEmote arg0 = 0-7). The emote byte is
# stored as the portrait VARIANT (task+160 -> portrait sprite 15851+variant), the same variant
# space as the live-verified canonical face frames -- so 0-5 reuse FACE_FRAMES names; 6/7 are
# unnamed extra frames (stay raw).
SPEAKER_EMOTES = {_e: (FACE_FRAMES[_e], "Speaker expression '%s' (portrait variant %d)."
                       % (FACE_FRAMES[_e], _e))
                  for _e in range(6) if _e in FACE_FRAMES}
ENUM_ARG_VALUES[(93, 0)] = SPEAKER_EMOTES

# Skill sub-arg of QueryPlayerVariable (op416 arg1 = the skill id, used when arg0 selects 'Skill').
# render_action already value-decodes it via the stat-query path; this just adds the dropdown.
ENUM_ARG_VALUES[(416, 1)] = SKILL_IDS

# Room / map name decoder (op291 SpawnChildEventRecords arg1 = room id). From the co-located
# map_names.json (index == room id); BLANK/placeholder rows are filtered out. Missing file =
# graceful disable.
_MAP_NAMES = []
try:
    with open(os.path.join(os.path.dirname(__file__), "map_names.json"), encoding="utf-8") as _mf:
        _MAP_NAMES = json.load(_mf)
except (OSError, ValueError):
    _MAP_NAMES = []
if _MAP_NAMES:
    ROOM_IDS = {_r: (_rn, "")
                for _r, _rn in enumerate(_MAP_NAMES)
                if _rn and not _rn.startswith("BLANK") and _rn != "JP"}
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
            try:
                sid = _lit_int(arg_strs[1]) if code == 104 else code
            except (ValueError, IndexError, TypeError):
                sid = code
            return "QueryPlayerVariable(Skill, %s)" % skill_name(sid)
        return "QueryPlayerVariable(%s)" % PLAYER_VAR_BY_CHARCODE.get(code, "code%d" % code)
    # Portrait / SetSpeaker ops (16..75): prepend `side` (from opcode parity: even=left,
    # odd=right) and resolve face-frame + emote-id numerics to canonical mood names. So
    # `SetSpeakerVishnal(1, 189)` on op 19 renders as `SetSpeakerVishnal(right, angry, angry)`.
    if 16 <= op <= 75:
        side = "left" if (op & 1) == 0 else "right"
        decorated = [side]
        for i, raw in enumerate(arg_strs):
            try:
                v = _lit_int(raw)
            except (ValueError, TypeError):
                decorated.append(raw)
                continue
            if i == 0:                            # face frame
                name = face_frame_name(v)
                decorated.append(name if name else str(v))
            elif i == 1:                          # emote / mood
                if v == 0:
                    decorated.append("0")         # 0 = no emote; leave numeric
                else:
                    name = portrait_emote_name(v)
                    decorated.append(name if name else str(v))
            else:                                 # target actor ref
                decorated.append(raw)
        return "%s(%s)" % (mnemonic(op), ", ".join(decorated))
    # Auto-annotate any op that has an enum registry entry: TriggerWorldAction(3=MessageBoard),
    # ShowCreditsOverlay(2=Credits (bottom)), etc. Falls back to the default rendering
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
            if entry:
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
# These entries override earlier metadata; per-op evidence is logged in DIFFS.md
# (decomp repo) for that session. Applied AFTER the generated fallbacks on purpose -
# explicit verified knowledge wins.
_AUDIT_2026_09_01 = {
    3: ('WaitReset', 'flow',
        "End the current quest-reaction beat and wait: signals the scene controller idle (sceneCtx+872->child[+24][+116] = 1, the same write EndDialogue does), advances the quest-reaction dispatch state (Quest_OnReactionDispatched_AdvanceState), then - if the script task is in run-state 4 - writes arg0 into the task's wait field (+120, state 4->2), i.e. the same duration mechanism as Wait. Same units as Wait (200 = 1 frame); retail passes durations like 1 (minimal yield) or 6000 (30 frames). 267 retail uses, always 1 arg.",
        ['duration (units; 200 = 1 frame)']),
    5: ('ShowNpcBubbleVariant', 'dialogue',
        'Show an NPC speech/thought bubble — a variant form of ShowNpcBubble (op 6) built on the same NpcBubble_DispatchFromDescriptor pipeline. Blocks (returns busy) until any active screen fade completes. Takes THREE args (corpus: all 793 uses pass 3): arg0 = line id (into rf3mc.<locale>; descriptor u16 slot 0), arg1 = sub-token (descriptor u16 slot 1), arg2 = a byte param/emote (descriptor byte 6; corpus values like 254). The old hint list promised a 4th sfx/emote arg that the handler never reads.',
        ['line id', 'sub-token', 'emote/param (byte)']),
    6: ('ShowNpcBubble', 'dialogue',
        'Show an NPC speech/thought bubble — the core bubble op. arg0 = content id with a dispatch: < 1000 = builtin EMOTE (emote-to-string table); 1000..1927 = dialogue STRING, index = id - 1000 (out of range clamps to 1000; 928 valid entries). arg1 = sub-token, arg2 = extra param (PSB-emote capable), arg3 = sfx/emote (>= 0x1F0 plays a voice line via the NPC-variant remap, else an emote id). Blocks until any active screen fade completes; re-showing identical text is a no-op (per-slot last-text cache).',
        ['content id (<1000=emote, 1000+=line, idx=id-1000)', 'sub', 'param', 'sfx/emote id']),
    7: ('ShowNpcBubble', 'dialogue',
        'Alias of op 6 (same handler): show an NPC speech/thought bubble.',
        ['content id (<1000=emote, 1000+=line)', 'sub', 'param', 'sfx/emote id (>=0x1F0=voice)']),
    8: ('DialogueLine', 'dialogue',
        "Show a dialogue line. arg0 = line id: >=0x30 = text-archive entry id (the common case, rendered as DIALOG #NNNN), 1-26 = standard slot load, 27-47 = event-participant line (portrait shown for 27-33/41-47), 0xFFFF = end marker. Also picks the speaker's dialogue tick-chime SFX class (Dialogue_PickChimeClassForSpeaker) before showing the text.",
        ['line id (>=0x30 archive entry; 1-26 std slot; 27-47 event line; 0xFFFF end)']),
    13: ('BubbleLineV3', 'dialogue',
        'Show a scripted speech bubble (3 tokens). arg0 = line id (also picks the chime SFX class and, when changed, remaps via Dialogue_RemapBubbleLineId24To28 into the shown text), arg1 = line index (compacted to a 0-5 bubble category), arg2 = sub index. Builds a bubble descriptor and calls NpcBubble_DispatchFromDescriptor; blocks while a fade runs. Per the IDB analysis the first token is a LINE id, not a speaker id. Unused in the shipped corpus.',
        ['line id', 'line index (0-5 category)', 'sub index']),
    14: ('BubbleLineV4', 'dialogue',
        'Show a scripted speech bubble (4 tokens; PSB-emote capable). arg0 = line id (NOT a speaker: when the emote feature flag is on and line id >= 30 it is remapped through the NPC emote PSB table; otherwise used directly for the bubble text). arg1 = line index, arg2 = sub index (>= 0x1F0 triggers the sfx sub-action chain), arg3 = param.',
        ['line id', 'line index', 'sub index', 'param']),
    15: ('ShowSpeakerBubble', 'dialogue',
        'Show a speech bubble line for a SPEAKER, with emote-PSB support. arg0 = speaker (npc/char id: selects the chime class, name text and per-NPC emote byte; with save-config emote flag 0x40 set, ids >= 30 index g_npcEmotePsbTable and get substituted -- the Switch-era PSB emote path). arg1 = line index (passed to Dialogue_LoadAndShowText). arg2 = sub/param. arg3 = trigger: >= 0x1F0 plays a voice sfx, else stored as the bubble emote byte.',
        ['speaker (npc id)', 'line index', 'sub', 'sfx/emote id (>=0x1F0=voice)']),
    16: ('SetSpeakerMC', 'dialogue',
        "Speaker cue for the following DIALOG line(s) -- designates the speaker=Lest/Frey (slot 0, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.",
        ['face frame', 'emote / voice id', 'emote / voice id 2', 'emote / voice id 3 (rare)']),
    23: ('SetSpeakerVolkanon', 'dialogue',
        "Speaker cue for the following DIALOG line(s) -- designates the speaker=Volkanon (slot 3, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.",
        ['face frame', 'emote / voice id', 'emote / voice id 2', 'emote / voice id 3']),
    31: ('SetSpeakerMargaret', 'dialogue',
        "Speaker cue for the following DIALOG line(s) -- designates the speaker=Margaret (slot 7, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.",
        ['face frame', 'emote / voice id', 'emote / voice id 2', 'emote / voice id 3']),
    39: ('SetSpeakerXiaoPai', 'dialogue',
        "Speaker cue for the following DIALOG line(s) -- designates the speaker=Xiao Pai (slot 11, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.",
        ['face frame', 'emote / voice id', 'emote / voice id 2', 'emote / voice id 3']),
    47: ('SetSpeakerDoug', 'dialogue',
        "Speaker cue for the following DIALOG line(s) -- designates the speaker=Doug (slot 15, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.",
        ['face frame', 'emote / voice id', 'emote / voice id 2', 'emote / voice id 3']),
    55: ('SetSpeakerNancy', 'dialogue',
        "Speaker cue for the following DIALOG line(s) -- designates the speaker=Nancy (slot 19, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.",
        ['face frame', 'emote / voice id', 'emote / voice id 2', 'emote / voice id 3']),
    63: ('SetSpeakerDaughter', 'dialogue',
        "Speaker cue for the following DIALOG line(s) -- designates the speaker=Daughter (slot 23, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.",
        ['face frame', 'emote / voice id', 'emote / voice id 2', 'emote / voice id 3']),
    71: ('SetSpeakerBarrett', 'dialogue',
        "Speaker cue for the following DIALOG line(s) -- designates the speaker=Barrett (slot 27, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.",
        ['face frame', 'emote / voice id', 'emote / voice id 2', 'emote / voice id 3']),
    77: ('SetActorFacingAngle', 'actor',
        "Turn an actor toward a target facing. arg0 = actor (char id, 0=player; resolved by matching the scene's two bound actor slots ctx+88/ctx+96, not the global tables). arg1 = TARGET facing, written raw (u16) to motion field +94 while +92 snapshots the current facing (+44) as the lerp start; bit 0x8000 of arg1 clears motion byte +99 (turn-mode/snap selector, default 1). arg2 = TURN SPEED: run through the engine's canonical speed formula ((167773*x)>>12, here x25 scale) into motion field +88, with turn progress (+32) reset to 0. NOTE: the previous hints had arg1/arg2 swapped (rate vs angle).",
        ['actor (char id, 0=player)', 'target facing (bit 0x8000 = mode flag)', 'turn speed']),
    79: ('SetActorTurnAngle', 'actor',
        "Turn an actor by a RELATIVE amount: adds signed arg1 to the motion target-turn field (+94); arg1's sign also sets the turn-direction byte (+99: positive=1, negative=0 — the old 'bit 0x8000 = ease vs snap' claim was just this sign bit). arg2 = turn SPEED, not an angle: it goes through the same 167773/4096 (x40.96, then x25) Q12 speed conversion as the move ops' speed channel and lands in motion +88. arg0 = actor (char id, matched against the two scene actor slots; 0 = player). Corpus shows paired +40/-40 wiggles at speed 100 during dialogue (head-shake beats).",
        ['actor (char id, 0=player)', 'turn delta (signed, sign=direction)', 'turn speed']),
    83: ('CloseDialogueBubbles', 'dialogue',
        "Close on-screen dialogue bubble(s) and BLOCK the scene until the close animation finishes. arg selects which: 0 = close the FIRST bubble slot (ctx+88), 1 = close the SECOND slot (ctx+96), any other value = close BOTH. Each path calls DialogueBubble_TransitionState(slot, 0) and then keeps returning 'blocked' while the bubble state / g_npcBubbleActiveByScreen shows a bubble still closing. Use before switching speakers or ending a conversation cleanly. (The old hint '0 = both' was wrong: 0 closes one slot; only a value other than 0/1 closes both.)",
        ['which (0=slot 0, 1=slot 1, other=both)']),
    89: ('SetActorMotionMask', 'actor',
        "Low-level motion tuning: writes a per-actor motion mask byte (actor motion struct +66). arg0 = actor (matched against the scene's two participant slots at ctx+96/+88, like op 81). arg1 is a LEVEL, not a raw mask: the byte written is 127>>arg1; arg1 = 0 (or out of 1..254) writes 0xFF (all bits). Engine-internal; exact field semantics uncertain.",
        ['actor (char id)', 'mask level n (byte written = 127>>n; 0 = 0xFF all bits)']),
    90: ('SetActorMotionMask', 'actor',
        "Alias of op 89 (same handler): set an actor's motion mask byte (motion struct +66) from a SHIFT COUNT, not a raw mask: writes 127>>n for n in 1..254, otherwise 0xFF. arg0 = actor (char id, resolved via a1+96/+88). Exact field semantics uncertain; unused in the shipped corpus.",
        ['actor (char id)', 'shift n (writes 127>>n; 0/255 = 0xFF)']),
    94: ('SetSpeakerEmote0', 'dialogue',
        "Set the current dialogue speaker's facial emote to 0 and retarget the portrait (Dialogue_SetSpeakerEmoteAndRetargetPortrait). The emote id is ENCODED BY THE OPCODE: emote = op - 94; ops 94-97 share this one handler (emotes 0-3), which reads its own opcode back from sceneCtx+260 — it does NOT read an actor field. Takes no args. The general form is op 93, which takes the emote as a normal argument.",
        []),
    95: ('SetSpeakerEmote1', 'dialogue',
        "Set the current dialogue speaker's facial emote to the FIXED id 1 and retarget the portrait. Ops 94-97 share one handler that recovers the emote from the opcode itself: emote = op - 94 (94->0, 95->1, 96->2, 97->3), read from the currently-dispatching opcode byte at sceneCtx+260. Calls Dialogue_SetSpeakerEmoteAndRetargetPortrait(1). No args. The general form is op 93 (SetSpeakerEmoteByArg), which takes the emote as a normal argument.",
        []),
    96: ('SetSpeakerEmote2', 'dialogue',
        "Set the current dialogue speaker's facial emote to the FIXED emote id 2 and retarget the portrait (Dialogue_SetSpeakerEmoteAndRetargetPortrait). The emote id is encoded in the OPCODE, not read from the actor: ops 94-97 share this handler and map to emotes 0-3 (emote = op - 94, recovered from the currently-dispatching opcode at sceneCtx+260). The general form is op 93, which takes the emote as a normal argument. Takes no args. Corpus: appears right after a SetSpeaker* cue, before the DIALOG line.",
        []),
    97: ('SetSpeakerEmote3', 'dialogue',
        "Set the dialogue speaker's facial emote to id 3 and retarget the portrait (Dialogue_SetSpeakerEmoteAndRetargetPortrait). The emote id is ENCODED IN THE OPCODE, not read from the actor: ops 94-97 map to emote 0-3 via (opcode - 94), same trick as the SetSpeaker cluster. Takes no args. The general form is op 93 (SetDialogueSpeakerEmoteByArg), which takes the emote id as a normal argument.",
        []),
    105: ('QueryCalendarEventStub', 'query',
        'Always writes 0 to the VM output — the intended calendar-event lookup is stubbed on the PC port (for arg >= 0x30 the search over g_calendarEventMng runs but its result is discarded). arg0 = event id (consumed by the arg decoder). Treat as returning 0.',
        ['event id (consumed; result discarded)']),
    115: ('MoveActorToTile_LockAI', 'actor',
        "Walk an actor to an ABSOLUTE tile position, then LOCK its AI (npc+568 |= 0x10) so nothing interrupts the staged pose — used when actors slide into cutscene positions and must hold. Despite the old 'ByOffset' name, args 1/2 are absolute tiles, not offsets: the move command stores x<<12 / y<<12 RAW with no world-position anchor added, on both the NPC and player/scene paths (ops 115-118 are the absolute family; 123-128 are the relative one). args: actor (0 = player), x, y (tiles), facing degrees (x181 -> u16 rotation), speed, jump flag (non-zero = jump/run, 1.2x speed multiplier).",
        ['actor (char id, 0=player)', 'x (tiles, absolute)', 'y (tiles, absolute)', 'facing (degrees)', 'speed', 'jump (0/1)']),
    116: ('MoveActorToTile_LockAI', 'actor',
        'Move an actor to an ABSOLUTE tile position + set facing, while locking its AI (npc+568 |= 0x10) so it cannot start new behaviors during the move. arg0 = actor (char id, 0 = player via the scene move queue), arg1/arg2 = target x/y in tiles (written raw as x<<12 / y<<12 - NOT offsets), arg3 = facing (degrees, *181 -> u16 rotation), arg4 = speed, arg5 = jump flag (0/1; jump selects the 4915.2 speed multiplier and sets npc+568 bit 0x800000). Ops 115-118 are the absolute-position family; 123-128 are the relative (ByOffset) family.',
        ['actor (char id, 0=player)', 'x (tiles, absolute)', 'y (tiles, absolute)', 'facing (degrees)', 'speed', 'jump (0/1)']),
    117: ('MoveActorToTile_LockAINoFace', 'actor',
        'Move an actor to an ABSOLUTE tile (x,y) with NO facing change, then post-lock its AI (npc task +568 |= 0x10). 5 args: actor (char id, 0=player, must be <48), x tile, y tile, speed, jump flag. Position is written raw as x<<12 / y<<12 into the move command (absolute Q12 world coords) -- unlike op 125, which is genuinely relative. Speed = (arg*167773>>12) x (4915.2 if jump else 4096.0) >> 12, then Npc_StartMoveTowards. Bank 211 walks Volkanon to absolute (166,467) with it; scenes also feed it coordinates straight from position queries (reg0/reg1).',
        ['actor (char id, 0=player)', 'x (tiles, absolute)', 'y (tiles, absolute)', 'speed', 'jump (0/1)']),
    118: ('MoveActorToTile_LockAINoFace', 'actor',
        "Alias of op 117 (same handler): move an actor to an ABSOLUTE tile (not a relative offset — the position args are written raw as x<<12/y<<12 into the move command, unlike the genuinely-relative op 125/126 variant which adds the actor's current position), with NO facing change, and lock the actor's AI afterward (npc.+64.+568 |= 0x10). arg0 = actor (char id, 0=player, <48), arg1/arg2 = X/Y tiles, arg3 = speed, arg4 = jump flag (0/1; jump applies a 1.2x speed factor). 5 args — there is no facing arg. IDB-corrected 2026-08-12 (bank 211 walks Volkanon to absolute (166,467)).",
        ['actor (char id, 0=player)', 'x (tiles)', 'y (tiles)', 'speed', 'jump (0/1)']),
    121: ('NpcMoveAlt', 'actor',
        "Start an NPC moving toward tile (arg1, arg2) using the ALTERNATE movement mode (kind 2048 — dash/teleport-style, distinct from the normal kind-2 walk/run mover). arg0 = npc char id (<48), arg3 = speed (scaled x167773>>12, ~x41 Q12). Exactly 4 args — there is no 5th 'target param': the handler reads 4 and calls Npc_StartMoveTowards(npc, cmd) with no target id. Sets the NPC actor's 'moving' flag (control_flags |= 0x10).",
        ['npc (char id <48)', 'tile x', 'tile y', 'speed']),
    126: ('MoveActorByOffset_InterruptAI', 'actor',
        'Alias of op 125 (same handler): interrupt-AI relative reposition.',
        ['actor (char id, 0=player)', 'dx (tiles)', 'dy (tiles)', 'speed', 'jump (0/1)']),
    127: ('MoveActorByOffset_Continue', 'actor',
        'Continuation move: relative tile offset, no facing update, no AI changes — chains after another Move to extend a walk. Takes exactly 5 args: actor (char id, 0 = player), dx, dy (tiles, Q12-shifted), speed (x40.96 coefficient, x1.2 when jumping), jump flag. Unlike its and-face sibling there is NO facing argument (that variant takes 6). NPC path uses move-kind 2 (walk-keep-facing); player/scene path kind 4 (or 12 with ctx+72 bit 0).',
        ['actor (char id, 0=player)', 'dx (tiles)', 'dy (tiles)', 'speed', 'jump (0/1)']),
    128: ('MoveActorByOffset_Continue', 'actor',
        'Alias of op 127 (same handler): move an actor (NPC, or the scene/player actor when arg0=0) by a RELATIVE tile offset WITHOUT updating its facing (NPC move kind 2 = walk-keep-facing; scene kind 4/12). 5 args -- there is NO facing argument; that belongs to the with-facing sibling handler. Jump flag scales speed 1.2x and sets the NPC jump bit 0x800000.',
        ['actor (char id, 0=player)', 'dx (tiles)', 'dy (tiles)', 'speed', 'jump (0/1)']),
    131: ('QueryActorBeyondRange', 'query',
        "1 while the actor is FARTHER than [range] tiles from its target marker (the player checks a global target position; an NPC checks its own move target); 0 once within range. arg0 = actor (char id, 0 = player), arg1 = range in tiles. Wait-until-arrived predicate. (Handler is named 'InRange' but returns 1 when far.)",
        ['actor (char id, 0=player)', 'range (tiles)']),
    143: ('MoveToCoords', 'actor',
        "Queue a scripted 'move to tile coordinates' command for the scene's active mover. arg0/arg1 = target tile x/y (<<12 to Q12), arg2 = SPEED coefficient (not a distance: it gets the identical 167773/4096 = x40.96 Q12 conversion as NpcWalkToTile's speed arg, x1.2 when running; shipped scenes pass ~120-250), arg3 = 0 to walk / non-zero to run. Mode byte 8 added when ctx+72 bit 0 is set. Choreographs NPC/player movement during a cutscene.",
        ['tile x', 'tile y', 'speed', 'run (0=walk)']),
    152: ('WaitPlayerScriptSync', 'query',
        "Blocking sync point, NOT a register query: it writes nothing to reg0 (branching on reg0 after it reads a stale value). The handler returns block/retry while the scene busy flag (sceneCtx+116 & 0x8000000) is clear AND the player's scene_node bit 8 is clear, and lets the script proceed once either is set. Shipped scenes place it between PlayerScriptedTalkAnim steps as an animation-phase sync. Exact flag polarity is engine-internal (the IDB notes it blocks while the player looks 'ready'). No args.",
        []),
    154: ('EventSpawnNpcVariant', 'actor',
        "Spawn an event/cutscene NPC that carries a pose/scene VARIANT index — always claims a NEW registry slot (unlike op 153 which updates in place). arg0 = char id (which character/model; ids 254-266 are filtered = no-op), arg1 = event key (the scene-local handle later ops address), arg2/arg3 = X/Y tiles, arg4 = facing degrees (x181 -> u16), arg5 = variant index (stored as index-1 in the entry's high dword; 0 -> 0). Entry WORD5 is hardwired to 0 by the engine — there is NO reserved 7th argument. Use for staged NPCs with an alternate pose/outfit variant.",
        ['char id (model)', 'event key (scene-local handle)', 'x (tiles)', 'y (tiles)', 'facing (degrees)', 'variant index']),
    157: ('SpawnMapEntity', 'effect',
        "Spawn a map entity, dispatched by TYPE ID to the right spawner — the central script-side object-placement op (handler ScriptVMOp_SpawnMapEntityByTypeIdDispatchTable). arg0 = entity type id: <20 → special trigger (treasure/quest item, Map_HandleSpecialTriggerEntity), 20-195 → placed game object 'pg_mobj' (Actor_AllocTask 65 → MapObj_SetupActorByTypeId), 196-335 → interactive object (door/stove/lift, Map_SpawnInteractiveObject), 336+ → decoration/scenery (MapDecoration_Spawn). arg1/arg2 = position, arg3 = facing (passed as DEGREES, handler multiplies by 182 = 65536/360 → u16 angle), arg4 = sub-param (handler multiplies by 40). args5-9 = up to 5 optional EXTRA placement params copied into the entity's setup struct; their meaning is ENTITY-TYPE-SPECIFIC (flags, linked ids, size, etc.). Dynamic prop/decor placement from a scene.",
        ['entity type id', 'param 1 (x/pos)', 'param 2 (y/pos)', 'facing (degrees)', 'sub-param (x40)', 'extra 5 (type-specific)', 'extra 6 (type-specific)', 'flag 7 (0/1, type-specific)', 'flag 8 (0/1, type-specific)', 'extra 9 (type-specific)', 'extra 10 (type-specific)']),
    169: ('WaitForEventActorReady', 'query',
        'WAIT/barrier, not a query: blocks the scene (handler returns 1 = replay next frame) until the keyed event actor exists and its controller bit 0x8 is set (streamed in / action committed), then execution continues. arg0 = event key. Writes nothing to the VM output — pair it directly with the next event-actor op.',
        ['event key']),
    177: ('EventActorEnterIdle', 'actor',
        'Return a spawned event actor to its idle state, loading the default idle animation for its entity type. arg0 = event key. Use to reset an actor after a scripted anim/pose.',
        ['event key', '(unused — handler reads only 1 arg; shipped scripts pass 2)']),
    178: ('SetEventActorTargetFacing', 'actor',
        "Set a spawned event actor's TARGET facing angle; the NPC tick interpolates its current facing toward it (a smooth turn). arg0 = event key, arg1 = facing degrees (×181 → u16). (The handler's name says 'DirIndex' but the math is plain degrees, matching every other facing op.)",
        ['event key', 'facing (degrees)']),
    188: ('SnapCameraToPlayer', 'screen',
        "Recenter/lock the camera on the player: sets scene flag +116 bit 0x40000 (camera-recenter request) and actor flag 4 on all players. arg != 0: additionally snapshots the CURRENT CAMERA position into the script anchor g_scriptMarkAnchorPosQ12 (the same anchor op 193 sets and op 196 tests) and rewrites the map scroll origin (map work_buffer[11..12]) to the camera tile - an instant snap. arg == 0: commits the camera target clamped to map bounds (smooth ease). Note the snapshot stores the camera position, not the player's tile.",
        ['instant (0=ease, 1=snap)']),
    194: ('FocusCameraOnPlayer', 'screen',
        "Snap/commit the camera target onto the player (Camera_CommitTargetAndClampToBounds + distance-vector recompute, sets camera flag 0x40000) and BLOCK the scene for 3 frames while it settles. The engine reads NO arguments, but every shipped statement passes one (e.g. FocusCameraOnPlayer(400) in the corpus) — a vestigial ease-speed the RF4S handler ignores. Handy to 'return to the hero' between cutscene shots.",
        ['(ignored — engine reads no args)']),
    201: ('SetCameraSettleMode', 'screen',
        "Enable/disable the camera's SETTLE (soft-landing) mode — bit 0x40 of the camera state flags. When set, once the camera is within ~12 frames' worth of travel of its target its velocity decays 0.8125x per frame down to a 0.125 floor, giving a decelerating arrival instead of a constant-velocity stop. Effective on scripted pans (the follow camera rewrites its speed every frame, overwriting the decay). arg0 non-zero sets, 0 clears. Resolved 2026-08-25 via Widget_TickTransformEaseTowardTargets bit-0x40 arm.",
        ['settle on (0/1)']),
    203: ('SetCameraMapBounds', 'actor',
        "Recompute and re-apply the camera's per-map clamp bounds and zoom for the current map — NOT a player rotation (old name was wrong). The handler calls Camera_SetBoundsForMap(active input-context/map id, flag), passing 0xFFFF while input is suppressed; that callee sets the script/follow camera's centre clamp from the map's tile dims and re-applies the small-map zoom. arg: 0 = write the camera distance directly onto the player's camera rig (flag=1 path); non-zero = apply via Camera_SetDistanceAndZoomFactor (flag=0 path). Used after scripted camera moves/zooms to restore the normal map camera.",
        ['mode (0=direct distance write, else standard zoom apply)']),
    204: ('SleepInBed', 'flow',
        "Run the go-to-bed / sleep-to-next-day sequence. arg0 != 0 (retail always 1): the full blocking cinematic FSM - bed anim + voice line, spouse/child walk to the bedside, fade to black, Player_SleepInBed (save snapshot + Day_OnAdvance day rollover), position restore, fade back in, morning BGM/weather; pressing the skip button fast-forwards the fades. arg0 == 0: calls Player_SleepInBed immediately with no cinematic. Dev menu 'Sleep' passes [1].",
        ['cinematic (1=full sequence, 0=instant day advance)']),
    230: ('ReleaseNpcLocks', 'flow',
        "Release every NPC AI lock/placement from a prior scene: restores normal AI bits, refreshes each placed NPC from its schedule (per bit in sceneCtx+352), and clears the placed-actor reservation mask. Despite the old 'CutsceneEnd' name, corpus tracing shows it typically runs at the START of scenes as a reset-prologue (49% of uses in the first decile; only 2% near the end), immediately before placement/teleport ops — the real lifecycle is RELEASE -> PLACE -> LOCK -> RUN. arg0 = release mode (0 = leave AI-locked, non-zero = restore normal AI), then the participant NPC ids -- there is no count argument, the handler loops over args 1..argc-1 (Cutscene_ReleaseNpcLocksAndRefreshFromSchedule reads argc as the count, verified 2026-09-23); participants are excluded and unlock via their own dialogue/anim completion).",
        ['release mode (0=stay locked)', 'participant npc id …']),
    231: ('ReleaseNpcLocks', 'flow',
        "Alias of op 230 (same handler): release NPC locks and refresh each flagged NPC from its schedule — restores normal-AI bits, calls Npc_RefreshFromSchedule for every bit in the sceneCtx+352 mask, then clears the mask. Despite the old 'CutsceneEnd' name, corpus timing shows it typically runs at scene START as a reset/prologue before placement ops (49% of uses in the first decile of their scene, only 2% near the end): the real lifecycle is RELEASE -> PLACE -> LOCK -> RUN. args: release mode (0 = stay locked), then participant npc ids (no count arg -- the handler uses argc) (participants are excluded from immediate release).",
        ['release mode (0=stay locked)', 'participant npc id …']),
    233: ('HideNpc', 'actor',
        'Hide an NPC — make it invisible/despawned and set its hidden state bit. arg0 = npc (char id). Removes the NPC from the scene; pair with a schedule refresh or SetNpcVisibleFlag to bring it back.',
        ['npc (char id <48)', '(unused — handler reads only 1 arg; corpus passes 2)']),
    234: ('HideNpc', 'actor',
        'Alias of op 233 (same handler): hide an NPC — calls Npc_SetHiddenFlag(id) and sets record+52 bit 0x20000000 (the hidden bit QueryNpcActorPresent/op 282 tests on the actor side). arg0 = npc (char id < 48). The corpus always passes a second arg (usually 1) that the RF4S handler never reads — vestigial.',
        ['npc (char id)', '(ignored)']),
    238: ('QueryQuestNpcsAvailable', 'quest',
        "Read 1 iff a primary NPC and all listed NPCs are available (not busy/sleeping schedule codes 13/25, not already mid-event, not inaccessible) AND each listed NPC is within a max distance of the primary — the quest-event group gate. arg0 = max distance, arg1 = primary npc (char id, <48), arg2+ = the other npc ids (their count is implied by the arg count — there is no explicit count arg). Writes 1/0 to reg0. Like op 240 but also requires the NPCs aren't already mid-event.",
        ['max distance', 'primary npc', 'other npc …']),
    240: ('QueryNpcGroupPresentNearby', 'query',
        "Read 1 into reg0 iff a group of NPCs are all present and available (actor state != 13/25, not busy/inaccessible) and each within arg0 distance of the primary. arg0 = max distance, arg1 = primary npc (char id), remaining args = the other npc char ids -- there is NO count argument: the handler derives the group size from the statement's own arg count. The dominant 2-arg form (distance, npc) degenerates to a single-NPC 'present & available' check (self-distance 0). 5-arg form = primary + 3 others.",
        ['max distance', 'primary npc (char id)', 'other npc …']),
    258: ('QueryAnyNpcEligibleForComment', 'query',
        "Alias of op 257 (same handler): writes 1 to the VM output iff ANY of the candidate NPCs passed as args can deliver a flavor comment ('this plant is well cared for' style). Variadic: EACH arg is one candidate char id (the arg count is implicit in the statement encoding — there is no explicit count argument). Candidates are filtered on: registered + loaded, not busy/inaccessible, in the current area, plus per-NPC story-flag gates. In the shipped corpus every use passes exactly one candidate, typically reg0 from a preceding query.",
        ['npc id … (candidate char ids, variadic)']),
    268: ('QueryNpcArrivedAtSchedule', 'query',
        'Read 1 iff the given NPC(s) have arrived at their schedule-computed spots and are available (Npc_IsAtScheduledSpotAndAvailable) into the VM output. arg0 = 0: checks ALL villagers 1..23 (1 only if every present one is in place). Otherwise EVERY arg is an npc char id - the op is variadic with NO count argument - and all listed NPCs must be in place. Wait-until-NPCs-in-position predicate before a staged scene.',
        ['npc (char id, 0=all villagers)', 'more npc ids (variadic)']),
    269: ('QueryNpcArrivedAtSchedule', 'query',
        "Query -> reg0 whether NPC(s) are at their scheduled spot (Npc_IsAtScheduledSpotAndAvailable). ALL args are npc char ids -- variadic list, NO count argument: with an explicit list, returns 1 iff EVERY listed NPC passes the check. With arg0 = 0, scans schedule-active NPCs 1..23 (record +228 bit 1 set) and returns 1 iff NONE of them passes -- the all-NPC mode's polarity is inverted vs the list mode (decompile-verified quirk). Alias of op 268 (same handler).",
        ['npc (char id; 0 = all-NPC mode)', 'more npc ids ... (variadic)']),
    273: ('QueryNpcPresent', 'query',
        "Read whether a villager is 'present' — record bit 0x400000 (bit 22 of record+52, present-in-town) — into the VM output. arg0 = villager id, valid only for 1-23 (the handler requires id < 24; other ids yield 0). arg0 = 0 instead returns the COUNT of villagers (1-23) currently present.",
        ['npc (villager id <24; 0 = count all present)']),
    275: ('SetNpcPresenceState', 'actor',
        "Set NPC [arg0]'s presence/companion state. arg1 = -1: clear the NPC's bit in the global presence mask (qword_...B300-family dword) and clear its record's companion bit (+52 bit 0x400000). Any other arg1 value sets the presence-mask bit; arg1 == 1 ADDITIONALLY marks the NPC as companion (+52: set bit 0x400000 and state bits 0x300), copies a record flag to byte +16, and writes 0 into packed game-flag 768. So: 1 = add as companion, -1 = remove, other values touch only the presence bit.",
        ['npc index', 'mode (1=add companion, -1=remove, other=presence bit only)']),
    280: ('QueryNpcDateState', 'query',
        "Read an NPC's 3-bit DATE STATE (dating/relationship progression, npc record +55 & 7) into reg0 -- NOT a facing direction. arg0 = npc (char id); yields 0 if the NPC can't be resolved. Byte-for-byte duplicate of Npc_GetDateState, which backs EMQ_DATE_STATE (query 124) and the EMQ_SUBEV_ENABLE_* gates (tested against 0 or 5). Branch on it to gate date/relationship sub-events.",
        ['npc (char id)']),
    285: ('SetSceneReadyFlag', 'flow',
        "Set a scene-state control bit (scene state +72 bit 0x1) when arg0 is 0 — a low-level 'wait / ready' marker the scene loop checks. arg0 = mode (0 sets it).",
        ['mode (0 = set flag)', '(ignored by handler)']),
    290: ('PostFamilyMilestones', 'actor',
        "Write the packed marriage/family-status game-flag (packed id 4391 -> value 2) and run the family birthday/anniversary milestone check for today: compares the current date to the spouse's and children's birthdays and the wedding anniversary, setting the matching family-milestone game-flags. These go through GameFlags_WritePacked (packed game-flags), NOT Steam achievements. No args. Used in anniversary/birthday cutscenes.",
        []),
    293: ('ResetNpcDailySchedule', 'actor',
        "Put an NPC back on a daily-schedule state. arg0 = npc (char id), arg1 = state. Two distinct paths: arg1 != -1 -> Npc_ResetDailyScheduleAndAi(npc, state) (resets schedule AND AI) and returns WITHOUT touching the scene reservation; arg1 == -1 -> recompute today's state (record +17, or Schedule_GetNpcStateForToday when the computed bit +228&1 is clear), apply via Npc_ApplyScheduleState, and clear this scene's placed-actor/reservation bit (ctx+352 bit npc). Heavier than op 296; use at scene end to hand an NPC back to normal life.",
        ['npc (char id)', 'state (-1 = auto)']),
    302: ('SetNpcActionDelay', 'actor',
        "Make an NPC wait before its next scheduled AI action: writes a jittered countdown into the NPC's schedule-wait timer (record +212). Value = uniform [0.75*arg1, 1.125*arg1) via the shared MMIX RNG; if 3/4*arg1 <= 0 nothing is written. NpcSchedule_Tick decrements it once per tick and performs the next schedule action when it hits 0; starting a move/interaction clears it. Does NOT touch friendship — the old name came from a mislabeled IDB function and was settled as wrong (2026-08 analysis; implemented in the decomp as TitleNpcPlacement.timer). arg0 = npc (char id), arg1 = base wait (ticks).",
        ['npc (char id)', 'base wait (ticks, jittered 0.75x-1.125x)']),
    303: ('SetNpcActionDelay', 'actor',
        "Alias of op 302 (same handler). Despite the old name it does NOT touch friendship: writes a jittered WAIT into the NPC's schedule countdown (npc record +212, decremented once per NpcSchedule_Tick; on expiry the NPC performs its next scheduled action). Written value is uniform in [0.75 x arg1, 1.125 x arg1); arg1 <= 0 writes nothing. Starting a move or interaction clears the timer. arg0 = npc (char id, < 48), arg1 = requested delay (ticks).",
        ['npc (char id)', 'delay (ticks, jittered 0.75-1.125x)']),
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
    327: ('SetActorOutfitVariant', 'actor',
        "Alias of op 328 (same handler Script_VMOp_SetActorOutfitVariant). arg0 = actor (char id, 0 = player; 48-255 no-op). arg1 = pose/variant: 255 = END — detach the current scripted pose and return the actor to AI idle; 3 = apply the alt-outfit asset set (Actor_ApplyNpcOutfitVariant 3); any other value only detaches a previous pose first. Player path also refreshes player render state. No transform-animation task is involved — the old 'PlayActorTransform' name overstated it. Unused in the shipped corpus.",
        ['actor (char id, 0=player)', 'pose/variant (255=end pose, 3=alt outfit)']),
    332: ('PlayScriptedBeat', 'flow',
        "Launch a 4-param scripted beat / cutscene event on an actor. Writes the four u16 args into the action task's config slots (+60..+66) and commits (bit 0x80 at +56). arg3 (kind_id) drives a range gate on +57: 1000-1099 -> bit 0 (credit-roll-scale variant), 100-999 -> bit 1 (scripted-event variant), anything else INCLUDING 1100+ -> both clear (decompile: (kind-100) <= 0x383 = 999 max). Also clears g_gameGlobalsSlotTable entry-4 low nibbles, clears sceneControlFlags bit 0x100000, flags the current dialogue task, and - only when kind_id != 0 - prunes pending g_gameEventQueue events of types 20/24/28/30 (mask 0x41100000). Vanilla: 'Ackna Battle' (globalvar[0x2D5], 403, 453, 0), 'Ending (Plaza 2nd Run)' (globalvar[0x30], 8, 347, 130), 'Credit Roll 3' (globalvar[0x94], -96, 0, 1200).",
        ['actor ctx', 'arg1', 'arg2', 'kind id']),
    357: ('SetVar7', 'dialogue',
        'Write `value` into global script-variable bank 7 at [index] (Globals_LookupChoiceCommitStateSlotByKindId(7), index <= 51). Same family as SetVar0/3/15: ENGINE-GLOBAL slots shared with the choice-commit system and readable by dialogue-text substitution codes. Shipped scripts use bank 7 to stage NUMBERS for the next menu/dialog -- e.g. order-shop scenes run GetEffectCost(license/upgrade, 0); SetVar7(0, reg0); GetEffectCost(...); SetVar7(1, reg0); ... so the price list can be substituted into the text. NOT a portrait/face op -- the handler is a bare kind-7 var write.',
        ['index', 'value']),
    358: ('GetVar7', 'query',
        "Read global script-variable bank 7 at [index] into reg0 (g_scriptVarArrayKind7_52u32, a 52-entry u32 array). Identical shape to GetVar0/GetVar3 — the handler is a plain kind-7 var-array read with nothing portrait-specific in it; the old 'GetPortrait' name asserted semantics the code doesn't show. Only 16 corpus uses, all in bank 60 (the order/dev-menu bank).",
        ['index']),
    366: ('SetVar13', 'flag',
        'Write to the paired global script-variable banks 13/14 at [index] — arg order is (value, index), not (index, value): bank13[arg1] = arg0, with arg0 == 0 replaced by the sentinel 0x3B49; every FURTHER arg is written into bank 14 starting at the same index (arg2 -> bank14[index], arg3 -> bank14[index+1], ...; both banks capped at 16 slots). The corpus-dominant 3-arg form SetVar13(0, idx, v) therefore stores v in BANK 14 and the sentinel in bank 13; the 11/12-arg forms bulk-fill bank 14. These are engine-global choice-commit slots (shared with PROMPT_CHOICE and dialogue-text substitution). Read back with GetVar13/GetVar14 (into reg0).',
        ['bank-13 value (0 -> sentinel 0x3B49)', 'index', 'bank-14 value(s) …']),
    369: ('QueryPlayerCanInteract', 'query',
        'Attempt a player-mount/interaction onto the current scene actor and report the outcome. reg0 = 0 if the player is mid-action, 2 if carry-blocked (status 0x4000), else the result of Player_BeginMountTransitionAndInstallTickAndAnchor -- i.e. when free it actually BEGINS the mount transition. reg1 = 1 iff the player is not mid-action. The handler reads NO script args, though shipped scripts always pass one literal (ignored).',
        ['(ignored)']),
    380: ('FadeMusic', 'audio',
        "Ramp the CURRENT background-music track's volume (crossfade to a new volume level, no track change): target volume = arg/100 (capped at 65535), via BGM_SwitchWithCrossfade(-1, target); also arms the scene's BGM-ramp bit (ctx+116 |= 0x10000000). ONE argument only — all 1,899 corpus uses pass exactly 1 arg (e.g. FadeMusic(3000) = target 30). There is no duration argument; the crossfade time is the engine's own.",
        ['target volume (arg/100)']),
    387: ('PlaySfxWithNpcRemap', 'audio',
        'Play a sound/voice by id, applying the per-NPC variant remap (calls Sfx_PlayByIdWithNpcVariantRemap): the remap picks a per-character voice/footstep variant when the same base sfx id is shared across characters (char-variant +5 remap windows; id 0 stops all menu audio; routes by id range to Sfx_PlayById or Player_PlayVoiceLine_VariantRemapped). Same callee the SetSpeaker* ops use for args >= 0x1F0 — which is why those args are voice ids. Companion op 385 plays a raw id without remapping.',
        ['sfx / voice id']),
    389: ('FindVoiceSlot', 'audio',
        'Reserve a voice sfx slot: Sfx_FindOrPreemptVoice() picks (or preempts) a slot and Sfx_ApplyDistanceAttenuation(slot, ..., 0) sets it to full volume. The handler reads NO script args - the single value retail scripts pass (12 uses) is decoded by the VM and discarded.',
        ['(ignored by the handler)']),
    393: ('FreezePlayer', 'actor',
        'Lock or release player input (scripted freeze). INVERTED sense: arg0 == 0 FREEZES the player (sets control_flags bit 4, scene-node word bit 1, and the input-disabled bit 0x20000000 on actor_inner); arg0 != 0 releases all three. Shipped scenes open with FreezePlayer(0) and close with FreezePlayer(1).',
        ['release (0=freeze, nonzero=unfreeze)']),
    400: ('SetPlayerLestOrFrey', 'actor',
        "Switch the player character between **Lest (male / arg=1)** and **Frey (female / arg=0)**. Calls `Player_SetCharacterVariantLestOrFrey`, refreshes equipped sprites + scene state, zeros the save-snapshot scratch, and reloads the greeting string from archive 16369 (NPC name archive): arg=1 -> entry 0 (title greeting), arg=0 -> entry 599 (default 'Frey' name). **Formerly named `RefreshPlayerAndApplyDefaultName` -- the technical name hides that this is the actual character-swap op**. Dev menu label: 'Boy' / 'Girl'.",
        ['gender (1=Lest/Boy, 0=Frey/Girl)']),
    406: ('GetMonsterFarmLovedToday', 'query',
        "Read whether the farm monster the script is CURRENTLY addressing (the barn roster record whose task ptr matches the script ctx subject at +32) has been 'loved'/cared for today (g_MonsterFarmTable record flag bit 18) into the VM output; 0 if the subject is not a barn monster. Takes NO args. Counterpart of op 405.",
        []),
    419: ('QueryBackpackHasFreeSlot', 'query',
        'Write 1 to the VM output if the backpack has any free slot, else 0 — a BOOLEAN, not a slot index. Walks the first 60 backpack slots looking for an empty/placeholder entry (slot kind < 0x800 or item id 0); if all are full it falls back to checking the special equip-extras slot (g_itemDatabase.ptr_00[+24]). No args. Used before placing an item.',
        []),
    443: ('SetFlagBit', 'flag',
        'Set or clear a single game-flag bit in GameFlags ZONE 2: absolute bit 4096 + id (the handler adds the buffer\'s zone2_base; ids are zone-2 relative like MOBJ f13, NOT emdeb/emflags names; known blocks in emflags.ZONE2_BLOCKS). No extra +1007 — do NOT confuse with op 318, which adds 1007 and only sets. arg0 = flag id, arg1 = 0 clears / non-zero sets. The handler reads only 2 args, but every shipped statement passes 4 — args 2-3 are always 0 and ignored; the editor should accept/emit the 4-arg form.',
        ['flag id', 'value (0=clear, else set)', '(unused, always 0)', '(unused, always 0)']),
    460: ('AddRewardItem', 'item',
        'Add an item to a reward slot and queue the reward popup (RewardSlot_AddToInventoryAndQueuePopup). arg0 = reward slot id, arg1 = item id, arg2 = count (clamped to 1-10; forced to 1 for non-stackable items), arg3 = quality (clamped to 1-9). Unused in the shipped corpus.',
        ['reward slot', 'item id', 'count (1-10)', 'quality (1-9)']),
    493: ('GetNpcFacingMode', 'query',
        "Read the CURRENT scene NPC's scripted-facing mode bits (low 2 bits of the facing-mode word at scene_npc+304 -> +450) into the VM output. Takes NO arguments — it always targets the scene's own NPC record (sceneCtx+32), writing 0 if there is none. Counterpart of the mode setter (op 492 family).",
        []),
    508: ('PopulateQuestKind2RandomAlts', 'quest',
        "Populate the current NPC's daily quest-request slot using request template KIND 2 (With Random Cats). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).",
        []),
    509: ('PopulateQuestKind2RandomAlts', 'quest',
        "Populate the current NPC's daily quest-request slot using request template KIND 2, whose alternate objective items are rolled AT RANDOM from shop-category tables ('cats' in the old name meant categories, not animals: Shop_RollByCategoryFromTable re-rolls each seed until the result differs from the main item; up to 4 alternates). arg0 = objective item id; then two template params; trailing args = alternate category seeds. Distinct from the literal-alternates (slot 208) and chained-random (slot 209) siblings. See docs/23.",
        ['item id', 'template param (byte4)', 'template param (byte5)', 'alt category seed …']),
    515: ('PopulateQuestKind4Byte4_1LiteralAlts', 'quest',
        "Populate the current NPC's daily quest-request slot using request template KIND 4 (Byte4_1 Literal Alts). A runtime quest generator whose alternate objective items are the EXPLICIT literal item ids passed as args (stored verbatim — NO random category roll). See docs/23.",
        ['target item id', 'param (byte5)', 'alt item id …']),
    517: ('PopulateQuestKind5SimpleNoAlts', 'quest',
        "Populate the current NPC's daily quest-request slot using request template KIND 5 (Simple No Alts). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).",
        ['item id']),
    522: ('PopulateQuestKind10BackrefRandomCats', 'quest',
        "Populate the current NPC's daily quest-request slot using request template KIND 10 (Backref Random Cats). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).",
        ['category id …']),
    523: ('PopulateQuestKind10BackrefLiteralAlts', 'quest',
        "Populate the current NPC's daily quest-request slot using request template KIND 10 (Backref Literal Alts). A runtime quest generator whose alternate objective items are the EXPLICIT literal item ids passed as args (stored verbatim — NO random category roll). See docs/23.",
        ['alt item id …']),
    528: ('QueryQuestRewardItem', 'quest',
        'Read one reward item id of a quest template into the VM output: returns the u16 at g_npcQuestRewardTemplates_12u16PerQuest[quest_id * 12 + index + 7]. TWO args: arg0 = quest (template) id, arg1 = reward slot index 0-3 (out-of-range index returns the default, 1). Corpus (8 uses, always 2 args): QueryQuestRewardItem(0, 0) gates SuppressRewardJingle + ShowQuestReward before QuestOnComplete.',
        ['quest id', 'reward index (0-3)']),
    541: ('PopulateQuestKind4ChainedRandom', 'quest',
        "Populate the current NPC's daily quest-request slot using request template KIND 4 (Chained Random). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).",
        ['target item id', 'param (byte4)', 'param (byte5)', 'category seed …']),
    543: ('PopulateQuestKind5SimpleNoAlts', 'quest',
        "Populate the current NPC's daily quest-request slot using request template KIND 5 (Simple No Alts). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).",
        ['item id']),
    559: ('StartFestivalContest', 'flow',
        "Start a festival contest mini-event: spawns the SceneEvent lifecycle task (SceneEvent_TickLifecycleStateMachine) and BLOCKS the VM (ctx+116 |= 0x10000) until the contest ends. arg0 = contest subtype -> task+4: 1=ONI, 2=EAT (eating contest), 3=MOKO, 4=MATO (target shooting), 5=YUKI, 6=QUIZ, 7=PET. Backs up the packed festival-status register (REG_FES_STATUS) into the task, restored when the contest completes. The old 'return-to-town prompt' reading was wrong.",
        ['contest (1=oni,2=eat,3=moko,4=mato,5=yuki,6=quiz,7=pet)']),
    578: ('SpawnEventMonsters', 'effect',
        'Spawn and initialise the monster-roster participants for the current scene event (e.g. a monster contest / event where farm monsters take part). Takes no arguments.',
        []),
    600: ('RollRandomShopItem', 'item',
        'Roll a random shop item id and write it to the VM output (reg0) for a following read. MMIX RNG first picks one of 5 shop categories (the \'!"#$%\' category byte table), then Shop_RollByCategoryFromTable rolls an item from that category\'s shop table. No args. Used to generate random reward/treasure contents.',
        []),
    605: ('RollRandomFilteredItem', 'item',
        "Roll a random item id from a fixed eligible set — iterates the 195 item ids in [123, 314), keeps those whose byte in a lookup table is 0, applies a shop-availability filter, then MMIX-picks one (falls back to item 314 if none) — and write it to the VM output for a following read. The table's meaning is unverified (plausibly 'gift items NPCs accept'). No args.",
        []),
    606: ('RollThreeFlowerItemsAvoidDup', 'item',
        'Roll a 3-flower gift choice: writes item 63 (fixed first option) plus two distinct random flower/plant items to the THREE VM outputs reg0/reg1/reg2 (ctx+64/+68/+72). Candidates are item ids 63-70 and 84-109 that pass the shop filter (up to 40 collected); the two rolled picks avoid id 63 and each other (retry-capped, falling back to 65/67), using the global MMIX PRNG. No args. Used by the flower-choice gift dialogue.',
        []),
    607: ('RollRandomItemByLookupBytemask28', 'item',
        'Roll a random item id from a fixed 28-id window and write it to the VM output for a following read. Scans item ids 758-785, keeps those whose entry in a 28-byte eligibility table is 0 AND that pass the shop-unlock filter (Item_CheckShopFilter), then picks one with the MMIX RNG; if none qualify, returns the fallback id 759. Takes no arguments. (What items 758-785 are is unconfirmed — likely an ingredient/produce subset — so the mnemonic is kept as-is.)',
        []),
    613: ('CalcChoicePrescroll', 'dialogue',
        "Compute the upcoming choice menu's pre-scroll position. arg0 = an option index; the handler subtracts the number of HIDDEN options below it (clear bits in the visible mask at scene+244, capped by the option count at scene+243), i.e. arg0's position within the visible list, and stores the result in the GLOBAL g_choiceDialogPrescrollCount -- not in a VM register. Call between SetChoiceVisibleMask and PROMPT_CHOICE so the list opens positioned at that option.",
        ['option index']),
    617: ('ShowCreditsOverlay', 'effect',
        "Spawn / configure the staff-credits overlay task (task class 'staff', reusing the item-pickup-icon framework as a scrollable credits driver); if the task already exists it is just re-flagged. arg0 = mode: 0 = Fade (long), 1 = Fade (short), 2 = Credits screen (bottom), 3 = Credits screen (top) - the dev menu's four entries.",
        ['mode (0=fade long, 1=fade short, 2=credits bottom, 3=credits top)']),
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

# ---- 2026-09-01 addendum: engine tiebreaks from the decomp port -------------------
# Porting the audit into the behavioral decomp surfaced places where the AUDITED
# reference itself was wrong and the decomp (written straight from the binary) was
# right. Each entry below is engine-decompile-confirmed; RVAs in the descriptions.
_AUDIT_2026_09_01B = {
    202: ("SetCameraZoom", "screen",
          "Set the camera zoom / pull-back distance: the engine stores (arg0 - 1500) in the "
          "player camera struct (+68 target). arg1 != 0 SNAPS (writes current +64 AND target "
          "+68); arg1 == 0 eases (target only, view drifts to the new framing). Both paths "
          "apply the zoom - the old 'arg1 = reset to default rig' reading was wrong "
          "(IDB-corrected 2026-08-25; re-confirmed in the 2026-09-01 decomp port). "
          "Magnification = 1 + arg0/1800.",
          ["zoom (distance = arg-1500)", "snap (0=ease to it, 1=jump)"]),
    227: ("QueryNpcScheduleIsOneOf", "query",
          "Read 1 iff an NPC's current schedule id matches ANY id in the list. arg0 = npc "
          "(char id; 0 tests the PLAYER's scene/menu-state field, 22 the current child id). "
          "args[1..] = the schedule ids - there is NO count argument: the 'count' is the "
          "statement's own packed arg-count slot (engine 0x7ff7c1fbd9f0 reads it from the "
          "encoding, decomp-port confirmed 2026-09-01).",
          ["npc (char id, 0=player, 22=current child)", "schedule id …"]),
    257: ("QueryAllNpcsEligibleForComment", "query",
          "Read 1 iff EVERY listed NPC is eligible to deliver an ambient flavor comment "
          "(present, not busy, in the current area, not story-gated). ALL-must-pass, not any: "
          "eligible_found starts at 1 and the FIRST failing candidate zeroes it; ids >= 0x30 "
          "are skipped (engine 0x7ff7c1fc07e0, decomp-port confirmed 2026-09-01). Variadic: "
          "each arg is one candidate char id; no count argument.",
          ["npc id … (candidate char ids, variadic)"]),
    258: ("QueryAllNpcsEligibleForComment", "query",
          "Alias of op 257 (same handler): 1 iff EVERY candidate char id passed as an arg "
          "can deliver a flavor comment - ALL-must-pass (first failure zeroes the result), "
          "ids >= 0x30 skipped. The dominant corpus form passes a single candidate (reg0), "
          "where all/any coincide.",
          ["npc id … (candidate char ids, variadic)"]),
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
          "'TriggerActorTalkAnim + talk indicator' reading retired; decomp port 2026-09-01.)",
          ["actor (char id, 0=player)"]),
    308: ("GetDateSnapshot", "time",
          "Read a full calendar snapshot into 5 VM outputs: reg0 = YEAR (+20), reg1 = SEASON "
          "(+16), reg2 = day (+12), reg3 = hour (+8), reg4 = minute (+4) - the verified "
          "cal_inner field order (the same offsets that proved op 305 returns the season). "
          "An earlier note listing minute..season order parroted stale IDB labels. No args.",
          []),
    380: ("StopMusic", "audio",
          "STOP the current BGM with a crossfade out: the handler computes a volume target "
          "from arg/100 but passes track id -1 to BGM_SwitchWithCrossfade (0x7ff7c1f5aa00), "
          "whose a1<0 branch stops the channel voice and discards the target. So the op "
          "halts music; it does not ramp to a level (old 'FadeMusic volume ramp' reading "
          "retired - decomp port 2026-09-01). The single corpus arg is effectively ignored.",
          ["volume arg (computed, then discarded by the stop branch)"]),
    541: ("PopulateQuestKind4ChainedRandom", "quest",
          "Populate the current NPC's daily quest-request slot from template KIND 4. Despite "
          "the 'Chained' name, the chained-roll path is DEAD CODE: the per-iteration arg "
          "read always succeeds (index < count at 0x7ff7c1fd6b20), so each category-seed arg "
          "gets exactly one independent roll. arg0 = target item id, arg1/arg2 = template "
          "bytes 4/5, args[3..] = per-roll category seeds.",
          ["target item id", "param (byte4)", "param (byte5)", "category seed … (one roll each)"]),
    691: ("MultiplyValues", "misc",
          "Multiply ALL the statement's args together, cap the product at 999,999,999, and "
          "write it to reg0. Deterministic - no RNG (the old 'Roll' name was wrong). There "
          "is NO separate count argument: the count is the statement's own packed arg-count "
          "slot, every script arg is a factor, and an EMPTY call yields 0, not 1 "
          "(0x7ff7c1fdfc40; decomp-port confirmed 2026-09-01).",
          ["factors (variadic; every arg is one factor)"]),
}
for _op, (_m, _c, _d, _a) in _AUDIT_2026_09_01B.items():
    _add(_op, _m, _c, _d, _a)

# Alias siblings of audited ops (same handler, "Alias of op N" descs) must carry the
# corrected arg labels too — the audit fixed the primary of each pair:
for _alias, _primary in ((125, 126), (239, 238), (241, 240), (257, 258), (228, 227)):
    META[_alias]["a"] = list(META[_primary]["a"])

# The enum-picker wiring above ran against pre-audit arg hints; drop any picker whose
# arg index the audit removed (e.g. op 493 turned out to take no arguments).
for _k in [k for k in ENUM_ARG_VALUES
           if (k[0] in _AUDIT_2026_09_01 or k[0] in _AUDIT_2026_09_01B)
           and k[1] >= len(META[k[0]]["a"])]:
    del ENUM_ARG_VALUES[_k]
