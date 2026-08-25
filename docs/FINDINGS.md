# Jade Cocoon RE — Findings Ledger

Rules: every entry is **CONFIRMED** (verified in binary/memory/disc) or **HYPOTHESIS**
(untested claim, incl. anything from the community wiki). Move entries up as they get verified.
Date each entry.

---

## Disc / executable

**CONFIRMED (2026-08-24):**
- Version: Europe, volume ID `SLES-02201`, single data track MODE2/2352 bin/cue.
- Boot: `BOOT = cdrom:\SLES_022.01;1`, `STACK = 801FFF00` (SYSTEM.CNF).
- `SLES_022.01`: PS-X EXE, 765,952 B on disc.
  - Entry point: `0x8001047C`
  - Load address (t_addr): `0x80010000`
  - Code+data size (t_size): `0x000BA800` (764,928 B)
  - So the exe occupies `0x80010000..0x800CA800` in RAM; everything above is heap/loaded data.
- Full ISO file list: only 30 files. All game data lives in `DATA/DATA.001` (211,658,752 B).
  `DATA/VOICE.XA` (88.7 MB XA audio), rest are STR movies. See `iso_filelist.json` for LBAs.

## DATA.001 archive — FILE TABLE CRACKED

**CONFIRMED (2026-08-24):**
- No header at offset 0: first 0x1000 bytes are zero. First non-zero data at `0x1000`.
- **The file table lives in the exe at RAM `0x800759C4`: 1108 entries, 12 bytes each.**
  Verified: sector counts match `ceil(size/2048)` for ALL 1079 in-archive entries, and
  computed offsets land exactly on the known TIM at 0xB000 and the size-prefixed blob at
  0x1000 (entry 3, size 0x12F8 == first u32 of the blob).
  ```c
  struct FileEntry {          // table[1108] @ 0x800759C4 (exe file offset 0x661C4)
      /* +0 */ DslLOC pos;    // BCD MSF (minute, second, sector, track) - authoring-time
      /* +4 */ uint32 sectors;// read length in 2048-byte sectors == ceil(size/2048)
      /* +8 */ uint32 size;   // exact byte size of the sub-file
  };
  ```
- **Offset math**: archive_byte_offset = `(LBA(pos) - 392) * 2048`, where 392 is
  `LBA(entry[2].pos)` — the rebase reference the game reads from RAM `0x800759DC`.
  At runtime the game computes the real disc LBA as
  `LBA(DATA.001 start from DsSearchFile) + LBA(entry) - 392` (see FUN_80041a70).
- 29 entries fall outside DATA.001 (entry 0 = the exe itself at disc LBA 23; others TBD —
  likely VOICE.XA / MOVIE content addressed through the same table).
- Table end: RAM 0x80078DB4. Full decoded index: `data001_index.json`
  (idx, lba, offset, sectors, size, guessed type). Split output in
  `extracted/DATA001_split/` as `NNNN_<offset>.<ext>`.
- Sub-file type census (by magic at start): 1075 custom "bin", 4 bare TIM, 0 bare TMD.
  The 22 sector-aligned TIMs / 31 TMDs from the raw scan are NESTED inside containers.
- **Nested pack format confirmed** (e.g. entry 4 = `0004_00002800.bin`):
  `u32 count; u32 offsets[count];` — offsets ascending, first == 4 + count*4.
  (395 files look like this "tiny count" shape; 95 medium; 577 still unclassified; 3 are
  size-prefixed single blobs.)

**HYPOTHESIS:**
- Container sub-formats: the size-prefixed blob at 0x1000 has repeating 48-byte records
  with a constant `06 49 B2 2C 19 01 00 00` field — possibly mesh/primitive data.
- Community wiki: 48 merge slots, GR stat formula — unverified, treat as hypotheses.
- 2019 Randomizer (Meos) patches data successfully → data locations partially mapped;
  its patch offsets would be a shortcut worth mining if source/notes are public.

## Loading architecture (game code)

**CONFIRMED (2026-08-24):**
- The game uses **libds** (Ds* functions), not libcd directly, for data loading.
- `FUN_80010110` (called from main-init) → `DsInit`.
- `FUN_80041fc0`: loops `DsSearchFile("\DATA\DATA.001;1")` → stores DslFILE (pos+size+name)
  at `0x80095550`. String at `0x80074878`, pointer to it at `0x80086A34`.
- `FUN_80041a70(DslLOC *out, int fileIndex)`: **the table lookup** — reads entry
  `0x800759C4 + index*12`, rebases vs `0x80095550` and `0x800759DC`, returns pos and
  writes sector count to out[1].
- `FUN_80041e20(loc, buf, sectors)`: seek (`DsControl(0x15 /*CdlSeekL*/)`) + read loop.
- `FUN_80041ef8(loc, sectors, buf)`: blocking read = `DsRead(..., mode 0x80)` + `DsReadSync`
  retry loop; global `0x8008D608` bit 0x100 = abort flag.
- `FUN_80041d44(fileIndex)`: **load-to-heap** = table lookup + `FUN_8003e9e4(sectors<<11)`
  (allocator) + read. Returns buffer. Callers: FUN_80030ae0, FUN_80041d90.
- `FUN_80041de4(fileIndex)`: load into fixed buffer `0x801B9250` (scratch load area).
  Caller: FUN_8004241c.
- Movie player `FUN_80042b00(movieIndex)`: STR playback via CdRead-alike `FUN_8004fecc` +
  MDEC (DecDCTin/out). Movie metadata table at `0x80086B54`, 0x34-byte entries, first u32 =
  disc LBA of the STR (these LBAs are OUTSIDE the DATA.001 window — separate system).

## Ghidra setup

**CONFIRMED (2026-08-24):**
- Project: `ghidra/JadeCocoon`. Program `/psx/SLES_022.01` = the real one
  (PSX Executables Loader, language `PSX:LE:32`, ghidra_psx_ldr 2026.07.08 installed into
  Ghidra 12.1.3 with extension.properties version bumped from 12.1.2 — works fine).
  A `/SLES_022.01` at project root is an earlier raw-binary import; ignore or delete.
- PSYQ signatures matched 1532/1989 functions (list: `Notes/psx_named_functions.txt`).
  `main` identified at `0x80010000`. Game code ends ~`0x8004DD00`; PSYQ libs after.
- Headless automation works: scripts in `tools/GhidraScripts/`
  (FuncStats, CallersUp, DecompFuncs, CdCallers, PsxSetup). Decompiled C lands in
  `notes/decomp/<addr>_<name>.c`.

## Archive content map (file indices)

