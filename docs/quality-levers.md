# Castle quality levers vs the Cycles reference (public run)

Scope: Castle Game Engine 7.0-alpha.3 snapshot (FPC 3.2.2), Mesa llvmpipe (LLVM 20.1.2) GL 4.5, no GPU, 512x512, single frame per lever.
Reference: Blender 5.3.0 Cycles CPU, add-on 603ca7a, 256 spp, GI on, no denoise. Metric: FLIP LDR (flip-evaluator 1.7, 67 ppd), `flip_mean` and `flip_mean_expnorm`
from `quality_metrics.py` (sha1_12 c99eeef912ac). Data: `results/quality/public/results.json`, `results/quality/public/castle_all_levers.json`, per-scene `results/quality/public/<scene>/castle_<lever>.png(.json)`,
sheets in `results/quality/public/sheets/`. Every delta below is `lever - castle_native` on the same scene against the same reference; negative = closer to the reference.
Grades: Confirmed = measured here (data named), Likely = measured, cause inferred, Suspected = read in source or inferred, not run.
I say "agree", not "follows"; X_ITE is one reference among several and is not used as a target here.

## 0. Headline

1. No single Castle lever moves the mean FLIP materially. Over the 15 public scenes the best single-lever mean change in `flip_mean` is ssaa4 -0.0027 (expnorm -0.0000); over core11 (the 11 scenes whose reference is not contaminated, defined in 1c) it is ssaa4 -0.0003, msaa4 -0.0002, aniso16 -0.0001. The reference noise floor (Cycles seed 0 vs 1) is 0.0034 mean. The whole lever menu is worth less than one noise-floor unit, while Castle's gap to the reference is 0.1321 (X_ITE 0.0748).
2. The gap is not a lever problem. Two scenes carry 77 % of the castle_native-minus-xite mean gap (0.0573): materials-world (castle_native minus xite flip_mean +0.4833) and lights-after (+0.1784); (0.4833+0.1784)/15 = 0.0441 of the 0.0573. Their `exposure_scale` against the reference is 0.123 and 0.712 (Castle is about 8x and 1.4x too bright), p1/p4 are 0.253/0.277. Exposure / light-unit calibration is outside the lever menu (Castle has no exposure lever; `u_Exposure` is commented out, `tone_mapping.fs:20,114`). Cause of the brightness gap not investigated here.
3. Shadow maps are the only lever with a large effect, and its sign depends on the reference: it is correct and large when the reference has shadows (stilllife-direct against `ref_shadows`: 0.1238 -> 0.0824 at 2048) and wrong when the file does not ask for shadows (against `ref`: 0.0842 -> 0.1282). X3D `shadows` defaults to false, so the file-literal image has no shadows in 12 of 15 scenes.
4. Tone mapping, colour space, SSAO, SSR, PBR mapping, IBL all make the mean worse. Several apparent per-scene wins are exposure coincidences or reference omissions (sections 3, 4).

## 1. Per-lever, per-scene delta (lever minus castle_native)

Columns: sl-dir stilllife-direct, sl-stg stilllife-stage, mat-w materials-world, lit-aft lights-after, annot annotation-standard, quat quaternion-xyzw, nurbs nurbs-weights.
`better/worse` counts scenes with delta below -0.001 / above +0.001. A `-` means the lever could not render (shadows needs a DirectionalLight or SpotLight: absent in earth-planet, village, p1, p2, p4, repair-2-render; castle-render exits 3 with the message, no unshadowed picture is written under a shadow label).
Warning for expnorm: it can be worse than plain FLIP when `exposure_scale` is far from 1 (native exposure_scale: mat-w 0.123, lit-aft 0.712, p1 0.253, p4 0.277, nurbs 0.381, quat 3.289, annot 0.782). quaternion-xyzw is worst: expnorm 0.4155 versus plain 0.2611 for the same image, so its expnorm column is not trustworthy. materials-world is saturated (white clipped floor and spheres in every Castle leg), so its deltas measure how much floor each lever darkens, not fidelity.

### 1a. flip_mean_expnorm (requested metric)

