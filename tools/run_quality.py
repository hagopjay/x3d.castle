#!/usr/bin/env python3
"""Quality orchestrator: every renderer leg for a list of X3D scenes, scored against a path-traced Cycles reference.

Run (it re-executes itself under the fidelity pipeline's venv python when numpy / flip-evaluator are missing):
    python3 run_quality.py                                   # the public scene set -> qual/public
    python3 run_quality.py --only p2-point-classic,lights-after
    python3 run_quality.py --extra-refs direct,shadows       # two more Cycles references, core legs only
    python3 run_quality.py --scenes FILE --out DIR           # PRIVATE mode: FILE lines NAME=PATH, no rig job needed

Legs per scene (SCENE/ is the scene's folder inside the output folder):
    ref.png              Blender Cycles 5.x CPU, add-on import, 256 spp, seed 0, 12 bounces (tools/cycles_reference.py)
    ref_seed1.png        the same, seed 1: with ref.png it gives the reference's own noise floor (noise_floor.json)
    xite.png             X_ITE on the X3D (the fidelity rig's render.mjs, Chromium + SwiftShader, 512x512)
    babylon_addon.png    Babylon.js on the glb the x3d-blender-io add-on writes (rig blender_leg.py, sRGB colours)
    babylon_castle.png   Babylon.js on our exporter's glb (x3d-castle-convert --no-headlight; the rig adds the headlight)
    castle_native.png    castle-render baseline (Castle Game Engine, Mesa llvmpipe)
    castle_<lever>.png   one Castle quality lever on its own (castle-render; see LEVERS)
    castle_all.png       the combination of the levers that lowered the mean flip_mean against ref.png over this scene set
                         (chosen by this script from its own numbers: in-sample, see castle_all_levers.json)
    ref_direct.png / ref_shadows.png    optional extra references (--extra-refs), core legs only:
                         direct = max-bounces 0 (what X_ITE and Babylon.js can show), shadows = every light casts shadows

The X3D headlight is treated the way the rig treats it: job.headlight is a lux value (headlight on, the scene's
NavigationInfo says so) or null (off). Cycles gets the job (sun lamp along the view), X_ITE reads the scene, Babylon.js gets the
lux from the job, castle-render gets --headlight LUX|off. View: the rig job's `view`, else the X3D default (0 0 10, fov pi/4)
when the job has none; in private mode the scene's own first Viewpoint (cycles_reference.first_viewpoint). Clear colour:
the job's, else the first Background skyColor, else black.

Then tools/quality_metrics.py (imported, same numbers as its `compare`): flip_mean (FLIP LDR, flip-evaluator, 67 ppd),
flip_mean_expnorm, ssim, psnr, mean_abs, mean_abs_geometry per leg against ref.png; the same pair-metrics of each leg against
xite.png (the X_ITE difference); a sheet per scene; results.json.

Resume: an output that exists is never made again; status.json per scene counts attempts. A leg that fails or times out is
retried until --tries attempts are used (default 3) across runs, then skipped and listed; --retry-failed resets the counters.
A scene whose ref.png could not be made is listed as skipped (its other legs still run, it gets no metrics).
Everything runs serially, one process at a time, 2 threads (LP_NUM_THREADS, Cycles --threads, OMP, and taskset for Chromium).

Private scenes: never run this on them with --out inside the public output folder (the script refuses).
"""
import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)                  # x3d.castle
SCRATCH = os.path.dirname(REPO)               # the scratchpad the whole evaluation lives in
sys.path.insert(0, HERE)

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_k, "2")
os.environ.setdefault("LP_NUM_THREADS", "2")

VENV_PY = os.path.join(SCRATCH, "venv-bpy", "v", "bin", "python")
try:
    import numpy as np
    from PIL import Image
    import flip_evaluator  # noqa: F401
    import skimage  # noqa: F401
except ImportError:
    if os.environ.get("RUN_QUALITY_REEXEC") or not os.path.exists(VENV_PY):
        raise
    os.execve(VENV_PY, [VENV_PY] + sys.argv, dict(os.environ, RUN_QUALITY_REEXEC="1"))

import quality_metrics as qm          # noqa: E402
import cycles_reference as cyref      # noqa: E402  (module level has no bpy import; first_viewpoint and friends are reused)

TOOL = "run_quality.py"
TOOL_VERSION = 1

PUBLIC_SCENES = ["stilllife-direct", "stilllife-stage", "materials-world", "lights-after", "village", "earth-planet",
                 "annotation-standard", "p1-point-physical", "p2-point-classic", "p3-directional-classic-i1",
                 "p4-point-quadratic-physical", "p5-directional-physical-i03", "nurbs-weights", "quaternion-xyzw", "repair-2-render"]
RIG_LABELS = ("h2h", "h2h2")                  # rig out/LABEL/jobs.json files that carry the public scenes' views

IBL_DIR = os.path.join(REPO, "castle-render", "ibl_sky_gradient")
# (name, castle-render arguments, group). Groups are what castle_all picks one of; None = never in castle_all.
LEVERS = [
    ("shadows",           ["--shadows"], "shadow"),
    ("shadows2048",       ["--shadows", "--shadow-map-size", "2048"], "shadow"),
    ("ssao",              ["--ssao"], "ssao"),
    ("ssr",               ["--ssr"], "ssr"),
    ("tonemap_aces",      ["--tonemap", "aces"], "tonemap"),
    ("tonemap_uncharted", ["--tonemap", "uncharted"], "tonemap"),
    ("tonemap_hejl",      ["--tonemap", "hejl"], "tonemap"),
    ("shading_phong",     ["--shading", "phong"], "shading"),
    ("shading_gouraud",   ["--shading", "gouraud"], "shading"),
    ("shading_pbr",       ["--shading", "pbr"], "shading"),
    ("msaa4",             ["--msaa", "4"], "aa"),
    ("ssaa2",             ["--ssaa", "2"], "aa"),
    ("ssaa4",             ["--ssaa", "4"], "aa"),
    ("aniso16",           ["--aniso", "16"], "aniso"),
    ("colorspace_linear", ["--colorspace", "linear"], "colorspace"),
    ("colorspace_srgb",   ["--colorspace", "srgb"], "colorspace"),
    ("ibl",               ["--ibl", IBL_DIR], None),    # synthetic sky cubemap, experimental in the engine, camera-locked
]
LEVER_NOTES = {
    "shading_pbr": "shading_pbr converts classic Material to PhysicalMaterial on the node tree (this project's mapping, not Castle's)",
    "ibl": "ibl uses a synthetic sky-gradient cubemap that is not part of the scene; Castle marks EnvironmentLight unfinished and it is camera-locked; never in castle_all",
}
EXTRA_REFS = {"direct": ["--max-bounces", "0"], "shadows": ["--force-shadows"]}
CORE_LEGS = ["ref", "xite", "babylon_addon", "babylon_castle", "castle_native", "castle_shadows", "castle_shadows2048", "castle_all"]
EPS_USEFUL = 1e-4          # a lever is "useful" for castle_all when its mean flip_mean change against castle_native is below -EPS_USEFUL
METRIC_KEYS = ("flip_mean", "flip_mean_expnorm", "exposure_scale", "ssim", "psnr", "mean_abs", "mean_abs_geometry",
               "flip_mean_geometry", "flip_mean_expnorm_geometry", "flip_p95", "geometry_fraction", "warnings")
LOG_PATH = [None]


# ---------------------------------------------------------------------------------------------------------------- utils
def log(msg):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if LOG_PATH[0]:
        with open(LOG_PATH[0], "a") as fh:
            fh.write(line + "\n")


