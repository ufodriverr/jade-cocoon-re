// Decompile every function whose entry lies in [start, end) to outDir.
// args: outDir hexStart hexEnd
import java.io.File;
import java.io.PrintWriter;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;

public class DecompRange extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outDir = args[0];
        long start = Long.parseLong(args[1].substring(2), 16);
        long end = Long.parseLong(args[2].substring(2), 16);
        new File(outDir).mkdirs();

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        int n = 0;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            long a = f.getEntryPoint().getOffset();
            if (a < start || a >= end) continue;
            DecompileResults res = decomp.decompileFunction(f, 90, monitor);
            if (res.decompileCompleted()) {
                try (PrintWriter pw = new PrintWriter(
                        new File(outDir, f.getEntryPoint() + "_" + f.getName() + ".c"))) {
                    pw.print(res.getDecompiledFunction().getC());
                }
                n++;
            } else {
                println("FAILED " + f.getName());
            }
        }
        println("decompiled " + n + " functions");
        decomp.dispose();
    }
}
