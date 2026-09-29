"""Hot-reload rf3.mc into a running RF4S.exe (Windows), any size, without a restart.

Why a restart is normally needed: Game_PreloadAllArchives (RF4S.exe+0x84FC0) loads
rf3.mc (archive 15209) once and never releases it, so the game never re-reads the file.
Every script read goes through that one resident copy:

  * nsFileArchive_Load (+0x241A50) returns the cached data pointer of the archive's
    24-byte cache entry (g_currentFileArchive +24 -> entry[id-1]: +0 data, +8 u16
    refcount, +10 flags). The entry holds no size, so the pointer is all there is.
  * SceneState_ParseMycfHeaderAndInstallReaders (+0x23DAB0) caches the header's section
    offsets / counts / max sizes / variable masks in the SceneState (+0x78..+0xBB) once.
  * MycfBankSlot_LoadBank (+0x23F9C0) copies one bank out of the resident file into its
    slot's buffer (global / primary / tail slot at SceneState +200 / +208 / +216). The
    buffer is a pointer field (slot +16), sized once from the header's max-size words.
    The game reloads banks on demand all the time (49 call sites), but only copies from
    the resident file.
  * A Script VM (ScriptVMContext_t) keeps a slot pointer and a u16 pc, and reads code
    through slot->buf every step.

So a reload is: put the new file in the game's memory and point the cache entry at it,
refresh the SceneState header cache, give each slot a buffer big enough for any bank
(64 KiB, the u16 pc limit) and copy in the new version of the bank it holds. All of it
happens with the process suspended. It is refused while a scene is running (a VM in
state 2 / 3 / 4: waiting / blocked / started), because its pc would point into the old
bank layout; Script_Opcode_FFFF_EndAndCleanup (+0x23EBA0) sets 1 when a script ends.

Dialogue text needs nothing: rf3mc.<locale> is not kept resident (refcount 0 in a live
game; only rf3mc.jpn is preloaded), so the game reads the file again for every line. A
resident locale file is swapped the same way when asked for.

Memory: the new file and the slot buffers are VirtualAllocEx'd. The game never frees them
(the archive entry keeps refcount >= 1; a slot is freed as one block, not its buffer).
A buffer from an earlier reload is reused or freed on the next one.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import struct
import subprocess
import time

EXE_NAME = "RF4S.exe"
# Where the two globals are in the RF4S.exe build the toolkit was made against. Another build
# (a newer Steam update, another store) moves them, so each is verified against the game's
# own data and, when that fails, found again by scanning the running exe's code for an
# instruction that uses it (RIP-relative: the global = instruction end + disp32).
RVA_CURRENT_FILE_ARCHIVE = 0xE9E538     # g_currentFileArchive (pointer)
RVA_SCENE_CONTEXT = 0xE3CB10            # g_currentSceneContext (SceneState_t *)
# (pattern, offset of the disp32, instruction length); None = any byte
SIG_FILE_ARCHIVE = ([0x48, 0x8B, 0x3D, None, None, None, None, 0x8B, 0xEA], 3, 7)   # nsFileArchive_Load: mov rdi, [g]
SIG_SCENE_CONTEXT = ([0x48, 0x89, 0x1D, None, None, None, None, 0x48, 0x85, 0xDB], 3, 7)  # ScriptTask_FirstTimeInit: mov [g], rbx
MC_ARCHIVE_ID = 15209                   # rom:/script/rf3.mc in the known build (found by path otherwise)
MC_ARCHIVE_PATH = "rom:/script/rf3.mc"
SLOT_OFFSETS = (("global", 200, 0), ("primary", 208, 1), ("tail", 216, 2))
SLOT_BUF_SIZE = 0x10000 + 64            # any bank fits: pcs are u16 (BANK_ADDRESS_LIMIT)
BUSY_VM_STATES = (2, 3, 4)              # waiting / blocked mid-op / started

_PROCESS_ACCESS = 0x0008 | 0x0010 | 0x0020 | 0x0400 | 0x0800   # VM_OP|READ|WRITE|QUERY|SUSPEND
_MEM_COMMIT_RESERVE, _MEM_RELEASE, _PAGE_RW = 0x3000, 0x8000, 0x04


class HotReloadError(Exception):
    """A reload that cannot happen for a reason the user can act on (the game is not
    running, a scene is playing, the file is not a valid rf3.mc)."""
    technical = False


class HotReloadTechnicalError(HotReloadError):
    """A reload that failed for a technical reason (32-bit Python, an unknown RF4S.exe
    build, memory access): the GUI logs it to the console for a bug report
    (guiutil.err_text)."""
    technical = True


class _MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD),
                ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD), ("Protect", wt.DWORD),
                ("Type", wt.DWORD)]


def find_pids(name=EXE_NAME):
    """PIDs of every running game process (tasklist), in its order."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % name, "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].strip('"').lower() == name.lower():
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def find_pid(name=EXE_NAME):
    """PID of the running game (the first one), or None."""
    pids = find_pids(name)
    return pids[0] if pids else None


