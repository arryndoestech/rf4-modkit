"""How the cutscene editor presents one action argument, for the Add-an-instruction form
(toolbox) and the Inspector alike:

  * a short label (the table's argument name, not its whole explanation);
  * help text in game terms -- engine internals (RF4S.exe offsets, g_ tables, handler
    names, "corpus") are left to the Reference window;
  * its unit: seconds for the timers (Wait counts 12000 per second, the fades 6000, the
    shake and BlackScreen 60), so a field can show "= 0.5 s" and accept "0.5 s";
  * the values to offer: named values for the units that have them (compass directions,
    fade colours, turn speeds, camera distance), then the values the shipped game passes
    most often (refdata/script_arg_common.json, gen_arg_common.py);
  * the value a new statement starts with: the shipped game's most common one.

`wait_after(op)` names the wait a fade / walk / turn / shake is normally followed by (the
op descriptions say "follow with WaitForFade" and so on).
"""
from __future__ import annotations

import json
import re

from rf4s_modkit import opcode_meta as meta
from rf4s_modkit import script
from rf4s_modkit.refdata import refdata_path

# ---- the shipped game's common values -------------------------------------------------- #
_COMMON = None


def common_values(op, i):
    """[(value, statements)] -- the constants the shipped rf3.mc passes as argument i of
    `op`, most used first ([] when the game never passes a constant there)."""
    global _COMMON
    if _COMMON is None:
        try:
            raw = json.loads(refdata_path("script_arg_common.json").read_text(encoding="utf-8"))["ops"]
            _COMMON = {int(k): v for k, v in raw.items()}
        except (OSError, ValueError, KeyError):
            _COMMON = {}
    args = _COMMON.get(op) or []
    return [tuple(x) for x in args[i]] if i < len(args) else []


# ---- units ------------------------------------------------------------------------------ #
class Unit:
    """A timer argument: `per_second` raw units make one second."""

    def __init__(self, per_second, what):
        self.per_second = per_second
        self.what = what                        # "12000 = 1 s" style note for the help

    def describe(self, raw):
        """'0.5 s' for a raw value (None for a non-number)."""
        try:
            v = int(raw, 0) if isinstance(raw, str) else int(raw)
        except (TypeError, ValueError):
            return None
        s = v / self.per_second
        return ("%g s" % round(s, 3)) if v else "immediate"

    _SECONDS = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)\s*$", re.I)

    def parse(self, text):
        """Raw units for '1.5 s' / '1.5s' / '1.5 seconds'; None for anything else."""
        m = self._SECONDS.match(text or "")
        return int(round(float(m.group(1)) * self.per_second)) if m else None


# keyed by the argument's "type" in opcode_table.json; each one's values text says the rate
UNITS = {
    "time units": Unit(12000, "12000 = 1 second"),          # Wait
    "1/100 frames": Unit(6000, "6000 = 1 second"),          # FadeScreen
    "fade units": Unit(6000, "6000 = 1 second"),            # FadeScreenToClear
    "frames": Unit(60, "60 = 1 second"),                    # ShakeCamera, BlackScreen
}

# named values for the unit-like types, in game terms (from each type's values text)
_COMPASS = [(0, "facing down (toward the camera)"), (45, "down-right"), (90, "right"),
            (135, "up-right"), (180, "up (away from the camera)"), (225, "up-left"),
            (270, "left"), (315, "down-left")]
_EASE = [(0, "instantly"), (1, "fast"), (2, "smooth"), (3, "slow"), (4, "slower")]
NAMED = {
    "degrees": _COMPASS,
    "shift": _EASE,
    "turn ease shift": _EASE,
    "signed 1/16 steps": [(-16, "black"), (16, "white"), (-8, "half black"), (8, "half white"),
                          (0, "clear (no overlay)")],
    "camera distance": [(0, "the normal view"), (200, "closer"), (400, "close")],
}


