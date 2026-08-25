"""Assemble a fully posed Jade Cocoon model: skeleton + per-bone meshes -> OBJ.

Pieces (all recovered from the binary):
  * bone table   (exe)  : 8-byte records {s16 depth, u8 self, u8 parent, s16 meshIdx, s16}
                          terminated by -1; found with find_bonelist.py
  * rest offsets (anim) : s16[3] per bone in the animation block header
  * rotations    (anim) : s16[3] per bone per frame, 4096 units per full turn
  * meshes       (mesh) : one mesh object per bone, in bone-local space
  * sine LUT     (exe)  : 4096 entries at 0x80084464; sin(a)=lut[a&0xFFF],
                          cos(a)=lut[(a+0x400)&0xFFF]

Rotation matrix composition transcribed from FUN_80047e4c.

Usage:
  python assemble_model.py <exe> <package> <meshSector> <animSector> <boneTableAddr>
                           <out.obj> [--anim N] [--frame N]
"""
import struct
import sys

import anim as animmod
import export_mesh
import mesh as meshmod

LUT_ADDR = 0x80084464


def exe_off(a):
    return a - 0x80010000 + 0x800


def load_lut(exe):
    return struct.unpack_from("<4096h", exe, exe_off(LUT_ADDR))


def parents_from_depth(bones):
    """Resolve the bone hierarchy.

    The parent is IMPLIED BY DEPTH: a bone's parent is the most recent preceding
    bone at depth-1 (classic depth-first skeleton encoding). The byte at record+3
    is NOT the parent - it agrees for most bones but diverges (e.g. bone16 of the
    25-bone rig lists 0 while its real parent is bone 1), which strands whole
    limb chains at the origin.
    """
    stack, parent = {}, {}
    for depth, slf, _b3, _m in bones:
        parent[slf] = stack.get(depth - 1, slf) if depth > 0 else slf
        stack[depth] = slf
    return parent


def load_bones_raw(buf, off):
    """Walk a bone table at a raw byte offset in any buffer."""
    out = []
    while True:
        depth, slf, par, midx, _x = struct.unpack_from("<hBBhh", buf, off)
        if depth == -1:
            break
        out.append((depth, slf, par, midx))
        off += 8
        if len(out) > 300:
            break
    return out


def load_bones_spec(exe, spec):
    """Resolve a rig from either the exe ('0x800...') or a package ('PATH@0xOFF').

    Most rigs live in the exe, but the larger creatures keep theirs in the actor
    overlay packages (e.g. the 37-bone rig for model 838 is in file 0467).
    """
    if "@" in spec:
        path, off = spec.rsplit("@", 1)
        return load_bones_raw(open(path, "rb").read(), int(off, 16))
    return load_bones(exe, int(spec, 16))


def load_bones(exe, addr):
    """Return list of (depth, self, byte3, meshIdx)."""
    off = exe_off(addr)
    out = []
    while True:
        depth, slf, par, midx, _x = struct.unpack_from("<hBBhh", exe, off)
        if depth == -1:
            break
        out.append((depth, slf, par, midx))
        off += 8
        if len(out) > 300:
            break
    return out


def rot_matrix(lut, a0, a1, a2):
    """Matrix from three 4096-unit Euler angles (transcribed from FUN_80047e4c)."""
    def s(a):
        return lut[a & 0xFFF]

    def c(a):
        return lut[(a + 0x400) & 0xFFF]

    s0, c0 = s(a0), c(a0)
    s1, c1 = s(a1), c(a1)
    s2, c2 = s(a2), c(a2)
    m00 = (c2 * c1) >> 12
    m01 = (((c2 * s1) >> 12) * s0 >> 12) - ((s2 * c0) >> 12)
    m02 = ((s2 * s0) >> 12) + (((c2 * s1) >> 12) * c0 >> 12)
    m10 = (s2 * c1) >> 12
    m11 = ((c2 * c0) >> 12) + (((s2 * s1) >> 12) * s0 >> 12)
    m12 = (((s2 * s1) >> 12) * c0 >> 12) - ((c2 * s0) >> 12)
    m20 = -s1
    m21 = (c1 * s0) >> 12
    m22 = (c1 * c0) >> 12
    return (m00, m01, m02, m10, m11, m12, m20, m21, m22)


def mat_mul(a, b):
    out = [0] * 9
    for r in range(3):
        for col in range(3):
            out[r * 3 + col] = sum(a[r * 3 + k] * b[k * 3 + col] for k in range(3)) >> 12
    return tuple(out)


def mat_apply(m, v):
    x, y, z = v
    return ((m[0] * x + m[1] * y + m[2] * z) >> 12,
            (m[3] * x + m[4] * y + m[5] * z) >> 12,
            (m[6] * x + m[7] * y + m[8] * z) >> 12)


