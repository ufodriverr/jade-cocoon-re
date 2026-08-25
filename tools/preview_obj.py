"""Render an OBJ to PNG with a tiny z-buffered rasterizer (no dependencies).

Draws three orthographic views (front / side / top) side by side so the shape is
easy to judge. Flat shading from a fixed light.

Usage: python preview_obj.py <in.obj> <out.png> [size]
"""
import struct
import sys

import tim


def load_obj(path):
    verts, faces = [], []
    for line in open(path):
        if line.startswith("v "):
            _, x, y, z = line.split()
            verts.append((float(x), float(y), float(z)))
        elif line.startswith("f "):
            idx = [int(p.split("/")[0]) for p in line.split()[1:]]
            faces.append(tuple(i - 1 for i in idx[:3]))
    return verts, faces


def render(verts, faces, size, axes):
    """Orthographic render along the given (ax, ay, azdepth) axis triple."""
    ax, ay, az = axes
    w = h = size
    buf = bytearray(w * h * 4)
    zbuf = [1e9] * (w * h)
    if not verts:
        return buf
    xs = [v[ax] for v in verts]
    ys = [v[ay] for v in verts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    span = max(maxx - minx, maxy - miny) or 1
    scale = (size * 0.88) / span
    ox = (size - (maxx - minx) * scale) / 2 - minx * scale
    oy = (size - (maxy - miny) * scale) / 2 - miny * scale

    for f in faces:
        try:
            p = [verts[i] for i in f]
        except IndexError:
            continue
        sx = [v[ax] * scale + ox for v in p]
        sy = [size - (v[ay] * scale + oy) for v in p]
        sz = [v[az] for v in p]
        # flat shade from face normal in screen space
        e1 = (sx[1] - sx[0], sy[1] - sy[0])
        e2 = (sx[2] - sx[0], sy[2] - sy[0])
        area = e1[0] * e2[1] - e1[1] * e2[0]
        if abs(area) < 1e-6:
            continue
        shade = 70 + int(150 * abs(area) / (abs(area) + 400))
        depth = sum(sz) / 3.0
        x0 = max(0, int(min(sx)))
        x1 = min(w - 1, int(max(sx)) + 1)
        y0 = max(0, int(min(sy)))
        y1 = min(h - 1, int(max(sy)) + 1)
        for py in range(y0, y1 + 1):
            for px in range(x0, x1 + 1):
                w0 = (sx[1] - sx[0]) * (py - sy[0]) - (sy[1] - sy[0]) * (px - sx[0])
                w1 = (sx[2] - sx[1]) * (py - sy[1]) - (sy[2] - sy[1]) * (px - sx[1])
                w2 = (sx[0] - sx[2]) * (py - sy[2]) - (sy[0] - sy[2]) * (px - sx[2])
                if (w0 >= 0 and w1 >= 0 and w2 >= 0) or (w0 <= 0 and w1 <= 0 and w2 <= 0):
                    o = py * w + px
                    if depth < zbuf[o]:
                        zbuf[o] = depth
                        buf[o * 4] = shade
                        buf[o * 4 + 1] = min(255, shade + 20)
                        buf[o * 4 + 2] = min(255, shade + 40)
                        buf[o * 4 + 3] = 255
    return buf


def main():
    src, out = sys.argv[1], sys.argv[2]
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 260
    verts, faces = load_obj(src)
    print(f"{src}: {len(verts)} verts, {len(faces)} tris")
    views = [(0, 1, 2), (2, 1, 0), (0, 2, 1)]  # front, side, top
    panels = [render(verts, faces, size, v) for v in views]
    # plus a 3/4 view: yaw 35 degrees about Y, then project front
    import math
    ca, sa = math.cos(math.radians(35)), math.sin(math.radians(35))
    rot = [(x * ca + z * sa, y, -x * sa + z * ca) for x, y, z in verts]
    panels.append(render(rot, faces, size, (0, 1, 2)))
    W = size * len(panels)
    combined = bytearray(W * size * 4)
    for pi, pan in enumerate(panels):
        for y in range(size):
            src_off = y * size * 4
            dst_off = (y * W + pi * size) * 4
            combined[dst_off:dst_off + size * 4] = pan[src_off:src_off + size * 4]
    tim.write_png(out, W, size, bytes(combined))
    print(f"wrote {out} ({W}x{size}) - front | side | top | 3-4 view")


if __name__ == "__main__":
    main()
