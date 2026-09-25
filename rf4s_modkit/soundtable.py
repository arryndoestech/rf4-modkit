r"""
soundtable.py -- the RF4S sound table (`*_audio_data.bdat`): parse, rebuild, edit, add.

Every sound the engine plays by number -- script ops PlaySound / PlayVoicedSound /
PlaySfxWithNpcRemap / StopVoiceId, the dialogue text blips, menu and battle SFX, music
streams, voice lines -- is a u32 SOUND ID looked up in this table. Three copies ship in
bundleMain: common_audio_data.bdat (541 rows: SE_/SEQ_/STRM_ music + effects),
voice_en_audio_data.bdat (8386 rows: V_ voice lines + STRM_ scene streams) and
voice_jp_audio_data.bdat (same ids; 45 STRM_*_REV rows point at *_REV.ogg files).

File format (all little-endian, all offsets absolute from the start of the file;
verified against SoundCache_ParseBdatEntries, RF4S.exe+0x3D2E60):

    header  u32 count, u32 id_table_off, u32 info_table_off, u32 string_pool_off
    id table   [count] x {u32 sound_id, u32 info_index}
    info table [n]     x 12 bytes {u8 volume, u8 priority, u8 flag0, u8 flag1,
                                   u32 name_off, u32 file_off}
    string pool        NUL-terminated ASCII strings

  The parser walks the id table only; each row's record is info_table[info_index]. There
  is no info count -- the shipped files have one record per row (info_index == row) and
  the pool holds (name, file) for record 0, 1, 2, ... in order. Every section starts on a
  16-byte boundary and the file is zero-padded to a multiple of 16. `SoundTable.build`
  emits exactly that layout, so the three shipped files round-trip byte for byte.

What each field does (every reader of the 120-byte cache record checked):

  volume   byte / 255.0 -> record+0 float. It is the SoLoud play volume
           (Sfx_PlaySoundWithDedupAndVoiceKill RF4S.exe+0x3BCE30 passes it to
           Sfx_PlayViaSoLoudHandle), and Sfx_ApplyVoiceVolume (+0x3BD860) re-applies it
           multiplied by the options slider. 255 = full scale; the table cannot boost.
           Shipped: 32-180 for effects/music, 85-132 for voices.
  priority byte -> record+4 int. NOT a pan: every play passes pan 0. It is the voice
           priority -- SoundEngine_FindActiveVoiceForSound (+0x3BC080) lets a new sound
           take a busy slot only when its priority >= the playing sound's, and
           Sfx_FindOrPreemptVoice (+0x3BEB20) preempts the lowest-priority voice in the
           pool. Shipped: 64 default, 80 for most UI/SE, 10 for ambient loops, 100/110 for
           hits. (A leftover 3DS "pan/param" byte in older notes.)
  flag0    (byte != 0) -> record+8. No reader on PC: the parser stores it and nothing in
           the sound code (cache, loader, player, preempt, tick) reads record+8. It is
           kept and round-tripped; changing it has no effect we could find.
  flag1    (byte != 0) -> record+9, the "exclusive / high class" bit:
             * a flag1 sound always wins a slot over a flag1=0 one and is never cut off by
               one (FindActiveVoiceForSound, FindOrPreemptVoice prefer flag1=0 victims);
             * only flag1 sounds run the kill rules in the player: a base name starting
               with 'V' stops any other playing voice of the same character (the token
               after 'V_' up to the next '_': "Killing other voice %s from character %s"),
               and a base name of the form STRM_ + 3 capitals + a digit (STRM_VZA04...)
               stops any other such scene stream ("Killing other stream %s");
             * replaying a flag1 sound fades out the instance already playing.
           Shipped: 1 for music streams, voices, SEQ_ jingles; 0 for most SE_ effects.
  name     the BASE name -> record+80. SoundCache_GetNameForId (+0x3D3260) returns it;
           it is the key into LoopPoints.plist (bundleMuteki; {loopStart, loopEnd} in
           samples -- set only when both are nonzero), its first letter picks the dedup
           window and the 'V' voice rules. Not always the file stem (the 63
           STRM_MOVIE_* rows, V_PLAM_TITLE_RUNE_EX -> V_PLAM_TITLE_RUNE4.ogg).
  file     the FILE name -> record+16, loaded by Sound_Load (+0x3BC940): a name with a
           '/' is used as a path, a bare name is resolved through the file manager, i.e.
           the startup `Bundle/**` loose-file index (see mbundle.py) and then the mounted
           bundles. One hard-wired swap: SE_SAVE.wav is loaded as SEQ_SAVE.wav.

Decoding (SoLoud Wav loader, RF4S.exe+0x403300 / +0x4034F4): the data is sniffed by
MAGIC, not extension -- 'OggS' = Ogg Vorbis, 'RIFF' = WAV, 'fLaC' = FLAC, anything else
is tried as MP3. So .ogg / .wav / .flac / .mp3 all work; AIFF does not.

Which tables load, and when (SoundCache_LazyInit, RF4S.exe+0x3D3330): once, at the first
sound request: common_audio_data.bdat, then voice_en_audio_data.bdat, both resolved by
bare name (so a copy in Bundle/00_mods/ overrides them). voice_jp_audio_data.bdat is
NEVER loaded -- its path string's only references are its static ctor/dtor. The voice
language switch (rf4spChangeSoundArchive +0x8AF00 -> the archive mounter at
+0x3BE1C0) instead mounts bundleVoiceJP.mbundle or bundleVoiceEN.mbundle, and the EN
table's file names are looked up in whichever is mounted. Edit voice_en for both
languages.

Ids: a u32 hashed with FNV-1a into a std-style hashmap, so ids need NOT be sorted (the
shipped tables are not) and have no range limit. A duplicate id is legal: the later row
wins (the parser re-points the existing node at the newest record), and voice_en wins
over common. Id 0 is never playable (Sfx_PlayById RF4S.exe+0x19B6F0 returns on 0). The
cache vector reserves 9000 records (8927 ship) but grows, so there is no count cap.
Sfx_PlayById applies the VOICE volume slider to ids 16777511..16785895 (0x1000127 +
0x20C0, exactly the shipped voice range) and the SE slider to every other id.

Playback dedup (Sfx_PlaySoundWithDedupAndVoiceKill): replaying the SAME id as the
previous request is skipped inside a window -- 0.25 x clip length for base names that
start with 'V', 0.05 s otherwise ("Attempted to play sound '%s' twice ...").

Adding a brand-new sound (see README / `rf4mod sound add`):
  1. put the audio file (.ogg recommended) anywhere under Bundle/, e.g.
     Bundle/00_mods/SE_MYMOD_BELL.ogg -- its bare file name must be unique;
  2. `rf4mod sound add common_audio_data.bdat auto SE_MYMOD_BELL.ogg -o <out>` and
     install <out> as Bundle/00_mods/common_audio_data.bdat (`rf4mod install`);
  3. restart the game, then play it from a script: PlaySound(<new id>).
"""
from __future__ import annotations

