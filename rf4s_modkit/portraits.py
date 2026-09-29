"""
portraits.py -- the dialogue portrait face a SetSpeaker cue shows.

A speaker cue (ops 16..75) takes the FACE as argument 0 (Script_VMOp_SetSpeaker
RF4S.exe+0x207F70 -> EmotePortrait_ShowFromDescriptor +0x207370). What it shows depends on
the game mode (verified in RF4S.exe 2026-09-25):

STORY MODE (the main game; everything but Newlywed mode) -- the classic 2D art, for every
speaker slot 0..28. EmotePortrait_ComposeContent (+0x1D9D50) draws two sprites from the row
table at +0x4DA980 (row = speaker slot + 1; the player is row 0 as Lest, 1 as Frey):
  * the body   <NN>_<NAME>_body_<outfit>.texture   (archive body base + outfit)
  * the face   archive (face base + face id)       -> <NN>_<NAME>_face_<nnn>_<...>.texture
So face id N is simply the N-th face file of that character (the 'faces' list below, in
archive order -- the file's own number can differ, e.g. Arthur's later faces). Face ids
255 / 254 are the SP1 / SP2 portraits (the *_face_500_SP1 / *_face_501_SP2 files with their
SP bodies, where the character has them). The first six faces are the same moods for
everyone (normal, angry, crying, smile, surprised, shy); the rest are per-character.

NEWLYWED MODE (save flag 0x40, set only by the title menu's Newlywed entry --
EmotePortrait_SpawnAndAttach +0x1D7810) -- animated E-mote portraits (rom:/emote/*.psbData) for
the player and the twelve candidates. The same face ids go through the character's
translation table (g_emotePortrait_emoteToStringIdTable +0x4DA670) to an E-mote face timeline;
ids 1000..1927 pick face x gesture directly (1000 + face*32 + gesture) and exist only there.

The outfit (swimsuit, pajama, wedding) is not chosen by the script -- the game picks it from
the character's state. Data: refdata/portrait_faces.json.
"""
from __future__ import annotations

import json
import re

from .refdata import refdata_path

SP1_ID, SP2_ID = 255, 254

# mood words used in the face file names
_MOODS = {"NORMAL": "normal", "ANGER": "angry", "CRY": "crying", "SMILE": "smile",
          "SURPRISE": "surprised", "SHY": "shy", "SP1": "special 1 (SP1)", "SP2": "special 2 (SP2)"}

# Newlywed (E-mote) face / gesture timeline names (psb.FACE_TIMELINES / GESTURE_TIMELINES order)
EMOTE_FACE_NAMES = (
    "normal", "angry", "sad", "smile", "surprised", "blush", "special 1 (SP1)", "special 2 (SP2)",
    "joy 1", "joy 2", "joy 3", "anger 1", "anger 2", "anger 3", "sorrow 1", "sorrow 2", "sorrow 3",
    "happy 1", "happy 2", "happy 3", "flushed 1", "flushed 2", "flushed 3",
    "surprise 1", "surprise 2", "surprise 3", "troubled 1", "troubled 2", "troubled 3")
EMOTE_GESTURE_NAMES = (
    "idle", "idle 2", "idle 3", "talk facing right", "talk facing left", "nod", "nod nod", "OK",
    "shake head", "shake head 2", "sigh", "disappointed", "puzzled", "excited", "laugh", "grin",
    "grin 2", "startled", "startled 2", "look right", "look left", "look up", "look down", "huff",
    "recoil", "worried", "act cute", "bashful", "bashful 2", "tremble", "confused", "cheerful")

_DATA = None


def _data():
    global _DATA
    if _DATA is None:
        try:
            raw = json.loads(refdata_path("portrait_faces.json").read_text(encoding="utf-8"))
            _DATA = ({int(k): v for k, v in raw["rows"].items()},
                     {int(k): v for k, v in raw["emote"]["rows"].items()})
        except (OSError, ValueError, KeyError):
            _DATA = ({}, {})
    return _DATA


def row_of(slot: int, lest: bool = True):
    """Portrait row of speaker `slot` (0 = the player), or None past the table."""
    if slot == 0:
        return 0 if lest else 1
    return slot + 1 if 1 <= slot <= 28 else None


def has_portrait(slot: int) -> bool:
    """Story mode: every speaker slot 0..28 has classic portrait art."""
    return row_of(slot) in _data()[0]


