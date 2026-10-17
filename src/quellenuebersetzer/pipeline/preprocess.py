"""Bildaufbereitung: Graustufen, Begradigen, Kontrast, Binarisierung."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def load_gray(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)  # robust bei Nicht-ASCII-Pfaden
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Bild kann nicht gelesen werden: {path.name}")
    return img


def save_png(img: np.ndarray, path: Path) -> Path:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("Bild konnte nicht gespeichert werden.")
    path.parent.mkdir(parents=True, exist_ok=True)
    buf.tofile(str(path))
    return path


def encode_png(img: np.ndarray, max_side: int | None = None) -> bytes:
    if max_side and max(img.shape[:2]) > max_side:
        scale = max_side / max(img.shape[:2])
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes() if ok else b""


def estimate_skew(gray: np.ndarray) -> float:
    """Schräglage in Grad (positiv = gegen den Uhrzeigersinn) über die Textzeilen-Ausrichtung."""
    small = gray
    scale = 1.0
    if max(gray.shape) > 2000:
        scale = 2000 / max(gray.shape)
        small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    binary = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3)))
    best_angle, best_score = 0.0, -1.0
    h, w = binary.shape
    center = (w / 2, h / 2)
    for angle in np.arange(-5.0, 5.01, 0.25):
        m = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(binary, m, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        profile = rotated.sum(axis=1, dtype=np.float64)
        score = float(np.var(profile))
        if score > best_score:
            best_angle, best_score = float(angle), score
    return best_angle


def deskew(gray: np.ndarray) -> tuple[np.ndarray, float]:
    angle = estimate_skew(gray)
    if abs(angle) < 0.2:
        return gray, 0.0
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated, angle


def enhance(gray: np.ndarray) -> np.ndarray:
    """Kontrast angleichen und leichtes Entrauschen – für Lesemodelle (bleibt Graustufen).

    Kantenerhaltende (bilaterale) Glättung statt Non-Local-Means: an der Testsammlung gleiche Lesequalität
    bei einem Bruchteil der Rechenzeit (etwa 0,1 statt 3,4 Sekunden je A4-Seite).
    """
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    out = clahe.apply(gray)
    return cv2.bilateralFilter(out, 5, 30, 5)


def flatten(gray: np.ndarray) -> np.ndarray:
    """Hintergrund ebnen: Papier samt Tönungen, Schatten und ungleichmäßiger Belichtung herausrechnen.

    Der Hintergrund wird geschätzt, indem die (schmalen, dunklen) Schriftzüge herausgefiltert werden; geteilt
    durch ihn ist der Grund überall gleich hell. So entstehen an Kanten hinterlegter Zeilen oder Spalten keine
    Punktreihen, die die Texterkennung stören.
    """
    # Fenster breiter als der dickste Schriftstrich (auch fette Titel), schmaler als hinterlegte Zeilen
    k = max(31, int(61 * gray.shape[1] / 2480)) | 1
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    return cv2.divide(gray, background, scale=255)


def binarize(gray: np.ndarray) -> np.ndarray:
    """Adaptive Binarisierung für Tesseract (verträgt fleckiges, vergilbtes Papier)."""
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    block = max(31, (min(gray.shape) // 40) | 1)
    return cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 15)


def prepare_page(path: Path) -> dict[str, np.ndarray]:
    gray = load_gray(path)
    straight, _ = deskew(gray)
    enhanced = enhance(straight)
    return {"gray": straight, "enhanced": enhanced, "binary": binarize(enhanced)}


def crop(img: np.ndarray, bbox: tuple[int, int, int, int], pad: int = 6) -> np.ndarray:
    x0, y0, x1, y1 = bbox
    h, w = img.shape[:2]
    return img[max(0, y0 - pad):min(h, y1 + pad), max(0, x0 - pad):min(w, x1 + pad)]


# --------------------------------------------------------------------------- Doppelseiten und Scannerränder


def crop_scanner_border(gray: np.ndarray) -> tuple[int, int, int, int]:
    """Rahmen der eigentlichen Seite(n) ohne schwarze Scannerränder: (x0, y0, x1, y1)."""
    h, w = gray.shape
    dark = gray < 50
    cols = dark.mean(axis=0)
    rows = dark.mean(axis=1)

    def edge(profile: np.ndarray, from_start: bool) -> int:
        idx = range(len(profile)) if from_start else range(len(profile) - 1, -1, -1)
        limit = int(len(profile) * 0.12)  # höchstens 12 % je Seite abschneiden
        for n, i in enumerate(idx):
            if n > limit or profile[i] < 0.6:
                return i
        return 0 if from_start else len(profile) - 1

    return edge(cols, True), edge(rows, True), edge(cols, False) + 1, edge(rows, False) + 1


def find_spread_split(gray: np.ndarray) -> int | None:
    """Erkennt ein aufgeschlagenes Buch (zwei Seiten auf einem Bild) und liefert die x-Position des Bundstegs.

    Kriterien: Querformat; im mittleren Drittel eine senkrechte Zone fast ohne Textschwärzung
    (leer oder gleichmäßiger Schatten); links und rechts davon jeweils deutlich Text.
    """
    h, w = gray.shape
    if w < h * 1.15:
        return None
    small = cv2.resize(gray, (min(1600, w), int(h * min(1600, w) / w)), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape
    ink = cv2.adaptiveThreshold(small, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15)
    ink[: int(sh * 0.08)] = 0
    ink[int(sh * 0.92):] = 0
    profile = ink.mean(axis=0).astype(np.float64)
    k = max(5, sw // 80) | 1
    smooth = np.convolve(profile, np.ones(k) / k, mode="same")
    lo, hi = int(sw * 0.35), int(sw * 0.65)
    x = lo + int(np.argmin(smooth[lo:hi]))
    left, right = smooth[int(sw * 0.08):x - k], smooth[x + k:int(sw * 0.92)]
    if left.size == 0 or right.size == 0:
        return None
    text_level = min(np.percentile(left, 70), np.percentile(right, 70))
    limit = text_level * 0.25
    if text_level < 0.01 or smooth[x] > limit:
        return None
    # ganze textfreie Zone um das Minimum bestimmen …
    a, b = x, x
    while a > int(sw * 0.2) and smooth[a - 1] <= limit:
        a -= 1
    while b < int(sw * 0.8) and smooth[b + 1] <= limit:
        b += 1
    # … und dort am Schatten des Buchfalzes schneiden, sonst in der Mitte
    brightness = small[:, a:b + 1].mean(axis=0)
    if brightness.size and np.median(brightness) - brightness.min() > 20:
        x = a + int(np.argmin(brightness))
    else:
        x = (a + b) // 2
    return int(x * w / sw)


def split_spread(path: Path, out_dir: Path, number: int) -> list[tuple[Path, str]]:
    """Teilt ein Doppelseitenbild in zwei Seiten. Ergebnis: [(Pfad, Bezeichnung)], bei Einzelseiten unverändert."""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        return [(path, str(number))]
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY if img.shape[2] == 3 else cv2.COLOR_BGRA2GRAY)
    full_h, full_w = gray.shape
    x0, y0, x1, y1 = crop_scanner_border(gray)
    img, gray = img[y0:y1, x0:x1], gray[y0:y1, x0:x1]
    split = find_spread_split(gray)
    if split is None:
        if (x0, y0, x1, y1) != (0, 0, full_w, full_h):
            out = out_dir / f"{path.stem}-zugeschnitten.png"
            ok, buf = cv2.imencode(".png", img)
            buf.tofile(str(out))
            return [(out, str(number))]
        return [(path, str(number))]
    margin = max(4, gray.shape[1] // 200)
    parts = [(img[:, : split - margin], "a"), (img[:, split + margin:], "b")]
    result = []
    for part, suffix in parts:
        out = out_dir / f"{path.stem}-{suffix}.png"
        ok, buf = cv2.imencode(".png", part)
        buf.tofile(str(out))
        result.append((out, f"{number}{suffix}"))
    return result


# --------------------------------------------------------------------------- Einband (Vorder- und Rückdeckel)


def ink_density(gray: np.ndarray) -> float:
    """Anteil der Schriftpixel (adaptive Schwelle) – Textseiten deutlich über, Einbände meist unter ~2 %."""
    small = cv2.resize(gray, (min(1200, gray.shape[1]), int(gray.shape[0] * min(1200, gray.shape[1]) / gray.shape[1])),
                       interpolation=cv2.INTER_AREA)
    ink = cv2.adaptiveThreshold(small, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 18)
    return float(ink.mean())


def find_spine(gray: np.ndarray) -> int:
    """x-Position des Buchrückens auf einer Einband-Aufnahme: kräftigste senkrechte Kante im mittleren Bereich."""
    h, w = gray.shape
    small = cv2.resize(gray, (min(1600, w), int(h * min(1600, w) / w)), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape
    gx = np.abs(cv2.Sobel(cv2.GaussianBlur(small, (5, 5), 0), cv2.CV_32F, 1, 0, ksize=3))
    profile = gx[int(sh * 0.1):int(sh * 0.9)].mean(axis=0)
    lo, hi = int(sw * 0.38), int(sw * 0.62)
    band = profile[lo:hi]
    if band.size == 0 or band.max() < np.median(profile) * 2.5:
        return w // 2  # keine deutliche Kante: Mitte
    return int((lo + int(np.argmax(band))) * w / sw)


def text_line_count(gray: np.ndarray) -> int:
    """Grobe Zahl der Textzeilen (Bänder im Zeilenprofil, nur Schrift – große Flächen und Kanten zählen nicht)."""
    small = cv2.resize(gray, (min(1000, gray.shape[1]), int(gray.shape[0] * min(1000, gray.shape[1]) / gray.shape[1])),
                       interpolation=cv2.INTER_AREA)
    ink = cv2.adaptiveThreshold(small, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 18)
    # nur schriftgroße Komponenten behalten (Kanten, Linien, Flächen fallen heraus)
    n, _labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    sh = small.shape[0]
    mask = np.zeros_like(ink)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if sh * 0.004 < h < sh * 0.06 and w < small.shape[1] * 0.2 and area > 6:
            mask[_labels == i] = 1
    profile = mask.sum(axis=1)
    rows = profile > max(2, small.shape[1] * 0.01)
    bands, inside = 0, False
    for on in rows:
        if on and not inside:
            bands += 1
        inside = on
    return bands


def is_cover_spread(path: Path) -> bool:
    """Querformat und beide Hälften (fast) ohne Textzeilen → Außenseite des Einbands."""
    data = np.fromfile(str(path), dtype=np.uint8)
    gray = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return False
    h, w = gray.shape
    if w < h * 1.15:
        return False
    x = find_spine(gray)
    return text_line_count(gray[:, :x]) <= 4 and text_line_count(gray[:, x:]) <= 4


def split_cover(path: Path, out_dir: Path) -> tuple[Path, Path]:
    """Teilt eine Einband-Aufnahme am Buchrücken: (Vorderdeckel = rechte Hälfte, Rückdeckel = linke Hälfte)."""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY if img.shape[2] == 3 else cv2.COLOR_BGRA2GRAY)
    x = find_spine(gray)
    front, back = img[:, x:], img[:, :x]
    paths = []
    for part, name in ((front, "vorderdeckel"), (back, "rueckdeckel")):
        out = out_dir / f"{path.stem}-{name}.png"
        ok, buf = cv2.imencode(".png", part)
        buf.tofile(str(out))
        paths.append(out)
    return paths[0], paths[1]