import fnmatch
import os
import pathlib
import struct
from collections.abc import Mapping
from dataclasses import dataclass, replace

TABLE_NAMES = ("common_audio_data.bdat", "voice_en_audio_data.bdat",
               "voice_jp_audio_data.bdat")
# Tables SoundCache_LazyInit actually loads, in load order (later wins on a shared id).
LOADED_TABLES = ("common_audio_data.bdat", "voice_en_audio_data.bdat")

HEADER = struct.Struct("<4I")
ID_ROW = struct.Struct("<2I")
INFO = struct.Struct("<4B2I")
ALIGN = 16
CACHE_RESERVE = 9000                      # SoundCache_LazyInit reserve (0x2328), not a cap
VOICE_SLIDER_IDS = range(0x1000127, 0x1000127 + 0x20C0 + 1)   # Sfx_PlayById voice range
AUDIO_EXTS = (".ogg", ".wav", ".flac", ".mp3")

FIELDS = {
    "volume": "u8, play volume = value/255 (x the options slider); 255 = full scale",
    "priority": "u8, voice priority: a new sound takes a busy slot only if >= the playing one "
                "(shipped 64 default, 80 UI/SE, 10 ambient); not a pan",
    "flag0": "u8 (0/1), stored at record+8, no reader in the PC exe",
    "flag1": "u8 (0/1), exclusive/high class: beats flag1=0 sounds for slots, enables the "
             "'V' same-character voice kill, the STRM_XXX# stream kill and fade-restart",
    "name": "base name: LoopPoints.plist key, 'V' prefix = voice rules + 0.25 x length dedup",
    "file": "audio file name (bare -> Bundle/** index then bundles; with '/' -> path)",
}


