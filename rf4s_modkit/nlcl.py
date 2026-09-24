r"""
nlcl.py -- generic RF4S `NLCL` fixed-record parameter-table read / edit / write.

~80 `rf3*/rf4*.bin` param files in bundleMain are `NLCL` tables: a 28-byte header
followed by `entry_count` fixed-size records. They drive almost all of the game's
tunable data — item sell prices & categories (`rf3ItemList`), equipment stats
(`rf3ItemEquipmentParam`), crop yield/growth (`rf3CropParam`), the level→price
multiplier grid (`rf3PriceTable`), recipes (`rf3Recipe*`), skills (`rf3ParamSkill`),
gift preferences (`rf3PresentNpc*`), NPC params, schedules, and more.

Header (verified against rf3ItemList / the NLCLINK_* `.h` defines):

    +0x00  "NLCL"
    +0x04  u32 BCD build date (e.g. 0x20201123)
    +0x08  8 bytes reserved (0)
    +0x10  u32 version (1 for param tables; Gen*.bin use 6 -> use gen.py instead)
    +0x14  u32 byte_size   (= 28 + entry_count*record_size)
    +0x18  u32 entry_count
    +0x1C  records[entry_count]      record_size = (byte_size - 28) / entry_count

So record `i` lives at byte `28 + i*record_size`. Fields are little-endian ints at
fixed byte offsets within a record. Verified example: rf3ItemList record_size=40,
sell price at record +12 (Cabbage id1 = 680, Turnip id29 = 30, Pumpkin id9 = 110).

Field edits are in-place (same-size int writes). Rows can also be ADDED / REMOVED
(`append_record` / `insert_record` / `delete_record`): `build()` then rewrites
entry_count (+24) and byte_size (+20) and regenerates the generic NLCL footer (the
build-tool xref table past byte_size; flat tables carry only the root descriptor
{0,24,0,0}, see `nlcl_footer`). An untouched table rebuilds byte-exact (56/56 shipped
version-1 tables). Whether the ENGINE reads an added row depends on the family -- the
schema key "grow" records the IDB-verified answer ("file-count" / "fixed:<N>" /
"paired-text:<stem>", see `NlclTable.grow_info`), printed by `rf4mod param info`.

`FIELD_SCHEMAS` gives friendly named fields for the well-understood tables; any other
NLCL table can still be read/edited generically by (record, byte-offset, type).
"""
from __future__ import annotations

import pathlib
import struct

MAGIC = b"NLCL"
HEADER_SIZE = 28
# The footer every shipped flat param table carries past byte_size: the root-record-array
# descriptor {0, 24, 0, 0} of the generic NLCL xref table (search_items.parse_nlcl_footer).
CANONICAL_FOOTER = struct.pack("<IIII", 0, 24, 0, 0)

# int type -> (struct code, size)
_FMT = {
    "u8": ("<B", 1), "s8": ("<b", 1),
    "u16": ("<H", 2), "s16": ("<h", 2),
    "u32": ("<I", 4), "s32": ("<i", 4),
}


