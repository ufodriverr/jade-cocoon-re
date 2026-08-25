# Jade Cocoon asset formats — textures (SOLVED) and models (in progress)

All findings verified against SLES-02201. Function addresses are in the main exe unless noted.

---

## 1. Textures — SOLVED, 100% confirmed

**Jade Cocoon uses stock Sony TIM images.** No custom encoding, no compression.
Earlier scans undercounted them badly because they only checked 2048-byte sector
boundaries; TIMs are actually embedded at arbitrary offsets inside package files.

**Result: 3302 textures extracted from 751 archive files** → `extracted/Textures_All/`
(PNG, RGBA, with `manifest.json` giving file index, VRAM coords, CLUT position, bpp).

### TIM layout (re-derived, then confirmed against the game's own parser `FUN_80029770`)
```c
u32 id;      // 0x10
u32 flags;   // bits0-2 = pmode (0=4bpp, 1=8bpp, 2=16bpp, 3=24bpp), bit3 = CLUT present
// if (flags & 8):
u32 clut_bnum;              // == 12 + w*h*2
u16 clut_x, clut_y, clut_w, clut_h;   // VRAM position of the palette
u16 clut[clut_w * clut_h];  // BGR555, bit15 = STP
// always:
u32 pix_bnum;               // == 12 + w*h*2
u16 x, y, w, h;             // VRAM position; w is in 16-bit WORDS
u16 pixels[w*h];            // 4bpp: 4 px/word, 8bpp: 2 px/word, 16bpp: 1 px/word
```
Real pixel width = `w*4` (4bpp), `w*2` (8bpp), `w` (16bpp).
Color: `r=(c&0x1F)<<3, g=((c>>5)&0x1F)<<3, b=((c>>10)&0x1F)<<3`; index 0 / black with
STP=0 is treated as transparent.

The game's parser confirms every field: `param_1[1] = flags & 7` (pmode),
`flags & 8` (CLUT test), CLUT data at `+0x14`, pixel block at `(+8) + clut_bnum`,
pixel data at that `+12`.

### Where textures live in a package
Package = `{u32 count; u32 sectionOff[count]}` (see FINDINGS.md). **The last section is
the texture set**: itself a `{u32 n; u32 subOff[n]}` list, one TIM per model part.
Confirmed load path:
```
FUN_80028edc(dst1, dst2, dst3, packageBuf, count)
  └─ FUN_80028f54(...) — walks sectionBase + subOff[i]
       ├─ FUN_80029770(tmp, timPtr)  — parses the TIM header (above)
       ├─ FUN_80029708(tmp)          — LoadImage() CLUT + pixels into VRAM
       ├─ FUN_80029914(...)          — builds a 20-byte texture descriptor (GetTPage)
       └─ FUN_80029a78(...)          — builds a 40-byte descriptor
```

### Tools
- `tools/tim.py` — parser + BGR555→RGBA + dependency-free PNG writer.
- `tools/extract_textures.py <split_dir> <out_dir> [--only A-B]` — bulk extract + manifest.

### Where the art is
- **831, 832** — character/NPC texture banks (832 alone holds 345 textures: skin,
  clothing, faces). Confirmed visually.
- **934-1080** — field/environment packages (trees, terrain, rock) plus effects.
- **0-99** — UI, fonts, menus (556 textures).
- **600-849** — the densest art region (~1400 textures).

---

## 1b. WHERE THE MODELS ARE — solved

The exe holds a **model descriptor table** that maps each model resource to its archive
file and the sector ranges inside it.

- `PTR_DAT_800823F0` = array of 16 pointers (read as `(&PTR_DAT_800823f0)[type]` in
  `FUN_80025268`, the streaming loader).
- Each pointed-to descriptor is a `u16[]` whose **first field is the DATA.001 file index**:
  descriptors 0..15 → **files 833, 834, 835 ... 848**.
- Following fields are `(sizeInSectors, cumulativeSectorOffset)` pairs describing the
  sub-resources inside that file, e.g. file 833: `[833, 0, 3,3, 17,20, 17,37, 24,21, 1,1]`.

**So files 833-848 are the model/animation data files** (831/832 are the character texture
banks; 934-1080 are environment). File 833 decoded layout:

| sectors | contents |
|---------|----------|
| 0 - 3   | small header container |
| 3 - 20  | **TIM textures** (10-part container, verified) |
| 20 - 37 | **mesh block** — header `{u32 totalSize, u32 boneCount, u32 offA=0x44, u32 offB=0x80D0}` |
| 37 - 61 | **animation container** (8 animations, verified below) |

## 1d. Skeleton and posing — SOLVED

Three separate pieces combine into a posed model, and all three are now decoded.

### Bone hierarchy table (in the EXE)
From `FUN_8001e858`: the actor copies its bone list from `spawnParams + 0x34`; the walk is
`while (*(s16*)p != -1) p += 8`, so it is an **array of 8-byte records terminated by -1**:
```c
struct BoneRec {
  /* +0 */ s16 depth;       // tree depth (0 = root) - THE HIERARCHY IS ENCODED HERE
  /* +2 */ u8  self;        // own index / animation slot, sequential 0,1,2,...
  /* +3 */ u8  unk;         // NOT the parent (see below)
  /* +4 */ s16 meshIndex;   // which mesh object this bone draws
  /* +6 */ s16 unk2;
};
```

