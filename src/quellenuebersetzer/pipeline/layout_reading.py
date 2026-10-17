"""Lesen für die Layoutkopie: Seitenaufbau erkennen, jeden Bereich mit dem passenden Werkzeug lesen.

Phase 1 (Struktur, ganzes Dokument zuerst):
  Merkmalsebenen in voller Auflösung und Farbe (``features``) + Layoutmodell auf dem Farbbild →
  Entscheidung mit Regeln (``structure``): Kästen als eigene Textflüsse, Linienraster als Tabellen,
  Spalten an echten Lücken geteilt.

Phase 2 (Text je Bereich):
  - Linien werden vor der Texterkennung aus dem Bild entfernt (Grafik ist kein Text).
  - Hinterlegte Kästen werden auf „dunkle Schrift auf hellem Grund“ umgerechnet (auch helle Schrift
    auf dunklem Grund); bei schlechter Lesesicherheit wird eine zweite Bildvariante versucht.
  - Zeichenfolgen ohne Buchstaben/Ziffern („----“, „....“, „|“) werden verworfen.
  - Strukturelemente nur mit Beleg: Fußnote mit Verweiszeichen oder Trennlinie, Seitenzahl nur, wenn sie
    wie eine aussieht, Tabellenkopf nur bei Fettdruck, Hinterlegung oder kräftigerer Linie.
  - Unlesbare Bereiche werden markiert und gemeldet, statt Zeichenmüll zu übersetzen.
Text, der in keinem erkannten Bereich liegt, wird über Tesseract aufgefangen (nichts geht verloren).
"""

from __future__ import annotations

import re
import statistics
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from quellenuebersetzer.pipeline import features as feat_mod
from quellenuebersetzer.pipeline import fusion, structure
from quellenuebersetzer.pipeline.document import PageImage
from quellenuebersetzer.pipeline.layout_doc import IMAGE_KINDS, LPage, LRegion
from quellenuebersetzer.pipeline.markup import mark_illegible, mark_reading
from quellenuebersetzer.pipeline.markup import strip_marks as markup_plain
from quellenuebersetzer.pipeline.markup import unescape_md
from quellenuebersetzer.pipeline.pagegeom import fit_to, normalize_geometry
from quellenuebersetzer.pipeline.preprocess import binarize, crop, enhance, flatten, save_png
from quellenuebersetzer.pipeline.reading import Item, PageReader, PageWork, _char_width, segment_lines
from quellenuebersetzer.pipeline.tables import Table, table_from_rules, table_from_words
from quellenuebersetzer.pipeline.typography import bold_flags, stroke_ratio
from quellenuebersetzer.pipeline.typography import measure as measure_style
from quellenuebersetzer.profile import SourceKind
from quellenuebersetzer.runtime.layout import LayoutDetector
from quellenuebersetzer.runtime.tesseract import Line, OcrPage, Word

SINGLE_LINE_KINDS = {"kopfzeile", "fusszeile", "seitenzahl", "titel"}
KEEP_SYMBOLS = {"-", "–", "—", "§", "&", "%", "*", "†", "‡", "¶", "/"}
FOOTNOTE_MARK_RE = re.compile(r"^\s*(?:\\?\*+|†|‡|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|\d{1,3}[\).]?|[a-z]\))(?:\s|$)")
PAGE_NUMBER_RE = re.compile(r"^[\s\[\(–—-]*(?:s\.|str\.|p\.)?\s*(?:\d{1,4}|[ivxlcdm]{1,7})[\s\]\)–—-]*$", re.I)
VOWELS = set("aeiouyąęóáéíúàèìòùâêîôûäöüæœAEIOUYĄĘÓÁÉÍÚÀÈÌÒÙÂÊÎÔÛÄÖÜÆŒ")


class LayoutWork(PageWork):
    def __init__(self, number: int):
        super().__init__(number)
        self.lpage: LPage | None = None
        self.region_items: dict[str, list[Item]] = {}
        self.region_tables: dict[str, tuple] = {}
        self.gridless: dict[str, bytes] = {}
        self.feats: feat_mod.PageFeatures | None = None
        self.color: np.ndarray | None = None
        self.binary: np.ndarray | None = None
        self.enhanced: np.ndarray | None = None


def _offset_line(line: Line, dx: int, dy: int) -> Line:
    words = [Word(w.text, w.conf, (w.bbox[0] + dx, w.bbox[1] + dy, w.bbox[2] + dx, w.bbox[3] + dy)) for w in line.words]
    x0, y0, x1, y1 = line.bbox
    return Line(words, (x0 + dx, y0 + dy, x1 + dx, y1 + dy), line.block, line.par)


