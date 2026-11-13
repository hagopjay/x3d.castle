# Reproduce the Castle scout

Everything here ran in a cloud container with no GPU, no Windows, no sudo beyond apt. Every number in this repo
names the software it came from; nothing was measured on a physical GPU.

| thing | version used |
|---|---|
| Castle Game Engine | 7.0-alpha.3 snapshot (linux-x86_64 bundle, 12 Nov 2026) |
| castle-model-viewer / castle-model-converter | 5.3.0 |
| FPC | 3.2.2 |
| renderer for Castle screenshots | Xvfb + Mesa llvmpipe (GL 4.5 core), 512 x 512, no multisample visuals |
| X_ITE | 16.7.1 (x3d-blender-io `tools/fidelity_rig`) |
| Babylon.js | 9.32.0 (same rig) |
| browser for the two web legs | Chromium 153, SwiftShader |
| glTF validator | Khronos glTF-Validator 2.0.0-dev.3.10 |

## 1. Get Castle

GitHub release downloads can be blocked in a sandbox. The project's own redirect works:

    curl -L -o castle.tar.xz https://castle-engine.gateway.scarf.sh/snapshot/castle-engine-7.0-alpha.3.snapshot-linux-x86_64-bundle.tar.xz
    tar xf castle.tar.xz -C cge        # about 800 MB; bin/ and src/ are both in the bundle

    sudo apt install xvfb libgl1-mesa-dri libharfbuzz-gobject0 fp-compiler   # Debian / Ubuntu names

## 2. Render one scene headless

    xvfb-run -a cge/castle_game_engine/bin/castle-model-viewer --hide-menu --no-sound \
        --geometry 512x512 --screenshot 0 out.png scene.x3d

Castle fits the camera when a scene has no Viewpoint and clears to 26/255 grey when it has no Background.
`tools/castle_leg.py --spec-defaults` writes a patched COPY with the X3D defaults (Viewpoint 0 0 10, black) so
renders are comparable; originals are never modified.

## 3. Build the converter / exporter (33 s cold, 2 s warm)

    cd castle-convert
    CASTLE_ENGINE_PATH=$PWD/../cge/castle_game_engine $CASTLE_ENGINE_PATH/bin/castle-engine compile
    ./x3d-castle-convert scene.x3d scene.glb --verbose

Options: `--engine-writer` (Castle's stock glTF writer, the baseline), `--colour-space=as-is|srgb`,
`--no-camera --no-lights --no-headlight --no-textures --no-phong-specular`, `--specular-max-f0=F`, `--text-quads`, `--light-scale=F`.

## 4. Census, validator, rig comparisons

    python3 tools/export_all.py scenes.txt out/ castle-convert/x3d-castle-convert REPO_ROOT
    (cd tools && npm i gltf-validator && node gltf_validate.mjs ../out/gltf-validate.json ../out/glb/*.glb)
    python3 tools/census_compare.py old_census.json out/glb out/census.json
    python3 tools/exporter_compare.py --rig ../x3d-blender-io/tools/fidelity_rig --label h2h --label h2h2 \
        --prev results/h2h-castle2 --conv castle-convert/x3d-castle-convert --out results/phase2

The rig (`x3d-blender-io/tools/fidelity_rig`) is reused as it is, not copied.

## 5. Quality run: every leg against a path-traced reference

`tools/run_quality.py` makes, per scene, a Cycles reference (`cycles_reference.py`, 256 spp, two seeds for the noise floor),
X_ITE and Babylon.js renders through the rig, our exporter's glb in Babylon.js, `castle-render` (native and one lever at a time,
plus `castle_all`), then the metrics of `quality_metrics.py` against the reference and against X_ITE, one sheet per scene and one
`results.json`. It re-executes itself under the venv that has bpy, flip-evaluator and scikit-image.

    (cd castle-render && ./build.sh)                          # castle-render binary; needs CASTLE_ENGINE_PATH
    python3 tools/run_quality.py --extra-refs direct,shadows  # public set -> ../qual/public (resumable, ~40 min on 4 shared vCPUs)
    python3 tools/run_quality.py --scenes scenes.txt --out DIR   # NAME=PATH lines, view from the scene's first Viewpoint

Private scenes: `--scenes` needs `--out`, and the script refuses an `--out` inside the public output folder.
`--extra-refs direct` adds a reference without indirect light (what X_ITE and Babylon.js can show), `shadows` one where every
light casts shadows (the file's own `shadows` field is otherwise honoured). The reference is Cycles as the x3d-blender-io add-on
imports the file: where the add-on drops a node (NurbsCurve, Billboard) or changes a light model (Blender lights always fall off
with 1/d^2) the reference does too, and a leg that reads the add-on's glb shares that.