**CONFIRMED (2026-08-24):**
- Index space is regioned by content type. Known so far:
  - 9, 10: loaded at boot by FUN_8004241c into fixed buffer 0x801B9250.
  - 23-53: global resources; descriptor table `{u32 fileIdx, u32 destPtrPtr}` at RAM
    `0x8007D90C` (31 entries), loaded via FUN_80020c60 / async queue.
  - **111: main character actor package — strings "Mahbu", "Lui", "Dream Man", "DMYB".**
  - **112: "Poacher", "ZIRA"; 113: "Dream Man", "Patlchu".**
  - **114: MINION NAME TABLE — 153 contiguous Shift-JIS katakana names starting at +8**
    (タイトン, スバァス, ...; includes the merge-family series ラドマイン/テラマイン/
    スクマイン/カーマイン etc). Header id = 0x139. Data section at +0x3364.
  - 115-188 (74 files): small records, shared header shape `{+0 u32 8, ...,
    marker 0x0003D000}` — per-minion(?) data, ids all 0. Format TBD.
  - 199-470: "actor packages" — header `{u32 sectionOff, u32 actorId, SJIS name(s)}`,
    contain MIPS OVERLAY CODE (function prologues visible) + data. actorId increases
    monotonically with file index (0x2C..0x12D region).
  - 471-478, 556-597+: large files (0.3-2 MB), some start with signed fixed-point-looking
    pairs (FFFFFED5 FFFFF8B1) — model/animation data candidates.
  - 484-552: repeating triads of identical sizes (638976/733184/579584) x ~17 groups of 4 —
    field variants (levels/seasons?).
  - 768-810: sound banks (VAB head/body + up to 2 SEPs). Container: 8 u32 header =
    {vabHeadOff, vabHeadSize, vabBodyOff, vabBodySize, sepOff, sepSize, sep2Off, sep2Size}
    (per FUN_80030ae0 = SOUND.C loader). Sound bank map table at RAM `0x80082E30`,
    8 B/entry: {s16 fileIdx, u8[4], s16} indexed by bankId (FUN_80030da8).
  - 833-864: field/arena packages with embedded standard TMD models (~330 KB each).
  - 1081 (0x439): referenced by XA/streaming code FUN_80040c98.
- **Genki source filenames survive in asserts: "SOUND.C" seen. Others likely findable.**
- Async load queue: FUN_80040f28 queues 0x28-byte requests (head 0x80095D38, list globals
  0x80086A04-10); request = {mode, fileIdx, 0, 0, dest, cbSrc, cbLen, extra}.

## Merge algorithm — CORE DECODED

**CONFIRMED (2026-08-24):** Located in the **merge UI overlay = file index 44**
(`\DATA\DATA.001` sub-file `0044`, loads to RAM `0x800B6ED0`, prev-loaded region ptr
`0x80073130`). String evidence: "Shall I merge them?", "Pick the cocoon to be the base",
"To increase HP/Mana, merge minions so...". Overlay decompiled to `notes/decomp_ovl44/`
(129 funcs). The base+material merge is `FUN_800BA198(base*, material*, out*, ...)`.

### Minion struct (0xF8 = 248 bytes) — offsets confirmed from merge code
```c
struct Minion {              // copied wholesale by FUN_800ba198: memcpy(out, base, 0xF8)
  /* +0x00 */ s16 species;               // *param==3 special-cased; == kind/id
  /* +0x03 */ u8  paletteOrType;         // overwritten from FUN_8001cdc0(param_4)
  /* +0x04 */ struct{...} growthParams[6]; // 6 x 12B blocks, blended via FUN_80019af4
  /* +0x10 */ ...                         // second 6x set (base stat vectors)
  /* +0x4C */ u8  slots[0x30];   // <<< THE 48 SLOTS. merged by FUN_800bad08: out.slots[i]
                                 //     = (i<0x20 && i*2<0x30) ? base.slots[i] : material.slots[i]
                                 //     i.e. first 24 from base, rest from material, then blended
  /* +0x58 */ ...                // FUN_800ba598: per-6 affinity blend via FUN_800ba63c
  /* +0x61 */ u8  elemCount[4]?  // counted for the 7<x "power" flags -> +0x126
  /* +0x7C */ u8                 // paired with +0xC6 in FUN_800ba8fc
  /* +0x88 */ s32 exp/mana?      // FUN_800ba8a0: out.f88 += FUN_80012204(base,material...)
  /* +0x94 */ struct{...}        // 12B vector, blended
  /* +0xA4 */ s8  elemAffinity[?]// FUN_800ba69c: avg then GR-matrix transform (see below)
  /* +0xB0 */ u8  stats[6];      // FUN_800ba538: out=base.stat - base[+0xb6]/20 (down);
                                 //   FUN_800ba820: out=base.stat + base[+0xb6]/20 (up, cap 100)
  /* +0xB6 */ u8                 // divisor-20 modifier for the +0xB0 stats
  /* +0xC2 */ u8  elemLevels[4]  // 4 elements; +0xc2..+0xc5 (Water/Fire/Earth/Wind order TBD)
  /* +0xC6 */ u8
  /* +0xC8 */ u8  (200 dec)      // copied in FUN_800ba8a0
  /* +0x126*/ u8  powerFlags     // bit set per element whose level > 7 (bits 1,2,4,8)
};
```

### GR / element-affinity transform (the wiki "GR formula")
`FUN_800ba69c` recomputes the 4 element affinities (+0xA4) as a **matrix multiply of the
4 element counts (+0xC2) by a fixed 4x4 weight matrix, then >>5 (divide by 32)**:
```
weights @ 0x8007B998 (s8[4][4]):   affinity[j] = (sum_i count[i]*W[i][j]) >> 5
  32 16 32 64      // diagonal 32 = self, 64 = opposite/strong, 16 = weak
  64 32 16 32
  32 64 32 16
  16 32 64 32
```
(Before the matrix pass, each pair is pre-averaged: `(a + 2*b)/3` when material>base, per
element index; see FUN_800ba69c head.)

### Per-stat "bonus" blend (FUN_800ba63c) - exact
```
result = (p1 + p2)/2 + ( ((p1 + p2 - 200) * K) >>hi32 + (p1+p2-200) ) >> 2   (K = seed|0x2493)
clamped to [0, 200]
```
This is a fixed-point weighted average that pulls two 0..200 stats toward their mean with a
correction term. Raw asm saved (0x800BA63C). The `|0x2493` seed is a per-merge value in v0.

### Slot inheritance detail (FUN_800bad08 + FUN_800babdc)
- 0x30-byte `slots[]` (+0x4C): first block from base, remainder from material (the classic
  "keep base's first moves, gain material's"). Then bit-mask cleanup in FUN_800babdc using
  helpers FUN_8001ae2c (test bit), FUN_8001ad30 (map), FUN_8001ae00 (clear bit) over 0x1E
  (=30) indices, plus 4 special slot indices {0x15,0x16,0x17,0x18} gated on bytes +0xC2..+0xC5.
- So the "48 slots" is really a **0x30-byte capability bitfield/list**, 30 primary entries
  + element extras. Needs the slot->skill name map (likely the 74 files 115-188, or a table).

**HYPOTHESIS / TODO:**
- Confirm element order at +0xC2 and slot semantics against in-game merges (save-state diff).
- FUN_800ba8fc does a big unaligned 3-byte-field copy over +0xDE..+0xF1 region: appearance /
  body-part composition (the visual merge). This is the model-assembly side — high value for
  the model-conversion goal.
- Seed source for FUN_800ba63c (|0x2493): find who sets v0 before the call (RNG or a counter).

## Minion packages (files 934-1080)

**CONFIRMED (2026-08-24):**
- 150 files use a **6-section container**: header `{u32 count=6; u32 sectionOff[6]}`,
  `sectionOff[0]==0x1C` (right after header). 147 of them are in indices **934-1080**,
  matching the 153-name roster in file 114. These are per-minion (and some creature/field)
  packages.