class SoundTableError(ValueError):
    pass


@dataclass
class SoundInfo:
    volume: int = 127
    priority: int = 64
    flag0: int = 0
    flag1: int = 0
    name: str = ""
    file: str = ""

    def as_dict(self):
        return {"volume": self.volume, "priority": self.priority, "flag0": self.flag0,
                "flag1": self.flag1, "name": self.name, "file": self.file}


@dataclass
class SoundEntry:
    """One id-table row, resolved: the id plus (a view of) its info record."""
    row: int
    sound_id: int
    info_index: int
    info: SoundInfo

    @property
    def name(self):
        return self.info.name

    @property
    def file(self):
        return self.info.file


def _align(n, a=ALIGN):
    return (n + a - 1) // a * a


def _cstr(data, off):
    if not 0 <= off < len(data):
        raise SoundTableError(f"string offset {off:#x} outside the file")
    end = data.find(b"\0", off)
    if end < 0:
        raise SoundTableError(f"unterminated string at {off:#x}")
    return data[off:end].decode("latin-1")


def _check_str(s, what):
    if not s:
        raise SoundTableError(f"{what} must not be empty")
    try:
        b = s.encode("ascii")
    except UnicodeEncodeError:
        raise SoundTableError(f"{what} {s!r} must be plain ASCII") from None
    if b"\0" in b:
        raise SoundTableError(f"{what} must not contain NUL")
    return s


def _u8(v, what):
    v = int(v)
    if not 0 <= v <= 255:
        raise SoundTableError(f"{what} {v} out of range 0..255")
    return v


