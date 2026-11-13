#!/usr/bin/env python3
"""Path-traced reference render of an X3D scene: the x3d-blender-io add-on imports it, Blender Cycles (CPU) renders it.

Licence note: about ten lines of the Viewpoint maths in first_viewpoint() adapt tools/fidelity_rig/compare.py from x3d-blender-io
(same owner, GPL-3 add-on). Keep that in mind before reusing this file outside this repository.

Run with a Python that has bpy (the fidelity pipeline's venv):
    python cycles_reference.py --x3d SCENE.x3d --out OUT.png \
        [--job-json JOBS.json --job-name NAME | --view-json FILE] [--samples 256] [--size 512] [--threads 2] [--seed 0] \
        [--denoise none|oidn] [--light-units xite|blender] [--clear R,G,B] [--headlight off|LUX] [--addon ADDON_SRC]

What it does, in order:
  1. Registers the add-on the way fidelity_rig/blender_leg.py does (symlink the source folder in as io_scene_x3d, register,
     read_factory_settings(use_empty=True), register again) and imports the file with bpy.ops.import_scene.x3d, colour space
     SRGB and light units X_ITE (or BLENDER with --light-units blender). The importer's own camera is not used.
  2. Camera: from the rig job's `view` (position, forward, up in X3D coordinates, fov = X3D fieldOfView in radians, which X3D
     applies to the SMALLER image side) or from --view-json (same dict, or a whole job) or, with neither, from the first
     Viewpoint/OrthoViewpoint in document order (the one a browser binds first), else X3D's default (0 0 10, looking down -Z,
     fov pi/4). X3D coordinates become Blender's with the add-on's own axis conversion (X3D -Z forward / Y up -> Blender Y / Z).
  3. World: the clear colour (--clear, else the job's `clear`, else the first Background's first skyColor, else black), seen by
     camera rays only. It emits no light: an X3D Background does not light a scene, a Blender world does. Reflections and
     indirect rays see black. The colour is a display (sRGB) value, as in the web renderers, and is stored linear.
  4. Headlight: an X3D headlight is a sun lamp along the view direction, strength = lux (the add-on's convention, sun W/m2 =
     glTF lux, which the rig uses for Babylon.js). Lux comes from --headlight, else the job's `headlight` (null = off), else
     with no job the scene's x3d_headlight_lux when the first NavigationInfo does not switch the headlight off.
  5. Colour management: view transform Standard, look None, exposure 0, gamma 1, sRGB display, dither 0: display-referred like
     the web renderers. Output is 8-bit sRGB PNG (RGB, no alpha).
  6. Cycles CPU, fixed samples (adaptive sampling off unless --adaptive), Cycles' default light paths otherwise (12 bounces:
     indirect light is part of the render, which X_ITE and Babylon.js do not have; --max-bounces 0 gives direct light only, the
     apples-to-apples case). No denoise unless --denoise oidn. X3D lights cast no shadows unless the file asks (the importer sets
     use_shadow from `shadows`). Point and spot lights get radius 0 and suns angle 0 (X3D and glTF lights are ideal points; the
     add-on leaves Blender's 0.25 m sphere), --light-size importer keeps the add-on's.

Optional beyond the contract: --circle-div N (add-on default 16, as blender_leg.py; 64 or more for a smooth silhouette),
--light-size ideal|importer, --adaptive, --max-bounces N, --save-blend FILE.
Light units: the add-on's X_ITE units (default) and BLENDER units both go through unchanged. Measured here (see the validation
notes): with X_ITE units a Blender point light of W watts and a sun of S W/m2 render in Cycles the way the glTF COMPAT export
renders them in Babylon.js (centre patch within 1 to 3 codes of X_ITE on the five rig probes), so no unit factor is applied.

OUT.png.json records the settings, versions, add-on commit, seconds, light count and everything the importer warned about.
Exit status: 0 on success, 1 when the import or the render failed (the JSON is still written with the error)."""
import argparse
import contextlib
import ctypes
import importlib
import json
import logging
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import warnings as warnings_mod
import xml.etree.ElementTree as ET

TOOL_VERSION = 1
DEFAULT_ADDON = os.environ.get("X3D_BLENDER_IO_SOURCE", "x3d-blender-io/source")   # the add-on source folder; pass --addon or set the variable

# X3D node types this reference cannot show (Cycles has no equivalent here, or the importer does not build them); counted
# in the XML so the JSON says what a comparison against X_ITE is missing.
NOT_RENDERED_NODES = ("Fog", "LocalFog", "ComposedShader", "PackagedShader", "ProgramShader", "ComposedCubeMapTexture",
                      "GeneratedCubeMapTexture", "ImageCubeMapTexture", "Billboard", "ClipPlane", "EnvironmentLight",
                      "ProjectiveTextureMapping", "MovieTexture", "ParticleSystem", "Layer", "LayerSet", "Viewport",
                      "TextureProjector", "ScreenText", "ScreenFontStyle", "PointProperties", "DepthMode", "BlendMode")


