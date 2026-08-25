"""Extract every TIM texture from the split DATA.001 sub-files to PNG.

Usage:
    python extract_textures.py <split_dir> <out_dir> [--only 934-1080]

Scans each sub-file for valid TIMs anywhere in the buffer (not just section 5),
writes <out>/<fileIdx>/<n>_<w>x<h>_<bpp>.png and a manifest JSON.
"""
import json
import os
import struct
import sys

import tim


def main():
    split_dir, out_dir = sys.argv[1], sys.argv[2]
    lo, hi = 0, 99999
    if "--only" in sys.argv:
        rng = sys.argv[sys.argv.index("--only") + 1]
        lo, hi = (int(v) for v in rng.split("-"))

    os.makedirs(out_dir, exist_ok=True)
    manifest = []
    total = 0
    for fn in sorted(os.listdir(split_dir)):
        path = os.path.join(split_dir, fn)
        if os.path.isdir(path) or not fn[:4].isdigit():
            continue
        idx = int(fn[:4])
        if not (lo <= idx <= hi):
            continue
        data = open(path, "rb").read()
        tims = tim.find_all(data)
        if not tims:
            continue
        sub = os.path.join(out_dir, f"{idx:04d}")
        os.makedirs(sub, exist_ok=True)
        for i, t in enumerate(tims):
            try:
                rgba = tim.to_rgba(t)
                name = f"{i:03d}_{t['width']}x{t['height']}_{tim.PMODE_NAMES[t['pmode']]}.png"
                tim.write_png(os.path.join(sub, name), t["width"], t["height"], rgba)
                manifest.append({
                    "file": idx, "n": i, "offset": t["off"], "size": t["size"],
                    "w": t["width"], "h": t["height"], "pmode": t["pmode"],
                    "vram": t["vram"], "clut": t["clut_dim"], "png": f"{idx:04d}/{name}",
                })
                total += 1
            except Exception as e:
                print(f"  !! {idx} tim{i}: {e}")
        print(f"file {idx}: {len(tims)} TIMs")
    with open(os.path.join(out_dir, "manifest.json"), "w") as fp:
        json.dump(manifest, fp, indent=1)
    print(f"\n{total} textures extracted from {len(set(m['file'] for m in manifest))} files")


if __name__ == "__main__":
    main()
