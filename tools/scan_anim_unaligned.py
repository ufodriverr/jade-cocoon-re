"""Scan every archive file for animation containers at ANY 4-byte alignment.

`build_index.py` only probes sector-aligned offsets (`sec * 2048`), which is right for
model packages (their containers start a sector) but misses containers embedded inside
overlay / scene / actor packages, where they sit wherever the linker put them.

A hit must be a `{u32 count; u32 offs[count]}` container whose blocks all parse, all
share one bone count, and tile with no gaps - the same test build_index uses.

Usage:  python scan_anim_unaligned.py <split_dir> [maxFileIdx] [out.json]
"""
import glob
import json
import os
import struct
import sys

import anim as animmod


def containers(data, step=4):
    out = []
    n = len(data)
    for base in range(0, n - 8, step):
        cnt = struct.unpack_from("<I", data, base)[0]
        if not (1 <= cnt <= 64):
            continue
        if base + 4 + cnt * 4 > n:
            continue
        blks = animmod.parse_container(data, base)
        if len(blks) != cnt:
            continue
        if len({b["bones"] for b in blks}) != 1:
            continue
        if any(blks[i]["off"] + blks[i]["size"] != blks[i + 1]["off"]
               for i in range(len(blks) - 1)):
            continue
        # first block must start right after the offset table
        if blks[0]["off"] != base + 4 + cnt * 4:
            continue
        out.append({"off": base, "anims": cnt, "bones": blks[0]["bones"],
                    "frames": [b["frames"] for b in blks],
                    "end": blks[-1]["off"] + blks[-1]["size"]})
    return out


def main():
    split = sys.argv[1]
    maxidx = int(sys.argv[2]) if len(sys.argv) > 2 else 10**9
    out_path = sys.argv[3] if len(sys.argv) > 3 else None
    hits = []
    files = sorted(glob.glob(os.path.join(split, "*.bin")))
    for path in files:
        idx = int(os.path.basename(path)[:4])
        if idx > maxidx:
            continue
        data = open(path, "rb").read()
        for c in containers(data):
            c["file"] = idx
            hits.append(c)
            print("file %4d  off 0x%06x  %2d anims  %3d bones  frames %s"
                  % (idx, c["off"], c["anims"], c["bones"], c["frames"][:8]))
    print("%d containers" % len(hits))
    if out_path:
        json.dump(hits, open(out_path, "w"))


if __name__ == "__main__":
    main()
