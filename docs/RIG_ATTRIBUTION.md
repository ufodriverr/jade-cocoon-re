# Rig / animation attribution — why 18 models export broken

Triage of a Blender review of the v0.2 export (`models/current/`). The reviewer
flagged 18 of the 90 rigged GLB as visibly wrong: wrong animation set, "head in the neck",
or "too tall with a super long neck and legs".

Companion to `MODEL_FORMAT.md` (mesh/skeleton/animation formats) and `MERGE_ALGORITHM.md`
(the appearance blob). Status tags follow `FINDINGS.md` convention.

> **Superseded in v0.4 by `OVERLAYS.md`.** The diagnosis below is right about *which* models
> are wrong and wrong about *why*. The class-B models were never short of a rig, and the
> shared 849 rest pose was not a fallback — it is the only 22-bone pose in the resident
> containers. Each of them owns a **streamed** animation set with its own rest pose, listed
> in the exe's model descriptor table; see `MODEL_FORMAT.md` § "The model descriptor table".
> With that wired in, **102 of 106 models export rigged and only 4 still borrow a pose**
> (870, 879, 893, 930 — the ones that need the missing 24/26-bone skeletons). Read this file
> for the triage history and the metric caveats, which all still hold.

---

## The one-line result

**CONFIRMED.** The export is wrong exactly where we have no ground truth, and right
everywhere we do. 48 models carry a parsed appearance blob with growth stages; **none of
those 48 was reported broken.** All 18 reported models are among the 42 that export with a
rig guessed purely from mesh-object count and a rest pose borrowed from another creature.

| class | n | has blob stages | rig source | reported broken |
|-------|---|-----------------|------------|-----------------|
| A — creature, ground truth | 48 | yes | matched, verified | **0** |
| B — shared rest pose | 23 | no | guessed, anims borrowed | 9 |
| C — rig one bone short | 11 | no | guessed, `mesh = bones+1` | 6 |
| D — own anims, no ground truth | 8 | no | guessed | 1 (840) |
| STATIC — unrigged OBJ | 16 | n/a | none found | n/a |

For all 48 class-A models the blob's `boneCount` equals the rig bone count the exporter
picked — **zero mismatches**. The fit-score attribution (`rigfit.py`) is sound; it simply
has nothing to work with outside the creature family.

---

## The structural discovery — every model already names its own skeleton

**CONFIRMED.** `appearance.py::parse` demands `offAnimTable`, `offMarkers` and `offStages`
all be non-zero:

```python
if not all(0 < o < size for o in (off_anim, off_mark, off_stage)):
    return None
```

Non-creature models legitimately have **`offMarkers == 0` and `offStages == 0`** — they do
not merge, so they carry no attachment markers and no growth stages. The parser therefore
returns `None` for every one of them and we throw away the rest of the blob, including the
`boneCount` we need.

Verified over all 106 model packages: **103 carry a valid section-0 blob at file offset 0**
with `offAnimTable == 0x0C`. The 3 that do not are `10`, `197`, `1072` — the non-contiguous
outliers already known to be odd.

```c
// file offset 0 of every model package
struct Section0 { u32 size; u8 blob[size]; };
// blob:
u32 offAnimTable;   // ALWAYS 0x0C — never zero
u32 offMarkers;     // 0 for non-merging models  <-- rejected by the current parser
u32 offStages;      // 0 for non-merging models  <-- rejected by the current parser
```

`boneCount` currently comes from the stage header (`offStages`), which is why it is
unavailable for exactly the models that need it. It has to be recovered another way for
class B/C/D — see "What to do next".

### The animation table is `count × 60` bytes

**CONFIRMED (59/61).** `offAnimTable` points at `{u32 count; Entry[count]}` with a
**60-byte** stride; the table ends exactly at `offMarkers` wherever `offMarkers != 0`.
Checked on all 61 models where both offsets are present: 59 hit `16 + count*60 == offMarkers`
exactly. The two exceptions are **831 and 832 at 64 bytes** — Levant and the other player
character, consistent with a richer per-animation record.

`appearance.py` reads `count` and stops. The entry payload is unparsed.

**HYPOTHESIS.** Each entry is 30 `u16`; `-2` (`0xFFFE`) fills unused slots and the record
ends in six `-1`s. Reading across all 1868 entries in the archive:

```c
struct AnimEntry {          // 60 bytes; 64 for models 831/832
  u8  clipId;               // 0..30, repeats across entries - a clip index, not a block
  u8  flag;                 // 0 or 1
  s16 startFrame;           // 0 for most; ascending within a clipId group
  s16 range[2][11];         // (start,end) frame pairs, -2 = unused
  s16 term[6];              // all -1
};
```

The frame numbers run well past any single stored block — model 854's table reaches frame
299 — so the table looks like **clip slices over a longer frame stream** rather than
indices into the 8 animation blocks. Model 854's `clipId == 16` entries carry starts
0, 19, 49, 109, 139, 182, 242 in order, which is the shape of a timeline being cut up.

Where that stream lives is **not solved**. It is not the model's own animation container,
and it is not in the rig-bearing overlay files (files 27, 195, 408, 422, 467 contain bone
tables and **no** animation containers at all). Do not assume the anim table can be used
for attribution until the stream is found.

`FUN_800BF750` is the only consumer: it passes the table straight into the actor spawn
(`FUN_8001D4C4`) alongside the marker list, the stage data and a **hard-coded** rig pointer
(`&DAT_80079064`). That is the reason no model package names its own skeleton — the rig is
chosen by the spawning code, and for everything except the two exe creature rigs that code
lives in an overlay.

---

## The four failure modes

### B — 23 models share one rest pose (9 reported)

`854 855 863 869 875 877 878 933` (+ `871`), and unreported `842 843 844 848 885 886 889
890 891 906`, plus `880 887 905` on the 16-bone rig.

Every one of them has **no animation container in its own package**. `choose_rig_and_anim`
falls through to `sweep(False)` and they all land on the same donor: **file 849's 22-bone,
4-animation container**, borrowed by 22 models. `849` in turn borrows `835`.

The rest offsets — the bone lengths — live in the animation block header. One donor rest
pose therefore gives **every humanoid NPC the same body proportions**. A short NPC on a
tall skeleton reads as "head sunk into the neck"; a tall one reads as "super long neck and
legs". The reviewer's read that the animations are the protagonist's is correct: the whole
NPC population is playing 835's set through the 849 hop.

Why `rigfit.py` scores these 28–43 (well inside the believable band) anyway: the stitch-quad
metric measures whether **seams close**, which is a function of rig topology, not of limb
length. A wrong rest pose on the right topology still closes its seams. The metric is not
broken — it is measuring something these failures do not disturb.

### C — 11 models take a rig one bone short (6 reported)

`849 876` (24 meshes → 23-bone rig), `870 879 893 930` (26 → 25), `871 894 831 832` (23 → 22),
`904` (17 → 16). The candidate filter is:

```python
and 0 <= nmesh - len(r["table"]) <= 1
```

so a rig can never have **more than one** fewer bone than the model has mesh objects, and
never more bones than meshes at all. Two consequences:

- **849 is denied its own animations.** File 849 holds a 22-bone × 4 container — the very
  set 22 other models borrow — but 849 has 24 mesh objects, so `24 - 22 = 2` fails the
  filter. It took a 23-bone rig from file 408 and 835's animations instead. **849 is
  almost certainly a 22-bone model** that should be using its own container.
- **870 is denied its own animations.** File 870 holds a **26-bone × 2** container. There
  is no 26-bone rig anywhere in the 244-table index, so no candidate survives and it fell
  back to the 25-bone creature rig plus 867's animations. The reviewer's "870 has creature
  animations, should have own unique ones" is precisely this. `879` similarly holds a
  12-bone × 1 container.

**CONFIRMED.** The index holds 20 distinct skeletons at 14, 15, 16, 19, 20, 22, 23, 25, 28,
37 and 40 bones. **There is no 24-bone and no 26-bone table in the archive** — yet a 26-bone
animation container exists, so a 26-bone skeleton demonstrably exists in the game. Those
tables are stored some other way, the same open thread as the 16 unrigged models.

### D — 884, 902, 840 (2 + 1 reported)

`884` and `902` have 25 meshes and 25 bones and so matched the **exe creature rig** by shape
alone — but they carry no appearance blob stages and no animations of their own, so they are
not creatures. They borrowed `883`'s and `895`'s sets. The reviewer's note that 884's
rig/animations "are actually used for 883" is the same observation from the other side.

`840` has 40 meshes, 40 bones and its **own** 40×2 animation container, yet still reads
wrong. There is exactly **one** 40-bone table in the whole archive (`422@0x180C`) and `836`
uses it too. One of those two models is wearing the other's skeleton.

---

## Hidden body parts — the fox with hands is correct data

