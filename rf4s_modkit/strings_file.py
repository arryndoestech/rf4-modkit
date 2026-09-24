r"""
strings_file.py -- Apple-style `.strings` localisation read / write.

The Muteki engine loads engine-UI text from classic Apple `.strings` files via
MFLocale_LoadFromStringsFile (RF4S.exe+0x19B90). Format:

    // line comment
    /* block comment */
    "key" = "value";
    bareKey = "value";

Lexer behaviour (verified against the loader, docs/09 §8b):
  * `//...EOL` and `/* ... */` (multi-line) comments are stripped.
  * key/value separated by `= "` ; statement ends with `";`.
  * keys are case-folded to lowercase on load (lookups are case-insensitive).
  * both key and value go through backslash-escape -> UTF-8 decoding
    (\n \t \" \\ \uNNNN \xNN, surrogate pairs).

This parser preserves insertion order and returns an ordered dict; the writer emits
UTF-8 with the standard escapes, suitable for the engine to re-read.
"""
from __future__ import annotations

import pathlib

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "'": "'", "0": "\0"}


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


def _unescape(s: str) -> str:
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nx = s[i + 1]
            if nx == "u" and i + 5 < n:      # need 4 hex digits at i+2..i+5 (i+6 <= n)
                out.append(chr(int(s[i + 2:i + 6], 16)))
                i += 6
                continue
            if nx == "x" and i + 3 < n:      # need 2 hex digits at i+2..i+3 (i+4 <= n)
                out.append(chr(int(s[i + 2:i + 4], 16)))
                i += 4
                continue
            out.append(_ESCAPES.get(nx, nx))
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


def parse(text: str, *, lowercase_keys: bool = False) -> dict:
    """Parse .strings content into an ordered dict {key: value}."""
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


def load(path, **kw) -> dict:
    return parse(pathlib.Path(path).read_text(encoding="utf-8"), **kw)


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


def dumps(mapping: dict) -> str:
    """Serialise {key: value} to .strings text (UTF-8, standard escapes)."""
    return "".join(f'"{_escape(str(k))}" = "{_escape(str(v))}";\n' for k, v in mapping.items())


def save(mapping: dict, path) -> None:
    pathlib.Path(path).write_text(dumps(mapping), encoding="utf-8")
