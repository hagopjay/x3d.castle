#!/usr/bin/env python3
"""Image-quality yardstick used beside the X_ITE difference (mean |delta|) in the x3d.castle evaluation.

Run with the venv that has flip-evaluator, scikit-image, numpy, Pillow:
    python quality_metrics.py SUBCOMMAND ...

  compare   --ref REF.png --test A.png B.png ... [--labels a b ...] --out DIR [--mask auto|none] [--ppd F]
            Per test image, against the reference: flip_mean, flip_mean_expnorm (+ exposure_scale), ssim, psnr,
            mean_abs, mean_abs_geometry (and a few extras). Writes DIR/metrics.json, a FLIP heatmap PNG per test
            image (DIR/LABEL_flip.png, magma, fixed scale 0..0.5) and the same after exposure normalisation
            (DIR/LABEL_flip_expnorm.png). Prints a table.
  sheet     --ref REF.png --tests A.png B.png ... [--labels ...] --out SHEET.png [--cols N] [--expnorm-row]
            Labelled montage: reference first, each test image with its numbers under it, then a row of FLIP heatmaps.
  floor     --a RENDER1.png --b RENDER2.png [--json OUT.json]
            Noise floor: the same metrics between two renders of the same thing (A plays the reference).
  selftest  --ref REF.png
            Runs the control relations (identity 0, blur < shift < exposure, expnorm removes exposure) on REF; exit 1 on failure.
  controls  --ref REF.png --out DIR
            Calibration: builds controls from REF (identity, blur, JPEG, noise, shift, exposure changes, colour cast,
            black, inverted), runs `compare` on each and writes DIR/controls.json + DIR/controls.txt.

All images are loaded as 8-bit sRGB RGB. Sizes must match; a test image whose size differs from the reference is
REFUSED (named in the output, recorded in the JSON, exit code 3), nothing is resized silently.

Definitions (every number a downstream report quotes comes from these):

  flip_mean            flip-evaluator (NVIDIA FLIP, pip flip-evaluator 1.7) LDR-FLIP, reference vs test, sRGB inputs
                       as float32 in [0,1], default 67 pixels per degree (override with --ppd), mean of the per-pixel
                       error map over the WHOLE frame. 0 = identical, lower is better, scale 0..1.
  Background rule      (--mask auto, the default)
                         bg colour = the most frequent exact RGB value among the four corner pixels of the REFERENCE;
                                     ties resolved in the order top-left, top-right, bottom-left, bottom-right
                                     (--bg R,G,B overrides it);
                         background pixel = reference pixel == bg colour AND test pixel == bg colour
                                     (exact 8-bit equality; --bg-tol N allows |delta| <= N per channel in both);
                         geometry pixel   = every other pixel.
                       --mask none: no background; geometry = the whole frame.
                       Known limits: pixels inside the object that are exactly the clear colour in both images (for
                       example pure black shadow under a black clear colour) count as background; if the test image
                       uses a different clear colour, the whole backdrop counts as geometry. The mask is per
                       (reference, test) pair and its size is reported as geometry_fraction.
  flip_mean_expnorm    The same FLIP mean after ONE scalar exposure correction of the test image, in linear light:
                         linear = IEC 61966-2-1 sRGB decode of v/255;  Y = 0.2126 R + 0.7152 G + 0.0722 B (linear);
                         s0 = mean(Y_ref over geometry) / mean(Y_test over geometry);
                         s  = s0 when s0 <= 1 (scaling down cannot clip);
                         s  > 1: the smallest s with mean(Y(clip(s * test_linear, 0, 1)) over geometry) equal to the
                                 reference mean (bisection; clipping makes s larger than s0), capped at 64 (flag
                                 exposure_scale_capped, then the means are NOT equal);
                         geometry pixels become round_to_8bit(encode(clip(s * linear, 0, 1))), i.e. the normalised test
                         image is again an ordinary 8-bit image; background pixels stay as they are (they already
                         equal the reference there). Rounding to 8 bit matters: FLIP reacts to differences far below
                         one 8-bit step (a float x0.999 scale alone raised flip_mean on a 0.004 pair to 0.007), so
                         an unrounded float image would make expnorm worse than plain FLIP when s is close to 1.
                         With rounding, s close to 1 gives exactly the plain number.
                       exposure_scale is that s (test linear light is multiplied by it). A value near 1 means the
                       test already had the reference's mean brightness; the further from 1, the more of the plain
                       FLIP number was a brightness offset. Saturation is not undone: clipped highlights stay wrong.
  ssim                 scikit-image structural_similarity, window 7 (uniform), data_range 255, on luma
                       Y' = 0.2126 R' + 0.7152 G' + 0.0722 B' of the sRGB-encoded 8-bit values, mean over the frame
                       (ssim_geometry: mean over geometry pixels, window-border pixels excluded). 1 = identical.
  psnr                 scikit-image peak_signal_noise_ratio on the RGB 8-bit images, data_range 255, whole frame, dB;
                       null (psnr_is_inf true) for identical images.
  mean_abs             mean |ref - test| over all pixels and channels, 8-bit scale 0..255, whole frame.
  mean_abs_geometry    the same, geometry pixels only (null when there are none). Same definition as castle_compare.py.
  Warnings             "warnings" per test image (marked ! in the table): the test image's own corner colour differs from the
                       reference's background colour, or the background rule matched under 0.1% of the frame. Both mean
                       the geometry mask (and with it expnorm and the *_geometry numbers) is probably not what you want.
  --best-scale         optional extra, about 20 more FLIP runs per test image: flip_mean_bestscale and bestscale = the one
                       linear-light scalar (same pixels, same 8-bit rounding as expnorm) that minimises flip_mean, found
                       by a 9-point log grid plus bounded Brent. Use it when expnorm looks wrong (see next).
  expnorm caveats      flip_mean_expnorm is NOT guaranteed to be <= flip_mean. Matching the MEAN is dragged by clipped
                       highlights and by structured (non-exposure) differences: Cycles-vs-X_ITE gets slightly worse
                       (0.1068 -> 0.1095), and a blur control can double (0.0084 -> 0.0164) because the blur lowers the mean
                       by about 2% and the rescale then adds an exposure error. Read expnorm only when exposure_scale is
                       clearly away from 1 (several %), and look at flip_mean_bestscale if in doubt.
  Extras               flip_mean_geometry, flip_mean_expnorm_geometry (FLIP error-map mean over geometry pixels),
                       flip_p95 and flip_max of the plain error map.

Heatmaps: FLIP error map e in [0,1] -> magma(clip(e / 0.5, 0, 1)); the magma table is the one flip-evaluator itself
uses for applyMagma (reconstructed from its output by binning, 256 entries; at 0.25/0.5/0.75 it gives (81,18,124), (182,55,121),
(251,135,97), within 2/255 of the magma anchors #50127b, #b73779, #fc8961).
"""
import argparse
import io
import json
import os
import re
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

