"""Build viewer/models.json - the file list the browser viewer reads.

The viewer is served over plain HTTP with no directory listing to rely on, so it needs
a manifest. This walks models/<folder>/ and records, per model, what the viewer wants
to show before the GLB is downloaded: name, vertex count, bone count, animation list,
which hidden body-part groups it carries.

    python build_viewer_index.py [modelsDir] [outFile]

Defaults to ../models and ../viewer/models.json. Re-run it after re-exporting.

Original code. Reads only files this repo generated; no game data required.
"""

import json
import os
import re
import struct
import sys

FOLDERS = [
    ("current", "Disc export", "Straight off the disc: every model the game ships."),
    ("merged", "Merged", "Creatures that do not exist on the disc, blended by "
                         "merge_reference.py from two or three parents."),
    ("derived_experiment", "Derived rigs", "Five models rebuilt on a synthesised "
                                           "skeleton. An experiment, not a fix."),
]


def read_glb(path):
    """Return the glTF JSON chunk of a .glb, or None if it is not one."""
    with open(path, "rb") as fh:
        head = fh.read(12)
        if len(head) < 12 or head[:4] != b"glTF":
            return None
        data = fh.read()
    off = 0
    while off + 8 <= len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        off += 8
        if ctype == 0x4E4F534A:
            return json.loads(data[off:off + clen].decode("utf-8"))
        off += clen
    return None


def glb_summary(js):
    verts = 0
    prims = 0
    hidden = []
    for mesh in js.get("meshes", []):
        name = mesh.get("name") or ""
        for prim in mesh["primitives"]:
            prims += 1
            verts += js["accessors"][prim["attributes"]["POSITION"]]["count"]
        if name.startswith("hidden_"):
            hidden.append(name[len("hidden_"):])
    bones = max([len(s["joints"]) for s in js.get("skins", [])] or [0])
    anims = []
    for anim in js.get("animations", []):
        name = anim.get("name") or "anim"
        frames = 1
        hit = re.search(r"_(\d+)f$", name)
        if hit:
            frames = int(hit.group(1))
        anims.append({"name": name, "frames": frames})
    return {
        "verts": verts,
        "prims": prims,
        "bones": bones,
        "hidden": hidden,
        "textures": len(js.get("images", [])),
        "anims": anims,
    }


def obj_summary(path):
    verts = tris = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("v "):
                verts += 1
            elif line.startswith("f "):
                tris += 1
    return {"verts": verts, "prims": tris, "bones": 0, "hidden": [],
            "textures": 0, "anims": []}


def label_for(stem):
    """`jc_0845_Marrdreg` -> (845, 'Marrdreg'). Unnamed files keep their index."""
    base = re.sub(r"_(static|derived)$", "", stem)
    hit = re.match(r"jc_?(\d{3,4})_?(.*)$", base)
    if not hit:
        return None, base.replace("_", " ")
    return int(hit.group(1)), hit.group(2).replace("_", " ").strip() or None


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    models_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "models")
    out_path = (sys.argv[2] if len(sys.argv) > 2
                else os.path.join(here, "..", "viewer", "models.json"))
    models_dir = os.path.abspath(models_dir)

    folders = []
    for fid, flabel, fnote in FOLDERS:
        fdir = os.path.join(models_dir, fid)
        if not os.path.isdir(fdir):
            continue

        report = {}
        rpath = os.path.join(fdir, "export_report.json")
        if os.path.isfile(rpath):
            with open(rpath, encoding="utf-8") as fh:
                report = json.load(fh)

        entries = []
        for fname in sorted(os.listdir(fdir)):
            stem, ext = os.path.splitext(fname)
            if ext == ".glb":
                js = read_glb(os.path.join(fdir, fname))
                if js is None:
                    continue
                info = glb_summary(js)
            elif ext == ".obj":
                info = obj_summary(os.path.join(fdir, fname))
            else:
                continue

            index, name = label_for(stem)
            entry = {"file": fname, "stem": stem, "name": name, "static": ext == ".obj"}
            if index is not None:
                entry["index"] = index
                rec = report.get("%04d" % index)
                if rec:
                    entry["nameSource"] = rec.get("nameSource")
                    entry["rigFile"] = rec.get("rigFile")
                    entry["animFile"] = rec.get("animFile")
                    entry["fit"] = rec.get("fit")
                    entry["note"] = rec.get("note")
            if os.path.isfile(os.path.join(fdir, stem + ".appearance.json")):
                entry["appearance"] = stem + ".appearance.json"
            entry.update(info)
            entries.append(entry)

        if entries:
            folders.append({"id": fid, "label": flabel, "note": fnote,
                            "dir": "../models/" + fid, "models": entries})

    out = {"folders": folders}
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)

    total = sum(len(f["models"]) for f in folders)
    print("wrote %s: %d folders, %d models" % (out_path, len(folders), total))
    for f in folders:
        print("  %-20s %3d" % (f["id"], len(f["models"])))


if __name__ == "__main__":
    main()