# --------------------------------------------------------------------------------------------------------------------
# small helpers (no bpy needed)

def floats(text, n=None):
    try:
        v = [float(x) for x in (text or "").replace(",", " ").split()]
    except ValueError:
        return None
    if n is None:
        return v
    return v[:n] if len(v) >= n else None


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def parse_size(text):
    m = re.fullmatch(r"(\d+)(?:[xX](\d+))?", str(text).strip())
    if not m:
        raise argparse.ArgumentTypeError("--size wants N or WxH")
    w = int(m.group(1))
    h = int(m.group(2) or w)
    return w, h


def parse_rgb(text):
    v = floats(text, 3)
    if v is None:
        raise argparse.ArgumentTypeError("--clear wants R,G,B")
    return v


def parse_headlight(text):
    t = str(text).strip().lower()
    if t in ("off", "none", "false", "no"):
        return "off"
    try:
        return float(t)
    except ValueError:
        raise argparse.ArgumentTypeError("--headlight wants off or a number (lux)")


def _rot(axis_angle):
    import numpy as np
    x, y, z, a = axis_angle
    n = np.linalg.norm([x, y, z]) or 1.0
    x, y, z = x / n, y / n, z / n
    c, s_, C = np.cos(a), np.sin(a), 1 - np.cos(a)
    return np.array([[c + x * x * C, x * y * C - z * s_, x * z * C + y * s_],
                     [y * x * C + z * s_, c + y * y * C, y * z * C - x * s_],
                     [z * x * C - y * s_, z * y * C + x * s_, c + z * z * C]])


def _wgs84_ecef(lat_deg, lon_deg, h):
    """WGS84 geodetic (degrees, metres) -> earth-centred earth-fixed (metres), numpy vector."""
    import numpy as np
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    la, lo = math.radians(lat_deg), math.radians(lon_deg)
    n = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return np.array([(n + h) * math.cos(la) * math.cos(lo), (n + h) * math.cos(la) * math.sin(lo),
                     (n * (1 - e2) + h) * math.sin(la)])


def _geo_local_frame(lat_deg, lon_deg):
    """The X3D geospatial local frame at a point (X_ITE's getStandardLocationMatrix, GD/WE): columns X = east, Y = geodetic up,
    Z = south (so -Z is north). GeoLocation maps its children from this frame to ECEF; GeoViewpoint.orientation is relative to it."""
    import numpy as np
    la, lo = math.radians(lat_deg), math.radians(lon_deg)
    east = np.array([-math.sin(lo), math.cos(lo), 0.0])
    up = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])
    return np.column_stack([east, up, np.cross(east, up)])


def geo_viewpoint_local(root, index=0):
    """View of the index-th GeoViewpoint (GD, WE only) expressed in the local frame of the first GeoLocation (or GeoLOD centre,
    else the viewpoint's own frame): the camera a renderer that treats GeoLocation as a plain group at the origin needs, to see
    the same picture as a geospatial browser. Returns (view dict, note) or (None, reason)."""
    import numpy as np
    gvs = [e for e in root.iter() if e.tag == "GeoViewpoint"]
    if index >= len(gvs):
        return None, "no GeoViewpoint"
    gv = gvs[index]
    sysf = (gv.get("geoSystem") or '"GD" "WE"').replace('"', " ").split()
    if not sysf or sysf[0] != "GD" or (len(sysf) > 1 and sysf[1] not in ("WE", "WGS84") and not sysf[1].startswith("GRS")) :
        return None, "GeoViewpoint geoSystem %s is not GD/WE" % sysf
    pos = floats(gv.get("position"), 3) or [0.0, 0.0, 100000.0]
    ori = floats(gv.get("orientation"), 4) or [0, 0, 1, 0]
    cen = None
    for e in root.iter():
        if e.tag == "GeoLocation" and floats(e.get("geoCoords"), 3):
            cen, src = floats(e.get("geoCoords"), 3), "first GeoLocation"
            break
    if cen is None:
        for e in root.iter():
            if e.tag == "GeoLOD" and floats(e.get("center"), 3):
                cen, src = floats(e.get("center"), 3), "first GeoLOD centre"
                break
    if cen is None:
        cen, src = pos, "the viewpoint itself"
    Fc, Fv = _geo_local_frame(cen[0], cen[1]), _geo_local_frame(pos[0], pos[1])
    p_local = Fc.T @ (_wgs84_ecef(*pos) - _wgs84_ecef(*cen))
    R = Fc.T @ Fv @ _rot(ori)
    view = dict(position=[float(v) for v in p_local], forward=[float(v) for v in -R[:, 2]], up=[float(v) for v in R[:, 1]],
                fov=float((floats(gv.get("fieldOfView"), 1) or [0.785398])[0]))
    return view, "GeoViewpoint #%d (%s) in the local frame (X east, Y up, Z south) of the %s" % (index, gv.get("DEF") or "unnamed", src)


