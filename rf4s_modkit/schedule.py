"""rf4s_modkit/schedule.py -- NPC daily-schedule itineraries (`rf3Schedule.bin`, archive 15216)
and the spot table they point at (`rf3ScheduleID.bin`, archive 15217, a flat NLCL table).
Read + edit + byte-exact rebuild + JSON round trip.

IDB-verified 2026-09-19 -- loader `ScheduleMng_TaskCtor` RF4S.exe+0x230010, plan builder
`NpcSchedule_PrepareDailyOutfitActionsAndPosition` +0x2301A0, spot picker
`NpcSchedule_PickRandomScheduleSlotByKind` +0x2318E0, time cursor
`NpcSchedule_FindCurrentTimeSliceIndex` +0x22D850, placement `NpcSchedule_PlaceNpcAtSliceWithJitter`
+0x22EAA0, state selector `Schedule_GetNpcStateForToday` +0x229160 (+ `Game_GetDayOfWeek`
+0x19C2B0).  (`Npc_GetCurrentScheduleId` +0x227230, cited by the old docstring, returns the NPC's
current ROOM and never touches this file.)

rf3Schedule.bin (custom binary, not NLCL):
    +0   u16 rows = 48 (NPC id)   +2 u16 cols = 18 (state code)   -- reads as u32 0x00120030
    +4   u32 off_npc_table (=16)  -> rows x u32  per-NPC value: 40 for most, 32 (Daughter 23),
                                    43 (24..27, 41), 0 for NPCs without schedules.  Stored by the
                                    loader but not read by any schedule function (bounded operand
                                    scan of the Npc/Schedule/Nav code); preserved verbatim.
    +8   u32 off_directory (=208) -> rows x cols x {u16 count, u16 start}: cell = npc*cols+state,
                                    (0xFFFF, 0xFFFF) = no schedule for that (npc, state)
    +12  u32 off_slices (=3664)   -> slice stream, 4 B each {u8 time_slot, u8 flags, u16 spot}
    In the shipped file the cells partition the stream in npc-major / state-minor order; build()
    re-lays the stream the same way and recomputes every count/start, so the two index sections
    are always consistent.

  slice.time_slot  15-minute unit from midnight: 24 = 06:00 (day start); values run to 108
                   (= 27:00; hours < 6 are 'next day' in the cursor logic).
  slice.flags      bit0 = randomised departure (the NPC leaves for the NEXT slice somewhere
                   between this slice's time and the next one's).  All 0 in the shipped file.
  slice.spot       a KIND index into rf3ScheduleID: kind k owns records [KIND_PREFIX[k],
                   KIND_PREFIX[k+1]) (g_scheduleSlotKindPrefixTable, RF4S.exe+0x4DCF70, 372 u16,
                   vendored below -- NOT a room id, which is what the pre-2026-09 decoder called
                   it).  A kind with several records is rolled per day, weighted by each record's
                   `weight`.  Kinds >= 328 are the festival / spouse substitutions the plan
                   builder swaps in by itself.
  One (npc, state) schedule holds at most 255 slices (u8 cursor) in ascending time order.

  state code:  0..5  weekday = (calendar day - 1) % 6 (a 6-day cycle in this code path)
               6..11 the same weekday when it rains/snows outdoors (weather 1,3,4; map type
                     attribute bit 0x10 clear)
               12 festival day        13 festival event 21
               14 married (spouse)    15 married date day (event 19)
               16, 17 present in the file for some NPCs; the selector never returns them
                     (scripts can force a state via Script_VMOp_ResetNpcScheduleWithState).

rf3ScheduleID.bin: NLCL, 3898 records x 12 B = the SPOTS (record base = archive + 28):
    +0 u16 room (872-room enum)   +2 i16 x   +4 i16 y   (tile units; << 12 = world Q12)
    +6 u8 facing (x 256 = angle)  +7 u8 action (bit0 -> the plan's 0x200 'act' bit)
    +8 u8 wander (jitter radius, tiles)   +9 u8 weight (pick weight within the kind)
    +10 u8 flags (bit1 = eligible for the 25% kind-0 reroll of 0x2000-flagged NPCs; bit2 SET =
    the spot is never picked unless the calendar state is 1 -- with bit2 clear the spot is
    instead skipped while its map is overcrowded; re-read 2026-09-24, the old note had this
    backwards)   +11 u8 busy (runtime, 0 on disk)
    room/x/y/facing/wander are read by PlaceNpcAtSliceWithJitter, weight/flags/busy by
    PickRandomScheduleSlotByKind; 'action' follows the IDB comment (its bit0 use is verified).
    The picker sums the weights of one kind in a u8 (and walks the running total in a u8), so
    a kind's total weight must stay <= 255 or the roll wraps: spot_weight_problems() checks.

"""
from __future__ import annotations

