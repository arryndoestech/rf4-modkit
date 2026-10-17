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
  python optest.py restore --bank 1120    undo a test put into a talk scene of a global bank
  python optest.py record 417 --call "ModifyPlayerResource(gold, add, 1234)" \\
        --observed "gold went up by 1234" --arg 0 --arg 2 --value 0:100=gold

The test plan (refdata/optest_plan.json): ready-made tests for the instructions not verified
yet -- the behaviour and each argument -- with on-screen notes for every step.

  python optest.py plan                       what is left, by category (verified ones drop out)
  python optest.py plan list query            the tests of one category (or a mnemonic)
  python optest.py plan show <id>             setup, steps, what to look for
  python optest.py plan run <id> [--map M]    install it: notes + steps in the map's entry scene
  python optest.py plan done <id> --observed "what you saw" [--failed]
                                              log it: marks the instruction / arguments verified

Test scenes go into a map's entry scene (it runs each time you walk into the map). That scene
starts while the warp's black screen is still up, so every sweep begins with a short Wait.
"""
import argparse
import datetime
import json
import pathlib
import re
import sys
import textwrap

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


def has_entry_scene(map_name):
    """True if the map has a scene that runs when you walk in (what install_sweep needs)."""
    S, data, path, c = _container()
    return bool(c.banks[c.n_primary + data.map_id(map_name)].entry_records(6))


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


BANK_STATE = _HERE / "out" / "optest_banks.json"  # banks a test went into: {bank: {before, after}}


def scene_pc(c, scene):
    """The pc a test's `scene` ({"bank", "type", optional "key", optional "call"}) points at in
    the container `c`: the first entry of that action type (with that key value, if given);
    with "call", the target of the CALL that entry starts with (where scenes that share code
    meet). Found by entry, not by a fixed pc, so the user's own edits of the bank can move it."""
    from rf4s_modkit import script as S2
    bank = c.banks[scene["bank"]]
    recs = [r for r in bank.entry_records(scene["type"])
            if "key" not in scene or any(v == scene["key"] for _t, v in r.subs)]
    if not recs:
        raise SystemExit("bank %d has no type-%d entry%s" % (scene["bank"], scene["type"],
                         " with key %d" % scene["key"] if "key" in scene else ""))
    pc = recs[0].event_id
    if scene.get("call"):
        for sc in S2.disassemble_bank(bank):
            st = sc.stmts.get(pc)
            if st is not None:
                if st.mnem != "CALL" or not st.code_targets:
                    raise SystemExit("the scene at %04x does not start with a CALL" % pc)
                return st.code_targets[0]
        raise SystemExit("no statement at %04x" % pc)
    return pc


def install_in_scene(scene, listing):
    """Put `listing` in front of the statement a test's `scene` names (see scene_pc), keeping
    the bank as it was in BANK_STATE so `restore --bank` can put back exactly that -- not the
    shipped bank, which would also undo the user's own edits there. Returns the pc."""
    import hashlib
    S, data, path, c = _container()
    i = scene["bank"]
    st = json.loads(BANK_STATE.read_text(encoding="utf-8")) if BANK_STATE.is_file() else {}
    if str(i) in st:
        raise SystemExit("bank %d still holds an earlier test: python optest.py restore --bank %d first" % (i, i))
    pc = scene_pc(c, scene)
    before = bytes(c.banks[i].data)
    body = listing[:-len("RET\n")] if listing.endswith("RET\n") else listing
    c.insert_before(c.banks[i], pc, body)
    _write(S, path, c)
    st[str(i)] = {"before": before.hex(), "after": hashlib.sha256(bytes(c.banks[i].data)).hexdigest()}
    BANK_STATE.parent.mkdir(parents=True, exist_ok=True)
    BANK_STATE.write_text(json.dumps(st), encoding="utf-8")
    return pc


def restore_bank(i):
    """Undo install_in_scene for bank `i`, only if the bank is still exactly as the test left it."""
    import hashlib
    st = json.loads(BANK_STATE.read_text(encoding="utf-8")) if BANK_STATE.is_file() else {}
    e = st.get(str(i))
    if e is None:
        raise SystemExit("no test was put into bank %d" % i)
    S, data, path, c = _container()
    if hashlib.sha256(bytes(c.banks[i].data)).hexdigest() != e["after"]:
        raise SystemExit("bank %d changed after the test went in (an edit?): left as it is; "
                         "take the test lines out in the cutscene editor" % i)
    c.set_bank_bytes(c.banks[i], bytes.fromhex(e["before"]))
    _write(S, path, c)
    del st[str(i)]
    BANK_STATE.write_text(json.dumps(st), encoding="utf-8")
    remove_test_text()


