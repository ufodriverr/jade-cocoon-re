"""Decode the DATA.001 file table embedded in SLES_022.01.

Table at RAM 0x800759C4 (per FUN_80041a70), 12-byte entries:
    +0  DslLOC pos   (BCD minute, second, sector, track)
    +4  u32 sectors  (read length in 2048-byte sectors)
    +8  u32 unknown
Rebase reference DslLOC at RAM 0x800759DC (table+0x18, i.e. entry[2].pos).
Archive byte offset of entry = (LBA(entry) - LBA(ref)) * 2048 relative to
wherever entry[2] lands... verified empirically below against known TIM/TMD
offsets in the extracted DATA.001.
"""
import struct
import sys

BASE_RAM = 0x80010000
HDR = 0x800
TABLE_RAM = 0x800759C4
REF_RAM = 0x800759DC


def unbcd(b):
    return (b >> 4) * 10 + (b & 0xF)


def loc_to_lba(m, s, f):
    return (unbcd(m) * 60 + unbcd(s)) * 75 + unbcd(f) - 150


def is_bcd(b):
    return (b >> 4) <= 9 and (b & 0xF) <= 9


def main():
    data = open(sys.argv[1], "rb").read()
    off = TABLE_RAM - BASE_RAM + HDR
    ref_off = REF_RAM - BASE_RAM + HDR
    ref_lba = loc_to_lba(data[ref_off], data[ref_off + 1], data[ref_off + 2])

    entries = []
    i = off
    while True:
        m, s, f, t = data[i:i + 4]
        if not (is_bcd(m) and is_bcd(s) and is_bcd(f)) or unbcd(s) >= 60 or unbcd(f) >= 75:
            break
        sectors, unk = struct.unpack_from("<II", data, i + 4)
        if sectors == 0 or sectors > 0x20000:
            break
        lba = loc_to_lba(m, s, f)
        entries.append((lba, sectors, unk, t))
        i += 12

    print(f"ref LBA (0x{REF_RAM:08X}): {ref_lba}")
    print(f"entries parsed: {len(entries)}  (table ends at RAM 0x{TABLE_RAM + len(entries)*12:08X})")
    print(f"{'idx':>4} {'lba':>7} {'rel_off':>10} {'sectors':>7} {'bytes':>10} {'unk':>8} trk")
    for idx, (lba, sectors, unk, t) in enumerate(entries):
        rel = (lba - ref_lba) * 2048
        print(f"{idx:>4} {lba:>7} 0x{rel & 0xFFFFFFFF:08X} {sectors:>7} {sectors*2048:>10,} {unk:>8X} {t}")


if __name__ == "__main__":
    main()
