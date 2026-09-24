"""script_explorer.py -- launcher for the RF4S cutscene editor.

    python script_explorer.py [folder with rf3.mc]

The editor itself is the `cutscene_editor` package (scenes in rf3.mc, dialogue in
rf3mc.<locale>, Event Manager conditions in em.bin, one undo history). This module only
starts it and keeps the old import name working.
"""
from cutscene_editor import (CutsceneExplorer, collect_xrefs, entry_keys_text,
                             main, map_enter_type, parse_entry_keys, recipe_types)

__all__ = ["CutsceneExplorer", "collect_xrefs", "entry_keys_text", "main", "map_enter_type",
           "parse_entry_keys", "recipe_types"]

if __name__ == "__main__":
    main()