TEXT_STATE = _HERE / "out" / "optest_text.json"   # the test lines now in the rf3mc.<locale> files


def _text_files():
    """{locale: path} of every rf3mc.<locale> the game loads."""
    from rf4s_modkit import gamepaths, hotreload
    names = ["rf3mc.%s" % loc for loc in hotreload.TEXT_LOCALES]
    t = gamepaths.game_targets(names) or {}
    out = {n[6:]: pathlib.Path(t[n]) for n in names if t.get(n) and pathlib.Path(t[n]).is_file()}
    if not out:
        raise SystemExit("no rf3mc.<locale> files in the game folder")
    return out


def _strip_test_text(arcs):
    """Take the previous test's lines (TEXT_STATE) off the end of each archive in `arcs`
    ({locale: TextArchive}) -- only where the file still ends with exactly them. True when
    anything was taken off."""
    if not TEXT_STATE.is_file():
        return False
    st = json.loads(TEXT_STATE.read_text(encoding="utf-8"))
    tail = [box_text(s).encode("utf-8") for s in st["lines"]]
    cut = False
    for loc, arc in arcs.items():
        n0 = st["base"].get(loc)
        if n0 is None:
            continue
        if arc.entries[-len(tail):] == tail and len(arc) >= n0 + len(tail)                 and all(e == b"" for e in arc.entries[n0:len(arc) - len(tail)]):
            del arc.entries[n0:]
            cut = True
        else:
            print("rf3mc.%s no longer ends with the previous test's lines: left as it is" % loc)
    return cut


def test_text_ids(lines):
    """The line ids install_test_text would give `lines` (nothing is written)."""
    from rf4s_modkit import textdb
    arcs = {loc: textdb.TextArchive.parse(f.read_bytes()) for loc, f in _text_files().items()}
    _strip_test_text(arcs)
    base = max(len(a) for a in arcs.values())
    return list(range(base, base + len(lines)))


def install_test_text(lines):
    """Write `lines` (test descriptions, wrapped to the box) to the end of EVERY rf3mc.<locale>
    on disk, with the same ids in all of them (a shorter file is padded with empty lines), so
    any reload -- Ctrl+R, F5, `script reload`, a restart -- keeps them. The previous test's
    lines are taken off first, so the files do not grow test after test; remove_test_text
    takes them off for good. Returns their ids for DIALOG #id."""
    from rf4s_modkit import gamepaths, textdb
    files = _text_files()
    arcs = {loc: textdb.TextArchive.parse(f.read_bytes()) for loc, f in files.items()}
    _strip_test_text(arcs)
    base = max(len(a) for a in arcs.values())
    state = {"base": {}, "lines": list(lines)}
    for loc, arc in arcs.items():
        state["base"][loc] = len(arc)
        while len(arc) < base:
            arc.append_text("")
        for s in lines:
            arc.append_text(box_text(s))
    for loc, arc in arcs.items():
        gamepaths.write_game_file(files[loc], arc.build())
    TEXT_STATE.parent.mkdir(parents=True, exist_ok=True)
    TEXT_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return list(range(base, base + len(lines)))


def remove_test_text():
    """Take the last test's lines off the rf3mc.<locale> files again. True when it did."""
    from rf4s_modkit import gamepaths, textdb
    if not TEXT_STATE.is_file():
        return False
    files = _text_files()
    arcs = {loc: textdb.TextArchive.parse(f.read_bytes()) for loc, f in files.items()}
    if _strip_test_text(arcs):
        for loc, arc in arcs.items():
            gamepaths.write_game_file(files[loc], arc.build())
    TEXT_STATE.unlink()
    return True


