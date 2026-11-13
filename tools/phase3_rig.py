#!/usr/bin/env python3
"""Phase 3 rig driver: X_ITE on the X3D against Babylon.js on the exporter's glb, mean |delta| per pixel (0..255).

The x3d-blender-io fidelity rig (render.mjs, xite.html, babylon.html) is used as it is: pass a folder that holds a copy
of those four files plus `npm install` (the rig's own package.json pins x_ite 16.7.1, babylonjs 9.32.0, playwright 1.63.0).
The rig's compare.py is not importable (it runs on import), so its first-Viewpoint code is exec'd from the file, not copied.
Unlike exporter_compare.py this driver needs no earlier rig run: it renders X_ITE itself.

Per scene and variant: convert (a WebP prepass copy when the scene uses WebP), write one job, run render.mjs, then
  frame     mean |delta| over the whole 512 x 512 frame
  geometry  the same over pixels where the glb draws something (magenta / green clear masks, as the rig does)
Variants are NAME=ARGS (ARGS go to the converter). `rigcam` = --no-headlight, the rig adds its headlight (lux 1.0, the rig's
fallback) and camera; `self` = converter defaults, the glb brings its headlight and the rig adds none.

    python3 tools/phase3_rig.py --rig /path/rigcopy --conv castle-convert/x3d-castle-convert --scenes tools/phase3_scenes.json \
        --out results/phase3/rig --variant rigcam=--no-headlight --variant self=
"""
import argparse, json, os, re, shlex, statistics, subprocess, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))


def load_rig_viewpoint(rig_compare):
    """exec the first part of the rig's compare.py (helper functions up to the PIL import) and return first_viewpoint."""
    text = open(rig_compare, encoding="utf-8").read()
    head = text.split("\nfrom PIL import Image", 1)[0]
    ns = {"__name__": "rig_compare_head", "__file__": rig_compare}
    sys.path.insert(0, os.path.dirname(rig_compare))
    exec(compile(head, rig_compare, "exec"), ns)
    return ns["first_viewpoint"]


