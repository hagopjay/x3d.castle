#!/usr/bin/env python3
"""Castle leg for the X3D fidelity pipeline.

For every scene it records, in one pass:
  1. castle-model-converter --validate   (strict: any warning is a non-zero exit)  -> warnings, verdict, seconds
  2. castle-model-converter --identify   (X3D version, CGE extensions used)
  3. castle-model-viewer --screenshot    (native Castle render, headless: Xvfb + Mesa llvmpipe) -> PNG, seconds
  4. castle-model-converter scene.glb    (Castle's own X3D -> glTF writer)                         -> glb bytes, seconds

Nothing here edits a scene: scenes are read in place, every output goes under --out.

    python3 castle_leg.py --castle /path/to/castle_game_engine/bin --out results \
        --size 512 --jobs 3 --timeout 120 scenes.txt          # scenes.txt: one .x3d path per line

Numbers it writes (results/matrix.json) name their tool versions; nothing is a frame rate (software GL)."""
import argparse, concurrent.futures as cf, hashlib, json, os, re, subprocess, sys, time

import numpy as np
from PIL import Image


def run(cmd, timeout, env=None):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, errors="replace")
        return r.returncode, r.stdout, r.stderr, round(time.time() - t0, 2), False
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), \
            (e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or ""), round(time.time() - t0, 2), True


def spec_defaults_copy(scene, workdir):
    """X3D defaults the Castle viewer does not apply on its own: with no Viewpoint it fits the camera to the scene (X3D says
    position 0 0 10, looking down -Z), and with no Background it clears to grey 0.1 (X3D says black). For the screenshot only, write
    a patched copy of an XML scene into `workdir` next to symlinks of the original folder's entries, so relative URLs still
    resolve and the original is never touched. Returns (path_to_render, list_of_defaults_added)."""
    if not scene.lower().endswith(".x3d"):
        return scene, []
    txt = open(scene, encoding="utf-8", errors="replace").read()
    add = []
    if not re.search(r"<(Ortho)?Viewpoint\b", txt):
        add.append("<Viewpoint position='0 0 10'/>")
    if not re.search(r"<Background\b", txt):
        add.append("<Background skyColor='0 0 0'/>")
    m = re.search(r"<Scene\b[^>]*?(?<!/)>", txt)
    if not add or not m:
        return scene, []
    os.makedirs(workdir, exist_ok=True)
    src = os.path.dirname(scene)
    for e in os.listdir(src):
        dst = os.path.join(workdir, e)
        if not os.path.lexists(dst):
            os.symlink(os.path.join(src, e), dst)
    out = os.path.join(workdir, "__patched__" + os.path.basename(scene))
    open(out, "w", encoding="utf-8").write(txt[:m.end()] + "".join(add) + txt[m.end():])
    return out, add


def image_stats(path):
    if not os.path.exists(path):
        return None
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)
    bg = a[0, 0]
    non_bg = float((np.abs(a - bg).sum(axis=2) > 6).mean())
    flat = a.reshape(-1, 3).astype(np.uint8)
    uniq = int(len(np.unique(flat[:, 0].astype(np.uint32) << 16 | flat[:, 1].astype(np.uint32) << 8 | flat[:, 2])))
    return dict(mean_rgb=[round(float(v), 1) for v in a.reshape(-1, 3).mean(axis=0)], corner_rgb=[int(v) for v in bg],
                non_background_share=round(non_bg, 3), unique_colours=uniq, size=list(Image.open(path).size))


