"""The cutscene editor's cross-bank index scan (which statements read / write each variable,
which name an em.bin entry), split over worker processes.

Each bank is scanned on its own -- a scan reads nothing outside the bank -- so the banks can be
shared out between processes and the result is exactly the one-process scan's. Processes, not
threads: a scan thread holds Python's GIL for seconds, and the editor's Tk calls (each one
gives the GIL up and waits to get it back) stall meanwhile; at start-up that froze the editor
for 6-7 s while the hidden Reference window filled its lists.

Plain child processes (`python -m rf4s_modkit.scanpool`), no executor: an executor unpickles
results on helper threads of its own, and a garbage collection there frees the editor's Tk
objects on the wrong thread (Tcl can abort). Here the caller polls (ScanJob.done) and reads the
results (ScanJob.result) on its own thread. A worker writes positions only (statement pcs); the
statements are decoded again from the bank bytes when read, a few hundredths of a second for
the ~21,000 uses of the shipped file. No Tk is imported: a worker imports this module and
rf4s_modkit.script only.
"""
import os
import pathlib
import pickle
import subprocess
import sys
import tempfile
import time

from . import script

MIN_BANKS_FOR_POOL = 64        # fewer banks to scan (an edit): one process is quicker
WORKER_TIMEOUT_S = 120


def bank_scan(bk):
    """One pass over a bank for both cross-bank indexes: ([(em entry id or None, scene entry,
    pc, stmt)] for the em bridge ops (371-374, 444; None = an entry id computed at run time),
    [(variable enc, access, scene entry, pc, stmt)] for every named variable read or written
    (varuses))."""
    from . import varuses
    em, var, seen = [], [], set()
    for sc in script.disassemble_bank(bk):
        for pc, st in sc.stmts.items():
            if pc in seen:
                continue
            seen.add(pc)
            for enc, acc in varuses.statement_var_access(bk.data, st):
                var.append((enc, acc, sc.entry_pc, pc, st))
            ai = script.EMF_ENTRY_OPS.get(st.op)
            if ai is None or ai >= len(st.args):
                continue
            try:
                eid = int(script.arg_repr(bk.data, st.args[ai]))
            except (ValueError, TypeError):
                eid = None
            em.append((eid, sc.entry_pc, pc, st))
    return em, var


def _slim(bk):
    em, var = bank_scan(bk)
    return ([(e, entry, pc) for e, entry, pc, _st in em],
            [(enc, acc, entry, pc) for enc, acc, entry, pc, _st in var])


def _restore(bk, em, var):
    """A worker's pcs back into bank_scan's lists, each statement decoded once."""
    cache = {}

    def st(pc):
        s = cache.get(pc)
        if s is None:
            s = cache[pc] = script.decode_statement(bk.data, pc)
        return s
    return ([(e, entry, pc, st(pc)) for e, entry, pc in em],
            [(enc, acc, entry, pc, st(pc)) for enc, acc, entry, pc in var])


def worker_count():
    return max(1, min(4, (os.cpu_count() or 1)))


class ScanJob:
    """bank_scan of many banks in worker processes. Poll done(), then read result() -- both
    on the caller's thread. A job whose workers cannot start or fail scans in-process instead
    (result() still returns the full scan)."""

    def __init__(self, container, positions, workers=None):
        self.c = container
        self.positions = list(positions)
        self.procs, self.outs, self.failed = [], [], False
        self.started = time.monotonic()
        workers = worker_count() if workers is None else workers
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="rf4s_scan_"))
        try:
            blob = self.tmp / "rf3.mc"
            blob.write_bytes(bytes(container.build()))
            root = str(pathlib.Path(__file__).resolve().parent.parent)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            for k in range(workers):
                share = self.positions[k::workers]       # interleaved: big and small banks spread
                if not share:
                    continue
                out = self.tmp / ("part%d.pkl" % k)
                lst = self.tmp / ("part%d.txt" % k)
                lst.write_text(",".join(map(str, share)), encoding="ascii")
                self.procs.append(subprocess.Popen(
                    [sys.executable, "-m", "rf4s_modkit.scanpool", str(blob), str(lst), str(out)],
                    cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, creationflags=flags))
                self.outs.append(out)
        except Exception:  # noqa: BLE001 -- no processes here: result() scans in-process
            self.failed = True

    def done(self):
        if self.failed:
            return True
        if time.monotonic() - self.started > WORKER_TIMEOUT_S:
            self.failed = True
            return True
        return all(p.poll() is not None for p in self.procs)

    def result(self):
        """{pos: (em, var)}; waits for the workers when called early."""
        out = {}
        try:
            if not self.failed:
                for p in self.procs:
                    p.wait(timeout=max(1, WORKER_TIMEOUT_S - (time.monotonic() - self.started)))
                if any(p.returncode != 0 for p in self.procs):
                    raise RuntimeError("a scan worker failed")
                for f in self.outs:
                    for pos, em, var in pickle.loads(f.read_bytes()):
                        out[pos] = _restore(self.c.banks[pos], em, var)
            if set(out) != set(self.positions):
                raise RuntimeError("a scan worker left banks out")
        except Exception:  # noqa: BLE001 -- fall back to scanning here
            self.cancel()
            out = {p: bank_scan(self.c.banks[p]) for p in self.positions}
        finally:
            self._cleanup()
        return out

    def cancel(self):
        for p in self.procs:
            if p.poll() is None:
                try:
                    p.kill()
                except OSError:
                    pass
        self._cleanup()

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


def scan_banks(container, positions, workers=None):
    """{pos: (em, var)} = bank_scan of each position of `container` (its current bytes, unsaved
    edits included). Many banks are shared out over worker processes; few are scanned here."""
    positions = list(positions)
    workers = worker_count() if workers is None else workers
    if workers <= 1 or len(positions) < MIN_BANKS_FOR_POOL:
        return {p: bank_scan(container.banks[p]) for p in positions}
    return ScanJob(container, positions, workers).result()


def _worker_main(blob_path, list_path, out_path):
    c = script.Container(pathlib.Path(blob_path).read_bytes())
    positions = [int(x) for x in pathlib.Path(list_path).read_text(encoding="ascii").split(",") if x]
    res = [(pos,) + _slim(c.banks[pos]) for pos in positions]
    tmp = pathlib.Path(out_path + ".part")
    tmp.write_bytes(pickle.dumps(res, protocol=pickle.HIGHEST_PROTOCOL))
    os.replace(tmp, out_path)


if __name__ == "__main__":
    _worker_main(*sys.argv[1:4])
