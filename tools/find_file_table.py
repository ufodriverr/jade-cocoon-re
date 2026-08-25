"""Hunt for the DATA.001 file table inside SLES_022.01.

Theory: the archive has no header, so the exe must hold a table of sub-file
locations - either byte offsets (sector-aligned, < 211,658,752), sector
numbers relative to archive start (< 103,349), or absolute disc LBAs
(542..103,890 for DATA.001).

Scans the exe image for monotonic increasing u32 runs at strides 4/8/12/16
and classifies them. Reports RAM address (base 0x80010000 + file offset).
"""
import struct
import sys

BASE = 0x80010000
HDR = 0x800
ARCHIVE_SIZE = 211_658_752
ARCHIVE_SECTORS = ARCHIVE_SIZE // 2048  # 103,349
LBA_START, LBA_END = 542, 103_891
MIN_RUN = 12


def classify(vals):
    if all(v % 2048 == 0 and 0 < v < ARCHIVE_SIZE for v in vals):
        return "byte-offsets(sector-aligned)"
    if all(0 < v < ARCHIVE_SECTORS for v in vals):
        return "relative-sectors"
    if all(LBA_START <= v <= LBA_END for v in vals):
        return "absolute-LBAs"
    return None


def main():
    data = open(sys.argv[1], "rb").read()[HDR:]
    n = len(data) // 4
    u32 = struct.unpack(f"<{n}I", data[:n * 4])

    found = []
    for stride_words in (1, 2, 3, 4):
        i = 0
        while i < n:
            j = i
            run = [u32[j]]
            while j + stride_words < n and u32[j + stride_words] > u32[j]:
                j += stride_words
                run.append(u32[j])
            if len(run) >= MIN_RUN:
                kind = classify(run)
                if kind:
                    found.append((i * 4, stride_words * 4, len(run), kind, run))
                i = j + stride_words
            else:
                i += 1

    # dedup: a stride-4 run inside a larger reported region is noise; sort by length
    found.sort(key=lambda x: -x[2])
    seen_spans = []
    for off, stride, count, kind, run in found:
        span = (off, off + count * stride)
        if any(s <= off and span[1] <= e for s, e in seen_spans):
            continue
        seen_spans.append(span)
        ram = BASE + off
        print(f"RAM 0x{ram:08X} (file+0x{off + HDR:X}) stride {stride:>2} count {count:>4}  {kind}")
        print(f"    first: {[hex(v) for v in run[:6]]}")
        print(f"    last:  {[hex(v) for v in run[-3:]]}")


if __name__ == "__main__":
    main()