class SoundTable:
    """A parsed `*_audio_data.bdat`. `rows` = [(sound_id, info_index)] in file order,
    `infos` = the info records. Edits keep one record per row, like the shipped files."""

    def __init__(self, rows=None, infos=None, source=None):
        self.rows = [list(r) for r in (rows or [])]
        self.infos = list(infos or [])
        self.source = source

    # ---------------------------------------------------------------- I/O
    @classmethod
    def parse(cls, data: bytes, source=None) -> "SoundTable":
        data = bytes(data)
        if len(data) < HEADER.size:
            raise SoundTableError("file too short for the 16-byte header")
        count, id_off, info_off, pool_off = HEADER.unpack_from(data, 0)
        if id_off + ID_ROW.size * count > len(data):
            raise SoundTableError(f"id table ({count} rows at {id_off:#x}) runs past the file")
        rows = [list(ID_ROW.unpack_from(data, id_off + ID_ROW.size * i)) for i in range(count)]
        n_info = max((r[1] for r in rows), default=-1) + 1
        if info_off + INFO.size * n_info > len(data):
            raise SoundTableError(f"info table ({n_info} records at {info_off:#x}) runs past the file")
        infos = []
        for j in range(n_info):
            vol, pri, f0, f1, name_off, file_off = INFO.unpack_from(data, info_off + INFO.size * j)
            infos.append(SoundInfo(vol, pri, f0, f1, _cstr(data, name_off), _cstr(data, file_off)))
        t = cls(rows, infos, source)
        t._header = (count, id_off, info_off, pool_off)
        return t

    @classmethod
    def load(cls, path) -> "SoundTable":
        p = pathlib.Path(path)
        return cls.parse(p.read_bytes(), source=p)

    def build(self) -> bytes:
        count = len(self.rows)
        for sid, idx in self.rows:
            if not 0 <= idx < len(self.infos):
                raise SoundTableError(f"id {sid} points at missing info record {idx}")
            if not 0 <= sid <= 0xFFFFFFFF:
                raise SoundTableError(f"sound id {sid} is not a u32")
        id_off = HEADER.size                                   # 16: already aligned
        info_off = _align(id_off + ID_ROW.size * count)
        pool_off = _align(info_off + INFO.size * len(self.infos))
        pool = bytearray()
        recs = bytearray()
        for inf in self.infos:
            name_o = pool_off + len(pool)
            pool += inf.name.encode("latin-1") + b"\0"
            file_o = pool_off + len(pool)
            pool += inf.file.encode("latin-1") + b"\0"
            recs += INFO.pack(_u8(inf.volume, "volume"), _u8(inf.priority, "priority"),
                              _u8(inf.flag0, "flag0"), _u8(inf.flag1, "flag1"), name_o, file_o)
        out = bytearray(HEADER.pack(count, id_off, info_off, pool_off))
        for sid, idx in self.rows:
            out += ID_ROW.pack(sid, idx)
        out += bytes(info_off - len(out)) + recs
        out += bytes(pool_off - len(out)) + pool
        out += bytes(_align(len(out)) - len(out))
        return bytes(out)

    def save(self, path):
        pathlib.Path(path).write_bytes(self.build())

    # ---------------------------------------------------------------- queries
    def __len__(self):
        return len(self.rows)

    def entries(self):
        return [SoundEntry(i, sid, idx, self.infos[idx]) for i, (sid, idx) in enumerate(self.rows)]

    def effective(self) -> dict:
        """{sound_id: SoundEntry} as the game sees it (a later duplicate row wins)."""
        return {e.sound_id: e for e in self.entries()}

    def get(self, sound_id):
        return self.effective().get(int(sound_id))

    def lookup(self, key):
        """Entry for an id (int / '0x..' / decimal string) or an exact base/file name
        (case-insensitive). None when absent."""
        sid = _as_id(key)
        if sid is not None:
            return self.get(sid)
        k = str(key).lower()
        for e in reversed(self.entries()):
            if e.name.lower() == k or e.file.lower() == k:
                return e
        return None

    def search(self, pattern):
        """Entries whose base or file name matches a glob (or contains the text)."""
        pat = str(pattern).lower()
        glob = any(c in pat for c in "*?[")
        out = []
        for e in self.entries():
            hay = (e.name.lower(), e.file.lower())
            if (any(fnmatch.fnmatchcase(h, pat) for h in hay) if glob
                    else any(pat in h for h in hay)) or str(e.sound_id) == pat:
                out.append(e)
        return out

    def duplicates(self):
        seen, dup = {}, []
        for e in self.entries():
            if e.sound_id in seen:
                dup.append((seen[e.sound_id], e))
            seen[e.sound_id] = e
        return dup

    def free_id(self, others=()):
        """A fresh id: one above the largest id in this table and in `others`."""
        ids = [r[0] for r in self.rows]
        for t in others:
            ids += [r[0] for r in t.rows]
        return max(ids, default=0x1000000 - 1) + 1

    # ---------------------------------------------------------------- edits
    def _row_for(self, sound_id):
        sid = int(sound_id)
        for i in range(len(self.rows) - 1, -1, -1):          # last row = the effective one
            if self.rows[i][0] == sid:
                return i
        raise SoundTableError(f"sound id {sid} is not in this table")

    def _own_info(self, row):
        """The row's info record, split off first if another row shares it."""
        idx = self.rows[row][1]
        if sum(1 for r in self.rows if r[1] == idx) > 1:
            self.infos.append(replace(self.infos[idx]))
            idx = len(self.infos) - 1
            self.rows[row][1] = idx
        return self.infos[idx]

    def set(self, sound_id, **fields) -> SoundInfo:
        """Change volume / priority / flag0 / flag1 / name / file of one id."""
        bad = set(fields) - set(FIELDS)
        if bad:
            raise SoundTableError(f"unknown field(s) {sorted(bad)}; known: {list(FIELDS)}")
        inf = self._own_info(self._row_for(sound_id))
        for k, v in fields.items():
            if v is None:
                continue
            if k in ("name", "file"):
                setattr(inf, k, _check_str(str(v), k))
            else:
                setattr(inf, k, _u8(v, k))
        return inf

    def rename(self, sound_id, file, name=None) -> SoundInfo:
        """Point an id at another audio file (and optionally a new base name)."""
        return self.set(sound_id, file=file, name=name)

    def add(self, sound_id, file, name=None, volume=127, priority=64, flag0=0, flag1=0,
            replace_existing=False) -> SoundEntry:
        """Append a new id row + info record. `name` defaults to the file stem."""
        sid = int(sound_id)
        if not 0 <= sid <= 0xFFFFFFFF:
            raise SoundTableError(f"sound id {sid} is not a u32")
        if sid == 0:
            raise SoundTableError("sound id 0 is never played (Sfx_PlayById ignores it)")
        _check_str(file, "file")
        name = _check_str(name or os.path.splitext(os.path.basename(file.replace("\\", "/")))[0], "name")
        if any(r[0] == sid for r in self.rows):
            if not replace_existing:
                raise SoundTableError(f"sound id {sid} already exists (use set/rename, or replace)")
            self.remove(sid)
        self.infos.append(SoundInfo(_u8(volume, "volume"), _u8(priority, "priority"),
                                    _u8(flag0, "flag0"), _u8(flag1, "flag1"), name, file))
        self.rows.append([sid, len(self.infos) - 1])
        return self.entries()[-1]

    def remove(self, sound_id) -> int:
        """Drop every row of an id; unreferenced info records are dropped and re-indexed.
        Returns the number of rows removed."""
        sid = int(sound_id)
        before = len(self.rows)
        self.rows = [r for r in self.rows if r[0] != sid]
        if len(self.rows) == before:
            raise SoundTableError(f"sound id {sid} is not in this table")
        used = sorted({r[1] for r in self.rows})
        remap = {old: new for new, old in enumerate(used)}
        self.infos = [self.infos[o] for o in used]
        for r in self.rows:
            r[1] = remap[r[1]]
        return before - len(self.rows)

    # ---------------------------------------------------------------- checks
    def problems(self, others=()):
        """[(severity, message)] for things the engine would trip over or ignore."""
        out = []
        for first, later in self.duplicates():
            out.append(("warning", f"id {later.sound_id} has more than one row "
                                   f"({first.file} / {later.file}); the game keeps the LATER row"))
        names = {}
        for e in self.entries():
            if e.sound_id == 0:
                out.append(("info", f"row {e.row}: id 0 ({e.file}) is never played"))
            ext = os.path.splitext(e.file)[1].lower()
            if ext not in AUDIO_EXTS:
                out.append(("warning", f"id {e.sound_id}: file {e.file!r} is not "
                                       f".ogg/.wav/.flac/.mp3 (decoded by magic; AIFF fails)"))
            names.setdefault(e.name.lower(), []).append(e.sound_id)
        for nm, ids in names.items():
            if len(set(ids)) > 1:
                out.append(("info", f"base name {nm!r} is shared by ids {sorted(set(ids))} "
                                    "(LoopPoints / name lookups see one name)"))
        total = len(self.rows) + sum(len(t.rows) for t in others)
        if total > CACHE_RESERVE:
            out.append(("info", f"{total} loaded rows > the {CACHE_RESERVE}-record reserve: "
                                "fine (the cache grows), noted for completeness"))
        return out


