# Jade Cocoon merge algorithm (reverse-engineered)

Status: **CONFIRMED from binary** (SLES-02201, merge UI overlay = DATA.001 file index 44,
loaded at RAM 0x800B6ED0). This documents mechanics only; no Genki code/data is reproduced.
Function addresses are into the loaded overlay. See `FINDINGS.md` for the struct and the raw
decompilations in `notes/decomp_ovl44/`.

The entry point is `FUN_800BA198(base, material, out, ...)`. "base" is the cocoon you pick
first ("Pick the cocoon to be the base"); "material" is merged into it; "out" is the result.
The whole 0xF8-byte minion struct is first copied from `base`, then fields are overwritten.

## Order of operations (FUN_800BA198)

1. `memcpy(out, base, 0xF8)` — result starts as a clone of the base minion.
2. Palette/type byte (+0x03) taken from a lookup `FUN_8001cdc0(param_4)` unless it returns -1.
3. `FUN_800bad08(out, material)` — **slot/part inheritance** (the "48 slots"): builds the
   0x30-byte `slots[]` (+0x4C) as *first 24 entries from base, remainder from material*,
   then blends 6 growth vectors (+0x04/+0x10/+0x94) pairwise via `FUN_80019af4`.
4. Averages 4 bytes at +0x61 (element tallies): `out[+0x61+i] = (base[+0x61+i] + material[+0xC2+i]) >> 1`.
5. `FUN_800ba538` — **stat down-shift**: `out.stat[i] (+0xB0) = base.stat[i] - base[+0xB6]/20`, 6 stats.
6. `FUN_800ba598` — **affinity blend** per 6 entries via `FUN_800ba63c` (formula below).
7. `FUN_800ba69c` — **GR / element-affinity matrix transform** (below).
8. `FUN_800ba820` — **stat up-shift**: `out.stat[i] += base[+0xB6]/20`, capped at 100.
9. `FUN_800ba8a0` — combine +0xC8 and a 4-byte field at +0x88 via `FUN_80012204`
   (result.f88 = base.f88 + f(base, material)) — looks like an EXP/mana carry.
10. `FUN_800ba8fc` + `FUN_800babdc` — **appearance/body-part composition** over bytes
    +0xDE..+0xF1 (the visual model assembly) and a slot bit-mask cleanup.
11. Sets `out[+0x126]` power flags: bit per element whose level (+0x61,+0xC5,+0x62,+0xC3) > 7.
12. If a computed value >0, spawns the "new cocoon" object.

## The two exact formulas

### Element/affinity blend — `FUN_800ba63c(p1, p2)` (seed K in v0, = seed|0x2493)
```
p1, p2 : each 0..200 (u8)
d   = p1 + p2 - 200
K   = seed | 0x2493            # seed is a per-merge value passed in v0
hi  = ( (d * K) >> 32 )         # signed high word of 32x32 multiply
res = (p1 + p2)/2 + ( (hi + d) >> 2  -  (d >> 31) )
clamp res to [0, 200]
return res & 0xFF
```
This is a fixed-point weighted average biasing two values toward their mean with a
magnitude correction. The `(d>>31)` term is sign rounding. `K` mixes in a merge seed, so
the affinity result has a deterministic-but-seed-dependent component (candidate RNG hook).

### GR element matrix — `FUN_800ba69c`
Recomputes the 4 element affinities at +0xA4 from the 4 element counts at +0xC2:
```
W = [[32,16,32,64],       # s8[4][4] at exe RAM 0x8007B998
     [64,32,16,32],
     [32,64,32,16],
     [16,32,64,32]]
# pre-average step (per element index i, when material > base):
#   c[i] = (base.c[i] + 2*material.c[i]) / 3     else weighted toward base
for j in 0..3:
    affinity[j] = ( sum_i count[i] * W[i][j] ) >> 5     # >>5 == /32
```
Diagonal weight 32 = neutral, 64 = the "opposing/dominant" element, 16 = the weak pairing.
This is the confirmed shape of the community "GR" stat relationship: elements reinforce in
a fixed 4x4 pattern (Water/Fire/Earth/Wind order still to be pinned to indices).

**Confirmed cyclic structure** (from the 64/16 positions in each row): a 4-element wheel
where element i is strong vs (i+3)%4 and weak vs (i+1)%4:
```
  0 --strong--> 3 --strong--> 2 --strong--> 1 --strong--> 0   (and weak the other way)
```
So it is rock-paper-scissors over 4 elements, not two opposing pairs. The name roster
(file 114) confirms 4 families via the ラド/テラ/スク/パタ prefixes on minions 60-143;
mapping each prefix to element index 0-3 needs the in-exe name-element table or a runtime
check.

## Open items
- Pin element index order at +0xC2 (Water/Fire/Earth/Wind vs the ラド/テラ/スク/パタ name prefixes).
- Find the seed source for `FUN_800ba63c` (constant, counter, or RNG).
- Map `slots[]` indices to skill/move names (candidate: files 115-188 or an in-exe table).
- Confirm +0xB0 stat identities (HP/MP/ATK/DEF/... order) via save-state diffing.

## Python reference (structural, from the decompiled logic)
See `tools/merge_reference.py`. It is a faithful transcription of the arithmetic above for
experimentation; it is NOT a drop-in (the full struct field semantics are still being
pinned). It also implements the whole **visual** merge and can write a merged GLB - see
"THE VISUAL MERGE, END TO END" S7.


---

# Update: how merging actually works (2026-08-24)

## The base minion is the body

`FUN_800BA198` starts with `memcpy(out, base, 0xF8)` - the **result keeps the base
cocoon's species and body**. The material minion contributes stats, skills and elemental
character, not its shape. This matches the UI text ("Pick the cocoon to be the base").

Visual change comes from the type/palette byte at +0x03, taken from a per-type table via
`FUN_8001cdc0(n) = 0x8007CA70 + n*4` (values 201-210; -1 means "leave unchanged").
**Superseded** - +0x03 is an *appearance species id* and those ten values are species
201-210, the ten unique models. See "THE VISUAL MERGE, END TO END" S1 and S5.

## Skill slots are elemental families - SUPERSEDED

**The 0x30 bytes at +0x4C are the minion's 48-slot ANCESTRY LIST, not skills, and the
"families of five" are a base species plus its four elemental variants.** The table below
is correct as data and wrong in its labels; see "THE VISUAL MERGE, END TO END" S1.

The 0x30-byte `slots[]` at +0x4C holds skill ids, and `FUN_800BAEA0` tallies them into
families of five: a base id plus four elemental variants. Observed families:

| base | elemental variants |
|------|--------------------|
| 0x03 | 0x45 0x46 0x47 0x48 |
| 0x07 | 0x55 0x56 0x57 0x58 |
| 0x09 | 0x5D 0x5E 0x5F 0x60 |
| 0x0E | 0x71 0x72 0x73 0x74 |
| 0x0F | 0x75 0x76 0x77 0x78 |
| 0x1E | 0xB1 0xB2 0xB3 0xB4 |

