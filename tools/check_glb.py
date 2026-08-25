"""Validate a GLB: structure, accessor bounds, skin sanity, and skinning result.

Recomputes skinned vertex positions by walking the node hierarchy and compares
them against an independently produced OBJ (assemble_model.py output), which
catches any mismatch between the two code paths.

Usage: python check_glb.py <file.glb> [reference.obj]
"""
import json
import struct
import sys

CT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2),
      5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def load(path):
    raw = open(path, "rb").read()
    assert raw[:4] == b"glTF", "not a GLB"
    ver, total = struct.unpack_from("<II", raw, 4)
    assert ver == 2, f"version {ver}"
    assert total == len(raw), f"header length {total} != file {len(raw)}"
    p = 12
    js = bin_data = None
    while p < len(raw):
        clen, ctype = struct.unpack_from("<I4s", raw, p)
        chunk = raw[p + 8:p + 8 + clen]
        if ctype == b"JSON":
            js = json.loads(chunk)
        elif ctype[:3] == b"BIN":
            bin_data = chunk
        p += 8 + clen
    return js, bin_data


def read_accessor(g, bin_data, idx):
    a = g["accessors"][idx]
    v = g["bufferViews"][a["bufferView"]]
    fmt, size = CT[a["componentType"]]
    n = NCOMP[a["type"]]
    off = v.get("byteOffset", 0)
    need = a["count"] * n * size
    assert off + need <= len(bin_data), f"accessor {idx} runs past buffer"
    assert need <= v["byteLength"], f"accessor {idx} exceeds its bufferView"
    vals = struct.unpack_from(f"<{a['count']*n}{fmt}", bin_data, off)
    return [vals[i * n:(i + 1) * n] for i in range(a["count"])]


def quat_mat(q):
    x, y, z, w = q
    return [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
            2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
            2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]


def node_matrix(n):
    t = n.get("translation", [0, 0, 0])
    q = n.get("rotation", [0, 0, 0, 1])
    m = quat_mat(q)
    return (m, t)


def compose(parent, child):
    pm, pt = parent
    cm, ct = child
    m = [sum(pm[r * 3 + k] * cm[k * 3 + c] for k in range(3))
         for r in range(3) for c in range(3)]
    t = [pt[i] + sum(pm[i * 3 + k] * ct[k] for k in range(3)) for i in range(3)]
    return (m, t)


