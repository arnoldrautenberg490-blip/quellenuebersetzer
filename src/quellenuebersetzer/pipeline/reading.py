"""Seiten lesen – je nach Quellenart mit unterschiedlicher Kombination der Leser.

Die Arbeit läuft in Durchgängen, damit die Grafikkarte nicht ständig zwischen Modellen wechselt:

  1. Analyse     – Bildaufbereitung, Tesseract, Tabellenraster, Zeilenzerlegung (ohne Sprachmodelle)
  2. Lesemodell  – GLM-OCR liest alle Zeilen/Zellen, die eine Zweitlesung brauchen
  3. Hauptmodell – Gemma 4 entscheidet strittige Stellen bzw. liest Handschrift
  4. Zusammenführen → Markdown-Blöcke mit Markierungen

Für Handschrift sind Schritt 2 und 3 vertauscht (Hauptmodell liest zuerst, GLM-OCR liefert die Zweitlesung).
"""

from __future__ import annotations

import html
import re
import statistics
from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from quellenuebersetzer.pipeline import fusion
from quellenuebersetzer.pipeline.document import Block, PageImage
from quellenuebersetzer.pipeline.markup import escape_md, mark_reading
from quellenuebersetzer.pipeline.preprocess import binarize, crop, encode_png, prepare_page
from quellenuebersetzer.pipeline.readers import GlmOcr, Reading, VisionJudge
from quellenuebersetzer.pipeline.tables import Cell, Table, detect_ruled_tables
from quellenuebersetzer.profile import SourceKind
from quellenuebersetzer.runtime.ollama import OllamaError
from quellenuebersetzer.runtime.tesseract import Line, OcrPage, Tesseract, Word


@dataclass
class PageResult:
    blocks: list[Block] = field(default_factory=list)
    marks: int = 0
    words: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class Item:
    """Eine Zeile oder Tabellenzelle, die gelesen und ggf. abgeglichen wird."""

    crop: np.ndarray
    line: Line | None = None  # Tesseract-Lesung (Druck)
    need_second: bool = False
    other: str | None = None  # Zweitlesung (GLM-OCR oder zweiter Handschrift-Durchgang)
    first: Reading | None = None  # Erstlesung Handschrift
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    group: tuple[int, int] = (0, 0)
    cell: Cell | None = None
    markdown: str = ""
    marks: int = 0
    words: int = 0


@dataclass
class PageWork:
    number: int
    items: list[Item] = field(default_factory=list)
    tables: list[tuple[Table, list[Item]]] = field(default_factory=list)
    gridless_table_png: bytes | None = None
    gridless_table: Block | None = None
    median_h: float = 20.0
    median_cw: float = 10.0
    thumb: np.ndarray | None = None
    notes: list[str] = field(default_factory=list)


Status = Callable[[str], None]



