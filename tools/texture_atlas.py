"""Rebuild a model's VRAM texture page(s) as atlas images, for UV-correct export.

How PS1 texturing works here, and why an atlas is the right shape:
  * A face carries a tpage id and a CLUT id. tpage names a 64-word-wide,
    256-tall VRAM page plus the colour depth; the face's u,v are texel
    coordinates INSIDE that page.
  * The model's TIMs each land at their own VRAM position, and together they
    tile the page exactly (verified on file 833: ten TIMs, no overlap, no gaps).

So reassembling the page reproduces precisely what the GPU samples, and the
face u,v can be used as-is - just divided by the page size.

Page texel width depends on depth, because VRAM x is in 16-bit words:
    4bpp -> 4 texels per word -> page is 256 texels wide
    8bpp -> 2 texels per word -> page is 128 texels wide
   16bpp -> 1 texel  per word -> page is  64 texels wide
Pages are always 256 texels tall. Faces of different depths therefore need
different atlases, so we key atlases by the full tpage id.
"""
import struct

import tim

PAGE_W_WORDS = 64
PAGE_H = 256


def tpage_info(tp):
    """Decode a tpage id -> (vram_x_words, vram_y, bpp_mode, texels_per_word)."""
    px = (tp & 0x0F) * PAGE_W_WORDS
    py = ((tp >> 4) & 1) * PAGE_H
    mode = (tp >> 7) & 3          # 0=4bpp, 1=8bpp, 2=16bpp
    per_word = 4 if mode == 0 else 2 if mode == 1 else 1
    return px, py, mode, per_word


def collect_tims(data, tex_sector):
    """Parse every TIM in a package's texture container."""
    base = tex_sector * 2048
    cnt = struct.unpack_from("<I", data, base)[0]
    if not (1 <= cnt <= 256):
        return []
    out = []
    for off in struct.unpack_from(f"<{cnt}I", data, base + 4):
        t = tim.parse(data, base + off)
        if t:
            out.append(t)
    return out


def resolve_cluts(tims):
    """Map CLUT VRAM position -> palette, so shared-CLUT TIMs can be decoded."""
    table = {}
    for t in tims:
        if t["clut"] is not None and t["clut_dim"]:
            table[t["clut_dim"][:2]] = t["clut"]
    return table


def build(data, tex_sector, tpages):
    """Build one atlas per requested tpage id.

    Returns {tpage: {"w","h","rgba","placed"}}. A TIM is placed into a page's
    atlas when its VRAM row range overlaps the page and its x lies within it.
    """
    tims = collect_tims(data, tex_sector)
    cluts = resolve_cluts(tims)
    atlases = {}
    for tp in tpages:
        px, py, mode, per_word = tpage_info(tp)
        aw, ah = PAGE_W_WORDS * per_word, PAGE_H
        rgba = bytearray(aw * ah * 4)
        placed = 0
        for t in tims:
            vx, vy, vw, vh = t["vram"]
            if t["pmode"] != mode:
                continue
            if not (px <= vx < px + PAGE_W_WORDS and py <= vy < py + PAGE_H):
                continue
            ox = (vx - px) * per_word
            oy = vy - py
            src = tim.to_rgba(t, shared_clut=cluts.get(t["clut_dim"][:2]) if t["clut_dim"] else None)
            for row in range(min(t["height"], ah - oy)):
                s = row * t["width"] * 4
                dcol = ox
                if dcol + t["width"] > aw:
                    continue
                dst = ((oy + row) * aw + dcol) * 4
                rgba[dst:dst + t["width"] * 4] = src[s:s + t["width"] * 4]
            placed += 1
        atlases[tp] = {"w": aw, "h": ah, "rgba": bytes(rgba), "placed": placed}
    return atlases


def png_bytes(atlas):
    """Encode an atlas as PNG bytes (in memory)."""
    import io
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        tim.write_png(path, atlas["w"], atlas["h"], atlas["rgba"])
        return open(path, "rb").read()
    finally:
        os.unlink(path)
