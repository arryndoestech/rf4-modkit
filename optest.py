"""In-game opcode tests: what is verified, value sweeps, and recording the results.

Every argument in refdata/opcode_table.json carries its own `human_verified` flag and a
`tests` log, and an argument whose value is a code can list `value_names` (the names a
listing writes and the assembler reads). An op counts as fully verified when the op and
each of its arguments are.

  python optest.py status                 the backlog: verified ops with unverified arguments
  python optest.py status ModifyPlayerResource   one op: each argument, its value names, its tests
  python optest.py sweep "ShowActorEmote(actor(player), {v})" 1-26 --then "ShowActorEmote(actor(player), 0)"
        install a value sweep into a map's entry scene: for each value the box says
        "The result: <value> points", then the call runs with that value
  python optest.py restore MAP_F_ROOM_00  put a map's scenes back as they were before the tests
  python optest.py record 417 --call "ModifyPlayerResource(gold, add, 1234)" \\
        --observed "gold went up by 1234" --arg 0 --arg 2 --value 0:100=gold

Test scenes go into a map's entry scene (it runs each time you walk into the map). That scene
starts while the warp's black screen is still up, so every sweep begins with a short Wait.
"""
import argparse
import datetime
import json
import pathlib
import re
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

TABLE = _HERE / "refdata" / "opcode_table.json"
NUMBER_LINE = 94412          # "The result: ＠数字０＠ points" (the number is SetVar3 slot 0)
NAME_RE = re.compile(r"[A-Za-z_]\w*\Z")


# ---- the table ---------------------------------------------------------------------
def load():
    return json.loads(TABLE.read_text(encoding="utf-8"))


def save(t):
    TABLE.write_text(json.dumps(t, indent=1, ensure_ascii=False), encoding="utf-8")


def find_op(t, what):
    """The action row for an op number or mnemonic (case-insensitive; first of a family)."""
    what = str(what).strip()
    if re.fullmatch(r"(0x[0-9a-fA-F]+|\d+)", what):
        r = t["actions"].get(str(int(what, 0)))
        if r:
            return r
    for r in t["actions"].values():
        if r["mnemonic"].lower() == what.lower():
            return r
    raise SystemExit("no op %r" % what)


def alias_group(t, r):
    """The rows that are one instruction with `r` (same mnemonic and handler: true aliases,
    and families like SetSpeaker whose leading arguments sit in the opcode). They share
    their arguments, so a test of one is a test of all."""
    return [x for x in t["actions"].values()
            if x["mnemonic"] == r["mnemonic"] and x.get("handler_rva") == r.get("handler_rva")]


def fully_verified(r):
    return bool(r.get("human_verified")) and all(a.get("human_verified") for a in r["args"])


def record(t, op, call, observed, args=(), values=None, op_verified=None, date=None, evidence=True):
    """Log one in-game test in the table `t` (saved by the caller).

    `args`: indices of the arguments this test confirmed (their human_verified is set);
    every argument the call exercised gets the test in its `tests` log either way.
    `values`: {arg index: {value: name or (name, text)}} -- names to add; each one this
    test showed is marked verified. `op_verified`: True/False to set the op's own flag."""
    r = find_op(t, op)
    date = date or datetime.date.today().isoformat()
    entry = {"date": date, "call": call, "observed": observed}
    touched = set(args) | set((values or {}).keys())
    for x in alias_group(t, r):
        for i in sorted(touched):
            if not 0 <= i < len(x["args"]):
                raise SystemExit("%s has no argument %d" % (x["mnemonic"], i))
            a = x["args"][i]
            a.setdefault("tests", []).append(dict(entry))
            if i in args:
                a["human_verified"] = True
        for i, vals in (values or {}).items():
            names = x["args"][i].setdefault("value_names", {})
            for v, nm in vals.items():
                nm, text = (nm, "") if isinstance(nm, str) else nm
                if not NAME_RE.match(nm):
                    raise SystemExit("value name %r: use letters, digits and _ only" % nm)
                e = names.setdefault(str(int(v)), {"name": nm, "text": text})
                e["name"] = nm
                if text:
                    e["text"] = text
                e["human_verified"] = True
            x["args"][i]["value_names"] = dict(sorted(names.items(), key=lambda kv: int(kv[0], 0)))
    if op_verified is not None:
        r["human_verified"] = bool(op_verified)
    if evidence:
        r["evidence"] = (r.get("evidence") or "").rstrip(".") + ". In-game test %s (user): %s -> %s." % (
            date, call, observed.rstrip("."))
    return r


