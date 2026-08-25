"""Minimal MIPS R3000 disassembler for reading PS1 code out of raw images.

Enough of the ISA to follow control flow and argument setup: loads/stores,
immediate arithmetic, branches, jumps and the common R-type ops. Anything it
does not know prints as a raw word, which is a useful signal in itself.
Original code; no game data.
"""
import struct

REG = ['zero','at','v0','v1','a0','a1','a2','a3','t0','t1','t2','t3','t4','t5','t6','t7',
       's0','s1','s2','s3','s4','s5','s6','s7','t8','t9','k0','k1','gp','sp','fp','ra']

SPECIAL = {0x00:'sll',0x02:'srl',0x03:'sra',0x04:'sllv',0x06:'srlv',0x07:'srav',
           0x08:'jr',0x09:'jalr',0x0c:'syscall',0x0d:'break',0x10:'mfhi',0x11:'mthi',
           0x12:'mflo',0x13:'mtlo',0x18:'mult',0x19:'multu',0x1a:'div',0x1b:'divu',
           0x20:'add',0x21:'addu',0x22:'sub',0x23:'subu',0x24:'and',0x25:'or',
           0x26:'xor',0x27:'nor',0x2a:'slt',0x2b:'sltu'}

OPS = {0x04:'beq',0x05:'bne',0x06:'blez',0x07:'bgtz',0x08:'addi',0x09:'addiu',
       0x0a:'slti',0x0b:'sltiu',0x0c:'andi',0x0d:'ori',0x0e:'xori',0x0f:'lui',
       0x20:'lb',0x21:'lh',0x22:'lwl',0x23:'lw',0x24:'lbu',0x25:'lhu',0x26:'lwr',
       0x28:'sb',0x29:'sh',0x2a:'swl',0x2b:'sw',0x2e:'swr',
       0x32:'lwc2',0x3a:'swc2'}

MEM = set('lb lh lwl lw lbu lhu lwr sb sh swl sw swr lwc2 swc2'.split())


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def dis1(w, pc):
    op = w >> 26
    rs, rt, rd = (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
    sa, imm = (w >> 6) & 31, w & 0xFFFF
    if w == 0:
        return 'nop'
    if op == 0:
        fn = w & 0x3F
        name = SPECIAL.get(fn)
        if name is None:
            return '.word 0x%08x' % w
        if name in ('sll', 'srl', 'sra'):
            return '%-6s %s,%s,%d' % (name, REG[rd], REG[rt], sa)
        if name == 'jr':
            return 'jr     %s' % REG[rs]
        if name == 'jalr':
            return 'jalr   %s,%s' % (REG[rd], REG[rs])
        if name in ('mfhi', 'mflo'):
            return '%-6s %s' % (name, REG[rd])
        if name in ('mult', 'multu', 'div', 'divu'):
            return '%-6s %s,%s' % (name, REG[rs], REG[rt])
        return '%-6s %s,%s,%s' % (name, REG[rd], REG[rs], REG[rt])
    if op in (2, 3):
        tgt = ((pc + 4) & 0xF0000000) | ((w & 0x03FFFFFF) << 2)
        return '%-6s 0x%08x' % ('j' if op == 2 else 'jal', tgt)
    if op == 1:
        name = {0: 'bltz', 1: 'bgez', 16: 'bltzal', 17: 'bgezal'}.get(rt, 'b?%d' % rt)
        return '%-6s %s,0x%08x' % (name, REG[rs], pc + 4 + (s16(imm) << 2))
    if op == 0x10:
        return 'cop0   0x%07x' % (w & 0x1FFFFFF)
    if op == 0x12:
        if (w >> 25) & 1:
            return 'gte    0x%07x' % (w & 0x1FFFFFF)
        mv = {0: 'mfc2', 2: 'cfc2', 4: 'mtc2', 6: 'ctc2'}.get(rs, 'cop2?')
        return '%-6s %s,$%d' % (mv, REG[rt], rd)
    name = OPS.get(op)
    if name is None:
        return '.word 0x%08x' % w
    if name in ('beq', 'bne'):
        return '%-6s %s,%s,0x%08x' % (name, REG[rs], REG[rt], pc + 4 + (s16(imm) << 2))
    if name in ('blez', 'bgtz'):
        return '%-6s %s,0x%08x' % (name, REG[rs], pc + 4 + (s16(imm) << 2))
    if name == 'lui':
        return 'lui    %s,0x%04x' % (REG[rt], imm)
    if name in MEM:
        return '%-6s %s,%d(%s)' % (name, REG[rt], s16(imm), REG[rs])
    if name in ('andi', 'ori', 'xori'):
        return '%-6s %s,%s,0x%04x' % (name, REG[rt], REG[rs], imm)
    return '%-6s %s,%s,%d' % (name, REG[rt], REG[rs], s16(imm))


def dis(img, base, start, end):
    out = []
    for a in range(start, end, 4):
        w = struct.unpack_from('<I', img, a - base)[0]
        out.append('%08x  %08x  %s' % (a, w, dis1(w, a)))
    return out


def load_psx_exe(path):
    d = open(path, 'rb').read()
    taddr = struct.unpack_from('<I', d, 0x18)[0]
    tsize = struct.unpack_from('<I', d, 0x1C)[0]
    return d[0x800:0x800 + tsize], taddr


if __name__ == '__main__':
    import sys
    img, base = load_psx_exe(sys.argv[1])
    s = int(sys.argv[2], 16)
    e = int(sys.argv[3], 16) if len(sys.argv) > 3 else s + 0x100
    print('\n'.join(dis(img, base, s, e)))
