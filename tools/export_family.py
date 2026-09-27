"""Export the 49-model merge family as a blend-ready package (R9).

Why this exists
---------------
`export_gltf.py` writes a beautiful GLB per model, but it splits hidden body-part
groups into their own primitives, so two family members do not share a vertex
order and cannot be used as each other's morph targets (MERGE_ALGORITHM.md,
"The current GLB export is NOT vertex-order identical").

This tool writes the same 49 creatures in ONE shared vertex order - every mesh
object, every primitive, every seam-pool vertex, hidden parts included - so a
consumer can run the game's own merge:

    dst = (0x1000 * dst + w * (src - dst)) >> 12

per vertex, per normal, on the exported s16 arrays and get exactly what
`merge_reference.py` produces from the archive bytes.

Output (see Docs/Research/family-format.md in the Unity project for the byte-by-byte
layout):

    family.json             shared topology: the 25-bone rig, the shared index
                            buffer, per-vertex joint / meshObject / partGroup,
                            the seam-stitch quads, the part-group bone masks and
                            the growth-stage level thresholds
    jc_NNNN.family.bin      per model: positions, normals, UVs, texture pages,
                            rest offsets, frame-0 rotations, 43 markers,
                            5 growth stages, part flags
    jc_NNNN_tex.png         per model: the whole texture atlas as RGBA
    jc_NNNN_clut.json       per model: the indexed-colour data (palettes +
                            per-texel palette/index planes) so a hue rotation
                            can be reproduced on the CLUT, not on RGB

Usage:
    python export_family.py --out ../models/family \\
        --unity-out "C:/.../Assets/Game/Art/Family" \\
        [--exe ../extracted/SLES_022.01] [--split ../extracted/DATA001_split] \\
        [--only 833,845] [--self-test]

This file only ever IMPORTS the existing tools; it never modifies them.
Original code. Reads the player's own disc; ships no game data.
"""

import base64
import glob
import json
import os
import shutil
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import anim as animmod                  # noqa: E402
import appearance as appmod             # noqa: E402
import assemble_model as AM             # noqa: E402
import export_mesh                      # noqa: E402
import merge_reference as MR            # noqa: E402
import mesh as meshmod                  # noqa: E402
import model_index                      # noqa: E402
import texture_atlas                    # noqa: E402
import tim as timmod                    # noqa: E402

# --------------------------------------------------------------------------- consts

CREATURE_RIG = 0x80079064       # the 25-bone rig every family member wears
FORMAT_VERSION = 1
MAGIC = b"JCFAMBIN"
HEADER_SIZE = 64
SECTION_ENTRY = 16
NO_PAGE = 0xFFFF                # per-vertex texture page id meaning "untextured"
NO_PALETTE = 0xFF               # per-texel palette id meaning "no texel here"

PART_GROUP_NAMES = ("none", "arms", "wings", "legs")

# The same normal table merge_reference blends through; repeated here only so the
# slot walk below is readable next to the code that uses it.
NORMALS = MR.NORMALS


def clamp16(v):
    return -0x8000 if v < -0x8000 else (0x7FFF if v > 0x7FFF else v)


def lerp_s16(d, s, w):
    """The game's per-component blend, exactly as merge_reference.lerp_svec does it."""
    return clamp16((0x1000 * d + w * clamp16(s - d)) >> 12)


# --------------------------------------------------------------------------- disc

class Disc:
    """The bits of the archive this exporter needs, loaded once."""

    def __init__(self, exe_path, split_dir):
        self.exe_path = exe_path
        self.split_dir = split_dir
        self.exe = open(exe_path, "rb").read()
        self.sections = model_index.sections(self.exe)
        self.bones = AM.load_bones(self.exe, CREATURE_RIG)
        self.parents = AM.parents_from_depth(self.bones)
        self.thresholds = list(MR.exe_read(self.exe, MR.STAGE_THRESHOLDS, 5))
        self.files = MR.model_files(self.exe)
        self._pkg = {}
        names_path = os.path.join(os.path.dirname(split_dir.rstrip("/\\")),
                                  "model_names.json")
        self.names = json.load(open(names_path)) if os.path.exists(names_path) else {}

    def package(self, fidx):
        if fidx not in self._pkg:
            hits = glob.glob(os.path.join(self.split_dir, "%04d_*.bin" % fidx))
            if not hits:
                raise KeyError("no split file for archive index %d" % fidx)
            self._pkg[fidx] = open(hits[0], "rb").read()
        return self._pkg[fidx]

    def name_of(self, fidx):
        rec = self.names.get("%04d" % fidx)
        return rec["name"] if rec else "Model%d" % fidx

    def mesh_sector(self, fidx):
        return self.sections[fidx]["ranges"][2][0]

    def tex_sector(self, fidx):
        return self.sections[fidx]["ranges"][1][0]

    def anim_sector(self, fidx):
        return self.sections[fidx]["ranges"][3][0]

    def mesh_of(self, fidx):
        data = self.package(fidx)
        sec = self.mesh_sector(fidx)
        return data, sec, meshmod.parse_block(data, sec * 2048)

    def family(self):
        """The largest set of model files sharing one exact chunk stream.

        Derived, not hard-coded - the same rule merge_studio.py uses.
        """
        groups = {}
        for fidx in sorted(set(self.files)):
            try:
                _d, _s, mr = self.mesh_of(fidx)
            except Exception:
                continue
            if "objs" not in mr or len(mr["objs"]) != mr["meshCount"]:
                continue
            sig = tuple(tuple(t for t, _p, _f in o["chunks"]) for o in mr["objs"])
            groups.setdefault(sig, []).append(fidx)
        return sorted(max(groups.values(), key=len)) if groups else []


