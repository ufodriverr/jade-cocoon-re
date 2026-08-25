"""Export EVERY Jade Cocoon creature model, not just the 16 in the exe descriptor table.

The exe's descriptor table at 0x800823F0 only names 16 models (files 833-848), which is
what `export_all.py` drives off. Scanning the whole archive for valid mesh blocks instead
finds 106 files (mostly 831-933) holding 104 distinct meshes - the full creature roster.

A model file names neither its rig nor its animation set, so both have to be inferred.
Matching on bone count alone is wrong: model 831 has 23 mesh objects but is really a
22-bone model, so it picked up a 23-bone rig and a 23-bone animation from an unrelated
creature and exported mangled. Candidates are now SCORED by how well the stitch quads
close (see rigfit.py) and the best pairing wins; a model whose best score is still poor is
exported as unrigged geometry rather than with a skeleton that is visibly wrong.

Also writes an `appearance.json` sidecar with the growth stages, per-bone scales, body-part
flags and attachment markers from the model's appearance blob (see appearance.py).

Output is named after the creature, not just the file: `jc_0845_Marrdreg.glb`. The index
stays in front because it is the disc's own identity for the model and every note in the
docs cites it; the name comes from `model_names.py`, and the seven files neither the
species table nor a scene package names keep the bare `jc_NNNN` stem.

Usage:
    python export_every.py <exe> <split_dir> <out_dir> [--only A-B] [--jobs N]
Needs `rig_anim_index.json` next to the split dir (see build_index.py).
"""
import glob
import hashlib
import json
import os
import struct
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

import anim as animmod
import appearance as appmod
import assemble_model as AM
import export_mesh
import mesh as meshmod
import model_names
import rigfit
from export_all import find_tex

HERE = os.path.dirname(os.path.abspath(__file__))

# Median stitch-quad extent, in game units, above which a rig/rest-pose pairing is not
# believable. A correct assembly scores ~30-90 (model 833 scores 52.7, matching the 53
# recorded in MODEL_FORMAT); the wrong-rig export of 831 scored 121.
FIT_LIMIT = 125.0
MAX_ANIM_SOURCES = 10
# Cap on streamed clips per model. 831/832 own ~200 and ~370 of them; the whole set is
# real data, but a 200-action GLB is unwieldy, so the export takes the lowest animation
# ids and `animSlotsTotal` in the report records how many were left behind.
MAX_ANIMS = 48
# How many mesh objects a candidate rig may leave unclaimed. See choose_rig_and_anim.
MESH_SLACK = 3
# Creature packages live from ~600 up. The low indices are UI and system overlays, and
# their animation containers are not skeletons - model 931 borrowed a 20-bone set from
# overlay 21 and scored BETTER (110) than model 930 did with a genuinely correct rig
# (113), so bone count and fit alone cannot separate them. Provenance can.
ANIM_FILE_MIN = 600