**CONFIRMED**, and already documented in `MERGE_ALGORITHM.md` § "Part flags". The reviewer
asked whether `jc_0860` (a bird) is supposed to have hands. It is. The game hides them.

`partFlagsA[3]` per growth stage gates three fixed bone groups (`FUN_80019B14`):

| group | mask | bones | part |
|-------|------|-------|------|
| 0 | `0x80072F60` = `0x000001F8` | 3–8 | arms / front limbs |
| 1 | `0x80072F64` = `0x0000F000` | 12–15 | wings |
| 2 | `0x80072F68` = `0x007E0000` | 17–22 | rear legs |

`partFlagsA[i] < 2` clears bit 1 of `boneRec+6` for every bone in mask `i`, which gates both
the transform and the draw. `jc_0860` is `[0,2,3]` at stages 0–2 and `[1,2,3]` at stages 3–4:
**arms hidden at every growth stage**, wings and legs drawn.

The merge rule (step 7 of `FUN_80010DB0`) is exactly the reviewer's guess:

```c
if (other.A[k] > 1 && mine.A[k] == 1) mine.A[k] = 2;   // gain the part
```

So the geometry has to be present on every model for the merge to be able to turn it on —
which is the same reason all 49 morph-family models share one topology. Note the rule needs
`mine.A[k] == 1` **exactly**: `jc_0860` is `0` at stages 0–2, so it can only gain arms once
it has grown to stage 3.

**This is systematic, not a one-off: 26 of the 48 creatures ship at least one hidden group.**

| flags at full growth | n | reading |
|---|---|---|
| `(2,2,3)` | 16 | everything drawn |
| `(3,1,3)` | 11 | no wings |
| `(2,1,3)` | 7 | no wings |
| `(1,2,3)` | 5 | no arms — `860 861 862 913 916` |
| `(3,2,3)` | 3 | everything drawn |
| `(1,1,1)` | 3 | **no arms, no wings, no legs** — `907 908 909` |
| `(2,3,3)` `(3,2,2)` `(3,3,3)` | 1 each | — |

**The exporter never reads `partFlagsA`** (no reference in `export_gltf.py`, `export_every.py`
or `export_mesh.py`). Every GLB ships the full bone-group geometry unconditionally, so all
26 of these show parts the game does not draw. That is an export gap, not corrupt data.

---

---

## Fixed in v0.3

All verified against the v0.2 export in `models/archive/v0.2/`; **no model's fit
score got worse**, and all 94 GLB pass `check_glb.py`.

1. **`appearance.py::parse` accepts absent sections.** Blob coverage **48 → 103 of 106**
   models (the 3 misses are 10/197/1072). Stage and marker output for the 48 creatures is
   byte-identical to v0.2. The animation table is now parsed too — count, derived stride and
   raw entries — and lands in every `jc_NNNN_<Creature>.appearance.json`.
2. **`MESH_SLACK` replaces `0 <= nmesh - bones <= 1`** (now 3). Safe because a candidate rig
   must still find an animation source with its exact bone count and own-file sources are
   tried first. Results:
   - **849: fit 100 → 33**, and it finally uses **its own** 22-bone rig and 4 animations
     instead of a 23-bone rig and 835's. It was the donor for 22 other models while being
     misattributed itself.
   - **884: fit 78 → 41** and **902: fit 103 → 34** — both are humanoid NPCs on the 22-bone
     rig, not creatures. They only matched the 25-bone creature rig because 25 meshes met
     25 bones.
   - **881, 882, 888, 897** now export rigged instead of static: **94 rigged / 12 static**
     (was 90 / 16).
   - 930 improved 113 → 104 but is still poor; it is not fixed.
3. **Hidden body-part groups are exported as separate nodes.** `hidden_arms` /
   `hidden_wings` / `hidden_legs`, skinned to the same skeleton, for the **26 creatures**
   that ship them. Hide the node to see the creature as the game draws it; show it to see
   what a merge can turn on. Verified on `jc_0860`: the split node holds exactly bones 3–8,
   matching mask `0x1F8`.
4. **Mesh objects no bone claims are no longer dropped.** v0.2 emitted geometry only per
   bone, so every model with more mesh objects than bones lost real geometry — **32 mesh
   objects across 17 models**, including a 79-primitive object on 870, 59 on 871 and 42 on
   904. They now export as an `unclaimed` node skinned to the root joint. Checked against
   the seam records: on 870, 893, 930, 849, 876 and 871 the extra object has **no** stitch
   quads, i.e. it is genuinely a detached prop, so parenting it to the root is right. Only
   **879** stitches its extra object (to bones 15, 22, 24), so 879 really does have a 26th
   bone.