def main():
    exe_path, pkg_path = sys.argv[1], sys.argv[2]
    mesh_sec, anim_sec = int(sys.argv[3]), int(sys.argv[4])
    bone_spec = sys.argv[5]
    out_path = sys.argv[6]
    which_anim = int(sys.argv[sys.argv.index("--anim") + 1]) if "--anim" in sys.argv else 0
    frame = int(sys.argv[sys.argv.index("--frame") + 1]) if "--frame" in sys.argv else 0

    exe = open(exe_path, "rb").read()
    data = open(pkg_path, "rb").read()
    lut = load_lut(exe)
    bones = load_bones_spec(exe, bone_spec)

    mr = meshmod.parse_block(data, mesh_sec * 2048)
    blocks = animmod.parse_container(data, anim_sec * 2048)
    blk = blocks[min(which_anim, len(blocks) - 1)]
    rest = animmod.rest_offsets(data, blk)
    frame = min(frame, blk["frames"] - 1)

    print(f"bones={len(bones)} meshes={len(mr['objs'])} "
          f"anim{which_anim}: {blk['frames']} frames x {blk['bones']} bones, using frame {frame}")

    # world transform per bone
    parent_of = parents_from_depth(bones)
    world_r = {}
    world_t = {}
    for depth, slf, _b3, midx in bones:
        if slf >= len(rest):
            continue
        rx, ry, rz = animmod.keyframe(data, blk, frame, slf)
        if slf == 0:
            rx = ry = rz = 0   # renderer forces slot 0 to zero rotation
        local_r = rot_matrix(lut, rx, ry, rz)
        off = rest[slf]
        if slf == 1:
            off = animmod.root_translation(data, blk, frame)  # animated body root
        par = parent_of[slf]
        if par == slf:
            world_r[slf] = local_r
            world_t[slf] = off
        else:
            pr = world_r.get(par, (4096, 0, 0, 0, 4096, 0, 0, 0, 4096))
            pt = world_t.get(par, (0, 0, 0))
            world_r[slf] = mat_mul(pr, local_r)
            rot_off = mat_apply(pr, off)
            world_t[slf] = (pt[0] + rot_off[0], pt[1] + rot_off[1], pt[2] + rot_off[2])

    lines = ["# Jade Cocoon assembled model", f"# {pkg_path} mesh@{mesh_sec} anim@{anim_sec}"]
    vbase = 1
    nv = nt = 0
    for depth, slf, _b3, midx in bones:
        par = parent_of[slf]
        if not (0 <= midx < len(mr["objs"])):
            continue
        obj = mr["objs"][midx]
        prims = list(export_mesh.read_prims(data, obj))
        if not prims:
            continue
        R = world_r.get(slf, (4096, 0, 0, 0, 4096, 0, 0, 0, 4096))
        T = world_t.get(slf, (0, 0, 0))
        lines.append(f"o bone{slf:02d}_mesh{midx:02d}")
        local, faces = [], []
        for _t, verts in prims:
            idx = [len(local) + vbase + k for k in range(len(verts))]
            for v in verts:
                w = mat_apply(R, v)
                local.append((w[0] + T[0], w[1] + T[1], w[2] + T[2]))
            if len(verts) == 3:
                faces.append((idx[0], idx[1], idx[2]))
            else:
                faces.append((idx[0], idx[1], idx[2]))
                faces.append((idx[1], idx[3], idx[2]))
        for x, y, z in local:
            lines.append(f"v {x} {-y} {z}")
        for a, b, c in faces:
            lines.append(f"f {a} {b} {c}")
        vbase += len(local)
        nv += len(local)
        nt += len(faces)

    # stitch quads: seam polygons whose four corners belong to different bones
    pools = {}
    for _d, slf, _b3, midx in bones:
        if 0 <= midx < len(mr["objs"]):
            pools[slf] = export_mesh.seam_pool(data, mr["objs"][midx])
    local, faces = [], []
    for quad in export_mesh.read_stitches(data, mesh_sec * 2048):
        corner = []
        for bi, vi in quad:
            pool = pools.get(bi)
            if pool is None or vi >= len(pool):
                corner = None
                break
            w = mat_apply(world_r[bi], pool[vi])
            t = world_t[bi]
            corner.append((w[0] + t[0], w[1] + t[1], w[2] + t[2]))
        if not corner:
            continue
        i0 = len(local) + vbase
        local.extend(corner)
        faces.append((i0, i0 + 1, i0 + 2))
        faces.append((i0 + 1, i0 + 3, i0 + 2))
    if local:
        lines.append("o stitches")
        for x, y, z in local:
            lines.append(f"v {x} {-y} {z}")
        for a, b, c in faces:
            lines.append(f"f {a} {b} {c}")
        nv += len(local)
        nt += len(faces)

    open(out_path, "w").write("\n".join(lines) + "\n")
    print(f"wrote {out_path}: {nv} vertices, {nt} triangles "
          f"({len(faces) // 2} stitch quads)")


if __name__ == "__main__":
    main()