import json
import struct
from collections import namedtuple

MAGIC = 0x00120030            # = rows 48 | cols 18 << 16
ROWS, COLS = 48, 18
NPC_TABLE_OFF = 16
NO_CELL = 0xFFFF
MAX_SLICES = 255
DAY_START_SLOT = 24

# g_scheduleSlotKindPrefixTable (RF4S.exe+0x4DCF70): kind k -> rf3ScheduleID records
# [KIND_PREFIX[k], KIND_PREFIX[k+1]).  Entry 371 = 3898 = the record count.
KIND_PREFIX = (
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
    30, 40, 50, 60, 69, 77, 86, 100, 110, 122, 130, 138, 146, 156, 167, 178, 186, 195, 202, 210,
    215, 216, 227, 228, 229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 239, 240, 241, 242, 243,
    244, 245, 246, 247, 248, 249, 250, 251, 252, 253, 256, 257, 258, 259, 260, 261, 262, 263, 264,
    265, 266, 267, 268, 269, 270, 271, 272, 273, 274, 275, 276, 277, 333, 369, 402, 418, 420, 421,
    423, 482, 521, 556, 572, 574, 575, 577, 579, 629, 663, 691, 707, 762, 796, 829, 853, 854, 856,
    858, 913, 947, 975, 998, 999, 1001, 1003, 1005, 1048, 1064, 1120, 1155, 1183, 1200, 1201, 1203,
    1205, 1209, 1278, 1331, 1372, 1388, 1390, 1394, 1396, 1411, 1465, 1499, 1530, 1546, 1547, 1548,
    1550, 1551, 1605, 1637, 1653, 1707, 1741, 1770, 1786, 1788, 1789, 1790, 1843, 1876, 1892, 1946,
    1980, 2008, 2024, 2026, 2027, 2029, 2031, 2032, 2034, 2090, 2126, 2154, 2170, 2171, 2231, 2271,
    2307, 2323, 2325, 2327, 2328, 2329, 2383, 2417, 2442, 2458, 2460, 2514, 2548, 2577, 2593, 2595,
    2597, 2599, 2601, 2658, 2692, 2720, 2736, 2737, 2738, 2799, 2833, 2858, 2874, 2875, 2876, 2941,
    2986, 3024, 3040, 3051, 3053, 3055, 3057, 3058, 3114, 3150, 3189, 3211, 3212, 3213, 3214, 3215,
    3216, 3217, 3218, 3219, 3220, 3221, 3222, 3223, 3225, 3243, 3255, 3265, 3282, 3294, 3304, 3318,
    3328, 3338, 3353, 3363, 3366, 3367, 3373, 3377, 3383, 3387, 3394, 3399, 3409, 3419, 3425, 3433,
    3439, 3441, 3447, 3452, 3459, 3467, 3473, 3481, 3486, 3494, 3500, 3508, 3513, 3516, 3524, 3530,
    3532, 3538, 3543, 3552, 3559, 3566, 3567, 3568, 3569, 3570, 3571, 3572, 3573, 3574, 3575, 3576,
    3577, 3578, 3579, 3580, 3581, 3582, 3583, 3584, 3585, 3586, 3587, 3588, 3589, 3590, 3591, 3592,
    3593, 3594, 3595, 3596, 3597, 3598, 3599, 3600, 3601, 3602, 3603, 3604, 3605, 3606, 3607, 3608,
    3609, 3610, 3611, 3612, 3613, 3619, 3651, 3660, 3710, 3744, 3764, 3777, 3829, 3830, 3831, 3867,
    3868, 3869, 3870, 3871, 3872, 3873, 3874, 3875, 3876, 3877, 3878, 3879, 3880, 3881, 3884, 3889,
    3890, 3891, 3892, 3893, 3894, 3895, 3896, 3897, 3898,
)
MAX_KIND = len(KIND_PREFIX) - 2          # 370