# ---- report ------------------------------------------------------------------------
def describe(r):
    out = ["%s  (op %d)  op %s" % (r["prototype"], r["op"],
                                   "verified" if r.get("human_verified") else "NOT verified")]
    for i, a in enumerate(r["args"]):
        out.append("  arg %d %-14s %s   [%s]" % (i, a["name"], "verified" if a.get("human_verified")
                                                 else "NOT verified", a.get("type") or ""))
        if a.get("values"):
            out.append("      claimed: %s" % a["values"])
        for v, e in (a.get("value_names") or {}).items():
            out.append("      %6s = %-14s %s%s" % (v, e["name"], "" if e.get("human_verified") else "(untested) ",
                                                    e.get("text") or ""))
        for te in a.get("tests") or ():
            out.append("      test %s: %s -> %s" % (te["date"], te["call"], te["observed"]))
    return "\n".join(out)


def backlog(t):
    rows = list(t["actions"].values())
    part = [r for r in rows if r.get("human_verified") and not fully_verified(r)]
    full = [r for r in rows if fully_verified(r)]
    out = ["%d ops fully verified, %d verified with arguments still open, %d not verified"
           % (len(full), len(part), len(rows) - len(full) - len(part)), ""]
    for r in part:
        open_ = [a["name"] for a in r["args"] if not a.get("human_verified")]
        out.append("  %-4d %-28s open: %s" % (r["op"], r["mnemonic"], ", ".join(open_)))
    return "\n".join(out)


# ---- test scenes -------------------------------------------------------------------
def parse_values(spec):
    out = []
    for part in spec.split(","):
        part = part.strip()
        m = re.fullmatch(r"(-?\w+)\s*-\s*(-?\w+)", part)
        if m:
            lo, hi = int(m.group(1), 0), int(m.group(2), 0)
            out.extend(range(lo, hi + 1))
        elif part:
            out.append(int(part, 0))
    return out


def sweep_listing(call, values, then=None, hold=24000):
    """Listing text of a value sweep: announce each value, run `call` with it, hold."""
    if "{v}" not in call:
        raise SystemExit("the call needs {v} where the value goes, e.g. \"ShowActorEmote(actor(player), {v})\"")
    lines = ["Wait(6000)"]                         # let the map's own fade-in finish
    for v in values:
        lines += ["SetVar3(0, %d)" % v, "SetSpeaker(MC, Left, 0, 0)", "DIALOG #%d" % NUMBER_LINE,
                  "EndDialogue()", call.replace("{v}", str(v)), "Wait(%d)" % hold]
        if then:
            lines.append(then.replace("{v}", str(v)))
    return "\n".join(lines + ["RET"]) + "\n"


def _container():
    from rf4s_modkit import script as S, emflags
    from map_editor import data
    path = data.rf3mc_path()
    c = S.Container(path.read_bytes() if hasattr(path, "read_bytes") else open(path, "rb").read())
    c.install_asm_resolver(emflags.EmFlagTable.load())
    return S, data, path, c


def _write(S, path, c):
    from rf4s_modkit import gamepaths
    blob = c.build()
    S.Container(blob)                              # it must read back
    gamepaths.write_game_file(path, blob)


