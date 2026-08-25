"""Validate a GLB *under animation*, not just in its bind pose.

`check_glb.py` checks the bind pose. That is a real blind spot: at bind pose every skin
matrix is `world(joint) * inverseBind(joint) == identity`, so a rig whose joints, bone
lengths or animation tracks disagree with the baked vertices still looks perfect. The
mesh only comes apart once a clip plays.

So this samples every clip and measures how far each triangle's edges stretch away from
their bind-pose length. Rigid skinning (one bone per vertex, which is what this game
uses) keeps an edge's length exactly constant unless the edge spans two bones, and even
then a joint only bends it. A stretch of 5x or 50x is geometry being pulled apart.

    python check_anim.py <file.glb> [more.glb ...] [--frames N] [--verbose]
    python check_anim.py ../models/merged/*.glb

Pass --baseline REF.glb to compare against a model known to be good - for a merged
file that is one of its parents. Exit status is 1 if a file comes out materially
worse than the baseline, so it works in a check script.

Original code. Reads only files this repo generated; no game data required.
"""

import glob
import json
import math
import struct
import sys

CT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2),
      5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

# Only edges of a reasonable length count: a 0.01-unit edge doubling means nothing.
MIN_EDGE = 0.02      # fraction of the model's span; shorter edges are ignored

# Deliberately NO absolute pass/fail threshold. Measured across models/current/, the
# known-good models reach 3.2x to 4.6x all by themselves, because a seam strip
# spanning two bones really does stretch when a limb bends. An absolute cutoff that
# admits those would miss real damage, so this tool reports the number and, with
# --baseline, compares a file against a model known to be good. Judge by comparison,
# not by a magic constant.
WORSE = 1.5          # --baseline: how many times the baseline counts as "worse"


def load(path):
    raw = open(path, "rb").read()
    assert raw[:4] == b"glTF", "not a GLB"
    p, js, binv = 12, None, None
    while p < len(raw):
        clen, ctype = struct.unpack_from("<I4s", raw, p)
        chunk = raw[p + 8:p + 8 + clen]
        if ctype == b"JSON":
            js = json.loads(chunk)
        elif ctype[:3] == b"BIN":
            binv = chunk
        p += 8 + clen
    return js, binv


def read_accessor(g, binv, idx):
    a = g["accessors"][idx]
    n = NCOMP[a["type"]]
    fmt, size = CT[a["componentType"]]
    if "bufferView" not in a:
        return [0] * (a["count"] * n)
    v = g["bufferViews"][a["bufferView"]]
    base = v.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = v.get("byteStride") or size * n
    out = []
    for e in range(a["count"]):
        off = base + e * stride
        out.extend(struct.unpack_from("<" + fmt * n, binv, off))
    return out


def quat_mat(q):
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]]


def trs_matrix(t, r, s):
    m = quat_mat(r)
    return [[m[i][j] * s[j] for j in range(3)] + [t[i]] for i in range(3)] + \
           [[0.0, 0.0, 0.0, 1.0]]


def mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)]
            for i in range(4)]


def slerp(a, b, t):
    d = sum(a[i] * b[i] for i in range(4))
    if d < 0:
        b = [-v for v in b]
        d = -d
    if d > 0.9995:
        out = [a[i] + (b[i] - a[i]) * t for i in range(4)]
    else:
        th = math.acos(max(-1.0, min(1.0, d)))
        s = math.sin(th)
        w0, w1 = math.sin((1 - t) * th) / s, math.sin(t * th) / s
        out = [a[i] * w0 + b[i] * w1 for i in range(4)]
    n = math.sqrt(sum(v * v for v in out)) or 1.0
    return [v / n for v in out]


def sample(times, values, width, t, rotation):
    n = len(times)
    if n == 1:
        return values[:width]
    i = 0
    while i < n - 1 and times[i + 1] < t:
        i += 1
    j = min(i + 1, n - 1)
    span = times[j] - times[i]
    f = 0.0 if span <= 0 else max(0.0, min(1.0, (t - times[i]) / span))
    a = values[i * width:i * width + width]
    b = values[j * width:j * width + width]
    if rotation:
        return slerp(a, b, f)
    return [a[k] + (b[k] - a[k]) * f for k in range(width)]