| lever | sl-dir | sl-stg | mat-w | lit-aft | village | earth | annot | p1 | p2 | p3 | p4 | p5 | nurbs | quat | repair | mean | better/worse |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NATIVE absolute | 0.0848 | 0.0931 | 0.2852 | 0.1652 | 0.0851 | 0.0023 | 0.1848 | 0.0193 | 0.0469 | 0.0049 | 0.0091 | 0.0021 | 0.1613 | 0.4155 | 0.0075 | 0.1045 | - |
| shadows | +0.0680 | +0.0538 | -0.0146 | +0.0055 | - | - | +0.0002 | - | - | +0.0000 | - | +0.0000 | +0.0000 | +0.0001 | - | +0.0126 (n=9) | 1 / 3 |
| shadows2048 | +0.0719 | +0.0559 | -0.0136 | +0.0061 | - | - | +0.0007 | - | - | +0.0000 | - | +0.0000 | -0.0057 | +0.0011 | - | +0.0129 (n=9) | 2 / 4 |
| ssao | +0.0035 | +0.0029 | -0.0060 | -0.0013 | +0.0471 | +0.0006 | +0.0077 | -0.0000 | +0.0000 | +0.0000 | -0.0000 | +0.0000 | +0.0010 | +0.0013 | +0.0001 | +0.0038 (n=15) | 2 / 5 |
| ssr | +0.0015 | -0.0009 | +0.0001 | +0.0039 | +0.0127 | +0.0000 | +0.0001 | -0.0000 | -0.0004 | +0.0000 | -0.0000 | +0.0000 | -0.0000 | -0.0000 | +0.0000 | +0.0011 (n=15) | 0 / 3 |
| tonemap_aces | +0.0077 | +0.0482 | -0.0124 | +0.0388 | +0.1591 | +0.0022 | -0.0010 | -0.0001 | -0.0111 | +0.0000 | +0.0004 | +0.0000 | -0.0083 | -0.0247 | +0.0032 | +0.0135 (n=15) | 4 / 6 |
| tonemap_uncharted | +0.0104 | +0.0149 | -0.0307 | -0.0002 | +0.0988 | +0.0065 | +0.0530 | -0.0000 | -0.0093 | -0.0000 | +0.0001 | +0.0000 | +0.0199 | +0.0319 | +0.0047 | +0.0133 (n=15) | 2 / 8 |
| tonemap_hejl | +0.0418 | +0.0600 | -0.0174 | +0.0276 | +0.1513 | +0.0037 | +0.0184 | -0.0001 | -0.0110 | -0.0000 | -0.0002 | +0.0000 | -0.0035 | -0.0050 | +0.0039 | +0.0180 (n=15) | 4 / 7 |
| shading_phong | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 (n=15) | 0 / 0 |
| shading_gouraud | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | -0.0005 | +0.0000 | -0.0019 | +0.0000 | +0.0000 | +0.0000 | -0.0058 | +0.0007 | +0.0000 | -0.0005 (n=15) | 2 / 0 |
| shading_pbr | +0.0000 | +0.0000 | -0.0001 | +0.0000 | +0.0000 | +0.0000 | +0.0884 | +0.0000 | -0.0116 | +0.0024 | +0.0000 | +0.0000 | +0.0102 | +0.0395 | +0.0001 | +0.0086 (n=15) | 1 / 4 |
| msaa4 | -0.0005 | -0.0005 | -0.0003 | +0.0003 | -0.0008 | +0.0018 | +0.0013 | -0.0010 | -0.0013 | +0.0012 | -0.0005 | -0.0007 | -0.0000 | +0.0017 | +0.0000 | +0.0001 (n=15) | 1 / 4 |
| ssaa2 | -0.0003 | -0.0002 | +0.0002 | +0.0002 | -0.0003 | +0.0015 | +0.0013 | -0.0008 | -0.0012 | +0.0017 | -0.0006 | -0.0005 | -0.0038 | +0.0013 | -0.0000 | -0.0001 (n=15) | 2 / 4 |
| ssaa4 | -0.0004 | -0.0005 | +0.0009 | +0.0003 | -0.0008 | +0.0017 | +0.0015 | -0.0010 | -0.0013 | +0.0012 | -0.0005 | -0.0007 | -0.0024 | +0.0018 | +0.0000 | -0.0000 (n=15) | 2 / 4 |
| aniso16 | -0.0001 | -0.0001 | -0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | -0.0000 (n=15) | 0 / 0 |
| colorspace_linear | +0.0000 | +0.0000 | -0.0004 | +0.0000 | +0.2055 | +0.0122 | +0.1509 | +0.0000 | -0.0106 | -0.0002 | +0.0000 | +0.0000 | +0.0391 | +0.0570 | +0.0025 | +0.0304 (n=15) | 1 / 6 |
| colorspace_srgb | +0.0320 | +0.1182 | -0.0130 | +0.1782 | +0.0000 | +0.0000 | +0.0000 | +0.0038 | +0.0000 | +0.0000 | +0.0018 | +0.0000 | +0.0000 | +0.0000 | -0.0008 | +0.0213 (n=15) | 1 / 5 |
| ibl | +0.0821 | +0.0415 | -0.0093 | -0.0352 | +0.0000 | +0.0000 | +0.0160 | +0.0024 | -0.0043 | +0.0014 | +0.0079 | +0.0056 | -0.0123 | -0.0361 | +0.0017 | +0.0041 (n=15) | 5 / 8 |
| all | -0.0004 | -0.0005 | +0.0009 | +0.0003 | -0.0008 | +0.0017 | +0.0000 | -0.0010 | -0.0026 | +0.0012 | -0.0005 | -0.0007 | -0.0117 | +0.0018 | +0.0000 | -0.0008 (n=15) | 2 / 3 |

### 1b. flip_mean (plain)