So every creature exists in four elemental flavours, which is why merging shifts a minion
along its elemental family (the roster's ラド/テラ/スク/パタ prefixes on minions 60-143).

## The hidden evolution rule - CONFIRMED

`FUN_800BAEA0` returns a **special species id** when the accumulated ancestry crosses a
threshold. If three specific families each have **more than 2** entries, the minion becomes
a unique creature whose exact form is chosen by the byte at +0xC8 (its level):

```
level <= 3   -> species 0x21
     4..6    -> 0x22
     7..11   -> 0x23
    12..17   -> 0x24
    18..24   -> 0x25
    25..30   -> 0x26
    >= 31    -> 0x27
```
A second, separate condition (a different set of four families each above 2) yields 0x23.
Otherwise the function returns 0 and the species is left alone.

This is the mechanic behind "special" minions: they are not a merge recipe of two parents
but a consequence of **accumulating enough skills from the right families**, with the level
at the moment of merging deciding which of the seven forms you get.

## Experience is combined in floating point

`FUN_800BA8A0` does `out.exp += FUN_80012204(base, material)`, and `FUN_80012204` runs on
**doubles** (`__adddf3`), converting each minion's experience out of and back into a packed
two-part representation: `byte[+0x64] * 0x4000000 + int[+0x44]`. So experience is stored as
a coarse exponent plus a fine mantissa and merged by real addition in log-ish space, not by
integer arithmetic - unusual for a PS1 title and easy to get wrong when reimplementing.

## Element relations, from the game's own text

The merge overlay (file 44) spells out the battle relation - each entry reads
"Increases X attack power and decreases effectiveness of Y":

| enhances | suppresses |
|----------|-----------|
| Wind  | Water |
| Water | Wind  |
| Earth | Fire  |
| Fire  | Earth |

So combat effectiveness is **two opposing pairs**: Water vs Wind, Fire vs Earth.

Note this is NOT the same relation as the merge-time GR matrix at `0x8007B998`, whose
64/16 weights form a four-cycle in index space. The two systems are separate: the matrix
transforms elemental affinity during a merge, the text above describes battle damage.
Mapping the matrix's index order onto the named elements is still open.

## What is still open
- Which matrix index is Water/Fire/Earth/Wind.
- The seed source for the `FUN_800ba63c` affinity blend (`v0 | 0x2493`).
- Full slot id -> skill name mapping.


## How the MESH changes when you merge — CORRECTED

**Earlier in this document a previous pass concluded "the mesh is never deformed". That was
wrong.** It was based on verifying that the *archive* holds no morph targets and that the
*battle renderer path* transforms static per-bone vertices — then over-generalising from
"no stored morph data" to "no morphing anywhere".

The decisive argument is combinatorial: **any minion can be merged with any other, any
number of times**, so the resulting shapes cannot possibly be pre-modelled. Players observe
real shape blending — e.g. merging a Skawosp (wasp) into a baby dragon base yields a dragon
whose ears bend toward the wasp's antennae and whose wings grow toward the wasp's, with a
texture that reads as the wasp's palette hue-shifted toward the base.

So the merged mesh is **generated at merge time** by interpolating the two parents'
geometry, and only the *recipe* is persisted.

### Why that is consistent with everything actually verified
- The archive holds one static mesh set per species (verified byte-exactly) — correct, and
  no longer contradictory: the blend result never needs storing on disc.
- The renderer draws static per-bone vertices — correct, because by draw time the blended
  mesh already exists in RAM.
- The minion struct is only 0xF8 bytes, far too small for geometry. **Merged minions persist
  in saves**, so the struct must hold the parameters to rebuild the mesh, not the mesh.

### Where to look next (highest value open thread)
1. **The recipe fields.** Prime candidates inside the 0xF8 struct: the six 12-byte vectors at
   +0x04 / +0x10 / +0x94 (copied wholesale by `FUN_80019AF4`, a 12-byte memcpy, during
   `FUN_800BAD08`), and the five appearance slots at +0xDE. Six 12-byte blocks is a
   suspicious shape for per-body-region blend parameters.
2. **The generator.** Find code that reads TWO mesh objects and writes a THIRD. The mesh
   allocator is `FUN_8002269C` (sizes the runtime records from the 10 chunk counts) and the
   builder is `FUN_8002188C`; a merge-time generator would plausibly call the same allocator
   with counts derived from a parent. Cross-reference writers of `MODEL+0x50`.
3. **Runtime is the cheap route here.** Breakpoint the mesh allocator while performing a
   merge in-game, then diff the produced mesh against both parents' meshes. That answers in
   minutes what static tracing would take hours to pin, and directly reveals the
   interpolation rule (per-vertex lerp? per-part weights? per-bone?).

Note the texture behaviour is a further clue: the result appears to use the *material's*
texture with a hue shift, which suggests the palette is also generated (CLUT blending),
not just selected from the 201-210 table.


---

# THE MESH MERGE — SOLVED (2026-08-24, static, from the binary)

Everything below is read off `SLES_022.01`; the generator is in the **main exe**, not the
merge overlay. Entry point: **`FUN_80010DB0`** — *BuildMergedModel(job)*.

## Short version

A merged minion's mesh is a **per-vertex linear blend (morph) of up to three parent
meshes**, computed once at merge time into a freshly allocated model. It works because the
mergeable minions all share **one identical mesh topology** — same 25 mesh objects, same
primitive counts, same vertex order — so vertex *i* of one creature corresponds to vertex
*i* of every other. Blended alongside the vertices are the normals, the rest skeleton, the
attachment markers, the growth scales, and the body-part on/off flags.

Nothing about this is stored on disc: only the recipe (which parents, which weights) has to
survive a save.

## The data each model carries — `MODEL+0x4C`, the "appearance blob"

Package section 0 (`{u32 size; u8 blob[size]}`) is copied verbatim into `MODEL+0x4C` by
`FUN_8002607C` (size at `MODEL+0x48`). For model file 833 it is 0x1070 bytes.

```c
struct AppearanceBlob {
  /* +0x00 */ u32 offAnimTable;   // -> {u32 count; ...}      (29 entries in 833)
  /* +0x04 */ u32 offMarkers;     // -> Marker[43], -1 terminated
  /* +0x08 */ u32 offStages;      // -> {u32 stageCount; u32 boneCount; Stage stages[]}
};

struct Marker {                   // 12 bytes; FUN_80018908 searches by id
  s16 id;        // 0..42 ; id 0x26 (38) = the ground/foot reference point
  s16 bone;      // which bone it rides
  s16 x, y, z;   // local offset
  s16 unk;
};

struct Stage {                    // 0x160 bytes in 833; size is explicit at +0x14
  /* +0x00 */ u32 offGlobalScale; // -> s32 vec[3]   (1.12 fixed)
  /* +0x04 */ u32 offBoneScale;   // -> {s16 x,y,z,pad}[boneCount]  (1.12 fixed)
  /* +0x08 */ u32 offPartFlagsA;  // -> s16[3]
  /* +0x0C */ u32 offPartFlagsB;  // -> s16[3]
  /* +0x10 */ u32 offMeshWeights; // -> s32[boneCount]   per-mesh-object blend weight
  /* +0x14 */ u32 size;           // stride to the next Stage
};
```

Accessors: `FUN_80024EA0` = animTable, `FUN_80024ECC` = markers, `FUN_80025010(model,stage)`
walks the Stage list, and `FUN_80024EF8 / F30 / F68 / FA0 / FD8` return the five Stage
fields.

### The five Stages are the five GROWTH steps

File 833's five stages carry global scales **1638, 2252, 2867, 3481, 4096** (0.40, 0.55,
0.70, 0.85, 1.00 in 1.12 fixed) — evenly spaced from hatchling to adult. Their per-bone
scale arrays encode **baby proportions**: at stage 0 the head and limb bones run 1.5x-2.0x
while the body and tail run 0.4x-0.6x; at stage 4 every bone is exactly 4096 (unity). So a
minion does not merely get bigger as it grows, it re-proportions.

### Part flags = the three swappable body-part groups

`FUN_80019B14(actorBoneTable, partFlagsA, partFlagsB)` walks 25 bones three times, using
three fixed bone bitmasks in the exe:

| mask | address | bones | body part |
|------|---------|-------|-----------|
| 0 | `0x80072F60` = 0x000001F8 | 3-8   | the two front limbs / arms |
| 1 | `0x80072F64` = 0x0000F000 | 12-15 | the two wings |
| 2 | `0x80072F68` = 0x007E0000 | 17-22 | the two rear legs |

- `partFlagsA[i] < 2` -> **clear bit 1 of `boneRec+6` for every bone in mask i** — the whole
  group vanishes (bit 1 gates both the transform and the draw in `FUN_80047E4C`).
- `partFlagsB[i] == 0` -> set bit 4, which is ORed into the primitive draw mode.

Observed per species: 833 `(2,2,3)`, 845 `(3,1,3)` (no wings), 860 `(1,2,3)` (no arms),
929 `(3,3,3)`. So "does this creature have arms / wings / legs" is three numbers.

## The generator — `FUN_80010DB0(job)`

```c
struct MergeJob {
  /* [0]    */ ResourceMgr *out;   // receives the freshly allocated model set
  /* [1]    */ int nSources;       // 1..3
  /* [2..4] */ int srcModelId[3];
  /* [5..7] */ int weight[3];      // 1.12 fixed, meant to sum to 4096
  /* [8]    */ int stage;          // which of the 5 growth stages
  /* [0xC]  */ int dominant;       // which source donates part count / marker table
  /* [0xD]  */ int dirCount;
  /* [0xE]  */ int state;          // set to 3 on completion
};
```

1. Resolve the three source `MODEL`s (`FUN_80024DD8`), allocate a new model set
   (`FUN_80024B44`).
2. **Take source 0's mesh wholesale**: `dst->meshArray(+0x50) = src0->meshArray`, mesh count
   copied too, and `src0->meshArray` is nulled — ownership moves, and the blend then
   *mutates* that array in place. This is why the base cocoon's model is the body.
3. **Per mesh object i (one per bone)**, pull the three per-mesh weights from each source's
   Stage (`FUN_80024FD8`). If all three agree, fall back to the job's global weights;
   otherwise scale the job weights by the per-mesh ones. Normalise to 4096. Then for source
   1 and source 2, if that source's weight is non-zero:
   ```
   FUN_80039FE8(srcMesh_i, dstMesh_i, srcMesh_i);            // srcMesh_i = srcMesh_i - dstMesh_i
   FUN_8003A6C8(w,         dstMesh_i, dstMesh_i, srcMesh_i); // dstMesh_i += w * delta
   ```
   i.e. **`dst = lerp(dst, src, w)` per vertex**, done twice to fold in both other parents.