def main():
    path = sys.argv[1]
    g, bin_data = load(path)
    print(f"GLB ok: {len(g['nodes'])} nodes, {len(g['accessors'])} accessors, "
          f"{len(g.get('animations', []))} animations, bin {len(bin_data)} bytes")
    assert g["buffers"][0]["byteLength"] <= len(bin_data), "buffer length mismatch"

    # accessor bounds
    for i in range(len(g["accessors"])):
        read_accessor(g, bin_data, i)
    print("  all accessors within their bufferViews")

    skin = g["skins"][0]
    njoints = len(skin["joints"])
    pos, jnt, ntri = [], [], 0
    # Every mesh, not just meshes[0]: hidden body-part groups are exported as extra
    # meshes, and validating only the first would skip exactly the geometry that is
    # new and least proven.
    nprim = sum(len(m["primitives"]) for m in g["meshes"])
    for prim in [p for m in g["meshes"] for p in m["primitives"]]:
        p = read_accessor(g, bin_data, prim["attributes"]["POSITION"])
        j = read_accessor(g, bin_data, prim["attributes"]["JOINTS_0"])
        w = read_accessor(g, bin_data, prim["attributes"]["WEIGHTS_0"])
        i = [v[0] for v in read_accessor(g, bin_data, prim["indices"])]
        assert max(i) < len(p), "index out of range"
        assert all(x[0] < njoints for x in j), "joint index out of range"
        assert all(abs(sum(x) - 1.0) < 1e-5 for x in w), "weights do not sum to 1"
        if "TEXCOORD_0" in prim["attributes"]:
            uv = read_accessor(g, bin_data, prim["attributes"]["TEXCOORD_0"])
            assert len(uv) == len(p), "UV count != vertex count"
            if "material" in prim and "baseColorTexture" in \
                    g["materials"][prim["material"]].get("pbrMetallicRoughness", {}):
                bad = [t for t in uv if not (-0.001 <= t[0] <= 1.001 and -0.001 <= t[1] <= 1.001)]
                assert not bad, f"{len(bad)} UVs outside [0,1], e.g. {bad[:3]}"
        pos += p
        jnt += j
        ntri += len(i) // 3
    ntex = len(g.get("textures", []))
    print(f"  {len(g['meshes'])} mesh(es), {nprim} primitives, {len(pos)} verts, "
          f"{ntri} tris, {njoints} joints, {ntex} texture(s); weights and UVs valid")

    # hierarchy: every joint reachable exactly once, no cycles
    seen = set()

    def walk(ni, depth=0):
        assert ni not in seen, f"node {ni} visited twice (cycle)"
        seen.add(ni)
        for c in g["nodes"][ni].get("children", []):
            walk(c, depth + 1)

    for root in g["scenes"][0]["nodes"]:
        walk(root)
    assert set(skin["joints"]) <= seen, "some joints not in the scene graph"
    print(f"  hierarchy acyclic, {len(seen)} nodes reachable, all joints present")

    # world matrices
    world = {}

    def build(ni, parent):
        m = compose(parent, node_matrix(g["nodes"][ni]))
        world[ni] = m
        for c in g["nodes"][ni].get("children", []):
            build(c, m)

    ident = ([1, 0, 0, 0, 1, 0, 0, 0, 1], [0, 0, 0])
    for root in g["scenes"][0]["nodes"]:
        build(root, ident)

    # Full glTF skinning: world(joint) * inverseBindMatrix(joint) * position.
    # The inverse bind matrices used to be identity (positions were stored in bone-local
    # space), so this step could be skipped; now that positions are baked into bind-pose
    # space it is mandatory - skipping it double-transforms and quietly shifts the bounds.
    ibm = None
    if "inverseBindMatrices" in skin:
        raw = read_accessor(g, bin_data, skin["inverseBindMatrices"])
        ibm = []
        for c in raw:                      # glTF MAT4 is column-major
            ibm.append(([c[0], c[4], c[8], c[1], c[5], c[9], c[2], c[6], c[10]],
                        [c[12], c[13], c[14]]))

    def apply(rt, v):
        m, t = rt
        return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + t[0],
                m[3] * v[0] + m[4] * v[1] + m[5] * v[2] + t[1],
                m[6] * v[0] + m[7] * v[1] + m[8] * v[2] + t[2])

    skinned = []
    for v, j in zip(pos, jnt):
        p = apply(ibm[j[0]], v) if ibm else v
        skinned.append(apply(world[skin["joints"][j[0]]], p))
    xs = [p[0] for p in skinned]
    ys = [p[1] for p in skinned]
    zs = [p[2] for p in skinned]
    print(f"  skinned bounds X[{min(xs):.2f},{max(xs):.2f}] "
          f"Y[{min(ys):.2f},{max(ys):.2f}] Z[{min(zs):.2f},{max(zs):.2f}]")

    if len(sys.argv) > 2:
        ref = []
        for line in open(sys.argv[2]):
            if line.startswith("v "):
                _, a, bb, c = line.split()
                ref.append((float(a), float(bb), float(c)))
        # OBJ used (x,-y,z); GLB root rotates 180 about X giving (x,-y,-z)
        assert len(ref) == len(skinned), f"vertex count {len(ref)} vs {len(skinned)}"
        worst = 0.0
        for (rx, ry, rz), (sx, sy, sz) in zip(ref, skinned):
            worst = max(worst, abs(rx / 100.0 - sx), abs(ry / 100.0 - sy),
                        abs(-rz / 100.0 - sz))
        print(f"  vs {sys.argv[2]}: max coordinate difference {worst:.5f}")
        # assemble_model.py mirrors the game exactly: integer math with >>12
        # truncation at every bone. The GLB uses floats, so a small divergence
        # is expected and grows with chain depth (measured: up to 2.9 game
        # units = 0.029 glTF units on the deepest bone). Anything beyond that
        # would indicate a real error.
        assert worst < 0.05, "skinned result diverges from the reference OBJ"
        print("  MATCH - glTF skinning reproduces the independent assembly")
        print("  (residual is fixed-point vs float rounding, not a structural error)")


if __name__ == "__main__":
    main()
