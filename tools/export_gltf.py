"""Export a Jade Cocoon model as a rigged, animated, TEXTURED GLB for Blender.

Everything here comes from the binary (see MODEL_FORMAT.md):
  * geometry  - per-bone mesh objects, sequential tagged chunk stream
  * seams     - stitch quads whose corners belong to different bones
  * skeleton  - bone table in the exe; parent implied by DEPTH
  * rest pose - per-bone translations in the animation block header
  * root      - bone 1's translation is animated from keyframe entry 1
  * animation - per-bone Euler rotations, 4096 units/turn, via the exe sine LUT
  * textures  - the model's TIMs retiled into their VRAM page, so face u,v can be
                used directly (divided by the page size)

Rigging: the game stores each bone's vertices in that bone's LOCAL space, which is
what an earlier version of this exporter wrote straight into POSITION with identity
inverse bind matrices. It animated correctly but every bone's geometry sat on top of
the origin in Blender's edit mode, making the mesh unusable for editing or UV work.
POSITION is now baked into BIND-POSE space (each vertex pushed through its joint's
rest world transform) with inverseBindMatrices set to the inverse of that transform,
so the rest pose renders identically while edit mode shows an assembled creature.
Every vertex still binds to exactly one joint at weight 1.0.

A root node rotates 180 degrees about X to turn PS1 Y-down into glTF Y-up (a real
rotation, not a mirror); that rotation is part of the bind transform, so joints and
baked vertices agree.

Usage:
  python export_gltf.py <exe> <package> <meshSector> <animSector> <boneTableAddr>
                        <out.glb> [--tex SECTOR] [--scale S] [--name PREFIX]
                        [--root NAME] [--animpkg FILE] [--animslots S,S,...]
"""
import json
import math
import struct
import sys

import anim as animmod
import appearance as appmod
import assemble_model as AM
import export_mesh
import mesh as meshmod
import texture_atlas

FPS = 30.0