4. Blend the five Stages' global-scale vectors by the same weights.
5. Allocate a **new one-frame animation** for the result (`FUN_80026798`, rest-offset array
   `count*6`, key array `(count+2)*6`).
6. `FUN_8004A520` blends the **skeleton**: per bone it lerps the rest offsets (bone lengths)
   from all three parents and lerps the frame-0 X rotation in modular 4096-unit angle space
   (wrapped to +-2048 so it takes the short way round), writing a new rest pose.
7. Merge the part flags pairwise: `if (other.A[k] > 1 && mine.A[k] == 1) mine.A[k] = 2` —
   **a wingless minion merged with a winged one gains wings.**
8. `FUN_80011904` blends the **43 attachment markers**, in IEEE float, weight/4096 each.
9. Transfer the dominant parent's appearance blob to the result, run `FUN_80046A7C` to build
   world bone positions, then look up marker id 0x26, transform it by its bone matrix, and
   **subtract its world Y from the root bone's rest offset** — regrounding the blended
   creature so its feet touch the floor.

### The two blend primitives, exactly

`FUN_80039FE8(a, b, out)` — for every SVECTOR of every primitive of every type, plus both
seam-vertex pools: `out.xyz = a.xyz - b.xyz`.

`FUN_8003A6C8(w, out, a, b)` — same walk, `out = (0x1000*a + w*b) >> 12`, done with
`gte_LoadAverageShort12` (GTE `GPF12`/`GPL12`), and for the seam pools with explicit
`gte_gpf12`/`gte_gpl12` pairs.

Both walk **all ten** entries of the 0x54-byte runtime mesh object, and the SVECTOR offsets
inside each primitive match the documented runtime record layout exactly:

| type | stride | first SVECTOR | count |
|------|--------|---------------|-------|
| F3  | 0x24 | +0x04 | 4 (normal + 3 verts) |
| G3  | 0x3C | +0x0C | 6 (3 normals + 3 verts) |
| FT3 | 0x30 | +0x10 | 4 |
| GT3 | 0x48 | +0x18 | 6 |
| F4  | 0x2C | +0x04 | 5 |
| G4  | 0x50 | +0x10 | 8 |
| FT4 | 0x38 | +0x10 | 5 |
| GT4 | 0x5C | +0x1C | 8 |
| pool A (+0x40/+0x44) | 0x14 | +0x04 and +0x0C | 2 |
| pool B (+0x48/+0x50) | 0x14 | +0x04 and +0x0C | 2 |

**Normals are blended too**, not recomputed.

## Why it works: 49 models share one topology — VERIFIED

Scanning all 1079 archive sub-files for valid mesh blocks finds **106 files** holding
**104 distinct meshes** (files 831-933, plus 10, 197, 1072). Grouping them by their exact
primitive-count signature (per type, per mesh object) gives **58 signatures**, and one of
them contains **49 files**:

```
833 834 845 846 847 850 851 852 853 856 857 858 859 860 861 862 864 865 866 867 868
872 873 874 883 892 895 898 899 900 901 907 908 909 912 913 914 915 916 917 918 919
920 921 922 923 924 929 932
```

All 25 mesh objects, all identical primitive counts, all 32976 bytes of mesh stream, all
using the 25-bone rig at `0x80079064`. That is a hand-authored **morph family** — the set
of minions that can be merged with each other. The remaining 55 meshes are one-offs
(bosses, NPCs, story creatures) and are not part of the blend space.

## What is applied at draw time (not baked)

`FUN_8001FA58` then `FUN_8001FD70` then `FUN_80047E4C`, per frame:

```
actor[0x26]          animated master scale, ramps toward actor[0x2A] by actor[0x28]/frame
actor[0x2C..0x34]  = stageGlobalScale(actor[0x138..0x140]) * actor[0x26] >> 12
boneTranslation[b] *= perBoneScale[b] / 4096                  // FUN_80047E4C
boneMatrix[b]       = boneMatrix[b] * diag(perBoneScale[b]) * diag(actor[0x2C..0x34])
```

The per-bone scale array reaches the actor through `spawnParams+0x3C` (`FUN_8001E858` copies
it to `actor+0x144`, defaulting to the unity vector at `0x80073FD4 = {4096,4096,4096,0}`),
and the growth vector through `spawnParams+0x38` -> `actor+0x138`. So the runtime still
applies **per-bone non-uniform scale** and a **whole-body scale** on top of the already
blended geometry. Growth (stage 0 -> 4) is pure scale; merging is a real vertex morph.

## Corrections to earlier notes in this file

- The six 12-byte blocks at minion struct `+0x04` are **not** blend parameters.
  `FUN_800BAD08` shuffles them as
  `[base.self, material.self, base.p0, base.p1, material.p0, material.p1]`, and
  `FUN_800BC550` passes `+0x94` straight to the string renderer `FUN_8002FAFC` — they are
  the minion's **name** (12 bytes) and its **six ancestors' names**, with a parallel 6-byte
  flag array at `+0x7C` (own flag at `+0xC6`). Merge history for the UI, nothing more.
- `FUN_8002269C` is not the merge-time allocator; the merged mesh reuses the base's existing
  mesh array in place.
- The "mesh block" at file 833 sectors 0-3 — previously listed as
  "833 (2nd, small), 4208 bytes, 12 bones, offVerts 0x6DC, offIdx 0x988" — is not a mesh
  block at all. It is the **appearance blob** above (`0x6DC` = markers, `0x988` = growth
  stages).



---

# THE VISUAL MERGE, END TO END (2026-08-25)

Everything above described *pieces*. This section is the whole chain, from the byte in
the minion struct that says "you are a Skawosp" to the hue-rotated palette on the
creature the game hands back. It closes open threads 1, 2 and 3 from `START_HERE.md`.

Read off `SLES_022.01` and the overlay images; status tags follow `FINDINGS.md`.
Function addresses in the main exe are absolute; overlay 44 is pinned at `0x800B6ED0`
and overlay 27/28 at `0x800A0530` (`OVERLAYS.md` §1).

## 0. The one-paragraph version

A merged creature is **not** chosen from a table. Its body is a per-vertex blend of up to
three parent meshes; which three, and in what proportion, is read off the minion's own
**48-slot ancestry list** — the three species that appear most often in it, weighted by
how often. Its skeleton is the same blend applied to bone lengths. Its texture is *not*
blended: one parent's texture section is loaded whole and its **palette is rotated around
the colour wheel** by an angle computed from the minion's four elemental tallies. All of
it is generated at merge time by an asynchronous job in the main exe; only the recipe
survives a save.

## 1. The pieces of the minion struct the visual merge reads

**CONFIRMED.** Four fields, and nothing else:

| offset | size | what it is |
|---|---|---|
| `+0x02` | u8 | **species id** — the creature's true species; picks its own mesh |
| `+0x03` | u8 | **appearance species id** — picks the texture and the palette reference |
| `+0x4C` | u8[48] | **the ancestry list** — one species id per slot; the merge recipe |
| `+0xC2` | u8[4] | the four **element tallies** — the palette hue |
| `+0xC8` | u8 | level — picks the growth stage |

### `slots[]` at +0x4C is the ancestry, not a skill list — CORRECTION

An earlier pass in this document called the 0x30-byte array at `+0x4C` a table of *skill
ids* and noted that they fall into "elemental families of five". That reading is wrong in
its labels and right in its structure, and the correct label explains the structure.

`FUN_80033938` builds a **histogram of the 48 slots over 211 buckets**, and 211 is exactly
the length of the game's species roster (§3). The "families of five" that `FUN_800BAEA0`
tallies are a base species plus its four elemental variants:

| what the old note called it | what it is |
|---|---|
| base skill `0x03`, variants `0x45 0x46 0x47 0x48` | species 3, variants 69-72 — all model 18 |
| `0x07` / `0x55-0x58` | species 7, variants 85-88 — all model 25 |
| `0x09` / `0x5D-0x60` | species 9, variants 93-96 — all model 27 |
| `0x0E` / `0x71-0x74` | species 14, variants 113-116 — all model 33 |
| `0x0F` / `0x75-0x78` | species 15, variants 117-120 — all model 41 |
| `0x1E` / `0xB1-0xB4` | species 30, variants 177-180 — all model 98 |

All six fit `variant(base b, element e) = 57 + b*4 + e` exactly, which is the species
table's own layout (§3). So the community's "48 merge slots" are literally the creature's
48 remembered ancestors, and the "hidden evolution rule" is "your ancestry contains more
than two members of each of three particular species families".

## 2. Who fills the MergeJob — OPEN THREAD 1, CLOSED

**CONFIRMED.** `FUN_80010DB0` never seems to have a caller that builds its argument,
because the job is not built by a caller at all: it is **memcpy'd in whole** by the job's
constructor.

### The job struct — corrected and completed

