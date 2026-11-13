# Castle quality leg: how close does each renderer get to a path-traced image?

Question: is Castle Game Engine the *quality* renderer of the X3D pipeline, and do its quality switches change that?
Yardstick: a Blender Cycles path-traced image of the same X3D file (not X_ITE), scored with FLIP. X_ITE is one of the legs.

Grades used everywhere: **Confirmed** = measured here with the data named; **Likely** = measured, the cause is inferred;
**Suspected** = read in source or inferred, not run. "Agree" means two renderers produce close images; it says nothing about which
of them is right or which influenced the other.

Everything below was measured with no GPU: Castle 7.0-alpha.3 snapshot (FPC 3.2.2) on Mesa llvmpipe (LLVM 20.1.2, GL 4.5), X_ITE 16.7.1
and Babylon.js 9.32.0 in Chromium 153 on SwiftShader, Blender 5.3.0 Cycles on the CPU. 512 x 512, one frame per leg, 4 shared vCPUs.
A GPU would change timings and may change MSAA and driver-dependent behaviour; it would not change a light model.
Tables are generated from `results/quality/public/results.json` by `tools/quality_tables.py` (see `docs/quality-tables.md`).

## 1. Method in one screen

| piece | what it is |
|---|---|
| reference | `tools/cycles_reference.py`: the x3d-blender-io add-on imports the X3D file, Cycles renders 256 spp (seed 0, a second seed for the spread), 12 bounces, no denoise, ideal point lights (radius 0), the job's camera, clear colour and headlight. Light units follow the add-on's default, which is calibrated to what X_ITE draws (so X_ITE-against-reference agreement on lit scenes is partly built in) |
| `xite` | X_ITE 16.7.1 on the X3D file, via the existing `fidelity_rig` |
| `babylon_addon` | Babylon.js 9.32.0 on the add-on's glb (shares the add-on's reading of the file with the reference: **not independent** of it) |
| `babylon_castle` | Babylon.js on the glb that our Castle exporter writes (an independent reading of the file) |
| `castle_native` | `castle-render`, our harness around the engine: X3D loaded and drawn by Castle itself, default settings |
| `castle_*` | the same, one quality switch at a time (shadows, SSAO, SSR, three tone maps, three shading modes, colour space, IBL, MSAA, SSAA, anisotropy), then `castle_all` (SSAA 4x + Gouraud, **chosen on these same scenes**, so in-sample) |
| scenes | 15 public scenes of x3d.demo and the fidelity rig: two still lifes, materials-world, lights-after, village, earth-planet, annotation-standard, nurbs-weights, quaternion-xyzw, repair-2-render and five light probes (p1..p5) |
| metric | **F** = mean FLIP (LDR, 67 ppd, flip-evaluator 1.7) against the reference, whole frame, lower is better. **E** = F after one linear-light exposure scalar (secondary, see section 5) |

The reference is "Cycles on the add-on's reading of the file", not truth. Where the add-on drops a node (NurbsCurve, GaussianSplats),
flattens a gradient Background to one colour or ignores a light's attenuation field, the reference does too. Four scenes are affected
so much that the headline is also given without them (**core 11** = 15 minus annotation-standard, nurbs-weights, quaternion-xyzw,
p2-point-classic).

## 2. Result

| leg | mean F, all 15 | mean F, core 11 |
|---|---:|---:|
| X_ITE 16.7.1 | 0.0748 | 0.0457 |
| Babylon on the add-on glb | 0.0516 | 0.0485 |
| Babylon on our Castle glb | 0.0658 | 0.0491 |
| Castle native | 0.1321 | 0.1149 |
| Castle all levers | 0.1289 | 0.1146 |

Paired bootstrap over scenes (5000 resamples; scenes are not independent, so the intervals are indicative):

* **Confirmed:** X_ITE, the add-on route and our Castle route are not separable on the core 11: their differences are +0.003 or
  less with intervals that span zero (add-on minus X_ITE +0.0027 [-0.0072, +0.0149]; Castle glb minus X_ITE +0.0033 [-0.0069, +0.0165]).
  On all 15 the add-on route is ahead of X_ITE by 0.023 [-0.053, +0.001], which comes from scenes where the reference and the add-on
  share an omission or a flattened Background (section 4), not from better shading.
