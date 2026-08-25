"""Derive a bone table from the mesh's own stitch records.

Five models own animations at a bone count for which no table exists anywhere on the disc
(checked over the raw 211 MB archive, gaps included). Handing them a shorter foreign rig
places the first N bones plausibly and strands everything past N, which is the
"partially in the right place, the rest is a mess" a Blender review reported.

Two facts turn the table into a search rather than a guess:

* **meshIdx == self in every one of the 244 tables on the disc**, so a bone draws the mesh
  object with its own index. Nothing to search there.
* **Parent is implied by depth**: bone k's parent is the most recent PRECEDING bone at
  depth-1. So the whole table is one integer per bone, and choosing bone k's depth only
  ever picks a parent off the rightmost path built so far.

The objective is the stitch records. Each quad has four corners that live in different
bones' spaces and must meet; a quad becomes evaluable as soon as every bone it names has
been placed. That makes the search a left-to-right beam over depths, scoring each quad the
moment its last bone lands.

Usage:
    python derive_rig.py <exe> <split_dir> --validate [--beam N]
    python derive_rig.py <exe> <split_dir> 870 879 [--beam N]
"""
import glob
import json
import math
import os
import statistics
import sys

import anim as animmod
import assemble_model as AM
import export_every as EE
import export_mesh
import mesh as meshmod
import rigfit

BEAM = 400
MAX_DEPTH = 9


def quads_by_last_bone(quads, nbones):
    """quad lists keyed by the highest bone index they name."""
    out = {k: [] for k in range(nbones)}
    for quad in quads:
        hi = max(b for b, _v in quad)
        if hi < nbones:
            out[hi].append(quad)
    return out


def derive(lut, data, mesh_sec, mr, adata, blk, nbones, beam=BEAM):
    """Beam-search a depth array. Returns [(medianExtent, depths, parents)]."""
    rest = animmod.rest_offsets(adata, blk)
    pools = [[it["pos"] for it in export_mesh.seam_pool_full(data, mr["objs"][i])]
             for i in range(nbones)]
    todo = quads_by_last_bone(export_mesh.read_stitches(data, mesh_sec * 2048), nbones)

    def place(parent_world, slf):
        rx, ry, rz = animmod.keyframe(adata, blk, 0, slf)
        if slf == 0:
            rx = ry = rz = 0
        r3 = tuple(v / 4096.0 for v in AM.rot_matrix(lut, rx, ry, rz))
        t = animmod.root_translation(adata, blk, 0) if slf == 1 else rest[slf]
        if parent_world is None:
            return (r3, (float(t[0]), float(t[1]), float(t[2])))
        pr, pt = parent_world
        tw = tuple(pt[i] + pr[i * 3] * t[0] + pr[i * 3 + 1] * t[1] + pr[i * 3 + 2] * t[2]
                   for i in range(3))
        rw = tuple(sum(pr[r * 3 + k] * r3[k * 3 + c] for k in range(3))
                   for r in range(3) for c in range(3))
        return (rw, tw)

    # state: (cost, depths, parents, stack, world)
    states = [(0.0, (0,), {0: 0}, {0: 0}, {0: place(None, 0)})]
    for k in range(1, nbones):
        nxt = []
        for cost, depths, parents, stack, world in states:
            for d in range(1, min(MAX_DEPTH, max(stack) + 2)):
                if d - 1 not in stack:
                    continue
                par = stack[d - 1]
                w = dict(world)
                w[k] = place(world[par], k)
                add = 0.0
                for quad in todo[k]:
                    pts = []
                    for bi, vi in quad:
                        if bi >= len(pools) or vi >= len(pools[bi]) or bi not in w:
                            pts = None
                            break
                        pts.append(rigfit._apply(w[bi], pools[bi][vi]))
                    if not pts:
                        continue
                    add += max(math.dist(pts[i], pts[j])
                               for i in range(4) for j in range(i + 1, 4))
                st = dict(stack)
                st[d] = k
                for dd in list(st):
                    if dd > d:
                        del st[dd]
                pa = dict(parents)
                pa[k] = par
                nxt.append((cost + add, depths + (d,), pa, st, w))
        nxt.sort(key=lambda s: s[0])
        states = nxt[:beam]
    out = []
    for cost, depths, parents, _st, _w in states[:8]:
        tbl = [(depths[i], i, 0, i) for i in range(nbones)]
        s = rigfit.score(lut, data, mesh_sec, mr, tbl, parents, adata, blk)
        out.append((s, depths, parents))
    out.sort(key=lambda r: (r[0] is None, r[0]))
    return out


def own_clip(index, fidx, data, nbones):
    blks = [b for b in index["streamed"].get(str(fidx), []) if b["bones"] >= nbones]
    if not blks:
        return None
    return animmod.parse_block(data, max(blks, key=lambda b: b["frames"])["sector"] * 2048)


def run(exe, lut, split_dir, index, fidx, nbones, truth=None, beam=BEAM):
    data = open(glob.glob(os.path.join(split_dir, "%04d_*.bin" % fidx))[0], "rb").read()
    mesh_sec, nobj, _ = EE.scan_meshes(data)[0]
    mr = meshmod.parse_block(data, mesh_sec * 2048)
    blk = own_clip(index, fidx, data, nbones)
    if blk is None:
        print("%d: no own clip with >= %d bones" % (fidx, nbones))
        return
    res = derive(lut, data, mesh_sec, mr, data, blk, nbones, beam)
    best = res[0]
    print("== %d: %d objects, deriving %d bones from %d-bone clip"
          % (fidx, nobj, nbones, blk["bones"]))
    print("   best fit %s  depths %s"
          % (round(best[0], 1) if best[0] else None, list(best[1])))
    if truth is not None:
        same = sum(1 for a, b in zip(best[2].values(), truth.values()) if a == b)
        print("   parents matching the real table: %d/%d" % (same, len(truth)))
    return best


def main():
    exe_path, split_dir = sys.argv[1], sys.argv[2]
    exe = open(exe_path, "rb").read()
    lut = AM.load_lut(exe)
    root = os.path.dirname(split_dir)
    index = json.load(open(os.path.join(root, "rig_anim_index.json")))
    report = json.load(open(os.path.join(root, "Models", "current", "export_report.json")))
    beam = int(sys.argv[sys.argv.index("--beam") + 1]) if "--beam" in sys.argv else BEAM
    if "--validate" in sys.argv:
        print("=== validation: derive a rig we already have ===")
        for fidx in (833, 867, 831, 840):
            spec = report["%04d" % fidx]["rig"]
            tbl = AM.load_bones_spec(exe, spec)
            run(exe, lut, split_dir, index, fidx, len(tbl),
                truth=AM.parents_from_depth(tbl), beam=beam)
        return
    args = sys.argv[3:]
    skip = set()
    for i, a in enumerate(args):
        if a == "--beam":
            skip.add(i)
            skip.add(i + 1)
    for i, arg in enumerate(args):
        if i in skip or arg.startswith("--"):
            continue
        fidx = int(arg)
        data = open(glob.glob(os.path.join(split_dir, "%04d_*.bin" % fidx))[0], "rb").read()
        nobj = EE.scan_meshes(data)[0][1]
        blks = index["streamed"].get(str(fidx), [])
        nb = min(nobj, max((b["bones"] for b in blks), default=nobj))
        run(exe, lut, split_dir, index, fidx, nb, beam=beam)


if __name__ == "__main__":
    main()
