# x3d-castle-convert: a glb exporter on Castle's render arrays

`castle-convert/x3dcastleexport.pas` (about 1,400 lines of Pascal) replaces the work Castle's stock glTF writer does for
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
  TextureTransform becomes `KHR_texture_transform`
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
  about 0.25 (the 0.5 default is what the published rig table used). Babylon 9.32 only; other viewers have not been tried.
  `--no-phong-specular` omits the extension.
* `--text-quads` (off by default). Castle's Text proxy is a set of glyph-cell quads; the font atlas is drawn by the renderer,
  not carried in the arrays, so those quads read as solid bars. By default Text shapes are skipped, with a warning and a
  `text_shapes_skipped` count in the sidecar JSON. A text-to-mesh (or text-to-texture) step is the follow-up.
* `--no-headlight` leaves the headlight to the harness (the x3d-blender-io rig adds its own).
* `--engine-writer` runs Castle's stock writer for before/after comparisons.

## Not covered

Animation, skinning, shaders, Text (skipped, above), Billboard, GaussianSplats, Background and Fog, cube and 3D textures, texture-coordinate
sets above 0, `DirectionalLight global=false` scoping (glTF lights are global; the log says when it matters),
Switch children hidden at load (a frame-sequence Switch with `whichChoice=-1` exports nothing).

Every run writes `OUT.glb.export.json` with counts and warnings, and `--verbose` prints one line per shape, light and image.