**CORRECTION (parenting).** The parent is **implied by depth** - a bone's parent is the
most recent preceding bone at `depth - 1` (classic depth-first skeleton encoding). The byte
at +3 looks like a parent index and agrees for almost every bone, which is why it was
initially taken as one, but it diverges: in the 25-bone rig, bone16 lists `+3 = 0` while its
real parent is bone 1. Using +3 strands bone16 and its three child chains (both rear legs
and the tail) at the world origin while the rest of the body sits 212 units up - the exact
"lower half at 0,0,0" symptom. `parents_from_depth()` in `assemble_model.py` implements the
correct rule.

Also: the renderer forces **animation slot 0 to zero rotation** (`if (slot == 0) angles = 0`
in FUN_80047e4c), which the exporters now replicate.

**Root motion.** Bone 1's translation is animated per frame from keyframe entry 1, not taken
from the static rest offset. Objective test on the idle animation: with the static offset the
feet drift 24 units while the body never moves (the model appears to paddle its legs in the
air); driving bone 1 from entry 1 plants the feet at **exactly 0 drift** while the body rises
and falls 51 units - the correct "body bobs, feet stay planted" behaviour. Entry 1 at frame 0
equals `restOffset[1]` exactly in all 24 animations across 6 files, which is what identifies
it. Entry 0 (locomotion displacement) is deliberately NOT applied, so animations play in
place - the usual preference for viewing in Blender.

With depth parenting the 25-bone rig reads as a coherent quadruped: root+shadow at the
ground, body 212 up, two front limbs at z=+95, head/neck forward-up at z=+161, wings at
x=+/-43, two rear limbs at z=-70 reaching the ground, and a tail sweeping back to z=-237.
Found with `tools/find_bonelist.py` (the sequential `self` byte is a strong signature).
Confirmed 25-bone rigs at **`0x80079064`** and **`0x80079134`**, matching the 25-mesh model
files (833/834/845/846/847). Example hierarchy from `0x80079134`: bone2 branches into five
limb chains (3-4-5, 6-7-8, 9-10-11, 12-13, 14-15) and bone16 into three more — and the
`depth` field agrees with every parent link.

### Rest pose (in the ANIMATION block header)
The 150-byte "header" is not opaque: it is **one `s16[3]` rest translation per bone**, so
the block header is exactly `8 + boneCount*6` bytes. This is why the constant 158 worked
earlier — every validated block happened to have 25 bones (8 + 25*6 = 158). The variable
formula now validates on **23, 25, 37 and 40-bone** files with zero-gap tiling.

The rest offsets show unmistakable skeletal structure — mirrored left/right limb pairs:
`bone3 (40,-95,26)` vs `bone6 (-39,-95,26)`, `bone12 (43,-44,-7)` vs `bone14 (-42,-44,-7)`,
`bone17 (50,81,13)` vs `bone20 (-49,81,13)`.

### Rotations and the sine LUT
Keyframe entries are three Euler angles in **4096 units per full turn**. The LUT at
`0x80084464` is verified: `lut[0]=0`, `lut[1024]=4096`, `lut[2048]=0`, `lut[3072]=-4096`,
with `sin(a) = lut[a & 0xFFF]` and `cos(a) = lut[(a + 0x400) & 0xFFF]`.

Matrix composition transcribed from `FUN_80047e4c` (all products `>> 12`):
```
m00 = c2*c1                       m01 = c2*s1*s0 - s2*c0      m02 = s2*s0 + c2*s1*c0
m10 = s2*c1                       m11 = c2*c0 + s2*s1*s0      m12 = s2*s1*c0 - c2*s0
m20 = -s1                         m21 = c1*s0                 m22 = c1*c0
```

### Assembly
```
world_R[i] = world_R[parent] * localRot(keyframe[frame][i])
world_T[i] = world_T[parent] + world_R[parent] * restOffset[i]
vertex_world = world_R[bone] * vertex_local + world_T[bone]
```
`tools/assemble_model.py <exe> <pkg> <meshSector> <animSector> <boneTableAddr> <out.obj>
[--anim N] [--frame N]` does this end to end.

**Result:** file 833 assembles into a clean, symmetric winged humanoid — head, torso, two
arms, two legs, crest — with every world transform sane and left/right bones perfectly
mirrored (`bone3 (40,-186,95)` vs `bone6 (-39,-186,95)`). See
`models/archive/scratch/posed_833*.png`.

Note: bone tables for the 37/40-bone models are not in the main exe (only 25- and 16-bone
rigs are), so those models likely carry their rigs in an overlay or in the package itself —
worth a follow-up, but the pipeline is proven.

## 1c. Animations — SOLVED and verified

Block layout, derived from the renderer's indexing and then **confirmed by exact size
arithmetic on every block** (all 8 blocks in file 833 tile with zero gaps):

```c
struct AnimBlock {
  /* +0x00 */ u32 frameCount;   // bit 31 = an extra u32 sits before restOffset
  /* +0x04 */ u32 boneCount;    // bit 31 = an event list follows the keyframes
  /* +0x08 */ u32 extra;        // only when bit 31 of frameCount is set
  /* +...  */ s16 restOffset[boneCount][3];             // per-bone rest translation
  /* +hdr  */ s16 keys[frameCount][boneCount + 2][3];   // hdr = 8 + extra? + boneCount*6
  /* +...  */ u32 eventCount;                           // only when bit 31 of boneCount
  /* +...  */ s16 events[eventCount][4];                // {frame, ?, id, ?}
};
// size = hdr + frameCount*(boneCount+2)*6, rounded up to 4,
//        then + 4 + eventCount*8, rounded up to 4 again
```