5. **`check_glb.py` validates every mesh**, not just `meshes[0]` — otherwise it would have
   skipped exactly the new hidden-part and unclaimed geometry.

## Fixed in v0.4 — the streamed animation table

The four failure modes above all bottomed out in "the actor-spawn code in the overlays".
Running that thread down (`OVERLAYS.md`) produced the data, not from the overlays but from
the exe descriptor table their loader reads:

1. **`anim.py::parse_block` rejected every flagged block.** Bit 31 of the boneCount word
   means "an event list follows"; bit 31 of the frameCount word means "an extra u32 precedes
   the rest offsets". Reading them raw gave boneCount 2147483670. Fixing it recovered the
   resident containers of **831, 832, 841, 876, 893 and 930** — including the claim in
   `START_HERE.md` that files 831/832 hold **zero** animation blocks. They hold five each.
2. **The exe descriptor table is 103 entries, not 16** (`model_index.py` had `NPTR = 16`),
   and past the four whole-file ranges each descriptor carries a per-animation
   `{startSector, sizeSectors}` table. **2474 streamed animation blocks over 103 models.**
3. **Class B is dissolved.** Those models were not missing animations; their resident range
   is a single empty sector and their whole library is streamed. 854 has 30 clips, 869 has
   37, 875 has 31 — each with its own rest pose. Bone 1 measures `-241` on the player
   characters, `-64` on 855, `-99` on 863, `-49` on 875 and 877. **That spread is the
   reported error**: the export was giving short NPCs the protagonist's proportions.
4. **Class C and D mostly dissolve with it.** 884, 902, 871, 882, 888 and the rest now use
   their own sets. 8 models that exported as unrigged OBJ (896, 910, 911, 925, 926, 927, 928,
   931) now find an animation source at their own bone count.

Result: **102 rigged / 4 static**, 4 borrowers, median fit 52.7 -> 47.4, all 102 GLB pass
`check_glb.py`. `export_report.json` gains `animSlots` / `animSlotsTotal`; only 831 and 832
are capped (48 exported of 197 and 196 — `MAX_ANIMS` in `export_every.py`).

### And one thing the triage got backwards

The class-B section below argues that one donor rest pose for the whole humanoid population
is the bug. It is worth recording that the *shared pose itself* was never wrong: 831, 832
and 849 have **byte-identical** rest offsets, and the 22-bone rig is byte-identical across
132 packages. The bug was not that the export shared a pose — it was that a per-model pose
existed and had not been found.

## What is still broken

**Nothing borrows a rest pose any more.** The four that did in v0.4 - `870 879 893 930` -
were held back by the exporter demanding `clip.boneCount == rig.boneCount`. The renderer does
not: `FUN_80047E4C` walks the rig and indexes the clip by each record's `self` byte at the
clip's own stride, so a clip only has to be **at least as long as** the rig. Allowing that for
a model's own clips gives 870 a 23-bone rig with its own 26-bone clips (fit 95 -> 55), 879 the
exe creature rig with its own 26-bone clips (81 -> 43), 893 a 23-bone rig with its own 24-bone
clips (90 -> 52) and 930 the same treatment (104 -> 85). See `OVERLAYS.md` §6.

Two things are genuinely left:

- **Model 841** - 35 mesh objects, its own 35-bone clips, and every table of 35 bones or
  fewer fails `rigfit`'s 80% stitch-coverage floor. The only model with real animation data
  and no rig.
- **Model 840** - rigged and animated from its own data, but on **836's** 40-bone table, the
  only 40-bone table on the disc. Its streamed set holds a 41-bone clip next to the 40-bone
  ones, which is the next lead.

The 24-, 26- and 35-bone skeletons this file kept asking for **do not exist**: a scan of the
raw 211 MB DATA.001, gaps included, finds bone tables at 14, 15, 16, 19, 20, 22, 23, 25, 28,
37 and 40 bones and nothing else. Two of the three were never needed.

The historical triage below is kept as written.

1. **Per-model rest poses for the 23 class-B models.** Still one donor pose for the whole
   humanoid NPC population, which is the "head in the neck" / "long neck and legs" error.
   849's own pose is now correct, but the 22 borrowers still share it. Their real poses are
   not in their packages and not in the archive's animation containers.
