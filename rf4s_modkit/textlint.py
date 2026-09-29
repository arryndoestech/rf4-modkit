r"""
textlint.py -- check a game text line the way the engine will read it.

The engine rewrites every string before drawing it (Text_PostProcessControlCodes,
RF4S.exe+0x2325E0) and the font layout reads a few control bytes (NFFontLayoutDelegate
vslot 1, +0x1B00F0). This module mirrors that grammar (docs/48-text-control-codes.md) so an
editor can tell, before the text reaches the game:

  error    -- the game can crash or cut the line off. Block the save.
              * ＠‡A,B＠ with no closing fullwidth ＠, no comma, or an alternative longer than
                63 bytes: the handler (+0x232C1A) scans for the ＠ without a bound, copies the
                text before the LAST comma with length (comma - start) -- negative without a
                comma -- into 64-byte stack buffers.
  warning  -- shown wrongly, but harmless.
              * text after a NUL character (the game shows the line up to the NUL;
                trailing NUL padding, as in some shipped Japanese lines, is fine),
              * a ＠ that starts no token the game knows (it is shown as written),
              * a token slot out of range (the token is shown as written),
              * an odd number of ＋ or ／ (the colour runs to the end of the line),
              * a carriage return or another control character the font does not draw.
  info     -- worth knowing.
              * a raw colour / pen control byte (0x01..0x08),
              * a token that reads a text slot no SetVar in the scene writes (it may be set
                earlier, by a choice, or by the game itself -- so only informative).

lint(text) -> [Issue]; errors(text) -> [Issue]; scene_slot_writes(scene, bank) gives the
slots a scene writes, for lint(text, slots=...).
"""
from __future__ import annotations

from dataclasses import dataclass

AT = "＠"                 # ＠
ALL = object()                # "every slot of this kind may be written" (non-constant index)

# base-32 digit of Text_MatchControlCodeAndParseBase32: 0-9, ０-９, then Ａ..Ｖ = 10..31
_DIG = {**{chr(0x30 + i): i for i in range(10)}, **{chr(0xFF10 + i): i for i in range(10)},
        **{chr(0xFF21 + i): 10 + i for i in range(22)}}

# the 24 name patterns at RF4S.exe+0x4DE090 (bodies after ＠); two have 3 digit slots
VILLAGERS = ["ビシュナル", "クローリカ", "ヴォルカノン", "フォルテ", "キール", "バド", "マーガレット",
             "ディラス", "アーサー", "ポコリーヌ", "シャオパイ", "リンファ", "コハク", "エルミナータ",
             "ダグ", "ブロッサム", "ドルチェ", "ジョーンズ", "ナンシー", "レオン", "セルザ"]
PICO = "ピコ"

# (literal body before the slot digit, text-slot kind, highest slot + 1); a body with no
# digit has kind None. Each is followed by the closing ＠.
_SLOTTED = [
    ("アイテム", 1, 16), ("セーブアイテム", 11, 16), ("マップ", 2, 24), ("カレンダー", 9, 16),
    ("キャラ", 0, 16), ("モン", 8, 16), ("その他", 13, 16), ("字", 15, 16), ("小屋", None, 16),
    ("牧場", None, 16), ("金", 4, 32), ("木", 5, 32), ("石", 6, 32), ("王", 7, 32), ("数字", 3, 32),
]
_PLAIN = ["しゅじんこうくん", "ヒーロー", "会話モン", "子供ちゃん", "姫", "私", "字"]
# the bare number ＠X＠: ０-９ = 0..9, Ａ-Ｚ = 10..35, ａ-ｏ = 36..50 (fullwidth only)
_BARE = {**{chr(0xFF10 + i): i for i in range(10)}, **{chr(0xFF21 + i): 10 + i for i in range(26)},
         **{chr(0xFF41 + i): 36 + i for i in range(15)}}
# Korean particle pickers: ＠※XY＠, ＠∀X＠, ＠∂XYZ＠, ＠℃ + 5 + ＠ (fixed lengths)
_KOREAN = {"※": 2, "∀": 1, "∂": 3, "℃": 5}

# control bytes the font layout reads
_CTRL = {1: "red text", 2: "blue text", 3: "normal colour", 4: "colour from the next 3 characters",
         5: "raise by 1/4 of the font size", 6: "lower by 1/4 of the font size",
         7: "lower by the next character's value (signed)", 8: "back to the normal baseline"}