def jdump(obj, path):
    def default(o):
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(type(o))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, default=default)
    os.replace(tmp, path)


def jload(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd, timeout, env=None, cwd=None, log_path=None):
    """Run one process in its own session, kill the whole group on timeout. Returns dict(rc, seconds, timeout, tail)."""
    e = dict(os.environ)
    e.update(env or {})
    t0 = time.time()
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
    lf = open(log_path, "w") if log_path else open(os.devnull, "w")
    try:
        p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=e, cwd=cwd, start_new_session=True)
        try:
            rc, to = p.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
            rc, to = None, True
    except OSError as exc:
        lf.close()
        return dict(rc=127, seconds=round(time.time() - t0, 2), timeout=False, tail=f"cannot start {cmd[0]}: {exc}")
    lf.close()
    tail = ""
    if log_path:
        try:
            tail = open(log_path, errors="replace").read()[-1500:]
        except OSError:
            pass
    return dict(rc=rc, seconds=round(time.time() - t0, 2), timeout=to, tail=tail)


def exists(path):
    return os.path.isfile(path) and os.path.getsize(path) > 0


def floats3(v):
    return ",".join(repr(float(x)) for x in v[:3])


# ---------------------------------------------------------------------------------------------------------------- scenes
class Scene:
    def __init__(self, name, x3d, job, origin, out_root):
        self.name, self.x3d, self.job, self.origin = name, os.path.abspath(x3d), job, origin
        self.dir = os.path.join(out_root, name)
        os.makedirs(self.dir, exist_ok=True)
        self.status_path = os.path.join(self.dir, "status.json")
        self.status = jload(self.status_path, {"legs": {}, "notes": []})
        self.castle_x3d = self.x3d      # the file the Castle legs read (a WebP-free copy when the scene has WebP textures)

    def p(self, *parts):
        return os.path.join(self.dir, *parts)

    def leg(self, name):
        return self.status["legs"].setdefault(name, {})

    def save(self):
        jdump(self.status, self.status_path)


def load_rig_jobs(rig):
    jobs = {}
    for lab in RIG_LABELS:
        for j in jload(os.path.join(rig, "out", lab, "jobs.json"), []):
            jobs.setdefault(j["name"], j)
    return jobs


def parse_scenes_file(path):
    out = []
    for ln in open(path):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if "=" not in ln:
            raise SystemExit(f"{TOOL}: {path}: line {ln!r} is not NAME=PATH")
        n, p = ln.split("=", 1)
        n, p = n.strip(), os.path.abspath(os.path.expanduser(p.strip()))
        if not re.fullmatch(r"[A-Za-z0-9._-]+", n):
            raise SystemExit(f"{TOOL}: scene name {n!r} may only hold letters, digits, . _ -")
        if not os.path.isfile(p):
            raise SystemExit(f"{TOOL}: {n}: scene file not found: {p}")
        out.append((n, p))
    return out


def job_from_scene(name, x3d, headlight_lux, wait):
    """A rig-style job for a scene with no entry in any rig jobs.json (compare.py's rules): the scene's own first Viewpoint
    (None = X3D default), first Background skyColor (else black), headlight lux when NavigationInfo does not switch it off."""
    root = cyref.read_xml(x3d)
    raw = None if root is not None else open(x3d, errors="ignore").read()
    view = cyref.first_viewpoint(root) if root is not None else None
    geo_note = view.pop("_note", None) if view else None      # a GeoViewpoint-only scene: see cycles_reference.geo_viewpoint_local
    sky = cyref.first_background_sky(root, raw)
    on = cyref.navigation_headlight(root, raw)
    return dict(name=name, x3d=x3d, clear=sky if sky is not None else [0.0, 0.0, 0.0],
                headlight=(headlight_lux if on else None), wait=wait, view=view), \
        (geo_note or ("first Viewpoint in the file" if view else "X3D default view (no Viewpoint found" + ("" if root is not None else "; not XML, VRML views are not read here") + ")"))


# ---------------------------------------------------------------------------------------------------------------- legs
class Ctx:
    """Everything a leg needs: options and tool paths."""

    def __init__(self, a):
        self.a = a
        self.py = VENV_PY if os.path.exists(VENV_PY) else sys.executable
        self.rig = os.path.abspath(a.rig)
        self.addon = os.path.abspath(a.addon)
        self.castle_render = os.path.abspath(a.castle_render)
        self.convert = os.path.abspath(a.convert)
        self.cycles = os.path.join(HERE, "cycles_reference.py")
        self.browser = {}                 # versions learnt from render.mjs output


def attempt(sc, leg, outputs, fn, ctx, force_status=False):
    """Run fn() (returns dict(ok, unsupported, rc, seconds, timeout, note, ...)) under the resume and retry rules.
    Returns the leg's status dict. Status: ok | exists | unsupported | failed | timeout | gave_up."""
    st = sc.leg(leg)
    have = all(exists(o) for o in outputs)
    if have and st.get("status") in (None, "ok", "exists", "gave_up"):
        st.setdefault("status", "exists")
        if st["status"] == "gave_up":
            st["status"] = "ok"
        return st
    if st.get("status") == "unsupported":
        return st
    if st.get("attempts", 0) >= ctx.a.tries and st.get("status") in ("failed", "timeout", "gave_up"):
        st["status"] = "gave_up"
        sc.save()
        return st
    while st.get("attempts", 0) < ctx.a.tries:
        st["attempts"] = st.get("attempts", 0) + 1
        log(f"  {sc.name}: {leg} (attempt {st['attempts']}/{ctx.a.tries})")
        res = fn()
        for k in ("rc", "seconds", "note", "error", "seconds_note", "seconds_inproc", "extra"):
            if k in res:
                st[k] = res[k]
        if res.get("ok") and all(exists(o) for o in outputs):
            st["status"] = "ok"
            st.pop("error", None)
            log(f"  {sc.name}: {leg} ok {res.get('seconds')} s")
            break
        if res.get("unsupported"):
            st["status"] = "unsupported"
            log(f"  {sc.name}: {leg} unsupported: {res.get('error')}")
            break
        st["status"] = "timeout" if res.get("timeout") else "failed"
        st["error"] = res.get("error") or (f"timed out after {res.get('seconds')} s" if res.get("timeout") else res.get("tail", "")[-300:])
        log(f"  {sc.name}: {leg} {st['status']} rc={res.get('rc')} {st['error'][-160:]!r}")
    if st.get("status") in ("failed", "timeout") and st.get("attempts", 0) >= ctx.a.tries:
        st["last_failure"], st["status"] = st["status"], "gave_up"
        log(f"  {sc.name}: {leg} gave up after {st['attempts']} attempt(s) ({st['last_failure']})")
    sc.save()
    return st


def leg_cycles(sc, ctx, out_png, extra, view_json, tag):
    def fn():
        cmd = [ctx.py, ctx.cycles, "--x3d", sc.x3d, "--out", out_png, "--view-json", view_json, "--samples", str(ctx.a.samples),
               "--threads", "2", "--addon", ctx.addon] + extra
        r = run(cmd, ctx.a.timeout_cycles, log_path=sc.p("logs", f"{tag}.log"))
        meta = jload(out_png + ".json", {})
        r["ok"] = r["rc"] == 0 and exists(out_png) and bool(meta.get("ok", True))
        r["seconds_inproc"] = (meta.get("seconds") or {}).get("render")
        r["note"] = f"{ctx.a.samples} spp; " + " ".join(extra)
        if not r["ok"] and not r["timeout"]:
            r["error"] = (meta.get("error") or r["tail"])[-300:]
        return r
    return fn


