"""Extract files from the raw PS1 bin using the JSON listing from iso_ls.py.

Usage:
    python iso_extract.py <bin> <filelist.json> <out_dir> [path-substring ...]

With no substrings, extracts everything. Otherwise extracts files whose ISO
path contains any given substring (case-insensitive).

Note: this reads Mode2 Form1 user data (2048 B/sector). STR movies and XA
audio are Form2 interleaved - extracting those with this tool will not give
playable files; use jPSXdec on the bin for A/V content instead.
"""
import json
import os
import sys

from iso_ls import BinImage


def main():
    bin_path, json_path, out_dir = sys.argv[1:4]
    pats = [p.lower() for p in sys.argv[4:]]
    listing = json.load(open(json_path))
    img = BinImage(bin_path)

    for fe in listing["files"]:
        if pats and not any(p in fe["path"].lower() for p in pats):
            continue
        dest = os.path.join(out_dir, fe["path"].lstrip("/").replace("/", os.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        print(f"extracting {fe['path']} ({fe['size']:,} B) -> {dest}")
        with open(dest, "wb") as fp:
            # stream in chunks to keep memory flat on the 200MB archive
            remaining = fe["size"]
            lba = fe["lba"]
            while remaining > 0:
                chunk = img.read_extent(lba, min(remaining, 2048 * 1024))
                fp.write(chunk)
                remaining -= len(chunk)
                lba += 1024


if __name__ == "__main__":
    main()
