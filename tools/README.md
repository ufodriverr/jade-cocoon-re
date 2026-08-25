# Tools

Python 3, no dependencies, no install. Every script that touches game data takes the path
to **your own** disc image or the files extracted from it as an argument; none of them
contain or download game data.

Most take `-h` or print usage when run with no arguments. Run them from this directory:
the export and index scripts assume `../extracted/` and `../models/` as in
[../docs/START_HERE.md](../docs/START_HERE.md).

## The pipeline

Run these in order to go from a disc image to the full model export. This is the whole
thing; everything else on this page is a component of it or a way of looking at it.

| script | what |
|--------|------|
| `iso_ls.py` | list the ISO9660 filesystem of a raw PS1 bin (MODE2/2352, single track) |
| `iso_extract.py` | extract files using the JSON listing from `iso_ls.py`. STR/XA are Form2 interleaved: use jPSXdec for A/V, this is for data files |
| `split_data001.py` | verify the decoded file table against `DATA.001` and split it into 1079 sub-files |
| `build_index.py` | archive-wide index of bone tables (rigs) and animation containers |
| `model_names.py` | give every model file its real in-game name, from the species table and the scene packages' actor records |
| `export_every.py` | **the exporter.** Every creature model to a rigged, animated, textured GLB, driven off the 103-entry exe descriptor table plus an archive census |

## Reading the formats

| script | what |
|--------|------|
| `dump_file_table.py` | decode the `DATA.001` file table embedded in the exe |
| `scan_data001.py` | first-pass structural scan of `DATA.001` |
| `tim.py` | PS1 TIM texture parser to PNG, written by hand, no deps |
| `extract_textures.py` | bulk-extract every TIM in the split sub-files to PNG |
| `texture_atlas.py` | rebuild a model's VRAM texture pages as atlas images, for UV-correct export |
| `mesh.py` | mesh block parser |
| `anim.py` | animation block parser |
| `appearance.py` | appearance blob parser (`MODEL+0x4C`): growth stages, body-part flags, markers |
| `model_index.py` | read the model descriptor table from the exe and classify each sector range. **Start here for model work** |
| `model_anims.py` | list every animation a model owns, streamed table included |
| `parse_memcard.py` | parse a PS1 memory card (raw 128 KB `.mcd`) and list or extract saves |

## Exporting

| script | what |
|--------|------|
| `export_gltf.py` | one model to a rigged, animated, textured GLB |
| `export_mesh.py` | mesh blocks to Wavefront OBJ |
| `export_all.py` | the older 16-model path, driven off the exe descriptor table alone |
| `export_derived.py` | the five models with no skeleton on the disc, on a **derived** bone table. An experiment |
| `assemble_model.py` | full skeletal assembly to a posed OBJ: hierarchy, rest pose, rotations |
| `check_glb.py` | validate a GLB: structure, accessor bounds, skin sanity, and the skinning result. Checks the **bind pose** only |
| `check_anim.py` | validate a GLB **under animation**, which `check_glb.py` cannot: at bind pose every skin matrix is the identity, so a rig that disagrees with its geometry still looks perfect. Reports worst edge stretch per clip; pass `--baseline` a known-good model to compare against |
| `preview_obj.py` | render an OBJ to PNG with a tiny z-buffered rasteriser, no deps |
| `build_viewer_index.py` | regenerate `viewer/models.json` after re-exporting |

## The merge

| script | what |
|--------|------|
| `merge_reference.py` | reference transcription of the merge: the confirmed formulas, the mesh and skeleton blend, the palette rotation, and a self-test against the game's fixed-point arithmetic. Can write a merged GLB |
| `merge_studio.py` | **the live tool.** Serves a local page that lists every creature by name and blends any two on a slider, animated, with palette rotation, the body-part rule and an age slider. Exports the result as a GLB. Needs your disc |
| `merge_studio.html` | the page `merge_studio.py` serves. Raw WebGL, no dependencies |

```bash
python merge_studio.py ../extracted/SLES_022.01 ../extracted/DATA001_split --open
```

## Rig attribution

| script | what |
|--------|------|
| `rigfit.py` | score how well a (rig, rest pose) pair actually fits a mesh block, by whether the seams close |
| `find_bonelist.py` | find bone-hierarchy tables in the exe |
| `derive_rig.py` | derive a bone table from the mesh's own stitch records. Recovers only 60-85% of parents on rigs we already have, so it is not a fix |
| `scan_anim_unaligned.py` | scan every archive file for animation containers at any 4-byte alignment |
| `scan_tmd.py` | scan the split sub-files for embedded TMD models |

## Code archaeology

These read the PS1 executable and the overlays. They are how the formats above were worked
out in the first place.

| script | what |
|--------|------|
| `mipsdis.py` | minimal MIPS R3000 disassembler for reading PS1 code out of raw images |
| `disovl.py` | disassemble a range of a raw overlay image loaded at a fixed address |
| `exe_strings.py` | printable strings in the exe with their RAM addresses |
| `find_store.py` | find MIPS loads and stores at a given struct offset |
| `find_jal.py` | scan every sub-file and the exe for `jal <addr>` to a main-exe routine |
| `find_mesh.py`, `find_mesh_array.py` | locate the packed mesh header and the 0x54-byte mesh object array in package files |
| `find_file_table.py`, `find_file_table2.py` | the two passes that found the archive file table |
| `GhidraScripts/` | headless Ghidra scripts. `MakeAndDecomp.java` is the useful one: it disassembles a range, creates a function at every `addiu sp,sp,-X` prologue and decompiles the lot, which is how code reached only through a jump table was found |

```bash
analyzeHeadless <proj> JadeCocoon/psx -process SLES_022.01 -noanalysis \
  -scriptPath tools/GhidraScripts -postScript DecompFuncs.java <outDir> 0xADDR ...
```

Ghidra 12.1.3 with `ghidra_psx_ldr`. PSYQ signatures name 1532 of 1989 functions.
