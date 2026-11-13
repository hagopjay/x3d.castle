# Docker image for the x3d.castle toolchain

One image that has what every step of this repo needs, so nobody has to repeat the sandbox set-up by hand:

| piece | where it comes from |
|---|---|
| Castle Game Engine 7.0-alpha.3 snapshot, linux-x86_64 bundle | download pinned by SHA-256 in `Dockerfile` (the URL is a moving snapshot; a replaced snapshot fails the build instead of changing the results) |
| FPC 3.2.2 | **inside the bundle** (`tools/contrib/fpc`), no distro `fp-compiler` needed. The distro one lacks the X11/GL units `castle-render` needs |
| `castle-engine` build tool, `castle-model-viewer`, `castle-model-converter` (5.3.0), `castle-editor` | the bundle's `bin/` |
| `x3d-castle-convert` (our glb exporter) and `castle-render` (our render harness with the quality levers) | built from this repo at image build time |
| headless GL | Xvfb + Mesa llvmpipe (software GL, no GPU) |

    docker build -f docker/Dockerfile -t x3d-castle .
    docker run --rm x3d-castle                       # docker/smoke.sh: validate, export, viewer screenshot, castle-render
    docker run --rm -it -v "$PWD":/work/out x3d-castle bash

## Status, plainly

* The commands in the `Dockerfile` were each run by hand on Ubuntu 24.04: the exporter builds with the bundle's FPC alone
  (47 s on a shared vCPU), `castle-render` builds with `castle-render/build.sh`, and `docker/smoke.sh` passes against those binaries.
* The image itself has **not** been built yet: the sandbox it was written in has no Docker daemon. The first run of
  `.github/workflows/docker.yml` is the first real test; treat a failure there as expected-to-fix, not as a regression.
* Not covered: the Castle editor needs a display (it is a GTK3/LCL app; Xvfb would start it, nobody has tried), packaging for
  Android / iOS / Windows needs extra toolchains, and no GPU exists in the image, so GPU-only behaviour (real MSAA, shader
  compile on drivers) is untested.
* To move to another Castle snapshot, change both `CASTLE_URL` and `CASTLE_SHA256`, rebuild, and rerun `tools/run_quality.py`:
  every number in this repo names the snapshot it was measured on.

## Engine patches

A patch against the engine does not belong in this image's layers. Keep it as a `.patch` file against the pinned snapshot's
`src/` (see `docs/exporter.md` for what is a Castle bug and what is ours), apply it in a build step, and compare with the stock
engine. Nothing goes to the Castle project until the owner says so.
