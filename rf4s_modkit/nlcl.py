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
import re
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


def type_range(typ: str) -> tuple[int, int]:
    """(min, max) value a field of int type `typ` can hold."""
    bits = _FMT[typ][1] * 8
    if typ.startswith("s"):
        return -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    return 0, (1 << bits) - 1


# --------------------------------------------------------------------------- #
# Per-file field schemas (verified offsets). Each: list of (name, offset, type).
# `key` is the field used as the row label / lookup id (default: record index).
# --------------------------------------------------------------------------- #
FIELD_SCHEMAS = {
    "MapOre_Rate": {
        # 25 records x 32 B — the ORE/MINERAL CONFIG table indexed by a type-0
        # MOBJ spawn's f10 (mining-rock spawn points). CORRECTED 2026-09-01
        # against TileObject_ApplyToolHit's reads (RF4S.exe+0x18B100/
        # +0x18B32A): field 0 is the gatherable KIND
        # (26..37 -> the rock sprite + "Mineral" char 459+kind), NOT an
        # "area id"; +4/+8 are the deplete/scrap probability bases, and the
        # weights sit at +12/16/20 pairing items +24/26/28 with rare at +30.
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
        # quest's `category` byte indexes the string directly, Quest_LoadDetailStrings
        # RF4S.exe+0x1ED1F0). byte0 = 2 on rows
        # 1..3 ("Item Needed: %s" variants), else 0; bytes 1..3 always 0. VERIFIED DEAD DATA
        # (2026-09-19): every code site that names archive 16345 or its pointer
        # (the qword at RF4S.exe+0xE9B188) only loads / zeroes / releases it -- QuestMenu_LoadDatabaseArchives
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
        # Player_gainEXP (+0xB3DE0) clamps the skill's XP counter to 0..0xFFFFFF before the
        # unsigned `xp < table[min(level,99)]` compare, so a threshold above 0xFFFFFF can never
        # be reached (the skill stops levelling); 0 levels instantly.
        "grow": "fixed:100",
        "fields": [("xp_to_next", 0, "s32")],
        "limits": {"xp_to_next": (0, 0xFFFFFF, "Player_gainEXP clamps skill XP to 0xFFFFFF, "
                                               "so a larger threshold is never reached")},
    },
    "rf3ParamSkillExpFarm": {"alias": "rf3ParamSkillExp"},
    "rf3ParamSkillExpFish": {"alias": "rf3ParamSkillExp"},
    "rf3ParamSkillExpMix": {"alias": "rf3ParamSkillExp"},
    "rf3ParamSkillExpSleep": {"alias": "rf3ParamSkillExp"},
    "rf3ItemList": {
        "names": "item",   # row index IS the item id (names from the game's item names)
        # ADD ROW (2026-09-19): the loader ItemDatabase_AllocateAndInit (RF4S.exe+0x3FBE0)
        # stores only archive+28 (never the +24 count) and readers index by item id, which
        # the code bounds with the CONSTANT 1108 (0x454, e.g. Item_ComputeStackGoldValue
        # +0x454A0: `if (item_id >= 0x454) return 0`). Rows past 1108 are unreachable; the
        # per-item parallel tables + rf3TxtItem_split2_1/_2 (names/descriptions) share the id.
        # PRICES (2026-09-24, Item_ComputeStackGoldValue +0x454A0): gold = price *
        # rf3PriceTable[row][stack level] / 100 in u32 arithmetic; the SHOP buy path
        # (Shop_BuildPageStockFromTemplate +0x3BC70, use_alt=1) uses buy_price (+8) with
        # row byte +6, every sell/ship/value path (ShippingBin_ProcessOvernight +0x5F000,
        # use_alt=0) uses sell_price (+12) with row byte +7. A row byte > 9 makes the item
        # worth 0 (the guard returns 0), so the row bytes are limited to 0..9.
        "grow": "fixed:1108",
        "fields": [
            ("base_item", 0, "u32"),     # base/family item (King Cabbage -> Cabbage)
            ("category", 4, "u8"),       # ItemMetadata_t +4: <= 14 = usable (rf3UseItemParam row), 0..2/46 = crops
            ("buy_price_row", 6, "u8"),  # rf3PriceTable row for the shop buy price
            ("sell_price_row", 7, "u8"),  # rf3PriceTable row for the sell / ship value
            ("buy_price", 8, "u32"),     # shop buy price (before the 10%/20% sale discount)
            ("sell_price", 12, "u32"),   # verified: Cabbage 680 / Turnip 30 / Pumpkin 110 (read unsigned)
            ("crop_link", 16, "u32"),    # ItemMetadata_t.data_10: rf3CropParam record a SEED plants (Turnip Seed 753 -> 72)
        ],
        "limits": {
            "buy_price_row": (0, 9, "Item_ComputeStackGoldValue returns 0 for a price row > 9"),
            "sell_price_row": (0, 9, "Item_ComputeStackGoldValue returns 0 for a price row > 9"),
        },
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
        # pm (per-mille ‰ chance; Actor_RecomputeAllStats +0xAD440 copies the chances only
        # for char ids 48..140 and >= 144). Field layout = the IDB's CharTemplate_t.
        # STATS CORRECTED 2026-09-24 (Actor_RecomputeAllStats RF4S.exe+0xAD440):
        # +44/+48/+52 are the STR/INT/VIT attributes -- ATK = flat_atk(+60) + STR,
        # MAT = flat_mat(+64) + INT, DEF = flat_def(+72) + VIT/2, MDF = flat_mdf(+76) + VIT/2
        # (before level growth). The old schema called +44/+48/+52 "atk"/"def"/"mat", so an
        # edit of "def" actually raised the monster's MAGIC attack; those names now error.
        # +80..+88 = the level-up STR/INT/VIT roll weights and +92..+108 the per-level
        # ATK/MAT/DEF/MDF/HP growth percents (Actor_ApplyLevelUp +0xB2CE0).
        # element affinities (s32, Q12: +4096 = +100% damage taken = WEAK; negative = resist)
        # + status-proc resists (low s16 of each dword, Q12: 4096 = 100% immune) IDA-verified vs
        # Actor_LoadBaseStatsFromTemplate (RF4S.exe+0xAF940): elements [0..7] copied to
        # stats+100..128 (note the swap: +176=neutral -> stats+128, +180=love -> stats+124);
        # resists [k] copied to stats+152+2k. RESIST ORDER CORRECTED 2026-09-24: status k =
        # poison, seal, paralysis, sleep, fatigue, cold, faint (+ drain) -- the order of the
        # proc mask bits (Combat_GetStatusProcMask +0x961B0 tests stats+152+2k for bit k), of
        # the cure bits Item_UseOnActor (+0xB4150) clears, and of the resist skills 26..32
        # (Player_ApplyAllSkillGrowthBonusesFromArchive14818 +0xB0E00). The old schema put
        # paralysis/sleep/seal at +188/+192/+196 (one slot off).
        # Live-cross-checked: boss[200] = ~100% status resist + fire-resist/water-weak.
        # ADD ROW (2026-09-19): Char_GetTemplate (RF4S.exe+0x1C63B0) copies archive 14812 +
        # 28 + 308*char_id into g_charTemplateBuffer with NO bound check and never reads the
        # +24 count, so any char id the game can reference (Gen rosters, scripts, `monster
        # new`) reaches its row; give it name/description lines in rf3TxtNpc_split2_1/_2.
        "grow": "id-indexed:char id (Gen rosters / scripts); names in rf3TxtNpc_split2_1/_2",
        "fields": [
            ("ai_script", 34, "u16"),
            ("hp", 40, "u32"), ("str", 44, "s32"), ("int", 48, "s32"),
            ("vit", 52, "s32"), ("kill_xp", 56, "u32"),
            ("flat_atk", 60, "s32"), ("flat_mat", 64, "s32"), ("hunger_drain", 68, "s32"),
            ("flat_def", 72, "s32"), ("flat_mdf", 76, "s32"),
            ("lvup_w_str", 80, "s32"), ("lvup_w_int", 84, "s32"), ("lvup_w_vit", 88, "s32"),
            ("grow_atk_pct", 92, "s32"), ("grow_mat_pct", 96, "s32"),
            ("grow_def_pct", 100, "s32"), ("grow_mdf_pct", 104, "s32"),
            ("grow_hp_pct", 108, "s32"),
            ("tame_base", 220, "u16"),   # MonsterTame_RollAttemptWithItem: 0 = untameable
            ("base_level", 288, "u16"),  # spawn level for char ids >= 48
            ("model", 272, "s16"), ("anim", 274, "s16"),   # -1 = none (the exe tests == -1)
            ("drop0_id", 228, "u16"), ("drop1_id", 230, "u16"),
            ("drop2_id", 232, "u16"), ("drop3_id", 234, "u16"),
            ("drop0_pm", 236, "u32"), ("drop1_pm", 240, "u32"),
            ("drop2_pm", 244, "u32"), ("drop3_pm", 248, "u32"),
            ("elem_fire", 152, "s32"), ("elem_water", 156, "s32"),
            ("elem_earth", 160, "s32"), ("elem_wind", 164, "s32"),
            ("elem_light", 168, "s32"), ("elem_dark", 172, "s32"),
            ("elem_none", 176, "s32"), ("elem_love", 180, "s32"),
            ("res_poison", 184, "s16"), ("res_seal", 188, "s16"),
            ("res_paralysis", 192, "s16"), ("res_sleep", 196, "s16"),
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
        # (+0xB4150); field offsets are that function's v78[] effect-buffer reads.
        # CORRECTED 2026-09-24: the fed buff at +32/+36/+40 (and the % scalers +52/+56/+60)
        # is STR / INT / VIT -- Item_UseOnActor multiplies +52 by str_base, +56 by int_base,
        # +60 by vit_base -- not ATK/DEF/MAT; the permanent raises +160..+172 add to base HP /
        # STR / INT / VIT. +64..+156 are the same while-fed knobs / resists / procs /
        # elements that rf3ItemStrengthening S[50..73] add per ingredient (Item_Compute
        # EffectiveStats sums S[k] into record dword k-34), named alike.
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
        #   +24 buff_hp / +28 buff_rp / +32 buff_str / +36 buff_int / +40 buff_vit
        #                      flat temporary stat buffs while the food buff is active
        #   +44 buff_hp_pct / +48 buff_rp_pct / +52 buff_str_pct / +56 buff_int_pct /
        #   +60 buff_vit_pct   the %-of-max/base scalers paired with +24..+40 (Q12)
        #   +160..+172 perm_hp / perm_str / perm_int / perm_vit  PERMANENT raises of the
        #                      base HP / STR / INT / VIT (stat-up seeds/dishes)
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
            ("buff_hp", 24, "s32"), ("buff_rp", 28, "s32"), ("buff_str", 32, "s32"),
            ("buff_int", 36, "s32"), ("buff_vit", 40, "s32"),
            ("buff_hp_pct", 44, "s32"), ("buff_rp_pct", 48, "s32"),
            ("buff_str_pct", 52, "s32"), ("buff_int_pct", 56, "s32"),
            ("buff_vit_pct", 60, "s32"),
            ("buff_x64", 64, "s32"), ("buff_x68", 68, "s32"), ("buff_x72", 72, "s32"),
        ] + [(f"fed_res_{s}", 76 + 4 * k, "s32") for k, s in enumerate(
            ("poison", "seal", "paralysis", "sleep", "fatigue", "cold", "faint"))
        ] + [(f"fed_proc_{s}", 104 + 4 * k, "s32") for k, s in enumerate(
            ("poison", "seal", "paralysis", "sleep", "fatigue", "cold", "faint"))
        ] + [(f"el_{s}", 132 + 4 * k, "s32") for k, s in enumerate(
            ("fire", "water", "earth", "wind", "light", "dark", "love"))
        ] + [
            ("perm_hp", 160, "s32"), ("perm_str", 164, "s32"),
            ("perm_int", 168, "s32"), ("perm_vit", 172, "s32"),
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
        # `data + 24*level + 28` (= record+0); Actor_ApplyLevelUp (+0xB2CE0) applies, per level
        # below 199, each base stat += record[newLevel].colN - record[level].colN into the base
        # stat block (PlayerStats_t+416): +4 base HP (dword), +10 base RP (u16, clamp 0..65535),
        # +12/+16/+20 base STR/INT/VIT (24-bit, clamp 0..10M). Actor_LoadBaseStatsFromTemplate
        # (+0xAF940) then copies those into hp_max / rp_max / str_base / int_base / vit_base.
        # CORRECTED 2026-09-24: the old names put "hp_max" on +8 (it is the RP column) and
        # called the HP column "lvl_exp_base"; those names now error with a hint.
        #   +0  xp_to_next -- EXP to advance level->level+1 (VERIFIED; 4,10,22,.. -> ~1.5M)
        #   +4  hp  (25 -> 23144)   +8 rp (56 -> 900)   +12/+16/+20 str / int / vit
        "fields": [
            ("xp_to_next", 0, "u32"), ("hp", 4, "u32"), ("rp", 8, "u32"),
            ("str", 12, "u32"), ("int", 16, "u32"), ("vit", 20, "u32"),
        ],
        "limits": {"rp": (0, 0xFFFF, "the base RP is a u16 (Actor_ApplyLevelUp clamps the "
                                     "running total to 65535)")},
    },
    "rf3ParameterNPC_01": {"alias": "rf3ParameterNPC"},
    "rf3ParameterNPC_02": {"alias": "rf3ParameterNPC"},
    "rf3ParameterNPC_03": {"alias": "rf3ParameterNPC"},
    "rf3ParameterNPC": {
        # 20 x 16-byte (4 x u32) per-NPC-class tiered growth table = archives 14814/14815/14816
        # (_01/_02/_03), selected by char-id category 0/1/2. *** VESTIGIAL / DEAD DATA ***
        # (RE-confirmed 2026-07-06, static referencer-exhaustion + live memory). These 3 archive
        # ids have exactly TWO referencers binary-wide: Game_PreloadAllArchives (loads them) and
        # Actor_AdvanceLevelByDays (+0xB32D0, GetDatas the category's archive but DISCARDS the
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
        # S[67..73] element affinities. S[9], S[13], S[39] are unread; S[61..66] are summed
        # into the dish record but zero in the shipped file.
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
        # Combat_CopyAttackEntryAndScaleDamageToItemRecord (+0x97250), Actor_BeginSkillEffectAnim
        # (+0x161970):
        #   dmg = base_dmg + (atk_scalar*ATK>>12) + (mat_scalar*MAT>>12), then *dmg_mult,
        #   +effect-level bonus (efflvl_mult), then *element bonus. flags = element/behaviour.
        # (Corrects the old Combat_GetAttackParamTableBase note: +28 is FLAGS, base dmg is +32.)
        # Data-checked: action0 = Fire magic (flags 0x81, base15, mat 1.0x); action445 =
        # physical (atk 1.5x, mult 5x).
        "fields": [
            ("flags", 28, "u32"),        # element + behaviour bits: use Flags... (every bit the
                                         # exe reads is named; FLAG_FIELDS lists the readers)
            ("base_dmg", 32, "s32"),
            ("atk_scalar", 36, "s32"),   # Q12, x attacker ATK_total
            ("mat_scalar", 40, "s32"),   # Q12, x attacker MAT_total
            ("dmg_mult", 44, "s32"),     # Q12 overall damage multiplier (4096 = 1.0x)
            ("efflvl_mult", 48, "s32"),  # Q12 effect-level (charge/spell-tier) scaling
            ("elem_resist", 52, "s32"),  # Q12 (-> AttackInfo+308 via *24576>>12)
            ("stagger", 56, "s32"),      # Q12 hit-stun multiplier: the attack's stun word =
                                         # stagger*30>>12 (+0x97250 -> AttackInfo+332);
                                         # Combat_ResolveHit (+0xA3D..) scales it by the
                                         # target's own Q12 factor (stats +68) into the
                                         # target's stun timer (actor +576). 4096 = 1x = 30
                                         # frames, the same as a plain weapon hit
                                         # (Attack_PopulateAttackInfoFromWeaponAndStatus
                                         # writes 30); 0 = the target does not flinch
            ("status_proc", 60, "s32"),  # status-infliction weight (-> *-10240>>12)
            # the STATUS block, copied as u16 (the low half of each dword) into the attack
            # (Combat_CopyAttackEntryAndScaleDamageToItemRecord +0x97250 and
            # Combat_FillAttackInfoFromEffectKind +0xED2D0 -> AttackInfo +334 / +340..+354)
            ("Hunger", 96, "u16"),       # -> AttackInfo+334 (hunger; shipped 0..25)
            ("Psn Atk%", 100, "u16"), ("Seal Atk%", 104, "u16"), ("Par Atk%", 108, "u16"),
            ("Slp Atk%", 112, "u16"), ("Ftg Atk%", 116, "u16"), ("Sick Atk%", 120, "u16"),
            ("Faint Atk%", 124, "u16"),  # Q12 status proc chances poison..faint (409 = 10%)
            ("Drain Atk%", 128, "u16"),  # Q12 HP drain (2048 = 50%)
            # the player's cost and reward (Effect_ApplyByKindAndSpawn +0xECEC0, Combat_ResolveHit)
            ("Skill Exp", 132, "u32"),   # XP given to skill `Skill Type`: Player_gainEXP(actor,
                                         # +132, +144) -- on cast, and on a hit only when both
                                         # costs are 0 (a free attack)
            ("RP Cost", 136, "u32"),     # flat RP cost (action 87 doubles it below skill level 50
                                         # with the wrong weapon category)
            ("RP% Cost", 140, "s32"),    # Q12 share of the caster's MAX RP; non-zero replaces RP Cost
            ("Skill Type", 144, "u16"),  # skill id that receives the XP (and whose rp_discount in
                                         # rf3ParamSkill lowers the cost)
        ],
    },
    "rf3ParamSkillData": {
        # 176 x 32-byte SKILL CAST-COST table = archive 14819 (indexed by action_id). IDA-
        # verified vs Player_ChargeSkillCastCostByActionIdFromArchive14819 (RF4S.exe+0xB2170):
        # RP cost = max(base_cost, (rp_max_coef * 16 * RP_MAX) >> 12) (CORRECTED 2026-09-24:
        # the coefficient scales the caster's MAX RP, stats+12, not ATK), then * (4096 -
        # min(gov skill level, 100) * rf3ParamSkill[gov_skill].rp_discount) >> 12, doubled if
        # cast with the wrong / unmastered weapon. The result is truncated to u16. (Decompiler
        # folds the 28-byte header into the field offset: record base = data + 28 + 32*id,
        # fields record-relative.) Data-checked: skill 35 = 4 rising-cost tiers (RP 4/10/25/30).
        "fields": [
            ("rp_max_coef", 0, "u32"),   # if nonzero, RP cost scales with the caster's max RP
            ("base_cost", 4, "u16"),     # flat RP cost (compared as the dword +4, so keep +6 = 0)
            ("gov_skill", 12, "s32"),    # governing skill id (for the level discount + mastery gate)
        ],
        "limits": {"gov_skill": (0, 39, "indexes the 40-row rf3ParamSkill table and the "
                                        "caster's 40 skill slots")},
    },
    "rf3ParamSkill": {
        # 40 x 40-byte per-SKILL stat-growth table = archive 14818 (row index = skill id
        # 0..39). IDA-verified vs Player_ApplyAllSkillGrowthBonusesFromArchive14818 (+0xB0E00),
        # CORRECTED 2026-09-24 (the old schema called the columns HP/ATK/DEF/MAT/MDF): for each
        # skill at level L, with t50 = ceil(L/50) and t300 = ceil(L/300):
        #   +0  hp_growth   hp_max  += ((coef * L) >> 12) * t50
        #   +4  rp_growth   rp_max  += min((coef * L) >> 12, 100*coef/4096)   (clamp 0..65535)
        #   +8  str_growth  str_base += ((coef * L) >> 12) * t300
        #   +12 int_growth  int_base += ...        +16 vit_growth  vit_base += ...
        #   +28 elem_dmg    magic skills 6..12 only: per-level element damage bonus added for
        #                   the matching element bit (Actor_ComputeDamageWithAtkScalarsAndElement
        #                   Bonus +0x96B40 reads rf3ParamSkill[6+e] +28)
        #   +36 rp_discount per-level Q12 discount on RP costs governed by this skill
        #                   (Player_ChargeSkillCastCostByActionIdFromArchive14819 +0xB2170:
        #                   cost * (4096 - min(L,100)*coef) >> 12)
        # Farming[13] HP=8192 (life skills grant big HP). +20/+24/+32 have no reader found.
        "fields": [
            ("hp_growth", 0, "u32"), ("rp_growth", 4, "u32"), ("str_growth", 8, "u32"),
            ("int_growth", 12, "u32"), ("vit_growth", 16, "u32"),
            ("unk20", 20, "u32"), ("unk24", 24, "u32"), ("elem_dmg", 28, "s32"),
            ("unk32", 32, "u32"), ("rp_discount", 36, "s32"),
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
        #               effect 0 sets it)
        # Engine reader traced 2026-08-31: Calendar_IsEventActive
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
        # queue in rf4NameEntry_Step0_QueueArchiveLoads (RF4S.exe+0x4EF30); the key-count source was not
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
        # the picker (busy = runtime scratch); the flag bits are in FLAG_FIELDS and
        # schedule.py (re-read 2026-09-30: 0x1 run, 0x2 replaceable, 0x4 season 1 only,
        # 0x8 ignore crowding). The picker sums the weights of a kind in a u8, so a kind's
        # total weight must stay <= 255 (schedule.spot_weight_problems checks it; shipped
        # max 152).
        "fields": [("room", 0, "u16"), ("x", 2, "s16"), ("y", 4, "s16"), ("facing", 6, "u8"),
                   ("action", 7, "u8"), ("wander", 8, "u8"), ("weight", 9, "u8"),
                   ("flags", 10, "u8"), ("busy", 11, "u8")],
        "limits": {"room": (0, 871, "a room id of the 872-room enum")},
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


# ---- fixed-point fields ---------------------------------------------------------
# Fields the exe reads as FIXED-POINT numbers: the stored integer is the value times
# 2**bits and the game multiplies, then shifts right by `bits`. Q12 (bits 12: 4096 = 1.0)
# is the engine's usual scale -- a 32-bit field is Q20.12, a 16-bit one Q4.12 -- and the
# crop growth-rate multipliers are Q7 (128 = 1.0). Only fields whose reader was checked
# are listed (see each schema's comments); the rest stay plain integers.
# {table stem: {field: fraction bits}}
FIXED_FIELDS = {
    "rf3ParamMagic": {f: 12 for f in ("atk_scalar", "mat_scalar", "dmg_mult", "efflvl_mult",
                                      "elem_resist", "stagger", "Psn Atk%", "Seal Atk%",
                                      "Par Atk%", "Slp Atk%", "Ftg Atk%", "Sick Atk%",
                                      "Faint Atk%", "Drain Atk%", "RP% Cost")},
    "rf3NpcParam": {**{f"elem_{e}": 12 for e in ("fire", "water", "earth", "wind", "light",
                                                 "dark", "none", "love")},
                    **{f"res_{s}": 12 for s in ("poison", "seal", "paralysis", "sleep",
                                                "fatigue", "cold", "faint", "drain")}},
    "rf3UseItemParam": {f: 12 for f in ("hp_recover_pct", "rp_recover_pct", "buff_hp_pct",
                                        "buff_rp_pct", "buff_str_pct", "buff_int_pct",
                                        "buff_vit_pct", "level_scale")},
    "rf3ParamSkill": {f: 12 for f in ("hp_growth", "rp_growth", "str_growth", "int_growth",
                                      "vit_growth", "rp_discount")},
    "rf3MapMiniPos": {"scale_x": 12, "scale_y": 12},
    "rf3ItemStrengthening": {"knockback_scale_q12": 12},
    "rf3CropParam": {f: 7 for f in ("gmul_size", "gmul_1", "gmul_2", "gmul_3")},
}
MULT_SIGNS = ("x", "X", "\u00d7")          # a trailing x / × marks a multiplier (1.5x = 150%)


# ---- bit-set fields ----------------------------------------------------------------
# Fields that are a set of independent bits: the GUI gives them one tick box per bit, the CLI
# takes `field=+name,-name`. {table stem: {field: {mask: name}}}; an empty dict = a bit set
# whose bits are not named yet (tick boxes "bit N"). Names only where the reader was checked:
#   rf3ParamMagic.flags: copied to AttackInfo+320 (RF4S.exe+0x97250 / +0xED2D0). Every reader
#     found by a byte scan of the exe for bit tests at +320..+323 and for loads of +320 followed
#     by a test (2026-09-30):
#     0x01..0x40 element (Actor_ComputeDamageWithAtkScalarsAndElementBonus +0x96B40,
#       Combat_GetElementBonus +0x96140, the hit sounds); fire also shears Wooly 111/176.
#     0x80 magic: the defender's MDF instead of DEF (Combat_ComputeDamage +0x95A70).
#     0x100 a hit on the player takes RP/HP directly, no hit reaction (Combat_ResolveHit +0xA2A50).
#     0x200 ignore DEF; 0x400 no +-12.5% variance; 0x200000 always 1 damage; 0x400000 an element
#       resist is halved (all Combat_ComputeDamage).
#     0x800 SE_HAMMER_HIT, 0x10000 STRM_HIT_WATER when no element (+0xA2680 sound router).
#     0x1000 full stun: the stun ignores the target's resistance and rooted field monsters
#       (48..199) can be knocked back (Combat_ResolveHit).
#     0x2000 the turnip-and-stars hit effect (efc_kabu + efc_star, actions 116/117) and
#       SE_NPC_HIT instead of the element spark -- the effect of hitting a villager.
#     0x8000 grab: when the attacker is Marionetta (char 231) the hit grabs the target
#       (Actor_OnGrabbedByMount).
#     0x800000 / 0x1000000 / 0x2000000 / 0x4000000: on a Faint proc, 50% each to drop a Cabbage /
#       Pumpkin / Potato / Turnip-or-Pink-Turnip (Combat_GetStatusProcMask +0x961B0).
#     0x40000000 never a critical hit (Combat_ResolveHit's crit roll).
#     No reader found for 0x4000, 0x20000, 0x40000, 0x80000, 0x100000, 0x8000000, 0x10000000,
#     0x20000000, 0x80000000 (unused; the shipped file sets none of them).
#   rf3UseItemParam.effect_bits: Item_UseOnActor (RF4S.exe+0xB4150) clears actor status bits
#     `effect_bits & 0x3F` (cures), ORs `(effect_bits & 0x1FC0) >> 6` into the inflicted
#     statuses and levels up on 0x2000; status order poison, seal, paralysis, sleep, fatigue,
#     sickness (cold), faint (the order of the proc / resist bits).
_STATUS = ("poison", "seal", "paralysis", "sleep", "fatigue", "sickness", "faint")
FLAG_FIELDS = {
    "rf3ParamMagic": {"flags": {
        0x1: "Fire", 0x2: "Water", 0x4: "Earth", 0x8: "Wind", 0x10: "Light", 0x20: "Dark",
        0x40: "Love", 0x80: "Magic", 0x100: "Direct damage to player", 0x200: "Ignore DEF",
        0x400: "No random spread", 0x800: "Hammer hit sound", 0x1000: "Full stun",
        0x2000: "Turnip-and-stars hit effect", 0x8000: "Grab (Marionetta)",
        0x10000: "Water hit sound", 0x200000: "Always 1 damage", 0x400000: "Half element resist",
        0x800000: "Faint drop Cabbage", 0x1000000: "Faint drop Pumpkin",
        0x2000000: "Faint drop Potato", 0x4000000: "Faint drop Turnip",
        0x40000000: "No critical hits"}},
    "rf3UseItemParam": {"effect_bits": {
        **{1 << k: "Cure " + s for k, s in enumerate(_STATUS[:6])},
        **{1 << (6 + k): "Inflict " + s for k, s in enumerate(_STATUS)},
        0x2000: "Level up"}},
    "rf3ItemEquipmentParam": {"boots_word": {}, "special_bit": {}},
    "rf3ItemStrengthening": {"status_word": {}},
    # rf3ScheduleID.flags: see rf4s_modkit/schedule.py (copied to the NPC's day plan +5)
    "rf3ScheduleID": {"flags": {0x1: "Run", 0x2: "Replaceable", 0x4: "Season 1 only",
                                0x8: "Ignore crowding"}},
    "rf3TxtShopNpc_split2_1": {"flag": {}},
    "rf4TxtQuestRequestDetailFormat_split2_1": {"flag": {}},
}


# ---- reference fields, value names, row names --------------------------------------------
# What a number in a field (or a row index) stands for, so the GUI can show a name and edit with
# a searchable picker. Only meanings stated as verified in the schema notes above are listed.
# Kinds: "item" (0 = an empty slot; recipe ingredients may be a category item such as 1083
# Minerals: any item of that category is accepted), "char", "room", "skill". Matched by stem
# (aliases followed), then by the PREFIX_SCHEMAS family prefix.
REF_FIELDS = {
    "rf3Recipe": {f: "item" for f in ("result", "ing1", "ing2", "ing3", "ing4", "ing5", "ing6")},
    "MapOre_Rate": {f: "item" for f in ("item0", "item1", "item2", "rare_item")},
    "rf3ItemList": {"base_item": "item"},
    "rf3TxtCalendar_split2_1": {"char_id": "char"},       # 30 = festival (VALUE_NAMES)
    "rf3TxtShopNpc_split2_1": {"char_id": "char"},
    "rf3TxtQuest_split3_1": {"client_id": "char"},
    "rf3ParamSkillData": {"gov_skill": "skill"},
    "rf3ParamMagic": {"Skill Type": "skill"},
    "rf3ScheduleID": {"room": "room"},
}
_SEASONS = {0: "Spring", 1: "Summer", 2: "Fall", 3: "Winter"}
# Named values of plain fields (shown as "Name (value)" and picked from a list).
VALUE_NAMES = {
    "rf3TxtCalendar_split2_1": {"season": _SEASONS, "char_id": {30: "(festival)"}},
    "rf3TxtShopNpc_split2_1": {"slot": {
        0: "unused", 1: "greeting", 2: "browse", 3: "ponder", 4: "decide", 5: "confirm",
        6: "thanks", 7: "come again", 8: "decline", 9: "no space", 10: "no money",
        11: "out of stock", 12: "sale 10%", 13: "sale 20%"}},
    "rf3TxtQuest_split3_1": {"client_id": {0: "(placeholder)", 22: "Anonymous", 23: "Anonymous"}},
}
# What a row index is: "item" / "room" / "skill" / "fish" (rows 0..31 = item 985+row, 32..37 =
# the rare remap, see the Fishing_rate_fish_Spring notes) / "level" (row L = level L -> L+1).
ROW_NAMES = {
    "rf3ParamSkill": "skill",
    "rf3MapMiniPos": "room",
    "Fishing_rate_fish_Spring": "fish",
    "rf3Parameter": "level",
    "Fishing_rate_lv_Spring": "bracket",
}
FISH_RARE_ITEMS = (1017, 1018, 1019, 893, 894, 934)


def canonical_stem(stem: str) -> str:
    """The schema key a file uses: aliases followed, family members mapped to their prefix."""
    seen = set()
    while stem in FIELD_SCHEMAS and "alias" in FIELD_SCHEMAS[stem] and stem not in seen:
        seen.add(stem)
        stem = FIELD_SCHEMAS[stem]["alias"]
    if stem in FIELD_SCHEMAS:
        return stem
    return next((p for p in PREFIX_SCHEMAS if stem.startswith(p)), stem)


def ref_kind(stem: str, name: str):
    """'item' / 'char' / 'room' / 'skill' when the field holds such an id, else None."""
    return REF_FIELDS.get(canonical_stem(stem), {}).get(name)


def is_item_field(stem: str, name: str) -> bool:
    """True when the field holds an item id."""
    return ref_kind(stem, name) == "item"


def value_names(stem: str, name: str) -> dict:
    """{value: name} for a field with named values ({} when none)."""
    return VALUE_NAMES.get(canonical_stem(stem), {}).get(name, {})


def row_kind(stem: str):
    """What a row index means for this table (see ROW_NAMES), or None."""
    c = canonical_stem(stem)
    sch = FIELD_SCHEMAS.get(c) or PREFIX_SCHEMAS.get(c) or {}
    if sch.get("names") == "item" and not sch.get("name_field"):
        return "item"
    return ROW_NAMES.get(c)


def fish_item(row: int):
    """The fish item id of a Fishing_rate_fish_* row."""
    if 0 <= row < 32:
        return 985 + row
    if 32 <= row < 32 + len(FISH_RARE_ITEMS):
        return FISH_RARE_ITEMS[row - 32]
    return None


_NOTES_CACHE: dict = {}


def schema_notes(stem: str) -> tuple[str, dict]:
    """(table notes, {field: note}) read from this module's own schema comments: the comment
    block that opens the table's entry, and the comment trailing a field tuple (plus the
    comment lines right under it). Used for the GUI's "About this table" and column help."""
    key = canonical_stem(stem)
    if key in _NOTES_CACHE:
        return _NOTES_CACHE[key]
    import pathlib as _pl
    try:
        lines = _pl.Path(__file__).read_text(encoding="utf-8").splitlines()
    except OSError:
        return "", {}
    start = next((k for k, ln in enumerate(lines) if re.match(r'\s{4}"%s": \{\s*$' % re.escape(key), ln)),
                 None)
    about, notes = [], {}
    if start is not None:
        # the comment block right above the key line (the family schemas keep theirs there) ...
        j = start - 1
        above = []
        while j >= 0 and lines[j].strip().startswith("#"):
            above.insert(0, lines[j].strip()[1:].strip())
            j -= 1
        # ... and every comment-only line of the entry before its field list
        k = start + 1
        while k < len(lines) and '"fields"' not in lines[k] and not lines[k].startswith("    }"):
            code, _, cmt = lines[k].partition("#")
            if cmt.strip() and (not code.strip() or code.strip().endswith(",")):
                about.append(cmt.strip())
            k += 1
        if not about:
            about = above
        k = start + 1
        depth = 1
        last = None
        while k < len(lines) and depth > 0:
            ln = lines[k]
            code, _, cmt = ln.partition("#")
            depth += code.count("{") - code.count("}")
            names = re.findall(r'\("([^"]+)",\s*\d+,\s*"\w+"\)', code)
            if names:
                last = names[-1] if len(names) == 1 else None
                if last and cmt.strip():
                    notes[last] = cmt.strip()
            elif last and not code.strip() and cmt.strip():
                notes[last] = (notes.get(last, "") + " " + cmt.strip()).strip()
            else:
                last = None
            k += 1
    sch = FIELD_SCHEMAS.get(key) or PREFIX_SCHEMAS.get(key) or {}
    for f, lim in (sch.get("limits") or {}).items():
        lo, hi, why = lim
        notes[f] = (notes.get(f, "") + f"  Range {lo}..{hi}: {why}.").strip()
    res = ("\n".join(about), notes)
    _NOTES_CACHE[key] = res
    return res


def flag_bits(stem: str, name: str):
    """{mask: name} of a bit-set field ({} when its bits have no names yet), or None when the
    field is not a bit set."""
    return FLAG_FIELDS.get(stem, {}).get(name)


def format_flags(raw: int, typ: str = "u32") -> str:
    """A bit-set value as hex, padded to the field width (0x00000081)."""
    width = {"u8": 2, "s8": 2, "u16": 4, "s16": 4}.get(typ, 8)
    return "0x%0*X" % (width, int(raw) & ((1 << (4 * width)) - 1))


def _flag_key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def apply_flag_edit(current: int, text: str, names=None, typ: str = "u32") -> int:
    """`+Fire,-Magic,+0x200,-bit3` -> current with those bits set / cleared (names are the
    field's bit names, case, spaces and _ ignored; `bitN` or a mask work for any bit).
    Anything not starting with + or - is a whole new value (0x.. allowed)."""
    t = str(text).strip()
    if not t or t[0] not in "+-":
        return parse_value(t, typ)
    by_name = {_flag_key(n): m for m, n in (names or {}).items()}
    v = int(current)
    for part in [p.strip() for p in t.split(",") if p.strip()]:
        sign, key = part[0], part[1:].strip()
        if sign not in "+-" or not key:
            raise NlclError(f"{part!r}: write +name or -name (e.g. +Fire, -0x80, +bit3)")
        k = _flag_key(key)
        if k in by_name:
            mask = by_name[k]
        elif re.fullmatch(r"bit\d+", k):
            mask = 1 << int(k[3:])
        else:
            try:
                mask = int(key, 0)
            except ValueError:
                known = ", ".join(sorted((names or {}).values())) or "none -- use bitN or a mask"
                raise NlclError(f"unknown flag {key!r} (known: {known})") from None
        v = (v | mask) if sign == "+" else (v & ~mask)
    lo, hi = type_range(typ)
    if typ.startswith("u"):
        v &= hi
    if not lo <= v <= hi:
        raise NlclError(f"{v:#x} does not fit {typ}")
    return v


def fixed_bits(stem: str, name: str):
    """Fraction bits of a fixed-point field (12 for Q12, 7 for Q7), or None."""
    return FIXED_FIELDS.get(stem, {}).get(name)


def format_value(raw: int, bits=None) -> str:
    """How a field value is shown: a percentage for a fixed-point field (the stored value
    over 2**bits: 4096 -> 100%, 6144 -> 150%, Q7 128 -> 100%), else the int. The percentage is
    the SHORTEST decimal that converts back to the same stored integer (4710 -> 115%, the value
    the designers typed, not 114.99%); two decimals always do for Q12, fewer for Q7."""
    if bits is None:
        return str(raw)
    one = 1 << bits
    for nd in range(0, 7):
        s = f"{raw * 100 / one:.{nd}f}"
        if round(float(s) * one / 100) == raw:
            break
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return (s if s not in ("-0", "") else "0") + "%"


def parse_value(text: str, typ: str = "s32", bits=None) -> int:
    """A typed field value -> the stored integer. For a fixed-point field '150%' (or the
    multiplier '1.5x' / '1.5×') is converted; anything else is a plain integer (0x.. allowed)
    stored as is. Checks the field's width and names the percentage range when it does not fit."""
    t = str(text).strip()
    if t.endswith("%") or t.endswith(MULT_SIGNS):
        if bits is None:
            raise NlclError(f"{t!r}: this field is not a percentage -- type a whole number")
        pct = t.endswith("%")
        try:
            v = float(t[:-1].strip())
        except ValueError:
            raise NlclError(f"{t!r} is not a number") from None
        raw = round((v / 100 if pct else v) * (1 << bits))
        lo, hi = type_range(typ)
        if not lo <= raw <= hi:
            raise NlclError(f"{t} does not fit a {typ} field: {lo * 100 / (1 << bits):g}% .. "
                            f"{hi * 100 / (1 << bits):g}%")
        return raw
    try:
        return int(t, 0)
    except ValueError:
        raise NlclError(f"{t!r} is not a whole number"
                        + (" (for a percentage add %, e.g. 150%)" if bits is not None else "")) from None


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
        if typ not in _FMT:
            raise NlclError(f"unknown field type {typ!r} (one of {', '.join(_FMT)})")
        code, sz = _FMT[typ]
        if off + sz > self.record_size:
            raise NlclError(f"{typ} at +{off} exceeds record size {self.record_size}")
        lo, hi = type_range(typ)
        value = int(value)
        if not (lo <= value <= hi):
            # struct would raise a bare struct.error; name the field width instead
            raise NlclError(f"value {value} does not fit {typ} ({lo}..{hi})")
        struct.pack_into(code, self.data, self._addr(rec, off), value)

    def record(self, rec: int) -> bytes:
        if not (0 <= rec < self.entry_count):   # a negative index would slice the header
            raise NlclError(f"record {rec} out of range (0..{self.entry_count-1})")
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
        """Write a named schema field. Besides the int-width check of set(), a schema may
        carry "limits" {field: (min, max, why)} for values the exe accepts in the file but
        misreads (e.g. an XP threshold the clamped XP counter can never reach)."""
        sch = self.schema(stem)
        if not sch:
            raise NlclError(f"no schema for {stem}; edit by offset instead")
        for fname, off, typ in sch["fields"]:
            if fname == name:
                lim = sch.get("limits", {}).get(name)
                if lim and not (lim[0] <= int(value) <= lim[1]):
                    raise NlclError(f"{stem}.{name} = {value} out of range "
                                    f"{lim[0]}..{lim[1]}: {lim[2]}")
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
