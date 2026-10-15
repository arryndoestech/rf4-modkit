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

1. **Unzip the toolkit anywhere.** It never looks for the game by itself: the first
   start asks for the game folder, or makes a copy for you (step 3).

2. **Double-click `start.bat`** in this folder. The first time, it finds 64-bit Python 3.10+
   (and offers to install it with winget if there is none), creates a private
   environment in `.venv` here and installs the three libraries into it; that takes
   a minute. After that it just starts the GUI. Keep its console window open while
   you work: closing it closes the GUI, and any error shows up there.

   **By hand instead:** open a terminal in the toolkit folder (in Explorer: click the
   address bar, type `cmd`, press Enter), install the libraries once and start the GUI:

   ```bat
   py -m pip install -r requirements.txt
   py rf4mod_gui.py
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

   The choice is saved; *Options…* → General → **Game folder** shows it, and *Change…* changes it.

   Then it opens the game's bundles. Pick a map for the **map editor**, or use the
   **Cutscenes** button for the **cutscene editor**. The command-line tool is
   `rf4mod.py --help` (in this folder); `rf4mod.py game` shows or sets the game copy.
4. *(Optional)* check the install: `py rf4mod.py selftest --quick` in the toolkit folder
   (about a minute; drop `--quick` for the full run, several minutes). It should end
   with `N/N checks passed`. Checks that need extracted files are *skipped*, not failed.

Edits are written as loose files under `Bundle\`; the packed `.mbundle` archives are never
changed unless you choose to; see [Three ways to install a mod](#three-ways-to-install-a-mod).

```
rf4s-modkit/
├── start.bat            # double-click: sets up Python and starts the GUI
├── rf4mod_gui.py        # the graphical asset explorer
├── rf4mod.py            # the command-line tool
├── map_explorer.py      # the map editor on its own
├── script_explorer.py   # the cutscene editor on its own
├── optest.py            # in-game tests of cutscene instructions (see below)
├── CUTSCENE_OPCODES.md  # every cutscene instruction, its arguments and values
├── OPCODE_TABLE.md      # the same names as one table (from refdata/opcode_table.json)
├── opcodes_list.csv     # flat list of all 702 instructions + the control opcodes
├── gen_*.py             # regenerate the reference files above and the refdata/ tables
├── selftest.py          # checks the toolkit against your game
├── refdata/             # names and tables the tools ship with
└── rf4s_modkit/         # the Python library every tool uses
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

### By hand

`py -m venv .venv`, `.venv\Scripts\activate`, `pip install -r requirements.txt`, then
`python rf4mod_gui.py` (what `start.bat` does for you).

### Bundle layout

The toolkit needs the `Bundle/` directory of your game **copy** (the one containing
`Manifest.plist` and the `bundle*.mbundle` archives). Every tool uses the one you chose
(`rf4s_modkit/gamepaths.py`): the folder saved in the toolkit's settings (`settings.json` in
the toolkit folder), set by the GUI's first-start window / *Options…* → General → **Game folder** or by
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
it. *File…* on any other file opens it in a new tab and keeps the game's files listed, so it
reads textures and text from the game like the game's own files (a map opened this way saves
back to its own file with Ctrl+S, not into the game folder). **Back to the game** lists the game's files again. `python rf4mod_gui.py <path>` opens any
of these from the command line.

### Verifying the install

```bash
python rf4mod.py selftest
```

The selftest exercises every reader/writer round-trip against your installed
bundles and reports per-check pass/fail. Tests that need data you haven't extracted
are *skipped*, not failed. A green run looks like:

```
…
  [PASS] mapground tile 0 at screen top-left  (tile-0 pixel matches stitched (4,4))
  [PASS] MAPJ f5 = dest_map (Selphia exits)   (f5 ids=[4, 28, 32, …])
…
N/N checks passed
```

If you see fewer-than-expected passes:

- **Pillow missing**: every `texture` / `mapground` / image check skips with
  `Pillow not installed`. Install with `pip install Pillow>=9.0`.
- **texture2ddecoder missing**: BC7 decode skips with `texture2ddecoder not
  installed`. Install with `pip install texture2ddecoder>=1.0`.
