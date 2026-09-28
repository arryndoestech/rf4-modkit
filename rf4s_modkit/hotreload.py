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
RVA_CURRENT_FILE_ARCHIVE = 0xE9E538     # g_currentFileArchive (pointer)
RVA_SCENE_CONTEXT = 0xE3CB10            # g_currentSceneContext (SceneState_t *)
MC_ARCHIVE_ID = 15209                   # rom:/script/rf3.mc
MC_ARCHIVE_PATH = "rom:/script/rf3.mc"
SLOT_OFFSETS = (("global", 200, 0), ("primary", 208, 1), ("tail", 216, 2))
SLOT_BUF_SIZE = 0x10000 + 64            # any bank fits: pcs are u16 (BANK_ADDRESS_LIMIT)
BUSY_VM_STATES = (2, 3, 4)              # waiting / blocked mid-op / started

_PROCESS_ACCESS = 0x0008 | 0x0010 | 0x0020 | 0x0400 | 0x0800   # VM_OP|READ|WRITE|QUERY|SUSPEND
_MEM_COMMIT_RESERVE, _MEM_RELEASE, _PAGE_RW = 0x3000, 0x8000, 0x04


class HotReloadError(Exception):
    pass


class _MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD),
                ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD), ("Protect", wt.DWORD),
                ("Type", wt.DWORD)]


def find_pid(name=EXE_NAME):
    """PID of the running game, or None."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % name, "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].strip('"').lower() == name.lower():
            try:
                return int(parts[1])
            except ValueError:
                pass
    return None


def is_running():
    return find_pid() is not None


class _Game:
    """A handle on the running game's memory."""

    def __init__(self, pid=None):
        if not hasattr(ctypes, "WinDLL"):
            raise HotReloadError("hot reload needs Windows")
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
        if not psapi.EnumProcessModulesEx(self.h, mods, ctypes.sizeof(mods), ctypes.byref(need), 3):
            raise HotReloadError("cannot list the game's modules (error %d)" % ctypes.get_last_error())
        self.base = mods[0]
        self.suspended = False

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
            raise HotReloadError("cannot read %d bytes at %#x in the game" % (n, addr))
        return buf.raw

    def write(self, addr, data):
        data = bytes(data)
        got = ctypes.c_size_t()
        if not self.k32.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data),
                                           ctypes.byref(got)) or got.value != len(data):
            raise HotReloadError("cannot write %d bytes at %#x in the game (error %d)"
                                 % (len(data), addr, ctypes.get_last_error()))

    def u8(self, a): return self.read(a, 1)[0]
    def u16(self, a): return struct.unpack("<H", self.read(a, 2))[0]
    def u32(self, a): return struct.unpack("<I", self.read(a, 4))[0]
    def i32(self, a): return struct.unpack("<i", self.read(a, 4))[0]
    def ptr(self, a): return struct.unpack("<Q", self.read(a, 8))[0]

    def alloc(self, n):
        p = self.k32.VirtualAllocEx(self.h, None, n, _MEM_COMMIT_RESERVE, _PAGE_RW)
        if not p:
            raise HotReloadError("cannot allocate %d bytes in the game (error %d)"
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
            raise HotReloadError("cannot pause the game")
        self.suspended = True

    def resume(self):
        self.ntdll.NtResumeProcess(self.h)
        self.suspended = False

    # ---- game structures -------------------------------------------------------------- #
    def archive(self):
        return self.ptr(self.base + RVA_CURRENT_FILE_ARCHIVE)

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
        for idx in range(MC_ARCHIVE_ID - 64, MC_ARCHIVE_ID + 64):
            if self.archive_path(idx) == path:
                return idx
        return None

    def scene(self):
        return self.ptr(self.base + RVA_SCENE_CONTEXT)

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
                raise HotReloadError("the game's %s script slot does not look as expected "
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
        if g.archive_path(MC_ARCHIVE_ID) != MC_ARCHIVE_PATH:
            raise HotReloadError("archive %d is not %s in this RF4S.exe build" % (MC_ARCHIVE_ID, MC_ARCHIVE_PATH))
        _, ptr, rc = g.archive_entry(MC_ARCHIVE_ID)
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
        if g.archive_path(MC_ARCHIVE_ID) != MC_ARCHIVE_PATH:
            raise HotReloadError("archive %d is not %s in this RF4S.exe build" % (MC_ARCHIVE_ID, MC_ARCHIVE_PATH))
        new_file = g.alloc(len(img.data) + 4160)
        g.write(new_file, img.data)
        spare = {}                                      # slot -> a fresh 64 KiB buffer
        g.suspend()
        try:
            entry, old_ptr, rc = g.archive_entry(MC_ARCHIVE_ID)
            if not old_ptr or rc == 0:
                raise HotReloadError("rf3.mc is not loaded in the game yet (still on the title screen?)")
            if g.read(old_ptr, 4) != b"MYCF":
                raise HotReloadError("the game's resident rf3.mc does not look like MYCF")
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