STATE_NAMES = {12: "festival", 13: "festival21", 14: "married", 15: "date", 16: "state16", 17: "state17"}
for _d in range(6):
    STATE_NAMES[_d] = f"weekday{_d}"
    STATE_NAMES[6 + _d] = f"rain{_d}"
STATE_BY_NAME = {v: k for k, v in STATE_NAMES.items()}


class ScheduleError(ValueError):
    pass


class Slice(namedtuple("Slice", "slot flags spot")):
    """One itinerary stop: time slot (15-min units), flags (bit0 = random departure), spot kind."""
    __slots__ = ()

    @property
    def room(self):        # legacy alias: the pre-2026-09 decoder mislabelled the kind as a room
        return self.spot

    @property
    def time(self) -> str:
        return slot_to_time(self.slot)


Waypoint = Slice          # legacy name

Spot = namedtuple("Spot", "room x y facing action wander weight flags busy")


def slot_to_time(slot: int) -> str:
    """15-min slot from midnight -> 'HH:MM' (slot 24 = 06:00; 27:00 style past midnight)."""
    return f"{slot // 4:02d}:{(slot % 4) * 15:02d}"


def time_to_slot(text) -> int:
    """'HH:MM' (or a bare slot number) -> 15-min slot; minutes must be a multiple of 15."""
    s = str(text).strip()
    if ":" not in s:
        return int(s, 0)
    h, m = s.split(":", 1)
    h, m = int(h), int(m)
    if m % 15 or not (0 <= m < 60) or not (0 <= h < 64):
        raise ScheduleError(f"time {text!r}: minutes must be 00/15/30/45")
    return h * 4 + m // 15


def state_code(token) -> int:
    """0..17, from a number or a name (weekday0..5, rain0..5, festival, festival21, married, date)."""
    s = str(token).strip().lower()
    if s in STATE_BY_NAME:
        return STATE_BY_NAME[s]
    v = int(s, 0)
    if not (0 <= v < COLS):
        raise ScheduleError(f"state {v} out of range 0..{COLS - 1}")
    return v


def kind_records(kind: int) -> range:
    """The rf3ScheduleID record indices a slice spot (kind) can resolve to."""
    if not (0 <= kind <= MAX_KIND):
        raise ScheduleError(f"spot kind {kind} out of range 0..{MAX_KIND}")
    return range(KIND_PREFIX[kind], KIND_PREFIX[kind + 1])


# ----------------------------------------------------------------------------- #
# rf3ScheduleID spots
# ----------------------------------------------------------------------------- #
SPOT_HEADER = 28
SPOT_SIZE = 12


def load_spots(data: bytes) -> list[Spot]:
    """rf3ScheduleID.bin -> list of Spot records (index = record number)."""
    if data[:4] != b"NLCL":
        raise ScheduleError("rf3ScheduleID.bin is not an NLCL table")
    n = struct.unpack_from("<I", data, 24)[0]
    return [Spot(*struct.unpack_from("<HhhBBBBBB", data, SPOT_HEADER + SPOT_SIZE * i))
            for i in range(n)]


MAX_KIND_WEIGHT = 255   # NpcSchedule_PickRandomScheduleSlotByKind sums a kind's weights in a u8


