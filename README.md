# x3d.castle

Castle Game Engine, scouted and wired into an X3D pipeline: X3D, then a validator, then X_ITE, Babylon.js, Blender, glb and (later) Unreal.
Independent work. It is not affiliated with or endorsed by the Castle Game Engine project; Castle is theirs and is credited here
for every capability it shows. Nothing in this repo has been sent to the Castle project.

Goal, in the owner's words: the highest-quality graphics, not only the closest match to what X_ITE draws. X_ITE stays a reference
the way a good proof copy does; it is not the only measure.

## What is here

| path | what |
|---|---|
| `castle-convert/x3dcastleexport.pas` | the shape-tree exporter: X3D to glb from Castle's own render arrays (about 1,700 lines of Pascal, links against Castle, builds in 2 s warm) |
| `castle-convert/x3d_castle_convert.dpr` | command line: `x3d-castle-convert in.x3d out.glb [options]` |
| `castle-render/` | `castle-render`: our render harness around the engine, with every quality switch (shadows, SSAO, SSR, tone maps, shading, colour space, IBL, MSAA/SSAA, anisotropy, exposure) on a command line |
| `tools/` | harness: headless Castle renders, census, Khronos validator run, rig comparison (`exporter_compare.py`), WebP prepass, contact sheets; the quality leg: `cycles_reference.py` (path-traced reference), `quality_metrics.py` (FLIP, SSIM), `run_quality.py` (every leg of every scene), `quality_tables.py` |
| `docker/` | Dockerfile and smoke test for the whole toolchain (not yet built in CI, see `docker/README.md`) |
| `docs/quality-leg.md` | **the quality leg**: Castle and the other renderers against a Cycles path-traced image, what Castle's quality switches are worth, where the gap comes from |
| `docs/quality-levers.md`, `docs/quality-tables.md` | per-switch, per-scene detail and the generated tables |
| `docs/exporter.md` | what one X3D shape becomes, the options, the light-unit and specular rules, what is not covered |
| `docs/castle-gaps.md` | the gaps found in Castle, each graded Confirmed / Likely / Suspected |
| `docs/reproduce.md` | versions, commands and the hardware every number came from |
| `results/` | the JSON and logs behind every number; `screens/` the contact sheets and per-scene montages |

## Headline results (software rendering only, no GPU; see `docs/reproduce.md` for versions)

* Castle 7.0-alpha.3 snapshot, castle-model-viewer 5.3.0, FPC 3.2.2; renders under Xvfb + Mesa llvmpipe.
* Scenes: the 70 unique x3d.demo `.x3d` files. All 70 convert, none crash.
* Castle's stock X3D to glb writer keeps geometry and material factors only. 0 of 43 lit scenes keep their lights; 24 of 70 glbs
  fail the Khronos validator (14,379 errors in all).
* The shape-tree exporter: 70 of 70 glbs pass Khronos glTF-Validator 2.0.0-dev.3.10 with 0 errors and 0 warnings (phase 2: 0 errors, 226 warnings in 2 scenes). Lights kept in 41 of 43
  scenes, cameras 55 of 55, vertex colours 26 of 27, textures 11 of 17 (the other six are shader-driven), line sets 14 of 17, point sets 10 of 11. Animation 0 of 21.
  Phase 3 added texture samplers and `TextureProperties`, texture-coordinate sets, emissive strength, generated tangents, light and scene extras, and four opt-in flags
  (`--text-atlas`, `--hidden-switch`, `--scope-lights`, `--events-at`); with the first three the census reads vertex colours 27 of 27, lines 16 of 17, points 11 of 11, still 70 of 70 clean.
* Against X_ITE 16.7.1, drawn by Babylon.js 9.32.0 from each glb (x3d-blender-io `tools/fidelity_rig`, Chromium 153 SwiftShader, 512 x 512, mean absolute pixel
  difference 0 to 255), over the 21 scenes where every column exists, 3 repeats and per-scene medians: exporter 7.80 on variant `self` (phase 2 binary on the same rig, same day: 7.53) and 7.95 on
  `rigcam` (7.96); published in phase 2 as 7.8 (median 3.5), add-on glb 9.2 (3.6), Castle stock glb 17.6 (17.1). The rig is noisy on animated scenes (one glb gave 0.4 and 8.7 on
  two runs), the median of the 21 flips between about 0.5 and 3.5 with it, and the default output of the 21 scenes did not move on any deterministic scene: phase 3 is a
  fidelity-of-content change (what the glb carries), not a pixel-difference change on this scene set. The new code shows on the fixtures instead (`docs/exporter.md`): for example texture clamp 9.68 to 0.34,
  texture-coordinate sets 32.06 to 2.87.
* **Quality leg** (path-traced Cycles reference, FLIP, 15 public scenes; `docs/quality-leg.md`): X_ITE, Babylon.js on the add-on glb and Babylon.js
  on our Castle glb are not separable on the core 11 scenes (mean FLIP 0.046 / 0.049 / 0.049); Castle's own native render is behind at 0.115, and the
  gap is carried by four scenes where Castle applies a light's `attenuation` as written and the others apply 1/d^2 to physical lights. The best
  single Castle quality switch (4x supersampling) changes mean FLIP by -0.003; tone maps, colour-space overrides, SSAO, SSR and the engine's
  unfinished IBL make it worse; shadow maps are the one big switch and their sign depends on the reference. So on this evidence Castle is a fast,
  scriptable second reader of X3D, not the quality renderer.
* Not measured: any physical GPU, any viewer other than Babylon.js for the exporter's glbs, Unreal.

## Known gaps in the exporter

Animation (one frame with `--events-at`, none by default), `GaussianSplats` (Castle has no node), Geo nodes, shader-driven textures (6 of 17 textured scenes),
`DirectionalLight` group scoping and Background / Fog (recorded as `extras`, not drawn by a viewer), Text and Switch frames hidden at load (opt-in flags, bitmap type is blurry),
image-based lighting (`EnvironmentLight` is recorded as extras, `EXT_lights_image_based` is not in the validator). odyssey draws near-black in Babylon.js by default because its lights start at
intensity 0 and are animated.
Details and grades in `docs/exporter.md` and `docs/castle-gaps.md`.

## Rules this repo follows

Every number names its source (tool, version, renderer). Claims are graded Confirmed, Likely or Suspected. Demo scenes are read in
place and never modified; patched copies are made beside them. Nothing is reported upstream until the owner says to.

## Licence

MIT (see `LICENSE`). The exporter and `castle-render` link against Castle Game Engine (engine core: LGPL with a static linking exception, per its
COPYING.md) and its bundled PasGLTF (zlib licence); check those terms before distributing a built binary. `tools/cycles_reference.py` adapts about ten lines of Viewpoint matrix maths from `x3d-blender-io/tools/fidelity_rig/compare.py` (same
owner; the add-on is GPL-3, so the owner decides how that one file is licensed). Apart from that no Castle, X_ITE, Babylon.js or add-on source is copied here.
