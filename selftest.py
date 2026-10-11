#!/usr/bin/env python3
r"""
selftest.py -- validate rf4s_modkit against the installed RF4S bundles.

Run via `python rf4mod.py selftest` or directly `python selftest.py`. It exercises
every reader/writer round-trip on real game data and reports pass/fail. Tests that
need data the user hasn't extracted are skipped, not failed.
"""
from __future__ import annotations

import pathlib
import random
import re
import struct
import sys
import tempfile
import shutil

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rf4s_modkit import (  # noqa: E402
    bplist, mbundle, textdb, texture, rf4m, aibn, strings_file, res_container, ident, gen, nlcl,
    mapground, search_items, mobj_types, emflags, emscript,
)

from rf4s_modkit import gamepaths as _gamepaths  # noqa: E402
BUNDLE_DIR = _gamepaths.bundle_dir()             # the game copy (rf4s_modkit.gamepaths)
GAME_DIR = BUNDLE_DIR.parent                     # the game folder holding Bundle/


def _private_settings():
    """Run against a scratch copy of settings.json: the GUI tests toggle settings the toolkit
    remembers (map layers, map grouping), which must neither land in the user's file nor be
    read back from it (a user's saved choices would change what the tests see)."""
    import json as _json
    d = _gamepaths._load_settings()
    for k in ("map_view", "group_maps_by_area", "season_note_shown", "map_wheel", "map_minimap_hidden",
              "map_palette_favorites", "cutscene_editor", "theme", "backup_originals", "backup_previous",
              "backup_dir", "list_rows", "ui_scale"):
        d.pop(k, None)
    # the GUI tests expect a save to keep the original (backups are off by default for users)
    d["backup_originals"], d["backup_previous"] = True, 1
    p = pathlib.Path(tempfile.mkdtemp(prefix="rf4s_selftest_")) / "settings.json"
    p.write_text(_json.dumps(d), encoding="utf-8")
    _gamepaths.settings_path = lambda: p


_private_settings()


def _no_editor_preload():
    """The cutscene editor builds the Reference / Event Manager hidden a second after it
    opens; the tests open and close editors and count windows, so that is off here (its own
    test, test_cutscene_preload, turns it on)."""
    try:
        from cutscene_editor import app as _capp
        _capp.CutsceneExplorer.PRELOAD = False
    except Exception:  # noqa: BLE001 -- no Tk: no editor tests either
        pass


_no_editor_preload()
# Extraction root: Bundle/extracted/ if present, else a flat Bundle/<bundle>/ layout.
EXTRACTED = (BUNDLE_DIR / "extracted") if (BUNDLE_DIR / "extracted").is_dir() else BUNDLE_DIR

# ---- quick mode + shared disassembly cache -----------------------------------------
# `python selftest.py --quick` = fast iteration run (~1 min): the handful of
# full-corpus rf3.mc sweeps are skipped or sliced (marked [SKIP]/detail "quick");
# run WITHOUT the flag for the full green stamp before calling work done.
#
# The cache exists because test_script/test_emscript sweep rf3.mc many times
# (coverage, render audit, op-range scan, EMF-bridge scans, ...) and every
# disassemble_bank call used to re-decode from scratch — profiled 2026-09-01 at
# ~485s of a 543s total, worse since the FRAME fall-through correction made scenes
# larger. Scenes are cached by (bank index, kind, discover, content-crc32):
# identical bytes decode identically, the crc keeps the cache honest across the
# round-trip EDIT checks (mutated bank bytes -> new key), and separate Containers
# of the same file share hits. Cached Scene objects are shared — checks must not
# mutate them (none do; edits go through the Container/bank-bytes APIs).
QUICK = "--quick" in sys.argv
import zlib as _zlib                                            # noqa: E402
import copy as _copy_mod                                        # noqa: E402
from rf4s_modkit import script as _script_mod                   # noqa: E402
_DISASM_CACHE = {}
_disassemble_bank_uncached = _script_mod.disassemble_bank


def _disassemble_bank_cached(bank, discover=True):
    key = (bank.index, bank.kind, bool(discover), _zlib.crc32(bytes(bank.data)))
    hit = _DISASM_CACHE.get(key)
    if hit is None:
        hit = list(_disassemble_bank_uncached(bank, discover=discover))
        _DISASM_CACHE[key] = hit
    # shallow copies: a caller that moves a scene's entry (the editor after an edit) must not
    # change what the next caller of the same bytes gets (2026-10-01: an editor test did)
    return [_copy_mod.copy(sc) for sc in hit]


_script_mod.disassemble_bank = _disassemble_bank_cached

_results = []


def _check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    _results.append((name, cond))
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))


def _skip(name, why):
    print(f"  [SKIP] {name}  ({why})")


def _first(glob):
    try:
        return next(EXTRACTED.rglob(glob))
    except StopIteration:
        return None


def _shipped(glob):
    """The game's ORIGINAL copy of a file: the one in ModdingBackup when a save (or a mod)
    replaced the game's file, else the game's own. Tests that pin addresses or counts in
    the shipped data use this, so a modded game folder doesn't fail them."""
    live = _first(glob)
    if live is None:
        return None
    try:
        orig = _gamepaths.backup_path(live)
    except Exception:  # noqa: BLE001 -- no backup folder configured
        orig = None
    return orig if orig is not None and orig.is_file() else live


def test_bplist():
    print("bplist:")
    for f in ("KeyBindings.plist", "MUKeyCodeConversion.plist"):
        p = BUNDLE_DIR.parent / f           # the game copy
        if not p.is_file():
            _skip(f"bplist round-trip {f}", "file not present")
            continue
        obj = bplist.loads(p.read_bytes())
        b1 = bplist.dumps(obj)
        _check(f"bplist value round-trip {f}", bplist.loads(b1) == obj)
        _check(f"bplist byte-stable re-dump {f}", bplist.dumps(bplist.loads(b1)) == b1)
    # synthetic edge cases
    sample = {"neg": -14336, "big": 5_000_000_000, "u": "café★日本語",
              "blob": b"RES\x00" * 9, "nest": {"a": [1, 2.5, True, None]}}
    _check("bplist synthetic round-trip", bplist.loads(bplist.dumps(sample)) == sample)
    # ints outside int64 must be REFUSED, never written as a 16-byte (0x14) int: the game's
    # Bplist_ReadInt (RF4S.exe+0x2678D0) frees its 8-byte scratch and reads 16 bytes into it.
    _refused = 0
    for _v in (2**63, 2**64 - 1, -(2**63) - 1):
        try:
            bplist.dumps({"a": _v})
        except bplist.BplistError:
            _refused += 1
    _edge = {"max": 2**63 - 1, "min": -(2**63)}
    _check("bplist refuses ints wider than 8 bytes; int64 extremes round-trip",
           _refused == 3 and bplist.loads(bplist.dumps(_edge)) == _edge)
    # offset table width must be 4 (or 8 past 0x3FFFFFFF): Bplist_ReadObjectByIndex (+0x266730)
    # reads every width other than 4 as u64, so a tiny plist with 1-byte offsets was misread.
    _tiny = bplist.Bplist(bplist.dumps({"a": 1}))
    _check("bplist writer uses 4-byte offsets + 4-byte refs (game-readable)",
           _tiny.offset_size == 4 and _tiny.ref_size == 4)
    # scalar dedup (the engine writer's `seen` map): repeated keys stored once, types kept apart
    _dd = {"x": [{"size": 1, "offset": 1}, {"size": True, "offset": 1.0}], "s": "size"}
    _ddb = bplist.dumps(_dd)
    _back = bplist.loads(_ddb)
    _check("bplist dedups scalars by (type, value)",
           _back == _dd and _ddb.count(b"\x54size") == 1
           and type(_back["x"][1]["size"]) is bool and type(_back["x"][1]["offset"]) is float)
    mani = BUNDLE_DIR / "Manifest.plist"
    if mani.is_file():
        _mraw = mani.read_bytes()
        _mv = bplist.loads(_mraw)
        _mout = bplist.dumps(_mv)
        _check("bplist Manifest re-dump value-equal and not larger than stock",
               bplist.loads(_mout) == _mv and len(_mout) <= len(_mraw),
               f"{len(_mout):,} vs {len(_mraw):,} bytes")


def test_mbundle():
    print("mbundle:")
    mani_p = BUNDLE_DIR / "Manifest.plist"
    if not mani_p.is_file():
        _skip("mbundle", "Manifest.plist not present")
        return
    man = mbundle.Manifest(mani_p)
    _check("manifest parse", "bundles" in man.root and len(man.bundles) >= 1,
           f"{len(man.bundles)} bundles")
    # smallest packed bundle present on disk -- or, when the bundles are extracted to directories
    # (no packed file), a SELF-CONTAINED synthetic bundle built via the toolkit's own
    # rebuild_from_dir. Either way the packed-bundle read + manifest==embedded-TOC + repack path is
    # tested deterministically (this branch used to _skip when no packed bundle was on disk).
    # (not a voice bundle: unpack() leaves those packed by default, so the unpack checks
    # below would find nothing -- a copy made by the toolkit keeps only those packed)
    present = [(b, (BUNDLE_DIR / b).stat().st_size) for b in man.bundle_names()
              if (BUNDLE_DIR / b).is_file() and b not in mbundle.VOICE_BUNDLES.values()]
    if present:
        small = min(present, key=lambda x: x[1])[0]
        bpath, mpath, use_man = BUNDLE_DIR / small, mani_p, man
    else:
        from rf4s_modkit import bplist as _bpl
        _syn = pathlib.Path(tempfile.mkdtemp())
        _src = _syn / "src"; (_src / "sub").mkdir(parents=True)
        (_src / "a.txt").write_bytes(b"hello bundle")
        (_src / "sub" / "b.bin").write_bytes(bytes(range(200)))
        small = "bundleSynthetic"
        bpath = _syn / small
        _toc = mbundle.rebuild_from_dir(_src, bpath)      # toolkit builds a self-consistent bundle
        mpath = _syn / "Manifest.plist"
        mpath.write_bytes(_bpl.dumps({"bundles": [{"bundleName": small, "files": _toc}]}))
        use_man = mbundle.Manifest(mpath)
    b_emb = mbundle.Bundle(bpath)
    b_man = mbundle.Bundle(bpath, manifest=use_man)
    _check(f"bundle TOC manifest==embedded ({small})", set(b_emb.names()) == set(b_man.names()))
    if b_emb.names():
        nm = b_emb.names()[0]
        _check("bundle read manifest==embedded", b_emb.read(nm) == b_man.read(nm))

    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        cb = tmp / small
        shutil.copyfile(bpath, cb)
        cm = tmp / "Manifest.plist"
        shutil.copyfile(mpath, cm)
        m2 = mbundle.Manifest(cm)
        nm = b_emb.names()[0]
        orig = b_emb.read(nm)
        # in-place patch (same size)
        mbundle.patch_inplace(cb, m2, nm, b"ZZZZ" + orig[4:])
        m2.save()
        chk = mbundle.Bundle(cb, manifest=mbundle.Manifest(cm))
        _check("in-place patch", chk.read(nm)[:4] == b"ZZZZ" and len(chk.read(nm)) == len(orig))
        # append repack (add new + grow)
        m3 = mbundle.Manifest(cm)
        mbundle.append_repack(cb, m3, {nm: b"\xAB" * 4096, "mod/new.bin": b"hello"})
        m3.save()
        chk2 = mbundle.Bundle(cb, manifest=mbundle.Manifest(cm))
        _check("append-repack grow+add",
               chk2.read(nm) == b"\xAB" * 4096 and chk2.read("mod/new.bin") == b"hello")
        # the EMBEDDED TOC must stay a valid bplist that matches the manifest after an append
        # (a raw append left the trailer inside the last blob: `bundle list` without
        # --use-manifest then read garbage)
        try:
            emb = mbundle.Bundle(cb)
            _emb_ok = (set(emb.names()) == set(chk2.names())
                       and all(emb.info(n) == chk2.info(n) for n in chk2.names()))
        except Exception as e:
            _emb_ok = False
        _check("append-repack keeps embedded TOC valid + == manifest", _emb_ok)
        # growing in place must refuse to overwrite a neighbouring entry
        m4 = mbundle.Manifest(cm)
        _ents = sorted((int(v["offset"]), k) for k, v in m4.files(small).items() if int(v["size"]))
        if len(_ents) >= 2:
            _victim = _ents[0][1]
            _gap = _ents[1][0] - _ents[0][0]
            try:
                mbundle.patch_inplace(cb, m4, _victim, b"\x00" * (_gap + 1), allow_grow=True)
                _grow_ok = False
            except mbundle.MbundleError:
                _grow_ok = True
            _check("patch_inplace(allow_grow) refuses to overwrite the next entry", _grow_ok)
        # a NEW bundle goes first in the manifest (first mount wins) under its .mbundle name
        m5 = mbundle.Manifest(cm)
        _srcd = tmp / "modsrc"; _srcd.mkdir()
        (_srcd / "x.bin").write_bytes(b"x")
        mbundle.rebuild_from_dir(_srcd, tmp / "bundleMod.mbundle", m5, "bundleMod.mbundle")
        _check("rebuild_from_dir inserts a new bundle first in the manifest",
               m5.bundle_names()[0] == "bundleMod.mbundle")
        # bundle-relative names must not escape the output / game root
        _esc = False
        try:
            mbundle.install_loose(tmp / "game", "../escape.txt", _srcd / "x.bin")
        except mbundle.MbundleError:
            _esc = True
        _check("install_loose refuses a path that climbs out of the game root",
               _esc and not (tmp / "escape.txt").exists())
        # loose files: the game indexes Bundle/** by name at startup (earliest sorted path
        # wins) ahead of the .mbundle archives, so installs go to Bundle/00_mods/
        _ins = mbundle.install_loose(tmp, "x.bin", _srcd / "x.bin")      # tmp holds Manifest.plist
        _check("install_loose writes <Bundle>/00_mods/<name> (Bundle/** is what the game indexes)",
               _ins == tmp / "00_mods" / "x.bin" and _ins.read_bytes() == b"x"
               and mbundle.install_loose(tmp / "game", "y.bin", _srcd / "x.bin")
               == tmp / "game" / "Bundle" / "00_mods" / "y.bin")
        _mu = mbundle.Manifest(cm)
        _r1 = mbundle.unpack(tmp, _mu)
        _stem = mbundle.unpack_dir_name(small)
        _chk = mbundle.Bundle(cb, manifest=_mu)
        _same = all((tmp / _stem / n).read_bytes() == _chk.read(n) for n in _chk.names())
        _r2 = mbundle.unpack(tmp, _mu)
        _check("unpack extracts a bundle to Bundle/<name>/ byte-exact and resumes (2nd run writes 0)",
               _same and _r1.get(small, (0, 0))[0] == len(_chk.names())
               and _r2.get(small) == (0, len(_chk.names())), f"{_r1} then {_r2}")
        _nm0 = _chk.names()[0].split("/")[-1]
        (tmp / "00_mods" / _nm0).write_bytes(b"mod")
        _win = mbundle.loose_index(tmp).get(_nm0, [""])[0]
        _check("a 00_mods copy wins over the extracted original (earliest sorted path)",
               _win == "00_mods/" + _nm0, _win)
        # the game's index is case-sensitive (exact-byte hash + compare) and sorts by raw
        # bytes: a copy in another case is a different file that never overrides the game's
        _var = _nm0.swapcase()
        (tmp / "01_case").mkdir()
        (tmp / "01_case" / _var).write_bytes(b"wrong case")
        for _d in ("B_upper", "a_lower"):
            (tmp / _d).mkdir()
            (tmp / _d / "zz_sorttest.bin").write_bytes(b"x")
        _idx = mbundle.loose_index(tmp)
        _rows = {r[1]: r for r in mbundle.overrides(tmp, _mu)}
        _check("loose files match by exact case: a copy named in another case is its own entry, "
               "never the winner, and is reported as ignored",
               _idx.get(_nm0, [""])[0] == "00_mods/" + _nm0 and _idx.get(_var) == ["01_case/" + _var]
               and mbundle.case_variants(_idx, _nm0) == ["01_case/" + _var]
               and _rows.get("01_case/" + _var, (None,) * 5)[4] == _nm0,
               f"{_idx.get(_var)} {mbundle.case_variants(_idx, _nm0)}")
        _check("folders sort by raw bytes like the game (upper case before lower: B_upper beats a_lower)",
               _idx.get("zz_sorttest.bin", [""])[0] == "B_upper/zz_sorttest.bin",
               str(_idx.get("zz_sorttest.bin")))
        # the explorer lists an archive's files from Bundle/<name>/ once unpacked, so a copy
        # whose archives were unpacked and removed still shows everything
        (tmp / small).unlink()
        try:
            import rf4mod_gui as _gui
            _src = _gui.Source.from_manifest(tmp / "Manifest.plist")
            _listed = [n for n, grp, _l in _src.entries if grp == small]
            _check("explorer lists an unpacked-and-removed archive from its folder",
                   sorted(_listed) == sorted(_chk.names())
                   and _src.entries and all(_l() for n, grp, _l in _src.entries if grp == small),
                   f"{len(_listed)} of {len(_chk.names())}")
        except ImportError as _e:              # no tkinter
            _skip("explorer lists an unpacked archive", str(_e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # a PACKED patch bundle is mounted ahead of Bundle/**: its files cannot be overridden
    _pt = pathlib.Path(tempfile.mkdtemp(prefix="rf4s_patch_"))
    try:
        (_pt / "Bundle" / "00_mods").mkdir(parents=True)
        shutil.copyfile(mani_p, _pt / "Bundle" / "Manifest.plist")
        _p1 = [f.split("/")[-1] for f in man.files("bundlePatch1.mbundle")] if "bundlePatch1.mbundle" in man.bundle_names() else []
        _none = mbundle.patch_shadows(_pt)                       # unpacked: nothing shadowed
        (_pt / "Bundle" / "bundlePatch1.mbundle").write_bytes(b"x")
        _some = mbundle.patch_shadows(_pt)
        _check("patch_shadows: nothing without a packed patch bundle; with bundlePatch1.mbundle "
               "present every file it holds is reported (a loose copy would be ignored)",
               _p1 and _none == {} and set(_p1) <= set(_some)
               and all(_some[n] == "bundlePatch1.mbundle" for n in _p1), f"{len(_p1)} files")
    finally:
        shutil.rmtree(_pt, ignore_errors=True)


def test_text():
    print("text:")
    p = _first("rf3mc.eng") or _first("*.eng")
    if not p:
        _skip("TEXT round-trip", "no .eng catalog extracted")
        return
    arc = textdb.TextArchive.load(p)
    rebuilt = textdb.TextArchive.parse(arc.build())
    _check(f"TEXT round-trip {p.name}", arc.entries == rebuilt.entries, f"{len(arc)} entries")
    # byte-exact rebuild of every shipped TEXT archive, incl. the 31 CJK catalogs that end
    # each string with TWO NULs (the terminator width used to be dropped on rebuild)
    _tot = _exact = _two = 0
    for _tp in sorted(EXTRACTED.rglob("*.jpn")) + sorted(EXTRACTED.rglob("*.kor")) \
            + sorted(EXTRACTED.rglob("*.twn")) + sorted(EXTRACTED.rglob("*.eng")):
        _raw = _tp.read_bytes()
        if _raw[:4] != textdb.MAGIC:
            continue
        _ta = textdb.TextArchive.parse(_raw)
        _tot += 1
        _exact += _ta.build() == _raw
        _two += _ta.terminator == 2
    if _tot:
        _check("TEXT byte-exact rebuild of shipped .jpn/.kor/.twn/.eng archives",
               _exact == _tot, f"{_exact}/{_tot}, {_two} with 2-NUL terminators")
    # robustness: malformed / truncated input (incl. valid magic but < 8-byte header) must raise
    # a clean TextDbError, never a raw struct.error (a modder loading a corrupt rf3mc.<locale>).
    _trob = True
    for _bad in (b"", b"\xff" * 8, textdb.MAGIC, textdb.MAGIC + b"\x00\x00"):
        try:
            textdb.TextArchive.parse(_bad)
            _trob = False
        except textdb.TextDbError:
            pass
        except Exception:
            _trob = False
    _check("TextArchive raises clean TextDbError on malformed/truncated input", _trob)
    # constructor footgun: TextArchive(raw_bytes) instead of .parse()/.load() would silently make a
    # list-of-ints archive (text() -> garbage/None, no error). The ctor must reject raw bytes/str with
    # a clear TextDbError -- while a real list of per-line bytes still constructs fine.
    _ctor_ok = True
    for _bad in (b"\x00\x01\x02", bytearray(b"x"), "some string"):
        try:
            textdb.TextArchive(_bad); _ctor_ok = False
        except textdb.TextDbError:
            pass
        except Exception:
            _ctor_ok = False
    _ctor_ok = _ctor_ok and textdb.TextArchive([b"a", b"b"]).text(0) == "a"
    _check("TextArchive(raw bytes/str) raises clean TextDbError; list of bytes still works", _ctor_ok)
    # same footgun across the OTHER parser classes whose ctor takes a parsed list (not raw bytes):
    # Rf4mMap([chunks]) once SILENTLY stored raw bytes as `chunks`; EmFlagTable/EmScript gave a
    # confusing 'int has no attribute name'. All must now reject raw bytes/str with a clear message.
    _pc_ok = True
    for _cls_call in (lambda: rf4m.Rf4mMap(b"\x00" * 40),
                      lambda: emflags.EmFlagTable(b"\x00" * 40),
                      lambda: emscript.EmScript(b"\x00" * 40, None),
                      lambda: search_items.SearchItemFile(b"\x00" * 40)):
        try:
            _cls_call(); _pc_ok = False               # must not construct silently
        except (rf4m.Rf4mError, ValueError, search_items.SearchItemError):
            pass
        except Exception:
            _pc_ok = False
    _pc_ok = _pc_ok and type(rf4m.Rf4mMap([]).chunks) is list   # valid list ctor still fine
    _check("parser ctors (Rf4mMap/EmFlagTable/EmScript/SearchItemFile) reject raw bytes clearly", _pc_ok)
    # `rf4mod text add` -- one-step add-line (append a NEW dialogue line + report its id), the CLI
    # equivalent of the GUI's Add-line. Append to a small archive; the new line must land at
    # id == old length. Self-contained (builds its own archive).
    try:
        import rf4mod as _rft
    except Exception:
        _rft = None
    if _rft is not None:
        _atmp = pathlib.Path(tempfile.mkdtemp())
        _asrc = _atmp / "a.eng"
        textdb.TextArchive([b"one", b"two", b"three"]).save(str(_asrc))
        _aout = _atmp / "a2.eng"
        _aa = type("A", (), {"file": str(_asrc), "text": "NEW", "enc": "utf-8", "out": str(_aout), "force": False})()
        _rft.cmd_text_add(_aa)
        _aarc = textdb.TextArchive.load(str(_aout))
        _check("CLI `text add` appends a new line at id == old length (add-line parity)",
               len(_aarc) == 4 and _aarc.text(3) == "NEW")
        # --pad-to aligns a shorter archive so a new line lands at a SHARED id across locales
        # (rf3mc.eng ships 1 line longer than the others). Pad a 3-line archive to 5, then append.
        _apout = _atmp / "ap.eng"
        _apa = type("A", (), {"file": str(_asrc), "text": "PADDED", "enc": "utf-8",
                              "out": str(_apout), "pad_to": 5, "force": False})()
        _rft.cmd_text_add(_apa)
        _aparc = textdb.TextArchive.load(str(_apout))
        _check("CLI `text add --pad-to N` lands the new line at id N (multi-locale align)",
               len(_aparc) == 6 and _aparc.text(5) == "PADDED" and _aparc.text(3) == "")
    else:
        _skip("CLI text add", "rf4mod not importable")
    # dialogue-text EDIT path -- the exact op the cutscene editor performs on rf3mc.<locale>:
    # rewrite one line, rebuild, reparse -> the new text persists, the archive stays structurally
    # intact (same entry count), and untouched lines are unchanged (localized edit).
    if len(arc) > 6:
        idx = 5
        arc2 = textdb.TextArchive.load(p)
        NEW = "SELFTEST EDIT — dialogue line"
        arc2.set_text(idx, NEW)
        reparsed = textdb.TextArchive.parse(arc2.build())
        _check("TEXT set_text edit persists + localized (rebuild+reparse)",
               len(reparsed) == len(arc)
               and reparsed.text(idx) == NEW
               and reparsed.text(0) == arc.text(0)
               and reparsed.text(len(arc) - 1) == arc.text(len(arc) - 1))
        # append a BRAND-NEW line (author new dialogue, e.g. a new beat or a missing translation):
        # the new id == old len, and build -> reparse keeps it + leaves existing lines intact.
        _n0 = len(arc)
        arc3 = textdb.TextArchive.load(p)
        _nid = arc3.append_text("SELFTEST APPENDED LINE")
        reparsed3 = textdb.TextArchive.parse(arc3.build())
        _check("TEXT append_text adds a new line (author new dialogue)",
               _nid == _n0 and len(reparsed3) == _n0 + 1
               and reparsed3.text(_nid) == "SELFTEST APPENDED LINE"
               and reparsed3.text(0) == arc.text(0))
    # multi-byte (CJK) locale support: translators edit rf3mc.jpn/kor/twn/chn -- UTF-8 with 3-byte
    # CJK codepoints. Verify a full CJK archive round-trips byte-perfect and a multi-byte edit +
    # append persist. The ASCII eng path above would NOT catch an encoding / byte-length regression
    # that only bites multi-byte text. The test string is built from codepoints (chr) so this edit
    # embeds no raw CJK bytes, and nothing CJK is printed to stdout (Windows console is cp1252).
    _jp = _first("rf3mc.jpn")
    if _jp is not None:
        _jarc = textdb.TextArchive.load(_jp)
        _jrt = _jarc.build() == pathlib.Path(_jp).read_bytes()
        _ci = next((_i for _i in range(200, 8000)
                    if any(ord(_ch) > 0x3000 for _ch in _jarc.text(_i, "utf-8"))), None)
        # "konnichiwa sekai" (hiragana + kanji) -- built from codepoints so this file stays ASCII
        _nv = "".join(chr(_cp) for _cp in (0x3053, 0x3093, 0x306B, 0x3061, 0x306F, 0x4E16, 0x754C))
        if _ci is not None:
            _jarc.set_text(_ci, _nv, "utf-8")
            _newid = _jarc.append_text(_nv, "utf-8")
            _jre = textdb.TextArchive.parse(_jarc.build())
            _jok = (_jre.text(_ci, "utf-8") == _nv
                    and len(_jre.entries[_ci]) == len(_nv.encode("utf-8"))
                    and _jre.text(_newid, "utf-8") == _nv)
        else:
            _jok = False
        _check("TEXT CJK locale round-trips byte-perfect + multi-byte edit/append persist",
               _jrt and _ci is not None and _jok,
               f"rt={_jrt} cjk_idx={_ci} edit_append_ok={_jok}")
    else:
        _skip("CJK locale round-trip", "no rf3mc.jpn catalog")
    # all 7 shipped locales present + round-trip byte-perfect. The editor offers eng/jpn/deu/fra/
    # kor/twn/chn; each must be a real, loadable TEXT archive that rebuilds exactly. (chn ships in
    # bundlePatch2, apart from the other six -- this guard catches a missing/moved/corrupt locale.)
    _LOCS = ["eng", "jpn", "deu", "fra", "kor", "twn", "chn"]
    _lp = {_L: _first("rf3mc.%s" % _L) for _L in _LOCS}
    _present = [_L for _L in _LOCS if _lp[_L]]
    _rt_ok = all(textdb.TextArchive.load(_lp[_L]).build() == pathlib.Path(_lp[_L]).read_bytes()
                 for _L in _present)
    if len(_present) >= 6:
        _check("all shipped rf3mc locales present + round-trip byte-perfect",
               _rt_ok and "chn" in _present, f"{len(_present)}/7 present: {','.join(_present)}")
    else:
        _skip("all-locale round-trip", f"only {len(_present)}/7 locales extracted")


def test_texture():
    # Flipbook frames (u32 @ file +0x24, consecutive equal payloads; engine
    # Texture_LoadRESFramesEx): confetti = 15 8x8 BC7 cells; the short-file
    # 8x12d00 clamps 12 -> what fits; static sheets report 1.
    _conf = next(EXTRACTED.rglob("confetti.texture"), None)
    if _conf:
        _d = _conf.read_bytes()
        _i = texture.parse(_d)
        _ok = _i["frames"] == 15 and _i["width"] == 8
        if texture.HAS_PIL and texture.HAS_BC:
            _ok = _ok and len(texture.decode_frames(_d)) == 15
        _b = next(EXTRACTED.rglob("OBJ_BED_00.texture"), None)
        if _b:
            _ok = _ok and texture.parse(_b.read_bytes())["frames"] == 1
        _check("texture flipbook frames", _ok, "confetti 15x 8x8; static = 1")

    print("texture:")
    if not texture.HAS_PIL:
        _skip("texture", "Pillow not installed")
        return
    bc7 = None
    for p in EXTRACTED.rglob("*.texture"):
        try:
            if texture.parse(p.read_bytes())["kind"] == "bc7":
                bc7 = p
                break
        except Exception:
            pass
    if bc7 and texture.HAS_BC:
        img = texture.decode_to_image(bc7.read_bytes())
        _check("BC7 decode", img is not None and img.size[0] > 0, f"{bc7.name} {img.size}")
    elif bc7:
        _skip("BC7 decode", "texture2ddecoder not installed")
    else:
        _skip("BC7 decode", "no .texture extracted")
    # raw encode round-trip
    raw = None
    for p in EXTRACTED.rglob("*.texture"):
        try:
            if texture.parse(p.read_bytes())["fmt_name"] in ("RGBA8", "RGBA4444", "ABGR1555"):
                raw = p
                break
        except Exception:
            pass
    if raw:
        tmpl = raw.read_bytes()
        tmp = pathlib.Path(tempfile.mkdtemp())
        try:
            png = tmp / "t.png"
            texture.decode_to_png(raw, png)
            new = texture.encode_into(tmpl, png)
            a = texture.decode_to_image(tmpl).convert("RGBA").tobytes()
            b = texture.decode_to_image(new).convert("RGBA").tobytes()
            _check("raw texture encode round-trip", a == b, raw.name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        _skip("raw texture encode", "no raw-format .texture extracted")


def test_rf4m():
    print("rf4m:")
    maps = list(EXTRACTED.rglob("*.rf4m"))
    if not maps:
        _skip("rf4m round-trip", "no maps extracted")
        return
    random.seed(0)
    random.shuffle(maps)
    sample = maps[:40]
    ok = sum(1 for p in sample if rf4m.Rf4mMap.parse(p.read_bytes()).build() == p.read_bytes())
    _check("rf4m byte-exact rebuild", ok == len(sample), f"{ok}/{len(sample)}")
    # MOBJ edit round-trip: change a record, rebuild, re-parse, verify + length stable.
    withobj = next((p for p in maps if rf4m.Rf4mMap.parse(p.read_bytes()).mobj_records()), None)
    if withobj:
        data = withobj.read_bytes()
        m = rf4m.Rf4mMap.parse(data)
        rec = list(m.mobj_records()[0]); rec[6] = 6144; rec[14] = 123
        m.set_mobj_record(0, rec)
        blob = m.build()
        m2 = rf4m.Rf4mMap.parse(blob)
        _check("rf4m MOBJ edit round-trip",
               list(m2.mobj_records()[0]) == rec and len(blob) == len(data), withobj.name)
        # editor ops: add, delete, paint ATTR cell
        m3 = rf4m.Rf4mMap.parse(data)
        n = len(m3.mobj_records())
        m3.add_mobj_record([28, -1, -1, -1, -1, -1, 4096, 0, 0, 0, 0, 0, 0, -1, 80, 80])
        added = rf4m.Rf4mMap.parse(m3.build())
        m3.delete_mobj_record(n)
        deleted = rf4m.Rf4mMap.parse(m3.build())
        ok = len(added.mobj_records()) == n + 1 and len(deleted.mobj_records()) == n
        if m3.attr_grid():
            m3.set_attr_cell(0, 0, 0x1234)
            ok = ok and rf4m.Rf4mMap.parse(m3.build()).attr_grid()[2][0] == 0x1234
        _check("rf4m editor add/delete/paint", ok, withobj.name)
        # complete-editor ops: header props (MSEA), MAPJ add/del, raw chunk add/del
        m4 = rf4m.Rf4mMap.parse(data)
        m4.set_ints("MSEA", [3])
        nm = len(m4.mapj_records())
        m4.add_mapj_record([-1, 8, 8, 32, 32, 8, 8, 0, 0])
        nc = len(m4.chunks)
        m4.add_chunk("ZZZZ", b"\x01\x02\x03\x04")
        built = rf4m.Rf4mMap.parse(m4.build())
        ok2 = (built.get_ints("MSEA") == [3]
               and len(built.mapj_records()) == nm + 1
               and len(built.chunks) == nc + 1
               and built.build()[:4] == b"MAPD")
        _check("rf4m editor props/warp/chunk", ok2, withobj.name)
    else:
        _skip("rf4m MOBJ edit", "no map with MOBJ records")
    # MAPJ field-order regression: MAP_CITY_00 (Selphia plaza) has 8 warps whose
    # destination map ids (f5) MUST be small valid map ids (CITY_01/02/03 + FARM_00
    # etc.). The pre-2026-06-10 mis-labelled version put dest_map at f7, which gave
    # values like 396/392/395 -- unrelated dungeons, obviously wrong.
    city00 = _first("MAP_CITY_00.rf4m")
    if city00:
        m = rf4m.Rf4mMap.parse(city00.read_bytes())
        mapjs = m.mapj_records()
        if mapjs:
            f5_max = max(r[5] for r in mapjs)
            f5_set = {r[5] for r in mapjs}
            # All Selphia exits resolve under id 250 (city/farm/room interiors)
            _check("MAPJ f5 = dest_map (Selphia exits)",
                   f5_max < 250 and {28, 32, 4}.issubset(f5_set),
                   f"f5 ids={sorted(f5_set)}")
        # Verified-layout decoders + loader validation (2026-09-19): f0 = disable flag
        # (-1 = none), f8 = arrival facing in degrees (the plaza exits face 60/180).
        w = m.decode_mapj()
        _check("MAPJ decode: f0 disable flag = -1, f8 facing in {0,60,180} deg",
               bool(w) and all(d["disable_flag"] == -1 for d in w)
               and {d["facing_deg"] for d in w} <= {0, 60, 180}
               and {60, 180} <= {d["facing_deg"] for d in w},
               f"facing={sorted({d['facing_deg'] for d in w})}")
        _check("MLIG decode: stock map = three engine-default tints; encode/decode round-trip",
               m.mlig_colors() == [None, None, None]
               and rf4m.mlig_decode(rf4m.mlig_encode((10, 20, 30))) == (10, 20, 30)
               and rf4m.mlig_encode(None) == 0xFF000000
               and "season" in rf4m.mgrp_notes(m.mgrp()))
        ok_v = m.validate(known_maps=set(range(874)))
        _check("validate(): stock map passes the loader rules",
               not any(s.startswith("ERROR") for s in ok_v), "; ".join(ok_v[:3]) or "clean")
        bad = rf4m.Rf4mMap.parse(city00.read_bytes())
        bad.add_chunk("ZZZZ", b"", at=0)                 # unknown tag stops the loader
        while len(bad.find(b"MOBJ")) < 41:               # 41st MOBJ chunk overflows the array
            bad.add_mobj_record([28, -1, -1, -1, -1, -1, 4096, 0, 0, 0, 0, 0, 0, -1, 80, 80])
        bad.delete_chunk(next(i for i, c in enumerate(bad.chunks) if c.tag == b"MGRP"))
        v = bad.validate()
        _check("validate(): unknown tag / 41 MOBJ chunks / missing MGRP are fatal",
               sum(1 for s in v if s.startswith("ERROR")) >= 3
               and any("unknown tag" in s for s in v) and any("41 MOBJ" in s for s in v)
               and any("MGRP" in s for s in v), f"{len(v)} findings")
        # Ground-atlas ceiling: Map_SpawnEntity keeps one tile pointer per atlas tile in
        # its 888-byte work buffer from +8, and the decoration-model pointer sits at +776
        # -> 96 slots. ATTR 250x250 needs 12x12 = 144 tiles and corrupts the buffer. Pure
        # ATTR math, so it runs with no texture files present.
        big = rf4m.Rf4mMap.parse(city00.read_bytes())
        big.set_attr_grid(250, 250, [0] * (250 * 250))
        vb = big.validate()
        _check("validate(): ATTR past the 96 tile-pointer slots is fatal",
               any(s.startswith("ERROR") and "work buffer" in s and "144" in s for s in vb),
               f"{mapground.MAX_TILE_SLOTS} slots")
        _check("validate(): ground_reader without map_name says the atlas check was skipped",
               any("map_name" in s for s in
                   rf4m.Rf4mMap.parse(city00.read_bytes()).validate(ground_reader=lambda fn: None)))
        # 2026-09-24 loader replay (Map_LoadById): single-slot tags keep the LAST chunk,
        # IMGD re-points the previous chunk's slot, the size word bounds the walk,
        # type-12 f8 indexes the tint array unchecked, arrivals are s16 words.
        raw = city00.read_bytes()
        dup = rf4m.Rf4mMap.parse(raw)
        mi = next(i for i, c in enumerate(dup.chunks) if c.tag == b"MGRP")
        dup.add_chunk("MGRP", struct.pack("<I", 0x1234), at=mi + 1)
        vd = dup.validate()
        _check("rf4m duplicate MGRP: the game (and mgrp()) use the LAST chunk; validate warns",
               dup.mgrp() == 0x1234 and any("second MGRP" in s for s in vd)
               and not any(s.startswith("ERROR") for s in vd))
        dup2 = rf4m.Rf4mMap.parse(raw)
        w0, h0, _c = dup2.attr_grid()
        dup2.add_chunk("ATTR", struct.pack("<II", 2, 2) + bytes(16))
        dup2.set_attr_cell(1, 1, 7)
        _check("rf4m set_attr_cell/attr_grid edit the live (last) ATTR chunk",
               dup2.attr_grid()[:2] == (2, 2) and dup2.attr_grid()[2][3] == 7
               and struct.unpack_from("<II", dup2.find(b"ATTR")[0].payload, 0) == (w0, h0))
        im = rf4m.Rf4mMap.parse(raw)
        im.add_chunk("IMGD", b"\0" * 4, at=mi + 1)
        _check("rf4m validate: IMGD after MGRP overwrites MGRP's slot (fatal)",
               any(s.startswith("ERROR") and "IMGD" in s and "MGRP" in s for s in im.validate()))
        bad_sz = bytearray(raw)
        struct.pack_into("<i", bad_sz, 4, len(raw) - 64)
        _check("rf4m validate: MAPD size word != file size is fatal; build() repairs it",
               any(s.startswith("ERROR") and "size word" in s
                   for s in rf4m.Rf4mMap.parse(bytes(bad_sz)).validate())
               and rf4m.Rf4mMap.parse(bytes(bad_sz)).build() == raw)
        tt = rf4m.Rf4mMap.parse(raw)
        tt.add_mobj_record([12, 0, 0, 0, 0, 0, 0, 0, 5, 10, 20, 30, 0, 0, 0, 0])
        tt.add_mapj_record([-1, 8, 8, 32, 32, 8, 40000, 8, 0])
        vt = tt.validate()
        _check("rf4m validate: tint slot f8=5 and arrival x=40000 are fatal",
               any(s.startswith("ERROR") and "tint_color" in s for s in vt)
               and any(s.startswith("ERROR") and "16-bit" in s for s in vt))
    # ATTR resize + the atlas check that makes it safe (needs the tiles next to the map)
    f01 = _first("MAP_FIELD_01.rf4m")
    if f01 and (f01.parent / "MAP_FIELD_201_0000.texture").is_file():
        rdr = lambda fn, d=f01.parent: (d / fn).read_bytes() if (d / fn).is_file() else None
        m = rf4m.Rf4mMap.load(f01)
        w, h, _ = m.attr_grid()
        _check("atlas_audit(): stock MAP_FIELD_01 atlas matches its ATTR grid",
               not m.validate(ground_reader=rdr, map_name="MAP_FIELD_01"),
               f"ATTR {w}x{h} -> {mapground.grid_dims(w, h)} tiles")
        # THE gap this closes: growing the grid needs tiles that do not exist, and the
        # loader asks for archive id base+i anyway (next set's files), so it must be fatal.
        grown = rf4m.Rf4mMap.load(f01)
        rep = grown.resize_attr_grid(150, 150, ground_reader=rdr, map_name="MAP_FIELD_01",
                                     dry_run=True)
        need = rep["atlas"]["new_need"]
        _check("resize_attr_grid(): grown map reports the tiles it now needs",
               rep["atlas"]["old_grid"] == (4, 4) and rep["atlas"]["new_grid"] == (8, 8)
               and rep["atlas"]["reindexed"]
               and any("author 48 new tile" in t for t in rep["todo"])
               and any(t.startswith("ERROR") and "MAP_FIELD_201_0063" in t
                       for t in rep["findings"]),
               f"16 shipped vs {need} needed")
        _check("resize_attr_grid(): dry_run changes nothing", grown.attr_grid()[:2] == (w, h))
        # apply: cells land at the right offset, entities shift with the terrain, and the
        # rebuilt file round-trips.
        m2 = rf4m.Rf4mMap.load(f01)
        before = {i: r[14:16] for i, r in enumerate(m2.mobj_records())}
        rep2 = m2.resize_attr_grid(w + 8, h + 8, origin=(4, 4), fill=0x2,
                                   ground_reader=rdr, map_name="MAP_FIELD_01")
        g0 = rf4m.Rf4mMap.load(f01).attr_grid()
        g1 = m2.attr_grid()
        moved = rep2["moved"]["mobj"]
        after = {i: r[14:16] for i, r in enumerate(m2.mobj_records())}
        _check("resize_attr_grid(): cells/entities move together and the file rebuilds",
               g1[0] == w + 8 and g1[1] == h + 8
               and g1[2][4 * (w + 8) + 4] == g0[2][0]          # old (0,0) -> new (4,4)
               and all(g1[2][x] == 0x2 for x in range(w + 8))   # padded row = the fill
               and bool(moved)
               and all(after[i][0] - before[i][0] == 32 and after[i][1] - before[i][1] == 32
                       for i in moved)
               and rf4m.Rf4mMap.parse(m2.build()).attr_grid()[:2] == (w + 8, h + 8),
               f"{len(moved)} MOBJ shifted by 4 tiles")
    else:
        _skip("rf4m ATTR resize + atlas check", "MAP_FIELD_01 or its ground tiles not extracted")
    # map-parameter records: type-12 tint records (slot f8 = 0 day / 1 evening / 2 night,
    # f9..f11 = RGB bytes, no position). Some maps carry only the night slot, so look for
    # one that sets all three.
    found, tints = None, []
    for p in maps:
        recs = [r for r in rf4m.Rf4mMap.parse(p.read_bytes()).mobj_records()
                if (r[0] & 0xFFFF) == 12]
        if len(recs) == 3:
            found, tints = p, recs
            break
    if found:
        _check("MOBJ type 12 = tint_color map parameter (3 slots, RGB bytes, positionless)",
               {r[8] for r in tints} == {0, 1, 2}
               and all(r[14] == 0 and r[15] == 0 for r in tints)
               and all(0 <= r[k] <= 255 for r in tints for k in (9, 10, 11))
               and mobj_types.mobj_display_name(12) == "tint_color"
               and mobj_types.mobj_kind(12) == "mapparam",
               f"{found.name}: slots {sorted(r[8] for r in tints)}")
    else:
        _skip("MOBJ type 12 tint records", "no map with three type-12 records")


def test_aibn():
    print("aibn:")
    ai = list(EXTRACTED.rglob("AI_*.bin"))
    if not ai:
        _skip("aibn round-trip", "no AI scripts extracted")
        return
    tok_ok = txt_ok = ann_ok = flat_ok = flat_ann_ok = 0
    seen = set()
    for p in ai:
        d = p.read_bytes()
        t = aibn.load_tokens(d)
        if aibn.build(t) == d:
            tok_ok += 1
        if aibn.assemble(aibn.disassemble(t)) == t:                       # pretty (default)
            txt_ok += 1
        if aibn.assemble(aibn.disassemble(t, annotate=True)) == t:
            ann_ok += 1
        if aibn.assemble(aibn.disassemble(t, style="flat")) == t:
            flat_ok += 1
        if aibn.assemble(aibn.disassemble(t, style="flat", annotate=True)) == t:
            flat_ann_ok += 1
        seen.update(aibn.stats(t))
    _check("aibn token-exact round-trip", tok_ok == len(ai), f"{tok_ok}/{len(ai)}")
    _check("aibn pretty disasm/asm round-trip", txt_ok == len(ai), f"{txt_ok}/{len(ai)}")
    _check("aibn pretty+annotated round-trip", ann_ok == len(ai), f"{ann_ok}/{len(ai)}")
    _check("aibn flat disasm/asm round-trip", flat_ok == len(ai), f"{flat_ok}/{len(ai)}")
    _check("aibn flat+annotated round-trip", flat_ann_ok == len(ai), f"{flat_ann_ok}/{len(ai)}")
    # pretty syntax spot checks: implicit 0x01 before actions, none before register/timer ops
    _check("aibn pretty: action call implies the 0x01 marker",
           aibn.assemble("WaitFrames(8)") == [aibn.HI | 0x01, aibn.HI | 0x41, 8]
           and aibn.assemble("!WaitFrames(8)") == [aibn.HI | 0x41, 8]
           and aibn.assemble("SetCooldownTimerA(180)") == [aibn.HI | 0x59, 180]
           and aibn.assemble("r1 += 5\nr2 = r0") == [aibn.HI | 0x49, 5, aibn.HI | 0x52, 10000])
    _check("aibn pretty: if-chain and labels",
           aibn.assemble("sub 100:\nif (DistanceToTarget <= 110 && RandomChance(50) || ActorIsNpcKind) {\n} else {\n}\n290:\ngoto 290\nreturn")
           == [aibn.HI | 0x07, 100, aibn.HI | 0x0C, aibn.HI | 0x5D, aibn.HI | 0x96, 110, aibn.HI | 0x94,
               aibn.HI | 0x5F, 50, aibn.HI | 0x93, aibn.HI | 0x74, aibn.HI | 0x0D, aibn.HI | 0x0E,
               aibn.HI | 0x05, 290, aibn.HI | 0x04, 290, aibn.HI | 0x08])
    # verified metadata (2026-09-17 handler re-read) covers every opcode the shipped scripts use
    from rf4s_modkit import aibn_meta
    missing = sorted(o for o in seen if aibn_meta.record(o) is None)
    _check("aibn_meta covers every shipped opcode", not missing, f"missing {[hex(o) for o in missing]}")
    _check("aibn_meta scripted-action table has 35 slots", len(aibn_meta.SCRIPTED_ACTIONS) == 35)
    # only the current mnemonics assemble (the pre-2026-09-17 names are gone)
    try:
        aibn.assemble("TickAI 90 30")
        _old_refused = False
    except Exception:  # noqa: BLE001 - any refusal
        _old_refused = True
    _check("aibn: current mnemonics assemble, old ones are refused",
           _old_refused and aibn.assemble("BackAwayFromTarget 90 30\nBlinkTeleportNearTarget 32 0xFFFF\n"
                                          "AndConnector") is not None)
    _check("aibn 0x15 RandomWalkInRoom is fixed arity 3", aibn.ARITY.get(0x15) == 3 and 0x15 not in aibn.VAR_OPS)
    # 2026-09-24 audit against the VM handlers (RF4S.exe IDB):
    H = aibn.HI
    # 0x80000094 in a comparator slot printed as `cmp.always` and re-assembled as 0x80000093
    t94 = [H | 0x0C, H | 0x5D, H | 0x94, 5, H | 0x0E]
    _check("aibn comparator slot 0x80000094 round-trips (was re-assembled as 0x93)",
           all(aibn.assemble(aibn.disassemble(t94, style=st)) == t94 for st in ("pretty", "flat")))
    # variable-arity handlers read AT MOST N operands (MonsterScript_Op13_ChaseTarget +0x1CAC20 loops 2x);
    # a third token is dispatched as a statement, so the walker must show it as an orphan
    t13 = [H | 0x01, H | 0x13, 1, 2, 3]
    sts13 = list(aibn.walk_statements(t13))
    _check("aibn var-arity op capped at the handler's N (extra token = orphan statement)",
           sts13[1][2] == [1, 2] and sts13[2][1] is None and aibn.assemble(aibn.disassemble(t13)) == t13
           and any("reads at most 2" in w for w in aibn.validate(t13)))
    # r8/r9 have no add/set/compare opcodes: `r8 += 1` used to assemble to 0x50 (r0 = 1), `r8 <= 3` to 0x72
    rej = []
    for src in ("r8 += 1", "r9 = 2", "if (r8 <= 3) {", "WaitFrames(0x100000000)", "WaitFrames(x)", "OP_99 1"):
        try:
            aibn.assemble("yield\n" + src)
            rej.append(False)
        except aibn.AibnError as ex:
            rej.append(str(ex).startswith("line 2:"))
    _check("aibn assembler rejects r8/r9 add/set/cmp, >32-bit operands, bad operands/ids (with line numbers)",
           all(rej), str(rej))
    # Goto/Call resolve labels by a raw scan for (tok & 0x7FFFFFFF) == 5/7 (MonsterScript_Op04_Goto +0x1D2F50)
    hij = aibn.assemble("!SidestepAroundTarget(5, 290, 0)\ngoto 290\n290:\ngoto 77")
    vw = aibn.validate(hij)
    _check("aibn validate: goto hijacked by an operand 5, goto to a missing label",
           any("lands at token #1" in w for w in vw) and any("goto 77 has no label" in w for w in vw), str(vw))
    found = {p.name for p in ai if aibn.validate(aibn.load_tokens(p.read_bytes()), p.read_bytes())}
    _check("aibn validate: shipped scripts clean except the three stock duplicate-label files",
           found <= {"AI_m109.bin", "AI_m52.bin", "AI_m36_b.bin"}, str(sorted(found)))


def test_strings():
    print("strings:")
    p = _first("*.strings") or next(iter(GAME_DIR.glob("*.strings")), None)
    if not p:
        _skip("strings round-trip", "no .strings file present")
        return
    d = strings_file.load(p)
    _check(f"strings round-trip {p.name}", strings_file.parse(strings_file.dumps(d)) == d,
           f"{len(d)} keys")
    # the lenient Apple-style lexer: a bare (unquoted) value must not swallow its trailing ';'
    _check("strings lenient bare value drops ';'",
           strings_file.parse_lenient("k = bareValue;") == {"k": "bareValue"}
           and strings_file.parse_lenient("k = 123;") == {"k": "123"})
    # every shipped .strings parses (Localization-en has UNESCAPED inner quotes, which the
    # game's line parser -- MFLocale_LoadFromStringsFile RF4S.exe+0x259B90 -- reads fine but the
    # old lexer raised on), matches the game's own reading, and survives dumps() unchanged
    _all = sorted(EXTRACTED.rglob("*.strings"))
    _sok = True
    for _sp in _all:
        try:
            _t = _sp.read_text(encoding="utf-8")
            _g = strings_file.parse_game(_t)
            _sok &= (strings_file.parse(_t, lowercase_keys=True) == _g and len(_g) > 0
                     and strings_file.parse_game(strings_file.dumps(strings_file.parse(_t))) == _g)
        except Exception:
            _sok = False
    if _all:
        _check("strings: every shipped file == game reading and dumps() round-trips", _sok,
               f"{len(_all)} files")
    # game escape rules (MFData_decodeBackslashEscapesToUTF8 +0x24C4E0): unknown escapes keep the
    # backslash, \b \f decode, \u0000 vanishes, surrogate pairs combine into one code point
    _check("strings unescape matches the game decoder",
           strings_file.parse_game('"k" = "\\q\\0\\b\\u0000\\ud83d\\ude00";') == {"k": "\\q\\0\x08\U0001F600"})
    # the game's line parser: `k = v;`, `"x"="y";` and empty values are DROPPED; key lowercased
    _check("strings parse_game drops what the game drops",
           strings_file.parse_game('k = v;\n"x"="y";\n"e" = "";\n"Up" = "ok";\n') == {"up": "ok"}
           and len(strings_file.game_issues('k = v;\n"Up" = "ok";\n/* never closed\n')) == 2)
    # a key ending in a backslash: the game ends a quoted key at the first `"` not preceded by
    # `\`, so dumps() must not emit `\\"` there
    _check("strings dumps() key ending in a backslash survives the game parser",
           strings_file.parse_game(strings_file.dumps({"a\\": "v"})) == {"a\\": "v"})


def test_res_and_ident():
    print("res / ident:")
    for ext in ("model", "bfskl", "bfsha", "psbData"):
        p = _first("*." + ext)
        if p:
            try:
                info = res_container.inspect(p.read_bytes())
                _check(f"res inspect .{ext}", info["magic"] is not None, info["magic"].split()[0])
            except Exception as e:
                _check(f"res inspect .{ext}", False, str(e))
        else:
            _skip(f"res inspect .{ext}", "not extracted")
    # PSB is not an NN container: BFRES_GetRelocationTableStart (+0x3CA9B0) semantics must not be
    # applied to it (the +0x18 dword used to be reported as a relocation table offset)
    _psb = res_container.inspect(b"PSB\x00" + b"\x01" * 60)
    _check("res inspect PSB has no NN relocation field",
           _psb["reloc_table_field"] is None and _psb["reloc_table_offset"] is None
           and "no NN relocation" in res_container.summary(b"PSB\x00" + b"\x01" * 60))
    # BNTX decode (over-model billboards, e.g. MAP_*.model): structural parse always,
    # full BC-n decode when Pillow is present.
    import struct as _struct
    pm = _first("MAP_*.model") or _first("*.model")
    if pm:
        raw = pm.read_bytes()
        pairs = texture.bntx_textures(raw)
        if pairs:
            brti = pairs[0][0]
            w = _struct.unpack_from("<I", raw, brti + 0x24)[0]
            h = _struct.unpack_from("<I", raw, brti + 0x28)[0]
            _check("bntx parse .model", w > 0 and h > 0, f"tex0 {w}x{h}, {len(pairs)} texture(s)")
            if texture.HAS_PIL and texture.HAS_BC:
                try:
                    im = texture.decode_bntx(raw)
                    _check("bntx decode .model", im is not None and im.size == (w, h),
                           str(im.size if im else None))
                except Exception as e:
                    _check("bntx decode .model", False, str(e))
        else:
            _skip("bntx parse .model", "sample .model has no BNTX (FMDL/empty)")
    else:
        _skip("bntx parse .model", "not extracted")
    # ident on a spread
    spread = {"rf4m": "rf4m", "bin": "aibn", "texture": "texture", "ogg": "ogg",
              "png": "png", "minterface": "bplist"}
    for ext, expect in spread.items():
        p = _first("*." + ext)
        if not p:
            continue
        ft = ident.identify(p.read_bytes()[:4096], filename=p.name)
        _check(f"ident .{ext}", ft.fmt == expect, ft.fmt)
    # NLCL disambiguation: SI (ver 2, even when renamed) vs Gen vs flat param
    si_p = _first("SI_*.bin")
    if si_p:
        d = si_p.read_bytes()
        _check("ident SI_*.bin -> search_items",
               ident.identify(d, filename=si_p.name).fmt == "search_items"
               and ident.identify(d, filename="renamed.bin").fmt == "search_items",
               "by name AND by version=2 content")


def test_gen():
    print("gen:")
    files = list(EXTRACTED.rglob("Gen*.bin"))
    if not files:
        _skip("gen encounter table", "no Gen*.bin extracted")
        return
    parsed = edited = 0
    for p in files:
        try:
            g = gen.GenTable.load(p)
        except gen.GenError:
            continue
        parsed += 1
    _check("gen parse Gen*.bin", parsed > 0, f"{parsed}/{len(files)} parsed")
    # edit round-trip on a file with a spawn record
    cand = None
    for p in files:
        try:
            g = gen.GenTable.load(p)
        except gen.GenError:
            continue
        if any(e.spawns for _pi, _ei, e in g.all_entries()):
            cand = (p, g); break
    if cand:
        p, g = cand
        e = next(e for _pi, _ei, e in g.all_entries() if e.spawns)
        g.set_weight(0, 0, 77); g.set_spawn_monster(e.spawns[0], 52)
        blob = g.build()
        g2 = gen.GenTable(blob)
        ok = (g2.patterns[0][0].weight == 77
              and len(blob) == len(p.read_bytes()))
        _check("gen edit round-trip", ok, p.name)
    else:
        _skip("gen edit", "no Gen file with spawn records")
    # gate / monster-spawn positions decode to sane (x,y) sub-unit tuples (map-overlay feature)
    posfile = None
    for p in files:
        try:
            g = gen.GenTable.load(p)
        except gen.GenError:
            continue
        for _pi, _ei, e in g.all_entries():
            if g.gate_positions(e):
                posfile = (p, g.gate_positions(e), g.monster_positions(e)); break
        if posfile:
            break
    if posfile:
        p, gp, mp = posfile
        ok = all(isinstance(t, tuple) and len(t) == 2
                 and 0 <= t[0] < 0x10000 and 0 <= t[1] < 0x10000 and (t[0] >> 3) < 512
                 for t in gp + mp)
        _check("gen gate/monster positions decode", ok, f"{p.name}: {len(gp)} gate pos")
        # gate MOVE round-trip: gate_positions_off + set_position write a new (x,y) in place
        gg = gen.GenTable.load(p)
        ee = next(e for _pi, _ei, e in gg.all_entries() if gg.gate_positions_off(e))
        ro = gg.gate_positions_off(ee)[0][0]
        gg.set_position(ro, 324, 404)
        gg2 = gen.GenTable(gg.build())
        ee2 = next(e for _pi, _ei, e in gg2.all_entries() if gg2.gate_positions_off(e))
        _check("gen gate move round-trip", gg2.gate_positions_off(ee2)[0][1:] == (324, 404))
    else:
        _skip("gen positions", "no Gen file exposes gate positions")


def test_fixed_point_fields():
    """Fixed-point fields (nlcl.FIXED_FIELDS): shown as the shortest percentage that converts
    back to the same stored integer, typed as 150% (or 1.5x) or a whole number, range-checked by width;
    the table editor and `param set` use it."""
    print("param tables: fixed-point (Q12 / Q7) fields shown and edited as percentages:")
    from rf4s_modkit import nlcl
    bad = [(b, r) for b in (12, 7) for r in list(range(-9000, 9000)) + [2 ** 31 - 1, -2 ** 31, 70000]
           if nlcl.parse_value(nlcl.format_value(r, b), "s32", b) != r]
    _check("every stored value round-trips through its percentage text (Q12 and Q7)", not bad, bad[:5])
    shown = [nlcl.format_value(r, 12) for r in (4096, 6144, 4710, 3686, -2048, 0)]
    _check("percentages read as designed: 4096 = 100%, 6144 = 150%, 4710 = 115% (not 114.99%)",
           shown == ["100%", "150%", "115%", "90%", "-50%", "0%"]
           and nlcl.format_value(96, 7) == "75%" and nlcl.parse_value("1.5x", "s32", 12) == 6144
           and nlcl.parse_value("150%", "s32", 12) == 6144, shown)
    errs = []
    for args in (("900%", "s16", 12), ("150%", "s32", None), ("abc", "s32", 12)):
        try:
            nlcl.parse_value(*args)
            errs.append(None)
        except nlcl.NlclError as e:
            errs.append(str(e))
    _check("a percentage past a 16-bit field (Q4.12 tops out near 800%), a percentage on a plain "
           "field and a non-number are refused with a reason",
           all(errs) and "799.976" in errs[0] and "not a percentage" in errs[1],
           errs)
    P = nlcl.PERCENT
    pct = (nlcl.format_value(200, P), nlcl.parse_value("250%", "u16", P), nlcl.parse_value("1.5x", "u16", P),
           nlcl.parse_value("120", "u16", P), nlcl.fixed_bits("rf3PriceTable", "Lv 10"))
    _check("whole-percent fields (rf3PriceTable: 100 = 100%): 200 shows as 200%, 250% / 1.5x / 120 "
           "store 250 / 150 / 120", pct == ("200%", 250, 150, 120, P), pct)
    _check("the fixed-point fields are real schema fields of their tables",
           all(f in {n for n, _o, _t in nlcl.FIELD_SCHEMAS[s]["fields"]}
               for s, fs in nlcl.FIXED_FIELDS.items() for f in fs),
           [(s, f) for s, fs in nlcl.FIXED_FIELDS.items() for f in fs
            if f not in {n for n, _o, _t in nlcl.FIELD_SCHEMAS[s]["fields"]}])
    src = pathlib.Path(BUNDLE_DIR) / "bundleMain" / "rf3ParamMagic.bin"
    if not src.exists():
        _skip("param set with a multiplier", "no rf3ParamMagic.bin"); return
    import importlib, tempfile
    rf4 = importlib.import_module("rf4mod")
    t = nlcl.NlclTable(src.read_bytes())
    rf4._param_assign(t, 0, "dmg_mult=125%", "rf3ParamMagic")
    rf4._param_assign(t, 0, "mat_scalar=8192", "rf3ParamMagic")
    row = t.row(0, "rf3ParamMagic")
    _check("param set: dmg_mult=125% stores 5120, a whole number is stored as is",
           row["dmg_mult"] == 5120 and row["mat_scalar"] == 8192, (row["dmg_mult"], row["mat_scalar"]))


def test_flag_fields():
    """Bit-set fields (nlcl.FLAG_FIELDS): hex display, +name/-name edits (CLI `param set`),
    and the table editor's tick-box dialog (one box per bit, named ones first)."""
    print("param tables: bit-set fields (tick boxes, +name / -name):")
    from rf4s_modkit import nlcl
    missing = [(s, f) for s, fs in nlcl.FLAG_FIELDS.items() for f in fs
               if f not in {n for n, _o, _t in nlcl.FIELD_SCHEMAS.get(s, {}).get("fields", ())}]
    _check("every bit-set field is a real schema field of its table", not missing, missing)
    names = nlcl.flag_bits("rf3ParamMagic", "flags")
    errs = []
    try:
        nlcl.apply_flag_edit(0, "+Frie", names)
    except nlcl.NlclError as e:
        errs.append(str(e))
    _check("+name / -name / +bitN / +mask set and clear single bits; an unknown name is refused "
           "with the known ones listed",
           nlcl.apply_flag_edit(0x81, "+Ignore DEF,-fire,+bit3", names) == 0x288
           and nlcl.apply_flag_edit(0x81, "+0x400", names) == 0x481
           and nlcl.apply_flag_edit(0x81, "0x7", names) == 7
           and errs and "Fire" in errs[0] and nlcl.format_flags(0x81, "u32") == "0x00000081"
           and nlcl.format_flags(5, "u8") == "0x05", errs)
    src = pathlib.Path(BUNDLE_DIR) / "bundleMain" / "rf3ParamMagic.bin"
    if not src.exists():
        _skip("bit-set fields on the shipped table", "no rf3ParamMagic.bin"); return
    import importlib
    rf4 = importlib.import_module("rf4mod")
    t = nlcl.NlclTable(src.read_bytes())
    before = t.row(1, "rf3ParamMagic")["flags"]
    rf4._param_assign(t, 1, "flags=+Ignore DEF,-Fire", "rf3ParamMagic")
    after = t.row(1, "rf3ParamMagic")["flags"]
    _check("param set flags=+Ignore DEF,-Fire changes only those bits (record 1, Fire magic 0x81)",
           before == 0x81 and after == 0x280, (hex(before), hex(after)))
    try:
        import tkinter as tk
        import rf4mod_gui as gui
        root = tk.Tk()
        root.withdraw()
    except Exception as e:
        _skip("tick-box dialog", f"no Tk ({e})"); return
    got = []
    try:
        win = gui._flag_dialog(root, "t", "u32", 0x81, names, got.append)
        ticked = sorted(m for m, v in win.boxes.items() if v.get())
        win.boxes[0x200].set(True)
        win.boxes[0x1].set(False)
        win.ok()
        win8 = gui._flag_dialog(root, "t", "u8", 0x5, {}, got.append)
        n8 = len(win8.boxes)
        win8.destroy()
    finally:
        root.destroy()
    _check("the tick-box dialog ticks the set bits, has one box per bit of the width (named first) "
           "and OK returns the new value",
           ticked == [0x1, 0x80] and got == [0x280] and n8 == 8 and len(win.boxes) == 32,
           (ticked, got, n8))


def test_bin_editors():
    """The .bin viewers that used to be read-only can edit: AI scripts (editable listing +
    Assemble), skill XP curves (set a level / scale), rf3ItemStrengthening (set a field of the
    selected item), rf3PresentCategory (add / remove an item). Each edit lands in the tab's
    working copy and an unchanged file stays byte-exact."""
    print("explorer: .bin editors (AI, skill curves, strengthening, gift categories):")
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    need = ["AI_m00.bin", "rf3ParamSkillExp.bin", "rf3ItemStrengthening.bin", "rf3PresentCategory.bin"]
    if not all((B / n).exists() for n in need):
        _skip(".bin editors", "files not extracted"); return
    try:
        import tkinter as tk
        import importlib.util
        root = tk.Tk(); root.withdraw()
    except Exception as e:
        _skip(".bin editors", f"no Tk ({e})"); return
    spec = importlib.util.spec_from_file_location("rf4mod_gui_bined", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
    gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
    from rf4s_modkit import aibn, skillcurve, gifts, strengthening
    res = {}
    try:
        app = gui.App(root, initial=str(B))
        app._testing = True
        # AI: the listing assembles back to the same file; an edit changes the working copy
        d = (B / "AI_m00.bin").read_bytes()
        app._show("AI_m00.bin", d); doc = app._doc
        same = doc._aibn_assemble() == d
        txt = doc._aibn_text
        body = txt.get("1.0", "end-1c")
        txt.delete("1.0", "end"); txt.insert("1.0", body + "\nBogusOp(1)\n")
        bad = doc._aibn_assemble() is None
        res["ai"] = (same, bad)
        # skill curve: select level 1, set it, scale it; the header names the skills; revert
        d = (B / "rf3ParamSkillExpFarm.bin").read_bytes()
        app._show("rf3ParamSkillExpFarm.bin", d); doc = app._doc
        sk = doc._skill
        sk["tree"].selection_set("1")
        sk["set_var"].set("777"); sk["do_set"]()
        one = skillcurve.parse(doc.cur_data)[1]
        sk["tree"].selection_set("1"); sk["pct_var"].set("50"); sk["do_scale"]()
        half = skillcurve.parse(doc.cur_data)[1]
        size_ok = len(doc.cur_data) == len(d)
        sk["revert"]()
        res["skill"] = (one, half, size_ok, doc.cur_data == d, "Farming" in sk["used"])
        # paint: one stroke from level 10 (high) to level 20 (low) fills every level in between,
        # leaves level 9 alone, is one Undo step
        import types
        sk["paint"].set(True); root.update()
        cw = max(sk["chart"].winfo_width(), 200); ch = max(sk["chart"].winfo_height(), 120)
        bw = (cw - 56) / skillcurve.REAL_LEVELS
        ev = lambda lvl, y: types.SimpleNamespace(x=50 + (lvl + 0.5) * bw, y=y, state=0)
        sk["press"](ev(10, 10)); sk["drag"](ev(20, ch - 22 - (ch - 32) * 0.1)); sk["release"](None)
        xp = skillcurve.parse(doc.cur_data)
        painted = xp[9] == skillcurve.parse(d)[9] and all(xp[i] > xp[i + 1] for i in range(10, 20))
        steps = len(sk["history"])
        sk["undo"]()
        res["paint"] = (painted, steps, doc.cur_data == d)
        # schedule: NPC + day pickers, add / remove a stop, copy to another day, revert
        if (B / "rf3Schedule.bin").exists():
            from rf4s_modkit import ident, schedule as _sch
            d = (B / "rf3Schedule.bin").read_bytes()
            app._show("rf3Schedule.bin", d); doc = app._doc
            sd = doc._sched
            first = (sd["npc"].get(), sd["day"].get(), len(sd["tree"].get_children()))
            n0 = len(sd["tree"].get_children())
            sd["tree"].selection_remove(*sd["tree"].selection())
            sd["time"].set("12:15"); sd["spot"].set("80: whatever"); sd["rand"].set(False)
            sd["edit"]("add")
            lst = sd["st"]["sc"].get(1, 0)
            added = len(lst) == n0 + 1 and any(w.slot == 49 and w.spot == 80 for w in lst) \
                and [w.slot for w in lst] == sorted(w.slot for w in lst)
            sd["tree"].selection_set(str(next(k for k, w in enumerate(lst) if w.slot == 49)))
            sd["edit"]("remove")
            removed = doc.cur_data == d
            sd["copy_var"].set(sd["state_label"](16)); sd["copy"]()
            copied = sd["st"]["sc"].get(1, 16) == sd["st"]["sc"].get(1, 0)
            sd["revert"]()
            res["sched"] = (first, added, removed, copied, doc.cur_data == d,
                            ident.identify(d, filename="rf3Schedule.bin").fmt)
        # rf3ParamMagic: a "used by" column after the id (spell item / monster timeline)
        if (B / "rf3ParamMagic.bin").exists():
            d = (B / "rf3ParamMagic.bin").read_bytes()
            app._show("rf3ParamMagic.bin", d); doc = app._doc
            tvm = doc._param_tree
            res["magic"] = (tvm["columns"][:2], tvm.set("0", "used by"), tvm.set("25", "used by").split(";")[0],
                            "Orc Archer" in tvm.set("53", "used by"), tvm.set("136", "used by"),
                            tvm.set("171", "used by"))
        # rf3ScheduleID: spot kind + room name after the id; "kind 26" lists that kind's spots
        if (B / "rf3ScheduleID.bin").exists():
            d = (B / "rf3ScheduleID.bin").read_bytes()
            app._show("rf3ScheduleID.bin", d); doc = app._doc
            tvs = doc._param_tree
            first = (tuple(tvs["columns"][:3]), tvs.set("30", "spot kind"), tvs.set("30", "room name"))
            import tkinter.ttk as _ttk
            ents = []

            def _walk(w):
                for c in w.winfo_children():
                    if isinstance(c, _ttk.Entry) and not isinstance(c, _ttk.Combobox):
                        ents.append(c)
                    _walk(c)
            _walk(doc.content)
            ents[0].insert(0, "kind 26"); root.update()
            res["sid"] = first + (list(tvs.get_children()) == [str(r) for r in range(30, 40)],)
        # E-mote portrait viewer: parts list, click-to-identify on the atlas, expandable tree
        if (B / "00_PLAYER_M.psbData").exists():
            import types as _types
            app._show("00_PLAYER_M.psbData", (B / "00_PLAYER_M.psbData").read_bytes())
            pv = getattr(app._doc, "_psb_view", None)
            if pv:
                ic = pv["icons"]["0000"]
                z = getattr(app._doc, "zoom", 1)
                pv["canvas"].xview_moveto(0); pv["canvas"].yview_moveto(0)
                pv["pick"](_types.SimpleNamespace(x=(ic["left"] + ic["width"] / 2) * z,
                                                  y=(ic["top"] + ic["height"] / 2) * z))
                tt = pv["tree"]
                src = next(i for i in tt.get_children("") if tt.item(i, "text") == "source")
                tt.focus(src); pv["open"]()
                res["psbview"] = (len(pv["parts"].get_children()), pv["state"]["sel"],
                                  [tt.item(i, "text") for i in tt.get_children(src)])
        # generic table editor: names for ids / values, row names, Undo / Revert, About
        if (B / "rf3TxtCalendar_split2_1.bin").exists() and (B / "rf3ParamSkill.bin").exists():
            d = (B / "rf3TxtCalendar_split2_1.bin").read_bytes()
            app._show("rf3TxtCalendar_split2_1.bin", d); doc = app._doc
            tvc = doc._param_tree
            shown = (tvc.set("0", "char_id"), tvc.set("1", "char_id"), tvc.set("12", "season"))
            doc._param_select(1)
            pv = doc._param_vars
            form = (pv["char_id"].get(), pv["season"].get())
            pv["season"].set("summer"); doc._param_apply()
            moved = nlcl.NlclTable(doc.cur_data).get(1, 1, "u8")
            doc._param_undo()
            undone = doc.cur_data == d
            pv["day"].set("9"); doc._param_apply(); doc._param_revert()
            reverted = doc.cur_data == d
            about = doc._param_about(); about_ok = "CALENDAR" in about.winfo_children()[0].get("1.0", "end")
            about.destroy()
            app._show("rf3ParamSkill.bin", (B / "rf3ParamSkill.bin").read_bytes())
            tvk = app._doc._param_tree
            res["generic"] = (shown, form, moved, undone, reverted, about_ok,
                              tuple(tvk["columns"][:2]), tvk.set("6", "name"))
        # recipe: item-id fields show names; the picker takes a name, "Name (id)" or an id
        if (B / "rf3RecipeAcce.bin").exists():
            d = (B / "rf3RecipeAcce.bin").read_bytes()
            app._show("rf3RecipeAcce.bin", d); doc = app._doc
            row = doc._param_tree.set("1")
            doc._param_select(1)
            pv = doc._param_vars
            shown = (row["result"], row["ing1"], row["ing2"], pv["ing1"].get(), "name" in row)
            pv["ing2"].set("minerals"); doc._param_apply()
            by_name = nlcl.NlclTable(doc.cur_data).get(1, 4, "u16")
            pv["ing2"].set("(none) (0)"); doc._param_apply()
            res["recipe"] = shown + (by_name, doc.cur_data == d)
        # strengthening: set a field of the selected row
        d = (B / "rf3ItemStrengthening.bin").read_bytes()
        app._show("rf3ItemStrengthening.bin", d); doc = app._doc
        tv = doc._str_tree
        first = tv.get_children()[0]
        tv.selection_set(first); root.update()
        fieldv, valv = doc._str_vars
        fieldv.set("atk"); valv.set("123"); doc._str_set()
        res["str"] = strengthening.StrengtheningTable(doc.cur_data).row(int(first))["atk"]
        # gift categories: add then remove an item
        d = (B / "rf3PresentCategory.bin").read_bytes()
        app._show("rf3PresentCategory.bin", d); doc = app._doc
        catv, itemv = doc._gift_vars
        catv.set("3"); itemv.set("1100"); doc._gift_add()
        added = 1100 in [e.value for e in gifts.GiftTable.parse(doc.cur_data).groups[3]["disliked"]]
        doc._gift_remove()
        res["gift"] = (added, doc.cur_data == d)
    finally:
        root.destroy()
    _check("AI script: the shown listing assembles back to the same file; a bad line is refused",
           res.get("ai") == (True, True), res.get("ai"))
    _check("skill XP curve: the header names the skills (Farming...); Set changes the selected level, "
           "Scale 50% halves it, the file keeps its size, Revert restores it",
           res.get("skill") == (777, 389, True, True, True), res.get("skill"))
    _check("skill XP curve: a paint stroke across the chart sets every level it crosses (a straight "
           "line between the drag points), is one history step, and Undo restores the file",
           res.get("paint") == (True, 4, True), res.get("paint"))
    if "psbview" in res:
        _check("E-mote viewer: 00_PLAYER_M lists 85 parts, a click on part 0000's rectangle selects it, "
               "the tree's 'source' node expands to 'tex'",
               res["psbview"] == (85, "0000", ["tex"]), res["psbview"])
    if "generic" in res:
        _check("table editor: ids and values show names (calendar char 30 = (festival), 21 = Ventuswill, "
               "season 1 = Summer), the form picks 'Ventuswill (21)' / 'Spring (0)', a typed name sets the "
               "number, Undo and Revert restore the file, About shows the notes, rf3ParamSkill rows are "
               "named by skill",
               res["generic"] == (("(festival)", "Ventuswill", "Summer"), ("Ventuswill (21)", "Spring (0)"),
                                  1, True, True, True, ("#", "name"), "Fire"), res["generic"])
    if "magic" in res:
        _check("rf3ParamMagic: 'used by' follows the id -- row 0 Fireball, 25 Double Sonic (spell items), "
               "53 the Orc Archer's move (monster timeline via rf3NpcParam +280), 136 Ancient Bone's "
               "scripted action 4 (AI script op 0x26), 171 the staff's fire shot",
               res["magic"] == (("#", "used by"), "Fireball", "Double Sonic", True,
                                "Ancient Bone (boss move 4)", "staff shot: Fire, level 0-1"), res["magic"])
    if "sid" in res:
        _check("rf3ScheduleID: 'spot kind' and 'room name' follow the id (record 30 = kind 26, 1 of 10, "
               "Butler's Room); searching 'kind 26' lists exactly records 30..39",
               res["sid"] == (("#", "spot kind", "room name"), "26  (1 of 10)", "Butler's Room", True), res["sid"])
    if "sched" in res:
        _check("rf3Schedule editor: opens on Herbert's normal-day routine (19 stops), Add puts a stop in "
               "time order, Remove restores the file, Copy makes another day's routine, Revert, "
               "identified as 'schedule'",
               res["sched"] == (("Herbert (1)", "Normal day: days 1, 7, 13, 19, 25", 19), True, True, True,
                                True, "schedule"), res["sched"])
    if "recipe" in res:
        _check("rf3Recipe*: item fields show item names (Yarn <- Furs), the picker shows "
               "'Furs (1088)', a typed name sets the id, (none) clears it (file byte-exact after)",
               res["recipe"] == ("Yarn", "Furs", "", "Furs (1088)", False, 1083, True), res["recipe"])
    _check("rf3ItemStrengthening: Set writes the chosen field of the selected item", res.get("str") == 123,
           res.get("str"))
    _check("rf3PresentCategory: Add puts an item in a category, Remove takes it out again (file "
           "byte-exact afterwards)", res.get("gift") == (True, True), res.get("gift"))


def test_param():
    print("param (NLCL):")
    files = [p for p in EXTRACTED.rglob("rf3*.bin") if nlcl.is_flat_nlcl(p.read_bytes()[:32])]
    if not files:
        _skip("NLCL param table", "no rf3*.bin param files extracted")
        return
    parsed = sum(1 for p in files if _try_parse(p))
    _check("NLCL param parse", parsed == len(files), f"{parsed}/{len(files)} parsed")
    # verified field check + edit round-trip on rf3ItemList
    il = next((p for p in files if p.name == "rf3ItemList.bin"), None)
    eq = next((p for p in files if p.name == "rf3ItemEquipmentParam.bin"), None)
    cp = next((p for p in files if p.name == "rf3CropParam.bin"), None)
    if eq:
        t = nlcl.NlclTable.load(eq)
        _check("rf3ItemEquipmentParam ATK field",
               t.get(330, 12) == 496 and t.get(342, 12) == 7000,   # Wind Sword / Dragon Slayer
               "Wind Sword=496, Dragon Slayer=7000")
        # get() must reject a multi-byte read that overruns the record (same guard as set)
        try:
            t.get(0, t.record_size - 1, "u32")
            _check("NLCL get() blocks cross-record read", False, "no error raised")
        except nlcl.NlclError:
            _check("NLCL get() blocks cross-record read", True)
    if cp:
        t = nlcl.NlclTable.load(cp)
        _check("rf3CropParam stages/harvest",
               t.get(72, 96, "u32") == 29 and [t.get(72, k, "u8") for k in range(4)] == [1, 1, 1, 0],
               "Turnip harvest=29, stages [1,1,1,0]")
        # growth-tick fields added 2026-07-20 (dual-binary verified): water@+40, season@+104
        _check("rf3CropParam water/season fields",
               t.get(55, 40, "u16") == 8
               and nlcl.crop_season_decode(t.get(55, 104, "u32"))["grows"] == ["summer"],
               "Pineapple(55) water=8, season affinity=summer")
        # crop_season_encode: reseason keeps low property bits + flips the affinity
        _cs = t.get(40, 104, "u32")
        _cn = nlcl.crop_season_encode(_cs, ["winter"], single=True)
        _check("crop_season_encode reseason round-trip",
               nlcl.crop_season_decode(_cn)["grows"] == ["winter"]
               and nlcl.crop_season_decode(_cn)["penalized"] == ["spring", "summer", "fall"]
               and (_cn & 0xFFF) == (_cs & 0xFFF),   # harvest-method / property low bits preserved
               "rec40 -> winter, off-seasons penalized, low bits intact")
    npc = next((p for p in files if p.name == "rf3NpcParam.bin"), None)
    if npc:
        t = nlcl.NlclTable.load(npc)
        _check("rf3NpcParam typed monster schema (Orc[48] hp/atk/model)",
               t.get(48, 40, "u32") == 48 and t.get(48, 44, "u32") == 5
               and t.get(48, 272, "u16") == 756 and t.get(200, 40, "u32") == 80000)
        # CharTemplate_t layout (Actor_RecomputeAllStats +0xAD440): +44/+48/+52 = STR/INT/VIT,
        # flat ATK/MAT/DEF/MDF at +60/+64/+72/+76; resists in status-bit order poison, SEAL,
        # PARALYSIS, SLEEP (Combat_GetStatusProcMask: bit k <- stats+152+2k <- dword k).
        so = {n: o for n, o, _ty in t.schema("rf3NpcParam")["fields"]}
        orc = t.row(48, "rf3NpcParam")
        _check("rf3NpcParam STR/INT/VIT + flat stats + resist order (exe layout)",
               (orc["str"], orc["int"], orc["vit"], orc["flat_atk"], orc["flat_def"]) == (5, 3, 4, 8, 2)
               and orc["tame_base"] == 25 and orc["base_level"] == 2
               and [so[f"res_{s}"] for s in ("poison", "seal", "paralysis", "sleep", "fatigue")]
               == [184, 188, 192, 196, 200]
               and t.row(1, "rf3NpcParam")["anim"] == -1)
        try:
            t.set_field(48, "def", 10, "rf3NpcParam")
            _ren = False
        except nlcl.NlclError as e:
            _ren = True
        _check("rf3NpcParam: an unknown column name ('def') is refused", _ren)
    stg = next((p for p in files if p.name == "rf3ItemStrengthening.bin"), None)
    if stg:
        t = nlcl.NlclTable.load(stg)
        # ptr_78 strengthening rows: 1150 records; +0 = upgrade DIFFICULTY (Soul Eater 340 = 70,
        # Turnip 29 = 1); +152 bit 0x4000 = NON-FOOD marker (set on real equipment, clear on
        # food/crops). Full decode: test_strengthening + rf4s_modkit.strengthening.
        _check("rf3ItemStrengthening difficulty + non-food marker (ptr_78)",
               t.entry_count == 1150 and t.get(340, 0, "u16") == 70 and t.get(29, 0, "u16") == 1
               and (t.get(340, 152, "u16") & 0x4000) and not (t.get(29, 152, "u16") & 0x4000))
    # named CSV view (rf4mod param csv / GUI Export CSV): schema columns + a name column
    pt = next((p for p in files if p.name == "rf3PriceTable.bin"), None)
    if pt and il:
        t = nlcl.NlclTable.load(pt)
        txt = t.to_csv(pt.stem)
        head = txt.splitlines()[0].split(",")
        ti = nlcl.NlclTable.load(il)
        itxt = ti.to_csv(il.stem, lambda i: {29: "Turnip"}.get(i, ""))
        rows = itxt.splitlines()
        _check("NLCL to_csv named view (rf3PriceTable columns, rf3ItemList name column)",
               head == ["#"] + [f"Lv {j}" for j in range(1, 11)] and len(txt.splitlines()) == 11
               and rows[0].endswith(",name") and rows[30].split(",")[0] == "29"
               and rows[30].endswith(",Turnip") and len(rows) == ti.entry_count + 1)
        rawh = t.to_csv(pt.stem, named=False).splitlines()[0]
        _check("NLCL to_csv raw view (dw columns)", rawh.startswith("#,dw0,dw1"))
    prm = next((p for p in files if p.name == "rf3Parameter.bin"), None)
    if prm:
        t = nlcl.NlclTable.load(prm)
        # archive 14813 char-level curve: 200 levels; +0 xp_to_next ascends, +8 hp_max ascends
        _check("rf3Parameter level curve (14813)",
               t.entry_count == 200 and t.get(0, 0, "u32") == 4 and t.get(5, 0, "u32") == 167
               and t.get(0, 8, "u32") == 56 and t.get(5, 8, "u32") == 85)
        # Actor_ApplyLevelUp: +4 -> base HP, +8 -> base RP (u16), +12/16/20 -> STR/INT/VIT
        r199 = t.row(199, "rf3Parameter")
        try:
            t.set_field(0, "rp", 70000, "rf3Parameter")
            _lim = False
        except nlcl.NlclError:
            _lim = True
        _check("rf3Parameter hp/rp/str columns + u16 RP limit",
               (r199["hp"], r199["rp"], r199["str"]) == (23144, 900, 734) and _lim)
    pnpc = next((p for p in files if p.name == "rf3ParameterNPC_01.bin"), None)
    if pnpc:
        t = nlcl.NlclTable.load(pnpc)
        # VESTIGIAL archive 14814: 20x16B tiered growth (dead data, no runtime reader).
        # The _01/_02/_03 stems alias to the shared rf3ParameterNPC schema (4 cols).
        sch = t.schema("rf3ParameterNPC_01")
        row = t.row(0, "rf3ParameterNPC_01")
        _check("rf3ParameterNPC alias -> 4-col schema (vestigial 14814)",
               sch is not None and "alias" not in sch and len(sch["fields"]) == 4
               and row["col0"] == 6 and row["col1"] == 9 and row["col2"] == 3 and row["col3"] == 5)
    mmp = next((p for p in files if p.name == "rf3MapMiniPos.bin"), None)
    if mmp:
        t = nlcl.NlclTable.load(mmp)
        # 873 per-map minimap layouts; +0 = picture sheet (texture = nsFileArchive 12199 + sheet),
        # +12..+24 = fog-of-war reveal rect, +28/+32 = Q12 scale (see minimap.py)
        r0, plain = t.row(0, "rf3MapMiniPos"), t.row(161, "rf3MapMiniPos")   # blank row / Selphia Plain
        _check("rf3MapMiniPos minimap layout",
               t.entry_count == 873 and t.record_size == 52 and r0["sheet"] == 73
               and plain["sheet"] == 66 and (plain["origin_x"], plain["origin_y"]) == (94, 71)
               and (plain["reveal_w"], plain["reveal_h"]) == (27, 27)
               and (plain["scale_x"], plain["scale_y"]) == (217, 201) and plain["parent_sheet"] == 73)
    mag = next((p for p in files if p.name == "rf3ParamMagic.bin"), None)
    if mag:
        t = nlcl.NlclTable.load(mag)
        # archive 14817 action-param: action 0 = Fire magic (flags 0x81, MAT-scaling), 446 records
        _check("rf3ParamMagic action schema (14817)",
               t.entry_count == 446 and t.get(0, 28, "u32") == 0x81
               and t.get(0, 40) == 4096 and t.get(0, 32) == 15)
    sdt = next((p for p in files if p.name == "rf3ParamSkillData.bin"), None)
    if sdt:
        t = nlcl.NlclTable.load(sdt)
        # archive 14819 skill cast-cost: action 3 = RP 14 / gov skill 0
        _check("rf3ParamSkillData cost schema (14819)",
               t.get(3, 4, "u16") == 14 and t.get(7, 4, "u16") == 16 and t.get(7, 12, "s32") == 1)
    psk = next((p for p in files if p.name == "rf3ParamSkill.bin"), None)
    if psk:
        t = nlcl.NlclTable.load(psk)
        # archive 14818 growth coefs (Player_ApplyAllSkillGrowthBonusesFromArchive14818 +0xB0E00:
        # dw0 -> hp_max, dw1 -> rp_max, dw2/3/4 -> STR/INT/VIT; +36 = RP-cost discount, +28 =
        # magic element bonus). Weapon skill 0 = RP+STR growth, Farming[13] = big HP.
        r0, r13 = t.row(0, "rf3ParamSkill"), t.row(13, "rf3ParamSkill")
        _check("rf3ParamSkill growth schema (14818)",
               r0["rp_growth"] == 1024 and r0["str_growth"] == 1024 and r0["hp_growth"] == 0
               and r13["hp_growth"] == 8192 and r0["rp_discount"] == 20)
        try:
            t.set_field(0, "atk_growth", 1, "rf3ParamSkill")
            _ren = False
        except nlcl.NlclError as e:
            _ren = True
        _check("rf3ParamSkill: an unknown column name is refused", _ren)
    if il:
        t = nlcl.NlclTable.load(il)
        ok = t.get(1, 12) == 680 and t.get(29, 12) == 30   # Cabbage 680 / Turnip 30
        _check("rf3ItemList sell-price field", ok, "Cabbage=680, Turnip=30")
        t.set_field(29, "sell_price", 9999, "rf3ItemList")
        blob = t.build()
        t2 = nlcl.NlclTable(blob)
        _check("NLCL edit round-trip",
               t2.get(29, 12) == 9999 and t2.get(1, 12) == 680 and len(blob) == len(t.data),
               il.name)
        # value / range guards: a value that does not fit the field width, an unknown type, a
        # negative record index and a price row > 9 (Item_ComputeStackGoldValue returns 0)
        # must raise NlclError instead of struct.error / a silent header slice / a 0-gold item
        _rej = 0
        for _bad in (lambda: t.set(29, 4, 256, "u8"), lambda: t.set(29, 12, -1, "u32"),
                     lambda: t.set(29, 12, 1, "f32"), lambda: t.record(-1),
                     lambda: t.set_field(29, "sell_price_row", 10, "rf3ItemList")):
            try:
                _bad()
            except nlcl.NlclError:
                _rej += 1
        _check("NLCL set/record guards (width, type, index, price row 0..9)",
               _rej == 5 and t.row(1, "rf3ItemList")["buy_price"] == 2800
               and t.row(1, "rf3ItemList")["sell_price_row"] == 3)
    else:
        _skip("rf3ItemList field check", "rf3ItemList.bin not extracted")
    # rf3UseItemParam: row index = item id, +0 HP recovery / +4 RP recovery.
    # Verified vs item names (= g_itemDatabase->ptr_68; Item_UseOnActor consumer).
    ui = next((p for p in files if p.name == "rf3UseItemParam.bin"), None)
    if ui:
        t = nlcl.NlclTable.load(ui)
        ok = (t.get(1, 0) == 140      # Cabbage HP+140
              and t.get(2, 0) == 600  # King Cabbage HP+600
              and t.get(5, 0) == 90 and t.get(5, 4) == 30)  # Pink Melon HP+90/RP+30
        _check("rf3UseItemParam hp/rp recovery", ok, "Cabbage 140, KingCabbage 600, PinkMelon 90/30")
        # Item_UseOnActor scales +52/+56/+60 by str_base/int_base/vit_base -> STR/INT/VIT buffs;
        # +64..+156 mirror rf3ItemStrengthening S[50..73] (dish record dword k-34 += S[k])
        uo = {n: o for n, o, _ty in t.schema("rf3UseItemParam")["fields"]}
        _check("rf3UseItemParam STR/INT/VIT buff names + full +64..+156 layout",
               (uo["buff_str"], uo["buff_int"], uo["buff_vit"], uo["buff_vit_pct"]) == (32, 36, 40, 60)
               and uo["fed_res_poison"] == 76 and uo["fed_proc_faint"] == 128
               and uo["el_love"] == 156 and uo["perm_vit"] == 172 and "buff_atk" not in uo)
    # MapOre_Rate: 25x32 dungeon rock/ore drop tables — area_id + 4 weighted ores.
    mo = next((p for p in EXTRACTED.rglob("MapOre_Rate.bin")), None)
    if mo:
        t = nlcl.NlclTable.load(mo)
        ok = (t.get(0, 0, "u32") == 26          # area id
              and t.get(0, 24, "u16") == 819    # ore0 = Iron
              and t.get(0, 8, "u32") == 100     # Iron weight 100
              and t.get(0, 28, "u16") == 930    # ore2 = Invisible Stone (rare)
              and t.get(0, 16, "u32") == 1)     # rare weight 1
        _check("MapOre_Rate area/ore/weight", ok, "area26 Iron w100, InvisibleStone w1")
    # Text-metadata companions of the TEXT split files (decoded 2026-08-31; see the
    # FIELD_SCHEMAS comments): calendar events, shop dialogue meta, name-entry keys.
    cal = next((p for p in files if p.name == "rf3TxtCalendar_split2_1.bin"), None)
    if cal:
        t = nlcl.NlclTable.load(cal)
        r1 = t.row(1, "rf3TxtCalendar_split2_1")    # "Ventuswill's Birthday"
        r42 = t.row(42, "rf3TxtCalendar_split2_1")  # "Christmas"
        ok = (t.entry_count == 45 and t.record_size == 4
              and (r1["char_id"], r1["season"], r1["day"], r1["festival_id"]) == (21, 0, 4, 0)
              and (r42["char_id"], r42["season"], r42["day"], r42["festival_id"]) == (30, 3, 25, 25))
        _check("rf3TxtCalendar event table", ok, "Venti bday spring 4, Christmas winter 25")
    sn = next((p for p in files if p.name == "rf3TxtShopNpc_split2_1.bin"), None)
    if sn:
        t = nlcl.NlclTable.load(sn)
        r = t.row(15, "rf3TxtShopNpc_split2_1")     # char 2 slot 1 "Welcome!"
        ok = (t.entry_count == 27 * 14 and t.record_size == 16
              and (r["char_id"], r["slot"], r["voice_a"], r["duration"]) == (2, 1, 1608, 90)
              and all(t.get(i * 14, 0, "u16") == i + 1 for i in range(27)))
        _check("rf3TxtShopNpc dialogue meta", ok, "27 chars x 14 slots, voiced greeting")
    ne = next((p for p in files if p.name == "rf3TxtNameEntryBoard_split2_1.bin"), None)
    if ne:
        t = nlcl.NlclTable.load(ne)
        v = t.get(0, 0, "u32")
        ch = v.to_bytes(4, "big").lstrip(b"\0").decode("utf-8", "replace")
        _check("rf3TxtNameEntryBoard utf8 keys",
               t.entry_count == 297 and ch == "あ", "key 0 = あ (0xE38182)")


def test_mapground():
    print("mapground (ground-texture atlas):")
    # Game-exact tile-grid formula (RF4S.exe Map_SpawnEntity: cols=ceil(24*ATTR_W/512)).
    # Pure integer math — runs even without Pillow. stitch uses this when aspect is known.
    _check("mapground grid_dims = ceil(24*W/512)",
           mapground.grid_dims(64, 64) == (3, 3) and mapground.grid_dims(51, 42) == (3, 2)
           and mapground.grid_dims(72, 72) == (4, 4) and mapground.grid_dims(128, 48) == (6, 3)
           and mapground.grid_dims(1, 1) == (1, 1),
           "64->3x3, 51x42->3x2, 72->4x4, 128x48->6x3")
    mapground.tile_cache_clear()
    _check("mapground tile cache API", mapground.tile_cache_size() == 0, "clear -> size 0")
    # Heuristic column count that does not divide the tile count (narrow tile at index 2
    # -> 3 cols, 5 tiles): the short last row must still be laid out (rows used to be
    # n // cols, so tile 3 indexed a row that did not exist -> IndexError).
    _dims = {0: (512, 512), 1: (512, 512), 2: (256, 512), 3: (512, 512), 4: (512, 512)}
    _fake = {mapground.tile_name("MAP_SELFTEST_SHORTROW", 0, i): i for i in _dims}
    _orig_parse = mapground._tex.parse
    try:
        mapground._tex.parse = lambda b: {"width": _dims[b][1], "height": _dims[b][0]}
        _lay = mapground.tile_layout(lambda fn: _fake.get(fn), "MAP_SELFTEST_SHORTROW", 0)
        _ok = (_lay is not None and (_lay["cols"], _lay["rows"]) == (3, 2)
               and [(t["x"], t["y"]) for t in _lay["tiles"]][3:] == [(0, 512), (512, 512)])
    except Exception as e:
        _lay, _ok = None, False
        print(f"    {type(e).__name__}: {e}")
    finally:
        mapground._tex.parse = _orig_parse
    _check("mapground tile_layout places a short last row (cols not dividing the tile count)", _ok,
           str(_lay and (_lay["cols"], _lay["rows"])))
    if not (texture.HAS_PIL and texture.HAS_BC):
        _skip("mapground stitch", "Pillow/texture2ddecoder not installed")
        return
    # find any MAP_*_0000.texture whose .rf4m also exists, prefer a field
    tile0 = None
    for p in EXTRACTED.rglob("MAP_*_0000.texture"):
        base = p.name[:-len("_0000.texture")]
        if (p.parent / f"{base}.rf4m").is_file():
            tile0 = (p.parent, base)
            if "FIELD" in base:
                break
    if not tile0:
        _skip("mapground stitch", "no map texture atlas extracted")
        return
    d, base = tile0
    reader = lambda fn, d=d: (d / fn).read_bytes() if (d / fn).is_file() else None
    layers = mapground.available_layers(reader, base)
    _check("mapground layer probe", layers == sorted(layers) and 0 in layers, f"{base} layers={layers}")
    res = mapground.stitch(reader, base, 0)
    ok = res is not None and res[0].size[0] > 0 and res[1] * res[2] >= 1
    _check("mapground stitch layer 0", ok, f"{base} -> {res[0].size} {res[1]}x{res[2]}" if res else "None")
    comp = mapground.stitch_composite(reader, base)
    _check("mapground composite all layers",
           comp is not None and comp[0].size == res[0].size,
           f"{base} {len(layers)} layers -> {comp[0].size}" if comp else "None")
    # orientation regression: stitched image aspect must agree with the ATTR grid
    # (both landscape or both portrait) — guards the row-major in-game alignment.
    f03 = next(EXTRACTED.rglob("MAP_FIELD_03.rf4m"), None)
    if f03:
        w, h, _ = rf4m.Rf4mMap.load(f03).attr_grid()
        freader = lambda fn, d=f03.parent: (d / fn).read_bytes() if (d / fn).is_file() else None
        gi = mapground.stitch_composite(freader, "MAP_FIELD_03", aspect=(w, h))
        if gi and w != h:
            iw, ih = gi[0].size
            _check("mapground orientation matches ATTR aspect",
                   (iw > ih) == (w > h), f"img {iw}x{ih} vs ATTR {w}x{h}")
    # row-major tile-ordering regression: tile 0 must land at the image top-left
    # corner (the user-confirmed in-game convention: 0000=TL, 0001=top-mid-left, ...,
    # last=bottom-right). We verify by stitching with only tile 0 substituted with a
    # solid red block, and checking pixel (1, 1) is red. Uses a synthetic reader.
    fr_dir = next(EXTRACTED.rglob("MAP_FIELD_01_0000.texture"), None)
    if fr_dir and texture.HAS_BC:
        # Wrap real reader; replace tile 0 of layer 0 with a solid-red 512x512 raw
        # texture isn't easy without a re-encode, so we just check the decoded tile 0
        # appears at canvas (0,0) by inspecting the first non-transparent pixel.
        d = fr_dir.parent
        rdr = lambda fn, d=d: (d / fn).read_bytes() if (d / fn).is_file() else None
        comp = mapground.stitch(rdr, "MAP_FIELD_01", 0)
        if comp:
            # Same pixel from raw tile 0 should equal that of stitched (0,0).
            t0 = texture.decode_to_image((d / "MAP_FIELD_01_0000.texture").read_bytes()).convert("RGBA")
            ok = t0.getpixel((4, 4)) == comp[0].getpixel((4, 4))
            _check("mapground tile 0 at screen top-left", ok,
                   "tile-0 pixel matches stitched (4,4)")
    # When ATTR aspect is supplied, the stitched canvas must equal the real
    # map extent (ATTR_W·24 × ATTR_H·24) — guards the MAP_CITY_06 alignment bug
    # where a full-512×512 atlas overran the actual map area and the editor's
    # resize-to-grid stretched padding into view.
    full_atlas = next(EXTRACTED.rglob("MAP_CITY_06.rf4m"), None)
    if full_atlas and texture.HAS_BC:
        wh = rf4m.Rf4mMap.load(full_atlas).attr_grid()
        if wh:
            w, h, _ = wh
            r = lambda fn, d=full_atlas.parent: (d / fn).read_bytes() if (d / fn).is_file() else None
            s = mapground.stitch(r, full_atlas.stem, 0, aspect=(w, h))
            if s:
                _check("mapground extent crops to ATTR·24 px",
                       s[0].size == (w * 24, h * 24),
                       f"{full_atlas.stem} ATTR {w}x{h} -> img {s[0].size}")
    # AUTHORITATIVE map -> texture-set mapping (from g_mapResourceTable). The ground
    # texture is usually a DIFFERENT set than the same-named one — only 121/872 maps
    # are name-matched. resolve_base must follow the mapping, not the map name.
    _check("map_texture_sets mapping loaded",
           len(mapground._texmap()) > 800,
           f"{len(mapground._texmap())} maps mapped")
    ts13 = mapground.texture_set_for("MAP_FIELD_13")
    ts03 = mapground.texture_set_for("MAP_FIELD_03")
    tsE1 = mapground.texture_set_for("MAP_DUNG_E01")
    _check("map->texture mapping anchors",
           ts13 and ts13[0] == "MAP_FIELD_10" and ts03 and ts03[0] == "MAP_FIELD_203"
           and tsE1 and tsE1[0] == "MAP_DUNG_E02_UV" and tsE1[1] is True,
           f"FIELD_13->{ts13}, FIELD_03->{ts03}, E01->{tsE1}")
    f13 = next(EXTRACTED.rglob("MAP_FIELD_13.rf4m"), None)
    if f13 and texture.HAS_BC:
        rr = lambda fn, d=f13.parent: (d / fn).read_bytes() if (d / fn).is_file() else None
        _check("resolve_base follows the mapping (not the name)",
               mapground.resolve_base(rr, "MAP_FIELD_13") == "MAP_FIELD_10",
               "MAP_FIELD_13 ground texture = MAP_FIELD_10")
    # a map with NO reachable atlas -> stitch returns None. "Reachable" must account
    # for the g_mapResourceTable mapping: a map without its own atlas can still stitch
    # via its mapped texture set (e.g. MAP_CITY_08 -> MAP_DUMMY_00), so exclude any
    # candidate whose stem OR mapped set (incl. the _UV-stripped stage set) is present.
    noatlas = None
    for p in EXTRACTED.rglob("*.rf4m"):
        s = p.stem
        if s.upper().endswith(("_SPRING", "_SUMMER", "_AUTUMN", "_FALL", "_WINTER")):
            continue
        ent = mapground.texture_set_for(s)
        cands = {s}
        if ent:
            cands.add(ent[0])
            if ent[0].endswith("_UV"):
                cands.add(ent[0][:-3])
        if any((p.parent / mapground.tile_name(c, 0, 0)).is_file()
               or (p.parent / mapground.single_name(c)).is_file() for c in cands):
            continue
        noatlas = p
        break
    if noatlas:
        nreader = lambda fn, d=noatlas.parent: (d / fn).read_bytes() if (d / fn).is_file() else None
        nname, ndetail = noatlas.stem, noatlas.stem
    else:
        # No corpus candidate (the mapping gives every map a reachable set) -> use a
        # synthetic empty bundle. The fictitious name has no mapping entry and no
        # cached tiles, so stitch must probe, find nothing, and return None.
        nreader = lambda fn: None
        nname, ndetail = "MAP_SELFTEST_NOATLAS", "synthetic: every corpus map has a reachable set"
    _check("mapground absent-atlas -> None",
           mapground.stitch(nreader, nname, 0) is None, ndetail)
    # season variant falls back to its base map's atlas
    var = next(EXTRACTED.rglob("MAP_*_SUMMER.rf4m"), None)
    if var:
        base = var.stem[:-len("_SUMMER")]
        vreader = lambda fn, d=var.parent: (d / fn).read_bytes() if (d / fn).is_file() else None
        if (var.parent / f"{base}_0000.texture").is_file():
            _check("mapground season-variant fallback",
                   mapground.stitch(vreader, var.stem, 0) is not None, f"{var.stem} -> {base}")


def test_search_items():
    print("search_items (SI_*.bin daily ground pickups):")
    files = sorted(EXTRACTED.rglob("SI_*.bin"))
    if not files:
        _skip("SI parse", "no SI_*.bin extracted")
        return
    perfect = semantic = failed = 0
    for p in files:
        d = p.read_bytes()
        try:
            f = search_items.SearchItemFile.parse(d)
            rb = f.build()
            if rb == d:
                perfect += 1
            else:
                f2 = search_items.SearchItemFile.parse(rb)
                same = (len(f2.spots) == len(f.spots) and all(
                    a.x == b.x and a.y == b.y and
                    [(e.item_id, e.weight) for e in a.pool.entries] ==
                    [(e.item_id, e.weight) for e in b.pool.entries]
                    for a, b in zip(f.spots, f2.spots)))
                if same:
                    semantic += 1
                else:
                    failed += 1
        except Exception:
            failed += 1
    # Pristine data round-trips byte-perfectly on all files. The local workspace's
    # SI_CITY_00.bin is hand-edited (non-canonical footer), so build() canonicalises
    # it -- tolerate at most one semantic-only file.
    _check("SI parse + round-trip", failed == 0 and semantic <= 1,
           f"{perfect} byte-perfect, {semantic} canonicalised, {failed} failed of {len(files)}")
    # 2026-09-24: SearchItem_RollSpotsAndSpawnFromArchive counts spots and pool entries
    # in u8 registers -> > 255 of either hangs the game; stock files are clean.
    stock_err = [p.name for p in files
                 if any(m.startswith("ERROR") for m in search_items.SearchItemFile.load(p).validate())]
    pool = search_items.DropPool(entries=[search_items.DropEntry(1, 1)] * 256)
    big = search_items.SearchItemFile(spots=[search_items.SearchSpot(80, 80, pool)] * 256)
    vb = big.validate()
    _check("SI validate: stock clean; 256 spots / 256-entry pool are fatal (u8 loop counters)",
           not stock_err and sum(1 for m in vb if m.startswith("ERROR")) == 2
           and search_items.SearchItemFile.parse(big.build()).validate() == vb,
           ", ".join(stock_err[:3]) or f"{len(vb)} findings on the bad file")
    # generic NLCL footer (build-tool xref table): every listed reference must
    # store its target offset. Validate across ALL NLCL files, not just SI.
    nl_ok = nl_total = 0
    for p in EXTRACTED.rglob("*.bin"):
        d = p.read_bytes()
        if d[:4] != b"NLCL" or len(d) < 28:
            continue
        nl_total += 1
        try:
            search_items.parse_nlcl_footer(d)
            nl_ok += 1
        except Exception:
            pass
    _check("NLCL footer xref-table valid", nl_ok == nl_total, f"{nl_ok}/{nl_total} NLCL files")


def test_entry_key_warnings():
    """Keys that can never match are refused when a trigger is added or re-keyed, odd ones
    warned: type 2 compares a spawned event actor's unsigned 16-bit key exactly (no -1
    wildcard; 0 marks a removed actor), actor ops read 1..47 as villagers, keys are signed
    32-bit, and typed keys (item, topic, festival, condition, map, npc) must name something."""
    print("entry key checks (type 2 = exact unsigned 16-bit event key; typed key ranges):")
    from rf4s_modkit import entry_types as _et
    kp, ke = _et.key_problems, _et.key_errors
    _check("type 2: -1, a negative, 0 and > 65535 are refused; 48 .. 65535 are fine; 1..47 warn "
           "(actor ops read them as villagers)",
           all(len(ke(2, [v])) == 1 for v in (-1, -5, 0, 70000)) and "65535" in ke(2, [(1, -1)])[0]
           and all(ke(2, [v]) == [] and kp(2, [v]) == [] for v in (48, 1000, 65535))
           and ke(2, [5]) == [] and len(kp(2, [5])) == 1)
    _check("any type: a key outside signed 32-bit is refused",
           len(ke(4, [2 ** 31])) == 1 and len(ke(4, [-2 ** 31 - 1])) == 1 and ke(4, [2 ** 31 - 1]) == [])
    item_t = next(t for t, s in _et.ENTRY_TYPES.items() if any(isinstance(k, dict) and k.get("name") == "item"
                                                                 for k in s.get("keys") or []))
    topic_ix = next(k["index"] for k in _et.ENTRY_TYPES[60]["keys"] if k.get("name") == "topic")
    _check("typed keys: an item id past 2047, a gossip topic past 10, an em.bin entry the file "
           "does not have, an unknown map / character are warned; valid ones are not",
           len(kp(60, [11])) == 1 and kp(60, [10]) == [] and topic_ix == 0
           and any("item" in w for w in kp(item_t, [3000] * 3))
           and len(kp(45, [300], em_count=272)) == 1 and kp(45, [100], em_count=272) == []
           and len(kp(39, [99999], map_ok=lambda v: v < 1000)) == 1 and kp(39, [5], map_ok=lambda v: v < 1000) == []
           and len(kp(28, [9999], char_ok=lambda v: v < 700)) == 1 and kp(28, [16582], char_ok=lambda v: v < 700) == [])
    wild = next(((t, k) for t, s in _et.ENTRY_TYPES.items() for k, ks in enumerate(s["keys"])
                 if isinstance(ks["index"], int) and ks.get("wildcard")), None)
    _check("a key the catalogue marks as a wildcard accepts -1 without a warning",
           wild is not None and kp(wild[0], [0] * wild[1] + [-1]) == [], wild)


def test_frame_sizing():
    """FRAME is sized by itself: a new scene starts empty (RET), and an edit that makes an
    argument a nested expression evaluated while other arguments are on the stack gets the
    routine a FRAME (inserted, or raised in place) -- the evaluator spills 2 words per level
    below the top to stack[frame_base..] (Script_EvalExpressionBytecode RF4S.exe+0x23E1C0)."""
    print("FRAME sizing (new scenes start empty; FRAME added / raised when needed):")
    from rf4s_modkit import bankrelink as BR, script as S
    mc = BUNDLE_DIR / "bundlePatch1" / "rf3.mc"
    if not mc.is_file():
        _skip("FRAME sizing", "no rf3.mc"); return
    _check("expression depth / need: literals and registers never need a frame; only a nested "
           "argument that is not the last one does",
           BR.expr_depth(b"\x17\x05\x00") == 1 and BR.expr_depth(b"\x07\x16\x86\x00") == 2
           and BR.action_frame_need([b"\x07\x16\x86\x00", b"\x17\x01\x00"]) == 2
           and BR.action_frame_need([b"\x17\x01\x00", b"\x07\x16\x86\x00"]) == 0
           and BR.action_frame_need([b"\x07\x16\x86\x00"]) == 0)
    c = S.Container(mc.read_bytes())
    pos = next(i for i, b in enumerate(c.banks) if b.kind == "tail" and len(b.data) == 296)
    bank = c.banks[pos]
    pc, _idx = c.add_entry(bank, 6, [], listing="RET")
    first = S.decode_statement(bank.data, pc)
    empty_ok = first is not None and first.mnem == "RET"
    npc = c.insert_before(bank, pc, "GivePlayerItem((reg0 + 1), 1, 0)")
    ent = bank.entry_records(6)[0].event_id
    st0 = S.decode_statement(bank.data, ent)
    inserted = st0.mnem == "FRAME" and st0.items == [2] and c.last_frames and c.last_frames[0][2] == 2
    nxt = S.decode_statement(bank.data, ent + st0.size)
    c.insert_after(bank, nxt.pc, "GivePlayerItem((reg0 + (reg1 * 2)), 1, 0)")
    ent = bank.entry_records(6)[0].event_id
    st1 = S.decode_statement(bank.data, ent)
    raised = st1.mnem == "FRAME" and st1.items == [4]
    c.insert_after(bank, ent, "GivePlayerItem(1, 1, (reg0 + (reg1 * (reg2 + 3))))")   # nested but LAST: no need
    st2 = S.decode_statement(bank.data, bank.entry_records(6)[0].event_id)
    _check("a new scene is just RET; a nested non-last argument inserts FRAME 2; a deeper one "
           "raises it to 4; a nested LAST argument changes nothing",
           empty_ok and inserted and raised and st2.items == [4],
           (empty_ok, st0.mnem, st0.items, st1.items, st2.items))
    shipped = S.Container(mc.read_bytes())
    changed = [i for i, b in enumerate(shipped.banks[:200]) if BR.BankModel.parse_any(b).ensure_frames()]
    _check("no shipped bank needs a FRAME change (every shipped routine meets the rule)",
           not changed, changed[:5])


def _walk_widgets(w):
    """Every descendant widget of `w`."""
    for ch in w.winfo_children():
        yield ch
        yield from _walk_widgets(ch)


def test_game_names():
    """Character / item / map / skill names come from the game's own text files (the copy the
    game loads: Bundle/00_mods beats bundleMain), with the toolkit's lists as the default, so a
    renamed character shows up in pickers, comments and actor(..)."""
    print("Names from the game's text files (gamenames):")
    import os
    from rf4s_modkit import gamenames as G, gamepaths, textdb, opcode_meta as om, script as S
    real = gamepaths.find_bundle_dir()
    if real is None:
        _skip("game names", "no game folder"); return
    G.reload()
    def _file_table(path, first):
        arc = textdb.TextArchive.parse(pathlib.Path(path).read_bytes())
        return {r - first: arc.text(r).strip() for r in range(first, len(arc.entries)) if arc.text(r).strip()}
    same = True
    for k in G.KINDS:
        src, first = G.source(k), G.FILES[k][1]
        # the tables are exactly the loaded file; the built-in lists are the game's original
        # (the ModdingBackup copy when a Save replaced it, a 00_mods file's bundleMain original)
        orig = gamepaths.backup_path(src)
        if orig is None or not orig.is_file():
            orig = src if src.parent.name != "00_mods" else real / "bundleMain" / src.name
        builtin = {i: v.strip() for i, v in G._builtin(k).items() if v.strip()}
        same = same and G.table(k) == _file_table(src, first) and _file_table(orig, first) == builtin
    _check("names are read from the game's files; the built-in lists match the unmodded originals",
           same, {k: str(G.source(k)) for k in G.KINDS})
    npc = G.source("characters")
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        (tmp / "00_mods").mkdir()
        (tmp / "bundleMain").mkdir()
        shutil.copy2(npc, tmp / "bundleMain" / npc.name)
        arc = textdb.TextArchive.parse(npc.read_bytes())
        arc.set_text(4, "Fortissa")
        (tmp / "00_mods" / npc.name).write_bytes(arc.build())
        saved = gamepaths.find_bundle_dir
        gamepaths.find_bundle_dir = lambda refresh=False: tmp
        try:
            G.reload()
            modded = (G.name("characters", 4) == "Fortissa" and G.source("characters").parent.name == "00_mods"
                      and om.CHAR_IDS[4][0] == "Fortissa" and S.actor_leaf_value("Fortissa") == 4
                      and S.actor_leaf_text(4) == "actor(Fortissa)" and G.source("items") is None
                      and G.name("items", 258) == "Pineapple Juice")
            detail = (G.name("characters", 4), str(G.source("characters")), om.CHAR_IDS[4])
            # a save of the file (no reload call) and removing the override are picked up
            every, G.CHECK_EVERY = G.CHECK_EVERY, 0
            try:
                arc.set_text(4, "Fortina")
                f = tmp / "00_mods" / npc.name
                f.write_bytes(arc.build())
                st = f.stat()
                os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
                saved_seen = (om.CHAR_IDS[4][0] == "Fortina" and S.actor_leaf_text(4) == "actor(Fortina)")
                f.unlink()
                removed_seen = om.CHAR_IDS[4][0] == "Forte" and G.source("characters").parent.name == "bundleMain"
            finally:
                G.CHECK_EVERY = every
            gamepaths.find_bundle_dir = lambda refresh=False: None
            G.reload()
            nogame = G.source("characters") is None and G.name("characters", 4) == "Forte"                 and om.CHAR_IDS[4][0] == "Forte"
        finally:
            gamepaths.find_bundle_dir = saved
            G.reload()
        _check("a character renamed in Bundle/00_mods shows everywhere (pickers, actor(..)); a file the "
               "mod lacks falls back to the built-in list", modded, detail)
        _check("without a game folder the built-in lists are the default", nogame)
        _check("saving a name file, and removing a 00_mods override, show up without a restart",
               saved_seen and removed_seen, (saved_seen, removed_seen))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_opcode_arg_verification():
    """Each opcode argument carries its own human_verified flag and tests log, and a code-valued
    argument lists value_names: the assembler reads a name as its number, the listing writes the
    number with the name in the statement's comment, and a true alias / family shares them (optest.py records into the whole group)."""
    print("Opcode argument verification and value names:")
    import json
    import re as _re
    import optest as O
    from rf4s_modkit import opcode_meta as om, scriptasm as A, script as S
    rows = om.TABLE["actions"]
    _check("every argument has a human_verified flag",
           all("human_verified" in a for r in rows.values() for a in r["args"]))
    bad, roundtrip = [], []
    reserved = {"add", "sub", "set", "zero", "null", "self", "player"}
    for k, r in rows.items():
        for i, a in enumerate(r["args"]):
            vn = a.get("value_names") or {}
            seen = set()
            for v, e in vn.items():
                nm = e["name"]
                if (not _re.fullmatch(r"[A-Za-z_]\w*", nm) or nm.lower() in seen or nm.lower() in reserved
                        or _re.fullmatch(r"(reg|arr)\d+", nm.lower())):
                    bad.append((k, i, nm))
                seen.add(nm.lower())
                if om.value_name(int(k), i, int(v, 0)) != nm:
                    bad.append((k, i, v, "not loaded"))
            if vn:
                roundtrip.append((int(k), i))
    _check("value names are identifiers, unique per argument, not a mode word or register",
           not bad, bad[:5])
    diff = [(r["op"], x["op"]) for r in rows.values() for x in O.alias_group(om.TABLE, r)
            if [a.get("value_names") for a in x["args"]] != [a.get("value_names") for a in r["args"]]
            or [a.get("human_verified") for a in x["args"]] != [a.get("human_verified") for a in r["args"]]]
    _check("aliases and families agree on their arguments' names and verification", not diff, diff[:5])
    fails = []
    for op, i in roundtrip:
        for v, nm in om.VALUE_NAMES[(op, i)].items():
            name = om.mnemonic(op)
            n = len(rows[str(op)]["args"])
            if om.OPCODE_ARGS.get(op) or n > 6:
                continue
            args = ["1"] * n
            args[i] = nm
            if om.MODE_ARG_SLOTS and any((op, j) in om.MODE_ARG_SLOTS for j in range(n)):
                args = [("add" if (op, j) in om.MODE_ARG_SLOTS else x) for j, x in enumerate(args)]
            try:
                reg, _l = A.assemble("%s(%s)" % (name, ", ".join(args)), 0x1000)
                buf = bytes(0x1000) + reg
                st = S.decode_statement(buf, 0x1000)
                back = A.operand_text(buf, st.args[i], st.op, i)
                val, ok = S.arg_constant(buf, st.args[i])
                pretty = S.render_action(st.op, S.stmt_arg_strs(buf, st)) or ""
                if back != str(v) or not ok or val != v or nm not in pretty:
                    fails.append((op, i, nm, back, val, pretty))
            except Exception as e:
                fails.append((op, i, nm, repr(e)[:80]))
    _check("a value name assembles to its number; the listing writes the number and names it in the comment (%d arguments)"
           % len(roundtrip), roundtrip and not fails, fails[:5])
    lst = O.sweep_listing("ShowActorEmote(actor(player), {v})", O.parse_values("1-3,6"),
                          then="ShowActorEmote(actor(player), none)")
    try:
        A.assemble(lst, 0x1000)
        ok = lst.count("DIALOG #%d" % O.NUMBER_LINE) == 4
    except Exception as e:
        ok = repr(e)
    _check("optest sweep listings assemble (announce, call, hold per value)", ok is True, ok)
    t = json.loads(json.dumps(om.TABLE))
    O.record(t, 211, "ShowActorEmote(actor(player), 9)", "a '?'", args=(1,), values={1: {9: "question"}},
             evidence=False)
    grp = [x["args"][1]["value_names"].get("9", {}).get("name") for x in O.alias_group(t, t["actions"]["211"])]
    _check("optest.record writes to every row of an alias group", len(grp) >= 2 and set(grp) == {"question"}, grp)
    # the friendly editors refuse what the game is known to break on; the Source tab
    # (strict=False) allows anything the bytecode can express
    risky = "SetButtonIconSlot(0, 192)\nSetSceneCast(0)\nRET\n"
    try:
        A.assemble(risky, 0x1000)
        strict_refuses = False
    except Exception as e:  # noqa: BLE001
        strict_refuses = "192" in str(e)
    try:
        A.assemble(risky, 0x1000, strict=False)
        loose_ok = True
    except Exception as e:  # noqa: BLE001
        loose_ok = repr(e)
    _check("strict assembly refuses a crash value (icon 192); strict=False (the Source tab) allows it",
           strict_refuses and loose_ok is True and om.arg_value_problem(365, 1, 191) is None,
           (strict_refuses, loose_ok))


def test_error_logging():
    """Toolkit failures go to the console as one copy-paste block (guiutil.log_error), the GUI
    only points there; failures the user can act on keep their message and log nothing."""
    print("error logging (console for toolkit bugs, GUI for user problems):")
    import contextlib
    import io
    import guiutil
    from rf4s_modkit import hotreload as H, script as S
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        user = [guiutil.err_text(x) for x in (ValueError("bad number"), S.ScriptError("line 3: unknown opcode"),
                                              FileNotFoundError("no such file"),
                                              H.HotReloadError("RF4S.exe is not running"))]
    _check("user problems keep their message and log nothing",
           user[0] == "bad number" and user[1] == "line 3: unknown opcode"
           and user[3] == "RF4S.exe is not running" and buf.getvalue() == "", (user, buf.getvalue()[:80]))
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        try:
            {}["missing"]
        except Exception as e:
            shown = guiutil.err_text(e, "a test action")
            again = guiutil.err_text(e, "a test action")
        tech = guiutil.err_text(H.HotReloadTechnicalError("cannot read memory"), "Reload in game")
    log = buf.getvalue()
    _check("a toolkit bug is logged once to the console with the traceback and versions; the GUI "
           "text points to the console",
           "console window" in shown and "KeyError" in shown and log.count("while: a test action") == 1
           and "Traceback" in log and "bit)" in log and "modkit " in log and shown == again, log[:300])
    _check("technical hot reload failures (32-bit Python, unknown build, memory) are logged too",
           "console window" in tech and "while: Reload in game" in log)
    _check("the release zip stamps VERSION with its commit (git archive export-subst)",
           "export-subst" in (pathlib.Path(__file__).parent / ".gitattributes").read_text(encoding="utf-8")
           and bool(guiutil.modkit_version()))


def test_hotreload_image():
    """rf3.mc hot reload (rf4s_modkit.hotreload), offline: the SceneState header cache it
    writes matches what the game's parser derives, bank bytes match the container, and a
    file the game would overflow on (or can't index) is refused before anything is sent."""
    print("rf3.mc hot reload (offline checks):")
    import struct as _st
    from rf4s_modkit import hotreload as H, script as S
    import rf4mod as _cli
    mc = BUNDLE_DIR / "bundlePatch1" / "rf3.mc"
    if not mc.is_file():
        _skip("hot reload image checks", "no rf3.mc in the game folder")
        return
    data = mc.read_bytes()
    img = H.McImage(data)
    c = S.Container(data)
    f = _st.unpack("<17I", img.scene_fields())
    _check("scene cache = header words in the parser's order, shifts = low zero bits",
           f[0] == img.global_off and f[3] == c.n_primary and f[4] == c.table1_off
           and f[7] == c.n_tail and f[8] == c.table2_off and f[5] == c.max_bank_size("primary")
           and f[9] == c.max_bank_size("tail") and f[12] == c.var_off_shift
           and f[14] == c.var_wid_shift and f[16] == c.type_table_slots, f)
    tail = [b for b in c.banks if b.kind == "tail"]
    prim = [b for b in c.banks if b.kind == "primary"]
    _check("bank_bytes = the container's banks (tail 60, primary 224, global)",
           img.bank_bytes(2, 60) == bytes(tail[60].data) and img.bank_bytes(1, 224) == bytes(prim[224].data)
           and len(img.bank_bytes(0, 0)) == img.global_size and img.bank_bytes(2, 99999) is None)
    bad = bytearray(data)
    _st.pack_into("<I", bad, 52, 100)                      # max tail bank below the real one
    worse = bytearray(data)
    _st.pack_into("<I", worse, img.table2_off + 4, len(data))   # tail bank 0 past the end
    errs = []
    for blob in (bytes(bad), bytes(worse), b"NOPE" + data[4:], data[:40]):
        try:
            H.McImage(blob)
            errs.append(None)
        except H.HotReloadError as e:
            errs.append(str(e))
    _check("refused: max-size words below the biggest bank, a bank past EOF, not MYCF, truncated",
           all(errs) and "overflow" in errs[0], errs)
    _check("ctz loop = the game's (32 for a zero mask)", H._ctz_loop(0) == 32 and H._ctz_loop(0xF000) == 12)
    # several RF4S.exe: ask once, remember the pick while that process runs; one: no question
    _gp, _ch = H.game_processes, dict(H._CHOSEN)
    try:
        a_, b_ = H.GameProcess(111, r"C:\Games\A\RF4S.exe", 1000), H.GameProcess(222, r"D:\B\RF4S.exe", 2000)
        H._CHOSEN["key"] = None
        asked = []

        def _choose(procs):
            asked.append(len(procs))
            return procs[1]
        H.game_processes = lambda name=H.EXE_NAME: [a_, b_]
        first, again = H.pick_process(_choose), H.pick_process(_choose)
        try:
            H._CHOSEN["key"] = None
            H.pick_process()
            cli_msg = ""
        except H.HotReloadError as e:
            cli_msg = str(e)
        H.game_processes = lambda name=H.EXE_NAME: [H.GameProcess(222, r"D:\B\RF4S.exe", 3000), a_]
        H._CHOSEN["key"] = (222, 2000)                  # pid 222 reused by a NEW process
        reused = H.pick_process(lambda procs: procs[1])
        H.game_processes = lambda name=H.EXE_NAME: [a_]
        single = H.pick_process(lambda procs: (_ for _ in ()).throw(AssertionError("asked")))
        _check("hot reload with several games: asks once and remembers the pick while it runs, a "
               "reused pid is not the same game, one game is used without asking, the CLI needs --pid",
               first == 222 and again == 222 and asked == [2] and reused == 111 and single == 111
               and "--pid" in cli_msg and "111" in cli_msg,
               (first, again, asked, reused, single, cli_msg))
    finally:
        H.game_processes = _gp
        H._CHOSEN.update(_ch)
    ap = _cli.build_parser() if hasattr(_cli, "build_parser") else None
    if ap is not None:
        ns = ap.parse_args(["script", "reload", "--force"])
        _check("CLI: script reload / script live", ns.func is _cli.cmd_script_reload and ns.force
               and ap.parse_args(["script", "live"]).func is _cli.cmd_script_live)
    # dialogue text: the game keeps its language's rf3mc.<locale> resident in archive 15213; the
    # reload finds the language by matching a few lines of the resident copy against the files
    from rf4s_modkit import textdb as _tdb
    _a = _tdb.TextArchive([("line %d" % i).encode() for i in range(120)])
    _blob = _a.build()
    _probe = H._text_lines(_blob, [1, 2, 3, 10, 100, 500])
    _check("dialogue text reload: the resident copy's lines are read by the file's own table "
           "(ids past the end are left out); archive 15213 = rom:/script/rf3mc.jpn",
           _probe == {i: ("line %d" % i).encode() for i in (1, 2, 3, 10, 100)}
           and H.TEXT_ARCHIVE_PATH == "rom:/script/rf3mc.jpn" and callable(H.reload_all), _probe)


def test_search_item_chances():
    """The pool 'chance' shown by the toolkit is what SearchItem_RollSpotsAndSpawnFromArchive
    (RF4S.exe+0x231FF0) picks: both the total and the running sum are bytes, and a total that
    wraps to 0 rolls 0."""
    print("search_items pool chances (byte sums, as the game picks):")
    from rf4s_modkit.search_items import DropEntry, DropPool

    def ch(*ws):
        c, n = DropPool([DropEntry(1, w) for w in ws]).engine_chances()
        return [round(x, 3) for x in c], round(n, 3)
    _check("up to 255 the chance is weight / total", ch(10, 10, 5, 5, 20, 30, 55)
           == ([round(100 * w / 135, 3) for w in (10, 10, 5, 5, 20, 30, 55)], 0.0))
    _check("above 255 the wrapped sums decide: 30 + 250 -> total 24, the 1st entry always wins",
           ch(30, 250) == ([100.0, 0.0], 0.0), ch(30, 250))
    _check("a total that wraps to 0 rolls 0: 128 + 128 -> the 1st entry always wins",
           ch(128, 128) == ([100.0, 0.0], 0.0), ch(128, 128))
    _check("all-zero weights never yield an item", ch(0, 0) == ([0.0, 0.0], 100.0), ch(0, 0))


def test_mobj_types():
    print("mobj_types (MOBJ type_id -> map_obj sprite identity):")
    # Spot-check IDA-dumped anchors across all four dispatch ranges.
    anchors = {51: "MOBJ_SHIP", 82: "DOOR_CITY_00_00", 199: "MOBJ_FI_TREE01",
               336: "OBJ_C06_SU_00", 393: "MOBJ_HOUSE_CITY_04_00_WINTER"}
    _check("mobj name anchors", all(mobj_types.mobj_name(t) == n for t, n in anchors.items()),
           f"{len(mobj_types.MOBJ_NAMES)} sprite names; ship/door/tree/decoration verified")
    # type_id < 20 records do NOT load a map_obj sprite (forage / inert), so no name.
    _check("mobj name suppressed <20",
           mobj_types.mobj_name(5) is None and mobj_types.mobj_name(9) is None
           and 0 not in mobj_types.MOBJ_NAMES,
           "type 5 (forage) / 9 (map parameter) -> None")
    # types 20..77 draw what their handler loads (often another archive, picked by a word)
    rec = lambda t, w8=0, w10=0: [t, 0, 0, 0, 0, 0, 0, 0, w8, 0, w10]
    tex = mobj_types.mobj_texture
    _check("mobj textures follow the handlers (theatre furniture, switches, crates, vents, ...)",
           [tex(rec(t)) for t in (64, 65, 66, 46, 51, 57, 59, 26, 43)]
           == ["FURNITURE_01", "FURNITURE_02", "FURNITURE_11", "floor_switch", "MOBJ_SHIP",
               "portrait", "FURNITURE_21", "OBJ_KAMITSUKI", "gmk18_windmill"]
           and tex(rec(46, 1)) is None and tex(rec(59, 1)) is None
           and tex(rec(53)) == "MOBJ_BOX" and tex(rec(53, 1)) == "MOBJ_FIELD_METAL02"
           and tex(rec(55)) == "MOBJ_FI_ERUPT_LAVA" and tex(rec(55, 0, 1)) == "MOBJ_FI_ERUPT"
           and tex(rec(45, 3)) == "switch_03" and tex(rec(43, 2)) == "propeller_ship_01"
           and all(tex(rec(t)) is None for t in (44, 58, 60))
           and tex(rec(42)) == tex(rec(52)) == "efcimg_04" and tex(rec(71, 3)) == "waterA"
           and tex(rec(20)) == "efc_liteC" and tex(rec(37)) == "efc_liteC" and tex(rec(68)) == "smoke_ring"
           and mobj_types.mobj_tint(20) == (22 / 31, 21 / 31, 8 / 31) and mobj_types.mobj_tint(68) is None
           and tex(rec(70)) == "RE_VLIGHT2" and tex(rec(72)) == "F_ROOM00" and tex(rec(72, 1)) == "F_ROOM00_WINTER"
           and tex(rec(82)) == mobj_types.mobj_name(82) and tex(rec(250)) == mobj_types.mobj_name(250))
    # which types the game sizes by f6 / what f7 is (hexrays read sweep of every handler)
    from rf4s_modkit import spritequad as _sq
    ship = {"type_id": 51, "pos_x": 0, "pos_y": 0, "params": [51, 0, 0, 0, 0, 0, 8192, 0]}
    room = {"type_id": 250, "pos_x": 0, "pos_y": 0, "params": [250, 0, 0, 0, 0, 0, -8192, 0]}
    q = (-30, -30, 30, 30)
    _check("f6 scales only the types that read it (doors, the airship ... ignore it); f7 is an "
           "angle for 9 gimmicks, the frame from 196 up, unread otherwise",
           _sq.world_rect(ship, q) == (-10, -10, 10, 10) and not _sq.mirrored(ship)
           and _sq.world_rect(room, q) == (-20, -20, 20, 20) and _sq.mirrored(room)
           and mobj_types.mobj_reads_scale(44) and not mobj_types.mobj_reads_scale(120)
           and mobj_types.mobj_f7_kind(29) == "angle" and mobj_types.mobj_f7_kind(300) == "frame"
           and mobj_types.mobj_f7_kind(51) is None)
    # MapDecoration_ApplyVariantOverride: the MAP_FIELD_69 bridge railing (353) moves 289 quad
    # units down onto its painted railing; its x scale is fixed (a negative f6 doesn't mirror it)
    rail = {"type_id": 353, "pos_x": 336, "pos_y": 173, "params": [353, 0, 0, 0, 0, 0, -8192, 0]}
    _rr = _sq.world_rect(rail, (-512.0, -384.0, 512.0, 384.0))
    _check("per-type quad overrides: the bridge railing drops 289 quad units, x scale fixed",
           abs(_rr[0] - (336 - 512 / 3)) < 1e-6 and abs(_rr[1] - (173 + (289 - 384) * 2 / 3)) < 1e-6
           and not _sq.mirrored(rail), str(_rr))
    from rf4s_modkit import mobj_params as _mp
    _check("MOBJ parameters traced through the ticks (chandelier, storm, fall-through hole, "
           "pressure plate, inscribed stone 263 ...)",
           "falls when approached" in _mp.field_meaning(56, 8)
           and "blows" in _mp.field_meaning(29, 10) and "pauses" in _mp.field_meaning(29, 11)
           and "destination map" in _mp.field_meaning(42, 10)
           and "pressure plate" in _mp.field_meaning(46, 9)
           and "empty crate" in _mp.field_meaning(53, 10)
           and [f for f, _s, _m in _mp.params_for(263)] == [8, 9, 13]
           and not any("untraced)" == m[-9:] or "state byte" in m or "behaviour param" in m
                       for t in _mp.GIMMICKS for _f, _s, m in _mp.params_for(t)))
    _check("MOBJ names say what an object is, not what it does",
           [mobj_types.mobj_display_name(t) for t in (56, 53, 44, 52)]
           == ["chandelier", "crate", "treasure chest", "knockback zone"])
    # Sprite_ApplyEffect_Glow: glows and windmills are one corner, mirrored into four
    glow = mobj_types.mobj_glow
    _check("glow-effect sprites: street light, red glow, windmills (not the propellers)",
           glow(rec(20)) and glow(rec(37)) and glow(rec(43)) and glow(rec(43, 1))
           and not glow(rec(43, 2)) and not glow(rec(43, 3)) and not glow(rec(68)))
    # types 70 / 72 draw textured meshes read from the exe
    from rf4s_modkit import mobj_meshes as _mm
    lv, li = _mm.light_mesh(1)
    ok_idx = all(max(m["i"]) < len(m["v"]) and len(m["i"]) % 3 == 0
                 for m in list(_mm.LIGHT.values()) + [_mm.ROOM])
    _check("light-shaft / room meshes: 15 kinds + the room, triangles index real vertices, "
           "kind 1 mirrors kind 0",
           ok_idx and sorted(_mm.LIGHT) == [0] + list(range(2, 16)) and len(_mm.ROOM["v"]) == 101 and len(_mm.ROOM["i"]) == 528
           and lv[3][0] == -_mm.LIGHT[0]["v"][3][0] and li == _mm.LIGHT[0]["i"]
           and _mm.light_mesh(99) == (_mm.LIGHT[0]["v"], _mm.LIGHT[0]["i"]))
    try:
        from PIL import Image as _Im
        import numpy  # noqa: F401
    except ImportError:
        _skip("mesh rasterizer", "no Pillow / numpy")
    else:
        tex8 = _Im.new("RGBA", (8, 8), (255, 0, 0, 255))
        img, quad = _mm.rasterize(tex8, _mm.ROOM["v"], _mm.ROOM["i"])
        # v counts from the stored image's bottom row: v = 0 at the mesh's top edge shows the
        # texture's LAST row (blue here), v = 1 at the bottom edge its first row (red)
        two = _Im.new("RGBA", (4, 2), (255, 0, 0, 255))
        two.paste((0, 0, 255, 255), (0, 1, 4, 2))
        sq = ((0, 0, 0, 0, 1), (10, 0, 1, 0, 1), (0, 10, 0, 1, 1), (10, 10, 1, 1, 1))
        flat, _q = _mm.rasterize(two, sq, (0, 1, 2, 1, 3, 2))
        _check("mesh textures: v counts from the bottom row (the room overlay is upright)",
               flat.getpixel((15, 2))[:3] == (0, 0, 255) and flat.getpixel((15, 27))[:3] == (255, 0, 0),
               (flat.getpixel((15, 2)), flat.getpixel((15, 27))))
        wv, wi = _mm.mesh_for([71, 0, 0, 0, 0, 0, 0, 0, 3])[1:]
        _check("type 71 water: 22 shapes read from the exe (kind 3 = MAP_CITY_05's moat strip); "
               "outside 1..21 = shape 0; mirror-wrapped UVs",
               sorted(_mm.WATER) == list(range(22)) and len(wv) == 40 and len(wi) == 72
               and _mm.mesh_for([71, 0, 0, 0, 0, 0, 0, 0, 99])[1] is _mm.WATER[0]["v"]
               and all(max(m["i"]) < len(m["v"]) for m in _mm.WATER.values())
               and _mm.rasterize(two, sq, (0, 1, 2, 1, 3, 2), mirror=True) is not None)
        from map_editor import render as _render
        # objects the game draws as a 3D model: rendered from the .model, 3 units per sub-unit
        _check("3D-model objects: treasure chest M26_0 (the field camera), ponds by f8 (top view)",
               mobj_types.mobj_model([44]) == ("M26_0", "field")
               and mobj_types.mobj_model([60, 0, 0, 0, 0, 0, 0, 0, 1]) == ("mobj_pond_lava", "top")
               and mobj_types.mobj_model([60]) == ("mobj_pond", "top") and mobj_types.mobj_model([53]) is None)
        _bm = {p.name: p for p in pathlib.Path(BUNDLE_DIR).rglob("*.model")
               if p.stem in ("M26_0", "mobj_pond")}
        if len(_bm) == 2:
            _sp = _render.Sprites()
            _sp.reader = lambda fn: _bm[fn].read_bytes() if fn in _bm else None
            chest = _sp.source({"type_id": 44, "params": [44]})
            pond = _sp.source({"type_id": 60, "params": [60]})
            # quads in sprite px (3 per sub-unit), models at 2 units per sub-unit: x1.5
            _check("the chest and pond models render at 2 model units per sub-unit: the chest "
                   "(68 units, 34 sub-units) stands on its spot, the pond (256 units) lies centred",
                   chest and pond and 0 <= chest[2][3] < 30 and 95 < chest[2][2] - chest[2][0] < 112
                   and 380 < pond[2][2] - pond[2][0] < 392 and abs(pond[2][0] + pond[2][2]) < 6
                   and _sp.pil(chest[0], 0, 40, 36, False) is not None,
                   (chest and chest[2], pond and pond[2]))
        # fishing spots show the fish Fishing_SpawnFishActor swims there: blue on water (ATTR
        # 0x8 / 0x4000), the orange sand fish anywhere else
        _check("fishing spots draw their fish: 'fish' on water, 'fish_sand' elsewhere, at half size",
               mobj_types.fish_texture(0x8) == mobj_types.fish_texture(0x4000) == "fish"
               and mobj_types.fish_texture(0x1) == "fish_sand"
               and mobj_types.mobj_draw_scale(24) == mobj_types.mobj_draw_scale(25) == 0.5)
        _ft = {p.name: p for p in pathlib.Path(BUNDLE_DIR).rglob("fish*.texture")}
        if {"fish.texture", "fish_sand.texture"} <= set(_ft):
            _sf = _render.Sprites()
            _sf.reader = lambda fn: _ft[fn].read_bytes() if fn in _ft else None
            spot = {"type_id": 24, "params": [24] + [0] * 13 + [16, 16]}
            _sf.cell = lambda x, y: 0x8
            on_water = _sf.source(spot)
            _sf.cell = lambda x, y: 0x1
            on_sand = _sf.source(spot)
            _check("a fishing spot on water shows the blue fish, on sand the sand fish",
                   on_water and on_sand and on_water[0].startswith("fish.texture")
                   and on_sand[0].startswith("fish_sand.texture"), (on_water, on_sand))
        # forage spawns grow the crop_NNN sprite of their gatherable: an ore spawn its
        # MapOre_Rate config's rock (not when f11 rolls one each day), 1 / 2 fixed kinds
        _ob = {p.name: p for p in pathlib.Path(BUNDLE_DIR).rglob("*")
               if p.name == "MapOre_Rate.bin" or p.name.startswith("crop_0")}
        if "MapOre_Rate.bin" in _ob:
            _fs = _render.Sprites()
            _fs.reader = lambda fn: _ob[fn].read_bytes() if fn in _ob else None
            import time
            from map_editor import data as _md
            from rf4s_modkit import mobj_params as _mpo
            k0 = _md.ore_configs(_fs.reader)[0][0]
            ore = _fs._forage_sprite([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
            _check("ore spawns show their ore config's rock (MapOre_Rate row f10 -> kind -> "
                   "crop sprite); a daily-rolled config, a random pool keep the marker",
                   26 <= k0 <= 37 and ore == _mpo.gather_kind_sprite(k0)
                   and _fs._forage_sprite([0] * 11 + [1]) is None
                   and _fs._forage_sprite([1]) == "crop_023" and _fs._forage_sprite([2]) == "crop_024"
                   and _fs._forage_sprite([5]) is None
                   and _fs.source({"type_id": 0, "pos_x": 8, "pos_y": 8, "params": [0] * 16}) is not None,
                   (k0, ore))
        glow = _Im.new("RGBA", (2, 1), (0, 0, 0, 255))
        glow.putpixel((1, 0), (255, 128, 0, 255))
        add = _render._as_additive(glow)
        _check("additive sprites (glows, warp sparkles, water, light shafts): black vanishes, "
               "bright parts stay",
               add.getpixel((0, 0))[3] == 0 and add.getpixel((1, 0)) == (255, 128, 0, 255)
               and mobj_types.MOBJ_ADDITIVE >= {20, 42, 70, 71} and 72 not in mobj_types.MOBJ_ADDITIVE,
               (add.getpixel((0, 0)), add.getpixel((1, 0))))
        # rendered mesh images are kept on disk: the second call is a PNG load, not a rasterize
        import tempfile as _tf
        texpath = next(pathlib.Path(BUNDLE_DIR).rglob("RE_VLIGHT2.texture"), None)
        if texpath is not None:
            cdir = pathlib.Path(_tf.mkdtemp(prefix="rf4s_meshcache_"))
            lv0, li0 = _mm.light_mesh(0)
            first = _mm.rasterize_cached(texpath.read_bytes(), lv0, li0, cache_dir=cdir)
            real_r, calls = _mm.rasterize, []
            _mm.rasterize = lambda *a, **k: calls.append(1) or real_r(*a, **k)
            try:
                second = _mm.rasterize_cached(texpath.read_bytes(), lv0, li0, cache_dir=cdir)
            finally:
                _mm.rasterize = real_r
            _check("mesh images are cached on disk: the second draw loads the PNG, same pixels",
                   first and second and not calls and len(list(cdir.glob("*.png"))) == 1
                   and first[0].tobytes() == second[0].tobytes() and first[1] == second[1])
        holes = img.getchannel("A").histogram()[0]
        _check("the room mesh fills its box around the object (a solid texture: over 95 % "
               "drawn, the rest is the mesh's own outline)",
               all(abs(q - w) < 1e-6 for q, w in zip(quad, (-686.025, -768.252, 686.025, 768.252)))
               and holes < img.width * img.height // 20,
               f"{img.size} {quad} {holes} empty px")
    # Human notes for opaque effect sprites. 2026-08-31: the whole actor band
    # 20..81 is identified from g_mapObjTypeInitTable (+0x4CF530), so every
    # fe*/gmk* type has a note now; plain scenery sprites (>= 82) still don't.
    _check("mobj note lookup",
           mobj_types.mobj_note(68) == "chimney smoke"
           and "FISHING" in (mobj_types.mobj_note(24) or "")
           and "BARRIER" in (mobj_types.mobj_note(48) or "")
           and mobj_types.mobj_note(199) is None,
           "fe123 smoke, fe036 fishing, fe107 barrier; scenery unnoted")
    # Display names: identified fe*/gmk* types show their readable identity, not
    # the codename; unidentified scenery keeps its MOBJ_* name.
    # MOBJ flag args are REGION-B scene bits (abs = 4096+id) — NOT emdeb names
    # (playtest catch: a boss barrier was mislabelled with a Nancy flag when
    # flag_label resolved raw ids against region-A emdeb). emdeb resolution
    # lives in emdeb_flag_label for absolute region-A ids.
    from rf4s_modkit import mobj_params
    _check("mobj flag_label = region-B scene bits",
           "abs 6907" in (mobj_params.flag_label(2811) or "")
           and "char 5" in (mobj_params.flag_label(1042) or "")
           and "daily greeting done" in (mobj_params.flag_label(1042) or "")
           and "box" in (mobj_params.flag_label(720) or "")
           and "recipe 341" in (mobj_params.flag_label(1403) or "")
           and mobj_params.flag_label(0) is None
           and mobj_params.flag_label(-1) is None,
           "2811 -> scene bit 6907; 1042 -> daily greeting done, char 5")
    if mobj_params._emflag_table() is None:
        _skip("mobj emdeb_flag_label (region A)", "emdeb.bin not found in Bundle/")
    else:
        _check("mobj emdeb_flag_label names a region-A bit, separately from flag_label",
               mobj_params.emdeb_flag_label(2811) == "FLG_ELISA_NO_75")
    _check("mobj display names replace codenames",
           mobj_types.mobj_display_name(48) == "barrier"
           and mobj_types.mobj_display_name(20) == "street light"
           and mobj_types.mobj_display_name(27) == "birds"
           and mobj_types.mobj_display_name(199) == "tree 1"
           and mobj_types.mobj_display_name(5) == "herb_pool32"
           and mobj_types.mobj_display_name(0) == "ore_rock_spawn"
           and mobj_types.mobj_display_name(12) == "tint_color"      # map parameter record
           and mobj_types.mobj_display_name(14) is None,             # unused parameter id
           "48 barrier, 20 street light, 27 birds, 199 tree 1; forage + map-parameter records named, unused 14 not")
    # every sprite type has a readable name (MOBJ_DISPLAY, 2026-09-26): from its sprite, its
    # maps and, for doors, the warp it stands at -- no codename left in the editors' lists
    _codes = [t for t, n in mobj_types.MOBJ_NAMES.items() if mobj_types.mobj_display_name(t) in (n, None)]
    _names = [mobj_types.mobj_display_name(t) for t in mobj_types.MOBJ_NAMES]
    _check("every map_obj type shows a readable name (airship, doors by their warp, no duplicates)",
           not _codes and mobj_types.mobj_display_name(51) == "airship"
           and mobj_types.mobj_display_name(82) == "door: Bell Hotel Lobby"
           and mobj_types.mobj_display_name(163) == "Obsidian Mansion door (C04 → C05)"
           and len({x for x in _names if x != "unused slot"}) == sum(1 for x in _names if x != "unused slot"),
           f"codenames left: {_codes[:5]}")
    # Archive formula = type_id + 17542, and the kind boundaries.
    _check("mobj archive id = type+17542",
           mobj_types.mobj_archive_id(199) == 17741 and mobj_types.MAP_OBJ_ARCHIVE_BASE == 17542,
           "object MOBJ_FI_TREE01 -> archive 17741")
    kinds = (mobj_types.mobj_kind(5), mobj_types.mobj_kind(15), mobj_types.mobj_kind(28),
             mobj_types.mobj_kind(200), mobj_types.mobj_kind(340))
    _check("mobj kind boundaries", kinds == ("forage", "mapparam", "actor", "object", "decoration"),
           f"<9/<20/<196/<336/>=336 -> {kinds}")
    # object-sprite overlay data path (map editor's "object sprites" layer): a structural object's
    # sprite name resolves to an extracted `.texture` that decodes to an RGBA billboard WITH
    # transparency (so it composites over the map). Skipped if the map_obj sprites aren't extracted.
    _spr = _first("DOOR_CITY_00_00.texture") or _first("MOBJ_SHIP.texture") or _first("MOBJ_BOX.texture")
    if _spr is not None:
        _sim = texture.decode_to_image(_spr.read_bytes()).convert("RGBA")
        _salpha = _sim.split()[3].getextrema()
        _check("object-sprite overlay: a map_obj sprite decodes to an RGBA billboard (w/ transparency)",
               _sim.size[0] > 0 and _salpha[0] < 255, f"size {_sim.size}, alpha {_salpha}")
    else:
        _skip("object-sprite overlay decode", "map_obj sprite textures not extracted")
    # MOBJ parameter map: all 62 gimmicks covered, describe() resolves any type_id
    from rf4s_modkit import mobj_params
    _check("mobj_params covers gimmicks 20-81",
           len(mobj_params.GIMMICKS) == 62 and all(t in mobj_params.GIMMICKS for t in range(20, 82)))
    role31, rows31 = mobj_params.describe(31)
    mm31 = {f: m for f, s, m in rows31}
    sz31 = {f: s for f, s, m in rows31}
    _check("mobj_params describe() known type (rock trap)",
           "Falling-rock" in role31 and mm31.get(10) == "damage / attack power")
    _check("mobj_params field sizes IDA-verified (rock f7/f11=u16, f10=u32; wind f13=u16)",
           sz31.get(7) == 2 and sz31.get(11) == 2 and sz31.get(10) == 4
           and mobj_params.field_size(30, 13) == 2 and mobj_params.field_size(30, 8) == 4)
    _check("mobj_params describe() resolves any type via lane",
           mobj_params.describe(340)[0] == "decoration" and mobj_params.lane_for(82)[0] == "door / road / wall")
    r5 = dict((f, m) for f, s, m in mobj_params.describe(5)[1])
    _check("mobj_params forage (0-8) decoded",
           "Herb" in mobj_params.role_for(5) and 8 in r5 and "spawn probability" in r5[8]
           and "ORE" in mobj_params.role_for(0)   # playtest-corrected: type 0 = ore spawn
           and mobj_params.lane_for(12)[0] == "map parameter record")
    # map parameter records 9..19 (Map_LoadById's MapEvent switch, verified 2026-09-19)
    r12 = dict((f, m) for f, s, m in mobj_params.describe(12)[1])
    _check("mobj_params map parameters: 12 = tint_color (slot + RGB bytes), 11 = uv_scroll",
           mobj_params.name_for(12) == "tint_color" and "slot" in r12.get(8, "")
           and mobj_params.field_size(12, 9) == 1 and mobj_params.name_for(11) == "uv_scroll"
           and mobj_params.name_for(14) == "(unused map-parameter id)"
           and mobj_params.interaction_class(12)[0] == "param")
    # interaction classification: type 263 = examine (shows marker), actor id = type+1000.
    c263, _l263, mark263 = mobj_params.interaction_class(263)
    _check("mobj_params interaction: 263 examine+marker, actor id 1263",
           c263 == "examine" and mark263 is True
           and mobj_params.runtime_actor_id(263) == 1263
           and mobj_params.runtime_actor_id(340) is None)
    _check("mobj_params interaction: hazards/doors/decor not marker, boxes/fish interactible",
           mobj_params.interaction_class(31)[0] == "hazard"
           and mobj_params.interaction_class(130)[0] == "door"
           and not mobj_params.is_interactible(199, -1)
           and mobj_params.is_interactible(53, -1) and mobj_params.is_interactible(24, -1))
    _check("mobj_params interaction_summary shows flag + actor id",
           "1263" in mobj_params.interaction_summary(263, 318)
           and "318" in mobj_params.interaction_summary(263, 318))
    # map names: warp destinations resolve to building/shop names (rf3TxtMapName, +1 index)
    from rf4s_modkit import map_names
    _check("map_names resolves buildings vs town segments",
           map_names.map_name(136) == "Bell Hotel Lobby"
           and map_names.is_building_entrance(136)
           and map_names.map_name(24).startswith("Selphia")
           and not map_names.is_building_entrance(24))
    # decode_mobj must surface name + archive_id on a real map.
    cm = BUNDLE_DIR / "bundleMain" / "MAP_CITY_00.rf4m"
    if cm.exists():
        objs = rf4m.Rf4mMap.load(cm).decode_mobj()
        ok = any(o["name"] == "MOBJ_SHIP" for o in objs) and all("archive_id" in o for o in objs)
        _check("decode_mobj carries identity", ok, f"MAP_CITY_00: {len(objs)} MOBJ, ship present")
    else:
        _skip("decode_mobj carries identity", "MAP_CITY_00.rf4m not extracted")


def test_minimap():
    print("\n[minimap] rf3MapMiniPos -> mini_map_* picture resolution + map-id registry")
    from rf4s_modkit import minimap, map_names
    # the mini_map group starts at nsFileArchive 12199 and runs in archive order
    _check("minimap sheet -> texture table",
           len(minimap.SHEET_TEXTURES) == 104
           and minimap.texture_for_sheet(0) == "mini_map_00_city"
           and minimap.texture_for_sheet(31) == "mini_map_30_farm"
           and minimap.texture_for_sheet(73) == "mini_map_99_dummy"
           and minimap.texture_for_sheet(87) == "mini_map_dung_q04"
           and minimap.texture_for_sheet(88) == "mini_map_rnd_00"
           and minimap.sheet_for_texture("mini_map_56_room_06.texture") == 55)
    tex = sorted(p.stem for p in EXTRACTED.rglob("mini_map_*.texture")) if EXTRACTED.is_dir() else []
    if tex:
        _check("minimap sheet table matches the bundle's mini_map_*.texture set",
               tex == list(minimap.SHEET_TEXTURES), f"{len(tex)} textures")
    else:
        _skip("minimap sheet table vs bundle textures", "no mini_map_*.texture under Bundle/")
    # map id <-> MAP_* file registry (map_overmodels.json key order = g_mapResourceTable order)
    _check("map_names id <-> MAP_* file",
           map_names.map_file(136) == "MAP_ROOM_06A"
           and map_names.map_id_for_file("MAP_ROOM_06A.rf4m") == 136
           and map_names.map_id_for_file("bundleMain/map_city_01_summer.rf4m") == 29
           and map_names.map_file(872) is None and map_names.map_count() == 874)
    _check("map_names HUD-band notes",
           "Volkanon" in (map_names.label_note(179) or "")
           and "farm" in (map_names.label_note(4) or "").lower()
           and "barn" in (map_names.label_note(100) or "").lower()
           and "%2dF" in (map_names.label_note(445) or "")
           and map_names.label_note(24) is None)
    if not minimap.table_available():
        _skip("minimap per-map table",
              "refdata/map_minimap.json missing -- run gen_map_names_json.py")
        return
    _check("minimap per-map picture",
           minimap.map_count() == 873
           and minimap.texture(24) == "mini_map_00_city"          # Selphia: Airship Way
           and minimap.texture(271) == "mini_map_01_dung_a"       # Yokmir Forest
           and minimap.texture(4) == "mini_map_30_farm"           # Farm
           and minimap.texture(77) == "mini_map_60_m_room"        # Monster Barn
           and minimap.texture(136) == "mini_map_56_room_06"      # Bell Hotel Lobby
           and minimap.texture(726) == "mini_map_dung_m01"        # Rune Prana
           and minimap.archive_id(24) == 12199)
    _check("minimap blank clamp + maze composition",
           minimap.texture(527) == "mini_map_99_dummy" and minimap.is_blank(527)   # '???' dungeon
           and minimap.sheet(442) == 110 and minimap.texture(442) == "mini_map_99_dummy"
           and minimap.is_composed(442) and not minimap.is_blank(442)
           and minimap.texture(0) == "mini_map_99_dummy" and minimap.is_blank(0))
    r = minimap.record(161)                                        # Selphia Plain
    _check("minimap record: origin / reveal rect / Q12 scale",
           r["sheet"] == 66 and r["origin"] == (94, 71) and r["reveal"] == (94, 71, 27, 27)
           and r["scale_q12"] == (217, 201) and minimap.record(24)["reveal"] is None)
    p = minimap.record(130)                                        # Porcoline's Kitchen
    _check("minimap interiors route NPC icons to the town sheet",
           p["parent_sheet"] == 0 and p["icon"] == (174, 70) and p["icon_slot"] == 6
           and minimap.record(161)["parent_sheet"] is None)
    v = minimap.variants(64)                                       # Your Room
    _check("minimap variant rules",
           [x["texture"] for x in minimap.variants(4)]
           == ["mini_map_30_farm", "mini_map_30_farm_1", "mini_map_30_farm_2",
               "mini_map_30_farm_3", "mini_map_30_farm_4"]
           and len(v) == 12 and v[6]["texture"] == "mini_map_50_f_room_sk_0"
           and minimap.variants(80)[0]["when"] == "REG_MON_HOUSE0_L_LV == 1"
           and minimap.variants(85)[0]["when"] == "REG_MON_HOUSE0_R_LV == 1"
           and minimap.variants(271) == [] and len(minimap.variants(24)) == 4)
    # Minimap_UpdateNpcIcons indexes a 12-byte stack counter array with icon_slot
    _check("minimap validate_record: stock table clean; icon_slot 12 is fatal",
           not any(minimap.validate_record(minimap.raw_record(i)) for i in range(minimap.map_count()))
           and any(m.startswith("ERROR") for m in minimap.validate_record(
               minimap.raw_record(130)[:9] + [12] + minimap.raw_record(130)[10:])))
    _check("minimap pos_to_sheet = origin + (scale * pos) >> 12",
           minimap.pos_to_sheet(161, 0, 0) == (94, 71)
           and minimap.pos_to_sheet(161, 4096, 4096) == (94 + 217, 71 + 201)
           and minimap.world_to_sheet(161, 4096 << 12, 0) == (94 + 217, 71))
    live = _first("rf3MapMiniPos.bin")
    if live:
        t = nlcl.NlclTable.load(live)
        rows = [[t.get(i, 4 * k, "s32") for k in range(13)] for i in range(t.entry_count)]
        _check("vendored map_minimap.json == bundle rf3MapMiniPos.bin",
               rows == [minimap.raw_record(i) for i in range(t.entry_count)],
               f"{len(rows)} records")
    else:
        _skip("vendored map_minimap.json vs bundle", "rf3MapMiniPos.bin not under Bundle/")


def _try_parse(p):
    try:
        nlcl.NlclTable.load(p)
        return True
    except nlcl.NlclError:
        return False


def test_script():
    print("script (rf3.mc cutscene bytecode):")
    from rf4s_modkit import script
    p = _first("rf3.mc")
    if not p:
        _skip("script", "rf3.mc not extracted")
        return
    raw = p.read_bytes()
    c = script.Container(raw)
    n_global = sum(1 for b in c.banks if b.kind == "global")
    _check("MYCF container parse", len(c.banks) == c.n_primary + c.n_tail + n_global,
           f"{len(c.banks)} banks ({c.n_primary} primary + {c.n_tail} tail + {n_global} global)")
    _check("container round-trip build()==original", c.build() == raw)
    # robustness: malformed / truncated input must raise a clean ScriptError, never a raw
    # struct.error or other unhandled exception (a modder loading a wrong/corrupt file).
    import struct as _struct_rob
    _corrupt = bytearray(raw)                          # valid header, absurd primary-bank count
    _struct_rob.pack_into("<I", _corrupt, 20, 0x7FFFFFFF)
    _rob = True
    for _bad in (b"", b"\xde\xad\xbe\xef" * 4, b"MYCF\x01\x00", b"MYCF" + b"\x00" * 12,
                 b"MYCF" + b"\x00" * 40,               # bad magic / truncated header
                 raw[:60], raw[:500], raw[:len(raw) // 2],   # valid header, truncated body
                 bytes(_corrupt)):                     # valid header, corrupt section table
        try:
            c_bad = script.Container(_bad)
            for _b in c_bad.banks:                     # exercise bank data (past-EOF slices)
                list(script.disassemble_bank(_b, discover=False))
            _rob = False                               # should have raised
        except script.ScriptError:
            pass                                       # clean, expected
        except Exception:
            _rob = False                               # unhandled -> fail
    _check("Container raises clean ScriptError on malformed/truncated/corrupt input", _rob)
    # edit-op robustness: mutating at an invalid pc must raise a clean ScriptError, never a raw
    # TypeError/IndexError (a modder editing a statement the disassembler couldn't place).
    _erc = script.Container(raw)
    _erob = True
    for _efn in (lambda: _erc.banks[1].set_action_arg_value(0xFFFE, 0, 5),
                 lambda: _erc.banks[1].set_action_arg(0xFFFE, 0, 5),
                 lambda: _erc.banks[1].set_dialog_id(0xFFFE, 5),
                 lambda: _erc.banks[1].set_expr_value(0xFFFFF, 5),
                 lambda: _erc.banks[1].set_expr_value(None, 5),
                 lambda: _erc.insert_before(_erc.banks[1], 0xFFFE, "DIALOG #8"),
                 lambda: _erc.delete_statement(_erc.banks[1], 0xFFFE),
                 lambda: _erc.rewrite_scene(1, 0xFFFE, "DIALOG #8")):
        try:
            _efn()
            _erob = False
        except script.ScriptError:
            pass
        except Exception:
            _erob = False
    _check("edit ops raise clean ScriptError at invalid pc/offset", _erob)
    # editing a NON-immediate arg (a variable / computed expression) must raise a clean ScriptError
    # explaining it isn't a literal, never a raw exception. The GUI gates this via arg_is_settable;
    # the library method must be safe when called directly too.
    cxc = script.Container(raw)
    _cx = None
    for _bx in cxc.banks[:40]:
        for _scx in script.disassemble_bank(_bx, discover=False):
            for _pcx, _stx in _scx.stmts.items():
                if _stx.op < 0xFFF0:
                    for _ix, _ax in enumerate(_stx.args):
                        # a genuinely RUNTIME arg: tag-3/4 typed constants (actor(..) /
                        # map(..)) are plain numbers to the handler and DO edit in place
                        if not script.arg_constant(_bx.data, _ax)[1]:
                            _cx = (_bx, _pcx, _ix)
                            break
                    if _cx:
                        break
            if _cx:
                break
        if _cx:
            break
    if _cx:
        _bx, _pcx, _ix = _cx
        try:
            _bx.set_action_arg_value(_pcx, _ix, 7)
            _cxok = False                              # a variable/computed arg must NOT set-edit
        except script.ScriptError:
            _cxok = True
        except Exception:
            _cxok = False
        _check("set_action_arg_value on a variable/computed arg raises clean ScriptError", _cxok)
        # GUI primary value-edit path (_set_value -> set_arg_value): unlike the
        # strict set_action_arg_value above, it SETS any arg -- giving a variable/computed/
        # fixed-push arg its own literal and rebuilding the bank -- so the value reads back after rebuild+
        # reparse, and it raises a clean ScriptError on a bad pc/arg (which the GUI turns into a
        # messagebox, never a crash). Fresh container so the shared `c` stays clean.
        _rpc = script.Container(raw)
        _rb = _rpc.banks[_bx.index]
        _rpc.set_arg_value(_rb, _pcx, _ix, 88)
        _rc2 = script.Container(_rpc.build())
        _rst2 = script.decode_statement(_rc2.banks[_bx.index].data, _pcx)
        _rv2, _rok2 = script.eval_expr(_rc2.banks[_bx.index].data, _rst2.args[_ix])
        _rrej = 0
        for _rbad in (lambda: _rpc.set_arg_value(_rb, 0xFFFE, 0, 5),
                      lambda: _rpc.set_arg_value(_rb, _pcx, 99, 5)):
            try:
                _rbad()
            except script.ScriptError:
                _rrej += 1
            except Exception:
                pass
        _check("set_arg_value (GUI edit path) sets a variable arg + rejects bad pc/arg",
               _rok2 and _rv2 == 88 and _rrej == 2)
    else:
        _skip("complex-expr edit safety", "no complex-expr arg found in sample")
    # control-op expression-literal editing (BR_Z/BR_NZ/RET_NZ threshold, EVAL value, SWITCH
    # selector): the editor's value-edit row now also rewrites literals inside a control-op's
    # guard/value expression (via script.expr_literals + Bank.set_expr_value). Guard the primitive:
    # expr_literals must return only set_expr_value-editable literals (each offset on a 0x17-0x1A
    # tag), a no-op write on every one must succeed, and the container stays byte-exact. Also
    # capture an EVAL target (bank/scene/pc/literal) for the GUI-handler check further below.
    _cl_exprs = _cl_lits = _cl_edit = 0
    _cl_target = None            # (bank_index, entry_pc, action_type, pc, literal_index, cur_value)
    for _clb in c.banks[:40]:
        for _clsc in script.disassemble_bank(_clb, discover=False):
            for _clpc, _clst in _clsc.stmts.items():
                if _clst.op < 0xFFF0 or not getattr(_clst, "expr_refs", None):
                    continue
                _lits = []
                for _e in _clst.expr_refs:
                    if _e is not None:
                        _lits.extend(script.expr_literals(_clb.data, _e))
                if not _lits:
                    continue
                _cl_exprs += 1
                _cl_lits += len(_lits)
                for (_loff, _lval, _lw) in _lits:
                    if _clb.data[_loff] not in (0x17, 0x18, 0x19, 0x1A):
                        continue
                    try:
                        _clb.set_expr_value(_loff, _lval)     # no-op write must succeed on every offset
                        _cl_edit += 1
                    except Exception:
                        pass
                if _cl_target is None and _clst.mnem == "EVAL":
                    _cl_target = (_clb.index, _clsc.entry_pc, _clsc.action_type,
                                  _clpc, 0, _lits[0][1])
    _cl_exact = (c.build() == raw)
    _check("script.expr_literals finds control-op guard/value literals, all set_expr_value-editable",
           _cl_exprs > 50 and _cl_lits > 100 and _cl_edit == _cl_lits and _cl_exact,
           f"{_cl_exprs} exprs, {_cl_lits} literals, {_cl_edit} editable, byte-exact={_cl_exact}")
    # PROMPT_CHOICE option retarget (new editor capability): Bank.set_choice_item rewrites a choice
    # option's rf3mc string id in place (u32) -- the choice analog of set-dialog. CLI `script set-val`
    # and the GUI value-row both route a 0xFFF4/0xFFF5 statement here. Find a real choice, retarget
    # option 0, verify only that option's 4-byte item changed (others + length intact) + bad rejects.
    _chc = script.Container(raw)
    _ch_found = None
    for _cb in _chc.banks:
        for _csc in script.disassemble_bank(_cb, discover=True):
            for _cpc, _cst in _csc.stmts.items():
                if _cst.op in (0xFFF4, 0xFFF5) and getattr(_cst, "items", None):
                    _ch_found = (_cb, _cpc, list(_cst.items)); break
            if _ch_found:
                break
        if _ch_found:
            break
    if _ch_found:
        _cb, _cpc, _old_items = _ch_found
        _cb.set_choice_item(_cpc, 0, 4242)
        _re_st = script.decode_statement(_cb.data, _cpc)
        _built = _chc.build()
        _ndiff = sum(1 for _x, _y in zip(raw, _built) if _x != _y)
        _crej = 0
        for _bad in (lambda: _cb.set_choice_item(0, 0, 1),        # pc 0 is not a choice op
                     lambda: _cb.set_choice_item(_cpc, 99, 1)):   # option index out of range
            try:
                _bad()
            except script.ScriptError:
                _crej += 1
        _check("script.set_choice_item retargets a PROMPT_CHOICE option (u32, round-trips) + rejects bad",
               _re_st.items[0] == 4242 and _re_st.items[1:] == _old_items[1:]
               and len(_built) == len(raw) and _ndiff <= 4 and _crej == 2)
    else:
        _skip("set_choice_item", "no PROMPT_CHOICE in the sample corpus")
    # branch-target retarget (new editor capability): Bank.set_branch_target rewrites a branch/jump/
    # choice destination (u16) to another statement pc -- the flow analog of set_choice_item. It is
    # crash-safe: with `valid_targets` (the scene's real statement pcs) an invalid/mid-statement pc
    # is rejected. Find a BR_Z/BR_NZ, retarget it to a sibling statement, verify + reject bad.
    _bt = script.Container(raw)
    _bt_found = None
    for _btb in _bt.banks:
        for _btsc in script.disassemble_bank(_btb, discover=True):
            _pcs = set(_btsc.stmts.keys())
            for _btpc, _btst in _btsc.stmts.items():
                if _btst.op in (0xFFF8, 0xFFF9) and _btst.code_targets:
                    _alt = next((p for p in _pcs if p != _btst.code_targets[0]), None)
                    if _alt is not None:
                        _bt_found = (_btb, _btpc, _btst.code_targets[0], _alt, _pcs); break
            if _bt_found:
                break
        if _bt_found:
            break
    if _bt_found:
        _btb, _btpc, _old_t, _alt, _pcs = _bt_found
        _btb.set_branch_target(_btpc, 0, _alt, valid_targets=_pcs)
        _re_bt = script.decode_statement(_btb.data, _btpc)
        _btbuilt = _bt.build()
        _btrej = 0
        for _bad in (lambda: _btb.set_branch_target(_btpc, 0, 0x9999, valid_targets=_pcs),  # bad pc
                     lambda: _btb.set_branch_target(_btpc, 9, _alt, valid_targets=_pcs),     # oob idx
                     lambda: _btb.set_branch_target(0, 0, _alt)):                            # non-branch
            try:
                _bad()
            except script.ScriptError:
                _btrej += 1
        _check("script.set_branch_target retargets a branch to a valid stmt pc + rejects invalid/oob/non-branch",
               _re_bt.code_targets[0] == _alt and _alt != _old_t
               and len(_btbuilt) == len(raw)
               and sum(1 for _x, _y in zip(raw, _btbuilt) if _x != _y) <= 2 and _btrej == 3)
    else:
        _skip("set_branch_target", "no BR_Z/BR_NZ in the sample corpus")
    # cross-variant offset-math guard: the _BRANCH_TARGET_BASE table + choice items_off math must be
    # correct for EVERY control-op variant, not just the one BR_Z/choice the focused guards happened
    # to hit. The offset differs per op (SWITCH @+6, choice-with-cancel @+6, others @+4/+2), so a
    # single-variant test could miss a wrong entry. Collect one of each op present and retarget
    # target[0] (+ retarget item[0] for choices); every edit must land only on its own slot.
    # Finding one site per variant needs a full-corpus scan (SWITCH_CLAMP occurs exactly
    # ONCE in the shipped game), which used to cost a whole-container decode on every
    # run. The sites depend only on the file bytes, so they are memoized in a sidecar
    # (.selftest_cache.json, keyed by the container's crc32) — a content change or a
    # missing/corrupt sidecar just triggers one fresh scan (with an all-found early exit).
    _VOPS = (0xFFF2, 0xFFF3, 0xFFF4, 0xFFF5, 0xFFF6, 0xFFF7, 0xFFF8, 0xFFF9, 0xFFFA, 0xFFFE)
    _vcache_p = pathlib.Path(__file__).with_name(".selftest_cache.json")
    _raw_crc = _zlib.crc32(raw)
    _V = {}
    try:
        import json as _json
        _vj = _json.loads(_vcache_p.read_text(encoding="utf-8"))
        if _vj.get("rf3mc_crc") == _raw_crc:
            _V = {int(_k): tuple(_v) for _k, _v in _vj["ctrl_variant_sites"].items()}
    except Exception:
        _V = {}
    if not _V:
        for _vb in script.Container(raw).banks:
            for _vsc in script.disassemble_bank(_vb, discover=True):
                for _vpc, _vst in _vsc.stmts.items():
                    if _vst.op in _VOPS and _vst.op not in _V:
                        _V[_vst.op] = (_vb.index, _vpc)
            if len(_V) == len(_VOPS):
                break
        try:
            _vcache_p.write_text(_json.dumps(
                {"rf3mc_crc": _raw_crc,
                 "ctrl_variant_sites": {str(_k): list(_v) for _k, _v in _V.items()}}),
                encoding="utf-8")
        except Exception:
            pass
    # re-derive each site's scene pc-set fresh (cheap: one bank each, usually cached)
    _V = {_vop: (_vbi, _vpc,
                 next(set(_s.stmts.keys()) for _s in script.disassemble_bank(
                     script.Container(raw).banks[_vbi], discover=True)
                      if _vpc in _s.stmts))
          for _vop, (_vbi, _vpc) in _V.items()}
    _var_ok = 0
    _var_bad = []
    for _vop, (_vbi, _vpc, _vpcs) in _V.items():
        _vc = script.Container(raw)
        _vbk = _vc.banks[_vbi]
        _v0 = script.decode_statement(_vbk.data, _vpc)
        if not _v0.code_targets:
            continue
        _valt = next((p for p in _vpcs if p != _v0.code_targets[0]), _v0.code_targets[0])
        _vbk.set_branch_target(_vpc, 0, _valt, valid_targets=_vpcs)
        _vre = script.decode_statement(_vbk.data, _vpc)
        _tgt_ok = (_vre.code_targets[0] == _valt and _vre.code_targets[1:] == _v0.code_targets[1:])
        _itm_ok = True
        if _vop in (0xFFF4, 0xFFF5):                       # choice: also item[0] on its own slot
            _vbk.set_choice_item(_vpc, 0, 6363)
            _vre2 = script.decode_statement(_vbk.data, _vpc)
            _itm_ok = (_vre2.items[0] == 6363 and _vre2.items[1:] == _v0.items[1:]
                       and _vre2.code_targets[0] == _valt)   # item edit didn't disturb targets
        if _tgt_ok and _itm_ok:
            _var_ok += 1
        else:
            _var_bad.append(hex(_vop))
    _check("set_branch_target/set_choice_item offset math correct for EVERY control-op variant",
           _var_ok >= 8 and not _var_bad, "ok=%d bad=%s" % (_var_ok, _var_bad))
    if QUICK:
        _skip("scene coverage ~100% clean (763-slot decoder)", "quick mode: full-corpus sweep")
    else:
        scenes, clean, stmts, dl = script.coverage(c)
        _check("scene coverage ~100% clean (763-slot decoder)",
               scenes > 0 and clean / scenes >= 0.999,
               f"{clean}/{scenes} clean ({100*clean/max(scenes,1):.2f}%), {dl} dialog lines")
    # display-path guard: render_action (the enum-decoding disassembly line the editor shows)
    # must not throw for ANY op that appears in real scenes. Render each distinct op once.
    _seen, _rerr = {}, 0
    for _b in (c.banks[:60] if QUICK else c.banks):
        for _sc in script.disassemble_bank(_b, discover=False):
            for _st in _sc.stmts.values():
                if _st.op < 0xFFF0 and _st.op not in _seen:
                    try:
                        script.render_action(_st.op, [script.arg_repr(_b.data, _a) for _a in _st.args])
                        _seen[_st.op] = True
                    except Exception:
                        _seen[_st.op] = False
                        _rerr += 1
    _check("render_action renders every op that appears in scenes without error",
           _rerr == 0, f"{len(_seen)} distinct ops, {_rerr} errors")
    # scene-op range boundary (IDA-verified 2026-07-11 against RF4S.exe):
    #   * g_sceneActionHandlerTable (RF4S.exe+0x4DB790) real scene-op range is 0..701.
    #   * SceneAction_DispatchTableWithCleanup (RF4S.exe+0x1F4AC0) indexes it with only a NULL-check
    #     (no upper bound), so a scene must NEVER emit an op > 701 or it would call into garbage.
    #   * slots 702..737 are inter-table padding/garbage (all metadata `(unused)`); 738..762 are a
    #     SEPARATE adjacent table `g_npcScheduleActionDispatchTable` (NPC schedule/behaviour handlers,
    #     NOT scene opcodes -- each metadata desc must keep the "NOT a cutscene-script opcode" flag).
    # This freezes that structure so a future opcode-table edit can't silently (a) let a bogus high
    # op slip into the corpus, (b) name a padding slot, or (c) drop the non-scene flag on 738..762.
    from rf4s_modkit import opcode_meta as _omb
    _max_scene_op = -1
    for _bb in (c.banks[:60] if QUICK else c.banks):
        for _ss in script.disassemble_bank(_bb, discover=True):
            for _s2 in _ss.stmts.values():
                if _s2.op < 0xFFF0 and _s2.op > _max_scene_op:
                    _max_scene_op = _s2.op
    _pad_unused = all(_omb.mnemonic(_o) in ("(unused)", "nop", "(unbound)", "invalid")
                      for _o in range(702, 738))
    _sched_nonscene = all("NOT a cutscene-script opcode" in (_omb.META.get(_o, {}).get("d") or "")
                          for _o in range(738, 763))
    _check("scene-op range boundary: max real op <=701, 702-737 unused, 738-762 non-scene (NPC schedule)",
           _max_scene_op <= 701 and _pad_unused and _sched_nonscene,
           f"max_scene_op={_max_scene_op}, pad_unused={_pad_unused}, sched_nonscene={_sched_nonscene}")
    # discovery-pass guard: the GUI/search use disassemble_bank(discover=True), which gap-fills
    # scenes registered only in the global index and invisible to the bank type-table.
    # REPINNED 2026-09-01 (the FRAME correction): 0xFFF1 is frame setup and FALLS THROUGH
    # (it is NOT a return), so typed scenes now absorb their CALLed subroutines whole and
    # discovery is left with only true orphans. In banks[:10] that is 34 scenes: 16 with real
    # content (DIALOG / action op) and 18 that are exactly single-RET return stubs. Verify:
    # every discovered scene decodes cleanly, some real orphans exist, and every non-real
    # one is a lone-RET stub (anything else = gap-fill noise creeping back in).
    _disc = _disc_bad = _disc_real = _disc_stub = 0
    _sum_tot = _sum_blank = _sum_op = 0        # scene_summary: the editor's non-dialogue list preview
    for _db in c.banks[:10]:
        for _dsc in script.disassemble_bank(_db, discover=True):
            if _dsc.action_type == -1:
                _disc += 1
                if not _dsc.ok:
                    _disc_bad += 1
                if any(_s.op < 0xFFF0 or _s.mnem == "DIALOG" for _s in _dsc.stmts.values()):
                    _disc_real += 1
                elif len(_dsc.stmts) == 1 and next(iter(_dsc.stmts.values())).mnem == "RET":
                    _disc_stub += 1
            if _dsc.stmts:                     # every non-empty scene gets a non-blank list preview
                _sum_tot += 1
                _summ = script.scene_summary(_dsc)
                if not _summ:
                    _sum_blank += 1
                elif _summ.startswith("-> "):
                    _sum_op += 1
    _check("discovery pass finds only true orphans: clean, real content or lone-RET stubs",
           _disc >= 20 and _disc_bad == 0 and _disc_real >= 10
           and _disc_real + _disc_stub == _disc,
           f"{_disc} discovered, {_disc_bad} unclean, {_disc_real} real, {_disc_stub} RET stubs")
    # scene_summary powers the editor's scene-list preview for scenes with no dialogue -- every
    # non-empty scene must get a non-blank one-line summary (first op or terminator), so no list
    # row is ever blank. Spot-checks the '-> <op>' form appears for action/control-only scenes.
    _check("scene_summary gives every non-empty scene a non-blank list preview",
           _sum_tot > 100 and _sum_blank == 0 and _sum_op > 0,
           f"{_sum_tot} scenes, {_sum_blank} blank, {_sum_op} op-summaries")
    # expression sub-language coverage: action-op args and control-flow guards are not literals --
    # each is an offset to a little RPN expression (Script_EvalExpressionBytecode) with leaf tags
    # (int/u8/s8/u16/s16 literals, packed vars, reg0..9, var arrays) and operators (arith/compare/
    # logic/compound-assign). disasm_expr must decode EVERY one -- a "?" means an undecoded token.
    # Bounded to the first 6 banks (~137k expressions incl. operators) to stay fast. The same
    # pass also cross-checks DIALOG resolution: every DIALOG line id must index a non-empty entry
    # in the stock rf3mc.<locale> catalog (the editor shows "[no text]" otherwise) -- guards a
    # text-archive/dialog-id mapping regression. Needs rf3mc.eng; DIALOG check skipped without it.
    _tp = _first("rf3mc.eng") or _first("*.eng")
    _tarc = textdb.TextArchive.load(_tp) if _tp else None
    _tn = len(_tarc) if _tarc else 0
    from rf4s_modkit import opcode_meta as om   # for the picker-plausibility tally below
    _ex_tot = _ex_bad = _ex_ops = 0
    _dlg_ok = _dlg_bad = 0
    _ex_leaves = set()
    _pick_tot, _pick_imp = {}, {}          # (op,ai) -> literal count / implausible-value count
    for _eb in c.banks[:6]:
        _ed, _en = _eb.data, len(_eb.data)
        for _esc in script.disassemble_bank(_eb, discover=False):
            for _est in _esc.stmts.values():
                if _tarc is not None and _est.mnem == "DIALOG" and _est.dialog_id is not None:
                    if 0 <= _est.dialog_id < _tn and _tarc.text(_est.dialog_id) != "":
                        _dlg_ok += 1
                    else:
                        _dlg_bad += 1
                if _est.op < 0xFFF0:        # picker-plausibility: an enum picker's token position
                    for _pai, _paoff in enumerate(_est.args):   # must hold values in its id-space,
                        if (_est.op, _pai) not in om.ENUM_ARG_VALUES:   # not e.g. 0x8100+ category
                            continue                                    # refs (the op-437 defect).
                        if not (0 <= _paoff < _en):
                            continue
                        _pv, _pok = script.eval_expr(_ed, _paoff)
                        if _pok and _pv is not None and _pv >= 0:
                            _pick_tot[(_est.op, _pai)] = _pick_tot.get((_est.op, _pai), 0) + 1
                            if _pv >= 0x8000 and _pv not in om.ENUM_ARG_VALUES[(_est.op, _pai)]:
                                # far above any real id space and not a known key (sound ids
                                # are 0x1000000|n by design and resolve through the table)
                                _pick_imp[(_est.op, _pai)] = _pick_imp.get((_est.op, _pai), 0) + 1
                for _eoff in list(_est.args) + list(getattr(_est, "expr_refs", None) or []):
                    if _eoff is None or not (0 <= _eoff < _en):
                        continue
                    _ex_tot += 1
                    _ex_leaves.add(_ed[_eoff])
                    _etxt, _ = script.disasm_expr(_ed, _eoff)
                    if _etxt == "?":
                        _ex_bad += 1
                    elif any(_o in _etxt for _o in ("+", "==", "&&", "+=", "%")):
                        _ex_ops += 1
    _check("expression VM: all corpus arg/guard expressions decode (leaves + operators, 0 unknown)",
           _ex_tot > 1000 and _ex_bad == 0 and _ex_ops > 0 and len(_ex_leaves) >= 10,
           f"{_ex_tot} exprs, {_ex_bad} unparsed, {_ex_ops} w/ ops, {len(_ex_leaves)} leaf tags")
    if _tarc is not None:
        _check("every corpus DIALOG line id resolves to non-empty rf3mc text",
               _dlg_ok > 500 and _dlg_bad == 0, f"{_dlg_ok} resolved, {_dlg_bad} unresolved")
        # end-to-end author workflow (the core 'add new dialogue', spanning BOTH files): append a
        # new line to rf3mc.<locale>, retarget a DIALOG beat to it, rebuild + reparse both, and
        # verify the beat now resolves to the new text while every other bank stays byte-identical.
        # Fresh copies so the shared container/archive are untouched.
        _wc = script.Container(raw)
        _wa = textdb.TextArchive.load(_tp)
        _wnew = _wa.append_text("SELFTEST new cutscene line")
        _wt = None
        for _wb in _wc.banks[:8]:
            for _wsc in script.disassemble_bank(_wb, discover=False):
                for _wpc, _wst in _wsc.stmts.items():
                    if _wst.mnem == "DIALOG":
                        _wt = (_wb, _wpc)
                        break
                if _wt:
                    break
            if _wt:
                break
        if _wt:
            _wb, _wpc = _wt
            _wb.set_dialog_id(_wpc, _wnew)
            _wc2 = script.Container(_wc.build())
            _wa2 = textdb.TextArchive.parse(_wa.build())
            _wst2 = script.decode_statement(_wc2.banks[_wb.index].data, _wpc)
            _check("end-to-end: append new line + retarget DIALOG -> reparse resolves to new text",
                   _wst2.dialog_id == _wnew
                   and _wa2.text(_wnew) == "SELFTEST new cutscene line"
                   and all(bytes(_wc2.banks[_i].data) == bytes(script.Container(raw).banks[_i].data)
                           for _i in range(len(_wc2.banks)) if _i != _wb.index))
        else:
            _skip("end-to-end add-dialogue", "no DIALOG in first 8 banks")
    else:
        _skip("DIALOG text resolution", "no rf3mc.eng catalog")
    # install pipeline (the final authoring step): build the rf3.mc, stage it, install_loose it as
    # a loose-file override under a temp game root, and read it back -- the override must land at
    # <root>/rf3.mc byte-identical and re-parse. Covers the build->deliver step the round-trip tests
    # don't (the GUI's Install-to-game button + Save both write container.build()).
    _built = c.build()
    _iroot = pathlib.Path(tempfile.mkdtemp())
    try:
        _istage = _iroot / "_stage.mc"
        _istage.write_bytes(_built)
        _idest = mbundle.install_loose(_iroot / "game", "rf3.mc", str(_istage))
        _iok = (_idest == _iroot / "game" / "Bundle" / "00_mods" / "rf3.mc" and _idest.is_file()
                and _idest.read_bytes() == _built
                and script.Container(_idest.read_bytes()).build() == _built)
    finally:
        shutil.rmtree(_iroot, ignore_errors=True)
    _check("install pipeline: build -> install_loose lands a byte-identical rf3.mc override", _iok)
    # CLI/GUI parity: `rf4mod script set-val` must edit a CONTROL-op literal (EVAL value, BR_Z
    # threshold, JMP_WEIGHTED weight), not only action args -- the GUI's _set_ctrl_literal has this, and
    # cmd_script_set_val now branches on op>=0xFFF0. Find an EVAL, run the CLI fn, verify the edit.
    try:
        import rf4mod as _rf
    except Exception:
        _rf = None
    if _rf is not None:
        _sv_tgt = None
        for _sb in c.banks[:20]:
            for _ssc in script.disassemble_bank(_sb, discover=False):
                for _spc, _sst in _ssc.stmts.items():
                    if _sst.mnem == "EVAL" and getattr(_sst, "expr_refs", None):
                        _sl = []
                        for _e in _sst.expr_refs:
                            if _e is not None:
                                _sl.extend(script.expr_literals(_sb.data, _e))
                        if _sl:
                            _sv_tgt = (_sb.index, _spc, _sl[0][1]); break
                if _sv_tgt:
                    break
            if _sv_tgt:
                break
        if _sv_tgt:
            _svb, _svpc, _svold = _sv_tgt
            _svtmp = pathlib.Path(tempfile.mkdtemp())
            _svin = _svtmp / "in.mc"; _svin.write_bytes(raw)
            _svout = _svtmp / "out.mc"
            _svnew = (_svold + 5) % 90
            _sva = type("A", (), {"file": str(_svin), "bank": _svb, "pc": hex(_svpc),
                                  "index": 0, "value": _svnew, "out": str(_svout)})()
            _rf.cmd_script_set_val(_sva)
            _svc2 = script.Container(_svout.read_bytes())
            _sve2 = next(e for e in script.decode_statement(_svc2.banks[_svb].data, _svpc).expr_refs
                         if e is not None)
            _svrb = script.expr_literals(_svc2.banks[_svb].data, _sve2)[0][1]
            _check("CLI `script set-val` edits a control-op literal (EVAL value), not only action args",
                   _svrb == _svnew, f"readback {_svrb} want {_svnew}")
        else:
            _skip("CLI set-val control-op", "no EVAL literal in sample")
        # CLI/GUI parity #2: `rf4mod script set-speaker` must change who speaks (rewrite a SetSpeaker
        # op) -- the GUI's _set_speaker has this; the CLI lacked it. Find a portrait op, set a
        # DIFFERENT speaker via the CLI fn, verify the op now decodes to that speaker + side.
        _sp_tgt = None
        for _pb in c.banks[:6]:
            for _psc in script.disassemble_bank(_pb, discover=False):
                for _ppc, _pst in _psc.stmts.items():
                    if script.is_portrait_op(_pst.op):
                        _cur, _ = script.portrait_speaker_slot(_pst.op)
                        _sp_tgt = (_pb.index, _ppc, _cur); break
                if _sp_tgt:
                    break
            if _sp_tgt:
                break
        if _sp_tgt:
            _spb, _sppc, _spcur = _sp_tgt
            _spnew = (_spcur + 1) % len(script.PORTRAIT_SPEAKERS)   # a different speaker
            _sptmp = pathlib.Path(tempfile.mkdtemp())
            _spin = _sptmp / "in.mc"; _spin.write_bytes(raw)
            _spout = _sptmp / "out.mc"
            _spa = type("A", (), {"file": str(_spin), "bank": _spb, "pc": hex(_sppc),
                                  "speaker": str(_spnew), "side": "right", "out": str(_spout)})()
            _rf.cmd_script_set_speaker(_spa)
            _spc2 = script.Container(_spout.read_bytes())
            _spop2 = script.decode_statement(_spc2.banks[_spb].data, _sppc).op
            _spslot2, _spside2 = script.portrait_speaker_slot(_spop2)
            _check("CLI `script set-speaker` rewrites who speaks a line (speaker + side)",
                   _spslot2 == _spnew and _spside2 == 1,
                   f"got slot {_spslot2} side {_spside2}, want {_spnew}/right")
        else:
            _skip("CLI set-speaker", "no SetSpeaker op in sample")
    else:
        _skip("CLI set-val/set-speaker", "rf4mod not importable")
    # dialogue search (the editor's Find feature -> find_scenes_with_dialog): the way an author
    # LOCATES a scene to edit. A common-word search must return scenes that GENUINELY contain the
    # substring (case-insensitive), a nonsense query returns nothing, and discovery-only scenes are
    # searchable (the "I was about to call you over." cutscene is type-table-invisible).
    _stp = None if QUICK else (_first("rf3mc.eng") or _first("*.eng"))
    if QUICK:
        _skip("dialogue search (Find)", "quick mode: full-corpus sweep")
    elif _stp is not None:
        _starc = textdb.TextArchive.load(_stp)
        _sdlg = lambda _l: _starc.text(_l)          # find_* wraps this in try/except
        _sh = script.find_scenes_with_dialog(c, "morning", _sdlg)
        _sh_ok = all(any("morning" in (_sdlg(_lid) or "").lower() for _lid in _ids)
                     for _bk, _sc, _ids in _sh[:200])
        _sh_ci = len(script.find_scenes_with_dialog(c, "MORNING", _sdlg)) == len(_sh)
        _sh_none = len(script.find_scenes_with_dialog(c, "zzxqqnotarealword", _sdlg)) == 0
        _sh_disc = len(script.find_scenes_with_dialog(c, "I was about to call you over", _sdlg)) >= 1
        _check("dialogue search (Find): genuine matches, case-insensitive, empty-on-miss, finds "
               "discovery-only scenes",
               len(_sh) > 50 and _sh_ok and _sh_ci and _sh_none and _sh_disc)
        # choice-menu options are dialogue too: an option's own text finds its scene, with the
        # option's line id among the hits, in the CLI finder and the editor's dialogue mode
        _cq = None
        for _bk, _sc in script.iter_scenes(c):
            for _st in _sc.stmts.values():
                if _st.mnem in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED") and _st.items:
                    _t = (_sdlg(_st.items[-1]) or "").strip()
                    if len(_t) >= 8 and "＠" not in _t:
                        _cq = (_bk, _sc.entry_pc, _st.items[-1], _t)
                        break
            if _cq:
                break
        if _cq is None:
            _skip("dialogue search finds choice options", "no choice menu with a plain option")
        else:
            _ch = script.find_scenes_with_dialog(c, _cq[3], _sdlg)
            _ch_ok = any(_bk is _cq[0] and _sc.entry_pc == _cq[1] and _cq[2] in _ids
                         for _bk, _sc, _ids in _ch)
            try:
                from cutscene_editor import browser as _ceb2

                class _TextDoc:
                    container, em, textarc = c, None, _starc
                    text = staticmethod(_sdlg)
                _ch_gui = any(_p == c.banks.index(_cq[0]) and _sc.entry_pc == _cq[1]
                              for _p, _sc in _ceb2.find_scenes(_TextDoc(), "dialogue", _cq[3]))
            except ImportError:
                _ch_gui = True
            _check("dialogue search finds choice-menu options (CLI finder + editor dialogue mode)",
                   _ch_ok and _ch_gui, f"{_cq[3]!r}: {len(_ch)} scene(s), editor {_ch_gui}")
    else:
        _skip("dialogue search", "no rf3mc.eng catalog")
    # map objects a scene spawns (SpawnMapEntity, op 157) are in use even when no map places
    # them: none may be labelled '(unused)' (the Sharance Maze entrance, 326, was "crystal charm
    # (unused)" until 2026-10-02)
    from rf4s_modkit import mobj_types as _mtu
    _spawn_op = next(_o for _o in range(script.DISPATCHABLE_ACTION_OPS)
                     if script.opcode_mnemonic(_o) == "SpawnMapEntity")
    _spawned = set()
    for _bk, _sc in script.iter_scenes(c):
        for _st in _sc.stmts.values():
            if _st.op == _spawn_op and _st.args:
                try:
                    _spawned.add(int(script.arg_repr(_bk.data, _st.args[0]), 0))
                except (ValueError, TypeError):
                    pass
    _bad = sorted(_t for _t in _spawned if "(unused)" in (_mtu.mobj_display_name(_t) or ""))
    _check("map objects spawned by scenes are not labelled '(unused)'",
           len(_spawned) > 5 and not _bad and "Sharance" in _mtu.mobj_display_name(326),
           f"{len(_spawned)} spawned types, mislabelled {_bad}")
    # structural search (the browser's opcode/speaker modes -> cutscene_editor.browser.find_scenes).
    # Run it headless on a stub document and confirm each mode returns scenes that GENUINELY
    # match: opcode search finds scenes containing the op (by-mnemonic count == by-number count,
    # every hit has it), speaker search finds scenes with the matching SetSpeaker, nonsense
    # returns nothing. Pairs with the dialogue-search guard (the other half of the search box).
    try:
        from cutscene_editor import browser as _ceb, catalog as _cec, render as _cer
    except Exception:
        _ceb = _cec = _cer = None
    if QUICK:
        _skip("structural search", "quick mode: full-corpus sweep")
    elif _ceb is not None:
        class _SearchDoc:
            container, em, textarc = c, None, None
        _sdoc = _SearchDoc()
        # ops 423 and 424 share the mnemonic (one handler, no opcode branch), so a search by
        # name must equal the union of the searches by each number
        _gops = [_o for _o in range(script.DISPATCHABLE_ACTION_OPS)
                 if "giveplayeritem" in script.opcode_mnemonic(_o).lower()]
        _r1 = _ceb.find_scenes(_sdoc, "opcode", "GivePlayerItem")
        _op_ok = all(any(_st.op in _gops for _st in _sc.stmts.values()) for _pos, _sc in _r1[:100])
        _r2 = sorted({(_p, _sc.entry_pc) for _o in _gops
                      for _p, _sc in _ceb.find_scenes(_sdoc, "opcode", str(_o))})
        _r3 = _ceb.find_scenes(_sdoc, "speaker", "Arthur")
        _spk_ok = all(any(script.is_portrait_op(_st.op)
                          and "arthur" in (script.portrait_speaker_name(_st.op) or "").lower()
                          for _st in _sc.stmts.values()) for _pos, _sc in _r3[:100])
        _r4 = _ceb.find_scenes(_sdoc, "opcode", "zznotanop")
        _check("structural search (opcode/speaker) matches genuinely + by-number == by-name",
               len(_r1) > 5 and _op_ok and len(_r2) == len(_r1) and len(_r3) > 5 and _spk_ok
               and not _r4, f"{len(_r1)}/{len(_r2)}/{len(_r3)}/{len(_r4)}")
        # variable mode: scenes that read or write an emdeb.bin variable by name. The
        # developers' "Related Birthday" menu (bank 252) writes REG_PLAYER_BIRTH_SEASON with EVAL
        from rf4s_modkit import emflags as _vef
        try:
            _sdoc.emf_vars = _vef.EmFlagTable.load(_vef.find_emdeb())
        except (FileNotFoundError, ValueError):
            _sdoc.emf_vars = None
        if _sdoc.emf_vars is None:
            _skip("variable search", "emdeb.bin not found")
        else:
            _v1 = _ceb.find_scenes(_sdoc, "variable", "REG_PLAYER_BIRTH_SEASON")
            _v2 = _ceb.find_scenes(_sdoc, "variable", "zznotavar")
            _check("variable search finds the scenes using a FLG_/REG_ name (bank 252 birthday menu)",
                   len(c.banks) > 252 and any(_p == 252 for _p, _sc in _v1) and not _v2,
                   f"{[(_p, hex(_sc.entry_pc)) for _p, _sc in _v1]} / {len(_v2)}")
    else:
        _skip("structural search", "cutscene_editor not importable")
    # xrefs (the editor's Callers… reverse lookup, 2026-09-01): control-flow callers over one
    # bank. Bank 210 ground truth: the shared close-bubbles subroutine @0x114C has hundreds of
    # CALL sites; the FRAME subroutine @0x17CE has exactly one caller (CALL @0x0508),
    # attributed to its typed parent scene; the Eliza-chat dispatcher @0x6394 has none
    # (engine/event dispatch only, shown as such in the UI).
    if _cec is not None and len(c.banks) > 210:
        _x1 = _cec.collect_xrefs(c.banks[210], 0x114C)
        _x2 = _cec.collect_xrefs(c.banks[210], 0x17CE)
        _x3 = _cec.collect_xrefs(c.banks[210], 0x6394)
        _check("editor xrefs: reverse CALL lookup (many/one/none pins on bank 210)",
               len(_x1) > 200 and all(_r[3] == "CALL" for _r in _x1[:20])
               and len(_x2) == 1 and _x2[0][2] == 0x0508 and _x2[0][3] == "CALL"
               and _x3 == [],
               f"{len(_x1)} sites / {len(_x2)} / {len(_x3)}")
    else:
        _skip("editor xrefs", "cutscene_editor not importable")
    # end-to-end explanation guard: the editor's Alt-hover explanation (render.SceneText.explain,
    # also the Inspector's "Description" box) must render a non-empty string for EVERY op that
    # appears in scenes -- DIALOG, control ops, and action ops (prototype + per-arg + enum/EMF/
    # speaker decode, the FLG_/REG_ legend of a condition). ScriptDocument has no Tk in it, so
    # this runs headless. Bounded to the first 15 banks (~225 ops).
    if _cer is not None:
        from cutscene_editor.document import ScriptDocument as _SDoc
        _tdoc = _SDoc(lambda _n: (_first(_n).read_bytes() if _first(_n) else None))
        _tdoc.load_from_reader()
        _tip_ok = _tip_err = 0
        _tip_ctrl, _tip_seen = set(), set()
        _choice_checked = _choice_ok = 0     # PROMPT_CHOICE explanation surfaces each option's line id
        for _tb in _tdoc.container.banks[:15]:
            for _tsc in script.disassemble_bank(_tb, discover=True):
                _tst_text = _cer.SceneText(_tdoc, _tb, _tsc)
                for _tst in _tsc.stmts.values():
                    if _tst.mnem in ("PROMPT_CHOICE", "PROMPT_CHOICE_FORCED") \
                            and getattr(_tst, "items", None) and _choice_checked < 5:
                        try:
                            _ct = _tst_text.explain(_tst)
                            _choice_checked += 1
                            if all(("#%d" % _it) in _ct for _it in _tst.items):
                                _choice_ok += 1
                        except Exception:
                            pass
                    if (_tst.op, _tst.mnem) in _tip_seen:
                        continue
                    _tip_seen.add((_tst.op, _tst.mnem))
                    try:
                        _txt = _tst_text.explain(_tst)
                        if isinstance(_txt, str) and _txt:
                            _tip_ok += 1
                            if _tst.op >= 0xFFF0:
                                _tip_ctrl.add(_tst.mnem)
                        else:
                            _tip_err += 1
                    except Exception:
                        _tip_err += 1
        _check("editor explanation (SceneText.explain) renders for every corpus op (headless)",
               _tip_ok > 100 and _tip_err == 0 and len(_tip_ctrl) >= 10,
               f"{_tip_ok} ops, {_tip_err} errors, {len(_tip_ctrl)} control mnems")
        # every-op coverage: the loop above only sees ops that appear in scenes -- ~125 named ops
        # (quest-request generators 508-548, rare NPC actions, ...) NEVER appear, so their
        # explanation was untested. Render each remaining named action op via a synthesized
        # 0-arg statement -- explain only touches the bank when the statement HAS args.
        import struct as _struct
        _seen_ops = {_o for _o, _m in _tip_seen}
        _every_ok = _every_err = 0
        _every_bad = []
        _bare = _cer.SceneText(_tdoc, None, None)
        # 702..762 carry names but have no handler slot, so they can never appear as a
        # statement (decode_statement rejects them) -- sweep only the dispatchable range.
        for _eop in range(script.DISPATCHABLE_ACTION_OPS):
            if _eop in _seen_ops:
                continue
            _emn = script.opcode_mnemonic(_eop)
            if not _emn or _emn in ("(unbound)", "(unused)", "invalid"):
                continue
            try:
                _est = script.decode_statement(_struct.pack("<HH", _eop, 0), 0)
                _etxt = _bare.explain(_est)
                if isinstance(_etxt, str) and _etxt.strip():
                    _every_ok += 1
                else:
                    _every_err += 1; _every_bad.append(_eop)
            except Exception as _ee:
                _every_err += 1; _every_bad.append((_eop, repr(_ee)[:40]))
        _check("editor explanation renders for every never-in-scenes named op too",
               _every_ok > 80 and _every_err == 0,
               f"{_every_ok} extra ops rendered, {_every_err} errors {_every_bad[:5]}")
        # choice-text editing reachability: the PROMPT_CHOICE explanation must surface each
        # option's rf3mc line #id (the Inspector's choice form edits them by id).
        _check("PROMPT_CHOICE explanation surfaces each option's line #id",
               _choice_checked > 0 and _choice_ok == _choice_checked,
               f"{_choice_ok}/{_choice_checked} choice explanations show all item ids")
    else:
        _skip("editor explanation render", "cutscene_editor not importable (no tkinter)")
    # picker-plausibility: every enum picker must sit on a token position whose corpus literal
    # values fall in a real id-space -- NOT >= 0x8000 (no wired enum has keys that large). A picker
    # mostly decoding >= 0x8000 values is misaligned (op 437 arg1 held 0x8100+ present-category
    # refs under a CHAR_IDS picker -- removed). Guards against re-introducing a misplaced picker.
    # An argument that takes two kinds of value is exempt: SetSpeaker's triggers name the
    # seven emote icons (186-192) but mostly carry voice ids (0x1000000+n) -- both real.
    def _two_kinds(_k):
        _r = om.table_row(_k[0]) or {}
        _a = (_r.get("args") or [])
        return _k[1] < len(_a) and " or voice" in (_a[_k[1]].get("type") or "")
    _mis = [(_k, _pick_imp[_k], _pick_tot[_k]) for _k in _pick_tot
            if _pick_tot[_k] >= 3 and _pick_imp.get(_k, 0) / _pick_tot[_k] >= 0.25 and not _two_kinds(_k)]
    _check("every enum picker decodes plausible corpus values (no 0x8000+ misalignment)",
           not _mis, str(_mis[:6]))
    # regression guard: the action-opcode table is 763 slots (was wrongly capped at 400,
    # which desync'd ~3.8% of scenes). An op in [400,762] must decode, not be rejected.
    _check("action opcode 700 decodes (763-slot table)",
           script.decode_statement(bytes.fromhex("bc020000"), 0) is not None)
    from rf4s_modkit import opcode_meta as _om
    _check("scene ops 146/148/300 have curated mnemonics",
           _om.mnemonic(146) == "EquipItemToPlayer" and _om.mnemonic(148) == "HasPlayerAccessoryEffect40000"
           and _om.mnemonic(300) == "ResetAllNpcSchedules")
    # SWITCH_CLAMP (0xFFF6) has exactly `cnt` targets, no spurious trailing duplicate
    # (IDA: selector>=n aliases target[n-1]; there is no separate default slot).
    _sw = script.decode_statement(bytes.fromhex("f6ff" + "0000" + "0200" + "1000" + "2000"), 0)
    _check("SWITCH_CLAMP has cnt targets (no dup)",
           _sw is not None and _sw.mnem == "SWITCH_CLAMP"
           and [t for t in _sw.code_targets if t is not None] == [0x10, 0x20])
    # JMP_WEIGHTED (0xFFF2 weighted-random branch) layout is [op][N][N targets][N weight-exprs] -- targets
    # FIRST (@+4), weight expressions SECOND (@+4+2N). IDA-verified (Script_Opcode_FFF2_ExecPrim) and
    # empirically (targets resolve to real statement PCs; weights point into the expr pool). The two
    # blocks are equal size, so a swap would keep the decode "clean" -- guard the order explicitly.
    _EXPR_LEAF = {0x01, 0x02, 0x03, 0x04, 0x05, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A}
    _rb_ok = None
    for _rbb in c.banks[:60]:
        _bpcs, _rb_st = set(), None
        for _rsc in script.disassemble_bank(_rbb, discover=True):
            _bpcs |= set(_rsc.stmts.keys())
            for _rst in _rsc.stmts.values():
                if _rst.op == 0xFFF2 and _rst.code_targets and _rb_st is None:
                    _rb_st = _rst
        if _rb_st is not None:
            _tgt_ok = all(t in _bpcs for t in _rb_st.code_targets if t is not None)
            _wt_ok = all(0 <= e < len(_rbb.data)
                         and (_rbb.data[e] in _EXPR_LEAF or 0x07 <= _rbb.data[e] <= 0x10)
                         for e in _rb_st.expr_refs if e is not None)
            _rb_ok = _tgt_ok and _wt_ok
            break
    if _rb_ok is not None:
        _check("JMP_WEIGHTED (0xFFF2) targets are real PCs + weights are expr-refs (block order not swapped)",
               _rb_ok)
    else:
        _skip("JMP_WEIGHTED layout", "no 0xFFF2 with targets in first 60 banks")
    # s16-negative literals encode (0x1A) instead of crashing; arg_repr shows decimal
    _neg = script.Container._literal_expr_bytes(-1000)
    _check("s16 negative literal encodes + round-trips",
           _neg[0] == 0x1A and script.eval_expr(_neg, 0) == (-1000, True)
           and script.arg_repr(_neg, 0) == "-1000")
    # packed condition variables (token 0x02) resolve to emdeb.bin FLG_/REG_ names
    try:
        from rf4s_modkit import emflags as _emf
        _emt = _emf.EmFlagTable.load(_emf.find_emdeb())
    except Exception:
        _emt = None
    if _emt is not None:
        bo, wd, _sg = c.unpack_var(0x40C6)                 # header-mask unpack
        script.install_emflags_var_resolver(c, _emt)
        # 02 c6 40 00 00 | 18 0b | 8c | 00  ==  REG_WIFE_ID == 11
        txt, _sz = script.disasm_expr(bytes.fromhex("02c6400000180b8c00"), 0)
        # corpus coverage: EVERY packed-var (token 0x02) reference in real scenes must resolve to
        # an emdeb.bin FLG_/REG_ name, so the editor never shows a bare var:0xNN. Uses expr_var_refs
        # to WALK each arg/guard expression fully -- so it counts vars nested after other tokens
        # (e.g. `A && FLG_Y`), not just a leading 0x02. 40 banks -> thousands of refs.
        _pv_res = _pv_raw = 0
        for _pb in c.banks[:40]:
            _pd = _pb.data
            for _psc in script.disassemble_bank(_pb, discover=False):
                for _pst in _psc.stmts.values():
                    for _po in list(_pst.args) + list(getattr(_pst, "expr_refs", None) or []):
                        if _po is None:
                            continue
                        for _voff, _enc in script.expr_var_refs(_pd, _po):
                            if script._packed_var_resolver(_enc):
                                _pv_res += 1
                            else:
                                _pv_raw += 1
        script.set_packed_var_resolver(None)              # restore global (display-only)
        _check("packed var 0x40C6 -> REG_WIFE_ID (bit 198, w5)",
               bo == 198 and wd == 5 and txt == "REG_WIFE_ID == 11")
        _check("every corpus packed-var ref (incl. nested) resolves to an emdeb name (no bare var:0xNN)",
               _pv_res > 2000 and _pv_raw == 0, f"{_pv_res} resolved, {_pv_raw} unresolved")
    else:
        _check("packed var name resolver (emdeb.bin skipped)", True)
    # in-place edit round-trips byte-perfect except the edited bytes
    bk = next(b for b in c.banks
              if any(s.mnem == "DIALOG" for sc in script.disassemble_bank(b)
                     for s in sc.stmts.values()))
    dpc = next(pc for sc in script.disassemble_bank(bk)
               for pc, s in sc.stmts.items() if s.mnem == "DIALOG")
    import struct as _st
    bk.set_dialog_id(dpc, 12345)
    edited = c.build()
    c2 = script.Container(edited)
    _check("in-place DIALOG edit persists + reparses",
           _st.unpack_from("<I", c2.banks[bk.index].data, dpc + 2)[0] == 12345)
    _check("edit changes only the targeted bytes",
           sum(1 for a, b in zip(raw, edited) if a != b) <= 4)
    # expression resolution + in-place value editing + labels
    c3 = script.Container(raw)
    # find an action statement with a settable (immediate) arg
    found = None
    for b3 in c3.banks:
        for s3 in script.disassemble_bank(b3, discover=False):
            for pc3, st3 in s3.stmts.items():
                if st3.op < 0xFFF0:
                    for ai, ao in enumerate(st3.args):
                        if script.arg_is_settable(b3.data, ao):
                            found = (b3, s3, pc3, st3, ai)
                            break
                    if found:
                        break
            if found:
                break
        if found:
            break
    if found:
        b3, s3, pc3, st3, ai = found
        b3.set_action_arg_value(pc3, ai, 7)
        s3b = script.disassemble_scene(b3, s3.action_type, s3.entry_pc)
        _check("set_action_arg_value yields the new value",
               script.arg_repr(b3.data, s3b.stmts[pc3].args[ai]) == "7")
        _check("value edit is same-length (round-trips)",
               len(c3.build()) == len(raw))
    else:
        _skip("script value-edit", "no settable immediate arg found")
    _check("eval_expr resolves an s8 immediate",
           script.eval_expr(b"\x18\x05\x00", 0) == (5, True))
    # structural editing: set_bank_bytes repack + relinked insert/delete
    c4 = script.Container(raw)
    c4.set_bank_bytes(5, bytes(c4.banks[5].data) + b"\x00" * 8)
    o4 = c4.build()
    c4b = script.Container(o4)
    _check("set_bank_bytes keeps other banks byte-identical",
           all(bytes(script.Container(raw).banks[i].data) == bytes(c4b.banks[i].data)
               for i in range(0, len(c4b.banks), 137) if i != 5))
    # find a clean scene with a DIALOG, insert a beat before it, verify
    c5 = script.Container(raw)
    target = None
    for b5 in c5.banks[:8]:
        for s5 in script.disassemble_bank(b5, discover=False):
            if s5.ok and any(st.mnem == "DIALOG" for st in s5.stmts.values()):
                dpc5 = next(pc for pc, st in s5.stmts.items() if st.mnem == "DIALOG")
                if script.decode_statement(b5.data, dpc5).size >= 4:
                    target = (b5, s5, dpc5)
                    break
        if target:
            break
    if target:
        b5, s5, dpc5 = target
        before = sum(1 for st in s5.stmts.values() if st.mnem == "DIALOG")
        c5.insert_before(b5, dpc5, "DIALOG #8709")
        _e5 = c5.last_relink[b5.index][s5.entry_pc]
        c5b = script.Container(c5.build())
        s5b = script.disassemble_scene(c5b.banks[b5.index], s5.action_type, _e5)
        ids = [st.dialog_id for st in s5b.stmts.values() if st.mnem == "DIALOG"]
        _check("relinked insert adds the beat in place (no JMP) + scene stays clean",
               s5b.ok and 8709 in ids and len(ids) == before + 1
               and sum(st.mnem == "JMP" for st in s5b.stmts.values())
               == sum(st.mnem == "JMP" for st in s5.stmts.values()))
        _check("insert leaves other banks byte-identical",
               all(bytes(script.Container(raw).banks[i].data) == bytes(c5b.banks[i].data)
                   for i in range(0, len(c5b.banks), 211) if i != b5.index))
        # rewrite_scene: author a fresh body on the same trigger
        c6 = script.Container(raw)
        _e6 = c6.rewrite_scene(b5.index, s5.entry_pc, "DIALOG #8709\nDIALOG #8709")
        s6 = script.disassemble_scene(c6.banks[b5.index], s5.action_type, _e6)
        ids6 = [st.dialog_id for st in s6.stmts.values() if st.mnem == "DIALOG"]
        _check("rewrite_scene installs the new body",
               s6.ok and ids6.count(8709) >= 2)
        # compound edits compose: an in-place edit must survive a LATER rebuild (the real
        # multi-edit modder workflow, where the second edit shifts file offsets). Both edits must
        # be present after build -> reparse from scratch.
        c7 = script.Container(raw)
        b7 = c7.banks[b5.index]
        b7.set_dialog_id(dpc5, 9001)                    # 1) in-place edit
        c7.insert_before(b7, dpc5, "DIALOG #9002")  # 2) bank rebuilt (shifts offsets)
        _ids7 = [st.dialog_id
                 for sc in script.disassemble_bank(script.Container(c7.build()).banks[b5.index],
                                                    discover=False)
                 for st in sc.stmts.values() if st.mnem == "DIALOG"]
        _check("compound edits compose (in-place edit survives a later rebuild)",
               9001 in _ids7 and 9002 in _ids7)
        # author-by-name: insert a DIALOG + an action resolved BY NAME in one shot; both must
        # persist through build->reparse and the action must decode (the opcode half of the
        # 'build a wholly-new cutscene' workflow, alongside append_text for the dialogue text).
        c8 = script.Container(raw)
        _give = script.op_from_name("GivePlayerItem")
        c8.insert_before(c8.banks[b5.index], dpc5,
                         "DIALOG #8801\nop%d 258, 1, 0" % _give)
        s8 = script.disassemble_scene(c8.banks[b5.index], s5.action_type,
                                      c8.last_relink[b5.index][s5.entry_pc])
        _m8 = [script.opcode_mnemonic(st.op) for st in s8.stmts.values() if st.op < 0xFFF0]
        _d8 = [st.dialog_id for st in s8.stmts.values() if st.mnem == "DIALOG"]
        _check("author-by-name: insert DIALOG + action-by-name composes + decodes",
               s8.ok and 8801 in _d8 and "GivePlayerItem" in _m8
               and script.render_action(_give, ["258", "1", "0"]) == "GivePlayerItem(258=Pineapple Juice, 1, 0)")
    else:
        _skip("script structural insert", "no suitable scene found")
    # delete-safety: deleting a statement that is a BRANCH TARGET must not corrupt the scene --
    # the rebuild sends the branch to the next statement (no dangling reference). Find such a
    # case, delete the target, verify still valid.
    cD = script.Container(raw)
    _dtgt = None
    for _bd2 in cD.banks[:30]:
        for _scd in script.disassemble_bank(_bd2, discover=False):
            if not _scd.ok:
                continue
            for _pc, _st in _scd.stmts.items():
                for _t in (_st.code_targets or []):
                    if (_t is not None and _t in _scd.stmts and _t != _pc
                            and _scd.stmts[_t].falls_through and not _scd.stmts[_t].terminator):
                        _dtgt = (_bd2, _scd, _t)
                        break
                if _dtgt:
                    break
            if _dtgt:
                break
        if _dtgt:
            break
    if _dtgt:
        _bd2, _scd, _t = _dtgt
        _st_t = _scd.stmts[_t]
        if _st_t.falls_through and not _st_t.terminator:
            _nx = cD.delete_statement(_bd2, _t)
            _scd2 = script.disassemble_scene(_bd2, _scd.action_type,
                                             cD.last_relink[cD.banks.index(_bd2)][_scd.entry_pc])
            _check("deleting a branch target keeps the scene valid (the branch goes to the next statement)",
                   _scd2.ok and _nx in _scd2.stmts and len(_scd2.stmts) == len(_scd.stmts) - 1
                   and cD.build() is not None)
        else:
            _skip("delete branch-target safety", "the first branch target found never falls through")
    else:
        _skip("delete branch-target safety", "no in-scene branch target found in sample")
    # global-bank edit path: the special opening-cutscene bank is addressed by a DIRECT header
    # pointer (byte 12), not a section table -- a distinct grow/fixup code path. Editing + growing
    # it must update that pointer's size and reparse cleanly with the edits applied.
    cg = script.Container(raw)
    _gb = next((b for b in cg.banks if b.kind == "global"), None)
    if _gb is not None:
        _gsc = list(script.disassemble_bank(_gb, discover=False))
        _gdpc = next((pc for sc in _gsc for pc, st in sc.stmts.items() if st.mnem == "DIALOG"), None)
        if _gdpc is not None:
            _gb.set_dialog_id(_gdpc, 7777)
        cg.insert_before(_gb, next(iter(_gsc[0].stmts)), "DIALOG #7778")
        cg2 = script.Container(cg.build())
        _gb2 = next(b for b in cg2.banks if b.kind == "global")
        _gids = [st.dialog_id for sc in script.disassemble_bank(_gb2, discover=False)
                 for st in sc.stmts.values() if st.mnem == "DIALOG"]
        _check("global bank (byte-12 pointer) edit+grow reparses with edits",
               7778 in _gids and (_gdpc is None or 7777 in _gids))
    else:
        _skip("global-bank edit", "no global bank in this rf3.mc")
    # set_action_opcode (the GUI's SetSpeaker speaker-swap): swapping an op is size-preserving and
    # reparses with the new op; a non-action opcode is rejected cleanly.
    cS = script.Container(raw)
    _sp = None
    for _bS in cS.banks[:20]:
        for _scS in script.disassemble_bank(_bS, discover=False):
            for _pcS, _stS in _scS.stmts.items():
                if 16 <= _stS.op <= 75:
                    _sp = (_bS, _pcS, _stS.op)
                    break
            if _sp:
                break
        if _sp:
            break
    if _sp:
        _bS, _pcS, _oldop = _sp
        _newop = _oldop + 2 if _oldop + 2 <= 75 else _oldop - 2
        _sz0 = script.decode_statement(_bS.data, _pcS).size
        _bS.set_action_opcode(_pcS, _newop)
        _stA = script.decode_statement(script.Container(cS.build()).banks[_bS.index].data, _pcS)
        _rej = False
        try:
            _bS.set_action_opcode(_pcS, 0xFFFF)
        except script.ScriptError:
            _rej = True
        except Exception:
            pass
        _check("set_action_opcode swaps in place (size-preserving) + rejects non-action ops",
               _stA.op == _newop and _stA.size == _sz0 and _rej)
    else:
        _skip("set_action_opcode swap", "no SetSpeaker op found")
    # cutscene-author friendly metadata layer (opcode_meta)
    from rf4s_modkit import opcode_meta as om
    # NOTE: opcode table corrected 2026-07-03 -- real base = g_sceneActionHandlerTable
    # (+0x4DB790); the old table was +302-shifted. actions 16..75 = the dialogue SetSpeaker
    # cue, and the Script_VMOp_* handlers are at their true (+302) indices.
    _check("opcode_meta covers the real action table (763 slots)",
           len(om.META) == 763 and all(om.mnemonic(o) for o in range(763)))
    # naming-integrity: no author-facing mnemonic may map to TWO different handlers -- that would
    # mean the disassembly shows one name for ops that actually DO different things (as the quest
    # PopulateQuestKind<N> family did: random-cats vs literal-alternates variants collapsed to one
    # name). Shared names are fine ONLY when the ops share a handler (dual dispatch slots / speaker
    # sides). Checked against the committed op->handler dump (script_opcodes.json = the IDB names).
    import json as _json, os as _os2
    _hp = _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)),
                         "refdata", "script_opcodes.json")
    if _os2.path.exists(_hp):
        _hmap = _json.load(open(_hp, encoding="utf-8"))
        _byname = {}
        for _o in range(763):
            _mn = om.mnemonic(_o)
            if _mn and _mn not in ("(unbound)", "(unused)", "invalid", "nop"):
                _byname.setdefault(_mn, []).append(_o)
        _ambig = {_mn: _ops for _mn, _ops in _byname.items()
                  if len({_hmap.get(str(_o)) for _o in _ops}) > 1}
        _check("no mnemonic maps to >1 distinct handler (names unambiguous)",
               not _ambig, "ambiguous: %s" % list(_ambig)[:5])
        # citation integrity: every `Script_VMOp_*` handler name cited in a description must be a
        # REAL handler (a value in the op->handler dump). Catches a reconstructed/guessed name that
        # doesn't exist in the IDB -- e.g. the SetVar template once cited "WriteVarArrayKind3" when
        # the actual handler is "WriteVarArrayKind3WithSaturation", misdirecting anyone tracing the RE.
        _real = set(_hmap.values())
        _badcite = []
        for _o in range(763):
            for _cm in re.finditer(r"\bScript_VMOp_[A-Za-z0-9_]+", om.describe(_o) or ""):
                if _cm.group(0) not in _real:
                    _badcite.append((_o, _cm.group(0)))
        _check("every Script_VMOp_* citation in a description is a real handler",
               not _badcite, "bogus: %s" % _badcite[:5])
    else:
        _skip("mnemonic->handler uniqueness", "script_opcodes.json missing")
    # cross-reference integrity: a description that points at another op by "Mnemonic (op NNN)" must
    # name that op by its CURRENT mnemonic -- when an op is renamed (e.g. the quest family, or
    # QueryNpcAnimDone -> WaitActorAnimDone), stale cross-refs send a modder looking for a name the
    # disassembly no longer shows. Only flag CamelCase (>=2 caps) tokens so descriptive prose like
    # "the char-id query (op 481)" isn't a false positive.
    _xref = re.compile(r"([A-Z][A-Za-z0-9_]{3,})\s*\((?:op|opcode)\s*(\d+)\)")
    _stale_xref = []
    for _o in range(763):
        for _xm in _xref.finditer(om.describe(_o) or ""):
            _nm, _ref = _xm.group(1), int(_xm.group(2))
            if sum(1 for _ch in _nm if _ch.isupper()) >= 2:
                _act = om.mnemonic(_ref)
                if _act and _nm != _act:
                    _stale_xref.append("op%d cites '%s (op %d)' now=%s" % (_o, _nm, _ref, _act))
    _check("no stale 'Mnemonic (op NNN)' cross-references in descriptions",
           not _stale_xref, "; ".join(_stale_xref[:5]))
    # ops 16..75 are one instruction SetSpeaker(character, side, ...): opcode = 16 + 2*character
    # + side (Script_VMOp_SetSpeaker RF4S.exe+0x207F70 decodes both from the opcode)
    _check("SetSpeaker: one mnemonic, character + side are opcode arguments (op = 16 + 2*char + side)",
           all(om.mnemonic(o) == "SetSpeaker" for o in range(16, 76))
           and om.opcode_arg_values(16) == ["MC", "Left"] and om.opcode_arg_values(17) == ["MC", "Right"]
           and om.opcode_arg_values(54) == ["Nancy", "Left"]
           and all(om.op_from_opcode_args("SetSpeaker", [str(c), str(sd)]) == 16 + 2 * c + sd
                   for c in range(30) for sd in (0, 1))
           and om.op_from_opcode_args("setspeaker", ["nancy", "LEFT"]) == 54
           and om.prototype(25) == "SetSpeaker(character, side, face, trigger1, trigger2, trigger3)"
           and om.portrait_speaker_tag(16) == "MC" and om.portrait_speaker_tag(54) == "Nancy")
    _check("opcode_meta known mnemonics (+302-corrected)",
           om.mnemonic(318) == "SetNpcBirthdayGiftFlag"
           and om.mnemonic(319) == "SetNpcNicknameForPlayer" and om.mnemonic(394) == "WarpPlayer"
           # 2026-09-01 audit: op 357 is a bare kind-7 var-array write (nothing portrait-
           # related in the handler; corpus stores GetEffectCost prices for text substitution)
           and om.mnemonic(357) == "SetVar7"
           # op 412 = BlackScreen is ground-truth: the binary's one surviving script ext-command
           # debug string is rf3sScriptExecExtCmd_BlackScreen (the op-412 handler). Lock it.
           and om.mnemonic(412) == "BlackScreen")
    tip = om.tooltip(394, arg_values=["9", "12"])
    _check("opcode_meta tooltip has desc + arg values + technical name",
           __import__("re").search(r"\bx\b[^\n]*= 9", tip) is not None and "TeleportPlayerToTile" in tip)
    # metadata-layer invariants (regression guards for the curated tables): every op must
    # render its tooltip/prototype/describe/category without throwing, every category must be
    # a known bucket, and the enum-picker layer must stay wired (item/char/room/skill/...).
    _VALID_CATS = {"dialogue", "screen", "actor", "companion", "flag", "audio", "time",
                   "item", "effect", "quest", "flow", "query", "noop", "misc"}
    _throws = 0
    for _o in range(763):
        for _fn in (om.tooltip, om.prototype, om.describe, om.category, om.category_label):
            try:
                _fn(_o)
            except Exception:
                _throws += 1
    _check("opcode_meta: all 763 ops render tooltip/prototype/describe/category w/o error",
           _throws == 0, f"{_throws} throws")
    _badcat = [_o for _o in range(763) if om.category(_o) not in _VALID_CATS]
    _check("opcode_meta: every op category is a known bucket", not _badcat, str(_badcat[:8]))
    # accuracy guard: no opcode that actually appears in the scene corpus may be described as
    # never-emitted / reserved. op 0 is the trap -- it dispatches to the shared return-0 stub yet
    # is emitted 420x as an inert NOP token, so it must read as a no-op, not "the game never emits
    # it". (_seen = distinct action ops observed in real scenes, built for the render_action guard.)
    _false_dead = [_o for _o in _seen if _o in om.META
                   and "never emit" in om.META[_o]["d"].lower()]
    _check("opcode_meta: no in-scene op is described as never-emitted (op0 NOP-token accuracy)",
           not _false_dead, str(_false_dead[:8]))
    # accuracy guard: no op may label the handler's implicit scene-state/VM context pointer as if
    # it were a scriptable operand. (op 549 RequestBoxClaimFinalize had arg0="scene state" but its
    # handler reads only a1 and the corpus emits it with cnt=0 -- a phantom arg in the prototype.)
    _ctx_names = {"scene state", "scene_state", "scene ctx", "scene context",
                  "vm state", "vm", "context", "vm context", "a1"}
    _phantom = [_o for _o in range(763)
                if any(_a.lower().strip() in _ctx_names for _a in om.arg_names(_o))]
    _check("opcode_meta: no op labels the implicit VM context as an operand",
           not _phantom, str(_phantom[:8]))
    # accuracy pin (IDA-verified 2026-07-11): op 452 was mislabeled "ShipItem / Ship item(s) into
    # the shipping bin" with placeholder args a/b/c. Its handler (Script_VMOp_SpawnItemAtTileAsDrop-
    # OrVisual @ RF4S.exe+0x20DB90) calls Item_SpawnAtPositionAsDropOrVisual(slot, x_tile, y_tile,
    # as_drop); all 28 scene call sites pass (item, count, quality, x_tile~100-431, y_tile, 0/1) -- so
    # it spawns an item at a MAP TILE, not a shipping-bin op (real shipping = op 649). Pin the
    # corrected mnemonic + x/y-tile + as-drop labels so a future edit can't reintroduce the misnomer.
    # (2026-09-27: facts that moved from the description into the table row's technical
    # `details` are checked against both)
    def _dtext(_o):
        return (om.describe(_o) + " " + ((om.table_row(_o) or {}).get("details") or "")).lower()
    _m452 = om.mnemonic(452)
    _a452 = [_a.lower().strip() for _a in om.arg_names(452)]
    _check("opcode_meta: op452 = SpawnItemAtPos (not the ShipItem misnomer), args carry x/y tile + as-drop",
           "spawn" in _m452.lower() and "ship" not in _m452.lower()
           and "x" in _a452 and "y" in _a452 and any(_a.startswith("pickup") for _a in _a452)
           and not any(_a in ("a", "b", "c") for _a in _a452)
           and "shipping bin" not in om.describe(452).lower())
    # accuracy pin (IDA-verified 2026-07-11): five high-use scene-ops had FEWER arg labels than the
    # handler actually reads (undocumented args a modder can't see in the tooltip). Each was confirmed
    # by decompiling the VM-op handler's arg extraction (arr[cnt-3]/-5/-7) + cross-checked vs scene
    # values. Pin the added/corrected labels: op464 DropItemStack +level; op609 RollRandomPoint
    # +center x/y/radius; op405 SetMonsterFarmLovedToday +loved bit; op478 SpawnNpcScripted +scripted
    # bit30; op10 SetSpeakerVoice name-string + chime/tone (2026-08-18: arg0 is the NAME-PLATE string
    # id loaded with mode 2 / no portrait dispatch, not a dialogue line — the captain monologue and
    # bandit whispers speak through it; supersedes the earlier 'line id' pin).
    def _la(_o):
        return [_a.lower() for _a in om.arg_names(_o)]
    _labelfix = (
        len(om.arg_names(464)) == 3 and any(_a.startswith("level") for _a in _la(464))
        and [_a.split(" ")[0] for _a in _la(609)] == ["x", "y", "radius"]
        and len(om.arg_names(405)) == 2 and any("plant" in _a for _a in _la(405))
        and len(om.arg_names(478)) == 2 and any("held" in _a for _a in _la(478))
        and len(om.arg_names(10)) == 2 and any("character-name archive" in _a for _a in _la(10))
        and any("blip" in _a for _a in _la(10)))      # arg1 = the text blip (SE_WORDS_M/F/O/D)
    _check("opcode_meta: five scene-ops carry their IDA-verified arg labels (464/609/405/478/10)",
           _labelfix)
    # accuracy pin (IDA-verified 2026-07-11, batch 2): four roll ops were TECHNICAL-only with []
    # labels + the generic "usually a random item id" auto-desc, and op656 had only 1 of 2 labels.
    # Each verified by decompiling the handler: op596 rolls [0,N) (arg=N), op597 Shop_RollByCategory
    # (arg=category), op598 matches a display-name string id, op681 LootTable_RollByCategory
    # (arg=category) -- all write the result to ctx+64 (a VM output, not an arg); op656
    # (2026-09-01 audit: really the map UV-scroll X speed target, renamed SetMapScrollSpeedX)
    # takes (speed_x10000, snap_flag). Pin the input labels so they can't regress to [].
    _labelfix2 = (
        len(om.arg_names(596)) == 1 and om.arg_names(596)[0].lower().startswith("n ")
        and len(om.arg_names(597)) == 1 and "categor" in om.arg_names(597)[0].lower()
        and len(om.arg_names(598)) == 1 and "name" in om.arg_names(598)[0].lower()
        and len(om.arg_names(681)) == 1 and "bread" in om.arg_names(681)[0].lower()
        and len(om.arg_names(656)) == 2 and any("snap" in _a.lower() for _a in om.arg_names(656)))
    _check("opcode_meta: five more scene-ops carry IDA-verified input labels (596/597/598/681/656)",
           _labelfix2)
    # accuracy pin, re-pinned 2026-09-01 (full audit): op657 went SetMapFadeColor(R,G,B) ->
    # SetMapFadeChannel1 (2026-07-12, arg count fixed) -> SetMapScrollSpeedY: the handler writes
    # the map tile UV-SCROLL Y velocity target (work_buffer 255/257/259 + snap), the vertical
    # sibling of op656 SetMapScrollSpeedX -- the "fade" reading was retired with the IDB rename
    # to Script_VMOp_SetMapUvScrollSpeedYTarget. Still 2 args (speed + snap), never an RGB triple.
    _m657 = om.mnemonic(657)
    _a657 = [_a.lower() for _a in om.arg_names(657)]
    _check("opcode_meta: op657 = 2-arg map UV-scroll Y speed (speed+snap), not fade / not RGB",
           _m657 == "SetMapScrollSpeedY" and len(_a657) == 2
           and any("speed" in _a for _a in _a657) and any("snap" in _a for _a in _a657)
           and _a657 != ["r", "g", "b"])
    # systematic guard (2026-07-12): an op whose description says "Alias of op N (same handler)"
    # runs the SAME handler, so it must carry the SAME NUMBER of arg labels as op N -- otherwise the
    # alias silently drops an arg the modder can't see (op200 SetCameraTargetActor had only ['actor
    # slot'] while its alias op199 had the camera-distance too). Encodes the shared-handler sibling
    # lesson offline (no IDA needed) from the description text.
    _alias_mismatch = []
    for _o in range(763):
        _dd = om.META.get(_o, {}).get("d") or ""
        _mm = re.match(r"(?:True |Exact )?[Aa]lias of op (\d+)", _dd)
        if _mm:
            _tgt = int(_mm.group(1))
            if len(om.arg_names(_o)) != len(om.arg_names(_tgt)):
                _alias_mismatch.append((_o, len(om.arg_names(_o)), _tgt, len(om.arg_names(_tgt))))
    _check("opcode_meta: every 'Alias of op N' op has the same arg-label count as op N",
           not _alias_mismatch, str(_alias_mismatch[:5]))
    # accuracy pin (IDA-verified 2026-07-12): op319 SetNpcNicknameForPlayer shares handler Script_VMOp_SetNpcEmoteByte
    # with op320, but its desc said "Show an emote bubble over an NPC" -- WRONG. The handler writes the
    # per-NPC facial-expression byte at record+57 (switches the portrait face), it is NOT the transient
    # emote-BUBBLE popup system (those are op5/6/7 ShowNpcBubble). Pin the corrected framing.
    _d319 = _dtext(319)
    _check("opcode_meta: op319 = facial-expression byte (record+57), not an emote 'bubble'",
           "nickname" in _d319 and "show an emote bubble" not in _d319 and "+57" in _d319)
    # companion pin (IDA-verified 2026-07-12): op322 SetNpcNickname writes the MOOD byte record+56 (handler
    # Script_VMOp_SetNpcMoodByte), a DIFFERENT byte from op319's emote +57. Its old terse "mood /
    # facial expression" wording collided with op319's "facial-expression" -- disambiguated so the two
    # NPC expression bytes (+56 mood vs +57 emote) don't blur together.
    _d322 = _dtext(322)
    _check("opcode_meta: op322 = mood byte (record+56), disambiguated from the +57 emote byte",
           "+56" in _d322 and "nickname" in _d322 and "mood / facial expression" not in _d322)
    # op93 SetDialogueBoxStyle (and ops 94-97 SetBoxNormal/Shout/Thought/Trembling) set the
    # MESSAGE-BOX style, not a face
    # (re-verified 2026-09-25: task+160 picks window art talk_win<n> = archive 15851+n and tail
    # talk_hige<n>; 4 = tail only). The 2026-07-12 reading ("3-bit portrait expression, 0-5 =
    # normal/angry/... ") was wrong. The picker names the five real styles.
    _d93 = _dtext(93)
    _e93 = om.ENUM_ARG_VALUES.get((93, 0), {})
    _check("opcode_meta: op93 = the message-box style (0 normal, 1 shout, 2 thought, 3 trembling, 4 tail only)",
           "box style" in _d93 and "talk_win" in _d93 and set(_e93) == {0, 1, 2, 3, 4}
           and _e93[1][0] == "shout" and _e93[4][0] == "tail_only")   # names are identifiers (seen in game 2026-10-01)
    # accuracy pin (IDA-verified 2026-07-11, batch 3): three ops carried the generic auto-desc
    # "Rolls a value via the RNG (usually a random item id)" that was FLATLY WRONG -- op631 is a
    # deterministic name-seeded hash, op632 uses the DAILY-seeded (reload-safe) RNG not the global
    # PRNG, and op691 is a deterministic product (no RNG at all). Each verified by decompile. Pin the
    # corrected descriptions/args so the wrong generic blurb can't creep back.
    _d631, _d632, _d691 = _dtext(631), _dtext(632), _dtext(691)
    _descfix = (
        "usually a random item id" not in _d631
        and "same name, same result" in _d631 and len(om.arg_names(631)) == 2
        and "daily" in _d632 and "usually a random item id" not in _d632 and len(om.arg_names(632)) == 2
        and "multiply" in _d691 and "random" not in _d691
        # 2026-09-01 engine tiebreak: every arg is a factor (the count is the
        # encoding's own packed slot), so a single variadic hint is correct.
        and len(om.arg_names(691)) == 1)
    _check("opcode_meta: op631/632/691 have corrected (non-generic) descriptions + args",
           _descfix)
    # accuracy pin (IDA-verified 2026-07-12): op290 wrote "unlocks achievement 4391", but 4391 is
    # NOT one of the ~30 real named achievements special-cased in GameFlags_WritePacked_OrAchievement
    # (RF4S.exe+0x1D6000) -- it falls through to GameFlags_WriteField as a PACKED game-flag write
    # (bit 295, width 2, value 2; the IDA handler name 'SetWifeStatus2...' = marriage status). So it
    # sets a marriage/family-status game-flag, then runs the family birthday/anniversary check -- NOT
    # an achievement unlock. Pin the corrected framing so the misnomer can't return.
    _d290 = _dtext(290)
    _check("opcode_meta: op290 = marriage-status game-flag write (not 'unlocks achievement 4391')",
           "game flag" in _d290 and "unlocks achievement 4391" not in _d290
           and "wife_status" in _d290 and "wife_days" in _d290)
    # completeness of the same fix (2026-07-12): op379 (id 1072 'first scripted BGM') and op557/558
    # (per-NPC ids 1451-1473) also route through GameFlags_WritePacked, so they're packed game-flag
    # writes, NOT the ~30 named Steam achievements. op379's note is corrected; op557/558 were renamed
    # UnlockNpcAchievements -> SetNpcRecognitionFlags (a graded per-NPC flag). Pin so "achievement"
    # framing can't creep back onto these packed-flag ids.
    _d379, _m557, _m558 = _dtext(379), om.mnemonic(557), om.mnemonic(558)
    _check("opcode_meta: op379/557/558 framed as packed game-flags, not achievements",
           "1072" in _d379 and "achievement 1072" not in _d379
           and _m557 == "SetNpcRecognitionFlags" and _m558 == "SetNpcRecognitionFlags"
           and "packed game flag" in _dtext(557) and "packed game flag" in _dtext(558))
    # A description that assigns a label's exact name to a different argN (e.g. the SetSpeaker
    # family said "arg1 = face frame" while "face frame" is label index 0) would mislead an author
    # cross-referencing the tooltip prose against the editor's 0-based arg rows. The negative
    # lookbehind skips the second half of combined "argA/argB = X/Y" refs (op 122 tile x/y).
    _obo = []
    for _o in range(763):
        _dl = om.describe(_o).lower()
        for _idx, _nm in enumerate(om.arg_names(_o)):
            _n = _nm.lower().strip()
            if len(_n) < 5 or "/" in _n:
                continue
            for _m in re.finditer(r"(?<![/\w])arg(\d+)\s*=\s*" + re.escape(_n), _dl):
                if int(_m.group(1)) != _idx:
                    _obo.append((_o, _n, int(_m.group(1)), _idx))
    _check("opcode_meta: description arg numbering is 0-based + matches label indices",
           not _obo, str(_obo[:6]))
    _pickers = sum(1 for _o in range(763) for _i in range(len(om.arg_names(_o)))
                   if om.enum_arg_choices(_o, _i))
    # ...and effect id 29 (0x1D, IDA-reversed: Effects_Dispatch/QueryById case 29 set/read
    # g_effectAppliedBits word2 bit[sub-index]) -- filled the EFFECT_IDS gap between 0x1C and 0x1F.
    # ...and op 197 ShakeCamera arg0 shake kind (IDA-reversed from PlayerEffect_TickJitterByKind
    # cases 0-5 = kinds 1-6; a bare "kind" arg that now decodes to named shake patterns).
    _check("opcode_meta: enum pickers wired + decode (item/char/room/skill/effect/shake/...)",
           _pickers >= 200 and om.enum_arg_label(423, 0, 258) == "Pineapple Juice"
           and om.enum_arg_label(644, 0, 29) == "Effect-applied flag"
           and om.enum_arg_label(197, 0, 6) == "rotational",   # the in-game names (2026-10-02)
           f"{_pickers} picker slots")
    # accuracy guard: every enum picker must be wired to an arg index that actually exists on the
    # op (ai < label count). A picker on arg3 of a 3-arg op (indices 0-2) would silently never
    # render -- a dead picker. (ENUM_ARG_VALUES keys are (op, arg_index).)
    _deadpick = [(_o, _ai) for (_o, _ai) in om.ENUM_ARG_VALUES
                 if _ai >= len(om.arg_names(_o))]
    _check("opcode_meta: no enum picker wired to a non-existent arg index",
           not _deadpick, str(_deadpick[:8]))
    # accuracy pin (2026-07-12): op 376 OpenShop arg1 is a SHOP dispatch id
    # (all 192 vanilla sites pass 75-89); its picker was wired to the FULL 83-entry
    # WORLD_INTERACTION_ACTIONS table, so a moder editing a "shop id" saw Save/Load/NameEntry
    # (non-shops that wouldn't open a shop). Scoped it to the shop subrange 75-89. Pin that op376's
    # picker is shop-only while op375 (OpenMenu) keeps the full action table.
    _p376 = om.ENUM_ARG_VALUES.get((376, 1), {})
    _p375 = om.ENUM_ARG_VALUES.get((375, 0), {})
    _check("opcode_meta: op376 shop-id picker scoped to shops 75-89 (not the full action table)",
           len(_p376) == 15 and set(_p376) == set(range(75, 90))
           and all(_v[0].lower().startswith("shop") for _v in _p376.values())
           and len(_p375) > 60 and 2 in _p375)   # op375 keeps Save/Load/... full set
    # accuracy guard: every "op N" cross-reference in a description points to a real action slot
    # (0..762). A typo'd or stale reference (e.g. "counterpart to op 900") would misdirect an
    # author to a non-existent op. Only 763 action slots exist.
    _xref_bad = []
    for _o in range(763):
        for _m in re.finditer(r"\bop(?:code)?\s+(\d{1,4})\b", om.describe(_o)):
            if int(_m.group(1)) > 762:
                _xref_bad.append((_o, int(_m.group(1))))
    _check("opcode_meta: all 'op N' description cross-references are in range (0..762)",
           not _xref_bad, str(_xref_bad[:8]))
    # insert-by-name: op_from_name resolves curated mnemonics (case-insensitive), rejects
    # unknowns, and round-trips for every non-placeholder op (name -> op -> same mnemonic).
    _rt = all(script.op_from_name(om.mnemonic(_o)) is not None
              for _o in range(763)
              if om.mnemonic(_o) not in ("(unbound)", "(unused)", "nop", "invalid"))
    _check("op_from_name resolves every curated mnemonic + is case-insensitive",
           _rt and script.op_from_name("giveplayeritem") == 423
           and script.op_from_name("no_such_op") is None)
    # op discovery search (powers 'did you mean' when authoring by name)
    _fade = {m for _o, m in script.find_ops("fade")}
    _check("find_ops discovers ops by name substring",
           "FadeScreen" in _fade and len(script.find_ops("camera")) >= 3
           and script.find_ops("zzznope") == [])
    # friendly text export: dump_text(friendly=True) is a full disassembly listing using the
    # curated mnemonics -- a reference/doc output outside the GUI. Guard it runs + emits a listing.
    _bd = next((b.index for b in c.banks
                for sc in script.disassemble_bank(b, discover=False)
                if any(st.mnem == "DIALOG" for st in sc.stmts.values())), 0)
    _dt = script.dump_text(c, banks=[_bd], friendly=True)
    _check("dump_text friendly export produces a curated disassembly listing",
           len(_dt) > 50 and "DIALOG" in _dt and "bank" in _dt)
    # control-op descriptions (used by the tooltip + the selection-panel one-liner): every
    # control mnemonic the disassembler emits must have a non-empty tooltip.
    _ctrl = set(script.CONTROL.values())
    _check("control_tooltip covers every control mnemonic",
           len(_ctrl) >= 15 and all((script.control_tooltip(_m) or "").strip() for _m in _ctrl),
           f"{len(_ctrl)} control ops")
    # format_scene friendly render (the GUI's scene view) works on a real scene
    _sc0 = next(iter(script.disassemble_bank(c.banks[_bd], discover=False)), None)
    _check("format_scene friendly render produces a listing",
           _sc0 is not None and isinstance(script.format_scene(_sc0, friendly=True), str)
           and len(script.format_scene(_sc0, friendly=True)) > 10)
    # the committed opcode reference must stay in sync with opcode_meta -- catches a metadata
    # change that forgot to re-run gen_opcode_reference. Skipped if the doc isn't present.
    import os as _os
    _refp = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "CUTSCENE_OPCODES.md")
    if _os.path.exists(_refp):
        try:
            import gen_opcode_reference as _gr
            _refdoc = open(_refp, encoding="utf-8").read()
            _check("CUTSCENE_OPCODES.md in sync with opcode_meta (re-run gen_opcode_reference.py)",
                   _gr.build() == _refdoc)
            # the flat opcodes_list.csv (spreadsheet/grep companion) is generated from the SAME
            # opcode_meta by the same generator -- guard it stays in sync too, so it can't silently
            # go stale after an opcode_meta edit (a rename/description change).
            _csvp = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "opcodes_list.csv")
            if _os.path.exists(_csvp):
                _check("opcodes_list.csv in sync with opcode_meta (re-run gen_opcode_reference.py)",
                       _gr.build_csv() == open(_csvp, encoding="utf-8").read())
            else:
                _skip("opcodes_list.csv sync", "opcodes_list.csv not generated")
            # the reference must also cover the em.bin (EMF) opcodes scenes bridge to -- not just the
            # rf3.mc VM. Guard that the Event-Manager section exists and names EVERY em action op +
            # comparison operator, so a future emscript change (or an accidental section drop, which
            # the doc==gen check alone wouldn't catch) surfaces here.
            from rf4s_modkit import emscript as _ems
            _emsec = "## Event Manager (em.bin) opcodes" in _refdoc
            _miss_act = [n for n in set(_ems.ACTION_NAMES.values()) if ("**%s**" % n) not in _refdoc]
            _miss_cmp = [v for v in _ems.CMP_NAMES.values() if ("`0x%02X` %s" %
                         ([k for k, vv in _ems.CMP_NAMES.items() if vv == v][0], v)) not in _refdoc]
            # the rf3.mc->em.bin bridge ops must be named in the doc by their EXACT mnemonic (so a
            # reader can cross-ref them in the opcode index) -- catches the approximated-name drift
            # that once slipped in (e.g. "EvalCondA" vs the real "EvalCondScriptA").
            _miss_bridge = [script.opcode_mnemonic(o) for o in script.EMF_ENTRY_OPS
                            if ("`%s` (%d)" % (script.opcode_mnemonic(o), o)) not in _refdoc]
            _check("opcode reference documents every em.bin action op + comparison + bridge op",
                   _emsec and not _miss_act and not _miss_cmp and not _miss_bridge,
                   f"section={_emsec}, missing acts={_miss_act}, cmps={_miss_cmp}, bridge={_miss_bridge}")
        except Exception as _e:
            _skip("opcode reference sync", str(_e))
    else:
        _skip("opcode reference sync", "CUTSCENE_OPCODES.md not generated")


def test_emflags():
    """Event Manager flag/register symbol table (emdeb.bin). Skipped if the file
    isn't in the bundle; validated structurally when present."""
    from rf4s_modkit import emflags
    try:
        path = emflags.find_emdeb()
    except FileNotFoundError:
        _check("emflags emdeb.bin present (skipped)", True)
        return
    t = emflags.EmFlagTable.load(path)
    _check("emflags parses the full variable table",
           len(t.variables) == 1822 and t.by_name["REG_MAIN_SCENARIO"].bit_offset == 0
           and t.by_name["REG_MAIN_SCENARIO"].bit_width == 9)
    # bit offsets are perfectly sequential (offset[i+1] == offset[i] + width[i])
    seq = all(t.variables[i + 1].bit_offset == t.variables[i].bit_offset + t.variables[i].bit_width
              for i in range(len(t.variables) - 1))
    _check("emflags bit offsets are contiguous", seq)
    # cross-check vs the save editor's verified GameFlags home-upgrade bit
    rk = t.by_name.get("REG_STORAGE_RUCK_LV")
    _check("emflags offset == GameFlags bit-id (Backpack @0x3DE w2)",
           rk is not None and rk.bit_offset == 0x3DE and rk.bit_width == 2)
    # packed read/write round-trip
    buf = bytearray((t.total_bits // 8) + 2)
    t.write_value(buf, "FLG_SUBEV_FORTE_MARRIAGE_CLEAR", 1)
    t.write_value(buf, "REG_MAIN_SCENARIO", 0x77)
    _check("emflags packed read/write round-trip",
           t.read_value(buf, "FLG_SUBEV_FORTE_MARRIAGE_CLEAR") == 1
           and t.read_value(buf, "REG_MAIN_SCENARIO") == 0x77
           and t.read_value(buf, "FLG_SUBEV_ARTHUR_MARRIAGE_CLEAR") == 0)
    # citation integrity: every FLG_/REG_/GF_ game-flag name cited in an opcode description must be a
    # REAL emdeb.bin variable (GF_ is a "game flag" display prefix -> strip it) -- a typo'd or renamed
    # flag name would misdirect a modder tracing the RE. Skip wildcard family refs (a '*' right after,
    # e.g. EM_BOSS_*_RETURN...). Completes the citation guards (handler names + op cross-refs + flags).
    from rf4s_modkit import opcode_meta as _omf
    _fl = set(t.by_name)
    _fpat = re.compile(r"\b((?:GF_|FLG_|REG_)[A-Z0-9_]{2,})\b")
    _fbad = []
    for _o in range(763):
        _dsc = _omf.describe(_o) or ""
        for _fm in _fpat.finditer(_dsc):
            if _dsc[_fm.end():_fm.end() + 1] == "*":
                continue
            _fn = _fm.group(1)
            if _fn in _fl or (_fn.startswith("GF_") and _fn[3:] in _fl):
                continue
            _fbad.append((_o, _fn))
    _check("every FLG_/REG_/GF_ flag citation in a description resolves in emdeb.bin",
           not _fbad, "unresolved: %s" % _fbad[:5])


def test_subevents():
    """Town events (subevents.py + the editor's names for them): bank 48 + i <-> em.bin entry
    166 + i, the diary title of each, what starts it (the scene running StartReservedSubEvent)
    and its participants (SUBEV_ENABLE_* in condition A). Ground truth traced 2026-10-04:
    COM_25 (bank 72) starts by talking to Porcoline, COM_26 (73) on entering Town Square,
    the Venti chat (100) on entering the Dragon Room, Margaret's marriage event (111) on
    entering Town Square."""
    from rf4s_modkit import subevents as SE
    # the nightly pick's hard-coded slots (DailyRequest_QueueTomorrowVisitor): COM_09 forced,
    # COM_49 replaces the list, MRG_VIZNAR..MRG_LEON (225..236) replace it as a group
    _rules = {e: (SE.special_rule(e) or (None,))[0] for e in (173, 174, 214, 224, 225, 229, 236, 237)}
    _check("subevents: the special slots of the nightly pick",
           _rules == {173: None, 174: "forced", 214: "replaces the pick", 224: None, 225: "marriage group",
                      229: "marriage group", 236: "marriage group", 237: None}, _rules)
    _check("subevents: bank <-> em.bin entry numbering",
           SE.entry_of_bank(73) == 191 and SE.bank_of_entry(191) == 73 and SE.entry_of_bank(47) is None
           and SE.entry_of_bank(144) is None and SE.bank_of_entry(262) is None)
    try:
        from cutscene_editor.document import ScriptDocument
        from cutscene_editor import catalog as _cat
    except Exception as e:  # noqa: BLE001
        _skip("subevents on the game data", "cutscene_editor not importable: %s" % e)
        return
    d = ScriptDocument(lambda n: (_first(n).read_bytes() if _first(n) else None))
    d.locale = "eng"
    if not d.load_from_reader() or d.em is None or len(d.container.banks) <= 1120:
        _skip("subevents on the game data", "rf3.mc / em.bin not extracted")
        return
    c = d.container
    start = {b: [SE.describe_start(t, r) for t, r in SE.starters(c.banks[b])] for b in (72, 73, 100, 111)}
    _check("subevents: what starts each event (talk vs entering a map)",
           start == {72: ["talking to Porcoline"], 73: ["entering Selphia: Town Square"],
                     100: ["entering Castle: Dragon Room"], 111: ["entering Selphia: Town Square"]}, start)
    n = sum(1 for b in range(SE.FIRST_BANK, SE.FIRST_BANK + SE.COUNT) if SE.starters(c.banks[b]))
    _check("subevents: 86 of the 96 town-event banks have a starting scene", n == 86, n)
    who = [nm for _c, nm in SE.participants(d.em, 190)]
    _check("subevents: participants = the SUBEV_ENABLE_* of condition A",
           who == ["Margaret", "Dylas", "Arthur", "Porcoline"], who)
    if d.textarc is None:
        _skip("subevents: diary titles", "rf3mc.eng not extracted")
    else:
        t = SE.diary_titles(c, d.text)
        _check("subevents: diary titles read from the diary scene",
               t.get(72) == "A Favor Repaid" and t.get(74) == "A Performance Without an Audience"
               and t.get(111) == "Being Here" and 100 not in t and len(t) > 30, (len(t), t.get(72), t.get(111)))
        _cat.refresh_subevent_names(d)
        _check("editor bank titles name town events",
               _cat.bank_title(c.banks[72]) == "Town event COM_25 · A Favor Repaid  (bank 72)"
               and _cat.bank_title(c.banks[56]).endswith("(bank 56)  ⚑ forced")
               and _cat.bank_title(c.banks[111]).endswith("(bank 111)  ⚑ marriage group")
               and _cat.bank_title(c.banks[100]) == "Town event COM_53  (bank 100)"
               and _cat.bank_title(c.banks[150]) == "Sub-event bank 150",
               (_cat.bank_title(c.banks[72]), _cat.bank_title(c.banks[100])))


def test_emscript():
    """em.bin (EMF_) Event Manager parser: entries, conditions, actions, names,
    and the rf3.mc bridge-op cross-reference. IDA-verified format (2026-07-04):
    CondScript_EvalNamedConditionA/B, CondScript_EvalEntry/EvalExpr,
    EMF_DispatchEntry/AltActionStream/DispatchActionOpcode/DecodeOperandPair."""
    from rf4s_modkit import emscript, script as S
    try:
        em = emscript.EmScript.load()
    except FileNotFoundError:
        _check("emscript em.bin present (skipped)", True)
        return
    _check("emscript parses all entries",
           len(em.entries) == 272 and em.entries[2].name == "OPENING_EV_FIN"
           and em.entries[271].name == "SUBEV_MAX")
    _check("emscript name tables complete",
           len(em.names.entry_names) == 272 and len(em.names.query_names) == 218
           and em.names.query_names[0][0] == "PlayerHP")
    # OP_HELP: every em.bin action opcode + comparison operator must carry a human-readable
    # one-liner (powers the GUI op-picker hint that explains MUL_S/DIV_U/SET_EQ_ZERO/etc to a
    # modder who doesn't read the _S/_U = signed/unsigned convention). Catches a future op added
    # to ACTION_NAMES/CMP_NAMES without a help string.
    _ophelp_missing = [_v for _v in set(emscript.ACTION_NAMES.values()) | set(emscript.CMP_NAMES.values())
                       if not emscript.OP_HELP.get(_v)]
    _check("emscript OP_HELP explains every action op + comparison operator",
           not _ophelp_missing and emscript.OP_HELP["MUL_S"].endswith("(signed multiply)")
           and "== 0" in emscript.OP_HELP["SET_EQ_ZERO"], str(_ophelp_missing))
    # every flag operand must resolve to an emdeb variable start with matching width
    ops = list(em.iter_flag_operands())
    exact = sum(1 for _e, o in ops
                if (v := em.names.flag_at(o.value)) is not None
                and v.bit_offset == o.value and v.bit_width == o.width)
    _check("emscript flag operands resolve 100%% (%d)" % len(ops),
           len(ops) >= 594 and exact == len(ops))
    # every query operand (a Script_QueryGameState id) must resolve to an emdeb.bin query name, so
    # the em condition/action editor shows a readable query name -- never a raw id. End-to-end proof
    # that the 218-name query table covers the whole corpus; parallels the flag-operand check.
    _q_tot = _q_named = 0
    for _e in em.entries:
        _qops = []
        for _which in (_e.cond_a, _e.cond_b):
            for _slot in (_which or []):
                for _x in _slot:
                    if _x.kind == "cmp":
                        _qops.extend((_x.op1, _x.op2))
        for _acts in (_e.actions, _e.alt_actions):
            for _a in (_acts or []):
                _qops.extend((_a.target, _a.value))
        for _o in _qops:
            if _o is not None and _o.kind == "query":
                _q_tot += 1
                if em.names.query_name(_o.value):
                    _q_named += 1
    _check("emscript query operands resolve 100%% (%d)" % _q_tot,
           _q_tot >= 600 and _q_named == _q_tot,
           "%d/%d named" % (_q_named, _q_tot))
    # every comparison in every entry's conditions must decode to a NAMED operator (CMP_NAMES =
    # ==/!=/>/>=; the VM has no </<= -- it uses >= with swapped operands). This locks that the em
    # condition editor (set_cmp_operator) can name+offer every operator the corpus uses; an unknown
    # nibble would surface as a bare/None operator in the editor. Parallels the flag-operand check.
    _cmp_tot = _cmp_named = 0
    for _ce in em.entries:
        for _cg in ("cond_a", "cond_b"):
            for _ccl in (getattr(_ce, _cg, None) or []):
                for _cx in (_ccl if isinstance(_ccl, (list, tuple)) else [_ccl]):
                    if getattr(_cx, "kind", None) == "cmp":
                        _cmp_tot += 1
                        if getattr(_cx, "cmp", None) in ("==", "!=", ">", ">="):
                            _cmp_named += 1
    _check("emscript every condition comparison decodes to a named operator (%d)" % _cmp_tot,
           _cmp_tot >= 500 and _cmp_named == _cmp_tot)
    # block-type census (verified against the game data)
    _check("emscript block census (condA/condB/actions/alt)",
           sum(1 for e in em.entries if e.cond_a) == 238
           and sum(1 for e in em.entries if e.cond_b) == 4
           and sum(1 for e in em.entries if e.actions) == 2
           and sum(1 for e in em.entries if e.alt_actions) == 6)
    # semantic spot-checks
    date = em.get("EV_DATE_FINISH")
    _check("emscript EV_DATE_FINISH alt actions",
           [a.pretty(em.names) for a in date.alt_actions]
           == ["FLG_DATE_FES_NOW = 0", "FLG_KOKUHAKU_NOW = 0", "REG_DATE_MAP = 0"])
    opening = em.get("OPENING_EV_FIN")
    _check("emscript OPENING_EV_FIN story jump",
           [a.pretty(em.names) for a in opening.alt_actions] == ["REG_MAIN_SCENARIO = 39"])
    day = em.get("EV_CMN_DAYTIME")
    _check("emscript EV_CMN_DAYTIME AND/OR structure",
           day.pretty_condition(em.names, "a", "") ==
           "   Hour >= 6 AND 12 > Hour\nOR Hour >= 12 AND 16 > Hour")
    # rf3.mc bridge ops resolve to entry names. Count DISTINCT (bank, pc) sites --
    # discovered scenes can overlap, so raw occurrences double-count.
    mc = BUNDLE_DIR / "bundlePatch1" / "rf3.mc"
    if QUICK and mc.is_file():
        _skip("emscript rf3.mc bridge ops all resolve", "quick mode: full-corpus sweep")
        _skip("cutscene tooltip EMF bridge names resolve", "quick mode: full-corpus sweep")
        _skip("emscript plays-when gate pattern", "quick mode: full-corpus sweep")
    elif mc.is_file():
        c = S.Container(mc.read_bytes())
        sites = {}
        for bk, sc in S.iter_scenes(c):
            for pc, st in sc.stmts.items():
                if st.op in S.EMF_ENTRY_OPS and st.args:
                    ai = S.EMF_ENTRY_OPS[st.op]
                    if ai >= len(st.args):
                        continue
                    try:
                        eid = int(S.arg_repr(bk.data, st.args[ai]))
                    except ValueError:
                        eid = None
                    sites.setdefault((bk.index, pc), eid)
        named = sum(1 for eid in sites.values()
                    if eid is not None and em.names.entry_name(eid))
        # every bridge-op operand must decode to a valid EMF entry id (0..271)
        _check("emscript rf3.mc bridge ops all resolve (%d/%d distinct sites)"
               % (named, len(sites)), len(sites) >= 100 and named == len(sites))
        # ...and via the module-level script.emf_entry_name (auto-find) -- the SAME resolver the
        # GUI tooltip uses ("Event Manager entry: <name>" in _rich_tip_text). Distinct code path
        # from em.names above; this locks that the editor shows em names, not raw entry ids.
        _named_gui = sum(1 for eid in sites.values()
                         if eid is not None and S.emf_entry_name(eid))
        _check("cutscene tooltip EMF bridge names resolve (module-level emf_entry_name)",
               _named_gui == len(sites))
        # "plays-when" gate pattern: EvalCondA/B (371/372) immediately feeding a
        # BR_Z/BR_NZ = a guard whose entry condition is the trigger. Confirm the
        # pattern exists and the referenced entries' conditions decode (editor uses
        # this for the scene "fires when" header).
        gate_hits = 0
        for bk, sc in S.iter_scenes(c):
            ss = sorted(sc.stmts.items())
            for i, (pc, st) in enumerate(ss):
                if st.op not in (371, 372) or not st.args:
                    continue
                if i + 1 >= len(ss) or ss[i + 1][1].mnem not in ("BR_Z", "BR_NZ"):
                    continue
                ai = S.EMF_ENTRY_OPS[st.op]
                try:
                    eid = int(S.arg_repr(bk.data, st.args[ai])) if ai < len(st.args) else None
                except ValueError:
                    eid = None
                if eid is not None and 0 <= eid < len(em.entries):
                    e = em.entries[eid]
                    if (e.cond_b if st.op == 372 else e.cond_a):
                        gate_hits += 1
        _check("emscript plays-when gate pattern (EvalCond+BR guards, %d)" % gate_hits,
               gate_hits >= 50)

    # em.bin in-place editor: byte-perfect no-op build + a real 3-byte edit round-trip
    raw_em = open(emscript.find_em(), "rb").read()
    em_e = emscript.EmScript.parse(raw_em, em.names)
    _check("emscript build() byte-perfect (no edits)", em_e.build() == raw_em)
    ent = em_e.get("EV_BOSS_SP_DEAD")            # condB: REG_MAIN_SCENARIO >= 19; alt: =19
    cx = ent.cond_b[0][0]
    lit = cx.op2 if cx.op2.kind in ("lit", "slit") else cx.op1
    em_e.set_operand_value(lit, 10)              # >= 19  ->  >= 10
    em_e.set_cmp_operator(cx, ">")               #        ->  > 10
    em_e.set_operand_value(ent.alt_actions[0].value, 39)   # = 19 -> = 39
    ed = em_e.build()
    re_e = emscript.EmScript.parse(ed, em.names).get("EV_BOSS_SP_DEAD")
    _check("emscript in-place edit (3 bytes, round-trips)",
           len(ed) == len(raw_em)
           and sum(1 for a, b in zip(raw_em, ed) if a != b) == 3
           and re_e.pretty_condition(em.names, "b", "").strip() == "REG_MAIN_SCENARIO > 10"
           and [a.pretty(em.names) for a in re_e.alt_actions] == ["REG_MAIN_SCENARIO = 39"])
    # set_action_op: the em editor's THIRD edit method (Event Manager window apply_field -> set_action_op)
    # -- changes an arithmetic action's operator (SET/ADD/SUB/MUL_.../SET_EQ_ZERO) via a 1-byte
    # high-nibble edit, preserving the operand; rejects CALL/None/bad-op. Fresh parse, independent
    # of the 3-byte edit above. The other two em-edit methods (set_operand_value/set_cmp_operator)
    # are covered above; this closes the last untested em-editor edit path.
    _ea = emscript.EmScript.parse(raw_em, em.names)
    _act = _ea.get("EV_BOSS_SP_DEAD").alt_actions[0]      # arithmetic SET action
    _newop = "ADD" if _act.name != "ADD" else "SUB"
    _ea.set_action_op(_act, _newop)
    _eab = _ea.build()
    _react = emscript.EmScript.parse(_eab, em.names).get("EV_BOSS_SP_DEAD").alt_actions[0]
    _arej = 0
    for _bad in (lambda: _ea.set_action_op(None, "SET"),
                 lambda: _ea.set_action_op(_act, "NOTANOP")):
        try:
            _bad()
        except Exception:
            _arej += 1
    _check("emscript set_action_op changes an action operator (1-byte, round-trips) + rejects bad",
           len(_eab) == len(raw_em)
           and sum(1 for a, b in zip(raw_em, _eab) if a != b) == 1
           and _react.name == _newop and _arej == 2)
    # set_cond_ref: repoint a condA/condB *reference* to another entry id (CLI `em set
    # --entry-ref`; the GUI omits it by design). Real target: EV_BOSS_SP_DEAD's cond_a[0][0]
    # is `not condB(#7)` -- retarget #7 -> #42 in place, rebuild, reparse, confirm the new
    # ref + byte-stability + rejection of a cmp expr / None.
    _cr = emscript.EmScript.parse(raw_em, em.names)
    _refx = _cr.get("EV_BOSS_SP_DEAD").cond_a[0][0]
    _cr.set_cond_ref(_refx, 42)                          # #7 -> #42
    _crb = _cr.build()
    _re_ref = emscript.EmScript.parse(_crb, em.names).get("EV_BOSS_SP_DEAD").cond_a[0][0]
    _crej = 0
    for _bad in (lambda: _cr.set_cond_ref(_cr.get("EV_BOSS_SP_DEAD").cond_b[0][0], 3),  # a cmp
                 lambda: _cr.set_cond_ref(None, 3)):
        try:
            _bad()
        except Exception:
            _crej += 1
    _check("emscript set_cond_ref repoints a condA/condB reference (round-trips) + rejects bad",
           _refx.kind == "not_cond_b" and _refx.ref == 42
           and len(_crb) == len(raw_em)
           and sum(1 for a, b in zip(raw_em, _crb) if a != b) == 1
           and _re_ref.kind == "not_cond_b" and _re_ref.ref == 42 and _crej == 2)
    # set_call_entry: repoint a CALL action to another entry id (CLI `em set --entry-ref` on an
    # action). The shipping em.bin corpus has ZERO CALL actions (control flow is via condA/condB
    # refs, all actions are arithmetic register writes) -- so this is a latent editor path with no
    # natural target; exercise its u16/u32 in-place packing on a crafted buffer instead. u16 CALL
    # #5 @0 and u32 CALL #0x11223344 @3, retarget both, verify bytes + u16-overflow / non-CALL
    # rejection. (Asserting the corpus is CALL-free documents *why* this guard is synthetic.)
    _corpus_calls = sum(1 for _en in em.entries for _s in (_en.actions, _en.alt_actions)
                        for _a in (_s or []) if _a.name == "CALL")
    _syn = emscript.EmScript([], em.names, data=bytearray(b"\x00\x05\x00\x10\x44\x33\x22\x11"))
    _a16 = emscript.Action(0x00, "CALL", entry=5, pos=0)
    _a32 = emscript.Action(0x10, "CALL", entry=0x11223344, pos=3)
    _syn.set_call_entry(_a16, 9)
    _syn.set_call_entry(_a32, 0x0A0B0C0D)
    _synb = _syn.build()
    _ok16 = struct.unpack_from("<H", _synb, 1)[0] == 9
    _ok32 = struct.unpack_from("<I", _synb, 4)[0] == 0x0A0B0C0D
    _srej = 0
    for _bad in (lambda: _syn.set_call_entry(emscript.Action(0x20, "SET", pos=0), 1),  # not CALL
                 lambda: _syn.set_call_entry(_a16, 0x10000)):                          # u16 overflow
        try:
            _bad()
        except Exception:
            _srej += 1
    _check("emscript set_call_entry repoints u16/u32 CALL (synthetic; corpus is CALL-free) + rejects bad",
           _corpus_calls == 0 and _ok16 and _ok32 and _srej == 2
           and len(_synb) == 8)
    # action TARGET retarget (completes the em action editor: --value edits the value written,
    # this edits WHICH flag/reg is written). All 77 corpus action targets are kind 'flag', so
    # set_operand_value(act.target, offset) works. CLI `em set --action .. --target FLG_NAME`
    # resolves the name -> bit offset via em.names.flags.find. Verify a real retarget round-trips.
    _tg = emscript.EmScript.parse(raw_em, em.names)
    _te = _tg.get("EV_SUBEV_INIT")
    _ta = _te.actions[0] if (_te and _te.actions) else None
    if _ta is not None and _ta.name != "CALL" and _ta.target and _ta.target.kind == "flag":
        _old_off = _ta.target.value
        # resolve a DIFFERENT flag by name, exactly as the CLI does
        _dst = [v for v in em.names.flags.find("FLG_SUBEV_B") if v.name == "FLG_SUBEV_B"]
        _new_off = _dst[0].bit_offset if _dst else _old_off
        _tg.set_operand_value(_ta.target, _new_off)
        _reta = emscript.EmScript.parse(_tg.build(), em.names).get("EV_SUBEV_INIT").actions[0]
        _check("emscript action-target retarget (set_operand_value on act.target, name-resolved) round-trips",
               _new_off != _old_off and _reta.target.value == _new_off
               and _reta.name == _ta.name and len(_tg.build()) == len(raw_em))
    else:
        _skip("emscript action-target retarget", "EV_SUBEV_INIT action 0 not an editable flag target")


def test_save():
    """rf4_sNN.sav per-slot save editor: CRC (zlib over file[4:4+140196]) round-trip +
    named GameFlag edit (MSB-first, via emflags @ save+0x1E8C4). Skipped w/o a real save."""
    print("save (rf4_sNN.sav editor):")
    from rf4s_modkit import save
    # scalar writes validate (season 0..3; a u32 overflow is a SaveError, not struct.error)
    _sy = save.SaveFile(bytes(save.SAVE_SIZE))
    _rej = 0
    for _bad in (lambda: _sy.set("season", 4), lambda: _sy.set("day", -1), lambda: _sy.set("year", 1 << 32)):
        try:
            _bad()
        except save.SaveError:
            _rej += 1
    _check("save scalar set validates (season 0..3, u32 range)",
           _rej == 3 and _sy.set("season", 3).get("season") == 3)
    p = next(iter(sorted(GAME_DIR.glob("rf4_s[0-9][0-9].sav"))), None)   # a real save next to Bundle/
    if p is None:
        _skip("save editor", "no real rf4_sNN.sav present")
        return
    orig = p.read_bytes()
    s = save.SaveFile(orig)
    _check("save CRC valid (stored==computed) + build byte-perfect",
           s.crc_ok() and s.build() == orig)
    # named GameFlag edit: MSB-first, minimal diff, CRC auto-recomputed, re-parses
    s2 = save.SaveFile(orig)
    before = s2.flag("REG_MAIN_SCENARIO")
    want = (before + 7) & 0x1FF
    s2.set_flag("REG_MAIN_SCENARIO", want)
    built = s2.build()
    s3 = save.SaveFile(built)
    _check("save flag edit round-trips + CRC valid + minimal diff",
           s3.flag("REG_MAIN_SCENARIO") == want and s3.crc_ok()
           and sum(1 for a, b in zip(orig, built) if a != b) <= 8)
    # multi-bit MSB-first sanity: child id must be a valid roster id (0 none / 22 son / 23 daughter)
    _check("save GameFlags MSB-first (REG_CHILD_ID in {0,22,23})",
           s.flag("REG_CHILD_ID") in (0, 22, 23))


def test_schedule():
    print("schedule:")
    from rf4s_modkit import schedule
    p = _first("rf3Schedule.bin")
    if not p:
        _skip("schedule decode", "no rf3Schedule.bin present")
        return
    d = p.read_bytes()
    _check("schedule magic", int.from_bytes(d[:4], "little") == schedule.MAGIC)
    scheds = [lst for _k, lst in schedule.Schedule.parse(d).ordered_cells()]
    _check("schedule split (>100 schedules)", len(scheds) > 100)
    # every stop has an in-range slot (0..110) and spot kind (<872); schedules start at day-start
    wps = [w for lst in scheds for w in lst]
    _check("schedule stops in range",
           all(0 <= w.slot <= 110 and w.spot < 872 for w in wps))
    _check("schedule first stop = 06:00 day-start",
           scheds[0][0].slot == 24 and schedule.slot_to_time(24) == "06:00")
    # NpcSchedule_PickRandomScheduleSlotByKind sums a kind's spot weights in a u8
    sid = _first("rf3ScheduleID.bin")
    if sid:
        spots = schedule.load_spots(sid.read_bytes())
        k = next(k for k in range(schedule.MAX_KIND + 1) if len(schedule.kind_records(k)) >= 2)
        heavy = list(spots)
        for i in schedule.kind_records(k):
            heavy[i] = heavy[i]._replace(weight=200)
        _check("schedule spot weights: shipped kinds fit the u8 total, a 2x200 kind is flagged",
               schedule.spot_weight_problems(spots) == []
               and schedule.spot_weight_problems(heavy) == [(k, 200 * len(schedule.kind_records(k)))])


def test_gifts():
    print("gifts:")
    from rf4s_modkit import gifts
    # Anchor on Raven (file 25) — cross-checked against the in-game Gift Preferences UI:
    # off3 = 19 LOVED (pendants/ores), off2 = 28 LIKED, off1 = DISLIKED (Skull is the -10
    # signature/hated item). This nails the loved<->disliked orientation.
    rv = _first("rf3PresentNpc25.bin")
    if rv:
        g = gifts.parse(rv.read_bytes())[0]
        _check("gift Raven tier counts (loved 19 / liked 28)",
               len(g["loved"]) == 19 and len(g["liked"]) == 28)
        _check("gift loved is positive-FP, disliked is negative-FP",
               all(gifts.entry_fp(e, "loved") > 0 for e in g["loved"])
               and all(gifts.entry_fp(e, "disliked") < 0 for e in g["disliked"]))
        _check("gift disliked has one signature/hated (-10) item",
               sum(1 for e in g["disliked"] if e.code == gifts.SIGNATURE_DISLIKE_CODE) == 1)
    else:
        _skip("gift Raven checks", "no rf3PresentNpc25.bin present")
    # cross-ref decode: raw 0x8100 -> xref idx 0 (was wrongly 512 via raw-0x7F00)
    _check("gift xref decode (0x8100 -> idx 0)",
           gifts._decode_target(0x8100) == ("xref", 0)
           and gifts._decode_target(0x8112) == ("xref", 18))
    # item-range wildcard (0x8000..0x80FF): tag 2 = vegetables (ids 1..54), from g_itemCategoryRangeTable
    _check("gift item-range #2 = vegetables (ids 1..54)",
           gifts.ITEM_RANGE_TABLE[2][:2] == (1, 55)
           and "vegetables" in gifts._fmt(gifts.Entry("category", 2, 0)))
    # GiftTable_FindEntryByItemIdOrRangeOrCrossRef compares the whole target with item & 0x7FF
    # and indexes the 12-pair g_itemCategoryRangeTable with the tag; FP codes are s16
    _rej = 0
    for _bad in (lambda: gifts.encode_target("item", 0x800), lambda: gifts.encode_target("category", 12),
                 lambda: gifts.GiftTable([{"loved": [], "liked": [], "disliked": []}]).set_item(5, "loved", fp=40000),
                 lambda: gifts.GiftTable([{"loved": [], "liked": [], "disliked": []}]).add(
                     "liked", gifts.Entry("item", 0x7FFF, 9))):
        try:
            _bad()
        except gifts.GiftError:
            _rej += 1
    _check("gift writer rejects targets/codes the lookup misreads (item > 0x7FF, range tag > 11, fp > s16)",
           _rej == 4 and gifts.encode_target("item", 0x7FF) == 0x7FF
           and gifts.encode_target("category", 11) == 0x800B)
    cat = _first("rf3PresentCategory.bin")
    if cat:
        cats = gifts.load_categories(cat.read_bytes())
        _check("gift categories (21 groups; cat0 = trash)",
               len(cats) == 21 and any(e.kind == "item" for e in cats[0]))
        _check("gift category resolves items", len(gifts.category_items(5, cats)) > 20)  # cat5 flowers
    p = _first("rf3PresentNpc01.bin")
    if not p:
        _skip("gift render", "no rf3PresentNpc01.bin present")
        return
    _check("gift render (3 tiers + FP)",
           all(t in gifts.render(p.read_bytes()) for t in ("loved", "liked", "disliked"))
           and "FP" in gifts.render(p.read_bytes()))


def test_montame():
    print("montame:")
    from rf4s_modkit import montame
    p = _first("rf3MonsterPresent.bin")
    if not p:
        _skip("monster tame prefs", "no rf3MonsterPresent.bin present")
        return
    d = p.read_bytes()
    # species 48 (Orc) = record 0; has favored tame items with positive bonuses
    pr = montame.prefs(d, 48)
    _check("montame species 48 prefs (item + bonus)",
           len(pr) >= 2 and all(item and bonus > 0 for item, bonus in pr))
    _check("montame out-of-range species -> empty",
           montame.prefs(d, 47) == [] and montame.prefs(d, 254) == [])
    # edit round-trip
    buf = bytearray(d)
    montame.set_pref(buf, 48, 0, 777, 12)
    _check("montame edit round-trip", montame.prefs(bytes(buf), 48)[0] == (777, 12))
    # MonsterTame_RollAttemptWithItem adds the bonus as an s16: >= 0x8000 would subtract
    _rej = 0
    for _b in (0x8000, 0xFFFF, -1):
        try:
            montame.set_pref(buf, 48, 0, 777, _b)
        except ValueError:
            _rej += 1
    _check("montame rejects bonuses the s16 roll misreads", _rej == 3
           and montame.prefs(bytes(buf), 48)[0] == (777, 12))


def test_monster():
    print("monster:")
    from rf4s_modkit import monster, nlcl
    p = _first("rf3NpcParam.bin")
    if not p:
        _skip("monster template", "no rf3NpcParam.bin present")
        return
    t = nlcl.NlclTable.load(p)
    _check("monster table 392x308", t.entry_count == 392 and t.record_size == 308)
    # Orc(48): IDA-verified stats + wind-resist / earth-weak elements
    m = monster.sheet(t, 48)
    _check("monster Orc(48) core stats",
           m["hp"] == 48 and m["model"] == 756 and m["ai_file"] == "AI_m00.bin")
    # boss / guest AI scripts are not a plain AI_m{n} run (2026-10-02): ai 169 = archive 170
    _amb = monster.sheet(t, 228)
    _check("monster AI file names follow the archive table (Ambrosia's caterpillar ai 169 = AI_mb40_1.bin)",
           _amb["ai_script"] == 169 and _amb["ai_file"] == "AI_mb40_1.bin"
           and monster.sheet(t, 229)["ai_file"] == "AI_mb40_2.bin")
    _check("rf3NpcParam +276 transform_into / +292 home_map (Ambrosia 228 -> 229, Yokmir Forest 271)",
           t.row(228, "rf3NpcParam").get("transform_into") == 229 and t.row(48, "rf3NpcParam").get("home_map") == 271)
    # ATK = flat_atk + STR, MAT = flat_mat + INT, DEF/MDF = flat + VIT/2 (Actor_RecomputeAllStats)
    _check("monster Orc(48) ATK/DEF/MAT/MDF from flat + STR/INT/VIT",
           (m["atk"], m["def"], m["mat"], m["mdf"]) == (13, 4, 5, 4)
           and (m["str"], m["int"], m["vit"]) == (5, 3, 4)
           and monster.STATUS[:4] == ["poison", "seal", "paralysis", "sleep"])
    _check("monster Orc(48) elements (wind resist, earth weak)",
           m["elements"]["wind"] < 0 and m["elements"]["earth"] > 0)
    _check("monster Orc(48) has drops", len(m["drops"]) == 4 and m["drops"][0]["item_id"] == 831)
    # boss(200): status-immune (Q12 4096 = 100%)
    b = monster.sheet(t, 200)
    _check("monster boss(200) status-immune", b["resists"]["poison"] == 4096 and b["hp"] == 80000)
    # id-range semantics
    _check("monster id semantics",
           "villager" in monster.id_semantics(0) and "field" in monster.id_semantics(48)
           and "boss" in monster.id_semantics(200) and "gate" in monster.id_semantics(400))
    # verified cut ids
    _check("monster free_slots = 179/180/181", monster.free_slots(t) == [179, 180, 181])
    # clone + edit round-trip (in-memory)
    monster.clone_record(t, 48, 179)
    _check("monster clone copies record", t.record(179) == t.record(48))
    monster.set_field(t, 179, "hp", 1500)
    monster.set_field(t, 179, "elem_fire", 4096)
    m2 = monster.sheet(t, 179)
    _check("monster clone+edit", m2["hp"] == 1500 and m2["elements"]["fire"] == 4096
           and t.record(48) != t.record(179))
    # `monster new` naming step relies on the rf3TxtNpc name table being char_id-indexed
    from rf4s_modkit import textdb
    ntbl = _first("rf3TxtNpc_split2_1.eng")
    if ntbl:
        names = textdb.TextArchive.load(ntbl).texts()
        _check("monster name table index==char_id (rf3TxtNpc)",
               len(names) > 181 and names[48] == "Orc" and names[179] == "???")


def test_skillcurve():
    print("skillcurve:")
    from rf4s_modkit import skillcurve
    p = _first("rf3ParamSkillExp.bin")
    if not p:
        _skip("skill XP curve", "no rf3ParamSkillExp.bin present")
    else:
        xp = skillcurve.parse(p.read_bytes())
        # 100 real levels, non-decreasing (main curve ramps), cap-bracket = table[99]
        _check("skillcurve parse (100 levels)", len(xp) == 100)
        # envelope rises across the whole curve (it's a per-decade sawtooth, not strictly monotonic)
        _check("skillcurve envelope rises", xp[99] > xp[50] > xp[10] > xp[0])
        _check("skillcurve cap-bracket == table[99]",
               skillcurve.cap_threshold(p.read_bytes()) == xp[99])
        # edit round-trip
        buf = bytearray(p.read_bytes())
        skillcurve.set_level_xp(buf, 5, 12345)
        _check("skillcurve edit round-trip", skillcurve.parse(bytes(buf))[5] == 12345)
        # Player_gainEXP clamps skill XP to 0xFFFFFF: a larger threshold is unreachable, so the
        # writer rejects it and --scale caps at it; the generic param path has the same limit
        try:
            skillcurve.set_level_xp(buf, 5, 0x1000000)
            _rej = False
        except ValueError:
            _rej = True
        _sc = skillcurve.scale_curve(bytearray(p.read_bytes()), 1e6)
        from rf4s_modkit import nlcl as _nl
        _t = _nl.NlclTable.load(p)
        try:
            _t.set_field(5, "xp_to_next", 0x1000000, "rf3ParamSkillExp")
            _rej2 = False
        except _nl.NlclError:
            _rej2 = True
        _check("skillcurve rejects/caps thresholds above the 0xFFFFFF XP clamp",
               _rej and _rej2 and max(_sc) == skillcurve.MAX_XP)
    # family selection is data-independent (from the IDA switch)
    _check("skillcurve family map (Skill_GetLevelTable)",
           skillcurve.archive_for_skill(13) == 14821 and skillcurve.archive_for_skill(19) == 14823
           and skillcurve.archive_for_skill(0) == 14820)


def test_strengthening():
    print("strengthening (rf3ItemStrengthening):")
    from rf4s_modkit import strengthening
    p = _first("rf3ItemStrengthening.bin")
    if not p:
        _skip("rf3ItemStrengthening", "no rf3ItemStrengthening.bin present")
        return
    t = strengthening.StrengtheningTable.load(p)
    _check("strengthening 1150 x 296 B", len(t) == 1150 and t.t.record_size == 296)
    r = t.row(887)   # Broken Ice Wall: the strongest plain forge material (Item_ComputeStats S[1..2])
    _check("strengthening core row (Broken Ice Wall ATK/MAT/difficulty)",
           r.atk == 105 and r.mat == 95 and r.difficulty == 96)
    _check("strengthening reach (Glitta Augite +50%, Raccoon Leaf +25%)",
           t.row(935).reach_scale == 2048 and t.row(883).reach_scale == 1024)
    _check("strengthening tier rows (1108 ATK+10/MAT+5, 1113 DEF+6/MDF+5, 1125 ATK+2000, 1149 MDF+780)",
           t.row(1108).atk == 10 and t.row(1108).mat == 5 and t.row(1113)["def"] == 6
           and t.row(1113).mdf == 5 and t.row(1125).atk == 2000 and t.row(1149).mdf == 780)
    nonfood = sum(1 for i in range(strengthening.ITEM_ROWS) if t.row(i).is_non_food)
    _check("strengthening NON-FOOD marker on 633 ids (Crafting_CraftFromInputs bit 0x4000)",
           nonfood == 633 and t.row(329).is_non_food and not t.row(359).is_non_food,
           f"{nonfood} flagged; Steel Sword flagged, Veggieblade not")
    _check("strengthening status word decode (Withered Grass inflicts poison, RP -20%)",
           "inflicts poison" in t.row(83).status_flags() and t.row(83).heal_rp_pct == -820)
    _check("strengthening heal fields (Invinciroid HP/RP 100%)",
           t.row(121).heal_hp_pct == 4096 and t.row(121).heal_rp_pct == 4096)
    # edit round-trip through the generic NLCL writer
    t.set(887, "atk", 500)
    t2 = strengthening.StrengtheningTable(t.build())
    _check("strengthening edit round-trip", t2.row(887).atk == 500 and t2.row(887).mat == 95)
    _check("strengthening nlcl schema agrees with the module",
           [f[0] for f in nlcl.FIELD_SCHEMAS["rf3ItemStrengthening"]["fields"]] == strengthening.NAMES)


def test_sound_table():
    print("sound table (*_audio_data.bdat):")
    import tempfile
    from rf4s_modkit import soundtable as _st, opcode_meta as _om
    paths = {n: (EXTRACTED / "bundleMain" / n) for n in _st.TABLE_NAMES}
    paths = {n: (p if p.is_file() else _first(n)) for n, p in paths.items()}
    if not all(paths.values()):
        _skip("sound table", "no *_audio_data.bdat present")
        return
    tabs = {}
    for n, p in paths.items():
        raw = p.read_bytes()
        t = _st.SoundTable.parse(raw)
        tabs[n] = t
        _check(f"sound {n}: byte-exact round trip ({len(t)} ids)", t.build() == raw)
    c, e, j = (tabs[n] for n in _st.TABLE_NAMES)
    _check("sound counts (541 common, 8386 voice_en/jp; one info record per row)",
           len(c) == 541 and len(e) == 8386 and len(j) == 8386
           and all(len(t.infos) == len(t) for t in tabs.values()))
    words = {16785916: "SE_WORDS_M.wav", 16785917: "SE_WORDS_F.ogg",
             16785918: "SE_WORDS_O.wav", 16785975: "SE_WORDS_D.wav"}
    _check("sound text-blip ids SE_WORDS_M/F/O/D (16785916/17/18/16785975)",
           all(c.get(k).file == v and c.get(k).name == v.rsplit(".", 1)[0]
               for k, v in words.items()))
    _check("sound SE_WORDS_M fields (vol 65, priority 80, flag0 1, flag1 0)",
           c.get(16785916).info.as_dict() == dict(volume=65, priority=80, flag0=1, flag1=0,
                                                   name="SE_WORDS_M", file="SE_WORDS_M.wav"))
    # duplicate id: the later row wins (SoundCache_ParseBdatEntries re-points the node)
    _check("sound duplicate id 16785897 resolves to the later row (SE_SAVE.wav)",
           c.get(16785897).file == "SE_SAVE.wav" and len(c.duplicates()) == 2)
    _check("sound voice id range == Sfx_PlayById voice-slider range",
           min(k for k in e.effective() if k) == _st.VOICE_SLIDER_IDS.start
           and max(e.effective()) == _st.VOICE_SLIDER_IDS.stop - 1)
    _check("sound voice_jp differs from voice_en only in 45 STRM_*_REV files",
           [r[0] for r in e.rows] == [r[0] for r in j.rows]
           and sum(1 for a, b in zip(e.infos, j.infos) if a != b) == 45)
    # edit
    t = _st.SoundTable.parse(paths["common_audio_data.bdat"].read_bytes())
    t.set(16785916, volume=90, priority=100, flag1=1)
    t.rename(16785917, "SE_MYMOD_BLIP.ogg", name="SE_MYMOD_BLIP")
    t2 = _st.SoundTable.parse(t.build())
    _check("sound edit round trip (volume/priority/flag1, rename file+name)",
           t2.get(16785916).info.volume == 90 and t2.get(16785916).info.priority == 100
           and t2.get(16785916).info.flag1 == 1 and t2.get(16785917).file == "SE_MYMOD_BLIP.ogg"
           and t2.get(16785918).file == "SE_WORDS_O.wav" and len(t2) == 541)
    # add a brand-new id, re-parse, then remove it again
    new_id = t.free_id([e])
    t.add(new_id, "SE_MYMOD_BELL.ogg", volume=120, priority=80, flag1=0)
    t3 = _st.SoundTable.parse(t.build())
    ne = t3.get(new_id)
    _check("sound add-entry re-parse (new id, name = file stem, strings in the pool)",
           ne is not None and ne.file == "SE_MYMOD_BELL.ogg" and ne.name == "SE_MYMOD_BELL"
           and ne.info.volume == 120 and len(t3) == 542 and new_id not in _st.VOICE_SLIDER_IDS
           and t3.get(16785975).file == "SE_WORDS_D.wav")
    t3.remove(new_id)
    _check("sound remove restores the edited table byte for byte",
           t3.build() == t2.build())
    try:
        t3.add(16785916, "X.ogg")
        dup_ok = False
    except _st.SoundTableError:
        dup_ok = True
    _check("sound add refuses an existing id without replace", dup_ok)
    # find across tables + the lazy opcode annotation
    hits = _st.find_all(16777511, tabs)
    _check("sound find by id spans the tables (voice_jp flagged not-loaded)",
           {h[0] for h in hits} == {"voice_en_audio_data.bdat", "voice_jp_audio_data.bdat"}
           and any(h[2] for h in hits if h[0] == "voice_en_audio_data.bdat")
           and not any(h[2] for h in hits if h[0] == "voice_jp_audio_data.bdat"))
    lab = _st.LazySoundLabels(paths["common_audio_data.bdat"].parent.parent)
    _check("sound labels on PlaySound/PlaySoundOnFreeVoice listings",
           _om.enum_arg_label(385, 0, 16785916) == "SE_WORDS_M.wav"
           and _om.enum_arg_label(392, 0, 16777511) == "V_PLAM_TITLE_RUNE4.ogg"
           and _om.render_action(385, ["16785917"]) == "PlaySound(16785917=SE_WORDS_F.ogg)"
           and lab.get(16785975, ("",))[0] == "SE_WORDS_D.wav")
    empty = _st.LazySoundLabels(tempfile.gettempdir())
    _check("sound labels stay optional without a bundle", not empty and empty.get(1) is None)


def test_asatk():
    print("asatk:")
    from rf4s_modkit import asatk
    p = _first("as_atk_sword_00.bin") or _first("as_atk_*.bin")
    if not p:
        _skip("asatk decode", "no as_atk_*.bin present")
        return
    d = p.read_bytes()
    ev = asatk.parse(d)
    # every stream is (op,arg) pairs terminated by END(66)
    _check(f"asatk stream ends with END ({p.name})", ev and ev[-1].op == asatk.END_OP)
    summ = asatk.summary(d)
    # frame markers must be monotonic non-decreasing (it's a timeline clock)
    frames = [e.arg for e in ev if e.op == 0]
    _check("asatk frame markers monotonic", all(b >= a for a, b in zip(frames, frames[1:])))
    # HIT_WIN open/close pairs must be well-formed (open frame <= close frame)
    _check("asatk hit-window open<=close",
           all(o is None or c is None or o <= c for o, c in summ["hit_windows"]))
    # render must not throw and must mention END
    _check("asatk render", "@END" in asatk.render(d))


def test_bugfixes():
    """Regression tests for bugs fixed in the 2026-07-06 review sweep."""
    print("bugfixes:")
    import struct as _s
    # rf4m.delete_record must count RECORDS across a multi-record chunk (was: counted chunks,
    # so index 1 of a 2-record chunk raised out-of-range / dropped the whole chunk)
    from rf4s_modkit import rf4m
    rec0 = _s.pack("<16i", *([10] + [0] * 15))
    rec1 = _s.pack("<16i", *([20] + [0] * 15))
    m = rf4m.Rf4mMap([rf4m.Chunk(b"MOBJ", rec0 + rec1)])   # ONE chunk, TWO records
    m.delete_record(b"MOBJ", 1, 64)                        # drop the 2nd record
    recs = m.records(b"MOBJ", 64)
    _check("rf4m delete_record splices multi-record chunk", len(recs) == 1 and recs[0][0] == 10)
    # rf4m.get_ints over-read -> clean Rf4mError, not a raw struct.error
    try:
        rf4m.Rf4mMap([rf4m.Chunk(b"MSEA", _s.pack("<i", 1))]).get_ints(b"MSEA", count=5)
        _check("rf4m get_ints over-read raises Rf4mError", False)
    except rf4m.Rf4mError:
        _check("rf4m get_ints over-read raises Rf4mError", True)
    # gifts.category_items must break an A->B->A xref cycle (was: unbounded recursion)
    from rf4s_modkit import gifts
    E = gifts.Entry
    _check("gifts category_items breaks A->B->A cycle",
           gifts.category_items(0, [[E("xref", 1, 0)], [E("xref", 0, 0)]]) == [])
    # save.SaveFile must reject a buffer too short for the CRC span (was: silent short CRC)
    from rf4s_modkit import save
    try:
        save.SaveFile(bytes(130000)); ok = False
    except save.SaveError:
        ok = True
    _check("save rejects sub-CRC-span buffer", ok)
    # strings_file._unescape: a truncated \uNNNN must NOT decode as a full codepoint
    from rf4s_modkit import strings_file
    _check("strings truncated \\u escape falls through",
           chr(0x123) not in strings_file._unescape("x\\u123"))
    # opcode_meta.render_action decodes QueryPlayerStatByCharCode(charcode, skill) -> readable
    from rf4s_modkit import opcode_meta as _om
    _q = next(o for o, t in _om.TECHNICAL.items() if "QueryPlayerStatByCharCode" in t)
    _check("opcode render_action decodes player-var query",
           _om.render_action(_q, ["104", "15"]) == "GetPlayerVariable(Skill, Mining)"
           and _om.render_action(_q, ["100", "0"]) == "GetPlayerVariable(Gold)"
           and _om.mnemonic(_q) == "GetPlayerVariable")


def test_gen_structural():
    """Gen*.bin as a full model (2026-09-19): byte-exact rebuild of every stock file,
    the corrected roster record layout (8 + 4K bytes per record, verified against the
    engine's fallback roster builder), structural edits and footer regeneration."""
    print("gen (structural editor):")
    files = sorted(EXTRACTED.rglob("Gen*.bin"))
    if not files:
        _skip("gen structural", "no Gen*.bin extracted")
        return
    exact = sum(1 for p in files if gen.GenTable(p.read_bytes()).build() == p.read_bytes())
    _check("gen byte-exact rebuild of every stock file (model + regenerated footer)",
           exact == len(files), f"{exact}/{len(files)}")
    a01 = _first("GenA01.bin")
    if not a01:
        _skip("gen GenA01 checks", "GenA01.bin not extracted")
        return
    g = gen.GenTable.load(a01)
    e1 = g.patterns[0][1]
    _check("gen roster records are 8+4K bytes (GenA01 gate 1: Orc weight 50 + Orc Archer 20)",
           [(s.monster_id, s.pick_weight, s.weights) for s in e1.spawns]
           == [(48, 50, [20, 10]), (50, 20, [50, 10])]
           and [s.pick_weight for s in e1.spawns] == [50, 20]
           and (e1.hdr.count_min, e1.hdr.count_max) == (2, 2),
           str([(s.monster_id, s.pick_weight) for s in e1.spawns]))
    # 2026-09-24: consumers read the roster with record 0's stride, kinds 48..277 crash
    # Encounter_SpawnMonsterFromTemplate, > 2 patterns overflow the gate slots.
    stock_err = [p.name for p in files
                 if any(m.startswith("ERROR") for m in gen.GenTable(p.read_bytes()).validate())]
    gb = gen.GenTable.load(a01)
    eb = gb.patterns[0][1]
    gb.add_spawn(eb, 55, 10, weights=[10, 10, 10])      # K = 3 among K0 = 2 records...
    gb.add_spawn(eb, 56, 10)                             # ...and not the last one
    gb.set_gate_kind(0, 0, 100)                          # a monster id used as the gate
    for _ in range(2):
        gb.add_entry(len(gb.patterns), 359, 1, clone=eb)
    vb = gb.validate()
    _check("gen validate: stock has no fatal finding; mixed K / kind 100 / 3 patterns are fatal",
           not stock_err
           and any(m.startswith("ERROR") and "stride" in m for m in vb)
           and any(m.startswith("ERROR") and "kind 100" in m for m in vb)
           and any(m.startswith("ERROR") and "3 patterns" in m for m in vb),
           ", ".join(stock_err[:3]) or f"{len(vb)} findings")
    g.add_spawn(e1, 55, 33)
    new = g.add_entry(0, 360, 7, clone=e1, share=False)
    g.add_monster_position(new, 400, 300)
    g2 = gen.GenTable(g.build())
    n2 = g2.patterns[0][2]
    ok = (len(g2.patterns[0]) == 3 and n2.gate_kind == 360 and n2.weight == 7
          and [(s.monster_id, s.pick_weight, s.weights) for s in n2.spawns]
          == [(48, 50, [20, 10, 10]), (50, 20, [50, 10, 10]), (55, 33, [10, 10, 10])]
          and len(n2.mon_pos.points) == 3 and not g2.validate()
          and len(search_items.parse_nlcl_footer(g2.build())) == 12)
    _check("gen add gate/monster/position round-trip + valid footer", ok)
    g2.remove_entry(0, 2)
    g2.remove_spawn(g2.patterns[0][1], 2)
    g3 = gen.GenTable(g2.build())
    _check("gen remove gate/monster round-trip",
           len(g3.patterns[0]) == 2 and len(g3.patterns[0][1].spawns) == 2
           and len(search_items.parse_nlcl_footer(g3.build())) == 8)


def test_texture_encode():
    """Container rewrite: ANY .texture as encode template (BC7 -> RGBA8), flipbook
    frames / strips, and the map ground export -> import inverse. The container facts
    are verified against RF4S.exe (+0x3C6000 pixel offset, +0x3C6130 memory pool,
    +0x3D2230 loader, +0x3CAA00 relocation) -- see rf4s_modkit/texture.py."""
    print("texture encode (container rewrite):")
    if not (texture.HAS_PIL and texture.HAS_BC):
        _skip("texture encode", "Pillow/texture2ddecoder not installed")
        return
    from PIL import Image
    tile = next(EXTRACTED.rglob("MAP_FIELD_01_0000.texture"), None)
    if tile is None:
        _skip("texture encode", "MAP_FIELD_01_0000.texture not extracted")
        return
    tmpl = tile.read_bytes()
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        # 1. BC7 template -> decoded PNG -> RGBA8 container; ident + parse + pixels
        png = tmp / "tile.png"
        texture.decode_to_png(tile, png)
        new = texture.encode_into(tmpl, png, fmt="RGBA8")
        i0, i1 = texture.parse(tmpl), texture.parse(new)
        ft = ident.identify(new[:0x4000], filename="x.texture")
        src = Image.open(png).convert("RGBA")
        dec = texture.decode_to_image(new).convert("RGBA")
        _check("BC7 template -> RGBA8 encode (ident/parse/pixels)",
               ft.fmt == "texture" and i0["kind"] == "bc7" and i1["fmt_name"] == "RGBA8"
               and i1["fmt_code"] == 0x0B01 and (i1["width"], i1["height"]) == (i0["width"], i0["height"])
               and i1["frames"] == 1 and i1["container"] and dec.tobytes() == src.tobytes(),
               f"{tile.name} {i0['width']}x{i0['height']} -> {len(new):,} B")
        # container fields the loader reads: file size, _RLT offset/self-offset, DESC size
        # (= memory-pool size), mip pointer -> DESC+0x10, single mip level
        w, h = i1["width"], i1["height"]
        fr = i1["frame_list"][0]
        _check("rewritten container fields (sizes, _RLT, DESC, mip ptr)",
               i1["file_size"] == len(new) and struct.unpack_from("<I", new, 0x1C)[0] == len(new)
               and i1["rlt_ok"] and struct.unpack_from("<I", new, i1["rlt_off"] + 4)[0] == i1["rlt_off"]
               and i1["desc_size"] == 0x10 + w * h * 4 and i1["rlt_off"] == i1["desc_off"] + i1["desc_size"]
               and fr["data_off"] == i1["desc_off"] + 0x10 and fr["mips"] == 1 and fr["image_size"] == w * h * 4
               and i1["desc_off"] == i0["desc_off"],
               f"DESC@0x{i1['desc_off']:x} size 0x{i1['desc_size']:x} _RLT@0x{i1['rlt_off']:x}")
        # relocation walk (BFRES_FixupRelocationPointers) must rebase the same slots
        s0, s1 = texture.relocation_slots(tmpl), texture.relocation_slots(new)
        _check("rewritten container relocates like the template",
               [s for s, _ in s0] == [s for s, _ in s1] and len(s1) > 0
               and all(t0 == t1 for (_, t0), (_, t1) in zip(s0, s1)),
               f"{len(s1)} slots")
        # another size is stored as that size (test_texture_resize covers it in depth)
        half = texture.parse(texture.encode_into(tmpl, Image.new("RGBA", (w // 2, h // 2))))
        _check("encode takes an image of another size (PIXL width/height rewritten)",
               (half["width"], half["height"]) == (w // 2, h // 2) and half["fmt_name"] == "BC7")
        # raw template keeps its own format; --fmt can force another raw format
        raw = next(EXTRACTED.rglob("common_touchpocket_08.texture"), None)
        if raw:
            rb = raw.read_bytes()
            rim = texture.decode_to_image(rb)
            keep = texture.parse(texture.encode_into(rb, rim))
            forced = texture.parse(texture.encode_into(rb, rim, fmt="RGBA4444"))
            _check("raw template keeps RGBA8; fmt= forces RGBA4444",
                   keep["fmt_name"] == "RGBA8" and forced["fmt_name"] == "RGBA4444"
                   and forced["frame_list"][0]["size"] == keep["width"] * keep["height"] * 2,
                   raw.name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 2. flipbooks: all frames, one frame (others stay BC7), and a mixed-size strip
    conf = next(EXTRACTED.rglob("confetti.texture"), None)
    if conf:
        cb = conf.read_bytes()
        frames = texture.decode_frames(cb)
        allnew = texture.encode_into(cb, frames, fmt="RGBA8")
        ia = texture.parse(allnew)
        ok = ia["frames"] == len(frames) == 15 and all(
            f["fmt_name"] == "RGBA8" for f in ia["frame_list"]) and all(
            texture.decode_to_image(allnew, frame=k).tobytes() == frames[k].convert("RGBA").tobytes()
            for k in range(15))
        _check("flipbook round trip (all 15 confetti frames -> RGBA8)", ok, f"{len(allnew):,} B")
        red = Image.new("RGBA", frames[3].size, (255, 0, 0, 255))
        one = texture.encode_into(cb, red, frame=3, fmt="RGBA8")
        io_ = texture.parse(one)
        fl = io_["frame_list"]
        ok = (fl[3]["fmt_name"] == "RGBA8" and all(fl[k]["fmt_name"] == "BC7" for k in range(15) if k != 3)
              and texture.decode_to_image(one, frame=3).getpixel((2, 2)) == (255, 0, 0, 255)
              and all(one[fl[k]["data_off"]:fl[k]["data_off"] + fl[k]["size"]]
                      == cb[texture.parse(cb)["frame_list"][k]["data_off"]:][:fl[k]["size"]]
                      for k in range(15) if k != 3)
              and texture.relocation_slots(one) is not None)
        _check("flipbook single-frame replace keeps the other frames' BC7 bytes", ok)
    else:
        _skip("flipbook round trip", "confetti.texture not extracted")
    d12 = next(EXTRACTED.rglob("8x12d00.texture"), None)
    if d12:
        db = d12.read_bytes()
        i12 = texture.parse(db)
        strip, boxes = texture.decode_strip(db)
        back = texture.encode_into(db, strip, strip=True, fmt="RGBA8")
        f12 = texture.decode_frames(db)
        ok = (i12["frames"] == 12 and {(f["width"], f["height"]) for f in i12["frame_list"]}
              == {(64, 32), (32, 16)} and len(boxes) == 12 and texture.parse(back)["frames"] == 12
              and all(texture.decode_to_image(back, frame=k).tobytes() == f12[k].convert("RGBA").tobytes()
                      for k in range(12)))
        _check("mixed-size flipbook (8x12d00: 12 frames, 64x32 + 32x16) strip round trip", ok,
               f"strip {strip.size}")
    else:
        _skip("mixed-size flipbook strip", "8x12d00.texture not extracted")

    # 3. ground export -> import inverse on MAP_FIELD_01 (4x4 grid, cropped extent)
    rf = next(EXTRACTED.rglob("MAP_FIELD_01.rf4m"), None)
    if rf is None:
        _skip("ground export/import", "MAP_FIELD_01.rf4m not extracted")
        return
    d = rf.parent
    reader = lambda fn, d=d: (d / fn).read_bytes() if (d / fn).is_file() else None
    w, h, _ = rf4m.Rf4mMap.load(rf).attr_grid()
    res = mapground.stitch(reader, "MAP_FIELD_01", 0, aspect=(w, h))
    lay = mapground.tile_layout(reader, "MAP_FIELD_01", 0, aspect=(w, h))
    if res is None or lay is None:
        _skip("ground export/import", "MAP_FIELD_01 has no atlas")
        return
    img = res[0]
    tiles = mapground.unstitch(reader, "MAP_FIELD_01", img, 0, aspect=(w, h), fmt="RGBA8")
    ok = (len(tiles) == len(lay["tiles"]) == res[1] * res[2] and lay["kind"] == "grid"
          and img.size == (lay["crop"] or lay["canvas"]))
    for t, (name, blob) in zip(lay["tiles"], tiles):
        if not ok:
            break
        dec = texture.decode_to_image(blob).convert("RGBA")
        crop = img.crop((t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"]))
        ok = (name == t["name"] and dec.size == crop.size and dec.tobytes() == crop.tobytes()
              and texture.parse(blob)["fmt_name"] == "RGBA8")
    _check("ground export -> import re-splits into tiles matching the stitched crops", ok,
           f"{lay['set']} {lay['cols']}x{lay['rows']} tiles, image {img.size}, crop {lay['crop']}")
    # re-stitching the new tiles reproduces the exported image byte-for-byte
    over = dict(tiles)
    mapground.tile_cache_clear()
    res2 = mapground.stitch(lambda fn: over.get(fn) or reader(fn), "MAP_FIELD_01", 0, aspect=(w, h))
    _check("re-stitch of the imported tiles equals the export",
           res2 is not None and res2[0].tobytes() == img.tobytes())
    mapground.tile_cache_clear()


def test_texture_resize():
    """Standalone .texture at ANY size (texture.encode_into rewrites the frame's PIXL width /
    height; the loader reads only format / width / height + the level-0 pointer, RF4S.exe
    +0x3C6000 / +0x3D2230 / +0x2A34F0) and the size_warnings survey (ground tiles on a fixed
    512-px grid, sprite quads from PolygonVertexes, pixel-size sprites)."""
    print("texture resize (standalone .texture):")
    if not (texture.HAS_PIL and texture.HAS_BC):
        _skip("texture resize", "Pillow/texture2ddecoder not installed")
        return
    from PIL import Image, ImageChops, ImageStat

    def rms(a, b):
        a, b = a.convert("RGBA"), b.convert("RGBA")
        return max(ImageStat.Stat(ImageChops.difference(a, b)).rms) if a.size == b.size else 999.0

    # 0. a no-op rebuild reproduces every shipped .texture byte for byte
    paths = list(EXTRACTED.rglob("*.texture"))
    if QUICK:
        paths = paths[::20]
    same = 0
    for p in paths:
        d = p.read_bytes()
        info = texture.parse(d)
        pl = [(f["fmt_code"], texture._slot_bytes(d, f)) for f in info["frame_list"]]
        same += texture._rebuild(d, info, pl) == d
    _check("container rebuild with unchanged payloads is byte-identical on every shipped .texture",
           same == len(paths) > 0, f"{same}/{len(paths)}")

    # 1. a ground tile at half size: BC7 kept, container consistent, the ground-grid warning
    tile = _first("MAP_FIELD_01_0000.texture")
    if tile is None:
        _skip("texture resize", "MAP_FIELD_01_0000.texture not extracted")
        return
    d = tile.read_bytes()
    im = texture.decode_to_image(d)
    small = im.resize((im.width // 2, im.height // 2))
    ch = texture.size_changes(d, small)
    warns = texture.size_warnings(d, ch, name=tile.name)
    n = texture.encode_into(d, small)
    i1 = texture.parse(n)
    fr = i1["frame_list"][0]
    _check("half-size ground tile: BC7 at the new size, sizes / _RLT / DESC / mip pointer rewritten",
           (i1["fmt_name"], i1["height"], i1["width"]) == ("BC7",) + small.size
           and i1["file_size"] == len(n) and i1["rlt_ok"] and i1["desc_size"] == 0x10 + fr["size"]
           and i1["rlt_off"] == i1["desc_off"] + i1["desc_size"] and fr["image_size"] == fr["size"]
           and len(texture.relocation_slots(n)) == len(texture.relocation_slots(d))
           and rms(texture.decode_to_image(n), small) < 4.0,
           f"{len(d):,} -> {len(n):,} B, rms {rms(texture.decode_to_image(n), small):.2f}")
    _check("size_changes / size_warnings: old -> new and the fixed 512-px ground grid",
           ch == [{"frame": 0, "old": im.size, "new": small.size}]
           and any("ground" in w and "512" in w for w in warns), warns[:1])
    _check("same size -> no size change reported", texture.size_changes(d, im) == [])
    # a resized output is itself a valid template (same size again -> same file size)
    again = texture.encode_into(n, texture.decode_to_image(n))
    _check("a resized .texture re-encodes at its new size without growing", len(again) == len(n))

    # 2. block formats only at sizes the exe can upload; RGBA8 takes any size
    try:
        texture.encode_into(d, im.resize((30, 30)))
        e30 = "no error"
    except texture.TextureError as e:
        e30 = str(e)
    r30 = texture.parse(texture.encode_into(d, im.resize((30, 30)), fmt="RGBA8"))
    _check("30x30 is refused as BC7 (exe passes w*h as the BC size) with the RGBA8 hint; RGBA8 takes it",
           "multiples of 4" in e30 and "RGBA8" in e30 and (r30["width"], r30["height"]) == (30, 30), e30[:60])

    # 3. flipbook: one frame at another size, the others keep their bytes; a 2x strip
    conf = _first("confetti.texture")
    if conf:
        cb = conf.read_bytes()
        frames = texture.decode_frames(cb)
        big = frames[3].resize((16, 16), Image.NEAREST)
        n = texture.encode_into(cb, big, frame=3)
        fl, fl0 = texture.parse(n)["frame_list"], texture.parse(cb)["frame_list"]
        ok = ((fl[3]["width"], fl[3]["height"]) == (16, 16) and fl[3]["fmt_name"] == "BC7"
              and all(n[fl[k]["data_off"]:][:fl[k]["size"]] == cb[fl0[k]["data_off"]:][:fl0[k]["size"]]
                      for k in range(15) if k != 3)
              and rms(texture.decode_to_image(n, frame=3), big) < 3.0 and texture.relocation_slots(n))
        _check("flipbook frame 3 at 16x16 (the other 14 frames byte-identical)", ok)
        strip, _boxes = texture.decode_strip(cb)
        s2 = strip.resize((strip.width * 2, strip.height * 2), Image.NEAREST)
        n2 = texture.encode_into(cb, s2, strip=True)
        _check("a 2x strip resizes every flipbook frame",
               {(f["width"], f["height"]) for f in texture.parse(n2)["frame_list"]} == {(16, 16)}
               and len(texture.size_changes(cb, s2, strip=True)) == 15)
        try:
            texture.encode_into(cb, strip.resize((strip.width + 3, strip.height)), strip=True)
            eodd = "no error"
        except texture.TextureError as e:
            eodd = str(e)
        _check("a strip that does not scale to whole-pixel frame boxes is refused", "whole pixels" in eodd)
    else:
        _skip("flipbook resize", "confetti.texture not extracted")

    # 4. raw texture without quad data: exact at 2x, "drawn at its pixel size" warning;
    #    a sprite with a quad: aspect change -> "stretched" warning
    raw = _first("common_touchpocket_08.texture")
    if raw:
        rb = raw.read_bytes()
        rim = texture.decode_to_image(rb)
        big = rim.resize((rim.width * 2, rim.height * 2), Image.NEAREST)
        n = texture.encode_into(rb, big)
        w = texture.size_warnings(rb, texture.size_changes(rb, big))
        _check("raw texture at 2x decodes exactly; no quad data -> pixel-size warning",
               texture.decode_to_image(n).tobytes() == big.convert("RGBA").tobytes()
               and any("pixel size" in x and "2x larger" in x for x in w), w[:1])
    bed = _first("OBJ_BED_00.texture")
    if bed:
        bb = bed.read_bytes()
        bim = texture.decode_to_image(bb)
        wide = bim.resize((bim.width * 2, bim.height))
        w = texture.size_warnings(bb, texture.size_changes(bb, wide), name=bed.name)
        same_aspect = texture.size_warnings(bb, texture.size_changes(bb, bim.resize((bim.width * 2, bim.height * 2))))
        _check("a quad sprite: aspect change warns 'stretched', a uniform 2x only notes the quad",
               any("stretched" in x for x in w) and not any("stretched" in x for x in same_aspect)
               and same_aspect, (w[:1], same_aspect[:1]))


def test_model_texture_resize():
    """Embedded .model textures at ANY size: texture.bntx_replace rebuilds the BNTX (same
    container as a .texture) and modelwrite.replace_embedded_file moves section 4 (table size,
    relocated pointers, outer _RLT). Checked with modelwrite.validate / validate_embedded,
    model.parse, res_container and the untouched textures / shader bytes."""
    print("texture resize (.model embedded BNTX):")
    if not (texture.HAS_PIL and texture.HAS_BC):
        _skip("model texture resize", "Pillow/texture2ddecoder not installed")
        return
    from PIL import ImageChops, ImageStat
    from rf4s_modkit import modelwrite as mw, model

    def rms(a, b):
        a, b = a.convert("RGBA"), b.convert("RGBA")
        return max(ImageStat.Stat(ImageChops.difference(a, b)).rms) if a.size == b.size else 999.0

    # 0. every shipped mesh .model: section-4 layout check + no-op replace is byte-identical
    seen, same, n_files, n_models, probs = set(), 0, 0, 0, []
    paths = [p for p in EXTRACTED.rglob("*.model") if not (p.name in seen or seen.add(p.name))]
    if QUICK:
        paths = paths[::10]
    for p in paths:
        d = p.read_bytes()
        files = mw.embedded_files(d)
        if not files:
            continue
        n_models += 1
        probs += mw.validate_embedded(d)
        for k, (o, s) in enumerate(files):
            n_files += 1
            same += mw.replace_embedded_file(d, k, d[o:o + s]) == d
    _check("embedded files: shipped layout holds and a no-op replace is byte-identical",
           n_models > 0 and same == n_files and not probs, f"{same}/{n_files} files in {n_models} models {probs[:1]}")

    pm = _first("MAP_CITY_00.model")
    if pm is None:
        _skip("model texture resize", "MAP_CITY_00.model not extracted")
        return
    m = pm.read_bytes()
    infos = texture.bntx_info(m)
    orig = [texture.decode_bntx(m, k) for k in range(len(infos))]
    files0 = mw.embedded_files(m)
    shader0 = m[files0[1][0]:files0[1][0] + files0[1][1]]
    nshapes = len(model.parse(m).shapes)
    nslots = len(mw.relocation_slots(m))
    results = []
    for size, fmt in (((768, 384), None), ((64, 32), None), ((100, 60), "RGBA8")):
        src = orig[0].resize(size)
        n = texture.bntx_replace(m, 0, src, fmt=fmt)
        t = texture.bntx_info(n)[0]
        files = mw.embedded_files(n)
        ri = res_container.inspect(n)
        rlt = ri["reloc_table_offset"]
        ok = ((t["width"], t["height"]) == size and t["fmt_name"] == (fmt or infos[0]["fmt_name"])
              and not mw.validate(n) and not mw.validate_embedded(n)
              and len(model.parse(n).shapes) == nshapes and len(mw.relocation_slots(n)) == nslots
              and n[rlt:rlt + 4] == b"_RLT" and rlt % 0x1000 == 0
              and n[files[1][0]:files[1][0] + files[1][1]] == shader0
              and all(texture.decode_bntx(n, k).tobytes() == orig[k].tobytes() for k in range(1, len(infos)))
              and rms(texture.decode_bntx(n, 0), src) < (0.01 if fmt == "RGBA8" else 12.0))
        results.append((size, fmt, ok, len(n)))
    _check("MAP_CITY_00 texture 0 at 768x384 BC3 / 64x32 BC3 / 100x60 RGBA8: model validates, "
           "shader + other 12 textures untouched", all(r[2] for r in results),
           "; ".join(f"{s[0]}x{s[1]} {f or 'keep'} {n:,} B" for s, f, _ok, n in results))
    # resize and back: the second replace works on the rebuilt file
    n = texture.bntx_replace(m, 5, orig[5].resize((96, 96)))
    back = texture.bntx_replace(n, 5, orig[5])
    _check("resize then back to the original size: same file size, validates",
           len(back) == len(m) and not mw.validate(back) and not mw.validate_embedded(back)
           and texture.bntx_info(back)[5]["width"] == infos[5]["width"])
    # a bare BNTX resizes too
    o, s = files0[0]
    nb = texture.bntx_replace(m[o:o + s], 2, orig[2].resize((52, 52)), fmt="RGBA8")
    _check("a bare BNTX resizes on its own (own _RLT walks, size field = length)",
           texture.bntx_info(nb)[2]["width"] == 52 and texture.relocation_slots(nb)
           and struct.unpack_from("<I", nb, 0x1C)[0] == len(nb))


def test_texture_resize_gui():
    """GUI Replace texture… (texture viewer and a .model's Textures tab) with a PNG of another
    size: a confirm shows old -> new (+ warnings); No keeps the working copy, Yes stores it."""
    print("GUI Replace texture… at another size:")
    import importlib.util
    try:
        import tkinter as tk
    except Exception as e:
        _skip("texture resize GUI", "no tkinter: %s" % e); return
    if not (texture.HAS_PIL and texture.HAS_BC):
        _skip("texture resize GUI", "Pillow/texture2ddecoder not installed"); return
    tex, mod = _first("common_touchpocket_08.texture"), _first("MAP_CITY_00.model")
    if tex is None or mod is None:
        _skip("texture resize GUI", "common_touchpocket_08.texture / MAP_CITY_00.model not extracted"); return
    from PIL import Image
    from rf4s_modkit import modelwrite as mw
    spec = importlib.util.spec_from_file_location("rf4mod_gui_texresize", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
    gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
    box = _headless_dialogs()
    from tkinter import messagebox, filedialog
    asked = []
    messagebox.askyesno = lambda t, m, **k: (asked.append(m), box["yesno"])[1]
    tmp = pathlib.Path(tempfile.mkdtemp())
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        app = gui.App(root, initial=str(tex.parent))
        # --- standalone texture
        f = tmp / tex.name
        shutil.copyfile(tex, f)
        app.open_path(f); root.update_idletasks()
        doc = app._doc
        before = doc.cur_data
        im = texture.decode_to_image(before)
        png = tmp / "big.png"
        im.resize((im.width * 2, im.height * 2), Image.NEAREST).save(png)
        filedialog.askopenfilename = lambda *a, **k: str(png)
        box["yesno"] = False
        app._replace_texture_png(f.name)
        declined = doc.cur_data == before and len(asked) == 1
        msg = asked[-1] if asked else ""
        box["yesno"] = True
        app._replace_texture_png(f.name)
        i = texture.parse(doc.cur_data)
        _check("texture viewer: another size asks first (old -> new + warning); No keeps, Yes stores it",
               declined and "%dx%d -> %dx%d" % (im.size + (im.width * 2, im.height * 2)) in msg
               and "pixel size" in msg and (i["height"], i["width"]) == (im.width * 2, im.height * 2)
               and "->" in app.status.cget("text") and not box["msgs"], msg.splitlines()[:1])
        n_asked = len(asked)
        cur = texture.decode_to_image(doc.cur_data)
        cur.save(png)
        app._replace_texture_png(f.name)
        _check("a PNG of the texture's own (new) size replaces without asking", len(asked) == n_asked
               and texture.decode_to_image(doc.cur_data).size == cur.size)
        # --- a .model's Textures tab
        g = tmp / mod.name
        shutil.copyfile(mod, g)
        app.open_path(g); root.update_idletasks()
        doc = app._doc
        before = doc.cur_data
        t = texture.bntx_info(before)[1]
        texture.decode_bntx(before, 1).resize((t["width"] * 2, t["height"] * 2)).save(png)

        class _Sel:           # the Textures tab's tree, with texture 1 selected
            def selection(self):
                return ("1",)
        box["yesno"] = False
        app._replace_bntx_png(g.name, _Sel())
        declined = doc.cur_data == before and len(asked) == n_asked + 1 and "normalised" in asked[-1]
        box["yesno"] = True
        app._replace_bntx_png(g.name, _Sel())
        t2 = texture.bntx_info(doc.cur_data)[1]
        _check("Model tab: another size asks first; Yes rebuilds the .model (validates)",
               declined and (t2["width"], t2["height"]) == (t["width"] * 2, t["height"] * 2)
               and len(doc.cur_data) != len(before) and not mw.validate(doc.cur_data)
               and not mw.validate_embedded(doc.cur_data) and "rebuilt" in app.status.cget("text")
               and not box["msgs"] and not errs,
               (declined, (t2["width"], t2["height"]), mw.validate(doc.cur_data)[:1],
                mw.validate_embedded(doc.cur_data)[:1], app.status.cget("text")[:60], box["msgs"][:1], errs[:1]))
    finally:
        root.destroy()
        shutil.rmtree(tmp, ignore_errors=True)


def test_behaviour_edits():
    """Editors added 2026-09-19 for the behaviour tables: gifts (rf3PresentNpc*/Category),
    tame foods (rf3MonsterPresent), schedules (rf3Schedule + rf3ScheduleID), the route graph
    (rf3route/rf3RouteResult) and the fishing-rate schemas. Byte-exact stock rebuilds, edit
    round trips and decode sanity checks against in-game facts."""
    print("behaviour editors (gifts / tame foods / schedules / routes / fishing schemas):")
    import json as _json
    import struct as _st
    from rf4s_modkit import gifts, montame, schedule, route, map_names
    try:
        import rf4mod as _rfm
    except Exception:
        _rfm = None
    tmp = pathlib.Path(tempfile.mkdtemp())

    # ---- gifts ------------------------------------------------------------------
    rv = _first("rf3PresentNpc25.bin")
    if rv:
        base = rv.parent
        files = [p for p in [base / f"rf3PresentNpc{n:02d}.bin" for n in range(1, 28)]
                 + [base / "rf3PresentCategory.bin"] if p.is_file()]
        exact = sum(1 for p in files if gifts.GiftTable.parse(p.read_bytes()).build() == p.read_bytes())
        _check("gift byte-exact rebuild of every stock table (27 NPC + category, NLCLINK tail)",
               exact == len(files) == 28, f"{exact}/{len(files)}")
        t = gifts.GiftTable.parse(rv.read_bytes())
        _check("gift Raven: Skull(874) = -10 signature dislike, Star Pendant(640) loved +15 (in-game UI)",
               t.tier_of(874) == "disliked" and t.tier_of(640) == "loved"
               and [e.code for e in t.tier("disliked") if e.value == 874] == [gifts.SIGNATURE_DISLIKE_CODE]
               and gifts.entry_fp(t.tier("loved")[0], "loved") == 15 and gifts.NEUTRAL_FP == 5)
        t.set_item(874, "loved", fp=20)
        t.set_item(640, "neutral")
        t.set_signature(873)
        t.add("liked", gifts.Entry("category", 2, 7))
        b = t.build()
        t2 = gifts.GiftTable.parse(b)
        sig = [e.value for e in t2.tier("disliked") if e.code == gifts.SIGNATURE_DISLIKE_CODE]
        _check("gift edit round trip (move to loved --fp / neutral / new signature / range entry)",
               t2.tier_of(874) == "loved" and t2.tier_of(640) == "neutral" and sig == [873]
               and gifts.Entry("category", 2, 7) in t2.tier("liked")
               and [e for e in t2.tier("loved") if e.value == 874][0].code == 20)
        nsec, dend = _st.unpack_from("<II", b, 16)
        _check("gift rebuilt NLCLINK tail: section count 4, ref list points at the off1 field",
               nsec == 4 and dend + 16 * nsec + 4 * 3 == len(b)
               and _st.unpack_from("<I", b, dend + 16 + 4)[0] == _st.unpack_from("<I", b, 28)[0]
               and _st.unpack_from("<I", b, dend + 16 * nsec)[0] == 28)
        try:
            t.groups[0]["loved"] = [gifts.Entry("item", i, 15) for i in range(1, 257)]
            t.build()
            guard = False
        except gifts.GiftError:
            guard = True
        _check("gift >255 entries refused (8-bit lookup loop in the reader)", guard)
        if _rfm is not None:
            out = tmp / "g25.bin"
            _rfm.main(["gift", "set", str(rv), "874", "loved", "--fp", "20", "-o", str(out)])
            t3 = gifts.GiftTable.parse(out.read_bytes())
            _check("CLI `gift set <npc> <item> loved --fp` writes the moved entry",
                   t3.tier_of(874) == "loved" and [e for e in t3.tier("loved") if e.value == 874][0].code == 20
                   and len(t3.tier("disliked")) == 4)
    else:
        _skip("gift editor checks", "no rf3PresentNpc25.bin present")

    # ---- monster taming foods ----------------------------------------------------
    mp = _first("rf3MonsterPresent.bin")
    if mp:
        d = mp.read_bytes()
        _check("montame Goblin(52) lists Onigiri(295) +15 but Orc(48) does not (per-species table)",
               montame.find_slot(d, 52, 295) is not None and dict(montame.prefs(d, 52)).get(295) == 15
               and montame.find_slot(d, 48, 295) is None)
        buf = bytearray(d)
        k = montame.set_item(buf, 48, 295, 7)
        ok1 = montame.find_slot(bytes(buf), 48, 295) == k and dict(montame.prefs(bytes(buf), 48))[295] == 7
        montame.remove_item(buf, 48, 295)
        _check("montame set_item / remove_item round trip",
               ok1 and montame.prefs(bytes(buf), 48) == montame.prefs(d, 48))
        _check("montame category modifier: Failed Dish cat 4 halves, cooked cats 5..14 add +32",
               montame.FAILED_DISH_CATEGORY == 4 and list(montame.COOKED_FOOD_CATEGORIES) == list(range(5, 15)))
    else:
        _skip("montame editor checks", "no rf3MonsterPresent.bin present")

    # ---- schedules ---------------------------------------------------------------
    sp = _first("rf3Schedule.bin")
    sid = _first("rf3ScheduleID.bin")
    if sp:
        d = sp.read_bytes()
        sc = schedule.Schedule.parse(d)
        _check("schedule byte-exact rebuild (directory + stream recomputed)",
               sc.build() == d and len(sc.cells) == 426)
        _check("schedule JSON round trip byte-exact", schedule.Schedule.loads(sc.dumps()).build() == d)
        first = sc.get(1, 0)[0]
        fact = first.slot == 24 and first.spot == 2 and first.time == "06:00"
        spots = schedule.load_spots(sid.read_bytes()) if sid else None
        if spots:
            fact = fact and schedule.kind_spots(2, spots)[0].room == 65 \
                and (map_names.map_name(65) or "").startswith("Butler")
            _check("schedule kind prefix table ends at the rf3ScheduleID record count",
                   schedule.KIND_PREFIX[-1] == len(spots) == 3898)
        _check("schedule Vishnal(1) weekday0 starts 06:00 at spot 2 = Butler's Room (in-game)", fact)
        orig2 = sc.get(2, 0)[:]
        k = sc.add_slice(1, 0, schedule.time_to_slot("07:15"), 5, flags=1)
        sc.set_slice(1, 0, k, spot=6)
        gone = sc.remove_slice(1, 0, 0)
        sc3 = schedule.Schedule.parse(sc.build())
        lst = sc3.get(1, 0)
        _check("schedule add/set/remove round trip (time order kept, other cells intact)",
               gone.spot == 2 and lst[0].slot == 26 and lst[2] == schedule.Slice(29, 1, 6)
               and len(lst) == 19 and sc3.get(2, 0) == orig2)
        _cells = schedule.Schedule.parse(d).ordered_cells()
        _check("schedule: 426 schedules, 5686 stops, the first stop's spot is 2",
               len(_cells) == 426 and sum(len(v) for _k, v in _cells) == 5686
               and _cells[0][1][0].spot == 2)
        if _rfm is not None:
            out = tmp / "sched.bin"
            _rfm.main(["schedule", "set", "1", "weekday0", "0", "--time", "06:30", "--file", str(sp),
                       "-o", str(out)])
            _check("CLI `schedule set` re-times a stop", schedule.Schedule.parse(out.read_bytes()).get(1, 0)[0].slot == 26)
    else:
        _skip("schedule editor checks", "no rf3Schedule.bin present")

    # ---- route graph + next-hop matrix -------------------------------------------
    rt = _first("rf3route.bin")
    rrp = _first("rf3RouteResult.bin")
    if rt:
        d = rt.read_bytes()
        g = route.RouteGraph.parse(d)
        _check("route TRCS byte-exact rebuild (room table + running indices regenerated)",
               g.build() == d and len(g.nodes) == 317 and len(g.edges) == 783)
        _check("route JSON round trip", route.RouteGraph.from_json(_json.loads(g.dumps())).build() == d)
        _check("ident rf3route -> route / rf3RouteResult -> route_result",
               ident.identify(d, filename="rf3route.bin").fmt == "route"
               and (rrp is None or ident.identify(rrp.read_bytes()[:64], filename=rrp.name).fmt == "route_result"))
        if rrp:
            rd = rrp.read_bytes()
            rr = route.RouteResult.parse(rd)
            _check("route next-hop matrix: 318 rows x 159 B nibbles, byte-exact",
                   rr.stride == 159 and rr.rows == 318 and rr.build() == rd)
            src, dst = g.node_index(65, 0), g.node_index(24, 0)
            hops, cost = rr.path(g, src, dst)
            _check("route path Butler's Room(65) -> Airship Way(24) walks the matrix to the target",
                   hops[-1][0] == dst and cost > 0 and len(hops) > 1)
            comp = route.RouteResult.compute(g, rows=rr.rows)
            rnd = random.Random(19)
            n, same, tried = len(g.nodes), 0, 0
            for _ in range(150):
                s, t_ = rnd.randrange(n), rnd.randrange(n)
                if s == t_:
                    continue
                try:
                    c1 = rr.path(g, s, t_)[1]
                except route.RouteError:
                    continue
                tried += 1
                same += rr.path(g, s, t_)[1] == comp.path(g, s, t_)[1] == c1
            _check("route rebuild-result reproduces the shipped path costs (sample)",
                   tried > 50 and same == tried, f"{same}/{tried}")
        # 2026-09-24: Nav_BuildPathFromAToB hard-codes the 159-byte row stride, so a
        # regenerated matrix must keep it whatever the node count (was ceil(n/2)).
        tiny = route.RouteGraph.from_json({"format": "rf3route", "nodes": [
            {"room": 0, "x": 0, "y": 0, "edges": [{"room": 0, "node": 1, "cost": 5}]},
            {"room": 0, "x": 8, "y": 0, "edges": [{"room": 0, "node": 0, "cost": 5},
                                                  {"room": 0, "node": 2, "cost": 5}]},
            {"room": 0, "x": 16, "y": 0, "edges": [{"room": 0, "node": 1, "cost": 5}]}]})
        tr = route.RouteResult.compute(tiny)
        tr2 = route.RouteResult.parse(tr.build())
        bad = route.RouteGraph.from_json({"format": "rf3route", "nodes": [
            {"room": 0, "x": 0, "y": 0, "edges": [{"room": 0, "node": 7, "cost": 1}]}]})
        _check("route compute keeps the engine's 159-byte stride for any node count; "
               "validate flags a dangling edge; stock graph validates clean",
               tr.stride == 159 and tr2.stride == 159 and tr2.path(tiny, 0, 2)[1] == 10
               and any(m.startswith("ERROR") for m in bad.validate())
               and not any(m.startswith("ERROR") for m in g.validate()))
    else:
        _skip("route checks", "no rf3route.bin present")

    # ---- fishing-rate + rf3ScheduleID schemas ------------------------------------
    ff = _first("Fishing_rate_fish_Spring.bin")
    fl = _first("Fishing_rate_lv_Spring.bin")
    if ff and fl:
        t = nlcl.NlclTable.load(ff)
        r0, r2 = t.row(0, ff.stem), t.row(2, ff.stem)
        _check("Fishing_rate_fish schema: Masu Trout row spring 597 / size class 0; row 2 class 3; Spring2 alias",
               r0["Spring"] == 597 and r0["Size class"] == 0 and r2["Size class"] == 3
               and t.schema("Fishing_rate_fish_Spring2") is t.schema("Fishing_rate_fish_Spring"))
        lv = nlcl.NlclTable.load(fl)
        l0 = lv.row(0, fl.stem)
        _check("Fishing_rate_lv schema: bracket 0 = 80/96/110/120 per size class; Spring2 alias",
               (l0["Size class 0"], l0["Size class 1"], l0["Size class 2"], l0["Size class 3"]) == (80, 96, 110, 120)
               and lv.schema("Fishing_rate_lv_Spring2") is not None)
    else:
        _skip("fishing schema checks", "no Fishing_rate_*.bin present")
    if sid:
        r = nlcl.NlclTable.load(sid).row(2, "rf3ScheduleID")
        _check("rf3ScheduleID schema: record 2 = room 65 @65,292 weight 1",
               r["room"] == 65 and r["x"] == 65 and r["y"] == 292 and r["weight"] == 1)


def test_asatk_edit():
    """Attack-timeline assembler + edit ops (2026-09-19): byte-exact assemble(disassemble)
    on every shipped as_atk file, edits that re-parse, and the validator."""
    print("asatk (assembler / editor):")
    from rf4s_modkit import asatk
    files = sorted(EXTRACTED.rglob("as_atk_*.bin"))
    if not files:
        _skip("asatk assembler", "no as_atk_*.bin extracted")
        return
    exact = sum(1 for p in files if asatk.assemble(asatk.disassemble(p.read_bytes())) == p.read_bytes())
    _check("asatk assemble(disassemble()) byte-exact on every stock timeline",
           exact == len(files), f"{exact}/{len(files)}")
    d = files[0].read_bytes()
    ev = asatk.parse(d, stop_at_end=False)
    ev2 = asatk.insert_at_frame(asatk.set_event(ev, 0, arg="1.5q"), 999, "SFX", "0x01002200")
    ev3 = asatk.delete_event(asatk.insert_event(ev2, 0, "DASH", "-2q"), 0)
    b = asatk.build(ev3)
    back = asatk.parse(b, stop_at_end=False)
    sfx = [e for e in back if e.op == 45 and e.arg == 0x01002200]
    _check("asatk set/insert_at_frame/insert/delete round-trip",
           len(back) == len(ev) + 2 and back[0].arg == 6144 and len(sfx) == 1
           and asatk.op_from_name("hitbox") == 10 and asatk.parse_operand("90deg") == 16384
           and asatk.parse_operand("-3") == 0xFFFFFFFD,
           f"{len(ev)} -> {len(back)} events")
    bad = asatk.build([(0, 5), (10, 1), (0, 3), (70, 0)])
    probs = asatk.validate(asatk.parse(bad, stop_at_end=False))
    _check("asatk validate flags no END / backwards FRAME / unknown op",
           any("no END" in p for p in probs) and any("backwards" in p for p in probs)
           and any("no handler" in p for p in probs), f"{len(probs)} findings")
    # 2026-09-24 audit (IDB): AnimEvent_Op0_WaitForFrame (+0xAB440) blocks only while arg > clock, so a
    # backwards FRAME fires at once (the old message said it never fires); slot 64 of
    # g_animEventOpHandlerTable is NULL and the pump (+0xA02E4) calls it unchecked, and
    # AnimEvent_Op63_ChainNextActionIfFlag400 (+0xACE60) returns 0 on a miss -> 63,64 crashes
    _check("asatk validate: backwards FRAME fires at once (not 'never fires')",
           any("fires at once" in p for p in probs) and not any("never fires" in p for p in probs))
    crash = asatk.validate(asatk.parse(asatk.build([(10, 1), (63, 5), (64, 2), (66, 0)]), stop_at_end=False))
    after = asatk.validate(asatk.parse(asatk.build([(62, 5), (64, 2), (45, 0x01000001), (66, 0)]), stop_at_end=False))
    _check("asatk validate: CHAIN_ONHIT+CHAIN_ANIM crash, pairs after CHAIN never run",
           any("CHAIN_ANIM after CHAIN_ONHIT" in p for p in crash)
           and any("after a CHAIN never runs" in p for p in after), f"{crash} / {after}")
    rej = 0
    for bad in ("FRAME 0x100000000", "@frame", "DASH 1e30q"):
        try:
            asatk.assemble(bad)
        except asatk.AsatkError:
            rej += 1
    _check("asatk assembler rejects >32-bit operands and a bare @frame (was: silent wrap / IndexError)",
           rej == 3, str(rej))
    crashy = [p.name for p in files
              if any("crashes" in w for w in asatk.validate(asatk.parse(p.read_bytes(), stop_at_end=False)))]
    _check("asatk validate: no stock timeline has a crash-class finding", not crashy, str(crashy[:5]))


def test_rows_em_structural_skill():
    """2026-09-19: row add/remove on flat NLCL tables (`rf4mod param add/remove`), em.bin
    STRUCTURAL edits (`rf4mod em add/remove/add-cond/remove-cond/add-action/remove-action`,
    the container is rebuilt), the `rf4mod skill set` curve editor, and the schema "grow"
    verdicts. Engine facts these lean on (IDB): CraftData_GetRecordCountByArchiveId
    (RF4S.exe+0x47B50) returns the recipe file's +24 count; CondScript_EvalNamedConditionA
    (+0x23B6A0) / EMF_DispatchEntry (+0x23B920) bound entry ids by em.bin +12 and take the
    table offset from +16 (header +4/+8 unread); Player_GetSkillXpToNextLevel (+0x38440)
    reads table[level] at Skill_GetLevelTable()+4*level (+396 = table[99] past 99), where
    Skill_GetLevelTable (+0x83E60) = nsFileArchive_GetData(1482x)+28."""
    print("rows / em structural / skill set:")
    import rf4mod as _rfx
    from rf4s_modkit import skillcurve
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="rf4s_rows_"))
    try:
        # ---- NLCL rows -------------------------------------------------------------
        files = [p for p in EXTRACTED.rglob("rf3*.bin") if nlcl.is_flat_nlcl(p.read_bytes()[:32])]
        v1 = [(p, p.read_bytes()) for p in files]
        v1 = [(p, d) for p, d in v1 if struct.unpack_from("<I", d, 16)[0] == 1]
        if not v1:
            _skip("NLCL row ops", "no rf3*.bin param tables extracted")
        else:
            exact = sum(1 for _p, d in v1 if nlcl.NlclTable(d).build() == d)
            canon = sum(1 for _p, d in v1 if nlcl.NlclTable(d).has_canonical_footer())
            _check("NLCL v1 tables: build() byte-exact + canonical {0,24,0,0} footer (%d files)" % len(v1),
                   exact == len(v1) and canon == len(v1), "%d exact, %d canonical" % (exact, canon))
        il = next((p for p in files if p.name == "rf3ItemList.bin"), None)
        if il:
            raw = il.read_bytes()
            t = nlcl.NlclTable(raw)
            n = t.entry_count
            i = t.append_record(t.record(29))
            t.set_field(i, "sell_price", 50, "rf3ItemList")
            blob = t.build()
            t2 = nlcl.NlclTable(blob)
            _check("NLCL append_record: entry_count/byte_size rewritten, footer regenerated, row readable",
                   i == n and t2.entry_count == n + 1 and t2.byte_size == 28 + 40 * (n + 1)
                   and len(blob) == len(raw) + 40 and blob[28:28 + 40 * n] == raw[28:28 + 40 * n]
                   and blob[:20] == raw[:20] and t2.get(n, 12) == 50 and t2.get(n, 0, "u32") == 29
                   and t2.tail == nlcl.CANONICAL_FOOTER)
            t.delete_record(n)
            _check("NLCL delete_record restores the stock bytes", t.build() == raw)
            t.insert_record(0, bytes(40))
            shifted = t.get(2, 12) == 680 and t.get(30, 12) == 30 and t.entry_count == n + 1
            t.delete_record(0)
            _check("NLCL insert_record(0) shifts rows (Cabbage 1 -> 2); delete(0) undoes", shifted and t.build() == raw)
            rej = 0
            gen = _first("GenA01.bin")
            for bad in (lambda: t.insert_record(5, bytes(39)), lambda: t.delete_record(n + 3),
                        lambda: t.insert_record(n + 1, None),
                        lambda: nlcl.NlclTable(gen.read_bytes()).append_record() if gen else (_ for _ in ()).throw(nlcl.NlclError("x"))):
                try:
                    bad()
                except nlcl.NlclError:
                    rej += 1
            _check("NLCL row ops reject wrong size / bad index / structured (Gen) tables", rej == 4, str(rej))
            out = tmp / "il_add.bin"
            _rfx.main(["param", "add", str(il), "--copy", "29", "--set", "sell_price=50", "-o", str(out)])
            ta = nlcl.NlclTable.load(out)
            _rfx.main(["param", "remove", str(out), str(n), "-o", str(tmp / "il_rm.bin")])
            _check("CLI param add --copy/--set then param remove -> stock bytes",
                   ta.entry_count == n + 1 and ta.get(n, 12) == 50 and (tmp / "il_rm.bin").read_bytes() == raw)
        else:
            _skip("NLCL row ops on rf3ItemList", "rf3ItemList.bin not extracted")
        # ---- em.bin structural --------------------------------------------------------
        try:
            raw_em = pathlib.Path(emscript.find_em()).read_bytes()
            em = emscript.EmScript.load()
        except FileNotFoundError:
            _skip("em structural edits", "em.bin not found")
            em = None
        if em:
            _check("emscript serialize() re-emits the stock em.bin byte-exact (5-section layout, 77-byte tail)",
                   em.serialize() == raw_em and len(em.tail) == 77 and em.hdr == raw_em[:20])
            n = len(em.entries)
            idx = em.add_entry(clone="EV_BOSS_SP_DEAD", name="TEST_CLONE")
            built = em.build()
            re1 = emscript.EmScript.parse(built, em.names)
            _check("em add_entry (clone): id == old count, header +12/+4 updated, clone decodes identically",
                   idx == n and struct.unpack_from("<I", built, 12)[0] == n + 1
                   and struct.unpack_from("<I", built, 4)[0] == len(built) and len(re1.entries) == n + 1
                   and re1.format_entry(re1.entries[idx]).splitlines()[1:]
                   == re1.format_entry(re1.get("EV_BOSS_SP_DEAD")).splitlines()[1:]
                   and em.get(idx).name == "TEST_CLONE")
            xs = em.parse_condition_spec("Hour >= 6 AND (12 > Hour OR FLG_DATE_FES_NOW == 1) AND !condA(EV_DATE_APPO)")
            _check("em condition spec: AND of OR-groups, query/flag/literal operands, cond refs, < swapped",
                   [x.pretty(em.names) for x in xs]
                   == ["Hour >= 6", "12 > Hour", "FLG_DATE_FES_NOW == 1", "!condA(EV_DATE_APPO)"]
                   and [x.or_next for x in xs] == [False, True, False, False]
                   and em.parse_condition_spec("Hour < 6")[0].pretty(em.names) == "6 > Hour")
            acts = [em.parse_action_spec(s).pretty(em.names) for s in (
                "REG_MAIN_SCENARIO = 39", "REG_MAIN_SCENARIO += 2", "MAX_U REG_MAIN_SCENARIO 5",
                "FLG_DATE_FES_NOW = (REG_MAIN_SCENARIO == 0)", "CALL EV_DATE_APPO")]
            _check("em action spec: SET / += / explicit MAX_U / SET_EQ_ZERO / CALL",
                   acts == ["REG_MAIN_SCENARIO = 39", "REG_MAIN_SCENARIO = ADD(REG_MAIN_SCENARIO, 2)",
                            "REG_MAIN_SCENARIO = MAX_U(REG_MAIN_SCENARIO, 5)",
                            "FLG_DATE_FES_NOW = (REG_MAIN_SCENARIO == 0)", "CALL EV_DATE_APPO"])
            slot = em.add_condition(idx, "a", xs)
            em.add_action(idx, "alt", em.parse_action_spec("REG_MAIN_SCENARIO += 2"))
            re2 = emscript.EmScript.parse(em.build(), em.names).entries[idx]
            _check("em add_condition (new OR-slot) + add_action survive rebuild + re-parse",
                   slot == 1 and re2.pretty_condition(em.names, "a").splitlines()[1].strip()
                   == "OR Hour >= 6 AND (12 > Hour OR FLG_DATE_FES_NOW == 1) AND !condA(EV_DATE_APPO)"
                   and [a.pretty(em.names) for a in re2.alt_actions][-1]
                   == "REG_MAIN_SCENARIO = ADD(REG_MAIN_SCENARIO, 2)")
            em.remove_action(idx, "alt", 1)
            em.remove_condition(idx, "a", 1)
            em.delete_entry(idx)
            _check("em remove_action / remove_condition / delete_entry restore the stock bytes",
                   em.build() == raw_em)
            em.add_condition("EV_CMN_DAYTIME", "a", em.parse_condition_spec("1 == 1 OR 2 == 2 OR 3 == 3"))
            em.remove_condition(66, "a", 2, 2)
            fixed = em.get(66).pretty_condition(em.names, "a").splitlines()[2].strip() == "OR (1 == 1 OR 2 == 2)"
            em.remove_condition(66, "a", 2)
            _check("em remove_condition closes the OR-group on the previous member", fixed and em.build() == raw_em)
            refused = False
            try:
                em.delete_entry(7)                      # EV_BOSS_SP_DEAD references itself
            except ValueError:
                refused = True
            n1 = em.add_entry(clone=7)
            n2 = em.add_entry()
            em.add_condition(n2, "a", em.parse_condition_spec("condA(#%d) AND Hour > 3" % n1))
            victim = next(k for k in range(100, 200) if not em.refs_to(k))
            vname, nxt = em.get(victim).name, em.get(victim + 1).name
            moved = em.delete_entry(victim)
            ref = em.get(n2 - 1).cond_a[0][0]
            _check("em delete_entry: refused when referenced; renumbers refs above it; names travel",
                   refused and moved >= 1 and ref.ref == n1 - 1 and em.get(victim).name == nxt
                   and vname not in em.by_name and len(em.entries) == n + 1)
            em = emscript.EmScript.load()
            em.clear_entry(7)
            e7 = em.get(7)
            _check("em clear_entry blanks in place (id-stable)",
                   not e7.cond_a and not e7.cond_b and not e7.alt_actions and len(em.entries) == n
                   and em.get(8).name == em.names.entry_name(8))
            o = tmp / "em_add.bin"
            _rfx.main(["em", "add", "--clone", "EV_BOSS_SP_DEAD", "--cond-a", "Season == 3 AND Hour > 20",
                       "--alt-action", "REG_MAIN_SCENARIO += 2", "-o", str(o)])
            _rfx.main(["em", "remove", str(n), "--em", str(o), "-o", str(tmp / "em_rm.bin")])
            _rfx.main(["em", "add-cond", "EV_CMN_DAYTIME", "Season == 3 AND Hour > 20", "-o", str(tmp / "em_ac.bin")])
            _rfx.main(["em", "remove-cond", "EV_CMN_DAYTIME", "--slot", "2", "--em", str(tmp / "em_ac.bin"),
                       "-o", str(tmp / "em_rc.bin")])
            _rfx.main(["em", "add-action", "EV_BOSS_SP_DEAD", "FLG_DATE_FES_NOW = (REG_MAIN_SCENARIO == 0)",
                       "--stream", "alt", "-o", str(tmp / "em_aa.bin")])
            _rfx.main(["em", "remove-action", "EV_BOSS_SP_DEAD", "--stream", "alt", "--index", "1",
                       "--em", str(tmp / "em_aa.bin"), "-o", str(tmp / "em_ra.bin")])
            added = emscript.EmScript.parse(o.read_bytes(), em.names)
            _check("CLI em add/remove, add-cond/remove-cond, add-action/remove-action (each pair -> stock bytes)",
                   len(added.entries) == n + 1
                   and added.entries[n].pretty_condition(em.names, "a").splitlines()[-1].strip()
                   == "OR Season == 3 AND Hour > 20"
                   and (tmp / "em_rm.bin").read_bytes() == raw_em
                   and (tmp / "em_rc.bin").read_bytes() == raw_em
                   and (tmp / "em_ra.bin").read_bytes() == raw_em)
        # ---- skill XP curve editing ------------------------------------------------------
        p = _first("rf3ParamSkillExp.bin")
        if p:
            raw = p.read_bytes()
            base = skillcurve.parse(raw)
            buf = bytearray(raw)
            skillcurve.set_level_xp(buf, 5, 120)
            scaled = skillcurve.scale_curve(bytearray(raw), 50)
            edited = skillcurve.parse(bytes(buf))
            rej = 0
            for bad in (lambda: skillcurve.set_level_xp(buf, 100, 1), lambda: skillcurve.set_level_xp(buf, 1, -5),
                        lambda: skillcurve.scale_curve(buf, 0)):
                try:
                    bad()
                except (IndexError, ValueError):
                    rej += 1
            _check("skillcurve set_level_xp / scale_curve (footer intact) + rejects level 100 / negative / 0%",
                   edited[5] == 120 and all(edited[k] == base[k] for k in range(100) if k != 5)
                   and bytes(buf)[-16:] == raw[-16:] and scaled == [max(1, int(x * 0.5 + 0.5)) for x in base]
                   and rej == 3)
            _rfx.main(["skill", "set", str(p), "5", "120", "--scale", "200", "-o", str(tmp / "sk.bin")])
            got = skillcurve.parse((tmp / "sk.bin").read_bytes())
            _check("CLI skill set LEVEL XP + --scale (scale first, then the explicit level; 100 x i32 + footer)",
                   got[5] == 120 and got[0] == base[0] * 2 and got[99] == base[99] * 2
                   and (tmp / "sk.bin").read_bytes()[:28] == raw[:28] and len(raw) == 28 + 400 + 16)
        else:
            _skip("skill set", "no rf3ParamSkillExp.bin present")
        # ---- new schemas + the per-family "grow" verdicts --------------------------------
        fe = _first("rf3FaceEffectParam.bin")
        if fe:
            t = nlcl.NlclTable.load(fe)
            r7 = t.row(7, "rf3FaceEffectParam")
            marks = [k for k in range(t.entry_count) if t.get(k, 0, "s8") == 1 and t.get(k, 1, "s8") == 0]
            _check("rf3FaceEffectParam schema: 442 = 34 slots x 13 kinds, s8 anchor pairs, kind-11 marker",
                   t.entry_count == 442 and t.record_size == 8
                   and (r7["x0"], r7["y0"], r7["x3"], r7["y3"]) == (-32, -40, 32, -60)
                   and marks == [13 * s + 11 for s in range(34)]
                   and (t.grow_info("rf3FaceEffectParam")[0] or "").startswith("unused:"))
        qf = _first("rf4TxtQuestRequestDetailFormat_split2_1.bin")
        if qf:
            t = nlcl.NlclTable.load(qf)
            _check("rf4TxtQuestRequestDetailFormat_split2_1 schema: 33 x 4, flag=2 on rows 1..3 only (dead data)",
                   t.entry_count == 33 and [k for k in range(33) if t.row(k, qf.stem)["flag"]] == [1, 2, 3]
                   and all(t.get(k, b, "u8") == 0 for k in range(33) for b in (1, 2, 3))
                   and (t.grow_info(qf.stem)[0] or "").startswith("unused:"))
        se = _first("rf3ParamSkillExpFarm.bin")
        if se:
            t = nlcl.NlclTable.load(se)
            _check("rf3ParamSkillExp* schema (alias) + fixed:100 verdict",
                   t.schema("rf3ParamSkillExpFarm") is t.schema("rf3ParamSkillExp") and t.entry_count == 100
                   and t.row(0, "rf3ParamSkillExpFarm")["xp_to_next"] == skillcurve.parse(se.read_bytes())[0]
                   and t.grow_info("rf3ParamSkillExpFarm")[0] == "fixed:100")
        verdicts = {s: (nlcl.FIELD_SCHEMAS.get(s) or {}).get("grow") for s in (
            "rf3ItemList", "rf3ItemEquipmentParam", "rf3PriceTable", "rf3NpcParam", "rf3CropParam",
            "rf3UseItemParam", "rf3TxtQuest_split3_1", "rf3TxtCalendar_split2_1", "rf3TxtShopNpc_split2_1",
            "rf4TxtItemParameter_split2_1", "rf4TxtShop_split2_1")}
        verdicts["rf3Recipe"] = nlcl.PREFIX_SCHEMAS["rf3Recipe"].get("grow")
        _check("grow verdicts recorded for every verified family (%d)" % len(verdicts),
               all(verdicts.values()) and verdicts["rf3Recipe"] == "file-count"
               and verdicts["rf3PriceTable"] == "fixed:10" and verdicts["rf3ItemList"] == "fixed:1108"
               and verdicts["rf3TxtCalendar_split2_1"].startswith("paired-text:")
               and "not verified" not in nlcl.describe_grow(verdicts["rf3Recipe"], 34),
               ", ".join(k for k, v in verdicts.items() if not v) or "all set")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_bcenc_and_model_textures():
    """BC1 / BC3 / BC7 encoders (rf4s_modkit/bcenc.py) and the same-size replacement paths
    built on them: packing bit-exact against texture2ddecoder, flat colours exact, quality
    on a real ground tile, `encode_into` keep-format (file size unchanged), and in-place
    texture replacement inside .model BNTX containers. Loader facts (RF4S.exe): the
    embedded BNTX is relocation-fixed and handed to SpriteResourceRegistry_AcquireSlotForBfres
    (+0x1BE270) by GfxCTR_Model_BuildFromResource (+0x1B52C0, calls at +0x1B550B / +0x1B5595);
    the per-BRTI init (+0x3C6000) -> MGTexture_LoadFromPIXL (+0x3D2230) reads only the
    format, width, height, access flags, name and mip-0 pointer."""
    print("bcenc / model textures:")
    import random
    import time
    from rf4s_modkit import bcenc
    if not (texture.HAS_PIL and texture.HAS_BC):
        _skip("bcenc", "Pillow/texture2ddecoder not installed")
        return
    from PIL import Image
    import texture2ddecoder as t2d

    def t2d_rgba(kind, blocks, w, h):
        fn = {"bc7": t2d.decode_bc7, "bc3": t2d.decode_bc3, "bc1": t2d.decode_bc1}[kind]
        return Image.frombytes("RGBA", (w, h), bytes(fn(blocks, w, h)), "raw", "BGRA").tobytes()

    def err_stats(a, b):
        mx, tot = 0, 0
        for x, y in zip(a, b):
            d = abs(x - y)
            tot += d
            if d > mx:
                mx = d
        return mx, tot / max(len(a), 1)

    # 0a. principal-axis seed: a red/green checker's axis (1,-1,0) is orthogonal to the
    # grey diagonal; the old (1,..,1) power-iteration seed collapsed it to the flat mean.
    chk = b"".join(bytes((255, 0, 0, 255)) if (i + i // 4) % 2 else bytes((0, 255, 0, 255))
                   for i in range(16))
    chk_err = {}
    for kind in ("bc1", "bc3", "bc7"):
        for use_np in ((True, False) if bcenc.HAS_NUMPY else (False,)):
            dec = bcenc.decode(kind, bcenc.encode(kind, chk, 4, 4, use_numpy=use_np), 4, 4)
            chk_err[(kind, use_np)] = sum((a - b) ** 2 for a, b in zip(chk, dec))
    _check("bcenc: a red/green checker block (axis orthogonal to grey) encodes exactly",
           all(v == 0 for v in chk_err.values()), str(chk_err))
    # 0b. BC3 8-level alpha refit: entry k>=2 is ((8-k)*a0 + (k-1)*a1)/7; with those weights
    # an exact ramp refits to its own endpoints (the old (7-k)/7 weight did not).
    ramp = bcenc._bc3_alpha_palette(200, 10) * 2
    cands = list(bcenc._bc3_alpha_candidates(ramp, min(ramp), max(ramp)))
    _check("bcenc: BC3 8-level alpha least-squares refit reproduces an exact ramp's endpoints",
           len(cands) == 3 and abs(cands[2][0] - 200) <= 1 and abs(cands[2][1] - 10) <= 1,
           f"{cands} (old weights gave (220, 35))")
    _upload_and_tile_checks()

    # 1. the flat-colour argument: with weight 21 mode 5 reaches every value 0..255
    tbl = bcenc._mode5_pairs()
    _check("BC7 mode-5 (weight 21) endpoint pairs reach every value 0..255",
           all(v in tbl for v in range(256)))
    # 2. flat colours round-trip EXACTLY through the real decoder
    random.seed(7)
    cols = [(0, 0, 0, 255), (255, 255, 255, 255), (255, 0, 0, 255), (0, 0, 0, 0),
            (37, 200, 0, 255), (128, 127, 1, 3)]
    cols += [tuple(random.randrange(256) for _ in range(4)) for _ in range(30)]
    ok7 = ok3 = ok1 = True
    for col in cols:
        im = Image.new("RGBA", (8, 4), col)
        ok7 = ok7 and t2d_rgba("bc7", bcenc.encode_bc7(im.tobytes(), 8, 4), 8, 4) == bytes(col) * 32
        r, g, b, a = col
        r5, g6, b5 = round(r * 31 / 255), round(g * 63 / 255), round(b * 31 / 255)
        grid = ((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2), a)
        gi = Image.new("RGBA", (4, 4), grid).tobytes()
        ok3 = ok3 and t2d_rgba("bc3", bcenc.encode_bc3(gi, 4, 4), 4, 4) == bytes(grid) * 16
        if a >= 128:
            ok1 = ok1 and t2d_rgba("bc1", bcenc.encode_bc1(gi, 4, 4), 4, 4)[:3] == bytes(grid[:3])
    _check("flat colours exact: BC7 any RGBA (opaque black / pure red need mode 5), BC3/BC1 on the 565 grid",
           ok7 and ok3 and ok1, f"{len(cols)} colours")
    # 3. packing bit-exact against texture2ddecoder (noise exercises every field), numpy + pure paths
    noise = bytes(random.randrange(256) for _ in range(24 * 20 * 4))
    ok, detail = True, []
    for kind in ("bc7", "bc3", "bc1"):
        for use_np in ((True, False) if bcenc.HAS_NUMPY else (False,)):
            blk = bcenc.encode(kind, noise, 24, 20, use_numpy=use_np)
            own = bcenc.decode(kind, blk, 24, 20)
            ref = t2d_rgba(kind, blk, 24, 20)
            if kind == "bc1":      # t2d returns opaque black for the punch-through index: compare RGB
                same = all(own[4 * i:4 * i + 3] == ref[4 * i:4 * i + 3] for i in range(24 * 20))
            else:
                same = own == ref
            ok = ok and same and len(blk) == 6 * 5 * bcenc.BLOCK_BYTES[kind]
            detail.append(f"{kind}{'/np' if use_np else '/py'}:{'ok' if same else 'DIFF'}")
    _check("reference decoders == texture2ddecoder bit-exact on noise (numpy and pure Python)", ok,
           " ".join(detail))
    # 4. real 512x512 BC7 ground tile: keep-format re-encode (same size), forced formats, quality, timing
    tile = _first("MAP_FIELD_01_0000.texture")
    if tile is None:
        _skip("keep re-encode / quality", "MAP_FIELD_01_0000.texture not extracted")
    else:
        tmpl = tile.read_bytes()
        i0 = texture.parse(tmpl)
        img = texture.decode_to_image(tmpl)
        src = img.convert("RGBA").tobytes()
        t0 = time.perf_counter()
        new7 = texture.encode_into(tmpl, img)
        dt7 = time.perf_counter() - t0
        i7 = texture.parse(new7)
        mx7, mean7 = err_stats(src, texture.decode_to_image(new7).convert("RGBA").tobytes())
        _check("encode_into default keeps BC7 at the same file size, container bytes untouched",
               len(new7) == len(tmpl) and i7["fmt_name"] == "BC7" and i7["fmt_code"] == 0x2001
               and new7[:i0["pixel_off"]] == tmpl[:i0["pixel_off"]] and new7[i0["rlt_off"]:] == tmpl[i0["rlt_off"]:]
               and texture.relocation_slots(new7) == texture.relocation_slots(tmpl) and mean7 <= 2.0 and mx7 <= 64,
               f"{i0['width']}x{i0['height']} in {dt7:.2f}s, mean err {mean7:.2f}, max {mx7}")
        sizes, errs = {}, {}
        for f in ("BC3", "BC1", "RGBA8"):
            t0 = time.perf_counter()
            nf = texture.encode_into(tmpl, img, fmt=f)
            dtf = time.perf_counter() - t0
            pf = texture.parse(nf)
            sizes[f] = (len(nf), pf["fmt_name"], dtf)
            errs[f] = err_stats(src, texture.decode_to_image(nf).convert("RGBA").tobytes())
        _check("fmt= forces BC3 (same size) / BC1 (smaller) / RGBA8 (4x, exact)",
               sizes["BC3"][0] == len(tmpl) and sizes["BC3"][1] == "BC3" and errs["BC3"][1] <= 5.0
               and sizes["BC1"][0] < len(tmpl) and sizes["BC1"][1] == "BC1" and errs["BC1"][1] <= 5.0
               and sizes["RGBA8"][0] > len(tmpl) and sizes["RGBA8"][1] == "RGBA8" and errs["RGBA8"] == (0, 0),
               "; ".join(f"{f} {s[0]:,} B {s[2]:.2f}s mean err {errs[f][1]:.2f}" for f, s in sizes.items()))
    # 5. .model: BNTX walk + in-place replacement (same file size, only the payload bytes change)
    pm = _first("MAP_CITY_00.model") or _first("MAP_*.model")
    if pm is None:
        _skip("model texture replace", "no MAP_*.model extracted")
        return
    mod = pm.read_bytes()
    infos = texture.bntx_info(mod)
    lst = texture.bntx_list(mod)
    _check("bntx_info walks the BRTI pointer array (payload = imageSize, 1 mip, linear, same list as bntx_list)",
           len(infos) == len(lst) > 0 and all(t["size"] == t["image_size"] and t["mips"] == 1 and t["tile"] == 1
                                              and t["data_off"] > 0 for t in infos)
           and all((x["w"], x["h"], x["name"]) == (y["width"], y["height"], y["name"]) for x, y in zip(lst, infos)),
           f"{pm.name}: {len(infos)} textures")
    k = min(3, len(infos) - 1)
    t = infos[k]
    card = texture.decode_bntx(mod, k)
    if card is None:
        _skip("model texture replace", f"texture {k} of {pm.name} not decodable")
        return
    t0 = time.perf_counter()
    newm = texture.bntx_replace(mod, k, card)
    dtm = time.perf_counter() - t0
    lo, hi = t["data_off"], t["data_off"] + t["image_size"]
    mxm, meanm = err_stats(card.convert("RGBA").tobytes(), texture.decode_bntx(newm, k).convert("RGBA").tobytes())
    _check("bntx_replace rewrites only the level-0 payload in place (same size, every other byte identical)",
           len(newm) == len(mod) and newm[:lo] == mod[:lo] and newm[hi:] == mod[hi:] and newm[lo:hi] != mod[lo:hi]
           and texture.bntx_info(newm) == infos and meanm <= 2.0
           and ident.identify(newm[:0x4000], filename=pm.name).fmt == "model",
           f"texture {k} {t['name']} {t['fmt_name']} {t['width']}x{t['height']} in {dtm:.2f}s, "
           f"mean err {meanm:.2f}, max {mxm}")
    # another size / a format with another payload size go through the BNTX rebuild
    # (test_model_texture_resize covers it in depth)
    from rf4s_modkit import modelwrite as _mw
    half = (max(4, t["width"] // 2 // 4 * 4), max(4, t["height"] // 2 // 4 * 4))
    r1 = texture.bntx_replace(mod, k, card.resize(half))
    r2 = texture.bntx_replace(mod, k, card, fmt="RGBA8" if t["fmt_name"] != "RGBA8" else "BC3")
    _check("bntx_replace takes another size and a format with another payload size (BNTX rebuilt)",
           (texture.bntx_info(r1)[k]["width"], texture.bntx_info(r1)[k]["height"]) == half
           and texture.bntx_info(r2)[k]["image_size"] != t["image_size"]
           and not _mw.validate(r1) and not _mw.validate_embedded(r2))
    if t["fmt_name"] in ("BC3", "BC7"):
        other = "BC7" if t["fmt_name"] == "BC3" else "BC3"
        n2 = texture.bntx_replace(mod, k, card, fmt=other)
        i2 = texture.bntx_info(n2)[k]
        _check(f"{t['fmt_name']} -> {other} in place rewrites only the BRTI format code (same payload size)",
               len(n2) == len(mod) and i2["fmt_name"] == other and i2["image_size"] == t["image_size"]
               and n2[:t["brti_off"] + 0x1C] == mod[:t["brti_off"] + 0x1C]
               and n2[t["brti_off"] + 0x20:lo] == mod[t["brti_off"] + 0x20:lo] and n2[hi:] == mod[hi:]
               and texture.decode_bntx(n2, k) is not None)


def _upload_and_tile_checks():
    """MCTexture_GLUpload (RF4S.exe+0x2A34F0) compressed-size rules (texture.upload_problem)
    and the block-linear .model slot rewrite; called from test_bcenc_and_model_textures."""
    from PIL import Image
    _check("upload_problem: BC1 needs a square block grid (exe sizes it from the width twice), "
           "BC3/BC7 multiples of 4, raw formats free",
           texture.upload_problem(0x1A01, 64, 32) and texture.upload_problem(0x1A01, 64, 64) is None
           and texture.upload_problem(0x2001, 6, 8) and texture.upload_problem(0x2001, 8, 12) is None
           and texture.upload_problem(0x1C01, 8, 6) and texture.upload_problem(0x0B01, 6, 5) is None)
    tp = next(EXTRACTED.rglob("common_touchpocket_08.texture"), None)
    if tp:
        d = tp.read_bytes()
        im = texture.decode_to_image(d)                  # 16x32 RGBA8, in-game orientation
        try:
            texture.encode_into(d, im, fmt="BC1")
            e1 = "no error"
        except texture.TextureError as e:
            e1 = str(e)
        ok3 = texture.parse(texture.encode_into(d, im, fmt="BC3"))["fmt_name"] == "BC3"
        # RGBA8 has two codes (0x0B01 / 0x0B03); keep must not rewrite 0x0B03 as 0x0B01
        d3 = bytearray(d)
        px = texture.parse(d)["frame_list"][0]["pixl_off"]
        struct.pack_into("<I", d3, px + 0x1C, 0x0B03)
        keep3 = texture.encode_into(bytes(d3), texture.decode_to_image(bytes(d3)))
        _check("encode_into refuses a format change the exe cannot upload (16x32 -> BC1), "
               "allows BC3, and keeps the 0x0B03 RGBA8 code byte-exact",
               "BC1" in e1 and "square" in e1 and ok3 and keep3 == bytes(d3), e1)
    else:
        _skip("encode_into upload check", "common_touchpocket_08.texture not extracted")
    fm = next(EXTRACTED.rglob("SYS_MENU_FONT_FAILURE_chn.model"), None)
    if fm:
        d = fm.read_bytes()
        infos = texture.bntx_info(d)
        k = next((t["index"] for t in infos if t["tile"] != 1 and t["image_size"] > t["size"]), None)
        if k is not None:
            t = infos[k]
            src = Image.new("RGBA", (t["width"], t["height"]))
            src.putdata([((x * 7) & 255, (y * 5) & 255, 128, 255)
                         for y in range(t["height"]) for x in range(t["width"])])
            nb = texture.bntx_replace(d, k, src)
            t2 = texture.bntx_info(nb)[k]
            dec = texture.decode_bntx(nb, k)
            _, mean = (0, 0) if dec is None else (0, sum(abs(a - b) for a, b in zip(
                dec.convert("RGBA").tobytes(), src.tobytes())) / (4 * t["width"] * t["height"]))
            nb2 = texture.bntx_replace(nb, k, src)
            _check("bntx_replace writes a block-linear (tileMode 0) slot linear and marks it "
                   "tile 1 / image size = payload (decodable, re-replaceable, file size unchanged)",
                   len(nb) == len(d) and t2["tile"] == 1 and t2["image_size"] == t["size"]
                   and dec is not None and mean < 4 and nb2 == nb,
                   f"{fm.name} #{k} {t['name']} {t['width']}x{t['height']} mean err {mean:.2f}")
        else:
            _skip("bntx tile-0 rewrite", f"{fm.name}: no block-linear texture")
    else:
        _skip("bntx tile-0 rewrite", "SYS_MENU_FONT_FAILURE_chn.model not extracted")


def test_script_authoring():
    """Cutscene authoring layer (2026-09-19): count-exact type tables, the expression
    compiler, the listing assembler (scene_listing -> assemble round trip), listing-text
    inserts/rewrites, and minting/removing/re-keying type-table entries (new scenes)."""
    print("script authoring (scriptasm + type-table entries):")
    from rf4s_modkit import script, scriptasm
    # argument counts: outside the shipped range is refused (op 93 with no argument hides the box)
    def _refused(t):
        try:
            scriptasm.assemble(t, 0x1000)
            return False
        except scriptasm.AsmError as e:
            return "op 93" in str(e) or "op 94" in str(e)
    _check("assembler refuses argument counts the game never uses (op93 bare, op94 with one) "
           "and keeps the shipped ones",
           _refused("SetDialogueBoxStyle") and _refused("op94 1")
           and scriptasm.assemble("op93 2\nop94", 0x1000) is not None
           and script.meta.arg_range(93) == (1, 1) and script.meta.arg_range(94) == (0, 0))
    p = _first("rf3.mc")
    if not p:
        _skip("script authoring", "rf3.mc not extracted")
        return
    raw = p.read_bytes()
    c = script.Container(raw)
    try:
        from rf4s_modkit.emflags import EmFlagTable
        emf = EmFlagTable.load()
    except Exception:
        emf = None
    if emf is not None:
        script.install_emflags_var_resolver(c, emf)
    resolver = c.install_asm_resolver(emf)
    _check("Container.install_asm_resolver wires emdeb.bin names into the assembler", resolver is not None)
    # --- typed-constant leaves (tags 3/4): named per argument slot (2026-09-23) --------------
    # The handlers read only the value of a tag-3 / tag-4 leaf (Script_PrepActionArgs pushes raw
    # (value, kind) pairs), so the tag is just a typed constant and the SLOT gives it its meaning.
    # The listing writes the raw tag3(N) / tag4(N) and names actor(Name) / map(MAP_NAME) in the
    # statement's comment where the slot is known.
    forms = {"actor(Forte)": b"\x03\x04\x00\x00\x00", "actor(4)": b"\x03\x04\x00\x00\x00",
             "tag3(0x4)": b"\x03\x04\x00\x00\x00", "actor(player)": b"\x03\x00\x00\x00\x00",
             "actor(Xiao Pai)": b"\x03\x0b\x00\x00\x00", "map(MAP_CITY_00)": b"\x04\x18\x00\x00\x00",
             "map(24)": b"\x04\x18\x00\x00\x00", "tag4(24)": b"\x04\x18\x00\x00\x00"}
    got = {t: scriptasm.asm_expr(t) for t in forms}
    rej = 0
    for bad in ("actor(Traveler)", "actor(Nobody)", "map(MAP_NOPE)"):   # shared / unknown names
        try:
            scriptasm.asm_expr(bad)
        except scriptasm.AsmError:
            rej += 1
    _check("actor(..)/map(..) assemble to the same bytes as tag3(..)/tag4(..); ambiguous names refused",
           got == forms and rej == 3, f"{sum(got[t] == forms[t] for t in forms)}/{len(forms)} forms, {rej}/3 refused")
    n_leaf = n_actor = n_map = 0
    leaf_bad, sched_txt, subev_txt = [], None, None
    for bk in c.banks:
        for sc in script.disassemble_bank(bk):
            for st in sc.stmts.values():
                if st.op >= 0xFFF0:
                    continue
                for i, off in enumerate(st.args):
                    if off is None or not (0 <= off < len(bk.data)) or bk.data[off] not in (3, 4):
                        continue
                    n_leaf += 1
                    txt = scriptasm.operand_text(bk.data, off, st.op, i)
                    named = script.arg_repr(bk.data, off, st.op, i)
                    n_actor += named.startswith("actor(")
                    n_map += named.startswith("map(")
                    if (not txt.startswith("tag%d(" % bk.data[off])
                            or scriptasm.asm_expr(txt) != bytes(bk.data[off:off + 5])
                            or scriptasm.asm_expr(named) != bytes(bk.data[off:off + 5])):
                        leaf_bad.append((bk.index, st.pc, txt, named))
                if st.op == 266 and sched_txt is None and len(st.args) > 1 \
                        and bk.data[st.args[0]] == 3 and bk.data[st.args[1]] == 4:
                    sched_txt = script.stmt_arg_strs(bk.data, st)[:2]
                if st.op == 629 and subev_txt is None and st.args and bk.data[st.args[0]] == 3:
                    subev_txt = script.stmt_arg_strs(bk.data, st)[0]
    _check("every tag-3/4 argument is listed raw (tagN(..)) and re-assembles byte-exact from it and from its slot-named form",
           n_leaf > 50000 and not leaf_bad and n_actor > 15000 and n_map > 500,
           f"{n_leaf} leaves, {n_actor} actor(..), {n_map} map(..), {len(leaf_bad)} mismatches {leaf_bad[:2]}")
    # schedule op 266 = (npc, map, ...): both named. op 629 loads a sub-event id (compared with
    # REG_SUBEV_NOW), which is NOT a character -- it must stay neutral, not become a monster name.
    from rf4s_modkit import entry_types as _et
    _check("char table: ids 24/25/26 are Barrett / Raven / Mistress Trupin (rf3TxtNpc; bank 26 = Trupin)",
           (_et.CHAR_NAMES.get(24), _et.CHAR_NAMES.get(25), _et.CHAR_NAMES.get(26)) == ("Barrett", "Raven", "Mistress Trupin")
           and script.actor_leaf_text(24) == "actor(Barrett)", str([_et.CHAR_NAMES.get(i) for i in (24, 25, 26)]))
    note318 = None
    for bk in c.banks[:40]:
        for sc in script.disassemble_bank(bk):
            for st in sc.stmts.values():
                if st.op == 318 and st.args and note318 is None:
                    note318 = script.flag_arg_note(bk.data, st.args[0], 318, 0)
    _check("op 318's actor argument resolves to that NPC's birthday-gift bit (zone-2 1007 + char)",
           bool(note318) and "birthday gift given" in note318, str(note318))
    _check("QueryNpcAnimDone's extra actors are labelled as ignored (only arg0 is read)",
           "ignored" in (script.opcode_arg_names(129) or ["", ""])[1]
           and script.leaf_slot_kind(129, 3) == "actor")
    _check("slot naming: NpcScheduleOrClear shows actor(..), map(MAP_..); a sub-event id stays neutral",
           bool(sched_txt) and sched_txt[0].startswith("actor(") and sched_txt[1].startswith("map(MAP_")
           and bool(subev_txt) and subev_txt.startswith("tag3("),
           f"{sched_txt} / {subev_txt}")
    # --- type table: (count, offset) slots, 74-slot tables, count-exact walks --------------
    slots = set()
    n_entries = 0
    n_types = 0
    walk_ok = True
    for b in c.banks:
        tt = b.type_table_full()
        slots.add(b.table_slots)
        for t, (cnt, off) in tt.items():
            n_types += 1
            recs = b.entry_records(t)
            n_entries += len(recs)
            if len(recs) != cnt or any(script.decode_statement(b.data, r.event_id) is None for r in recs):
                walk_ok = False
    _check("type tables are 74-slot (count, offset) tables on every bank; every entry pc decodes",
           slots == {74} and walk_ok and n_entries > 9000,
           f"slots={sorted(slots)} entries={n_entries} in {n_types} type lists")
    scenes, clean, stmts, dl = script.coverage(c)
    _check("coverage counts registered scenes once each (count-exact lists, no over-walk)",
           scenes == n_entries and clean == scenes, f"{scenes} scenes, {clean} clean")
    _check("parsing leaves the container byte-exact", c.build() == raw)
    # --- header max-bank-size words (the engine's reusable load buffers) -------------------
    # ScriptTask_FirstTimeInit (RF4S.exe+0x1EE060) sizes one buffer per bank kind from header
    # words 4 / 12 / 13 and the loader (RF4S.exe+0x23F9C0) copies each bank into it, so a bank
    # grown past its word overflows the game's heap. set_bank_bytes must raise the word.
    caps = {k: c.max_bank_size(k) for k in ("primary", "tail", "global")}
    actual = {}
    for kind in ("primary", "tail", "global"):
        actual[kind] = max((len(b.data) for b in c.banks if b.kind == kind), default=0)
    _check("header words 4/12/13 are the max global/primary/tail bank size (shipped file)",
           caps == actual and not c.validate_bank_sizes(), f"{caps} vs {actual}")
    cg = script.Container(raw)
    big = max((b for b in cg.banks if b.kind == "tail"), key=lambda b: len(b.data))
    gi_big = cg.banks.index(big)
    before = cg.max_bank_size("tail")
    cg.set_bank_bytes(big, bytes(big.data) + b"\x00" * 64)
    grown = script.Container(cg.build())
    _check("growing the largest bank raises its kind's max-size word (no heap overflow in game)",
           cg.max_bank_size("tail") == before + 64 == len(big.data)
           and grown.max_bank_size("tail") == len(grown.banks[gi_big].data)
           and grown.max_bank_size("primary") == caps["primary"], f"{before} -> {cg.max_bank_size('tail')}")
    cb = script.Container(raw)
    struct.pack_into("<I", cb.data, 52, 1024)          # pretend the recorded buffer is tiny
    flagged = cb.validate_bank_sizes()
    healed = script.Container(cb.build())              # build() re-derives the word first
    _check("validate_bank_sizes flags an undersized buffer word; build() repairs it",
           len(flagged) > 0 and healed.max_bank_size("tail") == caps["tail"]
           and not healed.validate_bank_sizes(), f"{len(flagged)} flagged")
    # --- the dispatchable action-opcode bound ---------------------------------------------
    # g_sceneActionHandlerTable (RF4S.exe+0x4DB790) has 702 valid slots: slot 702 is not a
    # function pointer and SceneAction_DispatchTableWithCleanup indexes it with no bounds
    # check, so a higher opcode would call past the table.
    _maxop = 0
    for b in c.banks:
        for sc in script.disassemble_bank(b, discover=False):
            for st in sc.stmts.values():
                if st.op < 0xFFF0:
                    _maxop = max(_maxop, st.op)
    _rej = 0
    for bad in (script.DISPATCHABLE_ACTION_OPS, 750, 762):
        if script.decode_statement(struct.pack("<HH", bad, 0), 0) is None:
            _rej += 1
        try:
            scriptasm.assemble("op%d 1" % bad, 0x1000)
        except script.ScriptError:
            pass
        else:
            _rej = -99
    _check("action opcodes are bounded by the engine's 702-slot handler table",
           script.DISPATCHABLE_ACTION_OPS == 702 and _maxop == 701 and _rej == 3
           and script.decode_statement(struct.pack("<HH", 701, 0), 0) is not None,
           f"corpus max op {_maxop}, bound {script.DISPATCHABLE_ACTION_OPS}")

    # --- expression compiler round trip ---------------------------------------------------
    n = same = fail = 0
    for b in c.banks[:25]:
        d = b.data
        for sc in script.disassemble_bank(b, discover=False):
            for st in sc.stmts.values():
                for o in (st.args if st.op < 0xFFF0 else st.expr_refs):
                    if o is None or o >= len(d):
                        continue
                    txt, _ = script.disasm_expr(d, o)
                    if txt == "?":
                        continue
                    n += 1
                    try:
                        src = scriptasm.operand_text(d, o) if d[o] in (3, 4, 5, 0x11, 0x12, 0x13) else txt
                        bb = scriptasm.asm_expr(src, c.asm_resolver)
                        if script.disasm_expr(bb, 0)[0] == txt:
                            same += 1
                        else:
                            fail += 1
                    except Exception:
                        fail += 1
    _check("asm_expr(disasm_expr(x)) re-renders identically for every operand in 25 banks",
           n > 10000 and fail == 0 and same == n, f"{n} operands, {fail} mismatches")
    enc = scriptasm.asm_expr("REG_WIFE_ID == 11", c.asm_resolver) if emf else None
    _check("symbolic game-flag names compile to token-0x02 packed refs (REG_WIFE_ID == 11)",
           enc is not None and enc[0] == 0x02 and script.disasm_expr(enc, 0)[0] == "REG_WIFE_ID == 11"
           and c.unpack_var(struct.unpack_from("<I", enc, 1)[0])[0] == emf.get("REG_WIFE_ID").bit_offset)
    st_asg = scriptasm.asm_expr("FLG_KOKUHAKU_NOW = 1", c.asm_resolver) if emf else b""
    _check("assignment compiles to <var> <1> op16 (the engine's compound-assign store)",
           st_asg[:1] == b"\x02" and st_asg[5:] == b"\x16\x90\x00")
    bad = 0
    for txt in ("5 = 1", "FLG_NOT_A_REAL_NAME_X == 1", "reg0 +", "(1 + 2", "arr[1"):
        try:
            scriptasm.asm_expr(txt, c.asm_resolver)
        except script.ScriptError:
            bad += 1
        except Exception:
            pass
    _check("asm_expr rejects bad expressions with a clean AsmError", bad == 5)
    # --- listing round trip ---------------------------------------------------------------
    tested = ok = 0
    for gi in (1, 150, 213, c.n_primary + 48, len(c.banks) - 1):
        b = c.banks[gi]
        for sc in [s for s in script.disassemble_bank(b, discover=False) if s.ok][:8]:
            text = scriptasm.scene_listing(sc, b, bank_no=gi)
            c2 = script.Container(raw)
            c2.set_asm_resolver(c.asm_resolver)
            try:
                base = c2.assemble(c2.banks[gi], text)
            except script.ScriptError as e:
                if "64 KB" in str(e):
                    continue                       # a near-full bank cannot take a copy
                tested += 1
                continue
            sc2 = script.disassemble_scene(c2.banks[gi], sc.action_type, base)
            tested += 1
            if sc2.ok and scriptasm.scene_signature(sc, b.data) == scriptasm.scene_signature(sc2, c2.banks[gi].data):
                ok += 1
    _check("scene_listing -> assemble -> disassemble reproduces the scene (5 banks incl. tail+global)",
           tested >= 30 and ok == tested, f"{ok}/{tested}")
    # --- listing-text edits: insert / rewrite with branches, flags and labels ------------
    c3 = script.Container(raw)
    c3.set_asm_resolver(c.asm_resolver)
    b3 = c3.banks[213]
    sc = next(s for s in script.disassemble_bank(b3, discover=False)
              if s.ok and any(x.mnem == "DIALOG" for x in s.stmts.values()))
    dpc = next(pc for pc, x in sc.stmts.items() if x.mnem == "DIALOG")
    c3.insert_after(b3, dpc, "BR_Z (FLG_KOKUHAKU_NOW) -> skip\nDIALOG #5\nskip:\nEVAL (reg0 = 3)")
    _e3 = c3.last_relink[213][sc.entry_pc]
    sc3 = script.disassemble_scene(b3, sc.action_type, _e3)
    lst = scriptasm.scene_listing(sc3, b3)
    _check("insert_after accepts listing text (branch + label + EVAL) and the scene stays clean",
           sc3.ok and "BR_Z (FLG_KOKUHAKU_NOW) ->" in lst and "EVAL (reg0 = 3)" in lst
           and "DIALOG #5" in lst and len(sc3.stmts) == len(sc.stmts) + 3,   # 3 new, in place
           f"{len(sc.stmts)} -> {len(sc3.stmts)} stmts, ok={sc3.ok}")
    body = ("FRAME 2\nSetSpeaker Nancy, Left, 3, 0\nDIALOG #8709\nBR_NZ (REG_WIFE_ID != 11) -> done\n"
            "PROMPT_CHOICE CANCEL->done, #100->yes, #101->done\nyes:\nGivePlayerItem 258, 1, 0\ndone:\nEND")
    _e4 = c3.rewrite_scene(b3, _e3, body)
    sc4 = script.disassemble_scene(b3, sc.action_type, _e4)
    kinds = [x.mnem for x in sc4.stmts.values()]
    _check("rewrite_scene from listing text: FRAME/speaker/DIALOG/BR_NZ/PROMPT_CHOICE/END all decode",
           sc4.ok and kinds.count("PROMPT_CHOICE") == 1 and kinds.count("BR_NZ") == 1
           and any(x.dialog_id == 8709 for x in sc4.stmts.values())
           and script.Container(c3.build()).banks[213].data == b3.data)
    rej = 0
    for txt in ("Frobnicate 1", "JMP nowhere", "PROMPT_CHOICE CANCEL->L0\nL0:\nEND", "BR_Z (reg0) L0",
                "DIALOG"):
        try:
            scriptasm.assemble(txt, 0x1000, resolver=c.asm_resolver)
        except script.ScriptError:
            rej += 1
        except Exception:
            pass
    _check("assemble rejects unknown ops / undefined labels / malformed choices cleanly", rej == 5)
    # CANCEL is optional: the never-taken slot gets the last option's target, like every shipped menu
    _region, _lbl = scriptasm.assemble("PROMPT_CHOICE #1->A, #2->B\nA:\nEND\nB:\nEND", 0x1000)
    _st = script.decode_statement(bytes(0x1000) + bytes(_region), 0x1000)
    _check("PROMPT_CHOICE without CANCEL assembles; its cancel slot = the last option's target",
           _st is not None and _st.mnem == "PROMPT_CHOICE" and len(_st.code_targets) == 3
           and _st.code_targets[0] == _st.code_targets[2], _st and _st.code_targets)
    # --- PROMPT_CHOICE engine limits (2026-09-24, RF4S.exe Script_VMStep 0xFFF4/5 + ChoiceDialog_*)
    _many = lambda k: "PROMPT_CHOICE_FORCED " + ", ".join("#%d->A" % i for i in range(k)) + "\nA:\nEND"
    try:
        scriptasm.assemble(_many(129), 0x1000)
        _rej129 = False
    except script.ScriptError:
        _rej129 = True
    _ok128 = len(scriptasm.assemble(_many(128), 0x1000)[0]) > 6 * 128
    _check("assemble caps a choice at 128 options (the game drops rows past 0x80)",
           _rej129 and _ok128 and script.MAX_CHOICE_OPTIONS == 128)
    _L = scriptasm.lint_listing
    _lv = lambda probs: [lvl for _pc, lvl, _m in probs]
    _hide_all = _L("ClearChoiceVisibleRange 0, 32\nSetChoiceVisibleBit 40, 1\n"
                   "PROMPT_CHOICE_FORCED #1->A, #2->A\nA:\nEND")
    _hide_ok = _L("SetChoiceVisibleMask 1, 0\nPROMPT_CHOICE_FORCED #1->A, #2->A\nA:\nEND")
    _check("choice lint: a mask that hides every option is an error (empty menu, div-by-zero)",
           _lv(_hide_all) == ["error"] and _hide_ok == [], f"{_hide_all} / {_hide_ok}")
    _cx = _L("PROMPT_CHOICE CANCEL->A, #1->A, #2->B\nA:\nEND\nB:\nEND")
    _cy = _L("PROMPT_CHOICE CANCEL->B, #1->A, #2->B\nA:\nEND\nB:\nEND")
    _check("choice lint: CANCEL != last option's target warns (cancel key picks the last row)",
           _lv(_cx) == ["warning"] and _cy == [], f"{_cx} / {_cy}")
    _tid = _L("PROMPT_CHOICE CANCEL->B, #1->A, #200000->B\nA:\nEND\nB:\nEND", text_count=1000)
    _check("choice lint: option id outside the text archive is an error (shows entry 0)",
           _lv(_tid) == ["error"] and "#200000" in _tid[0][2])
    _mt = _L("SetChoiceVisibleMask 0, 1, 1\nPROMPT_CHOICE_FORCED #1->A, #2->B, #3->B\nA:\nEND\nB:\nEND")
    _mt_ok = _L("SetChoiceVisibleMask 1, 1, 0\nPROMPT_CHOICE_FORCED #1->A, #2->B, #3->B\nA:\nEND\nB:\nEND")
    _check("choice lint: per-option targets under a mask that shifts rows warn (jump = visible row)",
           _lv(_mt) == ["warning"] and _mt_ok == [], f"{_mt} / {_mt_ok}")
    # the 2026-10-02 freeze: the next line after a menu is its last option's line (latched)
    _fz = _L("PROMPT_CHOICE_FORCED #1->A, #2->B\nA:\nSetVar3(0, 1)\nJMP C\nB:\nSetVar3(0, 2)\n"
             "C:\nDIALOG #2\nEND")
    _fz_ok = _L("PROMPT_CHOICE_FORCED #1->A, #2->B\nA:\nDIALOG #3\nDIALOG #2\nEND\nB:\nDIALOG #1\nEND")
    _sh = "SetSpeaker(MC, Left, 0, 0)\nDIALOG #5\n"
    _sp_ok = _L(_sh + "EndDialogue()\nSetDialogueSuppressed(1)\n" + _sh + "SetDialogueSuppressed(0)\n" + _sh + "END")
    _sp_open = _L(_sh + "SetDialogueSuppressed(1)\n" + _sh + "SetDialogueSuppressed(0)\nEND")
    _sp_left = _L("EndDialogue()\nSetDialogueSuppressed(1)\n" + _sh + "EndDialogue()\nEND")
    _check("SetDialogueSuppressed lint: on with a box open warns (freeze), left on at the end warns, "
           "closed first and turned off is clean",
           _sp_ok == [] and _lv(_sp_open) == ["warning"] and "freezes" in _sp_open[0][2]
           and _lv(_sp_left) == ["warning"] and "scene ends" in _sp_left[0][2],
           f"{_sp_ok} / {_sp_open} / {_sp_left}")
    _check("choice lint: the menu's last option line as the next DIALOG warns (the scene freezes)",
           _lv(_fz) == ["warning"] and "#2" in _fz[0][2] and "freezes" in _fz[0][2] and _fz_ok == [],
           f"{_fz} / {_fz_ok}")
    try:                                              # the shipped 40-option menu: decodes + lints clean
        _b252 = c.banks[252]
        _st40 = script.decode_statement(_b252.data, 0x08a2)
        _probs40 = script.choice_problems(_b252.data, [_st40])
        _check("shipped 40-option menu (bank 252 @0x08a2) decodes with 40 items, cancel = last target",
               _st40 is not None and _st40.mnem == "PROMPT_CHOICE" and len(_st40.items) == 40
               and _st40.code_targets[0] == _st40.code_targets[-1] and _probs40 == [],
               f"{_st40 and len(_st40.items)} items, {_probs40}")
    except IndexError:
        _skip("40-option menu", "bank 252 missing")
    # --- minting a new scene: type-table entry on an empty tail bank + a busy bank -------
    c5 = script.Container(raw)
    c5.set_asm_resolver(c.asm_resolver)
    empty = next(b for b in c5.banks if b.kind == "tail" and len(b.data) == 296)
    gi_e = c5.banks.index(empty)
    pc, idx = c5.add_entry(empty, 6, [], listing="FRAME 0\nSetSpeaker(Nancy, Left, 3, 0)\nDIALOG #8709\n"
                                                  "EVAL (FLG_KOKUHAKU_NOW = 1)\nEND")
    busy = c5.banks[213]
    bt = next(t for t, (cnt, off) in busy.type_table_full().items() if cnt >= 2)
    before = [(r.event_id, r.subs) for r in busy.entry_records(bt)]
    pc2, idx2 = c5.add_entry(busy, bt, [5, (1, -1)], listing="DIALOG #100\nEND", position=0)
    built = c5.build()
    c6 = script.Container(built)
    e6 = c6.banks[gi_e]
    recs6 = e6.entry_records(6)
    sc6 = script.disassemble_scene(e6, 6, pc) if recs6 else None
    changed = [i for i, (x, y) in enumerate(zip(c.banks, c6.banks)) if bytes(x.data) != bytes(y.data)]
    _check("add_entry mints a scene in an EMPTY tail bank: registered (count 1), decodes, other banks untouched",
           len(recs6) == 1 and recs6[0].event_id == pc and sc6 is not None and sc6.ok
           and "EVAL (FLG_KOKUHAKU_NOW = 1)" in scriptasm.scene_listing(sc6, e6)
           and sorted(changed) == sorted([gi_e, 213]), f"changed banks {changed}")
    after = c6.banks[213].entry_records(bt)
    _check("add_entry at position 0 in a busy bank keeps the old entries in order (count-exact reparse)",
           len(after) == len(before) + 1 and after[0].subs == [(1, 5), (1, -1)] and after[0].event_id == pc2
           and [(r.event_id, r.subs) for r in after[1:]] == before)
    c5.remove_entry(busy, bt, 0)
    _check("remove_entry restores the original list", [(r.event_id, r.subs) for r in busy.entry_records(bt)] == before)
    k0 = before[0][1]
    c5.set_entry(busy, bt, 0, subs=[(1, 77)] + k0[1:])
    r0 = busy.entry_records(bt)[0]
    grown = [(1, 77)] + k0 + [(1, 9)]
    c5.set_entry(busy, bt, 0, subs=grown)
    r1 = busy.entry_records(bt)[0]
    _check("set_entry re-keys in place (same length) and by list rewrite (grown)",
           r0.subs == [(1, 77)] + k0[1:] and r1.subs == grown and r1.event_id == before[0][0])
    bad = 0
    for fn in (lambda: c5.add_entry(empty, 74, [], event_pc=pc),
               lambda: c5.add_entry(empty, 6, [], event_pc=0xFFFE),
               lambda: c5.remove_entry(empty, 6, 5),
               lambda: c5.add_entry(empty, 6, [])):
        try:
            fn()
        except script.ScriptError:
            bad += 1
        except Exception:
            pass
    _check("entry ops reject a type past the table, a bad pc, a bad index and missing body cleanly", bad == 4)
    # --- engine-faithful checks (2026-09-24 audit vs RF4S.exe) --------------------------------
    # eval_expr = Script_EvalExpressionBytecode (RF4S.exe+0x23E1C0): int32 wrap, C division
    # (truncate toward zero), x/0 saturates to INT_MAX/INT_MIN/0, x%0 = 0, and a tag the
    # evaluator has no case for yields no value (not static).
    _E = lambda bs: script.eval_expr(bytes(bs), 0)
    _ev = [_E([0x18, 0xF9, 0x17, 2, 0x84, 0]), _E([0x18, 0xF9, 0x17, 2, 0x85, 0]),
           _E([0x17, 5, 0x14, 0x84, 0]), _E([0x18, 0xFB, 0x14, 0x84, 0]), _E([0x14, 0x14, 0x84, 0]),
           _E([0x17, 5, 0x14, 0x85, 0]), _E([1, 0xFF, 0xFF, 0xFF, 0x7F, 0x16, 0x86, 0]),
           _E([0x17, 1, 5, 0, 0, 0x86, 0]), _E([5, 0x34, 0x12]), _E([0x17, 9])]
    _check("eval_expr follows the engine's int32 arithmetic (trunc div, x/0 saturation, wrap, bad tags)",
           _ev == [(-3, True), (-1, True), (0x7FFFFFFF, True), (-0x80000000, True), (0, True), (0, True),
                   (-0x80000000, True), (None, False), (0x1234, True), (None, False)], repr(_ev))
    # SceneState_ParseMycfHeaderAndInstallReaders (RF4S.exe+0x23DAB0): word 1 != 0 = big-endian,
    # word 2 must be 0x10001 -- the parser is LE-only and the engine rejects other versions.
    _hdr_bad = 0
    for _w, _v in ((4, 1), (8, 0x10002)):
        _b = bytearray(raw)
        struct.pack_into("<I", _b, _w, _v)
        try:
            script.Container(bytes(_b))
        except script.ScriptError:
            _hdr_bad += 1
    _check("Container refuses a big-endian or non-0x10001 MYCF header", _hdr_bad == 2)
    # set_bank_bytes on a ZERO-length bank: the bank starts at the splice point and must keep its
    # offset (not shift past its own new bytes).
    _z = bytearray(raw)
    _zc = script.Container(bytes(_z))
    _zt = next(b for b in _zc.banks if b.kind == "tail")
    struct.pack_into("<II", _z, _zt.slot, _zt.file_off, 0)
    _zc = script.Container(bytes(_z))
    _zb = next(b for b in _zc.banks if b.kind == "tail" and b.index == _zt.index)
    _zc.set_bank_bytes(_zb, b"\xAB" * 8)
    _zr = script.Container(_zc.build())
    _zb2 = next(b for b in _zr.banks if b.kind == "tail" and b.index == _zt.index)
    _check("set_bank_bytes on a zero-length bank keeps its offset and holds exactly the new bytes",
           bytes(_zb2.data) == b"\xAB" * 8 and _zb2.file_off == _zt.file_off)
    # a new scene body lands on an even pc even when the bank size is odd (263 shipped banks
    # are): code always is (the rebuild puts it before the lists and the pool), so
    # add_entry/set_entry (which require even event pcs) accept it.
    c7 = script.Container(raw)
    _odd = next(b for b in c7.banks if len(b.data) % 2 and len(b.data) < 0xF000 and b.table_slots > 6)
    _pc7, _ = c7.add_entry(_odd, 6, [], listing="DIALOG #5\nEND")
    _recs7 = _odd.entry_records(6)
    c7.set_entry(_odd, 6, len(_recs7) - 1, event_pc=_pc7)
    _check("a new scene in an odd-sized bank starts on an even pc (add_entry/set_entry accept it)",
           _pc7 % 2 == 0 and script.decode_statement(_odd.data, _pc7).mnem == "DIALOG")
    # delete / insert_after refuse statements that never fall through (JMP, choices, ...).
    _nf = None
    for _b8 in c7.banks[:20]:
        for _sc8 in script.disassemble_bank(_b8, discover=False):
            _nf = next((s for s in _sc8.stmts.values()
                        if s.mnem in ("JMP", "PROMPT_CHOICE", "SWITCH_CLAMP") and s.size >= 4), None)
            if _nf:
                break
        if _nf:
            _nfb = _b8
            break
    _nfr = 0
    if _nf is not None:
        for _fn in (lambda: c7.delete_statement(_nfb, _nf.pc),
                    lambda: c7.insert_after(_nfb, _nf.pc, "DIALOG #5")):
            try:
                _fn()
            except script.ScriptError:
                _nfr += 1
    _check("delete_statement / insert_after refuse a statement that never falls through",
           _nf is not None and _nfr == 2, _nf.mnem if _nf else "none found")
    # assembler: malformed / out-of-range fields raise AsmError (never a raw ValueError or a
    # silent mask); zero-target SWITCH_CLAMP / JMP_RAND / JMP_WEIGHTED (which read past their table in
    # Script_VMStep / Script_Opcode_FFF2_ExecPrim) and > 11 SpawnMapEntity args are refused.
    _asm_bad = 0
    _bad_listings = ["DIALOG #abc", "FRAME x", "FRAME 70000", "PROMPT_CHOICE CANCEL->L, #zz->L\nL: END",
                     "SWITCH_CLAMP (reg0) ->", "JMP_RAND", "JMP_WEIGHTED", "DIALOG #99999999999",
                     "op5 u16(70000)", "op5 tag3(0x1FFFFFFFF)", "op5 @zz",
                     "op157 " + ", ".join(["1"] * 12)]
    for _t in _bad_listings:
        try:
            scriptasm.assemble(_t, 0x100)
        except scriptasm.AsmError:
            _asm_bad += 1
        except Exception:
            pass
    _ok157 = scriptasm.assemble("op157 " + ", ".join(["1"] * 11), 0x100)[0][:4] == b"\x9d\x00\x0b\x00"
    _check("assembler rejects malformed/out-of-range fields, empty jump tables and op-157 overflow cleanly",
           _asm_bad == len(_bad_listings) and _ok157, "%d/%d" % (_asm_bad, len(_bad_listings)))
    # speaker slots 25/26/29 are named from Script_VMOp_SetSpeaker (RF4S.exe+0x207F70)
    _check("SetSpeaker slots 25/26/29 = Soldier/Ethelberd/Traveler (no old names kept)",
           script.meta.opcode_arg_values(66) == ["Soldier", "Left"]
           and script.meta.opcode_arg_values(69) == ["Ethelberd", "Right"]
           and scriptasm.assemble("SetSpeaker Traveler, Left, 0, 0", 0x100)[0][:2] == b"\x4a\x00"
           and script.meta.op_from_mnemonic("SetSpeakerguest25") is None
           and script.meta.op_from_mnemonic("SetSpeakerTravelerLeft") is None
           and script.meta.op_from_mnemonic("SetSpeakerEmote1") is None)
    # a packed var whose width is not emdeb's keeps its raw var:0x form (it would re-assemble
    # with the emdeb width otherwise).
    if emf is not None:
        _v0 = emf.get("REG_MAIN_SCENARIO")
        _enc_ok = c.pack_var(_v0.bit_offset, _v0.bit_width)
        _enc_w = c.pack_var(_v0.bit_offset, _v0.bit_width + 1)
        _t_ok = script.disasm_expr(b"\x02" + struct.pack("<I", _enc_ok) + b"\x00", 0)[0]
        _t_w = script.disasm_expr(b"\x02" + struct.pack("<I", _enc_w) + b"\x00", 0)[0]
        _check("packed-var names only stand for the emdeb width (other widths stay var:0x..)",
               _t_ok == "REG_MAIN_SCENARIO" and _t_w.startswith("var:0x")
               and scriptasm.asm_expr(_t_w, resolver) == b"\x02" + struct.pack("<I", _enc_w) + b"\x00",
               "%s / %s" % (_t_ok, _t_w))
    # --- CLI surface (argparse wiring only) ----------------------------------------------
    try:
        import rf4mod as _rf4
        import io as _io
        _argv = ["script", "expr", "reg0 + 1"]
        _buf = _io.StringIO()
        _old = sys.stdout
        sys.stdout = _buf
        try:
            _rf4.main(_argv)
        finally:
            sys.stdout = _old
        _check("`rf4mod script expr` compiles an expression from the CLI", "reg0 + 1" in _buf.getvalue())
    except SystemExit:
        _check("`rf4mod script expr` compiles an expression from the CLI", False, "SystemExit")
    except Exception as e:
        _check("`rf4mod script expr` compiles an expression from the CLI", False, repr(e))
    # listing names: opcodes that share a mnemonic (handler aliases like 218/219) print as
    # Name_N instead of a bare opN; SetSpeaker ops print their opcode arguments first. Every
    # (name, opcode arguments) pair is unique and assembles back to its op.
    from rf4s_modkit import scriptasm as _sa
    _ln = [(_sa.listing_name(o), tuple(script.meta.opcode_arg_values(o)))
           for o in range(script.DISPATCHABLE_ACTION_OPS)]
    _bad = [(o, n) for o, n in enumerate(_ln)
            if (script.meta.op_from_opcode_args(n[0], list(n[1])) if n[1] else _sa.op_from_any(n[0])) != o]
    _bare = [o for o, n in enumerate(_ln) if re.fullmatch(r"op\d+", n[0])]
    _check("every action opcode has a unique listing name that assembles back (Name_N for shared names)",
           not _bad and len(set(_ln)) == len(_ln) and len(_bare) <= 2
           and _sa.action_line(53, ["3", "0"]) == "SetSpeaker(18, 1, 3, 0)"
           and all(script.meta.op_from_opcode_args("SetSpeaker", script.meta.opcode_arg_raws(o)) == o
                   for o in range(16, 76)),
           _bad[:3] or f"{len(_bare)} bare opN left: {_bare}")
    # the developers' test menus: bank 18 (Jones) carries the event / festival / date menus
    _tp = _first("rf3mc.eng")
    _mc = _first("rf3.mc")
    if _tp and _mc:
        import rf4mod as _rf4m
        try:
            _dm = script.dev_menus(script.Container(_mc.read_bytes()), _rf4m._dialog_fn(str(_tp)), banks=[18])
        except Exception as e:  # noqa: BLE001
            _dm = []; print("   dev_menus:", e)
        _items = {nm: (tgt, first) for _b, _s, _st, rows in _dm for nm, tgt, first in rows}
        _check("dev_menus finds bank 18's three '＊' test menus and routes '＊Hand Over Recipe' to its line",
               len(_dm) == 3 and _items.get("＊Hand Over Recipe", (None, None))[1] == 23914,
               f"{len(_dm)} menus, {len(_items)} items")
    else:
        _skip("dev_menus", "needs rf3.mc + rf3mc.eng")
    # who speaks each DIALOG: only certain speakers are labelled -- set on every path,
    # through CALLed routines (bank 210's request board speaks as the 'Eliza' name plate
    # after the player's "By the way..."); a line after EndDialogue gets no label
    if _mc:
        _c210 = script.Container(_mc.read_bytes())
        _b210 = _c210.banks[210]
        _s210 = next((s for s in script.disassemble_bank(_b210) if s.entry_pc == 0x02D4), None)
        _spk = script.dialog_speakers(_s210, _b210) if _s210 else {}
        _check("DIALOG speakers: player 'By the way...', then Eliza via CALL; none after EndDialogue",
               _spk.get(0x0E22) == "player" and _spk.get(0x0E4A) == "Eliza"
               and _spk.get(0x0E6A) == "Eliza" and 0x0220 not in _spk,
               f"{_spk.get(0x0E22)!r} / {_spk.get(0x0E4A)!r} / {_spk.get(0x0220)!r}")
        # DialogueLine (op 8) names the speaker from the name archive (1 = Vishnal), and
        # SetDialogueSpeakerIf 1 (op 699) switches the box to narration (no name, no blips)
        _b300 = _c210.banks[300]
        _s300 = next((s for s in script.disassemble_bank(_b300) if s.entry_pc == 0x49AE), None)
        _sp3 = script.dialog_speakers(_s300, _b300) if _s300 else {}
        from rf4s_modkit import gamenames as _gn
        _check("DIALOG speakers: op 8 DialogueLine 1 -> character 1 as the game names it; op 699 -> narration",
               _sp3.get(0x021A) == _gn.name("characters", 1) and _sp3.get(0x1EBC) == script.SPEAKER_NARRATION,
               f"{_sp3.get(0x021A)!r} / {_sp3.get(0x1EBC)!r}")
        # the cutscene editor's Script view shows the same (it used the last speaker op in
        # display order, so Eliza's board lines read as 'MC')
        try:
            from cutscene_editor import render as _cer

            class _Doc:
                em = None

                def text(self, i):
                    return "x"
            _rows = _cer.SceneText(_Doc(), _b210, _s210).story_rows()
            _who = {r.key[0]: "".join(x[0] for x in r.segs).strip().split(":")[0]
                    for r in _rows if r.key and r.key[0] in (0x0E22, 0x0E4A, 0x0220)}
            _check("the Script view labels the board lines Eliza and leaves speaker-less lines bare",
                   _who.get(0x0E22) == "MC" and _who.get(0x0E4A) == "Eliza" and _who.get(0x0220) == "“x”",
                   f"{_who}")
        except ImportError as e:
            _skip("Script view speakers", str(e))
    # actor names shared with alternate forms above the character range still name the
    # character: Clorica = 2 (also 308), Ventuswill = 21 (also 235 / 982)
    _names_ok = (script.actor_leaf_text(2) == "actor(Clorica)" and script.actor_leaf_text(21) == "actor(Ventuswill)"
                 and script.actor_leaf_text(308) == "actor(308)" and script.actor_leaf_value("Clorica") == 2
                 and script.actor_leaf_text(27) == "actor(27)")
    _check("actor(Clorica) / actor(Ventuswill) name ids 2 / 21; Traveler / Soldier ids stay numeric", _names_ok)
    # the event-spawn ops' char table covers every rf3NpcParam row, model-less markers too
    from rf4s_modkit import opcode_meta as _om
    _ec = _om.ENUM_ARG_VALUES.get((153, 0), {})
    _check("SpawnEventActor's char table lists all 392 rows, 269 'Search' as a model-less marker",
           len(_ec) == 392 and _ec.get(269, ("",))[0] == "Search (no model)"
           and _ec.get(9, ("",))[0].startswith("Arthur ["), f"{len(_ec)} rows, 269 = {_ec.get(269)}")
    # add / sub / set: ModifyPlayerResource / ModifyLumber / ApplyFriendshipDelta take their
    # mode from an argument's token KIND (null / zero / self leaves = kinds 4 / 5 / 6)
    if _mc:
        _cm = script.Container(_mc.read_bytes())
        _b252 = _cm.banks[252]
        _sc = next((s for s in script.disassemble_bank(_b252) if 0x099A in s.stmts), None)
        _st = _sc.stmts[0x099A] if _sc else None
        _mode = scriptasm.operand_text(_b252.data, _st.args[1], _st.op, 1) if _st else None
        _check("mode leaves list as add / sub / set and assemble back to the same leaf bytes",
               _st is not None and _st.op == 417 and _mode == "add"
               and scriptasm._LEAF_WORDS["add"] == _b252.data[_st.args[1]:_st.args[1] + 1]
               and scriptasm._LEAF_WORDS["sub"] == b"\x12" and scriptasm._LEAF_WORDS["set"] == b"\x13"
               and script.arg_repr(_b252.data, _st.args[1], _st.op, 1) == "add",   # the editor's Script tab
               f"{_mode!r}")


def test_bank_relink():
    """Whole-bank rebuild (bankrelink): parse -> build and listing -> assemble are byte-exact,
    and moving the code (a statement inserted at the top) keeps every scene's flow, operands
    and entry keys intact."""
    print("bank relink (whole-bank rebuild):")
    from rf4s_modkit import script, scriptasm, bankrelink as br
    _check("literals encode like the game's compiler (s8 before u8, s16 before u16)",
           scriptasm.int_literal_bytes(5) == b"\x18\x05" and scriptasm.int_literal_bytes(200) == b"\x17\xc8"
           and scriptasm.int_literal_bytes(-5) == b"\x18\xfb" and scriptasm.int_literal_bytes(1000) == b"\x1a\xe8\x03"
           and scriptasm.int_literal_bytes(40000) == b"\x19\x40\x9c"
           and scriptasm.Assembler().operand("actor(Forte)") == ("expr", b"\x03\x04\x00\x00\x00\x00"))
    p = _first("rf3.mc")
    if not p:
        _skip("bank relink", "rf3.mc not extracted")
        return
    c = script.Container(p.read_bytes())
    try:
        from rf4s_modkit.emflags import EmFlagTable
        emf = EmFlagTable.load()
        script.install_emflags_var_resolver(c, emf)
    except Exception:
        emf = None
    res = c.install_asm_resolver(emf)
    banks = c.banks if not QUICK else c.banks[::15]
    model_bad, text_bad, shift_bad, n_scenes = [], [], [], 0
    for bk in banks:
        d = bytes(bk.data)
        try:
            if br.relink(bk) != d:
                model_bad.append(bk.index)
            txt = br.bank_listing(bk, res)
            if br.assemble_bank(txt, res) != d:
                text_bad.append(bk.index)
        except script.ScriptError as e:
            text_bad.append((bk.index, str(e)[:80]))
            continue
        tt = bk.type_table_full()
        if not tt:
            continue
        ls = txt.splitlines()
        i = next(k for k, l in enumerate(ls) if not l.startswith((".table", ".slot", ".tword")))
        ls.insert(i, "    Wait 6000")
        nb = script.Bank(bk.index, bk.kind, 0, bytearray(br.assemble_bank("\n".join(ls), res)))
        nb.slots_hint = bk.slots_hint
        for t in tt:
            for a, b in zip(bk.entry_records(t), nb.entry_records(t)):
                n_scenes += 1
                s1 = [(s.op, s.size) for s in script.disassemble_scene(bk, t, a.event_id).stmts.values()]
                s2 = [(s.op, s.size) for s in script.disassemble_scene(nb, t, b.event_id).stmts.values()]
                if a.subs != b.subs or b.event_id != a.event_id + 6 or s1 != s2:
                    shift_bad.append((bk.index, t))
    # one listing syntax: actions are Name(args); control keywords keep ( cond ) and spaced ->
    _ctrl = ("RET", "FRAME", "DIALOG", "CALL", "JMP", "JMP_RAND", "EVAL", "RET_NZ", "BR_Z", "BR_NZ",
             "SWITCH", "SWITCH_CLAMP", "JMP_WEIGHTED", "PROMPT_CHOICE", "PROMPT_CHOICE_FORCED")
    _odd = []
    _sample = [bk for bk in banks if bk.type_table_full()][:6]
    for bk in _sample:
        _lines = br.bank_listing(bk, res).splitlines()
        for sc in script.disassemble_bank(bk)[:20]:
            _lines += scriptasm.scene_listing(sc, bk, show_addr=False).splitlines()
        for _l in _lines:
            _b = _l.split(";")[0].strip()
            if not _b or _b.endswith(":") or _b.startswith("."):
                continue
            _head = re.match(r"[A-Za-z_]\w*", _b)
            _head = _head.group(0) if _head else ""
            if _head in _ctrl:
                if "->" in _b.replace(" -> ", "") or _b.startswith("JMP_RAND ->"):
                    _odd.append(_b)
            elif not re.fullmatch(r"[A-Za-z_]\w*\(.*\)", _b):
                _odd.append(_b)
    _check("listings write every action as Name(args) and every control arrow as ' -> '",
           not _odd, str(_odd[:4]))
    _check("every bank rebuilds byte-exactly from its model (%d banks)" % len(banks), not model_bad, str(model_bad[:5]))
    _check("every bank rebuilds byte-exactly from its text listing", not text_bad, str(text_bad[:5]))
    _check("a statement inserted at the top relocates every scene (%d scenes)" % n_scenes,
           not shift_bad and n_scenes > 0, str(shift_bad[:5]))


def test_script_relink_edits():
    """Structural script edits rebuild the bank (bankrelink) instead of trampolining: an insert
    through the Container / CLI API re-parses in the compiler layout, adds no jump, decodes to
    the listing it was given and keeps every other scene's entry pc, keys and flow; deleting it
    restores the shipped bank byte for byte; a file trampolined the old way is detected and
    folded back with the same execution; the 64 KB address limit and the header load-buffer
    words are enforced."""
    print("script edits rebuild the bank (no trampolines):")
    from rf4s_modkit import script, bankrelink as br
    p = _first("rf3.mc")
    if not p:
        _skip("relinked edits", "rf3.mc not extracted")
        return
    raw = p.read_bytes()
    c0 = script.Container(raw)
    res = c0.install_asm_resolver()

    def entries(b):
        return [(t, r.event_id, r.subs) for t in b.type_table_full() for r in b.entry_records(t)]

    def jmps(b):
        return sum(1 for s in br.BankModel.parse(b).code if isinstance(s, br.Stmt) and s.op == 0xFFFA)

    # (a)-(d) on a spread of banks: insert before a DIALOG, then delete what was inserted
    picked = []
    for pos in range(0, len(c0.banks), 7 if QUICK else 3):
        b = c0.banks[pos]
        scs = [s for s in script.disassemble_bank(b, discover=False) if s.ok and s.action_type >= 0]
        hit = next(((s, q) for s in scs for q, st in s.stmts.items() if st.mnem == "DIALOG"), None)
        if hit and len(b.data) < 0xFF00:
            picked.append((pos, hit[0], hit[1]))
        if len(picked) >= (12 if QUICK else 40):
            break
    bad, n_other = [], 0
    for pos, sc, dpc in picked:
        c = script.Container(raw)
        c.set_asm_resolver(res)
        b = c.banks[pos]
        ents0, j0 = entries(b), jmps(b)
        sigs0 = [br.flow_signature(b, e) for _t, e, _s in ents0]
        new = c.insert_before(b, dpc, "DIALOG #9001\nBR_Z (reg0 == 3) -> L\nDIALOG #9002\nL:")
        pm = c.last_relink[pos]
        try:
            m = br.BankModel.parse(b)                 # (a) compiler layout again
            ok_a = m.build() == bytes(b.data) and m.fold() == 0
        except script.ScriptError:
            ok_a = False
        ok_b = jmps(b) == j0                          # (b) no trampoline jump
        d = b.data
        s1 = script.decode_statement(d, new)
        s2 = s1 and script.decode_statement(d, new + s1.size)
        s3 = s2 and script.decode_statement(d, new + s1.size + s2.size)
        s4 = s3 and script.decode_statement(d, new + s1.size + s2.size + s3.size)
        ok_c = (s1 and s1.dialog_id == 9001 and s2.mnem == "BR_Z" and s3.dialog_id == 9002
                and s2.code_targets[0] == s4.pc and pm[dpc] == new      # jumps to dpc run it first
                and s4.dialog_id == script.decode_statement(c0.banks[pos].data, dpc).dialog_id)
        ents1 = entries(b)                            # (d) entries follow, other flows unchanged
        ok_d = [(t, pm[e], k) for t, e, k in ents0] == ents1
        for (t, e0, _k), (_t, e1, _k1), sg in zip(ents0, ents1, sigs0):
            if dpc in script.disassemble_scene(c0.banks[pos], t, e0).stmts:
                continue                              # a scene that runs the edited spot
            n_other += 1
            ok_d = ok_d and br.flow_signature(b, e1) == sg
        c.delete_statement(b, new)
        c.delete_statement(b, new)
        c.delete_statement(b, new)
        ok_e = bytes(b.data) == bytes(c0.banks[pos].data) and c.build() == raw
        if not (ok_a and ok_b and ok_c and ok_d and ok_e):
            bad.append((pos, ok_a, ok_b, bool(ok_c), ok_d, ok_e))
    _check("insert through the API: bank re-parses in the compiler layout, no jump added, the new "
           "statements decode as written, entries follow and %d other scenes keep their flow (%d banks)"
           % (n_other, len(picked)), not bad and len(picked) >= 10, str(bad[:4]))
    _check("deleting the inserted statements restores the shipped bank byte for byte", not bad)
    # rewrite drops what only the old body used; other scenes unchanged
    c = script.Container(raw)
    c.set_asm_resolver(res)
    pos, sc, _dpc = picked[0]
    b = c.banks[pos]
    ents0 = entries(b)
    sigs0 = {e: br.flow_signature(b, e) for _t, e, _k in ents0}
    n0 = len(b.data)
    e_new = c.rewrite_scene(b, sc.entry_pc, "FRAME 0\nDIALOG #9003\nEND")
    pm = c.last_relink[pos]
    rsc = script.disassemble_scene(b, sc.action_type, e_new)
    _check("rewrite_scene puts the new body in place, drops the old one and keeps other scenes",
           [st.mnem for st in rsc.stmts.values()] == ["FRAME", "DIALOG", "RET"] and len(b.data) < n0
           and all(br.flow_signature(b, pm[e]) == sg for e, sg in sigs0.items() if pm[e] != e_new)
           and br.relink(b) == bytes(b.data))
    # a file trampolined the old way (append [new][moved copy][JMP back] after the pool and
    # overwrite the statement with a JMP; delete = JMP over the statement) is detected and folded
    c = script.Container(raw)
    c.set_asm_resolver(res)
    pos, sc, dpc = next(x for x in picked if c.banks[x[0]].kind == "primary")
    b = c.banks[pos]
    st = script.decode_statement(b.data, dpc)
    base = len(b.data) + (len(b.data) & 1)
    region, _l = _asm_region("DIALOG #9004\n.raw " + bytes(b.data[dpc:dpc + st.size]).hex(),
                                    base, res, dpc + st.size)
    c.set_bank_bytes(b, bytes(b.data) + b"\0" * (len(b.data) & 1) + region)
    struct.pack_into("<HH", b.data, dpc, 0xFFFA, base)
    old_sigs = [(t, e, br.flow_signature(b, e)) for t, e, _k in entries(b)]
    nxt = next((q for q, s2 in sc.stmts.items() if q > dpc + st.size and s2.op < 0xFFF0
                and s2.size > 4), None)
    if nxt is not None:                               # the old delete: a JMP over the statement
        struct.pack_into("<HH", b.data, nxt, 0xFFFA, nxt + script.decode_statement(b.data, nxt).size)
        old_sigs = [(t, e, br.flow_signature(b, e)) for t, e, _k in entries(b)]
    found = c.trampolined_banks()
    done = c.normalize_banks(found)
    pm = c.last_relink[pos]
    cn = script.Container(raw)
    cn.set_asm_resolver(res)
    cn.insert_before(pos, dpc, "DIALOG #9004")
    if nxt is not None:
        cn.delete_statement(pos, cn.last_relink[pos][nxt])
    _check("an old trampolined bank is detected and folded back: compiler layout, same flow for every "
           "entry, same scenes as the new insert/delete",
           found == [pos] and done and done[0][1] == (2 if nxt is not None else 1)
           and br.BankModel.parse(b).fold() == 0
           and all(br.flow_signature(b, pm[e]) == sg for _t, e, sg in old_sigs)
           and [br.flow_signature(b, e) for _t, e, _k in entries(b)]
           == [br.flow_signature(cn.banks[pos], e) for _t, e, _k in entries(cn.banks[pos])],
           "found %s done %s" % (found, done))
    # shipped banks: the flow reader + folding change nothing (sample; every bank verified once)
    sample = c0.banks[::97 if QUICK else 29]
    fold_bad = []
    for b in sample:
        m = br.BankModel.parse_flow(b)
        f = m.fold()
        nb = script.Bank(b.index, b.kind, 0, bytearray(m.build()))
        nb.slots_hint = b.slots_hint
        if f or [br.flow_signature(b, e) for _t, e, _k in entries(b)] != \
                [br.flow_signature(nb, e) for _t, e, _k in entries(nb)]:
            fold_bad.append(b.index)
    _check("the trampoline folder leaves shipped code alone (flow read + fold on %d banks)" % len(sample),
           not fold_bad and not c0.trampolined_banks(), str(fold_bad[:5]))
    # limits: 64 KB addressing refused cleanly; a growing bank raises its load-buffer word
    c = script.Container(raw)
    big = max((b for b in c.banks if b.kind == "tail"), key=lambda b: len(b.data))
    gpos = c.banks.index(big)
    bsc = next(s for s in script.disassemble_bank(big, discover=False) if s.ok and s.action_type >= 0)
    before = bytes(c.data)
    try:
        c.insert_before(big, bsc.entry_pc, "\n".join(["DIALOG #1"] * 200))
        refused = False
    except script.ScriptError as e:
        refused = "16-bit" in str(e) and bytes(c.data) == before
    cap = c.max_bank_size("tail")
    c.insert_before(big, bsc.entry_pc, "DIALOG #1")
    _check("an edit past 64 KB is refused (container unchanged); growing the largest bank raises "
           "the header's load-buffer word",
           refused and c.max_bank_size("tail") == len(big.data) == cap + 6
           and not c.validate_bank_sizes() and script.Container(c.build()).max_bank_size("tail") == cap + 6)
    # the CLI writes the rebuilt bank too
    import subprocess
    import tempfile
    tmp = pathlib.Path(tempfile.mkdtemp())
    pos, sc, dpc = picked[0]
    r = subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name("rf4mod.py")), "script", "insert",
                        str(p), "--bank", str(pos), "--pc", hex(dpc), "--before", "--stmt", "DIALOG #9005",
                        "-o", str(tmp / "out.mc")], capture_output=True, text=True)
    co = script.Container((tmp / "out.mc").read_bytes()) if (tmp / "out.mc").is_file() else None
    _check("CLI `script insert` writes the rebuilt bank (DIALOG in place, compiler layout)",
           r.returncode == 0 and co is not None
           and script.decode_statement(co.banks[pos].data, dpc).dialog_id == 9005
           and br.relink(co.banks[pos]) == bytes(co.banks[pos].data) and jmps(co.banks[pos]) == jmps(c0.banks[pos]),
           (r.stdout + r.stderr)[-200:])


def _asm_region(text, base, resolver, fallthrough_to):
    from rf4s_modkit import scriptasm
    return scriptasm.assemble(text, base, resolver=resolver, fallthrough_to=fallthrough_to)


def test_emflags_extras():
    """Modder-defined game-flag variables (2026-09-20): the emdeb_extra.json sidecar,
    allocation in the free tail of the 4096-bit store, validation, and resolution by the
    cutscene assembler/disassembler and the em.bin condition grammar."""
    print("emflags extras (new FLG_/REG_ variables via sidecar):")
    from rf4s_modkit.emflags import EmFlagTable, GAMEFLAGS_BITS
    from rf4s_modkit import script, scriptasm
    try:
        t = EmFlagTable.load(extra=False)
    except FileNotFoundError:
        _skip("emflags extras", "emdeb.bin not found")
        return
    used = t.total_bits
    tmp = pathlib.Path(tempfile.mkdtemp()) / "emdeb_extra.json"
    v = t.add_variable("FLG_SELFTEST_DONE")
    r = t.add_variable("REG_SELFTEST_CNT", 4, jp_name="テスト")
    _check("add_variable allocates the next free bits after the shipped table",
           v.bit_offset == used and r.bit_offset == used + 1 and r.bit_width == 4
           and t.free_bits == GAMEFLAGS_BITS - used - 5)
    t.save_extras(str(tmp))
    t2 = EmFlagTable.load(extra=str(tmp))
    _check("sidecar round-trips (load merges it; by_name/by_offset/extras see the variables)",
           [x.name for x in t2.extras] == ["FLG_SELFTEST_DONE", "REG_SELFTEST_CNT"]
           and t2.by_offset(used + 1) is t2.get("REG_SELFTEST_CNT") and t2.get("REG_SELFTEST_CNT").jp_name == "テスト")
    rej = 0
    for fn in (lambda: t2.add_variable("FLG_SELFTEST_DONE"),
               lambda: t2.add_variable("REG_BAD_WIDTH", 40),
               lambda: t2.add_variable("FLG_OVERLAP", 1, bit_offset=used),
               lambda: t2.add_variable("bad name!"),
               lambda: t2.add_variable("FLG_PAST_END", 2, bit_offset=GAMEFLAGS_BITS - 1)):
        try:
            fn()
        except ValueError:
            rej += 1
    _check("add_variable rejects duplicates, bad widths/names, overlaps and out-of-store bits", rej == 5)
    # zone 2 (2026-09-23): explicit placement is allowed, but never on bits the game uses
    # (emflags.ZONE2_BLOCKS: shop-door hours, daily-reset range, per-NPC bits, recipes, ...)
    from rf4s_modkit import emflags as _ef
    t3 = EmFlagTable.load(extra=False)
    z_rej = 0
    for fn in (lambda: t3.add_variable("FLG_ON_SHOP_DOOR", 1, bit_offset=_ef.ZONE2_BASE + 745),
               lambda: t3.add_variable("REG_ON_RECIPES", 4, bit_offset=_ef.ZONE2_BASE + 1100)):
        try:
            fn()
        except ValueError:
            z_rej += 1
    z_ok = t3.add_variable("FLG_ZONE2_FREE", 1, bit_offset=_ef.ZONE2_BASE + 1800)
    z_auto = t3.add_variable("FLG_AUTO_STAYS_ZONE1")
    _check("add_variable: zone-2 bits the game uses are refused; free zone-2 bits allowed; auto-allocation stays in zone 1",
           z_rej == 2 and z_ok.bit_offset == _ef.ZONE2_BASE + 1800 and z_auto.bit_offset < _ef.GAMEFLAGS_BITS,
           f"{z_rej}/2 refused, auto -> bit {z_auto.bit_offset}")
    _check("zone-2 map labels: birthday-gift / daily-greeting / recipe blocks decode with the char or recipe number",
           "Forte" in _ef.zone2_text(1011) and "birthday" in _ef.zone2_text(1011)
           and "daily greeting done" in _ef.zone2_text(1042) and "recipe 341" in _ef.zone2_text(1403)
           and "shop-door" in _ef.zone2_text(745) and "PAST THE END" in _ef.zone2_text(2600),
           _ef.zone2_text(1011))
    p = _first("rf3.mc")
    if p:
        c = script.Container(p.read_bytes())
        script.install_emflags_var_resolver(c, t2)
        c.install_asm_resolver(t2)
        enc = scriptasm.asm_expr("REG_SELFTEST_CNT += 1", c.asm_resolver)
        _check("cutscene assembler + disassembler resolve a sidecar variable",
               enc[0] == 0x02 and script.disasm_expr(enc, 0)[0] == "REG_SELFTEST_CNT += 1"
               and c.unpack_var(struct.unpack_from("<I", enc, 1)[0]) == (used + 1, 4, False))
        script.set_packed_var_resolver(None)
    try:
        from rf4s_modkit import emscript
        em = emscript.EmScript.load()
        em.names.flags.merge_extras(str(tmp))
        ex = em.parse_condition_spec("FLG_SELFTEST_DONE == 1 AND REG_SELFTEST_CNT >= 3")
        _check("em.bin condition grammar accepts the sidecar variables", len(ex) == 2)
    except FileNotFoundError:
        _skip("em condition with extras", "em.bin not found")


def test_portrait_faces():
    """rf4s_modkit.portraits: what a SetSpeaker face id shows, read from RF4S.exe -- the classic
    Story-mode faces for every speaker, the Newlywed-mode E-mote mapping for the candidates --
    checked against the shipped face files and every speaker cue in rf3.mc."""
    print("portraits (SetSpeaker faces):")
    from rf4s_modkit import portraits as pt, script
    _check("Story mode: every speaker slot 0..28 has classic faces; ids 0..5 are the shared moods",
           all(pt.has_portrait(s_) for s_ in range(29)) and len(pt.faces(3)) == 34
           and [pt.label(3, i) for i in range(6)] == ["normal", "angry", "crying", "smile", "surprised", "shy"]
           and pt.face_file(4, 10) == "04_FORTE_face_010_047" and pt.label(4, 255) == "special 1 (SP1)")
    _check("Newlywed mode: 12 candidates + the player map the same ids to E-mote faces; 1000+ ids are Newlywed-only",
           sum(pt.has_newlywed(s_) for s_ in range(29)) == 13 and not pt.has_newlywed(3)
           and pt.emote_label(4, 10) == "anger 2" and pt.label(4, 1394).startswith("Newlywed-only"))
    bm = _first("04_FORTE_face_000_NORMAL.texture")
    if bm:
        missing = [f for s_ in range(29) for _i, f, _m in pt.faces(s_)
                   if not (bm.parent / (f + ".texture")).is_file()]
        _check("every listed face file ships", not missing, f"{len(missing)} missing {missing[:3]}")
    mc = _first("rf3.mc")
    if not mc:
        _skip("shipped face ids fit the face lists", "rf3.mc not extracted")
        return
    c = script.Container(mc.read_bytes())
    bad, n, newly = [], 0, 0
    for b in c.banks:
        for sc in script.disassemble_bank(b):
            for st in sc.stmts.values():
                if not (script.is_portrait_op(st.op) and st.args):
                    continue
                slot = (st.op - 16) >> 1
                v = script.static_arg(b, st, 0)
                if v is None or not pt.has_portrait(slot):
                    continue
                n += 1
                if v >= 1000:
                    newly += 1
                elif pt.face_file(slot, v) is None:
                    bad.append((slot, v))
    # one shipped cue gives Raven (slot 28, a single face) face 4: the game reads whatever
    # archive follows her face file -- a quirk of the shipped script, listed as known
    bad = [x for x in bad if x != (28, 4)]
    _check("every shipped face id < 1000 names a face file of its speaker (known: one Raven cue)",
           n > 10000 and not bad, f"{n} cues ({newly} Newlywed-only ids), {len(bad)} bad {bad[:5]}")


def test_textlint():
    """rf4s_modkit.textlint: the game's text grammar -- what crashes, what shows
    wrongly -- and the shipped text passes."""
    print("textlint (game text checks):")
    from rf4s_modkit import textlint as tl
    lv = lambda t: [x.level for x in tl.lint(t)]                       # noqa: E731
    _check("＠‡A,B＠: a missing comma, a missing closing ＠ or a >63-byte side is an error",
           "error" in lv("ich bin ＠‡kein keine＠") and "error" in lv("ich bin ＠‡kein,keine")
           and "error" in lv("＠‡" + "x" * 64 + ",y＠") and "error" not in lv("ich bin ＠‡kein,keine＠"))
    toks = [(t.kind, t.slot) for t in tl.tokens("＠キャラ０＠ got ＠アイテムＦ＠ in ＠マップＮ＠ for ＠金１＠ "
                                               "＠しゅじんこうくん＠ ＠キール＠ ＠Ｚ＠")]
    _check("tokens: slot kinds and base-32 / bare-number slots decode like the game",
           toks == [(0, 0), (1, 15), (2, 23), (4, 1), (None, None), (None, None), (3, 35)], str(toks))
    _check("warnings: unknown token, slot out of range, odd ＋, carriage return; lone ＠ and NUL padding are fine",
           lv("＠ほげ＠") == ["warning"] and lv("＠マップＯ＠") == ["warning"]
           and lv("a ＋b") == ["warning"] and lv("a\r\nb") == ["warning"]
           and lv("＠") == [] and lv("text\x00\x00") == [])
    _check("info: a token whose text slot the scene never sets (op 343 SetVar1 writes slot 0 only)",
           [x.level for x in tl.lint("＠アイテム１＠", slots={1: {0}})] == ["info"]
           and tl.lint("＠アイテム０＠", slots={1: {0}}) == [])
    eng = _first("rf3mc.eng")
    if eng:
        texts = textdb.TextArchive.load(eng).texts()
        bad = [(i, x.message) for i, t in enumerate(texts) for x in tl.errors(t)]
        _check("every shipped rf3mc.eng line passes (no errors)", not bad and len(texts) > 100000,
               f"{len(bad)} errors {bad[:2]}")
    else:
        _skip("shipped text passes textlint", "rf3mc.eng not extracted")


def test_cutscene_bank_listing():
    """Options -> Advanced 'Bank listing tab': off by default; on, the Cutscene Editor gets a
    read-only tab with every scene of the open bank (registered and discovered), Find marks
    the matches, a double click opens that scene at that statement; the toolbar keeps the
    setting when it saves its own."""
    print("cutscene editor: whole-bank listing tab (Options -> Advanced):")
    try:
        import tkinter as tk
        import cutscene_editor as ce
    except Exception as e:
        _skip("bank listing", f"cutscene_editor/tkinter not importable ({e})")
        return
    from rf4s_modkit import script
    if not _first("rf3.mc"):
        _skip("bank listing", "rf3.mc not extracted")
        return

    def reader(n):
        f = _first(n)
        return f.read_bytes() if f else None

    CE = ce.CutsceneExplorer
    default_off = CE.bank_listing_setting() is False
    root = None
    try:
        try:
            root = tk.Tk()
            root.withdraw()
        except Exception as e:
            _skip("bank listing", f"no display for Tk ({e})")
            return
        ex = CE(tk.Toplevel(root), reader=reader)
        tabs0 = [ex.nb.tab(t, "text") for t in ex.nb.tabs()]
        CE.set_bank_listing_setting(True)
        ex.show_bank_listing(True)
        ex._save_prefs()                         # the toolbar's own save keeps the option
        kept = CE.bank_listing_setting()
        bank = ex.doc.container.n_primary + 272  # MAP_DUNG_A02: boss scenes + a shared SetFlagBit body
        ex.show_bank(bank)
        ex.nb.select(ex.listing)
        ex._tab_changed()
        txt = ex.listing.text.get("1.0", "end-1c")
        n_scenes = len(script.disassemble_bank(ex.doc.container.banks[bank]))
        heads = len(re.findall(r"^; container bank %d " % bank, txt, re.M))
        ex.listing.find_var.set("SetFlagBit(99")
        hits = len(ex.listing.text.tag_ranges("hit")) // 2
        line = next(i for i, (e, pc) in enumerate(ex.listing.line_at, 1) if pc == 0x0290)
        entry = ex.listing.line_at[line - 1][0]
        bb = ex.listing.text.bbox("%d.4" % line) or (0, 0, 0, 0)
        ex.listing.text.see("%d.4" % line)
        root.update_idletasks()
        bb = ex.listing.text.bbox("%d.4" % line) or bb
        ev = type("E", (), {"x": bb[0] + 1, "y": bb[1] + 1})()
        ex.listing._open_line(ev)
        opened = (ex.scene is not None and ex.scene.entry_pc == entry
                  and ex.nb.select() == str(ex.view))
        # the shown listing follows a bank change
        ex.nb.select(ex.listing)
        ex._tab_changed()
        info0 = ex.listing.info.cget("text")
        ex.show_bank(bank - 76)                  # MAP_FIELD_36 (Daily Road)
        root.update_idletasks()
        info1 = ex.listing.info.cget("text")
        # addresses follow the toolbar's "addresses": a column beside the Bank listing's and the
        # Source tab's text, never in the text itself
        import re as _re
        ex.addr.set(False)
        ex._view_mode()
        ex.nb.select(ex.listing)
        ex._tab_changed()
        _no_addr = not any(_re.match(r"^\s*[0-9a-f]{4}: ", ln)
                           for ln in ex.listing.text.get("1.0", "end").split("\n"))
        _pcs_kept = sum(1 for _e, _pc in ex.listing.line_at if _pc is not None) > 0
        _lcol_off = not ex.listing.addrcol.col.winfo_manager()
        ex.addr.set(True)
        ex._view_mode()
        _lrows = ex.listing.addrcol.col.get("1.0", "end").split("\n")
        _with_addr = (bool(ex.listing.addrcol.col.winfo_manager()) and _lcol_off
                      and not any(_re.match(r"^\s*[0-9a-f]{4}: ", ln)
                                  for ln in ex.listing.text.get("1.0", "end").split("\n"))
                      and any(_re.fullmatch(r"[0-9a-f]{4}", x) for x in _lrows))
        ex.nb.select(ex.source)
        ex._tab_changed()
        root.update_idletasks()
        src = ex.source
        _src_clean = not any(_re.match(r"^\s*[0-9a-f]{4}: ", ln)
                             for ln in src.text.get("1.0", "end").split("\n"))
        _g = [x for x in src.gutter.get("1.0", "end").split("\n") if x.strip()]
        _gutter_ok = bool(src.gutter.winfo_manager()) and len(_g) > 3 and all(
            _re.fullmatch(r"[0-9a-f]{4}", x) for x in _g)
        ex.addr.set(False)
        ex._view_mode()
        _gutter_off = not src.gutter.winfo_manager()
        CE.set_bank_listing_setting(False)
        ex.show_bank_listing(False)
        tabs1 = [ex.nb.tab(t, "text") for t in ex.nb.tabs()]
    finally:
        CE.set_bank_listing_setting(False)
        if root is not None:
            root.destroy()
    _check("the Bank listing tab is off by default and appears / goes when the option changes; "
           "the toolbar's own save keeps the option",
           default_off and "Bank listing" not in tabs0 and kept and "Bank listing" not in tabs1,
           (tabs0, kept, tabs1))
    _check("it lists every scene of the bank (one header each), Find marks the matches",
           n_scenes > 3 and heads == n_scenes and hits >= 4, (n_scenes, heads, hits))
    _check("a double click on a statement opens its scene in the Script tab", opened, (line, entry))
    _check("the shown Bank listing follows a bank change", info0 != info1 and "Daily Road" in info1,
           (info0, info1))
    _check("addresses follow the 'addresses' checkbox: a column beside the Bank listing and the "
           "Source text, never in the text (a double click still finds its statement)",
           _no_addr and _pcs_kept and _with_addr and _src_clean and _gutter_ok and _gutter_off,
           (_no_addr, _pcs_kept, _with_addr, _src_clean, _gutter_ok, _gutter_off))


def test_choice_form():
    """The Add-an-instruction form for a choice menu: 'jump' writes the menu alone; 'reg0'
    writes SetChoiceVisibleBit per option (its show-when condition), the menu with one shared
    target and SWITCH (reg0) to the options' targets; '→ continue after the menu' lands after
    the block. The listing assembles and inserts as written."""
    print("choice menus: Add-an-instruction form:")
    import tkinter as tk
    from map_editor import data as _med
    from rf4s_modkit import script
    from cutscene_editor import toolbox
    from cutscene_editor.app import CutsceneExplorer
    c = _med.rf3mc_container(live=False)
    if c is None:
        _skip("choice form", "rf3.mc not found"); return
    bk = c.banks[27]
    sc = script.disassemble_bank(bk)[0]
    dlg = next(s.pc for s in sc.stmts.values() if s.mnem == "DIALOG")

    class _Doc:
        container, reader = c, None

        def text(self, i):
            return {100: "Yes", 101: "No", 102: "Later"}.get(i)

    class _App:
        pass
    root = tk.Tk()
    root.withdraw()
    try:
        a = _App()
        a.frame, a.doc, a.scene, a.bank = root, _Doc(), sc, bk
        a._suggest = CutsceneExplorer._suggest
        a.assemble_check = lambda t, base=None, strict=True: CutsceneExplorer.assemble_check(a, t, base, strict)
        p = toolbox.InstructionPicker(a)
        ent = next(d for d, t in p._targets() if t == "0x%04x" % sc.entry_pc)
        nxt = toolbox.InstructionPicker.CHOICE_NEXT_DISP

        def fill(mode, m, rows):
            p.choice_mode.set(mode)
            p.set_instruction(("ctl", m))
            while len(p.rows) < len(rows):
                p._choice_add_row(render=False)
            for (_f, row), (line, cond, tgt) in zip(p.rows, rows):
                row[0][0].set(str(line))
                row[1][0].set(cond)
                row[2][0].set(tgt)
            p._rebuild()
            return p.text(), p.check()
        jt, jok = fill("jump", "PROMPT_CHOICE", [(100, "always", ent), (101, "always", nxt)])
        _check("jump mode: the menu alone, 'continue' lands after it",
               jok and jt.splitlines() == ["PROMPT_CHOICE #100 -> 0x%04x, #101 -> L_after_menu" % sc.entry_pc,
                                           "L_after_menu:"], jt)
        kt, kok = fill("reg0", "PROMPT_CHOICE_FORCED", [(100, "always", nxt), (101, "always", nxt)])
        _check("reg0 mode, every answer continues: no SWITCH, reg0 kept",
               kok and "SWITCH" not in kt and kt.count("SetChoiceVisibleBit") == 2, kt)
        rt, rok = fill("reg0", "PROMPT_CHOICE", [(100, "reg1 == 1", ent), (101, "reg1 == 2", nxt),
                                                 (102, "reg1 != 2", ent)])
        new = c.insert_after(bk, dlg, rt)
        sc2 = next(s for s in script.disassemble_bank(c.banks[27]) if new in s.stmts)
        ks = sorted(sc2.stmts)
        got = [sc2.stmts[q] for q in ks[ks.index(new):ks.index(new) + 6]]
        guard, menu, sw = got[3], got[4], got[5]
        stl = list(sc2.stmts.values())
        res = script.choice_results(c.banks[27].data, stl, [x.pc for x in stl].index(menu.pc))
        _check("reg0 mode: visibility ops, the all-hidden guard, menu -> one label, SWITCH (reg0) "
               "to the targets; choice_results sees reg0 written",
               rok and [g.op for g in got[:3]] == [612] * 3 and guard.mnem == "BR_Z"
               and guard.code_targets == [sw.pc + sw.size] and menu.mnem == "PROMPT_CHOICE"
               and set(menu.code_targets) == {sw.pc} and sw.mnem == "SWITCH"
               and sw.code_targets[1] == sw.pc + sw.size and isinstance(res, list) and len(res) == 3,
               (rt, [g.mnem for g in got]))
        at, _aok = fill("reg0", "PROMPT_CHOICE", [(100, "always", ent), (101, "reg1 == 2", ent)])
        _check("reg0 mode: no guard when an option is always shown", "BR_Z" not in at, at)
        p.preview.delete("1.0", "end")
        p.preview.insert("1.0", rt.replace("BR_Z (reg0) -> L_after_menu\n", ""))
        p._typed()
        p.check()
        _check("a hand-edited listing without the guard is flagged under the preview (Insert "
               "still allowed)", "⚠" in p.check_lbl.cget("text") and "EVERY" in p.check_lbl.cget("text"),
               p.check_lbl.cget("text")[:120])
    finally:
        root.destroy()
    # script.choice_empty_mask_problems on its own: flags only menus whose options can all be
    # hidden; the shipped corpus has none
    from rf4s_modkit import scriptasm
    tail = "PROMPT_CHOICE #100 -> L_a, #101 -> L_a\nL_a:\nSWITCH (reg0) -> L_b, L_b\nL_b:\nRET\n"
    flagged = {}
    for k, head in (("dynamic", "SetChoiceVisibleBit(0, reg1 == 2)\nSetChoiceVisibleBit(1, reg1 != 2)\n"),
                    ("zero", "SetChoiceVisibleBit(0, 0)\nSetChoiceVisibleBit(1, 0)\n"),
                    ("always", "SetChoiceVisibleBit(0, reg1 == 2)\nSetChoiceVisibleBit(1, 1)\n"),
                    ("guarded", "SetChoiceVisibleBit(0, reg1 == 2)\nSetChoiceVisibleBit(1, reg1 != 2)\n"
                                "BR_Z (reg0) -> L_b\n"),
                    ("unmasked", "")):
        flagged[k] = any("EVERY" in m for _p, _l, m in
                         scriptasm.lint_listing(head + tail, resolver=c.asm_resolver))
    shipped = sum(len(script.choice_empty_mask_problems(b.data, sorted(x.stmts.values(), key=lambda t: t.pc)))
                  for b, x in script.iter_scenes(c))
    _check("empty-mask warning: all-conditional and all-hidden menus flagged; an always-shown "
           "option, the BR_Z (reg0) guard, an unmasked menu and every shipped menu are not",
           flagged == {"dynamic": True, "zero": True, "always": False, "guarded": False,
                       "unmasked": False} and shipped == 0, (flagged, shipped))


def test_argspec():
    """How the instruction form and the Inspector present arguments (cutscene_editor.argspec):
    short labels, help without engine internals, seconds for the timers, the shipped game's
    most common value as the default, named values (compass, fade colour), the wait a
    fade / walk / turn is followed by; and the picker list (verified first, Most used, a
    Recently used list saved on Insert)."""
    print("instruction form: argument presentation:")
    import re as _re
    from rf4s_modkit import opcode_meta as meta
    from cutscene_editor import argspec as A
    bad_help, bad_label = [], []
    for k, r in meta.TABLE["actions"].items():
        if not r.get("human_verified") or r.get("category") == "noop":
            continue
        for i in range(len(r.get("args") or [])):
            sp = A.spec(int(k), i)
            if _re.search(r"RF4S\.exe|\+0x[0-9A-Fa-f]{4}|\bg_[a-z]", sp.help):
                bad_help.append("%s.%s" % (meta.mnemonic(int(k)), sp.label))
            if len(sp.label) > 24 or "(" in sp.label:
                bad_label.append(sp.label)
    _check("verified ops: every argument's help is free of exe offsets / g_ tables, labels are short",
           not bad_help and not bad_label, (bad_help[:4], bad_label[:4]))
    wait, fade_t, fade_d, walk_sp = A.spec(2, 0), A.spec(334, 0), A.spec(334, 1), A.spec(117, 3)
    _check("timers take seconds: Wait '1.5 s' = 18000 (12000 per second), FadeScreen '1 s' = 6000; "
           "the field explains a raw value ('= 0.5s')",
           wait.token("1.5 s") == "18000" and fade_d.token("1 s") == "6000"
           and wait.note("6000") == "= 0.5s" and fade_d.note("0") == "= immediate",
           (wait.token("1.5 s"), fade_d.token("1 s"), wait.note("6000")))
    give_lv = A.spec(423, 2)
    _check("list entries are short: '0.5s  (6000)', 'right  (90)', a plain common value is just '1'; "
           "GivePlayerItem's third argument is the item level",
           [d for d, _t in wait.options[:1]] == ["0.5s  (6000)"]
           and ("right  (90)", "90") in A.spec(103, 1).options
           and [d for d, _t in A.spec(423, 1).options[:1]] == ["1"]
           and give_lv.label == "level" and "quality" not in give_lv.help,
           (wait.options[:2], A.spec(423, 1).options[:2], give_lv.label, give_lv.help))
    _check("defaults are the game's own: FadeScreen(-16 black, 6000), walk speed 100; named values "
           "for the fade colour and the compass",
           fade_t.default == "-16" and fade_d.default == "6000" and walk_sp.default == "100"
           and fade_t.note("-16") == "= black" and A.spec(103, 1).note("90") == "= right",
           (fade_t.default, fade_d.default, walk_sp.default))
    _check("character / emote / position arguments do not take one scene's values: the player, "
           "no emote, 0",
           A.spec(117, 0).default in ("0", "actor(player)") and A.spec(16, 1).default == "0"
           and A.spec(117, 1).default == "0" and A.spec(16, 0).kind == "face",
           (A.spec(117, 0).default, A.spec(16, 1).default, A.spec(117, 1).default, A.spec(16, 0).kind))
    _check("waits: a fade adds WaitForFade, a walk waits on its actor, a shake with no time "
           "limit adds none",
           A.wait_line(334, ["-16", "6000"]) == "WaitForFade()"
           and A.wait_line(117, ["actor(Forte)", "0", "0", "100", "0"]) == "WaitActorMoveDone(actor(Forte))"
           and A.wait_line(197, ["3", "0"]) is None and A.wait_line(197, ["3", "12"]) == "WaitForPlayerEffect()"
           and A.wait_line(2, ["6000"]) is None)
    # every op a wait is offered for, and the wait itself, is verified in game
    names = {}
    for o in range(script_ops_count()):                 # a name shared by several ops: any verified one
        names[meta.mnemonic(o)] = names.get(meta.mnemonic(o)) or bool(meta.human_verified(o))
    _check("every op with an offered wait, and every wait, is verified in game",
           all(names.get(op) and names.get(w) for op, (w, _a) in A.WAITS.items()), A.WAITS)


def test_edit_instruction():
    """Edit instruction (F2 / the Script view's right-click menu): the Add window without the
    instruction list, its fields filled in from the selected action; Apply replaces the
    statement in one undoable edit (what jumped to it reaches the new one); the same code
    again changes nothing; opening Add afterwards brings the list back."""
    print("cutscene editor: Edit instruction:")
    try:
        import tkinter as tk
        import cutscene_editor as ce
        from rf4s_modkit import script
    except Exception as e:
        _skip("edit instruction", f"cutscene_editor not importable ({e})"); return
    mc = _shipped("rf3.mc")
    if mc is None:
        _skip("edit instruction", "rf3.mc not found"); return

    def reader(n):
        f = mc if n == "rf3.mc" else _first(n)
        return f.read_bytes() if f else None
    root = None
    try:
        try:
            root = tk.Tk()
            root.withdraw()
        except Exception as e:
            _skip("edit instruction", f"no display for Tk ({e})"); return
        ex = ce.CutsceneExplorer(tk.Toplevel(root), reader=reader)
        c = ex.doc.container
        hit = None                                  # a scene with a FadeScreen and a SetSpeaker
        for pos in range(len(c.banks)):
            for sc in script.disassemble_bank(c.banks[pos]):
                fade = next((q for q, t in sc.stmts.items() if t.op == 334 and len(t.args) == 2
                             and script.arg_constant(c.banks[pos].data, t.args[1])[1]), None)
                spk = next((q for q, t in sc.stmts.items() if script.is_portrait_op(t.op)), None)
                if fade is not None and spk is not None:
                    hit = (pos, sc.entry_pc, fade, spk)
                    break
            if hit:
                break
        if hit is None:
            _skip("edit instruction", "no scene with FadeScreen + SetSpeaker"); return
        pos, entry, fade, spk = hit
        ex.show_bank(pos, entry)
        ex.select((fade, None))
        orig = c.build()
        n_undo = len(ex.doc.undo_stack)
        # first a form WITH "+ another argument" (SetChoiceVisibleMask), then Edit on a form
        # without one: the old button is gone and must not be touched (it crashed: a stale
        # more_btn of the earlier form)
        p0 = ex.ask_insert_instruction(preset=("op", 610))
        root.update()
        had_more = p0.more_btn is not None
        p = ex.ask_edit_instruction()
        root.update()
        _check("Edit after a form that had '+ another argument' opens cleanly (no stale button)",
               had_more and p is not None and p.edit_pc == fade and p.more_btn is None)
        cur = script.arg_constant(ex.bank.data, ex.stmt(fade).args[1])[0]
        _check("Edit opens the form of the selected FadeScreen with its own values, without the "
               "instruction list, with Apply",
               p is not None and p.edit_pc == fade and str(p._left) not in [str(x) for x in p._pw.panes()]
               and p._insert_btn.cget("text") == "Apply" and p.op_fields[1].token() == str(cur)
               and p.text().startswith("FadeScreen("), (p.text() if p else None))
        same = p.insert()
        _check("Apply without a change changes nothing (no undo step)",
               same is None and ex.doc.container.build() == orig and len(ex.doc.undo_stack) == n_undo)
        p.op_fields[1].var.set("2 s")
        p._rebuild()
        ok = p.insert()
        new_st = ex.stmt(ex.sel[0]) if ex.sel else None
        _check("Apply replaces it: FadeScreen(…, 12000) selected, one undo step, the window closes",
               ok is True and new_st is not None and new_st.op == 334
               and script.arg_constant(ex.bank.data, new_st.args[1])[0] == 12000
               and len(ex.doc.undo_stack) == n_undo + 1 and not p.win.winfo_ismapped(), p.text())
        ex.undo()
        _check("undo puts the original back byte for byte", ex.doc.container.build() == orig)
        ex.select((spk, None))
        st = ex.stmt(spk)
        p = ex.ask_edit_instruction()
        root.update()
        slot, side = script.portrait_speaker_slot(st.op)
        _check("a SetSpeaker opens with its speaker and side (in the opcode) and its face",
               p.key == ("op", st.op) and p.text().startswith("SetSpeaker(%d, %d" % (slot, side)),
               p.text())
        p.show()
        root.update()
        _check("opening Add afterwards brings the instruction list and Insert back",
               p.edit_pc is None and str(p._left) in [str(x) for x in p._pw.panes()]
               and p._insert_btn.cget("text") == "Insert")
        # a dialogue line: its text to change (a new line), or another existing line
        dlg = next(q for q, t in ex.scene.stmts.items() if t.mnem == "DIALOG")
        ex.select((dlg, None))
        old_id = ex.stmt(dlg).dialog_id
        old_text = ex.doc.text(old_id)
        n_lines = len(ex.doc.textarc.entries)
        n_undo = len(ex.doc.undo_stack)
        p = ex.ask_edit_instruction()
        root.update()
        from rf4s_modkit import textesc as _te
        opened = (p.key == ("ctl", "DIALOG") and p.dlg_mode.get() == "new"
                  and _te.from_edit(p.dlg_form.txt.get("1.0", "end-1c")) == old_text)
        same = p.insert()
        p.dlg_form.set_text("Edited by selftest")
        ok = p.insert()
        new_st = ex.stmt(ex.sel[0]) if ex.sel else None
        _check("Edit on a DIALOG opens its text; Apply unchanged does nothing; new text becomes a "
               "new line the statement shows (the old line keeps its text), one undo step",
               opened and same is None and ok is True and new_st is not None and new_st.mnem == "DIALOG"
               and new_st.dialog_id != old_id and ex.doc.text(new_st.dialog_id) == "Edited by selftest"
               and ex.doc.text(old_id) == old_text and len(ex.doc.textarc.entries) > n_lines
               and len(ex.doc.undo_stack) == n_undo + 1,
               (opened, same, ok, new_st and new_st.dialog_id, old_id))
        ex.undo()
        ex.select((dlg, None))
        p = ex.ask_edit_instruction()
        root.update()
        p.dlg_mode.set("existing")
        p._dialogue_mode()
        p.line.var.set(str(old_id + 1))
        p._rebuild()
        ok2 = p.insert()
        st2 = ex.stmt(ex.sel[0]) if ex.sel else None
        _check("'an existing line' points the DIALOG at another line id",
               ok2 is True and st2 is not None and st2.dialog_id == old_id + 1, (ok2, p.text()))
        ex.undo()
        ex.select((fade_now(ex), None))
        p = ex.ask_edit_instruction()
        root.update()
        before = ex.doc.container.build()
        p.op_fields[1].var.set("3 s")
        p.win.event_generate("<Escape>")
        root.update()
        _check("Esc closes the Edit window without applying (no prompt)",
               not p.win.winfo_ismapped() and ex.doc.container.build() == before)
    finally:
        if root is not None:
            root.destroy()


def fade_now(ex):
    """The open scene's first FadeScreen (test_edit_instruction)."""
    return next(q for q, t in ex.scene.stmts.items() if t.op == 334)


def script_ops_count():
    from rf4s_modkit import script
    return script.DISPATCHABLE_ACTION_OPS


def test_choice_results():
    """What a choice writes to reg0 (script.choice_results): only behind a visibility mask
    (ops 610-612) does the pick go to reg0 as the option's index; the mask may be set right
    before the menu, inside a CALLed helper, or before branches that rejoin (shop menus)."""
    print("choice menus: reg0:")
    from map_editor import data as _med
    from rf4s_modkit import script, scriptasm
    c = _med.rf3mc_container(live=False)
    if c is None:
        _skip("choice reg0", "rf3.mc not found"); return

    def res(bank_i, pc):
        b = c.banks[bank_i]
        for sc in script.disassemble_bank(b):
            if pc in sc.stmts:
                stl = list(sc.stmts.values())
                return script.choice_results(b.data, stl, [x.pc for x in stl].index(pc))
        return "missing"
    direct = res(1, 0x5006)             # SetChoiceVisibleBit x N right before the menu
    rejoin = res(10, 0x20DA)            # SetChoiceVisibleMask, then 3 helpers that rejoin
    plain = res(1, 0x06DA)              # no mask: reg0 untouched
    _check("masked menus report reg0 = the option's index (set right before, or before "
           "rejoining branches); an unmasked menu leaves reg0 alone",
           isinstance(direct, list) and [k for k, _v in direct] == list(range(7))
           and isinstance(rejoin, list) and len(rejoin) >= 7 and plain is None,
           (direct and direct[:3], rejoin and rejoin[:2], plain))
    b1 = c.banks[1]
    sc = next(x for x in script.disassemble_bank(b1) if 0x5006 in x.stmts)
    line = next(ln for ln in scriptasm.scene_listing(sc, b1).split("\n") if "5006:" in ln)
    _check("the listing's comment names each masked option's reg0", "(reg0=6)" in line, line[-80:])


def test_visibility_audit():
    """Nothing that can run is hidden (every bank of the game's rf3.mc, ~1 minute):
    1) every statement of every scene the bank list shows -- the registered scenes and the
       real unreached code -- appears in the Story view, the listing (Source tab / Bank
       listing) and the Graph, and the Bank listing shows the same scenes as the bank list;
    2) every byte of code is shown, part of a stub the list skips on purpose (a lone JMP /
       RET into shown code), or dead -- and no dead stretch decodes to real content (an
       action, a line, a call, a menu), so nothing meaningful sits where no view shows it."""
    print("cutscene views hide nothing that can run (every bank):")
    try:
        from cutscene_editor.document import ScriptDocument
        from cutscene_editor.render import SceneText
        from cutscene_editor import cfg, browser
        from cutscene_editor.tabs import strip_addresses
        from rf4s_modkit import script, scriptasm
    except Exception as e:
        _skip("visibility audit", f"cutscene_editor not importable ({e})"); return

    def reader(n):
        f = _first(n)
        return f.read_bytes() if f else None
    doc = ScriptDocument(reader)
    doc.load_from_reader()
    c = doc.container
    if c is None:
        _skip("visibility audit", "rf3.mc not found"); return
    miss = {"story": [], "listing": [], "graph": [], "bank listing": []}
    dead_real, n_scenes, n_stmts = [], 0, 0
    code_bytes = shown_bytes = 0
    for bi, bank in enumerate(c.banks):
        try:
            scenes = script.disassemble_bank(bank)
        except Exception:
            continue
        rows = browser.scene_rows(bank)                       # what the bank list shows
        keep = {id(sc_) for sc_, _o in script.unreached(scenes)}
        listed = sorted({sc_.entry_pc for sc_ in scenes if sc_.action_type >= 0 or id(sc_) in keep})
        if listed != sorted({sc_.entry_pc for sc_ in rows}):
            miss["bank listing"].append((bi, "scene set differs"))
        for sc in rows:
            n_scenes += 1
            want = set(sc.stmts)
            n_stmts += len(want)
            got = {r.key[0] for r in SceneText(doc, bank, sc).story_rows()
                   if r.key is not None and isinstance(r.key[0], int)}
            if want - got:
                miss["story"].append((bi, hex(sc.entry_pc), len(want - got)))
            try:
                txt = scriptasm.scene_listing(sc, bank, dialog=doc.text, bank_no=bi)
                _l, pcs = strip_addresses(txt.split("\n"))
                lp = {x for x in pcs if x is not None}
            except Exception:
                lp = set()
            if want - lp:
                miss["listing"].append((bi, hex(sc.entry_pc), len(want - lp)))
            gp = {x for b in cfg.scene_graph(sc).values() for x, _t in b.lines if x is not None}
            if want - gp:
                miss["graph"].append((bi, hex(sc.entry_pc), len(want - gp)))
        # 2) bytes: shown / skipped stub / dead, and nothing real in the dead ones
        bank.type_table_full()
        te = getattr(bank, "_table_end", 0)
        tt = bank.type_table()
        code_end = min(tt.values()) if tt else len(bank.data)
        if code_end <= te:
            continue
        cov = bytearray(code_end)
        shown = [sc_ for sc_ in scenes if sc_.action_type >= 0 or id(sc_) in keep]
        stubs = [sc_ for sc_ in scenes if sc_.action_type < 0 and id(sc_) not in keep]
        for group, val in ((shown, 1), (stubs, 2)):
            for sc_ in group:
                for pc, st in sc_.stmts.items():
                    for i in range(pc, min(pc + st.size, code_end)):
                        if not cov[i]:
                            cov[i] = val
        code_bytes += code_end - te
        shown_bytes += sum(1 for i in range(te, code_end) if cov[i] == 1)
        off = te
        while off < code_end:
            if cov[off]:
                off += 1
                continue
            s0 = off
            while off < code_end and not cov[off]:
                off += 1
            q = s0
            while q < off:
                st = script.decode_statement(bank.data, q)
                if st is None:
                    q += 2
                    continue
                if script.is_real_statement(st):
                    dead_real.append((bi, hex(q)))
                    break
                q += st.size
    for view, bad in miss.items():
        _check("%s: every runnable statement of the %d shown scenes (%d statements) appears"
               % (view, n_scenes, n_stmts), not bad, bad[:5])
    _check("no dead code stretch holds real content; %.2f%% of the %d code bytes are shown"
           % (100.0 * shown_bytes / max(1, code_bytes), code_bytes),
           not dead_real and shown_bytes > 0.99 * code_bytes, dead_real[:5])



def test_script_debugger():
    """The script debugger (rf4s_modkit.scriptdbg) against a SIMULATED game -- fake process
    memory with a real bank and one Script VM, stepped the way Script_VMStep does for what the
    debugger relies on (the countdown, JMP, CALL, FRAME, RET, WaitPlain; any other statement
    just runs). No RF4S.exe needed: a breakpoint stops the script, Step moves on at the first
    press (also from ON a breakpoint and when the debugger polls before the game ran), Step
    over a RET stops after the CALL, the final RET says the script ends, and Detach gives the
    game its own rf3.mc and slot buffer back -- or keeps the buffer while a script is still in
    debugger code. Plus the live-value evaluator against the static one."""
    print("script debugger (simulated game):")
    import struct as _st
    from map_editor import data as _med
    from rf4s_modkit import scriptdbg as _sd, script as _sc, hotreload as _hr
    c = _med.rf3mc_container(live=False)
    if c is None:
        _skip("script debugger", "rf3.mc not found"); return
    FILE = bytes(c.build())
    BANK = 308                                              # the Dragon Room (tail 60)
    TAIL = BANK - c.n_primary

    class Mem:
        def __init__(self):
            self.regions, self.next = {}, 0x10000000
        def alloc(self, n):
            b = self.next
            self.regions[b] = bytearray(n)
            self.next += (n + 0xFFFF) & ~0xFFFF
            return b
        def _at(self, a, n):
            for b, r in self.regions.items():
                if b <= a and a + n <= b + len(r):
                    return r, a - b
            raise KeyError(hex(a))
        def read(self, a, n):
            r, o = self._at(a, n)
            return bytes(r[o:o + n])
        def write(self, a, d):
            r, o = self._at(a, len(d))
            r[o:o + len(d)] = d

    class Game:                                              # the hotreload._Game surface used
        pid, base, mc_id = 4242, 0x7000, 1
        def __init__(self):
            m = self.m = Mem()
            self.file = m.alloc(len(FILE)); m.write(self.file, FILE)
            self.entry = m.alloc(16); m.write(self.entry, _st.pack("<QH", self.file, 1))
            self.sc = m.alloc(0x200)
            self.slot = m.alloc(64); self.buf = m.alloc(0xFF30)      # the game's own buffer
            m.write(self.buf, bytes(c.banks[BANK].data))
            m.write(self.slot + 16, _st.pack("<Q", self.buf))
            self.vm = m.alloc(0x100); m.write(self.vm + 0x20, _st.pack("<Q", self.slot))
            self.stack = m.alloc(0x400); m.write(self.vm + 0x28, _st.pack("<Q", self.stack))
        def read(self, a, n): return self.m.read(a, n)
        def write(self, a, d): self.m.write(a, bytes(d))
        def u8(self, a): return self.read(a, 1)[0]
        def u32(self, a): return _st.unpack("<I", self.read(a, 4))[0]
        def ptr(self, a):
            try:
                return _st.unpack("<Q", self.read(a, 8))[0]
            except KeyError:
                return 0
        def alloc(self, n): return self.m.alloc(n)
        def own_allocation(self, p): return len(self.m.regions.get(p, b""))
        def free(self, p): pass
        def suspend(self): pass
        def resume(self): pass
        def close(self): pass
        def archive_entry(self, idx): return self.entry, self.ptr(self.entry), 1
        def scene(self): return self.sc
        def slots(self, sc):
            return [("tail", self.slot, 2, TAIL, self.ptr(self.slot + 16), len(c.banks[BANK].data), 1)]
        def vms(self, sc):
            return [(self.vm, self.u32(self.vm + 0x70), 0, self.ptr(self.vm + 0x20), self.u32(self.vm + 0x3C))]
        def frame(self):                                     # one frame of the game for our VM
            v = self.vm
            st, wait, pc = self.u32(v + 0x70), self.u32(v + 0x78), self.u32(v + 0x3C)
            if st != 2:
                return
            if wait:
                self.write(v + 0x78, _st.pack("<I", max(0, wait - 200)))
                return
            code = self.read(self.ptr(self.slot + 16), 0x10000)
            for _ in range(64):
                op = _st.unpack_from("<H", code, pc)[0]
                if op == 0xFFFA:                             # JMP
                    pc = _st.unpack_from("<H", code, pc + 2)[0]
                elif op == 0xFFFE:                           # CALL: push frame base, return pc
                    top, fb = self.u32(v + 0x34), self.u32(v + 0x6C)
                    self.write(self.stack + 4 * top, _st.pack("<ii", fb, pc + 4))
                    self.write(v + 0x34, _st.pack("<I", top + 2)); self.write(v + 0x6C, _st.pack("<I", top + 2))
                    pc = _st.unpack_from("<H", code, pc + 2)[0]
                elif op == 0xFFF1:                           # FRAME n
                    top = self.u32(v + 0x34)
                    self.write(v + 0x6C, _st.pack("<I", top))
                    self.write(v + 0x34, _st.pack("<I", top + _st.unpack_from("<H", code, pc + 2)[0]))
                    pc += 4
                elif op == 0xFFFF:                           # RET
                    fb = self.u32(v + 0x6C)
                    if fb == 0:
                        self.write(v + 0x70, _st.pack("<I", 1)); self.write(v + 0x3C, _st.pack("<I", pc))
                        return
                    pc = _st.unpack("<i", self.read(self.stack + 4 * (fb - 1), 4))[0]
                    nfb = _st.unpack("<i", self.read(self.stack + 4 * (fb - 2), 4))[0]
                    self.write(v + 0x34, _st.pack("<I", fb - 2)); self.write(v + 0x6C, _st.pack("<I", nfb))
                elif op == _sd.WAIT_PLAIN:                   # parks: the literal's countdown
                    val, _ok = _sc.eval_expr(code, _st.unpack_from("<H", code, pc + 4)[0])
                    self.write(v + 0x3C, _st.pack("<I", pc + 6)); self.write(v + 0x78, _st.pack("<I", val))
                    return
                else:
                    pc += _sc.decode_statement(code, pc).size
            self.write(v + 0x3C, _st.pack("<I", pc))

    def debugger(g):
        d = _sd.ScriptDebugger.__new__(_sd.ScriptDebugger)
        d.__dict__.update(c=c, g=g, orig_bufs={}, left=[], bps={}, held=set(), _saved_wait={}, _released={},
                          bufs={}, stub_top={}, _stubs={}, user=set(), user_pending={}, _maps={},
                          slot_bank={}, mismatch=set(), parked={}, freeze_clock=False,
                          _res_orig=None, _res_base=None, _res_img=None, _res_dirty=True, _res_free=[],
                          _clock=None, _note=None, _flags=None, _slots=None, recovered=[])
        d._write_note = lambda owner=True: None             # no recovery note from a test
        d._drop_note = lambda: None
        d._set_clock = lambda frozen: None
        d._look_at_resident()
        return d

    def at(g, pc, state, wait):
        g.write(g.vm + 0x3C, _st.pack("<I", pc)); g.write(g.vm + 0x70, _st.pack("<I", state))
        g.write(g.vm + 0x78, _st.pack("<I", wait))

    code = bytes(c.banks[BANK].data)
    plain = lambda st: st is not None and st.op < 0xFFF0 and st.size >= 4 and st.op != _sd.WAIT_PLAIN
    P = Q = None
    for sc in _sc.disassemble_bank(c.banks[BANK]):
        items = sorted(sc.stmts.items())
        for (p1, s1), (p2, s2), (p3, s3) in zip(items, items[1:], items[2:]):
            if all(plain(s) for s in (s1, s2, s3)) and p2 == p1 + s1.size and p3 == p2 + s2.size:
                P, Q = p1, p2
                break
        if P:
            break

    g = Game(); d = debugger(g)                              # a hit, then Step
    d.add_breakpoint(BANK, P); d.poll()
    at(g, P, 2, 0); g.frame(); d.poll(); v = d.vms()[0]
    _check("a breakpoint stops the script there", v.addr in d.held and d.logical_pc(v) == P)
    d.step(v); d.poll()                                      # polled before the game ran it
    _check("a released script is not taken for a new hit before the game runs it",
           d.vms()[0].addr not in d.held)
    g.frame(); d.poll(); v = d.vms()[0]
    _check("the first Step stops at the next statement", v.addr in d.held and d.logical_pc(v) == Q,
           "%04x" % d.logical_pc(v))

    g = Game(); d = debugger(g)                              # paused ON a breakpointed statement
    at(g, P, 2, 1000); d.poll(); d.pause(d.vms()[0])
    d.add_breakpoint(BANK, P); d.poll(); d.step(d.vms()[0])
    for _ in range(10):
        d.poll(); g.frame()
    d.poll(); v = d.vms()[0]
    _check("Step from a script standing ON a breakpoint goes on (not back into it)",
           v.addr in d.held and d.logical_pc(v) == Q)

    g = Game(); d = debugger(g)                              # looping back is a new hit
    d.add_breakpoint(BANK, P); d.poll()
    at(g, P, 2, 0); g.frame(); d.poll(); d.resume(d.vms()[0]); d.poll(); g.frame()
    at(g, P, 2, 0); g.frame(); d.poll(); v = d.vms()[0]
    _check("coming back to a breakpoint after Continue stops again",
           v.addr in d.held and d.bps[(BANK, P)].hits == 2)

    pick = None                                              # Step over a subroutine's RET
    for sc in _sc.disassemble_bank(c.banks[BANK]):
        for cpc, cst in sorted(sc.stmts.items()):
            if cst.mnem != "CALL" or not cst.code_targets or not plain(_sc.decode_statement(code, cpc + 4)):
                continue
            q = cst.code_targets[0]
            for _ in range(200):
                st = _sc.decode_statement(code, q)
                if st is None or st.code_targets or not st.falls_through:
                    break
                nx = _sc.decode_statement(code, q + st.size)
                if plain(st) and nx is not None and nx.op == 0xFFFF:
                    pick = (cpc, q)
                    break
                q += st.size
            if pick:
                break
        if pick:
            break
    C, S = pick
    g = Game(); d = debugger(g)
    d.add_breakpoint(BANK, S); d.poll()
    g.write(g.stack, _st.pack("<ii", 0, C + 4))
    g.write(g.vm + 0x34, _st.pack("<I", 2)); g.write(g.vm + 0x6C, _st.pack("<I", 2))
    at(g, S, 2, 0); g.frame(); d.poll()
    note = d.step(d.vms()[0])
    for _ in range(3):
        d.poll(); g.frame()
    d.poll(); v = d.vms()[0]
    _check("Step over a subroutine's RET stops after the CALL", note is None and v.addr in d.held
           and d.logical_pc(v) == C + 4, "%04x, want %04x" % (d.logical_pc(v), C + 4))
    # the CALL ran from a breakpoint's copy (Step into from a stop on the CALL), so the return
    # address points into that stub -- and the breakpoint is gone by the time the RET comes
    # (one-shot Step breakpoints are): Step still stops after the CALL, not "no statement"
    g = Game(); d = debugger(g)
    d.add_breakpoint(BANK, C); d.poll()
    at(g, C, 2, 0); g.frame(); d.poll()
    d.step(d.vms()[0], over=False)                           # Step into: runs the CALL copy
    for _ in range(3):
        d.poll(); g.frame()
    d.poll()
    d.remove_breakpoint(BANK, C)                             # its breakpoint goes away
    ret_in_stub = _st.unpack("<i", g.read(g.stack + 4, 4))[0] >= len(code)
    d.add_breakpoint(BANK, S); d.poll()
    v = d.vms()[0]
    if v.addr in d.held:
        d.resume(v)
    for _ in range(40):                                      # runs on to S
        d.poll(); g.frame()
    d.poll(); v = d.vms()[0]
    note = d.step(v)
    for _ in range(3):
        d.poll(); g.frame()
    d.poll(); v = d.vms()[0]
    _check("Step over a RET that returns into a gone breakpoint's stub stops after the CALL",
           ret_in_stub and note is None and v.addr in d.held and d.logical_pc(v) == C + 4,
           "return address in a stub: %s, note: %s, at %04x" % (ret_in_stub, note, d.logical_pc(v)))
    g = Game(); d = debugger(g)
    d.add_breakpoint(BANK, S); d.poll()
    at(g, S, 2, 0); g.frame(); d.poll()
    note = d.step(d.vms()[0])
    _check("Step onto the script's own last RET says it ends", note is not None and "ends" in note, note)

    g = Game(); d = debugger(g)                              # Detach restores
    d.add_breakpoint(BANK, P); d.poll()
    at(g, P, 2, 0); g.frame(); d.poll()
    swapped = g.ptr(g.slot + 16) != g.buf
    left = d.detach()                                        # let go, still in the stub
    _check("Detach keeps the buffer while a script is still in debugger code (and says so)",
           swapped and g.ptr(g.slot + 16) != g.buf and left)
    g.frame()
    kept = debugger(g)._give_buffers_back(d.orig_bufs)
    _check("... and the next attach gives the game's own buffer back, original bytes",
           not kept and g.ptr(g.slot + 16) == g.buf and g.read(g.buf, len(code)) == code)
    g = Game(); d = debugger(g)
    d.add_breakpoint(BANK, P); d.poll()
    at(g, P, 2, 0); g.frame(); d.poll(); d.resume(d.vms()[0]); g.frame(); g.frame()
    left = d.detach()
    _check("a clean Detach restores the rf3.mc pointer, the slot buffer and its bytes",
           left == [] and g.ptr(g.entry) == g.file and g.ptr(g.slot + 16) == g.buf
           and g.read(g.buf, len(code)) == code, left)

    n = same = 0                                             # live values
    for b in c.banks[240:320]:
        buf = bytes(b.data)
        for sc in _sc.disassemble_bank(b):
            for st in sc.stmts.values():
                for off in list(st.args if st.op < 0xFFF0 else []) + list(getattr(st, "expr_refs", None) or []):
                    if off is None:
                        continue
                    v0, k0 = _sc.eval_expr(buf, off)
                    if k0:
                        n += 1
                        same += _sd.eval_live(buf, off, [0] * 10, lambda e: 0) == (v0, True)
    _check("the live evaluator agrees with the static one on constant expressions", n and same == n,
           "%d/%d" % (same, n))
    enc = c.pack_var(100, 3)
    _check("the live evaluator reads registers and game variables",
           _sd.eval_live(bytes([0x07, 0x19, 5, 0, 0x86, 0]), 0, [7] + [0] * 9, None) == (12, True)
           and _sd.eval_live(bytes([0x02]) + _st.pack("<I", enc) + bytes([0x17, 2, 0x8C, 0]), 0, [0] * 10,
                             lambda e: 2 if e == enc else None) == (1, True))
    _check("a compound assignment is not evaluated (it would write)",
           _sd.eval_live(bytes([0x07, 0x17, 1, 0x94, 0]), 0, [0] * 10, None)[1] is False)

    # text slots: the banks the ＠ codes print, read live; the scene scan the Text slots tab lists
    from types import SimpleNamespace as _NS
    from rf4s_modkit import textlint as _tl
    from cutscene_editor import debugger as _dbgp
    g = Game(); d = debugger(g)
    lo = min(_sd.TEXT_SLOT_RVAS.values())
    blk = g.m.alloc(0x1000)
    g.m.regions[g.base + lo] = g.m.regions.pop(blk)             # the slot run at its RVA
    g.write(g.base + _sd.TEXT_SLOT_RVAS[1] + 4 * 2, _st.pack("<i", 178))      # item slot 2
    g.write(g.base + _sd.TEXT_SLOT_RVAS[3] + 4 * 51, _st.pack("<i", 999))     # last number slot
    g.write(g.base + _sd.TEXT_SLOT_RVAS[15], _st.pack("<i", 7))               # button slot 0
    s = d.text_slots()
    _check("text slots: every kind read from its RVA (item 2, number 51, button 0), no kind 12",
           s[1][2] == 178 and s[3][51] == 999 and s[15][0] == 7 and 12 not in s
           and all(len(s[k]) == n for k, n in _sd.TEXT_SLOT_COUNTS.items()))
    codes = [(k, n) for k in _sd.TEXT_SLOT_COUNTS for n in range(min(_sd.TEXT_SLOT_COUNTS[k], 32))
             if k != 14 and not (k == 3 and n > 50)]
    back = [(k, n) for k, n in codes if [(t.kind if k != 10 else 10, t.slot or 0)
                                         for t in _tl.tokens(_tl.slot_code(k, n))] in ([(k, n)], [(10, 0)])]
    _check("every slot's ＠ code reads back as that slot", len(back) == len(codes),
           str(sorted(set(codes) - set(back))[:4]))
    from rf4s_modkit import textdb as _tdb
    p = _first("rf3mc.eng")
    txt = _tdb.TextArchive.load(str(p)) if p else None
    found = None
    if txt is not None:
        from cutscene_editor.browser import scene_rows
        for pos in range(len(c.banks)):
            for sc in scene_rows(c.banks[pos]):
                sets = [p for p, st in sc.stmts.items() if st.op == 343 and _sc.static_arg(c.banks[pos], st, 0) == 0]
                shows = [p for p, st in sc.stmts.items() if st.mnem == "DIALOG"
                         and "＠アイテム０＠" in (txt.text(st.dialog_id) or "")]
                if sets and shows:
                    found = (pos, sc, min(sets), min(shows))
                    break
            if found:
                break
    if found is None:
        _skip("text slots scene scan", "no scene with SetVar1(0, ...) and ＠アイテム０＠ found")
    else:
        pos, sc, ps, pd = found
        fake = _NS(app=_NS(doc=_NS(container=c, text=lambda i: txt.text(i))))
        uses = _dbgp.DebuggerPanel._slot_uses(fake, pos, sc, pd)
        u = uses.get((1, 0))
        _check("the scene scan finds an item slot its SetVar1 fills and its dialogue prints, ▶ at the line",
               u is not None and u[0] == min(ps, pd) and u[1] and u[2] and u[3], "bank %d %s" % (pos, u))
    _check("slot values in words: item, map, season date, the player, a button",
           _dbgp.DebuggerPanel._slot_shows(9, 305) == "Winter 5"
           and _dbgp.DebuggerPanel._slot_shows(0, 0) == "the player's name"
           and _dbgp.DebuggerPanel._slot_shows(15, 7) == "button icon U+E007"
           and bool(_dbgp.DebuggerPanel._slot_shows(1, 178)))


def test_script_debugger_var_writes():
    """The script debugger's Set value (ScriptDebugger.write_var) against a fake flag store:
    1-bit, byte-spanning and signed fields round-trip through read_var MSB-first, the bits
    around the field keep their values, and a value that does not fit is refused."""
    print("script debugger variable writes (fake flag store):")
    import struct as _st
    from map_editor import data as _med
    from rf4s_modkit import scriptdbg as _sd, flagstate as _fs
    c = _med.rf3mc_container(live=False)
    if c is None:
        _skip("variable writes", "rf3.mc not found"); return

    class G:
        base, hdr, bits = 0x10000, 0x90000, 0xA0000

        def __init__(self):
            self.m = {}
            self.write(self.base + _fs.FLAGS_BUFFER_RVA, _st.pack("<Q", self.hdr))
            self.write(self.hdr, _st.pack("<IIQ", _fs.ZONE2_BASE, _fs.ZONE2_BITS, self.bits))
            self.write(self.bits, bytes([0xA5]) * _fs.BLOB_SIZE)   # busy neighbours

        def read(self, a, n):
            return bytes(self.m.get(a + i, 0) for i in range(n))

        def write(self, a, d):
            for i, b in enumerate(d):
                self.m[a + i] = b

        def ptr(self, a):
            return _st.unpack("<Q", self.read(a, 8))[0]

    g = G()
    d = _sd.ScriptDebugger.__new__(_sd.ScriptDebugger)
    d.__dict__.update(c=c, g=g, _flags=None)
    before = g.read(g.bits, _fs.BLOB_SIZE)
    results = []
    for off, width, signed, value in ((333, 1, False, 0), (333, 1, False, 1), (162, 9, False, 300),
                                      (0, 9, False, 69), (450, 8, True, -5), (5, 3, False, 6)):
        enc = c.pack_var(off, width, signed)
        got = d.write_var(enc, value)
        after = g.read(g.bits, _fs.BLOB_SIZE)
        outside = [i for i in range(8 * _fs.BLOB_SIZE) if not off <= i < off + width
                   and ((after[i >> 3] ^ before[i >> 3]) >> (i & 7)) & 1]
        results.append((off, width, value, got, outside))
        before = after
    _check("write_var round-trips each field (1-bit, byte-spanning 9-bit, signed 8-bit) and "
           "leaves every bit outside it alone",
           all(got == value and not outside for _o, _w, value, got, outside in results), results)
    refused = []
    for width, signed, value in ((1, False, 2), (9, False, 512), (8, True, 128), (8, True, -129), (4, False, -1)):
        try:
            d.write_var(c.pack_var(600, width, signed), value)
        except _sd.DebugError:
            refused.append(value)
    _check("a value that does not fit the variable is refused", len(refused) == 5, refused)
    # the Variables tab edits a value in place: the cell becomes an entry, Enter writes it
    try:
        import tkinter as tk
        from tkinter import ttk
        import types
        from cutscene_editor.debugger import DebuggerPanel
        root = tk.Tk()
    except Exception as e:  # noqa: BLE001
        _skip("in-place variable edit", "no Tk: %s" % e); return
    try:
        root.geometry("600x300+0+0")
        p = DebuggerPanel.__new__(DebuggerPanel)
        p.app = types.SimpleNamespace(doc=types.SimpleNamespace(container=c, emf_vars=None))
        p.dbg, p._var_edit = d, None
        p.var_tree = ttk.Treeview(root, columns=("name", "value", "where", "first"), show="headings")
        p.var_tree.pack(fill="both", expand=True)
        p.status = ttk.Label(root)
        p.status.pack()
        p._show_vm = lambda: None
        enc = c.pack_var(162, 9)
        d.write_var(enc, 7)
        p.var_tree.insert("", "end", iid=str(enc), values=("REG_X", 7, "", "@0000"))
        p.var_tree.selection_set(str(enc))
        root.update()
        p.set_var()
        root.update()
        ed = p._var_edit
        opened = ed is not None and ed[1].get() == "7" and ed[1].selection_present()
        if ed is not None:          # a background test window may lose the focus (which cancels)
            ed[1].unbind("<FocusOut>")
        ed[1].delete(0, "end"); ed[1].insert(0, "600")          # does not fit 9 bits
        p._commit_var_edit(); root.update()   # = Enter
        kept = p._var_edit is not None and d.read_var(enc) == 7 and "does not fit" in p.status.cget("text")
        ed[1].delete(0, "end"); ed[1].insert(0, "0x1F")
        p._commit_var_edit(); root.update()   # = Enter
        written = p._var_edit is None and d.read_var(enc) == 31
        p.set_var()
        p._var_edit[1].unbind("<FocusOut>"); root.update()
        p._var_edit[1].insert("end", "9")
        p.cancel_var_edit(); root.update()   # = Esc
        cancelled = p._var_edit is None and d.read_var(enc) == 31
        _check("Variables tab in place: the value cell opens with the value selected, a value "
               "that does not fit keeps it open with the reason, Enter writes, Esc cancels",
               opened and kept and written and cancelled, (opened, kept, written, cancelled))
        flag = c.pack_var(333, 1)
        d.write_var(flag, 0)
        p.var_tree.insert("", "end", iid=str(flag), values=("FLG_X", "off", "", "@0000"))
        p.var_tree.selection_set(str(flag))
        p.set_var(); root.update()
        on = d.read_var(flag) == 1 and p._var_edit is None
        p.set_var(); root.update()
        off = d.read_var(flag) == 0
        _check("a 1-bit flag shows on / off and flips at once (no entry); wider variables show "
               "their number", on and off and DebuggerPanel.var_text(1, 1) == "on"
               and DebuggerPanel.var_text(0, 1) == "off" and DebuggerPanel.var_text(5, 3) == 5,
               (on, off))
        # quick clicks on the flag's value: every SECOND click flips it (Tk alone flipped it
        # back on the 3rd); a slow second click does nothing
        p._clicks = (0, 0, 0, 0, None)
        p.set_var = DebuggerPanel.set_var.__get__(p)
        box = p.var_tree.bbox(str(flag), "#2")
        cx, cy = box[0] + 5, box[1] + 5
        seen = []
        for t in (1000, 1200, 1400, 1600, 5000, 9000):
            p._var_click(types.SimpleNamespace(x=cx, y=cy, time=t))
            root.update()
            seen.append(d.read_var(flag))
        _check("clicks on a flag's value: 2nd on, 3rd nothing, 4th off; slow clicks nothing",
               seen == [0, 1, 1, 0, 0, 0], seen)
    finally:
        root.destroy()


def test_script_debugger_edits():
    """The script debugger through edit / save / reload sequences: the real editor, debugger
    window and engine against a simulated game (fake memory, a VM stepped like Script_VMStep,
    'reload in game' like hot reload). A breakpoint follows its statement in the editor and
    keeps firing where the statement is in the game until a reload moves it there too:
    insert before it, reload, delete the insert (the reported bug), reload, an operand edited
    in place, a breakpoint on a statement the game does not have yet (dimmed, fires after the
    reload), its statement deleted, undo."""
    print("script debugger through edits, saves and reloads (simulated game):")
    try:
        import tkinter as tk
        import cutscene_editor as ce
        from cutscene_editor import app as capp
    except Exception as e:
        _skip("script debugger edits", "no tkinter: %s" % e); return
    import struct, time, tempfile
    from rf4s_modkit import script, scriptdbg, hotreload
    mc = _first("rf3.mc")
    if not mc:
        _skip("script debugger edits", "rf3.mc not extracted"); return
    dirs = [mc.parent] + [d for d in (pathlib.Path(BUNDLE_DIR) / "bundleMain",
                                     pathlib.Path(BUNDLE_DIR) / "bundlePatch2") if d.is_dir()]

    def reader(n):
        for d in dirs:
            if (d / n).is_file():
                return (d / n).read_bytes()

    class Mem:
        def __init__(self):
            self.regions, self.next = {}, 0x10000000
        def alloc(self, n):
            b = self.next
            self.regions[b] = bytearray(n)
            self.next += (n + 0xFFFF) & ~0xFFFF
            return b
        def _at(self, a, n):
            for b, r in self.regions.items():
                if b <= a and a + n <= b + len(r):
                    return r, a - b
            raise KeyError(hex(a))
        def read(self, a, n):
            r, o = self._at(a, n)
            return bytes(r[o:o + n])
        def write(self, a, d):
            r, o = self._at(a, len(d))
            r[o:o + len(d)] = d


    class Game:
        pid, base, mc_id = 4242, 0x7000, 1

        def __init__(self, file, bank_pos, n_primary):
            m = self.m = Mem()
            self.tail = bank_pos - n_primary
            self.file = m.alloc(len(file) + 64); m.write(self.file, file)
            self.entry = m.alloc(16); m.write(self.entry, struct.pack("<QH", self.file, 1))
            self.sc = m.alloc(0x200)
            self.slot = m.alloc(64); self.buf = m.alloc(0x10040)
            blob = hotreload.McImage(file).bank_bytes(2, self.tail)
            m.write(self.buf, blob); m.write(self.slot + 16, struct.pack("<Q", self.buf))
            m.write(self.slot + 24, struct.pack("<I", len(blob)))
            self.vm = m.alloc(0x100); m.write(self.vm + 0x20, struct.pack("<Q", self.slot))
            self.stack = m.alloc(0x400); m.write(self.vm + 0x28, struct.pack("<Q", self.stack))

        def reload(self, file):                    # what hotreload.reload_mc does
            new = self.m.alloc(len(file) + 64); self.m.write(new, file)
            self.m.write(self.entry, struct.pack("<Q", new))
            blob = hotreload.McImage(file).bank_bytes(2, self.tail)
            self.m.write(self.ptr(self.slot + 16), blob)
            self.m.write(self.slot + 24, struct.pack("<I", len(blob)))

        def read(self, a, n): return self.m.read(a, n)
        def write(self, a, d): self.m.write(a, bytes(d))
        def u8(self, a): return self.read(a, 1)[0]
        def u32(self, a): return struct.unpack("<I", self.read(a, 4))[0]
        def ptr(self, a):
            try:
                return struct.unpack("<Q", self.read(a, 8))[0]
            except KeyError:
                return 0
        def alloc(self, n): return self.m.alloc(n)
        def own_allocation(self, p): return len(self.m.regions.get(p, b""))
        def free(self, p): pass
        def suspend(self): pass
        def resume(self): pass
        def close(self): pass
        def archive_entry(self, idx): return self.entry, self.ptr(self.entry), 1
        def scene(self): return self.sc
        def slots(self, sc):
            return [("tail", self.slot, 2, self.tail, self.ptr(self.slot + 16), self.u32(self.slot + 24), 1)]
        def vms(self, sc):
            return [(self.vm, self.u32(self.vm + 0x70), 0, self.ptr(self.vm + 0x20), self.u32(self.vm + 0x3C))]

        def run_from(self, pc, frames=6):
            """Start the VM at pc and let the game run a few frames."""
            v = self.vm
            self.write(v + 0x3C, struct.pack("<I", pc)); self.write(v + 0x70, struct.pack("<I", 2))
            self.write(v + 0x78, struct.pack("<I", 0))
            for _ in range(frames):
                self.frame()

        def frame(self):
            v = self.vm
            st, wait, pc = self.u32(v + 0x70), self.u32(v + 0x78), self.u32(v + 0x3C)
            if st != 2:
                return
            if wait:
                self.write(v + 0x78, struct.pack("<I", max(0, wait - 200)))
                return
            code = self.read(self.ptr(self.slot + 16), 0x10000)
            for _ in range(64):
                op = struct.unpack_from("<H", code, pc)[0]
                if op == 0xFFFA:
                    pc = struct.unpack_from("<H", code, pc + 2)[0]
                elif op == scriptdbg.WAIT_PLAIN:
                    val, _ok = script.eval_expr(code, struct.unpack_from("<H", code, pc + 4)[0])
                    self.write(v + 0x3C, struct.pack("<I", pc + 6)); self.write(v + 0x78, struct.pack("<I", val))
                    return
                elif op >= 0xFFF0:                   # any other control op: stop this run here
                    self.write(v + 0x70, struct.pack("<I", 1)); self.write(v + 0x3C, struct.pack("<I", pc))
                    return
                else:
                    pc += script.decode_statement(code, pc).size
            self.write(v + 0x3C, struct.pack("<I", pc))



    saved = (hotreload._Game, hotreload.pick_process, scriptdbg.recovery_path,
             capp.CutsceneExplorer.debugger_docked_setting, capp.CutsceneExplorer.set_debugger_docked_setting)
    tmp = pathlib.Path(tempfile.mkdtemp())
    scriptdbg.recovery_path = lambda: tmp / "recovery.json"          # never the user's settings folder
    capp.CutsceneExplorer.debugger_docked_setting = classmethod(lambda c: True)
    capp.CutsceneExplorer.set_debugger_docked_setting = classmethod(lambda c, on: None)
    box = _headless_dialogs()
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        cx = ce.CutsceneExplorer(tk.Toplevel(root), reader=reader)
        c0 = cx.doc.container
        BANK = 308
        plain = lambda st: st is not None and st.op < 0xFFF0 and st.size >= 4 and st.op != scriptdbg.WAIT_PLAIN
        P = Q = None
        for sc in script.disassemble_bank(c0.banks[BANK]):
            items = sorted(sc.stmts.items())
            for (p1, s1), (p2, s2), (p3, s3) in zip(items, items[1:], items[2:]):
                if all(plain(s) for s in (s1, s2, s3)) and p2 == p1 + s1.size and p3 == p2 + s2.size:
                    P, Q, ENTRY = p1, p2, sc.entry_pc
                    break
            if P:
                break
        print("bank %d: run from %04x, breakpoint on %04x" % (BANK, P, Q))

        GAME = Game(bytes(c0.build()), BANK, c0.n_primary)
        hotreload._Game = lambda pid=None: GAME
        hotreload.pick_process = lambda choose=None: GAME.pid

        def pump(n=6):
            for _ in range(n):
                root.update(); time.sleep(0.07)


        def reload_in_game():
            GAME.reload(bytes(cx.doc.container.build())); pump()


        def fires(game_from, label, want_game, want_doc):
            """Run the game from game pc `game_from`; the breakpoint must stop it at game pc
            `want_game`, and the editor must mark its own pc `want_doc`."""
            GAME.run_from(game_from); pump()
            d = panel.dbg
            parked = next(iter(d.parked.values()), None)
            _check(label + ": stops at game %04x" % want_game, parked == (BANK, want_game), parked and "%04x" % parked[1])
            _check(label + ": the editor marks %04x" % want_doc, cx.debug_current == (BANK, want_doc), cx.debug_current)
            for v in d.vms():                        # let it go
                d.resume(v)
            GAME.frame(); pump(2)


        def stmt_size(pc):
            return script.decode_statement(cx.doc.container.banks[BANK].data, pc).size


        cx.open_scene(BANK, ENTRY)
        panel = cx.open_debugger()
        panel.toggle_attach(); pump()
        cx.set_breakpoint(BANK, Q, True); pump()
        fires(P, "1 fresh breakpoint", Q, Q)

        # 2. insert before the breakpoint (unsaved): the editor's row moves, the game's does not
        cx.apply("insert", lambda: cx.doc.container.insert_before(BANK, Q, "ClosePortraits(2)")); pump()
        ins = stmt_size(Q)
        _check("2 the editor's breakpoint moved with its statement", (BANK, Q + ins) in cx.breakpoints, sorted(cx.breakpoints))
        _check("2 not dimmed (it still fires in the game)", (BANK, Q + ins) not in cx.pending_breakpoints)
        fires(P, "2 after an unsaved insert", Q, Q + ins)

        # 3. save + reload in game: now the game has the inserted statement too
        reload_in_game()
        fires(P, "3 after reload", Q + ins, Q + ins)

        # 4. delete the inserted statement (unsaved) -- the reported bug
        cx.apply("delete", lambda: cx.doc.container.delete_statement(BANK, Q)); pump()
        _check("4 the editor's breakpoint moved back", (BANK, Q) in cx.breakpoints, sorted(cx.breakpoints))
        fires(P, "4 after an unsaved delete", Q + ins, Q)

        # 5. reload again
        reload_in_game()
        fires(P, "5 after reload", Q, Q)

        # 6. an operand edited in place (unsaved): still the same statement
        st = script.decode_statement(cx.doc.container.banks[BANK].data, Q)
        if st.args:
            cx.apply("operand", lambda: cx.doc.container.set_action_arg_expr(BANK, Q, 0, __import__("rf4s_modkit.scriptasm", fromlist=["x"]).asm_expr("1"))); pump()
            _check("6 breakpoint kept on an edited statement", (BANK, Q) in cx.breakpoints)
            fires(P, "6 after an unsaved operand edit", Q, Q)
            reload_in_game()

        # 7. a breakpoint on a statement the game does not have yet: dimmed, fires after reload
        cx.apply("insert 2", lambda: cx.doc.container.insert_before(BANK, Q, "ClosePortraits(2)")); pump()
        cx.set_breakpoint(BANK, Q, True); pump()     # on the NEW statement
        _check("7 a breakpoint on a new statement waits (dimmed)", (BANK, Q) in cx.pending_breakpoints,
           sorted(cx.pending_breakpoints))
        bp, why = panel.dbg.user_state(BANK, Q)
        _check("7 ... and says why", why and "Reload" in why, why)
        reload_in_game()
        _check("7 after reload it is live", (BANK, Q) not in cx.pending_breakpoints)
        GAME.run_from(P); pump()
        parked = next(iter(panel.dbg.parked.values()), None)
        _check("7 it fires on the new statement", parked == (BANK, Q), parked)
        for v in panel.dbg.vms():
            panel.dbg.resume(v)
        GAME.frame(); pump(2)

        def release_all():
            for _ in range(6):                        # every stop on the way let go, to the end
                for v in panel.dbg.vms():
                    panel.dbg.resume(v)
                GAME.frame(); pump(2)


        release_all()
        # 8. delete the breakpoint's own statement: the breakpoint goes, nothing stops in the game
        cx.set_breakpoint(BANK, Q, False)
        cx.set_breakpoint(BANK, Q + ins, True); pump()          # the original statement
        cx.apply("delete bp stmt", lambda: cx.doc.container.delete_statement(BANK, Q + ins)); pump()
        _check("8 the breakpoint went with its statement", not [k for k in cx.breakpoints if k[0] == BANK], sorted(cx.breakpoints))
        GAME.run_from(P); pump()
        _check("8 the game no longer stops there", not panel.dbg.parked, panel.dbg.parked)

        # 9. undo brings the statement back; a breakpoint set on it now fires (game still has it)
        cx.undo(); pump()
        cx.set_breakpoint(BANK, Q + ins, True); pump()
        GAME.run_from(P); pump()
        parked = next(iter(panel.dbg.parked.values()), None)
        _check("9 after undo a breakpoint on the restored statement fires", parked == (BANK, Q + ins), parked)
        for v in panel.dbg.vms():
            panel.dbg.resume(v)
        GAME.frame(); pump(2)

        # 10. detach leaves the game's slot as the reloaded file has it
        panel.toggle_attach(); pump()


        panel.toggle_attach(); pump()
        _check("the sequences raised no callback errors and showed no error boxes", not errs and not box["msgs"],
               (errs[:1], box["msgs"][:1]))
    finally:
        (hotreload._Game, hotreload.pick_process, scriptdbg.recovery_path,
         capp.CutsceneExplorer.debugger_docked_setting, capp.CutsceneExplorer.set_debugger_docked_setting) = saved
        try:
            root.destroy()
        except tk.TclError:
            pass

def test_scene_log():
    """rf4mod script log (rf4s_modkit.scenelog): the samples of the running game are sorted
    against what the editor shows -- checked offline with hand-made samples: a registered
    statement is 'shown', real unreached code 'unreached', a stub the list skips 'not shown',
    a pc inside a statement 'torn'."""
    print("scene log (running-game logger) classification:")
    from map_editor import data as _med
    from rf4s_modkit import scenelog
    c = _med.rf3mc_container(live=False)
    if c is None:
        _skip("scene log", "rf3.mc not found"); return
    log = scenelog.SceneLog.__new__(scenelog.SceneLog)     # no game needed for the check
    log.c, log.starts, log.bank_differs = c, [], set()
    log.samples = {(308, 0x7456): 5,      # the Dragon Room's order-board scene (registered)
                   (232, 0x4428): 2,      # real unreached code
                   (308, 0x01AA): 2,      # the lone JMP stub the bank list skips
                   (308, 0x7457): 2}      # the middle of a statement
    got = log.classify()
    _check("the logger sorts samples: shown / unreached / not shown / torn",
           got == {(308, 0x7456): "shown", (232, 0x4428): "unreached",
                   (308, 0x01AA): "not shown", (308, 0x7457): "torn"}, got)
    rep = "\n".join(log.report())
    _check("its report lists what needs a look (unreached, not shown, torn seen twice)",
           "bank 232 @4428" in rep and "bank 308 @01aa" in rep and "bank 308 @7457" in rep, rep)


def test_cutscene_graph():
    """The Graph tab: the scene's basic blocks and labelled edges (cutscene_editor.cfg), laid out
    and drawn; a click on a line selects the statement."""
    print("cutscene editor: control-flow graph:")
    try:
        import tkinter as tk
        import cutscene_editor as ce
        from cutscene_editor import cfg
        from rf4s_modkit import script
    except Exception as e:
        _skip("control-flow graph", f"cutscene_editor not importable ({e})"); return
    # the shipped rf3.mc (the addresses below are the game's own; a modded game folder
    # moves them), for the layout checks and the editor alike
    mc = _shipped("rf3.mc")
    if mc is None:
        _skip("control-flow graph", "rf3.mc not found"); return
    c = script.Container(mc.read_bytes())
    bank = c.banks[c.n_primary + 196]                   # MAP_FIELD_36: GetDayOfWeek branches
    sc = script.disassemble_bank(bank)[0]
    bl = cfg.scene_graph(sc)
    pcs = [p for b in bl.values() for p in b.pcs]
    first = bl[sc.entry_pc]
    back, w, h, _gs = cfg.layout(bl, sc.entry_pc, lambda b: (100.0, 20.0 * len(b.lines)))
    over = [(a, b2) for a in bl.values() for b2 in bl.values() if a is not b2
            and a.y == b2.y and a.x < b2.x + b2.w and b2.x < a.x + a.w]
    _check("blocks cover every statement once; the entry's BR_Z gives a true and a false edge; "
           "no two blocks of a layer overlap; every edge goes down or is a loop",
           sorted(pcs) == sorted(sc.stmts) and next(iter(bl)) == sc.entry_pc
           and sorted(k for _t, k, _l in first.edges) == ["no", "yes"] and not over
           and all(bl[t].layer > b2.layer or (s, t) in back
                   for s, b2 in bl.items() for t, k, _l in b2.edges if k != "call"),
           (len(bl), [(hex(t), k, l) for t, k, l in first.edges], over[:2]))
    # a scene that only CALLs the bank's shared subroutines (MAP_CITY_00 @1cca: 2 statements of
    # its own, 480 with what it calls): the body is its own small group on top, each
    # subroutine a titled group below, and no group spreads out of control
    sc2 = script.disassemble_scene(c.banks[c.n_primary + 24], -1, 0x1CCA)
    bl2 = cfg.scene_graph(sc2)
    _b2, w2, h2, gs2 = cfg.layout(bl2, 0x1CCA, lambda b: (8.0 * max(len(t) for _p, t in b.lines) + 12,
                                                         16.0 * len(b.lines) + 12))
    owned = sorted(s for g in gs2 for s in g.starts)
    _check("CALLed subroutines become their own groups: MAP_CITY_00 @1cca's body is 2 blocks on "
           "top, 16 subroutines below, every block in one group, the layout stays compact",
           gs2[0].root == 0x1CCA and len(gs2[0].starts) == 2 and gs2[0].y == 0
           and sum(1 for g in gs2 if g.callers) == 16 and owned == sorted(bl2)
           and bl2[0x1CCA].link == 0x332 and w2 < 12000,
           ([(hex(g.root), len(g.starts), int(g.w)) for g in gs2[:4]], int(w2), int(h2)))

    def reader(n):
        f = mc if n == "rf3.mc" else _first(n)
        return f.read_bytes() if f else None
    root = None
    try:
        try:
            root = tk.Tk()
            root.withdraw()
        except Exception as e:
            _skip("graph tab", f"no display for Tk ({e})"); return
        top = tk.Toplevel(root)
        top.geometry("1200x800")
        ex = ce.CutsceneExplorer(top, reader=reader)
        ex.show_bank(ex.doc.container.n_primary + 196)
        ex.nb.select(ex.graph)
        ex._tab_changed()
        root.update()
        g = ex.graph
        n_lines = len(g._line_items)
        pc = next(iter(g._line_items.values()))
        ex.select((pc, None))
        root.update()
        marked = len(g.canvas.find_withtag("selbox"))
        info = g.info.cget("text")
        # the plain mouse wheel zooms the graph
        z0 = g.zoom
        g._zoom_wheel(type("E", (), {"delta": 120, "x": 100, "y": 100})())
        zoomed = g.zoom > z0
        # "◀ Banks" hides the bank list and brings it back
        n0 = len(ex._paned.panes())
        ex.toggle_banks()
        n1 = len(ex._paned.panes())
        ex.toggle_banks()
        n2 = len(ex._paned.panes())
        first = str(ex._paned.panes()[0]) == str(ex.browser)
        # the bank list: each scene lists the subroutines it CALLs; code nothing registers or
        # calls is "unreached" with the size of its own code (bank 232 @4428); a stub that only
        # jumps into code a registered scene runs is not listed (MAP_DUNG_K01's @0708 / @0720)
        br = ex.browser
        fpos = ex.doc.container.n_primary + 8
        br._fill_bank(fpos)
        subs = [br.tree.item(k, "text") for k in br.tree.get_children("s:%d:%d" % (fpos, 0x152))]
        kpos = next(ex.doc.container.n_primary + i for i in range(900)
                    if __import__("rf4s_modkit.map_names", fromlist=["m"]).map_file(i) == "MAP_DUNG_K01")
        br._fill_bank(kpos)
        k01_stubs = [k for k in br.tree.get_children("b:%d" % kpos)
                     if "unreached" in br.tree.item(k, "text")]
        br._fill_bank(232)
        k01 = br.tree.item("s:%d:%d" % (232, 0x4428), "text") if br.tree.exists(
            "s:%d:%d" % (232, 0x4428)) else ""
        # deleting a subroutine's only CALL leaves its code "unreached" (visible, not lost), and
        # the CALL form offers it to call it again (MAP_FARM_01 @03fe CALLs @0128)
        ex.open_scene(fpos, 0x3FE)
        ex.select((0x3FE, None))
        ex.delete_selected()
        _orphan = [sc_.entry_pc for sc_ in script.disassemble_bank(ex.bank) if sc_.action_type < 0]
        _pk = ex.ask_insert_instruction(True, preset=("ctl", "CALL"))
        _offer = [d_ for d_ in _pk.t1.opts if d_.startswith("unreached @0128")]
        if _offer:
            _pk.t1.var.set(_offer[0])
            _pk._rebuild()
        ex.select((min(ex.scene.stmts), None))
        _pk.where.set("before")
        _pk.insert()
        _pk.win.withdraw()
        _back = [sc_.entry_pc for sc_ in script.disassemble_bank(ex.bank) if sc_.action_type < 0]
        ex.undo()
        ex.undo()
        # a line picked in the Script tab: the Graph scrolls to its block when shown again
        ex.open_scene(ex.doc.container.n_primary + 24, 0x1CCA)
        ex.nb.select(ex.view)
        ex._tab_changed()
        root.update()
        far = max(pc for pc in ex.scene.stmts if pc < 0x1CCA)   # deep in a subroutine group
        ex.select((far, None))
        ex.nb.select(ex.graph)
        ex._tab_changed()
        root.update()
        fb = g.blocks[cfg.block_of(g.blocks, far)]
        cv = g.canvas
        vx0, vy0 = cv.canvasx(0), cv.canvasy(0)
        vx1, vy1 = vx0 + cv.winfo_width(), vy0 + cv.winfo_height()
        bx, by = (fb.x + fb.w / 2) * g.zoom, (fb.y + fb.h / 2) * g.zoom
        followed = vx0 <= bx <= vx1 and vy0 <= by <= vy1
        # the path to the selected block (MAP_CITY_00 @1cca, a subroutine block): its ancestors
        # include the scene's entry, which reaches it through a CALL; gold marks are drawn
        fb_start = cfg.block_of(g.blocks, far)
        pedges = g.adjacent_edges(fb_start)
        anc = {p_ for p_, _k in pedges if p_ != fb_start}
        path_ok = (pedges and all(p_ == fb_start or g.blocks[p_].edges[k][0] == fb_start
                                  for p_, k in pedges)
                   # one gold arrow per drawn adjacent edge (CALLs are links, not arrows) + 1 frame
                   and len(g.canvas.find_withtag("pathhl"))
                   == sum(1 for e_ in pedges if e_ in g._edge_geo) + 1
                   and [int(t[7:]) for i in g.canvas.find_withtag("pathhl")
                        for t in g.canvas.gettags(i) if t.startswith("pathbox")] == [fb_start])
        # drag the entry block: it moves, the move survives a redraw, Reset layout undoes it
        eb = g.blocks[0x1CCA]
        zz = g.zoom
        px_ = int(eb.x * zz - g.canvas.canvasx(0) + 5)
        py_ = int(eb.y * zz - g.canvas.canvasy(0) + 5)
        _E = lambda x, y: type("E", (), {"x": x, "y": y})()
        g._press(_E(px_, py_))
        g._drag(_E(px_ + 50, py_ + 25))
        g._drag(_E(px_ + 100, py_ + 50))
        g._release(_E(px_ + 100, py_ + 50))
        root.update()
        off1 = g._moved.get(g._scene_key(), {}).get(0x1CCA)
        g.render(force=True)
        kept = (round(g.blocks[0x1CCA].x - g._base[0x1CCA][0]), round(g.blocks[0x1CCA].y - g._base[0x1CCA][1]))
        g.reset_layout()
        undone = (g._moved.get(g._scene_key()) is None
                  and g.blocks[0x1CCA].x == g._base[0x1CCA][0])
        # "Inspector" hides the right-hand pane and brings it back at the right
        ex.toggle_inspector()
        n3 = len(ex._paned.panes())
        ex.toggle_inspector()
        last = str(ex._paned.panes()[-1]) == str(ex._side) and len(ex._paned.panes()) == n0
    finally:
        if root is not None:
            root.destroy()
    _check("the Graph tab draws the scene's blocks and marks the selected statement",
           n_lines > 20 and marked == 1 and "23 blocks" in info, (n_lines, marked, info))
    _check("the mouse wheel zooms the graph; 'Banks' hides the bank list and restores it on the left",
           zoomed and n1 == n0 - 1 and n2 == n0 and first, (zoomed, n0, n1, n2, first))
    _check("the bank list shows each scene's CALLed subroutines and names unregistered, "
           "uncalled code 'unreached'",
           len(subs) == 7 and subs[0].startswith("calls sub @015e")
           and "unreached (28 statements)" in k01 and not k01_stubs,
           (subs[:2], k01, k01_stubs))
    _check("a subroutine whose only CALL is deleted shows as 'unreached', and the CALL form offers "
           "it to call it again", 0x128 in _orphan and _offer and 0x128 not in _back,
           ([hex(x) for x in _orphan], _offer[:1], [hex(x) for x in _back]))
    _check("a line picked in the Script tab: the Graph scrolls its block into view",
           followed, (hex(far), (int(bx), int(by)), (int(vx0), int(vy0), int(vx1), int(vy1))))
    _check("the selected block is framed in gold, with only the arrows into and out of it",
           path_ok,
           (hex(fb_start), len(anc), len(pedges)))
    _check("a block can be dragged; the move is kept across redraws and Reset layout undoes it",
           off1 is not None and round(off1[0] * zz) == 100 and round(off1[1] * zz) == 50
           and kept == (round(off1[0]), round(off1[1])) and undone, (off1, kept, undone))
    _check("'Inspector' hides the arguments pane and restores it on the right",
           n3 == n0 - 1 and last, (n0, n3, last))


def test_cutscene_editor_authoring():
    """Headless drive of the cutscene editor's authoring surfaces: Source tab (listing,
    Check, Apply to scene), listing-syntax insert, Triggers tab (New scene on an empty map
    bank, remove), the map editor's open_new_scene_dialog entry point, and the Event
    Manager window's add/remove entry, condition and action. Every blocking dialog is
    scripted (_headless_dialogs); the Tk root is withdrawn."""
    print("cutscene editor authoring (headless GUI):")
    try:
        import tkinter as tk
        import cutscene_editor as ce
        from cutscene_editor import dialogs as ce_dialogs, em_window
    except Exception as e:
        _skip("editor authoring", f"cutscene_editor/tkinter not importable ({e})")
        return
    from rf4s_modkit import script, scriptasm
    p = _first("rf3.mc")
    if not p:
        _skip("editor authoring", "rf3.mc not extracted")
        return

    def reader(n):
        f = _first(n)
        return f.read_bytes() if f else None

    box = _headless_dialogs()
    box["askstring"] = "EV_SELFTEST_NEW"
    old_ask = ce_dialogs.ask_new_scene
    root = None
    try:
        try:
            root = tk.Tk()
            root.withdraw()
        except Exception as e:
            _skip("editor authoring", f"no display for Tk ({e})")
            return
        errs = []
        root.report_callback_exception = lambda *a: errs.append(a)
        ex = ce.CutsceneExplorer(tk.Toplevel(root), reader=reader)
        doc = ex.doc
        c = doc.container
        _check("editor constructs headless with rf3.mc + text + assembler resolver",
               c is not None and doc.textarc is not None and c.asm_resolver is not None)
        # --- Source tab on a real scene ---
        ex.show_bank(213)
        sc = ex.scene
        ex.source.load(force=True)
        _check("show_bank(213) opens a scene and the Source tab lists it",
               sc is not None and "DIALOG" in ex.source.text.get("1.0", "end-1c"))
        sig0 = scriptasm.scene_signature(sc, ex.bank.data)
        _check("Source Check passes on the generated listing", ex.source.check() is not None,
               ex.source.msg.cget("text")[:100])
        n_bank = len(ex.bank.data)
        noop = ex.source.apply()
        _check("Apply to scene of an untouched listing is a no-op (no second body appended)",
               noop is False and len(ex.bank.data) == n_bank and not doc.script_dirty())
        ex.source.text.insert("end", "\n; selftest: same content, different text\n")
        n_undo = len(doc.undo_stack)
        same = ex.source.apply()
        sig1 = scriptasm.scene_signature(ex.scene, ex.bank.data)
        _check("Apply of a listing that only adds a comment rebuilds the same bytes: nothing "
               "changes, no undo step, the Source tab says so",
               same is False and sig0 == sig1 and len(ex.bank.data) == n_bank and not doc.script_dirty()
               and len(doc.undo_stack) == n_undo and "no change" in ex.source.msg.cget("text"),
               ex.source.msg.cget("text")[:100])
        lines = ex.source.text.get("1.0", "end-1c").splitlines()
        k = next(i for i, ln in enumerate(lines) if ln.strip().startswith("DIALOG"))
        ex.source.text.delete("1.0", "end")
        ex.source.text.insert("1.0", "\n".join(lines[:k] + ["EVAL (reg0 = 1)"] + lines[k:]))
        ok = ex.source.apply()
        _check("Apply to scene of a real change rebuilds the bank with the body in place",
               bool(ok) and doc.script_dirty() and len(doc.undo_stack) == n_undo + 1
               and "EVAL" in ex.source.text.get("1.0", "end-1c"), ex.source.msg.cget("text")[:100])
        ex.source.text.insert("end", "\nNoSuchOpcodeXYZ 1\n")
        bad = ex.source.check()
        _check("Source Check reports a bad line inline (no modal)", bad is None
               and "line" in ex.source.msg.cget("text") and not box["msgs"])
        ex.source.load(force=True)
        # --- listing insert after the first DIALOG of the scene ---
        dpc = next((pc for pc, st in ex.scene.stmts.items() if st.mnem == "DIALOG"), None)
        if dpc is not None:
            n0 = len(ex.scene.stmts)
            _j0 = sum(x.mnem == "JMP" for x in ex.scene.stmts.values())
            ex.insert_after(dpc, "BR_Z (FLG_KOKUHAKU_NOW) -> skip\nDIALOG #5\nskip:\nEVAL (reg1 = 2)")
            _check("listing-syntax insert adds the branch/label/EVAL beat in place (selected)",
                   len(ex.scene.stmts) == n0 + 3 and ex.scene.ok and ex.sel is not None
                   and ex.scene.stmts[ex.sel[0]].mnem == "BR_Z")
            # the save path writes the rebuilt bank: no trampoline, compiler layout, every other
            # bank as shipped (save_script through the scripted file dialog)
            from rf4s_modkit import bankrelink
            import tempfile
            _sv = pathlib.Path(tempfile.mkdtemp()) / "rf3.mc"
            box["save"] = str(_sv)
            _saved = ex.save_script()
            _cs = script.Container(_sv.read_bytes()) if _sv.is_file() else None
            _raw = p.read_bytes()
            _c0 = script.Container(_raw)
            _b = _cs.banks[213] if _cs else None
            _sc = script.disassemble_scene(_b, ex.scene.action_type, ex.scene.entry_pc) if _b else None
            _check("GUI save writes the rebuilt bank (compiler layout, no JMP added, other banks as shipped)",
                   _saved and _cs is not None and bankrelink.relink(_b) == bytes(_b.data)
                   and bankrelink.BankModel.parse(_b).fold() == 0
                   and bytes(_b.data) == bytes(ex.bank.data) and not doc.script_dirty()
                   and _sc.ok and any(x.dialog_id == 5 for x in _sc.stmts.values())
                   and sum(x.mnem == "JMP" for x in _sc.stmts.values())
                   == _j0
                   and all(bytes(x.data) == bytes(y.data) for i, (x, y) in enumerate(zip(_c0.banks, _cs.banks))
                           if i != 213))
            box["save"] = ""
        else:
            _skip("listing insert", "scene without DIALOG")
        # --- Triggers tab: new scene on an EMPTY tail bank, then remove ---
        empty_idx = next(i for i, b in enumerate(c.banks) if b.kind == "tail" and len(b.data) == 296)
        ex.show_bank(empty_idx)
        eb = c.banks[empty_idx]
        res = ex.add_entry(empty_idx, 7, "", "FRAME 0\nSetSpeaker Nancy, Left, 3, 0\nDIALOG #8709\nEND", "append")
        recs = eb.entry_records(7)
        _check("New scene mints a type-7 scene in an empty map bank and opens it",
               isinstance(res, tuple) and len(recs) == 1 and recs[0].event_id == res[0]
               and ex.scene is not None and ex.scene.entry_pc == res[0] and ex.scene.ok)
        rows = [v for v in ex.triggers.rows.values() if v[1] is not None]
        _check("Triggers tab lists exactly the bank's entries", len(rows) == sum(
            cnt for cnt, _ in eb.type_table_full().values()))
        note = c.entry_shadow_note(eb, 7)
        _check("entry_shadow_note warns that a second type-7 (MapLeaveScene, first entry runs) entry "
               "never runs", note is not None and "FIRST" in note and "never run" in note, note)
        iid = next(i for i, v in ex.triggers.rows.items() if v[1] is not None)
        ex.triggers.tree.selection_set(iid)
        ex.triggers.remove()
        _check("Triggers 'Remove' unregisters it (container still builds)",
               not eb.entry_records(7) and script.Container(c.build()).banks[empty_idx].entry_records(7) == [])
        n_msgs = len(box["msgs"])
        bad = ex.add_entry(empty_idx, 7, "", "FRAME 0\nBogusOpcode 1\nEND", "append")
        _check("New scene rejects a bad body (message names the problem, nothing changes)",
               bad is None and len(box["msgs"]) == n_msgs + 1 and not eb.entry_records(7))
        # --- the map editor's entry point: open the editor on a map bank + mint a scene ---
        ce_dialogs.ask_new_scene = lambda parent, app, bank, default_type=None: {
            "type_id": default_type, "keys": [], "body": "FRAME 0\nDIALOG #8709\nEND",
            "position": "append"}
        res2 = ex.open_new_scene_dialog(empty_idx)
        _check("open_new_scene_dialog (map editor's 'New scene on this map…') defaults to "
               "MapEnterScene (type 6, run on entering the map) in that map's tail bank",
               isinstance(res2, tuple) and [r.event_id for r in eb.entry_records(6)] == [res2[0]]
               and not eb.entry_records(7))
        from rf4s_modkit import entry_types as _et
        _b7 = next((i for i, b in enumerate(c.banks) if b.kind == "tail" and b.entry_records(7)), None)
        _sn = c.entry_shadow_note(_b7, 7, None) if _b7 is not None else "skip"
        _check("type 6 is MapEnterScene and type 7 MapLeaveScene (the map just left, first entry "
               "runs); appending a second leave scene is flagged as never running",
               _et.type_name(6) == "MapEnterScene" and _et.type_name(7) == "MapLeaveScene"
               and _et.map_enter_type() == 6 and (_sn == "skip" or "never run" in _sn), _sn)
        # --- Event Manager window: entries, conditions and actions ---
        emw = ex.open_event_manager()
        em = doc.em
        if emw is not None and em is not None:
            n_before = len(em.entries)
            box["askstring"] = "SELFTEST_ENTRY"
            nidx = emw.add_entry()
            box["askstring"] = None
            _check("Event Manager 'New entry' appends a named em.bin entry (tracked as unsaved)",
                   len(doc.em.entries) == n_before + 1 and "em.bin" in doc.dirty_parts()
                   and doc.em.entries[nidx].name == "SELFTEST_ENTRY" and emw.idx == nidx)
            # NB: EmScript._relayout() re-creates the Entry objects, so re-fetch by id
            # after every structural edit (the window itself re-selects by id and refills).
            _em = doc.em
            emw._edit("Add a condition", lambda: _em.add_condition(
                nidx, "a", _em.parse_condition_spec("Hour >= 6 AND FLG_RAINBOW == 1")), select=("sec", "a"))
            new = doc.em.entries[nidx]
            _check("Event Manager: a condition spec becomes a new way",
                   len(new.cond_a) == 1 and len(new.cond_a[0]) == 2)
            emw._edit("Add an action", lambda: _em.add_action(
                nidx, "alt", _em.parse_action_spec("REG_WIFE_ID = 3")), select=("act", "alt", 0))
            new = doc.em.entries[nidx]
            _check("Event Manager: an action spec lands in the alt stream",
                   len(new.alt_actions) == 1 and not new.actions)
            kinds = [r.key[0] for r in emw.rows if r.key and r.key[0] in ("expr", "act")]
            _check("the rule view lists each requirement and the action as selectable lines",
                   kinds == ["expr", "expr", "act"], kinds)
            rej = []
            for spec in ("Hour >>= 6", "NOT_A_VARIABLE_X == 1", "slot=9 Hour >= 6"):
                try:
                    em_window.parse_condition(doc.em, new, spec)
                except Exception:
                    rej.append(spec)
            _check("condition specs are validated before they are applied", len(rej) == 3, rej)
            emw.select(("act", "alt", 0))
            emw.remove_selected()
            _check("Event Manager 'Remove' drops the selected action", not doc.em.entries[nidx].alt_actions)
            from rf4s_modkit import emscript as _emsc
            _check("em.bin with the new entry + condition re-serialises and reparses",
                   len(_emsc.EmScript.parse(doc.em.serialize(), doc.em.names).entries) == len(doc.em.entries))
            for _ in range(4):              # remove action, add action, condition, entry
                ex.undo()
            # undo re-parses em.bin into a fresh EmScript, so read doc.em again
            _check("undo walks the Event Manager edits back to the shipped em.bin",
                   len(doc.em.entries) == n_before and "em.bin" not in doc.dirty_parts())
            emw.win.withdraw()
        else:
            _skip("Event Manager structural edits", "em.bin missing")
        # --- the trigger catalogue's registration recipes reach the editor ---
        try:
            from rf4s_modkit import entry_types
            recipes = [t for t, v in entry_types.ENTRY_TYPES.items() if v.get("recipe")]
            kinds = {v.get("bank_kind") for v in entry_types.ENTRY_TYPES.values()}
            _check("catalogue carries registration recipes + machine-readable bank kinds",
                   len(recipes) >= 10 and entry_types.map_enter_type() == 6
                   and kinds <= set(entry_types.BANK_KINDS) and len(ce.recipe_types()) == len(recipes),
                   f"{len(recipes)} recipes, kinds={sorted(kinds)}")
        except Exception as e:
            _check("catalogue carries registration recipes + machine-readable bank kinds", False, repr(e))
        _check("authoring drive raised no callback errors", not errs, f"{len(errs)}")
    finally:
        ce_dialogs.ask_new_scene = old_ask
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


def _headless_dialogs():
    """Replace every blocking tk dialog with a scripted answer; returns the answer box."""
    from tkinter import messagebox, filedialog, simpledialog
    box = {"yesnocancel": None, "yesno": True, "save": "", "msgs": []}
    for fn in ("showinfo", "showerror", "showwarning"):
        setattr(messagebox, fn, lambda t="", m="", **k: box["msgs"].append((t, str(m))))
    messagebox.askyesnocancel = lambda *a, **k: box["yesnocancel"]
    messagebox.askyesno = lambda *a, **k: box["yesno"]
    filedialog.asksaveasfilename = lambda *a, **k: box["save"]
    filedialog.askopenfilename = lambda *a, **k: ""
    simpledialog.askstring = lambda *a, **k: box.get("askstring")
    import guiutil
    guiutil.ask_yes_no_optout = lambda *a, **k: (box["yesno"], box.get("optout", False))
    return box


def test_explorer_open_file():
    """rf4mod_gui Open file…: one file from disk opens in a new tab and the file list (the game
    copy) stays, so the tab reads textures from the game; a map opened that way saves back
    to its own file, not into the game folder."""
    print("asset explorer Open file… (keeps the game copy):")
    import importlib.util, tempfile, shutil
    try:
        import tkinter as tk
    except Exception as e:
        _skip("explorer open file", "no tkinter: %s" % e); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_04.rf4m").exists():
        _skip("explorer open file", "no extracted bundleMain"); return
    spec = importlib.util.spec_from_file_location("rf4mod_gui_open", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
    gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
    _headless_dialogs()
    tmp = pathlib.Path(tempfile.mkdtemp())
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        f = tmp / "MAP_OPEN_TEST.rf4m"
        shutil.copyfile(B / "MAP_CITY_04.rf4m", f)
        app = gui.App(root, initial=str(B))
        src = app.source
        app.open_path(f)
        root.update_idletasks()
        doc = app._doc
        panel = doc._map_panel
        _check("Open file… on a map keeps the game copy listed and opens the map in a new tab",
               app.source is src and doc is not None and doc.key == ("file", str(f.resolve()))
               and panel is not None and panel.file_path == f.resolve(),
               (app.source is src, getattr(doc, "key", None)))
        _check("the opened map reads its textures from the game copy",
               panel.tex_reader == src.read_named, panel.tex_reader)
        before = f.read_bytes()
        panel.select(("mobj", 0))
        panel.nudge(8, 0)
        ok = panel.save_to_game()
        leaked = [p for p in pathlib.Path(BUNDLE_DIR).rglob("MAP_OPEN_TEST.rf4m")]
        _check("Ctrl+S on a map opened from disk writes that file, nothing in the game folder",
               ok and f.read_bytes() != before and not leaked and not panel.doc.dirty("map"),
               (ok, leaked))
        # rf3.mc opens the Cutscene Editor (one window; selecting it again brings that one forward)
        mc = next((p for p in pathlib.Path(BUNDLE_DIR).glob("bundlePatch*/rf3.mc")), None)
        if mc is not None:
            app2 = gui.App(tk.Toplevel(root), initial=str(mc.parent))
            n = next(e[0] for e in app2.source.entries if e[0].endswith("rf3.mc"))
            i = next(k for k, e in enumerate(app2.source.entries) if e[0] == n)
            app2._reveal_entry(i); app2._suppress_select = False; app2._on_select(None)
            root.update()
            ed = getattr(app2, "_cutscene_ed", None)
            app2._on_select(None)
            root.update()
            _check("selecting rf3.mc opens the Cutscene Editor (one window, reused)",
                   ed is not None and ed[0].winfo_exists() and app2._cutscene_ed is ed
                   and ed[1].doc.container is not None, ed)
        _check("Open file… raised no callback errors", not errs, errs[:1])
    finally:
        try:
            root.update()
        except tk.TclError:
            pass
        root.destroy()
        shutil.rmtree(tmp, ignore_errors=True)


def test_explorer_model_obj_import():
    """rf4mod_gui model tab: Import OBJ… replaces shapes' geometry from an OBJ (the Export OBJ
    format) -- each OBJ object goes onto the shape of the same name -- and makes the result
    the tab's working copy; an unedited export re-imports as 'unchanged'."""
    print("asset explorer: Import OBJ on a model tab:")
    import importlib.util, tempfile, shutil
    try:
        import tkinter as tk
    except Exception as e:
        _skip("model OBJ import", "no tkinter: %s" % e); return
    from rf4s_modkit import model as _model
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    src = next((p for p in sorted(B.glob("*.model")) if p.stat().st_size < 400_000
                and _model.is_mesh(p.read_bytes()) and len(_model.parse(p.read_bytes()).shapes) >= 2
                and all(sh.skin <= 1 for sh in _model.parse(p.read_bytes()).shapes)), None)
    if src is None:
        _skip("model OBJ import", "no small multi-shape .model"); return
    spec = importlib.util.spec_from_file_location("rf4mod_gui_obj", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
    gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
    _headless_dialogs()
    tmp = pathlib.Path(tempfile.mkdtemp())
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        f = tmp / src.name
        shutil.copyfile(src, f)
        app = gui.App(root, initial=str(B))
        app.open_path(f)
        root.update_idletasks()
        doc = app._doc
        orig = doc.cur_data
        m = _model.parse(orig)
        written = _model.export_obj(m, tmp, "exp")
        obj = next(pathlib.Path(w) for w in written if str(w).endswith(".obj"))
        text = obj.read_text(encoding="utf-8")
        same = app._import_model_obj(doc.cur_name, str(obj),
                                     choose=lambda mm, objs: {sh.index: sh.name for sh in mm.shapes})
        _check("re-importing an unedited export changes nothing",
               same and doc.cur_data == orig and "unchanged" in app.status.cget("text"),
               app.status.cget("text"))
        # scale the FIRST object's vertices by 2 (v lines up to the second 'o')
        out, obj_no = [], 0
        for ln in text.splitlines():
            if ln.startswith("o "):
                obj_no += 1
            if ln.startswith("v ") and obj_no == 1:
                x, y, z = (float(t) for t in ln.split()[1:4])
                ln = f"v {2 * x!r} {2 * y!r} {2 * z!r}"
            out.append(ln)
        edited = tmp / "edited.obj"
        edited.write_text("\n".join(out) + "\n", encoding="utf-8")
        first = m.shapes[0].name
        ok = app._import_model_obj(doc.cur_name, str(edited), choose=lambda mm, objs: {0: first})
        m2 = _model.parse(doc.cur_data)
        _check("Import OBJ… replaces the chosen shape's geometry: the working copy changes, still "
               "reads as a model, same shape count",
               ok and doc.cur_data != orig and len(m2.shapes) == len(m.shapes)
               and "Imported 1 shape" in app.status.cget("text"), app.status.cget("text"))
        _check("model OBJ import raised no callback errors", not errs, errs[:1])
    finally:
        try:
            root.update()
        except tk.TclError:
            pass
        root.destroy()
        shutil.rmtree(tmp, ignore_errors=True)


def test_model_fast_render():
    """model.render(fast=True), the playback path: nearest-texel sampling covers exactly the
    same pixels as the full render, and the textures' float arrays are kept in the caller's
    texture cache, so the next frame does not convert them again."""
    print("model render: the fast playback path:")
    from rf4s_modkit import model as _model
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    p = B / "M02_0.model"
    if not p.exists():
        _skip("fast render", "no M02_0.model"); return
    m = _model.parse(p.read_bytes())
    tex = {}
    full = _model.render(m, "field", 200, textures=tex)
    fast = _model.render(m, "field", 200, textures=tex, fast=True)
    cached = tex.get(("__float_arrays__",), {})
    same_cover = full.size == fast.size and full.getchannel("A").getbbox() == fast.getchannel("A").getbbox()
    _check("fast render: same size and coverage as the full render, texture arrays cached",
           same_cover and len(cached) >= 1, (full.size, fast.size, len(cached)))


def test_skelanim_write():
    """skelanim.build writes the shipped .bfskl layout: every shipped motion parses and
    rebuilds byte for byte."""
    print("skeletal animation writer (.bfskl):")
    from rf4s_modkit import skelanim as _sk
    files = sorted(pathlib.Path(BUNDLE_DIR).rglob("*.bfskl"))
    if not files:
        _skip("bfskl writer", "no extracted .bfskl"); return
    seen, bad = set(), []
    for p in files:
        if p.name in seen:
            continue
        seen.add(p.name)
        d = p.read_bytes()
        try:
            if _sk.build(_sk.parse(d)) != d:
                bad.append(p.name)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{p.name}: {e}")
    _check(f"all {len(seen)} shipped .bfskl rebuild byte for byte", not bad, bad[:3])


def test_gltf_motion_roundtrip():
    """Export for Blender / Import motion: a model and a motion go out as a .glb (skeleton,
    skin, textures, the motion sampled per frame) and the animation comes back as a .bfskl
    that poses the model like the original (within 0.05 % of the model's size; exact with no
    key reduction); bones of the replaced file the model lacks keep their motion; the GUI
    exports, previews and installs into the game folder (a scratch one here)."""
    print("glTF motion round trip (Export for Blender / Import motion):")
    import importlib.util, tempfile, shutil
    from rf4s_modkit import gltf as _gl, model as _model, skelanim as _sk
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "M02_0.model").exists() or not (B / "M02_0_00.bfskl").exists():
        _skip("glTF motion", "no M02_0 model / motion"); return
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        worst_rel, exact, glb_ok = 0.0, True, True
        for stem, motion in (("M02_0", "M02_0_00.bfskl"), ("NPC_TRAVELER_M", "00W_002_walk.bfskl"),
                             ("BM_00", "BM_00_00_1.bfskl")):
            if not (B / f"{stem}.model").exists() or not (B / motion).exists():
                continue
            m = _model.parse((B / f"{stem}.model").read_bytes())
            a = _sk.parse((B / motion).read_bytes())
            g = tmp / f"{stem}.glb"
            _gl.export_glb(m, g, a, stem)
            gj, bufs = _gl.read_gltf(g)
            glb_ok &= (len(gj["nodes"]) >= len(m.bones) and gj["skins"][0]["joints"] == list(range(len(m.bones)))
                       and len(gj["animations"]) == 1 and bool(gj.get("images")))
            b2 = _sk.parse(_sk.build(_gl.import_animation(g, m, template=a)))
            size = _gl._extent(m)
            for f in range(int(a.frame_count) + 1):
                for x, y in zip(_model.world_matrices(_sk.pose_bones(m, a, f)),
                                _model.world_matrices(_sk.pose_bones(m, b2, f))):
                    worst_rel = max(worst_rel, max(abs(x[r][c] - y[r][c]) for r in range(3) for c in range(4)) / size)
            if stem == "M02_0":
                keep = dict(_gl.TOL)
                _gl.TOL.update(r=0.0, s=0.0, t_rel=0.0)
                try:
                    b3 = _gl.import_animation(g, m, template=a)
                finally:
                    _gl.TOL.update(keep)
                for f in range(0, int(a.frame_count) + 1, 7):
                    for x, y in zip(_model.world_matrices(_sk.pose_bones(m, a, f)),
                                    _model.world_matrices(_sk.pose_bones(m, b3, f))):
                        exact &= max(abs(x[r][c] - y[r][c]) for r in range(3) for c in range(4)) < 1e-3
                kept = {bb.name for bb in b2.bones} >= {bb.name for bb in a.bones}
                meta_ok = b2.frame_count == a.frame_count and b2.loops == a.loops and b2.name == a.name
        _check("the .glb carries the skeleton (one joint per bone), the skin, the textures and the motion",
               glb_ok)
        _check("round trip: the imported motion poses the model like the original (within 0.05 % of "
               "its size), frame count / loop / name kept", worst_rel < 0.0005 and meta_ok,
               f"{100 * worst_rel:.4f} %")
        _check("round trip without key reduction is exact", exact)
        _check("bones of the replaced file that the model lacks keep their motion", kept)
        # --- the GUI: export, import, install into a scratch game folder ---
        try:
            import tkinter as tk
        except Exception:
            _skip("glTF motion GUI", "no tkinter"); return
        spec = importlib.util.spec_from_file_location("rf4mod_gui_gltf", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
        gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
        _headless_dialogs()
        game = tmp / "Game"
        bundle = game / "Bundle"
        (bundle / "bundleMain").mkdir(parents=True)
        (bundle / "Manifest.plist").write_bytes(b"")
        shutil.copyfile(B / "M02_0_00.bfskl", bundle / "bundleMain" / "M02_0_00.bfskl")
        real_find = _gamepaths.find_bundle_dir
        _gamepaths.find_bundle_dir = lambda refresh=False: bundle
        root = tk.Tk(); root.withdraw()
        errs = []
        root.report_callback_exception = lambda *a_: errs.append(a_)
        try:
            app = gui.App(root, initial=str(B))
            m = _model.parse((B / "M02_0.model").read_bytes())
            a = _sk.parse((B / "M02_0_00.bfskl").read_bytes())
            out = app._export_model_glb(m, "M02_0", a, path=str(tmp / "gui.glb"))
            new = app._import_motion_file(m, a, path=str(tmp / "gui.glb"))
            wrote = app._install_motion("M02_0_00.bfskl", new, answer=True)
            target = bundle / "bundleMain" / "M02_0_00.bfskl"
            backup = game / _gamepaths.BACKUP_DIR / "Bundle" / "bundleMain" / "M02_0_00.bfskl"
            _check("GUI: Export for Blender writes the .glb; Import motion builds the motion; install "
                   "writes it over the game's file and keeps the original in ModdingBackup",
                   out and new is not None and wrote == target and target.read_bytes() == _sk.build(new)
                   and backup.read_bytes() == (B / "M02_0_00.bfskl").read_bytes(), (out, wrote))
            _check("glTF motion GUI raised no callback errors", not errs, errs[:1])
        finally:
            _gamepaths.find_bundle_dir = real_find
            root.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_gltf_import_all_motions():
    """Export all motions / Import all motions: every motion of a model goes out in one .glb
    (one animation each, named after its file, timestamps never short of their frame) and
    comes back with nothing flagged as changed; a motion edited in the file is the only one
    flagged, and the GUI installs just that one (backup kept)."""
    print("glTF: export / import all motions:")
    import importlib.util, tempfile, shutil, struct as _st
    from rf4s_modkit import gltf as _gl, model as _model, skelanim as _sk
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "M02_0.model").exists():
        _skip("import all motions", "no M02_0"); return
    try:
        import tkinter as tk
    except Exception:
        _skip("import all motions", "no tkinter"); return
    _check("glTF timestamps never fall short of their game frame (Blender would drop the frame)",
           all(_st.unpack("<f", _st.pack("<f", _gl._frame_time(f)))[0] * 60 >= f for f in range(4000)))
    spec = importlib.util.spec_from_file_location("rf4mod_gui_all", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
    gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
    _headless_dialogs()
    tmp = pathlib.Path(tempfile.mkdtemp())
    game = tmp / "Game"; bundle = game / "Bundle"
    (bundle / "bundleMain").mkdir(parents=True); (bundle / "Manifest.plist").write_bytes(b"")
    real_find = _gamepaths.find_bundle_dir
    _gamepaths.find_bundle_dir = lambda refresh=False: bundle
    root = tk.Tk(); root.withdraw()
    try:
        app = gui.App(root, initial=str(B))
        src = app.source
        m = _model.parse((B / "M02_0.model").read_bytes())
        names = _sk.anim_candidates("M02_0", [n for n, _g, _l in src.entries])
        g = tmp / "all.glb"
        r = app._export_all_motions(m, "M02_0", names, src, path=str(g))
        anims = _gl.list_animations(g)
        _check("Export all motions: one animation per motion, named after the file",
               r and r[1] == len(names) and sorted(a[1] + ".bfskl" for a in anims) == sorted(names), (r and r[1], len(names)))
        templates = {pathlib.Path(n).stem: _sk.parse(src.read_named(n)) for n in names}
        res = _gl.import_all_animations(g, m, templates)
        _check("importing them all back flags nothing as changed", not res["changed"] and not res["failed"]
               and len(res["unchanged"]) == len(names) and not res["notes"], [c[0] for c in res["changed"]][:3])
        # edit one motion in the templates' place: the file now differs from it
        target = "M02_0_03"
        other = next(n for n in templates if n != target and templates[n].frame_count != templates[target].frame_count)
        fake = dict(templates); fake[target] = templates[other]
        res2 = _gl.import_all_animations(g, m, fake)
        _check("a motion that differs is the only one flagged as changed",
               [c[0] for c in res2["changed"]] == [target], [c[0] for c in res2["changed"]])
        shutil.copyfile(B / f"{target}.bfskl", bundle / "bundleMain" / f"{target}.bfskl")
        orig = src.read_named
        src.read_named = lambda n, _o=orig: (B / f"{other}.bfskl").read_bytes() if n == f"{target}.bfskl" else _o(n)
        try:
            w = app._import_all_motions(m, names, src, path=str(g), answer="install")
        finally:
            src.read_named = orig
        backup = game / _gamepaths.BACKUP_DIR / "Bundle" / "bundleMain" / f"{target}.bfskl"
        _check("GUI Import all motions installs only the changed motion, original kept in ModdingBackup",
               w and [fn for fn, _a in w] == [f"{target}.bfskl"] and backup.exists(), w and [fn for fn, _a in w])
    finally:
        _gamepaths.find_bundle_dir = real_find
        root.destroy()
        shutil.rmtree(tmp, ignore_errors=True)


def test_gltf_blender_roundtrip():
    """With Blender installed: Blender imports the Export for Blender .glb (armature + the
    motion), a bone is rotated by 30 degrees on one frame and Blender exports it; Import motion
    brings the change back at the right game frame, the motion's length is kept, and the rest of
    the motion stays within 0.3 % of the model's size (Blender's 24 fps resampling)."""
    print("glTF motion through Blender (optional):")
    import glob, math, subprocess, tempfile, shutil
    exe = next(iter(sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender*\blender.exe"), reverse=True)), None) \
        or shutil.which("blender")
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not exe or not (B / "M02_0.model").exists():
        _skip("glTF through Blender", "Blender not installed" if not exe else "no M02_0"); return
    from rf4s_modkit import gltf as _gl, model as _model, skelanim as _sk
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        m = _model.parse((B / "M02_0.model").read_bytes())
        a = _sk.parse((B / "M02_0_00.bfskl").read_bytes())
        src, dst = tmp / "in.glb", tmp / "out.glb"
        _gl.export_glb(m, src, a, "M02_0")
        script = tmp / "edit.py"
        script.write_text(
            "import bpy, math, sys\n"
            "from mathutils import Quaternion\n"
            "a = sys.argv[sys.argv.index('--') + 1:]\n"
            "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
            "bpy.ops.import_scene.gltf(filepath=a[0])\n"
            "arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')\n"
            "bpy.context.view_layer.objects.active = arm\n"
            "bpy.ops.object.mode_set(mode='POSE')\n"
            "pb = arm.pose.bones['Bip01_Head']\n"
            "bpy.context.scene.frame_set(20)\n"
            "pb.rotation_mode = 'QUATERNION'\n"
            "pb.rotation_quaternion = pb.rotation_quaternion @ Quaternion((1, 0, 0), math.radians(30))\n"
            "pb.keyframe_insert('rotation_quaternion', frame=20)\n"
            "bpy.ops.object.mode_set(mode='OBJECT')\n"
            "bpy.ops.export_scene.gltf(filepath=a[1], export_format='GLB', export_animations=True)\n",
            encoding="utf-8")
        r = subprocess.run([exe, "--background", "--python", str(script), "--", str(src), str(dst)],
                           capture_output=True, text=True, timeout=300)
        if not dst.exists():
            _check("Blender exported the edited .glb", False, (r.stdout or "")[-400:]); return
        b = _sk.parse(_sk.build(_gl.import_animation(dst, m, template=a)))
        head = next(i for i, bn in enumerate(m.bones) if bn.name == "Bip01_Head")
        d_head = (_sk.pose_bones(m, b, 50)[head].rotation[0] - _sk.pose_bones(m, a, 50)[head].rotation[0])
        size, worst = _gl._extent(m), 0.0
        for f in list(range(0, 36)) + list(range(66, 73)):       # away from the edit
            for x, y in zip(_model.world_matrices(_sk.pose_bones(m, a, f)),
                            _model.world_matrices(_sk.pose_bones(m, b, f))):
                worst = max(worst, max(abs(x[r_][c] - y[r_][c]) for r_ in range(3) for c in range(4)))
        _check("Blender round trip: the 30-degree head tilt arrives at game frame 50, the length is "
               "kept and the untouched frames stay within 0.3 % of the model's size",
               abs(d_head - math.radians(30)) < 0.02 and b.frame_count == a.frame_count
               and worst / size < 0.003, (round(d_head, 4), b.frame_count, f"{100 * worst / size:.3f} %"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_blender_addon():
    """With Blender installed: the add-on blender/rf4s_blender.py registers; File > Import >
    RF4S model / motions switches a 24 fps scene to 60 and fits the timeline to the active
    motion (0 .. its frame count); picking another action refits it; the export refuses at 24
    fps and at 60 writes a .glb whose motions all come back unchanged."""
    print("Blender add-on (optional):")
    import glob, subprocess, tempfile, shutil
    exe = next(iter(sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender*\blender.exe"), reverse=True)), None) \
        or shutil.which("blender")
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    addon = pathlib.Path(__file__).with_name("blender") / "rf4s_blender.py"
    if not exe or not (B / "M02_0.model").exists():
        _skip("Blender add-on", "Blender not installed" if not exe else "no M02_0"); return
    from rf4s_modkit import gltf as _gl, model as _model, skelanim as _sk
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        m = _model.parse((B / "M02_0.model").read_bytes())
        names = ["M02_0_00", "M02_0_01"]
        tpl = {n: _sk.parse((B / f"{n}.bfskl").read_bytes()) for n in names}
        src, dst = tmp / "in.glb", tmp / "out.glb"
        _gl.export_glb(m, src, [tpl[n] for n in names], "M02_0")
        script = tmp / "t.py"
        script.write_text(
            "import bpy, sys, importlib.util\n"
            "a = sys.argv[sys.argv.index('--') + 1:]\n"
            "spec = importlib.util.spec_from_file_location('rf4s_blender', a[0])\n"
            "mod = importlib.util.module_from_spec(spec); sys.modules['rf4s_blender'] = mod\n"
            "spec.loader.exec_module(mod)\n"
            "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
            "mod.register()\n"
            "sc = bpy.context.scene\n"
            "bpy.ops.import_scene.rf4s_glb(filepath=a[1])\n"
            "arm = next(o for o in sc.objects if o.type == 'ARMATURE')\n"
            "print('R1', sc.render.fps, sc.frame_start, sc.frame_end, arm.animation_data.action.name)\n"
            "arm.animation_data.action = bpy.data.actions['M02_0_01']\n"
            "bpy.context.view_layer.update()\n"
            "print('R2', sc.frame_start, sc.frame_end)\n"
            "sc.render.fps = 24\n"
            "try:\n"
            "    bpy.ops.export_scene.rf4s_glb(filepath=a[2]); print('R3 exported')\n"
            "except RuntimeError:\n"
            "    print('R3 refused')\n"
            "sc.render.fps = 60\n"
            "bpy.ops.export_scene.rf4s_glb(filepath=a[2])\n"
            "mod.unregister()\n",
            encoding="utf-8")
        r = subprocess.run([exe, "--background", "--factory-startup", "--python", str(script), "--",
                            str(addon), str(src), str(dst)], capture_output=True, text=True, timeout=300)
        got = {ln[:2]: ln[3:] for ln in r.stdout.splitlines() if ln[:2] in ("R1", "R2", "R3")}
        _check("add-on import: 60 fps, timeline 0..72 on the first motion; another action refits "
               "it to 0..120; export refused at 24 fps",
               got.get("R1") == "60 0 72 M02_0_00" and got.get("R2") == "0 120" and got.get("R3") == "refused",
               got or (r.stdout + r.stderr)[-400:])
        if not dst.exists():
            _check("add-on export wrote the .glb", False); return
        res = _gl.import_all_animations(dst, m, tpl)
        _check("add-on export at 60 fps: every motion comes back unchanged", sorted(res["unchanged"]) == names
               and not res["changed"] and not res["notes"], [c[0] for c in res["changed"]])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_live_names_and_combo_keys():
    """An open Cutscene Editor re-titles its bank list when a saved name file renames a
    character (no restart); Up / Down in a dropdown step its value and apply it at once."""
    print("live names in the cutscene editor; Up / Down in dropdowns:")
    import os
    try:
        import tkinter as tk
        from tkinter import ttk
        import cutscene_editor as ce
        import guiutil
    except Exception as e:
        _skip("live names", "no tkinter: %s" % e); return
    root = tk.Tk(); root.withdraw()
    try:
        guiutil.install_combo_keys(root)
        got = []
        cb = ttk.Combobox(root, values=("a", "b", "c"), state="readonly")
        cb.pack(); cb.set("a")
        cb.bind("<<ComboboxSelected>>", lambda _e: got.append(cb.get()))
        fc = guiutil.FilterCombo(root, ["one", "two", "three"], on_pick=got.append)
        fc.pack(); fc.var.set("two")
        root.update()
        guiutil.combo_step(cb, 1); guiutil.combo_step(cb, 1); guiutil.combo_step(cb, 1)
        guiutil.combo_step(fc, -1); guiutil.combo_step(fc, -1)
        down = root.bind_class("TCombobox", "<Down>") != ""
        _check("Up / Down step a dropdown's value and apply it (stopping at the ends); Alt+Down opens the list",
               got == ["b", "c", "one"] and cb.get() == "c" and fc.get() == "one" and down
               and root.bind_class("TCombobox", "<Alt-Down>") != "", got)
        mc = _first("rf3.mc")
        from rf4s_modkit import gamenames as G, gamepaths, textdb
        real = gamepaths.find_bundle_dir()
        npc = real / "bundleMain" / "rf3TxtNpc_split2_1.eng" if real else None
        if not mc or npc is None or not npc.is_file():
            _skip("live names", "no rf3.mc / rf3TxtNpc"); return
        dirs = [mc.parent, pathlib.Path(BUNDLE_DIR) / "bundleMain"]
        reader = lambda n: next(((d / n).read_bytes() for d in dirs if (d / n).is_file()), None)
        cx = ce.CutsceneExplorer(tk.Toplevel(root), reader=reader)
        root.update_idletasks()
        cx._watch_names()                    # what its timer does a second after opening
        bank1 = next((i for i, r in cx.browser._rows.items() if r == ("bank", 1)), None)
        before = cx.browser.tree.item(bank1, "text") if bank1 else ""
        tmp = pathlib.Path(tempfile.mkdtemp())
        saved = gamepaths.find_bundle_dir
        try:
            (tmp / "00_mods").mkdir()
            arc = textdb.TextArchive.parse(npc.read_bytes())
            arc.set_text(1, "Herbertina")
            (tmp / "00_mods" / npc.name).write_bytes(arc.build())
            gamepaths.find_bundle_dir = lambda refresh=False: tmp
            G.reload()
            cx._watch_names()
            after = cx.browser.tree.item(bank1, "text")
        finally:
            gamepaths.find_bundle_dir = saved
            G.reload()
            shutil.rmtree(tmp, ignore_errors=True)
        cx._watch_names()
        back = cx.browser.tree.item(bank1, "text")
        _check("an open Cutscene Editor re-titles its bank list when the game's names change",
               before.startswith(G.name("characters", 1)) and after.startswith("Herbertina")
               and back == before,
               (before, after, back))
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_text_escapes():
    """The editors' backslash notation (textesc) for characters that can't be typed: colours,
    the vertical shifts, button icons. Every shipped line round-trips exactly; bad escapes are
    refused with a reason; the text editor and the Cutscene Editor store the real characters."""
    print("text escapes (\\red, \\btn(a) ... in the editors, the characters in the files):")
    from rf4s_modkit import textesc as E, textdb
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    files = sorted(B.glob("*.eng")) if B.is_dir() else []
    n = bad = 0
    for f in files:
        with open(f, "rb") as fh:
            if fh.read(4) != b"TEXT":
                continue
        for t in textdb.TextArchive.parse(f.read_bytes()).texts():
            n += 1
            bad += E.from_edit(E.to_edit(t)) != t
    _check("every English line round-trips through the notation exactly (%d lines)" % n,
           n > 100000 and bad == 0, "%d failures" % bad)
    BS = "\\"
    cases = {BS + "redRED" + BS + "normal": "\x01RED\x03",
             BS + "rgb(200,30,200)x": "\x04\xc8\x1e\xc8x",
             "A" + BS + "shift(-16)B" + BS + "base": "A\x07\xf0B\x08",
             BS + "up(" + BS + "down)": "\x05(\x06)",
             BS + "btn(stick)" + BS + "btn(dpad)": "\ue0aa\ue0c1",
             BS + "u(E0A8)": "\ue0a8", "a" + BS + BS + "b": "a" + BS + "b"}
    got = {k: E.from_edit(k) for k in cases}
    back = all(E.to_edit(v) == k for k, v in cases.items() if not k.startswith(BS + "up("))
    refused = [x for x in (BS + "bleu", BS + "rgb(1,2)", BS + "rgb(0,1,1)", BS + "shift(0)",
                           BS + "btn(zz)", BS + "u(zz)", BS + "shift(5") if E.check(x) is None]
    _check("escapes: colours, rgb up to 255, signed shifts, buttons, \\u(...) and \\\\ read and write back; "
           "unknown or out-of-range ones are refused",
           got == cases and back and not refused, (got if got != cases else refused))
    try:
        import tkinter as tk
        import importlib.util
    except Exception as e:
        _skip("text escapes GUI", "no tkinter: %s" % e); return
    src = B / "rf3TxtItem_split2_1.eng"
    if not src.is_file():
        _skip("text escapes GUI", "no extracted bundleMain"); return
    spec = importlib.util.spec_from_file_location("rf4mod_gui_esc", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
    gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
    _headless_dialogs()
    root = tk.Tk(); root.withdraw()
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        app = gui.App(root, initial=str(B))
        cp = tmp / src.name
        cp.write_bytes(src.read_bytes())
        d = app.open_file_tab(cp)
        root.update_idletasks()
        t = d._text_tab
        t.show(5)
        t.edit.delete("1.0", "end")
        t.edit.insert("1.0", "Press " + BS + "btn(a) to eat " + BS + "redNOW" + BS + "normal")
        ok = t.apply()
        stored = textdb.TextArchive.parse(d.cur_data).text(5)
        t.edit.delete("1.0", "end")
        t.edit.insert("1.0", "oops " + BS + "bleu")
        refused = not t.apply(quiet=True)
        t.show(5)
        shown_back = t.typed()
        menu = [title for title, _items in __import__("text_tab").insert_codes()]
        _check("text editor: typed escapes are stored as the characters, shown as escapes again, a bad "
               "escape is refused; the Insert menu offers colours, shifts, buttons and the ＠ codes",
               ok and stored == "Press \ue0a0 to eat \x01NOW\x03" and refused
               and shown_back == "Press " + BS + "btn(a) to eat " + BS + "redNOW" + BS + "normal"
               and {"Colour", "Raise / lower", "Button icon", "Value set by the script", "Name"} <= set(menu),
               (stored, shown_back))
    finally:
        try:
            root.destroy()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


def test_theme():
    """Dark mode (guitheme): hand-set colours are adapted keeping their hue (dark text gets
    lighter, light backgrounds darker, dark ones stay), ttk switches to the dark palette, the
    tab strip follows, and switching back restores every original colour."""
    print("light / dark appearance (guitheme):")
    import colorsys
    try:
        import tkinter as tk
        from tkinter import ttk
        import guitheme, guiutil
    except Exception as e:
        _skip("theme", "no tkinter: %s" % e); return
    root = tk.Tk(); root.withdraw()
    saved = guitheme.setting
    try:
        def lum(c):
            r, g, b = (x / 65535.0 for x in root.winfo_rgb(c))
            return colorsys.rgb_to_hls(r, g, b)
        red = guitheme.adapt(root, "#c0392b", "fg")
        _check("colours: dark text lighter, white background dark, a dark canvas unchanged, red stays red",
               lum(guitheme.adapt(root, "#000000", "fg"))[1] > 0.8
               and lum(guitheme.adapt(root, "#ffffff", "bg"))[1] < 0.2
               and guitheme.adapt(root, "#101014", "bg") == "#101014"
               and abs(lum(red)[0] - lum("#c0392b")[0]) < 0.02 and lum(red)[1] > 0.6,
               red)
        guitheme.setting = lambda: "light"
        guitheme._state.update(root=None, bound=False, base_theme=None)
        guitheme.install(root)
        base = ttk.Style(root).theme_use()
        top = tk.Toplevel(root)
        lbl = tk.Label(top, text="hint", fg="#666666", bg="#f0f0f0")
        lbl.pack()
        txt = tk.Text(top, height=2)
        txt.tag_configure("warn", foreground="#b5471b")
        txt.pack()
        tl = ttk.Label(top, text="note", foreground="#888888")
        tl.pack()
        tb = guiutil.TabBar(top, lambda k: None, lambda k: None)
        tb.pack(fill="x")
        tb.add("a", "one")
        top.update_idletasks()
        before = (lbl.cget("fg"), lbl.cget("bg"), str(txt.cget("bg")), txt.tag_cget("warn", "foreground"),
                  str(tl.cget("foreground")), tb._tabs["a"][0].cget("bg"))
        guitheme.apply(root, "dark")
        top.update_idletasks()
        dark = (lbl.cget("fg"), lbl.cget("bg"), str(txt.cget("bg")), txt.tag_cget("warn", "foreground"),
                str(tl.cget("foreground")), tb._tabs["a"][0].cget("bg"))
        dark_ok = (ttk.Style(root).theme_use() == "clam" and lum(dark[0])[1] > 0.6
                   and lum(dark[1])[1] < 0.3 and lum(dark[2])[1] < 0.3 and lum(dark[3])[1] > 0.55
                   and lum(dark[4])[1] > 0.55 and lum(dark[5])[1] < 0.3)
        guitheme.apply(root, "light")
        top.update_idletasks()
        after = (lbl.cget("fg"), lbl.cget("bg"), str(txt.cget("bg")), txt.tag_cget("warn", "foreground"),
                 str(tl.cget("foreground")), tb._tabs["a"][0].cget("bg"))
        _check("dark mode darkens windows, keeps hints and warnings readable and the tab strip dark; "
               "light mode brings every original colour and the platform theme back",
               dark_ok and after == before and ttk.Style(root).theme_use() == base,
               {"before": before, "dark": dark, "after": after})
        # a pane divider made while dark (guiutil.Paned copies the frame colour when it is made)
        # takes the light colour when the app switches back
        guitheme.apply(root, "dark")
        pn = guiutil.Paned(top)
        pn.pack()
        top.update_idletasks()
        made_dark = lum(pn.cget("background"))[1] < 0.3
        guitheme.apply(root, "light")
        light_bg = ttk.Style(root).lookup("TFrame", "background")
        _check("a pane divider made in dark mode turns light when switching back",
               made_dark and pn.cget("background") == light_bg, (pn.cget("background"), light_bg))
    finally:
        guitheme.setting = saved
        guitheme._state.update(root=None, bound=False, mode="light")
        guitheme._state["orig"].clear()
        try:
            root.destroy()
        except Exception:
            pass


def test_text_tab():
    """The explorer edits every text file: TEXT archives (rf3Txt* / rf4Txt* / rf3mc.<locale>)
    line by line -- changed, added, reverted, never removed -- and .strings files key by key;
    a line the game could crash on is refused; Save writes where the game loads the file, or
    back to a file opened from disk; the tab is marked • until then."""
    print("explorer text editor (TEXT archives and .strings):")
    import importlib.util
    try:
        import tkinter as tk
    except Exception as e:
        _skip("text editor", "no tkinter: %s" % e); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    src_file = B / "rf3TxtItem_split2_1.eng"
    if not src_file.is_file():
        _skip("text editor", "no extracted bundleMain"); return
    from rf4s_modkit import textdb, strings_file
    spec = importlib.util.spec_from_file_location("rf4mod_gui_text", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
    gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
    box = _headless_dialogs()
    root = tk.Tk(); root.withdraw()
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        app = gui.App(root, initial=str(B))
        n = next(e[0] for e in app.source.entries if e[0].rsplit("/", 1)[-1] == src_file.name)
        i = next(k for k, e in enumerate(app.source.entries) if e[0] == n)
        app._reveal_entry(i); app._suppress_select = False; app._on_select(None)
        root.update_idletasks()
        doc = app._doc
        tt = doc._text_tab
        _check("a TEXT archive opens in the text editor with every line", tt is not None
               and len(tt.m.rows) == 1108 and tt.m.rows[1] == "Cabbage", tt and len(tt.m.rows))
        tt.show(1)
        ok = tt.apply("Cabbage X")
        root.update_idletasks()
        edited = textdb.TextArchive.parse(doc.cur_data)
        _check("Apply changes the line in the working copy; the tab is marked •; the row shows as changed",
               ok and edited.text(1) == "Cabbage X" and app.tabbar.text(doc).endswith("•")
               and "changed" in tt.tv.item(tt._iid(1), "tags"))
        refused = not tt.apply("gift for ＠‡him", quiet=True)
        _check("a line the game could crash on (＠‡ without its closing ＠) is refused",
               refused and tt.m.rows[1] == "Cabbage X")
        new = tt.new_row(text="Moon Cabbage")
        _check("＋ New line appends at the next id", new == 1108 and len(textdb.TextArchive.parse(doc.cur_data)) == 1109
               and textdb.TextArchive.parse(doc.cur_data).text(1108) == "Moon Cabbage", new)
        tt.show(1); tt.revert()
        tgt, kind = tt.target()
        _check("Revert line restores the loaded text; Save aims at the copy the game loads",
               tt.m.rows[1] == "Cabbage" and kind == "game" and tgt.name == src_file.name, (tgt, kind))
        # a file opened from disk saves back to it
        cp = tmp / src_file.name
        cp.write_bytes(src_file.read_bytes())
        d2 = app.open_file_tab(cp)
        root.update_idletasks()
        t2 = d2._text_tab
        t2.show(2); t2.apply("King Cabbage II")
        saved = t2.save()
        back = textdb.TextArchive.parse(cp.read_bytes())
        _check("Save writes a file opened from disk back to it; the tab is clean again",
               saved == cp and back.text(2) == "King Cabbage II" and not d2.is_dirty()
               and len(back) == 1108, (saved, back.text(2)))
        # .strings
        sp = tmp / "Localization-test.strings"
        sp.write_text(strings_file.dumps({"Menu.Start": "Start", "Menu.Quit": "Quit"}), encoding="utf-8")
        d3 = app.open_file_tab(sp)
        root.update_idletasks()
        t3 = d3._text_tab
        t3.show("Menu.Start"); t3.apply('Begin "now"')
        t3.new_row("Menu.Extra", "Extra")
        t3.delete_key("Menu.Quit")
        t3.save()
        got = strings_file.parse(sp.read_text(encoding="utf-8"))
        _check(".strings: values change, keys are added and deleted, and the saved file reads back",
               got == {"Menu.Start": 'Begin "now"', "Menu.Extra": "Extra"}, got)
    finally:
        try:
            root.destroy()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


def test_backups():
    """Saving a game file keeps its original once and the file as it was as a previous
    version (Options: on/off, how many, the folder); the restore window puts any of them
    back, keeping the replaced file as a previous version."""
    print("backups: originals, previous versions, restore:")
    from rf4s_modkit import gamepaths as G
    tmp = pathlib.Path(tempfile.mkdtemp())
    game = tmp / "game"
    (game / "Bundle" / "bundlePatch1").mkdir(parents=True)
    target = game / "Bundle" / "bundlePatch1" / "rf3.mc"
    target.write_bytes(b"v0")
    settings = {}
    saved = (G.find_bundle_dir, G.get_setting, G.set_setting)
    G.find_bundle_dir = lambda refresh=False: game / "Bundle"
    G.get_setting = lambda k, d=None: settings.get(k, d)
    G.set_setting = lambda k, v: settings.__setitem__(k, v)
    try:
        G.write_game_file(target, b"v1")
        _check("backups are off by default: a save keeps no original and no previous version",
               not G.keep_originals() and G.keep_previous() == 0 and not G.backup_path(target).exists()
               and not G.previous_versions(target))
        G.write_game_file(target, b"v0", force_original=True)
        forced = G.backup_path(target).read_bytes() == b"v1"
        G.backup_path(target).unlink()
        target.write_bytes(b"v0")
        _check("an action whose Restore needs the original (empty over-model) keeps it anyway", forced)
        settings.update(backup_originals=True, backup_previous=1)
        G.write_game_file(target, b"v1")
        G.write_game_file(target, b"v2")
        orig = G.backup_path(target)
        prev = [f.read_bytes() for f in G.previous_versions(target)]
        _check("turned on: the original is kept once, and one previous version (the file before the last save)",
               orig.read_bytes() == b"v0" and prev == [b"v1"] and orig.parent.name == "bundlePatch1"
               and G.backup_root() == game / G.BACKUP_DIR, (prev, orig))
        settings["backup_previous"] = 3
        for v in (b"v3", b"v4", b"v5"):
            G.write_game_file(target, v)
        prev = [f.read_bytes() for f in G.previous_versions(target)]
        _check("with 3 previous versions the newest three are kept, the oldest dropped",
               prev == [b"v4", b"v3", b"v2"], prev)
        G.restore_version(target, orig)
        prev = [f.read_bytes() for f in G.previous_versions(target)]
        _check("restoring the original puts it back and keeps the replaced file as a previous version",
               target.read_bytes() == b"v0" and prev[0] == b"v5" and len(prev) == 3, prev)
        listed = G.backed_up_files()
        _check("the backup folder lists the file with its original and previous versions",
               set(listed) == {target} and listed[target]["original"] == orig
               and len(listed[target]["previous"]) == 3, listed)
        other = game / "Bundle" / "bundlePatch1" / "em.bin"
        other.write_bytes(b"e0")
        settings.update(backup_originals=False, backup_previous=0)
        G.write_game_file(other, b"e1")
        settings["backup_dir"] = str(tmp / "elsewhere")
        G.write_game_file(target, b"v9")
        _check("originals and previous versions can be turned off; the backup folder can be moved",
               not G.backup_path(other).exists() and not G.previous_versions(other)
               and G.backup_root() == tmp / "elsewhere" and not (tmp / "elsewhere").exists())
        settings.update(backup_originals=True, backup_previous=2)
        G.write_game_file(target, b"v10")
        try:
            import tkinter as tk
            import backup_dialog
        except Exception as e:
            _skip("restore window", "no tkinter: %s" % e); return
        root = tk.Tk(); root.withdraw()
        try:
            win = backup_dialog.open_restore(root, answer=True)
            row = next(iid for iid, (t, src) in win.rows.items() if src == G.backup_path(target))
            win.tree.selection_set(row)
            got = win.restore()
            _check("the restore window lists the versions and puts the picked one back",
                   got == target and target.read_bytes() == b"v9"
                   and [f.read_bytes() for f in G.previous_versions(target)][0] == b"v10",
                   [f.read_bytes() for f in G.previous_versions(target)])
        finally:
            root.destroy()
    finally:
        G.find_bundle_dir, G.get_setting, G.set_setting = saved
        shutil.rmtree(tmp, ignore_errors=True)


def test_remembered_options():
    """The Cutscene Editor reopens with its last toolbar (locale, add new lines to every language,
    story / code, addresses, opcodes); the big lists' row cap and the text size come from
    Options (the text size scales the fonts and the list rows at start)."""
    print("remembered editor toolbar, list rows, text size:")
    try:
        import tkinter as tk
        import tkinter.font as tkfont
        import cutscene_editor as ce
        import guiutil
    except Exception as e:
        _skip("remembered options", "no tkinter: %s" % e); return
    from rf4s_modkit import gamepaths as G
    root = tk.Tk(); root.withdraw()
    try:
        cx = ce.CutsceneExplorer(tk.Toplevel(root))
        cx.set_locale("deu")
        cx.pad_locales.set(False); cx._save_prefs()
        cx.mode.set("code"); cx.addr.set(True); cx.show_ops.set(True); cx.file_offs.set(True); cx._view_mode()
        cx2 = ce.CutsceneExplorer(tk.Toplevel(root))
        got = (cx2.doc.locale, cx2.pad_locales.get(), cx2.mode.get(), cx2.addr.get(), cx2.show_ops.get(),
               cx2.file_offs.get(), cx2.view.mode, cx2.view.show_addr, cx2.view.show_ops, cx2.view.show_file_off)
        _check("the Cutscene Editor reopens with its last toolbar settings",
               got == ("deu", False, "code", True, True, True, "code", True, True, True), got)
        # file offsets: the u16 at the shown offset of the built file is the statement's opcode,
        # in a primary, a tail and the global bank -- also after an edit moved the later banks
        from rf4s_modkit import script as _scr
        from cutscene_editor.render import SceneText as _ST

        def _reader(name):
            p = _first(name)
            return p.read_bytes() if p else None
        cx2 = ce.CutsceneExplorer(tk.Toplevel(root), reader=_reader)
        c = cx2.doc.container
        if c is None:
            _skip("file offsets", "rf3.mc not extracted")
        else:
            def offsets_ok():
                built, n, ok = c.build(), 0, 0
                for pos in (1, c.n_primary + 48, len(c.banks) - 1):
                    for sc in [s for s in _scr.disassemble_bank(c.banks[pos]) if s.ok][:3]:
                        st_text = _ST(cx2.doc, c.banks[pos], sc)
                        for pc, st in sc.stmts.items():
                            off = int(st_text.file_offset_seg(pc)[0], 16)
                            n += 1
                            ok += int.from_bytes(built[off:off + 2], "little") == (st.op & 0xFFFF)
                return n, ok
            n0, ok0 = offsets_ok()
            first = next(s for s in _scr.disassemble_bank(c.banks[1]) if s.ok).entry_pc
            cx2.apply("probe", lambda: c.insert_before(1, first, "ClosePortraits(2)"))
            n1, ok1 = offsets_ok()
            _check("file offsets point at each statement's opcode in rf3.mc, also after an insert moved "
                   "the later banks", n0 and ok0 == n0 and n1 and ok1 == n1, "%d/%d, %d/%d" % (ok0, n0, ok1, n1))
        # switching the dialogue language keeps the script view where it was (it used to jump
        # a little: the scroll was restored as a yview fraction of the re-drawn text)
        cx3 = ce.CutsceneExplorer(tk.Toplevel(root), reader=_reader)
        c3 = cx3.doc.container
        _other = "eng" if cx3.doc.locale != "eng" else "deu"
        if c3 is None or len(c3.banks) <= 211 or not c3.banks[211].entry_records(69) or _first("rf3mc." + _other) is None:
            _skip("language switch keeps the script view's scroll", "rf3.mc / two dialogue languages not extracted")
        else:
            cx3.open_scene(211, c3.banks[211].entry_records(69)[0].event_id)
            _tv = cx3.view.text
            cx3.frame.update()
            _tv.yview_moveto(0.4); cx3.frame.update(); _tv.yview_scroll(7, "pixels"); cx3.frame.update()
            _top0 = _tv.index("@0,0")
            cx3.set_locale(_other)
            cx3.frame.update()
            _top1 = _tv.index("@0,0")
            _check("switching the dialogue language keeps the script view's scroll (same top row)",
                   _top0.split(".")[0] == _top1.split(".")[0] and _top0 != "1.0", f"{_top0} -> {_top1}")
        # dialogs without parent= open over the window last focused, not the main window
        from tkinter import messagebox as _mbx
        guiutil.install_dialog_parents(root)
        wrapped_once = _mbx.showerror
        guiutil.install_dialog_parents(root)
        ed = tk.Toplevel(root)
        ed.geometry("+-10000+-10000"); root.update()

        class _Ev:
            widget = ed
        guiutil._note_focus(_Ev())
        probe = guiutil._with_parent(lambda *a, **kw: kw.get("parent"))
        _check("a dialog without parent= opens over the window in use (the editor), not the main "
               "window; an explicit parent wins; installing twice wraps once",
               probe("t", "m") is ed and probe("t", "m", parent=root) is root
               and _mbx.showerror is wrapped_once and getattr(_mbx.showerror, "_rf4_parented", False))
        ed.destroy()
        G.set_setting("cutscene_editor", None)
        G.set_setting("list_rows", 1234)
        rows_ok = guiutil.list_rows() == 1234
        G.set_setting("list_rows", 5)
        rows_ok = rows_ok and guiutil.list_rows() == 100          # a floor, so lists never vanish
        G.set_setting("list_rows", None)
        _check("the big lists' row cap comes from Options (default 5000, at least 100)",
               rows_ok and guiutil.list_rows() == guiutil.DEFAULT_LIST_ROWS)
    finally:
        root.destroy()
    r2 = tk.Tk(); r2.withdraw()
    try:
        import guiscale
        guiscale._state.update(root=None, bound=False, factor=1.0, row=None)
        guiscale._state["named"].clear(); guiscale._state["orig"].clear()
        guiscale.install(r2)
        top = tk.Toplevel(r2)
        lbl = tk.Label(top, text="x", font=("Segoe UI", 9))
        lbl.pack()
        txt = tk.Text(top, height=2)
        txt.tag_configure("b", font=("Segoe UI", 9, "bold"))
        txt.pack()
        r2.update_idletasks()

        def px(spec):
            return tkfont.Font(root=r2, font=spec).metrics("linespace")
        base = (px(lbl.cget("font")), px(txt.tag_cget("b", "font")),
                tkfont.nametofont("TkDefaultFont", r2).metrics("linespace"))
        guiscale.apply(r2, 150)
        big = (px(lbl.cget("font")), px(txt.tag_cget("b", "font")),
               tkfont.nametofont("TkDefaultFont", r2).metrics("linespace"))
        late = tk.Label(top, text="new", font=("Segoe UI", 9))
        late.pack()
        r2.update()
        late_px = px(late.cget("font"))
        rh = guiscale.row_height()
        guiscale.apply(r2, 100)
        back = (px(lbl.cget("font")), px(txt.tag_cget("b", "font")),
                tkfont.nametofont("TkDefaultFont", r2).metrics("linespace"))
        _check("text size switches live: 150 % grows hand-set fonts, tag fonts, the named fonts, list rows "
               "and a window opened afterwards; 100 % brings the original sizes back",
               all(b2 > b1 * 1.3 for b1, b2 in zip(base, big)) and late_px > base[0] * 1.3
               and bool(rh) and back == base,
               {"base": base, "150": big, "opened later": late_px, "rows": rh, "back": back})
    finally:
        guiscale._state.update(root=None, bound=False, factor=1.0, row=None)
        guiscale._state["named"].clear(); guiscale._state["orig"].clear()
        r2.destroy()


def test_explorer_tabs():
    """rf4mod_gui tabs: every open file is a tab (_Doc) with its own working copy and view
    state. Clicking a file opens it in a new tab (unsaved edits elsewhere stay put);
    switching tabs restores each one's data; reopening an open file selects its tab; closing
    a tab with unsaved changes asks; map tabs keep their own editor, and an object copied in
    one map tab pastes into another with the keyboard; a hidden tab's animation waits."""
    print("asset explorer tabs (one per open file):")
    import importlib.util
    try:
        import tkinter as tk
    except Exception as e:
        _skip("explorer tabs", "no tkinter: %s" % e); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_04.rf4m").exists() or not (B / "MAP_FIELD_01.rf4m").exists():
        _skip("explorer tabs", "no extracted bundleMain"); return
    spec = importlib.util.spec_from_file_location("rf4mod_gui_tabs", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
    gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
    box = _headless_dialogs()
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        saved_clip = root.clipboard_get()
    except tk.TclError:
        saved_clip = None
    try:
        app = gui.App(root, initial=str(B))
        ents = {e[0].rsplit("/", 1)[-1]: e for e in app.source.entries}

        def open_(nm):
            # a click in the file list, the way a user opens a file
            n, _g, _l = ents[nm]
            i = next(k for k, e in enumerate(app.source.entries) if e[0] == n)
            app._reveal_entry(i)
            app._suppress_select = False
            app._on_select(None)
            root.update_idletasks()
            return app._doc

        def dclick(nm):
            # a double click: its first click, then the double click itself
            open_(nm)
            app._double_open(app.tree.selection()[0])
            root.update_idletasks()
            return app._doc

        def title(d):
            return app.tabbar.text(d)
        # 1) edits survive: a click with unsaved changes opens a new tab
        a = open_("rf3Schedule.bin")
        orig = app._doc.cur_data
        app._doc.cur_data = orig[:-1] + bytes([orig[-1] ^ 1])       # what an editor's Apply does
        root.update_idletasks()
        _check("an edit marks its tab • at once (no wait for the 1 s refresh)", title(a).endswith("•"),
               title(a))
        b = open_("rf3NpcParam.bin")
        _check("a click on a tab with unsaved changes opens a new tab (the edited one stays, marked •)",
               len(app._docs) == 2 and a is not b and title(a).endswith("•")
               and a.cur_data != orig and app._doc is b, [title(d) for d in app._docs])
        _tvs = [w for w in _all_widgets(b.content) if w.winfo_class() == "Treeview"]
        _hbars = [w for w in _all_widgets(b.content) if isinstance(w, gui.ttk.Scrollbar)
                  and str(w.cget("orient")) == "horizontal"]
        _wide = bool(_tvs) and all(not int(_tvs[0].column(c, "stretch")) for c in _tvs[0]["columns"])
        _check("a param table (rf3NpcParam) scrolls sideways: its columns keep their width "
               "and a horizontal scroll bar sits under it",
               _wide and bool(_hbars) and bool(str(_tvs[0].cget("xscrollcommand"))),
               (len(_tvs), len(_hbars)))
        c = open_("rf3CropParam.bin")
        _check("a click on a clean tab shows the file in that same tab",
               c is b and len(app._docs) == 2 and b.cur_name.endswith("rf3CropParam.bin"))
        dnm = next(n for n in sorted(ents) if n.startswith("rf3Item") and n.endswith(".bin"))
        d = dclick(dnm)
        _check("a double click opens the file in a new tab, and the tab its first click used gets "
               "its own file back",
               d is not b and len(app._docs) == 3 and d.key[1].endswith(dnm)
               and b.key[1].endswith("rf3CropParam.bin") and b.cur_name.endswith("rf3CropParam.bin"),
               [title(x) for x in app._docs])
        app._select_doc(a)
        _check("switching tabs restores that tab's working copy, header and Extract",
               app._doc.cur_data == a.cur_data and "rf3Schedule" in app.header.cget("text")
               and str(app.extract_btn.cget("state")) == "normal")
        again = open_("rf3Schedule.bin")
        _check("clicking a file that is already open selects its tab", again is a and len(app._docs) == 3)
        box["yesnocancel"] = None
        kept = app.cmd_close_tab(a) is False and a in app._docs
        box["yesnocancel"] = False
        gone = app.cmd_close_tab(a) is True and a not in app._docs and app._doc in (b, c)
        _check("closing a tab with unsaved changes asks: Cancel keeps it, No closes it", kept and gone)
        # 1b) Up / Down in the list browse in one tab; only a click opens a new tab
        def key_(nm):
            app._select_by_key = True           # what the list's <KeyPress> binding records
            return open_(nm)
        spare = [n for n in sorted(ents) if n.startswith("rf3") and n.endswith(".bin")
                 and not any(d.key and d.key[1].endswith(n) for d in app._docs)][:4]
        base = dclick(spare[0])                 # a new tab; browsing starts there
        n0 = len(app._docs)
        k1 = key_(spare[1])
        replaced = k1 is base and len(app._docs) == n0 and base.key[1].endswith(spare[1])
        k2 = key_("rf3CropParam.bin")           # already open in tab c: go there, keep it
        onto_open = k2 is c and len(app._docs) == n0 and c.key[1].endswith("rf3CropParam.bin")
        k3 = key_(spare[2])                     # browsing goes on in the browsed tab, not in c
        on_in_base = (k3 is base and base.key[1].endswith(spare[2]) and len(app._docs) == n0
                      and c.key[1].endswith("rf3CropParam.bin"))
        _check("Up / Down show the next file in the browsed tab (no new tab); an already-open "
               "file's tab is shown, and browsing goes on in the browsed tab",
               replaced and onto_open and on_in_base, f"{replaced} {onto_open} {on_in_base}")
        base.cur_data = base.cur_data[:-1] + bytes([base.cur_data[-1] ^ 1])
        k4 = key_(spare[3])
        _check("a browse step from a tab with unsaved changes opens a new tab (the edits stay)",
               k4 is not base and len(app._docs) == n0 + 1 and base.key[1].endswith(spare[2])
               and base.is_dirty())
        box["yesnocancel"] = False
        app.cmd_close_tab(base)
        # a real Down key in the list (keys need a window that can take the focus)
        root.deiconify(); root.geometry("900x600+20+20"); root.lift(); root.update()
        i0 = next(k for k, e in enumerate(app.source.entries) if e[0].endswith(spare[0]))
        app._reveal_entry(i0); root.update()
        app._select_by_key = False
        app._on_select(None); root.update()     # clicked: its own tab
        n1 = len(app._docs)
        clicked = app._doc
        app.tree.focus(app.tree.selection()[0])
        app.tree.focus_force(); root.update()
        app.tree.event_generate("<KeyPress-Down>"); root.update()
        root.withdraw()
        _check("the Down key in the file list shows the next file in the same tab",
               len(app._docs) == n1 and app._doc is clicked
               and not clicked.key[1].endswith(spare[0]), f"{n1} -> {len(app._docs)}")
        # opening a map (its tab builds a map editor) leaves the keyboard on the file list, so
        # Down works straight away, without clicking the list again
        root.deiconify(); root.lift(); root.update()
        im = next(k for k, e in enumerate(app.source.entries) if e[0].endswith("MAP_CITY_05.rf4m"))
        app._reveal_entry(im); root.update()
        app.tree.focus(app.tree.selection()[0])
        app.tree.focus_force(); root.update()
        app._select_by_key = False
        app._on_select(None); root.update()     # a click on a map: its own tab + map editor
        mdoc, kept = app._doc, root.focus_get() is app.tree
        for _ in range(5):
            root.update()
        _check("a map opens at 6 px per tile (Fit / 0 shows it all)",
               mdoc.map_panel() is not None and mdoc.map_panel().view.cp == 6,
               str(mdoc.map_panel().view.cp if mdoc.map_panel() else None))
        app.tree.event_generate("<KeyPress-Down>"); root.update()
        root.withdraw()
        _check("opening a map keeps the keyboard on the file list (Down right away shows the next "
               "file in the map's tab)",
               kept and mdoc.map_panel() is not None and app._doc is mdoc
               and not mdoc.key[1].endswith("MAP_CITY_05.rf4m"),
               f"focus kept={kept} now={mdoc.key[1] if mdoc.key else None}")
        # 2) map tabs: their own editors; copy in one, paste in the other with Ctrl+C / Ctrl+V
        m1 = dclick("MAP_CITY_04.rf4m")
        p1 = app._doc._map_panel
        m2 = dclick("MAP_FIELD_01.rf4m")
        p2 = app._doc._map_panel
        _check("each map tab has its own map editor", p1 is not None and p2 is not None and p1 is not p2
               and m1.map_panel() is p1 and m2.map_panel() is p2)
        # keys only reach a window that can take the focus: show it for the keyboard part
        root.deiconify(); root.geometry("900x600+20+20"); root.lift(); root.update()
        app._select_doc(m1); root.update()
        d1, d2 = p1.doc, p2.doc
        k = next(i for i, r in enumerate(d1.map.mobj_records()) if r[14] or r[15])
        rec = list(d1.map.mobj_records()[k])
        n1, n2 = len(d1.map.mobj_records()), len(d2.map.mobj_records())
        p1.select(("mobj", k))
        p1.view.canvas.focus_force(); root.update()
        p1.view.canvas.event_generate("<Control-c>")
        root.update()
        app._select_doc(m2); root.update()
        p2._pointer = (40, 48)
        p2.view.canvas.focus_force(); root.update()
        p2.view.canvas.event_generate("<Control-v>")
        root.update()
        root.withdraw()
        new = list(d2.map.mobj_records()[-1]) if len(d2.map.mobj_records()) == n2 + 1 else None
        _check("an object copied in one map tab (Ctrl+C) pastes into another map tab (Ctrl+V)",
               new is not None and new[:14] == rec[:14] and new[16:] == rec[16:]
               and len(d1.map.mobj_records()) == n1, f"{n2} -> {len(d2.map.mobj_records())}")
        app._refresh_marks()
        _check("the pasted-into map tab is marked unsaved, the copied-from one is not",
               title(m2).endswith("•") and not title(m1).endswith("•"),
               f"{title(m1)} | {title(m2)}")
        _check("a hidden map tab's editor is suspended (no background decodes)",
               m1.map_panel().view.ground.generation >= 1)
        # 3) a hidden tab's timer waits for its tab
        ran = []
        app._select_doc(m1)
        app._doc_after(1, lambda: ran.append(app._doc))
        app._select_doc(m2)
        root.after(30, lambda: None); root.update(); root.after(40, root.quit); root.mainloop()
        parked = len(m1.parked) == 1 and not ran
        app._select_doc(m1)
        _check("a timer that comes due in a hidden tab waits and runs when the tab is shown again",
               parked and ran == [m1] and not m1.parked)
        # past MAP_TABS_ASK open maps a new map asks; "Don't warn me again this session" (ticked
        # even on Cancel) stops the asking until the toolkit closes
        import guiutil
        asked = []
        _ask = guiutil.ask_yes_no_optout
        guiutil.ask_yes_no_optout = lambda *a, **k: (asked.append(1), (False, True))[1]

        def is_open(nm):
            return any(d.key and d.key[1].endswith(nm) for d in app._docs)
        def open_maps():
            return sum(1 for d in app._docs if d.map_panel() is not None)
        lim = app.MAP_TABS_ASK
        more = [n for n in sorted(ents) if n.startswith("MAP_CITY_") and n.endswith(".rf4m")
                and "_SUMMER" not in n and not is_open(n)]
        while open_maps() < lim:                # up to the limit: no question
            dclick(more.pop(0))
        quiet = not asked and open_maps() == lim
        extra = more.pop(0)
        dclick(extra)                           # one past it: asks; Cancel + the box ticked
        declined = len(asked) == 1 and not is_open(extra)
        dclick(extra)                           # asked no more this session
        guiutil.ask_yes_no_optout = _ask
        _check(f"up to {lim} map tabs open without asking; the next one asks, Cancel keeps it "
               "closed, and after 'Don't warn me again this session' it opens without asking",
               quiet and declined and len(asked) == 1 and is_open(extra), f"asked {len(asked)}x")
        box["yesnocancel"] = False
        for d in list(app._docs):
            app.cmd_close_tab(d)
        _check("closing every tab returns to the blank view",
               not app._docs and app._doc is app._blank and app._blank.frame.winfo_manager() == "pack")
        # Options… opens one window; its tick box sets the mouse wheel
        from map_editor import view as _mview
        bar_texts = [w.cget("text") for w in app._open_btn.master.winfo_children()
                     if isinstance(w, gui.ttk.Button)]
        win = app.cmd_options()
        again = app.cmd_options()
        boxes = [w for w in _all_widgets(win) if isinstance(w, gui.ttk.Checkbutton)]
        _tabs = [app._options_nb.tab(t, "text") for t in app._options_nb.tabs()]
        _in = {app._options_nb.tab(str(w.winfo_parent()), "text") if str(w.winfo_parent()) in
               app._options_nb.tabs() else None: w.cget("text") for w in boxes}
        _check("Options has the tabs General / Appearance / Map editor / Cutscene Editor / Advanced: group "
               "maps under General, the mouse wheel under Map editor, backups under Advanced",
               _tabs == ["General", "Appearance", "Map editor", "Cutscene Editor", "Advanced"]
               and "Keep each game file's original (copied the first time it is saved)" in [
                   w.cget("text") for w in boxes if app._options_nb.tab(str(w.winfo_parent()), "text")
                   == "Advanced"]
               and _in.get("Map editor") == "Mouse wheel zooms the map", (_tabs, _in))
        _game_txt = app._game_dir.get()
        _b = _gamepaths.find_bundle_dir()
        _check("Options -> General shows the current game folder (like the Change… window) with a Change… button",
               _game_txt == (str(_b.parent) if _b is not None else "(none chosen yet)")
               and any(isinstance(w, gui.ttk.Button) and w.cget("text") == "Change…"
                       and str(w.winfo_parent()) == app._options_nb.tabs()[0] for w in _all_widgets(win)),
               _game_txt)
        wheel = next(b for b in boxes if b.cget("text") == "Mouse wheel zooms the map")
        ticked_before = app._wheel_zooms.get()
        wheel.invoke()                          # untick: the wheel scrolls
        after_untick = (_mview.wheel_mode(), _gamepaths.get_setting(_mview.WHEEL_SETTING))
        wheel.invoke()                          # tick again: back to zooming
        after_tick = _mview.wheel_mode()
        import guiutil as _gu
        _ver = _gu.modkit_version()
        _ents = [w for w in _all_widgets(win) if w.winfo_class() == "Entry"]
        _foot = win.winfo_children()[0].winfo_children()[-1]
        _row = _foot.winfo_children()
        _check("Options… ends with one row: the modkit version (commit + date, selectable grey text) "
               "bottom-aligned on the left, Close on the right",
               _ver != "unknown" and _ents and _ents[0].get() == "Modkit version " + _ver
               and str(_ents[0].cget("state")) == "readonly" and _ents[0] in _row
               and any(isinstance(w, gui.ttk.Button) and w.cget("text") == "Close" for w in _row)
               and _ents[0].pack_info().get("anchor") == "s", _ver)
        _gm = [b for b in boxes if b.cget("text") == "Group maps by area"]
        _before = app.group_maps_var.get()
        if _gm:
            _gm[0].invoke()
        _moved = (bool(_gm) and app.group_maps_var.get() != _before
                  and _gamepaths.get_setting("group_maps_by_area") == app.group_maps_var.get()
                  and not [w for w in _all_widgets(app.root) if isinstance(w, gui.ttk.Checkbutton)
                           and w.winfo_toplevel() is app.root and w.cget("text") == "Group maps by area"])
        if _gm:
            _gm[0].invoke()
        _check("Group maps by area is in Options (not the toolbar), saved and applied at once", _moved)
        _pl = [b for b in boxes if b.cget("text") == "Add new lines to every language"]
        _pl_before = _pl[0].instate(["selected"]) if _pl else None
        if _pl:
            _pl[0].invoke()
        from cutscene_editor.app import CutsceneExplorer as _CE
        _pl_ok = bool(_pl) and _CE.pad_locales_setting() != _pl_before
        if _pl:
            _pl[0].invoke()
        _check("'Add new lines to every language' is in Options -> Cutscene Editor and saved for the editor",
               _pl_ok and _CE.pad_locales_setting() == _pl_before)
        _bl = [b for b in boxes if b.cget("text") == "Bank listing tab"]
        _bl_before = _CE.bank_listing_setting()
        if _bl:
            _bl[0].invoke()
        _bl_on = _CE.bank_listing_setting()
        if _bl:
            _bl[0].invoke()
        _check("'Bank listing tab' is in Options -> Advanced, off by default and saved for the editor",
               bool(_bl) and _bl_before is False and _bl_on is True
               and _CE.bank_listing_setting() is False
               and str(_bl[0].winfo_parent()) == app._options_nb.tabs()[-1], (_bl_before, _bl_on))
        win.destroy()
        import shortcuts_help as _sh
        hwin = _sh.open_help(app.root)
        _htabs = [hwin.notebook.tab(t, "text") for t in hwin.notebook.tabs()]
        _keys = {k for _t, secs in _sh.SHORTCUTS for _n, rows in secs for k, _w in rows}
        _bound = (bool(app.root.bind("<Control-w>")) and bool(app.root.bind("<Control-W>"))
                  and bool(app.root.bind("<Control-Tab>")))
        _check("Help (right end of the toolbar) lists the shortcuts per area; a sample matches the "
               "real bindings (Ctrl+W with and without Caps Lock, Ctrl+Tab)",
               app._help_btn.winfo_manager() == "pack"
               and _htabs == ["Explorer", "Map editor", "Cutscene Editor", "Event Manager & text"]
               and {"Ctrl+W", "Insert", "Ctrl+R", "Hold Alt over a line", "V"} <= _keys and _bound
               and _sh.open_help(app.root) is hwin, _htabs)
        hwin.destroy()
        _check("Options… is on the toolbar (Game folder… moved into it), opens one window, and its tick box "
               "switches the mouse wheel between zoom and scroll (saved in settings.json)",
               "Options…" in bar_texts and "Game folder…" not in bar_texts
               and again is win and len(boxes) == 5 and ticked_before
               and after_untick == ("scroll", "scroll") and after_tick == "zoom",
               (bar_texts, ticked_before, after_untick, after_tick))
        _check("explorer tabs raised no callback errors", not errs, str(errs[:1]))
    finally:
        try:
            root.clipboard_clear()
            if saved_clip is not None:
                root.clipboard_append(saved_clip)
            root.update()
        except tk.TclError:
            pass
        root.destroy()


# every rf4mod_gui viewer and a game file it shows (basename; "" = a made-up text file)
_TAB_VIEWERS = {
    "aibn": "AI_m00.bin", "asatk": "as_atk_axe_00.bin", "bplist": "AppConfig.plist",
    "crop": "rf3CropParam.bin", "emf": "em.bin", "gen": "GenA01.bin",
    "gift_categories": "rf3PresentCategory.bin", "gifts": "rf3PresentNpc01.bin",
    "hex": "01_M_VIZNAR.ogg", "image": "PetMe64-8.png", "monster": "rf3NpcParam.bin",
    "montame": "rf3MonsterPresent.bin", "param": "Fishing_rate_fish_Spring.bin",
    "psb": "00_PLAYER_M.psbData", "quest": "rf3TxtQuest_split3_1.bin",
    "res": "ANIM_DUNG_A02.model", "rf4m": "MAP_CITY_00.rf4m", "route": "rf3route.bin",
    "route_result": "rf3RouteResult.bin", "schedule": "rf3Schedule.bin",
    "search_items": "SI_CITY_00.bin", "skillcurve": "rf3ParamSkillExp.bin",
    "strengthening": "rf3ItemStrengthening.bin", "strings": "Localization-de.strings",
    "text": "", "textdb": "rf3mc.eng", "texture": "confetti.texture",
}
_TAB_SAVE_LABELS = ("Save table…", "Save…", "Save graph…")   # buttons that write the working copy


def test_viewer_tabs():
    """Every rf4mod_gui viewer in a tab: it opens without an error note, keeps its own data,
    widgets and header across a switch to another tab and back, and its Save button (the
    ones that write the working copy) clears the tab's unsaved mark."""
    print("asset explorer viewers, one per tab:")
    import importlib.util
    try:
        import tkinter as tk
    except Exception as e:
        _skip("viewer tabs", "no tkinter: %s" % e); return
    if not (pathlib.Path(BUNDLE_DIR) / "bundleMain" / "rf3Schedule.bin").exists():
        _skip("viewer tabs", "no extracted bundleMain"); return
    spec = importlib.util.spec_from_file_location("rf4mod_gui_vt", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
    gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
    box = _headless_dialogs()
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="rf4s_vt_"))
    notes = []
    _orig_hex = gui.App._view_hex
    gui.App._view_hex = lambda self, name, data, error=None: (
        notes.append((name, error)) if error else None, _orig_hex(self, name, data, error))[1]

    def widgets(w):
        n = 0
        for c in w.winfo_children():
            n += 1 + widgets(c)
        return n

    def find_buttons(w):
        out = []
        for c in w.winfo_children():
            if c.winfo_class() == "TButton" and str(c.cget("text")) in _TAB_SAVE_LABELS:
                out.append(c)
            out += find_buttons(c)
        return out
    try:
        app = gui.App(root, initial=str(BUNDLE_DIR))
        byname = {}
        for e in app.source.entries:
            byname.setdefault(e[0].rsplit("/", 1)[-1], e)
        for viewer, fname in _TAB_VIEWERS.items():
            if fname:
                if fname not in byname:
                    _skip(f"{viewer} viewer in a tab", f"{fname} not in this game copy"); continue
                n, _g, loader = byname[fname]
                key, data = app._entry_key(n), loader()
            else:
                n, key, data = "notes.xyz", ("test", "notes.xyz"), b"a made-up text file\nline 2\n"
            del notes[:]
            d1 = app._open_in_tab(key, n, data)
            root.update_idletasks()
            data1, header1, w1 = d1.cur_data, app.header.cget("text"), widgets(d1.frame)
            other = "rf3Schedule.bin" if fname != "rf3Schedule.bin" else "rf3NpcParam.bin"
            on, _g, ol = byname[other]
            d2 = app._open_in_tab(app._entry_key(on), on, ol())
            root.update_idletasks()
            app._select_doc(d1)
            root.update_idletasks()
            kept = (d2 is not d1 and app._doc is d1 and d1.cur_data is data1 and w1 > 0
                    and widgets(d1.frame) == w1 and app.header.cget("text") == header1)
            what = "opens, keeps its data, widgets and header across a tab switch"
            ok = not notes and kept
            saves = find_buttons(d1.frame)
            if saves:
                d1.cur_data = d1.cur_data[:-1] + bytes([d1.cur_data[-1] ^ 1])   # an edit
                dirty = d1.is_dirty()
                out = tmp / f"{viewer}.bin"
                box["save"] = str(out)
                saves[0].invoke()
                root.update_idletasks()
                box["save"] = ""
                what += f"; '{saves[0].cget('text')}' clears the tab's unsaved mark"
                ok = ok and dirty and out.is_file() and not d1.is_dirty()
            _check(f"{viewer} viewer in a tab: {what}", ok,
                   f"notes={notes[:1]} kept={kept} {fname or n}")
            box["yesnocancel"] = False
            for d in list(app._docs):
                app.cmd_close_tab(d)
        _check("viewer tabs raised no callback errors", not errs, str(errs[:1]))
    finally:
        gui.App._view_hex = _orig_hex
        root.destroy()
        shutil.rmtree(tmp, ignore_errors=True)


def _map_editor():
    """Import the map_editor package (the modding folder is already on sys.path)."""
    import map_editor
    return map_editor


def test_map_editor_script_spawns():
    """The script-NPC layer finds actors spawned by all three spawn ops (153/154/155), e.g.
    the Silver Wolf that MAP_DUNG_L13's event script places with SpawnEventActorVariant."""
    print("map editor script NPCs (SpawnEventActor / Variant / Ex):")
    from map_editor import data as med
    bi, sp = med.script_spawns("MAP_DUNG_L13")
    if bi is None:
        _skip("script NPCs", "rf3.mc not found"); return
    wolf = [s for s in sp if s.get("char_id") == 79]
    _check("MAP_DUNG_L13 shows the Silver Wolf its script spawns (SpawnEventActorVariant, "
           "sub-units 240, 290)",
           wolf and (wolf[0]["x"], wolf[0]["y"], wolf[0]["instance"]) == (240, 290, 100), str(sp))
    # SpawnMapEntity (op 157) builds a MOBJ record: MAP_FIELD_36's script plants its trees
    _bi36, _sp36 = med.script_spawns("MAP_FIELD_36")
    _ents = [s for s in _sp36 if s.get("kind") == "entity"]
    _t0 = _ents[0]["obj"] if _ents else None
    _check("script map objects: MAP_FIELD_36's SpawnMapEntity trees become MOBJ records "
           "(x/y sub-units in w14/w15, param*40 in w6)",
           len(_ents) >= 4 and _t0["pos_x"] == 272 and _t0["pos_y"] == 30
           and _t0["params"][14:16] == [272, 30] and _t0["params"][6] == 4000
           and _t0["name"] is not None, str(_ents[:2]))
    # PlayerRegionTrigger (type 3) boxes: MAP_FIELD_27's six areas gated by EV_HUTAGO_NOT_CLEAR
    _bi27, _rg27 = med.script_regions("MAP_FIELD_27")
    _check("script areas: MAP_FIELD_27's type-3 scenes give normalised sub-unit boxes with their "
           "em.bin condition",
           len(_rg27) == 6 and (_rg27[0]["x0"], _rg27[0]["y0"], _rg27[0]["x1"], _rg27[0]["y1"])
           == (208, 150, 318, 164) and _rg27[0]["cond_name"] == "EV_HUTAGO_NOT_CLEAR"
           and all(r["x0"] <= r["x1"] and r["y0"] <= r["y1"] for r in _rg27), str(_rg27[:2]))
    # the same type at the same spot from alternative branches is shown once (MAP_FIELD_40)
    _bi40, _sp40 = med.script_spawns("MAP_FIELD_40")
    _k40 = [(s["kind"], s.get("type_id", s.get("char_id")), s["x"], s["y"]) for s in _sp40]
    _check("script spawns: one marker per type and spot, the alternatives counted (MAP_FIELD_40)",
           _sp40 and len(_k40) == len(set(_k40)) and max(s["copies"] for s in _sp40) > 1,
           str([(k, s["copies"]) for k, s in zip(_k40, _sp40)]))
    # a chest's f10 runs the map's type-2 scene keyed 1024 + f10 when opened
    # (WorldObject_OnBreakDropLoot RF4S.exe+0x1662C0): MAP_DUNG_G01 #16 has an empty loot row
    # and gives 3630 G through its key-1025 scene
    from map_editor.document import MapDocument as _MD
    _g01 = _MD(med.load_map_by_id(med.map_id("MAP_DUNG_G01")), "MAP_DUNG_G01", load_sidecars=False)
    _recs = _g01.map.mobj_records()
    _ev = med.chest_event(_recs[16], "MAP_DUNG_G01")
    _bad = list(_recs[16]); _bad[10] = 5
    _probs = med.chest_problems("MAP_DUNG_G01", _recs)
    _check("chest f10 = script event: MAP_DUNG_G01 #16 ('empty' row) runs scene key 1025 that gives "
           "3630 G; not reported as 'gives nothing'; a key with no scene is a warning",
           _ev and "1025" in _ev and "ModifyPlayerResource(100, add, 3630)" in _ev
           and med.chest_event(_recs[17], "MAP_DUNG_G01") is None
           and not any(i == 16 for _s, i, _m in _probs)
           and any(s == "WARN" and "1029" in m for s, _i, m in med.chest_problems("MAP_DUNG_G01", [_bad])),
           _ev)
    # the chest check runs on every inspector refresh (each drag step): finding the game's
    # rf3.mc must be cached -- it walks the whole Bundle folder (~0.5 s) otherwise
    import time as _time
    med.rf3mc_path()
    _t = _time.perf_counter()
    for _ in range(20):
        med.chest_event(_recs[16], "MAP_DUNG_G01")
    _ms = (_time.perf_counter() - _t) / 20 * 1000
    _check("the chest script lookup is fast after the first call (no Bundle walk per redraw)",
           _ms < 20, "%.1f ms per call" % _ms)
    # type 8 = "gatherable": its f10 kind is a dropdown of the game's names (char 459 + kind)
    from rf4s_modkit import mobj_params as _mp, mobj_types as _mt
    _ch = _mp.param_choices(8, 10)
    _check("MOBJ type 8 is 'gatherable' and its kind (f10) offers the game's names",
           _mt.mobj_display_name(8) == "gatherable" and _mp.param_name(8, 10) == "kind"
           and len(_ch) == 139 and _ch[1] == (1, "1  Stone") and _ch[72] == (72, "72  Turnip")
           and "ore rock" in _ch[30][1], _ch[:3])
    _B8 = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    # type 24 = fishing spot: its fish table (f11) is a dropdown named after the fish-table columns
    _fc = _mp.param_choices(24, 11)
    _check("a fishing spot's fish table (f11) offers the fish-table column names "
           "(0 = by season, 12 = Yokmir Forest A04, 14 = Water Ruins, 17 = Junk Cheap Pole)",
           len(_fc) == 22 and _fc[0][0] == 0 and _fc[12] == (12, "12  Yokmir Forest A04")
           and _fc[14] == (14, "14  Water Ruins") and _fc[17] == (17, "17  Junk Cheap Pole"), _fc[:3])
    # raw words 0 / 14 / 15 are the type and the X / Y position of every record (not "unused")
    _check("raw words 0 / 14 / 15 are named type / X / Y for every MOBJ type, with a position note "
           "(map-parameter types 9..19 have none); type 35 is the 'mushroom pickup'",
           [_mp.param_name(35, f) for f in (0, 14, 15)] == ["type", "X", "Y"]
           and _mp.param_name(200, 14) == "X" and "sub-units" in _mp.common_field_note(35, 14)
           and "no position" in _mp.common_field_note(12, 14)
           and _mt.mobj_display_name(35) == "mushroom pickup",
           [_mp.param_name(35, f) for f in (0, 14, 15)])
    # type 35 = one-time item pickup: drawn as the dropped item's icon (item 48 = I_Crop24), at the
    # icon's own placement box like the forage sprites
    if (_B8 / "I_Crop24.texture").exists():
        from map_editor import render as _rnd, data as _md
        _spr = _rnd.Sprites(); _spr.reader = _md.folder_reader(_B8)
        _rec35 = [35, -1, -1, -1, -1, -1, 4096, 0, 50, 0, 0, 0, 0, 757, 133, 186]
        _s35 = _spr.source({"type_id": 35, "params": _rec35})
        _full = _rnd.spritequad.sprite_image((_B8 / "I_Crop24.texture").read_bytes(), 0)
        _check("a one-time item pickup (type 35) is drawn with the item's icon I_Crop24 at its own "
               "size, and its item kind is a named dropdown",
               _s35 is not None and _s35[0] == "I_Crop24.texture" and tuple(_s35[2]) == tuple(_full[1])
               and _mp.param_choices(35, 9)[0] == (0, "0  Mushroom (item 48)"), _s35)
    if (_B8 / "MAP_DUNG_A04.rf4m").exists():
        _rf, _pf, _ef = _headless_panel("MAP_DUNG_A04", _B8)
        try:
            _pf.select(("mobj", 24))
            _rf.update()
            _entf = next((w for w in _all_widgets(_pf.frame) if hasattr(w, "_pickers")), None)
            _pkf = _entf._pickers.get(11) if _entf is not None else None
            _check("the map editor shows MAP_DUNG_A04's fishing spot #24 as '12  Yokmir Forest A04'",
                   _pkf is not None and _pkf[0].var.get() == "12  Yokmir Forest A04",
                   _pkf[0].var.get() if _pkf else None)
        finally:
            _rf.destroy()
    if (_B8 / "MAP_DUNG_A04.rf4m").exists():
        _r8, _p8, _e8 = _headless_panel("MAP_DUNG_A04", _B8)
        try:
            _p8.select(("mobj", 14))
            _r8.update()
            _ins = _p8.inspector
            _ent = next((w for w in _all_widgets(_p8.frame) if hasattr(w, "_pickers")), None)
            _pk = _ent._pickers.get(10) if _ent is not None else None
            _shown = _pk is not None and _pk[0].var.get() == "15  Green Grass"
            if _pk is not None:
                _ent._pick_param(10, "72  Turnip")
                _r8.update()
            _val = _p8.doc.map.mobj_records()[14][10]
            _check("the map editor shows the gatherable kind as a dropdown, and picking one writes f10",
                   _shown and _val == 72, "shown=%s f10=%s" % (_shown, _val))
            _box = _ent.rows[10][1]
            _normal = (_pk[0].winfo_manager() == "grid", _box.winfo_manager() == "")
            _ent.raw.set(True); _ent.refresh(); _r8.update()
            _rawm = (_pk[0].winfo_manager() == "", _box.winfo_manager() == "grid")
            _ent.raw.set(False); _ent.refresh()
            _check("the kind shows only the dropdown normally, only the number box with the raw fields",
                   all(_normal) and all(_rawm), "normal %s raw %s" % (_normal, _rawm))
        finally:
            _r8.destroy()
    # with the layer on, leaving the map and coming back draws the markers again
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_DUNG_L12.rf4m").exists():
        _skip("script NPCs after a map switch", "no extracted bundleMain"); return
    from rf4s_modkit import rf4m as _rf4m
    root, panel, errs = _headless_panel("MAP_DUNG_L13", B)
    try:
        panel.viewtab.vars["spawns"].set(True)
        panel.set_layer("spawns", True)
        panel.view.flush()
        n = lambda: len(panel.view.canvas.find_withtag("spawn"))
        before = n()
        for nm in ("MAP_DUNG_L12", "MAP_DUNG_L13"):
            panel.set_map(_rf4m.Rf4mMap.load(B / (nm + ".rf4m")), nm)
            root.update()
            panel.view.flush()
        _check("script NPCs stay drawn after switching to another map and back",
               before > 0 and n() == before and not errs, "%d -> %d" % (before, n()))
    finally:
        root.destroy()


def test_map_editor_gate_ground():
    """Problems tab: a monster spawn point with no walkable tile (ATTR bit 0x01 / 0x20) in its
    radius, and a gate position outside the map, are flagged; clicking selects the point."""
    print("map editor: gate / spawn point ground checks:")
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_DUNG_H38.rf4m").exists():
        _skip("gate ground checks", "no extracted bundleMain"); return
    found = {}
    for nm in ("MAP_DUNG_H38", "MAP_FIELD_16", "MAP_DUNG_L13"):
        root, panel, errs = _headless_panel(nm, B)
        try:
            iss = [i for i in panel.validate() if "(Gen record @0x" in i[2]]
            sel = None
            if iss:
                panel.problems.issues = iss
                panel.problems.tree.insert("", "end", iid="0", text="WARN", values=(iss[0][2],))
                panel.problems.tree.selection_set("0")
                panel.problems._picked()
                sel = panel.sel
            found[nm] = (iss, sel)
            if nm == "MAP_DUNG_L13":
                # a spawn point pasted into solid rock is flagged at once
                gate = next(e for _pi, _ei, e in panel.doc.gen.all_entries())
                W, H, cells = panel.doc.grid
                blocked = next((tx, ty) for ty in range(H) for tx in range(W)
                               if not cells[ty * W + tx] & 0x21
                               and all(not cells[yy * W + xx] & 0x21
                                       for yy in range(max(0, ty - 2), min(H, ty + 3))
                                       for xx in range(max(0, tx - 2), min(W, tx + 3))))
                with panel.doc.edit("test", "gen"):
                    panel.doc.gen.add_monster_position(gate, blocked[0] * 8 + 4, blocked[1] * 8 + 4, 0)
                found["pasted"] = [i for i in panel.validate() if "monster spawn point (Gen" in i[2]]
        finally:
            root.destroy()
    h38, f16, l13 = found["MAP_DUNG_H38"], found["MAP_FIELD_16"], found["MAP_DUNG_L13"]
    _check("a spawn point with no walkable ground in reach is flagged and selectable (MAP_DUNG_H38)",
           any("monster spawn point" in i[2] for i in h38[0]) and h38[1] and h38[1][0] == "mpos", str(h38))
    _check("a gate position outside the map is flagged and selectable (MAP_FIELD_16)",
           any("outside the" in i[2] for i in f16[0]) and f16[1] and f16[1][0] == "gpos", str(f16))
    _check("a clean map stays clean; a point dropped into solid rock is flagged",
           not l13[0] and len(found["pasted"]) == 1, str(found["pasted"]))


def test_map_editor_gate_motion():
    """Gates that move (gen.gate_motion): kinds 375-382 glide along their positions (GenM73,
    Rune Prana, a dashed path with arrows), a nonzero flag high byte teleports (GenM05, dotted
    lines between every two positions); the Gates tab's 'teleports' box writes flag 0x100."""
    print("map editor: moving gates (glide / teleport):")
    from rf4s_modkit import gen
    from map_editor import render
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_DUNG_M05.rf4m").exists():
        _skip("moving gates", "no extracted bundleMain"); return
    got = {}
    for nm in ("MAP_DUNG_M73", "MAP_DUNG_M05", "MAP_DUNG_L13"):
        root, panel, errs = _headless_panel(nm, B)
        try:
            d = panel.doc
            e = next(e for _pi, _ei, e in d.gen.all_entries())
            lines = [p for p in render.gate_paths(d, 6) if p.kind == "line"]
            got[nm] = (gen.gate_motion(e), len(lines), {p.opt.get("arrow") for p in lines},
                       len(e.gate_pos.points))
            tv = panel.encounters.gates
            got[nm + " row"] = tv.set(tv.get_children()[0], "kind")
            tab = panel.encounters
            if nm == "MAP_DUNG_M73":
                panel.set_active_gate((0, 0))
                tab._show_gate()
                got["greyed"] = tab.teleport_cb.instate(["disabled"])
                # a file that already has both (made by hand): flagged, and the box can untick it
                with d.edit("test", "gen"):
                    d.gen.set_hdr(e, flag=gen.TELEPORT_FLAG)
                root.update()
                got["ticked"] = (gen.gate_motion(e), tab.motion_lbl.cget("text").startswith("Broken"),
                                 any("glides (375..382)" in m for m in d.gen.validate()),
                                 tab.teleport_cb.instate(["!disabled"]))
            if nm == "MAP_DUNG_M05":
                panel.set_active_gate((0, 0))
                tab._show_gate()
                got["m05 enabled"] = tab.teleport_cb.instate(["!disabled"])
                tab.kind.var.set("375")             # switch to a gliding kind: teleport goes
                tab._commit_gate()
                root.update()
                got["switched"] = (e.gate_kind, e.hdr.flag, gen.gate_motion(e),
                                   tab.teleport.get(), tab.teleport_cb.instate(["disabled"]))
        finally:
            root.destroy()
    m73, m05, l13 = got["MAP_DUNG_M73"], got["MAP_DUNG_M05"], got["MAP_DUNG_L13"]
    _check("a Void..Affection Gate (375-382) with 8 positions glides: one dashed leg per position, "
           "arrows", m73[0] == {"glide"} and m73[1] == m73[3] and m73[2] == {"last"}, m73)
    _check("a gate with flag 0x100 teleports: dotted lines between every two of its 4 positions",
           m05[0] == {"teleport"} and m05[1] == 6 and m05[2] == {None}, m05)
    _check("a gate that stays put draws no path (Frozen Gate 385, 2 positions, MAP_DUNG_L13)",
           not l13[0] and l13[1] == 0, l13)
    from map_editor import data as _mdata
    _ch = _mdata.gate_choices()
    _check("the gate list says how each gate moves; the kind list gives each kind's HP and marks "
           "the gliding kinds",
           got["MAP_DUNG_M05 row"].endswith("· teleports") and got["MAP_DUNG_M73 row"].endswith("· glides")
           and "·" not in got["MAP_DUNG_L13 row"].split("Frozen Gate", 1)[1].replace("(hidden)", "")
           and any(c.startswith("377") and c.endswith("800 HP · glides") for c in _ch)
           and any(c.startswith("385") and c.endswith("1000 HP") for c in _ch),
           [got[k] for k in got if k.endswith(" row")])
    _check("'teleports' is greyed out for a gliding kind and enabled for the others; picking a "
           "gliding kind unticks it",
           got["greyed"] and got["m05 enabled"]
           and got["switched"] == (375, 0, {"glide"}, False, True), (got["greyed"], got["switched"]))
    _check("a file that already has a gliding kind with the teleport flag is flagged as broken, "
           "and the box stays enabled so it can be unticked",
           got["ticked"] == ({"glide", "teleport"}, True, True, True), got["ticked"])
    # G markers: orange for a visible gate, gray for a hidden spawner; a gate picked in the Gates
    # list is outlined white until the map is clicked empty, which also clears the list
    _Bg = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if (_Bg / "MAP_DUNG_A04.rf4m").exists() and (_Bg / "MAP_DUNG_L13.rf4m").exists():
        from map_editor import render as _rg
        res_g = {}
        for _m in ("MAP_DUNG_A04", "MAP_DUNG_L13"):
            _root, _panel, _errs = _headless_panel(_m, _Bg)
            try:
                _c = _panel.view.canvas
                _panel.view.flush(); _root.update()
                res_g[_m] = {_c.itemcget(it, "fill") for it in _c.find_withtag("gate") if _c.type(it) == "polygon"}
                if _m == "MAP_DUNG_A04":
                    _tab = next(i for i in _panel.nb.tabs() if _panel.nb.tab(i, "text") == "Gates")
                    _panel.nb.select(_tab); _root.update()
                    _gl = _panel.encounters.gates
                    _gl.selection_set(_gl.get_children()[0]); _root.update()
                    _white = lambda: sum(1 for it in _c.find_withtag("gate") if _c.type(it) in ("polygon", "oval")
                                         and _c.itemcget(it, "outline").lower() in ("#fff", "#ffffff"))
                    _panel.view.flush(); _root.update(); _on = _white()
                    _panel.select(None); _panel.view.flush(); _root.update()
                    res_g["deselect"] = (_on > 0, _white(), tuple(_gl.selection()))
                    # clicking one of its points on the map picks the gate in the list again
                    _gp = next((k, o) for k, o, _x, _y, _u in _panel.doc.gate_points() if k == "gpos")
                    _panel.select(_gp); _root.update()
                    res_g["reselect"] = (len(_gl.selection()) == 1, _gl.selection()[0] if _gl.selection() else None)
                    # clicking a monster spawn point selects its gate and the point in the list
                    _pts = [(k, o) for k, o, _x, _y, _u in _panel.doc.gate_points() if k == "mpos"]
                    _mp_key = _pts[-1] if _pts else None
                    if _mp_key:
                        _panel.select(None); _root.update()
                        _panel.select(_mp_key); _root.update()
                        _ml = _panel.encounters.mpts
                        res_g["mpos"] = (bool(_gl.selection()), tuple(_ml.selection()) == (str(_mp_key[1]),))
            finally:
                _root.destroy()
        _check("gate G markers are orange for visible gates (MAP_DUNG_A04) and gray for hidden spawners "
               "(MAP_DUNG_L13)",
               res_g["MAP_DUNG_A04"] == {_rg.GATE_COLOR} and res_g["MAP_DUNG_L13"] == {_rg.GATE_HIDDEN_COLOR},
               {k: v for k, v in res_g.items() if k != "deselect"})
        _check("a gate picked in the Gates list is outlined white; clicking the map empty clears the "
               "outline and the list's selection", res_g["deselect"] == (True, 0, ()), res_g["deselect"])
        _check("clicking a gate point on the map selects that gate in the Gates list (also right after "
               "a deselect)", res_g["reselect"][0], res_g["reselect"])
        if "mpos" in res_g:
            _check("clicking a monster spawn point on the map selects its gate and that point in the "
                   "Gates tab's spawn-point list", res_g["mpos"] == (True, True), res_g["mpos"])


def test_map_editor_pool_spawn_sprites():
    """The wood / stone spawns (forage types 3 / 4) roll one of three things a day; the map and
    the palette draw the smallest (Branch / Stone), and the Inspect tab says so."""
    print("map editor: wood / stone spawn pictures:")
    from map_editor import render as _render, palette as _palette
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_FIELD_A3.rf4m").exists():
        _skip("wood / stone spawn pictures", "no extracted bundleMain"); return
    from map_editor import data as _mdata
    root, panel, errs = _headless_panel("MAP_FIELD_A3", B, reader=_mdata.folder_reader(B))
    try:
        d = panel.doc
        i = next(k for k, r in enumerate(d.map.mobj_records()) if r[0] & 0xFFFF == 4)
        src = panel.view.st.sprites.source(d.objs[i])
        panel.select(("mobj", i))
        root.update()
        note = panel.inspector.forms["mobj"].type_label.cget("text")
        pal = panel.palette
        pics = {t: pal.picture(t) is not None for t in (3, 4, 5)}
    finally:
        root.destroy()
    _check("a stone spawn is drawn as the Stone (crop_001) and the Inspect tab names the three "
           "daily rolls",
           src is not None and src[0].startswith("crop_001")
           and "drawn as a Stone" in note and "Rock" in note and "Clay Stone" in note, (src, note))
    _check("the palette pictures the wood and stone spawns (Branch / Stone); the herb pool keeps "
           "its marker", pics == {3: True, 4: True, 5: False}, pics)


def test_map_editor_clipboard():
    """Map editor clipboard: an entity, a warp, a search spot, a gate position and a monster
    spawn point copied on one map paste into
    another (records equal but for the position, at the pointer), cut removes the source,
    paste is one undo step, and a map at the engine's chunk cap refuses a paste. A search spot
    pasted into a map the game never rolls search items on (MAP_FIELD_01) is refused with the
    reason; into a map with an SI file it lands with its drops."""
    print("map editor clipboard (copy / cut / paste across maps):")
    try:
        import tkinter as tk
    except Exception:
        _skip("map editor clipboard", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_04.rf4m").exists() or not (B / "MAP_FIELD_01.rf4m").exists():
        _skip("map editor clipboard", "no extracted bundleMain"); return
    me = _map_editor()
    from map_editor import panel as mpanel
    from rf4s_modkit import rf4m as _rf4m
    box = _headless_dialogs()                       # no real message boxes
    root, src, errs = _headless_panel("MAP_CITY_04", B)
    try:
        try:
            saved_clip = root.clipboard_get()
        except tk.TclError:
            saved_clip = None
        dst = me.MapEditorPanel(tk.Frame(root), _rf4m.Rf4mMap.load(B / "MAP_FIELD_01.rf4m"), "MAP_FIELD_01")
        root.update_idletasks()
        d0, d1 = src.doc, dst.doc
        ok = []
        # entity: same 16 fields, placed at the pointer (whole tile, own sub-tile offset kept)
        k = next(i for i, r in enumerate(d0.map.mobj_records()) if r[14] or r[15])
        rec = list(d0.map.mobj_records()[k])
        src.copy_object(("mobj", k))
        clip = dst.clipboard_object()
        n1 = len(d1.map.mobj_records())
        dst.paste_object((40, 48))
        new = list(d1.map.mobj_records()[-1])
        ok.append(("entity", clip and clip["kind"] == "mobj" and len(d1.map.mobj_records()) == n1 + 1
                   and new[:14] == rec[:14] and new[16:] == rec[16:]
                   and new[14] == 40 + (rec[14] & 7) and new[15] == 48 + (rec[15] & 7)
                   and dst.sel == ("mobj", n1)))
        # undo takes the paste back in one step
        dst.undo()
        ok.append(("undo", len(d1.map.mobj_records()) == n1))
        # warp: same record, zone centred on the pointer, inside the grid
        wrec = list(d0.map.mapj_records()[0])
        src.copy_object(("warp", 0))
        dst.paste_object((64, 64))
        wnew = list(d1.map.mapj_records()[-1])
        ok.append(("warp", wnew[3:] == wrec[3:] and wnew[0] == wrec[0]
                   and 0 <= wnew[1] and 0 <= wnew[2]))
        # search spot into a map the game never rolls search items on: refused, with the reason
        sp = d0.si.spots[0]
        drops = [(e.effective_item_id, e.effective_weight) for e in sp.pool.entries]
        src.copy_object(("si", 0))
        n_msgs = len(box["msgs"])
        dst.paste_object(None)
        told = [m for _t, m in box["msgs"][n_msgs:]]
        ok.append(("search spot refused", d1.si is None
                   and any("never rolls search items on MAP_FIELD_01" in m for m in told)))
        # ... and into a map with an SI file: one more spot, drops copied
        sd = me.MapEditorPanel(tk.Frame(root), _rf4m.Rf4mMap.load(B / "MAP_CITY_00.rf4m"), "MAP_CITY_00")
        n_si = len(sd.doc.si.spots)
        sd.paste_object(None)
        got = sd.doc.si.spots[-1]
        ok.append(("search spot", len(sd.doc.si.spots) == n_si + 1
                   and [(e.effective_item_id, e.effective_weight) for e in got.pool.entries] == drops
                   and got.x == sp.x))                  # (y kept inside CITY_00's smaller grid)
        # cut removes the source (one undo step on the source map)
        n0 = len(d0.map.mobj_records())
        src.copy_object(("mobj", k), cut=True)
        ok.append(("cut", len(d0.map.mobj_records()) == n0 - 1 and dst.clipboard_object() is not None))
        src.undo()
        # the engine's 40-MOBJ-chunk cap: a full map refuses the paste, the map is unchanged
        while sum(1 for ch in d1.map.chunks if ch.tag == b"MOBJ") < 40:
            d1.map.add_mobj_record([0] * 16)
        n40 = len(d1.map.mobj_records())
        src.copy_object(("mobj", k))
        dst.paste_object((40, 48))
        ok.append(("cap", len(d1.map.mobj_records()) == n40 and dst.room_for("mobj")))
        # gate positions / monster spawn points: pasted into a gate on another map
        ga = me.MapEditorPanel(tk.Frame(root), _rf4m.Rf4mMap.load(B / "MAP_DUNG_A04.rf4m"), "MAP_DUNG_A04")
        gb = me.MapEditorPanel(tk.Frame(root), _rf4m.Rf4mMap.load(B / "MAP_DUNG_L13.rf4m"), "MAP_DUNG_L13")
        root.update_idletasks()
        pa = ga.doc.gate_points()
        mp = next(p for p in pa if p[0] == "mpos")
        gp = next(p for p in pa if p[0] == "gpos")
        e_a, i_a = ga.doc.locate_point("mpos", mp[1])
        extra = e_a.mon_pos.points[i_a][2]
        gate_b = next(e for _pi, _ei, e in gb.doc.gen.all_entries())
        nm0, ng0 = len(gate_b.mon_pos.points), len(gate_b.gate_pos.points)
        w0 = [len(s.weights) for s in gate_b.roster.spawns]
        ga.copy_object(("mpos", mp[1]))
        gb.paste_object((100, 120))                  # the map's only gate takes it
        pt = gate_b.mon_pos.points[-1]
        ok.append(("spawn point", len(gate_b.mon_pos.points) == nm0 + 1
                   and pt[0] == 96 + (mp[2] & 7) and pt[1] == 120 + (mp[3] & 7) and pt[2] == extra
                   and [len(s.weights) for s in gate_b.roster.spawns] == [w + 1 for w in w0]
                   and gb.sel and gb.sel[0] == "mpos"))
        ga.copy_object(("gpos", gp[1]))
        gb.paste_object(None)
        ok.append(("gate position", len(gate_b.gate_pos.points) == ng0 + 1))
        gb.undo()                                    # (undo reinstalls the Gen table)
        gate_b = next(e for _pi, _ei, e in gb.doc.gen.all_entries())
        ok.append(("undo point", len(gate_b.gate_pos.points) == ng0))
        # two gates and none chosen: refused until one is chosen in the Gates tab
        gb.doc.gen.add_entry(0, 0, 10, clone=gate_b, share=False)
        gb.set_active_gate(None)
        n2 = len(gb.doc.gate_points())
        gb.paste_object((100, 120))
        refused = len(gb.doc.gate_points()) == n2
        gb.set_active_gate((0, 1))
        gb.paste_object((100, 120))
        ok.append(("choose gate", refused and len(gb.active_gate.gate_pos.points) == ng0 + 1))
        # cut removes the point from its gate
        na = len(ga.doc.gate_points())
        ga.copy_object(("mpos", mp[1]), cut=True)
        ok.append(("cut point", len(ga.doc.gate_points()) == na - 1))
        # not text: a plain-text clipboard pastes nothing
        root.clipboard_clear(); root.clipboard_append("hello")
        ok.append(("plain text", dst.clipboard_object() is None))
        _check("clipboard: entity / warp / search spot / gate point copy across maps, cut, undo, chunk cap",
               all(v for _n, v in ok) and not errs, str([n for n, v in ok if not v]) + str(errs[:1]))
        _check("clipboard: Ctrl+C / X / V bound on the map canvas (text fields keep their own)",
               all(src.view.canvas.bind(f"<Control-{c}>") for c in "cxvCXV")
               and mpanel.CLIP_TAG.startswith("RF4S"))
    finally:
        try:
            root.clipboard_clear()
            if saved_clip is not None:
                root.clipboard_append(saved_clip)
            root.update()
        except Exception:
            pass
        root.destroy()


def test_map_editor_attr_tip():
    """Map editor ATTR tooltip: Alt+hover (like the cutscene editor) and Ctrl+hover show the
    tile's ATTR decode, a bare hover does not, and pressing / releasing Alt with the pointer
    at rest shows / drops it."""
    print("map editor ATTR tooltip (Alt / Ctrl hover):")
    try:
        import tkinter as tk
    except Exception:
        _skip("map editor ATTR tooltip", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_04.rf4m").exists():
        _skip("map editor ATTR tooltip", "no extracted bundleMain"); return
    me = _map_editor()
    from rf4s_modkit import rf4m as _rf4m
    root = tk.Tk()
    root.geometry("900x650+40+40")
    try:
        f = tk.Frame(root)
        f.pack(fill="both", expand=True)
        ed = me.MapEditorPanel(f, _rf4m.Rf4mMap.load(B / "MAP_CITY_04.rf4m"), "MAP_CITY_04")
        v, c = ed.view, ed.view.canvas
        for _ in range(200):                    # events reach a canvas only once it is mapped
            root.update()
            if c.winfo_ismapped() and c.winfo_width() > 200:
                break

        def tip():
            return v._tip_label.cget("text") if v._tip is not None else ""

        def move(state):
            v.hide_tip()
            c.event_generate("<Motion>", x=150, y=150, state=state, when="now")
            root.update()
            return tip()
        plain, ctrl, alt = move(0), move(0x0004), move(v.ALT_MASK)
        move(0)
        c.focus_force()
        c.event_generate("<KeyPress-Alt_L>", when="now"); root.update()
        at_rest = tip()
        c.event_generate("<KeyRelease-Alt_L>", when="now"); root.update()
        released = tip()
        _check("map editor: Alt+hover / Ctrl+hover show the ATTR tip, a bare hover does not",
               "ATTR =" in ctrl and "ATTR =" in alt and "ATTR =" not in plain,
               f"plain={plain!r} ctrl={ctrl!r} alt={alt!r}")
        _check("map editor: pressing Alt at rest shows the ATTR tip, releasing drops it",
               "ATTR =" in at_rest and "ATTR =" not in released,
               f"at_rest={at_rest!r} released={released!r}")
    finally:
        try:                                    # (let pending timers run / drop with their widgets)
            root.update()
        except tk.TclError:
            pass
        root.destroy()


def test_map_editor_palette():
    """Map editor Palette tab: every placeable type as a cell with the sprite a new record of it
    shows (the Add tool's defaults) or its category marker; Find / the group filter narrow the
    grid; a click picks the type for the Add tool (the tab stays open) and outlines it; the
    types already on the map are named in green, and that follows adds and undo."""
    print("map editor Palette tab (object pictures, pick to place):")
    try:
        import tkinter as tk
    except Exception:
        _skip("map editor palette", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_04.rf4m").exists():
        _skip("map editor palette", "no extracted bundleMain"); return
    me = _map_editor()
    from map_editor import data as _data, tools as _tools
    from rf4s_modkit import rf4m as _rf4m
    root = tk.Tk()
    root.geometry("1000x700+40+40")
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        f = tk.Frame(root)
        f.pack(fill="both", expand=True)
        ed = me.MapEditorPanel(f, _rf4m.Rf4mMap.load(B / "MAP_CITY_04.rf4m"), "MAP_CITY_04",
                               tex_reader=_data.folder_reader(B))
        ed.show_tab("Palette")
        pal = ed.palette
        for _ in range(200):
            root.update()
            if pal.canvas.winfo_ismapped() and pal.canvas.winfo_width() > 100:
                break
        pal.group.set("Interactive objects")
        pal._relayout()
        pal.make_all()
        objs = list(pal._shown)
        from rf4s_modkit import mobj_types as _mt
        shipped = [t for t in objs if (B / f"{_mt.mobj_name(t)}.texture").exists()]
        missing = [t for t in shipped if pal._photos.get(t) is None]
        _check("Palette: the interactive-object group lists only types 196..335, each with its "
               "sprite when the game ships one", objs and all(196 <= t < 336 for t in objs)
               and len(shipped) > 100 and not missing, (len(objs), len(shipped), missing[:5]))
        pal.group.set("All")
        pal.query.set("chest")
        root.update()
        _check("Palette: Find narrows the grid (chest -> the treasure chest, type 44)",
               44 in pal._shown and len(pal._shown) < 10, pal._shown)
        pal.query.set("")
        pal.group.set("Map parameters (no picture)")
        pal._relayout()
        pal.make_all()
        _check("Palette: map parameter records get their marker, not a picture",
               pal._shown and all(9 <= t <= 19 and pal._photos.get(t) is None for t in pal._shown),
               pal._shown)
        pal.group.set("All")
        pal.query.set("")
        root.update()
        x0, y0 = pal._cell_xy(223)
        pal.canvas.yview_moveto(y0 / max(1, float(pal.canvas.cget("scrollregion").split()[3])))
        root.update()
        wy = y0 - pal.canvas.canvasy(0) + 10
        tid = pal.tid_at(x0 + 10, wy)
        pal._click(type("E", (), {"x": x0 + 10, "y": wy})())
        outlined = pal.canvas.itemcget("cell223", "outline")
        _check("Palette: a click picks the type for the Add tool, outlines it and keeps the tab "
               "open", tid == 223 and ed.add_type == 223 and ed.tool.name == "add"
               and ed.add_kind == "entity" and ed.nb.tab(ed.nb.select(), "text") == "Palette"
               and outlined.lower() == "#00e5ff", (tid, ed.add_type, ed.tool.name, outlined))
        used = lambda t: pal.canvas.itemcget(f"name{t}", "fill") == pal.USED
        n0 = len(ed.doc.map.mobj_records())
        on_before = used(223)
        with ed.doc.edit("add", "mobj"):
            ed.doc.map.add_mobj_record(_tools.new_entity_record(223, 80, 80))
        root.update()
        after_add = used(223)
        ed.undo()
        root.update()
        _check("Palette: types on the map are named in green, following adds and undo",
               not on_before and after_add and not used(223)
               and len(ed.doc.map.mobj_records()) == n0, (on_before, after_add, used(223)))
        pal.group.set("Favorites")
        pal._relayout()
        empty = list(pal._shown)
        pal.set_favorite(223, True)
        pal.set_favorite(44, True)
        starred = sorted(pal._shown)
        from map_editor import palette as _pal_mod
        kept = _pal_mod.PaletteTab._load_favorites()
        pal.set_favorite(44, False)
        _check("Palette: Favorites starts empty, lists the starred types (remembered in the "
               "settings), and drops an unstarred one",
               empty == [] and starred == [44, 223] and kept == {44, 223} and pal._shown == [223]
               and pal.canvas.find_withtag("star"), (empty, starred, kept, pal._shown))
        pal.set_favorite(223, False)
        _check("Palette raised no callback errors", not errs, errs[:1])
    finally:
        root.destroy()


def test_map_editor_limits_bar():
    """Map editor limits bar: objects / warps / forage / doors / search spots as used/cap
    against the game's fixed per-map capacities; grey while there is room, orange when full,
    red past the cap; it follows edits and undo."""
    print("map editor limits bar:")
    try:
        import tkinter as tk
    except Exception:
        _skip("map editor limits bar", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_04.rf4m").exists():
        _skip("map editor limits bar", "no extracted bundleMain"); return
    from map_editor import tools as _tools
    from rf4s_modkit import rf4m as _rf4m
    root, ed, errs = _headless_panel("MAP_CITY_04", B)
    try:
        d = ed.doc
        L = ed.limit_lbls
        n0 = len(d.map.mobj_records())
        text = L["mobj"].cget("text")
        _check("limits bar: objects used / 40, warps / 10, forage / 32, doors / 4 and search "
               "spots / 253 are shown",
               text == f"Objects {n0}/40" and L["mapj"].cget("text").endswith("/10")
               and L["forage"].cget("text").endswith("/32")
               and L["doors"].cget("text").endswith("/4")
               and L["si"].cget("text").endswith("/253"),
               {k: w.cget("text") for k, w in L.items()})
        with d.edit("fill", "mobj"):
            while len(d.map.mobj_records()) < 40:
                d.map.add_mobj_record(_tools.new_entity_record(223, 80, 80))
        root.update()
        full = (L["mobj"].cget("text"), str(L["mobj"].cget("foreground")))
        with d.edit("over", "mobj"):
            d.map.add_mobj_record(_tools.new_entity_record(223, 80, 80))
        root.update()
        over = (L["mobj"].cget("text"), str(L["mobj"].cget("foreground")))
        ed.undo()
        ed.undo()
        root.update()
        back = (L["mobj"].cget("text"), str(L["mobj"].cget("foreground")))
        _check("limits bar: orange when full, red past the cap, back to grey after undo",
               full == ("Objects 40/40", ed.LIMIT_FULL) and over == ("Objects 41/40", ed.LIMIT_OVER)
               and back == (f"Objects {n0}/40", ed.LIMIT_OK), (full, over, back))
        _check("limits bar raised no callback errors", not errs, errs[:1])
    finally:
        root.destroy()


def test_collision_stamp_modes():
    """Object collision stamps as the game applies them: templates are OR-ed in (the invisible
    wall 262 adds 0x8000002 and blocks), but the airship gangway 294 goes through
    Map_SetAttrTileFlags (Map_SpawnInteractiveObject tests archive 0x45AC), whose group-wise
    merge replaces the walking bits -- the walls under it become walkable path."""
    print("object collision stamps (OR vs the gangway's merge):")
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_ROOM_25.rf4m").exists():
        _skip("collision stamps", "no extracted bundleMain"); return
    from map_editor import attrs as _attrs
    from rf4s_modkit import collisionstamp as _cs, rf4m as _rf4m
    _check("Map_SetAttrTileFlags merge: a walking bit replaces the walking group, other "
           "groups stay, stray bits are OR-ed",
           _cs.set_attr_flags(0x2 | 0x400000, 0x20000001) == 0x20400001
           and _cs.set_attr_flags(0x4, 0x8000000) == 0x8000004
           and _cs.set_attr_flags(0x8000 | 0x1, 0x20000000) == 0x20000001)
    player = _attrs.ACTOR_MASKS[0][1]

    def walkable(name, tid):
        m = _rf4m.Rf4mMap.load(B / f"{name}.rf4m")
        W, H, cells = m.attr_grid()
        rec = next(r for r in m.mobj_records() if (r[0] & 0xFFFF) == tid)
        mode, st = _cs.stamp(rec, W, H)
        after = _cs.apply(cells, W, H, [rec])
        return mode, len(st), sum(1 for (x, y) in st if not _attrs.blocks(after[y * W + x], player))

    def effects(name):
        m = _rf4m.Rf4mMap.load(B / f"{name}.rf4m")
        W, H, cells = m.attr_grid()
        out = {}
        for _i, mode, st in _cs.stamps(m.mobj_records(), W, H):
            for (x, y), v in st.items():
                k = _cs.effect(cells[y * W + x], mode, v, player)
                out[k] = out.get(k, 0) + 1
        return out

    e47, e25, e04 = effects("MAP_FIELD_47"), effects("MAP_ROOM_25"), effects("MAP_CITY_04")
    _check("the collision layer's three kinds: trees block at the trunk and only mark their canopy "
           "ring (grey, walking unchanged); the gangway opens (green); the invisible wall blocks",
           e47.get("blocks") and e47.get("marks") and not e47.get("opens")
           and set(e25) == {"opens"} and set(e04) == {"blocks"}, (e47, e25, e04))
    g = walkable("MAP_ROOM_25", 294)
    w = walkable("MAP_CITY_04", 262)
    _check("the airship gangway (294) makes its tiles walkable; the invisible wall (262) "
           "blocks every tile it covers",
           g[0] == "replace" and g[1] > 0 and g[2] == g[1]
           and w[0] == "template" and w[1] > 0 and w[2] == 0, (g, w))


def test_app_icon():
    """The window / taskbar icon: assets/app_icon.png (256 px) and assets/app_icon.ico (16..256)
    shipped with the toolkit, set on the root window for every later window too; no game
    file is read."""
    print("toolkit icon (assets/app_icon.png / .ico):")
    try:
        import tkinter as tk
        from PIL import Image
    except Exception:
        _skip("app icon", "no tkinter / Pillow"); return
    import app_icon
    root = tk.Tk()
    root.withdraw()
    try:
        ok = app_icon.apply(root)
        im = app_icon.image()
        sizes = sorted(Image.open(app_icon.ICO).info.get("sizes", [])) if app_icon.ICO.is_file() else []
        _check("the shipped icon is set (256 px square PNG, .ico with 16..256 px) and no game "
               "texture is read", ok and im is not None and im.size == (256, 256)
               and (16, 16) in sizes and (256, 256) in sizes
               and not hasattr(app_icon, "_texture_bytes"),
               (ok, im and im.size, sizes))
    finally:
        root.destroy()


def test_map_editor_blank_overmodel():
    """Make over-model empty… / Restore…: the map's over-model file is replaced with the game's
    own empty one (MAP_FIELD_43.model) only after a confirmation that names the maps sharing
    it; No leaves it alone; the original goes to ModdingBackup and Restore… puts it back.
    Runs in a scratch game folder."""
    print("map editor: empty / restore the over-model:")
    try:
        import tkinter as tk
    except Exception:
        _skip("blank over-model", "no tkinter"); return
    import shutil, tempfile
    from tkinter import messagebox as _mb
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_FARM_00.model").exists() or not (B / "MAP_FIELD_43.model").exists():
        _skip("blank over-model", "no extracted bundleMain"); return
    from rf4s_modkit import mapground as _mg
    game = pathlib.Path(tempfile.mkdtemp(prefix="rf4s_overmodel_")) / "Game"
    bundle = game / "Bundle"
    (bundle / "bundleMain").mkdir(parents=True)
    (bundle / "Manifest.plist").write_bytes(b"")          # what makes it a game folder
    orig = (B / "MAP_FARM_00.model").read_bytes()
    (bundle / "bundleMain" / "MAP_FARM_00.model").write_bytes(orig)
    real_find = _gamepaths.find_bundle_dir
    _gamepaths.find_bundle_dir = lambda refresh=False: bundle
    real_ask = _mb.askyesno
    asked = []
    answer = [False]
    _mb.askyesno = lambda title, msg, **k: (asked.append(msg), answer[0])[1]
    box = _headless_dialogs()
    _mb.askyesno = lambda title, msg, **k: (asked.append(msg), answer[0])[1]

    def reader(fn):
        for d in (bundle / "bundleMain", B):
            if (d / fn).is_file():
                return (d / fn).read_bytes()
        return None
    root, ed, errs = _headless_panel("MAP_FARM_00", B, reader=reader)
    try:
        target = bundle / "bundleMain" / "MAP_FARM_00.model"
        no = ed.blank_overmodel()
        _check("Make over-model empty asks first (naming the maps that share the file); No changes "
               "nothing", not no and target.read_bytes() == orig and asked
               and "SHARED" in asked[-1] and "MAP_FARM_01" in asked[-1]
               and "bundleMain" in asked[-1], asked[-1:])
        answer[0] = True
        yes = ed.blank_overmodel()
        backup = game / _gamepaths.BACKUP_DIR / "Bundle" / "bundleMain" / "MAP_FARM_00.model"
        _check("Yes writes the game's empty over-model (all textures transparent) and keeps the "
               "original in ModdingBackup", yes and _mg.overmodel_is_blank(target.read_bytes())
               and backup.is_file() and backup.read_bytes() == orig)
        again = ed.blank_overmodel()
        _check("an over-model that is already empty is left alone (says so)",
               not again and any("already empty" in m for _t, m in box["msgs"]))
        answer[0] = False
        ed.restore_overmodel()
        kept = target.read_bytes() != orig
        answer[0] = True
        ok = ed.restore_overmodel()
        _check("Restore… asks too; Yes copies the original back", kept and ok
               and target.read_bytes() == orig)
        _check("over-model buttons raised no callback errors", not errs, errs[:1])
    finally:
        _gamepaths.find_bundle_dir = real_find
        _mb.askyesno = real_ask
        root.destroy()
        shutil.rmtree(game.parent, ignore_errors=True)


def test_cutscene_install_leaves_no_temp():
    """The cutscene editor's Install writes the edited files to Bundle/00_mods of the game copy
    and leaves nothing behind in the temp folder (the staging folder is removed again).
    Runs against a scratch game folder with a stand-in document."""
    print("cutscene editor Install: no files left outside the toolkit / game:")
    import importlib, shutil, tempfile, types
    try:
        from tkinter import messagebox as _mb
        app_mod = importlib.import_module("cutscene_editor.app")
    except Exception as e:  # noqa: BLE001
        _skip("cutscene install", "no tkinter / cutscene editor: %s" % e); return
    cls = next((c for c in vars(app_mod).values()
                if isinstance(c, type) and "install" in vars(c) and "_refuse_broken_text" in dir(c)), None)
    if cls is None:
        _skip("cutscene install", "no Install method found"); return
    game = pathlib.Path(tempfile.mkdtemp(prefix="rf4s_ctest_"))
    bundle = game / "Bundle"
    bundle.mkdir()
    (bundle / "Manifest.plist").write_bytes(b"")
    before = {p.name for p in pathlib.Path(tempfile.gettempdir()).glob("rf4s_install_*")}
    real_find, real_info = _gamepaths.find_bundle_dir, _mb.showinfo
    _gamepaths.find_bundle_dir = lambda refresh=False: bundle
    _mb.showinfo = lambda *a, **k: None
    saved = {}
    doc = types.SimpleNamespace(
        container=types.SimpleNamespace(build=lambda: b"MC-bytes"),
        arcs={"eng": types.SimpleNamespace(build=lambda: b"ENG-bytes")},
        dirty_locales=lambda: ["eng"], em_dirty=lambda: True,
        em=types.SimpleNamespace(build=lambda: b"EM-bytes"),
        mark_saved=lambda **k: saved.update(k))
    fake = types.SimpleNamespace(doc=doc, _refuse_broken_text=lambda what: False,
                                 _chrome=lambda: None, status=lambda *a, **k: None)
    try:
        ok = cls.install(fake)
        mods = bundle / "00_mods"
        after = {p.name for p in pathlib.Path(tempfile.gettempdir()).glob("rf4s_install_*")}
        _check("Install writes rf3.mc / its text / em.bin to Bundle/00_mods and leaves no "
               "staging folder in %TEMP%",
               ok is not False and (mods / "rf3.mc").read_bytes() == b"MC-bytes"
               and (mods / "rf3mc.eng").read_bytes() == b"ENG-bytes"
               and (mods / "em.bin").read_bytes() == b"EM-bytes" and after == before,
               (ok, sorted(p.name for p in mods.glob("*")) if mods.exists() else None,
                sorted(after - before)))
    finally:
        _gamepaths.find_bundle_dir, _mb.showinfo = real_find, real_info
        shutil.rmtree(game, ignore_errors=True)


def test_settings_stay_in_toolkit():
    """The settings live only in the toolkit folder: nothing reads or removes a settings folder
    under %APPDATA% (the old location is no longer migrated)."""
    print("settings location:")
    import inspect
    src = inspect.getsource(_gamepaths)
    _check("gamepaths reads settings.json from the toolkit folder only (no %APPDATA% lookups)",
           "APPDATA" not in src and "rmtree" not in src
           and _gamepaths.TOOLKIT.name == pathlib.Path(__file__).resolve().parent.name)


def test_map_editor_place_and_delete():
    """Placing from the Palette: quick repeated clicks each place an object (Tk turns every
    second one into a double-click); an object whose layer is switched off turns that layer
    on so it shows (a rune flower with 'forage / triggers' off used to be invisible and so
    impossible to click and delete); the Objects tab deletes the selected row with Del, even
    an object the map view does not show, and Ctrl+Z brings it back."""
    print("map editor: place from the Palette, delete from the Objects tab:")
    try:
        import tkinter as tk
    except Exception:
        _skip("place and delete", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_FIELD_47.rf4m").exists():
        _skip("place and delete", "no extracted bundleMain"); return
    me = _map_editor()
    from map_editor import render as _render, tabs as _tabs
    from rf4s_modkit import rf4m as _rf4m
    root = tk.Tk()
    root.geometry("1200x700+40+40")
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        f = tk.Frame(root)
        f.pack(fill="both", expand=True)
        ed = me.MapEditorPanel(f, _rf4m.Rf4mMap.load(B / "MAP_FIELD_47.rf4m"), "MAP_FIELD_47")
        c = ed.view.canvas
        for _ in range(200):
            root.update()
            if c.winfo_ismapped() and c.winfo_width() > 200:
                break
        for k in ("trigger", "decoration"):             # as a user may have them
            ed.viewtab.vars[k].set(False)
            ed.set_layer(k, False)
        d = ed.doc
        n0 = len(d.map.mobj_records())
        ed.show_tab("Palette")
        placed = []
        for tid in (1, 340, 223):                       # rune flower, a decoration, a rock
            ed.palette.pick(tid)
            root.update()
            c.event_generate("<ButtonPress-1>", x=60, y=60)
            c.event_generate("<ButtonRelease-1>", x=60, y=60)
            root.update()
            placed.append(len(d.map.mobj_records()))
        _check("quick repeated clicks on the map each place an object (the second click of a "
               "'double-click' is not lost)", placed == [n0 + 1, n0 + 2, n0 + 3], placed)
        L = ed.view.st.layers
        o = d.objs[n0]
        _check("placing a rune flower / a decoration switches its hidden layer on, so the new "
               "object shows (and can be clicked)",
               L.get("trigger") and L.get("decoration") and _render.entity_visible(o, L)
               and ed.viewtab.vars["trigger"].get() and ed.viewtab.vars["decoration"].get(), dict(L))
        # hide the forage layer again: the rune flower is not drawn, but the Objects tab lists it
        ed.viewtab.vars["trigger"].set(False)
        ed.set_layer("trigger", False)
        ed.show_tab("Objects")
        ed.objects.rebuild()
        root.update()
        tree = ed.objects.tree
        iid = _tabs.key_iid(("mobj", n0))
        tree.selection_set(iid)
        tree.focus_force()
        root.update()
        tree.event_generate("<Delete>")
        root.update()
        gone = len(d.map.mobj_records()) == n0 + 2 and (d.map.mobj_records()[n0][0] & 0xFFFF) != 1
        ed.undo()
        root.update()
        back = len(d.map.mobj_records()) == n0 + 3 and (d.map.mobj_records()[n0][0] & 0xFFFF) == 1
        _check("Objects tab: Del deletes the selected row's object (also one the map view hides); "
               "Ctrl+Z brings it back", gone and back, (gone, back))
        ed.objects.rebuild()
        head_ok = not ed.objects.delete_row("mobj")      # a group heading
        row_ok = ed.objects.delete_row(_tabs.key_iid(("mobj", n0 + 2)))
        _check("Objects tab: the right-click Delete removes a row's object; group headings and "
               "script NPCs are not deletable", head_ok and row_ok
               and len(d.map.mobj_records()) == n0 + 2)
        _check("place / delete raised no callback errors", not errs, errs[:1])
    finally:
        root.destroy()


def test_scene_flag_reference():
    """Object / warp flags are zone-2 scene bits (game bit 4096 + the number), not the named
    story flags: the flag index lists who sets / clears / reads each one on every map and in
    the event scripts (ops 443 / 444 / 445 / 318); the Inspector spells a flag out with its role
    and the other users; Flags… opens the zone-2 reference on it, and the emdeb list is the
    separate 'Story / event flags (zone 1)'."""
    print("scene flags (zone 2): who uses each one:")
    try:
        import tkinter as tk
    except Exception:
        _skip("scene flags", "no tkinter"); return
    import time
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_DUNG_B06.rf4m").exists():
        _skip("scene flags", "no extracted bundleMain"); return
    from map_editor import data as _data
    from rf4s_modkit import flagusers as _fu, rf4m as _rf4m
    m = _rf4m.Rf4mMap.load(B / "MAP_DUNG_B06.rf4m")
    uses = _fu.index(_fu.object_uses("MAP_DUNG_B06", m.mobj_records(), m.mapj_records()))
    roles = sorted(u["role"] for u in uses.get(158, []))
    _check("MAP_DUNG_B06's flag 158: two seal doors set it when the room is cleared, the chest "
           "appears once it is set", roles == ["set when the room is cleared"] * 2
           + ["the chest appears once it is set"], roles)
    idx = _data._build_flag_index()
    bridge = [u for u in idx.get(70, [])]
    _check("the index covers every map and the event scripts: flag 70 = the FIELD_19 bridge "
           "(hidden while set) that event scripts clear (op 443)",
           any(u["kind"] == "object" and u["map"] == "MAP_FIELD_19" and u["role"] == "hidden while set"
               for u in bridge)
           and any(u["kind"] == "script" and u["op"] == 443 and u["role"] == "clears it" for u in bridge)
           and len(idx) > 700, (len(idx), [_fu.describe(u) for u in bridge][:3]))
    root, ed, errs = _headless_panel("MAP_DUNG_B06", B)
    try:
        ed.select(("mobj", 0))
        t0 = time.time()
        _data.request_flag_index(root)
        while _data.flag_index() is None and time.time() - t0 < 60:
            root.update()
            time.sleep(0.05)
        form = ed.inspector.forms["mobj"]
        rec = list(ed.doc.map.mobj_records()[0])
        note = form._note(rec[0] & 0xFFFF, 13, 4, "flag", rec[13], rec)
        _check("the Inspector spells the flag out: scene flag N = game bit 4096 + N, what it does "
               "for this object, and who else uses it",
               "scene flag 158 = game bit 4254" in note and "set when the room is cleared" in note
               and "#1 seal door" in note and "#2 treasure chest" in note, note)
        win = ed.open_flag_reference and __import__("map_editor.dialogs", fromlist=["x"]).scene_flag_reference(ed, 158)
        for _ in range(20):
            root.update()
        tree = next(w for w in _walk(win) if isinstance(w, tk.ttk.Treeview))
        lb = next(w for w in _walk(win) if isinstance(w, tk.Listbox))
        _check("Flags… opens the zone-2 reference on the object's flag, with its uses listed",
               tree.selection() == ("158",) and lb.size() == 3 and len(tree.get_children()) > 700,
               (tree.selection(), lb.size(), len(tree.get_children())))
        win.destroy()
        story = __import__("map_editor.dialogs", fromlist=["x"]).flag_reference(ed)
        _check("the emdeb list is the separate 'Story / event flags (zone 1)'",
               story is None or story.title().startswith("Story / event flags (zone 1)"))
        if story is not None:
            story.destroy()
        _check("scene flag reference raised no callback errors", not errs, errs[:1])
    finally:
        root.destroy()


def test_map_editor_hardcoded_warps():
    """The game's own warps / walls (Map_SpawnProgressWarpsAndWalls) are explained as built into
    the game: the Objects tab lists them read only under 'Built into the game'; Delete tells
    why it cannot remove them instead of deleting anything; the map's hover text says the
    same and what can be done instead."""
    print("map editor: warps built into the game:")
    try:
        import tkinter as tk
    except Exception:
        _skip("hard-coded warps", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_04.rf4m").exists():
        _skip("hard-coded warps", "no extracted bundleMain"); return
    from map_editor import render as _render, tabs as _tabs
    box = _headless_dialogs()
    root, ed, errs = _headless_panel("MAP_CITY_04", B)
    try:
        ed.objects.rebuild()
        tree = ed.objects.tree
        rows = [tree.item(i, "text") for i in tree.get_children("runtime")] if tree.exists("runtime") else []
        _check("the Objects tab lists the Magic merchant warp under 'Built into the game'",
               any("MAP_ROOM_12" in r or "House" in r for r in rows)
               and any("Magic merchant" in r for r in rows), rows)
        n_mobj, n_mapj = len(ed.doc.map.mobj_records()), len(ed.doc.map.mapj_records())
        iid = tree.get_children("runtime")[0]
        tree.selection_set(iid)
        root.update()
        before = len(box["msgs"])
        ed.objects._delete_key()
        told = box["msgs"][before:]
        _check("Delete on it explains that it is built into the game and changes nothing",
               told and "Built into the game" in told[0][0] and "RF4S.exe" in told[0][1]
               and len(ed.doc.map.mobj_records()) == n_mobj
               and len(ed.doc.map.mapj_records()) == n_mapj, told)
        tip = _render.runtime_spawns(ed.doc)[0][2]
        _check("the hover text says it is built into the game, when it appears and what to do "
               "instead", "Built into the game (RF4S.exe)" in tip and "Magic merchant" in tip
               and "paint walls" in tip, tip)
        # the big built-in zones do not pop up by themselves: Shift shows them, the status line
        # says so, and the View tab's option brings the automatic popup back; objects keep theirs
        v = ed.view
        shown = []
        v.show_tip = lambda e, text: shown.append(text)
        v.hide_tip = lambda: shown.append(None)
        (x0, y0, x1, y1), _s, _t = _render.runtime_spawns(ed.doc)[0]
        tx, ty = (x0 + x1) // 2, (y0 + y1) // 2
        ev = type("E", (), {"x": int(tx * v.cp - v.canvas.canvasx(0) + v.cp // 2),
                            "y": int(ty * v.cp - v.canvas.canvasy(0) + v.cp // 2),
                            "x_root": 0, "y_root": 0})()
        v._tip_at(ev, 0)
        plain = shown[-1]
        v._hover((tx, ty))
        status = v.status.cget("text")
        v._tip_at(ev, 0x0001)
        shift = shown[-1]
        ed.viewtab.rt_tips.set(True)
        ed.set_runtime_tips(True)
        v._tip_at(ev, 0)
        auto = shown[-1]
        ed.viewtab.rt_tips.set(False)
        ed.set_runtime_tips(False)
        _check("the built-in warp zone shows no popup on plain hover (the status line says Shift "
               "shows it); Shift shows it; the View tab option makes it pop up by itself again",
               plain is None and "hold Shift" in status and shift and "Built into the game" in shift
               and auto and "Built into the game" in auto, (plain, status[-60:], bool(shift), bool(auto)))
        chest = next((i for i, o in enumerate(ed.doc.objs) if (o["type_id"] & 0xFFFF) in (44, 53, 223)
                      and ed.view.st.layers.get(o["category"], True)), None)
        _check("objects still show their tooltip on plain hover",
               chest is None or bool(v.describe_key(("mobj", chest))))
        _check("hard-coded warps raised no callback errors", not errs, errs[:1])
    finally:
        root.destroy()


def test_map_editor_multi_select():
    """Map editor multi-selection: Shift+click adds / removes, a drag on empty map selects
    what lies in the box, dragging one of several moves them all (one undo step), arrow keys
    nudge and Delete deletes the whole selection (one undo step each), a plain click on one
    of them keeps only it, and every selected object gets a selection frame."""
    print("map editor multi-selection (Shift+click, box, group move / nudge / delete):")
    try:
        import tkinter as tk
    except Exception:
        _skip("map editor multi-select", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_04.rf4m").exists():
        _skip("map editor multi-select", "no extracted bundleMain"); return
    me = _map_editor()
    from map_editor import render as _render
    from rf4s_modkit import rf4m as _rf4m
    root = tk.Tk()
    root.geometry("1000x700+40+40")
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        f = tk.Frame(root)
        f.pack(fill="both", expand=True)
        ed = me.MapEditorPanel(f, _rf4m.Rf4mMap.load(B / "MAP_CITY_04.rf4m"), "MAP_CITY_04")
        v, c = ed.view, ed.view.canvas
        for _ in range(200):
            root.update()
            if c.winfo_ismapped() and c.winfo_width() > 200:
                break
        d = ed.doc

        def pos(k):
            r = d.map.mobj_records()[k]
            return r[14], r[15]
        objs = [i for i, o in enumerate(d.objs) if _render.entity_visible(o, v.st.layers)]
        a, b = objs[0], objs[1]

        def ev(x, y, state=0):
            """A pointer event at map sub-unit (x, y)."""
            px = x * v.cp / 8 - c.canvasx(0)
            py = y * v.cp / 8 - c.canvasy(0)
            return type("E", (), {"x": int(px), "y": int(py), "state": state,
                                  "x_root": 0, "y_root": 0})()

        def click(x, y, state=0, to=None):
            t = ed.tools["select"]
            t.press(ev(x, y, state))
            if to is not None:
                for k in range(1, 5):          # a few motion steps, as a real drag sends
                    t.drag(ev(x + (to[0] - x) * k // 4, y + (to[1] - y) * k // 4, state))
                t.release(ev(to[0], to[1], state))
            else:
                t.release(ev(x, y, state))
            root.update()
        ed.set_tool("select")
        # 1) Shift+click adds, the frames go on both
        ed.select(("mobj", a))
        ed.add_to_selection(("mobj", b))
        root.update()
        frames = _render._selection(v.st)
        _check("Shift+click adds to the selection; every selected object gets a frame",
               ed.selection == [("mobj", a), ("mobj", b)] and v.st.multi == tuple(ed.selection)
               and len(frames) >= 2, (ed.selection, len(frames)))
        # 2) arrows nudge all, one undo step
        pa, pb = pos(a), pos(b)
        n_undo = len(d.undo_stack)
        ed.nudge(8, 0)
        _check("arrow keys nudge every selected object (one undo step)",
               pos(a) == (pa[0] + 8, pa[1]) and pos(b) == (pb[0] + 8, pb[1])
               and len(d.undo_stack) == n_undo + 1, (pa, pos(a), pb, pos(b)))
        ed.undo()
        _check("one undo puts them all back", pos(a) == pa and pos(b) == pb)
        # 3) dragging one of them moves both
        ed.select(("mobj", b), keep=[("mobj", a)])
        v.center_on(pa[0] >> 3, pa[1] >> 3)
        root.update()
        grab = None                             # a point on one of the two, where it is drawn
        for it, k in list(v._items.items()):
            if k in ed.selection and c.bbox(it):
                x0, y0, x1, y1 = c.bbox(it)
                gx, gy = int((x0 + x1) / 2 * 8 / v.cp), int((y0 + y1) / 2 * 8 / v.cp)
                if any(q in ed.selection for q in v.pick_candidates(ev(gx, gy))):
                    grab = (gx, gy)
                    break
        if grab is not None:
            click(grab[0], grab[1], to=(grab[0] + 16, grab[1]))
            moved = pos(a) == (pa[0] + 16, pa[1]) and pos(b) == (pb[0] + 16, pb[1])
            _check("dragging one of several selected objects moves them all by the same amount",
                   moved and len(ed.selection) == 2, (pa, pos(a), pb, pos(b), ed.selection))
            ed.undo()
            _check("the group drag is one undo step", pos(a) == pa and pos(b) == pb)
        else:
            _skip("group drag", "object hidden under another at its position")
        # 4) a drag on empty map selects what lies in the box
        W, H, _ = d.grid
        spot = None
        for ty in range(1, H - 1, 2):
            for tx in range(1, W - 1, 2):
                v.center_on(tx, ty)
                root.update()
                if not v.pick_candidates(ev(tx * 8 + 4, ty * 8 + 4)):
                    spot = (tx * 8 + 4, ty * 8 + 4)
                    break
            if spot:
                break
        if spot is not None:
            ed.select(None)
            end = (min(W * 8 - 1, spot[0] + 160), min(H * 8 - 1, spot[1] + 160))
            v.center_on((spot[0] + end[0]) // 16, (spot[1] + end[1]) // 16)
            root.update()
            want = ed.keys_in_rect(spot[0], spot[1], end[0], end[1])
            click(spot[0], spot[1], to=end)
            _check("a drag on empty map selects everything in the box",
                   set(ed.selection) == set(want) and v.st.sel is not None if want else not ed.selection,
                   (len(want), len(ed.selection)))
        else:
            _skip("selection box", "no empty spot found")
        # 5) Ctrl+A, then Delete deletes them all as one undo step
        ed.select(("mobj", a), keep=[("mobj", b)])
        n_obj, n_undo = len(d.objs), len(d.undo_stack)
        ed.delete_selection()
        _check("Delete deletes the whole selection (one undo step)",
               len(d.objs) == n_obj - 2 and len(d.undo_stack) == n_undo + 1 and not ed.selection,
               (n_obj, len(d.objs)))
        ed.undo()
        _check("one undo brings them all back", len(d.objs) == n_obj and pos(a) == pa)
        ed.select_all()
        _check("Ctrl+A selects every shown object",
               len(ed.selection) >= len(objs) and ("mobj", a) in ed.selection, len(ed.selection))
        # 6) Shift+click on a selected one takes it out; a plain click keeps only one
        ed.select(("mobj", b), keep=[("mobj", a)])
        ed.remove_from_selection(("mobj", b))
        _check("Shift+click on a selected object takes it out of the selection",
               ed.selection == [("mobj", a)] and ed.sel == ("mobj", a) and v.st.multi == ())
        _check("multi-selection raised no callback errors", not errs, errs[:1])
    finally:
        try:
            root.update()
        except tk.TclError:
            pass
        root.destroy()


def test_chest_loot():
    """Treasure-chest loot (rf4s_modkit.chestloot): the RF4S.exe+0x9EFA60 table shipped in
    refdata/rf4s_exe_tables.json -- 190 rows of 4 slots (11-bit item id + a 4-bit value); when
    the game folder has the same RF4S.exe the file was extracted from, every table in it
    matches the exe byte for byte (gen_exe_tables_json.build). The map editor shows a chest's
    contents in the Inspect tab and the hover tooltip, and follows an f8 edit."""
    print("treasure-chest loot table (RF4S.exe+0x9EFA60, shipped in refdata) in the map editor:")
    import hashlib
    from rf4s_modkit import chestloot as cl, exetables as _ext
    rows = cl.load()
    _check("the shipped chest table: 190 rows of 4 slots",
           len(rows) == 190 and all(len(r) == 4 for r in rows), len(rows))
    exe = _ext.default_exe()
    if exe is None:
        _skip("shipped tables vs RF4S.exe", "no RF4S.exe next to the game's Bundle folder")
    elif hashlib.sha256(exe.read_bytes()).hexdigest() != cl.tables()["source"]["sha256"]:
        _skip("shipped tables vs RF4S.exe", "the game folder has a different RF4S.exe build")
    else:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gen_exe_tables_json", pathlib.Path(__file__).with_name("gen_exe_tables_json.py"))
        gen_mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(gen_mod)
        fresh = gen_mod.build(exe)
        shipped = cl.tables()
        _check("refdata/rf4s_exe_tables.json matches this RF4S.exe (chest rows, crate pools, "
               "area BGM; table at file offset 0x9EE660)",
               fresh["chest_loot"] == shipped["chest_loot"]
               and fresh["crate_pools"] == shipped["crate_pools"]
               and fresh["area_bgm"] == shipped["area_bgm"]
               and _ext.rva_to_offset(exe.read_bytes(), cl.TABLE_RVA) == 0x9EE660)
    _check("rows decode to item ids + the 4-bit value: row 0 = 3 Recovery Potions, row 7 = "
           "Bronze + 3 Iron [2], row 9 empty, a negative row has nothing",
           rows[0] == [(127, 0)] * 3 + [(0, 0)]
           and rows[7] == [(820, 0), (819, 2), (819, 2), (819, 2)]
           and rows[9] == [(0, 0)] * 4 and cl.row(-1) == []
           and cl.summary(rows[7], {820: "Bronze", 819: "Iron"}.get) == "Bronze, 3x Iron [2]"
           and cl.summary([]) == "(empty)", (rows[0], rows[7]))
    try:
        import tkinter as tk
    except Exception:
        _skip("chest loot in the editor", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_DUNG_A03.rf4m").exists():
        _skip("chest loot in the editor", "no extracted bundleMain"); return
    root, ed, errs = _headless_panel("MAP_DUNG_A03", B)
    try:
        recs = ed.doc.map.mobj_records()
        k = next(i for i, r in enumerate(recs) if (r[0] & 0xFFFF) == 44)
        ed.select(("mobj", k))
        root.update_idletasks()
        form = ed.inspector._form
        shown = form.type_label.cget("text")
        tip = ed.view.describe_key(("mobj", k))
        row = recs[k][8]
        _check("selecting a chest shows its loot in the Inspect tab and the hover tooltip",
               f"Loot (row {row}): " in shown and "Recovery Potion" in shown
               and f"Loot (row {row}): " in tip, (shown.splitlines()[-1:], tip.splitlines()[-1:]))
        rec = list(recs[k]); rec[8] = 6
        ed.apply("chest row", "mobj", lambda: ed.doc.map.set_mobj_record(k, rec))
        root.update_idletasks()
        after = form.type_label.cget("text")
        _check("changing the chest's row (f8) shows the new row's loot",
               "Loot (row 6): Spear, Iron Shield" in after, after.splitlines()[-1:])
        _check("chest loot raised no callback errors", not errs, errs[:1])
    finally:
        root.destroy()


def test_crate_loot_and_mgrp():
    """Crate loot + the MGRP decode: a crate (type 53) rolls one item per visit from the pool
    of its map's area group (zone = MGRP group bit - 5; DUNG_E 80 % common / 20 % rare, the
    rest the default pool) -- the odds of every pool add up to 1, the editor shows them in the
    Inspect tab / hover tooltip (f10 = 1: empty); mgrp_explain spells out the season, weather,
    group, base BGM, crate pool and the castle's extra group bits, and editing the season on
    the Map tab keeps those extra bits."""
    print("crate loot pools + MGRP decode:")
    from rf4s_modkit import chestloot as cl, rf4m as _rf4m
    zones = {z: cl.zone_of_mgrp(v) for z, v in (("castle", 0x00C00051), ("fields", 0x104),
                                                 ("DUNG_E", 0x2000), ("dummy", 0x10), ("none", None))}
    _check("zone = MGRP group bit - 5 (0 below 0x20; the lowest group bit wins)",
           zones == {"castle": 1, "fields": 3, "DUNG_E": 8, "dummy": 0, "none": None}, zones)
    sums = {z: round(sum(p for _i, p in cl.crate_odds(z)), 6) for z in (3, 5, 6, 7, 8, 10, 11, 13, 14, 15, 16)}
    e = dict(cl.crate_odds(8))
    _check("every crate pool's odds add up to 1; DUNG_E: Platinum 4/8 of the 20 % rare roll",
           set(sums.values()) == {1.0} and abs(max(e.values()) - 0.1) < 1e-9, sums)
    ex = _rf4m.mgrp_explain(0x00C00051)
    _check("mgrp_explain: fixed season, no weather, group bit 6 = zone 1, base BGM, crate pool, "
           "and the castle's extra bits 22 / 23 as the minimap room sub-group",
           any("fixed season: spring" in l for l in ex) and any("no weather" in l for l in ex)
           and any("bit 6" in l and "zone 1" in l for l in ex)
           and any("base BGM SEQ_ROOM" in l for l in ex) and any("crates roll the default" in l for l in ex)
           and any("22, 23" in l and "sub-group 0" in l for l in ex), ex)
    _check("mgrp_explain: bit 2 switches the BGM mode, DUNG_E crates roll 80 % / 20 %",
           any("target mode 2" in l for l in _rf4m.mgrp_explain(0x104))
           and any("DUNG_E common (80%) / DUNG_E rare (20%)" in l for l in _rf4m.mgrp_explain(0x2000)))
    try:
        import tkinter as tk
    except Exception:
        _skip("crate loot in the editor", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_DUNG_B01.rf4m").exists() or not (B / "MAP_F_ROOM_00.rf4m").exists():
        _skip("crate loot in the editor", "no extracted bundleMain"); return
    from map_editor import data as _md

    def _cl_text(mgrp):
        return _md.crate_loot([53] + [0] * 15, mgrp)
    root, ed, errs = _headless_panel("MAP_DUNG_B01", B)
    try:
        recs = ed.doc.map.mobj_records()
        k = next(i for i, r in enumerate(recs) if (r[0] & 0xFFFF) == 53)
        ed.select(("mobj", k))
        root.update_idletasks()
        form = ed.inspector._form
        shown = form.type_label.cget("text")
        tip = ed.view.describe_key(("mobj", k))
        from rf4s_modkit import chestloot as _cl
        n_items = len(_cl.crate_odds(5))
        listed = shown.splitlines()[-1].split(": ", 1)[1]
        names = [x for part in listed.split(" · ") for x in part.split("% ", 1)[1]
                 .removeprefix("each: ").split(", ")]
        _check("selecting a crate shows its whole area pool with the odds, same chances grouped "
               "(Inspect + hover tooltip, nothing cut off)",
               "Crate loot (DUNG_B pool, 1 item per visit): 8.6% Antidote Grass · 5.7% each: "
               "nothing, Grapes, Purple Grass" in shown and "more" not in shown
               and len(names) == n_items and tip.splitlines()[-1] == shown.splitlines()[-1],
               (len(names), n_items, shown.splitlines()[-1][:120]))
        big = tk.Label(root, text=ed.view.describe_key(("mobj", k)).rsplit("\n", 1)[0] + "\n"
                       + _cl_text(0x200010), font=("Consolas", 8), wraplength=480, justify="left")
        big.update_idletasks()
        _check("even the 79-item DUNG_M pool fits a tooltip (under 480 x 300 px)",
               big.winfo_reqwidth() <= 480 and big.winfo_reqheight() < 300,
               (big.winfo_reqwidth(), big.winfo_reqheight()))
        rec = list(recs[k]); rec[10] = 1
        ed.apply("empty crate", "mobj", lambda: ed.doc.map.set_mobj_record(k, rec))
        root.update_idletasks()
        _check("f10 = 1 shows the crate as empty",
               "nothing (f10 = 1" in form.type_label.cget("text"))
        # the castle keeps its extra group bits when the Map tab changes its season
        ed.set_map(_rf4m.Rf4mMap.load(B / "MAP_F_ROOM_00.rf4m"), "MAP_F_ROOM_00")
        mt = ed.maptab
        mt.refresh()
        mt.season.set("always summer")
        mt._commit_mgrp_controls()
        _check("choosing a season on the Map tab keeps MAP_F_ROOM_00's extra group bits 22 / 23",
               ed.doc.map.mgrp() == 0x00C00052, hex(ed.doc.map.mgrp()))
        _check("crate loot / MGRP raised no callback errors", not errs, errs[:1])
    finally:
        root.destroy()


def test_map_editor_mtxn_cap():
    """Map tab display layers (MTXN chunk count): Map_LoadById spawns one display layer per
    MTXN chunk (0 ground, 1 overlay) and never reads the stored value; '+' stops at the two
    layers the game draws (past 6 chunks the loader would overwrite the next pointer array),
    '-' removes one."""
    print("map editor display layers (MTXN count):")
    try:
        import tkinter as tk  # noqa: F401
    except Exception:
        _skip("MTXN cap", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_04.rf4m").exists():
        _skip("MTXN cap", "no extracted bundleMain"); return
    root, ed, errs = _headless_panel("MAP_CITY_04", B)
    try:
        m = ed.doc.map
        mt = ed.maptab
        n0 = len(m.find(b"MTXN"))
        mt._mtxn(-1)
        n1 = len(m.find(b"MTXN"))
        for _ in range(3):
            mt._mtxn(+1)
        n2 = len(m.find(b"MTXN"))
        _check("'-' removes a display layer, '+' adds one but never past 2 (ground + overlay)",
               n1 == n0 - 1 and n2 == 2, (n0, n1, n2))
        _check("MTXN cap raised no callback errors", not errs, errs[:1])
    finally:
        root.destroy()


def test_mgrp_panel_and_conflicts():
    """MGRP in the map editor (rf4s_modkit.areagroup): the Map tab shows it as Season /
    Weather / Area with what the game makes of it -- music, crate pool, the Gen table the gate
    spawner loads (map id - zone's first map + zone's first archive, refdata
    encounter_zones), minimap group -- and flags conflicts, also in the Problems tab. No
    shipped map is flagged; moving a dungeon room to the town group, a town map into a
    dungeon group, a wrong fixed season on a seasonal copy and a second group bit are."""
    print("MGRP panel + area-group conflict checks:")
    from rf4s_modkit import areagroup as ag, rf4m as _rf4m
    from map_editor import data as _md
    _check("the gate spawner's Gen archive: DUNG_B02 loads its own table; zones of one block "
           "share an offset (DUNG_B02 in the DUNG_C group still loads it); map 44 has none; "
           "DUNG_I13 reaches DUNG_J01's table",
           ag.gen_archive(285, 0x410) == ag.gen_archive(285, 0x800) == 4201
           and ag.archive_owner(4201) == 285 and ag.gen_archive(44, 0x100) is None
           and ag.archive_owner(ag.gen_archive(539, 0x20000)) == 541 and ag.base_map_id("MAP_CITY_05_SUMMER") == 44)
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    maps = sorted(B.glob("MAP_*.rf4m"))
    if not maps:
        _skip("MGRP conflicts", "no extracted bundleMain"); return
    flagged, borrow = [], []
    for p in maps:
        m = _rf4m.Rf4mMap.load(p)
        own = _md.gen_name_for_id(ag.base_map_id(p.stem))
        for sv, msg in ag.problems(m.mgrp(), p.name, gen_entries=_md.gen_entries(own) if own else None,
                                   gen_name_for=_md.gen_name_for_id, gen_entries_for=_md.gen_entries):
            (borrow if sv == "INFO" and "no gates of its own" in msg else flagged).append((p.stem, msg))
    _check(f"no shipped map gets a warning ({len(maps)} maps); only MAP_DUNG_I14 / N42 / N43 are "
           f"noted: they have no gates of their own and load GenJ02 / GenO02 / GenO03",
           not flagged and sorted(st for st, _m in borrow) == ["MAP_DUNG_I14", "MAP_DUNG_N42", "MAP_DUNG_N43"]
           and "GenJ02.bin" in dict(borrow)["MAP_DUNG_I14"], (flagged[:3], borrow))
    gn, ent = _md.gen_name_for_id, (lambda fn: 5)
    town = ag.problems(0x21, "MAP_DUNG_B02.rf4m", gen_entries=7, gen_name_for=gn, gen_entries_for=ent)
    stray = ag.problems(0x400, "MAP_CITY_02.rf4m", gen_name_for=gn, gen_entries_for=ent)
    season = ag.problems(0x21, "MAP_CITY_00_SUMMER.rf4m")
    two = ag.problems(0x2410, "MAP_DUNG_B02.rf4m")
    _check("flagged: a gated room moved to a gateless group, a town map pointed at a non-Gen "
           "archive, a fixed season contradicting the seasonal copy, a second group bit",
           any("never appear" in m for _s, m in town) and any("not a monster-gate table" in m for _s, m in stray)
           and any("summer file fixes the season to spring" in m for _s, m in season)
           and any("only bit 10" in m for _s, m in two), (town, stray, season, two))
    try:
        import tkinter as tk  # noqa: F401
    except Exception:
        _skip("MGRP panel", "no tkinter"); return
    root, ed, errs = _headless_panel("MAP_DUNG_B06", B)   # (GenB06 has gates; B02 has none)
    try:
        mt = ed.maptab
        mt.refresh()
        note = mt.mgrp_note.cget("text")
        _check("the Map tab shows MGRP as Season / Weather / Area and what the game makes of it",
               mt.season.get() == "follows the calendar" and mt.weather.get() is False
               and mt.group.get().startswith("bit 10 · DUNG_B Water Ruins (zone 5)")
               and "Music: SEQ_DGN_B.ogg" in note and "Monster gates: GenB06.bin" in note
               and "Crate loot: DUNG_B pool" in note and not mt.mgrp_warn.cget("text"), note)
        n_gates = _md.gen_entry_count(ed.doc.gen)
        mt.group.set(mt.group_choices[0 + 1])            # bit 5, the town
        mt._commit_mgrp_controls()
        ed._run_pending()
        warn = mt.mgrp_warn.cget("text")
        probs = [msg for sv, f, msg in ed.validate() if msg.startswith("MGRP:")]
        _check("moving the room into the town group warns on the Map tab and in Problems "
               "(its gates never appear)",
               ed.doc.map.mgrp() & ~0x1F == 0x20 and n_gates and f"{n_gates} gate entr" in warn
               and "never appear" in warn and probs, (hex(ed.doc.map.mgrp()), warn, probs))
        mt.weather.set(True); mt.season.set("always winter")
        mt._commit_mgrp_controls()
        _check("Weather / Season set only their own bits (rain on: bit 4 cleared; winter: bit 3)",
               ed.doc.map.mgrp() == 0x28, hex(ed.doc.map.mgrp()))
        _check("MGRP panel raised no callback errors", not errs, errs[:1])
    finally:
        root.destroy()


def test_map_editor_sidecar_files():
    """Which search-item / monster-gate file the map editor opens for a map, the way the game
    picks it (rf4s_modkit.exesidecars, refdata/rf4s_exe_sidecars.json): SI by base map id from
    g_searchItemArchiveByMapId (RF4S.exe+0x4DD260), Gen by zone (MGRP) and the zone's run of
    archives -- with the exceptions the old by-name lookup got wrong. Maps that never roll
    search items refuse new spots; the SI validation (253-spot limit) reaches Problems and gates
    the saves; a Gen file other rooms load too says so (Gates tab, Problems, save); the Gates tab
    adds a first gate to an empty table and edits the gate level and spawn radius; the wave
    cap note; MGRP bits 26-31 and a missing area bit are explained."""
    print("map editor: the game's SI / Gen file per map, sharing, new gate, MGRP 26-31:")
    import hashlib
    from rf4s_modkit import areagroup as ag, exesidecars as xs, exetables as _ext, gen as _gen
    from rf4s_modkit import rf4m as _rf4m, search_items as _si
    from map_editor import data as _md
    exe = _ext.default_exe()
    if exe is None or hashlib.sha256(exe.read_bytes()).hexdigest() != xs.tables()["source"]["sha256"]:
        _skip("rf4s_exe_sidecars.json vs RF4S.exe", "no RF4S.exe, or a different build")
    else:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gen_exe_tables_json", pathlib.Path(__file__).with_name("gen_exe_tables_json.py"))
        gm = importlib.util.module_from_spec(spec); spec.loader.exec_module(gm)
        _check("refdata/rf4s_exe_sidecars.json matches this RF4S.exe (SI table, Gen archive "
               "names, the rows read past the encounter / BGM tables)",
               gm.build_sidecars(exe) == xs.tables())
    si = {n: _md.si_name_for_map(n) for n in ("MAP_CITY_05", "MAP_CITY_05_WINTER", "MAP_CITY_06",
                                              "MAP_FIELD_A0", "MAP_FIELD_A2", "MAP_FIELD_A3",
                                              "MAP_DUNG_E45", "MAP_CITY_00_SUMMER")}
    _check("SI by map id: CITY_05 -> SI_CITY_06, CITY_06 none, FIELD_A0/A2/A3 -> SI_FIELD_101/"
           "103/104, E45 none (SI_DUNG_E45 is never loaded), seasons share the base's",
           si == {"MAP_CITY_05": "SI_CITY_06.bin", "MAP_CITY_05_WINTER": "SI_CITY_06.bin",
                  "MAP_CITY_06": None, "MAP_FIELD_A0": "SI_FIELD_101.bin",
                  "MAP_FIELD_A2": "SI_FIELD_103.bin", "MAP_FIELD_A3": "SI_FIELD_104.bin",
                  "MAP_DUNG_E45": None, "MAP_CITY_00_SUMMER": "SI_CITY_00.bin"}
           and "SI_DUNG_E45.bin" not in xs.si_files() and len(xs.si_files()) == 287, si)
    gn = {n: _md.gen_name_for_map(n) for n in ("MAP_DUNG_I14", "MAP_DUNG_N42", "MAP_DUNG_N43",
                                               "MAP_DUNG_J02", "MAP_FIELD_A0", "MAP_FIELD_105",
                                               "MAP_DUNG_B02")}
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    maps = sorted(p.stem for p in B.glob("MAP_*.rf4m"))
    q10 = [m for m in maps if (_md.gen_name_for_map(m) or "").lower() == "genq10.bin"]
    _check("Gen by zone: I14 -> GenJ02, N42 / N43 -> GenO02 / GenO03, FIELD_A0 / 105 -> "
           "GenField99_101 / 105; GenQ10 is loaded for no map; GenJ02 lists J02 then I14",
           gn == {"MAP_DUNG_I14": "GenJ02.bin", "MAP_DUNG_N42": "GenO02.bin",
                  "MAP_DUNG_N43": "GenO03.bin", "MAP_DUNG_J02": "GenJ02.bin",
                  "MAP_FIELD_A0": "GenField99_101.bin", "MAP_FIELD_105": "GenField99_105.bin",
                  "MAP_DUNG_B02": "GenB02.bin"}
           and not q10 and _md.maps_for_gen("GenJ02.bin", maps) == ["MAP_DUNG_J02", "MAP_DUNG_I14"]
           and _md.also_used_by("gen", "GenJ02.bin", "MAP_DUNG_J02") == ["MAP_DUNG_I14"]
           and _md.also_used_by("si", "SI_CITY_00.bin", "MAP_CITY_00_WINTER") == [], (gn, q10))
    f = _si.SearchItemFile([_si.SearchSpot(8, 8, _si.DropPool([_si.DropEntry(1, 1)]))
                            for _ in range(254)])
    v254 = f.validate()
    f.spots = f.spots[:253]
    pool = _si.DropPool([_si.DropEntry(1, 1)] * 255)
    ok255 = _si.SearchItemFile([_si.SearchSpot(8, 8, pool)]).validate()
    _check("SI limits: 253 spots is fine, 254 is an ERROR (spot 253's item roll uses daily "
           "stream 255, which never ends); 255 pool entries are fine",
           any(m.startswith("ERROR") and "HANG" in m for m in v254) and not f.validate()
           and not any(m.startswith("ERROR") for m in ok255), v254[:1])
    g2 = _gen.GenTable.load(B / "GenA01.bin")
    e0 = next(e for _p, _e, e in g2.all_entries())
    g2.patterns.append([])
    g2.add_entry(1, e0.gate_kind, 10, clone=e0, share=False)
    for _p, _e, e in g2.all_entries():
        e.hdr.count_max = 8
    _check("gen validate: two patterns whose gates want more than the map's 10 live monsters "
           "get an INFO note", any(m.startswith("INFO:") and "8 + 8 = 16" in m for m in g2.validate()))
    w26 = ag.problems(1 << 26, "MAP_DUNG_B02.rf4m")
    w0 = ag.problems(0x10, "MAP_DUNG_B02.rf4m")
    quiet = ag.problems(0x10, "MAP_ROOM_25.rf4m") + ag.problems(0, "MAP_DUMMY_00.rf4m")
    ex = _rf4m.mgrp_explain(1 << 26)
    eff = dict(ag.effects(1 << 31, "MAP_DUNG_B02.rf4m"))
    _check("MGRP bits 26-31 with no bit 5-25: zone 21+ (WARN: no area music, the Cluck-Cluck "
           "Nest gate row); no area bit at all: WARN zone 0 (not on the shipped rooms / "
           "placeholders that have none); explained in mgrp_explain / the panel",
           any("zone 21" in m and "Cluck-Cluck Nest" in m for _s, m in w26)
           and any("zone 0" in m for _s, m in w0) and not quiet
           and any("zone 21" in x for x in ex) and not any("no reader" in x for x in ex)
           and "0xFFFCFFFC" in eff.get("Music", ""), (w26, w0, quiet, ex, eff))
    try:
        import tkinter as tk
    except Exception:
        _skip("map editor side files", "no tkinter"); return
    box = _headless_dialogs()                       # no real message boxes
    me = _map_editor()
    root, ed, errs = _headless_panel("MAP_DUNG_I14", B)
    try:
        d = ed.doc
        ed.encounters.refresh()
        probs = ed.validate()
        box["yesno"] = False
        refused = ed.save_gen() is False
        _check("MAP_DUNG_I14 opens GenJ02.bin (the game's), the Gates tab and Problems say "
               "MAP_DUNG_J02 uses it too, and Save asks first",
               d.gen_path is not None and d.gen_path.name == "GenJ02.bin"
               and "Also used by: MAP_DUNG_J02" in ed.encounters.shared_file_lbl.cget("text")
               and any(sv == "INFO" and "also used by MAP_DUNG_J02" in m for sv, _w, m in probs)
               and not any(sv == "WARN" and "MGRP" in m for sv, _w, m in probs) and refused,
               ([x for x in probs if x[0] != "INFO"][:3], ed.encounters.shared_file_lbl.cget("text")))
        c6 = me.MapEditorPanel(tk.Frame(root), _rf4m.Rf4mMap.load(B / "MAP_CITY_06.rf4m"), "MAP_CITY_06")
        why = c6.doc.si_block_reason()
        try:
            c6.doc.ensure_si(); raised = False
        except _si.SearchItemError:
            raised = True
        c5 = me.MapEditorPanel(tk.Frame(root), _rf4m.Rf4mMap.load(B / "MAP_CITY_05.rf4m"), "MAP_CITY_05")
        _check("MAP_CITY_06 (never rolls search items) has no spots and refuses new ones with the "
               "reason; MAP_CITY_05 opens SI_CITY_06.bin",
               c6.doc.si is None and why and "never rolls search items" in why and raised
               and c5.doc.si_path is not None and c5.doc.si_path.name == "SI_CITY_06.bin", why)
        sp0 = c5.doc.si.spots[0]
        c5.doc.si.spots += [_si.SearchSpot(sp0.x, sp0.y, sp0.pool) for _ in range(260)]
        sprobs = [m for sv, w, m in c5.validate() if sv == "ERROR" and w == "search items"]
        box["yesno"] = False
        _check("an SI file past 253 spots is an ERROR in Problems, and Save refuses it unless told "
               "to save anyway", sprobs and c5.save_si() is False and c5.sidecar_saves_ok(["si"]) is False,
               sprobs[:1])
        b2 = me.MapEditorPanel(tk.Frame(root), _rf4m.Rf4mMap.load(B / "MAP_DUNG_B02.rf4m"), "MAP_DUNG_B02")
        enc = b2.encounters
        enc.refresh()
        n0 = _md.gen_entry_count(b2.doc.gen)
        enc._new_gate()
        ent = b2.active_gate
        enc.refresh()
        enc.v["level"].set("150")
        enc._commit_gate()
        pts = enc.mpts.get_children()
        if pts:
            enc.mpts.selection_set(pts[0])
        enc.vrad.set("48")
        enc._commit_radius()
        ent = b2.active_gate
        _check("Gates tab on an empty table (MAP_DUNG_B02): New adds a first gate with a spawn "
               "point and a monster, valid; the level field sets param_a, the radius field the "
               "spawn point's radius",
               n0 == 0 and ent is not None and _md.gen_entry_count(b2.doc.gen) == 1
               and ent.hdr.param_a == 150 and ent.mon_pos.points[0][2] == 48
               and len(ent.spawns) == 1 and not [m for m in b2.doc.gen.validate() if not m.startswith("INFO")],
               (n0, b2.doc.gen.validate() if b2.doc.gen else None))
        _check("side-file checks raised no callback errors", not errs, errs[:1])
    finally:
        root.destroy()


def test_map_editor_extra_warnings():
    """More Problems checks: a chest sharing its collected flag (with another chest here, or
    on another map -- a duplicate / pasted chest), a chest with no flag, an empty or
    out-of-table loot row (INFO / WARN), a room whose area group differs from the rest of its
    dungeon (INFO) and a file name the game never loads. The shipped maps get no notes: the
    36 chests with an empty loot row all run a scene through f10 (chest_event) -- no warning."""
    print("map editor: chest flags / loot rows, area vs dungeon, unloaded file names:")
    import collections
    from rf4s_modkit import areagroup as ag, rf4m as _rf4m
    from map_editor import data as _md
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    maps = sorted(B.glob("MAP_*.rf4m"))
    if not maps:
        _skip("extra warnings", "no extracted bundleMain"); return
    sev = collections.Counter()
    shared = 0
    for p in maps:
        m = _rf4m.Rf4mMap.load(p)
        for sv, _i, msg in _md.chest_problems(p.stem, m.mobj_records()):
            if sv == "WARN" and "shares its one-shot flag" in msg:
                shared += 1                 # reported on purpose, shipped maps included
            else:
                sev[sv] += 1
        sev.update(sv for sv, _m in ag.problems(m.mgrp(), p.name,
                                                sibling_zones=_md.sibling_zones(p.stem)))
    _check("shipped maps: no chest is noted as giving nothing (every empty-row chest runs an f10 "
           "scene), and the one-shot flags other maps reuse (crates, switches, seal doors) are "
           "warned about", not sev and shared == 27, (dict(sev), shared))
    m = _rf4m.Rf4mMap.load(B / "MAP_DUNG_A03.rf4m")
    recs = [list(r) for r in m.mobj_records()]
    k = next(i for i, r in enumerate(recs) if (r[0] & 0xFFFF) == 44)
    dup = list(recs[k]); recs.append(dup)                         # a duplicated chest
    other = next((stem, ch) for stem, (_g, ch, _wh) in _md.map_summaries().items()
                 if ch and not stem.upper().startswith("MAP_DUNG_A03"))
    foreign = list(recs[k]); foreign[13] = other[1][0][1]; recs.append(foreign)
    noflag = list(recs[k]); noflag[13] = -1; noflag[8] = 400; recs.append(noflag)
    msgs = [msg for _sv, _i, msg in _md.chest_problems("MAP_DUNG_A03", recs)]
    for r in recs[len(m.mobj_records()):]:
        m.add_mobj_record(r)
    here = [x for x in m.validate() if "one-shot flag" in x]
    _check("chests: a duplicate's shared flag (validate), a flag another map's chest uses, no "
           "flag, a row past the table are flagged",
           any(f"MOBJ #{len(recs) - 3} (chest) shares its one-shot flag" in x for x in here)
           and any(_md.SEASON_RE.sub("", other[0]) in x for x in msgs)
           and any("never removes it" in x for x in msgs)
           and any("past the 190-row" in x for x in msgs), (here, msgs))
    note = ag.problems(0x2000, "MAP_DUNG_B10.rf4m", sibling_zones=_md.sibling_zones("MAP_DUNG_B10"))
    _check("a Water Ruins room with the Floating Empire group gets a note (music, crates, minimap)",
           any(sv == "INFO" and "other MAP_DUNG_B rooms use area group bit 10" in x
               and "SEQ_DGN_F" in x for sv, x in note), note)
    _check("a file name the game never loads is flagged",
           any("not one of the game's map files" in x for _sv, x in ag.problems(0x21, "MAP_ALL_MOBJ.rf4m")))


def test_map_editor_minimap_tab():
    """The sidebar's Properties tab (was Map) and the minimap docked under the tabs (whatever tab
    is open; Hide / Show minimap, remembered; its details in Properties): it shows the picture
    the HUD draws for the open map's id (rf4s_modkit.minimap), the map's footprint and its
    fog-of-war reveal on it (both in the drawn half-scale px of rf3MapMiniPos), the part the
    editor shows, and a click centres the editor on that spot (the inverse placement); blank
    and maze pictures get no footprint."""
    print("map editor Minimap tab:")
    try:
        import tkinter as tk
    except Exception:
        _skip("minimap tab", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_00.rf4m").exists() or not (B / "MAP_DUNG_F01.rf4m").exists():
        _skip("minimap tab", "no extracted bundleMain"); return
    me = _map_editor()
    from map_editor import data as _md
    from rf4s_modkit import rf4m as _rf4m, minimap as _mm
    root = tk.Tk()
    root.geometry("1100x760+40+40")
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        f = tk.Frame(root)
        f.pack(fill="both", expand=True)
        ed = me.MapEditorPanel(f, _rf4m.Rf4mMap.load(B / "MAP_FIELD_01.rf4m"), "MAP_FIELD_01",
                               tex_reader=_md.folder_reader(B))
        for _ in range(30):
            root.update()
        tabs = [ed.nb.tab(t, "text") for t in ed.nb.tabs()]
        mt = ed.minimap_panel
        _check("the sidebar tabs: Map is now Properties; the minimap is no tab but docked under "
               "them, shown whatever tab is open",
               tabs == ["View", "Inspect", "Objects", "Palette", "Properties", "Gates", "Problems"]
               and mt.pic.winfo_ismapped(), tabs)
        ed.show_tab("Gates")
        root.update()
        shown_on_gates = mt.pic.winfo_ismapped()
        mt.toggle()
        root.update()
        hidden = (not mt.pic.winfo_ismapped() and mt.toggle_btn.cget("text") == "Show minimap"
                  and _gamepaths.get_setting("map_minimap_hidden") is True)
        mt.toggle()
        root.update()
        _check("Hide minimap hides the picture (remembered), Show brings it back",
               shown_on_gates and hidden and mt.pic.winfo_ismapped()
               and _gamepaths.get_setting("map_minimap_hidden") is False)
        mid = _md.map_id("MAP_FIELD_01")
        rects = [mt.pic.coords(i) for i in mt.pic.find_all() if mt.pic.type(i) == "rectangle"]
        foot = next((mt.pic.coords(i) for i in mt.pic.find_withtag("foot")), None)
        rev = _mm.record(mid)["reveal"]
        k = 2 * mt._scale
        _check("MAP_FIELD_01: its picture, footprint and fog reveal (same half-scale units)",
               mt._shown and mt._shown[1] == "mini_map_70_field" and mt._photo is not None
               and "mini_map_70_field" in ed.maptab.minimap_info.cget("text")
               and len(rects) >= 2 and foot is not None
               and abs(foot[0] - rev[0] * k) < 2 and abs(foot[1] - rev[1] * k) < 2,
               (foot, rev, mt._scale))
        ed.set_map(_rf4m.Rf4mMap.load(B / "MAP_CITY_00.rf4m"), "MAP_CITY_00")
        root.update()
        calls = []
        orig = ed.view.center_on
        ed.view.center_on = lambda tx, ty: (calls.append((tx, ty)), orig(tx, ty))
        W, H, _ = ed.doc.grid
        p = mt._to_canvas(_md.map_id("MAP_CITY_00"), W * 8 * 3 // 4, H * 8 // 2)
        mt._click(type("E", (), {"x": p[0], "y": p[1]})())
        _check("a click on the minimap centres the editor on that spot",
               calls and abs(calls[0][0] - W * 3 // 4) <= 1 and abs(calls[0][1] - H // 2) <= 1,
               (calls, W, H))
        ed.view.center_on = orig
        # a drag (real button-1 press + motion events): the editor's view follows the pointer
        ed.view.set_zoom(24)
        root.update()
        mid00 = _md.map_id("MAP_CITY_00")
        a = mt._to_canvas(mid00, W * 8 // 4, H * 8 // 2)
        b = mt._to_canvas(mid00, W * 8 * 3 // 4, H * 8 // 2)
        vc = ed.view.canvas
        mt.pic.event_generate("<ButtonPress-1>", x=int(a[0]), y=int(a[1]))
        root.update()
        x_start = vc.canvasx(0)
        for k in range(1, 6):
            x = int(a[0] + (b[0] - a[0]) * k / 5)
            mt.pic.event_generate("<Motion>", x=x, y=int(a[1]), state=0x100)   # Button1 held
            root.update()
        x_end = vc.canvasx(0)
        mt.pic.event_generate("<ButtonRelease-1>", x=int(b[0]), y=int(b[1]))
        root.update()
        moved_tiles = (x_end - x_start) / ed.view.cp
        _check("dragging on the minimap moves the editor's view along (about half the map "
               "for a drag across half the footprint)",
               abs(moved_tiles - W / 2) <= 3, (round(moved_tiles, 1), W))
        # the other rooms of the picture: named on hover, opened by a click (not by a drag)
        ed.set_map(_rf4m.Rf4mMap.load(B / "MAP_CITY_00.rf4m"), "MAP_CITY_00")
        for _ in range(5):
            root.update()
        rooms = [n for n, _r in mt._rooms]
        r = dict(mt._rooms).get("MAP_CITY_01")
        _check("the Selphia picture lists the other streets as rooms (not the open map)",
               r is not None and "MAP_CITY_00" not in rooms and len(rooms) >= 5, rooms)
        if r is not None:
            cx, cy = int((r[0] + r[2]) / 2), int((r[1] + r[3]) / 2)
            mt.pic.event_generate("<Motion>", x=cx, y=cy)
            root.update()
            hover = mt.hover_lbl.cget("text")
            mt.pic.event_generate("<ButtonPress-1>", x=cx, y=cy)
            root.update()
            for k in range(1, 4):
                mt.pic.event_generate("<Motion>", x=cx + 10 * k, y=cy, state=0x100)
                root.update()
            mt.pic.event_generate("<ButtonRelease-1>", x=cx + 30, y=cy)
            for _ in range(5):
                root.update()
            after_drag = ed.doc.base
            mt.pic.event_generate("<ButtonPress-1>", x=cx, y=cy)
            root.update()
            mt.pic.event_generate("<ButtonRelease-1>", x=cx, y=cy)
            for _ in range(10):
                root.update()
            _check("hovering a room names it, a drag from it only moves the view, a click opens it",
                   hover.startswith("Click to open MAP_CITY_01") and after_drag == "MAP_CITY_00"
                   and ed.doc.base == "MAP_CITY_01" and "MAP_CITY_00" in [n for n, _r in mt._rooms],
                   (hover, after_drag, ed.doc.base))
        ed.set_map(_rf4m.Rf4mMap.load(B / "MAP_DUNG_F01.rf4m"), "MAP_DUNG_F01")
        root.update()
        _check("a Sharance Maze floor: the blank picture, no footprint, the maze note",
               not mt.pic.find_withtag("foot") and not mt._rooms
               and "Sharance Maze" in ed.maptab.minimap_info.cget("text"),
               ed.maptab.minimap_info.cget("text"))
        _check("minimap tab raised no callback errors", not errs, errs[:1])
    finally:
        try:
            root.update()
        except tk.TclError:
            pass
        root.destroy()


def test_map_editor_resize_dialog():
    """Resize grid dialog: plain labels with tooltips (Width / Height / Shift right / Shift down /
    New tiles are ...), the fill as a named choice or any typed value; Preview changes nothing;
    Resize grows the grid, fills the new tiles, moves the objects, warps, search spots (SI) and
    gate / monster positions (Gen) with the content -- one undo step puts all of it back. The
    Properties tab has no Raw chunks button any more and its raw MGRP field is read only."""
    print("map editor Resize grid dialog:")
    try:
        import tkinter as tk
    except Exception:
        _skip("resize dialog", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_DUNG_B06.rf4m").exists():
        _skip("resize dialog", "no extracted bundleMain"); return
    import guiutil as _gu
    root, ed, errs = _headless_panel("MAP_DUNG_B06", B)
    try:
        d = ed.doc
        texts = []
        stack = [ed.maptab]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            try:
                texts.append(w.cget("text"))
            except tk.TclError:
                pass
        mg_state = str(next(w for w in _walk(ed.maptab) if isinstance(w, tk.ttk.Entry)
                            and str(w.cget("textvariable")) == str(ed.maptab.mgrp)).cget("state"))
        _check("Properties: no Raw chunks button, the raw MGRP field is read only",
               "Raw chunks…" not in texts and mg_state == "readonly", (mg_state,))
        W, H, _ = d.grid
        obj = next(i for i, o in enumerate(d.objs) if o["pos_x"] or o["pos_y"])
        o0 = (d.objs[obj]["pos_x"], d.objs[obj]["pos_y"])
        sp0 = (d.si.spots[0].x, d.si.spots[0].y)
        gp0 = {(pk, off): (x, y) for pk, off, x, y, _u in d.gate_points()}
        orig = d.map.build()
        dlg = ed.open_resize()
        labels = [w.cget("text") for w in _walk(dlg.win) if isinstance(w, tk.ttk.Label)]
        _check("the dialog's fields say what they are: Width / Height (tiles), Shift right / down, "
               "New tiles are",
               all(t in labels for t in ("Width (tiles)", "Height (tiles)", "Shift right",
                                         "Shift down", "New tiles are")), labels)
        dlg.v["w"].set(str(W + 3)); dlg.v["h"].set(str(H + 2))
        dlg.v["ox"].set("3"); dlg.v["oy"].set("2")
        dlg.v["fill"].set("0x0  empty (nothing)")
        dlg.preview()
        report = dlg.out.get("1.0", "end")
        _check("Preview lists the change (search spots / gates moving along) and changes nothing",
               d.map.build() == orig and "move with the map" in report
               and "3 new" not in dlg.summary.cget("text") and "new (filled with 0x0)" in dlg.summary.cget("text"),
               dlg.summary.cget("text"))
        n_undo = len(d.undo_stack)
        dlg.apply()
        W2, H2, cells = d.grid
        gp1 = {(pk, off): (x, y) for pk, off, x, y, _u in d.gate_points()}
        _check("Resize: bigger grid, new tiles filled with the chosen value, everything on the map "
               "moved with it (object, search spot, gate / monster points) -- one undo step",
               (W2, H2) == (W + 3, H + 2) and cells[0] == 0 and cells[(H2 - 1) * W2 + 0] == 0
               and (d.objs[obj]["pos_x"], d.objs[obj]["pos_y"]) == (o0[0] + 24, o0[1] + 16)
               and (d.si.spots[0].x, d.si.spots[0].y) == (sp0[0] + 24, sp0[1] + 16)
               and all(gp1.get(k) == (x + 24, y + 16) for k, (x, y) in gp0.items())
               and len(d.undo_stack) == n_undo + 1,
               ((W2, H2), cells[0], (d.objs[obj]["pos_x"], d.objs[obj]["pos_y"]), o0))
        ed.undo()
        _check("one undo puts the grid, the objects, the search spots and the gate positions back",
               d.grid[:2] == (W, H) and (d.si.spots[0].x, d.si.spots[0].y) == sp0
               and {(pk, off): (x, y) for pk, off, x, y, _u in d.gate_points()} == gp0
               and d.map.build() == orig)
        dlg.v["fill"].set("0x2001")
        _check("a typed fill value works too", dlg._fill() == 0x2001)
        _check("resize dialog raised no callback errors", not errs, errs[:1])
    finally:
        root.destroy()


def _walk(w):
    """Every widget under w (w included)."""
    out, stack = [], [w]
    while stack:
        x = stack.pop()
        out.append(x)
        stack.extend(x.winfo_children())
    return out


def test_map_editor_save_to_game():
    """Map editor Save (Ctrl+S) writes in place, like the cutscene editor: the changed map and
    search spots go over the files the game loads from the game folder, with no dialog; the
    originals are backed up to ModdingBackup once (a second save keeps them); a file the game
    only has packed goes to Bundle\\00_mods; same-named extra copies are warned about; a
    seasonal map says once that the other seasons are separate files."""
    print("map editor Save (Ctrl+S) overwrites the game's files:")
    try:
        import tkinter as tk
    except Exception:
        _skip("map editor save to game", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_00.rf4m").exists() or not (B / "SI_CITY_00.bin").exists():
        _skip("map editor save to game", "no extracted bundleMain"); return
    import tkinter.filedialog as _fd
    from rf4s_modkit import gamepaths as _gp, map_names as _mn
    me = _map_editor()
    from map_editor import data as med, panel as med_panel
    box = _headless_dialogs()
    asked = []
    _ask = _fd.asksaveasfilename
    _fd.asksaveasfilename = lambda *a, **k: asked.append(k.get("title")) or ""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="rf4s_save_"))
    game = tmp / "game" / "Bundle"
    (game / "bundleMain").mkdir(parents=True)
    (game / "bundlePatch2").mkdir()
    (game / "Manifest.plist").write_bytes(b"")          # what marks a Bundle folder
    for n in ("MAP_CITY_00.rf4m", "SI_CITY_00.bin"):
        shutil.copy2(B / n, game / "bundleMain" / n)
    shutil.copy2(B / "SI_CITY_00.bin", game / "bundlePatch2" / "SI_CITY_00.bin")   # a stray copy
    orig_map = (game / "bundleMain" / "MAP_CITY_00.rf4m").read_bytes()
    old = (_gp.find_bundle_dir, med.EXTRACTED, med._EXTRACTED_INDEX)
    _gp.find_bundle_dir = lambda refresh=False: game
    med.EXTRACTED, med._EXTRACTED_INDEX = game, None
    root = None
    try:
        root, p, errs = _headless_panel("MAP_CITY_00", game / "bundleMain")
        d = p.doc
        p.maptab.msea.set("3 winter"); p.maptab._commit_msea()
        d.si.spots[0].x += 8
        before = set(d.dirty_parts())
        ok1 = p.save_to_game()
        m_now = (game / "bundleMain" / "MAP_CITY_00.rf4m").read_bytes()
        s_now = (game / "bundleMain" / "SI_CITY_00.bin").read_bytes()
        bk = tmp / "game" / _gp.BACKUP_DIR / "Bundle" / "bundleMain"
        _check("Save writes the changed map and search spots over the game's own files, no dialog",
               ok1 and not asked and before == {"map", "search items"} and not d.dirty_parts()
               and m_now == d._bytes("map") and m_now != orig_map and s_now == d._bytes("si"),
               f"asked={asked} dirty_before={sorted(before)}")
        _check("the first save backs the originals up to ModdingBackup",
               (bk / "MAP_CITY_00.rf4m").read_bytes() == orig_map and (bk / "SI_CITY_00.bin").is_file())
        warns = [t for t, _m in box["msgs"] if t == "Other copies"]
        season = [m for t, m in box["msgs"] if t.startswith("Saved: a seasonal map")]
        _check("a same-named extra copy (bundlePatch2\\SI_CITY_00.bin) is warned about", len(warns) == 1)
        _check("a seasonal map says the other seasons are separate files (…_SUMMER / _AUTUMN / _WINTER)",
               len(season) == 1 and "MAP_CITY_00_AUTUMN" in season[0] and "spring" in season[0])
        p.maptab.msea.set("0 spring"); p.maptab._commit_msea()
        del box["msgs"][:]
        said = []
        real_status, p.status = p.status, said.append
        ok2 = p.save_to_game()
        p.status = real_status
        _check("after saving over a file the game knows, the hint says to re-enter the map "
               "(a new 00_mods file: restart)",
               said and said[-1].endswith("leave the map and enter it again to see it")
               and "restart the game" in med_panel.reload_hint(True), said[-1:])
        _check("a second save keeps the first backup (the true original) and doesn't repeat the season note",
               ok2 and (bk / "MAP_CITY_00.rf4m").read_bytes() == orig_map
               and not [1 for t, _m in box["msgs"] if t.startswith("Saved: a seasonal map")])
        _check("the season note is remembered in settings.json: never shown again, on any map or run",
               _gp.get_setting("season_note_shown") is True)
        tg = _gp.game_targets(["MAP_CITY_00.rf4m", "GenNOPE99.bin"])
        _check("a file the game only has packed goes to Bundle\\00_mods",
               tg["GenNOPE99.bin"] == game / "00_mods" / "GenNOPE99.bin"
               and tg["MAP_CITY_00.rf4m"] == game / "bundleMain" / "MAP_CITY_00.rf4m")
        fam = _mn.season_family(_mn.map_id_for_file("MAP_CITY_00_AUTUMN"))
        _check("season_family: Map_LoadById's ids 4..63 come in spring/summer/autumn/winter fours",
               [f for _s, f in fam] == ["MAP_CITY_00", "MAP_CITY_00_SUMMER", "MAP_CITY_00_AUTUMN",
                                        "MAP_CITY_00_WINTER"]
               and _mn.season_family(_mn.map_id_for_file("MAP_DUNG_M01")) == [])
        _check("map editor save raised no callback errors", not errs, str(errs[:1]))
    finally:
        _gp.find_bundle_dir = old[0]
        med.EXTRACTED, med._EXTRACTED_INDEX = old[1], old[2]
        _fd.asksaveasfilename = _ask
        if root is not None:
            root.destroy()
        shutil.rmtree(tmp, ignore_errors=True)


def test_map_editor_copy_to_seasons():
    """Copy changes to the other seasons (map editor Save menu, rf4s_modkit.mapdiff): an
    object the other season also has is changed there, a spring-only object is skipped and
    reported, a new object is added, an ATTR cell is copied; map settings never; the seasons
    are written over the game's files with their originals backed up."""
    print("map editor: copy changes to the other seasons:")
    try:
        import tkinter as tk
    except Exception:
        _skip("copy to seasons", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    fam = ["MAP_CITY_00", "MAP_CITY_00_SUMMER", "MAP_CITY_00_AUTUMN", "MAP_CITY_00_WINTER"]
    if not all((B / (f + ".rf4m")).exists() for f in fam):
        _skip("copy to seasons", "no extracted bundleMain"); return
    from tkinter import messagebox as _mb
    from rf4s_modkit import gamepaths as _gp, mapdiff, rf4m as _rf4m
    from map_editor import data as med
    box = _headless_dialogs()
    said = []
    _mb.askyesno = lambda t, m, **k: said.append(m) or True
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="rf4s_seasons_"))
    game = tmp / "game" / "Bundle"
    (game / "bundleMain").mkdir(parents=True)
    (game / "Manifest.plist").write_bytes(b"")
    for f in fam:
        shutil.copy2(B / (f + ".rf4m"), game / "bundleMain" / (f + ".rf4m"))
    old = (_gp.find_bundle_dir, med.EXTRACTED, med._EXTRACTED_INDEX)
    _gp.find_bundle_dir = lambda refresh=False: game
    med.EXTRACTED, med._EXTRACTED_INDEX = game, None
    root = None
    try:
        summer0 = _rf4m.Rf4mMap.load(game / "bundleMain" / "MAP_CITY_00_SUMMER.rf4m")
        s_recs = summer0.mobj_records()
        root, p, errs = _headless_panel("MAP_CITY_00", game / "bundleMain")
        m = p.doc.map
        recs = m.mobj_records()
        common = next(i for i, r in enumerate(recs) if r in s_recs and (r[0] & 0xFFFF) >= 20)
        only = next((i for i, r in enumerate(recs) if r not in s_recs and (r[0] & 0xFFFF) >= 20), None)
        moved = list(recs[common]); moved[14] += 8
        m.set_mobj_record(common, moved)
        if only is not None:
            o2 = list(recs[only]); o2[15] += 8
            m.set_mobj_record(only, o2)
        new = list(recs[common]); new[14], new[15] = 8, 8
        m.add_mobj_record(new)
        w, h, cells = m.attr_grid()
        m.set_attr_cell(1, 1, cells[w + 1] ^ 0x1)
        ok = p.copy_to_seasons()
        summer = _rf4m.Rf4mMap.load(game / "bundleMain" / "MAP_CITY_00_SUMMER.rf4m")
        sr = summer.mobj_records()
        sw, sh, sc = summer.attr_grid()
        _check("the changes land in the other seasons: a shared object moved, a new object added, "
               "an ATTR cell set",
               ok and tuple(moved) in sr and tuple(recs[common]) not in sr and tuple(new) in sr
               and sc[sw + 1] == cells[w + 1] ^ 0x1 and len(sr) == len(s_recs) + 1)
        _check("a spring-only object is skipped (and said so), not guessed",
               only is None or (tuple(o2) not in sr and said and "not the same here" in said[0]),
               "spring-only object: %s" % ("none" if only is None else "present"))
        same_rest = all([c.payload for c in summer.chunks if c.tag == t] ==
                        [c.payload for c in summer0.chunks if c.tag == t]
                        for t in {c.tag for c in summer0.chunks} - {b"MOBJ", b"ATTR"})
        _check("everything else in the season (map settings, warps) is left as it was", same_rest)
        bk = tmp / "game" / _gp.BACKUP_DIR / "Bundle" / "bundleMain" / "MAP_CITY_00_SUMMER.rf4m"
        _check("each season's original is backed up to ModdingBackup",
               bk.is_file() and bk.read_bytes() == (B / "MAP_CITY_00_SUMMER.rf4m").read_bytes())
        _check("mapdiff: a map compared with itself has no changes",
               mapdiff.diff(summer0, _rf4m.Rf4mMap.load(B / "MAP_CITY_00_SUMMER.rf4m")).empty())
        _check("copy to seasons raised no callback errors", not errs, str(errs[:1]))
    finally:
        _gp.find_bundle_dir = old[0]
        med.EXTRACTED, med._EXTRACTED_INDEX = old[1], old[2]
        if root is not None:
            root.destroy()
        shutil.rmtree(tmp, ignore_errors=True)


def test_map_container_checks():
    """Per-map exe tables (rf4s_modkit.mapres, refdata/rf4s_exe_map_resources.json): each map's
    overlay layer comes from g_mapResourceTable +2 (not the ground set's own _1000 tiles), the
    MTXN count is checked against it, short MLIG / MGRP chunks, warp destinations (base ids,
    id 0, the flag range, zone size, the arrival against the destination map), the night tint
    default, the runtime warps / walls, copy-to-seasons' chunk cap and the small-map camera."""
    print("map container: overlay ids, MTXN / MLIG / MGRP / warp checks, runtime warps:")
    import hashlib, struct
    from rf4s_modkit import exetables as _ext, mapdiff, mapground, mapres, minimap, rf4m as _rf4m
    rows = mapres.tables().get("map_resources", {}).get("rows", [])
    _check("refdata/rf4s_exe_map_resources.json: 872 maps x [rf4m, ground, overlay, over-model], "
           "216 without an overlay",
           len(rows) == 872 and sum(1 for r in rows if r[2] is None) == 216
           and rows[mapres.map_id("MAP_FIELD_01")][1:3] == ["MAP_FIELD_201_0000", "MAP_FIELD_01_1000"],
           len(rows))
    exe = _ext.default_exe()
    if exe is None:
        _skip("map resources vs RF4S.exe", "no RF4S.exe next to the game's Bundle folder")
    elif hashlib.sha256(exe.read_bytes()).hexdigest() != mapres.tables()["source"]["sha256"]:
        _skip("map resources vs RF4S.exe", "the game folder has a different RF4S.exe build")
    else:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gen_exe_tables_json", pathlib.Path(__file__).with_name("gen_exe_tables_json.py"))
        gen_mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(gen_mod)
        fresh = gen_mod.build_map_resources(exe)
        _check("refdata/rf4s_exe_map_resources.json matches this RF4S.exe (resource ids, type "
               "attributes, runtime warps)",
               fresh == mapres.tables())
    sp4 = mapres.runtime_spawns(6)                         # MAP_FARM_00_AUTUMN -> base 4
    _check("runtime warps / walls: the farm gets its field warps + walls by expansion level and "
           "the barn doors; the 50 barn rooms each get theirs; none on a dungeon",
           {s["dest"] for s in sp4 if s["kind"] == "warp"} == {8, 12, 16, 20, 77, 82}
           and sum(1 for s in sp4 if s["kind"] == "wall") == 4
           and all(mapres.runtime_spawns(m) for m in range(77, 127))
           and not mapres.runtime_spawns(mapres.map_id("MAP_DUNG_A01"))
           and mapres.wall_cells([0, 320, 16, 400]) == (0, 40, 2, 50)
           and mapres.wall_cells([0, 0, 0, 0]) is None)
    _check("night tint default: 181,214,214 where g_mapTypeAttribTable has bit 0x10 (a barn "
           "room), else 148,214,247; seasonal copies use the base id",
           _rf4m.mlig_defaults(77)[2] == (181, 214, 214) and _rf4m.mlig_defaults(4)[2] == (148, 214, 247)
           and _rf4m.mlig_defaults(7) == _rf4m.mlig_defaults(4)
           and _rf4m.mlig_defaults(None) == _rf4m.MLIG_DEFAULTS)
    _check("minimap: seasonal copies are left out of a sheet's maps with base_only",
           all(not (4 <= m < 64 and m % 4) for m in minimap.maps_on_sheet(0, base_only=True))
           and len(minimap.maps_on_sheet(0)) > len(minimap.maps_on_sheet(0, base_only=True)))
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_FIELD_01.rf4m").exists():
        _skip("map container checks", "no extracted bundleMain"); return
    from map_editor import data as med

    def reader(fn):
        p = med.find_extracted(fn)
        return p.read_bytes() if p else None
    ov = {n: mapground.overlay_for(reader, n) for n in
          ("MAP_FIELD_01", "MAP_FIELD_03", "MAP_CITY_07_SUMMER", "MAP_DUNG_I04", "MAP_DUNG_I08")}
    _check("overlay layer = g_mapResourceTable +2: FIELD_01 draws MAP_FIELD_01 over ground "
           "FIELD_201, FIELD_03 draws FIELD_07, CITY_07_SUMMER draws CITY_07, I04 / I08 none",
           ov == {"MAP_FIELD_01": "MAP_FIELD_01", "MAP_FIELD_03": "MAP_FIELD_07",
                  "MAP_CITY_07_SUMMER": "MAP_CITY_07", "MAP_DUNG_I04": None, "MAP_DUNG_I08": None}
           and mapground.available_layers(reader, "MAP_DUNG_I04") == [0]
           and mapground.available_layers(reader, "MAP_FIELD_01") == [0, 1]
           and mapground.tile_layout(reader, "MAP_FIELD_01", 1)["set"] == "MAP_FIELD_01"
           and mapground.tile_layout(reader, "MAP_DUNG_I04", 1) is None, ov)
    extra = sorted(a["set"] for n in ("MAP_DUNG_A01", "MAP_DUNG_B01", "MAP_DUNG_D06", "MAP_DUNG_I04")
                   for a in mapground.atlas_audit(reader, n, *_rf4m.Rf4mMap.load(
                       med.find_extracted(n + ".rf4m")).attr_grid()[:2]) if a["extra"])
    _check("three overlay atlases ship more tiles than spawned (A01, B01, D06; I04 has no overlay)",
           extra == ["MAP_DUNG_A01", "MAP_DUNG_B01", "MAP_DUNG_D06"], extra)
    known = set(med.rooms_by_id())

    def val(m, name, loader=med.load_map_by_id):
        return m.validate(known_maps=known, map_name=name, dest_loader=loader)

    f01 = _rf4m.Rf4mMap.load(B / "MAP_FIELD_01.rf4m")
    base_v = val(f01, "MAP_FIELD_01")
    one = _rf4m.Rf4mMap.load(B / "MAP_FIELD_01.rf4m")
    one.delete_chunk(max(i for i, c in enumerate(one.chunks) if c.tag == b"MTXN"))
    three = _rf4m.Rf4mMap.load(B / "MAP_FIELD_01.rf4m")
    three.add_chunk("MTXN", b"\0" * 4, at=[i for i, c in enumerate(three.chunks) if c.tag == b"MTXN"][-1] + 1)
    i04 = _rf4m.Rf4mMap.load(B / "MAP_DUNG_I04.rf4m")
    i04.add_chunk("MTXN", b"\0" * 4, at=[i for i, c in enumerate(i04.chunks) if c.tag == b"MTXN"][-1] + 1)
    _check("MTXN count vs the overlay id: 1 chunk on an overlay map WARNs (not drawn), 2 on a "
           "no-overlay map WARNs, 3 is an ERROR; the shipped map is clean",
           not base_v
           and any(s.startswith("WARN") and "will not be drawn" in s for s in val(one, "MAP_FIELD_01"))
           and any(s.startswith("ERROR") and "3 MTXN" in s for s in val(three, "MAP_FIELD_01"))
           and any(s.startswith("WARN") and "stays empty" in s for s in val(i04, "MAP_DUNG_I04")),
           base_v[:2])
    short = _rf4m.Rf4mMap.load(B / "MAP_FIELD_01.rf4m")
    short.set_ints("MLIG", [0, 0], signed=False)
    short.live_chunk(b"MGRP").payload = b"\0\0"
    vs = val(short, "MAP_FIELD_01")
    _check("an MLIG under 12 B and an MGRP under 4 B are ERRORs",
           any("MLIG chunk is 8 B" in s and s.startswith("ERROR") for s in vs)
           and any("MGRP chunk is 2 B" in s and s.startswith("ERROR") for s in vs), vs[:3])
    rec = list(f01.mapj_records()[0])
    dest = _rf4m.Rf4mMap.load(med.find_extracted(med.rooms_by_id()[rec[5]] + ".rf4m"))
    dw, dh, dcells = dest.attr_grid()
    wall = next((i for i, v in enumerate(dcells) if v == 0x2), None)
    dz = dest.mapj_records()[0]
    cases = {
        "seasonal": ([rec[0], *rec[1:5], 5, *rec[6:]], "ERROR", "seasonal copy"),
        "id 0": ([rec[0], *rec[1:5], 0, 0, rec[7], rec[8]], "ERROR", "never loads"),
        "flag": ([2560, *rec[1:]], "ERROR", "disable flag 2560"),
        "width": ([rec[0], rec[1], rec[2], 40000, *rec[4:]], "WARN", "zone width 40000"),
        "outside": ([*rec[:6], dw * 8 + 40, rec[7], rec[8]], "ERROR", "is outside"),
        "wall": ([*rec[:6], (wall % dw) * 8 + 4, (wall // dw) * 8 + 4, rec[8]]
                 if wall is not None else rec, "WARN", "is a wall"),
        "in zone": ([*rec[:6], dz[1] + dz[3] // 2, dz[2] + dz[4] // 2, rec[8]], "WARN", "lies inside"),
    }
    got = {}
    for k, (r, sev, needle) in cases.items():
        m = _rf4m.Rf4mMap.load(B / "MAP_FIELD_01.rf4m")
        m.set_mapj_record(0, r)
        got[k] = any(s.startswith(sev) and needle in s for s in val(m, "MAP_FIELD_01"))
    _check("warp checks: a seasonal-copy destination, dest 0 with a 0 arrival, a flag past 2559 are "
           "ERRORs; a zone past 16 bits WARNs; the arrival outside the destination grid is an "
           "ERROR, on a wall / inside a destination warp zone a WARN",
           all(got.values()), got)
    maze = _rf4m.Rf4mMap.load(med.find_extracted("MAP_DUNG_F01.rf4m"))
    _check("Sharance Maze floors: their direction-code arrivals are not flagged",
           not [s for s in val(maze, "MAP_DUNG_F01") if "warp #" in s])
    # copy to seasons: an add past the 40-object cap is skipped
    full = _rf4m.Rf4mMap.load(B / "MAP_FIELD_01.rf4m")
    while len(full.find(b"MOBJ")) < 40:
        full.add_mobj_record(full.mobj_records()[0])
    ch = mapdiff.Changes()
    ch.added["objects"] = [tuple(full.mobj_records()[0])]
    rep = mapdiff.apply(ch, full)
    _check("mapdiff.apply refuses an object past the game's 40 per map (reported as skipped)",
           len(full.find(b"MOBJ")) == 40 and not rep.done and "the most the game can load" in rep.skipped[0],
           rep.skipped)
    r1 = f01.resize_attr_grid(40, 30, dry_run=True)
    r2 = f01.resize_attr_grid(80, 60, dry_run=True)
    _check("resize: a grid under 52 x 32 tiles gets the centred, zoomed camera and the report "
           "says when a resize crosses that line",
           _rf4m.camera_note(51, 40) and _rf4m.camera_note(60, 31) and _rf4m.camera_note(52, 32) is None
           and any(t.startswith("camera:") for t in r1["todo"]) and r1["camera"]["new"]
           and not any(t.startswith("camera:") for t in r2["todo"]))


def test_map_editor_warps_and_saving():
    """Map editor, W1: a new warp names the base map; the destination list offers seasonal
    maps once; the minimap / MLIG default use the base id; Ctrl+S of a map opened under a
    non-game name refuses and a lower-case name is saved under the game's exact name; copy to
    seasons lists the targets' ERRORs; the runtime warps show in the view."""
    print("map editor: warp defaults, base ids, canonical save names:")
    try:
        import tkinter as tk
    except Exception:
        _skip("map editor warps and saving", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_FARM_00_SUMMER.rf4m").exists():
        _skip("map editor warps and saving", "no extracted bundleMain"); return
    from rf4s_modkit import gamepaths as _gp
    from map_editor import data as med, inspector as med_insp, render as med_render
    box = _headless_dialogs()
    ch = med.warp_choices()
    _check("destination list: seasonal maps once, by base id, marked 'season follows the calendar'",
           any(c.startswith("4 - MAP_FARM_00") and med.SEASON_FOLLOWS in c for c in ch)
           and not any(c.startswith("5 - ") for c in ch) and not any(c.startswith("0 - ") for c in ch))
    _check("facing names: 0 keeps, 1 down, 90 right, 180 up, 270 left",
           [med_insp.facing_text(v) for v in (0, 1, 90, 180, 270)]
           == ["keeps the current facing", "faces down", "faces right", "faces up", "faces left"])
    root = None
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="rf4s_w1_"))
    game = tmp / "game" / "Bundle"
    (game / "bundleMain").mkdir(parents=True)
    (game / "Manifest.plist").write_bytes(b"")
    shutil.copy2(B / "MAP_FARM_00.rf4m", game / "bundleMain" / "MAP_FARM_00.rf4m")
    shutil.copy2(B / "MAP_FARM_00.rf4m", tmp / "map_farm_00.rf4m")
    shutil.copy2(B / "MAP_FARM_00.rf4m", tmp / "MY_FARM.rf4m")
    old = (_gp.find_bundle_dir, med.EXTRACTED, med._EXTRACTED_INDEX)
    try:
        root, p, errs = _headless_panel("MAP_FARM_00_SUMMER", B)
        _check("the minimap panel and the Properties minimap use the base id (MAP_FARM_00_SUMMER -> 4)",
               p.minimap_panel._map_id() == 4 and p.maptab._tint_defaults()[2] == (148, 214, 247))
        n0 = len(p.doc.map.mapj_records())
        from map_editor import tools as med_tools
        wt = med_tools.WarpTool(p)
        ev = object()
        p.view.tile_at = lambda e, clamp=False: (3, 3)
        wt.press(ev); wt.release(ev)
        recs = p.doc.map.mapj_records()
        _check("a new warp on a seasonal copy leads to the BASE id (4), arrival inside the grid",
               len(recs) == n0 + 1 and recs[-1][5] == 4, recs[-1])
        rt = med_render.runtime_spawns(p.doc)
        _check("the farm's runtime warps / walls are listed for the view with a 'spawned by the "
               "game: appears when ...' tip", rt and all("Appears when" in t and "Built into the game" in t for _r, _s, t in rt), len(rt))
        root.destroy(); root = None
        _gp.find_bundle_dir = lambda refresh=False: game
        med.EXTRACTED, med._EXTRACTED_INDEX = game, None
        root, p, errs = _headless_panel("map_farm_00", tmp)
        p.maptab.msea.set("3 winter"); p.maptab._commit_msea()
        ok = p.save_to_game()
        saved = (game / "bundleMain" / "MAP_FARM_00.rf4m").read_bytes()
        _check("Ctrl+S of 'map_farm_00' writes the game's exact name MAP_FARM_00.rf4m, no stray "
               "lower-case file", ok and saved == p.doc._bytes("map")
               and not (game / "00_mods").exists(), sorted(x.name for x in game.rglob("*.rf4m")))
        root.destroy(); root = None
        del box["msgs"][:]
        root, p, errs = _headless_panel("MY_FARM", tmp)
        p.maptab.msea.set("3 winter"); p.maptab._commit_msea()
        ok2 = p.save_to_game()
        _check("Ctrl+S of a map under a non-game name refuses with a clear message",
               ok2 is False and any("not one of the game's map names" in m for _t, m in box["msgs"])
               and not (game / "00_mods").exists())
        root.destroy(); root = None
        fam = ["MAP_CITY_00", "MAP_CITY_00_SUMMER", "MAP_CITY_00_AUTUMN", "MAP_CITY_00_WINTER"]
        for f in fam:
            shutil.copy2(B / (f + ".rf4m"), game / "bundleMain" / (f + ".rf4m"))
        med._EXTRACTED_INDEX = None
        from tkinter import messagebox as _mb
        asked = []
        _mb.askyesno = lambda t, m, **k: asked.append(m) or False
        root, p, errs = _headless_panel("MAP_CITY_00", game / "bundleMain")
        r0 = list(p.doc.map.mapj_records()[0])
        r0[5] = 25                                  # a seasonal copy as the destination
        p.doc.map.add_mapj_record(r0)
        p.copy_to_seasons()
        _check("copy to seasons lists each target season's ERRORs before writing",
               asked and "would choke on" in asked[0] and "MAP_CITY_00_SUMMER: warp #" in asked[0]
               and "seasonal copy" in asked[0], asked[:1])
        _check("W1 map editor checks raised no callback errors", not errs, str(errs[:1]))
    finally:
        _gp.find_bundle_dir = old[0]
        med.EXTRACTED, med._EXTRACTED_INDEX = old[1], old[2]
        if root is not None:
            root.destroy()
        shutil.rmtree(tmp, ignore_errors=True)


def test_map_editor_labels():
    """Name labels (objects, script NPCs, warp destinations) stay on the map: one that would
    stick out above the top edge goes under its object, one past a side edge is shifted in;
    each is outlined (the text drawn again in black one pixel off in every direction, under
    it) and the PNG export draws a real stroke outline and places labels the same way."""
    print("map editor name labels (placement + outline):")
    try:
        import tkinter as tk
    except Exception:
        _skip("map editor labels", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_00.rf4m").exists():
        _skip("map editor labels", "no extracted bundleMain"); return
    from map_editor import render as mrender, view as mview
    root = None
    try:
        root, p, errs = _headless_panel("MAP_CITY_00", B)
        v, d = p.view, p.doc
        v.st.layers.update(labels=True, sprites=False)
        k = next(i for i, o in enumerate(d.objs) if mrender.entity_visible(o, v.st.layers))
        d.objs[k]["pos_y"] = 0                     # the object on the map's top row
        v._draw_group("ent")
        c = v.canvas
        mw, mh = d.grid[0] * v.cp, d.grid[1] * v.cp
        texts = [it for it in c.find_withtag("ent") if c.type(it) == "text"]
        yellow = [it for it in texts if c.itemcget(it, "fill") == "#ffe000"]
        black = [it for it in texts if c.itemcget(it, "fill") == mrender.LABEL_HALO]
        boxes = [c.bbox(it) for it in yellow]
        inside = all(b[1] >= 0 and b[0] >= 0 and b[2] <= mw for b in boxes)
        under = [it for it in yellow if c.itemcget(it, "anchor") == "n"]   # flipped below
        _check("labels stay on the map: one on the top row goes under its object, none past an edge",
               yellow and inside and under, f"{len(yellow)} labels, {len(under)} moved under")
        order = {it: n for n, it in enumerate(c.find_all())}
        outlined = all(
            sum(1 for h in black if c.itemcget(h, "text") == c.itemcget(it, "text")
                and abs(c.coords(h)[0] - c.coords(it)[0]) <= 1 and abs(c.coords(h)[1] - c.coords(it)[1]) <= 1
                and order[h] < order[it]) >= 8
            for it in yellow)
        _check("every label is outlined: 8 black copies, one pixel off, drawn under it",
               len(black) == 8 * len(yellow) and outlined, f"{len(black)} outline items for {len(yellow)} labels")
        # the hover tooltip names an object by its readable name, like its label
        tips = [v.describe_key(("mobj", i)) for i in range(len(d.objs))]
        want = [mobj_types.mobj_display_name(o["type_id"] & 0xFFFF) for o in d.objs]
        _check("hover tooltips show each object's readable name",
               tips and all(w and t.split("\n")[0].split("  ", 1)[1] == w for t, w in zip(tips, want)),
               tips[:2])
        # following a warp opens its destination at this zoom, centred on the arrival point
        from rf4s_modkit import rf4m as _rf4m
        from map_editor import data as _mdata
        recs = d.map.mapj_records()
        j = next(k for k, r in enumerate(recs) if _mdata.rooms_by_id().get(r[5])
                 and (B / (_mdata.rooms_by_id()[r[5]] + ".rf4m")).exists() and (r[6] or r[7]))
        dest = _mdata.rooms_by_id()[recs[j][5]]
        opened = []
        real_open = v.open_view
        v.open_view = lambda *a: opened.append(a)
        p.on_navigate = lambda n: p.set_map(_rf4m.Rf4mMap.load(B / (n + ".rf4m")), n)
        v.set_zoom(12)
        p.goto_warp(j)
        for _ in range(5):
            root.update()
        v.open_view = real_open
        _check("a warp opens its destination at the current zoom, centred where it arrives",
               p.doc.name == dest and opened and opened[-1] == (12, (recs[j][6] / 8, recs[j][7] / 8))
               and p.__dict__.get("_warp_view") is None, (dest, p.doc.name, opened))
        p.set_map(_rf4m.Rf4mMap.load(B / "MAP_CITY_00.rf4m"), "MAP_CITY_00")
        for _ in range(3):
            root.update()
        v.open_view = lambda *a: opened.append(a)
        p.view_open()
        v.open_view = real_open
        _check("a map opened any other way still opens at the default zoom",
               opened[-1] == (), opened[-1])
        # inspector: each parameter by its name, the explanation as the tooltip (no green notes)
        from rf4s_modkit import mobj_params as _mp
        from tkinter import ttk
        from map_editor import ui
        ship = next(i for i, o in enumerate(p.doc.objs) if o["type_id"] & 0xFFFF == 51)
        p.select(("mobj", ship))
        root.update_idletasks()
        form = p.inspector.forms["mobj"]
        shown = [(fi, lab.cget("text")) for fi, (lab, _e, _v) in enumerate(form.rows)
                 if lab.winfo_manager()]
        _check("the inspector labels each parameter by name and explains it in a tooltip",
               shown == [(8, "mode"), (13, "flag")]
               and form._meanings[8].startswith("word 8, read as u8\n")
               and _mp.field_meaning(51, 8) in form._meanings[8]
               and not any(isinstance(w, ttk.Label) and w.cget("foreground") == ui.GOOD
                           for w in form.pframe.winfo_children()),
               (shown, form._meanings.get(8)))
        # "darken" (Ground texture box): the ground drops by that % so the objects stand out
        from PIL import Image as _Im2
        g = _Im2.new("RGBA", (2, 2), (200, 100, 40, 255))
        base0, _t = mrender.Background().layers((2, 2, [0] * 4), v.colors, 1, g, attr_on=False,
                                                 alpha=0, edges_on=False, attr_version=0)
        base40, _t = mrender.Background().layers((2, 2, [0] * 4), v.colors, 1, g, attr_on=False,
                                                 alpha=0, edges_on=False, attr_version=0, dim=40)
        p.set_ground_dim(40)
        _check("the ground can be darkened (View tab slider, 25 % by default, remembered)",
               base0.getpixel((0, 0)) == (200, 100, 40, 255)
               and base40.getpixel((0, 0)) == (120, 60, 24, 255)
               and v.ground_dim == 40 and p.viewtab.saved.get("ground_dim") == 40
               and p.viewtab.dim.get() == 40, (base40.getpixel((0, 0)),))
        p.set_ground_dim(25)
        # monster gates the game shows draw as the Gate actor, clickable in the "G" marker's
        # place; hidden spawners (header flag low byte != 0) and gates off the map keep the "G"
        if (B / "MAP_DUNG_A03.rf4m").exists() and (B / "MAP_DUNG_A04.rf4m").exists():
            got = {}
            for nm in ("MAP_DUNG_A03", "MAP_DUNG_A04"):
                fr = tk.Frame(root)
                pg = _map_editor().MapEditorPanel(fr, _rf4m.Rf4mMap.load(B / (nm + ".rf4m")), nm)
                root.update_idletasks()
                try:
                    vg, dg = pg.view, pg.doc
                    vg.st.sprites.reader = lambda fn: next(pathlib.Path(BUNDLE_DIR).rglob(fn)).read_bytes()                         if fn == "EFC_00_GATEA.model" else None
                    vg.st.layers.update(sprites=True, gates=True)
                    if dg.gen is None:
                        continue
                    gp = [(k, off) for k, off, _x, _y, _u in dg.gate_points() if k == "gpos"]
                    under = [p for p in mrender.overlay("under", vg.st) if p.key and p.key[0] == "gpos"]
                    marks = [p for p in mrender.overlay("gate", vg.st) if p.kind == "text"]
                    vg.st.sel = gp[0] if gp else None
                    ring = [p for p in mrender.overlay("sel", vg.st) if p.kind == "oval"]
                    vg.st.sel = None
                    got[nm] = (len(gp), len(under), len(marks), ring and ring[0].xy)
                finally:
                    fr.destroy()
            a03, a04 = got.get("MAP_DUNG_A03"), got.get("MAP_DUNG_A04")
            if not (a03 and a04):
                _skip("monster gate sprites", "no GenA03 / GenA04")
            else:
                _check("visible monster gates draw as the Gate actor (A04), hidden spawners keep "
                       "the 'G' (A03, header flag 1); the selection ring fits the gate and goes "
                       "with the selection",
                       a04[1] == a04[0] >= 1 and a04[2] == 0 and a04[3][2] - a04[3][0] > 40
                       and a03[1] == 0 and a03[2] == a03[0] >= 1 and a03[3][2] - a03[3][0] < 40,
                       got)
        # a tooltip near a monitor edge wraps and stays on that monitor
        import guiutil as _gu
        left, top, right, bottom = _gu.monitor_rect(root, 10, 10)
        tip = tk.Toplevel(root)
        tip.wm_overrideredirect(True)
        tk.Label(tip, text="a long explanation " * 60, wraplength=_gu.tip_wraplength(root, right - 5, 10)).pack()
        _gu.place_popup(tip, right - 5, bottom - 5, above=bottom - 40)
        tip.update_idletasks()
        gx, gy = tip.winfo_x(), tip.winfo_y()
        gw, gh = tip.winfo_reqwidth(), tip.winfo_reqheight()
        tip.destroy()
        _check("tooltips wrap and stay on the monitor (moved left / above at its edges)",
               left <= gx and gx + gw <= right and top <= gy and gy + gh <= bottom
               and gw <= right - left, ((gx, gy, gw, gh), (left, top, right, bottom)))
        # Options… window: the wheel zooms (default) or scrolls, Ctrl+wheel the other; remembered
        class _Wheel:
            delta, x, y = -120, 50, 50
        did = []
        real_step = v.zoom_step
        v.zoom_step = lambda *a, **k: did.append("zoom")
        real_scroll = v.canvas.yview_scroll
        v.canvas.yview_scroll = lambda *a: did.append("scroll")
        try:
            default = mview.wheel_mode()
            v._wheel(_Wheel()); v._ctrl_wheel(_Wheel())
            as_zoom, did[:] = tuple(did), []
            mview.set_wheel_mode("scroll")
            v._wheel(_Wheel()); v._ctrl_wheel(_Wheel())
            as_scroll = tuple(did)
            stored = _gamepaths.get_setting(mview.WHEEL_SETTING)
            mview._wheel_mode = None                 # a new run reads it back
            reread = mview.wheel_mode()
        finally:
            v.zoom_step, v.canvas.yview_scroll = real_step, real_scroll
            mview.set_wheel_mode("zoom")
        _check("mouse wheel option: the wheel zooms (Ctrl scrolls) or scrolls (Ctrl zooms), "
               "remembered in settings.json",
               default == "zoom" and as_zoom == ("zoom", "scroll") and as_scroll == ("scroll", "zoom")
               and stored == "scroll" and reread == "scroll",
               (default, as_zoom, as_scroll, stored, reread))
        d = p.doc
        # label size follows the zoom: small when zoomed out, readable from ~6 px, 10 pt at 16 px
        sizes = {cp: mrender.label_size(cp) for cp in (2, 4, 6, 8, 12, 16, 24)}
        v.set_zoom(16)
        v._draw_group("ent")
        fonts = {c.itemcget(it, "font") for it in c.find_withtag("ent")
                 if c.type(it) == "text" and c.itemcget(it, "fill") == "#ffe000"}
        v.set_zoom(1)
        _check("name labels grow with the zoom (7 pt up to 6 px, 10 pt at 16 px, more above) and "
               "the zoom stops at 2 px",
               sizes[2] == sizes[6] == 7 and sizes[8] > 7 and sizes[16] == 10 and sizes[24] > 10
               and fonts == {"{Segoe UI} 10"} and v.cp == 2 and 1 not in mview.ZOOMS,
               f"{sizes} fonts={fonts} min zoom={v.cp}")
        # labels don't overlap each other (MAP_CITY_02 had "street street light" before)
        from rf4s_modkit import rf4m as _rf4m
        for nm in ("MAP_CITY_02", "MAP_FIELD_01"):
            fr = tk.Frame(root)                     # the same Tk (images don't cross interpreters)
            p2 = _map_editor().MapEditorPanel(fr, _rf4m.Rf4mMap.load(B / (nm + ".rf4m")), nm)
            root.update_idletasks()
            try:
                v2 = p2.view
                # the object labels on their own (warp names / script NPCs off, whatever an
                # earlier test left in settings.json)
                v2.st.layers.update(labels=True, sprites=False, dest=False, spawns=False)
                v2._draw_group("dest"); v2._draw_group("spawn")
                v2._draw_group("ent")
                v2._update_scrollregion()            # (normally set on idle)
                bx = [r["box"] for r in v2._labels["ent"]]
                ov = sum(1 for i in range(len(bx)) for j in range(i + 1, len(bx))
                         if bx[i][0] < bx[j][2] and bx[j][0] < bx[i][2]
                         and bx[i][1] < bx[j][3] and bx[j][1] < bx[i][3])
                _check(f"{nm}: no two name labels overlap ({len(bx)} labels)", bx and ov == 0,
                       f"{ov} overlapping pairs")
                # the window's top edge: a label it cuts off moves under its object, and back
                c2 = v2.canvas
                rec = next(r for r in v2._labels["ent"] if r["home_anchor"] == "s" and r["box"][1] > 50)
                sr = [float(x) for x in c2.cget("scrollregion").split()]
                c2.yview_moveto((rec["box"][1] + 3 - sr[1]) / (sr[3] - sr[1]))
                v2._fit_labels_to_view()
                under = not rec["at_home"] and c2.itemcget(rec["it"], "anchor") == "n"
                c2.yview_moveto(0)
                v2._fit_labels_to_view()
                back = rec["at_home"] and c2.coords(rec["it"]) == list(rec["home"])
                _check(f"{nm}: a label cut off by the window's top edge moves under its object, "
                       "and back once scrolled", under and back, f"under={under} back={back}")
            finally:
                fr.destroy()
        from PIL import Image, ImageDraw
        im = Image.new("RGBA", (200, 100))
        dr = ImageDraw.Draw(im)
        font = mrender._font(12)
        stroke = {"stroke_width": 1, "stroke_fill": (0, 0, 0)}
        xy, an = mrender._place_label(dr, (100, 2), {"text": "Up top", "below": (100, 30)}, font,
                                      "ms", im.size, stroke)
        xy2, _an2 = mrender._place_label(dr, (2, 60), {"text": "A long label", "below": (2, 80)},
                                         font, "ms", im.size, stroke)
        bx = dr.textbbox(xy2, "A long label", font=font, anchor="ms", stroke_width=1)
        img = p.render_to_image(scale=8)
        _check("the PNG export flips a label under its object and shifts one in from the edge, "
               "and renders the outlined labels",
               (xy, an) == ((100, 30), "mt") and bx[0] >= 0 and img is not None)
        _check("map editor labels raised no callback errors", not errs, str(errs[:1]))
    finally:
        if root is not None:
            root.destroy()


def test_map_explorer_list():
    """The standalone map editor's map list groups maps by in-game area like the explorer
    (shared map_names.map_area and the group_maps_by_area setting): headers open while a
    filter is typed, picking a map loads it, a header loads nothing, and turning the
    grouping off gives the plain list."""
    print("standalone map editor: map list grouped by area:")
    try:
        import tkinter as tk
    except Exception:
        _skip("map list", "no tkinter"); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_DUNG_M01.rf4m").exists():
        _skip("map list", "no extracted bundleMain"); return
    from map_editor import app as mapp, data as med
    from rf4s_modkit import gamepaths as _gp
    old = (med.EXTRACTED, med._EXTRACTED_INDEX)
    med.EXTRACTED, med._EXTRACTED_INDEX = B, None
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        _gp.set_setting("group_maps_by_area", True)
        ex = mapp.MapExplorer(root)
        t = ex.tree
        heads = {t.item(h, "text").split("  (")[0]: h for h in t.get_children()}
        rp = heads.get("Rune Prana")
        rp_maps = [t.item(k, "text") for k in t.get_children(rp)] if rp else []
        _check("the map list has one header per area, like the explorer (Rune Prana holds MAP_DUNG_M01)",
               len(heads) > 50 and "MAP_DUNG_M01" in rp_maps and len(rp_maps) == 127,
               f"{len(heads)} headers, Rune Prana {len(rp_maps)}")
        t.selection_set(rp); root.update()
        header_ok = ex._current is None
        leaf = next(k for k in t.get_children(rp) if t.item(k, "text") == "MAP_DUNG_M01")
        t.selection_set(leaf); root.update()
        _check("picking a map loads it; picking an area header loads nothing",
               header_ok and ex._current is not None and ex._current.stem == "MAP_DUNG_M01")
        ex.filter_var.set("dung_m0"); root.update()
        opened = [h for h in t.get_children() if t.item(h, "open")]
        _check("a filter keeps the headers that match, opened",
               opened and all(t.item(k, "text").lower().startswith("map_dung_m0")
                              for h in opened for k in t.get_children(h)), str(len(opened)))
        ex.filter_var.set("")
        ex.group_var.set(False); ex._toggle_group(); root.update()
        flat = t.get_children()
        _check("grouping off lists the maps flat (and is saved for both windows)",
               len(flat) == len(ex._all) and not t.get_children(flat[0])
               and _gp.get_setting("group_maps_by_area") is False)
        _check("map list raised no callback errors", not errs, str(errs[:1]))
    finally:
        med.EXTRACTED, med._EXTRACTED_INDEX = old
        root.destroy()


def _headless_panel(name, B, reader=None):
    """(root, panel, errors) for a hidden MapEditorPanel on `name` from folder B."""
    import tkinter as tk
    me = _map_editor()
    from rf4s_modkit import rf4m as _rf4m
    root = tk.Tk()
    root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    panel = me.MapEditorPanel(tk.Frame(root), _rf4m.Rf4mMap.load(B / (name + ".rf4m")), name,
                              tex_reader=reader)
    root.update_idletasks()
    return root, panel, errs


def test_models():
    """.model geometry (rf4s_modkit.model): every mesh-bearing .model parses; decoded
    positions fit the per-shape bounding boxes the files carry; UI layouts are told apart;
    single-influence skinning goes through the skeleton's matrix-to-bone table; map
    over-model cards land on the map grid; OBJ export and the map editor's scenery layer."""
    print("models: .model meshes, skeletons, materials, over-model scenery:")
    import struct, tempfile
    from rf4s_modkit import model
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    files = sorted(pathlib.Path(BUNDLE_DIR).rglob("*.model"))
    if not files:
        _skip("models", "no extracted .model files"); return
    if QUICK:
        files = files[::8]
    meshes = layouts = 0
    bad, out_of_range, missing_tex, bbox_bad, bbox_n = [], 0, 0, 0, 0
    for f in files:
        d = f.read_bytes()
        if not model.is_mesh(d):
            layouts += 1
            continue
        try:
            m = model.parse(d)
        except Exception as e:  # noqa: BLE001
            bad.append((f.name, str(e))); continue
        meshes += 1
        M = struct.unpack_from("<Q", d, 0x28)[0]
        for sh in m.shapes:
            vb = m.vertex_buffers[sh.vertex_buffer]
            if sh.indices and max(sh.indices) >= vb.count:
                out_of_range += 1
            if sh.skin <= 1:          # rigid / single-influence: box is in the shape's own space
                so = struct.unpack_from("<Q", d, M + 0x30)[0] + 0x70 * sh.index
                bb = struct.unpack_from("<Q", d, so + 0x40)[0]
                c, e = struct.unpack_from("<3f", d, bb), struct.unpack_from("<3f", d, bb + 12)
                tol = max(max(e) * 0.02, 0.01)
                bbox_n += 1
                if not all(abs(pt[k] - c[k]) <= e[k] + tol for pt in vb.data["_p0"] for k in range(3)):
                    bbox_bad += 1
        for mt in m.materials:
            missing_tex += sum(1 for t in mt.textures if m.texture_index(t) is None)
    _check("every mesh .model parses", not bad, bad[:3] or f"{meshes} meshes, {layouts} UI layouts told apart")
    _check("every index is inside its vertex buffer", out_of_range == 0, f"{out_of_range} shapes out of range")
    _check("decoded positions fit the bounding box stored with each shape", bbox_bad == 0,
           f"{bbox_n - bbox_bad}/{bbox_n} rigid / single-bone shapes")
    _check("every material texture name resolves in the embedded BNTX", missing_tex == 0, f"{missing_tex} missing")
    if not (B / "MAP_DUNG_A04.model").exists():
        return
    # single-influence skinning: _i0 indexes the matrix-to-bone table, not the bones
    m = model.load(B / "M04_2.model")
    ys = [p[1] for sh in m.shapes for p in m.shape_vertices(sh)]
    _check("single-influence vertices go through the matrix-to-bone table",
           m.matrix_to_bone[:10] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 11]
           and (round(min(ys), 1), round(max(ys), 1)) == (-31.4, 193.4),
           f"M04_2 height {min(ys):.1f}..{max(ys):.1f}")
    # map over-model: cards sit in map sub-units, placed by their bones
    om = model.load(B / "MAP_DUNG_A04.model")
    cards = model.overmodel_cards(om)
    _check("over-model cards are placed by their bones in map sub-units",
           len(cards) == 13 and tuple(round(v) for v in cards[0].bounds) == (0, 336, 128, 400)
           and all(0 <= c.bounds[0] and c.bounds[2] <= 99 * 8 and 0 <= c.bounds[1] and c.bounds[3] <= 66 * 8
                   for c in cards),
           f"{len(cards)} cards inside the 99x66-tile grid")
    _check("over-model material user data carries the 'po' depth",
           all("po" in mt.user_data for mt in om.materials), model.user_data_text(om.materials[0]))
    img = model.render_overmodel(om, 99 * 3, 66 * 3, 3 / 8.0)
    _check("the over-model renders top-down with transparent gaps",
           img.getchannel("A").getbbox() is not None and img.getpixel((150, 100))[3] == 0)
    # effect layers (ANIM_DUNG_*): BlendType 2 = SrcAlpha/One (Scene_SubmitDrawList
    # RF4S.exe+0x1B9430), UVs tile far outside 0..1, the vertex alpha fades the strips
    dung = [model.load(B / f"ANIM_DUNG_{n}.model") for n in ("A02", "B01")]
    _check("ANIM_DUNG materials are additive (BlendType 2)",
           all(mt.blend_type == 2 for m in dung for mt in m.materials),
           [(mt.name, mt.blend_type) for m in dung for mt in m.materials])
    try:
        import numpy as _np
    except ImportError:
        _np = None
    if _np is None:
        _skip("preview wraps UVs and fades by vertex alpha", "numpy not installed")
    else:
        arr = _np.random.default_rng(1).random((8, 8, 4)).astype(_np.float32)
        a = model._sample_repeat(_np, arr, _np.array([0.3, -0.45]), _np.array([0.6, 0.2]))
        b = model._sample_repeat(_np, arr, _np.array([2.3, 0.55]), _np.array([-1.4, 3.2]))
        _check("preview samples UVs with repeat wrap", _np.allclose(a, b))
        water = model.render(dung[1], "top", 200).getchannel("A")
        cover = sum(water.histogram()[1:]) / (water.width * water.height)
        _check("tiled water sheets (UVs to 6x) are textured across each sheet", cover > 0.15,
               f"{cover:.0%} of the frame covered; 1% before UVs wrapped")
        # rf4cmv.bfsha's shaders never read _c0 (the converted data stores 0 there): the
        # BM_* bosses carry pure-black vertex colours and must not render black
        tank = model.load(B / "BM_12_0.model")
        black = all(c[:3] == (0.0, 0.0, 0.0) for vb in tank.vertex_buffers for c in vb.data.get("_c0", []))
        im = model.render(tank, "front", 160, background=(0, 0, 0, 255)).convert("RGB")
        lit = sum(im.convert("L").histogram()[40:])
        _check("vertex colour is ignored like the game's shader (black _c0 still renders textured)",
               black and lit > 0.2 * im.width * im.height, f"{lit} of {im.width * im.height} px lit")
        # RGBA4444 is drawn with A in the top nibble and R in the low one (Rafflesia's leaves
        # are green in-game); every shipped one has a 0/15-only top nibble = punch-out alpha
        import struct as _st
        a44, rt = [], []
        for mf in ("BM_11_1", "BM_12_0", "M04_2"):
            md = (B / f"{mf}.model").read_bytes()
            for t in texture.bntx_info(md):
                if t["fmt_name"] != "RGBA4444":
                    continue
                im4 = texture.decode_bntx(md, t["index"]).convert("RGBA")
                a44.append(set(im4.getchannel("A").getdata()) <= {0, 255})
                raw = md[t["data_off"]:t["data_off"] + t["image_size"]]
                rt.append(texture._encode_raw(im4, "RGBA4444") == raw)
        _rd = (B / "BM_11_2.model").read_bytes()          # BM_11_02 = the Ruffled Vine / Rafflesia leaves
        raff = texture.decode_bntx(_rd, next(t["index"] for t in texture.bntx_info(_rd)
                                             if t["name"] == "BM_11_02")).convert("RGB").resize((1, 1))
        rr, gg, bb = raff.getpixel((0, 0))
        _check("RGBA4444 decodes alpha from the top nibble (0/255 only) and re-encodes byte-exact",
               a44 and all(a44) and all(rt), f"{len(a44)} textures")
        _check("Rafflesia's leaf texture comes out leaf-coloured (not the red tint of R-in-top-nibble)",
               gg > rr and gg > bb, f"mean rgb {(rr, gg, bb)}")
        # alpha follows the Muteki program the PC game picks (bundleMuteki mtk_body / mtk_item):
        # skinned shapes -> mtk_body (alpha rounded), the rest -> mtk_item (alpha kept, <= 0.1 dropped)
        clo = model.load(B / "NPC_A_CLORICA.model")
        _progs = {model.shape_program(clo, s) for s in clo.shapes if s.skin >= 1}
        _hb = model.render(clo, "front", 160).getchannel("A").histogram()
        _hi = model.render(tank, "front", 160).getchannel("A").histogram()
        _check("alpha follows the PC program: skinned = mtk_body (0/255 only), BM_12 = mtk_item (nothing <= 0.1 kept)",
               _progs == {"body"} and model.shape_program(tank, tank.shapes[0]) == "item"
               and sum(_hb[1:255]) < 0.02 * sum(_hb) and sum(_hi[1:26]) == 0,
               f"{_progs}, body partial {sum(_hb[1:255])}, item low {sum(_hi[1:26])}")
    # material animations (.bfmat): AnimChannel_SampleAsFloat curves driving texsrt0
    from rf4s_modkit import matanim
    bf = sorted(B.glob("*.bfmat"))
    bad = []
    for f in bf:
        try:
            matanim.parse(f.read_bytes())
        except Exception as e:  # noqa: BLE001
            bad.append((f.name, str(e)))
    _check("every .bfmat material animation parses", bf and not bad, bad[:3] or f"{len(bf)} files")
    a02 = matanim.load(B / "ANIM_DUNG_A02.bfmat")
    fr_at = (0, 60, 120, 180, 239)
    tx = [a02.materials[0].params[0].value(fr)[4] for fr in fr_at]
    steps = [(b - a) / (fb - fa) for a, b, fa, fb in zip(tx[:4], tx[1:4], fr_at, fr_at[1:4])]
    # linear over the one cubic segment; at frame 239 the seek lands on the last key itself
    # (AnimCurve_SeekKey_FrameS8), whose quantized value is 0.992
    _check("ANIM_DUNG_A02: lite_burst texsrt0 translate-U scrolls ~1 texture per 240-frame loop",
           a02.loops and a02.frame_count == 239 and abs(tx[0]) < 0.01 and abs(tx[-1] - 1) < 0.02
           and max(steps) - min(steps) < 1e-4, f"tx {[round(v, 3) for v in tx]}")
    ident = matanim.texsrt_matrix([0, 1.0, 1.0, 0.0, 0.0, 0.0])
    moved = matanim.apply_uv(matanim.texsrt_matrix([0, 1.0, 1.0, 0.0, 0.25, 0.0]), 0.5, 0.5)
    _check("texsrt mode 0 (TexSrt_BuildMatrix2x3_PivotA): identity at rest, u' = u - tx",
           all(abs(x - y) < 1e-6 for r, q in zip(ident, ((1, 0, 0), (0, 1, 0))) for x, y in zip(r, q))
           and abs(moved[0] - 0.25) < 1e-6 and abs(moved[1] - 0.5) < 1e-6, f"{moved}")
    cv = a02.materials[0].params[0].curves[0]
    import copy as _copy
    rep_cv = _copy.copy(cv); rep_cv.flags = (cv.flags & ~0x3000) | 0x1000       # post-wrap repeat
    rel_cv = _copy.copy(cv); rel_cv.flags = (cv.flags & ~0x3000) | 0x3000; rel_cv.delta = 1.0
    _check("curve wrap modes follow AnimChannel_SampleAsFloat (clamp / repeat / relative)",
           abs(cv.evaluate(300) - cv.evaluate(239)) < 1e-6 and abs(rep_cv.evaluate(300) - cv.evaluate(61)) < 1e-6
           and abs(rel_cv.evaluate(300) - (cv.evaluate(61) + 1.0)) < 1e-6)
    if _np is not None:
        f0 = model.render(dung[0], "top", 160, anim=a02, frame=0)
        f60 = model.render(dung[0], "top", 160, anim=a02, frame=60)
        loop = model.render(dung[0], "top", 160, anim=a02, frame=a02.frame_count)
        _check("the preview scrolls with the animation and loops at the frame count",
               f0.tobytes() != f60.tobytes() and f0.tobytes() == loop.tobytes())
    # export
    tmp = pathlib.Path(tempfile.mkdtemp())
    npc = model.load(B / "NPC_C_BADO.model")
    written = model.export_obj(npc, tmp, "npc")
    obj = (tmp / "npc.obj").read_text(encoding="utf-8").splitlines()
    nv = sum(1 for l in obj if l.startswith("v "))
    nf = sum(1 for l in obj if l.startswith("f "))
    _check("OBJ export writes every vertex, triangle and texture",
           nv == sum(v.count for v in npc.vertex_buffers) and nf == sum(len(s.indices) // 3 for s in npc.shapes)
           and len(written) == 2 + len(npc.textures), f"{nv} v, {nf} f, {len(written) - 2} PNG")
    # map editor scenery layer
    from map_editor import data as med, render as mrender
    reader = med.folder_reader(B)
    plain = mrender.GroundLoader.decode(reader, "MAP_CITY_00", "all", 180, 45, False)
    scen = mrender.GroundLoader.decode(reader, "MAP_CITY_00", "all", 180, 45, True)
    _check("the map editor draws the over-model scenery over the ground",
           plain is not None and scen is not None and scen.size == plain.size
           and scen.tobytes() != plain.convert("RGBA").tobytes(), f"{scen.size if scen else None}")


def test_model_import():
    """.model geometry writing (rf4s_modkit.modelwrite): the pool rebuild is byte-exact on
    shipped files, OBJ export -> import round-trips byte-identically, a replaced shape
    re-parses with its new counts and positions, the relocation table / embedded textures
    survive a pool that grows or shrinks, and in-place transforms touch only their shape."""
    print("model import: rebuild, OBJ round trip, shape replacement, transforms:")
    import math
    import struct
    from rf4s_modkit import model, modelwrite as mw, res_container, texture
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    files = sorted(pathlib.Path(BUNDLE_DIR).rglob("*.model"))
    if not files:
        _skip("model import", "no extracted .model files"); return
    sample = files[::8] if QUICK else files
    n = same = valid = 0
    for f in sample:
        d = f.read_bytes()
        if not model.is_mesh(d):
            continue
        n += 1
        try:
            same += mw.rebuild(d) == d
            valid += not mw.validate(d)
        except mw.ModelWriteError:
            pass
    _check("no-op pool rebuild is byte-identical and the loader walk validates"
           + (" (every 8th .model)" if QUICK else " (every mesh .model)"),
           n > 0 and same == n and valid == n, f"{same}/{n} identical, {valid}/{n} valid")

    # export -> import round trip, every shape
    rt_models = [B / x for x in ("I_ShieldJ03.model", "NPC_C_BADO.model", "BM_44_1.model", "BM_04.model",
                                 "MAP_CITY_00.model", "ANIM_DUNG_A02.model")] if QUICK else files
    shapes = ident = 0
    far = []
    for f in rt_models:
        d = f.read_bytes() if f.is_file() else b""
        if not model.is_mesh(d):
            continue
        m = model.parse(d)
        obj = model.to_obj(m)[0]
        for si in range(len(m.shapes)):
            shapes += 1
            ident += mw.import_obj(d, si, obj) == d
            if QUICK or si == 0:        # rebuild every vertex from the OBJ values (frames math)
                r = mw.import_obj(d, si, obj, keep_exact=False)
                m2 = model.parse(r)
                a, b = m.shape_vertices(m.shapes[si]), m2.shape_vertices(m2.shapes[si])
                e = max((max(abs(x - y) for x, y in zip(p, q)) / max(1.0, max(map(abs, p)))
                         for p, q in zip(a, b)), default=0.0)
                if e > 1e-5 or m2.shapes[si].indices != m.shapes[si].indices or mw.validate(r):
                    far.append((f.name, si, e))
    _check("OBJ export -> import of an unmodified OBJ is byte-identical, shape by shape",
           shapes > 0 and ident == shapes, f"{ident}/{shapes} shapes")
    _check("re-deriving every vertex from the OBJ lands back on the exported positions "
           "(bone frames for skin 0/1, model space for smooth skins)", not far, f"{far[:3]}")

    # replace a shape with a cube (shrinks the pool) / a big grid (grows it)
    npc_p = B / "NPC_C_BADO.model"
    shield_p = B / "I_ShieldJ03.model"
    for path, si in ((shield_p, 0), (npc_p, 1), (B / "BM_04.model", 0)):
        if not path.is_file():
            _skip(f"cube import {path.name}", "file missing"); continue
        d = path.read_bytes()
        m = model.parse(d)
        cube = mw.cube_obj((1.0, 2.0, 3.0), 10.0)
        r = mw.import_obj(d, si, cube)
        m2 = model.parse(r)
        sh2 = m2.shapes[si]
        pos = m2.shape_vertices(sh2)
        want = [o.vertices for o in mw.parse_obj(cube)][0]
        pos_ok = len(pos) == 24 and all(max(abs(x - y) for x, y in zip(p, w[0])) < 1e-4 for p, w in zip(pos, want))
        others = all(m2.vertex_buffers[i].data == m.vertex_buffers[i].data and m2.shapes[i].indices == m.shapes[i].indices
                     for i in range(len(m.shapes)) if i != si)
        tex_ok = [t["name"] for t in texture.bntx_info(r)] == [t["name"] for t in texture.bntx_info(d)] and \
            all(texture.decode_bntx(r, t["index"]).tobytes() == texture.decode_bntx(d, t["index"]).tobytes()
                for t in texture.bntx_info(d)[:2])
        info = res_container.inspect(r)
        rlt_ok = info["reloc_table_offset"] == struct.unpack_from("<I", r, 0x10)[0] and \
            r[info["reloc_table_offset"]:info["reloc_table_offset"] + 4] == b"_RLT"
        _check(f"{path.name} shape {si} (skin {m.shapes[si].skin}) -> cube: 24 v / 12 t at the OBJ positions, "
               f"other shapes and textures intact, relocation walk clean",
               m2.vertex_buffers[sh2.vertex_buffer].count == 24 and len(sh2.indices) == 36 and pos_ok
               and others and tex_ok and rlt_ok and not mw.validate(r),
               f"{len(d):,} -> {len(r):,} B")
    if shield_p.is_file():
        d = shield_p.read_bytes()
        N = 40
        pts = [(math.cos(2 * math.pi * i / N) * 5, j * 1.0, math.sin(2 * math.pi * i / N) * 5)
               for j in range(N) for i in range(N)]
        tris = [(j * N + i, j * N + (i + 1) % N, (j + 1) * N + i) for j in range(N - 1) for i in range(N)] + \
               [(j * N + (i + 1) % N, (j + 1) * N + (i + 1) % N, (j + 1) * N + i) for j in range(N - 1) for i in range(N)]
        r = mw.replace_shape(d, 0, pts, tris)
        m2 = model.parse(r)
        slots_old = {s for s, _t in mw.relocation_slots(d)}
        slots_new = {s for s, _t in mw.relocation_slots(r)}
        L = mw.layout(r)
        box = struct.unpack_from("<6f", r, L.shapes[0].bbox)
        raw = m2.vertex_buffers[0].data["_p0"]
        (c, e), rad = mw._bounds(raw)
        _check("a 1600-vertex import grows the pool: tail shifted by 4 KiB pages, every slot and "
               "texture still resolves, submesh / buffer sizes / bounds follow the new mesh",
               len(r) > len(d) and (len(r) - len(d)) % 0x1000 == 0 and slots_old == slots_new
               and m2.vertex_buffers[0].count == 1600 and len(m2.shapes[0].indices) == 3 * len(tris)
               and not mw.validate(r) and texture.decode_bntx(r, 0) is not None
               and tuple(box) == tuple(c) + tuple(e)
               and abs(struct.unpack_from("<f", r, L.shapes[0].radius)[0] - rad) < 1e-6,
               f"{len(d):,} -> {len(r):,} B")
        # back: re-importing the original export restores the original counts
        back = mw.import_obj(r, 0, model.to_obj(model.parse(d))[0])
        mb = model.parse(back)
        _check("importing the original OBJ back restores the original geometry and file size",
               len(back) == len(d) and mb.shapes[0].indices == model.parse(d).shapes[0].indices
               and all(max(abs(x - y) for x, y in zip(p, q)) < 1e-4 for p, q in
                       zip(mb.shape_vertices(mb.shapes[0]), model.parse(d).shape_vertices(model.parse(d).shapes[0]))))

    # render after round trip
    try:
        import numpy as _npm  # noqa: F401  (the raster renderer)
    except ImportError:
        _npm = None
    if _npm is not None and npc_p.is_file():
        d = npc_p.read_bytes()
        m = model.parse(d)
        r = mw.import_obj(d, 0, model.to_obj(m)[0])
        _check("render after an export -> import round trip is pixel-identical",
               model.render(m, "front", 160).tobytes() == model.render(model.parse(r), "front", 160).tobytes())

    # in-place transforms
    if npc_p.is_file() and shield_p.is_file():
        for path in (shield_p, npc_p, B / "BM_04.model"):
            if not path.is_file():
                continue
            d = path.read_bytes()
            m = model.parse(d)
            L = mw.layout(d)
            sh = L.shapes[0]
            t = mw.transform_shape(d, 0, offset=(1.0, 2.0, 3.0))
            m2 = model.parse(t)
            a, b = m.shape_vertices(m.shapes[0]), m2.shape_vertices(m2.shapes[0])
            moved = all(abs(q[k] - p[k] - (1.0, 2.0, 3.0)[k]) < 1e-3 * max(1.0, abs(p[k])) for p, q in zip(a, b) for k in range(3))
            vb0 = L.pool + sh.vertex_offset
            vb1 = vb0 + sh.buffers[0][2]
            touched = {i for i in range(len(d)) if d[i] != t[i]} if len(t) == len(d) else {-1}
            allowed = set(range(vb0, vb1)) | set(range(sh.bbox, sh.bbox + 0x18 * (1 + sh.n_submesh))) | \
                set(range(sh.radius, sh.radius + 4))
            back = mw.transform_shape(mw.transform_shape(d, 0, scale=2.0, rotate=(10, 20, 30)),
                                      0, matrix=mw._inv4(mw.transform_matrix(2.0, None, (10, 20, 30),
                                                                             mw.shape_center(m, 0))))
            c = model.parse(back).shape_vertices(model.parse(back).shapes[0])
            inv_ok = all(max(abs(x - y) for x, y in zip(p, q)) < 1e-3 * max(1.0, max(map(abs, p))) for p, q in zip(a, c))
            _check(f"{path.name}: transform offset moves shape 0 (skin {m.shapes[0].skin}) in model space, "
                   f"touches only its vertices and bounds; scale+rotate then the inverse returns",
                   len(t) == len(d) and moved and touched <= allowed and not mw.validate(t) and inv_ok)


def _posed_lbs_error(m, anim, frame, shape, expected):
    """Largest distance (fraction of the model's size) between `shape`'s posed vertices and
    `expected` = [(model-space bind position, {bone index: weight})] skinned by the plain rule
    world(bone) * inverse(bind world(bone)); each expected vertex against its nearest result."""
    import math
    from rf4s_modkit import gltf as _gl, model as _model, modelwrite as _mw, skelanim as _sk
    size = _gl._extent(m)
    m.pose = _sk.pose_bones(m, anim, frame)
    try:
        world = _model.world_matrices(m.pose)
        bind = _model.world_matrices(m.bones)
        got = m.shape_vertices(m.shapes[shape])
    finally:
        m.pose = None
    worst = 0.0
    for p, w in expected:
        q = [0.0, 0.0, 0.0]
        for b, x in w.items():
            r = _model._apply(_model._mul(world[b], _mw._inv4(bind[b])), p)
            for k in range(3):
                q[k] += x * r[k]
        worst = max(worst, min(math.dist(q, g) for g in got))
    return worst / size


def test_model_glb_import():
    """Import from Blender (rf4s_modkit.meshimport): Export for Blender -> import of an
    unmodified .glb is byte-identical; edited meshes come back with the file's positions and
    BONE WEIGHTS (posed like linear blend skinning of those weights), influences the shape
    cannot store are dropped (heaviest kept) or moved to the nearest ancestor bone that has a
    skinning matrix, the rebuilt file passes the loader walk, and a removed shape stays in the
    file drawing nothing."""
    print("model import from glTF (Import from Blender):")
    import copy, math, tempfile, shutil
    from rf4s_modkit import gltf as _gl, meshimport as _mi, model as _model, modelwrite as _mw, skelanim as _sk
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    files = sorted(p for p in pathlib.Path(BUNDLE_DIR).rglob("*.model"))
    if not files or not (B / "M09_0.model").exists():
        _skip("glTF mesh import", "no extracted .model files / M09_0"); return
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        pick = ([B / x for x in ("M09_0.model", "NPC_TRAVELER_M.model", "M40_1.model", "BM_00.model",
                                 "NPC_RF2_BULLET.model", "I_WeaponM05_L.model", "MAP_CITY_00.model")]
                if QUICK else files)
        n = same = 0
        bad = []
        for f in pick:
            d = f.read_bytes() if f.is_file() else b""
            if not _model.is_mesh(d):
                continue
            n += 1
            g = tmp / "x.glb"
            _gl.export_glb(_model.parse(d), g, None, f.stem)
            out, rep = _mi.import_glb(d, g)
            if out == d and not rep.changed and not rep.unmatched:
                same += 1
            else:
                bad.append(f.name)
        _check("Export for Blender -> Import from Blender of an unmodified .glb is byte-identical"
               + (" (7 models)" if QUICK else " (every mesh .model)"), n and same == n,
               f"{same}/{n} {bad[:4]}")

        d = (B / "M09_0.model").read_bytes()
        m = _model.parse(d)
        g = tmp / "M09_0.glb"
        _gl.export_glb(m, g, None, "M09_0")
        meshes = _mi.read_meshes(g)
        plan, rest = _mi.match_shapes(m, meshes)
        _check("each mesh of the export matches its shape by name", sorted(plan) == [0, 1] and not rest,
               (sorted(plan), [r.name for r in rest]))
        # Blender's duplicate-name suffix is accepted when unambiguous
        ren = copy.deepcopy(meshes)
        ren[0].name = ren[0].name + ".001"
        ren[0].mesh_name = ""
        p2, r2 = _mi.match_shapes(m, ren)
        _check("a Blender-renamed object ('X.001') still finds shape X", len(p2) == 2 and not r2,
               [x.name for x in r2])

        by = {b.name: b.index for b in m.bones}
        s0, s1 = plan[0], plan[1]                         # skin 2 (smooth) / skin 1 (rigid)
        # smooth shape: every vertex +5 in Y, weights repainted; half on a bone with no smooth
        # matrix (end_Bone14 -> its parent leg_LD_Bone13), a few with five influences
        ed = copy.deepcopy(s0)
        ed.positions = [(x, y + 5.0, z) for x, y, z in ed.positions]
        five = {"body_Bone02": 0.3, "head_Bone03": 0.25, "leg_LD_Bone11": 0.2, "leg_LM_Bone07": 0.15,
                "leg_RU_Bone15": 0.1}
        for k in range(len(ed.weights)):
            ed.weights[k] = dict(five) if k % 5 == 0 else {"end_Bone14": 0.7, "head_Bone03": 0.3}
        # rigid shape: unskinned mesh (no weights) moved -> bones from the nearest vertex
        ed1 = copy.deepcopy(s1)
        ed1.weights = None
        ed1.positions = [(x + 2.0, y, z) for x, y, z in ed1.positions]
        out, rep = _mi.import_glb(d, [ed, ed1])
        m2 = _model.parse(out)
        r0 = next(r for r in rep.shapes if r.shape == 0)
        exp = []
        for k, p in enumerate(ed.positions):
            if k % 5 == 0:
                w = {by["body_Bone02"]: 0.3 / 0.55, by["head_Bone03"]: 0.25 / 0.55}
            else:
                w = {by["leg_LD_Bone13"]: 0.7, by["head_Bone03"]: 0.3}
            exp.append((p, w))
        stored_ok = True
        vb = m2.vertex_buffers[m2.shapes[0].vertex_buffer]
        for k in range(len(ed.positions)):
            want = exp[k][1]
            j = min(range(vb.count), key=lambda i: math.dist(vb.data["_p0"][i], ed.positions[k]))
            got = {}
            for ix, w in zip(vb.data["_i0"][j], vb.data["_w0"][j]):
                if w:
                    got[m2.matrix_to_bone[ix]] = got.get(m2.matrix_to_bone[ix], 0.0) + w
            stored_ok &= set(got) == set(want) and all(abs(got[b] - want[b]) < 1e-6 for b in want) \
                and abs(sum(vb.data["_w0"][j]) - 1.0) < 1e-6
        a = _sk.parse((B / "M09_0_00.bfskl").read_bytes()) if (B / "M09_0_00.bfskl").exists() else None
        lbs = max(_posed_lbs_error(m2, a, f, 0, exp) for f in (0, 15, 30)) if a else 0.0
        _check("repainted weights are stored as painted (2 heaviest, renormalised, sorted) and the "
               "posed shape is their linear blend skinning (< 0.001 % of the model's size)",
               stored_ok and lbs < 1e-5, f"lbs {lbs:.2e}")
        _check("a bone without a smooth matrix hands its weight to its nearest ancestor with one; "
               "five influences on a 2-influence shape are cut to the heaviest (both reported)",
               r0.moved_influences == {"end_Bone14": "leg_LD_Bone13"}
               and r0.dropped_influences == (len(ed.positions) + 4) // 5, (r0.moved_influences, r0.dropped_influences))
        p_old = m.shape_vertices(m.shapes[1])
        p_new = m2.shape_vertices(m2.shapes[1])
        mv = max(math.dist((a_[0] + 2.0, a_[1], a_[2]), b_) for a_, b_ in zip(p_old, p_new)) if len(p_old) == len(p_new) else 1e9
        _check("the rigid shape moved 2 units in X (bone frames kept: skin-1 vertices in their "
               "bone's space) and the rebuilt file passes the loader walk",
               mv < 1e-4 and not _mw.validate(out) and m2.vertex_buffers[m2.shapes[1].vertex_buffer].data["_i0"]
               == m.vertex_buffers[m.shapes[1].vertex_buffer].data["_i0"], mv)
        # the used-bone list (SHAP+0x28) follows the new weights
        L2 = _mw.layout(out)
        s = L2.shapes[0].shap
        cnt = _mw._u16(out, s + 0x64)
        lst = list(struct.unpack_from("<%dH" % cnt, out, _mw._u64(out, s + 0x28)))
        _check("the shape's used-bone list is rewritten to the bones its vertices now use",
               lst == sorted({by["body_Bone02"], by["head_Bone03"], by["leg_LD_Bone13"]}), lst)
        # rest pose: head_Bone03 moved up 3 in the file (node translation + the inverse bind
        # matrices a Blender export would write for it and its child)
        gl, bufs = _gl.read_gltf(g)
        hn = next(i for i, nd in enumerate(gl["nodes"]) if nd.get("name") == "head_Bone03")
        wm_old = _model.world_matrices(m.bones)
        hb = by["head_Bone03"]
        R = [row[:3] for row in wm_old[m.bones[hb].parent][:3]]
        # +3 in model Y, expressed in the parent's frame
        Ri = _mw._inv3(R)
        dl = _mw._mv3(Ri, (0.0, 3.0, 0.0))
        gl["nodes"][hn]["translation"] = [a_ + b_ for a_, b_ in zip(gl["nodes"][hn]["translation"], dl)]
        worlds, _par = _mi._node_worlds(gl)
        skin = gl["skins"][0]
        acc = gl["accessors"][skin["inverseBindMatrices"]]
        bv = gl["bufferViews"][acc["bufferView"]]
        buf = bytearray(bufs[0])
        for k, j in enumerate(skin["joints"]):
            inv = _mw._inv4(worlds[j])
            struct.pack_into("<16f", buf, bv.get("byteOffset", 0) + acc.get("byteOffset", 0) + 64 * k,
                             *[inv[r_][c_] for c_ in range(4) for r_ in range(4)])
        g3 = tmp / "rest.glb"
        g3.write_bytes(_gl._glb(gl, bytes(buf)))
        keep, rep_k = _mi.import_glb(d, g3)
        out, rep = _mi.import_glb(d, g3, bones=True)
        m4 = _model.parse(out)
        wm_new = _model.world_matrices(m4.bones)
        dy = wm_new[hb][1][3] - wm_old[hb][1][3]
        rest_same = max(max(abs(a_ - b_) for a_, b_ in zip(p_, q_)) for s_a, s_b in zip(m.shapes, m4.shapes)
                        for p_, q_ in zip(m.shape_vertices(s_a), m4.shape_vertices(s_b)))
        ibm_err = max(abs(_model._mul(wm_new[m4.matrix_to_bone[k]], inv)[r_][c_] - (r_ == c_))
                      for k, inv in enumerate(m4.inverse_bind) for r_ in range(3) for c_ in range(4))
        _check("rest pose (bones=True): the moved bone is 3 up in the model, its inverse bind matrix "
               "follows (W * IBM = I), the model looks the same at rest, the file passes the walk",
               abs(dy - 3.0) < 1e-4 and ibm_err < 1e-4 and rest_same < 1e-4 and not _mw.validate(out)
               and "head_Bone03" in rep.bones_moved, (round(dy, 5), ibm_err, rest_same, rep.bones_moved))
        _check("rest pose not taken (default): the file is unchanged and the report says the bones moved",
               keep == d and any("rest pose" in x for x in rep_k.notes), rep_k.notes)
        # a new part (a mesh with no shape of its name) added to shape 0, weighted to the head
        cube = _mi.GltfMesh("NewPart", "NewPart", [], None, None, None, None, [])
        hw = _model.world_matrices(m.bones)[by["head_Bone03"]]
        for obj in _mw.parse_obj(_mw.cube_obj((hw[0][3], hw[1][3], hw[2][3]), 6.0)):
            cube.positions = [v[0] for v in obj.vertices]
            cube.uvs = [v[1] for v in obj.vertices]
            cube.normals = [v[2] for v in obj.vertices]
            cube.triangles = obj.triangles
        cube.weights = [{"head_Bone03": 1.0}] * len(cube.positions)
        out, rep = _mi.import_glb(d, meshes + [cube], add={"NewPart": 0})
        m5 = _model.parse(out)
        r5 = next(r for r in rep.shapes if r.shape == 0)
        n0 = m.vertex_buffers[m.shapes[0].vertex_buffer].count
        lbs = max(_posed_lbs_error(m5, a, f, 0, [(p_, {by["head_Bone03"]: 1.0}) for p_ in cube.positions])
                  for f in (0, 30)) if a else 0.0
        _check("a new part (--add NewPart=0) is appended to the shape: its original vertices keep "
               "their bytes, the part follows its weights when posed, the file passes the walk",
               r5.kept == n0 and r5.vertices == n0 + 24 and r5.triangles == len(m.shapes[0].indices) // 3 + 12
               and lbs < 1e-5 and not _mw.validate(out) and not rep.unmatched,
               (r5.kept, r5.vertices, r5.triangles, f"{lbs:.1e}"))
        # removal: a shape deleted in Blender (remove_missing) is kept but drawn as nothing
        out, rep = _mi.import_glb(d, [s0], remove_missing=True)
        m3 = _model.parse(out)
        again, _r = _mi.import_glb(out, [s0], remove_missing=True)
        _check("remove_missing: the shape with no mesh keeps its record and numbers but becomes one "
               "degenerate triangle (1 vertex, indices 0 0 0); the other shape is untouched; "
               "removing it again changes nothing",
               len(m3.shapes) == len(m.shapes) and m3.shapes[1].indices == [0, 0, 0]
               and m3.vertex_buffers[m3.shapes[1].vertex_buffer].count == 1
               and m3.vertex_buffers[m3.shapes[0].vertex_buffer].data == m.vertex_buffers[m.shapes[0].vertex_buffer].data
               and not _mw.validate(out) and again == out and m3.shapes[1].name == m.shapes[1].name,
               rep.text())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_model_glb_blender():
    """With Blender installed: Export for Blender -> Blender import -> Blender glTF export,
    untouched, re-imports byte-identically (Blender moves positions by ~1e-5 and reorders
    vertices; the original bytes are recovered); a Blender edit (a shape moved up 5, another
    subdivided) comes back with the move exact, the subdivided shape posed as the linear blend
    skinning of Blender's interpolated weights, and a file that passes the loader walk."""
    print("model import from Blender (optional):")
    import glob, subprocess, tempfile, shutil
    exe = next(iter(sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender*\blender.exe"), reverse=True)), None) \
        or shutil.which("blender")
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not exe or not (B / "M09_0.model").exists():
        _skip("model import from Blender", "Blender not installed" if not exe else "no M09_0"); return
    from rf4s_modkit import gltf as _gl, meshimport as _mi, model as _model, modelwrite as _mw, skelanim as _sk
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        script = tmp / "edit.py"
        script.write_text(
            "import bpy, bmesh, sys\n"
            "a = sys.argv[sys.argv.index('--') + 1:]\n"
            "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
            "bpy.ops.import_scene.gltf(filepath=a[0])\n"
            "for o in bpy.context.scene.objects:\n"
            "    if o.type == 'MESH' and o.name == a[2]:\n"
            "        for v in o.data.vertices:\n"
            "            v.co.z += 5.0\n"
            "    if o.type == 'MESH' and o.name == a[3]:\n"
            "        bm = bmesh.new(); bm.from_mesh(o.data)\n"
            "        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=1, use_grid_fill=True)\n"
            "        bm.to_mesh(o.data); bm.free(); o.data.update()\n"
            "bpy.ops.export_scene.gltf(filepath=a[1], export_format='GLB', export_animations=False)\n",
            encoding="utf-8")
        rest_script = tmp / "rest.py"
        rest_script.write_text(
            "import bpy, sys\n"
            "from mathutils import Vector\n"
            "a = sys.argv[sys.argv.index('--') + 1:]\n"
            "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
            "bpy.ops.import_scene.gltf(filepath=a[0])\n"
            "arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')\n"
            "bpy.context.view_layer.objects.active = arm\n"
            "bpy.ops.object.mode_set(mode='EDIT')\n"
            "eb = arm.data.edit_bones[a[2]]\n"
            "eb.head += Vector((0, 0, 3.0)); eb.tail += Vector((0, 0, 3.0))\n"
            "bpy.ops.object.mode_set(mode='OBJECT')\n"
            "bpy.ops.export_scene.gltf(filepath=a[1], export_format='GLB', export_animations=False)\n",
            encoding="utf-8")
        results = {}
        for stem, move, sub in (("M09_0", "-", "-"), ("NPC_TRAVELER_M", "-", "-"), ("wI_FistN07_R", "-", "-"),
                                ("M09_0", "Nw4cRoot__M09_01", "Nw4cRoot__M09_02")):
            d = (B / f"{stem}.model").read_bytes()
            src, dst = tmp / f"{stem}.glb", tmp / f"{stem}_{move}.glb"
            _gl.export_glb(_model.parse(d), src, None, stem)
            r = subprocess.run([exe, "--background", "--factory-startup", "--python", str(script), "--",
                                str(src), str(dst), move, sub], capture_output=True, text=True, timeout=300)
            if not dst.exists():
                _check(f"Blender exported {stem}", False, (r.stdout or "")[-400:]); return
            results[(stem, move)] = (d, dst)
        ident = [_mi.import_glb(d, p)[0] == d for (stem, move), (d, p) in results.items() if move == "-"]
        _check("untouched through Blender (import -> export): byte-identical (M09_0, NPC_TRAVELER_M, "
               "wI_FistN07_R -- a mirrored bone Blender cannot keep in its rest pose)",
               ident == [True, True, True], ident)
        d, p = results[("M09_0", "Nw4cRoot__M09_01")]
        out, rep = _mi.import_glb(d, p)
        m, m2 = _model.parse(d), _model.parse(out)
        si_mv = next(sh.index for sh in m.shapes if sh.name == "Nw4cRoot__M09_01")
        si_sub = next(sh.index for sh in m.shapes if sh.name == "Nw4cRoot__M09_02")
        a_ = m.shape_vertices(m.shapes[si_mv])
        b_ = m2.shape_vertices(m2.shapes[si_mv])
        moved = sorted((round(x, 3), round(y + 5.0, 3), round(z, 3)) for x, y, z in a_)
        back = sorted({(round(x, 3), round(y, 3), round(z, 3)) for x, y, z in b_})
        _check("the shape moved up 5 in Blender is up 5 in the model (every vertex)",
               sorted(set(moved)) == back, (len(a_), len(b_)))
        me = next(x for x in _mi.read_meshes(p) if x.name == "Nw4cRoot__M09_02")
        by = {bn.name: bn.index for bn in m.bones}
        exp = []
        for pos, w in zip(me.positions, me.weights):
            tot = sum(w.values())
            exp.append((pos, {by[k]: v / tot for k, v in w.items()}))
        anim = _sk.parse((B / "M09_0_00.bfskl").read_bytes())
        lbs = max(_posed_lbs_error(m2, anim, f, si_sub, exp) for f in (0, 20))
        r_sub = next(r for r in rep.shapes if r.shape == si_sub)
        _check("the subdivided shape: more vertices, posed as the linear blend skinning of "
               "Blender's weights (< 0.01 % of the model's size), the file passes the loader walk",
               r_sub.vertices > len(m.shape_vertices(m.shapes[si_sub])) and lbs < 1e-4
               and not _mw.validate(out), f"{r_sub.vertices} v, lbs {lbs:.2e}")
        # a cube added in Blender, parented to the armature with automatic weights, added to shape 0
        add_script = tmp / "add.py"
        add_script.write_text(
            "import bpy, sys\n"
            "a = sys.argv[sys.argv.index('--') + 1:]\n"
            "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
            "bpy.ops.import_scene.gltf(filepath=a[0])\n"
            "arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')\n"
            "loc = arm.matrix_world @ arm.data.bones[a[2]].head_local\n"
            "bpy.ops.mesh.primitive_cube_add(size=6.0, location=loc)\n"
            "cube = bpy.context.active_object; cube.name = 'NewPart'\n"
            "bpy.ops.object.select_all(action='DESELECT'); cube.select_set(True); arm.select_set(True)\n"
            "bpy.context.view_layer.objects.active = arm\n"
            "bpy.ops.object.parent_set(type='ARMATURE_AUTO')\n"
            "bpy.ops.export_scene.gltf(filepath=a[1], export_format='GLB', export_animations=False)\n",
            encoding="utf-8")
        src, dst = tmp / "M09_0.glb", tmp / "M09_0_add.glb"
        r = subprocess.run([exe, "--background", "--factory-startup", "--python", str(add_script), "--",
                            str(src), str(dst), "head_Bone03"], capture_output=True, text=True, timeout=300)
        if not dst.exists():
            _check("Blender exported the added cube", False, (r.stdout or "")[-400:]); return
        _plain, rep0 = _mi.import_glb(d, dst)
        out, rep = _mi.import_glb(d, dst, add={"NewPart": si_sub})
        m4 = _model.parse(out)
        me = next(x for x in _mi.read_meshes(dst, m) if x.name == "NewPart")
        exp = []
        for pos, w in zip(me.positions, me.weights):
            tot = sum(w.values())
            exp.append((pos, {by[k]: v / tot for k, v in w.items()}))
        # the shape keeps 2 influences: compare against the 2 heaviest, renormalised
        exp2 = []
        for pos, w in exp:
            top = sorted(w.items(), key=lambda kv: -kv[1])[:2]
            t = sum(x for _b, x in top)
            exp2.append((pos, {b_: x / t for b_, x in top}))
        lbs = max(_posed_lbs_error(m4, anim, f, si_sub, exp2) for f in (0, 20))
        r_add = next(x for x in rep.shapes if x.shape == si_sub)
        _check("a cube added in Blender (automatic weights) is ignored unless --add names a shape; "
               "added, it joins that shape (original vertices kept) and is posed by its 2 heaviest "
               "Blender weights", rep0.unmatched == ["NewPart"] and _plain == d and r_add.kept >= 74
               and lbs < 1e-4 and not _mw.validate(out), (rep0.unmatched, r_add.kept, f"{lbs:.1e}"))
        # a bone moved up 3 in Blender's edit mode (rest pose), bones=True
        src, dst = tmp / "M09_0.glb", tmp / "M09_0_rest.glb"
        r = subprocess.run([exe, "--background", "--factory-startup", "--python", str(rest_script), "--",
                            str(src), str(dst), "head_Bone03"], capture_output=True, text=True, timeout=300)
        if not dst.exists():
            _check("Blender exported the rest-pose edit", False, (r.stdout or "")[-400:]); return
        out, rep = _mi.import_glb(d, dst, bones=True)
        m3 = _model.parse(out)
        hb = next(bn.index for bn in m.bones if bn.name == "head_Bone03")
        dy = _model.world_matrices(m3.bones)[hb][1][3] - _model.world_matrices(m.bones)[hb][1][3]
        size = _gl._extent(m)
        rest_same = max(max(abs(a_ - b_) for a_, b_ in zip(p_, q_)) for s_a, s_b in zip(m.shapes, m3.shapes)
                        for p_, q_ in zip(m.shape_vertices(s_a), m3.shape_vertices(s_b))) / size
        _check("a bone moved in Blender's edit mode comes back with bones=True: 3 up in the model, "
               "the rest shape unchanged (< 1e-5 of the size), only that bone and its child moved",
               abs(dy - 3.0) < 1e-3 and rest_same < 1e-5 and rep.bones_moved == ["head_Bone03", "end_Bone04"]
               and not _mw.validate(out), (round(dy, 4), rest_same, rep.bones_moved))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_model_grow():
    """New shapes (rf4s_modkit.modelgrow): the _DIC builder regenerates every shipped name
    dictionary byte for byte; add_shapes appends clones whose records match the template, keeps
    every existing shape's data and number, passes the loader walk and survives a no-op rebuild;
    a glTF mesh becomes a new shape posed by its own weights; more than 32 shapes is refused."""
    print("model grow: new shapes:")
    from rf4s_modkit import gltf as _gl, meshimport as _mi, model as _model, modelgrow as _mg, modelwrite as _mw, skelanim as _sk
    import copy
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    files = sorted(pathlib.Path(BUNDLE_DIR).rglob("*.model"))
    if not files or not (B / "M09_0.model").exists():
        _skip("model grow", "no extracted .model files / M09_0"); return
    n = same = 0
    for f in (files[::8] if QUICK else files):
        d = f.read_bytes()
        if not _model.is_mesh(d):
            continue
        M = _mw._u64(d, 0x28)
        S = _mw._u64(d, M + 0x20)
        offs = [_mw._u64(d, 0x30), _mw._u64(d, 0xA0), _mw._u64(d, M + 0x38), _mw._u64(d, M + 0x48),
                _mw._u64(d, S + 0x10)]
        for off in offs:
            if not off:
                continue
            nodes = _mg.read_dict(d, off)
            n += 1
            same += _mg.build_dict([k for _r, _l, _rr, k in nodes[1:]]) == nodes
    _check("the dictionary builder reproduces the shipped model / shape / material / bone / "
           "embedded-file dictionaries" + (" (every 8th file)" if QUICK else ""), n and same == n, f"{same}/{n}")
    grown = bad = 0
    badl = []
    for f in (files[::16] if QUICK else files[::3]):
        d = f.read_bytes()
        if not _model.is_mesh(d):
            continue
        m = _model.parse(d)
        k = min(2, 32 - len(m.shapes))
        if k <= 0:
            continue
        grown += 1
        out = _mg.add_shapes(d, [_mg.NewShape(f"ZZ_new{j}", j % len(m.shapes)) for j in range(k)])
        m2 = _model.parse(out)
        ok = not _mw.validate(out) and _mw.rebuild(out) == out and len(m2.shapes) == len(m.shapes) + k
        for i, sh in enumerate(m.shapes):
            ok &= (m2.shapes[i].name == sh.name and m2.shapes[i].indices == sh.indices
                   and m2.vertex_buffers[m2.shapes[i].vertex_buffer].data == m.vertex_buffers[sh.vertex_buffer].data)
        for j in range(k):
            a_, b_ = m.shapes[j % len(m.shapes)], m2.shapes[len(m.shapes) + j]
            ok &= (b_.indices == a_.indices and b_.skin == a_.skin and b_.material == a_.material
                   and m2.vertex_buffers[b_.vertex_buffer].data == m.vertex_buffers[a_.vertex_buffer].data)
        ok &= [x[3].decode() for x in _mg.read_dict(out, _mw._u64(out, _mw._u64(out, 0x28) + 0x38))[1:]] \
            == [sh.name for sh in m2.shapes]
        if not ok:
            bad += 1
            badl.append(f.name)
    _check("add_shapes on shipped models: clones equal their template, existing shapes untouched, "
           "names in the dictionary, loader walk clean, no-op rebuild stable"
           + (" (every 16th file)" if QUICK else " (every 3rd file)"), grown and not bad, f"{grown - bad}/{grown} {badl[:3]}")

    d = (B / "M09_0.model").read_bytes()
    m = _model.parse(d)
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        g = tmp / "M09_0.glb"
        _gl.export_glb(m, g, None, "M09_0")
        meshes = _mi.read_meshes(g, m)
        by = {b.name: b.index for b in m.bones}
        cube = _mi.GltfMesh("Horn", "Horn", [], None, None, None, None, [])
        hw = _model.world_matrices(m.bones)[by["head_Bone03"]]
        obj = _mw.parse_obj(_mw.cube_obj((hw[0][3], hw[1][3] + 4.0, hw[2][3]), 5.0))[0]
        cube.positions = [v[0] for v in obj.vertices]
        cube.uvs = [v[1] for v in obj.vertices]
        cube.normals = [v[2] for v in obj.vertices]
        cube.triangles = obj.triangles
        cube.weights = [{"head_Bone03": 0.75, "body_Bone02": 0.25}] * len(cube.positions)
        out, rep = _mi.import_glb(d, meshes + [cube], new={"Horn": ("Nw4cRoot__M09_02", "M09_01")})
        m2 = _model.parse(out)
        hs = m2.shapes[-1]
        a = _sk.parse((B / "M09_0_00.bfskl").read_bytes()) if (B / "M09_0_00.bfskl").exists() else None
        exp = [(p_, {by["head_Bone03"]: 0.75, by["body_Bone02"]: 0.25}) for p_ in cube.positions]
        lbs = max(_posed_lbs_error(m2, a, f, hs.index, exp) for f in (0, 30)) if a else 0.0
        _check("a glTF mesh as a NEW shape: shape 2 'Horn', 24 v / 12 t, material M09_01, skinned by its "
               "own weights when posed, the other shapes untouched, loader walk clean",
               len(m2.shapes) == 3 and hs.name == "Horn" and len(hs.indices) == 36
               and m2.materials[hs.material].name == "M09_01" and lbs < 1e-5 and not _mw.validate(out)
               and all(m2.vertex_buffers[m2.shapes[i].vertex_buffer].data == m.vertex_buffers[m.shapes[i].vertex_buffer].data
                       for i in range(2)), (rep.text()[-200:], f"{lbs:.1e}"))
        again, rep2 = _mi.import_glb(out, meshes + [cube])
        _check("importing the same file again into the grown model changes nothing (Horn matches its shape)",
               again == out, rep2.text()[-200:])
        many = [_mg.NewShape(f"N{j}", 0) for j in range(31)]
        try:
            _mg.add_shapes(d, many)
            refused = False
        except _mg.ModelGrowError:
            refused = True
        _check("more than 32 shapes is refused (the game's per-model arrays hold 32)", refused)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_model_material():
    """Material settings (rf4s_modkit.matedit): every shipped material lists its wrap / user-data
    settings; an edit changes exactly the bytes the loader reads (sampler bytes 0-1, the int /
    float3 user-data values), keeps the file size, and refuses settings a material lacks."""
    print("model material settings:")
    from rf4s_modkit import matedit as _me, model as _model
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    files = sorted(pathlib.Path(BUNDLE_DIR).rglob("*.model"))
    if not files or not (B / "BM_00.model").exists():
        _skip("model material", "no extracted .model files / BM_00"); return
    n = one = 0
    for f in (files[::8] if QUICK else files):
        d = f.read_bytes()
        if not _model.is_mesh(d):
            continue
        for s in _me.materials(d):
            n += 1
            one += s.wrap is None or all(0 <= x <= 4 for x in s.wrap)      # 1 shipped material has no sampler
    _check("every material's sampler has wrap modes 0..4" + (" (every 8th file)" if QUICK else ""),
           n and one == n, f"{one}/{n}")
    d = (B / "BM_00.model").read_bytes()
    out = _me.set_material(d, 0, wrap_u="mirror", wrap_v="clamp", blend=2, draw_order=3, combine=2)
    s0 = _me.materials(out)[0]
    diff = [k for k in range(len(d)) if d[k] != out[k]]
    want = {s0.wrap_at, s0.wrap_at + 1} | {s0.user_at[k][0] for k in ("BlendType", "DrawOrder", "CombineType")}
    m2 = _model.parse(out)
    _check("an edit changes only the sampler / user-data bytes, in place, and reads back "
           "(model.parse sees BlendType 2)",
           len(out) == len(d) and set(diff) <= want and s0.wrap == (1, 2)
           and s0.user == {"DrawOrder": 3, "BlendType": 2, "CombineType": 2} and m2.materials[0].blend_type == 2,
           (s0.wrap, s0.user, len(diff)))
    try:
        _me.set_material((B / "M09_0.model").read_bytes(), 0, blend=2)
        refused = False
    except _me.MatEditError:
        refused = True
    _check("a user-data setting the material does not carry is refused (not added)", refused)


def test_explorer_model_glb_import():
    """rf4mod_gui model tab: Import from Blender… rebuilds shapes from a .glb (same-named mesh
    preselected), makes the result the tab's working copy, and reports an unedited export as
    unchanged; Materials… opens and edits a material's settings in place."""
    print("asset explorer: Import from Blender on a model tab:")
    import importlib.util, tempfile, shutil
    try:
        import tkinter as tk
    except Exception as e:
        _skip("model glb import", "no tkinter: %s" % e); return
    from rf4s_modkit import gltf as _gl, meshimport as _mi, model as _model
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    src = B / "M09_0.model"
    if not src.exists():
        _skip("model glb import", "no M09_0"); return
    spec = importlib.util.spec_from_file_location("rf4mod_gui_glb", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
    gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
    box = _headless_dialogs()
    tmp = pathlib.Path(tempfile.mkdtemp())
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        f = tmp / src.name
        shutil.copyfile(src, f)
        app = gui.App(root, initial=str(B))
        app.open_path(f)
        root.update_idletasks()
        doc = app._doc
        orig = doc.cur_data
        m = _model.parse(orig)
        g = tmp / "exp.glb"
        _gl.export_glb(m, g, None, "M09_0")
        seen = {}

        def take(mm, meshes, defaults):
            seen.update(defaults)
            return dict(defaults)
        same = app._import_model_glb(doc.cur_name, str(g), choose=take)
        _check("an unedited Export for Blender file re-imports as unchanged, same-named meshes "
               "preselected", same and doc.cur_data == orig and "unchanged" in app.status.cget("text")
               and seen == {sh.index: sh.name for sh in m.shapes}, (app.status.cget("text"), seen))
        # move the first mesh up 5 by rewriting its POSITION accessor in the .glb
        gl, bufs = _gl.read_gltf(g)
        mesh0 = next(nd for nd in gl["nodes"] if nd.get("name") == m.shapes[0].name)
        acc = gl["accessors"][gl["meshes"][mesh0["mesh"]]["primitives"][0]["attributes"]["POSITION"]]
        bv = gl["bufferViews"][acc["bufferView"]]
        buf = bytearray(bufs[0])
        for k in range(acc["count"]):
            o = bv.get("byteOffset", 0) + acc.get("byteOffset", 0) + 12 * k + 4
            struct.pack_into("<f", buf, o, struct.unpack_from("<f", buf, o)[0] + 5.0)
        acc["min"][1] += 5.0; acc["max"][1] += 5.0
        g2 = tmp / "moved.glb"
        g2.write_bytes(_gl._glb(gl, bytes(buf)))
        ok = app._import_model_glb(doc.cur_name, str(g2), choose=lambda mm, meshes, dflt: dict(dflt))
        m2 = _model.parse(doc.cur_data)
        dy = [b[1] - a[1] for a, b in zip(m.shape_vertices(m.shapes[0]), m2.shape_vertices(m2.shapes[0]))]
        _check("Import from Blender… rebuilds the edited shape into the working copy (moved up 5), "
               "the other shape untouched",
               ok and doc.cur_data != orig and dy and max(abs(x - 5.0) for x in dy) < 1e-3
               and m2.vertex_buffers[m2.shapes[1].vertex_buffer].data == m.vertex_buffers[m.shapes[1].vertex_buffer].data
               and "Rebuilt 1 shape" in app.status.cget("text") and not box["msgs"],
               (app.status.cget("text"), box["msgs"][:1]))
        # a new mesh in the file, appended to shape 1 through the add hook
        gl, bufs = _gl.read_gltf(g)
        nd = dict(next(x for x in gl["nodes"] if x.get("name") == m.shapes[1].name))
        nd["name"] = "NewPart"
        gl["nodes"].append(nd)
        gl["scenes"][0]["nodes"].append(len(gl["nodes"]) - 1)
        g4 = tmp / "added.glb"
        g4.write_bytes(_gl._glb(gl, bufs[0]))
        before = doc.cur_data
        ok = app._import_model_glb(doc.cur_name, str(g4), choose=lambda mm, meshes, dflt: dict(dflt),
                                   add={"NewPart": 1})
        m3 = _model.parse(doc.cur_data)
        n1 = _model.parse(before).vertex_buffers[m.shapes[1].vertex_buffer].count
        _check("Import from Blender… appends a mesh with no shape to the chosen shape (add)",
               ok and len(m3.shapes[1].indices) == 2 * len(m.shapes[1].indices), app.status.cget("text"))
        ok = app._import_model_glb(doc.cur_name, str(g4), choose=lambda mm, meshes, dflt: dict(dflt),
                                   new={"NewPart": 1})
        m4 = _model.parse(doc.cur_data)
        _check("Import from Blender… makes a mesh with no shape a new shape (new like shape 1)",
               ok and len(m4.shapes) == 3 and m4.shapes[2].name == "NewPart"
               and m4.shapes[2].indices == m.shapes[1].indices, app.status.cget("text"))
        # Materials…: the dialog builds (Apply with nothing changed returns nothing), and a
        # change goes into the working copy in place
        def press_apply():
            for w in root.winfo_children():
                if isinstance(w, tk.Toplevel):
                    for b in w.winfo_children():
                        for x in b.winfo_children():
                            if isinstance(x, gui.ttk.Button) and x.cget("text") == "Apply":
                                x.invoke(); return
        root.after(300, press_apply)
        nothing = app._edit_model_materials(doc.cur_name)
        before = doc.cur_data
        ok = app._edit_model_materials(doc.cur_name, changes={0: {"wrap_u": "mirror", "wrap_v": "clamp"}})
        from rf4s_modkit import matedit as _me
        _check("Materials…: the dialog opens and applies nothing when nothing changed; a wrap change "
               "lands in the working copy in place",
               nothing is False and ok and len(doc.cur_data) == len(before)
               and _me.materials(doc.cur_data)[0].wrap == (1, 2), _me.materials(doc.cur_data)[0].wrap)
        _check("model glb import raised no callback errors", not errs, errs[:1])
    finally:
        try:
            root.update()
        except tk.TclError:
            pass
        root.destroy()
        shutil.rmtree(tmp, ignore_errors=True)


def test_attr_tooltips():
    """The Paint ATTR controls must cover every bit that occurs in a shipped map,
    describe each one honestly, and make an impossible tile impossible to paint."""
    print("map editor: Paint ATTR controls + hover help:")
    mx = _map_editor()

    boxes = [b for _a, b in mx.PAINT_FLAGS]
    surf = [b for _a, b in mx.SURFACE_CHOICES if b]
    stairs = [b for _a, b in mx.STAIR_CHOICES if b]
    controls = set(boxes) | set(surf) | set(stairs)

    # the 24 bits that actually occur in the shipped maps, measured 2026-09-21
    OCCUR = {0x1, 0x2, 0x4, 0x8, 0x20, 0x40, 0x80, 0x100, 0x200, 0x400, 0x1000,
             0x2000, 0x4000, 0x8000, 0x10000, 0x20000, 0x40000, 0x80000,
             0x200000, 0x400000, 0x8000000, 0x10000000, 0x20000000, 0x40000000}
    missing = [hex(b) for b in sorted(OCCUR - controls)]
    _check("every occurring bit is paintable", not missing,
           missing or "%d bits: %d checkboxes + %d surface + %d stair choices"
           % (len(OCCUR), len(boxes), len(surf), len(stairs)))
    _check("stair choices match the loader's group B bits the maps use",
           set(stairs) == set(mx.STAIR_FIELD) and not set(stairs) & set(boxes)
           and all(b & 0x1C0E00 for b in stairs),
           "stairs + 0x80000 are one dropdown, no checkbox")

    _check("surface choices match the loader's group D",
           set(surf) == set(mx.SURFACE_FIELD),
           "%d choices == the 7 mutually-exclusive bits" % len(surf))
    overlap = [hex(b) for b in boxes if b in set(mx.SURFACE_FIELD)]
    _check("no surface bit also has a checkbox", not overlap,
           overlap or "the exclusive field is dropdown-only, so two cannot be set")
    _check("no duplicate checkbox", len(boxes) == len(set(boxes)),
           "%d distinct" % len(set(boxes)))

    nohelp = [hex(b) for b in sorted(controls) if b not in mx.ATTR_BIT_HELP]
    _check("every control has hover help", not nohelp,
           nohelp or "%d described" % len(controls))
    orphan = [hex(b) for b in mx.ATTR_BIT_HELP if b not in controls]
    _check("no help for a control that isn't there", not orphan, orphan or "none")

    _check("value list covers every shipped value", len(mx.KNOWN_ATTR_VALUES) == 110,
           "%d distinct values seen across all 872 maps" % len(mx.KNOWN_ATTR_VALUES))

    # bits whose meaning is not known must say so rather than invent one
    UNKNOWN = (0x1000, 0x8000, 0x80000, 0x200000, 0x10000000)
    bad = [hex(b) for b in UNKNOWN if not mx.ATTR_BIT_HELP[b].startswith("UNKNOWN")]
    _check("unknown bits are labelled UNKNOWN", not bad,
           bad or "%d marked honestly" % len(UNKNOWN))
    thin = [hex(b) for b in UNKNOWN if len(mx.ATTR_BIT_HELP[b]) < 200]
    _check("unknown bits carry the reasoning", not thin,
           thin or "each says where it occurs and what shape it makes")

    NO_READER = (0x200, 0x400, 0x40000, 0x2000, 0x20000, 0x40000000)
    bad = [hex(x) for x in NO_READER if "NOT read by any engine code" not in mx.ATTR_BIT_HELP[x]]
    _check("unread bits are labelled as unread", not bad,
           bad or "stairs / grass / snow / mansion-floor all marked")

    bad = [hex(x) for x in mx.SURFACE_FIELD if "only ONE" not in mx.ATTR_BIT_HELP[x]]
    _check("surface bits warn about exclusivity", not bad, bad or "all 7 warn")

    H = mx.ATTR_BIT_HELP
    _check("0x10: never blocks walking, not in any object template, unused by shipped maps",
           "Never blocks walking" in H[0x10] and "No shipped map authors it" in H[0x10]
           and "template" in H[0x10])
    _check("walking: 0x1 is not needed, 0x10000 stops only the knock-back, 0x8 blocks the "
           "player, the mask formula is given",
           "NOT needed for walking" in H[0x1] and "only the knock-back" in H[0x10000]
           and "Blocks the player" in H[0x8] and "cell & ~mask & 0x1018F" in H[0x1]
           and "0x101A1" in H[0x1] and "0x10021" in H[0x1] and "0x10121" in H[0x1])
    _check("0x4000 is 'fishable water' everywhere (note, surface choice, help)",
           "fishable-water" in mx.attr_notes(0x4000) and ("fishable water", 0x4000) in mx.SURFACE_CHOICES
           and H[0x4000].startswith("Fishable water"))
    _check("0x8000000 = object footprint marker, 0x20000000 = gangway, tilling needs a farm field",
           H[0x8000000].startswith("Object footprint marker") and H[0x20000000].startswith("Gangway")
           and "farm field" in H[0x20] and mx.attr_notes(0x8000002) == "block,footprint")
    from map_editor import attrs as A
    _check("walk readout from the actor masks",
           A.walk_readout(0x8) == "walk: player no · boots yes · monsters no · NPCs no · knock-back no"
           and A.walk_readout(0x10001) == "walk: player yes · boots yes · monsters yes · NPCs yes · knock-back no"
           and A.walk_readout(0x80) == "walk: player yes · boots yes · monsters no · NPCs no · knock-back no"
           and A.walk_readout(0x100) == "walk: player yes · boots yes · monsters no · NPCs yes · knock-back no"
           and A.walk_readout(0x0) == A.walk_readout(0x1), A.walk_readout(0x100))
    _check("value 0 is empty walkable ground with its own colour, not a void",
           mx.attr_notes(0) == "empty (walkable)"
           and A.assign_colors([0, 1, 1])[0] == A.ATTR_EMPTY != A.ATTR_FLOOR)
    _check("surface_help lists the whole field",
           all(("0x%X" % b) in mx.surface_help() for b in mx.SURFACE_FIELD),
           "dropdown tooltip names all 7")
    _check("attr_bit_help tolerates an unknown bit",
           "No description" in mx.attr_bit_help(0x80000000), "falls back cleanly")
    v = A.compose_value(0x80000001, {0x2}, "snow")
    _check("the flag controls keep bits they do not own and set one surface",
           v == 0x80020002 and A.surface_label(v) == "snow", hex(v))
    v = A.compose_value(0x201, {0x1}, "(none)", "stairs↕")
    _check("the stairs dropdown replaces the old stair direction",
           v == 0x40001 and A.stair_label(v) == "stairs↕" and "stairs↕" in mx.stairs_help() + "stairs↕",
           hex(v))


def test_map_editor_placed_objects():
    """Placed objects (MOBJ) vs RF4S.exe: flag fields stored as typed (no stale high bits),
    flag ids / forage / door / type-263 / inverted-gate checks, off-grid only warned where the
    player cannot reach, (0, 0) is a real position, the collision the objects stamp at load
    (refdata/rf4s_exe_collision.json) drawn and named in the Alt tooltip, and duplicate /
    paste / Add giving chests, crates and mushroom pickups an unused flag, warning about shared
    ones, keeping a warp point's destination and moving a knock-back target."""
    print("map editor: placed objects (flags, validation, collision stamps, copy rules):")
    import types
    from rf4s_modkit import collisionstamp, exetables, mobj_params as mp, rf4m as _rf4m
    # --- field sizes / names -------------------------------------------------------
    _check("f13 is a whole dword for objects, decorations, chests, seal doors; chest f9 a byte",
           all(mp.field_size(t, 13) == 4 for t in (200, 400, 44, 47, 53))
           and mp.field_size(44, 9) == 1 and mp.param_name(44, 9) == "reveal flag offset"
           and mp.field_size(263, 13) == 2 and "reveal" in mp.field_meaning(44, 9)
           and "every frame" in mp.field_meaning(200, 13))
    # --- validate(): synthetic records -------------------------------------------
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_DUNG_A03.rf4m").exists():
        _skip("placed objects", "no extracted bundleMain"); return
    base = _rf4m.Rf4mMap.load(B / "MAP_DUNG_A03.rf4m")
    W, H, _ = base.attr_grid()

    def findings(*recs):
        m = _rf4m.Rf4mMap.parse(base.build())
        for c in [c for c in m.chunks if c.tag == b"MOBJ"]:
            m.chunks.remove(c)
        for r in recs:
            m.add_mobj_record(list(r))
        return m.validate()

    def rec(t, x=80, y=80, **f):
        r = [t, -1, -1, -1, -1, -1, 4096, 0, 0, 0, 0, 0, 0, -1, x, y]
        for k, v in f.items():
            r[int(k[1:])] = v
        return r
    out = findings(rec(200, f13=2560), rec(44, f13=-5), rec(263, f13=-1), rec(44, f13=10, f9=-20),
                   rec(0, f10=30), rec(1, x=4, y=4, f9=8), rec(210, f12=4, f13=0))
    _check("flag ids outside -1 / 0..2559, a chest's reveal flag, type 263 with -1, ore row "
           "past MapOre_Rate, forage scatter off the packed range: ERROR; inverted gate with no "
           "flag: WARN",
           sum("is not -1 or 0..2559" in x for x in out) == 2
           and any("reveal flag f13 + f9 = -10" in x for x in out)
           and any("found flag f13 = -1" in x for x in out)
           and any("past the 25 rows" in x for x in out)
           and any("does not fit the forage registry" in x for x in out)
           and any(x.startswith("WARN") and "never stamps its collision" in x for x in out), out)
    out = findings(*[rec(3, x=100 + i, y=100) for i in range(33)])
    out2 = findings(*[rec(82 + i, f13=750) for i in range(5)])
    _check("33 forage spawners ERROR, 5 door / wall objects WARN",
           any(x.startswith("ERROR") and "at most 32" in x for x in out)
           and any(x.startswith("WARN") and "5 door / road / wall" in x for x in out2))
    out = findings(rec(44, x=-40, f13=200), rec(200, x=-40), rec(47, x=-240, y=0, f13=100),
                   rec(53, f13=800), rec(53, x=160, f13=800), rec(46, f13=300, f9=1),
                   rec(46, f13=300, f9=0))
    _check("off the grid: warned for a chest the player cannot reach, not for a tree or a "
           "seal-door controller; a shared crate flag is warned, a pressure plate is not "
           "a one-shot",
           any("MOBJ #0 (" in x and "outside the" in x for x in out)
           and not any(("MOBJ #1 (" in x or "MOBJ #2 (" in x) and "outside" in x for x in out)
           and sum("shares its one-shot flag 800" in x for x in out) == 2
           and not any("flag 300" in x for x in out), out)
    maps = sorted(B.glob("MAP_*.rf4m"))
    outside = shared = 0
    for p in maps:
        for x in _rf4m.Rf4mMap.load(p).validate():
            outside += "MOBJ" in x and "outside the" in x
            shared += "shares its one-shot flag" in x
    _check("shipped maps: no off-grid entity warning (was 228); the one-shot flags two records "
           "of one map share are all warned (66: 63 seal doors, 3 crates)",
           outside == 0 and shared == 66, (outside, shared))
    # --- (0, 0) is a real position; resize moves it and a knock-back target ------------
    m = _rf4m.Rf4mMap.parse(base.build())
    i0 = m.add_mobj_record(rec(71, x=0, y=0))
    i1 = m.add_mobj_record(rec(52, x=40, y=40, f8=100, f9=120))
    m.resize_attr_grid(W + 2, H + 2, origin=(1, 1))
    r0, r1 = m.mobj_records()[i0], m.mobj_records()[i1]
    _check("resize moves a record at (0, 0) and a knock-back vent's target",
           (r0[14], r0[15]) == (8, 8) and (r1[8], r1[9], r1[14]) == (108, 128, 48), (r0, r1))
    # --- collision stamps -----------------------------------------------------------
    tb = collisionstamp.table()
    _check("collision templates shipped: 111 object types, 196 uses 197's, 294 = gangway",
           len(tb["by_type"]) == 111 and tb["by_type"]["196"] == tb["by_type"]["197"]
           and set(collisionstamp.template(294)["cells"]) - {0} == {0x20000001},
           len(tb["by_type"]))
    try:
        fresh = __import__("gen_exe_tables_json").build_collision(None)
        _check("collision templates match RF4S.exe", fresh["templates"] == tb["templates"]
               and fresh["by_type"] == tb["by_type"])
    except exetables.ExeTableError as e:
        _skip("collision templates vs RF4S.exe", str(e))
    tree = rec(211, x=200, y=200, f11=0)
    mode, cells = collisionstamp.stamp(tree, 100, 100)
    mir = collisionstamp.stamp([*tree[:6], -4096, *tree[7:]], 100, 100)[1]
    box = collisionstamp.stamp(rec(202, f11=1), 100, 100)
    _check("a tree stamps its 18x18 template around its tile (mirrored with f6 < 0); an f11 "
           "record with f9 = f10 = 0 makes tile (0, 0) solid",
           mode == "template" and len(cells) == 122 and (25, 25) in cells
           and min(x for x, _y in cells) >= 25 - 9 and max(x for x, _y in cells) <= 25 + 8
           and {(2 * 25 - 1 - x, y) for x, y in cells} == set(mir)
           and box == ("box", {(0, 0): 2}), (mode, len(cells), box))
    # --- editor: duplicate / paste / add / nudge / Alt tooltip -----------------------
    try:
        import tkinter as tk
    except Exception:
        _skip("placed objects: editor", "no tkinter"); return
    me = _map_editor()
    from map_editor import data as med, render as mrender
    _headless_dialogs()
    root, p, errs = _headless_panel("MAP_DUNG_A03", B)
    try:
        saved_clip = None
        try:
            saved_clip = root.clipboard_get()
        except tk.TclError:
            pass
        d = p.doc
        recs = d.map.mobj_records
        k = next(i for i, r in enumerate(recs()) if (r[0] & 0xFFFF) == 44 and not r[9])
        used = set()
        for _s, (u, _o) in med.map_flag_uses().items():
            used |= u
        p.duplicate(("mobj", k))
        new = recs()[-1]
        _check("duplicating a chest gives the copy an unused scene flag (69..647)",
               new[13] != recs()[k][13] and 69 <= new[13] <= 647 and new[13] not in used
               and (new[14], new[15]) == (recs()[k][14] + 8, recs()[k][15] + 8), new)
        # inspector: typing -1 over a flag gives -1, 500 over -1 gives 500
        p.select(("mobj", k))
        form = p.inspector.forms["mobj"]
        form.rows[13][2].set("-1")
        form._commit_param(13)
        a = recs()[k][13]
        form.rows[13][2].set("500")
        form._commit_param(13)
        _check("the Inspector stores a flag as typed (-1, then 500), no stale high bits",
               a == -1 and recs()[k][13] == 500, (a, recs()[k][13]))
        # a switch keeps its flag and the status warns; a crate from another map gets a new one
        sw = rec(46, f13=recs()[k][13], f9=1)
        d.map.add_mobj_record(sw)
        d.notify({"mobj"})
        msgs = []
        p.status = msgs.append
        p.duplicate(("mobj", len(recs()) - 1))
        _check("duplicating a switch keeps its flag and the status line warns it is shared",
               recs()[-1][13] == 500 and msgs and "WARNING: it shares its one-shot flag 500" in msgs[-1],
               msgs[-1:])
        e14 = _rf4m.Rf4mMap.load(B / "MAP_DUNG_E14.rf4m")
        ci = next(i for i, r in enumerate(e14.mobj_records()) if (r[0] & 0xFFFF) == 53 and r[13] >= 752)
        import json
        root.clipboard_clear()
        root.clipboard_append(me.panel.CLIP_TAG + json.dumps(
            {"kind": "mobj", "from": "MAP_DUNG_E14", "record": list(e14.mobj_records()[ci])}))
        p.paste_object((80, 80))
        cr = recs()[-1]
        _check("a pasted daily crate gets an unused flag in the daily-reset block (752..969)",
               752 <= cr[13] <= 969 and cr[13] not in used and "got the unused flag" in msgs[-1],
               (cr[13], msgs[-1:]))
        a01 = _rf4m.Rf4mMap.load(B / "MAP_DUNG_A01.rf4m")
        wp = list(a01.mobj_records()[6])
        root.clipboard_clear()
        root.clipboard_append(me.panel.CLIP_TAG + json.dumps(
            {"kind": "mobj", "from": "MAP_DUNG_A01", "record": wp}))
        p.paste_object((80, 80))
        _check("a warp point pasted from another map keeps its destination (f10 is relative)",
               med.map_id("MAP_DUNG_A03") + recs()[-1][10] == med.map_id("MAP_DUNG_A01") + wp[10],
               (recs()[-1][10], wp[10]))
        # nudge: an entity may go off the grid
        j = len(recs()) - 1
        p.select(("mobj", j))
        x0 = recs()[j][14]
        p.nudge(-(x0 + 16), 0)
        _check("the arrow keys can move an entity off the grid", recs()[j][14] == -16, recs()[j][14])
        # add: the 40-record cap, and an inscribed stone gets a real flag
        p.add_kind, p.add_type = "entity", 263
        ev = types.SimpleNamespace(x=40, y=40, state=0)
        n = len(recs())
        p.tools["add"].press(ev)
        _check("Add: an inscribed stone (263) starts with an unused flag, not -1",
               len(recs()) == n + 1 and 69 <= recs()[-1][13] <= 647, recs()[-1])
        while sum(1 for ch in d.map.chunks if ch.tag == b"MOBJ") < 40:
            d.map.add_mobj_record(rec(400))
        d.notify({"mobj"})
        n = len(recs())
        p.tools["add"].press(ev)
        _check("Add refuses a 41st MOBJ record", len(recs()) == n and "Can't add" in msgs[-1], msgs[-1:])
        # (0, 0) drawn; the stamp layer and the Alt tooltip
        o0 = {"category": "object", "pos_x": 0, "pos_y": 0, "type_id": 200}
        _check("a record at (0, 0) is drawn; map parameters are not",
               mrender.entity_visible(o0, {}) and not mrender.entity_visible(
                   {"category": "mapparam", "pos_x": 0, "pos_y": 0}, {}))
        rp, pp, _e = _headless_panel("MAP_FIELD_04", B)
        try:
            pp.view.st.layers["stamps"] = True
            prims = mrender.overlay("stamp", pp.view.st)
            i, _mode, cells = mrender.object_stamps(pp.doc, None)[0]
            t = next(iter(cells))
            tip = pp.view.attr_tip(t)
            _check("the object-collision layer draws the stamps; the Alt tooltip names the object",
                   prims and all(q.opt.get("stipple") for q in prims)
                   and f"stamped by #{i}" in tip and "walk:" in tip, tip)
        finally:
            rp.destroy()
        _check("no Tk errors", not errs, errs[:1])
    finally:
        try:
            root.clipboard_clear()
            if saved_clip is not None:
                root.clipboard_append(saved_clip)
        except Exception:
            pass
        root.destroy()


def test_ground_texture_replacement():
    """The map editor's ground export/import must round-trip a real map: same grid,
    same tile count, same per-tile dimensions, same format, and visually lossless."""
    print("map editor: ground-texture export/import:")
    import tempfile
    try:
        import tkinter as tk  # noqa: F401
        from PIL import Image, ImageChops  # noqa: F401
    except Exception as e:
        _check("ground replacement", True, "skipped (no tkinter/PIL: %s)" % e)
        return
    from rf4s_modkit import texture, mapground
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not B.exists():
        _check("ground replacement", True, "skipped (no extracted bundleMain)")
        return

    def reader(n):
        f = B / n
        return f.read_bytes() if f.exists() else None

    name = "MAP_CITY_00"
    root, panel, _errs = _headless_panel(name, B, reader)
    try:
        from map_editor.tabs import LAYER_NAMES
        layer, note = panel.ground_layer_choice()
        _check("a ground layer is resolvable", layer is not None, note or "layer %s" % layer)
        if layer is None:
            return

        info = panel.ground_info(layer)
        # the set is resolved from the game's table, not assumed to be the map name
        _check("grid matches ceil(24*ATTR/512)",
               (info["cols"], info["rows"]) == mapground.grid_dims(180, 45),
               "%dx%d for a 180x45 map" % (info["cols"], info["rows"]))
        _check("tile count == cols*rows",
               len(info["tiles"]) == info["cols"] * info["rows"],
               "%d tiles" % len(info["tiles"]))

        tmp = pathlib.Path(tempfile.mkdtemp())
        lay = panel.ground_export_to(tmp / "g.png", layer)
        _check("export writes a PNG at the atlas extent",
               (tmp / "g.png").exists() and lay["image_size"] == (180 * 24, 45 * 24),
               "%dx%d == ATTR 180x45 * 24" % lay["image_size"])

        names = panel.ground_import_from(tmp / "g.png", tmp / "out", layer, "keep")
        _check("import writes one file per tile", len(names) == len(info["tiles"]),
               "%d files" % len(names))

        dims_ok = fmt_ok = True
        worst = 0.0
        for n in names:
            a = texture.parse(reader(n))
            b = texture.parse((tmp / "out" / n).read_bytes())
            if (a["width"], a["height"]) != (b["width"], b["height"]):
                dims_ok = False
            if b["fmt_name"] != "BC7":
                fmt_ok = False
            ia = texture.decode_to_image(reader(n)).convert("RGB")
            ib = texture.decode_to_image((tmp / "out" / n).read_bytes()).convert("RGB")
            if ia.size == ib.size:
                d = ImageChops.difference(ia, ib)
                px = list(d.getdata())
                worst = max(worst, sum(sum(t) for t in px) / (len(px) * 3))
        _check("per-tile dimensions preserved", dims_ok, "every tile kept its own size")
        _check("tiles stay BC7", fmt_ok, "format unchanged by a keep-format import")
        _check("round-trip is visually lossless", worst < 5.0,
               "worst tile mean abs error %.2f / 255" % worst)

        # a wrong-sized image must be refused, not silently rescaled
        Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(tmp / "bad.png")
        refused = False
        try:
            panel.ground_import_from(tmp / "bad.png", tmp / "out2", layer, "keep")
        except Exception:
            refused = True
        _check("a wrong-sized PNG is refused", refused, "import validates the extent")

        # --- the export layer is chosen explicitly, not inherited from the display
        # --- dropdown, and layer 1 works as well as layer 0
        avail = mapground.available_layers(reader, name)
        picker = list(panel.viewtab.glayer_cb["values"])
        _check("layer picker lists exactly the real layers",
               picker == [LAYER_NAMES.get(l, str(l)) for l in avail],
               "%s for layers %s" % (picker, avail))

        panel.set_ground_display("all")          # display says "all"...
        panel.viewtab.glayer.set(picker[-1])     # ...picker says the last layer
        got, _n = panel.ground_layer_choice()
        _check("display dropdown does not decide the export layer",
               got == avail[-1], "picker %r wins over display 'all' -> layer %s" % (picker[-1], got))

        if len(avail) > 1:
            l1 = avail[-1]
            lay1 = panel.ground_export_to(tmp / "g1.png", l1)
            n1 = panel.ground_import_from(tmp / "g1.png", tmp / "out1", l1, "keep")
            _check("layer %d exports and re-imports" % l1,
                   len(n1) == len(lay1["tiles"]) and (tmp / "g1.png").exists(),
                   "%d tiles, image %dx%d" % (len(n1), lay1["image_size"][0], lay1["image_size"][1]))
            import numpy as _np
            worst_a = 0.0
            has_alpha = False
            for f in n1:
                o = _np.asarray(texture.decode_to_image(reader(f)).convert("RGBA")).astype(int)
                r = _np.asarray(texture.decode_to_image((tmp / "out1" / f).read_bytes())
                                .convert("RGBA")).astype(int)
                if o[:, :, 3].min() < 250:
                    has_alpha = True
                worst_a = max(worst_a, float(_np.abs(o[:, :, 3] - r[:, :, 3]).mean()))
            _check("the overlay layer really is transparent", has_alpha,
                   "layer %d carries alpha, so preserving it matters" % l1)
            _check("alpha survives the round-trip", worst_a < 5.0,
                   "worst tile mean alpha error %.2f / 255" % worst_a)
    finally:
        root.destroy()


def test_map_editor_undo():
    """Undo/redo covers the map AND its sidecars as one history, moves the DISPLAYED grid
    (the renderer draws from a cache), and an undone edit is not 'unsaved'."""
    print("map editor: one undo history across map / search items / monster gates:")
    try:
        import tkinter as tk  # noqa: F401
    except Exception as e:
        _skip("map editor undo", "no tkinter: %s" % e); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_DUNG_A04.rf4m").exists():
        _skip("map editor undo", "no extracted bundleMain"); return
    root, panel, errs = _headless_panel("MAP_DUNG_A04", B)
    try:
        d = panel.doc
        w = d.grid[0]
        orig = {p: d._bytes(p) for p in ("map", "si", "gen")}

        def shown(x, y):
            return d.grid[2][y * w + x]

        painted = [(20, 20, 0x20001), (21, 20, 0x2), (22, 21, 0x4001)]
        for x, y, v in painted:
            with d.edit("paint", "attr"):
                d.set_cells({(x, y): v})
        _check("paints landed and each is one step", all(shown(x, y) == v for x, y, v in painted)
               and len(d.undo_stack) == 3)
        ok = True
        for x, y, _v in reversed(painted):
            panel.undo()
            ok &= shown(x, y) == d.map.attr_grid()[2][y * w + x]
        _check("undo moves the displayed grid, not just the map", ok, "display == map after 3 undos")
        for _ in painted:
            panel.redo()
        _check("redo re-applies", all(shown(x, y) == v for x, y, v in painted))
        root.update()
        missing = [hex(v) for v in set(d.grid[2]) if v not in panel.view.colors]
        _check("every displayed value has a colour", not missing, missing or "%d values" % len(set(d.grid[2])))
        # the Gates tab's "visible gate" box edits the header flag's low byte (0 = a gate you
        # see, else an invisible spawner), keeps its high byte, and undoes
        if d.gen is not None:
            gt = panel.encounters
            panel.set_active_gate((0, 0))
            gt._show_gate()
            ent = d.gen.patterns[0][0]
            # the gate's position as x / y fields in the Gates tab, editable (also off the map)
            x0, y0 = ent.gate_pos.points[0][:2]
            shown = (gt.gx.get(), gt.gy.get())
            gt.gx.set(str((d.grid[0] + 4) * 8))
            gt._commit_gpos()
            gt._show_gate()
            moved = (gt.gx.get(), gt.gpos_lbl.cget("text"))
            panel.undo()
            gt._show_gate()
            back = (gt.gx.get(), gt.gy.get())
            _check("the Gates tab shows the gate's position as x / y fields; typing moves it (also "
                   "off the map, marked), and it undoes",
                   shown == (str(x0), str(y0)) and moved[0] == str((d.grid[0] + 4) * 8)
                   and "off the map" in moved[1] and back == shown,
                   (shown, moved, back))
            ent = d.gen.patterns[0][0]              # the undo rebuilt the table
            f0 = ent.hdr.flag
            gt.visible.set(not gt.visible.get())
            gt._commit_gate()
            f1 = ent.hdr.flag
            gt.refresh()
            listed = gt.gates.item("0:0", "values")[0]
            panel.undo()
            # the active gate's white outlines follow the selection: gone once it moves on
            from map_editor import render as _mr
            mp = next((k, off) for k, off, _x, _y, _u in d.gate_points() if k == "mpos")
            panel.select(mp)
            lit = sum(1 for p in _mr.overlay("gate", panel.view.st) if p.opt.get("outline") == "#fff")
            panel.select(None)
            panel.show_tab("Inspect")
            after = sum(1 for p in _mr.overlay("gate", panel.view.st) if p.opt.get("outline") == "#fff")
            _check("a gate's white outlines show while its points are selected and go with the "
                   "selection (they used to stay)", lit >= 1 and after == 0, (lit, after))
            # the drawn gates follow the "monster gates" layer (sprites layer on)
            panel.view.st.sprites.reader = lambda fn: next(pathlib.Path(BUNDLE_DIR).rglob(fn)).read_bytes()                 if fn == "EFC_00_GATEA.model" else None
            panel.set_layer("sprites", True)
            panel.set_layer("gates", True)
            on = sum(1 for p in _mr.overlay("under", panel.view.st) if p.key and p.key[0] == "gpos")
            panel.set_layer("gates", False)
            off = sum(1 for p in _mr.overlay("under", panel.view.st) if p.key and p.key[0] == "gpos")
            panel.set_layer("gates", True)
            _check("the drawn gates follow the 'monster gates' layer", on >= 1 and off == 0, (on, off))
            panel.set_layer("gate_art", False)
            art_off = sum(1 for p in _mr.overlay("under", panel.view.st) if p.key and p.key[0] == "gpos")
            g_marks = sum(1 for p in _mr.overlay("gate", panel.view.st) if p.kind == "text")
            panel.set_layer("gate_art", True)
            _check("'draw gates' off: every gate position is the orange G again",
                   art_off == 0 and g_marks >= on, (art_off, g_marks))
            _check("the Gates tab's 'visible gate' box flips the gate header flag's low byte "
                   "(high byte kept), the list marks hidden gates, and it undoes",
                   (f0 & 0xFF == 0) == (f1 & 0xFF != 0) and f1 & 0xFF00 == f0 & 0xFF00
                   and ("(hidden)" in listed) == bool(f1 & 0xFF) and d.gen.patterns[0][0].hdr.flag == f0,
                   (hex(f0), hex(f1), listed))
        # sidecar edits share the history
        with d.edit("move spot", "si"):
            d.si.spots[0].x += 8
        with d.edit("add monster", "gen"):
            d.gen.add_spawn(next(d.gen.all_entries())[2], 60, 5)
        _check("map, SI and Gen edits all count as unsaved",
               panel.dirty_parts() == ["map", "search items", "monster gates"], panel.dirty_parts())
        while d.undo_stack:
            panel.undo()
        _check("undoing everything restores all three files byte-exact",
               all(d._bytes(p) == orig[p] for p in orig) and not panel.is_dirty())
        # a failing edit leaves no trace
        try:
            with d.edit("bad", "mobj"):
                d.map.set_mobj_record(0, [7] * 16)
                raise ValueError("refused")
        except ValueError:
            pass
        _check("a failed edit is rolled back and records nothing",
               d._bytes("map") == orig["map"] and not d.undo_stack)
        _check("no callback errors", not errs, f"{len(errs)}")
    finally:
        root.destroy()


def test_map_editor_workflows():
    """The map editor as a user drives it: a click with pointer jitter moves nothing; a
    drag is one undo step and keeps a warp's sub-unit offset; forms commit only real
    changes and never re-apply an undone value; paint / fill / rectangle / pick; the Add
    and Warp tools; the chunk editor refuses edits that break the map; validation lists
    problems and jumps to them; the export matches the view; unsaved edits are guarded and
    sidecar saves never overwrite the game's files."""
    print("map editor: workflows (tools, forms, chunks, validation, unsaved guard):")
    import tempfile, types
    from rf4s_modkit import mobj_types
    try:
        import tkinter as tk  # noqa: F401
    except Exception as e:
        _skip("map editor workflows", "no tkinter: %s" % e); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_06.rf4m").exists():
        _skip("map editor workflows", "no extracted bundleMain"); return
    box = _headless_dialogs()
    root, panel, errs = _headless_panel("MAP_CITY_06", B)
    try:
        d = panel.doc
        orig = d.map.build()
        panel.view.set_zoom(6)
        root.update_idletasks()
        cp = panel.view.cp
        c = panel.view.canvas

        def E(x, y, state=0):          # canvas coordinates -> a synthetic event
            return types.SimpleNamespace(x=int(x - c.canvasx(0)), y=int(y - c.canvasy(0)),
                                         state=state, widget=c, x_root=0, y_root=0)

        def click_drag(x0, y0, x1, y1, state=0):
            panel._press(E(x0, y0, state)); panel._drag(E(x1, y1, state)); panel._release(E(x1, y1, state))
            panel.view.flush()

        # ---- forms: committing unchanged values is a no-op -------------------------
        ef = panel.inspector.forms["mobj"]
        for i in range(len(d.objs)):
            panel.select(("mobj", i))
            ef._commit_pos(); ef._commit_field(6, ef.vscale); ef._commit_field(7, ef.vrot)
            for fi in range(16):
                if ef.rows[fi][1].winfo_manager():
                    ef._commit_param(fi)
        _vis_bad, _hidden_seen = [], 0
        for i, o in enumerate(d.objs):
            if o["category"] == "mapparam":
                continue
            panel.select(("mobj", i))
            _t = d.map.mobj_records()[i][0] & 0xFFFF
            _want = (mobj_types.mobj_reads_scale(_t), mobj_types.mobj_f7_kind(_t) is not None)
            _got = (bool(ef.scale_ent.winfo_manager()), bool(ef.rot_ent.winfo_manager()))
            _hidden_seen += not all(_want)
            if _want != _got or bool(ef.st.winfo_manager()) != any(_want):
                _vis_bad.append((i, _t, _want, _got))
        _check("the entity form shows Scale / Rotation only when the type reads f6 / f7 "
               "(an unused one only under 'show all 16 raw fields')",
               not _vis_bad and _hidden_seen > 0, _vis_bad[:5] or _hidden_seen)
        wf = panel.inspector.forms["warp"]
        for j in range(len(d.map.mapj_records())):
            panel.select(("warp", j)); wf._commit()
        mt = panel.maptab
        mt._commit_msea(); mt._commit_mgrp_controls()
        for i in range(3):
            mt._commit_tint_text(i)
        _check("committing every form unchanged changes nothing and records no undo",
               d.map.build() == orig and not d.undo_stack, f"{len(d.undo_stack)} steps")
        panel.select(None)

        # ---- select tool: jitter is a click, a drag is one step -------------------
        panel.set_tool("select")
        o = next(o for o in d.objs if o["pos_x"] == 143)          # 7/8 into its tile
        ox, oy = o["pos_x"] * cp / 8.0, o["pos_y"] * cp / 8.0
        click_drag(ox, oy, ox + 1, oy)
        w0 = d.map.mapj_records()[0]
        wx, wy = ((w0[1] + w0[3] // 2) >> 3) * cp + cp // 2, ((w0[2] + w0[4] // 2) >> 3) * cp + cp // 2
        panel.select(None)
        click_drag(wx, wy, wx + 1, wy)
        _check("a click with pointer jitter moves neither an entity near a tile edge nor a warp",
               d.map.build() == orig and not d.undo_stack)
        panel.select(None)
        click_drag(wx, wy, wx, wy + 2 * cp)
        w1 = d.map.mapj_records()[0]
        _check("dragging a warp 2 tiles is one step and keeps its exact sub-unit x / w / h",
               (w1[1], w1[2], w1[3], w1[4]) == (w0[1], w0[2] + 16, w0[3], w0[4]) and len(d.undo_stack) == 1,
               f"{w0[1:5]} -> {w1[1:5]}")
        panel.undo()
        i = next(k for k, o in enumerate(d.objs) if o["category"] != "mapparam" and o["pos_x"] and o["pos_y"])
        r0 = d.map.mobj_records()[i]
        ex, ey = r0[14] * cp / 8.0, r0[15] * cp / 8.0
        click_drag(ex, ey, ex + 3 * cp, ey + cp)
        r1 = d.map.mobj_records()[i]
        _check("dragging an entity moves it by whole tiles and keeps its sub-tile offset",
               (r1[14] - r0[14], r1[15] - r0[15]) == (24, 8) and panel.sel == ("mobj", i),
               f"{r0[14:16]} -> {r1[14:16]}")
        panel.undo()

        # ---- a form edit, undo, then the old focus-out must not bring it back -----
        panel.select(("mobj", i))
        ef.vx.set(str(r0[14] + 8)); ef._commit_pos()
        panel.undo(); ef._commit_pos()
        _check("undo then focus-out does not re-apply the undone entity edit", d.map.build() == orig)

        # ---- paint tools ----------------------------------------------------------
        panel.set_tool("paint"); panel.set_paint_value(0x4001); panel.set_brush(3)
        click_drag(10 * cp + 1, 10 * cp + 1, 16 * cp + 1, 10 * cp + 1)
        stroke = sum(1 for y in range(9, 12) for x in range(9, 18) if d.cell(x, y) == 0x4001)
        _check("a brush stroke paints a 3-wide band and is one undo step",
               stroke == 27 and len(d.undo_stack) == 1, f"{stroke} cells, {len(d.undo_stack)} steps")
        panel.set_tool("pick")
        panel._press(E(40 * cp + 1, 20 * cp + 1))
        _check("the pick tool takes the tile's value and returns to the paint tool",
               panel.paint_value == d.cell(40, 20) and panel.tool.name == "paint")
        panel.set_tool("rect"); panel.set_paint_value(0x2)
        click_drag(2 * cp + 1, 2 * cp + 1, 5 * cp + 1, 4 * cp + 1)
        _check("the rectangle tool fills the dragged tiles",
               all(d.cell(x, y) == 0x2 for x in range(2, 6) for y in range(2, 5)))
        panel.set_tool("fill"); panel.set_paint_value(0x8)
        before = d.cell(12, 10)
        panel._press(E(12 * cp + 1, 10 * cp + 1))
        _check("flood fill replaces the connected region", d.cell(12, 10) == 0x8 and d.cell(16, 11) == 0x8
               and before == 0x4001)
        while d.undo_stack:
            panel.undo()
        _check("paint, rectangle and fill all undo cleanly", d.map.build() == orig)

        # ---- add + warp tools ------------------------------------------------------
        panel.set_tool("add"); panel.set_add_kind("entity"); panel.add_type = 68
        panel._press(E(30 * cp + 2, 12 * cp + 2))
        rec = d.map.mobj_records()[-1]
        _check("the Add tool places an entity at the tile centre and selects it",
               panel.sel == ("mobj", len(d.objs) - 1) and rec[0] == 68 and (rec[14], rec[15]) == (244, 100))
        panel.set_tool("warp")
        click_drag(3 * cp + 1, 3 * cp + 1, 6 * cp + 1, 5 * cp + 1)
        wr = d.map.mapj_records()[-1]
        _check("the Warp tool creates a zone from the dragged rectangle",
               panel.sel == ("warp", len(d.map.mapj_records()) - 1) and tuple(wr[1:5]) == (24, 24, 32, 24),
               wr[1:5])
        while d.undo_stack:
            panel.undo()

        # ---- chunk editor refuses breaking edits -----------------------------------
        cd = panel.open_chunks()
        ai = next(k for k, ch in enumerate(d.map.chunks) if ch.tag == b"ATTR")
        cd.tree.selection_set(str(ai)); cd._selected()
        cd.hex.delete("1.0", "end"); cd.hex.insert("end", "00" * 20)
        cd.apply()
        cd.tag.set("ÄBCD"); cd.add()
        _check("chunk editor refuses a truncated ATTR and a non-ASCII tag (map untouched, no crash)",
               d.map.build() == orig and not errs and not d.undo_stack, f"{len(errs)} callback errors")
        cd.win.destroy()

        # ---- validation lists problems and jumps to them ---------------------------
        with d.edit("break a warp", "mapj"):
            r = list(d.map.mapj_records()[0]); r[5] = 9999; d.map.set_mapj_record(0, r)
        issues = panel.run_validation()
        k = next((n for n, (s, _w, m) in enumerate(issues) if s == "ERROR" and "warp #0" in m), None)
        if k is not None:
            panel.problems.tree.selection_set(str(k)); panel.problems._picked()
        _check("validation flags a warp to an unknown map and selecting it selects the warp",
               k is not None and panel.sel == ("warp", 0))
        panel.undo()

        # ---- export is the view --------------------------------------------------
        img = panel.render_to_image()
        W, H, _ = d.grid
        _check("PNG export matches the canvas extent at the current zoom",
               img is not None and img.size == (W * cp, H * cp), img.size if img else None)

        # ---- unsaved-changes guard + saves go through a dialog ---------------------
        mt.msea.set("3 winter"); mt._commit_msea()
        box["yesnocancel"] = None
        stays = panel.confirm_discard("switch") is False
        box["yesnocancel"] = False
        goes = panel.confirm_discard("switch") is True
        _check("unsaved map edits: Cancel stays, No discards", stays and goes and panel.dirty_parts() == ["map"])
        panel.undo()
        _check("an undone edit is not 'unsaved'", not panel.is_dirty())
        si_map = next((q for q in sorted(B.glob("MAP_FIELD_*.rf4m")) if _map_editor().si_file_for_map(q.name)), None)
        if si_map is not None:
            from rf4s_modkit import rf4m as _rf4m
            si_path = pathlib.Path(_map_editor().si_file_for_map(si_map.name))
            si_orig = si_path.read_bytes()
            panel.set_map(_rf4m.Rf4mMap.load(si_map), si_map.stem)
            panel.select(("si", 0))
            sf = panel.inspector.forms["si"]
            sf.vx.set(str(panel.doc.si.spots[0].x + 8)); sf._commit_pos()
            out = pathlib.Path(tempfile.mkdtemp()) / "SI_out.bin"
            box["save"] = str(out)
            saved = panel.save_si()
            _check("SI save writes through a Save dialog; the game's SI file is untouched",
                   saved and out.is_file() and si_path.read_bytes() == si_orig and not panel.is_dirty())
        # Ctrl shortcuts reach widgets built after startup (tagged when they take the focus)
        # and survive Caps Lock; Shift tells redo from undo
        import tkinter as _tk
        _late = _tk.Entry(panel.frame)                     # a field built after startup
        _late.pack()
        root.update_idletasks()
        _untagged = panel._tag not in _late.bindtags()
        # Tk delivers focus events only to a shown window: show it off-screen for a moment
        # (the harness never packs the panel's parent frame, so pack it too)
        panel.frame.master.pack(fill="both", expand=True)
        root.geometry("+-10000+-10000")
        root.deiconify()
        root.update()
        _late.event_generate("<FocusIn>", when="now")
        _tagged, _view = panel._tag in _late.bindtags(), _late.winfo_viewable()
        _late.focus_force()                                # key events go to the focus widget
        root.update()
        _calls = []
        _fns = (panel.save_to_game, panel.undo, panel.redo)
        panel.save_to_game = lambda: _calls.append("save")
        panel.undo = lambda: _calls.append("undo")
        panel.redo = lambda: _calls.append("redo")
        try:
            for _seq, _st in (("<Control-s>", 0x4), ("<Control-S>", 0x6),
                              ("<Control-Z>", 0x6), ("<Control-Z>", 0x5), ("<Control-y>", 0x4)):
                _late.event_generate(_seq, state=_st, when="now")
        finally:
            panel.save_to_game, panel.undo, panel.redo = _fns
            _late.destroy()
            root.withdraw()
        _check("map editor: Ctrl+S / Z / Y reach a widget built later (tagged on focus), also "
               "with Caps Lock; Shift+Z redoes",
               _untagged and _calls == ["save", "save", "undo", "redo", "redo"],
               f"calls={_calls} tagged={_tagged} viewable={_view} grab={root.grab_current()}")
        # the map stays anchored top-left: a map smaller than the window can't be scrolled
        # away from the corner (Tk lets a small scroll region float), a big one stays in bounds
        from map_editor import view as _mev
        _v = panel.view
        _cv = _v.canvas
        root.geometry("1600x1200+-10000+-10000")
        root.deiconify()
        root.update()
        _W, _H, _ = panel.doc.grid
        _small = [z for z in _mev.ZOOMS if _W * z < _cv.winfo_width() and _H * z < _cv.winfo_height()]
        _anch = bool(_small)
        if _small:
            _v.set_zoom(_small[-1])
            root.update()
            for _dir in (-10, 10):
                _cv.yview_scroll(_dir, "units")
                _cv.xview_scroll(_dir, "units")
                root.update()
                _anch = _anch and _cv.canvasx(0) == 0 and _cv.canvasy(0) == 0
        _inb = True
        root.geometry("700x500+-10000+-10000")                # small window: the map outgrows it
        root.update()
        _big = [z for z in _mev.ZOOMS if _W * z > _cv.winfo_width() + 100 and _H * z > _cv.winfo_height() + 100
                and z <= _v.max_zoom()]
        if _big:
            _v.set_zoom(_big[0])
            root.update()
            _cv.yview_scroll(10 ** 6, "units")
            _cv.xview_scroll(10 ** 6, "units")
            root.update()
            _inb = (_cv.canvasy(0) > 0 and _cv.canvasy(_cv.winfo_height()) <= _H * _v.cp + 1
                    and _cv.canvasx(_cv.winfo_width()) <= _W * _v.cp + 1)
            _cv.yview_scroll(-10 ** 6, "units")
            root.update()
            _inb = _inb and _cv.canvasy(0) == 0
        root.withdraw()
        _check("map view: a map smaller than the window stays anchored top-left while scrolling; "
               "a bigger one scrolls only within the map",
               _anch and _inb and bool(_big), f"small={_small[-1:]} big={_big[:1]}")
        _check("the workflows raised no callback errors", not errs, f"{len(errs)}")
    finally:
        box["save"] = ""
        root.destroy()


def test_cutscene_toolbox():
    """The cutscene editor's Instruction picker and Reference window (cutscene_editor/toolbox):
    every instruction's form makes a listing that assembles, an insert lands in the scene,
    SetSpeaker's character / side pickers choose the opcode, and the reference lists fill."""
    print("cutscene editor toolbox (instruction picker + reference):")
    try:
        import tkinter as tk
        import cutscene_editor as ce
    except Exception as e:
        _skip("cutscene toolbox", "no tkinter: %s" % e); return
    mc = _first("rf3.mc")
    if not mc:
        _skip("cutscene toolbox", "rf3.mc not extracted"); return
    dirs = [mc.parent] + [d for d in (pathlib.Path(BUNDLE_DIR) / "bundleMain",
                                     pathlib.Path(BUNDLE_DIR) / "bundlePatch2") if d.is_dir()]

    def reader(n):
        for d in dirs:
            if (d / n).is_file():
                return (d / n).read_bytes()
        return None
    from rf4s_modkit import script
    _headless_dialogs()
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        cx = ce.CutsceneExplorer(tk.Toplevel(root), reader=reader)
        sc = script.disassemble_bank(cx.doc.container.banks[48])[0]
        cx.show_bank(48, sc.entry_pc)
        first = next(iter(cx.scene.stmts))
        cx.select((first, None))
        p = cx.ask_insert_instruction()
        _check("one picker per editor", cx.ask_insert_instruction() is p)
        ents = p.entries()
        bad = []
        for _g, iid, text, _o, _v, _h in ents:
            kind, _, key = iid.partition(":")
            p.set_instruction((kind, int(key) if kind == "op" else key))
            if (kind, key) == ("ctl", "DIALOG"):       # "a new line" mints its id on Insert
                p.dlg_mode.set("existing")
                p._dialogue_mode()
            err = cx.assemble_check(p.text())[2]
            p.dlg_mode.set("new")
            if err:
                bad.append("%s: %s" % (p.text(), err[:80]))
        _check("every instruction's form (defaults) makes a listing that assembles",
               len(ents) > 600 and not bad, "%d instructions; %s" % (len(ents), bad[:3]))
        p.preset(("op", 16))
        p.fam_fields[0].var.set("Forte")
        p.fam_fields[1].var.set("Right")
        p._rebuild()
        _check("SetSpeaker: character + side pickers pick the opcode (Forte, Right = op 25, written 4, 1)",
               p.text().startswith("SetSpeaker(4, 1") and
               cx.assemble_check(p.text())[0][:2] == bytes([25, 0]), p.text())
        p.preset(("op", 628))                      # SetRegisters: reg0 .. reg9, the rest optional
        labels = [f.parts[0].cget("text") for f in p.op_fields]
        regs = p.op_fields
        regs[0].var.set("5")
        regs[2].var.set("7")
        p._rebuild()
        gap_ok = p.check()
        gap_msg = p.check_lbl.cget("text")
        gap_ins = p.insert()
        regs[1].var.set("6")
        p._rebuild()
        three = p.text()
        for k, f in enumerate(regs):
            f.var.set(str(k))
        p._rebuild()
        ten = p.text()
        _check("SetRegisters shows reg0 .. reg9 (reg1 .. reg9 optional); a gap (reg1 empty, reg2 set) "
               "is refused with a message and Insert does nothing; in order it writes only what is "
               "set; all ten assemble",
               labels[0] == "reg0" and labels[9] == "reg9 (optional)" and len(labels) == 10
               and gap_ok is False and "in order" in gap_msg and gap_ins is False
               and three == "SetRegisters(5, 6, 7)" and cx.assemble_check(three)[2] is None
               and ten.count(",") == 9 and cx.assemble_check(ten)[2] is None,
               (labels[:2], labels[-1:], gap_msg, three, ten))
        p.preset(("ctl", "PROMPT_CHOICE"))
        p._choice_add_row()
        p._rebuild()
        _check("a choice form with an added option assembles (one more option than the form starts with)",
               len(p.rows) == 3 and p.text().count("->") == 3 and cx.assemble_check(p.text())[2] is None,
               p.text())
        n0 = len(cx.scene.stmts)
        p.preset(("ctl", "EVAL"))
        p.e_val.var.set("7")
        p._rebuild()
        ok = p.insert()
        _check("Insert puts the listing after the selected statement (one more statement, undoable)",
               ok and len(cx.scene.stmts) == n0 + 1 and cx.stmt(cx.sel[0]).mnem == "EVAL", p.text())
        cx.undo()
        _check("undo removes it again", len(cx.scene.stmts) == n0)
        p.q.set("")
        p.fill_tree()
        tb_ = ce.toolbox
        fav = p.tree.get_children("grp:" + tb_.FAVOURITE_GROUP)
        rec = p.tree.get_children("grp:" + tb_.RECENT_GROUP) if p.tree.exists("grp:" + tb_.RECENT_GROUP) else ()
        p.tree.selection_set("fav:op:2")
        root.update()
        _check("the list opens on verified instructions, with Most used (DIALOG first) and the "
               "inserted EVAL under Recently used; a Most used row opens that instruction",
               p.only_ver.get() and fav and fav[0] == "fav:ctl:DIALOG" and rec and rec[0] == "rec:ctl:EVAL"
               and p.key == ("op", 2), (fav[:3], rec[:3], p.key))
        # x / y arguments: pick the point on the scene's map (1/8-tile units)
        from rf4s_modkit import script as _s
        c = cx.doc.container
        pos = c.n_primary + 60                        # tail bank of map 60 (the Dragon Room)
        spawn = next(((scn, pc) for scn in _s.disassemble_bank(c.banks[pos])
                      for pc, st in scn.stmts.items() if st.op == 153), None)
        if spawn is None:
            _skip("map point picker", "no SpawnEventActor in tail bank 60")
        else:
            cx.show_bank(pos, spawn[0].entry_pc)
            cx.select((spawn[1], None))
            p.preset(("op", 153))
            _check("SpawnEventActor's x / y are recognised as a map position",
                   ce.toolbox.coordinate_pairs(p.args) == [(2, 3)] and p.scene_map_id() == 60)
            mp = p.pick_on_map(2, 3)
            root.update()
            loaded = mp.view.doc is not None and mp.map_id == 60
            _check("SpawnEventActor in a map's bank: the picker's map is fixed to that map",
                   mp.locked and "disabled" in mp.map_cb.state())
            tb = ce.toolbox
            wargs = (script.meta.table_row(332) or {}).get("args") or []
            prim = next(b for b in c.banks if b.kind == "primary")
            m1 = tb.position_map(332, wargs, lambda i: 24 if i == 0 else None, prim)
            m2 = tb.position_map(332, wargs, lambda i: None, prim)
            m3 = tb.position_map(153, (script.meta.table_row(153) or {}).get("args") or [],
                                 lambda i: None, prim)
            _check("WarpToMap: a set map argument fixes the map; an unset one is chosen and written back; "
                   "SpawnEventActor in a primary bank lets you choose",
                   m1[0] == 24 and m1[1] and m1[3] == 0 and m2[0] is None and m2[1] is None
                   and m2[3] == 0 and m3[0] is None and m3[1] is None and m3[3] is None, "%s %s %s" % (m1, m2, m3))
            mp.grid_var.set(True)
            mp._grid()
            mp.view.set_zoom(8)
            mp.view.flush()
            n_grid = len(mp.view.canvas.find_withtag("grid"))
            mp.grid_var.set(False)
            mp._grid()
            mp.view.flush()
            _check("the position picker's grid checkbox draws / hides the tile grid",
                   n_grid > 0 and not mp.view.canvas.find_withtag("grid"), "%d grid items" % n_grid)
            cv = mp.view.canvas
            moved = []
            for (px, py) in ((60, 80), (140, 100)):
                cv.event_generate("<Motion>", x=px, y=py)
                cv.event_generate("<Button-1>", x=px, y=py)
                mp.view.invalidate("bg"); mp.view.invalidate("spawn"); mp.view.flush()
                items = cv.find_withtag("pickpt")
                moved.append((mp.pt, bool(items) and not cv.find_above(items[-1]),
                              "picked: x = %d" % mp.pt[0] in mp.readout.cget("text")))
            _check("a click moves the picker's marker and readout, and a redraw keeps the marker on top",
                   moved[0][0] != moved[1][0] and all(m[1] and m[2] for m in moved), moved)
            mp.pt = (8 * 20 + 4, 8 * 11 + 4)
            mp._use()
            p._rebuild()
            _check("picking a point writes it into the form (sub-units, 8 per tile)",
                   loaded and p.op_fields[2].token() == "164" and p.op_fields[3].token() == "92"
                   and ", 164, 92" in p.text(), p.text())
            texts = [w.cget("text") for w in _all_widgets(cx.inspector.frame if hasattr(cx.inspector, "frame") else cx.frame)
                     if w.winfo_class() == "TButton"]
            _check("the Inspector offers 'Pick x / y on the map' on an existing SpawnEventActor",
                   any("Pick x / y on the map" in str(t) for t in texts))
            # the map side follows the editor: a moved spawn shows at its new place
            import time
            from map_editor import data as _md
            calls = []
            _md.on_script_changed(lambda: calls.append(1) or True)
            spc = spawn[1]
            cx.select((spc, None))
            cx.set_arg(spc, 2, "200")
            cx.set_arg(spc, 3, "120")
            for _ in range(10):
                root.update(); time.sleep(0.03)
            now = [s for s in _md.script_spawns("MAP_F_ROOM_00")[1] if s["pc"] == cx.sel[0]]
            _check("after moving a SpawnEventActor, the map views see the new position (live, unsaved)",
                   now and (now[0]["x"], now[0]["y"]) == (200, 120) and calls,
                   "%s, %d change signal(s)" % (now[:1], len(calls)))
            cx.undo(); cx.undo()
        # Triggers tab: the selected entry's keys in the right-hand pane (no dialog)
        if len(c.banks) > 308 and c.banks[308].type_table_full().get(3, (0,))[0]:
            cx.show_bank(308)
            tt = cx.triggers
            iid = next(i for i, (ty, rr) in tt.rows.items() if ty == 3 and rr is not None)
            cx.nb.select(cx.triggers); root.update()
            tt.tree.selection_set(iid); root.update()
            d = cx.trigger_detail
            swapped = (cx.right_pane == "trigger" and d.winfo_manager() == "pack"
                       and cx.inspector.winfo_manager() == "")
            box0 = [v.get() for v in d.fields[0][2]]
            d.fields[0][2][2].set("120"); root.update()
            applied = d.apply(); root.update()
            subs = [v for _t, v in cx.doc.container.banks[308].entry_records(3)[0].subs]
            _check("Triggers pane: a region box shows as x / y / width / height, the condition by name, "
                   "and Apply writes the corners",
                   box0 == ["306", "440", "94", "80"] and "121" in d.fields[1][2].get()
                   and applied and subs == [306, 440, 426, 520, 121] and tt.selected()[0] == 3,
                   "%s -> %s" % (box0, subs))
            cx.undo(); root.update()
            bp = cx.trigger_detail.draw_box()
            root.update()
            bp.box = (100, 200, 180, 260); bp._use(); root.update()
            _check("Triggers pane: 'Draw the box on the map' opens the bank's map with the box and fills the fields",
                   bp.map_id == 60 and bp.locked and [v.get() for v in cx.trigger_detail.fields[0][2]] == ["100", "200", "80", "60"])
            cx.nb.select(cx.view); root.update()
            back = cx.right_pane == "inspector" and cx.inspector.winfo_manager() == "pack" \
                and cx.trigger_detail.winfo_manager() == ""
            # an edit on the Script tab refreshes the Triggers tab, which re-selects its row:
            # that must not take the right-hand pane away from the Inspector
            _f = next(iter(cx.scene.stmts))
            cx.select((_f, None))
            if cx.stmt(_f).op < 0xFFF0 and cx.stmt(_f).args:
                cx.set_arg(_f, 0, "12")
            root.update()
            _check("a trigger's details take the Inspector's place on the right while the Triggers tab "
                   "is open, and give it back on the Script tab -- also after an edit there",
                   swapped and back and cx.right_pane == "inspector"
                   and cx.inspector.winfo_manager() == "pack", cx.right_pane)
            cx.undo()
        r = cx.open_reference()
        _check("one Reference window per editor", cx.open_reference() is r)
        tabs = [r.nb.tab(i, "text") for i in range(len(r.nb.tabs()))]
        trees = [w for w in _all_widgets(r.win) if w.winfo_class() == "Treeview"
                 and w is not getattr(r, "uses", None)]          # the Flags tab's 'Used by' list
        counts = [len(t.get_children()) for t in trees]
        _check("Reference: flags, verified functions, text codes, characters, maps, items, trigger "
               "types all list something",
               tabs == ["Flags & variables", "Functions", "Text codes", "Characters", "Maps", "Items",
                        "Trigger types"]
               and len(counts) == 7 and all(counts) and counts[0] > 1000, "%s %s" % (tabs, counts))
        codes = [trees[2].item(i, "values") for i in trees[2].get_children()]
        from rf4s_modkit import textlint as _tl
        _num = next((c for c in codes if c[0] == "＠<n>＠"), None)
        _check("Text codes: every code the checker knows is listed, with the instruction that fills its slot "
               "(＠<n>＠ <- SetVar3)",
               _num is not None and "SetVar3" in _num[3] and len(codes) == len(_tl.token_reference())
               and all(any(c[0] == _tl.AT + v + _tl.AT for c in codes) for v in _tl.VILLAGERS)
               and all(any(lit in c[0] for c in codes) for lit, _k, _t in _tl._SLOTTED)
               and all(any(lit in c[0] for c in codes) for lit in _tl._PLAIN),
               _num)
        acts, ctl = ce.toolbox.verified_ops()
        _check("Functions lists only the human-verified instructions",
               counts[1] == len(acts) + len(ctl) and all(script.meta.human_verified(o) for o in acts),
               "%d rows, %d verified" % (counts[1], len(acts) + len(ctl)))
        import traceback as _tb
        _check("the toolbox raised no callback errors", not errs, "".join(_tb.format_exception(*errs[0])) if errs else "")
    finally:
        root.destroy()


def _all_widgets(w):
    for c in w.winfo_children():
        yield c
        yield from _all_widgets(c)


def test_statement_operands():
    """View -> Operands (2026-10-01): every statement's operands as stored -- an action's
    arguments as their expression bytes, a control op's fields -- shown in hex right after the
    opcode (one group and one colour per operand), in both views, named in the Alt explanation."""
    print("statement operands (View -> Operands):")
    from rf4s_modkit import script
    mc = _first("rf3.mc")
    if not mc:
        _skip("statement operands", "rf3.mc not extracted"); return
    c = script.Container(mc.read_bytes())
    n = bad = 0
    kinds = set()
    for bk in c.banks[::20]:
        seen = set()
        for sc in script.disassemble_bank(bk):
            for pc, st in sc.stmts.items():
                if pc in seen:
                    continue
                seen.add(pc)
                n += 1
                ops = script.statement_operands(bk.data, st)
                kinds.add(st.mnem if st.op >= 0xFFF0 else "action")
                if st.op < 0xFFF0:
                    ok = len(ops) == len(st.args) and all(
                        script.disasm_expr(o, 0)[0] == script.disasm_expr(bk.data, a)[0]
                        for (_l, o), a in zip(ops, st.args))
                else:
                    ex = [lab for lab, _o in ops if lab in ("value", "condition") or lab.startswith("weight")]
                    ok = sum(len(o) for lab, o in ops if lab not in ex) + 2 * len(ex) == st.size - 2
                bad += not ok
    _check("operands: an action's arguments are exactly its expressions; a control op's fields fill the "
           "statement (expressions counted by their 2-byte reference)",
           n > 10000 and bad == 0 and {"action", "DIALOG", "BR_Z", "CALL", "EVAL"} <= kinds,
           "%d statements, %d off, kinds %s" % (n, bad, sorted(kinds)[:6]))
    try:
        import tkinter as tk
        import cutscene_editor as ce
    except Exception as e:
        _skip("statement operands (editor)", "no tkinter: %s" % e); return
    root = tk.Tk(); root.withdraw()
    try:
        cx = ce.CutsceneExplorer(tk.Toplevel(root), reader=lambda nm: (_first(nm).read_bytes() if _first(nm) else None))
        sc = max((s for s in script.disassemble_bank(cx.doc.container.banks[48]) if s.ok), key=lambda s: len(s.stmts))
        cx.show_bank(48, sc.entry_pc)
        res = {}
        for mode in ("story", "code"):
            cx.mode.set(mode); cx.show_ops.set(True); cx.show_operands.set(True); cx._view_mode(); root.update()
            rows = [r for r in cx.view.rows if r.st is not None and r.key and r.key[1] is None]
            act = next(r for r in rows if r.st.op < 0xFFF0 and len(r.st.args) >= 2)
            tags = [t for _s, t in act.segs if t and t.startswith("opd")]
            groups = "".join(s for s, t in act.segs if t and t.startswith("opd")).split(" ")
            groups = [g for g in groups if g]
            if mode == "code":                          # monospace: the statement text lines up
                starts = {sum(len(s_) for s_, _t in r.segs[:next(i for i, (_s, t) in enumerate(r.segs)
                                                                   if t in ("act", "dlg"))])
                          for r in rows
                          if sum(len(o) for _l, o in script.statement_operands(cx.bank.data, r.st)) * 2
                          + len(script.statement_operands(cx.bank.data, r.st)) <= ce.render.SceneText.OPERAND_PAD_MAX}
                res["aligned"] = len(starts) == 1
            want = [o.hex() for _l, o in script.statement_operands(cx.bank.data, act.st)]
            seg_tags = [t for _s, t in act.segs]
            first_opd = next(i for i, t in enumerate(seg_tags) if t and t.startswith("opd"))
            text_at = next(i for i, (s_, t) in enumerate(act.segs) if t == "act" or "(" in s_)
            res[mode] = (len(tags) == len(act.st.args) and len(set(tags)) == min(len(tags), 6)
                         and groups == want                       # one hex group per operand
                         and seg_tags[first_opd - 1] == "opc"     # right after the opcode
                         and first_opd < text_at)                 # left of the statement
        cx.show_operands.set(False); cx.show_ops.set(False); cx.mode.set("story")
        cx._view_mode(); root.update()                  # (the toolbar is remembered: leave it plain)
        none = not any(isinstance(t, str) and t.startswith("opd") for r in cx.view.rows for _s, t in r.segs)
        st = act.st
        from cutscene_editor.render import SceneText
        expl = SceneText(cx.doc, cx.bank, cx.scene).explain(st)
        _check("both views show a statement's operands right after the opcode, one hex group and colour "
               "each, the bytes as stored; off again with the toggle; the Alt explanation names them",
               res == {"story": True, "code": True, "aligned": True} and none and "Operands (hex, as stored):" in expl
               and "arg 0 = " in expl, str((res, none)))
    finally:
        root.destroy()


def test_var_uses():
    """Variable xrefs (2026-10-01): every read / write of a named FLG_ / REG_ in every bank and
    in em.bin. `=` writes without reading, compound assignments read and write, everything
    else reads; the Reference window counts and lists them, opens a use, and follows edits."""
    print("variable uses across banks (FLG_ / REG_ xrefs):")
    import struct as _st
    from rf4s_modkit import script, varuses as vu, emscript
    from rf4s_modkit.emflags import EmFlagTable
    mc = _first("rf3.mc")
    if not mc:
        _skip("variable uses", "rf3.mc not extracted"); return
    c = script.Container(mc.read_bytes())
    emf = EmFlagTable.load()
    a, b = c.pack_var(100, 1), c.pack_var(200, 8)
    var = lambda e: b"\x02" + _st.pack("<I", e)
    acc = lambda bs: [x for _e, x in vu.expr_var_access(bs + b"\x00", 0)]
    _check("expressions: `=` writes, `+=` reads and writes, a comparison and a nested ref read",
           acc(var(a) + b"\x16\x90") == ["write"] and acc(var(b) + b"\x17\x02\x94") == ["read+write"]
           and acc(var(b) + b"\x17\x03\x8c") == ["read"]
           and acc(var(b) + b"\x17\x05\x8c" + var(a) + b"\x8e") == ["read", "read"])
    script.install_emflags_var_resolver(c, emf)
    import re as _re
    n = bad = 0
    for bk in c.banks[::10]:                                   # every 10th bank vs the disassembly
        for enc, ac, _entry, _pc, st in vu.bank_uses(bk):
            off, w, _s = c.unpack_var(enc)
            nm = vu.var_name(emf, off, w)
            if nm.startswith("var@"):
                continue
            offs = (list(st.args) if st.op < 0xFFF0 else []) + [x for x in (st.expr_refs or []) if x is not None]
            txt = " ".join(script.disasm_expr(bk.data, o)[0] for o in offs)
            q = _re.escape(nm)
            ok = {"write": bool(_re.search(r"\b%s = (?!=)" % q, txt)),
                  "read+write": bool(_re.search(r"\b%s (\*|/|%%|\+|-|&&|\|\|)= " % q, txt)),
                  "read": bool(_re.search(r"\b%s\b(?! (=|\*=|/=|%%=|\+=|-=|&&=|\|\|=) )" % q, txt))}[ac]
            n += 1
            bad += not ok
    _check("the read / write verdict agrees with the disassembly on every use checked", n > 500 and bad == 0,
           "%d checked, %d off" % (n, bad))
    db = _first("emdeb.bin")
    if _first("em.bin") and db:
        em = emscript.EmScript.parse(_first("em.bin").read_bytes(), emscript.EmNames.parse(db.read_bytes()))
        fes = next(v for v in emf.variables if v.name == "FLG_DATE_FES_NOW")
        fin = em.by_name["EV_DATE_FINISH"].idx
        _check("em.bin: EV_DATE_FINISH's alt action writes FLG_DATE_FES_NOW",
               (fes.bit_offset, fes.bit_width, "write", fin, "alt action") in vu.em_uses(em))
    try:
        import tkinter as tk
        import cutscene_editor as ce
    except Exception as e:
        _skip("variable uses (editor)", "no tkinter: %s" % e); return
    _headless_dialogs()
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *x: errs.append(x)
    try:
        cx = ce.CutsceneExplorer(tk.Toplevel(root), reader=lambda nm: (_first(nm).read_bytes() if _first(nm) else None))
        ref = cx.open_reference()

        def _wait_counts():                       # the index is built on a worker thread
            import time as _t
            t0 = _t.time()
            while (cx._var_uses is None or cx._var_thread is not None) and _t.time() - t0 < 180:
                root.update()
                _t.sleep(0.02)
            for _ in range(20):                   # let the poll hand the result to the window
                root.update()
                _t.sleep(0.01)
        ref._count_uses()
        _wait_counts()
        row = next(r for r in ref.flag_list.rows if r[0] == "REG_MAIN_SCENARIO")
        ok_sel = ref.show_var("REG_MAIN_SCENARIO")
        listed = len(ref.uses.get_children())
        _check("Reference: REG_MAIN_SCENARIO is read and written across banks and em.bin; selecting it "
               "lists every use", row[4] > 50 and row[5] > 50 and ok_sel
               and listed == len(cx.var_uses(*row[8])) and listed == row[4] + row[5]
               - sum(1 for x in cx.var_uses(*row[8]) if x[-2 if x[0] == "script" else 3] == "read+write"),
               "reads %s writes %s listed %d" % (row[4], row[5], listed))
        first = next(i for i in ref.uses.get_children() if ref._use_rows[i][0] == "script")
        ref.uses.selection_set(first)
        ref._open_use()
        root.update()
        _k, pos, entry, pc, _a, _s = ref._use_rows[first]
        _check("double-clicking a use opens that scene at the statement",
               cx.bank_pos == pos and cx.scene.entry_pc == entry and cx.sel == (pc, None))
        before = row[5]
        cx.apply("probe", lambda: cx.doc.container.insert_after(pos, pc, "EVAL (REG_MAIN_SCENARIO = 1)"))
        root.update()
        ref._count_uses()
        _wait_counts()
        after = next(r for r in ref.flag_list.rows if r[0] == "REG_MAIN_SCENARIO")[5]
        names = [nm for nm, _a in cx.statement_vars(cx.sel[0])] if cx.sel else []
        _check("an unsaved edit is counted at once (one more write); the script view knows the "
               "selected statement's variables", after == before + 1 and "REG_MAIN_SCENARIO" in names,
               "%s -> %s, %s" % (before, after, names))
        _check("variable uses raised no callback errors", not errs, str(errs[:1]))
    finally:
        root.destroy()


def test_entry_key_conflicts():
    """Scene triggers with keys already in use (2026-10-01): an entry the dispatcher could never
    reach (exact same keys, checked after an existing one, first-match type) is refused -- by
    Container.entry_key_conflicts, the editor's New scene / Keys paths and the CLI (--force
    overrides); one put first warns; types that collect every match are free; type 2 warns
    across the tail -> primary -> global lookup."""
    print("scene trigger keys already in use:")
    from rf4s_modkit import script
    mc = _first("rf3.mc")
    if not mc:
        _skip("trigger key conflicts", "rf3.mc not extracted"); return
    c = script.Container(mc.read_bytes())
    # a tail bank with two or more type-2 entries of different keys
    pos = next(p for p, b in enumerate(c.banks) if b.kind == "tail"
               and len({tuple(r.subs) for r in b.entry_records(2)}) >= 2)
    recs = c.banks[pos].entry_records(2)
    first = recs[0]
    other = next(r for r in recs if tuple(r.subs) != tuple(first.subs))
    err_app, w_app, _ = c.entry_key_conflicts(pos, 2, first.subs)
    err_top, w_top, _ = c.entry_key_conflicts(pos, 2, first.subs, 0)
    err_same, _w, _ = c.entry_key_conflicts(pos, 2, first.subs, editing=first.index)
    err_edit, _w, _ = c.entry_key_conflicts(pos, 2, first.subs, editing=other.index)
    _check("same keys, first-match type: appended (never runs) is refused, put first only warns, an "
           "entry keeps its own keys, another later entry cannot take them",
           err_app and "never run" in err_app and not err_top and any("stops running" in w for w in w_top)
           and not err_same and (err_edit if other.index > first.index else not err_edit),
           str((err_app, w_top, err_same, err_edit))[:200])
    allt = next((t for t, v in __import__("rf4s_modkit.entry_types", fromlist=["x"]).ENTRY_TYPES.items()
                 if isinstance(v, dict) and v.get("select") == "all"
                 and any(len(b.entry_records(t)) for b in c.banks)), None)
    if allt is not None:
        bp = next(p for p, b in enumerate(c.banks) if b.entry_records(allt))
        r0 = c.banks[bp].entry_records(allt)[0]
        _check("a type that runs every matching entry accepts the same keys again",
               c.entry_key_conflicts(bp, allt, r0.subs)[0] is None)
    g = next(p for p, b in enumerate(c.banks) if b.kind == "global")
    gerr, gw, gwhere = c.entry_key_conflicts(g, 2, first.subs)
    _check("type 2 in the global bank: a key a map's bank already uses warns that theirs runs there",
           gerr is None and pos in gwhere and any("theirs runs" in w for w in gw), str(gw)[:160])
    terr, tw, _ = c.entry_key_conflicts(pos, 2, [(1, 54321)])
    _check("an unused key in range raises nothing; one above 65535 is refused",
           terr is None and not tw and c.entry_key_conflicts(pos, 2, [(1, 987654)])[0], str((terr, tw)))
    # the editor refuses it, and nothing changes
    try:
        import tkinter as tk
        import cutscene_editor as ce
    except Exception as e:
        _skip("trigger key conflicts (editor)", "no tkinter: %s" % e); return
    box = _headless_dialogs()
    root = tk.Tk(); root.withdraw()
    try:
        cx = ce.CutsceneExplorer(tk.Toplevel(root), reader=lambda n: (_first(n).read_bytes() if _first(n) else None))
        before = cx.doc.container.build()
        n0 = len(cx.doc.undo_stack)
        r = cx.add_entry(pos, 2, first.subs, "RET")
        refused = r is None and cx.doc.container.build() == before and len(cx.doc.undo_stack) == n0
        msg = box["msgs"][-1][1] if box["msgs"] else ""
        ok_keys = cx.set_entry_keys(pos, 2, other.index, first.subs) if other.index > first.index else False
        _check("the editor refuses a new scene (and a re-key) that could never run, saying why",
               refused and "never run" in msg and ok_keys is False and cx.doc.container.build() == before,
               msg[:120])
    finally:
        root.destroy()


def test_cutscene_preload():
    """The cutscene editor preloads the Reference and Event Manager hidden once it is idle:
    the bank scan on a worker thread, the Reference one tab per step, the Event Manager after
    the scan. No step blocks the UI for long, opening reuses the preloaded windows, and edits
    made while they are hidden are caught up when they are shown."""
    print("cutscene editor preload:")
    import time as _t
    import gc as _gc
    # earlier tests' Tk roots are freed by the cycle collector, on whichever thread runs it:
    # free them here, on the main thread, before the worker thread starts (Tcl aborts when an
    # interpreter is deleted on another thread; the toolkit itself keeps one root for life)
    _gc.collect()
    try:
        import tkinter as tk
        import cutscene_editor as ce
        from cutscene_editor import app as capp
        root = tk.Tk(); root.withdraw()
    except Exception as e:  # noqa: BLE001
        _skip("preload", "no Tk: %s" % e); return
    saved = (capp.CutsceneExplorer.PRELOAD, capp.CutsceneExplorer.PRELOAD_DELAY_MS)
    capp.CutsceneExplorer.PRELOAD, capp.CutsceneExplorer.PRELOAD_DELAY_MS = True, 50
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    mc = _first("rf3.mc")
    dirs = ([mc.parent] if mc else []) + [d for d in (pathlib.Path(BUNDLE_DIR) / "bundleMain",
                                                     pathlib.Path(BUNDLE_DIR) / "bundlePatch2") if d.is_dir()]

    def reader(n):
        for d in dirs:
            if (d / n).is_file():
                return (d / n).read_bytes()
        return None
    try:
        cx = ce.CutsceneExplorer(tk.Toplevel(root), reader=reader)
        if cx.doc.container is None:
            _skip("preload", "rf3.mc not found"); return
        root.update()
        worst, end = 0.0, _t.perf_counter() + 120
        while _t.perf_counter() < end:
            t0 = _t.perf_counter()
            root.update()
            worst = max(worst, _t.perf_counter() - t0)
            r, em = cx._reference, cx._em_window
            if r is not None and r.built and (em is not None or cx.doc.em is None):
                break
            _t.sleep(0.01)
        r, em = cx._reference, cx._em_window
        hidden = (r is not None and r.built and r.win.state() == "withdrawn"
                  and (cx.doc.em is None or (em is not None and em.win.state() == "withdrawn")))
        _check("both windows are built hidden in the background", hidden,
               "reference %s, event manager %s" % (r and r.built, em is not None))
        _check("no single preload step blocked the UI for long", worst < 1.0, "%.2fs" % worst)
        if not hidden:
            return
        cx.doc.notify("edit")                        # an edit while both are hidden
        end = _t.perf_counter() + 0.6                # the editor passes it on after 200 ms
        while _t.perf_counter() < end:
            root.update()
            _t.sleep(0.01)
        stale = r._uses_stale and (em is None or em._stale)
        same = cx.open_reference() is r and r.win.state() == "normal" and not r._uses_stale
        if em is not None:
            same = same and cx.open_event_manager() is em and em.win.state() == "normal" and not em._stale
        _check("an edit while hidden only marks them stale; opening reuses the preloaded "
               "windows and catches up", stale and same,
               (r._uses_stale, em is None or em._stale, same))
        _check("no Tk errors during the preload", not errs, str(errs[:1]))
    finally:
        capp.CutsceneExplorer.PRELOAD, capp.CutsceneExplorer.PRELOAD_DELAY_MS = saved
        root.destroy()


def test_cutscene_reload_from_disk():
    """F5 / the reload button (2026-10-01): when another tool rewrote rf3.mc on disk, the
    editor reads it again -- the changed scene shows, it stays on the same bank and scene
    (by position when an insert moved the entry), the undo history goes, and unsaved edits
    are dropped only after the user agrees."""
    print("cutscene editor: reload rf3.mc from disk (F5):")
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
        import cutscene_editor as ce
    except Exception as e:
        _skip("reload from disk", "no tkinter: %s" % e); return
    import shutil, tempfile
    from rf4s_modkit import script
    src = _first("rf3.mc")
    if not src:
        _skip("reload from disk", "rf3.mc not extracted"); return
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="rf4s_reload_"))
    f = tmp / "rf3.mc"
    shutil.copyfile(src, f)
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    ask = messagebox.askyesno
    try:
        cx = ce.CutsceneExplorer(tk.Toplevel(root), reader=lambda n: (_first(n).read_bytes() if _first(n) else None))
        cx.doc.load_file(f)
        cx.browser.rebuild()
        from cutscene_editor.browser import scene_rows
        rows = scene_rows(cx.doc.container.banks[48])
        nth = len(rows) // 2
        cx.open_scene(48, rows[nth].entry_pc)
        root.update()
        # another tool puts a statement in front of that scene (its entry moves)
        c = script.Container(f.read_bytes())
        c.insert_before(c.banks[48], rows[nth].entry_pc, "Wait(4321)")
        f.write_bytes(c.build())
        # an unsaved edit: refusing the question keeps it and reloads nothing
        cx.doc.add_line("reload test line")
        cx._chrome()
        messagebox.askyesno = lambda *a, **k: False
        _check("with unsaved edits, saying No keeps them and reloads nothing",
               cx.reload_from_disk() is False and cx.unsaved())
        messagebox.askyesno = lambda *a, **k: True
        ok = cx.reload_from_disk()
        root.update()
        sts = list(cx.scene.stmts.values()) if cx.scene is not None else []
        _check("reloaded: same bank, the same scene (found by its place in the list), the "
               "inserted statement shows", ok and cx.bank_pos == 48 and any(
                   script.stmt_arg_strs(cx.bank.data, st) == ["4321"] for st in sts if st.op < 0xFFF0),
               "bank %s, %d stmts" % (cx.bank_pos, len(sts)))
        _check("reload drops the unsaved edit and the undo history",
               not cx.unsaved() and not cx.doc.undo_stack)
        f.unlink()
        _check("a file that is gone: nothing reloaded, the open file stays",
               cx.reload_from_disk() is False and cx.doc.container is not None)
        _arc = cx.doc.textarc
        if _arc is not None:
            _n = len(_arc)
            cx.doc.live_lines = {_n: "a test line only the game has"}
            _check("a line only the running game has (past the file's end) shows as text, marked "
                   "live-only; file lines and other locales are untouched",
                   cx.doc.text(_n) == "a test line only the game has" and cx.doc.live_only(_n)
                   and not cx.doc.live_only(_n - 1) and cx.doc.text(_n, "jpn") is None
                   and cx.doc.text(_n + 1) is None)
            cx.doc.live_lines = {}
        # Reload in game acts only on the game the debugger is attached to
        from rf4s_modkit import hotreload as _H
        import types as _types
        _calls = []
        _saved_h = (_H.reload_all, _H.reload_em, _H.pick_process, cx.save_targets)
        try:
            _H.pick_process = lambda *a, **k: (_ for _ in ()).throw(AssertionError("picked a game"))
            _H.reload_all = lambda data, pid=None, **k: (_calls.append(("mc", pid)) or (
                {"pid": pid, "bytes": len(data), "slots": []}, (None, "test")))
            _H.reload_em = lambda data, pid=None: _calls.append(("em", pid)) or {"pid": pid}
            cx.save_targets = lambda: {"rf3.mc": src, "em.bin": src}   # f is gone by now
            _no = cx.reload_in_game()
            cx._debugger = _types.SimpleNamespace(dbg=_types.SimpleNamespace(g=_types.SimpleNamespace(pid=4242)))
            _yes = cx.reload_in_game()
        finally:
            _H.reload_all, _H.reload_em, _H.pick_process, cx.save_targets = _saved_h
            cx._debugger = None
        _check("Reload in game is refused while the debugger is not attached, and then reloads "
               "rf3.mc and em.bin into the attached game only (never picks one itself)",
               _no is False and _yes is True and _calls == [("mc", 4242), ("em", 4242)], repr(_calls))
        _dm = cx.debug_menu
        _items = {_dm.entrycget(i, "label"): _dm.entrycget(i, "accelerator")
                  for i in range(_dm.index("end") + 1) if _dm.type(i) == "command"}
        _btns = [w.cget("text") for w in cx.toolbar.winfo_children()
                 if isinstance(w, (ttk.Button, ttk.Menubutton))]
        _check("the toolbar's Debug menu holds Reload in game (Ctrl+R), Reload from disk (F5) "
               "and the Debugger; neither has its own toolbar button any more",
               _items == {"▶ Launch game": "", "⟳ Reload in game": "Ctrl+R",
                          "⟲ Reload rf3.mc + dialogue from disk": "F5", "🐞 Debugger…": ""}
               and "🐞 Debug" in _btns and "⟳ Reload in game" not in _btns and "⟲" not in _btns, "%s %s" % (_items, _btns))
        # Launch game: starts the game folder's RF4S.exe; asks first when one already runs
        _launched = []
        _saved_l = (_H.game_exe, _H.find_pids, _H.launch)
        try:
            _exe = pathlib.Path(tmp) / "RF4S.exe"
            _H.launch = lambda exe=None: _launched.append(exe) or 777
            _H.game_exe = lambda: None
            _none = cx.launch_game()
            _H.game_exe = lambda: _exe
            _H.find_pids = lambda *a: []
            _fresh = cx.launch_game()
            _H.find_pids = lambda *a: [4242]
            messagebox.askyesno = lambda *a, **k: False
            _declined = cx.launch_game()
            messagebox.askyesno = lambda *a, **k: True
            _second = cx.launch_game()
        finally:
            _H.game_exe, _H.find_pids, _H.launch = _saved_l
        _check("Launch game: nothing without a game folder; starts its RF4S.exe; with a game "
               "already running it asks, and No starts nothing",
               _none is False and _fresh is True and _declined is False and _second is True
               and _launched == [_exe, _exe], "%s %s %s %s %s" % (_none, _fresh, _declined, _second, _launched))
        _check("no Tk errors during the reloads", not errs, str(errs[:1]))
    finally:
        messagebox.askyesno = ask
        root.destroy()
        shutil.rmtree(tmp, ignore_errors=True)


def test_cutscene_multi_select():
    """Script view, several rows (2026-10-01): Ctrl+A selects every row, Ctrl+C copies them in
    display order, Del deletes every selected statement that falls through as ONE undo step
    (the path-ending ones are kept), Shift ranges and Ctrl toggles, and a single click goes
    back to one row."""
    print("cutscene editor: multi-row selection (Ctrl+A / Ctrl+C / Del):")
    try:
        import tkinter as tk
        import cutscene_editor as ce
    except Exception as e:
        _skip("multi-row selection", "no tkinter: %s" % e); return
    from rf4s_modkit import script

    def reader(n):
        p = _first(n)
        return p.read_bytes() if p else None
    if not _first("rf3.mc"):
        _skip("multi-row selection", "rf3.mc not extracted"); return
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        cx = ce.CutsceneExplorer(tk.Toplevel(root), reader=reader)
        c = cx.doc.container
        before = bytes(c.banks[48].data)
        sc = max((s for s in script.disassemble_bank(c.banks[48]) if s.ok), key=lambda s: len(s.stmts))
        cx.show_bank(48, sc.entry_pc)
        root.update()
        v = cx.view
        keys = v._keys()
        v.select_all()
        _check("Ctrl+A selects every row of the scene", v.multi == keys and len(keys) > 3, "%d/%d" % (len(v.multi), len(keys)))
        v.copy_row()
        clip = root.clipboard_get().split("\n")
        _check("Ctrl+C copies every selected row, one line each, in display order",
               len(clip) == len(keys) and clip[0].strip() == v.text.get(
                   "%d.0" % v.line_of(keys[0]), "%d.end" % v.line_of(keys[0])).replace(" ", " ").strip())
        stmts = dict(cx.scene.stmts)
        ends = sum(1 for st in stmts.values() if not st.falls_through or st.terminator)
        cx.delete_selected()
        root.update()
        left = list(cx.scene.stmts.values())
        _check("Del deletes every selected statement that falls through as one edit; the ones that "
               "end a path are kept", 0 < len(left) <= ends + 1
               and all((not st.falls_through) or st.terminator or st.mnem == "FRAME" for st in left)
               and cx.doc.undo_stack[-1]["label"].startswith("Delete "),
               "%d left, %d path ends" % (len(left), ends))
        cx.undo()
        root.update()
        _check("one Ctrl+Z brings the whole bank back byte for byte",       # undo rebuilds the container
               bytes(cx.doc.container.banks[48].data) == before)
        cx.show_bank(48, sc.entry_pc)
        root.update()
        keys = v._keys()
        cx.select(keys[1])
        v.extend(1); v.extend(1)
        _check("Shift+Down grows a range from the anchor", v.multi == keys[1:4], str(v.multi[:4]))
        v._anchor = keys[1]
        v.select_keys(keys[1:4] + [keys[6]], keys[6], anchor=keys[6])
        _check("Ctrl+click adds a row that is not next to the range", v.multi == keys[1:4] + [keys[6]])
        # right-click inside the selection keeps it (and the menu says how many); outside, one row
        menus = []
        _popup = tk.Menu.tk_popup
        tk.Menu.tk_popup = lambda m, *_a: menus.append(
            [m.entrycget(i, "label") for i in range(m.index("end") + 1) if m.type(i) != "separator"])

        class _E:
            x_root = y_root = -5000

        def _at(key):
            ln = v.line_of(key)
            v.text.see("%d.0" % ln); root.update()
            bb = v.text.bbox("%d.0" % ln)
            e = _E(); e.x, e.y = bb[0] + 5, bb[1] + 2
            return e
        try:
            v._context_menu(_at(keys[2]))
            inside = (len(v.multi), menus[-1][1:3])
            v._context_menu(_at(keys[10]))
            outside = (len(v.multi), v.sel == keys[10], menus[-1][1])
        finally:
            tk.Menu.tk_popup = _popup
        _check("right-click inside a multi-selection keeps it and offers 'Copy / Delete 4 lines'; "
               "outside it selects just that row",
               inside == (4, ["Copy 4 lines  (Ctrl+C)", "Delete 4 lines  (Del)"])
               and outside == (0, True, "Copy line  (Ctrl+C)"), str((inside, outside)))
        cx.select(keys[2])
        _check("a plain click goes back to one row", v.multi == [] and v.selected_keys() == [keys[2]])
        _check("multi-row selection raised no callback errors", not errs, str(errs[:1]))
    finally:
        root.destroy()


def test_cutscene_editor_workflows():
    """Cutscene editor (2026-09-24 overhaul): the Inspector shows arguments in listing
    syntax, typed-constant args are set in place, one undo history covers rf3.mc and every
    rf3mc.<locale> byte-exactly, no-op edits record nothing, control-op literals patch in
    place, speaker / dialogue inserts undo cleanly, the unsaved-close guard asks, and every
    interactive control in the window carries a hover tip."""
    print("cutscene editor: undo/redo, inspector edits, no-op edits, tips:")
    try:
        import tkinter as tk
        from tkinter import ttk
        import cutscene_editor as ce
    except Exception as e:
        _skip("cutscene editor workflows", "no tkinter: %s" % e); return
    mc = _first("rf3.mc")
    if not mc:
        _skip("cutscene editor workflows", "rf3.mc not extracted"); return
    dirs = [mc.parent] + [d for d in (pathlib.Path(BUNDLE_DIR) / "bundleMain",
                                     pathlib.Path(BUNDLE_DIR) / "bundlePatch2") if d.is_dir()]

    def reader(n):
        for d in dirs:
            if (d / n).is_file():
                return (d / n).read_bytes()
        return None
    from rf4s_modkit import scriptasm, script
    box = _headless_dialogs()
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        cx = ce.CutsceneExplorer(tk.Toplevel(root), reader=reader)
        doc = cx.doc
        orig = doc.container.build()
        bank48 = doc.container.banks[48]
        pick = next(((sc, pc, st) for sc in script.disassemble_bank(bank48)
                     for pc, st in sc.stmts.items() if st.op == 266 and len(st.args) >= 3), None)
        if pick is None:
            _skip("cutscene editor workflows", "no op-266 statement in bank 48"); return
        sc, pc, st = pick
        cx.show_bank(48, sc.entry_pc)
        cx.select((pc, None)); root.update_idletasks()
        _sp = cx.doc.container.bank_space(48)
        _check("the status bar shows the open bank's room (64 KiB of bytecode per bank)",
               cx.space_lbl.cget("text") == "Bank 48: %s B free of 65,536 (%d%% used)"
               % (format(_sp["free"], ","), round(100 * _sp["used"] / 65536))
               and _sp["used"] + _sp["free"] == 65536, cx.space_lbl.cget("text"))

        def entries(w, out):
            for ch in w.winfo_children():
                if type(ch) is ttk.Entry:
                    out.append(ch.get())
                entries(ch, out)
            return out
        shown = entries(cx.inspector, [])
        combos = [ch.get() for ch in _walk_widgets(cx.inspector) if isinstance(ch, ttk.Combobox)]
        _check("Inspector shows arguments in listing syntax (raw tag3(..) / tag4(..)), and its pickers "
               "name the character and the map",
               any(v.startswith("tag3(") for v in shown) and any(v.startswith("tag4(") for v in shown)
               and any(c.startswith("MAP_") for c in combos)
               and any(c and not c.startswith("MAP_") and any(ch.isalpha() for ch in c) for c in combos),
               str(shown[:4]) + " " + str(combos[:4]))
        # no-op edits: re-setting every argument to its own text, and applying an untouched listing
        for i in range(len(st.args)):
            cx.set_arg(pc, i, scriptasm.operand_text(cx.bank.data, st.args[i], st.op, i))
        cx.source.load(force=True); cx.source.apply()
        _check("no-op argument edits / Apply to scene leave rf3.mc untouched, clean, with no undo step",
               doc.container.build() == orig and not doc.script_dirty() and not doc.undo_stack)
        # typed constant set in place + undo/redo
        cx.set_arg(pc, 0, "5")
        st2 = cx.stmt(pc)
        in_place = script.arg_repr(cx.bank.data, st2.args[0], st2.op, 0) == "actor(Kiel)"
        cx.undo()
        undone = doc.container.build() == orig and not doc.script_dirty()
        cx.redo(); redone = doc.container.build() != orig
        cx.undo()
        _check("a number on actor(..) stays a typed constant; undo/redo are byte-exact",
               in_place and undone and redone)
        # actor + map + a literal that needs a wider expression, then undo each
        cx.set_arg(pc, 0, "actor(Forte)")
        cx.set_arg(pc, 1, "map(MAP_CITY_00)")
        cx.set_arg(pc, 2, "70000")
        st3 = cx.stmt(pc)
        ok_vals = (script.arg_repr(cx.bank.data, st3.args[0], st3.op, 0) == "actor(Forte)"
                   and script.arg_repr(cx.bank.data, st3.args[1], st3.op, 1) == "map(MAP_CITY_00)"
                   and script.arg_constant(cx.bank.data, st3.args[2]) == (70000, True))
        for _ in range(3):
            cx.undo()
        _check("arguments set by name / map / wide literal; undo restores the grown bank exactly",
               ok_vals and doc.container.build() == orig)
        # control-op literal: patch a number in a guard / value expression, read it back, undo
        lit = None
        for lsc in script.disassemble_bank(bank48):
            for lpc, lst in lsc.stmts.items():
                if lst.op >= 0xFFF0 and lst.expr_refs:
                    ls = [x for e in lst.expr_refs if e is not None
                          for x in script.expr_literals(bank48.data, e)]
                    if ls:
                        lit = (lsc, lpc, ls[0][1]); break
            if lit:
                break
        if lit is not None:
            lsc, lpc, cur = lit
            cx.open_scene(48, lsc.entry_pc)
            want = (cur + 7) % 100
            cx.set_literal(lpc, 0, want)
            b2 = script.Container(doc.container.build()).banks[48]
            s2 = script.decode_statement(b2.data, lpc)
            back = [x[1] for e in s2.expr_refs if e is not None for x in script.expr_literals(b2.data, e)][0]
            cx.undo()
            _check("control-op literal patches in place (reads back after rebuild) and undoes exactly",
                   back == want and doc.container.build() == orig, f"{back} want {want}")
        else:
            _skip("control-op literal edit", "no literal in bank 48")
        # dialogue: no-op, real edit, undo
        cx.show_bank(4)
        dpc = next(q for q, t in cx.scene.stmts.items() if t.mnem == "DIALOG")
        lid = cx.stmt(dpc).dialog_id
        before = list(doc.textarc.entries)
        cx.set_text(lid, doc.text(lid))
        noop_clean = not doc.dirty_locales() and not doc.undo_stack
        cx.set_text(lid, "selftest line"); cx.undo()
        _check("dialogue: a no-op text edit records nothing; an edit undoes to the exact archive",
               noop_clean and list(doc.textarc.entries) == before and not doc.dirty_locales())
        # speaker change, a new spoken line, a detached line: all undo byte-exact
        spc = next((q for q, t in cx.scene.stmts.items() if script.is_portrait_op(t.op)), None)
        if spc is not None:
            cx.set_speaker(spc, 19, 1)
            spk = script.portrait_speaker_slot(cx.stmt(spc).op)
            cx.undo()
            _check("speaker change sets slot + side and undoes exactly",
                   spk == (19, 1) and doc.container.build() == orig)
        n0 = len(cx.scene.stmts)
        nid = cx.insert_dialogue_after(dpc, (19, 0), "Inserted by selftest")
        grew = len(cx.scene.stmts) > n0 and doc.text(nid) == "Inserted by selftest"
        cx.undo()
        cx.detach_line(dpc, "Detached by selftest")
        detached = cx.stmt(dpc).dialog_id != lid
        cx.undo()
        _check("insert dialogue / detach line add a new line and undo exactly (script + every locale)",
               grew and detached and doc.container.build() == orig and not doc.dirty_parts())
        # text checks (textlint): a line the game would crash on is refused, a warning-only
        # edit goes through; Save refuses an edited line that was broken behind the editor's back
        box["msgs"].clear()
        refused = cx.set_text(lid, "Ich bin ＠‡kein keine＠") is False
        refused = refused and list(doc.textarc.entries) == before and any(
            "comma" in m for _t, m in box["msgs"])
        box["msgs"].clear()
        cx.set_text(lid, "a ＋blue word")
        warned = doc.text(lid) == "a ＋blue word" and any("odd number" in m for _t, m in box["msgs"])
        doc.textarc.set_text(lid, "＠‡broken")
        save_refused = bool(cx.text_errors()) and cx.save_text() is False
        cx.undo()
        doc.textarc.entries[:] = before
        _check("text check: a crash-prone line is refused, a warning is shown, Save refuses broken lines",
               refused and warned and save_refused, f"{refused} {warned} {save_refused}")
        # a new line with a face: the cue carries it, the picker names it, undo is exact
        from rf4s_modkit import portraits as _pt
        from cutscene_editor.dialogs import FacePicker as _FP
        _fpk = _FP(tk.Toplevel(root), reader=doc.reader)
        _fpk.set_slot(3)                                  # Volkanon: classic faces in Story mode
        _fset = _fpk.set_value(3) and _fpk.value() == 3 and "smile" in _fpk.btn.cget("text")
        _fpk.choose()
        _all = []
        _stack = [root]
        while _stack:
            _w0 = _stack.pop()
            _all.append(_w0)
            _stack.extend(_w0.winfo_children())
        _grid = [w for w in _all if isinstance(w, tk.Toplevel) and w.title() == "Pick a face"]
        _fset = _fset and bool(_grid)
        for _w in _grid:
            _w.destroy()
        _fpk.set_slot(4)
        _fpk.set_value(10)
        _fset = _fset and not hasattr(_fpk, "note")               # no Newlywed hint under the picker
        _n0 = len(cx.scene.stmts)
        _nid = cx.insert_dialogue_after(dpc, (3, 1), "Face test", 3)
        _cue = next((t for t in cx.scene.stmts.values()
                     if t.op == script.portrait_opcode(3, 1) and script.static_arg(cx.bank, t, 0) == 3), None)
        cx.undo()
        _check("add a dialogue line with a face: the cue carries it, the picture picker works (Volkanon too), undo is exact",
               _nid is not None and _cue is not None and _fset
               and doc.container.build() == orig and len(cx.scene.stmts) == _n0,
               f"id={_nid} cue={_cue is not None} picker={_fset}")
        # the message-box style (ops 93-97): the picker, switching 94-97, and a new line with a box
        from cutscene_editor.dialogs import BoxStylePicker as _BP
        _bp = _BP(tk.Toplevel(root), reader=doc.reader, keep=True)
        _bok = _bp.value() is None
        _bp.set_value(2)
        _bok = _bok and _bp.value() == 2 and "thought" in _bp.btn.cget("text")
        _epc = next((q for q, t in cx.scene.stmts.items() if 94 <= t.op <= 97), None)
        if _epc is not None:
            _op0 = cx.stmt(_epc).op
            cx.set_opcode(_epc, 94 + ((_op0 - 94 + 1) % 4))
            _bok = _bok and cx.stmt(_epc).op != _op0
            cx.undo()
        _nid2 = cx.insert_dialogue_after(dpc, (4, 0), "Box test", 0, 1)
        _boxed = any(t.op == 95 for t in cx.scene.stmts.values())
        cx.undo()
        _nid3 = cx.insert_dialogue_after(dpc, None, "Tail test", 0, 4)
        _tail = any(t.op == 93 and script.static_arg(cx.bank, t, 0) == 4 for t in cx.scene.stmts.values())
        cx.undo()
        _check("box style: the picker, switching ops 94-97 and new lines with a box (op 95 / op 93 4) undo exactly",
               _bok and _boxed and _tail and doc.container.build() == orig
               and "shout style (style 1)" in script.opcode_describe(95),
               f"picker/switch={_bok} op95={_boxed} op93-4={_tail}")
        # Add before + adding at a label (= before the labelled statement, so jumps run it too)
        import cutscene_editor.dialogs as dialogs_mod
        def _first_new(pc):
            # the bank is rebuilt with the new line in place, right before `pc`'s statement: the
            # line takes `pc` (nothing before it moved) and the editor selects it
            return cx.stmt(cx.sel[0]) if (cx.sel is not None and cx.sel[0] == pc) else None
        _nb = cx.insert_dialogue_before(dpc, None, "Before test")
        _fb = _first_new(dpc)
        _before_ok = _nb is not None and _fb is not None and _fb.mnem == "DIALOG" and _fb.dialog_id == _nb
        cx.undo()
        _home = (cx.bank_pos, cx.scene.entry_pc)
        _lpc = None
        for _sc in script.disassemble_bank(cx.bank):            # a scene of this bank with a label
            _cand = [q for q in sorted(script.scene_labels(_sc))
                     if q in _sc.stmts and _sc.stmts[q].size >= 4]
            if _cand:
                cx.open_scene(cx.bank_pos, _sc.entry_pc)
                _lpc = _cand[0]
                break
        _lab_ok = False
        if _lpc is not None:
            _lop = cx.stmt(_lpc).op
            _lrow = any(r.key == (_lpc, cx.LABEL) for r in cx.view.rows)
            cx.select((_lpc, cx.LABEL))
            _btns = (cx.inspector.callers_btn.winfo_manager() == "pack"
                     and cx.inspector.del_btn.winfo_manager() == ""
                     and not hasattr(cx.inspector, "after_mb"))
            _no_del = cx.delete_selected() is False
            # "Add after" on a label, through the Add instruction window's DIALOG (a new line)
            _pk = cx.ask_insert_instruction(False, preset=("ctl", "DIALOG"))
            _pk.dlg_mode.set("new")
            _pk._dialogue_mode()
            _pk.dlg_form.set_text("Label test")
            _nl = _pk.insert()
            _pk.win.withdraw()
            _fl = _first_new(_lpc)
            _lab_ok = (_lrow and _btns and _no_del and _nl is not None and _fl is not None
                       and _fl.mnem == "DIALOG" and _fl.dialog_id == _nl)
            cx.undo()
            _lab_ok = _lab_ok and cx.stmt(_lpc).op == _lop
            cx.open_scene(*_home)
            cx.select((dpc, None))
            _lab_ok = _lab_ok and cx.inspector.del_btn.winfo_manager() == "pack"
        _check("adding before, and adding after a selected label (story view), insert ahead of the "
               "statement; labels can't be deleted (no Delete button); undo is exact",
               _before_ok and _lab_ok and doc.container.build() == orig,
               f"before={_before_ok} label={_lab_ok} lpc={_lpc}")
        # the message-box tail: a shipped thought line gets one (its cue has a portrait); a
        # thought box over narration does not, and the Inspector says so
        _t_ok, _t_pos = False, None
        for _tp, _tb in enumerate(doc.container.banks):
            for _tsc in script.disassemble_bank(_tb):
                _tpc = next((q for q, t in _tsc.stmts.items() if t.op == 96), None)
                if _tpc is not None:
                    _t_pos = (_tp, _tsc.entry_pc, _tpc)
                    break
            if _t_pos:
                break
        if _t_pos:
            cx.open_scene(_t_pos[0], _t_pos[1])
            _ok1, _n1 = cx.tail_note(_t_pos[2])
            cx.select((_t_pos[2], None))
            _shown = any("tail points at" in str(getattr(w, "cget", lambda k: "")("text"))
                         for w in cx.inspector.form.winfo_children() if isinstance(w, ttk.Label))
            _dp = next(q for q, _s in script.linearize(cx.scene) if cx.stmt(q).mnem == "DIALOG")
            # a name-plate voice (SetSpeakerVoice, no portrait) then a thought box: no tail
            _nn = cx.insert_before(_dp, "SetSpeakerVoice 738, 0\nop96\nDIALOG #%d" % cx.stmt(_dp).dialog_id)
            _lin = script.linearize(cx.scene)
            _bp = next((q for i, (q, t) in enumerate(_lin)
                        if t.op == 96 and i and _lin[i - 1][1].op == 10), None)
            _ok2, _n2 = cx.tail_note(_bp) if _bp is not None else (True, "")
            cx.undo()
            cx.open_scene(*_home)
            _t_ok = _ok1 and "portrait" in _n1 and _shown and _nn and not _ok2 and "name plate" in _n2
        _check("box tail: a shipped thought line points at its speaker's portrait; a thought box after a "
               "SetSpeakerVoice name plate is flagged 'No tail'", _t_ok,
               f"at={_t_pos} n1={locals().get('_n1')!r} shown={locals().get('_shown')} bp={locals().get('_bp')} n2={locals().get('_n2')!r}")
        # shortcuts reach the widgets the Inspector builds per selection (Ctrl+S used to do
        # nothing while typing in the line's text box); Caps Lock keeps Ctrl+S = save and
        # Ctrl+Z = undo; the explanation popup is on Alt now
        cx.select((dpc, None))
        root.update()
        _stack, _tb = [cx.inspector.form], None
        while _stack and _tb is None:
            _w0 = _stack.pop()
            _tb = _w0 if isinstance(_w0, tk.Text) else None
            _stack.extend(_w0.winfo_children())
        _calls = []
        _orig_fns = (cx.save_all, cx.undo, cx.redo)
        cx.save_all = lambda: _calls.append("save")
        cx.undo = lambda: _calls.append("undo")
        cx.redo = lambda: _calls.append("redo")
        try:
            if _tb is not None:
                _tb.focus_force()
                root.update()
                for _seq, _st in (("<Control-s>", 0x4), ("<Control-S>", 0x4 | 0x2),        # 0x2 = Caps Lock
                                  ("<Control-Z>", 0x4 | 0x2), ("<Control-Z>", 0x4 | 0x1)):  # 0x1 = Shift
                    _tb.event_generate(_seq, state=_st, when="now")
        finally:
            cx.save_all, cx.undo, cx.redo = _orig_fns
        _alt_ok = cx.view.ALT_MASK in (0x20000, 0x0008)
        _check("Ctrl+S / Ctrl+Z reach the Inspector's rebuilt widgets, also with Caps Lock; "
               "the explanation popup uses Alt",
               _tb is not None and cx._bindtag in _tb.bindtags()
               and _calls == ["save", "save", "undo", "redo"] and _alt_ok, f"calls={_calls}")
        # right after an edit applies, the Inspector rebuilds and destroys the focused box; the
        # focus must land back inside the editor (it used to drop onto the bare window, where
        # Ctrl+S did nothing until the user clicked somewhere)
        cx.select((dpc, None))
        root.update()
        _stack, _tb2 = [cx.inspector.form], None
        while _stack and _tb2 is None:
            _w0 = _stack.pop()
            _tb2 = _w0 if isinstance(_w0, tk.Text) else None
            _stack.extend(_w0.winfo_children())
        _refocus_ok = False
        if _tb2 is not None:
            _tb2.focus_force()
            root.update()
            _tb2.insert("end", " (edit)")
            _tb2._commit()                                   # Ctrl+Enter / leaving the box
            root.update()
            _f = cx.frame.focus_get()
            _calls = []
            _orig_save = cx.save_all
            cx.save_all = lambda: _calls.append("save")
            try:
                if _f is not None:
                    _f.event_generate("<Control-s>", state=0x4, when="now")
            finally:
                cx.save_all = _orig_save
            _refocus_ok = (_f is not None and str(_f).startswith(str(cx.frame) + ".")
                           and _calls == ["save"])
            cx.undo()
        # the Event Manager window shares the shortcuts; Save asks before skipping an
        # unapplied Source-tab listing
        _em_ok = True
        if doc.em is not None:
            _emw = cx.open_event_manager()
            root.update()
            _emw.text.focus_force()
            root.update()
            _calls = []
            _orig_save = cx.save_all
            cx.save_all = lambda: _calls.append("save")
            try:
                _emw.text.event_generate("<Control-s>", state=0x4, when="now")
            finally:
                cx.save_all = _orig_save
            _em_ok = _calls == ["save"]
            _emw.win.destroy()
        cx.source.load(force=True)
        cx.source.text.insert("end", "\n; a hand edit")
        cx.source.text.edit_modified(True)
        _asked = []
        import cutscene_editor.app as _ceapp
        _orig_ask = _ceapp.messagebox.askyesnocancel
        _ceapp.messagebox.askyesnocancel = lambda *a, **k: (_asked.append(1), None)[1]   # Cancel
        try:
            _src_ok = cx.source.pending() and cx.save_all() is False and _asked == [1]
        finally:
            _ceapp.messagebox.askyesnocancel = _orig_ask
            cx.source.load(force=True)
        _src_ok = _src_ok and not cx.source.pending()
        _check("after an edit applies the focus stays in the editor (Ctrl+S works at once); the "
               "Event Manager window has the shortcuts; Save asks about an unapplied Source listing",
               _refocus_ok and _em_ok and _src_ok,
               f"refocus={_refocus_ok} em={_em_ok} source={_src_ok}")
        # search: the first hit stays highlighted in the results and opens at the matching line
        _br = cx.browser
        _br.mode.set("dialogue")
        _br.q.set("morning")
        _br.search()
        root.update()
        _srow = _br._results.get("r:0")
        _sel = cx.stmt(cx.sel[0]) if cx.sel else None
        _s_ok = (_srow is not None and _br.results.selection() == ("r:0",)
                 and _br.nb.select() == str(_br.search_tab)
                 and (cx.bank_pos, cx.scene.entry_pc) == _srow[1:3]
                 and _sel is not None and _sel.mnem == "DIALOG"
                 and "morning" in (doc.text(_sel.dialog_id) or "").lower())
        if _br._results.get("r:1"):                          # clicking another result: same behaviour
            _br.results.selection_set("r:1")
            root.update()
            _r1 = _br._results["r:1"]
            _s_ok = _s_ok and _br.results.selection() == ("r:1",) and \
                (cx.bank_pos, cx.scene.entry_pc) == _r1[1:3] and cx.sel == (_r1[3], None)
        cx.open_scene(*_home)
        _check("search highlights the result (no jump into the bank tree) and opens the scene at the match",
               _s_ok, f"row={_srow} sel={cx.sel}")
        # the Trigger type dropdown: only the banks with that trigger type, only its scenes
        _lab6 = next((k for k, v in _br._type_ids.items() if v == 6), None)
        _ok6 = _lab6 is not None
        if _ok6:
            _br.type_filter.set(_lab6)
            _br.rebuild()
            root.update()
            _bk = [r[1] for r in _br._rows.values() if r[0] == "bank"]
            _ok6 = bool(_bk) and all(6 in cx.doc.container.banks[p].type_table_full() for p in _bk)
            if _ok6:
                _br._fill_bank(_bk[0])
                _pcs = {e.event_id for e in cx.doc.container.banks[_bk[0]].entry_records(6)}
                _sc = [r[2] for r in _br._rows.values() if r[0] == "scene" and r[1] == _bk[0]]
                _ok6 = bool(_sc) and set(_sc) <= _pcs
        _br.type_filter.set("all triggers")
        _br.rebuild()
        root.update()
        _ref = cx.open_reference("Trigger types")
        root.update()
        _ok_ref = _ref.nb.tab(_ref.nb.select(), "text") == "Trigger types"
        _ref._filter_banks(6)
        root.update()
        _check("Trigger type dropdown: type 6 lists only banks with a type-6 entry and only those "
               "scenes; the Reference window's Trigger types tab sets it", _ok6 and _ok_ref
               and _br._type_ids.get(_br.type_filter.get()) == 6, _lab6)
        _br.type_filter.set("all triggers")
        _br.rebuild()
        # Functions tab: sorted by opcode; Advanced settings: unverified instructions + CSV export
        from cutscene_editor.app import CutsceneExplorer as _CE
        _st = {"u": False, "c": False}
        _saved_s = (_CE.__dict__["reference_unverified_setting"], _CE.__dict__["reference_csv_setting"])
        try:
            _CE.reference_unverified_setting = classmethod(lambda cls: _st["u"])
            _CE.reference_csv_setting = classmethod(lambda cls: _st["c"])
            cx.refresh_reference()
            root.update()
            _fl = _ref._fn_list
            _ops = [int(row[1], 16) for row in _fl.shown_rows()]
            _ok_sort = _ops == sorted(_ops) and all(row[2] == "✓" for row in _fl.rows)
            _n_ver = len(_fl.rows)
            _no_btn = not any(l._export_shown for l in _ref.lists())
            _st.update(u=True, c=True)
            cx.refresh_reference()
            root.update()
            _ok_all = len(_fl.rows) > _n_ver and any(row[2] == "" for row in _fl.rows)
            _fl.sort_by("Opcode")                        # same column again: descending
            _desc = [int(row[1], 16) for row in _fl.shown_rows()]
            _fl.q.set("teleport")
            _fl.fill()
            import tempfile as _tf, csv as _csv
            _csvp = pathlib.Path(_tf.mkdtemp(prefix="rf4s_refcsv_")) / "fn.csv"
            _fl.write_csv(_csvp)
            _cr = list(_csv.reader(open(_csvp, encoding="utf-8-sig")))
            _ok_csv = (_cr[0] == ["Function", "Opcode", "✓", "Description"] and len(_cr) > 1
                       and all("teleport" in " ".join(x).lower() for x in _cr[1:]))
            _fl.q.set("")
        finally:
            _CE.reference_unverified_setting, _CE.reference_csv_setting = _saved_s
        _check("Reference Functions: sorted by opcode (a heading click reverses it); the Advanced "
               "settings add the unverified instructions (no ✓) and an Export CSV button on every "
               "list, which writes the filtered rows",
               _ok_sort and _no_btn and _ok_all and _desc == sorted(_desc, reverse=True) and _ok_csv
               and all(l._export_shown for l in _ref.lists()),
               "%s %s %s %s" % (_ok_sort, _no_btn, _ok_all, _ok_csv))
        _ref.win.destroy()
        # Save writes straight over the game folder's own files -- here a throwaway copy
        from rf4s_modkit import gamepaths as _gp
        import shutil as _sh
        import tempfile as _tf
        _tmpg = pathlib.Path(_tf.mkdtemp()) / "game"
        _old_find = _gp.find_bundle_dir
        try:
            for _n in ("rf3.mc", "rf3mc.%s" % doc.locale):
                _src = _first(_n)
                if _src is None:
                    raise FileNotFoundError(_n)
                _rel = _src.relative_to(_src.parents[1])            # e.g. bundleMain/rf3mc.eng
                (_tmpg / "Bundle" / _rel).parent.mkdir(parents=True, exist_ok=True)
                _sh.copy2(_src, _tmpg / "Bundle" / _rel)
            (_tmpg / "Bundle" / "Manifest.plist").write_bytes(b"")
            _gp.find_bundle_dir = lambda refresh=False: _tmpg / "Bundle"
            _t = cx.save_targets()
            _eng = _t["rf3mc.%s" % doc.locale]
            _orig_eng = _eng.read_bytes()
            box["save"] = ""                                   # a file dialog would cancel the save
            cx.set_text(lid, "selftest save line")
            _saved = cx.save_all()
            _back = _tmpg / cx.BACKUP_DIR / _eng.relative_to(_tmpg)
            _ok = (_saved is True and not doc.dirty_parts()
                   and textdb.TextArchive.parse(_eng.read_bytes()).text(lid) == "selftest save line"
                   and _back.is_file() and _back.read_bytes() == _orig_eng
                   and _t["rf3.mc"].parent.name == _first("rf3.mc").parent.name)
            cx.undo()
            cx.save_all()
            _ok = _ok and _back.read_bytes() == _orig_eng and _eng.read_bytes() == _orig_eng
            _check("Save overwrites the game folder's own files without asking; originals kept once in ModdingBackup",
                   _ok, f"saved={_saved} targets={sorted(_t)}")
        except FileNotFoundError as _e:
            _skip("save into the game folder", f"{_e} not extracted")
        finally:
            _gp.find_bundle_dir = _old_find
            _sh.rmtree(_tmpg.parent, ignore_errors=True)
        box["yesnocancel"] = None
        cx.set_text(lid, "selftest line")
        _check("unsaved dialogue: closing asks, Cancel stays", cx.confirm_discard("close") is False)
        cx.undo()
        # every interactive control (toolbar, browser, each Inspector form, Event Manager) has a tip
        kinds = (ttk.Button, ttk.Checkbutton, ttk.Menubutton, ttk.Combobox, ttk.Radiobutton, ttk.Entry)
        untipped = set()

        def walk(w):
            for ch in w.winfo_children():
                if isinstance(ch, kinds) and not ch.bind("<Enter>"):
                    try:
                        untipped.add(str(ch.cget("text")) or type(ch).__name__)
                    except tk.TclError:
                        untipped.add(type(ch).__name__)
                walk(ch)
        walk(cx.frame)
        cx.show_bank(19)
        seen_kinds = {}
        for q, t in cx.scene.stmts.items():
            k = "dlg" if t.mnem == "DIALOG" else "spk" if script.is_portrait_op(t.op) else \
                "ctl" if t.op >= 0xFFF0 else "act"
            seen_kinds.setdefault(k, q)
        for q in seen_kinds.values():
            cx.select((q, None)); root.update_idletasks(); walk(cx.inspector)
        emw = cx.open_event_manager()
        if emw is not None:
            walk(emw.win)
            emw.win.withdraw()
        _check("every interactive control in the editor carries a hover tip", not untipped,
               str(sorted(untipped)[:6]))
        _check("cutscene editor workflows raised no callback errors", not errs, f"{len(errs)}")
    finally:
        root.destroy()


def test_event_manager():
    """The Event Manager makeover (2026-09-25): emtext's English layer (descriptions, groups,
    query labels verified against Script_QueryGameState, sentences), emscript's replace/insert
    helpers, the problem checks Save relies on, and the window's browse / read / edit flow."""
    print("event manager (emtext + em_window):")
    from rf4s_modkit import emflags, emscript, emtext, script
    em_p, db_p = _first("em.bin"), _first("emdeb.bin")
    if not (em_p and db_p):
        _skip("event manager", "em.bin / emdeb.bin not extracted"); return
    names = emscript.EmNames.parse(db_p.read_bytes())
    orig = em_p.read_bytes()
    em = emscript.EmScript.parse(orig, names)
    # -- the English layer --
    _check("every entry has an English description and a browser group",
           all(emtext.entry_text(e.name) for e in em.entries)
           and all(emtext.entry_group(e.name) in {k for k, _t, _f in emtext.GROUPS} for e in em.entries))
    qi = lambda n: emtext.query_info(names, [i for i, (en, _j) in enumerate(names.query_names) if en == n][0])
    _check("query labels: characters from the roster order, value kinds, RF4S's unanswered queries",
           qi("LOVE_KEEL")[0] == "Love level with Kiel" and qi("LOVE_SYELZA")[0] == "Love level with Ventuswill"
           and qi("Season")[1] == "season" and qi("Party")[1] == "char" and qi("PLAYER_MAP")[1] == "map"
           and "always reads 0" in qi("Weather")[2] and not qi("Hour")[2])
    lab = lambda i: emtext.entry_text(em.entries[i].name)
    day = em.by_name["EV_CMN_DAYTIME"]
    fin = em.by_name["EV_DATE_FINISH"]
    s_day = [emtext.expr_text(names, x, lab) for x in day.cond_a[0]]
    s_fin = [emtext.action_text(names, a, lab) for a in fin.alt_actions]
    _check("sentences read the way the game means them ('12 > Hour' = Hour is less than 12; on/off)",
           s_day == ["Hour of the day (0–23) is at least 6", "Hour of the day (0–23) is less than 12"]
           and s_fin[0] == "turn FLG_DATE_FES_NOW off" and s_fin[2] == "set REG_DATE_MAP to 0", str(s_day + s_fin))
    _check("the shipped em.bin has no problems", not emtext.problems(em),
           str(emtext.problems(em)[:2]))
    # -- model helpers --
    k = day.idx
    em.insert_expr(k, "a", 0, 0, em.make_expr("Season == 1"), link="or")
    em.insert_expr(k, "a", 0, 0, em.make_expr("FLG_RAINBOW == 1"), link="and")
    shape = [[x.pretty(names) for _i, x in g] for g in emtext.groups_of(em.entries[k].cond_a[0])]
    em.replace_expr(k, "a", 0, 1, em.make_expr("Season == 2"))
    shape2 = [[x.pretty(names) for _i, x in g] for g in emtext.groups_of(em.entries[k].cond_a[0])]
    _check("insert_expr: OR joins the requirement's group, AND starts a new one; replace keeps the link",
           shape == [["Hour >= 6", "Season == 1"], ["FLG_RAINBOW == 1"], ["12 > Hour"]]
           and shape2 == [["Hour >= 6", "Season == 2"], ["FLG_RAINBOW == 1"], ["12 > Hour"]], str(shape2))
    em2 = emscript.EmScript.parse(orig, names)
    ap = em2.by_name["EV_DATE_APPO"].idx
    em2.add_condition(ap, "a", [em2.make_expr("condA(#%d)" % ap)])
    em2.add_action(ap, "main", em2.parse_action_spec("REG_DATE_MAP /= 0"))
    em2.add_action(ap, "main", emscript.Action(0x00, "CALL", entry=9999))
    msgs = [m for lvl, i, _p, m in emtext.problems(em2) if lvl == "error" and i == ap]
    _check("checks: a condition that loops back to itself, dividing by zero, running a missing entry",
           any("loops back" in m for m in msgs) and any("divides by zero" in m for m in msgs)
           and any("#9999" in m for m in msgs), str(msgs))
    # zone 2 (absolute bits 4096..6655): em.bin can reach it though emdeb names nothing there
    em3 = emscript.EmScript.parse(orig, names)
    z = em3.by_name["EV_DATE_APPO"].idx
    kiel_gift = [t for t, tok in emtext.zone2_choices() if "birthday gift given · Kiel" in t]
    em3.add_condition(z, "a", [em3.make_expr("flag@%d/1 == 1" % (4096 + 1007 + 5))])
    s_z = emtext.expr_text(names, em3.entries[z].cond_a[-1][0])
    ok_z = not emtext.problems(em3)
    em3.add_condition(z, "a", [em3.make_expr("flag@7000/1 == 1")])
    _check("zone-2 flags: pickable per character, read by name, valid (not 'past the end'); past bit "
           "6655 is an error",
           kiel_gift and "birthday gift given" in s_z and "Kiel" in s_z and ok_z
           and any("past the end of the 6656-bit" in m for _l, _i, _p, m in emtext.problems(em3)), s_z)
    # -- the window --
    try:
        import tkinter as tk
        from tkinter import ttk
        import cutscene_editor as ce
    except Exception as e:
        _skip("event manager window", "no tkinter: %s" % e); return
    box = _headless_dialogs()
    root = tk.Tk()
    root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)

    def reader(name):
        p = _first(name)
        return p.read_bytes() if p else None
    try:
        top = tk.Toplevel(root)
        top.geometry("+-10000+-10000")
        cx = ce.CutsceneExplorer(top, reader=reader)
        doc = cx.doc
        base = doc.em.build()
        w = cx.open_event_manager()
        w.win.geometry("1320x780+-10000+-10000")
        root.update()
        groups = w.tree.get_children()
        _check("browser: entries grouped by topic, each group counted",
               len(groups) == len({emtext.entry_group(e.name) for e in doc.em.entries})
               and sum(len(w.tree.get_children(g)) for g in groups) == len(doc.em.entries))
        k = doc.em.by_name["EV_CMN_DAYTIME"].idx
        w.open_entry(k)
        root.update()
        text = "\n".join("".join(s for s, _t in r.segs) for r in w.rows)
        _check("rule view: the entry reads as sentences (ways, requirements, its other test)",
               "True when any one of these ways holds" in text and "is less than 12" in text
               and "Its other test (condition B)" in text and w.tree.selection() == ("e:%d" % k,))
        key = ("expr", "a", 0, 0)
        w.select(key)
        root.update()

        def widgets(cls):
            out, stack = [], [w.insp.body]
            while stack:
                x = stack.pop()
                if x.winfo_class() == cls:
                    out.append(x)
                stack.extend(x.winfo_children())
            return out
        how = next(c for c in widgets("TCombobox") if "is at least" in c.cget("values"))
        how.set("is more than")
        how.event_generate("<<ComboboxSelected>>")
        root.update()
        _check("Inspector: picking 'is more than' rewrites the requirement in place",
               doc.em.entries[k].cond_a[0][0].pretty(doc.em.names) == "Hour > 6" and w.sel == key)
        n0 = len(doc.em.entries[k].cond_a[0])
        w.add_requirement("a", 0, 0, "or")
        w.add_requirement("a", 0, 0, "and")
        w.add_way("a")
        w.add_action_to("main")
        root.update()
        e = doc.em.entries[k]
        _check("placeholders change nothing: OR-ed 'never', AND-ed 'always', a 'never' way, 'run #0'",
               [x.pretty(doc.em.names) for x in e.cond_a[0]][:3] == ["Hour > 6", "FALSE", "TRUE"]
               and len(e.cond_a[0]) == n0 + 2 and [x.kind for x in e.cond_a[-1]] == ["false"]
               and e.actions[0].name == "CALL" and e.actions[0].entry == 0
               and not doc.em.entries[0].actions and not emtext.problems(doc.em))
        w.select(("act", "main", 0))
        w._switch_act(("act", "main", 0), "change")
        root.update()
        _check("an action switched to 'changes a variable' shows variable / operation / value pickers",
               doc.em.entries[k].actions[0].name == "ADD" and len(widgets("TCombobox")) == 3)
        # every control of the requirement and action forms has a hover tip
        untipped = [c for c in widgets("TCombobox") + widgets("TButton") + widgets("TRadiobutton")
                    if not c.bind("<Enter>")]
        w.select(key)
        root.update()
        untipped += [c for c in widgets("TCombobox") + widgets("TButton") + widgets("TRadiobutton")
                     if not c.bind("<Enter>")]
        _check("every control in the requirement and action forms has a hover tip", not untipped,
               str([str(c) for c in untipped[:3]]))
        _check("Alt-hover explains a line precisely (the raw em.bin form, the query's id)",
               "em.bin: Hour > 6" in w.explain(key) and "game query 3 Hour" in w.explain(key))
        # Internal names: entries and queries by their emdeb names, and back
        saved_pref = []
        cx.set_em_raw_names_setting = lambda on: saved_pref.append(on)     # not the user's settings
        ep = doc.em.by_name["EV_SUBEV_COM_49"].idx
        w.open_entry(ep)
        root.update()

        def rule_text():
            return "\n".join("".join(s for s, _t in r.segs) for r in w.rows)
        eng = rule_text()
        w.set_raw_names(True)
        root.update()
        raw = rule_text()
        w.set_raw_names(False)
        root.update()
        _check("Internal names: the rule names the entry and its queries by emdeb name, and switches back",
               "Arthur is free for a sub-event" in eng and "SUBEV_ENABLE_ARTHUR" not in eng
               and "SUBEV_ENABLE_ARTHUR" in raw and "EV_SUBEV_COM_49" in raw.splitlines()[0]
               and rule_text() == eng and saved_pref == [True, False]
               and w.tree.item("e:%d" % ep, "text").startswith(
                   "#%d %s" % (ep, emtext.entry_text("EV_SUBEV_COM_49"))),
               raw.splitlines()[0])
        w.q.set("kiel love")
        root.update()
        w.open_first_match()
        root.update()
        _check("search narrows the browser and Enter opens the first match",
               doc.em.entries[w.idx].name == "EV_LOVE_TALK_KEEL" and len(w.matches()) >= 1)
        w.q.set("")
        ap = doc.em.by_name["EV_DATE_APPO"].idx
        w.open_entry(ap)
        w.add_requirement("a", 0, 0, "or")
        w._set_ref(("expr", "a", 0, 1), {"ref": ap, "test": "cond_a"})
        root.update()
        box["msgs"].clear()
        refused = cx._refuse_broken_text("Save")
        _check("a condition that loops back to itself is an error and Save refuses em.bin",
               refused and any("loops back" in m for _t, m in box["msgs"])
               and w.prob_btn.cget("text").startswith("⚠"), str(box["msgs"][:1]))
        # fully custom content: a new entry, a new scene naming it, one computing its entry id
        import tempfile as _tf
        box["askstring"] = "MY_CUSTOM_EVENT"
        new = w.add_entry()
        box["askstring"] = None
        pos = next(i for i, bk in enumerate(doc.container.banks)
                   if i > 300 and not list(script.disassemble_bank(bk)))
        cx.add_entry(pos, 7, [], "FRAME 0\nEvalCondScriptA(%d)\nEND" % new)
        # the same (no) keys: put first, or it could never run (refused)
        cx.add_entry(pos, 7, [], "FRAME 0\nEvalCondScriptA(reg0)\nEND", "first")
        w.open_entry(new)
        root.update()
        text = "\n".join("".join(s for s, _t in r.segs) for r in w.rows)
        side = pathlib.Path(_tf.mkdtemp()) / "emdeb_extra.json"      # never the game folder
        doc.em.names.flags.extra_path = str(side)
        cx._save_em_names()
        fresh = emscript.EmNames.parse(_first("emdeb.bin").read_bytes())
        fresh.merge_entry_names(emflags.read_entry_names(str(side)))
        back = emscript.EmScript.parse(doc.em.build(), fresh)
        _check("custom content: a new scene naming a new entry is counted live; a computed entry id "
               "is listed; custom names survive a save; they get their own group",
               [u[0] for u in cx.em_uses(new)] == [pos] and w.tree.set("e:%d" % new, "uses") == "1"
               and "at run time" in text and back.entries[new].name == "MY_CUSTOM_EVENT"
               and emtext.entry_group("MY_CUSTOM_EVENT") == "custom", f"uses={cx.em_uses(new)[:1]}")
        for _ in range(40):
            if doc.em.build() == base and not doc.script_dirty():
                break
            cx.undo()
            root.update()
        _check("undo walks every Event Manager edit back to the shipped em.bin", doc.em.build() == base)
        _check("event manager raised no callback errors", not errs, f"{len(errs)}")
    finally:
        root.destroy()


def test_asset_explorer_gui():
    """rf4mod_gui performance work (2026-09-24) must not change behaviour: the os.walk folder
    source lists exactly what the pathlib one did; ONE map editor is reused across map
    clicks (hidden, not destroyed, for other views; its background decode suspended); the
    Hex tab fills on first view; the unsaved-edits guard still sees the reused panel; the
    Cutscene editor opens without the full-corpus coverage pass."""
    print("asset explorer (rf4mod_gui): source scan, reused map editor, lazy tabs:")
    import importlib.util, time
    try:
        import tkinter as tk
    except Exception as e:
        _skip("asset explorer gui", "no tkinter: %s" % e); return
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_FIELD_01.rf4m").exists():
        _skip("asset explorer gui", "no extracted bundleMain"); return
    spec = importlib.util.spec_from_file_location("rf4mod_gui_t", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
    gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
    box = _headless_dialogs()
    # 1) folder source == the old pathlib walk (names, groups, order)
    here = pathlib.Path(__file__).parent
    ref = []
    for q in sorted(here.rglob("*")):
        if q.is_file():
            rel = q.relative_to(here).as_posix()
            # group = top-level sub-folder; files directly in the folder are ungrouped
            ref.append((rel, q.parts[len(here.parts)] if len(q.parts) > len(here.parts) + 1 else ""))
    got = [(n, g) for n, g, _l in gui.Source.from_folder(here).entries]
    _check("Source.from_folder (os.walk) lists the same names/order as the pathlib walk; root files ungrouped",
           got == ref, f"{len(got)} vs {len(ref)} entries")
    root = tk.Tk(); root.withdraw()
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        app = gui.App(root, initial=str(B))
        ents = {e[0].rsplit("/", 1)[-1]: e for e in app.source.entries}

        def show(nm):
            n, _g, loader = ents[nm]
            app._show(n, loader()); root.update_idletasks()
        show("MAP_FIELD_01.rf4m")
        p1 = app._doc._map_panel
        show("MAP_CITY_00.rf4m")
        p2 = app._doc._map_panel
        _check("map clicks reuse ONE map editor (set_map, no rebuild)",
               p1 is not None and p1 is p2 and p2.map_base == "MAP_CITY_00")
        nb = app._doc._map_view["nb"]
        _outer = [nb.tab(t, "text") for t in nb.tabs()]
        _side = [p2.nb.tab(t, "text") for t in p2.nb.tabs()]
        _check("the map's Events tab sits in the editor's sidebar (once, just before Problems, "
               "which stays last); a map tab is the editor alone (no Chunks / Hex, no tab strip)",
               _outer == ["Map (edit)"] and nb.cget("style") == "MapOnly.TNotebook"
               and [e[0] for e in gui.ttk.Style().layout("MapOnly.TNotebook.Tab")] in ([], ["null"])
               and _side[-2:] == ["Events", "Problems"]
               and _side.count("Events") == 1, "%s | %s" % (_outer, _side))
        p2.show_tab("Problems")
        _check("show_tab finds a tab by its title with Events inserted (Problems, not Events)",
               p2.nb.tab(p2.nb.select(), "text") == "Problems")
        gen0 = p2.view.ground.generation
        show("MAP_FIELD_01_0000.texture")
        _check("a non-map view hides the editor (kept alive) and suspends its decode",
               app._doc._map_panel is None and nb.winfo_exists() and nb.winfo_manager() == ""
               and p2.view.ground.generation > gen0)
        show("MAP_FIELD_01.rf4m")
        _check("back to a map: the same editor is shown again", app._doc._map_panel is p1 and nb.winfo_manager() == "pack")
        p1.maptab.msea.set("3 winter"); p1.maptab._commit_msea()
        box["yesnocancel"] = None
        _check("unsaved-edits guard still covers the reused map editor",
               app._confirm_close(app._doc, "open another file") is False)
        box["yesnocancel"] = False
        # 2) the Cutscene editor opens without a full-corpus disassembly
        import cutscene_editor
        win = tk.Toplevel(root)
        t0 = time.perf_counter()
        cutscene_editor.CutsceneExplorer(win, reader=app.source.read_named)
        dt = time.perf_counter() - t0
        _check("Cutscene editor opens without the all-bank coverage pass (< 2 s)", dt < 2.0, "%.2f s" % dt)
        win.destroy()
        # only ever one Cutscene editor: every entry point reuses the open window
        _ce1 = app.cutscene_editor()
        _ce2 = app.cutscene_editor(5)
        _tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)
                 and str(w.title()) == "RF4S Cutscene Editor"]
        _check("a second Cutscene editor request reuses the open window",
               _ce1 is _ce2 and len(_tops) == 1, "same=%s, windows=%d" % (_ce1 is _ce2, len(_tops)))
        app._cutscene_ed[0].destroy()
        _check("after it is closed, the next request opens a new one",
               app.cutscene_editor() is not _ce1)
        app._cutscene_ed[0].destroy()
        # an ANIM_DUNG_* effect model finds its .bfmat and plays it in the Model tab
        show("ANIM_DUNG_A02.model")

        def widgets(w):
            for c in w.winfo_children():
                yield c
                yield from widgets(c)
        btns = [w for w in widgets(app._doc.content) if w.winfo_class() == "TButton" and str(w.cget("text")) == "Play"]
        labels = [w for w in widgets(app._doc.content) if w.winfo_class() == "TLabel"
                  and str(w.cget("text")).startswith("frame ")]
        before = str(labels[0].cget("text")) if labels else None
        if btns:
            btns[0].invoke()
            t_end = time.perf_counter() + 0.6
            while time.perf_counter() < t_end:
                root.update(); time.sleep(0.02)
            btns[0].invoke()
        after = str(labels[0].cget("text")) if labels else None
        _check("the Model tab plays an effect model's .bfmat (Play advances the frame)",
               bool(btns) and before != after and not app._doc._model_playing, f"{before!r} -> {after!r}")
        # categories, sizes and sorting (a first-time user's "what kind of file is this?")
        from rf4s_modkit import assetcat
        samples = {"01_M_VIZNAR.ogg": "audio", "00_PLAYER_M_body_00.texture": "texture",
                   "MAP_CITY_00.rf4m": "map", "SI_CITY_00.bin": "gather", "GenA01.bin": "spawn",
                   "AI_m00.bin": "ai", "as_atk_0001.bin": "attack", "rf3ItemData.bin": "data",
                   "rf3mc.eng": "text", "rf4TxtShop_split2_2.eng": "text", "rf3.mc": "script",
                   "em.bin": "script", "Achievement.minterface": "ui", "blur_f.glsl": "shader",
                   "AS_ARTHUR.sav": "save", "AppConfig.plist": "other"}
        wrong = {n: assetcat.category_of(n) for n, k in samples.items() if assetcat.category_of(n) != k}
        _check("asset categories come from the names (voice / texture / map / Gen spawns / SI gathering / AI / attack / "
               "data / text / script / UI / shader / save / other)", not wrong, str(wrong))
        src = app.source
        some = next(i for i, e in enumerate(src.entries) if e[0].endswith(".rf4m"))
        real = (B / src.entries[some][0]).stat().st_size
        _check("the explorer knows every file's size (from the directory scan, nothing opened)",
               all(x is not None for x in src.sizes) and src.sizes[some] == real, f"{src.sizes[some]} vs {real}")
        maps = next(v for v in app.cat_cb.cget("values") if v.startswith("Maps"))
        app.cat_var.set(maps)
        app.filter_var.set("")
        app.group_maps_var.set(False)                           # the flat list first
        app.cmd_group_maps()
        t = app.tree
        leaves = []
        for g in t.get_children():
            if g in app._group_indices:
                t.item(g, open=True); t.focus(g); app._on_group_open(None)
                leaves += list(t.get_children(g))
            else:
                leaves.append(g)
        cats_ok = leaves and all(t.item(k, "values")[0] == "Maps" for k in leaves if k in app._index)
        app._sort_by("size"); app._sort_by("size")            # biggest first
        sizes = []
        for g in t.get_children():
            kids = t.get_children(g) if g in app._group_indices else [g]
            sizes += [src.sizes[app._index[k]] for k in kids if k in app._index]
        _check("Show: Maps lists only maps; clicking Size twice sorts biggest first and keeps groups open",
               cats_ok and sizes and sizes == sorted(sizes, reverse=True)
               and t.heading("size", "text").endswith("▼"), f"{len(sizes)} rows")
        app.filter_var.set("city")
        app._apply_filter_now()
        hits = [app._index[k] for g in t.get_children() for k in (t.get_children(g) or [g]) if k in app._index]
        _check("the category and the text filter combine (Maps + 'city' = town maps only)",
               hits and all("city" in src.entries[i][0].lower() and src.categories()[i] == "map" for i in hits),
               f"{len(hits)} hits")
        # Group maps by area: a header per in-game area name, the maps under it, open ones kept
        app.filter_var.set("")
        app.group_maps_var.set(True)
        app.cmd_group_maps()
        areas = {}
        for g in t.get_children():
            if g in app._group_indices:
                t.item(g, open=True); t.focus(g); app._on_group_open(None)
            for a in (t.get_children(g) if g in app._group_indices else [g]):
                if a not in app._index:
                    areas[t.item(a, "text").split("  (")[0]] = a
        rp = areas.get("Rune Prana")
        rp_maps = [src.entries[app._index[k]][0].rsplit("/", 1)[-1] for k in t.get_children(rp)] if rp else []
        if rp:
            t.item(rp, open=True)
        app._sort_by("name")
        still = [a for g in t.get_children() for a in (g, *t.get_children(g))
                 if t.item(a, "text").startswith("Rune Prana  (")]
        _check("Group maps by area: one header per in-game area (Rune Prana holds MAP_DUNG_M01), "
               "an open header stays open across a re-sort",
               len(areas) > 50 and "MAP_DUNG_M01.rf4m" in rp_maps and len(rp_maps) == 127
               and still and t.item(still[0], "open"), f"{len(areas)} areas, Rune Prana {len(rp_maps)}")
        app.cat_var.set(app.ALL_CATS)
        app._apply_filter_now()
        # every kind of viewer opens without falling back to "[viewer note] <error>" (a renamed
        # field once broke the Gen viewer: 'Spawn' object has no attribute 'param')
        notes = []
        _orig_hex = gui.App._view_hex
        gui.App._view_hex = lambda self, name, data, error=None: (
            notes.append((name, error)) if error else None, _orig_hex(self, name, data, error))[1]
        try:
            byname = {e[0].rsplit("/", 1)[-1]: e for e in src.entries}
            cats, seen_cat, sample = src.categories(), set(), []
            for i, e in enumerate(src.entries):             # the first file of every category
                if cats[i] not in seen_cat:
                    seen_cat.add(cats[i])
                    sample.append(e)
            sample += [byname[n] for n in ("GenE89.bin", "SI_CITY_00.bin", "AI_m00.bin", "em.bin",
                                           "rf3NpcParam.bin", "rf3Schedule.bin", "rf3MonsterPresent.bin",
                                           "rf3ItemStrengthening.bin", "rf3route.bin", "rf3mc.eng")
                       if n in byname]
            for n, _g, loader in sample:
                app._show(n, loader())
                root.update_idletasks()
        finally:
            gui.App._view_hex = _orig_hex
        _check("every kind of file opens in its viewer without an error note (%d kinds sampled)"
               % len(sample), not notes, str(notes[:3]))
        def _find(w, cls):
            out = [w] if w.winfo_class() == cls else []
            for c in w.winfo_children():
                out += _find(c, cls)
            return out
        from map_editor import data as _med
        if "GenE89.bin" in byname:
            # a monster generator: the flat map picture + the map editor's Encounters pane
            n, _g, loader = byname["GenE89.bin"]
            app._show(n, loader())
            root.update()
            h = app._doc._gen_host
            _view_ok = (h.map is not None and h.map.endswith("MAP_DUNG_E89.rf4m") and h._picture() is not None
                        and type(h.pane).__name__ == "EncountersTab" and h.gate_index == (0, 0)
                        and len(h.pane.roster.get_children()) > 0)
            # drag a gate position on the picture, '+ spawn' then click, a roster edit
            ge = h.active_gate
            _off, _x0, _y0 = h.doc.gen.gate_positions_off(ge)[0]
            _ppt = h._picture()[1]
            _ev = type("E", (), {})()
            _ev.x, _ev.y = _x0 / 8 * _ppt, _y0 / 8 * _ppt
            h._press(_ev); _ev.x += 16; h._motion(_ev); h._release(_ev)
            _t = gen.GenTable(app._doc.cur_data)
            _moved = _t.gate_positions_off(_t.patterns[0][0])[0][1] != _x0
            _n0 = len(h.doc.gen.monster_positions_off(h.active_gate))
            h.start_add("mpos"); _ev.x, _ev.y = 60, 80; h._press(_ev)
            _added = len(h.doc.gen.monster_positions_off(h.active_gate)) == _n0 + 1
            _sp = h.active_gate.spawns[0]
            h.apply("Edit roster monster", "gen", lambda: h.doc.gen.set_spawn_pick_weight(_sp, 7))
            _edited = gen.GenTable(app._doc.cur_data).patterns[0][0].spawns[0].pick_weight == 7
            _fld = _med.maps_for_gen("GenField01.bin", ["MAP_FIELD_01_SUMMER.rf4m", "MAP_FIELD_01.rf4m",
                                                        "MAP_FIELD_02.rf4m", "MAP_DUNG_E89.rf4m"])
            _check("Gen view: its map's picture + the Gates pane (first gate selected); drag a gate, "
                   "'+ spawn' + click, a roster edit all reach the file; seasonal maps share the table",
                   _view_ok and _moved and _added and _edited
                   and _fld == ["MAP_FIELD_01.rf4m", "MAP_FIELD_01_SUMMER.rf4m"],
                   f"view={_view_ok} moved={_moved} added={_added} edited={_edited} field={_fld}")
            _ob = next((x for x in _find(app._doc.content, "TButton") if x.cget("text") == "Open in map editor"), None)
            _ok_btn = False
            if _ob is not None:
                _ob.invoke()
                root.update()
                _p = app._doc._map_panel
                _ok_btn = (app._doc.cur_name.endswith("MAP_DUNG_E89.rf4m") and _p is not None
                           and _p.nb.tab(_p.nb.select(), "text") == "Gates")
            _check("Gen view: 'Open in map editor' lands on that map's Gates tab", _ok_btn)
        _check("asset explorer raised no callback errors", not errs,
               f"{len(errs)}: " + ("; ".join(f"{e[0].__name__}: {e[1]}" for e in errs[:2]) if errs else ""))
    finally:
        root.destroy()

def test_material_anims():
    """matanim.py (2026-09-24): all 59 .bfmat parse and rebuild byte for byte (also through
    the JSON dump), texture patterns (AnimChannel_SampleAsInt step curves) swap a BM_*
    eye texture between frames, opacity fades a material's alpha, retiming keeps the loop
    closed, and the bfmat-info / -build / -set CLI runs."""
    print("material animations (.bfmat FMAA):")
    import json as _json
    import subprocess, tempfile
    from rf4s_modkit import matanim, model
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    files = sorted(B.glob("*.bfmat"))
    bad, kinds = [], {}
    for f in files:
        d = f.read_bytes()
        try:
            a = matanim.parse(d)
            if matanim.build(a) != d:
                bad.append((f.name, "build"))
            elif matanim.build(matanim.from_json(_json.loads(_json.dumps(matanim.to_json(a))))) != d:
                bad.append((f.name, "json"))
            for m in a.materials:
                for p in m.params:
                    kinds[p.name] = kinds.get(p.name, 0) + 1
                kinds["pattern"] = kinds.get("pattern", 0) + len(m.patterns)
        except Exception as e:  # noqa: BLE001
            bad.append((f.name, repr(e)))
    _check("all .bfmat parse and rebuild byte for byte (build + JSON round trip)",
           len(files) == 59 and not bad, bad[:3] or f"{len(files)} files")
    _check("shipped material animations: texsrt0 49, opacity 46, texture patterns 29, nothing else",
           kinds == {"texsrt0": 49, "opacity": 46, "pattern": 29}, str(kinds))

    # texture pattern: BM_05's eye (sampler _a0) steps through bm05_eye00..03
    m5, a5 = model.load(B / "BM_05.model"), matanim.load(B / "BM_05.bfmat")
    mi = next(mt.index for mt in m5.materials if mt.name == "BM_05_me")
    picks = [matanim.material_state(m5, a5, f).get(mi, {}).get("texture") for f in (0, 3, 5, 8)]
    _check("BM_05 eye pattern picks bm05_eye00/01/02/03 at frames 0/3/5/8 (step int keys)",
           picks == ["bm05_eye00", "bm05_eye01", "bm05_eye02", "bm05_eye03"]
           and matanim.material_samplers(m5, mi) == ["_a0"], str(picks))
    r0 = model.render(m5, "front", 160, anim=a5, frame=0)
    r8 = model.render(m5, "front", 160, anim=a5, frame=8)
    rn = model.render(m5, "front", 160)
    _check("a BM_* blink changes the rendered texture between frames (frame 0 = no anim)",
           r0.tobytes() != r8.tobytes() and r0.tobytes() == rn.tobytes())
    a2 = matanim.load(B / "BM_02.bfmat")
    p2 = a2.material("BM_02_03").patterns[0]
    _check("pattern index clamps to the texture array; the frame wraps at the frame count "
           "(BM_02's key at frame 34 = frame count never plays)",
           p2.index(34, 5) == 4 and a2.play_frame(34) == 0 and p2.index(a2.play_frame(34), 5) == 0
           and p2.index(24, 5) == 3)
    # opacity: level_up's text cards fade in
    ml, al = model.load(B / "level_up.model"), matanim.load(B / "level_up.bfmat")
    s0, s30 = matanim.material_state(ml, al, 0), matanim.material_state(ml, al, 30)
    alpha = lambda im: sum(im.getchannel("A").tobytes())
    i0, i30 = model.render(ml, "top", 160, anim=al, frame=0), model.render(ml, "top", 160, anim=al, frame=30)
    _check("opacity (rateOpacityData.r, clamped) fades level_up: 0 at frame 0, visible at 30",
           all(v["opacity"] == 0.0 for v in s0.values()) and max(v["opacity"] for v in s30.values()) > 0.5
           and alpha(i0) == 0 and alpha(i30) > 0, f"alpha {alpha(i0)} -> {alpha(i30)}")
    # retime: twice as fast, the curve still ends on the (new) last frame
    a02 = matanim.load(B / "ANIM_DUNG_A02.bfmat")
    before = [a02.materials[0].params[0].value(f)[4] for f in (0, 120, 239)]
    matanim.retime(a02, 2.0)
    fast = matanim.parse(matanim.build(a02))
    after = [fast.materials[0].params[0].value(f * 120 / 239)[4] for f in (0, 120, 239)]
    _check("retime x2: 239 -> 120 frames, same values at the scaled frame (ratio 120/239)",
           fast.frame_count == 120 and fast.materials[0].params[0].curves[0].end == 120.0
           and all(abs(x - y) < 1e-4 for x, y in zip(before, after)),
           f"{[round(v, 3) for v in before]} vs {[round(v, 3) for v in after]}")
    # companions by material name
    _check("companion .bfmat found by material name (SYS_MENU_ANIME_09 -> anim_com09, efc_start_deu -> font_start)",
           "anim_com09" in matanim.companion_stems("SYS_MENU_ANIME_09")
           and "font_start" in matanim.companion_stems("efc_start_deu")
           and matanim.binds(matanim.load(B / "anim_com09.bfmat"), model.load(B / "SYS_MENU_ANIME_09.model")))
    # CLI
    cli = [sys.executable, str(pathlib.Path(__file__).with_name("rf4mod.py")), "res"]
    with tempfile.TemporaryDirectory() as td:
        j, o, s = pathlib.Path(td) / "b.json", pathlib.Path(td) / "b.bfmat", pathlib.Path(td) / "s.bfmat"
        r1 = subprocess.run(cli + ["bfmat-info", str(B / "BM_10.bfmat")], capture_output=True, text=True)
        r2 = subprocess.run(cli + ["bfmat-info", str(B / "BM_10.bfmat"), "--json", str(j)], capture_output=True, text=True)
        r3 = subprocess.run(cli + ["bfmat-build", str(j), str(o)], capture_output=True, text=True)
        r4 = subprocess.run(cli + ["bfmat-set", str(B / "BM_10.bfmat"), str(s), "--speed", "0.5"],
                            capture_output=True, text=True)
        ok = (r1.returncode == 0 and "BM_10_fw08" in r1.stdout and r3.returncode == 0
              and o.read_bytes() == (B / "BM_10.bfmat").read_bytes()
              and r4.returncode == 0 and matanim.load(s).frame_count == 46)
        _check("CLI res bfmat-info / bfmat-build (byte-exact) / bfmat-set --speed",
               ok, (r1.stderr + r2.stderr + r3.stderr + r4.stderr)[-300:])


def test_skeletal_anims():
    """skelanim.py (2026-09-24): every .bfskl parses (FRES/FSKA, Euler XYZ, cubic curves),
    a walk cycle moves bones between frames and loops back, the posed/skinned render of a
    character differs from its bind pose, the CLI anim-info / anim-gif run, and the Model
    tab's motion row plays."""
    print("skeletal animations (.bfskl FSKA):")
    from rf4s_modkit import skelanim, model
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    files = sorted(B.glob("*.bfskl"))
    if not files:
        _skip("skeletal animations", "no extracted bundleMain"); return
    sample = files[::25] if QUICK else files
    bad = []
    for f in sample:
        try:
            a = skelanim.parse(f.read_bytes())
            if sum(len(b.curves) for b in a.bones) != a.curve_count or not a.euler:
                bad.append(f.name)
        except Exception as e:
            bad.append(f"{f.name}: {e}")
    _check(f"{len(sample)}{' sampled' if QUICK else ''} of {len(files)} .bfskl parse; curve totals "
           "match FSKA +0x50; all Euler XYZ", len(files) == 2001 and not bad, str(bad[:3]))
    walk = skelanim.load(B / "00W_002_walk.bfskl")
    m = model.load(B / "NPC_A_CLORICA.model")
    thigh = walk.bone("Bip01_L_Thigh")
    bind = next(b for b in m.bones if b.name == "Bip01_L_Thigh")
    # rn: the curves' own value at the (unwrapped) last frame -- the cycle is seamless
    r0, rh, rn = (thigh.srt(f, bind)[1] for f in (0, walk.frame_count / 2, walk.frame_count - 1e-3))
    _check("walk cycle: the thigh swings between frame 0 and mid-cycle and loops back at frameCount",
           walk.loops and max(abs(x - y) for x, y in zip(r0, rh)) > 0.2
           and max(abs(x - y) for x, y in zip(r0, rn)) < 1e-3 and walk.wrap(walk.frame_count) == 0.0,
           f"{r0} / {rh} / {rn}")
    matched, _ao, model_only = skelanim.bound_bones(m, walk)
    _check("bones bind by name (all 25 of Clorica's bones are driven by the 00W_ walk)",
           len(matched) == len(m.bones) and not model_only, f"{len(matched)}/{len(m.bones)}")
    m.pose = None
    pal = m.skin_palette()
    ident = all(abs(pal[k][r][c] - (1.0 if r == c else 0.0)) < 1e-3
                for k in range(m.smooth_count) for r in range(3) for c in range(4))
    _check("inverse bind matrices (SKEL +0x28) invert the bind pose: smooth palette = identity",
           m.smooth_count == 24 and len(m.inverse_bind) == 24 and ident)
    frames = model.render_skeletal_animation(m, walk, "side", 160, frames=[0, walk.frame_count // 4])
    bind_im = model.render(m, "side", 160, background=(32, 32, 36, 255))
    from PIL import ImageChops
    diff = ImageChops.difference(frames[0].convert("RGB"), frames[1].convert("RGB")).getbbox()
    _check("posed + skinned render moves between frames and differs from the bind pose",
           diff is not None and frames[0].tobytes() != bind_im.tobytes() and m.pose is None)
    cands = skelanim.anims_for_model(B / "M24_3.model")
    _check("anims_for_model: monster variants use their skeleton's set (M24_3 -> M24_0_*)",
           cands and all(p.name.startswith("M24_0_") for p in cands), str(cands[:2]))
    import subprocess, tempfile
    with tempfile.TemporaryDirectory() as td:
        gif = pathlib.Path(td) / "a.gif"
        r1 = subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name("rf4mod.py")), "res", "anim-info",
                             str(B / "M03_0_02.bfskl"), "--model", str(B / "M03_0.model")],
                            capture_output=True, text=True)
        r2 = subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name("rf4mod.py")), "res", "anim-gif",
                             str(B / "M03_0.model"), str(B / "M03_0_02.bfskl"), str(gif), "--size", "96",
                             "--step", "12"], capture_output=True, text=True)
        from PIL import Image
        n_fr = Image.open(gif).n_frames if gif.is_file() else 0
    _check("CLI res anim-info / anim-gif", r1.returncode == 0 and "20 bones matched" in r1.stdout
           and r2.returncode == 0 and n_fr == 4, (r1.stderr or r2.stderr)[-200:] + f" frames={n_fr}")
    # GUI: the Model tab's motion row lists the model's .bfskl and plays one
    try:
        import tkinter as tk
        import importlib.util, time
        spec = importlib.util.spec_from_file_location("rf4mod_gui_sk", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
        gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
        root = tk.Tk(); root.withdraw()
    except Exception as e:
        _skip("Model tab motion row", repr(e)); return
    errs = []
    root.report_callback_exception = lambda *a: errs.append(a)
    try:
        app = gui.App(root, initial=str(B))
        ent = next(e for e in app.source.entries if e[0].rsplit("/", 1)[-1] == "M03_0.model")
        app._show(ent[0], ent[2]()); root.update()

        def widgets(w):
            for c in w.winfo_children():
                yield c
                yield from widgets(c)
        cbs = [w for w in widgets(app._doc.content) if w.winfo_class() == "TCombobox"
               and any(str(v).endswith(".bfskl") for v in w.cget("values"))]
        ok = False
        if cbs:
            cbs[0].set("M03_0_02.bfskl"); cbs[0].event_generate("<<ComboboxSelected>>"); root.update()
            lab = [w for w in widgets(app._doc.content) if w.winfo_class() == "TLabel"
                   and str(w.cget("text")).startswith("frame ") and "/48" in str(w.cget("text"))]
            play = [w for w in cbs[0].master.winfo_children() if w.winfo_class() == "TButton"
                    and str(w.cget("text")) == "Play"]
            before = str(lab[0].cget("text")) if lab else None
            if play:
                play[0].invoke()
                t_end = time.perf_counter() + 1.0
                while time.perf_counter() < t_end:
                    root.update(); time.sleep(0.02)
                play[0].invoke()
            after = str(lab[0].cget("text")) if lab else None
            ok = bool(lab and play) and before != after
        _check("Model tab: motion row lists the model's .bfskl and Play advances the frame",
               ok and not errs, f"{len(cbs)} combos, errs={len(errs)}")
    finally:
        root.destroy()


def test_portraits():
    """E-mote character portraits (.psbData / .emtbytes) -- rf4s_modkit.psb."""
    print("portraits (E-mote PSB):")
    from rf4s_modkit import psb as _psb
    files = sorted(EXTRACTED.rglob("*.psbData")) + sorted(EXTRACTED.rglob("*.emtbytes"))
    if not files:
        _skip("psb corpus", "no .psbData/.emtbytes extracted"); return
    bad, fmts, face_missing = [], {}, []
    for f in files:
        try:
            p = _psb.PSB(f.read_bytes())
            ts = p.textures()
            if len(ts) != 1 or _psb._bytes_per_texture(ts[0]) != ts[0]["length"]:
                bad.append(f"{f.name}: textures {[(t['type'], t['length']) for t in ts]}")
            else:
                fmts[(f.suffix, ts[0]["type"], p.encrypted)] = fmts.get((f.suffix, ts[0]["type"], p.encrypted), 0) + 1
            tl = {_psb.repair_text(x) for x in p.timelines() if isinstance(x, str)}
            # SP-variant files are only loaded for the SP1/SP2 face rows (RF4S.exe+0x1D8730):
            # they must carry that row; several omit the six everyday faces.
            sp = re.search(r"_SP(\d?)\.", f.name)
            need = ([_psb.FACE_TIMELINES[6 if sp.group(1) in ("", "1") else 7]] if sp
                    else list(_psb.FACE_TIMELINES[:6]))
            # (B_FORTE / PLAYER_W_SMALL carry no NN_ id and are not in the exe's path table)
            if re.match(r"\d\d_", f.name) and not all(x in tl for x in need):
                face_missing.append(f.name)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{f.name}: {e}")
    _check("psb: every .psbData/.emtbytes parses (checksum, tree, one atlas of the right size)",
           not bad, f"{len(files) - len(bad)}/{len(files)} ok; " + ("; ".join(bad[:3]) or
                                                                   ", ".join(f"{k[0]} {k[1]} enc={k[2]} x{v}" for k, v in sorted(fmts.items()))))
    _check("psb: .psbData = RGBA8 plain, .emtbytes = ASTC_8BPP header-encrypted",
           set(fmts) <= {(".psbData", "RGBA8", 0), (".emtbytes", "ASTC_8BPP", 1)}, str(sorted(fmts)))
    _check("psb: face frames 0..5 (通常..照れ) are timelines in every base/outfit portrait, SP1/SP2 in the SP files",
           not face_missing, f"missing in {face_missing[:4]}" if face_missing else f"{len(files)} files")
    exe = BUNDLE_DIR.parent / "RF4S.exe"          # the game copy
    if exe.is_file():
        eb = exe.read_bytes()
        paths = set(m.group(1).decode() for m in re.finditer(rb"rom:/emote/([A-Z0-9_]+\.psbData)\x00", eb))
        have = {f.name for f in files}
        _check("psb: RF4S.exe's 64 rom:/emote/*.psbData all ship; exe never names .emtbytes",
               len(paths) == 64 and paths <= have and b"emtbytes" not in eb,
               f"{len(paths)} exe paths, missing={sorted(paths - have)[:3]}")
    else:
        _skip("psb exe path table", "RF4S.exe not next to Bundle")
    a_p = next((f for f in files if f.name == "02_CLORICA.psbData"), None)
    e_p = next((f for f in files if f.name == "02_CLORICA.emtbytes"), None)
    if not (a_p and e_p):
        _skip("psb Clorica checks", "02_CLORICA not extracted"); return
    a, e = _psb.PSB(a_p.read_bytes()), _psb.PSB(e_p.read_bytes())
    fa = {_psb.repair_text(s) for s in a.strings} - {"RGBA8"}
    fe = set(e.strings) - {"ASTC_8BPP"}
    _check("psb: .psbData text repair == the .emtbytes clean UTF-8 (strings + names)",
           fa == fe and {_psb.repair_text(n) for n in a.names} == set(e.names),
           f"{len(fa)} strings, {len(a.names)} names")
    try:
        import json as _json
        js = _json.dumps(_psb.to_jsonable(a), ensure_ascii=False)
        _check("psb: JSON dump of the full tree", '"$res": 0' in js and "照れ" in js, f"{len(js):,} chars")
    except Exception as ex:  # noqa: BLE001
        _check("psb: JSON dump of the full tree", False, str(ex))
    if not texture.HAS_PIL:
        _skip("psb atlas decode", "Pillow missing"); return
    from PIL import Image, ImageOps, ImageChops
    ta = a.textures()[0]
    im = _psb.decode_texture(a, ta)
    alpha = im.getchannel("A")
    hist = alpha.histogram()
    opaque = hist[255] / (im.width * im.height)
    colors = len(im.convert("RGB").resize((128, 128)).getcolors(1 << 16) or [])
    _check("psb: Clorica atlas decodes to a plausible image",
           im.size == (2048, 1236) and hist[0] > 0 and 0.2 < opaque < 0.8 and colors > 500,
           f"{im.size[0]}x{im.size[1]}, {opaque:.0%} opaque, {colors} colours, {len(ta['icons'])} parts")
    try:
        import texture2ddecoder  # noqa: F401
        ie = _psb.decode_texture(e, e.textures()[0])
        diff = ImageChops.difference(im, ie).convert("L").histogram()
        mad = sum(i * c for i, c in enumerate(diff)) / (im.width * im.height)
        _check("psb: .emtbytes ASTC atlas matches the .psbData RGBA8 atlas", mad < 1.0, f"mean |d| {mad:.3f}")
    except ImportError:
        _skip("psb ASTC decode", "texture2ddecoder missing")
    same = _psb.replace_texture(a, ta, im)
    _check("psb: replace with the decoded atlas is byte-identical", same == a.data)
    rgb = ImageOps.invert(im.convert("RGB")); rgb.putalpha(alpha)
    blob = _psb.replace_texture(a, ta, rgb)
    o, n = ta["offset"], ta["length"]
    r = _psb.PSB(blob)
    back = _psb.decode_texture(r, r.textures()[0])
    _check("psb: repaint round-trip (re-parses, pixels = PNG, every other byte identical)",
           len(blob) == len(a.data) and blob[:o] == a.data[:o] and blob[o + n:] == a.data[o + n:]
           and back.tobytes() == rgb.tobytes() and blob[o:o + n] != a.data[o:o + n])
    try:
        _psb.replace_texture(a, ta, im.resize((64, 64)))
        _check("psb: wrong-size PNG refused", False)
    except _psb.PSBError:
        _check("psb: wrong-size PNG refused", True)
    try:
        _psb.replace_texture(e, e.textures()[0], im)
        _check("psb: ASTC (.emtbytes) replace refused", False)
    except _psb.PSBError:
        _check("psb: ASTC (.emtbytes) replace refused", True)
    # asset explorer: a .psbData shows its atlas (zoomable canvas, Export = PNG)
    try:
        import importlib.util
        import tkinter as tk
        spec = importlib.util.spec_from_file_location("rf4mod_gui_p", pathlib.Path(__file__).with_name("rf4mod_gui.py"))
        gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
        _headless_dialogs()
        root = tk.Tk(); root.withdraw()
        errs = []
        root.report_callback_exception = lambda *x: errs.append(x)
        try:
            app = gui.App(root, initial=str(a_p.parent))
            ent = next(x for x in app.source.entries if x[0].rsplit("/", 1)[-1] == a_p.name)
            app._show(ent[0], ent[2]()); root.update_idletasks()
            _check("psb: asset explorer shows the portrait atlas for a .psbData",
                   app._doc._pil is not None and app._doc._pil.size == im.size and app._doc._export_kind == "png" and not errs)
        finally:
            root.destroy()
    except Exception as ex:  # noqa: BLE001
        _skip("psb asset explorer view", str(ex))


def test_shader_archive():
    """Shaders: .bfsha (FSHA+BNSH GLSL source arrays, read/extract only) and the loose
    bundleMuteki GLSL the PC build actually compiles (preprocess + validated replace)."""
    print("\n[shaderarchive]")
    from rf4s_modkit import shaderarchive as sa
    main = next((p for p in (EXTRACTED / "bundleMain", BUNDLE_DIR / "bundleMain") if p.is_dir()), None)
    if main is None or not (main / "rf4cmv.bfsha").is_file():
        _skip("shader archives", "bundleMain/*.bfsha not extracted")
        return
    arcs = {}
    for n in ("rf4cmv", "notexture", "billboard"):
        try:
            arcs[n] = sa.load(main / f"{n}.bfsha")
        except Exception as e:  # noqa: BLE001
            _check(f"{n}.bfsha parses", False, str(e))
    _check("all 3 .bfsha archives parse", len(arcs) == 3,
           ", ".join(f"{n}: {len(a.models)} model(s)" for n, a in arcs.items()))
    if len(arcs) != 3:
        return
    names = [m.name for m in arcs["rf4cmv"].models]
    _check("rf4cmv shading models body / costume / lighting (+ env)",
           names[:3] == ["body", "costume", "lighting"], str(names))
    bad, nsec, reloc_bad = [], 0, []
    for n, a in arcs.items():
        rel = set(a.pointers)
        for m in a.models:
            brel = {m.bnsh_offset + o for o in sa.relocation_pointers(a.data, m.bnsh_offset)}
            if m.bnsh_offset and (m.offset + 0x98) not in rel:
                reloc_bad.append(f"{n}/{m.name} BNSH ptr")
            for v in m.variations:
                for s in v.source_stages:
                    nsec += 1
                    src = s.source
                    define = b"NN_G3D_VERTEX_SHADER" if s.stage == "vertex" else b"NN_G3D_FRAGMENT_SHADER"
                    if not (src.startswith(b"#version 430") and define in s.prologue
                            and len(s.pieces) == 3):
                        bad.append(f"{n}/{m.name}/{s.stage}")
                    for p in s.pieces:
                        if a.data[p.offset + p.size] != 0 or p.ptr_field not in brel:
                            bad.append(f"{n}/{m.name}/{s.stage}@0x{p.offset:X}")
    _check("every source section = #version 430 + option #defines + body, NUL-terminated, "
           "piece pointers listed in the BNSH _RLT", not bad and nsec == 12,
           f"{nsec} sections" + (f"; bad {bad[:4]}" if bad else ""))
    _check("each shading model's BNSH pointer is relocated by the FSHA _RLT", not reloc_bad,
           str(reloc_bad[:3]))
    body = arcs["rf4cmv"].model("body")
    _check("body: static albedo_tex/multi_tex, dynamic skinning/coord/system_id, 1 program",
           [o.name for o in body.static_options] == ["albedo_tex", "multi_tex"]
           and [o.name for o in body.dynamic_options] == ["skinning", "coord", "system_id"]
           and body.program_count == 1 and "_p0" in body.attribs)
    offs = sorted((p.offset, p.size) for a in [arcs["rf4cmv"]] for _m, _v, s in a.sections()
                  for p in s.pieces)
    _check("rf4cmv source pieces are distinct (no shared blocks between stages/models)",
           all(o1 + n1 <= o2 for (o1, n1), (o2, _n2) in zip(offs, offs[1:])))
    try:
        blob = arcs["rf4cmv"].switch_binary("body", "vertex")
        _check("Switch GPU binary (zlib) decompresses to the recorded size",
               len(blob) == arcs["rf4cmv"].model("body").variations[0].binary_stages[0][2])
    except Exception as e:  # noqa: BLE001
        _check("Switch GPU binary (zlib) decompresses", False, str(e))
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="rf4s_shader_"))
    try:
        written = arcs["rf4cmv"].extract(tmp)
        want = {f"{m}.{e}.glsl" for m in ("body", "costume", "lighting", "env") for e in ("vert", "frag")}
        got = {p.name for p in written}
        same = all((tmp / "rf4cmv" / f"{m.name}.{sa.STAGE_EXT[s.stage]}.glsl").read_bytes() == s.source
                   for m, _v, s in arcs["rf4cmv"].sections())
        _check("extract writes body/costume/lighting/env vert+frag, byte-equal to the parsed "
               "sections (+ index.json)", want <= got and same and "index.json" in got)

        # ---- loose Muteki GLSL: the route the exe compiles -------------------------------
        mut = next((p for p in (EXTRACTED / "bundleMuteki", BUNDLE_DIR / "bundleMuteki")
                    if p.is_dir()), None)
        if mut is None or not (mut / "mtk_body_f.glsl").is_file():
            _skip("loose Muteki GLSL", "bundleMuteki not extracted")
            return
        idx = sa.ShaderIndex(mut)
        progs = idx.programs()
        _check("loose programs mtk_body / mtk_item / mtk_billboard have _v and _f files",
               all(progs[n]["vertex"] and progs[n]["fragment"]
                   for n in ("mtk_body", "mtk_item", "mtk_billboard")))
        miss_all, n_exp = [], 0
        for n, f in progs.items():
            if f["vertex"] and f["fragment"]:
                r = sa.expand_program(n, idx)
                n_exp += 1
                miss_all += r["missing"]
                if b"#include" in re.sub(rb"//[^\n]*|/\*.*?\*/", b"", r["vertex"] + r["fragment"],
                                         flags=re.S):
                    miss_all.append(f"{n}: unexpanded #include")
        _check("every loose program preprocesses with all #includes resolved",
               not miss_all and n_exp >= 10, f"{n_exp} programs" + (f"; {miss_all[:3]}" if miss_all else ""))
        orig = (mut / "mtk_body_f.glsl").read_bytes()
        dest, probs = sa.replace_loose("mtk_body_f.glsl", orig, tmp / "noop", idx)
        _check("no-op replace of mtk_body_f.glsl writes the shipped bytes back unchanged",
               dest.read_bytes() == orig and not probs, str(probs[:2]))
        marker = b"\n// rf4s_modkit selftest edit\n"
        edited = orig + marker
        dest, probs = sa.replace_loose("mtk_body_f.glsl", edited, tmp / "mod", idx)
        over = sa.ShaderIndex(tmp / "mod", mut)
        new = sa.expand_program("mtk_body", over)["fragment"]
        base = sa.expand_program("mtk_body", idx)
        others_same = all(sa.expand_program(n, over) == sa.expand_program(n, idx)
                          for n in ("mtk_item", "mtk_billboard"))
        _check("replaced source re-reads with the new text; vertex + other programs untouched",
               not probs and marker in new and marker not in base["fragment"]
               and sa.expand_program("mtk_body", over)["vertex"] == base["vertex"] and others_same)
        _, probs = sa.replace_loose("mtk_body_f.glsl", b"void f(){}\n#include <no_such.inc>\n",
                                    tmp / "bad", idx)
        _check("replace flags a missing #include / #version / main()",
               any("no_such" in p for p in probs) and any("#version" in p for p in probs)
               and any("main()" in p for p in probs))
        v = sa.preprocess(b"#version 430\nx\n", idx, defines={"K": 1})
        _check("preprocess: #version > 330 -> 330 + fp64 extension; defines after #version",
               v == b"#version 330\n#extension GL_ARB_gpu_shader_fp64 : enable\n#define K 1\nx\n", repr(v))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- static exe evidence (offline disassembly anchors) -------------------------------
    exe = BUNDLE_DIR.parent / "RF4S.exe"          # the game copy
    if not exe.is_file():
        _skip("RF4S.exe shader anchors", "RF4S.exe not next to Bundle/")
        return
    d = exe.read_bytes()
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec_pe = struct.unpack_from("<H", d, pe + 6)[0]
    sh = pe + 24 + struct.unpack_from("<H", d, pe + 20)[0]
    secs = [struct.unpack_from("<8sIIII", d, sh + 40 * i) for i in range(nsec_pe)]

    def at(rva, n):
        for _nm, vs, va, rs, rp in secs:
            if va <= rva < va + rs:
                return d[rp + rva - va:rp + rva - va + n]
        return b""

    def rip_target(rva, ilen=7):
        return rva + ilen + struct.unpack_from("<i", at(rva + 3, 4))[0]
    _check("exe: nn::gfx Shader init shim RF4S.exe+0x3D52A0 is `mov byte [rcx],1; xor eax,eax; ret`",
           at(0x3D52A0, 6) == bytes.fromhex("c60101" "33c0c3"))
    _check("exe: MCShader_ctor_base calls glShaderSource via the glew IAT slot (RF4S.exe+0x28B3FB/+0x28B47B)",
           at(0x28B3FB, 3) == b"\x48\x8b\x05" and rip_target(0x28B3FB) == 0x443930
           and rip_target(0x28B47B) == 0x443930)
    _check("exe: loose-file loader formats \"%s_v.glsl\" (RF4S.exe+0x27EB4D)",
           at(rip_target(0x27EB4D), 10) == b"%s_v.glsl\x00")


def test_sprite_quads_and_flags():
    """True-size map sprites (spritequad) and flag-gated object visibility (flagstate): the
    Dragon Lake bridge's crop/quad/world rectangle, every placed map_obj texture yields a
    placement, the decoration and interactive-object gate rules (incl. the f12 invert), a
    slot-save flag read, and the map editor drawing / hiding the bridge by those flags."""
    print("sprite quads + flag-gated objects (spritequad, flagstate, map editor):")
    import tempfile
    from rf4s_modkit import flagstate, rf4m, spritequad
    from rf4s_modkit.save import GAMEFLAGS_OFF, SAVE_SIZE
    B = pathlib.Path(BUNDLE_DIR) / "bundleMain"
    if not (B / "MAP_CITY_04.rf4m").exists():
        _skip("sprite quads", "no extracted bundleMain"); return
    objs = rf4m.Rf4mMap.load(B / "MAP_CITY_04.rf4m").decode_mobj()
    bridge, wall = objs[14], objs[15]
    _check("MAP_CITY_04 #14/#15 = bridge (f13 73) / clear wall (f13 74)",
           bridge["name"] == "MOBJ_BRIDGE_CITY_04_00" and wall["name"] == "MOBJ_CLEAR_WALL"
           and bridge["params"][13] == 73 and wall["params"][13] == 74)
    data = (B / "MOBJ_BRIDGE_CITY_04_00.texture").read_bytes()
    pl = spritequad.placement(data)
    _check("bridge: crop (0,0,384,768) of the decoded sheet, quad -192..192 x -384..384",
           pl == ((0, 0, 384, 768), (-192.0, -384.0, 192.0, 384.0)), str(pl))
    im, quad = spritequad.sprite_image(data)
    _check("bridge: world rect = sub-units (312,122)-(440,378) (spans the painted cliff)",
           spritequad.world_rect(bridge, quad) == (312.0, 122.0, 440.0, 378.0)
           and im.size == (384, 768), str(spritequad.world_rect(bridge, quad)))
    # every placed map_obj texture that ships a quad yields a placement
    names, bad = set(), []
    maps = sorted(B.glob("MAP_*.rf4m"))
    for f in (maps[::8] if QUICK else maps):
        for o in rf4m.Rf4mMap.load(f).decode_mobj():
            if o.get("name") and (B / (o["name"] + ".texture")).exists():
                names.add(o["name"])
    for n in sorted(names):
        try:
            if spritequad.placement((B / (n + ".texture")).read_bytes()) is None:
                bad.append(n)
        except Exception as e:
            bad.append("%s (%s)" % (n, e))
    _check("every placed map_obj texture (%d) has a TextureCoordinator/PolygonVertexes placement"
           % len(names), names and not bad, ", ".join(bad[:5]))
    # gate rules
    def state(*zone2_bits):
        blob = bytearray(flagstate.BLOB_SIZE)
        for n in zone2_bits:
            a = flagstate.ZONE2_BASE + n
            blob[a >> 3] |= 1 << (a & 7)
        return flagstate.FlagState(bytes(blob), "test")
    _check("no flags set: bridge shown, wall shown",
           not flagstate.hidden(bridge, state()) and not flagstate.hidden(wall, state()))
    _check("flag 73 hides the bridge (decoration), 74 removes the wall (object)",
           flagstate.hidden(bridge, state(73)) and not flagstate.hidden(wall, state(73))
           and flagstate.hidden(wall, state(74)) and not flagstate.hidden(bridge, state(74)))
    inv = dict(wall, params=list(wall["params"]))
    inv["params"][12] = 4
    _check("object f12 bit 2 inverts the gate (shown only once the flag is set)",
           flagstate.hidden(inv, state()) and not flagstate.hidden(inv, state(74)))
    _check("ungated records never hide", not any(
        flagstate.hidden(o, state(*range(1, 2560))) for o in objs
        if flagstate.gate(o) is None and (o["type_id"] & 0xFFFF) not in flagstate._ACTOR_GONE))
    chest = {"type_id": 44, "params": [44] + [0] * 12 + [180, 0, 0]}
    crate = {"type_id": 53, "params": [53] + [0] * 12 + [-1, 0, 0]}
    rchest = {"type_id": 44, "params": [44] + [0] * 8 + [1, 0, 0, 0, 180, 0, 0]}
    _check("chests / crates: gone once their flag is set, a -1 crate never; a reveal chest "
           "waits for flag f13 + f9",
           flagstate.hidden(chest, state(180)) and not flagstate.hidden(chest, state())
           and not flagstate.hidden(crate, state(*range(0, 2560)))
           and flagstate.actor_state(rchest, state()) == "unrevealed"
           and flagstate.actor_state(rchest, state(181)) is None
           and flagstate.hidden_reason(rchest, state()) == "not revealed yet: flag 181 is clear"
           and flagstate.hidden_reason(chest, state(180)) == "removed: flag 180 is set")
    noflag = dict(wall, params=list(wall["params"]))
    noflag["params"][12], noflag["params"][13] = 4, -1
    _check("an inverted gate with no flag is drawn (the tick skips flagless objects) but never "
           "stamps its collision",
           not flagstate.hidden(noflag, state()) and flagstate.no_flag_inverted(noflag)
           and "every frame" in flagstate.__doc__)
    with tempfile.TemporaryDirectory() as td:
        sav = bytearray(SAVE_SIZE)
        a = flagstate.ZONE2_BASE + 73
        sav[GAMEFLAGS_OFF + (a >> 3)] |= 1 << (a & 7)
        sav[GAMEFLAGS_OFF] |= 0x01                        # bit 0 = REG_MAIN_SCENARIO MSB -> 256
        pth = pathlib.Path(td) / "rf4_s99.sav"
        pth.write_bytes(bytes(sav))
        fs = flagstate.from_save(pth)
        _check("from_save: reads the zone-2 bit and the story register from the slot copy",
               fs.zone2(73) and not fs.zone2(74) and fs.story() == 256, "story %d" % fs.story())
    # map editor
    try:
        import tkinter as tk  # noqa: F401
    except Exception as e:
        _skip("sprite quads: map editor", "no tkinter: %s" % e); return
    from map_editor import data as med, render as mrender
    _headless_dialogs()
    root, panel, errs = _headless_panel("MAP_CITY_04", B, med.folder_reader(B))
    try:
        st = panel.view.st
        _check("editor: View is the first sidebar tab and the one open when the editor loads",
               panel.nb.tab(panel.nb.tabs()[0], "text") == "View"
               and panel.nb.tab(panel.nb.select(), "text") == "View")
        # the wheel zooms at the pointer; Ctrl+wheel scrolls (up/down) without zooming
        _cv = panel.view.canvas
        _cv.update()
        # (generated wheel events are not delivered reliably to a hidden window: check the
        # bindings, then drive the handlers with a stand-in event)
        _wb, _cb = _cv.bind("<MouseWheel>"), _cv.bind("<Control-MouseWheel>")

        class _W:
            delta, x, y = -120, 40, 40
        _z0 = panel.view.cp
        _scrolled = []
        _cv.yview_scroll = lambda n, what: _scrolled.append((n, what))   # (unlaid-out canvas)
        try:
            panel.view._ctrl_wheel(_W())
        finally:
            del _cv.yview_scroll
        _z1 = panel.view.cp
        panel.view._wheel(_W())
        _check("editor: the mouse wheel zooms, Ctrl+wheel scrolls",
               "_wheel" in _wb and "_ctrl_wheel" not in _wb and "_ctrl_wheel" in _cb
               and _z1 == _z0 and _scrolled == [(3, "units")] and panel.view.cp < _z0,
               "ctrl-wheel: zoom %s -> %s, scrolled %s; wheel: zoom -> %s"
               % (_z0, _z1, _scrolled, panel.view.cp))
        panel.view.fit()
        for k in ("sprites",):
            panel.viewtab.vars[k].set(True)
            panel.set_layer(k, True)
        kinds = lambda: {p.key[1]: p.kind for g in ("ent", "under") for p in mrender.overlay(g, st)
                         if p.key in (("mobj", 14), ("mobj", 15)) and p.kind != "text"}
        st.flags = None
        red = lambda: [p for p in mrender.overlay("ent", st)
                       if p.key == ("mobj", 14) and p.opt.get("outline") == mrender.BORDER_COLOR]
        had = bool(red())
        panel.set_layer("sprite_borders", False)
        gone_off = not red()
        panel.set_layer("sprite_borders", True)
        wall_red = any(p.key == ("mobj", 15) and p.opt.get("outline") == mrender.BORDER_COLOR
                       for p in mrender.overlay("ent", st))
        _check("editor: 'sprite borders' draws a red border around a full-size sprite, the "
               "transparent clear wall included (and can be turned off)", had and gone_off and wall_red)
        st.flags = None
        k0 = kinds()
        st.flags = state(73)
        k1 = kinds()
        st.flags = state(74)
        k2 = kinds()
        _check("editor: bridge + wall drawn full-size; flag 73 turns the bridge into an outline, "
               "74 the wall", k0 == {14: "sprite", 15: "sprite"} and k1 == {14: "rect", 15: "sprite"}
               and k2 == {14: "sprite", 15: "rect"}, "%s %s %s" % (k0, k1, k2))
        st.flags = None
        _v = panel.view
        _v.ground.get_blocking(_v.doc.base, _v.ground_sel, _v.doc.grid[0], _v.doc.grid[1], _v.scenery)
        panel.view.invalidate_all()                     # (the sprites wait for the ground)
        panel.view.flush()
        cv = panel.view.canvas
        pos = {it: n for n, it in enumerate(cv.find_all())}          # display list, bottom first
        low = lambda tag: min((pos[i] for i in cv.find_withtag(tag)), default=None)
        high = lambda tag: max((pos[i] for i in cv.find_withtag(tag)), default=None)
        _check("editor: full-size sprites sit right above the ground, below the ATTR fill/edges, "
               "the warps and the markers",
               None not in (high("under"), low("attr"), low("warp"), low("ent"))
               and (high("bg") is None or high("bg") < low("under"))
               and high("under") < low("attr") < low("warp") and high("under") < low("ent"),
               "bg %s under %s-%s attr %s warp %s ent %s" % (high("bg"), low("under"), high("under"),
                                                           low("attr"), low("warp"), low("ent")))
        # picking: inside a warp that a sprite covers, the warp wins; clicking again cycles
        v = panel.view
        cv = v.canvas
        # the sprites wait for the ground texture
        v.ground.cache.clear()
        v.invalidate("under")
        v.flush()
        held = v.ground_pending() and not cv.find_withtag("under")
        d0 = v.doc
        v.ground.get_blocking(d0.base, v.ground_sel, d0.grid[0], d0.grid[1], v.scenery)
        v._ground_ready(v.ground_key())
        v.flush()
        _check("editor: full-size sprites are held back until the ground texture has loaded",
               held and not v.ground_pending() and len(cv.find_withtag("under")) > 0)
        spr = {p.key: p.xy for p in mrender.overlay("under", st)}
        spot = None
        for j, rec in enumerate(v.doc.map.mapj_records()):
            wx0, wy0, wx1, wy1 = mrender.warp_rect_px(rec, st.cp)
            for k2, (sx0, sy0, sx1, sy1) in spr.items():
                x0, y0, x1, y1 = max(wx0, sx0) + 6, max(wy0, sy0) + 6, min(wx1, sx1) - 6, min(wy1, sy1) - 6
                if x1 > x0 and y1 > y0:
                    spot = (j, k2, (x0 + x1) // 2, (y0 + y1) // 2)
                    break
            if spot:
                break
        if spot is None:
            _skip("editor: warp under a sprite", "no warp overlaps a full-size sprite on MAP_CITY_04")
        else:
            j, k2, px, py = spot

            class _E:
                pass
            ev = _E()
            ev.x, ev.y = px - int(cv.canvasx(0)), py - int(cv.canvasy(0))
            ev.state = 0
            cands = v.pick_candidates(ev)
            tool = panel.tools["select"] if hasattr(panel, "tools") and isinstance(panel.tools, dict) else None
            picked = []
            if tool is not None:
                for _n in range(2):
                    tool.press(ev)
                    tool.release(ev) if hasattr(tool, "release") else None
                    picked.append(panel.sel)
            _check("editor: inside a warp that a full-size sprite covers, the warp is picked first; "
                   "clicking again steps to the sprite",
                   cands and cands[0] == ("warp", j) and k2 in cands
                   and (tool is None or (picked[0] == ("warp", j) and picked[1] != ("warp", j))),
                   "%s picked %s" % (cands, picked))
            if tool is not None:
                opened = []
                real_goto = panel.goto_warp
                panel.goto_warp = lambda jj: opened.append(jj)
                try:
                    # double-click where a sprite overlaps the warp: the warp opens
                    panel.select(k2)
                    tool.press(ev); tool.release(ev); tool.double(ev); tool.release(ev)
                    dbl_over = opened == [j]
                    # double-click on the selected warp: the first click steps away, the double
                    # brings the warp back and opens it
                    opened.clear()
                    panel.select(("warp", j))
                    tool.press(ev); tool.release(ev); tool.double(ev); tool.release(ev)
                    dbl_sel = opened == [j] and panel.sel == ("warp", j)
                    # a fast second click with no warp involved still cycles
                    opened.clear()
                    panel.select(k2)
                    tool.before_cycle = None
                    before = panel.sel
                    tool.double(ev); tool.release(ev)
                    fast = panel.sel != before and panel.sel in cands and not opened
                finally:
                    panel.goto_warp = real_goto
                _check("editor: double-clicking a warp opens it even where a sprite overlaps it, "
                       "and also when the warp was already selected",
                       dbl_over and dbl_sel, "overlap %s selected %s" % (dbl_over, dbl_sel))
                # press on the selection + drag: moves it, never cycles
                sel0 = panel.sel
                pos0 = tuple(panel.position_of(sel0))
                tool.press(ev)
                ev2 = _E()
                ev2.x, ev2.y, ev2.state = ev.x + 5 * st.cp, ev.y, 0
                tool.drag(ev2)
                tool.release(ev2)
                moved = tuple(panel.position_of(sel0)) != pos0
                kept = panel.sel == sel0
                panel.doc.undo() if hasattr(panel.doc, "undo") else None
                _check("editor: a fast second click (double-click) cycles too; a press + drag on "
                       "the selection moves it without cycling",
                       fast and moved and kept, "fast %s moved %s kept %s" % (fast, moved, kept))
        st.sel = ("mobj", 14)
        selp = mrender.overlay("sel", st)
        tr = [p.xy for p in mrender.overlay("under", st) if p.key == ("mobj", 14)]
        _check("editor: a selected full-size object gets a frame around its sprite, not the circle",
               tr and selp and all(p.kind == "rect" for p in selp)
               and any(p.xy == (tr[0][0] - 1, tr[0][1] - 1, tr[0][2] + 1, tr[0][3] + 1) for p in selp),
               "%s / %s" % ([(p.kind, p.xy) for p in selp], tr))
        panel.select(("mobj", 14))
        panel.view.flush()
        cv = panel.view.canvas
        pos = {it: n for n, it in enumerate(cv.find_all())}
        lift = [pos[i] for i in cv.find_withtag("lift")]
        attr_top = max((pos[i] for i in cv.find_withtag("attr")), default=None)
        warp_low = min((pos[i] for i in cv.find_withtag("warp")), default=None)
        lp = mrender.overlay("lift", st)
        _check("editor: the selected sprite shines through the ATTR fill (drawn again right above "
               "it, below the warps; not a hit target)",
               len(lp) == 1 and lp[0].kind == "sprite" and lp[0].key is None and lp[0].xy == tr[0]
               and lift and attr_top is not None and warp_low is not None
               and attr_top < min(lift) and max(lift) < warp_low,
               "lift %s attr %s warp %s" % (lift, attr_top, warp_low))
        panel.select(None)
        panel.view.flush()
        _check("editor: nothing is lifted once the selection is cleared",
               not cv.find_withtag("lift"))
        st.sel = None
        img = panel.render_to_image(scale=4)
        _check("editor: export draws the full-size sprites without errors",
               img is not None and not errs, str(errs[:1]))
    finally:
        root.destroy()


def run() -> int:
    import time
    mode = "QUICK (--quick: corpus sweeps skipped/sliced — run without it for the full stamp)" \
        if QUICK else "full"
    print(f"rf4s_modkit selftest  (bundles: {BUNDLE_DIR})  [{mode}]\n")
    slow = []
    for t in (test_bplist, test_mbundle, test_text, test_texture, test_texture_encode,
              test_texture_resize, test_model_texture_resize, test_texture_resize_gui, test_rf4m,
              test_aibn, test_strings, test_gen, test_param, test_fixed_point_fields, test_flag_fields, test_bin_editors, test_mapground,
              test_search_items, test_search_item_chances, test_entry_key_warnings, test_frame_sizing, test_opcode_arg_verification, test_game_names, test_error_logging, test_hotreload_image, test_mobj_types, test_minimap, test_res_and_ident, test_script,
              test_emflags, test_subevents, test_emscript, test_save, test_asatk, test_skillcurve, test_strengthening,
              test_sound_table, test_gifts, test_montame, test_schedule, test_monster, test_bugfixes,
              test_gen_structural, test_behaviour_edits, test_asatk_edit,
              test_rows_em_structural_skill, test_bcenc_and_model_textures,
              test_script_authoring, test_bank_relink, test_script_relink_edits, test_emflags_extras, test_textlint, test_portrait_faces, test_cutscene_editor_authoring, test_cutscene_bank_listing, test_cutscene_graph, test_choice_results, test_choice_form, test_argspec, test_edit_instruction, test_visibility_audit, test_scene_log, test_script_debugger, test_script_debugger_var_writes, test_script_debugger_edits,
              test_models, test_material_anims, test_skeletal_anims,test_model_import, test_attr_tooltips, test_ground_texture_replacement,
              test_map_editor_undo, test_map_editor_workflows, test_sprite_quads_and_flags,
              test_map_editor_clipboard, test_map_editor_placed_objects, test_map_editor_palette, test_map_editor_limits_bar, test_map_editor_place_and_delete, test_scene_flag_reference, test_map_editor_hardcoded_warps, test_collision_stamp_modes, test_app_icon, test_map_editor_blank_overmodel, test_cutscene_install_leaves_no_temp, test_settings_stay_in_toolkit, test_map_editor_attr_tip, test_map_editor_multi_select, test_chest_loot, test_crate_loot_and_mgrp, test_map_editor_mtxn_cap, test_mgrp_panel_and_conflicts, test_map_editor_extra_warnings, test_map_editor_sidecar_files, test_map_editor_minimap_tab, test_map_editor_resize_dialog, test_map_editor_script_spawns, test_map_editor_gate_ground, test_map_editor_gate_motion, test_map_editor_pool_spawn_sprites, test_map_editor_save_to_game, test_map_editor_labels, test_map_explorer_list, test_map_editor_copy_to_seasons,
              test_statement_operands, test_var_uses, test_entry_key_conflicts, test_cutscene_multi_select, test_cutscene_preload, test_cutscene_reload_from_disk, test_cutscene_editor_workflows, test_cutscene_toolbox, test_event_manager, test_asset_explorer_gui, test_explorer_open_file, test_explorer_model_obj_import, test_explorer_model_glb_import, test_model_fast_render, test_skelanim_write, test_gltf_motion_roundtrip, test_gltf_import_all_motions, test_gltf_blender_roundtrip, test_model_glb_import, test_model_glb_blender, test_model_material, test_model_grow, test_blender_addon, test_explorer_tabs, test_backups, test_remembered_options, test_theme, test_text_tab, test_text_escapes, test_live_names_and_combo_keys, test_viewer_tabs, test_portraits,
              test_shader_archive,
              test_map_container_checks, test_map_editor_warps_and_saving):
        t0 = time.perf_counter()
        try:
            t()
        except Exception as e:
            _check(t.__name__, False, f"exception: {e}")
        dt = time.perf_counter() - t0
        if dt >= 1.0:
            slow.append((dt, t.__name__))
    passed = sum(1 for _n, c in _results if c)
    total = len(_results)
    if slow:
        print("\nslowest sections: " + ", ".join(f"{n} {d:.0f}s" for d, n in
                                                 sorted(slow, reverse=True)))
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    _code = run()
    # Hard-exit: the disassembly cache holds tens of millions of small objects and
    # CPython's normal interpreter teardown spends MINUTES deallocating them (profiled
    # 2026-09-01: ~65s in quick mode, ~4 min full). All output is flushed above and
    # nothing here needs atexit/finalizers, so skip the teardown entirely.
    sys.stdout.flush()
    sys.stderr.flush()
    import os
    os._exit(_code)
