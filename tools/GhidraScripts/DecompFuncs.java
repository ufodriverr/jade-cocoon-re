// Decompile given functions (by hex addr or name) to an output dir and
// list each one's direct callers.
// args: outDir seed1 seed2 ...
import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class DecompFuncs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outDir = args[0];
        new File(outDir).mkdirs();

        List<Function> funcs = new ArrayList<>();
        for (int i = 1; i < args.length; i++) {
            Function f = args[i].startsWith("0x")
                ? getFunctionAt(toAddr(Long.parseLong(args[i].substring(2), 16)))
                : (getGlobalFunctions(args[i]).isEmpty() ? null : getGlobalFunctions(args[i]).get(0));
            if (f == null) { println("not found: " + args[i]); continue; }
            funcs.add(f);
        }

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        for (Function f : funcs) {
            Set<String> callers = new HashSet<>();
            for (Reference ref : getReferencesTo(f.getEntryPoint())) {
                Function c = getFunctionContaining(ref.getFromAddress());
                if (c != null && !c.equals(f)) {
                    callers.add(c.getName() + "@" + c.getEntryPoint());
                }
            }
            println("FUNC " + f.getName() + " @ " + f.getEntryPoint() + " callers: " + callers);
            DecompileResults res = decomp.decompileFunction(f, 90, monitor);
            if (res.decompileCompleted()) {
                String fname = f.getEntryPoint() + "_" + f.getName() + ".c";
                try (PrintWriter pw = new PrintWriter(new File(outDir, fname))) {
                    pw.print(res.getDecompiledFunction().getC());
                }
                println("  -> " + fname);
            } else {
                println("  DECOMP FAILED");
            }
        }
        decomp.dispose();
    }
}