def first_viewpoint(root, index=0):
    """World position, forward, up and fieldOfView of the index-th (default first) Viewpoint/OrthoViewpoint in document order, the way the rig's
    compare.py computes a job's view (Transform chain with centre, scale orientation, scale). A scene with no Viewpoint but a GeoViewpoint
    (GD/WE) gets that GeoViewpoint in the local frame of its first GeoLocation (geo_viewpoint_local); the note is in view['_note']."""
    import numpy as np
    parents = {child: parent for parent in root.iter() for child in parent}
    vps = [e for e in root.iter() if e.tag in ("Viewpoint", "OrthoViewpoint")]
    vp = vps[index] if index < len(vps) else None
    if vp is None:
        if not vps:
            gview, note = geo_viewpoint_local(root, index)
            if gview is not None:
                gview["_note"] = note
                return gview
        return None
    M = np.eye(4)
    chain, node = [], parents.get(vp)
    while node is not None:
        if node.tag == "Transform":
            chain.append(node)
        node = parents.get(node)
    for t in reversed(chain):
        T = np.eye(4); T[:3, 3] = floats(t.get("translation"), 3) or [0, 0, 0]
        R = np.eye(4); R[:3, :3] = _rot(floats(t.get("rotation"), 4) or [0, 0, 1, 0])
        S = np.diag((floats(t.get("scale"), 3) or [1, 1, 1]) + [1])
        C = np.eye(4); C[:3, 3] = floats(t.get("center"), 3) or [0, 0, 0]
        SR = np.eye(4); SR[:3, :3] = _rot(floats(t.get("scaleOrientation"), 4) or [0, 0, 1, 0])
        M = M @ T @ C @ R @ SR @ S @ np.linalg.inv(SR) @ np.linalg.inv(C)
    pos = np.array((floats(vp.get("position"), 3) or [0, 0, 10]) + [1.0])
    rot = _rot(floats(vp.get("orientation"), 4) or [0, 0, 1, 0])
    world_rot = M[:3, :3] @ rot
    world_rot = world_rot / np.linalg.norm(world_rot, axis=0)
    view = dict(position=[float(v) for v in (M @ pos)[:3]], forward=[float(v) for v in -world_rot[:, 2]],
                up=[float(v) for v in world_rot[:, 1]], fov=0.785398)
    if vp.tag == "OrthoViewpoint":
        view["ortho"] = floats(vp.get("fieldOfView"), 4) or [-1.0, -1.0, 1.0, 1.0]
    else:
        view["fov"] = float((floats(vp.get("fieldOfView"), 1) or [0.785398])[0])
    return view


DEFAULT_VIEW = dict(position=[0.0, 0.0, 10.0], forward=[0.0, 0.0, -1.0], up=[0.0, 1.0, 0.0], fov=0.785398)


def read_xml(path):
    """The scene as an ElementTree root, or None for a file that is not XML X3D (VRML, x3dv, x3dz)."""
    if not path.lower().endswith(".x3d"):
        return None
    try:
        return ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None


def census(root):
    """Node counts from the XML that matter for what a reference can and cannot show."""
    if root is None:
        return None
    tags = [e.tag for e in root.iter()]
    count = lambda *names: sum(1 for t in tags if t in names)
    out = dict(shapes=count("Shape"), lights=count("PointLight", "SpotLight", "DirectionalLight"),
               viewpoints=count("Viewpoint", "OrthoViewpoint"), backgrounds=count("Background", "TexturedBackground"),
               navigation_infos=count("NavigationInfo"), inlines=count("Inline"), proto_instances=count("ProtoInstance"))
    out["lights_off"] = sum(1 for e in root.iter() if e.tag in ("PointLight", "SpotLight", "DirectionalLight")
                            and (e.get("on") or "").strip().lower() == "false")
    out["lights_with_shadows"] = sum(1 for e in root.iter() if e.tag in ("PointLight", "SpotLight", "DirectionalLight")
                                     and (e.get("shadows") or "").strip().lower() == "true")
    out["not_rendered_nodes"] = {n: tags.count(n) for n in NOT_RENDERED_NODES if n in tags}
    return out


def first_background_sky(root, raw_text):
    if root is not None:
        bg = next((e for e in root.iter() if e.tag in ("Background", "TexturedBackground")), None)
        if bg is not None:
            v = floats(bg.get("skyColor"), 3)
            return v if v is not None else [0.0, 0.0, 0.0]   # a Background without skyColor: X3D default black
        return None
    m = re.search(r"Background\s*\{[^}]*skyColor\s*\[?\s*([-\d.eE+ ,]+)", raw_text or "")
    return floats(m.group(1), 3) if m else None


