"""First-pass structural scan of DATA.001.

Finds: first non-zero offset, and occurrences of known PS1 magics
(TIM 0x10, TMD 0x41) at 2048-byte sector boundaries, plus a histogram of
what the first u32 of each sector looks like.
"""
import struct
import sys
from collections import Counter

SEC = 2048


def main():
    path = sys.argv[1]
    f = open(path, "rb")

    tims, tmds = [], []
    first_nonzero = None
    magic_hist = Counter()
    sec_idx = 0
    while True:
        data = f.read(SEC * 1024)
        if not data:
            break
        for i in range(0, len(data), SEC):
            chunk = data[i:i + SEC]
            if first_nonzero is None and any(chunk):
                nz = next(j for j, b in enumerate(chunk) if b)
                first_nonzero = (sec_idx * SEC) + i + nz
            if len(chunk) >= 8:
                magic = struct.unpack_from("<I", chunk, 0)[0]
                magic_hist[magic] += 1
                off = sec_idx * SEC + i
                if magic == 0x10:  # TIM
                    tims.append(off)
                elif magic == 0x41:  # TMD
                    tmds.append(off)
        sec_idx += 1024

    print(f"first non-zero byte at offset 0x{first_nonzero:X}")
    print(f"TIM magic at sector boundary: {len(tims)} hits")
    for o in tims[:10]:
        print(f"   0x{o:X}")
    print(f"TMD magic at sector boundary: {len(tmds)} hits")
    for o in tmds[:10]:
        print(f"   0x{o:X}")
    print("top first-u32 values across sectors:")
    for val, n in magic_hist.most_common(12):
        print(f"   0x{val:08X}  x{n}")


if __name__ == "__main__":
    main()
