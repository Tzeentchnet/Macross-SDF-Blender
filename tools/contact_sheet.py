"""Combine preview PNGs into one labelled contact sheet (needs Pillow).

    python tools/contact_sheet.py OUT.png img1.png img2.png ... [--cols 4] [--size 384]
"""

import argparse
import os

from PIL import Image, ImageDraw


def main():
    p = argparse.ArgumentParser()
    p.add_argument("out")
    p.add_argument("images", nargs="+")
    p.add_argument("--cols", type=int, default=4)
    p.add_argument("--size", type=int, default=384)
    a = p.parse_args()
    n = len(a.images)
    cols = min(a.cols, n)
    rows = (n + cols - 1) // cols
    s = a.size
    sheet = Image.new("RGB", (cols * s, rows * (s + 18)), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    for i, path in enumerate(a.images):
        im = Image.open(path).convert("RGB")
        im.thumbnail((s, s))
        x, y = (i % cols) * s, (i // cols) * (s + 18)
        sheet.paste(im, (x, y + 18))
        d.text((x + 4, y + 3), os.path.basename(path)[-60:], fill=(230, 230, 230))
    sheet.save(a.out)


if __name__ == "__main__":
    main()