**The two flag bits are CONFIRMED** against `FUN_80026AF4`, the loader that converts an
on-disc block into the `0x1C`-byte runtime descriptor at `MODEL+0x54`; it does exactly this
arithmetic. Reading the boneCount word raw gives `0x80000016` = 2147483670, which is why
`parse_block` used to reject the flagged blocks outright and files 831, 832, 841, 876, 893
and 930 were recorded as having no animations of their own. On the player-character walk
cycle (831, block 1) the event ids alternate 21/22 across the stride, which reads as
left/right footstep triggers.
The renderer reads `key[(frame*(boneCount+2) + bone + 2) * 6]` — hence the two extra slots
per frame (root translation / flags).

**`bone` there is the bone record's `self` byte, and `boneCount` is the CLIP's, not the
rig's — so the two counts are independent.** `FUN_80047E4C` walks the *rig* to its `-1`
terminator, and for each record indexes the clip at that record's `self` byte using the
clip's own stride; the record's depth word drives a matrix stack. A clip therefore only has
to be **at least as long as the rig**. That is what lets model 870 (26 mesh objects, 26-bone
clips of its own) sit on a 23-bone rig and score 55 where the 25-bone rig it was borrowing
scored 95. The same function blends **two** clips at once — a crossfade, both indexed by the
same `self` byte — which is how `ovl_800A97E8` fades between the party's actions.

**Rotations are in the 4096-units-per-turn space of the sine LUT** at `0x80084464`
(1024 = 90 degrees), which the sampled data confirms: root bones read (0,0,0) and bone 2
sits at -1024/-1142 drifting a few units per frame.

Verified output for file 833 (`tools/anim.py <file> 37 -v`):
`8 animations — 1, 1, 32, 40, 70, 45, 70, 30 frames, all 25 bones`, every block boundary
matching the container's own offset table exactly.

## 2. Mesh geometry — SOLVED, models exporting to OBJ

Recovered end-to-end from the game's own decoder chain and verified: **all 15 model files
parse with byte-exact size agreement, and the exported OBJs render as recognizable
creatures.**

### Decoder chain (the functions that define the format)
```
FUN_8002188c(data, meshArray)   skip 0x10 header; meshCount = *(u32*)(data+4);
                                loop: FUN_800224c0(...), meshArray += 0x54
FUN_800224c0(meshObj, data)     data + 0x28 = chunk stream; walks tagged chunks
FUN_8002269c(meshObj, data)     reads the 10 u32 counts, allocates runtime records
0x8007DA04                      jump table, 8 chunk handlers (one per polygon type)
0x8007DA2C                      parallel callback table - non-null ONLY for the
                                textured types 2,3,6,7 (texture-page setup)
```

### On-disc layout
```c
struct MeshBlock {              // e.g. file 833 sector 20
  u32 totalSize;
  u32 meshCount;                // one mesh object per bone
  u32 unk1;
  u32 endOfMeshData;            // == exactly where the object stream ends (verified)
  MeshObject objs[meshCount];   // back to back, no offset table
};

struct MeshObject {
  u32 counts[10];               // 0x28 bytes, indexed by chunk type
  Chunk chunks[sum(counts)];    // { u8 type; u8 a; u8 b; u8 flags; u8 body[...] }
};
```

### Chunk table (type = PS1 primitive type)
| type | name | GPU code | on-disc body | runtime record | verts | header | vertex block |
|------|------|----------|--------------|----------------|-------|--------|--------------|
| 0 | F3  | 0x20 | 0x24 | 0x24 | 3 | 0x0C | 8  (pos + UV) |
| 1 | G3  | 0x30 | 0x3C | 0x3C | 3 | 0x0C | 16 (normal, pos@+8) |
| 2 | FT3 | 0x24 | 0x24 | 0x30 | 3 | 0x0C | 8 |
| 3 | GT3 | 0x34 | 0x40 | 0x48 | 3 | 0x10 | 16 |
| 4 | F4  | 0x28 | 0x2C | 0x2C | 4 | 0x0C | 8 |
| 5 | G4  | 0x38 | 0x50 | 0x50 | 4 | 0x10 | 16 |
| 6 | FT4 | 0x2C | 0x2C | 0x38 | 4 | 0x0C | 8 |
| 7 | GT4 | 0x3C | 0x54 | 0x5C | 4 | 0x14 | 16 |
| 8 | (special) | - | `4 + n*0x14` | 0x14 each | - | - | - |
| 9 | (special) | - | `8 + n*0x14` | 0x14 each | - | - | - |

Every entry satisfies `header + nVerts*blockStride == on-disc body size` (asserted in
`export_mesh.py`). Header = 4 bytes clut/tpage when textured, plus per-vertex CVECTOR
colors when gouraud, or one 8-byte face normal when flat.

**Vertex blocks:**
- flat/textured (8 bytes): `s16 x, y, z; u8 u, v`
- gouraud (16 bytes): `s16 nx, ny, nz; pad; s16 x, y, z; pad` — **normal first, position
  at +8**. Normals are unit vectors in 4096 fixed point (verified: 3124^2+2648^2 = 4095^2).

### Verification
- `tools/mesh.py <file> <sector>` — parses a block; **15/15 model files report
  "EXACT MATCH with u2"**, i.e. the walk lands precisely on the header's end offset.
- `tools/export_mesh.py <file> <sector> <out.obj> [--mesh N]` — exports OBJ.
- `tools/preview_obj.py <obj> <png>` — dependency-free rasterizer, front/side/top views.
- Exported models live in `models/` (600-1780 triangles each) and render as
  clearly identifiable creatures (horned/antlered minions).

