// Print the disassembly listing of a function.
// args: hexAddr
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;

public class DumpAsm extends GhidraScript {
    @Override
    public void run() throws Exception {
        Address a = toAddr(Long.parseLong(getScriptArgs()[0].substring(2), 16));
        Function f = getFunctionAt(a);
        if (f == null) { println("no function at " + a); return; }
        Instruction ins = getInstructionAt(a);
        while (ins != null && f.getBody().contains(ins.getAddress())) {
            println(ins.getAddress() + "  " + ins.toString());
            ins = ins.getNext();
        }
    }
}
