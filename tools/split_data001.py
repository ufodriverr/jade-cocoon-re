"""Verify the decoded file table against DATA.001 and split it into sub-files.

Usage:
    python split_data001.py <SLES_022.01> <DATA.001> <out_dir> [--verify-only]

Output names: NNNN_<off>.<ext> where ext is guessed from magic.
Also writes data001_index.json with the full table.
"""
import json
import os
import struct
import sys

from dump_file_table import BASE_RAM, HDR, TABLE_RAM, loc_to_lba, is_bcd, unbcd

REF_LBA = 392


def guess_ext(head):
    if head[:4] == b"\x10\x00\x00\x00":
        return "tim"
    if head[:4] == b"\x41\x00\x00\x00":
        return "tmd"
    if head[:4] == b"pQES":
        return "seq"
    if head[:3] == b"pBAV" or head[:4] == b"VABp":
        return "vab"
    if head[:4] == b"VAGp":
        return "vag"
    return "bin"


def main():
    exe_path, dat_path, out_dir = sys.argv[1:4]
    verify_only = "--verify-only" in sys.argv

    exe = open(exe_path, "rb").read()
    entries = []
    i = TABLE_RAM - BASE_RAM + HDR
    while True:
        m, s, f, t = exe[i:i + 4]
        if not (is_bcd(m) and is_bcd(s) and is_bcd(f)) or unbcd(s) >= 60 or unbcd(f) >= 75:
            break
        sectors, size = struct.unpack_from("<II", exe, i + 4)
        if sectors == 0 or sectors > 0x20000:
            break
        entries.append({"lba": loc_to_lba(m, s, f), "sectors": sectors, "size": size})
        i += 12

    dat = open(dat_path, "rb")
    dat_size = os.path.getsize(dat_path)

    ok = bad = skipped = 0
    kinds = {}
    index = []
    os.makedirs(out_dir, exist_ok=True)
    for idx, e in enumerate(entries):
        off = (e["lba"] - REF_LBA) * 2048
        if off < 0 or off + e["size"] > dat_size:
            skipped += 1
            index.append({"idx": idx, **e, "offset": off, "note": "outside archive"})
            continue
        # sanity: sectors must cover size
        if (e["size"] + 2047) // 2048 == e["sectors"]:
            ok += 1
        else:
            bad += 1
        dat.seek(off)
        head = dat.read(16)
        ext = guess_ext(head)
        kinds[ext] = kinds.get(ext, 0) + 1
        index.append({"idx": idx, **e, "offset": off, "ext": ext})
        if not verify_only:
            dat.seek(off)
            with open(os.path.join(out_dir, f"{idx:04d}_{off:08X}.{ext}"), "wb") as fp:
                fp.write(dat.read(e["size"]))

    print(f"entries: {len(entries)}, sectors==ceil(size/2048): {ok}, mismatch: {bad}, outside: {skipped}")
    print("by magic:", kinds)
    with open(os.path.join(out_dir, "..", "data001_index.json"), "w") as fp:
        json.dump(index, fp, indent=1)
    print("index written")


if __name__ == "__main__":
    main()