def is_artifact(token: str) -> bool:
    """Zeichenfolge ohne Buchstaben und Ziffern, die aus Linien, Punkten oder Schmuck entsteht."""
    t = token.strip()
    return bool(t) and not re.search(r"\w", t) and t not in KEEP_SYMBOLS


def clean_line(line: Line) -> Line | None:
    words = [w for w in line.words if not is_artifact(w.text)]
    if not words:
        return None
    bbox = (min(w.bbox[0] for w in words), min(w.bbox[1] for w in words),
            max(w.bbox[2] for w in words), max(w.bbox[3] for w in words))
    return Line(words, bbox, line.block, line.par)


def _bbox_of(lines: list[Line]) -> tuple[int, int, int, int]:
    return (min(l.bbox[0] for l in lines), min(l.bbox[1] for l in lines), max(l.bbox[2] for l in lines),
            max(l.bbox[3] for l in lines))


def _overlaps(a, b) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _trim_box(box, obstacle):
    """Rahmen an einem bestehenden Bereich beschneiden; None, wenn er (fast) ganz darin liegt."""
    from quellenuebersetzer.runtime.layout import _trim

    ix = max(0, min(box[2], obstacle[2]) - max(box[0], obstacle[0]))
    iy = max(0, min(box[3], obstacle[3]) - max(box[1], obstacle[1]))
    if ix * iy > 0.6 * max(1, (box[2] - box[0]) * (box[3] - box[1])):
        return None
    return _trim(box, obstacle)


def _reading_order_words(words: list[Word]) -> list[Word]:
    """Wörter einer Zelle zeilenweise von oben nach unten, in der Zeile von links nach rechts."""
    words = sorted(words, key=lambda w: (w.bbox[1] + w.bbox[3]) / 2)
    rows: list[list[Word]] = []
    for w in words:
        h = max(1, w.bbox[3] - w.bbox[1])
        if rows and abs((w.bbox[1] + w.bbox[3]) / 2 - (rows[-1][0].bbox[1] + rows[-1][0].bbox[3]) / 2) < 0.6 * h:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [w for row in rows for w in sorted(row, key=lambda w: w.bbox[0])]


def _ocr_score(lines: list[Line]) -> float:
    """Summe der Sicherheit echter Wörter – bevorzugt Varianten mit mehr *und* sichereren Wörtern."""
    return sum(w.conf for ln in lines for w in ln.words if re.search(r"\w", w.text))


def _mean_conf(lines: list[Line]) -> float:
    confs = [w.conf for ln in lines for w in ln.words if re.search(r"\w", w.text)]
    return float(statistics.mean(confs)) if confs else -1.0


def garbage_ratio(text: str) -> float:
    """Anteil der Zeichenfolgen, die keine Wörter sein können (keine Vokale, Ziffern-Buchstaben-Gemisch …)."""
    tokens = [t for t in re.split(r"\s+", text) if re.search(r"\w", t)]
    if not tokens:
        return 0.0
    bad = 0
    for t in tokens:
        core = re.sub(r"[^\w]", "", t)
        if not core or core.isdigit() or re.fullmatch(r"[ivxlcdmIVXLCDM]+", core):
            continue
        letters = re.sub(r"[\d_]", "", core)
        if (len(core) >= 3 and not (set(core) & VOWELS)) or (letters and re.search(r"\d", core) and len(core) > 3):
            bad += 1
    return bad / len(tokens)


def _alignment(lines: list[Line], box: tuple[int, int, int, int]) -> str:
    if not lines:
        return "left"
    bw = max(1, box[2] - box[0])
    lefts = [ln.bbox[0] - box[0] for ln in lines]
    rights = [box[2] - ln.bbox[2] for ln in lines]
    if len(lines) == 1:
        l, r = lefts[0], rights[0]
        return "center" if abs(l - r) < bw * 0.08 and l > bw * 0.05 else "left"
    centered = sum(abs(l - r) < bw * 0.06 for l, r in zip(lefts, rights)) / len(lines)
    if centered > 0.7 and statistics.median(lefts) > bw * 0.04:
        return "center"
    flush_right = sum(r < bw * 0.03 for r in rights[:-1]) / max(1, len(rights) - 1)
    flush_left = sum(l < bw * 0.03 for l in lefts) / len(lines)
    if flush_right > 0.7 and flush_left > 0.6:
        return "justify"
    if flush_right > 0.7:
        return "right"
    return "left"


def _hex_lab(hexcolor: str) -> np.ndarray:
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return cv2.cvtColor(np.uint8([[[b, g, r]]]), cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]


