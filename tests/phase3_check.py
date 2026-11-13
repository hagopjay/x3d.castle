#!/usr/bin/env python3
"""Phase 3 fixture checks for the shape-tree exporter.

Each fixture in tests/scenes-phase3/ names one feature. The check converts it (with the flags the case lists), runs the
Khronos glTF-Validator over the glb (0 errors always; the warning count the case expects) and asserts properties of the
glTF JSON. Nothing is skipped: a case that cannot run fails.

    CASTLE_CONVERT=castle-convert/x3d-castle-convert python3 tests/phase3_check.py [--out DIR] [--only NAME] [--json results.json]

Exit status 1 if any case fails.
"""
import argparse, json, os, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "scenes-phase3")


def load_glb(path):
    b = open(path, "rb").read()
    magic, ver, total = struct.unpack("<4sII", b[:12])
    assert magic == b"glTF", "not a glb"
    off, js = 12, None
    while off < len(b):
        n, t = struct.unpack("<I4s", b[off:off + 8])
        if t == b"JSON":
            js = json.loads(b[off + 8: off + 8 + n].decode("utf-8"))
        off += 8 + n
    return js


def ext(o, name):
    return (o.get("extensions") or {}).get(name)


def lights(g):
    return (ext(g, "KHR_lights_punctual") or {}).get("lights", []) if "extensions" in g else []


def prim(g, i=0):
    return g["meshes"][i]["primitives"][0]


def mats_by_color(g):
    return g["materials"]


# --------------------------------------------------------------------------------------------- the cases
# Each check returns a list of failure strings (empty = pass).
def c_tangent(g, rep, val):
    f = []
    p = prim(g)
    if "TANGENT" not in p["attributes"]:
        f.append("primitive has no TANGENT")
    if "TEXCOORD_0" not in p["attributes"]:
        f.append("primitive has no TEXCOORD_0")
    if g["materials"][p["material"]].get("normalTexture") is None:
        f.append("material has no normalTexture")
    return f


def c_emissive_strength(g, rep, val):
    f = []
    m = g["materials"][prim(g)["material"]]
    es = ext(m, "KHR_materials_emissive_strength")
    if not es or abs(es.get("emissiveStrength", 0) - 4.0) > 1e-3:
        f.append(f"emissiveStrength {es} (want 4)")
    ef = m.get("emissiveFactor", [0, 0, 0])
    if max(ef) > 1.0 + 1e-6 or abs(ef[0] - 1.0) > 1e-3 or abs(ef[1] - 0.5) > 1e-3 or abs(ef[2] - 0.25) > 1e-3:
        f.append(f"emissiveFactor {ef} (want 1 0.5 0.25)")
    if "KHR_materials_emissive_strength" not in g.get("extensionsUsed", []):
        f.append("extension not in extensionsUsed")
    return f


def c_texprops(g, rep, val):
    f = []
    if not g.get("samplers"):
        return ["no samplers"]
    s = g["samplers"][0]
    if s.get("magFilter") != 9728:
        f.append(f"magFilter {s.get('magFilter')} (want 9728 NEAREST)")
    if s.get("minFilter") != 9728:
        f.append(f"minFilter {s.get('minFilter')} (want 9728 NEAREST, generateMipMaps=false)")
    if s.get("wrapS") != 33648:
        f.append(f"wrapS {s.get('wrapS')} (want 33648 MIRRORED_REPEAT)")
    if s.get("wrapT") != 33071:
        f.append(f"wrapT {s.get('wrapT')} (want 33071 CLAMP_TO_EDGE)")
    return f


def c_texcoord_sets(g, rep, val):
    f = []
    p = prim(g)
    for a in ("TEXCOORD_0", "TEXCOORD_1"):
        if a not in p["attributes"]:
            f.append(f"missing {a}")
    m = g["materials"][p["material"]]
    bt = m["pbrMetallicRoughness"].get("baseColorTexture")
    et = m.get("emissiveTexture")
    if not bt or bt.get("texCoord", 0) != 0:
        f.append(f"baseColorTexture {bt} (want texCoord 0)")
    if not et or et.get("texCoord", 0) != 1:
        f.append(f"emissiveTexture {et} (want texCoord 1)")
    return f