def leg_addon_glb(sc, ctx):
    glb = sc.p("glb", "addon.glb")

    def fn():
        os.makedirs(sc.p("glb"), exist_ok=True)
        r = run([ctx.py, os.path.join(ctx.rig, "blender_leg.py"), ctx.addon, sc.x3d, glb], ctx.a.timeout_glb,
                env={"BLENDER_X3D_COLOR_SPACE": "SRGB"}, log_path=sc.p("logs", "addon_glb.log"))
        line = next((l for l in open(sc.p("logs", "addon_glb.log"), errors="replace").read().splitlines() if l.startswith("LEG ")), None)
        if line:
            try:
                jdump(json.loads(line[4:]), sc.p("glb", "addon.leg.json"))
            except ValueError:
                pass
        r["ok"] = r["rc"] == 0 and exists(glb)
        return r
    return glb, fn


def leg_castle_export(sc, ctx):
    glb = sc.p("glb", "castle.glb")

    def fn():
        os.makedirs(sc.p("glb"), exist_ok=True)
        r = run([ctx.convert, sc.castle_x3d, glb, "--no-headlight", "--verbose"], ctx.a.timeout_convert, log_path=sc.p("logs", "castle_export.log"))
        r["ok"] = r["rc"] == 0 and exists(glb)
        r["note"] = "x3d-castle-convert --no-headlight (default colour space srgb); the rig adds the headlight at the job's lux"
        return r
    return glb, fn


def parse_browser_log(ctx, text):
    for ln in text.splitlines():
        if ln.startswith("BROWSER "):
            ctx.browser["chromium"] = ln.split(" ", 1)[1].strip()
        elif ln.startswith("X_ITE "):
            ctx.browser["x_ite"] = ln.split(" ", 1)[1].strip()
        elif ln.startswith("BABYLON "):
            m = re.search(r'"version":"([^"]+)"', ln)
            if m:
                ctx.browser["babylon"] = m.group(1)


def run_rig(sc, ctx, tag, job, want):
    """One render.mjs call with one job; returns (result, {file: path}) for the files that came out. `want` = names to check."""
    od = sc.p("work", f"rig_{tag}")
    shutil.rmtree(od, ignore_errors=True)       # an old image must never be mistaken for this call's
    os.makedirs(od, exist_ok=True)
    jj = dict(job, outdir=od)
    jf = sc.p("work", f"rig_{tag}_jobs.json")
    jdump([jj], jf)
    cmd = ["node", os.path.join(ctx.rig, "render.mjs"), jf]
    if ctx.a.browser_cpus and shutil.which("taskset"):
        cmd = ["taskset", "-c", ctx.a.browser_cpus] + cmd
    r = run(cmd, ctx.a.timeout_browser, cwd=ctx.rig, log_path=sc.p("logs", f"rig_{tag}.log"))
    txt = open(sc.p("logs", f"rig_{tag}.log"), errors="replace").read()
    parse_browser_log(ctx, txt)
    got = {w: os.path.join(od, w + ".png") for w in want if exists(os.path.join(od, w + ".png"))}
    if len(got) != len(want) and not r["timeout"]:
        r["error"] = "missing " + ",".join(w for w in want if w not in got) + "; " + " | ".join(l for l in txt.splitlines() if "fail" in l or "error" in l.lower())[:300]
    return r, got


def empty_x3d(sc):
    p = sc.p("work", "empty.x3d")
    if not os.path.exists(p):
        os.makedirs(sc.p("work"), exist_ok=True)
        open(p, "w").write("<?xml version='1.0'?><X3D profile='Interchange' version='4.0'><Scene/></X3D>")
    return p


def castle_args(sc, ctx, view_json):
    job = sc.job
    head = "off" if job.get("headlight") is None else repr(float(job["headlight"]))
    return ["--view-json", view_json, "--clear", floats3(job.get("clear") or [0, 0, 0]), "--headlight", head]


def leg_castle_render(sc, ctx, out_png, extra, view_json):
    def fn():
        cmd = ["xvfb-run", "-a", ctx.castle_render, sc.castle_x3d, out_png] + castle_args(sc, ctx, view_json) + extra
        r = run(cmd, ctx.a.timeout_castle, log_path=sc.p("logs", os.path.basename(out_png)[:-4] + ".log"))
        meta = jload(out_png + ".json", {})
        r["ok"] = r["rc"] == 0 and exists(out_png)
        r["seconds_inproc"] = (meta.get("seconds") or {}).get("total")
        w = (meta.get("warnings") or [])
        r["note"] = " ".join(extra) + (f"; {len(w)} castle-render warning(s): {str(w[0])[:140]}" if w else "")
        if r["rc"] == 3:
            r["unsupported"] = True
            r["error"] = (meta.get("error") or r["tail"])[-300:]
        elif not r["ok"] and not r["timeout"]:
            r["error"] = (meta.get("error") or r["tail"])[-300:]
        return r
    return fn


# ---------------------------------------------------------------------------------------------------------------- metrics
def load8(path):
    return qm.load_rgb8(path)[0]


def pair_metrics(sc, ref_name, ref_path, leg_paths, heat=False):
    """{leg: row} metrics of each leg png against ref_path (cached by file hashes in SCENE/metrics_cache.json)."""
    cache_path = sc.p("metrics_cache.json")
    cache = jload(cache_path, {})
    rows = {}
    ref8, ref_sha = None, sha1_file(ref_path)
    changed = False
    for leg, path in leg_paths.items():
        if not exists(path):
            continue
        sha = sha1_file(path)
        key = f"{ref_name}|{ref_sha}|{sha}"
        ent = cache.get(key)
        hm = sc.p("metrics", f"{leg}_flip.png")
        if ent is not None and heat and not exists(hm):
            src = sc.p("metrics", f"{ent.get('heat_label')}_flip.png") if ent.get("heat_label") else None
            if src and exists(src):
                shutil.copy(src, hm)
                shutil.copy(src.replace("_flip.png", "_flip_expnorm.png"), sc.p("metrics", f"{leg}_flip_expnorm.png"))
            else:
                ent = None
        if ent is None:
            if ref8 is None:
                ref8 = load8(ref_path)
            try:
                m, maps = qm.metrics_pair(ref8, load8(path), "auto", None, None, 0, want_maps=heat)
            except qm.Refused as e:
                ent = dict(row=dict(error=str(e)))
            else:
                ent = dict(row=m)
                if heat:
                    os.makedirs(sc.p("metrics"), exist_ok=True)
                    Image.fromarray(qm.heatmap(maps["err"])).save(hm)
                    Image.fromarray(qm.heatmap(maps["err_expnorm"])).save(sc.p("metrics", f"{leg}_flip_expnorm.png"))
                    ent["heat_label"] = leg
            cache[key] = ent
            changed = True
        rows[leg] = ent["row"]
    if changed:
        jdump(cache, cache_path)
    return rows


def trim(row):
    if "error" in row:
        return dict(error=row["error"])
    return {k: row.get(k) for k in METRIC_KEYS if k in row}


def noise_floor(sc):
    a, b = sc.p("ref.png"), sc.p("ref_seed1.png")
    if not (exists(a) and exists(b)):
        return None
    path = sc.p("noise_floor.json")
    sig = sha1_file(a) + sha1_file(b)
    have = jload(path)
    if have and have.get("sig") == sig:
        return have
    a8, b8 = load8(a), load8(b)
    m, _ = qm.metrics_pair(a8, b8, "auto", None, None, 0, want_maps=False, names=("seed 0", "seed 1"))
    out = dict(sig=sig, seeds=[0, 1], what="metrics between the same Cycles render at two seeds (seed 0 plays the reference)", **trim(m))
    jdump(out, path)
    return out