| lever | sl-dir | sl-stg | mat-w | lit-aft | village | earth | annot | p1 | p2 | p3 | p4 | p5 | nurbs | quat | repair | mean | better/worse |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NATIVE absolute | 0.0842 | 0.0951 | 0.5956 | 0.2852 | 0.0772 | 0.0023 | 0.1975 | 0.0546 | 0.0465 | 0.0163 | 0.0446 | 0.0047 | 0.2122 | 0.2611 | 0.0044 | 0.1321 | - |
| shadows | +0.0425 | +0.0378 | -0.0408 | -0.0038 | - | - | +0.0000 | - | - | +0.0000 | - | +0.0000 | +0.0001 | -0.0000 | - | +0.0040 (n=9) | 2 / 2 |
| shadows2048 | +0.0440 | +0.0391 | -0.0472 | -0.0035 | - | - | +0.0009 | - | - | +0.0000 | - | +0.0000 | -0.0048 | -0.0001 | - | +0.0031 (n=9) | 3 / 2 |
| ssao | +0.0043 | +0.0051 | -0.0044 | -0.0154 | +0.0978 | +0.0003 | +0.0043 | -0.0001 | +0.0000 | +0.0000 | -0.0000 | +0.0000 | +0.0033 | +0.0016 | +0.0001 | +0.0065 (n=15) | 2 / 6 |
| ssr | +0.0007 | +0.0004 | +0.0001 | -0.0154 | +0.0186 | +0.0000 | -0.0016 | +0.0000 | -0.0001 | +0.0000 | +0.0000 | +0.0000 | -0.0000 | +0.0000 | +0.0000 | +0.0002 (n=15) | 2 / 1 |
| tonemap_aces | +0.0169 | +0.0455 | +0.0098 | +0.1893 | +0.2458 | +0.0025 | +0.0080 | +0.0122 | -0.0117 | +0.0018 | +0.0044 | +0.0001 | +0.0020 | -0.0052 | +0.0073 | +0.0352 (n=15) | 2 / 12 |
| tonemap_uncharted | +0.0251 | +0.0445 | -0.0447 | -0.1203 | +0.4297 | +0.0065 | -0.0003 | -0.0111 | +0.0170 | +0.0565 | -0.0081 | +0.0131 | -0.0311 | -0.0169 | +0.0099 | +0.0246 (n=15) | 6 / 8 |
| tonemap_hejl | +0.0500 | +0.0541 | -0.0064 | +0.1003 | +0.1450 | +0.0029 | -0.0137 | +0.0068 | +0.0029 | +0.0268 | +0.0022 | -0.0026 | -0.0163 | -0.0192 | +0.0094 | +0.0228 (n=15) | 5 / 10 |
| shading_phong | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 (n=15) | 0 / 0 |
| shading_gouraud | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0015 | +0.0000 | -0.0021 | +0.0000 | +0.0000 | +0.0000 | -0.0046 | -0.0006 | +0.0000 | -0.0004 (n=15) | 2 / 1 |
| shading_pbr | +0.0000 | +0.0000 | +0.0001 | +0.0000 | +0.0000 | +0.0000 | +0.0285 | +0.0000 | +0.0131 | +0.0498 | +0.0000 | +0.0000 | +0.0165 | +0.0106 | +0.0003 | +0.0079 (n=15) | 0 / 5 |
| msaa4 | -0.0002 | -0.0002 | +0.0005 | -0.0005 | +0.0002 | +0.0008 | -0.0008 | -0.0002 | -0.0011 | -0.0016 | -0.0000 | -0.0005 | -0.0002 | -0.0007 | -0.0002 | -0.0003 (n=15) | 2 / 0 |
| ssaa2 | -0.0001 | -0.0001 | +0.0003 | -0.0005 | -0.0010 | +0.0007 | -0.0008 | -0.0001 | -0.0012 | -0.0012 | +0.0000 | -0.0003 | -0.0224 | -0.0005 | -0.0003 | -0.0018 (n=15) | 3 / 0 |
| ssaa4 | -0.0001 | -0.0000 | -0.0015 | -0.0005 | +0.0001 | +0.0008 | -0.0010 | -0.0002 | -0.0012 | -0.0016 | -0.0000 | -0.0005 | -0.0345 | -0.0007 | -0.0002 | -0.0027 (n=15) | 5 / 0 |
| aniso16 | -0.0001 | -0.0001 | -0.0008 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | -0.0001 (n=15) | 0 / 0 |
| colorspace_linear | +0.0000 | +0.0000 | +0.0002 | +0.0000 | +0.3780 | +0.0278 | +0.4430 | +0.0000 | -0.0014 | +0.0193 | +0.0000 | +0.0000 | +0.4288 | +0.3778 | +0.0043 | +0.1118 (n=15) | 1 / 7 |
| colorspace_srgb | +0.1846 | +0.2408 | +0.0138 | +0.2162 | +0.0000 | +0.0000 | +0.0000 | -0.0254 | +0.0000 | +0.0000 | -0.0188 | +0.0527 | +0.0000 | +0.0000 | +0.0002 | +0.0443 (n=15) | 2 / 5 |
| ibl | +0.1396 | +0.0940 | +0.0119 | +0.1736 | +0.0000 | +0.0000 | +0.0462 | +0.0291 | +0.0239 | +0.0340 | +0.0403 | +0.0586 | +0.0004 | +0.0033 | +0.0012 | +0.0437 (n=15) | 0 / 12 |
| all | -0.0001 | -0.0000 | -0.0015 | -0.0005 | +0.0001 | +0.0008 | +0.0004 | -0.0002 | -0.0033 | -0.0016 | -0.0000 | -0.0005 | -0.0394 | -0.0013 | -0.0002 | -0.0032 (n=15) | 5 / 0 |

### 1c. Same deltas over cleaner scene subsets (mean of flip_mean / mean of flip_mean_expnorm)

Subsets: core11 = the 15 minus annotation-standard (Billboard not drawn and gradient Background flattened in the reference), nurbs-weights (add-on cannot import NurbsCurve, the reference has no curve), quaternion-xyzw (exposure_scale 3.3), p2-point-classic (reference falls off 1/d^2, file says attenuation 1 0 0). core10 = core11 without materials-world (saturated).
Native baseline: core11 0.1149 / 0.0690, core10 0.0669 / 0.0474 (X_ITE core11 0.0458 / 0.0484).

| lever | all 15 | core11 | core10 | 15 minus nurbs |
|---|---|---|---|---|
| shadows (n=9/6/5/8) | +0.0040 / +0.0126 | +0.0059 / +0.0188 | +0.0153 / +0.0255 | +0.0045 / +0.0141 |
| shadows2048 | +0.0031 / +0.0129 | +0.0054 / +0.0200 | +0.0159 / +0.0268 | +0.0041 / +0.0152 |
| ssao | +0.0065 / +0.0038 | +0.0080 / +0.0043 | +0.0092 / +0.0053 | +0.0067 / +0.0040 |
| ssr | +0.0002 / +0.0011 | +0.0004 / +0.0016 | +0.0004 / +0.0017 | +0.0002 / +0.0012 |
| tonemap_aces | +0.0352 / +0.0135 | +0.0487 / +0.0225 | +0.0526 / +0.0260 | +0.0376 / +0.0150 |
| tonemap_uncharted | +0.0246 / +0.0133 | +0.0365 / +0.0095 | +0.0446 / +0.0135 | +0.0286 / +0.0129 |
| tonemap_hejl | +0.0228 / +0.0180 | +0.0353 / +0.0246 | +0.0395 / +0.0288 | +0.0256 / +0.0195 |
| shading_gouraud | -0.0004 / -0.0005 | +0.0000 / +0.0000 | +0.0000 / +0.0000 | -0.0001 / -0.0001 |
| shading_pbr (our mapping) | +0.0079 / +0.0086 | +0.0046 / +0.0002 | +0.0050 / +0.0003 | +0.0073 / +0.0085 |
| msaa4 | -0.0003 / +0.0001 | -0.0002 / -0.0001 | -0.0002 / -0.0001 | -0.0003 / +0.0001 |
| ssaa2 | -0.0018 / -0.0001 | -0.0002 / +0.0001 | -0.0003 / +0.0001 | -0.0004 / +0.0002 |
| ssaa4 | -0.0027 / -0.0000 | -0.0003 / +0.0000 | -0.0002 / -0.0001 | -0.0005 / +0.0002 |
| aniso16 | -0.0001 / -0.0000 | -0.0001 / -0.0000 | -0.0000 / -0.0000 | -0.0001 / -0.0000 |
| colorspace_linear | +0.1118 / +0.0304 | +0.0391 / +0.0200 | +0.0429 / +0.0220 | +0.0892 / +0.0298 |
| colorspace_srgb | +0.0443 / +0.0213 | +0.0604 / +0.0291 | +0.0650 / +0.0333 | +0.0474 / +0.0229 |
| ibl (synthetic sky) | +0.0437 / +0.0041 | +0.0529 / +0.0089 | +0.0570 / +0.0107 | +0.0468 / +0.0053 |
| castle_all (ssaa4+gouraud) | -0.0032 / -0.0008 | -0.0003 / +0.0000 | -0.0002 / -0.0001 | -0.0006 / -0.0000 |

