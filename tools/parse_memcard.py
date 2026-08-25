"""Parse a PS1 memory card (.mcd raw 128KB) and list/extract saves.

Usage:
    python parse_memcard.py <card.mcd> [out_dir]
"""
import os
import sys

BLOCK = 8192
FRAME = 128


def main():
    path = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else None
    data = open(path, "rb").read()
    assert data[:2] == b"MC", "not a raw memcard image"

    saves = []
    for i in range(1, 16):
        dirent = data[i * FRAME:(i + 1) * FRAME]
        state = int.from_bytes(dirent[0:4], "little")
        size = int.from_bytes(dirent[4:8], "little")
        name = dirent[10:31].split(b"\x00")[0].decode("ascii", "replace")
        if state in (0x51, 0x52, 0x53):  # first / middle / last link
            kind = {0x51: "FIRST", 0x52: "MID", 0x53: "LAST"}[state]
            print(f"block {i:2}: {kind:5} size {size:6} name {name}")
            if state == 0x51:
                saves.append((i, size, name))
        elif state == 0xA0:
            pass
        else:
            print(f"block {i:2}: state 0x{state:02X} (free/other)")

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        for start, size, name in saves:
            # follow chain: block data lives at block index * 8KB
            blocks = [start]
            nxt = data[start * FRAME + 8]
            while nxt != 0xFF:
                blocks.append(nxt + 1)
                nxt = data[(nxt + 1) * FRAME + 8]
            raw = b"".join(data[b * BLOCK:(b + 1) * BLOCK] for b in blocks)[:size]
            fn = os.path.join(out_dir, name.replace(":", "_") + ".sav")
            open(fn, "wb").write(raw)
            print(f"extracted {name} -> {fn} ({len(raw)} B, blocks {blocks})")


if __name__ == "__main__":
    main()