def leg_files(sc, names):
    out = {}
    for n in names:
        p = sc.p(n + ".png")
        if exists(p):
            out[n] = p
    return out


def scene_leg_names(sc, lever_names, with_all=True):
    names = ["xite", "babylon_addon", "babylon_castle", "castle_native"] + [f"castle_{n}" for n in lever_names]
    if with_all:
        names.append("castle_all")
    return names


def do_metrics(sc, ctx, lever_names, with_all=True):
    if not exists(sc.p("ref.png")):
        return None
    paths = leg_files(sc, scene_leg_names(sc, lever_names, with_all))
    res = {"vs_ref": {}, "vs_xite": {}, "vs_ref_extra": {}}
    res["vs_ref"] = {k: trim(v) for k, v in pair_metrics(sc, "ref", sc.p("ref.png"), paths, heat=True).items()}
    if exists(sc.p("xite.png")):
        others = dict(paths)
        others.pop("xite", None)
        others["ref"] = sc.p("ref.png")
        res["vs_xite"] = {k: trim(v) for k, v in pair_metrics(sc, "xite", sc.p("xite.png"), others).items()}
    core = {k: v for k, v in dict(paths, ref=sc.p("ref.png")).items() if k in CORE_LEGS}
    for en in ctx.a.extra_refs:
        rp = sc.p(f"ref_{en}.png")
        if exists(rp):
            res["vs_ref_extra"][en] = {k: trim(v) for k, v in pair_metrics(sc, f"ref_{en}", rp, core).items()}
    return res


def make_sheet(sc, ctx, lever_names, with_all=True):
    paths = leg_files(sc, scene_leg_names(sc, lever_names, with_all))
    if not exists(sc.p("ref.png")) or not paths:
        return None
    out = os.path.join(ctx.sheet_dir, sc.name + ".png")
    sig = sha1_file(sc.p("ref.png")) + "".join(f"{k}{sha1_file(v)}" for k, v in paths.items())
    side = out + ".sig"
    if exists(out) and exists(side) and open(side).read() == sig:
        return out
    cmd = [ctx.py, os.path.join(HERE, "quality_metrics.py"), "sheet", "--ref", sc.p("ref.png"), "--tests"] + list(paths.values()) + \
          ["--labels"] + list(paths.keys()) + ["--out", out, "--tile", str(ctx.a.sheet_tile), "--cols", str(ctx.a.sheet_cols)]
    r = run(cmd, 900, log_path=sc.p("logs", "sheet.log"))
    if r["rc"] in (0, 3) and exists(out):
        open(side, "w").write(sig)
        return out
    log(f"  {sc.name}: sheet failed rc={r['rc']} {r['tail'][-200:]!r}")
    return None


# ---------------------------------------------------------------------------------------------------------------- pipeline
def prepare_scene(sc, ctx, scene_origin_view_note):
    """Write job.json and view.json, make the WebP-free copy for the Castle legs."""
    job = dict(sc.job)
    job["name"], job["x3d"] = sc.name, sc.x3d
    job["glb"] = sc.p("glb", "addon.glb")
    job["outdir"] = sc.p("work", "rig_addon")
    job.setdefault("wait", ctx.a.wait)
    sc.job = job
    ctx_job_headlight_fix(sc)
    jdump(sc.job, sc.p("job.json"))
    view = job.get("view") or dict(cyref.DEFAULT_VIEW)
    jdump(view, sc.p("view.json"))
    sc.status["view_source"] = scene_origin_view_note
    wp = run([ctx.py, os.path.join(HERE, "webp_prepass.py"), sc.x3d, sc.p("work", "webp")], 300, log_path=sc.p("logs", "webp_prepass.log"))
    lines = [l.strip() for l in open(sc.p("logs", "webp_prepass.log"), errors="replace").read().splitlines()]
    hit = next((l for l in lines if l.startswith("/") and os.path.isfile(l)), None)
    if wp["rc"] == 0 and hit:
        sc.castle_x3d = hit
    sc.status["castle_input"] = sc.castle_x3d if sc.castle_x3d != sc.x3d else "scene as is (no WebP textures)"
    sc.save()


def run_scene_legs(sc, ctx, levers, extra_refs_now=False):
    a = ctx.a
    # 1. add-on glb first: its LEG line carries the scene's headlight lux in private mode
    addon_glb, fn = leg_addon_glb(sc, ctx)
    attempt(sc, "addon_glb", [addon_glb], fn, ctx)
    ctx_job_headlight_fix(sc)
    prepare_scene_job_files(sc)
    view_json, job_json = sc.p("view.json"), sc.p("job.json")
    # 2. Cycles reference, seed 1 for the noise floor
    attempt(sc, "ref", [sc.p("ref.png")], leg_cycles(sc, ctx, sc.p("ref.png"), ["--seed", "0"], job_json, "ref"), ctx)
    if exists(sc.p("ref.png")):
        attempt(sc, "ref_seed1", [sc.p("ref_seed1.png")], leg_cycles(sc, ctx, sc.p("ref_seed1.png"), ["--seed", "1"], job_json, "ref_seed1"), ctx)
    # 3. X_ITE + Babylon on the add-on glb: one render.mjs call
    need = [n for n in ("xite", "babylon_addon") if not exists(sc.p(n + ".png"))]
    if need and sc.leg("rig_addon").get("status") != "gave_up":
        def fn_a():
            job = dict(sc.job, glb=addon_glb if exists(addon_glb) else sc.p("glb", "missing.glb"))
            r, got = run_rig(sc, ctx, "addon", job, ["xite", "babylon"])
            if "xite" in got and not exists(sc.p("xite.png")):
                shutil.copy(got["xite"], sc.p("xite.png"))
            if "babylon" in got and not exists(sc.p("babylon_addon.png")):
                shutil.copy(got["babylon"], sc.p("babylon_addon.png"))
                for extra in ("babylon_mask.png", "babylon_mask_green.png"):
                    if exists(os.path.join(os.path.dirname(got["babylon"]), extra)):
                        shutil.copy(os.path.join(os.path.dirname(got["babylon"]), extra), sc.p("work", "addon_" + extra))
            r["ok"] = exists(sc.p("xite.png")) and exists(sc.p("babylon_addon.png"))
            r["seconds_note"] = (f"wall of one render.mjs call (Chromium launch + X_ITE incl. its fixed {sc.job.get('wait')} ms wait + "
                                 f"Babylon.js + mask renders); X_ITE and Babylon.js are not separable")
            return r
        # xite and babylon_addon share one render.mjs call: the retry counters live on 'rig_addon', the two legs derive their status
        st_call = attempt(sc, "rig_addon", [sc.p("xite.png"), sc.p("babylon_addon.png")], fn_a, ctx)
        for n in ("xite", "babylon_addon"):
            s = sc.leg(n)
            s.update({k: v for k, v in st_call.items() if k in ("seconds", "seconds_note", "attempts", "rc", "error")})
            s["status"] = "ok" if exists(sc.p(n + ".png")) else st_call.get("status")
            if s["status"] == "ok":
                s.pop("error", None)
        sc.save()
    else:
        for n in ("xite", "babylon_addon"):
            if exists(sc.p(n + ".png")):
                sc.leg(n).setdefault("status", "exists")
    # 4. our exporter's glb, then Babylon.js on it
    cglb, fn = leg_castle_export(sc, ctx)
    attempt(sc, "castle_export", [cglb], fn, ctx)
    if exists(cglb):
        def fn_b():
            job = dict(sc.job, x3d=empty_x3d(sc), glb=cglb, wait=200)
            r, got = run_rig(sc, ctx, "castle", job, ["babylon"])
            if "babylon" in got:
                shutil.copy(got["babylon"], sc.p("babylon_castle.png"))
            r["ok"] = exists(sc.p("babylon_castle.png"))
            r["seconds_note"] = "wall of one render.mjs call on an empty X3D plus the glb: Chromium launch + Babylon.js + mask renders; exporter seconds are on castle_export"
            return r
        attempt(sc, "babylon_castle", [sc.p("babylon_castle.png")], fn_b, ctx)
    # 5. Castle: native, then each lever alone
    attempt(sc, "castle_native", [sc.p("castle_native.png")], leg_castle_render(sc, ctx, sc.p("castle_native.png"), [], view_json), ctx)
    for name, args, _grp in levers:
        out = sc.p(f"castle_{name}.png")
        st = attempt(sc, f"castle_{name}", [out], leg_castle_render(sc, ctx, out, args, view_json), ctx)
        if name in LEVER_NOTES and st.get("status") in ("ok", "exists"):
            st["lever_note"] = LEVER_NOTES[name]


