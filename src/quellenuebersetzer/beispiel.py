"""Eingebaute, erfundene Beispielquelle für den Leistungstest (keine echten Dokumente)."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TEXT = [
    "Akta miasta Krakowa z roku 1785.",
    "Starosta grodowy zatwierdził przywilej dla cechu młynarzy",
    "i nakazał, aby każdy młyn płacił dwa złote rocznie.",
    "Świadkowie: Jan Kowalski, Józef Nowak i Wojciech Zieliński.",
]
TABLE = [["Miejscowość", "Młyny", "Złote"], ["Bronowice", "3", "6"], ["Krowodrza", "2", "4"], ["Razem", "5", "10"]]
# Erwarteter Text (für die Messung der Lesegenauigkeit)
EXPECTED = " ".join(["PRZYWILEJ CECHOWY", *TEXT, *[c for row in TABLE for c in row]])


def _font(size: int) -> ImageFont.ImageFont:
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("times.ttf", "georgia.ttf", "arial.ttf"):
        if (fonts / name).exists():
            return ImageFont.truetype(str(fonts / name), size)
    return ImageFont.load_default(size)


def make_page(path: Path) -> Path:
    img = Image.new("L", (2480, 3508), 248)
    d = ImageDraw.Draw(img)
    f = _font(48)
    d.text((250, 250), "PRZYWILEJ CECHOWY", font=_font(80), fill=20)
    y = 450
    for line in TEXT:
        d.text((250, y), line, font=f, fill=25)
        y += 80
    y += 120
    col_w, row_h, x0 = [700, 400, 400], 100, 250
    xs = [x0]
    for w in col_w:
        xs.append(xs[-1] + w)
    for r in range(len(TABLE) + 1):
        d.line([(x0, y + r * row_h), (xs[-1], y + r * row_h)], fill=0, width=4)
    for x in xs:
        d.line([(x, y), (x, y + len(TABLE) * row_h)], fill=0, width=4)
    for r, row in enumerate(TABLE):
        for c, val in enumerate(row):
            d.text((xs[c] + 25, y + r * row_h + 25), val, font=f, fill=25)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path
