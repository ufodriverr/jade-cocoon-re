# Jade Cocoon RE - start here

Read this first, then `FINDINGS.md` for the full ledger.

Game: **Jade Cocoon: Story of the Tamamayu**, PS1, Europe, `SLES-02201`.
Goal: document the file formats and game mechanics, convert the assets to modern
formats, and eventually reimplement the merge system with original code.

Everything here was worked out from a legally owned disc. The tools read *your* copy;
none of them download anything. See `../NOTICE.md`.

## Where things are

| what | where |
|------|-------|
| your disc image (bin/cue) | wherever you dumped it. Every tool takes the path as an argument |
| extracted exe + archive | `extracted/` (gitignored, you generate it) |
| split archive sub-files | `extracted/DATA001_split/NNNN_<offset>.bin` |
| exported models | `models/current/` - see its `README.md` for the layout |
| extracted textures (PNG) | `extracted/Textures_All/` |
| Ghidra project | `ghidra/JadeCocoon`, program `/psx/SLES_022.01` (gitignored, you generate it) |
| decompiled C | `notes/decomp*/` (gitignored, regenerate with the scripts below) |
| tools | `tools/` (all Python, no dependencies) |

### Exported models layout

`models/` is the export target. A prebuilt copy is committed; re-running the pipeline
below overwrites it in place.

| folder | what |
|--------|------|
| `current/` | the live export: 102 rigged GLB + 4 `*_static.obj`, one `.appearance.json` per model, `export_report.json`. Files are named `jc_NNNN_<Creature>.glb` - see `model_names.py`. **Every rigged model uses its own animation data; none borrows a rest pose** |
| `merged/` | demo output of `merge_reference.py merge`: creatures that do not exist on the disc |
| `derived_experiment/` | five models rebuilt on a synthesised skeleton. An experiment, not a replacement. See `OVERLAYS.md` §7 |

Earlier export generations (`v0.0_first15`, `v0.1`, `v0.2`, `v0.4_streamed`) are not
committed. They were each superseded and are regenerable by checking out the matching
tag and re-running the pipeline; `FINDINGS.md` and the session log below record what
was wrong with each.