- Section layout (consistent):
  - **s0 @0x1C, fixed 204 bytes**: base data. Real stat/index data for tameable minions
    (e.g. file 970 holds an ascending u16 index list 0x3D..0x4E); all-0xFF for
    field/boss geometry files (934/940/943). First u32 always 0xC8 (200).
  - **s1**: small; first u32 = N (part/bone count, e.g. 0xB-0xE).
  - **s2**: medium geometry table (first u32 = a count).
  - **s3**: ~12180 B block in many (animation?).
  - **s4**: 4-byte marker (0).
  - **s5**: largest; first u32 = same N as s1 → N-entry data (parts/TIMs/anim).
- Standard TMD magic is NOT used for minion geometry (custom format). Only field/arena
  packages (833-864) and one stray (943) contain bare TMDs. The minion model interior
  (vertex/primitive/rig decode) is the next sub-project — best validated against runtime
  VRAM in PCSX-Redux, not pure static analysis.

## Textures — SOLVED (see MODEL_FORMAT.md)

**CONFIRMED (2026-08-24):** The game uses **stock Sony TIM** images, embedded at arbitrary
offsets inside package files (NOT only at sector boundaries — that is why the first scan
found only 22). Format re-derived and then verified field-by-field against the game's own
parser `FUN_80029770`.
- **3302 textures extracted from 751 archive files** → `extracted/Textures_All/` + manifest.
- Package's **last section = the texture set**, one TIM per model part.
- Load path: `FUN_80028edc` → `FUN_80028f54` (section walker) → `FUN_80029770` (parse) →
  `FUN_80029708` (LoadImage to VRAM) → `FUN_80029914`/`FUN_80029a78` (tpage descriptors).
- Art location: **831/832 = character-NPC texture banks** (832 has 345 textures),
  934-1080 = environment/effects, 0-99 = UI/fonts, 600-849 = densest art region.
- Tools: `tools/tim.py`, `tools/extract_textures.py`.

## 3D renderer / model format (see MODEL_FORMAT.md)

**CONFIRMED (2026-08-24):**
- Renderer lives at exe `0x80044000`-`0x8004DD00` (24 funcs, decompiled to
  `notes/decomp_render/`). Custom **skeletal** system, not TMD.
- **4096-entry sine LUT at `0x80084464`** (`angle & 0xFFF`; cosine = same table `+0x400`).
- Animation keyframes = 6-byte (3x s16) vectors, indexed
  `keyArray[(frame*(boneCount+2) + bone + 2)*6]`; holder has boneCount at +4, array at +0x18.
- Polygon emitters: `FUN_80045a08` (0x3C POLY_GT4), `FUN_8004c240` (0x2C POLY_FT4),
  `FUN_8004bfcc` (0x24 POLY_FT3).
- **Runtime primitive = 56 bytes**, vertices INLINE (no index buffer):
  color +0x00, normal +0x10, v0/v1/v2 +0x18 (SVECTOR x3), v3 +0x30, uv/tpage in spare bytes.

- **Model location SOLVED:** descriptor table at `PTR_DAT_800823F0` (16 pointers); each
  descriptor's first u16 is the **DATA.001 file index → files 833-848 are the model files**,
  followed by (sizeInSectors, cumulativeOffset) pairs for the sub-resources.
  File 833: sectors 3-20 = TIM textures, 20-37 = mesh block, 37-61 = animations.
- **ANIMATIONS SOLVED + VERIFIED:** `{u32 frameCount; u32 boneCount; 150B header;
  s16 keys[frames][bones+2][3]}`, total `158 + frames*(bones+2)*6` padded to 4.
  All 8 blocks in file 833 tile with ZERO gaps against the container's own offsets.
  Rotations use the sine LUT's 4096-per-turn units (1024 = 90 deg). Tool: `tools/anim.py`.
- Runtime object graph confirmed: actor+0x15C → MODEL(0x70); MODEL+0x38 id, +0x3A refcount,
  +0x50 mesh array (indexed `+ meshIdx*0x54`), +0x54 anim descriptors (0x1C each),
  +0x5C extra. Resource mgmt: FUN_80024b44 (alloc count*0x70), FUN_80024dd8 (get by id),
  FUN_80026734 (init), FUN_80026668 (count 16-byte directory entries, 0xFFFF-terminated).

- **MESH GEOMETRY SOLVED (2026-08-24):** the on-disc mesh is a **sequential tagged chunk
  stream**, which is why every offset-table hypothesis failed. Decoder chain:
  `FUN_8002188c` (skip 0x10 hdr, meshCount at +4, loop objects) → `FUN_800224c0`
  (0x28 count header + chunk walk) → jump table at `0x8007DA04` (8 handlers, one per PS1
  polygon type; textured types 2/3/6/7 alone have callbacks at `0x8007DA2C`).
  Chunk = `{u8 type, u8, u8, u8 flags, body}`; body sizes and vertex layouts in
  MODEL_FORMAT.md. Gouraud vertex blocks store the NORMAL first and the POSITION at +8.
  **Verified: 15/15 model files parse with the walk landing byte-exactly on the header's
  end-offset field.** Exported to OBJ in `models/archive/scratch/` — renders as recognizable
  horned/antlered creatures. Tools: `mesh.py`, `export_mesh.py`, `preview_obj.py`.

- **SKELETON + POSING SOLVED (2026-08-24):**
  - **Bone hierarchy** = 8-byte records in the EXE, terminated by -1 (per `FUN_8001e858`,
    copied from `spawnParams+0x34`): `{s16 depth, u8 self, u8 unk, s16 meshIndex, s16}`.
    **The parent is implied by DEPTH** (most recent preceding bone at depth-1), NOT by the
    byte at +3 — they agree for nearly every bone but diverge at bone16 of the 25-bone rig,
    which strands the rear legs and tail at the origin. Corrected 2026-08-24.
    25-bone rigs confirmed at `0x80079064` and `0x80079134`. Tool: `find_bonelist.py`.
  - **Rest pose** = the animation block's "150-byte header" is actually
    `s16 restOffset[boneCount][3]`, so the header is `8 + boneCount*6` (the old constant 158
    was just 8+25*6). Re-validated with zero gaps on 23/25/37/40-bone files.
  - **Rotations** = Euler angles at 4096 units/turn; sine LUT at `0x80084464` verified
    (lut[1024]=4096, lut[3072]=-4096); matrix composition transcribed from `FUN_80047e4c`.
  - **Skin stitching** = mesh block trailing data is `stitchCount` x 16-byte records of four
    `(boneIdx, vertIdx)` pairs; verified `trailing == stitchCount*16` on 6 files.
  - `tools/assemble_model.py` produces a fully posed OBJ. File 833 assembles into a
    symmetric winged humanoid with perfectly mirrored left/right bones.
  - **glTF/GLB export working**: `tools/export_gltf.py` writes a rigged, animated GLB
    (armature + skin weights + all 8 animations). Validated by `tools/check_glb.py`, which
    re-skins from the glTF data and matches the independent OBJ assembly to within
    fixed-point rounding. Output: `models/archive/v0.0_first15/` for the five 25-bone
    models. Animation frames 0/20/45 show clear wing motion.

  - **ROOT MOTION (2026-08-24):** each animation frame has 2 entries before the bones -
    entry 0 = accumulated locomotion displacement, entry 1 = the animated root translation
    that drives bone 1 (replacing its static rest offset). Verified objectively: static
    offset => feet drift 24 units and the body is rigid; entry 1 => feet drift exactly 0
    and the body bobs 51 units.
  - **CHUNK TYPES 8/9 SOLVED (2026-08-24):** they are the per-bone seam vertex pool that the
    stitch records index. For every bone, max(stitch vertexIndex)+1 == the type-8/9 item
    count; each 0x14-byte item holds a vector at +0 and the POSITION at +8. Emitting the
    stitch quads closes every seam - file 833 goes 600 -> 736 tris and renders as a
    complete, connected dragon.

