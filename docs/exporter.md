# x3d-castle-convert: a glb exporter on Castle's render arrays

`castle-convert/x3dcastleexport.pas` (about 2,500 lines of Pascal) replaces the work Castle's stock glTF writer does for
X3D to glb. It does not patch the engine: it links against the engine's public units and is built with
`castle-engine compile`.

## Why not patch the stock writer

The stock writer (`X3DLoadInternalGltf.SaveGLTF`) walks the *node graph by hand*. Each feature Castle resolves for
rendering (Inline, Switch, Transform center, per-corner normals, texture-coordinate generation, vertex colours, proxies)
would have to be re-implemented there. The exporter walks Castle's *shape tree* instead and takes each shape's
`TShape.GeometryArrays`, the same buffers Castle uploads to the GPU. What Castle draws is what ends up in the file.

## What one X3D shape becomes

* one glTF node (the shape's world matrix) with one mesh and one primitive: triangles, lines or points
* `POSITION`, `NORMAL` (normalised), `TEXCOORD_0` (V flipped to glTF's top-left origin), `COLOR_0`, `TANGENT` when Castle has them
* world matrices that glTF cannot hold as a node matrix (shear from nested non-uniform scale) are baked into the vertices
* materials: PhysicalMaterial to metallic-roughness; classic Material to metallic-roughness (roughness from shininess) plus
  `KHR_materials_specular`; no Material or UnlitMaterial to `KHR_materials_unlit`. The specular mapping has two rules, below.
* textures: PNG and JPEG are embedded byte for byte, other formats re-encoded to PNG; repeatS/T become sampler wrap;
  TextureTransform becomes `KHR_texture_transform`. A `TextureProperties` node becomes the sampler (boundary modes, minification and
  magnification filter). The `*TextureMapping` fields of X3D 4.0 (`diffuseTextureMapping`, `normalTextureMapping`, ...) pick the
  `TEXCOORD_n` set a map reads; each set a shape needs is written as its own attribute, and the material cache key includes the sets.
* PhysicalMaterial: emissive above 1 is split into `emissiveFactor` (at most 1) and `KHR_materials_emissive_strength`; an emissive texture keeps
  the emissive colour as its multiplier; a normal map on a shape that has no tangents gets `TANGENT` generated from the triangles
  (per-triangle dP/du and dP/dv, orthogonalised against the normal, handedness in w) so a viewer does not have to guess; `Appearance.alphaMode`
  (`BLEND` from `transparency`, `MASK` with `alphaCutoff`, `OPAQUE`) is written as glTF `alphaMode`, `solid=false` gives `doubleSided`; a PhysicalMaterial that only sets `baseColor` keeps it
  (see "Writer defects worked around", below).
* lights carry what glTF cannot hold as `extras.x3d` (see "Scene and light extras")
* scene level: bound Viewpoint (or the X3D default at 0 0 10) as a camera; lights as `KHR_lights_punctual`
  with intensities in glTF units (below); the X3D headlight as a directional light under the camera node
* `LOD` children are chosen from the Viewpoint position (Castle normally does this inside its render loop)

## Light units (why a glTF light is not the X3D number)

An X3D browser lights a classic Material as albedo * N.L * intensity, in display space, with no 1/d^2 (the attenuation
field defaults to 1 0 0). glTF viewers (Babylon.js, Blender, Unreal) divide Lambert by pi and fall off as 1/d^2.
The default mode (`--light-scale` unset, "AUTO") writes, with `level(x) = x` for a physical scene and
`pi * lin(min(a x, 1)) / lin(a)` for a classic one (a = median classic albedo; any PhysicalMaterial makes the scene physical):

* directional light and headlight: `level(i)`
* point and spot light: physical `i * attenuation(d)`; classic `level(i * attenuation(d)) * d^2`, where `d` is the median
  distance from the light to the lit shapes it reaches, and `attenuation(d) = 1 / max(c1 + c2 d + c3 d^2, 1)` (X3D 4.0, 17.2.2.3)
* the light's X3D `radius` becomes the glTF `range`

This is the same rule x3d-blender-io's importer applies (`finalize_light_units`), reached here from the render side, so
the two export paths agree. `--light-scale=F` switches to a plain multiplier. The scene's mode is in the sidecar JSON.

## Options that matter for fidelity work

* `--colour-space=srgb` (the default) converts classic (display-space) colours, vertex colours and unlit colours to linear, so a
  viewer's sRGB encode lands back on the authored value. PhysicalMaterial colours are linear already and are never converted.
  `--colour-space=as-is` keeps the numbers; on the village scene that moves the X_ITE difference from 3.5 to 48.8.
* Specular (`KHR_materials_specular`), two rules. (1) A black `specularColor`, which is the X3D default, becomes
  `specularFactor 0`. Without it glTF adds its own 4 % white sheen and a flat red square drew pink (lod-control: 0.1 with the
  extension, 4.6 without; p3: 0.3 against 1.0). (2) A coloured `specularColor` becomes `specularColorFactor = linear(color) / 0.04`
  so that F0 equals the authored colour, capped at `--specular-max-f0=F` (default 0.5). Uncapped (F0 up to 1, factor 25), Babylon.js
  9.32 shifted the hue: the gold cube in `annotation-standard` (diffuse 0.80 0.62 0.30, specular 1.0 0.88 0.6) came out teal.
  Measured on annotation-standard (mean difference from X_ITE 16.7.1, 0 to 255, Text skipped in every run): cap 0.04 gave 17.1,
  0.10 gave 17.6, 0.25 gave 17.6, 0.5 gave 17.9, uncapped 20.2; on five other scenes the caps moved the result by under 0.8. From
  0.5 the whole cube face takes an orange tint, where X_ITE has a small orange hotspot, so the default will probably move down to
  about 0.25 (the 0.5 default is what the published rig table used). Phase 3 re-measure on the 21 rig scenes (3 repeats, per-scene median, Babylon 9.32 against
  X_ITE 16.7.1): cap 0.25 against 0.5 moved annotation-standard 17.94 to 17.60 and repair-2-render 0.67 to 0.40, every other deterministic scene by under 0.1, mean 7.45
  against 7.80 (the mean is dominated by the rig's noise on villagers and materials-world, below). The default is left at 0.5; 0.25 is the recommendation.
  Babylon 9.32 only; other viewers have not been tried.
  `--no-phong-specular` omits the extension.
* `--text-quads` (off by default). Castle's Text proxy is a set of glyph-cell quads; the font atlas is drawn by the renderer,
  not carried in the arrays, so those quads read as solid bars. By default Text shapes are skipped, with a warning and a
  `text_shapes_skipped` count in the sidecar JSON. A text-to-mesh (or text-to-texture) step is the follow-up.
* `--no-headlight` leaves the headlight to the harness (the x3d-blender-io rig adds its own).
* `--engine-writer` runs Castle's stock writer for before/after comparisons.

## Scene and light extras

glTF has no slot for several X3D light and scene fields, so they are written as `extras` (ignored by viewers that do not know them, kept by
Blender and by anything that round-trips extras). Nothing here changes how a viewer draws the file.

* Light `extras.x3d`: `ambientIntensity`, `shadows`, `global`, `on`, `intensity` (as authored), `intensityIfOn`, and `scopeNodes` (glTF node indices
  of what a `global=false` light reaches, only when that is not the whole scene). A light with `on=false` is written with `intensity` 0, so a viewer
  does not light the scene with it, and `intensityIfOn` says what it would be.
* Spot lights: `cutOffAngle` becomes `outerConeAngle`, `beamWidth` becomes `innerConeAngle`, clamped so inner < outer. A `beamWidth` at or above the
  `cutOffAngle`, which X3D allows (it means "no falloff inside the cone"), made the glTF validator report `KHR_LIGHTS_PUNCTUAL_LIGHT_SPOT_ANGLES` before.
* Scene `extras.x3d`: the bound `Background` (sky and ground colours and angles), `Fog` (type, colour, visibility range) and `EnvironmentLight`
  (intensity and the diffuse and specular texture URLs). glTF has no background or fog; Babylon.js, for one, takes them from the page.
* `--scope-lights` (off by default): a `global=false` point or spot light gets its `range` clamped to the extent of its scope (the group it sits in),
  so the glTF light does not leak past where X3D lights. A directional light cannot be scoped in glTF; the sidecar JSON counts
  `lights_scoped_unscopable`.
* `--hidden-switch` (off by default): the unselected choices of a `Switch` are written too, each as a node with `KHR_node_visibility`
  `visible=false` (never listed as required), plus `extras.x3d.switch` / `choice` so a tool can flip them. Babylon.js 9.32 honours the extension;
  the Khronos validator 2.0.0-dev.3.10 does not know it and reports one INFO per file, no warning. Without the flag the file is as before.
* `--text-atlas` (off by default): `Text` becomes glyph quads textured with Castle's font atlas (`FontTextureNode`), alpha blended and double sided.
  The atlas is a bitmap, so type is blurry when magnified; a text-to-mesh step would be sharper. Without the flag Text is still skipped.
* `--events-at=T` (off by default, experimental): runs the scene's TimeSensor / interpolator events to T seconds and writes that state instead of
  the file as loaded. It follows routes into node fields only; a value that drives a shader uniform (the sky of `hyper-habsburg` is one) is not
  reached. Fixture: `tests/scenes-phase3/events-at.x3d`. It changes the output of several animated scenes, so look at them before relying on it. Example: `odyssey` authors all 74 lights
  at `intensity 0` and fades them in along a 138 s film, so its default glb draws near-black in Babylon.js 9.32 (mean 2.33 of 255) while X_ITE shows the lit gallery; with `--events-at=8` 8 of the
  74 lights are non-zero in the glb (`--events-at=1` and `3`: none; counted in the glb JSON, not rendered). Castle's scene time starts at 0 and X_ITE's page clock does not, so which
  T matches a given X_ITE frame is not known.

## Writer defects worked around

PasGLTF (the glTF library vendored inside Castle) has two defects that the exporter works around, both reproduced and drafted for the Castle
project in the held upstream pack (nothing sent), grade Confirmed:

* the sampler serialiser writes `wrapT` under the key `wrapS`. The exporter writes the `samplers` array itself in `WriteOut`. Before, the six dynasty
  "pocket" scenes that clamp T came out repeating T.
* `TPBRMetallicRoughness.GetEmpty` ignores `baseColorFactor`, so a PhysicalMaterial with default metallic and roughness (both 1 in X3D) and only a
  `baseColor` was written as `{}` (white). The exporter writes roughness 0.9999 in that case, which is below the visible threshold and forces the block.

## Output changes without a flag (no CLI option or default value changed)

These make the default glb more faithful or valid; none needs a flag and none changes how an option is read. In the 70 scenes the default glbs differ from phase 2 only
by these and by the added extras.

* sampler wrap, filters and `TextureProperties`; the T wrap is no longer lost (PasGLTF key bug)
* `TANGENT` generated for normal-mapped shapes without tangents (226 shapes in 2 scenes; the validator warnings go)
* a PhysicalMaterial with only `baseColor` keeps its colour; emissive above 1 uses `KHR_materials_emissive_strength`
* an emissive texture is multiplied by `emissiveColor`, black included (phase 2 forced white). Spec and X_ITE agree; odyssey's seven materials with an authored
  `emissiveColor 0 0 0` stop glowing. Chosen over the phase 2 look because the X3D text says so and the rig fixture drops from 32.06 to 2.87
* spot cone clamp (inner < outer), `on=false` lights at intensity 0 (none in the 70 scenes), NaN and Infinity in accessors written as 0 (none in the 70 default outputs)
* `extras.x3d` on lights and on the scene

## What phase 3 measured

Every number: Khronos glTF-Validator 2.0.0-dev.3.10 (npm `gltf-validator`) for validity; X_ITE 16.7.1 against Babylon.js 9.32.0 drawing each glb
(x3d-blender-io `tools/fidelity_rig`, Chromium 153.0.8010.12, SwiftShader, 512 x 512, mean absolute pixel difference 0 to 255, this container, 4 vCPU, no GPU).
Raw files: `results/phase3/`.

* Validity, 70 unique x3d.demo scenes: 0 errors before and after; warnings 226 (two normal-mapped scenes, odyssey 215 and materials 11, `MESH_PRIMITIVE_GENERATED_TANGENT_SPACE`) to 0; 70 of 70 clean
  (infos 77 both: unused-object notes). With `--text-atlas --hidden-switch --scope-lights` and with `--events-at=0.7` also 70 of 70 with 0 errors and 0 warnings
  (the hidden-switch run adds 22 INFOs, `KHR_node_visibility` not known to the validator).
* Census (same rules as phase 2): textures 11 of 17 (the other six draw their textures from shader-driven data, which glTF cannot carry), vertex colours 26 of 27,
  lights 41 of 43, cameras 55 of 55, lines 14 of 17, points 10 of 11, animation 0 of 21; unchanged by the default output. With `--hidden-switch` vertex colours
  27 of 27, lines 16 of 17, points 11 of 11 and 3,786 meshes against 1,946 (hall's hidden Switch choices and habsburg's frames).
* Rig, 21 scenes where every column exists, 3 repeats, per-scene median. Variant `self` (the glb carries camera and headlight): phase 2 binary mean 7.53, this
  branch 7.80. Variant `rigcam` (`--no-headlight`, the rig adds its headlight): 7.96 and 7.95. The default output is the same to within noise: 5 of the 21 glbs are
  byte-identical, the others differ by extras, extension lists and metadata, and no deterministic scene moves by more than 0.01. Two animated scenes move, materials-world
  (4.53 to 3.40, repeats 5.37 / 4.53 / 4.13 against 2.85 / 3.40 / 5.04, overlapping) and villagers (0.49, 7.93, 8.70 against 1.33, 0.52, 1.05), whose glb is byte-identical on both sides: it is the rig, whose animated scenes land on a different phase each run
  (an earlier pair of runs gave 5.51 and 0.37 on one glb). Excluding villagers the `self` mean is 7.85 before and 7.80 after. The median of the 21 is not a stable statistic
  here: it flips between about 0.5 and 3.49 (village) with the noisy scenes, so the published "median 3.5" is one state of a rig that gives 0.5 to 3.5; per-scene tables are in
  `results/phase3/rig-gate-summary.json`.
* Where the new code does show on the rig (fixtures, `results/phase3/rig-fixtures-summary.json`, 2 repeats, base = phase 2 binary): texture-properties 9.68 to 0.34
  (clamp instead of repeat), texcoord-sets 32.06 to 2.87 (the emissive fix and the second coordinate set), alpha-modes 5.06 to 1.92, light-extras 6.84 to 4.44
  (an `on=false` light no longer lights), switch-hidden 2.26 to 0.94. Opt-in flags: text-atlas 6.90 to 9.41 and habsburg-timeline 8.67 to 9.46 get *worse* by the pixel metric
  while the labels appear (X_ITE draws crisp vector-like type, the glb carries a bitmap atlas, so the glyph edges disagree more than an absent label does). annotation-standard
  stays at 17.94 either way. I chose labels present over the smaller number, and kept the flag off by default so the published table does not move.

## Not covered

Animation (the glTF has no animation channels; `--events-at` writes one frame), skinning, shaders (six of the 17 textured scenes draw their
textures from shader-driven data, which no glTF can hold), Billboard, GaussianSplats, cube and 3D textures, `DirectionalLight global=false` scoping
(recorded as extras, not enforced: a glTF light is global), Background and Fog (recorded as extras, not drawn), clearcoat / transmission / ior and
the other PBR extensions (X3D 4.0's `PhysicalMaterial` has no such fields, so there is nothing to carry),
image-based lighting (`EnvironmentLight` is recorded as extras; the validator 2.0.0-dev.3.10 does not support `EXT_lights_image_based`, so it is not written),
Text without `--text-atlas`, and Switch frames hidden at load without `--hidden-switch`.

Every run writes `OUT.glb.export.json` with counts and warnings, and `--verbose` prints one line per shape, light and image.