0x40 bytes, allocated by `FUN_80010850`. Byte offsets, not word indices:

```c
struct MergeJob {
  /* +0x00 */ ResourceMgr *out;      // set to 0 at creation, filled by state 1
  /* --- the 0x34-byte RECIPE, memcpy'd verbatim from the caller --- */
  /* +0x04 */ s32  nSources;         // 1..3
  /* +0x08 */ s32  srcModelId[3];    // model ids, not file indices
  /* +0x14 */ s32  weight[3];        // 1.12 fixed, summing to 4096
  /* +0x20 */ s32  stage;            // growth stage 0..4
  /* +0x24 */ s32  texSourceIndex;   // which source donates the texture, if no override
  /* +0x28 */ s32  hueDegrees;       // palette rotation, 0..359
  /* +0x2C */ s32  texModelId;       // >= 0: take the texture from THIS model instead
  /* +0x30 */ s32  dominant;         // whose appearance blob and markers the result keeps
  /* +0x34 */ ResourceDir *dir;      // the 16-byte resource directory to allocate from
  /* --- end of the recipe --- */
  /* +0x38 */ s32  state;
  /* +0x3C */ s32  nextState;        // where the wait state returns to
};
```

`+0x34` was previously written down as `dirCount`. It is a **pointer** to a resource
directory (`FUN_80026668` counts its 16-byte entries up to the `0xFFFF` terminator); the
merged model is allocated out of `dir + 0x20`, i.e. a second, shorter directory that sits
right after the one the sources were loaded into.

### The job is a five-state pump

**CONFIRMED.** `FUN_80010AD8(job)` is a jump-table loop over `job->state` (table at
`0x80071A84`, six entries). Each handler returns non-zero to keep stepping and zero to
yield until the next tick. Ghidra never found this function on its own because nothing
`jal`s the handlers — they are only reachable through the jump table.

| state | handler | what it does |
|---|---|---|
| 1 | `FUN_80010B90` | allocate the resource manager from `dir`, then queue a load of each of the three sources — **appearance blob + mesh + resident animations, deliberately *not* the textures**. The one whose index equals `dominant` is loaded with a flag set. Then `state = 4, nextState = 2` |
| 4 | `FUN_80010C30` | poll every resource record; while any load is still in flight, return 0 and yield. When all are idle, `state = nextState` |
| 2 | `FUN_80010DB0` | build the merged model (§4). Ends with `state = 3` |
| 3 | `FUN_80010CDC` | queue **the texture load** (§5) and then the *dominant* parent's resident animation container. `state = 4, nextState = 5` |
| 5 | — | done; the pump returns 1 |
| 0 | — | idle |

Lifecycle, all in the main exe:

```
FUN_80010850(recipe)   creates a scheduler task, allocates the 0x40-byte job,
                       memcpy(job+0x04, recipe, 0x34), state = 1, kicks the pump.
                       Returns a task handle.
FUN_80010A44()         returns the finished model array once state == 5.
FUN_8001098C()         waits for state == 5, frees the manager and the job.
```

### The recipe builder lives in the overlays — four copies of it

**CONFIRMED.** Scanning every archive sub-file for `jal 0x80010850` finds exactly four
callers: files **26, 28, 36 and 44**. File 44 is the merge UI; file 28 is the battle
overlay's slot-mate (files 23-28 share the `0x800A0530` load address, and 27 is
`ENMBATLE.C`); 36 is a third consumer. Files 28, 36 and 44 each also call `FUN_80033938`,
so the recipe rule below is the game's, not the UI's.

In overlay 44 the sequence is a three-liner at `0x800BF694`:

```c
slot = 0x800C0BB8;                       // {handle, minion*, recipe[0x34], ...}
FUN_800BF208(minion, &slot->recipe, resourceDirectory);
slot->minion = minion;
slot->handle = FUN_80010850(&slot->recipe);
```

### `FUN_800BF208(minion, recipe, resourceDir)` — the recipe, exactly

**CONFIRMED**, read instruction by instruction from the overlay image.

```c
own = SpeciesRec(minion[0x02]).modelId;        // the minion's own model

// 1. the three most common ancestors, and their share of the 48 slots
recipe->nSources = FUN_80033938(&minion[0x4C], species[3], weight[3]);
for (i = 0; i < 3; i++) {
    recipe->srcModelId[i] = SpeciesRec(species[i]).modelId;
    recipe->weight[i]     = weight[i];
}

// 2. collapse duplicates: two ancestors of different species can share a model
if (m0 == m1 && m1 == m2)  { n = 1; w0 += w1;  w1 = w2 = 0; }
else if (m0 == m1)         { n = 2; w0 += w1;  m1 = m2; w1 = w2; w2 = 0; }
else if (m0 == m2)         { n = 2; w0 += w2;  w2 = 0; }
else if (m1 == m2)         { n = 2; w1 += w2;  w2 = 0; }

// 3. force the minion's OWN model into slot 0 - it is the body
recipe->dominant = 0;
if (m0 != own) {
    if      (m1 == own) swap(slot0, slot1);
    else if (m2 == own) swap(slot0, slot2);
    else {                       // not an ancestor of itself: push everything down
        (n < 2 ? slot1 : slot2) = slot0;
        m0 = own; w0 = 0;
        n  = (n < 2 ? 2 : 3);
    }
}

// 4. growth, texture, palette
recipe->stage          = FUN_80019A80(minion[0xC8]);      // level -> stage 0..4
recipe->texSourceIndex = recipe->nSources - 1;
recipe->texModelId     = SpeciesRec(minion[0x03]).modelId;
recipe->hueDegrees     = FUN_800BF4C0(&minion[0xC2]);     // see §5
if (recipe->hueDegrees != -1000)
     recipe->hueDegrees = (recipe->hueDegrees - SpeciesRec(minion[0x03]).hueRef * 2) % 360;
else recipe->hueDegrees =                       SpeciesRec(minion[0x03]).hueBase * 2;
recipe->dir            = resourceDirectory;
```

Step 3 is the mechanical reason "the base cocoon keeps its body": `FUN_80010DB0` takes
source 0's mesh array wholesale and lerps the others into it, and source 0 is always the
minion's own species — with weight 0 if it is not in its own ancestry, which makes the
blend start from its shape and move away from it.

### `FUN_80033938(ancestry, outSpecies[3], outWeight[3])` — CONFIRMED

```c
u8 hist[211] = {0};
for (i = 0; i < 48; i++) hist[ancestry[i]]++;

n = 0;
for (count = 255; count >= 0; count--)          // descending multiplicity
    for (id = 0; id < 211; id++)                // ties broken by lower species id
        if (hist[id] >= count) {
            outSpecies[n] = (count ? id : outSpecies[0]);   // pad with source 0
            outWeight[n]  = count;
            hist[id] = 0;
            if (++n > 2) goto done;
        }
done:
    s = w0 + w1 + w2;
    for (i = 0; i < 3; i++) outWeight[i] = (outWeight[i] << 12) / s;   // -> 4096
    return  the number of entries with a non-zero count;
```

So a creature whose ancestry is 30 x species 12, 12 x species 7 and 6 x species 3 merges
as `{12, 7, 3}` at weights `{2560, 1024, 512}` — 30/48, 12/48 and 6/48 of 4096.
`tools/merge_reference.py::recipe_from_ancestry` is this function.

## 3. Species -> model file — OPEN THREAD 3, CLOSED

**CONFIRMED.** `FUN_80019C70(id)` is a one-line accessor into a 4-byte-per-entry table at
**`0x8007BC54`**. The region runs to the growth-stage thresholds at `0x8007C208`, so it
holds exactly **365 entries**; `FUN_80033938`'s 211-bucket histogram independently fixes
the *usable roster* at ids **0-210**.

```c
struct SpeciesRec {          // 0x8007BC54[365]
  u16 modelId;   // index into the model descriptor table at 0x800823F0
  u8  hueBase;   // palette angle in units of 2 degrees, used when the minion is single-element
  u8  hueRef;    // reference angle of this model's stored texture, in units of 2 degrees
};
```

The same table is read by the battle-enemy spawner (`ovl_800A1F10`), the scene-package
actor spawner (`ovl_800B25F4`) and the merge recipe builder — it is *the* species table.
Model id -> DATA.001 file index is the descriptor table's first `u16`, so this is a
complete species -> file map. `tools/merge_reference.py species <exe> <out>` dumps it;
the generated copy lives at `extracted/species_index.txt`.

### Its shape, and why that shape is a proof

| ids | count | what |
|---|---|---|
| 0-35 | 36 | the **base creatures** — one model file each |
| 36-56 | 21 | **specials**: story creatures, bosses, evolutions |
| 57-200 | 144 | the **four elemental variants** of each base creature: `57 + base*4 + element` |
| 201-210 | 10 | ten more uniques (models 83-92, files 914-923) |
| 211-364 | 154 | a **second, parallel table** covering ids 57-210 again at `id + 154`, with different hue pairs. No accessor for it has been found. **HYPOTHESIS**: an alternate palette set |

