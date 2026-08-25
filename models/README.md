# Exported models

Everything here was generated from a disc by `tools/`. A prebuilt copy is committed so
you can open the models without owning the game; re-running the pipeline in
`docs/START_HERE.md` against your own disc overwrites this folder in place and should
produce byte-comparable output.

| folder | what |
|--------|------|
| `current/` | **the live export.** 102 rigged/animated/textured GLB + 4 unrigged OBJ, one `.appearance.json` per model that has a blob, and `export_report.json`. Everything is named `jc_NNNN_<Creature>` — see "Naming" below |
| `merged/` | demo output of `tools/merge_reference.py merge`: creatures that do not exist on the disc. A 0/25/50/75/100% sweep of 833 x 867, a three-parent blend, a texture swap plus 120-degree hue rotation, 907 as base gaining its body parts from 833, and Arpatron x Skawasp, the pair that turned up the offset bug below |
| `derived_experiment/` | five `jc_NNNN_<Creature>_derived.glb` built with a **synthesised** bone table for the models whose skeleton is not on the disc (870, 879, 893, 930, 841). An experiment to look at beside `current/`, not a replacement - the derivation recovers only 60-85% of parents on rigs we already have. See `docs/OVERLAYS.md` §7 |
| `archive/` | **not committed.** Four superseded export generations (v0.0_first15, v0.1, v0.2, v0.4_streamed) plus one-off scratch evidence. Each is regenerable by checking out the matching tag and re-running the pipeline; what was wrong with each is in `docs/FINDINGS.md` and the session log in `docs/START_HERE.md` |

## These were wrong until 2026-08-25

Every file in `merged/` before that date was built by a blend that wrote to the wrong
byte offsets: it treated a primitive as a run of 8-byte vectors starting at the chunk,
when the body actually starts 4 bytes in and the gouraud types stride 16 bytes per
vertex. Every vertex was blended four bytes early and the output was geometry belonging
to neither parent - recognisable in outline, shattered up close.

A blend is now checked by reducing it and the target parent to multisets of
`(bone, bone-local position)`: at 100% weight every vertex of the merge must exist in
the target. It does. Before the fix it was 23.5%. The account is in
`docs/MERGE_ALGORITHM.md` under "The merge export was blending the wrong bytes",
including the check that passed while the output was broken.

## Naming

A file is `jc_<discFile>_<Creature>.<ext>`: `jc_0845_Marrdreg.glb`, `jc_0855_Garai.glb`,
`jc_0903_Old_Woman.glb`. The disc file index stays in front because it is the model's real
identity — every note in `*.md` cites it, `export_report.json` is keyed by it, and
it keeps the folder in disc order.

The names come from `tools/model_names.py`, out of two tables on the disc: the species
table names the creatures, and the scene packages' actor records name the NPCs (see
`OVERLAYS.md` §2). **99 of the 106 files are named.** The other seven — 10, 197, 834,
849, 922, 923, 1072 — are named by neither table and keep the bare `jc_NNNN` stem.

Two caveats worth knowing before going looking for a bug:

- **Six files are all called Mahbu** (877-882). They really are six models of the same
  character; the file index is what tells them apart.
- **831 and 832 are both `Levant`** and are the one attribution not read from a table.
  Neither is named on the disc; 831's texture bank holds one character portrait plus the
  game's sword set and 832 holds that same portrait with 345 textures of alternate outfits,
  and they are the only two models whose animation records are 64 bytes rather than 60 —
  the two the game treats as the player. It is an inference, and it lives in `MANUAL` in
  `model_names.py` where one line overturns it.

The GLB's root node carries the same name, so loading ten models into one Blender scene no
longer gives ten objects called `JadeCocoonModel`. Action names still use the bare index
(`jc0845_anim02_36f`): they have to stay unique across models, and six Mahbus would not be.

## Reading `current/`

- `jc_NNNN_<Creature>.glb` — rigged, animated, textured. Vertices are in bind-pose space with real
  inverse-bind matrices, so edit mode shows an assembled creature; the Y-up flip is in the
  root joint. Actions are named `jcNNNN_animII_FFf`, or `jcNNNN_poseII_1f` for the
  single-frame pose blocks.
  Extra nodes appear when the model has them, all skinned to the same skeleton:
  `hidden_arms` / `hidden_wings` / `hidden_legs` hold bone groups the game does **not**
  draw (`partFlagsA[g] < 2`) but which a merge can switch back on, and `unclaimed` holds
  mesh objects no bone indexes — usually a detached prop. Hide them to see the creature as
  the game draws it.
- `jc_NNNN_<Creature>_static.obj` — geometry only, for the 4 models whose rig is not in the archive
  (10, 197, 1072 are too small for any table; 841 needs the missing 35-bone one).
- `merged/*.glb` — generated, not from the disc. Same rig, same 29 clips and same 1,576
  vertices as the base parent; only the vertex positions, normals, bone lengths, body-part
  flags and palette differ. See `MERGE_ALGORITHM.md` § "THE VISUAL MERGE, END TO END" §7.
- `jc_NNNN_<Creature>.appearance.json` — growth stages (global + per-bone scale), the arms/wings/legs
  part flags, the 43 attachment markers, the per-mesh blend weights, and the raw animation
  table. 94 models have one; only the 48 merge-family models carry stages and markers, the
  rest carry just the animation table.
- `export_report.json` — per model, keyed by disc file index: its `name` / `nameSource` /
  `stem`, which rig and animation source were chosen, whether the
  rest pose was borrowed from another file, the stitch-closure fit score, `hiddenParts`,
  `unclaimedMeshes`, `animTableCount`, `animSlots` / `animSlotsTotal` (how many streamed
  clips were exported out of how many exist), and per-animation `frames` / `maxRotDelta` /
  `maxRootMove` / `moves`.

Most animations come from the **streamed** per-animation sector table in the exe model
descriptor, not from the model's resident container; the two are disjoint and both are
exported. Only `831` and `832` are capped, at 48 clips of ~197 (`MAX_ANIMS` in
`export_every.py`), and `animSlotsTotal` records what was left behind.


**No model borrows another file's rest pose.** Every rigged model runs its own animation
data. **Five are still wrong**, though: `jc_0870_Kikinak`, `jc_0879_Mahbu`, `jc_0893_Poacher`
and `jc_0930_Dream_Man` run their own
clips on a rig that is too short, so the first N bones land correctly and everything past N
hangs off in space; `jc_0841_Cushidra` has no rig at all. Their real tables (26, 24 and 35 bones) are
not on the disc. `jc_0840_Seterian` is rigged from `836`'s 40-bone table, the only one there is. See `docs/OVERLAYS.md` for how a model gets a skeleton and
`docs/RIG_ATTRIBUTION.md` for the triage history.

To regenerate: see "Rebuilding from scratch" in `docs/START_HERE.md`.