- **Bundles not extracted**: most map/texture/text checks skip with `no … extracted`.
  Unpack the game: `rf4mod.py unpack` (or the setup window's *Unpack*).
- **Real failure (`[FAIL] …`)**: file an issue with the failing check's name and
  the file (if any) it was operating on.

### Troubleshooting

**Reporting a bug.** When something fails because of the toolkit itself (not a wrong value
or a file that is open elsewhere, which the GUI explains), the GUI only says so, and the
console window `start.bat` opened gets one block between two lines of `=`: what was being
done, the toolkit version (the commit the zip was built from), the Python and Windows
versions and the full error. Copy that whole block into the bug report.

**Reload in game says the toolkit runs on 32-bit Python.** A 32-bit Python cannot reach
the 64-bit game. Install 64-bit Python 3.10+ (python.org, *Windows installer (64-bit)*) and
run `start.bat` again: it rebuilds `.venv` with it.

**Windows: `python` not found.** Install Python 3.10+ from <https://python.org>;
during install, tick *Add Python to PATH*. Or use the `py` launcher (`py -3.12`).

**Performance: map editor is slow on huge maps at high zoom.** The background image is
`(w*cp, h*cp)` pixels and is rebuilt when the grid or zoom changes (selections, drags and
paint strokes do not rebuild it). Zoom out, or turn the ground texture off in the View tab.

## GUI: the asset explorer

```bash
python rf4mod_gui.py          # auto-loads Bundle/Manifest.plist
python rf4mod_gui.py <path>   # open a manifest / bundle / folder / file
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
kept in `settings.json` and shared with the standalone map editor's map list (`map_explorer.py`),
which groups its maps the same way.

**Editing .bin files.** Every game `.bin` can be changed from the explorer: the data tables in the table editor, **AI scripts** (`AI_*.bin`) by editing their listing and pressing *Assemble* (the same assembler as `rf4mod ai asm`; every shipped script rebuilds byte-exact), the **skill XP curves** (`rf3ParamSkillExp*`: set one level or scale every level to a percentage), **rf3ItemStrengthening** (set any field of the selected item), **rf3PresentCategory** (add / remove an item of a gift category), em.bin through *Open Event Manager…*, and rf3RouteResult by *Recompute from rf3route.bin* (it is derived from the route graph). *Save as…* writes the file.

**Editing text.** Every text file opens in a text editor: the TEXT archives, i.e. all
`rf3Txt*` / `rf4Txt*` files and the cutscene dialogue `rf3mc.<locale>`, plus the
`Localization-*.strings` files. The TEXT archives hold item, character, map, skill, quest,
shop, menu, calendar and staff-roll names and descriptions. Click a line, change it below the
list, and press *Apply* (Ctrl+Enter). The line is checked the way the game reads it (the same
`＠` checks as the Cutscene Editor), and one the game could crash on is refused. Other
checker problems are shown in orange, and changed lines in blue. *Show* narrows the list to
changed lines or lines with problems. *＋ New line* appends a line whose number is its id.
TEXT lines are addressed by number, so they can't be removed. `.strings` files also take
*＋ New key…* and *Delete key*. *Revert line* goes back to the text as the file was opened.
*Save* writes the file where the game loads it (`Bundle\00_mods` when the game only has it
packed), or back to the file you opened from disk.
*Save as…* writes anywhere. The game keeps the dialogue text (`rf3mc.<locale>`) in memory:
the Cutscene Editor's *🐞 Debug → ⟳ Reload in game* swaps it in, otherwise restart. Other text needs a game
restart, but the editors' character, item, map and skill names follow the saved file at once.

**Bank listing** (*Options…* → Advanced, off by default): the Cutscene Editor gets a *Bank listing* tab with the whole open bank as one read-only listing (the `script listing --bank N` text): every scene, also those no trigger starts, with the code they share. *Find* marks and steps through matches (Enter / Shift+Enter), a double click opens that scene at that line, *Save as…* writes it out.

**Backups** (*Options…* → Advanced, **off by default**). When on, every save of a game file (map,
script, dialogue, text, table ...) keeps the file as it was as a *previous version*, in
`ModdingBackup\Previous\<same folder>\<name>.<date_time>` (how many per file: your choice, the
oldest are deleted), and the first save keeps the original in `ModdingBackup\<same path>`; the
folder can be moved. *Restore a previous version…* lists every backed-up file with its versions
and puts the picked one back (the file as it is then becomes a previous version, so a restore can
be undone). The Cutscene Editor's Save menu has the same restore for `rf3.mc`, the dialogue and
`em.bin`, and reloads afterwards. The map editor's *Make over-model empty…* keeps the original
even with backups off, because its *Restore…* needs it. The backup folder only holds copies: delete
it, or anything in it, whenever you like to free space; it is made again at the next save, and
*Restore* then offers only what was saved since.

**Display.** *Options…* → Appearance / General: the *text size* (100-200 %: every font and the list rows
scale at once, in every open window) and how many *rows the big lists show*
before "search to narrow" (5000 by default). The Cutscene Editor reopens with its last toolbar
(locale and the View menu: Story / Code, addresses, opcodes, file offsets).

**Dark mode.** *Options…* → Appearance: *Light*, *Dark* or *Follow Windows* (your Windows app
setting). It applies at once to every toolkit window, the map editor and the Cutscene Editor
included, and is kept in `settings.json`. Colours the toolkit uses for meaning (red warnings,
blue notes, grey hints, list highlights) keep their hue and are made readable on the dark
background; the Windows title bars turn dark too.

**Help.** The *Help* button at the right end of the explorer toolbar lists every keyboard
shortcut and mouse gesture, one tab per area (Explorer, Map editor, Cutscene Editor,
Event Manager & text).

**Dropdowns.** In every dropdown of the toolkit, Up / Down step to the previous / next value and apply it at once (Alt+Down opens the list).

**Colours, raise / lower and button icons in text.** Game text can hold characters nobody can type
or see in a text box. The editors (the text editor, the Cutscene Editor's dialogue box and its
new-line dialog) show and take them as backslash escapes, and the file gets the real characters.
Every shipped line reads back exactly, and no shipped line contains a backslash:

| Escape | In game (tested 2026-09-29) |
|---|---|
| `\red` `\blue` `\normal` | red / blue text, normal colour again (what `／` and `＋` do) |
| `\rgb(255,128,1)` | any colour, red / green / blue 1-255 |
| `\up` `\down` | raise / lower what follows by a quarter of the font size |
| `\shift(4)` | lower what follows by 4 pixels (negative raises); the shifts add up |
| `\base` | back to the normal baseline |
| `\btn(a)` | a button icon: a b x y l1 r1 l2 r2 stick right down up left start select dpad; it follows the player's controller or keyboard |
| `\u(E0A8)` | any character by its hexadecimal code |
| `\\` | a backslash |

An unknown escape is refused with the reason. The *Insert ▾* menu next to each text box puts an
escape or a `＠` code at the cursor.

**Tabs.** Clicking a file shows it in the current tab; **double-clicking opens it in a new
tab**; Up / Down in the list show the next file in the tab you are browsing. A file that is
already open just shows its tab, and a tab with unsaved changes is never replaced: a click
from it opens a new tab instead. Each tab keeps its own copy of its file, view and map editor,
so edits in one tab are never lost by opening another: a tab with unsaved changes is marked
**•**, and closing it (its **×**, a
middle click, Ctrl+W, or the tab's right-click menu) or the toolkit asks first. With many
tabs open, **◀ ▶** or the mouse wheel scroll the tab row and **▼** lists every tab;
Ctrl+Tab / Ctrl+Shift+Tab switch tabs. Each map tab keeps its own map editor, so more than
ten open maps ask first (tick *Don't warn me again this session* to stop that); objects
still copy and paste between maps with Ctrl+C / Ctrl+V. Opening another folder or file
keeps the open tabs.

Selecting an asset shows a **type-aware viewer**:

| Selected | Viewer |
|---|---|
| `.texture` | decoded image with ½×/1×/2×/4× zoom; **Export View → PNG**; **Replace from PNG…** (own format; a PNG of another size asks first, showing old → new and what it does in game) |
| `.model` | **Textures** tab: every embedded BNTX card with preview / Export / Export all; **Replace texture…** swaps the selected card from a PNG (in place at the same size; another size asks first, then rebuilds the `.model`) · Structure tab |
| `rf3mc.*` / TEXT | searchable string table; **Export → JSON** |
| `.minterface` / `.plist` / `Manifest` | expandable bplist tree; **Export → JSON**. `Manifest.plist`: every bundle's files with their size and offset, a **Filter** on the file name, and **Copy** (selected rows, or all shown: bundle / file / size / offset, tab-separated) |
| `.rf4m` | **embedded Map editor** tab (map + its search spots and encounter table, one undo history; see *Map Editor*; its sidebar gains an **Events** tab: the map's cutscene scenes, opened in the Cutscene editor) · Chunks · read-only Hex |
| `.bin` (AIBN) | opcode disassembly; **Export → .txt** |
| `Gen*.bin` | monster spawns: a **picture of the table's map** with its gates (◆) and monster points (●) — drag them, or `+ gate` / `+ spawn` then click the picture — beside the map editor's **Gates** pane (gates, weight, delay, min/max, rosters with pick weights). **Open in map editor** switches to the full editor on that map; **Save table…** writes the file |
| `rf3NpcParam.bin` | **monster/character editor** — resolved roster (name + kind) + full sheet (drops w/ item names, element affinities %, status resists, AI file) + per-field edit (stats/drops/8 elements/8 resists) + loose-override Save |
| `SI_*.bin` | **search-item spot editor** — daily ground-pickup spots, two panes: **Spots** (move x/y with live tile preview, assign a pool per spot) and **Pools** (first-class: add/delete pools, edit item id/weight per entry with names + live ~% odds, shared-pool "used by" display). Guards: u8 weight-wrap warnings, in-use pool delete block, unassigned-pool not-saved warnings. |
| `rf3*.bin` (NLCL) | param-table grid editor (named fields where decoded); **Add row (copy of selected) / Delete row** with the per-table "does the engine read an added row" verdict shown above the editor |
| `em.bin` / `emdeb.bin` | identified + **Open Event Manager…** (the Cutscene editor's Event Manager window: value edits, add / remove entries, conditions and actions) |
| `.strings` | key/value table |
| `as_atk_*.bin` | attack timeline: rendered per-frame view + **Edit** tab (canonical listing, *Assemble & apply*) |
| `rf3PresentNpc*.bin` / `rf3MonsterPresent.bin` | gift preferences / taming foods with **set / signature / remove** controls and Save |
| `rf3Schedule.bin` | per-(NPC, state) itineraries with **apply / add / remove stop** controls and Save |
| `rf3route.bin` / `rf3RouteResult.bin` | navigation graph tree (rooms → nodes → edges), **path query**, JSON export/import, next-hop matrix rebuild |
| `.psbData` / `.emtbytes` | E-mote portrait atlas (zoomable, Export PNG) + PSB summary |
| `.model` / `.bfskl` | NN container structure |
| `.ogg` `.wav` `.aif` `.webm` `.ttf` `.ttc` (sounds, videos, fonts) | **Open in default app** (a copy goes to the temp folder and opens in Windows' player / font viewer) + hex preview |
| anything else | identification + hex preview |

`Extract…` saves the selected asset's raw bytes to disk. Image/JSON viewers degrade to
a hex view if `Pillow`/`texture2ddecoder` aren't installed.

## Map Editor

```bash
python map_explorer.py                 # browse all 872 maps
python map_explorer.py MAP_DUNG_A04     # open one map (name or .rf4m path)
python rf4mod.py mapview MAP_DUNG_A04   # same, via the CLI
```

The editor (`map_editor.MapEditorPanel`) is **embedded in the main GUI**: selecting any
`.rf4m` opens it straight in the map editor (the whole tab), and map edits flow into the GUI's working
copy (so `Extract…` saves them). Outside the GUI, the same panel runs as a standalone
program with a map list (`map_explorer.py` / `rf4mod mapview`).

It edits a map **together with its two sidecar files** -- the search-item spots
(`SI_*.bin`) and the area's encounter table (`Gen*.bin`) -- with **one undo history**
across all three.

**Saving.** *Save* (Ctrl+S) writes the map's changed files -- the `.rf4m`, its search spots
(`SI_*.bin`) and its encounters (`Gen*.bin`) -- straight over the ones the game loads from your
game folder, without asking (into `Bundle\00_mods` for a file the game only has packed).
Turn on Backups (*Options…* → Advanced) to keep the originals. *Save … as…*
writes a copy elsewhere. To see a change, leave the map in the game and enter it again (a file
new to `Bundle\00_mods` needs a game restart: the game only looks for new files when it
starts). The farm, the fields, Selphia's
streets and the farmhouse come in four seasons (`MAP_CITY_00`, `…_SUMMER`, `…_AUTUMN`,
`…_WINTER`) and the game loads the one for the current season, so an edit to one only shows
in that season; the first time you save one, the editor says so (once, ever). *Copy changes
to the other seasons…* (Save menu) carries the edit over: it works out what you changed --
against the original in `ModdingBackup`, or the map as you opened it -- and replays it on the
other three: added objects / warps everywhere, changed or removed ones only where that season
has the same one, ATTR cells where the grid matches. Map settings (season, tints, layers) are
season-specific and never copied; anything that can't be matched is listed before you confirm.

**Layout.** A toolbar (Save menu, Undo / Redo, tools, zoom, Validate) above the map canvas
and a sidebar with six tabs (it opens on View):

| Tab | Description |
|---|---|
| **View** | layer toggles (kept in `settings.json`, like the ground display, scenery and ATTR opacity, so every map and the next start open the same way: ATTR fill, cell edges, grid lines, each entity category, name labels, warps, warp destinations, search spots, monster gates, script spawns, script areas), **draw sprites** (on by default: each object's art drawn where and as large as the game draws it, in the game's depth order, right on the ground under the ATTR fill and the warps -- bridges, doors, walls, houses; a selected one gets a frame around its sprite and shines through the ATTR fill; **sprite borders** outlines every one in red above the ATTR fill, invisible walls included), **Show objects as in** (take the game flags from a slot save, any `rf4_sNN.sav`, or the running game: flag-gated objects such as the Dragon Lake bridge appear or turn into a dashed outline exactly as that save would show them), ground texture display + ATTR opacity + **darken** (the ground drops by 0-80 %, 25 % by default, so the objects on it stand out), the **scenery** layer (the map's over-model cards, drawn where the game puts them), ground-art export / import |
| **Inspect** | options for the active tool + a form for whatever is selected: an **entity** (type picker with search, position, scale / rotation, and only the fields that type actually reads, each labelled with its meaning, flag names, ore config and the other entities wired to the same flag; *show all 16 raw fields* for everything else), a **warp** (zone, destination with search, arrival, facing, disable flag, *Open destination*), a **search spot** (position + drop pool with item search and live odds; warns when the weights wrap the game's one-byte sum), a **gate position / monster spawn point**, or -- with nothing selected -- the tile under the pointer |
| **Objects** | everything on the map, grouped (entities, map parameters, warps, search spots, monster gates, script spawns, script areas) and filterable; picking a row selects it and scrolls it into view |
| **Properties** | season tag (MSEA), MGRP as **Season** (follows the calendar / always …), **Weather** (rain and snow) and **Area** (the area group, by in-game name) plus the raw value (read only), with what the game makes of it (music, crate loot pool, the Gen table the gate spawner really loads, minimap group) and conflict warnings, also in Problems: a room whose gates would never appear, a group that points the spawner at a non-Gen archive, a fixed season contradicting a seasonal copy, extra season / group bits (each control changes only its own bits), the three MLIG tints with colour pickers (and which type-12 records override them), display layers (MTXN count), grid size + **Resize grid…** (width / height in tiles, shift right / down, what the new tiles are -- wall, empty, walkable or any value; objects, warps, search spots and gate positions move with the content in one undo step; Preview lists what else must be fixed: ground tiles, the minimap origin, seasonal copies, warps into the map), and a summary |
| **Minimap** (docked under the tabs, shown whatever tab is open; **Hide minimap** / **Show minimap**, remembered; its details are in Properties) | the HUD minimap picture the game draws for this map's id (rf3MapMiniPos), with the map's footprint (red), the area its first visit uncovers (dashed magenta) and the part the editor shows now (dashed blue); click or drag on it to move the editor's view there; the other rooms on the picture are outlined, named on hover, and a click opens one in the editor. The Properties tab's Minimap section lists the sheet / resource, fog of war, where an interior's NPC icons go, the other maps on the same picture and the save-state picture swaps; blank and Sharance Maze pictures are noted |
| **Gates** | the `Gen*.bin` (monster gates): gates (kind, weight, min / max alive, spawn delay; add a copy, remove, *make private* to unshare blocks), the selected gate's roster (add / replace / remove monsters), and adding gate positions / monster spawn points on the map. **Moving gates:** with 2+ gate positions, a visible Void .. Affection Gate of kinds 375-382 glides from position to position in list order (about 4 s a leg; drawn as a dashed loop with arrows), and a gate with *teleports* ticked blinks out and reappears at a random one of its positions every 6 s or so (dotted lines) -- the Rune Prana gates. The two don't combine: a teleporting gate must be a kind that doesn't glide (the game uses 383-390, the same gates with 1000 HP); so *teleports* is greyed out for the gliding kinds (picking one unticks it), and a file that has both anyway is flagged as broken. The gate list shows how each gate moves (*· glides*, *· teleports*); the *kind* list gives each kind's HP from `rf3NpcParam.bin` and marks the gliding kinds |
| **Events** | (in the asset explorer) the map's cutscene scenes from its event bank in `rf3.mc`, biggest first with a dialogue preview; double-click or *Open in Cutscene Editor*; *New scene on this map…* |
| **Problems** | validation of all three files -- including monster spawn points with no walkable ground (ATTR bit 0x01 / 0x20) within their radius, where the game then spawns every monster on the point itself, and gate positions outside the map, the MGRP conflicts, **treasure chests** sharing a collected flag (here or on another map: a duplicated / pasted chest; opening one removes the other) or having none (back every visit), a loot row past the table, a **room whose area group differs from the rest of its dungeon** (music, crates, minimap), and a **file name the game never loads**; INFO lines are notes (e.g. a chest that gives nothing); selecting an issue selects its object |

**Tools** (toolbar or key while the map has focus):

| Tool | Key | Use |
|---|---|---|
| Select | V | click selects (markers and borders first, then warps, then the inside of a sprite; clicking the selection again -- press and release without moving -- steps to the next thing under the pointer), drag moves the selection (whole tiles, keeping the sub-tile offset; hold Shift for free placement); a selected warp shows 8 handles to resize it; double-click / Ctrl+click a warp opens its destination (also where other objects overlap it). **Several at once:** Shift+click adds / removes one, a drag on empty map selects everything in the box (Shift+drag adds), Ctrl+A selects all; dragging any of them moves them all, arrow keys nudge and Delete deletes the whole selection (one undo step each), a plain click on one of them selects only it. A selected or hovered **treasure chest** shows its loot (its f8 row of the chest table, shipped in refdata/rf4s_exe_tables.json); a **crate** shows its whole area pool with each item's odds (one item rolled per visit; same chances grouped) |
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

**Keys:** Ctrl+Z / Ctrl+Y undo / redo · Ctrl+S saves (see below) · Delete removes
the selection · Ctrl+C / Ctrl+X / Ctrl+V copy, cut and paste an entity, warp, search spot, gate position or
monster spawn point -- also onto another map (it pastes at the pointer; a gate point goes
into the gate chosen in the Gates tab, or the map's only gate; right-click empty map for *Paste here*;
a map already holding the game's 40 entity / 10 warp chunks refuses) · arrows nudge it by a tile (Shift: one sub-unit) · Esc clears it · `+` / `-`
/ `0` zoom / fit (a map opens at 6 px per tile; zoom runs 2–24 px, and name labels grow with it) · the wheel zooms at the pointer and Ctrl+wheel scrolls (untick *Mouse wheel zooms the map* in *Options…* → Map editor to swap them; remembered in `settings.json`) · Shift+wheel scrolls sideways · middle-drag pans · Alt+hover a tile (Ctrl+hover works too)
shows its ATTR decode.

**Editing rules.** Every field commits on Enter or when it loses focus, as one undo step,
and only when the value changed; a failed edit restores the files and says why. A press
becomes a drag only after 4 px, so clicking never nudges anything, and a whole drag or
paint stroke is one step. **Unsaved changes are guarded** -- switching map (list, file,
warp) or closing asks first, for the map *and* its sidecars -- and **Save** warns before
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

**Script spawns:** characters, monsters and objects a map's scenes place at run time (not in
the `.rf4m`). The *script spawns* layer marks them; a click opens the script line in the
Cutscene editor. Spawns whose position the script computes can't be shown.

**Script areas:** every trigger box on the map: the map's own PlayerRegionTrigger scenes (they run
while the player stands inside and their em.bin condition holds) and the sub-event and story
scenes of other banks that start when the player enters a box on this map. The *script areas*
layer (on by default, like *script spawns*) draws them dashed, labelled with the condition or the
sub-event step / story chapter; hover says when one fires, a click opens its scene in its bank.

Code: `map_editor/` -- `document` (files, undo, dirty tracking), `render` (ground loader,
background, overlay primitives shared by canvas and PNG), `view` (canvas), `tools`,
`inspector`, `tabs`, `dialogs`, `panel`, `app`, `attrs` (what every ATTR bit means),
`data` (map ids, sidecar files, names). Every map edit goes through the verified `rf4m`
writers and re-serialises a byte-valid map.

### Resizing a map

The game sizes a map's ground art from its ATTR grid alone: one 512-px tile per 21⅓ map
tiles, numbered row by row. A grid that outgrows its tile set does not draw blanks, it shows
the next files' art. `map validate` (and Validate in the editor) reports:

| finding | meaning |
|---|---|
| **missing tiles** (ERROR) | the grid needs tiles the set lacks; the message names the files to make |
| **past 96 tile slots** (ERROR) | more ground tiles than the game has room for; the map breaks (no shipped map needs over 30) |
| **extra tiles** (WARN) | the set has more tiles than the grid uses; harmless |
| **interior gap** (WARN) | a narrow edge tile became an inner tile after a resize: an untextured strip |

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
python gen_map_names_json.py      # (re)build out/map_names.json
python gen_exe_tables_json.py     # re-read the refdata/rf4s_exe_*.json tables from RF4S.exe (only for a new game build)
python gen_minimap_sheets.py      # render out/minimap_sheets/ (needs Bundle/ + Pillow)
python gen_minimap_sheets.py --labels names --clean --zoom 4   # vanilla pictures + room names -> out/minimap_sheets_named/
```

`out/minimap_sheets/` holds one annotated PNG per minimap picture (reveal rects, origins,
scale extents and the NPC-icon spots of interiors drawn over the sheet) plus an index README.
`out/minimap_sheets_named/` is the clean set: the plain picture at 2048 px with each room labelled
by its name from `out/map_names.json` (duplicates numbered `_01..N`), and `labels.csv` /
`labels.json` mapping each label back to its map id.

`out/map_names.json` is the map-id registry: for every map id `0..873` the in-game name
(`rf3TxtMapName`, row = id + 1), the `MAP_*` file, a note where the HUD's location band
deviates from that name, and the **minimap** block. The library behind it:

| Module | What it answers |
|---|---|
| `map_names.py` | `map_name(id)` in-game name · `map_file(id)` / `map_id_for_file("MAP_ROOM_06A.rf4m")` · `is_building_entrance(id)` (signboard warps) · `label_note(id)` (farm/barn names, maze floor, the Cliff ↔ Volkanon Bridge swap) |
| `minimap.py` | `texture(id)` the `mini_map_*.texture` the HUD draws · `variants(id)` the save-state swaps · `record(id)` origin / fog-of-war rect / Q12 scale / NPC-icon parent sheet · `pos_to_sheet(id, x, y)` · `bake()` re-vendors the table from your bundle |

How the game picks the picture: `rf3MapMiniPos.bin` gives each map id a sheet (`mini_map_*`)
and its place on it. A few sheets are swapped by save state (town, Water Ruins, farm, your room,
barns, two fields), and Sharance Maze floors are put together at run time. Field list:
`rf4s_modkit/minimap.py`.

## Cutscene Editor

```bash
python rf4mod_gui.py     # open the Manifest, then toolbar "Cutscenes"
python script_explorer.py [folder with rf3.mc]   # or on its own
python gen_opcode_reference.py   # (re)build CUTSCENE_OPCODES.md
```

Edits the game's cutscene/event scripts: **`rf3.mc`** (the compiled Script-VM bytecode —
tens of thousands of scenes), the per-locale **`rf3mc.<locale>`** dialogue text, and the Event
Manager conditions in **`em.bin`**, with **one undo history** across all three. Reached from the
main GUI's **Cutscenes** toolbar button, the **Open in Cutscene Editor →** button on a map's
scene list, or by clicking a *script spawn* in the map editor (it opens on that exact line). It
reads the files by basename from the loaded source, so it works best with a **Manifest** open.

