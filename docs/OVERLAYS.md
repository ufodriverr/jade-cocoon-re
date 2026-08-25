# Overlays, actor spawning, and how a model gets a skeleton

Answers open thread 0 from `START_HERE.md`: *what picks a rig and an animation set for every
model that is not one of the 48 creatures.* Companion to `MODEL_FORMAT.md` (formats) and
`RIG_ATTRIBUTION.md` (what the export got wrong and why). Status tags follow `FINDINGS.md`.

---

## The one-line result

**CONFIRMED.** Nothing picks it. **Every spawn site names its skeleton by absolute address**,
and each package ships a private copy of the skeleton it needs. There is exactly **one**
22-bone humanoid skeleton in the whole game, linked into 149 packages, and a scene package's
generic actor spawner falls back to its own copy whenever an actor record leaves the rig
field null. The animation set is not chosen either: it always comes from the model, through
the exe's own model descriptor table.

---

## 1. Loading an overlay into Ghidra

**CONFIRMED.** Overlays are raw code+data images with no header, linked to a fixed address.
The exe has a descriptor table of `{u32 fileIdx, u32 destPtrPtr}` at `0x8007D90C`, 31 entries,
covering files 23-53; `destPtrPtr` points at the *slot variable* that holds the load address:

| slot var | load address | files |
|---|---|---|
| `0x8007311C` | `0x800CA058` | 29, 38, 39, 40 |
| `0x80073120` | `0x800A4018` | 30-35 |
| `0x80073124` | `0x800A0530` | 23, 24, 25, 26, **27**, 28 |
| `0x80073128` | `0x800B6890` | 36, 41, 42, 43, 46, 48, 51, 52 |
| `0x8007312C` | `0x800C2BB8` | 47, 50 |
| `0x80073130` | `0x800B6ED0` | 44, 45, 49, 53 |
| `0x80073134` | `0x800B2490` | not in the table - the scene/actor package slot, see §3 |

Then:

```
analyzeHeadless <proj> JadeCocoon/psx -process SLES_022.01 -noanalysis \
  -scriptPath tools/GhidraScripts \
  -postScript PatchOverlay.java <split>/0027_00148800.bin 0x800A0530 0 \
  -postScript DecompRange.java <outDir> 0x800A0530 0x800B248C
```

**How to check a load address without the exe table** (needed for the scene packages, which
are not in it): collect every `jal` target in the image and every `lui`+`addiu`/`lw` pair,
then find the base that makes them land on `addiu sp,sp,-X` prologues or on known structures.
File 27 puts **105 of 206** self-`jal` targets exactly on a prologue at `0x800A0530` and 0-4
at any neighbouring base; the misses are leaf functions with no stack frame.

**Overlay 44 spans `0x800B6ED0`..`0x800C0BF8`, so `FUN_800BF750` - the seed for this whole
thread - is inside it.** It is the merge UI drawing the creature you are about to merge,
which is why its rig pointer is `&DAT_80079064`, the exe's 25-bone creature rig.

### Genki source filenames

Overlays carry the PsyQ assert string. **File 27 is `ENMBATLE.C`**, the enemy battle overlay.
Grep any overlay image for `Assertion failed` and the filename follows it.

---

## 2. The spawn descriptor - `FUN_8001D4C4(SpawnDesc *)`

**CONFIRMED**, reconstructed from three independent call sites (`FUN_800BF750` in overlay 44,
`ovl_800A1F10` in overlay 27, `ovl_800B25F4` in scene package 203) and cross-checked field by
field against the two consumers, `FUN_8001E5DC` and `FUN_8001E858`.

```c
struct SpawnDesc {          // 0x50 bytes, built on the caller's stack
  /* 0x00 */ s32   modelId;     // >= 0: resolve with FUN_8002079C(id)
                                // <  0: use the modelPtr at +0x48 instead
  /* 0x04 */ s32   kind;        // 2 -> actor flag 0x1000
  /* 0x08 */ s32   x, y, z;
  /* 0x14 */ s16   rotX, rotY, rotZ;
  /* 0x1C */ s32   slot;        // actor index / spawn slot
  /* 0x20 */ s32   a, b;
  /* 0x28 */ s32   scale;       // 0x1000 = 1.0, written to actor +0x9C/A0/A4
  /* 0x2C */ s32   c;
  /* 0x30 */ s32   d;           // == 1 -> actor flag 0x40000
  /* 0x34 */ BoneRec *rig;      // <<< HARD-CODED SKELETON POINTER
  /* 0x38 */ s32   *globalScale;// 3 x s32, 0x1000 = 1.0  (FUN_80024EF8, per growth stage)
  /* 0x3C */ s16   *boneScale;  // 4 x s16 per bone       (FUN_80024F30, per growth stage)
  /* 0x40 */ void *animTable;   // FUN_80024EA0(model)  - the blob's animation table
  /* 0x44 */ void *markers;     // FUN_80024ECC(model)  - the 43 attachment markers
  /* 0x48 */ Model *modelPtr;   // used when modelId < 0
  /* 0x4C */ s32   wantExtra;   // allocate an extra 0x20 bytes per bone (actor +0x1C8)
};
```

