"""script_explorer.py -- launcher for the RF4S cutscene editor.

    python script_explorer.py [folder with rf3.mc]

The editor itself is the `cutscene_editor` package (scenes in rf3.mc, dialogue in
rf3mc.<locale>, Event Manager conditions in em.bin, one undo history). This module only
starts it.
"""
from cutscene_editor import main

if __name__ == "__main__":
    main()
