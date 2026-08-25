"""Scan every split sub-file for embedded TMD models (magic 0x41, version).

A PS1 TMD header is: u32 id(0x41), u32 flags(0/1), u32 nobj, then nobj objects
of 28 bytes each: {vert_ptr, n_vert, normal_ptr, n_normal, prim_ptr, n_prim, scale}.
We validate by checking nobj is sane and the first object's counts are plausible.
"""
import glob
import os
import struct
import sys

split_dir = sys.argv[1]


def looks_like_tmd(data, off):
    if off + 12 > len(data):
        return None
    idv, flags, nobj = struct.unpack_from("<III", data, off)
    if idv != 0x41 or flags > 1 or not (1 <= nobj <= 64):
        return None
    # object table follows; validate object 0
    if off + 12 + nobj * 28 > len(data):
        return None
    vptr, nvert, nptr, nnorm, pptr, nprim, scale = struct.unpack_from("<7i", data, off + 12)
    if not (0 < nvert < 20000 and 0 <= nnorm < 20000 and 0 < nprim < 20000):
        return None
    return {"nobj": nobj, "nvert0": nvert, "nprim0": nprim}


def main():
    hits = []
    for fn in sorted(glob.glob(os.path.join(split_dir, "*"))):
        if os.path.isdir(fn):
            continue
        data = open(fn, "rb").read()
        # check offset 0, and after a possible header, and at every 4-byte boundary in first 0x200
        found = []
        for off in range(0, min(len(data) - 12, 0x4000), 4):
            r = looks_like_tmd(data, off)
            if r:
                found.append((off, r))
                if len(found) >= 3:
                    break
        if found:
            base = os.path.basename(fn)
            hits.append((base, len(data), found))
    for base, size, found in hits:
        offs = ", ".join(f"0x{o:X}(obj{r['nobj']},v{r['nvert0']},p{r['nprim0']})" for o, r in found)
        print(f"{base:24} {size:>9,}  TMD@ {offs}")
    print(f"{len(hits)} files contain TMD data")


if __name__ == "__main__":
    main()