* **Confirmed:** Castle native is behind the other three by +0.069 F on the core 11 (against X_ITE [+0.007, +0.164], won 4 scenes,
  lost 7), and the gap is carried by four scenes (section 3). On the other 7 core scenes (both still lifes, village, earth-planet, p3, p5,
  repair-2-render; mean computed from the table) Castle is within 0.005 of the others: F 0.041 against 0.039 for X_ITE and 0.035 for the
  add-on route.
* **Confirmed:** the whole menu of Castle quality switches is worth less than the gap: the best single switch changes mean F by
  -0.0027 (section 6).

* **Confirmed (second full run):** a second run of all 15 scenes with the same tools (since edited only to remove local paths) reproduced the 60 reference pictures pixel for pixel and every F within 0.0002 (318 leg-by-scene values); the one value that moved, X_ITE on materials-world (0.1123 to 0.1121), is the wall-clock effect in section 5. The tables here and `quality-tables.md` are from that second run.

## 3. Why Castle native is behind: its light model, not its rasteriser

Castle uses the file's `attenuation` field as written, for classic and physical materials alike. The reference, X_ITE (for
PhysicalMaterial) and Babylon (through the add-on's or our glb) apply 1/d^2 to physical lights. The Castle scout read X3D 4.0 section 17.2.2.6
as attenuation-only (Likely), so this is an engine difference, not a Castle error; but it decides the picture.

Single-factor experiments on scratch copies of the scene (Castle re-rendered, one input changed, everything else equal):

| scene | what changed | Castle F before | after | X_ITE F |
|---|---|---:|---:|---:|
| materials-world | three spot intensities 30, 7, 26 set to 1 | 0.5956 | 0.1275 | 0.1121 |
| p1-point-physical | attenuation `1 0 0` to `0 0 1` (inverse square) | 0.0546 | 0.0059 | 0.0053 |
| p4-point-quadratic-physical | attenuation `1 0 0.2` to `0 0 1` | 0.0446 | 0.0237 | 0.0085 |
| repair-2-render | PointLight intensity 10 set to 1 | 0.0044 | 0.0026 | 0.0071 |
| lights-after | point light removed | 0.2852 | 0.1481 | 0.1068 |

* **Confirmed (the experiments reproduce; a skeptic re-ran them):** on materials-world, lights-after, p1 and p4 the brightness is a
  light-model effect: Castle is 8x, 1.4x, 4x and 3.6x too bright there (exposure scale 0.123, 0.712, 0.253, 0.277 against the reference).
  materials-world and lights-after alone carry 77% of the mean F gap between Castle native and X_ITE.
* **Not shown:** that Castle's *shading* quality equals X_ITE's once lit the same way. The edits are hand-picked (the lights-after one
  deletes a light the reference has, the materials-world one flattens three different intensities to 1), and on plain F edited Castle stays
  behind X_ITE on materials-world (0.1275 vs 0.1121), lights-after (0.1481 vs 0.1068) and p4 (0.0237 vs 0.0085); only p1 and repair-2-render
  come out level or ahead. On E materials-world and lights-after look level, but E has an exposure degree of freedom (section 5).
  A pipeline lever that applies inverse-square falloff to PhysicalMaterial scenes would test this honestly; it is the next step.
* **Likely:** p2-point-classic is the same story for a classic Material: Castle lights it in display space with no falloff, as X_ITE does
  (their F against each other is 0.016), while the add-on/Cycles path applies Blender's 1/d^2. Swapping Material for PhysicalMaterial in a
  copy gives box luminance ratios 0.197 against the reference's 0.176.
* Castle has no exposure setting (`u_Exposure` is commented out in `tone_mapping.fs`); `castle-render --exposure` adds one as a scene-wide
  Effect node.

## 4. Where the reference and the number disagree with the eye

* **Confirmed:** the reference clears to one colour; X_ITE and Castle draw the file's gradient Background. Over the 15 scenes 0.0217
  (X_ITE) and 0.0228 (Castle native) of mean F lies outside the reference's object footprint, against 0.0005 and 0.0012 for the two Babylon
  legs. On annotation-standard that is 52% of X_ITE's F, on nurbs-weights 71%.
* **Confirmed:** nurbs-weights: the add-on logs `unsupported type NurbsCurve`, so the reference has no curves and the add-on route "wins"
  (F 0.0338) by also omitting them. quaternion-xyzw uses `GaussianSplats` (X3D 4.1 draft): Castle logs `Unknown X3D node type` and draws an
  empty disc, X_ITE draws the medallion; plain F ranks the near-empty add-on frame (F 0.1548) ahead of X_ITE's correct picture (0.1962).
  FLIP rewards leaving content out when the reference leaves it out too.
* **Confirmed:** earth-planet at 3x zoom: X_ITE matches the reference best, Babylon and Castle look thinner and more aliased, yet FLIP
  ranks Castle first (0.0023). The object is 5% of the frame, so frame-level F is tiny; read `flip_mean_geometry` there.
* **Confirmed:** both still lifes: the four legs are within 0.003 of each other (all inside the scene's own 0.006-0.008 reference spread).
  The shared residual (F 0.085-0.095) is the metallic sphere and torus rim, which Cycles shows reflecting the rest of the scene and no
  rasteriser does. Global illumination explains about 0.02 of it; the rest is shared and unexplained (against the no-bounce reference
  Castle's F is still 0.064).
* **Confirmed:** village: the reference and the add-on route read 6-9 codes lighter on the lower floor rows than X_ITE and Castle, which
  agree with each other to under 1/255. The scene is unlit, so a headlight is not the cause (switching it changes no pixel). Cause not
  isolated; vertex-colour interpolation space is the candidate (Suspected).
* **Likely:** repair-2-render: X_ITE shows the planets elsewhere than every other leg. Its TimeSensors run during the rig's wait; the other
  legs draw time 0. materials-world has the same effect: X_ITE F moves between 0.097 and 0.113 as the wait goes 10 s to 0.3 s.

## 5. Metric cautions

* F rewards a dark, near-empty frame over a correct picture (quaternion-xyzw). E divides out brightness, so it cannot undo clipping
  (materials-world: Castle E 0.2852) and hides wrong shapes (p1: Castle E 0.0193 against F 0.0546 while the boxes are 2.8x, 3.6x and 16x too
  bright). E's mask is built per pair, so with different skies it is **not comparable across legs** in 3-5 scenes (nurbs Castle E 0.1613 becomes
  0.2164 under a common footprint mask); quaternion-xyzw supplies 48% of the Castle-minus-X_ITE gap in E and its E is unusable (exposure
  scale 3.3). For these reasons this document leads with F and treats E as secondary.
* The seed-to-seed spread of the reference (FLIP between two Cycles seeds: mean 0.0034, up to 0.0107) is **not the error bar of a
  leg-against-leg comparison**: re-scoring every leg against the other seed and a 512 spp average moves any leg by at most 0.00014 (0.0019
  for the average) and never changes a leg order. The ties in the still lifes come from the shared systematic residual above.
* The reference is not independent of X_ITE on light units (the add-on's default mode is calibrated to X_ITE), and `babylon_addon` is not
  independent of the reference at all.
* The public run's X_ITE leg waits a fixed time, so it is wall-clock dependent in animated scenes.

## 6. Castle's quality switches, one at a time

Change in mean F against `castle_native` over the scenes where both rendered (negative = closer to the reference). Full table, including
the core 11 and the shadow columns, in `docs/quality-tables.md`; per-scene tables and the source reading in `docs/quality-levers.md`.

| switch | mean F change | reading |
|---|---:|---|
| SSAA 4x / 2x, MSAA 4x | -0.0027 / -0.0018 / -0.0003 | the only family that never hurts; smooth silhouettes and thin lines (SSAA also shrinks Castle's constant-width GL curves to a quarter, which the NURBS reference-less scene counts as a gain: **not** a quality gain there). 5 of 15 scenes improve, none worsens. +20 to +95 ms on llvmpipe. The SSAA and the FBO MSAA are our harness's constructs, not the engine's window anti-aliasing (default none) |
| anisotropy 16 | -0.0001 | free on llvmpipe, no grazing textured plane in the suite to show it |
| Gouraud shading | -0.0004 | changes pixels only in classic-Material scenes; Phong (the default) is bit-identical to native |
| shadow maps | +0.0040 against the file-literal reference; **-0.0106** against a reference where every light casts (-0.0124 at 2048) | the one switch with a large effect, and its sign depends on the reference. X3D `shadows` defaults to false, so the file-literal image has shadows in only 3 of the 15 scenes. One orthographic map per directional light fitted to the casters, default 256 px, no point-light shadows (4 of the 6 scenes with no directional/spot light have a point light, 2 have no light at all). 4096 equals 2048. A still render needs the engine's update step first, otherwise no shadow map is ever made |
| SSAO | +0.0065 | self-occlusion band on the village ground (the flat plane darkens by up to 20% in a depth-dependent band); hard-coded near/far 1 and 1000 in the viewport (Suspected) |
| SSR | +0.0002 | ghost reflections with one fixed glossiness for every pixel |
| tone map ACES / Hejl / Uncharted | +0.035 / +0.023 / +0.025 | global curves, applied to unlit vertex-colour scenes too (village is the worst scene for all three) |
| colour space linear / sRGB | +0.112 / +0.044 | the engine default (linear for PhysicalMaterial only) is the right one for this suite |
| PBR mapping of classic Material | +0.0079 | our mapping, not an engine feature; dulls speculars |
| EnvironmentLight (IBL) | +0.0437 | the engine's implementation is flagged unfinished (one cube-map lookup with the normal, no integration, no roughness); our synthetic sky does not match the reference world either. **Not a measurement of proper IBL** |
| `castle_all` (SSAA 4x + Gouraud) | -0.0032 [-0.0085, -0.0002], 12 of 15 scenes | about one reference-spread unit; chosen in-sample |

* **Confirmed:** no single switch moves mean F materially: the best, SSAA 4x, is -0.0027 (-0.0003 on the core 11; -0.0005 without nurbs-weights,
  which supplies -0.0023 of it by thinning curves the reference does not have). Every *improving* switch is inside the reference spread (0.0034); the harmful ones (tone maps, colour-space overrides,
  IBL, SSAO, PBR mapping) are not.
* **Likely:** a default `castle-model-viewer` user gets the lowest setting of each switch (Phong per fragment, no tone map, anti-aliasing off,
  anisotropy off, SSAO/SSR off, shadow maps only where the file asks, at 256 px).
* Recommendation (Likely): turn on anti-aliasing (4x MSAA in a real GPU window, 2-4x SSAA offline), 16x anisotropy, and shadow maps at 2048 where the scene
  intends shadows or the target is the physically plausible image. Leave off SSAO, SSR, tone mapping, colour-space overrides, the
  engine's EnvironmentLight, Gouraud and the PBR mapping.

## 7. What this says about the pipeline

1. Castle is **not** the quality renderer of the pipeline on this evidence: its switches are worth about a reference-spread unit and its gap is
   a light model. It is a fast (about 0.5 s a frame here, against 3-6 s for the browser legs and 47 s for a 256 spp reference), standalone,
   scriptable reader of X3D that can write a glb. As an independent reading of the file it shows where the add-on route drops content (the
   gradient Background, NurbsCurve) and where Castle itself has no node (GaussianSplats).
2. The reference is the lever: the whole "ranking" moves when the reference's Background, light model or node coverage changes. A path-traced
   yardstick needs a stated convention per scene (ambient, Background, shadows, attenuation); `--extra-refs direct,shadows` exists for that.
3. **Next (not done):** a `castle-render` lever that applies inverse-square falloff to physical lights, run on all 15 scenes, would turn section 3's
   hand-edited experiments into a pipeline result; an exposure lever; text-to-mesh and animation in the exporter.

## 8. Reproduce

    python3 tools/run_quality.py --extra-refs direct,shadows        # public set, about 40 min, resumable
    python3 tools/quality_tables.py results/quality/public/results.json > docs/quality-tables.md

`results.json` records the tools' hashes, the versions of every renderer and the add-on commit. See `docs/reproduce.md` and `docker/README.md`.