def spot_weight_problems(spots: list[Spot]) -> list[tuple[int, int]]:
    """[(kind, total weight)] for every kind whose summed spot weight exceeds 255 -- the picker
    (RF4S.exe+0x2318E0) accumulates the weights in a u8, so such a kind rolls wrongly."""
    out = []
    for k in range(MAX_KIND + 1):
        tot = sum(sp.weight for sp in kind_spots(k, spots))
        if tot > MAX_KIND_WEIGHT:
            out.append((k, tot))
    return out


def kind_spots(kind: int, spots: list[Spot]) -> list[Spot]:
    return [spots[i] for i in kind_records(kind) if i < len(spots)]


def describe_kind(kind: int, spots: list[Spot] | None, name_fn=None) -> str:
    """'kind 26 -> Selphia: Airship Way (26) @318,270' or a multi-spot summary."""
    if not spots:
        return f"spot {kind}"
    sp = kind_spots(kind, spots)
    if not sp:
        return f"spot {kind} (no records)"

    def one(s: Spot) -> str:
        nm = (name_fn(s.room) if name_fn else "") or ""
        return f"{nm} ({s.room}) @{s.x},{s.y}" if nm else f"room {s.room} @{s.x},{s.y}"
    if len(sp) == 1:
        return one(sp[0])
    rooms = []
    for s in sp:
        nm = ((name_fn(s.room) if name_fn else "") or f"room {s.room}")
        if nm not in rooms:
            rooms.append(nm)
    return f"{len(sp)} spots (w {'/'.join(str(s.weight) for s in sp)}): " + ", ".join(rooms[:4]) + \
        (f", +{len(rooms) - 4} more" if len(rooms) > 4 else "")