2. **The 24- and 26-bone skeletons.** 870's own 26-bone container is well-formed (168
   bytes/frame = 26x6+12, mirrored L/R limb offsets), so the skeleton exists. **Tested and
   rejected:** the 25-bone creature depth array plus one appended bone scores **101** for
   870 against its own rest pose — worse than the 95 it gets borrowing 867's. 870's topology
   is genuinely different; do not synthesise it.
3. **Model 840 — it borrows 836's rig.** See below.
4. **Where the animation frame stream lives** — see the anim-table section above.

All four bottom out in the same place: **the actor-spawn code in the overlays**, which is
what picks a rig and an animation set for everything that is not one of the 48 creatures.
That is the next real thread; `FUN_800BF750` shows the shape of the call to look for.

---

## Model 840 in detail — the boss wearing 836's skeleton

840 is the one reported model that has **its own animations** and still exports wrong, so it
was worth running down separately. Conclusion: **its bone table is not in the archive and it
is borrowing 836's.**

What is established:

1. **840 really is a 40-bone model.** Its own animation container is well-formed — 2 blocks,
   55 and 70 frames, and the rest offsets are identical across both blocks.
2. **Exactly one 40-bone table exists archive-wide**, `0422_00FC9800.bin@0x180C`, and 836
   uses it too. Confirmed twice: the strict index scan, and a manual walk of file 422, which
   holds only a 23-bone table at `0x15A8` and the 40-bone one at `0x180C`.
3. **There are only two 40-bone animation containers** — 836's and 840's own. All four
   mesh x rest-pose combinations were scored; each model's own pose is clearly best (840 on
   its own: total assembly gap 818; on 836's: 973). **They are not swapped.**
4. **The fit score of 68 is meaningless here.** It covers **12 of 840's 40 bones** — the limb
   and claw bones carry no stitch records at all, so `rigfit` never looks at exactly the
   parts that come out detached. Now reported as `fitBones` / `fitBonesOf`; 836 and 840 are
   the only two models in the export where it drops under half.
5. **The error is structural, not an animation bug.** Total parent-child assembly gap is
   flat across all 125 frames of both animations (811-851), and identical at frame 0.
   836 on the same rig sits at 166, essentially all of it the legitimate root offset.
6. **The markers give it away.** 840's marker ids `0x127/0x128/0x129/0x12A` and
   `0x19F/0x1A0/0x1A1/0x1A2` are two four-fold sets landing on bones **12, 6, 24, 18** with
   the same offset `[0, 103, -32]` — the game treats those four as equivalent effectors. In
   the shared rig they sit at depths 6, 6, 6 and **3**: bones 6 and 12 are claw tips, 24 is
   one bone short of its claw tips (25/26/27), and **18 is a bare leaf hanging off bone 2**.
   A skeleton where four equivalent effectors have three different depths is not 840's.
   836's markers, by contrast, all land on genuine chain ends.

### Approaches tried and rejected

- **Deriving the parenting from the geometry.** Cost matrix of every (parent, child) pair by
  how well the child's mesh, placed at its rest offset, meets the parent's mesh. Validated
  against 836 first, where the answer is known: it recovered **7 of 39** parents. Large mesh
  objects overlap most candidates, so nearly everything ties at gap 0. Not usable.
- **Assembly gap as a general quality metric.** It cleanly separates 836 from 840 on a shared
  rig, but as an absolute score across models it false-alarms badly: 907 scores 172% of model
  extent, 899 98%, 924 96%, all of which look correct — creatures legitimately have detached
  spikes, orbs and floating parts. **Only meaningful when comparing one model across rigs.**
  Deliberately not shipped in the report.
- **A relaxed archive scan for a second 40-bone table**, dropping the sequential-`self`
  requirement. Thousands of false positives from runs of zeros; the `self` byte is the only
  thing that makes the pattern specific. No second table.

## Things that will bite you again

- A validator that shares an assumption with the thing it validates proves nothing — again.
  `rigfit.py` scores seam closure, which is invariant to limb length, so it rates a wrong
  rest pose 28–43 and calls it excellent. It cannot catch class-B failures **by construction**.
  Score proportion separately (e.g. mesh bounding box vs. rest-pose skeleton extent).
- A strict struct parser that returns `None` on a legitimately-zero optional field silently
  removes an entire population from the dataset. The 48/90 appearance-blob coverage looked
  like "only creatures have blobs"; it was really "only creatures pass the validator".
- Do not read `boneCount` from the stage header alone — it is absent for exactly the models
  whose bone count is in doubt.
