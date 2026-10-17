"""Schriftmerkmale eines Textbereichs am Scan messen: Farbe, Strichstärke (fett), Neigung (kursiv), Sperrsatz.

So bleiben z. B. rote Rubriken, fette oder gesperrte Zwischenüberschriften in der Übersetzung erhalten –
auch wenn die Seitenaufbau-Erkennung einen solchen Bereich nur als „Absatz“ einordnet.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Style:
    color: str = ""  # Hex-Farbe der Schrift, leer = übliche dunkle Schrift
    stroke: float = 0.0  # Strichstärke im Verhältnis zur Zeilenhöhe (für den Vergleich innerhalb der Seite)
    italic: bool = False
    spaced: bool = False  # Sperrsatz


def _ink(binary_crop: np.ndarray) -> np.ndarray:
    return (binary_crop < 128).astype(np.uint8)


def ink_color(color_crop: np.ndarray, ink: np.ndarray) -> str:
    """Farbe der Schrift, wenn sie deutlich farbig ist (z. B. rote Rubrik), sonst leer."""
    if ink.sum() < 30:
        return ""
    pixels = color_crop[ink.astype(bool)]
    hsv = cv2.cvtColor(pixels.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3)
    sat, val = np.median(hsv[:, 1]), np.median(hsv[:, 2])
    b, g, r = (int(v) for v in np.median(pixels, axis=0))
    if val > 170 and sat < 70:
        return f"#{r:02x}{g:02x}{b:02x}"  # helle Schrift (auf dunklem Grund)
    if sat < 70 or val < 50:
        return ""  # schwarz, grau oder braun-schwarz: normale Schrift
    # etwas abdunkeln: Druckfarbe wirkt auf dem Scan meist heller als im Satz
    r, g, b = (int(c * 0.85) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def stroke_ratio(ink: np.ndarray, line_px: float) -> float:
    """Mittlere Strichbreite (2 × Fläche / Umriss) im Verhältnis zur Zeilenhöhe – stufenlos, auch bei dünner Schrift."""
    if ink.sum() < 30 or line_px <= 0:
        return 0.0
    contours, _ = cv2.findContours(ink.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    perimeter = sum(cv2.arcLength(c, True) for c in contours)
    if perimeter <= 0:
        return 0.0
    return float(2 * ink.astype(bool).sum() / perimeter) / line_px


def slant(ink: np.ndarray) -> float:
    """Neigung der Schrift (Scherung, bei der die senkrechten Striche am schärfsten stehen)."""
    if ink.sum() < 60:
        return 0.0
    h, w = ink.shape
    best, best_score = 0.0, -1.0
    for s in np.arange(-0.4, 0.41, 0.05):
        m = np.float32([[1, s, -s * h / 2], [0, 1, 0]])
        sheared = cv2.warpAffine(ink, m, (w, h), flags=cv2.INTER_NEAREST)
        score = float(np.var(sheared.sum(axis=0)))
        if score > best_score:
            best, best_score = float(s), score
    return best


def letter_spacing(ink: np.ndarray, line_px: float) -> float:
    """Typischer Abstand zwischen benachbarten Buchstaben im Verhältnis zur Zeilenhöhe."""
    n, _labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    boxes = [stats[i] for i in range(1, n) if stats[i, 3] > line_px * 0.25 and stats[i, 2] < line_px * 2]
    if len(boxes) < 6 or line_px <= 0:
        return 0.0
    boxes.sort(key=lambda b: (b[1] // max(1, int(line_px)), b[0]))
    gaps = []
    for a, b in zip(boxes, boxes[1:]):
        same_line = abs(int(a[1]) - int(b[1])) < line_px * 0.6
        gap = int(b[0]) - int(a[0] + a[2])
        if same_line and 0 <= gap < line_px * 1.2:
            gaps.append(gap)
    return statistics.median(gaps) / line_px if len(gaps) >= 4 else 0.0


def measure(color_crop: np.ndarray, binary_crop: np.ndarray, line_px: float) -> Style:
    ink = _ink(binary_crop)
    return Style(
        color=ink_color(color_crop, ink),
        stroke=stroke_ratio(ink, line_px),
        italic=slant(ink) <= -0.12 or slant(ink) >= 0.12,
        spaced=letter_spacing(ink, line_px) > 0.22,
    )


def bold_flags(strokes: list[float], factor: float = 1.12) -> list[bool]:
    """Fett = deutlich kräftigere Striche als der übliche Text derselben Seite."""
    base = [s for s in strokes if s > 0]
    if len(base) < 2:
        return [False] * len(strokes)
    median = statistics.median(base)
    return [s > median * factor for s in strokes]
