"""RF4S map editor.

Edits an .rf4m map together with its two sidecar files -- the search-item spots
(SI_*.bin) and the area's encounter table (Gen*.bin) -- with one undo history across
all three.

    python map_explorer.py [MAP_NAME | path.rf4m]     # the standalone window

Modules:
    document   the editing model: files, undo/redo, dirty tracking, change events
    render     ground texture loader, background image, overlay primitives, PNG export
    view       the map canvas (layers, hit-testing, zoom, pan, hover)
    tools      canvas tools (select, paint, fill, rectangle, pick, add, warp)
    inspector  the selection-driven Inspector tab
    tabs       Objects / Map / Gates / View / Problems tabs
    dialogs    resize grid, raw chunks, flag reference
    panel      MapEditorPanel: the embeddable editor
    app        MapExplorer: the standalone window
    attrs      what every ATTR bit means
    data       game-data lookups (map ids, sidecar files, names)
"""
import pathlib as _pl
import sys as _sys

_HERE = str(_pl.Path(__file__).resolve().parent.parent)
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

from .attrs import (ATTR_BIT_HELP, KNOWN_ATTR_VALUES, PAINT_FLAGS, STAIR_CHOICES,  # noqa: E402,F401
                    STAIR_FIELD, SURFACE_CHOICES, SURFACE_FIELD, attr_bit_help, attr_notes,
                    stairs_help, surface_help)
from .data import (extracted_index, find_extracted, gen_file_for_map, load_rooms,  # noqa: E402,F401
                   si_file_for_map)
from .panel import MapEditorPanel  # noqa: E402,F401
from .app import MapExplorer, main  # noqa: E402,F401

__all__ = ["ATTR_BIT_HELP", "KNOWN_ATTR_VALUES", "PAINT_FLAGS", "STAIR_CHOICES", "STAIR_FIELD",
           "SURFACE_CHOICES", "SURFACE_FIELD", "attr_bit_help", "attr_notes", "stairs_help", "surface_help", "extracted_index", "find_extracted",
           "gen_file_for_map", "load_rooms", "si_file_for_map", "MapEditorPanel", "MapExplorer",
           "main", "warm_caches"]


def warm_caches():
    """Build the lookups the first map open would otherwise pay for (safe on a thread)."""
    from . import data
    from rf4s_modkit import gamenames, map_names, soundtable
    data.extracted_index()
    data.load_rooms()
    data.item_names()
    map_names._ids_by_file()
    data.map_summaries()            # the MGRP / gate / chest checks of every map
    data.rf3mc_path()               # walks the whole Bundle folder for the game's rf3.mc
    len(soundtable.SOUND_LABELS)    # the MGRP panel's area music
    gamenames.table("characters")   # gate monsters, script NPCs
