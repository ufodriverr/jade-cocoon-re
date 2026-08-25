"""Second pass table hunt: per-class windowed scan.

For each class (byte-offsets, relative sectors, absolute LBAs) and each
stride, find maximal runs where every element is a valid class member AND
non-decreasing. Also scans for (value, size)-style pairing by allowing the
run to be non-strict. Reports runs >= MIN_RUN.
"""
import struct
import sys

BASE = 0x80010000
HDR = 0x800
ARCHIVE_SIZE = 211_658_752
ARCHIVE_SECTORS = ARCHIVE_SIZE // 2048
LBA_START, LBA_END = 542, 103_891
MIN_RUN = 10

CLASSES = {
    "byte-off": lambda v: v % 2048 == 0 and 0 < v < ARCHIVE_SIZE,
    "rel-sec": lambda v: 0 < v < ARCHIVE_SECTORS,
    "abs-lba": lambda v: LBA_START <= v <= LBA_END,
}


def main():
    data = open(sys.argv[1], "rb").read()[HDR:]
    n = len(data) // 4
    u32 = struct.unpack(f"<{n}I", data[:n * 4])

    results = []
    for cname, valid in CLASSES.items():
        for sw in (1, 2, 3, 4):  # stride in words
            for phase in range(sw):
                i = phase
                run_start = None
                prev = -1
                count = 0
                while i < n:
                    v = u32[i]
                    if valid(v) and v >= prev:
                        if run_start is None:
                            run_start = i
                            count = 0
                        count += 1
                        prev = v
                    else:
                        if run_start is not None and count >= MIN_RUN:
                            results.append((run_start, sw, count, cname))
                        run_start = None
                        prev = -1
                    i += sw
                if run_start is not None and count >= MIN_RUN:
                    results.append((run_start, sw, count, cname))

    results.sort(key=lambda x: -x[2])
    reported = []
    for start, sw, count, cname in results[:400]:
        span = (start * 4, (start + count * sw) * 4)
        # skip if fully inside an already-reported longer span (any stride)
        if any(s <= span[0] and span[1] <= e for s, e, _ in reported):
            continue
        reported.append((span[0], span[1], cname))
        vals = [u32[start + k * sw] for k in range(count)]
        ram = BASE + start * 4
        print(f"RAM 0x{ram:08X} (file+0x{start * 4 + HDR:X}) stride {sw * 4:>2} "
              f"count {count:>4} {cname}")
        print(f"    first: {[hex(v) for v in vals[:6]]}")
        print(f"    last:  {[hex(v) for v in vals[-3:]]}")
        if len(reported) >= 25:
            break


if __name__ == "__main__":
    main()