def img(p):
    return np.asarray(Image.open(p).convert("RGB"), dtype=np.float64) if os.path.exists(p) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rig", required=True, help="folder with render.mjs, xite.html, babylon.html, node_modules")
    ap.add_argument("--rig-src", default=os.path.join(HERE, "..", "..", "x3d-blender-io", "tools", "fidelity_rig"),
                    help="the x3d-blender-io fidelity_rig folder (for compare.py's viewpoint code)")
    ap.add_argument("--addon-src", default=os.path.join(HERE, "..", "..", "x3d-blender-io", "source"),
                    help="the add-on's source folder (geospatial.py, used for GeoViewpoint scenes)")
    ap.add_argument("--conv", required=True); ap.add_argument("--scenes", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--base", default=os.path.join(HERE, "..", ".."), help="scene paths in the scenes file are relative to this (the folder that holds x3d.demo and x3d.castle)")
    ap.add_argument("--variant", action="append", required=True); ap.add_argument("--only", action="append")
    ap.add_argument("--reuse-xite", action="store_true", help="skip variants' X_ITE render when out/xite/NAME.png exists")
    a = ap.parse_args()
    first_viewpoint = load_rig_viewpoint(os.path.abspath(os.path.join(a.rig_src, "compare.py")))
    scenes = json.load(open(a.scenes))
    if a.only:
        scenes = [s for s in scenes if s["name"] in a.only]
    os.makedirs(a.out, exist_ok=True)
    results = {}
    for vspec in a.variant:
        vname, vargs = vspec.split("=", 1)
        vd = os.path.join(a.out, vname); os.makedirs(f"{vd}/glb", exist_ok=True); jobs = []
        for sc in scenes:
            n = sc["name"]; x3d = os.path.abspath(os.path.join(a.base, sc["x3d"]))
            src = x3d
            if re.search(r"\.webp", open(x3d, encoding="utf-8", errors="replace").read(), re.I):
                q = subprocess.run([sys.executable, os.path.join(HERE, "webp_prepass.py"), x3d, os.path.abspath(f"{vd}/prepass/{n}")],
                                   capture_output=True, text=True)
                if q.returncode == 0 and q.stdout.strip():
                    src = q.stdout.strip().splitlines()[0]
            g = os.path.abspath(f"{vd}/glb/{n}.glb")
            r = subprocess.run([a.conv, src, g, "--verbose"] + shlex.split(vargs), capture_output=True, text=True, timeout=300)
            open(f"{vd}/glb/{n}.log", "w").write(r.stderr + r.stdout)
            if r.returncode != 0 or not os.path.exists(g):
                print("export failed", vname, n); continue
            txt = open(x3d, errors="ignore").read()
            m = re.search(r"<Background\b[^>]*skyColor=['\"]([^'\"]+)", txt)
            clear = [float(v) for v in m.group(1).replace(",", " ").split()[:3]] if m else [0, 0, 0]
            nav = re.search(r"<NavigationInfo\b[^>]*headlight=['\"](\w+)", txt)
            head_on = not (nav and nav.group(1).lower() == "false")
            headlight = (1.0 if head_on else None) if "--no-headlight" in vargs else None
            jobs.append(dict(name=n, x3d=x3d, glb=g, clear=clear, headlight=headlight, outdir=os.path.abspath(f"{vd}/img/{n}"),
                             wait=sc.get("wait", 1500), view=first_viewpoint(x3d, os.path.abspath(a.addon_src))))
        jf = os.path.abspath(f"{vd}/jobs.json"); json.dump(jobs, open(jf, "w"), indent=1)
        log = subprocess.run(["node", os.path.join(a.rig, "render.mjs"), jf], capture_output=True, text=True, timeout=3000)
        open(f"{vd}/render.log", "w").write(log.stdout + log.stderr)
        rows = []
        for j in jobs:
            d = j["outdir"]; X, B = img(f"{d}/xite.png"), img(f"{d}/babylon.png")
            if X is None or B is None:
                rows.append(dict(scene=j["name"], error="missing render")); continue
            Mk, Mg = img(f"{d}/babylon_mask.png"), img(f"{d}/babylon_mask_green.png")
            diff = np.abs(X - B); row = dict(scene=j["name"], frame=round(float(diff.mean()), 2), geometry=None)
            if Mk is not None and Mg is not None:
                clr = ((Mk[..., 0] == 255) & (Mk[..., 1] == 0) & (Mk[..., 2] == 255)) & ((Mg[..., 0] == 0) & (Mg[..., 1] == 255) & (Mg[..., 2] == 0))
                geo = ~clr
                if geo.any():
                    row["geometry"] = round(float(diff[geo].mean()), 2); row["geometry_share"] = round(float(geo.mean()), 3)
            try:
                row["export"] = {k: v for k, v in json.load(open(j["glb"] + ".export.json")).items() if not isinstance(v, (list, dict))}
            except Exception:
                pass
            rows.append(row)
        fr = [r["frame"] for r in rows if "frame" in r]
        summ = dict(n=len(fr), mean=round(statistics.mean(fr), 2) if fr else None, median=round(statistics.median(fr), 2) if fr else None)
        browser = re.findall(r"BROWSER (\S+)", log.stdout); xv = re.findall(r"X_ITE (\S+)", log.stdout); bv = re.findall(r'"(\d+\.\d+\.\d+)"', log.stdout)
        results[vname] = dict(args=vargs, summary=summ, rows=rows, browser=browser[:1], x_ite=xv[:1])
        print(f"{vname}: n={summ['n']} mean {summ['mean']} median {summ['median']}  {browser[:1]} X_ITE {xv[:1]}")
        for r in rows:
            print(f"  {r['scene']:30s} {r.get('frame')} | {r.get('geometry')}")
    json.dump(results, open(f"{a.out}/results.json", "w"), indent=1)


if __name__ == "__main__":
    main()
