"""Every animation a model owns, from the exe's model descriptor table.

The descriptor table at 0x800823F0 has one entry per model file (103 of them, 831..933).
Past the four whole-file ranges (header / textures / mesh / resident animation container)
each descriptor carries a **per-animation sector table** at u16 index `10 + desc[9]`:
one `{startSector, sizeSectors}` pair per animation id. Those sectors hold a BARE
animation block - no container header - and the game streams them one at a time in
`FUN_800254A8`, which reads exactly `desc[desc[9] + animId*2 + 10]`.

That is where the animation frame stream lives. It is why models like 854, 863 and 875
look like they ship no animations at all: their resident container is a single all-zero
sector, and their whole library - 38, 24 and 43 clips - is in the streamed table.

Usage:  python model_anims.py <exe> <split_dir> [fileIdx]
"""
import glob
import os
import struct
import sys

import anim as animmod

PTR_TABLE = 0x800823F0


def _eo(a):
    return a - 0x80010000 + 0x800


def descriptors(exe):
    """[(fileIdx, u16[] descriptor)] in table order."""
    out = []
    ptrs = []
    for i in range(1024):
        p = struct.unpack_from("<I", exe, _eo(PTR_TABLE + i * 4))[0]
        if not (0x8007D000 <= p < 0x800A0000):
            break
        ptrs.append(p)
    for i, p in enumerate(ptrs):
        end = ptrs[i + 1] if i + 1 < len(ptrs) else p + 0x400
        v = [struct.unpack_from("<H", exe, _eo(p + j * 2))[0] for j in range((end - p) // 2)]
        out.append((v[0], v))
    return out


def anim_slots(vals):
    """[(animId, startSector, sizeSectors)] from the per-animation sector table."""
    base = 10 + vals[9]
    out = []
    for k in range((len(vals) - base) // 2):
        start, size = vals[base + 2 * k], vals[base + 2 * k + 1]
        if start and size:
            out.append((k, start, size))
    return out


def blocks_for(exe, split_dir, fidx=None):
    """{fileIdx: [{"id", "sector", "sectors", "frames", "bones", "size", "events"}]}"""
    out = {}
    for fi, vals in descriptors(exe):
        if fidx is not None and fi != fidx:
            continue
        m = glob.glob(os.path.join(split_dir, "%04d_*.bin" % fi))
        if not m:
            continue
        data = open(m[0], "rb").read()
        nsec = len(data) // 2048
        got = []
        for aid, start, size in anim_slots(vals):
            if start + size > nsec:
                continue
            blk = animmod.parse_block(data, start * 2048)
            # A slot that is not an animation (some descriptors list other resources
            # first) simply fails to parse or overruns its own sector range.
            if not blk or blk["size"] > size * 2048:
                continue
            got.append({"id": aid, "sector": start, "sectors": size,
                        "frames": blk["frames"], "bones": blk["bones"],
                        "size": blk["size"], "events": blk["events"]})
        out[fi] = got
    return out


def main():
    exe = open(sys.argv[1], "rb").read()
    split = sys.argv[2]
    only = int(sys.argv[3]) if len(sys.argv) > 3 else None
    res = blocks_for(exe, split, only)
    tot = 0
    for fi in sorted(res):
        bl = res[fi]
        tot += len(bl)
        bones = sorted({b["bones"] for b in bl})
        print("%4d  %3d streamed animations  bones %s  frames %s"
              % (fi, len(bl), bones, [b["frames"] for b in bl][:14]))
    print("%d models, %d streamed animation blocks" % (len(res), tot))


if __name__ == "__main__":
    main()