`FUN_8001E858` copies the rig verbatim: it walks 8-byte records to the `-1` terminator,
allocates `(n+1)*8 + n*0x14` (plus `n*0x20` when `wantExtra`), and memcpys the table to
`actor+0x134`. The bone-scale array is copied 8 bytes per bone, falling back to the constants
at `DAT_80073FD4/FD8` when the pointer is null. **No per-bone rest offsets travel through the
spawn descriptor at all** - those live in the animation block, reached through `MODEL+0x54`.

---

## 3. Who supplies the rig

**CONFIRMED.** Four spawn sites, four literal pointers:

| caller | rig passed | for |
|---|---|---|
| `FUN_800BF750` (overlay 44) | `&DAT_80079064` | the merge preview creature |
| `ovl_800A1F10` (overlay 27, `ENMBATLE.C`) | `&DAT_80079064` | battle enemies |
| `ovl_800A97E8` (overlay 27) | `&DAT_800B10C8` = overlay 27 + `0x10B98` | the party humanoid in battle |
| `ovl_800B25F4` (scene package) | a per-actor field, **default `&DAT_800B4004`** | every field NPC |

`&DAT_80079064` is the exe's 25-bone creature rig. The two exe rigs are the only skeletons
main-exe code names, which is what made this thread necessary.

### The generic scene-package spawner, decompiled

```c
ActorInst *inst = *(param_1 + 0x10);
Minion    *sp   = inst[1];       // set when the actor is a tamed creature
ActorInfo *info = inst[0];       // the actor's static record in the package

if (sp == NULL) {                          // an NPC / prop
    modelId = info->modelId;               // +0x04
    rig     = info->rig;                   // +0x08   usually NULL
    gscale  = info->globalScale;           // +0x0C   usually NULL
    bscale  = info->boneScale;             // +0x10   usually NULL
} else {                                   // a creature
    modelId = SpeciesTable(sp->species)[0];
    stage   = FUN_8001900C(&tmp, sp);      // growth stage out of the 0xF8 minion struct
    rig     = &DAT_80079064;               // the exe 25-bone creature rig, unconditionally
    gscale  = FUN_80024EF8(model, stage);
    bscale  = FUN_80024F30(model, stage);
}
desc.rig         = rig    ? rig    : &DAT_800B4004;   // the package's own 22-bone humanoid
desc.globalScale = gscale ? gscale : &DAT_800B40BC;   // == rig + 0xB8
desc.boneScale   = bscale ? bscale : NULL;
desc.animTable   = FUN_80024EA0(model);
desc.markers     = FUN_80024ECC(model);
actor = FUN_8001D4C4(&desc);
```

`&DAT_800B4004` is that package's own copy of the 22-bone table, and `&DAT_800B40BC` is the
`{0x1000, 0x1000, 0x1000}` unit scale that sits immediately after it. **That default is the
whole mechanism** behind "no model package names its own skeleton": an ordinary humanoid NPC
does not name one because it does not have to - the scene it stands in supplies it.

### `ActorInfo` +0x00 is the actor's name

**CONFIRMED.** The spawner never reads field +0x00, so decompiling it alone left the record
starting at `modelId`. It does not: +0x00 is a `char*` into the package's own string pool,
holding the actor's name in the same Shift-JIS full-width Latin the exe uses for species
names.

```c
struct ActorInfo {          // the actor's static record in its scene package
  /* 0x00 */ char     *name;         // "Garai", "Mahbu", "Old Woman"
  /* 0x04 */ s32       modelId;      // index into the exe descriptor table
  /* 0x08 */ BoneRec  *rig;          // usually NULL - the package default applies
  /* 0x0C */ s32      *globalScale;  // usually NULL
  /* 0x10 */ s16      *boneScale;    // usually NULL
};
```

That makes the 272 scene packages a **model-file name table for every NPC**, which is what
`tools/model_names.py` reads: scan files 199-470 for a pointer into the package followed by
a valid model id and three pointers that are null or in-package, and 48 model files that no
species names get their name. The evidence that the layout is right is that the two
independent tables agree wherever they overlap - `870 Kikinak`, `876 Masked Boy`,
`893 Poacher`, `930 Dream Man` and `835 Fire Boss` are named identically by the species
table and by an actor record. Where they disagree, the species table holds the player-facing
name and the actor record holds Genki's internal codename (`836` is `Tuturis` to the player,
`BSFS` in the package).