Every instruction has a name, argument labels and a description;
[`CUTSCENE_OPCODES.md`](CUTSCENE_OPCODES.md) lists them all.

**The window** has three panes:

- **Browser** (left) — banks grouped and named: *Characters* (`Nancy  (bank 19)`), *Villager
  behaviour*, *Maps* (`Map 274 · MAP_DUNG_A04 (Yokmir Forest)`), sub-events, quests. Each bank
  lists its triggered scenes first, each with the subroutines it CALLs under it (*calls sub
  @015e · …*, a click opens the scene there), then any **unreached** code: pieces nothing in the
  bank registers or calls, with the number of statements only they reach (a stub that just jumps
  into code a registered scene runs is not listed; the engine could start one at a fixed
  address, or it is left-over code). The search box finds scenes by **dialogue**
  (case-insensitive phrase), **speaker**, **opcode** (name or number), **Event Manager entry**, or
  jumps to a **bank #**. Empty map banks are hidden unless *empty banks* is ticked. The
  **Trigger type** dropdown shows only the scenes of one **trigger type** (*MapEnterScene*, a talk tier,
  *WarpArrivalScene* ...; the number is how many triggers ship) and only the banks that have one. The
  toolbar's **◀ Banks** button hides the list to give the scene the full width; **Inspector ▶**
  at its right end does the same for the Inspector.