# ---- help text --------------------------------------------------------------------------- #
_INTERNAL = re.compile(r"RF4S\.exe|\+0x[0-9A-Fa-f]{3,}|\bg_\w+|\b[A-Z][A-Za-z0-9]+_[A-Z]\w+|"
                       r"\bFUN_\w+|\bIDB\b|\bhandler\b|\btag[34]\b|\b\d{4}-\d{2}-\d{2}\b")


def clean_help(text):
    """`text` without the reverse-engineering notes: parentheses and sentences that name
    exe offsets, g_ tables, handler functions or dates go; 'corpus' becomes 'the game's
    scripts'; 'seen in game' notes go (the field already says verified)."""
    if not text:
        return ""
    t = text
    for _ in range(3):                                      # nested parentheses, inner first
        t = re.sub(r"\s*\((?:[^()]*)\)",
                   lambda m: "" if (_INTERNAL.search(m.group(0)) or
                                    re.search(r"seen in game|corpus|via ", m.group(0))) else m.group(0), t)
    parts = re.split(r"(?<=[.;])\s+", t)
    t = " ".join(p for p in parts if not _INTERNAL.search(p))
    t = re.sub(r"\bthe corpus\b|\bcorpus\b", "the game's scripts", t)
    t = re.sub(r"\s+([,.;])", r"\1", re.sub(r"\s{2,}", " ", t)).strip(" ;,")
    return t


# ---- the spec ------------------------------------------------------------------------------- #
class ArgSpec:
    """kind: 'enum' | 'actor' | 'map' | 'item' | 'face' | 'number' (see module doc)."""

    def __init__(self, label, help_, kind, options, default, unit=None, raw_help=""):
        self.label = label
        self.help = help_
        self.kind = kind
        self.options = options                  # [(display, token)]
        self.default = default                  # token
        self.unit = unit
        self.raw_help = raw_help                # the table's full text (tooltips)

    def token(self, text):
        """The listing token for what the user typed or picked: a picked option's token, a
        time typed in seconds converted to raw units, else the text as is."""
        t = (text or "").strip()
        opts = dict(self.options)
        if t in opts:
            return opts[t]
        if self.unit is not None:
            raw = self.unit.parse(t)
            if raw is not None:
                return str(raw)
        return t

    def note(self, token):
        """A live note for the current value: '= 0.5 s', '= facing right', or None."""
        tok = (token or "").strip()
        if self.unit is not None:
            d = self.unit.describe(tok)
            if d:
                return "= " + d
        for disp, t in self.options:
            if t == tok and "  " in disp:
                return "= " + disp.split("  ", 1)[1]
        return None


def _row_arg(op, i):
    r = meta.table_row(op) or {}
    args = r.get("args") or []
    if args:
        return args[min(i, len(args) - 1)], i >= len(args)
    names = meta.arg_names(op)
    return {"name": (names[i] if i < len(names) else "arg%d" % i).split(" (")[0]}, False


def portrait_slot_of_arg(op, i):
    """The arg index of the character whose face argument `i` is, or 'op' when the
    opcode itself names the speaker (SetSpeaker family) -- None for non-face args."""
    a, _rep = _row_arg(op, i)
    if (a.get("type") or "").lower() != "expression id":
        return None
    if script.portrait_speaker_slot(op) is not None:
        return "op"
    r = meta.table_row(op) or {}
    for j, b in enumerate(r.get("args") or []):
        if (b.get("type") or "").lower().startswith("char id"):
            return j
    return None