# script opcodes that write each text-slot kind (argument 0 = the slot)
SETVAR_KINDS = {340: (0,), 341: (0,), 343: (1,), 345: (11,), 347: (2,), 348: (2,), 349: (3,),
                351: (4,), 353: (5,), 355: (6,), 357: (7,), 359: (8,), 361: (9,), 362: (9,),
                363: (9,), 364: (10,), 365: (15,), 366: (13, 14)}
KIND_OPS = {}
for _op, _ks in SETVAR_KINDS.items():
    for _k in _ks:
        KIND_OPS.setdefault(_k, []).append(_op)


@dataclass
class Issue:
    level: str          # "error" | "warning" | "info"
    start: int          # character offsets into the line
    end: int
    message: str

    def __str__(self):
        return "%s at %d: %s" % (self.level, self.start, self.message)


@dataclass
class Token:
    text: str
    start: int
    end: int
    kind: int | None = None     # text-slot kind it reads, if any
    slot: int | None = None


def _match_token(t: str, i: int):
    """Token starting at t[i] (a ＠ or @): (Token, None) / (None, why-not)."""
    body = t[i + 1:]
    for name in VILLAGERS + [PICO]:
        if body.startswith(name + AT):
            return Token(t[i:i + len(name) + 2], i, i + len(name) + 2), None
    if len(body) >= 4 and all(c in _DIG for c in body[:3]) and body[3] == AT:
        return Token(t[i:i + 5], i, i + 5), None          # the two unnamed 3-digit slots
    for lit, kind, top in _SLOTTED:
        if body.startswith(lit) and len(body) > len(lit) + 1 and body[len(lit) + 1] == AT:
            d = body[len(lit)]
            if d in _DIG:
                n = _DIG[d]
                end = i + len(lit) + 3
                if n >= top:
                    return None, ("slot %s is out of range for ＠%s…＠ (0-%d)" % (d, lit, top - 1))
                return Token(t[i:end], i, end, kind, n), None
    for lit in _PLAIN:
        if body.startswith(lit + AT):
            end = i + len(lit) + 2
            return Token(t[i:end], i, end, 15 if lit == "字" else None,
                         0 if lit == "字" else None), None
    if len(body) >= 2 and body[0] in _BARE and body[1] == AT:
        return Token(t[i:i + 3], i, i + 3, 3, _BARE[body[0]]), None
    if body[:1] in _KOREAN:
        k = _KOREAN[body[0]]
        if len(body) > k + 1 and body[k + 1] == AT and AT not in body[1:k + 1]:
            return Token(t[i:i + k + 3], i, i + k + 3), None
        return None, "＠%s needs exactly %d character(s) and a closing ＠" % (body[0], k)
    return None, "not a token the game knows; it is shown as written"


def tokens(text: str) -> list[Token]:
    """Every token the game will expand, in order."""
    out, i = [], 0
    while i < len(text):
        if text[i] in (AT, "@") and text[i + 1:i + 2] != "‡":
            tok, _why = _match_token(text, i)
            if tok is not None:
                out.append(tok)
                i = tok.end
                continue
        i += 1
    return out


def _check_gender(text: str, i: int, issues: list):
    """＠‡A,B＠ starting at text[i]. Returns the index after it (or after ‡ on error)."""
    j = i + 2
    close = text.find(AT, j)
    if close < 0:
        issues.append(Issue("error", i, len(text),
                            "＠‡…: no closing fullwidth ＠ -- the game reads past the end of the line"))
        return j
    inner = text[j:close]
    comma = inner.rfind(",")
    if comma < 0:
        issues.append(Issue("error", i, close + 1,
                            "＠‡A,B＠ needs a comma between the Lest and the Frey text -- "
                            "without one the game crashes"))
        return close + 1
    for part, what in ((inner[:comma], "Lest"), (inner[comma + 1:], "Frey")):
        n = len(part.encode("utf-8"))
        if n > 63:
            issues.append(Issue("error", i, close + 1,
                                "the %s text of ＠‡A,B＠ is %d bytes; the game's buffer holds 63"
                                % (what, n)))
    return close + 1


