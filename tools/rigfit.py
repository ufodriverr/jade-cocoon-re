"""Score how well a (rig, rest pose) pair actually fits a mesh block.

A model file names neither its rig nor its animation set, so the exporter has to guess.
Matching on bone count alone is not enough: model 831 has 23 mesh objects, so it drew a
23-bone rig and a 23-bone animation from an unrelated creature and came out mangled.

The stitch records give an objective test. Each is a quad whose four corners live in four
different bones' local spaces, and the whole point of them is to close a seam - so under
the CORRECT rig and rest pose the four corners land within a few tens of units of each
other. Under a foreign skeleton the parts fly apart and the quads stretch across the whole
model. Scoring candidates by median stitch-quad size therefore picks the right rig, and a
bad best score is a reliable signal that the model's real skeleton is not in the archive.

Score is in game units; MODEL_FORMAT records a median max-edge of 53 for a correct
assembly of model 833.
"""
import math
import struct

import anim as animmod
import assemble_model as AM
import export_mesh


def bone_world(lut, bones, parent_of, adata, blk):
    """Per-bone rest world transform (3x3 row-major ints/4096, translation) in game units."""
    rest = animmod.rest_offsets(adata, blk)
    world = {}
    for _d, slf, _b3, _m in bones:          # depth-first order: parents come first
        rx, ry, rz = animmod.keyframe(adata, blk, 0, slf)
        if slf == 0:
            rx = ry = rz = 0
        r3 = tuple(v / 4096.0 for v in AM.rot_matrix(lut, rx, ry, rz))
        if slf == 1:
            t = animmod.root_translation(adata, blk, 0)
        else:
            t = rest[slf] if slf < len(rest) else (0, 0, 0)
        par = parent_of[slf]
        if par == slf:
            world[slf] = (r3, (float(t[0]), float(t[1]), float(t[2])))
        else:
            pr, pt = world[par]
            tw = tuple(pt[i] + pr[i * 3] * t[0] + pr[i * 3 + 1] * t[1] + pr[i * 3 + 2] * t[2]
                       for i in range(3))
            rw = tuple(sum(pr[r * 3 + k] * r3[k * 3 + c] for k in range(3))
                       for r in range(3) for c in range(3))
            world[slf] = (rw, tw)
    return world


def _apply(rt, v):
    r, t = rt
    return tuple(t[i] + r[i * 3] * v[0] + r[i * 3 + 1] * v[1] + r[i * 3 + 2] * v[2]
                 for i in range(3))


def score(lut, data, mesh_sec, mr, bones, parent_of, adata, blk, min_coverage=0.8):
    """Median stitch-quad extent under this rig + rest pose. Lower is better.

    Returns None when the pairing cannot be evaluated, or when the rig resolves fewer
    than `min_coverage` of the stitch quads. That second check matters: a 15-bone rig
    passes a naive "every meshIndex is in range" test against a 25-mesh model, then wins
    on score purely because it only ever gets judged on the handful of seams it can
    reach.
    """
    nmesh = len(mr["objs"])
    if any(not (0 <= m < nmesh) for _d, _s, _b3, m in bones):
        return None
    if blk["bones"] < max(s for _d, s, _b3, _m in bones) + 1:
        return None
    world = bone_world(lut, bones, parent_of, adata, blk)
    pools = {}
    for _d, slf, _b3, midx in bones:
        pools[slf] = [it["pos"] for it in export_mesh.seam_pool_full(data, mr["objs"][midx])]
    sizes = []
    quads = export_mesh.read_stitches(data, mesh_sec * 2048)
    for quad in quads:
        pts = []
        for bi, vi in quad:
            pool = pools.get(bi)
            if pool is None or vi >= len(pool) or bi not in world:
                pts = None
                break
            pts.append(_apply(world[bi], pool[vi]))
        if not pts:
            continue
        worst = 0.0
        for i in range(4):
            for j in range(i + 1, 4):
                d = math.dist(pts[i], pts[j])
                if d > worst:
                    worst = d
        sizes.append(worst)
    if not sizes or not quads:
        return None
    if len(sizes) < min_coverage * len(quads):
        return None
    sizes.sort()
    return sizes[len(sizes) // 2]


def read_rig(buf, off):
    """Bone table at `off` -> [(depth, self, unk, meshIndex), ...]."""
    out = []
    p = off
    while True:
        depth, slf, b3, midx, _f = struct.unpack_from("<hBBhh", buf, p)
        if depth == -1:
            break
        out.append((depth, slf, b3, midx))
        p += 8
        if len(out) > 300:
            break
    return out