**OPEN (minor):** bone tables for the 37/40-bone models are not in the main exe (only 25-
and 16-bone rigs), so those rigs live elsewhere; textures are extracted but not yet applied
to models (UVs confirmed for FT3/FT4, not yet for the gouraud types).

## Save format (memory card)

**CONFIRMED (2026-08-24):**
- EU card at `DuckStation/memcards/Jade Cocoon ... (Europe)_1.mcd` has 3 GAME saves
  (`BESLES-02201GAME0400/0401/0402`), extracted to `extracted/saves/*.sav` (8192 B each,
  single block). Parser: `tools/parse_memcard.py`.
- Save filename table (product code + GAME/COMB + 04xx) is baked in file index 48
  (UI/system overlay), so index 48 = save/load screen overlay.
- Title in save header (SJIS): "Jade Cocoon/Level 01/Latest Game".
- 3-way diff shows minion/party data region starts ~0x28D-0x300 and 0x5A8+; will map to the
  0xF8 struct once we breakpoint the save writer. (diffs logged this session.)

## RAM map

**CONFIRMED (2026-08-24):**
- `0x80010000..0x800CA800` = exe code+data (see above).

## Function addresses

(nothing yet)

---

## Next steps
1. Map file indices to content: find callers of FUN_80041d44 / FUN_80041de4 / FUN_80030ae0 /
   FUN_80041d90 / FUN_8004241c and see which indices they pass (immediates or tables) —
   that tells us which of the 1108 files are minion models, stats, fields, etc.
2. Crack the container sub-formats (577 unclassified; the count+offsets packs; find the
   nested TIMs/TMDs and pull one minion model out).
3. Runtime pass (PCSX-Redux or DuckStation debugger): breakpoint FUN_80041a70
   (0x80041A70) and log fileIndex args during boot → menu → battle → merge screen.
   That labels indices by game context fast.
4. Identify save-data / minion struct in RAM (memory search on known stat values).
5. Merge algorithm: once minion structs are known, breakpoint the merge UI flow.


## CORRECTION (2026-08-24): merged minions ARE geometry-blended

An earlier entry in this session concluded the engine has "no blendshapes / no morphing".
**That conclusion was wrong and is retracted.** What was actually verified is narrower:
the archive stores no morph targets, and the battle renderer transforms static per-bone
vertices. Both remain true.

The error was generalising from "no stored morph data" to "no morphing". Merged minions are
visibly shape-blended in game (a wasp merged into a dragon base produces antenna-ward ears
and larger wings), and since **any minion can merge with any other, repeatedly**, the
results cannot be pre-modelled. Therefore the merged mesh is **generated at merge time** and
only its recipe is persisted — which is exactly why nothing morph-like appears on disc, and
why the 0xF8-byte minion struct can survive a save/load.

Leads for the generator and the recipe fields are in MERGE_ALGORITHM.md ("How the MESH
changes when you merge — CORRECTED"). A runtime breakpoint on the mesh allocator during an
in-game merge is the cheapest way to settle the interpolation rule.


## THE MESH MERGE — SOLVED (2026-08-24)

**CONFIRMED (2026-08-24), statically from `SLES_022.01`:**

- The merged-mesh generator is **`FUN_80010DB0`** in the **main exe** (not the merge
  overlay). It blends up to **three** parent models by weight into a newly allocated one.
- The blend is a **per-vertex linear interpolation**, `dst = lerp(dst, src, w)`, implemented
  as `FUN_80039FE8` (`out = a - b`, per SVECTOR) followed by `FUN_8003A6C8`
  (`out = (0x1000*a + w*b) >> 12`, via `gte_LoadAverageShort12`). Both walk **all ten**
  entries of the 0x54-byte runtime mesh object — every primitive type plus both seam-vertex
  pools — and blend **normals as well as positions**.
- Source 0's mesh array is taken over wholesale (`dst->+0x50 = src0->+0x50`, source nulled)
  and mutated in place, which is why the base cocoon donates the body.
- Per mesh object the weights are modulated by a **per-mesh weight table** in each parent's
  appearance blob, so body regions blend at different rates.
- `FUN_8004A520` blends the **skeleton** (per-bone rest offsets, and the frame-0 X rotation
  in modular 4096-unit angle space) into a fresh one-frame animation.
- `FUN_80011904` blends the **43 attachment markers** in IEEE float.
- Body-part flags merge as `if (other.A[k] > 1 && mine.A[k] == 1) mine.A[k] = 2` — merging
  a wingless minion with a winged one **gains the wings**.
- Finally marker id `0x26` is transformed to world space and its Y subtracted from the root
  rest offset, re-seating the blended creature on the ground.

**Why it works — VERIFIED against the data:** a full-archive mesh scan finds 104 distinct
meshes, and **49 of them share one exact topology signature** (same 25 mesh objects, same
primitive counts per type, same 32976-byte stream length, same 25-bone rig at
`0x80079064`). That hand-authored morph family is the mergeable minion roster. Per-vertex
blending is only possible because of it.

**The appearance blob (`MODEL+0x4C`, package section 0)** carries the five growth stages
(global scale 1638..4096 = 0.40..1.00 in 1.12 fixed, plus a per-bone scale array giving
babies big heads and short bodies), the three body-part flags, the 43 markers, and the
per-mesh blend weights. Struct in `MERGE_ALGORITHM.md`. Parser: `tools/appearance.py`.

**Body-part groups** (`FUN_80019B14` + three exe bitmasks): `0x80072F60` = 0x1F8 = bones 3-8
arms, `0x80072F64` = 0xF000 = bones 12-15 wings, `0x80072F68` = 0x7E0000 = bones 17-22 legs.
`partFlagsA[i] < 2` clears bit 1 of `boneRec+6`, which gates both the transform and the draw
in `FUN_80047E4C` — the whole limb group disappears.

**Runtime scale chain** (`FUN_8001FA58` -> `FUN_8001FD70` -> `FUN_80047E4C`):
```
actor[0x26]         master scale, ramps toward actor[0x2A] by actor[0x28] per frame
actor[0x2C..0x34] = growthVector(actor[0x138..0x140]) * actor[0x26] >> 12
boneTranslation   *= perBoneScale / 4096
boneMatrix         = boneMatrix * diag(perBoneScale) * diag(actor[0x2C..0x34])
```
The per-bone scale reaches the actor via `spawnParams+0x3C` (`FUN_8001E858` -> `actor+0x144`,
default `{4096,4096,4096,0}` at `0x80073FD4`); the growth vector via `spawnParams+0x38`.

### RETRACTED
The six 12-byte blocks at minion struct `+0x04` are **not** geometry blend parameters (a
2026-08-24 hypothesis). `FUN_800BC550` passes `+0x94` to the string renderer `FUN_8002FAFC`:
`+0x94` is the minion's **name** (12 bytes) and `+0x04..+0x4B` its **six ancestors' names**,
shuffled by `FUN_800BAD08` as `[base.self, material.self, base.p0, base.p1, material.p0,
material.p1]`, with a parallel per-ancestor flag byte array at `+0x7C` (own flag `+0xC6`).
That is the merge-lineage display, nothing more.

## Model census — 104 meshes, 85 rigged exports

**CONFIRMED (2026-08-24):** files **831-933** (plus 10, 197, 1072) all carry mesh blocks —
106 files, 104 distinct meshes. The exe descriptor table only names 16 of them, which is why
earlier passes exported 15. New tools `tools/build_index.py` (archive-wide rig + animation
index: 244 bone tables, 104 animation containers) and `tools/export_every.py` export the
whole census: **85 rigged/animated/textured GLB** (all pass `check_glb.py`, all textured)
plus **21 unrigged OBJ** for the bone counts with no rig (2,4,5,17,24,26,35) or no animation
(14,15,19,28) anywhere in the archive. The rest pose lives inside the animation block, so a
model with no animation container cannot be skinned at all.


## Export pass 2 — corrections (2026-08-24)

**CONFIRMED:** seam (chunk type 8/9) vertices carry **u,v at on-disc +0x0E/+0x0F** and the
type-9 pool header is `{u32 count; u16 tpage; u16 clut}` — the same texture ids the bone's
faces use. Read off `FUN_80023074` / `FUN_80023274` field by field, and verified: all 160 of
model 833's seam UVs sample opaque texels from page 0x95. The v0.1 export read only the
position, which is why the connecting strips were untextured and their UV islands empty.
Type 8 has no UVs (the converter zeroes the runtime UV word) and is genuinely untextured.

**FIXED:** the exporter wrote POSITION in bone-local space with identity inverse bind
matrices. Correct under animation, useless in Blender's edit mode (every bone's geometry
collapsed onto the origin). POSITION is now baked into bind-pose space with real inverse bind
matrices; re-skinned bounds are identical to the digit. `check_glb.py` shared the identity
assumption and now does full glTF skinning.