# ----------------------------------------------------------------------------- #
# rf3Schedule.bin
# ----------------------------------------------------------------------------- #
class Schedule:
    """The whole file: `cells[(npc, state)]` -> list[Slice] for every (npc, state) that has a
    schedule (an empty list is a valid, 0-slice schedule; absent = 0xFFFF sentinel)."""

    def __init__(self, cells: dict, npc_table: list[int] | None = None,
                 rows: int = ROWS, cols: int = COLS):
        self.rows, self.cols = rows, cols
        self.npc_table = list(npc_table) if npc_table is not None else [0] * rows
        self.cells = cells

    # ---- parse ----------------------------------------------------------- #
    @classmethod
    def parse(cls, data: bytes) -> "Schedule":
        rows, cols, off_a, off_b, off_d = struct.unpack_from("<HHIII", data, 0)
        if not (0 < rows <= 256 and 0 < cols <= 64) or off_d > len(data):
            raise ScheduleError(f"not an rf3Schedule file (rows={rows} cols={cols})")
        npc_table = list(struct.unpack_from(f"<{rows}I", data, off_a))
        n_slices = (len(data) - off_d) // 4
        stream = [Slice(*struct.unpack_from("<BBH", data, off_d + 4 * i)) for i in range(n_slices)]
        cells = {}
        for npc in range(rows):
            for state in range(cols):
                count, start = struct.unpack_from("<HH", data, off_b + 4 * (npc * cols + state))
                if count == NO_CELL:
                    continue
                if start + count > n_slices:
                    raise ScheduleError(f"npc {npc} state {state}: slices {start}+{count} past EOF")
                cells[(npc, state)] = stream[start:start + count]
        return cls(cells, npc_table, rows, cols)

    # ---- query ----------------------------------------------------------- #
    def get(self, npc: int, state: int) -> list[Slice] | None:
        return self.cells.get((npc, state))

    def ordered_cells(self) -> list[tuple[tuple[int, int], list[Slice]]]:
        """Cells in file order (npc-major, state-minor)."""
        return [(k, self.cells[k]) for k in sorted(self.cells)]

    def npcs(self) -> list[int]:
        return sorted({npc for npc, _s in self.cells})

    # ---- edit ------------------------------------------------------------ #
    def _cell(self, npc: int, state: int, create: bool = False) -> list[Slice]:
        if not (0 <= npc < self.rows) or not (0 <= state < self.cols):
            raise ScheduleError(f"npc {npc} / state {state} out of range")
        lst = self.cells.get((npc, state))
        if lst is None:
            if not create:
                raise ScheduleError(f"npc {npc} has no schedule for state {state}")
            lst = self.cells[(npc, state)] = []
        return lst

    def set_slice(self, npc: int, state: int, idx: int, slot=None, flags=None, spot=None) -> Slice:
        lst = self._cell(npc, state)
        if not (0 <= idx < len(lst)):
            raise ScheduleError(f"slice index {idx} out of range (0..{len(lst) - 1})")
        old = lst[idx]
        new = Slice(old.slot if slot is None else int(slot),
                    old.flags if flags is None else int(flags),
                    old.spot if spot is None else int(spot))
        _check_slice(new)
        lst[idx] = new
        if slot is not None:                 # keep the ascending order the cursor relies on
            lst.sort(key=lambda s: s.slot)
        return new

    def add_slice(self, npc: int, state: int, slot: int, spot: int, flags: int = 0) -> int:
        """Insert a stop keeping ascending time order; returns its index."""
        lst = self._cell(npc, state, create=True)
        new = Slice(int(slot), int(flags), int(spot))
        _check_slice(new)
        if len(lst) >= MAX_SLICES:
            raise ScheduleError(f"a schedule holds at most {MAX_SLICES} slices")
        pos = len(lst)
        for k, s in enumerate(lst):
            if s.slot > new.slot:
                pos = k
                break
        lst.insert(pos, new)
        return pos

    def remove_slice(self, npc: int, state: int, idx: int) -> Slice:
        lst = self._cell(npc, state)
        if not (0 <= idx < len(lst)):
            raise ScheduleError(f"slice index {idx} out of range (0..{len(lst) - 1})")
        return lst.pop(idx)

    def delete_cell(self, npc: int, state: int) -> None:
        self.cells.pop((npc, state), None)

    # ---- build ----------------------------------------------------------- #
    def build(self) -> bytes:
        rows, cols = self.rows, self.cols
        off_a = NPC_TABLE_OFF
        off_b = off_a + 4 * rows
        off_d = off_b + 4 * rows * cols
        out = bytearray(struct.pack("<HHIII", rows, cols, off_a, off_b, off_d))
        out += struct.pack(f"<{rows}I", *self.npc_table)
        directory = bytearray(b"\xff" * (4 * rows * cols))
        stream = bytearray()
        pos = 0
        for (npc, state), lst in self.ordered_cells():
            if len(lst) > MAX_SLICES:
                raise ScheduleError(f"npc {npc} state {state}: {len(lst)} slices > {MAX_SLICES}")
            struct.pack_into("<HH", directory, 4 * (npc * cols + state), len(lst), pos)
            for s in lst:
                _check_slice(s)
                stream += struct.pack("<BBH", s.slot, s.flags, s.spot)
            pos += len(lst)
        if pos > 0xFFFF:
            raise ScheduleError("slice stream exceeds 65535 entries")
        return bytes(out + directory + stream)

    # ---- JSON ------------------------------------------------------------ #
    def to_json(self, spots: list[Spot] | None = None, name_fn=None) -> dict:
        scheds = []
        for (npc, state), lst in self.ordered_cells():
            entry = {"npc": npc, "state": state, "state_name": STATE_NAMES.get(state, str(state)),
                     "slices": []}
            for s in lst:
                d = {"time": slot_to_time(s.slot), "slot": s.slot, "flags": s.flags, "spot": s.spot}
                if spots:
                    d["where"] = describe_kind(s.spot, spots, name_fn)
                entry["slices"].append(d)
            scheds.append(entry)
        return {"format": "rf3Schedule", "rows": self.rows, "cols": self.cols,
                "npc_table": list(self.npc_table), "schedules": scheds}

    @classmethod
    def from_json(cls, d: dict) -> "Schedule":
        if d.get("format") != "rf3Schedule":
            raise ScheduleError("not an rf3Schedule JSON document (format field)")
        rows, cols = int(d.get("rows", ROWS)), int(d.get("cols", COLS))
        npc_table = list(d.get("npc_table") or [0] * rows)
        if len(npc_table) != rows:
            raise ScheduleError(f"npc_table must have {rows} entries")
        cells = {}
        for sc in d.get("schedules", []):
            npc, state = int(sc["npc"]), state_code(sc["state"])
            if (npc, state) in cells:
                raise ScheduleError(f"npc {npc} state {state} listed twice")
            lst = []
            for sl in sc.get("slices", []):
                slot = int(sl["slot"]) if "slot" in sl else time_to_slot(sl["time"])
                s = Slice(slot, int(sl.get("flags", 0)), int(sl["spot"]))
                _check_slice(s)
                lst.append(s)
            cells[(npc, state)] = lst
        return cls(cells, npc_table, rows, cols)

    def dumps(self, **kw) -> str:
        return json.dumps(self.to_json(**kw), indent=1)

    @classmethod
    def loads(cls, text: str) -> "Schedule":
        return cls.from_json(json.loads(text))


