"""Export Jade Cocoon mesh blocks to Wavefront OBJ.

Chunk body layouts recovered from the game's own converters:

FT4 (type 6, body 0x2C) - FUN_80024484:
    +0x00 u16 clut
    +0x02 u16 tpage
    +0x04 s16 nx, ny, nz, pad          (face normal)
    +0x0C + i*8  vertex i: s16 x, y, z ; u8 u, v      (i = 0..3)

GT4 (type 7, body 0x54) - FUN_80024798:
    +0x00..0x13  header (clut/tpage/UVs)
    +0x14 + i*16 vertex i: s16 x, y, z ; 2B ; s16 nx, ny, nz ; 2B   (i = 0..3)

GT3/FT3/F3/F4 follow the same idea with 3 vertices or no per-vertex normals;
the two above cover the overwhelming majority of primitives in every model file.

Quads are emitted as two triangles with the PS1 vertex order (0,1,2) + (1,3,2).

Usage:
    python export_mesh.py <package_file> <sector> <out.obj> [--mesh N]
"""
import struct
import sys

import mesh as meshmod

# type -> (vertexCount, firstVertexOffset, vertexStride)
# Header size = (4 if textured) + (per-vertex colors if gouraud, else one 8-byte normal),
# and every entry satisfies  header + nVerts*stride == on-disc body size.
# Gouraud types use a 16-byte vertex block holding the NORMAL first (a unit vector
# in 4096 fixed point) and the POSITION at +8. Flat/textured types use an 8-byte
# block that is position + u8 UV, with a single face normal in the header.
GEOM = {
    #   nVerts, firstBlockOff, blockStride, posOffsetInBlock
    0: (3, 0x0C, 8, 0),    # F3   0x24 = 12 + 3*8
    1: (3, 0x0C, 16, 8),   # G3   0x3C = 12 + 3*16
    2: (3, 0x0C, 8, 0),    # FT3  0x24 = 12 + 3*8
    3: (3, 0x10, 16, 8),   # GT3  0x40 = 16 + 3*16
    4: (4, 0x0C, 8, 0),    # F4   0x2C = 12 + 4*8
    5: (4, 0x10, 16, 8),   # G4   0x50 = 16 + 4*16
    6: (4, 0x0C, 8, 0),    # FT4  0x2C = 12 + 4*8   (confirmed via FUN_80024484)
    7: (4, 0x14, 16, 8),   # GT4  0x54 = 20 + 4*16  (confirmed via FUN_80024798)
}

# sanity: layout must exactly fill the on-disc body
for _t, (_nv, _first, _stride, _po) in GEOM.items():
    assert _first + _nv * _stride == meshmod.TYPES[_t][2], f"layout mismatch for type {_t}"


def seam_pool(data, obj):
    """Per-bone seam vertex pool, from chunk types 8 and 9.

    Each 0x14-byte item stores a normal at +0 and the POSITION at +8 (the same
    convention as the gouraud vertex blocks). Confirmed: for every bone,
    len(pool) == max stitch vertexIndex + 1, and resolving the stitch quads
    through it yields sane seam-sized quads (median 53 units) instead of the
    ~6856 you get from the +0 vector.
    """
    return [it["pos"] for it in seam_pool_full(data, obj)]


def seam_pool_full(data, obj):
    """Seam vertex pool with its UVs and texture ids.

    Layout of one 0x14-byte on-disc item, read straight off the game's converters
    FUN_80023074 (type 8) and FUN_80023274 (type 9), which copy it into the runtime
    record field by field:

        +0x00 s16 nx, ny, nz     normal      -> runtime +0x04
        +0x08 s16  x,  y,  z     position    -> runtime +0x0C
        +0x0E u8  u              texel u     -> packed into runtime +0x12  (type 9 only)
        +0x0F u8  v              texel v
        +0x10 u8  r, g, b        vertex colour -> runtime +0x00..+0x02

    Type 9 additionally has an 8-byte body header `{u32 count; u16 tpage; u16 clut}`
    that applies to the whole pool - the same (tpage, clut) pair the bone's textured
    faces use. Type 8 has only `{u32 count}` and explicitly zeroes the runtime UV word,
    so those seam vertices are untextured.

    This is why the earlier export left the connecting strips blank and their UV islands
    empty: only the position was being read.
    """
    out = []
    for t, p, _flags in obj["chunks"]:
        if t not in (8, 9):
            continue
        n = struct.unpack_from("<I", data, p + 4)[0]
        if t == 9:
            tpage, clut = struct.unpack_from("<2H", data, p + 8)
            body = p + 12
        else:
            tpage = clut = None
            body = p + 8
        for i in range(n):
            it = body + i * 0x14
            out.append({
                "pos": struct.unpack_from("<3h", data, it + 8),
                "nrm": struct.unpack_from("<3h", data, it),
                "uv": (data[it + 0x0E], data[it + 0x0F]) if t == 9 else None,
                "tpage": tpage,
                "clut": clut,
            })
    return out