# --------------------------------------------------------------------- topology

def part_group_of_bone(bone):
    for g in range(3):
        if appmod.PART_MASKS[g] >> bone & 1:
            return g + 1
    return 0


def walk_topology(data, mesh_base, objs):
    """The shared vertex order, and the SVECTOR slot walk that matches the merge.

    Vertices are emitted mesh object by mesh object and, inside one, chunk by
    chunk in on-disc order: a geometry chunk contributes its `nv` corner
    vertices, a seam chunk (types 8 and 9) contributes its whole pool. That is
    the same traversal `merge_reference.blend_mesh` performs, so the slot list
    built alongside lines up one-to-one with the bytes the reference blend
    touches.

    Returns a dict with the per-vertex attribute arrays, the triangle index
    buffer, the seam-pool index map and the slot walk.
    """
    joint, mobj, part, kind = [], [], [], []
    tris, tri_part = [], []
    slots = []                       # (arrayName, vertexIndex) in merge order
    seam_index = {}                  # (meshObject, poolIndex) -> vertex index
    mesh_ranges = []
    prim_tri_count = 0

    for midx, obj in enumerate(objs):
        start = len(joint)
        pool_n = 0
        for t, p, _flags in obj["chunks"]:
            if t in export_mesh.GEOM:
                nv, first, stride, posoff = export_mesh.GEOM[t]
                base = len(joint)
                for _i in range(nv):
                    joint.append(midx)
                    mobj.append(midx)
                    part.append(part_group_of_bone(midx))
                    kind.append(0)          # 0 = primitive corner
                nkind, _noff = NORMALS[t]
                if nkind == "face":
                    slots.append(("NORM", base))
                    for i in range(nv):
                        slots.append(("POSN", base + i))
                else:
                    for i in range(nv):
                        slots.append(("NORM", base + i))
                        slots.append(("POSN", base + i))
                g = part_group_of_bone(midx)
                if nv == 3:
                    tris.append((base, base + 1, base + 2))
                    tri_part.append(g)
                else:
                    tris.append((base, base + 1, base + 2))
                    tris.append((base + 1, base + 3, base + 2))
                    tri_part += [g, g]
                prim_tri_count = len(tris)
            elif t in (8, 9):
                cnt = struct.unpack_from("<I", data, p + 4)[0]
                for _k in range(cnt):
                    vi = len(joint)
                    seam_index[(midx, pool_n)] = vi
                    pool_n += 1
                    joint.append(midx)
                    mobj.append(midx)
                    part.append(part_group_of_bone(midx))
                    kind.append(1)          # 1 = seam-pool vertex
                    slots.append(("NORM", vi))
                    slots.append(("POSN", vi))
        mesh_ranges.append((start, len(joint) - start))

    # seam-stitch quads: four (bone, poolIndex) corners each
    quads = []
    for quad in export_mesh.read_stitches(data, mesh_base):
        corners = []
        for bi, vi in quad:
            gi = seam_index.get((bi, vi))
            if gi is None:
                corners = None
                break
            corners.append(gi)
        if corners is None:
            continue
        quads.append(corners)

    seam_tri_start = len(tris)
    for c in quads:
        # A seam face belongs to the swappable group of any bone it touches, so a
        # strip running into a limb hides and shows with the limb (export_gltf's rule).
        g = next((part[v] for v in c if part[v]), 0)
        tris.append((c[0], c[1], c[2]))
        tris.append((c[1], c[3], c[2]))
        tri_part += [g, g]

    return {
        "vertexCount": len(joint),
        "joint": joint, "meshObject": mobj, "partGroup": part, "kind": kind,
        "triangles": tris, "triPartGroup": tri_part,
        "primTriangleCount": prim_tri_count,
        "seamTriangleStart": seam_tri_start,
        "seamQuads": quads,
        "seamIndex": seam_index,
        "meshObjectRanges": mesh_ranges,
        "slots": slots,
    }


