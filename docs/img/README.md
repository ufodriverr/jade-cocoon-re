# Images

Rendered from the models in this repo by the viewer in [`../../viewer/`](../../viewer),
not captured from the game. Nothing here needs a disc.

- `gallery.png` - eight models from `models/current/`, each posed on its own longest
  animation clip, three-quarter front view. The front of a model is at yaw pi; yaw 0 shows
  its back.
- `merge_sweep.png` - the five `sweep_833x867_*` files from `models/merged/`, all on the
  same rig, the same clip and the same frame, with the camera locked to the union of all
  five bounding boxes. Only the geometry changes across the row.
- `merge_studio_age.png` - one merged creature (Arpatron x Skawasp) at levels 1, 7, 13, 22
  and 40, captured from the live `tools/merge_studio.py` with the camera held still so the
  size change is real. This one DOES need a disc, because the growth stages only exist in
  the live tool; the exported models are all adults.

To regenerate: serve the repo root, open `/viewer/`, and drive the page from the browser
console. Select a model, pose it, set `S.cam`, call `draw()`, then copy the WebGL canvas
into a 2D canvas tile with `drawImage`. The viewer keeps `preserveDrawingBuffer: true`
precisely so the canvas can be read back after a draw.
