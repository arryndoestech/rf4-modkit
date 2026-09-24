// Apply an RF4 cutscene "listing plan" (gen_ghidra_plan.py output) to an imported rf3.mc.
//
// With the RF4MC processor module installed (gen_sleigh_module.py --install <ghidra>),
// import rf3.mc with language RF4MC:LE:32:default and this script DISASSEMBLES the
// script bytecode into real instructions: named mnemonics, operand lists, and native
// CALL/JMP/branch flow (the XREF pane answers "who calls this scene" by itself).
// Big argument blocks and switch/choice tables are typed as word data so the
// disassembler never walks into them. On a plain DATA-language import the script
// falls back to comments + manual references only (the pre-processor behavior).
//
// WORKFLOW
//   1. python ghidra/gen_sleigh_module.py --install "<your Ghidra install folder>"
//      (once; restart Ghidra afterwards so it sees the new language)
//   2. Import rf3.mc as Raw Binary, language RF4MC:LE:32:default, base 0x0, no analysis.
//   3. From tools/modding:  python ghidra/gen_ghidra_plan.py --banks 210,211
//   4. Run this script from the Script Manager and pick the plan JSON.
// Re-running with a plan for other banks is additive.
// @author rf4s toolkit
// @category RF4

import java.io.File;
import java.io.FileReader;
import java.math.BigInteger;
import java.util.Map;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.ArrayDataType;
import ghidra.program.model.data.WordDataType;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.ProgramContext;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.SourceType;

public class ApplyRF4Cutscenes extends GhidraScript {

    private Address addr(long off) {
        return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(off);
    }

    private RefType refType(String kind) {
        if ("call".equals(kind)) return RefType.UNCONDITIONAL_CALL;
        if ("jump".equals(kind)) return RefType.UNCONDITIONAL_JUMP;
        return RefType.CONDITIONAL_JUMP;
    }

    private void label(long off, String name) {
        try {
            currentProgram.getSymbolTable().createLabel(addr(off), name, SourceType.USER_DEFINED);
        } catch (Exception e) {
            // duplicate / invalid name - keep going, the listing is still usable
        }
    }

    @Override
    protected void run() throws Exception {
        File f = askFile("RF4 cutscene plan JSON (gen_ghidra_plan.py output)", "Apply");
        JsonObject plan;
        try (FileReader rd = new FileReader(f)) {
            plan = JsonParser.parseReader(rd).getAsJsonObject();
        }

        boolean rf4mc = currentProgram.getLanguageID().getIdAsString().startsWith("RF4MC");
        ProgramContext pctx = currentProgram.getProgramContext();
        Register bankbaseReg = rf4mc ? pctx.getRegister("bankbase") : null;
        var refmgr = currentProgram.getReferenceManager();
        long memMax = currentProgram.getMaxAddress().getOffset();
        int totalStmts = 0, totalRefs = 0, totalInstr = 0, nBanks = 0;

        for (JsonElement be : plan.getAsJsonArray("banks")) {
            JsonObject bank = be.getAsJsonObject();
            long base = bank.get("file_off").getAsLong();
            long size = bank.get("size").getAsLong();
            int pos = bank.get("pos").getAsInt();
            if (base + size - 1 > memMax) {
                printf("bank %d lies outside the program (base 0x%x) - wrong import base? skipped\n",
                       pos, base);
                continue;
            }
            nBanks++;
            JsonArray stmts = bank.getAsJsonArray("stmts");
            monitor.setMessage("bank " + pos + " (" + stmts.size() + " statements)");

            // bank-local u16 targets resolve as bankbase+target in the RF4MC language
            if (bankbaseReg != null) {
                pctx.setValue(bankbaseReg, addr(base), addr(base + size - 1),
                              BigInteger.valueOf(base));
            }

            label(base, bank.get("label").getAsString());
            for (Map.Entry<String, JsonElement> e : bank.getAsJsonObject("labels").entrySet()) {
                label(base + Long.parseLong(e.getKey()), e.getValue().getAsString());
            }

            // pass 1: type the unmodeled tails (big arg blocks, switch/choice tables) as
            // word data FIRST, so disassembly flow can never run into them
            if (rf4mc) {
                for (JsonElement re : stmts) {
                    JsonArray row = re.getAsJsonArray();
                    long sz = row.get(1).getAsLong();
                    long ilen = row.size() > 4 ? row.get(4).getAsLong() : sz;
                    if (ilen < sz) {
                        try {
                            createData(addr(base + row.get(0).getAsLong() + ilen),
                                       new ArrayDataType(WordDataType.dataType,
                                                         (int) ((sz - ilen) / 2), 2));
                        } catch (Exception e) {
                            // already typed on a previous run
                        }
                    }
                }
            }

            // pass 2: disassemble every statement start (flow fills the gaps; existing
            // code units are skipped so re-runs are cheap)
            if (rf4mc) {
                for (JsonElement re : stmts) {
                    JsonArray row = re.getAsJsonArray();
                    Address a = addr(base + row.get(0).getAsLong());
                    if (getInstructionAt(a) == null) {
                        disassemble(a);
                        totalInstr++;
                    }
                    if (monitor.isCancelled()) { println("cancelled"); return; }
                }
            }

            String kind = bank.get("kind").getAsString();
            for (JsonElement se : bank.getAsJsonArray("scenes")) {
                JsonObject sc = se.getAsJsonObject();
                Address a = addr(base + sc.get("entry").getAsLong());
                int typ = sc.get("type").getAsInt();
                String plate = String.format(
                    "RF4 cutscene scene  --  bank %d (%s), %s, %d statements%s",
                    pos, kind, typ >= 0 ? ("type " + typ) : "discovered",
                    sc.get("stmts").getAsInt(),
                    sc.get("ok").getAsBoolean() ? "" : "  [PARTIAL DECODE]");
                String old = getPlateComment(a);
                if (old == null || !old.contains(plate)) {
                    setPlateComment(a, old == null ? plate : old + "\n" + plate);
                }
            }

            // pass 3: friendly text (resolved args + dialogue) as EOL comments, plus
            // manual references. Under RF4MC the language already provides CALL/JMP/
            // branch flow refs, so only table ops (their targets live in data tails)
            // need manual ones; on a DATA import everything is added manually.
            for (JsonElement re : stmts) {
                JsonArray row = re.getAsJsonArray();
                Address a = addr(base + row.get(0).getAsLong());
                String text = row.get(2).getAsString();
                setEOLComment(a, text);
                boolean tableOp = text.startsWith("SWITCH_") || text.startsWith("PROMPT_")
                                  || text.startsWith("JMP_IND") || text.startsWith("RAND_BR");
                if (!rf4mc || tableOp) {
                    for (JsonElement rr : row.get(3).getAsJsonArray()) {
                        JsonArray pair = rr.getAsJsonArray();
                        refmgr.addMemoryReference(a, addr(base + pair.get(0).getAsLong()),
                                                  refType(pair.get(1).getAsString()),
                                                  SourceType.USER_DEFINED, 0);
                        totalRefs++;
                    }
                }
                totalStmts++;
                if (monitor.isCancelled()) { println("cancelled"); return; }
            }
        }

        printf("applied: %d statements (%d disassembled), %d manual references, %d bank(s)%s\n",
               totalStmts, totalInstr, totalRefs, nBanks,
               rf4mc ? "" : "  [DATA import: comments+refs only - use language RF4MC:LE:32:default for real disassembly]");
        println("tip: 'G' jumps to a label (BANK_0210_PRIMARY, scene_b0210_t27_02d4, ...);");
        println("     click a scene_/loc_ label - the XREF pane lists its callers.");
    }
}
