"""Batch-export every Jade Cocoon model to a rigged, animated, textured GLB.

Drives off the exe's model descriptor table (0x800823F0) to find each model file.
NOTE: that table has 103 entries, not the 16 this script was written against - `model_index`
no longer truncates it, so this now walks every model file. `export_every.py` is the current
path; keep this one only for the descriptor-driven cross-check.
and its sector ranges, classifies those ranges as MESH / TIM / ANIM, then finds a
matching rig.

Rig discovery: a bone table is a run of 8-byte records with a sequential self
index, a depth that never jumps by more than +1, terminated by s16 -1. A table
matches a model when its bone count equals the model's mesh count AND every
meshIndex is in range. Most rigs are in the exe, but the larger creatures keep
theirs in the actor overlay packages (model 838's 37-bone rig is in file 0467,
model 840's 40-bone rig in file 0422).

Usage:
    python export_all.py <exe> <split_dir> <out_dir>
"""
import glob
import os
import struct
import subprocess
import sys

import anim as animmod
import mesh as meshmod
import model_index as MI
import model_names
import tim


def scan_bone_tables(buf, min_bones=4):
    """Find bone-table candidates in a buffer."""
    out = []
    n = len(buf)
    i = 0
    while i + 8 * min_bones <= n:
        k, prev, ok = 0, -1, True
        while i + k * 8 + 8 <= n:
            depth = struct.unpack_from("<h", buf, i + k * 8)[0]
            if depth == -1:
                break
            if buf[i + k * 8 + 2] != k or depth < 0 or depth > 40 or depth > prev + 1:
                ok = False
                break
            prev = max(prev, depth)
            k += 1
            if k > 250:
                ok = False
                break
        if ok and k >= min_bones:
            out.append((i, k))
            i += k * 8
        else:
            i += 1
    return out


def rig_matches(buf, off, nmesh):
    """True if the table at off is a plausible rig for a model with nmesh meshes."""
    bones = []
    p = off
    while True:
        depth, slf, _b3, midx, _x = struct.unpack_from("<hBBhh", buf, p)
        if depth == -1:
            break
        bones.append(midx)
        p += 8
        if len(bones) > 300:
            return False
    if len(bones) != nmesh:
        return False
    return all(0 <= m < nmesh for m in bones) and len(set(bones)) == nmesh


def find_mesh(data):
    """Sector of the model's MAIN mesh block (the one with the most parts).

    Several packages hold more than one mesh block - file 833 has a 12-part block
    at sector 0 as well as the real 25-part body at sector 20 - so pick the largest
    rather than the first.
    """
    best = None
    for sec in range(len(data) // 2048):
        base = sec * 2048
        if base + 16 > len(data):
            break
        total, mc, _u1, u2 = struct.unpack_from("<4I", data, base)
        if not (1 <= mc <= 200 and 16 < u2 <= total <= (len(data) - base)):
            continue
        r = meshmod.parse_block(data, base)
        if "objs" not in r or r.get("failed_at") is not None or "consumed" not in r:
            continue
        if r["consumed"] != u2 or len(r["objs"]) != mc:
            continue
        if best is None or mc > best[1]:
            best = (sec, mc)
    return best[0] if best else None


def find_anim(data, want_bones):
    """Sector of an animation container whose blocks tile exactly."""
    for sec in range(len(data) // 2048):
        blks = animmod.parse_container(data, sec * 2048)
        if not blks:
            continue
        cnt = struct.unpack_from("<I", data, sec * 2048)[0]
        if len(blks) != cnt:
            continue
        gaps = sum(1 for i in range(len(blks) - 1)
                   if blks[i]["off"] + blks[i]["size"] != blks[i + 1]["off"])
        if gaps == 0 and blks[0]["bones"] == want_bones:
            return sec
    return None


def find_tex(data, vals):
    """Sector of the texture container, from the descriptor ranges."""
    for start, size in MI.ranges_from(vals):
        kind, _info = MI.classify(data, start, size)
        if kind == "TIM":
            return start
    for sec in range(len(data) // 2048):
        kind, _i = MI.classify(data, sec, 1)
        if kind == "TIM":
            return sec
    return None


def main():
    exe_path, split_dir, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    exe = open(exe_path, "rb").read()
    os.makedirs(out_dir, exist_ok=True)
    creature = model_names.resolve(exe, split_dir)

    # build a rig catalogue once: exe first, then the actor packages
    sources = [("exe", exe_path, exe)]
    for f in sorted(glob.glob(os.path.join(split_dir, "*"))):
        if os.path.isdir(f):
            continue
        idx = int(os.path.basename(f)[:4])
        if 100 <= idx <= 500:          # actor/overlay packages
            sources.append((f"{idx:04d}", f, open(f, "rb").read()))
    catalogue = []
    for name, path, buf in sources:
        for off, cnt in scan_bone_tables(buf):
            catalogue.append((name, path, buf, off, cnt))
    print(f"rig catalogue: {len(catalogue)} candidate tables from {len(sources)} sources")

    ok = fail = 0
    for ptr, vals in MI.read_descriptors(exe):
        fidx = vals[0]
        matches = glob.glob(os.path.join(split_dir, f"{fidx:04d}_*"))
        if not matches:
            continue
        pkg = matches[0]
        data = open(pkg, "rb").read()
        mesh_sec = find_mesh(data)
        if mesh_sec is None:
            print(f"file {fidx}: skipped (no mesh block found)")
            fail += 1
            continue
        nmesh = meshmod.parse_block(data, mesh_sec * 2048)["meshCount"]
        anim_sec = find_anim(data, nmesh)
        tex_sec = find_tex(data, vals)
        anim_pkg = pkg
        if anim_sec is None:
            # Some models ship no animations of their own and share a set stored in
            # a neighbouring file (e.g. the 22-bone models use file 849).
            for cand in sorted(glob.glob(os.path.join(split_dir, "0*"))):
                ci = int(os.path.basename(cand)[:4])
                if not (fidx - 20 <= ci <= fidx + 20) or ci == fidx:
                    continue
                cdata = open(cand, "rb").read()
                s = find_anim(cdata, nmesh)
                if s is not None:
                    anim_sec, anim_pkg = s, cand
                    print(f"file {fidx}: borrowing {nmesh}-bone animations from {ci}")
                    break
        if anim_sec is None:
            print(f"file {fidx}: skipped (no {nmesh}-bone animation container)")
            fail += 1
            continue
        spec = None
        for name, path, buf, off, cnt in catalogue:
            if cnt == nmesh and rig_matches(buf, off, nmesh):
                spec = f"0x{0x80010000 + off - 0x800:X}" if name == "exe" else f"{path}@0x{off:X}"
                break
        if spec is None:
            print(f"file {fidx}: no rig for {nmesh} meshes - skipped")
            fail += 1
            continue
        stem = model_names.stem(fidx, creature)
        out = os.path.join(out_dir, f"{stem}.glb")
        cmd = [sys.executable, "export_gltf.py", exe_path, pkg, str(mesh_sec),
               str(anim_sec), spec, out, "--root", stem]
        if tex_sec is not None:
            cmd += ["--tex", str(tex_sec)]
        if anim_pkg != pkg:
            cmd += ["--animpkg", anim_pkg]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            print(f"file {fidx}: {r.stdout.strip().split(': ', 1)[-1]}")
            ok += 1
        else:
            print(f"file {fidx}: FAILED {r.stderr.strip().splitlines()[-1:]}")
            fail += 1
    print(f"\n{ok} models exported, {fail} skipped -> {out_dir}")


if __name__ == "__main__":
    main()