Cross-checks that all pass:

- Every one of the 144 variant entries has the **same `modelId` as its base species**, and
  the four hue values in each group are a **rigid 90-degree rotation** of one another —
  36 of 36 groups, no exceptions. Four elemental flavours of one mesh, four palettes 90
  degrees apart, exactly as the roster's four name prefixes suggested.
- **All 36 base species, all 144 variants and all 10 uniques resolve to files inside the
  49-model morph family.** 353 of 365 entries do. Nothing in this table's construction
  knows about the morph family; that they coincide is the confirmation that the family is
  the mergeable roster.
- The 12 entries that are *not* morph-family are all **specials** (ids 36-56), and their
  files are `835 836 837 838 839 840 841 870 876 893 930` — the one-off bosses.

**HYPOTHESIS**, worth a session of its own: five of those special files (**840, 841, 870,
893, 930**) are exactly the models whose skeleton `OVERLAYS.md` §7 could not find. So the
missing rigs belong to creatures that *do* have species ids and can therefore be party
minions. Tested and rejected as a shortcut: putting 870 on the exe's 25-bone creature rig
with its own 26-bone clips scores **95** against the 23-bone assignment's 55, and 893/930's
24-bone clips are shorter than a 25-bone rig so they cannot run on it at all. The lead is
that these creatures reach the renderer through a *third* spawn path, not that the
creature rig is the answer.

Species 43-48 land on files 838, 837, 836, 835, 840, 839 in that order, and 834 is the one
morph-family file no species names.

## 4. The geometry blend, corrected in two places

The description under "THE MESH MERGE — SOLVED" is right; two details were not exact.

### The per-mesh weights are a hard override, not a soft weight — CORRECTED

`FUN_80010DB0` pulls, for each mesh object, each source's own weight out of that source's
growth stage (`FUN_80024FD8`). The arithmetic, transcribed instruction for instruction:

```c
a = meshWeight[src0][i];  b = meshWeight[src1][i];  c = meshWeight[src2][i];
if (a == b && b == c) { w = jobWeight; }          // the usual case
else {
    t  = a + b + c;
    a  = (a << 12) / t;
    b  = (b << 12) / (a + b + c);                 // note: `a` is already the NEW a
    c  = (c << 12) / (a + b + c);                 // and so are `a` and `b` here
    w  = { a * jobWeight[0], b * jobWeight[1], c * jobWeight[2] };
}
for (i = 0; i < 3; i++)                            // same cascading denominator again
    w[i] = (w[i] << 12) / (w[0] + w[1] + w[2]);
```

The cascading denominator — each division's divisor already containing the results of the
previous ones — is in the original and is reproduced verbatim in
`merge_reference.py::mesh_object_weights`. It is almost certainly not what was intended,
but it is what runs.

**Measured across the whole archive: only three models carry a non-zero per-mesh weight at
all** — 845 (stage 0, mesh 10, value 2), 861 (stage 3, mesh 9, value 1) and 868 (stage 4,
mesh 5, value 2). Every other model's array is all zeros in every stage. So the
`a == b == c` branch fires for essentially every mesh object of every merge, and the
global weights are used unchanged. When a stray value *does* appear, the maths above sends
that mesh object to **100% of the parent that carries it**: with the other two at zero, the
normalisation collapses to `{0, 0, 4096}`. It is a per-body-part *override*, not a
per-body-part weight, and it is used three times in the entire game.

*(All three zero is caught by the equality test, so there is no divide by zero there — but
a non-zero per-mesh weight on a source whose global weight is zero would divide by zero.
It cannot happen with the three values that exist.)*

### On-disc SVECTOR runs, so the blend can be done outside the runtime

**CONFIRMED.** The blend walks the *runtime* mesh records. The on-disc chunk bodies hold
the same vectors with the loader's extra UV and colour fields removed, so the same blend
can be applied straight to the archive bytes:

| type | on-disc body | first SVECTOR | count |
|---|---|---|---|
| F3  | 0x24 | +0x04 | 4 |
| G3  | 0x3C | +0x0C | 6 |
| FT3 | 0x24 | +0x04 | 4 |
| GT3 | 0x40 | +0x10 | 6 |
| F4  | 0x2C | +0x04 | 5 |
| G4  | 0x50 | +0x10 | 8 |
| FT4 | 0x2C | +0x04 | 5 |
| GT4 | 0x54 | +0x14 | 8 |
| seam item (types 8, 9) | 0x14 | +0x00 and +0x08 | 2 |

Every row satisfies `first + count*8 == body`, exactly filling the chunk — which is the
self-check that the runs are right. Only the first three shorts of each slot are blended;
the fourth carries UVs or padding and survives from source 0, which is why **a merged
creature keeps the base's UV layout**.

## 5. The texture — OPEN THREAD 2, CLOSED

**CONFIRMED. The texture is selected, not blended. The palette is rotated.**

### Selected

The merge job's state 3 (`FUN_80010CDC`) is the only caller of `FUN_80025658` and
`FUN_80025720` in the whole executable — they exist for the merge and nothing else.

```c
id = (job->texModelId >= 0) ? job->texModelId
                            : job->srcModelId[job->texSourceIndex];
result->modelId = id;
FUN_80025658(mgr, id, job->hueDegrees);            // load section 1: THE TEXTURES
result->modelId = job->srcModelId[job->dominant];
FUN_80025720(mgr);                                 // load section 3: that parent's animations
```

Because `texModelId` is filled from a `u16` load it is never negative, so in the merge UI
the texture *always* comes from the appearance species at minion `+0x03`; the
`texSourceIndex` path is a fallback for a caller that writes -1.

Note what state 1 loaded and what it did not: the three sources came in **without their
textures** (sections 0, 2 and 3 only). Nothing else would make sense if the palettes were
being combined — there is only ever one texture set in memory for a merged creature.

### The model descriptor is (start, size) pairs — CORRECTED

`MODEL_FORMAT.md` reads the descriptor at `0x800823F0` as "(sizeSectors, cumulativeEnd)
pairs". The loaders read the same numbers as **(startSector, sizeSectors)** pairs, one per
section, and that is the reading the code actually uses:

```c
u16 fileIdx;                 // [0]
u16 start0, size0;           // [1][2]  appearance blob
u16 start1, size1;           // [3][4]  textures
u16 start2, size2;           // [5][6]  mesh
u16 start3, size3;           // [7][8]  resident animations
u16 slotBase;                // [9]     -> the per-animation streamed sector table
```