def navigation_headlight(root, raw_text):
    """The first NavigationInfo's headlight (X3D default and a browser's: on)."""
    if root is not None:
        nav = next((e for e in root.iter() if e.tag == "NavigationInfo"), None)
        return not (nav is not None and (nav.get("headlight") or "").strip().lower() == "false")
    m = re.search(r"NavigationInfo\s*\{[^}]*headlight\s+(TRUE|FALSE)", raw_text or "", re.I)
    return not (m and m.group(1).upper() == "FALSE")


def addon_commit(addon):
    """(commit hash, dirty flag) of the git checkout holding the add-on source, or (None, None)."""
    try:
        head = subprocess.run(["git", "-C", addon, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
        if head.returncode == 0:
            status = subprocess.run(["git", "-C", addon, "status", "--porcelain", "--", "."], capture_output=True, text=True, timeout=20)
            return head.stdout.strip(), bool(status.stdout.strip()) if status.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        pass
    d = os.path.abspath(addon)
    while d != os.path.dirname(d):
        git = os.path.join(d, ".git")
        if os.path.isfile(os.path.join(git, "HEAD")):
            ref = open(os.path.join(git, "HEAD")).read().strip()
            if ref.startswith("ref: "):
                p = os.path.join(git, ref[5:])
                return (open(p).read().strip() if os.path.exists(p) else None), None
            return ref, None
        d = os.path.dirname(d)
    return None, None


# --------------------------------------------------------------------------------------------------------------------
# output capture: Python logging from the importer, and the C-level stdout/stderr of Blender and Cycles

class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.records = []

    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        self.records.append(f"{record.name} {record.levelname}: {msg}")


@contextlib.contextmanager
def capture_fds(sink):
    """Redirect file descriptors 1 and 2 into a temporary file for the block; sink[0] gets the text afterwards."""
    libc = ctypes.CDLL(None)
    sys.stdout.flush(); sys.stderr.flush()
    libc.fflush(None)
    tmp = tempfile.TemporaryFile(mode="w+b")
    saved = os.dup(1), os.dup(2)
    os.dup2(tmp.fileno(), 1); os.dup2(tmp.fileno(), 2)
    try:
        yield
    finally:
        sys.stdout.flush(); sys.stderr.flush()
        libc.fflush(None)
        os.dup2(saved[0], 1); os.dup2(saved[1], 2)
        os.close(saved[0]); os.close(saved[1])
        tmp.seek(0)
        sink[0] = tmp.read().decode("utf-8", "replace")
        tmp.close()


WARN_LINE = re.compile(r"warn|error|fail|missing|not found|cannot|can't|unable|unsupported|skipp|invalid", re.I)
NOISE_LINE = re.compile(r"^(Fra:|Time:|Saved:|Blender quit|\s*$)|Sample \d+/\d+|CUEW initialization|Cycles.*(Loading|Updating|Synchronizing|Building|Writing|Rendering|Denoising)", re.I)


def interesting_lines(text):
    seen, out = set(), []
    for line in (text or "").splitlines():
        line = line.strip()
        if line and WARN_LINE.search(line) and not NOISE_LINE.search(line) and line not in seen:
            seen.add(line)
            out.append(line)
    return out


# --------------------------------------------------------------------------------------------------------------------

def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--x3d", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--job-json", help="rig jobs.json (a list of jobs); with --job-name the job supplies view, clear and headlight")
    ap.add_argument("--job-name")
    ap.add_argument("--view-json", help="a view dict {position, forward, up, fov[, ortho]} or a whole job with a `view` key")
    ap.add_argument("--samples", type=int, default=256, help="Cycles samples per pixel (default 256: seed 0 vs 1 FLIP LDR stays below 0.01 on the three validation scenes)")
    ap.add_argument("--size", type=parse_size, default=(512, 512), help="N or WxH (default 512)")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--denoise", choices=("none", "oidn"), default="none")
    ap.add_argument("--light-units", choices=("xite", "blender"), default="xite")
    ap.add_argument("--clear", type=parse_rgb, help="R,G,B display values 0..1 (default: the job's clear, else the first Background skyColor, else black)")
    ap.add_argument("--headlight", type=parse_headlight, help="off or lux (default: the job's headlight, else the scene's, see the docstring)")
    ap.add_argument("--addon", default=DEFAULT_ADDON)
    # beyond the contract, all optional
    ap.add_argument("--circle-div", type=int, default=None,
                    help="Sphere/Cylinder/Cone segments (default: the add-on's, 16 unless BLENDER_X3D_CIRCLE_DIV is set, as blender_leg.py)")
    ap.add_argument("--light-size", choices=("ideal", "importer"), default="ideal",
                    help="ideal (default): point and spot lights get radius 0 and suns angle 0, as X3D and glTF punctual lights are; "
                         "importer: keep what the add-on left (Blender's defaults, a 0.25 m sphere for point and spot lights, a 0.53 degree sun)")
    ap.add_argument("--adaptive", action="store_true", help="switch Cycles adaptive sampling on (default off: --samples is exact)")
    ap.add_argument("--max-bounces", type=int, default=None, help="Cycles total bounces (default: Cycles' 12)")
    ap.add_argument("--force-shadows", action="store_true",
                    help="every imported point, spot and sun light casts shadows (use_shadow True) even when the X3D file does not ask "
                         "(default: only lights with shadows='true' do). A truer image than the file's literal intent; the legs that "
                         "ignore the field cannot match it. Added by run_quality.py for its `shadows` extra reference")
    ap.add_argument("--save-blend", help="also save the prepared scene as a .blend here")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    t_start = time.time()
    x3d = os.path.abspath(a.x3d)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    width, height = a.size
    report = dict(tool="cycles_reference.py", tool_version=TOOL_VERSION, x3d=x3d, out=out, ok=False, error=None)
    warnings = []
    log_sink = [""]

    # ---- inputs that need no bpy: job, view, clear, headlight, XML facts
    job = None
    job_source = None
    if a.job_json or a.job_name:
        if not (a.job_json and a.job_name):
            sys.exit("--job-json and --job-name go together")
        jobs = json.load(open(a.job_json))
        jobs = jobs.get("jobs", jobs) if isinstance(jobs, dict) else jobs
        job = next((j for j in jobs if j.get("name") == a.job_name), None)
        if job is None:
            sys.exit(f"job {a.job_name!r} not in {a.job_json} (has: {', '.join(j.get('name', '?') for j in jobs)})")
        job_source = f"{a.job_json}#{a.job_name}"
        if job.get("x3d") and os.path.realpath(job["x3d"]) != os.path.realpath(x3d):
            warnings.append(f"--x3d {x3d} is not the job's x3d {job['x3d']}")
    view_json = None
    if a.view_json:
        view_json = json.load(open(a.view_json))
        if "position" not in view_json and "view" in view_json:
            job = job or view_json          # a whole job: its view, clear and headlight count
            job_source = job_source or f"{a.view_json}"
            view_json = None
    if not os.path.isfile(x3d):
        report["error"] = f"scene not found: {x3d}"
        return finish(report, out, t_start, 1)
    root = read_xml(x3d)
    raw = None if root is not None else open(x3d, errors="ignore").read()
    facts = census(root)

    if view_json is not None:
        view, view_src = view_json, f"--view-json {a.view_json}"
    elif job is not None and job.get("view"):
        view, view_src = job["view"], f"job {job_source}"
    else:
        view = first_viewpoint(root) if root is not None else None
        view_src = "first Viewpoint in the XML" if view else None
        if view is None:   # VRML or no Viewpoint: resolved from the imported camera objects below, else X3D's default
            view_src = "pending"
    if a.clear is not None:
        clear, clear_src = a.clear, "--clear"
    elif job is not None and job.get("clear") is not None:
        clear, clear_src = [float(c) for c in job["clear"][:3]], f"job {job_source}"
    else:
        sky = first_background_sky(root, raw)
        clear, clear_src = (sky, "first Background skyColor") if sky is not None else ([0.0, 0.0, 0.0], "default black")

    nav_on = navigation_headlight(root, raw)
    if a.headlight is not None:
        head_req, head_src = a.headlight, "--headlight"
    elif job is not None and "headlight" in job:
        head_req, head_src = ("off" if job["headlight"] is None else float(job["headlight"])), f"job {job_source}"
    else:
        head_req, head_src = ("auto" if nav_on else "off"), ("scene x3d_headlight_lux" if nav_on else "NavigationInfo headlight=false")

    # ---- bpy and the add-on, the way blender_leg.py loads it
    t0 = time.time()
    import bpy
    import addon_utils
    from mathutils import Matrix, Vector
    from bpy_extras.io_utils import axis_conversion
    addon = os.path.abspath(a.addon)
    handler = ListHandler()
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.WARNING)
    tmp = tempfile.mkdtemp(prefix="cyref_")
    os.symlink(addon, os.path.join(tmp, "io_scene_x3d"), target_is_directory=True)
    sys.path.insert(0, tmp)
    with capture_fds(log_sink):
        importlib.import_module("io_scene_x3d").register()
        bpy.ops.wm.read_factory_settings(use_empty=True)
        try:
            importlib.import_module("io_scene_x3d").register()
        except ValueError:
            pass   # still registered
        addon_utils.enable("cycles")
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = width, height, 100   # before the import: its cameras use the render size
    commit, dirty = addon_commit(addon)

    units = "X_ITE" if a.light_units == "xite" else "BLENDER"
    kwargs = dict(filepath=x3d, color_space="SRGB", light_units=units)
    if a.circle_div:
        kwargs["circle_divisions"] = a.circle_div
    t_imp = time.time()
    importer_stdout = [""]
    import_error = None
    try:
        with capture_fds(importer_stdout):
            result = bpy.ops.import_scene.x3d(**kwargs)
        if result != {"FINISHED"}:
            import_error = f"import_scene.x3d returned {result}"
    except Exception as exc:   # report it, do not hide it
        import_error = f"import_scene.x3d raised {type(exc).__name__}: {exc}"
    seconds_import = time.time() - t_imp
    importer_msgs = list(handler.records) + [l for l in interesting_lines(importer_stdout[0]) if l not in handler.records]
    if import_error:
        report.update(error=import_error, importer=dict(warnings=importer_msgs, census=facts))
        return finish(report, out, t_start, 1)

    # ---- what came in
    M = axis_conversion(from_forward="-Z", from_up="Y").to_4x4()     # the operator's default global matrix
    Mi = M.inverted()
    lights = []
    for ob in sc.objects:
        if ob.type == "LIGHT":
            d = ob.data
            was = round(d.angle, 6) if d.type == "SUN" else round(d.shadow_soft_size, 6)
            if a.force_shadows:
                d.use_shadow = True
            if a.light_size == "ideal":
                if d.type == "SUN":
                    d.angle = 0.0
                else:
                    d.shadow_soft_size = 0.0
            lights.append(dict(name=ob.name, type=d.type, energy=round(d.energy, 5), color=[round(c, 5) for c in d.color],
                               shadow=bool(d.use_shadow), range=(round(d.cutoff_distance, 4) if d.use_custom_distance else None),
                               hide_render=bool(ob.hide_render), importer_size=was,
                               size_used=(round(d.angle, 6) if d.type == "SUN" else round(d.shadow_soft_size, 6))))
    meshes = [ob for ob in sc.objects if ob.type in ("MESH", "CURVE", "SURFACE", "FONT", "META")]
    cams = [ob for ob in sc.objects if ob.type == "CAMERA"]
    model = sc.get("x3d_lighting_model")
    head_lux_scene = sc.get("x3d_headlight_lux")

    if view_src == "pending":
        if cams:   # VRML / x3dv, or XML without a Viewpoint element the parser found: take the importer's first camera
            c0 = cams[0]
            mw = Mi @ c0.matrix_world
            fov = importlib.import_module("io_scene_x3d.viewpoint_fov").x3d_field_of_view(
                c0.data.angle, c0.data.sensor_fit, float(width), float(height))   # the add-on's own inverse of blender_camera_angle
            view = dict(position=list(mw.to_translation()), forward=list(-(mw.to_3x3() @ Vector((0, 0, 1)))),
                        up=list(mw.to_3x3() @ Vector((0, 1, 0))), fov=float(fov))
            view_src = f"first imported camera object {c0.name!r} (not XML)"
            warnings.append("view taken from the first camera object of the import (scene.objects order), not from the document")
        else:
            view, view_src = dict(DEFAULT_VIEW), "X3D default view (no Viewpoint)"

    # ---- camera (own object; the importer's cameras stay in the scene but are not used)
    pos = M.to_3x3() @ Vector(view["position"])
    fwd = (M.to_3x3() @ Vector(view["forward"])).normalized()
    up = M.to_3x3() @ Vector(view["up"])
    right = fwd.cross(up).normalized()
    up = right.cross(fwd).normalized()
    cam_matrix = Matrix((right, up, -fwd)).transposed().to_4x4()
    cam_matrix.translation = pos
    cam_data = bpy.data.cameras.new("cycles_reference_camera")
    cam_data.clip_start, cam_data.clip_end = 0.01, 10000.0
    if view.get("ortho"):
        l, b, r, t = view["ortho"]
        cam_data.type = "ORTHO"
        wide = (r - l) >= (t - b)
        cam_data.sensor_fit = "HORIZONTAL" if wide else "VERTICAL"
        cam_data.ortho_scale = max(r - l, t - b)
        cam_data.shift_x = 0.5 * (l + r) / cam_data.ortho_scale
        cam_data.shift_y = 0.5 * (b + t) / cam_data.ortho_scale
        if abs((r - l) / (t - b) - width / height) > 1e-3:
            warnings.append("OrthoViewpoint extents and image aspect differ; the rig stretches, Blender cannot (Suspected: untested)")
    else:
        cam_data.type = "PERSP"
        cam_data.sensor_fit = "VERTICAL" if width >= height else "HORIZONTAL"   # X3D: fieldOfView spans the smaller side
        cam_data.angle = float(view["fov"])
    cam_ob = bpy.data.objects.new("cycles_reference_camera", cam_data)
    sc.collection.objects.link(cam_ob)
    cam_ob.matrix_world = cam_matrix
    sc.camera = cam_ob

    # cross-check against the importer's own camera objects (the first Viewpoint should be among them)
    cam_check = None
    if cams:
        dists = []
        for c in cams:
            p = (Mi @ c.matrix_world).to_translation()
            dists.append((math.dist(p, view["position"]), c.name))
        cam_check = dict(imported_cameras=len(cams), nearest_imported_camera=min(dists)[1], nearest_distance=round(min(dists)[0], 6))

    # ---- headlight
    head_lux = None
    if head_req == "auto":
        head_lux = float(head_lux_scene) if head_lux_scene is not None else 1.0
        if head_lux_scene is None:
            warnings.append("scene has no x3d_headlight_lux (light units BLENDER?); headlight at 1.0")
    elif head_req != "off":
        head_lux = float(head_req)
    if head_lux is not None and head_lux > 0.0:
        sun_data = bpy.data.lights.new("x3d_headlight", "SUN")
        sun_data.energy = head_lux
        sun_data.angle = 0.0
        sun_data.use_shadow = False
        sun = bpy.data.objects.new("x3d_headlight", sun_data)
        sc.collection.objects.link(sun)
        sun.matrix_world = cam_matrix                  # a sun shines along its local -Z, the camera looks along -Z
        sun_data["x3d_headlight_lux"] = head_lux
    else:
        head_lux = None

    # ---- world: the clear colour for camera rays, black for everything else
    world = bpy.data.worlds.new("cycles_reference_world")
    with warnings_mod.catch_warnings():
        warnings_mod.simplefilter("ignore", DeprecationWarning)   # World.use_nodes goes in Blender 6.0; 5.3 still needs it
        world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    lin = [srgb_to_linear(max(0.0, min(1.0, c))) for c in clear]
    bg_clear = nt.nodes.new("ShaderNodeBackground"); bg_clear.inputs["Color"].default_value = (*lin, 1.0); bg_clear.inputs["Strength"].default_value = 1.0
    bg_dark = nt.nodes.new("ShaderNodeBackground"); bg_dark.inputs["Color"].default_value = (0, 0, 0, 1); bg_dark.inputs["Strength"].default_value = 0.0
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    outn = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(bg_dark.outputs["Background"], mix.inputs[1])
    nt.links.new(bg_clear.outputs["Background"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], outn.inputs["Surface"])
    sc.world = world

    # ---- render settings
    sc.render.engine = "CYCLES"
    cy = sc.cycles
    cy.device = "CPU"
    cy.samples = int(a.samples)
    cy.use_adaptive_sampling = bool(a.adaptive)
    cy.seed = int(a.seed)
    cy.use_animated_seed = False
    cy.time_limit = 0.0
    if a.max_bounces is not None:
        cy.max_bounces = int(a.max_bounces)
    oidn_ok = True
    if a.denoise == "oidn":
        cy.use_denoising = True
        cy.denoiser = "OPENIMAGEDENOISE"
        cy.denoising_use_gpu = False
    else:
        cy.use_denoising = False
    sc.render.threads_mode = "FIXED"
    sc.render.threads = int(a.threads)
    sc.render.film_transparent = False
    sc.render.dither_intensity = 0.0
    sc.render.use_motion_blur = False
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0
    sc.view_settings.use_curve_mapping = False
    sc.display_settings.display_device = "sRGB"
    ims = sc.render.image_settings
    ims.file_format = "PNG"
    ims.color_mode = "RGB"
    ims.color_depth = "8"
    ims.compression = 15
    sc.render.filepath = out
    sc.frame_set(sc.frame_start)
    settings = dict(samples=cy.samples, adaptive=bool(cy.use_adaptive_sampling), seed=cy.seed, size=[width, height], threads=sc.render.threads,
                    denoise=("OpenImageDenoise (Cycles built in, CPU)" if a.denoise == "oidn" else "none"),
                    light_units=units, color_space="SRGB", light_size=a.light_size, circle_divisions=a.circle_div or "add-on default",
                    view_transform=sc.view_settings.view_transform, look=sc.view_settings.look, exposure=sc.view_settings.exposure,
                    gamma=sc.view_settings.gamma, display=sc.display_settings.display_device, dither=sc.render.dither_intensity,
                    device=cy.device, max_bounces=cy.max_bounces, diffuse_bounces=cy.diffuse_bounces, glossy_bounces=cy.glossy_bounces,
                    transmission_bounces=cy.transmission_bounces, transparent_bounces=cy.transparent_max_bounces,
                    clamp_direct=cy.sample_clamp_direct, clamp_indirect=cy.sample_clamp_indirect, filter_width=cy.filter_width,
                    light_tree=bool(cy.use_light_tree), film_transparent=False, force_shadows=bool(a.force_shadows))
    if a.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.save_blend), copy=True)

    # ---- render
    render_log = [""]
    t_r = time.time()
    render_error = None
    try:
        with capture_fds(render_log):
            bpy.ops.render.render(write_still=True)
    except Exception as exc:
        render_error = f"render raised {type(exc).__name__}: {exc}"
    seconds_render = time.time() - t_r
    if render_error is None and not os.path.exists(out):
        render_error = "render finished but no PNG was written"
    render_msgs = interesting_lines(render_log[0])

    image = None
    if render_error is None:
        try:
            import numpy as np
            from PIL import Image
            arr = np.asarray(Image.open(out).convert("RGB"), dtype=np.float64)
            bgpx = np.all(np.abs(arr - np.round(np.array(clear) * 255.0)) <= 1.0, axis=-1)
            image = dict(size=[arr.shape[1], arr.shape[0]], mean_rgb_0_255=[round(float(v), 3) for v in arr.reshape(-1, 3).mean(0)],
                         share_pixels_at_clear_colour=round(float(bgpx.mean()), 4), max=int(arr.max()),
                         share_saturated_255=round(float((arr >= 255).any(-1).mean()), 5))
        except Exception as exc:
            warnings.append(f"image statistics failed: {exc}")

    report.update(
        ok=render_error is None, error=render_error, settings=settings,
        blender=dict(version=bpy.app.version_string, hash=bpy.app.build_hash.decode() if isinstance(bpy.app.build_hash, bytes) else bpy.app.build_hash,
                     build_date=(bpy.app.build_date.decode() if isinstance(bpy.app.build_date, bytes) else str(bpy.app.build_date)), cycles="bundled with Blender " + bpy.app.version_string + " (add-on cycles enabled)",
                     python=sys.version.split()[0]),
        addon=dict(path=addon, commit=commit, dirty=dirty, version=list(importlib.import_module("io_scene_x3d").bl_info["version"])),
        view=dict(**{k: v for k, v in view.items()}, source=view_src, blender_camera=dict(location=[round(v, 5) for v in cam_ob.location],
                  type=cam_data.type, sensor_fit=cam_data.sensor_fit, angle=round(cam_data.angle, 6) if cam_data.type == "PERSP" else None),
                  crosscheck_importer_cameras=cam_check),
        clear=dict(display_rgb=clear, linear_rgb=[round(v, 6) for v in lin], source=clear_src),
        headlight=dict(requested=head_req, source=head_src, lux=head_lux, scene_x3d_headlight_lux=head_lux_scene, navigation_info_on=nav_on),
        lighting_model=model,
        seconds=dict(total=round(time.time() - t_start, 2), import_=round(seconds_import, 2), render=round(seconds_render, 2),
                     render_per_sample=round(seconds_render / max(1, a.samples), 4)),
        light_count=len(lights), light_count_with_headlight=len(lights) + (1 if head_lux else 0), lights=lights,
        objects=dict(meshes=len(meshes), cameras=len(cams), lights=len(lights), materials=len(bpy.data.materials)),
        importer=dict(warnings=importer_msgs, census=facts),
        render_messages=render_msgs, warnings=warnings, job=job_source, image=image)
    if facts:
        if facts["lights"] != len(lights):
            warnings.append(f"XML has {facts['lights']} light nodes, {len(lights)} light objects came in")
        if facts["lights_off"]:
            warnings.append(f"{facts['lights_off']} light(s) have on='false' in the XML; the importer ignores `on` (is_on TODO), so they shine here")
        if facts["not_rendered_nodes"]:
            warnings.append(f"XML uses nodes this reference does not draw: {facts['not_rendered_nodes']}")
        if facts["backgrounds"] > 1 or (root is not None and any(e.get("skyAngle") or e.get("backUrl") or e.get("frontUrl") for e in root.iter() if e.tag in ("Background", "TexturedBackground"))):
            warnings.append("Background gradient/skybox is reduced to a flat first skyColor")
    return finish(report, out, t_start, 0 if render_error is None else 1)


def finish(report, out, t_start, code):
    report.setdefault("seconds", {})["total"] = round(time.time() - t_start, 2)
    with open(out + ".json", "w") as f:
        json.dump(report, f, indent=1, default=str)
    msg = "OK" if report.get("ok") else f"FAILED: {report.get('error')}"
    sec = report.get("seconds", {})
    print(f"cycles_reference {msg} {out} render {sec.get('render')} s total {sec.get('total')} s", flush=True)
    return code


if __name__ == "__main__":
    code = main()
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(code)   # Blender's module teardown can crash after a good render; the PNG and JSON are already on disk
