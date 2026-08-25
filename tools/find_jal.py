"""Scan every DATA.001 sub-file (and the exe) for `jal <addr>` to a main-exe routine.

A MIPS `jal` encodes the absolute target, so an overlay image can be searched for
calls into the exe without knowing where the overlay loads. Reports file index and
byte offset of every hit. Original code; no game data.
"""
import glob
import os
import struct
import sys


def jal_word(addr):
    return 0x0C000000 | ((addr >> 2) & 0x03FFFFFF)


def scan(path, words):
    d = open(path, 'rb').read()
    hits = []
    for off in range(0, len(d) - 3, 4):
        w = struct.unpack_from('<I', d, off)[0]
        if w in words:
            hits.append((off, w))
    return hits


def main():
    splitdir = sys.argv[1]
    targets = [int(a, 16) for a in sys.argv[2:]]
    words = {jal_word(a): a for a in targets}
    for path in sorted(glob.glob(os.path.join(splitdir, '*.bin'))):
        hits = scan(path, words)
        if hits:
            name = os.path.basename(path)
            for off, w in hits:
                print('%s +0x%06x  jal %08x' % (name, off, words[w]))


if __name__ == '__main__':
    main()