**FIXED:** rig and animation attribution. Bone count alone is not enough — model 831 has 23
mesh objects but is a 22-bone model, and picked up a foreign rig and rest pose. `rigfit.py`
now scores candidates by how well the **stitch quads close** (median quad extent, game
units): 833 with its correct rig scores 53, 831 scored 121 with the wrong one and 32 with the
right one. Rest poses may only be borrowed from the creature region (file >= 600): model 931
had taken a 20-bone set from system overlay 21 and scored *better* (110) than model 930 with
a correct rig (113), so provenance, not fit, separates those two.

**Not a bug:** the `.001`/`.002` suffixes on animation names were Blender de-duplicating
identically named actions across separately imported GLBs. Names now carry the model id.
Single-frame blocks are real (the 25-bone family ships two poses and six motions) and are now
named `pose`.

**Result:** 90 rigged/animated/textured GLB (all valid, all textured) + 16 unrigged OBJ; fit
scores 20-113, median 53. `export_report.json` records the rig, animation source, borrow flag
and fit per model; 34 models legitimately share another file's rest pose.

**FIXED (flip):** the PS1 Y-down -> glTF Y-up rotation used to sit on a wrapper node above
both the joints and the mesh. Once vertex positions were baked into bind space they already
carried it, and Blender applies the object transform on top in edit mode - the model showed
up upside down. The flip now lives in the ROOT JOINT's local transform (bind pose and every
animation frame; the renderer forces slot 0 to zero rotation, so a naive export would key an
identity quaternion there and undo the flip on playback), and the wrapper is identity.
Verified: joint-local vertices round-trip through bake -> inverse-bind to 2e-4, rest bounds
match v0.1 exactly, animated frames match to 0.001.

**Animation census:** across the 90 rigged models there are 549 animation blocks; 432 move,
117 do not, and 115 of those 117 are single-frame. Every block with 3+ frames animates. The
"animations that do nothing" are pose blocks - the 25-bone family ships two 1-frame poses
plus six motions of 21-75 frames. Per-block `frames`/`maxRotDelta`/`maxRootMove`/`moves` are
recorded in `export_report.json`.

## Overlay actor spawning and the streamed animation library (2026-08-24)

Open thread 0. Full write-up in `OVERLAYS.md`; format detail in `MODEL_FORMAT.md`.

- **CONFIRMED** Overlay load addresses come from `{u32 fileIdx, u32 destPtrPtr}` at
  `0x8007D90C` (31 entries, files 23-53); the slot variables `0x8007311C`..`0x80073134` hold
  six distinct load addresses. **File 27 is `ENMBATLE.C` at `0x800A0530`** (105 of 206
  self-`jal` targets land on a prologue there, 0-4 at any neighbouring base).
- **CONFIRMED** `FUN_800BF750` lives in overlay 44 (`0x800B6ED0`+`0x9D28`) - the merge UI.
- **CONFIRMED** `FUN_8001D4C4` takes a **0x50-byte SpawnDesc** whose every field is now
  mapped, from three independent call sites and both consumers (`FUN_8001E5DC`,
  `FUN_8001E858`). The rig is `+0x34`, a raw pointer; no per-bone rest offsets pass through
  it at all.
- **CONFIRMED** Scene/actor packages (files ~111-113, 199-470) load at **`0x800B248C`**.
  Evidence: 131 of them contain a code word referencing exactly `base + rigOffset` and
  another referencing `base + rigOffset + 0xB8`.
- **CONFIRMED** Nothing "selects" a rig. Creatures get `&DAT_80079064` (the exe 25-bone
  table) unconditionally; every other actor takes the pointer in its own actor record, and
  when that field is null - which it is for ordinary NPCs - the scene package's generic
  spawner `ovl_800B25F4` substitutes **its own copy of the 22-bone humanoid table**.
- **CONFIRMED** There is exactly **one** 22-bone humanoid skeleton. 149 of the archive's 244
  bone tables have 22 bones; 132 are byte-identical and the other 17 differ only in bone 0's
  flag word. 831, 832 and 849 also have **byte-identical rest offsets**.
- **CONFIRMED** The animation block header carries two flag bits: bit 31 of `boneCount` =
  "an event list `{u32 count; s16 ev[count][4]}` follows the keyframes", bit 31 of
  `frameCount` = "an extra u32 precedes the rest offsets". Read off `FUN_80026AF4`, the
  on-disc -> runtime converter, and verified by zero-gap tiling in all six affected files.
- **CORRECTION** Files **831 and 832 do not contain zero animation blocks.** They hold five
  resident 22-bone blocks each (62, 44, 30, 61, 62 frames) plus ~200 streamed. The old claim
  came from the flag bit above. 841, 876, 893 and 930 were recovered the same way; 893 and
  930 are **24-bone** models, not 25 or 26.