def mat_to_quat(m):
    """Row-major 3x3 (floats) -> (x, y, z, w)."""
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = m
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        w, x, y, z = (m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        w, x, y, z = (m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        w, x, y, z = (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    return (x / n, y / n, z / n, w / n)


def rot_quat(lut, a0, a1, a2):
    return mat_to_quat(tuple(v / 4096.0 for v in AM.rot_matrix(lut, a0, a1, a2)))


# 180 degrees about X: PS1 is Y-down, glTF is Y-up. This is folded into the ROOT JOINT's
# local transform rather than into a wrapper node above the mesh. A wrapper works for
# rendering, but Blender then applies it to the mesh object on top of vertex positions that
# already have it baked in, and the model shows up upside down in edit mode.
ROOT_FLIP = (1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0)


def mat3_mul(a, b):
    """Row-major 3x3 multiply."""
    return tuple(sum(a[r * 3 + k] * b[k * 3 + c] for k in range(3))
                 for r in range(3) for c in range(3))


def flip_vec(t):
    return (t[0], -t[1], -t[2])


def mat4_mul(a, b):
    """Row-major 4x4 multiply."""
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4)
            for c in range(4)]


def mat4_from_rt(r3, t):
    """Row-major 4x4 from a row-major 3x3 rotation and a translation."""
    return [r3[0], r3[1], r3[2], t[0],
            r3[3], r3[4], r3[5], t[1],
            r3[6], r3[7], r3[8], t[2],
            0.0, 0.0, 0.0, 1.0]


def mat4_apply(m, v):
    return tuple(m[r * 4 + 0] * v[0] + m[r * 4 + 1] * v[1] + m[r * 4 + 2] * v[2] + m[r * 4 + 3]
                 for r in range(3))


def mat4_invert_rigid(m):
    """Inverse of a rotation+translation matrix (no scale): R^T, -R^T t."""
    r = [m[0], m[4], m[8], m[1], m[5], m[9], m[2], m[6], m[10]]
    t = (m[3], m[7], m[11])
    ti = tuple(-(r[i * 3] * t[0] + r[i * 3 + 1] * t[1] + r[i * 3 + 2] * t[2]) for i in range(3))
    return mat4_from_rt(r, ti)


def mat4_to_gltf(m):
    """Row-major 4x4 -> the column-major 16 floats glTF wants."""
    return struct.pack("<16f", m[0], m[4], m[8], m[12],
                       m[1], m[5], m[9], m[13],
                       m[2], m[6], m[10], m[14],
                       m[3], m[7], m[11], m[15])


class Buf:
    def __init__(self):
        self.data = bytearray()
        self.views = []
        self.accessors = []

    def add(self, raw, target=None):
        while len(self.data) % 4:
            self.data.append(0)
        off = len(self.data)
        self.data += raw
        v = {"buffer": 0, "byteOffset": off, "byteLength": len(raw)}
        if target:
            v["target"] = target
        self.views.append(v)
        return len(self.views) - 1

    def accessor(self, view, ctype, count, atype, mn=None, mx=None):
        a = {"bufferView": view, "componentType": ctype, "count": count, "type": atype}
        if mn is not None:
            a["min"], a["max"] = mn, mx
        self.accessors.append(a)
        return len(self.accessors) - 1


def main():
    exe_path, pkg_path = sys.argv[1], sys.argv[2]
    mesh_sec, anim_sec = int(sys.argv[3]), int(sys.argv[4])
    anim_path = sys.argv[sys.argv.index("--animpkg") + 1] if "--animpkg" in sys.argv else None
    bone_spec = sys.argv[5]
    out_path = sys.argv[6]
    tex_sec = int(sys.argv[sys.argv.index("--tex") + 1]) if "--tex" in sys.argv else None
    scale = float(sys.argv[sys.argv.index("--scale") + 1]) if "--scale" in sys.argv else 0.01

    exe = open(exe_path, "rb").read()
    data = open(pkg_path, "rb").read()
    lut = AM.load_lut(exe)
    bones = AM.load_bones_spec(exe, bone_spec)
    mr = meshmod.parse_block(data, mesh_sec * 2048)
    adata = open(anim_path, "rb").read() if anim_path else data
    slots = ([int(x) for x in sys.argv[sys.argv.index("--animslots") + 1].split(",") if x]
             if "--animslots" in sys.argv else [])
    blocks = animmod.load_set(adata, anim_sec, slots)
    if not blocks:
        print("no animation blocks found")
        return
    rest = animmod.rest_offsets(adata, blocks[0])
    parent_of = AM.parents_from_depth(bones)
    nb = len(bones)
    name_prefix = (sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv
                   else "")
    # What the root node is called. Every model used to export as "JadeCocoonModel",
    # so a Blender scene with ten of them loaded showed ten identically named objects.
    root_name = (sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv
                 else "JadeCocoonModel")

    # ---- body-part groups the game does not draw.
    # partFlagsA[g] < 2 clears the draw+transform bit for every bone in group g
    # (FUN_80019B14), so 26 of the 48 creatures ship limbs that never appear in game -
    # the bird with hands, the three that hide arms, wings AND legs. The geometry is not
    # junk: the merge ORs the flags (`if (other.A[k] > 1 && mine.A[k] == 1) A[k] = 2`),
    # so a merged creature can gain the part. Emitting it as a separate node keeps it
    # toggleable instead of deleting data the merge needs. See RIG_ATTRIBUTION.md.
    _off, appr = appmod.find(data)
    hidden_of = {}
    if appr and appr["stages"]:
        flags = appr["stages"][-1]["partFlagsA"]
        for g, name in enumerate(appmod.PART_NAMES):
            if flags[g] < 2:
                for bi in appmod.bones_in_group(g):
                    hidden_of[bi] = name

    def joint_local(slf, blk, frame):
        """A joint's local rotation+translation, with the Y-up flip folded into roots."""
        rx, ry, rz = animmod.keyframe(adata, blk, frame, slf)
        if slf == 0:
            rx = ry = rz = 0          # the renderer forces slot 0 to zero rotation
        r3 = tuple(v / 4096.0 for v in AM.rot_matrix(lut, rx, ry, rz))
        if slf == 1:
            t = animmod.root_translation(adata, blk, frame)
        else:
            t = rest[slf] if slf < len(rest) else (0, 0, 0)
        if parent_of[slf] == slf:
            r3, t = mat3_mul(ROOT_FLIP, r3), flip_vec(t)
        return r3, tuple(c * scale for c in t)

    # ---- bind pose: the rest world transform of every joint. The joint nodes below are
    # given exactly this local TRS, so baked vertices and joints agree.
    local_trs = {slf: joint_local(slf, blocks[0], 0) for _d, slf, _b3, _m in bones}
    bind, inv_bind = {}, {}
    ident4 = mat4_from_rt((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
    for _d, slf, _b3, _m in bones:          # table order is depth-first: parents come first
        r3, t = local_trs[slf]
        par = parent_of[slf]
        base_m = ident4 if par == slf else bind[par]
        bind[slf] = mat4_mul(base_m, mat4_from_rt(r3, t))
        inv_bind[slf] = mat4_invert_rigid(bind[slf])

    # ---- which texture pages are used, so each atlas gets the right size
    used_tpages = set()
    pools = {}
    for _d, slf, _b3, midx in bones:
        if 0 <= midx < len(mr["objs"]):
            for _t, _v, uvs, tp, _cl in export_mesh.read_prims_tex(data, mr["objs"][midx]):
                if uvs:
                    used_tpages.add(tp)
            pools[slf] = export_mesh.seam_pool_full(data, mr["objs"][midx])
            for it in pools[slf]:
                if it["uv"] is not None:
                    used_tpages.add(it["tpage"])
    claimed = {midx for _d, _s, _b3, midx in bones}
    unclaimed = [m for m in range(len(mr["objs"])) if m not in claimed]
    for midx in unclaimed:
        for _t, _v, uvs, tp, _cl in export_mesh.read_prims_tex(data, mr["objs"][midx]):
            if uvs:
                used_tpages.add(tp)
    atlases = {}
    if tex_sec is not None and used_tpages:
        atlases = texture_atlas.build(data, tex_sec, sorted(used_tpages))
    wh = {tp: (a["w"], a["h"]) for tp, a in atlases.items()}

    # ---- geometry, grouped by texture page (one primitive + material per group)
    groups = {}

    def add_face(key, verts, uvs, bone_ids, force_part=None):
        # A face belongs to the hidden group of any bone it touches, so a seam strip
        # running into a hidden limb hides along with the limb instead of dangling.
        part = force_part or next((hidden_of[bi] for bi in bone_ids if bi in hidden_of),
                                  None)
        g = groups.setdefault((key, part),
                              {"pos": [], "uv": [], "j": [], "w": [], "idx": []})
        base = len(g["pos"])
        size = wh.get(key)
        for i, v in enumerate(verts):
            local = (v[0] * scale, v[1] * scale, v[2] * scale)
            g["pos"].append(mat4_apply(bind[bone_ids[i]], local))
            g["j"].append((bone_ids[i], 0, 0, 0))
            g["w"].append((1.0, 0.0, 0.0, 0.0))
            g["uv"].append((uvs[i][0] / size[0], uvs[i][1] / size[1])
                           if (uvs and size) else (0.0, 0.0))
        if len(verts) == 3:
            g["idx"] += [base, base + 1, base + 2]
        else:
            g["idx"] += [base, base + 1, base + 2, base + 1, base + 3, base + 2]

    for _d, slf, _b3, midx in bones:
        if not (0 <= midx < len(mr["objs"])):
            continue
        for _t, verts, uvs, tp, _cl in export_mesh.read_prims_tex(data, mr["objs"][midx]):
            key = tp if (uvs and tp in wh) else None
            add_face(key, verts, uvs if key is not None else None, [slf] * len(verts))

    # Mesh objects no bone claims used to be dropped on the floor: the rig indexes mesh
    # objects, geometry was only ever emitted per bone, and every model whose mesh count
    # exceeds its bone count therefore lost real geometry - model 870 lost a 79-primitive
    # object, 871 lost 59, 904 lost 42. Emit them skinned to the root joint and named so
    # it is obvious they are unattributed rather than pretending they belong to a bone.
    root_joint = bones[0][1]
    for midx in unclaimed:
        for _t, verts, uvs, tp, _cl in export_mesh.read_prims_tex(data, mr["objs"][midx]):
            key = tp if (uvs and tp in wh) else None
            add_face(key, verts, uvs if key is not None else None,
                     [root_joint] * len(verts), force_part="unclaimed")

    # Seam polygons: corners belong to different bones, handled by per-vertex skinning.
    # Type-9 seam vertices carry their own u,v and share the pool's (tpage, clut), so
    # these quads are textured like any other face - they are the connecting strips whose
    # UV islands looked empty while only the position was read.
    nstitch = ntex_stitch = 0
    for quad in export_mesh.read_stitches(data, mesh_sec * 2048):
        corner, bone_ids, uvs, tps = [], [], [], set()
        for bi, vi in quad:
            pool = pools.get(bi)
            if pool is None or vi >= len(pool):
                corner = None
                break
            it = pool[vi]
            corner.append(it["pos"])
            bone_ids.append(bi)
            uvs.append(it["uv"])
            tps.add(it["tpage"])
        if not corner:
            continue
        key = None
        if len(tps) == 1 and all(u is not None for u in uvs):
            tp = next(iter(tps))
            if tp in wh:
                key = tp
                ntex_stitch += 1
        add_face(key, corner, uvs if key is not None else None, bone_ids)
        nstitch += 1

    b = Buf()
    images, textures, materials, primitives = [], [], [], []
    mat_of = {}
    for tp, a in atlases.items():
        v_img = b.add(texture_atlas.png_bytes(a))
        images.append({"bufferView": v_img, "mimeType": "image/png",
                       "name": f"page_{tp:04X}"})
        textures.append({"source": len(images) - 1, "sampler": 0})
        materials.append({
            "name": f"page_{tp:04X}",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": len(textures) - 1},
                "metallicFactor": 0.0, "roughnessFactor": 1.0,
            },
            "alphaMode": "MASK", "alphaCutoff": 0.5, "doubleSided": True,
        })
        mat_of[tp] = len(materials) - 1
    if any(k is None for k, _part in groups):
        materials.append({"name": "untextured", "doubleSided": True,
                          "pbrMetallicRoughness": {
                              "baseColorFactor": [0.72, 0.72, 0.76, 1.0],
                              "metallicFactor": 0.0, "roughnessFactor": 1.0}})
        mat_of[None] = len(materials) - 1

    total_v = total_t = 0
    prims_by_part = {}
    for (key, part), g in groups.items():
        if not g["pos"]:
            continue
        mn = [min(p[i] for p in g["pos"]) for i in range(3)]
        mx = [max(p[i] for p in g["pos"]) for i in range(3)]
        a_pos = b.accessor(b.add(b"".join(struct.pack("<3f", *p) for p in g["pos"]), 34962),
                           5126, len(g["pos"]), "VEC3", mn, mx)
        a_uv = b.accessor(b.add(b"".join(struct.pack("<2f", *t) for t in g["uv"]), 34962),
                          5126, len(g["uv"]), "VEC2")
        a_j = b.accessor(b.add(b"".join(struct.pack("<4H", *j) for j in g["j"]), 34962),
                         5123, len(g["j"]), "VEC4")
        a_w = b.accessor(b.add(b"".join(struct.pack("<4f", *w) for w in g["w"]), 34962),
                         5126, len(g["w"]), "VEC4")
        n_idx = len(g["idx"])
        a_i = b.accessor(b.add(struct.pack(f"<{n_idx}I", *g["idx"]), 34963),
                         5125, n_idx, "SCALAR")
        prim = {"attributes": {"POSITION": a_pos, "TEXCOORD_0": a_uv,
                               "JOINTS_0": a_j, "WEIGHTS_0": a_w},
                "indices": a_i, "mode": 4}
        if key in mat_of:
            prim["material"] = mat_of[key]
        prims_by_part.setdefault(part, []).append(prim)
        primitives.append(prim)
        total_v += len(g["pos"])
        total_t += n_idx // 3

    ibm_raw = b"".join(mat4_to_gltf(inv_bind[slf]) for _d, slf, _b3, _m in bones)
    a_ibm = b.accessor(b.add(ibm_raw), 5126, nb, "MAT4")

    # ---- nodes: root wrapper + one node per joint. The local TRS here is exactly what
    # the bind matrices above were built from, so the rest pose reproduces the baked
    # vertex positions.
    # The wrapper is a plain identity node: the Y-up flip lives in the root joint, so
    # nothing above the mesh can apply it a second time.
    nodes = [{"name": root_name, "children": []}]
    joint_node = {}
    for _d, slf, _b3, _m in bones:
        r3, t = local_trs[slf]
        nodes.append({"name": f"bone{slf:02d}",
                      "translation": list(t),
                      "rotation": list(mat_to_quat(r3))})
        joint_node[slf] = len(nodes) - 1
    for _d, slf, _b3, _m in bones:
        par = parent_of[slf]
        if par == slf:
            nodes[0]["children"].append(joint_node[slf])
        else:
            nodes[joint_node[par]].setdefault("children", []).append(joint_node[slf])

    # One mesh for what the game draws, plus one per hidden body-part group so the
    # hidden limbs can be switched back on (which is exactly what a merge does) rather
    # than being silently dropped from the export.
    meshes = []
    for part in [None] + sorted(p for p in prims_by_part if p is not None):
        prims = prims_by_part.get(part) or []
        if not prims:
            continue
        meshes.append({"name": "model" if part is None else "hidden_%s" % part,
                       "primitives": prims})
        nodes.append({"name": meshes[-1]["name"], "mesh": len(meshes) - 1, "skin": 0})
        nodes[0]["children"].append(len(nodes) - 1)
    joints_list = [joint_node[s] for _d, s, _p, _m in bones]

    # ---- animations
    animations = []
    for ai, blk in enumerate(blocks):
        nframes = blk["frames"]
        if nframes < 1:
            continue
        times = [i / FPS for i in range(nframes)]
        a_t = b.accessor(b.add(struct.pack(f"<{nframes}f", *times)),
                         5126, nframes, "SCALAR", [0.0], [times[-1]])
        channels, samplers = [], []
        for _d, slf, _p, _m in bones:
            if slf >= blk["bones"]:
                continue
            # joint_local() carries the Y-up flip for root joints, so the animation must
            # use it too - keying a bare identity on the root would undo the flip the
            # moment an action plays.
            quats = [mat_to_quat(joint_local(slf, blk, fr)[0]) for fr in range(nframes)]
            a_q = b.accessor(b.add(b"".join(struct.pack("<4f", *q) for q in quats)),
                             5126, nframes, "VEC4")
            samplers.append({"input": a_t, "output": a_q, "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1,
                             "target": {"node": joint_node[slf], "path": "rotation"}})
            if slf == 1:
                trs = []
                for fr in range(nframes):
                    trs.append(joint_local(slf, blk, fr)[1])
                a_tr = b.accessor(b.add(b"".join(struct.pack("<3f", *t) for t in trs)),
                                  5126, nframes, "VEC3")
                samplers.append({"input": a_t, "output": a_tr, "interpolation": "LINEAR"})
                channels.append({"sampler": len(samplers) - 1,
                                 "target": {"node": joint_node[slf], "path": "translation"}})
        # Blender de-duplicates action names across imported files by appending .001,
        # .002 ... so unprefixed "anim2_32f" from three models collides into three
        # confusing "variants". Prefixing with the model id keeps them apart. A single
        # frame is a pose, not a motion, so say so.
        kind = "pose" if nframes == 1 else "anim"
        animations.append({"name": f"{name_prefix}{kind}{ai:02d}_{nframes}f",
                           "samplers": samplers, "channels": channels})

    gltf = {
        "asset": {"version": "2.0", "generator": "JadeCocoon RE export_gltf.py"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "meshes": meshes,
        "skins": [{"inverseBindMatrices": a_ibm, "joints": joints_list,
                   "skeleton": joint_node[bones[0][1]]}],
        "bufferViews": b.views,
        "accessors": b.accessors,
        "buffers": [{"byteLength": len(b.data)}],
    }
    if images:
        gltf["images"] = images
        gltf["textures"] = textures
        gltf["samplers"] = [{"magFilter": 9728, "minFilter": 9728,
                             "wrapS": 10497, "wrapT": 10497}]  # nearest = PS1 look
    if materials:
        gltf["materials"] = materials
    if animations:
        gltf["animations"] = animations

    js = json.dumps(gltf, separators=(",", ":")).encode()
    while len(js) % 4:
        js += b" "
    bin_data = bytes(b.data)
    while len(bin_data) % 4:
        bin_data += b"\x00"
    total = 12 + 8 + len(js) + 8 + len(bin_data)
    with open(out_path, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, total))
        f.write(struct.pack("<I", len(js)) + b"JSON" + js)
        f.write(struct.pack("<I", len(bin_data)) + b"BIN\x00" + bin_data)
    print(f"wrote {out_path}: {total_v} verts, {total_t} tris, {nb} joints, "
          f"{len(animations)} anims, {len(atlases)} texture(s), "
          f"{nstitch} stitches ({ntex_stitch} textured), {total} bytes")


if __name__ == "__main__":
    main()