def lint(text: str, slots=None) -> list[Issue]:
    """Issues in one line. `slots` (optional): {kind: set of slots | ALL} a scene writes,
    to flag tokens whose text slot is never set there."""
    issues: list[Issue] = []
    plus = [k for k, c in enumerate(text) if c == "＋"]
    slash = [k for k, c in enumerate(text) if c == "／"]
    for marks, ch, colour in ((plus, "＋", "blue"), (slash, "／", "red")):
        if len(marks) % 2:
            issues.append(Issue("warning", marks[-1], marks[-1] + 1,
                                "odd number of %s: the %s text runs to the end of the line" % (ch, colour)))
    i = 0
    while i < len(text):
        c = text[i]
        o = ord(c)
        if c in (AT, "@"):
            if text[i + 1:i + 2] == "‡":
                i = _check_gender(text, i, issues)
                continue
            tok, why = _match_token(text, i)
            if tok is not None:
                if slots is not None and tok.kind is not None:
                    for k in ((13, 14) if tok.kind == 13 else (tok.kind,)):
                        have = slots.get(k, set())
                        if have is not ALL and tok.slot not in have:
                            ops = ", ".join("op %d" % op for op in KIND_OPS.get(k, []))
                            issues.append(Issue("info", tok.start, tok.end,
                                                "%s reads text slot %d of kind %d, which this scene "
                                                "never sets (%s); it may be set before the scene runs"
                                                % (tok.text, tok.slot, k, ops)))
                            break
                i = tok.end
                continue
            if c == AT and text.strip() != AT:        # ASCII @ is ordinary text when unmatched;
                close = text.find(AT, i + 1, i + 21)  # a lone ＠ is a placeholder. Report the
                end = close + 1 if close > 0 else i + 1  # would-be token once, closing ＠ included
                issues.append(Issue("warning", i, end, "%s: %s" % (text[i:end], why)))
                i = end
                continue
            i += 1
            continue
        if o == 0:
            if text[i:].strip("\x00"):
                issues.append(Issue("warning", i, i + 1,
                                    "NUL character: the game shows the line only up to here"))
            break
        elif o in _CTRL:
            issues.append(Issue("info", i, i + 1, "control byte 0x%02X (%s)" % (o, _CTRL[o])))
        elif o == 0x0D:
            issues.append(Issue("warning", i, i + 1, "carriage return (\\r): use a plain line break"))
        elif o < 0x20 and o != 0x0A:
            issues.append(Issue("warning", i, i + 1, "control character 0x%02X is not drawn" % o))
        i += 1
    issues.sort(key=lambda x: (x.start, x.level))
    return issues


def errors(text: str) -> list[Issue]:
    return [x for x in lint(text) if x.level == "error"]


def format_issues(issues, limit: int = 8) -> str:
    lines = ["• %s: %s" % (x.level, x.message) for x in issues[:limit]]
    if len(issues) > limit:
        lines.append("• … and %d more" % (len(issues) - limit))
    return "\n".join(lines)


def scene_slot_writes(scene, bank) -> dict:
    """{kind: set of slots | ALL} the scene's SetVar opcodes write (argument 0 = slot)."""
    from . import script
    out: dict = {}
    for st in scene.stmts.values():
        kinds = SETVAR_KINDS.get(st.op)
        if not kinds:
            continue
        slot = script.static_arg(bank, st, 0) if st.args else None
        for k in kinds:
            if slot is None or st.op in (362, 363):
                out[k] = ALL
            elif out.get(k) is not ALL:
                out.setdefault(k, set()).add(slot)
    return out


