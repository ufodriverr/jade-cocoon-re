// Patch an overlay file's bytes into program memory at its runtime address,
// then find function prologues (addiu sp,sp,-X) and create+analyze functions.
// args: overlayFilePath hexLoadAddr skipBytes
import java.nio.file.Files;
import java.nio.file.Paths;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

public class PatchOverlay extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        byte[] all = Files.readAllBytes(Paths.get(args[0]));
        long base = Long.parseLong(args[1].substring(2), 16);
        int skip = Integer.parseInt(args[2]);
        byte[] body = new byte[all.length - skip];
        System.arraycopy(all, skip, body, 0, body.length);

        Address start = toAddr(base);
        // clear any existing code units so setBytes succeeds
        clearListing(start, start.add(body.length - 1));
        currentProgram.getMemory().setBytes(start, body);
        println("patched " + body.length + " bytes at " + start);

        int made = 0;
        for (int off = 0; off + 4 <= body.length; off += 4) {
            int w = (body[off] & 0xFF) | (body[off + 1] & 0xFF) << 8
                  | (body[off + 2] & 0xFF) << 16 | (body[off + 3] & 0xFF) << 24;
            // addiu sp,sp,-X : opcode 0x27BD with negative immediate
            if ((w >>> 16) == 0x27BD && (w & 0x8000) != 0) {
                Address a = start.add(off);
                if (getFunctionAt(a) == null) {
                    disassemble(a);
                    if (createFunction(a, "ovl_" + a) != null) made++;
                }
            }
        }
        println("created " + made + " overlay functions");
        analyzeChanges(currentProgram);
    }
}
