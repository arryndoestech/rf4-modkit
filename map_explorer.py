#!/usr/bin/env python3
"""Launch the RF4S map editor (the `map_editor` package).

    python map_explorer.py                 # browse every map under Bundle/
    python map_explorer.py MAP_DUNG_A04    # open one map by name, or pass a .rf4m path
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from map_editor import main  # noqa: E402

if __name__ == "__main__":
    main()