def c_alpha(g, rep, val):
    f = []
    ms = g["materials"]
    by = {}
    for m in ms:
        by[(m.get("alphaMode", "OPAQUE"), m.get("doubleSided", False))] = m
    modes = sorted({m.get("alphaMode", "OPAQUE") for m in ms})
    if modes != ["BLEND", "MASK", "OPAQUE"]:
        f.append(f"alpha modes present {modes} (want BLEND MASK OPAQUE)")
    mask = [m for m in ms if m.get("alphaMode") == "MASK"]
    if not mask or abs(mask[0].get("alphaCutoff", 0.5) - 0.3) > 1e-4:
        f.append(f"MASK cutoff {mask[0].get('alphaCutoff') if mask else None} (want 0.3)")
    if not any(m.get("doubleSided") for m in ms):
        f.append("no doubleSided material for solid=false")
    unlit_blend = [m for m in ms if m.get("alphaMode") == "BLEND" and ext(m, "KHR_materials_unlit") is not None]
    if not unlit_blend:
        f.append("no unlit BLEND material (UnlitMaterial transparency)")
    elif unlit_blend[0]["pbrMetallicRoughness"].get("baseColorTexture") is None:
        f.append("unlit material lost its texture")
    return f


def c_spot(g, rep, val):
    f = []
    sp = [l for l in lights(g) if l["type"] == "spot"]
    if len(sp) != 2:
        return [f"{len(sp)} spot lights (want 2)"]
    a, b = sorted(sp, key=lambda l: l["name"])
    if abs(a["spot"]["innerConeAngle"] - 0.3) > 1e-4 or abs(a["spot"]["outerConeAngle"] - 0.8) > 1e-4:
        f.append(f"S1 cone {a['spot']} (want inner 0.3 outer 0.8)")
    if abs(a.get("range", 0) - 12) > 1e-3:
        f.append(f"S1 range {a.get('range')} (want 12 from radius)")
    if not (b["spot"]["innerConeAngle"] < b["spot"]["outerConeAngle"] <= 0.5 + 1e-6):
        f.append(f"S2 cone {b['spot']} (want inner < outer = 0.5)")
    return f


def c_light_extras(g, rep, val):
    f = []
    L = {l["name"]: l for l in lights(g)}
    sun, off = L.get("Sun"), L.get("Off")
    if not sun or not off:
        return [f"lights present {list(L)} (want Sun and Off)"]
    x = (sun.get("extras") or {}).get("x3d") or {}
    if abs(x.get("ambientIntensity", -1) - 0.3) > 1e-4:
        f.append(f"Sun extras.x3d.ambientIntensity {x.get('ambientIntensity')} (want 0.3)")
    if x.get("shadows") is not True:
        f.append(f"Sun extras.x3d.shadows {x.get('shadows')} (want true)")
    if x.get("global") is not False:
        f.append(f"Sun extras.x3d.global {x.get('global')} (want false: the X3D default for DirectionalLight)")
    if "scopeNodes" in x:
        f.append("Sun sits at the scene root: its scope is everything, scopeNodes must be omitted")
    xo = (off.get("extras") or {}).get("x3d") or {}
    if off.get("intensity") != 0:
        f.append(f"Off light intensity {off.get('intensity')} (want 0)")
    if xo.get("on") is not False or abs(xo.get("intensity", -1) - 3.0) > 1e-3 or not xo.get("intensityIfOn", 0) > 0:
        f.append(f"Off light extras.x3d {xo} (want on false, intensity 3 as authored, intensityIfOn > 0)")
    return f


def c_scope_extras(g, rep, val):
    f = []
    L = {l["name"]: l for l in lights(g)}
    for n in ("ScopedSun", "ScopedPoint"):
        l = L.get(n)
        if not l:
            f.append(f"light {n} missing")
            continue
        x = (l.get("extras") or {}).get("x3d") or {}
        if x.get("global") is not False:
            f.append(f"{n} extras.x3d.global {x.get('global')} (want false)")
        sc = x.get("scopeNodes")
        if not isinstance(sc, list) or len(sc) != 1:
            f.append(f"{n} extras.x3d.scopeNodes {sc} (want the one sphere node under its group)")
        else:
            nd = g["nodes"][sc[0]]
            if abs(nd.get("matrix", [0] * 16)[12] + 6) > 1e-4:
                f.append(f"{n} scope node is not the sphere at x=-6")
    want = 1 if "lights_scope_range_clamped" in rep and rep["lights_scope_range_clamped"] == 1 else 2
    if rep.get("lights_scoped_unscopable", None) != want:
        f.append(f"export.json lights_scoped_unscopable {rep.get('lights_scoped_unscopable')} (want {want}: the directional light"
                 + (", and the point light when --scope-lights is off)" if want == 2 else ")"))
    return f


def c_scope_range(g, rep, val):
    f = c_scope_extras(g, rep, val)
    L = {l["name"]: l for l in lights(g)}
    p = L.get("ScopedPoint", {})
    r = p.get("range")
    if r is None or not (0 < r < 10):
        f.append(f"ScopedPoint range {r} (want clamped to the scope's extent, under 10, with --scope-lights)")
    return f


