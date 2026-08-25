// Walk the caller graph upward from given seed functions (by name or hex addr),
// printing the tree until we reach game code (below LIB_START) or depth limit.
// args: seed1 seed2 ...
import java.util.HashSet;
import java.util.Set;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class CallersUp extends GhidraScript {
    static final long LIB_START = 0x8004dd00L;
    Set<Function> visited = new HashSet<>();

    @Override
    public void run() throws Exception {
        for (String arg : getScriptArgs()) {
            Function f;
            if (arg.startsWith("0x")) {
                f = getFunctionAt(toAddr(Long.parseLong(arg.substring(2), 16)));
            } else {
                var list = getGlobalFunctions(arg);
                f = list.isEmpty() ? null : list.get(0);
            }
            if (f == null) { println("seed not found: " + arg); continue; }
            println("SEED " + f.getName() + " @ " + f.getEntryPoint());
            walkUp(f, 1, 6);
        }
    }

    void walkUp(Function f, int depth, int maxDepth) {
        if (depth > maxDepth || !visited.add(f)) return;
        Set<Function> callers = new HashSet<>();
        for (Reference ref : getReferencesTo(f.getEntryPoint())) {
            Function c = getFunctionContaining(ref.getFromAddress());
            if (c != null && !c.equals(f)) callers.add(c);
        }
        for (Function c : callers) {
            boolean game = c.getEntryPoint().getOffset() < LIB_START;
            println("  ".repeat(depth) + (game ? "[GAME] " : "") + c.getName() + " @ " + c.getEntryPoint());
            if (!game) {
                walkUp(c, depth + 1, maxDepth);
            }
        }
    }
}