class NlclError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Per-file field schemas (verified offsets). Each: list of (name, offset, type).
# `key` is the field used as the row label / lookup id (default: record index).
# --------------------------------------------------------------------------- #
FIELD_SCHEMAS = {
    "MapOre_Rate": {
        # 25 records x 32 B — the ORE/MINERAL CONFIG table indexed by a type-0
        # MOBJ spawn's f10 (mining-rock spawn points). CORRECTED 2026-09-01
        # against the decomp's Mining_Init (= TileObject_ApplyToolHit reads,
        # RF4S.exe+0x18B100/+0x18B32A): field 0 is the gatherable KIND
        # (26..37 -> the rock sprite + "Mineral" char 459+kind), NOT an
        # "area id"; +4/+8 are the deplete/scrap probability bases, and the
        # weights sit at +12/16/20 pairing items +24/26/28 with rare at +30.
        # Full decoded table (config -> ores) in decomp docs/gathering.md.
        "fields": [
            ("kind", 0, "u32"), ("deplete_prob", 4, "u16"), ("scrap_prob", 8, "u16"),
            ("weight0", 12, "u16"), ("weight1", 16, "u16"), ("weight2", 20, "u16"),
            ("item0", 24, "u16"), ("item1", 26, "u16"),
            ("item2", 28, "u16"), ("rare_item", 30, "u16"),
        ],
    },
    "rf3TxtQuest_split3_1": {
        # 165 x 4-byte QUEST/REQUEST DATABASE = archive 16342 (g_questDatabase = archive_data+28).
        # Row index == quest_id. This is the DATA half of the rf3TxtQuest split file; the
        # localized quest text is in rf3TxtQuest_split3_2/_3.<locale>. IDA-verified vs
        # Quest_IsAcceptable (RF4S.exe+0x1ED130) and Quest_LoadDetailStrings (+0x1ED1F0):
        #   +0 client_id  read as *(u8*)(g_questDatabase + 4*quest_id) — the NPC who posts the
        #                 request (grouped ~3 quests per client). 22/23 = "Anonymous"; 0 = placeholder.
        #   +1 category   the a3 template selector (values 1..31) that Quest_LoadDetailStrings
        #                 switches on to pick the objective + reward-text format for that quest.
        #   +2,+3 pad     always 0.
        # RF4 "requests" are PROCEDURAL: the concrete objective (monster/item), count, and reward
        # are rolled at runtime by Quest_PopulateNpcSlot — only client + category are authored here.
        # (Story/named quests are script-driven in rf3.mc/MYCF, a different subsystem.)
        # ADD ROW (2026-09-19): the engine takes the quest count FROM THE FILE --
        # QuestMenu_GetQuestEntryCount (RF4S.exe+0x3A5A0) returns u32 @+24 of archive 16342 --
        # but the title / description TEXT twins (16377/16381 = rf3TxtQuest_split3_2/_3.<locale>)
        # are index-bound, so a new quest needs a line appended to both (`rf4mod text add`).
        "grow": "paired-text:rf3TxtQuest_split3_2 (+ _split3_3)",
        "fields": [
            ("client_id", 0, "u8"),
            ("category", 1, "u8"),
        ],
    },
    "rf4TxtQuestRequestDetailFormat_split2_1": {
        # 33 x 4-byte companion of the 33 request detail-FORMAT strings
        # (rf4TxtQuestRequestDetailFormat_split2_2.<locale>, archive 16345 = this .bin; the
        # quest's `category` byte indexes the string directly, see docs/23). byte0 = 2 on rows
        # 1..3 ("Item Needed: %s" variants), else 0; bytes 1..3 always 0. VERIFIED DEAD DATA
        # (2026-09-19): every code site that names archive 16345 or its pointer
        # (qword_7FF7BF78B188) only loads / zeroes / releases it -- QuestMenu_LoadDatabaseArchives
        # (RF4S.exe+0x3A440), QuestMenu_ReleaseDatabaseArchives (+0x3A4A0),
        # DailyRequest_RefreshAllNpcs (+0x1ED8B0), ScriptTask_FirstTimeInit (+0x1EE060) -- no
        # function dereferences the records, so `flag` has no gameplay effect. The twin's
        # strings ARE live, selected by category with the argument slots filled by the
        # hard-coded Quest_LoadDetailStrings (+0x1ED1F0) switch.
        "grow": "unused:the exe loads archive 16345 but never reads its records; the format "
                "strings are picked by the quest category byte whose meaning is hard-coded "
                "in Quest_LoadDetailStrings (+0x1ED1F0), so a 34th row/line is unreachable",
        "fields": [("flag", 0, "u8"), ("b1", 1, "u8"), ("b2", 2, "u8"), ("b3", 3, "u8")],
    },
    "rf3FaceEffectParam": {
        # 442 x 8 B, archive 4003 (rom:/face/). Layout DATA-DERIVED (2026-09-19, no reader in
        # the PC exe -- see below): 442 = 34 portrait slots x 13 effect kinds, record =
        # slot*13 + kind (118 records repeat exactly at stride 13, 0 at stride 17; kind 11 is
        # the (1, 0) marker on every slot). Each record holds up to four signed-byte (x, y)
        # anchor offsets for the effect sprite (sweat drop / anger vein / notes ...) relative
        # to the portrait: x in -58..48, y in -86..-6 (above the anchor), unused pairs 0.
        # NO CODE SITE references archive 4003 (immediate scan of .text 2026-09-19): the only
        # 0xFA3 constants are the `4003 + char_id` face-ICON base (faceIcon/face_NPC01 = 4004)
        # in the face-icon resolver (RF4S.exe+0x3C9C0) and Player_TransformToCharacterById
        # (+0x165FC0), so this table is inherited 3DS data the PC build never loads by id.
        "grow": "unused:no code site loads archive 4003 (the 0xFA3 constants in the exe are "
                "the 4003+char_id face-icon base)",
        "fields": [("x0", 0, "s8"), ("y0", 1, "s8"), ("x1", 2, "s8"), ("y1", 3, "s8"),
                   ("x2", 4, "s8"), ("y2", 5, "s8"), ("x3", 6, "s8"), ("y3", 7, "s8")],
    },
    "rf3ParamSkillExp": {
        # 100 x 4 B skill XP-to-next curve (archives 14820..14824 = rf3ParamSkillExp /
        # ...Farm / ...Fish / ...Mix / ...Sleep, byte-confirmed per the IDB note on
        # Skill_GetLevelTable RF4S.exe+0x83E60 = nsFileArchive_GetData(id)+28). Reader
        # Player_GetSkillXpToNextLevel (+0x38440): table[level] for level < 99, table[99]
        # (+396) for every level past 99 of an uncapped skill; the file's 16 trailing bytes
        # are the NLCL footer, not pad. Full editor: rf4s_modkit.skillcurve / `rf4mod skill`.
        "grow": "fixed:100",
        "fields": [("xp_to_next", 0, "s32")],
    },
    "rf3ParamSkillExpFarm": {"alias": "rf3ParamSkillExp"},
    "rf3ParamSkillExpFish": {"alias": "rf3ParamSkillExp"},
    "rf3ParamSkillExpMix": {"alias": "rf3ParamSkillExp"},
    "rf3ParamSkillExpSleep": {"alias": "rf3ParamSkillExp"},
    "rf3ItemList": {
        "names": "item",   # row index IS the item id; resolve name via rf4s_item_names.json
        # ADD ROW (2026-09-19): the loader ItemDatabase_AllocateAndInit (RF4S.exe+0x3FBE0)
        # stores only archive+28 (never the +24 count) and readers index by item id, which
        # the code bounds with the CONSTANT 1108 (0x454, e.g. Item_ComputeStackGoldValue
        # +0x454A0: `if (item_id >= 0x454) return 0`). Rows past 1108 are unreachable; the
        # per-item parallel tables + rf3TxtItem_split2_1/_2 (names/descriptions) share the id.
        "grow": "fixed:1108",
        "fields": [
            ("base_item", 0, "u32"),     # base/family item (King Cabbage -> Cabbage)
            ("category", 4, "u8"),       # ItemMetadata_t +4: <= 14 = usable (rf3UseItemParam row), 0..2/46 = crops
            ("sell_price", 12, "s32"),   # verified: Cabbage 680 / Turnip 30 / Pumpkin 110
            ("crop_link", 16, "u32"),    # ItemMetadata_t.data_10: rf3CropParam record a SEED plants (Turnip Seed 753 -> 72)
        ],
    },
    "rf3PriceTable": {
        # 10 records x 10 u16 = the level-upgrade price multiplier grid. Reader (IDB 2026-09-19)
        # Item_ComputeStackGoldValue (RF4S.exe+0x454A0): row = the item's price CATEGORY byte
        # (metadata data_6/data_7, must be <= 9 else value 0), column = the stack's level 0..9,
        # value = percent: gold = base_price * ptr_80[10*category + level] / 100. Loaded as
        # g_itemDatabase->ptr_80 = archive 14825 + 28 (ItemDatabase_AllocateAndInit +0x3FBE0);
        # the count is never read and the category guard caps rows at 10.
        "grow": "fixed:10",
        "fields": [(f"mult_lv{j}", j * 2, "u16") for j in range(10)],
    },
    "rf3NpcParam": {
        # 392 x 308-byte character/monster template DB, ROW INDEX == char_id. nlcl's
        # HEADER_SIZE=28 places record N at the char_id-N TEMPLATE start, so these are
        # template-relative offsets (= the raw 308*id record offset minus 28). Stat
        # fields IDA-verified vs Actor_RecomputeAllStats + live records (Orc[48] HP48/
        # ATK5/model756; boss[200] HP80000). model/anim/ai are DATA-DRIVEN resource ids
        # (ai_script N -> AIBN archive N+1; Orc 0 = AI_m00). drops: id (item, &0x7FF) +
        # pm (per-mille ‰ chance). See project_rf4s_monster_actor / project_rf4s_monster_drops.
        # element affinities (s32, Q12: +4096 = +100% damage taken = WEAK; negative = resist)
        # + status-proc resists (s16, Q12: 4096 = 100% immune) IDA-verified vs
        # Actor_LoadBaseStatsFromTemplate (RF4S.exe+0xC5F940): elements v9[38..45] copied to
        # stats+100..128 (note the file swap: +204=neutral, +208=love/mask0x40); resists
        # *((u16*)v9+92..106) copied to stats+152..166 (spaced 4 bytes apart in-file).
        # Live-cross-checked: boss[200] = ~100% status resist + fire-resist/water-weak.
        # ADD ROW (2026-09-19): Char_GetTemplate (RF4S.exe+0x1C63B0) copies archive 14812 +
        # 28 + 308*char_id into g_charTemplateBuffer with NO bound check and never reads the
        # +24 count, so any char id the game can reference (Gen rosters, scripts, `monster
        # new`) reaches its row; give it name/description lines in rf3TxtNpc_split2_1/_2.
        "grow": "id-indexed:char id (Gen rosters / scripts); names in rf3TxtNpc_split2_1/_2",
        "fields": [
            ("ai_script", 34, "u16"),
            ("hp", 40, "u32"), ("atk", 44, "u32"), ("def", 48, "u32"),
            ("mat", 52, "u32"), ("kill_xp", 56, "u32"),
            ("model", 272, "u16"), ("anim", 274, "u16"),
            ("drop0_id", 228, "u16"), ("drop1_id", 230, "u16"),
            ("drop2_id", 232, "u16"), ("drop3_id", 234, "u16"),
            ("drop0_pm", 236, "u32"), ("drop1_pm", 240, "u32"),
            ("drop2_pm", 244, "u32"), ("drop3_pm", 248, "u32"),
            ("elem_fire", 152, "s32"), ("elem_water", 156, "s32"),
            ("elem_earth", 160, "s32"), ("elem_wind", 164, "s32"),
            ("elem_light", 168, "s32"), ("elem_dark", 172, "s32"),
            ("elem_none", 176, "s32"), ("elem_love", 180, "s32"),
            ("res_poison", 184, "s16"), ("res_paralysis", 188, "s16"),
            ("res_sleep", 192, "s16"), ("res_seal", 196, "s16"),
            ("res_fatigue", 200, "s16"), ("res_cold", 204, "s16"),
            ("res_faint", 208, "s16"), ("res_drain", 212, "s16"),
        ],
    },
    "rf3CropParam": {
        # 93 x 108; record index != item id. Verified in +28 base: stage durations in
        # days at bytes 0..3 [stage1,stage2,stage3,regrow] (regrow 0 = single harvest;
        # Turnip [1,1,1,0]=3d, Cabbage [2,3,3,0]=8d, Strawberry [2,5,5,4]); harvested
        # item @+96, seed item @+100 (Turnip -> 29 / 753).
        #
        # GROWTH-TICK fields added 2026-07-20 (dual-binary verified: RF4S
        # Crop_TickGrowthForTile @RF4S.exe+0x185240 == code.bin Farm_DailyGrowCrops,
        # byte-identical; offsets cross-checked against live rf3CropParam records):
        #   +16 grow_cap   MISNOMER (kept as the field key). CORRECTED 2026-07-21: this
        #                  is the crop's BASE [HP] -- copied straight into tile+8 (the live
        #                  [HP] the Magnifying Glass shows) at planting, and the wither-roll
        #                  reference (buckets current [HP] at cap>>1, cap>>2). Apple=140.
        #                  NOT a "size/quality ceiling".
        #   +40 water      MISNOMER (kept as the field key). CORRECTED 2026-07-21: NOT water
        #                  consumption. Only fires when the crop's [HP] (tile+8) hits 0: then
        #                  it subtracts this from the crop's growth-quality byte (record+6)
        #                  each parched night (halved if watered that day). = the crop's
        #                  DROUGHT/dry-out growth penalty. Trees=0. (The [HP] drain itself
        #                  comes from a per-crop item-record field, not this.)
        #   +64/68/72/76 gmul_size/gmul_1/gmul_2/gmul_3  per-growth-dimension RATE
        #                  multipliers, applied as delta*val*32/4096 -> **128 = 1.0x**
        #                  (64=0.5x, 256=2.0x). +64 drives the size dimension; +68/72/76
        #                  the three quality/vigor dims. Neutral crops = 128,128,128,128.
        #   +104 season    property + SEASON-AFFINITY flag word (u32). Season bits:
        #                  BOOST (in-season, +50% growth) 0x1000=spring 0x2000=summer
        #                  0x4000=fall 0x8000=winter ; PENALTY (off-season, -25%..-75%)
        #                  0x10000=spring 0x20000=summer 0x40000=fall 0x80000=winter.
        #                  A single-season crop sets its 1 boost bit + the other 3
        #                  penalty bits (e.g. summer crop=0x2000|0x10000|0x40000|0x80000);
        #                  an all-season crop sets none of 0x1000..0x80000. Low bits also
        #                  carry harvest-method (0x400=tool / 0x600=hand-pickup) + misc
        #                  crop-property flags -- edit season bits, keep the low bits.
        # To reseason a crop: clear its old 0x1000..0x80000 bits, set the new boost bit
        # (+ the 3 off-season penalty bits if you want a single-season crop).
        # ADD ROW (2026-09-19): rows are addressed by the SEED ITEM's crop-link id -- the
        # u32 at rf3ItemList record +16 (ItemMetadata_t.data_10): Script_VMOp_QueryCropPlantable
        # AndTileInfo (RF4S.exe+0x2113D0) reads `g_currentMapTiles+32` (= archive 14807 + 28,
        # stored by FarmFieldTask_Spawn +0x1842B0 without reading the count) + 108*link. So a
        # 94th crop is reachable once a seed item links to it (`param set rf3ItemList.bin
        # <seed> crop_link=93`). Caveat: FarmFieldTask_Spawn also copies FIXED row ranges
        # (0..25, 26..37, 38..87 by kind flag) into per-kind lists at spawn, so a new row is
        # outside those lists.
        "grow": "id-indexed:the seed item's crop_link (rf3ItemList +16)",
        "names": "item", "name_field": "harvest",
        "fields": [
            ("stage1", 0, "u8"), ("stage2", 1, "u8"), ("stage3", 2, "u8"),
            ("regrow", 3, "u8"), ("growth", 12, "u32"), ("grow_cap", 16, "u32"),
            ("water", 40, "u16"),
            ("gmul_size", 64, "u32"), ("gmul_1", 68, "u32"),
            ("gmul_2", 72, "u32"), ("gmul_3", 76, "u32"),
            ("harvest", 96, "u32"), ("seed", 100, "u32"),
            ("season", 104, "u32"),
        ],
    },
    "rf3UseItemParam": {
        # 318 x 180-byte records, NLCL v1. row index = ITEM ID (the usable-item id block
        # 0..317; equipment ids >= 318 use rf3ItemEquipmentParam instead). FULLY VERIFIED
        # 2026-06-11: this file == g_itemDatabase->ptr_68 (archive 14848, confirmed by
        # live byte-match of ptr_68 against the file's records). Read by
        # Item_ComputeEffectiveStats (ptr_68 + 180*item_id) and applied by Item_UseOnActor
        # (+0xEF4150); field offsets are that function's v78[] effect-buffer reads.
        #
        # The original hp@0/rp@4 schema was correct in spirit (rec1 HP=140, rec2 HP=600
        # are the +0 flat-HP-recovery values); the full layout:
        #   +0  hp_recover     flat HP healed (negative = damage; e.g. failure dishes)
        #   +4  rp_recover     flat RP restored (only if actor has RP)
        #   +8  hp_recover_pct fraction of max HP, Q12 (4096 = 100%)
        #   +12 rp_recover_pct fraction of max RP, Q12
        #   +16 effect_bits    status field: bits 0..5 = cure mask (clear poison..faint);
        #                      bits 6..12 = INFLICT status (>>6 -> control_flags 0..6,
        #                      gated by proc-resist); 0x2000 = level-up (Lvl+ candy)
        #   +20 food_buff_min  buff duration, units of 10800 ticks = 3 min (0=no buff,
        #                      1=3min, 4=12min) -> "Fed" status icon 05
        #   +24 buff_hp / +28 buff_rp / +32 buff_atk / +36 buff_def / +40 buff_mat
        #                      flat temporary stat buffs while the food buff is active
        #   +44 buff_hp_pct / +48 buff_rp_pct / +52 buff_atk_pct / +56 buff_def_pct /
        #   +60 buff_mat_pct   the %-of-max/base scalers paired with +24..+40 (Q12)
        #   +160..+172 perm_boost0..3  PERMANENT max-stat raises (stat-up seeds/dishes:
        #                      write into stats->equip_record, gated by status bit 4)
        #   +176 level_scale   appraisal/cooking-level base multiplier, Q12 (~4096 = 1.0)
        # ADD ROW (2026-09-19): ptr_68 = archive 14848 + 28 (ItemDatabase_AllocateAndInit
        # +0x3FBE0, count never read); Item_ComputeEffectiveStats (+0x422C0) reads
        # `ptr_68 + 180*item_id` only for items whose rf3ItemList category byte (+4) is
        # <= 14 -- in the shipped data exactly ids 0..317, which is why the file has 318
        # rows. A new consumable therefore needs an item id in that block (or a category
        # <= 14 on a higher id, which then reads past this table unless it is grown to it).
        "grow": "id-indexed:item id, gated by rf3ItemList category <= 14 (ids 0..317)",
        "fields": [
            ("hp_recover", 0, "s32"), ("rp_recover", 4, "s32"),
            ("hp_recover_pct", 8, "s32"), ("rp_recover_pct", 12, "s32"),
            ("effect_bits", 16, "u32"), ("food_buff_min", 20, "s32"),
            ("buff_hp", 24, "s32"), ("buff_rp", 28, "s32"), ("buff_atk", 32, "s32"),
            ("buff_def", 36, "s32"), ("buff_mat", 40, "s32"),
            ("buff_hp_pct", 44, "s32"), ("buff_rp_pct", 48, "s32"),
            ("buff_atk_pct", 52, "s32"), ("buff_def_pct", 56, "s32"),
            ("buff_mat_pct", 60, "s32"),
            ("perm_boost0", 160, "s32"), ("perm_boost1", 164, "s32"),
            ("perm_boost2", 168, "s32"), ("perm_boost3", 172, "s32"),
            ("level_scale", 176, "s32"),
        ],
    },
    "rf3ItemEquipmentParam": {
        # 1106 x 180; record index = item id. The base stat record Item_ComputeStats
        # (RF4S.exe+0x43E60) starts from; the labels are PROVEN by where
        # Equip_AccumulateItemStats (+0xB11A0) merges each dword: +12 -> ATK total, +16 -> MAT
        # total, +20 -> DEF, +24 -> MDF, +28 -> STR, +32 -> INT, +36 -> VIT, +40 -> the
        # crit/hunger knob (clamp 0..500), not HP. CORRECTED 2026-09-16: the older entry had
        # no +16 and labelled +24..+40 as mat/mdf/str/int/hp, each one field early.
        # ATK data-checked: Broadsword 5, Steel Sword 29, Wind Sword 496 (MAT 30), Dragon
        # Slayer 7000. +4 = boots effect word, +8 = accessory special bit (one-hot, 27 items),
        # +88..+116 element affinities, +132..+156 status-proc resists, +164 tool charge mult,
        # +176 held-model archive offset.
        # ADD ROW (2026-09-19): loaded as g_itemDatabase->baseStats = archive 14808 + 28 by
        # ItemDatabase_AllocateAndInit (RF4S.exe+0x3FBE0) without reading the count; readers
        # index by item id under the same constant 1108 guard as rf3ItemList (the shipped
        # 1106 rows already leave ids 1106/1107 reading past the table).
        "grow": "fixed:1108",
        "names": "item",
        "fields": [
            ("atk", 12, "s32"), ("mat", 16, "s32"), ("def", 20, "s32"),
            ("mdf", 24, "s32"), ("str", 28, "s32"), ("int", 32, "s32"),
            ("vit", 36, "s32"), ("knob40", 40, "s32"),
            ("boots_word", 4, "u32"), ("special_bit", 8, "u32"),
        ],
    },
    "rf3Parameter": {
        # 200 x 24-byte CHARACTER-LEVEL curve = archive 14813 (row = character level 0..199).
        # IDA-verified: Player_GainXpAndLevelUp (RF4S.exe+0xB2800) reads xp_to_next at
        # `data + 24*level + 28` (= record+0); Actor_ApplyLevelUp (+0xB2CE0) applies, per level,
        # each pool += record[newLevel].colN - record[level].colN, writing equip_record +4/+10/
        # +12/+16/+20 (col2 -> equip+10 = HP max per the disasm; +12/+16/+20 are 24-bit pools).
        #   +0  xp_to_next -- EXP to advance level->level+1 (VERIFIED; 4,10,22,.. -> ~1.5M)
        #   +8  hp_max     -- per-level HP-max base (-> equip_record+10; 56 -> 900)
        # col0/col2 are consumer-anchored; +4/+12/+16/+20 map to equip_record fields (applied as
        # deltas) whose exact stat identity (EXP-base / RP / pools) is per the stats struct.
        "fields": [
            ("xp_to_next", 0, "u32"), ("lvl_exp_base", 4, "u32"), ("hp_max", 8, "u32"),
            ("pool_12", 12, "u32"), ("pool_16", 16, "u32"), ("pool_20", 20, "u32"),
        ],
    },
    "rf3ParameterNPC_01": {"alias": "rf3ParameterNPC"},
    "rf3ParameterNPC_02": {"alias": "rf3ParameterNPC"},
    "rf3ParameterNPC_03": {"alias": "rf3ParameterNPC"},
    "rf3ParameterNPC": {
        # 20 x 16-byte (4 x u32) per-NPC-class tiered growth table = archives 14814/14815/14816
        # (_01/_02/_03), selected by char-id category 0/1/2. *** VESTIGIAL / DEAD DATA ***
        # (RE-confirmed 2026-07-06, static referencer-exhaustion + live memory). These 3 archive
        # ids have exactly TWO referencers binary-wide: Game_PreloadAllArchives (loads them) and
        # Actor_AdvanceLevelByDays (+0x1633b4, GetDatas the category's archive but DISCARDS the
        # pointer -- never indexed). No code reads the buffer, so EDITING THIS HAS NO GAMEPLAY
        # EFFECT. Real NPC/monster growth = rf3Parameter (14813, base+24*level via Actor_ApplyLevelUp)
        # + the static in-EXE g_levelStatBracketTable. Fields kept for inspection only; names are
        # structural (col2/col3 shared across the 3 variants, col0/col1 differ). _01 rec0=[6,9,3,5].
        "fields": [
            ("col0", 0, "u32"), ("col1", 4, "u32"), ("col2", 8, "u32"), ("col3", 12, "u32"),
        ],
    },
    "rf3MapMiniPos": {
        # 873 x 52-byte (13 x s32) per-MAP minimap layout, indexed by map id (872 maps + 1).
        # IDA-verified 2026-09-05 against Minimap_BuildForMap (RF4S.exe+0x13B3F0), the reveal
        # blit (+0x13B2E0 -- x/y arrive in xmm2/xmm3, w/h on the stack) and
        # Minimap_UpdateNpcIcons (+0x13C680). Full write-up + resolver: minimap.py.
        #   +0  sheet          minimap PICTURE = nsFileArchive 12199 + sheet (12199 =
        #                      mini_map_00_city; 73 or > 87 -> mini_map_99_dummy = blank)
        #   +4  origin_x / +8  origin_y   the map's world origin on the picture (drawn px)
        #   +12 reveal_x / +16 reveal_y   fog-of-war rectangle uncovered when the map is
        #   +20 reveal_w / +24 reveal_h   visited (w or h 0 = no fog: towns / interiors)
        #   +28 scale_x  / +32 scale_y    Q12 drawn px per world unit:
        #                                 px = origin + (scale * (world >> 12)) >> 12
        #   +36 icon_slot, +40 parent_sheet (73 = none), +44 icon_x / +48 icon_y: an
        #                      interior's NPC icons are drawn on the parent sheet there
        # CORRECTION: +20/+24 were labelled "marker X/Y" -- they are the reveal WIDTH/HEIGHT
        # (the x/y are +12/+16), and +0 is the picture sheet, not a location icon.
        "fields": [
            ("sheet", 0, "s32"),
            ("origin_x", 4, "s32"), ("origin_y", 8, "s32"),
            ("reveal_x", 12, "s32"), ("reveal_y", 16, "s32"),
            ("reveal_w", 20, "s32"), ("reveal_h", 24, "s32"),
            ("scale_x", 28, "s32"), ("scale_y", 32, "s32"),
            ("icon_slot", 36, "s32"), ("parent_sheet", 40, "s32"),
            ("icon_x", 44, "s32"), ("icon_y", 48, "s32"),
        ],
    },
    "rf3ItemStrengthening": {
        # 1150 x 296-byte per-item STRENGTHENING record = g_itemDatabase->ptr_78 (accessor
        # Item_GetMetadataBytes RF4S.exe+0x43B90: `ptr_78 + 296*item_id`). 74 s32 dwords per row;
        # rows 1108..1149 are the synthetic level/quality tier rows Item_ComputeStats adds as
        # sources 12/13. Fully decoded 2026-09-16 (readers, units, the status-word bits) in
        # rf4s_modkit.strengthening (`rf4mod str ...`); this schema names the columns for the
        # generic param view. Corrections to the older two-field version of this entry:
        #   S[0]  is the upgrade DIFFICULTY (Recipe_ComputeRpCostForOneIngredient +0x3D7D0,
        #         Crafting_AwardUpgradeXP +0x3EF60, item detail row), not a craft level;
        #   S[38] +152 bit 0x4000 is the NON-FOOD marker (not a cooking ingredient): it spoils a
        #         dish and is skipped in the medicine level average (Crafting_CraftFromInputs
        #         +0x3DC86/+0x3DF1E). The low bits of S[38] are the dish effect word (cures 0x1..0x20,
        #         inflicts 0x40..0x1000, 0x2000 leveliser) ORed in by Item_ComputeEffectiveStats.
        # S[1..8] core stats, S[10..12] knobs, S[14..21] on-hit procs + HP drain, S[22..33]
        # resists + reach, S[34..37] heals, S[40..52] fed buff, S[53..66] fed resists/procs,
        # S[67..73] element affinities. S[9], S[13], S[39], S[61..66] are unread.
        "names": "item",
        "fields": [(n, 4 * k, "s32") for k, n in enumerate([
            "difficulty", "atk", "mat", "def", "mdf", "str", "int", "vit", "hunger_knob",
            "unused9", "x44_q12", "x48_q12", "knockback_scale_q12", "unused13",
            "proc_poison", "proc_seal", "proc_paralysis", "proc_sleep", "proc_fatigue",
            "proc_cold", "proc_faint", "hp_drain_attack", "will_resist", "x124_q12", "x128_q12",
            "res_poison", "res_seal", "res_paralysis", "res_sleep", "res_fatigue", "res_cold",
            "res_faint", "res_drain", "reach_scale", "heal_hp", "heal_rp", "heal_hp_pct",
            "heal_rp_pct", "status_word", "unused39", "buff_hp", "buff_rp", "buff_str",
            "buff_int", "buff_vit", "buff_hp_pct", "buff_rp_pct", "buff_str_pct",
            "buff_int_pct", "buff_vit_pct", "buff_x64", "buff_x68", "buff_x72",
            "fed_res_poison", "fed_res_seal", "fed_res_paralysis", "fed_res_sleep",
            "fed_res_fatigue", "fed_res_cold", "fed_res_faint", "fed_proc_poison",
            "fed_proc_seal", "fed_proc_paralysis", "fed_proc_sleep", "fed_proc_fatigue",
            "fed_proc_cold", "fed_proc_faint", "el_fire", "el_water", "el_earth", "el_wind",
            "el_light", "el_dark", "el_love"])],
    },
    "rf3ParamMagic": {
        # 446 x 148-byte ACTION/SKILL/MAGIC param table = archive 14817 (shared by weapon
        # arts, spells, monster attacks; indexed by action_id 0..445). IDA-verified vs
        # Actor_ComputeDamageWithAtkScalarsAndElementBonus (RF4S.exe+0x96B40),
        # Combat_CopyAttackEntry (+0x97250), Actor_BeginSkillEffectAnim (+0x161970):
        #   dmg = base_dmg + (atk_scalar*ATK>>12) + (mat_scalar*MAT>>12), then *dmg_mult,
        #   +effect-level bonus (efflvl_mult), then *element bonus. flags = element/behaviour.
        # (Corrects the old Combat_GetAttackParamTableBase note: +28 is FLAGS, base dmg is +32.)
        # Data-checked: action0 = Fire magic (flags 0x81, base15, mat 1.0x); action445 =
        # physical (atk 1.5x, mult 5x).
        "fields": [
            ("flags", 28, "u32"),        # 0x80=magic; 0x01..0x40=Fire/Water/Earth/Wind/Light/Dark/Love;
                                         # 0x200=ignore-def; 0x400=no-random; 0x200000=always-1-dmg
            ("base_dmg", 32, "s32"),
            ("atk_scalar", 36, "s32"),   # Q12, x attacker ATK_total
            ("mat_scalar", 40, "s32"),   # Q12, x attacker MAT_total
            ("dmg_mult", 44, "s32"),     # Q12 overall damage multiplier (4096 = 1.0x)
            ("efflvl_mult", 48, "s32"),  # Q12 effect-level (charge/spell-tier) scaling
            ("elem_resist", 52, "s32"),  # Q12 (-> AttackInfo+308 via *24576>>12)
            ("stagger", 56, "s32"),      # knockback/stagger (-> *30>>12)
            ("status_proc", 60, "s32"),  # status-infliction weight (-> *-10240>>12)
            ("elem0", 100, "u16"), ("elem1", 104, "u16"), ("elem2", 108, "u16"),
            ("elem3", 112, "u16"), ("elem4", 116, "u16"), ("elem5", 120, "u16"),
            ("elem6", 124, "u16"), ("elem7", 128, "u16"),  # 8 per-element damage scalars
        ],
    },
    "rf3ParamSkillData": {
        # 176 x 32-byte SKILL CAST-COST table = archive 14819 (indexed by action_id). IDA-
        # verified vs Player_ChargeSkillCastCostByActionIdFromArchive14819 (RF4S.exe+0xB2170):
        # RP cost = max(base_cost, (ATK * atk_coef * 16) >> 12), then discounted by the
        # governing skill's level (gov_skill), doubled if cast with the wrong/ unmastered
        # weapon. (Decompiler folds the 28-byte header into the field offset: record base =
        # data + 28 + 32*id, fields record-relative.) Data-checked: skill 35 = 4 rising-cost
        # tiers (RP 4/10/25/30).
        "fields": [
            ("atk_coef", 0, "u32"),      # if nonzero, RP cost scales with ATK
            ("base_cost", 4, "u16"),     # flat RP cost
            ("gov_skill", 12, "s32"),    # governing skill id (for the level discount + mastery gate)
        ],
    },
    "rf3ParamSkill": {
        # 40 x 40-byte per-SKILL stat-growth table = archive 14818 (row index = skill id
        # 0..39). IDA-verified vs Player_ApplyAllSkillGrowthBonusesFromArchive14818 (+0x360E00):
        # for each skill, per-level stat gain = (coef * skill_level) >> 12, times a tier
        # multiplier (tier1 = level/50 + 1 for HP/ATK; tier2 = level/300 + 1 for DEF/MAT/MDEF).
        # ATK gain is additionally capped at (100*coef)>>12 per level. Value-fit confirms the
        # mapping: weapon skills 0-5 = ATK+DEF growth (Axe[3] DEF=2x), magic 6-11 = MAT-lean,
        # Farming[13] HP=8192 (life skills grant big HP). The +20..+36 tail is NOT read by the growth fn
        # (consumer for those not yet found) -> exposed raw as unk*.
        "fields": [
            ("hp_growth", 0, "u32"), ("atk_growth", 4, "u32"), ("def_growth", 8, "u32"),
            ("mat_growth", 12, "u32"), ("mdf_growth", 16, "u32"),
            ("unk20", 20, "u32"), ("unk24", 24, "u32"), ("unk28", 28, "u32"),
            ("unk32", 32, "u32"), ("unk36", 36, "u32"),
        ],
    },
    "rf3TxtCalendar_split2_1": {
        # 45 x 4-byte CALENDAR EVENT table (decoded 2026-08-31; the DATA half of the
        # rf3TxtCalendar split — record i pairs with title i of _split2_2.<locale>).
        # Archive 16340. 21 birthdays + 24 festivals covering the whole year:
        #   char_id     the birthday NPC's char id (1=Vishnal .. 21=Venti), or the
        #               sentinel 30 for festivals (data-verified: every name matches,
        #               e.g. rec 1 char 21 "Ventuswill's Birthday", rec 37 char 6 Bado)
        #   season      0..3 spring/summer/fall/winter
        #   day         1..30
        #   festival_id 0 for birthdays; for festivals: the PP-ORDER FESTIVAL SUB ID —
        #               the calendar board shows the row only while that bit is set in
        #               the festival-scheduled bitmap g_effectAppliedBits.d1 (order
        #               effect 0 sets it; see decomp pp_orders.md/calendar.md)
        # Engine reader traced 2026-08-31: CalendarEvent_IsVisibleAtDate
        # (RF4S.exe+0x1B860) — matches season+day, then gates festivals on the
        # scheduled bitmap and birthdays on GameFlags bit 1007+char_id (NPC met).
        # Editing season/day here is the data-side hook for moving festivals.
        # ADD ROW (2026-09-19): Calendar_FindEventIndexBySeasonDay (RF4S.exe+0x2375A0) scans
        # the records up to the FILE count (u32 @+24 of archive 16340) and the board indexes
        # the TEXT twin rf3TxtCalendar_split2_2.<locale> (16352) by the same record index, so
        # a new event needs its title line appended there too.
        "grow": "paired-text:rf3TxtCalendar_split2_2",
        "fields": [
            ("char_id", 0, "u8"), ("season", 1, "u8"),
            ("day", 2, "u8"), ("festival_id", 3, "u8"),
        ],
    },
    "rf3TxtShopNpc_split2_1": {
        # 378 x 16-byte SHOP DIALOGUE metadata (decoded 2026-08-31): exactly 27
        # groups (char_id 1..27) x 14 fixed line slots, pairing 1:1 with the lines
        # of rf3TxtShopNpc_split2_2.<locale>. Slot roles (from the English text):
        # 0 unused, 1 greeting, 2 browse, 3 ponder, 4 decide, 5 confirm, 6 thanks,
        # 7 come-again, 8 decline, 9 no-space, 10 no-money, 11 out-of-stock,
        # 12 sale-10%%, 13 sale-20%%. Content is written for the char's shop role
        # (keeper lines for keepers, customer lines otherwise — e.g. group 6 Bado
        # "What you want?", group 12 Lin Fa "Welcome!").
        #   voice_a/voice_b: voice-cue pair (e.g. 1608/256), 0 = unvoiced line
        #   emote:    portrait/expression selector (0xBC02 sentinel on no-money)
        #   duration: bubble display frames (90/120/180)
        # ADD ROW (2026-09-19): Schedule_LoadDailyEntriesFromArchive16343 (RF4S.exe+0x675A0)
        # walks ALL records up to the file count (u32 @+24), matching char_id-1 against the
        # NPC and dispatching on `slot` 1..13; it stores the record index, which selects the
        # line of the TEXT twin rf3TxtShopNpc_split2_2.<locale> (16385) -- append there too.
        "grow": "paired-text:rf3TxtShopNpc_split2_2",
        "fields": [
            ("char_id", 0, "u16"), ("slot", 2, "u16"),
            ("voice_a", 4, "u16"), ("voice_b", 6, "u16"),
            ("emote", 8, "u16"), ("duration", 10, "u16"),
            ("flag", 12, "u16"), ("pad", 14, "u16"),
        ],
    },
    "rf3TxtNameEntryBoard_split2_1": {
        # 297 x 4-byte NAME-ENTRY KEYBOARD table (decoded 2026-08-31): one record per
        # key of the name-entry board, pairing 1:1 with _split2_2.<locale>. The u32
        # holds the key's character as its UTF-8 byte sequence packed BIG-endian into
        # the low bytes (0x00E38182 -> e3 81 82 -> あ; plain ASCII = its codepoint).
        # Decode: value.to_bytes(4,'big').lstrip(b'\0').decode('utf-8').
        # ADD ROW: not verified -- the only code site naming archive 16341 is the resource
        # queue in rf4NameEntry_Step0 (RF4S.exe+0x4EF30); the key-count source was not
        # traced (2026-09-19).
        "fields": [("utf8_be", 0, "u32")],
    },
    "rf4TxtShop_split2_1": {
        # 14 x 16-byte, ALL ZERO (checked 2026-08-31) — a count-carrier for the 14
        # shop-tab labels of rf4TxtShop_split2_2.<locale>; no data payload.
        # ADD ROW (2026-09-19): NO code site references archive 16346 (immediate scan of
        # .text), so the exe never loads this .bin by id; the labels come from the TEXT twin.
        "grow": "unused:no code site references archive 16346; only the TEXT twin "
                "rf4TxtShop_split2_2 is read",
        "fields": [],
    },
    "rf4TxtItemParameter_split2_1": {
        # 211 x 84-byte FORMAT-ARGUMENT tables for the item-parameter UI strings of
        # rf4TxtItemParameter_split2_2.<locale> (decoded 2026-08-31). Each record is
        # a BYTE ARRAY (not fixed fields): one parameter-source id per %-placeholder
        # of the paired format string, 0-padded (e.g. rec 150 "[%sSteamed] %s..." ->
        # bytes 82 01 02 03 09 0e ...). Simple label strings have all-zero records.
        # Formatter traced 2026-08-31: the unrolled item-info builders at
        # RF4S.exe+0x326E0/+0x33B70 compute rdi = string_idx*0x54 and read the arg
        # bytes from the record TAIL backwards ([archive + rdi + 0x6F], 0x6E, ...),
        # resolving each through the arg resolver at +0x38DD0 (installed into the
        # UI interface slots at +0x306E0) — a TWO-LEVEL switch on id 1..130:
        #   1        per-unit quality/level list from the inventory slot
        #   2 / 3    stack gold value via Item_ComputeStackGoldValue (+0x454A0)
        #   4/5/6    item-db getters +0x184D20/+0x184D70/+0x184DB0
        #   7,8,9,14,15,51,121,129 individual handlers (+0x166180, +0x42190, ...)
        #   71..78   one shared handler +0x38D60 parameterized by id (the 8-stat/
        #            elemental "%d%" family, e.g. "Dark Res %d%")
        #   130 (0x82) the conditional prefix flag ("[%sSteamed]")
        #   10..128 (rest) second-level table +0x39F18: text-template + numeric
        #            stat pairs read from the 0x400E text archive + a stat array.
        # ADD ROW (2026-09-19): the 60 reader sites in BagMenu_TickEquipSpriteSub
        # (RF4S.exe+0x326E0..+0x33018) each load archive 16344 and address a HARD-CODED
        # record index (rdi = string_idx*0x54), so a 212th record/line pair can never be
        # selected -- the row count is irrelevant to the engine.
        "grow": "fixed:211",
        "fields": [],
    },
    "Fishing_rate_fish_Spring": {
        # 38 x 88 B (22 dwords) fish-SPECIES spawn-weight table, archive 14803 (14804 =
        # Fishing_rate_fish_Spring2, the twin the game switches to once game flag 0xBAE
        # 'Forewater Bell' is set). Row = species index: rows 0..31 = fish item 985+row (Masu
        # Trout, Squid, Taimen, ...), rows 32..37 = g_fishRareSpeciesRemapTable (RF4S.exe
        # +0x4D2528) = items 1017, 1018, 1019, 893, 894, 934.  Decoded 2026-09-19 from the only
        # two code sites that load archive 14803/14804 (offline immediate scan of RF4S.exe):
        #   Fishing_PickSpeciesAndSize (RF4S.exe+0x183A40): dw0..dw7 = spawn weight per ZONE,
        #     zone = 2*season + (1 if the weather code is rain/snow/storm), season 0..3 =
        #     spring/summer/fall/winter (a map's own season override wins). The per-pole rod
        #     modifier (hard-coded in Fishing_RecomputeRodWeights, i16 per species) is added
        #     to a non-zero weight and the sum clamped to 0..99999; a 0 weight stays 0, so a
        #     species with all-zero zone weights never spawns. dw21 = size CLASS 0..3 = the
        #     column of Fishing_rate_lv_* used for the 10-bracket size roll.
        #   Fishing_RollCaughtLevelWeightedBySpecies (+0x183E60): reads dw21 only.
        # dw8..dw20 are read by neither reader (and Fishing_RecomputeRodWeights reads no
        # archive); they are exposed as unused8..unused20 and preserved verbatim.
        "fields": [
            ("w_spring", 0, "s32"), ("w_spring_rain", 4, "s32"),
            ("w_summer", 8, "s32"), ("w_summer_rain", 12, "s32"),
            ("w_fall", 16, "s32"), ("w_fall_rain", 20, "s32"),
            ("w_winter", 24, "s32"), ("w_winter_rain", 28, "s32"),
        ] + [(f"unused{k}", 4 * k, "s32") for k in range(8, 21)] + [("size_class", 84, "u32")],
    },
    "Fishing_rate_fish_Spring2": {"alias": "Fishing_rate_fish_Spring"},
    "Fishing_rate_lv_Spring": {
        # 10 x 16 B size-bracket / catch-level weights, archive 14805 (14806 =
        # Fishing_rate_lv_Spring2, byte-identical in the shipped bundle, selected by the same
        # 0xBAE flag). Row = bracket 0..9 (0 = smallest), column = the species' size_class
        # (Fishing_rate_fish_* dw21).  Readers (2026-09-19):
        #   Fishing_PickSpeciesAndSize (+0x183A40): weighted roll over the 10 rows of column
        #     size_class -> size bracket; size_mm = min + bracket*step + rand(step+1) with
        #     (min, max) from g_fishSizeRangeTable / g_fishMaxSizeTable (+0x4D39D0, 38 pairs)
        #     and step = (max - min) / 10.
        #   Fishing_RollCaughtLevelWeightedBySpecies (+0x183E60): the same 10-row roll for the
        #     catch's level byte, but it indexes the file ONE DWORD EARLY (payload dword
        #     4*level + size_class - 1): class 0 level 0 reads the NLCL count field (10) and
        #     class 0 level L>0 reads row L-1's class3, every other class reads the column to
        #     its left. Reproduce this quirk when balancing; do not 'fix' the table for it.
        "fields": [("class0", 0, "u32"), ("class1", 4, "u32"),
                   ("class2", 8, "u32"), ("class3", 12, "u32")],
    },
    "Fishing_rate_lv_Spring2": {"alias": "Fishing_rate_lv_Spring"},
    "rf3ScheduleID": {
        # 3898 x 12 B NPC schedule SPOTS, archive 15217 (see rf4s_modkit/schedule.py). A slice
        # of rf3Schedule.bin names a spot KIND k; kind k owns records [KIND_PREFIX[k],
        # KIND_PREFIX[k+1]) (g_scheduleSlotKindPrefixTable, RF4S.exe+0x4DCF70) and the game
        # rolls one of them per day weighted by `weight` (NpcSchedule_PickRandomScheduleSlotByKind
        # +0x2318E0). room/x/y/facing/wander are consumed by NpcSchedule_PlaceNpcAtSliceWithJitter
        # (+0x22EAA0: x,y tiles << 12; facing << 8; wander = jitter radius); weight/flags/busy by
        # the picker (flags bit2 = skip when the target map is overcrowded, busy = runtime
        # scratch); action bit0 feeds the plan's 0x200 bit (name per the IDB comment).
        "fields": [("room", 0, "u16"), ("x", 2, "s16"), ("y", 4, "s16"), ("facing", 6, "u8"),
                   ("action", 7, "u8"), ("wander", 8, "u8"), ("weight", 9, "u8"),
                   ("flags", 10, "u8"), ("busy", 11, "u8")],
    },
}

