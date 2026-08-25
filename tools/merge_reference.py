"""Reference transcription of the Jade Cocoon merge.

Faithful port of the confirmed STAT formulas (FUN_800ba63c affinity blend and
FUN_800ba69c GR matrix, plus the stat up/down shift) and of the whole VISUAL
merge - the recipe, the geometry blend, the rest-pose blend, the body-part rule
and the palette rotation. Original code, derived from observed mechanics; the
tables it needs are read out of the player's own SLES_022.01 at run time and
none of them are embedded here.

Run:
    python merge_reference.py                  self-test
    python merge_reference.py species <exe>    species -> model -> file table
    python merge_reference.py merge  ...       build a merged GLB
"""

import glob
import math
import os
import struct
import subprocess

# Confirmed 4x4 element weight matrix (exe RAM 0x8007B998), applied >>5.
GR_MATRIX = [
    [32, 16, 32, 64],
    [64, 32, 16, 32],
    [32, 64, 32, 16],
    [16, 32, 64, 32],
]


def sra(x, n):
    """Arithmetic shift right on a 32-bit signed value (MIPS sra)."""
    x &= 0xFFFFFFFF
    if x & 0x80000000:
        x -= 0x100000000
    return x >> n


def affinity_blend(p1, p2, seed):
    """FUN_800ba63c: fixed-point weighted average of two 0..200 values."""
    p1 &= 0xFF
    p2 &= 0xFF
    d = p1 + p2 - 200
    K = seed | 0x2493
    # signed 32x32 -> high 32 bits
    prod = d * K  # python big int; take high word of the 64-bit signed result
    prod &= 0xFFFFFFFFFFFFFFFF
    if prod & 0x8000000000000000:
        prod -= 0x10000000000000000
    hi = prod >> 32
    res = (p1 + p2) // 2 + (sra(hi + d, 2) - sra(d, 31))
    if res < 0:
        res = 0
    elif res > 200:
        res = 200
    return res & 0xFF


def gr_transform(counts, other_counts=None):
    """FUN_800ba69c: element affinities from element counts via the fixed matrix.

    counts: list[4] of the base element counts (+0xC2).
    other_counts: optional material counts for the pre-average step.
    Returns list[4] affinities.
    """
    c = list(counts)
    if other_counts is not None:
        for i in range(4):
            if other_counts[i] > c[i]:
                c[i] = (c[i] + 2 * other_counts[i]) // 3
    out = []
    for j in range(4):
        s = sum(c[i] * GR_MATRIX[i][j] for i in range(4))
        out.append(sra(s, 5))
    return out


def stat_shift(base_stat, modifier, direction):
    """FUN_800ba538 (down) / FUN_800ba820 (up): stat +/- modifier/20."""
    delta = modifier // 20
    if direction < 0:
        return base_stat - delta
    v = base_stat + delta
    return min(v, 100)


def slot_inherit(base_slots, material_slots):
    """FUN_800bad08 core: the 0x30 ancestry slots = first 24 from base, rest material."""
    assert len(base_slots) == 0x30 and len(material_slots) == 0x30
    out = bytearray(0x30)
    for i in range(0x30):
        # in the asm: index i<0x20 and (i*2)<0x30 -> base, else material
        out[i] = base_slots[i] if (i < 0x20 and (i * 2) < 0x30) else material_slots[i]
    return bytes(out)


# =============================================================================
# The VISUAL merge.
#
# Everything below reimplements what the game does to a creature's GEOMETRY,
# SKELETON and PALETTE when two cocoons are merged. See MERGE_ALGORITHM.md for
# where each rule was read off.
# =============================================================================

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_RIG = 0x80079064       # the 25-bone table the whole morph family uses
EXE_LOAD = 0x80010000          # PS-X EXE t_addr; file offset = 0x800 + (addr - t_addr)
SPECIES_TABLE = 0x8007BC54     # SpeciesRec[365]      (FUN_80019C70)
SPECIES_SPAN = 365             # up to the growth-stage thresholds at 0x8007C208
ROSTER_SIZE = 211              # ids an ancestry slot may hold (FUN_80033938 histogram)
STAGE_THRESHOLDS = 0x8007C208  # u8[5] level thresholds (FUN_80019A80)
MODEL_DESCS = 0x800823F0       # u32 pointer per model, null terminated
NAME_PTRS = 0x8007A094         # char* per species id, 209 entries (0..208)
NAME_COUNT = 209
NAME_POOL = (0x80072234, 0x80072F60)   # the strings themselves

