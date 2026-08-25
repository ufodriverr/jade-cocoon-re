"""Jade Cocoon appearance blob parser (MODEL+0x4C).

Package section 0 of a model file is `{u32 size; u8 blob[size]}` and the game copies
it verbatim into MODEL+0x4C (FUN_8002607C). It holds everything about a creature that
is NOT geometry: its growth stages, its per-bone scales, which body-part groups it has,
and its attachment markers. It is also the table the merge blender reads
(FUN_80010DB0 / FUN_8004A520 / FUN_80011904).

    struct AppearanceBlob {
      u32 offAnimTable;   // -> { u32 count; ... }
      u32 offMarkers;     // -> Marker[], terminated by a record with id/bone valid
                          //    but x==y==z==-1 (FUN_80018908 stops there)
      u32 offStages;      // -> { u32 stageCount; u32 boneCount; Stage[stageCount] }
    };
    struct Marker { s16 id, bone, x, y, z, unk; };          // 12 bytes
    struct Stage  {                                          // size explicit at +0x14
      u32 offGlobalScale;  // -> s32 [3]                     1.12 fixed
      u32 offBoneScale;    // -> {s16 x,y,z,pad}[boneCount]  1.12 fixed
      u32 offPartFlagsA;   // -> s16[3]   <2 hides the group
      u32 offPartFlagsB;   // -> s16[3]   ==0 sets draw bit 4
      u32 offMeshWeights;  // -> s32[boneCount]  per-mesh blend weight
      u32 size;
    };

Part-flag groups map to fixed bone bitmasks in the exe (FUN_80019B14):
    group 0 = 0x000001F8 -> bones 3-8    arms / front limbs
    group 1 = 0x0000F000 -> bones 12-15  wings
    group 2 = 0x007E0000 -> bones 17-22  rear legs
"""
import struct

PART_MASKS = (0x000001F8, 0x0000F000, 0x007E0000)
PART_NAMES = ("arms", "wings", "legs")
GROUND_MARKER_ID = 0x26


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def bones_in_group(g):
    return [i for i in range(32) if PART_MASKS[g] >> i & 1]


def parse(pkg, off=0):
    """Parse the `{u32 size; blob}` container at `off`. Returns None if it is not one."""
    if off + 4 > len(pkg):
        return None
    size = _u32(pkg, off)
    if not (0x40 <= size <= 0x20000) or off + 4 + size > len(pkg):
        return None
    blob = pkg[off + 4: off + 4 + size]
    try:
        off_anim, off_mark, off_stage = struct.unpack_from("<3I", blob, 0)
    except struct.error:
        return None
    # All three sections are OPTIONAL and the game guards each on non-zero:
    # FUN_80024EA0 (anim table), FUN_80024ECC (markers) and FUN_80025010 (stages) each
    # return 0 when their offset word is 0. Non-merging models - every NPC, boss and
    # player character - legitimately ship offMarkers == 0 and offStages == 0, so
    # demanding all three be present threw away the blob for 55 of the 103 models that
    # have one, which is exactly the population whose bone count we cannot otherwise
    # determine. See RIG_ATTRIBUTION.md.
    if any(o and not 0 < o < size for o in (off_anim, off_mark, off_stage)):
        return None
    if not off_anim:            # offAnimTable is the one field never observed as zero
        return None

    # stages
    n_stage = n_bone = 0
    stages = []
    if off_stage:
        if off_stage + 8 > size:
            return None
        n_stage, n_bone = struct.unpack_from("<2I", blob, off_stage)
        if not (1 <= n_stage <= 16 and 1 <= n_bone <= 64):
            return None
    p = off_stage + 8
    for _ in range(n_stage):
        if p + 0x18 > size:
            return None
        o_gs, o_bs, o_fa, o_fb, o_mw, rec = struct.unpack_from("<6I", blob, p)
        if not (0x18 <= rec <= 0x4000) or p + rec > size:
            return None
        if not all(0 < o < rec for o in (o_gs, o_bs, o_fa, o_fb, o_mw)):
            return None
        stages.append({
            "globalScale": list(struct.unpack_from("<3i", blob, p + o_gs)),
            "boneScale": [list(struct.unpack_from("<3h", blob, p + o_bs + i * 8))
                          for i in range(n_bone)],
            "partFlagsA": list(struct.unpack_from("<3h", blob, p + o_fa)),
            "partFlagsB": list(struct.unpack_from("<3h", blob, p + o_fb)),
            "meshWeights": list(struct.unpack_from("<%di" % n_bone, blob, p + o_mw)),
        })
        p += rec

    # markers: 12-byte records; FUN_80018908 stops on the first with x==-1
    markers = []
    q = off_mark
    while off_mark and q + 12 <= size and len(markers) < 256:
        r = struct.unpack_from("<6h", blob, q)
        if r[2] == -1 and r[3] == -1 and r[4] == -1:
            break
        markers.append({"id": r[0], "bone": r[1], "pos": list(r[2:5]), "unk": r[5]})
        q += 12

    # animation table: {u32 count; Entry[count]}. FUN_80024EA0 returns blob+offAnim+4,
    # i.e. the first entry, so the count sits at offAnim itself. The stride is 60 bytes
    # for every model measured except 831/832 (the two player characters) at 64, so it
    # is derived from the gap to whatever section comes next rather than assumed.
    anim_count = _u32(blob, off_anim) if off_anim + 4 <= size else 0
    tbl_start = off_anim + 4
    tbl_end = min([o for o in (off_mark, off_stage, size) if o and o > tbl_start] or [size])
    stride = (tbl_end - tbl_start) // anim_count if anim_count else 0
    entries = []
    if anim_count and stride >= 8:
        for i in range(anim_count):
            e = tbl_start + i * stride
            if e + stride > size:
                break
            entries.append(list(struct.unpack_from("<%dh" % (stride // 2), blob, e)))

    return {
        "blobSize": size,
        "boneCount": n_bone,
        "stageCount": n_stage,
        "stages": stages,
        "markers": markers,
        "animTableCount": anim_count,
        "animEntryStride": stride,
        "animTable": entries,
        # Without stages there are no part flags, and the game draws every group.
        "hasPart": ({PART_NAMES[i]: stages[-1]["partFlagsA"][i] >= 2 for i in range(3)}
                    if stages else {n: True for n in PART_NAMES}),
    }


def find(pkg):
    """The blob is at file offset 0 in the model packages; fall back to a sector scan."""
    r = parse(pkg, 0)
    if r:
        return 0, r
    for sec in range(min(len(pkg) // 2048, 8)):
        r = parse(pkg, sec * 2048)
        if r:
            return sec * 2048, r
    return None, None


if __name__ == "__main__":
    import glob
    import json
    import os
    import sys
    d = sys.argv[1]
    which = [int(a) for a in sys.argv[2:]] or None
    for f in sorted(glob.glob(os.path.join(d, "*.bin"))):
        idx = int(os.path.basename(f)[:4])
        if which and idx not in which:
            continue
        off, r = find(open(f, "rb").read())
        if not r:
            continue
        gs = [s["globalScale"][0] for s in r["stages"]]
        print("%4d @0x%X bones=%2d stages=%d scales=%s parts=%s markers=%d"
              % (idx, off, r["boneCount"], r["stageCount"], gs,
                 [k for k, v in r["hasPart"].items() if v], len(r["markers"])))
        if len(sys.argv) > 2:
            print(json.dumps(r["stages"][0], indent=1)[:1200])
