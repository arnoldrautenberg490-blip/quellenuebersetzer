"""Testhilfen. Alle Testdokumente werden hier synthetisch erzeugt – es gibt keine echten Quellen im Projekt."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"

# Erfundener Beispieltext im Stil einer Verwaltungsakte des 18. Jahrhunderts.
SAMPLE_PL = [
    "Akta miasta Krakowa z roku 1785.",
    "Starosta grodowy zatwierdził przywilej dla cechu młynarzy",
    "i nakazał, aby każdy młyn płacił dwa złote rocznie.",
    "Świadkowie: Jan Kowalski, Józef Nowak i Wojciech Zieliński.",
]

TABLE_PL = [
    ["Miejscowość", "Młyny", "Złote"],
    ["Bronowice", "3", "6"],
    ["Krowodrza", "2", "4"],
    ["Razem", "5", "10"],
]


def font(name: str = "times.ttf", size: int = 40) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def make_text_page(path: Path, lines=SAMPLE_PL, with_table: bool = True, size=(2480, 3508)) -> Path:
    img = Image.new("L", size, 250)
    d = ImageDraw.Draw(img)
    f = font(size=48)
    y = 250
    d.text((250, y), "PRZYWILEJ CECHOWY", font=font(size=80), fill=20)
    y += 200
    for line in lines:
        d.text((250, y), line, font=f, fill=25)
        y += 80
    if with_table:
        y += 120
        x0, col_w, row_h = 250, [700, 400, 400], 100
        n_rows = len(TABLE_PL)
        total_w = sum(col_w)
        for r in range(n_rows + 1):
            d.line([(x0, y + r * row_h), (x0 + total_w, y + r * row_h)], fill=0, width=4)
        xs = [x0]
        for w in col_w:
            xs.append(xs[-1] + w)
        for x in xs:
            d.line([(x, y), (x, y + n_rows * row_h)], fill=0, width=4)
        for r, row in enumerate(TABLE_PL):
            for c, val in enumerate(row):
                d.text((xs[c] + 25, y + r * row_h + 25), val, font=f, fill=25)
    img.save(path)
    return path


def make_handwriting_like(path: Path, n_lines: int = 6) -> Path:
    img = Image.new("L", (2000, 1400), 245)
    d = ImageDraw.Draw(img)
    f = font("georgiai.ttf" if (FONTS / "georgiai.ttf").exists() else "georgia.ttf", 52)
    for i in range(n_lines):
        d.text((150, 120 + i * 190), SAMPLE_PL[i % len(SAMPLE_PL)], font=f, fill=30)
    img.save(path)
    return path


@pytest.fixture
def tess_root() -> Path | None:
    """Datenwurzel mit portabler Tesseract-Kopie (per Umgebungsvariable QUE_TEST_ROOT)."""
    root = os.environ.get("QUE_TEST_ROOT")
    if not root or not (Path(root) / "runtime" / "tesseract" / "tesseract.exe").exists():
        pytest.skip("Keine Test-Tesseract-Installation (QUE_TEST_ROOT) vorhanden")
    return Path(root)


def make_mixed_page(path: Path) -> Path:
    """Erfundene Mischseite: Kopfzeile, Titel, zwei Spalten, Abbildung mit Unterschrift, Tabelle ohne Linien,
    Randnotiz, Fußnote, Seitenzahl."""
    W, H = 2480, 3508
    img = Image.new("L", (W, H), 246)
    d = ImageDraw.Draw(img)
    small, body, title = font(size=34), font(size=42), font(size=78)
    d.text((300, 160), "Kronika miasta Krakowa — tom II", font=small, fill=60)
    d.text((300, 300), "O MŁYNACH I CECHACH", font=title, fill=20)
    col_text = [
        "Starosta grodowy zatwierdził", "przywilej dla cechu młynarzy", "i nakazał, aby każdy młyn",
        "płacił dwa złote rocznie.", "Cech miał prawo wybierać", "starszych i sądzić spory",
        "między mistrzami a czeladzią.",
    ]
    for i, line in enumerate(col_text):
        d.text((300, 520 + i * 62), line, font=body, fill=25)
        d.text((1320, 520 + i * 62), line.replace("młyn", "dom"), font=body, fill=25)
    # Abbildung (Kupferstich-Imitat) mit Unterschrift
    d.rectangle([300, 1060, 1180, 1700], outline=40, width=6)
    for k in range(0, 600, 18):
        d.line([(320 + k, 1080), (320 + k // 2, 1680)], fill=90, width=3)
    d.ellipse([600, 1200, 900, 1500], outline=30, width=8)
    d.text((300, 1730), "Ryc. 1. Młyn wodny pod Krakowem.", font=small, fill=40)
    # Tabelle ohne Linien
    rows = [("Miejscowość", "Młyny", "Złote"), ("Bronowice", "3", "6"), ("Krowodrza", "2", "4"), ("Razem", "5", "10")]
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            d.text((1320 + c * 330, 1080 + r * 70), val, font=body, fill=25)
    # Randnotiz rechts außen
    d.text((2180, 560), "Por.", font=small, fill=50)
    d.text((2180, 600), "rok 1612", font=small, fill=50)
    # Fließtext unten, Fußnote, Seitenzahl
    for i, line in enumerate(SAMPLE_PL):
        d.text((300, 1950 + i * 62), line, font=body, fill=25)
    d.line([(300, 3180), (900, 3180)], fill=60, width=2)
    d.text((300, 3200), "¹ Według akt grodzkich krakowskich.", font=small, fill=50)
    d.text((1220, 3330), "42", font=small, fill=50)
    img.save(path)
    return path
