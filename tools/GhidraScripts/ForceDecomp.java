// Create functions at given addresses if missing (disassembling first), then
// decompile each to outDir.
// args: outDir addr1 addr2 ...
import java.io.File;
import java.io.PrintWriter;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class ForceDecomp extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outDir = args[0];
        new File(outDir).mkdirs();

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        for (int i = 1; i < args.length; i++) {
            Address a = toAddr(Long.parseLong(args[i].substring(2), 16));
            Function f = getFunctionAt(a);
            if (f == null) {
                disassemble(a);
                f = createFunction(a, null);
            }
            if (f == null) { println("FAILED to create at " + a); continue; }
            DecompileResults res = decomp.decompileFunction(f, 90, monitor);
            if (res.decompileCompleted()) {
                String fname = a + "_" + f.getName() + ".c";
                try (PrintWriter pw = new PrintWriter(new File(outDir, fname))) {
                    pw.print(res.getDecompiledFunction().getC());
                }
                println("ok " + fname);
            } else {
                println("DECOMP FAILED " + a);
            }
        }
        decomp.dispose();
    }
}