- **CORRECTION** The exe model descriptor table at `0x800823F0` has **103 entries**, one per
  model file 831-933, not 16. `tools/model_index.py` had `NPTR = 16` hard-coded.
- **CONFIRMED** Past its four whole-file ranges each descriptor carries a **per-animation
  `{startSector, sizeSectors}` table** at `[10 + desc[9]]`, read by `FUN_800254A8` to stream
  one clip at a time. Each slot holds a **bare** animation block with no container header.
  **2474 streamed blocks over 103 models**, against 548 resident, and the two sets are
  disjoint. This is the animation frame stream that `RIG_ATTRIBUTION.md` could not locate.
- **CONFIRMED** A model whose resident animation range is one all-zero sector is not
  animation-less: 39 models are in that state and their whole library is streamed. 854 owns
  30 clips, 869 owns 37, 875 owns 31 - each with its own rest pose. Bone 1 measures -241 on
  the player characters, -64 on 855, -99 on 863, -49 on 875/877. **That spread is the
  "head in the neck" / "long neck and legs" error the Blender review reported.**
- **CONFIRMED** For the player-character models the animation-table entry stride is `0x40`
  (`ovl_800AC678` and friends), with `+0x00` = animation id, `+0x01` a flag, `+0x06` the
  loop-restart frame, `+0x08` the end frame. Ids 14..109 are remapped by
  `FUN_800AC964` as `id + variant*16`; ids 0..13 are shared.
- **CONFIRMED (negative)** No 24-, 26- or 35-bone table exists. Checked three ways: the
  split-file scan, the same scan with the depth-monotonicity rule dropped, and a scan of the
  **raw 211 MB DATA.001**, which also covers the ~951 KB of gaps between file-table entries
  and anything straddling a split boundary. Bone tables exist at 14, 15, 16, 19, 20, 22, 23,
  25, 28, 37 and 40 bones and nowhere else. No second 40-bone table either.
- **CONFIRMED** `FUN_80047E4C` walks the **rig's** records to the `-1` terminator and indexes
  the clip as `keys[(frame*(clip->boneCount + 2) + rec->self + 2)*6]` - the clip's stride,
  the rig's iteration. **Rig length and clip length are therefore independent**; a clip only
  has to be at least as long as the rig. The record's depth word is a matrix-stack index,
  a third confirmation that parent is implied by depth. The same function blends two clips
  by weight, both indexed by the same `self` - the action crossfade.
- **CONFIRMED** With that relaxation applied to each model's own clips: 870 fit 95 -> 55
  (23-bone rig, own 26-bone clips), 879 81 -> 43 (25-bone, own 26-bone), 893 90 -> 52
  (23-bone, own 24-bone), 930 104 -> 85 (23-bone, own 24-bone). A known-correct assembly
  scores ~53.
- **CORRECTION** `MeshBlock+0x04` is the **mesh object count**, not the bone count - verified
  equal to the object count for all 106 models, while 831 has 23 objects on a 22-bone rig and
  893 has 26 on a 24-bone one.
- **Export v0.4**: 102 rigged / 4 static (was 94 / 12), 4 models still borrowing a rest pose
  (was 34), median fit 52.7 -> 47.4, all 102 GLB pass `check_glb.py`.
- **Export v0.5**: 102 rigged / 4 static and **zero borrowed rest poses**, median fit 46.4,
  all 102 GLB pass. Model 841 is the only one left with real animation data and no rig.
- **CORRECTION (Blender review)** "The 24/26-bone skeletons are not needed" was **wrong**.
  Running a model's own longer clip on a shorter rig places the first N bones correctly and
  strands every mesh object past N at the root; 870, 879, 893 and 930 read as "partially in
  the right place, the rest a mess". The shorter rig is an improvement (every fit score
  dropped), not a fix. Those tables are needed and are not on the disc.
- **REJECTED** Deriving the missing tables from the stitch graph. `meshIdx == self` in all
  244 tables and parent is implied by depth, so a table is one integer per bone; a beam
  search over depths scored by stitch closure (`tools/derive_rig.py`) recovers only 17/25
  (833), 21/25 (867), 18/22 (831) and **9/40** (840) parents, and on 867 the derived rig
  scores **better** (44) than the real one (51). It finds a skeleton that closes seams, not
  the skeleton. The stitch records witness about 15 of 24 true parent edges; the rest are
  unconstrained. Variants kept at `models/derived_experiment/`, not shipped.

## Export pass 3 - the appearance blob is not creature-only (2026-08-24)

Triage of a Blender review that flagged 18 of the 90 rigged GLB as visibly wrong. Full
write-up in `RIG_ATTRIBUTION.md`.

- **CONFIRMED** All three sections of the section-0 blob are optional. `FUN_80024EA0`
  (anim table), `FUN_80024ECC` (markers) and `FUN_80025010` (stages) each return 0 when
  their offset word is 0. `appearance.py` required all three, so it rejected the blob for
  every non-merging model - the NPCs, bosses and player characters, i.e. exactly the
  population whose bone count we could not otherwise determine. Coverage 48 -> 103 of 106.
- **CONFIRMED** The blob's animation table is `{u32 count; Entry[count]}` with a 60-byte
  stride, ending exactly at `offMarkers`. Verified on 59 of the 61 models where both
  offsets exist; models 831/832 (the player characters) use 64 bytes.
- **CONFIRMED** No model package names its own skeleton. `FUN_800BF750` passes the rig to
  the actor spawn as a hard-coded pointer (`&DAT_80079064`). Only the two 25-bone creature
  rigs are referenced from main-exe code; every other rig is selected by overlay code.
- **CONFIRMED** Where the blob parses, rig attribution was never wrong: bone count matched
  for all 48 creatures, 0 mismatches. Every model the review flagged lacks a blob.
- **CONFIRMED** v0.2 silently dropped mesh objects no bone claimed - 32 objects across 17
  models, up to 79 primitives on model 870. Geometry was only ever emitted per bone.
- **CONFIRMED** 26 of the 48 creatures ship body-part groups the game does not draw
  (`partFlagsA[g] < 2`); 907/908/909 hide arms, wings and legs. The export ignored the
  flags entirely.
- **HYPOTHESIS** The 60-byte entry is `{u8 clipId, u8 flag, s16 startFrame, s16 range[22],
  s16 term[6]}` and slices a longer frame stream into clips. Frame numbers run past any
  stored block (model 854 reaches 299) and the stream has not been located.
- **REJECTED** Model 870's 26-bone skeleton is not the 25-bone creature rig plus a bone:
  scored against 870's own rest pose it fits 101, worse than the 95 it gets borrowing 867.
- **CONFIRMED** Model 840 borrows 836's bone table. Only one 40-bone table exists in the
  archive (`0422@0x180C`) and only two 40-bone animation containers (836's and 840's own,
  not swapped - all four combinations scored). 840's marker ids 0x127-0x12A and
  0x19F-0x1A2 form four-fold effector sets on bones 12/6/24/18 with one offset, but that
  rig puts them at depths 6/6/6/3, with bone 18 a bare leaf. Its own table is not on disc.