# The four elements sit 90 degrees apart on the palette wheel. The game reads
# them out of its 4096-entry sine table at 0x80084464 as entries 739, 1763, 2787
# and 3811; that table is exactly round(sin(i * 2pi / 4096) * 4096), verified
# entry by entry, so we compute the same numbers instead of shipping them.
ELEMENT_RSIN = (739, 1763, 2787, 3811)
NO_HUE = -1000                 # FUN_800BF4C0's "single element" sentinel

# Which SVECTORs inside a primitive the blend has to touch.
#
# This used to carry its own (first, count) table describing each chunk body as a
# contiguous run of 8-byte SVECTORs. That table was wrong, and wrong in a way that
# hid well: it satisfied `first + count*8 == body size`, so it looked self-consistent
# and every check written against it agreed with it. What it missed is that a chunk
# body starts 4 bytes into the chunk, and that the gouraud types stride 16 bytes per
# vertex (normal, position, UV, colour), not 8. Every vertex was therefore blended 4
# bytes early, across the boundary between two fields, which is why a merge came out
# as geometry belonging to neither parent.
#
# So the layout is no longer described twice. `export_mesh.GEOM` is what the exporter
# and Merge Studio decode with, and it is now what the blend writes through, which
# makes "the bytes the blend touches" and "the bytes the exporter reads" the same set
# by construction.
#
#   GEOM[t]    = (nVerts, firstBlockOff, blockStride, posOffsetInBlock), body = p + 4
#   NORMALS[t] = ("face", off) one normal for the whole primitive, or
#                ("vert", off) one per vertex, at that offset inside its block
NORMALS = {
    0: ("face", 0x04), 2: ("face", 0x04), 4: ("face", 0x04), 6: ("face", 0x04),
    1: ("vert", 0), 3: ("vert", 0), 5: ("vert", 0), 7: ("vert", 0),
}
GEOM_TYPES = frozenset(NORMALS)
# Seam-pool items (chunk types 8 and 9) are 0x14 bytes: normal at +0, position
# at +8, then UV and vertex colour, which the blend leaves alone.
SEAM_ITEM = 0x14
SEAM_SVECS = (0x00, 0x08)


# ----------------------------------------------------------------- exe tables

def exe_read(exe, addr, n):
    """n bytes at a RAM address inside the loaded executable image."""
    off = 0x800 + (addr - EXE_LOAD)
    return exe[off:off + n]


def species_records(exe):
    """The species table at 0x8007BC54: (modelId, hueBase, hueRef) per species.

    modelId indexes the model descriptor table; hueBase and hueRef are palette
    angles stored in units of two degrees.
    """
    out = []
    for i in range(SPECIES_SPAN):
        b = exe_read(exe, SPECIES_TABLE + i * 4, 4)
        out.append((struct.unpack_from("<H", b)[0], b[2], b[3]))
    return out


def model_files(exe):
    """Model id -> DATA.001 file index, walked to the descriptor table's null."""
    out, a = [], MODEL_DESCS
    while True:
        (p,) = struct.unpack("<I", exe_read(exe, a, 4))
        if p == 0:
            return out
        out.append(struct.unpack("<H", exe_read(exe, p, 2))[0])
        a += 4


def _fullwidth_to_ascii(t):
    """The game stores Latin text as Shift-JIS full-width forms; fold them back."""
    return "".join(chr(ord(c) - 0xFF00 + 0x20) if 0xFF01 <= ord(c) <= 0xFF5E
                   else (" " if c == "　" else c) for c in t)


def species_names(exe):
    """Species id -> the game's own English name.

    `0x8007A094` is a plain `char*` array, one entry per species id 0..208, into
    a string pool at `0x80072234`. The strings are Shift-JIS full-width Latin,
    which is why an ASCII search of the disc finds none of them.
    """
    out = []
    for k in range(NAME_COUNT):
        (ptr,) = struct.unpack("<I", exe_read(exe, NAME_PTRS + k * 4, 4))
        if not (NAME_POOL[0] <= ptr < NAME_POOL[1]):
            break
        raw = exe_read(exe, ptr, 64).split(b"\x00")[0]
        out.append(_fullwidth_to_ascii(raw.decode("shift_jis", "replace")))
    return out


