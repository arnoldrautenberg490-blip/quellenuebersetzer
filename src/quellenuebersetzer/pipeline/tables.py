"""Tabellen: Datenmodell, HTML-Ausgabe und Erkennung von Gittertabellen in Scans."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from quellenuebersetzer.pipeline.markup import markdown_cell_to_html


@dataclass
class Cell:
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1
    markdown: str = ""
    bbox: tuple[int, int, int, int] | None = None  # x0, y0, x1, y1 im Seitenbild
    header: bool = False


@dataclass
class Table:
    n_rows: int
    n_cols: int
    cells: list[Cell] = field(default_factory=list)
    bbox: tuple[int, int, int, int] | None = None
    notes: list[str] = field(default_factory=list)

    def to_html(self) -> str:
        by_row: dict[int, list[Cell]] = {}
        for c in self.cells:
            by_row.setdefault(c.row, []).append(c)
        lines = ["<table>"]
        for r in range(self.n_rows):
            row = sorted(by_row.get(r, []), key=lambda c: c.col)
            if not row:
                continue
            parts = []
            for c in row:
                tag = "th" if c.header else "td"
                span = ""
                if c.rowspan > 1:
                    span += f' rowspan="{c.rowspan}"'
                if c.colspan > 1:
                    span += f' colspan="{c.colspan}"'
                parts.append(f"<{tag}{span}>{markdown_cell_to_html(c.markdown.strip())}</{tag}>")
            lines.append("<tr>" + "".join(parts) + "</tr>")
        lines.append("</table>")
        return "\n".join(lines)

    def plausibility(self) -> list[str]:
        """Einfache Prüfungen; Ergebnis sind Hinweise für das Verzeichnis unsicherer Stellen."""
        issues = []
        covered = np.zeros((self.n_rows, self.n_cols), dtype=int)
        for c in self.cells:
            covered[c.row:c.row + c.rowspan, c.col:c.col + c.colspan] += 1
        if (covered == 0).any():
            issues.append("Tabelle hat Lücken im Zellraster.")
        if (covered > 1).any():
            issues.append("Tabelle hat überlappende Zellen.")
        issues.extend(_check_sums(self))
        return issues


_NUM_RE = re.compile(r"^[\s]*-?\d{1,3}(?:[ . ]?\d{3})*(?:[.,]\d+)?[\s]*$")


def _to_number(text: str) -> float | None:
    from quellenuebersetzer.pipeline.markup import strip_marks, unescape_md

    t = unescape_md(strip_marks(text)).strip()
    if not t or not _NUM_RE.match(t):
        return None
    t = t.replace(" ", "").replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _check_sums(table: Table) -> list[str]:
    """Erkennt Summenzeilen (letzte Zeile beginnt mit Summa/Razem/Ogółem …) und prüft sie nach."""
    grid: dict[tuple[int, int], str] = {(c.row, c.col): c.markdown for c in table.cells if c.rowspan == c.colspan == 1}
    last = table.n_rows - 1
    first_cell = grid.get((last, 0), "").lower()
    if not re.search(r"summa|razem|ogółem|ogolem|suma|zusammen|in summa", first_cell):
        return []
    issues = []
    for col in range(1, table.n_cols):
        total = _to_number(grid.get((last, col), ""))
        if total is None:
            continue
        values = [_to_number(grid.get((r, col), "")) for r in range(last)]
        nums = [v for v in values if v is not None]
        if len(nums) >= 2 and abs(sum(nums) - total) > 0.01 * max(1.0, abs(total)):
            issues.append(f"Spalte {col + 1}: Summe der Werte ({sum(nums):g}) weicht von der Summenzeile ({total:g}) ab.")
    return issues


# --------------------------------------------------------------------------- Gittererkennung


def detect_ruled_tables(gray: np.ndarray, min_cells: int = 4) -> list[Table]:
    """Findet Tabellen mit gezogenen Linien und bestimmt das Zellraster samt verbundenen Zellen."""
    import cv2

    h, w = gray.shape[:2]
    binary = cv2.adaptiveThreshold(~gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
    horiz = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 30), 1)))
    vert = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 40))))
    # kleine Lücken in Linien schließen (alte, verblasste Tabellen)
    horiz = cv2.dilate(horiz, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3)))
    vert = cv2.dilate(vert, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 9)))
    grid = cv2.bitwise_or(horiz, vert)

    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    tables = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        if cw < w * 0.2 or ch < h * 0.05:
            continue
        t = _grid_to_table(horiz[y:y + ch, x:x + cw], vert[y:y + ch, x:x + cw], (x, y))
        if t and len(t.cells) >= min_cells:
            tables.append(t)
    tables.sort(key=lambda t: t.bbox[1])
    return tables


def _line_positions(profile: np.ndarray, min_fill: float, merge: int) -> list[int]:
    idx = np.where(profile >= min_fill)[0]
    if idx.size == 0:
        return []
    groups, start, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > merge:
            groups.append((start + prev) // 2)
            start = i
        prev = i
    groups.append((start + prev) // 2)
    return groups


def _grid_to_table(horiz: np.ndarray, vert: np.ndarray, offset: tuple[int, int]) -> Table | None:
    h, w = horiz.shape
    ys = _line_positions((horiz > 0).sum(axis=1) / w, 0.25, 6)
    xs = _line_positions((vert > 0).sum(axis=0) / h, 0.25, 6)
    if len(ys) < 2 or len(xs) < 2:
        return None
    n_rows, n_cols = len(ys) - 1, len(xs) - 1

    def has_vline(x: int, y0: int, y1: int) -> bool:
        band = vert[y0 + 2:y1 - 2, max(0, x - 4):x + 5]
        return band.size > 0 and (band.max(axis=1) > 0).mean() > 0.6

    def has_hline(y: int, x0: int, x1: int) -> bool:
        band = horiz[max(0, y - 4):y + 5, x0 + 2:x1 - 2]
        return band.size > 0 and (band.max(axis=0) > 0).mean() > 0.6

    owner = -np.ones((n_rows, n_cols), dtype=int)
    cells: list[Cell] = []
    ox, oy = offset
    for r in range(n_rows):
        for c in range(n_cols):
            if owner[r, c] >= 0:
                continue
            # nach rechts ausdehnen, solange keine senkrechte Trennlinie
            cs = 1
            while c + cs < n_cols and not has_vline(xs[c + cs], ys[r], ys[r + 1]):
                cs += 1
            # nach unten ausdehnen, solange keine waagrechte Trennlinie über die ganze Breite
            rs = 1
            while r + rs < n_rows and not has_hline(ys[r + rs], xs[c], xs[c + cs]):
                rs += 1
            owner[r:r + rs, c:c + cs] = len(cells)
            cells.append(
                Cell(r, c, rs, cs, bbox=(ox + xs[c], oy + ys[r], ox + xs[c + cs], oy + ys[r + rs]))
            )
    return Table(n_rows, n_cols, cells, bbox=(ox, oy, ox + w, oy + h))


def _cluster(values: list[int], tol: int) -> list[int]:
    out: list[list[int]] = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [int(sum(g) / len(g)) for g in out]


def table_from_rules(box: tuple[int, int, int, int], rules, tol: int = 10) -> Table | None:
    """Zellraster aus erkannten Linien (``features.Rule``) – auch gestrichelt, gepunktet oder lückenhaft.

    Fehlende Außenlinien werden durch den Tabellenrand ersetzt. Verbundene Zellen entstehen dort, wo
    eine Trennlinie fehlt. Ohne mindestens zwei Spalten und zwei Zeilen: ``None``.
    """
    x0, y0, x1, y1 = box
    hs = [r for r in rules if r.orient == "h" and r.length > (x1 - x0) * 0.25]
    vs = [r for r in rules if r.orient == "v" and r.length > (y1 - y0) * 0.25]
    ys = _cluster([r.pos for r in hs] + [y0, y1], tol)
    xs = _cluster([r.pos for r in vs] + [x0, x1], tol)
    if len(ys) < 3 or len(xs) < 3 or not vs:
        return None
    n_rows, n_cols = len(ys) - 1, len(xs) - 1

    def covered(rs, pos: int, a: int, b: int) -> bool:
        if b <= a:
            return False
        span = 0
        for r in rs:
            if abs(r.pos - pos) > tol:
                continue
            lo, hi = (r.x0, r.x1) if r.orient == "h" else (r.y0, r.y1)
            span += max(0, min(b, hi) - max(a, lo))
        return span >= 0.6 * (b - a)

    def has_vline(c: int, r0: int, r1: int) -> bool:
        x = xs[c]
        return c in (0, n_cols) or covered(vs, x, ys[r0], ys[r1])

    def has_hline(r: int, c0: int, c1: int) -> bool:
        y = ys[r]
        return r in (0, n_rows) or covered(hs, y, xs[c0], xs[c1])

    owner = -np.ones((n_rows, n_cols), dtype=int)
    cells: list[Cell] = []
    for r in range(n_rows):
        for c in range(n_cols):
            if owner[r, c] >= 0:
                continue
            cs = 1
            while c + cs < n_cols and not has_vline(c + cs, r, r + 1) and owner[r, c + cs] < 0:
                cs += 1
            rs = 1
            while r + rs < n_rows and not has_hline(r + rs, c, c + cs) and (owner[r + rs, c:c + cs] < 0).all():
                rs += 1
            owner[r:r + rs, c:c + cs] = len(cells)
            cells.append(Cell(r, c, rs, cs, bbox=(xs[c], ys[r], xs[c + cs], ys[r + rs])))
    return Table(n_rows, n_cols, cells, bbox=(xs[0], ys[0], xs[-1], ys[-1]))


# --------------------------------------------------------------------------- Tabellen ohne Gitterlinien

def table_from_words(lines, min_rows: int = 2, min_cols: int = 2):
    """Baut eine Tabelle ohne Linien aus Tesseract-Wortpositionen (Zeilen nach Höhe, Spalten nach Lücken).

    Es entsteht nur, was Tesseract tatsächlich gelesen hat – keine erfundenen Inhalte.
    Ergebnis: (Table, {(Zeile, Spalte): [Word, …]}) oder None, wenn keine Tabellenstruktur erkennbar ist.
    """
    import statistics

    words = [w for ln in lines for w in ln.words if w.text.strip()]
    if len(words) < min_rows * min_cols:
        return None
    heights = [w.bbox[3] - w.bbox[1] for w in words]
    hmed = statistics.median(heights) or 10
    # Zeilen: nach senkrechter Mitte gruppieren
    words.sort(key=lambda w: (w.bbox[1] + w.bbox[3]) / 2)
    rows: list[list] = []
    for w in words:
        cy = (w.bbox[1] + w.bbox[3]) / 2
        if rows and abs(cy - statistics.mean((x.bbox[1] + x.bbox[3]) / 2 for x in rows[-1])) < hmed * 0.6:
            rows[-1].append(w)
        else:
            rows.append([w])
    if len(rows) < min_rows:
        return None
    # Wortgruppen je Zeile (Wörter mit normalem Wortabstand gehören zusammen)
    phrases_by_row = []
    for row in rows:
        row.sort(key=lambda w: w.bbox[0])
        phrases = [[row[0]]]
        for w in row[1:]:
            if w.bbox[0] - phrases[-1][-1].bbox[2] < hmed * 1.2:
                phrases[-1].append(w)
            else:
                phrases.append([w])
        phrases_by_row.append(phrases)
    # Spaltengrenzen: Lücken, die in keiner Zeile von einer Wortgruppe überdeckt werden
    spans = sorted((p[0].bbox[0], p[-1].bbox[2]) for ph in phrases_by_row for p in ph)
    columns = [[spans[0][0], spans[0][1]]]
    for a, b in spans[1:]:
        if a - columns[-1][1] > hmed * 0.8:
            columns.append([a, b])
        else:
            columns[-1][1] = max(columns[-1][1], b)
    if len(columns) < min_cols:
        return None
    rows_with_multiple = sum(1 for ph in phrases_by_row if len(ph) >= 2)
    if rows_with_multiple < max(2, len(rows) // 2):
        return None  # eher Fließtext als Tabelle
    cells: list[Cell] = []
    cell_words: dict[tuple[int, int], list] = {}
    for r, phrases in enumerate(phrases_by_row):
        for p in phrases:
            x0, x1 = p[0].bbox[0], p[-1].bbox[2]
            covered = [c for c, (a, b) in enumerate(columns) if min(x1, b) > max(x0, a)]
            if not covered:
                continue
            c0, c1 = covered[0], covered[-1]
            key = (r, c0)
            if key in cell_words:
                cell_words[key].extend(p)
                continue
            cell_words[key] = list(p)
            bbox = (min(w.bbox[0] for w in p), min(w.bbox[1] for w in p), max(w.bbox[2] for w in p),
                    max(w.bbox[3] for w in p))
            cells.append(Cell(r, c0, 1, c1 - c0 + 1, "", bbox=bbox))
    # leere Plätze auffüllen, damit das Raster vollständig ist
    occupied = {(c.row, col) for c in cells for col in range(c.col, c.col + c.colspan)}
    for r in range(len(rows)):
        for c in range(len(columns)):
            if (r, c) not in occupied:
                cells.append(Cell(r, c, 1, 1, ""))
    cells.sort(key=lambda c: (c.row, c.col))
    return Table(len(rows), len(columns), cells), cell_words


# --------------------------------------------------------------------------- Raster aus Farbbändern und Wortlücken


def shading_cuts(color: np.ndarray, ink: np.ndarray, axis: int, min_band: int) -> list[int]:
    """Grenzen zwischen unterschiedlich hinterlegten Bändern (Zebrazeilen, hinterlegte Spalten).

    ``axis = 0``: waagrechte Bänder (Zeilengrenzen, Rückgabe y), ``axis = 1``: senkrechte (Spaltengrenzen, x).
    Gemessen wird nur an schriftfreien Pixeln (Median je Zeile bzw. Spalte), damit Text keine Grenzen erzeugt.
    """
    import cv2

    if color.size == 0:
        return []
    lab = cv2.cvtColor(color, cv2.COLOR_BGR2LAB).astype(np.float32)
    busy = cv2.dilate((ink > 0).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    if axis == 1:
        lab, busy = lab.transpose(1, 0, 2), busy.T
    n = lab.shape[0]
    prof = np.full((n, 3), np.nan, np.float32)
    step = max(1, lab.shape[1] // 400)
    for i in range(n):
        free = ~busy[i, ::step]
        if free.sum() >= 8:
            prof[i] = np.median(lab[i, ::step][free], axis=0)
    ok = ~np.isnan(prof[:, 0])
    if ok.sum() < 10:
        return []
    idx = np.arange(n)
    for ch in range(3):  # Lücken (reine Schriftzeilen) überbrücken
        prof[:, ch] = np.interp(idx, idx[ok], prof[ok, ch])
    k = 5
    smooth = np.stack([np.convolve(prof[:, ch], np.ones(k) / k, mode="same") for ch in range(3)], axis=1)
    d = 3
    diff = np.zeros(n)
    diff[d:n - d] = np.linalg.norm(smooth[2 * d:] - smooth[:-2 * d], axis=1)
    cuts: list[int] = []
    i = 0
    while i < n:
        if diff[i] > 4.0:
            j = i
            while j + 1 < n and diff[j + 1] > 4.0:
                j += 1
            cuts.append(int(i + np.argmax(diff[i:j + 1])))
            i = j + 1
        else:
            i += 1
    # nur echte Bänder: Grenzen weit genug voneinander und vom Rand
    out: list[int] = []
    for c in cuts:
        if c < min_band // 2 or c > n - min_band // 2:
            continue
        if out and c - out[-1] < min_band:
            continue
        out.append(c)
    return out


def word_columns(lines, min_gap: float | None = None) -> list[tuple[int, int]]:
    """Spalten einer Tabelle ohne Linien: Bereiche, die durch Lücken getrennt sind, die in keiner Zeile von
    einer Wortgruppe überdeckt werden."""
    import statistics

    words = [w for ln in lines for w in ln.words if w.text.strip()]
    if not words:
        return []
    hmed = statistics.median(w.bbox[3] - w.bbox[1] for w in words) or 10
    gap = min_gap or hmed * 0.8
    phrases = []
    for ln in lines:
        ws = sorted((w for w in ln.words if w.text.strip()), key=lambda w: w.bbox[0])
        if not ws:
            continue
        cur = [ws[0]]
        for w in ws[1:]:
            if w.bbox[0] - cur[-1].bbox[2] < hmed * 1.2:
                cur.append(w)
            else:
                phrases.append((cur[0].bbox[0], cur[-1].bbox[2]))
                cur = [w]
        phrases.append((cur[0].bbox[0], cur[-1].bbox[2]))
    spans = sorted(phrases)
    columns = [[spans[0][0], spans[0][1]]]
    for a, b in spans[1:]:
        if a - columns[-1][1] > gap:
            columns.append([a, b])
        else:
            columns[-1][1] = max(columns[-1][1], b)
    return [(int(a), int(b)) for a, b in columns]


def split_rows_in_band(words, a: int, b: int, col_bounds: list[int], line_h: float) -> list[int]:
    """Weitere Zeilengrenzen in einem Band: nur wenn ALLE belegten Spalten gleich viele, auf gleicher Höhe
    liegende Textzeilen haben (z. B. ein Farbband über mehrere Tabellenzeilen). Eine mehrzeilige Zelle neben
    einzeiligen bleibt dagegen eine Zeile."""
    per_col = []
    for c0, c1 in zip(col_bounds, col_bounds[1:]):
        ys = sorted((w.bbox[1] + w.bbox[3]) / 2 for w in words
                    if a <= (w.bbox[1] + w.bbox[3]) / 2 < b and c0 <= (w.bbox[0] + w.bbox[2]) / 2 < c1)
        centers: list[list[float]] = []
        for y in ys:
            if centers and y - centers[-1][-1] < 0.6 * line_h:
                centers[-1].append(y)
            else:
                centers.append([y])
        if centers:
            per_col.append([sum(c) / len(c) for c in centers])
    if len(per_col) < 2 or len({len(p) for p in per_col}) != 1 or len(per_col[0]) < 2:
        return []
    k = len(per_col[0])
    for i in range(k):
        vals = [p[i] for p in per_col]
        if max(vals) - min(vals) > 0.5 * line_h:
            return []
    means = [sum(p[i] for p in per_col) / len(per_col) for i in range(k)]
    return [int((means[i] + means[i + 1]) / 2) for i in range(k - 1)]
