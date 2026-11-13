#!/bin/sh
# Smoke test for the x3d.castle toolchain. Needs CASTLE_ENGINE_PATH, the two binaries on PATH and xvfb-run.
# Run inside the image (default CMD) or on any machine that has the same pieces. Exit 0 = every step passed.
set -eu
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

cat > "$T/cube.x3d" <<'X3D'
<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Interchange" version="4.0">
  <Scene>
    <Viewpoint position="0 0 6"/>
    <Background skyColor="0.1 0.1 0.3"/>
    <DirectionalLight direction="-1 -1 -1"/>
    <Transform rotation="1 1 0 0.6">
      <Shape>
        <Appearance><Material diffuseColor="1 0.4 0.1"/></Appearance>
        <Box size="2 2 2"/>
      </Shape>
    </Transform>
  </Scene>
</X3D>
X3D
sed -e '/<Transform/,/<\/Transform>/d' "$T/cube.x3d" > "$T/empty.x3d"

echo "[1/4] Castle tools present"
command -v castle-engine >/dev/null || fail "castle-engine not on PATH"
command -v castle-model-converter >/dev/null || fail "castle-model-converter not on PATH"
castle-model-converter --validate "$T/cube.x3d" || fail "validate"

echo "[2/4] exporter: X3D -> glb"
x3d-castle-convert "$T/cube.x3d" "$T/cube.glb" --verbose || fail "x3d-castle-convert"
[ "$(head -c 4 "$T/cube.glb")" = "glTF" ] || fail "output is not a glb"
echo "      glb bytes: $(wc -c < "$T/cube.glb")"

echo "[3/4] castle-model-viewer screenshot (Xvfb, software GL)"
xvfb-run -a castle-model-viewer --hide-menu --no-sound --geometry 256x256 --screenshot 0 "$T/viewer.png" "$T/cube.x3d" \
  || fail "castle-model-viewer"
[ "$(head -c 4 "$T/viewer.png" | tail -c 3)" = "PNG" ] || fail "viewer output is not a PNG"

echo "[4/4] castle-render screenshot with levers"
xvfb-run -a castle-render "$T/cube.x3d" "$T/render.png" --size 128 --ssaa 2 || fail "castle-render"
[ "$(head -c 4 "$T/render.png" | tail -c 3)" = "PNG" ] || fail "render output is not a PNG"
# the Box must be drawn: the same scene without the Transform renders as sky only, so the two PNGs must differ
xvfb-run -a castle-render "$T/empty.x3d" "$T/empty.png" --size 128 --ssaa 2 || fail "castle-render (empty scene)"
if cmp -s "$T/render.png" "$T/empty.png"; then fail "box not drawn: render equals the empty-scene render"; fi
echo "      render bytes: $(wc -c < "$T/render.png")  empty-scene bytes: $(wc -c < "$T/empty.png")"

echo "SMOKE OK"