# Schemas matched by filename PREFIX (a whole family sharing one layout).
PREFIX_SCHEMAS = {
    # All rf3Recipe*.bin (cooking/forging/crafting) share this 20-byte layout, archives
    # 14826..14847 (CraftData_GetRecordByArchiveIdAndIdx: record @ data+28+20*idx; record 0
    # is a dummy). Fields (data-verified vs rf3RecipeWeaponA: 328 Broadsword <- 1083 Minerals
    # @ lvl1; upgrade recipes list a base weapon as an ingredient, e.g. Steel Sword+ <- Steel
    # Sword + Minerals):
    #   u16[0] result item ; u16[1..6] up to 6 ingredient item ids ; u16[7]@+14 REQUIRED
    #   SKILL LEVEL (ascending 1/3/4/7/15/16/19/20..) ; u16[8]@+16 sequential global RECIPE ID
    #   (the learned-recipe index; unique across all recipe files).
    # ADD ROW (2026-09-19): honoured -- CraftData_GetRecordCountByArchiveId (RF4S.exe+0x47B50)
    # returns u32 @+24 of the recipe archive (14826..14847) and CraftData_GetRecordByArchiveIdAndIdx
    # (+0x47A80) addresses data+28+20*idx, so an appended recipe is enumerated by the station
    # UI once its `recipe_id` (the learned-recipe bit) is unique.
    "rf3Recipe": {
        "grow": "file-count",
        "names": "item", "name_field": "result",
        "fields": [
            ("result", 0, "u16"),
            ("ing1", 2, "u16"), ("ing2", 4, "u16"), ("ing3", 6, "u16"),
            ("ing4", 8, "u16"), ("ing5", 10, "u16"), ("ing6", 12, "u16"),
            ("level", 14, "u16"), ("recipe_id", 16, "u16"),
        ],
    },
}