- **CONFIRMED** `rigfit` scores only bones that appear in a stitch quad. Model 840 scores a
  healthy 68 while covering 12 of 40 bones, and the uncovered ones are the detached limbs.
  Reported as `fitBones`/`fitBonesOf`; 836 and 840 are the only models under half.
- **REJECTED** Parent-child assembly gap as a general quality metric: creatures legitimately
  carry detached parts, so 907 (172% of model extent), 899 and 924 outscore 840 while
  looking correct. Only valid comparing one model across rigs.
- **REJECTED** Deriving bone parenting from mesh geometry: validated against 836's known
  rig it recovered 7 of 39 parents, because large mesh objects tie at gap 0.


## The visual merge end to end (2026-08-25)

Full write-up in `MERGE_ALGORITHM.md`, section "THE VISUAL MERGE, END TO END". Ledger
entries only here.

**CONFIRMED**
- **The merge job is a five-state pump, not a call.** `FUN_80010850(recipe)` allocates a
  0x40-byte job, `memcpy`s a 0x34-byte recipe into it at +0x04, sets state 1 and registers
  `FUN_80010AD8` as a scheduler tick. `FUN_80010AD8` dispatches through a six-entry jump
  table at `0x80071A84`: 1 = load the three sources, 4 = wait, 2 = `FUN_80010DB0` (the
  blend), 3 = load the texture and the dominant parent's animations, 4 = wait, 5 = done.
  `FUN_80010A44` returns the finished model, `FUN_8001098C` frees it. None of the handlers
  is `jal`ed, which is why Ghidra had not created functions for any of them.
- **MergeJob +0x34 is a resource-directory POINTER**, not a count; the merged model is
  allocated out of `dir + 0x20`. Three previously unnamed fields are +0x24
  `texSourceIndex`, +0x28 `hueDegrees` and +0x2C `texModelId`.
- **Four overlays build a merge recipe**: files 26, 28, 36 and 44 all `jal 0x80010850`.
  28, 36 and 44 also call `FUN_80033938`, so the recipe rule is shared, not UI-specific.
- **`FUN_800BF208(minion, recipe, dir)` in overlay 44 is the recipe builder.** It reduces
  the ancestry to three parents, collapses duplicate models, forces the minion's own model
  into slot 0, and fills the stage, the texture id and the hue.
- **The 0x30 bytes at minion +0x4C are a 48-slot ANCESTRY LIST of species ids**, not skill
  ids. `FUN_80033938` histograms them over 211 buckets - the exact length of the species
  roster - takes the top three, and normalises their multiplicities to 4096. The six
  "skill families of five" recorded earlier are a base species plus its four elemental
  variants, and all six satisfy `variant = 57 + base*4 + element`, which is the species
  table's own layout.
- **The species table is at `0x8007BC54`**, 4 bytes per entry, 365 entries (the region ends
  at the growth-stage thresholds at `0x8007C208`); ids 0-210 are the usable roster.
  `{u16 modelId; u8 hueBase; u8 hueRef}`, both hue bytes in units of two degrees.
  `FUN_80019C70(id)` is the accessor, shared by the battle spawner, the scene-package actor
  spawner and the merge. This is the species -> model -> DATA.001 file map; dumped by
  `tools/merge_reference.py species` to `extracted/species_index.txt`.
- **Table layout**: 0-35 base creatures, 36-56 specials, 57-200 the four elemental variants
  of each base (`57 + base*4 + element`), 201-210 ten uniques, 211-364 a second parallel
  table for ids 57-210 at `id + 154`. All 36 bases, all 144 variants and all 10 uniques
  resolve to files inside the 49-model morph family; the only 12 that do not are specials,
  on files 835-841, 870, 876, 893 and 930.
- **The merged texture is SELECTED, not blended.** State 3 loads section 1 (textures) of
  one model id - the appearance species at minion +0x03 - and section 3 (animations) of the
  dominant parent. `FUN_80025658` and `FUN_80025720` have exactly one caller each, the
  merge job. The three sources are deliberately loaded *without* their textures.
- **The merged palette is HUE-ROTATED.** The resource-load block's field at +0x08 defaults
  to -1 and is only ever set by `FUN_80025658`. `FUN_800260E4` sees it non-negative and
  calls `FUN_80029044`, which runs `FUN_80029D68(tim, degrees)` over every TIM's CLUT
  before upload: BGR555 -> HSV on a 192-step hue circle, `h = (h + degrees*24/45) % 192`,
  achromatic entries skipped, saturation and value untouched. Only merged creatures ever
  take this path.
- **The hue comes from the four element tallies at minion +0xC2.** Each element is a unit
  direction 90 degrees from its neighbours (sine-table entries 739/1763/2787/3811 at
  `0x80084464` = 64.95, 154.95, 244.95, 334.95 degrees); the tallies are summed as a vector
  and `FUN_8003B570` = `ratan2` rescaled to whole degrees gives the angle. A single non-zero
  tally returns the sentinel -1000 and the species' own `hueBase*2` is used instead.
  Otherwise `hue = (angle - hueRef*2) mod 360`.
- **The four elemental variants of every one of the 36 base species differ by exactly 90
  degrees of `hueBase`**, in element order - 36 groups of 36, no exceptions. That is the
  independent proof that the two bytes are palette angles.
- **The model descriptor at `0x800823F0` is (startSector, sizeSectors) pairs**, one per
  section, not "(size, cumulative end)". Loads carry a section bitmask: 1 = appearance
  blob, 2 = textures, 4 = mesh, 8 = resident animations.
- **The per-mesh blend weights are a hard override, not a soft weight.** Only three models
  in the archive carry a non-zero value at all: 845 (stage 0, mesh 10), 861 (stage 3, mesh
  9) and 868 (stage 4, mesh 5). Everywhere else all three sources agree and the job's global
  weights are used unchanged. Where a value does appear the renormalisation collapses to
  `{0, 0, 4096}` and that mesh object comes entirely from the parent carrying it. The
  original's renormalisation cascades - each division's denominator already contains the
  previous results - and `merge_reference.py` reproduces that verbatim.
- **All 49 morph-family files have a byte-identical chunk-stream structure**: 25 mesh
  objects, same chunk types in the same order, 32,976 bytes consumed. **48 of 49 also share
  a byte-identical 68-quad seam table; model 850 has 64 quads** and a 34,000-byte mesh block
  against the others' 34,064, and packs its sections differently (1-sector blob, not 3).
- **The current GLB export is NOT vertex-order identical across the family.** All members
  export 1,576 vertices (1,560 for 850) but split across 3, 4 or 6 primitives depending on
  how many body-part groups the appearance blob hides; 22 of 49 match 833 exactly. Two
  arbitrary family members cannot be used as each other's shape keys as exported. Blending
  at the archive level avoids the problem.
- **The archive-level blend is numerically exact.** Over the 2,889 blended SVECTOR slots of
  a 833 x 867 merge (2,775 of which differ between the parents), weight 0 reproduces 833,
  weight 4096 reproduces 867, and weight 2048 matches `(0x1000*a + w*(b-a)) >> 12` in
  2,889 of 2,889.

**HYPOTHESIS**
- Species ids 211-364 are a second palette table for ids 57-210 (offset +154). No accessor
  found. Whatever reads it probably also decides a creature's appearance id (+0x03).
