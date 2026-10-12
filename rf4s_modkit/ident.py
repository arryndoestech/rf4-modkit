r"""
ident.py -- identify RF4S asset files by magic bytes.

Every extension that ships in the bundles is covered. Magic bytes were sampled
directly from the extracted corpus and cross-checked against the loader code.

`identify(data)` returns a FileType describing the format, the modkit module that
handles it (if any), and whether the toolkit can rewrite it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FileType:
    fmt: str            # short format id, e.g. "texture", "bplist", "bfres"
    desc: str           # human description
    container: str      # underlying container family
    handler: str | None  # modkit module that reads/writes it, or None
    writable: bool      # can the toolkit produce a modified version?
    note: str = ""

    def __str__(self):
        rw = "read+write" if self.writable else "read-only" if self.handler else "identify-only"
        return f"{self.fmt}: {self.desc} [{rw}]" + (f" -- {self.note}" if self.note else "")


# Magic-prefix table. Order matters (longest / most specific first).
_MAGICS = [
    (b"bplist00", FileType("bplist", "Muteki binary plist (UI layout / config / archive index)",
                           "bplist", "bplist", True,
                           "covers .mbundle, .minterface, .plist, Manifest.plist")),
    (b"MAPD",     FileType("rf4m", "Compiled map container", "rf4m", "rf4m", True)),
    (b"AIBN",     FileType("aibn", "Monster/NPC AI behaviour script", "aibn", "aibn", True)),
    (b"MYCF",     FileType("mycf", "Compiled cutscene/event script bytecode (rf3.mc)",
                           "mycf", None, False,
                           "u16 Script-VM bytecode; dialogue text in rf3mc.<locale>")),
    (b"TEXT",     FileType("text", "TEXT string archive (item names / dialogue / catalogs)",
                           "text", "textdb", True)),
    (b"EMF_",     FileType("emf", "Event Manager trigger programs (em.bin)",
                           "emf", "emscript", True,
                           "named entries: condition trees + flag-write actions; "
                           "EN/JP names live in emdeb.bin")),
    (b"EMDb",     FileType("emdeb", "Event Manager symbol table (emdeb.bin)",
                           "emf", "emscript", False,
                           "entry/query names for em.bin + the FLG_/REG_ save-flag layout")),
    (b"TRCS",     FileType("route", "NPC town-navigation graph (rf3route.bin: rooms/nodes/edges)",
                           "trcs", "route", True,
                           "pairs with rf3RouteResult.bin (next-hop matrix); JSON round trip")),
    # NLCL is disambiguated in identify(): Gen*.bin (version 6) -> gen encounter table;
    # everything else -> flat param table (item/crop/price/recipe/skill/...).
    (b"NLCL",     FileType("param", "NLCL parameter table (item/crop/price/recipe/skill/...)",
                           "nlcl", "nlcl", True, "flat fixed-record game-data table")),
    (b"FRES\x20\x20\x20\x20", FileType("bfres", "Nintendo BFRES resource (skeleton/material/model)",
                           "bfres", "res_container", True,
                           ".bfskl motions (play, import), .bfmat / .bfmts material "
                           "animations (play, edit)")),
    (b"FSHA\x20\x20\x20\x20", FileType("bfsha", "Nintendo BFRES shader archive",
                           "bfres", "res_container", False)),
    (b"RES\x00",  FileType("res", "Nintendo NN resource container (.model or .texture)",
                           "res", "res_container", True,
                           ".texture decodes/encodes; .model meshes, materials, textures")),
    (b"BNTX",     FileType("bntx", "Nintendo BNTX texture", "bntx", "texture", True)),
    (b"PSB\x00",  FileType("psb", "M2 Emote / PSB scripted data (.psbData / .emtbytes)",
                           "psb", "res_container", False, "M2 Emote SDK portrait/animation")),
    (b"\x89PNG\r\n\x1a\n", FileType("png", "PNG image", "png", None, True,
                           "standard PNG -- edit with any image tool")),
    # Standard raster images (viewable via Pillow; not a game-specific format).
    (b"\xff\xd8\xff",  FileType("jpg",  "JPEG image", "image", None, True, "standard JPEG")),
    (b"GIF87a",        FileType("gif",  "GIF image",  "image", None, True, "standard GIF")),
    (b"GIF89a",        FileType("gif",  "GIF image",  "image", None, True, "standard GIF")),
    (b"II*\x00",       FileType("tiff", "TIFF image", "image", None, True, "standard TIFF (little-endian)")),
    (b"MM\x00*",       FileType("tiff", "TIFF image", "image", None, True, "standard TIFF (big-endian)")),
    (b"DDS\x20",       FileType("dds",  "DDS texture image", "image", None, True, "DirectDraw Surface")),
    (b"OggS",     FileType("ogg", "Ogg Vorbis audio", "ogg", "audio", True,
                           "standard Ogg -- replace with any encoder")),
    (b"RIFF",     FileType("wav", "RIFF/WAVE PCM audio", "wav", "audio", True, "standard WAV")),
    (b"FORM",     FileType("aiff", "AIFF audio (UI sounds)", "aiff", "audio", True)),
    (b"\x1aE\xdf\xa3", FileType("webm", "WebM/Matroska cutscene video", "webm", None, True,
                           "VP8/VP9 + Vorbis/Opus -- replace with ffmpeg")),
    (b"DVLB",     FileType("shbin", "Nintendo 3DS shader binary", "ctr", None, False,
                           "unused on PC")),
    (b"FSAR",     FileType("bfsar", "Nintendo BFSAR audio archive", "nw", None, False,
                           "unused on PC (SoLoud replaces it)")),
    (b"CSAR",     FileType("bcsar", "Nintendo BCSAR audio archive", "nw", None, False,
                           "unused on PC")),
    (b"CGFX",     FileType("bcsdr", "Nintendo CGFX graphics archive", "nw", None, False,
                           "unused on PC")),
    (b"ttcf",     FileType("ttc", "TrueType collection font", "font", None, True,
                           "standard font -- swap freely")),
    (b"\x00\x01\x00\x00", FileType("ttf", "TrueType font", "font", None, True, "standard font")),
    (b"true",     FileType("ttf", "TrueType font", "font", None, True, "standard font")),
]


def identify(data: bytes, *, filename: str | None = None) -> FileType:
    """Identify a file from its leading bytes (and optionally its name)."""
    for magic, ft in _MAGICS:
        if data[:len(magic)] == magic:
            # Disambiguate NLCL by version/filename:
            #   SI_*.bin (version 2)  = search-item spot table (daily ground pickups)
            #   Gen*.bin (version 6+) = monster encounter table
            #   everything else      = flat param table
            if ft.fmt == "param":
                import struct
                ver = struct.unpack_from("<I", data, 16)[0] if len(data) >= 20 else 0
                base = (filename or "").rsplit("/", 1)[-1]
                if ver == 2 or base.startswith("SI_"):
                    return FileType("search_items",
                                    "NLCL search-item spot table (SI_*.bin)",
                                    "nlcl", "search_items", True,
                                    "daily ground-pickup spots + weighted drop pools")
                is_gen = ver == 6 or base.startswith("Gen")
                if is_gen:
                    return FileType("gen", "NLCL monster encounter table (Gen*.bin)",
                                    "nlcl", "gen", True, "dungeon/field monster spawn list")
                return ft
            # Disambiguate RES\0 -> texture vs model by content.
            if ft.fmt == "res":
                if b"PIXL" in data[:0x4000]:
                    return FileType("texture", "NN RES texture (BC7/RGBA8/...)",
                                    "res", "texture", True,
                                    "decode to PNG / encode from PNG (any template; "
                                    "re-encoded in its own format at the same size)")
                return FileType("model", "NN BFRES model (RES\\0 wrapper)",
                                "res", "res_container", True,
                                "meshes, materials, embedded textures; `rf4mod res`")
            # RIFF is shared by WAVE audio and WebP images -- split on the sub-chunk tag.
            if ft.fmt == "wav" and data[8:12] == b"WEBP":
                return FileType("webp", "WebP image", "image", None, True, "standard WebP")
            return ft

    # No magic matched -- fall back to heuristics / extension.
    ext = (filename or "").lower().rsplit(".", 1)[-1] if filename and "." in filename else ""
    base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base.startswith("as_atk_") and base.endswith(".bin"):
        return FileType("asatk", "Attack move timeline (as_atk_*.bin)", "binary", "asatk", True,
                        "per-frame events: hitboxes, effects, sounds; `rf4mod asatk`")
    if base.startswith("rf3monsterpresent"):
        return FileType("montame", "Monster taming foods (rf3MonsterPresent.bin)", "binary",
                        "montame", True, "4 (item, tame bonus) slots per species; "
                        "`rf4mod gift monster-set`")
    if base.startswith("rf3routeresult"):      # headerless 318 x 159 B nibble matrix
        return FileType("route_result", "NPC path next-hop matrix (rf3RouteResult.bin)",
                        "binary", "route", True,
                        "hop[dst][src] nibbles over rf3route.bin; `route rebuild-result`")
    if base == "rf3schedule.bin" or (data[:4] == b"\x30\x00\x12\x00" and data[4:8] == b"\x10\x00\x00\x00"):
        return FileType("schedule", "NPC daily routines (rf3Schedule.bin: 48 NPCs x 18 day kinds)",
                        "binary", "schedule", True,
                        "stops = time + spot kind (rf3ScheduleID); `rf4mod schedule`")
    if ext == "sav":
        return FileType("sav", "Bundled scenario preset save (AS_*/JM_*/E3_DEMO)",
                        "save", None, False,
                        "raw RF4 save image (CRC32 first); not editable")
    if ext == "bdat":
        return FileType("bdat", "Sound-id table (sound id -> file, volume, priority)",
                        "binary", "soundtable", True, "`rf4mod sound`")
    if ext in ("glsl", "hlsl", "inc"):
        return FileType("shader", "GLSL/HLSL shader source", "text", None, True,
                        "plain text -- edit directly")
    if ext == "strings":
        return FileType("strings", "Apple-style .strings localisation", "text",
                        "strings_file", True)
    if ext == "mmaterial":
        return FileType("mmaterial", "XML material description", "xml", None, True,
                        "plain XML")
    if ext == "mfi":
        return FileType("mfi", "Font metric table (pairs with .png atlas)", "text", None, True,
                        "CSV-like text")
    if ext in ("h", "txt", "log", "bat", "ini", "xml"):
        return FileType(ext, f"Text/build file (.{ext})", "text", None, True, "plain text")

    # Last resort: sniff for text vs binary.
    sample = data[:512]
    if sample and all(c == 9 or c == 10 or c == 13 or 32 <= c < 127 for c in sample):
        return FileType("text", "Unknown text file", "text", None, True)
    return FileType("unknown", f"Unrecognised binary (magic={data[:4]!r})", "binary", None, False)
