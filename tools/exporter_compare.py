#!/usr/bin/env python3
"""Phase 2: the shape-tree exporter's glb, rendered by Babylon.js through the x3d-blender-io fidelity rig, next to the
legs castle_compare.py already produced. The rig is NOT copied: its render.mjs and its out/LABEL folders are used as they are.

Per scene, mean |delta| per pixel (0-255), whole frame | add-on glb geometry mask:
  X_ITE vs Babylon on the add-on glb          the rig's own number
  X_ITE vs Castle native
  X_ITE vs Babylon on Castle's stock-writer glb          (before)
  X_ITE vs Babylon on the shape-tree exporter glb, per variant  (after)
Variants (CLI --variant NAME=ARGS, ARGS are x3d-castle-convert options):
  rigcam   default options but --no-headlight: the rig adds its own headlight and camera, like for every other leg
  srgb     rigcam + --colour-space=srgb
  self     default options: the glb brings its own camera and headlight, the rig headlight is switched off

    python3 exporter_compare.py --rig ../x3d-blender-io/tools/fidelity_rig --label h2h --label h2h2 \
        --prev results/h2h-castle2 --conv castle-convert/x3d-castle-convert --out results/phase2
"""
import argparse, json, os, subprocess, sys, shlex
import numpy as np
from PIL import Image, ImageDraw
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from castle_compare import load, proxies, delta, font

DEFAULT_VARIANTS = ["rigcam=--no-headlight", "srgb=--no-headlight --colour-space=srgb", "self="]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rig", required=True); ap.add_argument("--label", action="append", required=True)
    ap.add_argument("--prev", required=True, help="castle_compare.py output folder (has castle/, babylon_castle_glb/, results.json)")
    ap.add_argument("--conv", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--variant", action="append"); ap.add_argument("--only", action="append")
    a = ap.parse_args()
    variants = [v.split("=", 1) for v in (a.variant or DEFAULT_VARIANTS)]
    jobs = [j for lab in a.label for j in json.load(open(f"{a.rig}/out/{lab}/jobs.json"))]
    prev_names = {r["scene"] for r in json.load(open(f"{a.prev}/results.json"))["rows"]}
    jobs = [j for j in jobs if j["name"] in prev_names and (not a.only or j["name"] in a.only)]
    cm = {r["key"]: r for r in json.load(open(f"{a.prev}/castle/matrix.json"))["rows"]}
    os.makedirs(a.out, exist_ok=True)
    empty = os.path.abspath(f"{a.out}/empty.x3d")
    open(empty, "w").write("<?xml version='1.0'?><X3D profile='Interchange' version='4.0'><Scene/></X3D>")
    export_info = {}
    for vname, vargs in variants:
        vd = f"{a.out}/{vname}"; os.makedirs(f"{vd}/glb", exist_ok=True); dj = []
        for j in jobs:
            g = os.path.abspath(f"{vd}/glb/{j['name']}.glb")
            r = subprocess.run([a.conv, j["x3d"], g, "--verbose"] + shlex.split(vargs), capture_output=True, text=True, timeout=300)
            open(f"{vd}/glb/{j['name']}.log", "w").write(r.stderr + r.stdout)
            if r.returncode != 0 or not os.path.exists(g):
                print("export failed", vname, j["name"]); continue
            try:
                export_info[(vname, j["name"])] = json.load(open(g + ".export.json"))
            except Exception:
                pass
            jj = {**j, "x3d": empty, "glb": g, "outdir": os.path.abspath(f"{vd}/babylon/{j['name']}")}
            if vname == "self":
                jj["headlight"] = None
            dj.append(jj)
        json.dump(dj, open(f"{vd}/jobs.json", "w"), indent=1)
        if not os.path.exists(f"{vd}/babylon/.done"):
            os.makedirs(f"{vd}/babylon", exist_ok=True)
            r = subprocess.run(["node", f"{a.rig}/render.mjs", os.path.abspath(f"{vd}/jobs.json")], capture_output=True, text=True, timeout=3000)
            open(f"{vd}/babylon.log", "w").write(r.stdout + r.stderr); open(f"{vd}/babylon/.done", "w").write("1")
    rows, f = [], font(11)
    for j in jobs:
        n = j["name"]; d = j["outdir"]
        X, B = load(f"{d}/xite.png"), load(f"{d}/babylon.png")
        C = load(f"{a.prev}/castle/{cm[n]['render']['png']}") if cm[n]["render"]["png"] else None
        D = load(f"{a.prev}/babylon_castle_glb/{n}/babylon.png")
        Mk = load(f"{d}/babylon_mask.png")
        geo = ~((Mk[..., 0] == 255) & (Mk[..., 1] == 0) & (Mk[..., 2] == 255)) if Mk is not None else None
        row = dict(scene=n, xite_vs_babylon_addon=delta(X, B, geo), xite_vs_castle=delta(X, C, geo), xite_vs_babylon_stockglb=delta(X, D, geo), variants={})
        tiles = [("X_ITE 16.7.1 / X3D", X), ("Babylon / add-on glb", B), ("CASTLE native", C), ("Babylon / Castle STOCK glb", D)]
        for vname, _ in variants:
            V = load(f"{a.out}/{vname}/babylon/{n}/babylon.png")
            row["variants"][vname] = dict(xite=delta(X, V, geo), castle_native=delta(C, V, geo), quality=proxies(V) if V is not None else None,
                                          info={k: export_info.get((vname, n), {}).get(k) for k in ("shapes", "triangles", "lights", "cameras", "textures", "shapes_with_vertex_colours", "shapes_baked_for_shear")})
            tiles.append((f"Babylon / NEW glb [{vname}]", V))
        rows.append(row)
        sheet = Image.new("RGB", (len(tiles) * 512, 512 + 22), (16, 16, 20)); dr = ImageDraw.Draw(sheet)
        for i, (t, im) in enumerate(tiles):
            if im is not None:
                sheet.paste(Image.fromarray(im.astype(np.uint8)), (i * 512, 22))
            dr.text((i * 512 + 6, 5), t, fill=(235, 235, 240), font=f)
        os.makedirs(f"{a.out}/montage", exist_ok=True); sheet.save(f"{a.out}/montage/{n}.png")
    json.dump(dict(rig_label=a.label, variants=variants, rows=rows), open(f"{a.out}/results.json", "w"), indent=1)
    g = lambda r: (f"{r['frame']:.1f}|{r['geometry'] if r['geometry'] is not None else '-'}" if r else "-")
    head = f"{'scene':28s} {'X-B(addon)':>11s} {'X-Castle':>9s} {'X-stock':>9s}" + "".join(f" {'X-' + v:>11s}" for v, _ in variants)
    print(head)
    for r in rows:
        print(f"{r['scene']:28s} {g(r['xite_vs_babylon_addon']):>11s} {g(r['xite_vs_castle']):>9s} {g(r['xite_vs_babylon_stockglb']):>9s}" +
              "".join(f" {g(r['variants'][v]['xite']):>11s}" for v, _ in variants))


if __name__ == "__main__":
    main()
