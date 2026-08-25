"""Find bone-hierarchy tables in the exe.

From FUN_8001e858:
    psVar6 = *(short**)(spawnParams + 0x34);
    while (*psVar6 != -1) { psVar6 += 4; count++; }   // short* += 4 == 8 bytes

So a bone list is an array of 8-byte records terminated by s16 -1 at +0.
The renderer (FUN_80047e4c) reads:
    +0 s16 boneIndex   (used as `+2`, i.e. an animation keyframe slot)
    +2 u8  flagA
    +3 u8  flagB
    +4 s16 meshIndex   (which mesh object to draw for this bone)
    +6 s16 ?

Usage: python find_bonelist.py <exe> [minLen]
"""
import struct
import sys

BASE, HDR = 0x80010000, 0x800


def main():
    exe = open(sys.argv[1], "rb").read()
    min_len = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    n = (len(exe) - HDR) // 2
    u16 = struct.unpack_from(f"<{n}H", exe, HDR)

    def s16(i):
        v = u16[i]
        return v - 0x10000 if v & 0x8000 else v

    results = []
    i = 0
    while i + 4 < n:
        # candidate start: plausible record
        cnt = 0
        j = i
        ok = True
        while j + 4 <= n:
            b0 = s16(j)
            if b0 == -1:
                break
            m = s16(j + 2)
            if not (0 <= b0 <= 200 and -1 <= m <= 200):
                ok = False
                break
            cnt += 1
            j += 4
            if cnt > 300:
                ok = False
                break
        if ok and cnt >= min_len and j + 4 <= n and s16(j) == -1:
            results.append((BASE + i * 2, cnt))
            i = j + 4
        else:
            i += 1

    for addr, cnt in results:
        off = addr - BASE + HDR
        recs = []
        for k in range(min(cnt, 8)):
            b0, f, m, x = struct.unpack_from("<hHhh", exe, off + k * 8)
            recs.append((b0, m))
        print(f"0x{addr:08X}: {cnt:3} bones  first(bone,mesh)={recs}")
    print(f"{len(results)} candidate bone tables")


if __name__ == "__main__":
    main()