**What is not in this repo:** the disc image, the Ghidra project (it contains the game's
code), and raw decompiler output (a mechanical translation of Genki's code). Regenerate
the last two with the scripts below. Everything they taught us is written up in these
docs in our own words.

## Rebuilding from scratch

```bash
cd tools
python iso_ls.py "<path>/....bin" --json ../docs/iso_filelist.json
python iso_extract.py "<path>/....bin" ../docs/iso_filelist.json ../extracted SLES DATA.001
python split_data001.py ../extracted/SLES_022.01 ../extracted/DATA/DATA.001 ../extracted/DATA001_split
python build_index.py ../extracted/SLES_022.01 ../extracted/DATA001_split ../extracted/rig_anim_index.json
python model_anims.py ../extracted/SLES_022.01 ../extracted/DATA001_split   # optional: list streamed clips
python model_names.py ../extracted/SLES_022.01 ../extracted/DATA001_split ../extracted/model_names.json
python export_every.py ../extracted/SLES_022.01 ../extracted/DATA001_split ../models/current
```
(`export_all.py` is the older 16-model path driven off the exe descriptor table;
`export_every.py` covers the whole 106-file census.)

Ghidra headless (the decompiled C is regenerated, never committed):
```bash
analyzeHeadless <proj> JadeCocoon/psx -process SLES_022.01 -noanalysis \
  -scriptPath tools/GhidraScripts -postScript DecompFuncs.java <outDir> 0xADDR ...
```
Ghidra 12.1.3 with `ghidra_psx_ldr` (built for 12.1.2; bump `extension.properties` to
install). PSYQ signatures name 1532 of 1989 functions.

## What is solved

- **Archive**: DATA.001 file table lives in the exe at `0x800759C4`, 1108 entries, positions
  stored as BCD CD timecodes. Offset = `(LBA - 392) * 2048`.
- **Textures**: stock Sony TIM. Watch for shared CLUTs (`bnum == 12` = palette lives at that
  VRAM slot, uploaded by another texture).
- **Models**: **files 831-933** (plus 10, 197, 1072) — 106 files, 104 distinct meshes. The
  exe descriptor table at `0x800823F0` names **all 103** of them, with the sector range of
  every section AND a per-animation streamed sector table (see `MODEL_FORMAT.md`). Mesh is a
  sequential tagged chunk stream; chunk types 8/9 are the per-bone seam vertex pool.
- **Skeleton**: bone table = 8-byte records terminated by -1. **Parent is implied by DEPTH**,
  not the byte at +3 (that byte lies for bone16 of the 25-bone rig). A skeleton is never named
  by a model — the spawning code passes it as a **literal pointer**, and every scene package
  ships its own copy of the one 22-bone humanoid table. See `OVERLAYS.md`.
- **Animation**: `{u32 frames, u32 bones, restOffset[bones][3], keys}`, header `8 + bones*6`.
  Each frame has two entries before the bones: locomotion displacement, and the animated
  root translation that drives **bone 1** (not its static rest offset).
- **Export**: **106 of 106** — 102 rigged, animated, textured GLB (all pass `check_glb.py`)
  plus 4 unrigged OBJ, and **not one of them borrows another model's animations**. Hidden body-part groups and mesh objects no bone
  claims ride along as separate nodes (`hidden_arms`, `unclaimed`). Vertices are baked into bind-pose space with real
  inverse-bind matrices, seam strips carry their UVs, the Y-up flip lives in the root joint,
  and rigs/rest poses are chosen by a stitch-closure fit score (`rigfit.py`), not by bone
  count. Each file is named after its creature (`jc_0845_Marrdreg.glb`), and the GLB's root
  node carries the same name so a Blender scene with ten models loaded is readable.
  `export_report.json` records the name and its source, the rig, animation source, borrow
  flag, fit score and a per-animation `moves` flag for every model.
- **Animations**: **2474 streamed blocks** over the 103 models, plus 548 in the resident
  containers — the two sets are disjoint. Most models keep most of their animations in the
  per-animation sector table in the exe descriptor and stream them one clip at a time
  (`FUN_800254A8`); a model whose resident range is one all-zero sector is not animation-less.
  Everything with 3+ frames animates; single-frame blocks are **poses** (`poseNN_1f`).
- **Merge (stats)**: base keeps its body; skills live in a 0x30-byte slot array grouped into
  elemental families of five; special evolution triggers on skill accumulation with level
  choosing the form; experience merges in double-precision float.
- **Merge (mesh) — SOLVED**: `FUN_80010DB0` blends up to three parents **per vertex**,
  `dst = lerp(dst, src, w)` over every primitive and both seam pools, normals included. It
  works because **49 models share one exact topology** — the mergeable minion morph family.
  Skeleton, 43 attachment markers and body-part flags blend alongside; the result is
  re-seated on the ground via marker id 0x26. See `MERGE_ALGORITHM.md`.
- **Merge (the whole visual chain) — SOLVED**: the job is an asynchronous five-state pump
  (`FUN_80010AD8`); its 0x34-byte recipe is `memcpy`d in by `FUN_80010850` and built in the
  overlays by `FUN_800BF208`. The recipe is the **48-slot ancestry list at minion +0x4C**:
  the three most common ancestor species, weighted by multiplicity. The texture is
  **selected, not blended** — one parent's texture section, loaded whole, with its
  **palette hue-rotated** by an angle derived from the four element tallies at +0xC2.
  Full chain in `MERGE_ALGORITHM.md` § "THE VISUAL MERGE, END TO END".
- **Names — SOLVED**: every species' English name is a `char*` in the exe at
  `0x8007A094` (209 entries, species id 0..208), stored as Shift-JIS **full-width Latin**
  — which is why searching the disc for ASCII names finds nothing. File 114 is the
  Japanese katakana roster, 153 names, indexed as `200 - i` then `353 - i`.
- **Model file -> name — SOLVED**: species names cover the creatures; the **NPCs are named
  by the scene packages**. Every `ActorInfo` in files 199-470 starts with a `char*` to the
  actor's name, immediately followed by the `modelId` already documented in `OVERLAYS.md`
  §2, so Garai, Mahbu, Kelmar, Lui and 40 more attach to a model file. The two tables agree
  wherever they overlap. **99 of the 106 model files are named**; `tools/model_names.py`
  resolves them and `export_every.py` names its output `jc_NNNN_<Creature>.glb`.
- **Species -> model file — SOLVED**: the species table is at `0x8007BC54`,
  `{u16 modelId; u8 hueBase; u8 hueRef}`, 365 entries with ids 0-210 the usable roster
  (36 base creatures, 21 specials, 144 elemental variants at `57 + base*4 + element`, 10
  uniques). Dumped to `extracted/species_index.txt` by
  `tools/merge_reference.py species`.
- **Appearance blob** (`MODEL+0x4C`, package section 0): five growth stages (global scale
  0.40 -> 1.00 plus per-bone scales that give babies big heads), three body-part flags
  (arms / wings / legs = bone masks at `0x80072F60/64/68`), 43 markers, per-mesh blend
  weights. Parser `tools/appearance.py`; exported as `jc_NNNN_<Creature>.appearance.json`.

Full detail in `MODEL_FORMAT.md` and `MERGE_ALGORITHM.md`. `OVERLAYS.md` covers overlay
loading, the actor spawn descriptor, and how a model gets a skeleton and an animation set.
`RIG_ATTRIBUTION.md` triages the 18 models a Blender review flagged; its diagnosis is
superseded by `OVERLAYS.md` but its metric caveats still hold. `FINDINGS.md` marks every
entry CONFIRMED or HYPOTHESIS.

## Open threads, roughly by value

0. **AGE / GROWTH — the next thread.** Every creature grows baby -> adult with level.
   Much of it is already decoded and collected in `MERGE_ALGORITHM.md` §12: the level ->
   stage thresholds (`1, 7, 13, 22, 27` at `0x8007C208`), five `Stage` records per model
   with global and per-bone scale, the fact that babies are re-proportioned rather than
   just smaller, that six models change body-part flags as they age (856 loses its wings),
   that the flag value `0` means "hidden AND never grantable by merge" while `1` means
   "hidden but grantable", and the draw-time scale chain. **Open:** who drives the growth
   ramp (`actor[0x28]`/`[0x2A]`), whether anything but the body is stage-keyed, and where
   experience becomes level `+0xC8`.
0b. **The five models whose skeleton is not on the disc** — `870` and `879` (26 bones),
   `893` and `930` (24), `841` (35), plus `840` wearing **836's** 40-bone table. Their own
   clips now drive them, which places the first N bones correctly and strands everything
   past N — a Blender review reads it as "partially in the right place". No table of those
   sizes exists (raw-archive scan, gaps included) and **deriving one from the stitch graph is
   not good enough**: on rigs we already have it recovers 17/25, 21/25, 18/22 and 9/40
   parents. The remaining leads are code, not data — find the routine that draws these five,
   since neither the field-NPC nor the battle-enemy path could be passing their rig. 840 is
   the cheapest way in: its streamed set holds a **41-bone** clip beside the 40-bone ones.
   Detail in `OVERLAYS.md` §7; derived variants in `models/derived_experiment/`,
   reviewed in Blender as "better than the short rigs, still wrong" - the objective is the
   bottleneck, not the search width. **Parked by the user 2026-08-25**; the export ships the
   short-rig version.
1. ~~Who fills the MergeJob~~ — **CLOSED 2026-08-25.** The recipe is `memcpy`d into the job
   by `FUN_80010850` and built by `FUN_800BF208` in overlay 44 (and its copies in overlays
   28 and 36) out of the minion's 48-slot ancestry list. `MERGE_ALGORITHM.md` §2.
2. ~~The texture side of a merge~~ — **CLOSED 2026-08-25.** Selected, not blended: one
   model's whole texture section, with its CLUT hue-rotated by an element-derived angle.
   `MERGE_ALGORITHM.md` §5.
3. ~~Which species maps to which model file~~ — **CLOSED 2026-08-25.** Species table at
   `0x8007BC54`, and **every species' name is in the exe** at `0x8007A094` (209 of them,
   Shift-JIS full-width Latin). `MERGE_ALGORITHM.md` §3 and §9; the generated table is
   `extracted/species_index.txt`.
   *Still open on this thread*: tying the 153 **names** in file 114 to species ids. The
   species side is now solved; the name side is not.