# ---- reference: every code a line can contain ------------------------------------------
# (code, group, what the game shows, kind of the text slot it reads or None). The engine's
# text pass: Text_PostProcessControlCodes (RF4S.exe+0x2325E0) and the font layout's control
# bytes (+0x1B00F0). Slots are read with Globals_LookupChoiceCommitStateSlotByKindId (+0x234D10).
_REFERENCE = [
    ("＋text＋", "markup", "text between two ＋ in blue (each ＋ toggles blue on / off)", None),
    ("／text／", "markup", "text between two ／ in red (each ／ toggles red on / off)", None),
    ("＠<n>＠", "number", "the number in number slot n (n = ０-９, Ａ-Ｚ, ａ-ｏ = 0..50), in blue", 3),
    ("＠数字<n>＠", "number", "the same number, number slot n, in blue", 3),
    ("＠金<n>＠", "number", "a gold amount (slot n); red when the player has less gold", 4),
    ("＠木<n>＠", "number", "a lumber amount (slot n); red when the player has less", 5),
    ("＠石<n>＠", "number", "a material-stone amount (slot n); red when the player has less", 6),
    ("＠王<n>＠", "number", "a Prince Points amount (slot n); red when the player has fewer", 7),
    ("＠キャラ<n>＠", "people", "a character's name from slot n: 0 = the player's name, 22 / 23 = the "
     "child's, else that row of the character-name file", 0),
    ("＠しゅじんこうくん＠", "people", "how the current speaker addresses the player (their nickname "
     "for you; with no speaker, the player's name)", None),
    ("＠ヒーロー＠", "people", "the same as ＠しゅじんこうくん＠", None),
    ("VILLAGERS", "people", None, None),            # one row per villager, see token_reference
    ("＠ピコ＠", "people", "\"Pico\"", None),
    ("＠子供ちゃん＠", "people", "the player's child's name (the child picked by slot kind 10)", 10),
    ("＠姫＠", "people", "\"Prince\" for Lest, \"Princess\" for Frey", None),
    ("＠私＠", "people", "the player's word for \"I\" (Japanese text only)", None),
    ("＠会話モン＠", "people", "the name of the monster being talked to", None),
    ("＠モン<n>＠", "people", "a barn monster's given name (the monster in slot n)", 8),
    ("＠アイテム<n>＠", "things", "an item name (the item id in slot n), in blue", 1),
    ("＠セーブアイテム<n>＠", "things", "an item name (slot n of the saved-item kind), in blue", 11),
    ("＠マップ<n>＠", "things", "a place name (the map id in slot n), in blue", 2),
    ("＠カレンダー<n>＠", "things", "the calendar event on the date in slot n (season × 100 + day), in blue", 9),
    ("＠牧場<n>＠", "things", "the name of farm area n (renamable by the player)", None),
    ("＠小屋<n>＠", "things", "the name of barn n", None),
    ("＠その他<n>＠", "things", "any text line: the file and line stored in slot n (used for nicknames); "
     "a ＠ inside it becomes the player's name", 13),
    ("＠字<n>＠", "things", "a button icon: the private-use character U+E000 + the value in slot n "
     "(U+E0A0.. are the buttons, following the player's controller or keyboard); ＠字＠ = slot 0", 15),
    ("＠‡A,B＠", "grammar", "A when the player is Lest, B for Frey (German / French text); a missing "
     "comma or closing ＠ can crash the game", None),
    ("＠※XY＠", "grammar", "Korean: X after a final consonant, else Y", None),
    ("＠∀X＠", "grammar", "Korean: X after a final consonant, else nothing", None),
    ("＠∂XYZ＠", "grammar", "Korean: XY after a final consonant, else Z", None),
    ("＠℃ABCD＠", "grammar", "Korean: the same with longer alternatives", None),
    ("ESCAPES", "escapes", None, None),              # the textesc notation, see token_reference
]


def token_reference():
    """[(code, group, what the game shows, the instructions that fill its slot, slot kind)]:
    every code a text line can contain, for the editors' Reference. The filling
    instructions are named from the opcode table, so they follow its names."""
    try:
        from . import opcode_meta as _m
        name = _m.mnemonic
    except Exception:
        name = lambda op: "op %d" % op
    try:
        from . import gamenames as _g
        who = lambda cid: _g.name("characters", cid) or "character %d" % cid
    except Exception:
        who = lambda cid: "character %d" % cid
    out = []
    for code, group, shows, kind in _REFERENCE:
        if code == "ESCAPES":                        # characters no one can type: \\red, \\btn(a) ...
            from . import textesc
            for esc, what in textesc.reference():
                grp = "buttons" if esc.startswith(textesc.BS + "btn(") else "escapes"
                out.append((esc, grp, what + " (an editor escape; the file gets the character)", "", None))
            continue
        if code == "VILLAGERS":                      # ビシュナル = character 1 ... セルザ = 21
            for i, body in enumerate(VILLAGERS):
                out.append((AT + body + AT, group, "%s's name as the player calls them (their name, "
                            "or a nickname the player chose)" % who(i + 1), "", None))
            continue
        ops = KIND_OPS.get(kind, []) if kind is not None else []
        setby = ", ".join(sorted({name(op) for op in ops}))
        out.append((code, group, shows, setby, kind))
    return out