A load carries a **section bitmask**: `1` = blob, `2` = textures, `4` = mesh, `8` =
animations (`FUN_80025DE4` stores one base pointer per set bit, advancing by that
section's size). `FUN_80025268(mgr, id, -1, ...)` loads `1|4|8`; `FUN_80025658` loads `2`
alone; `FUN_80025720` loads `8` alone. `tools/model_index.py::sections` already returns the
right numbers.

### Rotated

The resource-load parameter block has a field at `+0x08` that `FUN_80025F38` initialises
to **-1**, and `FUN_80025658` is the only place it is ever set to something else. Its
consumer is the texture installer:

```c
FUN_800260E4(load):
    if (load->hue != -1) {
        FUN_80029044(0, 0, 0, load->texBase, timCount, load->vramPlacement + 4, load->hue);
        model->0x34 = load->hue;         // the result remembers its own rotation
    }
```

`FUN_80029044` walks the texture container — the ordinary
`{u32 count; u32 offsets[count]}` pack of TIMs — and for each TIM calls
**`FUN_80029D68(tim, degrees)`** before uploading it. For every ordinary load the field is
-1 and nothing happens; **only a merged creature is ever hue-rotated.**

`FUN_80029D68` is a palette rotation on a **192-step hue circle**:

```c
delta = (degrees * 24) / 45;               // 360 degrees -> 192 steps, integer division
for each of the CLUT's entries:
    (r,g,b) = unpack BGR555                          // 5 bits each
    hsv = FUN_80029F10(r,g,b)                        // H 0..191, S 0..31, V 0..31
    if (hsv is achromatic) continue;                 // S == 0 -> left exactly alone
    hsv.h = (hsv.h + delta) % 192;
    write back FUN_8002A0A8(hsv)                     // six 32-wide sectors
```

Saturation, value and the semi-transparency bit are untouched, and greys are skipped
entirely — which is exactly the behaviour players describe: a merged creature's colours
shift while its whites, blacks and eyes stay put. Every TIM in every model file measured
carries `clutHeight == 1`, so "the first `clutWidth` entries" is the whole palette and
there is no partial-rotation caveat.

### Where the angle comes from

**CONFIRMED.** `FUN_800BF4C0(&minion[0xC2])` turns the four element tallies into a hue.

The four elements are four unit directions **90 degrees apart** — the game reads them out
of its 4096-entry sine table at `0x80084464` as entries 739, 1763, 2787 and 3811, which is
`sin(i * 360/4096)` at 64.95, 154.95, 244.95 and 334.95 degrees. The tallies are summed as
a 2-D vector and the angle of that sum is the creature's hue:

```
x = sum_k  count[k] * sin(theta_k)
y = sum_k  count[k] * sin(theta_k - 90)
hue = ratan2(y, x), rescaled to whole degrees        (FUN_8003B570: (3a * 120) >> 12)
```

Two fast paths, and one sentinel:

- **exactly one non-zero tally** -> return `-1000`, and the caller uses the appearance
  species' own stored `hueBase * 2` instead. A pure-element creature has a designed
  colour, not a computed one.
- tallies in only elements 1 and 3 -> `65` if `count1 >= count3` else `245`;
  only elements 0 and 2 -> `155` if `count2 >= count0` else `335`. These are the element
  directions themselves, and they exist because the general formula degenerates when two
  opposite tallies are exactly equal — the vector sum would be zero.

Then `hue = (hue - hueRef * 2) mod 360`: the stored texture's own hue is subtracted so the
rotation is a *delta*, not an absolute.

The proof that `hueBase` and `hueRef` really are palette angles: **the four elemental
variants of every one of the 36 base species differ by exactly 90 degrees of `hueBase`**,
in the same order as the four element directions, 36 groups out of 36. For model 12
(file 845) the four variant angles are 310, 40, 130 and 220 degrees against element
directions 334, 64, 154 and 244 — a constant 24-degree offset, which is precisely that
species' `hueRef * 2`. **HYPOTHESIS**: `hueBase` was meant to equal
`elementDirection - hueRef*2` for every species. It does for three of the 36; the rest are
within about 30 degrees, so the two bytes are independent hand-authored values and the
exact relation should not be assumed.

## 6. Verifying the "49 models share one topology" claim — VERIFIED, with one exception

The earlier claim was checked by primitive-count signature. Checked harder this session,
against the archive bytes:

- **All 49 files have a byte-for-byte identical chunk-stream *structure*** — 25 mesh
  objects, the same chunk types in the same order, the same body sizes, 32,976 bytes
  consumed. Vertex *i* of one really is vertex *i* of every other.
- **48 of 49 also have a byte-identical seam-quad table**: 68 quads, same md5.
  **Model 850 has 64 quads** and a different table, and its mesh block totals 34,000 bytes
  where the other 48 total 34,064 — the 64-byte difference is those four quads. 850 also
  packs its sections differently (blob 1 sector, not 3). It blends fine: the seam table
  belongs to source 0, which the result takes wholesale.

### The current GLB export is NOT vertex-order identical — checked, and it is not

The question was whether the exported family can be used as each other's shape keys today.
**It cannot.** Every family member exports to 1,576 vertices (1,560 for 850), but split
across a **different number of primitives**: 3 for a creature that shows every body part,
4 when one group is hidden, 6 when all three are. `export_gltf.py` deliberately puts each
hidden body-part group in its own node (`hidden_arms`, `hidden_wings`, `hidden_legs`) so
the merge's part-flag rule stays visible, and the split changes the layout.

Measured: 22 of 49 match model 833's primitive list exactly; the other 27 differ only by
that grouping (and 850 by its 16 missing seam vertices). Blending at the **archive** level,
before the export splits anything, sidesteps this entirely — which is what
`merge_reference.py` does.

## 7. The reference implementation

`tools/merge_reference.py` now covers the visual merge as well as the stat math, and can
write a merged GLB.

```bash
cd tools
python merge_reference.py                                   # self-test
python merge_reference.py species ../extracted/SLES_022.01 ../extracted/species_index.txt
python merge_reference.py merge ../extracted/SLES_022.01 ../extracted/DATA001_split \
       ../models/merged/merge_833x867_50.glb \
       --sources 833,867 --weights 2048,2048
```

Options: `--sources` (one to three DATA.001 file indices, the first is the base body),
`--weights` (1.12 fixed, summing to 4096), `--stage 0..4`, `--texture-from <file>`,
`--hue <degrees>`, `--no-pose`, `--animslots` / `--index`.

What it does, in the game's order: blends every mesh object's SVECTOR runs and both seam
pools into a copy of the base's package; blends the rest-offset array of every animation
block; ORs the body-part flags; optionally splices in another model's texture section and
rotates its palettes; then hands the package to the normal `export_gltf.py`.

Numerically verified against the archive over the 2,889 blended SVECTOR slots of a
833 x 867 merge (2,775 of which genuinely differ between the two parents):

- weight 0 reproduces 833's vectors exactly;
- weight 4096 reproduces 867's vectors exactly;
- weight 2048 matches `(0x1000*a + w*(b-a)) >> 12` in **2,889 of 2,889** slots.

Median parent-to-parent displacement is 207 units and the maximum 6,598, so the blend is a
real shape change and not a rounding artefact. Nine demo GLBs are in
`models/merged/` — a 0/25/50/75/100% sweep, a three-parent blend, a
texture-swap-plus-120-degree-hue example, and 907-as-base gaining 15 part flags from 833.
All nine pass `check_glb.py`.

Two deliberate departures from the game, both because a GLB has to keep working afterwards:

- The game allocates the merged creature a **single-frame** animation and re-grounds it on
  marker id `0x26`. The tool instead writes the blended rest offsets into *every* animation
  block of the base package, so the whole 29-clip set still plays. Frame rotations are the
  base's; the game's `FUN_8004A520` also lerps frame-0's X rotation in modular angle space,
  which a multi-clip export cannot express.
- The 43 attachment markers are not blended (`FUN_80011904` does that in IEEE float); the
  result keeps the dominant parent's, which is what the game does with the rest of the
  appearance blob anyway.

## 8. What is still open on the visual side

- The **second species table** at ids 211-364. Same 154 models as ids 57-210, different hue
  pairs, no accessor found. Finding its reader would probably explain how a creature's
  appearance id (`+0x03`) is chosen in the first place.
- **`FUN_800BA198`'s `param_4`**, which indexes the ten-entry table at `0x8007CA70` (values
  201-210, plus -1 for "leave it") and overwrites the result's appearance id. Those ten
  values are exactly species ids 201-210, the ten unique models 914-923. What decides
  `param_4` is untraced.
- Whether the **merge UI's preview** and the **battle overlay's** recipes differ. Both call
  `FUN_80033938`; only overlay 44's builder has been read line by line.
- `FUN_80029044`'s `param_6` (`load->vramPlacement + 4`) — the VRAM placement descriptor —
  is assumed, not verified.


---

# NAMES, AND A LIVE MERGE TOOL (2026-08-25, later)

## 9. Every species has its name in the exe — thread 3 finished

**CONFIRMED.** The English names are in `SLES_022.01`, and nothing in the archive has
them, which is why an ASCII sweep of the 211 MB DATA.001 came up empty twice: the game
stores Latin text as **Shift-JIS full-width forms**, so "Carmine" is on disc as
`82 62 82 81 82 92 …`, never as `43 61 72 …`.

```c
char *speciesName[209];    // 0x8007A094, one pointer per species id 0..208
                           // -> a string pool at 0x80072234..0x80072F60
```

The pool ends exactly where the body-part bone masks begin (`0x80072F60`), which is the
boundary that fixes its extent. Reader: `tools/merge_reference.py::species_names`.

Two independent checks, both clean:

- **All 209 names match the community's Complete Minion List entry for entry**, and that
  list's hex IDs turn out to be *literally the game's species ids* — 0x00 Marrdreg is
  species 0, 0xD0 Klarrgas is species 208. The wiki was never consulted to build the
  table; it agrees with it.
- The names confirm the species table's own shape (§3): species 37-40 are four
  "Vatolka", 57-60 are Pataraid/Mafrayd/Terfrayd/Ragifrayd, and 201-208 are the eight
  Eternal Corridor bosses.

Species 209 and 210 exist in the species table but have no name pointer; nothing on the
disc references them.

### The Japanese names are in the archive, at a different index

**CONFIRMED.** File 114 is `{u32 size; u32 count; ...}` followed by NUL-terminated
Shift-JIS katakana strings, each padded to a 4-byte boundary. It holds **153** names, and
its index is *not* the species id:

| name index | species |
|---|---|
| 0 - 144 | `200 - index`   (species 200 down to 56) |
| 145 - 152 | `353 - index`  (species 208 down to 201) |

So the Japanese table covers species 56-208 only, in descending order; species 0-55 -
the wild enemy forms and the story bosses - have no katakana entry. Name 144 is
`？？？？？？？`, which lines up with species 56, **Cushidra**, the final boss whose name is
hidden until you meet it.

The count-313 word in file 114's header is not the name count; the strings stop at 153
and MIPS code follows.

### Which minions the missing-rig models are

