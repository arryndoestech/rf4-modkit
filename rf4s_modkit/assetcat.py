"""assetcat.py -- what kind of game file a name is (texture, voice line, map...), for the asset
explorer's Category column and filter.

Decided from the name alone (extension and the game's own naming prefixes), so ~38k files are
categorised instantly without opening any of them. The categories follow what a modder is looking
for, not the container format: a map's search items (SI_*.bin) and monster spawns (Gen*.bin) sit
with the maps, the AI and attack-timeline .bin files have their own groups, and every rf3Txt* /
rf3mc.<lang> file is text whatever its extension.
"""
from __future__ import annotations

# (key, title, one-line description) in the order the filter lists them
CATEGORIES = (
    ("audio", "Audio", "voice lines, music and sound effects"),
    ("video", "Video", "movies"),
    ("texture", "Textures & images", "textures and pictures"),
    ("model", "3D models", "models and their materials"),
    ("anim", "Animations", "skeletal animations"),
    ("portrait", "Portraits", "dialogue portraits (Newlywed mode)"),
    ("map", "Maps", "maps, their search items (SI_) and monster spawns (Gen)"),
    ("ai", "Monster AI", "enemy behaviour scripts (AI_)"),
    ("attack", "Attack timelines", "attack animations' hitboxes, effects and sounds (as_)"),
    ("data", "Game data tables", "item, monster, skill and shop tables (rf3*.bin)"),
    ("text", "Text & dialogue", "dialogue and names in every language"),
    ("script", "Scripts & events", "cutscene scripts (rf3.mc) and the Event Manager (em.bin)"),
    ("ui", "UI screens & fonts", "menus, HUD layouts and fonts"),
    ("shader", "Shaders", "GPU shader programs"),
    ("save", "Save templates", "the game's built-in save templates"),
    ("other", "Other", "configuration and anything else"),
)
TITLES = {k: t for k, t, _d in CATEGORIES}

_EXT = {
    ".ogg": "audio", ".wav": "audio", ".aif": "audio", ".bfsar": "audio", ".bcsar": "audio",
    ".bdat": "audio",
    ".webm": "video",
    ".texture": "texture", ".png": "texture", ".bntx": "texture",
    ".model": "model", ".bfmat": "model", ".bfres": "model",
    ".bfskl": "anim",
    ".psbdata": "portrait", ".emtbytes": "portrait",
    ".rf4m": "map",
    ".minterface": "ui", ".ttf": "ui", ".ttc": "ui", ".mfi": "ui",
    ".glsl": "shader", ".hlsl": "shader", ".inc": "shader", ".shbin": "shader",
    ".bfsha": "shader", ".bcsdr": "shader", ".mmaterial": "shader",
    ".strings": "text",
    ".sav": "save",
}
_SCRIPTS = {"rf3.mc", "em.bin", "emdeb.bin", "emdeb_extra.json"}


def category_of(name: str) -> str:
    """The category key of a file (a path or a bare name)."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    stem, dot, ext = base.rpartition(".")
    ext = "." + ext if dot else ""
    if base in _SCRIPTS:
        return "script"
    if base.startswith(("rf3mc.", "rf3txt", "rf4txt")):
        return "text"
    if ext == ".bin":
        if base.startswith("si_") or base.startswith("gen"):
            return "map"
        if base.startswith("ai_"):
            return "ai"
        if base.startswith("as_"):
            return "attack"
        if base.startswith(("rf3", "fishing", "mapore")):
            return "data"
    if ext == ".h":                        # the developers' headers for the data tables
        return "data"
    return _EXT.get(ext, "other")


def title(key: str) -> str:
    return TITLES.get(key, key)
