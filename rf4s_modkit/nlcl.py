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


def bit_range(typ: str):
    """(storage type, first bit, bit count) of a bit-range type "u8:0-3" (bits 0..3 of a u8:
    two values packed in one byte), else None."""
    if ":" not in typ:
        return None
    base, _, span = typ.partition(":")
    lo, _, hi = span.partition("-")
    try:
        lo, hi = int(lo), int(hi or lo)
    except ValueError:
        raise NlclError(f"bad bit range {typ!r} (e.g. u8:0-3)") from None
    if base not in _FMT or not base.startswith("u") or not 0 <= lo <= hi < 8 * _FMT[base][1]:
        raise NlclError(f"bad bit range {typ!r} (e.g. u8:0-3)")
    return base, lo, hi - lo + 1


def storage_type(typ: str) -> str:
    """The whole int a field is stored in ("u8" for "u8:4-7")."""
    br = bit_range(typ)
    return br[0] if br else typ


def type_range(typ: str) -> tuple[int, int]:
    """(min, max) value a field of int type `typ` can hold."""
    br = bit_range(typ)
    if br:
        return 0, (1 << br[2]) - 1
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
        # RE-CHECKED 2026-10-31 (TileObject_ApplyToolHit and its rolls):
        #   +0  only the low byte & 0x7F is read (Map_HandleSpecialTriggerEntity), so u8.
        #   +4 / +8 are read as s16 bases of ProbRoll_ExtraDrop_FavorsNoSkill(base, Mining level
        #     (skills+120), hammer tier (Item_GetWithinCategoryIndex_Cats27to32)): threshold =
        #     base with the first hammer, else base/2 - min(level,100)/2 - 16*tier (at least 1
        #     when base != 0); the roll passes when threshold >= a random byte 0..255, so the
        #     base is a chance out of 256. +4 passing zeroes the rock's remaining hits (it
        #     breaks); +8 passing turns the drop into Scrap Metal (818).
        #   +12/16/20 weights of Rng_WeightedPickIndex over the 3 items; on a special rock (set
        #     daily) the smallest weight is x4, capped at 255.
        #   +30 replaces the drop when ProbRoll_RareDrop_HighSkillAndLevel passes: Mining >= 50
        #     and hammer tier >= 3; chance/1024 = 30 (5 at tier 3), +10 at Mining 75, +20 at 90,
        #     +10 at 150, +15 at 300, +20 at 500 (Player_gainEXP lets Mining reach level 999).
        # The bonus drop (4*(min(level,100) + 8*tier) >= a random 0..1023) repeats the same item.
        # Shipped: the upper 16 bits of every dword are 0; rows 20-24 have no items.
        "fields": [
            ("Rock kind", 0, "u8"),           # the rock's gatherable kind (26..37): its sprite and name; only the low 7 bits count
            ("unused 1", 1, "u8"), ("unused 2", 2, "u16"),
            ("Break chance", 4, "s16"),       # chance per hit that the rock breaks, with the first hammer (256 = 100%); any better hammer halves it, and Mining lowers it further
            ("unused 6", 6, "u16"),
            ("Scrap chance", 8, "s16"),       # chance per drop that it is Scrap Metal instead, with the first hammer (256 = 100%); any better hammer halves it, and Mining lowers it further
            ("unused 10", 10, "u16"),
            ("Item 1 weight", 12, "u16"),     # how often Item 1 drops, relative to the other two weights
            ("unused 14", 14, "u16"),
            ("Item 2 weight", 16, "u16"),     # how often Item 2 drops, relative to the other two weights
            ("unused 18", 18, "u16"),
            ("Item 3 weight", 20, "u16"),     # how often Item 3 drops, relative to the other two weights
            ("unused 22", 22, "u16"),
            ("Item 1", 24, "u16"),
            ("Item 2", 26, "u16"),
            ("Item 3", 28, "u16"),
            ("Rare item", 30, "u16"),         # replaces the drop now and then once Mining is 50+: about 3% a drop with the Platinum Hammer (0.5% with the Golden, none below), rising to 6% at Mining 90, 7% at 150, 8% at 300 and 10% at 500
        ],
        "limits": {"Rock kind": (0, 127, "only the low 7 bits are read")},
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
            ("Client", 0, "u8"),            # the villager who posts the request (22 / 23 = Anonymous)
            ("Request kind", 1, "u8"),      # what kind of request it is: picks the objective and reward texts
            ("unused 2", 2, "u16"),
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
        "unused": "The game loads it but never reads its rows; the request texts are picked by "
                  "the quest's category alone.",
        "grow": "unused:the exe loads archive 16345 but never reads its records; the format "
                "strings are picked by the quest category byte whose meaning is hard-coded "
                "in Quest_LoadDetailStrings (+0x1ED1F0), so a 34th row/line is unreachable",
        "fields": [("Flag", 0, "u8"), ("unused 1", 1, "u8"), ("unused 2", 2, "u8"), ("unused 3", 3, "u8")],
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
        # Re-checked 2026-10-31: the only 4003 immediates are the face-icon resolver
        # (RF4S.exe+0x3C9C0, 4003 + char 1..23) and Player_TransformToCharacterById (+0x165EB0,
        # 4003 + char id), Game_PreloadAllArchives has no 4003 range, and the name appears only
        # in the UTF-16 archive path table.
        "unused": "The game never loads it (RF4S.exe has no code that opens it). It is probably "
                  "left over from the 3DS version: its rows look like where the sweat drops, anger "
                  "marks and notes sit around each portrait.",
        "grow": "unused:no code site loads archive 4003 (the 0xFA3 constants in the exe are "
                "the 4003+char_id face-icon base)",
        "fields": [("Spot 1 X", 0, "s8"), ("Spot 1 Y", 1, "s8"), ("Spot 2 X", 2, "s8"), ("Spot 2 Y", 3, "s8"),
                   ("Spot 3 X", 4, "s8"), ("Spot 3 Y", 5, "s8"), ("Spot 4 X", 6, "s8"), ("Spot 4 Y", 7, "s8")],
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
        "fields": [("XP to next level", 0, "s32")],
        "limits": {"XP to next level": (0, 0xFFFFFF, "Player_gainEXP clamps skill XP to 0xFFFFFF, "
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
        # LAYOUT 2026-10-31 (every byte; readers = the 248 functions that touch g_itemDatabase
        # plus the g_itemMetadataScratch copies, which only the +4 / +12 / +16 / +20 reads use):
        #   +5 two nibbles. Low = how many fit in one bag slot: InventorySlot_AreLeveledSameItem
        #     (> 1 = stackable), InventorySlot_MergeLeveledStacksSorted (free room = this - the
        #     slot's count; a slot keeps one level byte per item, 9 at most). High = the quality
        #     the item adds: Item_ApplyMaterialUpgrade (+0x3EC50) adds it (half below Forging 50)
        #     to forged gear, Crafting_CraftFromInputs sums it over the inputs, and
        #     Tile_ResolvePickupAndAwardItem_... puts it into a picked-up item's quality bits.
        #   +20 flag byte (+21..+23 always 0; Quest_OnNonGiftItemConsumed reads the dword, &2):
        #     0x1 Inventory_SpawnActionContextMenuFromSelectedSlot leaves out "Throw away";
        #     0x2 g_monsterTameRecentItemsRing tracking (Item_IsOwnedOrKnownAnywhere,
        #         ItemFx_PlayDeliveredToContainerById, Quest_OnNonGiftItemConsumed), never taken
        #         as bait (Fishing_StashBaitFromSlot), no NPC throw reaction -- Escape and the two
        #         Venti's Charms; 0x4 Fishing_SpawnFishActor sets the fish actor +29 bit 0x40 and
        #         the fishing state machine a catch flag (Stick, Vine, scales, Engagement Ring...);
        #     0x8 Item_SpawnVisualTask draws it as giant crop 8 * crop + 1107 (the giant crops);
        #     0x10 / 0x20 / 0x40 / 0x80 Item_ComputeStats: the level tier rows (1108 for 0x50,
        #         1113 for 0xA0) and quality tier rows (1118 / 1134 / 1126 / 1142) of
        #         rf3ItemStrengthening that a weapon / armour / staff / accessory gets.
        #   +24 read by nothing (a running index per kind, -1 for seeds, fish and spells).
        #   +28 Item_IsInRandomItemPool (+0x97410): > 9000 never; > 900 (> 960 in rune rolls)
        #     only once discovered; else offered once story progress reaches it.
        #     "Discovered" = g_saveBuffer_itemDiscoveredBitset, set by taking the item into the
        #     hands (Player_AttachHeldItem), buying it, crafting it, a reward popup, or showing a
        #     spell; ShippingBin_ProcessOvernight never sets it (checked 2026-10-31). Also read by
        #     ItemDrop_RollKillItemQualityTier / ItemDrop_RollItemLevelFromTierAndSkill and the
        #     Shop_Roll* / Script_VMOp_RollRandom* pickers.
        #   +32 Inventory_SortPage: the low 32 bits are the sort key within the item's page.
        #   +36 u16 Player_ApplyEquippedWeaponEffectIdsByItem -> stats +214 for the EQUIPPED
        #     weapon only: the effect level as_atk op 43 (operand -1) casts a staff's charged
        #     shot at (staffs 1..9). Fish / crops carry values here that nothing reads. +38 unread.
        "fields": [
            ("Family", 0, "u32"),        # the item whose family it belongs to (King Cabbage -> Cabbage): "any X" recipe inputs and random picks of a family use it
            ("Category", 4, "u8"),       # the item kind: 14 or less = usable (has an rf3UseItemParam row), 0..2 / 46 = crops
            ("Stack size", 5, "u8:0-3"),  # how many fit in one bag slot (1 = does not stack, 9 at most)
            ("Material quality", 5, "u8:4-7"),  # quality it adds when forged into gear (half below Forging 50) and when used in crafting
            ("Buy price curve", 6, "u8"),  # rf3PriceTable row for the shop price at each level
            ("Sell price curve", 7, "u8"),  # rf3PriceTable row for the selling / shipping value at each level
            ("Buy price", 8, "u32"),     # shop price (before the 10% / 20% sale discount)
            ("Sell price", 12, "u32"),   # selling / shipping value (Cabbage 680, Turnip 30)
            ("Crop", 16, "u32"),         # the rf3CropParam row a seed plants or a crop belongs to (Turnip Seed -> 72)
            ("Flags", 20, "u8"),         # what the game does with it: use the tick boxes
            ("unused 21", 21, "u8"), ("unused 22", 22, "u16"),
            ("unused 24", 24, "s32"),    # numbered per kind (-1 for seeds, fish, spells), but nothing reads it
            ("Story unlock", 28, "u32"),  # shops, drops and rewards offer it only once the story reaches this, or once you have had one (picked up, bought, crafted or got as a reward; shipping does not count); over 900 only that way, over 9000 never
            ("Sort order", 32, "u32"),   # its place when the bag is sorted
            ("Staff shot level", 36, "u16"),  # staffs: the level their charged shot is cast at (1-9); unused for anything else
            ("unused 38", 38, "u16"),
        ],
        "limits": {
            "Buy price curve": (0, 9, "Item_ComputeStackGoldValue returns 0 for a price row > 9"),
            "Sell price curve": (0, 9, "Item_ComputeStackGoldValue returns 0 for a price row > 9"),
            "Stack size": (0, 9, "a bag slot keeps one level byte per item, 9 at most"),
            "Staff shot level": (0, 9, "the damage formula caps the effect level at 9"),
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
        # column j = the stack's stored level j = in-game Lv j+1 (items store shown level - 1)
        "fields": [(f"Lv {j + 1}", j * 2, "u16") for j in range(10)],
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
        # element affinities (s32, Q12: POSITIVE = RESIST, +4096 = takes no damage of it; negative =
        # WEAK -- Combat_GetElementBonus +0x96140 returns -stat; corrected 2026-10-31, Ghost light
        # -4096, Dead Tree fire -4096)
        # + status-proc resists (low s16 of each dword, Q12: 4096 = 100% immune) IDA-verified vs
        # Actor_LoadBaseStatsFromTemplate (RF4S.exe+0xAF940): elements [0..7] copied to
        # stats+100..128 (note the swap: +176=neutral -> stats+128, +180=love -> stats+124);
        # resists [k] copied to stats+152+2k. RESIST ORDER CORRECTED 2026-09-24: status k =
        # poison, seal, paralysis, sleep, fatigue, cold, faint (+ drain) -- the order of the
        # proc mask bits (Combat_GetStatusProcMask +0x961B0 tests stats+152+2k for bit k), of
        # the cure bits Item_UseOnActor (+0xB4150) clears, and of the resist skills 26..32
        # (Player_ApplyAllSkillGrowthBonusesFromArchive14818 +0xB0E00). The old schema put
        # paralysis/sleep/seal at +188/+192/+196 (one slot off).
        # Live-cross-checked: boss[200] = ~100% status resist, fire -4096 (weak) / water +2048 (resists).
        # ADD ROW (2026-09-19): Char_GetTemplate (RF4S.exe+0x1C63B0) copies archive 14812 +
        # 28 + 308*char_id into g_charTemplateBuffer with NO bound check and never reads the
        # +24 count, so any char id the game can reference (Gen rosters, scripts, `monster
        # new`) reaches its row; give it name/description lines in rf3TxtNpc_split2_1/_2.
        "grow": "id-indexed:char id (Gen rosters / scripts); names in rf3TxtNpc_split2_1/_2",
        # COMPLETE LAYOUT 2026-10-31 (every byte of the 308; plain names). Readers: the 13
        # Char_GetTemplate callers (Actor_RecomputeAllStats +0xAD440 copies most fields into the
        # actor, Actor_LoadBaseStatsFromTemplate +0xAF940, Actor_ApplyLevelUp +0xB2CE0,
        # Actor_AdvanceLevelByDays, Familiar_BumpGrowthStatsFromKill +0xB2A00, the transform
        # actions) plus the functions that read archive 14812 directly at raw offsets (raw =
        # template + 28): Character_TickPose3DPreview / CompanionMenu (+28 + +306 height), the
        # face-icon resolver +0x3C9C0 (+252), Player_TransformToCharacterById (+0 / +32 / +272),
        # GameSystems_Init + Children_TickSpawnPendingChildNpcsIfAny (+8 / +12 / +32),
        # MonsterFarm_GetProduceItemIdLeveled +0x1E2720 / _TickDailyProduceDrop +0x1E2500
        # (+300 / +304 / +305), DailyVisitor_PickWantedItem +0x1EC590 (+294),
        # Quest_LoadDetailStrings + op 440 (+292), Town_BuildDailyGuestNpcRoster +0x23ACD0 (+34
        # for the guests 24..47). Nothing else reads g_charTemplateBuffer.
        #   +0 size (actor scale x/y/z), +4 body radius, +8 / +12 / +16 / +20 walk / run speed,
        #     acceleration and braking (x 6758 / 11264 / 1280+1536 / 2048+512+768 >> 12)
        #   +24 -> actor+176: the size of effects spawned on it (WorldObject_OnBreakDropLoot
        #     scales its burst by 1.5x this; attack-timeline op 59 overrides it)
        #   +28 height (head height = size * (+28 >> 2), hit radius +28 >> 1)
        #   +32 motion set: 1 = Lest's (default skeleton 14497 = rom:/mot/00/00_000_wait_normal,
        #     the 00_* set) instead of Frey's (14255 = 00W_000_wait_normal, the 00W_* set); both
        #     sets hold the same 242 motions. Also actor flag 0x8000000, which the game reads on
        #     the PLAYER as its gender (Player_IsMale, op 309: marriage candidates, voice, lines).
        #     Not the villagers' gender: Lin Fa / Amber / Dolce have 1, Barrett / Raven 0.
        #   +36 -> stats+224: Companion_AcquireTarget (+0x1E8F30) starts a freshly spawned
        #     monster in its lying-down (asleep) sequence when a random byte is below it
        #   +140 / +142 -> stats+52 / +80: the base hit arc (u16 angle, the FULL cone width:
        #     Collision_CircleVsCircleWithArcsRefined hits within +-arc/2 of the facing, 0 = a
        #     full circle; 16384 = 90 degrees) and hit reach the attack timeline ops 13 / 12 scale
        #     (AnimEvent_Op13_ScaleHitArc +0xAC280, AnimEvent_Op12_ScaleHitReach +0xAC0F0)
        #   +144 -> stats+172 bit 0x1000; set on the flying / floating monsters, but the only
        #     reader of that bit found is the player's XP x1.5 in Player_gainEXP
        #   +224 movement class (& 3: actor move param 24 * class + 584)
        #   +252 face icon: archive 17936 + this (monsters 48..253)
        #   +255 -> actor+220 |= 0x1C: floats over half-blocks and deep water while wild
        #   +256 model set: 48..253 = the monster model folder (12584 + model), else 933 + model
        #   +260 sight range (0 = unlimited), +264 field of view (u16 angle, full width:
        #     Monster_PickClosestVisibleTargetFromParty notices within +-fov/2 of the facing)
        #   +278 extra model (933 + this), +280 attack set (timeline archive 243 + this + N)
        #   +282..+287 ridden attacks: Actor_TickHeldByCarrier starts
        #     Actor_BeginAttackOrSkill(monster, +282/+284/+286, +283/+285/+287) on the rider's
        #     three attack buttons (input bits 0x800 / 0x100 / 0x400); throwing it uses +283
        #   +294 slay requests: DailyVisitor_PickWantedItem only picks this monster once
        #     g_storyProgressFlag9bit >= it (39 after the ending)
        #   +296..+299 when a companion defeats this monster it gains these bonus bytes
        #     (HP / STR / INT / VIT, each capped at 255, the four together at 512); the HP byte
        #     adds up to +50% max HP
        #   +228..+234 for villagers 0..26 the starting EQUIPMENT, not drops:
        #     Game_NewGame_InitWorldData (+0x88AA0) packs them into each villager's saved
        #     equipment (save +33815 + 63*id: slot 0 weapon, 1 shield, 4 headgear, 2 accessory
        #     for Drop 1..4; e.g. Forte Zweihaender + Iron Shield, Dolce's Silk Hat, Doug's
        #     Charm). The chances +236..+248 reach the actor only for ids 48..140 and 144+
        #     (Actor_RecomputeAllStats), so they mean nothing for anyone else.
        #   For monsters they ARE the drops (Actor_OnDefeatedCleanup +0xA8E00, one roll per slot
        #     with ActorDrop_RollItemDropFromSlot +0x966C0): drop when chance > baseline * rnd,
        #     baseline 1000, 920 on the Sharance Maze floors (maps 442..453), -250 on a lucky
        #     day, -70 with luck food, -100 with a luck item (ability 0x80000), -40 / -20 per
        #     companion with those. The item's quality comes from ItemDrop_RollKillItemQualityTier
        #     (equipment always level 0). Not rolled: the chests 141..143 (loot from the exe), and
        #     the story bosses 200 / 227-231 / 233 / 236 / 238 / 240 / 242 / 243 on their FIRST
        #     defeat outside the Maze; Ragnarok (238) drops item 910 only in the Maze.
        #   +300 produce item, +304 nonzero = the produce gets bigger at levels 50 / 100,
        #     +305 daily produce chance (passes when it >= a random byte)
        #   +306 extra height for the companion-menu figurine
        # No reader found: +6, +148 (set on hornets, chests and gates), +218, +222, +262,
        # +266..+271, +290, +302; +276 is copied and never read.
        "fields": [
            ("Size", 0, "s32"),                 # how big it is (100% = normal); scales the model and its collision
            ("Body radius", 4, "u16"),          # the radius of its body for collisions and AI distances
            ("unused 6", 6, "u16"),
            ("Walk speed", 8, "s32"),           # 100% = the normal walking speed
            ("Run speed", 12, "s32"),           # 100% = the normal running speed
            ("Acceleration", 16, "s32"),        # how fast it gets up to speed (100% = normal)
            ("Braking", 20, "s32"),             # how fast it slows down, also after a knockback (100% = normal)
            ("Effect size", 24, "s32"),         # the size of effects shown on it, e.g. the burst when it breaks (100% = normal)
            ("Height", 28, "s32"),              # how tall it is: sets its head height and how wide its hit area is
            ("Motion set", 32, "u16"),          # whose animations it moves with when Skeleton is -1: Lest's or Frey's. Not always its gender (Lin Fa, Amber and Dolce use Lest's, Barrett and Raven Frey's); on the player's body (rows 310 / 311) it is the player's gender for the whole game (marriage candidates, gendered lines, voice)
            ("AI script", 34, "u16"),           # monsters: the AI_m file it runs (AI_m<this>.bin); guests 24-47: how likely they visit town
            ("Spawn asleep chance", 36, "u32"),  # chance that it spawns lying asleep (256 = always)
            ("HP", 40, "u32"),
            ("STR", 44, "s32"),                 # adds to ATK
            ("INT", 48, "s32"),                 # adds to MAT
            ("VIT", 52, "s32"),                 # half of it adds to DEF and to MDF
            ("Kill XP", 56, "u32"),             # XP for defeating it
            ("ATK bonus", 60, "s32"),           # ATK = this + STR
            ("MAT bonus", 64, "s32"),           # MAT = this + INT
            ("Knockout build-up", 68, "s32"),   # each of its hits builds up a knockout on the target; past 100 the target collapses after its next knockback
            ("DEF bonus", 72, "s32"),           # DEF = this + half of VIT
            ("MDF bonus", 76, "s32"),           # MDF = this + half of VIT
            ("Level-up STR weight", 80, "s32"),  # when it levels up, how often the point goes to STR (against INT and VIT)
            ("Level-up INT weight", 84, "s32"),
            ("Level-up VIT weight", 88, "s32"),
            ("ATK growth", 92, "s32"),          # how much ATK it gains per level (100% = the standard curve)
            ("MAT growth", 96, "s32"),
            ("DEF growth", 100, "s32"),
            ("MDF growth", 104, "s32"),
            ("HP growth", 108, "s32"),
            ("Will resist", 112, "s32"),        # lowers the knockout build-up it takes (100% = none)
            ("Knockback", 116, "s32"),          # how far its hits knock targets back
            ("Stun", 120, "s32"),               # how long its hits stun targets
            ("Knockback resist", 124, "s32"),
            ("Stun taken", 128, "s32"),         # how long it stays stunned when hit (0% = no stun)
            ("Critical chance", 132, "s32"),
            ("Critical resist", 136, "s32"),
            ("Hit arc", 140, "u16"),            # how wide the cone of its body attacks is, in total (90° = 45° to each side of its facing); each attack scales it, 0 = all around
            ("Hit reach", 142, "u16"),          # how far its body attacks reach; each attack scales it
            ("Floating type", 144, "u32"),      # 1 on flying and floating monsters; no effect on them found (the same flag gives the player 1.5x XP)
            ("unused 148", 148, "u32"),         # 1 on the hornets, chests and gates; the game never reads it
            ("Fire resist", 152, "s32"),        # + = takes less fire damage (100% = none), - = weak to it
            ("Water resist", 156, "s32"),
            ("Earth resist", 160, "s32"),
            ("Wind resist", 164, "s32"),
            ("Light resist", 168, "s32"),
            ("Dark resist", 172, "s32"),
            ("Neutral resist", 176, "s32"),     # for hits with no element
            ("Love resist", 180, "s32"),
            ("Poison resist", 184, "s16"),      # 100% = immune
            ("unused 186", 186, "u16"),
            ("Seal resist", 188, "s16"),
            ("unused 190", 190, "u16"),
            ("Paralysis resist", 192, "s16"),
            ("unused 194", 194, "u16"),
            ("Sleep resist", 196, "s16"),
            ("unused 198", 198, "u16"),
            ("Fatigue resist", 200, "s16"),
            ("unused 202", 202, "u16"),
            ("Cold resist", 204, "s16"),
            ("unused 206", 206, "u16"),
            ("Faint resist", 208, "s16"),
            ("unused 210", 210, "u16"),
            ("Drain resist", 212, "s16"),
            ("unused 214", 214, "u16"),
            ("HP drain", 216, "s16"),           # share of the damage its hits heal it by
            ("unused 218", 218, "u16"),
            ("Tame chance", 220, "u16"),        # 0 = cannot be tamed; otherwise each fed item starts its roll at twice this out of 128 (bosses only need it nonzero: their favourite food decides)
            ("unused 222", 222, "u16"),
            ("Movement class", 224, "u32"),     # 0-3: which movement settings it uses
            ("Drop 1", 228, "u16"),             # monsters: an item it can drop when defeated; villagers 0-26: their starting WEAPON (put in their equipment when a new game starts)
            ("Drop 2", 230, "u16"),             # monsters: an item it can drop; villagers 0-26: their starting SHIELD
            ("Drop 3", 232, "u16"),             # monsters: an item it can drop; villagers 0-26: their starting HEADGEAR
            ("Drop 4", 234, "u16"),             # monsters: an item it can drop; villagers 0-26: their starting ACCESSORY
            ("Drop 1 chance", 236, "u32"),      # chance of Drop 1 when the monster is defeated (100% = always; a bit more likely in the Sharance Maze and with luck items); monsters 48-140 and 144+ only, unused for anyone else
            ("Drop 2 chance", 240, "u32"),
            ("Drop 3 chance", 244, "u32"),
            ("Drop 4 chance", 248, "u32"),
            ("Face icon", 252, "u16"),          # monsters: which face icon it shows
            ("Rideable", 254, "u8"),            # 1 = can be ridden once tamed
            ("Floats over water", 255, "u8"),   # 1 = crosses deep water and half-blocks while wild (not as a companion)
            ("Model set", 256, "u32"),          # 48-253 = takes its model from the monster models, else from the character models
            ("Sight range", 260, "u16"),        # how far it notices you (0 = no limit)
            ("unused 262", 262, "u16"),
            ("View angle", 264, "u16"),         # how wide the cone it notices you in is, in total (160° = 80° to each side of its facing); with Sight range 0 it sees all around whatever this says
            ("unused 266", 266, "u16"),
            ("unused 268", 268, "u16"),         # has values, but the game never reads them
            ("unused 270", 270, "u16"),
            ("Model", 272, "s16"),              # its model, counted within the model set (-1 = none)
            ("Skeleton", 274, "s16"),           # its skeleton (-1 = the default one)
            ("Transforms into", 276, "u16"),    # the form it turns into (0 = none), for information only: the game never reads it (the AI scripts do the transforms)
            ("Extra model", 278, "u16"),        # a second character model it loads
            ("Attack set", 280, "u16"),         # which set of attack moves it uses
            ("Ridden attack 1", 282, "u8"),     # the attack it does when its rider presses the first attack button
            ("Ridden attack 1 variant", 283, "u8"),  # also the attack used when it is thrown
            ("Ridden attack 2", 284, "u8"),     # the second attack button
            ("Ridden attack 2 variant", 285, "u8"),
            ("Ridden attack 3", 286, "u8"),     # the third attack button
            ("Ridden attack 3 variant", 287, "u8"),
            ("Level", 288, "u16"),              # its level when it spawns (monsters)
            ("unused 290", 290, "u16"),
            ("Home map", 292, "s16"),           # the map named in hunting requests ("Go to <map> ...")
            ("Slay request from", 294, "u16"),  # story progress from which it can be the target of slay requests
            ("Companion HP per kill", 296, "u8"),   # what a companion gains each time it defeats this monster
            ("Companion STR per kill", 297, "u8"),
            ("Companion INT per kill", 298, "u8"),
            ("Companion VIT per kill", 299, "u8"),
            ("Produce", 300, "u32"),            # the item it gives each day in a barn (0 = none)
            ("Produce grows", 304, "u8"),       # 1 = the produce becomes the bigger size at levels 50 and 100
            ("Produce chance", 305, "u8"),      # daily chance it gives its produce (255 = always)
            ("Figurine height", 306, "s16"),    # extra height for its figure in the companion menu
        ],
        "limits": {f"Drop {k}": (0, 0x7FF, "the game keeps 11 bits of a drop's item id")
                   for k in (1, 2, 3, 4)},
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
        # FIELD NAMES 2026-10-31: plain names ("Health" was grow_cap, "Drought penalty" water,
        # "Growth speed" / "Level gain" / "Size gain" / "Yield gain" gmul_size / gmul_1..3).
        #   +16 Health     CORRECTED 2026-07-21: this
        #                  is the crop's BASE [HP] -- copied straight into tile+8 (the live
        #                  [HP] the Magnifying Glass shows) at planting, and the wither-roll
        #                  reference (buckets current [HP] at cap>>1, cap>>2). Apple=140.
        #                  NOT a "size/quality ceiling".
        #   +40 Drought penalty  CORRECTED 2026-07-21: NOT water
        #                  consumption. Only fires when the crop's [HP] (tile+8) hits 0: then
        #                  it subtracts this from the crop's growth-quality byte (record+6)
        #                  each parched night (halved if watered that day). = the crop's
        #                  DROUGHT/dry-out growth penalty. Trees=0. (The [HP] drain itself
        #                  comes from a per-crop item-record field, not this.)
        #   +64/68/72/76   per-night RATE multipliers, applied as delta*val*32/4096 -> **128 =
        #                  1.0x** (64=0.5x, 256=2.0x); neutral crops = 128,128,128,128. RE-READ
        #                  2026-10-31 (Crop_TickGrowthForTile scales four separate gains):
        #                  +64 Growth speed -- the stage progress (tile+4 bits 0..16; the gain
        #                      Formula A/B/C raise, Crop_ApplyFertilizerToTile cases 806..808);
        #                  +68 Level gain -- the crop LEVEL (tile bits 10..21, diminished by
        #                      g_cropLevelGainDiminish; Greenifier / Greenifier+ raise it);
        #                  +72 Size gain -- the SIZE (tile bits 22..31; Giantizer raises,
        #                      Minimizer lowers it; at its maximum 511 four neighbours can merge
        #                      into a giant crop, Crop_TryMergeIntoGiantCropFrom4Adjacent);
        #                  +76 Yield gain -- how many you harvest (tile+4 bits 17..28,
        #                      g_cropNumberGainDiminish).
        #                  The old notes had +64 as the size rate.
        #   +104 Seasons   property + SEASON-AFFINITY flag word (u32). Season bits:
        #                  BOOST (in-season, +50% growth) 0x1000=spring 0x2000=summer
        #                  0x4000=fall 0x8000=winter ; PENALTY (off-season, -25%..-75%)
        #                  0x10000=spring 0x20000=summer 0x40000=fall 0x80000=winter.
        #                  A single-season crop sets its 1 boost bit + the other 3
        #                  penalty bits (e.g. summer crop=0x2000|0x10000|0x40000|0x80000);
        #                  an all-season crop sets none of 0x1000..0x80000. Low bits also
        #                  carry harvest-method (0x400=tool / 0x600=hand-pickup) + misc
        #                  crop-property flags -- edit season bits, keep the low bits.
        #   +12 Wild spawn weight  CORRECTED 2026-10-30 (was "growth", a u32): a u16 weight that
        #                  FarmFieldTask_Spawn (+0x1842B0) copies into the field's per-kind lists
        #                  (rows 0..25 debris / grass, 26..37 rocks, and crop rows with +104 bit 0x80
        #                  or 0x100) for Map_SpawnDailyRandomEntities' weighted picks (+0x186850):
        #                  how often that thing appears on its own (Branch 300, grasses 55 / 2 / 1).
        # LAYOUT 2026-10-31 (every byte), checked in RF4S.exe:
        #   +0..+3  the four stage lengths; TileTemplate_GetTotalGrowthDays sums all four
        #           (Apple 3+19+20+20 = 62). +3 is NOT the regrow time (the old name).
        #   +4..+11 MapEntity_GetSpriteScaleForGrowthStage: s8 seed / sprout / ripening / ripe,
        #           s16 giant (+8) and withered (+10) -- only the tree rows set them.
        #   +20     u8 body radius (Map_SpawnDailyRandomEntities, TileObject_ApplyToolHit).
        #   +24     Tile_ResolvePickupAndAwardItem_FishingAndGeneric (+0x1893D0): after a harvest,
        #           if +24 != 0, the crop has health and the soil has quality, the crop goes back
        #           to stage 4 with maturity = (total days - this) << 8 = ripe again in +24 days.
        #   +28     the yield: the same function's count base (0 = 1) and the tooltip
        #           (TileObjectCursor_RefreshTooltip adds the soil's yield bits, clamps 1..9).
        #           IDB note: TileTemplate_GetRegrowIntervalDays reads +28 and
        #           TileTemplate_GetYieldPerHarvest reads +96 (the harvest item) -- misnamed.
        #   +32     Weather_TickFieldEffects_RainWaterStormDebris: a storm picks a field tile;
        #           protection = soil +4 bits 10..15 + this, clamped 0..63; a draw of 0..76
        #           above protection / 63 * 100 hits the crop (TileObject_ApplyToolHit kind 10).
        #   +36     Crop_BumpStatsAndRollHarvestDropAndNpcEvent: an event fires when a byte draw
        #           < soil counter + 8 * this + 1 (villager visit 2009..2012 / friendship 2050).
        #   +40     Crop_DecayAccumulatedStatsAfterHarvest takes it off the soil quality (soil
        #           record +6) per harvest; the growth tick takes it on a night at 0 health.
        #   +44 / +48 / +52 / +56 / +60  the bump: soil level / growth / crop level (ql) / size
        #           / yield (no) counters (record +10 / +11 / +13 / +14 / +12), each step scaled
        #           by the tier table at RF4S.exe+0x4D3B50; a full counter raises the tier.
        #   +80 / +84 / +88 / +92  the decay: rate_growth -= (16*32*v) >> 12 (clamp 128..1280),
        #           rate_ql / rate_sz / rate_no -= (8*32*v) >> 12 (docs: farm-crop system §6).
        #   +14, +21..+23, +42 are read by nothing.
        # To reseason a crop: clear its old 0x1000..0x80000 bits, set the new boost bit
        # (+ the 3 off-season penalty bits if you want a single-season crop).
        # ADD ROW (2026-09-19): rows are addressed by the SEED ITEM's crop-link id -- the
        # u32 at rf3ItemList record +16 (ItemMetadata_t.data_10): Script_VMOp_QueryCropPlantable
        # AndTileInfo (RF4S.exe+0x2113D0) reads `g_currentMapTiles+32` (= archive 14807 + 28,
        # stored by FarmFieldTask_Spawn +0x1842B0 without reading the count) + 108*link. So a
        # 94th crop is reachable once a seed item links to it (`param set rf3ItemList.bin
        # <seed> Crop=93`). Caveat: FarmFieldTask_Spawn also copies FIXED row ranges
        # (0..25, 26..37, 38..87 by kind flag) into per-kind lists at spawn, so a new row is
        # outside those lists. AND (2026-10-30) Crop_TickGrowthForTile (+0x185240) only ticks tile
        # kinds 38..87 (the tile kind = the crop row, 7 bits): a planted row outside 38..87 never
        # grows, so a new crop has to reuse one of rows 38..87.
        "grow": "fixed:88",
        "names": "item", "name_field": "Harvest item",
        "fields": [
            ("Stage 1 days", 0, "u8"),        # days in the first growth stage (the four stages add up to the growth time)
            ("Stage 2 days", 1, "u8"),        # days in the second stage
            ("Stage 3 days", 2, "u8"),        # days in the third stage
            ("Stage 4 days", 3, "u8"),        # days in the fourth stage, then it is ripe
            ("Seed sprite size", 4, "s8"),    # sprite size change in the seed stage (trees only; 0 = normal)
            ("Sprout sprite size", 5, "s8"),  # ... in the sprout stage
            ("Ripening sprite size", 6, "s8"),  # ... while ripening
            ("Ripe sprite size", 7, "s8"),    # ... when ripe
            ("Giant sprite size", 8, "s16"),  # ... when ripe and giant
            ("Withered sprite size", 10, "s16"),  # ... when withered
            ("Wild spawn weight", 12, "u16"),  # how often it appears on its own on fields (debris, grass, wild crops)
            ("unused 14", 14, "u16"),
            ("Health", 16, "u32"),            # the crop's starting health (the Magnifying Glass HP); low health risks withering
            ("Body radius", 20, "u8"),        # how much room it takes (collisions); giant / small tiers scale it
            ("unused 21", 21, "u8"), ("unused 22", 22, "u16"),
            ("Regrow days", 24, "u32"),       # after a harvest it is ripe again this many days later; 0 = harvested once
            ("Yield", 28, "u32"),             # how many you harvest (0 = 1; the soil adds more, 9 at most)
            ("Storm resistance", 32, "u32"),  # chance a storm leaves it alone, out of 63 (the soil adds to it)
            ("Harvest event chance", 36, "u32"),  # how likely a harvest brings a villager visit or a friendship event
            ("Soil quality cost", 40, "u16"),  # soil quality used up by each harvest, and each night it is parched (half if watered)
            ("unused 42", 42, "u16"),
            ("Soil level up", 44, "u32"),     # each harvest raises the soil's level by this much (its counter fills to 255, then the level goes up)
            ("Soil growth up", 48, "u32"),    # each harvest raises the soil's growth speed tier by this much
            ("Soil crop level up", 52, "u32"),  # each harvest raises the soil's crop level tier by this much
            ("Soil size up", 56, "u32"),      # each harvest raises the soil's crop size tier by this much
            ("Soil yield up", 60, "u32"),     # each harvest raises the soil's yield tier by this much
            ("Growth speed", 64, "u32"),      # how fast it moves through its stages (100% = normal; Formula fertilizers raise the same gain)
            ("Level gain", 68, "u32"),        # how fast its level rises (Greenifier raises the same gain)
            ("Size gain", 72, "u32"),         # how fast it grows toward giant size (Giantizer raises it, Minimizer lowers it)
            ("Yield gain", 76, "u32"),        # how fast the number you harvest rises
            ("Soil growth drain", 80, "u32"),  # each harvest lowers the soil's growth speed by this / 8
            ("Soil crop level drain", 84, "u32"),  # each harvest lowers the soil's crop level rate by this / 16
            ("Soil size drain", 88, "u32"),   # each harvest lowers the soil's crop size rate by this / 16
            ("Soil yield drain", 92, "u32"),  # each harvest lowers the soil's yield rate by this / 16
            ("Harvest item", 96, "u32"),      # the item you get when you harvest it
            ("Seed item", 100, "u32"),        # the seed that plants it
            ("Seasons", 104, "u32"),          # which seasons it grows in (and how it is harvested): use the tick boxes
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
        #   +176 level_scale   per-level bonus: Item_ComputeEffectiveStats (+0x422C0) scales the
        #                      heal / buff fields by (item level * (level_scale >> 3) + 4096) / 4096,
        #                      i.e. level_scale / 32768 per item level (4096 = +12.5% a level,
        #                      0 = the level changes nothing); shown as that per-level percentage
        # ADD ROW (2026-09-19): ptr_68 = archive 14848 + 28 (ItemDatabase_AllocateAndInit
        # +0x3FBE0, count never read); Item_ComputeEffectiveStats (+0x422C0) reads
        # `ptr_68 + 180*item_id` only for items whose rf3ItemList category byte (+4) is
        # <= 14 -- in the shipped data exactly ids 0..317, which is why the file has 318
        # rows. A new consumable therefore needs an item id in that block (or a category
        # <= 14 on a higher id, which then reads past this table unless it is grown to it).
        "grow": "id-indexed:item id, gated by rf3ItemList category <= 14 (ids 0..317)",
        "fields": [
            ("HP healed", 0, "s32"),          # HP it heals (negative = damage, e.g. failed dishes)
            ("RP healed", 4, "s32"),          # RP it restores
            ("HP healed (share of max)", 8, "s32"),
            ("RP healed (share of max)", 12, "s32"),
            ("Effects", 16, "u32"),           # cures / inflicts statuses, levels up: use the tick boxes
            ("Fed time (x 3 min)", 20, "s32"),  # how long the fed buffs below last, in 3-minute steps (0 = none)
            ("Fed: max HP", 24, "s32"), ("Fed: max RP", 28, "s32"), ("Fed: STR", 32, "s32"),
            ("Fed: INT", 36, "s32"), ("Fed: VIT", 40, "s32"),
            ("Fed: max HP %", 44, "s32"), ("Fed: max RP %", 48, "s32"),
            ("Fed: STR %", 52, "s32"), ("Fed: INT %", 56, "s32"), ("Fed: VIT %", 60, "s32"),
            # +64/+68/+72: Actor_RecomputeStats (+0xB0180) adds them to stats+72 crit chance,
            # stats+64 knockback resist, stats+76 crit resist while fed (Q12)
            ("Fed: critical chance", 64, "s32"), ("Fed: knockback resist", 68, "s32"),
            ("Fed: critical resist", 72, "s32"),
        ] + [(f"Fed: {s} resist", 76 + 4 * k, "s32") for k, s in enumerate(
            ("poison", "seal", "paralysis", "sleep", "fatigue", "cold", "faint"))
        ] + [(f"Fed: {s} chance", 104 + 4 * k, "s32") for k, s in enumerate(
            ("poison", "seal", "paralysis", "sleep", "fatigue", "cold", "faint"))
        ] + [(f"Fed: {s} resist", 132 + 4 * k, "s32") for k, s in enumerate(
            ("fire", "water", "earth", "wind", "light", "dark", "love"))
        ] + [
            ("Max HP up", 160, "s32"),        # raises max HP for good (stat-up items)
            ("STR up", 164, "s32"), ("INT up", 168, "s32"), ("VIT up", 172, "s32"),
            ("Per-level bonus", 176, "s32"),  # how much stronger each item level makes it (heals and buffs)
        ],
    },
    "rf3ItemEquipmentParam": {
        # 1106 x 180; record index = item id. The base stat record Item_ComputeStats
        # (RF4S.exe+0x43E60) starts from; the labels are PROVEN by where
        # Equip_AccumulateItemStats (+0xB11A0) merges each dword: +12 -> ATK total, +16 -> MAT
        # total, +20 -> DEF, +24 -> MDF, +28 -> STR, +32 -> INT, +36 -> VIT, +40 -> the
        # knockout build-up (clamp 0..500), not HP. CORRECTED 2026-09-16: the older entry had
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
        # KNOCKOUT BUILD-UP (re-read 2026-10-31; the old notes called it hunger): every hit
        # carries it to AttackInfo+334; Combat_GetStatusProcMask (+0x961B0) adds it, less the
        # target's will resist (stats+48, Q12), to the target's counter (stats+168); past 100 the
        # target gets status 0x100, and when its hurt / knockdown ends it collapses
        # (Actor_BeginFallIntoPitDeath: the 4-second fall-and-vanish defeat; the player is knocked
        # out). The counter drains 1 every 32 frames while the target is not busy
        # (Actor_PreTickFrameCleanupAndDecay) and is cleared when a hit lands on a target lying in
        # its knockout pose (Combat_ResolveHit).
        # FULL LAYOUT 2026-10-30 (Item_ComputeStats +0x43E60 loads every field below and adds the
        # forged materials' rf3ItemStrengthening dwords; Equip_AccumulateItemStats +0xB11A0 merges
        # them into the wearer's stats, with the clamps noted): +40 knockout build-up per hit
        # (stats+44 -> AttackInfo+334, 0..500), +44 crit chance (stats+72, 0..4096), +48 knockback
        # dealt (stats+56: a weapon hit pushes 6x it), +52 hit-stun dealt (stats+60: +30x it frames),
        # +56..+80 on-hit status chances poison..faint and +84 HP drain (Attack_PopulateAttackInfo
        # FromWeaponAndStatus -> AttackInfo+340..+354), +88..+116 element affinities fire, water,
        # earth, wind, light, dark, love, neutral (-16384..8192; POSITIVE = RESIST: Combat_GetElement
        # Bonus +0x96140 returns -stat, Fire Ring +4096 fire / -2048 water), +120 will resist,
        # +124 crit resist (stats+76), +128 knockback resist (stats+64), +132..+156 status resists
        # poison..faint, +160 HP-drain resist, +164 farm-tool charge scale, +168 hit reach scale,
        # +172 hit arc scale, +176 the held model's archive offset. All Q12 except +40 and +176.
        # FIELD NAMES 2026-10-31: plain names, and +0 shown ("Ability flags": every worn item's
        # bits are ORed into the wearer's stats+188 (all slots) / +196 (armour slots) by
        # Actor_RecomputeStats; a weapon's are also its attack flags:
        # Attack_PopulateAttackInfoFromWeaponAndStatus copies the item's +0 into AttackInfo+320,
        # the bits rf3ParamMagic's flags use; Equip_AccumulateItemStats tests +0 bit 0x20000000).
        # +4 Boots effects = Player_GetBootsEffectWord (+0x16D170), +8 Accessory effects =
        # Player_CheckStatusFlag (+0xB24C0): each bit is set by exactly one shipped item, named
        # after it below (the effect wording is that item's in-game description).
        "fields": [
            ("Ability flags", 0, "u32"),      # special abilities: a weapon's go into its hits (element, hammer hit, ...), every worn item's count for the wearer (e.g. Dolphin Brooch): tick boxes
            ("Boots effects", 4, "u32"),      # the special effect of boots (walk on water, sneak, ...): tick boxes
            ("Accessory effects", 8, "u32"),  # the special effect of an accessory (Happy Ring, Talisman, ...): tick boxes
            ("ATK", 12, "s32"),               # attack added
            ("MAT", 16, "s32"),               # magic attack added
            ("DEF", 20, "s32"),               # defense added
            ("MDF", 24, "s32"),               # magic defense added
            ("STR", 28, "s32"),               # strength added
            ("INT", 32, "s32"),               # intelligence added
            ("VIT", 36, "s32"),               # vitality added
            ("Knockout build-up", 40, "s32"),  # each hit builds up a knockout (less the target's will resist); past 100 the target collapses after its next knockback; drains about 2 a second
            ("Critical chance", 44, "s32"),   # chance of a critical hit (100% = always)
            ("Knockback", 48, "s32"),         # how far your hits push (a weapon hit pushes 6x this)
            ("Stun", 52, "s32"),              # how long your hits make the target flinch
            ("Poison chance", 56, "s32"),     # chance a hit poisons
            ("Seal chance", 60, "s32"),       # chance a hit seals
            ("Paralysis chance", 64, "s32"),  # chance a hit paralyses
            ("Sleep chance", 68, "s32"),      # chance a hit puts to sleep
            ("Fatigue chance", 72, "s32"),    # chance a hit tires
            ("Cold chance", 76, "s32"),       # chance a hit gives a cold
            ("Faint chance", 80, "s32"),      # chance a hit knocks out
            ("HP drain", 84, "s32"),          # share of the damage you heal on a hit
            ("Fire resist", 88, "s32"),       # fire damage taken: 100% = none, negative = weak (takes more)
            ("Water resist", 92, "s32"),      # water damage taken: 100% = none, negative = weak
            ("Earth resist", 96, "s32"),      # earth damage taken: 100% = none, negative = weak
            ("Wind resist", 100, "s32"),      # wind damage taken: 100% = none, negative = weak
            ("Light resist", 104, "s32"),     # light damage taken: 100% = none, negative = weak
            ("Dark resist", 108, "s32"),      # dark damage taken: 100% = none, negative = weak
            ("Love resist", 112, "s32"),      # love damage taken: 100% = none, negative = weak
            ("Neutral resist", 116, "s32"),   # non-elemental damage taken: 100% = none, negative = weak
            ("Will resist", 120, "s32"),      # lowers the knockout build-up the wearer takes from hits (100% = none)
            ("Critical resist", 124, "s32"),  # lowers the attacker's critical chance (100% = never)
            ("Knockback resist", 128, "s32"),  # lowers how far hits push you (100% = not at all)
            ("Poison resist", 132, "s32"),    # 100% = immune to poison
            ("Seal resist", 136, "s32"),      # 100% = immune to seal
            ("Paralysis resist", 140, "s32"),  # 100% = immune to paralysis
            ("Sleep resist", 144, "s32"),     # 100% = immune to sleep
            ("Fatigue resist", 148, "s32"),   # 100% = immune to fatigue
            ("Cold resist", 152, "s32"),      # 100% = immune to colds
            ("Faint resist", 156, "s32"),     # 100% = immune to fainting
            ("HP drain resist", 160, "s32"),  # protects against hits that drain your HP
            ("Tool charge", 164, "s32"),      # how much a farm tool's charged use covers
            ("Reach", 168, "s32"),            # how far the weapon reaches (100% = normal)
            ("Swing arc", 172, "s32"),        # how wide the swing is (100% = normal)
            ("Held model", 176, "s32"),       # which model shows in the hand (an offset into the model archives)
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
            ("XP to next level", 0, "u32"),  # XP needed at this level to reach the next one
            ("Max HP", 4, "u32"),            # base max HP at this level
            ("Max RP", 8, "u32"),            # base max RP at this level
            ("STR", 12, "u32"), ("INT", 16, "u32"), ("VIT", 20, "u32"),  # base stats at this level
        ],
        "limits": {"Max RP": (0, 0xFFFF, "the base RP is a u16 (Actor_ApplyLevelUp clamps the "
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
        # Re-checked 2026-10-31: the ids 14814..14816 appear only in those two functions, the
        # pointer Actor_AdvanceLevelByDays gets back is never read, and every 14813 fetch is a
        # literal id (no 14813 + n).
        "unused": "The game loads it and never reads it. NPC and monster growth comes from "
                  "rf3Parameter.bin and the level table inside RF4S.exe.",
        "grow": "unused:the exe never reads these records",
        "fields": [
            ("Value 1", 0, "u32"), ("Value 2", 4, "u32"), ("Value 3", 8, "u32"), ("Value 4", 12, "u32"),
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
            ("Picture", 0, "s32"),          # which minimap picture it uses (73 or over 87 = none)
            ("Origin X", 4, "s32"), ("Origin Y", 8, "s32"),  # where the map's world origin sits on the picture (pixels)
            ("Fog X", 12, "s32"), ("Fog Y", 16, "s32"),      # the part of the picture uncovered once you visit it
            ("Fog width", 20, "s32"), ("Fog height", 24, "s32"),  # 0 = no fog (towns, interiors)
            ("Scale X", 28, "s32"), ("Scale Y", 32, "s32"),  # picture pixels per world unit (4096 = 1)
            ("Icon slot", 36, "s32"),       # interiors: which icon slot of the parent picture shows its NPCs
            ("Parent picture", 40, "s32"),  # interiors: the picture their NPC icons go on (73 = none)
            ("Icon X", 44, "s32"), ("Icon Y", 48, "s32"),    # interiors: where on the parent picture
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
        # S[1..8] core stats (S[8] = knockout build-up per hit), S[10..12] crit / knockback / stun,
        # S[23..24] crit / knockback resist (2026-10-30, see rf3ItemEquipmentParam), S[14..21] on-hit procs + HP drain, S[22..33]
        # resists + reach, S[34..37] heals, S[40..52] fed buff, S[53..66] fed resists/procs,
        # S[67..73] element affinities. S[9], S[13], S[39] are unread; S[61..66] are summed
        # into the dish record but zero in the shipped file.
        "names": "item",
        "fields": [(n, 4 * k, "s32") for k, n in enumerate([
            "Difficulty", "ATK", "MAT", "DEF", "MDF", "STR", "INT", "VIT", "Knockout build-up",
            "unused 9", "Critical chance", "Knockback", "Stun", "unused 13",
            "Poison chance", "Seal chance", "Paralysis chance", "Sleep chance", "Fatigue chance",
            "Cold chance", "Faint chance", "HP drain", "Will resist", "Critical resist", "Knockback resist",
            "Poison resist", "Seal resist", "Paralysis resist", "Sleep resist", "Fatigue resist", "Cold resist",
            "Faint resist", "Drain resist", "Reach", "HP healed", "RP healed", "HP healed (share of max)",
            "RP healed (share of max)", "Effects", "unused 39", "Fed: max HP", "Fed: max RP", "Fed: STR",
            "Fed: INT", "Fed: VIT", "Fed: max HP %", "Fed: max RP %", "Fed: STR %",
            "Fed: INT %", "Fed: VIT %", "Fed: critical chance", "Fed: knockback resist", "Fed: critical resist",
            "Fed: poison resist", "Fed: seal resist", "Fed: paralysis resist", "Fed: sleep resist",
            "Fed: fatigue resist", "Fed: cold resist", "Fed: faint resist", "Fed: poison chance",
            "Fed: seal chance", "Fed: paralysis chance", "Fed: sleep chance", "Fed: fatigue chance",
            "Fed: cold chance", "Fed: faint chance", "Fire resist", "Water resist", "Earth resist", "Wind resist",
            "Light resist", "Dark resist", "Love resist"])],
    },
    "rf3ParamMagic": {
        # 446 x 148-byte ACTION/SKILL/MAGIC param table = archive 14817 (shared by weapon
        # arts, spells, monster attacks; indexed by action_id 0..445). IDA-verified vs
        # Actor_ComputeDamageWithAtkScalarsAndElementBonus (RF4S.exe+0x96B40),
        # Combat_CopyAttackEntryAndScaleDamageToItemRecord (+0x97250), Actor_BeginSkillEffectAnim
        # (+0x161970):
        #   dmg = Base damage + ATK scaling x ATK + MAT scaling x MAT, then x Damage multiplier,
        #   + the level bonus, then the element bonus. Flags = element / behaviour bits.
        # (Corrects the old Combat_GetAttackParamTableBase note: +28 is FLAGS, base dmg is +32.)
        # Data-checked: action0 = Fire magic (flags 0x81, base15, mat 1.0x); action445 =
        # physical (atk 1.5x, mult 5x).
        # LAYOUT 2026-10-31 (every byte; readers = the 7 functions that load archive 14817 or
        # call Combat_GetAttackParamTableBase, plus MagicProjectile_SpawnTaskWithKindAngleAnd
        # Velocity reading row 113 by constant; none of them hands a record pointer on):
        #   +0..+27, +72..+95 are read by nothing (+92 holds 255 / 0 / 96 / 50 in the shipped
        #   rows, a leftover), nor are the upper halves of the u16 status words.
        #   +64 -> AttackInfo+316 = this * -1536 >> 12 for spell / effect hits only
        #     (Combat_FillAttackInfoFromEffectKind); weapon and thrown hits always use -1536
        #     (Combat_CopyAttackEntryAndScaleDamageToItemRecord) -- the gravity that pulls a
        #     launched target back down (shipped 50% almost everywhere).
        #   +68 -> AttackInfo+182 hit_reach = this * 30 >> 12 (Combat_FillAttackInfoFromEffectKind,
        #     MagicProjectile_Spawn... for row 113): the radius of the spell's hit circle
        #     (Collision_CircleVsCircleWithArcsRefined); several spell ticks grow it as they fly.
        #   +52 -> AttackInfo+308 = this * 24576 >> 12 (Combat_ResolveHit scales it by the
        #     target's 4096 - knockback resist); +56 -> AttackInfo+332 = this * 30 >> 12 frames
        #     (scaled by the target's stats +68 into actor +576); +60 -> AttackInfo+312 =
        #     this * -10240 >> 12, the upward speed; the u16 status words -> AttackInfo +334 and
        #     +340..+354 (both copy functions read only the low half).
        #   +132 / +136 / +140: Effect_ApplyByKindAndSpawn (+0xECEC0) charges the cost and gives
        #     the XP on cast; Combat_ResolveHit gives the XP on a hit only when both costs are 0.
        #   +144 Skill: Combat_ResolveHit reads it as u16, Effect_ApplyByKindAndSpawn as u32 (an
        #     index into rf3ParamSkill), so the whole dword must stay a skill id 0..39.
        #   Base damage / Level bonus (Actor_ComputeDamageWithAtkScalarsAndElementBonus): at
        #     effect level L = 1..9 (g_currentEffectLevel, capped at 9) the base part is
        #     L * Base damage / 2 + Level bonus * g_effectLevelDamageTable[L] >> 12; at L = 0 it
        #     is Base damage. A caster without stats (a trap, an object) does Base damage + 32.
        "fields": [
            ("unused 0", 0, "u32"), ("unused 4", 4, "u32"), ("unused 8", 8, "u32"),
            ("unused 12", 12, "u32"), ("unused 16", 16, "u32"), ("unused 20", 20, "u32"),
            ("unused 24", 24, "u32"),
            ("Flags", 28, "u32"),           # element + behaviour bits: use the tick boxes
            ("Base damage", 32, "s32"),     # damage before ATK / MAT (a caster without stats, e.g. a trap, does this + 32)
            ("ATK scaling", 36, "s32"),     # share of the attacker's ATK added (100% = all of it)
            ("MAT scaling", 40, "s32"),     # share of the attacker's MAT added (100% = all of it)
            ("Damage multiplier", 44, "s32"),  # the whole hit's damage (100% = unchanged)
            ("Level bonus", 48, "s32"),     # cast at a higher level L (1-9): base damage becomes L x Base damage / 2 + this x the game's per-level bonus
            ("Knockback", 52, "s32"),       # how far it pushes (100% = a plain weapon hit); lowered by the target's knockback resist
            ("Stun", 56, "s32"),            # how long the target flinches (100% = 30 frames, a plain weapon hit; 0 = no flinch)
            ("Launch", 60, "s32"),          # how high it throws the target up (0 = stays on the ground)
            ("Launch gravity", 64, "s32"),  # spells only: how fast a launched target falls back (100% = normal gravity; weapon hits always 100%)
            ("Hit size", 68, "s32"),        # spells only: radius of the hit circle (100% = 30, the scale of Body radius in rf3NpcParam)
            ("unused 72", 72, "u32"), ("unused 76", 76, "u32"), ("unused 80", 80, "u32"),
            ("unused 84", 84, "u32"), ("unused 88", 88, "u32"),
            ("unused 92", 92, "u32"),       # holds 255 / 0 / 96 ... in the shipped rows, but nothing reads it
            ("Knockout build-up", 96, "u16"),  # knockout build-up per hit (shipped 0..25), see rf3ItemEquipmentParam
            ("unused 98", 98, "u16"),
            ("Poison chance", 100, "u16"), ("unused 102", 102, "u16"),
            ("Seal chance", 104, "u16"), ("unused 106", 106, "u16"),
            ("Paralysis chance", 108, "u16"), ("unused 110", 110, "u16"),
            ("Sleep chance", 112, "u16"), ("unused 114", 114, "u16"),
            ("Fatigue chance", 116, "u16"), ("unused 118", 118, "u16"),
            ("Cold chance", 120, "u16"), ("unused 122", 122, "u16"),
            ("Faint chance", 124, "u16"), ("unused 126", 126, "u16"),
            ("HP drain", 128, "u16"),       # share of the damage the attacker heals
            ("unused 130", 130, "u16"),
            ("Skill XP", 132, "u32"),       # XP for `Skill` when cast (and on a hit, only for a move that costs no RP)
            ("RP cost", 136, "u32"),        # flat RP cost (action 87 doubles it below skill level 50 with the wrong weapon)
            ("RP cost (share of max RP)", 140, "s32"),  # a share of the caster's max RP; non-zero replaces RP cost
            ("Skill", 144, "u32"),          # the skill that gets the XP (and whose "RP cost cut per level" in rf3ParamSkill lowers the cost)
        ],
        "limits": {"Skill": (0, 39, "indexes the 40-row rf3ParamSkill table")},
    },
    "rf3ParamSkillData": {
        # 176 x 32-byte per-ACTION table = archive 14819, row = action id (an attack, a spell, a
        # tool use, eating, sleeping, ...). RE-CHECKED 2026-10-31: the archive id appears in
        # exactly three functions besides the preload -- Combat_ApplyAttackEntry (+0xB1F95: RP
        # cost + XP), Player_ChargeSkillCastCostByActionIdFromArchive14819 (+0xB2190: RP cost
        # only) and Player_AwardXpFromAttackEntry (+0xB2357: XP only). (The decompiler folds the
        # 28-byte header into the offsets: record base = data + 28 + 32*id.)
        #   RP cost = +4, or when +0 != 0, max(+4 as a dword, (16 * +0 * max RP) >> 12) -- so +0
        #     is a share of the caster's max RP out of 256 (stats+12) --, then
        #     * (4096 - min(L,100) * rf3ParamSkill[+12] +36) >> 12 with L = the +12 skill's level,
        #     truncated to u16, and doubled for the weapon special moves 108..144 when neither
        #     the matching weapon type is held nor that weapon skill is at level 50+
        #     (108-115 Short Sword, 116-122 Long Sword, 123-126 Spear, 127-132 Axe / Hammer,
        #     133-144 Dual Blades). Charged by Combat_ApplyDamage_RpThenHp (HP once RP is out).
        #   XP: Player_gainEXP(actor, amount, skill) three times: (+8, +12), (+16, +20 as u16),
        #     (+24, +28 as u16). An amount of 0 gives nothing.
        "fields": [
            ("RP cost (share of max RP)", 0, "u32"),  # when set, the RP cost is this share of the max RP instead, if that is more than the flat cost
            ("RP cost", 4, "u32"),            # flat RP cost (one reader takes 2 bytes, the other all 4, so 65535 at most)
            ("Skill 1 XP", 8, "s32"),         # XP given to skill 1 each time the action is used
            ("Skill 1", 12, "s32"),           # the action's skill: gets the XP above, and its "RP cost cut per level" lowers the cost
            ("Skill 2 XP", 16, "s32"),        # XP given to skill 2 each time the action is used
            ("Skill 2", 20, "u16"), ("unused 22", 22, "u16"),
            ("Skill 3 XP", 24, "s32"),        # XP given to skill 3 each time the action is used
            ("Skill 3", 28, "u16"), ("unused 30", 30, "u16"),
        ],
        "limits": {**{f: (0, 39, "indexes the 40-row rf3ParamSkill table and the player's 40 "
                                 "skill slots") for f in ("Skill 1", "Skill 2", "Skill 3")},
                   "RP cost": (0, 0xFFFF, "one reader takes only its low 2 bytes")},
    },
    "rf3ParamSkill": {
        # 40 x 40-byte per-SKILL table = archive 14818, row = skill id 0..39. Every field is a
        # Q12 amount per skill level (4096 = 1 point per level); the game adds (coef * L) >> 12
        # for a skill at level L. RE-CHECKED 2026-10-31: the archive id appears in exactly eight
        # functions besides the preload, and between them they read only these:
        #   +0..+16 Player_ApplyAllSkillGrowthBonusesFromArchive14818 (+0xB0E00), every skill:
        #     +0  max HP   += ((coef*L) >> 12) * ceil(L/50)   (x2 past level 50, x3 past 100, ...)
        #     +4  max RP   += min((coef*L) >> 12, (100*coef) >> 12)   (levels past 100 add nothing)
        #     +8 / +12 / +16  base STR / INT / VIT += ((coef*L) >> 12) * ceil(L/300)
        #     (skill levels go past 100: Player_gainEXP stops most skills at 999, Cooking /
        #     Forging / Chemistry / Crafting and the resist skills 26..32 at 99)
        #     (the status-resist skills 26..32 also add a HARD-CODED 83968*L >> 12 = 0.5% per
        #     level to their resist; that is not in this table)
        #   +20 only two rows are read: row 0 (Short Sword) by Actor_ComputeBuffedAtkOrDef
        #     (+0x969C7): the player's ATK and DEF += (row0.coef * L) >> 12 with L = the level of
        #     the skill of the held weapon or tool (hoe / watering can / sickle -> Farming, hammer
        #     -> Mining, axe -> Logging, pole -> Fishing); and row 35 (Throwing) by
        #     Item_ApplyThrowVelocity (+0xEAC7D): a thrown item's attack += coef * Throwing L.
        #     The other rows' +20 is never read.
        #   +24 no reader at all.
        #   +28 magic rows 6..12 (Fire..Love) only, Actor_ComputeDamageWithAtkScalarsAndElement
        #     Bonus (+0x96D61): the player's attack with that element += coef * L.
        #   +32 magic rows 6..12 only, Combat_ComputeDamage (+0x95DF2): damage taken from that
        #     element -= coef * the target's L (after DEF, in damage points).
        #   +36 RP cost cut: cost * (4096 - min(L,100) * coef) >> 12, for actions governed by
        #     this skill (Player_ChargeSkillCastCostByActionIdFromArchive14819 +0xB21E7,
        #     Combat_ApplyAttackEntry +0xB1FEC, Effect_ApplyByKindAndSpawn +0xED110).
        # All reads are signed 32-bit.
        "fields": [
            ("Max HP per level", 0, "s32"),        # max HP gained per level of this skill, times 2 past level 50, times 3 past 100, and so on
            ("Max RP per level", 4, "s32"),        # max RP gained per level of this skill (up to level 100)
            ("STR per level", 8, "s32"),           # base STR gained per level of this skill (times 2 past level 300)
            ("INT per level", 12, "s32"),          # base INT gained per level of this skill (times 2 past level 300)
            ("VIT per level", 16, "s32"),          # base VIT gained per level of this skill (times 2 past level 300)
            ("Weapon ATK per level", 20, "s32"),   # read on two rows only: Short Sword's value x the level of the held weapon or tool's own skill goes to ATK and DEF (for every weapon and tool); Throwing's goes to thrown items' attack; the other rows are ignored
            ("unused 24", 24, "s32"),              # the game never reads this column
            ("Spell ATK per level", 28, "s32"),    # magic skills only: attack added to spells of this element per level
            ("Element damage cut per level", 32, "s32"),  # magic skills only: damage taken from this element goes down by this per level
            ("RP cost cut per level", 36, "s32"),  # RP cost cut per level for actions of this skill (counted up to level 100)
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
            ("Birthday of", 0, "u8"),       # whose birthday it is (30 = a festival)
            ("Season", 1, "u8"),
            ("Day", 2, "u8"),               # 1..30
            ("Festival", 3, "u8"),          # festivals: shown only once this Prince-point order festival is scheduled (0 for birthdays)
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
            ("Character", 0, "u16"),        # who says it
            ("Line kind", 2, "u16"),        # when it is said (greeting, thanks, no money ...)
            ("Voice A", 4, "u16"), ("Voice B", 6, "u16"),  # the voice clip pair (0 = no voice)
            ("Expression", 8, "u16"),       # the portrait expression
            ("Bubble time", 10, "u16"),     # how long the speech bubble stays, in frames
            ("Flag", 12, "u16"),
            ("unused 14", 14, "u16"),
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
        "fields": [("Key character", 0, "u32")],  # the key's character as its UTF-8 bytes (0xE38182 = あ)
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
        # The item detail window's layout: row N goes with line N of
        # rf4TxtItemParameter_split2_2.<locale> (the same archive holds the window's text pieces in
        # lines 0..139 and the layouts in 140..210). Each of the 84 bytes picks what fills one %s of
        # that line, in order: byte 1 the first %s, byte 2 the second ... 0 = nothing.
        # Checked 2026-11-01: rf4DetailWindow_TickRefresh (RF4S.exe+0x33A20) and BagMenu_TickEquip
        # SpriteSub (+0x32590) each read all 84 bytes of the row DetailWindow_GetCurrentRecordIdx
        # gives (the row the item's kind picks) and pass each one to DetailWindow_RenderRowByKind
        # (+0x38DD0), which renders it with a text piece of the same archive (ITEM_DETAIL_IDS).
        # The values it shows come from the item's rf3UseItemParam, rf3ItemEquipmentParam and
        # rf3ItemStrengthening records (the window copies all three); 40 and 131..255 show nothing.
        # The row a kind of item uses is fixed in the exe, so added rows are never shown.
        "grow": "fixed:211",
        "fields": [(f"Detail {k}", k - 1, "u8") for k in range(1, 85)],
    },
    "Fishing_rate_fish_Spring": {
        # 38 x 88 B (22 dwords) fish-SPECIES spawn-weight table, archive 14803 (14804 =
        # Fishing_rate_fish_Spring2, the twin the game switches to while zone-1 game flag 2990
        # FLG_FISH_SUBTABLE is set; checked 2026-10-31: RF4S.exe only READS it (6 sites, all in
        # the two readers below), and no constant 2990 appears in any rf3.mc scene or em.bin
        # entry, so the shipped game never uses Spring2 -- it differs from Spring in rows 1, 18,
        # 20, 27 only, x10 weights). Row = species index: rows 0..31 = fish item 985+row (Masu
        # Trout, Squid, Taimen, ...), rows 32..37 = g_fishRareSpeciesRemapTable (RF4S.exe
        # +0x4D2528) = items 1017, 1018, 1019, 893, 894, 934.  Decoded 2026-09-19 from the only
        # two code sites that load archive 14803/14804 (offline immediate scan of RF4S.exe):
        #   Fishing_PickSpeciesAndSize (RF4S.exe+0x183A40): dw0..dw7 = spawn weight per ZONE,
        #     zone = 2*season + (1 if the weather code is rain/snow/storm), season 0..3 =
        #     spring/summer/fall/winter (a map's own season override wins). The per-pole rod
        #     modifier (hard-coded in Fishing_RecomputeRodWeights, i16 per species) is added
        #     to a non-zero weight and the sum clamped to 0..99999; a 0 weight stays 0, so a
        #     species with all-zero zone weights never spawns. Both callers pass the rod
        #     buffer, so every weight is clamped to 0..99999 (a negative one counts as 0).
        #     Only rows 0..37 are summed (loop of 38), so added rows are never picked.
        #     dw21 = size CLASS 0..3 = the column of Fishing_rate_lv_* used for the 10-bracket
        #     size roll (a class past 3 reads the next row's weights).
        #   Fishing_RollCaughtLevelWeightedBySpecies (+0x183E60): reads dw21 only.
        # CORRECTED 2026-09-30: every dw0..dw20 is a weight COLUMN. The column is
        # `zone_override - 1` when a caller passes one (an immediate scan cannot see this
        # computed index, which is why dw8..dw20 were once called unused):
        #   columns 0..7   2*season + wet (season from the map's MSEA, else the calendar;
        #                  wet = weather 1..4) -- the normal case
        #   columns 8..15  a fishing spot's "fish table" f11 = column + 1 (MOBJ type 24,
        #                  FishingMng_TrySpawnFish passes the spot's +14 value); each column is
        #                  named after the area of the shipped spots that use it (the map
        #                  editor's fish-table dropdown shows the same names)
        #   columns 16..20 the JUNK re-roll: Fishing_FinalizeCatch re-rolls a catch under
        #                  500 mm in column 16 + the equipped pole's tier (Cheap / Beginner's /
        #                  Skilled / Famous / Sacred Pole = items 584..588) and turns it into
        #                  the result only when that is a Can / Boot / Rare Can (rows 32..34);
        #                  shipped junk share 14 / 13 / 11 / 8 / 3 %. Only a catch under
        #                  500 mm (the fish actor's +48 size) gets the re-roll.
        # The per-column weights are weights among the 38 species (a 0 never spawns).
        "grow": "fixed:38",
        "limits": dict(
            {f: (0, 99999, "the game clamps every spawn weight to 0..99999") for f in (
                "Spring", "Spring rain", "Summer", "Summer rain", "Fall", "Fall rain", "Winter",
                "Winter rain", "Sercerezo Hill", "Idra Cave B2", "Idra Cave B1",
                "Yokmir Forest A04", "Yokmir Forest A06", "Water Ruins", "Maya Road",
                "Sechs Territory", "Junk Cheap Pole", "Junk Beginner's Pole",
                "Junk Skilled Pole", "Junk Famous Pole", "Junk Sacred Pole")},
            **{"Size class": (0, 3, "picks one of the 4 columns of Fishing_rate_lv; a larger "
                                    "value reads the next bracket's weights")}),
        "fields": [
            ("Spring", 0, "s32"),            # spring, clear weather
            ("Spring rain", 4, "s32"),       # spring, rain / snow / storm (weather 1..4)
            ("Summer", 8, "s32"),            # summer, clear weather
            ("Summer rain", 12, "s32"),      # summer, wet weather
            ("Fall", 16, "s32"),             # fall, clear weather
            ("Fall rain", 20, "s32"),        # fall, wet weather
            ("Winter", 24, "s32"),           # winter, clear weather (all of the L dungeon block)
            ("Winter rain", 28, "s32"),      # winter, wet weather
            ("Sercerezo Hill", 32, "s32"),            # fishing spots with fish table 9 (MAP_FIELD_99): sea -- Sand Flounder
            ("Idra Cave B2", 36, "s32"),              # fish table 10 (MAP_DUNG_J38): mostly Squid
            ("Idra Cave B1", 40, "s32"),              # fish table 11 (MAP_DUNG_J24): mostly Shrimp
            ("Yokmir Forest A04", 44, "s32"),         # fish table 12 (MAP_DUNG_A04): river fish
            ("Yokmir Forest A06", 48, "s32"),         # fish table 13 (MAP_DUNG_A06): an even mix
            ("Water Ruins", 52, "s32"),               # fish table 14 (MAP_DUNG_B02/B10/B11/B14/B15, MAP_FIELD_12)
            ("Maya Road", 56, "s32"),                 # fish table 15 (MAP_DUNG_K47)
            ("Sechs Territory", 60, "s32"),           # fish table 16 (MAP_DUNG_L41)
            ("Junk Cheap Pole", 64, "s32"),       # junk re-roll with the Cheap Pole (tier 0): only rows Can / Boot / Rare Can decide
            ("Junk Beginner's Pole", 68, "s32"),  # junk re-roll, tier 1
            ("Junk Skilled Pole", 72, "s32"),     # junk re-roll, tier 2
            ("Junk Famous Pole", 76, "s32"),      # junk re-roll, tier 3
            ("Junk Sacred Pole", 80, "s32"),      # junk re-roll, tier 4 (shipped: 3 % junk)
            ("Size class", 84, "u32"),            # 0..3: which column of Fishing_rate_lv rolls this fish's size and its item level
        ],
    },
    "Fishing_rate_fish_Spring2": {"alias": "Fishing_rate_fish_Spring",
                                  "unused": 'The game reads it only while game flag FLG_FISH_SUBTABLE is set, and nothing in the game sets that flag (no code in RF4S.exe and no event script writes it), so the plain Spring file is the one in use.'},
    "Fishing_rate_lv_Spring": {
        # 10 x 16 B size-bracket / catch-level weights, archive 14805 (14806 =
        # Fishing_rate_lv_Spring2, byte-identical in the shipped bundle, selected by the same
        # flag 2990, which nothing sets). Row = bracket 0..9 (0 = smallest), column = the species' size_class
        # (Fishing_rate_fish_* dw21).  Readers (2026-09-19):
        #   Fishing_PickSpeciesAndSize (+0x183A40): weighted roll over the 10 rows of column
        #     size_class -> size bracket; size_mm = min + bracket*step + rand(step+1) with
        #     (min, max) from g_fishSizeRangeTable / g_fishMaxSizeTable (+0x4D39D0, 38 pairs)
        #     and step = (max - min) / 10.
        #   The caught fish's ITEM LEVEL (checked 2026-10-31): Fishing_SpawnFishActor
        #     (+0x181350) stores the size bracket at the fish actor's +28 and the size in mm at
        #     +48; Fishing_FinalizeCatch (+0x181970) packs the item with level = that bracket
        #     (0 = Lv 1), then calls the roll below once per charge level of the cast
        #     (PlayerStats +132) and keeps the highest result. An uncharged cast keeps the
        #     bracket. Only rows 0..9 are read.
        #   Fishing_RollCaughtLevelWeightedBySpecies (+0x183E60): the same 10-row roll for the
        #     catch's level byte, but it indexes the file ONE DWORD EARLY (payload dword
        #     4*level + size_class - 1): class 0 level 0 reads the NLCL count field (10) and
        #     class 0 level L>0 reads row L-1's class3, every other class reads the column to
        #     its left. Reproduce this quirk when balancing; do not 'fix' the table for it.
        "grow": "fixed:10",
        "fields": [
            ("Size class 0", 0, "u32"),      # weight of this size bracket (and item level) for fish of size class 0
            ("Size class 1", 4, "u32"),      # ... size class 1
            ("Size class 2", 8, "u32"),      # ... size class 2
            ("Size class 3", 12, "u32"),     # ... size class 3
        ],
    },
    "Fishing_rate_lv_Spring2": {"alias": "Fishing_rate_lv_Spring",
                                "unused": 'The game reads it only while game flag FLG_FISH_SUBTABLE is set, and nothing in the game sets that flag (no code in RF4S.exe and no event script writes it), so the plain Spring file is the one in use.'},
    "rf3ScheduleID": {
        # 3898 x 12 B NPC schedule SPOTS, archive 15217 (see rf4s_modkit/schedule.py). A slice
        # of rf3Schedule.bin names a spot KIND k; kind k owns records [KIND_PREFIX[k],
        # KIND_PREFIX[k+1]) (g_scheduleSlotKindPrefixTable, RF4S.exe+0x4DCF70) and the game
        # rolls one of them per day weighted by `weight` (NpcSchedule_PickRandomScheduleSlotByKind
        # +0x2318E0). room/x/y/facing/wander are consumed by NpcSchedule_PlaceNpcAtSliceWithJitter
        # (+0x22EAA0: x,y script units << 12; facing << 8; wander = jitter radius); weight/flags/busy by
        # the picker (busy = runtime scratch); the flag bits are in FLAG_FIELDS and
        # schedule.py (re-read 2026-09-30: 0x1 run, 0x2 replaceable, 0x4 season 1 only,
        # 0x8 ignore crowding). The picker sums the weights of a kind in a u8, so a kind's
        # total weight must stay <= 255 (schedule.spot_weight_problems checks it; shipped
        # max 152).
        "fields": [
            ("Room", 0, "u16"),
            ("X", 2, "s16"), ("Y", 4, "s16"),  # position in the room (8 per tile)
            ("Facing", 6, "u8"),            # direction it faces (256 = a full turn)
            ("Action", 7, "u8"),            # what it does there (copied into the day plan)
            ("Wander", 8, "u8"),            # how far it may stray from the spot (tiles)
            ("Weight", 9, "u8"),            # chance among the spots of its kind (a kind's total must stay 255 or less)
            ("Flags", 10, "u8"),            # run / replaceable / season 1 only / ignore crowding: use the tick boxes
            ("Busy", 11, "u8"),             # the game's own marker while someone uses the spot (0 in the file)
        ],
        "limits": {"Room": (0, 871, "a room id of the 872-room enum")},
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
        # 2026-10-31: +14 is the level the station shows (CookingMenu_OnModeChanged_
        # RefreshSubpanel, Recipe_RefreshIngredientCheck); CraftSkill_CountMaxLearnableRecipesBy
        # Kind / Skill_GetUnlockFloatFromArchive count a recipe as learnable only when it is
        # <= 99 and its id is not 341.
        "names": "item", "name_field": "Result",
        "fields": [
            ("Result", 0, "u16"),          # the item it makes
            ("Ingredient 1", 2, "u16"), ("Ingredient 2", 4, "u16"), ("Ingredient 3", 6, "u16"),
            ("Ingredient 4", 8, "u16"), ("Ingredient 5", 10, "u16"), ("Ingredient 6", 12, "u16"),
            ("Skill level", 14, "u16"),    # the crafting skill level it needs (over 99: never learnable)
            ("Recipe id", 16, "u32"),      # the learned-recipe bit, unique across all recipe files (read as a dword)
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
# PERCENT marks a field stored as a plain whole percentage (100 = 100%; the game divides by 100),
# shown and typed with the same '150%' / '1.5x' forms.
# {table stem: {field: fraction bits or PERCENT}}
PERCENT = "pct"
# AMOUNT marks a Q12 field that is an amount, not a share (4096 = 1 point): shown and typed as a
# plain decimal number (0.5, 2), converted the way the shipped data was (0.1 -> 409, truncated).
AMOUNT = "amount"
# PERMILLE marks a field stored per mille (1000 = 100%), shown and typed as a percentage.
PERMILLE = "permille"
# ANGLE marks a u16 angle (65536 = 360 degrees), shown and typed in degrees ("90°", 90, 90deg).
ANGLE = "angle"
FIXED_FIELDS = {
    "rf3ParamMagic": {f: 12 for f in ("ATK scaling", "MAT scaling", "Damage multiplier",
                                      "Level bonus", "Knockback", "Stun", "Launch",
                                      "Launch gravity", "Hit size", "Poison chance",
                                      "Seal chance", "Paralysis chance", "Sleep chance",
                                      "Fatigue chance", "Cold chance", "Faint chance",
                                      "HP drain", "RP cost (share of max RP)")},
    "rf3NpcParam": {**{f"{e} resist": 12 for e in ("Fire", "Water", "Earth", "Wind", "Light",
                                                   "Dark", "Neutral", "Love", "Poison", "Seal",
                                                   "Paralysis", "Sleep", "Fatigue", "Cold",
                                                   "Faint", "Drain", "Will", "Knockback",
                                                   "Critical")},
                    **{f: 12 for f in ("Size", "Walk speed", "Run speed", "Acceleration",
                                       "Braking", "Effect size", "Knockback", "Stun",
                                       "Stun taken", "Critical chance", "HP drain")},
                    **{f"{s} growth": PERCENT for s in ("ATK", "MAT", "DEF", "MDF", "HP")},
                    **{f"Drop {k} chance": PERMILLE for k in (1, 2, 3, 4)},
                    "Spawn asleep chance": 8, "Produce chance": 8,
                    "Hit arc": ANGLE, "View angle": ANGLE},
    "rf3UseItemParam": {**{f: 12 for f in ("HP healed (share of max)", "RP healed (share of max)",
                                           "Fed: max HP %", "Fed: max RP %", "Fed: STR %",
                                           "Fed: INT %", "Fed: VIT %", "Fed: critical chance",
                                           "Fed: knockback resist", "Fed: critical resist")},
                        "Per-level bonus": 15},             # % per item level (4096 = 12.5%)
    "rf3ParamSkill": {**{f: AMOUNT for f in ("Max HP per level", "Max RP per level",
                                             "STR per level", "INT per level", "VIT per level",
                                             "Weapon ATK per level", "Spell ATK per level",
                                             "Element damage cut per level")},
                      "RP cost cut per level": 12},
    "rf3MapMiniPos": {"Scale X": 12, "Scale Y": 12},
    # every q12 column of rf3ItemStrengthening (strengthening.UNIT == "q12"; selftest compares)
    "rf3ItemStrengthening": {f: 12 for f in (
        "Critical chance",
        "Knockback",
        "Stun",
        "Poison chance",
        "Seal chance",
        "Paralysis chance",
        "Sleep chance",
        "Fatigue chance",
        "Cold chance",
        "Faint chance",
        "HP drain",
        "Will resist",
        "Critical resist",
        "Knockback resist",
        "Poison resist",
        "Seal resist",
        "Paralysis resist",
        "Sleep resist",
        "Fatigue resist",
        "Cold resist",
        "Faint resist",
        "Drain resist",
        "Reach",
        "HP healed (share of max)",
        "RP healed (share of max)",
        "Fed: max HP %",
        "Fed: max RP %",
        "Fed: STR %",
        "Fed: INT %",
        "Fed: VIT %",
        "Fed: critical chance",
        "Fed: knockback resist",
        "Fed: critical resist",
        "Fed: poison resist",
        "Fed: seal resist",
        "Fed: paralysis resist",
        "Fed: sleep resist",
        "Fed: fatigue resist",
        "Fed: cold resist",
        "Fed: faint resist",
        "Fed: poison chance",
        "Fed: seal chance",
        "Fed: paralysis chance",
        "Fed: sleep chance",
        "Fed: fatigue chance",
        "Fed: cold chance",
        "Fed: faint chance",
        "Fire resist",
        "Water resist",
        "Earth resist",
        "Wind resist",
        "Light resist",
        "Dark resist",
        "Love resist",
    )},
    "rf3ItemEquipmentParam": {f: 12 for f in (
        ["Critical chance", "Knockback", "Stun", "HP drain", "Will resist", "Critical resist",
         "Knockback resist", "HP drain resist", "Tool charge", "Reach", "Swing arc"]
        + [f"{s} chance" for s in ("Poison", "Seal", "Paralysis", "Sleep", "Fatigue", "Cold", "Faint")]
        + [f"{s} resist" for s in ("Poison", "Seal", "Paralysis", "Sleep", "Fatigue", "Cold", "Faint")]
        + [f"{s} resist" for s in ("Fire", "Water", "Earth", "Wind", "Light", "Dark", "Love", "Neutral")])},
    "rf3CropParam": {f: 7 for f in ("Growth speed", "Level gain", "Size gain", "Yield gain")},
    # Item_ComputeStackGoldValue (RF4S.exe+0x454A0): gold = price * value / 100
    "rf3PriceTable": {f"Lv {j}": PERCENT for j in range(1, 11)},
    # share of the max RP out of 256 (Combat_ApplyAttackEntry: (16 * coef * rp_max) >> 12)
    "rf3ParamSkillData": {"RP cost (share of max RP)": 8},
    # chances out of 256 (TileObject_ApplyToolHit's ProbRoll_ExtraDrop_FavorsNoSkill)
    "MapOre_Rate": {"Break chance": 8, "Scrap chance": 8},
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
    "rf3ParamMagic": {"Flags": {
        0x1: "Fire", 0x2: "Water", 0x4: "Earth", 0x8: "Wind", 0x10: "Light", 0x20: "Dark",
        0x40: "Love", 0x80: "Magic", 0x100: "Direct damage to player", 0x200: "Ignore DEF",
        0x400: "No random spread", 0x800: "Hammer hit sound", 0x1000: "Full stun (not reduced by stun resist; staggers monsters that never flinch)",
        0x2000: "Turnip-and-stars hit effect", 0x8000: "Grab (Marionetta)",
        0x10000: "Water hit sound", 0x200000: "Always 1 damage", 0x400000: "Half element resist",
        0x800000: "Faint drop Cabbage", 0x1000000: "Faint drop Pumpkin",
        0x2000000: "Faint drop Potato", 0x4000000: "Faint drop Turnip",
        0x40000000: "No critical hits"}},
    "rf3UseItemParam": {"Effects": {
        **{1 << k: "Cure " + s for k, s in enumerate(_STATUS[:6])},
        **{1 << (6 + k): "Inflict " + s for k, s in enumerate(_STATUS)},
        0x2000: "Level up"}},
    # rf3ItemEquipmentParam (2026-10-31): Ability flags = the rf3ParamMagic flags (the same word,
    # AttackInfo+320) plus the bits only equipment carries (Equip_AccumulateItemStats tests
    # 0x20000000; 0x80000 / 0x100000 / 0x8000000 from strengthening.FORGE_SPECIALS); the boots
    # and accessory bits are each set by one shipped item (named after it, its in-game description
    # as the effect; 0x400 / 0x20000 / 0x800000 / 0x2000000 / 0x2 / 0x4 / 0x8 also seen in code).
    "rf3ItemEquipmentParam": {
        "Ability flags": {**{m: n for m, n in ({
            0x1: "Fire", 0x2: "Water", 0x4: "Earth", 0x8: "Wind", 0x10: "Light", 0x20: "Dark",
            0x40: "Love", 0x80: "Magic", 0x100: "Direct damage to player", 0x200: "Ignore DEF",
            0x400: "No random spread", 0x800: "Hammer hit sound", 0x1000: "Full stun (not reduced by stun resist; staggers monsters that never flinch)",
            0x2000: "Turnip-and-stars hit effect", 0x8000: "Grab (Marionetta)",
            0x10000: "Water hit sound", 0x200000: "Always 1 damage", 0x400000: "Half element resist",
            0x800000: "Faint drop Cabbage", 0x1000000: "Faint drop Pumpkin",
            0x2000000: "Faint drop Potato", 0x4000000: "Faint drop Turnip",
            0x40000000: "No critical hits"}).items()},
            # 0x100000 (Dolphin Brooch; the White Stone as a forging material): when the wearer
            # is the spouse or a child (char 22 / 23, Player_GetMarriagePartnerNpcId), ATK / DEF
            # x2 from any slot (Actor_ComputeBuffedAtkOrDef) and damage taken /2 from an armour
            # slot (Combat_ComputeDamage); for ANY wearer, the player included, a positive element
            # bonus (a weakness) /2 from an armour slot (Combat_GetElementBonus has no spouse
            # test). Read from the worn items by Actor_RecomputeStats / Player_ApplyEquippedItemStats
            # (equip_granted_flags_all / _armor).
            0x80000: "Drop rate up",
            0x100000: "Half element weakness: a spouse / child wearer also gets ATK & DEF x2 and half damage taken",
            0x8000000: "Search like the Magnifying Glass",
            0x20000000: "Lightweight (a shield still works with dual blades / fists, at half)"},
        "Boots effects": {
            0x1: "Water Shoes: walk on water", 0x2: "Sneaking Boots: attack before monsters notice",
            0x4: "Fast Step Boots: a spring in your step", 0x8: "Free Farming Shoes: farm off the grid",
            0x10: "Piyo Sandals: chirp with every step", 0x20: "Ice Skates: skate (no jump or spin)",
            0x40: "Step-In Boots: no dash attacks", 0x80: "Snow Boots: never slip",
            0x100: "Wet Boots: more critical hits", 0x200: "Secret Shoes: look taller",
            0x400: "Ghost Boots: travel faster", 0x800: "Rocket Wing: walk much faster (tiring)",
            0x1000: "Iron Geta: travel slower", 0x2000: "Heavy Boots: not blown away, tire faster",
            0x4000: "Strider Boots: longer dash invincibility"},
        "Accessory effects": {
            0x1: "Happy Ring: find more items", 0x2: "Poison Ring: resist and inflict poison",
            0x4: "Paralysis Ring: resist and inflict paralysis",
            0x8: "Silent Ring: resist and inflict seal", 0x10: "Magic Ring: faster charging",
            0x20: "Throwing Ring: throw items far", 0x40: "Anette's Necklace: move faster",
            0x80: "Stay-up Ring: no yawning", 0x100: "Field Pendant: stronger friendly monsters",
            0x200: "Sun Pendant: stronger companions", 0x400: "Dew Pendant: farm tools hit harder",
            0x800: "Star Pendant: more experience", 0x1000: "Heart Pendant: more skill experience",
            0x2000: "Hand-Knit Scarf: half RP use", 0x4000: "Fluffy Scarf: no RP use (some exceptions)",
            0x8000: "Shield Ring: sometimes take only 1 damage",
            0x10000: "Magic Charm: use the stronger of ATK / MAT",
            0x20000: "Champ Belt: much more max HP", 0x40000: "Rosary: fewer monsters appear",
            0x80000: "Talisman: reverses status effects", 0x100000: "Hero's Proof: slowly recover HP",
            0x200000: "Proof of Wisdom: slowly recover RP", 0x400000: "Art of Defense: half flinch time",
            0x800000: "Art of Attack: wider weapon reach",
            0x1000000: "Art of Magic: halves non-elemental damage",
            0x2000000: "Earth Pendant: stronger recovery items",
            0x4000000: "Strange Pendant: no DEF / MDF"}},
    "rf3ItemStrengthening": {"Effects": {
        **{1 << k: "Cure " + s for k, s in enumerate(_STATUS[:6])},
        **{1 << (6 + k): "Inflict " + s for k, s in enumerate(_STATUS)},
        0x2000: "Level up", 0x4000: "Not food (spoils a dish)"}},
    # rf3ScheduleID.flags: see rf4s_modkit/schedule.py (copied to the NPC's day plan +5)
    "rf3ItemList": {"Flags": {
        0x1: "Can't be thrown away", 0x2: "Unique key item (tracked when given away; never bait)",
        0x4: "Special fishing catch", 0x8: "Giant crop (drawn with its crop's giant model)",
        0x10: "Weapon level / quality bonuses", 0x20: "Armour level / quality bonuses",
        0x40: "Staff level / quality bonuses", 0x80: "Accessory level / quality bonuses"}},
    "rf3ScheduleID": {"Flags": {0x1: "Run", 0x2: "Replaceable", 0x4: "Season 1 only",
                                0x8: "Ignore crowding"}},
    "rf3TxtShopNpc_split2_1": {"Flag": {}},
    "rf4TxtQuestRequestDetailFormat_split2_1": {"Flag": {}},
}


# ---- reference fields, value names, row names --------------------------------------------
# What a number in a field (or a row index) stands for, so the GUI can show a name and edit with
# a searchable picker. Only meanings stated as verified in the schema notes above are listed.
# Kinds: "item" (0 = an empty slot; recipe ingredients may be a category item such as 1083
# Minerals: any item of that category is accepted), "char", "room", "skill". Matched by stem
# (aliases followed), then by the PREFIX_SCHEMAS family prefix.
REF_FIELDS = {
    "rf3Recipe": {f: "item" for f in ("Result", *(f"Ingredient {k}" for k in range(1, 7)))},
    "MapOre_Rate": {f: "item" for f in ("Item 1", "Item 2", "Item 3", "Rare item")},
    "rf3ItemList": {"Family": "item"},
    "rf3TxtCalendar_split2_1": {"Birthday of": "char"},   # 30 = festival (VALUE_NAMES)
    "rf3TxtShopNpc_split2_1": {"Character": "char"},
    "rf3TxtQuest_split3_1": {"Client": "char"},
    "rf3ParamSkillData": {f: "skill" for f in ("Skill 1", "Skill 2", "Skill 3")},
    "rf3ParamMagic": {"Skill": "skill"},
    "rf3ScheduleID": {"Room": "room"},
    "rf3NpcParam": {**{f"Drop {k}": "item" for k in (1, 2, 3, 4)}, "Produce": "item",
                    "Home map": "room", "Transforms into": "char"},
}
# What each byte of rf4TxtItemParameter_split2_1 shows (DetailWindow_RenderRowByKind, RF4S.exe
# +0x38DD0): an item's own values, or one dword of its rf3UseItemParam ("Use item"),
# rf3ItemEquipmentParam ("Equipment") or rf3ItemStrengthening ("Upgrade") record.
_DETAIL_SOURCE = {
    **{i: ("rf3UseItemParam", d) for i, d in (
        (10, 0), (11, 2), (12, 1), (13, 3), (14, 4), (15, 5), (16, 6), (17, 11), (18, 7), (19, 12),
        (20, 8), (21, 13), (22, 9), (23, 14), (24, 10), (25, 15), (48, 16), (49, 18), (50, 17))},
    **{26 + k: ("rf3UseItemParam", 33 + k) for k in range(7)},       # element resists
    **{33 + k: ("rf3UseItemParam", 19 + k) for k in range(7)},       # status resists
    **{41 + k: ("rf3UseItemParam", 26 + k) for k in range(7)},       # status chances
    51: ("rf3ItemEquipmentParam", 0),                                # shown as its element
    **{52 + k: ("rf3ItemEquipmentParam", 3 + k) for k in range(39)},  # 52..90
    **{91 + k: ("rf3ItemStrengthening", 1 + k) for k in range(8)},    # 91..98
    **{99 + k: ("rf3ItemStrengthening", 10 + k) for k in range(3)},   # 99..101
    **{102 + k: ("rf3ItemStrengthening", 14 + k) for k in range(19)},  # 102..120
    121: ("rf3ItemStrengthening", 0),
    **{122 + k: ("rf3ItemStrengthening", 67 + k) for k in range(7)},  # element resists
}
_DETAIL_PREFIX = {"rf3UseItemParam": "Use item", "rf3ItemEquipmentParam": "Equipment",
                  "rf3ItemStrengthening": "Upgrade"}


def _detail_names() -> dict:
    out = {0: "", 1: "Level of each one in the stack", 2: "Sell price", 3: "Buy price",
           4: "Days to grow", 5: "Harvest yield", 6: "Sell price of the harvest",
           7: "Watering can: water left", 8: "Size (fish)", 9: "Unshipped mark",
           129: "Name of the item it is made from", 130: "Star mark"}
    for i, (tab, d) in _DETAIL_SOURCE.items():
        f = next(n for n, o, _t in FIELD_SCHEMAS[tab]["fields"] if o == 4 * d)
        out[i] = f"{_DETAIL_PREFIX[tab]}: {f}"
    out[51] = "Equipment: element"
    out[121] = "Upgrade: Difficulty"
    return dict(sorted(out.items()))


ITEM_DETAIL_IDS = _detail_names()
_SEASONS = {0: "Spring", 1: "Summer", 2: "Fall", 3: "Winter"}
# Named values of plain fields (shown as "Name (value)" and picked from a list).
VALUE_NAMES = {
    "rf3TxtCalendar_split2_1": {"Season": _SEASONS, "Birthday of": {30: "(festival)"}},
    "rf3TxtShopNpc_split2_1": {"Line kind": {
        0: "unused", 1: "greeting", 2: "browse", 3: "ponder", 4: "decide", 5: "confirm",
        6: "thanks", 7: "come again", 8: "decline", 9: "no space", 10: "no money",
        11: "out of stock", 12: "sale 10%", 13: "sale 20%"}},
    "rf3TxtQuest_split3_1": {"Client": {0: "(placeholder)", 22: "Anonymous", 23: "Anonymous"}},
    "rf4TxtItemParameter_split2_1": {f"Detail {k}": ITEM_DETAIL_IDS for k in range(1, 85)},
    # 388 of the 392 rows hold 0 (char 0 is the player): no other form
    "rf3NpcParam": {"Transforms into": {0: "(none)"},
                    "Motion set": {0: "Frey's", 1: "Lest's"}},   # the game tests it nonzero
}
# What a row index is: "item" / "room" / "skill" / "fish" (rows 0..31 = item 985+row, 32..37 =
# the rare remap, see the Fishing_rate_fish_Spring notes) / "level" (row L = level L -> L+1).
ROW_NAMES = {
    "rf3ParamSkill": "skill",
    "rf3NpcParam": "char",
    "rf3MapMiniPos": "room",
    "Fishing_rate_fish_Spring": "fish",
    "rf3Parameter": "level",
    "Fishing_rate_lv_Spring": "bracket",
    "rf4TxtItemParameter_split2_1": "text",          # row N = line N of the paired text file
}
# The TEXT archive whose line N goes with row N, for tables whose row kind is "text".
PAIRED_TEXT = {"rf4TxtItemParameter_split2_1": "rf4TxtItemParameter_split2_2"}
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


def unused_reason(stem: str) -> str:
    """Why the game ignores this table ("" when it is read): the schema's "unused" sentence,
    set only where the exe was checked to load the table without ever reading its rows (or to
    read it only behind a flag nothing sets). A file's own entry wins over the one it aliases."""
    own = FIELD_SCHEMAS.get(stem, {}).get("unused")
    return own if own is not None else FIELD_SCHEMAS.get(canonical_stem(stem), {}).get("unused", "")


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
    if key == "rf4TxtItemParameter_split2_1":
        for k in range(1, 85):
            notes.setdefault(f"Detail {k}", f"What fills %s number {k} of this row's text line "
                                            "(blank = nothing).")
    if key == "rf3ItemStrengthening":           # its field notes live in the strengthening module
        from . import strengthening
        for f, doc in strengthening.DOC.items():
            notes.setdefault(f, doc[:1].upper() + doc[1:] + ".")
    sch = FIELD_SCHEMAS.get(key) or PREFIX_SCHEMAS.get(key) or {}
    for f, lim in (sch.get("limits") or {}).items():
        lo, hi, why = lim
        notes[f] = (notes.get(f, "") + f"  Range {lo}..{hi}: {why}.").strip()
    res = ("\n".join(about), notes)
    _NOTES_CACHE[key] = res
    return res


# Bit sets whose every bit the exe reads is named (checked 2026-11-01): the editor's tick-box
# picker leaves the other bits out. The Effects words: Item_UseOnActor (+0xB4150) reads only
# 0x3F / 0x1FC0 / 0x2000, Crafting_CraftFromInputs only 0x4000 of rf3ItemStrengthening's (and
# Actor_RecomputeStats, Inventory_RefreshSlotStatPanel, script op 580 test none); rf3ItemList
# Flags names all 8 bits of its byte.
FLAG_FIELDS_COMPLETE = {
    ("rf3UseItemParam", "Effects"), ("rf3ItemStrengthening", "Effects"), ("rf3ItemList", "Flags"),
}


def flag_bits_complete(stem: str, name: str) -> bool:
    """True when every bit of this bit set the game reads is named (FLAG_FIELDS_COMPLETE)."""
    return (canonical_stem(stem), name) in FLAG_FIELDS_COMPLETE


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
    by_name = {}
    for m, n in (names or {}).items():
        # also the short form before an explanation: "Full stun", "Water Shoes"
        for short in (n, re.split(r"\s*\(|:", n, maxsplit=1)[0]):
            by_name.setdefault(_flag_key(short), m)
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
    """Fraction bits of a fixed-point field (12 for Q12, 7 for Q7), PERCENT for a whole-percent
    field, or None."""
    return FIXED_FIELDS.get(canonical_stem(stem), {}).get(name)


def fixed_scale(bits) -> int:
    """The stored value that means 100%: 2**bits, or 100 for a PERCENT field."""
    return 100 if bits == PERCENT else 1000 if bits == PERMILLE else 4096 if bits == AMOUNT \
        else 65536 if bits == ANGLE else 1 << bits


def _amount_raw(v: float) -> int:
    """A typed AMOUNT -> the stored Q12 integer, truncated toward zero like the shipped data
    (0.1 -> 409, 0.3 -> 1228); the epsilon keeps 0.25 * 4096 from landing on 1023.999."""
    q = v * 4096
    return int(q + 1e-6) if q >= 0 else -int(-q + 1e-6)


def _format_amount(raw: int) -> str:
    """The shortest decimal that converts back to `raw` (409 -> 0.1, 8192 -> 2)."""
    a = abs(raw)
    for nd in range(0, 13):
        k = 10 ** nd
        c = -(-a * k // 4096)                    # the smallest nd-digit decimal >= a/4096
        if _amount_raw(c / k) == a:
            s = f"{c / k:.{nd}f}"
            break
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return ("-" + s) if raw < 0 else s


def format_value(raw: int, bits=None) -> str:
    """How a field value is shown: a percentage for a fixed-point field (the stored value
    over 2**bits: 4096 -> 100%, 6144 -> 150%, Q7 128 -> 100%), else the int. The percentage is
    the SHORTEST decimal that converts back to the same stored integer (4710 -> 115%, the value
    the designers typed, not 114.99%); two decimals always do for Q12, fewer for Q7."""
    if bits is None:
        return str(raw)
    if bits == AMOUNT:
        return _format_amount(raw)
    if bits == ANGLE:                           # the shortest degrees that store back the same
        for nd in range(0, 7):
            s = f"{raw * 360 / 65536:.{nd}f}"
            if round(float(s) * 65536 / 360) == raw:
                break
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s + "\u00b0"
    one = fixed_scale(bits)
    for nd in range(0, 7):
        s = f"{raw * 100 / one:.{nd}f}"
        if round(float(s) * one / 100) == raw:
            break
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return (s if s not in ("-0", "") else "0") + "%"


def parse_value(text: str, typ: str = "s32", bits=None) -> int:
    """A typed field value -> the stored integer. In a field shown as a percentage, a number
    is a percentage ('150', '150%'; or the multiplier '1.5x' / '1.5×') and only hex ('0x1800')
    is the stored value as is; in any other field it is a plain integer (0x.. allowed). Checks
    the field's width and names the percentage range when it does not fit."""
    t = typed = str(text).strip()
    if bits == ANGLE and not t.lstrip("+-").lower().startswith("0x"):
        num = t.rstrip("\u00b0").strip()
        num = num[:-3].strip() if num.lower().endswith("deg") else num
        try:
            raw = round(float(num) * 65536 / 360)
        except ValueError:
            raise NlclError(f"{typed!r} is not a number of degrees") from None
        lo, hi = type_range(typ)
        if not lo <= raw <= hi:
            raise NlclError(f"{typed} does not fit a {typ} field: {lo * 360 / 65536:g}\u00b0 .. "
                            f"{hi * 360 / 65536:g}\u00b0")
        return raw
    if bits not in (None, AMOUNT, ANGLE) and not t.endswith(("%",) + MULT_SIGNS) \
            and not t.lstrip("+-").lower().startswith("0x"):
        t += "%"                                # a plain number in a percentage field
    if bits == AMOUNT:
        try:
            raw = _amount_raw(float(t))
        except ValueError:
            raise NlclError(f"{t!r} is not a number") from None
        lo, hi = type_range(typ)
        if not lo <= raw <= hi:
            raise NlclError(f"{t} does not fit a {typ} field: {lo / 4096:g} .. {hi / 4096:g}")
        return raw
    if t.endswith("%") or t.endswith(MULT_SIGNS):
        if bits is None:
            raise NlclError(f"{t!r}: this field is not a percentage -- type a whole number")
        pct = t.endswith("%")
        try:
            v = float(t[:-1].strip())
        except ValueError:
            raise NlclError(f"{typed!r} is not a number") from None
        one = fixed_scale(bits)
        raw = round((v / 100 if pct else v) * one)
        lo, hi = type_range(typ)
        if not lo <= raw <= hi:
            raise NlclError(f"{t} does not fit a {typ} field: {lo * 100 / one:g}% .. "
                            f"{hi * 100 / one:g}%")
        return raw
    try:
        return int(t, 0)
    except ValueError:
        raise NlclError(f"{t!r} is not a whole number") from None


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
        br = bit_range(typ)
        if br:
            return (self.get(rec, off, br[0]) >> br[1]) & ((1 << br[2]) - 1)
        code, sz = _FMT[typ]
        if off + sz > self.record_size:            # same guard as set(): no cross-record read
            raise NlclError(f"{typ} at +{off} exceeds record size {self.record_size}")
        return struct.unpack_from(code, self.data, self._addr(rec, off))[0]

    def set(self, rec: int, off: int, value: int, typ: str = "s32"):
        br = bit_range(typ)
        if br:                                  # write those bits, keep the rest of the int
            base, lo, n = br
            value = int(value)
            if not 0 <= value < (1 << n):
                raise NlclError(f"value {value} does not fit {typ} (0..{(1 << n) - 1})")
            mask = ((1 << n) - 1) << lo
            self.set(rec, off, (self.get(rec, off, base) & ~mask) | (value << lo), base)
            return
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