def c_env(g, rep, val):
    f = []
    x = ((g.get("scenes") or [{}])[g.get("scene", 0)].get("extras") or {}).get("x3d") or {}
    bg = x.get("background")
    if not bg:
        f.append("scene extras.x3d.background missing")
    else:
        if len(bg.get("skyColor", [])) != 2 or len(bg.get("groundColor", [])) != 2:
            f.append(f"background colours {bg}")
        if abs(bg["skyAngle"][0] - 1.4) > 1e-4:
            f.append("skyAngle lost")
    fog = x.get("fog")
    if not fog or fog.get("type") != "EXPONENTIAL" or abs(fog.get("visibilityRange", 0) - 40) > 1e-3:
        f.append(f"fog {fog}")
    el = x.get("environmentLight")
    if not el or abs(el.get("intensity", -1) - 0.5) > 1e-4:
        f.append(f"environmentLight {el}")
    return f


def c_switch_default(g, rep, val):
    # the default run keeps today's behaviour: only the selected choice of "Pick" is written, hidden ones are not
    n = len(g["meshes"])
    return [] if n == 1 else [f"{n} meshes (default must write only the active choice: 1)"]


def c_switch_hidden(g, rep, val):
    f = []
    vis = []
    for i, nd in enumerate(g["nodes"]):
        if "mesh" in nd:
            e = ext(nd, "KHR_node_visibility")
            vis.append((i, None if e is None else e.get("visible")))
    if len(vis) != 4:
        f.append(f"{len(vis)} mesh nodes (want 4: 2 hidden Frames, active + hidden Pick)")
    hidden = [i for i, v in vis if v is False]
    if len(hidden) != 3:
        f.append(f"{len(hidden)} hidden nodes (want 3)")
    shown = [i for i, v in vis if v is None]
    if len(shown) != 1:
        f.append(f"{len(shown)} always-visible mesh nodes (want 1: the active Pick choice)")
    if "KHR_node_visibility" not in g.get("extensionsUsed", []):
        f.append("KHR_node_visibility not in extensionsUsed")
    if "KHR_node_visibility" in g.get("extensionsRequired", []):
        f.append("KHR_node_visibility must not be required")
    return f


def c_text_default(g, rep, val):
    return [] if not g.get("meshes") and rep.get("text_shapes_skipped", 0) >= 1 else [
        f"default must skip Text: meshes {len(g.get('meshes', []))}, skipped {rep.get('text_shapes_skipped')}"]


def c_text_atlas(g, rep, val):
    f = []
    if not g.get("meshes"):
        return ["no mesh for Text"]
    p = prim(g)
    m = g["materials"][p["material"]]
    if m.get("alphaMode") not in ("BLEND", "MASK"):
        f.append(f"alphaMode {m.get('alphaMode')} (want BLEND or MASK)")
    if m["pbrMetallicRoughness"].get("baseColorTexture") is None:
        f.append("no baseColorTexture (the font atlas)")
    if "TEXCOORD_0" not in p["attributes"]:
        f.append("no TEXCOORD_0")
    if rep.get("text_shapes_exported", 0) < 1:
        f.append(f"export.json text_shapes_exported {rep.get('text_shapes_exported')}")
    return f


def c_base_only(g, rep, val):
    m = g["materials"][0]
    bc = (m.get("pbrMetallicRoughness") or {}).get("baseColorFactor")
    if not bc or abs(bc[0] - 1) > 1e-6 or abs(bc[1] - 1) > 1e-6 or abs(bc[2]) > 1e-6 or abs(bc[3] - 0.75) > 1e-6:
        return [f"baseColorFactor {bc} (want 1 1 0 0.75)"]
    return []


def _base(g):
    return (g["materials"][0].get("pbrMetallicRoughness") or {}).get("baseColorFactor") or [0, 0, 0, 1]


def c_events_default(g, rep, val):
    b = _base(g)
    return [] if b[0] > 0.9 and b[2] < 0.1 else [f"default baseColorFactor {b} (want red, the file as loaded)"]


def c_events_at(g, rep, val):
    b = _base(g)
    return [] if b[2] > 0.9 and b[0] < 0.1 else [f"--events-at=1 baseColorFactor {b} (want blue, the interpolator end)"]


def c_nonfinite(g, rep, val):
    f = []
    if rep.get("nonfinite_values_zeroed", 0) < 1:
        f.append(f"export.json nonfinite_values_zeroed {rep.get('nonfinite_values_zeroed')} (the fixture must hit the case)")
    return f


def v_regress(g, rep, val):
    return []