def ctx_job_headlight_fix(sc):
    """Private mode only: the job's headlight lux comes from the add-on import (scene property x3d_headlight_lux), the way
    the rig's compare.py does it, when the scene has the headlight on."""
    if sc.origin != "scene-file":
        return
    leg = jload(sc.p("glb", "addon.leg.json"), {})
    lux = leg.get("headlight_lux")
    if sc.job.get("headlight") is not None:
        sc.job["headlight"] = float(lux) if lux else 1.0
        sc.status["headlight_lux_source"] = "add-on scene property x3d_headlight_lux" if lux else "default 1.0 (the add-on import gave no value)"
        sc.save()


def prepare_scene_job_files(sc):
    jdump(dict(sc.job), sc.p("job.json"))


def choose_all_combo(scenes, lever_names, ctx, out_root):
    """castle_all: from the per-scene metrics against ref.png pick, per lever group, the lever with the lowest mean flip_mean
    change against castle_native (over the scenes where both rendered), if that change is below -EPS_USEFUL."""
    path = os.path.join(out_root, "castle_all_levers.json")
    have = jload(path)
    names = sorted(s.name for s in scenes)
    if have and not ctx.a.recompute_all and have.get("scenes") == names:
        return have
    table = {}
    for name, _args, grp in LEVERS:
        if name not in lever_names:
            continue
        deltas, n_native = [], []
        for sc in scenes:
            m = sc.metrics_ref or {}
            if "castle_native" in m and f"castle_{name}" in m and "flip_mean" in m["castle_native"] and "flip_mean" in m[f"castle_{name}"]:
                deltas.append(m[f"castle_{name}"]["flip_mean"] - m["castle_native"]["flip_mean"])
        table[name] = dict(group=grp, n_scenes=len(deltas), mean_delta_flip=(float(np.mean(deltas)) if deltas else None),
                           scenes_better=int(sum(d < -EPS_USEFUL for d in deltas)), scenes_worse=int(sum(d > EPS_USEFUL for d in deltas)))
    chosen = []
    for grp in sorted({g for _, _, g in LEVERS if g}):
        cands = [(v["mean_delta_flip"], k) for k, v in table.items() if v["group"] == grp and v["mean_delta_flip"] is not None]
        if cands:
            d, k = min(cands)
            if d < -EPS_USEFUL:
                chosen.append(k)
    doc = dict(chosen=chosen, rule=f"per group, the lever with the lowest mean (flip_mean(lever) - flip_mean(castle_native)) against ref.png over the "
                                  f"scenes where both rendered, kept when that mean is below -{EPS_USEFUL}; ibl is never in the combination. "
                                  f"In-sample: the same scenes choose and score it.", table=table,
               n_scenes=len(scenes), scenes=names)
    jdump(doc, path)
    if have and have.get("chosen") != chosen:
        for sc in scenes:    # a different combination: the old castle_all renders are stale
            if exists(sc.p("castle_all.png")):
                os.remove(sc.p("castle_all.png"))
            sc.status["legs"].pop("castle_all", None)
            sc.save()
    return doc


def run_castle_all(sc, ctx, chosen, view_json):
    levs = {n: args for n, args, _ in LEVERS}
    used, dropped = [], []
    for n in chosen:
        st = sc.leg(f"castle_{n}")
        if st.get("status") in ("ok", "exists") and exists(sc.p(f"castle_{n}.png")):
            used.append(n)
        else:
            dropped.append(f"{n} ({st.get('status', 'not run')})")
    args = []
    for n in used:
        args += levs[n]
    # duplicate option names would be a bug in the table: shadows2048 and shadows never co-occur (same group)
    out = sc.p("castle_all.png")
    st = attempt(sc, "castle_all", [out], leg_castle_render(sc, ctx, out, args, view_json), ctx)
    st["levers_used"], st["levers_dropped"] = used, dropped
    sc.save()


def extra_ref_phase(sc, ctx):
    job_json = sc.p("job.json")
    if ctx.a.extra_refs_scenes and sc.name not in ctx.a.extra_refs_scenes.split(","):
        return
    for en in ctx.a.extra_refs:
        out = sc.p(f"ref_{en}.png")
        attempt(sc, f"ref_{en}", [out], leg_cycles(sc, ctx, out, ["--seed", "0"] + EXTRA_REFS[en], job_json, f"ref_{en}"), ctx)