def spec(op, i):
    """The ArgSpec of argument i of action `op` (the last named argument repeats)."""
    from . import toolbox                                   # pickers (character / map / item lists)
    a, repeated = _row_arg(op, i)
    name = (a.get("name") or "arg").split(" (")[0]
    label = name if not repeated else "%s #%d" % (name, i - len((meta.table_row(op) or {}).get("args") or []) + 2)
    typ = (a.get("type") or "").lower()
    raw_help = ((a.get("type") or "") + (": " + a["values"] if a.get("values") else "")).strip()
    help_ = clean_help(a.get("values") or "")
    unit = UNITS.get(typ)
    if unit is not None:
        if unit.what not in help_ and "= 1 s" not in help_:
            help_ = help_ + ("; " if help_ else "") + unit.what
        help_ += " — you can type seconds, e.g. 1.5 s"
    common = common_values(op, i)
    kind, opts, default = toolbox._arg_spec(op, i, a)
    if kind == "enum":
        by_num = {}
        for d, t in opts:
            try:
                by_num[int(d.split()[0], 0)] = t
            except (ValueError, IndexError):
                pass
        top = next((by_num[v] for v, _n in common if v in by_num), None)
        if typ.startswith(("char id", "npc char id", "item id")) or "char id" in typ:
            top = by_num.get(0, default)                    # the player / no item: not one game's pick
        elif "emote" in typ or re.search(r"\b0 = (none|nothing|off|no)\b", a.get("values") or ""):
            top = by_num.get(0, "0")                        # an optional extra (emote, voice): none
        return ArgSpec(label, help_, "enum", opts, top if top is not None else default,
                       raw_help=raw_help)
    if kind in ("actor", "map", "item"):
        return ArgSpec(label, help_, kind, opts, default, raw_help=raw_help)
    # numbers: named values first, then what the game passes most often
    options, seen = [], set()

    def add(v, words):
        if v in seen:
            return
        seen.add(v)
        extra = []
        if unit is not None:
            d = unit.describe(v)
            if d:
                extra.append(d)
        if words:
            extra.append(words)
        options.append(("%d  %s" % (v, " · ".join(extra)) if extra else str(v), str(v)))
    for v, words in NAMED.get(typ, ()):
        add(v, words)
    kind = "face" if portrait_slot_of_arg(op, i) is not None else "number"
    if typ.startswith("script units") or kind == "face":
        common = []                     # a position / face only means something on its map / character
    for v, n in common:
        add(v, "used %d× in the game" % n if v not in dict(NAMED.get(typ, ())) else "")
    default_v = common[0][0] if common else (NAMED[typ][0][0] if typ in NAMED else 0)
    return ArgSpec(label, help_, kind, options, str(default_v), unit=unit, raw_help=raw_help)


# ---- waits ----------------------------------------------------------------------------------- #
# op mnemonic -> (wait mnemonic, argument of the op the wait repeats or None); from the op
# descriptions ("Pair with WaitActorMoveDone", "follow with WaitForFade", ...). ShakeCamera
# with duration 0 shakes until stopped, so its wait is only offered for a set duration.
WAITS = {
    "WalkActorTo": ("WaitActorMoveDone", 0),
    "TurnActorToAngle": ("WaitActorMoveDone", 0),
    "TurnActorToFaceTarget": ("WaitActorMoveDone", 0),
    "TurnPlayerToAngle": ("WaitPlayerMoveDone", None),
    "FadeScreen": ("WaitForFade", None),
    "FadeScreenToClear": ("WaitForFade", None),
    "ShakeCamera": ("WaitForPlayerEffect", None),
}


def wait_after(op):
    """(wait mnemonic, copied arg index or None) for `op`, or None."""
    return WAITS.get(meta.mnemonic(op))


def wait_line(op, arg_tokens):
    """The listing line of the wait that follows `op` with these argument tokens, or None
    (no wait for this op, or ShakeCamera with no time limit)."""
    w = wait_after(op)
    if w is None:
        return None
    mn, ai = w
    if mn == "WaitForPlayerEffect" and len(arg_tokens) > 1 and arg_tokens[1].strip() in ("0", ""):
        return None
    if ai is None:
        return "%s()" % mn
    return "%s(%s)" % (mn, arg_tokens[ai] if ai < len(arg_tokens) else "0")