# --------------------------------------------------------------------------- #
# rf3CropParam +104 season-affinity helpers (dual-binary + live-data verified
# 2026-07-20; see the rf3CropParam schema comment). Boost bit 0x1000<<i and
# penalty bit 0x10000<<i for season i (spring/summer/fall/winter).
# --------------------------------------------------------------------------- #
CROP_SEASONS = ("spring", "summer", "fall", "winter")
_CROP_SEASON_MASK = 0xFF000  # the 8 season bits (0x1000..0x80000)


def crop_season_decode(season: int) -> dict:
    """Decode an rf3CropParam +104 season word into readable affinity info."""
    grows = [n for i, n in enumerate(CROP_SEASONS) if season & (0x1000 << i)]
    penalized = [n for i, n in enumerate(CROP_SEASONS) if season & (0x10000 << i)]
    method = "hand" if (season & 0x600) == 0x600 else ("tool" if season & 0x400 else "-")
    return {"grows": grows or ["all-season"], "penalized": penalized,
            "harvest": method, "raw": season}


def crop_season_encode(old: int, seasons, single: bool = True) -> int:
    """Build a new +104 season word: boost `seasons`, preserving all non-season
    (harvest-method / property) bits. If single, also set off-season penalty bits
    so the crop grows ONLY in the given season(s) (the vanilla single-season shape)."""
    idx = [CROP_SEASONS.index(s) for s in seasons]
    val = old & ~_CROP_SEASON_MASK          # clear the 8 season bits, keep everything else
    for i in idx:
        val |= (0x1000 << i)                 # in-season growth boost
    if single:
        for i in range(4):
            if i not in idx:
                val |= (0x10000 << i)        # off-season penalty
    return val


