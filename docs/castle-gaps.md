# Castle gaps found while scouting

Grades: **Confirmed** = reproduced here and the log is in `results/`. **Likely** = strong evidence, one step short.
**Suspected** = read in the source, not reproduced. Nothing here has been reported to the Castle project.

| # | gap | grade | how it shows | workaround here |
|---|---|---|---|---|
| 1 | No `GaussianSplats` node (X3D 4.1) | Confirmed | `Unknown X3D node type "GaussianSplats"`; 5 of 70 demo scenes export zero meshes | none; splats need a different path |
| 2 | GLSL ES `#version 300 es` shaders fail | Confirmed | Castle writes its `#define`s above the `#version` line | none yet; port the shaders |
| 3 | WebP textures cannot be decoded | Confirmed | `Unrecognized image MIME type`; the six dynasty "pocket" scenes lose their portraits | `tools/webp_prepass.py` converts to PNG in a copy |
| 4 | `GetPerspectiveViewpoint` raises `EAbstractError` on a scene with `GeoViewpoint` | Confirmed | ellipsoid-earth, ellipsoid-moon | exporter catches it and writes the X3D default camera |
| 5 | `GeoElevationGrid` draws nothing; `GeoLOD` children produce no shapes | Confirmed | 0 shapes for ellipsoid-*, geolod-* | none |
| 6 | Viewer fits the camera without a Viewpoint and clears to 26/255 grey without a Background | Confirmed | differs from the X3D defaults (0 0 10, black) | `--spec-defaults` copies |
| 7 | `--anti-alias` changes nothing under Xvfb + llvmpipe | Confirmed | PNG hashes identical for levels 0 to 6 | not a quality result: that rig has no multisample visuals |
| 8 | Stock glTF writer keeps geometry and material factors only | Confirmed | lights, cameras, textures, vertex colours, Inline all dropped | `castle-convert/x3dcastleexport.pas` |
| 9 | Stock writer: `Inline` not followed (stilllife-stage writes an empty glb) | Confirmed | 0 meshes | same |
| 10 | Stock writer: `GltfNode.Mesh := Meshes.Count - 1` after a Shape that added no mesh points at the previous shape's mesh | Suspected | source, `x3dloadinternalgltf.pas` `ProcessChildNode` | exporter does not share the code path |
| 11 | Stock writer: Transform `center` / `scaleOrientation` ignored; IndexedFaceSet `normalIndex` / `texCoordIndex` ignored; texture V not flipped | Suspected | source | exporter takes world matrices and render arrays from the shape tree |
| 12 | `ElevationGrid` with no `height` field gives no geometry (manifold-webgpu `Veil`) | Suspected | 0 vertices | unknown whether X_ITE draws a flat plane |
| 13 | `Text` reaches `TShape.GeometryArrays` as untextured glyph-cell quads; the font atlas is applied only by the renderer | Confirmed | annotation-standard: the labels export as solid bars; 111 Text shapes in 14 of the 70 scenes | exporter skips Text and says so (`--text-quads` keeps the bars); a text-to-mesh step is the follow-up |
| 14 | (x3d.demo, not Castle) `gobbler-worlds-within/v1/source/bird.x3d` uses `url="data/worlds/glow.png"`, which resolves under `source/`; the file is at `v1/data/worlds/glow.png` | Confirmed | `texture failed to load: ImageTexture`; `source/data/` does not exist | none needed; the url wants `../data/worlds/glow.png` (X_ITE resolves relative to the page, so check there before changing it) |

## What Castle already does well (measured)

* Native render of the PBR still life is 0.5/255 from X_ITE 16.7.1 (mean absolute pixel difference, 512 px).
* Colour rules equal X_ITE's by pixel: classic Material 0.5 gives 128, PhysicalMaterial emissive 0.5 gives 186.
* Defaults equal X_ITE's: no tone mapping, linear lighting when a PhysicalMaterial is used.
* Shadow maps work with `shadows="true"` on a light.
* Physical point lights are about 1.8x brighter than X_ITE 16.7.1 because Castle applies no 1/d^2 falloff; the X3D 4.0
  text (clause 17.2.2.3 / 17.2.2.6) applies the attenuation field, default (1 0 0) = none, to both material kinds.
