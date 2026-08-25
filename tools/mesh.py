"""Jade Cocoon mesh block parser.

Format recovered from the game's own decoder:
  FUN_8002188c  - skips a 0x10 header, then parses meshCount objects sequentially
  FUN_800224c0  - parses ONE mesh object: 0x28 count header + a tagged chunk stream
  FUN_8002269c  - reads the 10 u32 counts and allocates the runtime records
  0x8007DA04    - jump table of 8 chunk handlers (one per PS1 polygon type)

Mesh block:
    +0x00 u32 totalSize
    +0x04 u32 meshCount        (one mesh object per bone)
    +0x08 u32 unk1
    +0x0C u32 unk2
    +0x10 mesh objects, back to back

Mesh object:
    +0x00 u32 counts[10]       (0x28 bytes; index = chunk type)
    +0x28 chunks: { u8 type; u8 a; u8 b; u8 flags; u8 body[BODY[type]] }

Chunk types map 1:1 to the PS1 primitive types; textured types (2,3,6,7) carry a
texture-page callback in the parallel table at 0x8007DA2C.
"""
import struct
import sys

# type -> (name, gpu code, on-disc body size, runtime record size)
TYPES = {
    0: ("F3",  0x20, 0x24, 0x24),
    1: ("G3",  0x30, 0x3C, 0x3C),
    2: ("FT3", 0x24, 0x24, 0x30),
    3: ("GT3", 0x34, 0x40, 0x48),
    4: ("F4",  0x28, 0x2C, 0x2C),
    5: ("G4",  0x38, 0x50, 0x50),
    6: ("FT4", 0x2C, 0x2C, 0x38),
    7: ("GT4", 0x3C, 0x54, 0x5C),
}

# Variable-size chunk types: body = BASE + count * 0x14, count = first u32 of body.
#   type 8 -> FUN_80023074 (base 4), type 9 -> FUN_80023274 (base 8)
VARIABLE = {8: 4, 9: 8}


def chunk_body_size(data, p, t):
    """Body size of the chunk whose 4-byte header starts at p."""
    if t in TYPES:
        return TYPES[t][2]
    if t in VARIABLE:
        n = struct.unpack_from("<I", data, p + 4)[0]
        if n > 20000:
            return None
        return VARIABLE[t] + n * 0x14
    return None


def parse_mesh_object(data, off):
    """Parse one mesh object. Returns (info, nextOff) or (None, None)."""
    if off + 0x28 > len(data):
        return None, None
    counts = list(struct.unpack_from("<10I", data, off))
    if any(c > 20000 for c in counts):
        return None, None
    total_chunks = sum(counts)
    p = off + 0x28
    chunks = []
    for _ in range(total_chunks):
        if p + 4 > len(data):
            return None, None
        t = data[p]
        body = chunk_body_size(data, p, t)
        if body is None:
            return {"off": off, "counts": counts, "chunks": chunks,
                    "stopped_at_type": t, "pos": p}, None
        chunks.append((t, p, data[p + 3]))
        p += 4 + body
    return {"off": off, "counts": counts, "chunks": chunks, "end": p}, p


def parse_block(data, base):
    total, mesh_count, u1, u2 = struct.unpack_from("<4I", data, base)
    objs = []
    p = base + 0x10
    for i in range(mesh_count):
        info, nxt = parse_mesh_object(data, p)
        if info is None:
            return {"total": total, "meshCount": mesh_count, "u1": u1, "u2": u2,
                    "objs": objs, "failed_at": i, "pos": p}
        objs.append(info)
        if nxt is None:
            return {"total": total, "meshCount": mesh_count, "u1": u1, "u2": u2,
                    "objs": objs, "stopped_at": i, "pos": info["pos"],
                    "stopped_type": info["stopped_at_type"]}
        p = nxt
    return {"total": total, "meshCount": mesh_count, "u1": u1, "u2": u2,
            "objs": objs, "end": p, "consumed": p - base}


def main():
    path, sector = sys.argv[1], int(sys.argv[2])
    data = open(path, "rb").read()
    base = sector * 2048
    r = parse_block(data, base)
    print(f"mesh block @sector {sector}: totalSize={r['total']} meshCount={r['meshCount']} "
          f"u1=0x{r['u1']:X} u2=0x{r['u2']:X}")
    if "failed_at" in r:
        print(f"  FAILED at mesh {r['failed_at']} (offset 0x{r['pos']-base:X})")
        return
    if "stopped_at" in r:
        print(f"  stopped at mesh {r['stopped_at']}: unhandled chunk type "
              f"{r['stopped_type']} at 0x{r['pos']-base:X}")
        return
    print(f"  parsed all {len(r['objs'])} mesh objects, consumed {r['consumed']} bytes")
    # the u2 header field marks the end of the mesh-object stream
    match = "EXACT MATCH with u2" if r["consumed"] == r["u2"] else \
        f"MISMATCH: consumed {r['consumed']} vs u2 {r['u2']} (diff {r['consumed']-r['u2']})"
    print(f"  -> {match}")
    tally = {}
    for o in r["objs"]:
        for t, _, _ in o["chunks"]:
            tally[t] = tally.get(t, 0) + 1
    print("  primitives by type: " +
          ", ".join(f"{TYPES[t][0] if t in TYPES else 'T'+str(t)}={n}" for t, n in sorted(tally.items())))
    if "-v" in sys.argv:
        for i, o in enumerate(r["objs"][:8]):
            nz = {(TYPES[k][0] if k in TYPES else "T"+str(k)): c for k, c in enumerate(o["counts"]) if c}
            print(f"    mesh{i:3} @0x{o['off']-base:06X}: {nz}")


if __name__ == "__main__":
    main()