TOOL = "quality_metrics.py"
HEAT_SCALE = 0.5            # FLIP error that maps to the top of the colour map
EXPNORM_CAP = 64.0
LUMA = np.array([0.2126, 0.7152, 0.0722])

# 256-entry magma table (RGB bytes as hex), reconstructed from flip-evaluator's own applyMagma output (see module docstring)
_MAGMA_HEX = (
    "00000401000501010601010802010a02020c02020e03031004031204041405041606051806051a07061c08071e090720"
    "0a08220b09240c09260d0a280e0b2b100b2d110c2f120d31130d34140e36150e38160f3b180f3d19103f1a10421c1044"
    "1d11471e114920114b21114e22115024125325125527115829115a2a115c2c115f2d11612f1163311165331067341069"
    "36106b38106c390f6e3b0f703d0f713f0f72400f74420f75440f764510774710784910784a10794c117a4e117b4f127b"
    "51127c52137c54137d55147d57157e59157e5a167e5c167f5d177f5f187f601880621980641a80651a80671b80681c81"
    "6a1c816b1d816d1d816e1e81701f81721f817320817521817621817822817922827b23827c23827e2482802582812581"
    "8326818426818627818827818928818b29818c29818e2a81902a81912b81932b80942c80962c80982d80992d809b2e7f"
    "9c2e7f9e2f7fa02f7fa1307ea3307ea5317ea6317da8327daa337dab337cad347cae347bb0357bb2357bb3367ab5367a"
    "b73779b83779ba3878bc3978bd3977bf3a77c03a76c23b75c43c75c53c74c73d73c83e73ca3e72cc3f71cd4071cf4070"
    "d0416fd2426fd3436ed5446dd6456cd8456cd9466bdb476adc4869de4968df4a68e04c67e24d66e34e65e44f64e55064"
    "e75263e85362e95462ea5661eb5760ec5860ed5a5fee5c5eef5d5ef05f5ef1605df2625df2645cf3655cf4675cf4695c"
    "f56b5cf66c5cf66e5cf7705cf7725cf8745cf8765cf9785df9795df97b5dfa7d5efa7f5efa815ffb835ffb8560fb8761"
    "fc8961fc8a62fc8c63fc8e64fc9065fd9266fd9467fd9668fd9869fd9a6afd9b6bfe9d6cfe9f6dfea16efea36ffea571"
    "fea772fea973feaa74feac76feae77feb078feb27afeb47bfeb67cfeb77efeb97ffebb81febd82febf84fec185fec287"
    "fec488fec68afec88cfeca8dfecc8ffecd90fecf92fed194fed395fed597fed799fed89afdda9cfddc9efddea0fde0a2"
    "fde2a3fde3a5fde5a7fde7a9fde9aafdebacfcedaefceeb0fcf0b2fcf2b4fcf4b5fcf7b9fcf9bbfcfabcfcfcbefcfdbf"
)

_MAGMA = None


def magma_lut():
    global _MAGMA
    if _MAGMA is None:
        _MAGMA = np.frombuffer(bytes.fromhex(_MAGMA_HEX), dtype=np.uint8).reshape(256, 3).astype(np.float64)
    return _MAGMA


def apply_magma(t):
    """t in [0,1] (any shape) -> uint8 (...,3), linear interpolation in the 256-entry table."""
    lut = magma_lut()
    x = np.clip(np.asarray(t, dtype=np.float64), 0, 1) * 255.0
    i0 = np.minimum(x.astype(np.int64), 254)
    f = (x - i0)[..., None]
    return np.round(lut[i0] * (1 - f) + lut[i0 + 1] * f).astype(np.uint8)


def heatmap(err, scale=HEAT_SCALE):
    return apply_magma(np.asarray(err, dtype=np.float64) / scale)


# ----------------------------------------------------------------------------------------------- loading

class Refused(Exception):
    pass