- **Script** (middle) — the open scene. The **Story** view reads like a script:
  `Nancy: “…”` in the speaker's colour, actions by name (`▸ GivePlayerItem(reg1, 1, reg3)`),
  flow as `if not (FLG_X) → go to L2`, choice options on their own rows, and a header saying
  **when it plays** (its triggers and the em.bin gates). **Code** shows the disassembly. Both are in the
  toolbar's **View** menu, with four columns *Addresses* (each statement's address in its bank),
  *Opcodes* (the raw opcode), *File offsets* (its byte offset in `rf3.mc`, hex; with unsaved
  edits, where it will be in the saved file) and *Operands* (its operands as stored, in hex right
  after the opcode -- `0x063  030e000000 1a860200 1aab0100` -- one group and one colour per
  operand: an action's arguments are their expression bytes, e.g. `030e000000` = actor 14,
  `1a860200` = 646; a control op's targets, line ids, counts and conditions; the column is padded
  so the statements line up; Alt-hover names each operand); *Xref counts* puts after each label how
  many statements of the bank lead to it (`L2:  · 3 xrefs`; X lists them). Arrow keys / PgUp / PgDn move the selection, Enter jumps to the editor,
  Delete deletes. **Several lines:** Ctrl+A selects all, Shift+click / Shift+arrows a range, Ctrl+click adds or
  removes one; Delete deletes them as one undo step (a RET, a menu and a random pick are kept:
  delete those on their own). **Cut / copy / paste:** Ctrl+C copies the selected lines as code (a
  jump into the copied lines becomes a label, so they paste anywhere in the bank; the Source tab
  takes them too), Ctrl+X cuts them (copy + delete, one undo step), Ctrl+V pastes after the selected
  line -- at a selected label, or before a RET / jump / menu, since nothing runs after those. **Hold Alt over a line** for the full explanation (prototype, every argument
  decoded, speaker, Event Manager entry).
- **Inspector** (right) — a form for the selected statement, applied as you go (Enter or
  leaving the field): a **dialogue line**'s text (Ctrl+Enter), its line id, *Find a line…*,
  *As new line* (a fresh id in every locale) and *Show other locales*; a **speaker** picker with
  the portrait side; each **action argument** in listing syntax (`tag3(4)`, `tag4(24)`,
  `FLG_X + 1`, `@0xNNNN` for an existing expression; `actor(Forte)` / `map(MAP_CITY_00)` can be
  typed too) with a character / map / named-value picker where the argument has one; the **numbers in a condition or EVAL** (branch targets and
  every other offset are untouched); each **choice option**'s text, line id and destination. In the
  Add / Edit instruction window a menu's options move with ▲ / ▼ (editing a menu that stores the
  answer in reg0 warns that its separate visibility lines and SWITCH keep the old order).
  **Open map** (toolbar) shows the scene's map in the map editor, script spawns and areas on: its
  bank's map, or one its triggers or instructions name (a menu when there are several).
  *Delete* removes the statement: what jumped to it goes to the next statement (a JMP too: the
  goto goes away). A **menu** asks which option the scene goes on with, as if the player had picked
  it (a masked menu also sets reg0 to that option, as the pick would; its visibility-mask lines
  stay, for a menu you put in its place); a random pick or SWITCH_CLAMP asks which path; the code
  only the other options led to stays in the bank as unreached code, to jump to or call again. A RET can't be deleted (nothing comes after it).
  *Xrefs…* (also in the right-click menu; key X) lists every CALL / jump / branch /
  choice that lands on it, or on the scene when nothing is selected, and *Description*
  repeats the explanation.

Every structural edit — insert, delete, *Apply to scene*, a new scene, a wider argument, a
changed trigger list — **rebuilds the whole bank** (`rf4s_modkit/bankrelink.py`): the new code
sits where it belongs, and every branch target, entry pc and operand offset after it moves with
it. Nothing is appended behind the bank's data and no jumps are patched in, so repeated edits
never pile up dead code; the editor follows the open scene and the selection to their new
addresses. Same-size edits (a line id, a number, a speaker, a branch target) are still patched
in place. A bank can hold 64 KB (every address in it is 16-bit); an edit that would pass that is
refused with a message. The game copies each bank into a buffer sized from the rf3.mc header,
so the rebuild also raises those header sizes when a bank grows.

Files edited by earlier toolkit versions, which inserted code by **trampolining** (new code
appended at the bank's end, reached through a jump written over the original statement), still
load and play as before. When such a file is saved again — from the editor, or by any `rf4mod
script` command that writes rf3.mc — those banks are rebuilt in the new layout first: each
appended block moves back in place of its jump, skipped statements and unreachable leftovers
are dropped, and every scene still executes the same statements (`rf4mod script normalize
rf3.mc -o out.mc` does only that).

The **Source** tab shows the scene as a re-assemblable listing — labels,
actions as calls (`GivePlayerItem(258, reg0 + 1, 0)`, `EndDialogue()`), control statements as
keywords with the condition in parentheses (`BR_Z (REG_WIFE_ID == 11) -> L1`, `EVAL (FLG_X = 1)`,
`PROMPT_CHOICE #123 -> L3, #124 -> L4`, `JMP L1`); *Check* reports the failing line inline and *Apply to
scene* re-assembles it in place: the new body takes the old body's place and statements only
the old body used are dropped. The
**Triggers** tab lists the bank's triggers by trigger type (each with its decoded keys) and mints
**new scenes**: pick when it plays (a trigger type; the catalogue supplies a recipe per type: which bank,
which keys, the ordering caveat), its keys and a body (for a trigger with a box -- a player region,
a sub-event or story region scene -- *📍 Draw the box…* drags it on the map, the map's other boxes
dashed); a note warns when a new trigger would
**shadow** the bank's existing scene of that type. *Change keys…* and *Remove* edit existing
triggers. Keys are checked as you type: a trigger that could never run is refused (exactly
the keys of a trigger checked before it; a type-2 event key outside 1..65535 or -1 -- spawned
event actors carry a 16-bit key, and 0 marks a removed one; anything outside signed 32-bit),
and odd keys warn (type-2 keys 1..47, which ops that take an actor read as villagers -- use
48..65535; the same type-2 key in another level of the tail → primary → global lookup; an item,
gossip topic, festival, em.bin condition, map or character that does not exist). `script
add-trigger` / `set-trigger` refuse the same way (`--force` overrides). The **Overview** tab summarises the scene: its **checks**, speakers, every dialogue line,
the Event Manager entries it gates on or runs, the flags and variables it writes, and its
control flow.

**Scene checks** (`rf4s_modkit/scenelint.py`; after every edit the editor warns about the
problems that edit brought in, and the Overview tab lists all of them):
- a loop that waits for the player (their position, the stick) with no dialogue, menu or
  scripted move in it: the player can't move while a scene runs, so it never ends;
- a loop that never waits and has no way out (the game hangs);
- a menu followed by its last option's line, dialogue suppression left on, a masked menu
  whose options can all be hidden (they freeze or misbehave);
- a warp to a map id that has no map;
- a line missing in one of the languages (it shows line 0 there), or with more rows than the
  box shows (3) or rows longer than the game's own text ever uses (80 characters, 30
  full-width), per language.
Effects the shipped scenes hand on to the next scene on purpose (the black overlay, a music
lock, a frozen player) are not warned about. `rf4mod.py script lint` runs every check over the
whole `rf3.mc` (or `--bank N`). The **Graph** tab draws that control flow: the scene's basic blocks with their
statements, green / red arrows for the branch taken when a guard is true / false, orange for
switch, choice and random slots, and loops up the right-hand side. The scene body sits on top;
every subroutine it CALLs is its own titled group below it, and a CALL block's
"→ sub @xxxx" line scrolls to that group.
The mouse wheel zooms, dragging the background pans and *Fit* shows the whole scene; a block
can be dragged anywhere (kept for the session, *Reset layout* puts them back). A click selects
a statement for the Inspector, frames its block in gold and turns the arrows into and out of
it gold; a double click opens it in the Script tab.

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
  **Internal names** in the toolbar switches entries and game queries to their emdeb names
  (`EV_SUBEV_COM_49`, `SUBEV_ENABLE_ARTHUR`), the names the cutscene editor shows; the choice is
  remembered.