class PageReader:
    def __init__(
        self,
        kind: SourceKind,
        tesseract: Tesseract | None,
        tess_langs: list[str],
        glm: GlmOcr | None,
        judge: VisionJudge | None,
        period_label: str = "",
        status: Status | None = None,
    ):
        self.kind = kind
        self.tesseract = tesseract
        self.langs = tess_langs
        self.glm = glm
        self.judge = judge
        self.period = period_label
        self.status = status or (lambda _m: None)
        self.strict = kind == SourceKind.ALTDRUCK

    # ------------------------------------------------------------------ öffentlich
    def read(self, page: PageImage) -> PageResult:
        return self.read_pages([page])[0]

    def read_pages(self, pages: list[PageImage]) -> list[PageResult]:
        works = []
        for i, p in enumerate(pages, start=1):
            self.status(f"Seite {p.number} wird vorbereitet ({i}/{len(pages)})")
            works.append(self._analyse(p))
        if self.kind == SourceKind.HANDSCHRIFT:
            self._pass_handwriting_first(works)
            self._pass_glm(works)
        else:
            self._pass_glm(works)
        return [self._compose(w) for w in works]

    # ------------------------------------------------------------------ 1. Analyse
    def _analyse(self, page: PageImage) -> PageWork:
        prep = prepare_page(page.path)
        work = PageWork(page.number)
        if self.kind == SourceKind.HANDSCHRIFT:
            enhanced = prep["enhanced"]
            work.thumb = cv2.resize(enhanced, None, fx=0.35, fy=0.35, interpolation=cv2.INTER_AREA)
            for bbox in segment_lines(prep["binary"]):
                work.items.append(Item(crop(enhanced, bbox, pad=10), bbox=bbox, need_second=True))
            if not self.judge:
                work.notes.append("Für Handschrift wird ein Lesemodell benötigt; es ist nicht verfügbar.")
            return work

        gray, enhanced, binary = prep["gray"], prep["enhanced"], prep["binary"]
        masked = binary.copy()
        for t in detect_ruled_tables(gray):
            cells = []
            for cell in t.cells:
                if not cell.bbox:
                    continue
                x0, y0, x1, y1 = cell.bbox
                inner = (x0 + 4, y0 + 4, x1 - 4, y1 - 4)
                if inner[2] <= inner[0] or inner[3] <= inner[1]:
                    continue
                c_bin = crop(binary, inner, pad=0)
                if c_bin.size == 0 or (c_bin < 128).mean() < 0.003:
                    continue  # leere Zelle
                ocr = self.tesseract.run_tsv(c_bin, self.langs, psm=6) if self.tesseract else OcrPage()
                words = [w for ln in ocr.lines for w in ln.words]
                line = Line(words, inner, 0, 0) if words else None
                need = line is None or self.strict or line.min_conf < fusion.CONF_OK or _looks_numeric(line.text)
                cells.append(Item(crop(enhanced, inner, pad=0), line=line, need_second=need, bbox=inner, cell=cell))
            work.tables.append((t, cells))
            x0, y0, x1, y1 = t.bbox
            masked[y0:y1, x0:x1] = 255


        ocr = self.tesseract.run_tsv(masked, self.langs, psm=3) if self.tesseract else OcrPage()
        heights = [ln.height for ln in ocr.lines if ln.height > 0]
        work.median_h = statistics.median(heights) if heights else 20
        cws = [_char_width(ln) for ln in ocr.lines if ln.text]
        work.median_cw = statistics.median(cws) if cws else 10
        for ln in ocr.lines:
            work.items.append(
                Item(crop(enhanced, ln.bbox, pad=8), line=ln, bbox=ln.bbox, group=(ln.block, ln.par),
                     need_second=self.strict or ln.min_conf < fusion.CONF_SECOND)
            )
        return work

    # ------------------------------------------------------------------ 2. Lesemodell
    def _glm(self, img: np.ndarray) -> str | None:
        if not self.glm:
            return None
        try:
            return self.glm.text(img)
        except OllamaError:
            return None

    def _pass_glm(self, works: list[PageWork]) -> None:
        if not self.glm:
            return
        todo = [it for w in works for it in w.items + [c for _, cs in w.tables for c in cs] if it.need_second]
        for i, it in enumerate(todo, start=1):
            if i % 10 == 1:
                self.status(f"Zweitlesung {i} von {len(todo)}")
            it.other = self._glm(it.crop)
        for w in works:
            if w.gridless_table_png:
                self.status(f"Seite {w.number}: Tabelle ohne Gitterlinien wird erkannt")
                try:
                    raw = self.glm.table_png(w.gridless_table_png)
                except OllamaError:
                    raw = ""
                table = parse_table_output(raw) if raw else None
                if table:
                    w.gridless_table = Block("tabelle", table.to_html(), page=w.number,
                                             note="Tabelle ohne Gitterlinien – Werte prüfen")
                    w.notes.append("Tabelle ohne Gitterlinien aus dem Bild gelesen – Werte bitte prüfen.")

    # ------------------------------------------------------------------ 3. Handschrift
    def _pass_handwriting_first(self, works: list[PageWork]) -> None:
        if not self.judge:
            return
        total = sum(len(w.items) for w in works)
        n = 0
        for w in works:
            previous = ""
            for it in w.items:
                n += 1
                self.status(f"Handschrift: Zeile {n} von {total}")
                try:
                    it.first = self.judge.transcribe_line(it.crop, w.thumb, previous, self.period)
                    previous = it.first.text
                except OllamaError:
                    it.first = None
        if not self.glm:
            # ohne GLM-OCR: zweite Lesung durch das Hauptmodell auf dem binarisierten Bild
            for w in works:
                for it in w.items:
                    if it.first is None:
                        continue
                    try:
                        it.other = self.judge.transcribe_line(binarize(it.crop), None, "", self.period).text
                    except OllamaError:
                        it.other = None
            for w in works:
                for it in w.items:
                    it.need_second = False  # bereits erledigt

    # ------------------------------------------------------------------ 4. Zusammenführen
    def _judge_for(self, img: np.ndarray):
        # Der Schiedsrichter (großes Modell mit Bildausschnitt) ist teuer: nur bei altem Druck/Fraktur.
        # Bei normalem Druck werden Abweichungen markiert statt entschieden.
        if not self.judge or not self.strict:
            return None
        return lambda options: self.judge.decide(img, options)

    def _fuse_item(self, it: Item) -> None:
        if it.line is None:
            if it.other:
                it.markdown = mark_reading(it.other, [it.other], 0.5)
                it.marks = 1
            return
        fused = fusion.fuse_line(it.line, it.other, self._judge_for(it.crop), strict=self.strict)
        it.markdown, it.marks, it.words = fused.markdown, fused.marks, fused.words

    def _compose(self, w: PageWork) -> PageResult:
        if self.kind == SourceKind.HANDSCHRIFT:
            return self._compose_handwriting(w)
        result = PageResult(notes=list(w.notes))
        table_blocks: list[tuple[int, Block]] = []
        for t, cells in w.tables:
            for it in cells:
                self._fuse_item(it)
                it.cell.markdown = it.markdown
                result.marks += it.marks
                result.words += it.words
            issues = t.plausibility()
            result.notes.extend(issues)
            table_blocks.append((t.bbox[1], Block("tabelle", t.to_html(), page=w.number, bbox=t.bbox, note=" ".join(issues))))
        if w.gridless_table:
            table_blocks.append((0, w.gridless_table))

        total = len(w.items)
        for i, it in enumerate(w.items, start=1):
            if i % 20 == 1 and self.judge:
                self.status(f"Seite {w.number}: Abgleich Zeile {i} von {total}")
            self._fuse_item(it)
            result.marks += it.marks
            result.words += it.words
        text_blocks = self._paragraphs(w)
        if w.gridless_table:
            table_text = re.sub(r"<[^>]+>", " ", w.gridless_table.markdown)
            text_blocks = [(y, b) for y, b in text_blocks if not _mostly_contained(b.markdown, table_text)]
        merged = sorted(text_blocks + table_blocks, key=lambda it: it[0])
        result.blocks = [b for _, b in merged]
        return result

    def _paragraphs(self, w: PageWork) -> list[tuple[int, Block]]:
        if not w.items:
            return []
        groups: dict[tuple[int, int], list[Item]] = {}
        for it in w.items:
            groups.setdefault(it.group, []).append(it)
        spans = [(min(i.bbox[0] for i in g), max(i.bbox[2] for i in g)) for g in groups.values()]
        main_x0 = statistics.median(s[0] for s in spans)
        main_x1 = statistics.median(s[1] for s in spans)
        main_w = max(1, main_x1 - main_x0)
        out = []
        for g in groups.values():
            text = fusion.join_lines([i.markdown for i in g])
            if not text.strip():
                continue
            x0 = min(i.bbox[0] for i in g)
            x1 = max(i.bbox[2] for i in g)
            y0 = min(i.bbox[1] for i in g)
            h = statistics.median(i.line.height for i in g)
            cw = statistics.median(_char_width(i.line) for i in g)
            kind = "absatz"
            if (x1 < main_x0 + main_w * 0.1 or x0 > main_x1 - main_w * 0.1) and (x1 - x0) < main_w * 0.4:
                kind = "randnotiz"
            elif len(text) < 160 and len(g) <= 2 and (
                h > w.median_h * 1.45 or (cw > w.median_cw * 1.35 and not text.rstrip().endswith((",", ";")))
            ):
                kind = "ueberschrift"
            out.append((y0, Block(kind, text, page=w.number, bbox=(x0, y0, x1, y0 + int(h)))))
        return out

    def _compose_handwriting(self, w: PageWork) -> PageResult:
        result = PageResult(notes=list(w.notes))
        lines_md: list[tuple[tuple[int, int, int, int], str]] = []
        for it in w.items:
            if it.first is None:
                lines_md.append((it.bbox, fusion.mark_by_confidence([("[?]", 0.0)])[0]))
                result.marks += 1
                continue
            words = it.first.word_confidences()
            if not words:
                continue
            pseudo = Line([Word(t, p * 100, it.bbox) for t, p in words], it.bbox, 0, 0)
            fused = fusion.fuse_line(pseudo, it.other, None, strict=True) if it.other else None
            if fused is None or fused.marks == 0:
                md, m = fusion.mark_by_confidence(words, threshold=0.45)
            else:
                md, m = fused.markdown, fused.marks
            result.marks += m
            result.words += len(words)
            lines_md.append((it.bbox, md))
        gaps = [b[0][1] - a[0][3] for a, b in zip(lines_md, lines_md[1:])]
        median_gap = statistics.median(gaps) if gaps else 0
        paragraphs, para = [], []
        for i, (_bbox, md) in enumerate(lines_md):
            if i > 0 and median_gap > 0 and gaps[i - 1] > median_gap * 2.2 and para:
                paragraphs.append(fusion.join_lines(para))
                para = []
            para.append(md)
        if para:
            paragraphs.append(fusion.join_lines(para))
        result.blocks = [Block("absatz", t, page=w.number) for t in paragraphs if t.strip()]
        return result