def read_vertex_arrays(data, objs, topo):
    """Positions, normals, UVs and texture pages of one model, in the shared order."""
    n = topo["vertexCount"]
    pos = [(0, 0, 0)] * n
    nrm = [(0, 0, 0)] * n
    uv = [(0.0, 0.0)] * n
    page = [NO_PAGE] * n
    uv_texel = [(0, 0)] * n

    cursor = 0
    for midx, obj in enumerate(objs):
        pool_n = 0
        for t, p, _flags in obj["chunks"]:
            if t in export_mesh.GEOM:
                nv, first, stride, posoff = export_mesh.GEOM[t]
                body = p + 4
                nkind, noff = NORMALS[t]
                face_n = (struct.unpack_from("<3h", data, body + noff)
                          if nkind == "face" else None)
                tex = export_mesh.TEXUV.get(t)
                tp = struct.unpack_from("<H", data, body)[0] if tex else None
                for i in range(nv):
                    blk = body + first + i * stride
                    vi = cursor + i
                    pos[vi] = struct.unpack_from("<3h", data, blk + posoff)
                    nrm[vi] = (face_n if face_n is not None
                               else struct.unpack_from("<3h", data, blk + noff))
                    if tex:
                        f2, s2, uvo = tex
                        q = body + f2 + i * s2 + uvo
                        uv_texel[vi] = (data[q], data[q + 1])
                        page[vi] = tp
                cursor += nv
            elif t in (8, 9):
                cnt = struct.unpack_from("<I", data, p + 4)[0]
                base = 4 if t == 8 else 8
                tp = (struct.unpack_from("<H", data, p + 8)[0] if t == 9 else None)
                for k in range(cnt):
                    it = p + 4 + base + k * 0x14
                    vi = topo["seamIndex"][(midx, pool_n)]
                    pool_n += 1
                    nrm[vi] = struct.unpack_from("<3h", data, it)
                    pos[vi] = struct.unpack_from("<3h", data, it + 8)
                    if t == 9:
                        uv_texel[vi] = (data[it + 0x0E], data[it + 0x0F])
                        page[vi] = tp
                    cursor += 1
    return {"pos": pos, "nrm": nrm, "uvTexel": uv_texel, "page": page, "uv": uv}


# ---------------------------------------------------------------------- textures