Reading: the -0.0027 for ssaa4 on all 15 is 0.0345 of one scene (nurbs-weights) divided by 15 (see section 4). Remove it and ssaa4 is -0.0005. castle_all's chosen levers (ssaa4 + gouraud) were picked in-sample by the same scenes that score it; on core11 it is -0.0003 flip, +0.0000 expnorm.

## 2. Best single lever, best combination

Against the file-literal reference (`ref.png`), by `flip_mean`:
- Best single lever over 15 scenes: ssaa4 (-0.0027). Over core11: ssaa4 (-0.0003), msaa4 (-0.0002), aniso16 (-0.0001). All three are inside the reference's seed-to-seed spread (0.0034); the harmful levers are not. The honest reading is "no lever helps measurably; AA is the only family that is non-negative on most scenes". Confirmed (data), grade for the ranking itself: Likely (sub-noise).
- By `flip_mean_expnorm` over 15: castle_all -0.0008, shading_gouraud -0.0005, ssaa2 -0.0001; nothing exceeds 0.001.
Against the shadow-enabled reference (`ref_shadows`, every light casts), over the 9 scenes with a Directional or Spot light: shadows2048 -0.0124 (flip_mean), shadows 256 -0.0106; stilllife-direct -0.0414, stilllife-stage -0.0282, materials-world -0.0333, lights-after -0.0041. The three scenes whose file already says `shadows=TRUE` (annotation-standard, nurbs-weights, quaternion-xyzw) change by 0.0000 to +0.0008 (native already honours the file flag, `castlescenecore.pas:2368`, `ShadowMaps` default true) except nurbs-weights 2048 -0.0048.
Best combination: castle_all (ssaa4 + shading_gouraud, chosen in-sample, ibl excluded by rule) 0.1289 / 0.1037 against native 0.1321 / 0.1045. Gouraud adds only -0.0005 on top of ssaa4 over 15 scenes and 0.0000 on every scene with PhysicalMaterial-only or textured Phong shapes; it is not a real contributor (section 5).
Combinations I rendered myself to test additivity (castle-render built from `castle_render.dpr`, same args as the harness plus levers; scored with the same `quality_metrics.py compare`; `lever_analysis/combo_metrics_raw.json`):
- ssaa4 + aniso16: identical to ssaa4 alone within 0.0001 on every scene (aniso adds nothing measurable, only 2 scenes have textures).
- ssaa4 + aniso16 + shadows2048 (shadows only where a Directional/Spot light exists; elsewhere the image equals ssaa4+aniso16): against `ref` mean flip_mean over 15 -0.0010 (core11 +0.0024), against `ref_shadows` -0.0103 (core11 -0.0103), expnorm against `ref_shadows` -0.0072. msaa4 instead of ssaa4: -0.0079 against `ref_shadows`. Effects add: against `ref`, the separately measured ssaa4 and shadows2048 deltas sum to the combined delta within 0.0006 on 8 of the 9 shadow scenes and within 0.0018 on materials-world (combined -0.0505 versus -0.0487); nurbs-weights is also additive (-0.0345 + -0.0048 = -0.0393 versus -0.0396 measured). With msaa4 in place of ssaa4 the nurbs-weights delta is only -0.0052 because MSAA does not thin the curve (section 4).

## 3. What each lever visibly does (read from the sheets and montages)

Images: `results/quality/public/sheets/*.png` (full 17-lever sheets per scene), `lever_analysis/img/shadows_montage.png` (ref, ref_shadows, native, shadows 256, shadows 2048 on four scenes), `lever_analysis/img/lights_after_sphere_zoom.png` (contrast x2 crop), `lever_analysis/img/viewer_vs_castle_render_annot.png`.

