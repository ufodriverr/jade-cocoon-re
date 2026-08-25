// Trace the game's CD access layer: list callers of the PSYQ CD functions,
// then decompile every game-side caller (below the library region) to
// notes/decomp/<addr>_<name>.c
//
// arg 0: output directory for decompiled C
import java.io.File;
import java.io.PrintWriter;
import java.util.HashSet;
import java.util.Set;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class CdCallers extends GhidraScript {
    static final String[] TARGETS = {
        "CdControl", "CdControlB", "CdControlF", "CdIntToPos", "CdPosToInt",
        "CdGetSector", "CdGetSector2", "CdDataSync", "CdDataCallback",
        "CdReadyCallback", "CdSync", "CdReady", "CdMix", "CdSearchFile"
    };
    static final long LIB_START = 0x8004dd00L; // game code sits below this

    @Override
    public void run() throws Exception {
        String outDir = getScriptArgs()[0];
        new File(outDir).mkdirs();

        Set<Function> gameCallers = new HashSet<>();
        for (String name : TARGETS) {
            for (Function f : getGlobalFunctions(name)) {
                println("TARGET " + name + " @ " + f.getEntryPoint());
                for (Reference ref : getReferencesTo(f.getEntryPoint())) {
                    Function caller = getFunctionContaining(ref.getFromAddress());
                    if (caller == null) continue;
                    println("  caller: " + caller.getName() + " @ " + caller.getEntryPoint());
                    if (caller.getEntryPoint().getOffset() < LIB_START) {
                        gameCallers.add(caller);
                    }
                }
            }
        }

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        for (Function f : gameCallers) {
            DecompileResults res = decomp.decompileFunction(f, 60, monitor);
            if (!res.decompileCompleted()) {
                println("DECOMP FAILED: " + f.getName());
                continue;
            }
            String fname = f.getEntryPoint() + "_" + f.getName() + ".c";
            try (PrintWriter pw = new PrintWriter(new File(outDir, fname))) {
                pw.print(res.getDecompiledFunction().getC());
            }
            println("decompiled -> " + fname);
        }
        decomp.dispose();
    }
}