def _row(slot, lest=True):
    return _data()[0].get(row_of(slot, lest))


def mood_of(file_name: str):
    """'smile' for '..._face_003_SMILE', None for a numbered face."""
    m = re.search(r"_face_\d{3}(.*)$", file_name or "")
    if not m:
        return None
    for word in reversed([w for w in m.group(1).split("_") if w]):
        if word.upper() in _MOODS:
            return _MOODS[word.upper()]
    return None


def faces(slot: int, lest: bool = True):
    """[(face id, file name, mood name or None)] of the speaker's classic faces, then SP1/SP2
    when the character has those portraits."""
    r = _row(slot, lest)
    if not r:
        return []
    out = [(i, f, mood_of(f)) for i, f in enumerate(r["faces"])]
    for fid, f in ((SP1_ID, r["sp"][0]), (SP2_ID, r["sp"][1])):
        if f and "_face_" in f:
            out.append((fid, f, mood_of(f) or ("special 1 (SP1)" if fid == SP1_ID else "special 2 (SP2)")))
    return out


def face_file(slot: int, face_id: int, lest: bool = True):
    """The face texture (without extension) Story mode shows for `face_id`, or None when
    the id is past the character's face list."""
    r = _row(slot, lest)
    if not r:
        return None
    if face_id in (SP1_ID, SP2_ID):
        f = r["sp"][0 if face_id == SP1_ID else 1]
        if f and "_face_" in f:
            return f
        k = 0 if face_id == SP1_ID else 1          # no SP portrait: the game falls back
        return r["faces"][k] if len(r["faces"]) > k else None
    if 0 <= face_id < len(r["faces"]):
        return r["faces"][face_id]
    return None


def label(slot: int, face_id: int, lest: bool = True):
    """Story-mode name of a face id: 'smile', 'face 12', 'special 1 (SP1)', ... or None."""
    if not has_portrait(slot):
        return None
    if face_id >= 1000:
        e = emote_label(slot, face_id, lest)
        return "Newlywed-only face%s" % (" (%s)" % e if e else "")
    f = face_file(slot, face_id, lest)
    if f is None:
        return "past the face list (%d faces)" % len(_row(slot, lest)["faces"])
    mood = mood_of(f)
    if face_id in (SP1_ID, SP2_ID) and not (mood and mood.startswith("special")):
        return "%s (no SP%d portrait)" % (mood or "face %d" % (face_id != SP1_ID),
                                          1 if face_id == SP1_ID else 2)
    return mood or "face %d" % face_id


def body_file(slot: int, face_id: int = 0, outfit: int = 0, lest: bool = True):
    """The body texture a cue shows (outfit 0 base, 2 swimsuit, 3 pajama, 4 wedding; SP1/SP2
    face ids use the SP bodies where they exist)."""
    r = _row(slot, lest)
    if not r:
        return None
    col = {SP1_ID: 1, SP2_ID: 5}.get(face_id, outfit)
    return r["body"][col] or r["body"][0]


# ---- Newlywed mode (E-mote) --------------------------------------------------------------- #
def has_newlywed(slot: int) -> bool:
    return row_of(slot) in _data()[1]


def emote_decode(slot: int, face_id: int, lest: bool = True):
    """Newlywed mode: (E-mote face row, gesture) for a face id, or None."""
    r = _data()[1].get(row_of(slot, lest))
    if r is None:
        return None
    if face_id == SP1_ID:
        return 6, 0
    if face_id == SP2_ID:
        return 7, 0
    if 0 <= face_id < 1000:
        return (r["faces"][face_id], 0) if face_id < len(r["faces"]) else None
    if 1000 <= face_id < 1928:
        return divmod(face_id - 1000, 32)
    return 0, 0


def emote_label(slot: int, face_id: int, lest: bool = True):
    fg = emote_decode(slot, face_id, lest)
    if fg is None:
        return None
    f, g = fg
    name = EMOTE_FACE_NAMES[f] if 0 <= f < len(EMOTE_FACE_NAMES) else "face %d" % f
    return name if g == 0 else "%s · %s" % (name, EMOTE_GESTURE_NAMES[g] if g < len(EMOTE_GESTURE_NAMES) else g)


def emote_encode(face: int, gesture: int = 0) -> int:
    """Newlywed-only direct id: 1000 + face*32 + gesture."""
    return 1000 + face * 32 + gesture
