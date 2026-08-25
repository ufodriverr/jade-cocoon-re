"""Archive-wide index of bone tables (rigs) and animation containers.

`export_all.py` only looked for rigs in the exe and files 100-500, and only borrowed
animations from files within +-40 of the model. Several creatures keep their rig or their
animation set much further away, so this builds one index over the whole archive and
caches it as JSON.

Bone tables are located with a regex on the `self` byte (which is sequential 0,1,2,3...
at stride 8) so the byte-by-byte validator only runs on real candidates - a full-archive
scan then takes seconds instead of half an hour.

Usage:
    python build_index.py <exe> <split_dir> <out.json>
"""
import glob
import json
import os
import re
import struct
import sys

import anim as animmod
import model_anims as MA
import model_index as MI

# self byte == 0,1,2,3 at stride 8 -> the start of a >=4-record bone table.
# Zero-width lookahead so every alignment gets tested: a consuming match eats 26 bytes
# and swallows the real table start, which is usually two bytes further on.
SEED = re.compile(rb"(?=..\x00.{7}\x01.{7}\x02.{7}\x03)", re.DOTALL)


def bone_tables(buf, min_bones=4, max_bones=250):
    """Validated bone tables in a buffer -> [(offset, boneCount, [meshIndex...])]."""
    out = []
    n = len(buf)
    for m in SEED.finditer(buf):
        i = m.start()
        k, prev, ok, mesh = 0, -1, True, []
        while i + k * 8 + 8 <= n:
            depth, slf, _b3, midx, _x = struct.unpack_from("<hBBhh", buf, i + k * 8)
            if depth == -1:
                break
            if slf != k or depth < 0 or depth > 40 or depth > prev + 1:
                ok = False
                break
            prev = max(prev, depth)
            mesh.append(midx)
            k += 1
            if k > max_bones:
                ok = False
                break
        if ok and min_bones <= k:
            out.append((i, k, mesh))
    return out


def anim_containers(data):
    """Sector-aligned animation containers whose blocks tile with no gaps."""
    out = []
    for sec in range(len(data) // 2048):
        base = sec * 2048
        if base + 4 > len(data):
            break
        blks = animmod.parse_container(data, base)
        if not blks:
            continue
        cnt = struct.unpack_from("<I", data, base)[0]
        if len(blks) != cnt:
            continue
        gaps = sum(1 for i in range(len(blks) - 1)
                   if blks[i]["off"] + blks[i]["size"] != blks[i + 1]["off"])
        if gaps == 0:
            out.append({"sector": sec, "anims": cnt, "bones": blks[0]["bones"],
                        "frames": [b["frames"] for b in blks]})
    return out


def build(exe_path, split_dir):
    rigs = []      # {"src": "exe"|path, "off": int, "bones": int, "meshMax": int}
    anims = []     # {"file": idx, "sector": int, "bones": int, "anims": int}

    exe = open(exe_path, "rb").read()
    # The exe's model descriptor table names, for every one of the 103 model files, the
    # sector range that holds its animation container. When a valid container sits there
    # it is the model's REAL animation set and everything else the scan turns up in that
    # file is something else that happens to parse - files 831/832 carry five extra
    # 120-frame cutscene containers deep in the file, and they outscored the real sets by
    # a fraction of a point and stole 20 NPCs. Files whose named range is empty (a single
    # all-zero sector) keep whatever the scan finds, which is how 903's 16-bone set at
    # sector 221 stays available to the eight models that borrow it.
    hdr_anim = {f: s["anim"][0] for f, s in MI.sections(exe).items() if s["anim"]}
    for off, cnt, mesh in bone_tables(exe):
        rigs.append({"src": "exe", "off": off, "addr": 0x80010000 + off - 0x800,
                     "bones": cnt, "meshMax": max(mesh), "uniq": len(set(mesh))})

    files = sorted(glob.glob(os.path.join(split_dir, "*.bin")))
    for n, path in enumerate(files):
        idx = int(os.path.basename(path)[:4])
        buf = open(path, "rb").read()
        for off, cnt, mesh in bone_tables(buf):
            rigs.append({"src": path, "file": idx, "off": off, "bones": cnt,
                         "meshMax": max(mesh), "uniq": len(set(mesh))})
        found = anim_containers(buf)
        named = any(a["sector"] == hdr_anim.get(idx) for a in found)
        for a in found:
            a["file"] = idx
            a["primary"] = (not named) or a["sector"] == hdr_anim.get(idx)
            anims.append(a)
        if n % 200 == 0:
            print("  ...%d/%d files" % (n, len(files)))
    # Per-animation streamed slots. Most of a model's animations are NOT in its resident
    # container: the descriptor carries a {startSector, sizeSectors} pair per animation
    # id and the game streams each clip in on demand (FUN_800254A8). 2474 blocks over the
    # 103 models, against 548 in the resident containers - and for the humanoid NPCs the
    # streamed blocks hold the only rest pose they own.
    streamed = {str(f): b for f, b in MA.blocks_for(exe, split_dir).items() if b}
    return {"rigs": rigs, "anims": anims, "streamed": streamed}


def main():
    exe_path, split_dir, out = sys.argv[1], sys.argv[2], sys.argv[3]
    idx = build(exe_path, split_dir)
    json.dump(idx, open(out, "w"))
    from collections import Counter
    print("%d rigs, bone counts: %s"
          % (len(idx["rigs"]), sorted(Counter(r["bones"] for r in idx["rigs"]).items())))
    print("%d animation containers, bone counts: %s"
          % (len(idx["anims"]), sorted(Counter(a["bones"] for a in idx["anims"]).items())))
    nb = Counter(b["bones"] for v in idx["streamed"].values() for b in v)
    print("%d streamed animation blocks over %d models, bone counts: %s"
          % (sum(len(v) for v in idx["streamed"].values()), len(idx["streamed"]),
             sorted(nb.items())))


if __name__ == "__main__":
    main()
