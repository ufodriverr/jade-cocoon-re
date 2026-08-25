// Pre-analysis setup for a raw-imported PS-X EXE (SLES-02201).
// Adds the PS1 memory map around the loaded text block and marks the entry point.
// Values come from the PS-X EXE header: t_addr 0x80010000, t_size 0xBA800, pc0 0x8001047C.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.Memory;

public class PsxSetup extends GhidraScript {
    @Override
    public void run() throws Exception {
        Memory mem = currentProgram.getMemory();

        // Kernel area below the exe
        mem.createUninitializedBlock("kernel_ram", toAddr(0x80000000L), 0x10000L, false);
        // Everything above the exe image up to end of 2MB RAM: BSS + heap + stack
        mem.createUninitializedBlock("bss_heap", toAddr(0x800CA800L), 0x80200000L - 0x800CA800L, false);
        // Scratchpad (D-cache used as fast RAM)
        mem.createUninitializedBlock("scratchpad", toAddr(0x1F800000L), 0x400L, false);
        // Memory-mapped I/O
        mem.createUninitializedBlock("io_ports", toAddr(0x1F801000L), 0x2000L, false);

        Address entry = toAddr(0x8001047CL);
        createLabel(entry, "entry", true);
        addEntryPoint(entry);
        disassemble(entry);
        println("PSX memory map created, entry at " + entry);
    }
}
