# RF4S Cutscene Opcode Reference

Reverse-engineered `rf3.mc` cutscene Script VM opcodes (`g_sceneActionHandlerTable`, RF4S.exe+0x4DB790, 763 slots).

Auto-generated from `rf4s_modkit/opcode_meta.py` by `gen_opcode_reference.py` — **726** named opcodes across 14 categories (plus 37 reserved/unused slots), the control-flow opcodes, the expression grammar, and the **em.bin** Event-Manager opcodes scenes bridge to. Do not edit by hand; re-run the generator to refresh. This is the GUI-free companion to the editor's Alt-hover tooltips.

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
- [No-op (PC-port stub)](#no-op-pc-port-stub) (20 ops)
- [Control opcodes (flow backbone)](#control-opcodes-flow-backbone) (15 ops)
- [Expression operands (argument encoding)](#expression-operands-argument-encoding)
- [Event Manager (em.bin) opcodes](#event-manager-embin-opcodes)
- [Opcode index (by number)](#opcode-index-by-number)

## Dialogue & portraits

### `op 5` — ShowPortrait(character id, expression, side)
*handler:* `Script_VMOp_ShowNpcBubbleVariant`

Show or update a character's E-mote portrait (no name plate, no text-blip change, no emote icon, no voice). arg0 = character id (0 = player), arg1 = expression (<1000 = that character's face index, 1000..1927 = raw expression entry, 255/254 = special reset values), arg2 = side (0 / 1). Returns busy while a screen fade runs.

Args:
  0. character id (0=player)
  1. expression (face index; 1000+ = raw entry)
  2. side (0/1)

### `op 6` — ShowPortraitWithEmote(character id, side, expression, emote icon)
*handler:* `Script_VMOp_ShowNpcBubble`

Show or update a character's E-mote portrait by character id, optionally with an emote icon or a voice clip; does not touch the name plate or text blip. arg0 = character id (0 = player), arg1 = side (0/1), arg2 = expression (<1000 = face index, 1000..1927 = raw expression entry), arg3 = trigger: >= 0x1F0 plays that voice/sfx through Sfx_PlayByIdWithNpcVariantRemap, otherwise an emote-icon id (186..192) queued on the portrait (0 = none). Busy while a fade runs.

Args:
  0. character id (0=player)
  1. side (0/1)
  2. expression (face index; 1000+ = raw entry)
  3. emote icon (186-192) or voice sfx id (>=0x1F0)

### `op 7` — ShowPortraitWithEmote(character id, side, expression, emote icon)
*handler:* `Script_VMOp_ShowNpcBubble`

Show or update a character's E-mote portrait by character id, optionally with an emote icon or a voice clip; does not touch the name plate or text blip. arg0 = character id (0 = player), arg1 = side (0/1), arg2 = expression (<1000 = face index, 1000..1927 = raw expression entry), arg3 = trigger: >= 0x1F0 plays that voice/sfx through Sfx_PlayByIdWithNpcVariantRemap, otherwise an emote-icon id (186..192) queued on the portrait (0 = none). Busy while a fade runs.

Args:
  0. character id (0=player)
  1. side (0/1)
  2. expression (face index; 1000+ = raw entry)
  3. emote icon (186-192) or voice sfx id (>=0x1F0)

### `op 8` — SetSpeakerName(name id)
*handler:* `Dialogue_ProcessLineDirective`

Set the message-box NAME PLATE (and the matching text blip) for the following DIALOG lines; shows no text and no portrait. arg0 = name id: 0 = the player's own saved name with the player's blip ('???' instead before main-scenario progress 2 or in state 0x401000), 1..26 = that villager's name (22/23 = the child names from the prebuilt child-name buffer, not the archive) (chime class from Dialogue_PickChimeClassForSpeaker, g_lastDialogueEmoteId from the NPC's byte +57), 27..47 = an event participant resolved at run time via g_eventNpcParticipants (27-33 / 41-47 also show its portrait, Dialogue_LoadEventLineWithPortrait), >= 48 = any entry of the task's name archive, 0xFFFF = the '???' placeholder. Latched at host+108 (repeating the same id does nothing); also clears the name-hide bit (entries[4] bit 0) except on the 0xFFFF path.

Args:
  0. name id (0 = player's own name, 1-26 villager, 27-47 event participant, >=48 name-archive entry, 0xFFFF '???')

### `op 9` — SetSpeakerName(name id)
*handler:* `Dialogue_ProcessLineDirective`

Set the message-box NAME PLATE (and the matching text blip) for the following DIALOG lines; shows no text and no portrait. arg0 = name id: 0 = the player's own saved name with the player's blip ('???' instead before main-scenario progress 2 or in state 0x401000), 1..26 = that villager's name (22/23 = the child names from the prebuilt child-name buffer, not the archive) (chime class from Dialogue_PickChimeClassForSpeaker, g_lastDialogueEmoteId from the NPC's byte +57), 27..47 = an event participant resolved at run time via g_eventNpcParticipants (27-33 / 41-47 also show its portrait, Dialogue_LoadEventLineWithPortrait), >= 48 = any entry of the task's name archive, 0xFFFF = the '???' placeholder. Latched at host+108 (repeating the same id does nothing); also clears the name-hide bit (entries[4] bit 0) except on the 0xFFFF path.

Args:
  0. name id (0 = player's own name, 1-26 villager, 27-47 event participant, >=48 name-archive entry, 0xFFFF '???')

### `op 10` — SetSpeakerVoice(name string id, text blip)
*handler:* `NpcBubble_DispatchSimpleScriptedLine`

Set the speaker for the following DIALOG line(s) to a NAMED VOICE: name plate only, NO portrait ('no portrait dispatch' — the handler's own contract). This is how off-screen and un-introduced characters speak — the opening's captain monologue (name string 738) and the stowaway bandits' whispers (392) both talk through it. arg0 = the NAME-PLATE string id: an entry of the character-name archive (the same list as char_names.json -- 21 Ventuswill, 236 Ethelwill, 392 '???', 738 Joyful Captain; not an rf3mc line id), shown through Dialogue_LoadAndShowText(archive, id, 2) and latched at task+108 so repeating it is free. arg1 = the TEXT BLIP, the tick sound played while the line types out (Dialogue_SetTickChimeSfxId; no voice acting is involved; the typewriter, Sprite_TickTypewriterDripText RF4S.exe+0x246AD0, plays it on every 4th character and restarts the count at each line break): 0 = male blip (sfx 16785916 = SE_WORDS_M.wav), 1 = female blip (16785917 = SE_WORDS_F.ogg), 2 = monster / animal blip (16785918 = SE_WORDS_O.wav; Buffamoo, Fiergaenger), 3 = dragon blip (16785975 = SE_WORDS_D.wav; Ventuswill in dragon form, Ancient Bone) -- names from common_audio_data.bdat, the files sit in bundleMain; 4+ = the PLAYER's own blip -- male for Lest's model (model 1217 = NPC_PLAYER_00), female for Frey's (1233 = NPC_PLAYER_01), male again when neither and player control flag 0x8000000 is set. Shipped uses: 651x 0, 170x 1, 5x 2, 105x 3 (931 in all). IDA-verified (NpcBubble_DispatchSimpleScriptedLine, RF4S.exe+0x20A240).

Args:
  0. name string id (name archive)
     - *(enum: 1000 values — use the in-editor picker or the id database)*
  1. text blip (0 male, 1 female, 2 monster, 3 dragon, 4+ player's)
     - `0` = male blip
     - `1` = female blip
     - `2` = monster blip
     - `3` = dragon blip
     - `4` = player's blip

### `op 11` — SetSpeakerNameVisible(name label)
*handler:* `ScriptVMOp11_SetSceneStateBit0FromArg`

Show or hide the speaker name label for the following DIALOG lines: arg0 == 0 sets the name-hide bit (g_gameGlobalsSlotTable entries[4] bit 0), any non-zero value clears it; DialogueBox_SpawnBubbleAndSpeakerNameSprites and Dialogue_LoadAndShowText copy the bit into the name-label sprite's hidden flag. Every Dialogue_LoadAndShowText call clears the bit again (it sets it only for name id 0xFFFF), so a later speaker cue that loads a new name re-shows the label.

Args:
  0. name label (0 = hide, non-zero = show)
     - `0` = hide name
     - `1` = show name

### `op 12` — SetSpeakerById(speaker, face, side)
*handler:* `NpcBubble_DispatchScriptedLineV3Tokens`

Speaker cue by CHARACTER ID (the generic form of ops 16-75, without emote/voice triggers): arg0 = speaker char id (portrait + name plate + text blip; name via Dialogue_RemapBubbleLineId24To28, 24..28 -> 309/149/239/24/25), arg1 = face index compacted to a class (0-1 -> 0, 2-4 -> 1, 5-8 -> 2, 9-11 -> 3, 12-15 -> 4, 16-18 -> 1, 19 -> 5, >= 20 passed through raw), arg2 = side (0/1; also the side for Dialogue_LoadAndShowText). Clears host+864; busy while a fade runs.

Args:
  0. speaker (char id, 0=player)
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
  1. face (compacted to 0-5)
  2. side (0/1)

### `op 13` — SetSpeakerById(speaker, face, side)
*handler:* `NpcBubble_DispatchScriptedLineV3Tokens`

Speaker cue by CHARACTER ID (the generic form of ops 16-75, without emote/voice triggers): arg0 = speaker char id (portrait + name plate + text blip; name via Dialogue_RemapBubbleLineId24To28, 24..28 -> 309/149/239/24/25), arg1 = face index compacted to a class (0-1 -> 0, 2-4 -> 1, 5-8 -> 2, 9-11 -> 3, 12-15 -> 4, 16-18 -> 1, 19 -> 5, >= 20 passed through raw), arg2 = side (0/1; also the side for Dialogue_LoadAndShowText). Clears host+864; busy while a fade runs.

Args:
  0. speaker (char id, 0=player)
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
  1. face (compacted to 0-5)
  2. side (0/1)

### `op 14` — SetSpeakerByIdWithEmote(speaker, side, expression, emote icon)
*handler:* `NpcBubble_DispatchScriptedLineV4TokensWithEmoteSupport`

Speaker cue by CHARACTER ID (runtime-selectable form of ops 16-75): arg0 = speaker char id (name plate via Dialogue_LoadAndShowText when it differs from host+108, text blip via Dialogue_PickChimeClassForSpeaker, portrait; with save-config flag 0x40, ids >= 30 are first mapped through g_npcEmotePsbTable), arg1 = side (0 left / 1 right; passed both to the portrait descriptor and as Dialogue_LoadAndShowText's side), arg2 = expression (<1000 face index, 1000..1927 raw expression entry), arg3 = emote icon 186-192 (queued on the portrait) or a voice sfx id >= 0x1F0 (played). Busy while a fade runs.

Args:
  0. speaker (char id, 0=player)
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
  1. side (0/1)
  2. expression (face index; 1000+ = raw entry)
  3. emote icon (186-192) or voice sfx id (>=0x1F0)

### `op 15` — SetSpeakerByIdWithEmote(speaker, side, expression, emote icon)
*handler:* `NpcBubble_DispatchScriptedLineV4TokensWithEmoteSupport`

Speaker cue by CHARACTER ID (runtime-selectable form of ops 16-75): arg0 = speaker char id (name plate via Dialogue_LoadAndShowText when it differs from host+108, text blip via Dialogue_PickChimeClassForSpeaker, portrait; with save-config flag 0x40, ids >= 30 are first mapped through g_npcEmotePsbTable), arg1 = side (0 left / 1 right; passed both to the portrait descriptor and as Dialogue_LoadAndShowText's side), arg2 = expression (<1000 face index, 1000..1927 raw expression entry), arg3 = emote icon 186-192 (queued on the portrait) or a voice sfx id >= 0x1F0 (played). Busy while a fade runs.

Args:
  0. speaker (char id, 0=player)
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
  1. side (0/1)
  2. expression (face index; 1000+ = raw entry)
  3. emote icon (186-192) or voice sfx id (>=0x1F0)

### `op 16` — SetSpeakerMC(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 0 = Lest/Frey (player) (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate with the player's saved name (Dialogue_LoadAndShowText id 0 -> Save_GetPlayerNameOrDefault; '???' before main-scenario progress 2); also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 17` — SetSpeakerMC(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 0 = Lest/Frey (player) (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate with the player's saved name (Dialogue_LoadAndShowText id 0 -> Save_GetPlayerNameOrDefault; '???' before main-scenario progress 2); also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 18` — SetSpeakerVishnal(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 1 = Vishnal (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 1; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 19` — SetSpeakerVishnal(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 1 = Vishnal (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 1; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 20` — SetSpeakerClorica(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 2 = Clorica (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 2; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 21` — SetSpeakerClorica(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 2 = Clorica (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 2; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 22` — SetSpeakerVolkanon(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 3 = Volkanon (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 3; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 23` — SetSpeakerVolkanon(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 3 = Volkanon (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 3; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 24` — SetSpeakerForte(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 4 = Forte (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 4; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 25` — SetSpeakerForte(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 4 = Forte (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 4; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 26` — SetSpeakerKiel(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 5 = Kiel (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 5; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 27` — SetSpeakerKiel(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 5 = Kiel (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 5; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 28` — SetSpeakerBado(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 6 = Bado (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 6; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 29` — SetSpeakerBado(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 6 = Bado (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 6; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 30` — SetSpeakerMargaret(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 7 = Margaret (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 7; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 31` — SetSpeakerMargaret(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 7 = Margaret (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 7; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 32` — SetSpeakerDylas(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 8 = Dylas (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 8; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 33` — SetSpeakerDylas(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 8 = Dylas (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 8; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 34` — SetSpeakerArthur(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 9 = Arthur (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 9; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 35` — SetSpeakerArthur(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 9 = Arthur (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 9; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 36` — SetSpeakerPorcoline(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 10 = Porcoline (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 10; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 37` — SetSpeakerPorcoline(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 10 = Porcoline (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 10; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 38` — SetSpeakerXiaoPai(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 11 = Xiao Pai (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 11; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 39` — SetSpeakerXiaoPai(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 11 = Xiao Pai (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 11; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 40` — SetSpeakerLinFa(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 12 = Lin Fa (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 12; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 41` — SetSpeakerLinFa(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 12 = Lin Fa (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 12; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 42` — SetSpeakerAmber(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 13 = Amber (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 13; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 43` — SetSpeakerAmber(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 13 = Amber (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 13; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 44` — SetSpeakerIlluminata(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 14 = Illuminata (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 14; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 45` — SetSpeakerIlluminata(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 14 = Illuminata (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 14; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 46` — SetSpeakerDoug(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 15 = Doug (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 15; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 47` — SetSpeakerDoug(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 15 = Doug (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 15; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 48` — SetSpeakerBlossom(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 16 = Blossom (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 16; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 49` — SetSpeakerBlossom(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 16 = Blossom (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 16; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 50` — SetSpeakerDolce(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 17 = Dolce (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 17; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 51` — SetSpeakerDolce(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 17 = Dolce (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 17; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 52` — SetSpeakerJones(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 18 = Jones (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 18; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 53` — SetSpeakerJones(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 18 = Jones (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 18; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 54` — SetSpeakerNancy(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 19 = Nancy (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 19; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 55` — SetSpeakerNancy(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 19 = Nancy (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 19; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 56` — SetSpeakerLeon(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 20 = Leon (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 20; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 57` — SetSpeakerLeon(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 20 = Leon (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 20; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 58` — SetSpeakerVentuswill(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 21 = Ventuswill (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 21; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 59` — SetSpeakerVentuswill(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 21 = Ventuswill (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 21; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 60` — SetSpeakerSon(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 22 = Son (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 22; the portrait/chime resolve slot 22/23 to REG_CHILD_ID; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 61` — SetSpeakerSon(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 22 = Son (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 22; the portrait/chime resolve slot 22/23 to REG_CHILD_ID; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 62` — SetSpeakerDaughter(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 23 = Daughter (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 23; the portrait/chime resolve slot 22/23 to REG_CHILD_ID; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 63` — SetSpeakerDaughter(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 23 = Daughter (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 23; the portrait/chime resolve slot 22/23 to REG_CHILD_ID; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 64` — SetSpeakerPico(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 24 = Pico (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 309 (slot remap); also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 65` — SetSpeakerPico(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 24 = Pico (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 309 (slot remap); also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 66` — SetSpeakerSoldier(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 25 = Soldier (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 149 (slot remap); also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 67` — SetSpeakerSoldier(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 25 = Soldier (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 149 (slot remap); also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 68` — SetSpeakerEthelberd(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 26 = Ethelberd (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 239 (slot remap); also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 69` — SetSpeakerEthelberd(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 26 = Ethelberd (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 239 (slot remap); also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 70` — SetSpeakerBarrett(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 27 = Barrett (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 24 (slot remap); also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 71` — SetSpeakerBarrett(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 27 = Barrett (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 24 (slot remap); also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 72` — SetSpeakerRaven(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 28 = Raven (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 25 (slot remap); also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 73` — SetSpeakerRaven(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 28 = Raven (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 25 (slot remap); also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 74` — SetSpeakerTraveler(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 29 = Traveler (slot = (op-16)>>1), left side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 29; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 75` — SetSpeakerTraveler(face, emote icon, emote icon or voice sfx id 2, emote icon or voice sfx id 3)
*handler:* `NpcBubble_DispatchAreaInfoLine`

Speaker cue for the following DIALOG line(s): speaker slot 29 = Traveler (slot = (op-16)>>1), right side (op & 1), shows that character's E-mote portrait and, when the slot differs from the latched host+108, loads the name plate = name-archive entry 29; also sets the text blip (Dialogue_PickChimeClassForSpeaker). Carries no text and persists until the next speaker op / EndDialogue. arg0 = expression: < 1000 = the character's face index (via g_npcBubble_emoteToStringIdTable), 1000..1927 = a raw expression entry (id-1000), 255 / 254 = the stock alternate expressions of the character's current outfit row (g_npcBubbleKindRows; NpcBubble_Show then uses entries 1192 / 1224). arg1..arg3 (argc clamped to 4) = triggers: >= 0x1F0 plays that voice/sfx via Sfx_PlayByIdWithNpcVariantRemap; otherwise an emote-icon id (186-192) queued on the portrait (the first two non-voice ids are kept; 0 = none).

Args:
  0. face (expression: <1000 face index, 1000-1927 raw entry, 255/254 stock alternates)
  1. emote icon (186-192) or voice sfx id (>=0x1F0)
  2. emote icon or voice sfx id 2
  3. emote icon or voice sfx id 3 (rare)

### `op 83` — ClosePortraits(which)
*handler:* `Script_VMOp_CloseBubblesWaitClosed`

Dismiss speaker PORTRAIT(s) and block until the dismissal animation is done. arg0: 0 = the side-0 portrait (host+88), 1 = the side-1 portrait (host+96), any other value = both. Each is sent DialogueBubble_TransitionState(p, 0) (slide off to x -64 or 464) and the slot pointer cleared; the op keeps returning busy while g_npcBubbleActiveByScreen / the portrait slot table still shows one active.

Args:
  0. which (0 = side-0 portrait, 1 = side-1 portrait, other = both)

### `op 92` — EndDialogue()
*handler:* `ScriptVMOp_DialogueTeardownBubblesAndCommit_NoArgs`

Close both speaker bubbles and commit the dialogue state -- the end of a spoken exchange. ALSO CLEARS THE SPEAKER (sceneCtx+108 = -1): the next DIALOG without a new SetSpeaker is narration again (plain box, no name/portrait). Returns to the scene controller when no other event is in flight. The #2 most-used action op (10,564 uses) -- every dialogue beat ends with one.

### `op 93` — SetDialogueBoxStyle(box style)
*handler:* `ScriptVMOp_SetDialogueSpeakerEmoteByArg`

Set the dialogue box style from an argument (the general form of ops 94-97, and the only way to get style 4). It sets the MESSAGE-BOX STYLE, not a face (verified 2026-09-25: Dialogue_SetSpeakerEmoteAndRetargetPortrait RF4S.exe+0x234E20 stores it at dialogue task +160; Dialogue_RetargetPortraitAndBubble +0x2380B0 then shows window art talk_win<n> (archive 15851+n) and tail talk_hige<n> (15846+n); Dialogue_SetTimingState +0x238350 adds the effect). 0 = normal box, 1 = shout (jagged box; everything shakes for 10 frames and the screen flashes), 2 = thought (cloud box with a bubble-trail tail; the box floats for ~1 s -- it does not delay the line), 3 = trembling (wavy box; a 10-frame sideways shake), 4 = tail only (no box). 5-7 would read unrelated textures. Lasts until changed or the dialogue box closes. The tail points at the side of the last speaker cue (an even SetSpeaker op = left, odd = right) and only shows while a portrait is up on that side for a named character: narration and SetSpeakerVoice name plates get no tail (DialogueBox_TickStateMachine +0x235BF0).

Args:
  0. box style (0 normal, 1 shout, 2 thought, 3 trembling, 4 tail only)
     - `0` = normal box
     - `1` = shout
     - `2` = thought
     - `3` = trembling
     - `4` = tail only

### `op 94` — SetBoxNormal()
*handler:* `ScriptVMOp_SetDialogueSpeakerEmoteFromOpcode`

Dialogue box style 0: the normal box. Ops 94-97 = styles 0-3, the style is the opcode (op - 94); op 93 takes it as an argument. It sets the MESSAGE-BOX STYLE, not a face (verified 2026-09-25: Dialogue_SetSpeakerEmoteAndRetargetPortrait RF4S.exe+0x234E20 stores it at dialogue task +160; Dialogue_RetargetPortraitAndBubble +0x2380B0 then shows window art talk_win<n> (archive 15851+n) and tail talk_hige<n> (15846+n); Dialogue_SetTimingState +0x238350 adds the effect). 0 = normal box, 1 = shout (jagged box; everything shakes for 10 frames and the screen flashes), 2 = thought (cloud box with a bubble-trail tail; the box floats for ~1 s -- it does not delay the line), 3 = trembling (wavy box; a 10-frame sideways shake), 4 = tail only (no box). 5-7 would read unrelated textures. Lasts until changed or the dialogue box closes. The tail points at the side of the last speaker cue (an even SetSpeaker op = left, odd = right) and only shows while a portrait is up on that side for a named character: narration and SetSpeakerVoice name plates get no tail (DialogueBox_TickStateMachine +0x235BF0).

### `op 95` — SetBoxShout()
*handler:* `ScriptVMOp_SetDialogueSpeakerEmoteFromOpcode`

Dialogue box style 1: shout -- a jagged box that shakes, with a screen flash. Ops 94-97 = styles 0-3 (op - 94); op 93 takes the style as an argument. It sets the MESSAGE-BOX STYLE, not a face (verified 2026-09-25: Dialogue_SetSpeakerEmoteAndRetargetPortrait RF4S.exe+0x234E20 stores it at dialogue task +160; Dialogue_RetargetPortraitAndBubble +0x2380B0 then shows window art talk_win<n> (archive 15851+n) and tail talk_hige<n> (15846+n); Dialogue_SetTimingState +0x238350 adds the effect). 0 = normal box, 1 = shout (jagged box; everything shakes for 10 frames and the screen flashes), 2 = thought (cloud box with a bubble-trail tail; the box floats for ~1 s -- it does not delay the line), 3 = trembling (wavy box; a 10-frame sideways shake), 4 = tail only (no box). 5-7 would read unrelated textures. Lasts until changed or the dialogue box closes. The tail points at the side of the last speaker cue (an even SetSpeaker op = left, odd = right) and only shows while a portrait is up on that side for a named character: narration and SetSpeakerVoice name plates get no tail (DialogueBox_TickStateMachine +0x235BF0).

### `op 96` — SetBoxThought()
*handler:* `ScriptVMOp_SetDialogueSpeakerEmoteFromOpcode`

Dialogue box style 2: thought -- a cloud box with a bubble-trail tail pointing at the speaker; the box floats for about a second. Ops 94-97 = styles 0-3 (op - 94); op 93 takes the style as an argument. It sets the MESSAGE-BOX STYLE, not a face (verified 2026-09-25: Dialogue_SetSpeakerEmoteAndRetargetPortrait RF4S.exe+0x234E20 stores it at dialogue task +160; Dialogue_RetargetPortraitAndBubble +0x2380B0 then shows window art talk_win<n> (archive 15851+n) and tail talk_hige<n> (15846+n); Dialogue_SetTimingState +0x238350 adds the effect). 0 = normal box, 1 = shout (jagged box; everything shakes for 10 frames and the screen flashes), 2 = thought (cloud box with a bubble-trail tail; the box floats for ~1 s -- it does not delay the line), 3 = trembling (wavy box; a 10-frame sideways shake), 4 = tail only (no box). 5-7 would read unrelated textures. Lasts until changed or the dialogue box closes. The tail points at the side of the last speaker cue (an even SetSpeaker op = left, odd = right) and only shows while a portrait is up on that side for a named character: narration and SetSpeakerVoice name plates get no tail (DialogueBox_TickStateMachine +0x235BF0).

### `op 97` — SetBoxTrembling()
*handler:* `ScriptVMOp_SetDialogueSpeakerEmoteFromOpcode`

Dialogue box style 3: trembling -- a wavy box that shakes sideways. Ops 94-97 = styles 0-3 (op - 94); op 93 takes the style as an argument. It sets the MESSAGE-BOX STYLE, not a face (verified 2026-09-25: Dialogue_SetSpeakerEmoteAndRetargetPortrait RF4S.exe+0x234E20 stores it at dialogue task +160; Dialogue_RetargetPortraitAndBubble +0x2380B0 then shows window art talk_win<n> (archive 15851+n) and tail talk_hige<n> (15846+n); Dialogue_SetTimingState +0x238350 adds the effect). 0 = normal box, 1 = shout (jagged box; everything shakes for 10 frames and the screen flashes), 2 = thought (cloud box with a bubble-trail tail; the box floats for ~1 s -- it does not delay the line), 3 = trembling (wavy box; a 10-frame sideways shake), 4 = tail only (no box). 5-7 would read unrelated textures. Lasts until changed or the dialogue box closes. The tail points at the side of the last speaker cue (an even SetSpeaker op = left, odd = right) and only shows while a portrait is up on that side for a named character: narration and SetSpeakerVoice name plates get no tail (DialogueBox_TickStateMachine +0x235BF0).

### `op 98` — ShakeDialogueBox(frames)
*handler:* `Script_VMOp_SetDialogueField161`

Shake the message box for N frames: writes the dialogue task's shake counter (+161, u8). DialogueBox_TickStateMachine offsets the box, name and text by the byte_7FF753E5E1D0 dx/dy pattern while the counter is non-zero and decrements it each frame (horizontal only while box style 3 is active). This is the same counter the shout/trembling styles arm with 10. The argument is truncated to a byte; any box-style op resets it to 0.

Args:
  0. frames (u8; value & 0xFF)

### `op 149` — PlayerScriptedTalkAnim(anim id, loop)
*handler:* `ScriptVM_Op_BeginPlayerScriptedTalkWithAnim`

Put the player into scripted-talk mode (if not already) and play an anim on the player. arg0 = anim id (-1 -> 187; 1 = return to default behaviour instead of a clip). arg1 != 0 sets the player's scene_node flag 0x4 = loop the clip; arg1 == 0 leaves the bit unchanged (it is never cleared here). Also clears scene ctx+116 bit 0x8000000, which re-arms the wait in op 152.

Args:
  0. anim id (-1 = 187, 1 = back to default)
  1. loop (non-zero sets the loop bit; 0 leaves it unchanged)

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

Set an NPC's facial-expression / emote byte (record +57), switching its portrait face (happy/sad/angry/etc) -- e.g. mid-dialogue. Ops 319 and 320 share this handler. NOT an emote icon over the actor (that is op 211/212 ShowActorEmote).

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

### `op 320` — SetEmote(npc id, emote id)
*handler:* `Script_VMOp_SetNpcEmoteByte`

Set an NPC's facial-expression / emote byte (record +57), switching its portrait face (happy/sad/angry/etc) -- e.g. mid-dialogue. Ops 319 and 320 share this handler. NOT an emote icon over the actor (that is op 211/212 ShowActorEmote).

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

### `op 323` — SetMood(npc id, mood id)
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

### `op 357` — SetVar7(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind7`

Write `value` into global script-variable bank 7 (52 u32 slots) at [index]; index > 51 is ignored and the value is clamped as UNSIGNED to 999,999,999 (negatives become 999999999). Shipped scripts use it to stage numbers (e.g. prices from GetPrinceOrderCost) for dialogue-text substitution; bank 7 is also the slot the choice-commit system writes. Read back with GetVar7.

Args:
  0. index (0-51)
  1. value (clamped to 999999999)

### `op 413` — SetDialogueBoxY(y position)
*handler:* `Script_VMOp_SetEntries8DwordFromArg`

Override the dialogue box's Y position: game-globals slot 8 = arg0; when non-zero DialogueBox_TickStateMachine uses it instead of the default 110 (0x6E) for the box layouts that take a fixed Y. Cleared by Dialogue_TickHudTeardown when the dialogue HUD closes.

Args:
  0. y position (0 = default 110)

### `op 415` — SetDialogueFlag4Bit2(cond)
*handler:* `Script_VMOp_SetEntries4Bit2ByZero`

Set or clear dialogue-box control bit 0x4 in the dialogue flags word: arg0 == 0 sets the bit, non-zero clears it. A low-level dialogue-box toggle.

Args:
  0. cond (0=set bit, else clear)

### `op 555` — SetNpcAttentionRadius(npc, radius)
*handler:* `Script_VMOp_SetNpcDialogueBubbleFlavorById`

Set the NPC's attention radius (record +26, stored as a byte zero-extended into the word) and run Npc_BroadcastBubbleProximityHandshake. For every villager with a non-zero +26, that routine flags each other villager on the same map with record +48 bit 0x20 when it is within +26 tile units (octagonal distance) and is not itself radiating, muted (+20 bit 0x40) or busy (+228 bit 0x1). 0 turns it off. It is a distance, not a bubble variant.

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
  1. radius (tile units, 0-255; 0 = off)

### `op 556` — SetNpcAttentionRadius(npc, radius)
*handler:* `Script_VMOp_SetNpcDialogueBubbleFlavorById`

Set the NPC's attention radius (record +26, stored as a byte zero-extended into the word) and run Npc_BroadcastBubbleProximityHandshake. For every villager with a non-zero +26, that routine flags each other villager on the same map with record +48 bit 0x20 when it is within +26 tile units (octagonal distance) and is not itself radiating, muted (+20 bit 0x40) or busy (+228 bit 0x1). 0 turns it off. It is a distance, not a bubble variant.

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
  1. radius (tile units, 0-255; 0 = off)

### `op 610` — SetChoiceVisibleMask(choice 0 visible, choice 1 visible, …)
*handler:* `Script_VMOp_SetSceneChoiceVisibleMaskFromArgs`

REBUILD the scene's choice-visibility mask from a list of booleans — zeroes mask dword 0 (choices 0..31; dwords 1-3 are untouched), then sets bit i when arg i is non-zero. Each bit gates whether option i appears in the next PROMPT_CHOICE, and the picked VISIBLE ROW maps back through the set bits to the option's ORIGINAL index in reg0 (that's what the SWITCH_EQ after a staged prompt dispatches on). Sets reg0 = 1 if any of the 128 mask bits is set, else 0. Only 32 args are meaningful: arg i >= 32 wraps onto bit i-32 (the shift is mod 32). IDA-verified 2026-08-17 / 2026-09-24 (Script_VMOp_SetSceneChoiceVisibleMaskFromArgs).

Args:
  0. choice 0 visible
  1. choice 1 visible
  2. …

### `op 611` — ClearChoiceVisibleRange(start index, count)
*handler:* `Script_VMOp_ClearSceneChoiceVisibleMaskRange`

Clear COUNT choice-visibility bits starting at START (hide those choices; dword 0 only, i.e. options 0..31). arg0 = start bit, arg1 = count — NOT a from/to pair (IDA-verified 2026-08-17: clears bits [start, start+count)). Sets reg0 = 1 if any bit anywhere is still set, else 0. CAUTION: a mask cleared to all-zero means 'no mask' -- the next prompt shows EVERY option (there is no way to hide all). Companion to SetChoiceVisibleMask (op 610).

Args:
  0. start index
  1. count

### `op 612` — SetChoiceVisibleBit(choice index, visible)
*handler:* `Script_VMOp_ToggleSceneChoiceVisibleBit`

Show or hide a SINGLE choice by index in the scene's choice-visibility mask. arg0 = choice index (0-127), arg1 = visible (1) / hidden (0). Sets reg0 = 1 if any choice is still visible, else 0 — scripts branch on 'is anything left to offer'. The next PROMPT_CHOICE presents only flagged options (jumping to target[visible row]) and puts the picked option's ORIGINAL index in reg0; the prompt then CLEARS the whole mask. The shipped idiom sets bit i for every option (1 or a flag expression), points all targets at one label and SWITCH_EQs on reg0. A mask with bits set only past the menu's last option opens an EMPTY menu that crashes on confirm. Bit 5 on a 4-option menu is harmless.

Args:
  0. choice index (0-127)
  1. visible (0/1)

### `op 613` — CalcChoicePrescroll(option index)
*handler:* `Script_VMOp_CalcChoiceDialogPrescrollFromVisibleMask`

Pick the row the NEXT choice menu opens on (the default highlight). arg0 = a row index, stored in the GLOBAL g_choiceDialogPrescrollCount (not a VM register); when the menu builds its rows it moves the cursor down that many times (wrapping past the last row) and then zeroes it. The handler means to subtract the HIDDEN options below arg0 (clear bits of mask dword 0), but it only counts the options the current prompt has already queued (scene +243), which is 0 whenever a script can run this op -- so in practice the value is arg0 unchanged, i.e. a VISIBLE-row index; subtract hidden options yourself. Shipped use (8x): the menu reopens on the option picked last time (arg = a register). Call right before PROMPT_CHOICE. IDA-verified 2026-09-24 (Script_VMOp_CalcChoiceDialogPrescrollFromVisibleMask, ChoiceDialog_TickStateMachine state 3).

Args:
  0. option index

### `op 614` — SetDialogueBoxMode(mode)
*handler:* `Script_VMOp_SetDialogueSpeakerSideByte`

Set the dialogue-box mode byte (byte 2 of g_gameGlobalsSlotTable.entries[9]). 2 = narration: no speaker-name label, no text blips; 0 = normal; 1 = the menu-style dialogue layout (every shipped use; FMenu_*, NpcBubble_SpawnPositionedDualScreen, Dialogue_SpawnHud and ChoiceDialog code pick different widget offsets when the byte is 1). (The existing description is right; only the name is misleading.)

Args:
  0. mode (0 = normal, 1 = menu-style dialogue layout, 2 = narration)

### `op 615` — ArmChoiceOption(value 1, value 2, value 3)
*handler:* `Script_VMOp_SetUpToThreeChoiceDialogValuesAndArm`

ARM the next DIALOG as a choice ROW DESCRIPTION: instead of displaying, that DIALOG's line is QUEUED (44-byte record in the global g_dialoguePendingLineQueue, 128 slots) with up to 3 values (args past 3 are ignored; 0 = not stored), gated on the row's visibility bit when a mask is set. Shape: [ArmChoiceOption(v..); DIALOG line] x N, in row order, any time before the menu (often a separate scene). While the menu is open, the line queued for the HIGHLIGHTED visible row is shown in the dialogue box (on open and on every cursor move), and its values are written to element 0 of var arrays kind 4 / 5 / 6 (arg1 / arg2 / arg3 -- the SetVar4/5/6 arrays that the ＠ text tokens read) -- so the description can show per-row numbers. The menu's own option text still comes from the PROMPT_CHOICE ids; the queue is emptied when the menu closes. 1,839 uses (1,834 followed by their DIALOG). IDA-verified 2026-09-24 (Script_VMOp_SetUpToThreeChoiceDialogValuesAndArm, deferred path of Dialogue_HandleScriptActionShowLine, ChoiceDialog_CommitSelectionAndDispatchActions).

Args:
  0. value 1 (-> SetVar4 slot 0)
  1. value 2 (-> SetVar5 slot 0)
  2. value 3 (-> SetVar6 slot 0)

### `op 623` — SetDialogueAutoAdvance(mode)
*handler:* `Script_VMOp_SetDialogueAutoAdvanceTimingMode`

Set how the current dialogue line auto-advances (the timing mode). 0 = no auto-advance (wait for the player to press confirm); 1 = auto-compute a reading timer from the text length (~7*(len/3)+30 frames); any other N = dismiss the line after exactly N frames. Lets a scripted line time out on its own.

Args:
  0. mode (0=off, 1=auto, N=frames)

### `op 624` — SetDialogueHoldFrames(frames)
*handler:* `Script_VMOp_SetDialogueHoldFrameCounter`

Lock out the player's advance input for N dialogue-box frames: sets a byte countdown that DialogueBox_TickStateMachine decrements every tick; while it is nonzero, DialogueBox_TickState5 ignores the confirm/skip buttons. Stops a line from being skipped too fast.

Args:
  0. frames (0-255)

### `op 698` — SetShopkeeperMessage(shopkeeper message index)
*handler:* `Script_VMOp_WriteJustmMessageRegAndCallback`

Set the active shop's shopkeeper message/greeting line to `arg`. Writes arg (a message index) into the 10-bit packed GameFlag field 3006 = REG_JUSTM_MESSAGE (so the chosen greeting persists), then FMenu_SetShopMessageTextFromArchive(arg): loads locale text archive 15206 (0x3B66), copies entry[arg] (clamped to <360) into the shop's dialogue-text sprite and reveals it with the typewriter effect. CORRECTION: this is NOT an achievement. The raw handler id 39870 decodes (via GameFlags_WriteField) to packed-flag id 3006, width 10 -- and 3006 is not among the ~30 named-achievement switch cases, so it falls through to a plain packed-flag write. The IDA name `WriteJustmMessageRegAndCallback` is accurate (Justm = the shopkeeper message register). Corpus: bank 292 @0x0e7e sets arg=244.

Args:
  0. shopkeeper message index (0-359, indexes locale text archive 15206)

### `op 699` — SetNarrationModeIf(enable)
*handler:* `Script_VMOp_SetDialogueSecondarySpeakerIfNonzero`

If arg0 != 0, set the dialogue-box mode byte (the byte op 614 writes) to 2 = narration (no speaker-name label, muted text blips); if arg0 == 0, leave it unchanged. (The existing description is right; only the name is misleading.)

Args:
  0. enable (nonzero = narration mode)

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

### `op 188` — HoldCameraInPlace(exact)
*handler:* `Script_VMOp_SnapCameraToPlayer`

Detach the camera from following (player camera flag 4) and make its current position its target, so it stops where it is. arg != 0: target = current camera position exactly (plus map scroll origin). arg == 0: commit the current position through Camera_CommitTargetAndClampToBounds (clamped into the map's camera bounds). Nothing here reads the player's position.

Args:
  0. exact (1 = hold exactly, 0 = clamp into bounds)

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

### `op 191` — ResetCameraToActor(actor, speed)
*handler:* `Script_VMOp_ResetCameraToActor`

Re-attach the camera and center it on an actor (0 = player, 1..47 NPC). arg1 = 0 -> hard-snap target+position to the actor; -1 -> attach only; any other value is the ease SPEED (x40.96, same /100-tiles-per-frame channel as op 190). Blocks ~4 frames (ctx+26 counter) before continuing.

Args:
  0. actor (0=player, 1-47 NPC)
  1. speed (/100 tiles per frame; 0 = snap, -1 = attach only)

### `op 192` — ResetCameraToActor(actor, speed)
*handler:* `Script_VMOp_ResetCameraToActor`

Re-attach the camera and center it on an actor (0 = player, 1..47 NPC). arg1 = 0 -> hard-snap target+position to the actor; -1 -> attach only; any other value is the ease SPEED (x40.96, same /100-tiles-per-frame channel as op 190). Blocks ~4 frames (ctx+26 counter) before continuing.

Args:
  0. actor (0=player, 1-47 NPC)
  1. speed (/100 tiles per frame; 0 = snap, -1 = attach only)

### `op 193` — SetCameraTargetToCurrentPosition(speed)
*handler:* `Script_VMOp_SetCameraAnchorToPlayerOrTarget`

Make the camera's current position its target (no player involved). arg = 0: target = position exactly (and map scroll origin), then recompute the pan vector. arg != 0: commit the position through the bounds clamp, then (unless arg == -1) recompute the pan vector with speed arg (x40.96, /100 tiles per frame) - i.e. ease back inside the map bounds.

Args:
  0. speed (0 = hold exactly, -1 = clamp only, else /100 tiles per frame)

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

Pan the camera to an actor chosen by scene-slot (same 0..0x2F slot space as dialogue speakers; slot 0 / empty slot falls back to the player). Anchors on the actor's world position and recomputes the follow vector; locks player movement. arg1 = the same PAN-SPEED channel as SetCameraTarget (op 190): arg1/100 tiles per frame, cap 15 (shipped scenes use ~100-400).

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

Set the camera zoom / pull-back distance: the engine stores (arg0 - 1500) in the player camera struct (+68 target). arg1 != 0 SNAPS (writes current +64 AND target +68); arg1 == 0 eases (target only, view drifts to the new framing). Both paths apply the zoom - the old 'arg1 = reset to default rig' reading was wrong (IDB-corrected 2026-08-25; re-confirmed 2026-09-01). Magnification = 1 + arg0/1800.

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

Play full-motion video [arg0] (Cutscene_PlayVideoById). If a dialogue box is still open (or a scripted event / dialogue-slot mismatch blocks it), the op instead nudges the dialogue to close (state 6 -> 7), tears down the two bubble slots, and returns 1 so the VM retries the op next step. The video therefore starts only once no dialogue is up; the dialogue is never 'advanced' as an alternative outcome.

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

### `op 77` — SlidePortraitToX(portrait character id, target screen x, slide speed)
*handler:* `Script_VMOp_SetActorFacingAngle`

Slide a speaker PORTRAIT horizontally to an absolute screen x. arg0 = character id of the portrait (must be one of the two on-screen portraits, else no-op), arg1 = target screen x (pixels; written to portrait +94, start = current x; bit 15 of the value clears the direction byte +99), arg2 = slide speed (same Q12 conversion as the move ops, x25). Does not wait; pair with op 81.

Args:
  0. portrait character id
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
  1. target screen x (pixels)
  2. slide speed

### `op 78` — SlidePortraitToX(portrait character id, target screen x, slide speed)
*handler:* `Script_VMOp_SetActorFacingAngle`

Slide a speaker PORTRAIT horizontally to an absolute screen x. arg0 = character id of the portrait (must be one of the two on-screen portraits, else no-op), arg1 = target screen x (pixels; written to portrait +94, start = current x; bit 15 of the value clears the direction byte +99), arg2 = slide speed (same Q12 conversion as the move ops, x25). Does not wait; pair with op 81.

Args:
  0. portrait character id
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
  1. target screen x (pixels)
  2. slide speed

### `op 79` — SlidePortraitBy(portrait character id, x delta, slide speed)
*handler:* `Script_VMOp_SetActorTurnAngle`

Slide a speaker PORTRAIT horizontally by a relative amount. arg0 = character id of an on-screen portrait (else no-op), arg1 = signed x delta in pixels added to the portrait's target x (+94; sign sets the direction byte +99), arg2 = slide speed (Q12 conversion x25 -> +88). Starts the slide (state 0xC) and returns immediately; op 81 waits for it.

Args:
  0. portrait character id
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
  1. x delta (pixels, signed)
  2. slide speed

### `op 80` — SlidePortraitBy(portrait character id, x delta, slide speed)
*handler:* `Script_VMOp_SetActorTurnAngle`

Slide a speaker PORTRAIT horizontally by a relative amount. arg0 = character id of an on-screen portrait (else no-op), arg1 = signed x delta in pixels added to the portrait's target x (+94; sign sets the direction byte +99), arg2 = slide speed (Q12 conversion x25 -> +88). Starts the slide (state 0xC) and returns immediately; op 81 waits for it.

Args:
  0. portrait character id
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
  1. x delta (pixels, signed)
  2. slide speed

### `op 84` — SetPortraitField62(portrait character id, value, apply)
*handler:* `Script_VMOp_SetActorMotionField62`

Portrait tweak: if arg2 != 0 and a portrait with char id arg0 is on screen, write arg1 to field +62 of the SIDE-0 portrait (host+88) - note it always writes the host+88 portrait, not the matched one. +62 is initialised to 100 by NpcBubble_Init; no reader was found. With arg2 = 0 (every shipped use) the op does nothing.

Args:
  0. portrait character id
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
  1. value (u16; default 100)
  2. apply (0 = do nothing)

### `op 85` — SetPortraitTargetY(portrait character id, target screen y)
*handler:* `Script_VMOp_SetActorMotionField56`

Move a speaker PORTRAIT vertically: sets its target screen y (+56); each frame its y eases 1/4 of the remaining distance toward it. 0 disables the easing (y stays where it is). arg0 = portrait character id (else no-op), arg1 = target y (pixels, signed).

Args:
  0. portrait character id
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
  1. target screen y (pixels; 0 = hold)

### `op 86` — SetPortraitTargetY(portrait character id, target screen y)
*handler:* `Script_VMOp_SetActorMotionField56`

Move a speaker PORTRAIT vertically: sets its target screen y (+56); each frame its y eases 1/4 of the remaining distance toward it. 0 disables the easing (y stays where it is). arg0 = portrait character id (else no-op), arg1 = target y (pixels, signed).

Args:
  0. portrait character id
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
  1. target screen y (pixels; 0 = hold)

### `op 87` — JoltPortraitY(portrait character id, y jolt)
*handler:* `Script_VMOp_SetActorMotionField60`

Give a speaker PORTRAIT a vertical jolt: sets its extra y offset (+60), which NpcBubble_SetPosition adds to the drawn y and NpcBubble_TickTask halves toward 0 every frame (a hop / drop that springs back). arg0 = portrait character id (else no-op), arg1 = offset in pixels (signed).

Args:
  0. portrait character id
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
  1. y jolt (pixels, signed; decays by half per frame)

### `op 88` — JoltPortraitY(portrait character id, y jolt)
*handler:* `Script_VMOp_SetActorMotionField60`

Give a speaker PORTRAIT a vertical jolt: sets its extra y offset (+60), which NpcBubble_SetPosition adds to the drawn y and NpcBubble_TickTask halves toward 0 every frame (a hop / drop that springs back). arg0 = portrait character id (else no-op), arg1 = offset in pixels (signed).

Args:
  0. portrait character id
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
  1. y jolt (pixels, signed; decays by half per frame)

### `op 89` — SetPortraitTremble(portrait character id, tremble level n)
*handler:* `Script_VMOp_SetActorMotionMask`

Make a speaker PORTRAIT tremble: writes the tremble mask +66 = 127 >> n for n in 1..254 (the portrait's y flips by the +58 amplitude, 1 px by default, whenever (phase & mask) == 0, so n = 6 flips every 2 frames, n = 3 every 16); n = 0 (or 255) writes 0xFF = tremble off. arg0 = portrait character id (else no-op).

Args:
  0. portrait character id
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
  1. tremble level n (0 = off; larger = faster, 6 = every other frame)

### `op 90` — SetPortraitTremble(portrait character id, tremble level n)
*handler:* `Script_VMOp_SetActorMotionMask`

Make a speaker PORTRAIT tremble: writes the tremble mask +66 = 127 >> n for n in 1..254 (the portrait's y flips by the +58 amplitude, 1 px by default, whenever (phase & mask) == 0, so n = 6 flips every 2 frames, n = 3 every 16); n = 0 (or 255) writes 0xFF = tremble off. arg0 = portrait character id (else no-op).

Args:
  0. portrait character id
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
  1. tremble level n (0 = off; larger = faster, 6 = every other frame)

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

### `op 101` — PlaceActorAndFace(actor, x, y, facing)
*handler:* `ScriptAction_PlaceActorOrSetFacing`

Teleport an actor to a tile AND set its facing. arg0 = actor (0 = player, 1..47 NPC; >= 48 = no-op), arg1/arg2 = x/y tiles (as op 99: marks host+352, streams the NPC in, snaps the player to the ground), arg3 = facing in degrees (x181; player: facing_b + g_playerFacingDirty; NPC: target yaw +158 with ease shift +160 = 0, i.e. instant). There is no face-only mode: with fewer than 3 args the handler returns busy and the statement blocks forever; with exactly 3 the facing is taken from an uninitialised local.

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

### `op 102` — PlaceActorAndFace(actor, x, y, facing)
*handler:* `ScriptAction_PlaceActorOrSetFacing`

Teleport an actor to a tile AND set its facing. arg0 = actor (0 = player, 1..47 NPC; >= 48 = no-op), arg1/arg2 = x/y tiles (as op 99: marks host+352, streams the NPC in, snaps the player to the ground), arg3 = facing in degrees (x181; player: facing_b + g_playerFacingDirty; NPC: target yaw +158 with ease shift +160 = 0, i.e. instant). There is no face-only mode: with fewer than 3 args the handler returns busy and the statement blocks forever; with exactly 3 the facing is taken from an uninitialised local.

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

### `op 103` — TurnActorToAngle(actor, facing, ease shift)
*handler:* `ScriptVM_Op_SetEntityFacingAngleByteScaled`

Turn an actor toward a compass facing. arg0 = actor (0 = player, 1..47 NPC; >= 48 or argc < 3 = no-op), arg1 = facing in degrees (x181 -> u16), arg2 = turn ease shift: each frame the facing moves (remaining >> shift) toward the target, so 0 = instant snap, 2 = a quarter per frame (NPC: actor+158 target / +160 shift, npc+20 |= 0x800 when shift != 0; player: facing_b + field_A0 = shift, g_playerFacingDirty).

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
  2. ease shift (0 = snap; 2 = 1/4 per frame)

### `op 104` — TurnActorToAngle(actor, facing, ease shift)
*handler:* `ScriptVM_Op_SetEntityFacingAngleByteScaled`

Turn an actor toward a compass facing. arg0 = actor (0 = player, 1..47 NPC; >= 48 or argc < 3 = no-op), arg1 = facing in degrees (x181 -> u16), arg2 = turn ease shift: each frame the facing moves (remaining >> shift) toward the target, so 0 = instant snap, 2 = a quarter per frame (NPC: actor+158 target / +160 shift, npc+20 |= 0x800 when shift != 0; player: facing_b + field_A0 = shift, g_playerFacingDirty).

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
  2. ease shift (0 = snap; 2 = 1/4 per frame)

### `op 106` — RotateActorInPlace(npc, degrees per frame, frame count)
*handler:* `ScriptVM_Op_RotateEntityFacingByStepsWithCounter`

Spin an NPC in place: every frame adds arg1 degrees (x181) to its current and target facing (and to its held entity's facing at actor+240 -> +186), blocking until this has run arg2 times (a single global step counter, reset to 0 on completion). arg0 must be an NPC id 1..47: id 0 dereferences a null actor (crash), >= 48 is a no-op; with fewer than 3 args the op blocks forever.

Args:
  0. npc (char id 1-47; not the player)
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
  1. degrees per frame (signed)
  2. frame count

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

### `op 109` — TurnActorToFaceTarget(turner, look-at target, mode)
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

### `op 110` — FaceEventActor(actor, event-actor id, ease shift)
*handler:* `ScriptVMOp_MakeActorFaceCalendarEventActorAndSetAnim`

Turn an actor (0 = player, 1..47 NPC; >= 48 = no-op) to face an EVENT ACTOR looked up by id in g_calendarEventMng (the monster / event-bound actor ids such as 100, 200, 300). arg2 is the same turn ease shift as op 107 (0 = snap, 2 = quarter per frame), not an animation.

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
  1. event-actor id (g_calendarEventMng record id)
  2. ease shift (0 = snap)

### `op 111` — SetActorAuxYaw(actor, secondary yaw target)
*handler:* `Script_VMOp_SetActorRotationRaw`

Set the TARGET of an actor's secondary yaw pair (actor+0xD8; current value at +0xD6), not its body facing: arg1 degrees x181. Actor_IntegrateMotionAndFacing eases +0xD6 toward it with the actor's ease shift (+160), so it is not an instant snap. arg0 = actor (0 = player, 1..47 NPC; >= 48 = no-op); needs 2 args.

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
  1. secondary yaw target (degrees)

### `op 112` — SetActorAuxYaw(actor, secondary yaw target)
*handler:* `Script_VMOp_SetActorRotationRaw`

Set the TARGET of an actor's secondary yaw pair (actor+0xD8; current value at +0xD6), not its body facing: arg1 degrees x181. Actor_IntegrateMotionAndFacing eases +0xD6 toward it with the actor's ease shift (+160), so it is not an instant snap. arg0 = actor (0 = player, 1..47 NPC; >= 48 = no-op); needs 2 args.

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
  1. secondary yaw target (degrees)

### `op 115` — MoveActorToTile_LockAI(actor, x, y, facing, speed, jump)
*handler:* `ScriptAction_MoveActorToAbsoluteTile_LockAiAndFace`

Walk an actor to an ABSOLUTE tile position, then LOCK its AI (npc+568 |= 0x10) so nothing interrupts the staged pose — used when actors slide into cutscene positions and must hold. Args 1/2 are absolute tiles, not offsets: the move command stores x<<12 / y<<12 RAW with no world-position anchor added, on both the NPC and player/scene paths (ops 115-118 are the absolute family; 123-128 are the relative one). args: actor (0 = player), x, y (tiles), facing degrees (x181 -> u16 rotation), speed, jump flag (non-zero = jump/run, 1.2x speed multiplier).

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

Walk an actor to an ABSOLUTE tile position, then LOCK its AI (npc+568 |= 0x10) so nothing interrupts the staged pose — used when actors slide into cutscene positions and must hold. Args 1/2 are absolute tiles, not offsets: the move command stores x<<12 / y<<12 RAW with no world-position anchor added, on both the NPC and player/scene paths (ops 115-118 are the absolute family; 123-128 are the relative one). args: actor (0 = player), x, y (tiles), facing degrees (x181 -> u16 rotation), speed, jump flag (non-zero = jump/run, 1.2x speed multiplier).

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

### `op 117` — MoveActorToTileFaceTravel(actor, x, y, speed, jump)
*handler:* `ScriptAction_MoveActorToAbsoluteTile_LockAiNoFace`

Move an actor to an ABSOLUTE tile (x,y). Move-command mode byte = 0, so the actor turns to face its direction of travel (there is simply no final-facing argument); afterwards sets actor.control_flags(+0x238) bit 0x10, the same 'scene-controlled' bit the dispatcher sets on every NPC when a cutscene starts. Speed = (arg*167773>>12) x 1.2 when jump != 0.

Args:
  0. actor (char id <48)
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

### `op 118` — MoveActorToTileFaceTravel(actor, x, y, speed, jump)
*handler:* `ScriptAction_MoveActorToAbsoluteTile_LockAiNoFace`

Move an actor to an ABSOLUTE tile (x,y). Move-command mode byte = 0, so the actor turns to face its direction of travel (there is simply no final-facing argument); afterwards sets actor.control_flags(+0x238) bit 0x10, the same 'scene-controlled' bit the dispatcher sets on every NPC when a cutscene starts. Speed = (arg*167773>>12) x 1.2 when jump != 0.

Args:
  0. actor (char id <48)
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

### `op 119` — MoveActorToTileKeepFacing(npc, x, y, speed, jump)
*handler:* `ScriptVMOp_NpcStartMoveWithSpeedAndMode`

Move an NPC to an ABSOLUTE tile while KEEPING its current facing (side-step / back-pedal): move-command mode byte = 2, which Npc_StartMoveTowards turns into control_flags 0x20000 (no auto-face). Afterwards sets control_flags bit 0x10 (scene-controlled), exactly like op 117. jump/run flag != 0 multiplies speed by 1.2 and sets the jump bit 0x800000.

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
  1. x (tiles, absolute)
  2. y (tiles, absolute)
  3. speed
  4. jump (0/1)

### `op 120` — MoveActorToTileKeepFacing(npc, x, y, speed, jump)
*handler:* `ScriptVMOp_NpcStartMoveWithSpeedAndMode`

Move an NPC to an ABSOLUTE tile while KEEPING its current facing (side-step / back-pedal): move-command mode byte = 2, which Npc_StartMoveTowards turns into control_flags 0x20000 (no auto-face). Afterwards sets control_flags bit 0x10 (scene-controlled), exactly like op 117. jump/run flag != 0 multiplies speed by 1.2 and sets the jump bit 0x800000.

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
  1. x (tiles, absolute)
  2. y (tiles, absolute)
  3. speed
  4. jump (0/1)

### `op 121` — MoveNpcToTileKeepAnim(npc, x, y, speed)
*handler:* `ScriptVMOp_NpcStartMoveAlternateKind2048`

Move an NPC to an ABSOLUTE tile WITHOUT resetting its animation: cmd mode byte = 8, which makes Npc_StartMoveTowards skip Npc_FinalizeTeleportAndNotify (the reset-to-idle/walk-anim routine), so whatever clip PlayActorAnim started keeps playing while the actor glides. No jump flag (byte0 = 0); speed = arg*167773>>12 (same scale as a non-jump walk). Sets control_flags 0x10 afterwards.

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
  1. x (tiles, absolute)
  2. y (tiles, absolute)
  3. speed

### `op 122` — MoveNpcToTileKeepAnim(npc, x, y, speed)
*handler:* `ScriptVMOp_NpcStartMoveAlternateKind2048`

Move an NPC to an ABSOLUTE tile WITHOUT resetting its animation: cmd mode byte = 8, which makes Npc_StartMoveTowards skip Npc_FinalizeTeleportAndNotify (the reset-to-idle/walk-anim routine), so whatever clip PlayActorAnim started keeps playing while the actor glides. No jump flag (byte0 = 0); speed = arg*167773>>12 (same scale as a non-jump walk). Sets control_flags 0x10 afterwards.

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
  1. x (tiles, absolute)
  2. y (tiles, absolute)
  3. speed

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

### `op 125` — MoveActorByOffsetFaceTravel(actor, dx, dy, speed, jump)
*handler:* `ScriptAction_MoveActorToRelativeOffset_InterruptAi`

Move an actor by a RELATIVE tile offset, turning to face the direction of travel (mode 0, no end-facing arg). NPC path first clears control_flags bit 0x4 (the 'hidden' bit op 141 sets) and actor+0xB4 bits 0x10C, then Npc_StartMoveTowards; actor 0 = player via the scene mover (mode 0, or 8 when ctx+72 bit 0 is set). 5 args, no facing.

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

### `op 126` — MoveActorByOffsetFaceTravel(actor, dx, dy, speed, jump)
*handler:* `ScriptAction_MoveActorToRelativeOffset_InterruptAi`

Move an actor by a RELATIVE tile offset, turning to face the direction of travel (mode 0, no end-facing arg). NPC path first clears control_flags bit 0x4 (the 'hidden' bit op 141 sets) and actor+0xB4 bits 0x10C, then Npc_StartMoveTowards; actor 0 = player via the scene mover (mode 0, or 8 when ctx+72 bit 0 is set). 5 args, no facing.

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

### `op 127` — MoveActorByOffsetKeepFacing(actor, dx, dy, speed, jump)
*handler:* `ScriptAction_MoveActorToRelativeOffset_NoFaceUpdate`

Move an actor by a RELATIVE tile offset while KEEPING its current facing (side-step / back-pedal). NPC path mode 2 (-> control_flags 0x20000); player path via the scene mover with mode 4 (-> player control_flags 0x20000) or 12. 5 args, no facing; jump flag x1.2 speed.

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

### `op 128` — MoveActorByOffsetKeepFacing(actor, dx, dy, speed, jump)
*handler:* `ScriptAction_MoveActorToRelativeOffset_NoFaceUpdate`

Move an actor by a RELATIVE tile offset while KEEPING its current facing (side-step / back-pedal). NPC path mode 2 (-> control_flags 0x20000); player path via the scene mover with mode 4 (-> player control_flags 0x20000) or 12. 5 args, no facing; jump flag x1.2 speed.

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

### `op 133` — PlayActorAnim(actor, anim id, loop)
*handler:* `Script_VMOp_PlayActorActionAnim`

Play an animation on an actor. arg1 = anim id; id 1 is special: instead of a clip it calls the actor's own behaviour callback (actor+0x48), i.e. hands the actor back to its default idle/AI (for the player it may begin a scripted talk interaction). arg2 != 0 sets scene_node flag 0x4 = LOOP the clip (the engine sets the same bit on idle anims); 0 clears it for NPCs (plays once, op 137 can wait for its end); on the player path 0 leaves the bit unchanged (the player branch only ever sets it). Player: begins a scripted-talk interaction first if not already in one.

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
  1. anim id (1 = resume default behaviour)
  2. loop (0/1; 0 clears the bit for NPCs only)

### `op 134` — PlayActorAnim(actor, anim id, loop)
*handler:* `Script_VMOp_PlayActorActionAnim`

Play an animation on an actor. arg1 = anim id; id 1 is special: instead of a clip it calls the actor's own behaviour callback (actor+0x48), i.e. hands the actor back to its default idle/AI (for the player it may begin a scripted talk interaction). arg2 != 0 sets scene_node flag 0x4 = LOOP the clip (the engine sets the same bit on idle anims); 0 clears it for NPCs (plays once, op 137 can wait for its end); on the player path 0 leaves the bit unchanged (the player branch only ever sets it). Player: begins a scripted-talk interaction first if not already in one.

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
  1. anim id (1 = resume default behaviour)
  2. loop (0/1; 0 clears the bit for NPCs only)

### `op 141` — SetActorOpacity(actor, opacity percent)
*handler:* `ScriptVMOp_SetActorInvulnerability`

Show/hide an actor. arg1 == 0 sets control_flags(+0x238) bit 0x4 (hidden); arg1 != 0 clears that bit and sets the model opacity to arg1 percent (SceneNode_SetAlpha(node, arg1*0.01)).

Args:
  0. actor (char id <48, 0=player)
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
  1. opacity percent (0 = hide)

### `op 142` — MoveSceneActorToTile(x, y, facing, speed, run)
*handler:* `Script_VMOp_MoveActorToCoords`

Move the scene-controlled actor (the player) to an ABSOLUTE tile, with facing. arg0/arg1 = X/Y tiles, arg2 = facing degrees, arg3 = speed, arg4 = run flag (0 = walk, non-zero = run). No char-id arg — always the scene's own actor.

Args:
  0. x (tiles)
  1. y (tiles)
  2. facing (degrees)
  3. speed
  4. run (0/1)

### `op 143` — MoveSceneActorToTileFaceTravel(x, y, speed, run)
*handler:* `ScriptVM_Op_QueueMoveCommandToCoords`

Move the scene-controlled actor (the player) to an ABSOLUTE tile, facing the direction of travel (mode 0, no end-facing, no keep-facing). arg2 = speed (x40.96, x1.2 when running), arg3 = run flag.

Args:
  0. x (tiles)
  1. y (tiles)
  2. speed
  3. run (0/1)

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

Scripted equip: if the player's current held/equip slot passes Inventory_CanStackOrMerge, writes item (id & 0x7FF | 0x800) into the player's equip slot record (actor_inner+0x2A0+984 -> +72), calls Player_OnEquipChanged, then Player_BeginScriptedTalkAndIdle(1).

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
     - *(enum: 392 values — use the in-editor picker or the id database)*
  1. event key (scene-local handle)
  2. x (tiles)
  3. y (tiles)
  4. facing (degrees)

### `op 154` — EventSpawnNpcVariant(char id, event key, x, y, facing, variant index)
*handler:* `ScriptVMOp_CalendarEvent_AddNpcWithVariantIndex`

Spawn an event/cutscene NPC that carries a pose/scene VARIANT index — always claims a NEW registry slot (unlike op 153 which updates in place). arg0 = char id (which character/model; ids 254-266 are filtered = no-op), arg1 = event key (the scene-local handle later ops address), arg2/arg3 = X/Y tiles, arg4 = facing degrees (x181 -> u16), arg5 = variant index (stored as index-1 in the entry's high dword; 0 -> 0). Entry WORD5 is hardwired to 0 by the engine — there is NO reserved 7th argument. Use for staged NPCs with an alternate pose/outfit variant.

Args:
  0. char id (model)
     - *(enum: 392 values — use the in-editor picker or the id database)*
  1. event key (scene-local handle)
  2. x (tiles)
  3. y (tiles)
  4. facing (degrees)
  5. variant index

### `op 155` — EventSpawnNpcEx(char id, event key, x, y, facing, flag, scalar %)
*handler:* `ScriptVMOp_CalendarEvent_AddNpcWithFollowSpeedAndFlag`

Always appends a new event-actor record like op 154 (char arg0, key arg1, x, y, facing deg). Record WORD5 = 0x8000 | (arg5 & 1) << 14 - only bit 0 of arg5 matters and bit 15 is always set; record +16 = float(arg6) * 0.01. What reads WORD5 bits 14/15 and the +16 float was not traced, so 'follow speed' is unconfirmed.

Args:
  0. char id (model)
     - *(enum: 392 values — use the in-editor picker or the id database)*
  1. event key
  2. x (tiles)
  3. y (tiles)
  4. facing (degrees)
  5. flag (bit 0 only)
  6. scalar % (stored x0.01)

### `op 156` — UnregisterEventActor(char id, event key)
*handler:* `ScriptVMOp_KillCalendarEventByCharAndEventKey`

Remove a spawned event actor from the calendar-event registry, matching on BOTH char id and event key; frees its slot on the next sweep. arg0 = char id, arg1 = event key. Registry-level cleanup — no death animation and no dismiss reset (contrast KillEventActor op 180 / DismissEventActor op 181). Use when a scene ends.

Args:
  0. char id
     - *(enum: 392 values — use the in-editor picker or the id database)*
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

### `op 161` — EventNpcWalkToTileKeepFacing(event key, x, y, speed, run)
*handler:* `ScriptVMOp_CalendarEvent_BeginScriptedNpcMovementAndSetCtrlFlag20000`

Same as op 160 (walk/run an event actor to an absolute tile) but first sets the actor's control_flags bit 0x20000, which suppresses auto-facing toward the movement direction - the actor side-steps / back-pedals keeping its current facing.

Args:
  0. event key
  1. x (tiles)
  2. y (tiles)
  3. speed
  4. run (0/1)

### `op 162` — SetEventActorFacing(event key, facing, turn ease)
*handler:* `ScriptVMOp_SetMonsterFacingDegrees`

Set a spawned EVENT actor's target facing. arg0 = event key (not a monster/char id), arg1 = degrees (x181), arg2 = turn easing shift stored at actor+0xA0: each frame facing moves by (remaining >> shift), so 0 = snap, 1 = half the gap per frame, 2 = quarter (smoother). Sets record flag 0x8 (turn pending) for op 164.

Args:
  0. event key
  1. facing (degrees)
  2. turn ease (0 = snap, higher = slower)

### `op 163` — FaceEventActorTowardTarget(event key, look-at target, turn ease)
*handler:* `ScriptVM_Op_FaceCalendarEventTowardEntity`

Turn a spawned event actor to look at a roster actor. arg0 = event key (the one that turns), arg1 = look-at target (0 = player, 1..47 = NPC; values >= 48 are NOT supported - the handler uses an uninitialised pointer), arg2 = turn easing shift (0 = snap, n = 1/2^n of the remaining angle per frame).

Args:
  0. event key
  1. look-at target (0=player, 1-47 NPC)
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
  2. turn ease (0 = snap, higher = slower)

### `op 167` — EventActorPlayAnim(event key, anim id, loop)
*handler:* `ScriptVMOp_StartAnimOnCalendarEventActorWithLoopFlag`

Play an animation on a spawned event actor. arg0 = event key, arg1 = anim id, arg2 = loop flag (non-zero = keep repeating). Pair with QueryEventActorAnimBusy (op 169) to wait for a one-shot anim to finish.

Args:
  0. event key
  1. anim id
  2. loop (0/1)

### `op 168` — EventActorResyncAnimFrame(event key)
*handler:* `ScriptVMOp_SyncAnimFrameFromWidgetOnCalendarEventActor`

Force a spawned event actor to re-sync its animation frame from its widget after a state swap (fixes a one-frame visual pop when the anim state changes). arg0 = event key (char id). Low-level; pair with an anim change if you see a flicker.

Args:
  0. event key

### `op 170` — SetEventActorAnimSpeed(event key, anim speed %)
*handler:* `ScriptVMOp_CalendarEvent_SetActorMoveScaleFactor`

Set a spawned event actor's ANIMATION playback speed: model node (actor+0x20) +0x180 float = arg1 * 0.01 (100 = normal, 50 = half, 0 = frozen pose). Movement speed is not affected.

Args:
  0. event key
  1. anim speed % (100 = normal, 0 = freeze)

### `op 171` — SetEventActorAlpha(event key, alpha %)
*handler:* `ScriptVMOp_SetCalendarEventActorAlphaPercent0To100OrHide`

Fade a spawned event actor: arg1 = alpha percent 0..100 (packed into the sprite's 5-bit alpha). arg1 == 0 HIDES the actor (sets its hide flag). arg0 = event key (char id). Used for ghost/translucent/fade-in-out cutscene effects.

Args:
  0. event key
  1. alpha % (0-100, 0=hide)

### `op 172` — ShowEventActorEmote(event key, emote icon id)
*handler:* `ScriptVMOp_StopAnimAndClearOutfitOverride_OnCalendarEventActor`

Show an emote/balloon icon over a spawned event actor. arg1 = icon subtype (0 = clear). Stores it at actor+0x140 and, unless the same icon (>=16) is already shown, spawns Action 143 (VfxAction_SpawnPrimarySprite) at the actor with subtype arg1 and plays a matching SFX for ids 4/5, 6/8 and 14.

Args:
  0. event key
  1. emote icon id (0 = clear)

### `op 173` — SetEventActorInScriptFlag(event key)
*handler:* `Script_VMOp_MarkCalendarEventActorByEventId`

Set bit 0x80 of the event ACTOR's +0x234 flags (not the record). The only reader is monster AI opcode 0x80 (MonsterScript_Op80_IfScriptLocked), which treats the actor as 'in script/cutscene' and takes its scripted branch. arg0 = event key.

Args:
  0. event key

### `op 174` — AddActorHeightOffset(actor, height delta)
*handler:* `ScriptVMOp_AddVerticalVelocityToActorClampedByJumpFlag`

Add arg1 << 12 to the actor's height offset (actor+0x50, a position component integrated alongside x/y in Actor_IntegrateMotionAndFacing; NEGATIVE = up). Unless render_state_flags bit 0x4 is set the result is clamped to <= 0, so the actor cannot be pushed below its ground height. Target: 0 = player, 1..47 NPC, > 48 = event key (48 itself fails).

Args:
  0. actor (0=player, 1-47 NPC, >48 event key)
  1. height delta (negative = up)

### `op 175` — SetEventActorCollideRadius(event key, collision radius)
*handler:* `ScriptVMOp_SetCalendarEventActorWordField172`

Set a spawned event actor's collision radius: u16 at actor+0xAC (Actor_t.collide_radius) = arg1.

Args:
  0. event key
  1. collision radius

### `op 176` — SetEventActorScale(event key, scale %)
*handler:* `ScriptVMOp_SetCalendarEventActorSpriteTintGreyscale`

Set a spawned event actor's uniform model scale: scale_x/y/z (actor+0x88/+0x8C/+0x90) = arg1 * 167773 >> 12, i.e. percent -> Q12 (100 = 4096 = 1.0, 50 = half size).

Args:
  0. event key
  1. scale % (100 = normal)

### `op 177` — EventActorEnterIdle(event key, (unused — handler reads only 1 arg; shipped scripts pass 2))
*handler:* `ScriptVMOp_EnterActorIdleStateByCalendarEventKey`

Return a spawned event actor to its idle state, loading the default idle animation for its entity type. arg0 = event key. Use to reset an actor after a scripted anim/pose.

Args:
  0. event key
  1. (unused — handler reads only 1 arg; shipped scripts pass 2)

### `op 178` — SetEventActorTurnAngle(event key, angle)
*handler:* `ScriptVMOp_SetCalendarEventActorTargetFacingDegrees`

Set the target of an event actor's SECONDARY rotation (u16 at actor+0xD8 = 181*deg); Actor_IntegrateMotionAndFacing eases the current value at +0xD6 toward it using the same +0xA0 shift as facing. This is the angle pair op 113 WaitActorAuxYaw and op 179 test - NOT the movement facing (+0x9C/+0x9E) that ops 162/163/164 use.

Args:
  0. event key
  1. angle (degrees)

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

### `op 183` — SetActorAIScript(actor, AI script id)
*handler:* `ScriptVM_Op_SetEntityLevelAndSpawnMonster`

Replace an actor's monster-AI (AIBN) script. arg1 = AI script id: written to stats->ai_script_id (+0x54), the old script ctx gets flag 0x1000, and MonsterScript_SpawnTaskAndLoadScript starts a new AI task loading archive (id+1). arg1 = -1 instead sets the current script ctx flag 0x40000000 (the flag Npc_FinalizeTeleportAndNotify clears) without loading anything. Target: 0 = player, 1..47 NPC, >= 48 event key.

Args:
  0. actor (0=player, 1-47 NPC, 48+ event key)
  1. AI script id (-1 = suspend current)

### `op 184` — SetActorIgnoredByMonsters(actor, set)
*handler:* `ScriptVMOp_SetActorOrEventActorStatusEquipBit10000000`

Set/clear bit 0x10000000 of the actor's status_equip_flags (+0x10). Monster AI skips an actor with this bit when picking or validating a target, and Combat_ComputeDamage branches on it in the element-bonus step. arg1 != 0 sets, 0 clears. Target: 0 = player, 1..47 NPC, >= 48 event key.

Args:
  0. actor (0=player, 1-47 NPC, 48+ event key)
  1. set (0/1)

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

Recompute and re-apply the camera's per-map clamp bounds and zoom for the current map — NOT a player rotation. The handler calls Camera_SetBoundsForMap(active input-context/map id, flag), passing 0xFFFF while input is suppressed; that callee sets the script/follow camera's centre clamp from the map's tile dims and re-applies the small-map zoom. arg: 0 = write the camera distance directly onto the player's camera rig (flag=1 path); non-zero = apply via Camera_SetDistanceAndZoomFactor (flag=0 path). Used after scripted camera moves/zooms to restore the normal map camera.

Args:
  0. mode (0=direct distance write, else standard zoom apply)

### `op 206` — SetActorHeldItem(actor, item id)
*handler:* `Script_VMOp_CancelNpcPathOrPlayerEquipMainhand`

Set what an actor holds. NPC (arg0 1..47): arg1 = item id -> Npc_ClearActivePathTarget(actor, item|0x8000) which, as the id is negative as int16, calls Actor_EquipStartingItemByNpcParam and puts that item's model in the NPC's hand; arg1 = 1 -> passes 0 (re-apply the NPC's configured equipment when it is in equipped mode, else clear); arg1 = 0 -> destroys the three held-item models (actor inner +248/+256/+264) and zeroes the held ids +180/+182/+184. Player (arg0 = 0): arg1 = item id -> add to bag if absent (applying the pending-interaction record) and equip it as the main weapon; arg1 = 0 -> unequip the weapon to the bag and re-apply the other equipment.

Args:
  0. actor (0=player, 1-47 NPC)
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
  1. item id (0 = remove; NPC: 1 = default equipment)
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 207` — SetActorHeldItem(actor, item id)
*handler:* `Script_VMOp_CancelNpcPathOrPlayerEquipMainhand`

Set what an actor holds. NPC (arg0 1..47): arg1 = item id -> Npc_ClearActivePathTarget(actor, item|0x8000) which, as the id is negative as int16, calls Actor_EquipStartingItemByNpcParam and puts that item's model in the NPC's hand; arg1 = 1 -> passes 0 (re-apply the NPC's configured equipment when it is in equipped mode, else clear); arg1 = 0 -> destroys the three held-item models (actor inner +248/+256/+264) and zeroes the held ids +180/+182/+184. Player (arg0 = 0): arg1 = item id -> add to bag if absent (applying the pending-interaction record) and equip it as the main weapon; arg1 = 0 -> unequip the weapon to the bag and re-apply the other equipment.

Args:
  0. actor (0=player, 1-47 NPC)
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
  1. item id (0 = remove; NPC: 1 = default equipment)
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 208` — HandOrDropItem(target npc, item id)
*handler:* `Script_Action_HandOrDropItem`

**Cutscene 'NPC hands you a gift' primitive.** Spawns an item visual and attaches it to either an NPC's hand or the player. **arg 0 = target**: 0 = give to player (either attach to hand OR drop on ground if player has status 0x4000 / secondary_mod in the 'item-blocked' range 1..0x453 — plays Sfx 0x100226D + fires Action_TriggerActor(0x13)). >0 = NPC slot index (looked up via g_gameGlobalsSlotTable), then `Item_SpawnVisualTask` + `Npc_AttachHeldItem`. **arg 1 = item_id** masked to 11 bits (0..2047). The item metadata is loaded from `g_itemDatabase` (recipe metadata copied via 5-byte stride).

Args:
  0. target npc (0=player)
  1. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 211` — ShowActorEmote(actor, emote icon id)
*handler:* `ScriptVMOp_StopActorAnimAndClearOutfitOverride`

Show an emote/balloon icon over an actor (0 = player, -1 = current interaction NPC, 1..47 NPC). arg1 = icon id (0 = clear). Stored at actor+0x140; unless the same icon (>= 16) is already up, spawns Action 143 (VfxAction_SpawnPrimarySprite, subtype = icon) at the actor and plays an SFX for icons 4/5, 6/8 and 14. NPCs whose control_flags hidden bit 0x4 is set are skipped. No animation or outfit is touched.

Args:
  0. actor (0=player, -1=current NPC, 1-47 NPC)
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
  1. emote icon id (0 = clear)

### `op 212` — ShowActorEmote(actor, emote icon id)
*handler:* `ScriptVMOp_StopActorAnimAndClearOutfitOverride`

Show an emote/balloon icon over an actor (0 = player, -1 = current interaction NPC, 1..47 NPC). arg1 = icon id (0 = clear). Stored at actor+0x140; unless the same icon (>= 16) is already up, spawns Action 143 (VfxAction_SpawnPrimarySprite, subtype = icon) at the actor and plays an SFX for icons 4/5, 6/8 and 14. NPCs whose control_flags hidden bit 0x4 is set are skipped. No animation or outfit is touched.

Args:
  0. actor (0=player, -1=current NPC, 1-47 NPC)
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
  1. emote icon id (0 = clear)

### `op 217` — ApplyFriendshipDelta(npc id, mode, xp/value)
*handler:* `ScriptVM_Op_ApplyFriendshipDeltaToNpc`

Modify an NPC's friendship XP or absolute friendship. **3 args**: npc_id, mode, xp_or_value. The mode is arg1's TOKEN KIND, not its value (ScriptVM_Op_ApplyFriendshipDeltaToNpc, RF4S.exe+0x1FD2B0, reads the kind slot at idx-4): a `null` leaf = kind 4 = **ADD** (`Npc_AddFriendshipXpAndProcessLevelUp(npc, +xp)`), `zero` = kind 5 = **SUBTRACT** (`... , -xp)`), `self` = kind 6 = **SET absolute** (`Npc_SetFriendshipPointsAbsoluteAndCheckMaxAchievement(npc, value)`); listings print them add / sub / set. All 283 shipped uses are add. npc_id >= 48 is ignored. **Special: npc_id == 22 → dynamically resolves to the CHILD NPC id** via `GameFlags_ReadField(0, GF_REG_CHILD_ID, 5)`. That confirms slot 22 = Son is the runtime child-actor slot (paired with slot 23 = Daughter). The developers' '＊Date' test branch adds 99999999 xp (instant max friendship).

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
  1. mode (add / sub / set = the null / zero / self leaf)
  2. xp/value

### `op 221` — AdjustCurrentNpcFriendship(mode, xp/value)
*handler:* `ScriptVMOp_NpcFriendshipAdjustByKindWithCurrentInteraction`

Adjust the current interaction NPC's friendship. The mode is arg0's token KIND (like op 217's arg1), not its value: null leaf (kind 4) = add XP, zero leaf (kind 5) = subtract XP, self leaf (kind 6) = set points absolutely. arg1 = amount.

Args:
  0. mode (add / sub / set = null / zero / self leaf)
  1. xp/value

### `op 222` — LockNpcPose(npc)
*handler:* `ScriptVMOp_NpcLockFacingAndSetActionFlags`

Freeze an NPC's facing/pose for a cutscene: snapshots its current facing and sets the pose-locked + action-pending flags so it holds still and won't turn on its own. arg0 = npc (char id).

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

### `op 234` — HideNpc(npc, (unused — handler reads only 1 arg; corpus passes 2))
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

### `op 244` — NpcShowItem(npc)
*handler:* `Script_VMOp_BeginNpcItemShow`

Make an NPC hold up the item it is carrying: needs the NPC's model to hold an item (+304 -> +178 in 1..1107). If the NPC's actor state is 20 it instead puts the item away and returns to idle (Npc_ResetActorPostTeleport + Npc_FinalizeTeleportAndNotify); otherwise it starts the show-item action (actor state 19, anim archive base+18, tick NpcAction_TickItemShow).

Args:
  0. npc (char id, 1-47)
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

### `op 246` — StreamInNpcAtTile(npc, map id, x, y)
*handler:* `ScriptAction_StreamInNpcAtPosition`

Stream an NPC into a given map and place it at a tile with no walk-on: sets the NPC actor's map id (actor+84, via Actor_SetFacingDirection which is misnamed) and record+188 to arg1, runs the schedule spawn/place, writes X/Y (tiles<<12) to actor+88/+92 and record+192/+196, stops its anim if not moving, then (for npc != 0) drops any held item and restores its idle pose.

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
  1. map id
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

### `op 252` — SetActorAnimSpeedScale(actor, speed %)
*handler:* `ScriptVMOp_SetActorAnimSpeedScale`

Set an actor's animation speed multiplier. arg0 = actor (char id, 0 = player), arg1 = speed percent (÷100: 100 = normal, 50 = slow-mo, 200 = fast). The regular-actor twin of SetEventActorAnimSpeed (op 170).

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

Set an actor's animation speed multiplier. arg0 = actor (char id, 0 = player), arg1 = speed percent (÷100: 100 = normal, 50 = slow-mo, 200 = fast). The regular-actor twin of SetEventActorAnimSpeed (op 170).

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

Set or clear status-ailment bits on actor+180. arg0: 0 = player, 2 = companion 1, 3 = companion 2, anything else = the companion matching the current interaction NPC. arg1: 0 = clear 0x2F (every ailment except fatigue 0x10), 1 = set 0x2F (poison/seal/paralysis/sleep + cold, not fatigue), 2 = set 0x20 (cold), 3 = clear 0x0F, 4 = clear 0x30 (fatigue + cold).

Args:
  0. target (0 = player, 2/3 = companion slot, else talking companion)
  1. op (0 clear 0x2F, 1 set 0x2F, 2 set cold, 3 clear 0x0F, 4 clear fatigue+cold)

### `op 261` — SetNpcParticipationFlag(npc id …)
*handler:* `ScriptVMOp_SetNpcFriendshipBit80000000_RangeOrList`

Set bit 0x80000000 in npc record+52 (meaning not established). arg0 = 0: all villagers 1..23. Otherwise every arg is an npc char id (variadic, no count arg) and each gets the bit.

Args:
  0. npc id … (arg0 = 0 = all villagers 1-23)
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

### `op 263` — ResetNpcToIdle(npc)
*handler:* `ScriptVMOp_RespawnNpcAtScheduledPosition`

Reset an NPC's scripted action: destroy the item/prop it is holding (actor+264 task, model+178 cleared), restore its idle animation and idle tick (Npc_FinalizeTeleportAndNotify), and clear its movement target (actor+112/+120). Does not move the NPC.

Args:
  0. npc (char id, 1-47)
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

### `op 264` — ResetNpcToIdle(npc)
*handler:* `ScriptVMOp_RespawnNpcAtScheduledPosition`

Reset an NPC's scripted action: destroy the item/prop it is holding (actor+264 task, model+178 cleared), restore its idle animation and idle tick (Npc_FinalizeTeleportAndNotify), and clear its movement target (actor+112/+120). Does not move the NPC.

Args:
  0. npc (char id, 1-47)
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

### `op 266` — SetOrClearNpcSchedule(npc, map id, x, y, facing, apply, sched kind, sub kind, state)
*handler:* `Script_VMOp_NpcScheduleOrClear`

Pin an NPC to a scripted spot, or release it. Always writes the scripted-placement record: record+220 = {x, y, map id, facing}, record+228 = {2*sched kind | 1 (active), sub kind, state}, +232 = 0. arg5 != 0 then applies it (Npc_ApplyScheduleState(npc, 18)); arg5 == 0 instead resets the NPC's schedule working state (+17 = 18, frees the path buffers at +112/+120, clears flag bits) without clearing the record's active bit.

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
  1. map id
  2. x (tiles)
  3. y (tiles)
  4. facing (degrees, stored as deg*181>>8)
  5. apply (0 = release)
  6. sched kind
  7. sub kind
  8. state

### `op 267` — SetOrClearNpcSchedule(npc, map id, x, y, facing, apply, sched kind, sub kind, state)
*handler:* `Script_VMOp_NpcScheduleOrClear`

Pin an NPC to a scripted spot, or release it. Always writes the scripted-placement record: record+220 = {x, y, map id, facing}, record+228 = {2*sched kind | 1 (active), sub kind, state}, +232 = 0. arg5 != 0 then applies it (Npc_ApplyScheduleState(npc, 18)); arg5 == 0 instead resets the NPC's schedule working state (+17 = 18, frees the path buffers at +112/+120, clears flag bits) without clearing the record's active bit.

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
  1. map id
  2. x (tiles)
  3. y (tiles)
  4. facing (degrees, stored as deg*181>>8)
  5. apply (0 = release)
  6. sched kind
  7. sub kind
  8. state

### `op 270` — ReleaseNpcScriptedPlacement(npc, full reset)
*handler:* `Script_VMOp_RefreshNpcSchedule`

Hand an NPC pinned by a script (record+228 bit 0) back to its schedule for today: clears the pin; if the in-conversation bit (record+52 0x1000) was set it ends the conversation and ALWAYS does the full Npc_ResetDailyScheduleAndAi; otherwise arg1 == 0 applies today's state in place (Npc_ApplyScheduleState) while arg1 != 0 does the full schedule+AI reset (skipped when the NPC is flagged record+48 bit 0x10 and its current schedule map is walkable). Does nothing if the NPC is not pinned.

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
  1. full reset (0 = apply state only)

### `op 271` — ReleaseNpcScriptedPlacement(npc, full reset)
*handler:* `Script_VMOp_RefreshNpcSchedule`

Hand an NPC pinned by a script (record+228 bit 0) back to its schedule for today: clears the pin; if the in-conversation bit (record+52 0x1000) was set it ends the conversation and ALWAYS does the full Npc_ResetDailyScheduleAndAi; otherwise arg1 == 0 applies today's state in place (Npc_ApplyScheduleState) while arg1 != 0 does the full schedule+AI reset (skipped when the NPC is flagged record+48 bit 0x10 and its current schedule map is walkable). Does nothing if the NPC is not pinned.

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
  1. full reset (0 = apply state only)

### `op 275` — SetNpcPresenceState(npc, mode)
*handler:* `ScriptVMOp275_SetNpcPresenceStateAndFlag768`

Set or clear an NPC's town-presence state. arg1 == -1 clears the NPC's bit (1<<npc) in g_sys_npcPresenceBits, any other value sets it. Independently, record+52 bit 0x400000 (the present flag op 273 reads) is set to (arg1 == 1), so it is CLEARED for every value other than 1. When arg1 == 1 it also sets record+52 bits 0x300 (clearing 0x400), copies record+52 bit 0x80 into byte +16, and writes 0 to packed game-flag 768.

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
  1. mode (1 = present, -1 = absent, other = presence-mask bit only, clears the present flag)

### `op 281` — SetNpcDateState(npc, date state)
*handler:* `NpcSchedule_ApplyStateAndAwardFriendship`

Set an NPC's DATE STATE (3 bits at npc record +55; read by QueryNpcDateState, op 280, and em.bin's DATE_STATE query): 0 no date, 1 a date is promised for tomorrow, 2 the date is today, 3 on the date, 4 the date went well, 5 turned you down today. arg0 = npc (char id), arg1 = the state. Setting 4 also AWARDS friendship (up to the next level on the first date, otherwise +55). Lifecycle (traced 2026-09-25): the invitation scene sets 1 when the NPC accepts ('I would love to accompany you!') or 5 when they decline ('I have work to do tomorrow'); Day_UpdateNpcDailyFlags (RF4S.exe+0x227AE0) turns 1 into 2 at the daily rollover, clears 5, and treats a 2 that is still 2 as a stood-up date (stood-up mark 1-3, back to 0, em.bin EV_DATE_FINISH); Npc_TryDateInvitation_NightFinale does the same at 18:00/22:00; the date-day talk sets 3 when the date starts; leaving the party with 3 or 4 ends the date (Companion_SyncToScene: back to 0 + EV_DATE_FINISH).

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
  1. date state
     - `0` = no date
     - `1` = date promised
     - `2` = date today
     - `3` = on the date
     - `4` = date went well
     - `5` = turned you down

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

Set an NPC's outfit variant (Actor_ApplyNpcOutfitVariant loads model file + variant). arg1: 0 = default (clears record+52 bits 0x60), 1 = variant 1 / pajamas (sets 0x40), 2 or 4 = variant 2 / swimsuit (sets 0x20), 3 = variant 3 applied without record bits (not persistent). Bits 0x20/0x40 in the record make variants 1-2 persist.

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
  1. outfit (0 default, 1 pajamas, 2 swimsuit, 3 variant 3 not persisted)
     - `0` = Default
     - `1` = Pajamas
     - `2` = Swimsuit
     - `3` = Variant 3

### `op 289` — CarryBaby(actor)
*handler:* `ScriptVMOp_ActorCarryBaby_Dakko240`

Family-scene beat: the target actor picks up the newest child. Anim ordinal 240 resolves to 00_470_dakko.bfskl (the baby-CARRY pose, not a 'talking gesture'), and the gated callee spawns a task literally named 'baby' (MCModel 4*flag+1167) held by the actor. The gate reads GF_REG_CHILD_NUM then bit 287+(num-1) - the per-child variant flag choosing which baby model rides along. (Old 'TriggerActorTalkAnim + talk indicator' reading retired 2026-09-01.)

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

Write the packed marriage/family-status game-flag (packed id 4391 -> value 2) and run the family birthday/anniversary milestone check for today: compares the current date to the spouse's and children's birthdays and the wedding anniversary, setting the matching family-milestone game-flags. These go through GameFlags_WritePacked_OrAchievement (packed game-flags), NOT Steam achievements. No args. Used in anniversary/birthday cutscenes.

### `op 291` — SpawnChildEventRecords(value stored at record+4, value stored at record+6)
*handler:* `ScriptVMOp_SpawnSpecialCalendarEventRecordsByChildNum`

Add at most ONE child record to the calendar-event/placement registry (g_calendarEventMng_20wPerRecord, cap 32): only when GF_REG_CHILD_NUM != 0 (count clamped to 1). Record = {key 512, type 302 or 303 (by child variant flag 287), arg0, arg1, random word, active bit}.

Args:
  0. value stored at record+4 (u16)
  1. value stored at record+6 (u16)

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

Make an NPC wait before its next scheduled AI action: writes a jittered countdown into the NPC's schedule-wait timer (record +212). Value = uniform [0.75*arg1, 1.125*arg1) via the shared MMIX RNG; if 3/4*arg1 <= 0 nothing is written. NpcSchedule_Tick decrements it once per tick and performs the next schedule action when it hits 0; starting a move/interaction clears it. Does NOT touch friendship (2026-08 analysis). arg0 = npc (char id), arg1 = base wait (ticks).

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

### `op 303` — SetNpcActionDelay(npc, base wait)
*handler:* `Script_VMOp_SetNpcActionDelayWithJitter`

Make an NPC wait before its next scheduled AI action: writes a jittered countdown into the NPC's schedule-wait timer (record +212). Value = uniform [0.75*arg1, 1.125*arg1) via the shared MMIX RNG; if 3/4*arg1 <= 0 nothing is written. NpcSchedule_Tick decrements it once per tick and performs the next schedule action when it hits 0; starting a move/interaction clears it. Does NOT touch friendship (2026-08 analysis). arg0 = npc (char id), arg1 = base wait (ticks).

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

### `op 313` — RestorePlayerRP()
*handler:* `Script_VMOp_RestorePlayerRPFull`

Fully restore the player's RP (Rune Points) to max. No args.

### `op 315` — QueueNpcGreetingEvent(x, y)
*handler:* `Friendship_QueueNpcWaveEvent`

Find the NPC standing near tile (x, y) — within ~16 tiles and in the active input context — and queue a greeting / wave interaction event with them. arg0/arg1 = X/Y tiles. Sets that NPC as the interaction subject.

Args:
  0. x (tiles)
  1. y (tiles)

### `op 317` — SetNpcVisible(npc id, visible)
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

### `op 327` — EndActorTransformAndSetOutfit(actor, mode)
*handler:* `Script_VMOp_SetActorOutfitVariant`

arg0 = actor (0 = player, 48-255 ignored). arg1 == 255: if the actor is character-changed (status_equip_flags bit 0x8 set, 0x400 clear) spawn a 'char_change' task back to its own character (Actor_SpawnCharacterChangeTransformTask(actor, 0)). Other arg1: if both bits 0x408 are set, revert the same way first; then arg1 == 3 applies outfit variant 3. Player target also calls Player_BeginScriptedTalkAndIdle(1).

Args:
  0. actor (char id, 0 = player)
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
  1. mode (255 = end transform, 3 = outfit variant 3, other = revert only)

### `op 328` — EndActorTransformAndSetOutfit(actor, mode)
*handler:* `Script_VMOp_SetActorOutfitVariant`

arg0 = actor (0 = player, 48-255 ignored). arg1 == 255: if the actor is character-changed (status_equip_flags bit 0x8 set, 0x400 clear) spawn a 'char_change' task back to its own character (Actor_SpawnCharacterChangeTransformTask(actor, 0)). Other arg1: if both bits 0x408 are set, revert the same way first; then arg1 == 3 applies outfit variant 3. Player target also calls Player_BeginScriptedTalkAndIdle(1).

Args:
  0. actor (char id, 0 = player)
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
  1. mode (255 = end transform, 3 = outfit variant 3, other = revert only)

### `op 330` — SetActorOutfitDirect(actor, outfit variant)
*handler:* `Script_VMOp_SetActorOutfitDirect`

Directly set an actor's outfit/costume variant with NO transition animation (an instant swap). arg0 = actor (char id, 0 = player), arg1 = outfit variant id. The lightweight version of EndActorTransformAndSetOutfit (op 328).

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
     - `2` = Swimsuit
     - `3` = Variant 3

### `op 331` — SetActorOutfitDirect(actor, outfit variant)
*handler:* `Script_VMOp_SetActorOutfitDirect`

Directly set an actor's outfit/costume variant with NO transition animation (an instant swap). arg0 = actor (char id, 0 = player), arg1 = outfit variant id. The lightweight version of EndActorTransformAndSetOutfit (op 328).

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
     - `2` = Swimsuit
     - `3` = Variant 3

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

### `op 395` — SetPlayerFacingAndPose(facing, pose byte)
*handler:* `Script_VMOp_SetPlayerFacingAndPose`

Snap the player's facing to arg0 degrees (facing = deg * 181) and set the player byte at +0xA0 to arg1 (a pose/stance byte, 0-3 in the corpus); marks g_playerFacingDirty. Ops 395 and 396 share this handler.

Args:
  0. facing (degrees)
  1. pose byte

### `op 396` — SetPlayerFacingAndPose(facing, pose byte)
*handler:* `Script_VMOp_SetPlayerFacingAndPose`

Snap the player's facing to arg0 degrees (facing = deg * 181) and set the player byte at +0xA0 to arg1 (a pose/stance byte, 0-3 in the corpus); marks g_playerFacingDirty. Ops 395 and 396 share this handler.

Args:
  0. facing (degrees)
  1. pose byte

### `op 397` — SetPartyOutfit(outfit id)
*handler:* `Script_VMOp_SetPartyOutfitVariantAndSyncFriendship`

Change the outfit of the player and both companions. Outfit ids follow the fashion flags: 0 normal, 1 pajamas, 2 swimsuit, 3 wedding, 4 bath (4 also sets player control bit 0). Player: Actor_ApplyNpcOutfitVariant(player, arg). Companions with char id < 24: 1 persists the pajama bit (NPC state +52 bit 0x40), 2 or 4 persists the swimsuit bit (0x20), 0 clears both, 3 applies the wedding outfit without persisting. Returns the previous outfit ids: reg0 = player, reg1/reg2 = companion 1/2 (0 when absent).

Args:
  0. outfit id (0 normal, 1 pajamas, 2 swimsuit, 3 wedding, 4 bath)

### `op 400` — SetPlayerMale(male)
*handler:* `Script_VMOp_SetPlayerCharacterLestOrFrey`

Switch the player between Lest (arg != 0: model NPC_PLAYER_00, control bit 0x8000000, scale 4096) and Frey (arg = 0: NPC_PLAYER_01, scale 3904) via Player_SetCharacterVariantLestOrFrey, refresh the game-globals slot ids, then RESET the player name to the default for that gender (text archive 16369 rf3TxtNpc entry 0 'Lest' / entry 599 'Frey').

Args:
  0. male (1 = Lest, 0 = Frey)

### `op 427` — MaxWeaponSkills()
*handler:* `Script_VMOp_SetFirst6WeaponSkillsToLevel30`

Set the player's six weapon skills (Sword, Long Sword, Spear, Axe/Hammer, Dual Blade, Glove) all to level 30 and refresh the weapon-skill rank-unlock bits — a scripted/dev mastery grant (e.g. a New Game+ starter). Takes no arguments.

### `op 472` — SetGuestNpcSubVariant(npc, variant)
*handler:* `Script_VMOp_SetChildFriendshipByteAt2`

Write byte +2 of the per-NPC record for char id 24-47 (ignored if value >= 65). That byte is the guest's second dialogue/portrait variant: Town_BuildDailyGuestNpcRoster rolls it in [0,65) each day and Dialogue_ProcessLineDirective passes it to Dialogue_LoadEventLineWithPortrait.

Args:
  0. npc (char id 24-47)
  1. variant (0-64)

### `op 474` — SetGuestRosterGate(roster gate value, force rebuild)
*handler:* `Script_VMOp_SetCurrentEventLeadNpcAndClearFlag2`

Write arg0 to the header byte of the daily guest-NPC roster (RF4S.exe data at the IDB label g_currentEventParticipantNpcList_8u16; initialised to 100, and Town_BuildDailyGuestNpcRoster spawns no guests when it is 0). If arg1 != 0, also clear the roster's 'already built' bit (header word bit 0x2) so the next roster build runs again.

Args:
  0. roster gate value (0 = no guests)
  1. force rebuild (0/1)

### `op 475` — SetNpcStateByte(npc, value)
*handler:* `Script_VMOp_SetNpcFriendshipByteAt58`

Write arg1 to byte +58 (0x3A) of the NPC's record (g_gameGlobalsSlotTable entry) for char id < 48. What the byte means is not established. The 'relationship/state-machine' label has no support. An invalid id or missing table writes to address 0x3A (deliberate crash).

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

### `op 476` — RecruitNpcToParty(npc)
*handler:* `Script_VMOp_StreamInNpcAtPlayerPos`

Add an NPC to the player's party. If the NPC has no actor yet, stream it in (Npc_StreamInById) and place it at the player's position. Then Companion_AddOrSyncWithMarriageTrigger puts it in a free companion slot (Npc_RecruitAsCompanionAndStateClean -> Companion_FinalizeInPartyAllocStatsAndGauge: party slot, friendship gauge, equipment/stats). If both slots are full, companion 1 is dismissed first, and a date with them ends (EV_DATE_FINISH). No-op if the NPC is already a companion.

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

### `op 477` — RecruitNpcToParty(npc)
*handler:* `Script_VMOp_StreamInNpcAtPlayerPos`

Add an NPC to the player's party. If the NPC has no actor yet, stream it in (Npc_StreamInById) and place it at the player's position. Then Companion_AddOrSyncWithMarriageTrigger puts it in a free companion slot (Npc_RecruitAsCompanionAndStateClean -> Companion_FinalizeInPartyAllocStatsAndGauge: party slot, friendship gauge, equipment/stats). If both slots are full, companion 1 is dismissed first, and a date with them ends (EV_DATE_FINISH). No-op if the NPC is already a companion.

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

### `op 478` — RecruitNpcToPartyHeld(npc, held)
*handler:* `Script_VMOp_StreamInNpcAtPlayerPos_WithScriptedFlag`

Same as RecruitNpcToParty (stream in at the player's position if needed via Npc_RequestStreamInViaController + Npc_SetSlotWorldPosition, then add to a companion slot), then set (arg1 != 0) or clear bit 0x40000000 of the NPC record +52. That bit is the scene-held flag: Friendship_QueueFirstNpcEncounterEvent skips NPCs that have it, and Companion_DismissNpcAndRestoreSchedule clears it.

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
  1. held (0/1)

### `op 479` — RecruitNpcToPartyHeld(npc, held)
*handler:* `Script_VMOp_StreamInNpcAtPlayerPos_WithScriptedFlag`

Same as RecruitNpcToParty (stream in at the player's position if needed via Npc_RequestStreamInViaController + Npc_SetSlotWorldPosition, then add to a companion slot), then set (arg1 != 0) or clear bit 0x40000000 of the NPC record +52. That bit is the scene-held flag: Friendship_QueueFirstNpcEncounterEvent skips NPCs that have it, and Companion_DismissNpcAndRestoreSchedule clears it.

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
  1. held (0/1)

### `op 480` — RecruitHostNpcToParty()
*handler:* `Script_VMOp_WakeSceneChildOfCurrentInteractionNpc`

If there is a current interaction NPC (char id != 0xFFFF), add the script host's actor (host+32, i.e. the NPC whose script is running) to the party via Companion_AddOrSyncWithMarriageTrigger. That call dismisses companion 1 if both slots are full and ends a date with them. No args.

### `op 492` — FaceNpcToPlayer(mode)
*handler:* `Script_VMOp_SetSceneNpcFacingModeAndStandInFrontOfPlayer`

Set the script host NPC's scripted-facing mode (bits 16-17 of the dword at [actor+304]+448, read back by op 493) to arg0. Mode 1 also gives the NPC a stand point 96 world units from the player, on the line toward the NPC (written to [actor+296]+194/196), so it walks up and faces the player. Any other mode clears that stand point. Acts only on the host actor (host+32).

Args:
  0. mode (0 = off, 1 = stand in front of player, 2 = mode 2 without stand point)

### `op 553` — SetNpcSubEventFlag(set, npc char id …)
*handler:* `Script_VMOp_SetNpcRecordBit23ByList`

Set (arg0 != 0) or clear bit 0x800000 of record +52 for each listed NPC (char id < 48). If the list is empty or contains a 0, the bit is applied to all villagers 1-23 instead. FinishCurrentSubEvent (op 549) clears the same bit for everyone, so it is a sub-event participation marker; no reader was located, so what the bit gates is unproven (hence the neutral name).

Args:
  0. set (0 = clear, else set)
  1. npc char id … (0 or none = all villagers 1-23)

### `op 554` — SetNpcSubEventFlag(set, npc char id …)
*handler:* `Script_VMOp_SetNpcRecordBit23ByList`

Set (arg0 != 0) or clear bit 0x800000 of record +52 for each listed NPC (char id < 48). If the list is empty or contains a 0, the bit is applied to all villagers 1-23 instead. FinishCurrentSubEvent (op 549) clears the same bit for everyone, so it is a sub-event participation marker; no reader was located, so what the bit gates is unproven (hence the neutral name).

Args:
  0. set (0 = clear, else set)
  1. npc char id … (0 or none = all villagers 1-23)

### `op 562` — RefreshSceneNpcs()
*handler:* `Script_VMOp_RefreshAllNpcsOnSceneLoadAndUnblockVM`

Snap every NPC to their current scheduled position and unblock the cutscene VM. Call after a scene load or map change so NPCs appear where their daily schedule says they should be right now. Takes no arguments.

### `op 589` — PlayerPickUpObject()
*handler:* `Script_VMOp_PlayerPickupSceneObject1Tile`

Make the player pick up / carry the scene's target object: snaps the player to the ground if airborne, places the object one tile away, and starts the carry. The 'come pick this up' cutscene op. Takes no arguments.

### `op 594` — CommitGrabbedObject()
*handler:* `Script_VMOp_PlayerCommitGrabbedItemToBagIfThrowable`

If the player is holding a grabbed object that is flagged throwable, commit it into the bag. A pickup-convenience op. Takes no arguments.

### `op 620` — MarkSpouseCleared(spouse char id)
*handler:* `Script_VMOp_UnlockMonsterDexEntryAchievement`

Record that the given NPC was married (spouse cleared): reports flag/achievement 16582 with the NPC id, sets g_saveConfigFlags bit 1, sets bit [id] in g_sys_spouseClearedBits (rf4_sys.sav), then runs Marriage_FinalizeOnceAndBroadcastWedding.

Args:
  0. spouse char id

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

Set (arg1 != 0) or clear bit 0x4000 of Actor_t.control_flags (+568) on the actor with char id [arg0] (0 player, <48 NPC, >=48 event actor). Requires the actor to have a stats block. What the bit means is unknown: its writers include Npc_BuildCharNpcActorTask, Actor_SpawnByCharId, Npc_SpawnCharEventActor, Companion_DismissAndResetActorState, Player_BeginThrowAction, the boss ultimate-attack action and op 664; it is cleared in Player_OnHitCancelInteractionAndCinematic, Quest_OnReactionDispatched_AdvanceState and others. Nothing supports 'armor break'.

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

### `op 663` — MakeActorUntameable(char id)
*handler:* `Script_VMOp_SetActorHpRegenRateZeroByCharId`

Set the target actor's tame base (stats+0xDA) to 0, which makes the monster impossible to tame: MonsterTame_RollAttemptWithItem returns -1 when stats+218 == 0. arg0 = char id (0 player, <48 NPC, >=48 event actor, the usual case: event monsters 100-105/300).

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

On the target actor (char id: 0 player, <48 NPC, >=48 event actor), set stats+0xDC and stats+0xDE to -1 (IDB field names ai_sight_range / ai_fov_width), set control_flags (+568) bit 0x4000 (see op 662), and clear bit 0x800 of dword +40 of the object at actor field_108+32. Nothing here touches SP/RP.

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

### `op 692` — FinishPendingDate()
*handler:* `Script_VMOp_OnFirstMarriageAcceptanceUnlockAndReset`

Find the first NPC (ids 1-23) whose date state (npc_record+52 bits 24-26) is 1 or 2 (a date promised or scheduled today). If found: write packed flag/achievement 34346 = 0, reset that date state to 0, and dispatch em.bin entry 80 (EMFE_EV_DATE_FINISH, the post-date reset). No-op if no NPC has a pending date. No args.

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

Set party HP to a fraction of max. arg0 >= 0: player HEALS hp_max >> arg0; each companion is first damaged by its full hp_max and then healed hp_max >> arg0, i.e. its HP is SET to hp_max >> arg0 (flags two HUD entries for redraw). arg0 < 0: player HP is SET to hp_max >> -arg0 (full heal, then damage max - max>>n); companions untouched.

Args:
  0. shift (>= 0: player +max>>n, companions = max>>n; < 0: player = max>>-n)

### `op 314` — CurePartyStatus()
*handler:* `Script_VMOp_ClearPartyStatusConditions`

Cure the standard status conditions on the whole party (player + both companions): poison, paralysis, sleep, seal, and cold. Fatigue and faint are NOT cleared. No args. For medicine / recovery scenes.

### `op 483` — DismissBothCompanions()
*handler:* `Script_VMOp_SyncBothCompanionsToScene`

Dismiss both companions from the party. For each slot, Companion_SyncToScene kills its AI script and gauge. An NPC goes back to its schedule (Companion_DismissNpcAndRestoreSchedule), staying on the current map if its schedule has a spot here, else warping out with the departure effect (action 0x8C). A date in state 3/4 ends (EV_DATE_FINISH). A tamed monster is recalled to the farm (MonsterFarm_RecallCompanionAndRehome). No args.

### `op 484` — DismissBothCompanionsQuiet()
*handler:* `Script_VMOp_SyncBothCompanionsToScene_SetSyncFlag1`

Dismiss both companions like op 483, but first set dismiss-mode bit 0x1, which suppresses the departure effect (Action_TriggerAttacker 0x8C at the companion's position) for NPCs and recalled monsters. No args.

### `op 485` — DismissBothCompanionsEx(force return to schedule, no departure effect)
*handler:* `Script_VMOp_SyncBothCompanionsToScene_WithFlags`

Dismiss both companions with options. arg0 != 0 sets mode bit 0x2: the NPC is always sent back to its schedule, skipping the 'stay on this map' path. arg1 != 0 sets bit 0x1: no departure effect.

Args:
  0. force return to schedule (0/1)
  1. no departure effect (0/1)

### `op 486` — DismissCompanionByCharId(char id, force return to schedule, no departure effect)
*handler:* `Script_VMOp_SyncCompanionMatchingCharIdWithFlags`

Dismiss the one companion whose char id matches arg0 (no-op if none), with the same two mode flags as op 485. arg0 = 0 matches the script host's actor; arg0 = 22 is replaced by GameFlag REG_CHILD_ID (5 bits), not the spouse.

Args:
  0. char id (0 = host actor, 22 = REG_CHILD_ID)
  1. force return to schedule (0/1)
  2. no departure effect (0/1)

### `op 488` — SetCompanionScriptedPresence(mode)
*handler:* `Script_VMOp_SetBothCompanionScriptedPresenceAndMaybeReset`

Lock or release BOTH companions' AI for cutscene control. arg0 = 0 puts them in scripted-presence mode (the scene drives them); non-zero releases them back to normal AI (and resets their behaviour). The companion counterpart of SetNpcEngaged (op 223).

Args:
  0. mode (0=lock for scene, else release)

### `op 489` — SetCompanionsSceneHeld(release)
*handler:* `Script_VMOp_SetCompanionNpcRecordScriptedFlagAndQueueEncounter`

Set (arg0 == 0) or clear (arg0 != 0) the scene-held bit 0x40000000 of both companions' NPC records. When clearing at night (hour < 6 or > 18), queue companion event kind 2 for companion slots 1 and 2 through Friendship_QueueFirstNpcEncounterEvent. That call skips the spouse, NPCs still held, NPCs with friendship level >= 7, NPCs with a date state, and runs only when REG_SUBEV_NOW is 0. This is the late-night companion check, not a first meeting.

Args:
  0. release (0 = hold, else release and run the night check)

### `op 494` — SetCompanionVisible(slot, visible)
*handler:* `Script_VMOp_SetCompanionArmorBreakBit4`

Show or hide the companions. arg1 == 0 sets control_flags (+0x238) bit 0x4 (hidden, the same bit op 141 SetActorOpacity uses) on companion slot arg0 (0/1; >= 2 = both); non-zero clears it (shown; unlike op 141 no opacity is applied). The companion move/pose ops (496-501) clear the same bit and op 503 skips hidden companions. Nothing here affects damage.

Args:
  0. slot (0/1, >=2 = both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. visible (0 = hide, else show)

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

### `op 503` — ShowCompanionEmote(slot, emote icon id)
*handler:* `Script_VMOp_StopCompanionAnimAndClearOutfitOverride`

Show an emote icon over a companion (companion form of op 211 ShowActorEmote). For companion slot arg0 (0/1, 2 = both) whose actor is not hidden (control_flags bit 0x4 clear), Npc_StopAnimAndClearOutfitOverride(actor, arg1) stores arg1 at actor+0x140 and, unless the same icon (>= 16) is already up, spawns Action 143 (VfxAction_SpawnPrimarySprite, subtype = icon) and plays an SFX for icons 4/5, 6/8 and 14; arg1 = 0 clears the icon. Then clears control_flags bit 0x4 and field_B4 bits 0x10C. No animation or outfit is touched.

Args:
  0. slot (0 = companion 1, 1 = companion 2, 2 = both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. emote icon id (0 = clear)

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

Write `value` into global script-variable bank 4 (52 u32 slots) at [index]; index > 51 is ignored. The value is clamped as UNSIGNED to 999,999,999, so any negative value is stored as 999999999. Bank 4 is engine-global (not per-scene), is also written by the choice-commit system and is read by dialogue-text substitution codes; read back with GetVar4.

Args:
  0. index (0-51)
  1. value (clamped to 999999999)

### `op 353` — SetVar5(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind5`

Write `value` into global script-variable bank 5 (52 u32 slots) at [index]; index > 51 is ignored and the value is clamped as UNSIGNED to 999,999,999 (negatives become 999999999). Engine-global bank, also written by choice commit and read by dialogue-text substitution codes; read back with GetVar5.

Args:
  0. index (0-51)
  1. value (clamped to 999999999)

### `op 355` — SetVar6(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind6`

Write `value` into global script-variable bank 6 (52 u32 slots) at [index]; index > 51 is ignored and the value is clamped as UNSIGNED to 999,999,999 (negatives become 999999999). Engine-global bank, also written by choice commit and read by dialogue-text substitution codes; read back with GetVar6.

Args:
  0. index (0-51)
  1. value (clamped to 999999999)

### `op 359` — SetVar8(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind8`

Write `value` into global script-variable bank 8 (16 u32 slots) at [index]; index >= 16 is ignored, no value clamp. Special values: -1 stores companion 1's farm-table record index (signed u16 at actor+0x1E6, the index op 411 uses into g_MonsterFarmTable; -1 when the monster has no record) and -2 companion 2's (0 when that companion slot is empty). Read back with GetVar8; also read by dialogue-text substitution codes.

Args:
  0. index (0-15)
  1. value (-1 = companion 1 farm-table record index, -2 = companion 2's)

### `op 361` — SetVar9(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind9_WithNpcFallback`

Write `value` into global script-variable bank 9 (16 u32 slots) at [index]; index >= 16 ignored. value -1 is replaced by the calendar date code (day + 100*season) of the festival currently in progress (GameFlag REG_FESTA), when one is set. Bank 9 has no VM reader op; it is consumed by dialogue-text substitution codes and by NpcAi_ResolveVillagerBehavior.

Args:
  0. index (0-15)
  1. value (-1 = current festival's date code)

### `op 364` — SetVar10(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind10`

Write `value` into global script-variable bank 10 at [index] (index < 16, no value clamp). Bank 10 has no VM reader op; it is read directly by dialogue-text substitution codes.

Args:
  0. index (0-15)
  1. value

### `op 365` — SetVar15(index, value)
*handler:* `Script_VMOp_WriteVarArrayKind15`

Write `value` into global script-variable bank 15 at [index] (index < 16, no clamp). Bank 15 has no VM reader op; it feeds dialogue-text substitution codes (corpus writes ids like 23, 161-165 right before a dialogue line).

Args:
  0. index (0-15)
  1. value

### `op 366` — SetVar13And14(bank-13 value, index, bank-14 values…)
*handler:* `Script_VMOp_WriteVarArrayKind13AndKind14Multi`

bank13[arg1] = arg0 (0 is replaced by 0x3B49); then each further arg k (k >= 2) is written to bank14[arg1 + k - 2] (both banks 16 slots, out-of-range writes dropped). The common 3-arg form SetVar13And14(0, idx, v) puts v in bank 14 (read back with GetVar14) and the sentinel in bank 13; the 11/12-arg forms bulk-fill bank 14.

Args:
  0. bank-13 value (0 -> 0x3B49)
  1. index
  2. bank-14 values…

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

### `op 443` — SetFlagBit(flag id, value, (ignored), (ignored))
*handler:* `Script_VMOp_SetGameFlagBitDirect`

Set (arg1 != 0) or clear (arg1 = 0) GameFlags bit zone2_base + arg0 (zone-2 relative id). Only two args are read; shipped statements pass four, and the ignored third arg is 1 in about 40% of them, the fourth always 0.

Args:
  0. flag id (zone-2 relative)
  1. value (0 = clear, else set)
  2. (ignored)
  3. (ignored)

### `op 444` — SetFlagBitIfCond(flag id, em entry id)
*handler:* `Script_VMOp_SetGameFlagBitGatedByCondScript`

Set/clear GameFlags bit [flag id] from em.bin entry [entry id]'s condition A: cond TRUE -> clear the bit, FALSE -> set it (inverse!). The flag id is ZONE-2 RELATIVE (absolute bit 4096 + id; Script_VMOp_SetGameFlagBitGatedByCondScript adds the buffer's zone2_base), like ops 443/445 -- not an emdeb/emflags name.

Args:
  0. flag id
  1. em entry id

### `op 557` — SetNpcRecognitionFlags(value, npc ids)
*handler:* `Script_VMOp_UnlockPerNpcAchievementByList`

Write a per-NPC packed game-flag (base id 1451 + npc id) = [arg0] for each npc id in the variadic list (an npc id of 0 falls back to the married partner). These are the 23 per-NPC recognition flags (1451-1473); like op290/op698 they go through GameFlags_WritePacked_OrAchievement -- a graded packed-flag write, NOT one of the ~30 named Steam achievements.

Args:
  0. value
  1. npc ids (variadic)

### `op 558` — SetNpcRecognitionFlags(value, npc ids)
*handler:* `Script_VMOp_UnlockPerNpcAchievementByList`

Write a per-NPC packed game-flag (base id 1451 + npc id) = [arg0] for each npc id in the variadic list (an npc id of 0 falls back to the married partner). These are the 23 per-NPC recognition flags (1451-1473); like op290/op698 they go through GameFlags_WritePacked_OrAchievement -- a graded packed-flag write, NOT one of the ~30 named Steam achievements.

Args:
  0. value
  1. npc ids (variadic)

### `op 566` — RecordFestivalPlacement(placement, festival id)
*handler:* `Script_VMOp_OnStoryMilestoneProgressAndUnlock`

Record the player's placement in a festival contest. If placement is 1-3, broadcast it to the NPCs (Memory_BroadcastEventToNpcsAndApplyPlayerEffect(festival, placement)). Then read that festival's 2-bit best-placement field (packed ids 4876-4904; 0 counts as 4) and store the new placement if it is better, i.e. lower. The ids are packed game-flag fields, not achievements or story steps.

Args:
  0. placement (1-3)
  1. festival id (REG_FESTA value: 6, 8-17)

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

Load the VM REGISTER FILE reg0..reg9 (ctx+64..+100) from up to 10 argument values — reg[i] = arg[i]. These are the registers expressions read back via the reg tokens, SWITCH_EQ selectors dispatch on, and camera/position ops consume (GetPlayerPosition writes reg0/reg1; a staged PROMPT_CHOICE writes the pick to reg0). This op is how a script seeds them explicitly (1,825 uses). Registers are flat scratch — NOT saved across CALL — so consume them before the next op that writes reg0.

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

### `op 685` — SetFreeLookCameraMode(mode)
*handler:* `Script_VMOp_SetGlobalDword302E4`

Set the free-look camera control word (dword_...02E4) that ActionTask_TickFreeLookCamera reads every tick: nonzero lets the stick/d-pad drive the free-look camera; 2 (or higher) makes the camera exit (sfx 0x100223F, word reset to 0, task switched to ActionTask_TickPausedNoInputContext); 3 pauses it the same way without the reset. 0 = the tick's default branch.

Args:
  0. mode (0, 1, 2 = exit, 3 = pause)

## Audio

### `op 379` — PlayMusic(bgm id)
*handler:* `Script_VMOp_PlayBGMOrRestore`

Switch background music with a crossfade. **arg = -1 restores the contextual BGM** (clears the scripted-BGM marker bit 0x10000000 at ctx+116, calls Scene_ApplyContextualBGM). Otherwise starts BGM #arg via BGM_SwitchWithCrossfade and sets the scripted-BGM marker so the contextual picker won't override it. Also sets the 'first scripted BGM played' game-flag (packed id 1072, via GameFlags_WritePacked_OrAchievement) -- an internal milestone flag, not a Steam achievement. Special case: `arg == 16777332` triggers an additional Sfx_ApplyVoiceVolume with category-bias 45.

Args:
  0. bgm id (or -1 = restore)

### `op 380` — StopMusic((ignored; corpus passes 0-18000))
*handler:* `Script_VMOp_StopBGMWithCrossfade`

Stop the current BGM immediately (no fade): BGM_SwitchWithCrossfade(-1, arg/100) takes its negative-id branch, which calls Sfx_StopChannelVoice and ignores the fade argument. Also sets the scripted-BGM marker (host+116 bit 0x10000000) so the contextual BGM does not restart until PlayMusic -1.

Args:
  0. (ignored; corpus passes 0-18000)

### `op 382` — FadeMusicVolume(volume percent, fade duration)
*handler:* `Script_VMOp_SetSfxCaptureVolumeOverride`

Fade the BGM channel volume. arg0 != -1: remember the current BGM volume in host+264 and ramp the BGM (Sfx_GetVoiceSlotByChannel(-1)) to arg0/100 of the category volume over arg1 ticks. arg0 = -1: ramp back to the remembered volume over arg1 and clear host+264 to -1.0.

Args:
  0. volume percent (-1 = restore)
  1. fade duration

### `op 383` — SetMusicLock(lock)
*handler:* `Script_VMOp_SetSfxCaptureBypassFlag`

Set/clear the BGM lock byte (sound-task ctx +9). While set, Scene_ApplyContextualBGM does nothing, so the scripted track keeps playing across map changes and the 06:00/21:00 hour rolls instead of being replaced by the area music.

Args:
  0. lock (0/1)

### `op 384` — ResetMusicResumePositions()
*handler:* `Script_VMOp_ClearSfxCaptureWorkVars`

Zero the five per-class BGM resume positions (sound-task ctx +72..+91), so the next village/dungeon/story/title/jingle track started by BGM_SwitchWithCrossfade plays from the beginning instead of resuming.

### `op 385` — PlaySound(sfx id)
*handler:* `Script_VMOp_PlaySfxById`

Play a sound effect by id.

Args:
  0. sfx id
     - *(enum: 8923 values — use the in-editor picker or the id database)*

### `op 386` — StopVoices()
*handler:* `Script_VMOp_VoiceStopAllActive`

Stop all active voice slots.

### `op 387` — PlaySfxWithNpcRemap(sfx / voice id)
*handler:* `Script_VMOp_PlayVoiceOrSfxWithNpcVariantRemap`

Play a sound/voice by id, applying the per-NPC variant remap (calls Sfx_PlayByIdWithNpcVariantRemap): the remap picks a per-character voice/footstep variant when the same base sfx id is shared across characters (char-variant +5 remap windows; id 0 stops all menu audio; routes by id range to Sfx_PlayById or Player_PlayVoiceLine_VariantRemapped). Same callee the SetSpeaker* ops use for args >= 0x1F0 — which is why those args are voice ids. Companion op 385 plays a raw id without remapping.

Args:
  0. sfx / voice id
     - *(enum: 8923 values — use the in-editor picker or the id database)*

### `op 389` — SetPooledVoiceVolume(volume percent)
*handler:* `Script_VMOp_FindOrPreemptVoiceSlot`

Set a voice-pool slot's volume to arg0/100 immediately: Sfx_FindOrPreemptVoice picks a slot (a free one if any, else the lowest-priority / shortest-remaining playing voice) and Sfx_ApplyDistanceAttenuation(slot, arg0/100, 0) applies it. The argument IS read.

Args:
  0. volume percent

### `op 390` — StopVoiceId(voice id)
*handler:* `Script_VMOp_VoiceStopMatchingId`

Stop the voice matching an id.

Args:
  0. voice id
     - *(enum: 8923 values — use the in-editor picker or the id database)*

### `op 392` — PlayVoicedSound(sfx id)
*handler:* `Script_VMOp_PlaySfxByIdViaVoiceSlot`

Play a sound effect via a dedicated voice slot.

Args:
  0. sfx id
     - *(enum: 8923 values — use the in-editor picker or the id database)*

### `op 461` — SuppressRewardJingle()
*handler:* `Script_VMOp_SuppressNextRewardPopupSfx`

Set host+120 bit 0x40, which silences the jingle of every later reward popup from this script host (ops 457, 458, 459, 462); the reward ops only test the bit and never clear it.

## Time & calendar

### `op 300` — ResetAllNpcSchedules()
*handler:* `ScriptVMOp300_AdvanceDayResetSchedules`

Reset every villager (1..23) and every current event participant to today's schedule state with a full schedule+AI reset (Npc_ResetDailyScheduleAndAi), skipping NPCs mid-event (actor+16 bit 0x200) or already flagged; marks each reset NPC with record+48 bit 0x1000. The calendar is not touched. No args.

### `op 304` — GetYear()
*handler:* `Script_VMOp_GetCalendarMinute`

reg0 = the calendar YEAR (cal_inner+20). No args.

### `op 305` — GetSeason()
*handler:* `Script_VMOp_GetCalendarSeason`

Read the current calendar SEASON index into the VM output — NOT the hour. The handler reads cal_inner+16, and the verified calendar layout (from the SetTime handler and Calendar_NormalizeTimeCarry) is [+0 sec, +4 minute, +8 hour, +12 day, +16 season, +20 year]: the real hour lives at +8. Season is 0-3 (Spring..Winter). No args.

### `op 306` — GetDay()
*handler:* `Script_VMOp_GetCalendarDay`

Read the current calendar day.

### `op 307` — GetHourMinute()
*handler:* `Script_VMOp_GetCalendarMonthAndSeason`

reg0 = current HOUR (cal_inner+8, 0-23), reg1 = current MINUTE (cal_inner+4). No args.

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

reg0 = (day - 1) % 6 where day is the calendar day-of-season field (cal_inner +12, 0 treated as 1); range 0-5.

### `op 465` — SetCalendarPauseFlag(pause)
*handler:* `Script_VMOp_SetCalendarPauseFlagFromBit0`

Halt or resume in-game time during a scene — sets the scene's calendar-pause control flag from arg0's low bit (1 = the scene controls time). Use to freeze the clock for a cutscene, then release it.

Args:
  0. pause (bit 0)

### `op 466` — SkipToTime(hour, minute, target mode)
*handler:* `Script_VMOp_FastForwardCalendarToHourMinute`

Advance the clock and run the sleep fast-forward (Calendar_FastForwardForSleep). arg2 != 0: target mode - hours += (arg0 - hour) mod 24 and minutes += arg1 - minute when arg1 > minute. arg2 = 0: relative mode - hours += arg0, minutes += arg1. Quirks of target mode: when arg0 equals the current hour the CURRENT hour count is added, when arg1 equals the current minute the current minute is added, and when arg1 is below the current minute (current - arg1) minutes are added.

Args:
  0. hour (target, or delta when arg2 = 0)
  1. minute (target, or delta when arg2 = 0)
  2. target mode (1) / delta mode (0)

### `op 467` — SetTime(hour, minute, absolute)
*handler:* `Script_VMOp_SetOrAddCalendarHourMinute`

Set or advance the in-game CLOCK (hour:minute). arg0 = HOUR (cal_inner +8), arg1 = MINUTE (cal_inner +4), arg2 = 0 to ADD them as a delta or non-zero to SET them absolutely. Definitive field map from Calendar_NormalizeTimeCarry: cal_inner = [+0 Q12sec, +4 minute, +8 hour, +12 day, +16 season, +20 year]. The DAY/season/year fields (+12/+16/+20) are PRESERVED -- these ops do NOT take a date arg; the date advances only when the hour overflows 24 (-> day) or day overflows 30 (-> season). Normalizes overflow and refreshes the clock/weather UI. Shipped scenes: arg0 = an hour (12/23), arg1 = 0, arg2 = 1. Unlike op 466 SkipToTime this supports absolute-set + a full year-tier UI refresh. (Was mislabeled SetDate/day+month.)

Args:
  0. hour
  1. minute
  2. absolute (0=add, else set)

### `op 468` — FastForwardCalendar(year, season, day, mode)
*handler:* `Script_VMOp_FastForwardCalendarFineGrained`

Advance the calendar's year / season / day and run the sleep fast-forward (Calendar_FastForwardForSleep) plus a schedule refresh. Takes 4 args, not 5: arg0 = year, arg1 = season, arg2 = day, arg3 = mode. mode != 0 adds arg0/1/2 to year/season/day as deltas; mode 0 adds |arg0 - current year| and |arg2 - current day| (so reaches the target only when it is ahead; an equal value doubles the field) and adds arg1 to the season. It never touches hour; it also adds the current seconds and minute to themselves (doubles them) before normalising.

Args:
  0. year (delta or target)
  1. season (delta)
  2. day (delta or target)
  3. mode (0 = move toward target, non-zero = add deltas)

### `op 469` — SetOrAddCalendarDate(year, season, day, absolute)
*handler:* `Script_VMOp_SetOrAddCalendarYMDS`

Set or add the calendar year / season / day in one call, then run the sleep fast-forward and refresh the clock/weather HUD. arg3 = mode: non-zero sets the three fields directly, 0 adds them (if the added day lands on 0 it becomes day 30 of the previous season). Hour/minute are kept.

Args:
  0. year
  1. season (0-3)
  2. day (1-30)
  3. absolute (0 = add, non-zero = set)

### `op 627` — JumpToRandomDate()
*handler:* `Script_VMOp_SleepWithRandomizedMinuteAndUnpause`

Move the calendar to a random date in the current year: keeps the time of day (seconds/minute/hour) and the year, sets day = random 1..30 and season = random 0..3, normalizes, then runs Calendar_FastForwardForSleep to the new target with the per-minute callbacks suppressed. Afterwards clears the player's field_B4 and sets game-main work+8 bit 1. No args.

### `op 637` — SaveCalendarSnapshot()
*handler:* `Calendar_SaveSnapshot`

Save a calendar snapshot.

## Items, rewards, economy

### `op 209` — HandOrDropItem(target npc, item id)
*handler:* `Script_Action_HandOrDropItem`

**Cutscene 'NPC hands you a gift' primitive.** Spawns an item visual and attaches it to either an NPC's hand or the player. **arg 0 = target**: 0 = give to player (either attach to hand OR drop on ground if player has status 0x4000 / secondary_mod in the 'item-blocked' range 1..0x453 — plays Sfx 0x100226D + fires Action_TriggerActor(0x13)). >0 = NPC slot index (looked up via g_gameGlobalsSlotTable), then `Item_SpawnVisualTask` + `Npc_AttachHeldItem`. **arg 1 = item_id** masked to 11 bits (0..2047). The item metadata is loaded from `g_itemDatabase` (recipe metadata copied via 5-byte stride).

Args:
  0. target npc (0=player)
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

### `op 417` — ModifyPlayerResource(resource code, mode, amount)
*handler:* `Script_VMOp_ModifyPlayerResourceByCharCodeOp`

Grant or take a player resource (Script_VMOp_ModifyPlayerResourceByCharCodeOp, RF4S.exe+0x20D640). arg0 = resource char-code: 'd'(100)=gold (caps at 2,000,000,000; reaching 10M unlocks achievement 810), 'f'(102)=the player's level (base_stats.level), 'g'(103)=fodder (add/sub go through MonsterFarm_AddFodderToBin, set writes the bin), 'i'(105)=stone, 'j'(106)=compost (both cap 50,000); any other code does nothing -- the developers' '＊All Skills: Level 50' cheat passes the skill ids 0..39 and is a no-op in the shipped game. arg1 = the mode, taken from the argument's TOKEN KIND (the handler reads the kind slot at idx-4, not the value): `null` = add, `zero` = subtract, `self` = set; listings print them add / sub / set. arg2 = amount. Subtracting gold plays the coin-clink SFX. The 'pay 1000 gold' (`100, sub, 1000`) / 'here's a reward' (`100, add, N`) op.

Args:
  0. resource code (d=gold,f=level,g=fodder,i=stone,j=compost)
  1. mode (add / sub / set = the null / zero / self leaf)
  2. amount

### `op 423` — GivePlayerItem(item id, count, quality)
*handler:* `Script_VMOp_GivePlayerItemWithStackAndQuality`

Give the player item arg0 x arg1 at quality/level arg2 (stored as arg2-1 in each quality byte; 9 bytes for stackables, 1 otherwise), applying any attributes staged by op 421. Tries the backpack, then the rune-ability page; reg0 = 1 if it went into one of them. If both are full: when the player is already carrying something (status 0x4000 or a held item) the item is dropped at the player's feet with the drop jingle, otherwise the player holds it up in their hands. Ops 423 and 424 share this handler.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count
  2. quality (1-10)

### `op 424` — GivePlayerItem(item id, count, quality)
*handler:* `Script_VMOp_GivePlayerItemWithStackAndQuality`

Give the player item arg0 x arg1 at quality/level arg2 (stored as arg2-1 in each quality byte; 9 bytes for stackables, 1 otherwise), applying any attributes staged by op 421. Tries the backpack, then the rune-ability page; reg0 = 1 if it went into one of them. If both are full: when the player is already carrying something (status 0x4000 or a held item) the item is dropped at the player's feet with the drop jingle, otherwise the player holds it up in their hands. Ops 423 and 424 share this handler.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count
  2. quality (1-10)

### `op 425` — ForcePlayerHoldItem(item id, count, quality)
*handler:* `Script_VMOp_ForcePlayerHoldItemOrConsume`

Put an item straight into the player's hands (equipment record 0, the carried item) with the SE_HOLD jingle: arg0 = item id, arg1 = count, arg2 = quality (> 10 treated as 1). Staged op-421 attributes are applied. arg0 = 0 instead uses up the currently held stack (up to 15 decrements until empty).

Args:
  0. item id (0 = consume held)
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count
  2. quality

### `op 428` — TakeItem(item id, count, level filter)
*handler:* `Script_VMOp_TakeItemFromAnyContainer`

Remove arg1 (5-bit, max 31) of item arg0 from every player container in order: backpack (60), the carried item (decremented up to count times), equipment records 1-10, storage, weapon rack, closet, tool box, shipping box, fridge, bookshelf, rune page. A stack larger than the demand is reduced and the op stops; a stack equal to the demand is cleared and the op stops; a stack SMALLER than the demand is cleared and the scan continues with the full, undiminished demand. arg2 >= 0 restricts removal to copies whose level byte is 0; -1 = any level. The 'delivered' item effect, g_lastRemovedItemIdForScript and Player_ClearCarriedRecordsMatching only run when the scan reaches the end without an early stop.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count (max 31)
  2. level filter (-1 = any, >= 0 = level-1 copies only)

### `op 429` — TakeItemFromBackpack(item id, count, level filter)
*handler:* `Script_VMOp_TakeItemFromBackpackOrEquipExtras`

Same removal loop as op 428 but only over the 60 backpack slots, then the carried item (decremented up to count times if its id matches). arg2 >= 0 only removes level-byte-0 copies (-1 = any). A stack equal to the demand is cleared and the scan stops; only a smaller stack is cleared and followed by further removals with the full demand. Writes no result register.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count (max 31)
  2. level filter (-1 = any)

### `op 430` — ConsumeHeldItem(count)
*handler:* `Script_VMOp_ConsumeFromHeldItemNTimes`

Consume / use up N of the item the player is currently holding. arg0 = count. For 'the player uses the item' cutscene moments.

Args:
  0. count

### `op 452` — SpawnItemAtTile(item id, quality, count, x tile, y tile, as pickup)
*handler:* `Script_VMOp_SpawnItemAtTileAsDropOrVisual`

Spawn item arg0 in the world at tile (arg3, arg4) via Item_SpawnAtPositionAsDropOrVisual, as a pickup when arg5 != 0 or a visual-only prop when 0. arg1 is the QUALITY (clamped to 1-10, stored as arg1-1) and arg2 the COUNT (packed << 11). Staged op-421 attributes are applied.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. quality (1-10)
  2. count
  3. x tile
  4. y tile
  5. as pickup (0 = visual, 1 = pickup)

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

### `op 460` — AddRewardItem(reward slot, item id, quality, count)
*handler:* `Script_VMOp_AddItemToRewardSlotPopup`

Put an item into reward-popup slot arg0 (RewardSlot_AddToInventoryAndQueuePopup): arg1 = item id, arg2 = QUALITY (clamped to 1-10, stored as arg2-1), arg3 = COUNT (clamped to 1-9). Sets the item's discovered bit.

Args:
  0. reward slot
  1. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  2. quality (1-10)
  3. count (1-9)

### `op 462` — GrantFestivalRewards(item/token 1, count 1, item/token 2, count 2, item/token 3, count 3, item/token 4, count 4)
*handler:* `Festival_RollAndDistributeRewardsFromTemplate`

Open a reward popup (jingle 0x10000E9 unless op 461 was used) and fill up to 4 reward slots from (item, count) ARG PAIRS: even args pick the item - 9997 (0x270D) a random shop-available item among ids 111-114, 9998 (0x270E) a Shop_RollByCategoryFromTable roll over 13 categories, 9999 (0x270F) Loot_RollGenericFromTable, 10000 (0x2710) Loot_RollQuestSpecificFromTable (with a price-based stack when a request is active), anything else a literal item id - and each following odd arg sets that slot's count. At most 8 args are read.

Args:
  0. item/token 1
  1. count 1
  2. item/token 2
  3. count 2
  4. item/token 3
  5. count 3
  6. item/token 4
  7. count 4

### `op 463` — DropItem(item id)
*handler:* `Script_VMOp_DropSingleItemAtPlayer`

Drop a single item at the player.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 464` — DropItemStack(item id, quality, count)
*handler:* `Script_VMOp_DropItemStackAtPlayer`

Drop item arg0 at the player: arg1 = QUALITY (0 treated as 1, stored as arg1-1), arg2 = COUNT (packed << 11). Plays the drop jingle 0x100226D and action 0x13.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. quality
  2. count

### `op 563` — EquipScriptedWeapon(weapon item id)
*handler:* `Script_VMOp_ForceEquipWeaponSlot1AsScripted`

Temporarily arm the player with a specific weapon for a scripted scene (tutorials, cutscenes). Backs up whatever is in the mainhand slot, then force-equips arg0's item id there and refreshes the HUD. Pair with RemoveScriptedWeapon (op 564) to restore the player's real weapon afterwards.

Args:
  0. weapon item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 564` — RemoveScriptedWeapon()
*handler:* `Script_VMOp_RemoveScriptedWeaponAndRefreshHud`

Undo EquipScriptedWeapon (op 563): restore the mainhand weapon that was backed up when the scripted weapon was equipped, and refresh the HUD. Takes no arguments.

### `op 587` — PlaceFurniture(furniture/tile-object id, room id, tile x, tile y)
*handler:* `Script_VMOp_TryGiveTileObjectAndPlayDrop`

Place a furniture tile object (id [arg0], in the tile-object id space, not the item table) in room [arg1] at tile (arg2, arg3). Only allowed if that room has fewer than 16 active objects; id 328 is exempt and instead upgrades an existing 327 record in place. arg1 = -1 means the current room; tile -1 = default position. If placed in the current room (and id != 328), plays sfx 0x100226D and action 0x13 at the tile (or at the player). reg0 = 1 if placed, else 0.

Args:
  0. furniture/tile-object id
  1. room id (-1 = current room)
  2. tile x (-1 = default/player)
  3. tile y (-1 = default/player)

### `op 590` — BreakFurnitureIntoMaterials()
*handler:* `Script_VMOp_DropQuestBoxItems1022And1023AndDestroy`

Break the host furniture object: dirt-cloud puff, drop item 1022 (Lumber) and item 1023 (Material Stone) at its position, free its tile-object registry slot and destroy the object. Takes no arguments.

### `op 597` — RollShopCategoryItemReturnId(shop category)
*handler:* `Script_VMOp_RollShopCategoryItemReturnId`

Roll a random item id from a shop category table (Shop_RollByCategoryFromTable) and write it to the VM output slot for a following read.

Args:
  0. shop category

### `op 598` — RollRandomItemMatchingDisplayName(display-name string id)
*handler:* `Script_VMOp_RollRandomItemMatchingDisplayName`

Roll a random item among all items whose display-name string id == arg0 (items sharing a name) that pass Item_CheckShopFilter (the story/unlock gate); reg0 = the pick. If none pass, reg0 = the matching item with the lowest unlock threshold (data_28), or 82 if nothing matches.

Args:
  0. display-name string id

### `op 599` — RollRandomDishItem()
*handler:* `Script_VMOp_LootRollGenericFromTable`

Pick one of shop categories 5-11 uniformly (item ids 134-299, the cooked-dish range, Trout Sashimi..Turnip Heaven) and roll an unlocked item from it with Shop_RollByCategoryFromTable; reg0 = item id. No args.

### `op 600` — RollRandomEquipmentItem()
*handler:* `Script_VMOp_RollRandomShopItemFromRandomCategory`

Pick one of 16 fixed shop categories uniformly (15-19, 24-26 weapons; 33 shields; 34 accessories; 35 headgear; 36 shoes; 37 armor; 48/49 skill and spell items; 57 the 318-327 bread range) and roll an unlocked item from it; reg0 = item id. No args.

### `op 601` — RollRandomFurItem()
*handler:* `Script_VMOp_RollRandomRingItemIdInTier`

Roll a random unlocked item from {814, 815, 816, 879, 939} (Fur S/M/L, Wooly Furball, Quality Puffy Fur); reg0 = item id. If none passes Item_CheckShopFilter, falls back to the lowest-threshold member (default 814). No args.

### `op 602` — RollRandomMedicineOrFailedDish()
*handler:* `Script_VMOp_RollRandomTurnipFamilyItemIdInTier`

Roll a random unlocked item from ids 115-119, 123, 131-133 (Antidote Potion, Para-Gone, Roundoff, Cold Medicine, Formuade, Heavy Spice, Object X, Failed Dish, Disastrous Dish); reg0 = item id, fallback 132 (Failed Dish). No args.

### `op 603` — RollRandomGrassItem()
*handler:* `Script_VMOp_ShopRollByCategoryRange`

Roll a random unlocked item from ids 71-81 (Medicinal Herb, Antidote Grass and the colored grasses); reg0 = item id, fallback = the lowest-threshold member (initially 71). No args.

### `op 604` — RollRandomIngredientItem()
*handler:* `Script_VMOp_RollRandomMineralOrIngredientItemIdInTier`

Roll a random unlocked item from the fixed set {5, 33, 37, 38, 123, 294, 301, 304, 305, 306, 313} (Pink Melon, Leek, Hot-Hot Fruit, Giant Hot-Hot Fruit, Heavy Spice, Relax Tea Leaves, Chocolate, Milk S/M/L, Honey); reg0 = item id, default 301 (Chocolate). No args.

### `op 605` — RollRandomSeasoningItem()
*handler:* `Script_VMOp_RollRandomItemByLookupBytemask195`

Roll a random unlocked seasoning/cooking-base item: ids 123-126, 270, 271, 302, 310, 314-317 (Heavy Spice, Sweet Powder, Sour Drop, Mixed Herbs, Ketchup, Butter, Wine, Mayonnaise, Flour, Oil, Curry Powder, Rice Flour); reg0 = item id, default 314 (Flour). No args.

### `op 606` — RollThreeFlowerItemsAvoidDup()
*handler:* `Script_VMOp_RollThreeFlowerItemsAvoidDup`

Roll a 3-flower gift choice: writes item 63 (fixed first option) plus two distinct random flower/plant items to the THREE VM outputs reg0/reg1/reg2 (ctx+64/+68/+72). Candidates are item ids 63-70 and 84-109 that pass the shop filter (up to 40 collected); the two rolled picks avoid id 63 and each other (retry-capped, falling back to 65/67), using the global MMIX PRNG. No args. Used by the flower-choice gift dialogue.

### `op 607` — RollRandomFlowerSeedItem()
*handler:* `Script_VMOp_RollRandomItemByLookupBytemask28`

Roll a random unlocked flower seed: ids 758, 759, 765, 771, 773-785 (Moondrop, Toyherb, Pink Cat, Charm Blue, Cherry Grass ... White Crystal Seeds; vegetable seeds in 758-785 are excluded); reg0 = item id, default 759 (Toyherb Seeds). No args.

### `op 616` — QueryAndSetCraftedFlag(item id)
*handler:* `Script_VMOp_QueryAndSetCraftedItemFlagBit`

Test-and-set the 'has been crafted' flag. For an item id: looks up its craft record (Item_FindCraftDataRecordForItemId); reg0 = the OLD bit at zone2 + craft_id + 1062, then the bit is set (reg0 = 0 and nothing is set if the item has no craft record). For 100000: the handler sets flag zone2+1403 BEFORE reading it, so reg0 is always 1 (when a save is loaded).

Args:
  0. item id (100000 = misc-craft flag)
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

Promote the prince rank for every tier whose tourist threshold is reached (it can jump several ranks, up to 5), add each tier's gold reward to player gold (clamped to 2e9; sets flag 810 once gold >= 10,000,000). Outputs: reg0 = 1 if promoted, reg1 = the new rank, reg2 = the gold reward. No args.

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

### `op 681` — RollBreadRecipe(bread item id)
*handler:* `Script_VMOp_LootRollByCategoryForPlayer`

Roll the recipe the player learns from a recipe bread: arg0 = the bread item id (318/319 Medicine Bread(+), 320/321 Cooking Bread(+), 322/323 Weapon Bread(+), 324/325 Accessory Bread(+), 326/327 Farming Bread(+)). The pool is built from that bread's crafting-data archives, with weight 80 for the plain bread and 100 for the '+' version; Cooking Bread's pool depends on which kitchen utensils exist (or on unlock bit 23). reg0 = the rolled recipe's item id (0 if none).

Args:
  0. bread item id (318-327)

### `op 696` — RemoveItemFromBackpack(item id, count, level filter)
*handler:* `Script_VMOp_RemoveItemFromBackpackByIdAndCount`

Take [arg1] of item [arg0] from the backpack (60 slots). A slot matches if its id == arg0 and its flag bit (+2 bit 0) is set; with arg2 >= 0 it must also have level byte (+4) == 0 (arg2's value itself is not compared; -1 = any level). The first slot holding more than the count is reduced and the op ends. A slot holding <= count is emptied, and the search continues with the FULL count again (the remaining count is never reduced), so a split stack can lose more than asked. If nothing ended the search and the held item matches, it decrements the held stack up to count times and clears the carried records.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count
  2. level filter (-1 = any, >=0 = level-0 slots only)

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

### `op 150` — TriggerActionAtTile(action id, x, y)
*handler:* `Script_VMOp_TriggerActorAction`

Spawn a scripted Action (effect/task) at a world tile via Action_TriggerActor (g_actionConstructorTable dispatch — the 'Action 0xNN' family). arg0 = action id. arg1/arg2 = X/Y tiles. Action ids 65 and 105 auto-target the player's position instead of the passed tile.

Args:
  0. action id
  1. x (tiles)
  2. y (tiles)

### `op 151` — TriggerActionOnActor(action id, actor)
*handler:* `Script_VMOp_TriggerActorAttack`

Spawn an Action (g_actionConstructorTable id - the same id space as op 150/165, not an as_atk attack timeline) parented to an actor and placed at its position (payload flag byte +20 bit 0 set). arg0 = action id, arg1 = actor (0 = player, 1..47 NPC).

Args:
  0. action id
  1. actor (char id, 0=player)
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

Spawn a map entity, dispatched by TYPE ID to the right spawner — the central script-side object-placement op (handler ScriptVMOp_SpawnMapEntityByTypeIdDispatchTable). arg0 = entity type id: <20 → special trigger (treasure/quest item, Map_HandleSpecialTriggerEntity), 20-195 → placed game object 'pg_mobj' (Actor_AllocTask 65 → MapObj_SetupActorByTypeId), 196-335 → interactive object (door/stove/lift, Map_SpawnInteractiveObject), 336+ → decoration/scenery (MapDecoration_Spawn). arg1/arg2 = position, arg3 = facing (passed as DEGREES, handler multiplies by 182 = 65536/360 → u16 angle), arg4 = sub-param (handler multiplies by 40). args 5-10 = up to 6 optional EXTRA placement params (the handler copies them into a 6-slot buffer without a bound check: never pass more than 11 args) copied into the entity's setup struct; their meaning is ENTITY-TYPE-SPECIFIC (flags, linked ids, size, etc.). Dynamic prop/decor placement from a scene.

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

### `op 401` — SendMonsterToFarmArea(farm area)
*handler:* `Script_VMOp_MonsterFarmSpawnFromInteraction`

Send the barn monster this script belongs to (host+32) out to work farm area arg0: 1-3 = that area, -1 (0xFF) = a weighted-random free area, 0 = recall (clears the area bits 0x600 and the seed-planting order 0x40000). Sets record flags bits 9-10 = area plus 0x2000 and spawns its farm-worker task. Does nothing if the monster is already assigned to that area, is flagged 0x100, or the global at RF4S.exe+0xE3CB30 has id 0xFFFF.

Args:
  0. farm area (1-3, -1 = random free, 0 = recall)

### `op 402` — RecallFarmMonster(farm record index)
*handler:* `Script_VMOp_MonsterFarmSpawnOrClearFlags`

Stop a barn monster's field work. arg0 = -1: the script's own monster (host+32) via MonsterFarm_PickAreaAndSpawn(.., 1, 0), whose area-0 path clears the area bits 0x600 and the seed-planting order 0x40000. Otherwise arg0 is a g_MonsterFarmTable index and only its area bits 0x600 are cleared.

Args:
  0. farm record index (-1 = this script's monster)

### `op 405` — SetFarmMonsterPlantOrder(farm record index, plant seeds)
*handler:* `Script_VMOp_SetMonsterFarmLovedTodayBit`

Set or clear record flag bit 18 (0x40000) of a barn monster: arg0 = g_MonsterFarmTable index, or -1 for the monster this script belongs to (host+32); arg1 = 1 set / 0 clear. Bit 18 is the 'also plant seeds' work order: the farm-worker state machine goes to the seed-planting phase only when it is set. It is a standing order (not daily), cleared when the monster is recalled.

Args:
  0. farm record index (-1 = this script's monster)
  1. plant seeds (0/1)

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

### `op 593` — PickRandomPlacedFurniture(candidate furniture ids)
*handler:* `Script_VMOp_PickRandomActiveTileObjectByCandidates`

From a list of candidate furniture ids, gather those that have an active tile object in the current room and pick one at random. The pick is weighted by the id value itself (the ids are passed to MMIX_WeightedRandomPick as weights), and repeating an id raises its odds. Only 1 roll in 8 picks anything: 7/8 of the time reg0 = 0. reg0 = the picked id, or 0.

Args:
  0. candidate furniture ids (variadic)

### `op 617` — ShowStaffCredits(mode)
*handler:* `Script_VMOp_SpawnOrConfigureItemPickupIconTaskStaff`

Start the staff-credits task (task name 'staff', tick ItemPickupIcon_Tick_StateMachine). Mode 0 sets work+166 |= 0x10, mode 1 |= 0x18, modes 2 and 3 switch the tick to ItemPickupIcon_Tick_ScrollAndSpawn (the handler treats 2 and 3 identically). If the credits task already exists, it sets that task's work byte +172 = 1 (a finish/advance signal) only when host+312 is that task, and clears host+312.

Args:
  0. mode (0, 1 = fade variants; 2/3 = scrolling credits)
     - `0` = Fade (long)
     - `1` = Fade (short)
     - `2` = Credits (bottom)
     - `3` = Credits (top)

### `op 625` — EnterSharanceMazeStage(maze stage)
*handler:* `Trigger_DungeonAreaBegin`

Start a Sharance Maze challenge stage (0 Garden of Light, 1 Smoldering Prominence, 2 Deepwater Shrine, 3 Dragon Ruins, 4 Challenge to Fantasy, 5 Banquet of Nightmares). Sets g_currentBossState_modeFlag = stage, remembers the current room and the player's tile for the return trip (Dungeon_BeginArea), then writes scene-context fields +0x3C = 442, +0x3E/+0x40 = 0x120, +0x42 = 0 and sets +0x38 bit 0x80. The script warps with the next op.

Args:
  0. maze stage (0-5)

### `op 643` — ApplyPrinceOrder(order id, sub-index / variant)
*handler:* `Script_DispatchEffectById`

Buy and apply Prince Point order [arg0] (sub-index arg1: festival id, license/NPC variant, etc.). Orders 32-50 need and deduct all four costs (PP, lumber, material stone, gold); every other order deducts only PP = GetCost(id, sub). If unaffordable nothing changes. reg0 = 1 if the order was paid and applied, else 0.

Args:
  0. order id
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

### `op 678` — WallOffTileRect(x, y, width, height)
*handler:* `Script_VMOp_ResetTileAttribFlagsInRectTo2`

Turn every tile of a rectangle of the current map into WALL: each cell becomes cell & 0xFFFEFE70 | 0x2 (the walking bits cleared, then 0x2 set -- the bit that blocks the player, monsters and NPCs), clipped to the grid (Script_VMOp_ResetTileAttribFlagsInRectTo2, re-read 2026-09-27). Lasts until the map is loaded again. arg0/arg1 = x/y, arg2/arg3 = width/height, all in fine units (sub-units, >>3 = tiles).

Args:
  0. x (fine)
  1. y (fine)
  2. width (fine)
  3. height (fine)

### `op 689` — RespawnRoomFurnitureVisuals()
*handler:* `Script_VMOp_ResetMonsterSpawnTrackerForPlayer`

Re-spawn the visual tasks of every active furniture/tile object in the player's current room/context (the one held by the player is skipped). A redraw of placed furniture; no monsters are involved. No args.

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

Read 1 iff a primary NPC and all listed NPCs are available (not busy/sleeping schedule codes 13/25, not already mid-event, not inaccessible) AND each listed NPC is within a max distance of the primary — the quest-event group gate. arg0 = max distance, arg1 = primary npc (char id, <48), arg2+ = the other npc ids (their count is implied by the arg count — there is no explicit count arg). Writes 1/0 to reg0. Like op 240 but also requires the NPCs aren't already mid-event.

Args:
  0. max distance
  1. primary npc
  2. other npc …

### `op 507` — PopulateSlayRequest(monster char id, kill count, reward category …)
*handler:* `Quest_PopulateNpcSlot`

Post a kind-1 (slay monsters) request into the host NPC's request record (char id < 24, else record 0). arg0 = monster char id (0 = DailyVisitor_PickWantedItem: weighted pick of 48..199, 1-in-16 chance of the 200..253 boss band, story-gated). arg1 = kill count (0 = random 1-4; forced to 1 for ids 200..253). Each further arg is a reward CATEGORY: Shop_RollByCategoryFromTable rolls one reward item per arg into rewards[0..3] (-1 skips). The record is written only if not already posted (status bit 0x2), except record 0. Status becomes posted + fresh (0x4002). reg0 = 1 if a target existed.

Args:
  0. monster char id (0 = random)
  1. kill count (0 = random 1-4)
  2. reward category … (up to 4, -1 = none)

### `op 508` — PopulateQuestKind2RandomRewards(target item id, param byte, count, reward category …)
*handler:* `Script_VMOp_PopulateQuestRequestKind2WithRandomCats`

Post a kind-2 request into the host NPC's record (char id < 24, else record 0; skipped if already posted, except record 0): +2 = arg0 item, +5 = arg1, +4 = arg2 (count). Each further arg is a reward category: Shop_RollByCategoryFromTable rolls up to 4 reward items (re-rolling up to 64 times so a reward never equals the target item) into rewards[0..3]. No register result. The preview op (532) returns target / count / rewards / param in reg0 / reg1 / reg2-4 / reg5.

Args:
  0. target item id
  1. param byte (+5; corpus: an NPC char id local / REG_CHILD_ID)
  2. count (+4)
  3. reward category … (up to 4)

### `op 509` — PopulateQuestKind2RandomRewards(target item id, param byte, count, reward category …)
*handler:* `Script_VMOp_PopulateQuestRequestKind2WithRandomCats`

Post a kind-2 request into the host NPC's record (char id < 24, else record 0; skipped if already posted, except record 0): +2 = arg0 item, +5 = arg1, +4 = arg2 (count). Each further arg is a reward category: Shop_RollByCategoryFromTable rolls up to 4 reward items (re-rolling up to 64 times so a reward never equals the target item) into rewards[0..3]. No register result. The preview op (532) returns target / count / rewards / param in reg0 / reg1 / reg2-4 / reg5.

Args:
  0. target item id
  1. param byte (+5; corpus: an NPC char id local / REG_CHILD_ID)
  2. count (+4)
  3. reward category … (up to 4)

### `op 510` — PopulateQuestKind2LiteralRewards(target item id, param byte, count, reward item id …)
*handler:* `Script_VMOp_PopulateQuestRequestKind2WithLiteralAlternates`

Post a kind-2 request like op 508, but the trailing args are literal reward item ids copied verbatim into rewards[0..3] (no roll, no stop on 0).

Args:
  0. target item id
  1. param byte (+5)
  2. count (+4)
  3. reward item id … (first 4 kept)

### `op 511` — PopulateQuestKind3RandomRewards(item A, item B, count, param byte, reward category …)
*handler:* `Script_VMOp_PopulateQuestRequestKind3TwoItemsRandomCats`

Post a kind-3 request into the host NPC's record: +6 = arg0, +8 = arg1 (two u16s, presumably two items; +2 target stays 0), +4 = arg2, +5 = arg3. Each extra arg (from arg4) is a reward category rolled into rewards[1..3]. The loop index is off by one, so rewards[0] stays 0 and a 4th category is dropped.

Args:
  0. item A (+6)
  1. item B (+8)
  2. count (+4)
  3. param byte (+5)
  4. reward category … (up to 3)

### `op 512` — PopulateQuestKind3RandomRewards(item A, item B, count, param byte, reward category …)
*handler:* `Script_VMOp_PopulateQuestRequestKind3TwoItemsRandomCats`

Post a kind-3 request into the host NPC's record: +6 = arg0, +8 = arg1 (two u16s, presumably two items; +2 target stays 0), +4 = arg2, +5 = arg3. Each extra arg (from arg4) is a reward category rolled into rewards[1..3]. The loop index is off by one, so rewards[0] stays 0 and a 4th category is dropped.

Args:
  0. item A (+6)
  1. item B (+8)
  2. count (+4)
  3. param byte (+5)
  4. reward category … (up to 3)

### `op 513` — PopulateQuestKind4RandomRewards(target item id, param byte, count, reward category …)
*handler:* `Script_VMOp_PopulateQuestRequestKind4ChainedRandom`

Post a kind-4 request into the host NPC's record: +2 = arg0 item, +5 = arg1, +4 = arg2 (count). Each further arg is a reward category rolled once into rewards[0..3] (no re-roll). The 'chained' seed feedback is dead: every iteration re-reads its own arg.

Args:
  0. target item id
  1. param byte (+5)
  2. count (+4)
  3. reward category …

### `op 514` — PopulateQuestKind4RandomRewards(target item id, param byte, count, reward category …)
*handler:* `Script_VMOp_PopulateQuestRequestKind4ChainedRandom`

Post a kind-4 request into the host NPC's record: +2 = arg0 item, +5 = arg1, +4 = arg2 (count). Each further arg is a reward category rolled once into rewards[0..3] (no re-roll). The 'chained' seed feedback is dead: every iteration re-reads its own arg.

Args:
  0. target item id
  1. param byte (+5)
  2. count (+4)
  3. reward category …

### `op 515` — PopulateQuestKind4LiteralRewards(target item id, param byte, (ignored), reward item id …)
*handler:* `Script_VMOp_PopulateQuestRequestKind4Byte4_1LiteralAlts`

Post a kind-4 request with count forced to 1: +2 = arg0 item, +5 = arg1. arg2 is never read (the literal loop starts at index 3). From arg3 on, literal reward item ids go verbatim into rewards[0..3].

Args:
  0. target item id
  1. param byte (+5)
  2. (ignored)
  3. reward item id …

### `op 516` — PostBoardQuestKind5(param byte)
*handler:* `Script_VMOp_PopulateQuestRequestKind5SimpleNoAlts`

Overwrite request record 0 (the board record, whoever the host NPC is) with a kind-5 entry: +5 = arg0, +10 = host char id, state 1, status reset to posted (0x2). No target item, count or rewards.

Args:
  0. param byte (+5)

### `op 517` — PostBoardQuestKind5(param byte)
*handler:* `Script_VMOp_PopulateQuestRequestKind5SimpleNoAlts`

Overwrite request record 0 (the board record, whoever the host NPC is) with a kind-5 entry: +5 = arg0, +10 = host char id, state 1, status reset to posted (0x2). No target item, count or rewards.

Args:
  0. param byte (+5)

### `op 518` — PostBoardQuestKind6(param byte, count)
*handler:* `Script_VMOp_PopulateQuestRequestKind6TwoArgsNoItem`

Overwrite request record 0 (the board record) with a kind-6 entry: +5 = arg0, +4 = arg1 (count/goal), no target item and no rewards.

Args:
  0. param byte (+5)
  1. count (+4)

### `op 519` — PostBoardCraftQuest(craft category, item id, param byte, count)
*handler:* `Script_VMOp_PopulateQuestRequestKind7CraftRecipeExpose`

Overwrite request record 0 with a kind-7 (craft) entry: +8 = arg0 craft category, +2 = arg1 item, +5 = arg2, +4 = arg3. Then load that category's craft data and, if the item has a recipe, return its up to 6 non-zero ingredient ids in reg1..reg6 and their count in reg0.

Args:
  0. craft category
  1. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  2. param byte (+5)
  3. count (+4)

### `op 520` — PostQuestGoalNumber(goal number, reward item ids)
*handler:* `Script_VMOp_PopulateQuestRequestKind8_GoalNumberLiteralRewards`

Post a request-box GOAL-NUMBER quest (slot kind 8): an objective with NO target item where the player must reach a number — a skill level, an upgrade level, a tamed-monster count, a craft count. arg0 = the goal number shown to the player (display only: completion is checked by the request scene itself via query ops / em conditions, never by slot progress); further args = LITERAL reward item ids written verbatim into reward_items[0..3] (stops at the first 0; no category roll). Also binds the posted slot to the script task's reward-template pointer (task+136) so the accept/complete/reward-popup ops that follow read this quest. All 6 retail uses are Eliza tutorial requests in bank 210, e.g. (20,3000) = 'Raise Skill Levels!' (any skill >= 20), (15,1052 Rush Attack) = 'Upgrade Weapons!', (5,0) = 'Befriend Monsters!'. IDA-verified 2026-09-01: the literals are the REWARDS, not alternate objective items.

Args:
  0. goal number (level/count to reach)
  1. reward item ids (variadic, literal)

### `op 521` — PopulateQuestKind9LiteralRewards(target item id, reward item id …)
*handler:* `Script_VMOp_PopulateQuestRequestKind9BackrefLiteralAlts`

Post a kind-9 request into the host NPC's record (else record 0): +2 = arg0 item. Literal reward item ids from arg1 go into rewards[0..3] (stop at the first 0). The record pointer is bound to the script task (task+136) so the following accept/complete/reward ops use it.

Args:
  0. target item id
  1. reward item id … (0 ends)

### `op 522` — PopulateQuestKind10RandomRewards(reward category …)
*handler:* `Script_VMOp_PopulateQuestRequestKind10BackrefRandomCats`

Post a kind-10 request (no target, count or param) into the host NPC's record (else record 0) and bind it to the script task (task+136). Each arg is a reward category rolled into rewards[0..3]; a 0 category stops the list.

Args:
  0. reward category … (0 ends)

### `op 523` — PopulateQuestKind10LiteralRewards(reward item id …)
*handler:* `Script_VMOp_PopulateQuestRequestKind10BackrefLiteralAlts`

Post a kind-10 request (no target) into the host NPC's record (else record 0), bind it to the script task (task+136), and copy the literal reward item ids (0 ends) into rewards[0..3].

Args:
  0. reward item id … (0 ends)

### `op 525` — QuestOnComplete()
*handler:* `Quest_OnComplete`

Complete the quest bound to the script task (task+136): RQ clear count +1, write the quest id to a packed flag, queue companion event 10, Quest_OnComplete_TriggerNpcReactions (friendship). A villager request (record npc != 0) adds prince points (category 7). A board request adds category-6 points, bumps REG_RQ_COUNT, or sets the per-insert flag (2684 + REG_INSERT_NOW) when REG_INSERT_NOW is set; for board quest ids 33-36 it instead clears daily-visitor discount bit 0-3, and decrements REG_REM_QUEST_COUNT. The record is then zeroed and marked done (0x8001). No items are given here; the reward popup op does that.

### `op 528` — QueryQuestRewardItem(request record, reward index)
*handler:* `Script_VMOp_QueryQuestRewardItemAt`

reg0 = reward item idx (0-3) of request record [arg0] (the 24-byte request record of char id arg0; 0 = the board record). An index >= 4 returns 1. The record index is not range-checked.

Args:
  0. request record (char id < 24, 0 = board)
  1. reward index (0-3)

### `op 529` — ClearAllRequestRecords()
*handler:* `Script_VMOp_ClearAllNpcQuestRewardTemplates`

Zero all 24 request records (576 bytes: the board record and every villager's request, including status bits). No args.

### `op 530` — CommitQuestAcceptance()
*handler:* `Quest_CommitAcceptance`

Commit the player's acceptance of the offered quest — moves it from 'preview' to an active daily request on the NPC. The second step of the two-step accept (preview → commit).

### `op 531` — ClearBoardRequest()
*handler:* `Script_VMOp_QuestSceneTeardownAndClearRewards`

Dispatch em.bin alt action EV_SUBEV_COM_52, zero request record 0 (the board record, all 24 bytes), and set scene control flags (& 0xFF3EFFFF | 0x800000). No args.

### `op 532` — QueryNpcQuestPreview()
*handler:* `Script_VMOp_QueryCurrentInteractionNpcQuestPreview`

If the interaction NPC's request record (char id < 24, else record 0) is posted (status 0x2): reg0 = target item (+2), reg1 = count (+4), reg2..reg4 = rewards[0..2], reg5 = param byte (+5), reg6 = accepted (status bit 0x4). Otherwise reg6 = 0 and the other registers are unchanged.

### `op 535` — QueryQuestRemainingByItem(item id)
*handler:* `Script_VMOp_QueryQuestRequestRemainingByItemId`

reg0 = max(0, count - progress) of the first request record whose target equals arg0 (0 if its state is 2). Bug: the loop bound is an uninitialised stack byte (the unused home slot of the 2nd argument), so the number of records searched is undefined.

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 536` — StartReservedSubEvent()
*handler:* `Script_VMOp_OnRequestBoxFirstSubmitAchievementAndScriptCallback`

If no sub-event is running (REG_SUBEV_NOW == 0) and one is reserved (REG_SUBEV_RSV != 0): move RSV into NOW and clear RSV. Set request-array flag 0x4, dispatch em.bin EV_SUBEV_INIT and the sub-event's own entry (id + 118, for ids 25..143), clear scene flag 0x200000, zero two more 9-bit registers (packed 0x80B4 / 0x80BD), and register SubEvent_AdvanceNowTimer in a free calendar callback slot (index kept for op 549). No args.

### `op 537` — QueueSubEventGoalKind2(target item id, param byte, count)
*handler:* `Script_VMOp_PopulateQuestRequestKind2WithRandomCats`

Queue-mode alias of op 508. Because the opcode is >= 537, the handler does not touch the NPC request record. If a sub-event is running (REG_SUBEV_NOW != 0) and fewer than 20 entries are queued, it appends a 24-byte kind-2 entry {+2 item = arg0, +5 = arg1, +4 count = arg2, +10 host char id, state 1 = active} to the sub-event goal queue (count at request-array byte 3, entries at RF4S.exe data 0xE9AF0C). Reward args are ignored in this mode.

Args:
  0. target item id
  1. param byte (+5)
  2. count (+4)

### `op 538` — QueueSubEventGoalKind2(target item id, param byte, count)
*handler:* `Script_VMOp_PopulateQuestRequestKind2WithRandomCats`

Queue-mode alias of op 508. Because the opcode is >= 537, the handler does not touch the NPC request record. If a sub-event is running (REG_SUBEV_NOW != 0) and fewer than 20 entries are queued, it appends a 24-byte kind-2 entry {+2 item = arg0, +5 = arg1, +4 count = arg2, +10 host char id, state 1 = active} to the sub-event goal queue (count at request-array byte 3, entries at RF4S.exe data 0xE9AF0C). Reward args are ignored in this mode.

Args:
  0. target item id
  1. param byte (+5)
  2. count (+4)

### `op 539` — QueueSubEventGoalKind3(item A, item B, count, param byte)
*handler:* `Script_VMOp_PopulateQuestRequestKind3TwoItemsRandomCats`

Queue-mode alias of op 511: append an active kind-3 entry {+6 = arg0, +8 = arg1, +4 = arg2, +5 = arg3, +10 host} to the sub-event goal queue when REG_SUBEV_NOW != 0 (max 20). No reward rolls.

Args:
  0. item A (+6)
  1. item B (+8)
  2. count (+4)
  3. param byte (+5)

### `op 540` — QueueSubEventGoalKind3(item A, item B, count, param byte)
*handler:* `Script_VMOp_PopulateQuestRequestKind3TwoItemsRandomCats`

Queue-mode alias of op 511: append an active kind-3 entry {+6 = arg0, +8 = arg1, +4 = arg2, +5 = arg3, +10 host} to the sub-event goal queue when REG_SUBEV_NOW != 0 (max 20). No reward rolls.

Args:
  0. item A (+6)
  1. item B (+8)
  2. count (+4)
  3. param byte (+5)

### `op 541` — QueueSubEventGoalKind4(target item id, param byte, count)
*handler:* `Script_VMOp_PopulateQuestRequestKind4ChainedRandom`

Queue-mode alias of op 513: append an active kind-4 entry {+2 item = arg0, +5 = arg1, +4 count = arg2, +10 host} to the sub-event goal queue when REG_SUBEV_NOW != 0 (max 20). No reward rolls.

Args:
  0. target item id
  1. param byte (+5)
  2. count (+4)

### `op 542` — QueueSubEventGoalKind4(target item id, param byte, count)
*handler:* `Script_VMOp_PopulateQuestRequestKind4ChainedRandom`

Queue-mode alias of op 513: append an active kind-4 entry {+2 item = arg0, +5 = arg1, +4 count = arg2, +10 host} to the sub-event goal queue when REG_SUBEV_NOW != 0 (max 20). No reward rolls.

Args:
  0. target item id
  1. param byte (+5)
  2. count (+4)

### `op 543` — QueueSubEventGoalKind5(param byte)
*handler:* `Script_VMOp_PopulateQuestRequestKind5SimpleNoAlts`

Queue-mode alias of op 516: append an active kind-5 entry {+5 = arg0, +10 host char id} to the sub-event goal queue when REG_SUBEV_NOW != 0 (max 20). Record 0 is not touched.

Args:
  0. param byte (+5)

### `op 544` — QueueSubEventGoalKind5(param byte)
*handler:* `Script_VMOp_PopulateQuestRequestKind5SimpleNoAlts`

Queue-mode alias of op 516: append an active kind-5 entry {+5 = arg0, +10 host char id} to the sub-event goal queue when REG_SUBEV_NOW != 0 (max 20). Record 0 is not touched.

Args:
  0. param byte (+5)

### `op 545` — QueueSubEventGoalKind6(param byte, count)
*handler:* `Script_VMOp_PopulateQuestRequestKind6TwoArgsNoItem`

Queue-mode alias of op 518: append an active kind-6 entry {+5 = arg0, +4 = arg1} to the sub-event goal queue when REG_SUBEV_NOW != 0.

Args:
  0. param byte (+5)
  1. count (+4)

### `op 546` — QueueSubEventCraftGoal(craft category, item id, param byte, count)
*handler:* `Script_VMOp_PopulateQuestRequestKind7CraftRecipeExpose`

Queue-mode alias of op 519: append an active kind-7 craft entry {+8 craft category = arg0, +2 item = arg1, +5 = arg2, +4 = arg3} to the sub-event goal queue when REG_SUBEV_NOW != 0. The recipe lookup still runs: ingredients go to reg1..reg6, count to reg0.

Args:
  0. craft category
  1. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  2. param byte (+5)
  3. count (+4)

### `op 547` — QueueSubEventGoalKind10((ignored) …)
*handler:* `Script_VMOp_PopulateQuestRequestKind10BackrefRandomCats`

Queue-mode alias of op 522: append an empty active kind-10 entry (only the host char id) to the sub-event goal queue when REG_SUBEV_NOW != 0. The category args are ignored and the task binding is not made.

Args:
  0. (ignored) …

### `op 549` — FinishCurrentSubEvent()
*handler:* `Script_VMOp_OnRequestBoxQuestClaimedFinalize`

End the running town sub-event (only if REG_SUBEV_NOW != 0). Set its done bit (flag 1224 + id), store the id in the 9-bit register at 0x80AB, clear REG_SUBEV_NOW and flag 334, dispatch em.bin EV_SUBEV_INIT, and clear request-array flag 0x4. Also roll flag 5785 = 1/2 and refresh NPC 1-23 schedules. Wipe the sub-event goal queue and 32 bytes after it, and clear per-NPC sub-event record bits and flags (1427+i, 863-885 blocks) for ids 1-31. Add category-5 prince points (unless save bit 0x40) and unregister the SubEvent_AdvanceNowTimer calendar callback that op 536 installed. No args.

## Scene flow / control

### `op 1` — SetSceneCtxBit3FromArg(value)
*handler:* `Script_VMOp_SetContextBit8FromArg`

Copies bit 0 of arg into bit 3 (0x8) of the scene ctx's control field at +120. `ctx[+120] = (ctx[+120] & ~8) | ((arg & 1) << 3)`. Author use unknown; likely a scene mode flag toggle.

Args:
  0. value

### `op 2` — Wait(duration)
*handler:* `Script_VMOp_WaitUnitsAndAdvanceReaction`

WAIT — pause the scene for a scripted duration. The one argument is a TIME in script units: 200 units = 1 frame, so 12000 = 1 second, 6000 = 0.5 s, 3000 = 0.25 s (the corpus's four most common values are exactly these). Any value 1..200 yields exactly one frame — `Wait(1)` is the idiomatic single-frame yield. This is the single most common pacing op (5,529 uses). Two traps, both engine-verified: the argument's expression KIND must be 0 (a computed expression — a plain literal is silently ignored, which is why the compiler always emits waits as expressions), and there must be EXACTLY one argument. IDA-verified as the wait primitive (vm[+120] = units, state -> WAITING; RF4S.exe+0x1FAB50).

Args:
  0. duration (units; 200 = 1 frame, 12000 = 1 s)

### `op 3` — WaitReset(duration)
*handler:* `Script_VMOp_EndReactionResetAndWait`

End the current quest-reaction beat and wait: signals the scene controller idle (sceneCtx+872->child[+24][+116] = 1, the same write EndDialogue does), advances the quest-reaction dispatch state (Quest_OnReactionDispatched_AdvanceState), then - if the script task is in run-state 4 - writes arg0 into the task's wait field (+120, state 4->2), i.e. the same duration mechanism as Wait. Same units as Wait (200 = 1 frame); retail passes durations like 1 (minimal yield) or 6000 (30 frames). 267 retail uses, always 1 arg.

Args:
  0. duration (units; 200 = 1 frame)

### `op 4` — WaitPlain(duration)
*handler:* `Script_VMOp_WaitPlain`

Wait like op 2 but WITHOUT advancing the quest-reaction state: a non-zero duration sets the wait counter and puts the running VM into the waiting state (Script_VMOp_WaitPlain, RF4S.exe+0x1FABC0 -- the same body as Wait minus the reaction call). Not a jump: the arg is a duration, never a code address. Same units as Wait.

Args:
  0. duration (units; 200 = 1 frame)

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

### `op 230` — SetSceneCast(mode, kept villager id …)
*handler:* `Cutscene_ReleaseNpcLocksAndRefreshFromSchedule`

Scene-cast setup. For every villager 1..23 NOT named in args 1..n and for ALL eight entries of the event participant list (the args exempt only villagers) (and not in companion/equipped mode, actor+16 bit 0x200): record +48 bits 28/29 = mode, and actor control_flags bits 0x4 (hidden) and 0x20 = mode (with mode != 0 it also clears the emote at +0x140 and sets +0x23C bit 0x20). So mode 1 HIDES everyone except the listed participants and mode 0 un-hides them. Also sets ctx+116 bit 29 = mode, calls Npc_RefreshFromSchedule for those same NPCs when their ctx+352 placement-mask bit is set (listed villagers are never refreshed), and clears that mask.

Args:
  0. mode (1 = hide non-participants, 0 = show all)
  1. kept villager id … (1-23; the event-participant list is always processed)

### `op 231` — SetSceneCast(mode, kept villager id …)
*handler:* `Cutscene_ReleaseNpcLocksAndRefreshFromSchedule`

Scene-cast setup. For every villager 1..23 NOT named in args 1..n and for ALL eight entries of the event participant list (the args exempt only villagers) (and not in companion/equipped mode, actor+16 bit 0x200): record +48 bits 28/29 = mode, and actor control_flags bits 0x4 (hidden) and 0x20 = mode (with mode != 0 it also clears the emote at +0x140 and sets +0x23C bit 0x20). So mode 1 HIDES everyone except the listed participants and mode 0 un-hides them. Also sets ctx+116 bit 29 = mode, calls Npc_RefreshFromSchedule for those same NPCs when their ctx+352 placement-mask bit is set (listed villagers are never refreshed), and clears that mask.

Args:
  0. mode (1 = hide non-participants, 0 = show all)
  1. kept villager id … (1-23; the event-participant list is always processed)

### `op 242` — SetSceneFlag0x200()
*handler:* `Script_VMOp_SetSceneFlag0x200`

If the script host has an actor (host+32), OR bit 0x200 into host+116 (the host's event-state word). No reader of this bit with a direct 0x200 test has been found in RF4S.exe, so its effect is unknown; the 'scene outcome consumed' reading is inferred from where scripts place it (just before END), not from code.

### `op 285` — SetSceneReadyFlag(mode, (ignored by handler))
*handler:* `ScriptVMOp_SetScriptStateBit72_1_OnArgZero`

Set a scene-state control bit (scene state +72 bit 0x1) when arg0 is 0 — a low-level 'wait / ready' marker the scene loop checks. arg0 = mode (0 sets it).

Args:
  0. mode (0 = set flag)
  1. (ignored by handler)

### `op 332` — WarpToMap(map id, x, y, arrival event id)
*handler:* `ScriptAction_BeginConfiguredAction_PruneUiEvents`

Request a map transition for the script host: host+60/+62/+64/+66 = map id, x, y, arrival event id; sets host+56 bit 0x80. The event id also sets host+57 bit 0 (1000-1099) or bit 1 (100-999). Clears dialogue-lock state like op 243 and, when the event id is non-zero, prunes queued events of types 20/24/28/30. NpcAi_FinalizeEventAndPostTick later consumes it: starts the scene transition to (map, x, y) and, if the event id is non-zero, sets host+56 bit 0x40 and packed flag 1018.

Args:
  0. map id
  1. x (tiles)
  2. y (tiles)
  3. arrival event id (0 = none)

### `op 333` — WarpToMapInSubEvent(map id, x, y, arrival event id)
*handler:* `ScriptAction_BeginConfiguredAction_Variant1`

Same as op 332 (map, x, y, arrival event id) but afterwards forces host+57 to bit 0 only and stores GF_REG_SUBEV_NOW (low 7 bits) into host+58.

Args:
  0. map id
  1. x (tiles)
  2. y (tiles)
  3. arrival event id (0 = none)

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

### `op 376` — BeginShopkeeperInteraction(npc id, action id, (ignored))
*handler:* `Script_VMOp_BeginCalendarContextualInteraction`

Open an NPC's shop/service interaction (action id arg1, stored at host+25) via World_DispatchInteractionEvent, after computing a per-NPC interaction kind and a weekday check: arg0 (NPC) maps to a kind override and a weekday (e.g. 8 Dylas -> kind 23 if FLG_DIRUS_FRIENDLY, 13 -> 25 if packed flag 875, 15 -> 24 if EV_DAG_SILENT, 25 -> kind 21 / sub 28, 22/23/unknown -> 26). If today's (day-1)%6 equals that weekday g_interactionDailyEligible = 1, otherwise 0 plus a deterministic ~1/63 daily roll seeded by arg1 and the calendar. Blocks until the interaction finishes. The third argument is not read.

Args:
  0. npc id
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
  1. action id (75-89 in the corpus)
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
  2. (ignored)

### `op 421` — SetNextItemAttributes(level byte, crafted bits, ingredient item ids)
*handler:* `Script_VMOp_SetupPendingInteractionRecord`

Stage attributes for the NEXT item a script creates (GivePlayerItem, SpawnItemAtTile, ForcePlayerHoldItem, the NPC hand/attach-item ops; DropItem/DropItemStack do not read it): arg0 overrides the item's level byte (+4), arg1 sets the 3-bit 'crafted' field (bits 1-3 of the flags word +2), and args 2-7 fill the six u16 ingredient/material item-id slots (+6..+17, e.g. a dish's ingredients). The record is consumed and cleared by the first such op.

Args:
  0. level byte
  1. crafted bits (0-7)
  2. ingredient item ids (up to 6)

### `op 422` — SetNextItemAttributesPacked(byte +4, byte +6, 10-bit fields…)
*handler:* `Script_VMOp_SetupPendingInteractionRecord_Variant2`

Alternate staging form (marker 2): byte+4 = arg0, byte+6 = arg1, arg2 and args 3-5 packed as 10-bit fields. No consumer applies a marker-2 record - every item op only applies marker 1 and then clears the record - so in the shipped exe this op has no lasting effect beyond discarding any staged op-421 attributes.

Args:
  0. byte +4
  1. byte +6
  2. 10-bit fields…

### `op 524` — NopCompleteSubEventGoals()
*handler:* `Script_VMOp_PromoteAllPendingThrowEntriesToActive`

No-op as opcode 524. The shared handler only acts when the current opcode is >= 537; op 548 is the working form (sets every active sub-event goal to state 2, complete).

### `op 548` — CompleteAllSubEventGoals()
*handler:* `Script_VMOp_PromoteAllPendingThrowEntriesToActive`

Set every sub-event goal-queue entry in state 1 (active) to state 2. State 2 is 'complete' for these records: op 552 then reports 0 remaining, and NpcAi_AdvanceQuestProgressAndScheduleReaction uses 2 for completed kill requests. Only this opcode does anything; op 524 (same handler) is a no-op. No args.

### `op 551` — ResetSubEventGoals()
*handler:* `Script_VMOp_ResetGeneralThrowQueue`

Clear the sub-event goal queue: entry count = 0 and all 20 x 24-byte entries zeroed. No args.

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

### `op 81` — WaitPortraitSettled(portrait character id)
*handler:* `Script_VMOp_QueryActorMotionState`

Block the script while the given speaker portrait is still animating (sliding in/out or moving: portrait state (+42 & 0x7C) != 0x10); continue once it has settled. arg0 = portrait character id; if no on-screen portrait matches, it does not block. Nothing is written to a VM register - the result is the handler's busy flag.

Args:
  0. portrait character id
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

### `op 82` — WaitPortraitSettled(portrait character id)
*handler:* `Script_VMOp_QueryActorMotionState`

Block the script while the given speaker portrait is still animating (sliding in/out or moving: portrait state (+42 & 0x7C) != 0x10); continue once it has settled. arg0 = portrait character id; if no on-screen portrait matches, it does not block. Nothing is written to a VM register - the result is the handler's busy flag.

Args:
  0. portrait character id
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

### `op 113` — WaitActorAuxYaw(actor)
*handler:* `Script_VMOp_QueryActorRotating`

Block while the actor's secondary yaw (actor+0xD6) has not reached the target set by op 111 (+0xD8); continue when equal, or at once for ids >= 48 / missing actors. Nothing is written to a VM register - the result is the handler's busy flag.

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

### `op 114` — WaitActorAuxYaw(actor)
*handler:* `Script_VMOp_QueryActorRotating`

Block while the actor's secondary yaw (actor+0xD6) has not reached the target set by op 111 (+0xD8); continue when equal, or at once for ids >= 48 / missing actors. Nothing is written to a VM register - the result is the handler's busy flag.

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

### `op 129` — QueryActorMoveBusy(actor, ignored actor …)
*handler:* `Script_VMOp_QueryNpcAnimDone`

Blocking predicate: returns 1 (op re-runs next frame) while the NPC still has an active move command (npc+20 bit 0x8, set by Npc_StartMoveTowards) or a pending turn (npc+20 bit 0x800 with actor facing +0x9C != target +0x9E); 0 when done or actor absent. Actor 0 delegates to QueryPlayerTurnBusy (player scripted-move lock 0x10000 / pending turn). It does NOT look at animation state. Only arg0 is read.

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
  1. ignored actor … (not read)

### `op 130` — QueryActorMoveBusy(actor, ignored actor …)
*handler:* `Script_VMOp_QueryNpcAnimDone`

Blocking predicate: returns 1 (op re-runs next frame) while the NPC still has an active move command (npc+20 bit 0x8, set by Npc_StartMoveTowards) or a pending turn (npc+20 bit 0x800 with actor facing +0x9C != target +0x9E); 0 when done or actor absent. Actor 0 delegates to QueryPlayerTurnBusy (player scripted-move lock 0x10000 / pending turn). It does NOT look at animation state. Only arg0 is read.

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
  1. ignored actor … (not read)

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

### `op 137` — QueryActorAnimBusy(npc)
*handler:* `ScriptVMOp_QueryNpcExistsLoadedAndNotIdle`

Blocking predicate: returns 1 (re-run next frame) while the NPC exists, has an actor, and its scene node's 'anim finished' flag (node+8 bit 0x8) is still clear, i.e. waits for the current non-looping clip to end. Returns 0 at once if the NPC or its actor is missing.

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

### `op 138` — QueryActorAnimBusy(npc)
*handler:* `ScriptVMOp_QueryNpcExistsLoadedAndNotIdle`

Blocking predicate: returns 1 (re-run next frame) while the NPC exists, has an actor, and its scene node's 'anim finished' flag (node+8 bit 0x8) is still clear, i.e. waits for the current non-looping clip to end. Returns 0 at once if the NPC or its actor is missing.

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

### `op 145` — QueryPlayerTurnBusy()
*handler:* `Script_VMOp_QueryPlayerTurnBusy`

1 while the player is still turning / settling their facing (or in a scripted-busy state); 0 when idle. No args. Wait for the player's turn to finish before the next beat.

### `op 148` — QueryPlayerFlag40000()
*handler:* `ScriptVMOp148_QueryPlayerFlag40000`

Query -> VM query register: 1 if the player has status/accessory-effect flag 0x40000, else 0.

### `op 152` — QueryPlayerAnimBusy()
*handler:* `Script_VMOp_QueryPlayerScriptReady`

Blocking predicate (player twin of op 137): returns 1 (re-run next frame) while scene ctx+116 bit 0x8000000 is clear AND the player's scene_node 'anim finished' bit 0x8 is clear, i.e. waits until the clip started by op 149 / op 133 on the player has ended. No args; writes nothing to registers.

### `op 164` — QueryEventActorMoving(event key)
*handler:* `ScriptVMOp_CalendarEvent_QueryNpcTurnOrArrivalState`

1 while a spawned event actor is still walking OR turning; 0 once it has both arrived and settled its facing. arg0 = event key. The COMBINED wait predicate — op 179 checks only turning, this also checks arrival.

Args:
  0. event key

### `op 169` — QueryEventActorAnimBusy(event key)
*handler:* `ScriptVMOp_QueryCalendarEventActorReadyOrInMidAction`

Blocking predicate: returns 1 (re-run next frame) while the keyed event actor is missing or its scene_node 'anim finished' bit (node+8 bit 0x8) is clear - i.e. waits for the one-shot clip started by op 167 to end.

Args:
  0. event key

### `op 179` — QueryEventActorTurning(event key)
*handler:* `ScriptVMOp_QueryCalendarEventActorStillTurningTowardTarget`

1 while a spawned event actor is still turning toward its target facing (target != current); 0 once settled. arg0 = event key. Wait-for-turn predicate — the event-actor twin of WaitActorAuxYaw (op 113).

Args:
  0. event key

### `op 182` — QueryEventActorTilePosition(event key)
*handler:* `ScriptVMOp_QueryCalendarEventActorWorldXY_Tiles`

Read a spawned event actor's current tile position: writes X and Y (tiles) to the VM output slots for a following read. arg0 = event key. The event-actor counterpart of QueryActorTilePosition (op 135).

Args:
  0. event key

### `op 195` — WaitCameraAtMark()
*handler:* `Script_VMOp_QueryCameraAtMarkAnchor`

BARRIER: block the scene until the CAMERA has arrived at the mark anchor set by SetCameraPosition/SetCameraTarget (ops 186/190) — per-axis |camera − anchor| <= 2048 Q12 = half a tile (Chebyshev). No args. This is what paces every scripted camera sweep: `SetCameraTarget(x, y, speed); WaitCameraAtMark()` holds until the pan lands. (The IDB comparison is against g_cameraPosQ12, the CAMERA, not the player.)

### `op 196` — QueryCameraBeyondRangeOfTarget(range)
*handler:* `Script_VMOp_QueryPlayerMovedBeyondDistFromAnchor`

Blocking predicate: 1 while the CAMERA position is more than arg tiles from its target on X or Y, 0 once within range - a range-parameterised op 195. The player position is not read.

Args:
  0. range (tiles)

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

### `op 220` — QueryAllNpcsFriendship(0, target level)
*handler:* `ScriptVMOp_QueryAllAvailableNpcsFriendshipMeetsTarget`

reg0 = 1 if every story-available villager 1..23 (mask gated by story progress 0x3C/0x63/0x8B/0xD1, the EMFE_SYELZA_READY condition, plus the current child from GameFlags) has friendship level >= arg1. arg0 must be 0: with a non-zero arg0 the handler (bug) evaluates Npc_GetFriendshipLevel(arg1) >= arg1, i.e. it looks up the NPC whose id equals the target level.

Args:
  0. 0 (non-zero is broken)
  1. target level

### `op 226` — QueryNpcScheduleId(npc)
*handler:* `Script_VMOp_QueryNpcScheduleId`

reg0 = the NPC's current schedule id (Npc_GetCurrentScheduleId), rounded down to a multiple of 4 when < 0x40. arg0 = 0 instead returns the current ROOM id (g_currentRoomId; -1 while input is suppressed or the main task's flag 2 is set).

Args:
  0. npc (char id, 0 = current room id)
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

Read 1 iff an NPC's current schedule id matches ANY id in the list. arg0 = npc (char id; 0 tests the PLAYER's scene/menu-state field, 22 the current child id). args[1..] = the schedule ids - there is NO count argument: the 'count' is the statement's own packed arg-count slot (the handler at RF4S.exe+0x1FD9F0 reads it from the encoding, confirmed 2026-09-01).

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

Read 1 iff an NPC's current schedule id matches ANY id in the list. arg0 = npc (char id; 0 tests the PLAYER's scene/menu-state field, 22 the current child id). args[1..] = the schedule ids - there is NO count argument: the 'count' is the statement's own packed arg-count slot (the handler at RF4S.exe+0x1FD9F0 reads it from the encoding, confirmed 2026-09-01).

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

reg0 = 1 if bit 0x40 of the NPC record's u16 at +20 is clear. The mechanics are certain; what bit 0x40 means (the 'available' label) is not established, and the handler has no null check on the record.

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

Query (reg0) whether an NPC is eligible for a once-per-toggle interaction with the script's own actor: NPC and the calling actor (host+32) must not be in actor state 13/25, the NPC must pass Npc_IsInCurrentArea, and it must be within 48 distance units of the calling actor. On success it TOGGLES bit 0x100000 of the CALLING actor's npc record+48 and returns 1 if that bit was clear before (0 if it was set). Equivalent to op 236 with range fixed at 48.

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

### `op 236` — QueryNpcInteractEligible(npc, range)
*handler:* `Script_VMOp_QueryNpcInteractEligible`

Same as op 235 but with an explicit range: reg0 = 1 iff the NPC and the calling actor are free (state not 13/25), the NPC exists, the NPC is within arg1 distance of the calling actor (0 = no range check), and bit 0x100000 on the calling actor's record+48 was clear before this call (the bit is toggled every successful call).

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
  1. range (distance units, 0 = unlimited)

### `op 237` — QueryNpcPairInteraction(npc A, npc B, range to the calling actor)
*handler:* `ScriptVM_Op_QueryNpcInteractionEligibilityWithSubject`

Advance and read a 2-bit hysteresis state (bits 21-22 of the calling actor's npc record+48) for two NPCs relative to the script's own actor: each NPC is 'close' if it and the calling actor are not in state 13/25 and it is within arg2 distance of the CALLING actor (arg2 = 0 treats both as close). reg0 = the next state of a fixed 0->1->2->3->0 sequence: from 0: both close -> 1, only A -> 2, only B -> 3, neither -> 0; from 1: A close -> 2, else B close -> 3, else 0; from 2: B close -> 3, else 0; from 3: always 0 (arg2 = 0 marks both as close, so the value simply cycles). A non-zero GF_REG_FESTA forces a would-be 2/3 to 0. Both NPCs must pass Npc_IsInCurrentArea (villager game-flag bit 981+id / child table), else reg0 is not written.

Args:
  0. npc A (char id)
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
  1. npc B (char id)
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
  2. range to the calling actor

### `op 240` — QueryNpcGroupPresentNearby(max distance, primary npc, other npc …)
*handler:* `Script_QueryNpcGroupPresentNearby`

Read 1 into reg0 iff a group of NPCs are all present and available (actor state != 13/25, not busy/inaccessible) and each within arg0 distance of the primary. arg0 = max distance, arg1 = primary npc (char id), remaining args = the other npc char ids -- there is NO count argument: the handler derives the group size from the statement's own arg count. The dominant 2-arg form (distance, npc) degenerates to a single-NPC 'present & available' check (self-distance 0). 5-arg form = primary + 3 others.

Args:
  0. max distance
  1. primary npc (char id)
  2. other npc …

### `op 241` — QueryNpcGroupPresentNearby(max distance, primary npc, other npc …)
*handler:* `Script_QueryNpcGroupPresentNearby`

Read 1 into reg0 iff a group of NPCs are all present and available (actor state != 13/25, not busy/inaccessible) and each within arg0 distance of the primary. arg0 = max distance, arg1 = primary npc (char id), remaining args = the other npc char ids -- there is NO count argument: the handler derives the group size from the statement's own arg count. The dominant 2-arg form (distance, npc) degenerates to a single-NPC 'present & available' check (self-distance 0). 5-arg form = primary + 3 others.

Args:
  0. max distance
  1. primary npc (char id)
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

### `op 255` — QueryActorAilmentState(target)
*handler:* `ScriptVM_Op_QueryEntityActionStatusAndEventCode`

Read an actor's status-ailment bits (actor+180, the same word op 256 sets) as two codes. reg0: 1 if bit 0x08 set, else 4 if only bit 0x10 (fatigue) is set, 2 if 0x10 plus others or any other ailment bit, 3 if no ailment and HP <= half max, else 0. reg1: 115 if bit 0x01, 116 if 0x04, 117 if 0x02, 118 if 0x20 (cold), else 0. arg0 = 0: the player; non-zero: the companion whose char id matches the current interaction NPC.

Args:
  0. target (0 = player, else the companion being talked to)

### `op 257` — QueryAllNpcsEligibleForComment(npc id …)
*handler:* `NpcAi_AllNpcsEligibleForFlavorComment`

reg0 = 1 iff EVERY listed NPC can deliver an ambient comment: exists, not busy/inaccessible, actor state not 13/25/208, per-villager gate flag (bit 862+id) clear for ids < 24, and extra gates for id 7 (GF_FLG_MARGUERITE_VOICE_OFF) and 15 (GF_FLG_DAG_SUBEV_STOP). An arg of 0 means the player's spouse (GF_REG_WIFE_ID); ids >= 0x30 are skipped. Variadic, no count arg.

Args:
  0. npc id … (0 = spouse)

### `op 258` — QueryAllNpcsEligibleForComment(npc id …)
*handler:* `NpcAi_AllNpcsEligibleForFlavorComment`

reg0 = 1 iff EVERY listed NPC can deliver an ambient comment: exists, not busy/inaccessible, actor state not 13/25/208, per-villager gate flag (bit 862+id) clear for ids < 24, and extra gates for id 7 (GF_FLG_MARGUERITE_VOICE_OFF) and 15 (GF_FLG_DAG_SUBEV_STOP). An arg of 0 means the player's spouse (GF_REG_WIFE_ID); ids >= 0x30 are skipped. Variadic, no count arg.

Args:
  0. npc id … (0 = spouse)

### `op 259` — PickRandomVillagers(count to pick, excluded npc id …)
*handler:* `ScriptVM_Op_QueryNpcRosterPresenceByList`

Pick arg0 distinct random villagers (from the 23 roster ids) and write their char ids to reg0..reg(arg0-1) (max 10). Args 1.. are char ids to EXCLUDE (built into a bitmask); the roster also drops NPCs gated by story progress, the spouse's/child state, record+52 bit 0x1000, the per-villager gate flags (862+id) and festival-day rules. If GF_REG_FESTA > 17 nothing is picked (outputs 0).

Args:
  0. count to pick (<=10 written)
  1. excluded npc id …

### `op 260` — QueryActorHpWellness()
*handler:* `ScriptVMOp_QueryActorHpLowOrUnknownForDialogueBranch`

Read the script host actor's (host+32) HP state into reg0: 2 = HP is 0, 1 = HP <= half max, 0 = otherwise. No args.

### `op 262` — QueryCurrentInteractionNpc()
*handler:* `ScriptVMOp_QueryCurrentInteractionNpcCharId`

Read the char id of the NPC the player is currently talking to / interacting with into the VM output slot (0xFFFF if none). Use to branch a shared script on which NPC triggered it.

### `op 265` — QueryPlayerOrCompanionDowned(mode)
*handler:* `Script_VMOp_QueryPlayerOrCompanionDowned`

reg0: arg0 != 0 -> 1 if the player's task tick is Player_DeathTickCallback (player down); arg0 == 0 -> 1 if either companion has stats hp_curr == 0 and actor state 11 (knocked out).

Args:
  0. mode (non-zero = player, 0 = companions)

### `op 268` — QueryNpcArrivedAtSchedule(npc id …)
*handler:* `Script_VMOp_QueryNpcArrivedAtSchedule`

reg0 = 1 iff every listed NPC has reached its scripted/scheduled spot and is available (Npc_IsAtScheduledSpotAndAvailable: record+228 bit 0 set, not busy, not festival-substituted, waypoint index at the end). Variadic, every arg is an npc id, no count. arg0 = 0 switches mode: scan villagers 1..23 with record+228 bit 0 set and return 1 iff NONE of them is in place.

Args:
  0. npc id … (arg0 = 0 = all-villager mode)
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

### `op 269` — QueryNpcArrivedAtSchedule(npc id …)
*handler:* `Script_VMOp_QueryNpcArrivedAtSchedule`

reg0 = 1 iff every listed NPC has reached its scripted/scheduled spot and is available (Npc_IsAtScheduledSpotAndAvailable: record+228 bit 0 set, not busy, not festival-substituted, waypoint index at the end). Variadic, every arg is an npc id, no count. arg0 = 0 switches mode: scan villagers 1..23 with record+228 bit 0 set and return 1 iff NONE of them is in place.

Args:
  0. npc id … (arg0 = 0 = all-villager mode)
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

### `op 276` — QueryNpcHeldItem(npc)
*handler:* `Script_VMOp_QueryNpcModelId`

reg0 = the item id the NPC is currently holding (actor+304 -> +178, valid range 1..1107), else 0.

Args:
  0. npc (char id, 1-47)
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

### `op 277` — QueryNpcHeldItem(npc)
*handler:* `Script_VMOp_QueryNpcModelId`

reg0 = the item id the NPC is currently holding (actor+304 -> +178, valid range 1..1107), else 0.

Args:
  0. npc (char id, 1-47)
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

### `op 280` — QueryNpcDateState(npc)
*handler:* `Script_VMOp_QueryNpcDateState`

Read an NPC's DATE STATE (npc record +55 & 7) into reg0 -- NOT a facing direction: 0 no date, 1 a date is promised for tomorrow, 2 the date is today, 3 on the date, 4 the date went well, 5 turned you down today (6/7 unused). arg0 = npc (char id); yields 0 if the NPC can't be resolved. Same read as Npc_GetDateState, which backs em.bin's DATE_STATE query (124) and the SUBEV_ENABLE_* gates (a sub-event may start at 0 or 5, i.e. with no date pending). Set by op 281 SetNpcDateState. Lifecycle (traced 2026-09-25): the invitation scene sets 1 when the NPC accepts ('I would love to accompany you!') or 5 when they decline ('I have work to do tomorrow'); Day_UpdateNpcDailyFlags (RF4S.exe+0x227AE0) turns 1 into 2 at the daily rollover, clears 5, and treats a 2 that is still 2 as a stood-up date (stood-up mark 1-3, back to 0, em.bin EV_DATE_FINISH); Npc_TryDateInvitation_NightFinale does the same at 18:00/22:00; the date-day talk sets 3 when the date starts; leaving the party with 3 or 4 ends the date (Companion_SyncToScene: back to 0 + EV_DATE_FINISH).

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

### `op 283` — QueryDateCompanionId()
*handler:* `Script_VMOp_QueryCompanionNpcId`

reg0 = char id of the party companion (companion slot 1 or 2, char id < 48) whose date state (npc record+52 bits 24-26, the op 280/281 field) is non-zero, else 0. A companion with no date state is not returned.

### `op 288` — QueryNpcOutfit(npc)
*handler:* `ScriptVMOp_QueryNpcActorWordField488`

reg0 = the NPC's current outfit variant (actor+488: 0 default, 1 pajamas, 2 swimsuit, 3 ...), 0 if unresolvable.

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

### `op 338` — QueryNpcOnPlayerMap(npc)
*handler:* `Script_VMOp_GetNpcScheduleMatchAndId`

reg0 = 1 iff the NPC's current map (Npc_GetCurrentScheduleId: actor+84, or record+188 when not spawned) equals the player's current map (player actor+84); reg1 = the NPC's map id, plus the season index for outdoor maps < 0x40. arg0 = 0 means the spouse (GF_REG_WIFE_ID).

Args:
  0. npc (char id, 0 = spouse)

### `op 339` — GetNpcCurrentMap(npc)
*handler:* `Script_VMOp_GetNpcCurrentScheduleId`

reg0 = the NPC's current map id (actor+84, or record+188 when not spawned, 0xFFFFFFFF if unresolvable), plus the season index for outdoor maps < 0x40.

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

### `op 362` — GetFestivalDate(bank-9 slot, festival id)
*handler:* `Script_VMOp_GetNpcBirthdayMonthAndDay`

Look up festival #arg1 in the calendar table (archive 16340, rf3TxtCalendar_split2_1.bin: 4-byte records {npc, season, day, festival}) by the FESTIVAL byte (record byte 3). reg0 = season (0-3), reg1 = day, and bank-9 var [arg0] = day + 100*season. If not found the outputs are uninitialised stack bytes.

Args:
  0. bank-9 slot (0-15)
  1. festival id

### `op 363` — GetNpcBirthday(var slot, npc id)
*handler:* `Script_VMOp_GetCalendarEventMonthWithFallback`

Get character #arg1's birthday: arg1 != 0 looks up the calendar table (archive 16340) by the NPC byte (record byte 0); arg1 = 0 reads the player's birthday from GameFlags REG_PLAYER_BIRTH_SEASON/DAY. reg0 = season (0-3), reg1 = day; bank-0 var [arg0] = season + 616 (a text-substitution id for the season name) and bank-3 var [arg0] = day.

Args:
  0. var slot (bank 0 index 0-15, bank 3 index 0-51)
  1. npc id (0 = player)

### `op 367` — GetVar14(index)
*handler:* `Script_VMOp_ReadVarArrayKind14`

Read global script-variable bank 14 at [index] into reg0 -- the paired reader for SetVar14. Engine-global state (kinds 0-3 in the game-globals slot table, the rest in dedicated arrays), shared with the choice-commit system, so it can read back a value that an earlier scene or a committed choice stored. IDA-verified: Script_VMOp_ReadVarArrayKind14.

Args:
  0. index

### `op 369` — TryMountPlayerOnHostActor((ignored))
*handler:* `Script_VMOp_QueryPlayerCanInteractWithActor`

Try to mount the player on the script's host actor (host+32, e.g. a farm monster). reg1 = 0 if the player is mid-action (render_state_flags & 0x1E) else 1; reg0 = 0 when mid-action, 2 when the player already has status 0x4000 (mounted/carrying), otherwise the result of Player_BeginMountTransitionAndInstallTickAndAnchor - which actually starts the mount. Takes no script args (the corpus passes one ignored literal).

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

### `op 377` — ConsumeInteractionResult()
*handler:* `Script_VMOp_ConsumeChoiceCommitResult`

If host+116 bit 24 (interaction result pending) is set, reg0 = (host+116 >> 22) & 3 and bit 24 is cleared; otherwise reg0 is untouched. The pending bit is set by World_DispatchInteractionEvent for action ids 3, 43 and 44 (which also set host+164 = 1/2/3 and clear bits 22-23) and cleared at the start of every other world interaction.

### `op 378` — ConsumeInteractionResult()
*handler:* `Script_VMOp_ConsumeChoiceCommitResult`

If host+116 bit 24 (interaction result pending) is set, reg0 = (host+116 >> 22) & 3 and bit 24 is cleared; otherwise reg0 is untouched. The pending bit is set by World_DispatchInteractionEvent for action ids 3, 43 and 44 (which also set host+164 = 1/2/3 and clear bits 22-23) and cleared at the start of every other world interaction.

### `op 398` — BuildOutfitChoiceMask(invert)
*handler:* `Script_VMOp_QueryUnlockedAlternatePoseMask`

Build the choice-visibility mask (host+244) for an outfit menu: bit 0 = player is not in the normal outfit, bit i (1-15) = fashion flag 728+i (GF_FLG_FASHION_PAJAMA .. _COLOR07) unlocked and not the outfit currently worn. arg0 != 0 inverts the mask; a non-zero mask gets bit 0x10000; bit 4 (bath) is always cleared. reg0 = mask != 0.

Args:
  0. invert (0/1)

### `op 399` — GetPlayerSubstate()
*handler:* `Script_VMOp_GetPlayerSubstateId`

Read the player's substate id.

### `op 403` — GetFreeFarmAreas()
*handler:* `Script_VMOp_QueryMonsterRosterAbsentMask`

For farm areas 1-3 of the farm the player is on (current room mapped to its farm-field id), reg0/reg1/reg2 = 1 if no worker monster is assigned to that area, else 0. No args.

### `op 404` — GetOccupiedFarmAreas(farm field / room id)
*handler:* `Script_VMOp_QueryMonsterRosterPresentMaskByCtx`

For farm areas 1-3 of the farm field given by arg0, reg0/reg1/reg2 = 1 if a worker monster is assigned to that area. arg0 is a room/field id: 4-23 used directly, barn rooms 77-126 map to field 4 + 4*((room-77)/10), anything else to 4; a negative value means the current room.

Args:
  0. farm field / room id (-1 = current)

### `op 406` — GetFarmMonsterPlantOrder()
*handler:* `Script_VMOp_GetMonsterFarmLovedTodayBit`

reg0 = bit 18 (the 'also plant seeds' work order) of the g_MonsterFarmTable record whose worker task is this script's host subject (host+32); 0 if the subject is not a barn monster. No args. Counterpart of op 405.

### `op 407` — QueryActiveKillCount()
*handler:* `Script_VMOp_QueryActiveKillCount`

Read the count of monsters still alive in the active kill-aggregate list into the VM output — how many enemies are still standing. No args. For boss/battle scenes gating on 'defeat all the monsters' progress.

### `op 408` — CountLivingEnemies()
*handler:* `Script_VMOp_QueryKillAggregateActiveCountExclBoss`

Count the living monsters on the field EXCLUDING the two boss char ids (141/142) into the VM output. The 'kill all the trash before the boss appears' gate.

### `op 409` — CountTamedFarmMonsters()
*handler:* `Script_VMOp_CountTamedMonstersWithFlag1000`

Count the occupied slots of the 200-entry monster table (record flag 0x1000 = slot holds a tamed monster), i.e. how many monsters the player owns; cache it at g_farmMonsterMng+250 and return it in reg0.

### `op 411` — QueryCompanionMonsterData(companion slot / farm record index, query kind)
*handler:* `Script_QueryCompanionMonsterData`

Multi-purpose monster query, arg1 = kind. Kinds 0-4 read party slot arg0 (0 = companion 1, 1 = companion 2) stats: 0 = 4 dwords (+60/+68/+72/+76) into reg0-3, 1 and 2 = eight s16 stat blocks (+136.., +152..), 3 = eight dwords (+100..), 4 = monster fields plus reg6 = level and reg7 = affinity of its farm record. 5 = for farm areas 1-3 on this farm, reg0-2 = the working monster's record index (0xFFFF if none). 6 = plant-seeds order bit of record arg0. 7 = barn workload count (ceil(owned/4) + owned monsters with order bits 0x40000/0x20000 + owned monsters working an area). 8 = for this script's monster: reg0 = state (1 working an area, 2 flag 0x100, 3 out in the roster, 0 otherwise), reg1 = affinity, reg2 = 1, reg3 = area. 9 = this script's monster: reg0 = level, reg1 = affinity. 10 = record arg0: reg0 = level, reg1 = affinity.

Args:
  0. companion slot / farm record index
  1. query kind (0-10)

### `op 414` — GetChoiceIndexAndItem()
*handler:* `Script_VMOp_GetScriptChoiceIndexAndItemId`

Read the last scripted item-selection result into TWO VM outputs: query register 0 = the choice slot index (0-7, extracted from scene-ctx +116 bits 6-8), register 1 = the associated item id (11-bit, from ctx+40 field +380). DISTINCT from ConsumeInteractionResult (ops 377/378) -- eResult (op 377/378 = Script_VMOp_ConsumeChoiceCommitResult, a different handler) -- this one (Script_VMOp_GetScriptChoiceIndexAndItemId) returns the index+item pair for an item-pick menu, not the committed PROMPT_CHOICE value.

### `op 416` — QueryPlayerVariable(variable code, skill id)
*handler:* `Script_VMOp_QueryPlayerStatByCharCode`

reg0 = a player value selected by an ASCII code: 'd'(100) gold, 'f'(102) player level (base_stats.level + 1), 'g'(103) fodder in the barn bin (g_farmMonsterMng+252), 'h'(104) level of skill arg1, 'i'(105) stone, 'j'(106) compost, 'k'(107) highest level among the 40 skills; any other code 0-39 = that skill's level. Other codes leave reg0 = 0.

Args:
  0. variable code
     - `100` = Gold
     - `102` = ArmorDef
     - `103` = FarmTameCount
     - `104` = Skill
     - `105` = Stone
     - `106` = Compost
     - `107` = MaxSkillLevel
  1. skill id (only for 'h')
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

### `op 418` — QueryBackpackHasRoom()
*handler:* `Script_VMOp_QueryBackpackHasOccupiedSlot`

reg0 = 1 if the backpack has at least one EMPTY slot within its current capacity (15/30/45/60 from Inventory_GetPageSlotCount), else 0. No args.

### `op 419` — QueryBackpackHasFreeSlot()
*handler:* `Script_VMOp_QueryBackpackOrEquipFirstFreeSlot`

Write 1 to the VM output if the backpack has any free slot, else 0 — a BOOLEAN, not a slot index. Walks the first 60 backpack slots looking for an empty/placeholder entry (slot kind < 0x800 or item id 0); if all are full it falls back to checking the special equip-extras slot (g_itemDatabase.ptr_00[+24]). No args. Used before placing an item.

### `op 420` — QueryBackpackFreeSlots(min free slots)
*handler:* `Script_VMOp_QueryBackpackFreeSlotCountGTE`

Read 1 iff the player's backpack has at least [N] free slots into the VM output — the 'do you have room for N more items?' check before granting items. arg0 = N.

Args:
  0. min free slots

### `op 426` — IsPlayerHoldingItem()
*handler:* `Script_VMOp_QueryEquipExtrasSlot24Occupied`

reg0 = 1 if the player's carried-item slot (record 0 of the equipment block, g_itemDatabase->ptr_00 + 24) holds an item. No args.

### `op 431` — HasItem(item id, min count, min quality)
*handler:* `Script_VMOp_QueryItemAvailableInBackpackOrEquipExtras`

reg0 = 1 if the backpack (60 slots), the carried item or equipment record 1 holds item arg0 with count >= arg1 and level byte + 1 >= arg2 (0 or -1 = any level). reg2 (not reg1) = bit 0 of the matched slot's flags byte (+2).

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. min count
  2. min quality (<= 0 = any)

### `op 432` — CheckCropPlantable(seed item id)
*handler:* `Script_VMOp_QueryCropPlantableAndTileInfo`

Look up seed item arg0's crop row (item metadata data_10 -> rf3CropParam row, 108 bytes) - no tile is inspected. reg0 = 1 if the current season's bit is set in the row's season mask (high nibble of the word at +104), or if arg0 == 39 and it is spring; reg1 = sum of the row's first four bytes (the growth-stage lengths); reg2 = item metadata byte +4 (category); reg3 = item metadata flag (data_10+4 bit 3).

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

### `op 437` — IsItemInCategoryList(item id, category list)
*handler:* `Script_VMOp_QueryItemInNpcOfferListArchive14850`

reg0 = 1 if item arg0 appears in item-category list (arg1 - 0x8100) of rf3PresentCategory.bin (archive 14850, 21 lists of item ids). The list index is computed as u16(arg1 + 0x7F00), so scripts pass 0x8100 + list index (33024 + k).

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. category list (0x8100 + index)

### `op 438` — QueryHasItemOfCategory(category id)
*handler:* `Script_VMOp_QueryBackpackOrEquipHasItemOfCategory`

Read 1 iff the player holds any item of a given CATEGORY (weapon class, food, seed, etc — the item-metadata category byte) into the VM output. arg0 = category id. For 'do you have any [type]?' dialogue gates.

Args:
  0. category id

### `op 440` — GetNpcSpecies(char id)
*handler:* `Script_VMOp_QueryNpcParamSpeciesByCharId`

reg0 = the signed 16-bit field at +292 of rf3NpcParam record arg0 (archive 14812, 308-byte records). The field is 0 for all 48 villager records and 161-726 for monster records, shared by colour variants.

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

### `op 456` — QueryEquippedItemAttr(equip selector, attribute)
*handler:* `Script_VMOp_QueryEquippedItemAttrByEquipSlot`

reg0 = item id of the player's equipment record picked by arg0 (0 -> record 1 weapon/tool, 1 -> record 2 shield, 2 -> record 4, 3 -> record 5, 4 -> record 6 boots, 5 -> record 3), reg1 = attribute arg1: 0-8 = the nine 10-bit enchantment ids (Item_GetEnchantmentSlotId), 9 = Item_AggregateUpgradeAttrA, 10 = Item_AggregateUpgradeAttrB, 11 = Item_GetUpgradeBoundItemId, 12 = payload byte +6, 13 = bits 10-19 of dword +8, 14 = bits 0-9 of dword +8; other values leave reg1 unchanged. A selector outside 0-5 dereferences null.

Args:
  0. equip selector (0-5)
  1. attribute (0-14)

### `op 470` — GetGuestNpcVariant(npc)
*handler:* `Script_VMOp_QueryChildFriendshipByteAt1`

Return byte +1 of the per-NPC record for char ids 24-47 (g_ChildFriendshipTable, 8 bytes per id) in reg0. That byte is not friendship: Town_BuildDailyGuestNpcRoster writes 4/5/6 for ids 24/25/26 and a random appearance/variant value for guest ids 27-47, and Dialogue_ProcessLineDirective passes it to Dialogue_LoadEventLineWithPortrait as the guest's variant. Out-of-range id reads through a null pointer (no guard).

Args:
  0. npc (char id 24-47)

### `op 471` — GetChildFriendPoints(npc)
*handler:* `Script_VMOp_QueryChildFriendshipWordAt4`

Return the raw friendship word (+4) of the record for char id 24-47 in reg0 (0 if out of range). The value is level*4 + a 2-bit progress count: Npc_GetFriendshipLevel returns word>>2 (cap 10000) and Npc_GetFriendshipLevelBase returns word&3 for these ids.

Args:
  0. npc (char id 24-47)

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

Read a party member's identity field (task +8) by slot into the VM output: arg0 = 0 for companion 1, 1 for companion 2. Returns 0 if that slot is empty. Used to branch dialogue on who is currently in the party.

Args:
  0. slot (0=companion 1, 1=companion 2)

### `op 487` — QueryCurrentNpcInParty()
*handler:* `Script_VMOp_QueryCurrentInteractionNpcInActiveParty`

Read 1 iff the NPC the player is currently talking to is in the active party (one of the two companion slots). No args. Branch on 'is this NPC traveling with me'.

### `op 490` — QueryDatePartnerAtDateSpot()
*handler:* `Script_VMOp_QueryMarriagePartnerInPartyAndUnlockAch771`

reg0 = 1 if your date is here: a companion (or, when companion slot 0 is empty, the script host's actor) with char id < 24, NPC date state 3 (record +52 bits 24-26 == 3, on a date), standing on the map stored in GameFlag REG_DATE_MAP. If that NPC was found through a companion slot, it also writes packed flag / achievement 771. Returns 0 when FLG_NEXT_IS_MAPJUMP_EVENT is set. No args.

### `op 493` — GetNpcFacingMode()
*handler:* `Script_VMOp_QueryNpcScriptedFacingModeBits`

Read the CURRENT scene NPC's scripted-facing mode bits (low 2 bits of the facing-mode word at scene_npc+304 -> +450) into the VM output. Takes NO arguments — it always targets the scene's own NPC record (sceneCtx+32), writing 0 if there is none. Counterpart of the mode setter (op 492 family).

### `op 502` — WaitCompanionSettled(slot)
*handler:* `Script_VMOp_QueryAnyCompanionStillTransitioning`

Blocking wait: while the selected companion(s) are still moving (record +20 bit 0x8) or still turning (record +20 bit 0x800 with actor +158 != +156), the handler returns 1, so the op re-runs next tick. Otherwise it returns 0 and the script continues. Writes no register.

Args:
  0. slot (0/1, 2 = both)
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

### `op 552` — GetSubEventGoalRemaining(item id)
*handler:* `Script_VMOp_QueryGeneralThrowQueueRemainingByItemId`

reg0 = max(0, count - progress) of the first sub-event goal-queue entry whose target item equals arg0 (0 if that entry's state is 2 or none matches).

Args:
  0. item id
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 561` — GetSceneStateBytes()
*handler:* `Script_VMOp_QuerySceneEntityBytesArray4`

Read the current scene's four state-machine bytes (scene+540..+543) into the first four VM outputs. Scene-local status bytes a scene script can inspect (byte +541 is the SetSceneScratch byte).

### `op 567` — GetTomorrowsCalendarEvent()
*handler:* `Script_VMOp_QueryTomorrowBirthdayNpcIfNotMet`

reg0 = the calendar event id scheduled for tomorrow, if that event is enabled (bit id set in the calendar-event enable bitmap, dword g_effectAppliedBits+4); else 0. The date is taken as tomorrow only when the hour is 6-23 (before 6:00 it uses today's date). The id comes from the 4-byte records of archive 16340 (season, day -> event id).

### `op 568` — GetSceneNpc(index)
*handler:* `Script_VMOp_QuerySceneNpcByIndexAndDirtyBit`

Read a scene NPC's char id into the main VM output — arg0 <= 0 selects the scene's primary NPC, arg0 1-7 selects the scene family/participant NPC list. The second output gets the scene's 'refresh queued' dirty bit.

Args:
  0. index (<=0 = primary, 1-7 = family)

### `op 569` — RankFestivalContestants(player score part A, player score part B)
*handler:* `Script_VMOp_QueryTopRankedNpcsFromRoster`

Rank three roster NPCs plus the player for the active festival (REG_FESTA). Scene_BuildNpcRoster picks 3 NPCs and Festival_RollContestCompetitorScores rolls each one's two score parts. The player is the 4th entry (id 0), scored with arg0/arg1. The entries are sorted by the sum of the parts (ties nudged down by 1), and the top three (id, part A, part B) go to reg0..reg8.

Args:
  0. player score part A
  1. player score part B

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

### `op 577` — GetFestivalResults()
*handler:* `Script_VMOp_QueryCalendarEventParticipantsAndScoreFromArchive16340`

For places 1-4 of the current scene event (u16 ids at scene+376, values at scene+384): reg(2i+1) = id, reg(2i+2) = value. When the id is 0 (the player) and scene+533 bit 0x8 is clear, it broadcasts the player's placement i+1 to the NPCs (Memory_BroadcastEventToNpcsAndApplyPlayerEffect(event, i+1)). reg0 = the event's calendar date (season*100 + day) from archive 16340. There is no computed score.

### `op 579` — GetSceneEventFlags()
*handler:* `Script_VMOp_QuerySceneEventFlagsTriplet`

Read the scene's event-state triplet into three VM outputs: a word at scene+546, a byte at scene+543, and a word at scene+548. Scene-event bookkeeping fields.

### `op 580` — GetGivenItemStats()
*handler:* `Script_VMOp_QueryHeldItemEffectiveStatsOrCraftRecord`

Read stats of the item slot stored at g_currentSceneContext+356, which is the item last thrown or handed to an NPC (written by Throw_DispatchToNpcWithQuestGiftCheck), not the item in the player's hand. For ids 132-317 (equipment), Item_ComputeEffectiveStats gives: reg0 = slot flag bit 0, reg1 = u16 slot+18, reg2 = (slot+2 >> 1) & 7, reg3/reg4 = two stat percentages clamped to +/-100. For other items: reg0 = flag bit 0, reg1 = (dword slot+8 >> 10) & 0x3FF, reg2 = u8 slot+6, reg3 = the craft record's level byte (>99 -> 1). reg5 = item id in both cases.

### `op 581` — CheckFishRecord(fish size rank)
*handler:* `Script_VMOp_QueryAndUpdateFishCaughtMaxRank`

Compare arg0 with the saved fish record (high dword of g_fishCaughtBitfield). If arg0 is larger, store it and set reg0 = 0 (new record). Otherwise reg0 = 1 on a tie and 2 if smaller. reg1 = the previous record.

Args:
  0. fish size rank

### `op 582` — GetFishRecord()
*handler:* `Script_VMOp_QueryFishCaughtMaxRank`

Read the saved 'largest fish caught' size rank into the VM output. Read-only counterpart to CheckFishRecord (op 581).

### `op 588` — IsFurniturePlaced(furniture/tile-object id)
*handler:* `Script_VMOp_QueryTileObjectActiveByItemId`

Query whether a furniture tile object with id [arg0] is active anywhere, in any room (it scans all 64 registry slots). reg0 = 1 if found, else 0.

Args:
  0. furniture/tile-object id

### `op 592` — CanPlaceFurnitureInRoom(room id)
*handler:* `Script_VMOp_QueryTileObjectFreeOrFew`

Query whether room [arg0] can take another furniture tile object: reg0 = 1 when fewer than 16 are active in that room. arg0 = 0 means the current room.

Args:
  0. room id (0 = current room)

### `op 618` — WaitStaffCreditsDone()
*handler:* `Script_VMOp_QueryActiveItemPickupIcon`

Block while the staff-credits task (from op 617) is running: the handler returns 1 while the task's tick is one of the two credits ticks, so the VM re-runs the op every step; it returns 0 (continues) once the task is gone. reg0 is not written. No args.

### `op 619` — QueryNpcAcceptsPartyInvite()
*handler:* `Script_VMOp_QueryAndCacheNpcAdmireResponse`

Decide whether the current interaction NPC agrees to go out with the player (party invite). reg0 = 1 accept, 0 decline. Declines if: (char < 24) their flag 1451+id is set, or they are tied up in the reserved sub-event; (char 24/25) g_saveConfigFlags bit 6 is set; friendship level < 7 and the hour is outside 6..17; Ventuswill (char 21) before story progress 0x1FF; Doug (char 15) before 0x1A4. Otherwise the answer is cached for the day in npc_record+48 bits 26-27: roll accept with (95 + level/2)% if friendship >= 3, never below 3; Forte (4) always accepts.

### `op 622` — QueryDifficulty()
*handler:* `Script_VMOp_QueryDifficultyMode`

Read the current difficulty into the VM output (counterpart of op 621): 0 = Easy, 1 = Normal, 2 = Hard or Hell (indistinguishable at the engine level). No args.

### `op 626` — GetMazeStageClearedBit(maze stage bit)
*handler:* `Script_VMOp_QueryPlayerInventoryFlagBit`

reg0 = bit [arg0] of g_playerInventoryFlags_word. Bits 0-5 are the Sharance Maze stages cleared (0 Garden of Light ... 5 Banquet of Nightmares): the maze menu shows stage i+1 only if bit i is set, and bit 5 gates the 'You completed the Banquet of Nightmares' trophy text.

Args:
  0. maze stage bit (0-5)

### `op 635` — GetActionTriggerByte(index)
*handler:* `Script_VMOp_QueryActionTriggerByteByIdx`

Read action-trigger byte [arg0] (index clamped 0-2, from the scene's 3-byte trigger array) into the VM output. The read counterpart of SetActionTriggerByte (op 634).

Args:
  0. index (0-2)

### `op 638` — GetHarvestReport()
*handler:* `Script_Query_DailyForecasts`

Fill reg0..reg3 with the item ids of the weekly harvest report: reg0 = this week's bumper crop, reg1 = this week's poor crop, reg2/reg3 = next week's bumper/poor crop (the calendar advanced 6 days). Each value is the u16 at +96 of crop-kind record 38..78 in the current map's tile/crop table, chosen by the date-seeded daily RNG. No args.

### `op 644` — GetPrinceOrderState(order id, sub-index / bit)
*handler:* `Script_QueryEffectStateById`

reg0 = the state of Prince Point order [arg0]: for ids 0-2 and 29, bit [arg1] of the applied-order bitsets; for shop/license orders (10-28), the unlock bit (12 returns the 2-bit Cooking Bread tier); for storage orders (31+), the current upgrade level read from GameFlags.

Args:
  0. order id
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
  1. sub-index / bit (usually 0)

### `op 646` — GetPrinceRank()
*handler:* `Script_QueryPrinceRank`

Read the current prince rank into reg1 (NOT reg0; this handler writes vm+68). No args.

### `op 647` — GetPrinceOrderCost(order id, currency)
*handler:* `Script_QueryEffectCostForCurrency`

reg0 = the cost of Prince Point order [arg0]. arg1 is the currency (0 PP, 1 lumber, 2 material stone, 3 gold) for the multi-currency orders (storage 31-38, room/farm expansion 39/40, barns 41-50). For orders with sub-variants it is the sub-index instead: order 0 = festival id (g_ppOrderFestivalCostBySub), order 29 = airship sub (0/1).

Args:
  0. order id
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
  1. currency (0 PP/1 lumber/2 stone/3 gold) or sub-index

### `op 648` — GetShippingCompletionPercent()
*handler:* `Script_QueryTownDevelopmentPercent`

reg0 = shipping-list completion percent: the number of distinct shippable items ever shipped divided by the number of distinct shippable items, times 100, truncated and clamped to 100. Uses the ALL category (index 0) of the sale-records cache. No args.

### `op 649` — QueryShippingBoxGold()
*handler:* `Script_VMOp_QueryShippingBoxTotalGold`

Read the total gold value of everything currently in the shipping box into the VM output (capped at 999,999,999). No args. For shipping-total dialogue.

### `op 650` — GetLifetimeShippedGold()
*handler:* `Script_VMOp_QueryLifetimeShippedGoldCategory0`

reg0 = total gold earned from shipping over the whole save, all categories (sale-records category 0 = the ALL aggregate), capped at 2,000,000,000. No args.

### `op 652` — GetPreviousMapId()
*handler:* `Script_VMOp_QuerySceneA1Word348`

reg0 = scene-context word +348, which Npc_OnTalkAction_QueueDialogueCascade sets to the previous g_lastInteractionActionId (the value it also writes to REG_PREV_MAPID) on each scene transition, i.e. the map the player came from. No args.

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

### `op 676` — GetMedalGoldRate()
*handler:* `Script_VMOp_QueryConst20`

reg0 = 20, the Rune Medal -> gold exchange rate that op 675 applies. The shipped use shows it in the exchange dialogue next to the medal count. No args.

### `op 684` — IsProjectorSceneUnlocked(scene index)
*handler:* `Script_VMOp_QuerySaveConfigFlagBitByIdx`

reg0 = unlock bit [arg0] of the system-save scene-memory bitset: bits 0-26 from g_sys_scriptFlagBits0_26, bits 27-58 from g_sys_scriptFlagBits27_58 (bit arg0-27). Used by the Projector memory-playback menu to show which scenes ('Opening', 'Opening 2', 'Enter Vishnal', ...) can be replayed.

Args:
  0. scene index (0-58)

### `op 686` — GetFreeLookCameraMode()
*handler:* `Script_VMOp_QueryGlobalDword302E4`

reg0 = the free-look camera control word (see op 685); ActionTask_TickFreeLookCamera resets it to 0 when the camera exits, so scripts can poll for that. No args.

### `op 690` — GetNpcGivenHat(npc char id)
*handler:* `Script_VMOp_QueryNpcRecordDword252AndItemId676`

For NPC [arg0]: reg0 = npc_record+252 dword (nonzero while the NPC has / wears a headgear the player gave them), reg1 = that headgear's item id = 676 + npc_record+256 byte (0 if none; 677+ = Silver Hairpin, Gold Hairpin, Fancy Hat, ...). arg0 = 0 gives 0/0.

Args:
  0. npc char id
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

### `op 695` — QuerySpouseClearedBit(spouse char id)
*handler:* `Script_VMOp_QueryMonsterDexBitByMonsterId`

Intended: reg0 = bit [arg0] of g_sys_spouseClearedBits (rf4_sys.sav; set by op 620). Actual code (bug): reg0 = g_sys_spouseClearedBits & ((1 << arg0) != 0) = g_sys_spouseClearedBits & 1, so it reads only bit 0 whatever arg0 is (practically always 0).

Args:
  0. spouse char id (ignored, see bug)

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

Multiply ALL the statement's args together, cap the product at 999,999,999, and write it to reg0. Deterministic - no RNG (the old 'Roll' name was wrong). There is NO separate count argument: the count is the statement's own packed arg-count slot, every script arg is a factor, and an EMPTY call yields 0, not 1 (RF4S.exe+0x21FC40; confirmed 2026-09-01).

Args:
  0. factors (variadic; every arg is one factor)

## No-op (PC-port stub)

### `op 0` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 76` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 272` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 381` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 388` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 391` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 491` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 505` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 526` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 533` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 550` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 565` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 583` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 584` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 585` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 586` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 608` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 630` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 636` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

### `op 693` — nop()
*handler:* `BusInstance_SoLoud__vslot_002`

No-op: the dispatch slot is the shared do-nothing stub (RF4S.exe+0x193B0, returns 0), so the VM decodes any args and ignores them. Harmless to keep or delete; shipped scenes still emit ops 381, 388 and 693, the other slots are unused.

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

Unconditional jump.

### `0xFFF9` — BR_NZ

Branch if the guard expression is non-zero (true).

### `0xFFF8` — BR_Z

Branch if the guard expression is 0 (false).

### `0xFFF7` — SWITCH_EQ

Indexed jump table: evaluate the selector expression, then jump to targets[value] when 0 <= value < N -- a DENSE 0..N-1 index, not a set of per-case compare values. The comparison is UNSIGNED, so a negative selector (like reg0 = -1 after a cancelled prompt) falls through to the next statement, same as any >= N value. The canonical use is dispatching a choice result: `SWITCH_EQ (reg0)` after a staged PROMPT_CHOICE jumps to the picked option's branch. Layout: [op][selector-expr][N][N u16 targets]. IDA-verified (Script_VMStep case 0xFFF7, RF4S.exe+0x23EF60).

### `0xFFF6` — SWITCH_GE

Indexed jump table, always-branch variant of SWITCH_EQ: jump to targets[value] when value < N, and CLAMP an out-of-range value (>= N, including negatives -- the compare is unsigned) to the last target (targets[N-1]) rather than falling through -- so it never falls through. Same [op][selector-expr][N][N u16 targets] layout as SWITCH_EQ. Used exactly once in the whole game. IDA-verified (Script_VMStep case 0xFFF6).

### `0xFFF5` — PROMPT_CHOICE_FORCED

Present a choice menu with NO cancel key -- one of the N options must be picked (the cancel key does nothing). Same UI as PROMPT_CHOICE: each option is a full u32 rf3mc.<locale> text id (no flag bits; an id past the archive shows entry 0), 4 rows on screen with a wrap-around scrolling list, at most 128 options (the rest are silently dropped); option text goes through the normal ＠ substitution pass. Branches to targets[picked VISIBLE ROW]. reg0 is written ONLY when a visibility mask is set (ops 610/611/612): then only flagged options appear, reg0 = the picked option's ORIGINAL index, the mask is cleared, and the shipped idiom is all targets -> one label + SWITCH_EQ on reg0. A mask whose set bits all lie past option N-1 opens an EMPTY menu that crashes on confirm (divide by zero); an all-zero mask shows every option. An unmasked prompt leaves reg0 UNTOUCHED -- shipped scenes carry a GetPlayerPosition result in reg0/reg1 across a Yes/No prompt (the deck-fight chase). CalcChoicePrescroll (613) sets the initially highlighted row. Layout: [op][N][N u16 targets][N u32 items]; size 6N+4. IDA-verified 2026-09-24 (Script_VMStep case 0xFFF5, SceneEvent_FinalizeAndPickFromBitmap, ChoiceDialog_TickStateMachine).

### `0xFFF4` — PROMPT_CHOICE

Present a choice menu whose cancel key jumps the cursor to the LAST option (and picks it when already there) -- so make the last option the 'never mind' one. The picked row's target is taken as for PROMPT_CHOICE_FORCED (same UI, 128-option cap, 4 visible rows, visibility-mask and reg0 rules). The CANCEL slot (target[0]) is only used for a NEGATIVE pick, which the menu never produces: 890 of the 891 shipped menus just repeat the last option's target there. Layout: [op][N][cancel u16][N u16 targets][N u32 items]; size = 6N+6. IDA-verified 2026-09-24 (Script_VMStep case 0xFFF4, ChoiceDialog_ConfirmViaScrollArrow, SceneEvent_FinalizeAndPickFromBitmap).

### `0xFFF3` — JMP_IND

Uniform-random jump: pick one of the N targets at random (each 1/N) and jump to it -- the UNWEIGHTED sibling of RAND_BR. Takes no operand (the target table is the only data); the pick is an RNG roll in [0, N) via the same VM RNG (reader-vtable +56) that RAND_BR rolls its weighted pick with. Layout: [op][N][N u16 targets]. IDA-verified (Script_VMStep case 0xFFF3).

### `0xFFF2` — RAND_BR

Weighted-random branch: pick one of N targets at random, each weighted by an expression. Every case's weight is evaluated fresh (so a weight can depend on game state), the weights are summed, then an RNG roll in [0, total) selects a target -- case i fires with probability weight[i] / sum(weights) (weight 0 = never taken). The editable literals on this op ARE those per-target weights, so raising one tilts the odds toward its branch. Layout: [op][N][N u16 targets][N u16 weight-exprs]; size 4N+4. IDA-verified (Script_VMStep case 0xFFF2 -> Script_Opcode_FFF2_ExecPrim, RF4S.exe+0x23EC40).

### `0xFFF1` — FRAME

Frame setup (it does NOT return): sets the frame base to the current operand-stack top and reserves [local slots] entries for locals (always even -- the stack holds value/kind pairs, 2 per local), then execution FALLS THROUGH to the next statement. Typically the first statement of a CALLed subroutine; the matching return is RET (0xFFFF). IDA-verified: Script_VMStep case 0xFFF1, corrected 2026-08-06.

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

368, 702, 703, 704, 705, 706, 707, 708, 709, 710, 711, 712, 713, 714, 715, 716, 717, 718, 719, 720, 721, 722, 723, 724, 725, 726, 727, 728, 729, 730, 731, 732, 733, 734, 735, 736, 737

## Opcode index (by number)

Every named action opcode by number (reserved slots omitted; see above).

| op | mnemonic | op | mnemonic | op | mnemonic |
|---:|:--|---:|:--|---:|:--|
| 0 | `nop` | 1 | `SetSceneCtxBit3FromArg` | 2 | `Wait` |
| 3 | `WaitReset` | 4 | `WaitPlain` | 5 | `ShowPortrait` |
| 6 | `ShowPortraitWithEmote` | 7 | `ShowPortraitWithEmote` | 8 | `SetSpeakerName` |
| 9 | `SetSpeakerName` | 10 | `SetSpeakerVoice` | 11 | `SetSpeakerNameVisible` |
| 12 | `SetSpeakerById` | 13 | `SetSpeakerById` | 14 | `SetSpeakerByIdWithEmote` |
| 15 | `SetSpeakerByIdWithEmote` | 16 | `SetSpeakerMC` | 17 | `SetSpeakerMC` |
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
| 66 | `SetSpeakerSoldier` | 67 | `SetSpeakerSoldier` | 68 | `SetSpeakerEthelberd` |
| 69 | `SetSpeakerEthelberd` | 70 | `SetSpeakerBarrett` | 71 | `SetSpeakerBarrett` |
| 72 | `SetSpeakerRaven` | 73 | `SetSpeakerRaven` | 74 | `SetSpeakerTraveler` |
| 75 | `SetSpeakerTraveler` | 76 | `nop` | 77 | `SlidePortraitToX` |
| 78 | `SlidePortraitToX` | 79 | `SlidePortraitBy` | 80 | `SlidePortraitBy` |
| 81 | `WaitPortraitSettled` | 82 | `WaitPortraitSettled` | 83 | `ClosePortraits` |
| 84 | `SetPortraitField62` | 85 | `SetPortraitTargetY` | 86 | `SetPortraitTargetY` |
| 87 | `JoltPortraitY` | 88 | `JoltPortraitY` | 89 | `SetPortraitTremble` |
| 90 | `SetPortraitTremble` | 91 | `SetSceneBit` | 92 | `EndDialogue` |
| 93 | `SetDialogueBoxStyle` | 94 | `SetBoxNormal` | 95 | `SetBoxShout` |
| 96 | `SetBoxThought` | 97 | `SetBoxTrembling` | 98 | `ShakeDialogueBox` |
| 99 | `TeleportActor` | 100 | `TeleportActor` | 101 | `PlaceActorAndFace` |
| 102 | `PlaceActorAndFace` | 103 | `TurnActorToAngle` | 104 | `TurnActorToAngle` |
| 105 | `QueryCalendarEventStub` | 106 | `RotateActorInPlace` | 107 | `TurnActorToFaceTarget` |
| 108 | `TurnActorToFaceTarget` | 109 | `TurnActorToFaceTarget` | 110 | `FaceEventActor` |
| 111 | `SetActorAuxYaw` | 112 | `SetActorAuxYaw` | 113 | `WaitActorAuxYaw` |
| 114 | `WaitActorAuxYaw` | 115 | `MoveActorToTile_LockAI` | 116 | `MoveActorToTile_LockAI` |
| 117 | `MoveActorToTileFaceTravel` | 118 | `MoveActorToTileFaceTravel` | 119 | `MoveActorToTileKeepFacing` |
| 120 | `MoveActorToTileKeepFacing` | 121 | `MoveNpcToTileKeepAnim` | 122 | `MoveNpcToTileKeepAnim` |
| 123 | `MoveActorByOffset` | 124 | `MoveActorByOffset` | 125 | `MoveActorByOffsetFaceTravel` |
| 126 | `MoveActorByOffsetFaceTravel` | 127 | `MoveActorByOffsetKeepFacing` | 128 | `MoveActorByOffsetKeepFacing` |
| 129 | `QueryActorMoveBusy` | 130 | `QueryActorMoveBusy` | 131 | `QueryActorBeyondRange` |
| 132 | `QueryActorBeyondRange` | 133 | `PlayActorAnim` | 134 | `PlayActorAnim` |
| 135 | `QueryActorTilePosition` | 136 | `QueryActorTilePosition` | 137 | `QueryActorAnimBusy` |
| 138 | `QueryActorAnimBusy` | 139 | `ApplyEffectToActor` | 140 | `ApplyEffectToActor` |
| 141 | `SetActorOpacity` | 142 | `MoveSceneActorToTile` | 143 | `MoveSceneActorToTileFaceTravel` |
| 144 | `MoveSceneActorStraight` | 145 | `QueryPlayerTurnBusy` | 146 | `EquipItemToPlayer` |
| 147 | `RestoreDefaultEquip` | 148 | `QueryPlayerFlag40000` | 149 | `PlayerScriptedTalkAnim` |
| 150 | `TriggerActionAtTile` | 151 | `TriggerActionOnActor` | 152 | `QueryPlayerAnimBusy` |
| 153 | `EventSpawnNpc` | 154 | `EventSpawnNpcVariant` | 155 | `EventSpawnNpcEx` |
| 156 | `UnregisterEventActor` | 157 | `SpawnMapEntity` | 158 | `SetMapAmbientColor` |
| 159 | `SwapMapPalette` | 160 | `EventNpcWalkToTile` | 161 | `EventNpcWalkToTileKeepFacing` |
| 162 | `SetEventActorFacing` | 163 | `FaceEventActorTowardTarget` | 164 | `QueryEventActorMoving` |
| 165 | `TriggerActionAtEventActor` | 166 | `ApplyEffectToEventActor` | 167 | `EventActorPlayAnim` |
| 168 | `EventActorResyncAnimFrame` | 169 | `QueryEventActorAnimBusy` | 170 | `SetEventActorAnimSpeed` |
| 171 | `SetEventActorAlpha` | 172 | `ShowEventActorEmote` | 173 | `SetEventActorInScriptFlag` |
| 174 | `AddActorHeightOffset` | 175 | `SetEventActorCollideRadius` | 176 | `SetEventActorScale` |
| 177 | `EventActorEnterIdle` | 178 | `SetEventActorTurnAngle` | 179 | `QueryEventActorTurning` |
| 180 | `KillEventActor` | 181 | `DismissEventActor` | 182 | `QueryEventActorTilePosition` |
| 183 | `SetActorAIScript` | 184 | `SetActorIgnoredByMonsters` | 185 | `PlayActorSplash` |
| 186 | `SetCameraPosition` | 187 | `ReattachCameraToActor` | 188 | `HoldCameraInPlace` |
| 189 | `ResetCameraToPlayer` | 190 | `SetCameraTarget` | 191 | `ResetCameraToActor` |
| 192 | `ResetCameraToActor` | 193 | `SetCameraTargetToCurrentPosition` | 194 | `FocusCameraOnPlayer` |
| 195 | `WaitCameraAtMark` | 196 | `QueryCameraBeyondRangeOfTarget` | 197 | `ShakeCamera` |
| 198 | `WaitForPlayerEffect` | 199 | `SetCameraTargetActor` | 200 | `SetCameraTargetActor` |
| 201 | `SetCameraSettleMode` | 202 | `SetCameraZoom` | 203 | `SetCameraMapBounds` |
| 204 | `SleepInBed` | 205 | `RefreshMapTiles` | 206 | `SetActorHeldItem` |
| 207 | `SetActorHeldItem` | 208 | `HandOrDropItem` | 209 | `HandOrDropItem` |
| 210 | `AttachItemVisual` | 211 | `ShowActorEmote` | 212 | `ShowActorEmote` |
| 213 | `GetPlayerPosition` | 214 | `SetNpcStoryFlag` | 215 | `ClearNpcStoryFlag` |
| 216 | `QueryNpcInCurrentArea` | 217 | `ApplyFriendshipDelta` | 218 | `QueryNpcFriendshipLevel` |
| 219 | `QueryNpcFriendshipLevel` | 220 | `QueryAllNpcsFriendship` | 221 | `AdjustCurrentNpcFriendship` |
| 222 | `LockNpcPose` | 223 | `SetNpcEngaged` | 224 | `SetNpcEngaged` |
| 225 | `StreamInNpc` | 226 | `QueryNpcScheduleId` | 227 | `QueryNpcScheduleIsOneOf` |
| 228 | `QueryNpcScheduleIsOneOf` | 229 | `QueryNpcAvailableFlagClear` | 230 | `SetSceneCast` |
| 231 | `SetSceneCast` | 232 | `QueryNpcHidden` | 233 | `HideNpc` |
| 234 | `HideNpc` | 235 | `QueryNpcSeenToggle` | 236 | `QueryNpcInteractEligible` |
| 237 | `QueryNpcPairInteraction` | 238 | `QueryQuestNpcsAvailable` | 239 | `QueryQuestNpcsAvailable` |
| 240 | `QueryNpcGroupPresentNearby` | 241 | `QueryNpcGroupPresentNearby` | 242 | `SetSceneFlag0x200` |
| 243 | `EndDialogueLock` | 244 | `NpcShowItem` | 245 | `QueryGiftAffinity` |
| 246 | `StreamInNpcAtTile` | 247 | `QueryTileFacingTarget` | 248 | `SetNpcVisibleFlag` |
| 249 | `SetNpcVisibleFlag` | 250 | `SyncActorAnimFrame` | 251 | `SyncActorAnimFrame` |
| 252 | `SetActorAnimSpeedScale` | 253 | `SetActorAnimSpeedScale` | 254 | `SetActorAnimFrameDirect` |
| 255 | `QueryActorAilmentState` | 256 | `SetActorStatusConditions` | 257 | `QueryAllNpcsEligibleForComment` |
| 258 | `QueryAllNpcsEligibleForComment` | 259 | `PickRandomVillagers` | 260 | `QueryActorHpWellness` |
| 261 | `SetNpcParticipationFlag` | 262 | `QueryCurrentInteractionNpc` | 263 | `ResetNpcToIdle` |
| 264 | `ResetNpcToIdle` | 265 | `QueryPlayerOrCompanionDowned` | 266 | `SetOrClearNpcSchedule` |
| 267 | `SetOrClearNpcSchedule` | 268 | `QueryNpcArrivedAtSchedule` | 269 | `QueryNpcArrivedAtSchedule` |
| 270 | `ReleaseNpcScriptedPlacement` | 271 | `ReleaseNpcScriptedPlacement` | 272 | `nop` |
| 273 | `QueryNpcPresent` | 274 | `QueryNpcPresent` | 275 | `SetNpcPresenceState` |
| 276 | `QueryNpcHeldItem` | 277 | `QueryNpcHeldItem` | 278 | `QueryNpcFavoriteItem` |
| 279 | `QueryNpcFavoriteItem` | 280 | `QueryNpcDateState` | 281 | `SetNpcDateState` |
| 282 | `QueryNpcActorPresent` | 283 | `QueryDateCompanionId` | 284 | `MountActor` |
| 285 | `SetSceneReadyFlag` | 286 | `ShakeActor` | 287 | `SetNpcOutfit` |
| 288 | `QueryNpcOutfit` | 289 | `CarryBaby` | 290 | `PostFamilyMilestones` |
| 291 | `SpawnChildEventRecords` | 292 | `CommitMarriage` | 293 | `ResetNpcDailySchedule` |
| 294 | `ResetNpcDailySchedule` | 295 | `ResetNpcScheduleWithState` | 296 | `ApplyNpcScheduleState` |
| 297 | `ApplyNpcScheduleState` | 298 | `ApplyPendingNpcPlan` | 299 | `ApplyPendingNpcPlan` |
| 300 | `ResetAllNpcSchedules` | 301 | `RefreshNpcScheduleForToday` | 302 | `SetNpcActionDelay` |
| 303 | `SetNpcActionDelay` | 304 | `GetYear` | 305 | `GetSeason` |
| 306 | `GetDay` | 307 | `GetHourMinute` | 308 | `GetDateSnapshot` |
| 309 | `IsFrey` | 310 | `QueryPlayerIsLest` | 311 | `HealPartyFull` |
| 312 | `HealPartyByShift` | 313 | `RestorePlayerRP` | 314 | `CurePartyStatus` |
| 315 | `QueueNpcGreetingEvent` | 316 | `SetNpcVisible` | 317 | `SetNpcVisible` |
| 318 | `SetFlag` | 319 | `SetEmote` | 320 | `SetEmote` |
| 321 | `GetEmote` | 322 | `SetMood` | 323 | `SetMood` |
| 324 | `GetMood` | 325 | `GetLumber` | 326 | `ModifyLumber` |
| 327 | `EndActorTransformAndSetOutfit` | 328 | `EndActorTransformAndSetOutfit` | 329 | `IsPosing` |
| 330 | `SetActorOutfitDirect` | 331 | `SetActorOutfitDirect` | 332 | `WarpToMap` |
| 333 | `WarpToMapInSubEvent` | 334 | `FadeScreen` | 335 | `FadeScreenToClear` |
| 336 | `SetFadeColor` | 337 | `WaitForFade` | 338 | `QueryNpcOnPlayerMap` |
| 339 | `GetNpcCurrentMap` | 340 | `SetVar0` | 341 | `SetVar0` |
| 342 | `GetVar0` | 343 | `SetVar1` | 344 | `GetVar1` |
| 345 | `SetVar11` | 346 | `GetVar11` | 347 | `SetVar2` |
| 348 | `SetVar2` | 349 | `SetVar3` | 350 | `GetVar3` |
| 351 | `SetVar4` | 352 | `GetVar4` | 353 | `SetVar5` |
| 354 | `GetVar5` | 355 | `SetVar6` | 356 | `GetVar6` |
| 357 | `SetVar7` | 358 | `GetVar7` | 359 | `SetVar8` |
| 360 | `GetVar8` | 361 | `SetVar9` | 362 | `GetFestivalDate` |
| 363 | `GetNpcBirthday` | 364 | `SetVar10` | 365 | `SetVar15` |
| 366 | `SetVar13And14` | 367 | `GetVar14` | 369 | `TryMountPlayerOnHostActor` |
| 370 | `SetSceneStateBit1` | 371 | `EvalCondScriptA` | 372 | `EvalCondScriptB` |
| 373 | `DispatchCondScriptEntry` | 374 | `CondScriptDispatchAltAction` | 375 | `TriggerWorldAction` |
| 376 | `BeginShopkeeperInteraction` | 377 | `ConsumeInteractionResult` | 378 | `ConsumeInteractionResult` |
| 379 | `PlayMusic` | 380 | `StopMusic` | 381 | `nop` |
| 382 | `FadeMusicVolume` | 383 | `SetMusicLock` | 384 | `ResetMusicResumePositions` |
| 385 | `PlaySound` | 386 | `StopVoices` | 387 | `PlaySfxWithNpcRemap` |
| 388 | `nop` | 389 | `SetPooledVoiceVolume` | 390 | `StopVoiceId` |
| 391 | `nop` | 392 | `PlayVoicedSound` | 393 | `FreezePlayer` |
| 394 | `WarpPlayer` | 395 | `SetPlayerFacingAndPose` | 396 | `SetPlayerFacingAndPose` |
| 397 | `SetPartyOutfit` | 398 | `BuildOutfitChoiceMask` | 399 | `GetPlayerSubstate` |
| 400 | `SetPlayerMale` | 401 | `SendMonsterToFarmArea` | 402 | `RecallFarmMonster` |
| 403 | `GetFreeFarmAreas` | 404 | `GetOccupiedFarmAreas` | 405 | `SetFarmMonsterPlantOrder` |
| 406 | `GetFarmMonsterPlantOrder` | 407 | `QueryActiveKillCount` | 408 | `CountLivingEnemies` |
| 409 | `CountTamedFarmMonsters` | 410 | `TameEventMonster` | 411 | `QueryCompanionMonsterData` |
| 412 | `BlackScreen` | 413 | `SetDialogueBoxY` | 414 | `GetChoiceIndexAndItem` |
| 415 | `SetDialogueFlag4Bit2` | 416 | `QueryPlayerVariable` | 417 | `ModifyPlayerResource` |
| 418 | `QueryBackpackHasRoom` | 419 | `QueryBackpackHasFreeSlot` | 420 | `QueryBackpackFreeSlots` |
| 421 | `SetNextItemAttributes` | 422 | `SetNextItemAttributesPacked` | 423 | `GivePlayerItem` |
| 424 | `GivePlayerItem` | 425 | `ForcePlayerHoldItem` | 426 | `IsPlayerHoldingItem` |
| 427 | `MaxWeaponSkills` | 428 | `TakeItem` | 429 | `TakeItemFromBackpack` |
| 430 | `ConsumeHeldItem` | 431 | `HasItem` | 432 | `CheckCropPlantable` |
| 433 | `QueryFishSizeRecords` | 434 | `GetItemGoldValue` | 435 | `GetItemBuyPrice` |
| 436 | `IsItemStackable` | 437 | `IsItemInCategoryList` | 438 | `QueryHasItemOfCategory` |
| 439 | `ReleaseFarmMonster` | 440 | `GetNpcSpecies` | 441 | `QueryConfirmButton` |
| 442 | `QueryStickInputActive` | 443 | `SetFlagBit` | 444 | `SetFlagBitIfCond` |
| 445 | `GetFlagBit` | 446 | `SetWeather` | 447 | `GetWeather` |
| 448 | `SetWeatherTransition` | 449 | `GetWeatherTransition` | 450 | `GetWeatherStreak` |
| 451 | `GetDayOfWeek` | 452 | `SpawnItemAtTile` | 453 | `DropStagedItem` |
| 454 | `SpawnItemVisual` | 455 | `DespawnItemVisuals` | 456 | `QueryEquippedItemAttr` |
| 457 | `ShowRewardPopup` | 458 | `ShowQuestReward` | 459 | `ShowRewardPopupAtTile` |
| 460 | `AddRewardItem` | 461 | `SuppressRewardJingle` | 462 | `GrantFestivalRewards` |
| 463 | `DropItem` | 464 | `DropItemStack` | 465 | `SetCalendarPauseFlag` |
| 466 | `SkipToTime` | 467 | `SetTime` | 468 | `FastForwardCalendar` |
| 469 | `SetOrAddCalendarDate` | 470 | `GetGuestNpcVariant` | 471 | `GetChildFriendPoints` |
| 472 | `SetGuestNpcSubVariant` | 473 | `RollChildDailyPref` | 474 | `SetGuestRosterGate` |
| 475 | `SetNpcStateByte` | 476 | `RecruitNpcToParty` | 477 | `RecruitNpcToParty` |
| 478 | `RecruitNpcToPartyHeld` | 479 | `RecruitNpcToPartyHeld` | 480 | `RecruitHostNpcToParty` |
| 481 | `GetPartyMemberId` | 482 | `GetPartyMemberId` | 483 | `DismissBothCompanions` |
| 484 | `DismissBothCompanionsQuiet` | 485 | `DismissBothCompanionsEx` | 486 | `DismissCompanionByCharId` |
| 487 | `QueryCurrentNpcInParty` | 488 | `SetCompanionScriptedPresence` | 489 | `SetCompanionsSceneHeld` |
| 490 | `QueryDatePartnerAtDateSpot` | 491 | `nop` | 492 | `FaceNpcToPlayer` |
| 493 | `GetNpcFacingMode` | 494 | `SetCompanionVisible` | 495 | `WarpCompanion` |
| 496 | `MoveCompanion` | 497 | `MoveCompanionNF` | 498 | `MoveCompanionRel` |
| 499 | `MoveCompanionRelNF` | 500 | `SetCompanionPose` | 501 | `CompanionFaceTarget` |
| 502 | `WaitCompanionSettled` | 503 | `ShowCompanionEmote` | 504 | `QueryPartyMemberTileY` |
| 505 | `nop` | 506 | `WarpMonstersToPlayer` | 507 | `PopulateSlayRequest` |
| 508 | `PopulateQuestKind2RandomRewards` | 509 | `PopulateQuestKind2RandomRewards` | 510 | `PopulateQuestKind2LiteralRewards` |
| 511 | `PopulateQuestKind3RandomRewards` | 512 | `PopulateQuestKind3RandomRewards` | 513 | `PopulateQuestKind4RandomRewards` |
| 514 | `PopulateQuestKind4RandomRewards` | 515 | `PopulateQuestKind4LiteralRewards` | 516 | `PostBoardQuestKind5` |
| 517 | `PostBoardQuestKind5` | 518 | `PostBoardQuestKind6` | 519 | `PostBoardCraftQuest` |
| 520 | `PostQuestGoalNumber` | 521 | `PopulateQuestKind9LiteralRewards` | 522 | `PopulateQuestKind10RandomRewards` |
| 523 | `PopulateQuestKind10LiteralRewards` | 524 | `NopCompleteSubEventGoals` | 525 | `QuestOnComplete` |
| 526 | `nop` | 527 | `AdvanceRng` | 528 | `QueryQuestRewardItem` |
| 529 | `ClearAllRequestRecords` | 530 | `CommitQuestAcceptance` | 531 | `ClearBoardRequest` |
| 532 | `QueryNpcQuestPreview` | 533 | `nop` | 534 | `GetDailyVisitor` |
| 535 | `QueryQuestRemainingByItem` | 536 | `StartReservedSubEvent` | 537 | `QueueSubEventGoalKind2` |
| 538 | `QueueSubEventGoalKind2` | 539 | `QueueSubEventGoalKind3` | 540 | `QueueSubEventGoalKind3` |
| 541 | `QueueSubEventGoalKind4` | 542 | `QueueSubEventGoalKind4` | 543 | `QueueSubEventGoalKind5` |
| 544 | `QueueSubEventGoalKind5` | 545 | `QueueSubEventGoalKind6` | 546 | `QueueSubEventCraftGoal` |
| 547 | `QueueSubEventGoalKind10` | 548 | `CompleteAllSubEventGoals` | 549 | `FinishCurrentSubEvent` |
| 550 | `nop` | 551 | `ResetSubEventGoals` | 552 | `GetSubEventGoalRemaining` |
| 553 | `SetNpcSubEventFlag` | 554 | `SetNpcSubEventFlag` | 555 | `SetNpcAttentionRadius` |
| 556 | `SetNpcAttentionRadius` | 557 | `SetNpcRecognitionFlags` | 558 | `SetNpcRecognitionFlags` |
| 559 | `StartFestivalContest` | 560 | `StageSceneNpcs` | 561 | `GetSceneStateBytes` |
| 562 | `RefreshSceneNpcs` | 563 | `EquipScriptedWeapon` | 564 | `RemoveScriptedWeapon` |
| 565 | `nop` | 566 | `RecordFestivalPlacement` | 567 | `GetTomorrowsCalendarEvent` |
| 568 | `GetSceneNpc` | 569 | `RankFestivalContestants` | 570 | `GetTodaysRequestNpc` |
| 571 | `SetSceneScratch` | 572 | `GetSceneScratchByte` | 573 | `GetFestivalPlacements` |
| 574 | `ShuffleSceneBuffer` | 575 | `GetShuffleValue` | 576 | `GetSceneEventNpc` |
| 577 | `GetFestivalResults` | 578 | `SpawnEventMonsters` | 579 | `GetSceneEventFlags` |
| 580 | `GetGivenItemStats` | 581 | `CheckFishRecord` | 582 | `GetFishRecord` |
| 583 | `nop` | 584 | `nop` | 585 | `nop` |
| 586 | `nop` | 587 | `PlaceFurniture` | 588 | `IsFurniturePlaced` |
| 589 | `PlayerPickUpObject` | 590 | `BreakFurnitureIntoMaterials` | 591 | `ClearAllTileObjects` |
| 592 | `CanPlaceFurnitureInRoom` | 593 | `PickRandomPlacedFurniture` | 594 | `CommitGrabbedObject` |
| 595 | `SetMinimapMarker` | 596 | `RollUniformIntegerLessThanN` | 597 | `RollShopCategoryItemReturnId` |
| 598 | `RollRandomItemMatchingDisplayName` | 599 | `RollRandomDishItem` | 600 | `RollRandomEquipmentItem` |
| 601 | `RollRandomFurItem` | 602 | `RollRandomMedicineOrFailedDish` | 603 | `RollRandomGrassItem` |
| 604 | `RollRandomIngredientItem` | 605 | `RollRandomSeasoningItem` | 606 | `RollThreeFlowerItemsAvoidDup` |
| 607 | `RollRandomFlowerSeedItem` | 608 | `nop` | 609 | `RollRandomPointInRadiusAroundCenter` |
| 610 | `SetChoiceVisibleMask` | 611 | `ClearChoiceVisibleRange` | 612 | `SetChoiceVisibleBit` |
| 613 | `CalcChoicePrescroll` | 614 | `SetDialogueBoxMode` | 615 | `ArmChoiceOption` |
| 616 | `QueryAndSetCraftedFlag` | 617 | `ShowStaffCredits` | 618 | `WaitStaffCreditsDone` |
| 619 | `QueryNpcAcceptsPartyInvite` | 620 | `MarkSpouseCleared` | 621 | `SetDifficulty` |
| 622 | `QueryDifficulty` | 623 | `SetDialogueAutoAdvance` | 624 | `SetDialogueHoldFrames` |
| 625 | `EnterSharanceMazeStage` | 626 | `GetMazeStageClearedBit` | 627 | `JumpToRandomDate` |
| 628 | `SetRegisters` | 629 | `SetRegisters` | 630 | `nop` |
| 631 | `RollSeededHashByMode16` | 632 | `RollSeededDailyRandom` | 633 | `ResetActionEventId` |
| 634 | `SetActionTriggerByte` | 635 | `GetActionTriggerByte` | 636 | `nop` |
| 637 | `SaveCalendarSnapshot` | 638 | `GetHarvestReport` | 639 | `GetPrincePoints` |
| 640 | `AddPrincePoints` | 641 | `GetTourists` | 642 | `AddTourists` |
| 643 | `ApplyPrinceOrder` | 644 | `GetPrinceOrderState` | 645 | `PromotePrinceRank` |
| 646 | `GetPrinceRank` | 647 | `GetPrinceOrderCost` | 648 | `GetShippingCompletionPercent` |
| 649 | `QueryShippingBoxGold` | 650 | `GetLifetimeShippedGold` | 651 | `AdvanceStoryProgress` |
| 652 | `GetPreviousMapId` | 653 | `ClearShopSelectionA` | 654 | `ClearShopSelectionB` |
| 655 | `ClearShopSelectionC` | 656 | `SetMapScrollSpeedX` | 657 | `SetMapScrollSpeedY` |
| 658 | `GetSceneWordPair112` | 659 | `MyShopAction` | 660 | `SetActorStatusFlag` |
| 661 | `SetActorStatFlagRecompute` | 662 | `SetActorArmorBreak` | 663 | `MakeActorUntameable` |
| 664 | `LockActorMaxSp` | 665 | `SetActorFacing` | 666 | `QuerySaveConfigBit0` |
| 667 | `SetSaveConfigBit0` | 668 | `QuerySaveConfigBit4` | 669 | `SetSaveConfigBit4` |
| 670 | `QuerySaveConfigBit5` | 671 | `SetSaveConfigBit5` | 672 | `QuerySaveConfigBit2` |
| 673 | `QuerySaveConfigBit3` | 674 | `GetRuneMedals` | 675 | `ConvertMedalsToGold` |
| 676 | `GetMedalGoldRate` | 677 | `SpawnTileEffectObject` | 678 | `WallOffTileRect` |
| 679 | `IncrementPlayerSkillLevel` | 680 | `ApplyAttackToPlayer` | 681 | `RollBreadRecipe` |
| 682 | `SetSceneFlag400` | 683 | `PlayCutsceneVideo` | 684 | `IsProjectorSceneUnlocked` |
| 685 | `SetFreeLookCameraMode` | 686 | `GetFreeLookCameraMode` | 687 | `RebuildMinimap` |
| 688 | `ToggleMinimap` | 689 | `RespawnRoomFurnitureVisuals` | 690 | `GetNpcGivenHat` |
| 691 | `MultiplyValues` | 692 | `FinishPendingDate` | 693 | `nop` |
| 694 | `QuerySaveConfigBit1` | 695 | `QuerySpouseClearedBit` | 696 | `RemoveItemFromBackpack` |
| 697 | `ReturnToTitle` | 698 | `SetShopkeeperMessage` | 699 | `SetNarrationModeIf` |
| 700 | `QueryBackpackHasItem` | 701 | `SetPlayerSkillXp` | 738 | `NpcAction_Kind0_LieDownToSleep` |
| 739 | `Npc_TickWanderBehavior` | 740 | `NpcAction_PlayKindIdleAnim` | 741 | `NpcAction_PlayKindIdleAnim` |
| 742 | `NpcAction_PlayKindIdleAnim` | 743 | `NpcAction_PlayKindIdleAnim` | 744 | `NpcAction_PlayKindIdleAnim` |
| 745 | `NpcAction_PlayKindIdleAnim` | 746 | `NpcAction_PlayKindIdleAnim` | 747 | `NpcAction_Kind9_LookAroundIdle` |
| 748 | `NpcAction_Kind10_GreetThenBow` | 749 | `NpcAction_PlayKindIdleAnim` | 750 | `NpcAction_PlayKindIdleAnim` |
| 751 | `NpcAction_Kind13_GiftAndTeleportOut` | 752 | `NpcAction_Kind14_DelayedIdleAnim` | 753 | `NpcAction_Kind15_SleepOrExitHome` |
| 754 | `NpcAction_PlayKindIdleAnim` | 755 | `NpcAction_Kind17_EatFood` | 756 | `NpcAction_Kind18_RandomTimerIdleAnim` |
| 757 | `NpcAction_Kind19_ChatByFriendshipLevel` | 758 | `NpcAction_Kind20_EquipTool506` | 759 | `NpcAction_PlayKindIdleAnim` |
| 760 | `NpcAction_Kind22_EquipTool483` | 761 | `NpcAction_Kind23_EquipHeldTool` | 762 | `NpcAction_Kind24_RandomGreetGesture` |