def is_running():
    return bool(find_pids())


class GameProcess:
    """One running game: pid, exe path and start time (a pid reused by a new process gets a
    different start time, so a remembered choice does not follow it)."""

    __slots__ = ("pid", "path", "started")

    def __init__(self, pid, path, started):
        self.pid, self.path, self.started = pid, path, started

    def label(self):
        import datetime
        when = ""
        if self.started:
            # FILETIME: 100 ns ticks since 1601-01-01 UTC
            t = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=self.started // 10)
            when = t.replace(tzinfo=datetime.timezone.utc).astimezone().strftime("%H:%M:%S")
        folder = self.path.rsplit("\\", 1)[0] if self.path else "?"
        return "pid %d · started %s · %s" % (self.pid, when or "?", folder)

    def key(self):
        return (self.pid, self.started)


def game_processes(name=EXE_NAME):
    """[GameProcess] for every running game."""
    out = []
    if not hasattr(ctypes, "WinDLL"):
        return out
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wt.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_wchar_p, ctypes.POINTER(wt.DWORD)]
    k.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(ctypes.c_ulonglong)] * 4
    for pid in find_pids(name):
        path, started = "", 0
        h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                n = wt.DWORD(len(buf))
                if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    path = buf.value
                t = [ctypes.c_ulonglong() for _ in range(4)]
                if k.GetProcessTimes(h, *[ctypes.byref(x) for x in t]):
                    started = t[0].value
            finally:
                k.CloseHandle(h)
        out.append(GameProcess(pid, path, started))
    return out


_CHOSEN = {"key": None}          # (pid, start time) of the game picked while several run


def pick_process(choose=None):
    """The pid to hot-reload into. One running game: that one. Several: the one picked before
    while it still runs, else `choose([GameProcess])` -> the chosen GameProcess or None
    (cancelled); the pick is remembered until that process ends. Raises HotReloadError when
    none runs, or when several run and there is no `choose` (the CLI: pass --pid)."""
    procs = game_processes()
    if not procs:
        raise HotReloadError("%s is not running" % EXE_NAME)
    if len(procs) == 1:
        _CHOSEN["key"] = procs[0].key()
        return procs[0].pid
    for p in procs:
        if p.key() == _CHOSEN["key"]:
            return p.pid
    if choose is None:
        raise HotReloadError("%d copies of %s are running (%s): pick one with --pid"
                             % (len(procs), EXE_NAME, ", ".join(str(p.pid) for p in procs)))
    got = choose(procs)
    if got is None:
        return None
    _CHOSEN["key"] = got.key()
    return got.pid


