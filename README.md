# RF4S Modding Toolkit

A complete, self-contained toolkit for modding **Rune Factory 4 Special** (PC /
Steam, the XSEED Muteki-engine port). It can read **and write** every asset format
that ships in the game's `.mbundle` archives.

## Quick start (Windows, fresh Python)

You need your own copy of RF4S (Steam). No game data is included here; the tools
read the game's own files. Python is installed for you if it is missing (step 2).

Mods are written into the game's `Bundle\` folder, so it's best to mod a **copy** of
the game and keep your Steam install as it is (you then start the game from the
copy's `RF4S.exe` to try your mods). Any install works, though.

1. **Unzip the toolkit anywhere**, for example into your game copy. If you don't have
   a copy yet, the toolkit makes one for you on first start (step 2). If you unzip it
   inside the copy, it finds the game there on its own, whether it ends up as
   `<copy>\rf4s-modkit\`, `<copy>\rf4s-modkit\rf4s-modkit\` (Windows' *Extract
   All…* adds that second folder) or `<copy>\tools\modding\`:

   ```
   Rune Factory 4 Special\
   ├── Bundle\            ← the game's (Manifest.plist, bundleMain.mbundle, …)
   ├── RF4S.exe
   └── rf4s-modkit\       ← this folder (start.bat, rf4mod_gui.py, README.md, …)
   ```

2. **Double-click `start.bat`** in this folder. The first time, it finds Python 3.10+
   (and offers to install it with winget if there is none), creates a private
   environment in `.venv` here and installs the three libraries into it; that takes
   a minute. After that it just starts the GUI. Keep its console window open while
   you work: closing it closes the GUI, and any error shows up there.

   **By hand instead:** open a terminal in the game folder (in Explorer: click the
   address bar, type `cmd`, press Enter), install the libraries once and start the GUI:

   ```bat
   py -m pip install -r tools\modding\requirements.txt
   py tools\modding\rf4mod_gui.py
   ```

   (`py` is the launcher the python.org installer always adds; `python` works too
   if you ticked *Add Python to PATH*.)
3. **Use the GUI.**
   On the first start it asks which game to use: **Choose the game folder…** (the one with
   `RF4S.exe` and `Bundle\`), or **Make a copy for me…** (pick the game —
   Steam: right-click the game → *Manage* → *Browse local files* shows it — and a
   place for the copy; about 5 GB of disk space).

   Either way it first checks the folder is complete: `RF4S.exe` plus every archive
   the game's `Manifest.plist` lists (packed, or already unpacked), and it names
   anything missing. The map editor and the name / texture lookups read the game's
   files **unpacked**, and the game runs the same from unpacked folders (a missing
   `.mbundle` is simply skipped), so:
   - *Make a copy* checks the archives aren't damaged, then unpacks them straight
     from the original into the copy instead of copying them. The copy never needs
     room for both, and each file's size is checked as it's written. Every archive is
     unpacked, voices included, so voice clips can be replaced in place too. (EN and
     JP clips share file names; unpacked, the game plays the English ones whichever
     voice language is set.)
   - For a folder you choose, it offers to unpack in place, and to delete each
     archive as soon as it is unpacked, which needs only the largest archive's
     worth of free space at a time. Or keep the archives.

   The choice is saved, and the toolbar's **Game folder…** button shows or changes it.

   Then it opens the game's bundles. Pick a map for the **map editor**, or use the
   **Cutscenes** button for the **cutscene editor**. The command-line tool is
   `rf4mod.py --help` (in this folder); `rf4mod.py game` shows or sets the game copy.
4. *(Optional)* check the install: `py tools\modding\rf4mod.py selftest --quick`
   (about a minute; drop `--quick` for the full run, several minutes). It should end
   with `N/N checks passed`. Checks that need extracted files are *skipped*, not failed.

Edits are saved as separate files and never overwrite the game's bundles unless you
choose to; see [Three ways to install a mod](#three-ways-to-install-a-mod).

Everything is grounded in the `RF4S.exe` loader code (reverse-engineered in IDA);
code comments cite the IDA function names and `RF4S.exe+RVA` each fact was verified
against. Comments of the form `docs/NN` refer to the numbered RF4S documentation set
(e.g. `docs/09-file-formats.md`, `docs/15-modding-toolkit.md`), which is kept separately
and is not part of this folder.

```
tools/modding/
├── rf4mod.py            # the command-line tool (start here)
├── rf4mod_gui.py        # the graphical asset explorer (Tkinter)
├── map_explorer.py      # launches the map editor (the map_editor/ package)
├── map_editor/          # the map editor: map + SI + Gen editing with one undo history
├── script_explorer.py   # launches the cutscene editor (the cutscene_editor/ package)
├── cutscene_editor/     # the cutscene editor: rf3.mc + rf3mc.<locale> + em.bin, one undo history
├── gen_opcode_reference.py  # regenerates CUTSCENE_OPCODES.md + opcodes_list.csv from opcode_meta
├── gen_map_names_json.py    # regenerates docs/map_names.json (map id -> name, MAP_* file, minimap sheet)
├── gen_minimap_sheets.py    # renders docs/minimap_sheets/: every minimap picture with its rf3MapMiniPos rows drawn on
├── CUTSCENE_OPCODES.md  # greppable reference: every reversed cutscene opcode + enum-arg values + em.bin ops
├── opcodes_list.csv  # flat list: op_dec, op_hex, mnemonic, handler, category, prototype, description (all 763 + control)
├── selftest.py          # validates the toolkit against your installed bundles
├── README.md
└── rf4s_modkit/         # the importable Python library
    ├── script.py        # rf3.mc cutscene VM    disassemble + edit + author-by-name + triggers
    ├── scriptasm.py     # cutscene ASSEMBLER: listing language + expression compiler (the inverse of script.py)
    ├── entry_types.py   # what each type-table action type keys on (scene trigger catalogue)
    ├── opcode_meta.py    # cutscene opcode names / args / descriptions (editor tooltips)
    ├── bplist.py        # Muteki binary plist  read + write
    ├── mbundle.py       # .mbundle archives     read + repack + Manifest sync
    ├── ident.py         # magic-based file-type identification
    ├── textdb.py        # TEXT string archives  read + write  (translations!)
    ├── matanim.py       # .bfmat material animations  parse + evaluate + byte-exact write (texsrt UV scroll, texture patterns = BM_* eye blinks, opacity fades); JSON dump / retime
    ├── shaderarchive.py # shaders: loose Muteki GLSL (compiled) preprocess/replace + .bfsha FSHA/BNSH source read/extract
    ├── skelanim.py      # .bfskl skeletal animations (FSKA) parse + evaluate; poses / skins a .model (render_skeletal_animation)
    ├── texture.py       # .texture (BC7/RGBA8)  decode->PNG + encode from PNG into ANY template (flipbooks too); .model textures in place
    ├── bcenc.py         # BC1/BC3/BC7 encoders  same-size re-encodes (numpy-accelerated, pure-Python fallback)
    ├── rf4m.py          # .rf4m maps            parse + rebuild + full edit
    ├── mapground.py     # ground-texture atlas  stitch + layer composite + export/import (tile split)
    ├── map_names.py     # map id -> in-game name / MAP_* file, HUD location-band rules
    ├── minimap.py       # map id -> mini_map_* picture + placement (rf3MapMiniPos)
    ├── aibn.py          # AI scripts            disassemble + assemble
    ├── gen.py           # Gen*.bin encounters   read + edit
    ├── nlcl.py          # rf3*/rf4* param tables read + edit (named schemas)
    ├── search_items.py  # SI_*.bin daily pickups read + write + footer parse
    ├── strings_file.py  # Apple .strings        read + write
    └── res_container.py # NN BFRES/BNTX/PSB     inspect
```

## Install

### Requirements

| Component | Version | Why |
|---|---|---|
| **Python** | **3.10 or newer** | the code uses PEP 604 union syntax (`T \| None`) |
| **Tk / Tkinter** | bundled with Python on Windows & macOS; on Linux `sudo apt install python3-tk` (or your distro's equivalent) | needed for the GUI (`rf4mod_gui.py`) and the standalone map editor window. The CLI works without it. |
| **Pillow** | `>=9.0` | every `.texture` decode/encode, the map editor's grid render, the texture viewer in the GUI |
| **texture2ddecoder** | `>=1.0` | decodes BC7/BC1/BC2/BC3 block-compressed textures (most stock textures are BC7) |
| **numpy** | optional | speeds up the BC7/BC3/BC1 *encoders* ~10× (a 512² BC7 tile in ≈ 2.5 s instead of ≈ 30 s); without it the same pure-Python code runs block by block |

Pillow and texture2ddecoder are imported inside `try/except` blocks, so the CLI's
non-image features (`bplist`, `mbundle`, `textdb`, `aibn`, `strings`, `nlcl`, `gen`,
MOBJ/MAPJ edit, `selftest`) still work without them — but for the GUI, the map editor,
and any texture work, install both.

### Standard install (pip + virtualenv)

The [Quick start](#quick-start-windows-fresh-python) above is enough on Windows. For
an isolated environment, run this from the folder that contains `tools/` (the game
folder, if you followed the Quick start):

```bash
# 1. Unzip so this folder is tools/modding/ (see Quick start)

# 2. Create + activate a virtualenv (optional but recommended)
python -m venv .venv
# Windows (PowerShell):    .venv\Scripts\Activate.ps1
# Windows (cmd):           .venv\Scripts\activate.bat
# Linux/macOS:             source .venv/bin/activate

# 3. Install the two third-party deps from requirements.txt
pip install -r tools/modding/requirements.txt

# 4. Verify against your installed RF4S bundles (see "Bundle layout" below)
python tools/modding/rf4mod.py selftest
# expect: "N/N checks passed"; checks that need extracted files are skipped
```

### Conda install

```bash
conda create -n rf4s python=3.12
conda activate rf4s
pip install -r tools/modding/requirements.txt
python tools/modding/rf4mod.py selftest
```

### Bundle layout

The toolkit needs the `Bundle/` directory of your game **copy** (the one containing
`Manifest.plist` and the `bundle*.mbundle` archives). Every tool uses the one you chose
(`rf4s_modkit/gamepaths.py`): the folder saved in the toolkit's settings (`settings.json` in
the toolkit folder; an older `%APPDATA%\RF4S Modding Toolkit\settings.json` is moved there
on the next start), set by the GUI's first-start window / **Game folder…** button or by
`rf4mod.py game <copy>` (`rf4mod.py game --forget` drops it). Nothing is guessed from where
the toolkit sits or from environment variables, so no tool picks up a game you didn't mean,
not even the one the toolkit is unpacked inside.

`rf4mod.py game` prints the chosen folder, or why it can't be used.
The contents can be in any of these layouts:

- **The game's own `Bundle/`** (`Manifest.plist` + `bundle*.mbundle`) — a plain copy
  of the Steam install. The asset explorer reads the archives directly; the map
  editor's map list and the cross-file lookups need them unpacked (next layout).
- **`Bundle/<bundle>/`** — bundles unpacked into folders (`bundleMain/`, …) by the
  setup window's *Unpack*, `rf4mod.py unpack` or `rf4mod bundle extract-all`. The
  selftest's per-file checks use this layout.
- **`Bundle/extracted/`** — extracted contents in one flat directory.

The GUI lists the game copy's files on start. Its **Open** menu (*File…*, *Folder…*) looks at
files outside the game (a downloaded mod, `Bundle\00_mods`, exported files) from any folder,
no fixed layout required; *File…* on a `.mbundle` or a `Manifest.plist` lists the files inside
it. **Back to the game** lists the game's files again. `python rf4mod_gui.py <path>` opens any
of these from the command line.

### Verifying the install

```bash
python tools/modding/rf4mod.py selftest
```

The selftest exercises every reader/writer round-trip against your installed
bundles and reports per-check pass/fail. Tests that need data you haven't extracted
are *skipped*, not failed. A green run looks like:

```
…
  [PASS] mapground tile 0 at screen top-left  (tile-0 pixel matches stitched (4,4))
  [PASS] MAPJ f5 = dest_map (Selphia exits)   (f5 ids=[4, 28, 32, …])
…
66/66 checks passed
```

If you see fewer-than-expected passes:

- **Pillow missing**: every `texture` / `mapground` / image check skips with
  `Pillow not installed`. Install with `pip install Pillow>=9.0`.
- **texture2ddecoder missing**: BC7 decode skips with `texture2ddecoder not
  installed`. Install with `pip install texture2ddecoder>=1.0`.
- **Bundles not extracted**: most map/texture/text checks skip with `no … extracted`.
  Either extract them with `rf4mod bundle extract …` or point the toolkit at the
  full `Bundle/` directory (see "Bundle layout" above).
- **Real failure (`[FAIL] …`)**: file an issue with the failing check's name and
  the file (if any) it was operating on.

### Troubleshooting

**Windows: `python` not found.** Install Python 3.10+ from <https://python.org>;
during install, tick *Add Python to PATH*. Or use the `py` launcher (`py -3.12`).

**Linux: `ModuleNotFoundError: No module named 'tkinter'`.** Tkinter ships
separately from Python on many distros. Install:
- Debian/Ubuntu: `sudo apt install python3-tk`
- Fedora/RHEL:   `sudo dnf install python3-tkinter`
- Arch:          `sudo pacman -S tk`

**macOS: GUI text rendering looks tiny.** Use the python.org Python (not the
Homebrew one) — its Tk bundle has Retina support; Homebrew Python uses a
non-HiDPI Tcl/Tk by default.

**`ImportError: texture2ddecoder requires a C extension`** on a fresh OS install.
You need a C build toolchain for the wheel-less platforms. Modern wheels exist for
Windows / macOS / Linux x86_64 + arm64 — upgrade pip first
(`pip install --upgrade pip`) and the wheel should grab the right binary.

**Performance: map editor is slow on huge maps at high zoom.** The background image is
`(w*cp, h*cp)` pixels and is rebuilt when the grid or zoom changes (selections, drags and
paint strokes do not rebuild it). Zoom out, or turn the ground texture off in the View tab.

## GUI: the asset explorer

```bash
python tools/modding/rf4mod_gui.py          # auto-loads Bundle/Manifest.plist
python tools/modding/rf4mod_gui.py <path>   # open a manifest / bundle / folder / file
```

A single-window explorer (Tkinter, stdlib) built on the same library. The left pane
is a tree of every asset — open a `Manifest.plist` to browse all six bundles' 38,000+
files **read-on-demand** (so the 4.7 GB `bundleMain` is never loaded whole), or open a
`.mbundle`, a folder of extracted files, or one file.

**Finding files without knowing their names:** every file has a **Category** (Audio,
Textures & images, 3D models, Animations, Maps, Monster spawns (the `Gen` monster generators),
Gathering spots (the `SI_` daily pick-up item pools), Monster AI, Attack timelines, Game data
tables, Text & dialogue, Scripts & events, UI, Shaders, …) and a **Size**. The **Show:**
box next to Filter lists only one category, with its file count, and combines with the
text filter (Maps + `city` = the town maps). Click a column header (Asset, Category, Size)
to sort by it; click again to reverse (Size ▼ = biggest first). Categories come from the
file names (`rf4s_modkit/assetcat.py`), so nothing has to be opened to sort 38,000 files.
**Group maps by area** (on by default) lists the `.rf4m` maps under one header per in-game
area, which opens and closes (all of `MAP_DUNG_M*` under **Rune Prana**, every street of the
town under **Selphia**, a shop's upper floor with the shop, a dungeon's entrance and depths with
the dungeon); untick it for the plain file list. The choice is
kept in `settings.json`.

**Tabs.** Clicking a file opens it in its own tab (a file that is already open just
shows its tab); Up / Down in the list show the next file in the same tab instead. Each tab
keeps its own copy of its file, view and map editor, so edits in one tab are never lost by
opening another: a tab with unsaved changes is marked **•**, and closing it (its **×**, a
middle click, Ctrl+W, or the tab's right-click menu) or the toolkit asks first. With many
tabs open, **◀ ▶** or the mouse wheel scroll the tab row and **▼** lists every tab;
Ctrl+Tab / Ctrl+Shift+Tab switch tabs. Each map tab keeps its own map editor, so more than
ten open maps ask first (tick *Don't warn me again this session* to stop that); objects
still copy and paste between maps with Ctrl+C / Ctrl+V. Opening another folder or file
keeps the open tabs.

Selecting an asset shows a **type-aware viewer**:

| Selected | Viewer |
|---|---|
| `.texture` | decoded image with ½×/1×/2×/4× zoom; **Export View → PNG**; **Replace from PNG…** (same size, own format) |
| `.model` | **Textures** tab: every embedded BNTX card with preview / Export / Export all; **Replace texture…** swaps the selected card in place from a PNG · Structure tab |
| `rf3mc.*` / TEXT | searchable string table; **Export → JSON** |
| `.minterface` / `.plist` / `Manifest` | expandable bplist tree; **Export → JSON** |
| `.rf4m` | **embedded Map editor** tab (map + its search spots and encounter table, one undo history; see *Map Editor*; its sidebar gains an **Events** tab: the map's cutscene scenes, opened in the Cutscene editor) · Chunks · read-only Hex |
| `.bin` (AIBN) | opcode disassembly; **Export → .txt** |
| `Gen*.bin` | monster spawns: a **picture of the table's map** with its gates (◆) and monster points (●) — drag them, or `+ gate` / `+ spawn` then click the picture — beside the map editor's **Encounters** pane (gates, weight, delay, min/max, rosters with pick weights). **Open in map editor** switches to the full editor on that map; **Save table…** writes the file |
| `rf3NpcParam.bin` | **monster/character editor** — resolved roster (name + kind) + full sheet (drops w/ item names, element affinities %, status resists, AI file) + per-field edit (stats/drops/8 elements/8 resists) + loose-override Save |
| `SI_*.bin` | **search-item spot editor** — daily ground-pickup spots, two panes: **Spots** (move x/y with live tile preview, assign a pool per spot) and **Pools** (first-class: add/delete pools, edit item id/weight per entry with names + live ~% odds, shared-pool "used by" display). Guards: u8 weight-wrap warnings, in-use pool delete block, unassigned-pool not-saved warnings. See `docs/16`. |
| `rf3*.bin` (NLCL) | param-table grid editor (named fields where decoded); **Add row (copy of selected) / Delete row** with the per-table "does the engine read an added row" verdict shown above the editor |
| `em.bin` / `emdeb.bin` | identified + **Open Event Manager…** (the Cutscene editor's Event Manager window: value edits, add / remove entries, conditions and actions) |
| `.strings` | key/value table |
| `as_atk_*.bin` | attack timeline: rendered per-frame view + **Edit** tab (canonical listing, *Assemble & apply*) |
| `rf3PresentNpc*.bin` / `rf3MonsterPresent.bin` | gift preferences / taming foods with **set / signature / remove** controls and Save |
| `rf3Schedule.bin` | per-(NPC, state) itineraries with **apply / add / remove stop** controls and Save |
| `rf3route.bin` / `rf3RouteResult.bin` | navigation graph tree (rooms → nodes → edges), **path query**, JSON export/import, next-hop matrix rebuild |
| `.psbData` / `.emtbytes` | E-mote portrait atlas (zoomable, Export PNG) + PSB summary |
| `.model` / `.bfskl` | NN container structure |
| anything else | identification + hex preview |

`Extract…` saves the selected asset's raw bytes to disk. Image/JSON viewers degrade to
a hex view if `Pillow`/`texture2ddecoder` aren't installed.

## Map Editor

```bash
python tools/modding/map_explorer.py                 # browse all 872 maps
python tools/modding/map_explorer.py MAP_DUNG_A04     # open one map (name or .rf4m path)
python tools/modding/rf4mod.py mapview MAP_DUNG_A04   # same, via the CLI
```

The editor (`map_editor.MapEditorPanel`) is **embedded in the main GUI**: selecting any
`.rf4m` opens it as the front **Map (edit)** tab, and map edits flow into the GUI's working
copy (so `Extract…` saves them). Outside the GUI, the same panel runs as a standalone
program with a map list (`map_explorer.py` / `rf4mod mapview`).

It edits a map **together with its two sidecar files** -- the search-item spots
(`SI_*.bin`) and the area's encounter table (`Gen*.bin`) -- with **one undo history**
across all three.

**Layout.** A toolbar (Save menu, Undo / Redo, tools, zoom, Validate) above the map canvas
and a sidebar with six tabs (it opens on View):

| Tab | What it does |
|---|---|
| **View** | layer toggles (kept in `settings.json`, like the ground display, scenery and ATTR opacity, so every map and the next start open the same way: ATTR fill, cell edges, grid lines, each entity category, name labels, warps, warp destinations, search spots, monster gates, script NPCs), **draw sprites** (on by default: each object's art drawn where and as large as the game draws it, in the game's depth order, right on the ground under the ATTR fill and the warps -- bridges, doors, walls, houses; a selected one gets a frame around its sprite and shines through the ATTR fill; **sprite borders** outlines every one in red above the ATTR fill, invisible walls included), **Show objects as in** (take the game flags from a slot save, any `rf4_sNN.sav`, or the running game: flag-gated objects such as the Dragon Lake bridge appear or turn into a dashed outline exactly as that save would show them), ground texture display + ATTR opacity, the **scenery** layer (the map's over-model cards, drawn where the game puts them), ground-art export / import |
| **Inspect** | options for the active tool + a form for whatever is selected: an **entity** (type picker with search, position, scale / rotation, and only the fields that type actually reads, each labelled with its meaning, flag names, ore config and the other entities wired to the same flag; *show all 16 raw fields* for everything else), a **warp** (zone, destination with search, arrival, facing, disable flag, *Open destination*), a **search spot** (position + drop pool with item search and live odds; warns when the weights wrap the game's one-byte sum), a **gate position / monster spawn point**, or -- with nothing selected -- the tile under the pointer |
| **Objects** | everything on the map, grouped (entities, map parameters, warps, search spots, monster gates, script NPCs) and filterable; picking a row selects it and scrolls it into view |
| **Map** | season tag (MSEA), MGRP as checkboxes + area-group dropdown (raw hex too), the three MLIG tints with colour pickers (and which type-12 records override them), display layers (MTXN count), grid size + **Resize grid…**, **Raw chunks…** (hex editor for any chunk), and a summary |
| **Encounters** | the `Gen*.bin`: gates (kind, weight, min / max alive, spawn delay; add a copy, remove, *make private* to unshare blocks), the selected gate's roster (add / replace / remove monsters), and adding gate positions / monster spawn points on the map |
| **Events** | (in the asset explorer) the map's cutscene scenes from its event bank in `rf3.mc`, biggest first with a dialogue preview; double-click or *Open in Cutscene Editor*; *New scene on this map…* |
| **Problems** | validation of all three files -- including monster spawn points with no walkable ground (ATTR bit 0x01 / 0x20) within their radius, where the game then spawns every monster on the point itself, and gate positions outside the map; selecting an issue selects its object |

**Tools** (toolbar or key while the map has focus):

| Tool | Key | Use |
|---|---|---|
| Select | V | click selects (markers and borders first, then warps, then the inside of a sprite; clicking the selection again -- press and release without moving -- steps to the next thing under the pointer), drag moves the selection (whole tiles, keeping the sub-tile offset; hold Shift for free placement); a selected warp shows 8 handles to resize it; double-click / Ctrl+click a warp opens its destination (also where other objects overlap it) |
| Paint | B | paint the ATTR value with a 1-9 tile brush (`[` / `]`); right-click picks a value; Shift+click draws a line from the last painted tile |
| Fill | G | flood-fill the clicked region, or replace that value on the whole map |
| Rectangle | R | drag a rectangle and fill it |
| Pick | I | take a tile's value, then return to the previous tool |
| Add | A | place an entity (searchable type list), a search spot, a gate position or a monster spawn point |
| Warp | W | drag out a new warp zone |

The ATTR value for Paint / Fill / Rectangle is set with one checkbox per flag, a dropdown
for the surface field (the loader keeps at most one of those per tile, so two cannot be
picked), presets, a raw hex entry, or a click in the list of values the map already uses.
Hover any flag for what the game does with it (and whether that is known at all).

**Keys:** Ctrl+Z / Ctrl+Y undo / redo · Ctrl+S saves every changed file · Delete removes
the selection · Ctrl+C / Ctrl+X / Ctrl+V copy, cut and paste an entity, warp, search spot, gate position or
monster spawn point -- also onto another map (it pastes at the pointer; a gate point goes
into the gate chosen in the Encounters tab, or the map's only gate; right-click empty map for *Paste here*;
a map already holding the game's 40 entity / 10 warp chunks refuses) · arrows nudge it by a tile (Shift: one sub-unit) · Esc clears it · `+` / `-`
/ `0` zoom / fit · the wheel zooms at the pointer · Ctrl+wheel / Shift+wheel scroll · middle-drag pans · Ctrl+hover a tile
shows its ATTR decode.

**Editing rules.** Every field commits on Enter or when it loses focus, as one undo step,
and only when the value changed; a failed edit restores the files and says why. A press
becomes a drag only after 4 px, so clicking never nudges anything, and a whole drag or
paint stroke is one step. **Unsaved changes are guarded** -- switching map (list, file,
warp) or closing asks first, for the map *and* its sidecars -- and every file saves through
its own Save dialog (never over the game's extracted files); **Save map** warns before
writing a map the loader would choke on. The raw chunk editor refuses an edit that would
leave the map unreadable. **Export PNG** (Save menu) writes exactly the current view,
transparent where no base layer is drawn.

**Validate** checks the map against the loader's actual rules: unknown chunk tags, missing
MGRP / ATTR / MTXN, the fixed pointer-array capacities (10 MAPJ, 40 MOBJ, 6 MTXN chunks),
multi-record chunks (only the first record is read), MOBJ types past the sprite band,
objects and zones off the grid, warps to unknown maps, **the ground atlas against the ATTR
grid** (below) -- the same checks as `rf4mod map validate` -- plus the encounter table
(weights vs. spawn points, empty tables, ids outside the gate / monster ranges) and the
search spots (empty pools, one-byte weight wrap, spots off the grid).

**Script NPCs:** actors the map's *event script* places (`EventSpawnNpc`, `EventSpawnNpcVariant` or
`EventSpawnNpcEx` in the map's `rf3.mc` bank -- NPCs, monsters such as the hungry Silver Wolf
in Sechs Territory (MAP_DUNG_L13), and interactibles such as char 269 "Search") are not in the `.rf4m`;
the *script NPCs* layer shows them, and clicking one opens its script line in the
Cutscene editor.

Code: `map_editor/` -- `document` (files, undo, dirty tracking), `render` (ground loader,
background, overlay primitives shared by canvas and PNG), `view` (canvas), `tools`,
`inspector`, `tabs`, `dialogs`, `panel`, `app`, `attrs` (what every ATTR bit means),
`data` (map ids, sidecar files, names). Every map edit goes through the verified `rf4m`
writers and re-serialises a byte-valid map.

### Resizing a map, and why the atlas check exists

The ATTR grid is the **only** thing the engine sizes a map from, so changing it is never
a local edit. `Map_SpawnEntity` derives the ground-atlas tile grid from ATTR alone —
`cols = ceil(24*W/512)`, `rows = ceil(24*H/512)` — then loops `i` over `cols*rows` and
loads tile `i` as **archive id `base + i`**, with no bounds check of any kind. Tiles of a
set occupy consecutive ids (`MAP_FIELD_01_0000`…`_0015` are 8813…8828 and `_1000` follows
at 8829), so a map whose grid outgrew its atlas does *not* draw blanks: it loads whatever
files come next — the overlay layer's tiles, then the next map's set — and shows them as
ground. `map validate` catches exactly this:

| finding | what it means |
|---|---|
| **missing tiles** (ERROR) | the grid asks for more tiles than the set ships; those cells draw another set's art. The message names the exact files to author |
| **past 96 tile slots** (ERROR) | `Map_SpawnEntity` keeps one widget pointer per tile in its 888-byte work buffer from `+8`, and the decoration-model pointer sits at `+776` → **96 slots**. Tile 96 overwrites it, 97 the task pointer, 98 the archive id. The biggest shipped map needs 30 tiles, so only an edited map can hit this. Checked from ATTR alone, no texture files needed |
| **extra tiles** (WARN) | more tiles than the grid spawns; harmless (four shipped overlays do it) but usually means the grid shrank |
| **interior gap / short of extent** (WARN) | tiles are pitched at exactly 512 px, so an old last-column (narrow) tile that a resize turned into an interior one leaves an untextured strip |

Swept over all 872 shipped maps (1270 tiled + 139 single layers): **no stock map trips the
ERRORs**, and the four `extra` hits are the same four the ground-texture notes flag as not
matching the grid formula.

`rf4mod map resize-attr` does the resize *and* prints the derived-artefact list up front:

```bash
python rf4mod.py map resize-attr MAP_FIELD_01.rf4m --width 150 --height 150 --dry-run
```

It reports the extent change, the old→new tile grid (and loudly whether the **column count
changed**, because tiles are indexed row-major — a different `cols` moves *every* existing
tile to a different screen cell, so the atlas has to be re-laid-out rather than extended),
the exact tile files to author, entities and warp zones that fell off the grid, cropped-away
ATTR cells, and the off-file knock-ons (the map's `rf3MapMiniPos` minimap record, warps in
*other* maps that arrive in this one, and the seasonal sibling `.rf4m` files that share the
atlas). `--origin X,Y` pads the left/top and moves MOBJ/MAPJ positions with the terrain;
`--fill` sets the new cells (default `0x2`, the block bit, so padding is solid wall). Both
commands take `--dir` for the tile folder and `--map MAP_NAME` when the file is a working
copy whose name no longer resolves the texture set.
The safe order for the art is **export the layer before the resize, resize, then import it
back** — the exporter takes its aspect from the map's current ATTR.
## Map ids, names and minimap sheets

```bash
python tools/modding/gen_map_names_json.py      # (re)build docs/map_names.json from the vendored tables
python tools/modding/gen_minimap_sheets.py      # render docs/minimap_sheets/ (needs Bundle/ + Pillow)
python tools/modding/gen_minimap_sheets.py --labels names --clean --zoom 4   # vanilla pictures + room names -> docs/minimap_sheets_named/
```

`docs/minimap_sheets/` holds one annotated PNG per minimap picture (reveal rects, origins,
scale extents and the NPC-icon spots of interiors drawn over the sheet) plus an index README.
`docs/minimap_sheets_named/` is the clean set: the plain picture at 2048 px with each room labelled
by its name from `docs/map_names.json` (duplicates numbered `_01..N`), and `labels.csv` /
`labels.json` mapping each label back to its map id.

`docs/map_names.json` is the map-id registry: for every map id `0..873` the in-game name
(`rf3TxtMapName`, row = id + 1), the `MAP_*` file, a note where the HUD's location band
deviates from that name, and the **minimap** block. The library behind it:

| Module | What it answers |
|---|---|
| `map_names.py` | `map_name(id)` in-game name · `map_file(id)` / `map_id_for_file("MAP_ROOM_06A.rf4m")` · `is_building_entrance(id)` (signboard warps) · `label_note(id)` (farm/barn names, maze floor, the Cliff ↔ Volkanon Bridge swap) |
| `minimap.py` | `texture(id)` the `mini_map_*.texture` the HUD draws · `variants(id)` the save-state swaps · `record(id)` origin / fog-of-war rect / Q12 scale / NPC-icon parent sheet · `pos_to_sheet(id, x, y)` · `bake()` re-vendors the table from your bundle |

How the game picks the picture (from `Minimap_BuildForMap`, RF4S.exe+0x13B3F0): the map id
indexes **`rf3MapMiniPos.bin`** (873 × 52 B); dword 0 is a sheet number and the picture is
resource **12199 + sheet** (`mini_map_00_city` … `mini_map_dung_q04`; 73 or > 87 → the blank
`99_dummy`). Then a few sheets are swapped by save state: town (a scene flag + a Prince Point
order), Water Ruins (story ≥ 0x52), farm (`REG_FARM_LV`), your room (`REG_MYROOM`, Newlywed
mode uses the `_sk_` set), barns (`REG_MON_HOUSEn_L/R_LV`), and two field sheets (scene flags
70 / 134). Sharance Maze floors are composed at runtime from the `mini_map_rnd_*` tiles.
Many maps share a sheet; the rest of the record places the map on it and drives the
room-by-room fog-of-war reveal. Full field list: `rf4s_modkit/minimap.py`.

## Cutscene Editor

```bash
python tools/modding/rf4mod_gui.py     # open the Manifest, then toolbar "Cutscenes"
python tools/modding/script_explorer.py [folder with rf3.mc]   # or on its own
python tools/modding/gen_opcode_reference.py   # (re)build CUTSCENE_OPCODES.md
```

Edits the game's cutscene/event scripts: **`rf3.mc`** (the compiled Script-VM bytecode —
tens of thousands of scenes), the per-locale **`rf3mc.<locale>`** dialogue text, and the Event
Manager conditions in **`em.bin`**, with **one undo history** across all three. Reached from the
main GUI's **Cutscenes** toolbar button, the **Open in Cutscene Editor →** button on a map's
scene list, or by clicking a *script NPC* in the map editor (it opens on that exact line). It
reads the files by basename from the loaded source, so it works best with a **Manifest** open.

Its foundation is a **complete reverse-engineering of the Script VM opcode table** (702
dispatchable slots, `g_sceneActionHandlerTable`): every reachable opcode has a curated
author-facing **name, argument labels and description** (`rf4s_modkit/opcode_meta.py`, and the
greppable [`CUTSCENE_OPCODES.md`](CUTSCENE_OPCODES.md) reference).

**The window** has three panes:

- **Browser** (left) — banks grouped and named: *Characters* (`Nancy  (bank 19)`), *Villager
  behaviour*, *Maps* (`Map 274 · MAP_DUNG_A04 (Yokmir Forest)`), sub-events, quests. Each bank
  lists its triggered scenes first, then subroutines. The search box finds scenes by **dialogue**
  (case-insensitive phrase), **speaker**, **opcode** (name or number), **Event Manager entry**, or
  jumps to a **bank #**. Empty map banks are hidden unless *empty banks* is ticked.
- **Script** (middle) — the open scene. The **Story** view reads like a script:
  `Nancy: “…”` in the speaker's colour, actions by name (`▸ GiveItem(reg1, 1, reg3)`),
  flow as `if not (FLG_X) → go to L2`, choice options on their own rows, and a header saying
  **when it plays** (its triggers and the em.bin gates). **Code** shows the disassembly; *addresses*
  adds byte offsets. Arrow keys / PgUp / PgDn move the selection, Enter jumps to the editor,
  Delete deletes. **Hold Alt over a line** for the full explanation (prototype, every argument
  decoded, speaker, Event Manager entry).
- **Inspector** (right) — a form for the selected statement, applied as you go (Enter or
  leaving the field): a **dialogue line**'s text (Ctrl+Enter), its line id, *Find a line…*,
  *As new line* (a fresh id in every locale) and *Show other locales*; a **speaker** picker with
  the portrait side; each **action argument** in listing syntax (`actor(Forte)`,
  `map(MAP_CITY_00)`, `FLG_X + 1`, `@0xNNNN` for an existing expression) with a named-value
  picker where the argument has one; the **numbers in a condition or STORE** (branch targets and
  every other offset are untouched); each **choice option**'s text, line id and destination.
  *Add after* inserts a spoken line (speaker + text) or any statements in listing syntax,
  *Delete* removes the statement, *Callers…* lists every CALL / jump / branch / choice that lands
  on it, and *What it does* repeats the explanation.

The **Source** tab shows the scene as a re-assemblable listing — labels,
actions as calls (`GivePlayerItem(258, reg0 + 1, 0)`, `EndDialogue()`), control statements as
keywords with the condition in parentheses (`BR_Z (REG_WIFE_ID == 11) -> L1`, `STORE (FLG_X = 1)`,
`PROMPT_CHOICE CANCEL -> L2, #123 -> L3`, `JMP L1`); *Check* reports the failing line inline and *Apply to
scene* re-assembles it (the scene's entry jumps to the new body, so nothing else moves). The
**Triggers** tab lists the bank's type table (every registration with its decoded keys) and mints
**new scenes**: pick when it plays (the trigger catalogue supplies a recipe per type: which bank,
which keys, the ordering caveat), its keys and a body; a note warns when a registration would
**shadow** the bank's existing scene of that type. *Change keys…* and *Remove* edit existing
registrations. The **Overview** tab summarises the scene: speakers, every dialogue line,
the Event Manager entries it gates on or runs, the flags and variables it writes, and its
control flow.

**Event Manager…** opens the em.bin window. em.bin holds the game's 272 rules, each asked "is this
true right now?" to decide which talk plays, whether a shop is open or which event fires today:

- **Browser** (left): entries grouped by topic (dates, marriage & family, everyday events, shops,
  boss rematches…), each with an English description (translated from emdeb's Japanese labels),
  what it holds (✔ condition, ▶ actions) and how many scene statements use it. The search box
  matches descriptions, names and everything an entry checks or changes (`kiel love`,
  `REG_DATE_COUNT`, `rain`); Enter opens the first match.
- **Rule** (middle): the entry as sentences — "True when any one of these ways holds", each way's
  requirements ("Hour of the day is at least 6", "Dating Amber", "“The date is today” is true"),
  its other test (condition B), the actions scenes run, and who uses it (double-click a scene to
  open it, or an entry to go there). Hold **Alt** over a line for its exact em.bin form.
- **Inspector** (right): edit the selected line with pickers — what a requirement checks (a game
  value, a variable, another entry), how ("is at least", "is less than"…), and against what (named
  values for seasons, characters, maps, on/off); what an action changes and how ("set to", "add"…).
  **Add an alternative (OR)**, **Add a requirement (AND)**, **Add a way**, **Add an action
  before / after** and **Remove** work next to the selection. New lines start as placeholders
  that change nothing, so em.bin keeps working at every step.
- **Checks**: the toolbar counts problems. Errors (a condition that loops back to itself, an entry
  that doesn't exist, dividing by zero) make Save refuse; warnings flag things like the weather
  queries, which RF4S never answers (they always read 0). **Type it…** still takes the text form
  (`Hour >= 6 AND Season == 1`, `alt: REG_WIFE_ID = 3`, `CALL EV_FOO`).

Selecting `em.bin` in the asset explorer opens the same window.

**Undo / Redo** (↶ ↷, Ctrl+Z / Ctrl+Y) cover every edit — script, dialogue in every locale and
em.bin — byte-exact. A step stores only what changed; an edit that changes nothing records
nothing. *Unsaved* is a byte comparison against what was loaded or saved, so undoing back to it
makes the file clean again, and closing or opening another `rf3.mc` asks first. **Save** (Ctrl+S)
writes the changed files straight into your game folder without asking, over the copies the
game loads: an unpacked `Bundle\bundlePatch1\rf3.mc`, `Bundle\bundleMain\rf3mc.<locale>` and so
on, or an existing `Bundle\00_mods` override. A file the game only has inside a packed
`.mbundle` goes to `Bundle\00_mods`. The first time a file is overwritten, the original is copied
to `ModdingBackup\` in the game folder, keeping the same path; copy it back to undo everything. A
file opened with *Open rf3.mc…* is saved back where it was opened. *Save … as…* writes a copy
anywhere, and *Install as loose files* puts copies in `Bundle\00_mods`. Restart the game to see
changes. *New lines in all locales* gives a new dialogue line the same id in every `rf3mc.<locale>`
(untranslated), so it shows in every language.

Everything the editor does is also on the CLI (`rf4mod script listing / asm / check / insert /
set-val / set-target / set-speaker / entries / add-entry / remove-entry / set-entry`, `rf4mod em …`,
`rf4mod text add --pad-to N`). Corpus-verified: every operand in the shipped file compiles back to
identical bytes-or-text, and the type tables are read count-exact (10,169 registered scenes).
`selftest.py` covers the container round-trip, in-place and repointed argument edits, literal
edits, trampoline insert/rewrite, dialogue rewrite, search, the explanation for every opcode, and a
headless drive of the editor (`test_cutscene_editor_authoring`, `test_cutscene_editor_workflows`).

Code: `cutscene_editor/` — `document` (the files, one undo history, unsaved tracking), `render`
(story rows, listing lines, explanations, overview), `browser`, `view` (Script tab), `inspector`,
`tabs` (Source / Triggers / Overview), `dialogs`, `em_window`, `catalog` (trigger types, bank
names, grammar help, xrefs), `app` (the window).


**Portrait faces.** *Add dialogue line* and a selected speaker cue both have a **Face**
button that shows the current face as a picture. Click it to see all of that speaker's faces
and pick one. The face is the cue's first argument (`rf4s_modkit/portraits.py`, tables read
from `RF4S.exe` into `refdata/portrait_faces.json`):

- **Story mode (the main game)** draws the classic 2D portraits for every speaker: the
  villagers, the children, Pico and the guests. Face id N is the N-th
  `<NN>_<NAME>_face_…` file of that character. Ids 0–5 are the same six moods for everyone
  (normal, angry, crying, smile, surprised, shy); the rest are per-character, so the pictures
  are the names. 255 / 254 are the SP1 / SP2 portraits.
- **Newlywed mode** draws the animated E-mote portraits (`*.psbData`) instead, for the player
  and the twelve candidates. The same id is translated to an E-mote face, and the picker notes
  what it shows there. Ids of 1000 and up (face × gesture) only exist in Newlywed mode.

The outfit (swimsuit, pajama, wedding) follows the character's state; the script doesn't
choose it. The listing names the shared moods (`SetSpeakerVolkanon(right, angry, …)`) and
numbers the rest (`face 29`).

**Box style.** `SetBoxNormal`, `SetBoxShout`, `SetBoxThought`, `SetBoxTrembling` (ops 94–97) and
`SetDialogueBoxStyle` (op 93) set the **message-box style**: 0 normal, 1 shout (jagged box that
shakes, screen flash), 2 thought (cloud box that floats for about a second), 3 trembling (wavy box
that shakes sideways), 4 tail only (no box, op 93 only). The style lasts until changed or the box
closes. Their Inspector and *Add dialogue line* have a **Box style** picker that shows the game's
own box art.

The box's **tail** points at the side of the last speaker cue (`SetSpeaker…(left, …)` or
`(right, …)`), and it only shows while a portrait is up on that side for a named character.
Narration and `SetSpeakerVoice` name plates get no tail. So a thought line needs a speaker cue
on the side where that character's portrait should be. The game's own thought lines always
follow one. The Inspector says where the tail will point, or why it won't show.

**Text checks.** Every line you edit or add is checked the way the game reads it
(`rf4s_modkit/textlint.py`; the grammar is in the RF4S docs, chapter 48, *Text control codes*):

- **Refused**: a `＠‡A,B＠` gender switch without its comma, without the closing fullwidth
  `＠`, or with a side longer than 63 bytes. The game crashes on those.
- **Warned, but applied**: a `＠…＠` the game doesn't know or with a slot number out of range
  (shown as written), an odd number of `＋` (blue) or `／` (red) marks (the colour runs to the
  end of the line), text after a NUL, a stray carriage return.
- **Shown under the text box while you type**, together with a note when a token reads a text
  slot that no `SetVar` opcode in the scene sets.

Save and Install refuse to write while an edited line would crash the game.
## What can be modded, and how

| Format | Extensions | Tool | Round-trip |
|---|---|---|---|
| Bundle archive | `.mbundle`, `Manifest.plist` | `rf4mod bundle` | ✅ full |
| UI layout / config | `.minterface`, `.plist` | `rf4mod plist` | ✅ full (bplist) |
| Game text | `rf3mc.*`, TEXT archives | `rf4mod text` | ✅ full |
| Engine UI text | `.strings` | `rf4mod strings` | ✅ full |
| Textures | `.texture` | `rf4mod texture` | ✅ decode all; **encode from PNG into any template, in the template's own format**: BC7 / BC3 / BC1 are re-encoded by the built-in `bcenc` encoders at the **same size** (the file stays `bundle patch`-able in place), raw formats are kept, `--fmt RGBA8` (4×) / `BC7` / `BC3` / `BC1` force one; flipbook frames and strips; `rf4mod map ground-export` / `ground-import` round-trip a whole ground layer as one PNG |
| Maps | `.rf4m` | `rf4mod map` | ✅ chunk-level; `map validate` checks the game loader's rules **and the ground atlas against the ATTR grid**; `map resize-attr` resizes the tile grid and lists every derived artefact it invalidates |
| Monster/NPC AI | `AI_*.bin` (AIBN) | `rf4mod ai` | ✅ full (token + text); `disasm --annotate` adds the verified operand meanings, `ai ops` / `ai actions` print the opcode and scripted-action references (every handler re-read 2026-09-17) |
| Attack move timelines | `as_atk_*.bin` (690) | `rf4mod asatk` | ✅ decode (`show`/`summary`) + **assembler/editor**: `dump` → edit listing → `asm`, or point edits `set` / `insert --frame` / `delete`; byte-exact on every stock file; GUI Edit tab |
| Event Manager triggers | `em.bin`, `emdeb.bin` | `rf4mod em` | ✅ conditions/actions decode; in-place edit; **structural**: add / remove entries, condition terms and actions from a readable spec (`em add / remove / add-cond / remove-cond / add-action / remove-action`; the container is rebuilt, stock re-serialises byte-exact) |
| Skill XP curves | `rf3ParamSkillExp*.bin` | `rf4mod skill` | ✅ decode + `skill set FILE LEVEL XP` / `--scale PCT` (every level) |
| Monster encounter tables | `Gen*.bin` (NLCL) | `rf4mod gen` | ✅ full: gates / weights / rosters / positions, add & remove gates and monsters (rebuilds the file + footer; all 690 stock files round-trip byte-exact) |
| Game-data param tables | `rf3*/rf4*.bin` (NLCL) | `rf4mod param` | ✅ item prices/stats, crops, recipes, skills, fish spawn/size weights (`Fishing_rate_*`, named fields), schedule spots (`rf3ScheduleID`)…; **rows can be added / removed** (`param add --copy N --set …` / `param remove`; header counts + footer regenerated) and `param info` states per table whether the engine honours an extra row (count read from the file, capped by a constant, or bound to a TEXT twin that must be extended too) |
| NPC gift preferences | `rf3PresentNpc01..27.bin`, `rf3PresentCategory.bin` | `rf4mod gift` | ✅ move items between loved / liked / disliked / neutral, set the FP code and the one −10 "signature" dislike, add range / category entries; the file is rebuilt (sub-list offsets + NLCLINK tail), all 28 stock tables round-trip byte-exact |
| Monster taming foods | `rf3MonsterPresent.bin` | `rf4mod gift monster-set` / `monster-clear` | ✅ the 4 per-species (item, tame bonus) slots |
| NPC daily schedules | `rf3Schedule.bin` + `rf3ScheduleID.bin` | `rf4mod schedule` | ✅ per-(NPC, state) itineraries: set / add / remove stops, JSON decode → edit → encode (index sections recomputed; stock re-encodes byte-exact); spot kinds resolved to rooms |
| NPC navigation graph | `rf3route.bin` (TRCS), `rf3RouteResult.bin` | `rf4mod route` | ✅ rooms → nodes → edges decode / JSON / encode (byte-exact), game-accurate path walk, next-hop matrix regeneration after graph edits |
| Models / skeletons / materials | `.model` `.bfskl` `.bfmat` `.bfsha` | `rf4mod res` | ✅ **`.model` meshes read**: `res model-info` / `model-export` (OBJ + MTL + PNG) / `model-render` (UVs wrap, vertex colour, additive BlendType); ✅ **`.model` meshes written** (`rf4s_modkit.modelwrite`, statically verified, not yet tried in game): `res model-import MODEL SHAPE mesh.obj` replaces one shape's geometry with any vertex / triangle count (memory pool, buffer sizes, submesh, bounds and every relocated pointer rebuilt; an unmodified export re-imports byte-identically; skin weights copied from the nearest original vertex), `res model-transform` moves / scales / rotates a shape in place; ✅ **`.bfmat` material animations played and written** (all 59 rebuild byte for byte): `res model-gif` and Play in the GUI's Model tab show texsrt UV scroll, texture patterns (BM_* eye blinks / emblem swaps, anim_com* frame flips) and opacity fades; the `.bfmat` is found by stem or by material name (SYS_MENU_ANIME_09 -> anim_com09); `res bfmat-info` lists curves (`--json` dumps an editable file), `res bfmat-build JSON OUT` encodes it, `res bfmat-set IN OUT --speed 2` retimes; ✅ **`.bfskl` skeletal animations played** (all 2,001 parse): `res anim-info` (`--json` dump, `--model` binding) / `res anim-gif MODEL ANIM out.gif`, and the Model tab's motion row — bones bind by name, skinned meshes blended through the inverse bind matrices; ✅ **textures embedded in a `.model`** (the BNTX of the 164 map over-models, character / monster / weapon / effect cards): `res texture-list` / `texture-decode` / `texture-encode` replace one texture **in place** in its own block format — file size and every container field unchanged |
| Emote / portraits | `.psbData` (loaded) `.emtbytes` (never loaded by the PC exe) | `rf4mod psb` | ✅ full E-mote PSB v4 reader (all 130 parse; `.emtbytes` header decrypted): `psb info` (atlas, face-frame timelines 0-5 = 通常/怒り/哀しみ/笑顔/驚き/照れ, variables), `psb dump -o DIR [--resources]` (whole tree → JSON), `psb textures -o DIR [--parts]` (RGBA8 / ASTC atlas → PNG, plus every named part crop); ✅ **repaint a portrait**: `psb replace-texture X.psbData edited.png -o out/` (same size; only the atlas bytes change, re-parsed and checked). Keep part outlines where they are — the mesh/part rectangles are absolute atlas pixels |
| Sound-id table | `common_audio_data.bdat`, `voice_en_audio_data.bdat` (`voice_jp_…` ships but is never loaded) | `rf4mod sound` | ✅ `list` / `show` / `find` (all three tables) / `set` volume · priority · flags / point an id at another file / `add` a brand-new id / `remove`; byte-exact rebuild of all 3 stock tables; PlaySound / PlayVoicedSound listings show the file name. New sound: drop `SE_MYMOD.ogg` (or .wav/.flac/.mp3, sniffed by magic) under `Bundle\00_mods\`, `rf4mod sound add common_audio_data.bdat auto SE_MYMOD.ogg -o my.bdat`, `rf4mod install <game> common_audio_data.bdat my.bdat`, restart, `PlaySound(<id>)` |
| Audio | `.ogg` `.wav` `.flac` `.mp3` | `rf4mod ident` | ➡️ swap (standard formats; the loader sniffs OggS / RIFF / fLaC / else MP3 — AIFF is not decoded; the one shipped `UISelect.aif` is referenced nowhere in the exe) |
| Video | `.webm` | `rf4mod ident` | ➡️ swap (re-encode w/ ffmpeg) |
| Images / fonts | `.png` `.ttf` `.ttc` | `rf4mod ident` | ➡️ edit directly |
| Shaders | `.glsl` `.glsl.inc` (bundleMuteki), `.bfsha` | `rf4mod shader` | ✅ the game compiles **only the loose bundleMuteki GLSL** (`mtk_body/item/billboard` = every model, from source at each start, no shader cache): `shader list`, `shader extract mtk_body -o dir` (includes inlined as GL gets them), `shader replace mtk_body_f.glsl edited.glsl -o dir` (checks includes / `#version` / `main`) then `install`. `.bfsha` GLSL is never compiled on PC (the nn::gfx shader init is a stub), so it is read + extracted only (`shader list/extract rf4cmv.bfsha`); `.hlsl` files are never loaded |

✅ = the toolkit fully reads and rewrites it · 🔍 = identify + structural inspect ·
➡️ = standard format, edit/replace with off-the-shelf tools

## Three ways to install a mod

At startup the game indexes **every file under `Bundle\`** (all sub-folders, by file
name) and mounts that index **ahead of** the `.mbundle` archives; the first match
wins. A missing `.mbundle` is just skipped, so the game also runs from a fully
extracted `Bundle\` (verified in `BundleManager_LoadManifest`, the `Bundle/**`
file-system index, and the game's own log). Files next to `RF4S.exe` are **not**
looked at. So:

1. **Loose file (recommended — no repack, uninstall by deleting it).**
   ```bash
   python rf4mod.py install "C:/Games/RF4S" rf3mc.eng my_translation.eng
   ```
   This copies it to `Bundle\00_mods\rf3mc.eng`. **Restart the game** to load it.
   `00_mods` sorts before the `bundle…` folders, so it also wins over an extracted
   original (when a name exists twice under `Bundle\`, the path that sorts first wins).
   `python rf4mod.py mods "C:/Games/RF4S"` lists everything that currently overrides
   the game.
2. **In-place patch (same or smaller size).** Overwrites bytes inside a bundle and
   updates `Manifest.plist`.
   ```bash
   python rf4mod.py bundle patch bundlePatch1.mbundle rf3.mc new_rf3.mc --manifest Bundle/Manifest.plist
   ```
3. **Repack (any size).** Appends the new data and repoints `Manifest.plist`
   (works even on the 4.7 GB `bundleMain`). The runtime reads file offsets from the
   **Manifest**, so keeping it in sync is what matters.
   ```bash
   python rf4mod.py bundle add bundleMain.mbundle ui/Foo.minterface Foo.minterface
   ```

**Unpacking everything.** `python rf4mod.py unpack "C:/Games/RF4S"` extracts every
bundle into `Bundle\<bundle>\` (about 5 GB; a second run resumes). The game and the
toolkit both work from that layout, and you can then edit files in place. It checks
the archives aren't damaged first. With `--delete-archives` each `.mbundle` is deleted
as soon as it's fully unpacked, so it needs only one archive's worth of free space
at a time (keep a backup of the game if you do). The folder argument can be left out
to use the saved game folder. On the command line the voice bundles are left packed
by default (`--voice en|jp|both` to include them; the GUI's setup unpacks both): EN
and JP share every file name, so extracted, the English clips always win whatever the
voice setting says.

> **Always back up `Manifest.plist` and any bundle you patch.** Prefer loose files
> while iterating — they leave the originals untouched.

## Quick examples

```bash
# Identify anything
python rf4mod.py ident path/to/file

# Translate: dump the English catalog to JSON, edit, rebuild
python rf4mod.py text decode rf3mc.eng -o eng.json
#   ...edit eng.json...
python rf4mod.py text encode eng.json -o rf3mc.eng     # refuses lines the game would crash on
python rf4mod.py text check rf3mc.eng                   # list lines the game would show wrongly
python rf4mod.py install "C:/Games/RF4S" rf3mc.eng rf3mc.eng

# View a texture (flipbooks: --frame N, or --strip for every frame side by side)
python rf4mod.py texture decode 00_PLAYER_M_body_00.texture -o player.png
python rf4mod.py texture info confetti.texture            # format, frame list, container offsets

# Re-skin ANY texture from a PNG of the same size. The default (--fmt keep) re-encodes
# BC7/BC3/BC1 sources in their own format at the SAME size (bundle patch-able in place);
# raw sources keep their format; --fmt BC7|BC3|BC1|RGBA8|RGBA4444|ABGR1555|GL_RED_8bpp forces one.
python rf4mod.py texture encode OBJ_BED_00.texture edited.png -o new.texture
python rf4mod.py texture encode confetti.texture cell.png --frame 3 -o new.texture   # one flipbook frame
python rf4mod.py texture encode OBJ_BED_00.texture edited.png --fmt RGBA8 -o new.texture   # lossless, 4x bigger

# Repaint a map's ground: export the stitched layer, edit it, split it back into tiles
python rf4mod.py map ground-export MAP_FIELD_01 -o ground.png          # --layer 1 = overlay
python rf4mod.py map ground-import MAP_FIELD_01 ground.png -o overrides/   # -> MAP_FIELD_201_00NN.texture (BC7, same size)

# Meshes inside a .model (characters, monsters, weapons, map over-model scenery)
python rf4mod.py res model-info NPC_C_BADO.model --bones             # shapes, materials, skeleton
python rf4mod.py res model-export NPC_C_BADO.model out/              # OBJ + MTL + texture PNGs
python rf4mod.py res model-render MAP_CITY_00.model --view top       # textured preview PNG
python rf4mod.py res model-gif ANIM_DUNG_B01.model b01.gif          # one loop of its .bfmat (water scroll)
python rf4mod.py res model-gif BM_05.model bm05.gif --view front     # the boss's eye texture pattern
python rf4mod.py res bfmat-info BM_05.bfmat                          # materials, params, patterns, curve keys
python rf4mod.py res bfmat-set ANIM_DUNG_B01.bfmat fast.bfmat --speed 2   # scroll twice as fast
python rf4mod.py res anim-gif NPC_A_CLORICA.model 00W_002_walk.bfskl walk.gif --view side   # a .bfskl on a character
python rf4mod.py res model-import NPC_C_BADO.model 1 part.obj -o out.model   # replace shape 1 from an OBJ (any vertex count; pool + pointers rebuilt)
python rf4mod.py res model-transform NPC_C_BADO.model 0 --scale 1.2 --rotate 0,45,0 -o out.model   # move / scale / rotate a shape in place

# Textures inside a .model (map over-model scenery cards, character/monster/weapon/effect models)
python rf4mod.py res texture-list MAP_CITY_00.model                    # index, name, format, size
python rf4mod.py res texture-decode MAP_CITY_00.model 3 -o card3.png   # upright PNG
python rf4mod.py res texture-encode MAP_CITY_00.model 3 card3.png -o MAP_CITY_00.model   # same size, in place

# Edit a UI layout
python rf4mod.py plist decode Achievement.minterface -o ach.json
python rf4mod.py plist encode ach.json -o Achievement.minterface

# Tweak monster AI (disassemble, edit, reassemble)
python rf4mod.py ai disasm m08 > m08.txt          # language-style listing (see below)
python rf4mod.py ai disasm m08 --annotate      # with operand meanings/units as comments
python rf4mod.py ai disasm m08 --flat          # one opcode per line, every token explicit
python rf4mod.py ai ops 0x1E                   # what SidestepAroundTarget takes and does
python rf4mod.py ai actions 3                  # scripted action 3 (InvokeScriptedAction 3)
python rf4mod.py ai asm m08.txt -o AI_m08.bin

The listing reads like a small language and assembles back byte-exactly:

```
sub 200:
    if (ActorLevel >= 50) {
        SetActorFlag800000(1)
    }
    if (DistanceToTarget <= 44) {
        if (RandomChance(20)) {
            BackAwayFromTarget(90, 30)      # stop when distance to target = 90 units | time budget frames = 30 frames
            goto 290
        }
    }
    if (DistanceToTarget <= 96 && DistanceToTarget >= 45) {
        r1 += 5
        call 400
    } else if (RandomChance(5)) {
        WaitFrames(8)
    } else {
        SetCooldownTimerA(180)
    }
    return
```

`sub N:` / `N:` are subroutine and goto labels, `if (...) { } else if (...) { } else { }` and
`loop { }` are the block tokens, `end` / `return` / `restart` / `yield` / `goto` / `call` the
control opcodes, `Action(args)` an action (the VM's begin-action marker before it is implied;
write `!Action(args)` to omit it), `rN += v` / `rN = v` the register ops, and conditions are
written as expressions (`DistanceToTarget <= 110`, `RandomChance(50)`, `ActorIsNpcKind`).
`rf4mod ai ops <name-or-id>` explains any opcode.

# Edit a cutscene / event script (rf3.mc): find a scene by its dialogue, read it, then
# reword a line, retune an action arg, or insert a beat — every edit is byte-safe.
python rf4mod.py script find rf3.mc "about to call you" --text rf3mc.eng   # → bank + pc of matches
python rf4mod.py script dev-menus rf3.mc --text rf3mc.eng --bank 18  # the devs' ＊ test menus: event / festival / date → routine pc
python rf4mod.py script space rf3.mc [--bank N]                     # bytecode room left per bank (64 KiB each; fullest first)
python rf4mod.py script disasm rf3.mc --bank 1 --text rf3mc.eng --friendly # read the scene (author names)
python rf4mod.py script set-text rf3mc.eng --line 8709 --text "New line!" -o rf3mc.eng   # reword a line
python rf4mod.py text add rf3mc.eng --text "A whole new beat!" -o rf3mc.eng   # author a NEW line (prints its id)
python rf4mod.py script set-speaker rf3.mc --bank 1 --pc 0x08c2 --speaker Vishnal --side right -o new.mc  # change who speaks
python rf4mod.py script set-val rf3.mc --bank 1 --pc 0x3478 --index 0 --value 258 -o new.mc  # change an arg value / STORE value / choice option's line id
python rf4mod.py script set-target rf3.mc --bank 1 --pc 0x400e --index 1 --target 0x4036 -o new.mc  # retarget a branch/choice destination (validated)
python rf4mod.py script insert rf3.mc --bank 1 --pc 0x3478 --dialogue 66494 -o new.mc         # add a dialogue beat
python rf4mod.py script insert rf3.mc --bank 1 --pc 0x3478 --stmt "BR_Z (FLG_X) -> L1 / DIALOG #5 / L1:" -o new.mc  # a conditional beat
python rf4mod.py script listing rf3.mc --bank 1 --pc 0x3478 --text rf3mc.eng -o scene.txt   # scene as re-assemblable source…
python rf4mod.py script asm rf3.mc --bank 1 --pc 0x3478 --listing scene.txt -o new.mc         # …edit, and put it back
python rf4mod.py script entries rf3.mc --bank 248                                              # a map bank's triggers + keys
python rf4mod.py script add-entry rf3.mc --bank 248 --type 6 --stmt "FRAME 0 / DIALOG #8709 / END" -o new.mc  # a NEW scene
python rf4mod.py em show EV_BOSS_SP_DEAD    # decode a scene's "plays when" condition + effects
python rf4mod.py em new-var FLG_MY_QUEST_DONE          # a NEW game flag (free bit of the 4096-bit store; sidecar emdeb_extra.json)
python rf4mod.py em new-var REG_MY_COUNTER --width 4   # …or a register; usable in em conditions and cutscene listings at once
python tools/modding/script_explorer.py     # …or edit cutscenes visually (story view, inspector, one undo history)

# Inspect a map, then edit a placed-entity (MOBJ) record and save a new map
python rf4mod.py map info MAP_DUNG_A04.rf4m
python rf4mod.py map set MAP_DUNG_A04.rf4m 20 f0=48 f6=6144 f14=500 f15=500 -o test.rf4m
python rf4mod.py map validate test.rf4m               # will the game load it the way you expect?
python rf4mod.py map resize-attr test.rf4m --width 96 --height 64 --dry-run   # + what the resize breaks
python rf4mod.py res info ANIM_DUNG_A02.model

# Edit game-data param tables (NLCL, ~80 tables): prices, equipment, crops, recipes…
python rf4mod.py param info rf3ItemList.bin            # item id → sell price + name
python rf4mod.py param set rf3ItemList.bin 29 sell_price=9999 -o new.bin   # Turnip → 9999G
python rf4mod.py param info rf3ItemEquipmentParam.bin  # weapon/armor ATK/MAT/DEF/MDF/STR/INT/VIT (+ boots word, accessory bit)
python rf4mod.py param set rf3ItemEquipmentParam.bin 328 atk=999 -o w.bin  # Broadsword ATK→999
python rf4mod.py param info rf3CropParam.bin           # crop stage-days + harvest/seed item
python rf4mod.py param info rf3RecipeWeaponA.bin       # result + ingredients
python rf4mod.py param dump rf3UseItemParam.bin -o use.csv             # consumable HP/RP effects
python rf4mod.py param csv rf3ItemList.bin -o items.csv                # the NAMED table view (schema columns + item names)
python rf4mod.py param csv-all -o tables/                              # every rf3*.bin param table -> tables/<stem>.csv
python rf4mod.py param info Fishing_rate_fish_Spring.bin               # fish spawn weight per season x rain zone + size class (named fields)
python rf4mod.py param add rf3RecipeCookFry.bin --copy 3 --set result=120 recipe_id=999 -o fry.bin   # NEW recipe row (count read from the file -> honoured)
python rf4mod.py param add rf3TxtQuest_split3_1.bin --set client_id=2 category=1 -o q.bin   # new request row; add its title/description lines with `text add` too
python rf4mod.py param remove fry.bin 53 -o fry.bin                    # delete a row (later rows shift down by one)
python rf4mod.py param info rf3ItemList.bin                            # the 2nd line says whether an added row is ever read (here: capped at 1108 ids)

# Event Manager structure: new trigger entries, condition terms and actions (see docs/19)
python rf4mod.py em add --clone EV_BOSS_SP_DEAD --cond-a "Season == 3 AND Hour > 20" --alt-action "REG_MAIN_SCENARIO += 2" -o em.bin   # prints the new id
python rf4mod.py em add-cond EV_CMN_DAYTIME "FLG_RAIN == 0" --slot 0 -o em.bin        # AND a term onto OR-slot 0 (omit --slot for a new OR-slot)
python rf4mod.py em add-action EV_BOSS_SP_DEAD "FLG_DATE_FES_NOW = (REG_MAIN_SCENARIO == 0)" --stream alt -o em.bin
python rf4mod.py em remove EV_SUBEV_COM_14_A --blank -o em.bin                        # empty an entry but keep every id stable

# Skill XP curves (rf3ParamSkillExp*.bin; `skill family` says which file a skill uses)
python rf4mod.py skill set rf3ParamSkillExp.bin 5 120 -o curve.bin     # level 5 -> 6 now costs 120 XP
python rf4mod.py skill set rf3ParamSkillExpMix.bin --scale 50 -o mix.bin   # cooking/forging/chemistry/crafting level twice as fast

# NPC gift preferences (rf3PresentNpc01..27 + rf3PresentCategory): who loves / likes / hates what.
# Loved/liked entries carry the friendship points they pay (+15 / +9 stock), a generic dislike is a
# fixed -5, the one 0xFFF6 "signature" dislike -10 with its own dialogue, anything unlisted +5.
python rf4mod.py gift show Raven                                          # the 3 tiers with FP per entry
python rf4mod.py gift set Raven Skull loved --fp 20 -o rf3PresentNpc25.bin        # move an item: loved | liked | disliked | neutral
python rf4mod.py gift signature Raven "Ghost Hood" -o rf3PresentNpc25.bin         # make it THE -10 hated item (old one demoted to -5)
python rf4mod.py gift set Raven range:2 liked -o rf3PresentNpc25.bin              # a whole item-id range (all vegetables); cat:N = a shared category
python rf4mod.py gift remove Raven "Star Pendant" -o rf3PresentNpc25.bin          # -> neutral
python rf4mod.py gift monster-set Goblin auto Onigiri 15 -o rf3MonsterPresent.bin # taming-food slot (per species; auto = reuse/first free)

# NPC daily schedules (rf3Schedule itineraries + rf3ScheduleID spots), one per (NPC, state):
# states 0..5 weekday, 6..11 the same day in rain, 12/13 festival, 14/15 married / date day.
python rf4mod.py schedule show --npc Vishnal --state weekday0     # 06:00 Butler's Room -> ... -> 24:00 Butler's Room
python rf4mod.py schedule set Vishnal weekday0 3 --time 07:30 --spot 26 -o rf3Schedule.bin   # re-time / re-target a stop
python rf4mod.py schedule add Vishnal rain0 --time 09:45 --spot 5 -o rf3Schedule.bin        # insert a stop (kept in time order)
python rf4mod.py schedule remove Vishnal weekday0 18 -o rf3Schedule.bin
python rf4mod.py schedule spots 26                                # the rf3ScheduleID records a spot kind rolls between (weights)
python rf4mod.py schedule decode -o sched.json                    # ...edit the JSON... then:
python rf4mod.py schedule encode sched.json -o rf3Schedule.bin    # index sections recomputed (stock JSON re-encodes byte-exact)

# NPC town-navigation graph (rf3route TRCS + rf3RouteResult next-hop matrix)
python rf4mod.py route info                                       # rooms -> nodes (tile coords, jitter) -> edges (dest, cost)
python rf4mod.py route path room:65 room:24                       # walk the matrix like the game: Butler's Room -> Airship Way
python rf4mod.py route decode -o route.json                       # ...edit nodes/edges...
python rf4mod.py route encode route.json -o rf3route.bin --result rf3RouteResult.bin   # rebuild both (matrix regenerated)

# Forge materials / dish ingredients / craft flags (rf3ItemStrengthening, archive 14811):
# what every item adds when forged into gear, what it adds to a dish, and the status word
# whose bit 0x4000 marks NON-FOOD items (a sword in a dish makes it a Failed Dish).
python rf4mod.py str show "Broken Ice Wall" 935 1108   # ATK+105 MAT+95; Glitta Augite reach +50%; a tier row
python rf4mod.py str list --field reach_scale          # every item that changes weapon reach
python rf4mod.py str list --group attack_proc          # on-hit poison/seal/... chances by material
python rf4mod.py str flags                             # status-word histogram + the non-food marker by category
python rf4mod.py str specials                          # id-keyed forge behaviour (elements, ability bits, x2/x8)
python rf4mod.py str fields                            # the 74-dword record reference with its readers
python rf4mod.py str dump -o strengthening.csv         # everything, one row per item (or --json)
python rf4mod.py str set 887 atk=500 -o new.bin        # edit a row byte-safely

# See / edit which monsters a dungeon area spawns (Gen*.bin encounter tables)
python rf4mod.py gen formap MAP_DUNG_A04       # which Gen file a map uses → GenA04.bin
python rf4mod.py gen area GenA                 # roster across dungeon area A
python rf4mod.py gen info GenA01.bin           # gates + spawns of one file
python rf4mod.py gen set GenA01.bin 0 1 --spawn 0=50 -o out.bin   # spawn Orc Archer

# Monster / character templates (rf3NpcParam.bin, archive 14812): stats, drops, elements, AI
python rf4mod.py monster show Orc              # full sheet: stats, drops(names), elements%, AI file
python rf4mod.py monster list --range 48-80    # roster (id, name, HP, ATK, kind)
python rf4mod.py monster free                  # cut ids usable for a data-only NEW monster
python rf4mod.py monster set 49 --set hp=2000 atk=150 elem_fire=4096 -o out.bin  # buff High Orc
# author a brand-new monster in a cut slot (no EXE patch): clone art/behaviour, then retune
python rf4mod.py monster clone --src 48 --dst 179 -o new.bin      # seed slot 179 from Orc
python rf4mod.py monster set 179 --set hp=1500 def=200 drop0_id=95 drop0_pm=300 --file new.bin -o new.bin
# …or do the WHOLE data-only new-monster mod in one shot (clone + name + encounter + package):
python rf4mod.py monster new --name "Test Golem" --from Orc \
    --set hp=1800 atk=140 def=250 elem_fire=-2048 drop0_id=95 drop0_pm=250 \
    --encounter GenA01.bin --out-dir mymod/     # writes rf3NpcParam.bin + rf3TxtNpc_* + GenA01.bin
```

Run `python rf4mod.py <group> -h` for full per-command help.

## Using the library directly

```python
import sys; sys.path.insert(0, "tools/modding")
from rf4s_modkit import textdb, mbundle

arc = textdb.TextArchive.load("rf3mc.eng")
arc.set_text(0, "Going to bed?")          # entry 0
arc.save("rf3mc.eng")

man = mbundle.Manifest("Bundle/Manifest.plist")
print(man.find_file("rf3.mc"))            # -> ('bundlePatch1.mbundle', {'size':..,'offset':..})
```

## Notes & limits

- **Block-compressed encoders** (`rf4s_modkit/bcenc.py`, pure Python, numpy-accelerated
  when numpy is installed): `rf4mod texture encode` / `map ground-import` / `res
  texture-encode` re-encode BC7 (mode 6, plus mode 5 for alpha edges and for flat blocks,
  which round-trip exactly), BC3 and BC1 (1-bit alpha only when a block needs it) at the
  source's own size, so the result can go back with `rf4mod bundle patch`. Quality on a
  512² ground tile: BC7 ≈ 46 dB PSNR (mean error < 1/255), BC3/BC1 ≈ 37 dB; a 512² tile
  takes ≈ 2.5 s (BC7) / 1 s (BC3) / 0.7 s (BC1) with numpy, ≈ 30 s / 6 s / 5 s without.
  `--fmt RGBA8` keeps the old lossless path (4 B/px: a 512² tile grows from 264 KB to 1 MB
  and needs a loose override or bundle repack; the container's DESC size, `_RLT` offset and
  per-frame pointers are patched — docs/09 §3). The PNG must have the template frame's
  dimensions (the sprite UV/quad user data is per-sprite and is left untouched). No shipped
  texture has mipmaps and the loader uploads level 0 only, so replacements are single-level.
  BC2 / ASTC (not shipped) have no encoder and fall back to RGBA8.
- **Textures inside `.model`** are replaced strictly in place (`texture.bntx_replace`):
  the PNG must match the texture's size and the format must keep the payload size (its
  own format, or BC3 ↔ BC7). The embedded BNTX is loaded by the same code as `.texture`
  (`GfxCTR_Model_BuildFromResource` hands it to `SpriteResourceRegistry_AcquireSlotForBfres`,
  RF4S.exe+0x1B5595), which reads only each BRTI's format / width / height / mip-0 pointer,
  so nothing else in the container needs touching — docs/09 §4.
- **Mesh editing**: `.model` geometry is read (export to OBJ, preview renders, the map
  editor's scenery layer) but not written back. It is not stock BFRES -- the blocks are
  renamed and shifted -- so generic BFRES tools do not open it (docs/09 §4).
- **Save files** (`.sav`) are handled by the existing
  [`tools/rf4s_save_editor.py`](../rf4s_save_editor.py); the bundled `AS_*`/`JM_*`
  `.sav` presets are raw save images, not runtime saves.