class NlclTable:
    def __init__(self, data: bytes):
        if data[:4] != MAGIC:
            raise NlclError(f"not an NLCL table (magic={data[:4]!r})")
        self.build_date = struct.unpack_from("<I", data, 4)[0]
        self.version = struct.unpack_from("<I", data, 16)[0]
        self.byte_size = struct.unpack_from("<I", data, 20)[0]
        self.entry_count = struct.unpack_from("<I", data, 24)[0]
        body = self.byte_size - HEADER_SIZE
        if self.entry_count <= 0 or body <= 0 or body % self.entry_count != 0:
            raise NlclError(
                f"not a flat fixed-record table (entry_count={self.entry_count}, "
                f"body={body}); structured NLCL (e.g. Gen*.bin) — use the gen module")
        self.record_size = body // self.entry_count
        # `data` = the whole file: the NLCL chunk (header + records, byte_size bytes) followed
        # by the generic build-tool footer (`tail`, see nlcl_footer()). Row inserts/deletes
        # splice inside the chunk, so the footer stays at the end and an unchanged table
        # rebuilds byte-exact; after a row edit build() regenerates the (canonical) footer.
        self.data = bytearray(data)
        self._rows_changed = False

    @property
    def tail(self) -> bytes:
        """The bytes past the NLCL chunk = the generic footer (16 B {0,24,0,0} on every
        shipped version-1 param table)."""
        return bytes(self.data[HEADER_SIZE + self.entry_count * self.record_size:])

    @classmethod
    def load(cls, path) -> "NlclTable":
        return cls(pathlib.Path(path).read_bytes())

    # ---- raw field access ------------------------------------------------ #
    def _addr(self, rec: int, off: int) -> int:
        if not (0 <= rec < self.entry_count):
            raise NlclError(f"record {rec} out of range (0..{self.entry_count-1})")
        if not (0 <= off <= self.record_size - 1):
            raise NlclError(f"offset {off} out of record (size {self.record_size})")
        return HEADER_SIZE + rec * self.record_size + off

    def get(self, rec: int, off: int, typ: str = "s32"):
        code, sz = _FMT[typ]
        if off + sz > self.record_size:            # same guard as set(): no cross-record read
            raise NlclError(f"{typ} at +{off} exceeds record size {self.record_size}")
        return struct.unpack_from(code, self.data, self._addr(rec, off))[0]

    def set(self, rec: int, off: int, value: int, typ: str = "s32"):
        code, sz = _FMT[typ]
        if off + sz > self.record_size:
            raise NlclError(f"{typ} at +{off} exceeds record size {self.record_size}")
        struct.pack_into(code, self.data, self._addr(rec, off), int(value))

    def record(self, rec: int) -> bytes:
        base = HEADER_SIZE + rec * self.record_size
        return bytes(self.data[base:base + self.record_size])

    def record_dwords(self, rec: int) -> list[int]:
        r = self.record(rec)
        return [struct.unpack_from("<i", r, k)[0] for k in range(0, len(r) - 3, 4)]

    # ---- schema-aware views ---------------------------------------------- #
    def schema(self, stem: str):
        sch = None
        if stem in FIELD_SCHEMAS:
            sch = FIELD_SCHEMAS[stem]
        else:
            for prefix, psch in PREFIX_SCHEMAS.items():
                if stem.startswith(prefix):
                    sch = psch
                    break
        # follow an "alias" indirection (e.g. rf3ParameterNPC_01 -> rf3ParameterNPC)
        seen = set()
        while sch is not None and "alias" in sch and sch["alias"] not in seen:
            seen.add(sch["alias"])
            sch = FIELD_SCHEMAS.get(sch["alias"])
        return sch

    def row(self, rec: int, stem: str) -> dict:
        sch = self.schema(stem)
        if not sch:
            return {"#": rec, "dwords": self.record_dwords(rec)}
        out = {"#": rec}
        for name, off, typ in sch["fields"]:
            out[name] = self.get(rec, off, typ)
        return out

    def set_field(self, rec: int, name: str, value: int, stem: str):
        sch = self.schema(stem)
        if not sch:
            raise NlclError(f"no schema for {stem}; edit by offset instead")
        for fname, off, typ in sch["fields"]:
            if fname == name:
                self.set(rec, off, value, typ)
                return
        raise NlclError(f"{stem} has no field {name!r}")

    # ---- structural edits: add / remove rows ----------------------------- #
    def has_canonical_footer(self) -> bool:
        """True when the bytes past byte_size are exactly the root-only footer {0,24,0,0}
        (every shipped version-1 param table: 56/56). Tables whose footer lists further
        sub-objects (Gen*, rf3PresentNpc*, SI_*) carry internal offsets that a generic row
        insert would break, so row edits are refused for them."""
        return self.tail == CANONICAL_FOOTER

    def _require_growable(self):
        if not self.has_canonical_footer():
            raise NlclError(
                "this NLCL file is not a plain fixed-record table (its footer lists internal "
                "sub-objects) -- rows cannot be added/removed generically; use the gen / gift / "
                "search_items module for it")

    def _sync_header(self):
        self.byte_size = HEADER_SIZE + self.entry_count * self.record_size
        struct.pack_into("<I", self.data, 20, self.byte_size)
        struct.pack_into("<I", self.data, 24, self.entry_count)
        self._rows_changed = True

    def insert_record(self, index: int, rec: bytes | None = None) -> int:
        """Insert a record at `index` (0..entry_count; == entry_count appends). `rec` is the
        record_size-byte payload, or None for an all-zero row. Later rows shift up by one --
        for tables whose row index IS an id (item / char / quest / skill id) that renumbers
        everything after the insertion point, so prefer append_record() for those.
        Rewrites entry_count (+24) and byte_size (+20); build() emits the regenerated footer."""
        self._require_growable()
        if rec is None:
            rec = bytes(self.record_size)
        rec = bytes(rec)
        if len(rec) != self.record_size:
            raise NlclError(f"record must be exactly {self.record_size} bytes (got {len(rec)})")
        if not (0 <= index <= self.entry_count):
            raise NlclError(f"insert index {index} out of range (0..{self.entry_count})")
        at = HEADER_SIZE + index * self.record_size
        self.data[at:at] = rec
        self.entry_count += 1
        self._sync_header()
        return index

    def append_record(self, rec: bytes | None = None) -> int:
        """Append a record (a copy of an existing row via `t.record(i)`, or None = zero row)
        and return its index (== the old entry_count)."""
        return self.insert_record(self.entry_count, rec)

    def delete_record(self, index: int) -> bytes:
        """Remove row `index` (later rows shift down by one) and return its bytes. The table
        must keep at least one record (NLCL readers divide by entry_count)."""
        self._require_growable()
        if not (0 <= index < self.entry_count):
            raise NlclError(f"record {index} out of range (0..{self.entry_count-1})")
        if self.entry_count == 1:
            raise NlclError("cannot delete the last record of a table")
        at = HEADER_SIZE + index * self.record_size
        old = bytes(self.data[at:at + self.record_size])
        del self.data[at:at + self.record_size]
        self.entry_count -= 1
        self._sync_header()
        return old

    def grow_info(self, stem: str) -> tuple[str | None, str]:
        """(grow code, human sentence) for the table: whether the ENGINE honours an appended
        row. Codes (schema key "grow", IDB-verified per family -- see FIELD_SCHEMAS):
          "file-count"          the reader takes the row count from the file (+24) -> new
                                rows are live once something references their index
          "fixed:<N>"           the reader indexes with a constant / a caller-supplied id
                                space of N rows -> rows past N are never read
          "paired-text:<stem>"  record i is bound to line i of a TEXT archive -> extend
                                the TEXT twin too (`rf4mod text add`)
          "id-indexed:<what>"   rows are addressed by an id other data supplies and the
                                count is never read -> reachable once something uses the id
          "unused:<why>"        the exe never reads the table -> rows do not matter
          None                  not verified"""
        sch = self.schema(stem)
        code = sch.get("grow") if sch else None
        return code, describe_grow(code, self.entry_count)

    # ---- rebuild --------------------------------------------------------- #
    def build(self) -> bytes:
        """The file bytes: NLCL chunk + footer. Byte-identical to the input until a row is
        added or removed; after that the footer is regenerated (root descriptor only, which
        is exactly what every shipped param table carries)."""
        chunk = bytes(self.data[:HEADER_SIZE + self.entry_count * self.record_size])
        return chunk + (nlcl_footer() if self._rows_changed else self.tail)

    def save(self, path):
        pathlib.Path(path).write_bytes(self.build())

    def summary(self, stem: str = "", name_fn=None) -> str:
        sch = self.schema(stem)
        lines = [f"NLCL {stem or '(table)'}  build {self.build_date:#x}  "
                 f"{self.entry_count} records x {self.record_size} B"]
        if sch:
            cols = [f[0] for f in sch["fields"]]
            lines.append("  fields: " + ", ".join(cols))
        return "\n".join(lines)

    def csv_columns(self, stem: str, named: bool = True) -> list:
        """Column names of the table view: '#', the schema field names (or dw0..dwN when
        the table has no schema or named=False), and 'name' when the schema has a name table."""
        sch = self.schema(stem) if named else None
        if sch:
            cols = ["#"] + [f[0] for f in sch["fields"]]
            if sch.get("names"):
                cols.append("name")
            return cols
        return ["#"] + [f"dw{k}" for k in range(self.record_size // 4)]

    def to_csv(self, stem: str, name_fn=None, named: bool = True) -> str:
        """The table view as CSV text: one row per record, the columns of csv_columns().
        `name_fn(id) -> str` resolves the name column (schema 'name_field' or the row
        index); pass None for an empty name column."""
        import csv as _csv
        import io as _io
        sch = self.schema(stem) if named else None
        buf = _io.StringIO()
        w = _csv.writer(buf, lineterminator="\n")
        w.writerow(self.csv_columns(stem, named))
        name_field = sch.get("name_field") if sch else None
        name_off_typ = next(((o, ty) for n, o, ty in (sch["fields"] if sch else [])
                             if n == name_field), None)
        for i in range(self.entry_count):
            if sch:
                row = [i] + [self.get(i, off, typ) for _n, off, typ in sch["fields"]]
                if sch.get("names"):
                    key = self.get(i, *name_off_typ) if name_off_typ else i
                    row.append(name_fn(key) if name_fn else "")
            else:
                row = [i] + self.record_dwords(i)
            w.writerow(row)
        return buf.getvalue()


def nlcl_footer(objects: list[tuple[int, list[int]]] | None = None) -> bytes:
    """The generic NLCL footer the build tool appends past byte_size (decoded in
    search_items.py: 16-byte descriptors {0, object_offset, ref_count, ref_list_offset}
    then the ref lists; the ENGINE never reads it -- every IDB-verified consumer resolves
    offsets manually). Flat param tables carry only the root descriptor {0, 24, 0, 0}.
    `objects` = [(object_offset, [absolute offsets of the u32 fields that store it])]
    for sub-object tables; mirrors SearchItemFile.build()'s footer writer. The list
    offsets are relative to the footer start plus `byte_size`, so callers pass
    `byte_size` via the second form: nlcl_footer_at(byte_size, objects)."""
    if not objects:
        return CANONICAL_FOOTER
    raise NlclError("sub-object footers need the chunk size: use nlcl_footer_at()")


def nlcl_footer_at(byte_size: int, objects: list[tuple[int, list[int]]]) -> bytes:
    """Footer with sub-object descriptors (see nlcl_footer)."""
    out = bytearray(CANONICAL_FOOTER)
    lists_start = byte_size + 16 * (1 + len(objects))
    lp = lists_start
    for tgt, refs in objects:
        out += struct.pack("<IIII", 0, tgt, len(refs), lp if refs else 0)
        lp += 4 * len(refs)
    for _tgt, refs in objects:
        for r in refs:
            out += struct.pack("<I", r)
    return bytes(out)


def describe_grow(code: str | None, count: int) -> str:
    """Human sentence for a schema "grow" code (see NlclTable.grow_info)."""
    if not code:
        return ("add row: engine behaviour not verified for this table -- extra rows are "
                "written but may never be read")
    if code == "file-count":
        return (f"add row: honoured -- the reader takes the row count from the file "
                f"(new rows = index {count}+)")
    if code.startswith("fixed:"):
        n = code.split(":", 1)[1]
        return (f"add row: NOT honoured past row {n} -- the engine indexes this table with a "
                f"constant/id space of {n} rows (rows >= {n} are never read)")
    if code.startswith("paired-text:"):
        twin = code.split(":", 1)[1]
        return (f"add row: honoured only together with its TEXT twin -- record i pairs with "
                f"line i of {twin}; append a line there too (`rf4mod text add`)")
    if code.startswith("id-indexed:"):
        detail = code.split(":", 1)[1]
        return (f"add row: honoured for any id the game can reference -- the reader indexes "
                f"rows by {detail} and never reads the count")
    if code.startswith("unused:"):
        return "add row: irrelevant -- " + code.split(":", 1)[1]
    return f"add row: {code}"


def is_flat_nlcl(data: bytes) -> bool:
    """True if `data` is a flat fixed-record param NLCL table (NOT a structured Gen
    file). Gen*.bin use version 6 and a non-uniform record layout; param tables use
    version 1."""
    if data[:4] != MAGIC:
        return False
    if struct.unpack_from("<I", data, 16)[0] == 6:   # Gen encounter tables
        return False
    try:
        NlclTable(data)
        return True
    except NlclError:
        return False