**CONFIRMED**, and it recasts `OVERLAYS.md` §7 in plain language. The five models whose
bone table is nowhere on the disc are all "special" species, and now they have names:

| file | species | name |
|---|---|---|
| 840 | 47 | Seterian |
| 870 | 49 | Kikinak |
| 893 | 51 | **Poacher** (`密猟者`) |
| 930 | 41 / 55 | Dream Man / Chosen One |
| 841 | 56 | **Cushidra**, the final boss |

893 being the Poacher - a human, not a creature - explains at a stroke why no creature
rig fits it. 841 being the final boss explains why it is the one model with real
animations and no rig anywhere: it is drawn by its own set-piece code.

### Element index -> name prefix

**CONFIRMED.** Reading the four variants of all 36 base species, the element index at
minion `+0xC2` maps onto the roster's name prefixes:

| element index | prefix | e.g. |
|---|---|---|
| 0 | Pata / パタ | Patawasp, Pataraid |
| 1 | Sk / スク | Skawasp, Skbaran |
| 2 | Ter / テラ | Terwasp, Terbaran |
| 3 | Rad / ラド (Dog on some) | Radwasp, Ladbaran |

17-21 of the 36 groups use the plain prefix in each column and the rest are one-off
names, but no column ever takes another column's prefix. **HYPOTHESIS**: `テラ` is *terra*,
so element 2 is Earth - which would settle the open GR-matrix index order. Not proven;
the game's own element text has not been tied to an index yet.

## 10. Merge Studio — pick two creatures and watch it happen

`tools/merge_studio.py` + `tools/merge_studio.html`. A dependency-free local web app:
the Python side reads geometry, skeleton, clips and palettes straight off the disc, and
the **browser runs the blend itself**, per vertex, in the same fixed-point arithmetic the
PS1 uses, so the weight slider morphs in real time rather than rebuilding a file.

```bash
cd tools
python merge_studio.py ../extracted/SLES_022.01 ../extracted/DATA001_split
# then open http://127.0.0.1:8765/  (or pass --open to launch a browser)
```

What is on screen: both rosters by name, a blend slider, an **age slider**, a
palette-rotation slider, a texture-source switch, every animation clip with scrub and
playback, body-part toggles showing what each parent contributed, wireframe, and an
**export .glb** button that writes the current blend through `merge_reference.py` into
`models/merged/`.

How faithful each part is:

| piece | how it is done |
|---|---|
| vertex + normal blend | `(0x1000*a + w*(b-a)) >> 12` per s16 component, in JS |
| bone lengths | the same lerp over both parents' rest offsets |
| skinning | each vertex is rigid to one bone; the vertex shader applies that bone's world matrix |
| pose | `FUN_80047E4C`'s Euler-triple-to-matrix, on a JS copy of the game's 4096-entry sine table |
| body parts | the OR rule, evaluated on the CURRENT stage's flags, with per-group toggles so you can see who gave what |
| age | a level 1-40 slider -> stage via `FUN_80019A80`'s five thresholds; the stage's whole-body scale is blended between the parents, its per-bone scale is the base's, and both are applied the way `FUN_80047E4C` does (S12) |
| per-mesh weights | `FUN_80010DB0`'s cascading-denominator maths, per vertex via a mesh-object id sent with the geometry - so stage 0 of file 845 really does pin mesh object 10 to one parent |
| palette | `FUN_80029D68` transcribed into the fragment shader: quantise to 5 bits, 192-step HSV, rotate, skip achromatic |
| topology | the mergeable family is **derived at startup** by grouping every model file by its exact chunk stream and taking the largest group - it finds 49, unprompted |

Two things it does differently from the game, both deliberate:

- Both parents are emitted with the **base's seam-quad table**, which is what the merge
  does anyway, and is what keeps the one odd family member (file 850, 64 quads instead of
  68) lined up with everyone else.
- Clips come from the base parent. The game gives a merged creature a single-frame pose;
  keeping the base's 29 clips is more useful to look at.

Rendering notes worth keeping: PS1 winding is clockwise once the Y/Z flip is folded into
the view matrix, and the atlas must be sampled `NEAREST` - the hue rotation is only exact
on unfiltered texels, because every texel is a palette entry.

## 11. Does an unmerged creature get its palette rotated?

**HYPOTHESIS, with evidence.** The species record's `hueBase` is only ever read by the
merge recipe builder. The two ordinary spawn paths - the battle-enemy spawner
(`ovl_800A1F10`) and the scene-package actor spawner (`ovl_800B25F4`) - both read only
`*(u16*)rec`, the model id, and never touch `+2` or `+3`. Their texture load leaves the
hue field at its -1 default, so nothing rotates.

That would make a wild Pataraid and a wild Terfrayd - same model, palette angles 90
degrees apart - render identically, which cannot be right. The resolution that fits
every observation: **any minion you own is built through the merge job**, even when it
has one parent. `FUN_800BF208` degenerates cleanly to that case - a freshly caught minion
has only its own species in its ancestry, so `nSources == 1`, weight 4096, and the blend
is an identity copy - while the texture load still applies the hue. Four overlays call
`FUN_80010850`, not just the merge UI, which is consistent.

Untested. A save-state or a breakpoint on `FUN_80010850` while walking around with a
party would settle it in a minute.


---

# WHERE THE EXPORT BLEND STOPS BEING TRUSTWORTHY (2026-08-25, later still)

## The rest pose is half the blend - CONFIRMED

A user merged Arpatron with Skawasp in Merge Studio, exported the GLB, and got a
creature whose skin had come off its skeleton: the silhouette was roughly right and
the surface was a fan of long thin shards. The live tool looked fine; only the export
was wrong. Everything obvious checked out and had to be eliminated one at a time:

- the blended mesh is **byte-exact**. At weight 4096 all 2,889 SVECTOR slots equal the
  source model's own, seam pools included.
- the rest-offset blend is right, the bone hierarchy is identical across the family,
  the mesh-object headers match, the per-mesh-object stage weights agree, the
  appearance blob's per-bone scales are all identity at stage 4, and every one of these
  models uses the same 25-bone table at `0x80079064`.
- `check_glb.py` passes the broken file, because it only checks the **bind pose**, and
  at bind pose every skin matrix is `world(joint) * inverseBind(joint) = identity`. A
  rig that disagrees with its geometry still looks perfect there.

The cause is that **a vertex is stored per bone and relative to that bone**, so what
its numbers mean depends on where the bone is pointing in the rest pose. `export_gltf`
builds the bind pose from the rest offsets **and the first block's frame-0 rotations**.
Blending only the offsets, as the exporter used to, leaves the blended geometry hanging
on the base parent's default angles.

How far apart two parents hold the same bone decides how badly that shows:

| pair | worst bone | result |
|------|-----------|--------|
| 833 x 867 | 3.6 deg | fine; this was the demo pair, which is why the bug hid |
| 833 x 850 | 0.0 deg | fine |
| 833 x 862 | 4.1 deg | fine |
| 833 x 845 | 15.6 deg | visibly distorted |
| 833 x 860 | 28.1 deg | distorted |
| 833 x 907 | 45.4 deg | badly distorted |
| 833 x 864 | 55.1 deg | the reported break |
| 833 x 899 | 179.4 deg | nothing survives |

**Only 12 of the 25-mesh family are within 15 degrees of 833.** Sharing a topology is
not the same as sharing a pose, and the "49 models are each other's morph targets"
result is about topology alone.

The game never hits this. It builds a fresh single-frame pose for the merged creature,
so its skeleton and its geometry always agree. An export is different: it keeps one
parent's whole clip set so that all 29 animations still play, which pins the skeleton
to that parent.

## What was fixed, and what is still open - PARTIAL

`blend_rest_pose` now also blends the bind rotations (shortest way round, since 4096
units is a full turn) and the frame-0 root translation that drives bone 1. That makes
the blend exact at weight 0, removes the shattering, and leaves the skeleton bone-for-bone
identical to the target parent at weight 4096.

It is **not** a complete fix. At full weight the result still is not the target model,
because the merged package keeps the base's UVs, texture page assignments and seam
stitch records while taking the other parent's positions. Limbs then close against the
wrong stitch partners. Judged against the target parent's own export, 64% of vertices
are still misplaced, worst case a quarter of the model's span.

So `merge_reference.py` now measures the divergence up front and prints a warning past
15 degrees (`REST_POSE_LIMIT`). `models/merged/` only ships pairs that pass. A real fix
has to blend the stitch records and UVs as well, or drop the "keep the base's clips"
rule and synthesise a single pose the way the game does.

## check_anim.py, and a metric that did not work - NEGATIVE RESULT

