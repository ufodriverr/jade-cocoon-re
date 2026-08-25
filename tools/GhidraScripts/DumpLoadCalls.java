// For each target loader function, find every call site and report the
// argument values (constants resolved via the decompiler's high pcode).
// args: outFile target1 target2 ...   (targets as 0xADDR)
import java.io.File;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.pcode.HighFunction;
import ghidra.program.model.pcode.PcodeOp;
import ghidra.program.model.pcode.PcodeOpAST;
import ghidra.program.model.pcode.Varnode;
import ghidra.program.model.symbol.Reference;

public class DumpLoadCalls extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        PrintWriter out = new PrintWriter(new File(args[0]));

        Set<Address> targets = new HashSet<>();
        for (int i = 1; i < args.length; i++) {
            targets.add(toAddr(Long.parseLong(args[i].substring(2), 16)));
        }

        // group call sites by caller so each caller decompiles once
        Map<Function, List<Address>> byCaller = new HashMap<>();
        for (Address t : targets) {
            for (Reference ref : getReferencesTo(t)) {
                Function c = getFunctionContaining(ref.getFromAddress());
                if (c == null) continue;
                byCaller.computeIfAbsent(c, k -> new ArrayList<>()).add(ref.getFromAddress());
            }
        }

        DecompInterface decomp = new DecompInterface();
        decomp.openProgram(currentProgram);
        for (Map.Entry<Function, List<Address>> e : byCaller.entrySet()) {
            Function caller = e.getKey();
            DecompileResults res = decomp.decompileFunction(caller, 90, monitor);
            if (!res.decompileCompleted()) {
                out.println(caller.getName() + " @ " + caller.getEntryPoint() + " DECOMP FAILED");
                continue;
            }
            HighFunction hf = res.getHighFunction();
            Iterator<PcodeOpAST> ops = hf.getPcodeOps();
            while (ops.hasNext()) {
                PcodeOpAST op = ops.next();
                if (op.getOpcode() != PcodeOp.CALL) continue;
                Address dest = op.getInput(0).getAddress();
                if (!targets.contains(dest)) continue;
                StringBuilder sb = new StringBuilder();
                sb.append(caller.getName()).append(" @ ").append(op.getSeqnum().getTarget())
                  .append(" -> ").append(dest).append(" args:");
                for (int i = 1; i < op.getNumInputs(); i++) {
                    Varnode v = op.getInput(i);
                    if (v.isConstant()) {
                        sb.append(" #0x").append(Long.toHexString(v.getOffset()));
                    } else if (v.isAddress()) {
                        sb.append(" @").append(v.getAddress());
                    } else {
                        sb.append(" dyn");
                    }
                }
                out.println(sb);
                println(sb.toString());
            }
        }
        decomp.dispose();
        out.close();
    }
}