- **Inspector** (right): edit the selected line with pickers — what a requirement checks (a game
  value, a variable, another entry), how ("is at least", "is less than"…), and against what (named
  values for seasons, characters, maps, on/off); what an action changes and how ("set to", "add"…).
  **Add an alternative (OR)**, **Add a requirement (AND)**, **Add a way**, **Add an action
  before / after** and **Remove** work next to the selection. New lines start as placeholders
  that change nothing, so em.bin keeps working at every step.
- **Checks**: the toolbar counts problems. Errors (a condition that loops back to itself, an entry
  that doesn't exist, dividing by zero) make Save refuse; warnings flag things like the weather
  queries, which RF4S never answers (they always read 0). The text form (`Hour >= 6 AND
  Season == 1`, `REG_WIFE_ID = 3`, `CALL EV_FOO`) is on the CLI: `rf4mod em add-cond` /
  `add-action` / `set`.

Selecting `em.bin` in the asset explorer opens the same window.

**Undo / Redo** (↶ ↷, Ctrl+Z / Ctrl+Y) cover every edit — script, dialogue in every locale and
em.bin — byte-exact. A step stores only what changed; an edit that changes nothing records
nothing. *Unsaved* is a byte comparison against what was loaded or saved, so undoing back to it
makes the file clean again, and closing or opening another `rf3.mc` asks first. **Save** (Ctrl+S)
writes the changed files straight into your game folder without asking, over the copies the
game loads: an unpacked `Bundle\bundlePatch1\rf3.mc`, `Bundle\bundleMain\rf3mc.<locale>` and so
on, or an existing `Bundle\00_mods` override. A file the game only has inside a packed
`.mbundle` goes to `Bundle\00_mods` -- except rf3.mc and the em.bin files while
`bundlePatch1.mbundle` / `bundlePatch2.mbundle` are still packed: those archives beat any loose
copy, so unpack them first (`rf4mod.py unpack`). With Backups on (*Options…* → Advanced), the
original is kept in `ModdingBackup\`. A
file opened with *Open rf3.mc…* is saved back where it was opened. *Save … as…* writes a copy
anywhere, and *Install as loose files* puts copies in `Bundle\00_mods`.

**Adding instructions without typing them.** Right-click in the script (or the Insert key): *Add
instruction…*; the window inserts it after the selected one, or before it (a choice in the window,
back to "after" once inserted). The list shows the instructions verified in game (untick the box
for all ~700), with **Most used** (what the game's own scenes use most) and **Recently used** on
top (*Most used* is a fixed list: the instructions the game's own scenes use most; either group
can be switched off in Options → Cutscene Editor), each with a one-line Description; search finds
them by it ("fade", "walk"). Picking
one shows a one-line description (*More…* for the rest) and a form with one field per argument.
Each field starts at the value the game's own scenes use most (walk speed 100, a fade to black over
1 second) and lists the named values (compass directions, fade colours, turn speeds) and the other
common ones. Timers take seconds: type `1.5 s` in a Wait, fade or shake and the field writes the raw
value (each counts differently: Wait 12000 per second, the fades 6000, the shake 60), and every
field says what its value means (`= 0.5 s`, `= facing right`). Portrait faces are pictures to pick.
Walks, turns, fades and shakes offer *then wait until it's done*, which adds the matching wait.
The form scrolls; *Insert* stays at the bottom, and Esc closes the window without inserting.
Characters, maps, items, flags and named values are pickers. SetRegisters shows reg0 … reg9: fill
them in order (the form refuses an empty register before a filled one).

**Editing an instruction the same way.** *Edit instruction…* (right-click a line, or F2) opens the
same form without the list, filled in from the selected statement (any kind: actions, dialogue,
menus, conditions, jumps, switches, EVAL, FRAME); *Apply* replaces the statement in
one undoable step (whatever jumped to it reaches the new one). On a dialogue line it holds the
line's text: changed text is saved as a new line (other scenes that show the old one keep it), and
*an existing line* points the statement at another line. A statement the form can't hold exactly
(say, an EVAL that only compares) opens as its listing text instead. Esc closes it without changing
anything.
Optional and repeating arguments can be added, jump targets come from the scene's own statements,
and choice menus, switches and random jumps take rows. DIALOG writes **a new line** (speaker,
side, face, box style and text, added in every locale) or shows an existing one by id. Every x / y
position has **📍 Pick on
map…**: click the spot on the rendered map of the scene (1/8-tile units, as the script stores them).
The listing the form makes is checked live; tick *Advanced: show the listing* (remembered) to see
and hand-edit it. *Insert* puts it
after or before the selected statement and closes the window (the new statement is selected). The Inspector
edits existing statements the same way: short argument names, the value's meaning, the named and
common values, face pictures, the character / map / item pickers and *Pick x / y on the map*.
For writing by hand, the **Source** tab holds the whole scene as editable listing text.

**Variables.** Opt-in: tick Options → Cutscene Editor → *Variable editor* (off by default; off, the
list is read-only and nothing is written). Then *Variables…* (toolbar) opens the Reference on Flags &
variables, which is also the variable editor. **New variable…** names free bits of the game-flag store (bits 3017–4095 are
unused by the game's own table) as an on/off flag or a 2–16-bit number; scripts and event
conditions can use the name at once. **Rename…** renames any variable, the game's own too:
the game stores bit positions only, so no game file changes, and a game variable keeps
answering to its original name as well (**Restore name** gives it back). **Delete** removes
your own. *Show* filters the list to variables unused by scripts and events, yours, renamed
or the game's. The game's code can still use a variable by its bit position, so prefer New
variable over taking over an unused game one. The names are kept in `emdeb_extra.json` next to
`emdeb.bin` (with the Event Manager's entry names); every tool reads them.

**Reference.** *📖 Reference* lists the flags and variables (emdeb.bin's FLG_ / REG_ / EV_ names,
bit id, width, value range and Japanese label, plus the recovered zone-2 bits), the functions
verified in game (with everything the opcode table knows about each), the **text codes** a
dialogue line can hold (`＠０＠`, `＠キャラ０＠`, `＋blue＋` ..., what each shows and which instruction fills
its slot: `SetVar3(0, n)` feeds `＠０＠`), and the character, map and
item ids with the form an argument takes, and the **trigger types**: what makes a scene
run (the bank's type table, the keys each type compares, which trigger wins), one row per type with
its keys, trigger count and matcher; double-clicking a type sets the Banks list's Trigger type
filter to it. Double-click copies. A click on a column heading sorts the list by it (again: the other way
round); the Functions tab starts sorted by opcode. **Options → Advanced** adds *Show unverified
instructions in the Reference* (the Functions tab lists every instruction, ✓ = checked in game) and
*Export CSV buttons in the Reference* (each list saves the rows its filter lets through as a CSV). **Where a variable is used:** the
flags list counts each variable's reads and writes over every bank and em.bin (unsaved edits
included); selecting one lists every statement and em.bin entry that reads or writes it, and a
double-click opens it. In the script view, right-click a statement → *Uses of FLG_X…* for each
variable it names. (Ops that change a register inside their own handler, e.g. op 536 moving
REG_SUBEV_RSV into REG_SUBEV_NOW, are not counted: the script does not name the variable.)

**Names come from your game.** Character, item, map and skill names are read from the game's
own English text files (`rf3TxtNpc_split2_1.eng`, `rf3TxtItem_split2_1.eng`, `rf3TxtMapName.eng`,
`rf3TxtSkill_split2_1.eng`). The toolkit uses the copy the game loads, so one in `Bundle\00_mods`
wins over `bundleMain`. A mod that renames a character therefore shows the new name in every
picker, comment and map-editor label, and `actor(NewName)` is accepted when typing. A saved
change to one of these files is picked up within half a second, with no restart, and so is a
`00_mods` copy being added or removed; an open Cutscene Editor re-titles its bank list by itself. Without a game folder, or when one of the files is
missing, the toolkit falls back to the lists it ships with (`refdata/`), which match the
unmodded game. Flag names come from your `emdeb.bin` and sound names from your
`*_audio_data.bdat` in the same way.

**Testing instructions in game (`optest.py`).** Verification is kept per argument, not only per
instruction. In `refdata/opcode_table.json` every argument has its own `human_verified` flag
and a `tests` log (date, the call, what was seen). An argument whose value is a code can list
`value_names`, for example ModifyPlayerResource's `resource`: `100` = `gold`, `105` = `stone`.
The assembler reads the name (`ModifyPlayerResource(gold, add, 1234)`) and the pickers offer it. The
listing keeps the game's own number and names it in the statement's comment:
`ModifyPlayerResource(100, add, 1234)   ; ModifyPlayerResource(gold, add, 1234)`. Typed
constants work the same way: the listing writes the raw `tag3(0)` and the comment shows
`actor(player)`. Each name records whether it was seen working in game. True aliases and
families such as SetSpeaker share one set of arguments, so a test of one counts for all of them.
The Reference, the instruction picker and the Inspector mark verified arguments with ✓.

```bash
python optest.py status                    # verified instructions that still have unverified arguments
python optest.py status ModifyPlayerResource   # one instruction: arguments, value names, tests
python optest.py sweep "ShowActorEmote(actor(player), {v})" 1-26 --then "ShowActorEmote(actor(player), none)"
python optest.py restore MAP_F_ROOM_00     # put that map's scenes back as the game shipped them
python optest.py record 417 --call "ModifyPlayerResource(gold, add, 1234)" --observed "gold +1234" --arg 0 --value 0:100=gold
```

A *sweep* tries each value in turn, to find out what the values of an argument do. For each value,
a dialogue box first says "The result: *N* points", then the call runs with that value and the
scene holds for 2 seconds. It goes into the entry scene of a map (`--map`, the Dragon Room by
default), which runs every time you walk in. That scene starts while the warp's black screen is
still up, so the sweep waits half a second first. Otherwise a fade or anything else on screen
would be hidden.

**Reload from disk:** *🐞 Debug → ⟲ Reload rf3.mc + dialogue from disk* (F5) reads `rf3.mc`, the dialogue of every language, `em.bin` / `emdeb.bin` and the game's
character, item and map names again from disk, for when another tool (`optest.py`, `rf4mod script …`) changed the file while the
editor was open. It stays on the same scene; unsaved edits and the undo history are dropped (it
asks first). While the script debugger is attached it also picks up dialogue lines that game holds past the
end of the file (the test lines `optest.py` puts only into the running game) and shows them marked
*[running game only]*; nothing is written.

**No restart for scenes:** *🐞 Debug → ⟳ Reload in game* (Ctrl+R) saves, then puts `rf3.mc` into the game
the script debugger is attached to, whatever the new size. It works only while the debugger is
attached, so the reload and the debugger always act on the same game (attach first: *🐞 Debug →
Debugger… → Attach*). The game keeps `rf3.mc` in memory for the whole session, so the
reload swaps that copy and the three bank buffers in place while the game is paused for a moment.
While a scene is playing the reload is queued (its code must not change under it): the editor
checks the game twice a second and reloads as soon as the scene has ended; another *Reload* replaces
the queued one. Changed scenes run from the
next trigger or talk. The dialogue text is swapped in too: scripts show lines from one archive slot
that the game fills with your language's `rf3mc.<locale>` at start and keeps in memory, and a line id
past its line count shows line 0 ("Are you turning in for the night?"). So new or changed lines need
this reload (the toolkit finds which language the game holds) or a restart. `em.bin` is swapped in too: the game keeps it in memory
(one archive slot plus the Event Manager's own pointer to it), and the reload replaces both. A
file that is new to `Bundle\00_mods` still needs a restart. On the CLI: `rf4mod script reload [rf3.mc] [--force]` and
`rf4mod script live` (what the game currently holds). `rf4mod script log` watches the running game (read only) and lists every scene start and every piece of script code it saw run, flagging any the editor does not show or shows only as *unreached*. *Add new lines to every language* (*Options…* → Cutscene Editor, on by default) gives a new dialogue line the same id in every `rf3mc.<locale>`
(untranslated), so it shows in every language.

**Script debugger** (*🐞 Debug → 🐞 Debugger…* on the toolbar; docks below the tabs, *Undock* puts it in its own
window). *Attach* connects to the running game (its memory; no native debugger, the exe is not
changed). **F9** (or the right-click menu) sets a breakpoint on the selected Script-tab statement:
a script that reaches it stops just before the statement runs, the editor opens that scene at it,
and game time stands still while it waits (*Stop game time while a script is stopped*; the rest of
the world keeps running). *Continue* lets it go on, *Step* runs one statement and stops at the next
(a CALL runs whole; *Step into* stops inside it; stepping onto a RET stops after the CALL it returns
to, and a script's last RET ends it). *Pause* holds a script that is waiting on its own countdown;
idle scripts and scripts in the middle of a prompt, choice or dialogue can't be held there (set a
breakpoint on the statement after it). The details show the registers, the stack and the statement
the script stands at with the live value of every argument and condition; the *Variables* tab lists
every FLG_/REG_ the scene uses with its value in the game, and the *Text slots* tab the slots its
dialogue's ＠ codes print (＠アイテム０＠, ＠キャラ１＠, ＠金２＠ …) or its SetVar statements fill, with the
live value in words (the item, character, map, date) and whether the scene sets it -- a slot it only
shows prints what an earlier scene left there. A RET can't take a breakpoint (it is too
short), and a breakpoint on code the game doesn't run yet waits until you save and *Reload in game*.
Breakpoints move with your edits and a MapEnterScene can be stopped too (the game's copy of the
script file carries them). *Detach*, closing the debugger or closing the toolkit puts everything
back as it was; if the toolkit is killed while attached, the next attach to that game cleans up. One
debugger per game at a time, and *Reload in game* waits until no script is stopped.

Everything the editor does is also on the CLI (`rf4mod script listing / asm / check / insert /
delete / set-val / set-target / set-speaker / triggers / add-trigger / remove-trigger / set-trigger /
normalize`, `rf4mod em …`,
`rf4mod text add --pad-to N`). Every shipped bank reads and rebuilds byte for byte.

Code: `cutscene_editor/` — `document` (the files, one undo history, unsaved tracking), `render`
(story rows, listing lines, explanations, overview), `browser`, `view` (Script tab), `inspector`,
`tabs` (Source / Triggers / Overview), `cfg` + `graph` (the Graph tab's blocks, layout and
canvas), `dialogs`, `em_window`, `catalog` (trigger types, bank names, grammar help, xrefs),
`app` (the window).


**Portrait faces.** *Add instruction* → DIALOG (a new line) and a selected speaker cue both have a **Face**
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
choose it. The listing names the shared moods (`SetSpeaker(Volkanon, Right, angry, …)`) and
numbers the rest (`face 29`).

**Box style.** `SetBoxNormal`, `SetBoxShout`, `SetBoxThought`, `SetBoxTrembling` (ops 94–97) and
`SetDialogueBoxStyle` (op 93) set the **message-box style**: 0 normal, 1 shout (jagged box that
shakes, screen flash), 2 thought (cloud box that floats for about a second), 3 trembling (wavy box
that shakes sideways), 4 tail only (no box, op 93 only). The style lasts until changed or the box
closes. Their Inspector and *Add instruction* → DIALOG have a **Box style** picker that shows the game's
own box art.

The box's **tail** points at the side of the last speaker cue (`SetSpeaker(…, Left, …)` or
`SetSpeaker(…, Right, …)`), and it only shows while a portrait is up on that side for a named character.
Narration and `SetSpeakerVoice` name plates get no tail. So a thought line needs a speaker cue
on the side where that character's portrait should be. The game's own thought lines always
follow one. The Inspector says where the tail will point, or why it won't show.

**Text checks.** Every line you edit or add is checked the way the game reads it
(`rf4s_modkit/textlint.py`):

- **Refused**: a `＠‡A,B＠` gender switch without its comma, without the closing fullwidth
  `＠`, or with a side longer than 63 bytes. The game crashes on those.
- **Warned, but applied**: a `＠…＠` the game doesn't know or with a slot number out of range
  (shown as written), an odd number of `＋` (blue) or `／` (red) marks (the colour runs to the
  end of the line), text after a NUL, a stray carriage return.
- **Shown under the text box while you type**, together with a note when a token reads a text
  slot that no `SetVar` opcode in the scene sets.

Save and Install refuse to write while an edited line would crash the game.
## Animating in Blender

Models and their motions (`.bfskl`) round-trip through Blender as glTF (`.glb`):

1. **Install the add-on once** (optional, recommended): Blender > Edit > Preferences > Add-ons >
   the drop-down arrow at the top right > **Install from Disk…** > `blender/rf4s_blender.py`.
   It adds **File > Import > RF4S model / motions** (switches the scene to the game's 60 fps
   first, so every game frame is a Blender frame), keeps the **timeline fitted** to the motion
   you are editing (frame 0 .. its last frame; frame N = game frame N), and **File > Export >
   RF4S motions** (refuses at any rate but 60). Without the add-on: set Output > Frame Rate to
   60 *before* File > Import > glTF 2.0, and set the frame range yourself.
2. **Export** from the Model tab: **Export for Blender…** (the model + the motion picked in the
   motion row) or **Export all motions…** (every motion of the model, one Blender action each,
   named after its file).
3. **Animate** in Blender. Keep the bone and action names: an action's name decides which
   motion file it replaces. Export the .glb (every action; untouched ones are fine).
4. **Import** in the Model tab: **Import all motions…** lists only the actions that differ from
   the game's motions and installs the ones you tick, or
   **Import motion…** replaces the motion picked in the list. Command line: `res model-glb`,
   `res motion-import`, `res motion-import-all`.

Limits: motions are replaced, not added (the game plays them by file name); bones cannot be
added; changing a motion's length can put attack hitboxes / sounds (timed by frame) out of step.
At 24 fps Blender smooths fast moves away -- the toolkit warns when a file was exported at
another rate.

**Editing the mesh itself** (shape, UVs, weight painting) goes the same way back:

1. **Export for Blender…** and import the .glb into Blender (the add-on or File > Import >
   glTF 2.0).
2. **Edit** the meshes: move / add / delete vertices, subdivide, re-UV, repaint weights. Keep
   each object's name (Blender's `.001` suffix on a lone copy is fine) and the bone names.
3. **Export** File > Export > glTF 2.0 (.glb) -- or the add-on's RF4S export, same file.
4. **Import from Blender…** in the Model tab (command line `res model-import-glb MODEL FILE.glb
   [-o OUT]`, `--map SHAPE=MESH` to pair them by hand). Each mesh replaces the shape of its
   name with its positions, normals, UVs **and bone weights**, any vertex / triangle count.
   Meshes you did not touch keep their exact bytes: an untouched round trip through Blender
   gives back the original file byte for byte (for a few models Blender re-splits some
   triangles; those come back drawing the same).

What a shape can store is fixed by its vertex format: rigid shapes (skin 0) follow their one
bone whatever the weights say; skin-1 shapes keep each vertex's heaviest bone; skinned shapes
keep their 2 / 3 / 4 heaviest influences, renormalised. A bone the game has no skinning matrix
for passes its weight to its nearest parent that has one. The import names every such case.
To **remove** a part, delete its object in Blender and import with `--remove-missing` (or pick
"(remove)" for that shape in the dialog, `--remove SHAPE`): the shape stays in the file (shape
numbers do not shift) but draws nothing. To **add** a part, model it as a new object
(parented to the armature with weights). The import asks what to do with it: *add to* an
existing shape (command line `--add NewPart=SHAPE`: it joins that shape and its material), or
make it a **new shape** *like* an existing one (`--new NewPart=SHAPE[:MATERIAL]`: the shape's
vertex format and skin type are copied, the material is that shape's or any other existing
one, so map the UVs onto that texture). A model holds at most 32 shapes (the game's limit).
Not possible yet: new materials or textures, changing a shape's skin type, adding or
re-parenting bones.

**Moving bones** (the rest pose): move or turn bones in Blender's edit mode, export, and answer
Yes when the import asks (command line `--bones`). The model keeps its look at rest (inverse
bind matrices and rigid parts follow); motions then turn the parts about the new pivots.
Blender cannot keep a bone's rest *scale* (36 shipped bones have one), so scale is never taken
from Blender.

## What can be modded, and how

| Format | Extensions | Tool | Round-trip |
|---|---|---|---|
| Bundle archive | `.mbundle`, `Manifest.plist` | `rf4mod bundle` | ✅ full |
| UI layout / config | `.minterface`, `.plist` | `rf4mod plist` | ✅ full (bplist) |
| Game text | `rf3mc.*`, TEXT archives, `.strings` | explorer text editor, Cutscene Editor, `rf4mod text` / `rf4mod strings` | ✅ full |
| Engine UI text | `.strings` | `rf4mod strings` | ✅ full |
| Textures | `.texture` | `rf4mod texture` | ✅ decode; encode a PNG into any texture in its own format (`--fmt` forces one), at any size (map ground tiles must stay 512 px); flipbook frames; `map ground-export` / `ground-import` for a whole ground layer |
| Maps | `.rf4m` | `rf4mod map` | ✅ chunk-level; `map validate` checks the game loader's rules **and the ground atlas against the ATTR grid**; `map resize-attr` resizes the tile grid and lists every derived artefact it invalidates |
| Monster/NPC AI | `AI_*.bin` (AIBN) | `rf4mod ai` | ✅ full (token + text); `disasm --annotate` adds the verified operand meanings, `ai ops` / `ai actions` print the opcode and scripted-action references |
| Attack move timelines | `as_atk_*.bin` (690) | `rf4mod asatk` | ✅ decode (`show`/`summary`) + **assembler/editor**: `dump` → edit listing → `asm`, or point edits `set` / `insert --frame` / `delete`; byte-exact on every stock file; GUI Edit tab |
| Cutscene / event scripts | `rf3.mc` | `rf4mod script`, cutscene editor (`script_explorer.py`) | ✅ full: disassemble, a listing language that assembles back byte-exact (every shipped bank), insert / delete / rewrite with the **bank rebuilt in place**, new scene triggers (`script add-trigger` / the editor's New scene…); opcode names from `refdata/opcode_table.json` |
| Search-item spots | `SI_*.bin` (288) | GUI table editor, map editor | ✅ daily ground-pickup spots, item pools and weights (footer rebuilt) |
| Monster / character templates | `rf3NpcParam.bin` | `rf4mod monster`, GUI monster editor | ✅ stats, drops, elements, AI; `monster clone` / `new` mint templates |
| Saves | `rf4_sNN.sav` | `rf4mod save` | ✅ named GameFlags, field get / set, CRC fix-up |
| Event Manager triggers | `em.bin`, `emdeb.bin` | `rf4mod em` | ✅ conditions/actions decode; in-place edit; **structural**: add / remove entries, condition terms and actions from a readable spec (`em add / remove / add-cond / remove-cond / add-action / remove-action`; the container is rebuilt, stock re-serialises byte-exact) |
| Skill XP curves | `rf3ParamSkillExp*.bin` | `rf4mod skill` | ✅ decode + `skill set FILE LEVEL XP` / `--scale PCT` (every level) |
| Monster encounter tables | `Gen*.bin` (NLCL) | `rf4mod gen` | ✅ full: gates / weights / rosters / positions, add & remove gates and monsters (rebuilds the file + footer; all 690 stock files round-trip byte-exact) |
| Game-data param tables | `rf3*/rf4*.bin` (NLCL) | `rf4mod param` | ✅ named fields for items, crops, recipes, skills, fishing, schedules...; add / remove rows (`param info` says whether the game reads an added row); fixed-point fields as percentages (`150%`); flag fields by name (`param set rf3ParamMagic.bin 1 "flags=+Ignore DEF,-Fire"`) |
| NPC gift preferences | `rf3PresentNpc01..27.bin`, `rf3PresentCategory.bin` | `rf4mod gift` | ✅ move items between loved / liked / disliked / neutral, set the FP code and the one −10 "signature" dislike, add range / category entries; the file is rebuilt (sub-list offsets + NLCLINK tail), all 28 stock tables round-trip byte-exact |
| Monster taming foods | `rf3MonsterPresent.bin` | `rf4mod gift monster-set` / `monster-clear` | ✅ the 4 per-species (item, tame bonus) slots |
| NPC daily schedules | `rf3Schedule.bin` + `rf3ScheduleID.bin` | `rf4mod schedule` | ✅ per-(NPC, state) itineraries: set / add / remove stops, JSON decode → edit → encode (index sections recomputed; stock re-encodes byte-exact); spot kinds resolved to rooms |
| NPC navigation graph | `rf3route.bin` (TRCS), `rf3RouteResult.bin` | `rf4mod route` | ✅ rooms → nodes → edges decode / JSON / encode (byte-exact), game-accurate path walk, next-hop matrix regeneration after graph edits |
| Models / skeletons / materials | `.model` `.bfskl` `.bfmat` `.bfsha` | `rf4mod res` | ✅ read, OBJ / glTF export, preview renders; write: shapes from OBJ or Blender (with bone weights), new and hidden shapes, bone rest pose, material settings, embedded textures (any size), `.bfmat` material animations (play, edit, retime), `.bfskl` motions (play, import). Written models are statically checked, not yet tried in game. See [Animating in Blender](#animating-in-blender) |
| Emote / portraits | `.psbData` (loaded) `.emtbytes` (never loaded by the PC exe) | `rf4mod psb` | ✅ full E-mote PSB v4 reader (all 130 parse; `.emtbytes` header decrypted): `psb info` (atlas, face-frame timelines 0-5 = 通常/怒り/哀しみ/笑顔/驚き/照れ, variables), `psb dump -o DIR [--resources]` (whole tree → JSON), `psb textures -o DIR [--parts]` (RGBA8 / ASTC atlas → PNG, plus every named part crop); ✅ **repaint a portrait**: `psb replace-texture X.psbData edited.png -o out/` (same size; only the atlas bytes change, re-parsed and checked). Keep part outlines where they are — the mesh/part rectangles are absolute atlas pixels |
| Sound-id table | `common_audio_data.bdat`, `voice_en_audio_data.bdat` (`voice_jp_…` ships but is never loaded) | `rf4mod sound` | ✅ `list` / `show` / `find` (all three tables) / `set` volume · priority · flags / point an id at another file / `add` a brand-new id / `remove`; byte-exact rebuild of all 3 stock tables; PlaySound / PlaySoundOnFreeVoice listings show the file name. New sound: drop `SE_MYMOD.ogg` (or .wav/.flac/.mp3, sniffed by magic) under `Bundle\00_mods\`, `rf4mod sound add common_audio_data.bdat auto SE_MYMOD.ogg -o my.bdat`, `rf4mod install <game> common_audio_data.bdat my.bdat`, restart, `PlaySound(<id>)` |
| Audio | `.ogg` `.wav` `.flac` `.mp3` | `rf4mod ident` | ➡️ swap (standard formats; the loader sniffs OggS / RIFF / fLaC / else MP3 — AIFF is not decoded; the one shipped `UISelect.aif` is referenced nowhere in the exe) |
| Video | `.webm` | `rf4mod ident` | ➡️ swap (re-encode w/ ffmpeg) |
| Images / fonts | `.png` `.ttf` `.ttc` | `rf4mod ident` | ➡️ edit directly |
| Shaders | `.glsl` `.glsl.inc` (bundleMuteki), `.bfsha` | `rf4mod shader` | ✅ the game compiles **only the loose bundleMuteki GLSL** (`mtk_body/item/billboard` = every model, from source at each start, no shader cache): `shader list`, `shader extract mtk_body -o dir` (includes inlined as GL gets them), `shader replace mtk_body_f.glsl edited.glsl -o dir` (checks includes / `#version` / `main`) then `install`. `.bfsha` GLSL is never compiled on PC (the game never compiles it), so it is read + extracted only (`shader list/extract rf4cmv.bfsha`); `.hlsl` files are never loaded |

✅ = the toolkit fully reads and rewrites it · 🔍 = identify + structural inspect ·
➡️ = standard format, edit/replace with off-the-shelf tools

## Three ways to install a mod

At startup the game indexes **every file under `Bundle\`** (all sub-folders, by file
name) and mounts that index **ahead of** the `.mbundle` archives; the first match
wins. A missing `.mbundle` is just skipped, so the game also runs from a fully
extracted `Bundle\`. Files next to `RF4S.exe` are **not** looked at.
Exception: while `bundlePatch1.mbundle` / `bundlePatch2.mbundle` are still packed, their files
(rf3.mc and the em.bin files among them) win over any loose copy -- unpack them first
(`rf4mod.py unpack`); `rf4mod.py mods` lists such ignored files. So:

1. **Loose file (recommended — no repack, uninstall by deleting it).**
   ```bash
   python rf4mod.py install "C:/Games/RF4S" rf3mc.eng my_translation.eng
   ```
   This copies it to `Bundle\00_mods\rf3mc.eng`. **Restart the game** to load it.
   `00_mods` sorts before the `bundle…` folders, so it also wins over an extracted
   original (when a name exists twice under `Bundle\`, the path that sorts first wins).
   **File names are case-sensitive to the game**, even though Windows isn't: the override
   must have exactly the game's name (`rf3mc.eng`, not `RF3MC.ENG`; `MAP_CITY_00.rf4m`,
   not `map_city_00.rf4m`), or the game never loads it. Sorting is by raw characters too:
   digits, then upper case, then `_`, then lower case.
   `python rf4mod.py mods "C:/Games/RF4S"` lists everything that currently overrides
   the game, and flags any file in the wrong case as ignored.
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

# Re-skin ANY texture from a PNG. The default (--fmt keep) re-encodes BC7/BC3/BC1 sources
# in their own format (same PNG size -> same file size, bundle patch-able in place);
# raw sources keep their format; --fmt BC7|BC3|BC1|RGBA8|RGBA4444|ABGR1555|GL_RED_8bpp forces one.
# A PNG of another size is stored at that size; the command prints what that does in game.
python rf4mod.py texture encode OBJ_BED_00.texture edited.png -o new.texture
python rf4mod.py texture encode OBJ_BED_00.texture edited_2x.png -o new.texture     # 2x resolution
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
python rf4mod.py res model-import-glb NPC_C_BADO.model edited.glb -o out.model   # shapes + bone weights from Blender's glTF export
python rf4mod.py res model-transform NPC_C_BADO.model 0 --scale 1.2 --rotate 0,45,0 -o out.model   # move / scale / rotate a shape in place

# Textures inside a .model (map over-model scenery cards, character/monster/weapon/effect models)
python rf4mod.py res texture-list MAP_CITY_00.model                    # index, name, format, size
python rf4mod.py res texture-decode MAP_CITY_00.model 3 -o card3.png   # upright PNG
python rf4mod.py res texture-encode MAP_CITY_00.model 3 card3.png -o MAP_CITY_00.model   # same size, in place
python rf4mod.py res texture-encode MAP_CITY_00.model 3 card3_2x.png -o out.model        # any size: .model rebuilt

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
```

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

```bash
# Edit a cutscene / event script (rf3.mc): find a scene by its dialogue, read it, then
# reword a line, retune an action arg, or insert a beat — inserts rebuild the bank in place.
python rf4mod.py script find rf3.mc "about to call you" --text rf3mc.eng   # → bank + pc of matches
python rf4mod.py script dev-menus rf3.mc --text rf3mc.eng --bank 18  # the devs' ＊ test menus: event / festival / date → routine pc
python rf4mod.py script space rf3.mc [--bank N]                     # bytecode room left per bank (64 KiB each; fullest first)
python rf4mod.py script reload                                       # push the game folder's rf3.mc into the RUNNING game (no restart)
python rf4mod.py script log --seconds 300 --out log.json            # watch the RUNNING game: log the scene code it runs, flag any the editor doesn't show
python rf4mod.py script disasm rf3.mc --bank 1 --text rf3mc.eng            # read the scene (op names)
python rf4mod.py script set-text rf3mc.eng --line 8709 --text "New line!" -o rf3mc.eng   # reword a line
python rf4mod.py text add rf3mc.eng --text "A whole new beat!" -o rf3mc.eng   # author a NEW line (prints its id)
python rf4mod.py script set-speaker rf3.mc --bank 1 --pc 0x08c2 --speaker Vishnal --side right -o new.mc  # change who speaks
python rf4mod.py script set-val rf3.mc --bank 1 --pc 0x3478 --index 0 --value 258 -o new.mc  # change an arg value / EVAL value / choice option's line id
python rf4mod.py script set-target rf3.mc --bank 1 --pc 0x400e --index 1 --target 0x4036 -o new.mc  # retarget a branch/choice destination (validated)
python rf4mod.py script insert rf3.mc --bank 1 --pc 0x3478 --dialogue 66494 -o new.mc         # add a dialogue beat
python rf4mod.py script insert rf3.mc --bank 1 --pc 0x3478 --stmt "BR_Z (FLG_X) -> L1 / DIALOG #5 / L1:" -o new.mc  # a conditional beat
python rf4mod.py script delete rf3.mc --bank 1 --pc 0x3478 -o new.mc          # remove a statement (the bank is rebuilt)
python rf4mod.py script delete rf3.mc --bank 1 --pc 0x5006 --option 2 -o new.mc  # remove a menu: go on as if option 2 was picked
python rf4mod.py script listing rf3.mc --bank 1 --pc 0x3478 --text rf3mc.eng -o scene.txt   # scene as re-assemblable source…
python rf4mod.py script asm rf3.mc --bank 1 --pc 0x3478 --listing scene.txt -o new.mc         # …edit, and put it back
python rf4mod.py script triggers rf3.mc --bank 248                                             # a map bank's triggers + keys
python rf4mod.py script add-trigger rf3.mc --bank 248 --type 6 --stmt "FRAME 0 / DIALOG #8709 / END" -o new.mc  # a NEW scene
python rf4mod.py em show EV_BOSS_SP_DEAD    # decode a scene's "plays when" condition + effects
python rf4mod.py em new-var FLG_MY_QUEST_DONE          # a NEW game flag (free bit of the 4096-bit store; sidecar emdeb_extra.json)
python rf4mod.py em new-var REG_MY_COUNTER --width 4   # …or a register; usable in em conditions and cutscene listings at once
python script_explorer.py     # …or edit cutscenes visually (story view, inspector, one undo history)

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
python rf4mod.py param set rf3ParamMagic.bin 0 dmg_mult=150% -o m.bin    # a fixed-point field takes a percentage
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

# Event Manager structure: new trigger entries, condition terms and actions
python rf4mod.py em add --clone EV_BOSS_SP_DEAD --cond-a "Season == 3 AND Hour > 20" --alt-action "REG_MAIN_SCENARIO += 2" -o em.bin   # prints the new id
python rf4mod.py em add-cond EV_CMN_DAYTIME "Hour >= 18" --slot 0 -o em.bin        # AND a term onto OR-slot 0 (omit --slot for a new OR-slot)
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

# Monster / character templates (rf3NpcParam.bin): stats, drops, elements, AI
python rf4mod.py monster show Orc              # full sheet: stats, drops(names), elements%, AI file
python rf4mod.py monster list --range 48-80    # roster (id, name, HP, ATK, kind)
python rf4mod.py monster free                  # cut ids usable for a data-only NEW monster
python rf4mod.py monster set 49 --set hp=2000 flat_atk=150 elem_fire=4096 -o out.bin  # buff High Orc
# author a brand-new monster in a cut slot (no EXE patch): clone art/behaviour, then retune
python rf4mod.py monster clone --src 48 --dst 179 -o new.bin      # seed slot 179 from Orc
python rf4mod.py monster set 179 --set hp=1500 flat_def=200 drop0_id=95 drop0_pm=300 --file new.bin -o new.bin
# …or do the WHOLE data-only new-monster mod in one shot (clone + name + encounter + package):
python rf4mod.py monster new --name "Test Golem" --from Orc \
    --set hp=1800 flat_atk=140 flat_def=250 elem_fire=-2048 drop0_id=95 drop0_pm=250 \
    --encounter GenA01.bin --out-dir mymod/     # writes rf3NpcParam.bin + rf3TxtNpc_* + GenA01.bin
```

Run `python rf4mod.py <group> -h` for full per-command help.

## Using the library directly

```python
import sys; sys.path.insert(0, ".")   # run from the toolkit folder
from rf4s_modkit import textdb, mbundle

arc = textdb.TextArchive.load("rf3mc.eng")
arc.set_text(0, "Going to bed?")          # entry 0
arc.save("rf3mc.eng")

man = mbundle.Manifest("Bundle/Manifest.plist")
print(man.find_file("rf3.mc"))            # -> ('bundlePatch1.mbundle', {'size':..,'offset':..})
```

## Notes & limits

- **Texture encoding** is built in (numpy makes it ~10x faster): BC7 ≈ 46 dB, BC3/BC1 ≈ 37 dB
  on a ground tile; a 512² tile takes ≈ 2.5 s with numpy, ≈ 30 s without. A PNG of another size
  rebuilds the texture around it: a sprite with its own quad data keeps its on-screen size, one
  without grows with the texture, map ground tiles must stay 512 px. Block formats need sizes
  in multiples of 4 (else `--fmt RGBA8`). BC2 / ASTC sources are re-encoded as RGBA8.
- **Textures inside `.model`**: at the same size they are replaced in place
  (`texture.bntx_replace`, its own format or BC3 ↔ BC7); at **another size** the embedded
  BNTX is rebuilt and everything after it in the `.model` moves with it
  (`modelwrite.replace_embedded_file`; statically verified, not yet tried in game). The game
  reads only each texture's format, size and first mip level, so nothing else needs touching.
- **Mesh editing**: `.model` geometry is read (OBJ / glTF export, preview renders, the map
  editor's scenery layer) **and written back** — shape geometry from OBJ (skin weights
  copied from the nearest original vertex) or from Blender's glTF (with the painted bone
  weights), new shapes (up to 32), hidden shapes, bone rest-pose moves and material
  settings (statically verified, not yet tried in game). Not possible: new materials or
  textures, a different skin type, new or re-parented bones. The format is not stock
  BFRES -- the blocks are renamed and shifted -- so generic BFRES tools do not open it.
- **Save files** (`rf4_sNN.sav`) are handled by `rf4mod save`.
