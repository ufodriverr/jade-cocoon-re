"""Disassemble a range of a raw overlay image loaded at a fixed address.

usage: disovl.py <image> <hexBase> <hexStart> [hexEnd]
If hexStart is omitted's end, dumps 0x100 bytes. Prints the enclosing function
start guess (nearest preceding `addiu sp,sp,-X`) when asked with --func.
Original code; no game data.
"""
import struct
import sys

from mipsdis import dis1


def main():
    img = open(sys.argv[1], 'rb').read()
    base = int(sys.argv[2], 16)
    start = int(sys.argv[3], 16)
    if '--func' in sys.argv:
        a = start
        while a > base:
            w = struct.unpack_from('<I', img, a - base)[0]
            if (w >> 16) == 0x27BD and (w & 0x8000):
                break
            a -= 4
        start = a
    end = int(sys.argv[4], 16) if len(sys.argv) > 4 and not sys.argv[4].startswith('--') else start + 0x100
    for a in range(start, end, 4):
        w = struct.unpack_from('<I', img, a - base)[0]
        print('%08x  %08x  %s' % (a, w, dis1(w, a)))


if __name__ == '__main__':
    main()
