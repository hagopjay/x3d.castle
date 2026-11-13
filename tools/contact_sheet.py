#!/usr/bin/env python3
"""Contact sheets of the screens in a castle_leg.py results folder.

    python3 contact_sheet.py results/matrix.json results/sheets --cols 5 --rows 4 --cell 256

Each cell: the 512 px render shrunk to --cell, the scene's short name, the validate verdict and the render seconds."""
import argparse, json, os
from PIL import Image, ImageDraw, ImageFont


def font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def short(key):
    k = key.replace("docs__demos__", "")
    k = k.replace("__v1__", "/").replace("__v2__", "/").replace("__scenes__", "/").replace("__data__", "/").replace("__", "/")
    return k


def main():
    p = argparse.ArgumentParser()
    p.add_argument("matrix"); p.add_argument("out")
    p.add_argument("--cols", type=int, default=5); p.add_argument("--rows", type=int, default=4); p.add_argument("--cell", type=int, default=256)
    a = p.parse_args()
    m = json.load(open(a.matrix)); base = os.path.dirname(os.path.abspath(a.matrix)); os.makedirs(a.out, exist_ok=True)
    rows = m["rows"]; per = a.cols * a.rows; f = font(11)
    title = f"Castle {m['meta']['tool'][0]} | {m['meta']['hardware']} | {m['meta']['size']} px"
    for si in range(0, len(rows), per):
        chunk = rows[si:si + per]
        sheet = Image.new("RGB", (a.cols * a.cell, 22 + a.rows * (a.cell + 30)), (18, 18, 22))
        d = ImageDraw.Draw(sheet); d.text((6, 4), title, fill=(200, 200, 210), font=f)
        for i, r in enumerate(chunk):
            x, y = (i % a.cols) * a.cell, 22 + (i // a.cols) * (a.cell + 30)
            if r["render"]["png"]:
                im = Image.open(os.path.join(base, r["render"]["png"])).convert("RGB").resize((a.cell, a.cell), Image.LANCZOS)
                sheet.paste(im, (x, y))
            col = {"clean": (120, 220, 140), "warnings": (240, 200, 90)}.get(r["validate"]["verdict"], (240, 110, 110))
            d.text((x + 3, y + a.cell + 2), short(r["key"])[-(a.cell // 7):], fill=(225, 225, 230), font=f)
            d.text((x + 3, y + a.cell + 15), f"validate:{r['validate']['verdict']}  {r['render']['seconds']}s", fill=col, font=f)
        out = os.path.join(a.out, f"sheet-{si // per + 1:02d}.png"); sheet.save(out); print(out, len(chunk))


if __name__ == "__main__":
    main()