def install_sweep(map_name, listing):
    """Put `listing` in front of `map_name`'s entry scene (the map's own scene still runs
    after it). Returns the scene's pc."""
    S, data, path, c = _container()
    bank = c.banks[c.n_primary + data.map_id(map_name)]
    recs = bank.entry_records(6)
    if not recs:
        raise SystemExit("%s has no entry scene" % map_name)
    body = listing[:-len("RET\n")] if listing.endswith("RET\n") else listing
    c.insert_before(bank, recs[0].event_id, body)
    _write(S, path, c)
    return bank.entry_records(6)[0].event_id, path


def test_lines(lines, pid=None):
    """Load the game's dialogue text plus `lines` (test descriptions) into the running game only
    -- no file changes -- and return their line ids for DIALOG #id. The game's language file
    is the base; a later `script reload` puts the plain text back. Run it after the rf3.mc
    reload (that one reloads the text from disk)."""
    from rf4s_modkit import gamepaths, hotreload, textdb
    loc, _n = hotreload.text_locale(pid=pid)
    if loc is None:
        raise SystemExit("the game's dialogue text matches none of the rf3mc.<locale> files")
    f = (gamepaths.game_targets(["rf3mc.%s" % loc]) or {}).get("rf3mc.%s" % loc)
    arc = textdb.TextArchive.parse(pathlib.Path(f).read_bytes())
    ids = [arc.append_text(s) for s in lines]
    hotreload.reload_text(arc.build(), pid=pid)
    return ids


def restore(map_name):
    """Put the map's scene bank back as it is in the original file (the backup the toolkit
    made before its first write). Only that map's bank changes."""
    from rf4s_modkit import gamepaths, script as S2
    S, data, path, c = _container()
    orig = gamepaths.backup_path(path)
    if orig is None or not pathlib.Path(orig).is_file():
        raise SystemExit("no original copy of %s to restore from" % path)
    o = S2.Container(pathlib.Path(orig).read_bytes())
    i = c.n_primary + data.map_id(map_name)
    c.set_bank_bytes(c.banks[i], bytes(o.banks[i].data))
    _write(S, path, c)
    return orig


# ---- command line ------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status"); p.add_argument("op", nargs="?")
    p = sub.add_parser("sweep")
    p.add_argument("call"); p.add_argument("values")
    p.add_argument("--then"); p.add_argument("--map", default="MAP_F_ROOM_00")
    p.add_argument("--hold", type=int, default=24000, help="time per value (200 = 1 frame)")
    p.add_argument("--dry", action="store_true", help="print the listing only")
    p = sub.add_parser("restore"); p.add_argument("map")
    p = sub.add_parser("record")
    p.add_argument("op"); p.add_argument("--call", required=True); p.add_argument("--observed", required=True)
    p.add_argument("--arg", type=int, action="append", default=[])
    p.add_argument("--value", action="append", default=[], help="ARG:VALUE=name[:text]")
    p.add_argument("--op-verified", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "status":
        t = load()
        print(describe(find_op(t, a.op)) if a.op else backlog(t))
    elif a.cmd == "sweep":
        listing = sweep_listing(a.call, parse_values(a.values), a.then, a.hold)
        if a.dry:
            print(listing)
            return
        pc, path = install_sweep(a.map, listing)
        print("installed in %s's entry scene (@%04x) of %s" % (a.map, pc, path))
        print("walk into the map; each box names the value the next step uses")
    elif a.cmd == "restore":
        print("restored %s from %s" % (a.map, restore(a.map)))
    elif a.cmd == "record":
        values = {}
        for spec in a.value:
            m = re.fullmatch(r"(\d+):(-?\w+)=([A-Za-z_]\w*)(?::(.*))?", spec)
            if not m:
                raise SystemExit("--value wants ARG:VALUE=name[:text], got %r" % spec)
            values.setdefault(int(m.group(1)), {})[int(m.group(2), 0)] = (m.group(3), m.group(4) or "")
        t = load()
        r = record(t, a.op, a.call, a.observed, a.arg, values, True if a.op_verified else None)
        save(t)
        print(describe(r))


if __name__ == "__main__":
    main()