def _check_slice(s: Slice) -> None:
    if not (0 <= s.slot <= 255):
        raise ScheduleError(f"time slot {s.slot} must be 0..255 (u8)")
    if not (0 <= s.flags <= 255):
        raise ScheduleError(f"flags {s.flags} must be 0..255")
    if not (0 <= s.spot <= MAX_KIND):
        raise ScheduleError(f"spot kind {s.spot} out of range 0..{MAX_KIND}")


# ----------------------------------------------------------------------------- #
# legacy helpers (kept for the GUI / older callers)
# ----------------------------------------------------------------------------- #
def header(data: bytes) -> dict:
    magic, sec_a, sec_b, data_off = struct.unpack_from("<IIII", data, 0)
    return {"magic": magic, "rows": magic & 0xFFFF, "cols": magic >> 16,
            "section_a": sec_a, "section_b": sec_b, "data_off": data_off}


def waypoints(data: bytes) -> list[Slice]:
    """Every slice of the stream in file order."""
    return [s for _k, lst in Schedule.parse(data).ordered_cells() for s in lst]


def schedules(data: bytes) -> list[list[Slice]]:
    """One list per (npc, state) cell that has a schedule, in file order."""
    return [lst for _k, lst in Schedule.parse(data).ordered_cells()]


def render(data: bytes, name_fn=None, limit: int | None = None, spots: list[Spot] | None = None,
           npc_name_fn=None, only_npc: int | None = None, only_state: int | None = None) -> str:
    """Human-readable itineraries per (npc, state)."""
    sc = Schedule.parse(data)
    cells = [(k, v) for k, v in sc.ordered_cells()
             if (only_npc is None or k[0] == only_npc) and (only_state is None or k[1] == only_state)]
    lines = [f"# rf3Schedule: {len(sc.cells)} schedules ({len(sc.npcs())} NPCs x up to {sc.cols} states), "
             f"{sum(len(v) for v in sc.cells.values())} slices"]
    for i, ((npc, state), lst) in enumerate(cells):
        if limit is not None and i >= limit:
            lines.append(f"... ({len(cells) - limit} more schedules)")
            break
        who = (npc_name_fn(npc) if npc_name_fn else "") or ""
        lines.append(f"npc {npc} {who} state {state} ({STATE_NAMES.get(state, '?')}) -- {len(lst)} stops:")
        for k, s in enumerate(lst):
            fl = "  [random depart]" if s.flags & 1 else (f"  [flags {s.flags:#x}]" if s.flags else "")
            lines.append(f"    {k:>2}  {slot_to_time(s.slot)}  spot {s.spot:>3}  "
                         f"{describe_kind(s.spot, spots, name_fn)}{fl}")
    return "\n".join(lines)