- shadows (shadow maps): adds hard-to-soft cast shadows from Directional and Spot lights only. In stilllife-direct and stilllife-stage the shadow wedge of the vase and torus on the table lands where `ref_shadows` has it, with similar darkness; 256 px gives soft blobby edges (PCF16 over a map fitted to the whole scene), 2048 gives crisp torus and vase edges, 4096 is no better than 2048 (stilllife-direct 0.0824 vs 0.0824 against `ref_shadows`). In materials-world the two spot-light shadows of the sphere and box on the floor appear with the right overall shape. Against the file-literal `ref` they are simply extra dark area, hence worse. Artefacts: a rectangular patch (one low-poly sphere facet) on the blue sphere's upper left in lights-after at 256 and a faint outline at 2048 (self-shadow, `lights_after_sphere_zoom.png`); the castle sphere shadow in lights-after sits straight under the sphere while `ref_shadows` throws it right/back (two lights, Castle shades the Directional only, point lights skipped).
- ssao: darkens by a few percent where depth differs between neighbours. Pixel luminance ratio ssao/native over non-background: mean 0.985 stilllife-direct, 0.964 materials-world, 0.985 lights-after, 1.000 on p1..p5 and repair-2-render (no effect on sparse isolated-object scenes), 0.935 village with 5th percentile 0.794 and a 15 % darker band (rows 300-340 ratio 0.846) on the flat ground: self-occlusion banding on a large plane at a grazing angle (village flip +0.0978 worse). Cause: Likely, read from `ssao.glsl:13-37` and the hard-coded depth range (section 6), not isolated.
- ssr: adds ghost reflections of the scene on diffuse floors with one fixed glossiness for every pixel (0.5, no material information): faint mirrored fountain on village's ground, garbled brown blobs under the sphere and cube in lights-after (visible in the sheet), nothing on scenes without a floor. Mean pixel ratio 0.998-1.010. By expnorm worse in 3 scenes (village +0.0127, lights-after +0.0039, stilllife-direct +0.0015), better in none beyond 0.001; by plain flip lights-after is -0.0154 better (the same brightness effect as SSAO there, not a fidelity gain).
- tonemap (aces / uncharted / hejl): global curve applied per fragment before output. Visually: aces lifts and desaturates mid-tones (village fountain washed out, annotation cube pale yellow), uncharted darkens everything strongly (it pre-multiplies by 2.0 and, when there is no gamma path, the result is displayed without gamma: village and nurbs very dark), hejl brightens and desaturates. Unlit / vertex-colour scenes (village and earth-planet have no Material, only Color) get the curve applied to display-referred colours: village +0.0988 to +0.1591 expnorm worse. The apparent win of uncharted on lights-after (-0.1203 plain) is brightness: its expnorm delta is -0.0002, i.e. it darkens an over-bright image (native exposure_scale 0.712) and does not improve it; aces and hejl are +0.0388 and +0.0276 worse there after exposure normalisation.
- shading phong: bit-identical to native on all 15 (engine default is Phong). gouraud: per-vertex lighting; changes pixels only where a classic `Material` shape exists (annotation, p2, nurbs, quaternion; PhysicalMaterial-only scenes and textured shapes unchanged); +/-0.002 flip, no visible difference in the sheets. pbr: this is OUR mapping (classic Material to PhysicalMaterial in castle_render.dpr), not an engine feature. It dulls specular: the gold cube in annotation-standard turns dull brown (expnorm +0.0884 worse), p3 +0.0498 flip worse.
- msaa4 / ssaa2 / ssaa4: smoother silhouette edges; mean SSIM 0.8527 native, 0.8561 msaa4, 0.8564 ssaa2, 0.8574 ssaa4; mean |d| over geometry 26.73 / 26.10 / 25.91 / 25.69. SSAA is our harness addition (an NxN FBO box-averaged in display space, `castle_render.dpr:937-967`), MSAA is the FBO multisample path (`castle_render.dpr:947`) because Xvfb has no multisample visual. SSAA also thins GL lines and points relative to the frame (section 4).
- aniso16: not visible in this suite. Only stilllife-direct (1 texture) and materials-world (28 textures) have textures; delta -0.0001 and -0.0008. The scenes have no large textured plane at a grazing angle, so the suite cannot resolve this lever.
- colorspace linear: identical to native on scenes whose shapes are all PhysicalMaterial (stilllife x2, lights-after, p1, p4, p5; delta 0.0000) because the default `csLinearWhenPhysicalMaterial` is already linear there. On classic-Material and vertex-colour scenes it re-encodes sRGB-authored colours a second time: village, annotation-standard and nurbs-weights wash out to light grey, annotation-standard +0.4430 flip worse. colorspace srgb: PhysicalMaterial scenes turn very dark (no gamma on PBR output): stilllife-direct +0.1846, stilllife-stage +0.2408, lights-after +0.2162; classic-Material scenes unchanged (0.0000).
- ibl (synthetic gradient sky as EnvironmentLight): brightens every surface with a flat bluish fill, flattens shading (stilllife-direct +0.1396 flip). Not a fair test: the Cycles world in these scenes is a flat near-black colour, the sky I injected is unrelated to it. See section 6 for what the engine's implementation actually does.

## 4. Where a lever "wins" for the wrong reason (do not read these as quality gains)

- nurbs-weights, ssaa4 -0.0345 (ssaa2 -0.0224, msaa4 -0.0002): native draws the NurbsCurve as a thick stair-stepped line; the add-on cannot import NurbsCurve so the reference has no curve at all. With SSAA the GL line width (pixels) is constant while the buffer is 4x larger, so after the box downscale the curve is 1/4 as thick; less curve is closer to a reference with none. MSAA does not change line width, and its delta is -0.0002. Confirmed (the three numbers), cause Likely.
- lights-after tonemap_uncharted (-0.1203) and materials-world tonemap_uncharted (-0.0447 flip, expnorm -0.0307) and materials-world shadows (-0.0408): all in scenes where native is far too bright (exposure_scale 0.712 / 0.123); anything that darkens the white floor "improves" FLIP. Confirmed (numbers), cause Likely.
- p2-point-classic: shading_gouraud -0.0021, shading_pbr +0.0131, tonemap_aces -0.0117: the reference itself disagrees with the file here (attenuation 1 0 0 versus Blender 1/d^2), so any change is noise relative to the intended image.
- quaternion-xyzw: expnorm is invalid there (exposure_scale 3.289), so its expnorm deltas (ibl -0.0361, aces -0.0247) are not usable.

## 5. Render-time cost on software GL (llvmpipe, 2 threads, shared 4 vCPUs, NOT a GPU number)