### Skin stitching (the mesh block's trailing data) — SOLVED
The two header fields after `meshCount` are `stitchCount` and `stitchOffset`. The trailing
region is `stitchCount` records of 16 bytes, each **four `(u16 boneIndex, u16 vertexIndex)`
pairs** forming a quad that bridges two bone parts (e.g. all-`(2,n)`/`(16,n)` quads sewing
bone 2 to bone 16). Verified on six files: trailing bytes == `stitchCount * 16` exactly
(833:68, 835:116, 838:174, 840:58, 841:104, 842:132). The mesh block is now fully
accounted for, byte for byte.

**SOLVED:** `vertexIndex` indexes the per-bone **seam vertex pool**, which is exactly what
chunk types 8/9 contain. Proof: for every single bone, `max(vertexIndex) + 1` equals the
number of type-8/9 items in that bone's mesh object. Each 0x14-byte item stores a vector at
+0 and the **position at +8** - the same normal-then-position convention as the gouraud
vertex blocks. Resolving stitches through +8 gives sane seam quads (median max-edge 53
units); through +0 it gives ~6856, which is how the two were told apart.

Type 8 bodies are `4 + n*0x14`, type 9 bodies `8 + n*0x14`, so the item array starts at
body+4 and body+8 respectively.

Both exporters now emit the stitch quads. Because each corner belongs to a different bone,
per-vertex skinning binds them naturally and they deform correctly under animation. File 833
goes from 600 to 736 triangles and the model closes into a complete, connected creature.

### Remaining nuance (not blocking)
Chunk types 8/9 (`0x14`-byte records) are size-walked correctly but their contents are not
yet interpreted — they are the likely home of the per-bone indexed vertex pool that the
stitch records reference.

## 2b. Historical notes — earlier dead ends

Minion/character geometry is **not** TMD (only field packages 833-864 and file 943 hold
stock TMDs). It is a custom skeletal system. The renderer is fully located:
**exe range `0x80044000`-`0x8004DD00`, 24 functions**, decompiled to `notes/decomp_render/`.

### What is confirmed
- **Skeletal animation.** `FUN_80047e4c` (the big one, 822 lines) walks a bone hierarchy,
  builds per-bone matrices, and calls `ApplyMatrixLV` / `gte_SetRotMatrix`.
- **Rotations are angle indices, not matrices.** There is a **4096-entry sine LUT at
  `0x80084464`**, indexed `angle & 0xFFF`; cosine is the same table with `+0x400`
  (quarter-turn offset). Classic PS1 trick.
- **Animation keyframes are 6-byte vectors** (3 × s16), addressed as
  `base[+0x18] + (frame * (boneCount + 2) + boneIndex + 2) * 6`, where the holder struct
  has `boneCount` at `+4` and the keyframe array pointer at `+0x18`.
- **Polygon emitters identified** (GPU primitive codes):
  - `FUN_80045a08` → `0x3C` POLY_GT4 (gouraud textured quad)
  - `FUN_8004c240` → `0x2C` POLY_FT4 (flat textured quad)
  - `FUN_8004bfcc` → `0x24` POLY_FT3 (flat textured triangle)
- **Runtime primitive record = 56 bytes** (`0x38`; loop advances `r0_01 += 0xE` CVECTORs).
  Layout read off the GTE calls in `FUN_8004c240`:
  ```
  +0x00  CVECTOR  color (r,g,b,code)      <- gte_ldrgb
  +0x10  SVECTOR  normal                  <- gte_ldv0, used by gte_ncds lighting
  +0x18  SVECTOR  v0, v1, v2  (3 x 8B)    <- gte_ldv3c (loads all three at once)
  +0x30  SVECTOR  v3                      <- gte_ldv0 + gte_rtps
         tpage / clut / UVs packed in the spare halfwords around +0x03/+0x07/+0x2D/+0x35
  ```
  Vertices are **inline per-primitive** (no shared index buffer) — this is why nothing
  looked like a classic vertex array.
- Culling/sorting uses `gte_nclip` (backface), `gte_avsz4` (average Z), OT depth
  `(z-1) < 0xFFF`.

### The mesh object header — CONFIRMED
`FUN_8004c7e0(meshObj, ...)` is the per-object draw dispatcher. It is a table of
`{s16 count, s16 pad, u32 pointer}` entries, one per PS1 polygon type, and it calls a
dedicated emitter for each non-empty entry. Byte offsets and the full type table:

| hdr off | type | GPU code | emitter | record stride |
|---------|------|----------|---------|---------------|
| +0x00 | F3   flat tri        | 0x20 | FUN_8004b344 | 20 |
| +0x08 | G3   gouraud tri     | 0x30 | FUN_8004b868 | (tbd) |
| +0x10 | FT3  textured tri    | 0x24 | FUN_8004bfcc | **48** |
| +0x18 | GT3  gouraud+tex tri | 0x34 | inline in 8004c7e0 | (tbd) |
| +0x20 | F4   flat quad       | 0x28 | FUN_8004b5b4 | (tbd) |
| +0x28 | G4   gouraud quad    | 0x38 | FUN_8004bbc0 | (tbd) |
| +0x30 | FT4  textured quad   | 0x2C | FUN_8004c240 | **56** |
| +0x38 | GT4  gouraud+tex quad| 0x3C | inline in 8004c7e0 | (tbd) |
| +0x40 | (s32 count) extra    | -    | inline | - |
| +0x48 | extra                | -    | FUN_8004c514 | - |

All eight standard PS1 primitive types are supported. Strides marked **bold** are confirmed
from the loop increments; the rest follow the same "inline vertices" pattern.

### The model descriptor table — CONFIRMED, and it is 103 entries, not 16

`0x800823F0` is a pointer array with **one entry per model file, 831..933** — all 103 of
them. It ends on a null pointer. Everything that said "the exe descriptor table only names
16 models" was quoting `NPTR = 16` in `tools/model_index.py`, not the data.