class Model:
    def __init__(self, path):
        self.g, self.bin = load(path)
        g = self.g
        self.parent = {}
        for i, n in enumerate(g.get("nodes", [])):
            for c in n.get("children", []):
                self.parent[c] = i
        self.rest = []
        for n in g.get("nodes", []):
            self.rest.append((list(n.get("translation", [0, 0, 0])),
                              list(n.get("rotation", [0, 0, 0, 1])),
                              list(n.get("scale", [1, 1, 1]))))
        skin = (g.get("skins") or [None])[0]
        self.joints = skin["joints"] if skin else []
        self.ibm = []
        if skin and "inverseBindMatrices" in skin:
            flat = read_accessor(g, self.bin, skin["inverseBindMatrices"])
            for j in range(len(self.joints)):
                c = flat[j * 16:j * 16 + 16]      # glTF matrices are column-major
                self.ibm.append([[c[col * 4 + row] for col in range(4)]
                                 for row in range(4)])
        self.prims = []
        for node in g.get("nodes", []):
            if "mesh" not in node:
                continue
            mesh = g["meshes"][node["mesh"]]
            for p in mesh["primitives"]:
                if p.get("mode", 4) != 4:
                    continue
                at = p["attributes"]
                pos = read_accessor(g, self.bin, at["POSITION"])
                idx = (read_accessor(g, self.bin, p["indices"])
                       if "indices" in p else list(range(len(pos) // 3)))
                jt = read_accessor(g, self.bin, at["JOINTS_0"]) if "JOINTS_0" in at else None
                wt = read_accessor(g, self.bin, at["WEIGHTS_0"]) if "WEIGHTS_0" in at else None
                self.prims.append({"name": mesh.get("name", ""), "pos": pos,
                                   "idx": idx, "j": jt, "w": wt})

    def pose(self, anim_index=None, t=0.0):
        """Local TRS for every node with clip `anim_index` sampled at time `t`."""
        cur = [(list(a), list(b), list(c)) for a, b, c in self.rest]
        if anim_index is not None:
            anim = self.g["animations"][anim_index]
            for ch in anim["channels"]:
                tgt = ch.get("target", {})
                ni, path = tgt.get("node"), tgt.get("path")
                if ni is None or path == "weights":
                    continue
                s = anim["samplers"][ch["sampler"]]
                times = read_accessor(self.g, self.bin, s["input"])
                vals = read_accessor(self.g, self.bin, s["output"])
                w = 4 if path == "rotation" else 3
                v = sample(times, vals, w, t, path == "rotation")
                slot = {"translation": 0, "rotation": 1, "scale": 2}[path]
                cur[ni] = tuple(list(v) if k == slot else list(cur[ni][k])
                                for k in range(3))
        world = {}

        def W(i):
            if i in world:
                return world[i]
            m = trs_matrix(*cur[i])
            if i in self.parent:
                m = mul(W(self.parent[i]), m)
            world[i] = m
            return m

        return [mul(W(self.joints[j]), self.ibm[j]) for j in range(len(self.joints))]

    def skin(self, mats):
        out = []
        for p in self.prims:
            pos, jt, wt = p["pos"], p["j"], p["w"]
            n = len(pos) // 3
            res = [0.0] * (n * 3)
            for v in range(n):
                x, y, z = pos[v * 3], pos[v * 3 + 1], pos[v * 3 + 2]
                if not mats or jt is None:
                    res[v * 3], res[v * 3 + 1], res[v * 3 + 2] = x, y, z
                    continue
                ax = ay = az = 0.0
                for k in range(4):
                    w = wt[v * 4 + k] if wt else (1.0 if k == 0 else 0.0)
                    if w == 0.0:
                        continue
                    m = mats[jt[v * 4 + k]]
                    ax += w * (m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3])
                    ay += w * (m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3])
                    az += w * (m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3])
                res[v * 3], res[v * 3 + 1], res[v * 3 + 2] = ax, ay, az
            out.append(res)
        return out


def edge_lengths(model, skinned):
    """Length of every triangle edge, flattened, in primitive order."""
    out = []
    for p, pos in zip(model.prims, skinned):
        idx = p["idx"]
        for t in range(0, len(idx) - 2, 3):
            a, b, c = idx[t] * 3, idx[t + 1] * 3, idx[t + 2] * 3
            for u, v in ((a, b), (b, c), (c, a)):
                out.append(math.dist(pos[u:u + 3], pos[v:v + 3]))
    return out


def check(path, frames=9, verbose=False):
    m = Model(path)
    name = path.replace("\\", "/").split("/")[-1]
    if not m.joints:
        print("%-44s no skin, nothing to animate" % name)
        return 0.0
    bind = m.skin(m.pose())
    span = 0.0
    for axis in range(3):
        vals = [pr[i] for pr in bind for i in range(axis, len(pr), 3)]
        if vals:
            span = max(span, max(vals) - min(vals))
    base = edge_lengths(m, bind)
    floor = span * MIN_EDGE
    keep = [k for k, b in enumerate(base) if b >= floor]
    worst, worst_clip, worst_t = 1.0, "-", 0.0
    rows = []
    for ai, anim in enumerate(m.g.get("animations", [])):
        dur = 0.0
        for ch in anim["channels"]:
            ts = read_accessor(m.g, m.bin, anim["samplers"][ch["sampler"]]["input"])
            dur = max(dur, ts[-1] if ts else 0.0)
        clip_worst = 1.0
        for s in range(frames):
            t = dur * s / max(frames - 1, 1)
            cur = edge_lengths(m, m.skin(m.pose(ai, t)))
            for k in keep:
                r = cur[k] / base[k]
                if r > clip_worst:
                    clip_worst = r
                    if r > worst:
                        worst, worst_clip, worst_t = r, anim.get("name", str(ai)), t
        rows.append((clip_worst, anim.get("name", str(ai))))
    print("%-44s worst edge stretch %6.2fx  (%s @ %.2fs)"
          % (name, worst, worst_clip, worst_t))
    if verbose:
        for r, n in sorted(rows, reverse=True)[:6]:
            print("      %6.2fx  %s" % (r, n))
    return worst


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    frames = 9
    if "--frames" in sys.argv:
        frames = int(sys.argv[sys.argv.index("--frames") + 1])
        args = [a for a in args if a != str(frames)]
    verbose = "--verbose" in sys.argv
    baseline = None
    if "--baseline" in sys.argv:
        baseline = sys.argv[sys.argv.index("--baseline") + 1]
        args = [a for a in args if a != baseline]
    paths = []
    for a in args:
        paths.extend(sorted(glob.glob(a)) if any(c in a for c in "*?") else [a])
    if not paths:
        print(__doc__)
        return 2
    ref = None
    if baseline:
        ref = check(baseline, frames, verbose)
        print("   ^ baseline: more than %.1fx this is worse than its parent\n" % WORSE)
    bad = 0
    for p in paths:
        try:
            got = check(p, frames, verbose)
            if ref and got > ref * WORSE:
                print("%44s   ^ %.1fx the baseline" % ("", got / ref))
                bad += 1
        except Exception as exc:
            print("%-44s FAILED: %s" % (p, exc))
            bad += 1
    if ref and len(paths) > 1:
        print("\n%d of %d file(s) come out worse than the baseline" % (bad, len(paths)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