Source: `seconds.load_and_setup` and `seconds.render_and_save` in each `castle_<lever>.png.json` (GetTickCount64, 1 ms resolution). One cold frame per run: it includes shader compilation (llvmpipe JIT) and, for shadows, the update step that renders the shadow maps (counted in `load_and_setup`, so use total). Cycles reference for comparison: mean 24.3 s per scene at 256 spp on the same box.

| lever | n | mean total ms (load+render) | same-scene delta vs native, mean / median / max ms | mean render_and_save ms | mean load_and_setup ms |
|---|---|---|---|---|---|
| native | 15 | 214 | +0 / +0 / +0 | 21 | 179 |
| shadows | 9 | 295 | +49 / +51 / +131 | 54 | 222 |
| shadows2048 | 9 | 374 | +128 / +71 / +600 | 108 | 248 |
| ssao | 15 | 253 | +40 / +39 / +66 | 46 | 184 |
| ssr | 15 | 226 | +12 / +11 / +43 | 28 | 182 |
| tonemap_aces | 15 | 263 | +49 / +21 / +403 | 59 | 189 |
| tonemap_uncharted | 15 | 271 | +57 / +17 / +481 | 59 | 198 |
| tonemap_hejl | 15 | 265 | +51 / +19 / +433 | 62 | 188 |
| shading_phong | 15 | 211 | -2 / +2 / +14 | 16 | 181 |
| shading_gouraud | 15 | 221 | +7 / +5 / +54 | 25 | 182 |
| shading_pbr | 15 | 223 | +9 / -1 / +150 | 27 | 182 |
| msaa4 | 15 | 293 | +79 / +36 / +474 | 100 | 179 |
| ssaa2 | 15 | 234 | +20 / +19 / +47 | 41 | 178 |
| ssaa4 | 15 | 309 | +95 / +74 / +193 | 112 | 182 |
| aniso16 | 15 | 214 | -0 / +2 / +31 | 17 | 183 |
| colorspace_linear | 15 | 224 | +10 / +9 / +62 | 27 | 183 |
| colorspace_srgb | 15 | 231 | +17 / +0 / +302 | 38 | 181 |
| ibl | 15 | 313 | +99 / +58 / +579 | 89 | 208 |
| all | 15 | 308 | +94 / +69 / +202 | 110 | 183 |

Reading: SSAA4 costs about +95 ms (16x pixels), MSAA4 +79 ms median +36 ms, shadows +49 ms at 256 and +128 ms mean (+71 median) at 2048, SSAO +40 ms, SSR +12 ms, aniso16 and phong 0. The tone-map and colour-space maxima (+300 to +480 ms, all on materials-world with 16 shapes and 28 textures) are shader recompilation, not per-pixel cost. These numbers say little about GPU frame time: llvmpipe cost is proportional to pixels shaded, a GPU would show shadow-map and SSAA cost very differently and SSAO/SSR cost as a few full-screen passes. Likely.

## 6. How each lever is implemented in the engine (file:line) and what depends on the GL renderer

All paths are under `cge/castle_game_engine/src/`.

| lever | where | what it does | GPU behaviour |
|---|---|---|---|
| shadow maps | `scene/castleinternalshadowmaps.pas:195-300`, `scene/castlescenecore.pas:980,2368,3206`, `scene/x3d/x3dnodes_castle.inc:80-81`, `scene/castleinternalrenderer_texture.inc:2319`, `scene/glsl/source/shadow_map_common.fs:35-111`, `base/castlerenderoptions_renderoptions.inc:144` | One orthographic map per Directional light fitted to the bounding box of all shadow casters (`:262-290`); Spot lights use the projection of the light node (not read in detail); default 256 px, PCF16 default; bias is `glPolygonOffset(4.0, 4.0)` (X3D `GeneratedShadowMap.scale/bias` defaults); outside the map = lit (`shadow_map_common.fs:47-49`); no point-light shadow maps in this snapshot; no cascades | Algorithm identical. Depends on GL: polygon-offset "units" are implementation-defined (24-bit int vs 32F depth changes acne/peter-panning balance); hardware shadow samplers and PCF filtering. Suspected: bias needs re-tuning on real GPUs. Resolution falls with scene size (one map per light over the whole bbox), same on GPU |
| ssao | `scene/castleviewport.pas:442,1446-1466,3069-3170`, `scene/glsl/source/ssao.glsl:13-90` | Screen effect on the final colour (after tone map and gamma, also dims emissive and specular), 6 samples x 3 rings, depth-compare constants fixed (aoMultiplier 100, aoCap 0.8, aorange 60), final `ao*0.8+0.2`; `near` and `far` uniforms are HARD-CODED 1.0 and 1000.0 (`:1465-1466`, with a TODO saying the real values made it "much less noticeable") | Same math on GPU. Depth-buffer precision and the `sin()` noise hash (`ssao.glsl:20-22`) are GL-dependent. Result depends on scene scale because of the hard-coded range (Suspected: actual camera near/far were not measured here) |
| ssr | `scene/castleviewport.pas:443-444,1473-1494,3069-3170`, `scene/glsl/source/ssr.glsl:12-44` | Screen-space ray march, 16 steps of world-unit length, normals reconstructed from depth, one global glossiness 0.5 (`DefaultScreenSpaceReflectionsSurfaceGlossiness`), `near` 0.1 / `far` 1000 hard-coded (`:1483-1484`), fade 20..300 world units | Same math on GPU; scene-scale dependent (world-unit step) |
| tone mapping | `base/castlerenderoptions_globals.inc:46-63,635`, `scene/castlerendererinternalshader.pas:1862,1915,2159-2182,2245`, `scene/glsl/source/tone_mapping.fs:57-131`, `scene/glsl/source/main_shading_phong.fs:79-90`, `main_shading_gouraud.fs:25-31` | Global variable `ToneMapping` (default tmNone), baked into every shader as a define, applied per fragment on the lit colour before fog; gamma is `pow(c, 1/2.2)`, not the sRGB piecewise curve. Per-scene X3D `Environment.tonemapping` is declared but nothing outside the generated node code reads it (Suspected: global only) | Same on GPU (pure shader math, fp precision only) |
| shading mode | `base/castlerenderoptions_renderoptions.inc:126,316`, `scene/castlerendererinternalshader.pas:1342-1350,1647-1678`, `scene/castleinternalrenderer_surfacetextures.inc:36-70`, `scene/glsl/source/lighting_model_physical/add_light.glsl:134-165` | `PhongShading` default true: per-fragment lighting; false: per-vertex (`main_shading_gouraud.fs`, `shading_gouraud.vs`); shapes with a normal map or other surface textures force Phong anyway; PhysicalMaterial uses a glTF-Sample-Viewer style microfacet model (specularReflection, visibilityOcclusion, microfacetDistribution) | Same on GPU |
| colour space | `base/castlerenderoptions_globals.inc:65-110,574,612`, `scene/castleinternalrenderer_meshrenderer.inc:1088-1090`, `tone_mapping.fs:23-55` | Global; default `csLinearWhenPhysicalMaterial`: gamma only for PhysicalMaterial shapes; linear = gamma on everything | Same on GPU |
| IBL (EnvironmentLight) | `scene/castlescene.pas:25-26`, `scene/castlerendererinternalshader_light.inc:207,271-282`, `scene/glsl/source/lighting_model_physical/add_light.glsl:54-57,90,159-160` (phong model `:85,141,159`) | The engine's own comment says the implementation is not finished and `CASTLE_EXPERIMENTAL_ENVIRONMENT_LIGHT` is off by default. In the shader the "light direction" for an environment light is the eye-space normal (`light_dir = normal_eye`, `:90`) and the cube map is sampled once with it (`textureCube(diffuseTexture, light_dir)`), scaling the analytic diffuse and specular terms: no hemisphere integration, no mip/roughness lookup, no BRDF table, no reflection vector, and the cube lookup rotates with the camera. Confirmed (read) | Same on GPU. Not usable as image-based lighting in this snapshot |
| anti-aliasing | `window/castlewindow.pas:409-421,3128-3146`; harness `castle_render.dpr:927-967` | Engine: `TCastleWindow.AntiAliasing` (default aaNone) sets window `MultiSampling` 2/4/8/16, a multisample visual; no FXAA or SSAA in the engine. Harness: FBO multisample (msaa) and own SSAA | GL-dependent: needs a multisample visual or FBO samples (hardware on GPU); under Xvfb + llvmpipe `castle-model-viewer --anti-alias N` changes nothing (`castle-gaps.md` row 7, identical PNG hashes for levels 0-6) |
| anisotropic filtering | `scene/castleinternalrenderer_texture.inc:579,593`, `scene/x3d/auto_generated_node_helpers/x3dnodes_textureproperties.inc:236` | Per texture via X3D `TextureProperties.anisotropicDegree`, default 1.0 (off) | GL-dependent: sampler implementation and quality differ by vendor; llvmpipe reports max 16 |