# ---------------------------------------------------------------------------------------------------------------- results
def tool_version_line(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return (r.stdout + r.stderr).strip().splitlines()[0][:200]
    except Exception:  # noqa: BLE001
        return None


def gather_metadata(ctx, scenes, out_root, lever_names):
    a = ctx.a
    first_ref = next((jload(sc.p("ref.png.json")) for sc in scenes if exists(sc.p("ref.png.json"))), None) or {}
    first_cr = next((jload(sc.p("castle_native.png.json")) for sc in scenes if exists(sc.p("castle_native.png.json"))), None) or {}
    cpu = next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), None)
    mem = next((int(l.split()[1]) // 1024 for l in open("/proc/meminfo") if l.startswith("MemTotal")), None)
    bj = jload(os.path.join(out_root, "browser_versions.json"), {})
    if ctx.browser:
        bj.update(ctx.browser)
        jdump(bj, os.path.join(out_root, "browser_versions.json"))
    rig_commit = tool_version_line(["git", "-C", ctx.rig, "log", "-1", "--format=%H %cd"])
    commit, dirty = cyref.addon_commit(ctx.addon)
    files = {n: sha1_file(p)[:12] for n, p in (("run_quality.py", os.path.abspath(__file__)), ("cycles_reference.py", ctx.cycles),
                                               ("quality_metrics.py", os.path.join(HERE, "quality_metrics.py")),
                                               ("webp_prepass.py", os.path.join(HERE, "webp_prepass.py")),
                                               ("castle-render (binary)", ctx.castle_render), ("x3d-castle-convert (binary)", ctx.convert),
                                               ("castle_render.dpr", os.path.join(REPO, "castle-convert", "castle_render.dpr")),
                                               ("x3dcastleexport.pas", os.path.join(REPO, "castle-convert", "x3dcastleexport.pas"))) if os.path.exists(p)}
    return dict(
        tool=f"{TOOL} v{TOOL_VERSION}", date_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        reference=dict(renderer="Blender Cycles (CPU, bundled with Blender)", blender=first_ref.get("blender"), addon_commit=commit, addon_dirty=dirty,
                       addon_version=(first_ref.get("addon") or {}).get("version"), samples=a.samples, seeds=[0, 1], denoise="none",
                       bounces="Cycles default (12)", light_size="ideal (radius 0 / angle 0)", colour_management="Standard view transform, sRGB display, exposure 0",
                       extra_refs={n: EXTRA_REFS[n] for n in a.extra_refs}, noise_floor="seed 0 vs seed 1, metrics from quality_metrics.py"),
        legs=dict(x_ite=bj.get("x_ite"), babylon=bj.get("babylon"), chromium=bj.get("chromium"), browser_gpu="SwiftShader (software), 512x512",
                  rig=dict(path=ctx.rig, git=rig_commit), addon_glb="rig blender_leg.py, BLENDER_X3D_COLOR_SPACE=SRGB, COMPAT light units",
                  castle=dict(engine=first_cr.get("castle_version"), fpc=first_cr.get("fpc"), gl_renderer=first_cr.get("gl_renderer"),
                              gl_version=first_cr.get("gl_version"), tool=first_cr.get("tool"),
                              viewer="castle-model-viewer / castle-model-converter 5.3.0 (bundle), castle-render built from castle_render.dpr"),
                  castle_levers=lever_names, ibl_cubemap=IBL_DIR),
        metrics=dict(versions=qm.versions(), flip="LDR-FLIP, 67 ppd default, sRGB 8-bit inputs", background_rule="quality_metrics.py --mask auto",
                     expnorm_note="expnorm can be worse than plain FLIP (see quality_metrics.py docstring); read it only when exposure_scale is clearly away from 1"),
        hardware=dict(cpu=cpu, vcpus=os.cpu_count(), ram_mb=mem, gpu="none", os=platform.platform(), threads="LP_NUM_THREADS=2, Cycles threads 2, OMP 2, Chromium taskset " + str(a.browser_cpus),
                      load_avg_at_write=os.getloadavg()),
        timeouts_s=dict(cycles=a.timeout_cycles, glb=a.timeout_glb, browser=a.timeout_browser, castle=a.timeout_castle, convert=a.timeout_convert),
        tries=a.tries, tool_files_sha1_12=files)


def mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return (float(sum(xs) / len(xs)) if xs else None), len(xs)


def build_results(ctx, scenes, out_root, lever_names, combo, skipped):
    res = dict(metadata=gather_metadata(ctx, scenes, out_root, lever_names), castle_all=combo, scenes={}, summary={}, skipped=skipped)
    legs_seen = []
    for sc in scenes:
        ref_meta = jload(sc.p("ref.png.json"), {})
        ent = dict(x3d=sc.x3d, origin=sc.origin, view_source=sc.status.get("view_source"), view=sc.job.get("view"), clear=sc.job.get("clear"),
                   headlight_lux=sc.job.get("headlight"), castle_input=sc.status.get("castle_input"),
                   cycles=dict(lights=ref_meta.get("light_count"), importer_warnings=(ref_meta.get("importer") or {}).get("warnings"),
                               warnings=ref_meta.get("warnings"), census=(ref_meta.get("importer") or {}).get("census"),
                               seconds=ref_meta.get("seconds")),
                   noise_floor=noise_floor(sc), legs={})
        m = getattr(sc, "metrics_all", None) or {}
        names = ["ref", "ref_seed1", "xite", "babylon_addon", "babylon_castle", "castle_export", "addon_glb", "castle_native"] + \
                [f"castle_{n}" for n in lever_names] + ["castle_all"] + [f"ref_{e}" for e in ctx.a.extra_refs]
        for leg in names:
            st = dict(sc.status["legs"].get(leg, {}))
            if not st and not exists(sc.p(leg + ".png")):
                continue
            row = dict(status=st.get("status", "exists" if exists(sc.p(leg + ".png")) else "missing"),
                       seconds=st.get("seconds"), seconds_inproc=st.get("seconds_inproc"), seconds_note=st.get("seconds_note"),
                       attempts=st.get("attempts"), note=st.get("note"), error=st.get("error"))
            if leg == "castle_all":
                row["levers_used"], row["levers_dropped"] = st.get("levers_used"), st.get("levers_dropped")
            if st.get("lever_note"):
                row["lever_note"] = st["lever_note"]
            if exists(sc.p(leg + ".png")):
                row["png"] = sc.p(leg + ".png")
                row["sha1_12"] = sha1_file(sc.p(leg + ".png"))[:12]
            if leg in (m.get("vs_ref") or {}):
                row["vs_ref"] = m["vs_ref"][leg]
            if leg in (m.get("vs_xite") or {}):
                row["vs_xite"] = m["vs_xite"][leg]
            for en, tab in (m.get("vs_ref_extra") or {}).items():
                if leg in tab:
                    row[f"vs_ref_{en}"] = tab[leg]
            ent["legs"][leg] = row
            if leg not in legs_seen and leg not in ("ref_seed1", "castle_export", "addon_glb"):
                legs_seen.append(leg)
        nat = ent["legs"].get("castle_native", {})
        for leg, row in ent["legs"].items():
            if leg.startswith("castle_") and leg != "castle_native" and row.get("sha1_12") and row.get("sha1_12") == nat.get("sha1_12"):
                row["identical_to"] = "castle_native"
        res["scenes"][sc.name] = ent
    # summary: per leg means over the scenes where the leg has numbers; castle levers also against native on the same scenes
    for leg in legs_seen:
        s = dict()
        for block in ("vs_ref", "vs_xite", "vs_ref_direct", "vs_ref_shadows"):
            rows = [(n, e["legs"][leg][block]) for n, e in res["scenes"].items() if leg in e["legs"] and isinstance(e["legs"][leg].get(block), dict)
                    and "flip_mean" in e["legs"][leg][block]]
            if not rows:
                continue
            b = dict(n_scenes=len(rows))
            for k in ("flip_mean", "flip_mean_expnorm", "ssim", "psnr", "mean_abs", "mean_abs_geometry"):
                b["mean_" + k], _ = mean([r.get(k) for _, r in rows])
            if leg.startswith("castle_") and leg != "castle_native":
                # castle_native over the same scenes (levers can be unsupported on some), so a lever's mean is read against its own baseline
                nat_rows = {n: (res["scenes"][n]["legs"].get("castle_native") or {}).get(block) or {} for n, _ in rows}
                same = [n for n, _ in rows if "flip_mean" in nat_rows[n]]
                if same:
                    b["mean_flip_mean_castle_native_same_scenes"], _ = mean([nat_rows[n]["flip_mean"] for n in same])
                    b["mean_flip_mean_expnorm_castle_native_same_scenes"], _ = mean([nat_rows[n]["flip_mean_expnorm"] for n in same])
                b["scenes"] = [n for n, _ in rows]
            s[block] = b
        sc_status = {}
        for n, e in res["scenes"].items():
            st = e["legs"].get(leg, {}).get("status")
            sc_status[st] = sc_status.get(st, 0) + 1
        s["status_counts"] = sc_status
        res["summary"][leg] = s
    # common-scene summary: the means above use different scene sets per leg (levers can be unsupported); also the mean over the
    # scenes every one of the core legs and castle_native have, so the core legs are comparable with each other
    common = [n for n, e in res["scenes"].items() if all(isinstance((e["legs"].get(l, {}).get("vs_ref") or {}).get("flip_mean"), float)
                                                         for l in ("xite", "babylon_addon", "babylon_castle", "castle_native"))]
    res["summary_common_core_scenes"] = dict(scenes=common)
    for leg in ("xite", "babylon_addon", "babylon_castle", "castle_native", "castle_all"):
        rows = [res["scenes"][n]["legs"][leg]["vs_ref"] for n in common if leg in res["scenes"][n]["legs"] and "flip_mean" in (res["scenes"][n]["legs"][leg].get("vs_ref") or {})]
        res["summary_common_core_scenes"][leg] = dict(n_scenes=len(rows), mean_flip_mean=mean([r["flip_mean"] for r in rows])[0],
                                                      mean_flip_mean_expnorm=mean([r["flip_mean_expnorm"] for r in rows])[0])
    nf = [e["noise_floor"] for e in res["scenes"].values() if e.get("noise_floor") and "flip_mean" in e["noise_floor"]]
    res["summary_noise_floor"] = dict(n_scenes=len(nf), mean_flip_mean=mean([x["flip_mean"] for x in nf])[0], max_flip_mean=(max(x["flip_mean"] for x in nf) if nf else None),
                                      mean_ssim=mean([x["ssim"] for x in nf])[0], mean_mean_abs=mean([x["mean_abs"] for x in nf])[0])
    return res


def summary_text(res):
    L = []
    L.append("per-leg mean over the scenes that have the leg (n), against ref.png (Cycles, GI on, 256 spp); and each leg against xite.png")
    L.append(f"{'leg':26s} {'n':>3s} {'flip_mean':>9s} {'flip_expnorm':>12s} {'ssim':>7s} {'psnr':>6s} {'|d|':>6s} {'|d|geo':>7s} | vs X_ITE: {'|d|':>6s} {'|d|geo':>7s} {'flip':>7s}")
    for leg, s in res["summary"].items():
        b = s.get("vs_ref")
        x = s.get("vs_xite")
        if not b and not x:
            continue
        left = (f"{leg:26s} {b['n_scenes']:3d} {b['mean_flip_mean']:9.4f} {b['mean_flip_mean_expnorm']:12.4f} {b['mean_ssim']:7.4f} "
                f"{b['mean_psnr']:6.2f} {b['mean_mean_abs']:6.2f} {b['mean_mean_abs_geometry']:7.2f}") if b else f"{leg:26s} {'-':>3s}"
        right = f"{x['mean_mean_abs']:6.2f} {x['mean_mean_abs_geometry']:7.2f} {x['mean_flip_mean']:7.4f}" if x else "-"
        L.append(f"{left} | {right}")
    common = res.get("summary_common_core_scenes", {})
    L.append("")
    L.append(f"core legs over the {len(common.get('scenes', []))} scenes where xite, babylon_addon, babylon_castle and castle_native all have numbers:")
    for leg in ("xite", "babylon_addon", "babylon_castle", "castle_native", "castle_all"):
        c = common.get(leg)
        if c and c.get("mean_flip_mean") is not None:
            L.append(f"  {leg:18s} n={c['n_scenes']:2d} mean flip_mean {c['mean_flip_mean']:.4f}  mean flip_mean_expnorm {c['mean_flip_mean_expnorm']:.4f}")
    nf = res.get("summary_noise_floor", {})
    if nf.get("n_scenes"):
        L.append(f"reference noise floor (Cycles seed 0 vs seed 1): mean flip_mean {nf['mean_flip_mean']:.4f}, max {nf['max_flip_mean']:.4f} over {nf['n_scenes']} scenes")
    L.append("")
    cols = ["ref(vs xite)", "xite", "babylon_addon", "babylon_castle", "castle_native", "castle_all"]
    L.append("per scene flip_mean against ref.png (noise floor in the last column; ref(vs xite) = Cycles ref against xite.png)")
    L.append(f"{'scene':30s} " + " ".join(f"{c:>14s}" for c in cols) + f" {'noise_floor':>12s}")
    for n, e in res["scenes"].items():
        vals = []
        for c in cols:
            if c == "ref(vs xite)":
                v = ((e["legs"].get("ref") or {}).get("vs_xite") or {}).get("flip_mean")
            else:
                v = ((e["legs"].get(c) or {}).get("vs_ref") or {}).get("flip_mean")
            vals.append(f"{v:14.4f}" if isinstance(v, float) else f"{'-':>14s}")
        nfv = (e.get("noise_floor") or {}).get("flip_mean")
        L.append(f"{n:30s} " + " ".join(vals) + (f" {nfv:12.4f}" if isinstance(nfv, float) else f" {'-':>12s}"))
    L.append("")
    if res.get("castle_all"):
        L.append("castle_all levers: " + ", ".join(res["castle_all"]["chosen"]) + "   (" + res["castle_all"]["rule"] + ")")
    L.append("skipped / failed legs: " + (json.dumps(res["skipped"], indent=1) if res["skipped"] else "none"))
    return "\n".join(L)


def print_table(res, path=None):
    txt = summary_text(res)
    print("\n" + txt)
    if path:
        with open(path, "w") as fh:
            fh.write(txt + "\n")


# ---------------------------------------------------------------------------------------------------------------- main
def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="output folder (default for the public set: qual/public next to this repo)")
    ap.add_argument("--scenes", help="PRIVATE mode: file with NAME=PATH lines; the view comes from the scene's first Viewpoint; --out is required")
    ap.add_argument("--only", help="comma list of scene names to run")
    ap.add_argument("--samples", type=int, default=256, help="Cycles samples per pixel (default 256, from the noise-floor study)")
    ap.add_argument("--extra-refs", default="", help="comma list of extra Cycles references: direct (no indirect light), shadows (all lights cast shadows)")
    ap.add_argument("--extra-refs-scenes", default="", help="comma list of scene names that get the extra references (default: every scene of the run); "
                                                            "the others are left without them (slow scenes)")
    ap.add_argument("--levers", default="all", help="all | none | comma list of lever names")
    ap.add_argument("--tries", type=int, default=3, help="attempts per leg before it is skipped (counted across runs)")
    ap.add_argument("--retry-failed", action="store_true", help="reset the attempt counters of failed / timed-out legs")
    ap.add_argument("--recompute-all", action="store_true", help="choose the castle_all combination again (deletes castle_all.png first)")
    ap.add_argument("--timeout-cycles", type=int, default=1200)
    ap.add_argument("--timeout-glb", type=int, default=600)
    ap.add_argument("--timeout-browser", type=int, default=600)
    ap.add_argument("--timeout-castle", type=int, default=180)
    ap.add_argument("--timeout-convert", type=int, default=300)
    ap.add_argument("--browser-cpus", default="0-1", help="taskset CPU list for Chromium (2 threads); '' disables")
    ap.add_argument("--wait", type=int, default=2500, help="X_ITE wait in ms for scenes without a rig job (private mode)")
    ap.add_argument("--sheet-tile", type=int, default=256)
    ap.add_argument("--sheet-cols", type=int, default=6)
    ap.add_argument("--rig", default=os.path.join(SCRATCH, "repos", "x3d-blender-io", "tools", "fidelity_rig"))
    ap.add_argument("--addon", default=os.path.join(SCRATCH, "repos", "x3d-blender-io", "source"))
    ap.add_argument("--castle-render", default=os.path.join(REPO, "castle-render", "castle-render"))
    ap.add_argument("--convert", default=os.path.join(REPO, "castle-convert", "x3d-castle-convert"))
    ap.add_argument("--metrics-only", action="store_true", help="make no renders: recompute metrics, sheets and results.json from what exists")
    ap.add_argument("--list", action="store_true", help="print the scene list and the lever list and exit")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    public_out = os.path.join(SCRATCH, "qual", "public")
    private_mode = bool(a.scenes)
    if private_mode:
        if not a.out:
            raise SystemExit(f"{TOOL}: --scenes needs --out DIR")
        out_root = os.path.realpath(os.path.abspath(a.out))
        if os.path.commonpath([out_root, os.path.realpath(public_out)]) == os.path.realpath(public_out):
            raise SystemExit(f"{TOOL}: refusing --out {out_root}: private scenes must not be written under {public_out}")
    else:
        out_root = os.path.abspath(a.out or public_out)
    os.makedirs(out_root, exist_ok=True)
    LOG_PATH[0] = os.path.join(out_root, "run_quality.log")
    a.extra_refs = [e for e in a.extra_refs.split(",") if e]
    for e in a.extra_refs:
        if e not in EXTRA_REFS:
            raise SystemExit(f"{TOOL}: unknown extra reference {e!r} (have {', '.join(EXTRA_REFS)})")
    lever_names = [n for n, _, _ in LEVERS] if a.levers == "all" else ([] if a.levers == "none" else a.levers.split(","))
    bad = [n for n in lever_names if n not in {x[0] for x in LEVERS}]
    if bad:
        raise SystemExit(f"{TOOL}: unknown lever(s) {bad}")
    levers = [x for x in LEVERS if x[0] in lever_names]
    ctx = Ctx(a)
    ctx.sheet_dir = os.path.join(out_root, "sheets")
    os.makedirs(ctx.sheet_dir, exist_ok=True)

    # ---- scene list (the --only filter runs before any scene folder is made)
    entries = []        # (name, x3d, job, origin, view_note)
    if private_mode:
        for name, path in parse_scenes_file(a.scenes):
            job, note = job_from_scene(name, path, 1.0, a.wait)
            entries.append((name, path, job, "scene-file", note))
    else:
        jobs = load_rig_jobs(ctx.rig)
        for name in PUBLIC_SCENES:
            if name not in jobs:
                raise SystemExit(f"{TOOL}: scene {name} has no job in {ctx.rig}/out/{{{','.join(RIG_LABELS)}}}/jobs.json")
            j = jobs[name]
            entries.append((name, j["x3d"], j, "rig jobs.json",
                            "rig job view" if j.get("view") else "X3D default view (the rig job has none: the scene has no Viewpoint)"))
    if a.only:
        keep = set(a.only.split(","))
        unknown = keep - {e[0] for e in entries}
        if unknown:
            raise SystemExit(f"{TOOL}: unknown scene(s) {sorted(unknown)}")
        entries = [e for e in entries if e[0] in keep]
    scenes = []
    for name, x3d, job, origin, note in entries:
        sc = Scene(name, x3d, job, origin, out_root)
        sc.view_note = note
        scenes.append(sc)
    if a.list:
        print("scenes:", *[f"\n  {s.name}  {s.x3d}" for s in scenes])
        print("\nlevers:", *[f"\n  castle_{n}  {' '.join(args)}  [{g}]" for n, args, g in LEVERS])
        return 0
    if a.retry_failed:
        for sc in scenes:
            for st in sc.status["legs"].values():
                if st.get("status") in ("failed", "timeout", "gave_up"):
                    st["attempts"], st["status"] = 0, "retry"
            sc.save()

    log(f"=== run_quality: {len(scenes)} scene(s) -> {out_root} ({'PRIVATE mode' if private_mode else 'public set'}), samples {a.samples}, extra refs {a.extra_refs or 'none'}, "
        f"{len(levers)} levers, tries {a.tries}")
    t_all = time.time()
    # ---- phase A: per scene, every leg except castle_all; metrics against ref for the lever choice
    for i, sc in enumerate(scenes, 1):
        log(f"--- [{i}/{len(scenes)}] {sc.name}")
        sc.metrics_ref, sc.metrics_all = None, None
        prepare_scene(sc, ctx, sc.view_note)
        if not a.metrics_only:
            try:
                run_scene_legs(sc, ctx, levers)
            except Exception as exc:  # noqa: BLE001
                log(f"  {sc.name}: orchestrator error {type(exc).__name__}: {exc}")
                sc.status["notes"].append(f"orchestrator error: {type(exc).__name__}: {exc}")
                sc.save()
        m = do_metrics(sc, ctx, lever_names, with_all=False)
        sc.metrics_all = m
        sc.metrics_ref = (m or {}).get("vs_ref")
        if m and "ref" not in {k for k in m["vs_ref"]}:
            pass
        fm = {k: round(v["flip_mean"], 4) for k, v in (sc.metrics_ref or {}).items() if "flip_mean" in v}
        log(f"  {sc.name}: flip_mean " + ", ".join(f"{k} {v}" for k, v in list(fm.items())[:6]) + (" ..." if len(fm) > 6 else ""))
    # ---- phase B: choose the castle_all combination
    combo = None
    ranked = [sc for sc in scenes if sc.metrics_ref]
    if "castle_native" in {k for sc in ranked for k in sc.metrics_ref} and levers:
        if a.recompute_all:
            for sc in scenes:
                if exists(sc.p("castle_all.png")):
                    os.remove(sc.p("castle_all.png"))
                sc.status["legs"].pop("castle_all", None)
        combo = choose_all_combo(ranked, lever_names, ctx, out_root)
        log(f"=== castle_all = {combo['chosen']}")
    # ---- phase C: castle_all per scene, final metrics, sheet
    skipped = []
    for sc in scenes:
        if combo is not None and not a.metrics_only:
            run_castle_all(sc, ctx, combo["chosen"], sc.p("view.json"))
        sc.metrics_all = do_metrics(sc, ctx, lever_names, with_all=True)
        if not exists(sc.p("ref.png")):
            skipped.append(dict(scene=sc.name, reason=f"ref.png missing: {sc.leg('ref').get('status')} after {sc.leg('ref').get('attempts')} attempt(s)",
                                error=sc.leg("ref").get("error")))
        for leg, st in sc.status["legs"].items():
            if st.get("status") in ("failed", "timeout", "gave_up") and leg != "rig_addon":
                skipped.append(dict(scene=sc.name, leg=leg, status=st["status"], attempts=st.get("attempts"), error=(st.get("error") or "")[-200:]))
        if not a.metrics_only or True:
            make_sheet(sc, ctx, lever_names)
    out = build_results(ctx, scenes, out_root, lever_names, combo, skipped)
    jdump(out, os.path.join(out_root, "results.json"))
    log(f"=== phase A-C done in {time.time() - t_all:.0f} s; results.json written")
    # ---- phase D: extra references (core legs only), appended to the same results.json
    if a.extra_refs:
        for sc in scenes:
            if not a.metrics_only:
                extra_ref_phase(sc, ctx)
            sc.metrics_all = do_metrics(sc, ctx, lever_names, with_all=True)
        skipped2 = []
        for sc in scenes:
            if not exists(sc.p("ref.png")):
                skipped2.append(dict(scene=sc.name, reason="ref.png missing"))
            for leg, st in sc.status["legs"].items():
                if st.get("status") in ("failed", "timeout", "gave_up") and leg != "rig_addon":
                    skipped2.append(dict(scene=sc.name, leg=leg, status=st["status"], attempts=st.get("attempts"), error=(st.get("error") or "")[-200:]))
        out = build_results(ctx, scenes, out_root, lever_names, combo, skipped2)
        jdump(out, os.path.join(out_root, "results.json"))
        log("=== extra references done; results.json rewritten")
    print_table(out, os.path.join(out_root, "summary.txt"))
    log(f"=== all done in {time.time() - t_all:.0f} s. skipped/failed: {len(out['skipped'])}")
    for s in out["skipped"]:
        log(f"   SKIPPED {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
