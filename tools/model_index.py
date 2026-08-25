"""Read the model descriptor table from the exe and classify each sector range.

The exe holds a pointer table at 0x800823F0 (103 entries). Each descriptor is a
u16 array whose first field is the DATA.001 file index (833..848), followed by
(sizeInSectors, cumulativeSectorOffset) pairs for the sub-resources.

For each range we identify the content:
    TIM   - a {count, offs[]} container whose parts start with TIM magic
    ANIM  - a {count, offs[]} container of animation blocks that tile exactly
    MESH  - {u32 totalSize, u32 boneCount, u32 offA, u32 offB} with totalSize
            close to the range size
    ?     - unidentified

Usage: python model_index.py <exe> <split_dir>
"""
import glob
import os
import struct
import sys

import anim
import tim

PTR_TABLE = 0x800823F0
# The table is 103 entries long - one for EVERY model file, 831..933 - not 16. The old
# NPTR = 16 is why the docs said "the exe descriptor table only names 16 models"; the
# loader (FUN_80025268 / FUN_800254A8 / FUN_80025658 / FUN_80025720) indexes it by the
# model id with no bound of its own. Entry 103 is a null pointer, which ends the walk.
NPTR = 256


def exe_off(a):
    return a - 0x80010000 + 0x800


def read_descriptors(exe):
    out = []
    for i in range(NPTR):
        p = struct.unpack_from("<I", exe, exe_off(PTR_TABLE) + i * 4)[0]
        if not (0x80010000 <= p < 0x800CA800):
            break
        vals = struct.unpack_from("<12H", exe, exe_off(p))
        out.append((p, vals))
    return out


def ranges_from(vals):
    """Yield (startSector, sizeSectors) from the (size, cumulative) pairs."""
    out = []
    prev_cum = 0
    i = 2
    while i + 1 < len(vals):
        size, cum = vals[i], vals[i + 1]
        if size == 0 or cum != prev_cum + size:
            break
        out.append((prev_cum, size))
        prev_cum = cum
        i += 2
    return out


def ranges_all(vals):
    """Like ranges_from, plus the FINAL range.

    The descriptor stores (size, cumulativeEnd) pairs, and the last section is written
    as a lone size with no cumulative partner - the word after it is the sub-resource
    offset, not a cumulative total, so the pair walk stops one range early. That last
    range is the animation container, which is exactly the one we want.
    """
    out = ranges_from(vals)
    prev_cum = out[-1][0] + out[-1][1] if out else 0
    i = 2 + 2 * len(out)
    if i < len(vals) and vals[i]:
        out.append((prev_cum, vals[i]))
    return out


def sections(exe):
    """{fileIdx: {"ranges": [(start, size), ...], "anim": (start, size)}} for all 103
    model files. The last range is the model's own animation container; a range of one
    sector that reads as all zeroes means the model genuinely ships no animations."""
    out = {}
    for _p, vals in read_descriptors(exe):
        rs = ranges_all(vals)
        out[vals[0]] = {"ranges": rs, "anim": rs[-1] if rs else None}
    return out


def classify(data, start, size):
    base = start * 2048
    if base + 16 > len(data):
        return "past-EOF", ""
    # MESH signature
    total, bones, offA, offB = struct.unpack_from("<4I", data, base)
    if 0 < total <= size * 2048 and 1 <= bones <= 200 and 8 < offA < total and offA < offB < total:
        return "MESH", f"size={total} bones={bones} verts@0x{offA:X} idx@0x{offB:X}"
    # container?
    cnt = struct.unpack_from("<I", data, base)[0]
    if 1 <= cnt <= 256 and base + 4 + cnt * 4 <= len(data):
        offs = struct.unpack_from(f"<{cnt}I", data, base + 4)
        if offs and offs[0] == (cnt + 1) * 4:
            t = tim.parse(data, base + offs[0])
            if t:
                return "TIM", f"{cnt} textures, first {t['width']}x{t['height']}"
            blks = anim.parse_container(data, base)
            if len(blks) == cnt:
                gaps = sum(1 for i in range(len(blks) - 1)
                           if blks[i]["off"] + blks[i]["size"] != blks[i + 1]["off"])
                if gaps == 0:
                    frames = [b["frames"] for b in blks]
                    return "ANIM", f"{cnt} anims, {blks[0]['bones']} bones, frames={frames}"
            return "container", f"{cnt} parts"
    return "?", ""


def main():
    exe = open(sys.argv[1], "rb").read()
    split_dir = sys.argv[2]
    for p, vals in read_descriptors(exe):
        fidx = vals[0]
        matches = glob.glob(os.path.join(split_dir, f"{fidx:04d}_*"))
        if not matches:
            print(f"file {fidx}: (not split out)")
            continue
        data = open(matches[0], "rb").read()
        print(f"=== file {fidx}  ({len(data):,} B = {len(data)//2048} sectors)  desc@0x{p:08X}")
        for start, size in ranges_from(vals):
            kind, info = classify(data, start, size)
            print(f"    sectors {start:4}-{start+size:<4} ({size:3}) {kind:10} {info}")


if __name__ == "__main__":
    main()