class _Game:
    """A handle on the running game's memory."""

    def __init__(self, pid=None):
        if not hasattr(ctypes, "WinDLL"):
            raise HotReloadError("hot reload needs Windows")
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            # a 32-bit process cannot list or read a 64-bit one (EnumProcessModulesEx fails
            # with error 299 ERROR_PARTIAL_COPY, and addresses past 4 GB are out of reach)
            raise HotReloadTechnicalError("the toolkit is running on 32-bit Python, which cannot reach the "
                                 "64-bit game: install 64-bit Python 3.10+ (python.org, 'Windows "
                                 "installer (64-bit)'), then run start.bat again -- it rebuilds "
                                 "the toolkit's .venv with it")
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.ntdll = ctypes.WinDLL("ntdll")
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        k = self.k32
        k.OpenProcess.restype = wt.HANDLE
        k.VirtualAllocEx.restype = ctypes.c_void_p
        k.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
        k.VirtualFreeEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD]
        k.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(_MBI), ctypes.c_size_t]
        k.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.POINTER(ctypes.c_size_t)]
        k.WriteProcessMemory.argtypes = k.ReadProcessMemory.argtypes
        self.ntdll.NtSuspendProcess.argtypes = [wt.HANDLE]
        self.ntdll.NtResumeProcess.argtypes = [wt.HANDLE]
        self.pid = pid or find_pid()
        if not self.pid:
            raise HotReloadError("%s is not running" % EXE_NAME)
        self.h = k.OpenProcess(_PROCESS_ACCESS, False, self.pid)
        if not self.h:
            raise HotReloadError("cannot open %s (pid %d): error %d -- run the toolkit as the same "
                                 "user as the game" % (EXE_NAME, self.pid, ctypes.get_last_error()))
        mods = (wt.HMODULE * 1024)()
        need = wt.DWORD()
        psapi.EnumProcessModulesEx.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                                               ctypes.POINTER(wt.DWORD), wt.DWORD]
        base = None
        for _try in range(5):              # error 299 also happens while the game is still starting
            if psapi.EnumProcessModulesEx(self.h, mods, ctypes.sizeof(mods), ctypes.byref(need), 3):
                base = mods[0]
                break
            err = ctypes.get_last_error()
            time.sleep(0.2)
        if base is None:
            base = self._base_from_snapshot()
        if base is None:
            raise HotReloadTechnicalError("cannot find the game's exe in its memory (error %d) -- if the "
                                 "game is still starting, wait for the title screen and retry"
                                 % err)
        self.base = base
        self.suspended = False
        self._locate()

    def _base_from_snapshot(self):
        """The exe's load address from a Toolhelp module snapshot (the fallback when
        EnumProcessModulesEx fails), or None."""
        class _ME32(ctypes.Structure):
            _fields_ = [("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
                        ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD),
                        ("modBaseAddr", ctypes.c_void_p), ("modBaseSize", wt.DWORD),
                        ("hModule", wt.HMODULE), ("szModule", ctypes.c_wchar * 256),
                        ("szExePath", ctypes.c_wchar * 260)]
        k = self.k32
        k.CreateToolhelp32Snapshot.restype = wt.HANDLE
        k.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        k.Module32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(_ME32)]
        snap = k.CreateToolhelp32Snapshot(0x8 | 0x10, self.pid)       # MODULE | MODULE32
        if not snap or snap == wt.HANDLE(-1).value:
            return None
        try:
            me = _ME32()
            me.dwSize = ctypes.sizeof(me)
            if k.Module32FirstW(snap, ctypes.byref(me)):
                return me.modBaseAddr
        finally:
            k.CloseHandle(snap)
        return None

    def close(self):
        if self.suspended:
            self.resume()
        self.k32.CloseHandle(self.h)

    # ---- memory ---------------------------------------------------------------------- #
    def read(self, addr, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        if not self.k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)) \
                or got.value != n:
            raise HotReloadTechnicalError("cannot read %d bytes at %#x in the game" % (n, addr))
        return buf.raw

    def write(self, addr, data):
        data = bytes(data)
        got = ctypes.c_size_t()
        if not self.k32.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data),
                                           ctypes.byref(got)) or got.value != len(data):
            raise HotReloadTechnicalError("cannot write %d bytes at %#x in the game (error %d)"
                                 % (len(data), addr, ctypes.get_last_error()))

    def u8(self, a): return self.read(a, 1)[0]
    def u16(self, a): return struct.unpack("<H", self.read(a, 2))[0]
    def u32(self, a): return struct.unpack("<I", self.read(a, 4))[0]
    def i32(self, a): return struct.unpack("<i", self.read(a, 4))[0]
    def ptr(self, a): return struct.unpack("<Q", self.read(a, 8))[0]

    def alloc(self, n):
        p = self.k32.VirtualAllocEx(self.h, None, n, _MEM_COMMIT_RESERVE, _PAGE_RW)
        if not p:
            raise HotReloadTechnicalError("cannot allocate %d bytes in the game (error %d)"
                                 % (n, ctypes.get_last_error()))
        return p

    def own_allocation(self, p):
        """Size of the VirtualAlloc region that starts exactly at `p` (one of ours), else 0.
        The game's heap blocks (aligned_malloc) never start on their region's base."""
        if not p:
            return 0
        mbi = _MBI()
        if not self.k32.VirtualQueryEx(self.h, ctypes.c_void_p(p), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            return 0
        if mbi.AllocationBase != p or mbi.BaseAddress != p or mbi.Type != 0x20000 or mbi.State != 0x1000:
            return 0                                   # not MEM_PRIVATE / MEM_COMMIT at its base
        return mbi.RegionSize

    def free(self, p):
        self.k32.VirtualFreeEx(self.h, ctypes.c_void_p(p), 0, _MEM_RELEASE)

    def suspend(self):
        if self.ntdll.NtSuspendProcess(self.h) != 0:
            raise HotReloadTechnicalError("cannot pause the game")
        self.suspended = True

    def resume(self):
        self.ntdll.NtResumeProcess(self.h)
        self.suspended = False

    # ---- finding the globals ------------------------------------------------------------ #
    def _text_section(self):
        """(address, size) of the exe's .text section, from its PE headers in memory."""
        pe = self.base + struct.unpack("<I", self.read(self.base + 0x3C, 4))[0]
        nsec = struct.unpack("<H", self.read(pe + 6, 2))[0]
        opt = struct.unpack("<H", self.read(pe + 20, 2))[0]
        sec = pe + 24 + opt
        for i in range(nsec):
            h = self.read(sec + 40 * i, 40)
            if h[:5] == b".text":
                vsize, rva = struct.unpack("<II", h[8:16])
                return self.base + rva, vsize
        raise HotReloadTechnicalError("the game's exe has no .text section")

    def _scan(self, sig):
        """Addresses of the global every match of `sig` in .text references."""
        pat, doff, ilen = sig
        import re
        rx = re.compile(b"".join(b"." if b is None else re.escape(bytes([b])) for b in pat), re.S)
        start, size = self._text_section()
        out, chunk, pos = [], 1 << 22, 0
        while pos < size:
            n = min(chunk + len(pat), size - pos)
            try:
                data = self.read(start + pos, n)
            except HotReloadError:
                pos += chunk
                continue
            for m in rx.finditer(data):
                if m.start() < chunk:
                    ins = start + pos + m.start()
                    disp = struct.unpack("<i", data[m.start() + doff:m.start() + doff + 4])[0]
                    out.append(ins + ilen + disp)
            pos += chunk
        return sorted(set(out))

    def _archive_ok(self, g):
        """rf3.mc's archive id when `g` is g_currentFileArchive, else None."""
        try:
            arc = self.ptr(g)
            if not arc:
                return None
            toc = self.ptr(arc + 16)
            count = self.u32(arc + 560)
            if not (0 < count < 200000) or not toc:
                return None
            want = MC_ARCHIVE_PATH.encode("utf-16-le") + b"\0\0"
            if MC_ARCHIVE_ID < count and self.read(toc + (MC_ARCHIVE_ID << 8), len(want)) == want:
                return MC_ARCHIVE_ID
            step = 4096                              # 16 names of 256 bytes per read
            for first in range(0, count, step // 256):
                blob = self.read(toc + (first << 8), min(step, (count - first) << 8))
                for k in range(0, len(blob), 256):
                    if blob[k:k + len(want)] == want:
                        return first + k // 256
        except HotReloadError:
            return None
        return None

    def _scene_ok(self, g):
        """True when `g` holds 0 (no session yet) or a SceneState whose three bank slots point
        back at it -- what g_currentSceneContext holds."""
        try:
            sc = self.ptr(g)
            if not sc:
                return True
            for _n, off, mode in SLOT_OFFSETS:
                sl = self.ptr(sc + off)
                if not sl or self.ptr(sl) != sc or self.i32(sl + 8) != mode:
                    return False
            return True
        except HotReloadError:
            return False

    def _locate(self):
        """Set self.g_archive, self.g_scene and self.mc_id for this build of the game."""
        g = self.base + RVA_CURRENT_FILE_ARCHIVE
        mc = self._archive_ok(g)
        if mc is None:
            hits = [(a, self._archive_ok(a)) for a in self._scan(SIG_FILE_ARCHIVE)]
            hits = [(a, m) for a, m in hits if m is not None]
            if len(hits) != 1:
                raise HotReloadTechnicalError(
                    "this RF4S.exe build is not one the toolkit knows, and the file-archive table "
                    "could not be found in it (%d candidate(s)); hot reload cannot run -- restart "
                    "the game to load the saved rf3.mc (or wait until the game reaches the title "
                    "screen)" % len(hits))
            g, mc = hits[0]
        self.g_archive, self.mc_id = g, mc
        g = self.base + RVA_SCENE_CONTEXT
        if not self._scene_ok(g) or (self.ptr(g) == 0 and self._scan_needed_for_scene()):
            hits = [a for a in self._scan(SIG_SCENE_CONTEXT) if self._scene_ok(a) and self.ptr(a)]
            if len(hits) != 1:
                raise HotReloadTechnicalError(
                    "this RF4S.exe build is not one the toolkit knows, and its script state could "
                    "not be found (%d candidate(s)); load a save first, or restart the game to "
                    "load the saved rf3.mc" % len(hits))
            g = hits[0]
        self.g_scene = g

    def _scan_needed_for_scene(self):
        """A zero at the known address only proves something in the known build: in another
        build (the archive global was not where expected) look the scene global up too."""
        return self.g_archive != self.base + RVA_CURRENT_FILE_ARCHIVE

    # ---- game structures -------------------------------------------------------------- #
    def archive(self):
        return self.ptr(self.g_archive)

    def archive_path(self, idx):
        toc = self.ptr(self.archive() + 16)
        raw = self.read(toc + (idx << 8), 256)
        return raw.decode("utf-16-le", "replace").split("\0")[0]

    def archive_entry(self, idx):
        """(address of the cache entry, data pointer, refcount)."""
        e = self.ptr(self.archive() + 24) + 24 * idx - 24
        ptr, rc = struct.unpack("<QH", self.read(e, 10))
        return e, ptr, rc

    def find_archive(self, path):
        """Archive id of `path` (e.g. 'rom:/script/rf3mc.eng'), searched near rf3.mc."""
        for idx in range(self.mc_id - 64, self.mc_id + 64):
            if self.archive_path(idx) == path:
                return idx
        return None

    def scene(self):
        return self.ptr(self.g_scene)

    def slots(self, sc):
        """[(name, slot address, mode, bank_index, buf, bank_size, loaded)]."""
        out = []
        for name, off, mode_expected in SLOT_OFFSETS:
            s = self.ptr(sc + off)
            if not s:
                out.append((name, 0, mode_expected, -1, 0, 0, 0))
                continue
            back = self.ptr(s)
            mode, bi = struct.unpack("<ii", self.read(s + 8, 8))
            buf = self.ptr(s + 16)
            size = self.u32(s + 24)
            loaded = self.u8(s + 28)
            if back != sc or mode != mode_expected:
                raise HotReloadTechnicalError("the game's %s script slot does not look as expected "
                                     "(unknown RF4S.exe build?)" % name)
            out.append((name, s, mode, bi, buf, size, loaded))
        return out

    def vms(self, sc):
        """[(vm address, state, halted, bank slot, pc)] of the scene's Script VMs."""
        out, vm, n = [], self.ptr(sc + 0x70), 0
        while vm and n < 256:
            out.append((vm, self.u32(vm + 0x70), self.u32(vm + 0x74), self.ptr(vm + 0x20),
                        self.u32(vm + 0x3C)))
            vm = self.ptr(vm + 8)
            n += 1
        return out


# ---- the new file ------------------------------------------------------------------- #
def _ctz_loop(mask):
    """The parser's shift: count the low zero bits of `mask` (32 for 0)."""
    v, i = (~mask) & 0xFFFFFFFF, 0
    while v & 1:
        v >>= 1
        i += 1
    return i


class McImage:
    """The parts of a rf3.mc the engine caches, checked for a live reload."""

    def __init__(self, data):
        data = bytes(data)
        if len(data) < 76 or data[:4] != b"MYCF":
            raise HotReloadError("not a rf3.mc (MYCF) file")
        w = struct.unpack_from("<19I", data, 0)
        if w[1] != 0:
            raise HotReloadError("big-endian MYCF is not supported")
        if w[2] != 0x10001:
            raise HotReloadError("MYCF version %#x (the game needs 0x10001)" % w[2])
        self.data = data
        self.w = w
        self.global_off, self.global_size = w[3], w[4]
        self.n_primary, self.table1_off, self.n_tail, self.table2_off = w[5], w[6], w[7], w[8]
        self.max_primary, self.max_tail = w[12], w[13]
        n = len(data)

        def table(off, count, kind):
            if off + 8 * count > n:
                raise HotReloadError("%s section table runs past the end of the file" % kind)
            out = []
            for i in range(count):
                o, s = struct.unpack_from("<II", data, off + 8 * i)
                if o + s > n:
                    raise HotReloadError("%s bank %d (%d bytes at %d) runs past the end of the file"
                                         % (kind, i, s, o))
                if s > 0x10000:
                    raise HotReloadError("%s bank %d is %d bytes (the limit is 65,536)" % (kind, i, s))
                out.append((o, s))
            return out

        self.primary = table(self.table1_off, self.n_primary, "primary")
        self.tail = table(self.table2_off, self.n_tail, "tail")
        if self.global_off + self.global_size > n or self.global_size > 0x10000:
            raise HotReloadError("the global bank does not fit the file / 64 KiB")
        big_p = max((s for _, s in self.primary), default=0)
        big_t = max((s for _, s in self.tail), default=0)
        if big_p > self.max_primary or big_t > self.max_tail:
            raise HotReloadError("the header's max bank sizes (%d / %d) are below the biggest "
                                 "banks (%d / %d): the game would overflow its buffers the next "
                                 "time it starts a session -- save the file with the toolkit"
                                 % (self.max_primary, self.max_tail, big_p, big_t))

    def scene_fields(self):
        """SceneState +0x78..+0xBB (17 u32), as the header parser fills them."""
        w = self.w
        return struct.pack("<17I", w[3], w[4], w[15], w[5], w[6], w[12], w[16], w[7], w[8], w[13],
                           w[17], w[9], _ctz_loop(w[9]), w[10], _ctz_loop(w[10]), w[11], w[14])

    def bank_bytes(self, mode, index):
        """Bytes of the bank a slot of `mode` (0 global / 1 primary / 2 tail) holds, or None."""
        if mode == 0:
            return self.data[self.global_off:self.global_off + self.global_size]
        table = self.primary if mode == 1 else self.tail
        if not 0 <= index < len(table):
            return None
        o, s = table[index]
        return self.data[o:o + s]


# ---- status / reload ------------------------------------------------------------------ #
def status(pid=None):
    """What the running game holds: a dict for display (raises HotReloadError)."""
    g = _Game(pid)
    try:
        _, ptr, rc = g.archive_entry(g.mc_id)
        sc = g.scene()
        out = {"pid": g.pid, "resident": bool(ptr), "refcount": rc, "scene": bool(sc),
               "slots": [], "vms": [], "busy": False}
        if sc:
            out["slots"] = [dict(kind=n, bank=bi, size=sz, loaded=bool(ld))
                            for n, s, m, bi, buf, sz, ld in g.slots(sc)]
            out["vms"] = [dict(state=st, halted=bool(hl), pc=pc) for _, st, hl, _, pc in g.vms(sc)]
            out["busy"] = any(v["state"] in BUSY_VM_STATES for v in out["vms"])
        return out
    finally:
        g.close()


def reload_mc(data, pid=None, force=False, settle=0.25):
    """Put `data` (a whole rf3.mc) into the running game in place of the resident copy.
    Returns a report dict. Raises HotReloadError (nothing is changed) when the file is not
    valid, the game is not in a known state, or a scene is running (unless `force`)."""
    img = McImage(data)
    g = _Game(pid)
    freed = []
    try:
        new_file = g.alloc(len(img.data) + 4160)
        g.write(new_file, img.data)
        spare = {}                                      # slot -> a fresh 64 KiB buffer
        g.suspend()
        try:
            entry, old_ptr, rc = g.archive_entry(g.mc_id)
            if not old_ptr or rc == 0:
                raise HotReloadError("rf3.mc is not loaded in the game yet (still on the title screen?)")
            if g.read(old_ptr, 4) != b"MYCF":
                raise HotReloadTechnicalError("the game's resident rf3.mc does not look like MYCF")
            sc = g.scene()
            slots = g.slots(sc) if sc else []
            vms = g.vms(sc) if sc else []
            busy = [v for v in vms if v[1] in BUSY_VM_STATES]
            if busy and not force:
                raise HotReloadError("a scene is running (Script VM state %d at pc 0x%04x) -- let it "
                                     "finish, then reload" % (busy[0][1], busy[0][4]))
            reloaded = []
            if sc:
                g.write(sc + 0x78, img.scene_fields())
                for name, s, mode, bi, buf, size, loaded in slots:
                    if not s:
                        continue
                    if g.own_allocation(buf) < SLOT_BUF_SIZE:
                        if buf != s + 32 and g.own_allocation(buf):
                            freed.append(buf)
                        spare[s] = g.alloc(SLOT_BUF_SIZE)
                        buf = spare[s]
                        g.write(s + 16, struct.pack("<Q", buf))
                    blob = img.bank_bytes(mode, bi) if loaded else None
                    if blob is None:
                        g.write(s + 28, b"\0")          # not loaded: the next use loads it
                        reloaded.append((name, bi, None))
                        continue
                    g.write(buf, blob)
                    g.write(s + 24, struct.pack("<I", len(blob)))
                    reloaded.append((name, bi, len(blob)))
            g.write(entry, struct.pack("<Q", new_file))
            if g.own_allocation(old_ptr):
                freed.append(old_ptr)
        except Exception:
            g.resume()
            g.free(new_file)
            for p in spare.values():
                g.free(p)
            raise
        g.resume()
        # A thread paused inside MycfBankSlot_LoadBank finishes its copy after the resume:
        # check every slot against the new file and fix any that changed.
        time.sleep(settle)
        fixed = []
        if sc:
            g.suspend()
            try:
                for name, s, mode, bi, buf, size, loaded in g.slots(sc):
                    blob = img.bank_bytes(mode, bi) if (s and loaded) else None
                    if blob is not None and (size != len(blob) or g.read(buf, len(blob)) != blob):
                        g.write(buf, blob)
                        g.write(s + 24, struct.pack("<I", len(blob)))
                        fixed.append(name)
            finally:
                g.resume()
        for p in freed:                                   # older buffers of ours, now unused
            g.free(p)
        return {"pid": g.pid, "bytes": len(img.data), "slots": reloaded, "fixed_after": fixed,
                "forced": bool(force and busy)}
    finally:
        g.close()


def describe(report):
    """One line for a reload report."""
    parts = []
    for name, bi, n in report["slots"]:
        parts.append("%s bank %d %s" % (name, bi, "reloaded" if n is not None else "(reloads on use)"))
    s = "rf3.mc (%d bytes) is live in the running game (pid %d)" % (report["bytes"], report["pid"])
    if parts:
        s += "; " + ", ".join(parts)
    if report.get("fixed_after"):
        s += "; re-copied %s after a load in flight" % ", ".join(report["fixed_after"])
    if report.get("forced"):
        s += "; FORCED while a scene was running -- expect that scene to misbehave"
    return s