def test_lines(lines, pid=None):
    """install_test_text(lines), then put the game's language file (now with them) into the
    running game. Returns the line ids for DIALOG #id."""
    from rf4s_modkit import hotreload
    ids = install_test_text(lines)
    loc, _n = hotreload.text_locale(pid=pid)
    if loc is None:
        raise SystemExit("the game's dialogue text matches none of the rf3mc.<locale> files")
    hotreload.reload_text(_text_files()[loc].read_bytes(), pid=pid)
    return ids


BOX_WIDTH = 56          # characters per dialogue-box row that stay on screen (about 80 get cut off)
BOX_ROWS = 3


def box_text(s, width=BOX_WIDTH):
    """Break a test line into rows that fit the dialogue box. Rows already broken with \\n
    are wrapped on their own; a value slot (＠０＠) counts as a few digits."""
    rows = []
    for part in s.split("\n"):
        rows += textwrap.wrap(part, width, break_long_words=False, break_on_hyphens=False) or [""]
    if len(rows) > BOX_ROWS:
        print("warning: test line needs %d rows (the box shows %d): %s" % (len(rows), BOX_ROWS, s[:60]))
    return "\n".join(rows)


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
    remove_test_text()                             # its test lines go too
    return orig


# ---- command line ------------------------------------------------------------------
PLAN = _HERE / "refdata" / "optest_plan.json"


def plan_load():
    if not PLAN.is_file():
        raise SystemExit("no test plan (%s)" % PLAN)
    return json.loads(PLAN.read_text(encoding="utf-8"))


def plan_find(tests, tid):
    hit = [x for x in tests if x["id"].lower() == tid.lower()]
    if not hit:
        near = [x["id"] for x in tests if tid.lower() in x["id"].lower()][:8]
        raise SystemExit("no test %r%s" % (tid, (" -- did you mean: " + ", ".join(near)) if near else ""))
    return hit[0]


def plan_open(t, test):
    """Whether the test still checks something not verified (the op, or one of its arguments)."""
    r = find_op(t, test["ops"][0])
    v = test.get("verifies") or {}
    if v.get("op") and not r.get("human_verified"):
        return True
    return any(i < len(r["args"]) and not r["args"][i].get("human_verified") for i in v.get("args", ()))


def plan_listing(test, note_ids):
    """The test scene: a short wait, then each step's note in a box and its statements."""
    lines = ["Wait(6000)"]
    for k, step in enumerate(test["steps"]):
        if step.get("say"):
            lines += ["SetSpeaker(MC, Left, 0, 0)", "DIALOG #%d" % note_ids[k], "EndDialogue()"]
        lines += [x for x in (step.get("do") or "").splitlines() if x.strip()]
    return "\n".join(lines + ["RET"]) + "\n"


def plan_describe(test):
    v = test.get("verifies") or {}
    out = ["%s   (%s, op %s)%s" % (test["id"], test["mnemonic"], "/".join(map(str, test["ops"])),
                                   "   [needs special context]" if test.get("hard") else ""),
           "  checks: %s" % ", ".join((["what it does"] if v.get("op") else [])
                                     + ["argument %d" % i for i in v.get("args", ())]),
           ("  scene:  bank %d, before the type-%d entry%s%s" % (
               test["scene"]["bank"], test["scene"]["type"],
               " with key %d" % test["scene"]["key"] if "key" in test["scene"] else "",
               " (the code it CALLs)" if test["scene"].get("call") else "")
            if test.get("scene") else "  map:    %s" % test["map"]),
           "  setup:  %s" % test["setup"], "  steps:"]
    for k, step in enumerate(test["steps"], 1):
        if step.get("say"):
            out.append("    %d. note: %s" % (k, step["say"]))
        for x in (step.get("do") or "").splitlines():
            if x.strip():
                out.append("         %s" % x.strip())
    out.append("  expect: %s" % test["expect"])
    return "\n".join(out)


