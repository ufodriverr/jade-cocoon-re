"""Merge Studio - pick two creatures, watch the game's merge happen live.

A dependency-free local web app. The server pulls geometry, skeleton, animation
and palettes straight out of the disc image; the browser does the blend itself,
per vertex, with the same fixed-point arithmetic the PS1 runs, so the weight
slider morphs in real time.

    python merge_studio.py <exe> <splitDir> [--port 8765] [--open]

Then open http://127.0.0.1:8765/ yourself, or pass --open to have it launched.

Original code. Reads the player's own disc; ships no game data.
"""

import base64
import glob
import http.server
import json
import os
import struct
import sys
import threading
import urllib.parse
import webbrowser

import anim as animmod
import appearance as appmod
import assemble_model as AM
import export_mesh
import mesh as meshmod
import merge_reference as MR
import model_index
import texture_atlas

HERE = os.path.dirname(os.path.abspath(__file__))

CREATURE_RIG = 0x80079064      # the exe's 25-bone creature rig; the whole family uses it
PART_ID = {None: 0, "arms": 1, "wings": 2, "legs": 3, "unclaimed": 4}

# Per chunk type, where the normals live in the on-disc body:
#   ("face", off)  one normal for the whole primitive
#   ("vert", off)  one per vertex, at blockStart + off
NORMALS = {
    0: ("face", 0x04), 2: ("face", 0x04), 4: ("face", 0x04), 6: ("face", 0x04),
    1: ("vert", 0), 3: ("vert", 0), 5: ("vert", 0), 7: ("vert", 0),
}


def b64(arr, fmt):
    return base64.b64encode(struct.pack("<%d%s" % (len(arr), fmt), *arr)).decode()


# ------------------------------------------------------------------ disc access