# -------------------------------------------------------------------- helpers
def _as_id(key):
    if isinstance(key, int):
        return key
    s = str(key).strip()
    try:
        return int(s, 0)
    except ValueError:
        return None


def describe(entry: SoundEntry, table_name="") -> str:
    i = entry.info
    lines = [f"id {entry.sound_id} (0x{entry.sound_id:08X})" + (f"  [{table_name}]" if table_name else ""),
             f"  file      {i.file}",
             f"  name      {i.name}",
             f"  volume    {i.volume}  (= {i.volume / 255:.3f})",
             f"  priority  {i.priority}",
             f"  flag0     {i.flag0}  (no reader on PC)",
             f"  flag1     {i.flag1}  ({'exclusive / high class' if i.flag1 else 'normal'})",
             f"  slider    {'voice' if entry.sound_id in VOICE_SLIDER_IDS else 'sound effects'}",
             f"  row {entry.row}, info record {entry.info_index}"]
    return "\n".join(lines)


def default_bundle_root():
    """The game copy's Bundle folder (rf4s_modkit.gamepaths), or None."""
    from . import gamepaths
    return gamepaths.find_bundle_dir()


def find_table(name, bundle_root=None):
    """Path of a sound table the way the game would pick it: a loose copy in
    Bundle/00_mods/ (any depth) wins over bundleMain's. None when absent."""
    root = pathlib.Path(bundle_root) if bundle_root else default_bundle_root()
    if root is None:
        return None
    mods = root / "00_mods"
    if mods.is_dir():
        for p in sorted(mods.rglob(name)):
            if p.is_file():
                return p
    p = root / "bundleMain" / name
    return p if p.is_file() else None