def plan_cmd(a):
    tests = plan_load()
    t = load()
    if a.action in (None, "summary"):
        left = [x for x in tests if plan_open(t, x)]
        by = {}
        for x in left:
            by.setdefault(find_op(t, x["ops"][0]).get("category") or "?", []).append(x)
        print("%d of %d tests still check something not verified:" % (len(left), len(tests)))
        for cat, xs in sorted(by.items(), key=lambda kv: -len(kv[1])):
            print("  %-10s %3d tests, %d instructions" % (cat, len(xs), len({x["mnemonic"] for x in xs})))
        print("python optest.py plan list <category> -- then plan show / run / done <id>")
    elif a.action == "list":
        want = (a.id or "").lower()
        for x in tests:
            cat = (find_op(t, x["ops"][0]).get("category") or "").lower()
            if want and want not in (cat, x["mnemonic"].lower()):
                continue
            print("%s %-48s %s" % ("open" if plan_open(t, x) else "done", x["id"], x["expect"][:70]))
    elif a.action == "show":
        print(plan_describe(plan_find(tests, a.id)))
    elif a.action == "run":
        test = plan_find(tests, a.id)
        notes = [st.get("say") or "" for st in test["steps"]]
        if a.dry:                                  # the notes are not written anywhere
            print(plan_listing(test, [NUMBER_LINE] * len(notes)))
            return
        ids = test_lines([n for n in notes if n])
        it = iter(ids)
        note_ids = [next(it) if n else None for n in notes]
        listing = plan_listing(test, note_ids)
        if test.get("scene"):                      # a talk scene of another bank, not a map's entry
            sc = test["scene"]
            pc = install_in_scene(sc, listing)
            print(plan_describe(test))
            print("\ninstalled in bank %d before @%04x; reload rf3.mc in the game (F5 in the cutscene "
                  "editor), then do what the setup says. Afterwards: python optest.py plan done %s "
                  "--observed \"...\"  and  python optest.py restore --bank %d"
                  % (sc["bank"], pc, test["id"], sc["bank"]))
            return
        if not has_entry_scene(a.map or test["map"]):
            print(plan_describe(test))
            print("\n%s has no entry scene, so this one is placed by hand: copy the scene below, "
                  "select where the setup says in the cutscene editor and press Ctrl+V, then reload.\n\n%s"
                  % (a.map or test["map"], listing))
            return
        pc, path = install_sweep(a.map or test["map"], listing)
        print(plan_describe(test))
        print("\ninstalled in %s's entry scene (@%04x); walk into the map. Afterwards: "
              "python optest.py plan done %s --observed \"...\"  and  python optest.py restore %s"
              % (a.map or test["map"], pc, test["id"], a.map or test["map"]))
    elif a.action == "done":
        test = plan_find(tests, a.id)
        if not a.observed:
            raise SystemExit("--observed \"what you saw\" is needed")
        v = test.get("verifies") or {}
        values = {}
        if not a.failed:
            for k, names in (test.get("values") or {}).items():
                values[int(k)] = {int(val, 0): (nm, "") for val, nm in names.items()}
        r = record(t, test["ops"][0], test["call"], ("FAILED: " if a.failed else "") + a.observed,
                   [] if a.failed else list(v.get("args", ())), values,
                   None if a.failed or not v.get("op") else True)
        save(t)
        print(describe(r))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status"); p.add_argument("op", nargs="?")
    p = sub.add_parser("sweep")
    p.add_argument("call"); p.add_argument("values")
    p.add_argument("--then"); p.add_argument("--map", default="MAP_F_ROOM_00")
    p.add_argument("--hold", type=int, default=24000, help="time per value (200 = 1 frame)")
    p.add_argument("--dry", action="store_true", help="print the listing only")
    p = sub.add_parser("restore"); p.add_argument("map", nargs="?")
    p.add_argument("--bank", type=int, help="undo a test put into a talk scene of this bank")
    p = sub.add_parser("plan")
    p.add_argument("action", nargs="?", choices=("summary", "list", "show", "run", "done"))
    p.add_argument("id", nargs="?", help="a test id (list: a category or mnemonic)")
    p.add_argument("--map", help="run: another map than the test's")
    p.add_argument("--dry", action="store_true", help="run: print the scene only (notes as line %d)" % NUMBER_LINE)
    p.add_argument("--observed", help="done: what you saw")
    p.add_argument("--failed", action="store_true", help="done: it did not do what the test expects")
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
    elif a.cmd == "plan":
        plan_cmd(a)
    elif a.cmd == "restore":
        if a.bank is not None:
            restore_bank(a.bank)
            print("bank %d is back as it was before the test" % a.bank)
        elif a.map:
            print("restored %s from %s" % (a.map, restore(a.map)))
        else:
            raise SystemExit("restore MAP, or restore --bank N")
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
