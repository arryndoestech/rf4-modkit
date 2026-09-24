// Headless verifier: print a few code units starting at each hex file offset given
// as a script argument. Used by the toolkit's automated RF4MC language test.
// @category RF4

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.CodeUnit;

public class DumpRF4Listing extends GhidraScript {
    @Override
    protected void run() throws Exception {
        for (String s : getScriptArgs()) {
            long off = Long.parseLong(s, 16);
            Address a = currentProgram.getAddressFactory()
                        .getDefaultAddressSpace().getAddress(off);
            println("==== @0x" + Long.toHexString(off));
            for (int i = 0; i < 8 && a != null; i++) {
                CodeUnit cu = currentProgram.getListing().getCodeUnitAt(a);
                if (cu == null) { println(a + ": (no code unit)"); break; }
                String c = cu.getComment(CodeUnit.EOL_COMMENT);
                println(String.format("%s  %-40s ;%s", a, cu.toString(), c == null ? "" : c));
                a = cu.getMaxAddress().add(1);
            }
        }
    }
}
