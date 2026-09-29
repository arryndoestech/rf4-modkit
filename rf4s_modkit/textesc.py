r"""textesc.py -- the editors' backslash notation for the characters game text can't show.

Game text can hold control characters the font layout reads (colours, a vertical shift) and
private-use characters it draws as button icons. None of them can be typed or seen in a text
box, so the editors show and take them as backslash escapes; the file keeps the real
characters. No shipped text contains a backslash, and a real one is written `\\`.

    \red  \blue  \normal       colour 0x01 / 0x02 / 0x03 (what ／ and ＋ turn into)
    \rgb(r,g,b)                0x04 + three values 1-255: any colour
    \up  \down                 0x05 / 0x06: raise / lower what follows by 1/4 of the font size
    \shift(n)                  0x07 + n: lower by n pixels (n = -128..127, not 0; negative raises)
    \base                      0x08: back to the normal baseline
    \btn(a)                    a button icon: a b x y l1 r1 l2 r2 stick right down up left
                               start select dpad (U+E0A0..U+E0C1)
    \u(E0A8)                   any character by its hexadecimal code
    \\                         a backslash

A name ends where the known name does (`\redRED\normal` = red "RED"). The shifts add up until
\base. Values are characters, not bytes, so 128-255 work; 0 would end the line and is refused.
Font layout RF4S.exe+0x1B00F0; in-game test 2026-09-29 (colours, rgb up to 255, the shifts,
the button icons on keyboard).

to_edit(text) -> notation;  from_edit(notation) -> text (raises EscapeError).
from_edit(to_edit(t)) == t for any text.
"""
from __future__ import annotations

BS = "\\"

SIMPLE = {"red": "\x01", "blue": "\x02", "normal": "\x03", "up": "\x05", "down": "\x06", "base": "\x08"}
SIMPLE_TEXT = {"red": "red text", "blue": "blue text", "normal": "normal colour again",
               "up": "raise what follows by 1/4 of the font size",
               "down": "lower what follows by 1/4 of the font size",
               "base": "back to the normal baseline"}
# the first code of each action; the duplicates (U+E0A8 l1 ...) stay \u(....) so they round-trip
BUTTONS = {"a": 0xE0A0, "b": 0xE0A1, "x": 0xE0A2, "y": 0xE0A3, "l1": 0xE0A4, "r1": 0xE0A5,
           "l2": 0xE0A6, "r2": 0xE0A7, "stick": 0xE0AA, "right": 0xE0AB, "down": 0xE0AC,
           "up": 0xE0AD, "left": 0xE0AE, "start": 0xE0B3, "select": 0xE0B4, "dpad": 0xE0C1}
_BUTTON_OF = {v: k for k, v in BUTTONS.items()}
_NAMES = sorted(list(SIMPLE) + ["rgb", "shift", "btn", "u"], key=len, reverse=True)


class EscapeError(ValueError):
    """A bad escape: `pos` is its offset in the notation text."""

    def __init__(self, message, pos=0):
        super().__init__(message)
        self.pos = pos


def _code(ch):
    return BS + "u(%04X)" % ord(ch)