def load_rgb8(path):
    """Any PIL-readable image -> (uint8 HxWx3, info dict). Alpha is composited over black (noted); 16-bit and float
    greyscale modes are quantised to 8 bit (noted); palette / grey / CMYK are converted to RGB."""
    if not os.path.isfile(path):
        raise Refused(f"file not found: {path}")
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:  # noqa: BLE001
        raise Refused(f"cannot read {path}: {type(e).__name__}: {e}")
    notes, mode = [], im.mode
    if mode in ("I;16", "I;16L", "I;16B", "I;16N"):
        a = np.asarray(im, dtype=np.float64) / 65535.0
        rgb = np.round(np.repeat(np.clip(a, 0, 1)[..., None], 3, axis=2) * 255).astype(np.uint8)
        notes.append("16-bit greyscale quantised to 8-bit")
        if a.max() * 65535.0 <= 255:
            notes.append("WARNING: all 16-bit values are <= 255, read as true 16-bit (image is nearly black)")
    elif mode == "I":
        a = np.asarray(im, dtype=np.float64)
        a = a / (65535.0 if a.max() > 255 else 255.0)
        rgb = np.round(np.repeat(np.clip(a, 0, 1)[..., None], 3, axis=2) * 255).astype(np.uint8)
        notes.append("32-bit integer greyscale scaled to 8-bit")
    elif mode == "F":
        a = np.clip(np.asarray(im, dtype=np.float64), 0, 1)
        rgb = np.round(np.repeat(a[..., None], 3, axis=2) * 255).astype(np.uint8)
        notes.append("float greyscale assumed 0..1, quantised to 8-bit")
    else:
        has_alpha = mode in ("RGBA", "LA", "PA", "RGBa", "La") or (mode == "P" and "transparency" in im.info)
        if has_alpha:
            rgba = np.asarray(im.convert("RGBA"), dtype=np.float64)
            alpha = rgba[..., 3:4] / 255.0
            if (alpha < 1).any():
                notes.append("alpha composited over black")
            rgb = np.round(rgba[..., :3] * alpha).astype(np.uint8)
        else:
            rgb = np.asarray(im.convert("RGB"))
    if mode != "RGB":
        notes.append(f"converted from mode {mode}")
    return np.ascontiguousarray(rgb), dict(path=os.path.abspath(path), mode=mode, size=[im.width, im.height], notes=notes)


# ----------------------------------------------------------------------------------------------- colour helpers

def srgb_to_linear(v):
    v = np.asarray(v, dtype=np.float64)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(v):
    v = np.clip(np.asarray(v, dtype=np.float64), 0, 1)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055)


def luma_encoded(rgb8):
    return rgb8.astype(np.float64) @ LUMA


# ----------------------------------------------------------------------------------------------- mask + exposure

def corner_colour(ref8):
    h, w = ref8.shape[:2]
    cs = [tuple(int(x) for x in ref8[y, x]) for (y, x) in ((0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1))]
    best = max(cs, key=lambda c: (cs.count(c), -cs.index(c)))   # most frequent; ties -> earliest corner
    return best, cs


def background_mask(ref8, test8, bg, tol=0):
    b = np.array(bg, dtype=np.int16)
    r = (np.abs(ref8.astype(np.int16) - b) <= tol).all(axis=2)
    t = (np.abs(test8.astype(np.int16) - b) <= tol).all(axis=2)
    return r & t


def exposure_normalise(ref8, test8, geo):
    """See the module docstring. Returns (test_norm float64 HxWx3 in [0,1] sRGB-encoded, info dict)."""
    info = dict(exposure_scale=1.0, exposure_scale_closed_form=1.0, exposure_clip_aware=False, exposure_scale_capped=False,
                expnorm_mean_ratio_after=None, expnorm_degenerate=False)
    test_f = test8.astype(np.float64) / 255.0
    if not geo.any():
        info["expnorm_degenerate"] = True
        return test_f, info
    ref_lin = srgb_to_linear(ref8.astype(np.float64) / 255.0)
    test_lin = srgb_to_linear(test_f)
    target = float((ref_lin[geo] @ LUMA).mean())
    tg = test_lin[geo]
    cur = float((tg @ LUMA).mean())
    if cur <= 0.0 or target <= 0.0:
        info["expnorm_degenerate"] = True      # a black image on either side: no meaningful scalar
        return test_f, info
    s0 = target / cur
    info["exposure_scale_closed_form"] = s0
    f = lambda s: float((np.clip(s * tg, 0, 1) @ LUMA).mean())      # noqa: E731
    if s0 <= 1.0:
        s = s0
    else:
        info["exposure_clip_aware"] = True
        if f(EXPNORM_CAP) < target:
            s, info["exposure_scale_capped"] = EXPNORM_CAP, True
        else:
            lo, hi = s0, EXPNORM_CAP
            for _ in range(60):
                mid = 0.5 * (lo + hi)
                lo, hi = (mid, hi) if f(mid) < target else (lo, mid)
            s = 0.5 * (lo + hi)
    info["exposure_scale"] = s
    out = test_f.copy()
    out[geo] = np.round(linear_to_srgb(np.clip(s * tg, 0, 1)) * 255.0) / 255.0
    # mean luminance of the normalised (8-bit) geometry over the reference's, so the residual of clipping and rounding is visible
    info["expnorm_mean_ratio_after"] = float((srgb_to_linear(out[geo]) @ LUMA).mean()) / target
    return out, info


# ----------------------------------------------------------------------------------------------- metrics

def flip_ldr(ref_f, test_f, ppd=None):
    """LDR-FLIP via flip-evaluator. ref_f, test_f: float arrays HxWx3 in [0,1], sRGB-encoded. Returns (err HxW float32, mean, params)."""
    import flip_evaluator
    params = {} if ppd is None else {"ppd": float(ppd)}
    err, mean, used = flip_evaluator.evaluate(np.ascontiguousarray(ref_f, dtype=np.float32), np.ascontiguousarray(test_f, dtype=np.float32),
                                              "LDR", inputsRGB=True, applyMagma=False, computeMeanError=True, parameters=params)
    return np.asarray(err, dtype=np.float32).reshape(ref_f.shape[0], ref_f.shape[1]), float(mean), used


def best_exposure_scale(ref8, test8, geo, ppd, s_centre):
    """Optional extra (--best-scale): the single linear-light scalar on the test geometry pixels that MINIMISES flip_mean
    (9-point log grid of +-0.5 ln units around s_centre, then bounded Brent inside the best cell; every candidate image is
    rounded to 8 bit like expnorm). Not the brief's expnorm: it is robust to the clipping bias of the mean-matching rule.
    Returns (best_s, flip_mean_at_best_s, number_of_flip_evaluations)."""
    from scipy.optimize import minimize_scalar
    ref_f = ref8.astype(np.float64) / 255.0
    test_f = test8.astype(np.float64) / 255.0
    tg = srgb_to_linear(test_f[geo])
    calls = [0]

    def cost(ls):
        calls[0] += 1
        o = test_f.copy()
        o[geo] = np.round(linear_to_srgb(np.clip(np.exp(ls) * tg, 0, 1)) * 255.0) / 255.0
        return flip_ldr(ref_f, o, ppd)[1]

    grid = np.log(s_centre) + np.linspace(-0.5, 0.5, 9)
    costs = [cost(g) for g in grid]
    i = int(np.argmin(costs))
    best_ls, best_c = grid[i], costs[i]
    r = minimize_scalar(cost, bounds=(grid[max(i - 1, 0)], grid[min(i + 1, 8)]), method="bounded", options=dict(xatol=2e-3))
    if r.fun < best_c:
        best_ls, best_c = float(r.x), float(r.fun)
    return float(np.exp(best_ls)), float(best_c), calls[0]