def read_stitches(data, base):
    """The mesh block's stitch quads: 4 x (boneIndex, seamVertexIndex) each."""
    _total, _mc, count, off = struct.unpack_from("<4I", data, base)
    quads = []
    for i in range(count):
        p = base + off + i * 16
        quads.append([struct.unpack_from("<2H", data, p + k * 4) for k in range(4)])
    return quads


# type -> (firstBlockOff, blockStride, uvOffsetInBlock) for the textured types.
# UV byte positions confirmed from the converters: GT4 (FUN_80024798) reads them
# at body 0x22/0x32/0x42/0x52, i.e. block+14; FT4 (FUN_80024484) at block+6.
TEXUV = {
    2: (0x0C, 8, 6),    # FT3
    3: (0x10, 16, 14),  # GT3
    6: (0x0C, 8, 6),    # FT4
    7: (0x14, 16, 14),  # GT4
}


def read_prims_tex(data, obj):
    """Yield (type, verts, uvs, tpage, clut) - uvs/tpage are None when untextured.

    tpage and clut are the first two u16 of the chunk body.
    """
    for t, p, _flags in obj["chunks"]:
        if t not in GEOM:
            continue
        nv, first, stride, posoff = GEOM[t]
        body = p + 4
        verts = [struct.unpack_from("<3h", data, body + first + i * stride + posoff)
                 for i in range(nv)]
        if t in TEXUV:
            f2, s2, uvo = TEXUV[t]
            uvs = [(data[body + f2 + i * s2 + uvo], data[body + f2 + i * s2 + uvo + 1])
                   for i in range(nv)]
            tpage, clut = struct.unpack_from("<2H", data, body)
            yield t, verts, uvs, tpage, clut
        else:
            yield t, verts, None, None, None


def read_prims(data, obj):
    """Yield (type, [(x,y,z), ...]) for each geometry chunk in a mesh object."""
    for t, p, _flags in obj["chunks"]:
        if t not in GEOM:
            continue
        nv, first, stride, posoff = GEOM[t]
        body = p + 4
        verts = []
        for i in range(nv):
            x, y, z = struct.unpack_from("<3h", data, body + first + i * stride + posoff)
            verts.append((x, y, z))
        yield t, verts


def main():
    path, sector, out_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    only = None
    if "--mesh" in sys.argv:
        only = int(sys.argv[sys.argv.index("--mesh") + 1])

    data = open(path, "rb").read()
    r = meshmod.parse_block(data, sector * 2048)
    if "objs" not in r or ("failed_at" in r):
        print("mesh block did not parse")
        return

    lines = ["# Jade Cocoon mesh export", f"# source {path} sector {sector}"]
    vbase = 1
    nverts = ntris = 0
    for mi, obj in enumerate(r["objs"]):
        if only is not None and mi != only:
            continue
        prims = list(read_prims(data, obj))
        if not prims:
            continue
        lines.append(f"o mesh_{mi:03d}")
        local = []
        faces = []
        for t, verts in prims:
            idx = [len(local) + vbase + k for k in range(len(verts))]
            local.extend(verts)
            if len(verts) == 3:
                faces.append((idx[0], idx[1], idx[2]))
            else:
                faces.append((idx[0], idx[1], idx[2]))
                faces.append((idx[1], idx[3], idx[2]))
        for x, y, z in local:
            # PS1 Y is down; flip to make the model upright in normal viewers
            lines.append(f"v {x} {-y} {z}")
        for a, b, c in faces:
            lines.append(f"f {a} {b} {c}")
        vbase += len(local)
        nverts += len(local)
        ntris += len(faces)

    open(out_path, "w").write("\n".join(lines) + "\n")
    print(f"wrote {out_path}: {nverts} vertices, {ntris} triangles "
          f"from {len(r['objs'])} mesh objects")
    xs = [v[0] for o in r["objs"] for _, vs in read_prims(data, o) for v in vs]
    ys = [v[1] for o in r["objs"] for _, vs in read_prims(data, o) for v in vs]
    zs = [v[2] for o in r["objs"] for _, vs in read_prims(data, o) for v in vs]
    if xs:
        print(f"  bounds X[{min(xs)},{max(xs)}] Y[{min(ys)},{max(ys)}] Z[{min(zs)},{max(zs)}]")


if __name__ == "__main__":
    main()
