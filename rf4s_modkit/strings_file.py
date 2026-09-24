r"""
strings_file.py -- Apple-style `.strings` localisation read / write.

The Muteki engine loads engine-UI text from classic Apple `.strings` files via
MFLocale_LoadFromStringsFile (RF4S.exe+0x259B90). Format:

    // line comment
    /* block comment */
    "key" = "value";
    bareKey = "value";

The game's loader is LINE-BASED, far stricter than Apple's lexer (verified in
MFLocale_LoadFromStringsFile):
  * UTF-8, one statement per line (CR/LF split, each line whitespace-trimmed).
  * A trimmed line starting with `/` is a comment: `//` skips the line; `/*` skips
    lines until one whose FIRST `*/` is its last two characters. An unclosed block
    comment runs off the end of the buffer.
  * Quoted key: up to the next `"` not preceded by a backslash. Bare key: up to the
    first space. The rest of the line, trimmed, must START with exactly `= "`; the
    value is everything between that and the line's last two characters (`";`).
    So `k="v";`, `k = v;`, a trailing `// comment`, or a missing `;` are misread.
  * Entries whose key or value is empty are dropped.
  * Keys are lowercased; key and value go through MFData_decodeBackslashEscapesToUTF8
    (+0x24C4E0): \" \' \\ \b \f \n \r \t \xNN \uNNNN (+ surrogate pairs); any other
    escape is kept verbatim (backslash included); \u0000 and unpaired surrogates vanish.

`parse` reads a file with the game's line algorithm (so it copes with the stock
Localization-en.strings, whose values contain unescaped `"`), keeping the key case
unless `lowercase_keys`; `parse_game` is exactly the dict the game builds
(lowercased keys, the engine's surrogate-pair formula). `parse_lenient` is an
Apple-style lexer (multi-line / multi-statement files, bare values) for files from
other tools, and `game_issues` lists the lines the game will drop or read
differently from it. `dumps` writes one `"key" = "value";` line per entry, which the
game reads back as-is (for non-empty keys and values).
"""
from __future__ import annotations

import pathlib

# the escapes MFData_decodeBackslashEscapesToUTF8 knows; any other `\c` stays `\c`
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "'": "'",
            "b": "\b", "f": "\f"}


class StringsError(Exception):
    pass


def _strip_comments(text: str) -> str:
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c == '"':                      # skip string literal whole (keep it)
            out.append(c)
            i += 1
            while i < n:
                out.append(text[i])
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _hex(s: str) -> int | None:
    try:
        return int(s, 16) if s and all(c in "0123456789abcdefABCDEF" for c in s) else None
    except ValueError:
        return None


def _unescape(s: str, *, game_pairs: bool = False) -> str:
    r"""Decode backslash escapes like MFData_decodeBackslashEscapesToUTF8. A surrogate
    pair `\uD8xx\uDCxx` becomes one code point; `game_pairs=True` reproduces the
    engine's combine formula `((hi & 0x3BF) | 0x40) << 10 | (lo & 0x3FF)`, which is
    only correct when bit 6 of the high surrogate is clear."""
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nx = s[i + 1]
            if nx == "u" and _hex(s[i + 2:i + 6]) is not None and i + 6 <= n:
                cp = _hex(s[i + 2:i + 6])
                i += 6
                if 0xD800 <= cp <= 0xDBFF:
                    lo = _hex(s[i + 2:i + 6]) if s[i:i + 2] == "\\u" else None
                    if lo is None:
                        continue                      # unpaired high surrogate: dropped
                    i += 6
                    if not 0xDC00 <= lo <= 0xDFFF:
                        continue                      # bad pair: both dropped
                    if game_pairs:
                        cp = ((cp & 0x3BF) | 0x40) << 10 | (lo & 0x3FF)
                    else:
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                    if 0xD800 <= cp <= 0xDFFF:
                        continue                      # (game formula) not encodable
                elif cp == 0 or 0xDC00 <= cp <= 0xDFFF:
                    continue                          # \u0000 / lone low surrogate: dropped
                out.append(chr(cp))
                continue
            if nx == "x" and _hex(s[i + 2:i + 4]) is not None and i + 4 <= n:
                out.append(chr(_hex(s[i + 2:i + 4])))
                i += 4
                continue
            if nx in _ESCAPES:
                out.append(_ESCAPES[nx])
            else:
                out.append("\\" + nx)                # unknown escape: kept verbatim
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _read_quoted_or_bare(text: str, i: int):
    """Return (token, next_index) reading a quoted or bare token starting at i."""
    n = len(text)
    while i < n and text[i] in " \t\r\n":
        i += 1
    if i >= n:
        return None, i
    if text[i] == '"':
        i += 1
        start = i
        buf = []
        while i < n:
            if text[i] == "\\" and i + 1 < n:
                buf.append(text[i:i + 2])
                i += 2
                continue
            if text[i] == '"':
                return _unescape("".join(buf)), i + 1
            buf.append(text[i])
            i += 1
        raise StringsError("unterminated string")
    # bare token: read until whitespace, '=' or the ';' terminator (an unquoted
    # value must not swallow its trailing ';' -- parse() then skips the ';' itself).
    start = i
    while i < n and text[i] not in " \t\r\n=;":
        i += 1
    return text[start:i], i