def growth_stage(exe, level):
    """FUN_80019A80: level -> one of the five growth stages.

    Counts how many of the five level thresholds the minion has passed and
    returns that count minus one, so the first threshold is stage 0. A level
    below the first threshold returns -1 in the original too; levels start at 1,
    so it never comes up.
    """
    th = exe_read(exe, STAGE_THRESHOLDS, 5)
    stage = 0
    while stage < 5 and level >= th[stage]:
        stage += 1
    return stage - 1


# -------------------------------------------------- recipe from the ancestry

def recipe_from_ancestry(slots):
    """FUN_80033938: the 48-slot ancestry list -> up to three parents + weights.

    `slots` is the 0x30-byte array at minion+0x4C, one species id per slot. The
    three most common species become the blend sources; their multiplicities,
    normalised to 4096, become the weights. Ties go to the lower species id.
    Returns (nSources, species[3], weight[3]).
    """
    slots = list(slots)
    assert len(slots) == 0x30
    hist = [0] * ROSTER_SIZE
    for s in slots:
        hist[s] += 1

    sp = [ROSTER_SIZE] * 3
    wt = [0] * 3
    n = 0
    first = 0
    done = False
    for count in range(255, -1, -1):
        for sid in range(ROSTER_SIZE):
            if hist[sid] >= count:
                if count == 0:
                    sp[n] = sp[0]
                    if first == 0:
                        first = n
                else:
                    sp[n] = sid
                wt[n] = count
                hist[sid] = 0
                n += 1
            if n > 2:
                if first == 0:
                    first = 3
                done = True
                break
        if done:
            break

    total = wt[0] + wt[1] + wt[2]
    wt = [(w << 12) // total for w in wt]
    return first, sp, wt


# ------------------------------------------------------------ the palette hue

def rsin(i):
    """The game's 4096-entry sine table, reproduced exactly."""
    return int(round(math.sin(i * 2 * math.pi / 4096) * 4096))


def ratan2_deg(y, x):
    """FUN_8003B570: ratan2 rescaled to whole degrees, 0..359."""
    a = int(round(math.atan2(y, x) / (2 * math.pi) * 4096)) % 4096
    d = ((3 * a) * 0x78) >> 12
    return 0 if d > 0x167 else d


def elemental_hue(counts):
    """FUN_800BF4C0 / FUN_800BF590: the four element tallies -> a hue angle.

    Each element is a unit direction 90 degrees from its neighbours; the tallies
    are summed as a 2-D vector and the angle of that sum is the creature's hue.
    A creature of a single element has no meaningful direction, so the game
    returns NO_HUE and falls back to the species' own stored angle.
    """
    e = list(counts)
    assert len(e) == 4
    if sum(1 for v in e if v) == 1:
        return NO_HUE
    # The two two-element shortcuts the game takes. They agree with the general
    # formula and additionally cover the exactly-balanced case, where the vector
    # sum is zero and the angle would be undefined.
    if e[3] and e[1] and not (e[0] or e[2]):
        return 65 if e[1] >= e[3] else 245
    if e[0] and e[2] and not (e[1] or e[3]):
        return 155 if e[2] >= e[0] else 335
    c = [rsin(i) for i in ELEMENT_RSIN]
    x = sum(c[k] * e[k] for k in range(4))
    y = c[3] * e[0] + c[0] * e[1] + c[1] * e[2] + c[2] * e[3]
    return ratan2_deg(y, x)


def palette_hue(counts, rec):
    """The hue rotation handed to the texture loader, in degrees.

    `rec` is the species record of the minion's APPEARANCE id (+0x03), whose two
    bytes are its own stored angle and the reference angle of its texture.
    """
    _model, hue_base, hue_ref = rec
    h = elemental_hue(counts)
    if h == NO_HUE:
        return (hue_base * 2) % 360
    return (h - hue_ref * 2) % 360


# ---------------------------------------------------------- per-mesh weights

def mesh_object_weights(per_mesh, job_weights):
    """The three blend weights for one mesh object.

    `per_mesh` is each source's own weight for this mesh object, out of its
    growth stage's weight array; `job_weights` are the recipe's global weights.
    When all three sources agree - which is the case for every mesh object of
    every model but three - the global weights are used unchanged.

    Reproduces the original's renormalisation exactly, including the fact that
    each division's denominator already contains the results of the previous
    ones rather than the original values.
    """
    a, b, c = per_mesh
    if a == b == c:
        w = list(job_weights)
    else:
        t = a + b + c
        a2 = (a << 12) // t
        b2 = (b << 12) // (a2 + b + c)
        c2 = (c << 12) // (a2 + b2 + c)
        w = [a2 * job_weights[0], b2 * job_weights[1], c2 * job_weights[2]]
    out = list(w)
    for i in range(3):
        t = out[0] + out[1] + out[2]
        if t == 0:
            return [0, 0, 0]
        out[i] = (w[i] << 12) // t
        w[i] = out[i]
    return out


# ------------------------------------------------------------ the two blends

def _clamp16(v):
    return -0x8000 if v < -0x8000 else (0x7FFF if v > 0x7FFF else v)


def lerp_svec(dst, src, w):
    """The pair FUN_80039FE8 + FUN_8003A6C8, collapsed.

    The game computes `src - dst` into a scratch buffer and then
    `(0x1000*dst + w*delta) >> 12`. Folded together that is a plain fixed-point
    lerp of each of the three components; the fourth short of the slot carries
    UVs or padding and is never touched.
    """
    out = []
    for d, s in zip(dst, src):
        delta = _clamp16(s - d)
        out.append(_clamp16((0x1000 * d + w * delta) >> 12))
    return out


def _svec_offsets(t):
    """Byte offsets, relative to the chunk, of every SVECTOR in a primitive of
    type `t`: its normal(s) and its vertex positions."""
    import export_mesh
    nv, first, stride, posoff = export_mesh.GEOM[t]
    kind, noff = NORMALS[t]
    body = 4                                    # the chunk body starts at p + 4
    offs = []
    if kind == "face":
        offs.append(body + noff)                # one normal for the whole face
    for i in range(nv):
        blk = body + first + i * stride
        if kind == "vert":
            offs.append(blk + noff)
        offs.append(blk + posoff)
    return offs


def blend_prim(buf, dst_off, src, src_off, t, w):
    """Blend one primitive's normals and positions in place inside `buf`."""
    for off in _svec_offsets(t):
        d, s = dst_off + off, src_off + off
        a = struct.unpack_from("<3h", buf, d)
        b = struct.unpack_from("<3h", src, s)
        struct.pack_into("<3h", buf, d, *lerp_svec(a, b, w))


# --------------------------------------------------------- package assembly

def _load(split_dir, fidx):
    hits = glob.glob(os.path.join(split_dir, "%04d_*.bin" % fidx))
    if not hits:
        raise SystemExit("no split file for index %d in %s" % (fidx, split_dir))
    return open(hits[0], "rb").read()


def _mesh_sector(data):
    import export_every
    blocks = export_every.scan_meshes(data)
    if not blocks:
        raise SystemExit("no mesh block in package")
    return blocks[0][0]


def blend_mesh(out, srcs, mesh_secs, stage_weights, job_weights):
    """Blend every mesh object of `srcs[1..]` into `out` (which starts as srcs[0]).

    The three packages must carry the same chunk stream - same mesh objects, same
    primitive types in the same order - which is exactly what the 49-model morph
    family guarantees.
    """
    import mesh as meshmod
    mrs = [meshmod.parse_block(s, mesh_secs[i] * 2048) for i, s in enumerate(srcs)]
    n = len(mrs[0]["objs"])
    for i in range(3):
        if len(mrs[i]["objs"]) != n:
            raise SystemExit("source %d has %d mesh objects, not %d - not the same "
                             "topology, cannot blend" % (i, len(mrs[i]["objs"]), n))
    for mi in range(n):
        objs = [mrs[i]["objs"][mi] for i in range(3)]
        per = [sw[mi] if sw and mi < len(sw) else 0 for sw in stage_weights]
        w = mesh_object_weights(per, job_weights)
        chunks = [o["chunks"] for o in objs]
        if any(len(c) != len(chunks[0]) for c in chunks):
            raise SystemExit("mesh object %d: differing chunk counts" % mi)
        for src_i in (1, 2):
            if w[src_i] == 0:
                continue
            for ci, (t, p, _f) in enumerate(chunks[0]):
                t2, p2, _f2 = chunks[src_i][ci]
                if t2 != t:
                    raise SystemExit("mesh object %d chunk %d: type %d vs %d"
                                     % (mi, ci, t, t2))
                if t in GEOM_TYPES:
                    blend_prim(out, p, srcs[src_i], p2, t, w[src_i])
                elif t in (8, 9):
                    base = 4 if t == 8 else 8
                    cnt = struct.unpack_from("<I", out, p + 4)[0]
                    cnt2 = struct.unpack_from("<I", srcs[src_i], p2 + 4)[0]
                    for k in range(min(cnt, cnt2)):
                        d0 = p + 4 + base + k * SEAM_ITEM
                        s0 = p2 + 4 + base + k * SEAM_ITEM
                        for so in SEAM_SVECS:
                            a = struct.unpack_from("<3h", out, d0 + so)
                            b = struct.unpack_from("<3h", srcs[src_i], s0 + so)
                            struct.pack_into("<3h", out, d0 + so,
                                             *lerp_svec(a, b, w[src_i]))
    return out


def blend_rest_pose(out, srcs, anim_secs, weights, slots=()):
    """Blend the rest skeleton (the bone-length half of FUN_8004A520).

    The game builds a fresh single-frame pose for the merged creature; for an
    export we want the whole animation set to keep working, so every block in the
    result gets the same treatment - bone lengths become the weighted average of
    the three parents' first block, and rotations stay with the base's clips.
    """
    import anim as animmod
    firsts = []
    for i, s in enumerate(srcs):
        blks = animmod.parse_container(s, anim_secs[i] * 2048)
        firsts.append(blks[0] if blks else None)
    if any(b is None for b in firsts):
        return 0
    rests = [animmod.rest_offsets(srcs[i], firsts[i]) for i in range(3)]
    nb = min(len(r) for r in rests)
    blended = []
    for b in range(nb):
        blended.append([_clamp16(sum(rests[i][b][c] * weights[i]
                                     for i in range(3)) >> 12) for c in range(3)])
    frozen = bytes(out)
    blocks = list(animmod.parse_container(frozen, anim_secs[0] * 2048))
    for sec in slots:
        blk = animmod.parse_block(frozen, sec * 2048)
        if blk:
            blocks.append(blk)
    for blk in blocks:
        base = blk["off"] + 8 + (4 if blk.get("extra") else 0)
        for b in range(min(nb, blk["bones"])):
            struct.pack_into("<3h", out, base + b * 6, *blended[b])

    # The bind pose is the rest offsets AND the first block's frame-0 rotations -
    # export_gltf builds it from exactly those - so blending only the offsets
    # leaves the merged geometry hung on the base's default angles. Parents in
    # this family can hold the same bone 55 degrees apart, which peels the skin
    # off the skeleton. Blend the bind rotations to match. The clips still carry
    # the base's motion from frame 1 on, as the docstring above says.
    first = blocks[0] if blocks else None
    if first is not None:
        nbones = min(nb, first["bones"])
        rot0 = [[animmod.keyframe(srcs[i], firsts[i], 0, b)
                 if b < firsts[i]["bones"] else (0, 0, 0) for b in range(nbones)]
                for i in range(3)]
        frame0 = first["off"] + first["hdr"]
        # Bone 1 does not use its rest offset: the renderer drives it from the
        # frame's second leading entry. Leaving that at the base's value shifts
        # everything below bone 1 as one block, so blend it like any other offset.
        roots = [animmod.root_translation(srcs[i], firsts[i], 0) for i in range(3)]
        struct.pack_into("<3h", out, frame0 + 6,
                         *[_clamp16(sum(roots[i][c] * weights[i]
                                        for i in range(3)) >> 12) for c in range(3)])
        rbase = frame0 + 2 * 6
        for b in range(nbones):
            triple = []
            for c in range(3):
                a = rot0[0][b][c]
                acc = 0
                for i in range(3):
                    # Shortest way round: 4096 units is a full turn, so a plain
                    # average of 10 and 4090 would swing the bone the long way.
                    d = ((rot0[i][b][c] - a + 0x800) & 0xFFF) - 0x800
                    acc += d * weights[i]
                triple.append(_clamp16(a + (acc >> 12)))
            struct.pack_into("<3h", out, rbase + b * 6, *triple)
    return len(blocks)


def _part_flag_offsets(buf, container_off):
    """Absolute offset of each growth stage's partFlagsA triple.

    The blob proper starts one u32 (its size) past the container; every offset
    inside it is blob-relative, and a Stage's five sub-offsets are relative to
    the Stage record rather than to the blob.
    """
    blob = container_off + 4
    off_stages = struct.unpack_from("<I", buf, blob + 8)[0]
    if not off_stages:
        return []
    count, _bones = struct.unpack_from("<2I", buf, blob + off_stages)
    p = off_stages + 8
    out = []
    for _ in range(count):
        o_fa = struct.unpack_from("<I", buf, blob + p + 8)[0]
        out.append(blob + p + o_fa)
        p += struct.unpack_from("<I", buf, blob + p + 0x14)[0]
    return out


def or_part_flags(out, srcs):
    """A wingless minion merged with a winged one gains wings.

    The rule is `if (other.A[k] > 1 and mine.A[k] == 1) mine.A[k] = 2`, applied
    once per other parent, over the three body-part groups of every growth stage.
    """
    import appearance as appmod
    offs = [appmod.find(s)[0] for s in srcs]
    if any(o is None for o in offs):
        return 0
    others = [appmod.parse(s, o) for s, o in zip(srcs[1:], offs[1:])]
    changed = 0
    for si, fa in enumerate(_part_flag_offsets(out, offs[0])):
        mine = list(struct.unpack_from("<3h", out, fa))
        for other in others:
            if si >= len(other["stages"]):
                continue
            oa = other["stages"][si]["partFlagsA"]
            for k in range(3):
                if oa[k] > 1 and mine[k] == 1:
                    mine[k] = 2
                    changed += 1
        struct.pack_into("<3h", out, fa, *mine)
    return changed


# ------------------------------------------------------------ palette rotation

def rgb_to_hsv(r, g, b):
    """FUN_80029F10, on 5-bit components. Hue is 0..191; None when achromatic."""
    mx, which = b, 0
    if b < r:
        mx, which = r, 1
    if mx < g:
        mx, which = g, 2
    mn = min(r, g, b)
    v = mx
    s = 0 if mx == 0 else ((mx - mn) * 31) // mx
    if s == 0:
        return None
    d = mx - mn
    if which == 1:
        h = (((mx - b) - (mx - g)) * 32) // d
    elif which == 2:
        h = (((mx - r) - (mx - b)) * 32) // d + 0x40
    else:
        h = (((mx - g) - (mx - r)) * 32) // d + 0x80
    if h < 0:
        h += 0xC0
    return h, s, v


def hsv_to_rgb(h, s, v):
    """FUN_8002A0A8: six 32-wide sectors over the 192-step hue circle."""
    hh = h + 31 if h < 0 else h
    sector = (hh >> 5) % 6
    f = h - (hh >> 5) * 32
    p = (v * (0x3E0 - s * 32) + 0x1F0) // 0x3E0
    q = (v * (0x3E0 - s * f) + 0x1F0) // 0x3E0
    t = (v * (0x3E0 - s * (32 - f)) + 0x1F0) // 0x3E0
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][sector]