- Five of the twelve "special" species files - 840, 841, 870, 893, 930 - are exactly the
  models whose bone table is not on the disc (`OVERLAYS.md` S7). They have species ids, so
  they can be party minions, which means a spawn path other than the field-NPC and
  battle-enemy ones must draw them.
- `FUN_800BA198`'s `param_4` selects one of ten appearance ids (201-210, the ten unique
  models 914-923) from the table at `0x8007CA70`, or -1 for "leave unchanged". What sets
  `param_4` is untraced.

**REJECTED**
- Putting model 870 on the exe's 25-bone creature rig with its own 26-bone clips: fit 95
  against the current 23-bone assignment's 55. Models 893 and 930 cannot run on a 25-bone
  rig at all - their own clips are 24 bones, shorter than the rig.

## Species names, and the merge studio (2026-08-25)

**CONFIRMED**
- **Every species' English name is in the exe.** `0x8007A094` is a `char*` array with
  exactly 209 entries, one per species id 0..208, pointing into a string pool at
  `0x80072234..0x80072F60` (which ends where the part-flag bone masks begin). The strings
  are Shift-JIS **full-width Latin**, which is why two ASCII sweeps of DATA.001 found
  nothing. Reader: `tools/merge_reference.py::species_names`.
- **The community Complete Minion List's hex IDs are the game's species ids.** All 209
  names match entry for entry; 0x00 Marrdreg is species 0, 0xD0 Klarrgas is species 208.
  Two independently derived tables agreeing is what makes both trustworthy.
- **File 114 is the Japanese name table**: `{u32 size; u32 count}` then NUL-terminated
  Shift-JIS katakana padded to 4 bytes, 153 entries. Its index is not the species id -
  name `0..144` is species `200 - index` and name `145..152` is species `353 - index`, so
  it covers species 56..208 in descending order and nothing below 56. Entry 144 is
  `？？？？？？？`, matching species 56 Cushidra, the final boss with a hidden name. The
  count word (313) is not the name count; MIPS code follows the strings.
- **The five models with no bone table on disc are named specials**: 840 Seterian,
  870 Kikinak, 893 **Poacher** (a human, `密猟者`), 930 Dream Man / Chosen One, and
  841 **Cushidra**, the final boss. 893 being a human explains why no creature rig fits.
- **Element index -> roster prefix**: 0 = Pata/パタ, 1 = Sk/スク, 2 = Ter/テラ,
  3 = Rad/ラド. Measured over all 36 four-variant groups; 17-21 groups per column use the
  plain prefix and the rest are one-offs, but no column ever borrows another's prefix.
- **Neither ordinary spawn path reads the palette angles.** `ovl_800A1F10` (battle
  enemies) and `ovl_800B25F4` (scene actors) both read only `*(u16*)rec`; `hueBase` and
  `hueRef` are touched by the merge recipe builder alone.

**HYPOTHESIS**
- `テラ` = terra, so element index 2 is Earth. Would settle the GR-matrix index order.
  Not proven - the game's element text is not yet tied to an index.
- **Every party minion is built through the merge job**, not just merged ones. It is the
  only path that applies a palette rotation, `FUN_800BF208` degenerates to an identity
  copy when a minion's ancestry holds only its own species, and four overlays call
  `FUN_80010850`. Otherwise a wild Pataraid and a wild Terfrayd would render identically.
  Settleable with one breakpoint.

**TOOLING**
- `tools/merge_studio.py` + `merge_studio.html`: a dependency-free local web app. Server
  reads the disc; the browser does the per-vertex blend in the game's own fixed-point
  arithmetic, so the weight slider morphs live. Skinning, pose (`FUN_80047E4C`'s Euler
  maths on a JS copy of the sine table), the part-flag OR rule, the growth stages (level
  -> stage, blended whole-body scale, the base's per-bone scale applied per bone without
  inheriting down the chain, per-stage part flags and the per-mesh-object weight override)
  and the palette rotation (`FUN_80029D68` in the fragment shader) are all transcribed. It derives the 49-model
  mergeable family at startup by grouping model files by chunk stream, and can export the
  current blend as a GLB. PS1 winding is clockwise once the Y/Z flip is in the view
  matrix, and the atlas must be sampled NEAREST or the hue rotation stops being exact.
## Every model file gets its name (2026-08-25)

**CONFIRMED**
- **`ActorInfo +0x00` is a pointer to the actor's name.** `OVERLAYS.md` §2 decompiled the
  scene-package spawner and recovered the record from `modelId` at +0x04 onward; the
  spawner never touches +0x00, which is why the field was invisible from the code. It is a
  `char*` into the package's own string pool, holding the name in the same Shift-JIS
  full-width Latin the exe uses for species names. Records are found by requiring the three
  trailing fields (`rig`, `globalScale`, `boneScale`) to be null or in-package - the check
  that separates a record from a coincidence, and it leaves exactly one false positive over
  the whole archive (a sentence of help text in overlay 42).
- **The 272 scene packages are therefore a name table for every NPC**, and they close the
  gap the species table leaves. Species names cover 51 model files; actor records cover 48
  more, including Garai, Mahbu, Lui, Kelmar, Ada, Baba, Tao, Poto, Kupid, Nam, Musa, Wen,
  Baku, Koris and Grotta. **99 of the 106 model files are now named.**
- **The two tables agree wherever they overlap** - `835 Fire Boss`, `870 Kikinak`,
  `876 Masked Boy`, `893 Poacher`, `930 Dream Man` are named identically by both. That
  agreement is the evidence the record layout is right. Where they differ, the species
  table holds the player-facing name and the actor record holds the internal codename:
  `836` is `Tuturis` to the player and `BSFS` in the package, `838` `Delfanel`/`BSGS`,
  `840` `Seterian`/`BSWS`, `841` `Cushidra`/`BSZZ`.
- **Seven files are named by neither table**: 10, 197, 834, 849, 922, 923 and 1072. 922/923
  are species 209/210, past the 209-entry name array, and sit in the same series as the
  eight named uniques (914-921). 197's texture bank is an opening-cutscene set (subtitle
  strips plus a winged creature) and 1072's is lens flares - neither is an actor.

**HYPOTHESIS**
- **831 and 832 are both Levant.** Neither is named on the disc and neither is spawned
  through an `ActorInfo`. 831's texture bank is one character portrait plus the game's
  sword set; 832 is that same portrait with 345 textures of alternate outfits and weapons.
  They are also the only two models whose animation records are 64 bytes instead of 60
  (`RIG_ATTRIBUTION.md`), i.e. the only two the game treats as the player. Recorded as
  `MANUAL` in `tools/model_names.py` so it is one line to overturn.

**TOOLING**
- `tools/model_names.py`: resolves model file -> name from both tables, dumps
  `extracted/model_names.json`. `export_every.py`, `export_all.py` and `export_derived.py`
  now name their output `jc_NNNN_<Creature>.glb` and put the same name on the GLB's root
  node (`--root`), which also retires the ten-objects-called-`JadeCocoonModel` problem in
  Blender. Action names keep the bare index: they must stay unique across models and six
  model files are called Mahbu. `export_report.json` is still keyed by file index and gains
  `name`, `nameSource` and `stem`; re-exporting changed nothing else in it, which is the
  check that the rename is only a rename.