def normalize_panel(color: np.ndarray, fill_hex: str) -> np.ndarray:
    """Hinterlegte Fläche → Graubild mit dunkler Schrift auf hellem Grund (Abstand zur Hintergrundfarbe).

    Funktioniert gleich für helle Schrift auf dunklem Grund, farbige Schrift auf farbigem Grund und
    dunkle Schrift auf hellem Kasten.
    """
    lab = cv2.cvtColor(color, cv2.COLOR_BGR2LAB).astype(np.float32)
    d = np.linalg.norm(lab - _hex_lab(fill_hex), axis=2)
    top = max(30.0, float(np.percentile(d, 99)))
    return (255 - np.clip(d / top * 255, 0, 255)).astype(np.uint8)


class LayoutReader(PageReader):
    def __init__(self, *args, detector: LayoutDetector, workdir: Path, workers: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        self.detector = detector
        self.workdir = workdir
        self.workers = max(1, workers)  # Seiten gleichzeitig (Prozessorkerne)
        self.geometry_reports: dict = {}
        if self.workers > 1 and self.tesseract:
            self.tesseract.threads = 1

    # ------------------------------------------------------------------ Phase 1: Seitenaufbau (ganzes Buch)
    def prepare_page(self, page: PageImage) -> tuple[int, int]:
        """Seitengeometrie: Seite finden und entzerren, Schräglage und Wölbung ausgleichen. → (Breite, Höhe)."""
        bg = self.workdir / f"hintergrund-{page.number:04d}.png"
        if bg.exists():  # beim Fortsetzen bereits aufbereitet
            with Image.open(bg) as im:
                return im.size
        data = np.fromfile(str(page.path), dtype=np.uint8)
        color = cv2.imdecode(data, cv2.IMREAD_COLOR)
        color, report = normalize_geometry(color)
        self.geometry_reports[page.number] = report
        save_png(color, bg)
        return color.shape[1], color.shape[0]

    def detect_page(self, page: PageImage, target_size: tuple[int, int] | None = None) -> LPage:
        """Seitenaufbau erkennen (nach der Aufbereitung, auf dem einheitlichen Format) – noch ohne Text."""
        bg_name = f"hintergrund-{page.number:04d}.png"
        self.prepare_page(page)
        data = np.fromfile(str(self.workdir / bg_name), dtype=np.uint8)
        color = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if target_size:
            fitted = fit_to(color, target_size)
            if fitted is not color:
                color = fitted
                save_png(color, self.workdir / bg_name)
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        lpage = LPage(page.number, w, h, page.dpi, bg_name, label=page.label)
        if not self.detector.available:
            return lpage
        # Stufe A: Merkmale (volle Auflösung, Farbe) und Modell auf dem Farbbild
        feats = feat_mod.analyse(color)
        raw = self.detector.detect_raw(cv2.cvtColor(color, cv2.COLOR_BGR2RGB))
        # Stufe B: Entscheidung aus allen Signalen
        regions, decorations = structure.build(raw, feats, feat_mod.text_ink(gray, feats), color)
        lpage.decorations = decorations
        for i, reg in enumerate(regions):
            rid = f"s{page.number}b{i + 1}"
            lr = LRegion(rid, reg.kind, tuple(int(v) for v in reg.box), i, container=reg.container)
            if reg.kind in IMAGE_KINDS:
                name = f"abbildung-{rid}.png"
                save_png(crop(color, reg.box, pad=0), self.workdir / name)
                lr.image = name
            lpage.regions.append(lr)
        return lpage

    # ------------------------------------------------------------------ Phase 2: Texterkennung je Bereich
    def _analyse(self, lpage: LPage) -> LayoutWork:
        work = LayoutWork(lpage.number)
        work.lpage = lpage
        data = np.fromfile(str(self.workdir / lpage.background), dtype=np.uint8)
        color = cv2.imdecode(data, cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        work.color = color
        feats = feat_mod.analyse(color)
        work.feats = feats
        enhanced = enhance(flatten(gray))
        # hinterlegte Kästen: in dunkle Schrift auf hellem Grund umrechnen (je Kasten, nicht seitenweit)
        for d in lpage.decorations:
            if not d.get("fill"):
                continue
            x0, y0, x1, y1 = d["box"]
            enhanced[y0:y1, x0:x1] = enhance(normalize_panel(color[y0:y1, x0:x1], d["fill"]))
        binary = binarize(enhanced)
        if feats.line_mask is not None:
            binary[feats.line_mask > 0] = 255  # Linien sind Grafik, kein Text
        work.binary, work.enhanced = binary, enhanced
        h, w = gray.shape
        covered = np.zeros_like(binary, dtype=bool)
        for lr in lpage.regions:
            x0, y0, x1, y1 = lr.box
            covered[y0:y1, x0:x1] = True
            if lr.kind in IMAGE_KINDS:
                continue
            if lr.kind == "tabelle":
                self._analyse_table(work, lr, enhanced, binary)
            else:
                self._analyse_text(work, lr, enhanced, binary)

        # Sicherheitsnetz: Text außerhalb aller erkannten Bereiche (ohne Linien und Schmuck)
        if self.tesseract and self.kind != SourceKind.HANDSCHRIFT:
            masked = binary.copy()
            masked[covered] = 255
            if (masked < 128).sum() > 150:  # schon zwei kurze Randzeilen zählen
                rest = self.tesseract.run_tsv(masked, self.langs, psm=3)
                groups: dict[tuple[int, int], list[Line]] = {}
                for ln in rest.lines:
                    ln = clean_line(ln)
                    if ln and len(re.sub(r"\W", "", ln.text)) > 1 and _mean_conf([ln]) >= 40:
                        groups.setdefault((ln.block, ln.par), []).append(ln)
                caught = 0
                pieces: list[list[Line]] = []
                for g in groups.values():
                    # ein aufgefangener Bereich darf keinen bestehenden überlappen: notfalls zeilenweise
                    bx = _bbox_of(g)
                    if any(_overlaps(bx, r.box) for r in lpage.regions):
                        pieces.extend([l] for l in g)
                    else:
                        pieces.append(g)
                for g in pieces:
                    bx = _bbox_of(g)
                    for r in lpage.regions:
                        if bx and _overlaps(bx, r.box):
                            bx = _trim_box(bx, r.box)
                    if bx is None:
                        continue  # liegt in einem erkannten Bereich – dessen Lesung enthält den Text
                    center = ((bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2)
                    container = next((d["id"] for d in lpage.decorations
                                      if d["box"][0] <= center[0] <= d["box"][2]
                                      and d["box"][1] <= center[1] <= d["box"][3]), "")
                    at_margin = center[0] < w * 0.15 or center[0] > w * 0.85
                    kind = "randnotiz" if at_margin and not container and _mean_conf(g) >= 60 else "absatz"
                    rid = f"s{lpage.number}b{len(lpage.regions) + 1}"
                    lr = LRegion(rid, kind, bx, len(lpage.regions), container=container)
                    lpage.regions.append(lr)
                    items = [Item(crop(enhanced, l.bbox, pad=8), line=l, bbox=l.bbox, group=(0, 0),
                                  need_second=self.strict or l.min_conf < fusion.CONF_SECOND) for l in g]
                    work.region_items[rid] = items
                    lr.line_px = statistics.median(l.height for l in g)
                    lr.lines = len(g)
                    lr.erase_boxes = [l.bbox for l in g]
                    lr.conf = _mean_conf(g)
                    caught += 1
                if caught:
                    lpage.issues.append(f"{caught} Textstelle(n) lagen außerhalb der erkannten Bereiche "
                                        "und wurden nachträglich aufgenommen – Lesereihenfolge prüfen.")
        work.items = [it for its in work.region_items.values() for it in its]
        work.tables = [(t, cells) for t, cells in work.region_tables.values()]
        return work

    def _ocr_region(self, box, binary, enhanced, psm: int, line_mask: np.ndarray | None = None) -> list[Line]:
        """Bereich lesen; bei schwacher Sicherheit zweite Bildvariante (Otsu) versuchen, bessere behalten."""
        x0, y0, x1, y1 = box
        dx, dy = max(0, x0 - 6), max(0, y0 - 6)
        sub = crop(binary, box, pad=6)
        lines = [clean_line(_offset_line(ln, dx, dy)) for ln in self.tesseract.run_tsv(sub, self.langs, psm=psm).lines]
        lines = [ln for ln in lines if ln]
        if _mean_conf(lines) >= 70 or sub.size == 0:
            return lines
        alt_src = crop(enhanced, box, pad=6)
        _t, alt = cv2.threshold(alt_src, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if line_mask is not None:
            alt[crop(line_mask, box, pad=6) > 0] = 255  # entfernte Linien bleiben entfernt
        lines2 = [clean_line(_offset_line(ln, dx, dy)) for ln in self.tesseract.run_tsv(alt, self.langs, psm=psm).lines]
        lines2 = [ln for ln in lines2 if ln]
        return lines2 if _ocr_score(lines2) > _ocr_score(lines) * 1.05 else lines

    def _analyse_text(self, work: LayoutWork, lr: LRegion, enhanced, binary) -> None:
        x0, y0, x1, y1 = lr.box
        if self.kind == SourceKind.HANDSCHRIFT:
            sub = crop(binary, lr.box, pad=0)
            boxes = [(a + x0, b + y0, c + x0, d + y0) for a, b, c, d in segment_lines(sub, min_height=8)]
            items = [Item(crop(enhanced, b, pad=10), bbox=b, need_second=True, group=(0, 0)) for b in boxes]
            work.region_items[lr.id] = items
            lr.lines = len(boxes)
            lr.line_px = statistics.median(b[3] - b[1] for b in boxes) if boxes else (y1 - y0)
            lr.erase_boxes = boxes or [lr.box]
            if work.thumb is None:
                work.thumb = cv2.resize(enhanced, None, fx=0.35, fy=0.35, interpolation=cv2.INTER_AREA)
            return
        psm = 7 if lr.kind in SINGLE_LINE_KINDS and (y1 - y0) < 140 else 6
        mask = work.feats.line_mask if work.feats else None
        lines = self._ocr_region(lr.box, binary, enhanced, psm, mask) if self.tesseract else []
        items = [Item(crop(enhanced, ln.bbox, pad=8), line=ln, bbox=ln.bbox, group=(0, 0),
                      need_second=self.strict or ln.min_conf < fusion.CONF_SECOND) for ln in lines]
        if not lines and (crop(binary, lr.box, pad=0) < 128).mean() > 0.01:
            # nichts erkannt, aber Schrift vorhanden: ganzen Bereich vom Lesemodell lesen lassen
            items = [Item(crop(enhanced, lr.box, pad=4), bbox=lr.box, need_second=True, group=(0, 0))]
        work.region_items[lr.id] = items
        lr.lines = len(lines)
        lr.conf = _mean_conf(lines)
        lr.line_px = statistics.median(ln.height for ln in lines) if lines else (y1 - y0) * 0.8
        lr.align = _alignment(lines, lr.box)
        lr.bold = lr.kind in ("titel", "ueberschrift")
        lr.erase_boxes = [ln.bbox for ln in lines] or [lr.box]
        if lines and work.color is not None:
            style = measure_style(crop(work.color, lr.box, pad=0), crop(binary, lr.box, pad=0), lr.line_px)
            lr.color, lr.italic, lr.spaced, lr.stroke = style.color, style.italic, style.spaced, style.stroke

    # ------------------------------------------------------------------ Tabellen
    def _analyse_table(self, work: LayoutWork, lr: LRegion, enhanced, binary) -> None:
        x0, y0, x1, y1 = lr.box
        scale = work.lpage.width_px / 2480.0
        rules = work.feats.rules_in(lr.box, margin=int(14 * scale) + 4) if work.feats else []
        t = table_from_rules(lr.box, rules, tol=max(6, int(14 * scale)))
        mask = work.feats.line_mask if work.feats else None
        if t:
            # die ganze Tabelle in EINEM Aufruf lesen (Linien sind schon entfernt) und die Wörter nach ihrer
            # Lage den Zellen zuordnen – statt eines Programmstarts je Zelle
            table_lines = self._ocr_region(lr.box, binary, enhanced, 6, mask) if self.tesseract else []
            self._fill_cells(work, lr, t, [wd for ln in table_lines for wd in ln.words], enhanced, binary, mask)
        else:
            # Tabelle ohne (senkrechte) Linien: Zeilen aus waagrechten Linien oder Farbbändern, Spalten aus
            # hinterlegten Spalten oder Wortlücken – so bleibt eine mehrzeilige Zelle eine Zelle
            lines = self._ocr_region(lr.box, binary, enhanced, 6, mask) if self.tesseract else []
            banded = self._grid_from_bands(work, lr.box, rules, lines, scale)
            if banded is not None:
                t = banded
                self._fill_cells(work, lr, t, [wd for ln in lines for wd in ln.words], enhanced, binary, mask)
                lr.conf = _mean_conf(lines)
                built = None
            else:
                built = table_from_words(lines)
        if t is None:
            if built is None:
                # keine Tabellenstruktur erkennbar → als normaler Text lesen (statt Inhalte zu raten)
                lr.kind = "absatz"
                self._analyse_text(work, lr, enhanced, binary)
                return
            t, cell_words = built
            cells_items = []
            for cell in t.cells:
                words = cell_words.get((cell.row, cell.col))
                if not words or not cell.bbox:
                    continue
                line = Line(words, cell.bbox, 0, 0)
                need = self.strict or line.min_conf < fusion.CONF_SECOND
                cells_items.append(Item(crop(enhanced, cell.bbox, pad=4), line=line, need_second=need,
                                        bbox=cell.bbox, cell=cell))
            lr.erase_boxes = [ln.bbox for ln in lines] or [lr.box]
            work.region_tables[lr.id] = (t, cells_items)
            lr.conf = _mean_conf(lines)
        row_boxes: dict[int, tuple[int, int, int, int]] = {}  # ganze Tabellenzeilen (Vereinigung der Zellen)
        for c in t.cells:
            if c.bbox and c.rowspan == 1:
                b = row_boxes.get(c.row)
                row_boxes[c.row] = c.bbox if b is None else (min(b[0], c.bbox[0]), min(b[1], c.bbox[1]),
                                                              max(b[2], c.bbox[2]), max(b[3], c.bbox[3]))
        if self._header_evidence(work, t, row_boxes, rules):
            for c in t.cells:
                c.header = c.row == 0
        lr.line_px = 0.0

    def _fill_cells(self, work: LayoutWork, lr: LRegion, t: Table, table_words: list[Word], enhanced, binary,
                    mask) -> None:
        """Wörter der in einem Aufruf gelesenen Tabelle nach ihrer Lage den Zellen zuordnen."""
        by_cell: dict[int, list[Word]] = {}
        for wd in table_words:
            cx, cy = (wd.bbox[0] + wd.bbox[2]) / 2, (wd.bbox[1] + wd.bbox[3]) / 2
            k = next((k for k, c in enumerate(t.cells)
                      if c.bbox[0] <= cx < c.bbox[2] and c.bbox[1] <= cy < c.bbox[3]), None)
            if k is not None:
                by_cell.setdefault(k, []).append(wd)
        cells_items = []
        for k, cell in enumerate(t.cells):
            inner = (cell.bbox[0] + 4, cell.bbox[1] + 4, cell.bbox[2] - 4, cell.bbox[3] - 4)
            if inner[2] <= inner[0] or inner[3] <= inner[1]:
                continue
            c_bin = crop(binary, inner, pad=0)
            if c_bin.size == 0 or (c_bin < 128).mean() < 0.003:
                continue
            words = by_cell.get(k)
            if words:
                words = _reading_order_words(words)
            elif self.tesseract:
                # Schrift in der Zelle, aber kein Wort zugeordnet → Zelle einzeln nachlesen (Vollständigkeit)
                single = (inner[3] - inner[1]) < max(60, 2.2 * self._line_h(c_bin))
                lines = self._ocr_region(inner, binary, enhanced, 7 if single else 6, mask)
                words = [wd for ln in lines for wd in ln.words]
            line = Line(words, inner, 0, 0) if words else None
            need = line is None or self.strict or line.min_conf < fusion.CONF_SECOND or (
                any(ch.isdigit() for ch in line.text) and line.min_conf < fusion.CONF_OK)
            cells_items.append(Item(crop(enhanced, inner, pad=0), line=line, need_second=need, bbox=inner,
                                    cell=cell))
            lr.erase_boxes.append(inner)
        work.region_tables[lr.id] = (t, cells_items)

    def _grid_from_bands(self, work: LayoutWork, box, rules, lines: list[Line], scale: float) -> Table | None:
        """Zellraster einer Tabelle ohne senkrechte Linien.

        Zeilen: waagrechte Linien oder – ohne Linien – Farbbänder (Zebrazeilen); innerhalb eines Bandes nur
        dann weiter geteilt, wenn alle Spalten gleich viele Textzeilen auf gleicher Höhe haben.
        Spalten: hinterlegte Spalten oder Wortlücken. Ohne Zeilen-Belege → None (bisheriges Verfahren).
        """
        from quellenuebersetzer.pipeline.features import Rule
        from quellenuebersetzer.pipeline.tables import shading_cuts, split_rows_in_band, word_columns

        words = [w for ln in lines for w in ln.words if w.text.strip()]
        if len(words) < 4 or work.color is None:
            return None
        x0, y0, x1, y1 = box
        line_h = float(statistics.median(w.bbox[3] - w.bbox[1] for w in words))
        tol = max(6, int(10 * scale))
        hcuts = sorted(r.pos for r in rules if r.orient == "h" and r.length > 0.6 * (x1 - x0)
                       and y0 + tol < r.pos < y1 - tol)
        color = crop(work.color, box, pad=0)
        ink = (crop(work.binary, box, pad=0) < 128)

        def free_h(y: int) -> bool:  # keine Textzeile wird von der Grenze durchschnitten
            return not any(w.bbox[1] + 0.25 * line_h < y < w.bbox[3] - 0.25 * line_h for w in words)

        def free_v(x: int) -> bool:
            return not any(w.bbox[0] + 2 < x < w.bbox[2] - 2 for w in words)

        vcuts: list[int] = []
        if not hcuts:
            bands = [y0 + c for c in shading_cuts(color, ink, 0, max(int(1.2 * line_h), 20))]
            bands = [y for y in bands if free_h(y)]
            if len(bands) >= 2:
                hcuts = bands  # Zebrazeilen
            else:
                vbands = [x0 + c for c in shading_cuts(color, ink, 1, max(int(3 * line_h), 40))]
                vbands = [x for x in vbands if free_v(x)]
                if len(vbands) < 2:
                    return None
                vcuts = vbands  # hinterlegte Spalten; Zeilen dann aus den Textzeilen
                centers = sorted((w.bbox[1] + w.bbox[3]) / 2 for w in words)
                groups: list[list[float]] = []
                for c in centers:
                    if groups and c - groups[-1][-1] < 0.6 * line_h:
                        groups[-1].append(c)
                    else:
                        groups.append([c])
                mids = [sum(g) / len(g) for g in groups]
                hcuts = [int((a + b) / 2) for a, b in zip(mids, mids[1:])]
        if not hcuts:
            return None
        if not vcuts:
            cols = word_columns(lines)
            vcuts = [x for x in ((a[1] + b[0]) // 2 for a, b in zip(cols, cols[1:])) if free_v(x)]
        if not vcuts:
            return None
        col_bounds = [x0] + vcuts + [x1]
        bounds = [y0] + hcuts + [y1]
        extra = []
        for a, b in zip(bounds, bounds[1:]):
            extra += split_rows_in_band(words, a, b, col_bounds, line_h)
        synthetic = [Rule("h", x0, y, x1, y + 1, "solid", 1, "#000000") for y in sorted(hcuts + extra)]
        synthetic += [Rule("v", x, y0, x + 1, y1, "solid", 1, "#000000") for x in vcuts]
        return table_from_rules(box, synthetic, tol=tol)

    @staticmethod
    def _line_h(binary_crop: np.ndarray) -> float:
        rows = (binary_crop < 128).any(axis=1)
        return float(rows.sum()) or 30.0

    def _header_evidence(self, work: LayoutWork, t: Table, row_boxes: dict, rules) -> bool:
        """Kopfzeile nur mit Beleg: fett, hinterlegt oder durch eine kräftigere Linie abgesetzt."""
        if t.n_rows < 2 or 0 not in row_boxes or work.color is None:
            return False
        first = row_boxes[0]
        rest = [b for r, b in row_boxes.items() if r > 0]
        if not rest:
            return False
        # 1. kräftigere Linie unter der ersten Zeile
        hs = [r for r in rules if r.orient == "h"]
        boundary = (first[3] + min(b[1] for b in rest)) / 2
        tol = max(12, (min(b[1] for b in rest) - first[3]))
        under = [r for r in hs if abs(r.pos - boundary) <= tol]
        others = [r for r in hs if r not in under and first[1] - 4 < r.pos]
        if under:
            base = statistics.median([r.thickness for r in others]) if others else 0
            if not others or max(r.thickness for r in under) >= 1.6 * base:
                return True
        # 2. Hinterlegung
        def bg(box):
            sub = crop(work.color, box, pad=0)
            ink = crop(work.binary, box, pad=0) < 128
            px = sub[~ink] if sub.size else np.empty((0, 3))
            return np.median(px.reshape(-1, 3), axis=0) if len(px) else None

        b0 = bg(first)
        brest = [bg(b) for b in rest[:4]]
        brest = [b for b in brest if b is not None]
        if b0 is not None and brest:
            lab0 = cv2.cvtColor(np.uint8([[b0]]), cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]
            labr = cv2.cvtColor(np.uint8([[np.median(brest, axis=0)]]), cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]
            if np.linalg.norm(lab0 - labr) > 8:
                return True
        # 3. Fettdruck
        def stroke(box):
            ink = (crop(work.binary, box, pad=0) < 128).astype(np.uint8)
            return stroke_ratio(ink, 40.0)

        s0 = stroke(first)
        srest = [s for s in (stroke(b) for b in rest) if s > 0]
        return bool(s0 and srest and s0 > 1.1 * statistics.median(srest) and s0 > 1.05 * max(srest))

    # ------------------------------------------------------------------ 4. Zusammenführen je Bereich
    def _compose(self, w: LayoutWork):
        for rid, (table, cells) in w.region_tables.items():
            for it in cells:
                self._fuse_item(it)
                it.cell.markdown = it.markdown
            region = next(r for r in w.lpage.regions if r.id == rid)
            region.source_md = table.to_html()
            region.issues.extend(table.plausibility())
        for region in w.lpage.regions:
            items = w.region_items.get(region.id)
            if items is None:
                continue
            if self.kind == SourceKind.HANDSCHRIFT:
                region.source_md = self._compose_hw_region(items)
                continue
            lines_md = []
            for it in items:
                if it.line is None and not it.other:
                    continue
                self._fuse_item(it)
                lines_md.append(it.markdown)
            region.source_md = fusion.join_lines(lines_md)
        w.lpage.regions = [r for r in w.lpage.regions
                           if r.kind in IMAGE_KINDS or r.source_md.strip() or r.kind == "tabelle"]
        if self.kind != SourceKind.HANDSCHRIFT:
            for r in w.lpage.regions:
                self._check_structure(w, r)
                self._quality_gate(r)
        # fett = deutlich kräftiger als der übliche Text dieser Seite (z. B. fette Zwischenüberschriften)
        # nur Bereiche mit genug Text vergleichen (Seitenzahlen o. ä. geben kein verlässliches Strichbild)
        texts = [r for r in w.lpage.regions if r.is_text and len(markup_plain(r.source_md)) >= 8]
        for r, is_bold in zip(texts, bold_flags([r.stroke for r in texts])):
            r.bold = r.bold or is_bold
        return w.lpage

    def _check_structure(self, w: LayoutWork, r: LRegion) -> None:
        """Strukturelemente nur mit Beleg – sonst als gewöhnlicher Text behandeln."""
        text = unescape_md(markup_plain(r.source_md)).strip()
        if r.kind == "fussnote":
            rule_above = any(
                ru.orient == "h" and r.box[1] - 3 * max(20.0, r.line_px) <= ru.pos <= r.box[1] + 4
                and ru.x1 > r.box[0] and ru.x0 < r.box[2]
                for ru in (w.feats.rules if w.feats else []))
            if not (FOOTNOTE_MARK_RE.match(text) or rule_above):
                r.kind = "absatz"
        elif r.kind == "seitenzahl" and not PAGE_NUMBER_RE.match(text):
            r.kind = "fusszeile" if r.box[1] > w.lpage.height_px * 0.85 else (
                "kopfzeile" if r.box[3] < w.lpage.height_px * 0.15 else "absatz")

    def _quality_gate(self, r: LRegion) -> None:
        """Unlesbares wird markiert und gemeldet, statt als Zeichenmüll übersetzt zu werden."""
        if r.kind in IMAGE_KINDS or r.kind == "tabelle" or not r.source_md.strip():
            return
        text = unescape_md(markup_plain(r.source_md))
        ratio = garbage_ratio(text)
        n = len(text.split())
        if (n >= 3 and ratio > 0.5) or (0 <= r.conf < 35 and n >= 3):
            r.issues.append(f"Bereich unlesbar (Lesesicherheit {max(0, r.conf):.0f} %) – nicht übersetzt.")
            r.source_md = mark_illegible()
        elif 0 <= r.conf < fusion.CONF_LOW or ratio > 0.2:
            r.issues.append(f"Geringe Lesesicherheit ({max(0, r.conf):.0f} %) – Text prüfen.")

    def _compose_hw_region(self, items: list[Item]) -> str:
        out = []
        for it in items:
            if it.first is None:
                out.append(mark_reading("[?]", ["[?]"], 0.0))
                continue
            words = it.first.word_confidences()
            if not words:
                continue
            pseudo = Line([Word(t, p * 100, it.bbox) for t, p in words], it.bbox, 0, 0)
            fused = fusion.fuse_line(pseudo, it.other, None, strict=True) if it.other else None
            md = fused.markdown if fused and fused.marks else fusion.mark_by_confidence(words, threshold=0.45)[0]
            out.append(md)
        return fusion.join_lines(out)

    def analyse_pages(self, lpages: list[LPage]) -> list[LayoutWork]:
        """Phase 2a (Prozessor, mehrere Seiten gleichzeitig): Bereiche vorbereiten und mit Tesseract lesen."""
        from quellenuebersetzer.pipeline.parallel import pmap

        return list(pmap(self._analyse_light, lpages, self.workers))

    def _analyse_light(self, lpage: LPage) -> LayoutWork:
        work = self._analyse(lpage)
        # große Bildspeicher sofort freigeben – nur Zeilenausschnitte und Linien werden weiter gebraucht
        work.color = work.binary = work.enhanced = None
        if work.feats is not None:
            work.feats.line_mask = None
        return work

    def finish_pages(self, works: list[LayoutWork]) -> list[LPage]:
        """Phase 2b (Grafikkarte): Zweitlesung unsicherer Stellen, dann Zusammenführen je Bereich."""
        if self.kind == SourceKind.HANDSCHRIFT:
            self._pass_handwriting_first(works)
        self._pass_glm(works)
        out = [self._compose(w) for w in works]
        for w in works:
            w.feats = None
        for lp in out:
            lp.read = True
        return out

    def read_regions(self, lpages: list[LPage]) -> list[LPage]:
        """Phase 2 für bereits erkannte Seiten: Text je Bereich lesen (in Durchgängen je Modell)."""
        return self.finish_pages(self.analyse_pages(lpages))

    def read_layout(self, pages: list[PageImage]) -> list[LPage]:
        """Beide Phasen für wenige Seiten am Stück (z. B. Tests)."""
        return self.read_regions([self.detect_page(p) for p in pages])


__all__ = ["LayoutReader", "_char_width", "garbage_ratio", "is_artifact"]