### There is exactly one humanoid skeleton

**CONFIRMED.** Of the 244 bone tables in the archive, **149 have 22 bones**, and:

- **132 are byte-identical** (file 27 `@0x10B98`, file 111 `@0x1DDC`, and 129 scene packages);
- **16** differ only in bone 0's flag word (`0x44` instead of `0x46`);
- **1** (file 207) differs only in the same word (`0x02`).

Every one of the 131 scene packages that carries one contains a code word referencing exactly
`base + rigOffset`, and a second referencing `base + rigOffset + 0xB8` - the rig and the unit
scale, i.e. the two defaults above. **That agreement across 131 files is what fixes the scene
package load address at `0x800B248C`**, and it also confirms the fallback is real code, not a
decompiler artefact.

So rig attribution for a 22-bone humanoid is not a guess and never had an alternative. The
export has been using the right table all along.

---

## 4. Who supplies the animation set

**CONFIRMED.** The model does, and the exe says exactly where. Full layout in
`MODEL_FORMAT.md` § "The model descriptor table"; in brief:

- `MODEL+0x4C` is the appearance blob. `FUN_80024EA0` returns its **animation table**; each
  entry selects a clip.
- `MODEL+0x54` is the runtime array of `0x1C`-byte animation descriptors, one per animation,
  built by `FUN_80026AF4` from the on-disc blocks.
- The descriptor table at `0x800823F0` names, per model, both the resident animation container
  **and a per-animation streamed sector table**. `FUN_800254A8(model, animId, ...)` reads
  `desc[desc[9] + animId*2 + 10]` for the `{startSector, sizeSectors}` of one clip and streams
  it in on demand.

`ovl_800A97E8` is the consumer side for the battle party:

```c
clip  = model->animDescs[ animTable[actionId * 0x40] ];   // entry byte 0 = animation id
frame = counter % clip->frameCount;
draw.rig       = &DAT_800B10C8;         // overlay 27's own 22-bone table
draw.boneScale = &DAT_800B1180;         // == rig + 0xB8
FUN_80046A7C(&draw, ...);
```

with the animation-table index remapped by `FUN_800AC964`:

```c
if (actionId - 14u < 0x60) return actionId + variant * 16;   // ids 14..109 come in variants
return actionId;                                             // ids 0..13 are shared
```

`variant` is `DAT_800B13AC[DAT_8008BD34]`, a small per-overlay table indexed by a global
(weapon or stance). Entry fields in use: `+0x00` animation id, `+0x01` a flag, `+0x06` the
loop-restart frame, `+0x08` the end frame, `+0x34` a sub-record.

The **entry stride is 0x40 for models 831/832** (the player characters), matching the 64-byte
stride `RIG_ATTRIBUTION.md` had already measured for them from the table's own extent; every
other model measures 60.

---

## 5. What this settles, and what it does not

| open question | answer |
|---|---|
| what picks the rig | nothing - a literal pointer per spawn site, defaulting to the package's own 22-bone humanoid table |
| the 22-bone humanoid rig | one table, 149 copies, already the one the export uses |
| per-model NPC rest poses | in each model's **streamed** animation blocks - found, and now exported |
| where the animation frame stream lives | the per-animation sector table in the exe model descriptor; 2474 blocks over 103 models |
| the 24- and 26-bone skeletons | **they do not exist on the disc, and they ARE needed.** A scan of the raw 211 MB DATA.001 - gaps between file-table entries included - finds bone tables at 14, 15, 16, 19, 20, 22, 23, 25, 28, 37 and 40 bones and nothing else. A shorter rig runs the model's own clips and places the first N bones plausibly, but strands every mesh object past N; a Blender review of 870/879/893/930 reads exactly that way. See §7 |
| model 841 | the one model left with real animation data and no rig. 35 mesh objects, 35-bone clips, and every table of 35 bones or fewer fails `rigfit`'s 80% stitch-coverage floor |
| model 840 | still wearing 836's 40-bone table. Its streamed set holds 40- **and 41-bone** blocks, which is a new lead |

---

## 6. Rig length and clip length are independent

**CONFIRMED** from `FUN_80047E4C`, the skeletal walker. It iterates the **rig's** records
until the `-1` terminator and, for each one, reads

```c
angles = clip->keys[(frame * (clip->boneCount + 2) + rec->self + 2) * 6];
```

so the clip is indexed by the record's `self` byte at the **clip's** stride. The rig's own
length never enters the calculation; a clip only has to be at least as long as the rig. The
record's depth word (`+0x00`) is used as a matrix-stack index, which is the third
independent confirmation that **parent is implied by depth**.

