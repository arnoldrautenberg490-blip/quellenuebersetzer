"""Lesen für die Layoutkopie: Seitenaufbau erkennen, jeden Bereich mit dem passenden Werkzeug lesen.

Nutzt die Durchgänge des ``PageReader`` (Tesseract → GLM-OCR → Gemma-Schiedsrichter), aber pro Bereich.
Text, der in keinem erkannten Bereich liegt, wird über Tesseract aufgefangen (nichts geht verloren).
"""

from __future__ import annotations

import statistics
from pathlib import Path

import cv2
import numpy as np

from quellenuebersetzer.pipeline import fusion
from quellenuebersetzer.pipeline.document import PageImage
from PIL import Image

from quellenuebersetzer.pipeline.layout_doc import IMAGE_KINDS, LPage, LRegion
from quellenuebersetzer.pipeline.pagegeom import fit_to, normalize_geometry
from quellenuebersetzer.pipeline.markup import mark_reading
from quellenuebersetzer.pipeline.preprocess import (
    binarize,
    crop,
    enhance,
    estimate_skew,
    load_gray,
    save_png,
)
from quellenuebersetzer.pipeline.reading import Item, PageReader, PageWork, _char_width, parse_table_output, segment_lines
from quellenuebersetzer.pipeline.tables import detect_ruled_tables, table_from_words
from quellenuebersetzer.pipeline.markup import strip_marks as markup_plain
from quellenuebersetzer.pipeline.typography import bold_flags
from quellenuebersetzer.pipeline.typography import measure as measure_style
from quellenuebersetzer.profile import SourceKind
from quellenuebersetzer.runtime.layout import LayoutDetector, Region
from quellenuebersetzer.runtime.ollama import OllamaError
from quellenuebersetzer.runtime.tesseract import Line, OcrPage

SINGLE_LINE_KINDS = {"kopfzeile", "fusszeile", "seitenzahl", "titel"}


class LayoutWork(PageWork):
    def __init__(self, number: int):
        super().__init__(number)
        self.lpage: LPage | None = None
        self.region_items: dict[str, list[Item]] = {}
        self.region_tables: dict[str, tuple] = {}
        self.gridless: dict[str, bytes] = {}


def _offset_line(line: Line, dx: int, dy: int) -> Line:
    from quellenuebersetzer.runtime.tesseract import Word

    words = [Word(w.text, w.conf, (w.bbox[0] + dx, w.bbox[1] + dy, w.bbox[2] + dx, w.bbox[3] + dy)) for w in line.words]
    x0, y0, x1, y1 = line.bbox
    return Line(words, (x0 + dx, y0 + dy, x1 + dx, y1 + dy), line.block, line.par)


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


