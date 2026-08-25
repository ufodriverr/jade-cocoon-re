"""Jade Cocoon animation block parser.

Block layout (confirmed against renderer FUN_80047e4c and by size arithmetic
across every block in file 833):

    +0x00  u32 frameCount
    +0x04  u32 boneCount   -- bit 31 = "an event list follows the keyframes"
    +0x08  8 + bones*6 header total (rest offsets: one s16[3] per bone)
    +hdr   keyframes: frameCount * (boneCount + 2) entries of 6 bytes (3 x s16)
    [+     u32 eventCount; {u32 frame, u32 eventId}[eventCount]   -- only if bit 31]

    total size = 8 + bones*6 + frames*(bones+2)*6, padded up to 4 bytes,
                 plus 4 + eventCount*8 (re-padded) when bit 31 is set.

The renderer indexes keyframes as
    key[(frame * (boneCount + 2) + bone + 2) * 6]
which is why there are two extra slots per frame (slots 0 and 1 carry
root translation / flags).

Usage: python anim.py <package_file> <sector> [-v]
"""
import struct
import sys

def hdr_size(bones):
    """Header = 8-byte counts + one s16[3] rest offset per bone."""
    return 8 + bones * 6


# Bit 31 of the boneCount word means the block carries a trailing EVENT LIST.
# Six containers in the archive set it (831, 832, 841, 876, 893, 930) and reading the
# word as a plain count made boneCount 0x80000016 = 2147483670, so parse_block rejected
# them and those models were recorded as having no animations of their own.
EVENT_FLAG = 0x80000000


def parse_block(data, off):
    """Parse one animation block; return dict or None if it fails validation.

    Field by field this is the loader FUN_80026AF4, which converts an on-disc block into
    the 0x1C-byte runtime descriptor at MODEL+0x54.
    """
    if off + 8 > len(data):
        return None
    frames, bones = struct.unpack_from("<II", data, off)
    has_extra = bool(frames & EVENT_FLAG)     # an extra u32 sits before the rest offsets
    has_events = bool(bones & EVENT_FLAG)     # an event list follows the keyframes
    frames &= ~EVENT_FLAG
    bones &= ~EVENT_FLAG
    if not (1 <= frames <= 4000 and 1 <= bones <= 200):
        return None
    hdr = hdr_size(bones) + (4 if has_extra else 0)
    size = hdr + frames * (bones + 2) * 6
    size = (size + 3) & ~3
    nevents = 0
    ev_off = None
    if has_events:
        if off + size + 4 > len(data):
            return None
        ev_off = off + size
        nevents = struct.unpack_from("<I", data, ev_off)[0]
        if nevents > 256:
            return None
        size += 4 + nevents * 8
        size = (size + 3) & ~3
    if off + size > len(data):
        return None
    return {"off": off, "frames": frames, "bones": bones, "size": size, "hdr": hdr,
            "extra": has_extra, "events": nevents, "eventOff": ev_off}


def events(data, blk):
    """The block's event list: 4 x s16 per entry, copied verbatim by FUN_80026AF4 into
    the runtime array at descriptor +0x10. On the player walk cycle (831 block 1) the
    third field alternates 21/22, which reads as left/right footstep triggers."""
    if not blk.get("events"):
        return []
    p = blk["eventOff"] + 4
    return [struct.unpack_from("<4h", data, p + i * 8) for i in range(blk["events"])]


def rest_offsets(data, blk):
    """Per-bone rest translation (s16 x,y,z), relative to the bone's parent."""
    base = blk["off"] + 8 + (4 if blk.get("extra") else 0)
    return [struct.unpack_from("<3h", data, base + i * 6)
            for i in range(blk["bones"])]


def extra(data, blk, frame, which):
    """The two non-bone entries at the start of each frame.

    which=0 -> accumulated world DISPLACEMENT (locomotion): zero for in-place
               animations, grows monotonically for walk/charge.
    which=1 -> the animated ROOT TRANSLATION. At frame 0 it equals restOffset[1]
               exactly (verified across 24 animations in 6 files), and it drives
               bone 1 instead of that static rest offset. Using the static value
               leaves the body rigid while the legs swing (feet drift 24 units);
               using this entry plants the feet exactly (0 drift) and bobs the body.
    """
    stride = blk["bones"] + 2
    p = blk["off"] + blk["hdr"] + (frame * stride + which) * 6
    return struct.unpack_from("<3h", data, p)


def root_translation(data, blk, frame):
    return extra(data, blk, frame, 1)


def displacement(data, blk, frame):
    return extra(data, blk, frame, 0)


def keyframe(data, blk, frame, bone):
    """Return (x, y, z) for a bone at a frame (raw fixed-point angle units)."""
    stride = blk["bones"] + 2
    idx = frame * stride + bone + 2
    p = blk["off"] + blk["hdr"] + idx * 6
    return struct.unpack_from("<3h", data, p)


def parse_container(data, base):
    """Parse a {u32 count; u32 offs[count]} container of animation blocks."""
    cnt = struct.unpack_from("<I", data, base)[0]
    if not (1 <= cnt <= 256):
        return []
    offs = struct.unpack_from(f"<{cnt}I", data, base + 4)
    out = []
    for o in offs:
        blk = parse_block(data, base + o)
        if blk:
            blk["rel"] = o
            out.append(blk)
    return out


def load_set(data, sector, slots=()):
    """A model's whole animation set: the resident container at `sector` (pass a
    negative sector when the model has none) followed by the bare blocks at each
    streamed slot sector.

    The two are disjoint on disc. The resident container is what the game keeps in RAM;
    everything else is streamed one clip at a time out of the per-animation sector table
    in the exe model descriptor (see model_anims.py), which is where most models keep
    most of their animations - and, for the humanoid NPCs, where their only rest pose
    lives.
    """
    out = list(parse_container(data, sector * 2048)) if sector is not None and sector >= 0 else []
    for sec in slots:
        blk = parse_block(data, sec * 2048)
        if blk:
            blk["rel"] = sec * 2048
            out.append(blk)
    return out


def main():
    path, sector = sys.argv[1], int(sys.argv[2])
    data = open(path, "rb").read()
    base = sector * 2048
    blocks = parse_container(data, base)
    print(f"{path} sector {sector}: {len(blocks)} animation blocks")
    total_ok = 0
    for i, b in enumerate(blocks):
        print(f"  anim{i}: {b['frames']:3} frames x {b['bones']:3} bones, "
              f"size {b['size']:>6} @0x{b['off']:X}")
        total_ok += 1
        if "-v" in sys.argv and b["frames"]:
            for bone in range(min(3, b["bones"])):
                k0 = keyframe(data, b, 0, bone)
                k1 = keyframe(data, b, min(1, b["frames"] - 1), bone)
                print(f"      bone{bone}: f0={k0} f1={k1}")
    # contiguity check: each block should butt against the next
    for i in range(len(blocks) - 1):
        end = blocks[i]["off"] + blocks[i]["size"]
        nxt = blocks[i + 1]["off"]
        flag = "OK " if end == nxt else f"gap {nxt-end}"
        print(f"   block{i} end 0x{end:X} -> block{i+1} 0x{nxt:X}  {flag}")


if __name__ == "__main__":
    main()