def parse_lenient(text: str, *, lowercase_keys: bool = False) -> dict:
    """Apple-style lexer: comments anywhere, several statements per line, statements
    spanning lines, bare values. NOT what the game does -- see parse()/game_issues()."""
    body = _strip_comments(text)
    result: dict[str, str] = {}
    i, n = 0, len(body)
    while i < n:
        while i < n and body[i] in " \t\r\n;":
            i += 1
        if i >= n:
            break
        key, i = _read_quoted_or_bare(body, i)
        if key is None:
            break
        while i < n and body[i] in " \t\r\n":
            i += 1
        if i >= n or body[i] != "=":
            raise StringsError(f"expected '=' after key {key!r}")
        i += 1
        val, i = _read_quoted_or_bare(body, i)
        while i < n and body[i] in " \t\r\n":
            i += 1
        if i < n and body[i] == ";":
            i += 1
        if lowercase_keys:
            key = key.lower()
        result[key] = val
    return result


def parse(text: str, *, lowercase_keys: bool = False) -> dict:
    """Parse .strings content into an ordered dict {key: value}, line by line exactly as
    MFLocale_LoadFromStringsFile does (lines the game drops are skipped). Keys keep
    their case unless lowercase_keys (the game lowercases them)."""
    result: dict[str, str] = {}
    for _no, line, kind in _game_lines(text):
        if kind == "stmt":
            kv = _game_statement(line, lower=lowercase_keys, game_pairs=False)
            if kv:
                result[kv[0]] = kv[1]
    return result


def load(path, **kw) -> dict:
    return parse(pathlib.Path(path).read_text(encoding="utf-8"), **kw)


def _closes(line: str) -> bool:
    """The loader's block-comment end test: the FIRST `*/` is the line's last two chars."""
    k = line.find("*/")
    return k >= 0 and k == len(line) - 2


def _game_lines(text: str):
    """Yield (line_no, trimmed_line, kind) the way MFLocale_LoadFromStringsFile walks the
    file; kind is 'stmt', 'comment' or 'unclosed' (block comment never closed)."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(raw):
        line = raw[i].strip(" \t")
        no = i + 1
        i += 1
        if not line:
            continue
        if line[0] != "/":
            yield no, line, "stmt"
            continue
        if line[1:2] == "*" and not _closes(line):
            # later lines are NOT trimmed: `*/` must be the untrimmed line's last 2 chars
            while i < len(raw) and not _closes(raw[i]):
                i += 1
            if i >= len(raw):
                yield no, line, "unclosed"
                return
            i += 1
        yield no, line, "comment"


def _game_statement(line: str, *, lower: bool = True, game_pairs: bool = True):
    """(key, value) as the game extracts them from one trimmed line, or None if dropped."""
    if line[0] == '"':
        q = line.find('"', 1)
        while q > 1 and line[q - 1] == "\\":
            q = line.find('"', q + 1)
        if q < 0:
            return None
        key, rest = line[1:q], line[q + 1:].strip(" \t")
    else:
        q = line.find(" ")
        while q > 1 and line[q - 1] == "\\":
            q = line.find(" ", q + 1)
        if q < 0:
            return None
        key, rest = line[:q], line[q + 1:].strip(" \t")
    if not rest.startswith('= "'):
        return None
    value = rest[3:len(rest) - 2]
    if not key or not value:
        return None
    key = _unescape(key, game_pairs=game_pairs)
    return (key.lower() if lower else key), _unescape(value, game_pairs=game_pairs)


def parse_game(text: str) -> dict:
    """Exactly the {lowercased key: value} dict the game builds from this text."""
    result: dict[str, str] = {}
    for _no, line, kind in _game_lines(text):
        if kind == "stmt":
            kv = _game_statement(line)
            if kv:
                result[kv[0]] = kv[1]
    return result


def game_issues(text: str) -> list[str]:
    """Human-readable list of lines the game will drop or read differently from `parse`."""
    issues = []
    for no, line, kind in _game_lines(text):
        if kind == "unclosed":
            issues.append(f"line {no}: block comment never closed (the game reads past the end)")
        elif kind == "stmt":
            kv = _game_statement(line)
            if kv is None:
                issues.append(f"line {no}: not `\"key\" = \"value\";` with a non-empty key and "
                              f"value -- the game drops it: {line[:60]!r}")
            else:
                try:
                    lenient = parse_lenient(line, lowercase_keys=True)
                except StringsError:
                    continue            # only the game's reading exists (e.g. unescaped `"`)
                if lenient != {kv[0]: kv[1]}:
                    issues.append(f"line {no}: the game reads {kv[0]!r} = {kv[1]!r}")
    return issues


def _escape(s: str) -> str:
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        else:
            out.append(ch)
    return "".join(out)


def _escape_key(k: str) -> str:
    e = _escape(k)
    # The game ends a quoted key at the first `"` NOT preceded by a backslash, so a key
    # ending in an (escaped) backslash would swallow its closing quote; spell it \x5c.
    if k.endswith("\\"):
        e = e[:-2] + "\\x5c"
    return e


def dumps(mapping: dict) -> str:
    """Serialise {key: value} to .strings text (UTF-8, standard escapes), one
    `"key" = "value";` line per entry -- the only statement shape the game's line
    parser reads reliably. The game drops entries with an empty key or value."""
    return "".join(f'"{_escape_key(str(k))}" = "{_escape(str(v))}";\n'
                   for k, v in mapping.items())


def save(mapping: dict, path) -> None:
    pathlib.Path(path).write_text(dumps(mapping), encoding="utf-8")