`check_anim.py` was written to catch this class of bug: it walks every clip, skins the
mesh on the CPU and measures how far each triangle edge stretches from its bind length.
Worth recording that **an absolute threshold does not work here**. The known-good models
in `models/current/` reach 3.2x to 4.6x on their own, because a seam strip spanning two
bones really does stretch when a limb bends, so any cutoff loose enough to admit them is
too loose to catch real damage. The tool therefore reports the number and compares
against a `--baseline` model instead of pretending to a verdict.

It also would not have caught this particular bug, which is visible in the bind pose
itself. It stays because the blind spot it covers is real.


# 12. AGE / GROWTH — what is already known, for the next session

Not the open thread's write-up, a **head start on it**. Most of the machinery turned up
while chasing the merge, so this collects it in one place with what is measured and what
is still guesswork.

## Level -> stage — CONFIRMED

`FUN_80019A80(level)` walks five `u8` thresholds at `0x8007C208` and returns how many the
minion has passed, minus one. The thresholds are **1, 7, 13, 22, 27**:

| level | stage |
|---|---|
| 1 - 6 | 0 |
| 7 - 12 | 1 |
| 13 - 21 | 2 |
| 22 - 26 | 3 |
| 27 and up | 4 |

The level is minion `+0xC8` - the same byte the hidden-evolution rule reads to pick which
of the seven special forms you get. Port: `merge_reference.py::growth_stage`.

## The stage data — CONFIRMED

Every mergeable model carries **exactly five** `Stage` records in its appearance blob
(`MODEL+0x4C`), laid out as in the earlier section. Measured across the 48 models that
have them:

- **Global scale ladders.** 35 of 48 share `1638, 2252, 2867, 3481, 4096`, i.e. 0.40 to
  1.00 in even steps. The rest differ, and some **never reach unity**: one ladder tops out
  at `2867` (0.70) and another at `2252` (0.55). Those creatures are permanently small,
  which is a designed trait, not a bug.
- **41 of 48 end at exact unity** in both global and per-bone scale; the seven that do not
  are the truncated ladders.
- **Per-bone scale gives babies baby proportions.** At stage 0 the head and limb bones run
  1.5x-2.0x while body and tail run 0.4x-0.6x; by stage 4 (for most) every bone is 4096.
  So growing up is not one uniform scale-up - the creature re-proportions as it ages.

### Which axis is which, and why the scale must not be inherited - CONFIRMED

The triple is in the **bone's own frame**, and a bone's length axis is **local Y**: every
rest offset in the 25-bone creature rig runs along Y (`(0, 45, 0)`, `(0, 69, 0)`,
`(0, 120, 0)`...). So `x` and `z` are that limb's **width and depth**, and the pattern in
the data reads straight off:

| bones | stage 0 triple | what it means |
|---|---|---|
| 4, 7 (forearms) | `(1.50, 1.00, 1.50)` | same length, chubbier |
| 5, 8 (hands) | `(2.00, 1.00, 2.00)` | fat little hands |
| 9 (neck) | `(1.00, 0.60, 1.00)` | short neck |
| 10, 11 (head, jaw) | `(2.00, 2.00, 1.00)` | big head, not deeper |
| 12-15 (wings) | `(0.60, 0.40, 0.40)` | stubs |
| 23, 24 (tail) | `(1.20, 0.60, 1.20)` | short, thick tail |

The authored numbers are **absolute, not inherited**. Folding a bone's scale into the
matrix the children are built from compounds it down the chain and puts the jaw at
2.0 x 2.0 = 4x and the hand at 1.5 x 2.0 = 3x - visibly wrong, and inconsistent with the
1.5x-2.0x range the arrays themselves stay inside. What the child *does* take from the
parent is the **offset**: the rest offset is transformed by the parent's scaled matrix, so
a 0.6x neck pulls the head in against the body instead of leaving it floating. Merge
Studio keeps two matrices per bone for exactly this - a plain world rotation the children
inherit, and a `M * diag(s)` copy used to draw that bone and to place its children.

## Body parts change with age — CONFIRMED

`partFlagsA` is stored **per stage**, and six models change it as they grow: 856, 860,
861, 862, 913, 916. Only one is a visible change: **file 856** (Geenwee / Karn / Telma)
has `wings = 2` at stages 0-1 and `1` from stage 2 on — *a hatchling with wings that loses
them growing up.* The other five move a group from `0` to `1`, which is invisible because
both are below the draw threshold — but see below, it is not meaningless.

`partFlagsB` never changes between stages in any model.

### The three flag values are not two — CONFIRMED

The draw rule is `partFlagsA[k] < 2` hides the group, so 0 and 1 look identical on screen.
The **merge** rule is not symmetric:

```c
if (other.A[k] > 1 && mine.A[k] == 1) mine.A[k] = 2;
```

It promotes a **1** and never a **0**. So:

| value | on screen | can a merge grant it? |
|---|---|---|
| 0 | hidden | **no** |
| 1 | hidden | yes |
| 2 | shown | (already) |
| 3 | shown | (already) |

Measured at the adult stage across all 48: **no model has a 0** - every hidden group is
grantable. The zeros only appear at *younger* stages. A baby with `arms = 0` cannot gain
arms by merging; the same creature as an adult (`arms = 1`) can. Group 2 (legs) is `3` in
44 of 48 models, so `3` looks like "structural, always there" against `2` for "present".

## What the runtime does with the stage — CONFIRMED

Per frame, through `FUN_8001FA58` -> `FUN_8001FD70` -> `FUN_80047E4C`:

```
actor[0x26]         animated master scale, ramping toward actor[0x2A] by actor[0x28] per frame
actor[0x2C..0x34] = stageGlobalScale * actor[0x26] >> 12
boneTranslation[b] *= perBoneScale[b] / 4096
boneMatrix[b]       = boneMatrix[b] * diag(perBoneScale[b]) * diag(actor[0x2C..0x34])
```

The stage vectors reach the actor through the spawn descriptor: `+0x38` global scale
(`FUN_80024EF8(model, stage)`) and `+0x3C` per-bone scale (`FUN_80024F30(model, stage)`).
The scene spawner picks the stage with `FUN_8001900C(&tmp, minion)`, which wraps the
level->stage lookup.

## Which of the two scales the merge blends - CONFIRMED

`FUN_80010DB0` blends the **whole-body** scale and not the per-bone one:

- The global-scale loop runs over **all five stages**, writing
  `out.globalScale[stage] = sum_k src[k].globalScale[stage] * weight[k] >> 12` back into
  source 0's blob, which becomes the result's. So a full-size creature merged 50/50 with
  one whose ladder tops out at 0.70 gets a 0.85 adult, at every stage of its life.
- The per-bone array is passed to the skeleton blender `FUN_8004A520` as
  `FUN_80024F30(src_k, stage)` for all three sources - but the call site passes **0** as
  that function's last argument, which is the output array it would write the blended
  per-bone scale into. The blend is computed and thrown away; the result keeps source 0's
  proportions, along with the rest of the dominant parent's appearance blob.

Five family models never reach unity even as adults - **834** (0.55), **853**, **874**,
**915** (0.70) and **859** (0.60) - and three keep a non-unity per-bone scale at stage 4
(**852, 853, 914**). File **850** carries no stage list at all. Merge Studio treats a
missing list as five unity stages, which is what the game's null guards amount to.

## What is actually open

1. **The growth animation.** `actor[0x26]` ramps toward `actor[0x2A]` at `actor[0x28]` per
   frame, so a level-up visibly *grows* the creature rather than snapping. Nothing has
   traced who writes `+0x28` and `+0x2A`. The per-bone array is **not** swapped instantly:
   `FUN_80047E4C` reads *two* per-bone scale arrays - `actor+0x10` and a second pointer -
   and interpolates them per bone, `s[c] = A[b][c] + ((B[b][c] - A[b][c]) * t >> 12)`,
   with `t` a 1.12 factor from the same local block. So the re-proportioning crossfades
   between stages the same way the master scale ramps. Who fills the second pointer and
   `t` is still untraced; Merge Studio uses the stage's array directly, i.e. `t = 0`.
2. **Does stage affect anything but the body?** Stats, skills and the merge weights are all
   read from other fields; the only stage-indexed data found so far is scale, part flags
   and the (barely used) per-mesh weights. Worth confirming there is no stat curve keyed
   off the stage.
3. **How a minion levels at all** - where experience turns into `+0xC8`. The merge's
   double-precision experience carry (`FUN_80012204`) is decoded, but the level-up path is
   not.
4. **`FUN_8001900C`** is only known by its role. Reading it would confirm the level ->
   stage call is the whole story and not one branch of several.
5. Whether the **five stages are the same five "ages" the UI names**, and whether a merged
   creature is re-staged from the merged level or keeps the base's stage. `FUN_800BF208`
   passes `growth_stage(minion.level)`, which suggests re-staged - but that is the merge
   preview, not the party model.

`tools/merge_studio.py` already fetches stage 4; adding a stage selector is a few lines
(`build_merged_package` and `_prims` both take one) and would make this thread visual
immediately.