Which levers will behave the same on a real GPU: tone mapping, colour space, shading mode, PBR lighting, EnvironmentLight sampling, and the SSAO/SSR algorithms are shader math and will produce the same images up to fp precision (Likely, read in source, not run on a GPU). Which depend on the GL renderer: MSAA (and the whole `--anti-alias` path), anisotropic filtering, the shadow bias (polygon offset units), hardware shadow-sampler PCF, depth precision for SSAO/SSR, and all timings. Nothing here was run on a GPU.

## 7. Defaults in castle-model-viewer 5.3.0 (are users getting these?)

castle-model-viewer 5.3.0 is built against CGE 7.0-alpha.3.snapshot with FPC 3.2.2 (its log `~/.config/castle-model-viewer/castle-model-viewer.log`). Its source is not in the bundle (`tools/` has no castle-model-viewer), so the evidence is the engine defaults (source file:line), `--help` and the strings in the binary.

| setting | default users get | evidence |
|---|---|---|
| shading | Phong per fragment | `castlerenderoptions_renderoptions.inc:126`; viewer menu item "Phong Shading on Everything" present in binary strings |
| tone mapping | none | `castlerenderoptions_globals.inc:635`; menu "Tone Mapping" present |
| colour space | linear only for PBR materials | `:574`; binary string "Linear On Physical Materials (Gamma Correction = when PBR)" |
| shadow maps | ON, but only for lights/shapes that ask (`shadows=TRUE`, `receiveShadows`), size 256, PCF16 | `castlescenecore.pas:980,2368,3206`; menu "Shadow Maps / Enable / Set Default Shadow Map Size" |
| shadow volumes | stencil requested by default (`DefaultStencilBits = 8`), rendering is opt-in per light (`TCastleLight.Shadows`) and a viewer menu item | `castlerenderoptions_globals.inc:585` (stencil bits), `scene/castlescene_punctuallight.inc:52` (`TCastleLight.Shadows` default false); not tested here |
| SSAO / SSR | off; no menu string for either in the 5.3.0 binary (Likely not exposed) | `castleviewport.pas:442-443`; `strings` found only "Occlusion Sort / Use Occlusion Culling" |
| anti-aliasing | none (`--anti-alias AMOUNT`, "Exact 0 means no anti-aliasing, this is the default") | `--help`; `castlewindow.pas:421` |
| anisotropy | off (1.0) | `x3dnodes_textureproperties.inc:236` |
| IBL | none | EnvironmentLight unfinished, section 6 |
| bump mapping | basic | `castlerenderoptions_renderoptions.inc:124` |

So a default viewer user gets Phong, no tone mapping, no AA, no AO/SSR/IBL, and shadows only when the file asks, at the lowest quality settings of those (256 px map). Pitfall found in section 8: the harness's own note and my re-run show the engine needs an Update step before a still render or shadow maps are never generated.

## 8. Verification runs (all on public scenes)