def versions():
    from importlib import metadata
    import skimage
    v = dict(python=sys.version.split()[0], numpy=np.__version__, pillow=Image.__version__, scikit_image=skimage.__version__)
    try:
        v["flip_evaluator"] = metadata.version("flip-evaluator")
    except Exception:  # noqa: BLE001
        v["flip_evaluator"] = "unknown"
    return v


def metrics_pair(ref8, test8, mask="auto", ppd=None, bg=None, bg_tol=0, want_maps=True, best_scale=False, names=("reference", "test")):
    """All numbers for one (reference, test) pair of equal-size uint8 RGB arrays. Returns (dict, maps dict)."""
    from skimage.metrics import peak_signal_noise_ratio, structural_similarity
    if ref8.shape != test8.shape:
        raise Refused(f"size differs: {names[0]} {ref8.shape[1]}x{ref8.shape[0]}, {names[1]} {test8.shape[1]}x{test8.shape[0]}; "
                      f"sizes must match, nothing is resized")
    h, w = ref8.shape[:2]
    out = dict(width=w, height=h, mask=mask, ppd_requested=ppd)
    warns = out["warnings"] = []
    if mask == "none":
        geo = np.ones((h, w), dtype=bool)
        out.update(bg_colour=None, geometry_fraction=1.0)
    else:
        corners = None
        if bg is None:
            bg, corners = corner_colour(ref8)
        else:
            corners = [list(bg)]
        bgm = background_mask(ref8, test8, bg, bg_tol)
        geo = ~bgm
        out.update(bg_colour=list(bg), bg_tol=bg_tol, geometry_fraction=float(geo.mean()))
        tbg, _ = corner_colour(test8)
        out["test_corner_colour"] = list(tbg)
        if max(abs(a - b) for a, b in zip(tbg, bg)) > bg_tol:
            warns.append(f"test corner colour {tuple(tbg)} differs from the reference bg {tuple(bg)}: every pixel that is not the reference bg "
                         f"in BOTH images counts as geometry (see --bg-tol, --mask none)")
        if bgm.mean() < 0.001:
            warns.append("the background rule matched under 0.1% of the frame (gradient/textured backdrop or colour mismatch): geometry is about the whole frame")
    has_geo = bool(geo.any())

    ref_f, test_f = ref8.astype(np.float64) / 255.0, test8.astype(np.float64) / 255.0
    err, fmean, used = flip_ldr(ref_f, test_f, ppd)
    out["flip_mean"] = fmean
    out["flip_mean_geometry"] = float(err[geo].mean()) if has_geo else None
    out["flip_p95"] = float(np.percentile(err, 95))
    out["flip_max"] = float(err.max())
    out["flip_ppd_used"] = float(used.get("ppd", 0.0))

    norm_f, info = exposure_normalise(ref8, test8, geo)
    out.update(info)
    if info["expnorm_degenerate"] or (not has_geo):
        err_n, out["flip_mean_expnorm"], out["flip_mean_expnorm_geometry"] = err, fmean, out["flip_mean_geometry"]
    else:
        err_n, nmean, _ = flip_ldr(ref_f, norm_f, ppd)
        out["flip_mean_expnorm"] = nmean
        out["flip_mean_expnorm_geometry"] = float(err_n[geo].mean())

    if best_scale and has_geo and not info["expnorm_degenerate"]:
        bs, bc, ncalls = best_exposure_scale(ref8, test8, geo, ppd, info["exposure_scale"])
        out.update(bestscale=bs, flip_mean_bestscale=bc, bestscale_flip_evals=ncalls)

    yr, yt = luma_encoded(ref8), luma_encoded(test8)
    s_val, s_map = structural_similarity(yr, yt, win_size=7, data_range=255.0, full=True)
    pad = 3
    out["ssim"] = float(s_val)
    if has_geo and h > 2 * pad and w > 2 * pad and geo[pad:-pad, pad:-pad].any():
        out["ssim_geometry"] = float(s_map[pad:-pad, pad:-pad][geo[pad:-pad, pad:-pad]].mean())
    else:
        out["ssim_geometry"] = None
    mse = float(np.mean((ref8.astype(np.float64) - test8.astype(np.float64)) ** 2))
    out["psnr_is_inf"] = mse == 0.0
    out["psnr"] = None if mse == 0.0 else float(peak_signal_noise_ratio(ref8, test8, data_range=255))
    d = np.abs(ref8.astype(np.int16) - test8.astype(np.int16)).astype(np.float64)
    out["mean_abs"] = float(d.mean())
    out["mean_abs_geometry"] = float(d[geo].mean()) if has_geo else None
    maps = dict(err=err, err_expnorm=err_n, geo=geo) if want_maps else {}
    return out, maps


# ----------------------------------------------------------------------------------------------- formatting

def f4(x, nd=4):
    return "-" if x is None else f"{x:.{nd}f}"


def psnr_s(r):
    return "inf" if r.get("psnr_is_inf") else ("-" if r.get("psnr") is None else f"{r['psnr']:.2f}")