# name, fixture, args, expected validator warnings, check, note
CASES = [
    ("tangent-normalmap", "tangent-normalmap.x3d", [], 0, c_tangent, "TANGENT generated when Castle has none"),
    ("emissive-strength", "emissive-strength.x3d", [], 0, c_emissive_strength, "KHR_materials_emissive_strength"),
    ("texture-properties", "texture-properties.x3d", [], 0, c_texprops, "TextureProperties to sampler"),
    ("texcoord-sets", "texcoord-sets.x3d", [], 0, c_texcoord_sets, "texCoord sets above 0 via *TextureMapping"),
    ("material-base-only", "material-base-only.x3d", [], 0, c_base_only, "baseColor kept when metallic and roughness are the X3D defaults (PasGLTF Empty test)"),
    ("alpha-modes", "alpha-modes.x3d", [], 0, c_alpha, "alpha modes, cutoff, doubleSided, unlit alpha texture"),
    ("spot-cone", "spot-cone.x3d", [], 0, c_spot, "spot cone angles and range"),
    ("light-extras", "light-extras.x3d", [], 0, c_light_extras, "light ambientIntensity / shadows / on / global as extras"),
    ("light-scope", "light-scope.x3d", [], 0, c_scope_extras, "global=false scope recorded as extras"),
    ("light-scope-range", "light-scope.x3d", ["--scope-lights"], 0, c_scope_range, "--scope-lights clamps a scoped point light's range"),
    ("environment", "environment.x3d", [], 0, c_env, "Background / Fog / EnvironmentLight as scene extras"),
    ("switch-default", "switch-hidden.x3d", [], 0, c_switch_default, "default keeps writing active Switch choices only"),
    ("switch-hidden", "switch-hidden.x3d", ["--hidden-switch"], 0, c_switch_hidden, "--hidden-switch writes hidden choices with KHR_node_visibility"),
    ("events-default", "events-at.x3d", [], 0, c_events_default, "default writes the file as loaded"),
    ("events-at", "events-at.x3d", ["--events-at=1"], 0, c_events_at, "--events-at=1 writes the state after the TimeSensor ran 1 s"),
    ("nonfinite-texcoord", "nonfinite-texcoord.x3d", [], 0, c_nonfinite, "NaN generated texture coordinates are written as 0 (validator ACCESSOR_INVALID_FLOAT)"),
    ("text-default", "text-atlas.x3d", [], 0, c_text_default, "default still skips Text"),
    ("text-atlas", "text-atlas.x3d", ["--text-atlas"], 0, c_text_atlas, "--text-atlas writes glyph quads with the font atlas"),
]


def validate(glb, out_dir):
    vj = os.path.join(out_dir, os.path.basename(glb) + ".validation.json")
    r = subprocess.run(["node", os.path.join(ROOT, "tools", "gltf_validate.mjs"), vj, glb], capture_output=True, text=True)
    try:
        row = json.load(open(vj))[0]
    except Exception:
        return {"fail": (r.stdout + r.stderr)[-300:]}
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "phase3", "fixtures"))
    ap.add_argument("--only", action="append"); ap.add_argument("--json")
    ap.add_argument("--conv", default=os.environ.get("CASTLE_CONVERT", os.path.join(ROOT, "castle-convert", "x3d-castle-convert")))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    results, bad = [], 0
    for name, fx, args, want_w, check, note in CASES:
        if a.only and name not in a.only:
            continue
        glb = os.path.join(a.out, name + ".glb")
        if os.path.exists(glb):
            os.remove(glb)
        r = subprocess.run([a.conv, os.path.join(FIX, fx), glb, "--verbose"] + args, capture_output=True, text=True)
        open(os.path.join(a.out, name + ".log"), "w").write(r.stderr + r.stdout)
        fails = []
        rep = {}
        if r.returncode != 0 or not os.path.exists(glb):
            fails.append(f"converter exit {r.returncode}")
            g = {}
        else:
            g = load_glb(glb)
            try:
                rep = json.load(open(glb + ".export.json"))
            except Exception as e:
                fails.append(f"export.json unreadable: {e}")
            val = validate(glb, a.out)
            if val.get("fail") or val.get("errors"):
                fails.append(f"validator errors {val.get('errors')} {val.get('messages') or val.get('fail')}")
            elif val.get("warnings", 0) != want_w:
                fails.append(f"validator warnings {val.get('warnings')} (want {want_w}) {val.get('messages')}")
            try:
                fails += check(g, rep, val)
            except Exception as e:  # a missing key is a failed case, not a crash
                fails.append(f"check raised {type(e).__name__}: {e}")
        status = "PASS" if not fails else "FAIL"
        bad += bool(fails)
        results.append({"case": name, "fixture": fx, "args": args, "status": status, "failures": fails, "note": note})
        print(f"{status}  {name:20s} {note}")
        for x in fails:
            print(f"        - {x}")
    print(f"\n{len(results) - bad} of {len(results)} cases pass")
    if a.json:
        json.dump(results, open(a.json, "w"), indent=1)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