def build_atlas(disc, fidx, used_pages, uv_texel, page):
    """One combined RGBA atlas plus its indexed-colour description.

    Each PS1 texture page used by the model is cropped to the bounding box of the
    TIMs that land in it (unioned with the UVs that address it) and the crops are
    laid side by side, ordered by page id. Nothing is resampled: a texel keeps its
    palette index, which is what lets a hue rotation be redone on the CLUT.
    """
    data = disc.package(fidx)
    tex_sec = disc.tex_sector(fidx)
    tims = texture_atlas.collect_tims(data, tex_sec)
    shared = texture_atlas.resolve_cluts(tims)

    order = sorted(used_pages)
    uv_box = {}
    for i, tp in enumerate(page):
        if tp == NO_PAGE:
            continue
        u, v = uv_texel[i]
        b = uv_box.setdefault(tp, [255, 0, 255, 0])
        b[0] = min(b[0], u); b[1] = max(b[1], u)
        b[2] = min(b[2], v); b[3] = max(b[3], v)

    placements = {}
    for tp in order:
        px, py, mode, per_word = texture_atlas.tpage_info(tp)
        page_w, page_h = texture_atlas.PAGE_W_WORDS * per_word, texture_atlas.PAGE_H
        rects = []
        for t in tims:
            vx, vy, _vw, _vh = t["vram"]
            if t["pmode"] != mode:
                continue
            if not (px <= vx < px + texture_atlas.PAGE_W_WORDS
                    and py <= vy < py + texture_atlas.PAGE_H):
                continue
            ox, oy = (vx - px) * per_word, vy - py
            if ox + t["width"] > page_w or oy + t["height"] > page_h:
                continue
            rects.append((t, ox, oy))
        x0, y0, x1, y1 = page_w, page_h, 0, 0
        for _t, ox, oy in rects:
            x0 = min(x0, ox); y0 = min(y0, oy)
            x1 = max(x1, ox + _t["width"]); y1 = max(y1, oy + _t["height"])
        b = uv_box.get(tp)
        if b:
            x0 = min(x0, b[0]); x1 = max(x1, b[1] + 1)
            y0 = min(y0, b[2]); y1 = max(y1, b[3] + 1)
        if x1 <= x0 or y1 <= y0:
            x0, y0, x1, y1 = 0, 0, page_w, page_h
        placements[tp] = {"tims": rects, "crop": (x0, y0, x1 - x0, y1 - y0),
                          "mode": mode, "pageW": page_w, "pageH": page_h}

    atlas_w = sum(placements[tp]["crop"][2] for tp in order)
    atlas_h = max([placements[tp]["crop"][3] for tp in order] or [1])
    rgba = bytearray(atlas_w * atlas_h * 4)
    pal_plane = bytearray([NO_PALETTE]) * (atlas_w * atlas_h)
    idx_plane = bytearray(atlas_w * atlas_h)

    palettes = []                # [{key, entries}]
    pal_id = {}

    def palette_for(t):
        if not t["clut_dim"]:
            return None
        key = t["clut_dim"][:2]
        entries = t["clut"] if t["clut"] is not None else shared.get(key)
        if entries is None:
            return None
        if key not in pal_id:
            pal_id[key] = len(palettes)
            palettes.append({"vram": [key[0], key[1]], "entries": list(entries)})
        return pal_id[key]

    x_cursor = 0
    pages_meta = []
    for tp in order:
        pl = placements[tp]
        cx, cy, cw, ch = pl["crop"]
        for t, ox, oy in pl["tims"]:
            pid = palette_for(t)
            if pid is None:
                continue
            pal = palettes[pid]["entries"]
            words = t["words"]
            tw, th = t["width"], t["height"]
            for row in range(th):
                dy = oy + row - cy
                if not (0 <= dy < ch):
                    continue
                for col in range(tw):
                    dx = ox + col - cx
                    if not (0 <= dx < cw):
                        continue
                    i = row * tw + col
                    if t["pmode"] == 0:
                        b = words[i >> 1]
                        ci = (b & 0xF) if (i & 1) == 0 else (b >> 4)
                    elif t["pmode"] == 1:
                        ci = words[i]
                    else:
                        continue            # direct-colour TIMs carry no CLUT
                    o = (dy * atlas_w + x_cursor + dx)
                    pal_plane[o] = pid
                    idx_plane[o] = ci
                    c = pal[ci] if ci < len(pal) else 0
                    rgba[o * 4:o * 4 + 4] = bytes(timmod.bgr555_to_rgba(c))
        pages_meta.append({"page": tp, "x": x_cursor, "y": 0, "w": cw, "h": ch,
                           "cropX": cx, "cropY": cy, "bpp": 4 if pl["mode"] == 0
                           else 8 if pl["mode"] == 1 else 16})
        x_cursor += cw

    return {"w": atlas_w, "h": atlas_h, "rgba": bytes(rgba),
            "palettes": palettes, "palPlane": bytes(pal_plane),
            "idxPlane": bytes(idx_plane), "pages": pages_meta}


def atlas_uv(atlas, tp, u, v):
    """Texel coordinates inside a PS1 page -> normalised atlas UV."""
    for p in atlas["pages"]:
        if p["page"] == tp:
            return ((p["x"] + u - p["cropX"]) / atlas["w"],
                    (p["y"] + v - p["cropY"]) / atlas["h"])
    return (0.0, 0.0)


# ------------------------------------------------------------------- binary I/O

class SectionWriter:
    def __init__(self):
        self.sections = []

    def add(self, sid, raw, count):
        assert len(sid) == 4
        self.sections.append([sid, bytes(raw), count])

    def build(self, header_fields):
        n = len(self.sections)
        table_off = HEADER_SIZE
        data_off = table_off + n * SECTION_ENTRY
        data_off = (data_off + 3) & ~3
        body = bytearray()
        table = bytearray()
        for sid, raw, count in self.sections:
            while len(body) % 4:
                body.append(0)
            off = data_off + len(body)
            table += sid.encode("ascii") + struct.pack("<3I", off, len(raw), count)
            body += raw
        payload = bytes(table).ljust(data_off - table_off, b"\x00") + bytes(body)
        head = bytearray(HEADER_SIZE)
        struct.pack_into("<8s", head, 0, MAGIC)
        struct.pack_into("<6I", head, 8,
                         FORMAT_VERSION, HEADER_SIZE,
                         header_fields["modelFile"], header_fields["vertexCount"],
                         header_fields["boneCount"], header_fields["markerCount"])
        struct.pack_into("<5I", head, 32,
                         header_fields["stageCount"], n, table_off,
                         header_fields["flags"], zlib.crc32(payload) & 0xFFFFFFFF)
        return bytes(head) + payload