Each descriptor is a `u16` array. **Corrected 2026-08-25** — the loaders read these as
`(startSector, sizeSectors)` pairs, one per section, not as `(size, cumulativeEnd)`. Same
numbers, but the pairing is offset by one and the code's reading is the right one:

```c
u16 fileIdx;                 // [0]  DATA.001 index
u16 start0, size0;           // [1][2]  package header / appearance blob   (0, 3)
u16 start1, size1;           // [3][4]  textures                          (3, 17)
u16 start2, size2;           // [5][6]  mesh                              (20, 17)
u16 start3, size3;           // [7][8]  resident animations               (37, N)
u16 slotBase;                // [9]  u16-offset to the per-animation sector table
// at [10 + slotBase]:
struct { u16 startSector, sizeSectors; } animSlot[];   // one per animation id
```

A load request carries a **section bitmask** saying which of the four to install:
`1` = appearance blob, `2` = textures, `4` = mesh, `8` = resident animations
(`FUN_80025DE4` records one base pointer per set bit, advancing by `size<N>*2048` each
time). `FUN_80025268(mgr, id, -1, ...)` asks for `1|4|8` - everything but the textures -
which is how the merge loads its parents. `tools/model_index.py::ranges_all` and
`sections()` already return the right numbers.

**The per-animation sector table is where the animation frame stream lives.** Each slot holds
one **bare** animation block — no container header — and `FUN_800254A8(model, animId, ...)`
reads exactly `desc[desc[9] + animId*2 + 10]` to stream that one clip in. The resident
container in the header range is only the subset the game keeps in RAM; the two sets are
disjoint on disc.

Across the 103 models: **2474 streamed animation blocks** against 548 in the resident
containers. `tools/model_anims.py` enumerates them and `build_index.py` caches them into
`rig_anim_index.json` under `"streamed"`.

Two consequences that had been read backwards for two sessions:

- A model whose resident animation range is a **single all-zero sector** does not lack
  animations — 39 models are in that state and their whole library is streamed. Model 854 has
  30 clips, 869 has 37, 875 has 31.
- Every humanoid NPC therefore has its **own rest pose**, in its own streamed blocks, and
  they differ substantially from each other: bone 1 is `-241` for the player characters, `-64`
  for 855, `-99` for 863, `-49` for 875. That is the "head sunk into the neck" / "too tall
  with a long neck" error the Blender review reported.

### The runtime object graph — CONFIRMED
```
actor + 0x15C  -> MODEL (0x70 bytes, resource record)
MODEL + 0x30   = index in resource array
MODEL + 0x38   = u16 model id   (matched by FUN_80026698)
MODEL + 0x3A   = s16 refcount
MODEL + 0x50   = mesh object array base   -> FUN_8004c7e0(base + meshIdx*0x54)
MODEL + 0x54   = animation descriptor table, 0x1C (28) bytes per entry
MODEL + 0x5C   = extra (passed to FUN_80045a08)

AnimDescriptor (0x1C):  +0x00 frameCount, +0x04 boneCount, +0x18 keyframe array ptr
```
Resource management: `FUN_80024b44` allocates `count * 0x70` models from a directory of
16-byte entries terminated by `0xFFFF` at +2 (`FUN_80026668` counts them);
`FUN_80026734` zero-inits one; `FUN_80024dd8` fetches by id and bumps the refcount.

The mesh index for each bone comes from the bone list: `*(s16*)(boneRec + 4)`.

### What is NOT yet solved — and what was ruled out
The 56/48-byte records are the **runtime work format**. Two hypotheses for the on-disc form
were tested and **both failed** (recorded so nobody retries them):
1. *Header stored verbatim with file-relative offsets* — scanned package files for a
   self-tiling `{count, offset}` table (`tools/find_mesh.py`); only absurd false positives.
2. *Header stored with absolute RAM pointers* (like the fixed-address overlays) — package
   files contain almost no words in the RAM range (1005 of 4,049,408 in file 832, all
   coincidental), so there is no absolute pointer table.

3. *An array of verbatim 0x54 mesh objects on disc* — `tools/find_mesh_array.py` scans for
   runs of consecutive valid records; zero real hits in model, character or minion files.

Conclusion: **the on-disc mesh is a compact form expanded into these structures at load.**

### The mesh block — located and header CONFIRMED across all 16 model files
```c
struct MeshBlock {
  /* +0x00 */ u32 totalSize;   // always <= the sector range it occupies
  /* +0x04 */ u32 meshObjects; // NOT the bone count - verified equal to the mesh object
                               // count for all 106 models, while 831 has 23 objects on a
                               // 22-bone rig and 893 has 26 on a 24-bone one
  /* +0x08 */ u32 offVerts;    // vertex / per-bone transform data
  /* +0x0C */ u32 offIdx;      // index / connectivity data
};
```
Validated by `tools/model_index.py`, which drives off the exe descriptor table.
Bone counts vary sensibly per model and the internal offsets scale with size:

| file | mesh sectors | totalSize | bones | offVerts | offIdx |
|------|--------------|-----------|-------|----------|--------|
| 833/834/845/846/847 | 20-37 | 34064 | 25 | 0x44 | 0x80D0 |
| 833 (2nd, small)    | 0-3   | 4208  | 12 | 0x6DC | 0x988 |
| 835 | 19-50 | 61568  | 23 | 0x74 | 0xE940 |
| 837 | 19-52 | 66000  | 23 | 0x72 | 0xFAB0 |
| 838 | 16-65 | 100032 | 37 | 0xAE | 0x17BE0 |
| 840 | 18-59 | 83676  | 40 | 0x3A | 0x1433C |
| 841 | 19-59 | 80112  | 35 | 0x68 | 0x13270 |
| 842/843/844/848 | ~16 | ~32300 | 22 | 0x84 | ~0x7600 |