4. **The second species table** at ids 211-364 — the same 154 models as ids 57-210 with
   different hue pairs, and no accessor found. Whatever reads it probably also decides a
   creature's appearance id (minion +0x03), which is what picks the merged texture, and
   `FUN_800BA198`'s untraced `param_4` is the other half of the same question.
5. **The last 4 unrigged models** — 10, 197, 1072 (2, 4 and 5 mesh objects: too small for
   any table) and 841 (35). Folded into thread 0; the rig index is archive-wide
   (`extracted/rig_anim_index.json`, 244 tables / 11 distinct bone counts, confirmed against
   a scan of the raw 211 MB DATA.001). *Corrected: files 831/832 do NOT contain zero
   animation blocks — they hold five resident and ~200 streamed each, and their own rest
   pose. The old claim came from the animation-block flag bug.*
6. **GR matrix index order** — which index is Water/Fire/Earth/Wind. Battle relations are
   known from the game's own text (Water vs Wind, Fire vs Earth); the merge matrix is a
   different relation and its index order is unmapped. New lead: the element index maps
   onto the roster's name prefixes (0 = Pata, 1 = Sk, 2 = Ter, 3 = Rad), so if `テラ` is
   *terra* then index 2 is Earth — plausible, unproven.
7. **The affinity blend seed** (`v0 | 0x2493`) — constant, counter or RNG, untraced.
   *(Minion names are done: `MERGE_ALGORITHM.md` §9.)*
