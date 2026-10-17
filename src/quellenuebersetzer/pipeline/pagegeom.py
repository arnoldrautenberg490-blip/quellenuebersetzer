"""Seitengeometrie für Archivscans: Seite finden, perspektivisch entzerren, Wölbung glätten, Format vereinheitlichen.

1. Papierfläche vom (dunkleren) Scan-Hintergrund trennen und per Perspektivtransformation auf ein Rechteck ziehen
   (behebt Schiefe und Trapezverzerrung).
2. Restliche Schräglage ausgleichen.
3. Wölbung (gebogene Zeilen, typisch zum Bundsteg hin): Aus dem Verlauf der Textzeilen wird ein senkrechtes
   Verschiebungsfeld geschätzt und die Seite so umgerechnet, dass die Zeilen wieder gerade laufen.
4. Einheitliches Format: Alle Seiten eines Dokuments werden auf ein gemeinsames Normalformat gebracht
   (Median der Seitengrößen), damit die Übersetzung durchgehend dieselbe Seitengröße hat.

Alles mit OpenCV, lokal, ohne Zusatzmodelle. Bei unsicherer Erkennung bleibt das Bild unverändert.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import cv2
import numpy as np

from quellenuebersetzer.pipeline.preprocess import estimate_skew


@dataclass
class GeometryReport:
    cropped: bool = False
    deskew_deg: float = 0.0
    dewarp_px: float = 0.0  # größte korrigierte Zeilenbiegung


# --------------------------------------------------------------------------- 1. Seite finden und entzerren


def _order_quad(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def find_page_quad(gray: np.ndarray) -> np.ndarray | None:
    """Vier Ecken der Papierfläche – nur wenn sie sich deutlich vom Hintergrund abhebt."""
    h, w = gray.shape
    scale = 1000 / max(h, w)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    sh, sw = small.shape
    ring = np.concatenate([small[:sh // 30].ravel(), small[-sh // 30:].ravel(),
                           small[:, :sw // 30].ravel(), small[:, -sw // 30:].ravel()])
    center = small[sh // 4:3 * sh // 4, sw // 4:3 * sw // 4]
    if np.median(center) - np.median(ring) < 25:
        return None  # kein deutlicher Hintergrund (bereits zugeschnitten oder heller Hintergrund)
    blur = cv2.GaussianBlur(small, (9, 9), 0)
    _, mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    cnt = max(contours, key=cv2.contourArea)
    if cv2.contourArea(cnt) < 0.35 * sh * sw:
        return None
    approx = cv2.approxPolyDP(cnt, 0.02 * cv2.arcLength(cnt, True), True)
    quad = approx if len(approx) == 4 else cv2.boxPoints(cv2.minAreaRect(cnt))
    return _order_quad(np.array(quad, dtype=np.float32) / scale)


def warp_to_rect(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = quad
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(quad, dst)
    out = cv2.warpPerspective(img, m, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    inset = max(2, int(min(width, height) * 0.006))  # Reste des Scan-Hintergrunds am Rand wegschneiden
    return out[inset:height - inset, inset:width - inset]


# --------------------------------------------------------------------------- 3. Wölbung glätten


def _text_lines(gray: np.ndarray) -> list[np.ndarray]:
    """Mittellinien der Textzeilen als Punktfolgen (x, y) – aus waagrecht verschmierten Zeilenbändern."""
    h, w = gray.shape
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    # große Flächen/Linien entfernen: nur schriftgroße Komponenten
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    keep = np.zeros(n, dtype=bool)
    for i in range(1, n):
        cw, ch = stats[i, 2], stats[i, 3]
        keep[i] = h * 0.004 < ch < h * 0.05 and cw < w * 0.15
    text = (keep[labels]).astype(np.uint8) * 255
    smear = cv2.morphologyEx(text, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 40), 3)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(smear, connectivity=8)
    lines = []
    step = max(4, w // 120)
    for i in range(1, n):
        x, y, cw, ch = stats[i, :4]
        if cw < w * 0.25 or ch > h * 0.08:
            continue
        comp = labels[y:y + ch, x:x + cw] == i
        pts = []
        for cx in range(0, cw, step):
            ys = np.nonzero(comp[:, cx])[0]
            if ys.size:
                pts.append((x + cx, y + ys.mean()))
        if len(pts) >= 8:
            lines.append(np.array(pts, dtype=np.float32))
    return lines


def dewarp(img: np.ndarray, gray: np.ndarray, min_shift: float = 3.0) -> tuple[np.ndarray, float]:
    """Gebogene Textzeilen geradeziehen. Ergebnis: (Bild, größte Korrektur in Pixeln)."""
    h, w = gray.shape
    lines = _text_lines(gray)
    if len(lines) < 5:
        return img, 0.0
    cols = np.linspace(0, w - 1, 48)
    samples: list[tuple[float, np.ndarray]] = []  # (mittlere y-Lage der Zeile, Verschiebung je Spalte)
    max_dy = 0.0
    for pts in lines:
        coeff = np.polyfit(pts[:, 0], pts[:, 1], 3)
        x_min, x_max = pts[:, 0].min(), pts[:, 0].max()
        xs = np.clip(cols, x_min, x_max)  # außerhalb der Zeile: Randwert fortsetzen
        ys = np.polyval(coeff, xs)
        ref = float(np.median(ys))
        dy = ys - ref
        max_dy = max(max_dy, float(np.abs(dy).max()))
        samples.append((ref, dy))
    if max_dy < min_shift or max_dy > h * 0.05:
        return img, 0.0  # zu gering – oder unplausibel stark (eher Messfehler, z. B. an Abbildungen)
    samples.sort(key=lambda s: s[0])
    refs = np.array([s[0] for s in samples])
    dys = np.stack([s[1] for s in samples])  # (Zeilen, Spalten)
    # glätten: Ausreißer-Zeilen (z. B. Überschrift) dämpfen
    if len(samples) >= 5:
        dys = cv2.GaussianBlur(dys.astype(np.float32), (1, 3), 0) if dys.shape[0] >= 3 else dys
    grid_y = np.linspace(0, h - 1, 64)
    field = np.zeros((len(grid_y), len(cols)), dtype=np.float32)
    for j in range(len(cols)):
        field[:, j] = np.interp(grid_y, refs, dys[:, j])
    full = cv2.resize(field, (w, h), interpolation=cv2.INTER_CUBIC)
    map_x, map_y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    out = cv2.remap(img, map_x, map_y + full, interpolation=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return out, max_dy


# --------------------------------------------------------------------------- Gesamt


def rotate(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def normalize_geometry(color: np.ndarray) -> tuple[np.ndarray, GeometryReport]:
    """Seite finden und entzerren, Schräglage und Wölbung ausgleichen."""
    report = GeometryReport()
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    quad = find_page_quad(gray)
    if quad is not None:
        color = warp_to_rect(color, quad)
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        report.cropped = True
    angle = estimate_skew(gray)
    if abs(angle) >= 0.2:
        color = rotate(color, angle)
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        report.deskew_deg = angle
    color, report.dewarp_px = dewarp(color, gray)
    return color, report


def common_size(sizes: list[tuple[int, int]]) -> tuple[int, int] | None:
    """Gemeinsames Normalformat (Median von Breite und Höhe); None bei nur einer Seite."""
    if len(sizes) < 2:
        return None
    return int(statistics.median(s[0] for s in sizes)), int(statistics.median(s[1] for s in sizes))


def fit_to(img: np.ndarray, size: tuple[int, int], tolerance: float = 0.15) -> np.ndarray:
    """Auf das Normalformat bringen. Stark abweichende Seiten (z. B. Falttafeln) behalten ihr Format."""
    h, w = img.shape[:2]
    tw, th = size
    if abs(w / tw - 1) > tolerance * 2 or abs(h / th - 1) > tolerance * 2:
        return img
    if (w, h) == (tw, th):
        return img
    return cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA if w > tw else cv2.INTER_CUBIC)
