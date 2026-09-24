"""rf4s_modkit/skillcurve.py -- skill XP-per-level curves (`rf3ParamSkillExp*.bin`).

Each curve file is a 28-byte NLCL header (entry_count 100 @+24) followed by a flat array of
**100 little-endian i32 XP thresholds**, `table[level]` = XP needed to advance FROM that
level to the next, then the 16-byte generic NLCL footer ({0,24,0,0}; an earlier version of
this note miscounted it as "4 zero-pad entries"). Levels cap at 99 for the crafting skills
and 999 for the rest -- 999-skills reuse `table[99]` as the asymptotic bracket. The main
curve is a per-decade **sawtooth** (costs ramp within each 10-level band, then step down
at each x10 boundary) under a rising overall envelope (e.g. 8 .. 20000).

Consumer-verified (re-read 2026-09-19):
  * `Player_GetSkillXpToNextLevel` (RF4S.exe+0x38440): 0xFFFFFF at the cap (level >= 999,
    or >= 99 for skills 17..20); otherwise `*(u32*)(LevelTable + 4*level)` for level < 99
    and `*(u32*)(LevelTable + 396)` (= table[99]) for every level past 99.
  * `Skill_GetLevelTable` (RF4S.exe+0x83E60): `nsFileArchive_GetData(archive) + 28`, the
    archive picked by the skill-id switch reproduced in FAMILY_ARCHIVE below.

The archive-id -> filename pairing (ARCHIVE_FILE) was byte-confirmed on 2026-08-21 (per the
IDB note on Skill_GetLevelTable: NLCL count 100 @+24, 444 bytes each); the curve FILE
format and the family->archive-id selection are verified as above. Editing: `set_level_xp`
/ `scale_curve` (CLI `rf4mod skill set`); the NLCL footer is left untouched.
"""
from __future__ import annotations

import struct

HEADER = 28
REAL_LEVELS = 100          # the file holds exactly 100 i32 (+ the 16-byte NLCL footer)
_CAP_OFFSET = 99 * 4       # table[99] = +396 within the array (the +0x18C the game reads)


# Skill_GetLevelTable (+0x83E60): skill_id -> XP-curve archive id (IDA-verified switch).
# Skill ids per the authoritative 40-slot table (project_rf4s_skill_ids):
FAMILY_ARCHIVE = {
    **{s: 14821 for s in (13, 14, 15)},                       # Farming / (hole) / Mining
    **{s: 14822 for s in (16, 21, 26, 27, 28, 29, 30, 31, 32, 34, 35)},  # Fishing / Searching / Resist* / Taming / Throwing
    **{s: 14823 for s in (17, 18, 19, 20)},                   # Cooking / Forging / Chemistry / Crafting (the 4 cap-99 crafting skills)
    **{s: 14824 for s in (23, 24, 33)},                       # Sleeping / Eating / Bathing (passive life skills)
}
DEFAULT_ARCHIVE = 14820                                       # standard curve (all others: weapons, magic, Defense, Walking...)

# The 5 shipped curve files (rf3ParamSkillExp*) -> the 5 consecutive curve archives
# 14820..14824 (byte-confirmed 2026-08-21, see the module docstring).
ARCHIVE_FILE = {
    14820: "rf3ParamSkillExp",       # default / standard
    14821: "rf3ParamSkillExpFarm",   # Farming/Mining
    14822: "rf3ParamSkillExpFish",   # Fishing/Searching/Resists...
    14823: "rf3ParamSkillExpMix",    # Cooking/Forging/Chemistry/Crafting (mixing)
    14824: "rf3ParamSkillExpSleep",  # Sleeping/Eating/Bathing
}
CURVE_FILES = tuple(ARCHIVE_FILE.values())


def file_for_skill(skill_id: int) -> str:
    """The XP-curve .bin file that governs a given skill id (via its archive)."""
    return ARCHIVE_FILE[archive_for_skill(skill_id)]


def archive_for_skill(skill_id: int) -> int:
    """Which XP-curve archive id the game uses for a given skill id (Skill_GetLevelTable)."""
    return FAMILY_ARCHIVE.get(skill_id, DEFAULT_ARCHIVE)


def parse(data: bytes) -> list[int]:
    """Return the per-level XP-to-next array (i32), trimmed to the real levels (0..99)."""
    body = data[HEADER:]
    n = min(REAL_LEVELS, len(body) // 4)
    return [struct.unpack_from("<i", body, i * 4)[0] for i in range(n)]


def cap_threshold(data: bytes) -> int:
    """table[99] -- the bracket a 999-cap skill keeps using past level 99."""
    return struct.unpack_from("<i", data, HEADER + _CAP_OFFSET)[0]


def render(data: bytes, upto: int = 30) -> str:
    """Human-readable curve: level -> XP-to-next and running cumulative total."""
    xp = parse(data)
    # table[L] = XP required while AT internal skill-level L to reach L+1 (from the consumer).
    lines = ["level L  xp[L]->next   cumulative"]
    total = 0
    for lvl, step in enumerate(xp[:upto]):
        total += step
        lines.append(f"{lvl:>5}   {step:>10}   {total:>10}")
    if upto < len(xp):
        lines.append(f" ... ({len(xp) - upto} more levels; total to 100 = {sum(xp)})")
    lines.append(f"flat? {'yes' if len(set(xp[:20])) == 1 else 'no'}   cap-bracket(table[99]) = {xp[-1] if xp else 0}")
    return "\n".join(lines)


def set_level_xp(buf: bytearray, level: int, value: int) -> None:
    """Edit table[level] in place (buf must be the full file bytearray). The value is the
    XP needed to go from `level` to `level + 1` (Player_GetSkillXpToNextLevel reads
    `archive + 28 + 4*level`, or +0x18C = table[99] once an uncapped skill is past 99)."""
    if not (0 <= level < REAL_LEVELS):
        raise IndexError(f"level {level} out of range 0..{REAL_LEVELS - 1}")
    v = int(value)
    if not (0 <= v <= 0x7FFFFFFF):
        raise ValueError(f"xp {v} out of range 0..2147483647")
    struct.pack_into("<i", buf, HEADER + level * 4, v)


def scale_curve(buf: bytearray, percent: float, minimum: int = 1) -> list[int]:
    """Multiply every level's XP-to-next by `percent`/100 in place (rounded half-up,
    floored at `minimum` so no level becomes free) and return the new table. 50 = twice
    as fast to level, 200 = twice as slow."""
    if percent <= 0:
        raise ValueError("percent must be > 0")
    out = []
    for lvl, xp in enumerate(parse(bytes(buf))):
        v = max(minimum, int(xp * percent / 100.0 + 0.5))
        set_level_xp(buf, lvl, v)
        out.append(v)
    return out
