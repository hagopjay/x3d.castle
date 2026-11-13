# Castle gaps found while scouting

Grades: **Confirmed** = reproduced here and the log is in `results/`. **Likely** = strong evidence, one step short.
**Suspected** = read in the source, not reproduced. Nothing here has been reported to the Castle project.

| # | gap | grade | how it shows | workaround here |
|---|---|---|---|---|
| 1 | No `GaussianSplats` node (X3D 4.1) | Confirmed | `Unknown X3D node type "GaussianSplats"`; 5 of 70 demo scenes export zero meshes | none; splats need a different path |
| 2 | Explicit `#version` (GLSL ES `#version 300 es`, also `330` and `330 core`) in a ComposedShader fails | Confirmed | `TShader.Define` inserts `#define ...` lines at the start of the user's source, above the `#version` line; the GLSL compiler then rejects it ("#version must appear on the first line"). The shape is drawn with the fallback shader. Reproduced with a 12-line scene and with the unmodified x3d.demo gobbler3 (5 shapes) | none yet; port the shaders. Draft report prepared, not sent |
| 3 | WebP textures cannot be decoded | Confirmed | `Unrecognized image MIME type`; the six dynasty "pocket" scenes lose their portraits | `tools/webp_prepass.py` converts to PNG in a copy |
| 4 | `GetViewpoint` / `GetPerspectiveViewpoint` raise `EAbstractError` on a scene whose first viewpoint is a `GeoViewpoint` | Confirmed | `TGeoViewpointNode` does not override the abstract class function `TAbstractViewpointNode.ProjectionType` (release and debug builds, exit 217). A 3-line override tried on a copy of the source removes it | exporter catches it and writes the X3D default camera. Draft report prepared, not sent |
| 5 | `GeoElevationGrid` draws nothing; `GeoLOD` children produce no shapes | Confirmed | 0 shapes for ellipsoid-*, geolod-* | none |
| 6 | Viewer fits the camera without a Viewpoint and clears to 26/255 grey without a Background | Confirmed | differs from the X3D defaults (0 0 10, black) | `--spec-defaults` copies |
| 7 | `--anti-alias` changes nothing under Xvfb + llvmpipe | Confirmed | PNG hashes identical for levels 0 to 6 | not a quality result: that rig has no multisample visuals |
| 8 | Stock glTF writer keeps geometry and material factors only | Confirmed | lights, cameras, textures, vertex colours, Inline all dropped | `castle-convert/x3dcastleexport.pas` |
| 9 | Stock writer: `Inline` not followed (stilllife-stage writes an empty glb) | Confirmed | 0 meshes | same |
| 10 | Stock writer: a Shape that yields no mesh (line sets, point sets, Text, empty Shape, several others) gets the previous shape's mesh index | Confirmed | glb has phantom triangle copies where X3D has none; Castle's own loader reads 2 shapes from the X3D and 3 from the glb | exporter does not share the code path. Draft report prepared, not sent |
| 11 | Stock writer: Transform `center` and `scaleOrientation` ignored; IndexedFaceSet `normalIndex` / `texCoordIndex` ignored (the glTF validator rejects unequal accessor counts); Inline not followed | Confirmed | bounding boxes of the X3D and the glb differ; checked against an independent implementation of the X3D matrix. Texture V flip is an open question (textures are not written at all) | exporter takes world matrices and render arrays from the shape tree. Draft report prepared, not sent |
| 12 | `ElevationGrid` with no `height`, or fewer than `xDimension * zDimension` heights, gives no geometry (`TElevationGridNode.ClassIsNotEmpty`) | Confirmed | 0 vertices and 0 pixels; X_ITE 16.7.1 draws a flat grid (missing heights = 0). The source does this on purpose and the X3D text says nothing on a short list, so it is an interoperability gap, not a spec violation | none needed in the exporter (the render arrays are empty). Draft prepared as an enhancement request, not sent |
| 13 | `Text` reaches `TShape.GeometryArrays` as untextured glyph-cell quads; the font atlas is applied only by the renderer | Confirmed | annotation-standard: the labels export as solid bars; 111 Text shapes in 14 of the 70 scenes | exporter skips Text and says so (`--text-quads` keeps the bars); a text-to-mesh step is the follow-up |
| 14 | (x3d.demo, not Castle) `gobbler-worlds-within/v1/source/bird.x3d` uses `url="data/worlds/glow.png"`, which resolves under `source/`; the file is at `v1/data/worlds/glow.png` | Confirmed | `texture failed to load: ImageTexture`; `source/data/` does not exist | none needed; the url wants `../data/worlds/glow.png` (X_ITE resolves relative to the page, so check there before changing it) |
| 15 | Explicit image format: `.webp` (and `image/webp`) is not recognised | Confirmed | `Unrecognized image MIME type`; the texture loads lazily, so `--validate` exits 0 and the shape renders untextured. No WebP unit exists in the engine or the bundled Vampyre library; the maintainer said in a 2023 forum thread that lossy WebP is not supported (as read from a search summary, Likely) | `tools/webp_prepass.py`. A feature request or a docs line, not a defect |
| 16 | `Background` with one `groundColor` and no `groundAngle`: Castle draws the sky colour below the horizon, X_ITE draws the ground colour | Confirmed (behaviour, on a 10-line synthetic scene) | the X3D text on a single ground colour was not checked, so the grade of "bug" is Suspected | none; the reference of the quality leg clears to one colour, so it cannot judge this |
| 17 | Still-frame shadow maps need the engine's update step; without it no shadow map is ever generated | Likely | `castle-render --no-update` gives the dark picture that `castle-model-viewer --screenshot` shows on a scene with `shadows=TRUE`; the viewer's frame size and camera differ, so the cause is not isolated | `castle-render` always updates before it renders |
| 18 | Physical lights get no inverse-square falloff; `attenuation` is used as written for every material | Confirmed | p1 and p4 light probes: Castle 4x (p1) and 3.6x (p4) too bright against Cycles, X_ITE and Babylon; `attenuation 0 0 1` brings p1 to F 0.0059 (X_ITE 0.0053). The Castle scout read X3D 4.0 17.2.2.6 as attenuation-only, so this is an engine difference, not necessarily a bug | see `docs/quality-leg.md` section 3 |

## What Castle already does well (measured)

* Native render of the PBR still life is 0.5/255 from X_ITE 16.7.1 (mean absolute pixel difference, 512 px).
* Colour rules equal X_ITE's by pixel: classic Material 0.5 gives 128, PhysicalMaterial emissive 0.5 gives 186.
* Defaults equal X_ITE's: no tone mapping, linear lighting when a PhysicalMaterial is used.
* Shadow maps work with `shadows="true"` on a light.
* Physical point lights are about 1.8x brighter than X_ITE 16.7.1 because Castle applies no 1/d^2 falloff; the X3D 4.0
  text (clause 17.2.2.3 / 17.2.2.6) applies the attenuation field, default (1 0 0) = none, to both material kinds.