class LayoutReader(PageReader):
    def __init__(self, *args, detector: LayoutDetector, workdir: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self.detector = detector
        self.workdir = workdir
        self.geometry_reports: dict = {}

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
        regions: list[Region] = self.detector.detect(gray) if self.detector.available else []
        for i, reg in enumerate(regions):
            rid = f"s{page.number}b{i + 1}"
            lr = LRegion(rid, reg.kind, reg.box, reg.order)
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
        enhanced = enhance(gray)
        binary = binarize(enhanced)
        h, w = gray.shape
        covered = np.zeros_like(binary, dtype=bool)
        for lr in lpage.regions:
            x0, y0, x1, y1 = lr.box
            covered[y0:y1, x0:x1] = True
            if lr.kind in IMAGE_KINDS:
                continue
            if lr.kind == "tabelle":
                self._analyse_table(work, lr, gray, enhanced, binary)
            else:
                self._analyse_text(work, lr, enhanced, binary)

        # Sicherheitsnetz: Text außerhalb aller erkannten Bereiche
        if self.tesseract and self.kind != SourceKind.HANDSCHRIFT:
            masked = binary.copy()
            masked[covered] = 255
            rest = self.tesseract.run_tsv(masked, self.langs, psm=3)
            groups: dict[tuple[int, int], list[Line]] = {}
            for ln in rest.lines:
                if ln.text.strip() and len(ln.text.strip()) > 1:
                    groups.setdefault((ln.block, ln.par), []).append(ln)
            for g in groups.values():
                bx = (min(l.bbox[0] for l in g), min(l.bbox[1] for l in g), max(l.bbox[2] for l in g), max(l.bbox[3] for l in g))
                center = (bx[0] + bx[2]) / 2
                kind = "randnotiz" if center < w * 0.15 or center > w * 0.85 else "absatz"
                rid = f"s{lpage.number}b{len(lpage.regions) + 1}"
                lr = LRegion(rid, kind, bx, len(lpage.regions))
                lpage.regions.append(lr)
                items = [Item(crop(enhanced, l.bbox, pad=8), line=l, bbox=l.bbox, group=(0, 0),
                              need_second=self.strict or l.min_conf < fusion.CONF_SECOND) for l in g]
                work.region_items[rid] = items
                lr.line_px = statistics.median(l.height for l in g)
                lr.lines = len(g)
                lr.erase_boxes = [l.bbox for l in g]
        work.items = [it for its in work.region_items.values() for it in its]
        work.tables = [(t, cells) for t, cells in work.region_tables.values()]
        return work

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
        sub = crop(binary, lr.box, pad=6)
        psm = 7 if lr.kind in SINGLE_LINE_KINDS and (y1 - y0) < 140 else 6
        ocr = self.tesseract.run_tsv(sub, self.langs, psm=psm) if self.tesseract else OcrPage()
        dx, dy = max(0, x0 - 6), max(0, y0 - 6)
        lines = [_offset_line(ln, dx, dy) for ln in ocr.lines]
        items = [Item(crop(enhanced, ln.bbox, pad=8), line=ln, bbox=ln.bbox, group=(0, 0),
                      need_second=self.strict or ln.min_conf < fusion.CONF_SECOND) for ln in lines]
        if not lines:
            # nichts erkannt: ganzen Bereich vom Lesemodell lesen lassen
            items = [Item(crop(enhanced, lr.box, pad=4), bbox=lr.box, need_second=True, group=(0, 0))]
        work.region_items[lr.id] = items
        lr.lines = len(lines)
        lr.line_px = statistics.median(ln.height for ln in lines) if lines else (y1 - y0) * 0.8
        lr.align = _alignment(lines, lr.box)
        lr.bold = lr.kind in ("titel", "ueberschrift")
        lr.erase_boxes = [ln.bbox for ln in lines] or [lr.box]
        if lines and getattr(work, "color", None) is not None:
            style = measure_style(crop(work.color, lr.box, pad=0), crop(binary, lr.box, pad=0), lr.line_px)
            lr.color, lr.italic, lr.spaced, lr.stroke = style.color, style.italic, style.spaced, style.stroke

    def _analyse_table(self, work: LayoutWork, lr: LRegion, gray, enhanced, binary) -> None:
        x0, y0, x1, y1 = lr.box
        tables = detect_ruled_tables(crop(gray, lr.box, pad=0), min_cells=2)
        if tables:
            t = tables[0]
            cells_items = []
            for cell in t.cells:
                cx0, cy0, cx1, cy1 = cell.bbox
                cell.bbox = (cx0 + x0, cy0 + y0, cx1 + x0, cy1 + y0)
                inner = (cell.bbox[0] + 4, cell.bbox[1] + 4, cell.bbox[2] - 4, cell.bbox[3] - 4)
                if inner[2] <= inner[0] or inner[3] <= inner[1]:
                    continue
                c_bin = crop(binary, inner, pad=0)
                if c_bin.size == 0 or (c_bin < 128).mean() < 0.003:
                    continue
                ocr = self.tesseract.run_tsv(c_bin, self.langs, psm=6) if self.tesseract else OcrPage()
                words = [wd for ln in ocr.lines for wd in ln.words]
                line = Line(words, inner, 0, 0) if words else None
                need = line is None or self.strict or line.min_conf < fusion.CONF_SECOND or (
                    any(ch.isdigit() for ch in line.text) and line.min_conf < fusion.CONF_OK)
                cells_items.append(Item(crop(enhanced, inner, pad=0), line=line, need_second=need, bbox=inner, cell=cell))
                lr.erase_boxes.append(inner)
            work.region_tables[lr.id] = (t, cells_items)
        else:
            # Tabelle ohne Linien: aus Tesseract-Wortpositionen aufbauen (nichts wird „erfunden“);
            # das Lesemodell liest höchstens einzelne unsichere Zellen gegen.
            sub = crop(binary, lr.box, pad=6)
            ocr = self.tesseract.run_tsv(sub, self.langs, psm=6) if self.tesseract else OcrPage()
            dx, dy = max(0, x0 - 6), max(0, y0 - 6)
            lines = [_offset_line(ln, dx, dy) for ln in ocr.lines]
            built = table_from_words(lines)
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
        lr.line_px = 0.0

    # ------------------------------------------------------------------ 4. Zusammenführen je Bereich
    def _compose(self, w: LayoutWork):
        for rid, (table, cells) in w.region_tables.items():
            for it in cells:
                self._fuse_item(it)
                it.cell.markdown = it.markdown
            region = next(r for r in w.lpage.regions if r.id == rid)
            region.source_md = table.to_html()
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
        # fett = deutlich kräftiger als der übliche Text dieser Seite (z. B. fette Zwischenüberschriften)
        # nur Bereiche mit genug Text vergleichen (Seitenzahlen o. ä. geben kein verlässliches Strichbild)
        texts = [r for r in w.lpage.regions if r.is_text and len(markup_plain(r.source_md)) >= 8]
        for r, is_bold in zip(texts, bold_flags([r.stroke for r in texts])):
            r.bold = r.bold or is_bold
        return w.lpage

    def _compose_hw_region(self, items: list[Item]) -> str:
        from quellenuebersetzer.runtime.tesseract import Word

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

    def read_regions(self, lpages: list[LPage]) -> list[LPage]:
        """Phase 2 für bereits erkannte Seiten: Text je Bereich lesen (in Durchgängen je Modell)."""
        works = [self._analyse(lp) for lp in lpages]
        if self.kind == SourceKind.HANDSCHRIFT:
            self._pass_handwriting_first(works)
        self._pass_glm(works)
        out = [self._compose(w) for w in works]
        for lp in out:
            lp.read = True
        return out

    def read_layout(self, pages: list[PageImage]) -> list[LPage]:
        """Beide Phasen für wenige Seiten am Stück (z. B. Tests)."""
        return self.read_regions([self.detect_page(p) for p in pages])


__all__ = ["LayoutReader", "_char_width"]
