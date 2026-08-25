// Disassemble a range, create functions at every addiu sp,sp,-X prologue, then
// decompile every function whose entry lies in the range.
// args: outDir hexStart hexEnd
import java.io.File;
import java.io.PrintWriter;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class MakeAndDecomp extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outDir = args[0];
        long start = Long.parseLong(args[1].substring(2), 16);
        long end = Long.parseLong(args[2].substring(2), 16);
        new File(outDir).mkdirs();

        int made = 0;
        for (long a = start; a + 4 <= end; a += 4) {
            Address addr = toAddr(a);
            int w = getInt(addr);
            if ((w >>> 16) == 0x27BD && (w & 0x8000) != 0) {
                if (getFunctionAt(addr) == null) {
                    disassemble(addr);
                    if (createFunction(addr, null) != null) made++;
                }
            }
        }
        println("created " + made + " functions in " + args[1] + ".." + args[2]);
        analyzeChanges(currentProgram);

        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        int n = 0;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            long a = f.getEntryPoint().getOffset();
            if (a < start || a >= end) continue;
            DecompileResults r = d.decompileFunction(f, 90, monitor);
            if (r.decompileCompleted()) {
                try (PrintWriter pw = new PrintWriter(
                        new File(outDir, f.getEntryPoint() + "_" + f.getName() + ".c"))) {
                    pw.print(r.getDecompiledFunction().getC());
                }
                n++;
            } else println("FAILED " + f.getName());
        }
        println("decompiled " + n);
        d.dispose();
    }
}