`offVerts` holds small signed values consistent with vertex coordinates; `offIdx` holds
ascending `(u16, u16)` pairs like (2,7)(2,8)(16,0)(16,1) — index / connectivity data.
**Decoding those two arrays is the single remaining step for full geometry export.**

**Next concrete step:** the expander is reachable from `FUN_80025268` (the streaming loader
that reads the descriptor table). Follow what it does with the loaded sector range for the
`+0x50` mesh field — that function converts this block into the 0x54 objects.

A runtime check (PCSX-Redux: breakpoint `FUN_8004c240`, dump the pointed-to array, then
diff against these bytes) would settle it in minutes versus hours of static work. Not
*required* — the answer is in the binary — but now that the block is narrowed to a single
known location, the diff would be conclusive immediately.


---

## 3. Textures on models - SOLVED

A textured face carries a **tpage id** and a **CLUT id** in the first two u16 of its
chunk body, and per-vertex `u,v` bytes inside each vertex block:

| type | UV byte within the vertex block |
|------|--------------------------------|
| FT3 / FT4 (8-byte blocks)  | +6  |
| GT3 / GT4 (16-byte blocks) | +14 |

Confirmed from the converters: `FUN_80024798` reads GT4's UVs at body
0x22/0x32/0x42/0x52 (= block+14), `FUN_80024484` reads FT4's at block+6.

**How the pairing works.** The tpage names a VRAM page (64 words wide, 256 tall) plus
the colour depth, and `u,v` are texel coordinates *inside that page*. Each of the model's
TIMs lands at its own VRAM position, and together they tile the page exactly. So
rebuilding the page as one atlas reproduces precisely what the GPU samples, and the face
UVs can be used as-is - just divided by the page size.

Page texel width depends on depth, because VRAM x is measured in 16-bit words:
4bpp -> 256 texels, 8bpp -> 128, 16bpp -> 64; height is always 256. Faces of different
depths therefore get different atlases, keyed by tpage id.

Verification: model 833's FT4 faces use a 20x28 TIM at VRAM (378,480). Page origin is
(320,256) at 4bpp, so its texel origin is (378-320)*4 = 232 across and 480-256 = 224 down -
and the FT4 UVs run exactly u[232..251], v[224..251]. Exact, with no fudging.

### Shared CLUTs
Many TIMs carry an **empty CLUT block** (`bnum == 12`, no palette data): they reference a
palette another texture already uploaded to that VRAM slot. The parser initially rejected
these, which is why 8 of model 833's 10 textures looked like "not a TIM". `tim.py` now
accepts them and `texture_atlas.py` resolves the palette by VRAM position.

`tools/texture_atlas.py` builds the atlases; `export_gltf.py --tex SECTOR` embeds them as
PNG, one material per page, with nearest-neighbour sampling for the PS1 look.

## 4. Batch export

`tools/export_all.py <exe> <split_dir> <out_dir>` exports every model automatically:
it reads the descriptor table, finds each file's largest mesh block, its animation
container and texture container, then locates a matching rig.

**Rig discovery.** A bone table is a run of 8-byte records with a sequential self index and
a depth that never jumps by more than +1, terminated by -1. A table matches a model when
its bone count equals the mesh count and every meshIndex is in range and unique. Most rigs
are in the exe, but the larger creatures keep theirs in the **actor overlay packages** -
model 838's 37-bone rig is in file 0467, model 840's 40-bone rig in file 0422.

**Shared animations.** Some models ship no animations of their own: the four 22-bone models
(842/843/844/848) borrow a shared set from file 849. `export_all.py` searches neighbouring
files when a model has no matching animation container.

Result: **15 of the 16 models export** as rigged, animated, textured GLB, all passing
`check_glb.py`. Only model 841 is outstanding - no 35-bone animation container found yet.


---

## Scope note on "no morph targets"

This document states that the mesh and animation formats are accounted for byte-exactly and
that the renderer interpolates matrices rather than vertices. Both are true **of the data on
disc and of the draw path**. They do NOT mean the engine never blends geometry: merged
minions are demonstrably shape-blended, and that blend is computed at merge time into RAM.
See the corrected section in MERGE_ALGORITHM.md.


---

## 5. The full model census — the archive holds 104 meshes, not 16

The exe descriptor table at `0x800823F0` names only 16 models (files 833-848), so
`export_all.py` only ever saw 16. Scanning **every sector boundary of all 1079 archive
sub-files** for a mesh block whose chunk walk lands byte-exactly on the header's
`endOfMeshData` field finds:

- **106 files** with a valid mesh block: **831-933** contiguously, plus 10, 197 and 1072.
- **104 distinct meshes** (833, 917 and 922 are byte-identical triplets).

Grouping them by exact primitive-count signature (per chunk type, per mesh object) gives 58
signatures. One signature covers **49 files** — the mergeable minion morph family; see
`MERGE_ALGORITHM.md`. The other 55 are one-off creatures.

Bone counts across the census: 2, 4, 5, 14, 15, 16, 17, 19, 20, 22, 23, 24, 25, 26, 28, 35,
37, 40.

### Tools

- `tools/build_index.py <exe> <split> <out.json>` — one archive-wide index of **bone tables**
  and **animation containers**. Bone tables are located with a regex on the sequential
  `self` byte (stride 8), so validation only runs on real candidates and a full scan takes
  seconds. Use a **zero-width lookahead** in that regex: a consuming match eats 26 bytes and
  swallows the real table start, which is usually two bytes further on (this silently
  returned zero rigs first time round).
  Result: **244 bone tables** (counts 14,15,16,19,20,22,23,25,28,37,40) and
  **104 animation containers** (counts 1,2,9,12,16,20,22,23,25,26,37,40).