def read_family_bin(raw):
    """Parse a .family.bin back into plain Python - used by --self-test."""
    if raw[:8] != MAGIC:
        raise ValueError("not a family binary")
    (version, header_size, model_file, vcount, bcount,
     mcount) = struct.unpack_from("<6I", raw, 8)
    stage_count, nsec, table_off, flags, crc = struct.unpack_from("<5I", raw, 32)
    out = {"version": version, "modelFile": model_file, "vertexCount": vcount,
           "boneCount": bcount, "markerCount": mcount, "stageCount": stage_count,
           "flags": flags, "crc32": crc, "sections": {}}
    for i in range(nsec):
        p = table_off + i * SECTION_ENTRY
        sid = raw[p:p + 4].decode("ascii")
        off, length, count = struct.unpack_from("<3I", raw, p + 4)
        out["sections"][sid] = {"offset": off, "length": length, "count": count,
                                "bytes": raw[off:off + length]}
    def vec3s(sid, n):
        b = out["sections"][sid]["bytes"]
        return [struct.unpack_from("<3h", b, i * 6) for i in range(n)]
    out["pos"] = vec3s("POSN", vcount)
    out["nrm"] = vec3s("NORM", vcount)
    uvb = out["sections"]["TXUV"]["bytes"]
    out["uv"] = [struct.unpack_from("<2f", uvb, i * 8) for i in range(vcount)]
    pgb = out["sections"]["TPAG"]["bytes"]
    out["page"] = list(struct.unpack_from("<%dH" % vcount, pgb, 0))
    out["rest"] = vec3s("REST", bcount)
    out["rot0"] = vec3s("ROT0", bcount)
    out["root"] = struct.unpack_from("<3h", out["sections"]["ROOT"]["bytes"], 0)
    mb = out["sections"]["MARK"]["bytes"]
    out["markers"] = [struct.unpack_from("<6h", mb, i * 12) for i in range(mcount)]
    sb = out["sections"]["STGE"]["bytes"]
    stride = STAGE_STRIDE
    stages = []
    for i in range(stage_count):
        p = i * stride
        gs = list(struct.unpack_from("<3i", sb, p))
        bs = [list(struct.unpack_from("<3h", sb, p + 12 + j * 6)) for j in range(bcount)]
        fa = list(struct.unpack_from("<3h", sb, p + 12 + bcount * 6))
        fb = list(struct.unpack_from("<3h", sb, p + 18 + bcount * 6))
        mw = list(struct.unpack_from("<%di" % bcount, sb, p + 24 + bcount * 6))
        stages.append({"globalScale": gs, "boneScale": bs,
                       "partFlagsA": fa, "partFlagsB": fb, "meshWeights": mw})
    out["stages"] = stages
    fl = out["sections"]["PFLG"]["bytes"]
    out["partFlagsA"] = list(struct.unpack_from("<3h", fl, 0))
    out["partFlagsB"] = list(struct.unpack_from("<3h", fl, 6))
    return out


BONES = 25
STAGE_STRIDE = 12 + BONES * 6 + 6 + 6 + BONES * 4      # 274, see docs
STAGE_STRIDE = (STAGE_STRIDE + 3) & ~3                 # 276


# --------------------------------------------------------------------- exporting