def rotate_clut(buf, off, count, degrees):
    """FUN_80029D68: rotate `count` BGR555 entries by `degrees` around the wheel.

    Greys have no hue and are left exactly as they are, which is why a merged
    creature's whites, blacks and metal stay put while its colours shift.
    """
    delta = (degrees * 24) // 45          # degrees -> the 192-step hue circle
    for i in range(count):
        (w,) = struct.unpack_from("<H", buf, off + i * 2)
        hsv = rgb_to_hsv(w & 0x1F, (w >> 5) & 0x1F, (w >> 10) & 0x1F)
        if hsv is None:
            continue
        h, s, v = hsv
        r2, g2, b2 = hsv_to_rgb((h + delta) % 0xC0, s, v)
        struct.pack_into("<H", buf, off + i * 2,
                         (w & 0x8000) | (b2 << 10) | (g2 << 5) | r2)


def hue_rotate_textures(buf, tex_sector, degrees):
    """Rotate every palette in a package's texture container."""
    import tim
    n = 0
    base = tex_sector * 2048
    (cnt,) = struct.unpack_from("<I", buf, base)
    frozen = bytes(buf)
    for rel in struct.unpack_from("<%dI" % cnt, buf, base + 4):
        t = tim.parse(frozen, base + rel)
        if not t or not t["clut"]:
            continue
        rotate_clut(buf, base + rel + 8 + 12, t["clut_dim"][2], degrees)
        n += 1
    return n


