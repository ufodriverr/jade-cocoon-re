"""Find the array of 0x54-byte mesh objects inside package files.

From FUN_80047e4c:  FUN_8004c7e0(meshArrayBase + meshIndex * 0x54, ...)
From FUN_8004c7e0:  the object is 10 x {s16 count, s16 pad, u32 ptr} + 4 bytes = 0x54.

On disc the pointers are almost certainly offsets (relocated at load). This scans
for runs of >= 2 consecutive plausible records, which is a far stronger filter
than a single record.

Usage: python find_mesh_array.py <file> [--base-rel] [--min-run N]
"""
import struct
import sys

NPAIR = 10
RECSZ = 0x54


def rec_ok(data, off, maxoff):
    """Validate one 0x54 record; return list of (count, ptr) or None."""
    if off + RECSZ > len(data):
        return None
    pairs = []
    nonzero = 0
    for i in range(NPAIR):
        cnt, pad, ptr = struct.unpack_from("<hHI", data, off + i * 8)
        if cnt < 0 or cnt > 4000:
            return None
        if pad != 0:
            return None
        if cnt:
            if ptr == 0 or ptr > maxoff:
                return None
            nonzero += 1
        pairs.append((cnt, ptr))
    if nonzero == 0:
        return None
    return pairs


def main():
    path = sys.argv[1]
    min_run = int(sys.argv[sys.argv.index("--min-run") + 1]) if "--min-run" in sys.argv else 2
    data = open(path, "rb").read()
    maxoff = len(data)

    runs = []
    off = 0
    while off + RECSZ <= len(data):
        r = rec_ok(data, off, maxoff)
        if r:
            start = off
            recs = []
            while off + RECSZ <= len(data):
                rr = rec_ok(data, off, maxoff)
                if not rr:
                    break
                recs.append(rr)
                off += RECSZ
            if len(recs) >= min_run:
                runs.append((start, recs))
        else:
            off += 4
    runs.sort(key=lambda x: -len(x[1]))
    for start, recs in runs[:6]:
        print(f"=== array @0x{start:X}: {len(recs)} records of 0x54")
        for i, r in enumerate(recs[:4]):
            parts = [f"t{j}:{c}@0x{p:X}" for j, (c, p) in enumerate(r) if c]
            print(f"   rec{i}: " + "  ".join(parts))
    print(f"{len(runs)} candidate arrays (min run {min_run}) in {path}")


if __name__ == "__main__":
    main()
