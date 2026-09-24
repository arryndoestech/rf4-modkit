# rf3.mc in Ghidra — cutscene bytecode as a first-class listing

Load Rune Factory 4 Special's cutscene container into Ghidra with labels, friendly
per-statement disassembly (dialogue inlined from `rf3mc.eng`), and **real memory
references** for every CALL / JMP / branch / choice — so Ghidra's own XREF pane,
"References To" (Ctrl+Shift+F), and label navigation answer "who calls this scene"
natively, exactly like machine code.

No SLEIGH processor is involved: the toolkit's Python decoder (the same one behind
`script_explorer.py`) pre-renders a *listing plan*, and a small Jython script applies
it to the raw import. That keeps a single source of truth for the bytecode format.

## Setup (once)

1. **Install the RF4MC processor** (a generated SLEIGH language — the script VM's
   bytecode disassembles into real instructions, not just comments):

   ```bash
   python ghidra/gen_sleigh_module.py --install "C:/Users/arryn/ghidra_12.1.2_PUBLIC"
   ```

   Restart Ghidra afterwards so it picks up the new language. Regenerate + reinstall
   whenever opcode names change in rf4s_modkit (the mnemonics come from opcode_meta).

2. **Import rf3.mc** into your Ghidra project:
   - `File > Import File...` → `Bundle/bundlePatch1/rf3.mc`
   - Format: **Raw Binary**, Language: **RF4MC:LE:32:default**, base address **0x0**
   - Decline auto-analysis.

   (Without the processor installed, `DATA:LE:64:default` still works — the apply
   script then falls back to comments + manual references only.)

   With the Ghidra MCP bridge running the import can also be done from Claude:
   `import_file(file_path=".../rf3.mc", language="RF4MC:LE:32:default", auto_analyze=False)`.

2. **Add this folder as a script directory**: Window > Script Manager > "Manage Script
   Directories" (the list icon) → add `tools/modding/ghidra`.

## Per-session workflow

1. Generate a plan for the banks you're reading (CPython, from `tools/modding`):

   ```bash
   python ghidra/gen_ghidra_plan.py --banks 210,211
   ```

   Ranges work (`--banks 200-260`), `--all` does the whole container (~3.4M
   statements — expect a large JSON and a long apply). `--locale` picks the dialogue
   language inlined into DIALOG comments (default `eng`).

2. In Ghidra, with the imported rf3.mc open: Script Manager → run
   **ApplyRF4Cutscenes.java** (category RF4) → pick the generated
   `rf4_cutscene_plan.json`. Re-running with more banks is additive.

   (`ApplyRF4Cutscenes.py` is the same script for PyGhidra users — stock Ghidra 12
   runs `.py` only when launched via `support\pyghidraRun.bat`, so the `.java`
   twin is the one that works out of the box.)

## What you get

- `BANK_0210_PRIMARY` labels at bank starts; `scene_b0210_t27_02d4` at scene entries
  (`t27` = type-table action type, `disc` = discovered); `loc_b0210_0140` at branch
  targets.
- Plate comment on each scene entry (type, statement count, decode status).
- EOL comment on every statement — the toolkit's friendly rendering, e.g.
  `PostQuestGoalNumber(20, 3000)`, `DIALOG #63402 "Okay! I wrote down..."`,
  `CALL -> scene_b0210_disc_17ce`, `FRAME 2`.
- REAL instructions under RF4MC: `FRAME 0x2`, `CALL scene_...`, `BR_Z ...`,
  `SetVar2 0x7bda,0x7bdc`, `DIALOG 0xf7e7` — with native flow, so the XREF pane,
  call graphs and "References To" work exactly as for machine code. Action-op
  operands are expression-pool offsets (the raw encoding); the resolved friendly
  values + dialogue text ride in the EOL comment on the same line. Big argument
  blocks and switch/choice tables are typed as word data so disassembly never
  walks into them (their targets get manual references).
- On a DATA import instead: typed manual references only (CALL/JMP/branch).

## Notes

- Bytecode targets are bank-local u16 pcs; the plan converts them to absolute file
  offsets (`bank.file_off + pc`), which is why the raw import must sit at base 0x0.
- Scenes reached only by engine dispatch (type tables, em.bin, quest system) have no
  in-file callers — same truth the script explorer's Xrefs dialog reports.
- The plan reflects rf3.mc as shipped; if you edit and reinstall a modified rf3.mc,
  regenerate against the edited file (offsets can shift on container rebuild).
