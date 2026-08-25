// Dump function statistics: total, auto-named (FUN_), and the named ones.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;

public class FuncStats extends GhidraScript {
    @Override
    public void run() throws Exception {
        int total = 0, auto = 0;
        StringBuilder named = new StringBuilder();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            total++;
            if (f.getName().startsWith("FUN_")) {
                auto++;
            } else {
                named.append(f.getEntryPoint()).append("  ").append(f.getName()).append("\n");
            }
        }
        println("total functions: " + total);
        println("auto FUN_: " + auto + ", named: " + (total - auto));
        println("named list:\n" + named);
    }
}
