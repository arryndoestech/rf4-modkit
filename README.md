# RF4S Modding Toolkit

Edit **Rune Factory 4 Special** (PC / Steam): items, crops, monsters, maps, cutscenes,
dialogue, textures, models and more. No game data is included; the toolkit works on your
own copy of the game.

## Get started

1. **Unzip the toolkit** anywhere.
2. **Double-click `start.bat`.** The first time it sets up Python and its libraries for you
   (it offers to install Python if it's missing), which takes a minute. Keep the console
   window it opens: closing it closes the toolkit.
3. **Pick the game.** On the first start, choose **Make a copy for me…** (recommended, about
   5 GB) or **Choose the game folder…** (the folder with `RF4S.exe` in it; on Steam:
   right-click the game → *Manage* → *Browse local files*).
   Modding a copy keeps your Steam install untouched; you then play from the copy's `RF4S.exe`.

## Making a change

1. Find a file in the list on the left (the **Search** box takes `*` wildcards, e.g. `rf3*.bin`),
   or use the **Cutscenes** button for scenes and dialogue.
2. Edit it in the tab that opens. Hovering over a column heading or button explains it.
3. **Save** (Ctrl+S) writes your change where the game loads it. **Undo** (Ctrl+Z) steps back.
4. **Restart the game** to see the change.

Turn on **Options… → Backups** before your first save if you want the original files kept.

## Sharing a mod

Each file you save replaces the game's file of the same name. To share a mod, collect the
files you changed (**Extract…** saves a copy of the open file anywhere) and give them to
others to put in their own `Bundle\00_mods\` folder. File names must keep their exact
upper / lower case, or the game ignores them.

## Help

- **Help** (top right) lists every shortcut; **Options…** next to it holds the settings.
- [MANUAL.md](MANUAL.md) is the full reference: every editor, the command-line tool
  (`py rf4mod.py --help`) and every file format.
- **Something broke?** The console window shows a block between two lines of `=`.
  Copy that whole block into your bug report.