def export_model(disc, fidx, topo, out_dirs, report):
    data, mesh_sec, mr = disc.mesh_of(fidx)
    objs = mr["objs"]
    if len(objs) != len(topo["meshObjectRanges"]):
        raise ValueError("mesh object count %d, expected %d"
                         % (len(objs), len(topo["meshObjectRanges"])))
    va = read_vertex_arrays(data, objs, topo)

    used_pages = {p for p in va["page"] if p != NO_PAGE}
    atlas = build_atlas(disc, fidx, used_pages, va["uvTexel"], va["page"])
    uv = []
    for i in range(topo["vertexCount"]):
        tp = va["page"][i]
        if tp == NO_PAGE:
            uv.append((0.0, 0.0))
        else:
            u, v = va["uvTexel"][i]
            uv.append(atlas_uv(atlas, tp, u, v))

    # ---- skeleton: rest offsets, frame-0 rotations, the animated root translation
    anim_sec = disc.anim_sector(fidx)
    blocks = animmod.parse_container(data, anim_sec * 2048)
    blk = next((b for b in blocks if b["bones"] >= BONES), None)
    if blk is None:
        raise ValueError("no animation block with >= %d bones" % BONES)
    rest = animmod.rest_offsets(data, blk)[:BONES]
    rot0 = [animmod.keyframe(data, blk, 0, b) for b in range(BONES)]
    root = animmod.root_translation(data, blk, 0)

    # ---- appearance blob: markers, growth stages, part flags
    _off, app = appmod.find(data)
    markers = (app["markers"] if app else [])[:43]
    stages = (app["stages"] if app else [])[:5]
    flags = 0
    if stages:
        flags |= 1
    if markers:
        flags |= 2

    w = SectionWriter()
    w.add("POSN", b"".join(struct.pack("<3h", *p) for p in va["pos"]),
          topo["vertexCount"])
    w.add("NORM", b"".join(struct.pack("<3h", *p) for p in va["nrm"]),
          topo["vertexCount"])
    w.add("TXUV", b"".join(struct.pack("<2f", *p) for p in uv), topo["vertexCount"])
    w.add("TPAG", struct.pack("<%dH" % topo["vertexCount"], *va["page"]),
          topo["vertexCount"])
    w.add("REST", b"".join(struct.pack("<3h", *r) for r in rest), BONES)
    w.add("ROT0", b"".join(struct.pack("<3h", *r) for r in rot0), BONES)
    w.add("ROOT", struct.pack("<3h", *root), 1)
    w.add("MARK", b"".join(struct.pack("<6h", m["id"], m["bone"], m["pos"][0],
                                       m["pos"][1], m["pos"][2], m["unk"])
                           for m in markers), len(markers))
    stage_raw = bytearray()
    for st in stages:
        rec = bytearray(STAGE_STRIDE)
        struct.pack_into("<3i", rec, 0, *st["globalScale"])
        bs = st["boneScale"]
        for j in range(BONES):
            v = bs[j] if j < len(bs) else [4096, 4096, 4096]
            struct.pack_into("<3h", rec, 12 + j * 6, *v[:3])
        struct.pack_into("<3h", rec, 12 + BONES * 6, *st["partFlagsA"])
        struct.pack_into("<3h", rec, 18 + BONES * 6, *st["partFlagsB"])
        mw = st["meshWeights"]
        struct.pack_into("<%di" % BONES, rec, 24 + BONES * 6,
                         *[(mw[j] if j < len(mw) else 0) for j in range(BONES)])
        stage_raw += rec
    w.add("STGE", stage_raw, len(stages))
    fa = stages[-1]["partFlagsA"] if stages else [3, 3, 3]
    fb = stages[-1]["partFlagsB"] if stages else [0, 0, 0]
    w.add("PFLG", struct.pack("<3h", *fa) + struct.pack("<3h", *fb), 1)

    raw = w.build({"modelFile": fidx, "vertexCount": topo["vertexCount"],
                   "boneCount": BONES, "markerCount": len(markers),
                   "stageCount": len(stages), "flags": flags})

    # round-trip check before anything hits the disk
    back = read_family_bin(raw)
    if back["pos"] != [tuple(p) for p in va["pos"]]:
        raise ValueError("re-read positions differ from the source array")
    if back["nrm"] != [tuple(p) for p in va["nrm"]]:
        raise ValueError("re-read normals differ from the source array")

    clut = {
        "model": fidx,
        "name": disc.name_of(fidx),
        "atlas": {"width": atlas["w"], "height": atlas["h"], "pages": atlas["pages"]},
        "format": "bgr555",
        "encoding": "base64/raw-u8-planes",
        "palettes": [{"id": i, "vram": p["vram"], "count": len(p["entries"]),
                      "entries": p["entries"]}
                     for i, p in enumerate(atlas["palettes"])],
        "noPalette": NO_PALETTE,
        "paletteMap": base64.b64encode(atlas["palPlane"]).decode(),
        "indexMap": base64.b64encode(atlas["idxPlane"]).decode(),
    }

    stem = "jc_%04d" % fidx
    for d, bin_ext in out_dirs:
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, stem + bin_ext), "wb").write(raw)
        timmod.write_png(os.path.join(d, stem + "_tex.png"),
                         atlas["w"], atlas["h"], atlas["rgba"])
        with open(os.path.join(d, stem + "_clut.json"), "w") as fh:
            json.dump(clut, fh, separators=(",", ":"))

    report.append({
        "file": fidx, "name": disc.name_of(fidx), "vertices": topo["vertexCount"],
        "markers": len(markers), "stages": len(stages),
        "atlas": "%dx%d" % (atlas["w"], atlas["h"]),
        "palettes": len(atlas["palettes"]),
        "bytes": len(raw), "status": "ok",
    })
    return raw