8. **Is every party minion built through the merge job?** The palette rotation only
   happens on that path, and no ordinary spawn path reads a species' palette angle, so a
   wild Pataraid and a wild Terfrayd would otherwise look identical. One breakpoint on
   `FUN_80010850` settles it. `MERGE_ALGORITHM.md` §11.
9. **Save format** — the memcard saves parse, but the packed minion layout inside them is
   not mapped to the 0xF8 runtime struct. *(The old note here said the EU build encodes
   text as font byte indices. It does not: game text is Shift-JIS, with Latin stored as
   full-width forms. Whatever a save holds is a separate question.)*

## Recreating the merge (Blender / Unity)

Everything needed is exported and documented:

- The 49 morph-family files share vertex order **on disc**. The exported GLBs do **not** —
  hidden body-part groups become separate primitives, so members export as 3, 4 or 6
  primitives and cannot be dropped in as each other's shape keys. Blend at the archive
  level instead: `tools/merge_reference.py merge` does exactly that and writes a merged
  GLB. Demo output in `models/merged/`.
- `jc_NNNN_<Creature>.appearance.json` per model: five growth stages (global + per-bone scale), the
  arms/wings/legs flags, the 43 attachment markers, and the per-mesh blend weights the game
  uses to weight the blend per body region.
- **Interactive:** `tools/merge_studio.py` serves a local page that lists every creature
  by name, blends any two live on a slider with animation, palette rotation, the
  body-part rule and an **age slider** (level 1-40 -> growth stage -> the whole-body and
  per-bone scale ladders, so a hatchling really is head-heavy and stubby), and exports the
  result as a GLB.
  ```bash
  cd tools
  python merge_studio.py ../extracted/SLES_022.01 ../extracted/DATA001_split
  # open http://127.0.0.1:8765/   (--open launches a browser for you)
  ```
- The blend rule is `dst = lerp(dst, src, w)` per vertex AND per normal, plus the rest-offset
  lerp for the skeleton, plus the part-flag OR rule, plus re-grounding on marker id 0x26.
  All of it is in `MERGE_ALGORITHM.md` under "THE MESH MERGE".