# --------------------------------------------------------------------------- Zeilenzerlegung (Handschrift)


def segment_lines(binary: np.ndarray, min_height: int = 12) -> list[tuple[int, int, int, int]]:
    """Zerlegt eine Seite in Textzeilen über das horizontale Projektionsprofil.

    Bewusst einfach und ohne Zusatzmodelle (läuft nativ unter Windows). Für stark schräge oder
    ineinander verschlungene Zeilen ist ein trainiertes Segmentierungsmodell als späterer Ausbau vorgesehen.
    """
    ink = (binary < 128).astype(np.uint8)
    h, w = ink.shape
    # Ränder (Scanner-Schatten) ignorieren
    margin_x = int(w * 0.02)
    ink[:, :margin_x] = 0
    ink[:, w - margin_x:] = 0
    ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    profile = ink.sum(axis=1).astype(np.float64)
    if profile.max() == 0:
        return []
    k = max(3, h // 300) | 1
    smooth = np.convolve(profile, np.ones(k) / k, mode="same")
    threshold = max(smooth.max() * 0.06, w * 0.004)
    rows = smooth > threshold
    bands = []
    start = None
    for y, on in enumerate(rows):
        if on and start is None:
            start = y
        elif not on and start is not None:
            bands.append((start, y))
            start = None
    if start is not None:
        bands.append((start, h))
    bands = [b for b in bands if b[1] - b[0] >= min_height]
    if not bands:
        return []
    median_h = statistics.median(b[1] - b[0] for b in bands)

    split: list[tuple[int, int]] = []
    for y0, y1 in bands:
        n = round((y1 - y0) / median_h) if median_h else 1
        if n >= 2:
            # zu hohe Bänder (zusammengewachsene Zeilen) an den Profilminima teilen
            seg = smooth[y0:y1]
            cuts = []
            for j in range(1, n):
                center = int(len(seg) * j / n)
                window = max(2, int(median_h * 0.3))
                lo, hi = max(1, center - window), min(len(seg) - 1, center + window)
                cuts.append(y0 + lo + int(np.argmin(seg[lo:hi])))
            edges = [y0] + cuts + [y1]
            split.extend(zip(edges, edges[1:]))
        else:
            split.append((y0, y1))

    boxes = []
    pad = int(median_h * 0.25)
    for y0, y1 in split:
        cols = np.where(ink[y0:y1].sum(axis=0) > 0)[0]
        if cols.size == 0:
            continue
        boxes.append((int(cols[0]), max(0, y0 - pad), int(cols[-1]) + 1, min(h, y1 + pad)))
    return boxes


# --------------------------------------------------------------------------- Hilfsfunktionen


def _char_width(line: Line) -> float:
    """Mittlere Zeichenbreite – unterscheidet Schriftgrade zuverlässiger als die Zeilenhöhe (Versalien)."""
    return (line.bbox[2] - line.bbox[0]) / max(1, len(line.text))


def _looks_numeric(text: str) -> bool:
    return bool(re.search(r"\d", text))


def _mostly_contained(paragraph_md: str, haystack: str) -> bool:
    words = [w for w in re.findall(r"\w+", paragraph_md) if len(w) > 2]
    if not words:
        return True
    hay = set(re.findall(r"\w+", haystack))
    return sum(w in hay for w in words) / len(words) > 0.7


def parse_table_output(raw: str) -> Table | None:
    """Wertet die Tabellenausgabe eines Lesemodells aus (HTML oder Markdown-Pipe-Tabelle)."""
    raw = re.sub(r"^```\w*|```$", "", raw.strip()).strip()
    if "<table" in raw.lower():
        return _parse_html_table(raw)
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip().startswith("|")]
    rows = [ln.strip("|").split("|") for ln in lines if not re.fullmatch(r"\|?[\s:\-|]+\|?", ln)]
    if len(rows) < 2:
        return None
    n_cols = max(len(r) for r in rows)
    cells = [Cell(r, c, markdown=escape_md(v.strip()), header=(r == 0)) for r, row in enumerate(rows) for c, v in enumerate(row)]
    return Table(len(rows), n_cols, cells)