# --------------------------------------------------------------- the driver

def build_merged_package(exe, split_dir, sources, weights, stage,
                         texture_from=None, hue=0, blend_pose=True, slots=()):
    """Produce the bytes of a package holding the merged creature.

    `sources` is one to three DATA.001 file indices; source 0 is the base whose
    body, seams, appearance blob and animation set the result inherits. Returns
    (packageBytes, meshSector, animSector, texSector, notes).
    """
    import appearance as appmod
    import model_index
    sources = list(sources)
    weights = list(weights)
    srcs = [_load(split_dir, f) for f in sources]
    while len(srcs) < 3:
        srcs.append(srcs[0])
        sources.append(sources[0])
        weights.append(0)
    sec = model_index.sections(exe)
    mesh_secs = [_mesh_sector(s) for s in srcs]
    anim_secs = [sec[f]["ranges"][3][0] for f in sources]
    tex_sec = sec[sources[0]]["ranges"][1][0]

    out = bytearray(srcs[0])
    notes = []

    stage_w = []
    for s in srcs:
        _o, app = appmod.find(s)
        st = app["stages"][stage] if app and stage < len(app["stages"]) else None
        stage_w.append(st["meshWeights"] if st else None)

    blend_mesh(out, srcs, mesh_secs, stage_w, weights)
    notes.append("mesh blended from files %s at weights %s" % (sources, weights))

    if blend_pose:
        n = blend_rest_pose(out, srcs, anim_secs, weights, slots)
        notes.append("rest pose blended into %d animation blocks" % n)

    n = or_part_flags(out, srcs)
    if n:
        notes.append("%d body-part flags gained from the other parents" % n)

    if texture_from is not None and texture_from != sources[0]:
        donor = _load(split_dir, texture_from)
        d_start, d_len = sec[texture_from]["ranges"][1]
        b_start, b_len = sec[sources[0]]["ranges"][1]
        if d_len != b_len:
            notes.append("texture donor %d has %d sectors, base has %d - kept the "
                         "base's textures" % (texture_from, d_len, b_len))
        else:
            out[b_start * 2048:(b_start + b_len) * 2048] = \
                donor[d_start * 2048:(d_start + d_len) * 2048]
            notes.append("textures taken from model file %d" % texture_from)

    if hue:
        n = hue_rotate_textures(out, tex_sec, hue)
        notes.append("%d palettes rotated by %d degrees" % (n, hue))

    return bytes(out), mesh_secs[0], anim_secs[0], tex_sec, notes


