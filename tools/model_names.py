"""Give every model file its real in-game name.

A DATA.001 model file has no name inside it - it is just geometry, and the
export used to fall back on the file index (`jc_0845.glb`). Two tables on the
disc between them name almost all of them, from opposite directions:

1. **The species table** (`0x8007BC54`) maps a species id to a model id, and the
   name array at `0x8007A094` maps the same species id to its English name. That
   covers everything the player can catch, merge or fight as a creature. Several
   species share one model - the 144 elemental variants are the same mesh under
   a rotated palette - so a file is named after the **lowest** species id that
   points at it, which is always the base form (`845 -> Marrdreg`, not
   `845 -> Terfrayd`).

2. **Scene-package actor records** name the rest: the NPCs. Every scene package
   (files 199-470) carries an `ActorInfo` per actor it spawns, and its first two
   fields are exactly what is needed here:

       struct ActorInfo {
         /* 0x00 */ char     *name;         // into the package, Shift-JIS full-width
         /* 0x04 */ s32       modelId;      // index into the exe descriptor table
         /* 0x08 */ BoneRec  *rig;          // usually NULL - see OVERLAYS.md
         /* 0x0C */ s32      *globalScale;  // usually NULL
         /* 0x10 */ s16      *boneScale;    // usually NULL
       };

   `OVERLAYS.md` §2 decompiled the consumer (`ovl_800B25F4`) and documented
   fields 0x04..0x10; the name pointer at 0x00 is what this module adds. The
   three trailing pointers are the discriminator: they are either null or point
   back into the same package, which is what separates a real record from a
   coincidence. Scene packages load at `0x800B248C`, so a pointer is resolved by
   subtracting that.

   The two tables agree wherever they overlap - `870 Kikinak`, `876 Masked Boy`,
   `893 Poacher`, `930 Dream Man`, `835 Fire Boss` are named identically by both
   - which is the cross-check that the record layout is right. Where they
   disagree the species table wins, because the actor record holds the internal
   codename (`836` is `Tuturis` to the player and `BSFS` to Genki).

Six files stay nameless: neither table mentions them. They keep the bare
`jc_NNNN` stem.

Usage:
    python model_names.py <exe> <splitDir> [out.json]
"""
import glob
import json
import os
import re
import struct
import sys

import merge_reference as MR

# Where a scene package is loaded, and therefore what to subtract from a pointer
# stored inside one. OVERLAYS.md §1: the packages start at 0x800B248C.
SCENE_BASE = 0x800B248C
# Only the scene/actor packages carry ActorInfo. Scanning the whole archive adds
# nothing but false positives - the one extra hit is a sentence of help text in
# the battle overlay that happens to sit four bytes before a small integer.
ACTOR_FILES = list(range(111, 115)) + list(range(199, 471))
# An actor name is short, starts with a capital and is otherwise letters, spaces
# and apostrophes. Room names ("GARAI'S HOME") live in the same string pool and
# match this too, but they are never pointed at by an ActorInfo.
NAME_RE = re.compile(r"^[A-Z][A-Za-z' ]{1,19}$")

# Named by neither table, identified from their own texture banks instead.
# 831 carries one character portrait plus the game's sword set, and 832 is that
# same portrait with 345 textures of alternate outfits and weapons: the player
# character and his wardrobe. Both are also the only two models whose animation
# records are 64 bytes instead of 60 (RIG_ATTRIBUTION.md), i.e. the only two the
# game treats as the player.
MANUAL = {831: "Levant", 832: "Levant"}


def slug(name):
    """A file-name-safe form of an in-game name: `Old Woman` -> `Old_Woman`."""
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def species_names_by_file(exe):
    """Model file -> the English name of the lowest species that uses it."""
    records = MR.species_records(exe)
    files = MR.model_files(exe)
    names = MR.species_names(exe)
    out = {}
    for sid, (model, _hb, _hr) in enumerate(records):
        if sid >= len(names) or model >= len(files):
            continue
        name = names[sid].strip()
        if name:
            out.setdefault(files[model], name)
    return out


def actor_names_by_file(exe, split_dir):
    """Model file -> NPC name, read out of every scene package's actor records.

    Returns the most frequently seen name per file; a name that appears in many
    packages (Garai stands in nine of them) is the actor's, not an accident.
    """
    files = MR.model_files(exe)
    votes = {}
    for fidx in ACTOR_FILES:
        hits = glob.glob(os.path.join(split_dir, "%04d_*.bin" % fidx))
        if not hits:
            continue
        data = open(hits[0], "rb").read()
        end = len(data)
        for off in range(0, end - 0x14, 4):
            ptr, model = struct.unpack_from("<II", data, off)
            if not (SCENE_BASE <= ptr < SCENE_BASE + end) or model >= len(files):
                continue
            rig, gscale, bscale = struct.unpack_from("<III", data, off + 8)
            if any(v and not (SCENE_BASE <= v < SCENE_BASE + end)
                   for v in (rig, gscale, bscale)):
                continue
            raw = data[ptr - SCENE_BASE:ptr - SCENE_BASE + 40].split(b"\x00")[0]
            if len(raw) < 2:
                continue
            try:
                name = MR._fullwidth_to_ascii(raw.decode("shift_jis")).strip()
            except UnicodeDecodeError:
                continue
            if NAME_RE.match(name):
                votes.setdefault(files[model], {})
                votes[files[model]][name] = votes[files[model]].get(name, 0) + 1
    return {f: max(v.items(), key=lambda kv: (kv[1], kv[0]))[0]
            for f, v in votes.items()}


def resolve(exe, split_dir):
    """Model file -> {"name", "slug", "source"} for every file either table names.

    Species names win over actor names: the species table holds what the game
    shows the player, the actor record sometimes holds Genki's internal
    codename for the same model.
    """
    by_species = species_names_by_file(exe)
    by_actor = actor_names_by_file(exe, split_dir) if split_dir else {}
    out = {}
    for source, table in (("actor", by_actor), ("species", by_species),
                          ("manual", MANUAL)):
        for fidx, name in table.items():
            out[fidx] = {"name": name, "slug": slug(name), "source": source}
    return out


def stems(names):
    """Model file -> export file stem. Nameless files keep the bare index."""
    return {f: "jc_%04d_%s" % (f, e["slug"]) for f, e in names.items()}


def stem(fidx, names):
    """The export stem for one file: `jc_0845_Marrdreg`, or `jc_0834` if unnamed."""
    entry = names.get(fidx)
    return "jc_%04d_%s" % (fidx, entry["slug"]) if entry else "jc_%04d" % fidx


def load(path, exe_path=None, split_dir=None):
    """The cached name map if it exists, otherwise rebuild it from the disc."""
    if path and os.path.exists(path):
        return {int(k): v for k, v in json.load(open(path)).items()}
    return resolve(open(exe_path, "rb").read(), split_dir)


def main():
    exe_path, split_dir = sys.argv[1], sys.argv[2]
    names = resolve(open(exe_path, "rb").read(), split_dir)
    text = json.dumps({"%04d" % f: names[f] for f in sorted(names)},
                      indent=1, sort_keys=True)
    if len(sys.argv) > 3:
        open(sys.argv[3], "w").write(text + "\n")
        print("wrote %s (%d named models)" % (sys.argv[3], len(names)))
    else:
        for f in sorted(names):
            print("%4d  %-9s %s" % (f, names[f]["source"], names[f]["name"]))
        print("# %d models named" % len(names))


if __name__ == "__main__":
    main()
