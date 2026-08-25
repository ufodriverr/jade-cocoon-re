"""PS1 TIM texture parser -> PNG (no external deps; writes PNG by hand).

TIM layout:
  u32 id = 0x10
  u32 flags: bits0-2 pmode (0=4bpp,1=8bpp,2=16bpp,3=24bpp), bit3 = CLUT present
  [if CF] CLUT block: u32 bnum(total len); u16 x,y,w,h; u16 entries[w*h]
  pixel block:        u32 bnum(total len); u16 x,y,w,h; u16 words[w*h]
    (w is in 16-bit words, so 4bpp image width = w*4, 8bpp = w*2, 16bpp = w)
"""
import struct
import zlib

PMODE_NAMES = {0: "4bpp", 1: "8bpp", 2: "16bpp", 3: "24bpp"}


def parse(data, off=0):
    """Parse a TIM at off. Returns dict or None if not a valid TIM."""
    if off + 8 > len(data):
        return None
    idv, flags = struct.unpack_from("<II", data, off)
    if idv != 0x10:
        return None
    pmode = flags & 7
    has_clut = bool(flags & 8)
    if pmode > 3 or (flags & ~0xF):
        return None
    p = off + 8
    clut = None
    clut_dim = None
    if has_clut:
        if p + 12 > len(data):
            return None
        bnum, cx, cy, cw, ch = struct.unpack_from("<IHHHH", data, p)
        if bnum < 12 or p + bnum > len(data) or cw == 0 or ch == 0:
            return None
        if bnum == 12:
            # Empty CLUT block: this texture SHARES a palette already uploaded to
            # (cx, cy) by another TIM. Common space optimization - the first texture
            # of a set carries the palette and the rest just reference the VRAM slot.
            clut = None
            clut_dim = (cx, cy, cw, ch)
        elif bnum != 12 + cw * ch * 2:
            return None
        else:
            clut = struct.unpack_from(f"<{cw*ch}H", data, p + 12)
            clut_dim = (cx, cy, cw, ch)
        p += bnum
    if p + 12 > len(data):
        return None
    bnum, x, y, w, h = struct.unpack_from("<IHHHH", data, p)
    if bnum < 12 or p + bnum > len(data) or w == 0 or h == 0:
        return None
    if bnum != 12 + w * h * 2:
        return None
    words = data[p + 12:p + bnum]
    total = p + bnum - off
    px_w = w * 4 if pmode == 0 else w * 2 if pmode == 1 else w
    return {
        "off": off, "size": total, "pmode": pmode, "has_clut": has_clut,
        "clut": clut, "clut_dim": clut_dim, "vram": (x, y, w, h),
        "width": px_w, "height": h, "words": words,
    }


def bgr555_to_rgba(c):
    r = (c & 0x1F) << 3
    g = ((c >> 5) & 0x1F) << 3
    b = ((c >> 10) & 0x1F) << 3
    stp = (c >> 15) & 1
    # black with STP=0 is fully transparent in PS1 convention
    a = 0 if (c & 0x7FFF) == 0 and stp == 0 else 255
    return (r | r >> 5, g | g >> 5, b | b >> 5, a)


def to_rgba(tim, clut_index=0, shared_clut=None):
    """Decode to a flat RGBA bytes buffer of width*height*4.

    shared_clut: palette to use when this TIM has an empty CLUT block (it
    references a palette another texture uploaded to the same VRAM slot).
    """
    w, h = tim["width"], tim["height"]
    words = tim["words"]
    out = bytearray(w * h * 4)
    pmode = tim["pmode"]
    clut = tim["clut"]
    clut = clut if clut is not None else shared_clut
    if clut and tim["clut_dim"]:
        _, _, cw, ch = tim["clut_dim"]
        pal_size = 16 if pmode == 0 else 256
        start = min(clut_index, max(0, ch - 1)) * cw
        pal = clut[start:start + pal_size]
    else:
        pal = None

    for i in range(w * h):
        if pmode == 0:  # 4bpp
            b = words[i >> 1]
            idx = (b & 0xF) if (i & 1) == 0 else (b >> 4)
            c = pal[idx] if pal and idx < len(pal) else 0
            rgba = bgr555_to_rgba(c)
        elif pmode == 1:  # 8bpp
            idx = words[i]
            c = pal[idx] if pal and idx < len(pal) else 0
            rgba = bgr555_to_rgba(c)
        elif pmode == 2:  # 16bpp direct
            c = struct.unpack_from("<H", words, i * 2)[0]
            rgba = bgr555_to_rgba(c)
        else:  # 24bpp
            j = i * 3
            rgba = (words[j], words[j + 1], words[j + 2], 255)
        out[i * 4:i * 4 + 4] = bytes(rgba)
    return bytes(out)


def write_png(path, width, height, rgba):
    """Minimal PNG writer (RGBA8, no external deps)."""
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # filter type none
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag, payload):
        c = struct.pack(">I", len(payload)) + tag + payload
        return c + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    open(path, "wb").write(png)


def find_all(data, step=4, limit=None):
    """Scan a buffer for all valid TIMs."""
    out = []
    off = 0
    while off + 8 <= len(data):
        t = parse(data, off)
        if t:
            out.append(t)
            off += max(t["size"], step)
            if limit and len(out) >= limit:
                break
        else:
            off += step
    return out
