"""List the ISO9660 filesystem of a raw PS1 bin (MODE2/2352, single track).

Usage:
    python iso_ls.py <path-to-bin> [--json out.json]

Prints every file with LBA, size, and path. Optionally dumps the listing as
JSON for later tools (extractors) to consume.
"""
import json
import struct
import sys

SECTOR_RAW = 2352
# Mode2 Form1: 12 sync + 3 addr + 1 mode + 8 subheader = 24 bytes before user data
USER_OFFSET = 24
USER_SIZE = 2048


class BinImage:
    def __init__(self, path):
        self.f = open(path, "rb")

    def sector(self, lba):
        self.f.seek(lba * SECTOR_RAW + USER_OFFSET)
        return self.f.read(USER_SIZE)

    def read_extent(self, lba, size):
        out = bytearray()
        n = (size + USER_SIZE - 1) // USER_SIZE
        for i in range(n):
            out += self.sector(lba + i)
        return bytes(out[:size])


def parse_dir_records(data):
    """Yield (name, lba, size, is_dir) from one directory extent."""
    pos = 0
    while pos < len(data):
        rec_len = data[pos]
        if rec_len == 0:
            # rest of this sector is padding; jump to next sector boundary
            pos = (pos // USER_SIZE + 1) * USER_SIZE
            continue
        rec = data[pos:pos + rec_len]
        lba = struct.unpack_from("<I", rec, 2)[0]
        size = struct.unpack_from("<I", rec, 10)[0]
        flags = rec[25]
        name_len = rec[32]
        name = rec[33:33 + name_len].decode("ascii", "replace")
        yield name, lba, size, bool(flags & 0x02)
        pos += rec_len


def walk(img, lba, size, prefix, out):
    data = img.read_extent(lba, size)
    for name, child_lba, child_size, is_dir in parse_dir_records(data):
        if name in ("\x00", "\x01"):  # self / parent
            continue
        clean = name.split(";")[0]
        path = f"{prefix}/{clean}"
        if is_dir:
            walk(img, child_lba, child_size, path, out)
        else:
            out.append({"path": path, "lba": child_lba, "size": child_size})


def main():
    bin_path = sys.argv[1]
    img = BinImage(bin_path)

    pvd = img.sector(16)
    assert pvd[0] == 1 and pvd[1:6] == b"CD001", "PVD not found (unexpected sector layout?)"
    vol_id = pvd[40:72].decode("ascii", "replace").strip()
    root_rec = pvd[156:156 + 34]
    root_lba = struct.unpack_from("<I", root_rec, 2)[0]
    root_size = struct.unpack_from("<I", root_rec, 10)[0]
    print(f"Volume ID: {vol_id}")

    files = []
    walk(img, root_lba, root_size, "", files)
    files.sort(key=lambda x: x["lba"])
    for fe in files:
        print(f"  LBA {fe['lba']:>7}  {fe['size']:>11,} B  {fe['path']}")
    print(f"{len(files)} files")

    if "--json" in sys.argv:
        out_path = sys.argv[sys.argv.index("--json") + 1]
        with open(out_path, "w") as fp:
            json.dump({"volume_id": vol_id, "files": files}, fp, indent=1)
        print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
