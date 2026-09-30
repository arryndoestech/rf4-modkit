"""rf4s_modkit/magicnames.py -- what each rf3ParamMagic.bin row (effect kind) is used for.

rf3ParamMagic (archive 14817) is one id space shared by player spells, monster and boss attacks,
weapon moves and utility effects; the file itself carries no names. A row is named from the
places that fire it:

  * attack timelines (as_atk_*.bin, archives 243..932): an op 43 event fires its operand as the
    effect kind (AnimEvent_Op43_TriggerEffectKind -> Effect_ApplyByKindAndSpawn, RF4S.exe+0xECEC0).
      - as_atk_magic_<element><tier> is the player spell of item 1025 + 3*element + tier
        (Fireball .. Mediseal; the element and skill id of every row match the item's);
      - as_atk_m_<NN>_* / as_atk_mb_<NN>_* are monster / boss moves. A monster uses the
        timelines from `archive = rf3NpcParam +280 + 243 + skill_id` (Actor_BeginAttackOrSkill
        RF4S.exe+0x1610C0 via stats +176), so a group's lowest archive - 243 == the +280 value of
        the monsters that use it (all 71 groups line up with rf3NpcParam);
      - everything else (seed_*, sword_skill_*, magic_9x_been ...) is named by its timeline.
    The archive id of each timeline comes from the exe's archive path table (UTF-16, 256 bytes
    per id), located by the path of archive 243.
  * rows no timeline fires are left unnamed (they are fired from code: boss scripts, thrown
    items, traps ...).
"""
from __future__ import annotations

import pathlib
import re
import struct

from . import asatk

FIRST_TIMELINE = 243
LAST_TIMELINE = 932
_ENTRY = 256
_ANCHOR = "rom:/as/as_atk_axe_00.bin"

_CACHE: dict = {}


def timeline_archive_ids(exe_data: bytes) -> dict[str, int]:
    """{'m_06_08': archive id, ...} for every as_atk timeline, read from the exe's path table."""
    anchor = _ANCHOR.encode("utf-16-le") + b"\0\0"
    off = exe_data.find(anchor)
    if off < 0:
        return {}
    base = off - FIRST_TIMELINE * _ENTRY
    out = {}
    for aid in range(FIRST_TIMELINE, LAST_TIMELINE + 1):
        raw = exe_data[base + aid * _ENTRY: base + (aid + 1) * _ENTRY]
        path = raw.decode("utf-16-le", "replace").split("\0", 1)[0]
        m = re.fullmatch(r"rom:/as/as_atk_(.+)\.bin", path)
        if m:
            out[m.group(1)] = aid
    return out


def _group(tl: str):
    """'m_06_08' -> 'm_06', 'mb_32b_11' -> 'mb_32b', else None."""
    m = re.match(r"(mb?_[0-9a-z]+)_\d", tl)
    return m.group(1) if m else None


def build(bundle_main, exe_data: bytes | None, npc_param: bytes | None,
          item_name, char_name) -> dict[int, str]:
    """{kind: 'Fireball; Little Mage, Little Wizard +3 (m_06_02)'} for every kind a timeline
    fires. item_name / char_name: id -> name ('' when unknown)."""
    bundle_main = pathlib.Path(bundle_main)
    fired: dict[int, list[str]] = {}
    for p in sorted(bundle_main.glob("as_atk_*.bin")):
        tl = p.stem[len("as_atk_"):]
        try:
            events = asatk.parse(p.read_bytes())
        except Exception:
            continue
        for e in events:
            if e.op == 43:
                k = asatk._s32(e.arg)
                # 0 is the caster's own quick-slot spell / tool, except in the spell timelines
                # themselves, where magic_00 (Fireball) fires row 0
                if (k > 0 or (k == 0 and re.fullmatch(r"magic_[0-7][0-2]", tl))) and tl not in fired.setdefault(k, []):
                    fired[k].append(tl)
    # monster group -> names, through rf3NpcParam +280 (= group base archive - 243)
    group_monsters: dict[str, list[str]] = {}
    if exe_data and npc_param:
        ids = timeline_archive_ids(exe_data)
        lows: dict[str, int] = {}
        for tl, aid in ids.items():
            g = _group(tl)
            if g:
                lows[g] = min(lows.get(g, aid), aid)
        by_base = {aid - FIRST_TIMELINE: g for g, aid in lows.items()}
        try:
            from .nlcl import NlclTable
            t = NlclTable(npc_param)
            for cid in range(t.entry_count):
                g = by_base.get(t.get(cid, 280, "u16"))
                nm = char_name(cid)
                if g and nm and nm != "???" and nm not in group_monsters.setdefault(g, []):
                    group_monsters[g].append(nm)
        except Exception:
            pass
    out = {}
    for k, tls in fired.items():
        spells, groups, others = [], {}, []
        for tl in sorted(tls):
            m = re.fullmatch(r"magic_([0-7])([0-2])", tl)
            g = _group(tl)
            if m:
                nm = item_name(1025 + 3 * int(m.group(1)) + int(m.group(2)))
                if nm and nm not in spells:
                    spells.append(nm)
            elif g and group_monsters.get(g):
                groups.setdefault(g, []).append(tl)
            else:
                others.append(f"timeline {tl}")
        parts, full = list(spells), [f"spell: {s}" for s in spells]
        for g, g_tls in groups.items():
            mons = group_monsters[g]
            who = ", ".join(mons[:2]) + (f" +{len(mons) - 2}" if len(mons) > 2 else "")
            parts.append(f"{who} ({', '.join(g_tls)})")
            full.append(f"{', '.join(mons)} ({', '.join(g_tls)})")
        parts += others
        full += others
        out[k] = "; ".join(parts[:2]) + (f"; +{len(parts) - 2} more" if len(parts) > 2 else "")
        _FULL[k] = "\n".join(full)
    return out


def full_text(kind: int) -> str:
    """Every user of a row, one per line (for a details pane); names_for_game() fills it."""
    return _FULL.get(kind, "")


_FULL: dict[int, str] = {}


def names_for_game(bundle_dir=None) -> dict[int, str]:
    """The names for the selected game folder (cached). Empty when the files are missing."""
    try:
        from . import gamepaths, gamenames, exetables
        bd = pathlib.Path(bundle_dir or gamepaths.bundle_dir())
        main = bd / "bundleMain"
        key = (str(bd), main.stat().st_mtime_ns if main.exists() else 0)
        if key in _CACHE:
            return _CACHE[key]
        try:
            exe = exetables.exe_bytes(bd.parent / "RF4S.exe") if (bd.parent / "RF4S.exe").is_file() \
                else exetables.exe_bytes()
        except Exception:
            exe = None
        npc = main / "rf3NpcParam.bin"
        items = gamenames.table("items")
        chars = gamenames.table("characters")
        res = build(main, exe, npc.read_bytes() if npc.is_file() else None,
                    lambda i: items.get(i, ""), lambda i: chars.get(i, ""))
        _CACHE.clear()
        _CACHE[key] = res
        return res
    except Exception:
        return {}