All in `lever_analysis/verify/` with castle-render, LP_NUM_THREADS=2, xvfb-run.
- Determinism: a rerun of `--shadows` on stilllife-direct is bit-identical in metrics to the harness image (flip 0.1266 both).
- Shadow sampling and map size on stilllife-direct against `ref_shadows` (flip_mean): native 0.1238, 256 PCF16 0.0854, 256 simple 0.0834, 256 VSM 0.0844, 2048 0.0824, 4096 0.0824. Against the file-literal `ref`: native 0.0842, 256 0.1266, simple 0.1273, VSM 0.1261, 4096 0.1283. PCF16 (the default) is not better than simple at this size (differences 0.001-0.002); 4096 adds nothing over 2048. Confirmed.
- `--shadows --no-update` (skip the update step): the picture is dark (flip 0.2942 against `ref`, mean abs 26.9 versus 7.98), confirming that without `Container.EventUpdate` the generated shadow maps are not produced (`castle_render.dpr:901-908`). `castle-model-viewer --screenshot` on annotation-standard (which has `shadows=TRUE`): the cube is dull, the disc dark and there is no visible cast shadow, unlike castle-render native (`img/viewer_vs_castle_render_annot.png`). Consistent with the same missing update step, but the viewer frame size (1024x819), camera and headlight differ, so this is Likely, not isolated.

## 9. Three levers worth turning on by default in our pipeline, and pitfalls

1. Anti-aliasing: 4x MSAA in a real GPU window (`TCastleWindow.AntiAliasing`) for interactive/rendering legs, 2x-4x SSAA for offline conversion renders. The only lever family non-negative on most scenes (SSIM 0.8527 to 0.8574 for ssaa4, |d| geometry 26.73 to 25.69; FLIP -0.0003 on core11, below noise). Cost on llvmpipe: +95 ms ssaa4, +79 ms msaa4. Pitfalls: SSAA thins GL lines/points (nurbs-weights curve) so line-based geometry changes look; MSAA does not antialias shader aliasing or the SSAO/SSR passes; a multisample visual is not available under Xvfb, so test MSAA on a GPU. The measurement here cannot show a visible AA gain in FLIP terms because the reference is path traced with its own pixel filter.
2. Shadow maps at 2048 on Directional and Spot lights, when the scene intends shadows (honour `shadows=TRUE`; the engine already does) or when the goal is the physically plausible image (against shadow-enabled Cycles: -0.0124 mean flip over 9 scenes, -0.0414 on stilllife-direct). 4096 adds nothing at this scale. Do not force it on files that say nothing if the goal is fidelity to the file: against `ref` it is +0.0031 mean worse and +0.0425/0.0378 worse on the stilllife scenes. Pitfalls: point lights get no shadow (6 of 15 scenes cannot be shadowed at all, and 4 more - lights-after, annotation-standard, nurbs-weights, quaternion-xyzw - have point lights that stay unshadowed), acne/self-shadow facet patch on low-poly spheres (lights-after), one map per light over the whole bbox so resolution falls with scene size, `glPolygonOffset(4,4)` bias is GL-dependent, soft shadow-edge width does not match Cycles' ideal point light, and a still render must run the update step (without it shadows come out black).
3. Anisotropic filtering 16x (`TextureProperties.anisotropicDegree`, also settable on every texture node as the harness does): zero measured cost, delta -0.0001 to -0.0008 on the two textured scenes. Grade of the benefit is Suspected: this suite has no large textured plane at a grazing angle, so it cannot resolve the lever, and anisotropy quality is GL-dependent.

Levers to leave off, with the evidence: SSAO (worse in 5 scenes, village +0.0978; banding on large planes; hard-coded depth range), SSR (worse, ghost reflections, one glossiness for everything), tone mapping of any kind (+0.013 to +0.018 expnorm mean, global and applied to unlit colours too), colour space linear or srgb (default is right for PhysicalMaterial-only scenes; linear washes out classic-Material scenes, srgb darkens PBR scenes), the engine EnvironmentLight (unfinished, see section 6), gouraud (no real effect), our pbr mapping (dulls speculars). Keep the engine defaults for Phong shading, colour space and no tone mapping.
The brightest unaddressed item is not a lever: exposure / light units in materials-world, lights-after, p1, p4 (section 0).

## 10. Caveats

- 15 scenes, 4 with reference semantics that distort the comparison (annotation-standard, nurbs-weights, quaternion-xyzw, p2-point-classic) and 2 saturated or over-exposed (materials-world, lights-after); core11/core10 subsets are post hoc.
- `castle_all` chose its levers on the same scenes that score it. My combo test (`run_combo.py`) fixes the combination before measuring but uses the same 15 scenes, so it is also in-sample.
- Plain FLIP and expnorm disagree in sign for many lever/scene pairs; I report both and flag where exposure_scale is far from 1.
- IBL used one synthetic gradient cube map that does not match the Cycles world; the IBL lever number says nothing about proper IBL.
- SSAA and MSAA are harness constructs (FBO), not the engine's window anti-aliasing path.
- Shadow volumes, bump-mapping modes, `--min-filter`, `--max-lights` and the exposure effect are exposed by castle-render but were not part of the public run; I tested shadow sampling and map size on one scene only.
- Timings: single cold frame, 1 ms resolution, shared vCPUs, llvmpipe JIT included; no GPU number exists in this data.
- Source claims about hard-coded SSAO/SSR near/far and the EnvironmentLight direction are read from source (Confirmed as text); their effect on images was not isolated with an experiment. Actual camera near/far in the harness were not measured.

## 11. Independent re-score

A second reader re-scored 273 lever pairs, 75 core pairs, 60 pairs against X_ITE and 60 re-seeded pairs with their own FLIP and
exposure-normalisation code: the largest difference to `results.json` is 0. Three wording fixes came out of it and are applied above:
"every non-negative lever is below the noise floor" is false (the harmful levers exceed it; only the improving ones are inside it),
the p2 cause is the classic-Material display-space lighting (`docs/quality-leg.md` section 3), and plain F, not E, is the headline metric.