def _parse_html_table(raw: str) -> Table | None:
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows: list[list[dict]] = []
            self.cell: dict | None = None

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "tr":
                self.rows.append([])
            elif tag in ("td", "th") and self.rows is not None:
                if not self.rows:
                    self.rows.append([])
                self.cell = {"text": "", "rs": int(a.get("rowspan", 1) or 1), "cs": int(a.get("colspan", 1) or 1), "th": tag == "th"}

        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.cell is not None:
                self.rows[-1].append(self.cell)
                self.cell = None

        def handle_data(self, data):
            if self.cell is not None:
                self.cell["text"] += data

    p = P()
    try:
        p.feed(raw)
    except Exception:  # noqa: BLE001 – fehlerhaftes HTML eines Modells
        return None
    if not p.rows:
        return None
    occupied: set[tuple[int, int]] = set()
    cells = []
    n_cols = 0
    for r, row in enumerate(p.rows):
        c = 0
        for item in row:
            while (r, c) in occupied:
                c += 1
            for dr in range(item["rs"]):
                for dc in range(item["cs"]):
                    occupied.add((r + dr, c + dc))
            cells.append(Cell(r, c, item["rs"], item["cs"], escape_md(html.unescape(" ".join(item["text"].split()))), header=item["th"] or r == 0))
            c += item["cs"]
            n_cols = max(n_cols, c)
    return Table(len(p.rows), n_cols, cells)
