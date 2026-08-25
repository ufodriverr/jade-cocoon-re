"""Export the five models whose skeleton is not on the disc, using a DERIVED bone table.

`derive_rig.py` beam-searches a depth array against the mesh's own stitch records. On rigs
we already have it recovers 17/25, 21/25, 18/22 and 9/40 parents - it finds *a* skeleton
that closes the seams, not *the* one - so these exports are an EXPERIMENT to look at beside
the shipped ones, not a replacement for them. Nothing here goes into `Models/current/`.

Usage:  python export_derived.py <exe> <split_dir> <out_dir>
"""
import glob
import json
import os
import struct
import subprocess
import sys

import assemble_model as AM
import derive_rig
import export_every as EE
import mesh as meshmod
import model_names
from export_all import find_tex

HERE = os.path.dirname(os.path.abspath(__file__))
# model -> bone count, from its own clips and its mesh object count (see OVERLAYS.md).
TARGETS = {870: 26, 879: 26, 893: 24, 930: 24, 841: 35}


def table_bytes(depths):
    out = b""
    for i, d in enumerate(depths):
        par = 0
        out += struct.pack("<hBBhh", d, i, par, i, 0x0B)
    return out + b"\xff" * 8


def main():
    exe_path, split_dir, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(out_dir, exist_ok=True)
    exe = open(exe_path, "rb").read()
    lut = AM.load_lut(exe)
    root = os.path.dirname(split_dir)
    index = json.load(open(os.path.join(root, "rig_anim_index.json")))
    rig_path = os.path.join(root, "derived_rigs.bin")

    blob, meta = b"", {}
    for fidx, nb in sorted(TARGETS.items()):
        best = derive_rig.run(exe, lut, split_dir, index, fidx, nb)
        if best is None:
            continue
        meta["%04d" % fidx] = {"off": len(blob), "bones": nb, "fit": best[0],
                               "depths": list(best[1])}
        blob += table_bytes(best[1])
    open(rig_path, "wb").write(blob)
    json.dump(meta, open(os.path.join(root, "derived_rigs.json"), "w"), indent=1)

    names = model_names.resolve(open(exe_path, "rb").read(), split_dir)
    for key, m in sorted(meta.items()):
        fidx = int(key)
        pkg = glob.glob(os.path.join(split_dir, "%04d_*.bin" % fidx))[0]
        data = open(pkg, "rb").read()
        mesh_sec, _nobj, _t = EE.scan_meshes(data)[0]
        slots = [b["sector"] for b in index["streamed"].get(str(fidx), [])
                 if b["bones"] >= m["bones"]][:EE.MAX_ANIMS]
        resident = [a for a in index["anims"]
                    if a["file"] == fidx and a.get("primary") and a["bones"] >= m["bones"]]
        anim_sec = resident[0]["sector"] if resident else -1
        stem = "%s_derived" % model_names.stem(fidx, names)
        out = os.path.join(out_dir, "%s.glb" % stem)
        cmd = [sys.executable, os.path.join(HERE, "export_gltf.py"), exe_path, pkg,
               str(mesh_sec), str(anim_sec), "%s@0x%X" % (rig_path, m["off"]), out,
               "--name", "jc%04d_" % fidx, "--animslots", ",".join(map(str, slots)),
               "--root", stem]
        tex = find_tex(data, [fidx])
        if tex is not None:
            cmd += ["--tex", str(tex)]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
        ok = "ok" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["?"])[-1]
        print("%d  %d bones, %d clips, fit %.1f -> %s"
              % (fidx, m["bones"], len(slots), m["fit"] or -1, ok))


if __name__ == "__main__":
    main()
