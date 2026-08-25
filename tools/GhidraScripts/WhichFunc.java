// Report the function containing each given address, and decompile it.
// args: outDir addr1 addr2 ...
import java.io.File;
import java.io.PrintWriter;
import java.util.LinkedHashSet;
import java.util.Set;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class WhichFunc extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outDir = args[0];
        new File(outDir).mkdirs();
        Set<Function> funcs = new LinkedHashSet<>();
        for (int i = 1; i < args.length; i++) {
            Address a = toAddr(Long.parseLong(args[i].substring(2), 16));
            Function f = getFunctionContaining(a);
            println(args[i] + " -> " + (f == null ? "NONE" : f.getName() + " @ " + f.getEntryPoint()));
            if (f != null) funcs.add(f);
        }
        DecompInterface d = new DecompInterface();
        d.openProgram(currentProgram);
        for (Function f : funcs) {
            DecompileResults r = d.decompileFunction(f, 90, monitor);
            if (r.decompileCompleted()) {
                try (PrintWriter pw = new PrintWriter(
                        new File(outDir, f.getEntryPoint() + "_" + f.getName() + ".c"))) {
                    pw.print(r.getDecompiledFunction().getC());
                }
                println("  wrote " + f.getEntryPoint() + "_" + f.getName() + ".c");
            }
        }
        d.dispose();
    }
}