- The weights are not free parameters: they are the three most common species in the
  creature's 48-slot ancestry, divided by 48. The texture is one parent's, hue-rotated.
  `MERGE_ALGORITHM.md` § "THE VISUAL MERGE, END TO END" has both rules and
  `tools/merge_reference.py` implements them.

## Things that will bite you again

- Offset-table thinking. The mesh has **no** offset tables; it is a sequential chunk stream.
  Three offset-based hypotheses were tested and disproven (documented in `MODEL_FORMAT.md`)
  before the sequential decoder was found in `FUN_8002188c`.
- Gouraud vertex blocks store the **normal first, position at +8**. Reading +0 gives values
  clamped near 4096 (unit normals) that look like broken geometry.
- Bone parenting: use depth, never the byte at +3.
- "No morph data on disc" did NOT mean "no morphing" — that was settled the hard way. The
  morphing is real, it just needs no stored targets: 49 models share one topology, so any
  two of them are already each other's morph targets. Anything combinatorial is generated at
  runtime and only its recipe stored.
- The merge blend and the growth stages both live in the **main exe**, not in the merge
  overlay. Overlay 44 does the stats; `FUN_80010DB0` does the geometry.
- When regex-scanning for fixed-stride records, use a **zero-width lookahead**. A consuming
  match eats the window and hides a valid table start a couple of bytes later — that quietly
  returned "0 rigs" from a scan that should have found 244.
- Don't match a rig to a model by bone count: mesh-object count and bone count differ (831
  has 23 meshes on a 22-bone rig). Score candidates with `rigfit.py` instead, and never
  borrow a rest pose from outside the creature region.
- A validator that shares an assumption with the thing it validates proves nothing:
  `check_glb.py` skipped the inverse bind matrices because they used to be identity.
- Don't put a coordinate-system flip on a wrapper node above a skinned mesh. Blender applies
  the object transform on top of already-baked vertices and the model shows up upside down in
  edit mode. Fold it into the root joint (bind pose AND every animation frame).
- `FINDINGS.md` has mixed encodings from earlier writes — open it with
  `encoding='utf-8', errors='surrogateescape'` when editing programmatically.
- **A hard-coded loop bound is not a fact about the data.** `model_index.NPTR = 16` is the
  entire reason four documents said "the exe descriptor table only names 16 models". It has
  103 entries. Before writing down what a table contains, walk it to its terminator.
- **A struct field with a flag bit in it looks like corruption.** Bit 31 of the animation
  block's boneCount made it read as 2147483670, the validator rejected the block, and six
  models were recorded as owning no animations at all. When a field is wildly out of range
  in a small minority of records, suspect a flag before suspecting the parser's offset.
- **A better fit score is not a correct model.** `rigfit` measures whether seams close.
  A derived 25-bone rig for model 867 scores **44** where its real table scores **51**, while
  getting 4 of 25 parents wrong. Never promote a synthesised rig on score alone; the only
  reliable check is a human looking at it in Blender.
- **Text you cannot find may just be encoded differently.** Two sweeps for ASCII minion
  names across the 211 MB archive found nothing, and the conclusion "the EU build has no
  name strings" was wrong: the game stores Latin text as Shift-JIS **full-width** forms,
  so `Carmine` is `82 62 82 81 82 92 …`. Search for both encodings before concluding
  something is not there.
- **A field name written down from a plausible reading is a guess until a consumer confirms
  it.** The model descriptor's section list was recorded as `(size, cumulativeEnd)` pairs
  and is really `(start, size)` pairs - the same numbers, paired one word apart. Nothing
  broke, because every tool was self-consistent; the error only surfaced when the loader
  was read. Likewise `MergeJob+0x34` was a "dirCount" that is actually a pointer.
- **A function with no `jal` to it can still be live.** The whole merge job pump
  (`FUN_80010AD8` and its four handlers) is reached only through a jump table, so Ghidra
  had created no function for any of it and `getFunctionContaining` returned NONE for a
  perfectly ordinary block of code. `tools/GhidraScripts/MakeAndDecomp.java` disassembles a
  range, creates a function at every `addiu sp,sp,-X` prologue, and decompiles the lot.
