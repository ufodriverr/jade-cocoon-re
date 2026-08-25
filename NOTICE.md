# Notice

## What this project is

A non-commercial reverse-engineering and preservation study of **Jade Cocoon: Story of the
Tamamayu** (PS1, 1998). Nothing here is sold, monetised, or served from anywhere but this
repository. The point is documentation: how the game's files are laid out, and how its
merge mechanic actually computes a new creature.

## Who owns what

- **Jade Cocoon: Story of the Tamamayu** is copyright Genki Co., Ltd., with character
  designs by Katsuya Kondo / Studio Ghibli, and was published by Crave Entertainment and
  Ubi Soft. This project is not affiliated with, endorsed by, or connected to any of them.
- **The code and documentation in this repository** (`tools/`, `docs/`, `viewer/`, this
  file, the README) are original work by the contributors, released under the MIT licence
  in [LICENSE](LICENSE).
- **The files under `models/`** are converted from the game's data. They are Genki's
  copyrighted assets in a different container. The MIT licence does **not** cover them, and
  no licence to them is granted or implied by this repository.

## What is deliberately not here

- No disc image, and no instructions or links for obtaining one.
- No game executable (`SLES_022.01`) and no part of it.
- No decompiled or disassembled game code. The Ghidra project and the decompiler output
  that this research was built on are excluded on purpose, because decompiler output is a
  mechanical translation of Genki's code. What they taught us is written up in `docs/` in
  our own words, alongside bare function addresses, which are facts about the binary rather
  than a copy of it.

The tools operate on a disc image you supply yourself. They do not download anything, and
they do not contain any game data.

## On the extracted models

They are included so that people can look at, study and preserve this game's art without
each needing to redo the format work. That is a preservation argument, not a legal one. We
are not claiming it is fair use, and non-commercial intent is not a defence in itself.

Under `models/` you will find only character and creature meshes with their textures and
animations. No music, no voice, no video, no text, no code.

## Takedown

If you hold rights in Jade Cocoon and want any part of this repository removed, open an
issue or contact the repository owner directly. It will be taken down promptly and without
argument. No notice, no lawyer and no formal process is required.

## If you fork this

If you republish the `models/` directory somewhere else, that is your call and your risk,
not ours. If you build on the tools and documentation, the MIT licence covers you and a
credit is appreciated. Please do not remove this notice from a fork that still ships the
assets.