def load_tables(bundle_root=None, names=TABLE_NAMES):
    """{table name: SoundTable} for the tables found (missing ones are skipped)."""
    out = {}
    for n in names:
        p = find_table(n, bundle_root)
        if p is not None:
            try:
                out[n] = SoundTable.load(p)
            except (OSError, SoundTableError):
                pass
    return out


def find_all(query, tables):
    """Search every table: [(table name, entry, is_effective_in_game)]. An id query
    returns that id's row(s); a text query matches base/file names (glob or substring).
    is_effective = the row the running game resolves (voice_jp is never loaded)."""
    sid = _as_id(query)
    eff = {}
    for n in LOADED_TABLES:
        if n in tables:
            for k, e in tables[n].effective().items():
                eff[k] = (n, e.row)
    hits = []
    for n, t in tables.items():
        rows = [e for e in t.entries() if e.sound_id == sid] if sid is not None else t.search(query)
        for e in rows:
            hits.append((n, e, eff.get(e.sound_id) == (n, e.row)))
    return hits


class LazySoundLabels(Mapping):
    """{sound id: (file name, description)} for opcode_meta.ENUM_ARG_VALUES, loaded from
    the game's own tables on first use. Empty (falsy) when the bundle is absent, so the
    listing just shows the number."""

    def __init__(self, bundle_root=None):
        self._root = bundle_root
        self._d = None

    def _load(self):
        if self._d is None:
            d = {}
            try:
                tables = load_tables(self._root, LOADED_TABLES)
            except Exception:
                tables = {}
            for n in LOADED_TABLES:
                if n in tables:
                    for sid, e in tables[n].effective().items():
                        if sid:
                            d[sid] = (e.file, f"{e.name} ({n}, vol {e.info.volume}, "
                                              f"priority {e.info.priority})")
            self._d = d
        return self._d

    def __getitem__(self, k):
        return self._load()[k]

    def __iter__(self):
        return iter(self._load())

    def __len__(self):
        return len(self._load())

    def __contains__(self, k):
        return k in self._load()

    def reset(self, bundle_root=None):
        self._root, self._d = bundle_root, None


SOUND_LABELS = LazySoundLabels()


def sound_label(sound_id):
    """File name of a sound id from the game's loaded tables, or None."""
    e = SOUND_LABELS.get(sound_id)
    return e[0] if e else None