class Disc:
    """Everything the studio needs out of one exe + split archive."""

    def __init__(self, exe_path, split_dir, index_path=None):
        self.exe = open(exe_path, "rb").read()
        self.split_dir = split_dir
        self.exe_path = exe_path
        self.records = MR.species_records(self.exe)
        self.names = MR.species_names(self.exe)
        self.files = MR.model_files(self.exe)
        self.sections = model_index.sections(self.exe)
        self.lut = AM.load_lut(self.exe)
        self.bones = AM.load_bones(self.exe, CREATURE_RIG)
        self.parents = AM.parents_from_depth(self.bones)
        self.index = {}
        self.index_path = index_path
        if index_path and os.path.exists(index_path):
            self.index = json.load(open(index_path)).get("streamed", {})
        self._pkg = {}
        # FUN_80019A80's five level thresholds; the browser maps level -> stage with them.
        self.thresholds = list(MR.exe_read(self.exe, MR.STAGE_THRESHOLDS, 5))
        self.family = self._find_family()

    def package(self, fidx):
        if fidx not in self._pkg:
            hits = glob.glob(os.path.join(self.split_dir, "%04d_*.bin" % fidx))
            if not hits:
                raise KeyError("no split file %d" % fidx)
            self._pkg[fidx] = open(hits[0], "rb").read()
        return self._pkg[fidx]

    def mesh_of(self, fidx):
        data = self.package(fidx)
        sec = self.sections[fidx]["ranges"][2][0]
        return data, sec, meshmod.parse_block(data, sec * 2048)

    def _signature(self, fidx):
        try:
            _d, _s, mr = self.mesh_of(fidx)
        except Exception:
            return None
        if "objs" not in mr or len(mr["objs"]) != mr["meshCount"]:
            return None
        return tuple(tuple(t for t, _p, _f in o["chunks"]) for o in mr["objs"])

    def _find_family(self):
        """The largest set of model files sharing one exact chunk stream.

        This is the mergeable roster and it is derived, not hard-coded: any two
        members have the same primitives in the same order, so vertex i of one is
        vertex i of the other.
        """
        groups = {}
        for fidx in self.files:
            sig = self._signature(fidx)
            if sig:
                groups.setdefault(sig, []).append(fidx)
        return set(max(groups.values(), key=len)) if groups else set()

    # ---------------------------------------------------------------- roster

    def roster(self):
        out = []
        for sid, (model, hue_base, hue_ref) in enumerate(self.records):
            if sid >= len(self.names):
                break
            if model >= len(self.files):
                continue
            fidx = self.files[model]
            out.append({
                "id": sid,
                "name": self.names[sid],
                "model": model,
                "file": fidx,
                "hue": hue_base * 2,
                "hueRef": hue_ref * 2,
                "kind": MR.species_kind(sid),
                "mergeable": fidx in self.family,
            })
        return out

    # ------------------------------------------------------------------- age

    def _ages(self, app, mesh_count):
        """The five growth stages of one model, as the browser needs them.

        `Stage` records live in the appearance blob (`MODEL+0x4C`); a minion's
        level picks one of them through FUN_80019A80. Per stage the game keeps a
        whole-body scale, a per-bone scale, the three body-part flags and a
        per-mesh-object blend weight - everything that makes a hatchling a
        hatchling rather than a shrunken adult.

        `boneScale` is flattened to 3 entries per bone SLOT id, because that is
        how both the game (FUN_80047E4C indexes it by the bone record's byte +2)
        and this app's rest-offset array are addressed.
        """
        nb = max(s for _d, s, _b3, _m in self.bones) + 1
        out = []
        for st in ((app["stages"] if app else None) or []):
            bs = [0] * (nb * 3)
            for i, v in enumerate(st["boneScale"][:nb]):
                bs[i * 3], bs[i * 3 + 1], bs[i * 3 + 2] = v
            mw = list(st["meshWeights"][:mesh_count])
            mw += [0] * (mesh_count - len(mw))
            out.append({"scale": list(st["globalScale"]), "bone": bs,
                        "flags": list(st["partFlagsA"]), "mesh": mw})
        while len(out) < 5:            # models without a stage list never re-proportion
            out.append({"scale": [4096, 4096, 4096], "bone": [4096] * (nb * 3),
                        "flags": [3, 3, 3], "mesh": [0] * mesh_count})
        return out

    # -------------------------------------------------------------- geometry

    def _prims(self, data, obj):
        """Yield (verts, normals, uvs, tpage) per primitive, in on-disc order."""
        for t, p, _flags in obj["chunks"]:
            if t not in export_mesh.GEOM:
                continue
            nv, first, stride, posoff = export_mesh.GEOM[t]
            body = p + 4
            verts, nrms = [], []
            kind, noff = NORMALS[t]
            face_n = (struct.unpack_from("<3h", data, body + noff)
                      if kind == "face" else None)
            for i in range(nv):
                blk = body + first + i * stride
                verts.append(struct.unpack_from("<3h", data, blk + posoff))
                nrms.append(face_n if face_n else
                            struct.unpack_from("<3h", data, blk + noff))
            uvs = tpage = None
            if t in export_mesh.TEXUV:
                f2, s2, uvo = export_mesh.TEXUV[t]
                uvs = [(data[body + f2 + i * s2 + uvo], data[body + f2 + i * s2 + uvo + 1])
                       for i in range(nv)]
                tpage = struct.unpack_from("<H", data, body)[0]
            yield verts, nrms, uvs, tpage

    def build_pair(self, sid_a, sid_b):
        """Geometry for two creatures in one shared vertex order.

        Both are emitted with the BASE creature's seam-quad table, because that is
        what the merge does - the result keeps source 0's stitching. Without it
        the one family member with a different quad count (file 850) would produce
        arrays the browser could not line up.
        """
        ra, rb = self.records[sid_a], self.records[sid_b]
        fa, fb = self.files[ra[0]], self.files[rb[0]]
        da, seca, mra = self.mesh_of(fa)
        db, secb, mrb = self.mesh_of(fb)
        if len(mra["objs"]) != len(mrb["objs"]):
            raise ValueError("different mesh object counts - not the same topology")

        hidden = {}
        parts, ages = [], []
        for src in (da, db):
            _o, app = appmod.find(src)
            flags = app["stages"][-1]["partFlagsA"] if (app and app["stages"]) else [3, 3, 3]
            parts.append(flags)
            ages.append(self._ages(app, len(mra["objs"])))
        # The merge ORs the groups on: a wingless parent gains its partner's wings.
        merged_flags = [max(parts[0][k], parts[1][k]) if
                        (parts[0][k] == 1 and parts[1][k] > 1) else parts[0][k]
                        for k in range(3)]
        for g, nm in enumerate(appmod.PART_NAMES):
            for bi in appmod.bones_in_group(g):
                hidden[bi] = nm

        pos = {"a": [], "b": []}
        nrm = {"a": [], "b": []}
        uv, joint, part, page, idx, mobj = [], [], [], [], [], []
        pages_used = set()
        midx_of = {slf: midx for _d, slf, _b3, midx in self.bones}

        def emit(va, na, vb, nb, uvs, tp, bone_ids, force_part=None, mobj_ids=None):
            base = len(joint)
            for i in range(len(va)):
                pos["a"] += list(va[i]); nrm["a"] += list(na[i])
                pos["b"] += list(vb[i]); nrm["b"] += list(nb[i])
                u, v = uvs[i] if uvs else (0, 0)
                uv.append(u); uv.append(v)
                bi = bone_ids[i]
                joint.append(bi)
                # A face belongs to the swappable group of any bone it touches, so a
                # seam strip running into a limb hides and shows along with the limb.
                grp = force_part if force_part is not None else \
                    PART_ID[hidden.get(next((b for b in bone_ids if b in hidden), None))]
                part.append(grp)
                page.append(tp if tp is not None else 0xFFFF)
                # Which mesh object the vertex came from: a growth stage can carry a
                # per-mesh-object weight that overrides the global one for that part.
                mobj.append(mobj_ids[i] if mobj_ids else
                            max(0, min(255, midx_of.get(bi, 0))))
            if tp is not None:
                pages_used.add(tp)
            if len(va) == 3:
                idx.extend([base, base + 1, base + 2])
            else:
                idx.extend([base, base + 1, base + 2, base + 1, base + 3, base + 2])

        claimed = set()
        for _d, slf, _b3, midx in self.bones:
            if not (0 <= midx < len(mra["objs"])):
                continue
            claimed.add(midx)
            pa = list(self._prims(da, mra["objs"][midx]))
            pb = list(self._prims(db, mrb["objs"][midx]))
            for (va, na, uvs, tp), (vb, nb, _u2, _t2) in zip(pa, pb):
                emit(va, na, vb, nb, uvs, tp, [slf] * len(va),
                     mobj_ids=[midx] * len(va))

        root = self.bones[0][1]
        for midx in range(len(mra["objs"])):
            if midx in claimed:
                continue
            pa = list(self._prims(da, mra["objs"][midx]))
            pb = list(self._prims(db, mrb["objs"][midx]))
            for (va, na, uvs, tp), (vb, nb, _u2, _t2) in zip(pa, pb):
                emit(va, na, vb, nb, uvs, tp, [root] * len(va),
                     force_part=PART_ID["unclaimed"], mobj_ids=[midx] * len(va))

        pool_a = {slf: export_mesh.seam_pool_full(da, mra["objs"][midx])
                  for _d, slf, _b3, midx in self.bones if 0 <= midx < len(mra["objs"])}
        pool_b = {slf: export_mesh.seam_pool_full(db, mrb["objs"][midx])
                  for _d, slf, _b3, midx in self.bones if 0 <= midx < len(mrb["objs"])}
        for quad in export_mesh.read_stitches(da, seca * 2048):
            va, na, vb, nb, uvs, bones_i, tps = [], [], [], [], [], [], set()
            ok = True
            for bi, vi in quad:
                A, B = pool_a.get(bi), pool_b.get(bi)
                if A is None or B is None or vi >= len(A) or vi >= len(B):
                    ok = False
                    break
                va.append(A[vi]["pos"]); na.append(A[vi]["nrm"])
                vb.append(B[vi]["pos"]); nb.append(B[vi]["nrm"])
                uvs.append(A[vi]["uv"]); bones_i.append(bi); tps.add(A[vi]["tpage"])
            if not ok:
                continue
            tp = next(iter(tps)) if (len(tps) == 1 and all(u for u in uvs)) else None
            emit(va, na, vb, nb, uvs if tp is not None else None, tp, bones_i)

        atlases_a = texture_atlas.build(da, self.sections[fa]["ranges"][1][0],
                                        sorted(pages_used))
        atlases_b = texture_atlas.build(db, self.sections[fb]["ranges"][1][0],
                                        sorted(pages_used))
        order = sorted(pages_used)
        page_ix = {tp: i for i, tp in enumerate(order)}
        wh = {tp: (atlases_a[tp]["w"], atlases_a[tp]["h"]) for tp in order}
        uvn = []
        for i in range(len(joint)):
            tp = page[i]
            w, h = wh.get(tp, (1, 1))
            uvn += [uv[i * 2] / w, uv[i * 2 + 1] / h]
        # Group the triangles by texture page so the browser can draw each atlas in one
        # call. Only the index buffer is reordered - the vertex arrays keep the order
        # both parents were emitted in, which is what lets the blend line them up.
        tris = [idx[i:i + 3] for i in range(0, len(idx), 3)]
        tris.sort(key=lambda t: page_ix.get(page[t[0]], -1))
        draws, flat = [], []
        cur, start = object(), 0
        for t in tris:
            pi = page_ix.get(page[t[0]], -1)
            if pi != cur:
                if flat:
                    draws.append({"page": cur, "start": start, "count": len(flat) - start})
                cur, start = pi, len(flat)
            flat.extend(t)
        if flat:
            draws.append({"page": cur, "start": start, "count": len(flat) - start})
        idx = flat

        def pack_pages(atl):
            return [{"id": tp, "w": atl[tp]["w"], "h": atl[tp]["h"],
                     "png": base64.b64encode(texture_atlas.png_bytes(atl[tp])).decode()}
                    for tp in order]

        return {
            "a": self._info(sid_a), "b": self._info(sid_b),
            "rig": {"parent": [self.parents[s] for _d, s, _b, _m in self.bones],
                    "self": [s for _d, s, _b, _m in self.bones]},
            "counts": {"verts": len(joint), "tris": len(idx) // 3},
            "geom": {"uv": b64(uvn, "f"), "joint": b64(joint, "B"),
                     "part": b64(part, "B"), "idx": b64(idx, "H"),
                     "mobj": b64(mobj, "B")},
            "draws": draws,
            "pos": {"a": b64(pos["a"], "h"), "b": b64(pos["b"], "h")},
            "nrm": {"a": b64(nrm["a"], "h"), "b": b64(nrm["b"], "h")},
            "pages": {"a": pack_pages(atlases_a), "b": pack_pages(atlases_b)},
            "parts": {"a": parts[0], "b": parts[1], "merged": merged_flags},
            "ages": {"a": ages[0], "b": ages[1], "thresholds": self.thresholds},
            "anim": self.animation(fa, fb),
        }

    def export_glb(self, sid_a, sid_b, weight, texsrc="a", hue=0, stage=4):
        """Write the blend the browser is showing as a real GLB, via the same
        reference implementation the command line uses."""
        fa = self.files[self.records[sid_a][0]]
        fb = self.files[self.records[sid_b][0]]
        tex = fa if texsrc == "a" else fb
        slots = MR.streamed_slots(self.index_path, fa, len(self.bones))
        pkg, ms, asec, ts, _notes = MR.build_merged_package(
            self.exe, self.split_dir, [fa, fb], [4096 - weight, weight],
            stage, tex, hue, True, slots)
        out_dir = os.path.join(os.path.dirname(self.split_dir.rstrip("/\\")),
                               "Models", "merged")
        os.makedirs(out_dir, exist_ok=True)
        name = "studio_%s_x_%s_%d%s%s.glb" % (
            self.names[sid_a], self.names[sid_b], round(weight * 100 / 4096),
            ("_hue%d" % hue) if hue else "",
            ("_stage%d" % stage) if stage != 4 else "")
        out = os.path.abspath(os.path.join(out_dir, name.replace(" ", "")))
        MR.export_glb(self.exe_path, pkg, ms, asec, ts, out, slots=slots)
        print("wrote " + out)
        return out

    def _info(self, sid):
        model, hb, hr = self.records[sid]
        return {"id": sid, "name": self.names[sid] if sid < len(self.names) else "?",
                "model": model, "file": self.files[model],
                "hue": hb * 2, "hueRef": hr * 2, "kind": MR.species_kind(sid)}

    # ------------------------------------------------------------- animation

    def _blocks(self, fidx):
        data = self.package(fidx)
        sec = self.sections[fidx]["ranges"][3][0]
        slots = [b["sector"] for b in self.index.get(str(fidx), [])
                 if b["bones"] >= len(self.bones)]
        return data, animmod.load_set(data, sec, slots)

    def animation(self, fa, fb):
        """Clips and rest pose. Clips come from the base; both rest poses are sent
        so the browser can blend bone lengths the way FUN_8004A520 does."""
        da, blocks_a = self._blocks(fa)
        db, blocks_b = self._blocks(fb)
        if not blocks_a or not blocks_b:
            return None
        nb = len(self.bones)
        rest_a = animmod.rest_offsets(da, blocks_a[0])
        rest_b = animmod.rest_offsets(db, blocks_b[0])
        clips = []
        for i, blk in enumerate(blocks_a):
            if blk["bones"] < nb:
                continue
            stride = blk["bones"] + 2
            keys = []
            for f in range(blk["frames"]):
                keys += list(animmod.extra(da, blk, f, 1))          # root translation
                for _d, slf, _b3, _m in self.bones:
                    keys += list(animmod.keyframe(da, blk, f, slf))
            clips.append({"name": "clip%02d_%df" % (i, blk["frames"]),
                          "frames": blk["frames"], "bones": nb,
                          "keys": b64(keys, "h")})
        flat = lambda r: [c for v in r[:nb] for c in v]
        return {"restA": b64(flat(rest_a), "h"), "restB": b64(flat(rest_b), "h"),
                "clips": clips}


# --------------------------------------------------------------------- server

class Handler(http.server.BaseHTTPRequestHandler):
    disc = None

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path in ("/", "/index.html"):
                page = open(os.path.join(HERE, "merge_studio.html"), "rb").read()
                return self._send(200, page, "text/html; charset=utf-8")
            if u.path == "/api/roster":
                return self._send(200, json.dumps(self.disc.roster()), "application/json")
            if u.path.startswith("/api/pair/"):
                a, b = (int(x) for x in u.path[len("/api/pair/"):].split("/"))
                data = self.disc.build_pair(a, b)
                return self._send(200, json.dumps(data), "application/json")
            if u.path == "/api/glb":
                q = urllib.parse.parse_qs(u.query)
                out = self.disc.export_glb(
                    int(q["a"][0]), int(q["b"][0]), int(q.get("w", ["2048"])[0]),
                    q.get("tex", ["a"])[0], int(q.get("hue", ["0"])[0]),
                    max(0, min(4, int(q.get("stage", ["4"])[0]))))
                return self._send(200, json.dumps({"path": out}), "application/json")
        except Exception as exc:            # surface the reason in the browser
            import traceback
            traceback.print_exc()
            return self._send(500, json.dumps({"error": str(exc)}), "application/json")
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        """`POST /api/shot?name=foo` saves a PNG the page hands back.

        The page posts a bare data: URL; useful for keeping a picture of a blend
        without leaving the browser.
        """
        u = urllib.parse.urlparse(self.path)
        if u.path != "/api/shot":
            return self._send(404, "not found", "text/plain")
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode("ascii", "ignore")
        if "," in body:
            body = body.split(",", 1)[1]
        name = urllib.parse.parse_qs(u.query).get("name", ["shot"])[0]
        name = "".join(c for c in name if c.isalnum() or c in "-_.") or "shot"
        out = os.path.join(HERE, name + ".png")
        with open(out, "wb") as fh:
            fh.write(base64.b64decode(body))
        print("wrote " + out)
        self._send(200, json.dumps({"path": out}), "application/json")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    exe_path, split_dir = sys.argv[1], sys.argv[2]
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8765
    index = (sys.argv[sys.argv.index("--index") + 1] if "--index" in sys.argv else
             os.path.join(os.path.dirname(split_dir.rstrip("/\\")), "rig_anim_index.json"))
    print("reading the disc...")
    Handler.disc = Disc(exe_path, split_dir, index)
    print("mergeable family: %d model files, %d named species"
          % (len(Handler.disc.family),
             sum(1 for r in Handler.disc.roster() if r["mergeable"])))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d/" % port
    print("serving " + url + "   (ctrl-c to stop)")
    if "--open" in sys.argv:            # only pop a browser when actually asked
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
