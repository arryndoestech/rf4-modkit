# RF4S Cutscene Opcode Reference

Every `rf3.mc` cutscene instruction (702 slots).

Auto-generated from `rf4s_modkit/opcode_meta.py` by `gen_opcode_reference.py` — **682** named opcodes across 14 categories (plus 20 reserved/unused slots), the control-flow opcodes, the expression grammar, and the **em.bin** Event-Manager opcodes scenes bridge to. Do not edit by hand; re-run the generator to refresh. This is the GUI-free companion to the editor's Alt-hover tooltips.

## Contents

- [Dialogue & portraits](#dialogue--portraits) (108 ops)
- [Camera / screen](#camera--screen) (35 ops)
- [Actors & player](#actors--player) (158 ops)
- [Companions & party](#companions--party) (28 ops)
- [Flags & variables](#flags--variables) (36 ops)
- [Audio](#audio) (12 ops)
- [Time & calendar](#time--calendar) (18 ops)
- [Items, rewards, economy](#items-rewards-economy) (48 ops)
- [Effects & world](#effects--world) (18 ops)
- [Quests](#quests) (42 ops)
- [Scene flow / control](#scene-flow--control) (22 ops)
- [Queries](#queries) (147 ops)
- [Other](#other) (8 ops)
- [No-op (PC-port stub)](#no-op-pc-port-stub) (2 ops)
- [Control opcodes (flow backbone)](#control-opcodes-flow-backbone) (15 ops)
- [Expression operands (argument encoding)](#expression-operands-argument-encoding)
- [Event Manager (em.bin) opcodes](#event-manager-embin-opcodes)
- [Reserved / unused slots](#reserved--unused-slots)
- [Opcode index (by number)](#opcode-index-by-number)

## Dialogue & portraits

### `op 1` — SetDialogueSuppressed(suppressed)
*verified:* yes, in game

Dialogue suppression switch: 1 makes every following DIALOG skip its line (nothing is shown), 0 turns lines back on. Sets bit 3 (0x8) of the scene control word (g_sceneAuxControlFlags = g_currentSceneContext+120) from bit 0 of the argument. With no box open a skipped DIALOG finishes at once; with a box still open (after its line was confirmed) the skipped DIALOG waits for that box to finish again, which never happens: the scene FREEZES. Close the box (EndDialogue) before turning it on, and turn it off again before the scene ends (only an engine reset of the scene context clears it). Unused by the shipped scripts.

Args:
  0. suppressed (1 = following DIALOG lines are skipped, 0 = shown again (only bit 0 counts)) — verified in game
     - `0` = show_lines
     - `1` = skip_lines

### `op 5` — ShowPortrait(character, face, side)
*verified:* yes, in game

Show or change a character's E-mote portrait on the left or right side without touching the name plate, text blip, voice or emote icons. A DIALOG line must come after it (usually after the SetSpeaker… that names the speaker): the portrait belongs to the next line shown.

Args:
  0. character (0 = player; 1-23 villagers; 22/23 = child (resolved to GF_REG_CHILD_ID); 25 = no-op) — verified in game
  1. face (< 1000 = face index; 1000-1927 = raw expression entry; 255/254 = stock alternates of the outfit row) — verified in game
  2. side (0 = the left slot, any non-zero value = the right slot (seen in game for 1, 2, 3, 254). The code also sets a flip bit from bit 0, but no value mirrors the portrait on screen) — verified in game
     - `0` = left
     - `1` = right

### `op 6` — ShowPortraitWithEmote(character, side, expression, emote_or_voice)

Show or update a character's E-mote speaker portrait on one side of the dialogue box, with an optional emote icon or voice clip. Does not change the name plate or the text blip, so it is used to change a listener's face between lines.

Args:
  0. character (0 = player, 1-26 villagers/family per the character table (22/23 = the children via REG_CHILD_ID))
  1. side (0 = side-0 portrait slot (host+88), 1 = side-1 slot (host+96))
  2. expression (< 1000 = per-character face index; 1000..1927 = raw expression entry (id-1000); 254/255 = special portrait states)
  3. emote_or_voice (0 = none; 186..192 = emote icon shown on the portrait; >= 0x1F0 (496) = play that voice/sfx id instead)

### `op 7` — ShowPortraitWithEmote(character, side, expression, emote_or_voice)

Show or update a character's E-mote speaker portrait on one side of the dialogue box, with an optional emote icon or voice clip. Does not change the name plate or the text blip, so it is used to change a listener's face between lines.

Args:
  0. character (0 = player, 1-26 villagers/family per the character table (22/23 = the children via REG_CHILD_ID))
  1. side (0 = side-0 portrait slot (host+88), 1 = side-1 slot (host+96))
  2. expression (< 1000 = per-character face index; 1000..1927 = raw expression entry (id-1000); 254/255 = special portrait states)
  3. emote_or_voice (0 = none; 186..192 = emote icon shown on the portrait; >= 0x1F0 (496) = play that voice/sfx id instead)

### `op 8` — SetSpeakerName(name_id)

Set the message-box name plate (and the matching text blip) for the following DIALOG lines. Shows no text and no portrait (except event-participant ids 27-33 / 41-47, which also bring up that participant's portrait).

Args:
  0. name_id (0 = player's own saved name; 1..26 villager; 27..47 event participant; >= 48 name-archive entry; 0xFFFF = '???')

### `op 9` — SetSpeakerName(name_id)

Set the message-box name plate (and the matching text blip) for the following DIALOG lines. Shows no text and no portrait (except event-participant ids 27-33 / 41-47, which also bring up that participant's portrait).

Args:
  0. name_id (0 = player's own saved name; 1..26 villager; 27..47 event participant; >= 48 name-archive entry; 0xFFFF = '???')

### `op 10` — SetSpeakerVoice(name_id, blip)
*verified:* yes, in game

Set the speaker for the following DIALOG lines to a named voice: name plate plus a chosen text blip, no portrait. Used for off-screen, unnamed or non-villager speakers. It does not remove a portrait already on screen (seen in game): clear it first if the voice should speak alone.

Args:
  0. name_id (entry of the character-name archive (e.g. 21 Ventuswill, 236 Ethelwill, 392 '???', 738 Joyful Captain)) — verified in game
     - *(enum: 1000 values — use the in-editor picker or the id database)*
  1. blip (0 = male (normal), 1 = female (high), 2 = monster (slightly lower), 3 = dragon (Ventuswill), 4 and above = the player's own blip (female for Frey, male for Lest) -- all seen in game) — verified in game
     - `0` = male
     - `1` = female
     - `2` = monster
     - `3` = dragon
     - `4` = player_blip

### `op 11` — SetSpeakerNameVisible(visible)
*verified:* yes, in game

Hides (0) or shows (non-zero) the speaker-name label for the following DIALOG lines. Authors wrap sound-effect lines such as "*MUNCH*" in SetSpeakerNameVisible(0) ... SetSpeakerNameVisible(1).

Args:
  0. visible (0 = hide the name label, non-zero = show it) — verified in game
     - `0` = hide name
     - `1` = show name

### `op 12` — SetSpeakerById(speaker, face, side)

Speaker cue by character id: shows that character's portrait on the given side, sets the name plate and the text blip for the next DIALOG. The generic form of the per-character SetSpeaker ops, without emote icon or voice.

Args:
  0. speaker (0 = player, 1-47 = NPC/villager char id (see the character table); 24-28 name via the remap table)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. face (compacted to an expression class 0-5 (>= 20 passed raw))
  2. side (0 = left portrait, 1 = right portrait)

### `op 13` — SetSpeakerById(speaker, face, side)

Speaker cue by character id: shows that character's portrait on the given side, sets the name plate and the text blip for the next DIALOG. The generic form of the per-character SetSpeaker ops, without emote icon or voice.

Args:
  0. speaker (0 = player, 1-47 = NPC/villager char id (see the character table); 24-28 name via the remap table)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. face (compacted to an expression class 0-5 (>= 20 passed raw))
  2. side (0 = left portrait, 1 = right portrait)

### `op 14` — SetSpeakerByIdWithEmote(speaker, side, expression, emote)

Speaker cue by a runtime character id (typically the spouse in REG_WIFE_ID): portrait with an expression on the given side, name plate, text blip, and an optional emote icon or voice clip.

Args:
  0. speaker (0 = player, 1-47 = NPC/villager char id (see the character table); usually REG_WIFE_ID or 30-37 (child / event slots))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. side (0 = left, 1 = right (corpus: always 1))
  2. expression (< 1000 face index, 1000+ raw expression entry (corpus 1, 2, 1192, 1224 ...))
  3. emote (0 = none; 186-192 emote icon over the portrait; >= 0x1F0 = a voice/sfx id played immediately)

### `op 15` — SetSpeakerByIdWithEmote(speaker, side, expression, emote)

Speaker cue by a runtime character id (typically the spouse in REG_WIFE_ID): portrait with an expression on the given side, name plate, text blip, and an optional emote icon or voice clip.

Args:
  0. speaker (0 = player, 1-47 = NPC/villager char id (see the character table); usually REG_WIFE_ID or 30-37 (child / event slots))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. side (0 = left, 1 = right (corpus: always 1))
  2. expression (< 1000 face index, 1000+ raw expression entry (corpus 1, 2, 1192, 1224 ...))
  3. emote (0 = none; 186-192 emote icon over the portrait; >= 0x1F0 = a voice/sfx id played immediately)

### `op 16` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = MC (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): the player (Lest/Frey) speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue. Before story progress 2 (the opening's name entry sets it) the name plate reads '???' instead of the player's name.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 17` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = MC (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): the player (Lest/Frey) speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue. Before story progress 2 (the opening's name entry sets it) the name plate reads '???' instead of the player's name.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 18` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Vishnal (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Vishnal speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 19` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Vishnal (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Vishnal speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 20` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Clorica (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Clorica speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 21` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Clorica (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Clorica speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 22` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Volkanon (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Volkanon speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 23` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Volkanon (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Volkanon speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 24` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Forte (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Forte speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 25` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Forte (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Forte speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 26` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Kiel (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Kiel speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 27` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Kiel (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Kiel speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 28` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Bado (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Bado speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 29` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Bado (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Bado speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 30` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Margaret (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Margaret speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 31` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Margaret (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Margaret speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 32` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Dylas (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Dylas speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 33` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Dylas (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Dylas speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 34` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Arthur (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Arthur speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 35` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Arthur (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Arthur speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 36` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Porcoline (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Porcoline speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 37` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Porcoline (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Porcoline speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 38` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = XiaoPai (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): XiaoPai speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 39` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = XiaoPai (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): XiaoPai speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 40` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = LinFa (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): LinFa speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 41` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = LinFa (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): LinFa speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 42` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Amber (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Amber speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 43` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Amber (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Amber speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 44` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Illuminata (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Illuminata speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 45` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Illuminata (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Illuminata speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 46` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Doug (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Doug speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 47` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Doug (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Doug speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 48` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Blossom (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Blossom speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 49` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Blossom (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Blossom speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 50` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Dolce (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Dolce speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 51` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Dolce (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Dolce speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 52` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Jones (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Jones speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 53` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Jones (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Jones speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 54` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Nancy (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Nancy speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 55` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Nancy (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Nancy speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 56` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Leon (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Leon speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 57` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Leon (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Leon speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 58` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Ventuswill (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Ventuswill speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 59` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Ventuswill (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Ventuswill speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 60` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Son (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Son speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 61` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Son (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Son speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 62` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Daughter (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Daughter speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 63` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Daughter (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Daughter speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 64` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Pico (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Pico speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 65` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Pico (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Pico speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 66` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Soldier (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Soldier speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue. Slot 25 has no portrait art: only the name plate changes, the previous portrait stays up.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 67` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Soldier (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Soldier speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue. Slot 25 has no portrait art: only the name plate changes, the previous portrait stays up.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 68` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Ethelberd (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Ethelberd speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 69` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Ethelberd (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Ethelberd speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 70` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Barrett (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Barrett speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 71` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Barrett (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Barrett speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 72` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Raven (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Raven speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 73` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Raven (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Raven speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 74` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Traveler (opcode = 16 + 2 * character + side), side = Left (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Traveler speaks, portrait on the left side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue. CRASHES THE GAME: slot 29 has no portrait art and the portrait code dereferences the missing sprite (in-game 2026-10-02, op 74; op 75 takes the same path). Unused by the shipped scripts.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 75` — SetSpeaker(character, side, face, trigger1, trigger2, trigger3)
*opcode arguments:* character = Traveler (opcode = 16 + 2 * character + side), side = Right (opcode & 1)
*verified:* yes, in game

Speaker cue for the following DIALOG line(s): Traveler speaks, portrait on the right side. Shows the E-mote portrait with the given face, sets the name plate and text blip when the speaker changes, and optionally plays a voice clip and shows up to two emote icons over the portrait (186 blush, 187 teardrop, 188 sweat, 189 white puff, 190 '!', 191 '?', 192 '!?'; a third icon is ignored; a voice id 0x1000000+n plays the clip). Carries no text; stays in effect until the next speaker op or EndDialogue. CRASHES THE GAME: slot 29 has no portrait art and the portrait code dereferences the missing sprite (in-game 2026-10-02, op 74; op 75 takes the same path). Unused by the shipped scripts.

Args:
  0. face (< 1000 = the character's face index (via g_emotePortrait_emoteToStringIdTable); 1000-1927 = raw expression entry (id-1000); 255 / 254 = the stock alternate expressions of the current outfit row (g_emotePortraitKindRows)) — verified in game
  1. trigger1 (0 = none; 186-192 = emote icon over the portrait; >= 0x1F0 (in practice 0x1000000+n) = voice/sfx played via Sfx_PlayByIdWithNpcVariantRemap; a player voice clip plays the player's own set (0x10001C0 = V_PLAW for Frey, V_PLAM for Lest; seen in game)) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  2. trigger2 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question
  3. trigger3 (as trigger1) — verified in game
     - `186` = blush
     - `187` = teary
     - `188` = sweat
     - `189` = angry
     - `190` = exclaim
     - `191` = question
     - `192` = exclaim_question

### `op 77` — SlidePortraitToX(character, x, speed)

Slides a speaker portrait horizontally to an absolute screen x. Returns immediately; follow with WaitPortraitSettled to wait for the slide.

Args:
  0. character (must match one of the two E-mote portraits, else no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (absolute target; corpus always 30)
  2. speed (stored as ~speed*1024 per tick; corpus 40)

### `op 78` — SlidePortraitToX(character, x, speed)

Slides a speaker portrait horizontally to an absolute screen x. Returns immediately; follow with WaitPortraitSettled to wait for the slide.

Args:
  0. character (must match one of the two E-mote portraits, else no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (absolute target; corpus always 30)
  2. speed (stored as ~speed*1024 per tick; corpus 40)

### `op 79` — SlidePortraitBy(character, dx, speed)

Slides a speaker portrait horizontally by a relative amount (negative = left). Returns immediately; WaitPortraitSettled waits for it.

Args:
  0. character (else no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (corpus -160..160; +/-100 = step in/out, +/-40 = lean)
  2. speed (corpus 5..200, mostly 30-100)

### `op 80` — SlidePortraitBy(character, dx, speed)

Slides a speaker portrait horizontally by a relative amount (negative = left). Returns immediately; WaitPortraitSettled waits for it.

Args:
  0. character (else no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (corpus -160..160; +/-100 = step in/out, +/-40 = lean)
  2. speed (corpus 5..200, mostly 30-100)

### `op 81` — WaitPortraitSettled(character)

Waits until the given speaker portrait has finished sliding. If no on-screen portrait belongs to that character it continues at once.

Args:
  0. character (no match = no wait)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 82` — WaitPortraitSettled(character)

Waits until the given speaker portrait has finished sliding. If no on-screen portrait belongs to that character it continues at once.

Args:
  0. character (no match = no wait)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 83` — ClosePortraits(which)

Dismiss one or both speaker portraits and wait until they have slid away.

Args:
  0. which (0 = side-0 portrait (host+88), 1 = side-1 portrait (host+96), anything else = both)

### `op 84` — SetPortraitField62(character, value, apply)

Writes a value into an unused field of the left portrait. Every shipped use passes apply = 0, so it does nothing in the retail game; it looks like a disabled portrait 'pulse' effect (130, 90, 120, 100 in a row).

Args:
  0. character (a character whose portrait is on screen (matched via EmotePortrait_MatchesCharId against host+96 then host+88))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. value (corpus 90/100/120/130 (100 looks like the default))
  2. apply (0 = do nothing; non-zero = write)

### `op 89` — SetPortraitTremble(character, level)

Makes a speaker portrait tremble (shake up and down); 0 stops it. Used for scared or shivering lines.

Args:
  0. character (else no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. level (0 = off; 1..6 larger = faster (6 = every other frame, 3 = every 16 frames); corpus 0-6)

### `op 90` — SetPortraitTremble(character, level)

Makes a speaker portrait tremble (shake up and down); 0 stops it. Used for scared or shivering lines.

Args:
  0. character (else no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. level (0 = off; 1..6 larger = faster (6 = every other frame, 3 = every 16 frames); corpus 0-6)

### `op 92` — EndDialogue()
*verified:* yes, in game

Close the dialogue box and both portraits at the end of a spoken exchange and clear the current speaker, so the next DIALOG without a SetSpeaker is narration. Waits until the box has closed.

### `op 93` — SetDialogueBoxStyle(style)
*verified:* yes, in game

Set the message-box style for the following lines: normal, shout, thought, trembling or tail-only. The general form of the fixed box-style ops 94-97 and the only way to get style 4.

Args:
  0. style (0 normal, 1 shout (jagged; the screen shakes), 2 thought (cloud), 3 trembling (wobbly; the box shakes), 4 tail only (no box, text only); 5 and 6 show only the name plate, 7 stray art (all seen in game)) — verified in game
     - `0` = normal
     - `1` = shout
     - `2` = thought
     - `3` = trembling
     - `4` = tail_only

### `op 94` — SetBoxNormal()
*verified:* yes, in game

Switch the message box to the normal style (style 0). Stays until another box-style op or the box closes.

### `op 95` — SetBoxShout()
*verified:* yes, in game

Switch the message box to the shout style (style 1): a jagged box, and the whole screen shakes when it appears (seen in game). Stays until another box-style op or the box closes.

### `op 96` — SetBoxThought()
*verified:* yes, in game

Switch the message box to the thought style (style 2): a cloud box with a bubble-trail tail that floats for about a second (does not delay the line). Stays until another box-style op or the box closes.

### `op 97` — SetBoxTrembling()
*verified:* yes, in game

Switch the message box to the trembling style (style 3): a wobbly box that shakes sideways when it appears (seen in game). Stays until another box-style op or the box closes.

### `op 98` — ShakeDialogueBox(frames)

Shake the message box (box, name and text) for a number of frames. Only the low byte of the argument is used.

Args:
  0. frames (value & 0xFF; 9000 -> 40 frames)

### `op 243` — EndDialogueLock(mode)

Release the conversation lock so control can return to the player at the end of a talk.

Args:
  0. mode (must be 0; any other value does nothing)

### `op 319` — SetNpcNicknameForPlayer(npc, nickname)

Sets what an NPC calls the player: from now on, the player-name placeholder in that NPC's lines shows the chosen nickname instead of the player's name. Used after dialogue choices like "I'll call you ..., just like always".

Args:
  0. npc
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. nickname (entry of rf3TxtHeroNickName (archive 15177): 94 Darling, 95 Honey, 99 Princess, 103 Dearest, 161 My Lady, 178 Your Highness, 185 Prince ...; 0 = use the player's name)

### `op 320` — SetNpcNicknameForPlayer(npc, nickname)

Sets what an NPC calls the player: from now on, the player-name placeholder in that NPC's lines shows the chosen nickname instead of the player's name. Used after dialogue choices like "I'll call you ..., just like always".

Args:
  0. npc
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. nickname (entry of rf3TxtHeroNickName (archive 15177): 94 Darling, 95 Honey, 99 Princess, 103 Dearest, 161 My Lady, 178 Your Highness, 185 Prince ...; 0 = use the player's name)

### `op 365` — SetButtonIconSlot(slot, icon)
*verified:* yes, in game

Choose which button icon the ＠字＠ token in the next dialogue lines shows (e.g. 'press ＠字＠ repeatedly'). Slot 0 is the plain ＠字＠.

Args:
  0. slot (slot index n used by the text token ＠字n＠ (larger ignored)) — verified in game
  1. icon (glyph U+E000 + icon; 160-182 and 193 are button icons (names from the game's glyph table), 183-191 draw nothing; 192 CRASHES the game (reads past the 32-entry glyph table, seen in game 2026-10-03); 23 draws nothing (seen in game 2026-10-06)) — verified in game
     - `160` = a
     - `161` = b
     - `162` = x
     - `163` = y
     - `164` = l1
     - `165` = r1
     - `166` = l2
     - `167` = r2
     - `168` = l1_2
     - `169` = r1_2
     - `170` = stick
     - `171` = right
     - `172` = down
     - `173` = up
     - `174` = left
     - `175` = up_2
     - `176` = down_2
     - `177` = left_2
     - `178` = right_2
     - `179` = start
     - `180` = select
     - `181` = start_2
     - `182` = select_2
     - `193` = dpad

### `op 366` — SetTextSlotEntries(archive, slot, entries...)

Fill the text slots that the ＠その他n＠ dialogue token prints: slot n shows entry bank14[n] of archive bank13[n] (with ＠ replaced by the player's name). Used for the nickname choice lists ('What would you like me to call you?'); GetVar14 (op 367) reads the entries back.

Args:
  0. archive (0 = 15177 (the nickname list); corpus always 0)
  1. slot (first slot)
  2. entries... (entry for slot, slot+1, ...; out-of-range slots dropped)

### `op 413` — SetDialogueBoxY(y)

Moves the dialogue box to a fixed screen height for the rest of the conversation (0 = default).

Args:
  0. y (0 = default (110); corpus 50)

### `op 415` — SetSubstitutionHighlight(enabled)

Turn the colour highlight of inserted words (item / map / name substitutions) off or back on for the following DIALOG lines.

Args:
  0. enabled (0 = turn the highlight markup of substituted text OFF (sets global bit 4); non-zero = back on)

### `op 555` — SetNpcAttentionRadius(npc, radius)

Set how far away an NPC 'radiates' for chatter: villagers within this many script position units (8 per tile) of it on the same map get flagged as its audience. 0 turns it off.

Args:
  0. npc (1..47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. radius (0 = off; 8 per tile (60 = 7.5 tiles); stored as a byte, so 1000 becomes 232)

### `op 556` — SetNpcAttentionRadius(npc, radius)

Set how far away an NPC 'radiates' for chatter: villagers within this many script position units (8 per tile) of it on the same map get flagged as its audience. 0 turns it off.

Args:
  0. npc (1..47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. radius (0 = off; 8 per tile (60 = 7.5 tiles); stored as a byte, so 1000 becomes 232)

### `op 610` — SetChoiceVisibleMask(choice visible...)

Choose which options the next choice menu shows: one flag per option (arg i non-zero shows option i). Hidden options close up, and the menu jumps to the target of the VISIBLE row the player picked (the first listed target for the first shown option ...), not of the option -- so masked menus usually give every option the same target and SWITCH on reg0, where the pick writes the option's ORIGINAL index. The mask is for the next menu only (picking clears it). An all-zero mask means no mask: every option shows and reg0 is left as it was.

Args:
  0. choice visible... (arg i non-zero shows option i of the next PROMPT_CHOICE (i < 32; higher args wrap))

### `op 611` — ClearChoiceVisibleRange(start, count)

Hide a run of options (start .. start+count-1) in the next choice menu's visibility mask. Hidden options close up, and the menu jumps to the target of the VISIBLE row the player picked (the first listed target for the first shown option ...), not of the option -- so masked menus usually give every option the same target and SWITCH on reg0, where the pick writes the option's ORIGINAL index. The mask is for the next menu only (picking clears it). An all-zero mask means no mask: every option shows and reg0 is left as it was.

Args:
  0. start (first option to hide (dword 0 only: 0..31))
  1. count (number of options to hide (not an end index))

### `op 612` — SetChoiceVisibleBit(index, visible)
*verified:* yes, in game

Show or hide one option of the next choice menu by setting / clearing its bit in the visibility mask. The mask only counts once a bit is set: then only the options with set bits show; while it is empty every option shows (seen in game). Careful: with an option hidden the menu jumps by visible position (the 2nd shown option takes the 2nd listed target), so shipped scripts send every option to one label and branch on reg0.

Args:
  0. index (0..127 (>= 128 lands in dword 3)) — verified in game
  1. visible (non-zero shows the option, 0 hides it) — verified in game

### `op 613` — CalcChoicePrescroll(option)

Choose which row the next choice menu opens on (default highlight). Call right before PROMPT_CHOICE; pass a visible-row index (subtract hidden options yourself).

Args:
  0. option (the visible row the next choice menu should open on)

### `op 614` — SetDialogueBoxMode(mode)
*verified:* yes, in game

Switch the dialogue box style for the following lines: 0 = the normal box; 1 = the Order Symbol (prince/princess) layout: the ring frame around the screen (prince_bg_01/02), the portrait 31 px higher, choice menus restyled (red diamond rows, placed right of centre), and HUD counters raised by ops 653-655 stay visible during the box; 2 = the cinematic event box: a dark see-through box in mid-screen, the speaker's name as plain text instead of the green plate, the portrait faded, a Next / Fast Fwd / View / Cancel help bar, and (per the code) no text blips. It stays set until changed; the shipped scripts only use 1 (21 times, the Order Symbol) and set it back to 0 themselves.

Args:
  0. mode (0 = normal, 1 = menu-style dialogue layout (all shipped uses), 2 = narration (no name label, no text blips)) — verified in game
     - `0` = normal
     - `1` = order_symbol
     - `2` = cinematic

### `op 615` — SetNextChoiceDescription(value 1, value 2, value 3)
*verified:* yes, in game

Make the next DIALOG the description of the next choice row instead of showing it: the Nth armed line describes row N of the following PROMPT_CHOICE / PROMPT_CHOICE_FORCED and is shown in the dialogue box while that row is highlighted. Takes 1 to 3 numbers, positional: value 1 prints through ＠金０＠, value 2 through ＠木０＠, value 3 through ＠石０＠ (shipped line 8858); values not passed are 0, and the shipped scripts mostly pass a single 0 (a description with no numbers). Give neighbouring rows different description lines: when the highlight moves to a row whose description is the same line id, the box is not reloaded and keeps the previous row's numbers (in game 2026-10-02).

Args:
  0. value 1 (-> var bank 4 slot 0 while the row is highlighted) — verified in game
  1. value 2 (-> var bank 5 slot 0) — verified in game
  2. value 3 (-> var bank 6 slot 0) — verified in game

### `op 623` — SetDialogueAutoAdvance(mode)

Make the following dialogue lines close by themselves (after a reading time or a fixed number of frames), or back to manual with 0. While on, the player cannot skip ahead.

Args:
  0. mode (0 = wait for the player; 1 = timer from the text length (7*(len/3)+30 frames); N >= 2 = close after N frames)

### `op 624` — SetDialogueHoldFrames(frames)

Stops the player from advancing or skipping the dialogue box for the given number of frames.

Args:
  0. frames (corpus always 90 (1.5 s))

### `op 698` — SetShopkeeperMessage(message)

Show a shopkeeper line in the shop menu and remember it as the current shop greeting.

Args:
  0. message (0-359, entry of text archive 15206)

### `op 699` — SetNarrationModeIf(enable)

Switch the dialogue box to narration mode (no name label, muted blips) - the mode byte op 614 also writes. 0 does nothing.

Args:
  0. enable (non-zero = switch the box to narration mode; 0 = leave the mode unchanged)

## Camera / screen

### `op 158` — SetMapAmbientColor(red, green, blue, apply_now)

Override the current map's light colour with one RGB value for every time of day (day, evening and night all get the same colour). Used with a darkening loop for dramatic scenes.

Args:
  0. red (0-255)
  1. green (0-255)
  2. blue (0-255)
  3. apply_now (non-zero = reload now; 0 = on the next map tick)

### `op 159` — ResetMapAmbientColor(apply now)

Restore the map's own ambient colours after SetMapAmbientColor (op 158) tinted them, e.g. when a darkening effect ends.

Args:
  0. apply now (non-zero = reload the palette immediately; 0 = on the next map tick)

### `op 186` — SetCameraPosition(x, y, snap)

Points the camera at a tile. With snap = 1 the camera cuts there immediately (the usual use); with 0 it only sets the target, clamped to the map's camera bounds.

Args:
  0. x (script units, 8 per tile)
  1. y (script units, 8 per tile)
  2. snap (1 = cut there now; 0 = set the target only)

### `op 187` — ReattachCameraToActor(character, snap)

Hand the camera back to the player rig after scripted camera work and, optionally, snap it straight onto a character (usually the player or the NPC just placed).

Args:
  0. character (0 = player, 1-47 NPC (slot table))
  1. snap (non-zero = hard-snap camera target/position to the character; 0 = only re-attach)

### `op 188` — HoldCameraInPlace(exact)

Stop the camera from following the player and leave it where it is, so actors can walk out of or around a fixed shot.

Args:
  0. exact (1 = keep the exact current position (corpus always 1); 0 = commit it clamped into the map's camera bounds)

### `op 189` — ResetCameraToPlayer(snap)

Gives the camera back to the player (normal follow camera). With snap = 1 it also cuts straight to the player's position, typically right after warping the player.

Args:
  0. snap (1 = also cut the camera to the player now)

### `op 190` — SetCameraTarget(x, y, speed)

Pans the camera to a tile at a constant speed. Follow with WaitCameraAtMark to hold the script until it arrives.

Args:
  0. x (script units, 8 per tile)
  1. y (script units, 8 per tile)
  2. speed (arg/100 tiles per frame, max 15; corpus 50-800, 200 and 400 typical)

### `op 191` — ResetCameraToActor(actor, speed)

Re-attach the camera to follow an actor and bring it onto that actor (snap or ease). Holds the script for a few frames while the camera settles.

Args:
  0. actor (0 = player, 1..47 NPC)
  1. speed (0 = snap camera target+position onto the actor; -1 (65535) = attach only; other = ease speed (/100 tiles per frame, same channel as op 190; 200 typical))

### `op 192` — ResetCameraToActor(actor, speed)

Re-attach the camera to follow an actor and bring it onto that actor (snap or ease). Holds the script for a few frames while the camera settles.

Args:
  0. actor (0 = player, 1..47 NPC)
  1. speed (0 = snap camera target+position onto the actor; -1 (65535) = attach only; other = ease speed (/100 tiles per frame, same channel as op 190; 200 typical))

### `op 193` — SetCameraTargetToCurrentPosition(speed)

Makes the camera's current position its target so it stops where it is. A non-zero speed first clamps that position into the map's camera bounds and eases there. Unused by the shipped scripts.

Args:
  0. speed (0 = hold exactly where it is; -1 = clamp only; other = pull back inside the bounds at arg/100 tiles per frame)

### `op 194` — FocusCameraOnPlayer(unused)

Point the camera target back at the player (clamped to the map bounds) and hold the script for 3 frames. Usually followed by WaitCameraAtMark.

Args:
  0. unused (retail passes 200/300/400; the handler reads no args)

### `op 195` — WaitCameraAtMark()

Wait until the camera has arrived at the target set by SetCameraPosition / SetCameraTarget (within half a tile on each axis). This paces scripted camera pans.

### `op 196` — WaitCameraNearMark(range)

Wait until the camera is within [range] tiles of its target on both axes: WaitCameraAtMark with a custom tolerance.

Args:
  0. range (per-axis tolerance)

### `op 197` — ShakeCamera(kind, duration)
*verified:* yes, in game

Shake the screen for a number of frames. A running shake is only replaced by an equal or stronger kind; kind 0 stops it.

Args:
  0. kind (0 stop; 1 light up-and-down, 2 up-and-down, 3 bigger up-and-down, 4 a sideways semicircle sway, 5 a strong shake in all directions, 6 nothing; 7 and above nothing visible, but WaitForPlayerEffect still waits the duration (all seen in game). A running shake is only replaced by an equal or stronger kind) — verified in game
     - `0` = stop
     - `1` = vertical_light
     - `2` = vertical
     - `3` = vertical_big
     - `4` = arc
     - `5` = strong
     - `6` = rotational
  1. duration (frames (60 = 1 s; seen in game); 0 = no limit, until ShakeCamera(0, 0) or a stronger shake) — verified in game

### `op 199` — SetCameraTargetActor(actor, speed)

Pans the camera to where an actor stands now (it does not keep following). Follow with WaitCameraAtMark.

Args:
  0. actor (0, empty slot or >= 48 = the player)
  1. speed (arg/100 tiles per frame, max 15; corpus 100-800)

### `op 200` — SetCameraTargetActor(actor, speed)

Pans the camera to where an actor stands now (it does not keep following). Follow with WaitCameraAtMark.

Args:
  0. actor (0, empty slot or >= 48 = the player)
  1. speed (arg/100 tiles per frame, max 15; corpus 100-800)

### `op 201` — SetCameraSettleMode(on)

Turns on (or off) the camera's soft landing: scripted pans slow down as they reach their target instead of stopping abruptly.

Args:
  0. on (non-zero = on, 0 = off; corpus always 1)

### `op 202` — SetCameraZoom(zoom, snap)
*verified:* yes, in game

Set the camera zoom (pull-back distance), either easing to it or snapping.

Args:
  0. zoom (larger = closer: 0 is the normal view, 200 noticeably closer, 400 close (seen in game); stored as zoom - 1500, magnification = 1 + zoom/1800) — verified in game
  1. snap (0 = glide to the new distance at a steady 8 units per frame; non-zero = jump to it at once (both seen in game)) — verified in game

### `op 203` — SetCameraMapBounds(apply_zoom)

Restore the normal map camera after scripted camera moves: re-applies the current map's camera clamp bounds and the small-map zoom.

Args:
  0. apply_zoom (0 = write the small-map camera distance into the player camera rig (work+68) only; non-zero = apply it via Camera_SetDistanceAndZoomFactor)

### `op 334` — FadeScreen(target, duration)
*verified:* yes, in game

Fade the screen to black or white (or partly). Returns at once; follow with WaitForFade to wait for it. Only the opacity fades: the colour (black / white) switches at once, so fade to white from a clear screen, not from black. Without WaitForFade the next statements run while it fades, and a later FadeScreen takes over from the current opacity. A dialogue line waits for the fade to finish but is drawn under the overlay, so fade back before showing text.

Args:
  0. target (sign = colour (<= 0 black, > 0 white), |v|/16 = opacity: -16 black, +16 white, +-8 half) — verified in game
  1. duration (frames = duration/100 (6000 = 60 frames = 1 s); 0 = immediate; 100..199 is also immediate) — verified in game

### `op 335` — FadeScreenToClear(duration)
*verified:* yes, in game

Fade the screen back in (to fully clear) over the given time, keeping the current fade colour. The reveal counterpart of FadeScreen (op 334); follow with WaitForFade to block.

Args:
  0. duration (frames = value / 100 (6000 = 60 frames = 1 s)) — verified in game

### `op 336` — SetFadeColor(red, green, blue, frames)

Set the colour the screen fades through (e.g. white 255,255,255 or black 0,0,0), either instantly or blended over a number of frames. Pair with FadeScreen.

Args:
  0. red (0-255)
  1. green (0-255)
  2. blue (0-255)
  3. frames (0 = snap; n = reach the colour over n fade-task steps)

### `op 412` — BlackScreen(to_black, duration)
*verified:* yes, in game

Fade to or from a solid black overlay and wait for the fade to finish. The overlay is separate from FadeScreen and is not removed when the scene ends: a scene that leaves it on keeps the screen black through warps and later scenes until something calls BlackScreen(0, ...) (observed in the custom opening, 2026-10-03). Shipped scenes always pair the two (101 x on, 102 x off).

Args:
  0. to_black (1 = fade to black, 0 = fade back from black) — verified in game
  1. duration (fade length handed to FadeTask_Init (15/30/60/180 in the corpus); 0 or -1 = immediate) — verified in game

### `op 595` — SetMinimapMarker(target)

Show a marker on the minimap (value stored as its target), or clear it with -1. The scene flag it sets is cleared again when the event ends.

Args:
  0. target (value stored in the minimap marker (corpus 0 in 60 of 80 uses, 4); -1 = clear)
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 617` — ShowStaffCredits(mode)

Starts the staff-credits sequence; calling it again while the credits task runs signals it to finish.

Args:
  0. mode (0 / 1 = static variants (work flags 0x10 / 0x18); 2 or 3 = scrolling credits (identical in this handler))
     - `0` = Fade (long)
     - `1` = Fade (short)
     - `2` = Credits (bottom)
     - `3` = Credits (top)

### `op 618` — WaitStaffCreditsDone()

Wait until the staff-credits roll started by ShowStaffCredits (op 617) has finished.

### `op 653` — ShowLumberCounter()
*verified:* yes, in game

Make the lumber counter in the screen corner slide in and show the player's current amount (it slides away again after a few seconds). To have it visible during a scene, call SetDialogueBoxMode(1) after it, before the dialogue (as the Order Symbol does); otherwise it only appears once the scene ends. Once shown during a scene it stays on screen until the scene ends.

### `op 654` — ShowStoneCounter()
*verified:* yes, in game

Make the material stone counter in the screen corner slide in and show the player's current amount (it slides away again after a few seconds). To have it visible during a scene, call SetDialogueBoxMode(1) after it, before the dialogue (as the Order Symbol does); otherwise it only appears once the scene ends. Once shown during a scene it stays on screen until the scene ends.

### `op 655` — ShowPrincePointCounter()
*verified:* yes, in game

Make the Prince Points counter in the screen corner slide in and show the player's current amount (it slides away again after a few seconds). To have it visible during a scene, call SetDialogueBoxMode(1) after it, before the dialogue (as the Order Symbol does); otherwise it only appears once the scene ends. Once shown during a scene it stays on screen until the scene ends.

### `op 656` — SetMapScrollSpeedX(speed, snap)

Set how fast the map's scrolling layer moves horizontally (the cloud sky on the airship deck); 0 stops it. Op 657 is the vertical channel.

Args:
  0. speed (UV scroll per frame x 10000 (-200 = -0.02))
  1. snap (1 = jump to the new speed, 0 = ease towards it)

### `op 657` — SetMapScrollSpeedY(speed, snap)

Set the Y speed of the map's scrolling texture layer (e.g. flowing water). Unused by the shipped scripts.

Args:
  0. speed (target Y scroll speed * 10000)
  1. snap (non-zero = jump to it, 0 = ease)

### `op 683` — PlayCutsceneVideo(video)
*verified:* yes, in game

Play a full-motion video. If a dialogue box is still open, it is closed first and the op waits.

Args:
  0. video (0-38 (the shipped scripts pass reg0); the file comes from a switch in the exe; ids 19 and 20 both play Rune4_s23_t1 (there is no s22); other ids pick no valid file) — verified in game
     - `0` = opening_a
     - `1` = opening_b
     - `2` = s05
     - `3` = s06
     - `4` = s07
     - `5` = s08
     - `6` = s09
     - `7` = s10
     - `8` = s11
     - `9` = s12
     - `10` = s13
     - `11` = s14
     - `12` = s15
     - `13` = s16
     - `14` = s17
     - `15` = s18
     - `16` = s19
     - `17` = s20
     - `18` = s21
     - `19` = s23
     - `20` = s23_2
     - `21` = s24
     - `22` = s25
     - `23` = s26
     - `24` = s27
     - `25` = s28
     - `26` = s29
     - `27` = m01_viznar
     - `28` = m02_clorica
     - `29` = m04_forte
     - `30` = m05_keel
     - `31` = m07_marguerite
     - `32` = m08_dirus
     - `33` = m09_arthur
     - `34` = m11_syaopai
     - `35` = m13_kohaku
     - `36` = m15_dag
     - `37` = m17_dolce
     - `38` = m20_leon

### `op 685` — SetFreeLookCameraMode(mode)

Control the free-look camera task: enable stick control, exit or pause it.

Args:
  0. mode (0 = default, 1 = stick/d-pad drives the free-look camera, 2 = exit (sfx 0x100223F, word reset, task paused), 3 = pause without reset)

### `op 687` — RebuildMinimap()

Rebuild the minimap for the current map, e.g. after a bridge or gate flag changed.

### `op 688` — ToggleMinimap(visible)

Shows or hides the minimap (with its fade).

Args:
  0. visible (non-zero = show, 0 = hide)

## Actors & player

### `op 85` — SetPortraitTargetY(character, target_y)

Move a speaker portrait vertically: sets a target screen y that the portrait eases toward (1/4 of the remaining distance per frame).

Args:
  0. character (character shown in one of the two portrait slots; no-op if neither matches)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. target_y (0 = no easing (y holds))

### `op 86` — SetPortraitTargetY(character, target_y)

Move a speaker portrait vertically: sets a target screen y that the portrait eases toward (1/4 of the remaining distance per frame).

Args:
  0. character (character shown in one of the two portrait slots; no-op if neither matches)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. target_y (0 = no easing (y holds))

### `op 87` — JoltPortraitY(character, jolt)

Give a speaker portrait a quick vertical jolt (a hop or drop that springs back), e.g. when a character is startled.

Args:
  0. character (character shown in one of the two portrait slots; no-op if neither matches)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. jolt (extra y offset, halves toward 0 every frame)

### `op 88` — JoltPortraitY(character, jolt)

Give a speaker portrait a quick vertical jolt (a hop or drop that springs back), e.g. when a character is startled.

Args:
  0. character (character shown in one of the two portrait slots; no-op if neither matches)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. jolt (extra y offset, halves toward 0 every frame)

### `op 99` — TeleportActor(actor, x, y)
*verified:* yes, in game

Instantly puts an actor (player or NPC) on a spot, without a walk animation. An NPC is loaded into the map if needed.

Args:
  0. actor (ids >= 48 ignored) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (script units, 8 per tile; +x = right, +y = down (toward the camera)) — verified in game
  2. y (script units, 8 per tile; +x = right, +y = down (toward the camera)) — verified in game

### `op 100` — TeleportActor(actor, x, y)

Instantly puts an actor (player or NPC) on a tile, without a walk animation. An NPC is loaded into the map if needed.

Args:
  0. actor (ids >= 48 ignored) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (script units, 8 per tile; +x = right, +y = down (toward the camera)) — verified in game
  2. y (script units, 8 per tile; +x = right, +y = down (toward the camera)) — verified in game

### `op 101` — PlaceActorAndFace(actor, x, y, facing)
*verified:* yes, in game

Teleport an actor to a spot and set its facing instantly. Streams the NPC into the map if it is not loaded yet.

Args:
  0. actor (0 = player, 1..47 NPC; >= 48 = no-op) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (script units, 8 per tile; +x = right, +y = down (toward the camera)) — verified in game
  2. y (script units, 8 per tile; +x = right, +y = down (toward the camera)) — verified in game
  3. facing (0-359 degrees, counter-clockwise on screen: 0 = facing down (toward the camera), 90 = right, 180 = up (away), 270 = left (seen in game 2026-10-06)) — verified in game

### `op 102` — PlaceActorAndFace(actor, x, y, facing)

Teleport an actor to a tile and set its facing instantly. Streams the NPC into the map if it is not loaded yet.

Args:
  0. actor (0 = player, 1..47 NPC; >= 48 = no-op) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (script units, 8 per tile; +x = right, +y = down (toward the camera)) — verified in game
  2. y (script units, 8 per tile; +x = right, +y = down (toward the camera)) — verified in game
  3. facing (0-359 degrees, counter-clockwise on screen: 0 = facing down (toward the camera), 90 = right, 180 = up (away), 270 = left (seen in game 2026-10-06)) — verified in game

### `op 103` — TurnActorToAngle(actor, facing, ease)
*verified:* yes, in game

Turn an actor (player or NPC) to a fixed compass direction, either instantly or easing toward it. Pair with WaitActorMoveDone (op 129) / WaitPlayerMoveDone (op 145) to wait for the turn.

Args:
  0. actor (0 = player, 1-47 = NPC/villager char id (see the character table); >= 48 ignored) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. facing (0-359 degrees, counter-clockwise on screen: 0 = facing down (toward the camera), 90 = right, 180 = up (away), 270 = left (seen in game 2026-10-06)) — verified in game
  2. ease (0 = snap instantly; n = each frame close 1/2^n of the remaining angle (2 = a quarter per frame)) — verified in game

### `op 104` — TurnActorToAngle(actor, facing, ease)

Turn an actor (player or NPC) to a fixed compass direction, either instantly or easing toward it. Pair with WaitActorMoveDone (op 129) / WaitPlayerMoveDone (op 145) to wait for the turn.

Args:
  0. actor (0 = player, 1-47 = NPC/villager char id (see the character table); >= 48 ignored) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. facing (0-359 degrees, counter-clockwise on screen: 0 = facing down (toward the camera), 90 = right, 180 = up (away), 270 = left (seen in game 2026-10-06)) — verified in game
  2. ease (0 = snap instantly; n = each frame close 1/2^n of the remaining angle (2 = a quarter per frame)) — verified in game

### `op 106` — RotateActorInPlace(npc, degrees, frames)

Spins an NPC in place: turns it by the given degrees every frame for the given number of frames, and waits until done.

Args:
  0. npc (0 crashes (null actor), >= 48 no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. degrees (corpus -12..45)
  2. frames (corpus 9..120; <= 0 never finishes)

### `op 107` — TurnActorToFaceTarget(turner, target, ease)
*verified:* yes, in game

Turn one actor to look at another - the usual setup before two characters talk. The turn snaps or eases; wait for it with WaitActorMoveDone (op 129) / WaitPlayerMoveDone (op 145).

Args:
  0. turner (0 = player, 1-47 = NPC/villager char id (see the character table); >= 48 event actor / monster) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. target (same encoding (0 = player)) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  2. ease (0 = snap; n = close 1/2^n of the remaining angle per frame (corpus mostly 2)) — verified in game

### `op 108` — TurnActorToFaceTarget(turner, target, ease)

Turn one actor to look at another - the usual setup before two characters talk. The turn snaps or eases; wait for it with WaitActorMoveDone (op 129) / WaitPlayerMoveDone (op 145).

Args:
  0. turner (0 = player, 1-47 = NPC/villager char id (see the character table); >= 48 event actor / monster) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. target (same encoding (0 = player)) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  2. ease (0 = snap; n = close 1/2^n of the remaining angle per frame (corpus mostly 2)) — verified in game

### `op 109` — TurnActorToFaceTarget(turner, target, ease)

Turn one actor to look at another - the usual setup before two characters talk. The turn snaps or eases; wait for it with WaitActorMoveDone (op 129) / WaitPlayerMoveDone (op 145).

Args:
  0. turner (0 = player, 1-47 = NPC/villager char id (see the character table); >= 48 event actor / monster) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. target (same encoding (0 = player)) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  2. ease (0 = snap; n = close 1/2^n of the remaining angle per frame (corpus mostly 2)) — verified in game

### `op 110` — FaceEventActor(actor, event_actor, ease)

Turns an actor (player or NPC) to face an event actor, i.e. a monster or prop the scene registered under an event key. Does not wait; follow with WaitActorMoveDone / WaitPlayerMoveDone.

Args:
  0. actor (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. event_actor (corpus 100-306 (e.g. 100, 200, 300 = monsters/props registered by the event))
  2. ease (0 = snap, 1-3 = ease (2 in 101 of 113 uses))

### `op 111` — SetActorAuxYaw(actor, angle)

Sets the target of an actor's secondary yaw (a second rotation separate from the body facing that TurnActorToAngle changes); the engine eases towards it. Scenes use it after an emote to make a character glance aside and back (60 then 0). Pair with WaitActorAuxYaw.

Args:
  0. actor (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. angle (target of the secondary yaw; corpus 0, +/-30..60, 315-340)

### `op 112` — SetActorAuxYaw(actor, angle)

Sets the target of an actor's secondary yaw (a second rotation separate from the body facing that TurnActorToAngle changes); the engine eases towards it. Scenes use it after an emote to make a character glance aside and back (60 then 0). Pair with WaitActorAuxYaw.

Args:
  0. actor (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. angle (target of the secondary yaw; corpus 0, +/-30..60, 315-340)

### `op 113` — WaitActorAuxYaw(actor)

Waits until the actor's secondary yaw has reached the target set by SetActorAuxYaw.

Args:
  0. actor (>= 48 or missing actor = no wait)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
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

Waits until the actor's secondary yaw has reached the target set by SetActorAuxYaw.

Args:
  0. actor (>= 48 or missing actor = no wait)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 115` — WalkActorToAndFace(actor, x, y, facing, speed, jump)

Walk an actor to an absolute position and turn it to the given facing at the end. Returns at once; follow with WaitActorMoveDone to wait for arrival. Like every NPC move op it marks the NPC scene-controlled, so its schedule does not move it again until the scene ends.

Args:
  0. actor (0 = player, 1..47 NPC; >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (script units, 8 per tile)
  2. y (script units, 8 per tile)
  3. facing (facing the move command ends with)
  4. speed (100 = normal walk (x 167773/4096 internal scale))
  5. jump (non-zero = run/jump: speed x1.2 and jump bit 0x800000)

### `op 116` — WalkActorToAndFace(actor, x, y, facing, speed, jump)

Walk an actor to an absolute position and turn it to the given facing at the end. Returns at once; follow with WaitActorMoveDone to wait for arrival. Like every NPC move op it marks the NPC scene-controlled, so its schedule does not move it again until the scene ends.

Args:
  0. actor (0 = player, 1..47 NPC; >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (script units, 8 per tile)
  2. y (script units, 8 per tile)
  3. facing (facing the move command ends with)
  4. speed (100 = normal walk (x 167773/4096 internal scale))
  5. jump (non-zero = run/jump: speed x1.2 and jump bit 0x800000)

### `op 117` — WalkActorTo(actor, x, y, speed, jump)

Walks an NPC to an absolute position, turning to face the way it walks (no end facing). Does not wait; follow with WaitActorMoveDone.

Args:
  0. actor — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (script units, 8 per tile) — verified in game
  2. y (script units, 8 per tile) — verified in game
  3. speed (corpus 30-400, 100 typical) — verified in game
  4. jump (0 = walk, non-zero = jump/run gait, speed x1.2)

### `op 118` — WalkActorTo(actor, x, y, speed, jump)

Walks an NPC to an absolute position, turning to face the way it walks (no end facing). Does not wait; follow with WaitActorMoveDone.

Args:
  0. actor — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (script units, 8 per tile) — verified in game
  2. y (script units, 8 per tile) — verified in game
  3. speed (corpus 30-400, 100 typical) — verified in game
  4. jump (0 = walk, non-zero = jump/run gait, speed x1.2)

### `op 119` — StepNpcTo(npc, x, y, speed, jump)

Move an NPC to an absolute position without turning it (side-step / back-pedal), then lock its AI. Returns at once; use WaitActorMoveDone to wait.

Args:
  0. npc (1..47 (NPC table; no player branch); >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (script units, 8 per tile)
  2. y (script units, 8 per tile)
  3. speed (100 = normal walk)
  4. jump (non-zero = run/jump: speed x1.2 and jump bit)

### `op 120` — StepNpcTo(npc, x, y, speed, jump)

Move an NPC to an absolute position without turning it (side-step / back-pedal), then lock its AI. Returns at once; use WaitActorMoveDone to wait.

Args:
  0. npc (1..47 (NPC table; no player branch); >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (script units, 8 per tile)
  2. y (script units, 8 per tile)
  3. speed (100 = normal walk)
  4. jump (non-zero = run/jump: speed x1.2 and jump bit)

### `op 121` — MoveNpcToPosKeepAnim(npc, x, y, speed)

Moves an NPC to an absolute position while keeping the animation that is currently playing (e.g. a knocked-back or flying pose started with PlayActorAnim), instead of switching to the walk cycle.

Args:
  0. npc
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (script units, 8 per tile)
  2. y (script units, 8 per tile)
  3. speed (corpus 17-800)

### `op 122` — MoveNpcToPosKeepAnim(npc, x, y, speed)

Moves an NPC to an absolute position while keeping the animation that is currently playing (e.g. a knocked-back or flying pose started with PlayActorAnim), instead of switching to the walk cycle.

Args:
  0. npc
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. x (script units, 8 per tile)
  2. y (script units, 8 per tile)
  3. speed (corpus 17-800)

### `op 123` — MoveActorByOffset(actor, dx, dy, facing, speed, jump)

Walks an actor (player or NPC) by a relative offset in script units (8 per tile) from where it stands and turns it to the given facing at the end. Does not wait.

Args:
  0. actor (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (relative; 8 per tile)
  2. dy (relative; 8 per tile)
  3. facing (end facing (0/90/180/270 ...))
  4. speed (corpus 100-150)
  5. jump (0 = walk, non-zero = jump/run gait, speed x1.2)

### `op 124` — MoveActorByOffset(actor, dx, dy, facing, speed, jump)

Walks an actor (player or NPC) by a relative offset in script units (8 per tile) from where it stands and turns it to the given facing at the end. Does not wait.

Args:
  0. actor (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (relative; 8 per tile)
  2. dy (relative; 8 per tile)
  3. facing (end facing (0/90/180/270 ...))
  4. speed (corpus 100-150)
  5. jump (0 = walk, non-zero = jump/run gait, speed x1.2)

### `op 125` — MoveActorByOffsetFaceTravel(actor, dx, dy, speed, jump)

Walks an actor (player or NPC) by a relative offset in script units (8 per tile), facing the way it walks. Does not wait.

Args:
  0. actor (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (relative; 8 per tile)
  2. dy (relative; 8 per tile)
  3. speed (corpus 15-400, 100 typical)
  4. jump (0 = walk, non-zero = jump/run gait, speed x1.2)

### `op 126` — MoveActorByOffsetFaceTravel(actor, dx, dy, speed, jump)

Walks an actor (player or NPC) by a relative offset in script units (8 per tile), facing the way it walks. Does not wait.

Args:
  0. actor (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (relative; 8 per tile)
  2. dy (relative; 8 per tile)
  3. speed (corpus 15-400, 100 typical)
  4. jump (0 = walk, non-zero = jump/run gait, speed x1.2)

### `op 127` — MoveActorByOffsetKeepFacing(actor, dx, dy, speed, jump)

Moves an actor (player or NPC) by a relative offset in script units (8 per tile) while keeping its current facing, e.g. a step back or a side-step. Does not wait.

Args:
  0. actor (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (relative; 8 per tile)
  2. dy (relative; 8 per tile)
  3. speed (corpus 50-350)
  4. jump (0 = walk, non-zero = jump/run gait, speed x1.2)

### `op 128` — MoveActorByOffsetKeepFacing(actor, dx, dy, speed, jump)

Moves an actor (player or NPC) by a relative offset in script units (8 per tile) while keeping its current facing, e.g. a step back or a side-step. Does not wait.

Args:
  0. actor (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. dx (relative; 8 per tile)
  2. dy (relative; 8 per tile)
  3. speed (corpus 50-350)
  4. jump (0 = walk, non-zero = jump/run gait, speed x1.2)

### `op 129` — WaitActorMoveDone(actor, ignored...)

Wait until an actor has finished its scripted move and any pending turn. Put it after Move*/Turn* ops. For actor 0 it waits on the player (same as WaitPlayerMoveDone (op 145)).

Args:
  0. actor (0 = player, 1-47 = NPC/villager char id (see the character table)) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. ignored... (extra args are accepted but never read (corpus has up to 6))

### `op 130` — WaitActorMoveDone(actor, ignored...)

Wait until an actor has finished its scripted move and any pending turn. Put it after Move*/Turn* ops. For actor 0 it waits on the player (same as WaitPlayerMoveDone (op 145)).

Args:
  0. actor (0 = player, 1-47 = NPC/villager char id (see the character table)) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. ignored... (extra args are accepted but never read (corpus has up to 6))

### `op 131` — WaitActorNearMoveTarget(actor, range)

Wait until an actor has come within [range] tiles of the destination of its current move, so the script can chain the next waypoint before the actor stops.

Args:
  0. actor (0 = player, 1..47 NPC; >= 48 = no wait)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. range (octagonal distance, same units as the move x/y)

### `op 132` — WaitActorNearMoveTarget(actor, range)

Wait until an actor has come within [range] tiles of the destination of its current move, so the script can chain the next waypoint before the actor stops.

Args:
  0. actor (0 = player, 1..47 NPC; >= 48 = no wait)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. range (octagonal distance, same units as the move x/y)

### `op 133` — PlayActorAnim(actor, anim, loop)

Play an animation clip on an actor, looping or once. Anim id 1 returns the actor to its default idle behaviour. For the player it first enters the scripted-talk state.

Args:
  0. actor (0 = player, 1..47 NPC; >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. anim (clip index into the shared 00_/00W_NNN_*.bfskl sets; 1 = hand back to the actor's default behaviour (calls actor+0x48))
  2. loop (non-zero sets scene_node flag 4 (loop/hold); 0 clears it for NPCs only)

### `op 134` — PlayActorAnim(actor, anim, loop)

Play an animation clip on an actor, looping or once. Anim id 1 returns the actor to its default idle behaviour. For the player it first enters the scripted-talk state.

Args:
  0. actor (0 = player, 1..47 NPC; >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. anim (clip index into the shared 00_/00W_NNN_*.bfskl sets; 1 = hand back to the actor's default behaviour (calls actor+0x48))
  2. loop (non-zero sets scene_node flag 4 (loop/hold); 0 clears it for NPCs only)

### `op 137` — WaitActorAnimDone(npc)

Wait until an NPC's current one-shot animation (e.g. after PlayActorAnim or HandOrDropItem) has finished. Returns immediately if the NPC is not spawned.

Args:
  0. npc (1-47 NPC (0 resolves NPC slot 0, not the player))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 138` — WaitActorAnimDone(npc)

Wait until an NPC's current one-shot animation (e.g. after PlayActorAnim or HandOrDropItem) has finished. Returns immediately if the NPC is not spawned.

Args:
  0. npc (1-47 NPC (0 resolves NPC slot 0, not the player))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 141` — SetActorOpacity(actor, opacity)

Fade or hide an actor's model: 0 hides it, any other value shows it at that opacity percent.

Args:
  0. actor (0 = player, 1..47 NPC; >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. opacity (0 = hide (sets hidden bit, alpha untouched); 1..100 = show at that opacity)

### `op 142` — WalkPlayerToAndFace(x, y, facing, speed, run)

Walk or run the player to an absolute position, then turn to the given facing. Wait with WaitPlayerMoveDone (op 145).

Args:
  0. x (script units, 8 per tile)
  1. y (script units, 8 per tile)
  2. facing (end facing after arriving)
  3. speed (internal = speed x 40.96 (x1.2 when running); corpus 50-300)
  4. run (0 = walk, non-zero = run animation and +20% speed)

### `op 143` — WalkPlayerTo(x, y, speed, run)

Walk or run the player to an absolute position, facing the direction of travel (no end facing). Wait with WaitPlayerMoveDone (op 145).

Args:
  0. x (script units, 8 per tile)
  1. y (script units, 8 per tile)
  2. speed (x40.96 internal, x1.2 when running)
  3. run (0 = walk, non-zero = run)

### `op 144` — StepPlayerTo(x, y, speed, run)

Move the player in a straight line to an absolute position without turning (keeps the current facing, e.g. backing away or side-stepping). Wait with WaitPlayerMoveDone (op 145).

Args:
  0. x (script units, 8 per tile)
  1. y (script units, 8 per tile)
  2. speed (x40.96 internal, x1.2 when running; corpus 30-500)
  3. run (0 = walk, non-zero = run)

### `op 145` — WaitPlayerMoveDone()
*verified:* yes, in game

Wait until the player has finished a scripted move (ops 142-144) and any pending scripted turn (TurnActorToAngle / TurnActorToFaceTarget on actor 0). The player counterpart of WaitActorMoveDone (op 129).

### `op 147` — RestorePlayerEquip()

Undo a scripted EquipItemToPlayer (op 146): put back the item that op 146 stashed and return the player to idle.

### `op 149` — PlayPlayerAnim(anim, loop)

Play an animation on the player during a cutscene (entering scripted-talk mode first if needed). Anim 1 returns the player to the default idle. Wait for one-shot clips with op 152.

Args:
  0. anim (1-based clip ordinal in the player's clip set; 1 = hand back to default behaviour; -1 = 187)
  1. loop (non-zero sets the loop bit; 0 leaves the bit unchanged)

### `op 152` — WaitPlayerAnimDone()

Waits until the player's current one-shot animation (started with the player talk/anim ops) has finished.

### `op 153` — SpawnEventActor(char, key, x, y, facing)

Spawn an event (cutscene) actor under a scene-local key, or reposition it if that key already exists. Later event-actor ops address it by the key. x / y are script units: 8 per map-editor tile, so tile (40, 15) is (320, 120), its centre (324, 124) (in game: a Captain spawned with (324, 124) stood on tile (40, 15) of Leon Karnak D19).

Args:
  0. char (character/NPC-param id incl. monsters and props (e.g. 269, 27, 324 'Barrel', 331 'Captain'); 254..266 ignored)
     - *(enum: 392 values — use the in-editor picker or the id database)*
  1. key (scene-local handle (100, 101, 200, 300...) used by every later EventActor op)
  2. x (script units, 8 per map-editor tile (tile * 8 + 4 = the tile's centre))
  3. y (script units, 8 per map-editor tile (tile * 8 + 4 = the tile's centre))
  4. facing

### `op 154` — SpawnEventActorVariant(char, event_key, x, y, facing, variant)

Registers a new event actor (a scene extra such as a monster or crowd member) under an event key at a tile, with a variant index. Later event-actor ops address it by the key.

Args:
  0. char (48+ (monsters, extras); 254-266 are filtered (no-op))
     - *(enum: 392 values — use the in-editor picker or the id database)*
  1. event_key (the scene-local key given when the event actor was spawned (corpus 100-306))
  2. x
  3. y
  4. facing
  5. variant (stored as variant-1; corpus 1-180 and registers)

### `op 155` — SpawnEventActorEx(char, event_key, x, y, facing, flag, scalar)

Registers a new event actor like SpawnEventActorVariant but with an extra flag and a percentage value whose effect is not identified. Only used for character 215 in two scenes.

Args:
  0. char (254-266 filtered)
     - *(enum: 392 values — use the in-editor picker or the id database)*
  1. event_key (the scene-local key given when the event actor was spawned (corpus 100-306))
  2. x
  3. y
  4. facing
  5. flag (only bit 0 is used -> record word5 bit 14)
  6. scalar (stored as float arg*0.01 at record +16; corpus 0/100)

### `op 156` — UnregisterEventActor(char, event_key)

Removes an event actor that matches both the character id and the event key; the engine despawns it on its next sweep. No death animation (compare KillEventActor).

Args:
  0. char
     - *(enum: 392 values — use the in-editor picker or the id database)*
  1. event_key (the scene-local key given when the event actor was spawned (corpus 100-306))

### `op 160` — WalkEventActorTo(key, x, y, speed, run)

Walk or run an event actor to an absolute position. Updates the move if one is already in progress. Returns at once; use WaitEventActorMoveDone to wait.

Args:
  0. key
  1. x (script units, 8 per tile)
  2. y (script units, 8 per tile)
  3. speed (100 = the actor's base walk/run speed)
  4. run (0 = walk speed base (+368), 1 = run speed base (+372))

### `op 161` — StepEventActorTo(key, x, y, speed, run)

Like WalkEventActorTo but the actor keeps its current facing while moving (side-step / back-pedal).

Args:
  0. key
  1. x (script units, 8 per tile)
  2. y (script units, 8 per tile)
  3. speed (100 = base speed)
  4. run

### `op 162` — TurnEventActorToAngle(key, facing, ease)

Turn an event actor to a facing (degrees), instantly or eased. Pair with WaitEventActorMoveDone to wait for the turn.

Args:
  0. key
  1. facing
  2. ease (turn easing: each frame the facing moves by remaining >> ease; 0 = snap, 2 = typical smooth turn)

### `op 163` — TurnEventActorToFaceTarget(event_key, target, ease)

Turns an event actor to face the player or an NPC.

Args:
  0. event_key (the scene-local key given when the event actor was spawned (corpus 100-306))
  1. target (0 = player, 1-47 NPC; >= 48 unsupported (uninitialised pointer))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  2. ease (0 = snap, 1-2 = ease)

### `op 164` — WaitEventActorMoveDone(event_key)

Waits until an event actor has finished walking and turning. Waiting on a key that is not registered never ends.

Args:
  0. event_key (the scene-local key given when the event actor was spawned (corpus 100-306))

### `op 167` — PlayEventActorAnim(event key, anim, loop)

Play an animation on a spawned event actor (event key 100+). Wait for a one-shot clip with WaitEventActorAnimDone (op 169).

Args:
  0. event key (100+ key used when spawning (corpus 100-352))
  1. anim (clip ordinal; 1 = default behaviour callback)
  2. loop (non-zero = loop, 0 = play once (clears the loop bit))

### `op 168` — SkipEventActorAnimToEnd(key)

Jump an event actor's current animation to its last frame, so a pose just started (e.g. lying down) shows its end pose at once. The event-actor twin of SkipActorAnimToEnd (op 250).

Args:
  0. key

### `op 169` — WaitEventActorAnimDone(event_key)

Waits until an event actor's current one-shot animation (started with PlayEventActorAnim) has finished. A missing key waits forever.

Args:
  0. event_key (the scene-local key given when the event actor was spawned (corpus 100-306))

### `op 170` — SetEventActorAnimSpeed(event_key, speed_percent)

Set a spawned event actor's animation playback speed in percent (0 freezes the current pose). Movement speed is not affected.

Args:
  0. event_key (key given to SpawnEventActor (100-204 in the corpus))
  1. speed_percent (100 = normal, 50 = half, 0 = freeze the pose)

### `op 171` — SetEventActorAlpha(event_key, alpha_percent)

Make a spawned event actor translucent (1-100 % opacity) or hide it (0). Used for ghosts and fade-in/out effects, often in a loop with a register.

Args:
  0. event_key (key given to SpawnEventActor)
  1. alpha_percent (1-100 = opacity; 0 = hide the actor)

### `op 172` — ShowEventActorEmote(event_key, emote)

Shows an emote icon (surprise, sweat, heart...) over an event actor, with a sound for some icons; 0 clears it.

Args:
  0. event_key (the scene-local key given when the event actor was spawned (corpus 100-306))
  1. emote (0 = clear; corpus 1-27, mostly 6 and 15)

### `op 173` — SetEventActorInScriptFlag(event_key)

Mark a spawned event actor (typically a monster) as under script control, so its monster AI takes its scripted branch. There is no op that clears the mark.

Args:
  0. event_key (key given to SpawnEventActor)

### `op 174` — AddActorHeightOffset(actor, delta)

Raise or lower a character's drawn height by a delta (negative = up). Unless the actor is flagged airborne the result is clamped so it cannot go below ground. Scripts lift with -64 and then add 8 per frame to drop back down.

Args:
  0. actor (0 = player, 1-47 NPC, > 48 event key (48 finds nothing and blocks))
  1. delta (negative = up (-64 lifts one tile-ish), positive = down)

### `op 175` — SetEventActorHeight(event key, height)

Set a spawned event actor's height: where its overhead widgets, effects and damage numbers are placed.

Args:
  0. event key
  1. height (height above the actor (corpus 36))

### `op 176` — SetEventActorScale(event_key, scale)

Sets the uniform model scale of an event actor in percent (100 = normal).

Args:
  0. event_key (the key the event actor was spawned with)
  1. scale (100 = normal size, 50 = half)

### `op 177` — EnableEventActorWandering(event key, unused)
*verified:* yes, in game

Let a spawned event actor wander on its own: it stands in its idle animation for 90-217 frames, then walks in a random direction for 30-93 frames, and repeats, turning back when it strays about 42 tiles from where it stood when this op ran. Used right after SpawnEventActor / TurnEventActorIntoNpc for animals that should roam (the captive Woolies in Idra Cave B1). Leave it out to keep the actor standing still.

Args:
  0. event key — verified in game
  1. unused (shipped scripts pass 1; never read) — verified in game

### `op 178` — SetEventActorAuxYaw(event_key, angle)

Sets the target of an event actor's secondary yaw, the same rotation SetActorAuxYaw sets for roster actors (not the body facing that TurnEventActorToAngle changes). The engine eases towards it; the corpus uses it to make a character glance left and right.

Args:
  0. event_key (the key the event actor was spawned with)
  1. angle (target of the secondary yaw; corpus 350, 30, 0)

### `op 179` — WaitEventActorAuxYaw(key)

Wait until an event actor has finished turning to the angle set with SetEventActorAuxYaw (op 178). The event-actor twin of WaitActorAuxYaw (op 113).

Args:
  0. key

### `op 180` — KillEventActor(event_key)

Kills an event actor on the spot: it plays its death animation, is knocked back, falls and is removed.

Args:
  0. event_key (the key the event actor was spawned with)

### `op 181` — TurnEventActorIntoNpc(event_key)
*verified:* yes, in game

Turn a spawned event actor into a peaceful, talkable NPC-like prop: it stops fighting altogether (no attacks on the player, no retaliation when hit, no attacks on other monsters), keeps its idle animation and stays where it is, and the player can now interact with it. Which scene talking runs is chosen by the actor's EVENT KEY: the type-2 entry with that key in the map's tail bank, then the primary bank, then the global bank (no entry = nothing happens). It is NOT removed, gets no villager features (schedule, gifts, friendship) and does not join the party. The shipped scripts call it right after SpawnEventActor for mounts and extras (e.g. Ventuswill in bank 216 before MountActor). To remove an event actor use KillEventActor or UnregisterEventActor.

Args:
  0. event_key (key given to SpawnEventActor) — verified in game

### `op 183` — SetActorAIScript(actor, ai script)

Give an actor (usually a spawned event monster) a different monster-AI script, e.g. to make a boss start fighting or a spawned monster behave a certain way.

Args:
  0. actor (0 = player, 1-47 NPC, >= 48 event key)
  1. ai script (monster AI script id (loads archive id+1); -1 = only flag the current script)

### `op 184` — SetActorIgnoredByMonsters(target, set)

Make monsters ignore an actor (or stop ignoring it): sets or clears the status bit that monster AI skips when choosing or keeping a target.

Args:
  0. target (0 = player, 1..47 NPC, >= 48 = event key)
  1. set (non-zero sets the bit, 0 clears it)

### `op 185` — PlayActorSplash(actor)

Play the water-splash reaction on a character: a squash-and-stretch bob, the splash sound and three ripple effects.

Args:
  0. actor (0 = player, 1-47 NPC, >= 48 event key)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 206` — SetActorHeldItem(actor, item)
*verified:* yes, in game

Make an NPC hold a tool or equipment item in hand (arg 1 >= 2), restore its configured equipment (1) or clear its held tool models (0); for the player (actor 0) give the item and equip it as the weapon. It works on the NPC's equipment models, not on a hand prop given by HandOrDropItem: after HandOrDropItem(Forte, Cabbage), SetActorHeldItem(Forte, 0) left the Cabbage in her hand (she pulled it out, GetNpcHeldItem still 1, in game). In game: item 559 put a hoe in Forte's hand, 328 a sword, 0 emptied it, 1 restored her own equipment (and her gifted White Ribbon appeared on her head).

Args:
  0. actor (0 = player, 1-47 = NPC/villager char id (see the character table)) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. item (item to hold; 0 = remove; NPC only: 1 = its default equipment) — verified in game
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 207` — SetActorHeldItem(actor, item)
*verified:* yes, in game

Make an NPC hold an item in their hand (or put it away), or give the player an item and equip it as their weapon. Used when a character pulls out a tool or hands something over.

Args:
  0. actor (0 = player, 1-47 = NPC/villager char id (see the character table)) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. item (item to hold; 0 = remove; NPC only: 1 = its default equipment) — verified in game
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 211` — ShowActorEmote(actor, icon)
*verified:* yes, in game

Show an emote balloon icon over an actor (the player or an NPC), with a sound for some icons. Icons: 1 heart, 2 bones, 3 annoyed (scribble), 4 note, 5 notes, 6 '!', 7 '?', 8 '!?', 9 sweat, 10 anger mark, 11 blush, 12 turnip, 13 Zzz, 14 light bulb, 15 '…', 22 bones (stays longer), 23 bad mood (scribble), 24 sleepy (growing Z), 25 treasure chest, 26 nothing (pauses the actor's action), 27 heart (pops in), 28 bones; any other id shows the anger mark; 0 clears it. All seen in game.

Args:
  0. actor (0 = player, -1 = the current interaction NPC, 1..47 NPC) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. icon (0 = none; 1-15 and 22-28 = the icons listed under value names (all seen in game); any other id (seen: 16-21, 29, 99) draws the anger mark like 10 (ActionConstructor_EmotionIcon RF4S.exe+0xC6920 starts from archive 2129, the anger mark, and only the listed ids replace it; the debug menu's names for 16-21 -- Poison, Paralysis, Sealed, Fatigue, Cold, Healthy -- have no icon on PC); 26 shows nothing and pauses the actor's action) — verified in game
     - `0` = none
     - `1` = heart
     - `2` = bones
     - `3` = annoyed
     - `4` = note
     - `5` = notes
     - `6` = exclaim
     - `7` = question
     - `8` = exclaim_question
     - `9` = sweat
     - `10` = anger
     - `11` = blush
     - `12` = turnip
     - `13` = zzz
     - `14` = idea
     - `15` = silence
     - `22` = bones_b
     - `23` = bad_mood
     - `24` = sleepy
     - `25` = treasure
     - `26` = pause
     - `27` = heart_b
     - `28` = bones_c

### `op 212` — ShowActorEmote(actor, icon)
*verified:* yes, in game

Show an emote balloon icon over an actor (the player or an NPC), with a sound for some icons. Icons: 1 heart, 2 bones, 3 annoyed (scribble), 4 note, 5 notes, 6 '!', 7 '?', 8 '!?', 9 sweat, 10 anger mark, 11 blush, 12 turnip, 13 Zzz, 14 light bulb, 15 '…', 22 bones (stays longer), 23 bad mood (scribble), 24 sleepy (growing Z), 25 treasure chest, 26 nothing (pauses the actor's action), 27 heart (pops in), 28 bones; any other id shows the anger mark; 0 clears it. All seen in game.

Args:
  0. actor (0 = player, -1 = the current interaction NPC, 1..47 NPC) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. icon (0 = none; 1-15 and 22-28 = the icons listed under value names (all seen in game); any other id (seen: 16-21, 29, 99) draws the anger mark like 10 (ActionConstructor_EmotionIcon RF4S.exe+0xC6920 starts from archive 2129, the anger mark, and only the listed ids replace it; the debug menu's names for 16-21 -- Poison, Paralysis, Sealed, Fatigue, Cold, Healthy -- have no icon on PC); 26 shows nothing and pauses the actor's action) — verified in game
     - `0` = none
     - `1` = heart
     - `2` = bones
     - `3` = annoyed
     - `4` = note
     - `5` = notes
     - `6` = exclaim
     - `7` = question
     - `8` = exclaim_question
     - `9` = sweat
     - `10` = anger
     - `11` = blush
     - `12` = turnip
     - `13` = zzz
     - `14` = idea
     - `15` = silence
     - `22` = bones_b
     - `23` = bad_mood
     - `24` = sleepy
     - `25` = treasure
     - `26` = pause
     - `27` = heart_b
     - `28` = bones_c

### `op 217` — ApplyFriendshipDelta(npc, mode, amount)

Add to, subtract from, or set an NPC's friendship points. The mode is written as the add/sub/set keyword, not a number.

Args:
  0. npc (1-47; 22 = the current child (REG_CHILD_ID))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. mode (add (null leaf, kind 4) / sub (zero, kind 5) / set (self, kind 6); read from the arg's KIND slot)
  2. amount (xp to add/subtract, or the absolute points for set)

### `op 221` — AdjustCurrentNpcFriendship(mode, amount)

Changes the friendship of the NPC the player is currently interacting with: add, subtract or set, chosen by the kind of the first argument. Unused by the shipped scripts.

Args:
  0. mode (null = add XP, zero = subtract XP, self = set points; a plain number does nothing)
  1. amount

### `op 222` — LockNpcPose(npc)

Freeze an NPC for a cutscene: saves its current facing and sets the flags that stop its AI from moving or turning it on its own.

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
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

Pull an NPC out of its daily schedule for a scene (or hand it back), refreshing its schedule state immediately.

Args:
  0. npc (1..47; >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. engaged (non-zero = take the NPC out of its schedule; 0 = release it back)

### `op 224` — SetNpcEngaged(npc, engaged)

Pull an NPC out of its daily schedule for a scene (or hand it back), refreshing its schedule state immediately.

Args:
  0. npc (1..47; >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. engaged (non-zero = take the NPC out of its schedule; 0 = release it back)

### `op 225` — StreamInNpc(npc, load)

Bring an NPC's actor into the current map (or just re-apply its schedule state). Use StreamInNpcAtPos (op 246) to also place it.

Args:
  0. npc (1..47; >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. load (0 = only re-apply the schedule state; non-zero = force-load the NPC into the map)

### `op 233` — SkipNpcDailyGreeting(npc, unused)

Mark a villager's daily greeting as already played, so their next talk skips the DailyGreeting scene (entry type 22, a morning / day / evening line picked by friendship or weather) and goes straight to normal talk. It does not hide anyone. Sets two flags: GameFlags zone-2 bit 1037 + id (cleared every morning) and record +52 bit 0x20000000 (survives sleep, cleared by the next talk); the game sets the same flag itself after a greeting has played. A greeting is also skipped when the villager has a pending type-30 event, takes part in today's town event (sub-event), or has certain story flags set, so in normal play the difference is rare. Traced in game 2026-10-02 (breakpoints on the talk-start code, not yet seen on screen): flagged Clorica / Volkanon skipped the greeting lookup, unflagged Bado ran it, all else equal. The second argument is never read.

Args:
  0. npc (1..47; >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. unused (never read; the corpus always passes 1)

### `op 234` — SkipNpcDailyGreeting(npc, unused)

Mark a villager's daily greeting as already played, so their next talk skips the DailyGreeting scene (entry type 22, a morning / day / evening line picked by friendship or weather) and goes straight to normal talk. It does not hide anyone. Sets two flags: GameFlags zone-2 bit 1037 + id (cleared every morning) and record +52 bit 0x20000000 (survives sleep, cleared by the next talk); the game sets the same flag itself after a greeting has played. A greeting is also skipped when the villager has a pending type-30 event, takes part in today's town event (sub-event), or has certain story flags set, so in normal play the difference is rare. Traced in game 2026-10-02 (breakpoints on the talk-start code, not yet seen on screen): flagged Clorica / Volkanon skipped the greeting lookup, unflagged Bado ran it, all else equal. The second argument is never read.

Args:
  0. npc (1..47; >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. unused (never read; the corpus always passes 1)

### `op 244` — ShowNpcHeldItem(npc)

Make an NPC hold up the item in its hand (after HandOrDropItem); if it is already in the show pose, it puts the item away and returns to normal instead. Does nothing when the NPC holds no item.

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 246` — StreamInNpcAtPos(npc, map, x, y)

Brings an NPC onto a map and places it on a spot at once (no walk-in), resetting it to its idle pose.

Args:
  0. npc (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. map (corpus: map(MAP_X) constants)
  2. x (script units, 8 per tile)
  3. y (script units, 8 per tile)

### `op 248` — SetNpcVisibleFlag(npc, visible)

Set or clear an NPC's record bit 0x800 (+52), used together with SetNpcVisible when an NPC leaves a scene. What the bit gates was not traced.

Args:
  0. npc (1..47; >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. visible (0 sets npc record +52 bit 0x800, non-zero clears it)

### `op 249` — SetNpcVisibleFlag(npc, visible)

Set or clear an NPC's record bit 0x800 (+52), used together with SetNpcVisible when an NPC leaves a scene. What the bit gates was not traced.

Args:
  0. npc (1..47; >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. visible (0 sets npc record +52 bit 0x800, non-zero clears it)

### `op 250` — SkipActorAnimToEnd(actor)

Jump an actor's current animation to its last frame, so a pose just started (e.g. lying down, sitting) shows its end pose at once.

Args:
  0. actor (0 = player, 1..47 NPC)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 251` — SkipActorAnimToEnd(actor)

Jump an actor's current animation to its last frame, so a pose just started (e.g. lying down, sitting) shows its end pose at once.

Args:
  0. actor (0 = player, 1..47 NPC)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 252` — SetActorAnimSpeedScale(actor, speed)

Set how fast an actor's animation plays (percent). 0 freezes the current pose. The actor counterpart of SetEventActorAnimSpeed (op 170).

Args:
  0. actor (0 = player, 1-47 = NPC/villager char id (see the character table))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. speed (100 = normal, 50 = half, 0 = frozen, 200 = double)

### `op 253` — SetActorAnimSpeedScale(actor, speed)

Set how fast an actor's animation plays (percent). 0 freezes the current pose. The actor counterpart of SetEventActorAnimSpeed (op 170).

Args:
  0. actor (0 = player, 1-47 = NPC/villager char id (see the character table))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. speed (100 = normal, 50 = half, 0 = frozen, 200 = double)

### `op 254` — SetActorAnimFrame(actor, frame)

Jump an actor's current animation to a given frame (no blending); combine with SetActorAnimSpeedScale(actor, 0) to hold a pose.

Args:
  0. actor (0 = player, 1-47 = NPC/villager char id (see the character table))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. frame (frame of the current clip)

### `op 256` — SetActorStatusConditions(target, action)

Cure or inflict status ailments on the player or a companion. Retail only uses it to cure (action 0 or 4) before story battles.

Args:
  0. target (0 = player, 2 = companion 1, 3 = companion 2, other = the companion whose char id matches the current interaction NPC)
  1. action (0 = clear 0x2F (poison/seal/paralysis/sleep + cold; keeps fatigue 0x10), 1 = set 0x2F, 2 = set cold 0x20, 3 = clear 0x0F, 4 = clear fatigue+cold 0x30; other = nothing)

### `op 261` — SetNpcRecordFlag80000000(npcs)

Set bit 0x80000000 of the listed NPCs' record word +52 (or of all villagers 1..23 when arg0 is 0). What the bit does is not known.

Args:
  0. npcs (arg0 = 0: all villagers 1..23; otherwise every arg (count from argc) is a char id)
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
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

End an NPC's scripted action: put away what it is holding, return it to its idle animation and clear its movement target. The NPC stays where it is.

Args:
  0. npc (1-47 (0 and >= 48 ignored))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
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

End an NPC's scripted action: put away what it is holding, return it to its idle animation and clear its movement target. The NPC stays where it is.

Args:
  0. npc (1-47 (0 and >= 48 ignored))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 266` — SetOrClearNpcSchedule(npc, map, x, y, facing, apply, kind, sub kind, state)

Give an NPC a scripted destination (map, tile and facing) that it walks to on its own, e.g. to gather villagers for an event; with apply = 0 the NPC's schedule work state is reset instead. Check arrival with IsNpcAtScheduledSpot (op 268).

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. map (a map id (map(MAP_X)))
  2. x
  3. y
  4. facing (stored as 181*deg >> 8)
  5. apply (non-zero = send the NPC there now; 0 = reset its schedule work state)
  6. kind (corpus 0/5/20/30/32/50 ...)
  7. sub kind (corpus 0/9/13/17 ...)
  8. state (0/1)

### `op 267` — SetOrClearNpcSchedule(npc, map, x, y, facing, apply, kind, sub kind, state)

Give an NPC a scripted destination (map, tile and facing) that it walks to on its own, e.g. to gather villagers for an event; with apply = 0 the NPC's schedule work state is reset instead. Check arrival with IsNpcAtScheduledSpot (op 268).

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. map (a map id (map(MAP_X)))
  2. x
  3. y
  4. facing (stored as 181*deg >> 8)
  5. apply (non-zero = send the NPC there now; 0 = reset its schedule work state)
  6. kind (corpus 0/5/20/30/32/50 ...)
  7. sub kind (corpus 0/9/13/17 ...)
  8. state (0/1)

### `op 270` — ReleaseNpcScriptedPlacement(npc, full_reset)

Hands an NPC that a script placed back to its normal daily schedule. Does nothing if the NPC was not script-placed.

Args:
  0. npc (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. full_reset (0 = re-apply today's schedule state in place; non-zero = full schedule + AI reset)

### `op 271` — ReleaseNpcScriptedPlacement(npc, full_reset)

Hands an NPC that a script placed back to its normal daily schedule. Does nothing if the NPC was not script-placed.

Args:
  0. npc (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. full_reset (0 = re-apply today's schedule state in place; non-zero = full schedule + AI reset)

### `op 275` — SetNpcPresenceState(npc, mode)

Start (mode 1) or end (-1) dating a villager: sets / clears record +52 bit 22, the flag IsDatingNpc (op 274) and em.bin's PARTNER_<name> queries read. Each marriage candidate's successful confession scene ends with it.

Args:
  0. npc
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. mode (1 = present (corpus always 1); -1 = clear the presence bit; other = set the presence bit but clear the present flag)

### `op 281` — SetNpcDateState(npc, state)

Set an NPC's date state. Setting 4 (the date went well) also awards friendship: up to the next level on the very first date, otherwise +55.

Args:
  0. npc (1..47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. state (0 none, 1 date promised for tomorrow, 2 date is today, 3 on the date, 4 date went well, 5 turned you down today)
     - `0` = no date
     - `1` = date promised
     - `2` = date today
     - `3` = on the date
     - `4` = date went well
     - `5` = turned you down

### `op 284` — MountActor(character, mount_key)

Put a character on a rideable event actor (spawned with SpawnEventActor), or pass 0 to make them dismount.

Args:
  0. character (0 = player, 1-47 NPC)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. mount_key (0 = dismount (snap to ground); else the SpawnEventActor key of the monster to ride)

### `op 286` — ShakeActor(actor, frames)

Make an actor tremble for a number of frames (a quick jitter, e.g. on an impact or a fright).

Args:
  0. actor (0 = player, 1..47 NPC; >= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. frames (shake countdown (corpus 4..30))

### `op 287` — SetNpcOutfit(npc, outfit)

Change an NPC's outfit: 0 normal clothes, 1 pajamas, 2 swimsuit (both kept until changed back), 3 the third outfit (probably wedding) for this scene only.

Args:
  0. npc (1-47 (0 = nothing))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. outfit (0 = default (clears record+52 bits 0x60), 1 = variant 1 / pajamas (bit 0x40, persists), 2 or 4 = variant 2 / swimsuit (bit 0x20, persists), 3 = variant 3 (likely wedding) for this scene only; other = nothing)
     - `0` = Default
     - `1` = Pajamas
     - `2` = Swimsuit
     - `3` = Variant 3

### `op 289` — CarryBaby(actor)

Make the player or an NPC (usually the spouse) pick up and hold the baby: spawns the baby model in their arms and plays the carry pose.

Args:
  0. actor (0 = player, 1-47 = NPC/villager char id (see the character table))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 291` — SpawnChildEventActor(x, y)

If the player has a child, registers the child as an event actor (key 512) at the given tile with a random facing. Unused by the shipped scripts.

Args:
  0. x (record word2)
  1. y (record word3)

### `op 293` — ResetNpcDailySchedule(npc, state)

Hand an NPC back to its normal daily routine at the end of a scene. With -1 the NPC gets today's schedule state again and is released from the scene.

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. state (-1 = today's state (every corpus use); other = explicit state)

### `op 294` — ResetNpcDailySchedule(npc, state)

Hand an NPC back to its normal daily routine at the end of a scene. With -1 the NPC gets today's schedule state again and is released from the scene.

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. state (-1 = today's state (every corpus use); other = explicit state)

### `op 295` — ResetNpcScheduleWithState(npc, state)

Re-parse an NPC's schedule plan with an explicit state and apply today's calendar, then clear the scene's placement bit for that NPC.

Args:
  0. npc
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. state (schedule state to apply)

### `op 296` — ApplyNpcScheduleState(npc, state)

Puts an NPC back where its schedule says it should be now (position and pose for a schedule state) without resetting its AI, and releases it from the scene.

Args:
  0. npc
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. state (-1 = today's state (corpus always -1))

### `op 297` — ApplyNpcScheduleState(npc, state)

Puts an NPC back where its schedule says it should be now (position and pose for a schedule state) without resetting its AI, and releases it from the scene.

Args:
  0. npc
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. state (-1 = today's state (corpus always -1))

### `op 298` — ApplyPendingNpcPlan(npc)

Re-reads an NPC's schedule plan for today (including a schedule a script just set with SetOrClearNpcSchedule) and applies it, releasing the NPC from the scene.

Args:
  0. npc
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
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

Re-reads an NPC's schedule plan for today (including a schedule a script just set with SetOrClearNpcSchedule) and applies it, releasing the NPC from the scene.

Args:
  0. npc
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
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

Recompute an NPC's schedule for today and re-apply its daily plan, without releasing it from the scene. Unused by the shipped scripts.

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 302` — SetNpcActionDelay(npc, wait)

Make an NPC hold still for a while before resuming its schedule (used right after a conversation so the NPC does not walk off at once).

Args:
  0. npc (1..47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. wait (base wait; stored jittered to [0.75x, 1.125x); corpus 1200 / 600 / 300)

### `op 303` — SetNpcActionDelay(npc, wait)

Make an NPC hold still for a while before resuming its schedule (used right after a conversation so the NPC does not walk off at once).

Args:
  0. npc (1..47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. wait (base wait; stored jittered to [0.75x, 1.125x); corpus 1200 / 600 / 300)

### `op 313` — RestorePlayerRP()

Refills the player's RP to the maximum.

### `op 315` — QueueNpcGreetingEvent(x, y)

Finds the first NPC on the current map within 16 tiles of the given tile and starts an interaction event (type 4) with it, putting the player into talk mode. Unused by the shipped scripts.

Args:
  0. x
  1. y

### `op 316` — SetNpcVisible(npc, visible)

Show or hide a spawned NPC's model. The NPC keeps existing and acting while hidden.

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. visible (0 = hide, non-zero = show)

### `op 317` — SetNpcVisible(npc, visible)

Show or hide a spawned NPC's model. The NPC keeps existing and acting while hidden.

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. visible (0 = hide, non-zero = show)

### `op 322` — SetNpcNickname(npc, nickname)

Set the nickname the player uses for this NPC: dialogue that names the NPC through its name token (e.g. ＠ビシュナル＠) then prints this nickname. Used right after the 'what should I call you' choices.

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. nickname (entry of text archive 15177 (nickname list); corpus 7-176)

### `op 323` — SetNpcNickname(npc, nickname)

Set the nickname the player uses for this NPC: dialogue that names the NPC through its name token (e.g. ＠ビシュナル＠) then prints this nickname. Used right after the 'what should I call you' choices.

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. nickname (entry of text archive 15177 (nickname list); corpus 7-176)

### `op 327` — EndActorTransformAndSetOutfit(actor, mode)

End an actor's character-change transform and/or put it in outfit variant 3 (the corpus uses 3 on the spouse in wedding-memory scenes).

Args:
  0. actor (0 = player, 1..47 NPC; 48..255 ignored)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. mode (255 = end a character-change transform; 3 = (after ending any active one) switch to outfit variant 3; other = only end an active one)

### `op 328` — EndActorTransformAndSetOutfit(actor, mode)

End an actor's character-change transform and/or put it in outfit variant 3 (the corpus uses 3 on the spouse in wedding-memory scenes).

Args:
  0. actor (0 = player, 1..47 NPC; 48..255 ignored)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. mode (255 = end a character-change transform; 3 = (after ending any active one) switch to outfit variant 3; other = only end an active one)

### `op 330` — SetActorOutfit(actor, outfit)

Instantly switch an actor's costume, with no transformation effect.

Args:
  0. actor (0 = player, 1-47 NPC (48-253 ignored))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. outfit (costume id (e.g. REG_PLAYER_COS_ID_WORK))
     - `0` = Default
     - `1` = Pajamas
     - `2` = Swimsuit
     - `3` = Variant 3

### `op 331` — SetActorOutfit(actor, outfit)

Instantly switch an actor's costume, with no transformation effect.

Args:
  0. actor (0 = player, 1-47 NPC (48-253 ignored))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. outfit (costume id (e.g. REG_PLAYER_COS_ID_WORK))
     - `0` = Default
     - `1` = Pajamas
     - `2` = Swimsuit
     - `3` = Variant 3

### `op 369` — TryMountPlayerOnHostActor(unused)

Tries to put the player on the script's host actor (the monster being talked to) as a mount. reg1 = 0 if the player is busy; reg0 = 2 if already riding, else the mount result.

Args:
  0. unused (the handler reads no args; the corpus passes 1)

### `op 393` — FreezePlayer(release)

Lock the player's controls for a cutscene (0) or give them back (1). Note the inverted argument: scenes start with FreezePlayer(0) and end with FreezePlayer(1).

Args:
  0. release (0 = freeze the player, non-zero = release)

### `op 394` — WarpPlayer(x, y)

Teleport the player to a position on the current map and settle them on the ground.

Args:
  0. x (script units, 8 per tile)
  1. y (script units, 8 per tile)

### `op 395` — TurnPlayerToAngle(facing, ease)
*verified:* yes, in game

Turn the player to face an angle: degrees counter-clockwise on screen from facing the camera (0 down, 90 right, 180 up, 270 left). Ease 0 turns at once; ease n turns 1/2^n of the remaining angle each frame (higher = slower). Does not wait; WaitPlayerMoveDone waits for the turn.

Args:
  0. facing (any angle in degrees, counter-clockwise on screen from facing the camera: 0 = down (toward the camera), 45 = down-right, 90 = right, 180 = up (away from the camera), 270 = left (seen in game); the game stores 181 * degrees in a 65536-per-turn field, so angles land about 0.6 % short (180 -> 179.0 deg)) — verified in game
  1. ease (0 = turn at once; n = turn 1/2^n of the remaining angle each frame, so a higher n is a slower, softer turn (seen in game for 0-4; the shipped scripts use 0-3)) — verified in game

### `op 396` — TurnPlayerToAngle(facing, ease)
*verified:* yes, in game

Turn the player to face an angle: degrees counter-clockwise on screen from facing the camera (0 down, 90 right, 180 up, 270 left). Ease 0 turns at once; ease n turns 1/2^n of the remaining angle each frame (higher = slower). Does not wait; WaitPlayerMoveDone waits for the turn.

Args:
  0. facing (any angle in degrees, counter-clockwise on screen from facing the camera: 0 = down (toward the camera), 45 = down-right, 90 = right, 180 = up (away from the camera), 270 = left (seen in game); the game stores 181 * degrees in a 65536-per-turn field, so angles land about 0.6 % short (180 -> 179.0 deg)) — verified in game
  1. ease (0 = turn at once; n = turn 1/2^n of the remaining angle each frame, so a higher n is a slower, softer turn (seen in game for 0-4; the shipped scripts use 0-3)) — verified in game

### `op 397` — SetPartyOutfit(outfit)

Change the outfit of the player and both companions at once (normal, pajamas, swimsuit, wedding, bath). The outfits worn before are returned in reg0-reg2 so they can be restored.

Args:
  0. outfit (0 normal, 1 pajamas, 2 swimsuit, 3 wedding, 4 bath (4 = variant 2 for companions and sets player control bit 0))

### `op 400` — SetPlayerMale(male)

Switches the player character to Lest (1) or Frey (0) and resets the player's name to that character's default name, overwriting a custom name.

Args:
  0. male (non-zero = Lest, 0 = Frey)

### `op 427` — SetWeaponSkillsToLevel30()

Sets the player's six weapon skills (skill slots 0-5) to level 30, then refreshes the skill-rank bits. Higher levels are lowered to 30. Used by debug/test scripts.

### `op 472` — SetGuestNpcTitle(npc, title)

Set a traveller's title: byte +2 of the guest record, the index of the first word of their speaker label ('<title> <name>', from rf3TxtTravelerTitleM / W). Normally rolled 0-64 each day.

Args:
  0. npc (24-47)
  1. title (0-64 (>= 65 ignored))

### `op 474` — SetGuestRosterGate(gate, rebuild)

Controls the daily visiting-guest roster: writes its gate byte (0 = no guests) and optionally forces the roster to be rebuilt. Unused by the shipped scripts.

Args:
  0. gate (0 = no guest NPCs when the roster is next built; default 100)
  1. rebuild (non-zero = clear the 'already built' bit so the roster is rebuilt)

### `op 475` — SetNpcStateByte(npc, value)

Writes a byte (offset 58) of an NPC's record. What the game uses it for is not known.

Args:
  0. npc (invalid id writes to address 0x3A (crash))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. value (corpus 0/1)

### `op 492` — SetNpcFacingMode(mode)

Sets the talking NPC's facing mode (read back by GetNpcFacingMode). Mode 1 also makes it step to a spot in front of the player.

Args:
  0. mode (1 = walk to a point in front of the player; 0/2 clear the stand point)

### `op 562` — RefreshSceneNpcs()

Put every NPC back where its schedule says it should be now, and release the script block set by StartFestivalContest (op 559).

### `op 589` — PickUpHostObject()

Makes the player pick up and carry the object the script belongs to (e.g. a furniture piece).

### `op 594` — CommitGrabbedObject()

If the player is holding a grabbed object flagged throwable (bit 0x200000), put it into the bag.

### `op 620` — MarkSpouseCleared(spouse)

Record the marriage to this NPC in the system save (unlocks them for the Newlywed mode) and finalize the wedding.

Args:
  0. spouse (the NPC just married (REG_WIFE_ID / reg0))

### `op 660` — SetActorInvulnerable(actor, on)

Make a character or event monster immune to attacks (1) or vulnerable again (0). Retail uses it on scripted fight monsters until the fight begins. For character 239 a different, special shield bit is used.

Args:
  0. actor (0 = player, 1-47 NPC, >= 48 event key)
  1. on (non-zero = invulnerable, 0 = normal)

### `op 661` — SetActorStatFlagRecompute(target, on)

Set or clear status bit 0x20000 on an actor's stats and recompute its stats; clearing also caps current HP at the new max HP.

Args:
  0. target (0 = player, 1..47 NPC, >= 48 event key)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. on (non-zero sets, 0 clears)

### `op 662` — SetActorControlBit4000(actor, on)

Set or clear bit 0x4000 of a character's control flags. Its effect is not known; the only retail use sets it on Ventuswill (char 21) before a story fight.

Args:
  0. actor (0 = player, 1-47 NPC, >= 48 event key)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. on (non-zero = set, 0 = clear)

### `op 663` — MakeActorUntameable(actor)

Make a monster impossible to tame (e.g. story bosses and event monsters spawned by the script).

Args:
  0. actor (0 = player, 1-47 NPC, >= 48 event key (retail: event monsters 100-105, 300))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 664` — SetActorUnlimitedSight(target)

Make a monster notice the party at any distance and from any direction, so it engages right away.

Args:
  0. target (0 = player, 1..47 NPC, >= 48 event key (corpus: event monsters 100-103, 202, 205))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 665` — SetActorFacing(actor, degrees)

Instantly set a character's facing direction in degrees (no turning animation).

Args:
  0. actor (0 = player, 1-47 NPC, >= 48 event key)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. degrees (degrees (multiplied by 181 into u16 angle units))

### `op 679` — IncrementPlayerSkillLevel(skill)

Raise one of the player's skills by one level (a scripted training reward). No cap, no XP reset and no stat recalculation.

Args:
  0. skill (0-39 (skill id table; corpus 12-37))
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

### `op 680` — ApplyAttackToPlayer(attack)

Apply a combat attack entry to the player as if hit by it (damage / knockback / status or a scripted reaction, depending on the entry).

Args:
  0. attack (combat attack table entry (corpus 151, 158..164))

### `op 692` — CancelPendingDate()

Cancel a date that is promised or due today: the first villager (1-23) with date state 1 or 2 is reset to 0 and the post-date cleanup (em.bin EV_DATE_FINISH) runs. Does nothing if no date is pending.

### `op 701` — SetPlayerSkillXp(skill, xp)

Set the XP of one player skill directly (the corpus uses it to zero every skill).

Args:
  0. skill (skill index; not bounds-checked)
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
  1. xp

## Companions & party

### `op 311` — HealPartyFull()

Restore the player and both companions to full HP.

### `op 312` — SetPartyHpByShift(shift)

Change party HP by a power-of-two fraction of max HP. A negative value sets the player's HP to max/2^n (story injuries: -2 = a quarter, -4 = a sixteenth); a positive value heals the player by max/2^n and sets each companion's HP to max/2^n.

Args:
  0. shift (>= 0: player heals max>>shift, companions' HP = max>>shift; < 0: player HP = max>>-shift (companions untouched))

### `op 314` — CurePartyStatus()

Cure poison, paralysis, sleep, seal and cold on the player and both companions. Fatigue and faint stay.

### `op 402` — RecallFarmMonster(record)

Take a barn monster off its farm-area work so it stays in the barn. With -1 it acts on the monster the script belongs to and also cancels its seed-planting order.

Args:
  0. record (0..199 = g_MonsterFarmTable index; -1 = the script's own monster (host+32))

### `op 405` — SetFarmMonsterPlantOrder(farm slot, plant)

Give a barn monster the standing order to also plant seeds (1) or cancel it (0). Used by the monster work-assignment menu.

Args:
  0. farm slot (g_MonsterFarmTable record index (u8, not bounds-checked); -1 = the monster this script belongs to)
  1. plant (1 = also plant seeds, 0 = stop)

### `op 410` — TameEventMonster(key)

Tame a spawned event monster and add it to the player's monsters (as if tamed in the field). reg0 = the registration result (2 = success).

Args:
  0. key

### `op 476` — RecruitNpcToParty(npc)

Add an NPC to the player's party. If it is not loaded, it is streamed in at the player's position first. If both companion slots are full, companion 1 is dismissed (ending a date with them).

Args:
  0. npc (1..47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
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

Add an NPC to the player's party. If it is not loaded, it is streamed in at the player's position first. If both companion slots are full, companion 1 is dismissed (ending a date with them).

Args:
  0. npc (1..47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
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

Adds an NPC to the player's party (streaming them in at the player's position if they are not loaded) and marks them as held by the scene.

Args:
  0. npc
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. held (non-zero = mark the NPC scene-held; corpus always 1)

### `op 479` — RecruitNpcToPartyHeld(npc, held)

Adds an NPC to the player's party (streaming them in at the player's position if they are not loaded) and marks them as held by the scene.

Args:
  0. npc
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. held (non-zero = mark the NPC scene-held; corpus always 1)

### `op 480` — RecruitHostNpcToParty()

Add the NPC whose talk script is running to the party - the 'sure, I'll come along' branch. If both slots are full, companion 1 is dismissed.

### `op 483` — DismissBothCompanions()

Send both companions away: villagers go back to their schedule (walking off with the departure effect if their schedule is elsewhere), a date in progress ends, and a tamed monster returns to its barn.

### `op 484` — DismissBothCompanionsQuiet()

Send both party companions away like DismissBothCompanions (op 483), but without the departure effect.

### `op 485` — DismissBothCompanionsEx(return_to_schedule, no_effect)

Send both party companions away with options: force them back to their normal schedule and/or skip the departure effect. Retail always passes (1, 1), e.g. right after the wedding.

Args:
  0. return_to_schedule (non-zero = always send the NPC back to its schedule (skip the 'stay on this map' path))
  1. no_effect (non-zero = no departure effect)

### `op 486` — DismissCompanionByCharId(char id, return to schedule, no effect)

Send one specific companion away (the one with this character id); nothing happens if no companion matches.

Args:
  0. char id (companion to dismiss; 0 = the script host's actor; 22 = the current child (REG_CHILD_ID))
  1. return to schedule (non-zero = force the schedule return (mode bit 2))
  2. no effect (non-zero = skip the departure effect (mode bit 1))

### `op 488` — SetCompanionScriptedPresence(release)

Take both companions' AI under script control for a scene (0) or give it back (non-zero). Unused by the shipped scripts.

Args:
  0. release (0 = hand both companions to the script; non-zero = release them and reset their AI)

### `op 489` — SetCompanionsSceneHeld(release)

Mark both current companions as held by the scene (0), or release them (non-zero). Releasing at night (before 6:00 or after 18:00) also queues the late-night 'time to go home' check for each companion.

Args:
  0. release (0 = hold both companions for the scene; non-zero = release them (and at night queue the late-night companion check))

### `op 494` — SetCompanionVisible(slot, visible)

Hides or shows the companions (e.g. hide both before a scene, show one before moving it).

Args:
  0. slot (0 = companion 1, 1 = companion 2, 2 = both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. visible (0 = hide, non-zero = show)

### `op 495` — WarpCompanion(slot, x, y)

Instantly puts a companion (or both) on a tile.

Args:
  0. slot (0 = companion 1, 1 = companion 2, 2 = both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. x (script units, 8 per tile)
  2. y (script units, 8 per tile)

### `op 496` — WalkCompanionToAndFace(slot, x, y, facing, speed, run)

Walks a companion (or both) to a position and turns it to the given facing at the end. Does not wait; WaitCompanionSettled waits for it.

Args:
  0. slot (0 = companion 1, 1 = companion 2, 2 = both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. x (script units, 8 per tile)
  2. y (script units, 8 per tile)
  3. facing (end facing)
  4. speed (corpus 100-200)
  5. run (non-zero = run gait, speed x1.2)

### `op 497` — WalkCompanionTo(slot, x, y, speed, run)

Walk or run a companion (or both) to a position, facing the way they walk. Wait with WaitCompanionSettled (op 502).

Args:
  0. slot (0 = companion 1, 1 = companion 2, 2 = both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. x (script units, 8 per tile)
  2. y (script units, 8 per tile)
  3. speed (x40.96 internal, x1.2 when running)
  4. run

### `op 498` — MoveCompanionByOffset(slot, dx, dy, facing, speed, run)

Walk a companion (or both) by an offset from where they stand, ending with the given facing. Returns at once; WaitCompanionSettled waits for arrival.

Args:
  0. slot (0 = companion 1, 1 = companion 2, 2 = both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. dx (offset from the companion's current position)
  2. dy
  3. facing
  4. speed (100 = normal walk)
  5. run (speed x1.2 + jump bit)

### `op 499` — MoveCompanionByOffsetFaceTravel(slot, dx, dy, speed, run)

Walks a companion (or both) by a relative tile offset, facing the way it walks (no end-facing argument). Does not wait.

Args:
  0. slot (0 = companion 1, 1 = companion 2, 2 = both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. dx
  2. dy
  3. speed (corpus 100-150)
  4. run (non-zero = run gait, speed x1.2)

### `op 500` — TurnCompanionToAngle(slot, facing, ease)

Turn a companion (or both) to a compass direction, snapping or easing - the companion version of TurnActorToAngle (op 103).

Args:
  0. slot (2 = both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. facing (x181 -> u16)
  2. ease (0 = snap; n = close 1/2^n of the remaining angle per frame)

### `op 501` — TurnCompanionToFaceTarget(slot, target, ease)

Turn a companion (or both) to face the player or an NPC.

Args:
  0. slot (0 = companion 1, 1 = companion 2, 2 = both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. target (0 = player, 1..47 NPC (not an event key))
  2. ease (turn easing at actor+160 (0 = snap; 2 = typical); non-zero also sets record +20 bit 0x800)

### `op 502` — WaitCompanionSettled(slot)

Wait until the selected companion(s) have finished moving and turning.

Args:
  0. slot (2 = both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both

### `op 503` — ShowCompanionEmote(slot, emote)

Shows an emote icon over a companion (or both) with its sound; 0 clears it.

Args:
  0. slot (0 = companion 1, 1 = companion 2, 2 = both)
     - `0` = Companion 1
     - `1` = Companion 2
     - `2` = Both
  1. emote (0 = clear; corpus 6, 7, 8, 15)

### `op 506` — WarpMonstersToPlayer()

Move any monster companions in the party to the player's position (villager companions stay where they are).

## Flags & variables

### `op 214` — SetNpcStoryFlag(npc)

Mark a villager as met (GameFlags zone-2 bit 981 + char id) -- the flag that stops their first-meeting introduction from playing; 0 marks every villager 1..23.

Args:
  0. npc (1..47 (flag range covers 1..23); 0 = every loaded NPC 1..23)

### `op 215` — ClearNpcStoryFlag(npc)

Clear a villager's met flag (GameFlags zone-2 bit 981 + id) - the counterpart of SetNpcStoryFlag (op 214); their first-meeting introduction can play again.

Args:
  0. npc (1-23 (flag 981+id must stay below 1005))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 290` — SetWifeStatusAndAdvanceFamilyDay()

Set the spouse status game flag to 2 and run the once-a-day family update: add a day to the married-days counter and set or clear each child's 'birthday today' talk flag.

### `op 292` — RegisterChildBirth()

Record the birth of the player's first child: sets the child count, the child's birthday (today), marks the child as present in town, loads its default name and resets the pregnancy day counter. Does nothing if a child already exists.

### `op 318` — SetNpcBirthdayGiftFlag(npc)

Mark that the player gave this NPC a gift on its birthday (game flag 1007 + char id). Only sets, never clears.

Args:
  0. npc (0-29 in the bit range 1007-1036)

### `op 340` — SetVar0(index, value)
*verified:* yes, in game

Store a value in script-variable bank 0 at [index] (16 slots). Read it back with GetVar0. ＠キャラn＠ prints slot n as a character's name (0 = the player; else that row of the character-name file).

Args:
  0. index (out of range -> ignored) — verified in game
  1. value — verified in game

### `op 341` — SetVar0(index, value)
*verified:* yes, in game

Store a value in script-variable bank 0 at [index] (16 slots). Read it back with GetVar0. ＠キャラn＠ prints slot n as a character's name (0 = the player; else that row of the character-name file).

Args:
  0. index (out of range -> ignored) — verified in game
  1. value — verified in game

### `op 343` — SetVar1(index, value)
*verified:* yes, in game

Stores a value in script-variable bank 1 at the given slot. Scenes use slot 0 to hand a value (often an item or NPC id) to text substitution and to later scenes. ＠アイテムn＠ prints slot n as an item name.

Args:
  0. index (index >= 16 ignored) — verified in game
  1. value — verified in game

### `op 345` — SetVar11(index, value)
*verified:* yes, in game

Store a value in slot [index] of engine variable bank 11 (16 slots). Read it back with GetVar11. ＠セーブアイテムn＠ prints slot n as an item name.

Args:
  0. index (0-15) — verified in game
  1. value — verified in game

### `op 347` — SetVar2(index, value)
*verified:* yes, in game

Store a value in script-variable bank 2 at [index] (24 slots). Read it back with GetVar2. ＠マップn＠ prints slot n as a place name.

Args:
  0. index (out of range -> ignored) — verified in game
  1. value — verified in game

### `op 348` — SetVar2(index, value)
*verified:* yes, in game

Store a value in script-variable bank 2 at [index] (24 slots). Read it back with GetVar2. ＠マップn＠ prints slot n as a place name.

Args:
  0. index (out of range -> ignored) — verified in game
  1. value — verified in game

### `op 349` — SetVar3(index, value)
*verified:* yes, in game

Store a value in script-variable bank 3 at [index] (52 slots), capped at 999,999,999. Read it back with GetVar3. ＠n＠ / ＠数字n＠ print slot n as a number.

Args:
  0. index (out of range -> ignored) — verified in game
  1. value (clamped (unsigned) to 999,999,999) — verified in game

### `op 351` — SetVar4(index, value)
*verified:* yes, in game

Stores a value in script-variable bank 4 (52 slots). Shops and the smithy/pharmacy scenes use banks 4/5/6 slot by slot as parallel lists (e.g. price in bank 4) that a later menu reads back. ＠金n＠ prints slot n as a gold amount (red when the player has less).

Args:
  0. index (index > 51 ignored) — verified in game
  1. value (unsigned clamp to 999999999 (negative values become 999999999)) — verified in game

### `op 353` — SetVar5(index, value)
*verified:* yes, in game

Store a value in script-variable bank 5 at [index] (52 slots), capped at 999,999,999. Read it back with GetVar5. ＠木n＠ prints slot n as a lumber amount (red when the player has less).

Args:
  0. index (out of range -> ignored) — verified in game
  1. value (clamped (unsigned) to 999,999,999) — verified in game

### `op 355` — SetVar6(index, value)
*verified:* yes, in game

Store a number in slot [index] of engine variable bank 6 (52 slots). Read back with GetVar6. ＠石n＠ prints slot n as a material-stone amount (red when the player has less).

Args:
  0. index (0-51) — verified in game
  1. value (0-999999999 (unsigned clamp: larger or negative values become 999999999)) — verified in game

### `op 357` — SetVar7(index, value)
*verified:* yes, in game

Store a number in script variable bank 7 [index]. Read back with GetVar7 (op 358). ＠王n＠ prints slot n as a Prince Points amount (red when the player has fewer).

Args:
  0. index (0-51 (larger ignored)) — verified in game
  1. value (clamped (unsigned) to 999,999,999) — verified in game

### `op 359` — SetVar8(index, value)
*verified:* yes, in game

Store a value in slot [index] of engine variable bank 8 (16 slots). -1 / -2 store the monster-barn record index of companion 1 / 2 instead. Used to remember which farm monster a menu refers to. ＠モンn＠ prints slot n as that barn monster's given name. The value is a monster-barn record index; ＠モンn＠ prints that monster's own (player-given) name (in game).

Args:
  0. index (0-15) — verified in game
  1. value (any; -1 = companion 1's farm-table record index, -2 = companion 2's) — verified in game

### `op 361` — SetVar9(index, value)
*verified:* yes, in game

Store a value in slot [index] of engine variable bank 9 (16 slots). -1 stores the calendar date code of the festival currently running. There is no GetVar9 op; villager AI also reads the bank. ＠カレンダーn＠ prints the calendar event on the date in slot n (season x 100 + day).

Args:
  0. index (0-15) — verified in game
  1. value (any; -1 = date code of the festival in progress (GF_REG_FESTA), if any) — verified in game

### `op 364` — SetVar10(index, value)

Stores a value in script-variable bank 10. There is no GetVar10. ＠子供ちゃん＠ prints the name of the child it picks.

Args:
  0. index (index >= 16 ignored)
  1. value

### `op 373` — DispatchCondScriptEntry(em_entry)

Run the main action stream of an Event Manager (em.bin) entry - usually a batch of game-flag writes.

Args:
  0. em_entry (e.g. EV_SUBEV_INIT)

### `op 374` — RunEmEntryAltAction(entry)

Run the ALT action stream of an em.bin (event manager) entry, e.g. entry 80 to finish a date.

Args:
  0. entry (80 = EV_DATE_FINISH (clears FLG_DATE_FES_NOW / FLG_KOKUHAKU_NOW / REG_DATE_MAP); 265-267 also used)

### `op 443` — SetFlagBit(flag, value, unused, unused)

Set or clear a zone-2 game flag bit. Only the first two arguments matter; shipped scripts always pass four.

Args:
  0. flag (bit zone2_base + id (same numbering as GetFlagBit, MOBJ f13))
  1. value (0 = clear, non-zero = set)
  2. unused (ignored (corpus 0 or 1))
  3. unused (ignored (corpus 0))

### `op 444` — SetFlagBitIfCond(flag, condition)

Sets or clears a game-flag bit from an em.bin condition, inverted: condition true clears the bit, false sets it. Unused by the shipped scripts.

Args:
  0. flag (absolute bit = zone2_base + flag)
  1. condition (its condition A is evaluated)

### `op 553` — SetNpcSubEventFlag(set, npcs)

Sets or clears a per-NPC sub-event flag (bit 23 of the NPC's record flags) for the listed NPCs. FinishCurrentSubEvent clears it for everyone.

Args:
  0. set (non-zero = set, 0 = clear)
  1. npcs (a 0 in the list applies the bit to all villagers 1-23 and ends the list)

### `op 554` — SetNpcSubEventFlag(set, npcs)

Sets or clears a per-NPC sub-event flag (bit 23 of the NPC's record flags) for the listed NPCs. FinishCurrentSubEvent clears it for everyone.

Args:
  0. set (non-zero = set, 0 = clear)
  1. npcs (a 0 in the list applies the bit to all villagers 1-23 and ends the list)

### `op 557` — SetNpcRecognitionFlags(value, npcs)

Writes packed game flag 1451 + npc = value for each listed villager (23 per-villager flags 1452-1474 for ids 1-23). Sub-event scenes call it right after starting, with every participant.

Args:
  0. value (corpus always 1)
  1. npcs (ids 1-23; >= 24 skipped; 0 = the spouse (GF_REG_WIFE_ID))

### `op 558` — SetNpcRecognitionFlags(value, npcs)

Writes packed game flag 1451 + npc = value for each listed villager (23 per-villager flags 1452-1474 for ids 1-23). Sub-event scenes call it right after starting, with every participant.

Args:
  0. value (corpus always 1)
  1. npcs (ids 1-23; >= 24 skipped; 0 = the spouse (GF_REG_WIFE_ID))

### `op 566` — RecordFestivalPlacement(placement, festival)

Record the player's placing in a festival contest: tells the villagers about a top-3 finish and saves it as the best placing if it beats the old one (which also awards the matching Steam achievement).

Args:
  0. placement (1-3 (1st-3rd); other values only update the record if better)
  1. festival (6, 8-17 (7 and others: undefined packed id))

### `op 571` — SetSceneScratch(byte_value, word_value)

Stores a byte and a word in the current scene's scratch fields for later ops of the same scene to read.

Args:
  0. byte_value (scene +541)
  1. word_value (scene +544)

### `op 621` — SetDifficulty(mode)

Set the game difficulty.

Args:
  0. mode (0 = Easy, 1 = Normal, 2 = Hard (Hell is Hard plus FLG_DIFFICULTY_HELL set by the script))

### `op 628` — SetRegisters(values...)
*verified:* yes, in game

Load the VM registers reg0.. from the arguments (reg0 = arg0, reg1 = arg1, ...). Scripts use it to read a variable into reg0 for a following branch.

Args:
  0. values... (reg0, reg1, ... reg9 in order (args past 10 ignored)) — verified in game

### `op 629` — SetRegisters(values...)
*verified:* yes, in game

Load the VM registers reg0.. from the arguments (reg0 = arg0, reg1 = arg1, ...). Scripts use it to read a variable into reg0 for a following branch.

Args:
  0. values... (reg0, reg1, ... reg9 in order (args past 10 ignored)) — verified in game

### `op 651` — AdvanceStoryProgress(progress)

Moves the main story progress forward to the given value; it never goes backwards. Plot scenes call it at their end.

Args:
  0. progress (0-511 (9-bit GF_REG_MAIN_SCENARIO))

### `op 667` — SetGameClearedSysFlag()

Mark the game as cleared in the system save (rf4_sys.sav): unlocks the post-game Extra Orders in every save slot. Set-only.

### `op 669` — SetSaveConfigBit4()

Set bit 4 (0x10) of g_saveConfigFlags. Set-only.

### `op 671` — SetSaveConfigBit5()

Sets bit 5 of the system save-config flags (shared by all save slots). The only shipped use enables the data-transfer extra order ('Data transfer is now enabled by making an extra order!').

## Audio

### `op 379` — PlayMusic(bgm)
*verified:* yes, in game

Switch the background music (crossfade) to a track, or with -1 go back to the area's normal music. When the scene ends, the game brings the area's music back (NpcAi_FinalizeEventAndPostTick RF4S.exe+0x1F61F0 -> BGM_RestoreFromBossOrTransient, which ignores SetMusicLock) unless FLG_BGM_NOT_RETURN is 1: EVAL (FLG_BGM_NOT_RETURN = 1) before the scene ends keeps the new state (the game clears that flag again at the scene end, so it is one-shot).

Args:
  0. bgm (sound id (0x1000000+); -1 = return to the map's normal music) — verified in game

### `op 380` — StopMusic(fade)
*verified:* yes, in game

Stop the current background music at once (the fade argument is never read: StopMusic(30000) still cut the music at once in game). When the scene ends, the game brings the area's music back (NpcAi_FinalizeEventAndPostTick RF4S.exe+0x1F61F0 -> BGM_RestoreFromBossOrTransient, which ignores SetMusicLock) unless FLG_BGM_NOT_RETURN is 1: EVAL (FLG_BGM_NOT_RETURN = 1) before the scene ends keeps the new state (the game clears that flag again at the scene end, so it is one-shot). The next map change, and the 06:00 / 21:00 switch, pick the area music again unless SetMusicLock(1).

Args:
  0. fade (corpus passes 0..30000 but the stop path never reads it) — verified in game

### `op 382` — FadeMusicVolume(volume, time)

Fade the music volume to a percentage, and later back with -1. Handy to duck the music under a sound effect or a quiet moment.

Args:
  0. volume (target volume % of the category volume; -1 = back to the saved volume)
  1. time (ramp length in the sound system's units (corpus 0/60/120/18000))

### `op 383` — SetMusicLock(lock)

Lock or unlock the background music. While locked, map changes and the 06:00/21:00 switch do not replace the current track. It stays locked across maps until SetMusicLock(0). It does not stop the scene-end restore after PlayMusic / StopMusic (that one ignores the lock; use FLG_BGM_NOT_RETURN).

Args:
  0. lock (1 = keep the current BGM, 0 = allow area music again)

### `op 384` — ResetMusicResumePositions()

Forget where each music class (village, dungeon, story, ...) was paused, so the next PlayMusic starts its track from the beginning.

### `op 385` — PlaySound(sfx)
*verified:* yes, in game

Play a sound effect.

Args:
  0. sfx (0x1000000+ sound id; 0 = nothing) — verified in game
     - *(enum: 8923 values — use the in-editor picker or the id database)*

### `op 386` — StopVoices()

Stops every voice line that is currently playing. Unused by the shipped scripts.

### `op 387` — PlaySfxWithNpcRemap(sound)
*verified:* yes, in game

Plays a sound effect or voice line by id, with the per-character remap the engine applies to shared ids (the variant of the current character's voice). Most uses are voice clips placed before DIALOG lines. Tested with Lest only (0x10001C0 played V_PLAM); whether it switches player clips to the female set for Frey, as SetSpeaker's voice trigger does (V_PLAW), is untested.

Args:
  0. sound (0x1000000 + n; mostly voice lines 16777394-16785998; 0 stops menu audio) — verified in game
     - *(enum: 8923 values — use the in-editor picker or the id database)*

### `op 389` — SetPooledVoiceVolume(volume)

Sets the volume of one slot of the 12-slot sound pool to a percentage. Which slot is affected is decided by the pool allocator (a free slot, else the lowest-priority/oldest one), so the audible effect is unreliable; shipped scenes call it right after a PlaySfxWithNpcRemap.

Args:
  0. volume (arg/100, clamped to 0..1 after the capture-mix factor; corpus -1, 30, 50, 70, 127)

### `op 390` — StopVoiceId(sound)

Stops the playing voice line or looping sound with the given id.

Args:
  0. sound
     - *(enum: 8923 values — use the in-editor picker or the id database)*

### `op 392` — PlaySoundOnFreeVoice(sound)

Play a sound on a free (or pre-empted) pooled voice instead of the script host's own sound slot, so it does not cut off the host's current sound.

Args:
  0. sound (common_audio_data id (0x1000000 + n))
     - *(enum: 8923 values — use the in-editor picker or the id database)*

### `op 461` — SuppressRewardJingle()

Silence the jingle of every later reward popup started by this script (ops 457, 458, 459, 462).

## Time & calendar

### `op 204` — SleepInBed(cinematic)

Put the player to bed and advance to the next day. With 0 the day rollover happens at once (cutscenes fade out themselves first); with 1 the full bed cinematic plays (spouse/child walk over, fade out, sleep, fade in, morning music).

Args:
  0. cinematic (0 = advance the day immediately (no animation); non-zero = full go-to-bed sequence)

### `op 300` — ResetAllNpcSchedules()

Resets every villager and every current event participant to today's schedule with a full schedule and AI reset. It does not change the date.

### `op 304` — GetYear()
*verified:* yes, in game

Get the current calendar year. reg0 = year.

### `op 305` — GetSeason()
*verified:* yes, in game

Put the current season (0 Spring, 1 Summer, 2 Autumn, 3 Winter) into reg0.

### `op 306` — GetDay()
*verified:* yes, in game

Get the current day of the season (1-30). reg0 = day.

### `op 307` — GetHourMinute()
*verified:* yes, in game

Read the current clock time: reg0 = hour (0-23), reg1 = minute (0-59).

### `op 308` — GetDateSnapshot()
*verified:* yes, in game

Get the whole current date and time at once: reg0 = year, reg1 = season, reg2 = day, reg3 = hour, reg4 = minute.

### `op 362` — GetFestivalDate(slot, festival)
*verified:* yes, in game

Looks up the date of a festival: reg0 = season (0-3), reg1 = day, and script-variable bank 9 [slot] = season*100 + day for text substitution.

Args:
  0. slot (receives season*100 + day; >= 16 not written) — verified in game
  1. festival (1-25 (0 would match the first birthday record)) — verified in game

### `op 449` — GetWeatherTransition()

Read the weather state byte the toolkit calls the transition flag (BYTE2 of g_weather[8].name). reg0 = value (0 without a weather task).

### `op 450` — GetWeatherStreak()

Put the weather system's streak counter into reg0 (30 when there is no weather task). Retail tests for values 1-3.

### `op 451` — GetDayOfWeek()
*verified:* yes, in game

Read the weekday into reg0 (0-5), computed from the day of the season like the rest of the game does. 0 = the weekday the calendar shows as 'HOL' (Autumn 7 read 0, Autumn 8 read 1): the week has 6 days.

### `op 465` — SetCalendarPauseFlag(pause)

Take control of the in-game clock for the rest of the scene (1): clears the calendar's run byte now and stops the scene end from setting it back. 0 clears the flag so the scene end restores the clock as usual.

Args:
  0. pause (bit 0 used: 1 = set, 0 = clear)

### `op 466` — SkipToTime(hour, minute, mode)

Advance the clock to a given time (or by an amount) and run the fast-forward that sleeping uses, so NPC schedules and day changes catch up.

Args:
  0. hour (target hour (or hours to add when mode = 0))
  1. minute (target minute (or minutes to add when mode = 0))
  2. mode (1 = go to hour:minute, 0 = add hours/minutes)

### `op 467` — SetTime(hour, minute, absolute)

Set the clock to a time (or move it forward by hours/minutes). The date only changes if the time rolls past midnight.

Args:
  0. hour
  1. minute
  2. absolute (non-zero = set the clock; 0 = add hour/minute as a delta)

### `op 468` — FastForwardCalendar(year, season, day, mode)

Advance the date by years/seasons/days (or toward a target year/day) and run the overnight update. Unused by the shipped scripts.

Args:
  0. year (delta (mode != 0) or target)
  1. season (delta)
  2. day (delta (mode != 0) or target)
  3. mode (non-zero = add deltas; 0 = move to the target)

### `op 469` — SetOrAddCalendarDate(year, season, day, absolute)

Sets the calendar date (year, season, day) or adds to it, then fast-forwards the world as after sleeping and refreshes the clock/weather display. Hour and minute are kept.

Args:
  0. year
  1. season
  2. day
  3. absolute (non-zero = set the date, 0 = add to it)

### `op 627` — JumpToRandomDate()

Move the calendar to a random day and season of the current year (time of day kept) and run the sleep fast-forward to it. Looks like a debug op.

### `op 637` — SaveCalendarSnapshot()

Copy the current date and time (calendar +0..+23) into the calendar's snapshot block (+24..+47), the 'from' time the sleep fast-forward uses.

## Items, rewards, economy

### `op 146` — EquipItemToPlayer(item)

Put an item into the player's weapon/tool slot for a scripted scene (e.g. hand the player a hammer), stashing what was equipped so RestorePlayerEquip (op 147) can give it back. The player is put into the scripted-talk idle.

Args:
  0. item (e.g. 575 = Iron Hammer)
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 208` — HandOrDropItem(holder, item)
*verified:* yes, in game

Put an item in a character's hands: an NPC holds it (e.g. before handing it over), or the player receives it held over their head - dropped at their feet if they are already holding something. reg0 tells whether it is held.

Args:
  0. holder (0 = player, 1-47 = NPC/villager char id (see the character table)) — verified in game
  1. item (0-2047 (11 bits)) — verified in game
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 209` — HandOrDropItem(holder, item)
*verified:* yes, in game

Put an item in a character's hands: an NPC holds it (e.g. before handing it over), or the player receives it held over their head - dropped at their feet if they are already holding something. reg0 tells whether it is held.

Args:
  0. holder (0 = player, 1-47 = NPC/villager char id (see the character table)) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. item (0-2047 (11 bits)) — verified in game
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 210` — HandOrDropItemWithLevel(holder, item, level, amount)

Like HandOrDropItem, but with an explicit item level and stack amount - used when a cooked or crafted item with a level is handed over. reg0 tells whether it is held.

Args:
  0. holder (0 = player, 1-47 = NPC/villager char id (see the character table))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. item (0-2047)
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  2. level (1-10 (stored as level-1, capped at 9))
  3. amount (stack amount, capped at 9 (5-bit field))

### `op 325` — GetLumber()
*verified:* yes, in game

Get the player's lumber count. reg0 = lumber (seen in game). GetPlayerVariable has no lumber code; this is the only way to read it.

### `op 326` — ModifyLumber(mode, amount)
*verified:* yes, in game

Add to, subtract from or set the player's lumber. The mode is add / sub / set (a plain number does nothing). Add caps at 50,000, subtract stops at 0, but set caps at 9,999 (all seen in game). Lumber has its own ops; GetPlayerVariable / ModifyPlayerResource have no lumber code.

Args:
  0. mode (the operation comes from the argument's KIND, not its value: null leaf (listed 'null', kind 4) = add (cap 50000), zero leaf (listed '0', token 0x12, kind 5) = subtract (floor 0), self leaf (listed 'self', kind 6) = set (cap 9999); a plain number (kind 0) does nothing) — verified in game
  1. amount — verified in game

### `op 417` — ModifyPlayerResource(resource, mode, amount)
*verified:* yes, in game

Give, take or set gold, stone, compost, fodder or the player's level, e.g. pay 1000 gold = ModifyPlayerResource(gold, sub, 1000). Stone and compost stay within 0..50,000 and gold within 0..2,000,000,000; 'set' on the level takes the 0-based value (set 49 = level 50). All five seen in game.

Args:
  0. resource (100 'd' gold, 102 'f' player level, 103 'g' fodder, 105 'i' stone, 106 'j' compost; anything else does nothing) — verified in game
     - `100` = gold
     - `102` = level
     - `103` = fodder
     - `105` = stone
     - `106` = compost
  1. mode (add (null leaf, kind 4) / sub (zero leaf, kind 5) / set (self leaf, kind 6); read from the arg's KIND slot) — verified in game
  2. amount — verified in game

### `op 421` — SetNextItemAttributes(level, crafted, ingredients...)

Prepare level, crafted bits and ingredient list for the NEXT item a script creates (GivePlayerItem, SpawnItemAtPos, ForcePlayerHoldItem, HandOrDropItem ...). The first such op uses and clears it.

Args:
  0. level (stored into the item's level byte)
  1. crafted (3-bit crafted field (flags word bits 1-3))
  2. ingredients... (up to 6 u16 ingredient / material ids (e.g. a dish's ingredients))

### `op 422` — SetNextItemAttributesPacked(byte4, byte6, field0, packed)

Stages an alternative item-attribute record (marker 2) for the next item op. No item op in this build applies a marker-2 record, so the only lasting effect is that attributes staged by the marker-1 op are discarded. Unused by the shipped scripts.

Args:
  0. byte4 (stored at record +4)
  1. byte6 (stored at record +6)
  2. field0 (record +8 bits 10-19)
  3. packed (packed into the high dword of record +8)

### `op 423` — GivePlayerItem(item, count, level)
*verified:* yes, in game

Give the player an item stack. It goes into the backpack, else the rune-ability page; if both are full it is dropped at the player's feet (when they already carry something) or the player holds it up. reg0 = 1 if it went into a page.

Args:
  0. item — verified in game
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count (stack size (5 bits)) — verified in game
  2. level (stored as level-1 in each level byte) — verified in game

### `op 424` — GivePlayerItem(item, count, level)
*verified:* yes, in game

Give the player an item stack. It goes into the backpack, else the rune-ability page; if both are full it is dropped at the player's feet (when they already carry something) or the player holds it up. reg0 = 1 if it went into a page.

Args:
  0. item — verified in game
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count (stack size (5 bits)) — verified in game
  2. level (stored as level-1 in each level byte) — verified in game

### `op 425` — ForcePlayerHoldItem(item, count, level)

Put an item straight into the player's hands with the pick-up jingle (bypassing the bag). With item 0 it instead uses up the stack the player is holding.

Args:
  0. item (0 = use up the currently held stack instead)
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count (stack size)
  2. level (> 10 treated as 1)

### `op 428` — TakeItem(item, count, level_filter)

Remove items from the player, searching the backpack, held item, equipment, storage, racks, closet, tool box, shipping box, fridge, bookshelf and rune page in that order.

Args:
  0. item
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count (demand (5 bits))
  2. level_filter (-1 = any copy; >= 0 = only copies whose level/quality byte is 0)

### `op 429` — TakeItemFromBackpack(item, count, level filter)
*verified:* yes, in game

Remove a number of an item from the backpack (first 60 slots), then from the carried item; a partial take drops the lowest-level copies of the stack. Over-removes when the demand spans slots. Writes no result.

Args:
  0. item — verified in game
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count (count & 31) — verified in game
  2. level filter (-1 = any stack; >= 0 (any value) = only stacks whose highest level byte is 0, i.e. every copy is level 1) — verified in game

### `op 430` — ConsumeHeldItem(count)

Uses up items from the stack the player is holding out (e.g. the item just handed to an NPC).

Args:
  0. count (-1 = the whole held stack)

### `op 452` — SpawnItemAtPos(item, level, count, x, y, pickup)

Places an item in the world at a position, either as a collectable drop or as a visual-only prop.

Args:
  0. item
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. level (outside 1..10 -> 1; stored as level-1)
  2. count (packed << 11 (low 5 bits used))
  3. x
  4. y
  5. pickup (0 = visual prop only, non-zero = collectable drop)

### `op 453` — DropStagedItem()

Drop the item staged in the script host's item record onto the ground at the player's tile.

### `op 454` — SpawnItemVisual(item, x, y)

Place an item model at a tile for display (up to 3 at a time), e.g. to show gift choices laid out in a scene. Remove them with DespawnItemVisuals (op 455).

Args:
  0. item
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. x (script units, 8 per tile; -1 together with y = -1 = the player's tile)
  2. y (script units, 8 per tile)

### `op 455` — DespawnItemVisuals()

Remove all item models placed with SpawnItemVisual (op 454).

### `op 457` — ShowRewardPopup(item1, item2, item3, item4)

Show the 'you got' reward popup for up to four items (count 1 each) with the reward jingle, and mark them as discovered.

Args:
  0. item1 (item id (1 to 4 items, count 1 each))
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. item2 (item id)
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  2. item3 (item id)
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  3. item4 (item id)
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 458` — ShowQuestReward()

Shows the reward popup for the active NPC request (its four reward items) with the reward jingle, marking the items as discovered.

### `op 459` — ShowRewardPopupAtPos(item, x, y)

Shows a one-item reward popup ('You got ...!') anchored at a position, with the reward jingle, and marks the item as discovered.

Args:
  0. item
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. x
  2. y

### `op 460` — AddRewardItem(slot, item, level, count)

Put an item into a reward-popup slot (adds it and queues the popup), marking it discovered.

Args:
  0. slot
  1. item
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  2. level (out of range -> 1; stored as level-1)
  3. count (out of range -> 1)

### `op 462` — GiveRewardItems(item1, count1, item2, count2, item3, count3, item4, count4)

Open the reward popup and give up to four items as (item, count) pairs. Special item values roll a random prize: 9997 stat drink, 9998 shop item, 9999 generic loot, 10000 request reward.

Args:
  0. item1 (item id; 9997 = random shop-available stat drink among ids 111-114; 9998 = Item_RollRandomIdInCategory over 13 categories; 9999 = Loot_RollGenericFromTable; 10000 = request reward roll (Loot_RollQuestSpecificFromTable, stack sized by the active request's price, level from skill 36))
  1. count1 (1-15 (stored as count << 11; the popup keeps a 4-bit count))
  2. item2 (as item1)
  3. count2 (as count1)
  4. item3 (as item1)
  5. count3 (as count1)
  6. item4 (as item1)
  7. count4 (as count1)

### `op 463` — DropItem(item)

Drop one of an item on the ground at the player's position, with the drop jingle.

Args:
  0. item
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 464` — DropItemStack(item, level, count)

Drops a stack of an item on the ground at the player's feet, with the item jingle.

Args:
  0. item
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. level (0 treated as 1; stored as level-1)
  2. count (packed << 11)

### `op 563` — EquipScriptedWeapon(item)

Give the player a specific weapon for a scripted scene (the real weapon is backed up); restore it later with op 564.

Args:
  0. item (weapon to put in the player's hands)
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 564` — RemoveScriptedWeapon()

Gives the player back the main-hand weapon that was swapped out by the scripted-weapon equip op.

### `op 587` — PlaceFurniture(furniture, room, x, y)

Put a piece of furniture into a room (max 16 per room). reg0 = 1 if it was placed. Used when the player buys furniture.

Args:
  0. furniture (furniture id in the tile-object space (corpus 335-381))
  1. room (-1 = the current room)
  2. x (8 per tile; -1 = default / player position)
  3. y (8 per tile; -1 = default / player position)

### `op 590` — BreakFurniture()
*verified:* yes (no test logged)

Break the furniture object running this script: a dust puff, it drops one Lumber (1022) and one Material Stone (1023) and disappears.

### `op 597` — RollShopCategoryItemReturnId(category)

Roll a random unlocked item from a shop category and put its id into reg0 (e.g. the gift an NPC hands over).

Args:
  0. category (0-52 in the corpus (e.g. 2 = items 63-110, 51 = 813-984))

### `op 598` — RollRandomItemMatchingDisplayName(name id)

Put into reg0 a random item among those that share a display name (e.g. the colour/level variants of one item), choosing only unlocked ones.

Args:
  0. name id (items whose metadata base_item_id (+0) equals this (corpus 1083-1099))

### `op 599` — RollRandomDishItem()

Put a random unlocked cooked dish into reg0 (uniform over shop categories 5-11, item ids 134-299).

### `op 600` — RollRandomEquipmentItem()

Put a random unlocked item from one of 16 fixed shop categories (mostly weapons and equipment, plus skill/spell items and breads) into reg0 - used for NPC birthday/return gifts.

### `op 601` — RollRandomFurItem()

Sets reg0 to a random fur item the player has unlocked: Fur (S)/(M)/(L), Wooly Furball or Quality Puffy Fur. Used to pick the target of a random request.

### `op 602` — RollRandomMedicineOrFailedDish()

Roll a random unlocked item from the medicine/failed-dish set (ids 115-119, 123, 131-133) into reg0.

### `op 603` — RollRandomGrassItem()

Sets reg0 to a random unlocked herb/grass item (ids 71-81: Medicinal Herb, Antidote Grass and the coloured grasses). Used to pick the target of a random request.

### `op 604` — RollRandomIngredientItem()

Pick a random available item from a fixed ingredient set (Pink Melon, Leek, Hot-Hot Fruit, Giant Hot-Hot Fruit, Heavy Spice, Relax Tea Leaves, Chocolate, Milk S/M/L, Honey). reg0 = item id.

### `op 605` — RollRandomSeasoningItem()

Put a random unlocked seasoning / cooking base (Flour, Oil, Curry Powder, Ketchup, ...) into reg0; Flour if none is unlocked.

### `op 606` — RollThreeFlowerItemsAvoidDup()

Offers three plant items: reg0 = 63 (Toyherb) and reg1/reg2 = two different random unlocked flowers (ids 63-70 and 84-109), neither of them Toyherb.

### `op 607` — RollRandomFlowerSeedItem()

Roll a random unlocked flower seed (ids 758, 759, 765, 771, 773-785) into reg0.

### `op 616` — TestAndSetCraftedFlag(item)

Marks a recipe as known/crafted and returns whether it already was (reg0 = old value). Used when an NPC teaches recipes. With 100000 it sets a special flag and always returns 1.

Args:
  0. item (100000 = the special 'misc' flag (zone-2 bit 1403))
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 640` — AddPrincePoints(amount)

Add (or with a negative amount, remove) Prince Points.

Args:
  0. amount (added (negative subtracts); result clamped to 0..99999)

### `op 643` — ApplyPrinceOrder(order, variant)

Buy and carry out a Prince Point order: pays its cost and applies the effect. reg0 = 1 if it was paid and applied, 0 if unaffordable.

Args:
  0. order (Prince Point order (0-98 in the corpus))
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
  1. variant (order sub-index (festival id, license / NPC variant ...))

### `op 645` — PromotePrinceRank()

Raise the Prince rank for every tourist threshold reached (up to rank 5) and pay out the rank-up gold. reg0 = promoted?, reg1 = new rank, reg2 = gold reward.

### `op 675` — ConvertMedalsToGold()

Exchanges all of the player's Rune Medals for gold at 20 gold each; reg0 = the gold gained.

### `op 681` — RollBreadRecipe(bread_item)

Roll which recipe the player learns from eating a recipe bread; the result goes into reg0 (0 when the bread has nothing left to teach).

Args:
  0. bread_item (318/319 Medicine Bread(+), 320/321 Cooking Bread(+), 322/323 Weapon Bread(+), 324/325 Accessory Bread(+), 326/327 Farming Bread(+))

### `op 696` — RemoveItemFromBackpack(item, count, level_filter)

Take a number of an item from the player's backpack -- but only stacks whose flag bit 0 is set (plain items are left alone, seen in game); for ordinary items use TakeItemFromBackpack or TakeItem. A request spanning several stacks can over-remove (see details).

Args:
  0. item (0-2047 (low 11 bits))
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. count (how many to take)
  2. level_filter (-1 = any level; >= 0 = only slots whose level byte is 0 (the value itself is not compared))

## Effects & world

### `op 139` — ApplyEffectToActor(actor, effect_kind)

Applies an effect kind (magic, heal, status or visual) to an actor as if that actor used it, e.g. a healing spell in a cutscene.

Args:
  0. actor (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. effect_kind (corpus 48/49 (healing-magic kinds))

### `op 140` — ApplyEffectToActor(actor, effect_kind)

Applies an effect kind (magic, heal, status or visual) to an actor as if that actor used it, e.g. a healing spell in a cutscene.

Args:
  0. actor (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. effect_kind (corpus 48/49 (healing-magic kinds))

### `op 150` — TriggerActionAtPos(action_id, x, y)

Spawns a scripted action (visual effect, projectile, explosion, prop task...) by action id at a position. Scenes use it for sparkles, smoke, impacts and similar effects.

Args:
  0. action_id (corpus 2-473; 65 and 105 always use the player's position) — verified in game
     - `21` = spawn_lightning
     - `25` = explosion
     - `37` = blue_diamond
     - `151` = white_smoke
     - `152` = smoke_puff
  1. x (script units, 8 per tile)
  2. y (script units, 8 per tile)

### `op 151` — TriggerActionOnActor(action, actor)

Spawn an action/effect (by action-constructor id) attached to an actor, at the actor's position.

Args:
  0. action (g_actionConstructorTable id (same id space as ops 150/165; e.g. 61, 117, 164))
  1. actor (0 = player, 1..47 NPC)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 157` — SpawnMapEntity(type, x, y, facing, param, extra1, extra2, extra3, extra4, extra5, extra6)

Spawns a map entity (object, interactive object, decoration or special trigger) by type id, the same kind of placement a room file does.

Args:
  0. type (<20 special trigger; 20-195 placed object (pg_mobj); 196-335 interactive object; >=336 decoration)
     - *(enum: 389 values — use the in-editor picker or the id database)*
  1. x
  2. y
  3. facing (x182)
  4. param (x40; corpus mostly 100 / -100)
  5. extra1
  6. extra2
  7. extra3
  8. extra4
  9. extra5
  10. extra6

### `op 165` — TriggerActionAtEventActor(key, action)

Spawn an action/effect (by action-constructor id) attached to an event actor, at its position.

Args:
  0. key
  1. action (g_actionConstructorTable id (same id space as ops 150/151))

### `op 166` — ApplyEffectToEventActor(key, effect)

Apply an effect kind (damage / status / visual) to an event actor; the event-actor twin of ApplyEffectToActor (op 139).

Args:
  0. key
  1. effect (Effect_ApplyByKindAndSpawn kind)

### `op 205` — RefreshMapTiles()

Forces every tile of the current map to be redrawn/re-evaluated. Scenes call it during a fade-out before the sleep/next-day transition.

### `op 401` — SendMonsterToFarmArea(area)

Sends the barn monster being talked to out to work on a farm field (1-3), a random free field (-1), or calls it back (0).

Args:
  0. area (1-3 = that field, -1 (0xFF) = a random free field, 0 = recall; only the low byte is used, 4 & 3 = 0)

### `op 439` — ReleaseFarmMonster()

Releases the barn monster being talked to: it disappears with an effect and its barn slot is freed.

### `op 446` — SetWeather(weather, seasonal)
*verified:* yes, in game

Change the weather for a scene (rain, snow, typhoon, Rooneys ...) or put it back with -1. If a dialogue box is open it is closed first and the op waits a frame. With the second argument non-zero the first is a daily-weather roll, not a weather code (1 then means cloudy, not rain).

Args:
  0. weather (with seasonal 0: 0 sunny, 1 rain, 2 snow, 3 typhoon, 4 blizzard, 5 cloudy, 6 Rooney (floating Rooneys), 7 light rain, 8 light snow (all seen in game); 9 and above: nothing falling (seen for 9, 10); -1 = put back the weather from before this script's first SetWeather (seen). With seasonal non-zero the number is a daily-weather ROLL instead, see seasonal) — verified in game
     - `0` = sunny
     - `1` = rain
     - `2` = snow
     - `3` = typhoon
     - `4` = blizzard
     - `5` = cloudy
     - `6` = rooney
     - `7` = light_rain
     - `8` = light_snow
  1. seasonal (0 = arg 0 is the weather code. Non-zero = arg 0 is a daily-weather roll that Weather_PromoteRollToWeatherCode (RF4S.exe+0x19D4F0) turns into a code, with a 50 % chance value: 0 sunny, 1 cloudy, 2 rain (1/64 light rain), 3 typhoon, 4 Rooney (rolls 0-4 seen in game), 5-7 chance between sunny / cloudy / rain; then winter turns rain into snow and a typhoon into a blizzard, and late autumn (day > 20) gives rain a 25 % chance of snow) — verified in game

### `op 448` — SetWeatherTransition(on)

Set the weather task's transition flag (the byte SetWeather(0) clears). Used right after SetWeather in two scenes.

Args:
  0. on (0 / non-zero)

### `op 578` — SpawnEventMonsters()

Spawn the farm monsters taking part in the current festival scene event (e.g. the monster contest). Use while the screen is faded out.

### `op 591` — ClearAllTileObjects()

Removes every placed furniture/tile object record (all rooms) by clearing its active bit. Unused by the shipped scripts.

### `op 625` — EnterSharanceMazeStage(stage)

Starts a Sharance Maze challenge stage: records the stage and the current room/tile for the return trip. The script warps into the maze with the next op.

Args:
  0. stage (0 Garden of Light, 1 Smoldering Prominence, 2 Deepwater Shrine, 3 Dragon Ruins, 4 Challenge to Fantasy, 5 Banquet of Nightmares (menu order))

### `op 677` — SpawnEffectObjectAtPos(x, y)

Spawn the class-2050 floating object (the harvest-notification style effect actor) at a position.

Args:
  0. x (script units, 8 per tile)
  1. y (script units, 8 per tile)

### `op 678` — WallOffTileRect(x, y, width, height)

Turn a rectangle of the current map into solid wall that blocks the player, monsters and NPCs (used to fence in a boss arena). Lasts until the map is reloaded.

Args:
  0. x (sub-tile units (>> 3 = tile))
  1. y (sub-tile units)
  2. width (rounded up to whole tiles)
  3. height (rounded up to whole tiles)

### `op 689` — RespawnRoomFurnitureVisuals()

Re-creates the visuals of all placed furniture in the player's current room (e.g. after a Prince order changed them).

## Quests

### `op 238` — IsQuestNpcGroupAvailable(max_distance, primary, others)

Sets reg0 = 1 if the primary NPC and all listed NPCs are free (not asleep, not busy, not already in an event) and every listed NPC is within the given distance of the primary; else 0. Used to decide whether a group scene can start.

Args:
  0. max_distance (corpus 64/120/180/240)
  1. primary (>= 48 = no-op (reg0 not written))
  2. others (count = argc - 2)

### `op 239` — IsQuestNpcGroupAvailable(max_distance, primary, others)

Sets reg0 = 1 if the primary NPC and all listed NPCs are free (not asleep, not busy, not already in an event) and every listed NPC is within the given distance of the primary; else 0. Used to decide whether a group scene can start.

Args:
  0. max_distance (corpus 64/120/180/240)
  1. primary (>= 48 = no-op (reg0 not written))
  2. others (count = argc - 2)

### `op 507` — PopulateSlayRequest(monster, count, reward_categories)

Post a 'slay monsters' request (kind 1) into the talking NPC's request record, with rewards rolled from the given categories. reg0 = 1 if a target existed.

Args:
  0. monster (monster to slay; 0 = random (DailyVisitor_PickWantedItem: weighted pick of 48..199, 1-in-16 boss band 200..253, story-gated))
  1. count (0 = random 1-4; forced to 1 for ids 200..253)
  2. reward_categories (variable count (up to 4 used); each is rolled once with Item_RollRandomIdInCategory into rewards[0..3]; -1 = skip)

### `op 508` — PopulateQuestKind2RandomRewards(item, npc, count, reward categories...)

Post a 'bring me this item' request (kind 2) for the NPC whose script is running, with randomly rolled reward items. Read it back with the quest-preview op (532).

Args:
  0. item (requested item (+2))
  1. npc (record byte +5; corpus passes an NPC char id (actor(Name) constants, or REG_CHILD_ID))
  2. count (record byte +4 (corpus 1))
  3. reward categories... (up to 4; each rolls one reward item (corpus 51, 49, 46, 10, 3))

### `op 509` — PopulateQuestKind2RandomRewards(item, npc, count, reward categories...)

Post a 'bring me this item' request (kind 2) for the NPC whose script is running, with randomly rolled reward items. Read it back with the quest-preview op (532).

Args:
  0. item (requested item (+2))
  1. npc (record byte +5; corpus passes an NPC char id (actor(Name) constants, or REG_CHILD_ID))
  2. count (record byte +4 (corpus 1))
  3. reward categories... (up to 4; each rolls one reward item (corpus 51, 49, 46, 10, 3))

### `op 510` — PopulateQuestKind2LiteralRewards(target_item, param, count, reward1, reward2, reward3, reward4)

Post a kind-2 (bring an item) request on the script's NPC with fixed reward items instead of random ones. Does nothing if that NPC already has a posted request (except the board record 0).

Args:
  0. target_item (the requested item (record +2))
  1. param (record +5 (corpus 0-17))
  2. count (record +4 (corpus 1))
  3. reward1 (literal reward item (0 allowed))
  4. reward2 (as reward1)
  5. reward3 (as reward1)
  6. reward4 (as reward1)

### `op 511` — PopulateQuestKind3RandomRewards(item A, item B, count, param, reward categories...)

Post a kind-3 request (two item slots) for the NPC whose script is running, with randomly rolled rewards. Unused by the shipped scripts.

Args:
  0. item A (record +6)
  1. item B (record +8)
  2. count (record +4)
  3. param (record +5)
  4. reward categories... (rolled into reward u16s 1-3 (record +16..+21))

### `op 512` — PopulateQuestKind3RandomRewards(item A, item B, count, param, reward categories...)

Post a kind-3 request (two item slots) for the NPC whose script is running, with randomly rolled rewards. Unused by the shipped scripts.

Args:
  0. item A (record +6)
  1. item B (record +8)
  2. count (record +4)
  3. param (record +5)
  4. reward categories... (rolled into reward u16s 1-3 (record +16..+21))

### `op 513` — PopulateQuestKind4RandomRewards(target, param, count, reward_categories)

Post a kind-4 request into the talking NPC's request record, with rewards rolled from the given categories.

Args:
  0. target (record +2 (corpus 13 / 52 / 46))
  1. param (record +5 (corpus: a villager char id, actor(Name)))
  2. count (record +4)
  3. reward_categories (each rolled once into rewards[0..3])

### `op 514` — PopulateQuestKind4RandomRewards(target, param, count, reward_categories)

Post a kind-4 request into the talking NPC's request record, with rewards rolled from the given categories.

Args:
  0. target (record +2 (corpus 13 / 52 / 46))
  1. param (record +5 (corpus: a villager char id, actor(Name)))
  2. count (record +4)
  3. reward_categories (each rolled once into rewards[0..3])

### `op 515` — PopulateQuestKind4LiteralRewards(target_item, param, unused, reward1, reward2, reward3, reward4)

Post a kind-4 request on the script's NPC with a count of 1 and fixed reward items. Skipped if that NPC already has a posted request (except the board record 0).

Args:
  0. target_item (record +2)
  1. param (record +5)
  2. unused (never read (count is forced to 1))
  3. reward1 (literal reward item)
  4. reward2 (as reward1)
  5. reward3 (as reward1)
  6. reward4 (as reward1)

### `op 516` — PostBoardQuestKind5(param)

Overwrite request record 0 (the board record) with a kind-5 entry. Unused by the shipped scripts.

Args:
  0. param (record +5)

### `op 517` — PostBoardQuestKind5(param)

Overwrite request record 0 (the board record) with a kind-5 entry. Unused by the shipped scripts.

Args:
  0. param (record +5)

### `op 518` — PostBoardQuestKind6(param, count)

Overwrite request record 0 (the board record) with a kind-6 request that has no target item and no rewards.

Args:
  0. param (record +5)
  1. count (record +4)

### `op 519` — PostBoardCraftQuest(category, item, param, count)

Posts a 'craft this item' request (kind 7) as request record 0 and returns the item's recipe ingredients: reg0 = ingredient count, reg1..reg6 = ingredient item ids. Unused by the shipped scripts.

Args:
  0. category (selects the craft archive (CraftData_ResolveArchiveIdFromCategory))
  1. item
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  2. param (stored at record +5)
  3. count (stored at record +4)

### `op 520` — PostQuestGoalNumber(goal, rewards)

Posts a request whose objective is reaching a number (a skill level, a tame count ...), with literal reward items. The request scene itself checks completion.

Args:
  0. goal (shown to the player (skill level, count ...); not checked by the engine)
  1. rewards (written verbatim; 0 ends the list)

### `op 521` — PopulateQuestKind9LiteralRewards(target, rewards)

Post a kind-9 request (the daily visitor's wanted item) into the talking NPC's request record with literal reward items, and bind it to this script for the following accept/complete ops.

Args:
  0. target (record +2 (corpus: the daily visitor's wanted item from GetDailyVisitor))
  1. rewards (literal reward item ids into rewards[0..3]; 0 ends the list)

### `op 522` — PopulateQuestKind10RandomRewards(reward categories...)

Post a kind-10 request (no item target) for the NPC whose script is running, with rolled rewards, and remember it for the script. Used before quest completion scenes.

Args:
  0. reward categories... (each rolls one reward item; 0 ends the list)

### `op 523` — PostQuestLiteralRewards(rewards)

Posts a request with no target item (kind 10) and fixed reward items; the request scene checks completion itself.

Args:
  0. rewards (written verbatim; 0 ends the list (a lone 0 = no reward))

### `op 525` — CompleteQuest()

Complete the request bound to this script: count the clear, tell the client NPC (friendship reaction), add prince points and mark the record done. It gives no items; the reward popup op does that.

### `op 528` — GetRequestRewardItem(record, index)

Get one reward item id of a request record. reg0 = item id (0 = none).

Args:
  0. record (request record index (< 24; 0 = the board record); not range-checked)
  1. index (reward slot; >= 4 returns 1)

### `op 529` — ClearAllRequestRecords()

Erase all 24 request records (the board record and every villager's request, including their status bits).

### `op 530` — CommitQuestAcceptance()

Accept the request the current NPC offered: marks it accepted and active and binds it to this script (so CompleteQuest can finish it later).

### `op 531` — ClearBoardRequest()

Clear the board request (record 0) and run the em.bin sub-event common cleanup. Unused by the shipped scripts.

### `op 532` — GetNpcQuestPreview()

Reads the request posted by the NPC being talked to: reg0 = target item, reg1 = count, reg2-reg4 = reward items, reg5 = extra byte, reg6 = 1 if accepted. Scripts copy these into text variables to phrase the request.

### `op 535` — GetQuestRemainingByItem(item)

Intended to put how many more of an item a request still needs into reg0. Broken: the number of request records it searches is garbage, so the result is unreliable (retail never uses it).

Args:
  0. item (target item of a request)
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 536` — StartReservedSubEvent()

Start the reserved town sub-event (if none is running): move REG_SUBEV_RSV into REG_SUBEV_NOW and run its setup. Placed at the start of sub-event scripts.

### `op 537` — QueueSubEventGoalKind2(item, npc, count, ignored...)

Add a kind-2 goal ('bring item') to the running sub-event's goal list (max 20). Does nothing if no sub-event is running.

Args:
  0. item (+2)
  1. npc (+5 (corpus: actor(Margaret)))
  2. count (+4)
  3. ignored... (reward categories are ignored in this mode)

### `op 538` — QueueSubEventGoalKind2(item, npc, count, ignored...)

Add a kind-2 goal ('bring item') to the running sub-event's goal list (max 20). Does nothing if no sub-event is running.

Args:
  0. item (+2)
  1. npc (+5 (corpus: actor(Margaret)))
  2. count (+4)
  3. ignored... (reward categories are ignored in this mode)

### `op 539` — QueueSubEventGoalKind3(taste_of, gift_tier, count, npc, ignored...)

Add a kind-3 goal to the running sub-event's goal list (max 20). Unused by the shipped scripts.

Args:
  0. taste_of (+6: whose gift taste the item is judged by)
  1. gift_tier (+8: 1 neutral, 2 disliked, 3 liked, 4 loved, 5 signature dislike)
  2. count (+4)
  3. npc (+5: the NPC who must receive the item)
  4. ignored... (reward categories ignored)

### `op 540` — QueueSubEventGoalKind3(taste_of, gift_tier, count, npc, ignored...)

Add a kind-3 goal to the running sub-event's goal list (max 20). Unused by the shipped scripts.

Args:
  0. taste_of (+6: whose gift taste the item is judged by)
  1. gift_tier (+8: 1 neutral, 2 disliked, 3 liked, 4 loved, 5 signature dislike)
  2. count (+4)
  3. npc (+5: the NPC who must receive the item)
  4. ignored... (reward categories ignored)

### `op 541` — QueueSubEventGoalKind4(item_category, npc, count)

Append a kind-4 goal to the current sub-event's goal queue (only while a sub-event is running).

Args:
  0. item_category (+2: rf3ItemList category byte of the item (0 = crops))
  1. npc (+5: the NPC who must receive the item)
  2. count (entry +4)

### `op 542` — QueueSubEventGoalKind4(item_category, npc, count)

Append a kind-4 goal to the current sub-event's goal queue (only while a sub-event is running).

Args:
  0. item_category (+2: rf3ItemList category byte of the item (0 = crops))
  1. npc (+5: the NPC who must receive the item)
  2. count (entry +4)

### `op 543` — QueueSubEventGoalKind5(npc)

Add a kind-5 goal to the running sub-event's goal list (max 20), e.g. 'talk to this villager'. Does nothing if no sub-event is running.

Args:
  0. npc (+5; corpus passes an NPC char id (actor(Name)))

### `op 544` — QueueSubEventGoalKind5(npc)

Add a kind-5 goal to the running sub-event's goal list (max 20), e.g. 'talk to this villager'. Does nothing if no sub-event is running.

Args:
  0. npc (+5; corpus passes an NPC char id (actor(Name)))

### `op 545` — QueueSubEventGoalKind6(npc, count)

Append a kind-6 goal to the current sub-event's goal queue (only while a sub-event is running).

Args:
  0. npc (+5: the NPC who must receive the item)
  1. count (entry +4)

### `op 546` — QueueSubEventCraftGoal(category, item, npc, count)

Queue form of PostBoardCraftQuest: while a sub-event is running, adds a 'craft this item' goal to the sub-event goal queue, and returns the recipe ingredients like op 519. Unused by the shipped scripts.

Args:
  0. category
  1. item
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  2. npc (+5: the NPC who must receive the item)
  3. count (record +4)

### `op 547` — QueueSubEventGoalKind10(ignored...)

Add an empty kind-10 goal to the running sub-event's goal list (max 20). Unused by the shipped scripts.

Args:
  0. ignored... (category args are ignored in this mode)

### `op 548` — CompleteAllSubEventGoals()

Mark every active goal in the sub-event goal list as complete. Unused by the shipped scripts.

### `op 549` — FinishCurrentSubEvent()

End the running town sub-event: mark it done, clear the sub-event state and goal queue, reset per-villager sub-event bits, refresh schedules and add prince points. Does nothing if no sub-event is running.

### `op 551` — ResetSubEventGoals()

Empty the sub-event goal list.

### `op 552` — GetSubEventGoalRemaining(item)

Sets reg0 to how many more of an item the current sub-event goal still needs (0 if done or not found).

Args:
  0. item
     - *(enum: 1108 values — use the in-editor picker or the id database)*

## Scene flow / control

### `op 2` — Wait(duration)
*verified:* yes, in game

Pauses the script for a time. 12000 units = 1 second (200 per frame), so 6000 = half a second and Wait(1) yields exactly one frame.

Args:
  0. duration (200 = 1 frame, 12000 = 1 s; 1..200 = one frame) — verified in game

### `op 3` — WaitReset(duration)

Like Wait, but first marks the scene controller as out of dialogue (the same idle write EndDialogue does, without closing the portraits), then waits the given time. Authors use it right before fades/warps after a talk.

Args:
  0. duration (200 = 1 frame, 12000 = 1 s; 1 = yield one frame)

### `op 4` — WaitPlain(duration)

Pause the script for the given time, like Wait but without advancing the quest-reaction state. Authors use WaitPlain(1) to yield a single frame right after spawning actors.

Args:
  0. duration (200 = 1 frame, 12000 = 1 s; 0 = no wait)

### `op 91` — SetSceneBit(bit, on)

Set or clear one bit of the running script host's local bit field (host+404).

Args:
  0. bit
  1. on (non-zero sets, 0 clears)

### `op 198` — WaitForPlayerEffect()
*verified:* yes, in game

Wait until the running screen-shake / player effect task ends. In the shipped scripts it always follows ShakeCamera.

### `op 230` — SetSceneCast(mode, cast)

Set up the cast of a scene: with mode 1 every villager not listed (and every current event participant) is hidden and taken off its routine; mode 0 shows them again. NPCs the scene moved are put back per their schedule.

Args:
  0. mode (1 = hide everyone not in the cast (scene start), 0 = show them again)
  1. cast (villager ids 1..23 that stay visible (variable count); ids >= 24 have no effect here. With nobody to keep, list the player: SetSceneCast(0, tag3(0)) is the shipped form)

### `op 231` — SetSceneCast(mode, cast)

Set up the cast of a scene: with mode 1 every villager not listed (and every current event participant) is hidden and taken off its routine; mode 0 shows them again. NPCs the scene moved are put back per their schedule.

Args:
  0. mode (1 = hide everyone not in the cast (scene start), 0 = show them again)
  1. cast (villager ids 1..23 that stay visible (variable count); ids >= 24 have no effect here. With nobody to keep, list the player: SetSceneCast(0, tag3(0)) is the shipped form)

### `op 242` — ContinueNormalTalk()

Pass the conversation on to the NPC's next kind of talk: when this scene ends, the game moves the talk on by one step and runs the NPC's talk again, so the next talk entry plays (in the end their usual chat). Talk scenes use it on branches that have nothing to say, often as the whole scene (ContinueNormalTalk(); RET). Only acts in a scene started by talking to someone.

### `op 285` — SetSceneReadyFlag(mode, unused)

Sets bit 0 of the scene context's +72 flags when the first argument is 0. Retail brackets one player move with (0, 1) and (0, 0), which looks like a set/clear pair, but on PC both calls just set the bit.

Args:
  0. mode (0 = set host+72 bit 0; anything else = nothing)
  1. unused (retail passes 1 before a move and 0 after it)

### `op 332` — WarpToMap(map, x, y, event)

Move the player to another map at the given tile (usually after fading to black), optionally starting an event on arrival. The script normally ends right after it.

Args:
  0. map (a map id (map(MAP_X)))
  1. x
  2. y
  3. event (event/scene started on arrival; 0 = none)

### `op 333` — WarpToMapInSubEvent(map, x, y, event)

Like WarpToMap, but marks the arrival as part of the current sub-event (remembers GF_REG_SUBEV_NOW). Unused by the shipped scripts.

Args:
  0. map
  1. x
  2. y
  3. event (0 = none)

### `op 337` — WaitForFade()
*verified:* yes, in game

Wait until the current screen fade (FadeScreen / FadeScreenToClear) has finished on both screens.

### `op 370` — SetSceneStateBit1()

Set bit 1 of the scene context's state word (+120). Retail sets it before spawning a temporary rideable event actor.

### `op 375` — OpenMenu(menu)

Open one of the game's menu screens by id (save, name entry, calendar, storage, cooking, crafting, shipping bin, ...) and wait until it has closed.

Args:
  0. menu (World_DispatchInteractionEvent cases (WORLD_INTERACTION_ACTIONS has every id): 1 save, 2 load, 3 request notebook, 4-9 name entry (hero, farm, fields 1-4), 10 shipping records, 11 calendar, 12 Storage, 14 chemistry, 16-22 cooking, 23 Fridge, 25/26 backup save, 28-42 name entry (barns, children), 45 Bookshelf, 51/57 monster name entry, 53 Shipping Box, 54 Weapon Box, 55 Closet, 56 Farm Tool Box, 58-73 forge / crafting table, 74 Shop Box, 75-89 shops, 90 birthday. 24, 27 and 52 open nothing; 0 is ignored; any other id (13, 15, 46-50, 91+) opens the save-data inheritance screen (pick a save to inherit items, levels, skills and monsters from))
     - `1` = Save
     - `2` = Load
     - `3` = MessageBoard
     - `4` = NameEntry_Hero
     - `5` = NameEntry_Farm
     - `6` = NameEntry_Field1
     - `7` = NameEntry_Field2
     - `8` = NameEntry_Field3
     - `9` = NameEntry_Field4
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
     - `24` = (nothing)
     - `25` = BackupSaveNow
     - `26` = BackupSaveNow
     - `27` = (nothing)
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
     - `44` = RequestNotebook(mode 3)
     - `45` = Bookshelf
     - `51` = NameEntry_TamedMonster
     - `52` = (nothing)
     - `53` = ShippingBin
     - `54` = WeaponBox
     - `55` = Closet
     - `56` = FarmToolBox
     - `57` = NameEntry_FarmMonster
     - `58` = Forge_ShortSword
     - `59` = Forge_LongSword
     - `60` = Forge_Spear
     - `61` = Forge_AxeHammer
     - `62` = Forge_Axe
     - `63` = Forge_DualBlades
     - `64` = Forge_Fist
     - `65` = Forge_Staff
     - `66` = Forge_FarmTool
     - `67` = Craft_Armor
     - `68` = Craft_Shield
     - `69` = Craft_Headgear
     - `70` = Craft_Shoes
     - `71` = Craft_Accessory
     - `72` = Forge_UpgradeWeapon
     - `73` = Craft_UpgradeArmor
     - `74` = ShopBox
     - `75` = Shop_WeaponFarmTool
     - `76` = Shop_Accessory
     - `77` = Shop_ExcavatedEquipment
     - `78` = Shop_HospitalMedicine
     - `79` = Shop_Flower
     - `80` = Shop_FlowerExpanded
     - `81` = Shop_General
     - `82` = Shop_GeneralExpanded
     - `83` = Shop_Ability
     - `84` = Shop_Magic
     - `85` = Shop_Jewel
     - `86` = Shop_SakuTuner
     - `87` = Shop_Yue
     - `88` = Shop_Restaurant
     - `89` = Shop_FishMarket
     - `90` = BirthdayEntry
     - `200` = InheritSave

### `op 376` — OpenShop(shopkeeper, shop_action, unused)

Open a shopkeeper's shop menu and wait until the player leaves it. The shopkeeper and today's weekday decide which stock variant is used. Follow with ConsumeInteractionResult.

Args:
  0. shopkeeper (the NPC running the shop; selects the interaction kind and a weekday (0 -> 22; 8 -> 23 if GF_FLG_DIRUS_FRIENDLY; 13 -> 25 if packed flag 875; 15 -> 24 if EV_DAG_SILENT; 25 -> kind 21 sub 28; 22/23/other -> 26))
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
     - `25` = Raven
  1. shop_action (75-89 (Shop_WeaponFarmTool, Shop_Accessory, ... Shop_SakuTuner 86))
     - `75` = Shop_WeaponFarmTool
     - `76` = Shop_Accessory
     - `77` = Shop_ExcavatedEquipment
     - `78` = Shop_HospitalMedicine
     - `79` = Shop_Flower
     - `80` = Shop_FlowerExpanded
     - `81` = Shop_General
     - `82` = Shop_GeneralExpanded
     - `83` = Shop_Ability
     - `84` = Shop_Magic
     - `85` = Shop_Jewel
     - `86` = Shop_SakuTuner
     - `87` = Shop_Yue
     - `88` = Shop_Restaurant
     - `89` = Shop_FishMarket
  2. unused (retail passes 0)

### `op 559` — StartFestivalContest(contest)

Start a festival contest mini-game (eating contest, quiz, monster contest ...). The contest runs as its own task; the script continues and should wait/fade as needed.

Args:
  0. contest (1 ONI, 2 EAT (eating contest), 3 MOKO, 4 MATO (target shooting), 5 YUKI, 6 QUIZ, 7 PET)

### `op 560` — StageSceneNpcs()

At the start of a festival/group scene, pick and stage the participating NPCs and companions, and return the four participant ids in reg0-reg3 for placement.

### `op 574` — ShuffleSceneBuffer(count)

Fill the scene's shuffle buffer with the numbers 0..count-1 in random order; read them with GetShuffleValue (op 575).

Args:
  0. count (values 0..count-1 (capped at 64))

### `op 633` — ResetActionEventId()

Reset the last-dispatched action-event id to 0. Unused by the shipped scripts.

### `op 634` — SetActionTriggerByte(index, value)

Set one of the scene's three action-trigger bytes; read back with GetActionTriggerByte (op 635).

Args:
  0. index (0-2 (larger or negative values are clamped to 2))
  1. value (0-255)

### `op 682` — SetSceneField400(value)

Set a scene state field to 0, 1 or 2 (purpose not established; one use).

Args:
  0. value (other values are ignored)

### `op 697` — ReturnToTitle()

Leave the game and go back to the title screen (used after endings and in the dev menu, after a fade: FadeScreen(16, 1500), which fades to white).

## Queries

### `op 105` — GetEventActorIndexStub(event actor id)

Leftover lookup that always returns 0 in reg0. It searches the event-actor table for the id but throws the result away, so scripts should not rely on it.

Args:
  0. event actor id (event-actor id (corpus 0, 2, 100); ignored for the result)

### `op 135` — GetActorPosition(actor)
*verified:* yes, in game

Read an actor's current position into reg0 (X) and reg1 (Y). If an NPC's actor is not spawned, its stored position is used. Positions are in script units (world >> 12); one map-editor tile is 8 units (tile = value / 8).

Args:
  0. actor (0 = player, 1-47 = NPC/villager char id (see the character table); >= 48 writes nothing) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 136` — GetActorPosition(actor)
*verified:* yes, in game

Read an actor's current position into reg0 (X) and reg1 (Y). If an NPC's actor is not spawned, its stored position is used.

Args:
  0. actor (0 = player, 1-47 = NPC/villager char id (see the character table); >= 48 writes nothing) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 148` — HasPlayerAccessoryEffect40000()

Check whether the player wears the Rosary (accessory special bit 0x40000): reg0 = 1 if so, else 0.

### `op 182` — GetEventActorPosition(event key)

Read a spawned event actor's position into reg0 (X) and reg1 (Y). The event-actor counterpart of GetActorPosition (op 135). Positions are in script units (world >> 12); one map-editor tile is 8 units (tile = value / 8).

Args:
  0. event key

### `op 213` — GetPlayerPosition()
*verified:* yes, in game

Stores the player's position in reg0 (x) and reg1 (y), and 1 in reg2. Positions are in script units (world >> 12); one map-editor tile is 8 units (tile = value / 8).

### `op 216` — HasNpcStoryFlag(character)
*verified:* yes, in game

Check whether the player has met a villager (the flag SetNpcStoryFlag sets; it is what keeps the first-meeting introduction from replaying). For child slots 24-47 it checks the child record instead.

Args:
  0. character (1-23 villagers (0 = player also maps to bit 981); 24-47 = child slots) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 218` — GetNpcFriendshipLevel(npc)
*verified:* yes, in game

Read an NPC's friendship level (not raw points) into reg0. Id 0 means the NPC the player is talking to.

Args:
  0. npc (0 = the NPC currently being talked to; 1-23 villagers; 24-47 child/extra slots) — verified in game
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 219` — GetNpcFriendshipLevel(npc)
*verified:* yes, in game

Read an NPC's friendship level (not raw points) into reg0. Id 0 means the NPC the player is talking to.

Args:
  0. npc (0 = the NPC currently being talked to; 1-23 villagers; 24-47 child/extra slots) — verified in game
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 220` — IsAllNpcFriendshipAtLeast(mode, level)

Check whether every villager currently in town has at least the given friendship level. Pass 0 as the first argument.

Args:
  0. mode (0 = all available villagers; 1-47 = broken single mode (see details); >= 48 = op does nothing)
  1. level (1-10 in the corpus)

### `op 226` — GetActorMapId(actor)
*verified:* yes, in game

Get the map (room) id a character is currently in; 0 gives the player's current map. Scripts compare two results to test whether characters are in the same place.

Args:
  0. actor (0 = the player's current map; 1..47 = where that NPC currently is) — verified in game
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 227` — IsActorInMap(actor, maps)

Sets reg0 = 1 if the actor is currently on one of the listed maps, else 0. There is no count argument: every argument after the first is a map id.

Args:
  0. actor (>= 48 = no-op (reg0 not written))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. maps (compared against the actor's current map; shipped scripts pass map ids (map(MAP_X) constants))

### `op 228` — IsActorInMap(actor, maps)

Sets reg0 = 1 if the actor is currently on one of the listed maps, else 0. There is no count argument: every argument after the first is a map id.

Args:
  0. actor (>= 48 = no-op (reg0 not written))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. maps (compared against the actor's current map; shipped scripts pass map ids (map(MAP_X) constants))

### `op 229` — IsNpcOffScheduleRoute(npc)

Returns 1 in reg0 when the NPC is NOT currently travelling along its daily schedule route between maps, 0 while it is. Unused by the shipped scripts.

Args:
  0. npc (1-47 (entry must exist - no null check))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 232` — HasNpcGreetedToday(npc)

Check whether a villager's daily greeting counts as played (reg0 = 1/0): set by SkipNpcDailyGreeting (ops 233 / 234) or by the game after the greeting scene ran. Reads both flags: the daily GameFlags bit (cleared each morning) and the record bit (cleared by the next talk). In game: 1 right after op 233 / 234, 0 for untouched villagers; the talk-start code reads the same value.

Args:
  0. npc (0-47 (hidden bits exist for 0-23))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 235` — IsNpcNearbyToChimeIn(npc)

Check whether an NPC is within 48 units of the character running this script and both are free to talk. Each successful check flips a bit, so repeated checks alternate 1, 0, 1 ... (used to alternate between two lines).

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 236` — IsNpcInRangeToChimeIn(npc, range)

Check whether another villager is around to chime in on the current conversation: reg0 = 1 if the NPC has been met, is awake and within range of the talking actor. The check alternates: it succeeds only on every other passing call.

Args:
  0. npc
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. range (max distance from the script's own actor; 0 = no range check)

### `op 237` — GetNpcPairChimeInState(npc_a, npc_b, range)

Pick which of two nearby villagers chimes in on a conversation: reg0 = 0..3 from a small state machine (1 = both, 2 = A, 3 = B, 0 = nobody), stepping on each call.

Args:
  0. npc_a (1..47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. npc_b (1..47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  2. range (max distance of each NPC from the script's own actor; 0 = both count as close)

### `op 240` — IsNpcGroupPresentNearby(max_distance, primary, others)

Check that a group of villagers are all present, awake and free, each within range of the first one. reg0 = 1 if so. With only (distance, npc) it just checks that one NPC is present and free.

Args:
  0. max_distance (max distance of each other NPC from the primary (corpus always 180))
  1. primary (1..47)
  2. others (variable count, taken from argc; may be empty)

### `op 241` — IsNpcGroupPresentNearby(max_distance, primary, others)

Check that a group of villagers are all present, awake and free, each within range of the first one. reg0 = 1 if so. With only (distance, npc) it just checks that one NPC is present and free.

Args:
  0. max_distance (max distance of each other NPC from the primary (corpus always 180))
  1. primary (1..47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  2. others (variable count, taken from argc; may be empty)

### `op 245` — GetGiftAffinity(npc, item)

Sets reg0 to the NPC's gift-reaction value for an item (how much they like it). Unused by the shipped scripts.

Args:
  0. npc (>= 48 = no-op)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. item (masked to 11 bits (0-2047))
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 247` — GetApproachPos(mover, target)

Get the position right next to the target on the mover's side (one step back from the target toward the mover), i.e. where the mover should walk to stand in front of the target. reg0 = x, reg1 = y (tiles).

Args:
  0. mover (0 = player, 1..47 NPC: the actor that will walk)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin
  1. target (0 = player, 1..47 (looked up with Npc_FindActorByNpcId when the mover is an NPC))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 255` — GetActorStatusEffect(target)
*verified:* yes, in game

Read the status effect state of the player (0) or of the companion being talked to. reg0: 0 fine, 1 asleep, 4 fatigue only, 2 any other status effect (or fatigue plus another), 3 no status effect but HP at half or below. reg1 names one status effect: 115 poison, 116 paralysis, 117 seal, 118 cold (sleep / fatigue / faint have none). Other statuses (e.g. the 'ate a dish' apple) are not part of it. Only the player (0) or a party companion: any non-zero argument means 'the companion I am talking to' (the value itself is ignored). Not talking to a companion, it reads companion slot 2 instead, and with that slot empty it dereferences a missing actor (crash).

Args:
  0. target (0 = the player; any non-zero value = the party companion currently being talked to (the number is ignored)) — verified in game

### `op 257` — IsNpcGroupFreeToComment(npcs)

Check that every listed villager is free to make an ambient comment (met, present, awake, not busy, not blocked by a story gate). reg0 = 1 if all are.

Args:
  0. npcs (variable count (from argc); 0 = the player's spouse (REG_WIFE_ID); ids >= 48 are skipped)

### `op 258` — IsNpcGroupFreeToComment(npcs)

Check that every listed villager is free to make an ambient comment (met, present, awake, not busy, not blocked by a story gate). reg0 = 1 if all are.

Args:
  0. npcs (variable count (from argc); 0 = the player's spouse (REG_WIFE_ID); ids >= 48 are skipped)

### `op 259` — PickRandomVillagers(count, excluded...)

Pick a number of different random villagers and put their character ids in reg0, reg1, ... - excluding the listed ones and anyone unavailable today. Used for festival crowd lines.

Args:
  0. count (how many distinct villagers to pick (first 10 go to reg0-reg9))
  1. excluded... (villagers to exclude (0 is ignored))

### `op 260` — GetHostActorHpState()

Read the HP state of the actor this script runs for into reg0: 2 = HP is 0, 1 = at or below half HP, 0 = above half.

### `op 262` — GetCurrentInteractionNpc()
*verified:* yes, in game

Sets reg0 to the char id of the NPC the player is currently talking to or interacting with (0xFFFF if none).

### `op 265` — IsPlayerOrCompanionDowned(who)
*verified:* yes, in game

Check whether the player (arg != 0) or either of the two companions (arg 0) is knocked out; result in reg0. Unused by the shipped scripts.

Args:
  0. who (non-zero = the player; 0 = either companion) — verified in game

### `op 268` — IsNpcAtScheduledSpot(npc...)

reg0 = 1 when every listed NPC has reached the spot set by SetOrClearNpcSchedule and is available. Special: with 0 as the first argument, reg0 = 1 only when NONE of the villagers with a scripted spot has arrived yet.

Args:
  0. npc... (one or more NPC ids; a first arg of 0 switches to the all-villager mode)
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 269` — IsNpcAtScheduledSpot(npc...)

reg0 = 1 when every listed NPC has reached the spot set by SetOrClearNpcSchedule and is available. Special: with 0 as the first argument, reg0 = 1 only when NONE of the villagers with a scripted spot has arrived yet.

Args:
  0. npc... (one or more NPC ids; a first arg of 0 switches to the all-villager mode)
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 273` — IsDatingNpc(npc)
*verified:* yes, in game

Check whether the player is dating a villager (record +52 bit 22, set by op 275 when a confession succeeds). With 0 it returns how many villagers the player is dating -- the confession scenes use that count to lower the success odds.

Args:
  0. npc (1..23 -> that villager's flag; 0 -> count of villagers 1..23 with the flag; >= 24 -> 0) — verified in game
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 274` — IsDatingNpc(npc)
*verified:* yes, in game

Check whether the player is dating a villager (record +52 bit 22, set by op 275 when a confession succeeds). With 0 it returns how many villagers the player is dating -- the confession scenes use that count to lower the success odds.

Args:
  0. npc (1..23 -> that villager's flag; 0 -> count of villagers 1..23 with the flag; >= 24 -> 0) — verified in game
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 276` — GetNpcHeldItem(npc)
*verified:* yes, in game

Get the item an NPC is currently holding in its hand (e.g. a gift it is about to hand over). reg0 = item id, or 0 if none.

Args:
  0. npc (1..47) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 277` — GetNpcHeldItem(npc)
*verified:* yes, in game

Get the item an NPC is currently holding in its hand (e.g. a gift it is about to hand over). reg0 = item id, or 0 if none.

Args:
  0. npc (1..47) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 278` — GetNpcFavoriteItem(npc)

Put a random item this NPC likes into reg0 - used to pick the gift an NPC hands the player.

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 279` — GetNpcFavoriteItem(npc)

Put a random item this NPC likes into reg0 - used to pick the gift an NPC hands the player.

Args:
  0. npc (1-47)
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 280` — GetNpcDateState(npc)

Read an NPC's date state into reg0: 0 none, 1 date promised for tomorrow, 2 date is today, 3 on the date, 4 the date went well, 5 declined today.

Args:
  0. npc (1-47 (REG_CHILD_ID also used)) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 282` — IsNpcActorPresent(npc)
*verified:* yes, in game

Check whether an NPC's actor is loaded in the current map and not flagged away (actor+568 bit 0x20000000 clear). reg0 = 1/0.

Args:
  0. npc (1..47) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 283` — GetDateCompanionId()

Sets reg0 to the char id of the party companion who is on a date with the player (a companion whose date state is set), or 0 if none.

### `op 288` — GetNpcOutfit(npc)
*verified:* yes, in game

Sets reg0 to the NPC's current outfit variant (0 = normal; 2 = swimsuit is what the corpus tests for). 1 = pajamas (Forte at night, in game 2026-10-02).

Args:
  0. npc (0 or >= 48 -> reg0 = 0) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 309` — IsPlayerMale()
*verified:* yes, in game

Sets reg0 = 1 when the player character is Lest (male), 0 when Frey (female). Scripts branch on it for gendered lines, nicknames and animations.

### `op 310` — IsPlayerModelLest()
*verified:* yes, in game

Check the player's current MODEL, not the gender: reg0 = 1 when the player actor's model is Lest's (model 1217), 0 for Frey's (1233) or any other model. For a normal Lest or Frey this matches IsPlayerMale (309), which reads the saved character flag; while the player's model is swapped (Player_TransformToCharacterById) this one says 0 even for Lest. It does not check for a missing player actor (crashes in the no-player state). Unused by the shipped scripts; use IsPlayerMale for the gender.

### `op 321` — GetNpcNicknameForPlayer(npc)
*verified:* yes, in game

Sets reg0 to the nickname id the NPC currently uses for the player (0 = the player's own name). Scripts branch on it to pick the matching voice clip.

Args:
  0. npc — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 324` — GetMood(npc)

Get a byte from an NPC's record (+56) that the toolkit calls its mood id. reg0 = the value (0 if no record).

Args:
  0. npc (1..47 (corpus: REG_WIFE_ID))
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
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

Check the actor's status bit 0x400 (per the IDB, 'scripted pose active'). reg0 = 1/0.

Args:
  0. actor (0 = player, 1..47 NPC) — verified in game

### `op 338` — IsNpcOnPlayerMap(npc)
*verified:* yes, in game

reg0 = 1 if the NPC is on the same map as the player, else 0; reg1 = the NPC's current map id (season-adjusted for outdoor maps). Used to check who is around before a scene.

Args:
  0. npc (1-47; 0 = the spouse (GF_REG_WIFE_ID)) — verified in game

### `op 339` — GetNpcCurrentMap(npc)
*verified:* yes, in game

Put the map the NPC is currently on into reg0 (outdoor maps below 0x40 get the season added, giving the seasonal map variant).

Args:
  0. npc (1-47) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
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
*verified:* yes, in game

Read script variable bank 0 at [index] into reg0 - the reader for SetVar0.

Args:
  0. index (0-15 (not bounds-checked)) — verified in game

### `op 344` — GetVar1(index)
*verified:* yes, in game

Read script variable bank 1 at [index] into reg0 - the reader for SetVar1.

Args:
  0. index (not bounds-checked) — verified in game

### `op 346` — GetVar11(index)
*verified:* yes, in game

Reads slot [index] of script-variable bank 11 into reg0. Unused by the shipped scripts.

Args:
  0. index (no bounds check (bank has 16 slots)) — verified in game

### `op 350` — GetVar3(index)
*verified:* yes, in game

Read slot [index] of engine variable bank 3 into reg0 (the shop scripts read slots 0/1 before MyShopAction).

Args:
  0. index (0-51 (corpus 0-14)) — verified in game

### `op 352` — GetVar4(index)
*verified:* yes, in game

Reads slot [index] of script-variable bank 4 into reg0.

Args:
  0. index (no bounds check (bank has 52 slots)) — verified in game

### `op 354` — GetVar5(index)
*verified:* yes, in game

Read script variable bank 5 at [index] into reg0 - the reader for SetVar5.

Args:
  0. index (not bounds-checked (array has 52 slots)) — verified in game

### `op 356` — GetVar6(index)
*verified:* yes, in game

Reads slot [index] of script-variable bank 6 into reg0.

Args:
  0. index (no bounds check (bank has 52 slots)) — verified in game

### `op 358` — GetVar7(index)
*verified:* yes, in game

Read slot [index] of engine variable bank 7 into reg0.

Args:
  0. index (0-51 (corpus 0-29)) — verified in game

### `op 360` — GetVar8(index)
*verified:* yes, in game

Read script-variable bank 8 at [index] into reg0 (16 slots). The pair of SetVar8.

Args:
  0. index (NOT bounds-checked) — verified in game

### `op 363` — GetNpcBirthday(slot, character)
*verified:* yes, in game

Look up a character's birthday: season into reg0, day into reg1, and also bank 0 [slot] = the season's name line and bank 3 [slot] = the day, so ＠キャラn＠ ＠n＠ in the next DIALOG line print '<season> <day>'.

Args:
  0. slot (bank-0 index 0-15 / bank-3 index 0-51 for the text codes) — verified in game
  1. character (0 = player (REG_PLAYER_BIRTH_SEASON/DAY); else looked up in the calendar table archive 16340) — verified in game

### `op 367` — GetVar14(index)

Read text-slot entry bank 14 [index] (set by SetTextSlotEntries, op 366) into reg0.

Args:
  0. index (0-15 (not bounds-checked))

### `op 371` — EvalCondScriptA(em_entry)
*verified:* yes, in game

Evaluate condition A of an Event Manager (em.bin) entry and put the result (1/0) into reg0.

Args:
  0. em_entry (e.g. 87, 79, 78, 73 (EV_DATE_APPO, boss rematch checks ...)) — verified in game

### `op 372` — EvalCondScriptB(em entry)

Evaluate condition list B of an em.bin entry (typically the negated/alternate test, e.g. 'not daytime') into reg0. Unused by the shipped scripts.

Args:
  0. em entry

### `op 377` — ConsumeInteractionResult()

Read (and clear) the pending result of the last world interaction (e.g. a shop or OpenMenu menu) into reg0. If nothing is pending, reg0 is left unchanged.

### `op 378` — ConsumeInteractionResult()

Read (and clear) the pending result of the last world interaction (e.g. a shop or OpenMenu menu) into reg0. If nothing is pending, reg0 is left unchanged.

### `op 398` — BuildOutfitChoiceMask(invert)

Prepare the choice list for a change-outfit menu: only outfits the player has unlocked and is not wearing are shown (plus 'normal clothes' when not wearing them). Follow with PROMPT_CHOICE.

Args:
  0. invert (0 = normal; non-zero = invert the mask)

### `op 399` — GetPlayerActionState()

Read the player's current action state number into reg0. Unused by the shipped scripts.

### `op 403` — GetFreeFarmAreas()

For farm areas 1-3 of the field the player is on, reg0/reg1/reg2 = 1 if no monster is assigned to work that area, else 0.

### `op 404` — GetOccupiedFarmAreas(field)

For one farm field, report in reg0-reg2 whether each of its three work areas has a monster assigned.

Args:
  0. field (4-23 = field id; barn rooms 77-126 -> field 4 + 4*((room-77)/10); negative = current room; other -> 4)

### `op 406` — GetFarmMonsterPlantOrder()

Read whether this script's barn monster has the 'also plant seeds' order into reg0 (1/0).

### `op 407` — GetAliveKillTargetCount()

Put the number of monsters still alive on the current map into reg0: the map's tracked monster list (every spawned monster, minion, summon and gate spawn), counting those not flagged defeated. It is the count a sealed room waits on before it opens. CountLivingEnemies (op 408) is the same count without monster ids 141 / 142.

### `op 408` — CountLivingEnemies()

Sets reg0 to the number of living monsters on the map, not counting the two boss ids 141 and 142. Unused by the shipped scripts. Same list as GetAliveKillTargetCount (op 407), which also counts 141 / 142.

### `op 409` — GetTamedMonsterCount()
*verified:* yes, in game

Get how many monsters the player owns (occupied slots of the 200-entry monster table). reg0 = count.

### `op 411` — GetCompanionMonsterData(target, kind)

Multi-purpose monster query: stats of a companion monster, or barn/farm information (which monster works each farm area, a monster's friendship level, work state, plant-seed order). The second argument selects what is returned in reg0-reg7.

Args:
  0. target (kinds 0-4: 0 = companion 1, 1 = companion 2; kinds 6 and 10: g_MonsterFarmTable record index (e.g. from kind 5 or SetVar8 -1/-2); kinds 5, 7, 8, 9: ignored)
  1. kind (0 base stats, 1/2 s16 stat blocks, 3 dword block, 4 monster fields + friendship, 5 area workers, 6 plant-order bit, 7 barn workload, 8 this monster's work state, 9 this monster's friendship, 10 record's friendship)

### `op 414` — GetChoiceIndexAndItem()

Get the result of the last item-pick menu: reg0 = chosen slot index (0-7), reg1 = the item id.

### `op 416` — GetPlayerVariable(code, skill)
*verified:* yes, in game

Get a player value chosen by a letter code (gold, level, fodder, a skill level, stone, compost, best skill level). reg0 = the value.

Args:
  0. code ('d' 100 gold, 'f' 102 player level (stored level + 1), 'g' 103 fodder in the barn bin, 'h' 104 level of skill [skill], 'i' 105 stone, 'j' 106 compost, 'k' 107 highest skill level; 0..39 = that skill's level; other = 0) — verified in game
     - `100` = Gold
     - `102` = Level
     - `103` = Fodder
     - `104` = Skill
     - `105` = Stone
     - `106` = Compost
     - `107` = MaxSkillLevel
  1. skill (only read for 'h') — verified in game
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

### `op 418` — HasBackpackRoom()
*verified:* yes, in game

Check whether the player's backpack has at least one free slot (within the currently unlocked size) before handing over an item.

### `op 419` — HasRoomForItem()

reg0 = 1 if the player has room for an item: a free slot among the first 60 backpack slots, or empty hands. Unused by the shipped scripts.

### `op 420` — HasBackpackFreeSlots(count)
*verified:* yes, in game

Check whether the backpack has at least the given number of empty slots.

Args:
  0. count (number of empty slots needed (0 behaves like 1)) — verified in game

### `op 426` — IsPlayerHoldingItem()
*verified:* yes, in game

reg0 = 1 if the player is carrying an item in their hands (over the head), else 0. Unused by the shipped scripts.

### `op 431` — HasItem(item, min_count, min_level)
*verified:* yes, in game

Sets reg0 = 1 if one backpack slot (or the held/equipped extra slots) has the item with at least the given count, and that stack's highest level is at least min_level, else 0. reg2 = a flag bit of the matching stack.

Args:
  0. item — verified in game
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. min_count (count in ONE slot; a split stack is not added up) — verified in game
  2. min_level (the stack's highest level >= this (a stack keeps up to 9 per-item levels sorted highest first; only the first is read); 0 or -1 = any level) — verified in game

### `op 432` — GetSeedCropInfo(seed_item)

Look up a seed's crop data: whether it grows in the current season, how many days it takes, plus two item-type values. No field tile is inspected.

Args:
  0. seed_item (a seed item id)
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 433` — GetFishSizeRecords(fish)

Reads the player's size records for a fish: reg0 = the biggest one caught, reg1 = the smallest.

Args:
  0. fish

### `op 434` — GetItemSellPrice(item)
*verified:* yes, in game

Get an item's sell price for one unit at level 1 (the 'Sell:' on the item screen) into reg0, e.g. to show prices in a scripted menu. Seen in game.

Args:
  0. item (0-1107) — verified in game
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 435` — GetItemBuyPrice(item)
*verified:* yes, in game

Get an item's shop buy price (the 'Buy:' on the item screen) into reg0. Seen in game.

Args:
  0. item — verified in game
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 436` — IsItemStackable(item)
*verified:* yes, in game

Check whether an item stacks. reg0 = 1 if its metadata stack nibble (+5 & 0xF) is > 1, else 0.

Args:
  0. item — verified in game
     - *(enum: 1108 values — use the in-editor picker or the id database)*

### `op 437` — IsItemInCategoryList(item, list)

Check whether an item belongs to one of the present item-category lists (e.g. 'cakes', 'sweets') used for gift reactions. reg0 = 1 if found.

Args:
  0. item
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. list (list index = (u16)(arg + 0x7F00), so 33025 = list 1 ... (rf3PresentCategory.bin, 21 lists))

### `op 438` — HasItemOfCategory(category)

reg0 = 1 if the player has any item of the given category in the backpack (first 60 slots), in their hands, or in equipment record 1.

Args:
  0. category (item-metadata byte +4 (corpus 32))

### `op 440` — GetNpcMapID(char)
*verified:* yes, in game

Get a monster's home map from its rf3NpcParam record (offset 292) into reg0: the map hunting requests send the player to ('Go to ＠マップ０＠ and get rid of ...', via SetVar2). 0 for villagers.

Args:
  0. char (no bounds check) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 441` — IsConfirmButtonDown()

Check whether the player is holding the confirm (advance dialogue) button right now. Retail uses it to let the player skip the staff credits.

### `op 442` — IsStickInputActive()

Check whether the analog stick / d-pad is currently being pushed.

### `op 445` — GetFlagBit(flag)

Read a zone-2 game flag bit into reg0 (1 set / 0 clear) - the reader for SetFlagBit.

Args:
  0. flag (bit zone2_base + id)

### `op 447` — GetWeather()
*verified:* yes, in game

Read the current weather code into reg0 (codes as in SetWeather).

### `op 456` — GetEquippedItemAttr(slot, attr)
*verified:* yes, in game

Get the item equipped in one of the player's equipment slots and one attribute of it: reg0 = item id, reg1 = the chosen attribute (an upgrade, a base material, or one of two hidden sell-price ratings).

Args:
  0. slot (0 weapon/tool, 1 shield, 2 body armor, 3 headgear, 4 shoes, 5 accessory (verified in game); other values fault (null record)) — verified in game
     - `0` = weapon
     - `1` = shield
     - `2` = body
     - `3` = head
     - `4` = shoes
     - `5` = accessory
  1. attr (0-8 the forge upgrade slots, as item ids (verified: a Hammer Piece added at the forge appeared in 0). An upgrade goes into the slot numbered by the item's level BEFORE it (Lv.1 -> 0, Lv.9 -> 8) and raises the level by one (Item_AppendRuneToSlot / Item_ApplyMaterialUpgrade), so an item bought or found at a higher level has empty lower slots, and a Lv.10 item takes no more; ids are stored in 10 bits (an item id >= 1024 would be cut); 9/10/11 the three base materials the item came with, as item ids (a chest Poison Spear: Insect Horn / Insect Carapace / Bird's Feather, unchanged by the upgrade); 12 level_total = the materials' total level (the 30/60/90/120/150 stat-bonus tiers; a Lv.1 Hammer Piece made it 36 -> 37, and the spear's tier-30 M.ATK +5 shows in game); 13 quality_total = the materials' total quality points (25..200 tiers; the Hammer Piece's quality 9 made it 21 -> 30); both also raise the sell price. Neither is the item level, which this op cannot read; 14 dword +8 bits 0-9 = an item id whose base stats the item uses instead of its own (0 on every item tested); other values leave reg1 untouched) — verified in game
     - `0` = upgrade1
     - `1` = upgrade2
     - `2` = upgrade3
     - `3` = upgrade4
     - `4` = upgrade5
     - `5` = upgrade6
     - `6` = upgrade7
     - `7` = upgrade8
     - `8` = upgrade9
     - `9` = material1
     - `10` = material2
     - `11` = material3
     - `12` = level_total
     - `13` = quality_total
     - `14` = stats_from_item

### `op 470` — GetGuestNpcVariant(npc)

Put a guest character's appearance/dialogue variant (rolled daily) into reg0.

Args:
  0. npc (24-47 (temporary/guest characters))

### `op 471` — GetChildFriendPoints(npc)

Get the raw friendship word of a character with id 24-47 (the second friendship table: children and other non-villager residents). reg0 = level*4 + a 2-bit progress count.

Args:
  0. npc (ids outside 24..47 -> 0)

### `op 473` — RollChildDailyPref(child, range)

Returns a random number in [0, range) for a child character that stays the same on later calls: the first call rolls and stores it, later calls return the stored value.

Args:
  0. child (other ids -> reg0 = 0)
  1. range (corpus 104, 114)

### `op 481` — GetPartyMemberId(slot)
*verified:* yes, in game

Read the character id of a party member into reg0 (0 if the slot is empty).

Args:
  0. slot (0 = companion 1, 1 = companion 2 (not range-checked; -1 reads the player)) — verified in game

### `op 482` — GetPartyMemberId(slot)
*verified:* yes, in game

Read the character id of a party member into reg0 (0 if the slot is empty).

Args:
  0. slot (0 = companion 1, 1 = companion 2 (not range-checked; -1 reads the player)) — verified in game

### `op 487` — IsCurrentNpcInParty()

Check whether the NPC the player is talking to is one of the two companions. reg0 = 1/0.

### `op 490` — IsDatePartnerAtDateSpot()

Check whether your date has arrived at the date spot: reg0 = 1 if a companion (or the scene's own actor) is a villager on a date (date state 3) standing on the date map (REG_DATE_MAP). Also sets packed flag 771 when found through a companion slot.

### `op 493` — GetNpcFacingMode()

Sets reg0 to the talking NPC's facing mode (0-2), as set by SetNpcFacingMode; 0 if there is no host NPC.

### `op 504` — GetPartyMemberPosY(slot)
*verified:* yes, in game

Read a party member's Y position into reg0 (0 if the slot is empty). Positions are in script units (world >> 12); one map-editor tile is 8 units (tile = value / 8).

Args:
  0. slot (0 = companion 1, 1 = companion 2, -1 = player) — verified in game

### `op 534` — GetDailyVisitor(mode)

Read the day's travelling-visitor (Sakura merchant) data selected by mode into reg0..reg3.

Args:
  0. mode (0 = offer category A, 1 = offer category B, 2 = visitor npc id / wanted item / price tier (reg0..reg2), 3 = alt wanted item / quantity (reg0..reg1), 9 = the four discount bits (reg0..reg3), 10 = quest id of the posted board record (0 if none))

### `op 561` — GetSceneStateBytes()

Read the current scene's four state bytes (scene +540..+543) into reg0..reg3.

### `op 567` — GetTomorrowsCalendarEvent()

Get the calendar event (festival / birthday row id) scheduled for tomorrow, if that event is enabled; reg0 = event id or 0. Before 6:00 'tomorrow' means today's date.

### `op 568` — GetSceneNpc(index)

Get a festival scene's NPC: index 0 or below = the main NPC, 1-7 = the participant list. reg1 receives a scene status bit.

Args:
  0. index (<= 0 = the scene's primary NPC; 1-7 = participant list entry)

### `op 569` — RankFestivalContestants(player_a, player_b)

Rank three roster NPCs and the player for the current festival contest; the top three (char id, score A, score B) go to reg0..reg8.

Args:
  0. player_a (the player's first score part (corpus: GetFishRecord result))
  1. player_b

### `op 570` — GetTodaysRequestNpc()

Read into reg0 the character id of the NPC whose daily request is active today (0 if none).

### `op 572` — GetSceneScratchByte()

Read the festival scene's scratch byte (set by op 571) into reg0.

### `op 573` — GetFestivalPlacements()

Compute the festival contest placements and read the top four entries (two values each) into reg0..reg7.

### `op 575` — GetShuffleValue(index)

Read entry [index] of the shuffle buffer (op 574) into reg0.

Args:
  0. index (not bounds-checked)

### `op 576` — GetSceneEventNpc(index)

Read the character id stored in scene event-actor slot [index] into reg0 (e.g. the festival placings after GetFestivalPlacements).

Args:
  0. index (0-3 in the corpus (not bounds-checked))

### `op 577` — GetFestivalResults()

Reads the current festival's top four places into registers (reg1/reg3/reg5/reg7 = char id, reg2/reg4/reg6/reg8 = value) and reg0 = the festival's date (season*100 + day). If the player (id 0) placed, the placement is announced to the NPCs.

### `op 579` — GetSceneEventFlags()

Read three scene event fields into reg0..reg2: u16 scene+546, u8 scene+543, u16 scene+548.

### `op 580` — GetGivenItemStats()

Reads stats of the item the player last threw or handed to an NPC (used when judging contest entries). Equipment gives adjusted stat percentages; other items give their level/craft data. reg5 = the item id.

### `op 581` — CompareFishRecord(size)

Compare a catch with the saved biggest-fish record and store it if bigger. reg0 = 0 new record, 1 tie, 2 smaller; reg1 = the previous record.

Args:
  0. size (the catch's size value (corpus: reg1 from the catch message))

### `op 582` — GetFishRecord()

Read the saved largest-fish size rank into reg0 (the fishing contest score).

### `op 588` — HasMapEntityOfKind(kind)

Check whether a piece of furniture of the given kind is placed (active in the furniture registry): reg0 = 1/0. Scenes use it for 'you don't have a wardrobe yet' and similar lines.

Args:
  0. kind (furniture object id -- its sprite is rom:/chr/OBJ_*.bntx at archive id + 933: 325 OBJ_ARSENAL00, 327 / 328 bed / double bed, 335 bookshelf, 341 wardrobe (OBJ_CLOAK00), 343..352 OBJ_COMPO_00..09, 365 OBJ_FARMING00, 366 / 367 fridge, 370 fodder box (OBJ_KAIBA_A), 372 lumber / stone box (OBJ_MATERIAL), 375 OBJ_PASTURE, 380 / 381 shelf, 382 shipping bin (OBJ_SHIPMENT), 387 well)

### `op 592` — CanPlaceFurnitureInRoom(room)

Sets reg0 = 1 if the room has fewer than 16 placed furniture objects (room for one more), else 0.

Args:
  0. room (0 = the current room)

### `op 593` — PickRandomPlacedFurniture(candidates)

Rarely (1 roll in 8) picks one of the listed furniture ids that is placed in the current room and returns it in reg0; otherwise, or when none is placed, reg0 = 0. NPC visit scenes use it to comment on a piece of furniture.

Args:
  0. candidates (repeating an id raises its odds)

### `op 619` — IsPartyInviteAccepted()

Decide whether the NPC being talked to agrees to join the player's party: reg0 = 1 yes, 0 no. The answer is cached for the day.

### `op 622` — GetDifficulty()
*verified:* yes, in game

Sets reg0 to the difficulty: 0 = Easy, 1 = Normal, 2 = Hard (or Hell; the two are not distinguished here).

### `op 626` — IsMazeStageCleared(stage)

reg0 = 1 if the given Sharance Maze stage has been cleared.

Args:
  0. stage (0 Garden of Light ... 5 Banquet of Nightmares) — verified in game

### `op 635` — GetActionTriggerByte(index)

Sets reg0 to one of the three scene action-trigger bytes (the ones SetActionTriggerByte writes). Unused by the shipped scripts.

Args:
  0. index (values > 2 read index 2)

### `op 638` — GetHarvestReport()

Fill reg0-reg3 with the crop items of the weekly harvest report (bumper and poor crop for this week and next), for Arthur's harvest-report text.

### `op 639` — GetPrincePoints()
*verified:* yes, in game

Get the current Prince Points. reg0 = points.

### `op 641` — GetTourists()
*verified:* yes, in game

Get the current tourist count. reg0 = tourists.

### `op 644` — GetPrinceOrderState(order, sub)

Sets reg0 to the state of a Prince Point order: whether it is unlocked/applied (0/1), or an upgrade level for the storage orders.

Args:
  0. order (0-2, 29: applied-order bitsets; 10-28: shop/license unlocks; 31+: storage upgrade levels)
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
  1. sub (usually 0)

### `op 646` — GetPrinceRank()
*verified:* yes, in game

Read the current Prince rank into reg1 (not reg0). Ranks 0-5 = Apprentice, Struggling, Respected, Reliable, Honorable Prince/Princess, Crown of Crowns (verified in game: 1 before an order-sign promotion, 5 = Crown of Crowns after).

### `op 647` — GetPrinceOrderCost(order, currency)

Get the cost of a Prince Point order in the chosen currency (or of an order variant). reg0 = cost.

Args:
  0. order
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
  1. currency (0 PP, 1 lumber, 2 material stone, 3 gold for multi-currency orders (storage 31-38, expansions 39/40, barns 41-50); order 0: festival id; order 29: airship sub 0/1)

### `op 648` — GetShippingCompletionPercent()

Get the shipping-list completion percent (distinct items ever shipped / distinct shippable items * 100, max 100). reg0 = percent.

### `op 649` — GetShippingBoxGold()
*verified:* yes, in game

Sets reg0 to the total sale value of everything in the shipping box (capped at 999,999,999). It is the SELL value (an onigiri read 57; 180 is its shop price).

### `op 650` — GetLifetimeShippedGold()

Sets reg0 to the total gold earned from shipping over the whole save (all categories), capped at 2,000,000,000.

### `op 652` — GetPreviousMapId()
*verified:* yes, in game

Put the id of the map the player came from into reg0 (compared against map globalvars to see where the player entered from). For outdoor maps it is the season-independent base id (coming from the farm read 4, not the seasonal 4-7 variant); from a room, that room's id (Your Room = 64).

### `op 658` — GetDefeatPosition()
*verified:* yes, in game

Sets reg0/reg1 to the tile where the most recently defeated monster fell, e.g. to put the girl where Ambrosia fell. Shipped scenes use it only in monster-defeated scenes (type 17, and the type-68 scene after the Ambrosia fight), followed by a spawn or teleport at (reg0, reg1).

### `op 666` — IsGameClearedSysFlagSet()
*verified:* yes, in game

Check bit 0 of the system-save flags (rf4_sys.sav, shared by all save slots). The bit unlocks the post-game Extra Orders category; scripts set it with op 667.

### `op 668` — IsSaveConfigBit4Set()

Sets reg0 to bit 4 of the system save-config flags (shared by all save slots).

### `op 670` — IsSaveConfigBit5Set()

reg0 = bit 5 of the system-save config flags (meaning not established; the order menu uses it before offering order 96).

### `op 672` — IsSaveConfigBit2Set()

Check bit 2 of the system-save flags (shared by all save slots). The marriage commit sets it (bit 3 instead for one spouse case), so it records a past wedding on this system save.

### `op 673` — IsSaveConfigBit3Set()

Check bit 3 (0x8) of g_saveConfigFlags. reg0 = 1/0. RegisterChildBirth (op 292) sets this bit when the child is id 23 (and bit 2 otherwise).

### `op 674` — GetRuneMedals()
*verified:* yes, in game

Read the player's medal count into reg0 (used by the medal exchange).

### `op 676` — GetMedalGoldRate()
*verified:* yes, in game

Put the Rune Medal to gold exchange rate (always 20) into reg0, for the exchange dialogue text.

### `op 684` — IsProjectorSceneUnlocked(scene)

Check whether a memory scene can be replayed in the Projector. reg0 = 1/0.

Args:
  0. scene (Projector scene index (0 = 'Opening', ...))

### `op 686` — GetFreeLookCameraMode()

Read the free-look camera mode word into reg0; it drops back to 0 when the player leaves free-look, so scripts poll it.

### `op 690` — GetNpcGivenHat(npc)
*verified:* yes, in game

For a villager: reg0 = the headgear they have been GIVEN, as a bitmask (record +252): bit n = item 677 + n (bit 0 Silver Hairpin ... bit 10 Cute Knitting = 1024 ... bit 22 Spring Headdress); gifts add bits, nothing clears them. reg1 = 676 + record byte +256 = the hat picked for them to wear today (each day's spawn rolls 25% to pick one of the given hats), or 0 when none was picked. Used by the 'whose hats am I taking back?' menu. The script language has no bitwise operators: test bit n as (reg0 / 2^n) % 2, e.g. (reg0 / 1024) % 2 for Cute Knitting (in game).

Args:
  0. npc (0 -> reg0 = reg1 = 0) — verified in game
     - `0` = Lest/Frey
     - `1` = Herbert
     - `2` = Clorica
     - `3` = Volkanon
     - `4` = Forte
     - `5` = Kiel
     - `6` = Bado
     - `7` = Margaret
     - `8` = Dylas
     - `9` = Arthur
     - `10` = Porcoline
     - `11` = Xiao Pai
     - `12` = Lin Fa
     - `13` = Amber
     - `14` = Illuminata
     - `15` = Doug
     - `16` = Blossom
     - `17` = Dolce
     - `18` = Jones
     - `19` = Nancy
     - `20` = Leon
     - `21` = Ventuswill
     - `22` = Son
     - `23` = Daughter
     - `24` = Barrett
     - `25` = Raven
     - `26` = Mistress Trupin

### `op 694` — HasClearedAnyMarriage()

reg0 = 1 if a marriage has ever been completed on this system save (the flag MarkSpouseCleared sets).

### `op 695` — IsSpouseCleared(character)

Meant to check whether the game has been cleared with this character as spouse (system save, set by op 620). Because of a bug it always reads bit 0, whatever character is passed. Unused in retail.

Args:
  0. character (intended: the spouse char id; actually ignored except for (1 << id) != 0)

### `op 700` — HasItemWithFlagBit0(item, min_count, min_level)

Sets reg0 = 1 if the player has the item with at least the given count and level AND the stack's flag bit 0 is set, else 0. Like HasItem but the flag bit must be set.

Args:
  0. item
     - *(enum: 1108 values — use the in-editor picker or the id database)*
  1. min_count
  2. min_level (level byte + 1 >= this)

## Other

### `op 527` — AdvanceRng(categories)

Advances the shared random-number generator by performing up to four shop-category rolls and throwing the results away. Unused by the shipped scripts.

Args:
  0. categories (each is rolled once and the result discarded; extra args ignored)

### `op 596` — RollUniformIntegerLessThanN(n)
*verified:* yes, in game

Roll a random integer from 0 to n-1 into reg0.

Args:
  0. n (exclusive upper bound; 0 gives 0) — verified in game

### `op 609` — RollRandomPointInRadiusAroundCenter(x, y, radius)

Picks a random tile within a radius of a centre tile: reg0 = x, reg1 = y (absolute). Points cluster toward the centre (the distance is uniform, not the area).

Args:
  0. x (script units, 8 per tile)
  1. y (script units, 8 per tile)
  2. radius (corpus 4-32)

### `op 631` — GetNameHashRoll(name, modulus)

Turn a name into a fixed number 0..modulus-1 (same name, same result) and put it in reg0 - used for name-dependent comments ('What a lovely name!').

Args:
  0. name (0 player name, 1 farm name, 2-5 'Kardia'/'Alvarna'/'Sharance'/'Norad', 6-15 barn monster name slots 0-9)
  1. modulus (result range 0..modulus-1)

### `op 632` — RollSeededDailyRandom(mode, max)

Put a random number into reg0 that is fixed for the current day (reloading does not change it).

Args:
  0. mode (0 = result 0..max-1; 1 = result 0..100 with max used as a seed offset)
  1. max (range (mode 0) or seed offset (mode 1))

### `op 642` — AddTourists(amount)
*verified:* yes, in game

Add to the town's tourist count (Prince Point system; it shows on the Order Symbol). A negative amount subtracts; the count stays within 0..99,999,999 (both limits seen in game).

Args:
  0. amount (any signed number (the shipped scripts use 10-250); GetTourists reads the count back) — verified in game

### `op 659` — MyShopAction(subcase, args...)

Run one step of the player's own shop (My Shop, the Sakura/tourist stall): check stock, pick what a visitor wants, price it, commit the sale, or start/stop the visitor spawner.

Args:
  0. subcase (0 any item for sale?, 1 pick a visitor's wanted item, 2 barter sale price, 3 sale totals, 4 new-record flag, 5 start tourist spawner, 6 stop it, 7 commit a sale, 8 roll a price variation) — verified in game
     - `3` = sale_totals
     - `4` = new_record_flag
  1. args... (subcase-specific: 1 visitor char id; 2 (roll arg, price %); 7 (count, gold); 8 (base price, tier))

### `op 691` — MultiplyValues(factor1)

Multiply all arguments together and put the result (max 999,999,999) into reg0.

Args:
  0. factor1 (every argument is one factor (variadic))

## No-op (PC-port stub)

### `op 388` — nop()
*verified:* yes, from the exe

No-op: the do-nothing stub; the VM decodes and discards any args and moves on. This is THE nop: `nop` assembles to it, it takes no arguments (4 bytes, as in its 4 shipped uses), and the editor lists only it. The other no-op slots (0, 76, 272, 381, 693, ...) run the same stub and show as nop_N.

### `op 524` — NopCompleteSubEventGoals()
*verified:* yes, from the exe

Does nothing: the handler it shares with op 548 only works for opcodes >= 537. Use op 548 to complete sub-event goals.

## Control opcodes (flow backbone)

These are the VM's control-flow tokens (opcode >= `0xFFF0`), built into the script engine. They structure every scene: dialogue, branches, choices, calls, and the scene end.

### `0xFFFF` — RET

Return-or-end -- the VM's real RETURN instruction (IDA-verified: Script_Opcode_FFFF_EndAndCleanup, RF4S.exe+0x23EBA0). Discards the current frame's locals, then: inside a CALLed subroutine it pops the saved PC and resumes right after the CALL; at the top level (frame base 0) it ends the scene (task state 1 READY). So `CALL -> Lx ... Lx: ... RET` is a subroutine, and only a top-level RET terminates the script. (Displayed as END before 2026-09-01.)

### `0xFFFE` — CALL

Call a subroutine: push the caller's frame base and the return PC onto the operand stack, then jump. The subroutine comes back here when it executes RET (the VM's return).

### `0xFFFD` — RET_NZ

Conditional RET (early-exit guard): evaluate the guard expression -- if it is nonzero/true, do exactly what RET does (return from a CALLed subroutine, or end the scene at top level); otherwise fall through to the next statement. Never emitted in shipped scripts. IDA-verified (Script_VMStep case 0xFFFD -> Script_EvalExpressionOrVar, then Script_Opcode_FFFF_EndAndCleanup when true).

### `0xFFFC` — DIALOG

Show a dialogue line (by text id). The current SPEAKER (set by a SetSpeaker* portrait op, SetSpeakerVoice op 10, or nothing = narration) PERSISTS across consecutive DIALOG lines until the next speaker op or EndDialogue (op 92) — 917 shipped scenes rely on back-to-back lines under one speaker. If an SetNextChoiceDescription (op 615) precedes this line, it does NOT display: it queues as a choice option for a later PROMPT_CHOICE instead. Trap (proven in game 2026-10-02): the game only starts a line whose id differs from the last one it started (g_currentSceneContext+68), and a menu's options go through the same call, so after PROMPT_CHOICE / PROMPT_CHOICE_FORCED that id is the menu's LAST option. A DIALOG of that same line right after the menu is never started and the scene softlocks (state stuck, no input); writing -1 to +68 released it at once, three times. Never follow a menu with its last option's line.

### `0xFFFB` — EVAL

Evaluate an expression and store it into a variable.

### `0xFFFA` — JMP

Unconditional jump.

### `0xFFF9` — BR_NZ

Branch if the guard expression is non-zero (true).

### `0xFFF8` — BR_Z

Branch if the guard expression is 0 (false).

### `0xFFF7` — SWITCH

Indexed jump table: evaluate the selector expression, then jump to targets[value] when 0 <= value < N -- a DENSE 0..N-1 index, not a set of per-case compare values. The comparison is UNSIGNED, so a negative selector (like reg0 = -1 after a cancelled prompt) falls through to the next statement, same as any >= N value. The canonical use is dispatching a choice result: `SWITCH (reg0)` after a staged PROMPT_CHOICE jumps to the picked option's branch. Layout: [op][selector-expr][N][N u16 targets]. IDA-verified (Script_VMStep case 0xFFF7, RF4S.exe+0x23EF60).

### `0xFFF6` — SWITCH_CLAMP

Indexed jump table, always-branch variant of SWITCH: jump to targets[value] when value < N, and CLAMP an out-of-range value (>= N, including negatives -- the compare is unsigned) to the last target (targets[N-1]) rather than falling through -- so it never falls through. Same [op][selector-expr][N][N u16 targets] layout as SWITCH. Used exactly once in the whole game. IDA-verified (Script_VMStep case 0xFFF6).

### `0xFFF5` — PROMPT_CHOICE_FORCED

Present a choice menu with NO cancel key -- one of the N options must be picked (the cancel key does nothing). Same UI as PROMPT_CHOICE: each option is a full u32 rf3mc.<locale> text id (no flag bits; an id past the archive shows entry 0), 4 rows on screen with a wrap-around scrolling list, at most 128 options (the rest are silently dropped); option text goes through the normal ＠ substitution pass. Branches to targets[picked VISIBLE ROW]. reg0 is written ONLY when a visibility mask is set (ops 610/611/612): then only flagged options appear, reg0 = the picked option's ORIGINAL index, the mask is cleared, and the shipped idiom is all targets -> one label + SWITCH on reg0. A mask whose set bits all lie past option N-1 opens an EMPTY menu that crashes on confirm (divide by zero); an all-zero mask shows every option. An unmasked prompt leaves reg0 UNTOUCHED -- shipped scenes carry a GetPlayerPosition result in reg0/reg1 across a Yes/No prompt (the deck-fight chase). CalcChoicePrescroll (613) sets the initially highlighted row. Layout: [op][N][N u16 targets][N u32 items]; size 6N+4. IDA-verified 2026-09-24 (Script_VMStep case 0xFFF5, SceneEvent_FinalizeAndPickFromBitmap, ChoiceDialog_TickStateMachine). Trap (proven in game 2026-10-02): the game only starts a line whose id differs from the last one it started (g_currentSceneContext+68), and a menu's options go through the same call, so after PROMPT_CHOICE / PROMPT_CHOICE_FORCED that id is the menu's LAST option. A DIALOG of that same line right after the menu is never started and the scene softlocks (state stuck, no input); writing -1 to +68 released it at once, three times. Never follow a menu with its last option's line.

### `0xFFF4` — PROMPT_CHOICE

Present a choice menu whose cancel key jumps the cursor to the LAST option (and picks it when already there) -- so make the last option the 'never mind' one. The picked row's target is taken as for PROMPT_CHOICE_FORCED (same UI, 128-option cap, 4 visible rows, visibility-mask and reg0 rules). The CANCEL slot (target[0]) is only used for a NEGATIVE pick, which the menu never produces: 890 of the 891 shipped menus just repeat the last option's target there. Layout: [op][N][cancel u16][N u16 targets][N u32 items]; size = 6N+6. IDA-verified 2026-09-24 (Script_VMStep case 0xFFF4, ChoiceDialog_ConfirmViaScrollArrow, SceneEvent_FinalizeAndPickFromBitmap). Trap (proven in game 2026-10-02): the game only starts a line whose id differs from the last one it started (g_currentSceneContext+68), and a menu's options go through the same call, so after PROMPT_CHOICE / PROMPT_CHOICE_FORCED that id is the menu's LAST option. A DIALOG of that same line right after the menu is never started and the scene softlocks (state stuck, no input); writing -1 to +68 released it at once, three times. Never follow a menu with its last option's line.

### `0xFFF3` — JMP_RAND

Uniform-random jump: pick one of the N targets at random (each 1/N) and jump to it -- the UNWEIGHTED sibling of JMP_WEIGHTED. Takes no operand (the target table is the only data); the pick is an RNG roll in [0, N) via the same VM RNG (reader-vtable +56) that JMP_WEIGHTED rolls its weighted pick with. Layout: [op][N][N u16 targets]. IDA-verified (Script_VMStep case 0xFFF3).

### `0xFFF2` — JMP_WEIGHTED

Weighted-random branch: pick one of N targets at random, each weighted by an expression. Every case's weight is evaluated fresh (so a weight can depend on game state), the weights are summed, then an RNG roll in [0, total) selects a target -- case i fires with probability weight[i] / sum(weights) (weight 0 = never taken). The editable literals on this op ARE those per-target weights, so raising one tilts the odds toward its branch. Layout: [op][N][N u16 targets][N u16 weight-exprs]; size 4N+4. IDA-verified (Script_VMStep case 0xFFF2 -> Script_Opcode_FFF2_ExecPrim, RF4S.exe+0x23EC40).

### `0xFFF1` — FRAME

Frame setup (it does NOT return): sets the frame base to the stack top, reserves N stack words, and falls through. The reserved words are the spill room of the expression evaluator: an expression of depth d writes 2*(d-1) words at the frame base (8-byte {kind, value} slots), and an action pushes its arguments (value, kind) last to first at the stack top = frame base + N. So an action argument that is a nested expression (e.g. reg0 + 1) and not the last one needs N >= 2*(depth-1), or it overwrites the arguments already pushed. Literals, registers and flags (depth 1), branch conditions and EVAL never need it. The shipped scripts never need theirs (FRAME 2 everywhere is compiler slack); the editor adds / raises FRAME by itself when an edit needs it.

## Expression operands (argument encoding)

Action-op arguments and control-op guard/value expressions are not raw integers -- each is a little postfix (RPN) expression evaluated by the game. Most resolve to a single literal, but they can be variables, VM registers, or arithmetic. Leaf operands:

- **int literal** — a constant (u8 / s8 / u16 / s16 / int32).
- **`FLG_`/`REG_` name** (e.g. `REG_WIFE_ID`) — a packed game-flag / register reference (an emdeb.bin variable); shown as `var:0xNN` when the name table is unavailable.
- **`reg0`..`reg9`** — the VM's scratch registers. A query op writes its result to `reg0` (the ctx result slot); a following op / branch reads it.
- **`arr[0xNN]`** — a scene var-array load; **`self`**, **`null`**, **`0`** — fixed leaves.
- **`tag3(N)`** / **`tag4(N)`** (tag bytes 0x03 / 0x04) — typed u32 CONSTANTS, not variables: the instruction receives the number N. The listing always writes this raw form; where the argument slot is known (a character id in actor slots, a map id in the schedule ops) the comment shows it as **`actor(Name)`** / **`map(MAP_NAME)`**, which the assembler also accepts.

Operators build parenthesised infix — binary `*` `/` `%` `+` `-` `<` `>` `<=` `>=` `==` `!=` `&&` `||`; unary negate and logical-not; and the compound-assign forms `=` `*=` `/=` `%=` `+=` `-=` `&&=` `||=` (which write the result back into the target variable, e.g. `REG_X += 1`).

## Event Manager (em.bin) opcodes

Scenes bridge to **em.bin** Event-Manager entries via the bridge action opcodes `EvalCondScriptA` (371), `EvalCondScriptB` (372), `DispatchCondScriptEntry` (373), `RunEmEntryAltAction` (374), `SetFlagBitIfCond` (444) — `EvalCondScriptA` / `EvalCondScriptB` test an entry's conditions, `DispatchCondScriptEntry` / `RunEmEntryAltAction` run its main / alt actions, and `SetFlagBitIfCond` sets a flag when an entry's condition holds — for their *plays-when* conditions and their flag / variable effects. Each entry is its own little bytecode — a system SEPARATE from the rf3.mc VM above — decoded by `rf4s_modkit/emscript.py` and shown/edited in the toolkit's Event Manager. Names come from the debug `emdeb.bin` (shipped alongside em.bin).

**Condition expression opcodes** — `op = byte & 0x7F`; the high bit means "OR with the next expr", so consecutive high-bit exprs form an OR-group and the groups AND together:

- `0` **TRUE**, `1` **FALSE** — constant guards.
- `2`/`3` **CondA**(id) and `4`/`5` **NOT CondA** — test named condition A (entry id as u16 / u32).
- `6`/`7` **CondB** and `8`/`9` **NOT CondB** — test named condition B.
- comparison of two operands: `0x10` == (equal), `0x20` != (not-equal), `0x30` > (greater), `0x40` >= (greater-or-equal) — signed when either operand is a signed literal or signed flag ref.

**Comparison operand types** — `type1 = (op>>2)&3`, `type2 = op&3` :

- `0` u32 literal · `1` signed u32 literal · `2` **query id** (a game-state query id — a live game-state read, shown by its `emdeb.bin` query name) · `3` **flag ref** (an `emdeb.bin` `FLG_`/`REG_` variable: packed sign / size / width + bit-offset). Query ids and flag refs both resolve to their debug names in the editor.

**Action opcodes** — high nibble selects the op; the byte's low bits describe the operand (target mode `(b>>2)&3`, value type `b&3` = same encoding as a comparison operand; result is `target OP value`, target-first — no reverse-sub, unlike the rf3.mc expression VM):

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

368

These slots hold the same do-nothing stub as `nop` (op 388); listings show them as `nop_N` so shipped banks rebuild byte-exact, but `nop` is the one to write: 0, 76, 272, 381, 391, 491, 505, 526, 533, 550, 565, 583, 584, 585, 586, 608, 630, 636, 693

## Opcode index (by number)

Every named action opcode by number (reserved slots omitted; see above).

| op | mnemonic | op | mnemonic | op | mnemonic |
|---:|:--|---:|:--|---:|:--|
| 1 | `SetDialogueSuppressed` | 2 | `Wait` | 3 | `WaitReset` |
| 4 | `WaitPlain` | 5 | `ShowPortrait` | 6 | `ShowPortraitWithEmote` |
| 7 | `ShowPortraitWithEmote` | 8 | `SetSpeakerName` | 9 | `SetSpeakerName` |
| 10 | `SetSpeakerVoice` | 11 | `SetSpeakerNameVisible` | 12 | `SetSpeakerById` |
| 13 | `SetSpeakerById` | 14 | `SetSpeakerByIdWithEmote` | 15 | `SetSpeakerByIdWithEmote` |
| 16 | `SetSpeaker` | 17 | `SetSpeaker` | 18 | `SetSpeaker` |
| 19 | `SetSpeaker` | 20 | `SetSpeaker` | 21 | `SetSpeaker` |
| 22 | `SetSpeaker` | 23 | `SetSpeaker` | 24 | `SetSpeaker` |
| 25 | `SetSpeaker` | 26 | `SetSpeaker` | 27 | `SetSpeaker` |
| 28 | `SetSpeaker` | 29 | `SetSpeaker` | 30 | `SetSpeaker` |
| 31 | `SetSpeaker` | 32 | `SetSpeaker` | 33 | `SetSpeaker` |
| 34 | `SetSpeaker` | 35 | `SetSpeaker` | 36 | `SetSpeaker` |
| 37 | `SetSpeaker` | 38 | `SetSpeaker` | 39 | `SetSpeaker` |
| 40 | `SetSpeaker` | 41 | `SetSpeaker` | 42 | `SetSpeaker` |
| 43 | `SetSpeaker` | 44 | `SetSpeaker` | 45 | `SetSpeaker` |
| 46 | `SetSpeaker` | 47 | `SetSpeaker` | 48 | `SetSpeaker` |
| 49 | `SetSpeaker` | 50 | `SetSpeaker` | 51 | `SetSpeaker` |
| 52 | `SetSpeaker` | 53 | `SetSpeaker` | 54 | `SetSpeaker` |
| 55 | `SetSpeaker` | 56 | `SetSpeaker` | 57 | `SetSpeaker` |
| 58 | `SetSpeaker` | 59 | `SetSpeaker` | 60 | `SetSpeaker` |
| 61 | `SetSpeaker` | 62 | `SetSpeaker` | 63 | `SetSpeaker` |
| 64 | `SetSpeaker` | 65 | `SetSpeaker` | 66 | `SetSpeaker` |
| 67 | `SetSpeaker` | 68 | `SetSpeaker` | 69 | `SetSpeaker` |
| 70 | `SetSpeaker` | 71 | `SetSpeaker` | 72 | `SetSpeaker` |
| 73 | `SetSpeaker` | 74 | `SetSpeaker` | 75 | `SetSpeaker` |
| 77 | `SlidePortraitToX` | 78 | `SlidePortraitToX` | 79 | `SlidePortraitBy` |
| 80 | `SlidePortraitBy` | 81 | `WaitPortraitSettled` | 82 | `WaitPortraitSettled` |
| 83 | `ClosePortraits` | 84 | `SetPortraitField62` | 85 | `SetPortraitTargetY` |
| 86 | `SetPortraitTargetY` | 87 | `JoltPortraitY` | 88 | `JoltPortraitY` |
| 89 | `SetPortraitTremble` | 90 | `SetPortraitTremble` | 91 | `SetSceneBit` |
| 92 | `EndDialogue` | 93 | `SetDialogueBoxStyle` | 94 | `SetBoxNormal` |
| 95 | `SetBoxShout` | 96 | `SetBoxThought` | 97 | `SetBoxTrembling` |
| 98 | `ShakeDialogueBox` | 99 | `TeleportActor` | 100 | `TeleportActor` |
| 101 | `PlaceActorAndFace` | 102 | `PlaceActorAndFace` | 103 | `TurnActorToAngle` |
| 104 | `TurnActorToAngle` | 105 | `GetEventActorIndexStub` | 106 | `RotateActorInPlace` |
| 107 | `TurnActorToFaceTarget` | 108 | `TurnActorToFaceTarget` | 109 | `TurnActorToFaceTarget` |
| 110 | `FaceEventActor` | 111 | `SetActorAuxYaw` | 112 | `SetActorAuxYaw` |
| 113 | `WaitActorAuxYaw` | 114 | `WaitActorAuxYaw` | 115 | `WalkActorToAndFace` |
| 116 | `WalkActorToAndFace` | 117 | `WalkActorTo` | 118 | `WalkActorTo` |
| 119 | `StepNpcTo` | 120 | `StepNpcTo` | 121 | `MoveNpcToPosKeepAnim` |
| 122 | `MoveNpcToPosKeepAnim` | 123 | `MoveActorByOffset` | 124 | `MoveActorByOffset` |
| 125 | `MoveActorByOffsetFaceTravel` | 126 | `MoveActorByOffsetFaceTravel` | 127 | `MoveActorByOffsetKeepFacing` |
| 128 | `MoveActorByOffsetKeepFacing` | 129 | `WaitActorMoveDone` | 130 | `WaitActorMoveDone` |
| 131 | `WaitActorNearMoveTarget` | 132 | `WaitActorNearMoveTarget` | 133 | `PlayActorAnim` |
| 134 | `PlayActorAnim` | 135 | `GetActorPosition` | 136 | `GetActorPosition` |
| 137 | `WaitActorAnimDone` | 138 | `WaitActorAnimDone` | 139 | `ApplyEffectToActor` |
| 140 | `ApplyEffectToActor` | 141 | `SetActorOpacity` | 142 | `WalkPlayerToAndFace` |
| 143 | `WalkPlayerTo` | 144 | `StepPlayerTo` | 145 | `WaitPlayerMoveDone` |
| 146 | `EquipItemToPlayer` | 147 | `RestorePlayerEquip` | 148 | `HasPlayerAccessoryEffect40000` |
| 149 | `PlayPlayerAnim` | 150 | `TriggerActionAtPos` | 151 | `TriggerActionOnActor` |
| 152 | `WaitPlayerAnimDone` | 153 | `SpawnEventActor` | 154 | `SpawnEventActorVariant` |
| 155 | `SpawnEventActorEx` | 156 | `UnregisterEventActor` | 157 | `SpawnMapEntity` |
| 158 | `SetMapAmbientColor` | 159 | `ResetMapAmbientColor` | 160 | `WalkEventActorTo` |
| 161 | `StepEventActorTo` | 162 | `TurnEventActorToAngle` | 163 | `TurnEventActorToFaceTarget` |
| 164 | `WaitEventActorMoveDone` | 165 | `TriggerActionAtEventActor` | 166 | `ApplyEffectToEventActor` |
| 167 | `PlayEventActorAnim` | 168 | `SkipEventActorAnimToEnd` | 169 | `WaitEventActorAnimDone` |
| 170 | `SetEventActorAnimSpeed` | 171 | `SetEventActorAlpha` | 172 | `ShowEventActorEmote` |
| 173 | `SetEventActorInScriptFlag` | 174 | `AddActorHeightOffset` | 175 | `SetEventActorHeight` |
| 176 | `SetEventActorScale` | 177 | `EnableEventActorWandering` | 178 | `SetEventActorAuxYaw` |
| 179 | `WaitEventActorAuxYaw` | 180 | `KillEventActor` | 181 | `TurnEventActorIntoNpc` |
| 182 | `GetEventActorPosition` | 183 | `SetActorAIScript` | 184 | `SetActorIgnoredByMonsters` |
| 185 | `PlayActorSplash` | 186 | `SetCameraPosition` | 187 | `ReattachCameraToActor` |
| 188 | `HoldCameraInPlace` | 189 | `ResetCameraToPlayer` | 190 | `SetCameraTarget` |
| 191 | `ResetCameraToActor` | 192 | `ResetCameraToActor` | 193 | `SetCameraTargetToCurrentPosition` |
| 194 | `FocusCameraOnPlayer` | 195 | `WaitCameraAtMark` | 196 | `WaitCameraNearMark` |
| 197 | `ShakeCamera` | 198 | `WaitForPlayerEffect` | 199 | `SetCameraTargetActor` |
| 200 | `SetCameraTargetActor` | 201 | `SetCameraSettleMode` | 202 | `SetCameraZoom` |
| 203 | `SetCameraMapBounds` | 204 | `SleepInBed` | 205 | `RefreshMapTiles` |
| 206 | `SetActorHeldItem` | 207 | `SetActorHeldItem` | 208 | `HandOrDropItem` |
| 209 | `HandOrDropItem` | 210 | `HandOrDropItemWithLevel` | 211 | `ShowActorEmote` |
| 212 | `ShowActorEmote` | 213 | `GetPlayerPosition` | 214 | `SetNpcStoryFlag` |
| 215 | `ClearNpcStoryFlag` | 216 | `HasNpcStoryFlag` | 217 | `ApplyFriendshipDelta` |
| 218 | `GetNpcFriendshipLevel` | 219 | `GetNpcFriendshipLevel` | 220 | `IsAllNpcFriendshipAtLeast` |
| 221 | `AdjustCurrentNpcFriendship` | 222 | `LockNpcPose` | 223 | `SetNpcEngaged` |
| 224 | `SetNpcEngaged` | 225 | `StreamInNpc` | 226 | `GetActorMapId` |
| 227 | `IsActorInMap` | 228 | `IsActorInMap` | 229 | `IsNpcOffScheduleRoute` |
| 230 | `SetSceneCast` | 231 | `SetSceneCast` | 232 | `HasNpcGreetedToday` |
| 233 | `SkipNpcDailyGreeting` | 234 | `SkipNpcDailyGreeting` | 235 | `IsNpcNearbyToChimeIn` |
| 236 | `IsNpcInRangeToChimeIn` | 237 | `GetNpcPairChimeInState` | 238 | `IsQuestNpcGroupAvailable` |
| 239 | `IsQuestNpcGroupAvailable` | 240 | `IsNpcGroupPresentNearby` | 241 | `IsNpcGroupPresentNearby` |
| 242 | `ContinueNormalTalk` | 243 | `EndDialogueLock` | 244 | `ShowNpcHeldItem` |
| 245 | `GetGiftAffinity` | 246 | `StreamInNpcAtPos` | 247 | `GetApproachPos` |
| 248 | `SetNpcVisibleFlag` | 249 | `SetNpcVisibleFlag` | 250 | `SkipActorAnimToEnd` |
| 251 | `SkipActorAnimToEnd` | 252 | `SetActorAnimSpeedScale` | 253 | `SetActorAnimSpeedScale` |
| 254 | `SetActorAnimFrame` | 255 | `GetActorStatusEffect` | 256 | `SetActorStatusConditions` |
| 257 | `IsNpcGroupFreeToComment` | 258 | `IsNpcGroupFreeToComment` | 259 | `PickRandomVillagers` |
| 260 | `GetHostActorHpState` | 261 | `SetNpcRecordFlag80000000` | 262 | `GetCurrentInteractionNpc` |
| 263 | `ResetNpcToIdle` | 264 | `ResetNpcToIdle` | 265 | `IsPlayerOrCompanionDowned` |
| 266 | `SetOrClearNpcSchedule` | 267 | `SetOrClearNpcSchedule` | 268 | `IsNpcAtScheduledSpot` |
| 269 | `IsNpcAtScheduledSpot` | 270 | `ReleaseNpcScriptedPlacement` | 271 | `ReleaseNpcScriptedPlacement` |
| 273 | `IsDatingNpc` | 274 | `IsDatingNpc` | 275 | `SetNpcPresenceState` |
| 276 | `GetNpcHeldItem` | 277 | `GetNpcHeldItem` | 278 | `GetNpcFavoriteItem` |
| 279 | `GetNpcFavoriteItem` | 280 | `GetNpcDateState` | 281 | `SetNpcDateState` |
| 282 | `IsNpcActorPresent` | 283 | `GetDateCompanionId` | 284 | `MountActor` |
| 285 | `SetSceneReadyFlag` | 286 | `ShakeActor` | 287 | `SetNpcOutfit` |
| 288 | `GetNpcOutfit` | 289 | `CarryBaby` | 290 | `SetWifeStatusAndAdvanceFamilyDay` |
| 291 | `SpawnChildEventActor` | 292 | `RegisterChildBirth` | 293 | `ResetNpcDailySchedule` |
| 294 | `ResetNpcDailySchedule` | 295 | `ResetNpcScheduleWithState` | 296 | `ApplyNpcScheduleState` |
| 297 | `ApplyNpcScheduleState` | 298 | `ApplyPendingNpcPlan` | 299 | `ApplyPendingNpcPlan` |
| 300 | `ResetAllNpcSchedules` | 301 | `RefreshNpcScheduleForToday` | 302 | `SetNpcActionDelay` |
| 303 | `SetNpcActionDelay` | 304 | `GetYear` | 305 | `GetSeason` |
| 306 | `GetDay` | 307 | `GetHourMinute` | 308 | `GetDateSnapshot` |
| 309 | `IsPlayerMale` | 310 | `IsPlayerModelLest` | 311 | `HealPartyFull` |
| 312 | `SetPartyHpByShift` | 313 | `RestorePlayerRP` | 314 | `CurePartyStatus` |
| 315 | `QueueNpcGreetingEvent` | 316 | `SetNpcVisible` | 317 | `SetNpcVisible` |
| 318 | `SetNpcBirthdayGiftFlag` | 319 | `SetNpcNicknameForPlayer` | 320 | `SetNpcNicknameForPlayer` |
| 321 | `GetNpcNicknameForPlayer` | 322 | `SetNpcNickname` | 323 | `SetNpcNickname` |
| 324 | `GetMood` | 325 | `GetLumber` | 326 | `ModifyLumber` |
| 327 | `EndActorTransformAndSetOutfit` | 328 | `EndActorTransformAndSetOutfit` | 329 | `IsPosing` |
| 330 | `SetActorOutfit` | 331 | `SetActorOutfit` | 332 | `WarpToMap` |
| 333 | `WarpToMapInSubEvent` | 334 | `FadeScreen` | 335 | `FadeScreenToClear` |
| 336 | `SetFadeColor` | 337 | `WaitForFade` | 338 | `IsNpcOnPlayerMap` |
| 339 | `GetNpcCurrentMap` | 340 | `SetVar0` | 341 | `SetVar0` |
| 342 | `GetVar0` | 343 | `SetVar1` | 344 | `GetVar1` |
| 345 | `SetVar11` | 346 | `GetVar11` | 347 | `SetVar2` |
| 348 | `SetVar2` | 349 | `SetVar3` | 350 | `GetVar3` |
| 351 | `SetVar4` | 352 | `GetVar4` | 353 | `SetVar5` |
| 354 | `GetVar5` | 355 | `SetVar6` | 356 | `GetVar6` |
| 357 | `SetVar7` | 358 | `GetVar7` | 359 | `SetVar8` |
| 360 | `GetVar8` | 361 | `SetVar9` | 362 | `GetFestivalDate` |
| 363 | `GetNpcBirthday` | 364 | `SetVar10` | 365 | `SetButtonIconSlot` |
| 366 | `SetTextSlotEntries` | 367 | `GetVar14` | 369 | `TryMountPlayerOnHostActor` |
| 370 | `SetSceneStateBit1` | 371 | `EvalCondScriptA` | 372 | `EvalCondScriptB` |
| 373 | `DispatchCondScriptEntry` | 374 | `RunEmEntryAltAction` | 375 | `OpenMenu` |
| 376 | `OpenShop` | 377 | `ConsumeInteractionResult` | 378 | `ConsumeInteractionResult` |
| 379 | `PlayMusic` | 380 | `StopMusic` | 382 | `FadeMusicVolume` |
| 383 | `SetMusicLock` | 384 | `ResetMusicResumePositions` | 385 | `PlaySound` |
| 386 | `StopVoices` | 387 | `PlaySfxWithNpcRemap` | 388 | `nop` |
| 389 | `SetPooledVoiceVolume` | 390 | `StopVoiceId` | 392 | `PlaySoundOnFreeVoice` |
| 393 | `FreezePlayer` | 394 | `WarpPlayer` | 395 | `TurnPlayerToAngle` |
| 396 | `TurnPlayerToAngle` | 397 | `SetPartyOutfit` | 398 | `BuildOutfitChoiceMask` |
| 399 | `GetPlayerActionState` | 400 | `SetPlayerMale` | 401 | `SendMonsterToFarmArea` |
| 402 | `RecallFarmMonster` | 403 | `GetFreeFarmAreas` | 404 | `GetOccupiedFarmAreas` |
| 405 | `SetFarmMonsterPlantOrder` | 406 | `GetFarmMonsterPlantOrder` | 407 | `GetAliveKillTargetCount` |
| 408 | `CountLivingEnemies` | 409 | `GetTamedMonsterCount` | 410 | `TameEventMonster` |
| 411 | `GetCompanionMonsterData` | 412 | `BlackScreen` | 413 | `SetDialogueBoxY` |
| 414 | `GetChoiceIndexAndItem` | 415 | `SetSubstitutionHighlight` | 416 | `GetPlayerVariable` |
| 417 | `ModifyPlayerResource` | 418 | `HasBackpackRoom` | 419 | `HasRoomForItem` |
| 420 | `HasBackpackFreeSlots` | 421 | `SetNextItemAttributes` | 422 | `SetNextItemAttributesPacked` |
| 423 | `GivePlayerItem` | 424 | `GivePlayerItem` | 425 | `ForcePlayerHoldItem` |
| 426 | `IsPlayerHoldingItem` | 427 | `SetWeaponSkillsToLevel30` | 428 | `TakeItem` |
| 429 | `TakeItemFromBackpack` | 430 | `ConsumeHeldItem` | 431 | `HasItem` |
| 432 | `GetSeedCropInfo` | 433 | `GetFishSizeRecords` | 434 | `GetItemSellPrice` |
| 435 | `GetItemBuyPrice` | 436 | `IsItemStackable` | 437 | `IsItemInCategoryList` |
| 438 | `HasItemOfCategory` | 439 | `ReleaseFarmMonster` | 440 | `GetNpcMapID` |
| 441 | `IsConfirmButtonDown` | 442 | `IsStickInputActive` | 443 | `SetFlagBit` |
| 444 | `SetFlagBitIfCond` | 445 | `GetFlagBit` | 446 | `SetWeather` |
| 447 | `GetWeather` | 448 | `SetWeatherTransition` | 449 | `GetWeatherTransition` |
| 450 | `GetWeatherStreak` | 451 | `GetDayOfWeek` | 452 | `SpawnItemAtPos` |
| 453 | `DropStagedItem` | 454 | `SpawnItemVisual` | 455 | `DespawnItemVisuals` |
| 456 | `GetEquippedItemAttr` | 457 | `ShowRewardPopup` | 458 | `ShowQuestReward` |
| 459 | `ShowRewardPopupAtPos` | 460 | `AddRewardItem` | 461 | `SuppressRewardJingle` |
| 462 | `GiveRewardItems` | 463 | `DropItem` | 464 | `DropItemStack` |
| 465 | `SetCalendarPauseFlag` | 466 | `SkipToTime` | 467 | `SetTime` |
| 468 | `FastForwardCalendar` | 469 | `SetOrAddCalendarDate` | 470 | `GetGuestNpcVariant` |
| 471 | `GetChildFriendPoints` | 472 | `SetGuestNpcTitle` | 473 | `RollChildDailyPref` |
| 474 | `SetGuestRosterGate` | 475 | `SetNpcStateByte` | 476 | `RecruitNpcToParty` |
| 477 | `RecruitNpcToParty` | 478 | `RecruitNpcToPartyHeld` | 479 | `RecruitNpcToPartyHeld` |
| 480 | `RecruitHostNpcToParty` | 481 | `GetPartyMemberId` | 482 | `GetPartyMemberId` |
| 483 | `DismissBothCompanions` | 484 | `DismissBothCompanionsQuiet` | 485 | `DismissBothCompanionsEx` |
| 486 | `DismissCompanionByCharId` | 487 | `IsCurrentNpcInParty` | 488 | `SetCompanionScriptedPresence` |
| 489 | `SetCompanionsSceneHeld` | 490 | `IsDatePartnerAtDateSpot` | 492 | `SetNpcFacingMode` |
| 493 | `GetNpcFacingMode` | 494 | `SetCompanionVisible` | 495 | `WarpCompanion` |
| 496 | `WalkCompanionToAndFace` | 497 | `WalkCompanionTo` | 498 | `MoveCompanionByOffset` |
| 499 | `MoveCompanionByOffsetFaceTravel` | 500 | `TurnCompanionToAngle` | 501 | `TurnCompanionToFaceTarget` |
| 502 | `WaitCompanionSettled` | 503 | `ShowCompanionEmote` | 504 | `GetPartyMemberPosY` |
| 506 | `WarpMonstersToPlayer` | 507 | `PopulateSlayRequest` | 508 | `PopulateQuestKind2RandomRewards` |
| 509 | `PopulateQuestKind2RandomRewards` | 510 | `PopulateQuestKind2LiteralRewards` | 511 | `PopulateQuestKind3RandomRewards` |
| 512 | `PopulateQuestKind3RandomRewards` | 513 | `PopulateQuestKind4RandomRewards` | 514 | `PopulateQuestKind4RandomRewards` |
| 515 | `PopulateQuestKind4LiteralRewards` | 516 | `PostBoardQuestKind5` | 517 | `PostBoardQuestKind5` |
| 518 | `PostBoardQuestKind6` | 519 | `PostBoardCraftQuest` | 520 | `PostQuestGoalNumber` |
| 521 | `PopulateQuestKind9LiteralRewards` | 522 | `PopulateQuestKind10RandomRewards` | 523 | `PostQuestLiteralRewards` |
| 524 | `NopCompleteSubEventGoals` | 525 | `CompleteQuest` | 527 | `AdvanceRng` |
| 528 | `GetRequestRewardItem` | 529 | `ClearAllRequestRecords` | 530 | `CommitQuestAcceptance` |
| 531 | `ClearBoardRequest` | 532 | `GetNpcQuestPreview` | 534 | `GetDailyVisitor` |
| 535 | `GetQuestRemainingByItem` | 536 | `StartReservedSubEvent` | 537 | `QueueSubEventGoalKind2` |
| 538 | `QueueSubEventGoalKind2` | 539 | `QueueSubEventGoalKind3` | 540 | `QueueSubEventGoalKind3` |
| 541 | `QueueSubEventGoalKind4` | 542 | `QueueSubEventGoalKind4` | 543 | `QueueSubEventGoalKind5` |
| 544 | `QueueSubEventGoalKind5` | 545 | `QueueSubEventGoalKind6` | 546 | `QueueSubEventCraftGoal` |
| 547 | `QueueSubEventGoalKind10` | 548 | `CompleteAllSubEventGoals` | 549 | `FinishCurrentSubEvent` |
| 551 | `ResetSubEventGoals` | 552 | `GetSubEventGoalRemaining` | 553 | `SetNpcSubEventFlag` |
| 554 | `SetNpcSubEventFlag` | 555 | `SetNpcAttentionRadius` | 556 | `SetNpcAttentionRadius` |
| 557 | `SetNpcRecognitionFlags` | 558 | `SetNpcRecognitionFlags` | 559 | `StartFestivalContest` |
| 560 | `StageSceneNpcs` | 561 | `GetSceneStateBytes` | 562 | `RefreshSceneNpcs` |
| 563 | `EquipScriptedWeapon` | 564 | `RemoveScriptedWeapon` | 566 | `RecordFestivalPlacement` |
| 567 | `GetTomorrowsCalendarEvent` | 568 | `GetSceneNpc` | 569 | `RankFestivalContestants` |
| 570 | `GetTodaysRequestNpc` | 571 | `SetSceneScratch` | 572 | `GetSceneScratchByte` |
| 573 | `GetFestivalPlacements` | 574 | `ShuffleSceneBuffer` | 575 | `GetShuffleValue` |
| 576 | `GetSceneEventNpc` | 577 | `GetFestivalResults` | 578 | `SpawnEventMonsters` |
| 579 | `GetSceneEventFlags` | 580 | `GetGivenItemStats` | 581 | `CompareFishRecord` |
| 582 | `GetFishRecord` | 587 | `PlaceFurniture` | 588 | `HasMapEntityOfKind` |
| 589 | `PickUpHostObject` | 590 | `BreakFurniture` | 591 | `ClearAllTileObjects` |
| 592 | `CanPlaceFurnitureInRoom` | 593 | `PickRandomPlacedFurniture` | 594 | `CommitGrabbedObject` |
| 595 | `SetMinimapMarker` | 596 | `RollUniformIntegerLessThanN` | 597 | `RollShopCategoryItemReturnId` |
| 598 | `RollRandomItemMatchingDisplayName` | 599 | `RollRandomDishItem` | 600 | `RollRandomEquipmentItem` |
| 601 | `RollRandomFurItem` | 602 | `RollRandomMedicineOrFailedDish` | 603 | `RollRandomGrassItem` |
| 604 | `RollRandomIngredientItem` | 605 | `RollRandomSeasoningItem` | 606 | `RollThreeFlowerItemsAvoidDup` |
| 607 | `RollRandomFlowerSeedItem` | 609 | `RollRandomPointInRadiusAroundCenter` | 610 | `SetChoiceVisibleMask` |
| 611 | `ClearChoiceVisibleRange` | 612 | `SetChoiceVisibleBit` | 613 | `CalcChoicePrescroll` |
| 614 | `SetDialogueBoxMode` | 615 | `SetNextChoiceDescription` | 616 | `TestAndSetCraftedFlag` |
| 617 | `ShowStaffCredits` | 618 | `WaitStaffCreditsDone` | 619 | `IsPartyInviteAccepted` |
| 620 | `MarkSpouseCleared` | 621 | `SetDifficulty` | 622 | `GetDifficulty` |
| 623 | `SetDialogueAutoAdvance` | 624 | `SetDialogueHoldFrames` | 625 | `EnterSharanceMazeStage` |
| 626 | `IsMazeStageCleared` | 627 | `JumpToRandomDate` | 628 | `SetRegisters` |
| 629 | `SetRegisters` | 631 | `GetNameHashRoll` | 632 | `RollSeededDailyRandom` |
| 633 | `ResetActionEventId` | 634 | `SetActionTriggerByte` | 635 | `GetActionTriggerByte` |
| 637 | `SaveCalendarSnapshot` | 638 | `GetHarvestReport` | 639 | `GetPrincePoints` |
| 640 | `AddPrincePoints` | 641 | `GetTourists` | 642 | `AddTourists` |
| 643 | `ApplyPrinceOrder` | 644 | `GetPrinceOrderState` | 645 | `PromotePrinceRank` |
| 646 | `GetPrinceRank` | 647 | `GetPrinceOrderCost` | 648 | `GetShippingCompletionPercent` |
| 649 | `GetShippingBoxGold` | 650 | `GetLifetimeShippedGold` | 651 | `AdvanceStoryProgress` |
| 652 | `GetPreviousMapId` | 653 | `ShowLumberCounter` | 654 | `ShowStoneCounter` |
| 655 | `ShowPrincePointCounter` | 656 | `SetMapScrollSpeedX` | 657 | `SetMapScrollSpeedY` |
| 658 | `GetDefeatPosition` | 659 | `MyShopAction` | 660 | `SetActorInvulnerable` |
| 661 | `SetActorStatFlagRecompute` | 662 | `SetActorControlBit4000` | 663 | `MakeActorUntameable` |
| 664 | `SetActorUnlimitedSight` | 665 | `SetActorFacing` | 666 | `IsGameClearedSysFlagSet` |
| 667 | `SetGameClearedSysFlag` | 668 | `IsSaveConfigBit4Set` | 669 | `SetSaveConfigBit4` |
| 670 | `IsSaveConfigBit5Set` | 671 | `SetSaveConfigBit5` | 672 | `IsSaveConfigBit2Set` |
| 673 | `IsSaveConfigBit3Set` | 674 | `GetRuneMedals` | 675 | `ConvertMedalsToGold` |
| 676 | `GetMedalGoldRate` | 677 | `SpawnEffectObjectAtPos` | 678 | `WallOffTileRect` |
| 679 | `IncrementPlayerSkillLevel` | 680 | `ApplyAttackToPlayer` | 681 | `RollBreadRecipe` |
| 682 | `SetSceneField400` | 683 | `PlayCutsceneVideo` | 684 | `IsProjectorSceneUnlocked` |
| 685 | `SetFreeLookCameraMode` | 686 | `GetFreeLookCameraMode` | 687 | `RebuildMinimap` |
| 688 | `ToggleMinimap` | 689 | `RespawnRoomFurnitureVisuals` | 690 | `GetNpcGivenHat` |
| 691 | `MultiplyValues` | 692 | `CancelPendingDate` | 694 | `HasClearedAnyMarriage` |
| 695 | `IsSpouseCleared` | 696 | `RemoveItemFromBackpack` | 697 | `ReturnToTitle` |
| 698 | `SetShopkeeperMessage` | 699 | `SetNarrationModeIf` | 700 | `HasItemWithFlagBit0` |
| 701 | `SetPlayerSkillXp` |  |  |  |  |
