#!/usr/bin/env python3
"""Castle as a third and fourth leg next to the x3d-blender-io fidelity rig (X_ITE on the X3D, Babylon.js on the add-on's glb).

The rig is NOT copied here: this script reads the folder `compare.py` already wrote (out/LABEL with jobs.json and one
sub-folder per scene) and adds
  C  Castle, native render of the X3D                         (castle-model-viewer --screenshot, same 512 px, same first Viewpoint)
  D  Babylon.js 9.x on the glb that castle-model-converter writes from the same X3D (the rig's own render.mjs, unchanged)
and then reports, per scene, mean |delta| per pixel (0-255) over the whole frame and over the add-on glb's geometry mask:
  X_ITE-vs-Babylon(add-on glb)    the rig's number
  X_ITE-vs-Castle                 Castle against the reference renderer
  Babylon(add-on glb)-vs-Castle
  Castle-vs-Babylon(Castle glb)   how much of Castle's own picture survives the trip through its glb writer
plus three no-reference quality proxies per image (sharpness, contrast span, highlight clip), which are stand-ins until a
FLIP or path-traced reference exists.

    python3 castle_compare.py --rig ../x3d-blender-io/tools/fidelity_rig --label h2h --castle $CGE/bin --out results/h2h
"""
import argparse, json, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))


def load(p):
    return np.asarray(Image.open(p).convert("RGB"), dtype=np.float64) if os.path.exists(p) else None


def luma(a):
    return a @ np.array([0.2126, 0.7152, 0.0722])


def proxies(a):
    y = luma(a)
    lap = (-4 * y[1:-1, 1:-1] + y[:-2, 1:-1] + y[2:, 1:-1] + y[1:-1, :-2] + y[1:-1, 2:])
    return dict(sharpness=round(float(lap.var()), 1), p1=round(float(np.percentile(y, 1)), 1), p99=round(float(np.percentile(y, 99)), 1),
                clip_share=round(float((a.max(axis=2) >= 250).mean()), 4))


def delta(a, b, mask=None):
    if a is None or b is None:
        return None
    d = np.abs(a - b)
    return dict(frame=round(float(d.mean()), 2),
                geometry=(round(float(d[mask].mean()), 2) if mask is not None and mask.any() else None))