The function takes two clips and a weight and blends them, both indexed by the same `self` -
that is the action crossfade `ovl_800A97E8` drives with `0x1000 - fade`.

Consequences for the export, all measured against each model's **own** clips:

| model | was | now | fit |
|---|---|---|---|
| 870 | 25-bone rig + 867's clips | 23-bone rig + its own 26-bone clips | 95 -> **55** |
| 879 | 25-bone rig + 867's clips | 25-bone rig + its own 26-bone clips | 81 -> **43** |
| 893 | 25-bone rig + 895's clips | 23-bone rig + its own 24-bone clips | 90 -> **52** |
| 930 | 23-bone rig + 835's clips | 23-bone rig + its own 24-bone clips | 104 -> **85** |

A known-correct assembly scores ~53 (model 833), so 870, 879 and 893 land in the right band.
930 is better but still the weakest of the rigged models.

The relaxation is deliberately allowed **only for a model's own clips**. A foreign clip of a
different length is a different skeleton, and letting it in would put a creature's 25-bone
set on a humanoid.

**It is a partial fix, not a fix.** See §7.

---

## 7. The five models whose skeleton is not on the disc - where this actually stands

**870, 879, 893, 930** (and **841**, still unrigged) own animations at 26, 24 and 35 bones.
No table of those sizes exists anywhere - checked three ways, most recently across the raw
211 MB archive including the ~951 KB of inter-entry gaps.

Running their own clips on a shorter rig (§6) improved every fit score, but a Blender review
of the result is unambiguous: *"partially better... like trying to be at correct places"* -
the head, an arm, a beak land correctly and everything past the rig's last bone hangs off in
space. That is the expected signature: mesh objects past the rig are parented to the root.
**So the shorter rig is an improvement, not a solution, and the missing tables are needed.**

### Deriving the table - tried, and not good enough

Two facts reduce a bone table to one integer per bone:

* **`meshIdx == self` in all 244 tables on the disc**, so a bone draws the mesh object with
  its own index.
* **Parent is implied by depth**, so choosing bone k's depth picks its parent off the
  rightmost path built so far. The whole table is a depth array.

`tools/derive_rig.py` beam-searches that array against the mesh's stitch quads, scoring each
quad the moment its last bone is placed. Validated by deriving rigs we already have:

| model | bones | parents recovered | derived fit | real fit |
|---|---|---|---|---|
| 833 | 25 | 17/25 | 55.2 | 52.7 |
| 867 | 25 | 21/25 | 44.0 | 51.0 |
| 831 | 22 | 18/22 | 32.4 | 32.3 |
| 840 | 40 | **9/40** | 57.1 | 68.1 |

It finds *a* skeleton that closes the seams, not *the* skeleton - and on 867 it scores
**better** than the real table, so the metric cannot be trusted to choose between them. The
stitch records only witness about 15 of 24 true parent edges (measured on 833, 835, 831 and
867), and the rest are unconstrained.

`tools/export_derived.py` writes the derived variants to
`models/derived_experiment/` for eyeball comparison. **They are not shipped.**

**Blender verdict (2026-08-25): the derived rigs look better than the short ones and are
still wrong.** So the derivation is picking up real structure - it is not noise - but the
60-85% of parents it gets right are not enough. Worth knowing before anyone re-runs the
search with a wider beam: the beam is not the bottleneck, the objective is. Any next attempt
needs a constraint the stitch graph does not provide, or the real table.

### What would actually settle it

The stitch graph is the only geometric witness and it is too sparse. The remaining leads are
code, not data: find the routine that draws these five - they are not ordinary field NPCs or
battle enemies, since both of those paths pass a literal 22- or 25-bone pointer - and read
the rig pointer it uses. Model **840** is the cheapest way in: it is rigged from **836**'s
40-bone table, the only 40-bone table on the disc, and its streamed set holds a **41-bone**
clip next to the 40-bone ones.

---

## Things that will bite you again

- The exe's model descriptor table is **103 entries**, one per model file. `model_index.py`
  had `NPTR = 16` hard-coded, and every doc that said "the exe descriptor table only names 16
  models" was quoting that constant, not the data.
- A load address that is not in the `0x8007D90C` table is still discoverable: 131 scene
  packages agreeing on `base + rigOffset` is far stronger evidence than one plausible-looking
  slot variable. Note `0x80073134` holds `0x800B2490`, four bytes above the real base.
- `PatchOverlay.java` writes into the shared Ghidra program. Overlay 27 (`0x800A0530` +
  `0x11F5C`) stops exactly at `0x800B248C`, where the scene packages start, and overlay 44
  starts at `0x800B6ED0`. Patch a big scene package and you will silently overwrite one of
  the others; re-patch what you clobbered before trusting the next decompile.