def export_glb(exe_path, pkg_bytes, mesh_sec, anim_sec, tex_sec, out_glb,
               rig=None, slots=(), name="merged_"):
    """Hand the merged package to the normal exporter."""
    import sys
    if rig is None:
        rig = "0x%08X" % DEFAULT_RIG
    tmp = out_glb + ".pkg"
    with open(tmp, "wb") as fh:
        fh.write(pkg_bytes)
    cmd = [sys.executable, os.path.join(HERE, "export_gltf.py"),
           exe_path, tmp, str(mesh_sec), str(anim_sec), rig, out_glb, "--name", name,
           # Name the root node after the blend so a Blender scene holding several
           # merges does not show a row of identical objects.
           "--root", os.path.splitext(os.path.basename(out_glb))[0]]
    if tex_sec is not None:
        cmd += ["--tex", str(tex_sec)]
    if slots:
        cmd += ["--animslots", ",".join(str(s) for s in slots)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    os.remove(tmp)
    if r.returncode != 0:
        raise SystemExit("export_gltf failed:\n" + r.stdout + r.stderr)
    return r.stdout.strip()


def species_kind(i):
    if i < 36:
        return "base"
    if i < 57:
        return "special"
    if i < 201:
        return "variant of base %d, element %d" % ((i - 57) // 4, (i - 57) % 4)
    if i < 211:
        return "unique"
    return "second table"


def cmd_species(argv):
    """Print the species table: species id -> model id -> DATA.001 file."""
    exe = open(argv[0], "rb").read()
    recs = species_records(exe)
    files = model_files(exe)
    names = species_names(exe)
    lines = ["# species  model  file  hueBase  hueRef  name            kind"]
    for i, (m, hb, hr) in enumerate(recs):
        f = files[m] if m < len(files) else -1
        nm = names[i] if i < len(names) else ""
        lines.append("%9d %6d %5d %8d %7d  %-15s %s" % (i, m, f, hb * 2, hr * 2, nm,
                                                        species_kind(i)))
    text = "\n".join(lines)
    if len(argv) > 1:
        open(argv[1], "w").write(text + "\n")
        print("wrote %s (%d species)" % (argv[1], len(recs)))
    else:
        print(text)


def streamed_slots(index_path, fidx, min_bones=0):
    """The streamed clip sectors of one model, out of the cached archive index."""
    import json
    if not index_path or not os.path.exists(index_path):
        return []
    idx = json.load(open(index_path))
    return [b["sector"] for b in idx.get("streamed", {}).get(str(fidx), [])
            if b["bones"] >= min_bones]


def cmd_merge(argv):
    exe_path, split_dir, out_glb = argv[0], argv[1], argv[2]
    rest = argv[3:]

    def opt(flag, default=None):
        return rest[rest.index(flag) + 1] if flag in rest else default

    sources = [int(x) for x in opt("--sources").split(",")]
    ws = opt("--weights")
    if ws:
        weights = [int(x) for x in ws.split(",")]
    else:
        w = 4096 // len(sources)
        weights = [4096 - w * (len(sources) - 1)] + [w] * (len(sources) - 1)
    tex = opt("--texture-from")
    index = opt("--index", os.path.join(os.path.dirname(split_dir.rstrip("/\\")),
                                        "rig_anim_index.json"))
    slots = ([int(x) for x in opt("--animslots").split(",")] if opt("--animslots")
             else streamed_slots(index, sources[0], 25))
    pkg, ms, asec, ts, notes = build_merged_package(
        open(exe_path, "rb").read(), split_dir, sources, weights,
        int(opt("--stage", "4")), int(tex) if tex else None,
        int(opt("--hue", "0")), "--no-pose" not in rest, slots)
    for n in notes:
        print("  " + n)
    print(export_glb(exe_path, pkg, ms, asec, ts, out_glb, slots=slots))
    print("wrote " + out_glb)


def _selftest():
    print("affinity_blend(150, 100, seed=0):", affinity_blend(150, 100, 0))
    print("gr_transform([10,0,0,0]):", gr_transform([10, 0, 0, 0]))
    print("stat_shift(80, mod=40, up):", stat_shift(80, 40, +1))
    anc = [12] * 30 + [7] * 12 + [3] * 6
    print("recipe_from_ancestry(30x12, 12x7, 6x3):", recipe_from_ancestry(anc))
    print("recipe_from_ancestry(all one species):", recipe_from_ancestry([9] * 48))
    print("elemental_hue([1,0,0,0]) single element:", elemental_hue([1, 0, 0, 0]))
    print("elemental_hue([3,1,0,0]):", elemental_hue([3, 1, 0, 0]))
    print("elemental_hue([0,1,0,2]):", elemental_hue([0, 1, 0, 2]))
    print("mesh_object_weights all-equal:",
          mesh_object_weights([0, 0, 0], [2048, 1024, 1024]))
    print("mesh_object_weights one override:",
          mesh_object_weights([0, 0, 2], [2048, 1024, 1024]))
    print("lerp_svec((0,0,0),(100,200,300),2048):",
          lerp_svec((0, 0, 0), (100, 200, 300), 2048))
    print("(pass an exe path to see species names)")
    print("rotate a mid red by 120 deg:",
          hsv_to_rgb((rgb_to_hsv(31, 4, 4)[0] + (120 * 24) // 45) % 0xC0,
                     *rgb_to_hsv(31, 4, 4)[1:]))


USAGE = """usage:
  merge_reference.py                       run the self-test
  merge_reference.py species <exe> [out]   dump the species -> model -> file table
  merge_reference.py merge <exe> <splitDir> <out.glb>
        --sources F0[,F1[,F2]]     DATA.001 file indices; F0 is the base body
        [--weights W0,W1,W2]       1.12 fixed, meant to sum to 4096
        [--stage N]                growth stage 0..4 (default 4, the adult)
        [--texture-from F]         take the palette + pixels from this model file
        [--hue DEG]                rotate every palette by DEG degrees
        [--no-pose]                leave the base's rest skeleton alone
        [--index P]                rig_anim_index.json, for the streamed clips
        [--animslots S,S,...]      streamed clip sectors, overriding the index
"""

if __name__ == "__main__":
    import sys
    if len(sys.argv) == 1:
        _selftest()
    elif sys.argv[1] == "species":
        cmd_species(sys.argv[2:])
    elif sys.argv[1] == "merge":
        cmd_merge(sys.argv[2:])
    else:
        print(USAGE)