def one(item, a):
    name, scene = item
    key = name or os.path.relpath(scene, a.root).replace(os.sep, "__").replace(".x3d", "")
    shot = f"{a.out}/screens/{key}.png"
    glb = f"{a.out}/glb/{key}.glb"
    os.makedirs(os.path.dirname(glb), exist_ok=True)
    conv, view = f"{a.castle}/castle-model-converter", f"{a.castle}/castle-model-viewer"
    row = dict(key=key, scene=os.path.relpath(scene, a.root), bytes=os.path.getsize(scene),
               sha1=hashlib.sha1(open(scene, "rb").read()).hexdigest()[:12])
    rc, out, err, sec, to = run([conv, "--validate", scene], a.timeout)
    warn = [l.strip() for l in (out + "\n" + err).splitlines() if l.strip()]
    row["validate"] = dict(exit=rc, timeout=to, seconds=sec, verdict=("clean" if rc == 0 and not warn else "warnings" if rc is not None else "timeout"),
                           lines=warn[:40], line_count=len(warn))
    rc, out, err, sec, to = run([conv, "--identify", scene], a.timeout)
    ident = (out + err).strip()
    row["identify"] = dict(text=ident[:600], x3d_version=(re.search(r"Loaded as X3D (\S+)", ident) or [None, None])[1],
                           uses_cge_extensions=("does not use any X3D extensions" not in ident))
    env = dict(os.environ)
    render_scene, added = (spec_defaults_copy(scene, f"{a.out}/_patched/{key}") if a.spec_defaults else (scene, []))
    cmd = ["xvfb-run", "-a", "-s", "-screen 0 1600x1200x24", view, "--hide-menu", "--no-sound", "--geometry", f"{a.size}x{a.size}",
           "--screenshot", "0", shot]
    if a.anti_alias:
        cmd += ["--anti-alias", str(a.anti_alias)]
    cmd += a.viewer_args + [render_scene]
    rc, out, err, sec, to = run(cmd, a.timeout, env)
    row["render"] = dict(spec_defaults_added=added, exit=rc, timeout=to, seconds=sec, stderr_lines=[l for l in (out + "\n" + err).splitlines() if l.strip()][:30],
                         png=(os.path.relpath(shot, a.out) if os.path.exists(shot) else None), stats=image_stats(shot))
    rc, out, err, sec, to = run([conv, scene, glb], a.timeout)
    row["glb"] = dict(exit=rc, timeout=to, seconds=sec, bytes=(os.path.getsize(glb) if os.path.exists(glb) else None),
                      path=(os.path.relpath(glb, a.out) if os.path.exists(glb) else None), lines=[l for l in (out + err).splitlines() if l.strip()][:20])
    print(f"{key:72s} validate={row['validate']['verdict']:8s} render={'ok ' if row['render']['png'] else 'FAIL'} {row['render']['seconds']:6.1f}s "
          f"glb={row['glb']['bytes']}", flush=True)
    return row


def main():
    p = argparse.ArgumentParser()
    p.add_argument("scenes")
    p.add_argument("--castle", required=True)
    p.add_argument("--root", default=".", help="scenes are reported relative to this folder")
    p.add_argument("--out", default="results")
    p.add_argument("--size", type=int, default=512)
    p.add_argument("--jobs", type=int, default=3)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--anti-alias", type=int, default=0)
    p.add_argument("--spec-defaults", action="store_true", help="render a patched copy with X3D's default Viewpoint and Background when the scene has none")
    p.add_argument("--viewer-arg", action="append", default=[], dest="viewer_args")
    a = p.parse_args()
    a.root = os.path.abspath(a.root)
    os.makedirs(f"{a.out}/screens", exist_ok=True)
    scenes = []  # one per line: PATH or NAME=PATH (NAME names the outputs, otherwise the path relative to --root does)
    for l in open(a.scenes):
        l = l.strip()
        if l and not l.startswith("#"):
            name, _, path = l.partition("=") if "=" in l and not l.startswith("/") else ("", "", l)
            scenes.append((name, os.path.abspath(path)))
    ver = subprocess.run([f"{a.castle}/castle-model-viewer", "--version"], capture_output=True, text=True).stdout.strip().splitlines()
    t0 = time.time()
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        rows = list(ex.map(lambda s: one(s, a), scenes))
    meta = dict(tool=ver, hardware="no GPU: Mesa llvmpipe (LLVM 20.1.2, 256-bit), 4 vCPU, Xvfb 24-bit", size=a.size, anti_alias=a.anti_alias,
                wall_seconds=round(time.time() - t0, 1), scenes=len(rows))
    json.dump(dict(meta=meta, rows=rows), open(f"{a.out}/matrix.json", "w"), indent=1)
    ok = sum(1 for r in rows if r["render"]["png"])
    print(f"DONE {len(rows)} scenes, {ok} rendered, {meta['wall_seconds']}s wall")


if __name__ == "__main__":
    main()