def font(sz):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rig", required=True); ap.add_argument("--label", required=True, action="append", help="rig out/LABEL folder; repeat to merge several runs")
    ap.add_argument("--castle", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--py", default=sys.executable)
    a = ap.parse_args()
    jobs = [j for lab in a.label for j in json.load(open(f"{a.rig}/out/{lab}/jobs.json"))]; os.makedirs(a.out, exist_ok=True)
    # 1. Castle native + Castle glb for the same X3D files
    lst = f"{a.out}/scenes.txt"; open(lst, "w").write("\n".join(f"{j['name']}={j['x3d']}" for j in jobs) + "\n")
    if not os.path.exists(f"{a.out}/castle/matrix.json"):
        subprocess.run([a.py, f"{HERE}/castle_leg.py", lst, "--castle", a.castle, "--out", f"{a.out}/castle", "--jobs", "2", "--timeout", "150", "--spec-defaults"], check=True)
    # E: Castle as a glTF viewer, on the add-on's glb
    lst2 = f"{a.out}/scenes_addon_glb.txt"; open(lst2, "w").write("\n".join(f"{j['name']}={j['glb']}" for j in jobs) + "\n")
    if not os.path.exists(f"{a.out}/castle_on_addon_glb/matrix.json"):
        subprocess.run([a.py, f"{HERE}/castle_leg.py", lst2, "--castle", a.castle, "--out", f"{a.out}/castle_on_addon_glb", "--jobs", "2", "--timeout", "150"], check=True)
    em = {r["key"]: r for r in json.load(open(f"{a.out}/castle_on_addon_glb/matrix.json"))["rows"]}
    cm = {r["key"]: r for r in json.load(open(f"{a.out}/castle/matrix.json"))["rows"]}
    # 2. Babylon on Castle's glb through the rig's own render.mjs; X_ITE is pointed at an empty scene so it costs nothing
    empty = f"{a.out}/empty.x3d"
    open(empty, "w").write("<?xml version='1.0'?><X3D profile='Interchange' version='4.0'><Scene/></X3D>")
    dj = []
    for j in jobs:
        g = f"{a.out}/castle/{cm[j['name']]['glb']['path']}" if cm[j["name"]]["glb"]["path"] else None
        if not g or os.path.getsize(g) < 700:
            continue
        dj.append({**j, "x3d": os.path.abspath(empty), "glb": os.path.abspath(g), "outdir": os.path.abspath(f"{a.out}/babylon_castle_glb/{j['name']}")})
    json.dump(dj, open(f"{a.out}/jobs_castle_glb.json", "w"), indent=1)
    if dj and not os.path.exists(f"{a.out}/babylon_castle_glb/.done"):
        r = subprocess.run(["node", f"{a.rig}/render.mjs", os.path.abspath(f"{a.out}/jobs_castle_glb.json")], capture_output=True, text=True, timeout=1800)
        open(f"{a.out}/babylon_castle_glb.log", "w").write(r.stdout + r.stderr); open(f"{a.out}/babylon_castle_glb/.done", "w").write("1")
    # 3. numbers and montages
    rows, f = [], font(11)
    for j in jobs:
        n = j["name"]; d = j["outdir"]
        X, B = load(f"{d}/xite.png"), load(f"{d}/babylon.png")
        C = load(f"{a.out}/castle/{cm[n]['render']['png']}") if cm[n]["render"]["png"] else None
        D = load(f"{a.out}/babylon_castle_glb/{n}/babylon.png")
        E = load(f"{a.out}/castle_on_addon_glb/{em[n]['render']['png']}") if em[n]["render"]["png"] else None
        Mk = load(f"{d}/babylon_mask.png")
        geo = ~((Mk[..., 0] == 255) & (Mk[..., 1] == 0) & (Mk[..., 2] == 255)) if Mk is not None else None
        row = dict(scene=n,
                   xite_vs_babylon_addon=delta(X, B, geo), xite_vs_castle=delta(X, C, geo), babylon_addon_vs_castle=delta(B, C, geo),
                   castle_vs_babylon_castleglb=delta(C, D, geo), xite_vs_babylon_castleglb=delta(X, D, geo), castle_on_addon_glb_vs_babylon_addon=delta(E, B, geo), castle_on_addon_glb_vs_castle_native=delta(E, C, geo),
                   quality={k: (proxies(v) if v is not None else None) for k, v in dict(xite=X, babylon_addon=B, castle=C, babylon_castleglb=D, castle_on_addon_glb=E).items()},
                   castle_glb_bytes=cm[n]["glb"]["bytes"], castle_validate=cm[n]["validate"]["verdict"], castle_render_seconds=cm[n]["render"]["seconds"])
        rows.append(row)
        tiles = [("X_ITE 16.7.1 / X3D", X), ("Babylon / add-on glb", B), ("CASTLE native / X3D", C), ("Babylon / Castle glb", D), ("Castle native / add-on glb", E)]
        sheet = Image.new("RGB", (5 * 512, 512 + 22), (16, 16, 20)); dr = ImageDraw.Draw(sheet)
        for i, (t, im) in enumerate(tiles):
            if im is not None:
                sheet.paste(Image.fromarray(im.astype(np.uint8)), (i * 512, 22))
            dr.text((i * 512 + 6, 5), f"{t}", fill=(235, 235, 240), font=f)
        dr.text((512 * 2 + 200, 5), f"|d| vs X_ITE: {row['xite_vs_castle']['frame'] if row['xite_vs_castle'] else '-'}", fill=(240, 200, 90), font=f)
        os.makedirs(f"{a.out}/montage", exist_ok=True); sheet.save(f"{a.out}/montage/{n}.png")
    json.dump(dict(rig_label=a.label, rows=rows), open(f"{a.out}/results.json", "w"), indent=1)
    print(f"{'scene':30s} {'X-B(add-on)':>12s} {'X-Castle':>9s} {'B-Castle':>9s} {'Castle-D':>9s} {'X-D':>7s} {'E-B':>8s} | frame|geometry")
    g = lambda r, k: (f"{r[k]['frame']:.1f}|{r[k]['geometry'] if r[k]['geometry'] is not None else '-'}" if r[k] else "-")
    for r in rows:
        print(f"{r['scene']:30s} {g(r,'xite_vs_babylon_addon'):>12s} {g(r,'xite_vs_castle'):>9s} {g(r,'babylon_addon_vs_castle'):>9s} "
              f"{g(r,'castle_vs_babylon_castleglb'):>9s} {g(r,'xite_vs_babylon_castleglb'):>7s} {g(r,'castle_on_addon_glb_vs_babylon_addon'):>8s}")


if __name__ == "__main__":
    main()
