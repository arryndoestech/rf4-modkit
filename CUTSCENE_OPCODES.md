# RF4S Cutscene Opcode Reference

Reverse-engineered `rf3.mc` cutscene Script VM opcodes (`g_sceneActionHandlerTable`, RF4S.exe+0x4DB790, 763 slots).

Auto-generated from `rf4s_modkit/opcode_meta.py` by `gen_opcode_reference.py` — **711** named opcodes across 14 categories (plus 52 reserved/unused slots), the control-flow opcodes, the expression grammar, and the **em.bin** Event-Manager opcodes scenes bridge to. Do not edit by hand; re-run the generator to refresh. This is the GUI-free companion to the editor's Ctrl-hover tooltips.

## Contents

- [Dialogue & portraits](#dialogue--portraits) (101 ops)
- [Camera / screen](#camera--screen) (26 ops)
- [Actors & player](#actors--player) (182 ops)
- [Companions & party](#companions--party) (19 ops)
- [Flags & variables](#flags--variables) (34 ops)
- [Audio](#audio) (12 ops)
- [Time & calendar](#time--calendar) (17 ops)
- [Items, rewards, economy](#items-rewards-economy) (51 ops)
- [Effects & world](#effects--world) (23 ops)
- [Quests](#quests) (39 ops)
- [Scene flow / control](#scene-flow--control) (29 ops)
- [Queries](#queries) (166 ops)
- [Other](#other) (7 ops)
- [No-op (PC-port stub)](#no-op-pc-port-stub) (5 ops)
- [Control opcodes (flow backbone)](#control-opcodes-flow-backbone) (15 ops)
- [Expression operands (argument encoding)](#expression-operands-argument-encoding)
- [Event Manager (em.bin) opcodes](#event-manager-embin-opcodes)
- [Opcode index (by number)](#opcode-index-by-number)

## Dialogue & portraits

### `op 5` — ShowNpcBubbleVariant(line id, sub-token, emote/param)
*handler:* `Script_VMOp_ShowNpcBubbleVariant`

Show an NPC speech/thought bubble — a variant form of ShowNpcBubble (op 6) built on the same NpcBubble_DispatchFromDescriptor pipeline. Blocks (returns busy) until any active screen fade completes. Takes THREE args (corpus: all 793 uses pass 3): arg0 = line id (into rf3mc.<locale>; descriptor u16 slot 0), arg1 = sub-token (descriptor u16 slot 1), arg2 = a byte param/emote (descriptor byte 6; corpus values like 254). The old hint list promised a 4th sfx/emote arg that the handler never reads.

Args:
  0. line id
  1. sub-token
  2. emote/param (byte)

### `op 6` — ShowNpcBubble(content id, sub, param, sfx/emote id)
*handler:* `Script_VMOp_ShowNpcBubble`

Show an NPC speech/thought bubble — the core bubble op. arg0 = content id with a dispatch: < 1000 = builtin EMOTE (emote-to-string table); 1000..1927 = dialogue STRING, index = id - 1000 (out of range clamps to 1000; 928 valid entries). arg1 = sub-token, arg2 = extra param (PSB-emote capable), arg3 = sfx/emote (>= 0x1F0 plays a voice line via the NPC-variant remap, else an emote id). Blocks until any active screen fade completes; re-showing identical text is a no-op (per-slot last-text cache).

Args:
  0. content id (<1000=emote, 1000+=line, idx=id-1000)
  1. sub
  2. param
  3. sfx/emote id

### `op 7` — ShowNpcBubble(content id, sub, param, sfx/emote id)
*handler:* `Script_VMOp_ShowNpcBubble`

Alias of op 6 (same handler): show an NPC speech/thought bubble.

Args:
  0. content id (<1000=emote, 1000+=line)
  1. sub
  2. param
  3. sfx/emote id (>=0x1F0=voice)

### `op 8` — DialogueLine(line id)
*handler:* `Dialogue_ProcessLineDirective`

Show a dialogue line. arg0 = line id: >=0x30 = text-archive entry id (the common case, rendered as DIALOG #NNNN), 1-26 = standard slot load, 27-47 = event-participant line (portrait shown for 27-33/41-47), 0xFFFF = end marker. Also picks the speaker's dialogue tick-chime SFX class (Dialogue_PickChimeClassForSpeaker) before showing the text.

Args:
  0. line id (>=0x30 archive entry; 1-26 std slot; 27-47 event line; 0xFFFF end)

### `op 9` — DialogueLine(speaker/line id)
*handler:* `Dialogue_ProcessLineDirective`

Show a dialogue line (portrait speaks; reads speaker/line tokens).

Args:
  0. speaker/line id

### `op 10` — SetSpeakerVoice(name string id, chime/tone)
*handler:* `NpcBubble_DispatchSimpleScriptedLine`

Set the speaker for the following DIALOG line(s) to a NAMED VOICE: name plate only, NO portrait ('no portrait dispatch' — the handler's own contract). This is how off-screen and un-introduced characters speak — the opening's captain monologue (name string 738) and the stowaway bandits' whispers (392) both talk through it. arg0 = the NAME-PLATE string id (a name-archive entry, not an rf3mc line id; latched at sceneCtx+108 so repeats are free); arg1 = the text-tick chime class (0 = default 16785916, 1 = happy, 2 = excited, 3 = variant). IDA-verified (NpcBubble_DispatchSimpleScriptedLine, RF4S.exe+0x20A240).

Args:
  0. name string id
  1. chime/tone (0=default,1=happy,2=excited,3=variant3)

### `op 11` — SetDialogStateBit(mode)
*handler:* `ScriptVMOp11_SetSceneStateBit0FromArg`

Dialogue-state toggle: sets bit0 of the dialogue state word (g_gameGlobalsSlotTable scratch field entries[4]) to (arg==0). Runs before lines (~1584x); a per-line render/advance mode flag (exact purpose tentative).

Args:
  0. mode (0 sets the bit)

### `op 12` — BubbleLineV3(speaker, index, sub)
*handler:* `NpcBubble_DispatchScriptedLineV3Tokens`

Show a scripted speech bubble (3 tokens: speaker, index, sub).

Args:
  0. speaker
  1. index
  2. sub

### `op 13` — BubbleLineV3(line id, line index, sub index)
*handler:* `NpcBubble_DispatchScriptedLineV3Tokens`

Show a scripted speech bubble (3 tokens). arg0 = line id (also picks the chime SFX class and, when changed, remaps via Dialogue_RemapBubbleLineId24To28 into the shown text), arg1 = line index (compacted to a 0-5 bubble category), arg2 = sub index. Builds a bubble descriptor and calls NpcBubble_DispatchFromDescriptor; blocks while a fade runs. Per the IDB analysis the first token is a LINE id, not a speaker id. Unused in the shipped corpus.

Args:
  0. line id
  1. line index (0-5 category)
  2. sub index

### `op 14` — BubbleLineV4(line id, line index, sub index, param)
*handler:* `NpcBubble_DispatchScriptedLineV4TokensWithEmoteSupport`

Show a scripted speech bubble (4 tokens; PSB-emote capable). arg0 = line id (NOT a speaker: when the emote feature flag is on and line id >= 30 it is remapped through the NPC emote PSB table; otherwise used directly for the bubble text). arg1 = line index, arg2 = sub index (>= 0x1F0 triggers the sfx sub-action chain), arg3 = param.

Args:
  0. line id
  1. line index
  2. sub index
  3. param

### `op 15` — ShowSpeakerBubble(speaker, line index, sub, sfx/emote id)
*handler:* `NpcBubble_DispatchScriptedLineV4TokensWithEmoteSupport`

Show a speech bubble line for a SPEAKER, with emote-PSB support. arg0 = speaker (npc/char id: selects the chime class, name text and per-NPC emote byte; with save-config emote flag 0x40 set, ids >= 30 index g_npcEmotePsbTable and get substituted -- the Switch-era PSB emote path). arg1 = line index (passed to Dialogue_LoadAndShowText). arg2 = sub/param. arg3 = trigger: >= 0x1F0 plays a voice sfx, else stored as the bubble emote byte.

Args:
  0. speaker (npc id)
  1. line index
  2. sub
  3. sfx/emote id (>=0x1F0=voice)

### `op 16` — SetSpeakerMC(face frame, emote / voice id, emote / voice id 2, emote / voice id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Lest/Frey (slot 0, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2
  3. emote / voice id 3 (rare)

### `op 17` — SetSpeakerMC(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Lest/Frey (slot 0, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 18` — SetSpeakerVishnal(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Vishnal (slot 1, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 19` — SetSpeakerVishnal(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Vishnal (slot 1, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 20` — SetSpeakerClorica(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Clorica (slot 2, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 21` — SetSpeakerClorica(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Clorica (slot 2, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 22` — SetSpeakerVolkanon(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Volkanon (slot 3, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 23` — SetSpeakerVolkanon(face frame, emote / voice id, emote / voice id 2, emote / voice id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Volkanon (slot 3, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2
  3. emote / voice id 3

### `op 24` — SetSpeakerForte(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Forte (slot 4, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 25` — SetSpeakerForte(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Forte (slot 4, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 26` — SetSpeakerKiel(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Kiel (slot 5, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 27` — SetSpeakerKiel(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Kiel (slot 5, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 28` — SetSpeakerBado(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Bado (slot 6, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 29` — SetSpeakerBado(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Bado (slot 6, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 30` — SetSpeakerMargaret(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Margaret (slot 7, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 31` — SetSpeakerMargaret(face frame, emote / voice id, emote / voice id 2, emote / voice id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Margaret (slot 7, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2
  3. emote / voice id 3

### `op 32` — SetSpeakerDylas(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Dylas (slot 8, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 33` — SetSpeakerDylas(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Dylas (slot 8, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 34` — SetSpeakerArthur(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Arthur (slot 9, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 35` — SetSpeakerArthur(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Arthur (slot 9, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 36` — SetSpeakerPorcoline(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Porcoline (slot 10, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 37` — SetSpeakerPorcoline(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Porcoline (slot 10, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 38` — SetSpeakerXiaoPai(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Xiao Pai (slot 11, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 39` — SetSpeakerXiaoPai(face frame, emote / voice id, emote / voice id 2, emote / voice id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Xiao Pai (slot 11, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2
  3. emote / voice id 3

### `op 40` — SetSpeakerLinFa(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Lin Fa (slot 12, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 41` — SetSpeakerLinFa(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Lin Fa (slot 12, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 42` — SetSpeakerAmber(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Amber (slot 13, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 43` — SetSpeakerAmber(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Amber (slot 13, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 44` — SetSpeakerIlluminata(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Illuminata (slot 14, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 45` — SetSpeakerIlluminata(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Illuminata (slot 14, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 46` — SetSpeakerDoug(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Doug (slot 15, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 47` — SetSpeakerDoug(face frame, emote / voice id, emote / voice id 2, emote / voice id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Doug (slot 15, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2
  3. emote / voice id 3

### `op 48` — SetSpeakerBlossom(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Blossom (slot 16, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 49` — SetSpeakerBlossom(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Blossom (slot 16, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 50` — SetSpeakerDolce(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Dolce (slot 17, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 51` — SetSpeakerDolce(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Dolce (slot 17, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 52` — SetSpeakerJones(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Jones (slot 18, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 53` — SetSpeakerJones(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Jones (slot 18, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 54` — SetSpeakerNancy(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Nancy (slot 19, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 55` — SetSpeakerNancy(face frame, emote / voice id, emote / voice id 2, emote / voice id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Nancy (slot 19, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2
  3. emote / voice id 3

### `op 56` — SetSpeakerLeon(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Leon (slot 20, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 57` — SetSpeakerLeon(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Leon (slot 20, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 58` — SetSpeakerVentuswill(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Ventuswill (slot 21, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 59` — SetSpeakerVentuswill(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Ventuswill (slot 21, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 60` — SetSpeakerSon(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Son (slot 22, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 61` — SetSpeakerSon(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Son (slot 22, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 62` — SetSpeakerDaughter(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Daughter (slot 23, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 63` — SetSpeakerDaughter(face frame, emote / voice id, emote / voice id 2, emote / voice id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Daughter (slot 23, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2
  3. emote / voice id 3

### `op 64` — SetSpeakerPico(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Pico (slot 24, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 65` — SetSpeakerPico(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Pico (slot 24, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 66` — SetSpeakerguest25(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=guest25? (slot 25, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 67` — SetSpeakerguest25(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=guest25? (slot 25, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 68` — SetSpeakerguest26(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=guest26? (slot 26, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 69` — SetSpeakerguest26(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=guest26? (slot 26, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 70` — SetSpeakerBarrett(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Barrett (slot 27, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 71` — SetSpeakerBarrett(face frame, emote / voice id, emote / voice id 2, emote / voice id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Barrett (slot 27, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2
  3. emote / voice id 3

### `op 72` — SetSpeakerRaven(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Raven (slot 28, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 73` — SetSpeakerRaven(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=Raven (slot 28, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 74` — SetSpeakerguest29(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=guest29? (slot 29, from the opcode number), left side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 75` — SetSpeakerguest29(face frame, emote / voice id, emote / voice id 2)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s) -- designates the speaker=guest29? (slot 29, from the opcode number), right side, and their portrait. Carries no text (the next DIALOG does), and PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) -- one cue can carry a whole multi-line speech (917 shipped scenes do). arg0 = face frame (0=neutral, 1=anger, 2=cry, 3=smile, 4=surprise, 5=shy, 6+ per-character extras -- selects <NN>_<NAME>_face_<FFF> portrait art). arg1/arg2 = up to two trigger ids, each either an emote-bubble id (186-192: 188 normal, 189 anger, 190 sad, 191 smile, 192 surprise; row/kind-dependent, renders !/? for surprise/troubled) OR a voice-line sfx id (>= 0x1F0 -- the engine's dual-use threshold -- played through the NPC-variant remap). NOTE: arg2 is a second trigger id, not a target actor.

Args:
  0. face frame
  1. emote / voice id
  2. emote / voice id 2

### `op 83` — CloseDialogueBubbles(which)
*handler:* `Script_VMOp_CloseBubblesWaitClosed`

Close on-screen dialogue bubble(s) and BLOCK the scene until the close animation finishes. arg selects which: 0 = close the FIRST bubble slot (ctx+88), 1 = close the SECOND slot (ctx+96), any other value = close BOTH. Each path calls DialogueBubble_TransitionState(slot, 0) and then keeps returning 'blocked' while the bubble state / g_npcBubbleActiveByScreen shows a bubble still closing. Use before switching speakers or ending a conversation cleanly. (The old hint '0 = both' was wrong: 0 closes one slot; only a value other than 0/1 closes both.)

Args:
  0. which (0=slot 0, 1=slot 1, other=both)

### `op 92` — EndDialogue()
*handler:* `ScriptVMOp_DialogueTeardownBubblesAndCommit_NoArgs`

Close both speaker bubbles and commit the dialogue state -- the end of a spoken exchange. ALSO CLEARS THE SPEAKER (sceneCtx+108 = -1): the next DIALOG without a new SetSpeaker is narration again (plain box, no name/portrait). Returns to the scene controller when no other event is in flight. The #2 most-used action op (10,564 uses) -- every dialogue beat ends with one.

### `op 93` — SetDialogueSpeakerEmote(emote id)
*handler:* `ScriptVMOp_SetDialogueSpeakerEmoteByArg`

Set the CURRENT dialogue speaker's facial emote/expression and re-target the portrait to it. arg0 = emote id: a 3-bit field (0..7), of which the game names 0-5 (0=normal, 1=angry, 2=sad, 3=laugh, 4=surprise, 5=blush -- the picker); 6-7 are valid field values but have no named portrait. This is the dialogue-portrait expression (0-7), a DIFFERENT space from op319 SetEmote's per-NPC record+57 emote byte. Use to change a speaker's expression mid-conversation without re-issuing the SetSpeaker.

Args:
  0. emote id (0-7)
     - `0` = normal
     - `1` = angry
     - `2` = sad
     - `3` = laugh
     - `4` = surprise
     - `5` = blush

### `op 94` — SetSpeakerEmote0()
*handler:* `ScriptVMOp_SetDialogueSpeakerEmoteFromOpcode`

Set the current dialogue speaker's facial emote to 0 and retarget the portrait (Dialogue_SetSpeakerEmoteAndRetargetPortrait). The emote id is ENCODED BY THE OPCODE: emote = op - 94; ops 94-97 share this one handler (emotes 0-3), which reads its own opcode back from sceneCtx+260 — it does NOT read an actor field. Takes no args. The general form is op 93, which takes the emote as a normal argument.

### `op 95` — SetSpeakerEmote1()
*handler:* `ScriptVMOp_SetDialogueSpeakerEmoteFromOpcode`

Set the current dialogue speaker's facial emote to the FIXED id 1 and retarget the portrait. Ops 94-97 share one handler that recovers the emote from the opcode itself: emote = op - 94 (94->0, 95->1, 96->2, 97->3), read from the currently-dispatching opcode byte at sceneCtx+260. Calls Dialogue_SetSpeakerEmoteAndRetargetPortrait(1). No args. The general form is op 93 (SetSpeakerEmoteByArg), which takes the emote as a normal argument.

### `op 96` — SetSpeakerEmote2()
*handler:* `ScriptVMOp_SetDialogueSpeakerEmoteFromOpcode`

Set the current dialogue speaker's facial emote to the FIXED emote id 2 and retarget the portrait (Dialogue_SetSpeakerEmoteAndRetargetPortrait). The emote id is encoded in the OPCODE, not read from the actor: ops 94-97 share this handler and map to emotes 0-3 (emote = op - 94, recovered from the currently-dispatching opcode at sceneCtx+260). The general form is op 93, which takes the emote as a normal argument. Takes no args. Corpus: appears right after a SetSpeaker* cue, before the DIALOG line.

### `op 97` — SetSpeakerEmote3()
*handler:* `ScriptVMOp_SetDialogueSpeakerEmoteFromOpcode`

Set the dialogue speaker's facial emote to id 3 and retarget the portrait (Dialogue_SetSpeakerEmoteAndRetargetPortrait). The emote id is ENCODED IN THE OPCODE, not read from the actor: ops 94-97 map to emote 0-3 via (opcode - 94), same trick as the SetSpeaker cluster. Takes no args. The general form is op 93 (SetDialogueSpeakerEmoteByArg), which takes the emote id as a normal argument.

### `op 98` — SetDialogueField161(value)
*handler:* `Script_VMOp_SetDialogueField161`

Write a byte to field +161 of the current dialogue task. arg0 = value. Low-level dialogue-display flag; exact effect is engine-internal (only touched by a few scenes).

Args:
  0. value

### `op 149` — PlayerScriptedTalkAnim(anim id, trigger flag)
*handler:* `ScriptVM_Op_BeginPlayerScriptedTalkWithAnim`

Put the player into a scripted-talk pose and play an animation on them — for gestures during dialogue (nod, bow, shrug). arg0 = anim id (-1 = the default 'standard talk' anim 187). arg1 non-zero sets the anim-trigger-active bit.

Args:
  0. anim id (-1 = default talk)
  1. trigger flag (0/1)

### `op 243` — EndDialogueLock(mode)
*handler:* `Script_VMOp_EndDialogueLock`

End the dialogue lock — release the player-input / scene lock held during a conversation and hand control back to the player. arg0 = 0 performs the release (non-zero is a no-op). Use to close out a conversation.

Args:
  0. mode (0 = end lock)

### `op 316` — SetNpcVisible(npc id, visible)
*handler:* `Script_VMOp_SetNpcVisibility`

Show or hide a scene NPC.

Args:
  0. npc id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. visible

### `op 319` — SetEmote(npc id, emote id)
*handler:* `Script_VMOp_SetNpcEmoteByte`

Set an NPC's facial-expression / emote byte (record +57), switching its portrait face (happy/sad/angry/etc) -- e.g. mid-dialogue. Same handler as op320 SetNpcEmoteByte. NOT a transient emote 'bubble' popup (those are op5/6/7 ShowNpcBubble).

Args:
  0. npc id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. emote id

### `op 320` — SetNpcEmoteByte(npc, emote id)
*handler:* `Script_VMOp_SetNpcEmoteByte`

Set an NPC's persistent emote / facial-expression byte (record +57) — the expression it shows (happy / sad / angry …) both in and out of dialogue, and the last-dialogue-emote global. arg0 = npc (char id), arg1 = emote id. Distinct from op 93 (which sets the CURRENT dialogue speaker's emote only).

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. emote id

### `op 322` — SetMood(npc id, mood id)
*handler:* `Script_VMOp_SetNpcMoodByte`

Set an NPC's MOOD byte (record +56) -- a per-NPC temperament/mood state. Distinct from the displayed facial expression / emote byte (record +57, op319 SetEmote); unlike SetEmote this does NOT update g_lastDialogueEmoteId. Same handler as op323.

Args:
  0. npc id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. mood id

### `op 323` — SetNpcMoodByte(npc, mood id)
*handler:* `Script_VMOp_SetNpcMoodByte`

Set an NPC's persistent MOOD byte (record +56) — its temperament/default expression state, distinct from the emote byte (+57, op 320). arg0 = npc (char id), arg1 = mood id.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. mood id

### `op 357` — SetVar7(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind7`

Write `value` into global script-variable bank 7 at [index] (Globals_LookupChoiceCommitStateSlotByKindId(7), index <= 51). Same family as SetVar0/3/15: ENGINE-GLOBAL slots shared with the choice-commit system and readable by dialogue-text substitution codes. Shipped scripts use bank 7 to stage NUMBERS for the next menu/dialog -- e.g. order-shop scenes run GetEffectCost(license/upgrade, 0); SetVar7(0, reg0); GetEffectCost(...); SetVar7(1, reg0); ... so the price list can be substituted into the text. NOT a portrait/face op -- the handler is a bare kind-7 var write.

Args:
  0. index
  1. value

### `op 413` — SetDialogueState8(value)
*handler:* `Script_VMOp_SetEntries8DwordFromArg`

Set a low-level dialogue-box auxiliary state value (game-globals slot 8, one of the aux speaker/line-descriptor fields cleared together with slots 7 and 9 when the dialogue HUD tears down). arg0 = value.

Args:
  0. value

### `op 415` — SetDialogueFlag4Bit2(cond)
*handler:* `Script_VMOp_SetEntries4Bit2ByZero`

Set or clear dialogue-box control bit 0x4 in the dialogue flags word: arg0 == 0 sets the bit, non-zero clears it. A low-level dialogue-box toggle.

Args:
  0. cond (0=set bit, else clear)

### `op 555` — SetNpcBubbleFlavor(npc, flavor id)
*handler:* `Script_VMOp_SetNpcDialogueBubbleFlavorById`

Set an NPC's ambient dialogue-bubble flavor (record +26) — which floating speech-bubble variant it shows (mood / '!' / '?' etc). arg0 = npc (char id), arg1 = flavor id. See project_rf4s_dialogue.md.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. flavor id

### `op 556` — SetNpcBubbleFlavor(npc, flavor id)
*handler:* `Script_VMOp_SetNpcDialogueBubbleFlavorById`

Alias of op 555 (same handler): set an NPC's dialogue-bubble flavor.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. flavor id

### `op 610` — SetChoiceVisibleMask(choice 0 visible, choice 1 visible, …)
*handler:* `Script_VMOp_SetSceneChoiceVisibleMaskFromArgs`

REBUILD the scene's choice-visibility mask from a list of booleans — zeroes mask dword 0 (choices 0..31; dwords 1-3 are untouched), then sets bit i when arg i is non-zero. Each bit gates whether option i appears in the next PROMPT_CHOICE, and the picked VISIBLE ROW maps back through the set bits to the option's ORIGINAL index in reg0 (that's what the SWITCH_EQ after a staged prompt dispatches on). Writes 1 to reg0 now if any bit is set. IDA-verified 2026-08-17 (Script_VMOp_SetSceneChoiceVisibleMaskFromArgs).

Args:
  0. choice 0 visible
  1. choice 1 visible
  2. …

### `op 611` — ClearChoiceVisibleRange(start index, count)
*handler:* `Script_VMOp_ClearSceneChoiceVisibleMaskRange`

Clear COUNT choice-visibility bits starting at START (hide those choices; dword 0 only, i.e. options 0..31). arg0 = start bit, arg1 = count — NOT a from/to pair (IDA-verified 2026-08-17: clears bits [start, start+count)). Writes 1 to reg0 if any bit anywhere is still set. Companion to SetChoiceVisibleMask (op 610).

Args:
  0. start index
  1. count

### `op 612` — SetChoiceVisibleBit(choice index, visible)
*handler:* `Script_VMOp_ToggleSceneChoiceVisibleBit`

Show or hide a SINGLE choice by index in the scene's choice-visibility mask. arg0 = choice index (0-127), arg1 = visible (1) / hidden (0). Writes 1 to reg0 if any choice is still visible — scripts branch on 'is anything left to offer'. The next PROMPT_CHOICE presents only flagged options and maps the pick back to the original index in reg0; the prompt then CLEARS the whole mask.

Args:
  0. choice index (0-127)
  1. visible (0/1)

### `op 613` — CalcChoicePrescroll(option index)
*handler:* `Script_VMOp_CalcChoiceDialogPrescrollFromVisibleMask`

Compute the upcoming choice menu's pre-scroll position. arg0 = an option index; the handler subtracts the number of HIDDEN options below it (clear bits in the visible mask at scene+244, capped by the option count at scene+243), i.e. arg0's position within the visible list, and stores the result in the GLOBAL g_choiceDialogPrescrollCount -- not in a VM register. Call between SetChoiceVisibleMask and PROMPT_CHOICE so the list opens positioned at that option.

Args:
  0. option index

### `op 614` — SetDialogueSpeaker(side)
*handler:* `Script_VMOp_SetDialogueSpeakerSideByte`

Set which side speaks the NEXT dialogue line (byte 2 of the active line descriptor). Value 2 = secondary/right-side speaker: the nameplate + text box render on the right using the question/choice-bubble widgets and recoloured nameplate. Any other value = the normal left speaker. Lets a script flip the apparent speaker between two on-screen characters.

Args:
  0. side (2=right/secondary, else left)

### `op 615` — ArmChoiceOption(staged value 1, staged value 2, staged value 3)
*handler:* `Script_VMOp_SetUpToThreeChoiceDialogValuesAndArm`

ARM the next DIALOG statement as a CHOICE OPTION: instead of displaying, that DIALOG's line is QUEUED into the pending-option list (44-byte record in g_dialoguePendingLineQueue) together with up to 3 staged follow-up values, gated on the option's visibility bit. The canonical list shape is [ArmChoiceOption(v); DIALOG line] × N — then a later PROMPT_CHOICE (often in a DIFFERENT scene; the queue is global) presents the queued lines. On selection the picked option's line is ECHOED as the next spoken line and its staged values are committed to the choice-commit state slots (kinds 4/5/6 — read back via the GetVar ops or ConsumeChoiceCommitResult). 1,803 uses — the most common choice idiom; 99.7%% are immediately followed by their DIALOG. IDA-verified 2026-08-17 (deferred path of Dialogue_HandleScriptActionShowLine + ChoiceDialog_CommitSelectionAndDispatchActions).

Args:
  0. staged value 1
  1. staged value 2
  2. staged value 3

### `op 623` — SetDialogueAutoAdvance(mode)
*handler:* `Script_VMOp_SetDialogueAutoAdvanceTimingMode`

Set how the current dialogue line auto-advances (the timing mode). 0 = no auto-advance (wait for the player to press confirm); 1 = auto-compute a reading timer from the text length (~7*(len/3)+30 frames); any other N = dismiss the line after exactly N frames. Lets a scripted line time out on its own.

Args:
  0. mode (0=off, 1=auto, N=frames)

### `op 624` — SetDialogueHoldFrames(frames)
*handler:* `Script_VMOp_SetDialogueHoldFrameCounter`

Seed the dialogue box's per-frame hold countdown (byte 3 of the line descriptor). The speech-box state machine decrements it once per frame, so this briefly delays the box for arg0 frames (0-255). Used to pace a line before it starts advancing.

Args:
  0. frames (0-255)

### `op 698` — SetShopkeeperMessage(shopkeeper message index)
*handler:* `Script_VMOp_WriteJustmMessageRegAndCallback`

Set the active shop's shopkeeper message/greeting line to `arg`. Writes arg (a message index) into the 10-bit packed GameFlag field 3006 = REG_JUSTM_MESSAGE (so the chosen greeting persists), then Shop_SetMessageTextFromArchive(arg): loads locale text archive 15206 (0x3B66), copies entry[arg] (clamped to <360) into the shop's dialogue-text sprite and reveals it with the typewriter effect. CORRECTION: this is NOT an achievement. The raw handler id 39870 decodes (via GameFlags_WriteField) to packed-flag id 3006, width 10 -- and 3006 is not among the ~30 named-achievement switch cases, so it falls through to a plain packed-flag write. The IDA name `WriteJustmMessageRegAndCallback` is accurate (Justm = the shopkeeper message register). Corpus: bank 292 @0x0e7e sets arg=244.

Args:
  0. shopkeeper message index (0-359, indexes locale text archive 15206)

### `op 699` — SetDialogueSpeakerIf(condition)
*handler:* `Script_VMOp_SetDialogueSecondarySpeakerIfNonzero`

Conditional form of SetDialogueSpeaker (op 614): if arg0 is non-zero, mark the next line as spoken by the secondary (right-side) speaker (descriptor byte 2 = 2); if zero, leave the current speaker side unchanged. Handy for 'if this NPC is present, put the line on their side'.

Args:
  0. condition (non-zero = right speaker)

## Camera / screen

### `op 158` — SetMapAmbientColor(R, G, B, apply now)
*handler:* `ScriptVM_Op_SetMapColorTriple`

Set the map's ambient RGB tint (mood / time-of-day lighting) — writes the three internal colour triples. arg0/arg1/arg2 = R/G/B (0-255). arg3 = apply now (non-zero forces an immediate palette reload; 0 defers to the next map tick).

Args:
  0. R (0-255)
  1. G (0-255)
  2. B (0-255)
  3. apply now (0/1)

### `op 159` — SwapMapPalette(apply now)
*handler:* `ScriptVMOp_SwapMapPaletteAndTriggerReload`

Swap the current map to its staged alternate palette bank (day/night, weather, or a magic/mood shift) by copying the staging colours over the active ones. arg0 = apply now (non-zero = immediate palette reload; 0 = deferred).

Args:
  0. apply now (0/1)

### `op 186` — SetCameraPosition(x, y, snap camera now)
*handler:* `Script_VMOp_SetCameraPositionCoords`

Set the camera ANCHOR at world tile (x, y) (g_scriptMarkAnchorPosQ12, clamped to the map's camera bounds). arg2 non-zero additionally SNAPS the live camera to the anchor immediately (writes g_cameraPosQ12 + the map task's scroll origin) — the instant-cut variant; arg2 = 0 leaves the camera to ease there. The opening parks its vista with (353, 0, snap=1). Coords are tiles (stored as Q12). IDA-verified 2026-08-10.

Args:
  0. x (tiles)
  1. y (tiles)
  2. snap camera now (0/1)

### `op 187` — ReattachCameraToActor(actor slot, snap position)
*handler:* `Script_VMOp_ResetCameraToActorVariant`

Re-attach the camera rig to the player(s) and optionally recenter on an actor. BLOCKING: holds the scene until it settles. arg0 = actor scene-slot to center on (0 = player); arg1 != 0 also hard-snaps the anchor + player pos to that actor. Near-duplicate of op 191 (ResetCameraToActor).

Args:
  0. actor slot (0=player)
  1. snap position (0/1)

### `op 188` — SnapCameraToPlayer(instant)
*handler:* `Script_VMOp_SnapCameraToPlayer`

Recenter/lock the camera on the player: sets scene flag +116 bit 0x40000 (camera-recenter request) and actor flag 4 on all players. arg != 0: additionally snapshots the CURRENT CAMERA position into the script anchor g_scriptMarkAnchorPosQ12 (the same anchor op 193 sets and op 196 tests) and rewrites the map scroll origin (map work_buffer[11..12]) to the camera tile - an instant snap. arg == 0: commits the camera target clamped to map bounds (smooth ease). Note the snapshot stores the camera position, not the player's tile.

Args:
  0. instant (0=ease, 1=snap)

### `op 189` — ResetCameraToPlayer(snap)
*handler:* `Script_VMOp_WarpPlayerAndResetCamera`

Reset the camera rig to the player and re-attach it (single- or co-op). arg != 0 also hard-snaps the camera anchor + map scroll origin to the player's current tile. Use after teleporting the player to kill the follow lag.

Args:
  0. snap (0/1)

### `op 190` — SetCameraTarget(x, y, pan speed)
*handler:* `Script_VMOp_SetCameraTarget`

PAN the camera to world tile (x, y): sets the anchor (clamped to camera bounds) and starts a constant-velocity pan toward it. Also locks player movement (flags 1+4) so the shot holds. arg2 = the PAN SPEED: speed×4096/100 Q12, capped 0xF000 — i.e. arg2/100 tiles per frame, max 15 (shipped scenes use 50-400 = 0.5..4 tiles/frame; the opening's deck pans use 200 = 2 tiles/frame). Follow with WaitCameraAtMark (op 195) to HOLD the scene until the pan arrives — that pairing is what paces the between-line camera sweeps. IDA-verified 2026-08-10 (Camera_ComputeDistanceVectorToTarget; the old 'zoom/distance' label was wrong — zoom is op 202).

Args:
  0. x (tiles)
  1. y (tiles)
  2. pan speed (/100 tiles per frame, cap 15)

### `op 191` — ResetCameraToActor(actor slot, mode)
*handler:* `Script_VMOp_ResetCameraToActor`

Re-attach the camera to the player(s) and center on an actor. BLOCKING: returns busy until a ~3-frame settle completes. arg0 = actor scene-slot (0 = player). arg1 = mode: 0 -> hard-snap the anchor to the actor, -1 -> attach only (no recompute), any other value -> ease toward the actor.

Args:
  0. actor slot (0=player)
  1. mode (0=snap, -1=attach only, else ease)

### `op 192` — ResetCameraToActor(actor slot, mode)
*handler:* `Script_VMOp_ResetCameraToActor`

Alias of op 191 (same handler): re-attach + center the camera on an actor, blocking until a ~3-frame settle completes.

Args:
  0. actor slot (0=player)
  1. mode (0=snap, -1=attach only, else ease)

### `op 193` — SetCameraAnchorToPlayer(mode)
*handler:* `Script_VMOp_SetCameraAnchorToPlayerOrTarget`

Anchor the scene camera (handler Script_VMOp_SetCameraAnchorToPlayerOrTarget). Always sets camera-mode bit 0x40000 on ctx+116, then branches on arg: (0) anchor the camera to the player -- as a side effect this also snapshots the player's world position into the script 'mark' (g_scriptMarkAnchorPosQ12) and writes the tile (x, y) into the current map task's work_buffer[+11]/[+12]; (non-0) refresh the camera toward the current target actor. Ends with Camera_ComputeDistanceVectorToTarget. The mark it records in mode 0 is what QueryPlayerMovedBeyondSnapshot (op 196) reads to detect whether the player has moved.

Args:
  0. mode (0 = anchor to player + set movement mark, else refresh to target)

### `op 194` — FocusCameraOnPlayer((ignored — engine reads no args))
*handler:* `Script_VMOp_FocusCameraOnPlayerWait`

Snap/commit the camera target onto the player (Camera_CommitTargetAndClampToBounds + distance-vector recompute, sets camera flag 0x40000) and BLOCK the scene for 3 frames while it settles. The engine reads NO arguments, but every shipped statement passes one (e.g. FocusCameraOnPlayer(400) in the corpus) — a vestigial ease-speed the RF4S handler ignores. Handy to 'return to the hero' between cutscene shots.

Args:
  0. (ignored — engine reads no args)

### `op 197` — ShakeCamera(kind, duration)
*handler:* `Script_OpRequestCameraJitterEffect`

Shake / jitter the screen (PlayerEffect_RequestJitterByKind -> tick PlayerEffect_TickJitterByKind). arg0 = jitter KIND 1-6 (a shake pattern; the value is also a priority -- a running shake only escalates to a HIGHER kind, never a lower one): 1 = light 12-step jitter, 2 = medium 12-step signed jitter, 3 = short sharp 4-step jitter, 4 = long 22-step jitter, 5 = heavy 22-step jitter (2x amplitude), 6 = rotational rumble (sin-cos with decay). kind 0 resets/stops the shake. arg1 = duration in frames. Used for impacts, quakes, explosions.

Args:
  0. kind (1-6, 0=stop)
     - `0` = Stop
     - `1` = Light jitter
     - `2` = Medium jitter
     - `3` = Short sharp jitter
     - `4` = Long jitter
     - `5` = Heavy jitter
     - `6` = Rotational rumble
  1. duration

### `op 199` — SetCameraTargetActor(actor slot, pan speed)
*handler:* `Script_VMOp_SetCameraTargetActor`

Pan the camera to an actor chosen by scene-slot (same 0..0x2F slot space as dialogue speakers; slot 0 / empty slot falls back to the player). Anchors on the actor's world position and recomputes the follow vector; locks player movement. arg1 = the same PAN-SPEED channel as SetCameraTarget (op 190): arg1/100 tiles per frame, cap 15 (shipped scenes use ~100-400).

Args:
  0. actor slot
  1. pan speed (/100 tiles per frame)

### `op 200` — SetCameraTargetActor(actor slot, pan speed)
*handler:* `Script_VMOp_SetCameraTargetActor`

Alias of op 199 (same handler): pan the camera to an actor by scene-slot. arg1 = the same pan-speed channel as op 199 (shipped scenes use 400-800 here = 4..8 tiles/frame).

Args:
  0. actor slot
  1. pan speed (/100 tiles per frame)

### `op 201` — SetCameraSettleMode(settle on)
*handler:* `Script_VMOp_SetCameraSettleMode`

Enable/disable the camera's SETTLE (soft-landing) mode — bit 0x40 of the camera state flags. When set, once the camera is within ~12 frames' worth of travel of its target its velocity decays 0.8125x per frame down to a 0.125 floor, giving a decelerating arrival instead of a constant-velocity stop. Effective on scripted pans (the follow camera rewrites its speed every frame, overwriting the decay). arg0 non-zero sets, 0 clears. Resolved 2026-08-25 via Widget_TickTransformEaseTowardTargets bit-0x40 arm.

Args:
  0. settle on (0/1)

### `op 202` — SetCameraZoom(zoom, snap)
*handler:* `Script_VMOp_SetCameraZoom`

Set the camera zoom / pull-back distance: the engine stores (arg0 - 1500) in the player camera struct (+68 target). arg1 != 0 SNAPS (writes current +64 AND target +68); arg1 == 0 eases (target only, view drifts to the new framing). Both paths apply the zoom - the old 'arg1 = reset to default rig' reading was wrong (IDB-corrected 2026-08-25; re-confirmed in the 2026-09-01 decomp port). Magnification = 1 + arg0/1800.

Args:
  0. zoom (distance = arg-1500)
  1. snap (0=ease to it, 1=jump)

### `op 334` — FadeScreen(fade target, duration)
*handler:* `Script_VMOp_BeginDualScreenFadeWithKindAndDuration`

Fade both screens (dual-screen, 3DS legacy) via two FadeTask_Init calls -- channel A (screen overlay) + channel B (scene tint). arg0 = signed fade TARGET: its SIGN picks the overlay colour (negative -> BLACK, positive -> WHITE) and |arg0|/16 = the target opacity (16 = fully opaque, 8 = half). Corpus: -16 = fade to black (dominant; used by Return-to-Title) and +16 = fade to white. arg1 = DURATION: the fade animates over arg1/100 frames (6000 -> 60 frames ~= 1s at 60fps; 18000 -> ~3s; 0 or <100 -> immediate). NOTE: arg1 is NOT milliseconds -- effective frames = arg1/100 (verified via FadeTask_Init(target_alpha, frame_count, channel)). Resolved by static analysis.

Args:
  0. fade target (sign: - = to black, + = to white; |v|/16 = opacity; -16 = black, +16 = white)
  1. duration (frames = arg1/100; 6000 ~= 1s, 0 = immediate)

### `op 335` — FadeScreenToClear(duration)
*handler:* `Script_VMOp_FadeScreenToClearOverDuration`

Fade the screen overlay back toward CLEAR (target alpha 0 = fully transparent, revealing the scene) over arg0/100 frames -- the reveal counterpart of op 334 FadeScreen. Re-launches the current dual-screen fade task on both channels toward alpha 0 via FadeTask_Init(0.0, arg0/100, channel), keeping the current overlay colour. CORRECTION: earlier called 'FadeChangeKindOnly' with a 'kind' arg -- verified the single arg is the DURATION (feeds FadeTask_Init's frame_count) and the target is always clear, NOT a kind selector. Corpus arg values (6000/12000/18000...) match op334's durations.

Args:
  0. duration (frames = arg0/100; 6000 ~= 1s)

### `op 336` — SetFadeColor(R, G, B, duration)
*handler:* `Script_VMOp_SetFadeColorRGBOverDuration`

Set the screen fade/tint colour, R/G/B each 0-255, applied to both screen channels (top + bottom). arg3 = duration in frames: 0 snaps the colour immediately, > 0 animates the fade task toward it (per-frame delta). Pair with FadeScreen (op 334) to fade in/out through a chosen colour.

Args:
  0. R (0-255)
  1. G (0-255)
  2. B (0-255)
  3. duration (frames)

### `op 412` — BlackScreen(direction, duration)
*handler:* `rf3sScriptExecExtCmd_BlackScreen`

Fade the screen to / from a solid black overlay (spawns the black-overlay object, then drives g_currentFadeTask via FadeTask_Init). arg0 = DIRECTION: 1 = fade TO black, 0 = fade FROM black (reveal). arg1 = DURATION in frames (e.g. 15/30/60/180 = 0.25/0.5/1/3 s at 60fps; a negative value such as -1 = instant). Handler rf3sScriptExecExtCmd_BlackScreen. CORRECTION: earlier curation wrongly said 'takes no arguments' -- the handler reads two (argbuf[-3]=direction, [-5]=duration).

Args:
  0. direction (1 = to black, 0 = from black / reveal)
  1. duration (frames; <0 = instant)

### `op 595` — SetMinimapMarker(npc)
*handler:* `Script_VMOp_SetMinimapMarkerOrClear`

Place or clear a quest-target marker on the minimap. arg0 = npc (char id) to mark — the marker points the player at that NPC — or -1 to clear the marker. Guides the player to a quest NPC.

Args:
  0. npc (char id, -1=clear)
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 656` — SetMapScrollSpeedX(scroll speed X, snap)
*handler:* `Script_VMOp_SetMapUvScrollSpeedXTarget`

Set the map's X-axis tile UV-SCROLL velocity target — NOT a fade alpha (IDB corrected 2026-08-08: work_buffer[254] is scroll velocity). arg0 = speed x10000 (e.g. -200 -> -0.02/frame; drives the scrolling-cloud sky on the airship deck and couples to the propeller flipbook rate), arg1 = snap flag (1 = jump current to target, 0 = ease toward it at 0.002-0.05/frame). Non-zero speed also enables repeat-wrap on layer-0 tiles. The next slot (op 657) is the Y channel.

Args:
  0. scroll speed X (x10000)
  1. snap (0/1)

### `op 657` — SetMapScrollSpeedY(speed, snap)
*handler:* `Script_VMOp_SetMapUvScrollSpeedYTarget`

Set the target Y-axis scroll speed of the map's tile UV scrolling (the auto-scrolling texture layer): target = value/10000, stored in the map task's work buffer (float slots 257=target, 259=prev; eased toward the target by MapTask_Tick, consumed by the tile-scroll/time-tint renderer). arg1 = snap flag: non-zero jumps the current value (slot 255) straight to the target, 0 eases. Y twin of op 656 (X axis). NOT a fade op — the old 'map fade channel 1' reading was wrong. Unused in the shipped corpus.

Args:
  0. speed (x10000)
  1. snap (0=ease, 1=jump)

### `op 683` — PlayCutsceneVideo(video id)
*handler:* `Script_VMOp_PlayCutsceneVideoOrAdvanceDialogue`

Play a pre-rendered full-motion cutscene VIDEO by id (a WebM movie), OR — if a dialogue is mid-step — advance it to the next step instead. arg0 = video id. The op that triggers an FMV cutscene.

Args:
  0. video id

### `op 687` — RebuildMinimap()
*handler:* `Script_VMOp_RebuildMinimapForActiveContext`

Rebuild the minimap for the active context.

### `op 688` — ToggleMinimap(visible)
*handler:* `Script_VMOp_ToggleMinimapVisibilityAndQueueFade`

Show/hide the minimap and queue a fade.

Args:
  0. visible

## Actors & player

### `op 77` — SetActorFacingAngle(actor, target facing, turn speed)
*handler:* `Script_VMOp_SetActorFacingAngle`

Turn an actor toward a target facing. arg0 = actor (char id, 0=player; resolved by matching the scene's two bound actor slots ctx+88/ctx+96, not the global tables). arg1 = TARGET facing, written raw (u16) to motion field +94 while +92 snapshots the current facing (+44) as the lerp start; bit 0x8000 of arg1 clears motion byte +99 (turn-mode/snap selector, default 1). arg2 = TURN SPEED: run through the engine's canonical speed formula ((167773*x)>>12, here x25 scale) into motion field +88, with turn progress (+32) reset to 0. NOTE: the previous hints had arg1/arg2 swapped (rate vs angle).

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. target facing (bit 0x8000 = mode flag)
  2. turn speed

### `op 78` — SetActorFacingAngle(actor, turn rate, angle)
*handler:* `Script_VMOp_SetActorFacingAngle`

Alias of op 77 (same handler): set an actor's target facing angle + turn rate.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. turn rate (bit 0x8000 = ease)
  2. angle (degrees)

### `op 79` — SetActorTurnAngle(actor, turn delta, turn speed)
*handler:* `Script_VMOp_SetActorTurnAngle`

Turn an actor by a RELATIVE amount: adds signed arg1 to the motion target-turn field (+94); arg1's sign also sets the turn-direction byte (+99: positive=1, negative=0 — the old 'bit 0x8000 = ease vs snap' claim was just this sign bit). arg2 = turn SPEED, not an angle: it goes through the same 167773/4096 (x40.96, then x25) Q12 speed conversion as the move ops' speed channel and lands in motion +88. arg0 = actor (char id, matched against the two scene actor slots; 0 = player). Corpus shows paired +40/-40 wiggles at speed 100 during dialogue (head-shake beats).

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. turn delta (signed, sign=direction)
  2. turn speed

### `op 80` — SetActorTurnAngle(actor, turn delta, angle)
*handler:* `Script_VMOp_SetActorTurnAngle`

Alias of op 79 (same handler): add to an actor's turn rate + aim it at an angle.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. turn delta (bit 0x8000 = ease)
  2. angle (degrees)

### `op 84` — SetActorMotionField62(actor, value, apply)
*handler:* `Script_VMOp_SetActorMotionField62`

Low-level motion tuning: write a value to an actor's motion-struct field +62 (only if the 3rd arg is non-zero). arg0 = actor (matched vs the scene's participant slots), arg1 = value, arg2 = apply flag. Engine-internal motion parameter — rarely needed directly.

Args:
  0. actor (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. value
  2. apply (0/1)

### `op 85` — SetActorMotionField56(actor, value)
*handler:* `Script_VMOp_SetActorMotionField56`

Low-level motion tuning: write a value to an actor's motion-struct field +56. arg0 = actor, arg1 = value. Engine-internal motion parameter.

Args:
  0. actor (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. value

### `op 86` — SetActorMotionField56(actor, value)
*handler:* `Script_VMOp_SetActorMotionField56`

Alias of op 85 (same handler): write actor motion field +56.

Args:
  0. actor (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. value

### `op 87` — SetActorMotionField60(actor, value)
*handler:* `Script_VMOp_SetActorMotionField60`

Low-level motion tuning: write a value to an actor's motion-struct field +60. arg0 = actor, arg1 = value. Engine-internal motion parameter.

Args:
  0. actor (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. value

### `op 88` — SetActorMotionField60(actor, value)
*handler:* `Script_VMOp_SetActorMotionField60`

Alias of op 87 (same handler): write actor motion field +60.

Args:
  0. actor (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. value

### `op 89` — SetActorMotionMask(actor, mask level n)
*handler:* `Script_VMOp_SetActorMotionMask`

Low-level motion tuning: writes a per-actor motion mask byte (actor motion struct +66). arg0 = actor (matched against the scene's two participant slots at ctx+96/+88, like op 81). arg1 is a LEVEL, not a raw mask: the byte written is 127>>arg1; arg1 = 0 (or out of 1..254) writes 0xFF (all bits). Engine-internal; exact field semantics uncertain.

Args:
  0. actor (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. mask level n (byte written = 127>>n; 0 = 0xFF all bits)

### `op 90` — SetActorMotionMask(actor, shift n)
*handler:* `Script_VMOp_SetActorMotionMask`

Alias of op 89 (same handler): set an actor's motion mask byte (motion struct +66) from a SHIFT COUNT, not a raw mask: writes 127>>n for n in 1..254, otherwise 0xFF. arg0 = actor (char id, resolved via a1+96/+88). Exact field semantics uncertain; unused in the shipped corpus.

Args:
  0. actor (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. shift n (writes 127>>n; 0/255 = 0xFF)

### `op 99` — TeleportActor(actor, x, y)
*handler:* `Script_VMOp_TeleportActorToCoords`

Instantly warp an actor to a tile. arg0 = actor (char id, 0 = player). arg1/arg2 = destination X/Y in tiles. The player is snapped to the ground; an NPC is streamed in if needed. No walk animation — use the Move* ops for a visible walk.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (tiles)
  2. y (tiles)

### `op 100` — TeleportActor(actor, x, y)
*handler:* `Script_VMOp_TeleportActorToCoords`

Alias of op 99 (same handler): instantly warp an actor to a tile.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (tiles)
  2. y (tiles)

### `op 101` — PlaceOrFaceActor(actor, x, y, facing)
*handler:* `ScriptAction_PlaceActorOrSetFacing`

Dual-purpose: with X and Y given, TELEPORT an actor to that tile (like op 99); with only an actor id + angle, just set its facing. arg0 = actor (char id, 0 = player). arg1/arg2 = X/Y tiles (place mode). arg3 = facing degrees (face-only mode). Player is re-snapped to the ground on placement.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (tiles)
  2. y (tiles)
  3. facing (degrees)

### `op 102` — PlaceOrFaceActor(actor, x, y, facing)
*handler:* `ScriptAction_PlaceActorOrSetFacing`

Alias of op 101 (same handler): teleport an actor to a tile, or set its facing.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (tiles)
  2. y (tiles)
  3. facing (degrees)

### `op 103` — TurnActorToAngle(actor, facing, pitch/mode)
*handler:* `ScriptVM_Op_SetEntityFacingAngleByteScaled`

Turn an actor toward a facing angle in DEGREES (×181 -> the u16 angle; 181×360 ≈ 65536), plus a pitch/mode byte — sets the TARGET facing and the turn-pending flag (the turn-lerp tick eases toward it; pair with QueryActorAnimBusy op 129 to wait for the turn). arg0 = actor (char id, 0 = player), arg1 = degrees, arg2 = pitch/mode. CORPUS-PROVEN degrees: the arg distribution is 0/45/90/135/180/225/270/315 — compass multiples of 45, never a 0-255 spread (the old 'byte angle' reading was wrong). Distinct from SetActorFacingAngle (77/78), which writes the facing instantly.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. facing (degrees)
  2. pitch/mode

### `op 104` — TurnActorToAngle(actor, facing, pitch/mode)
*handler:* `ScriptVM_Op_SetEntityFacingAngleByteScaled`

Alias of op 103 (same handler): turn an actor toward a target facing in degrees.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. facing (degrees)
  2. pitch/mode

### `op 106` — RotateActorInPlace(actor, delta, total steps)
*handler:* `ScriptVM_Op_RotateEntityFacingByStepsWithCounter`

Rotate an actor's facing by [delta] each frame for [total steps] frames — a spin/turn-in-place animation. BLOCKING until the step count is reached. arg0 = actor (char id, 0 = player), arg1 = delta (byte per step, ×181), arg2 = total steps. For 'spin around' moments (dizzy, transformation, celebration).

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. delta (byte/step)
  2. total steps

### `op 107` — TurnActorToFaceTarget(turner, look-at target, mode)
*handler:* `ScriptAction_TurnActorToFaceTarget`

Rotate one actor to look at another — the workhorse for 'actors face each other before dialogue'. arg0 = turner (0 = player, 1..47 = villager, >=48 = monster). arg1 = look-at target (same encoding). arg2 = mode: 0 = snap instantly, non-zero = ease/lerp toward it.

Args:
  0. turner (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. look-at target (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  2. mode (0=snap, else ease)

### `op 108` — TurnActorToFaceTarget(turner, look-at target, mode)
*handler:* `ScriptAction_TurnActorToFaceTarget`

Alias of op 107 (same handler): turn an actor to face another actor.

Args:
  0. turner (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. look-at target (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  2. mode (0=snap, else ease)

### `op 109` — TurnActorToFaceTarget(turner, look-at target, mode)
*handler:* `ScriptAction_TurnActorToFaceTarget`

Alias of op 107 (same handler): turn an actor to face another actor.

Args:
  0. turner (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. look-at target (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  2. mode (0=snap, else ease)

### `op 110` — FaceEventActor(char id, event key, anim id)
*handler:* `ScriptVMOp_MakeActorFaceCalendarEventActorAndSetAnim`

Make an actor turn to face a calendar-event-bound actor and start an animation. arg0 = char id (0=player, 1-47=NPC), arg1 = event key (calendar-event registry lookup), arg2 = animation id. NPC targets also re-align a paired sibling. The cutscene 'turn to look at X and react' op.

Args:
  0. char id (0=player, 1-47=NPC)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. event key
  2. anim id

### `op 111` — SetActorRotationRaw(actor, facing)
*handler:* `Script_VMOp_SetActorRotationRaw`

Instantly SNAP an actor's facing to an angle — no turn animation, no easing. arg0 = actor (char id, 0 = player). arg1 = facing degrees (converted ×181 to the u16 rotation, 65536 = 360°). Contrast op 77 SetActorFacingAngle, which turns via the motion/ease field.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. facing (degrees)

### `op 112` — SetActorRotationRaw(actor, facing)
*handler:* `Script_VMOp_SetActorRotationRaw`

Alias of op 111 (same handler): instantly snap an actor's facing angle.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. facing (degrees)

### `op 115` — MoveActorToTile_LockAI(actor, x, y, facing, speed, jump)
*handler:* `ScriptAction_MoveActorToAbsoluteTile_LockAiAndFace`

Walk an actor to an ABSOLUTE tile position, then LOCK its AI (npc+568 |= 0x10) so nothing interrupts the staged pose — used when actors slide into cutscene positions and must hold. Despite the old 'ByOffset' name, args 1/2 are absolute tiles, not offsets: the move command stores x<<12 / y<<12 RAW with no world-position anchor added, on both the NPC and player/scene paths (ops 115-118 are the absolute family; 123-128 are the relative one). args: actor (0 = player), x, y (tiles), facing degrees (x181 -> u16 rotation), speed, jump flag (non-zero = jump/run, 1.2x speed multiplier).

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (tiles, absolute)
  2. y (tiles, absolute)
  3. facing (degrees)
  4. speed
  5. jump (0/1)

### `op 116` — MoveActorToTile_LockAI(actor, x, y, facing, speed, jump)
*handler:* `ScriptAction_MoveActorToAbsoluteTile_LockAiAndFace`

Move an actor to an ABSOLUTE tile position + set facing, while locking its AI (npc+568 |= 0x10) so it cannot start new behaviors during the move. arg0 = actor (char id, 0 = player via the scene move queue), arg1/arg2 = target x/y in tiles (written raw as x<<12 / y<<12 - NOT offsets), arg3 = facing (degrees, *181 -> u16 rotation), arg4 = speed, arg5 = jump flag (0/1; jump selects the 4915.2 speed multiplier and sets npc+568 bit 0x800000). Ops 115-118 are the absolute-position family; 123-128 are the relative (ByOffset) family.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (tiles, absolute)
  2. y (tiles, absolute)
  3. facing (degrees)
  4. speed
  5. jump (0/1)

### `op 117` — MoveActorToTile_LockAINoFace(actor, x, y, speed, jump)
*handler:* `ScriptAction_MoveActorToAbsoluteTile_LockAiNoFace`

Move an actor to an ABSOLUTE tile (x,y) with NO facing change, then post-lock its AI (npc task +568 |= 0x10). 5 args: actor (char id, 0=player, must be <48), x tile, y tile, speed, jump flag. Position is written raw as x<<12 / y<<12 into the move command (absolute Q12 world coords) -- unlike op 125, which is genuinely relative. Speed = (arg*167773>>12) x (4915.2 if jump else 4096.0) >> 12, then Npc_StartMoveTowards. Bank 211 walks Volkanon to absolute (166,467) with it; scenes also feed it coordinates straight from position queries (reg0/reg1).

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (tiles, absolute)
  2. y (tiles, absolute)
  3. speed
  4. jump (0/1)

### `op 118` — MoveActorToTile_LockAINoFace(actor, x, y, speed, jump)
*handler:* `ScriptAction_MoveActorToAbsoluteTile_LockAiNoFace`

Alias of op 117 (same handler): move an actor to an ABSOLUTE tile (not a relative offset — the position args are written raw as x<<12/y<<12 into the move command, unlike the genuinely-relative op 125/126 variant which adds the actor's current position), with NO facing change, and lock the actor's AI afterward (npc.+64.+568 |= 0x10). arg0 = actor (char id, 0=player, <48), arg1/arg2 = X/Y tiles, arg3 = speed, arg4 = jump flag (0/1; jump applies a 1.2x speed factor). 5 args — there is no facing arg. IDB-corrected 2026-08-12 (bank 211 walks Volkanon to absolute (166,467)).

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (tiles)
  2. y (tiles)
  3. speed
  4. jump (0/1)

### `op 119` — NpcWalkToTile(npc, x, y, speed, run)
*handler:* `ScriptVMOp_NpcStartMoveWithSpeedAndMode`

Walk an NPC to an ABSOLUTE tile. arg0 = npc char id (<48). arg1/arg2 = target X/Y in tiles. arg3 = speed coefficient. arg4 = run flag (0 = walk, non-zero = run at 1.2x). Sets the NPC's 'moving' flag; unlike the Move*ByOffset ops this takes an absolute destination, not a delta.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (tiles)
  2. y (tiles)
  3. speed
  4. run (0/1)

### `op 120` — NpcWalkToTile(npc, x, y, speed, run)
*handler:* `ScriptVMOp_NpcStartMoveWithSpeedAndMode`

Alias of op 119 (same handler): walk an NPC to an absolute tile.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (tiles)
  2. y (tiles)
  3. speed
  4. run (0/1)

### `op 121` — NpcMoveAlt(npc, tile x, tile y, speed)
*handler:* `ScriptVMOp_NpcStartMoveAlternateKind2048`

Start an NPC moving toward tile (arg1, arg2) using the ALTERNATE movement mode (kind 2048 — dash/teleport-style, distinct from the normal kind-2 walk/run mover). arg0 = npc char id (<48), arg3 = speed (scaled x167773>>12, ~x41 Q12). Exactly 4 args — there is no 5th 'target param': the handler reads 4 and calls Npc_StartMoveTowards(npc, cmd) with no target id. Sets the NPC actor's 'moving' flag (control_flags |= 0x10).

Args:
  0. npc (char id <48)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. tile x
  2. tile y
  3. speed

### `op 122` — NpcMoveAlt(npc, tile x, tile y, speed, target param)
*handler:* `ScriptVMOp_NpcStartMoveAlternateKind2048`

Start an NPC moving toward a tile using the alternate movement mode (kind 2048), duplicate of op 121. arg0 = npc char id (<48), arg1/arg2 = tile x/y, arg3 = speed, arg4 = target parameter.

Args:
  0. npc (char id <48)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. tile x
  2. tile y
  3. speed
  4. target param

### `op 123` — MoveActorByOffset(actor, dx, dy, facing, speed, jump)
*handler:* `ScriptAction_MoveActorToRelativeOffsetAndFace`

Basic cutscene walk: move an actor by a RELATIVE tile offset and face the given angle (no AI changes). args: actor (0=player), dx, dy (tiles), facing degrees, speed, jump flag.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (tiles)
  2. dy (tiles)
  3. facing (degrees)
  4. speed
  5. jump (0/1)

### `op 124` — MoveActorByOffset(actor, dx, dy, facing, speed, jump)
*handler:* `ScriptAction_MoveActorToRelativeOffsetAndFace`

Alias of op 123 (same handler): relative move + face, no AI changes.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (tiles)
  2. dy (tiles)
  3. facing (degrees)
  4. speed
  5. jump (0/1)

### `op 125` — MoveActorByOffset_InterruptAI(actor, dx, dy, speed, jump)
*handler:* `ScriptAction_MoveActorToRelativeOffset_InterruptAi`

Force-reposition: PRE-CLEARS the actor's AI state, then moves it by a RELATIVE tile offset (no facing update). Use to yank an actor out of its routine before a scene. args: actor (0=player), dx, dy, (facing ignored), speed, jump flag.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (tiles)
  2. dy (tiles)
  3. speed
  4. jump (0/1)

### `op 126` — MoveActorByOffset_InterruptAI(actor, dx, dy, speed, jump)
*handler:* `ScriptAction_MoveActorToRelativeOffset_InterruptAi`

Alias of op 125 (same handler): interrupt-AI relative reposition.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (tiles)
  2. dy (tiles)
  3. speed
  4. jump (0/1)

### `op 127` — MoveActorByOffset_Continue(actor, dx, dy, speed, jump)
*handler:* `ScriptAction_MoveActorToRelativeOffset_NoFaceUpdate`

Continuation move: relative tile offset, no facing update, no AI changes — chains after another Move to extend a walk. Takes exactly 5 args: actor (char id, 0 = player), dx, dy (tiles, Q12-shifted), speed (x40.96 coefficient, x1.2 when jumping), jump flag. Unlike its and-face sibling there is NO facing argument (that variant takes 6). NPC path uses move-kind 2 (walk-keep-facing); player/scene path kind 4 (or 12 with ctx+72 bit 0).

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (tiles)
  2. dy (tiles)
  3. speed
  4. jump (0/1)

### `op 128` — MoveActorByOffset_Continue(actor, dx, dy, speed, jump)
*handler:* `ScriptAction_MoveActorToRelativeOffset_NoFaceUpdate`

Alias of op 127 (same handler): move an actor (NPC, or the scene/player actor when arg0=0) by a RELATIVE tile offset WITHOUT updating its facing (NPC move kind 2 = walk-keep-facing; scene kind 4/12). 5 args -- there is NO facing argument; that belongs to the with-facing sibling handler. Jump flag scales speed 1.2x and sets the NPC jump bit 0x800000.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (tiles)
  2. dy (tiles)
  3. speed
  4. jump (0/1)

### `op 133` — PlayActorAnim(actor, anim id, hold pose)
*handler:* `Script_VMOp_PlayActorActionAnim`

Play an action/animation on an actor. arg0 = actor (char id, 0 = player). arg1 = anim/action id -- an index into that actor's own animation archive, so the same id can be a different animation on different characters (no global id->name list); verify per character. arg2 non-zero marks it as a held scripted pose (and, for the player, begins a scripted-talk interaction). Pair with QueryActorAnimBusy (op 129) to wait for it.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. anim id (per-character archive)
  2. hold pose (0/1)

### `op 134` — PlayActorAnim(actor, anim/action id, hold pose)
*handler:* `Script_VMOp_PlayActorActionAnim`

Alias of op 133 (same handler): play an action animation on an actor.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. anim/action id
  2. hold pose (0/1)

### `op 141` — SetActorInvulnerable(actor, guard)
*handler:* `ScriptVMOp_SetActorInvulnerability`

Toggle an actor's scripted invulnerability guard. arg0 = actor (char id, 0 = player). arg1 has INVERTED polarity: arg1 == 0 turns the guard ON (sets the armor-guard bit); arg1 != 0 turns it OFF and clears the invuln overlay tint. Wrap scripted-combat cutscenes so staged actors can't be killed.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. guard (0 = invulnerable ON, non-zero = OFF)

### `op 142` — MoveSceneActorToTile(x, y, facing, speed, run)
*handler:* `Script_VMOp_MoveActorToCoords`

Move the scene-controlled actor (the player) to an ABSOLUTE tile, with facing. arg0/arg1 = X/Y tiles, arg2 = facing degrees, arg3 = speed, arg4 = run flag (0 = walk, non-zero = run). No char-id arg — always the scene's own actor.

Args:
  0. x (tiles)
  1. y (tiles)
  2. facing (degrees)
  3. speed
  4. run (0/1)

### `op 143` — MoveToCoords(tile x, tile y, speed, run)
*handler:* `ScriptVM_Op_QueueMoveCommandToCoords`

Queue a scripted 'move to tile coordinates' command for the scene's active mover. arg0/arg1 = target tile x/y (<<12 to Q12), arg2 = SPEED coefficient (not a distance: it gets the identical 167773/4096 = x40.96 Q12 conversion as NpcWalkToTile's speed arg, x1.2 when running; shipped scenes pass ~120-250), arg3 = 0 to walk / non-zero to run. Mode byte 8 added when ctx+72 bit 0 is set. Choreographs NPC/player movement during a cutscene.

Args:
  0. tile x
  1. tile y
  2. speed
  3. run (0=walk)

### `op 144` — MoveSceneActorStraight(x, y, speed, run)
*handler:* `Script_VMOp_MoveActorStraight`

Move the scene-controlled actor (the player) in a straight line to an ABSOLUTE tile, KEEPING its current facing (no turn). arg0/arg1 = X/Y tiles, arg2 = speed, arg3 = run flag (0 = walk, non-zero = run). Like op 142 but without a facing arg.

Args:
  0. x (tiles)
  1. y (tiles)
  2. speed
  3. run (0/1)

### `op 146` — EquipItemToPlayer(item id)
*handler:* `ScriptVMOp146_ScriptedEquipItemToPlayer`

Scripted equip: force-equips item [item id] into the player's equip slot 1 (via Player_OnEquipChanged), if it can be held. Pairs with op 147 to restore.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 147` — RestoreDefaultEquip()
*handler:* `ScriptVMOp147_RestoreDefaultEquipAndIdle`

Restore the player's default weapon and switch to idle -- undoes a scripted op-146 equip. No args.

### `op 153` — EventSpawnNpc(char id, event key, x, y, facing)
*handler:* `ScriptVMOp_CalendarEvent_SpawnOrUpdateNpcAtTilePos`

Spawn (or reposition) an event/cutscene NPC in the calendar-event registry. arg0 = the CHAR id (which character/model — record WORD1); arg1 = the EVENT KEY (a scene-local handle — record WORD0, what every later move/face/anim/query op addresses); arg2/arg3 = X/Y tiles; arg4 = facing degrees (×181 -> u16). If the key is already registered the op just updates position + facing; otherwise it claims a new slot (32 max, pending-placement bit set for the streamer). The deck opening spawns char 324 'Barrel' ×7, 331 'Captain', 31 Traveler this way (331 and 31 share field model NPC_TRAVELER_M2 — rf3NpcParam+272 is 321 for both; the model resolves as chr-TOC[+272 + 933], or mons-TOC[+272 + 12584] for monster-body chars, per Actor_RecomputeAllStats). ARG ORDER IDA-VERIFIED 2026-08-17 (the old 'scene id, char id' labels were swapped): ScriptVMOp_CalendarEvent_SpawnOrUpdateNpcAtTilePos matches records on arg1 and stores arg0 as the char word.

Args:
  0. char id (model)
     - *(enum: 364 values — use the in-editor picker or the id database)*
  1. event key (scene-local handle)
  2. x (tiles)
  3. y (tiles)
  4. facing (degrees)

### `op 154` — EventSpawnNpcVariant(char id, event key, x, y, facing, variant index)
*handler:* `ScriptVMOp_CalendarEvent_AddNpcWithVariantIndex`

Spawn an event/cutscene NPC that carries a pose/scene VARIANT index — always claims a NEW registry slot (unlike op 153 which updates in place). arg0 = char id (which character/model; ids 254-266 are filtered = no-op), arg1 = event key (the scene-local handle later ops address), arg2/arg3 = X/Y tiles, arg4 = facing degrees (x181 -> u16), arg5 = variant index (stored as index-1 in the entry's high dword; 0 -> 0). Entry WORD5 is hardwired to 0 by the engine — there is NO reserved 7th argument. Use for staged NPCs with an alternate pose/outfit variant.

Args:
  0. char id (model)
     - *(enum: 364 values — use the in-editor picker or the id database)*
  1. event key (scene-local handle)
  2. x (tiles)
  3. y (tiles)
  4. facing (degrees)
  5. variant index

### `op 155` — EventSpawnNpcFollower(char id, event key, x, y, facing, behaviour flag, follow speed)
*handler:* `ScriptVMOp_CalendarEvent_AddNpcWithFollowSpeedAndFlag`

Spawn an event NPC that trails at a follow speed — always claims a NEW registry slot. arg0 = char id (which character/model), arg1 = event key (the scene-local handle — SAME char/key order as ops 153/154, IDA-verified 2026-08-18: ScriptVMOp_CalendarEvent_AddNpcWithFollowSpeedAndFlag stores arg0 in the char word and arg1 in the key word), arg2/arg3 = X/Y tiles, arg4 = facing degrees, arg5 = behaviour flag byte (packed at record WORD5), arg6 = follow-speed multiplier (stored as value × 0.01). Use for a companion/tag-along that keeps pace during a scene.

Args:
  0. char id (model)
     - *(enum: 364 values — use the in-editor picker or the id database)*
  1. event key (scene-local handle)
  2. x (tiles)
  3. y (tiles)
  4. facing (degrees)
  5. behaviour flag
  6. follow speed

### `op 156` — UnregisterEventActor(char id, event key)
*handler:* `ScriptVMOp_KillCalendarEventByCharAndEventKey`

Remove a spawned event actor from the calendar-event registry, matching on BOTH char id and event key; frees its slot on the next sweep. arg0 = char id, arg1 = event key. Registry-level cleanup — no death animation and no dismiss reset (contrast KillEventActor op 180 / DismissEventActor op 181). Use when a scene ends.

Args:
  0. char id
     - *(enum: 364 values — use the in-editor picker or the id database)*
  1. event key

### `op 160` — EventNpcWalkToTile(event key, x, y, speed, run)
*handler:* `ScriptVMOp_CalendarEvent_BeginOrUpdateNpcMovement`

Walk/run a spawned event NPC to an ABSOLUTE tile (updates an in-progress move or starts a new one). arg0 = event key, arg1/arg2 = X/Y tiles, arg3 = speed coefficient (scaled by the NPC's walk/run base speed), arg4 = run flag (0 = walk, non-zero = run).

Args:
  0. event key
  1. x (tiles)
  2. y (tiles)
  3. speed
  4. run (0/1)

### `op 161` — EventNpcWalkToTilePriority(event key, x, y, speed, run)
*handler:* `ScriptVMOp_CalendarEvent_BeginScriptedNpcMovementAndSetCtrlFlag20000`

Walk a spawned event NPC to an ABSOLUTE tile AND lock it into high-priority scripted movement (control flag 0x20000) so it ignores AI and player interaction until the walk finishes — the cutscene-safe version of op 160. arg0 = event key (char id), arg1/arg2 = X/Y tiles, arg3 = speed, arg4 = run (0/1).

Args:
  0. event key
  1. x (tiles)
  2. y (tiles)
  3. speed
  4. run (0/1)

### `op 162` — SetMonsterFacing(monster, facing, mode)
*handler:* `ScriptVMOp_SetMonsterFacingDegrees`

Set a monster's facing to an absolute angle. arg0 = monster (char id), arg1 = facing degrees (×181 → u16), arg2 = mode (0 = snap, non-zero = ease). (The handler's name says 'EightDirIndex' but the value is plain degrees, like every other facing op.)

Args:
  0. monster (char id)
  1. facing (degrees)
  2. mode (0=snap, else ease)

### `op 163` — FaceEventActorTowardTarget(event key, look-at target, mode)
*handler:* `ScriptVM_Op_FaceCalendarEventTowardEntity`

Rotate a spawned event actor to look at another entity — the event-actor twin of TurnActorToFaceTarget (op 107). arg0 = event key (the actor that turns). arg1 = look-at target (0 = player, 1..47 = NPC, 48+ = event actor). arg2 = mode (0 = snap, non-zero = ease/lerp).

Args:
  0. event key
  1. look-at target (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  2. mode (0=snap, else ease)

### `op 167` — EventActorPlayAnim(event key, anim id, loop)
*handler:* `ScriptVMOp_StartAnimOnCalendarEventActorWithLoopFlag`

Play an animation on a spawned event actor. arg0 = event key, arg1 = anim id, arg2 = loop flag (non-zero = keep repeating). Pair with WaitForEventActorReady (op 169) to wait for a one-shot anim to finish.

Args:
  0. event key
  1. anim id
  2. loop (0/1)

### `op 168` — EventActorResyncAnimFrame(event key)
*handler:* `ScriptVMOp_SyncAnimFrameFromWidgetOnCalendarEventActor`

Force a spawned event actor to re-sync its animation frame from its widget after a state swap (fixes a one-frame visual pop when the anim state changes). arg0 = event key (char id). Low-level; pair with an anim change if you see a flicker.

Args:
  0. event key

### `op 170` — SetEventActorSpeedScale(event key, scale %)
*handler:* `ScriptVMOp_CalendarEvent_SetActorMoveScaleFactor`

Set a spawned event actor's move / animation speed multiplier. arg0 = event key (char id), arg1 = scale percent (÷100 = the multiplier: 100 = normal, 50 = half-speed slow-mo, 200 = double). For slow-motion or sped-up cutscene moments.

Args:
  0. event key
  1. scale % (100 = 1.0×)

### `op 171` — SetEventActorAlpha(event key, alpha %)
*handler:* `ScriptVMOp_SetCalendarEventActorAlphaPercent0To100OrHide`

Fade a spawned event actor: arg1 = alpha percent 0..100 (packed into the sprite's 5-bit alpha). arg1 == 0 HIDES the actor (sets its hide flag). arg0 = event key (char id). Used for ghost/translucent/fade-in-out cutscene effects.

Args:
  0. event key
  1. alpha % (0-100, 0=hide)

### `op 172` — EventActorStopAnim(event key, anim id)
*handler:* `ScriptVMOp_StopAnimAndClearOutfitOverride_OnCalendarEventActor`

Stop a spawned event actor's current animation and clear any outfit/costume override. arg0 = event key, arg1 = anim id to settle to. Event-actor twin of StopActorAnimAndClearOutfitOverride (ops 211/212).

Args:
  0. event key
  1. anim id

### `op 173` — MarkCalendarEventCancelled(event id)
*handler:* `Script_VMOp_MarkCalendarEventActorByEventId`

Find the calendar-event record with matching event_id (low-16 match in `g_calendarEventMng_20wPerRecord`) and OR 0x80 into its +564 field -- the 'cancelled/expired' flag. Returns 1 if the event id wasn't found in the current table.

Args:
  0. event id

### `op 174` — AddActorVerticalVelocity(actor, velocity)
*handler:* `ScriptVMOp_AddVerticalVelocityToActorClampedByJumpFlag`

Add a vertical velocity impulse to an actor — a scripted hop/jump or a downward burst. arg0 = target (0 = player, 1..48 = NPC, 48+ = event key). arg1 = velocity (positive = up). If the actor lacks the jump flag the result is clamped to non-upward (so it can only fall, not launch).

Args:
  0. actor (0=player, 1-48=NPC, 48+=event key)
  1. velocity (up if jump-enabled)

### `op 175` — SetEventActorStateWord(event key, value)
*handler:* `ScriptVMOp_SetCalendarEventActorWordField172`

Set a low-level per-actor state word (task field +172) on a spawned event actor. arg0 = event key, arg1 = value. Engine-internal state used by specific scripted setups; exact effect depends on the actor.

Args:
  0. event key
  1. value

### `op 176` — SetEventActorGreyscale(event key, grey level)
*handler:* `ScriptVMOp_SetCalendarEventActorSpriteTintGreyscale`

Tint a spawned event actor's sprite toward greyscale/monochrome (all three colour channels set equal). arg0 = event key, arg1 = grey level (scaled ×40.96 internally; lower = darker/dimmer). For flashbacks, petrification, dark-mood scenes.

Args:
  0. event key
  1. grey level (lower = darker)

### `op 177` — EventActorEnterIdle(event key, (unused — handler reads only 1 arg; shipped scripts pass 2))
*handler:* `ScriptVMOp_EnterActorIdleStateByCalendarEventKey`

Return a spawned event actor to its idle state, loading the default idle animation for its entity type. arg0 = event key. Use to reset an actor after a scripted anim/pose.

Args:
  0. event key
  1. (unused — handler reads only 1 arg; shipped scripts pass 2)

### `op 178` — SetEventActorTargetFacing(event key, facing)
*handler:* `ScriptVMOp_SetCalendarEventActorTargetFacingDegrees`

Set a spawned event actor's TARGET facing angle; the NPC tick interpolates its current facing toward it (a smooth turn). arg0 = event key, arg1 = facing degrees (×181 → u16). (The handler's name says 'DirIndex' but the math is plain degrees, matching every other facing op.)

Args:
  0. event key
  1. facing (degrees)

### `op 180` — KillEventActor(event key)
*handler:* `ScriptVMOp_CalendarEvent_KillActorWithDeathAnimAndKnockback`

Kill a spawned event actor with the full death sequence — knockout flags, a downward knockback impulse, the death-pose animation, and the fall-physics tick. arg0 = event key. For scripted deaths in cutscenes (e.g. a boss collapsing).

Args:
  0. event key

### `op 181` — DismissEventActor(event key)
*handler:* `ScriptVMOp_CalendarEvent_DismissActorAndDecrementCount`

Cleanly despawn a spawned event actor — NO death animation (contrast op 180 KillEventActor). arg0 = event key. Runs the canonical companion-dismiss reset and decrements the event-companion count; the player can't be dismissed.

Args:
  0. event key

### `op 183` — SetEntityLevelAndRespawnAI(entity, level)
*handler:* `ScriptVM_Op_SetEntityLevelAndSpawnMonster`

Set an actor's level and re-run its monster behaviour script (respawns its AI at the new level) with a level-up VFX. arg0 = entity (0 = player, 1..47 = NPC, 48+ = event key). arg1 = new level, or -1 to play the level-up VFX only without changing the level. Used for scripted power-ups / boss phase changes.

Args:
  0. entity (0=player, 1-47=NPC, 48+=event key)
  1. level (-1 = VFX only)

### `op 184` — SetActorScriptedStateBit(actor, flag)
*handler:* `ScriptVMOp_SetActorOrEventActorStatusEquipBit10000000`

Set or clear an actor's scripted-state bit 0x10000000 in its status/equip bitfield (inferred to hide the actor during a scene transition). arg0 = target (0 = player, 1..47 = NPC, 48+ = event key). arg1 = 0 clears the bit, non-zero sets it.

Args:
  0. actor (0=player, 1-47=NPC, 48+=event key)
  1. flag (0/1)

### `op 185` — PlayActorSplash(actor)
*handler:* `Script_VMOp_PlayActorSplashAnim`

Play a 'splash into water' animation on an actor — a squish/stretch bobble with the splash sound and 3 ripple effects. arg0 = actor (char id; 0 = player, 48+ = event actor). For scenes where a character jumps or falls into water.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 203` — SetCameraMapBounds(mode)
*handler:* `Script_VMOp_ApplyCameraMapBoundsAndZoom`

Recompute and re-apply the camera's per-map clamp bounds and zoom for the current map — NOT a player rotation (old name was wrong). The handler calls Camera_SetBoundsForMap(active input-context/map id, flag), passing 0xFFFF while input is suppressed; that callee sets the script/follow camera's centre clamp from the map's tile dims and re-applies the small-map zoom. arg: 0 = write the camera distance directly onto the player's camera rig (flag=1 path); non-zero = apply via Camera_SetDistanceAndZoomFactor (flag=0 path). Used after scripted camera moves/zooms to restore the normal map camera.

Args:
  0. mode (0=direct distance write, else standard zoom apply)

### `op 206` — CancelNpcPathOrEquipMainhand(npc, item id / cancel target)
*handler:* `Script_VMOp_CancelNpcPathOrPlayerEquipMainhand`

Dual-purpose. For an NPC (arg0 != 0): cancel its pending path / scripted action so it stays put for a scene (arg1 = a specific target to cancel, 0 = cancel all). For the player (arg0 = 0): equip the mainhand weapon = arg1 (0 = unequip), refreshing stats. Stages the player's loadout ('NPC hands you a sword') or freezes an NPC's movement.

Args:
  0. npc (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. item id / cancel target
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 207` — CancelNpcPathOrEquipMainhand(npc, item id / cancel target)
*handler:* `Script_VMOp_CancelNpcPathOrPlayerEquipMainhand`

Alias of op 206 (same handler): cancel an NPC's path, or equip the player's mainhand.

Args:
  0. npc (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. item id / cancel target
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 208` — HandOrDropItem(target npc, item id)
*handler:* `Script_Action_HandOrDropItem`

**Cutscene 'NPC hands you a gift' primitive.** Spawns an item visual and attaches it to either an NPC's hand or the player. **arg 0 = target**: 0 = give to player (either attach to hand OR drop on ground if player has status 0x4000 / secondary_mod in the 'item-blocked' range 1..0x453 — plays Sfx 0x100226D + fires Action_TriggerActor(0x13)). >0 = NPC slot index (looked up via g_gameGlobalsSlotTable), then `Item_SpawnVisualTask` + `Npc_AttachHeldItem`. **arg 1 = item_id** masked to 11 bits (0..2047). The item metadata is loaded from `g_itemDatabase` (recipe metadata copied via 5-byte stride).

Args:
  0. target npc (0=player)
  1. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 211` — StopActorAnim(actor, anim id)
*handler:* `ScriptVMOp_StopActorAnimAndClearOutfitOverride`

Stop an actor's current animation cleanly and clear any outfit/costume override (set by SetNpcOutfit). arg0 = actor (char id; 0 = player, -1 = the current interaction NPC, 1..47 = NPC). arg1 = anim id to settle to. Use to drop a special pose/outfit between scene beats.

Args:
  0. actor (char id, 0=player, -1=current)
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. anim id

### `op 212` — StopActorAnim(actor, anim id)
*handler:* `ScriptVMOp_StopActorAnimAndClearOutfitOverride`

Alias of op 211 (same handler): stop an actor's anim + clear its outfit override.

Args:
  0. actor (char id, 0=player, -1=current)
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. anim id

### `op 217` — ApplyFriendshipDelta(npc id, op kind, xp/value)
*handler:* `ScriptVM_Op_ApplyFriendshipDeltaToNpc`

Modify an NPC's friendship XP or absolute friendship. **3 args**: npc_id, op_kind, xp_or_value. Op-kind dispatch: **4 = ADD** (`Npc_AddFriendshipXpAndProcessLevelUp(npc, +xp)`); **5 = SUBTRACT** (`... , -xp)`); **6 = SET absolute** (`Npc_SetFriendshipPointsAbsoluteAndCheckMaxAchievement(npc, value)`). **Special: npc_id == 22 → dynamically resolves to the CHILD NPC id** via `GameFlags_ReadField(0, GF_REG_CHILD_ID, 5)`. That confirms slot 22 = Son is the runtime child-actor slot (paired with slot 23 = Daughter). Dev-menu debug branch uses this with (npc_id, 6, 99999999) = instant MAX friendship to unlock date/marriage flow.

Args:
  0. npc id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. op kind (4=add, 5=sub, 6=set)
  2. xp/value

### `op 221` — AdjustCurrentNpcFriendship(op kind, xp/value)
*handler:* `ScriptVMOp_NpcFriendshipAdjustByKindWithCurrentInteraction`

Adjust the friendship of the NPC the player is currently talking to (g_currentInteractionNpc). arg0 = op kind: 4 = add friendship XP, 5 = subtract XP, 6 = set the friendship points absolutely. arg1 = the XP delta (kinds 4/5) or the absolute value (kind 6). The go-to op for dialogue-choice reactions (+/- affection).

Args:
  0. op kind (4=add, 5=sub, 6=set)
  1. xp/value

### `op 222` — LockNpcPose(npc)
*handler:* `ScriptVMOp_NpcLockFacingAndSetActionFlags`

Freeze an NPC's facing/pose for a cutscene: snapshots its current facing and sets the pose-locked + action-pending flags so it holds still and won't turn on its own. arg0 = npc (char id). Released by ReleaseNpcLocks (op 230).

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 223` — SetNpcEngaged(npc, engaged)
*handler:* `ScriptVMOp_SetNpcEngagedFlagAndRefreshSchedule`

Pull an NPC out of (or back into) its daily schedule so it can take part in a scene. arg0 = npc (char id), arg1 = engaged: non-zero pauses the NPC's routine ('engaged'), 0 releases it back to its schedule. Refreshes its schedule state immediately.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. engaged (0=release, 1=engage)

### `op 224` — SetNpcEngaged(npc, engaged)
*handler:* `ScriptVMOp_SetNpcEngagedFlagAndRefreshSchedule`

Alias of op 223 (same handler): pause/resume an NPC's schedule for a scene.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. engaged (0=release, 1=engage)

### `op 225` — StreamInNpc(npc, mode)
*handler:* `ScriptVM_Op_StreamInNpcOrRefresh`

Bring an NPC into the scene (load its actor into rendering + activate it). arg0 = npc (char id, <48). arg1 = mode: non-zero force-streams the NPC (full load), 0 just re-applies its schedule state without streaming. Use before an NPC is needed on screen. To also place it, use StreamInNpcAtTile (op 246).

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. mode (0=refresh, 1=force load)

### `op 233` — HideNpc(npc, (unused — handler reads only 1 arg; corpus passes 2))
*handler:* `Script_VMOp_HideNpcAndSetFlag`

Hide an NPC — make it invisible/despawned and set its hidden state bit. arg0 = npc (char id). Removes the NPC from the scene; pair with a schedule refresh or SetNpcVisibleFlag to bring it back.

Args:
  0. npc (char id <48)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. (unused — handler reads only 1 arg; corpus passes 2)

### `op 234` — HideNpc(npc, (ignored))
*handler:* `Script_VMOp_HideNpcAndSetFlag`

Alias of op 233 (same handler): hide an NPC — calls Npc_SetHiddenFlag(id) and sets record+52 bit 0x20000000 (the hidden bit QueryNpcActorPresent/op 282 tests on the actor side). arg0 = npc (char id < 48). The corpus always passes a second arg (usually 1) that the RF4S handler never reads — vestigial.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. (ignored)

### `op 244` — NpcShowItem(npc)
*handler:* `Script_VMOp_BeginNpcItemShow`

Make an NPC play its 'show / hold up an item' gesture — the pose used when an NPC presents an item to the player (gift, quest reward, discovery). arg0 = npc (char id).

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 246` — StreamInNpcAtTile(npc, stream kind, x, y)
*handler:* `ScriptAction_StreamInNpcAtPosition`

The 'appear here' action: stream an NPC into the scene AND place it at a tile, with no walk-on. arg0 = npc (char id, <48), arg1 = stream kind (load filter), arg2/arg3 = X/Y tiles. Lighter than a full teleport — keeps the NPC's existing AI state.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. stream kind
  2. x (tiles)
  3. y (tiles)

### `op 248` — SetNpcVisibleFlag(npc, visible)
*handler:* `Script_VMOp_SetNpcVisibleFlag`

Toggle an NPC's visibility/interaction suppression bit (record +52 bit 0x800). arg0 = npc (char id), arg1 = visible: non-zero clears the suppress bit (NPC shown / interactive), 0 sets it (suppressed). Lighter than HideNpc — just flips the flag.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. visible (0=suppressed)

### `op 249` — SetNpcVisibleFlag(npc, visible)
*handler:* `Script_VMOp_SetNpcVisibleFlag`

Alias of op 248 (same handler): toggle an NPC's visibility-suppression flag.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. visible (0=suppressed)

### `op 250` — SyncActorAnimFrame(actor)
*handler:* `ScriptVMOp_SyncActorAnimFrameFromWidget`

Force an actor to re-sync its animation frame from its widget after a programmatic state change (fixes a one-frame pose pop). arg0 = actor (char id, 0 = player). The regular-actor twin of EventActorResyncAnimFrame (op 168).

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 251` — SyncActorAnimFrame(actor)
*handler:* `ScriptVMOp_SyncActorAnimFrameFromWidget`

Alias of op 250 (same handler): re-sync an actor's animation frame from its widget.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 252` — SetActorAnimSpeedScale(actor, speed %)
*handler:* `ScriptVMOp_SetActorAnimSpeedScale`

Set an actor's animation speed multiplier. arg0 = actor (char id, 0 = player), arg1 = speed percent (÷100: 100 = normal, 50 = slow-mo, 200 = fast). The regular-actor twin of SetEventActorSpeedScale (op 170).

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. speed % (100 = 1.0×)

### `op 253` — SetActorAnimSpeedScale(actor, speed %)
*handler:* `ScriptVMOp_SetActorAnimSpeedScale`

Alias of op 252 (same handler): set an actor's animation speed multiplier.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. speed % (100 = 1.0×)

### `op 254` — SetActorAnimFrameDirect(actor, frame number)
*handler:* `ScriptVMOp_SetActorAnimFrameDirect`

Snap an actor to a specific animation FRAME with no interpolation — a freeze-frame / posed shot. arg0 = actor (char id, 0 = player), arg1 = frame number. Combine with speed scale 0 (op 252) to hold a pose.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. frame number

### `op 256` — SetActorStatusConditions(target, op)
*handler:* `ScriptVMOp_SetActorStatusConditionsByMaskAndTargetSelect`

Apply or cure status conditions (poison / paralysis / sleep / seal / fatigue / cold) on an actor — for story afflictions and cures. arg0 = target (0 = player, 2 = companion 1, 3 = companion 2, else = the current interaction NPC). arg1 = op: 0 = clear all, 1 = afflict (poison+paralysis+sleep+seal+fatigue), 2 = cold only, 3 = clear the standard 4, 4 = clear cold+fatigue.

Args:
  0. target (0=player,2/3=companion,else NPC)
  1. op (0=clear,1=afflict,2=cold,3/4=cure)

### `op 261` — SetNpcParticipationFlag(npc, count, other npc …)
*handler:* `ScriptVMOp_SetNpcFriendshipBit80000000_RangeOrList`

Set a persistent NPC flag (record +52 bit 0x80000000) — a town-wide event / ledger participation marker. arg0 = npc (char id); 0 applies it to ALL 23 villagers. Otherwise arg1 = count and that many npc ids each get the flag.

Args:
  0. npc (char id, 0=all)
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. count
  2. other npc …

### `op 263` — RespawnNpcAtSchedulePos(npc)
*handler:* `ScriptVMOp_RespawnNpcAtScheduledPosition`

Make an NPC reappear at its schedule-computed position after it was moved off-screen — resets its motion state and fires the 'arrived' event. arg0 = npc (char id). Used for quest-delivery / scene transitions.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 264` — RespawnNpcAtSchedulePos(npc)
*handler:* `ScriptVMOp_RespawnNpcAtScheduledPosition`

Alias of op 263 (same handler): respawn an NPC at its scheduled position.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 266` — SetOrClearNpcSchedule(npc, persist, x, y, facing, apply, sched kind, sub kind, state)
*handler:* `Script_VMOp_NpcScheduleOrClear`

Place an NPC at a scripted (location, facing, state) for a scene, OR clear its schedule entirely. arg0 = npc (char id), arg1 = persist flag, arg2/arg3 = X/Y tiles, arg4 = facing (0-255), arg5 = apply switch (non-zero = place, 0 = clear back to normal schedule), arg6 = schedule kind, arg7 = sub-kind, arg8 = state byte. The heavy 'pin this NPC here' / 'release it' lever.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. persist
  2. x (tiles)
  3. y (tiles)
  4. facing (0-255)
  5. apply (0=clear)
  6. sched kind
  7. sub kind
  8. state

### `op 267` — SetOrClearNpcSchedule(npc, persist, x, y, facing, apply, sched kind, sub kind, state)
*handler:* `Script_VMOp_NpcScheduleOrClear`

Alias of op 266 (same handler): pin an NPC to a scripted spot/state, or clear it.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. persist
  2. x (tiles)
  3. y (tiles)
  4. facing (0-255)
  5. apply (0=clear)
  6. sched kind
  7. sub kind
  8. state

### `op 270` — RefreshNpcSchedule(npc, mode flag)
*handler:* `Script_VMOp_RefreshNpcSchedule`

Refresh an NPC's schedule for TODAY — re-evaluates where it should be for the current day/time and updates it there. arg0 = npc (char id), arg1 = a mode flag. Use after a scene displaces NPCs or after advancing time.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. mode flag

### `op 271` — RefreshNpcSchedule(npc, mode flag)
*handler:* `Script_VMOp_RefreshNpcSchedule`

Alias of op 270 (same handler): refresh an NPC's schedule for today.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. mode flag

### `op 275` — SetNpcPresenceState(npc index, mode)
*handler:* `ScriptVMOp275_SetNpcPresenceStateAndFlag768`

Set NPC [arg0]'s presence/companion state. arg1 = -1: clear the NPC's bit in the global presence mask (qword_...B300-family dword) and clear its record's companion bit (+52 bit 0x400000). Any other arg1 value sets the presence-mask bit; arg1 == 1 ADDITIONALLY marks the NPC as companion (+52: set bit 0x400000 and state bits 0x300), copies a record flag to byte +16, and writes 0 into packed game-flag 768. So: 1 = add as companion, -1 = remove, other values touch only the presence bit.

Args:
  0. npc index
  1. mode (1=add companion, -1=remove, other=presence bit only)

### `op 281` — ApplyNpcDateOutcome(npc, outcome state)
*handler:* `NpcSchedule_ApplyStateAndAwardFriendship`

Set an NPC's date/event OUTCOME state (3-bit, into its record). arg0 = npc (char id), arg1 = outcome state. State 4 = a successful date, which AWARDS friendship XP (enough to level up on the first date, otherwise +55). Use at the end of a dating/event scene.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. outcome state (4=success)

### `op 284` — MountActor(actor, mount event key)
*handler:* `ScriptVMOp_MountActorOrDismountByCalendarEventKey`

Mount an actor onto a rideable partner, or dismount. arg0 = actor (char id, 0 = player). arg1 = mount event key: 0 dismounts (drops to the ground), non-zero looks up the ride partner in the event registry by that key and starts the mount transition. Used for scripted riding (e.g. climbing onto a tamed monster).

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. mount event key (0=dismount)

### `op 286` — ShakeActor(actor, shake duration)
*handler:* `ScriptVM_Op_SetActorShakeFramesLow16`

Start an actor TREMBLE: arg1 (low 16 bits) is a shake-frames countdown written into the actor's state word's low half - each tick offsets the sprite through a jitter table until it runs out. The high word (a separate blink/flash timer) is preserved. The old 'set state bitfield low16' reading described the store, not the effect. arg0 = actor (char id, 0 = player; ids >= 0x30 resolve to nothing).

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. shake duration (frames)

### `op 287` — SetNpcOutfit(npc, outfit)
*handler:* `ScriptVMOp_SetNpcOutfitVariantAndPersistBitsInRecord`

Change an NPC's outfit/costume variant. arg0 = npc (char id), arg1 = variant: 0 = default, 1 = pajamas / bed outfit, 2 = festival / alternate, 3 = swimwear. Variants 0-2 PERSIST across scene changes (stored in the NPC record); variant 3 is single-scene only.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. outfit (0=default,1=pajamas,2=festival,3=swim)
     - `0` = Default
     - `1` = Pajamas
     - `2` = Festival
     - `3` = Swimsuit

### `op 289` — CarryBaby(actor)
*handler:* `ScriptVMOp_ActorCarryBaby_Dakko240`

Family-scene beat: the target actor picks up the newest child. Anim ordinal 240 resolves to 00_470_dakko.bfskl (the baby-CARRY pose, not a 'talking gesture'), and the gated callee spawns a task literally named 'baby' (MCModel 4*flag+1167) held by the actor. The gate reads GF_REG_CHILD_NUM then bit 287+(num-1) - the per-child variant flag choosing which baby model rides along. (Old 'TriggerActorTalkAnim + talk indicator' reading retired; decomp port 2026-09-01.)

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 290` — PostFamilyMilestones()
*handler:* `ScriptVMOp_SetWifeStatus2AndFireBirthdayMarriageEvents`

Write the packed marriage/family-status game-flag (packed id 4391 -> value 2) and run the family birthday/anniversary milestone check for today: compares the current date to the spouse's and children's birthdays and the wedding anniversary, setting the matching family-milestone game-flags. These go through GameFlags_WritePacked (packed game-flags), NOT Steam achievements. No args. Used in anniversary/birthday cutscenes.

### `op 291` — SpawnChildEventRecords(char id, room id)
*handler:* `ScriptVMOp_SpawnSpecialCalendarEventRecordsByChildNum`

Spawn calendar-event records for the player's CHILDREN (count comes from the child-number game flag). Each record places a child event NPC into the scene registry. arg0 = char id, arg1 = room id. Used in family / child cutscenes.

Args:
  0. char id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. room id
     - *(enum: 867 values — use the in-editor picker or the id database)*

### `op 292` — CommitMarriage()
*handler:* `ScriptVMOp_CommitMarriageToSpouseAndFireAchievements`

The climax of a marriage scene: permanently record the player's spouse (the NPC chosen earlier via game flags), set the married-NPC save flag + marriage save-config bit, fire the four marriage achievements, and stage the announcement text. No args — the spouse is read from GameFlags.

### `op 293` — ResetNpcDailySchedule(npc, state)
*handler:* `Script_VMOp_ResetNpcDailySchedule`

Put an NPC back on a daily-schedule state. arg0 = npc (char id), arg1 = state. Two distinct paths: arg1 != -1 -> Npc_ResetDailyScheduleAndAi(npc, state) (resets schedule AND AI) and returns WITHOUT touching the scene reservation; arg1 == -1 -> recompute today's state (record +17, or Schedule_GetNpcStateForToday when the computed bit +228&1 is clear), apply via Npc_ApplyScheduleState, and clear this scene's placed-actor/reservation bit (ctx+352 bit npc). Heavier than op 296; use at scene end to hand an NPC back to normal life.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. state (-1 = auto)

### `op 294` — ResetNpcDailySchedule(npc, state)
*handler:* `Script_VMOp_ResetNpcDailySchedule`

Alias of op 293 (same handler): reset an NPC's daily schedule + AI.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. state (-1 = auto)

### `op 295` — ResetNpcScheduleWithState(npc, state)
*handler:* `Script_VMOp_ResetNpcScheduleWithState`

Reset an NPC's schedule to an EXPLICIT state — re-parses its schedule plan and applies the calendar, then clears its scene reservation. arg0 = npc (char id), arg1 = state. Like op 293 but always uses the given state (no auto-compute).

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. state

### `op 296` — ApplyNpcScheduleState(npc, state)
*handler:* `Script_VMOp_ApplyNpcScheduleState`

Apply a schedule STATE to an NPC (its position/pose for that state) and clear its scene reservation. arg0 = npc (char id), arg1 = state, or -1 to auto-compute today's. Lighter than op 293 — does not reset the NPC's AI.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. state (-1 = auto)

### `op 297` — ApplyNpcScheduleState(npc, state)
*handler:* `Script_VMOp_ApplyNpcScheduleState`

Alias of op 296 (same handler): apply a schedule state to an NPC.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. state (-1 = auto)

### `op 298` — ApplyPendingNpcPlan(npc)
*handler:* `NpcSchedule_ApplyPendingNpcPlan`

Apply an NPC's PENDING schedule plan for today — re-parses and applies its calendar-computed schedule, clears its scene reservation, and refreshes the story-progress cache. arg0 = npc (char id). Like op 296 but also snapshots story progress.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 299` — ApplyPendingNpcPlan(npc)
*handler:* `NpcSchedule_ApplyPendingNpcPlan`

Alias of op 298 (same handler): apply an NPC's pending schedule plan for today.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 301` — RefreshNpcScheduleForToday(npc)
*handler:* `Script_VMOp_RefreshNpcScheduleForToday`

Refresh an NPC's daily schedule for TODAY — computes its current-day state and re-parses/applies its schedule plan. arg0 = npc (char id). Like op 298 but does not clear the scene reservation or snapshot story progress.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 302` — SetNpcActionDelay(npc, base wait)
*handler:* `Script_VMOp_SetNpcActionDelayWithJitter`

Make an NPC wait before its next scheduled AI action: writes a jittered countdown into the NPC's schedule-wait timer (record +212). Value = uniform [0.75*arg1, 1.125*arg1) via the shared MMIX RNG; if 3/4*arg1 <= 0 nothing is written. NpcSchedule_Tick decrements it once per tick and performs the next schedule action when it hits 0; starting a move/interaction clears it. Does NOT touch friendship — the old name came from a mislabeled IDB function and was settled as wrong (2026-08 analysis; implemented in the decomp as TitleNpcPlacement.timer). arg0 = npc (char id), arg1 = base wait (ticks).

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. base wait (ticks, jittered 0.75x-1.125x)

### `op 303` — SetNpcActionDelay(npc, delay)
*handler:* `Script_VMOp_SetNpcActionDelayWithJitter`

Alias of op 302 (same handler). Despite the old name it does NOT touch friendship: writes a jittered WAIT into the NPC's schedule countdown (npc record +212, decremented once per NpcSchedule_Tick; on expiry the NPC performs its next scheduled action). Written value is uniform in [0.75 x arg1, 1.125 x arg1); arg1 <= 0 writes nothing. Starting a move or interaction clears the timer. arg0 = npc (char id, < 48), arg1 = requested delay (ticks).

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. delay (ticks, jittered 0.75-1.125x)

### `op 313` — RestorePlayerRP()
*handler:* `Script_VMOp_RestorePlayerRPFull`

Fully restore the player's RP (Rune Points) to max. No args.

### `op 315` — QueueNpcGreetingEvent(x, y)
*handler:* `Friendship_QueueNpcWaveEvent`

Find the NPC standing near tile (x, y) — within ~16 tiles and in the active input context — and queue a greeting / wave interaction event with them. arg0/arg1 = X/Y tiles. Sets that NPC as the interaction subject.

Args:
  0. x (tiles)
  1. y (tiles)

### `op 317` — SetNpcVisibility(npc, show)
*handler:* `Script_VMOp_SetNpcVisibility`

Show or hide an NPC's LIVE actor immediately by toggling its render-hide bit. arg0 = npc (char id), arg1 = show (non-zero = show, 0 = hide). More direct than HideNpc (op 233) and distinct from SetNpcVisibleFlag (op 248, which flips a record bit).

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. show (0=hide, 1=show)

### `op 327` — SetActorOutfitVariant(actor, pose/variant)
*handler:* `Script_VMOp_SetActorOutfitVariant`

Alias of op 328 (same handler Script_VMOp_SetActorOutfitVariant). arg0 = actor (char id, 0 = player; 48-255 no-op). arg1 = pose/variant: 255 = END — detach the current scripted pose and return the actor to AI idle; 3 = apply the alt-outfit asset set (Actor_ApplyNpcOutfitVariant 3); any other value only detaches a previous pose first. Player path also refreshes player render state. No transform-animation task is involved — the old 'PlayActorTransform' name overstated it. Unused in the shipped corpus.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. pose/variant (255=end pose, 3=alt outfit)

### `op 328` — PlayActorTransform(actor, pose/variant)
*handler:* `Script_VMOp_SetActorOutfitVariant`

Play an animated outfit / pose CHANGE on an actor (the character-change transform task). arg0 = actor (char id, 0 = player). arg1 = pose: 255 = end the pose and return to idle, 3 = swap to the alternate-outfit asset set; other values begin a pose (detaching any prior one). For 'character transforms / changes clothes' moments. Contrast op 287 (SetNpcOutfit — persistent pajamas/festival/swim variants).

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. pose/variant (255=end, 3=alt)

### `op 330` — SetOutfitDirect(actor, outfit)
*handler:* `Script_VMOp_SetActorOutfitDirect`

Set an actor's outfit index directly.

Args:
  0. actor
  1. outfit
     - `0` = Default
     - `1` = Pajamas
     - `2` = Festival
     - `3` = Swimsuit

### `op 331` — SetActorOutfitDirect(actor, outfit variant)
*handler:* `Script_VMOp_SetActorOutfitDirect`

Directly set an actor's outfit/costume variant with NO transition animation (an instant swap). arg0 = actor (char id, 0 = player), arg1 = outfit variant id. The lightweight version of PlayActorTransform (op 328).

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. outfit variant
     - `0` = Default
     - `1` = Pajamas
     - `2` = Festival
     - `3` = Swimsuit

### `op 393` — FreezePlayer(release)
*handler:* `Script_VMOp_SetPlayerScriptedFreeze`

Lock or release player input (scripted freeze). INVERTED sense: arg0 == 0 FREEZES the player (sets control_flags bit 4, scene-node word bit 1, and the input-disabled bit 0x20000000 on actor_inner); arg0 != 0 releases all three. Shipped scenes open with FreezePlayer(0) and close with FreezePlayer(1).

Args:
  0. release (0=freeze, nonzero=unfreeze)

### `op 394` — WarpPlayer(tile x, tile y)
*handler:* `Script_VMOp_TeleportPlayerToTile`

Teleport the player to a map tile.

Args:
  0. tile x
  1. tile y

### `op 395` — SetPlayerPose(facing deg, pose)
*handler:* `Script_VMOp_SetPlayerFacingAndPose`

Set the player's facing angle and pose.

Args:
  0. facing deg
  1. pose

### `op 396` — SetPlayerFacingAndPose(facing, pose)
*handler:* `Script_VMOp_SetPlayerFacingAndPose`

Set the player's facing angle AND pose in one op (instant snap). arg0 = facing degrees (×181 → u16), arg1 = pose byte. Marks the renderer dirty so the change shows immediately. Handy for a posed player shot.

Args:
  0. facing (degrees)
  1. pose

### `op 397` — SetPartyOutfit(variant)
*handler:* `Script_VMOp_SetPartyOutfitVariantAndSyncFriendship`

Set the party outfit variant and sync friendship.

Args:
  0. variant

### `op 400` — SetPlayerLestOrFrey(gender)
*handler:* `Script_VMOp_SetPlayerCharacterLestOrFrey`

Switch the player character between **Lest (male / arg=1)** and **Frey (female / arg=0)**. Calls `Player_SetCharacterVariantLestOrFrey`, refreshes equipped sprites + scene state, zeros the save-snapshot scratch, and reloads the greeting string from archive 16369 (NPC name archive): arg=1 -> entry 0 (title greeting), arg=0 -> entry 599 (default 'Frey' name). **Formerly named `RefreshPlayerAndApplyDefaultName` -- the technical name hides that this is the actual character-swap op**. Dev menu label: 'Boy' / 'Girl'.

Args:
  0. gender (1=Lest/Boy, 0=Frey/Girl)

### `op 427` — MaxWeaponSkills()
*handler:* `Script_VMOp_SetFirst6WeaponSkillsToLevel30`

Set the player's six weapon skills (Sword, Long Sword, Spear, Axe/Hammer, Dual Blade, Glove) all to level 30 and refresh the weapon-skill rank-unlock bits — a scripted/dev mastery grant (e.g. a New Game+ starter). Takes no arguments.

### `op 472` — SetChildGrowthValue(child, value)
*handler:* `Script_VMOp_SetChildFriendshipByteAt2`

Write a child NPC's growth/level value (record byte +2, distinct from the friendship-level byte; capped below 65). arg0 = child char id (24-47), arg1 = value (0-64).

Args:
  0. child (char id 24-47)
  1. value (0-64)

### `op 474` — SetEventLeadNpc(npc, clear flag)
*handler:* `Script_VMOp_SetCurrentEventLeadNpcAndClearFlag2`

Declare the lead / central NPC of the current scripted event (who is speaking or the scene focuses on) — writes it to the event participant list. arg0 = npc (char id), arg1 non-zero also clears a status flag on that slot. Used at scene start.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. clear flag (0/1)

### `op 475` — SetNpcStateByte(npc, value)
*handler:* `Script_VMOp_SetNpcFriendshipByteAt58`

Write a per-NPC state byte (offset +58 in the NPC record array) for npc [arg0] (< 48) — a relationship/state-machine flag byte. arg1 = value. Invalid npc ids trap as a script error.

Args:
  0. npc (char id, <48)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. value

### `op 476` — SpawnNpc(npc id)
*handler:* `Script_VMOp_StreamInNpcAtPlayerPos`

Stream an NPC in at the player's position.

Args:
  0. npc id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 477` — StreamInNpcAtPlayer(npc)
*handler:* `Script_VMOp_StreamInNpcAtPlayerPos`

Bring an NPC into the scene at the player's position (streaming it in if needed) and add/sync it as a companion, with marriage-trigger handling. arg0 = npc (char id). Use to make an NPC join the player for a scene.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 478` — SpawnNpcScripted(npc id, scripted)
*handler:* `Script_VMOp_StreamInNpcAtPlayerPos_WithScriptedFlag`

Stream an NPC in at the player. arg1 sets/clears the npc record's bit 30 (0x40000000) 'scripted-presence / cutscene-owned' marker.

Args:
  0. npc id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. scripted (0/1)

### `op 479` — StreamNpcAtPlayer(npc, scripted)
*handler:* `Script_VMOp_StreamInNpcAtPlayerPos_WithScriptedFlag`

Stream an NPC into the scene at the player's position and sync it as a companion (handles the marriage trigger). arg0 = npc char id, arg1 = scripted flag: non-zero sets the NPC's 'owned by cutscene / scripted-presence' record bit, zero clears it. Used to make an NPC appear beside the player for a scene.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. scripted (0/1)

### `op 480` — WakeSceneNpcChild()
*handler:* `Script_VMOp_WakeSceneChildOfCurrentInteractionNpc`

Wake the scene child of the current interaction NPC.

### `op 492` — FaceNpcToPlayer(mode)
*handler:* `Script_VMOp_SetSceneNpcFacingModeAndStandInFrontOfPlayer`

Make a scene NPC stand in front of / face the player.

Args:
  0. mode

### `op 553` — SetNpcScriptedPresence(flag, npc id …)
*handler:* `Script_VMOp_SetNpcRecordBit23ByList`

Set or clear the 'presence-locked / scripted' bit (record +52 bit 0x800000) on one or more NPCs. arg0 = flag (0 = clear, 1 = set), followed by npc ids; with no ids it applies to all 23 villagers. Locks NPCs into the scene's control.

Args:
  0. flag (0=clear, 1=set)
  1. npc id …

### `op 554` — SetNpcScriptedPresence(flag, npc id …)
*handler:* `Script_VMOp_SetNpcRecordBit23ByList`

Alias of op 553 (same handler): set/clear the scripted-presence bit on NPCs.

Args:
  0. flag (0=clear, 1=set)
  1. npc id …

### `op 562` — RefreshSceneNpcs()
*handler:* `Script_VMOp_RefreshAllNpcsOnSceneLoadAndUnblockVM`

Snap every NPC to their current scheduled position and unblock the cutscene VM. Call after a scene load or map change so NPCs appear where their daily schedule says they should be right now. Takes no arguments.

### `op 589` — PlayerPickUpObject()
*handler:* `Script_VMOp_PlayerPickupSceneObject1Tile`

Make the player pick up / carry the scene's target object: snaps the player to the ground if airborne, places the object one tile away, and starts the carry. The 'come pick this up' cutscene op. Takes no arguments.

### `op 594` — CommitGrabbedObject()
*handler:* `Script_VMOp_PlayerCommitGrabbedItemToBagIfThrowable`

If the player is holding a grabbed object that is flagged throwable, commit it into the bag. A pickup-convenience op. Takes no arguments.

### `op 620` — UnlockMonsterDex(monster id)
*handler:* `Script_VMOp_UnlockMonsterDexEntryAchievement`

Unlock a monster's bestiary / dex entry — sets the dex bit and fires the first-encounter achievement. arg0 = monster id. Fired the first time a monster is encountered. Setter counterpart of QueryMonsterDexBit (op 695).

Args:
  0. monster id

### `op 660` — SetActorStatusFlag(char id, on)
*handler:* `Script_VMOp_SetActorStatusFlagBit0x20Or0x10000ByCharId`

Set/clear the target actor's stats.status_flags bit 0x20 by char id (for char id 239 it toggles bit 0x10000 instead). No stat recompute. arg0 = char id (0=player, 1..47=NPC, >=48=event actor via calendar-event mng), arg1 = 0 to clear / non-zero to set. NOTE: distinct from op 661 SetActorStatFlagRecompute (bit 0x20000 + stat recompute + HP clamp).

Args:
  0. char id (0=player, <48=NPC, >=48=event)
  1. on (0=clear, else set)

### `op 661` — SetActorStatFlagRecompute(char id, on)
*handler:* `Script_VMOp_SetActorStatusFlagBit0x20000RecomputeByCharId`

Toggle stats.status_flags bit 0x20000 on the target AND recompute its stats; clearing it also clamps current HP down to the new max HP. arg0 = char id (0=player, <48=NPC, >=48=event actor), arg1 = 0 to clear / non-zero to set. A scripted stat-affecting status toggle. NOTE: distinct from op 660 SetActorStatusFlag (a different handler that toggles the plain status bit 0x20, or 0x10000 for char 239, with NO stat recompute).

Args:
  0. char id (0=player, <48=NPC, >=48=event)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. on (0=clear, else set)

### `op 662` — SetActorArmorBreak(char id, value)
*handler:* `Script_VMOp_SetActorArmorBreakBit0x4000ByCharId`

Toggle an actor's armor-break bit by char id.

Args:
  0. char id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. value

### `op 663` — DisableActorHpRegen(char id)
*handler:* `Script_VMOp_SetActorHpRegenRateZeroByCharId`

Set the target actor's HP-regen rate to 0, stopping passive HP recovery. arg0 = char id (0=player, <48=NPC, >=48=event actor). Used so a scripted actor can't heal itself mid-battle.

Args:
  0. char id (0=player, <48=NPC, >=48=event)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 664` — LockActorMaxSp(char id)
*handler:* `Script_VMOp_ForceActorMaxSpAndLockByCharId`

Force the target actor to maximum SP/RP (regen set to -1) and set a locked state, also releasing any companion-AI claim on it. arg0 = char id (0=player, <48=NPC, >=48=event actor). Freezes an actor in a controlled state for a cutscene.

Args:
  0. char id (0=player, <48=NPC, >=48=event)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 665` — SetActorFacing(char id, deg)
*handler:* `Script_VMOp_SetActorPadA0FacingAngleByCharId`

Set an actor's facing angle by char id.

Args:
  0. char id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. deg

### `op 680` — ApplyAttackToPlayer(attack id)
*handler:* `Script_VMOp_CombatApplyAttackEntryToPlayer`

Apply a combat attack entry (from the attack database) to the player — scripted damage / knockback / status, as if the player were hit by that attack. arg0 = attack id. For cutscene moments where the player takes a hit (boss intro, ambush).

Args:
  0. attack id

### `op 692` — OnFirstMarriageAccepted()
*handler:* `Script_VMOp_OnFirstMarriageAcceptanceUnlockAndReset`

Finalize a first marriage acceptance: unlock the marriage achievement, clear the candidate NPC's proposal state, and trigger the marriage-acceptance follow-up sequence (CondScript entry 80). No args — fired the moment a proposal is accepted.

### `op 738` — NpcAction_Kind0_LieDownToSleep()
*handler:* `NpcAction_Kind0_LieDownToSleep`

kind 0 Lie Down To Sleep (schedule kind 0). An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 739` — Npc_TickWanderBehavior()
*handler:* `Npc_TickWanderBehavior`

Npc Tick Wander Behavior. An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 740` — NpcAction_PlayKindIdleAnim()
*handler:* `NpcAction_PlayKindIdleAnim`

Play kind Idle Anim. An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 741` — NpcAction_PlayKindIdleAnim()
*handler:* `NpcAction_PlayKindIdleAnim`

Play kind Idle Anim. An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 742` — NpcAction_PlayKindIdleAnim()
*handler:* `NpcAction_PlayKindIdleAnim`

Play kind Idle Anim. An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 743` — NpcAction_PlayKindIdleAnim()
*handler:* `NpcAction_PlayKindIdleAnim`

Play kind Idle Anim. An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 744` — NpcAction_PlayKindIdleAnim()
*handler:* `NpcAction_PlayKindIdleAnim`

Play kind Idle Anim. An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 745` — NpcAction_PlayKindIdleAnim()
*handler:* `NpcAction_PlayKindIdleAnim`

Play kind Idle Anim. An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 746` — NpcAction_PlayKindIdleAnim()
*handler:* `NpcAction_PlayKindIdleAnim`

Play kind Idle Anim. An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 747` — NpcAction_Kind9_LookAroundIdle()
*handler:* `NpcAction_Kind9_LookAroundIdle`

kind 9 Look Around Idle (schedule kind 9). An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 748` — NpcAction_Kind10_GreetThenBow()
*handler:* `NpcAction_Kind10_GreetThenBow`

kind 10 Greet Then Bow (schedule kind 10). An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 749` — NpcAction_PlayKindIdleAnim()
*handler:* `NpcAction_PlayKindIdleAnim`

Play kind Idle Anim. An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 750` — NpcAction_PlayKindIdleAnim()
*handler:* `NpcAction_PlayKindIdleAnim`

Play kind Idle Anim. An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 751` — NpcAction_Kind13_GiftAndTeleportOut()
*handler:* `NpcAction_Kind13_GiftAndTeleportOut`

kind 13 Gift And Teleport Out (schedule kind 13). An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 752` — NpcAction_Kind14_DelayedIdleAnim()
*handler:* `NpcAction_Kind14_DelayedIdleAnim`

kind 14 Delayed Idle Anim (schedule kind 14). An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 753` — NpcAction_Kind15_SleepOrExitHome()
*handler:* `NpcAction_Kind15_SleepOrExitHome`

kind 15 Sleep Or Exit Home (schedule kind 15). An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 754` — NpcAction_PlayKindIdleAnim()
*handler:* `NpcAction_PlayKindIdleAnim`

Play kind Idle Anim. An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 755` — NpcAction_Kind17_EatFood()
*handler:* `NpcAction_Kind17_EatFood`

kind 17 Eat Food (schedule kind 17). An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 756` — NpcAction_Kind18_RandomTimerIdleAnim()
*handler:* `NpcAction_Kind18_RandomTimerIdleAnim`

kind 18 Random Timer Idle Anim (schedule kind 18). An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 757` — NpcAction_Kind19_ChatByFriendshipLevel()
*handler:* `NpcAction_Kind19_ChatByFriendshipLevel`

kind 19 Chat By Friendship Level (schedule kind 19). An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 758` — NpcAction_Kind20_EquipTool506()
*handler:* `NpcAction_Kind20_EquipTool506`

kind 20 Equip Tool 506 (schedule kind 20). An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 759` — NpcAction_PlayKindIdleAnim()
*handler:* `NpcAction_PlayKindIdleAnim`

Play kind Idle Anim. An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 760` — NpcAction_Kind22_EquipTool483()
*handler:* `NpcAction_Kind22_EquipTool483`

kind 22 Equip Tool 483 (schedule kind 22). An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 761` — NpcAction_Kind23_EquipHeldTool()
*handler:* `NpcAction_Kind23_EquipHeldTool`

kind 23 Equip Held Tool (schedule kind 23). An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

### `op 762` — NpcAction_Kind24_RandomGreetGesture()
*handler:* `NpcAction_Kind24_RandomGreetGesture`

kind 24 Random Greet Gesture (schedule kind 24). An NPC idle/schedule BEHAVIOR handler dispatched by the NPC AI tick — it is NOT a cutscene-script opcode (it takes an NPC behaviour-state block, not the script VM context) and won't appear in rf3.mc. Listed for completeness because it shares the tail of the scene action-handler table.

## Companions & party

### `op 311` — HealPartyFull()
*handler:* `Script_VMOp_HealPartyHPFull`

Fully heal the party — restores the player and both active companions to max HP. No args. Post-battle / rescue recovery scenes.

### `op 312` — HealPartyByShift(shift)
*handler:* `Script_VMOp_HealPartyHPByShift`

Heal the party (player + both companions) by a fraction of each one's max HP. arg0 = shift: 0 = full heal, 1 = half max HP, 2 = quarter, and so on (heal = hp_max >> shift). Partial recovery.

Args:
  0. shift (0=full, 1=½, 2=¼ …)

### `op 314` — CurePartyStatus()
*handler:* `Script_VMOp_ClearPartyStatusConditions`

Cure the standard status conditions on the whole party (player + both companions): poison, paralysis, sleep, seal, and cold. Fatigue and faint are NOT cleared. No args. For medicine / recovery scenes.

### `op 483` — SyncCompanions()
*handler:* `Script_VMOp_SyncBothCompanionsToScene`

Sync both companions into the scene.

### `op 484` — SyncBothCompanions()
*handler:* `Script_VMOp_SyncBothCompanionsToScene_SetSyncFlag1`

Bring both companions into the current scene with a forced full sync (sets sync bit 0). Takes no arguments. Use SyncBothCompanionsWithFlags (op 485) when you need finer control over the sync mode.

### `op 485` — SyncBothCompanionsWithFlags(flag1, flag2)
*handler:* `Script_VMOp_SyncBothCompanionsToScene_WithFlags`

Bring both companions into the current scene, configuring the sync mode: arg0 non-zero sets sync bit 1, arg1 non-zero sets sync bit 0 (force full sync). The general-purpose companion scene-sync op.

Args:
  0. flag1 (sync bit 1)
  1. flag2 (force full sync)

### `op 486` — SyncCompanionByCharId(char id, flag1, flag2)
*handler:* `Script_VMOp_SyncCompanionMatchingCharIdWithFlags`

Bring the ONE companion whose char id matches [arg0] into the scene, with the same two sync flags as op 485. arg0 = 0 matches the scene's current actor, arg0 = 22 looks up the married partner via game flag, otherwise it is a direct char-id match.

Args:
  0. char id (0=scene actor, 22=spouse)
  1. flag1 (sync bit 1)
  2. flag2 (force full sync)

### `op 488` — SetCompanionScriptedPresence(mode)
*handler:* `Script_VMOp_SetBothCompanionScriptedPresenceAndMaybeReset`

Lock or release BOTH companions' AI for cutscene control. arg0 = 0 puts them in scripted-presence mode (the scene drives them); non-zero releases them back to normal AI (and resets their behaviour). The companion counterpart of SetNpcEngaged (op 223).

Args:
  0. mode (0=lock for scene, else release)

### `op 489` — SetCompanionMetFlag(clear)
*handler:* `Script_VMOp_SetCompanionNpcRecordScriptedFlagAndQueueEncounter`

Toggle both companions' 'already met / scripted-present' record flag: arg0 == 0 sets it (mark as met), non-zero clears it — and when cleared outside months 6-18, queues each companion's first-meeting encounter event. Used at a cutscene's end to control whether first-time-meeting dialogue fires.

Args:
  0. clear (0=mark met, else clear + maybe queue meeting)

### `op 494` — SetCompanionInvulnerable(slot, clear)
*handler:* `Script_VMOp_SetCompanionArmorBreakBit4`

Set or clear a companion's invulnerability guard (control_flags bit 4) — the companion counterpart of SetActorInvulnerable (op 141). arg0 = companion slot (0 or 1; >=2 = both). arg1 = 0 sets the guard (invulnerable), non-zero clears it. Wrap scripted combat so companions can't be downed.

Args:
  0. slot (0/1, >=2=both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. clear (0=guard on, else off)

### `op 495` — WarpCompanion(slot, tile x, tile y)
*handler:* `Script_VMOp_TeleportCompanionsToTile`

Teleport companion(s) to a tile.

Args:
  0. slot
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. tile x
  2. tile y

### `op 496` — MoveCompanion(slot, tile x, tile y, facing deg, speed, run)
*handler:* `Script_VMOp_CompanionMoveTowardsTileFineGrained`

Move a companion toward a tile (choreographed, with facing).

Args:
  0. slot
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. tile x
  2. tile y
  3. facing deg
  4. speed
  5. run

### `op 497` — MoveCompanionNF(slot, tile x, tile y, speed, run)
*handler:* `Script_VMOp_CompanionMoveTowardsTileNoFacing`

Move a companion toward a tile (no facing change).

Args:
  0. slot
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. tile x
  2. tile y
  3. speed
  4. run

### `op 498` — MoveCompanionRel(slot, dx, dy, facing deg, speed, run)
*handler:* `Script_VMOp_CompanionMoveRelativeFromCurrent`

Move a companion relative to its current tile (with facing).

Args:
  0. slot
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. dx
  2. dy
  3. facing deg
  4. speed
  5. run

### `op 499` — MoveCompanionRelNF(slot, dx, dy, speed, run)
*handler:* `Script_VMOp_CompanionMoveRelativeFromCurrentNoFacing`

Move a companion (or both, slot=2) by a RELATIVE tile offset WITHOUT changing its facing — the no-facing variant of MoveCompanionRel (op 498). arg0 = slot (0/1, 2=both), arg1/arg2 = dx/dy tiles, arg3 = speed, arg4 = run flag (0=walk).

Args:
  0. slot (0/1, 2=both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. dx (tiles)
  2. dy (tiles)
  3. speed
  4. run (0/1)

### `op 500` — SetCompanionPose(slot, facing deg, pose)
*handler:* `Script_VMOp_SetCompanionFacingAngleAndPose`

Set a companion's facing angle and pose.

Args:
  0. slot
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. facing deg
  2. pose

### `op 501` — CompanionFaceTarget(slot, target, pose)
*handler:* `Script_VMOp_SetCompanionFaceTargetAndPose`

Turn a companion to face a target actor, set pose.

Args:
  0. slot
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. target
  2. pose

### `op 503` — StopCompanionAnim(slot, clear mode/flag)
*handler:* `Script_VMOp_StopCompanionAnimAndClearOutfitOverride`

Stop the companion's current animation and (per the flag) clear its per-NPC outfit override; also clears armor-break bit 4 and control-flags 0x10C. Skips companions that are stunned/frozen (actor+568 bit 4). arg0 = companion slot (0=companion 1, 1=companion 2, 2=both). arg1 = clear mode/flag passed to Npc_StopAnimAndClearOutfitOverride (NOT an outfit id).

Args:
  0. slot (0=comp1, 1=comp2, 2=both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. clear mode/flag

### `op 506` — WarpMonstersToPlayer()
*handler:* `Script_VMOp_TeleportAllCompanionMonstersToPlayer`

Teleport all companion monsters to the player.

## Flags & variables

### `op 214` — SetNpcStoryFlag(npc id)
*handler:* `Script_VMOp_SetNpcStoryFlag`

Set the 'NPC has appeared in story' flag for NPC(s). **arg == 0**: sets the flag for **all NPCs 1..23** (bulk unlock). **arg != 0**: sets the flag for just that NPC. Flag address = GameFlags bit `arg + 981` (so NPC #1 = flag 982, etc.). Distinct from op 233's flag range. Used by the dev 'Boy'/'Girl' name-entry path to bulk-set all NPCs to visible after switching gender.

Args:
  0. npc id (0 = all)

### `op 215` — ClearNpcStoryFlag(npc id)
*handler:* `Script_VMOp_ClearPerNpcFlagBase981`

Mirror of op 214 `SetNpcStoryFlag`: clears the 'NPC has appeared' flag bit `981 + arg` for one NPC. Uses the same NPC slot bounds (1..47) and same flag bit formula, just AND-NOT instead of OR.

Args:
  0. npc id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 318` — SetFlag(npc)
*handler:* `Script_VMOp_SetPackedGameFlag`

Set GameFlags zone-2 bit 4096 + 1007 + id (only sets, never clears). Every shipped call (150) passes a character id as actor(..), so this is the 'birthday gift given' bit of that NPC -- the same bit NpcAi_OnReceivedThrownItem sets when the player gives a gift on the NPC's birthday, and the one Calendar_IsEventActive tests for birthday rows (verified 2026-09-23).

Args:
  0. npc (char id) -- sets the birthday-gift-given bit 1007 + id

### `op 340` — SetVar0(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind0`

Write `value` into global script-variable bank 0 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar0 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind0.

Args:
  0. index
  1. value

### `op 341` — SetVar0(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind0`

Write `value` into global script-variable bank 0 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar0 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind0.

Args:
  0. index
  1. value

### `op 343` — SetVar1(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind1`

Write `value` into global script-variable bank 1 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar1 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind1.

Args:
  0. index
  1. value

### `op 345` — SetVar11(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind11`

Write `value` into global script-variable bank 11 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar11 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind11.

Args:
  0. index
  1. value

### `op 347` — SetVar2(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind2`

Write `value` into global script-variable bank 2 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar2 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind2.

Args:
  0. index
  1. value

### `op 348` — SetVar2(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind2`

Write `value` into global script-variable bank 2 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar2 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind2.

Args:
  0. index
  1. value

### `op 349` — SetVar3(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind3WithSaturation`

Write `value` into global script-variable bank 3 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar3 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind3WithSaturation.

Args:
  0. index
  1. value

### `op 351` — SetVar4(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind4`

Write `value` into global script-variable bank 4 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar4 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind4.

Args:
  0. index
  1. value

### `op 353` — SetVar5(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind5`

Write `value` into global script-variable bank 5 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar5 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind5.

Args:
  0. index
  1. value

### `op 355` — SetVar6(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind6`

Write `value` into global script-variable bank 6 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar6 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind6.

Args:
  0. index
  1. value

### `op 359` — SetVar8(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind8`

Write `value` into global script-variable bank 8 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar8 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind8.

Args:
  0. index
  1. value

### `op 361` — SetVar9(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind9_WithNpcFallback`

Write `value` into global script-variable bank 9 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar9 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind9_WithNpcFallback.

Args:
  0. index
  1. value

### `op 364` — SetVar10(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind10`

Write `value` into global script-variable bank 10 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar10 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind10.

Args:
  0. index
  1. value

### `op 365` — SetVar15(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind15`

Write `value` into global script-variable bank 15 at [index]. These banks are ENGINE-GLOBAL state slots -- kinds 0-3 live in the game-globals slot table, the rest in dedicated arrays -- NOT per-scene scratch: a value set here stays visible to later scenes and SHARES storage with the choice-commit system (a committed PROMPT_CHOICE writes its follow-up param into the same slots via the same lookup). These slots also feed NPC villager-behavior AI and dialogue-text substitution codes (a text code reads a stored slot, else falls back to a default), so SetVar reaches beyond scene branching. Read it back with GetVar15 (into reg0). IDA-verified: Script_VMOp_WriteVarArrayKind15.

Args:
  0. index
  1. value

### `op 366` — SetVar13(bank-13 value, index, bank-14 value(s) …)
*handler:* `Script_VMOp_WriteVarArrayKind13AndKind14Multi`

Write to the paired global script-variable banks 13/14 at [index] — arg order is (value, index), not (index, value): bank13[arg1] = arg0, with arg0 == 0 replaced by the sentinel 0x3B49; every FURTHER arg is written into bank 14 starting at the same index (arg2 -> bank14[index], arg3 -> bank14[index+1], ...; both banks capped at 16 slots). The corpus-dominant 3-arg form SetVar13(0, idx, v) therefore stores v in BANK 14 and the sentinel in bank 13; the 11/12-arg forms bulk-fill bank 14. These are engine-global choice-commit slots (shared with PROMPT_CHOICE and dialogue-text substitution). Read back with GetVar13/GetVar14 (into reg0).

Args:
  0. bank-13 value (0 -> sentinel 0x3B49)
  1. index
  2. bank-14 value(s) …

### `op 373` — DispatchCondScriptEntry(em entry id)
*handler:* `Script_VMOp_DispatchCondScriptEntry`

Run em.bin entry [id]'s MAIN action stream (GameFlags writes; CALLs recurse into other entries' main streams). E.g. EV_SUBEV_INIT resets all sub-event flags.

Args:
  0. em entry id

### `op 374` — CondScriptDispatchAltAction(em entry id)
*handler:* `Script_VMOp_CondScriptDispatchAltActionByEntryId`

Run em.bin entry [id]'s ALT action stream. Date scenes end with entry 80 EV_DATE_FINISH (clears FLG_DATE_FES_NOW / FLG_KOKUHAKU_NOW / REG_DATE_MAP).

Args:
  0. em entry id

### `op 443` — SetFlagBit(flag id, value, (unused, always 0), (unused, always 0))
*handler:* `Script_VMOp_SetGameFlagBitDirect`

Set or clear a single game-flag bit in GameFlags ZONE 2: absolute bit 4096 + id (the handler adds the buffer's zone2_base; ids are zone-2 relative like MOBJ f13, NOT emdeb/emflags names; known blocks in emflags.ZONE2_BLOCKS). No extra +1007 — do NOT confuse with op 318, which adds 1007 and only sets. arg0 = flag id, arg1 = 0 clears / non-zero sets. The handler reads only 2 args, but every shipped statement passes 4 — args 2-3 are always 0 and ignored; the editor should accept/emit the 4-arg form.

Args:
  0. flag id
  1. value (0=clear, else set)
  2. (unused, always 0)
  3. (unused, always 0)

### `op 444` — SetFlagBitIfCond(flag id, em entry id)
*handler:* `Script_VMOp_SetGameFlagBitGatedByCondScript`

Set/clear GameFlags bit [flag id] from em.bin entry [entry id]'s condition A: cond TRUE -> clear the bit, FALSE -> set it (inverse!). The flag id is ZONE-2 RELATIVE (absolute bit 4096 + id; Script_VMOp_SetGameFlagBitGatedByCondScript adds the buffer's zone2_base), like ops 443/445 -- not an emdeb/emflags name.

Args:
  0. flag id
  1. em entry id

### `op 557` — SetNpcRecognitionFlags(value, npc ids)
*handler:* `Script_VMOp_UnlockPerNpcAchievementByList`

Write a per-NPC packed game-flag (base id 1451 + npc id) = [arg0] for each npc id in the variadic list (an npc id of 0 falls back to the married partner). These are the 23 per-NPC recognition flags (1451-1473); like op290/op698 they go through GameFlags_WritePacked -- a graded packed-flag write, NOT one of the ~30 named Steam achievements (the old 'UnlockNpcAchievements' name overstated it).

Args:
  0. value
  1. npc ids (variadic)

### `op 558` — SetNpcRecognitionFlags(value, npc ids)
*handler:* `Script_VMOp_UnlockPerNpcAchievementByList`

Write a per-NPC packed game-flag (base id 1451 + npc id) = [arg0] for each npc id in the variadic list (duplicate of op 557; npc id 0 = the married partner). Per-NPC recognition flags 1451-1473 via GameFlags_WritePacked -- a packed-flag write, not a Steam achievement.

Args:
  0. value
  1. npc ids (variadic)

### `op 566` — AdvanceStoryMilestone(progress, story step)
*handler:* `Script_VMOp_OnStoryMilestoneProgressAndUnlock`

Advance a main-story milestone and unlock its achievement. arg0 = progress level (1-3), arg1 = story-step id (6-17). Commits the story-progress game flag, broadcasts the story event to every NPC (updates their reactions), and — if this raises the recorded progress — unlocks the achievement mapped to that step. The core 'story just advanced' op for scenario cutscenes.

Args:
  0. progress (1-3)
  1. story step (6-17)

### `op 571` — SetSceneScratch(byte value, word value)
*handler:* `Script_VMOp_SetSceneFlagByteAndWord`

Store a scene-local scratch byte + word for the current scene. arg0 = byte (scene+541), arg1 = word (scene+544). Free scratch space a scene script can stash small state in; read the byte back with GetSceneScratchByte (op 572).

Args:
  0. byte value
  1. word value

### `op 621` — SetDifficulty(mode)
*handler:* `Script_VMOp_SetDifficultyMode`

Set the game DIFFICULTY (the Special-edition Easy/Normal/Hard/Hell option; the old 'SetDevMode' name was wrong). arg0 = mode: 0 = Easy (g_globalGameStateFlags bit 0x4000), 1 = Normal (clears 0xC000), 2 = Hard AND Hell (bit 0x8000 — the script distinguishes Hell with a separate packed-flag STORE, the engine bit is the same). Modes 0/1 also write packed GameFlag 3005 = 0. Bit 0x8000 gates monster bonus-level tiers, extra per-level stat gains, and lethal status/environment damage; 0x4000 skips a faint penalty. Used by the difficulty-change dialog (bank 71 tail @0x12a6).

Args:
  0. mode (0=Easy, 1=Normal, 2=Hard/Hell)

### `op 628` — SetRegisters(reg0 value, reg1 value, …up to reg9)
*handler:* `Script_VMOp_ExportArgsAsCtxOutArray10`

Load the VM REGISTER FILE reg0..reg9 (ctx+64..+100) from up to 10 argument values — reg[i] = arg[i]. These are the registers expressions read back via the reg tokens, SWITCH_EQ selectors dispatch on, and camera/position ops consume (GetPlayerPosition writes reg0/reg1; a staged PROMPT_CHOICE writes the pick to reg0). This op is how a script seeds them explicitly (1,825 uses). Registers are flat scratch — NOT saved across CALL — so consume them before the next op that writes reg0.

Args:
  0. reg0 value
  1. reg1 value
  2. …up to reg9

### `op 629` — SetRegisters(reg0 value, reg1 value, …up to reg9)
*handler:* `Script_VMOp_ExportArgsAsCtxOutArray10`

Alias of op 628 (same handler): load reg0..reg9 from up to 10 values.

Args:
  0. reg0 value
  1. reg1 value
  2. …up to reg9

### `op 651` — AdvanceStoryProgress(story progress value)
*handler:* `Script_VMOp_AdvanceStoryProgressMax`

Advance the main story-progress flag to a new value — MONOTONIC: it only moves forward, never regresses, and unlocks the matching story achievement. arg0 = the new story-progress value (0..511, GF_REG_MAIN_SCENARIO). THE op that marks a story milestone at the end of a plot cutscene.

Args:
  0. story progress value

### `op 667` — SetSaveConfigBit0()
*handler:* `Script_VMOp_SetSaveConfigBit0`

Set save-config settings flag bit 0 of g_saveConfigFlags.

### `op 669` — SetSaveConfigBit4()
*handler:* `Script_VMOp_SetSaveConfigBit4`

Set save-config settings flag bit 4 of g_saveConfigFlags.

### `op 671` — SetSaveConfigBit5()
*handler:* `Script_VMOp_SetSaveConfigBit5`

Set save-config settings flag bit 5 of g_saveConfigFlags.

### `op 685` — SetGlobalScratch(value)
*handler:* `Script_VMOp_SetGlobalDword302E4`

Set a general-purpose global scratch dword (persists across scenes within a session). arg0 = value. Stash a value here and read it back later with GetGlobalScratch (op 686) to pass data between scripts.

Args:
  0. value

## Audio

### `op 379` — PlayMusic(bgm id)
*handler:* `Script_VMOp_PlayBGMOrRestore`

Switch background music with a crossfade. **arg = -1 restores the contextual BGM** (clears the scripted-BGM marker bit 0x10000000 at ctx+116, calls Scene_ApplyContextualBGM). Otherwise starts BGM #arg via BGM_SwitchWithCrossfade and sets the scripted-BGM marker so the contextual picker won't override it. Also sets the 'first scripted BGM played' game-flag (packed id 1072, via GameFlags_WritePacked) -- an internal milestone flag, not a Steam achievement. Special case: `arg == 16777332` triggers an additional Sfx_ApplyVoiceVolume with category-bias 45.

Args:
  0. bgm id (or -1 = restore)

### `op 380` — StopMusic(volume arg)
*handler:* `Script_VMOp_StopBGMWithCrossfade`

STOP the current BGM with a crossfade out: the handler computes a volume target from arg/100 but passes track id -1 to BGM_SwitchWithCrossfade (0x7ff7c1f5aa00), whose a1<0 branch stops the channel voice and discards the target. So the op halts music; it does not ramp to a level (old 'FadeMusic volume ramp' reading retired - decomp port 2026-09-01). The single corpus arg is effectively ignored.

Args:
  0. volume arg (computed, then discarded by the stop branch)

### `op 382` — SetSfxVolume(mode / volume, attenuation)
*handler:* `Script_VMOp_SetSfxCaptureVolumeOverride`

Override the SFX-capture volume for the scene (handler Script_VMOp_SetSfxCaptureVolumeOverride). arg0 = mode/volume: -1 restores the default volume; any other value captures the current scaled capture volume. arg1 = distance attenuation, passed to Sfx_ApplyDistanceAttenuation. (Handler reads two args -- argbuf[-3]=mode, [-5]=attenuation.)

Args:
  0. mode / volume (-1 = restore default)
  1. attenuation

### `op 383` — SetSfxDuckingBypass(enable)
*handler:* `Script_VMOp_SetSfxCaptureBypassFlag`

Set the SFX-capture / audio-ducking bypass flag on `g_sfxCaptureActive[+9]` (writes `arg != 0`). Used to **temporarily disable SFX ducking during cutscenes** so scripted BGM plays at full volume without being auto-lowered by an active NPC bubble / dialog.

Args:
  0. enable

### `op 384` — ResetSfxScratch()
*handler:* `Script_VMOp_ClearSfxCaptureWorkVars`

Reset the SFX/BGM dispatcher's per-channel scratch state (zeroes ~20 bytes of capture work vars). Low-level audio housekeeping. Takes no arguments.

### `op 385` — PlaySound(sfx id)
*handler:* `Script_VMOp_PlaySfxById`

Play a sound effect by id.

Args:
  0. sfx id

### `op 386` — StopVoices()
*handler:* `Script_VMOp_VoiceStopAllActive`

Stop all active voice slots.

### `op 387` — PlaySfxWithNpcRemap(sfx / voice id)
*handler:* `Script_VMOp_PlayVoiceOrSfxWithNpcVariantRemap`

Play a sound/voice by id, applying the per-NPC variant remap (calls Sfx_PlayByIdWithNpcVariantRemap): the remap picks a per-character voice/footstep variant when the same base sfx id is shared across characters (char-variant +5 remap windows; id 0 stops all menu audio; routes by id range to Sfx_PlayById or Player_PlayVoiceLine_VariantRemapped). Same callee the SetSpeaker* ops use for args >= 0x1F0 — which is why those args are voice ids. Companion op 385 plays a raw id without remapping.

Args:
  0. sfx / voice id

### `op 389` — FindVoiceSlot((ignored by the handler))
*handler:* `Script_VMOp_FindOrPreemptVoiceSlot`

Reserve a voice sfx slot: Sfx_FindOrPreemptVoice() picks (or preempts) a slot and Sfx_ApplyDistanceAttenuation(slot, ..., 0) sets it to full volume. The handler reads NO script args - the single value retail scripts pass (12 uses) is decoded by the VM and discarded.

Args:
  0. (ignored by the handler)

### `op 390` — StopVoiceId(voice id)
*handler:* `Script_VMOp_VoiceStopMatchingId`

Stop the voice matching an id.

Args:
  0. voice id

### `op 392` — PlayVoicedSound(sfx id)
*handler:* `Script_VMOp_PlaySfxByIdViaVoiceSlot`

Play a sound effect via a dedicated voice slot.

Args:
  0. sfx id

### `op 461` — SuppressRewardJingle()
*handler:* `Script_VMOp_SuppressNextRewardPopupSfx`

Suppress the jingle of the NEXT reward popup (sets the scene's suppress bit that the reward ops check). Pairs with GrantFestivalRewards (op 462). Takes no arguments.

## Time & calendar

### `op 300` — AdvanceDay()
*handler:* `ScriptVMOp300_AdvanceDayResetSchedules`

Advance to the next day and reset all NPC schedules + AI (Day_AdvanceResetAllNpcSchedulesAndAi). No args.

### `op 304` — GetMinute()
*handler:* `Script_VMOp_GetCalendarMinute`

Read the current calendar minute.

### `op 305` — GetSeason()
*handler:* `Script_VMOp_GetCalendarSeason`

Read the current calendar SEASON index into the VM output — NOT the hour. The handler reads cal_inner+16, and the verified calendar layout (from the SetTime handler and Calendar_NormalizeTimeCarry) is [+0 sec, +4 minute, +8 hour, +12 day, +16 season, +20 year]: the real hour lives at +8. Season is 0-3 (Spring..Winter). No args.

### `op 306` — GetDay()
*handler:* `Script_VMOp_GetCalendarDay`

Read the current calendar day.

### `op 307` — GetMonthSeason()
*handler:* `Script_VMOp_GetCalendarMonthAndSeason`

Read the calendar's month and season into the VM outputs: main output = month, second output = season (0=Spring, 1=Summer, 2=Fall, 3=Winter). Reads the display-snapshot calendar struct. Takes no arguments.

### `op 308` — GetDateSnapshot()
*handler:* `Script_VMOp_GetCalendarFullSnapshot`

Read a full calendar snapshot into 5 VM outputs: reg0 = YEAR (+20), reg1 = SEASON (+16), reg2 = day (+12), reg3 = hour (+8), reg4 = minute (+4) - the verified cal_inner field order (the same offsets that proved op 305 returns the season). An earlier note listing minute..season order parroted stale IDB labels. No args.

### `op 448` — SetWeatherTransition(transitioning)
*handler:* `Script_Action_SetWeatherTransitionFlag`

Set the weather-transition flag — whether the weather is currently mid-change. arg0 = 0 (settled) or non-zero (transitioning). Read it back with GetWeatherTransition (op 449).

Args:
  0. transitioning (0/1)

### `op 449` — GetWeatherTransition()
*handler:* `Script_Query_WeatherTransitionFlag`

Read the weather-transition flag into the VM output (1 while the weather is mid-change, else 0). Takes no arguments.

### `op 450` — GetWeatherStreak()
*handler:* `Script_Query_WeatherStreakCounter`

Read the weather streak / cycle-position counter into the VM output (how far through the current weather cycle; defaults to 30 when no weather task is active). Takes no arguments.

### `op 451` — GetDayOfWeek()
*handler:* `Script_VMOp_GetCalendarDayOfWeek`

Read the current day of the week.

### `op 465` — SetCalendarPauseFlag(pause)
*handler:* `Script_VMOp_SetCalendarPauseFlagFromBit0`

Halt or resume in-game time during a scene — sets the scene's calendar-pause control flag from arg0's low bit (1 = the scene controls time). Use to freeze the clock for a cutscene, then release it.

Args:
  0. pause (bit 0)

### `op 466` — SkipToTime(hour, minute, enable)
*handler:* `Script_VMOp_FastForwardCalendarToHourMinute`

Fast-forward the clock FORWARD to a target time (hour:minute), rolling into the next day(s) if the target is earlier than now -- the classic cutscene 'time passes' skip (FastForwardForSleep). arg0 = target HOUR (cal_inner +8, forward delta mod 24), arg1 = target MINUTE (cal_inner +4), arg2 = enable (0 = no-op). Definitive field map from Calendar_NormalizeTimeCarry: cal_inner = [+0 Q12sec, +4 minute, +8 hour, +12 day, +16 season, +20 year]; hour>24 rolls the day, day>30 rolls the season -- so this sets the TIME, not the date (date advances only via rollover). Shipped scenes: arg0 = a target hour (6/8/17/21/22...), arg1 = 0 (on the hour), arg2 = 1. (Was mislabeled SkipToDate/day+month.)

Args:
  0. hour
  1. minute
  2. enable (0 = no-op)

### `op 467` — SetTime(hour, minute, absolute)
*handler:* `Script_VMOp_SetOrAddCalendarHourMinute`

Set or advance the in-game CLOCK (hour:minute). arg0 = HOUR (cal_inner +8), arg1 = MINUTE (cal_inner +4), arg2 = 0 to ADD them as a delta or non-zero to SET them absolutely. Definitive field map from Calendar_NormalizeTimeCarry: cal_inner = [+0 Q12sec, +4 minute, +8 hour, +12 day, +16 season, +20 year]. The DAY/season/year fields (+12/+16/+20) are PRESERVED -- these ops do NOT take a date arg; the date advances only when the hour overflows 24 (-> day) or day overflows 30 (-> season). Normalizes overflow and refreshes the clock/weather UI. Shipped scenes: arg0 = an hour (12/23), arg1 = 0, arg2 = 1. Unlike op 466 SkipToTime this supports absolute-set + a full year-tier UI refresh. (Was mislabeled SetDate/day+month.)

Args:
  0. hour
  1. minute
  2. absolute (0=add, else set)

### `op 468` — FastForwardCalendar(±year/season, ±month, ±day, ±hour, absolute)
*handler:* `Script_VMOp_FastForwardCalendarFineGrained`

Fast-forward the in-game calendar and run the sleep update (schedule refresh, crop growth, etc). arg0 = year/season, arg1 = month, arg2 = day, arg3 = hour, arg4 = absolute mode (0 = advance by these amounts, non-zero = set directly). The time-skip op ('…the next morning').

Args:
  0. ±year/season
  1. ±month
  2. ±day
  3. ±hour
  4. absolute (0/1)

### `op 469` — SetOrAddCalendarDate(year/season, month, day, absolute)
*handler:* `Script_VMOp_SetOrAddCalendarYMDS`

Set or advance the calendar's year / month / day in one call, then run the sleep update and refresh the clock HUD. arg0-2 = the date components, arg3 = absolute mode (0 = add the amounts, non-zero = set them directly). Coarser than FastForwardCalendar (op 468) — no hour.

Args:
  0. year/season
  1. month
  2. day
  3. absolute (0/1)

### `op 627` — SleepToMorning()
*handler:* `Script_VMOp_SleepWithRandomizedMinuteAndUnpause`

Advance to the next morning (randomized minute) and unpause.

### `op 637` — SaveCalendarSnapshot()
*handler:* `Calendar_SaveSnapshot`

Save a calendar snapshot.

## Items, rewards, economy

### `op 209` — GiveOrDropItem(target, item id)
*handler:* `Script_Action_HandOrDropItem`

Materialize an item and place it: arg0 = target (0 = the player, 1-47 = an NPC slot), arg1 = item id. NPCs receive it in-hand; the player holds it, or — if the player can't hold it — it drops on the ground with a puff. The 'NPC hands you a gift / holds up an item' cutscene primitive (uses the pending-interaction record for item attributes).

Args:
  0. target (0=player, 1-47=NPC)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 210` — AttachItemVisual(holder, item id, variant, level)
*handler:* `Script_VMOp_AttachItemVisualToNpcOrPlayerOrDrop`

Make a character visibly HOLD UP / present an item — the 'Vishnal hands you a sword' / 'Doug presents the trophy' op. arg0 = holder (char id, 0 = player), arg1 = item id, arg2 = variant/charge, arg3 = level/quality. If the player is already holding something, the item is dropped at their feet instead. Writes 1 (held) / 0 (dropped) to the VM output. Consumes the pending-interaction record (for a just-crafted / just-gifted item's attributes).

Args:
  0. holder (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  2. variant
  3. level

### `op 325` — GetLumber()
*handler:* `Script_VMOp_GetPlayerLumber`

Read the player's lumber count.

### `op 326` — ModifyLumber(mode arg, amount)
*handler:* `Script_VMOp_ModifyPlayerLumber`

Modify the player's lumber. The operation is taken from arg0's TOKEN KIND (the handler reads the kind slot at idx-2; arg0's value is ignored): kind 4 = add (cap 50000), 5 = subtract (clamp 0), 6 = set (stricter 9999 cap). arg1 = amount. Corpus always passes 2 args; bank 6's building-cost path runs it between ModifyPlayerResource calls to deduct lumber, so 'Add' was misleading — it also subtracts and sets.

Args:
  0. mode arg (op from token kind: 4=add, 5=sub, 6=set; value unused)
  1. amount

### `op 417` — ModifyPlayerResource(resource code, op, amount)
*handler:* `Script_VMOp_ModifyPlayerResourceByCharCodeOp`

Grant or take a player resource. arg0 = resource char-code: 'd'(100)=gold (caps at 2,000,000,000), 'i'(105)=stone, 'j'(106)=compost (both cap 50,000), 'f'(102)=armor def. arg1 = op: 4 = add, 5 = subtract, 6 = set. arg2 = amount. Subtracting gold plays the coin-clink SFX. The 'pay 1000 gold' / 'here's a reward' op.

Args:
  0. resource code (d=gold,i=stone,j=compost,f=def)
  1. op (4=add,5=sub,6=set)
  2. amount

### `op 423` — GiveItem(item id, count, quality)
*handler:* `Script_VMOp_GivePlayerItemWithStackAndQuality`

Give the player an item (stack + quality).

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count
  2. quality

### `op 424` — GivePlayerItem(item id, stack count, quality)
*handler:* `Script_VMOp_GivePlayerItemWithStackAndQuality`

Give the player an item — the core reward/gift op. arg0 = item id, arg1 = stack count, arg2 = quality. Plays the pick-up animation and adds it to the backpack (or rune/ability page); if the bag is full it drops the item at the player's feet with a jingle instead. Writes success (1/0) to the VM output.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. stack count
  2. quality

### `op 425` — ForcePlayerHoldItem(item id, quality, stack count)
*handler:* `Script_VMOp_ForcePlayerHoldItemOrConsume`

Put an item directly in the player's HANDS (held, not in the bag) with the pickup jingle. arg0 = item id (0 = instead consume/use up the currently-held item), arg1 = quality, arg2 = stack count. For 'the player holds up what they just made / received'. Distinct from GivePlayerItem (op 424), which adds to the backpack.

Args:
  0. item id (0=consume held)
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. quality
  2. stack count

### `op 428` — TakeItem(item id, count, quality filter)
*handler:* `Script_VMOp_TakeItemFromAnyContainer`

Remove (consume) N of an item from ANY of the player's containers — backpack, equipped-extras, every inventory page, storage, weapon rack, closet, tool box, shipping bin, fridge, bookshelf, and rune abilities — scanned in priority order until the demand is met. arg0 = item id, arg1 = count, arg2 = quality filter (when > 0, only removes copies whose quality byte is 0). Plays the 'item removed' jingle when finished.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count
  2. quality filter (>0=plain only)

### `op 429` — TakeItemFromBackpack(item id, count, quality)
*handler:* `Script_VMOp_TakeItemFromBackpackOrEquipExtras`

Remove an item from the player's backpack or equip-extras (a scripted take). arg0 = item id, further args = count / quality. Used for quest turn-ins and story items taken from the player.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count
  2. quality

### `op 430` — ConsumeHeldItem(count)
*handler:* `Script_VMOp_ConsumeFromHeldItemNTimes`

Consume / use up N of the item the player is currently holding. arg0 = count. For 'the player uses the item' cutscene moments.

Args:
  0. count

### `op 452` — SpawnItemAtTile(item id, count, quality, x tile, y tile, as-drop)
*handler:* `Script_VMOp_SpawnItemAtTileAsDropOrVisual`

Spawn an item in the world at a map tile -- as a droppable pickup or a visual-only prop, chosen by the last arg (handler Item_SpawnAtPositionAsDropOrVisual). NOT a shipping-bin op despite the old name (real shipping = QueryShippingBoxTotalGold @ op 649). Verified: 28 scene call sites pass (item, count, quality, x_tile, y_tile, drop).

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count
  2. quality
  3. x tile
  4. y tile
  5. as-drop (0=visual, 1=pickup)

### `op 453` — DropStagedItem()
*handler:* `Script_VMOp_DropStagedItemAtPlayerTile`

Drop the pre-staged item (set up earlier in the scene) onto the ground at the player's tile. No args — it reads the staged item record. Used when an item should 'appear on the ground' at the player's feet.

### `op 454` — SpawnItemVisual(item id, x, y)
*handler:* `Script_VMOp_SpawnItemVisualAt3SlotTracker`

Spawn a floating item-display visual at a tile (one of 3 scripted slots). arg0 = item id, arg1/arg2 = X/Y tiles ( -1, -1 = the player's tile ). For showing items floating in a scene — gift choices, item reveals. Clear them with op 455.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. x (tiles, -1=player)
  2. y (tiles, -1=player)

### `op 455` — DespawnItemVisuals()
*handler:* `Script_VMOp_DespawnAllScriptedItemVisuals`

Despawn all the floating item-display visuals spawned by SpawnItemVisual (op 454). No args. Cleanup at the end of an item-reveal scene.

### `op 457` — ShowRewardPopup(item0, item1, item2, item3)
*handler:* `Script_VMOp_SpawnRewardPopupWithUpTo4Items`

Show a reward popup for up to 4 items.

Args:
  0. item0
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. item1
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  2. item2
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  3. item3
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 458` — ShowQuestReward()
*handler:* `Script_VMOp_SpawnNpcQuestRewardPopup`

Show the NPC quest-reward popup.

### `op 459` — ShowRewardPopupAtTile(item id, x, y)
*handler:* `Script_VMOp_SpawnRewardPopupSingleAtTile`

Show a single-item reward popup ('You got [item]!') at a specific world TILE, with the reward jingle, and mark the item as discovered. arg0 = item id, arg1/arg2 = X/Y tiles. Unlike ShowRewardPopup (op 457), this places the popup at a chosen tile rather than on the player.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. x (tiles)
  2. y (tiles)

### `op 460` — AddRewardItem(reward slot, item id, count, quality)
*handler:* `Script_VMOp_AddItemToRewardSlotPopup`

Add an item to a reward slot and queue the reward popup (RewardSlot_AddToInventoryAndQueuePopup). arg0 = reward slot id, arg1 = item id, arg2 = count (clamped to 1-10; forced to 1 for non-stackable items), arg3 = quality (clamped to 1-9). Unused in the shipped corpus.

Args:
  0. reward slot
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. item id
  2. count (1-10)
  3. quality (1-9)

### `op 462` — GrantFestivalRewards(reward tokens)
*handler:* `Festival_RollAndDistributeRewardsFromTemplate`

Roll and grant up to 8 festival/event rewards from a reward template and show the reward popup (with the completion jingle unless silenced by op 461). Each variadic token chooses a roll strategy: 0x270D festival prize item, 0x270E shop-category roll, 0x270F generic loot, 0x2710 quest-specific loot; any other value is a literal item id.

Args:
  0. reward tokens (variadic)

### `op 463` — DropItem(item id)
*handler:* `Script_VMOp_DropSingleItemAtPlayer`

Drop a single item at the player.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 464` — DropItemStack(item id, count, quality)
*handler:* `Script_VMOp_DropItemStackAtPlayer`

Drop a stack of an item at the player (item id, count, quality). Handler packs quality into the slot's high bits, like the item-spawn family.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count
  2. quality

### `op 563` — EquipScriptedWeapon(weapon item id)
*handler:* `Script_VMOp_ForceEquipWeaponSlot1AsScripted`

Temporarily arm the player with a specific weapon for a scripted scene (tutorials, cutscenes). Backs up whatever is in the mainhand slot, then force-equips arg0's item id there and refreshes the HUD. Pair with RemoveScriptedWeapon (op 564) to restore the player's real weapon afterwards.

Args:
  0. weapon item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 564` — RemoveScriptedWeapon()
*handler:* `Script_VMOp_RemoveScriptedWeaponAndRefreshHud`

Undo EquipScriptedWeapon (op 563): restore the mainhand weapon that was backed up when the scripted weapon was equipped, and refresh the HUD. Takes no arguments.

### `op 587` — GiveTileObject(item id, container id, x, y)
*handler:* `Script_VMOp_TryGiveTileObjectAndPlayDrop`

Place a 'tile object' — a collectible/scene object that sits on a tile (like a dropped item the player can walk over to pick up) — with the drop jingle and drop indicator. arg0 = item id, arg1 = container/context id (-1 = current), arg2/arg3 = X/Y tiles (-1 = the player's tile). Writes 1 to the VM output if placed (max 16 active).

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. container id (-1=current)
  2. x (tiles, -1=player)
  3. y (tiles, -1=player)

### `op 590` — OpenRequestBox()
*handler:* `Script_VMOp_DropQuestBoxItems1022And1023AndDestroy`

Open the scene's request box: spawn item 1022 (the Box) and item 1023 (the Note) at the object's position with a dirt-cloud puff, then clear the tile-object slot and destroy the box actor. This is the 'open Eliza's Request Box' interaction. Takes no arguments.

### `op 597` — RollShopCategoryItemReturnId(shop category)
*handler:* `Script_VMOp_RollShopCategoryItemReturnId`

Roll a random item id from a shop category table (Shop_RollByCategoryFromTable) and write it to the VM output slot for a following read.

Args:
  0. shop category

### `op 598` — RollRandomItemMatchingDisplayName(display-name string id)
*handler:* `Script_VMOp_RollRandomItemMatchingDisplayName`

Roll a random item whose display-name string id matches the arg (groups items that share a name, e.g. all Swords), preferring the cheapest tier; result to the VM output slot. Used for shop randomization.

Args:
  0. display-name string id

### `op 599` — LootRollGenericFromTable()
*handler:* `Script_VMOp_LootRollGenericFromTable`

Loot Roll Generic From Table. Rolls a value via the RNG (usually a random item id, sometimes an integer or position) and writes the result to the VM output slot for a following read — used to generate reward / treasure / shop contents.

### `op 600` — RollRandomShopItem()
*handler:* `Script_VMOp_RollRandomShopItemFromRandomCategory`

Roll a random shop item id and write it to the VM output (reg0) for a following read. MMIX RNG first picks one of 5 shop categories (the '!"#$%' category byte table), then Shop_RollByCategoryFromTable rolls an item from that category's shop table. No args. Used to generate random reward/treasure contents.

### `op 601` — RollRandomRingItemIdInTier()
*handler:* `Script_VMOp_RollRandomRingItemIdInTier`

Roll Random Ring Item Id In Tier. Rolls a value via the RNG (usually a random item id, sometimes an integer or position) and writes the result to the VM output slot for a following read — used to generate reward / treasure / shop contents.

### `op 602` — RollRandomTurnipFamilyItemIdInTier()
*handler:* `Script_VMOp_RollRandomTurnipFamilyItemIdInTier`

Roll Random Turnip Family Item Id In Tier. Rolls a value via the RNG (usually a random item id, sometimes an integer or position) and writes the result to the VM output slot for a following read — used to generate reward / treasure / shop contents.

### `op 603` — ShopRollByCategoryRange()
*handler:* `Script_VMOp_ShopRollByCategoryRange`

Shop Roll By Category Range. Rolls a value via the RNG (usually a random item id, sometimes an integer or position) and writes the result to the VM output slot for a following read — used to generate reward / treasure / shop contents.

### `op 604` — RollRandomMineralOrIngredientItemIdInTier()
*handler:* `Script_VMOp_RollRandomMineralOrIngredientItemIdInTier`

Roll Random Mineral Or Ingredient Item Id In Tier. Rolls a value via the RNG (usually a random item id, sometimes an integer or position) and writes the result to the VM output slot for a following read — used to generate reward / treasure / shop contents.

### `op 605` — RollRandomFilteredItem()
*handler:* `Script_VMOp_RollRandomItemByLookupBytemask195`

Roll a random item id from a fixed eligible set — iterates the 195 item ids in [123, 314), keeps those whose byte in a lookup table is 0, applies a shop-availability filter, then MMIX-picks one (falls back to item 314 if none) — and write it to the VM output for a following read. The table's meaning is unverified (plausibly 'gift items NPCs accept'). No args.

### `op 606` — RollThreeFlowerItemsAvoidDup()
*handler:* `Script_VMOp_RollThreeFlowerItemsAvoidDup`

Roll a 3-flower gift choice: writes item 63 (fixed first option) plus two distinct random flower/plant items to the THREE VM outputs reg0/reg1/reg2 (ctx+64/+68/+72). Candidates are item ids 63-70 and 84-109 that pass the shop filter (up to 40 collected); the two rolled picks avoid id 63 and each other (retry-capped, falling back to 65/67), using the global MMIX PRNG. No args. Used by the flower-choice gift dialogue.

### `op 607` — RollRandomItemByLookupBytemask28()
*handler:* `Script_VMOp_RollRandomItemByLookupBytemask28`

Roll a random item id from a fixed 28-id window and write it to the VM output for a following read. Scans item ids 758-785, keeps those whose entry in a 28-byte eligibility table is 0 AND that pass the shop-unlock filter (Item_CheckShopFilter), then picks one with the MMIX RNG; if none qualify, returns the fallback id 759. Takes no arguments. (What items 758-785 are is unconfirmed — likely an ingredient/produce subset — so the mnemonic is kept as-is.)

### `op 616` — QueryAndSetCraftedFlag(item id)
*handler:* `Script_VMOp_QueryAndSetCraftedItemFlagBit`

Read the 'has ever been crafted' flag for an item — returns the OLD value to the VM output, then marks the item as crafted in the save flags. arg0 = item id (100000 = a misc-craft sentinel). Gates first-craft dialogue / rewards.

Args:
  0. item id (100000=misc)
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 639` — GetPrincePoints()
*handler:* `Script_QueryPrincePoints`

Read the current prince points.

### `op 640` — AddPrincePoints(amount)
*handler:* `Script_AddPrincePoints`

Add prince points.

Args:
  0. amount

### `op 641` — GetTourists()
*handler:* `Script_QueryTourists`

Read the current tourist count.

### `op 642` — AddTourists(amount)
*handler:* `Script_AddTourists`

Add tourists.

Args:
  0. amount

### `op 645` — PromotePrinceRank()
*handler:* `PrinceRank_PromoteIfReached`

Promote the prince rank if the threshold is reached.

### `op 653` — ClearShopSelectionA()
*handler:* `Script_VMOp_ClearShopSelectedSlotIdxA`

Reset shop selection slot A to 'none' (writes the no-selection sentinel into the current shop task's work buffer). Takes no arguments.

### `op 654` — ClearShopSelectionB()
*handler:* `Script_VMOp_ClearShopSelectedSlotIdxB`

Reset shop selection slot B to 'none' (no-selection sentinel in the shop work buffer). Takes no arguments.

### `op 655` — ClearShopSelectionC()
*handler:* `Script_VMOp_ClearShopSelectedSlotIdxC`

Reset shop selection slot C to 'none' (no-selection sentinel in the shop work buffer). Takes no arguments.

### `op 675` — ConvertMedalsToGold()
*handler:* `Currency_ConvertMedalsToGold`

Convert all of the player's Rune Medals to gold at 20 gold per medal, clearing the medal count. Writes the gold gained to the VM output. No args. For a medal-exchange NPC.

### `op 679` — IncrementPlayerSkillLevel(skill index)
*handler:* `Script_VMOp_IncrementPlayerSkillLevelByIdx`

Increment a player skill's level by 1. arg0 = skill index (0-39; see the skill id table). A scripted skill bump (e.g. a training-event reward).

Args:
  0. skill index (0-39)
     - `0` = Short Sword
     - `1` = Long Sword
     - `2` = Spear
     - `3` = Axe/Hammer
     - `4` = Dual Blades
     - `5` = Fist
     - `6` = Fire
     - `7` = Water
     - `8` = Earth
     - `9` = Wind
     - `10` = Light
     - `11` = Dark
     - `12` = Love
     - `13` = Farming
     - `14` = Logging
     - `15` = Mining
     - `16` = Fishing
     - `17` = Cooking
     - `18` = Forging
     - `19` = Chemistry
     - `20` = Crafting
     - `21` = Searching
     - `22` = Walking
     - `23` = Sleeping
     - `24` = Eating
     - `25` = Defense
     - `26` = Resist Poison
     - `27` = Resist Seals
     - `28` = Resist Paralysis
     - `29` = Resist Sleep
     - `30` = Resist Fatigue
     - `31` = Resist Cold
     - `32` = Resist Knockout
     - `33` = Bathing
     - `34` = Taming
     - `35` = Throwing
     - `36` = Leadership
     - `37` = Bartering

### `op 681` — LootRollByCategoryForPlayer(loot category)
*handler:* `Script_VMOp_LootRollByCategoryForPlayer`

Roll a loot item for the player from a category loot table (LootTable_RollByCategory) and write the item id to the VM output slot for a following read.

Args:
  0. loot category

### `op 696` — RemoveItemFromBackpack(item id, count, quality)
*handler:* `Script_VMOp_RemoveItemFromBackpackByIdAndCount`

Remove items from the player — the 'take from player' op (quest turn-in, a story item being taken). arg0 = item id, arg1 = count, arg2 = quality filter (-1 = any quality; >=0 = only that quality). Also decrements the held item if it matches.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count
  2. quality (-1=any)

### `op 701` — SetPlayerSkillXp(skill index, xp value)
*handler:* `Script_VMOp_SetPlayerSkillXpByIdx`

Set a player skill's XP directly. arg0 = skill index (0-39), arg1 = XP value. Scripted skill-XP set.

Args:
  0. skill index (0-39)
     - `0` = Short Sword
     - `1` = Long Sword
     - `2` = Spear
     - `3` = Axe/Hammer
     - `4` = Dual Blades
     - `5` = Fist
     - `6` = Fire
     - `7` = Water
     - `8` = Earth
     - `9` = Wind
     - `10` = Light
     - `11` = Dark
     - `12` = Love
     - `13` = Farming
     - `14` = Logging
     - `15` = Mining
     - `16` = Fishing
     - `17` = Cooking
     - `18` = Forging
     - `19` = Chemistry
     - `20` = Crafting
     - `21` = Searching
     - `22` = Walking
     - `23` = Sleeping
     - `24` = Eating
     - `25` = Defense
     - `26` = Resist Poison
     - `27` = Resist Seals
     - `28` = Resist Paralysis
     - `29` = Resist Sleep
     - `30` = Resist Fatigue
     - `31` = Resist Cold
     - `32` = Resist Knockout
     - `33` = Bathing
     - `34` = Taming
     - `35` = Throwing
     - `36` = Leadership
     - `37` = Bartering
  1. xp value

## Effects & world

### `op 139` — ApplyEffectToActor(actor, effect kind id)
*handler:* `ScriptVM_Op_ApplyEffectKindToEntity`

Apply an Effect (damage / heal / status / VFX) to an actor via Effect_ApplyByKindAndSpawn — the scripted-effect entry point. arg0 = actor (char id, 0 = player). arg1 = effect kind id (dispatched by g_effectKindSpawnTable to spawn the visual + apply the gameplay effect). Used for scripted magic, sparkles, heals, and status in cutscenes.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. effect kind id

### `op 140` — ApplyEffectToActor(actor, effect kind id)
*handler:* `ScriptVM_Op_ApplyEffectKindToEntity`

Alias of op 139 (same handler): apply an effect kind to an actor.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. effect kind id

### `op 150` — TriggerActionAtTile(action id, x, y)
*handler:* `Script_VMOp_TriggerActorAction`

Spawn a scripted Action (effect/task) at a world tile via Action_TriggerActor (g_actionConstructorTable dispatch — the 'Action 0xNN' family). arg0 = action id. arg1/arg2 = X/Y tiles. Action ids 65 and 105 auto-target the player's position instead of the passed tile.

Args:
  0. action id
  1. x (tiles)
  2. y (tiles)

### `op 151` — TriggerActorAttack(attack id, attacker)
*handler:* `Script_VMOp_TriggerActorAttack`

Make an actor perform a combat attack move (as_atk timeline) from its current position, via Action_TriggerAttacker. arg0 = attack id. arg1 = attacker (char id, 0 = player). Used for scripted combat in cutscenes (boss demos, story fights).

Args:
  0. attack id
  1. attacker (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 157` — SpawnMapEntity(entity type id, param 1, param 2, facing, sub-param, extra 5, extra 6, flag 7, flag 8, extra 9, extra 10)
*handler:* `ScriptVMOp_SpawnMapEntityByTypeIdDispatchTable`

Spawn a map entity, dispatched by TYPE ID to the right spawner — the central script-side object-placement op (handler ScriptVMOp_SpawnMapEntityByTypeIdDispatchTable). arg0 = entity type id: <20 → special trigger (treasure/quest item, Map_HandleSpecialTriggerEntity), 20-195 → placed game object 'pg_mobj' (Actor_AllocTask 65 → MapObj_SetupActorByTypeId), 196-335 → interactive object (door/stove/lift, Map_SpawnInteractiveObject), 336+ → decoration/scenery (MapDecoration_Spawn). arg1/arg2 = position, arg3 = facing (passed as DEGREES, handler multiplies by 182 = 65536/360 → u16 angle), arg4 = sub-param (handler multiplies by 40). args5-9 = up to 5 optional EXTRA placement params copied into the entity's setup struct; their meaning is ENTITY-TYPE-SPECIFIC (flags, linked ids, size, etc.). Dynamic prop/decor placement from a scene.

Args:
  0. entity type id
  1. param 1 (x/pos)
  2. param 2 (y/pos)
  3. facing (degrees)
  4. sub-param (x40)
  5. extra 5 (type-specific)
  6. extra 6 (type-specific)
  7. flag 7 (0/1, type-specific)
  8. flag 8 (0/1, type-specific)
  9. extra 9 (type-specific)
  10. extra 10 (type-specific)

### `op 165` — TriggerActionAtEventActor(event key, action id)
*handler:* `ScriptVMOp_TriggerActionAtCalendarEventActorPosition`

Spawn a scripted Action (VFX / SFX / trigger) at a spawned event actor's position via Action_TriggerAttacker. arg0 = event key, arg1 = action id. The event-actor counterpart of TriggerActionAtTile (op 150).

Args:
  0. event key
  1. action id

### `op 166` — ApplyEffectToEventActor(event key, effect kind id)
*handler:* `ScriptVMOp_ApplyEffectKindToCalendarEventActor`

Apply an Effect (damage / heal / status / VFX) to a spawned event actor via Effect_ApplyByKindAndSpawn — the event-actor twin of op 139. arg0 = event key (char id), arg1 = effect kind id.

Args:
  0. event key
  1. effect kind id

### `op 205` — RefreshMapTiles()
*handler:* `Script_VMOp_RefreshAllMapTiles`

Force a full refresh of the current map's tiles — mark every tile dirty and recompute its visibility/attribute flags, then flag the player for refresh. Call after a scripted map or tile-attribute change so it redraws. Takes no arguments.

### `op 401` — MonsterFarmSpawn(spawn param)
*handler:* `Script_VMOp_MonsterFarmSpawnFromInteraction`

Send the current interaction monster to the player's monster farm (picks a farm area and spawns it there). arg0 = a spawn mode/param. For taming/relocating a monster you're interacting with.

Args:
  0. spawn param

### `op 402` — SendMonsterToFarmOrClearFlags(arg)
*handler:* `Script_VMOp_MonsterFarmSpawnOrClearFlags`

Dual-purpose monster-farm op: arg0 == -1 sends the current interaction monster to the farm (if it is a valid monster); any other value is a farm-slot index whose status flags (bits 0x600) get cleared.

Args:
  0. arg (-1 = send to farm, else farm slot)

### `op 405` — SetMonsterFarmLovedToday(farm monster, loved)
*handler:* `Script_VMOp_SetMonsterFarmLovedTodayBit`

Set or clear the 'loved today' bit (record flag 0x40000) for a farm monster. arg0 = the farm monster (-1 = current interaction NPC's monster); arg1 = the bit value (1 = mark loved/cared-for today, 0 = clear). Affects daily affection/produce. Read back with op 406.

Args:
  0. farm monster
  1. loved (0/1)

### `op 410` — TameEventMonster(event key)
*handler:* `Script_VMOp_TameCalendarEventNpc`

Tame a spawned event-actor monster and add it to the player's monster farm (queues the tame-success event). arg0 = event key. For a cutscene that 'gifts' the player a tamed / bonded monster.

Args:
  0. event key

### `op 439` — ReleaseFarmMonster()
*handler:* `Script_VMOp_ReleaseFarmMonsterFromInteraction`

Release the scene's target farm monster: clear its farm-table entry, play the release effect, remove the actor, and decrement the tamed-monster count. Used when a monster leaves the farm during a scene. Takes no arguments.

### `op 446` — SetWeather(weather code, apply seasonal conversion)
*handler:* `Script_Action_SetWeather`

Set the current weather. arg0 = weather code (0 Sunny, 1 Rain, 2 Snow, 3 Typhoon, 4 Blizzard, 5 Cloudy, 6 Rooney, 7 Rain-weak, 8 Snow-weak; 0 also clears scripted weather; -1 restores the previous weather). arg1 = if non-zero, run the seasonal promoter so the code is adjusted for the current season (e.g. Rain->Snow in winter). The editor offers a weather picker for arg0.

Args:
  0. weather code
     - `-1` = (restore previous)
     - `0` = Sunny
     - `1` = Rain
     - `2` = Snow
     - `3` = Typhoon
     - `4` = Blizzard
     - `5` = Cloudy
     - `6` = Rooney
     - `7` = Rain (weak)
     - `8` = Snow (weak)
  1. apply seasonal conversion (0/1)

### `op 578` — SpawnEventMonsters()
*handler:* `Script_VMOp_SpawnSceneEventMonsterRosterParticipants`

Spawn and initialise the monster-roster participants for the current scene event (e.g. a monster contest / event where farm monsters take part). Takes no arguments.

### `op 591` — ClearAllTileObjects()
*handler:* `Script_VMOp_ClearAll61TileObjectsActiveBit`

Clear the active flag of every placed tile object (mass reset of the 61 map-object records) and zero their state. Takes no arguments.

### `op 593` — PickRandomTileObject(candidate item ids)
*handler:* `Script_VMOp_PickRandomActiveTileObjectByCandidates`

From a variadic list of candidate item ids, randomly pick one that currently has an active tile object matching the input context (MMIX weighted-random; ~1/8 of the time it picks nothing). Main output = picked item id, or 0. Used to randomly choose which placed object to trigger.

Args:
  0. candidate item ids (variadic)

### `op 617` — ShowCreditsOverlay(mode)
*handler:* `Script_VMOp_SpawnOrConfigureItemPickupIconTaskStaff`

Spawn / configure the staff-credits overlay task (task class 'staff', reusing the item-pickup-icon framework as a scrollable credits driver); if the task already exists it is just re-flagged. arg0 = mode: 0 = Fade (long), 1 = Fade (short), 2 = Credits screen (bottom), 3 = Credits screen (top) - the dev menu's four entries.

Args:
  0. mode (0=fade long, 1=fade short, 2=credits bottom, 3=credits top)
     - `0` = Fade (long)
     - `1` = Fade (short)
     - `2` = Credits (bottom)
     - `3` = Credits (top)

### `op 625` — BeginDungeonArea(dungeon area id)
*handler:* `Trigger_DungeonAreaBegin`

Enter a dungeon area by id — loads the area and installs the in-dungeon input context (442). arg0 = dungeon area id. A scene-transition op for going into a dungeon.

Args:
  0. dungeon area id

### `op 643` — TriggerEffect(effect id, sub-index / variant)
*handler:* `Script_DispatchEffectById`

Dispatch a town/prince effect by id (Effects_DispatchById; spends its cost) and write the returned did-promote flag to the query register. arg1 = sub-index/variant handed to the dispatcher (commonly a runtime variable; verified read at argbuf[-5]).

Args:
  0. effect id
     - `10` = Blossom's Furniture
     - `11` = Lumi's Flower Shop
     - `12` = Cooking Bread tier
     - `13` = Furniture Shop
     - `14` = Blossom's Groceries
     - `15` = Bado's Accessories
     - `16` = Bado's Bargain Sale
     - `17` = Clothing Shop
     - `18` = Fish Market
     - `19` = Jewelry Shop
     - `20` = Magic Shop
     - `21` = Ability Shop
     - `22` = Business License
     - `23` = Nationalize Baths
     - `24` = Forging License
     - `25` = Chemistry License
     - `26` = Crafting License
     - `27` = EZ Cooking License
     - `28` = Pro Cooking License
     - `29` = Effect-applied flag
     - `31` = Rucksack upgrade
     - `32` = Fridge upgrade
     - `33` = Storage upgrade
     - `34` = Bookshelf upgrade
     - `35` = Weapon Rack upgrade
     - `36` = Farm Tool Box upgrade
     - `37` = Closet upgrade
     - `38` = Shipping Box upgrade
  1. sub-index / variant

### `op 677` — SpawnTileEffectObject(x, y)
*handler:* `Script_VMOp_SpawnTileObjectClass2050AtTile`

Spawn a special class-2050 tile object — a floating harvest-notification-style effect actor — at a tile. arg0/arg1 = X/Y tiles. For scripted visual effects.

Args:
  0. x (tiles)
  1. y (tiles)

### `op 678` — ClearTileAttribsInRect(x, y, width, height)
*handler:* `Script_VMOp_ResetTileAttribFlagsInRectTo2`

Clear the tile-attribute flags over a rectangle so the area becomes plain walkable ground (no special attribute) — used to stage an area for a cutscene. arg0/arg1 = x/y, arg2/arg3 = width/height, all in fine units (>>3 = tiles).

Args:
  0. x (fine)
  1. y (fine)
  2. width (fine)
  3. height (fine)

### `op 689` — ResetMonsterSpawns()
*handler:* `Script_VMOp_ResetMonsterSpawnTrackerForPlayer`

Reset the monster-spawn tracker for the player.

## Quests

### `op 238` — QueryQuestNpcsAvailable(max distance, primary npc, other npc …)
*handler:* `Quest_AreAllNpcsAvailableAndWithinDistance`

Read 1 iff a primary NPC and all listed NPCs are available (not busy/sleeping schedule codes 13/25, not already mid-event, not inaccessible) AND each listed NPC is within a max distance of the primary — the quest-event group gate. arg0 = max distance, arg1 = primary npc (char id, <48), arg2+ = the other npc ids (their count is implied by the arg count — there is no explicit count arg). Writes 1/0 to reg0. Like op 240 but also requires the NPCs aren't already mid-event.

Args:
  0. max distance
  1. primary npc
  2. other npc …

### `op 239` — QueryQuestNpcsAvailable(max distance, primary npc, other npc …)
*handler:* `Quest_AreAllNpcsAvailableAndWithinDistance`

Alias of op 238 (same handler): 1 iff the quest's NPCs are all free and gathered.

Args:
  0. max distance
  1. primary npc
  2. other npc …

### `op 507` — PopulateNpcQuestRequest(target item id, count, category alt …)
*handler:* `Quest_PopulateNpcSlot`

Fill the current NPC's daily quest-request slot with a 'bring me [item]' request (into g_npcDailyRequestArray). arg0 = target item id (0 = auto-pick from the daily wanted list), arg1 = required count (0 = random 1-4), further args = category ids for alternate acceptable items. Writes success to the VM output. The base runtime quest generator; the PopulateQuestKindN ops are its templated variants.

Args:
  0. target item id (0=auto)
  1. count (0=random)
  2. category alt …

### `op 508` — PopulateQuestKind2RandomAlts()
*handler:* `Script_VMOp_PopulateQuestRequestKind2WithRandomCats`

Populate the current NPC's daily quest-request slot using request template KIND 2 (With Random Cats). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 509` — PopulateQuestKind2RandomAlts(item id, template param, template param, alt category seed …)
*handler:* `Script_VMOp_PopulateQuestRequestKind2WithRandomCats`

Populate the current NPC's daily quest-request slot using request template KIND 2, whose alternate objective items are rolled AT RANDOM from shop-category tables ('cats' in the old name meant categories, not animals: Shop_RollByCategoryFromTable re-rolls each seed until the result differs from the main item; up to 4 alternates). arg0 = objective item id; then two template params; trailing args = alternate category seeds. Distinct from the literal-alternates (slot 208) and chained-random (slot 209) siblings. See docs/23.

Args:
  0. item id
  1. template param (byte4)
  2. template param (byte5)
  3. alt category seed …

### `op 510` — PopulateQuestKind2WithLiteralAlternates()
*handler:* `Script_VMOp_PopulateQuestRequestKind2WithLiteralAlternates`

Populate the current NPC's daily quest-request slot using request template KIND 2 (With Literal Alternates). A runtime quest generator whose alternate objective items are the EXPLICIT literal item ids passed as args (stored verbatim — NO random category roll). See docs/23.

### `op 511` — PopulateQuestKind3TwoItemsRandomCats()
*handler:* `Script_VMOp_PopulateQuestRequestKind3TwoItemsRandomCats`

Populate the current NPC's daily quest-request slot using request template KIND 3 (Two Items Random Cats). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 512` — PopulateQuestKind3TwoItemsRandomCats()
*handler:* `Script_VMOp_PopulateQuestRequestKind3TwoItemsRandomCats`

Populate the current NPC's daily quest-request slot using request template KIND 3 (Two Items Random Cats). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 513` — PopulateQuestKind4ChainedRandom()
*handler:* `Script_VMOp_PopulateQuestRequestKind4ChainedRandom`

Populate the current NPC's daily quest-request slot using request template KIND 4 (Chained Random). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 514` — PopulateQuestKind4ChainedRandom()
*handler:* `Script_VMOp_PopulateQuestRequestKind4ChainedRandom`

Populate the current NPC's daily quest-request slot using request template KIND 4 (Chained Random). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 515` — PopulateQuestKind4Byte4_1LiteralAlts(target item id, param, alt item id …)
*handler:* `Script_VMOp_PopulateQuestRequestKind4Byte4_1LiteralAlts`

Populate the current NPC's daily quest-request slot using request template KIND 4 (Byte4_1 Literal Alts). A runtime quest generator whose alternate objective items are the EXPLICIT literal item ids passed as args (stored verbatim — NO random category roll). See docs/23.

Args:
  0. target item id
  1. param (byte5)
  2. alt item id …

### `op 516` — PopulateQuestKind5SimpleNoAlts()
*handler:* `Script_VMOp_PopulateQuestRequestKind5SimpleNoAlts`

Populate the current NPC's daily quest-request slot using request template KIND 5 (Simple No Alts). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 517` — PopulateQuestKind5SimpleNoAlts(item id)
*handler:* `Script_VMOp_PopulateQuestRequestKind5SimpleNoAlts`

Populate the current NPC's daily quest-request slot using request template KIND 5 (Simple No Alts). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

Args:
  0. item id

### `op 518` — PopulateQuestKind6TwoArgsNoItem()
*handler:* `Script_VMOp_PopulateQuestRequestKind6TwoArgsNoItem`

Populate the current NPC's daily quest-request slot using request template KIND 6 (Two Args No Item). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 519` — PopulateQuestKind7CraftRecipeExpose()
*handler:* `Script_VMOp_PopulateQuestRequestKind7CraftRecipeExpose`

Populate the current NPC's daily quest-request slot using request template KIND 7 (Craft Recipe Expose). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 520` — PostQuestGoalNumber(goal number, reward item ids)
*handler:* `Script_VMOp_PopulateQuestRequestKind8_GoalNumberLiteralRewards`

Post a request-box GOAL-NUMBER quest (slot kind 8): an objective with NO target item where the player must reach a number — a skill level, an upgrade level, a tamed-monster count, a craft count. arg0 = the goal number shown to the player (display only: completion is checked by the request scene itself via query ops / em conditions, never by slot progress); further args = LITERAL reward item ids written verbatim into reward_items[0..3] (stops at the first 0; no category roll). Also binds the posted slot to the script task's reward-template pointer (task+136) so the accept/complete/reward-popup ops that follow read this quest. All 6 retail uses are Eliza tutorial requests in bank 210, e.g. (20,3000) = 'Raise Skill Levels!' (any skill >= 20), (15,1052 Rush Attack) = 'Upgrade Weapons!', (5,0) = 'Befriend Monsters!'. IDA-verified 2026-09-01; formerly 'PopulateQuestKind8BackrefLiteralAlts' (the 'alternate objective items' reading was wrong — the literals are the REWARDS).

Args:
  0. goal number (level/count to reach)
  1. reward item ids (variadic, literal)

### `op 521` — PopulateQuestKind9BackrefLiteralAlts()
*handler:* `Script_VMOp_PopulateQuestRequestKind9BackrefLiteralAlts`

Populate the current NPC's daily quest-request slot using request template KIND 9 (Backref Literal Alts). A runtime quest generator whose alternate objective items are the EXPLICIT literal item ids passed as args (stored verbatim — NO random category roll). See docs/23.

### `op 522` — PopulateQuestKind10BackrefRandomCats(category id …)
*handler:* `Script_VMOp_PopulateQuestRequestKind10BackrefRandomCats`

Populate the current NPC's daily quest-request slot using request template KIND 10 (Backref Random Cats). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

Args:
  0. category id …

### `op 523` — PopulateQuestKind10BackrefLiteralAlts(alt item id …)
*handler:* `Script_VMOp_PopulateQuestRequestKind10BackrefLiteralAlts`

Populate the current NPC's daily quest-request slot using request template KIND 10 (Backref Literal Alts). A runtime quest generator whose alternate objective items are the EXPLICIT literal item ids passed as args (stored verbatim — NO random category roll). See docs/23.

Args:
  0. alt item id …

### `op 525` — QuestOnComplete()
*handler:* `Quest_OnComplete`

Run the quest-completion handler for the current request — award friendship / rewards and mark the request done. Fired when the player fulfils an NPC's request.

### `op 528` — QueryQuestRewardItem(quest id, reward index)
*handler:* `Script_VMOp_QueryQuestRewardItemAt`

Read one reward item id of a quest template into the VM output: returns the u16 at g_npcQuestRewardTemplates_12u16PerQuest[quest_id * 12 + index + 7]. TWO args: arg0 = quest (template) id, arg1 = reward slot index 0-3 (out-of-range index returns the default, 1). Corpus (8 uses, always 2 args): QueryQuestRewardItem(0, 0) gates SuppressRewardJingle + ShowQuestReward before QuestOnComplete.

Args:
  0. quest id
  1. reward index (0-3)

### `op 529` — ClearQuestRewardTemplates()
*handler:* `Script_VMOp_ClearAllNpcQuestRewardTemplates`

Clear all of the current NPC's staged quest-reward templates. No args. Used when abandoning or resetting a quest offer.

### `op 530` — CommitQuestAcceptance()
*handler:* `Quest_CommitAcceptance`

Commit the player's acceptance of the offered quest — moves it from 'preview' to an active daily request on the NPC. The second step of the two-step accept (preview → commit).

### `op 531` — QuestSceneTeardown()
*handler:* `Script_VMOp_QuestSceneTeardownAndClearRewards`

Tear down the quest-offer scene and clear its staged rewards. No args. Called when the request-board / quest dialogue closes.

### `op 532` — QueryNpcQuestPreview()
*handler:* `Script_VMOp_QueryCurrentInteractionNpcQuestPreview`

Read a preview of the current interaction NPC's available quest request into the VM output (so the dialogue can describe it before the player accepts). No args.

### `op 535` — QueryQuestRemainingByItem(item id)
*handler:* `Script_VMOp_QueryQuestRequestRemainingByItemId`

Read how many of an item are still needed across active quest requests into the VM output. arg0 = item id. For 'you still owe me N of these' dialogue.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 536` — RequestBoxFirstSubmit()
*handler:* `Script_VMOp_OnRequestBoxFirstSubmitAchievementAndScriptCallback`

Run the 'first request-box quest submitted today' pipeline: mark the active request claimed, unlock the submit achievements, play the shared + per-quest reward scenes, and schedule tomorrow's request reroll. Does nothing if already submitted today or there is no active quest. Takes no arguments. Pairs with RequestBoxClaimFinalize (op 549).

### `op 537` — PopulateQuestKind2WithRandomCats()
*handler:* `Script_VMOp_PopulateQuestRequestKind2WithRandomCats`

Populate the current NPC's daily quest-request slot using request template KIND 2 (With Random Cats). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 538` — PopulateQuestKind2WithRandomCats()
*handler:* `Script_VMOp_PopulateQuestRequestKind2WithRandomCats`

Populate the current NPC's daily quest-request slot using request template KIND 2 (With Random Cats). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 539` — PopulateQuestKind3TwoItemsRandomCats()
*handler:* `Script_VMOp_PopulateQuestRequestKind3TwoItemsRandomCats`

Populate the current NPC's daily quest-request slot using request template KIND 3 (Two Items Random Cats). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 540` — PopulateQuestKind3TwoItemsRandomCats()
*handler:* `Script_VMOp_PopulateQuestRequestKind3TwoItemsRandomCats`

Populate the current NPC's daily quest-request slot using request template KIND 3 (Two Items Random Cats). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 541` — PopulateQuestKind4ChainedRandom(target item id, param, param, category seed …)
*handler:* `Script_VMOp_PopulateQuestRequestKind4ChainedRandom`

Populate the current NPC's daily quest-request slot from template KIND 4. Despite the 'Chained' name, the chained-roll path is DEAD CODE: the per-iteration arg read always succeeds (index < count at 0x7ff7c1fd6b20), so each category-seed arg gets exactly one independent roll. arg0 = target item id, arg1/arg2 = template bytes 4/5, args[3..] = per-roll category seeds.

Args:
  0. target item id
  1. param (byte4)
  2. param (byte5)
  3. category seed … (one roll each)

### `op 542` — PopulateQuestKind4ChainedRandom()
*handler:* `Script_VMOp_PopulateQuestRequestKind4ChainedRandom`

Populate the current NPC's daily quest-request slot using request template KIND 4 (Chained Random). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 543` — PopulateQuestKind5SimpleNoAlts(item id)
*handler:* `Script_VMOp_PopulateQuestRequestKind5SimpleNoAlts`

Populate the current NPC's daily quest-request slot using request template KIND 5 (Simple No Alts). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

Args:
  0. item id

### `op 544` — PopulateQuestKind5SimpleNoAlts()
*handler:* `Script_VMOp_PopulateQuestRequestKind5SimpleNoAlts`

Populate the current NPC's daily quest-request slot using request template KIND 5 (Simple No Alts). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 545` — PopulateQuestKind6TwoArgsNoItem()
*handler:* `Script_VMOp_PopulateQuestRequestKind6TwoArgsNoItem`

Populate the current NPC's daily quest-request slot using request template KIND 6 (Two Args No Item). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 546` — PopulateQuestKind7CraftRecipeExpose()
*handler:* `Script_VMOp_PopulateQuestRequestKind7CraftRecipeExpose`

Populate the current NPC's daily quest-request slot using request template KIND 7 (Craft Recipe Expose). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 547` — PopulateQuestKind10BackrefRandomCats()
*handler:* `Script_VMOp_PopulateQuestRequestKind10BackrefRandomCats`

Populate the current NPC's daily quest-request slot using request template KIND 10 (Backref Random Cats). A runtime quest generator: rolls the objective item(s)/counts from the request template (plus alternate items from categories where this shape has them). See docs/23. Args are template-specific (item ids and category ids).

### `op 549` — RequestBoxClaimFinalize()
*handler:* `Script_VMOp_OnRequestBoxQuestClaimedFinalize`

Finalize and clean up the request-box reward claim (counterpart to op 536): set the completion flags, unlock the reward achievements, dispatch the reward scenes, reset the throw queue, refresh every NPC's schedule, clear all NPCs' request state, award prince points, and unregister the reroll callback. Takes no arguments -- the handler (Script_VMOp_OnRequestBoxQuestClaimedFinalize) reads only the implicit scene state; the corpus emits it with zero operands (cnt=0 in all occurrences).

## Scene flow / control

### `op 1` — SetSceneCtxBit3FromArg(value)
*handler:* `Script_VMOp_SetContextBit8FromArg`

Copies bit 0 of arg into bit 3 (0x8) of the scene ctx's control field at +120. `ctx[+120] = (ctx[+120] & ~8) | ((arg & 1) << 3)`. Author use unknown; likely a scene mode flag toggle.

Args:
  0. value

### `op 2` — Wait(duration)
*handler:* `Script_VMOp_WaitUnitsAndAdvanceReaction`

WAIT — pause the scene for a scripted duration. The one argument is a TIME in script units: 200 units = 1 frame, so 12000 = 1 second, 6000 = 0.5 s, 3000 = 0.25 s (the corpus's four most common values are exactly these). Any value 1..200 yields exactly one frame — `Wait(1)` is the idiomatic single-frame yield. This is the single most common pacing op (5,529 uses). Two traps, both engine-verified: the argument's expression KIND must be 0 (a computed expression — a plain literal is silently ignored, which is why the compiler always emits waits as expressions), and there must be EXACTLY one argument. The old name 'EndReactionAndJump' described a side call (Quest_OnReactionDispatched_AdvanceState), not the behaviour — IDA-verified as the wait primitive (vm[+120] = units, state -> WAITING; RF4S.exe+0x1FAB50).

Args:
  0. duration (units; 200 = 1 frame, 12000 = 1 s)

### `op 3` — WaitReset(duration)
*handler:* `Script_VMOp_EndReactionResetAndWait`

End the current quest-reaction beat and wait: signals the scene controller idle (sceneCtx+872->child[+24][+116] = 1, the same write EndDialogue does), advances the quest-reaction dispatch state (Quest_OnReactionDispatched_AdvanceState), then - if the script task is in run-state 4 - writes arg0 into the task's wait field (+120, state 4->2), i.e. the same duration mechanism as Wait. Same units as Wait (200 = 1 frame); retail passes durations like 1 (minimal yield) or 6000 (30 frames). 267 retail uses, always 1 arg.

Args:
  0. duration (units; 200 = 1 frame)

### `op 4` — ConditionalJump(jump target)
*handler:* `Script_VMOp_ConditionalJump`

Redirect the VM to a target pc when the scene is in the pending-reaction state (ctx state 4) — a lightweight conditional jump used inside quest-reaction sequences (does not advance any quest state). arg0 = target.

Args:
  0. jump target

### `op 91` — SetSceneBit(bit index, on)
*handler:* `Script_VMOp_SetSceneBit404`

Set or clear bit [arg0] of the scene's local bit-field (scene context +404): arg1 non-zero sets the bit, zero clears it. Scene-local scratch flags for a scene script's own bookkeeping.

Args:
  0. bit index
  1. on (0/1)

### `op 198` — WaitForPlayerEffect()
*handler:* `Script_VMOp_QueryPlayerEffectActive`

Block the cutscene VM until the current player effect/animation task finishes running. Takes no arguments.

### `op 204` — SleepInBed(cinematic)
*handler:* `Bed_TickSleepSequence`

Run the go-to-bed / sleep-to-next-day sequence. arg0 != 0 (retail always 1): the full blocking cinematic FSM - bed anim + voice line, spouse/child walk to the bedside, fade to black, Player_SleepInBed (save snapshot + Day_OnAdvance day rollover), position restore, fade back in, morning BGM/weather; pressing the skip button fast-forwards the fades. arg0 == 0: calls Player_SleepInBed immediately with no cinematic. Dev menu 'Sleep' passes [1].

Args:
  0. cinematic (1=full sequence, 0=instant day advance)

### `op 230` — ReleaseNpcLocks(release mode, participant npc id …)
*handler:* `Cutscene_ReleaseNpcLocksAndRefreshFromSchedule`

Release every NPC AI lock/placement from a prior scene: restores normal AI bits, refreshes each placed NPC from its schedule (per bit in sceneCtx+352), and clears the placed-actor reservation mask. Despite the old 'CutsceneEnd' name, corpus tracing shows it typically runs at the START of scenes as a reset-prologue (49% of uses in the first decile; only 2% near the end), immediately before placement/teleport ops — the real lifecycle is RELEASE -> PLACE -> LOCK -> RUN. arg0 = release mode (0 = leave AI-locked, non-zero = restore normal AI), then the participant NPC ids -- there is no count argument, the handler loops over args 1..argc-1 (Cutscene_ReleaseNpcLocksAndRefreshFromSchedule reads argc as the count, verified 2026-09-23); participants are excluded and unlock via their own dialogue/anim completion).

Args:
  0. release mode (0=stay locked)
  1. participant npc id …

### `op 231` — ReleaseNpcLocks(release mode, participant npc id …)
*handler:* `Cutscene_ReleaseNpcLocksAndRefreshFromSchedule`

Alias of op 230 (same handler): release NPC locks and refresh each flagged NPC from its schedule — restores normal-AI bits, calls Npc_RefreshFromSchedule for every bit in the sceneCtx+352 mask, then clears the mask. Despite the old 'CutsceneEnd' name, corpus timing shows it typically runs at scene START as a reset/prologue before placement ops (49% of uses in the first decile of their scene, only 2% near the end): the real lifecycle is RELEASE -> PLACE -> LOCK -> RUN. args: release mode (0 = stay locked), then participant npc ids (no count arg -- the handler uses argc) (participants are excluded from immediate release).

Args:
  0. release mode (0=stay locked)
  1. participant npc id …

### `op 242` — SetSceneFlag0x200()
*handler:* `Script_VMOp_SetSceneFlag0x200`

Set bit 0x200 in the scene ctx's result/control field at [+116] (if ctx+32 is non-null; +116 is the same field Script_VMStep sets to 1 on halt). In the corpus (703 uses) it is almost always `BR_Z(guard) -> SetSceneFlag0x200 -> END` -- set CONDITIONALLY at the very end of a scene branch, right before the scene ends. So it marks a scene OUTCOME bit the caller reads after the scene returns (e.g. 'this branch was taken / handled'). The gating guard is usually a per-NPC sub-event flag (`FLG_SUB_T_*`) or `FLG_JUST_MARRIED_MODE`, so in practice it flags a marriage / sub-event scene branch as consumed. The exact outcome bit is not pinned, but it is set at scene-EXIT, not during dialogue -- an earlier 'blocks input while dialogue is active' guess was wrong, contradicted by the usage pattern.

### `op 285` — SetSceneReadyFlag(mode, (ignored by handler))
*handler:* `ScriptVMOp_SetScriptStateBit72_1_OnArgZero`

Set a scene-state control bit (scene state +72 bit 0x1) when arg0 is 0 — a low-level 'wait / ready' marker the scene loop checks. arg0 = mode (0 sets it).

Args:
  0. mode (0 = set flag)
  1. (ignored by handler)

### `op 332` — PlayScriptedBeat(actor ctx, arg1, arg2, kind id)
*handler:* `ScriptAction_BeginConfiguredAction_PruneUiEvents`

Launch a 4-param scripted beat / cutscene event on an actor. Writes the four u16 args into the action task's config slots (+60..+66) and commits (bit 0x80 at +56). arg3 (kind_id) drives a range gate on +57: 1000-1099 -> bit 0 (credit-roll-scale variant), 100-999 -> bit 1 (scripted-event variant), anything else INCLUDING 1100+ -> both clear (decompile: (kind-100) <= 0x383 = 999 max). Also clears g_gameGlobalsSlotTable entry-4 low nibbles, clears sceneControlFlags bit 0x100000, flags the current dialogue task, and - only when kind_id != 0 - prunes pending g_gameEventQueue events of types 20/24/28/30 (mask 0x41100000). Vanilla: 'Ackna Battle' (globalvar[0x2D5], 403, 453, 0), 'Ending (Plaza 2nd Run)' (globalvar[0x30], 8, 347, 130), 'Credit Roll 3' (globalvar[0x94], -96, 0, 1200).

Args:
  0. actor ctx
  1. arg1
  2. arg2
  3. kind id

### `op 333` — BeginBeat2()
*handler:* `ScriptAction_BeginConfiguredAction_Variant1`

Begin a scripted scene action (variant; caches a game-flag value).

### `op 337` — WaitForFade()
*handler:* `Script_VMOp_WaitForFadeComplete`

Block the scene until the current dual-screen fade started by FadeScreen (op 334) completes.

### `op 370` — SetSceneStateBit1()
*handler:* `Script_VMOp_SetSceneFlagBit1At120`

Set scene-state flag bit 1 (scene context +120) — a scene-local marker a scene script sets for its own logic. Takes no arguments.

### `op 375` — TriggerWorldAction(action id)
*handler:* `Script_VMOp_TriggerWorldInteractionAction`

Fire a World_DispatchInteractionEvent by action id (see the TriggerWorldInteractionAction picker for the full list). Common ids: 1 = Save menu, 2 = Load menu (dev-menu ONLY -- crashes mid-gameplay), 3 = Message Board, 11 = Calendar, 12 = Storage, 23 = Fridge, 25 = BackupSaveNow (autosave), 45 = Bookshelf, 53 = Shipping Bin, 54 = Safe, 55 = Wardrobe, 56 = Toolbox, 58 = Forge, 71 = Crafting.

Args:
  0. action id
     - `1` = Save
     - `2` = Load
     - `3` = MessageBoard
     - `4` = NameEntry_Hero
     - `5` = NameEntry_Farm
     - `6` = NameEntry(subId=15)
     - `7` = NameEntry(subId=16)
     - `8` = NameEntry(subId=17)
     - `9` = NameEntry(subId=18)
     - `10` = ShippingHistory
     - `11` = Calendar
     - `12` = Storage
     - `14` = Chemistry
     - `16` = Cooking
     - `17` = Cook_FryingPan
     - `18` = Cook_Pot
     - `19` = Cook_Oven
     - `20` = Cook_Mixer
     - `21` = Cook_Steamer
     - `22` = Cook_Knife
     - `23` = Fridge
     - `24` = MonsterManagement
     - `25` = BackupSaveNow
     - `26` = BackupSaveNow
     - `27` = (cleanup only)
     - `28` = NameEntry_BarnA
     - `29` = NameEntry_BarnB
     - `30` = NameEntry_BarnC
     - `31` = NameEntry_BarnD
     - `32` = NameEntry_BarnE
     - `33` = NameEntry_BarnF
     - `34` = NameEntry_BarnG
     - `35` = NameEntry_BarnH
     - `36` = NameEntry_BarnI
     - `37` = NameEntry_BarnJ
     - `38` = NameEntry_Child0
     - `39` = NameEntry_Child1
     - `40` = NameEntry_Child2
     - `41` = NameEntry_Child3
     - `42` = NameEntry_Child4
     - `43` = Posts
     - `44` = ScriptAction_10(v3)
     - `45` = Bookshelf
     - `51` = MonsterFarmMenu
     - `52` = (word write nop)
     - `53` = ShippingBin
     - `54` = Safe
     - `55` = Wardrobe
     - `56` = Toolbox
     - `57` = MonsterFarm(focused)
     - `58` = Forge
     - `59` = ScriptAction_41
     - `60` = ScriptAction_42
     - `61` = ScriptAction_43
     - `62` = ScriptAction_44
     - `63` = ScriptAction_46
     - `64` = ScriptAction_47
     - `65` = ScriptAction_45
     - `66` = ScriptAction_48
     - `67` = ScriptAction_53
     - `68` = ScriptAction_50
     - `69` = ScriptAction_51
     - `70` = ScriptAction_52
     - `71` = Crafting
     - `72` = ScriptAction_54
     - `73` = ScriptAction_55
     - `74` = ScriptAction_08
     - `75` = Shop_WeaponFarmTool
     - `76` = Shop_Accessory
     - `77` = Shop_ExcavatedEquipment
     - `78` = Shop_HospitalMedicine
     - `79` = Shop_Interaction_4F
     - `80` = Shop_Flower
     - `81` = Shop_BaseIds_19_20_a
     - `82` = Shop_Furniture
     - `83` = Shop_Ability
     - `84` = Shop_Magic
     - `85` = Shop_Jewel
     - `86` = Shop_SakuTuner
     - `87` = Shop_Yue
     - `88` = Shop_Restaurant
     - `89` = Shop_BaseId_57
     - `90` = BirthdayEntry

### `op 376` — BeginShopkeeperInteraction(shopkeeper npc, shop id, mode)
*handler:* `Script_VMOp_BeginCalendarContextualInteraction`

**'Try to open shopkeeper NPC's shop, gated by their schedule.'** Same underlying dispatcher as TriggerWorldAction (op 375, World_DispatchInteractionEvent) but adds a **day-of-week eligibility check** on the shopkeeper's schedule first. Corpus proof: **all 192 vanilla call sites in rf3.mc pass a shop id (kinds 75-89)** — none use anything else. \n\nThe switch on arg 0 dispatches on the SHOPKEEPER's NPC ID and maps each to their day-off + a kind-override table: 0 (generic/anon) -> kind 22 / day 6 (Sat); 6 (Bado) / 9 (Arthur) / 10 (Porcoline) -> passthrough / day 0 (Sun); 8 (Dylas) -> kind 23 if GF_FLG_DIRUS_FRIENDLY set, else 8 / day 0 (Sun); 11 (Xiao Pai) / 12 (Lin Fa) -> passthrough / day 6 (Sat); 13 (Amber) -> kind 25 if GameFlag 875 packed, else 13 / day 5 (Fri); 14 (Illuminata) -> passthrough / day 5 (Fri); 15 (Doug) -> kind 24 if Scene_EvalConditionByIdA(0x2D) true, else 15 / day 5 (Fri); 16 (Blossom) -> passthrough / day 5 (Fri); 17 (Dolce) / 18 (Jones) / 19 (Nancy) -> passthrough / day 1 (Mon); 22/23 (Son/Daughter) -> kind 26 / day 6 (Sat); 25 -> kind 21 / day 6 (Sat); default -> kind 26 / day 6 (Sat). \n\nDay-of-week check: today = `(g_calendarTask.cal_inner[+12] - 1) % 6`. If matched -> eligible (`g_interactionDailyEligible = 1`, `g_interactionDailyRollPassed = 0`). Else eligible=0 and roll a **deterministic MMIX-LCG (~1/63 chance)** using (shop_id + 0x4000, g_calendarDailyRandomSeed, calendar-snapshot) to set DailyRollPassed. The downstream shop task reads those globals to decide 'shop open normally' vs 'bonus lucky day' vs 'closed today, show closed-dialog instead'. Then World_DispatchInteractionEvent fires with arg 1 (shop id) in a1+25. arg 2 = mode (always 0 in vanilla).

Args:
  0. shopkeeper npc
     - `0` = Anonymous
     - `6` = Bado
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `22` = Son
     - `23` = Daughter
     - `25` = Guest25
  1. shop id
     - `75` = Shop_WeaponFarmTool
     - `76` = Shop_Accessory
     - `77` = Shop_ExcavatedEquipment
     - `78` = Shop_HospitalMedicine
     - `79` = Shop_Interaction_4F
     - `80` = Shop_Flower
     - `81` = Shop_BaseIds_19_20_a
     - `82` = Shop_Furniture
     - `83` = Shop_Ability
     - `84` = Shop_Magic
     - `85` = Shop_Jewel
     - `86` = Shop_SakuTuner
     - `87` = Shop_Yue
     - `88` = Shop_Restaurant
     - `89` = Shop_BaseId_57
  2. mode

### `op 421` — SetupPendingInteraction(action id, flag byte, extra param …)
*handler:* `Script_VMOp_SetupPendingInteractionRecord`

Stage a 'pending interaction record' — a scratch buffer that the next item-give / interaction op (GivePlayerItem, AttachItemVisual) reads to apply extra params (e.g. a just-crafted item's runes, a specific action). arg0 = action id, arg1 = flag byte, then up to 6 extra u16 params.

Args:
  0. action id
  1. flag byte
  2. extra param …

### `op 422` — SetupPendingInteractionV2(action id, flag byte, extra param …)
*handler:* `Script_VMOp_SetupPendingInteractionRecord_Variant2`

Variant of op 421 (distinct handler Script_VMOp_SetupPendingInteractionRecord_Variant2, same purpose): stage the pending-interaction record for the next item/interaction op.

Args:
  0. action id
  1. flag byte
  2. extra param …

### `op 524` — CommitThrowQueue()
*handler:* `Script_VMOp_PromoteAllPendingThrowEntriesToActive`

Promote every pending entry in the dungeon 'throw'/delivery queue from pending to active, committing a batch of populated entries at once. Only takes effect while in a dungeon area. Takes no arguments.

### `op 548` — CommitThrowQueue()
*handler:* `Script_VMOp_PromoteAllPendingThrowEntriesToActive`

Promote every pending entry in the dungeon 'throw'/delivery queue to active (duplicate of op 524). Only takes effect in a dungeon area. Takes no arguments.

### `op 551` — ResetThrowQueue()
*handler:* `Script_VMOp_ResetGeneralThrowQueue`

Clear the dungeon 'throw'/delivery queue: reset the entry count to 0 and wipe all 20 entry templates. Takes no arguments.

### `op 559` — StartFestivalContest(contest)
*handler:* `Script_VMOp_SpawnFestivalSceneEvent`

Start a festival contest mini-event: spawns the SceneEvent lifecycle task (SceneEvent_TickLifecycleStateMachine) and BLOCKS the VM (ctx+116 |= 0x10000) until the contest ends. arg0 = contest subtype -> task+4: 1=ONI, 2=EAT (eating contest), 3=MOKO, 4=MATO (target shooting), 5=YUKI, 6=QUIZ, 7=PET. Backs up the packed festival-status register (REG_FES_STATUS) into the task, restored when the contest completes. The old 'return-to-town prompt' reading was wrong.

Args:
  0. contest (1=oni,2=eat,3=moko,4=mato,5=yuki,6=quiz,7=pet)

### `op 560` — StageSceneNpcs()
*handler:* `Script_VMOp_StageSceneNpcsAndExpose4Ids`

At cutscene start, stage the scene's NPCs + companions and expose the 4 participating NPC ids into the VM output slots (so the script can reference them). Marks the villagers as 'in scene'. No args. A scene-setup op.

### `op 574` — ShuffleSceneBuffer(count)
*handler:* `Script_VMOp_SeedFisherYatesShuffleInSceneBuf`

Fill the scene's shuffle buffer with a random permutation of [0 .. arg0-1] (arg0 capped at 64), using the save-scummable MMIX RNG (Fisher-Yates). Scripts use this to randomize order — e.g. pick NPCs/events in a random sequence. Read entries back with GetShuffleValue (op 575).

Args:
  0. count (1-64)

### `op 633` — ResetActionEventId()
*handler:* `Script_VMOp_ResetLastDispatchedActionEventId`

Clear the last-dispatched action-event id (resets the action-trigger bookkeeping). Takes no arguments.

### `op 634` — SetActionTriggerByte(index, value)
*handler:* `Script_VMOp_SetActionTriggerByteByIdx`

Set one of the scene's 3 action-trigger bytes (ctx state, index 0-2). arg0 = index (0-2), arg1 = value. Low-level scene flag used to gate scripted actions; read back with GetActionTriggerByte (op 635).

Args:
  0. index (0-2)
  1. value

### `op 682` — SetSceneFlag400(phase)
*handler:* `Script_VMOp_SetSceneFlagAt400FromMode3`

Set the scene context's +400 tristate field: arg must be 0, 1, or 2 and is written directly (scene+400 = arg). Purpose of the field is unconfirmed — likely a fade-direction or scene-phase indicator. One argument; single corpus use (bank 223).

Args:
  0. phase (0/1/2)

### `op 697` — ReturnToTitle()
*handler:* `Script_VMOp_BeginReturnToTitleViaAppRelaunch`

Kick off the return-to-title sequence via app relaunch. Dev menu uses this after FadeScreen(16, 1500) + WaitForFade. No args.

## Queries

### `op 81` — QueryActorMotionState(actor)
*handler:* `Script_VMOp_QueryActorMotionState`

1 while the actor is mid-motion — its motion-state code (motion+42 & 0x7C) is NOT the settled/idle value 0x10; 0 once settled. arg0 = actor (matched against the scene's two participant slots). Wait-for-move-done predicate.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 82` — QueryActorMotionState(actor)
*handler:* `Script_VMOp_QueryActorMotionState`

Alias of op 81 (same handler): 1 while the actor is mid-motion, 0 when settled.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 105` — QueryCalendarEventStub(event id)
*handler:* `Script_VMOp_QueryCalendarEvent`

Always writes 0 to the VM output — the intended calendar-event lookup is stubbed on the PC port (for arg >= 0x30 the search over g_calendarEventMng runs but its result is discarded). arg0 = event id (consumed by the arg decoder). Treat as returning 0.

Args:
  0. event id (consumed; result discarded)

### `op 113` — QueryActorRotating(actor)
*handler:* `Script_VMOp_QueryActorRotating`

1 while the actor is still turning toward its target facing (current rotation != target rotation); 0 once the turn has settled. arg0 = actor (char id, 0 = player). Pair with SetActorFacingAngle / TurnActorToFaceTarget to wait for the turn.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 114` — QueryActorRotating(actor)
*handler:* `Script_VMOp_QueryActorRotating`

Alias of op 113 (same handler): 1 while the actor is still turning, 0 when settled.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 129` — QueryActorAnimBusy(actor, ignored actor …)
*handler:* `Script_VMOp_QueryNpcAnimDone`

1 while the actor is still playing its scripted action animation OR turning; 0 once idle/done. arg0 = actor (char id, 0 = player, which delegates to QueryPlayerTurnBusy). Pair with PlayActorAnim (op 133) to wait for the anim to finish. (Handler is named 'AnimDone' but returns busy=1.) ONLY arg0 IS READ: 72 of the 2,072 shipped statements pass extra actors, but Script_VMOp_QueryNpcAnimDone never looks past arg0 (verified 2026-09-23), so the wait ends as soon as the FIRST actor is idle. To wait on several actors, use one statement per actor.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. ignored actor … (not read by the engine)

### `op 130` — QueryActorAnimBusy(actor, ignored actor …)
*handler:* `Script_VMOp_QueryNpcAnimDone`

Alias of op 129 (same handler): 1 while the actor's anim/turn is still playing. Only arg0 is read; extra actors are ignored.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. ignored actor … (not read by the engine)

### `op 131` — QueryActorBeyondRange(actor, range)
*handler:* `ScriptVM_Op_QueryEntityBeyondRangeOfTarget`

1 while the actor is FARTHER than [range] tiles from its target marker (the player checks a global target position; an NPC checks its own move target); 0 once within range. arg0 = actor (char id, 0 = player), arg1 = range in tiles. Wait-until-arrived predicate. (Handler is named 'InRange' but returns 1 when far.)

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. range (tiles)

### `op 132` — QueryActorBeyondRange(actor, range)
*handler:* `ScriptVM_Op_QueryEntityBeyondRangeOfTarget`

Alias of op 131 (same handler): 1 while the actor is beyond [range] of its target.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. range (tiles)

### `op 135` — QueryActorTilePosition(actor)
*handler:* `ScriptVMOp_QueryActorWorldPositionAsTile`

Read an actor's current tile position: writes X and Y (tiles) to the VM output slots for a following read. arg0 = actor (char id, 0 = player). Falls back to the NPC's backup position if its actor isn't spawned.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 136` — QueryActorTilePosition(actor)
*handler:* `ScriptVMOp_QueryActorWorldPositionAsTile`

Alias of op 135 (same handler): read an actor's tile X/Y into the VM output slots.

Args:
  0. actor (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 137` — QueryNpcLoadedAndActive(npc)
*handler:* `ScriptVMOp_QueryNpcExistsLoadedAndNotIdle`

1 if the NPC exists, has a live actor, and is NOT in its idle state (i.e. is currently doing something); 0 otherwise. arg0 = npc (char id, <48). Gate scripted branches on whether an NPC is present and active.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 138` — QueryNpcLoadedAndActive(npc)
*handler:* `ScriptVMOp_QueryNpcExistsLoadedAndNotIdle`

Alias of op 137 (same handler): 1 if the NPC is loaded and active.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 145` — QueryPlayerTurnBusy()
*handler:* `Script_VMOp_QueryPlayerTurnBusy`

1 while the player is still turning / settling their facing (or in a scripted-busy state); 0 when idle. No args. Wait for the player's turn to finish before the next beat.

### `op 148` — QueryPlayerFlag40000()
*handler:* `ScriptVMOp148_QueryPlayerFlag40000`

Query -> VM query register: 1 if the player has status/accessory-effect flag 0x40000, else 0.

### `op 152` — WaitPlayerScriptSync()
*handler:* `Script_VMOp_QueryPlayerScriptReady`

Blocking sync point, NOT a register query: it writes nothing to reg0 (branching on reg0 after it reads a stale value). The handler returns block/retry while the scene busy flag (sceneCtx+116 & 0x8000000) is clear AND the player's scene_node bit 8 is clear, and lets the script proceed once either is set. Shipped scenes place it between PlayerScriptedTalkAnim steps as an animation-phase sync. Exact flag polarity is engine-internal (the IDB notes it blocks while the player looks 'ready'). No args.

### `op 164` — QueryEventActorMoving(event key)
*handler:* `ScriptVMOp_CalendarEvent_QueryNpcTurnOrArrivalState`

1 while a spawned event actor is still walking OR turning; 0 once it has both arrived and settled its facing. arg0 = event key. The COMBINED wait predicate — op 179 checks only turning, this also checks arrival.

Args:
  0. event key

### `op 169` — WaitForEventActorReady(event key)
*handler:* `ScriptVMOp_QueryCalendarEventActorReadyOrInMidAction`

WAIT/barrier, not a query: blocks the scene (handler returns 1 = replay next frame) until the keyed event actor exists and its controller bit 0x8 is set (streamed in / action committed), then execution continues. arg0 = event key. Writes nothing to the VM output — pair it directly with the next event-actor op.

Args:
  0. event key

### `op 179` — QueryEventActorTurning(event key)
*handler:* `ScriptVMOp_QueryCalendarEventActorStillTurningTowardTarget`

1 while a spawned event actor is still turning toward its target facing (target != current); 0 once settled. arg0 = event key. Wait-for-turn predicate — the event-actor twin of QueryActorRotating (op 113).

Args:
  0. event key

### `op 182` — QueryEventActorTilePosition(event key)
*handler:* `ScriptVMOp_QueryCalendarEventActorWorldXY_Tiles`

Read a spawned event actor's current tile position: writes X and Y (tiles) to the VM output slots for a following read. arg0 = event key. The event-actor counterpart of QueryActorTilePosition (op 135).

Args:
  0. event key

### `op 195` — WaitCameraAtMark()
*handler:* `Script_VMOp_QueryCameraAtMarkAnchor`

BARRIER: block the scene until the CAMERA has arrived at the mark anchor set by SetCameraPosition/SetCameraTarget (ops 186/190) — per-axis |camera − anchor| <= 2048 Q12 = half a tile (Chebyshev). No args. This is what paces every scripted camera sweep: `SetCameraTarget(x, y, speed); WaitCameraAtMark()` holds until the pan lands. (The old name 'QueryPlayerMovedFromMark' followed the technical symbol; the IDB comparison is against g_cameraPosQ12, the CAMERA, not the player.)

### `op 196` — QueryPlayerMovedBeyondSnapshot(threshold)
*handler:* `Script_VMOp_QueryPlayerMovedBeyondDistFromAnchor`

Query -> VM register: 1 if the player's world position has moved more than `arg << 12` (Q4.12 tiles) from the last op-193 snapshot in EITHER axis; 0 otherwise. Pair with op 193 as a 'watch for the player leaving a set radius' construct.

Args:
  0. threshold

### `op 213` — GetPlayerPosition()
*handler:* `Script_VMOp_GetPlayerPosition`

Read the player's current tile position into the VM output — X to output slot 0, Y to slot 1, and a 'valid' flag (1) to slot 2. No args. Reference the player's location in a scene.

### `op 216` — QueryNpcInCurrentArea(npc id)
*handler:* `Script_VMOp_QueryNpcInCurrentArea`

Query -> VM register: `Npc_IsInCurrentArea(npc_id)` -- 1 if the given NPC's actor is spawned in the currently-loaded room/area, else 0. Distinct from op 282 `QueryNpcPresent` which checks the spawn+visible actor+568 flag.

Args:
  0. npc id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 218` — QueryNpcFriendshipLevel(npc)
*handler:* `Script_VMOp_QueryNpcFriendshipLevel`

Read an NPC's friendship LEVEL (not raw points) into the VM output slot. arg0 = npc (char id); 0 uses the NPC the player is currently talking to. -1 if the NPC isn't found.

Args:
  0. npc (char id, 0=current)
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 219` — QueryNpcFriendshipLevel(npc)
*handler:* `Script_VMOp_QueryNpcFriendshipLevel`

Alias of op 218 (same handler): read an NPC's friendship level into the VM output.

Args:
  0. npc (char id, 0=current)
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 220` — QueryAllNpcsFriendship(npc, target level)
*handler:* `ScriptVMOp_QueryAllAvailableNpcsFriendshipMeetsTarget`

Read 1 iff an NPC's friendship level meets/exceeds [target]. arg0 = npc (char id), arg1 = target level. When arg0 = 0, instead checks that ALL story-available villagers meet the target (gated by story progress + the active festival). Gate town-wide events on overall affection.

Args:
  0. npc (char id, 0=all available)
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. target level

### `op 226` — QueryNpcScheduleId(npc)
*handler:* `Script_VMOp_QueryNpcScheduleId`

Read an NPC's current schedule id (which scheduled activity it's doing) into the VM output. arg0 = npc (char id). Quirk: arg0 = 0 returns the current INPUT-CONTEXT id instead of a schedule. Branch on what an NPC is up to right now.

Args:
  0. npc (char id, 0=input ctx)
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 227` — QueryNpcScheduleIsOneOf(npc, schedule id …)
*handler:* `ScriptVM_Op_QueryNpcCurrentScheduleIsOneOf`

Read 1 iff an NPC's current schedule id matches ANY id in the list. arg0 = npc (char id; 0 tests the PLAYER's scene/menu-state field, 22 the current child id). args[1..] = the schedule ids - there is NO count argument: the 'count' is the statement's own packed arg-count slot (engine 0x7ff7c1fbd9f0 reads it from the encoding, decomp-port confirmed 2026-09-01).

Args:
  0. npc (char id, 0=player, 22=current child)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. schedule id …

### `op 228` — QueryNpcScheduleIsOneOf(npc, schedule id …)
*handler:* `ScriptVM_Op_QueryNpcCurrentScheduleIsOneOf`

Alias of op 227 (same handler): 1 iff an NPC's schedule matches one of a list.

Args:
  0. npc (char id, 0=player, 22=current child)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. schedule id …

### `op 229` — QueryNpcAvailableFlagClear(npc id)
*handler:* `Script_VMOp_QueryNpcSlotFlag40Clear`

Query -> VM register: 1 if NPC's state word (npc[+20]) bit 0x40 is CLEAR, else 0. Bit 0x40 is presumably an 'is busy' or 'in scene' marker; the op returns TRUE when the NPC is FREE. Silently no-ops for npc id >= 48.

Args:
  0. npc id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 232` — QueryNpcHidden(npc)
*handler:* `Script_VMOp_QueryNpcHidden`

Read whether an NPC is hidden (1 = hidden, 0 = visible) into the VM output. arg0 = npc (char id). The query counterpart to HideNpc (op 233).

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 235` — QueryNpcSeenToggle(npc)
*handler:* `Script_VMOp_QueryNpcSeenToggle`

Read whether an NPC is interaction-eligible AND toggle its 'seen today' bit into the VM output. arg0 = npc (char id). Like QueryNpcInteractEligible (op 236) but with a fixed mode. Used to gate first-encounter dialogue.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 236` — QueryNpcInteractEligible(npc, mode)
*handler:* `Script_VMOp_QueryNpcInteractEligible`

Read whether an NPC is currently eligible to be interacted with (present, loaded, not busy) into the VM output, and toggle its 'seen' bit. arg0 = npc (char id), arg1 = mode. Used to gate first-interaction / talk dialogue.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. mode

### `op 237` — QueryNpcPairInteraction(subject npc, target npc, range)
*handler:* `ScriptVM_Op_QueryNpcInteractionEligibilityWithSubject`

Read whether one NPC can interact with another right now — close enough and hasn't already interacted with them today. arg0 = subject npc (char id), arg1 = target npc (char id), arg2 = range. For NPC-to-NPC greeting / pairing events.

Args:
  0. subject npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. target npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  2. range

### `op 240` — QueryNpcGroupPresentNearby(max distance, primary npc, other npc …)
*handler:* `Script_QueryNpcGroupPresentNearby`

Read 1 into reg0 iff a group of NPCs are all present and available (actor state != 13/25, not busy/inaccessible) and each within arg0 distance of the primary. arg0 = max distance, arg1 = primary npc (char id), remaining args = the other npc char ids -- there is NO count argument: the handler derives the group size from the statement's own arg count. The dominant 2-arg form (distance, npc) degenerates to a single-NPC 'present & available' check (self-distance 0). 5-arg form = primary + 3 others.

Args:
  0. max distance
  1. primary npc (char id)
  2. other npc …

### `op 241` — QueryNpcGroupPresentNearby(max distance, primary npc, other npc …)
*handler:* `Script_QueryNpcGroupPresentNearby`

Alias of op 240 (same handler): 1 iff a group of NPCs are gathered within range.

Args:
  0. max distance
  1. primary npc (char id)
  2. other npc …

### `op 245` — QueryGiftAffinity(npc id, item id)
*handler:* `Script_VMOp_QueryNpcGiftAffinity`

Query -> VM register: `Npc_GetGiftAffinityHashByItemAndCharId(npc_id, {item_id & 0x7FF})`. Returns the NPC's gift-affinity hash for the given item -- values like 'loved / liked / disliked / hated' as per rf3PresentNpc (see the gift preferences memory). item_id is masked to 11 bits (0..2047).

Args:
  0. npc id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 247` — QueryTileFacingTarget(actor A, target B)
*handler:* `ScriptVMOp_QueryTileOneStepBehindActorTowardTarget`

Compute the tile one step in front of target B along the line from A to B — where A should stand to be adjacent to and facing B. Writes X and Y (tiles) to the VM output slots. arg0 = actor A (char id, 0 = player), arg1 = target B (char id). If already adjacent, returns A's own tile. Used to line NPCs up for a conversation.

Args:
  0. actor A (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. target B (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 255` — QueryEntityActionStatus(entity)
*handler:* `ScriptVM_Op_QueryEntityActionStatusAndEventCode`

Read an entity's status + action-event codes into TWO VM output slots. arg0 = entity (char id, 0 = player; else resolved via the current interaction NPC's companion). Output +64 = status (0 idle / 1 busy / 2 talking / 3 low-HP / 4 talking-only); output +68 = action-event code (115..118) used to pick a follow-up dialogue reaction.

Args:
  0. entity (char id, 0=player)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 257` — QueryAllNpcsEligibleForComment(npc id …)
*handler:* `NpcAi_AllNpcsEligibleForFlavorComment`

Read 1 iff EVERY listed NPC is eligible to deliver an ambient flavor comment (present, not busy, in the current area, not story-gated). ALL-must-pass, not any: eligible_found starts at 1 and the FIRST failing candidate zeroes it; ids >= 0x30 are skipped (engine 0x7ff7c1fc07e0, decomp-port confirmed 2026-09-01). Variadic: each arg is one candidate char id; no count argument.

Args:
  0. npc id … (candidate char ids, variadic)

### `op 258` — QueryAllNpcsEligibleForComment(npc id …)
*handler:* `NpcAi_AllNpcsEligibleForFlavorComment`

Alias of op 257 (same handler): 1 iff EVERY candidate char id passed as an arg can deliver a flavor comment - ALL-must-pass (first failure zeroes the result), ids >= 0x30 skipped. The dominant corpus form passes a single candidate (reg0), where all/any coincide.

Args:
  0. npc id … (candidate char ids, variadic)

### `op 259` — QueryNpcRosterPresence(slot count, npc id …)
*handler:* `ScriptVM_Op_QueryNpcRosterPresenceByList`

Check which of the listed NPCs are currently rendered in the scene — writes a present/absent flag (1/0) for each into up to 10 consecutive VM output slots. arg0 = how many slots to fill, then the npc ids to test. Test which characters are on-stage before triggering interactions.

Args:
  0. slot count
  1. npc id …

### `op 260` — QueryActorHpWellness()
*handler:* `ScriptVMOp_QueryActorHpLowOrUnknownForDialogueBranch`

Read the current scene subject's HP wellness for a dialogue branch into the VM output: 0 = healthy (HP > 50%), 1 = low HP (≤ 50%), 2 = no combat stats. No args (uses the scene's subject actor). Drives 'Are you ok? You look hurt.' reactions.

### `op 262` — QueryCurrentInteractionNpc()
*handler:* `ScriptVMOp_QueryCurrentInteractionNpcCharId`

Read the char id of the NPC the player is currently talking to / interacting with into the VM output slot (0xFFFF if none). Use to branch a shared script on which NPC triggered it.

### `op 265` — QueryPlayerDeadOrCompanionScripted(mode)
*handler:* `Script_VMOp_QueryPlayerOrCompanionDowned`

Dual-mode query -> VM register based on arg: (arg != 0) writes 1 if the player is currently dead (vtable[+7] == Player_DeathTickCallback), else 0. (arg == 0) walks companions 0..1 and writes 1 if any companion has `companion[+460] == 11` with a null `[+304]` field (a 'scripted sequence in progress' state), else 0.

Args:
  0. mode

### `op 268` — QueryNpcArrivedAtSchedule(npc, more npc ids)
*handler:* `Script_VMOp_QueryNpcArrivedAtSchedule`

Read 1 iff the given NPC(s) have arrived at their schedule-computed spots and are available (Npc_IsAtScheduledSpotAndAvailable) into the VM output. arg0 = 0: checks ALL villagers 1..23 (1 only if every present one is in place). Otherwise EVERY arg is an npc char id - the op is variadic with NO count argument - and all listed NPCs must be in place. Wait-until-NPCs-in-position predicate before a staged scene.

Args:
  0. npc (char id, 0=all villagers)
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. more npc ids (variadic)

### `op 269` — QueryNpcArrivedAtSchedule(npc, more npc ids ...)
*handler:* `Script_VMOp_QueryNpcArrivedAtSchedule`

Query -> reg0 whether NPC(s) are at their scheduled spot (Npc_IsAtScheduledSpotAndAvailable). ALL args are npc char ids -- variadic list, NO count argument: with an explicit list, returns 1 iff EVERY listed NPC passes the check. With arg0 = 0, scans schedule-active NPCs 1..23 (record +228 bit 1 set) and returns 1 iff NONE of them passes -- the all-NPC mode's polarity is inverted vs the list mode (decompile-verified quirk). Alias of op 268 (same handler).

Args:
  0. npc (char id; 0 = all-NPC mode)
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. more npc ids ... (variadic)

### `op 273` — QueryNpcPresent(npc)
*handler:* `Script_VMOp_QueryNpcPresentFlag`

Read whether a villager is 'present' — record bit 0x400000 (bit 22 of record+52, present-in-town) — into the VM output. arg0 = villager id, valid only for 1-23 (the handler requires id < 24; other ids yield 0). arg0 = 0 instead returns the COUNT of villagers (1-23) currently present.

Args:
  0. npc (villager id <24; 0 = count all present)
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 274` — QueryNpcPresent(npc)
*handler:* `Script_VMOp_QueryNpcPresentFlag`

Alias of op 273 (same handler): read an NPC's present flag, or the villager present-count when arg0 = 0.

Args:
  0. npc (char id, 0=count all)
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 276` — QueryNpcModelId(npc)
*handler:* `Script_VMOp_QueryNpcModelId`

Read an NPC's current model/resource id (the loaded character model) into the VM output; 0 if none. arg0 = npc (char id). Use to check which model/costume an NPC is displaying.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 277` — QueryNpcModelId(npc)
*handler:* `Script_VMOp_QueryNpcModelId`

Alias of op 276 (same handler): read an NPC's current model/resource id.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 278` — QueryNpcFavoriteItem(npc)
*handler:* `Script_VMOp_QueryNpcFavoriteItem`

Read one of an NPC's favorite/loved gift item ids (rolled) into the VM output. arg0 = npc (char id). Used to hint or pre-fill a gift in a scene.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 279` — QueryNpcFavoriteItem(npc)
*handler:* `Script_VMOp_QueryNpcFavoriteItem`

Alias of op 278 (same handler): read a rolled favorite-gift item id for an NPC.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 280` — QueryNpcDateState(npc)
*handler:* `Script_VMOp_QueryNpcDateState`

Read an NPC's 3-bit DATE STATE (dating/relationship progression, npc record +55 & 7) into reg0 -- NOT a facing direction. arg0 = npc (char id); yields 0 if the NPC can't be resolved. Byte-for-byte duplicate of Npc_GetDateState, which backs EMQ_DATE_STATE (query 124) and the EMQ_SUBEV_ENABLE_* gates (tested against 0 or 5). Branch on it to gate date/relationship sub-events.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 282` — QueryNpcActorPresent(npc)
*handler:* `ScriptVMOp282_QueryNpcActorPresent`

Read whether an NPC's LIVE actor is spawned and visible in the current scene (its actor exists and the hidden bit is clear) into the VM output. arg0 = npc (char id). Distinct from QueryNpcPresent (op 273), which checks the town-roster flag.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 283` — QueryCompanionNpcId()
*handler:* `Script_VMOp_QueryCompanionNpcId`

Read the char id of the player's current NPC companion (the villager following the player) into the VM output, or 0 if none. Use to branch on who is accompanying the player during a scene.

### `op 288` — QueryNpcActorStateWord(npc)
*handler:* `ScriptVMOp_QueryNpcActorWordField488`

Read a per-NPC actor state word (actor field +488) into the VM output; 0 if the NPC isn't loaded. arg0 = npc (char id). The exact meaning is engine-internal (a 16-bit state field a few scripts branch on).

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 309` — IsFrey()
*handler:* `Script_VMOp_GetPlayerIsFreyVariant`

Writes 1 to reg0 when playing as Frey (female protagonist), 0 for Lest. The scripts pick gendered lines/animations by branching on reg0 right after.

### `op 310` — QueryPlayerIsLest()
*handler:* `Script_VMOp_QueryPlayerIsLest`

Read 1 if the player is Lest (the MALE protagonist), else 0 (Frey / female). CORRECTION: not an item check. Reads the actor's voice-marker u16 at task +0x220 and tests == 1217. That field is the voice marker (voice-family base + per-character offset), set by Player_SetCharacterVariantLestOrFrey / Player_TransformToCharacterById; the code documents 1217 = Lest, 1233 = Frey. So this is the standard player-gender / protagonist branch used to fork dialogue between the male and female hero. No args.

### `op 321` — GetEmote(npc id)
*handler:* `Script_VMOp_GetNpcEmoteByte`

Read an NPC's current emote id.

Args:
  0. npc id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 324` — GetMood(npc id)
*handler:* `Script_VMOp_GetNpcMoodByte`

Read an NPC's current mood id.

Args:
  0. npc id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 329` — IsPosing(actor)
*handler:* `Script_VMOp_GetActorScriptedPoseActive`

1 if an actor's scripted pose is active.

Args:
  0. actor

### `op 338` — CheckNpcSchedule(npc)
*handler:* `Script_VMOp_GetNpcScheduleMatchAndId`

Check whether an NPC is currently on its EXPECTED schedule and read that schedule id. arg0 = NPC char id (0 falls back to the player's spouse via the wife-id game flag). Writes 1/0 to the main VM output — 1 if the NPC's current schedule id equals the scene's pre-set expected-schedule field — and the NPC's season-adjusted current schedule id to the second output. Used to gate dialogue on where an NPC is supposed to be right now.

Args:
  0. npc (char id, 0=spouse)

### `op 339` — GetNpcSchedule(npc)
*handler:* `Script_VMOp_GetNpcCurrentScheduleId`

Read an NPC's current schedule id (which daily-itinerary slot it is in right now) into the VM output. arg0 = NPC char id. Schedules below 0x40 are season-adjusted: the current season index is added unless it is Winter. Lets a script branch on an NPC's present activity/location.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 342` — GetVar0(index)
*handler:* `Script_VMOp_ReadVarArrayKind0`

Read global script-variable bank 0 at [index] into reg0 -- the paired reader for SetVar0. Engine-global state (kinds 0-3 in the game-globals slot table, the rest in dedicated arrays), shared with the choice-commit system, so it can read back a value that an earlier scene or a committed choice stored. IDA-verified: Script_VMOp_ReadVarArrayKind0.

Args:
  0. index

### `op 344` — GetVar1(index)
*handler:* `Script_VMOp_ReadVarArrayKind1`

Read global script-variable bank 1 at [index] into reg0 -- the paired reader for SetVar1. Engine-global state (kinds 0-3 in the game-globals slot table, the rest in dedicated arrays), shared with the choice-commit system, so it can read back a value that an earlier scene or a committed choice stored. IDA-verified: Script_VMOp_ReadVarArrayKind1.

Args:
  0. index

### `op 346` — GetVar11(index)
*handler:* `Script_VMOp_ReadVarArrayKind11`

Read global script-variable bank 11 at [index] into reg0 -- the paired reader for SetVar11. Engine-global state (kinds 0-3 in the game-globals slot table, the rest in dedicated arrays), shared with the choice-commit system, so it can read back a value that an earlier scene or a committed choice stored. IDA-verified: Script_VMOp_ReadVarArrayKind11.

Args:
  0. index

### `op 350` — GetVar3(index)
*handler:* `Script_VMOp_ReadVarArrayKind3`

Read global script-variable bank 3 at [index] into reg0 -- the paired reader for SetVar3. Engine-global state (kinds 0-3 in the game-globals slot table, the rest in dedicated arrays), shared with the choice-commit system, so it can read back a value that an earlier scene or a committed choice stored. IDA-verified: Script_VMOp_ReadVarArrayKind3.

Args:
  0. index

### `op 352` — GetVar4(index)
*handler:* `Script_VMOp_ReadVarArrayKind4`

Read global script-variable bank 4 at [index] into reg0 -- the paired reader for SetVar4. Engine-global state (kinds 0-3 in the game-globals slot table, the rest in dedicated arrays), shared with the choice-commit system, so it can read back a value that an earlier scene or a committed choice stored. IDA-verified: Script_VMOp_ReadVarArrayKind4.

Args:
  0. index

### `op 354` — GetVar5(index)
*handler:* `Script_VMOp_ReadVarArrayKind5`

Read global script-variable bank 5 at [index] into reg0 -- the paired reader for SetVar5. Engine-global state (kinds 0-3 in the game-globals slot table, the rest in dedicated arrays), shared with the choice-commit system, so it can read back a value that an earlier scene or a committed choice stored. IDA-verified: Script_VMOp_ReadVarArrayKind5.

Args:
  0. index

### `op 356` — GetVar6(index)
*handler:* `Script_VMOp_ReadVarArrayKind6`

Read global script-variable bank 6 at [index] into reg0 -- the paired reader for SetVar6. Engine-global state (kinds 0-3 in the game-globals slot table, the rest in dedicated arrays), shared with the choice-commit system, so it can read back a value that an earlier scene or a committed choice stored. IDA-verified: Script_VMOp_ReadVarArrayKind6.

Args:
  0. index

### `op 358` — GetVar7(index)
*handler:* `Script_VMOp_ReadVarArrayKind7`

Read global script-variable bank 7 at [index] into reg0 (g_scriptVarArrayKind7_52u32, a 52-entry u32 array). Identical shape to GetVar0/GetVar3 — the handler is a plain kind-7 var-array read with nothing portrait-specific in it; the old 'GetPortrait' name asserted semantics the code doesn't show. Only 16 corpus uses, all in bank 60 (the order/dev-menu bank).

Args:
  0. index

### `op 360` — GetVar8(index)
*handler:* `Script_VMOp_ReadVarArrayKind8`

Read global script-variable bank 8 at [index] into reg0 -- the paired reader for SetVar8. Engine-global state (kinds 0-3 in the game-globals slot table, the rest in dedicated arrays), shared with the choice-commit system, so it can read back a value that an earlier scene or a committed choice stored. IDA-verified: Script_VMOp_ReadVarArrayKind8.

Args:
  0. index

### `op 362` — GetNpcBirthdayMonthAndDay(kind9 slot, npc id)
*handler:* `Script_VMOp_GetNpcBirthdayMonthAndDay`

Read NPC #arg1's birthday from calendar archive 16340. Format: archive record = 4 bytes each: [+0]=npc_id, [+1]=month (1..4 = RF4 season month), [+2]=day, [+3]=unused. Walks records at archive+28 (count at archive+24) until matching npc_id found. **Writes** the packed calendar code `day + 100*month` to var-array-kind-9 at [arg 0], and separately writes month to ctx[+64] + day to ctx[+68]. Silently defaults to (0, 0) if the NPC is not in the archive.

Args:
  0. kind9 slot
  1. npc id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 363` — GetEventMonthOrBirthFlag(kind0 slot, event id)
*handler:* `Script_VMOp_GetCalendarEventMonthWithFallback`

Like op 362 but reads only the MONTH byte from calendar archive 16340 for a given event_id. **Fallback when arg 1 = 0**: reads player's birth season/day from GameFlags (GF_REG_PLAYER_BIRTH_SEASON 2-bit + GF_REG_PLAYER_BIRTH_DAY 5-bit). Writes result + **616** (a festival-ID base offset) into var-array-kind-0 at [arg 0]; also writes day into var-array-kind-3 and ctx[+64]/[+68]. Used to compute 'this event's festival id' for downstream lookups.

Args:
  0. kind0 slot
  1. event id (0=player birthday)

### `op 367` — GetVar14(index)
*handler:* `Script_VMOp_ReadVarArrayKind14`

Read global script-variable bank 14 at [index] into reg0 -- the paired reader for SetVar14. Engine-global state (kinds 0-3 in the game-globals slot table, the rest in dedicated arrays), shared with the choice-commit system, so it can read back a value that an earlier scene or a committed choice stored. IDA-verified: Script_VMOp_ReadVarArrayKind14.

Args:
  0. index

### `op 369` — QueryPlayerCanInteract((ignored))
*handler:* `Script_VMOp_QueryPlayerCanInteractWithActor`

Attempt a player-mount/interaction onto the current scene actor and report the outcome. reg0 = 0 if the player is mid-action, 2 if carry-blocked (status 0x4000), else the result of Player_BeginMountTransitionAndInstallTickAndAnchor -- i.e. when free it actually BEGINS the mount transition. reg1 = 1 iff the player is not mid-action. The handler reads NO script args, though shipped scripts always pass one literal (ignored).

Args:
  0. (ignored)

### `op 371` — EvalCondScriptA(em entry id)
*handler:* `Script_VMOp_EvalCondScriptA`

Evaluate em.bin entry [id]'s condition A (Event Manager trigger check); bool result goes to the VM query register. E.g. EV_DATE_APPO, EM_BOSS_*_RETURN_MATCH_CHECK.

Args:
  0. em entry id

### `op 372` — EvalCondScriptB(em entry id)
*handler:* `Script_VMOp_EvalCondScriptB`

Evaluate em.bin entry [id]'s condition B (the entry's alternate/negated variant, e.g. EV_CMN_DAYTIME's B = 'not daytime').

Args:
  0. em entry id

### `op 377` — GetChoiceResult()
*handler:* `Script_VMOp_ConsumeChoiceCommitResult`

Consume and read the last PROMPT_CHOICE result: after a menu commits, this opcode reads the committed value into the VM query register.

### `op 378` — GetChoiceResult()
*handler:* `Script_VMOp_ConsumeChoiceCommitResult`

Consume and read the last PROMPT_CHOICE result (dupe of op 377).

### `op 398` — QueryUnusedPoses(invert)
*handler:* `Script_VMOp_QueryUnlockedAlternatePoseMask`

Read 1 iff the player has any UNUSED unlocked alternate pose available. Scans the 16 alternate-pose unlock flags (GameFlags 729-744), skips the pose already in use, and builds an availability bitmask into the scene's choice-visibility field (the same one op 610's choice menu reads). Used to offer a 'change pose' menu only when there is an unused pose to switch to. arg0 = invert flag.

Args:
  0. invert (0/1)

### `op 399` — GetPlayerSubstate()
*handler:* `Script_VMOp_GetPlayerSubstateId`

Read the player's substate id.

### `op 403` — GetMonsterRosterAbsent()
*handler:* `Script_VMOp_QueryMonsterRosterAbsentMask`

For monster ids 1-3, write to the VM outputs whether each is NOT active in the monster roster (inverted presence flag, fixed context). Produces three outputs. (Formerly mislabeled a 'fishing' op.)

### `op 404` — GetMonsterRosterPresent(input context)
*handler:* `Script_VMOp_QueryMonsterRosterPresentMaskByCtx`

For monster ids 1-3, write to the VM outputs whether each IS active in the monster roster within input context [arg0]. Produces three outputs. (Formerly mislabeled a 'fishing' op.)

Args:
  0. input context

### `op 406` — GetMonsterFarmLovedToday()
*handler:* `Script_VMOp_GetMonsterFarmLovedTodayBit`

Read whether the farm monster the script is CURRENTLY addressing (the barn roster record whose task ptr matches the script ctx subject at +32) has been 'loved'/cared for today (g_MonsterFarmTable record flag bit 18) into the VM output; 0 if the subject is not a barn monster. Takes NO args. Counterpart of op 405.

### `op 407` — QueryActiveKillCount()
*handler:* `Script_VMOp_QueryActiveKillCount`

Read the count of monsters still alive in the active kill-aggregate list into the VM output — how many enemies are still standing. No args. For boss/battle scenes gating on 'defeat all the monsters' progress.

### `op 408` — CountLivingEnemies()
*handler:* `Script_VMOp_QueryKillAggregateActiveCountExclBoss`

Count the living monsters on the field EXCLUDING the two boss char ids (141/142) into the VM output. The 'kill all the trash before the boss appears' gate.

### `op 409` — CountTamedFarmMonsters()
*handler:* `Script_VMOp_CountTamedMonstersWithFlag1000`

Count farm monsters flagged 'tamed today' (flag bit 0x1000) across all 200 farm slots into the VM output.

### `op 411` — QueryCompanionMonsterData(target index, query kind)
*handler:* `Script_QueryCompanionMonsterData`

Read player / companion / farm-monster data into the VM output — a multi-purpose query. arg0 = target index (party member or monster), arg1 = query kind: 0-4 = party-member stats (base / mods / points / monster fields), 5-10 = farm-monster roster / flags / census / level / affinity. Sibling of QueryGameState. For stat-based dialogue and monster-farm scenes.

Args:
  0. target index
  1. query kind

### `op 414` — GetChoiceIndexAndItem()
*handler:* `Script_VMOp_GetScriptChoiceIndexAndItemId`

Read the last scripted item-selection result into TWO VM outputs: query register 0 = the choice slot index (0-7, extracted from scene-ctx +116 bits 6-8), register 1 = the associated item id (11-bit, from ctx+40 field +380). DISTINCT from GetChoiceResult (op 377/378 = Script_VMOp_ConsumeChoiceCommitResult, a different handler) -- this one (Script_VMOp_GetScriptChoiceIndexAndItemId) returns the index+item pair for an item-pick menu, not the committed PROMPT_CHOICE value.

### `op 416` — QueryPlayerVariable(variable, skill id)
*handler:* `Script_VMOp_QueryPlayerStatByCharCode`

Read a player variable chosen by an ASCII char-code arg: 'd'(100)=Gold, 'f'(102)=ArmorDef, 'g'(103)=FarmTameCount, 'h'(104)=Skill (2nd arg = skill id), 'i'(105)=Stone, 'j'(106)=Compost, 'k'(107)=MaxSkillLevel; a bare index <=39 reads that skill's level. Result goes to the scene query slot.

Args:
  0. variable
     - `100` = Gold
     - `102` = ArmorDef
     - `103` = FarmTameCount
     - `104` = Skill
     - `105` = Stone
     - `106` = Compost
     - `107` = MaxSkillLevel
  1. skill id
     - `0` = Short Sword
     - `1` = Long Sword
     - `2` = Spear
     - `3` = Axe/Hammer
     - `4` = Dual Blades
     - `5` = Fist
     - `6` = Fire
     - `7` = Water
     - `8` = Earth
     - `9` = Wind
     - `10` = Light
     - `11` = Dark
     - `12` = Love
     - `13` = Farming
     - `14` = Logging
     - `15` = Mining
     - `16` = Fishing
     - `17` = Cooking
     - `18` = Forging
     - `19` = Chemistry
     - `20` = Crafting
     - `21` = Searching
     - `22` = Walking
     - `23` = Sleeping
     - `24` = Eating
     - `25` = Defense
     - `26` = Resist Poison
     - `27` = Resist Seals
     - `28` = Resist Paralysis
     - `29` = Resist Sleep
     - `30` = Resist Fatigue
     - `31` = Resist Cold
     - `32` = Resist Knockout
     - `33` = Bathing
     - `34` = Taming
     - `35` = Throwing
     - `36` = Leadership
     - `37` = Bartering

### `op 418` — QueryBackpackHasOccupiedSlot()
*handler:* `Script_VMOp_QueryBackpackHasOccupiedSlot`

Read 1 iff the player's backpack has at least one occupied slot (holds any item) into the VM output. No args.

### `op 419` — QueryBackpackHasFreeSlot()
*handler:* `Script_VMOp_QueryBackpackOrEquipFirstFreeSlot`

Write 1 to the VM output if the backpack has any free slot, else 0 — a BOOLEAN, not a slot index. Walks the first 60 backpack slots looking for an empty/placeholder entry (slot kind < 0x800 or item id 0); if all are full it falls back to checking the special equip-extras slot (g_itemDatabase.ptr_00[+24]). No args. Used before placing an item.

### `op 420` — QueryBackpackFreeSlots(min free slots)
*handler:* `Script_VMOp_QueryBackpackFreeSlotCountGTE`

Read 1 iff the player's backpack has at least [N] free slots into the VM output — the 'do you have room for N more items?' check before granting items. arg0 = N.

Args:
  0. min free slots

### `op 426` — IsExtrasSlotFull()
*handler:* `Script_VMOp_QueryEquipExtrasSlot24Occupied`

Read 1 iff the player's equip-extras slot (the single extra/accessory slot at inventory +24) currently holds at least one of a valid item. Writes the boolean to the VM output so a script can test whether that slot is occupied before offering to fill it. Takes no arguments.

### `op 431` — HasItem(item id, min count, min quality)
*handler:* `Script_VMOp_QueryItemAvailableInBackpackOrEquipExtras`

Query whether the player owns at least [count] of an item at quality >= [quality], searching the backpack + equip-extras slot. Main output = 1 if found, else 0; the second output = a per-slot flag bit of the matched slot. arg2 quality is 1-based (pass 0 to accept any quality). The classic 'do you have N of item X?' dialogue gate.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. min count
  2. min quality (0=any)

### `op 432` — CheckCropPlantable(seed item id)
*handler:* `Script_VMOp_QueryCropPlantableAndTileInfo`

Check whether a seed can be planted on the tile the player is on, and read tile info. arg0 = seed item id. Outputs: main = plantable this season (1/0; Turnip Seed [39] is always plantable in Spring), then the tile's yield/pattern value, the crop sub-type, and a 'regrowing crop' flag. Gates the 'plant this here?' farming dialogue.

Args:
  0. seed item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 433` — QueryFishSizeRecords(fish id)
*handler:* `Script_VMOp_QueryFishSizeRecords`

Query the player's caught-fish size records for the given fish id. Writes TWO results: the BIGGEST recorded size (FishRecord_GetBestSize) to query register 0 (ctx+64), and the SMALLEST recorded size (FishRecord_GetSmallestSize) to query register 1 (ctx+68). Confirmed by decompile -- an earlier label mis-guessed this as a craft-record query, but both results are fish-size records (biggest + smallest).

Args:
  0. fish id

### `op 434` — GetItemGoldValue(item id)
*handler:* `Script_VMOp_QueryItemBaseGoldValueQuality0`

Read an item's base gold value — a single unit at quality 0 — into the VM output. arg0 = item id. Use it to show or compute a price in a scripted menu.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 435` — GetItemBuyPrice(item id)
*handler:* `Script_VMOp_QueryItemBuyPrice`

Read an item's base BUY price into the VM output (the metadata buy-price field, the amount a shop charges before any modifier). arg0 = item id. Contrast GetItemGoldValue (op 434), which is the SELL value.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 436` — IsItemStackable(item id)
*handler:* `Script_VMOp_QueryItemIsStackable`

Read 1 if the item can stack (its metadata stack field is > 1), else 0. arg0 = item id.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 437` — NpcWantsItem(item id, npc)
*handler:* `Script_VMOp_QueryItemInNpcOfferListArchive14850`

Query whether item [arg0] appears in NPC [arg1]'s offer / present list (the gift-preference archive 14850). Main output = 1 if the item is in that NPC's list. Used to gate 'does this NPC want this item?' dialogue.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. npc (char id)

### `op 438` — QueryHasItemOfCategory(category id)
*handler:* `Script_VMOp_QueryBackpackOrEquipHasItemOfCategory`

Read 1 iff the player holds any item of a given CATEGORY (weapon class, food, seed, etc — the item-metadata category byte) into the VM output. arg0 = category id. For 'do you have any [type]?' dialogue gates.

Args:
  0. category id

### `op 440` — GetNpcSpecies(char id)
*handler:* `Script_VMOp_QueryNpcParamSpeciesByCharId`

Read an NPC/monster's species id from the NPC-parameter data (rf3NpcParam) into the VM output. arg0 = char id. Lets a script tell what species an actor is (e.g. 'is this a monster?').

Args:
  0. char id
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 441` — QueryConfirmButton()
*handler:* `Script_VMOp_QueryConfirmButtonBit41`

Read 1 if the CONFIRM / advance button is currently down, else 0. Tests g_inputState_HighBits bit 41 (0x20000000000) -- the same bit DialogueBox_TickState4_ShowText OR's with the keyboard/analog inputs to ADVANCE dialogue, so it's the primary confirm/action button. Used in cutscenes to detect the player pressing confirm (e.g. to advance or skip). No args.

### `op 442` — QueryStickInputActive()
*handler:* `Script_VMOp_QueryStickByte5Pressed`

Read 1 if the analog stick / d-pad is currently engaged, else 0. Tests byte 5 of g_inputState_StickInput (non-zero = stick pushed/tilted); the dialogue input path uses the same byte to gate its stick-magnitude checks. No args.

### `op 445` — GetFlagBit(flag id)
*handler:* `Script_VMOp_QueryGameFlagBitDirect`

Query -> VM query register: 1 if game-flag bit [flag id] is set, else 0. The id is ZONE-2 RELATIVE: the handler tests absolute bit 4096 + id (it adds the buffer's zone2_base), the same numbering as ops 443/444 and MOBJ f13 -- NOT the emdeb/emflags (zone-1) table. Known blocks: emflags.ZONE2_BLOCKS.

Args:
  0. flag id

### `op 447` — GetWeather()
*handler:* `Script_Query_CurrentWeather`

Read the current weather code into the VM output (see SetWeather / op 446 for the code values 0-8). Takes no arguments.

### `op 456` — QueryEquippedItemAttr(equip slot, attribute id)
*handler:* `Script_VMOp_QueryEquippedItemAttrByEquipSlot`

Read an equipped item's id + a chosen attribute into the VM output (output slot 0 = item id, slot 1 = attribute value). arg0 = equip slot (0 weapon, 1 shield, 2 head, 3 body, 4 boots, 5 accessory). arg1 = attribute id: 0-8 = enchant-slot effects, 9/10 = upgrade attrs, 11 = base item id, 12 = rune-slot count, 13/14 = rune ids. For upgrade / enchant / appraisal dialogue.

Args:
  0. equip slot (0=weapon..5=accessory)
  1. attribute id

### `op 470` — GetChildFriendLevel(child)
*handler:* `Script_VMOp_QueryChildFriendshipByteAt1`

Read a child NPC's friendship level (record byte +1) into the VM output. arg0 = child char id (24-47); out-of-range yields 0.

Args:
  0. child (char id 24-47)

### `op 471` — GetChildFriendPoints(child)
*handler:* `Script_VMOp_QueryChildFriendshipWordAt4`

Read a child NPC's friendship points (the word at record +4) into the VM output. arg0 = child char id (24-47).

Args:
  0. child (char id 24-47)

### `op 473` — RollChildDailyPref(child, range)
*handler:* `Script_VMOp_RollOrGetChildPersistedRandom`

Roll-once-and-remember a child NPC's daily random preference in [0, range). The first call this session rolls it (MMIX RNG) and stores it in the record; later calls return the stored value, so it stays stable across save reloads. arg0 = child char id (24-47), arg1 = range.

Args:
  0. child (char id 24-47)
  1. range

### `op 481` — GetPartyMemberId(slot)
*handler:* `Script_VMOp_QueryPartyMemberDwordAt8`

Read a party member's identity field (task +8) by slot into the VM output: arg0 = 0 for companion 1, 1 for companion 2. Returns 0 if that slot is empty. Used to branch dialogue on who is currently in the party.

Args:
  0. slot (0=companion 1, 1=companion 2)

### `op 482` — GetPartyMemberId(slot)
*handler:* `Script_VMOp_QueryPartyMemberDwordAt8`

Read a party member's identity field (task +8) by slot into the VM output (duplicate of op 481): arg0 = 0 for companion 1, 1 for companion 2. Returns 0 if the slot is empty.

Args:
  0. slot (0=companion 1, 1=companion 2)

### `op 487` — QueryCurrentNpcInParty()
*handler:* `Script_VMOp_QueryCurrentInteractionNpcInActiveParty`

Read 1 iff the NPC the player is currently talking to is in the active party (one of the two companion slots). No args. Branch on 'is this NPC traveling with me'.

### `op 490` — QueryMarriagePartnerInParty()
*handler:* `Script_VMOp_QueryMarriagePartnerInPartyAndUnlockAch771`

Read 1 iff your marriage candidate is present in the party for a date/proposal scene (and, if so, unlock the 'met your partner' achievement). No args. Gates the marriage-scene branch.

### `op 493` — GetNpcFacingMode()
*handler:* `Script_VMOp_QueryNpcScriptedFacingModeBits`

Read the CURRENT scene NPC's scripted-facing mode bits (low 2 bits of the facing-mode word at scene_npc+304 -> +450) into the VM output. Takes NO arguments — it always targets the scene's own NPC record (sceneCtx+32), writing 0 if there is none. Counterpart of the mode setter (op 492 family).

### `op 502` — IsCompanionMoving(slot)
*handler:* `Script_VMOp_QueryAnyCompanionStillTransitioning`

1 if any companion is still moving/rotating (blocking poll).

Args:
  0. slot
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both

### `op 504` — QueryPartyMemberTileY(slot)
*handler:* `Script_VMOp_QueryPartyMemberWorldYTile`

Read a party member's Y tile coordinate into the VM output. arg0 = companion slot (0 = companion 1, 1 = companion 2; -1 = the player). Pairs with the char-id query (op 481).

Args:
  0. slot (0/1 companion, -1=player)

### `op 534` — GetDailyVisitor(mode)
*handler:* `Script_VMOp_QueryDailyVisitorByMode`

Read the daily traveling-visitor (Sakura merchant) data by mode into the VM outputs: 0/1 = an offer category, 2 = npc id + wanted item + price tier, 3 = alt wanted item + quantity, 9 = the four discount bits, 10 = the packed want-quest id. arg0 = mode.

Args:
  0. mode (0,1,2,3,9,10)

### `op 552` — GetThrowQueueRemaining(item id)
*handler:* `Script_VMOp_QueryGeneralThrowQueueRemainingByItemId`

Read how many more of item [arg0] are still needed by the dungeon 'throw'/delivery queue (need minus have, floored at 0) into the VM output. The 'how many left to gather?' check.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 561` — GetSceneStateBytes()
*handler:* `Script_VMOp_QuerySceneEntityBytesArray4`

Read the current scene's four state-machine bytes (scene+540..+543) into the first four VM outputs. Scene-local status bytes a scene script can inspect (byte +541 is the SetSceneScratch byte).

### `op 567` — GetTomorrowsBirthdayNpc()
*handler:* `Script_VMOp_QueryTomorrowBirthdayNpcIfNotMet`

Read the char id of the NPC whose birthday is TOMORROW into the VM output (0 if none, or if the reminder for them is already accounted for today). Drives 'don't forget about X's birthday tomorrow!' reminder dialogue.

### `op 568` — GetSceneNpc(index)
*handler:* `Script_VMOp_QuerySceneNpcByIndexAndDirtyBit`

Read a scene NPC's char id into the main VM output — arg0 <= 0 selects the scene's primary NPC, arg0 1-7 selects the scene family/participant NPC list. The second output gets the scene's 'refresh queued' dirty bit.

Args:
  0. index (<=0 = primary, 1-7 = family)

### `op 569` — RankFestivalContestants(contest param 0, contest param 1)
*handler:* `Script_VMOp_QueryTopRankedNpcsFromRoster`

Roll and rank the top 3 festival-contest competitors (friendship-weighted scores, gated by the active festival flag) and write their (npc id, score_lo, score_hi) tuples into the scene result registers (9 dwords at ctx+64..+100) for the contest-results cutscene. arg0/arg1 tune the roster/scoring. (Recategorized flow->query: returns data to the VM.)

Args:
  0. contest param 0
  1. contest param 1

### `op 570` — GetTodaysRequestNpc()
*handler:* `Script_VMOp_QueryTodayDailyRequestActiveNpcId`

Read the char id of the NPC who has an active daily request/order posted today into the VM output (0 if none). Lets a script point the player at today's request-giver.

### `op 572` — GetSceneScratchByte()
*handler:* `Script_VMOp_QuerySceneFlagByteAt541`

Read the scene-local scratch byte (scene+541) set by SetSceneScratch (op 571) into the VM output. Takes no arguments.

### `op 573` — GetFestivalPlacements()
*handler:* `Script_VMOp_QueryFourSceneEventTwoFields`

Compute the final festival-contest placements (Festival_ComputeAndRecordPlacements), then read the top four events' (score, entry) pairs into the first eight VM outputs (ctx+64..+92). Drives the contest-results cutscene that shows the winners. (Recategorized flow->query: it writes 8 result registers, so it is a data-returning query.)

### `op 575` — GetShuffleValue(index)
*handler:* `Script_VMOp_QueryShuffleBufferByteAt`

Read entry [arg0] of the scene shuffle buffer built by ShuffleSceneBuffer (op 574) into the VM output — the arg0-th value of the random permutation.

Args:
  0. index

### `op 576` — GetSceneEventNpc(event index)
*handler:* `Script_VMOp_QuerySceneEventNpcByEventIdx`

Read the NPC/actor id of scene event #arg0 into the VM output (from the 40-byte-stride scene event-actor registry at scene+172).

Args:
  0. event index

### `op 577` — GetEventParticipants()
*handler:* `Script_VMOp_QueryCalendarEventParticipantsAndScoreFromArchive16340`

Read the current calendar event's four participants (npc id + day, into the VM outputs) and compute the event's score from the calendar-event archive (16340) into the main output. Empty participant slots are consumed as it scans. Used by festival/event cutscenes to list who took part and how they scored.

### `op 579` — GetSceneEventFlags()
*handler:* `Script_VMOp_QuerySceneEventFlagsTriplet`

Read the scene's event-state triplet into three VM outputs: a word at scene+546, a byte at scene+543, and a word at scene+548. Scene-event bookkeeping fields.

### `op 580` — GetHeldItemStats()
*handler:* `Script_VMOp_QueryHeldItemEffectiveStatsOrCraftRecord`

Read the currently-held item's display stats into the VM outputs (6 values starting at the main output). Weapon/armor: [0] equipped flag, [1] sub-value, [2] equip type, [3] ATK%, [4] DEF% (percentages clamped to +/-100), [5] item id. Any other item: [0] equipped flag, [1] craft tier, [2] a byte field, [3] craft level, [5] item id. Used to render the held-item tooltip inside scripted menus.

### `op 581` — CheckFishRecord(fish size rank)
*handler:* `Script_VMOp_QueryAndUpdateFishCaughtMaxRank`

Compare a fish's size rank (arg0) against the saved 'largest fish caught' record and update the record if it is bigger. Main output = 0 for a new record (and the record is saved), 2 if it ties the record, 1 if smaller; the previous max is written to the second output. Drives the 'biggest catch!' fishing dialogue.

Args:
  0. fish size rank

### `op 582` — GetFishRecord()
*handler:* `Script_VMOp_QueryFishCaughtMaxRank`

Read the saved 'largest fish caught' size rank into the VM output. Read-only counterpart to CheckFishRecord (op 581).

### `op 588` — IsTileObjectActive(item id)
*handler:* `Script_VMOp_QueryTileObjectActiveByItemId`

Query whether a placed map object (tile object) holding item [arg0] is currently active on the map — searches the 64-slot map-entity registry. Main output = 1 if found, else 0.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 592` — CanPlaceTileObject(item id)
*handler:* `Script_VMOp_QueryTileObjectFreeOrFew`

Query whether there is room for another tile object matching item [arg0] (pass 0 for any): main output = 1 when fewer than 16 of them are currently active. The 'can I place another?' gate.

Args:
  0. item id (0 = any)
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 618` — IsPickingUpItem()
*handler:* `Script_VMOp_QueryActiveItemPickupIcon`

Read 1 if the player is currently mid-item-pickup (the pickup-icon animation task is active), else 0. Lets a script wait out a pickup before continuing.

### `op 619` — QueryNpcAdmireResponse()
*handler:* `Script_VMOp_QueryAndCacheNpcAdmireResponse`

Read the current interaction NPC's 'admire' reaction into the VM output: 0 = no/reserved, 1 = happy, 2 = excited. Gated by friendship level, story progress, season, and per-NPC conditions; the result is cached so re-queries stay stable. Drives confession / gift-admire dialogue branches. No args.

### `op 622` — QueryDifficulty()
*handler:* `Script_VMOp_QueryDifficultyMode`

Read the current difficulty into the VM output (counterpart of op 621): 0 = Easy, 1 = Normal, 2 = Hard or Hell (indistinguishable at the engine level). No args.

### `op 626` — GetInventoryFlagBit(bit index)
*handler:* `Script_VMOp_QueryPlayerInventoryFlagBit`

Read bit [arg0] of the player's inventory-flags word into the VM output — a generic inventory state-bit test (0 or 1).

Args:
  0. bit index

### `op 635` — GetActionTriggerByte(index)
*handler:* `Script_VMOp_QueryActionTriggerByteByIdx`

Read action-trigger byte [arg0] (index clamped 0-2, from the scene's 3-byte trigger array) into the VM output. The read counterpart of SetActionTriggerByte (op 634).

Args:
  0. index (0-2)

### `op 638` — GetForecasts()
*handler:* `Script_Query_DailyForecasts`

Roll and read today/tomorrow/day+6 crop & weather forecast icons into four VM outputs (used by the Prince-Points HUD forecast display). Takes no arguments.

### `op 644` — GetEffectState(effect id, sub-index / variant)
*handler:* `Script_QueryEffectStateById`

Query a town/prince effect's state by id (Effects_QueryById) into the query register. arg1 = sub-index/variant (verified read at argbuf[-5]; usually 0 in shipped scenes).

Args:
  0. effect id
     - `10` = Blossom's Furniture
     - `11` = Lumi's Flower Shop
     - `12` = Cooking Bread tier
     - `13` = Furniture Shop
     - `14` = Blossom's Groceries
     - `15` = Bado's Accessories
     - `16` = Bado's Bargain Sale
     - `17` = Clothing Shop
     - `18` = Fish Market
     - `19` = Jewelry Shop
     - `20` = Magic Shop
     - `21` = Ability Shop
     - `22` = Business License
     - `23` = Nationalize Baths
     - `24` = Forging License
     - `25` = Chemistry License
     - `26` = Crafting License
     - `27` = EZ Cooking License
     - `28` = Pro Cooking License
     - `29` = Effect-applied flag
     - `31` = Rucksack upgrade
     - `32` = Fridge upgrade
     - `33` = Storage upgrade
     - `34` = Bookshelf upgrade
     - `35` = Weapon Rack upgrade
     - `36` = Farm Tool Box upgrade
     - `37` = Closet upgrade
     - `38` = Shipping Box upgrade
  1. sub-index / variant

### `op 646` — GetPrinceRank()
*handler:* `Script_QueryPrinceRank`

Read the current prince rank.

### `op 647` — GetEffectCost(effect id, currency index)
*handler:* `Script_QueryEffectCostForCurrency`

Read the cost of a town/prince development effect in a given currency into the VM output. arg0 = effect id, arg1 = currency index.

Args:
  0. effect id
     - `10` = Blossom's Furniture
     - `11` = Lumi's Flower Shop
     - `12` = Cooking Bread tier
     - `13` = Furniture Shop
     - `14` = Blossom's Groceries
     - `15` = Bado's Accessories
     - `16` = Bado's Bargain Sale
     - `17` = Clothing Shop
     - `18` = Fish Market
     - `19` = Jewelry Shop
     - `20` = Magic Shop
     - `21` = Ability Shop
     - `22` = Business License
     - `23` = Nationalize Baths
     - `24` = Forging License
     - `25` = Chemistry License
     - `26` = Crafting License
     - `27` = EZ Cooking License
     - `28` = Pro Cooking License
     - `29` = Effect-applied flag
     - `31` = Rucksack upgrade
     - `32` = Fridge upgrade
     - `33` = Storage upgrade
     - `34` = Bookshelf upgrade
     - `35` = Weapon Rack upgrade
     - `36` = Farm Tool Box upgrade
     - `37` = Closet upgrade
     - `38` = Shipping Box upgrade
  1. currency index

### `op 648` — QueryTownDevelopment()
*handler:* `Script_QueryTownDevelopmentPercent`

Read the town/shipping development percentage (unique items shipped ÷ total unique × 100, clamped to 100) into the VM output. For progress-gated dialogue ('the town is X% developed'). No args.

### `op 649` — QueryShippingBoxGold()
*handler:* `Script_VMOp_QueryShippingBoxTotalGold`

Read the total gold value of everything currently in the shipping box into the VM output (capped at 999,999,999). No args. For shipping-total dialogue.

### `op 650` — GetLifetimeCropGold()
*handler:* `Script_VMOp_QueryLifetimeShippedGoldCategory0`

Read the player's lifetime shipped-gold total for shipping category 0 (Crops) into the VM output (capped at 2,000,000,000). Takes no arguments.

### `op 652` — GetSceneWord348()
*handler:* `Script_VMOp_QuerySceneA1Word348`

Read the scene context's state word at offset +348 into the VM output. A scene-local scratch/status value whose meaning depends on the individual scene script.

### `op 658` — GetSceneWordPair112()
*handler:* `Script_VMOp_QuerySceneA1WordPair112`

Read the scene context's word pair at offsets +112 and +114 into the two VM outputs (main + second). These are scene-local coordinate/scratch words also used by the NPC streaming/respawn ops, so they typically hold a tile (x, y).

### `op 666` — QuerySaveConfigBit0()
*handler:* `Script_VMOp_QuerySaveConfigBit0`

Read save-config settings flag bit 0 (g_saveConfigFlags) into the VM output.

### `op 668` — QuerySaveConfigBit4()
*handler:* `Script_VMOp_QuerySaveConfigBit4`

Read save-config settings flag bit 4 (g_saveConfigFlags) into the VM output.

### `op 670` — QuerySaveConfigBit5()
*handler:* `Script_VMOp_QuerySaveConfigBit5`

Read save-config settings flag bit 5 (g_saveConfigFlags) into the VM output.

### `op 672` — QuerySaveConfigBit2()
*handler:* `Script_VMOp_QuerySaveConfigBit2`

Read save-config settings flag bit 2 (g_saveConfigFlags) into the VM output.

### `op 673` — QuerySaveConfigBit3()
*handler:* `Script_VMOp_QuerySaveConfigBit3`

Read save-config settings flag bit 3 (g_saveConfigFlags) into the VM output.

### `op 674` — GetRuneMedals()
*handler:* `Script_VMOp_QueryPlayerRuneMedalsDword`

Read the player's rune-medal count into the VM output. Takes no arguments.

### `op 676` — GetConst20()
*handler:* `Script_VMOp_QueryConst20`

Write the constant 20 to the VM output — a fixed capacity/limit sentinel used by a few scripts. Takes no arguments.

### `op 684` — QuerySaveConfigBitByIdx(config bit index)
*handler:* `Script_VMOp_QuerySaveConfigFlagBitByIdx`

Read a save-config settings flag bit by INDEX into the VM output. arg0 = bit index (0..58, spanning a 27-bit + a 32-bit config word). Generic settings read (distinct from the g_saveConfigFlags bit ops 666-673).

Args:
  0. config bit index

### `op 686` — GetGlobalScratch()
*handler:* `Script_VMOp_QueryGlobalDword302E4`

Read the general-purpose global scratch dword (set by op 685) into the VM output. No args.

### `op 690` — GetNpcProgressAndProp(npc)
*handler:* `Script_VMOp_QueryNpcRecordDword252AndItemId676`

Read an NPC's progress/state value (record +252) into the main VM output, and a derived prop item id (base 676 + an NPC state byte, or 0) into the second output. arg0 = npc char id.

Args:
  0. npc (char id)
     - `0` = Lest/Frey
     - `1` = Vishnal
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 694` — QuerySaveConfigBit1()
*handler:* `Script_VMOp_QuerySaveConfigBit1`

Read save-config settings flag bit 1 (g_saveConfigFlags) into the VM output.

### `op 695` — QueryMonsterDexBit(monster id)
*handler:* `Script_VMOp_QueryMonsterDexBitByMonsterId`

Read 1 iff a monster has been recorded in the monster dex (encountered/tamed) into the VM output. arg0 = monster id. For 'have you seen this monster?' gates.

Args:
  0. monster id

### `op 700` — QueryBackpackHasItem(item id, min quantity, min quality)
*handler:* `Script_VMOp_QueryBackpackHasItemAtLeastQtyQuality`

Read 1 iff the player's backpack holds at least [min qty] of an item at [min quality] or better. arg0 = item id, arg1 = min quantity, arg2 = min quality. The 'do you have X?' check for quest turn-ins and dialogue gates.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. min quantity
  2. min quality

## Other

### `op 527` — AdvanceRng(category ids)
*handler:* `Script_VMOp_AdvanceMmixRngByCategoryRolls`

Advance the shared MMIX RNG by up to 4 rolls WITHOUT using the results — an RNG warm-up / desync op. Each variadic arg is a shop-category id whose roll is performed and then discarded, shifting the random sequence for following rolls.

Args:
  0. category ids (0-4, variadic)

### `op 596` — RollUniformIntegerLessThanN(N)
*handler:* `Script_VMOp_RollUniformIntegerLessThanN`

Roll a uniform random integer in [0, N) via the MMIX RNG (N = 0 yields 0); the result is written to the VM output slot (ctx+64) for a following read.

Args:
  0. N (exclusive upper bound)

### `op 609` — RollRandomPointInRadiusAroundCenter(center x, center y, radius)
*handler:* `Script_VMOp_RollRandomPointInRadiusAroundCenter`

Roll a random tile point within a radius around a center: a Q12 polar roll (MMIX RNG angle + radius factor) writes the resulting tile-space point to the VM output slots (x at +64, y at +68) for a following read. Used to scatter monster spawns / placements around a target tile.

Args:
  0. center x
  1. center y
  2. radius

### `op 631` — RollSeededHashByMode16(mode, modulus)
*handler:* `Script_VMOp_RollSeededHashByMode16`

Deterministic NAME-seeded roll (NOT an RNG draw): hashes the bytes of a string chosen by `mode` (0 = player name, 1 = farm name, 2-5 = the RF1-4 town names Kardia/Alvarna/Sharance/Norad, 6-15 = a per-farm-monster name) via an MMIX mix, then returns a value in [0, modulus) at the VM output slot. Same name -> same result across reloads.

Args:
  0. mode (0=player,1=farm,2-5=RF town,6-15=farm monster)
  1. modulus

### `op 632` — RollSeededDailyRandom(mode, max)
*handler:* `Script_VMOp_RollSeededDailyRandom`

Roll a DAILY-seeded random integer: uses the calendar/date daily RNG, NOT the save-scummable global PRNG -- so it is reload-safe but date-dependent (same day -> same result). mode 0 = uniform [0, max); mode 1 = uniform [0, 101) (the arg is mixed in as a seed offset). Result written to the VM output slot.

Args:
  0. mode (0=[0,max), 1=[0,101))
  1. max

### `op 659` — MyShopAction(subcase, subcase args)
*handler:* `SakuraEvent_DispatchAction`

Dispatch a 'My Shop' (Sakura tourist-shop) sub-action chosen by arg0: 0 = has any item for sale, 1 = pick a visitor's desired item, 2 = compute a barter sale price, 3 = read sale totals, 4 = check the new-record flag, 5 = start the tourist spawner, 6 = stop it (also runs during map cleanup), 7 = commit a sale (gold + records + tourist count), 8 = roll a price variation. Later args and outputs are subcase-specific.

Args:
  0. subcase (0-8)
  1. subcase args (variadic)

### `op 691` — MultiplyValues(factors)
*handler:* `Script_VMOp_ComputeProductSeries`

Multiply ALL the statement's args together, cap the product at 999,999,999, and write it to reg0. Deterministic - no RNG (the old 'Roll' name was wrong). There is NO separate count argument: the count is the statement's own packed arg-count slot, every script arg is a factor, and an EMPTY call yields 0, not 1 (0x7ff7c1fdfc40; decomp-port confirmed 2026-09-01).

Args:
  0. factors (variadic; every arg is one factor)

## No-op (PC-port stub)

### `op 0` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op / padding token -- 4 bytes, no operands. Its dispatch slot is the shared return-0 stub, so it does nothing at runtime. Shipped cutscenes emit it inertly between statements (interspersed padding / alignment). Harmless to keep or delete.

### `op 272` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

Reserved opcode — bound to a shared no-op stub (a SoLoud bus placeholder). Does nothing and should not appear in real scripts.

### `op 381` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

Stubbed no-op (bound to the shared `return 0;` stub) — a 3DS-era op that does nothing on the PC port. UNLIKE most stub slots, shipped cutscenes DO still emit it (~15x in rf3.mc), so seeing it in a scene is normal, not corruption. Safe to keep or delete.

### `op 388` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

Stubbed no-op (bound to the shared `return 0;` stub) — a 3DS-era op that does nothing on the PC port. Shipped cutscenes still emit it (~5x in rf3.mc), so it is a legitimate (if inert) statement, not corruption. Safe to keep or delete.

### `op 693` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

**No-op stub in the PC port** (ICF-folded `return 0;` with ~379 xrefs in the binary). Bank 292 @0x0888 fires it with args 2..18, 100/101, 221 as if toggling dev flags ('Scenario Clear Flag ON', 'Marriage Flag ON', 'Movie flags OFF', ...), but the actual side-effect was stripped. The dev-menu dialog messages ('Marriage Flag has been set to +ON+') still print, but nothing happens. Was likely a 3DS-era dev-flag setter. Safe to keep, delete, or rewrite -- it does nothing on PC.

## Control opcodes (flow backbone)

These are the VM's control-flow tokens (opcode >= `0xFFF0`), handled inline by `Script_VMStep` rather than via the action-dispatch table. They structure every scene: dialogue, branches, choices, calls, and the scene end.

### `0xFFFF` — RET

Return-or-end -- the VM's real RETURN instruction (IDA-verified: Script_Opcode_FFFF_EndAndCleanup, RF4S.exe+0x23EBA0). Discards the current frame's locals, then: inside a CALLed subroutine it pops the saved PC and resumes right after the CALL; at the top level (frame base 0) it ends the scene (task state 1 READY). So `CALL -> Lx ... Lx: ... RET` is a subroutine, and only a top-level RET terminates the script. (Displayed as END before 2026-09-01.)

### `0xFFFE` — CALL

Call a subroutine: push the caller's frame base and the return PC onto the operand stack, then jump. The subroutine comes back here when it executes RET (the VM's return).

### `0xFFFD` — BR_RET

Conditional RET (early-exit guard): evaluate the guard expression -- if it is nonzero/true, do exactly what RET does (return from a CALLed subroutine, or end the scene at top level); otherwise fall through to the next statement. Never emitted in shipped scripts. IDA-verified (Script_VMStep case 0xFFFD -> Script_EvalExpressionOrVar, then Script_Opcode_FFFF_EndAndCleanup when true).

### `0xFFFC` — DIALOG

Show a dialogue line (by text id). The current SPEAKER (set by a SetSpeaker* portrait op, SetSpeakerVoice op 10, or nothing = narration) PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) — 917 shipped scenes rely on back-to-back lines under one speaker. If an ArmChoiceOption (op 615) precedes this line, it does NOT display: it queues as a choice option for a later PROMPT_CHOICE instead.

### `0xFFFB` — STORE

Evaluate an expression and store it into a variable.

### `0xFFFA` — JMP

Unconditional jump (trampoline-inserted beats read inline).

### `0xFFF9` — BR_NZ

Branch if the guard expression is non-zero (true).

### `0xFFF8` — BR_Z

Branch if the guard expression is 0 (false).

### `0xFFF7` — SWITCH_EQ

Indexed jump table: evaluate the selector expression, then jump to targets[value] when 0 <= value < N -- a DENSE 0..N-1 index, not a set of per-case compare values. The comparison is UNSIGNED, so a negative selector (like reg0 = -1 after a cancelled prompt) falls through to the next statement, same as any >= N value. The canonical use is dispatching a choice result: `SWITCH_EQ (reg0)` after a staged PROMPT_CHOICE jumps to the picked option's branch. Layout: [op][selector-expr][N][N u16 targets]. IDA-verified (Script_VMStep case 0xFFF7, RF4S.exe+0x23EF60).

### `0xFFF6` — SWITCH_GE

Indexed jump table, always-branch variant of SWITCH_EQ: jump to targets[value] when value < N, and CLAMP an out-of-range value (>= N, including negatives -- the compare is unsigned) to the last target (targets[N-1]) rather than falling through -- so it never falls through. Same [op][selector-expr][N][N u16 targets] layout as SWITCH_EQ. Used exactly once in the whole game. IDA-verified (Script_VMStep case 0xFFF6).

### `0xFFF5` — PROMPT_CHOICE_FORCED

Present a choice dialog the player CANNOT cancel -- one of the N u32 items MUST be picked. Same UI as PROMPT_CHOICE (each item is an rf3mc.<locale> string id) but with no CANCEL target. Branches to targets[picked VISIBLE ROW]. reg0: written ONLY when the choice was STAGED (a visibility mask via ops 610/612, or an ArmChoiceOption 615 queue) -- then reg0 = the picked option's ORIGINAL index (mapped through the mask bits), and a following SWITCH_EQ on reg0 dispatches it. An UNSTAGED prompt leaves reg0 UNTOUCHED -- shipped scenes rely on that to carry a GetPlayerPosition result in reg0/reg1 straight across a Yes/No prompt into the moves after it (the deck-fight chase). Layout: [op][N][N u16 targets][N u32 items]; size 6N+4. IDA-re-verified 2026-08-18 (SceneEvent_FinalizeAndPickFromBitmap).

### `0xFFF4` — PROMPT_CHOICE

Present a cancellable choice dialog (B backs out). Branches to the CANCEL target (index 0) on dismissal, else to the picked row's target. reg0 follows the same STAGED-ONLY rule as PROMPT_CHOICE_FORCED: a visibility-mask or armed-option prompt writes the picked option's ORIGINAL index to reg0 (for the following SWITCH_EQ); an unstaged prompt leaves reg0 alone, so values parked there by query ops survive the prompt. With a staged visibility mask only flagged options appear, and the prompt clears the mask (and any armed queue) after the pick. Layout: [op][N][N+1 u16 targets: target[0]=cancel, target[1..N]=per-choice][N u32 items]; size = 6N+6. IDA-verified via Script_VMStep case 0xFFF4 + SceneEvent_FinalizeAndPickFromBitmap (2026-08-18).

### `0xFFF3` — JMP_IND

Uniform-random jump: pick one of the N targets at random (each 1/N) and jump to it -- the UNWEIGHTED sibling of RAND_BR. Takes no operand (the target table is the only data); the pick is an RNG roll in [0, N) via the same VM RNG (reader-vtable +56) that RAND_BR rolls its weighted pick with. Layout: [op][N][N u16 targets]. IDA-verified (Script_VMStep case 0xFFF3).

### `0xFFF2` — RAND_BR

Weighted-random branch: pick one of N targets at random, each weighted by an expression. Every case's weight is evaluated fresh (so a weight can depend on game state), the weights are summed, then an RNG roll in [0, total) selects a target -- case i fires with probability weight[i] / sum(weights) (weight 0 = never taken). The editable literals on this op ARE those per-target weights, so raising one tilts the odds toward its branch. Layout: [op][N][N u16 targets][N u16 weight-exprs]; size 4N+4. IDA-verified (Script_VMStep case 0xFFF2 -> Script_Opcode_FFF2_ExecPrim, RF4S.exe+0x23EC40).

### `0xFFF1` — FRAME

Frame setup (formerly mislabeled 'RET' -- it does NOT return): sets the frame base to the current operand-stack top and reserves [local slots] entries for locals (always even -- the stack holds value/kind pairs, 2 per local), then execution FALLS THROUGH to the next statement. Typically the first statement of a CALLed subroutine; the matching return is RET (0xFFFF). IDA-verified: Script_VMStep case 0xFFF1, corrected 2026-08-06 (decomp docs/script_vm.md 2.3).

## Expression operands (argument encoding)

Action-op arguments and control-op guard/value expressions are not raw integers -- each is a little postfix (RPN) expression evaluated by `Script_EvalExpressionBytecode`. Most resolve to a single literal, but they can be variables, VM registers, or arithmetic. Leaf operands:

- **int literal** — a constant (u8 / s8 / u16 / s16 / int32).
- **`FLG_`/`REG_` name** (e.g. `REG_WIFE_ID`) — a packed game-flag / register reference (an emdeb.bin variable); shown as `var:0xNN` when the name table is unavailable.
- **`reg0`..`reg9`** — the VM's scratch registers. A query op writes its result to `reg0` (the ctx result slot); a following op / branch reads it.
- **`arr[0xNN]`** — a scene var-array load; **`self`**, **`null`**, **`0`** — fixed leaves.
- **`actor(Name)`** / **`map(MAP_NAME)`** (raw form **`localvar[N]`** / **`globalvar[N]`**) — typed CONSTANTS, not variables: the handler receives the number N (`Script_PrepActionArgs` never dereferences them). The listing names them only where the argument slot is known — a character id in actor slots, a map id in the schedule ops — and keeps `localvar[N]`/`globalvar[N]` elsewhere.

Operators build parenthesised infix — binary `*` `/` `%` `+` `-` `<` `>` `<=` `>=` `==` `!=` `&&` `||`; unary negate and logical-not; and the compound-assign forms `=` `*=` `/=` `%=` `+=` `-=` `&&=` `||=` (which write the result back into the target variable, e.g. `REG_X += 1`).

## Event Manager (em.bin) opcodes

Scenes bridge to **em.bin** Event-Manager entries via the bridge action opcodes `EvalCondScriptA` (371), `EvalCondScriptB` (372), `DispatchCondScriptEntry` (373), `CondScriptDispatchAltAction` (374), `SetFlagBitIfCond` (444) (each listed in the opcode index) — the `EvalCondScript*` pair test an entry's conditions, the `*DispatchCondScript*` / `*DispatchAltAction` pair run its main / alt action stream, and `SetFlagBitIfCond` sets a flag when an entry's condition holds — for their *plays-when* conditions and their flag / variable effects. Each entry is its own little bytecode — a system SEPARATE from the rf3.mc VM above — decoded by `rf4s_modkit/emscript.py` and shown/edited in the toolkit's Event Manager. Names come from the debug `emdeb.bin` (shipped alongside em.bin).

**Condition expression opcodes** — `op = byte & 0x7F`; the high bit means "OR with the next expr", so consecutive high-bit exprs form an OR-group and the groups AND together (`CondScript_EvalEntry`, RF4S.exe+0x23BDB0):

- `0` **TRUE**, `1` **FALSE** — constant guards.
- `2`/`3` **CondA**(id) and `4`/`5` **NOT CondA** — test named condition A (entry id as u16 / u32).
- `6`/`7` **CondB** and `8`/`9` **NOT CondB** — test named condition B.
- comparison of two operands: `0x10` == (equal), `0x20` != (not-equal), `0x30` > (greater), `0x40` >= (greater-or-equal) — signed when either operand is a signed literal or signed flag ref.

**Comparison operand types** — `type1 = (op>>2)&3`, `type2 = op&3` (`CondScript_ReadComparisonOperands`, RF4S.exe+0x23C1A0):

- `0` u32 literal · `1` signed u32 literal · `2` **query id** (a `Script_QueryGameState` id — a live game-state read, shown by its `emdeb.bin` query name) · `3` **flag ref** (an `emdeb.bin` `FLG_`/`REG_` variable: packed sign / size / width + bit-offset). Query ids and flag refs both resolve to their debug names in the editor.

**Action opcodes** — high nibble selects the op; the byte's low bits describe the operand (target mode `(b>>2)&3`, value type `b&3` = same encoding as a comparison operand; result is `target OP value`, target-first — no reverse-sub, unlike the rf3.mc expression VM) (`EMF_DispatchActionOpcode`, RF4S.exe+0x23C390):

- `0x00`/`0x10` **CALL** — invoke another em entry (main stream → its MAIN block, alt stream → its ALT; `0x00` = u16 entry id, `0x10` = u32).
- `0x20` **SET** — target = value.
- `0x30` **ADD** — target += value.
- `0x40` **SUB** — target -= value.
- `0x50` **MUL_S** — target *= value (signed).
- `0x60` **MUL_U** — target *= value (unsigned).
- `0x70` **DIV_S** — target /= value (signed).
- `0x80` **DIV_U** — target /= value (unsigned).
- `0x90` **MOD_S** — target %= value (signed).
- `0xA0` **MOD_U** — target %= value (unsigned).
- `0xB0` **MAX_S** — target = max(target, value) (signed).
- `0xC0` **MAX_U** — target = max (unsigned).
- `0xD0` **MIN_S** — target = min(target, value) (signed).
- `0xE0` **MIN_U** — target = min (unsigned).
- `0xF0` **SET_EQ_ZERO** — target = (value == 0).

## Reserved / unused slots

These dispatch-table slots carry no author-facing opcode (reserved, removed in the PC port, or table padding):

76, 368, 391, 491, 505, 526, 533, 550, 565, 583, 584, 585, 586, 608, 630, 636, 702, 703, 704, 705, 706, 707, 708, 709, 710, 711, 712, 713, 714, 715, 716, 717, 718, 719, 720, 721, 722, 723, 724, 725, 726, 727, 728, 729, 730, 731, 732, 733, 734, 735, 736, 737

## Opcode index (by number)

Every named action opcode by number (reserved slots omitted; see above).

| op | mnemonic | op | mnemonic | op | mnemonic |
|---:|:--|---:|:--|---:|:--|
| 0 | `nop` | 1 | `SetSceneCtxBit3FromArg` | 2 | `Wait` |
| 3 | `WaitReset` | 4 | `ConditionalJump` | 5 | `ShowNpcBubbleVariant` |
| 6 | `ShowNpcBubble` | 7 | `ShowNpcBubble` | 8 | `DialogueLine` |
| 9 | `DialogueLine` | 10 | `SetSpeakerVoice` | 11 | `SetDialogStateBit` |
| 12 | `BubbleLineV3` | 13 | `BubbleLineV3` | 14 | `BubbleLineV4` |
| 15 | `ShowSpeakerBubble` | 16 | `SetSpeakerMC` | 17 | `SetSpeakerMC` |
| 18 | `SetSpeakerVishnal` | 19 | `SetSpeakerVishnal` | 20 | `SetSpeakerClorica` |
| 21 | `SetSpeakerClorica` | 22 | `SetSpeakerVolkanon` | 23 | `SetSpeakerVolkanon` |
| 24 | `SetSpeakerForte` | 25 | `SetSpeakerForte` | 26 | `SetSpeakerKiel` |
| 27 | `SetSpeakerKiel` | 28 | `SetSpeakerBado` | 29 | `SetSpeakerBado` |
| 30 | `SetSpeakerMargaret` | 31 | `SetSpeakerMargaret` | 32 | `SetSpeakerDylas` |
| 33 | `SetSpeakerDylas` | 34 | `SetSpeakerArthur` | 35 | `SetSpeakerArthur` |
| 36 | `SetSpeakerPorcoline` | 37 | `SetSpeakerPorcoline` | 38 | `SetSpeakerXiaoPai` |
| 39 | `SetSpeakerXiaoPai` | 40 | `SetSpeakerLinFa` | 41 | `SetSpeakerLinFa` |
| 42 | `SetSpeakerAmber` | 43 | `SetSpeakerAmber` | 44 | `SetSpeakerIlluminata` |
| 45 | `SetSpeakerIlluminata` | 46 | `SetSpeakerDoug` | 47 | `SetSpeakerDoug` |
| 48 | `SetSpeakerBlossom` | 49 | `SetSpeakerBlossom` | 50 | `SetSpeakerDolce` |
| 51 | `SetSpeakerDolce` | 52 | `SetSpeakerJones` | 53 | `SetSpeakerJones` |
| 54 | `SetSpeakerNancy` | 55 | `SetSpeakerNancy` | 56 | `SetSpeakerLeon` |
| 57 | `SetSpeakerLeon` | 58 | `SetSpeakerVentuswill` | 59 | `SetSpeakerVentuswill` |
| 60 | `SetSpeakerSon` | 61 | `SetSpeakerSon` | 62 | `SetSpeakerDaughter` |
| 63 | `SetSpeakerDaughter` | 64 | `SetSpeakerPico` | 65 | `SetSpeakerPico` |
| 66 | `SetSpeakerguest25` | 67 | `SetSpeakerguest25` | 68 | `SetSpeakerguest26` |
| 69 | `SetSpeakerguest26` | 70 | `SetSpeakerBarrett` | 71 | `SetSpeakerBarrett` |
| 72 | `SetSpeakerRaven` | 73 | `SetSpeakerRaven` | 74 | `SetSpeakerguest29` |
| 75 | `SetSpeakerguest29` | 77 | `SetActorFacingAngle` | 78 | `SetActorFacingAngle` |
| 79 | `SetActorTurnAngle` | 80 | `SetActorTurnAngle` | 81 | `QueryActorMotionState` |
| 82 | `QueryActorMotionState` | 83 | `CloseDialogueBubbles` | 84 | `SetActorMotionField62` |
| 85 | `SetActorMotionField56` | 86 | `SetActorMotionField56` | 87 | `SetActorMotionField60` |
| 88 | `SetActorMotionField60` | 89 | `SetActorMotionMask` | 90 | `SetActorMotionMask` |
| 91 | `SetSceneBit` | 92 | `EndDialogue` | 93 | `SetDialogueSpeakerEmote` |
| 94 | `SetSpeakerEmote0` | 95 | `SetSpeakerEmote1` | 96 | `SetSpeakerEmote2` |
| 97 | `SetSpeakerEmote3` | 98 | `SetDialogueField161` | 99 | `TeleportActor` |
| 100 | `TeleportActor` | 101 | `PlaceOrFaceActor` | 102 | `PlaceOrFaceActor` |
| 103 | `TurnActorToAngle` | 104 | `TurnActorToAngle` | 105 | `QueryCalendarEventStub` |
| 106 | `RotateActorInPlace` | 107 | `TurnActorToFaceTarget` | 108 | `TurnActorToFaceTarget` |
| 109 | `TurnActorToFaceTarget` | 110 | `FaceEventActor` | 111 | `SetActorRotationRaw` |
| 112 | `SetActorRotationRaw` | 113 | `QueryActorRotating` | 114 | `QueryActorRotating` |
| 115 | `MoveActorToTile_LockAI` | 116 | `MoveActorToTile_LockAI` | 117 | `MoveActorToTile_LockAINoFace` |
| 118 | `MoveActorToTile_LockAINoFace` | 119 | `NpcWalkToTile` | 120 | `NpcWalkToTile` |
| 121 | `NpcMoveAlt` | 122 | `NpcMoveAlt` | 123 | `MoveActorByOffset` |
| 124 | `MoveActorByOffset` | 125 | `MoveActorByOffset_InterruptAI` | 126 | `MoveActorByOffset_InterruptAI` |
| 127 | `MoveActorByOffset_Continue` | 128 | `MoveActorByOffset_Continue` | 129 | `QueryActorAnimBusy` |
| 130 | `QueryActorAnimBusy` | 131 | `QueryActorBeyondRange` | 132 | `QueryActorBeyondRange` |
| 133 | `PlayActorAnim` | 134 | `PlayActorAnim` | 135 | `QueryActorTilePosition` |
| 136 | `QueryActorTilePosition` | 137 | `QueryNpcLoadedAndActive` | 138 | `QueryNpcLoadedAndActive` |
| 139 | `ApplyEffectToActor` | 140 | `ApplyEffectToActor` | 141 | `SetActorInvulnerable` |
| 142 | `MoveSceneActorToTile` | 143 | `MoveToCoords` | 144 | `MoveSceneActorStraight` |
| 145 | `QueryPlayerTurnBusy` | 146 | `EquipItemToPlayer` | 147 | `RestoreDefaultEquip` |
| 148 | `QueryPlayerFlag40000` | 149 | `PlayerScriptedTalkAnim` | 150 | `TriggerActionAtTile` |
| 151 | `TriggerActorAttack` | 152 | `WaitPlayerScriptSync` | 153 | `EventSpawnNpc` |
| 154 | `EventSpawnNpcVariant` | 155 | `EventSpawnNpcFollower` | 156 | `UnregisterEventActor` |
| 157 | `SpawnMapEntity` | 158 | `SetMapAmbientColor` | 159 | `SwapMapPalette` |
| 160 | `EventNpcWalkToTile` | 161 | `EventNpcWalkToTilePriority` | 162 | `SetMonsterFacing` |
| 163 | `FaceEventActorTowardTarget` | 164 | `QueryEventActorMoving` | 165 | `TriggerActionAtEventActor` |
| 166 | `ApplyEffectToEventActor` | 167 | `EventActorPlayAnim` | 168 | `EventActorResyncAnimFrame` |
| 169 | `WaitForEventActorReady` | 170 | `SetEventActorSpeedScale` | 171 | `SetEventActorAlpha` |
| 172 | `EventActorStopAnim` | 173 | `MarkCalendarEventCancelled` | 174 | `AddActorVerticalVelocity` |
| 175 | `SetEventActorStateWord` | 176 | `SetEventActorGreyscale` | 177 | `EventActorEnterIdle` |
| 178 | `SetEventActorTargetFacing` | 179 | `QueryEventActorTurning` | 180 | `KillEventActor` |
| 181 | `DismissEventActor` | 182 | `QueryEventActorTilePosition` | 183 | `SetEntityLevelAndRespawnAI` |
| 184 | `SetActorScriptedStateBit` | 185 | `PlayActorSplash` | 186 | `SetCameraPosition` |
| 187 | `ReattachCameraToActor` | 188 | `SnapCameraToPlayer` | 189 | `ResetCameraToPlayer` |
| 190 | `SetCameraTarget` | 191 | `ResetCameraToActor` | 192 | `ResetCameraToActor` |
| 193 | `SetCameraAnchorToPlayer` | 194 | `FocusCameraOnPlayer` | 195 | `WaitCameraAtMark` |
| 196 | `QueryPlayerMovedBeyondSnapshot` | 197 | `ShakeCamera` | 198 | `WaitForPlayerEffect` |
| 199 | `SetCameraTargetActor` | 200 | `SetCameraTargetActor` | 201 | `SetCameraSettleMode` |
| 202 | `SetCameraZoom` | 203 | `SetCameraMapBounds` | 204 | `SleepInBed` |
| 205 | `RefreshMapTiles` | 206 | `CancelNpcPathOrEquipMainhand` | 207 | `CancelNpcPathOrEquipMainhand` |
| 208 | `HandOrDropItem` | 209 | `GiveOrDropItem` | 210 | `AttachItemVisual` |
| 211 | `StopActorAnim` | 212 | `StopActorAnim` | 213 | `GetPlayerPosition` |
| 214 | `SetNpcStoryFlag` | 215 | `ClearNpcStoryFlag` | 216 | `QueryNpcInCurrentArea` |
| 217 | `ApplyFriendshipDelta` | 218 | `QueryNpcFriendshipLevel` | 219 | `QueryNpcFriendshipLevel` |
| 220 | `QueryAllNpcsFriendship` | 221 | `AdjustCurrentNpcFriendship` | 222 | `LockNpcPose` |
| 223 | `SetNpcEngaged` | 224 | `SetNpcEngaged` | 225 | `StreamInNpc` |
| 226 | `QueryNpcScheduleId` | 227 | `QueryNpcScheduleIsOneOf` | 228 | `QueryNpcScheduleIsOneOf` |
| 229 | `QueryNpcAvailableFlagClear` | 230 | `ReleaseNpcLocks` | 231 | `ReleaseNpcLocks` |
| 232 | `QueryNpcHidden` | 233 | `HideNpc` | 234 | `HideNpc` |
| 235 | `QueryNpcSeenToggle` | 236 | `QueryNpcInteractEligible` | 237 | `QueryNpcPairInteraction` |
| 238 | `QueryQuestNpcsAvailable` | 239 | `QueryQuestNpcsAvailable` | 240 | `QueryNpcGroupPresentNearby` |
| 241 | `QueryNpcGroupPresentNearby` | 242 | `SetSceneFlag0x200` | 243 | `EndDialogueLock` |
| 244 | `NpcShowItem` | 245 | `QueryGiftAffinity` | 246 | `StreamInNpcAtTile` |
| 247 | `QueryTileFacingTarget` | 248 | `SetNpcVisibleFlag` | 249 | `SetNpcVisibleFlag` |
| 250 | `SyncActorAnimFrame` | 251 | `SyncActorAnimFrame` | 252 | `SetActorAnimSpeedScale` |
| 253 | `SetActorAnimSpeedScale` | 254 | `SetActorAnimFrameDirect` | 255 | `QueryEntityActionStatus` |
| 256 | `SetActorStatusConditions` | 257 | `QueryAllNpcsEligibleForComment` | 258 | `QueryAllNpcsEligibleForComment` |
| 259 | `QueryNpcRosterPresence` | 260 | `QueryActorHpWellness` | 261 | `SetNpcParticipationFlag` |
| 262 | `QueryCurrentInteractionNpc` | 263 | `RespawnNpcAtSchedulePos` | 264 | `RespawnNpcAtSchedulePos` |
| 265 | `QueryPlayerDeadOrCompanionScripted` | 266 | `SetOrClearNpcSchedule` | 267 | `SetOrClearNpcSchedule` |
| 268 | `QueryNpcArrivedAtSchedule` | 269 | `QueryNpcArrivedAtSchedule` | 270 | `RefreshNpcSchedule` |
| 271 | `RefreshNpcSchedule` | 272 | `nop` | 273 | `QueryNpcPresent` |
| 274 | `QueryNpcPresent` | 275 | `SetNpcPresenceState` | 276 | `QueryNpcModelId` |
| 277 | `QueryNpcModelId` | 278 | `QueryNpcFavoriteItem` | 279 | `QueryNpcFavoriteItem` |
| 280 | `QueryNpcDateState` | 281 | `ApplyNpcDateOutcome` | 282 | `QueryNpcActorPresent` |
| 283 | `QueryCompanionNpcId` | 284 | `MountActor` | 285 | `SetSceneReadyFlag` |
| 286 | `ShakeActor` | 287 | `SetNpcOutfit` | 288 | `QueryNpcActorStateWord` |
| 289 | `CarryBaby` | 290 | `PostFamilyMilestones` | 291 | `SpawnChildEventRecords` |
| 292 | `CommitMarriage` | 293 | `ResetNpcDailySchedule` | 294 | `ResetNpcDailySchedule` |
| 295 | `ResetNpcScheduleWithState` | 296 | `ApplyNpcScheduleState` | 297 | `ApplyNpcScheduleState` |
| 298 | `ApplyPendingNpcPlan` | 299 | `ApplyPendingNpcPlan` | 300 | `AdvanceDay` |
| 301 | `RefreshNpcScheduleForToday` | 302 | `SetNpcActionDelay` | 303 | `SetNpcActionDelay` |
| 304 | `GetMinute` | 305 | `GetSeason` | 306 | `GetDay` |
| 307 | `GetMonthSeason` | 308 | `GetDateSnapshot` | 309 | `IsFrey` |
| 310 | `QueryPlayerIsLest` | 311 | `HealPartyFull` | 312 | `HealPartyByShift` |
| 313 | `RestorePlayerRP` | 314 | `CurePartyStatus` | 315 | `QueueNpcGreetingEvent` |
| 316 | `SetNpcVisible` | 317 | `SetNpcVisibility` | 318 | `SetFlag` |
| 319 | `SetEmote` | 320 | `SetNpcEmoteByte` | 321 | `GetEmote` |
| 322 | `SetMood` | 323 | `SetNpcMoodByte` | 324 | `GetMood` |
| 325 | `GetLumber` | 326 | `ModifyLumber` | 327 | `SetActorOutfitVariant` |
| 328 | `PlayActorTransform` | 329 | `IsPosing` | 330 | `SetOutfitDirect` |
| 331 | `SetActorOutfitDirect` | 332 | `PlayScriptedBeat` | 333 | `BeginBeat2` |
| 334 | `FadeScreen` | 335 | `FadeScreenToClear` | 336 | `SetFadeColor` |
| 337 | `WaitForFade` | 338 | `CheckNpcSchedule` | 339 | `GetNpcSchedule` |
| 340 | `SetVar0` | 341 | `SetVar0` | 342 | `GetVar0` |
| 343 | `SetVar1` | 344 | `GetVar1` | 345 | `SetVar11` |
| 346 | `GetVar11` | 347 | `SetVar2` | 348 | `SetVar2` |
| 349 | `SetVar3` | 350 | `GetVar3` | 351 | `SetVar4` |
| 352 | `GetVar4` | 353 | `SetVar5` | 354 | `GetVar5` |
| 355 | `SetVar6` | 356 | `GetVar6` | 357 | `SetVar7` |
| 358 | `GetVar7` | 359 | `SetVar8` | 360 | `GetVar8` |
| 361 | `SetVar9` | 362 | `GetNpcBirthdayMonthAndDay` | 363 | `GetEventMonthOrBirthFlag` |
| 364 | `SetVar10` | 365 | `SetVar15` | 366 | `SetVar13` |
| 367 | `GetVar14` | 369 | `QueryPlayerCanInteract` | 370 | `SetSceneStateBit1` |
| 371 | `EvalCondScriptA` | 372 | `EvalCondScriptB` | 373 | `DispatchCondScriptEntry` |
| 374 | `CondScriptDispatchAltAction` | 375 | `TriggerWorldAction` | 376 | `BeginShopkeeperInteraction` |
| 377 | `GetChoiceResult` | 378 | `GetChoiceResult` | 379 | `PlayMusic` |
| 380 | `StopMusic` | 381 | `nop` | 382 | `SetSfxVolume` |
| 383 | `SetSfxDuckingBypass` | 384 | `ResetSfxScratch` | 385 | `PlaySound` |
| 386 | `StopVoices` | 387 | `PlaySfxWithNpcRemap` | 388 | `nop` |
| 389 | `FindVoiceSlot` | 390 | `StopVoiceId` | 392 | `PlayVoicedSound` |
| 393 | `FreezePlayer` | 394 | `WarpPlayer` | 395 | `SetPlayerPose` |
| 396 | `SetPlayerFacingAndPose` | 397 | `SetPartyOutfit` | 398 | `QueryUnusedPoses` |
| 399 | `GetPlayerSubstate` | 400 | `SetPlayerLestOrFrey` | 401 | `MonsterFarmSpawn` |
| 402 | `SendMonsterToFarmOrClearFlags` | 403 | `GetMonsterRosterAbsent` | 404 | `GetMonsterRosterPresent` |
| 405 | `SetMonsterFarmLovedToday` | 406 | `GetMonsterFarmLovedToday` | 407 | `QueryActiveKillCount` |
| 408 | `CountLivingEnemies` | 409 | `CountTamedFarmMonsters` | 410 | `TameEventMonster` |
| 411 | `QueryCompanionMonsterData` | 412 | `BlackScreen` | 413 | `SetDialogueState8` |
| 414 | `GetChoiceIndexAndItem` | 415 | `SetDialogueFlag4Bit2` | 416 | `QueryPlayerVariable` |
| 417 | `ModifyPlayerResource` | 418 | `QueryBackpackHasOccupiedSlot` | 419 | `QueryBackpackHasFreeSlot` |
| 420 | `QueryBackpackFreeSlots` | 421 | `SetupPendingInteraction` | 422 | `SetupPendingInteractionV2` |
| 423 | `GiveItem` | 424 | `GivePlayerItem` | 425 | `ForcePlayerHoldItem` |
| 426 | `IsExtrasSlotFull` | 427 | `MaxWeaponSkills` | 428 | `TakeItem` |
| 429 | `TakeItemFromBackpack` | 430 | `ConsumeHeldItem` | 431 | `HasItem` |
| 432 | `CheckCropPlantable` | 433 | `QueryFishSizeRecords` | 434 | `GetItemGoldValue` |
| 435 | `GetItemBuyPrice` | 436 | `IsItemStackable` | 437 | `NpcWantsItem` |
| 438 | `QueryHasItemOfCategory` | 439 | `ReleaseFarmMonster` | 440 | `GetNpcSpecies` |
| 441 | `QueryConfirmButton` | 442 | `QueryStickInputActive` | 443 | `SetFlagBit` |
| 444 | `SetFlagBitIfCond` | 445 | `GetFlagBit` | 446 | `SetWeather` |
| 447 | `GetWeather` | 448 | `SetWeatherTransition` | 449 | `GetWeatherTransition` |
| 450 | `GetWeatherStreak` | 451 | `GetDayOfWeek` | 452 | `SpawnItemAtTile` |
| 453 | `DropStagedItem` | 454 | `SpawnItemVisual` | 455 | `DespawnItemVisuals` |
| 456 | `QueryEquippedItemAttr` | 457 | `ShowRewardPopup` | 458 | `ShowQuestReward` |
| 459 | `ShowRewardPopupAtTile` | 460 | `AddRewardItem` | 461 | `SuppressRewardJingle` |
| 462 | `GrantFestivalRewards` | 463 | `DropItem` | 464 | `DropItemStack` |
| 465 | `SetCalendarPauseFlag` | 466 | `SkipToTime` | 467 | `SetTime` |
| 468 | `FastForwardCalendar` | 469 | `SetOrAddCalendarDate` | 470 | `GetChildFriendLevel` |
| 471 | `GetChildFriendPoints` | 472 | `SetChildGrowthValue` | 473 | `RollChildDailyPref` |
| 474 | `SetEventLeadNpc` | 475 | `SetNpcStateByte` | 476 | `SpawnNpc` |
| 477 | `StreamInNpcAtPlayer` | 478 | `SpawnNpcScripted` | 479 | `StreamNpcAtPlayer` |
| 480 | `WakeSceneNpcChild` | 481 | `GetPartyMemberId` | 482 | `GetPartyMemberId` |
| 483 | `SyncCompanions` | 484 | `SyncBothCompanions` | 485 | `SyncBothCompanionsWithFlags` |
| 486 | `SyncCompanionByCharId` | 487 | `QueryCurrentNpcInParty` | 488 | `SetCompanionScriptedPresence` |
| 489 | `SetCompanionMetFlag` | 490 | `QueryMarriagePartnerInParty` | 492 | `FaceNpcToPlayer` |
| 493 | `GetNpcFacingMode` | 494 | `SetCompanionInvulnerable` | 495 | `WarpCompanion` |
| 496 | `MoveCompanion` | 497 | `MoveCompanionNF` | 498 | `MoveCompanionRel` |
| 499 | `MoveCompanionRelNF` | 500 | `SetCompanionPose` | 501 | `CompanionFaceTarget` |
| 502 | `IsCompanionMoving` | 503 | `StopCompanionAnim` | 504 | `QueryPartyMemberTileY` |
| 506 | `WarpMonstersToPlayer` | 507 | `PopulateNpcQuestRequest` | 508 | `PopulateQuestKind2RandomAlts` |
| 509 | `PopulateQuestKind2RandomAlts` | 510 | `PopulateQuestKind2WithLiteralAlternates` | 511 | `PopulateQuestKind3TwoItemsRandomCats` |
| 512 | `PopulateQuestKind3TwoItemsRandomCats` | 513 | `PopulateQuestKind4ChainedRandom` | 514 | `PopulateQuestKind4ChainedRandom` |
| 515 | `PopulateQuestKind4Byte4_1LiteralAlts` | 516 | `PopulateQuestKind5SimpleNoAlts` | 517 | `PopulateQuestKind5SimpleNoAlts` |
| 518 | `PopulateQuestKind6TwoArgsNoItem` | 519 | `PopulateQuestKind7CraftRecipeExpose` | 520 | `PostQuestGoalNumber` |
| 521 | `PopulateQuestKind9BackrefLiteralAlts` | 522 | `PopulateQuestKind10BackrefRandomCats` | 523 | `PopulateQuestKind10BackrefLiteralAlts` |
| 524 | `CommitThrowQueue` | 525 | `QuestOnComplete` | 527 | `AdvanceRng` |
| 528 | `QueryQuestRewardItem` | 529 | `ClearQuestRewardTemplates` | 530 | `CommitQuestAcceptance` |
| 531 | `QuestSceneTeardown` | 532 | `QueryNpcQuestPreview` | 534 | `GetDailyVisitor` |
| 535 | `QueryQuestRemainingByItem` | 536 | `RequestBoxFirstSubmit` | 537 | `PopulateQuestKind2WithRandomCats` |
| 538 | `PopulateQuestKind2WithRandomCats` | 539 | `PopulateQuestKind3TwoItemsRandomCats` | 540 | `PopulateQuestKind3TwoItemsRandomCats` |
| 541 | `PopulateQuestKind4ChainedRandom` | 542 | `PopulateQuestKind4ChainedRandom` | 543 | `PopulateQuestKind5SimpleNoAlts` |
| 544 | `PopulateQuestKind5SimpleNoAlts` | 545 | `PopulateQuestKind6TwoArgsNoItem` | 546 | `PopulateQuestKind7CraftRecipeExpose` |
| 547 | `PopulateQuestKind10BackrefRandomCats` | 548 | `CommitThrowQueue` | 549 | `RequestBoxClaimFinalize` |
| 551 | `ResetThrowQueue` | 552 | `GetThrowQueueRemaining` | 553 | `SetNpcScriptedPresence` |
| 554 | `SetNpcScriptedPresence` | 555 | `SetNpcBubbleFlavor` | 556 | `SetNpcBubbleFlavor` |
| 557 | `SetNpcRecognitionFlags` | 558 | `SetNpcRecognitionFlags` | 559 | `StartFestivalContest` |
| 560 | `StageSceneNpcs` | 561 | `GetSceneStateBytes` | 562 | `RefreshSceneNpcs` |
| 563 | `EquipScriptedWeapon` | 564 | `RemoveScriptedWeapon` | 566 | `AdvanceStoryMilestone` |
| 567 | `GetTomorrowsBirthdayNpc` | 568 | `GetSceneNpc` | 569 | `RankFestivalContestants` |
| 570 | `GetTodaysRequestNpc` | 571 | `SetSceneScratch` | 572 | `GetSceneScratchByte` |
| 573 | `GetFestivalPlacements` | 574 | `ShuffleSceneBuffer` | 575 | `GetShuffleValue` |
| 576 | `GetSceneEventNpc` | 577 | `GetEventParticipants` | 578 | `SpawnEventMonsters` |
| 579 | `GetSceneEventFlags` | 580 | `GetHeldItemStats` | 581 | `CheckFishRecord` |
| 582 | `GetFishRecord` | 587 | `GiveTileObject` | 588 | `IsTileObjectActive` |
| 589 | `PlayerPickUpObject` | 590 | `OpenRequestBox` | 591 | `ClearAllTileObjects` |
| 592 | `CanPlaceTileObject` | 593 | `PickRandomTileObject` | 594 | `CommitGrabbedObject` |
| 595 | `SetMinimapMarker` | 596 | `RollUniformIntegerLessThanN` | 597 | `RollShopCategoryItemReturnId` |
| 598 | `RollRandomItemMatchingDisplayName` | 599 | `LootRollGenericFromTable` | 600 | `RollRandomShopItem` |
| 601 | `RollRandomRingItemIdInTier` | 602 | `RollRandomTurnipFamilyItemIdInTier` | 603 | `ShopRollByCategoryRange` |
| 604 | `RollRandomMineralOrIngredientItemIdInTier` | 605 | `RollRandomFilteredItem` | 606 | `RollThreeFlowerItemsAvoidDup` |
| 607 | `RollRandomItemByLookupBytemask28` | 609 | `RollRandomPointInRadiusAroundCenter` | 610 | `SetChoiceVisibleMask` |
| 611 | `ClearChoiceVisibleRange` | 612 | `SetChoiceVisibleBit` | 613 | `CalcChoicePrescroll` |
| 614 | `SetDialogueSpeaker` | 615 | `ArmChoiceOption` | 616 | `QueryAndSetCraftedFlag` |
| 617 | `ShowCreditsOverlay` | 618 | `IsPickingUpItem` | 619 | `QueryNpcAdmireResponse` |
| 620 | `UnlockMonsterDex` | 621 | `SetDifficulty` | 622 | `QueryDifficulty` |
| 623 | `SetDialogueAutoAdvance` | 624 | `SetDialogueHoldFrames` | 625 | `BeginDungeonArea` |
| 626 | `GetInventoryFlagBit` | 627 | `SleepToMorning` | 628 | `SetRegisters` |
| 629 | `SetRegisters` | 631 | `RollSeededHashByMode16` | 632 | `RollSeededDailyRandom` |
| 633 | `ResetActionEventId` | 634 | `SetActionTriggerByte` | 635 | `GetActionTriggerByte` |
| 637 | `SaveCalendarSnapshot` | 638 | `GetForecasts` | 639 | `GetPrincePoints` |
| 640 | `AddPrincePoints` | 641 | `GetTourists` | 642 | `AddTourists` |
| 643 | `TriggerEffect` | 644 | `GetEffectState` | 645 | `PromotePrinceRank` |
| 646 | `GetPrinceRank` | 647 | `GetEffectCost` | 648 | `QueryTownDevelopment` |
| 649 | `QueryShippingBoxGold` | 650 | `GetLifetimeCropGold` | 651 | `AdvanceStoryProgress` |
| 652 | `GetSceneWord348` | 653 | `ClearShopSelectionA` | 654 | `ClearShopSelectionB` |
| 655 | `ClearShopSelectionC` | 656 | `SetMapScrollSpeedX` | 657 | `SetMapScrollSpeedY` |
| 658 | `GetSceneWordPair112` | 659 | `MyShopAction` | 660 | `SetActorStatusFlag` |
| 661 | `SetActorStatFlagRecompute` | 662 | `SetActorArmorBreak` | 663 | `DisableActorHpRegen` |
| 664 | `LockActorMaxSp` | 665 | `SetActorFacing` | 666 | `QuerySaveConfigBit0` |
| 667 | `SetSaveConfigBit0` | 668 | `QuerySaveConfigBit4` | 669 | `SetSaveConfigBit4` |
| 670 | `QuerySaveConfigBit5` | 671 | `SetSaveConfigBit5` | 672 | `QuerySaveConfigBit2` |
| 673 | `QuerySaveConfigBit3` | 674 | `GetRuneMedals` | 675 | `ConvertMedalsToGold` |
| 676 | `GetConst20` | 677 | `SpawnTileEffectObject` | 678 | `ClearTileAttribsInRect` |
| 679 | `IncrementPlayerSkillLevel` | 680 | `ApplyAttackToPlayer` | 681 | `LootRollByCategoryForPlayer` |
| 682 | `SetSceneFlag400` | 683 | `PlayCutsceneVideo` | 684 | `QuerySaveConfigBitByIdx` |
| 685 | `SetGlobalScratch` | 686 | `GetGlobalScratch` | 687 | `RebuildMinimap` |
| 688 | `ToggleMinimap` | 689 | `ResetMonsterSpawns` | 690 | `GetNpcProgressAndProp` |
| 691 | `MultiplyValues` | 692 | `OnFirstMarriageAccepted` | 693 | `nop` |
| 694 | `QuerySaveConfigBit1` | 695 | `QueryMonsterDexBit` | 696 | `RemoveItemFromBackpack` |
| 697 | `ReturnToTitle` | 698 | `SetShopkeeperMessage` | 699 | `SetDialogueSpeakerIf` |
| 700 | `QueryBackpackHasItem` | 701 | `SetPlayerSkillXp` | 738 | `NpcAction_Kind0_LieDownToSleep` |
| 739 | `Npc_TickWanderBehavior` | 740 | `NpcAction_PlayKindIdleAnim` | 741 | `NpcAction_PlayKindIdleAnim` |
| 742 | `NpcAction_PlayKindIdleAnim` | 743 | `NpcAction_PlayKindIdleAnim` | 744 | `NpcAction_PlayKindIdleAnim` |
| 745 | `NpcAction_PlayKindIdleAnim` | 746 | `NpcAction_PlayKindIdleAnim` | 747 | `NpcAction_Kind9_LookAroundIdle` |
| 748 | `NpcAction_Kind10_GreetThenBow` | 749 | `NpcAction_PlayKindIdleAnim` | 750 | `NpcAction_PlayKindIdleAnim` |
| 751 | `NpcAction_Kind13_GiftAndTeleportOut` | 752 | `NpcAction_Kind14_DelayedIdleAnim` | 753 | `NpcAction_Kind15_SleepOrExitHome` |
| 754 | `NpcAction_PlayKindIdleAnim` | 755 | `NpcAction_Kind17_EatFood` | 756 | `NpcAction_Kind18_RandomTimerIdleAnim` |
| 757 | `NpcAction_Kind19_ChatByFriendshipLevel` | 758 | `NpcAction_Kind20_EquipTool506` | 759 | `NpcAction_PlayKindIdleAnim` |
| 760 | `NpcAction_Kind22_EquipTool483` | 761 | `NpcAction_Kind23_EquipHeldTool` | 762 | `NpcAction_Kind24_RandomGreetGesture` |
