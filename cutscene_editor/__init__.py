"""RF4S cutscene editor: browse and edit the Script-VM scenes in rf3.mc, their dialogue in
rf3mc.<locale> and the Event Manager conditions in em.bin, with one undo history.

    python script_explorer.py [folder with rf3.mc]

Modules:
    document    the files, one undo history, byte-exact unsaved tracking
    render      a scene as story rows / listing lines / explanations / overview
    browser     banks grouped with readable names, scenes, search
    view        the Script tab (selectable rows, keyboard, Ctrl-hover)
    inspector   the form for the selected statement
    tabs        Source, Triggers, Overview
    dialogs     prompts (listing, dialogue, line picker, new scene) and the callers list
    em_window   the Event Manager window
    catalog     trigger-type catalogue, bank naming, grammar cheat-sheets, xrefs
    app         CutsceneExplorer, the window
"""
import pathlib as _pl
import sys as _sys

_HERE = str(_pl.Path(__file__).resolve().parent.parent)
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

from .catalog import (collect_xrefs, entry_keys_text, map_enter_type,  # noqa: E402
                      parse_entry_keys, recipe_types)
from .app import CutsceneExplorer, main  # noqa: E402

__all__ = ["CutsceneExplorer", "main", "collect_xrefs", "entry_keys_text", "map_enter_type",
           "parse_entry_keys", "recipe_types"]