- `tools/export_every.py <exe> <split> <out> [--only A-B] [--jobs N]` — exports the whole
  census. Uses the index to borrow animations from anywhere in the archive (the 22-bone
  models borrow from 849, the 16-bone ones from 903, the 20-bone ones from system overlays
  19-22 — no +-40 file window would ever reach those). Falls back to an unrigged OBJ when no
  rig or no animation with the right bone count exists anywhere.
- `tools/appearance.py <split> [idx...]` — parses the appearance blob (below).

### Result

**106 of 106 exported**: 85 as rigged, animated, textured GLB (all pass `check_glb.py`, all
carry textures) and 21 as unrigged OBJ. The 21 are the bone counts with no rig anywhere
(2, 4, 5, 17, 24, 26, 35 — model 841 among them) or no animation container anywhere
(14, 15, 19, 28); since the **rest pose lives inside the animation block**, a model without
one cannot be skinned.

Output: `models/current/jc_NNNN_<Creature>.glb`, `jc_NNNN_<Creature>_static.obj`,
`jc_NNNN_<Creature>.appearance.json`, `export_report.json`. The name comes from
`tools/model_names.py` (species table for the creatures, scene-package actor records for the
NPCs, see `OVERLAYS.md` §2); the seven files neither table names keep the bare `jc_NNNN`
stem. See `models/README.md` for the folder layout.

## 6. The appearance blob — package section 0, `MODEL+0x4C`

Correction: MODEL_FORMAT previously listed a second mesh block in file 833 at sectors 0-3
("4208 bytes, 12 bones, offVerts 0x6DC, offIdx 0x988"). **That is not a mesh block.** It is
`{u32 size; u8 blob[size]}`, copied verbatim into `MODEL+0x4C` by `FUN_8002607C`, and it
holds everything about a creature that is not geometry:

- the **five growth stages** (global scale 0.40 -> 1.00, plus a per-bone scale array that
  encodes baby proportions),
- the **body-part flags** for the three swappable groups (arms = bones 3-8, wings = 12-15,
  legs = 17-22),
- the **43 attachment markers** (id, bone, local offset), including id 0x26 = the ground
  reference used to re-seat merged creatures on the floor,
- the **per-mesh blend weights** the merge blender uses.

Full struct in `MERGE_ALGORITHM.md`. Exactly the 49 morph-family files carry one (48 parse
with the standard layout; 850 lays its package out differently). Every one reports 25 bones,
5 stages, 43 markers.

**Exporter note:** the GLBs contain *all* geometry including part groups a species has
switched off, because the blend needs that geometry to exist. `jc_NNNN.appearance.json`
carries `hasPart: {arms, wings, legs}` — hide those bone groups to see the creature as the
game draws it. In a preview render, a disabled group shows up as thin collapsed slivers
(e.g. model 907 has all three off).


---

## 7. Export pass 2 — seam UVs, bind pose, and rig attribution

Three defects turned up when the v0.1 GLBs were opened in Blender. All three are now fixed;
`models/archive/v0.1/` keeps the old output for comparison.

### 7a. Seam vertices carry UVs — the empty UV strips

The connecting strips between bone parts rendered untextured, with a blank band left in the
UV layout exactly where (for example) a belly should sit. That was an exporter omission, not
missing data. Reading the game's own converters `FUN_80023074` (chunk type 8) and
`FUN_80023274` (type 9) field by field gives the full on-disc seam item:

```c
struct SeamVertex {          // 0x14 bytes
  /* +0x00 */ s16 nx, ny, nz;   // normal        -> runtime +0x04
  /* +0x08 */ s16  x,  y,  z;   // position      -> runtime +0x0C
  /* +0x0E */ u8  u, v;         // TEXEL COORDS  -> packed into runtime +0x12 (type 9 only)
  /* +0x10 */ u8  r, g, b;      // vertex colour -> runtime +0x00..+0x02
  /* +0x13 */ u8  pad;
};
```

and the type-9 chunk body has an 8-byte header `{u32 count; u16 tpage; u16 clut}` that
applies to the whole pool. Type 8 has only `{u32 count}` and the converter explicitly zeroes
the runtime UV word, so those seam vertices really are untextured.

Verified on model 833: the pool header reads `(tpage 149, clut 24688)` — byte-identical to
the pair its GT3/GT4 faces use — and every one of the 160 seam UVs samples an opaque texel
from that page (blues for 833, reds for 872, yellows for 907). All 68 stitch quads in 833
are now textured; only a single flat quad with no UVs in the source data stays untextured.

The UV values also explain the "empty strips": they are thin bands at the page edges
(u = 127 with v running 0..55, or v = 192 with u running 0..47), which is what a seam band
looks like when it is one texel wide.

### 7b. POSITION is now baked into bind-pose space

The exporter used to write each vertex in its **bone's local space** with identity inverse
bind matrices. That animates correctly, but Blender's edit mode shows raw POSITION data, so
every bone's geometry piled up on the origin and the mesh was useless for editing or UV work.

`export_gltf.py` now pushes every vertex through its joint's rest world transform and sets
`inverseBindMatrices[j] = inverse(bindGlobal(j))`. The 180-degree X rotation that turns PS1
Y-down into glTF Y-up is folded into the same transform, so joints and baked vertices agree.

