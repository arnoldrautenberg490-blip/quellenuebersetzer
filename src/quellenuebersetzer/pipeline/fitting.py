"""Text in seinen Originalbereich einpassen – gemeinsam für PDF und Word berechnet.

Reihenfolge (das Schriftbild soll so lange wie möglich dem Original entsprechen):
  1. Bereich in freien Raum darunter wachsen lassen (bis zum nächsten Block bzw. Seitenrand)
  2. Zeilenabstand verringern (1,15 → 1,05)
  3. Laufweite minimal verringern (bis −2 %)
  4. Schrift verkleinern (bis 60 %)
  5. Notfalls kürzen mit „[…]“ – der vollständige Text steht dann im Anhang

Gemessen wird mit den echten Schriftmaßen von Times New Roman (PDF und Word nutzen dieselbe Schrift).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from quellenuebersetzer.pipeline import markup

FONT_FAMILY = "Times New Roman"
LEADING_NORMAL, LEADING_MIN = 1.15, 1.05  # unter 1,05 schneidet Word Akzente über Versalien ab
TRACKING_MIN = -0.02  # em
MIN_SCALE = 0.6
WIDTH_SAFETY = 0.97  # kleine Reserve für Unterschiede im Umbruch zwischen den Programmen


@dataclass
class Fit:
    size: float  # Schriftgröße in pt
    leading: float  # Zeilenabstand als Vielfaches der Schriftgröße
    tracking: float  # Laufweite in em
    text_md: str  # ggf. gekürzter Text (Markdown mit Markierungen)
    truncated: bool
    box: tuple[float, float, float, float]  # x, y, Breite, Höhe in pt (ggf. vergrößert)


@lru_cache(maxsize=64)
def _font(bold: bool, italic: bool, size_tenths: int) -> ImageFont.FreeTypeFont:
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    name = {(False, False): "times.ttf", (True, False): "timesbd.ttf", (False, True): "timesi.ttf",
            (True, True): "timesbi.ttf"}[(bold, italic)]
    for candidate in (name, "times.ttf", "georgia.ttf"):
        if (fonts / candidate).exists():
            return ImageFont.truetype(str(fonts / candidate), max(1, size_tenths) / 10)
    return ImageFont.load_default(max(1, size_tenths) / 10)


def lines_needed(words: list[str], width: float, size: float, bold: bool, italic: bool, tracking: float) -> int:
    font = _font(bold, italic, int(size * 10))
    extra = tracking * size  # pro Zeichen
    space = font.getlength(" ") + extra
    lines, current = 1, 0.0
    for w in words:
        wl = font.getlength(w) + extra * len(w)
        if current and current + space + wl > width * WIDTH_SAFETY:
            lines += 1
            current = wl
        else:
            current += (space if current else 0) + wl
    return lines


def _units(md: str) -> list[str]:
    """Markdown in Einheiten zerlegen, die beim Kürzen nicht zerrissen werden (Markierungen bleiben ganz)."""
    units, pos = [], 0
    for start, end, _m in markup.find_marks(md):
        units.extend(md[pos:start].split())
        units.append(md[start:end])
        pos = end
    units.extend(md[pos:].split())
    return units


def _plain_words(units: list[str]) -> list[str]:
    return [w for u in units for w in markup.unescape_md(markup.strip_marks(u)).split()]


def fit_text(md: str, box: tuple[float, float, float, float], base_size: float, bold: bool = False,
             italic: bool = False, spaced: bool = False) -> Fit:
    x, y, w, h = box
    units = _units(md)
    words = _plain_words(units) + ["¹"] * len(markup.find_marks(md))  # Platz für Anmerkungsziffern
    track0 = 0.12 if spaced else 0.0

    def fits(size: float, leading: float, tracking: float, ws: list[str]) -> bool:
        return lines_needed(ws, w, size, bold, italic, tracking) * size * leading <= h

    # 2.–4.: Zeilenabstand, Laufweite, Schriftgröße – in dieser Reihenfolge
    size = base_size
    while size >= base_size * MIN_SCALE - 1e-6:
        for leading in (LEADING_NORMAL, 1.1, LEADING_MIN):
            for tracking in (track0, track0 - 0.01, track0 + TRACKING_MIN):
                if fits(size, leading, tracking, words):
                    return Fit(size, leading, tracking, md, False, box)
        size *= 0.95
    # 5.: kürzen – so viele Einheiten wie bei kleinster Einstellung passen
    size, leading, tracking = base_size * MIN_SCALE, LEADING_MIN, track0 + TRACKING_MIN
    lo, hi = 0, len(units)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(size, leading, tracking, _plain_words(units[:mid]) + ["[…]"]):
            lo = mid
        else:
            hi = mid - 1
    shortened = " ".join(units[:lo]) + " \\[…\\]"
    return Fit(size, leading, tracking, shortened, True, box)


def expand_boxes(regions, page_h_px: float, margin_px: float = 0) -> dict[str, tuple[int, int, int, int]]:
    """Textbereiche nach unten in freien Raum wachsen lassen – bis zum nächsten Block darunter.

    Gibt neue Rahmen (Pixel) zurück; Abbildungen und Tabellen bleiben unverändert.
    """
    boxes = {r.id: r.box for r in regions}
    out = {}
    for r in regions:
        x0, y0, x1, y1 = r.box
        if not r.is_text:
            out[r.id] = r.box
            continue
        limit = page_h_px - margin_px
        for o in regions:
            if o.id == r.id:
                continue
            ox0, oy0, ox1, oy1 = boxes[o.id]
            if oy0 >= y1 - 2 and min(x1, ox1) > max(x0, ox0):  # darunter und waagrecht überlappend
                limit = min(limit, oy0)
        gap = max(2, (y1 - y0) * 0.02)
        new_y1 = max(y1, limit - gap)
        # nicht übermäßig wachsen: höchstens um die doppelte Höhe (sonst wirkt die Seite leer/verrutscht)
        out[r.id] = (x0, y0, x1, int(min(new_y1, y1 + 2 * (y1 - y0))))
    return out


def strip_trailing_note(md: str) -> str:
    return re.sub(r"\s*\\\[…\\\]$", "", md)
