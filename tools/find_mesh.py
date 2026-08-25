"""Locate the packed mesh header inside package sub-files.

Header derived from FUN_8004c7e0 (the primitive-type dispatcher): a run of
{s16 count, s16 pad, u32 offset} pairs, one per PS1 polygon type, in the order
F3, G3, FT3, GT3, F4, G4, FT4, GT4 (byte offsets 0x00,0x08,...,0x38).

Confirmed record strides (loop increments in the emitters):
    FT3 (0x24) = 48 bytes    FT4 (0x2C) = 56 bytes
Others are solved by requiring the blocks to tile contiguously.

Test: for a real header, offset[i] + count[i]*stride[i] == offset[i+1] for the
non-empty entries.
"""
import struct
import sys

# byte offset in header -> (name, gpu code, stride guess)
TYPES = [
    ("F3", 0x20, 20), ("G3", 0x30, 28), ("FT3", 0x24, 48), ("GT3", 0x34, 56),
    ("F4", 0x28, 24), ("G4", 0x38, 36), ("FT4", 0x2C, 56), ("GT4", 0x3C, 68),
]


def read_header(data, off):
    """Return list of (name, count, offset) or None."""
    if off + 0x40 > len(data):
        return None
    out = []
    for i, (name, code, stride) in enumerate(TYPES):
        p = off + i * 8
        cnt = struct.unpack_from("<h", data, p)[0]
        ptr = struct.unpack_from("<I", data, p + 4)[0]
        if cnt < 0 or cnt > 4000:
            return None
        if cnt and (ptr < 0x40 or ptr > len(data)):
            return None
        out.append((name, cnt, ptr, stride))
    if not any(c for _, c, _, _ in out):
        return None
    return out


def score(hdr, buflen):
    """How well do the non-empty blocks tile contiguously?"""
    blocks = sorted(((p, c, s, n) for n, c, p, s in hdr if c), key=lambda b: b[0])
    if not blocks:
        return 0, []
    good = 0
    for i, (p, c, s, n) in enumerate(blocks):
        end = p + c * s
        if i + 1 < len(blocks):
            if end == blocks[i + 1][0]:
                good += 1
        elif end <= buflen:
            good += 1
    return good, blocks


def main():
    path = sys.argv[1]
    data = open(path, "rb").read()
    step = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    best = []
    for off in range(0, min(len(data), 0x20000), step):
        hdr = read_header(data, off)
        if not hdr:
            continue
        g, blocks = score(hdr, len(data))
        if g >= max(1, len(blocks) - 1) and len(blocks) >= 2:
            best.append((g, len(blocks), off, hdr))
    best.sort(key=lambda x: (-x[0], -x[1]))
    for g, nb, off, hdr in best[:10]:
        print(f"header @0x{off:X}  ({g}/{nb} blocks tile)")
        for name, cnt, ptr, stride in hdr:
            if cnt:
                print(f"    {name:4} x{cnt:5} @0x{ptr:06X} stride {stride} -> ends 0x{ptr+cnt*stride:X}")
    print(f"{len(best)} candidate headers in {path}")


if __name__ == "__main__":
    main()
