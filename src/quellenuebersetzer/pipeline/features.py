"""Stufe A der Seitenaufbau-Erkennung: Merkmalsebenen in voller Auflösung und in Farbe.

Hier wird nur *erfasst*, nichts entschieden. Jede Ebene ist unabhängig:

- Linien:      waagrechte und senkrechte Linien – durchgezogen, gestrichelt, gepunktet, blass, mit Lücken
- Flächen:     Rechtecke aus Rahmen (Linien) oder aus Farbkanten (hinterlegte Kästen, auch ohne Rahmen),
               mit Hintergrundfarbe und Rahmenart
- Linienmaske: alle Linienpixel – vor der Texterkennung werden sie entfernt („Grafik ist kein Text“)

Die Entscheidung über die Struktur (Stufe B) trifft ``structure.py`` mit allen Ebenen und dem Layoutmodell.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Rule:
    orient: str  # "h" | "v"
    x0: int
    y0: int
    x1: int
    y1: int
    style: str  # solid | dashed | dotted
    thickness: int
    color: str  # Hex

    @property
    def length(self) -> int:
        return (self.x1 - self.x0) if self.orient == "h" else (self.y1 - self.y0)

    @property
    def pos(self) -> int:
        return (self.y0 + self.y1) // 2 if self.orient == "h" else (self.x0 + self.x1) // 2


@dataclass
class Panel:
    """Rechteckige Fläche: gerahmter oder hinterlegter Kasten (oder ein Tabellengitter)."""

    box: tuple[int, int, int, int]
    fill: str = ""  # Hintergrundfarbe (Hex), leer = Papier
    stroke: str = ""  # Rahmenfarbe (Hex), leer = kein Rahmen
    dash: str = ""  # solid | dashed | dotted
    stroke_px: int = 0
    dark: bool = False  # helle Schrift auf dem Grund (gemessen: Weiß auf Rot, Blau, Grau …)
    grid: bool = False  # enthält ein Linienraster (Tabelle)
    source: str = "kanten"  # kanten (Rahmen/Farbkanten) | farbe (formunabhängige Farbfläche)


@dataclass
class PageFeatures:
    width: int
    height: int
    paper: tuple[int, int, int]  # BGR
    rules: list[Rule] = field(default_factory=list)
    panels: list[Panel] = field(default_factory=list)
    line_mask: np.ndarray | None = None  # 255 = Linienpixel (volle Auflösung)

    def rules_in(self, box, orient: str | None = None, margin: int = 6) -> list[Rule]:
        x0, y0, x1, y1 = box
        return [r for r in self.rules if (orient is None or r.orient == orient)
                and r.x0 >= x0 - margin and r.x1 <= x1 + margin and r.y0 >= y0 - margin and r.y1 <= y1 + margin]


def hexcolor(bgr) -> str:
    b, g, r = (int(round(float(v))) for v in bgr)
    return f"#{r:02x}{g:02x}{b:02x}"


def _scale(w: int) -> float:
    return w / 2480.0  # Maße sind für 300 dpi (A4-Breite) gewählt und werden mitskaliert


# --------------------------------------------------------------------------- Linien


def ink_mask(gray: np.ndarray) -> np.ndarray:
    """Dunkle Striche (Schrift und Linien) als 255 – lokal angepasst, verträgt Vergilbung und Schatten."""
    block = max(31, (min(gray.shape) // 40) | 1)
    return cv2.adaptiveThreshold(cv2.GaussianBlur(gray, (3, 3), 0), 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                 cv2.THRESH_BINARY_INV, block, 12)


def _classify(profile: np.ndarray) -> str:
    """Strichart aus der Belegung entlang der Linie (1 = Tinte)."""
    if profile.size == 0:
        return "solid"
    fill = float(profile.mean())
    if fill > 0.9:
        return "solid"
    edges = np.flatnonzero(np.diff(np.concatenate([[0], profile.astype(np.int8), [0]])))
    runs = edges[1::2] - edges[0::2]
    mean_run = float(runs.mean()) if runs.size else 0.0
    return "dotted" if mean_run < 8 else "dashed"


def _regular(profile: np.ndarray) -> bool:
    """Gleichmäßiges Strich-Lücke-Muster (gestrichelt/gepunktet) statt zufälliger Schriftteile."""
    edges = np.flatnonzero(np.diff(np.concatenate([[0], profile.astype(np.int8), [0]])))
    runs = (edges[1::2] - edges[0::2])[1:-1]  # angeschnittene Enden nicht werten
    gaps = edges[2::2] - edges[1:-1:2]
    if runs.size < 4 or gaps.size < 4:
        return False
    cv_runs = float(runs.std() / max(1.0, runs.mean()))
    cv_gaps = float(gaps.std() / max(1.0, gaps.mean()))
    return cv_runs < 0.45 and cv_gaps < 0.6


def extract_rules(ink: np.ndarray, color: np.ndarray | None = None, min_len: int | None = None,
                  max_thick: int | None = None, gap: int | None = None) -> tuple[list[Rule], np.ndarray]:
    """Findet Linien jeder Art. Lücken (Striche, Punkte, Ausbrüche) werden vor der Längenprüfung geschlossen.

    Schrift wird nicht zur Linie: Zusammengeschlossene Textzeilen sind dicker als ``max_thick``.
    Ergebnis: Linien und eine Maske ihrer Pixel (im Original, nicht die geschlossene Form).
    """
    h, w = ink.shape
    s = _scale(max(w, 600))
    min_len = min_len or max(40, int(150 * s))
    max_thick = max_thick or max(4, int(11 * s))
    gap = gap or max(8, int(26 * s))  # überbrückt auch weit gestrichelte, ausgebrochene Linien
    rules: list[Rule] = []
    mask = np.zeros_like(ink)
    for orient in ("h", "v"):
        k_gap = (gap, 1) if orient == "h" else (1, gap)
        k_len = (min_len, 1) if orient == "h" else (1, min_len)
        closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, k_gap))
        long = cv2.morphologyEx(closed, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, k_len))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(long, connectivity=8)
        for i in range(1, n):
            x, y, bw, bh, _area = stats[i]
            thick = bh if orient == "h" else bw
            length = bw if orient == "h" else bh
            if thick > max_thick or length < min_len:
                continue
            band = ink[y:y + bh, x:x + bw] > 0
            profile = band.any(axis=0 if orient == "h" else 1)
            # Linie oder zusammengeschlossene Schrift? Neben einer Linie ist es (fast) leer,
            # neben einem Schriftband stehen die Buchstabenkörper.
            off, depth = max(2, int(3 * s)), max(4, int(9 * s))
            if orient == "h":
                above = ink[max(0, y - off - depth):max(0, y - off), x:x + bw]
                below = ink[y + bh + off:y + bh + off + depth, x:x + bw]
                sides = [a.any(axis=0).mean() if a.size else 0.0 for a in (above, below)]
            else:
                left = ink[y:y + bh, max(0, x - off - depth):max(0, x - off)]
                right = ink[y:y + bh, x + bw + off:x + bw + off + depth]
                sides = [a.any(axis=1).mean() if a.size else 0.0 for a in (left, right)]
            if min(sides) > 0.25 or max(sides) > 0.6:
                continue
            style = _classify(profile)
            # kurze unterbrochene „Linien“ sind fast immer zufällig ausgerichtete Schriftteile;
            # echte Strich- und Punktlinien sind regelmäßig und haben freien Raum auf beiden Seiten
            if style != "solid" and (length < max(min_len * 2, int(300 * s)) or not _regular(profile)
                                     or max(sides) > 0.2):
                continue
            # dünne „Linien“ aus aneinandergereihten Zeichen (z. B. Unterstreichung von Text) sind selten;
            # Punktlinien müssen aber regelmäßig sein: sehr ungleichmäßige Belegung → keine Linie
            if style == "dotted" and profile.mean() < 0.12:
                continue
            col = "#1e1b17"
            if color is not None:
                px = color[y:y + bh, x:x + bw][band]
                if px.size:
                    col = hexcolor(np.median(px.reshape(-1, 3), axis=0))
            real_thick = int(max(1, round(band.sum() / max(1, profile.sum()))))
            rules.append(Rule(orient, int(x), int(y), int(x + bw), int(y + bh), style, real_thick, col))
            mask[y:y + bh, x:x + bw] |= (band.astype(np.uint8) * 255)
    return rules, mask


# --------------------------------------------------------------------------- Flächen (Kästen)


def _lab(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)


def _edges_to_rects(hs: list[tuple[int, int, int]], vs: list[tuple[int, int, int]], tol: int,
                    min_w: int, min_h: int) -> list[tuple[int, int, int, int]]:
    """Rechtecke aus waagrechten (y, x0, x1) und senkrechten (x, y0, y1) Kanten."""
    rects = []
    hs = sorted(hs)
    for i, (ya, ax0, ax1) in enumerate(hs):
        for yb, bx0, bx1 in hs[i + 1:]:
            if yb - ya < min_h:
                continue
            x0, x1 = max(ax0, bx0), min(ax1, bx1)
            if x1 - x0 < min_w or abs(ax0 - bx0) > tol * 3 or abs(ax1 - bx1) > tol * 3:
                continue

            def side(xx: int) -> bool:
                return any(abs(vx - xx) <= tol * 2 and vy0 <= ya + tol * 2 and vy1 >= yb - tol * 2
                           for vx, vy0, vy1 in vs)

            if side(x0) and side(x1):
                rects.append((x0, ya, x1, yb))
    # innere Duplikate (gleiche Kanten) zusammenfassen: kleinste Rechtecke je oberer Kante behalten
    out: list[tuple[int, int, int, int]] = []
    for r in sorted(rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1])):
        if any(abs(r[0] - o[0]) <= tol and abs(r[1] - o[1]) <= tol and abs(r[2] - o[2]) <= tol
               and abs(r[3] - o[3]) <= tol for o in out):
            continue
        out.append(r)
    return out


def _fill_edges(color: np.ndarray, factor: int) -> tuple[list, list]:
    """Lange gerade Farbkanten (Rand hinterlegter Flächen) auf einem schriftfreien, verkleinerten Bild."""
    small = cv2.resize(color, None, fx=1 / factor, fy=1 / factor, interpolation=cv2.INTER_AREA)
    smooth = cv2.medianBlur(small, 9)  # entfernt Schrift (Tinte belegt nur einen kleinen Teil der Fläche)
    lab = _lab(smooth)
    grad_y = np.zeros(lab.shape[:2], np.float32)
    grad_x = np.zeros(lab.shape[:2], np.float32)
    for ch in range(3):
        grad_y = np.maximum(grad_y, np.abs(cv2.Sobel(lab[..., ch], cv2.CV_32F, 0, 1, ksize=3)))
        grad_x = np.maximum(grad_x, np.abs(cv2.Sobel(lab[..., ch], cv2.CV_32F, 1, 0, ksize=3)))
    min_len_h = max(20, smooth.shape[1] // 10)
    min_len_v = max(12, int(110 * smooth.shape[1] / 2480 * 0.7))  # so kurz wie der niedrigste Kasten
    out = []
    for grad, orient in ((grad_y, "h"), (grad_x, "v")):
        edge = (grad > 8).astype(np.uint8) * 255  # auch blasse, gealterte Tönungen
        k = (min_len_h, 1) if orient == "h" else (1, min_len_v)
        edge = cv2.morphologyEx(edge, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT,
                                                                               (15, 1) if orient == "h" else (1, 15)))  # Unterbrechungen durch nahe Schrift
        edge = cv2.morphologyEx(edge, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, k))
        n, _l, stats, _ = cv2.connectedComponentsWithStats(edge, connectivity=8)
        segs = []
        for i in range(1, n):
            x, y, bw, bh, _a = stats[i]
            if orient == "h" and bh <= 6:
                segs.append((int((y + bh / 2) * factor), int(x * factor), int((x + bw) * factor)))
            elif orient == "v" and bw <= 6:
                segs.append((int((x + bw / 2) * factor), int(y * factor), int((y + bh) * factor)))
        out.append(segs)
    return out[0], out[1]


def _surrounding_lab(color: np.ndarray, box, tol: int, fallback: np.ndarray) -> np.ndarray:
    """Papierfarbe direkt um eine Fläche (schriftfreie Pixel eines Rings) – unempfindlich gegen ungleichmäßige
    Belichtung und Vergilbung, die die Seite stellenweise dunkler machen."""
    h, w = color.shape[:2]
    x0, y0, x1, y1 = box
    ring = max(20, tol * 3)
    ox0, oy0, ox1, oy1 = max(0, x0 - ring), max(0, y0 - ring), min(w, x1 + ring), min(h, y1 + ring)
    outer = color[oy0:oy1, ox0:ox1]
    mask = np.ones(outer.shape[:2], bool)
    mask[max(0, y0 - tol - oy0):max(0, y1 + tol - oy0), max(0, x0 - tol - ox0):max(0, x1 + tol - ox0)] = False
    mask &= ink_mask(cv2.cvtColor(outer, cv2.COLOR_BGR2GRAY)) == 0
    px = outer[mask]
    if px.size < 300:
        return fallback
    med = np.median(px.reshape(-1, 3)[:: max(1, len(px) // 20000)], axis=0)
    return _lab(med.reshape(1, 1, 3).astype(np.uint8))[0, 0]


def detect_panels(color: np.ndarray, rules: list[Rule], paper_lab: np.ndarray) -> list[Panel]:
    h, w = color.shape[:2]
    s = _scale(w)
    tol = max(4, int(12 * s))
    min_w, min_h = int(250 * s), int(110 * s)
    # Kanten aus Linien (Rahmen) und aus Farbflächen
    hs = [(r.pos, r.x0, r.x1) for r in rules if r.orient == "h"]
    vs = [(r.pos, r.y0, r.y1) for r in rules if r.orient == "v"]
    fh, fv = _fill_edges(color, max(1, round(w / 620)))
    rects = _edges_to_rects(hs + fh, vs + fv, tol, min_w, min_h)
    panels: list[Panel] = []
    for (x0, y0, x1, y1) in rects:
        inner = color[y0 + tol:y1 - tol, x0 + tol:x1 - tol]
        if inner.size == 0:
            continue
        smooth = cv2.medianBlur(cv2.resize(inner, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA), 7)
        bg = np.median(smooth.reshape(-1, 3), axis=0)
        bg_lab = _lab(bg.reshape(1, 1, 3).astype(np.uint8))[0, 0]
        if bg_lab[0] * 100 / 255 >= 45:
            # heller Grund: Farbe nur aus Pixeln ohne Schrift – über einem dichten Textblock ist das Papier,
            # so entsteht dort kein Scheinkasten
            free = inner[ink_mask(cv2.cvtColor(inner, cv2.COLOR_BGR2GRAY)) == 0]
            if free.size:
                bg = np.median(free.reshape(-1, 3)[:: max(1, len(free) // 20000)], axis=0)
                bg_lab = _lab(bg.reshape(1, 1, 3).astype(np.uint8))[0, 0]
        diff = float(np.linalg.norm(bg_lab - _surrounding_lab(color, (x0, y0, x1, y1), tol, paper_lab)))
        # Rahmen: Linien auf (fast) allen vier Seiten
        frame = [r for r in rules if (r.orient == "h" and min(abs(r.pos - y0), abs(r.pos - y1)) <= tol
                                      and r.x0 <= x0 + tol * 3 and r.x1 >= x1 - tol * 3)
                 or (r.orient == "v" and min(abs(r.pos - x0), abs(r.pos - x1)) <= tol
                     and r.y0 <= y0 + tol * 3 and r.y1 >= y1 - tol * 3)]
        inside = [r for r in rules if r.x0 > x0 + tol and r.x1 < x1 - tol and r.y0 > y0 + tol and r.y1 < y1 - tol]
        inside_h = sum(1 for r in inside if r.orient == "h")
        inside_v = sum(1 for r in inside if r.orient == "v")
        # Gitter: auch Linien, die bis an den Rahmen reichen, zählen
        cross_h = sum(1 for r in rules if r.orient == "h" and y0 + tol < r.pos < y1 - tol
                      and r.x0 <= x0 + tol * 3 and r.x1 >= x1 - tol * 3)
        cross_v = sum(1 for r in rules if r.orient == "v" and x0 + tol < r.pos < x1 - tol
                      and r.y0 <= y0 + tol * 3 and r.y1 >= y1 - tol * 3)
        grid = (cross_h + inside_h) >= 1 and (cross_v + inside_v) >= 1
        filled = diff > 6
        if not frame and not filled:
            continue  # weder Rahmen noch eigene Farbe: zufälliges Kantenpaar
        stroke = dash = ""
        stroke_px = 0
        if len(frame) >= 3:
            styles = [r.style for r in frame]
            dash = max(set(styles), key=styles.count)
            stroke = frame[0].color
            stroke_px = int(np.median([r.thickness for r in frame]))
        elif not filled:
            continue
        light_text = filled and light_text_on(cv2.cvtColor(inner, cv2.COLOR_BGR2GRAY))
        panels.append(Panel((x0, y0, x1, y1), hexcolor(bg) if filled else "", stroke, dash, stroke_px,
                            dark=light_text, grid=grid))
    # Verschachtelte Doppelungen (Rahmen- und Farbkante desselben Kastens) zusammenfassen;
    # Teilrechtecke eines Gitters (Zeilen einer Tabelle) gehören zum ganzen Gitter
    out: list[Panel] = []
    for p in sorted(panels, key=lambda p: -(p.box[2] - p.box[0]) * (p.box[3] - p.box[1])):
        if any(o.grid and _inside(p.box, o.box, tol * 2) for o in out):
            continue
        dup = next((o for o in out if all(abs(a - b) <= tol * 3 for a, b in zip(p.box, o.box))), None)
        if dup:
            dup.fill = dup.fill or p.fill
            dup.stroke, dup.dash = dup.stroke or p.stroke, dup.dash or p.dash
            dup.grid = dup.grid or p.grid
            continue
        out.append(p)
    return out


def _inside(inner, outer, tol: int = 0) -> bool:
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and inner[2] <= outer[2] + tol
            and inner[3] <= outer[3] + tol)


def paper_color(color: np.ndarray) -> np.ndarray:
    small = cv2.resize(color, None, fx=0.1, fy=0.1, interpolation=cv2.INTER_AREA)
    return np.median(small.reshape(-1, 3), axis=0)


# --------------------------------------------------------------------------- Farbflächen (formunabhängig)


def light_text_on(gray_crop: np.ndarray) -> bool:
    """Ist die Schrift auf dieser Fläche heller als der Grund? (Weiß auf Rot, Grün, Blau, Grau …)

    Gemessen statt aus der Helligkeit des Grundes geschlossen: Schriftpixel sind die Minderheit, die sich
    deutlich vom Median abhebt – nach oben (helle Schrift) oder nach unten (dunkle Schrift).
    """
    if gray_crop.size == 0:
        return False
    med = float(np.median(gray_crop))
    lighter = float((gray_crop > med + 40).mean())
    darker = float((gray_crop < med - 40).mean())
    return lighter > darker and lighter > 0.005


def detect_color_regions(color: np.ndarray, factor: int | None = None) -> list[Panel]:
    """Farbig hinterlegte Flächen jeder Form und Lage – auch randabfallend, abgerundet oder direkt an einer
    andersfarbigen Fläche.

    Die Schrift wird herausgefiltert (zweifacher Median auf dem verkleinerten Bild, egal ob dunkel oder hell),
    dann wird das Bild an Farbkanten in einheitliche Flächen zerlegt. Die größte Fläche ist das Papier; jede
    andere große, einheitliche Fläche, die sich vom Papier daneben unterscheidet, ist ein Block.
    """
    h, w = color.shape[:2]
    factor = factor or max(1, round(w / 620))  # Arbeitsbild etwa 620 Pixel breit – unabhängig von der Auflösung
    small = cv2.resize(color, None, fx=1 / factor, fy=1 / factor, interpolation=cv2.INTER_AREA)
    smooth = cv2.medianBlur(cv2.medianBlur(small, 9), 9)
    lab = _lab(smooth)
    grad = np.zeros(lab.shape[:2], np.float32)
    kernel = np.ones((3, 3), np.uint8)
    for ch in range(3):
        grad = np.maximum(grad, cv2.morphologyEx(lab[..., ch], cv2.MORPH_GRADIENT, kernel))
    uniform = (cv2.dilate((grad > 4).astype(np.uint8), kernel) == 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(uniform, connectivity=4)
    if n <= 1:
        return []
    paper_id = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    paper_mask = labels == paper_id
    s = _scale(w)
    min_area = (250 * s / factor) * (110 * s / factor)
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    panels: list[Panel] = []
    for i in range(1, n):
        if i == paper_id:
            continue
        x, y, bw, bh, area = (int(v) for v in stats[i])
        if area < min_area:
            continue
        mask = (labels[y:y + bh, x:x + bw] == i).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = sum(cv2.contourArea(c) for c in contours)
        if filled < 0.55 * bw * bh:
            continue  # verästelte Fläche (z. B. Teil eines Fotos), kein Block
        region = lab[y:y + bh, x:x + bw][mask > 0]
        own = np.median(region, axis=0)
        # Papier in der Umgebung (unempfindlich gegen Vergilbung und Schatten)
        ring = 12
        ry0, ry1, rx0, rx1 = max(0, y - ring), min(lab.shape[0], y + bh + ring), max(0, x - ring), min(lab.shape[1], x + bw + ring)
        near = lab[ry0:ry1, rx0:rx1][paper_mask[ry0:ry1, rx0:rx1]]
        paper_lab = np.median(near, axis=0) if len(near) > 30 else np.median(lab[paper_mask], axis=0)
        if float(np.linalg.norm(own - paper_lab)) < 6:
            continue
        box = (x * factor, y * factor, min(w, (x + bw) * factor), min(h, (y + bh) * factor))
        bgr = np.median(smooth[y:y + bh, x:x + bw][mask > 0], axis=0)
        sub = gray[box[1]:box[3], box[0]:box[2]]
        panels.append(Panel(box, hexcolor(bgr), dark=light_text_on(sub), source="farbe"))
    return panels


def text_ink(gray: np.ndarray, feats: PageFeatures) -> np.ndarray:
    """Schriftpixel ohne Linien – auf dunklem Grund wird die helle Schrift gesucht."""
    ink = ink_mask(gray)
    for p in feats.panels:
        if p.dark:
            x0, y0, x1, y1 = p.box
            ink[y0:y1, x0:x1] = ink_mask(255 - gray[y0:y1, x0:x1])
    if feats.line_mask is not None:
        ink[feats.line_mask > 0] = 0
    return ink


def _merge_panels(framed: list[Panel], colored: list[Panel]) -> list[Panel]:
    """Kästen aus Kanten (mit Rahmenart) und Farbflächen zusammenführen – dieselbe Fläche nur einmal."""
    out = []
    for p in framed:
        if not p.stroke and not p.grid:
            # rahmenloses „Rechteck“, das in Wahrheit aus mehreren aneinanderstoßenden Farbflächen besteht
            parts = [c for c in colored if _inside_box(c.box, p.box, 16)]
            covered = sum((c.box[2] - c.box[0]) * (c.box[3] - c.box[1]) for c in parts)
            if len(parts) >= 2 and covered > 0.7 * (p.box[2] - p.box[0]) * (p.box[3] - p.box[1]):
                continue
        out.append(p)
    for c in colored:
        same = next((p for p in out if _box_iou(p.box, c.box) > 0.7), None)
        if same is not None:
            same.fill = same.fill or c.fill
            same.dark = same.dark or c.dark
            continue
        # Fläche ganz in einem Linienraster (Zebrazeile, hinterlegte Spalte) übernimmt die Tabelle
        out.append(c)
    return out


def _inside_box(inner, outer, tol: int) -> bool:
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol and inner[2] <= outer[2] + tol
            and inner[3] <= outer[3] + tol)


def _box_iou(a, b) -> float:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def analyse(color: np.ndarray) -> PageFeatures:
    h, w = color.shape[:2]
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    paper = paper_color(color)
    rules, mask = extract_rules(ink_mask(gray), color)
    paper_lab = _lab(paper.reshape(1, 1, 3).astype(np.uint8))[0, 0]
    panels = _merge_panels(detect_panels(color, rules, paper_lab), detect_color_regions(color))
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    return PageFeatures(w, h, tuple(int(v) for v in paper), rules, panels, mask)