def scan_meshes(data):
    """Every sector-aligned mesh block in a package, largest first."""
    out = []
    for sec in range(len(data) // 2048):
        base = sec * 2048
        if base + 0x30 > len(data):
            break
        total, mc, _u1, u2 = struct.unpack_from("<4I", data, base)
        if not (1 <= mc <= 200):
            continue
        if not (0x10 < u2 <= len(data) - base) or u2 & 3:
            continue
        counts = struct.unpack_from("<10I", data, base + 0x10)
        if any(c > 20000 for c in counts) or sum(counts) == 0:
            continue
        r = meshmod.parse_block(data, base)
        if r.get("consumed") == r["u2"] and len(r.get("objs", [])) == mc:
            out.append((sec, mc, total))
    out.sort(key=lambda t: -t[1])
    return out


def distinct_rigs(index, exe_path, split_dir):
    """Deduplicate the index's bone tables by content: 244 tables, only ~20 distinct."""
    seen, out = {}, []
    bufs = {"exe": open(exe_path, "rb").read()}
    for r in index["rigs"]:
        key = r.get("file", "exe")
        if key not in bufs:
            m = glob.glob(os.path.join(split_dir, "%04d_*.bin" % key))
            if not m:
                continue
            bufs[key] = open(m[0], "rb").read()
        raw = bufs[key][r["off"]:r["off"] + (r["bones"] + 1) * 8]
        h = hashlib.md5(raw).hexdigest()
        if h in seen:
            continue
        seen[h] = True
        path = exe_path if key == "exe" else glob.glob(
            os.path.join(split_dir, "%04d_*.bin" % key))[0]
        spec = ("0x%X" % (0x80010000 + r["off"] - 0x800) if key == "exe"
                else "%s@0x%X" % (path, r["off"]))
        out.append({"spec": spec, "src": key, "off": r["off"], "bones": r["bones"],
                    "table": rigfit.read_rig(bufs[key], r["off"])})
    return out


def choose_rig_and_anim(lut, data, fidx, mesh_sec, mr, rigs, index, split_dir, cache):
    """Score every plausible (rig, animation source) pairing; return the best."""
    nmesh = len(mr["objs"])
    # The rig must account for essentially the whole mesh block, but "one spare mesh
    # object" was too tight. Model 849 has 24 mesh objects and carries its OWN 22-bone,
    # 4-animation container - the very set 22 other models borrow - yet 24 - 22 = 2
    # failed the old test, so it took a 23-bone rig from file 408 and 835's animations
    # instead. MESH_SLACK is the number of mesh objects a rig may leave unclaimed;
    # widening it is safe because a candidate rig still has to find an animation source
    # with its exact bone count, and own-file sources are tried first (see sweep).
    cands = [r for r in rigs
             if all(0 <= m < nmesh for _d, _s, _b3, m in r["table"])
             and len({m for _d, _s, _b3, m in r["table"]}) == len(r["table"])
             and 0 <= nmesh - len(r["table"]) <= MESH_SLACK]
    if not cands:
        return None

    def fits(clip_bones, nbones, own):
        """Can a clip with `clip_bones` bones drive a rig of `nbones` bones?

        The renderer (FUN_80047E4C) walks the RIG's records and indexes the clip by each
        record's `self` byte using the CLIP's own stride, so the two counts are independent
        as long as the clip is at least as long as the rig. Model 870 has 26 mesh objects
        and 26-bone clips of its own, and on a 23-bone rig those clips score 53 - the same
        band as a known-correct assembly - against 95 for the 25-bone rig it was borrowing.

        Only allowed for a model's OWN clips. Borrowing still demands an exact match: a
        foreign clip of a different length is a different skeleton, and the wider net would
        let a creature's 25-bone set drive a humanoid.
        """
        return clip_bones >= nbones if own else clip_bones == nbones

    def slots_for(fi, nbones):
        """Streamed animation slots of file `fi` that can drive an `nbones` rig."""
        own = fi == fidx
        return [b["sector"] for b in index["streamed"].get(str(fi), [])
                if fits(b["bones"], nbones, own)][:MAX_ANIMS]

    def anim_sources(nbones):
        # Exact bone count only: the rest pose lives in the animation block header, so a
        # container with a different bone count describes a different skeleton.
        # "primary" = the container the exe's own model descriptor table points at.
        # Without it, files 831/832's deep 120-frame cutscene containers outscored their
        # real 5-animation sets by a fraction of a point and pulled 20 NPCs with them.
        srcs = [{"file": a["file"], "sector": a["sector"],
                 "slots": slots_for(a["file"], nbones)}
                for a in index["anims"]
                if fits(a["bones"], nbones, a["file"] == fidx)
                and a["file"] >= ANIM_FILE_MIN and a.get("primary")]
        # Most models keep most of their animations OUT of the resident container, in the
        # per-animation streamed slot table (model_anims.py). A model whose resident
        # container is an empty sector - every humanoid NPC - has a source only here, and
        # it is the one that carries its own rest pose.
        have = {a["file"] for a in srcs}
        for key in index["streamed"]:
            fi = int(key)
            if fi < ANIM_FILE_MIN or fi in have:
                continue
            sl = slots_for(fi, nbones)
            if sl:
                srcs.append({"file": fi, "sector": -1, "slots": sl})
        srcs.sort(key=lambda a: (a["file"] != fidx, abs(a["file"] - fidx)))
        return srcs[:MAX_ANIM_SOURCES]

    def load(fi):
        if fi not in cache:
            m = glob.glob(os.path.join(split_dir, "%04d_*.bin" % fi))
            cache[fi] = open(m[0], "rb").read() if m else None
        return cache[fi]

    fallback = [None]

    def sweep(own_only):
        """Best (rig, animation) pairing over every candidate rig."""
        best = None
        for rig in cands:
            par = AM.parents_from_depth(rig["table"])
            for a in anim_sources(rig["bones"]):
                if own_only and a["file"] != fidx:
                    continue
                adata = load(a["file"])
                if adata is None:
                    continue
                blks = animmod.load_set(adata, a["sector"], a["slots"])
                if not blks:
                    continue
                pick = {"rig": rig, "animFile": a["file"], "animSector": a["sector"],
                        "slots": a["slots"], "anims": len(blks)}
                s = rigfit.score(lut, data, mesh_sec, mr, rig["table"], par, adata,
                                 blks[0])
                if s is None:
                    # Not every model has stitch records, and without them there is
                    # nothing to score. Keep the first bone-count match as a fallback.
                    if fallback[0] is None:
                        fallback[0] = dict(pick, score=None)
                    continue
                if best is None or s < best["score"]:
                    best = dict(pick, score=s)
        return best

    # A model's own animation set is authoritative, so try it across every candidate rig
    # first and only look elsewhere if nothing of its own is believable. Without this a
    # sibling creature wins by a point or two and the export is silently posed by the
    # wrong data - model 833 was picking up 852's rest pose that way.
    own = sweep(True)
    if own is not None and own["score"] <= FIT_LIMIT:
        return own
    return sweep(False) or own or fallback[0]


def anim_stats(adata, sector, prefix, slots=()):
    """Per-animation: does it actually move? Answers "why do some do nothing".

    Every multi-frame block in the archive genuinely animates; the only static ones are
    the single-frame blocks, which are poses (the 25-bone family ships two of those and
    six motions). Recorded so the question does not have to be asked again.
    """
    out = []
    for i, blk in enumerate(animmod.load_set(adata, sector, slots)):
        base = [animmod.keyframe(adata, blk, 0, j) for j in range(blk["bones"])]
        t0 = animmod.root_translation(adata, blk, 0)
        rot = tr = 0
        for f in range(blk["frames"]):
            for j in range(blk["bones"]):
                k = animmod.keyframe(adata, blk, f, j)
                rot = max(rot, max(abs(k[c] - base[j][c]) for c in range(3)))
            t = animmod.root_translation(adata, blk, f)
            tr = max(tr, max(abs(t[c] - t0[c]) for c in range(3)))
        kind = "pose" if blk["frames"] == 1 else "anim"
        out.append({"name": "%s%s%02d_%df" % (prefix, kind, i, blk["frames"]),
                    "frames": blk["frames"], "maxRotDelta": rot, "maxRootMove": tr,
                    "moves": bool(rot or tr)})
    return out


def export_static(pkg, fidx, stem, mesh_sec, out_dir, why):
    """No believable rig: still emit the raw geometry as an unrigged OBJ."""
    out = os.path.join(out_dir, "%s_static.obj" % stem)
    r = subprocess.run([sys.executable, os.path.join(HERE, "export_mesh.py"),
                        pkg, str(mesh_sec), out],
                       capture_output=True, text=True, cwd=HERE)
    if r.returncode != 0:
        return fidx, "fail", (r.stderr.strip().splitlines() or ["?"])[-1], {}
    return fidx, "static", "%s - unrigged OBJ" % why, {"reason": why}


def export_one(args):
    exe_path, split_dir, out_dir, pkg, fidx, stem, rigs, index = args
    data = open(pkg, "rb").read()
    blocks = scan_meshes(data)
    if not blocks:
        return fidx, "skip", "no mesh block", {}
    mesh_sec, nmesh, _tot = blocks[0]

    lut = AM.load_lut(open(exe_path, "rb").read())
    mr = meshmod.parse_block(data, mesh_sec * 2048)
    cache = {fidx: data}
    pick = choose_rig_and_anim(lut, data, fidx, mesh_sec, mr, rigs, index, split_dir, cache)
    if pick is None:
        return export_static(pkg, fidx, stem, mesh_sec, out_dir,
                             "no rig fits %d meshes" % nmesh)
    if pick["score"] is not None and pick["score"] > FIT_LIMIT:
        return export_static(pkg, fidx, stem, mesh_sec, out_dir,
                             "best rig fit %.0f > %.0f" % (pick["score"], FIT_LIMIT))

    anim_pkg = cache[pick["animFile"]] and glob.glob(
        os.path.join(split_dir, "%04d_*.bin" % pick["animFile"]))[0]
    tex_sec = find_tex(data, [fidx])
    out = os.path.join(out_dir, "%s.glb" % stem)
    cmd = [sys.executable, os.path.join(HERE, "export_gltf.py"), exe_path, pkg,
           str(mesh_sec), str(pick["animSector"]), pick["rig"]["spec"], out,
           "--name", "jc%04d_" % fidx, "--root", stem]
    if tex_sec is not None:
        cmd += ["--tex", str(tex_sec)]
    if pick["animFile"] != fidx:
        cmd += ["--animpkg", anim_pkg]
    if pick.get("slots"):
        cmd += ["--animslots", ",".join(str(s) for s in pick["slots"])]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    if r.returncode != 0:
        return fidx, "fail", (r.stderr.strip().splitlines() or ["?"])[-1], {}

    _off, app = appmod.find(data)
    if app:
        with open(os.path.join(out_dir, "%s.appearance.json" % stem), "w") as fh:
            json.dump(app, fh, indent=1)
    note = "%d meshes, %d-bone rig %s, %d anims" % (
        nmesh, pick["rig"]["bones"], pick["rig"]["spec"], pick["anims"])
    if pick["animFile"] != fidx:
        note += " from %04d" % pick["animFile"]
    note += ", fit %s" % ("%.0f" % pick["score"] if pick["score"] is not None
                          else "n/a (no stitches)")
    if tex_sec is None:
        note += ", NO TEXTURES"
    if app:
        note += ", %d stages" % app["stageCount"]
    adata = data if pick["animFile"] == fidx else open(anim_pkg, "rb").read()
    claimed = {m for _d, _s, _b3, m in pick["rig"]["table"]}
    unclaimed = [m for m in range(nmesh) if m not in claimed]
    # How much of the skeleton the fit score actually looked at. `rigfit` measures whether
    # seams close, so it can only judge bones that appear in a stitch quad - model 840
    # scores a healthy 68 while covering 12 of its 40 bones, and every bone the score
    # never saw is one of the limbs that come out visibly detached. A low ratio means the
    # fit number is not evidence of anything.
    stitch_bones = {bi for quad in export_mesh.read_stitches(data, mesh_sec * 2048)
                    for bi, _vi in quad}
    nbones = pick["rig"]["bones"]
    if len(stitch_bones) < nbones * 0.5:
        note += ", fit covers only %d/%d bones" % (len(stitch_bones), nbones)
    hidden = ([n for n, v in app["hasPart"].items() if not v] if app and app["stages"]
              else [])
    if unclaimed:
        note += ", %d unclaimed mesh obj" % len(unclaimed)
    if hidden:
        note += ", hides %s" % "/".join(hidden)
    total_slots = len([b for b in index["streamed"].get(str(pick["animFile"]), [])
                       if b["bones"] >= pick["rig"]["bones"]])
    info = {"animStats": anim_stats(adata, pick["animSector"], "jc%04d_" % fidx,
                                    pick.get("slots", [])),
            "animSlots": len(pick.get("slots", [])), "animSlotsTotal": total_slots,
            "unclaimedMeshes": unclaimed, "hiddenParts": hidden,
            "fitBones": len(stitch_bones), "fitBonesOf": nbones,
            "animTableCount": app["animTableCount"] if app else 0,
            "meshes": nmesh, "meshSector": mesh_sec, "rigBones": pick["rig"]["bones"],
            "rig": pick["rig"]["spec"], "animFile": pick["animFile"],
            "animSector": pick["animSector"], "anims": pick["anims"],
            "animBorrowed": pick["animFile"] != fidx, "fit": pick["score"],
            "textured": tex_sec is not None, "stages": app["stageCount"] if app else 0}
    return fidx, "ok", note, info


def main():
    exe_path, split_dir, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    lo, hi = 0, 9999
    if "--only" in sys.argv:
        lo, hi = (int(x) for x in sys.argv[sys.argv.index("--only") + 1].split("-"))
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 8
    os.makedirs(out_dir, exist_ok=True)

    ipath = os.path.join(os.path.dirname(split_dir), "rig_anim_index.json")
    index = json.load(open(ipath))
    names = model_names.resolve(open(exe_path, "rb").read(), split_dir)
    print("names: %d of the model files are named by the disc" % len(names))
    rigs = distinct_rigs(index, exe_path, split_dir)
    print("index: %d bone tables -> %d distinct rigs (%s bones), %d animation containers"
          % (len(index["rigs"]), len(rigs), sorted({r["bones"] for r in rigs}),
             len(index["anims"])))

    todo = []
    for pkg in sorted(glob.glob(os.path.join(split_dir, "*.bin"))):
        fidx = int(os.path.basename(pkg)[:4])
        if not (lo <= fidx <= hi):
            continue
        if scan_meshes(open(pkg, "rb").read()):
            todo.append((pkg, fidx))
    print("%d files carry a mesh block" % len(todo))

    stems = {fidx: model_names.stem(fidx, names) for _pkg, fidx in todo}
    work = [(exe_path, split_dir, out_dir, pkg, fidx, stems[fidx], rigs, index)
            for pkg, fidx in todo]
    tally, report = {}, {}
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for fidx, status, note, info in ex.map(export_one, work):
            named = names.get(fidx, {})
            print("%4d  %-12s %-6s %s" % (fidx, named.get("name", "-"), status, note))
            tally[status] = tally.get(status, 0) + 1
            report["%04d" % fidx] = dict(info, status=status, note=note,
                                         name=named.get("name"),
                                         nameSource=named.get("source"),
                                         stem=stems[fidx])
    with open(os.path.join(out_dir, "export_report.json"), "w") as fh:
        json.dump(report, fh, indent=1, sort_keys=True)
    borrowed = sorted(k for k, v in report.items() if v.get("animBorrowed"))
    print("\n%s -> %s" % (", ".join("%d %s" % (v, k) for k, v in sorted(tally.items())),
                          out_dir))
    print("%d models use another file's rest pose: %s" % (len(borrowed), " ".join(borrowed)))


if __name__ == "__main__":
    main()