def build_family_json(disc, topo, ref_file, exported):
    names = ["bone%02d" % s for _d, s, _b, _m in disc.bones]
    return {
        "version": FORMAT_VERSION,
        "generator": "jade-cocoon-re/tools/export_family.py",
        "binaryMagic": MAGIC.decode("ascii"),
        "referenceModel": ref_file,
        "rig": {
            "address": "0x%08X" % CREATURE_RIG,
            "boneCount": len(disc.bones),
            "names": names,
            "self": [s for _d, s, _b, _m in disc.bones],
            "depth": [d for d, _s, _b, _m in disc.bones],
            "parent": [disc.parents[s] for _d, s, _b, _m in disc.bones],
            "meshObject": [m for _d, _s, _b, m in disc.bones],
        },
        "partGroups": [
            {"id": g + 1, "name": appmod.PART_NAMES[g],
             "mask": appmod.PART_MASKS[g], "bones": appmod.bones_in_group(g)}
            for g in range(3)
        ],
        "partGroupNames": list(PART_GROUP_NAMES),
        "growth": {
            "levelThresholds": disc.thresholds,
            "stageCount": 5,
            "note": "level >= thresholds[i] selects stage i (FUN_80019A80)",
        },
        "counts": {
            "vertices": topo["vertexCount"],
            "meshObjects": len(topo["meshObjectRanges"]),
            "triangles": len(topo["triangles"]),
            "primitiveTriangles": topo["primTriangleCount"],
            "seamTriangles": len(topo["triangles"]) - topo["seamTriangleStart"],
            "seamQuads": len(topo["seamQuads"]),
            "models": len(exported),
        },
        "vertex": {
            "joint": topo["joint"],
            "meshObject": topo["meshObject"],
            "partGroup": topo["partGroup"],
            "kind": topo["kind"],
        },
        "indices": [i for t in topo["triangles"] for i in t],
        "indexRanges": {
            "primitiveTriangleStart": 0,
            "primitiveTriangleCount": topo["primTriangleCount"],
            "seamTriangleStart": topo["seamTriangleStart"],
            "seamTriangleCount": len(topo["triangles"]) - topo["seamTriangleStart"],
        },
        "triPartGroup": topo["triPartGroup"],
        "seamQuads": topo["seamQuads"],
        "meshObjectRanges": [list(r) for r in topo["meshObjectRanges"]],
        "blend": {
            "formula": "dst = (0x1000*dst + w*clamp16(src-dst)) >> 12",
            "weightScale": 4096,
            "appliesTo": ["POSN", "NORM", "REST", "ROT0", "ROOT", "MARK",
                          "STGE.globalScale"],
            "rotationsAreModular": True,
            "rotationUnitsPerTurn": 4096,
        },
        "models": exported,
    }


# --------------------------------------------------------------------- self test

def self_test(disc, topo, out_dir, base=833, other=867, weight=2048):
    """Blend two exported models and compare against merge_reference's own result.

    The comparison is made at merge_reference's granularity: every SVECTOR slot
    the reference blend writes (normals and vertex positions of every primitive of
    every mesh object, plus both seam pools) is looked up in the exported arrays
    and the two numbers must agree.
    """
    print("--- self-test: %d x %d at w=%d ------------------------------"
          % (base, other, weight))
    a = read_family_bin(open(os.path.join(out_dir, "jc_%04d.family.bin" % base),
                             "rb").read())
    b = read_family_bin(open(os.path.join(out_dir, "jc_%04d.family.bin" % other),
                             "rb").read())

    # (1) round trip
    src_a = read_vertex_arrays(disc.package(base), disc.mesh_of(base)[2]["objs"], topo)
    ok_rt = (a["pos"] == [tuple(p) for p in src_a["pos"]]
             and a["nrm"] == [tuple(p) for p in src_a["nrm"]])
    print("re-read of jc_%04d.family.bin reproduces the source arrays: %s"
          % (base, "YES" if ok_rt else "NO"))

    # (2) the blend, on the exported s16 arrays
    blend_pos = [tuple(lerp_s16(a["pos"][i][c], b["pos"][i][c], weight)
                       for c in range(3)) for i in range(a["vertexCount"])]
    blend_nrm = [tuple(lerp_s16(a["nrm"][i][c], b["nrm"][i][c], weight)
                       for c in range(3)) for i in range(a["vertexCount"])]

    # (3) the same merge through merge_reference, straight off the archive bytes
    srcs = [disc.package(base), disc.package(other), disc.package(base)]
    files = [base, other, base]
    out = bytearray(srcs[0])
    mesh_secs = [disc.mesh_sector(f) for f in files]
    stage_w = []
    for s in srcs:
        _o, app = appmod.find(s)
        st = app["stages"][4] if (app and len(app["stages"]) > 4) else None
        stage_w.append(st["meshWeights"] if st else None)
    MR.blend_mesh(out, srcs, mesh_secs, stage_w, [4096 - weight, weight, 0])

    # (4) walk the reference result slot by slot in the merge's own order
    objs = meshmod.parse_block(bytes(out), mesh_secs[0] * 2048)["objs"]
    ref_slots = []
    for midx, obj in enumerate(objs):
        for t, p, _f in obj["chunks"]:
            if t in MR.GEOM_TYPES:
                for off in MR._svec_offsets(t):
                    ref_slots.append(struct.unpack_from("<3h", out, p + off))
            elif t in (8, 9):
                cnt = struct.unpack_from("<I", out, p + 4)[0]
                bse = 4 if t == 8 else 8
                for k in range(cnt):
                    d0 = p + 4 + bse + k * 0x14
                    for so in MR.SEAM_SVECS:
                        ref_slots.append(struct.unpack_from("<3h", out, d0 + so))

    mine = []
    for kind, vi in topo["slots"]:
        mine.append(blend_nrm[vi] if kind == "NORM" else blend_pos[vi])

    total = len(ref_slots)
    if total != len(mine):
        print("SLOT COUNT MISMATCH: reference %d, exported walk %d" % (total, len(mine)))
        return False
    match = sum(1 for i in range(total) if tuple(ref_slots[i]) == tuple(mine[i]))
    print("blend through the exported data matches merge_reference in %d/%d slots"
          % (match, total))

    # (5) the two end points, for good measure
    end0 = sum(1 for i, (kind, vi) in enumerate(topo["slots"])
               if tuple((a["nrm"] if kind == "NORM" else a["pos"])[vi])
               == tuple((a["nrm"] if kind == "NORM" else a["pos"])[vi]))
    diff = sum(1 for i in range(total)
               if tuple((a["nrm"] if topo["slots"][i][0] == "NORM" else a["pos"])
                        [topo["slots"][i][1]])
               != tuple((b["nrm"] if topo["slots"][i][0] == "NORM" else b["pos"])
                        [topo["slots"][i][1]]))
    print("slots that actually differ between the two parents: %d/%d" % (diff, total))
    print("--- self-test %s ------------------------------------------"
          % ("PASSED" if (match == total and ok_rt) else "FAILED"))
    return match == total and ok_rt