def table(rows, ref_name):
    hdr = f"{'label':26s} {'flip':>8s} {'flip_expn':>9s} {'xposure':>8s} {'ssim':>7s} {'psnr':>7s} {'abs':>7s} {'abs_geo':>8s} {'geo%':>6s}"
    has_best = any("flip_mean_bestscale" in r for r in rows)
    if has_best:
        hdr += f" {'flip_best':>9s} {'best_s':>7s}"
    lines = [f"reference: {ref_name}", hdr]
    for r in rows:
        if "error" in r:
            lines.append(f"{r['label'][:26]:26s} REFUSED: {r['error']}")
            continue
        lines.append(f"{r['label'][:26]:26s}{'!' if r.get('warnings') else ' '}{f4(r['flip_mean']):>8s} {f4(r['flip_mean_expnorm']):>9s} {f4(r['exposure_scale'], 3):>8s} "
                     f"{f4(r['ssim']):>7s} {psnr_s(r):>7s} {f4(r['mean_abs'], 3):>7s} {f4(r['mean_abs_geometry'], 3):>8s} "
                     f"{100 * r['geometry_fraction']:6.1f}"
                     + (f" {f4(r.get('flip_mean_bestscale')):>9s} {f4(r.get('bestscale'), 3):>7s}" if has_best else ""))
    for r in rows:
        for w in r.get("warnings") or []:
            lines.append(f"  ! {r['label']}: {w}")
    return "\n".join(lines)


def safe_label(s):
    return re.sub(r"[^A-Za-z0-9._+-]+", "_", s).strip("_") or "img"


def make_labels(paths, labels):
    if labels:
        if len(labels) != len(paths):
            raise SystemExit(f"{TOOL}: {len(labels)} labels for {len(paths)} images")
        base = list(labels)
    else:
        base = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    seen, out = {}, []
    for b in base:
        b = safe_label(b)
        seen[b] = seen.get(b, 0) + 1
        out.append(b if seen[b] == 1 else f"{b}_{seen[b]}")
    return out


def run_compare(ref_path, test_paths, labels, mask="auto", ppd=None, bg=None, bg_tol=0, want_maps=True, best_scale=False, display=None):
    """Shared by compare / sheet / controls. Returns (ref8, rows, maps_by_label)."""
    ref8, rinfo = load_rgb8(ref_path)
    rows, maps = [], {}
    for i, (p, lab) in enumerate(zip(test_paths, labels)):
        row = dict(label=lab, path=os.path.abspath(p))
        if display:
            row["display"] = display[i]
        try:
            t8, tinfo = load_rgb8(p)
            row.update(input_mode=tinfo["mode"], input_size=tinfo["size"], input_notes=tinfo["notes"])
            m, mp = metrics_pair(ref8, t8, mask, ppd, bg, bg_tol, want_maps, best_scale)
            row.update(m)
            maps[lab] = dict(mp, test8=t8)
        except Refused as e:
            row["error"] = str(e)
        rows.append(row)
    return ref8, rinfo, rows, maps


def meta(ref_info, args_mask, ppd, bg_tol):
    return dict(tool=TOOL, versions=versions(), flip="LDR-FLIP (flip-evaluator), sRGB float inputs", heatmap_scale=HEAT_SCALE,
                mask=args_mask, ppd_requested=ppd, bg_tol=bg_tol, reference=ref_info)


def parse_bg(s):
    if s is None:
        return None
    try:
        v = [int(x) for x in s.split(",")]
        assert len(v) == 3 and all(0 <= x <= 255 for x in v)
        return tuple(v)
    except Exception:  # noqa: BLE001
        raise SystemExit(f"{TOOL}: --bg wants R,G,B in 0..255, got {s!r}")


# ----------------------------------------------------------------------------------------------- compare

def cmd_compare(a):
    labels = make_labels(a.test, a.labels)
    os.makedirs(a.out, exist_ok=True)
    try:
        _ref8, rinfo, rows, maps = run_compare(a.ref, a.test, labels, a.mask, a.ppd, parse_bg(a.bg), a.bg_tol, True, a.best_scale)
    except Refused as e:
        print(f"{TOOL}: reference refused: {e}", file=sys.stderr)
        return 2
    for lab, mp in maps.items():
        Image.fromarray(heatmap(mp["err"])).save(os.path.join(a.out, f"{lab}_flip.png"))
        Image.fromarray(heatmap(mp["err_expnorm"])).save(os.path.join(a.out, f"{lab}_flip_expnorm.png"))
    doc = dict(meta(rinfo, a.mask, a.ppd, a.bg_tol), results=rows)
    with open(os.path.join(a.out, "metrics.json"), "w") as fh:
        json.dump(doc, fh, indent=1)
    print(table(rows, os.path.basename(a.ref)))
    bad = [r for r in rows if "error" in r]
    for r in bad:
        print(f"{TOOL}: REFUSED {r['label']}: {r['error']}", file=sys.stderr)
    print(f"wrote {os.path.join(a.out, 'metrics.json')} and {len(maps)} x 2 heatmaps")
    return 3 if bad else 0


# ----------------------------------------------------------------------------------------------- sheet