Objectively unchanged: re-skinning model 833 gives bounds `X[-1.50,1.50] Y[-1.49,3.76]
Z[-3.14,4.45]` before and after, to the last digit. Raw POSITION now renders as an assembled
dragon instead of a heap at the origin.

`check_glb.py` had the identity assumption baked in too and was silently skipping the inverse
bind step; it now does full glTF skinning, which is what made the equality check meaningful.

### 7c. Rigs and animations are chosen by fit, not by bone count

A model file names neither its rig nor its animation set. Matching on bone count alone put a
foreign 23-bone rig and a foreign rest pose on model 831 (Levant): it has 23 mesh objects but
is really a **22-bone** model, with one spare mesh. The result was mangled.

`rigfit.py` scores a candidate pairing by **how well the stitch quads close**. Each stitch is
a quad whose four corners live in four different bones' local spaces, so under the correct
rig and rest pose they land within tens of units; under a foreign skeleton the parts fly
apart. Median stitch-quad extent, in game units:

| model | pairing | score |
|-------|---------|-------|
| 833 | exe rig `0x80079064` + own animations | **53** (MODEL_FORMAT records 53 for a correct assembly) |
| 831 | 23-bone rig + 835's rest pose (v0.1) | 121 — visibly broken |
| 831 | 22-bone rig + 849's rest pose | **32** — a clean humanoid |

Selection rules in `export_every.py`:
1. A candidate rig must cover the mesh block: every `meshIndex` in range and unique, and at
   most one spare mesh object (`0 <= nmesh - boneCount <= 1`, which is exactly the 831 case).
2. A candidate animation container must have the **same** bone count — the rest pose lives in
   its header, so a different count is a different skeleton.
3. Score must cover at least 80% of the stitch quads. Without this a 15-bone rig "fits" a
   25-mesh model and then wins on score because it is only ever judged on the few seams it
   can reach.
4. A model's own animation set is authoritative: sweep it across every candidate rig first
   and only look elsewhere if nothing of its own is believable. (Model 833 was otherwise
   being posed by 852's rest pose, which scored two points better.)
5. Borrowed animations may only come from the creature region (file index >= 600). Model 931
   had borrowed a 20-bone set from system overlay 21 and scored **110** — better than model
   930 with a genuinely correct rig at **113** — so fit alone cannot separate them, but
   provenance can. 930 renders as a clean robed figure; 931 was a jumble.
6. Anything left over is exported as unrigged geometry rather than with a wrong skeleton.

### 7d. Animation names

Actions were named `anim{i}_{n}f` with no model id, so importing several GLBs into one
Blender scene collided them into `anim5_40f`, `anim5_40f.001`, `anim5_40f.002` — which read
as mysterious "variants" but were just three different creatures' animations. Names are now
`jc0872_anim05_40f`, and single-frame blocks are called `pose` because that is what they are
(the 25-bone family ships 8 blocks: two 1-frame poses and six real motions).

The same collision hit the objects themselves: every model's root node was called
`JadeCocoonModel`. It now carries the export stem — `jc_0872_Patalchu` — so a scene with ten
models loaded is readable. The **action** prefix stays the bare index: action names have to
be unique across models, and the six Mahbu models (877-882) would not be.

### Result

**90 rigged, animated, textured GLB + 16 unrigged OBJ**, every GLB passing `check_glb.py`,
every one textured. Fit scores run 20 to 113 with a median of 53. `export_report.json` in the
output directory records, per model, the rig used, the animation source, whether the rest
pose was borrowed (34 models), and the fit score.

### Why the data is shaped so awkwardly for a modeller

The mesh is stored per bone in bone-local space, and the UVs are raw texel coordinates inside
a 256x256 VRAM page rather than normalised 0..1 over one texture. Nobody modelled it that
way: the creature was built whole and UV-mapped against the VRAM layout, then a build tool
split it per bone, packed the textures into pages, and emitted the seam pools to sew the
parts back together. The awkward form is the compiled output, not the source art.

### 7e. The Y-up flip belongs in the root joint, not a wrapper node

PS1 is Y-down, glTF is Y-up, and the exporter used to put the 180-degree X rotation on a
wrapper node above both the joints and the mesh. That is fine on its own, but once vertex
positions are baked into bind space (7b) they already carry the flip - and Blender applies
the mesh object's transform on top in edit mode, so the model appears **upside down** while
looking correct in object mode.

The flip is now folded into the local transform of the **root joint** (any bone whose parent
is itself), for the bind pose *and* for every animation frame, and the wrapper node is a
plain identity. Nothing above the mesh can apply it twice.

Keying the root's animated rotation matters: the renderer forces slot 0 to zero rotation, so
the naive export writes an identity quaternion there - which would undo the flip the instant
an action played.

Verified: joint-local vertices round-trip through bake -> inverse-bind to within 2e-4
(float32 noise), skinned rest bounds are unchanged from v0.1 to the digit, and the animated
pose at several frames of several actions matches v0.1 to 0.001. Raw POSITION Y now runs
-1.49 .. 3.76 for model 833 - upright.

### 7f. Animation census - which blocks actually move

Across the 90 rigged models, **549 animation blocks**: 432 move, 117 do not. Of the 117
static ones, **115 are single-frame** and 2 are two-frame. Every block with three or more
frames genuinely animates.

So "lots of animations that do nothing" is not an export fault: those are the pose blocks.
The 25-bone minion family ships eight blocks each - two 1-frame poses followed by six real
motions of 21 to 75 frames. They are named `poseNN_1f` now so they read as poses.

`export_report.json` records, per model and per block, `frames`, `maxRotDelta`,
`maxRootMove` and a `moves` flag, so this never has to be re-measured.
