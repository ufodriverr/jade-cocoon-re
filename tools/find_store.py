"""Scan the exe for MIPS store instructions with a given immediate offset.

Usage: python find_store.py <exe> <hexImm> [more hexImm...]
Finds `sw/sh/sb rX, imm(rY)` so we can locate who writes a given struct field.
"""
import struct
import sys

BASE, HDR = 0x80010000, 0x800
OPS = {0x28: "sb", 0x29: "sh", 0x2B: "sw", 0x23: "lw", 0x21: "lh", 0x25: "lhu"}


def main():
    exe = open(sys.argv[1], "rb").read()
    imms = {int(a, 16) for a in sys.argv[2:]}
    n = (len(exe) - HDR) // 4
    words = struct.unpack_from(f"<{n}I", exe, HDR)
    for i, w in enumerate(words):
        op = w >> 26
        if op not in OPS:
            continue
        imm = w & 0xFFFF
        if imm in imms:
            addr = BASE + i * 4
            rs = (w >> 21) & 31
            rt = (w >> 16) & 31
            print(f"0x{addr:08X}  {OPS[op]:3} r{rt:<2} 0x{imm:X}(r{rs})")


if __name__ == "__main__":
    main()