# -------------------------------------------------------------------------- main

def main(argv):
    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv else default

    out_dir = os.path.abspath(opt("--out", os.path.join(HERE, "..", "models", "family")))
    unity_out = opt("--unity-out")
    exe_path = opt("--exe", os.path.join(HERE, "..", "extracted", "SLES_022.01"))
    split_dir = opt("--split", os.path.join(HERE, "..", "extracted", "DATA001_split"))
    only = ([int(x) for x in opt("--only").split(",")] if opt("--only") else None)

    disc = Disc(exe_path, split_dir)
    fam = disc.family()
    print("mergeable family: %d model files" % len(fam))
    ref_file = fam[0]

    data, mesh_sec, mr = disc.mesh_of(ref_file)
    topo = walk_topology(data, mesh_sec * 2048, mr["objs"])
    print("shared topology from jc_%04d: %d vertices, %d triangles, %d seam quads, "
          "%d blend slots" % (ref_file, topo["vertexCount"], len(topo["triangles"]),
                              len(topo["seamQuads"]), len(topo["slots"])))

    out_dirs = [(out_dir, ".family.bin")]
    if unity_out:
        out_dirs.append((os.path.abspath(unity_out), ".family.bytes"))
    for d, _e in out_dirs:
        os.makedirs(d, exist_ok=True)

    targets = [f for f in fam if only is None or f in only]
    report, failures = [], []
    for fidx in targets:
        try:
            export_model(disc, fidx, topo, out_dirs, report)
            print("  jc_%04d %-16s ok" % (fidx, disc.name_of(fidx)))
        except Exception as exc:
            failures.append((fidx, str(exc)))
            report.append({"file": fidx, "name": disc.name_of(fidx),
                           "vertices": 0, "status": "FAILED: %s" % exc})
            print("  jc_%04d %-16s FAILED: %s" % (fidx, disc.name_of(fidx), exc))

    exported = [{"file": r["file"], "name": r["name"],
                 "bin": "jc_%04d.family.bin" % r["file"],
                 "bytes": "jc_%04d.family.bytes" % r["file"],
                 "texture": "jc_%04d_tex.png" % r["file"],
                 "clut": "jc_%04d_clut.json" % r["file"],
                 "status": r["status"]}
                for r in report if r["status"] == "ok"]
    fam_json = build_family_json(disc, topo, ref_file, exported)
    for d, _e in out_dirs:
        with open(os.path.join(d, "family.json"), "w") as fh:
            json.dump(fam_json, fh, separators=(",", ":"))

    with open(os.path.join(out_dir, "export_report.json"), "w") as fh:
        json.dump({"reference": ref_file, "family": fam, "models": report},
                  fh, indent=1)

    print("exported %d/%d models to %s" % (len(exported), len(targets), out_dir))
    if unity_out:
        print("  and to %s" % os.path.abspath(unity_out))
    for f, why in failures:
        print("  FAILED %d: %s" % (f, why))

    ROSTER = (833, 845, 857, 864, 872, 907)
    bad = [f for f in ROSTER if f in targets
           and f not in [e["file"] for e in exported]]
    if bad:
        print("ROSTER MODELS FAILED: %s" % (bad,))

    if "--self-test" in argv:
        ok = self_test(disc, topo, out_dir)
        return 0 if (ok and not bad) else 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
