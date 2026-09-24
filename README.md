# RF4S Modding Toolkit

A complete, self-contained toolkit for modding **Rune Factory 4 Special** (PC /
Steam, the XSEED Muteki-engine port). It can read **and write** every asset format
that ships in the game's `.mbundle` archives.

## Quick start (Windows, fresh Python)

You need **Python 3.10 or newer** from <https://python.org> and your own copy of
RF4S (Steam). No game data is included here; the tools read the game's own files.

1. **Put this folder inside the game folder** as `tools\modding`. In Steam:
   right-click *Rune Factory 4 Special* → *Manage* → *Browse local files*. That opens
   the folder holding `RF4S.exe` and `Bundle\`. Create `tools\` there and unzip into
   it, so you end up with:

   ```
   Rune Factory 4 Special\
   ├── Bundle\            ← the game's (Manifest.plist, bundleMain.mbundle, …)
   ├── RF4S.exe
   └── tools\
       └── modding\       ← this folder (rf4mod.py, rf4mod_gui.py, README.md, …)
   ```

   The tools look for the game at `..\..\Bundle` from this folder, so nothing has
   to be copied or extracted.
2. **Open a terminal in the game folder** (in Explorer: click the address bar,
   type `cmd`, press Enter) and install the three libraries once:

   ```bat
   py -m pip install -r tools\modding\requirements.txt
   ```

   (`py` is the launcher the python.org installer always adds; `python` works too
   if you ticked *Add Python to PATH*.)
3. **Start the GUI:**

   ```bat
   py tools\modding\rf4mod_gui.py
   ```

   It opens the game's bundles on its own. Pick a map for the **map editor**, or
   use the **Cutscenes** button for the **cutscene editor**. The command-line tool
   is `py tools\modding\rf4mod.py --help`.
4. *(Optional)* check the install: `py tools\modding\rf4mod.py selftest`. It
   should end with `N/N checks passed`. Checks that need extracted files are
   *skipped*, not failed.

Edits are saved as separate files and never overwrite the game's bundles unless you
choose to; see [Three ways to install a mod](#three-ways-to-install-a-mod). You can
also keep the toolkit elsewhere: put it at `<anywhere>\tools\modding\` with the
game's `Bundle\` (or a link to it) at `<anywhere>\Bundle\`, or use the GUI's
*Open Manifest…* to point at the game.

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
    ├── matanim.py       # .bfmat material animations  parse + evaluate (texsrt UV scroll of the ANIM_DUNG_* light / water layers)
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

The toolkit needs to find your RF4S install's `Bundle/` directory (the one
containing `Manifest.plist` and the `bundle*.mbundle` archives).
It looks at `../../Bundle` from this folder and accepts three layouts:

- **The game's own `Bundle/`** (`Manifest.plist` + `bundle*.mbundle`) — what a
  Steam install has. The GUI, map editor and cutscene editor read the archives
  directly; nothing needs extracting. Easiest: unzip the toolkit into the game
  folder as `tools/modding/` (see Quick start), or link the game's `Bundle/` next
  to `tools/` (`mklink /J Bundle "<game folder>\Bundle"`).
- **`Bundle/<bundle>/`** — bundles extracted into folders (`bundleMain/`, …) with
  `rf4mod bundle extract-all`. The selftest's per-file checks use this layout.
- **`Bundle/extracted/`** — extracted contents in one flat directory.

For the GUI's "Open Manifest…" + map editor "Open .rf4m…" buttons, you can also
point at any directory containing those files at runtime — no fixed layout
required.

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
`.mbundle`, a folder of extracted files, or one file. Selecting an asset shows a
**type-aware viewer**:

| Selected | Viewer |
|---|---|
| `.texture` | decoded image with ½×/1×/2×/4× zoom; **Export View → PNG**; **Replace from PNG…** (same size, own format) |
| `.model` | **Textures** tab: every embedded BNTX card with preview / Export / Export all; **Replace texture…** swaps the selected card in place from a PNG · Structure tab |
| `rf3mc.*` / TEXT | searchable string table; **Export → JSON** |
| `.minterface` / `.plist` / `Manifest` | expandable bplist tree; **Export → JSON** |
| `.rf4m` | **embedded Map editor** tab (map + its search spots and encounter table, one undo history; see *Map Editor*) · Events · Chunks · read-only Hex |
| `.bin` (AIBN) | opcode disassembly; **Export → .txt** |
| `Gen*.bin` | monster encounter table editor (gates/spawns, names, weights) |
| `rf3NpcParam.bin` | **monster/character editor** — resolved roster (name + kind) + full sheet (drops w/ item names, element affinities %, status resists, AI file) + per-field edit (stats/drops/8 elements/8 resists) + loose-override Save |
| `SI_*.bin` | **search-item spot editor** — daily ground-pickup spots, two panes: **Spots** (move x/y with live tile preview, assign a pool per spot) and **Pools** (first-class: add/delete pools, edit item id/weight per entry with names + live ~% odds, shared-pool "used by" display). Guards: u8 weight-wrap warnings, in-use pool delete block, unassigned-pool not-saved warnings. See `docs/16`. |
| `rf3*.bin` (NLCL) | param-table grid editor (named fields where decoded); **Add row (copy of selected) / Delete row** with the per-table "does the engine read an added row" verdict shown above the editor |
| `em.bin` / `emdeb.bin` | identified + **Open Event Manager…** (the Cutscene editor's Event Manager window: value edits, add / remove entries, conditions and actions) |
| `.strings` | key/value table |
| `as_atk_*.bin` | attack timeline: rendered per-frame view + **Edit** tab (canonical listing, *Assemble & apply*) |
| `rf3PresentNpc*.bin` / `rf3MonsterPresent.bin` | gift preferences / taming foods with **set / signature / remove** controls and Save |
| `rf3Schedule.bin` | per-(NPC, state) itineraries with **apply / add / remove stop** controls and Save |
| `rf3route.bin` / `rf3RouteResult.bin` | navigation graph tree (rooms → nodes → edges), **path query**, JSON export/import, next-hop matrix rebuild |
| `.model` / `.bfskl` / `.psbData` | NN container structure |
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
copy (so `Extract…` saves them). The same panel runs as a standalone window with a map list
(`map_explorer.py`, or the GUI toolbar's **Map Explorer** button).

It edits a map **together with its two sidecar files** -- the search-item spots
(`SI_*.bin`) and the area's encounter table (`Gen*.bin`) -- with **one undo history**
across all three.

**Layout.** A toolbar (Save menu, Undo / Redo, tools, zoom, Validate) above the map canvas
and a sidebar with six tabs:

| Tab | What it does |
|---|---|
| **Inspect** | options for the active tool + a form for whatever is selected: an **entity** (type picker with search, position, scale / rotation, and only the fields that type actually reads, each labelled with its meaning, flag names, ore config and the other entities wired to the same flag; *show all 16 raw fields* for everything else), a **warp** (zone, destination with search, arrival, facing, disable flag, *Open destination*), a **search spot** (position + drop pool with item search and live odds; warns when the weights wrap the game's one-byte sum), a **gate position / monster spawn point**, or -- with nothing selected -- the tile under the pointer |
| **Objects** | everything on the map, grouped (entities, map parameters, warps, search spots, encounter points, script NPCs) and filterable; picking a row selects it and scrolls it into view |
| **Map** | season tag (MSEA), MGRP as checkboxes + area-group dropdown (raw hex too), the three MLIG tints with colour pickers (and which type-12 records override them), display layers (MTXN count), grid size + **Resize grid…**, **Raw chunks…** (hex editor for any chunk), and a summary |
| **Encounters** | the `Gen*.bin`: gates (kind, weight, min / max alive, spawn delay; add a copy, remove, *make private* to unshare blocks), the selected gate's roster (add / replace / remove monsters), and adding gate positions / monster spawn points on the map |
| **View** | layer toggles (ATTR fill, cell edges, grid lines, each entity category, object sprites, name labels, warps, warp destinations, search spots, encounter points, script NPCs), ground texture display + ATTR opacity, the **scenery** layer (the map's over-model cards, drawn where the game puts them), ground-art export / import |
| **Problems** | validation of all three files; selecting an issue selects its object |

**Tools** (toolbar or key while the map has focus):

| Tool | Key | Use |
|---|---|---|
| Select | V | click selects, drag moves (whole tiles, keeping the sub-tile offset; hold Shift for free placement); a selected warp shows 8 handles to resize it; double-click / Ctrl+click a warp opens its destination |
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
the selection · arrows nudge it by a tile (Shift: one sub-unit) · Esc clears it · `+` / `-`
/ `0` zoom / fit · Ctrl+wheel zooms at the pointer · middle-drag pans · Ctrl+hover a tile
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

**Script NPCs:** actors the map's *event script* places (`EventSpawnNpc` in the map's
`rf3.mc` bank -- NPCs and interactibles such as char 269 "Search") are not in the `.rf4m`;
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
  Delete deletes. **Hold Ctrl over a line** for the full explanation (prototype, every argument
  decoded, speaker, Event Manager entry).
- **Inspector** (right) — a form for the selected statement, applied as you go (Enter or
  leaving the field): a **dialogue line**'s text (Ctrl+Enter), its line id, *Find a line…*,
  *As new line* (a fresh id in every locale) and *Show other locales*; a **speaker** picker with
  the portrait side; each **action argument** in listing syntax (`actor(Forte)`,
  `map(MAP_CITY_00)`, `(FLG_X + 1)`, `@0xNNNN` for an existing expression) with a named-value
  picker where the argument has one; the **numbers in a condition or STORE** (branch targets and
  every other offset are untouched); each **choice option**'s text, line id and destination.
  *Add after* inserts a spoken line (speaker + text) or any statements in listing syntax,
  *Delete* removes the statement, *Callers…* lists every CALL / jump / branch / choice that lands
  on it, and *What it does* repeats the explanation.

The **Source** tab shows the scene as a re-assemblable listing — labels,
`BR_Z (REG_WIFE_ID == 11) -> L1`, `STORE (FLG_X = 1)`, `PROMPT_CHOICE CANCEL->L2, #123->L3`,
actions by name with expression arguments; *Check* reports the failing line inline and *Apply to
scene* re-assembles it (the scene's entry jumps to the new body, so nothing else moves). The
**Triggers** tab lists the bank's type table (every registration with its decoded keys) and mints
**new scenes**: pick when it plays (the trigger catalogue supplies a recipe per type: which bank,
which keys, the ordering caveat), its keys and a body; a note warns when a registration would
**shadow** the bank's existing scene of that type. *Change keys…* and *Remove* edit existing
registrations. The **Overview** tab summarises the scene: speakers, every dialogue line,
the Event Manager entries it gates on or runs, the flags and variables it writes, and its
control flow.

**Event Manager…** opens the em.bin window: entries decoded to `FLG_`/`REG_` names, a **Filter**
that matches the decoded text (`IS_WBED` → `EV_PROPOSE_DISABLE`; `REG_DATE_COUNT` → all 11
marriage gates), the scenes that use the selected entry, in-place value and operator edits (with a
one-line explanation of each operator, e.g. `MUL_S → t = t * v`), and whole conditions / actions
added from text (`Hour >= 6 AND (12 > Hour OR FLG_RAINBOW == 1)`, `alt: REG_WIFE_ID = 3`,
`CALL EV_FOO`) or removed. Selecting `em.bin` in the asset explorer opens the same window.

**Undo / Redo** (↶ ↷, Ctrl+Z / Ctrl+Y) cover every edit — script, dialogue in every locale and
em.bin — byte-exact. A step stores only what changed; an edit that changes nothing records
nothing. *Unsaved* is a byte comparison against what was loaded or saved, so undoing back to it
makes the file clean again, and closing or opening another `rf3.mc` asks first. **Save** writes the
changed files (all at once with Ctrl+S, or one at a time) or installs them into the game as loose
files. *New lines in all locales* gives a new dialogue line the same id in every `rf3mc.<locale>`
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
| Models / skeletons / materials | `.model` `.bfskl` `.bfmat` `.bfsha` | `rf4mod res` | ✅ **`.model` meshes read**: `res model-info` / `model-export` (OBJ + MTL + PNG) / `model-render` (UVs wrap, vertex colour, additive BlendType); ✅ **`.bfmat` material animations played**: `res model-gif` and Play in the GUI's Model tab; ✅ **textures embedded in a `.model`** (the BNTX of the 164 map over-models, character / monster / weapon / effect cards): `res texture-list` / `texture-decode` / `texture-encode` replace one texture **in place** in its own block format — file size and every container field unchanged |
| Emote / portraits | `.psbData` `.emtbytes` | `rf4mod res` | 🔍 inspect (M2 PSB) |
| Audio | `.ogg` `.wav` `.aif` | `rf4mod ident` | ➡️ swap (standard formats) |
| Video | `.webm` | `rf4mod ident` | ➡️ swap (re-encode w/ ffmpeg) |
| Images / fonts / shaders | `.png` `.ttf` `.ttc` `.glsl` `.hlsl` | `rf4mod ident` | ➡️ edit directly |

✅ = the toolkit fully reads and rewrites it · 🔍 = identify + structural inspect ·
➡️ = standard format, edit/replace with off-the-shelf tools

## Three ways to install a mod

The engine resolves a requested file by walking its mounted filesystem list and
taking the **first** match, and it mounts loose-directory filesystems **ahead of**
the `.mbundle` archives (verified in `BundleManager_LoadManifest` +
`MFFileManager::fileExistsAtPath`). So:

1. **Loose file (recommended — no repack).** Drop your modified file next to the
   game with the same bundle-relative name; it shadows the packed copy.
   ```bash
   python rf4mod.py install "C:/Games/RF4S" rf3mc.eng my_translation.eng
   ```
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

> **Always back up `Manifest.plist` and any bundle you patch.** Prefer loose files
> while iterating — they leave the originals untouched.

## Quick examples

```bash
# Identify anything
python rf4mod.py ident path/to/file

# Translate: dump the English catalog to JSON, edit, rebuild
python rf4mod.py text decode rf3mc.eng -o eng.json
#   ...edit eng.json...
python rf4mod.py text encode eng.json -o rf3mc.eng
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