def get_font(size, mono=False):
    names = (["DejaVuSansMono.ttf", "LiberationMono-Regular.ttf"] if mono else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"])
    dirs = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation", "/usr/share/fonts/dejavu", "/Library/Fonts"]
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def wrap_text(text, font, max_w):
    lines, cur = [], ""
    for word in text.split(" "):
        trial = (cur + " " + word) if cur else word
        if cur and font.getlength(trial) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + [cur] if cur else lines


def fit_tile(arr8, tile, bg=(20, 20, 24)):
    im = Image.fromarray(arr8)
    if im.size != (tile, tile):
        s = min(tile / im.width, tile / im.height)
        im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS if s < 1 else Image.NEAREST)
    canvas = Image.new("RGB", (tile, tile), bg)
    canvas.paste(im, ((tile - im.width) // 2, (tile - im.height) // 2))
    return canvas


def colour_bar(width, height, font):
    im = Image.new("RGB", (width, height), (20, 20, 24))
    d = ImageDraw.Draw(im)
    x0, x1, y0, y1 = 14, width - 14, 8, 8 + max(16, height // 12)
    ramp = apply_magma(np.linspace(0, 1, x1 - x0))
    im.paste(Image.fromarray(np.repeat(ramp[None], y1 - y0, axis=0)), (x0, y0))
    for i in range(6):
        x = x0 + round((x1 - x0 - 1) * i / 5)
        d.line([(x, y1), (x, y1 + 5)], fill=(200, 200, 205))
        d.text((x, y1 + 8), f"{HEAT_SCALE * i / 5:.1f}" if i < 5 else f"{HEAT_SCALE:.1f}+", fill=(220, 220, 225), font=font, anchor="ma")
    return im


def cmd_sheet(a):
    labels = make_labels(a.tests, a.labels)
    try:
        ref8, rinfo, rows, maps = run_compare(a.ref, a.tests, labels, a.mask, a.ppd, parse_bg(a.bg), a.bg_tol, True, a.best_scale, display=a.labels)
    except Refused as e:
        print(f"{TOOL}: reference refused: {e}", file=sys.stderr)
        return 2
    T = a.tile
    fs = max(12, T // 32)
    f_lab, f_num, f_small = get_font(fs + 4), get_font(fs, mono=True), get_font(max(11, fs - 3))
    line_h = fs + 6
    n_text = 6 if a.best_scale else 5
    cols = max(1, a.cols or min(len(rows), 5))
    blocks = [rows[i:i + cols] for i in range(0, len(rows), cols)] or [[]]
    pad, lab_h, text_h = 10, fs + 14, n_text * line_h + 8
    n_rows_per_block = 2 + (1 if a.expnorm_row else 0)
    block_h = lab_h + T + text_h + (n_rows_per_block - 1) * (T + lab_h) + 14
    W = pad + (cols + 1) * (T + pad)
    v = versions()
    head1 = wrap_text(f"{TOOL}  |  reference: {os.path.basename(a.ref)}  |  FLIP LDR (flip-evaluator {v['flip_evaluator']}), mask {a.mask}, "
                      f"ppd {'67 (default)' if a.ppd is None else a.ppd}", f_lab, W - 2 * pad)
    head2 = wrap_text(f"heatmap = FLIP error, magma, fixed scale 0..{HEAT_SCALE};  expnorm = one linear-light exposure scalar on the test image "
                      f"(non-background mean luminance matched to the reference)", f_small, W - 2 * pad)
    head_h = 8 + len(head1) * (fs + 8) + len(head2) * (fs + 1) + 8
    H = head_h + len(blocks) * block_h + pad
    sheet = Image.new("RGB", (W, H), (20, 20, 24))
    d = ImageDraw.Draw(sheet)
    hy = 8
    for ln in head1:
        d.text((pad, hy), ln, fill=(235, 235, 240), font=f_lab)
        hy += fs + 8
    for ln in head2:
        d.text((pad, hy), ln, fill=(170, 170, 180), font=f_small)
        hy += fs + 1
    for bi, block in enumerate(blocks):
        y0 = head_h + bi * block_h
        # reference column
        x = pad
        d.text((x, y0), "REFERENCE", fill=(120, 200, 255), font=f_lab)
        sheet.paste(fit_tile(ref8, T), (x, y0 + lab_h))
        ty = y0 + lab_h + T + 4
        bgc, _ = corner_colour(ref8)
        for i, s in enumerate([os.path.basename(a.ref)[:T // (fs // 2 + 3)], f"{ref8.shape[1]}x{ref8.shape[0]} px, bg {bgc}" if a.mask != "none" else f"{ref8.shape[1]}x{ref8.shape[0]} px, mask none"]):
            d.text((x, ty + i * line_h), s, fill=(225, 225, 230), font=f_num)
        ry = y0 + lab_h + T + text_h
        d.text((x, ry), "FLIP error scale", fill=(120, 200, 255), font=f_lab)
        sheet.paste(colour_bar(T, T, f_small), (x, ry + lab_h))
        # test columns
        for ci, r in enumerate(block):
            x = pad + (ci + 1) * (T + pad)
            d.text((x, y0), r.get("display", r["label"]), fill=(255, 215, 120), font=f_lab)
            mp = maps.get(r["label"])
            if "error" in r or mp is None:
                tile = Image.new("RGB", (T, T), (60, 20, 20))
                ImageDraw.Draw(tile).text((10, 10), "REFUSED", fill=(255, 120, 120), font=f_lab)
                sheet.paste(tile, (x, y0 + lab_h))
                msg = r.get("error", "")
                for k in range(0, min(len(msg), 3 * 40), 40):
                    d.text((x, y0 + lab_h + T + 4 + (k // 40) * line_h), msg[k:k + 40], fill=(255, 140, 140), font=f_num)
                continue
            sheet.paste(fit_tile(mp["test8"], T), (x, y0 + lab_h))
            lines = [f"FLIP {f4(r['flip_mean'])}  geo {f4(r['flip_mean_geometry'])}",
                     f"FLIP expnorm {f4(r['flip_mean_expnorm'])}  x{r['exposure_scale']:.3f}",
                     f"SSIM {f4(r['ssim'])}  PSNR {psnr_s(r)}",
                     f"|d| {f4(r['mean_abs'], 2)}  geo {f4(r['mean_abs_geometry'], 2)}",
                     f"geometry {100 * r['geometry_fraction']:.1f}% of frame"]
            if "flip_mean_bestscale" in r:
                lines.append(f"best-scale FLIP {f4(r['flip_mean_bestscale'])}  x{r['bestscale']:.3f}")
            ty = y0 + lab_h + T + 4
            for i, s in enumerate(lines):
                d.text((x, ty + i * line_h), s, fill=(235, 235, 240) if i < 2 else (200, 200, 208), font=f_num)
            ry = y0 + lab_h + T + text_h
            d.text((x, ry), "FLIP error", fill=(255, 215, 120), font=f_lab)
            sheet.paste(fit_tile(heatmap(mp["err"]), T), (x, ry + lab_h))
            if a.expnorm_row:
                ry2 = ry + lab_h + T
                d.text((x, ry2), "FLIP error after exposure normalisation", fill=(255, 215, 120), font=f_lab)
                sheet.paste(fit_tile(heatmap(mp["err_expnorm"]), T), (x, ry2 + lab_h))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    sheet.save(a.out)
    print(table(rows, os.path.basename(a.ref)))
    print(f"wrote {a.out} ({W}x{H})")
    return 3 if any("error" in r for r in rows) else 0


# ----------------------------------------------------------------------------------------------- floor

def cmd_floor(a):
    try:
        a8, ia = load_rgb8(a.a)
        b8, ib = load_rgb8(a.b)
        m, mp = metrics_pair(a8, b8, a.mask, a.ppd, parse_bg(a.bg), a.bg_tol, want_maps=bool(a.heatmap), best_scale=a.best_scale, names=("A", "B"))
    except Refused as e:
        print(f"{TOOL}: REFUSED: {e}", file=sys.stderr)
        return 2
    m.update(a=os.path.abspath(a.a), b=os.path.abspath(a.b), input_notes=ia["notes"] + ib["notes"])
    if a.heatmap:
        Image.fromarray(heatmap(mp["err"])).save(a.heatmap)
    doc = dict(meta(ia, a.mask, a.ppd, a.bg_tol), floor=m)
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, "w") as fh:
            json.dump(doc, fh, indent=1)
    print(f"noise floor  A={os.path.basename(a.a)}  B={os.path.basename(a.b)}  ({m['width']}x{m['height']}, mask {a.mask}, geometry {100 * m['geometry_fraction']:.1f}%)")
    print(f"  flip_mean {m['flip_mean']:.5f}   flip_p95 {m['flip_p95']:.4f}   flip_max {m['flip_max']:.4f}   flip_mean_geometry {f4(m['flip_mean_geometry'], 5)}")
    print(f"  mean_abs {m['mean_abs']:.4f}   mean_abs_geometry {f4(m['mean_abs_geometry'], 4)}   ssim {m['ssim']:.5f}   psnr {psnr_s(m)}")
    return 0


# ----------------------------------------------------------------------------------------------- controls

def _roundq(x):
    return np.clip(np.round(x * 255), 0, 255).astype(np.uint8)


def build_controls(ref8, seed=1):
    """name -> (description, test8, own_reference8 or None)."""
    rng = np.random.default_rng(seed)
    f = ref8.astype(np.float64) / 255.0
    lin = srgb_to_linear(f)
    out = {}
    out["identity"] = ("copy of the reference", ref8.copy(), None)
    for q in (95, 90, 75):
        buf = io.BytesIO()
        Image.fromarray(ref8).save(buf, "JPEG", quality=q)
        buf.seek(0)
        out[f"jpeg_q{q}"] = (f"JPEG quality {q} round trip", np.asarray(Image.open(buf).convert("RGB")).copy(), None)
    for sg in (2, 8):
        out[f"noise_s{sg}"] = (f"gaussian noise sigma {sg}/255 per channel (sRGB-encoded), seed {seed}",
                               np.clip(np.round(ref8 + rng.normal(0, sg, ref8.shape)), 0, 255).astype(np.uint8), None)
    for sg in (1.0, 2.0):
        out[f"blur_s{sg:g}"] = (f"gaussian blur sigma {sg:g} px", np.asarray(Image.fromarray(ref8).filter(ImageFilter.GaussianBlur(sg))).copy(), None)
    for dx in (2, 8):
        sh = np.pad(ref8, ((0, 0), (dx, 0), (0, 0)), mode="edge")[:, :ref8.shape[1]]
        out[f"shift_x{dx}"] = (f"content shifted right by {dx} px (edge replicate)", np.ascontiguousarray(sh), None)
    out["exp_x1.5_lin"] = ("linear light x1.5 (+0.585 EV), clipped at 1.0", _roundq(linear_to_srgb(1.5 * lin)), None)
    bgc, _ = corner_colour(ref8)
    keep = (ref8 == np.array(bgc, dtype=np.uint8)).all(axis=2, keepdims=True)
    out["exp_x1.5_lin_keepbg"] = ("linear light x1.5 clipped, pixels equal to the reference corner colour left alone (light scale differs, clear colour does not)",
                                  np.where(keep, ref8, _roundq(linear_to_srgb(1.5 * lin))).astype(np.uint8), None)
    dark = _roundq(linear_to_srgb(lin / 1.5))
    out["exp_x1.5_lin_noclip"] = ("test = reference, reference = linear light /1.5 (so the test is 1.5x brighter, nothing clips)", ref8.copy(), dark)
    out["exp_x0.667_lin"] = ("linear light x2/3 (-0.585 EV)", _roundq(linear_to_srgb(lin * (2 / 3))), None)
    out["bright_x1.5_srgb"] = ("sRGB-encoded values x1.5, clipped (gamma-space multiply)", _roundq(f * 1.5), None)
    cast = lin * np.array([1.1, 1.0, 0.9])
    out["cast_r1.1_b0.9_lin"] = ("linear light R x1.1, B x0.9 (colour cast)", _roundq(linear_to_srgb(cast)), None)
    out["black"] = ("all-black frame", np.zeros_like(ref8), None)
    out["inverted"] = ("255 - value", (255 - ref8).astype(np.uint8), None)
    return out


def cmd_controls(a):
    try:
        ref8, rinfo = load_rgb8(a.ref)
    except Refused as e:
        print(f"{TOOL}: reference refused: {e}", file=sys.stderr)
        return 2
    cdir = os.path.join(a.out, "controls")
    os.makedirs(cdir, exist_ok=True)
    rows = []
    for name, (desc, t8, own_ref) in build_controls(ref8).items():
        Image.fromarray(t8).save(os.path.join(cdir, f"{name}.png"))
        r8 = ref8 if own_ref is None else own_ref
        if own_ref is not None:
            Image.fromarray(own_ref).save(os.path.join(cdir, f"{name}_REF.png"))
        m, mp = metrics_pair(r8, t8, a.mask, a.ppd, parse_bg(a.bg), a.bg_tol, want_maps=True, best_scale=a.best_scale)
        Image.fromarray(heatmap(mp["err"])).save(os.path.join(cdir, f"{name}_flip.png"))
        rows.append(dict(label=name, description=desc, own_reference=own_ref is not None, **m))
    doc = dict(meta(rinfo, a.mask, a.ppd, a.bg_tol), controls=rows)
    with open(os.path.join(a.out, "controls.json"), "w") as fh:
        json.dump(doc, fh, indent=1)
    txt = table(rows, os.path.basename(a.ref))
    txt += "\n\n" + "\n".join(f"{r['label']:22s} {r['description']}" for r in rows)
    with open(os.path.join(a.out, "controls.txt"), "w") as fh:
        fh.write(txt + "\n")
    print(txt)
    return 0


def cmd_selftest(a):
    """Re-runs the controls on REF and checks the relations the yardstick must satisfy. Exit 0 = all pass."""
    ref8, _ = load_rgb8(a.ref)
    res = {}
    for name, (_d, t8, own) in build_controls(ref8).items():
        if name in ("identity", "blur_s1", "shift_x8", "exp_x1.5_lin_noclip", "exp_x0.667_lin"):
            res[name] = metrics_pair(ref8 if own is None else own, t8, a.mask, a.ppd, parse_bg(a.bg), a.bg_tol, want_maps=False)[0]
    fl = lambda n: res[n]["flip_mean"]      # noqa: E731
    fx = lambda n: res[n]["flip_mean_expnorm"]      # noqa: E731
    checks = [
        ("FLIP(identity) == 0 and psnr inf", fl("identity") == 0.0 and res["identity"]["psnr_is_inf"]),
        ("0 < FLIP(blur sigma 1) < FLIP(shift 8 px)", 0 < fl("blur_s1") < fl("shift_x8")),
        ("FLIP(shift 8 px) < FLIP(exposure x1.5, no clipping)", fl("shift_x8") < fl("exp_x1.5_lin_noclip")),
        ("expnorm removes >= 90% of the exposure x1.5 FLIP", fx("exp_x1.5_lin_noclip") <= 0.1 * fl("exp_x1.5_lin_noclip")),
        ("expnorm removes >= 90% of the exposure x0.667 FLIP", fx("exp_x0.667_lin") <= 0.1 * fl("exp_x0.667_lin")),
        ("exposure_scale within 3% of the true factor (x1/1.5, x1.5)",
         abs(res["exp_x1.5_lin_noclip"]["exposure_scale"] * 1.5 - 1) < 0.03 and abs(res["exp_x0.667_lin"]["exposure_scale"] / 1.5 - 1) < 0.03),
    ]
    ok = True
    for name, passed in checks:
        ok &= bool(passed)
        print(("PASS  " if passed else "FAIL  ") + name)
    print("flip_mean: " + ", ".join(f"{n} {fl(n):.4f}" for n in res) + "  |  expnorm: " + ", ".join(f"{n} {fx(n):.4f}" for n in res))
    return 0 if ok else 1


# ----------------------------------------------------------------------------------------------- cli

def add_common(p):
    p.add_argument("--mask", choices=["auto", "none"], default="auto", help="background rule (default auto, see --help of the module)")
    p.add_argument("--ppd", type=float, default=None, help="FLIP pixels per degree (default: flip-evaluator's 67)")
    p.add_argument("--bg", default=None, help="override the background colour R,G,B (default: reference corner rule)")
    p.add_argument("--bg-tol", type=int, default=0, help="per-channel tolerance for the background test (default 0 = exact)")
    p.add_argument("--best-scale", action="store_true", help="also search the single exposure scalar that minimises FLIP (about 20 extra FLIP runs per test image)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compare", help="metrics of test images against a reference")
    c.add_argument("--ref", required=True)
    c.add_argument("--test", nargs="+", required=True)
    c.add_argument("--labels", nargs="+", default=None)
    c.add_argument("--out", required=True)
    add_common(c)
    c.set_defaults(fn=cmd_compare)

    s = sub.add_parser("sheet", help="labelled montage: reference, tests with numbers, FLIP heatmaps")
    s.add_argument("--ref", required=True)
    s.add_argument("--tests", nargs="+", required=True)
    s.add_argument("--labels", nargs="+", default=None)
    s.add_argument("--out", required=True)
    s.add_argument("--tile", type=int, default=512)
    s.add_argument("--cols", type=int, default=0, help="test tiles per row-block (default: all up to 5, then wraps; the reference repeats in each block)")
    s.add_argument("--expnorm-row", action="store_true", help="add a third row: FLIP heatmaps after exposure normalisation")
    add_common(s)
    s.set_defaults(fn=cmd_sheet)

    f = sub.add_parser("floor", help="noise floor between two renders of the same thing")
    f.add_argument("--a", required=True)
    f.add_argument("--b", required=True)
    f.add_argument("--json", default=None)
    f.add_argument("--heatmap", default=None, help="optional PNG path for the FLIP heatmap")
    add_common(f)
    f.set_defaults(fn=cmd_floor)

    k = sub.add_parser("controls", help="calibration controls built from one reference image")
    k.add_argument("--ref", required=True)
    k.add_argument("--out", required=True)
    add_common(k)
    k.set_defaults(fn=cmd_controls)

    t = sub.add_parser("selftest", help="check the control relations on one reference image (exit 1 on failure)")
    t.add_argument("--ref", required=True)
    add_common(t)
    t.set_defaults(fn=cmd_selftest)

    a = ap.parse_args(argv)
    t0 = time.time()
    rc = a.fn(a)
    print(f"({time.time() - t0:.1f} s)", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
