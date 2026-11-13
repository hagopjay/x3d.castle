#!/usr/bin/env python3
"""Castle Game Engine (7.0-alpha.3 snapshot, 12 Nov 2026) cannot decode WebP textures
("Unrecognized image MIME type", the texture is dropped, the shape renders untextured).
This pre-pass writes a COPY of an X3D file in OUTDIR with every *.webp texture URL replaced by an absolute
file:// URL of a PNG converted next to it. The original scene and its images are never touched.

    webp_prepass.py in.x3d OUTDIR      -> prints the path of the patched copy (or in.x3d unchanged if no .webp is used)
"""
import sys, os, re, hashlib
from PIL import Image

def main():
    src, out = sys.argv[1], sys.argv[2]
    text = open(src, encoding="utf-8").read()
    base = os.path.dirname(os.path.abspath(src))
    hits = sorted(set(re.findall(r"[A-Za-z0-9_@%+~./\\:-]+\.webp", text, flags=re.I)))
    if not hits:
        print(src); return
    os.makedirs(out, exist_ok=True); png_dir = os.path.join(out, "png"); os.makedirs(png_dir, exist_ok=True)
    n = 0
    for h in hits:
        p = h[7:] if h.startswith("file://") else h
        p = p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))
        if not os.path.exists(p):
            continue
        dst = os.path.join(png_dir, hashlib.sha1(p.encode()).hexdigest()[:16] + ".png")
        if not os.path.exists(dst):
            Image.open(p).convert("RGBA").save(dst)
        text = text.replace(h, "file://" + dst); n += 1
    dst_x3d = os.path.join(out, os.path.basename(src))
    open(dst_x3d, "w", encoding="utf-8").write(text)
    print(dst_x3d)
    print(f"webp_prepass: {n} WebP texture(s) converted to PNG for {os.path.basename(src)}", file=sys.stderr)

if __name__ == "__main__":
    main()