- **Two counts with the same name are not the same count.** `MeshBlock+0x04` was documented
  as `boneCount`; it is the **mesh object count** (equal for all 106 models), and the rig it
  implies is often shorter. Likewise a clip's `boneCount` is the clip's stride, not the rig's.
- **A resource being absent from where you looked is not evidence it is absent.**
  `build_index.anim_containers` only probes `sector * 2048`, and the whole streamed animation
  library sits in sectors nothing pointed at until the exe descriptor was read to the end.
  Two sessions concluded "these models ship no animations" from that.
- Scene/actor packages (files ~111-113, 199-470) are overlays too, loaded at `0x800B248C`.
  They hold code, dialogue, their own rig copies and their actor records. `OVERLAYS.md` has
  the method for pinning down an overlay's load address from the image alone.

## Session log

- **v0.1** (`v0.1-mesh-merge`, commit `d85b688`) — mesh merge solved, first full 106-model
  export. Known-bad: bone-local vertex positions, untextured seams, rigs matched by bone
  count. Output kept at `models/archive/v0.1/` for comparison.
- **v0.2** (`v0.2-exports`) — seam UVs, bind-pose bake, fit-scored rig attribution, root-joint
  Y-up flip, model-id-prefixed animation names, `export_report.json`. Kept at
  `models/archive/v0.2/`.
- **v0.3** — triage of a Blender review (`RIG_ATTRIBUTION.md`). Lenient appearance-blob
  parse (48 → 103 models), body-part flags applied, 32 dropped mesh objects recovered,
  849/884/902 re-attributed, 94 rigged / 12 static. 13 of 18 reported models still wrong.
- **v0.4** — open thread 0 run down (`OVERLAYS.md`). Overlay load addresses and the
  `SpawnDesc` struct mapped; rig selection turns out to be a hard-coded pointer with a
  package-local default, and there is exactly one 22-bone humanoid skeleton (149 copies).
  Two flag bits recovered in the animation block header, and the exe descriptor table turns
  out to be 103 entries carrying a **per-animation streamed sector table** — 2474 animation
  blocks, the missing frame stream, and a per-model rest pose for every humanoid NPC.
  **102 rigged / 4 static, 4 borrowers** (was 94 / 12 and 34), median fit 52.7 → 47.4.
- **v0.7** — names and a live tool. Every species' English name found in the exe
  (`0x8007A094`, 209 entries, Shift-JIS full-width Latin), cross-checked 209/209 against
  the community roster, whose hex IDs turn out to be the game's own species ids; file 114
  decoded as the 153-name Japanese roster at a reversed index. The five rig-less models
  got names, and 893 turned out to be the **Poacher**, a human. `tools/merge_studio.py`
  is a local web app that blends any two creatures live, animated, with the palette
  rotation in the shader, and exports GLBs.
- **v0.6** — the visual merge end to end (`MERGE_ALGORITHM.md` § "THE VISUAL MERGE, END TO
  END"). Open threads 1, 2 and 3 closed: the merge job is a five-state pump whose recipe is
  the minion's 48-slot **ancestry list**; the texture is **selected and hue-rotated**, not
  blended; and the **species table at `0x8007BC54`** maps every species id to a model file.
  `merge_reference.py` gained the whole visual side and can write a merged GLB
  (`models/merged/`). The 49-model topology claim was re-verified against the
  archive bytes (48 of 49 also share a seam table; 850 does not) and the export was checked
  and found **not** vertex-order identical.
- **v0.5** — `FUN_80047E4C` reads: the renderer walks the **rig** and indexes the clip by each
  record's `self` byte at the **clip's** stride, so rig length and clip length are independent
  as long as the clip is the longer one. Allowing that for a model's own clips gave 870, 879,
  893 and 930 their own animations (fit 95→55, 81→43, 90→52, 104→85). **102 rigged / 4 static
  and zero borrowed rest poses**, median fit 46.4. A Blender review of those four says
  "partially in the right place" — better, not fixed; the short rig strands every mesh object
  past its last bone. Deriving the missing tables was tried and rejected (`OVERLAYS.md` §7).