def to_edit(text):
    """The notation of a game text: special characters as escapes, a backslash as \\."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        o = ord(c)
        if c == BS:
            out.append(BS + BS)
        elif o == 4 and i + 3 < n and all(0 < ord(x) < 256 for x in text[i + 1:i + 4]):
            out.append(BS + "rgb(%d,%d,%d)" % tuple(ord(x) for x in text[i + 1:i + 4]))
            i += 4
            continue
        elif o == 7 and i + 1 < n and 0 < ord(text[i + 1]) < 256:
            v = ord(text[i + 1])
            out.append(BS + "shift(%d)" % (v - 256 if v > 127 else v))
            i += 2
            continue
        elif c in SIMPLE.values():
            out.append(BS + next(k for k, v in SIMPLE.items() if v == c))
        elif o in _BUTTON_OF:
            out.append(BS + "btn(%s)" % _BUTTON_OF[o])
        elif (o < 0x20 and c != "\n") or 0xE000 <= o <= 0xF8FF:
            out.append(_code(c))
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _args(s, i, name):
    """The text inside `(...)` right after an escape name at s[i]; (inner, next index)."""
    if i >= len(s) or s[i] != "(":
        raise EscapeError("%s%s needs (…) after it" % (BS, name), i)
    j = s.find(")", i)
    if j < 0:
        raise EscapeError("%s%s( has no closing )" % (BS, name), i)
    return s[i + 1:j].strip(), j + 1


def _int(t, lo, hi, what, pos):
    try:
        v = int(t.strip(), 0)
    except ValueError:
        raise EscapeError("%s: %r is not a number" % (what, t.strip()), pos)
    if not lo <= v <= hi:
        raise EscapeError("%s: %d is out of range (%d..%d)" % (what, v, lo, hi), pos)
    return v


def from_edit(s):
    """The game text of a notation; raises EscapeError for an unknown or bad escape."""
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c != BS:
            out.append(c)
            i += 1
            continue
        if i + 1 < n and s[i + 1] == BS:
            out.append(BS)
            i += 2
            continue
        rest = s[i + 1:]
        if rest.startswith("u("):
            name = "u"
        else:
            name = next((nm for nm in _NAMES if nm != "u" and rest.startswith(nm)), None)
        if name is None:
            word = rest.split()[0] if rest.split() else ""
            raise EscapeError("unknown escape %s%s (write %s%s for a backslash)"
                              % (BS, word[:12], BS, BS), i)
        j = i + 1 + len(name)
        if name in SIMPLE:                              # no (…): a "(" after it is text
            out.append(SIMPLE[name])
            i = j
            continue
        inner, j2 = _args(s, j, name)
        if name == "rgb":
            parts = inner.split(",")
            if len(parts) != 3:
                raise EscapeError("%srgb needs three values: %srgb(255,128,1)" % (BS, BS), i)
            out.append("\x04" + "".join(chr(_int(p, 1, 255, "rgb", i)) for p in parts))
        elif name == "shift":
            v = _int(inner, -128, 127, "shift", i)
            if v == 0:
                raise EscapeError("%sshift(0) would end the line; use %sbase" % (BS, BS), i)
            out.append("\x07" + chr(v & 0xFF))
        elif name == "btn":
            if inner not in BUTTONS:
                raise EscapeError("%sbtn(%s): the buttons are %s" % (BS, inner, " ".join(BUTTONS)), i)
            out.append(chr(BUTTONS[inner]))
        elif name == "u":
            try:
                v = int(inner, 16)
            except ValueError:
                raise EscapeError("%su(%s): write the code in hexadecimal, e.g. %su(E0A8)"
                                  % (BS, inner, BS), i)
            if not 0 <= v <= 0x10FFFF or 0xD800 <= v <= 0xDFFF:
                raise EscapeError("%su(%s) is not a character code" % (BS, inner), i)
            out.append(chr(v))
        i = j2
    return "".join(out)


def check(s):
    """None when `s` is valid notation, else the EscapeError."""
    try:
        from_edit(s)
    except EscapeError as e:
        return e
    return None


def reference():
    """[(escape, what it does)] for the editors' Insert menu and the Text codes reference."""
    rows = [(BS + k, SIMPLE_TEXT[k]) for k in ("red", "blue", "normal")]
    rows.append((BS + "rgb(255,128,1)", "any colour: red, green, blue 1-255"))
    rows += [(BS + k, SIMPLE_TEXT[k]) for k in ("up", "down")]
    rows.append((BS + "shift(4)", "lower what follows by 4 pixels (negative raises)"))
    rows.append((BS + "base", SIMPLE_TEXT["base"]))
    rows += [(BS + "btn(%s)" % k, "the %s button icon (follows the player's controller / keyboard)" % k)
             for k in BUTTONS]
    rows.append((BS + "u(E0A8)", "any character by its hexadecimal code"))
    rows.append((BS + BS, "a backslash"))
    return rows
