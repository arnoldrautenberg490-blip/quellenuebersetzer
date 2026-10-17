"""Quellen einlesen: Dateien finden, digitale Dokumente direkt übernehmen, Scans als Bilder bereitstellen."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

from quellenuebersetzer.pipeline.document import Block, PageImage
from quellenuebersetzer.pipeline.markup import escape_md
from quellenuebersetzer.pipeline.tables import Cell, Table

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".jp2"}
PDF_EXT = {".pdf"}
DOCX_EXT = {".docx"}
TEXT_EXT = {".txt", ".md"}
SUPPORTED = IMAGE_EXT | PDF_EXT | DOCX_EXT | TEXT_EXT

OUTPUT_DIR_NAME = "Übersetzungen"
RENDER_DPI = 300

Image.MAX_IMAGE_PIXELS = 400_000_000  # große Archivscans zulassen


def natural_key(p: Path) -> list:
    """Natürliche Sortierung: „Scan2“ vor „Scan10“."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(p))]


def _wanted(p: Path, base: Path) -> bool:
    if not p.is_file() or p.suffix.lower() not in SUPPORTED:
        return False
    if OUTPUT_DIR_NAME in p.relative_to(base).parts:
        return False  # eigene Ergebnisse nicht erneut verarbeiten
    return not p.name.startswith(("~$", "."))  # Word-Sperrdateien, versteckte Dateien


def iter_sources(path: Path) -> list[Path]:
    """Eine Datei oder alle Quellen eines Ordners (mit Unterordnern).

    Ein Ordner, der ausschließlich Seitenbilder enthält (mindestens zwei), gilt als EIN Dokument –
    z. B. ein Buch oder eine Akte, Seite für Seite gescannt. Er wird dann als Ordnerpfad zurückgegeben.
    """
    path = Path(path)
    if path.is_file():
        return [path] if path.suffix.lower() in SUPPORTED else []
    files = sorted((p for p in path.rglob("*") if _wanted(p, path)), key=natural_key)
    by_dir: dict[Path, list[Path]] = {}
    for f in files:
        by_dir.setdefault(f.parent, []).append(f)
    out: list[Path] = []
    for d in sorted(by_dir, key=natural_key):
        group = by_dir[d]
        if len(group) >= 2 and all(f.suffix.lower() in IMAGE_EXT for f in group):
            out.append(d)
        else:
            out.extend(group)
    return out


def folder_images(folder: Path) -> list[Path]:
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXT
                   and not p.name.startswith(".")), key=natural_key)


@dataclass
class Ingested:
    origin: str  # digital | scan
    blocks: list[Block]
    pages: list[PageImage]
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- Bilder


def _save_pages(img: Image.Image, dest_dir: Path, number: int, dpi: float, split: bool = True) -> list[PageImage]:
    """Speichert ein Seitenbild im Arbeitsordner; Doppelseiten werden geteilt, Scannerränder entfernt."""
    from quellenuebersetzer.pipeline.preprocess import split_spread

    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"seite-{number:04d}.png"
    img.save(dest, optimize=False)
    parts = split_spread(dest, dest_dir, number) if split else [(dest, str(number))]
    pages = []
    for path, label in parts:
        with Image.open(path) as im:
            w, h = im.size
        pages.append(PageImage(number, path, w, h, label if label != str(number) else "", dpi))
    return pages


def _dpi_of(im: Image.Image) -> float:
    dpi = im.info.get("dpi")
    try:
        value = float(dpi[0]) if dpi else 0.0
    except (TypeError, ValueError):
        value = 0.0
    return value if 100 <= value <= 1200 else 300.0


def load_images(path: Path, cache: Path, start: int = 1) -> list[PageImage]:
    pages: list[PageImage] = []
    with Image.open(path) as im:
        n = getattr(im, "n_frames", 1)
        for i in range(n):
            im.seek(i)
            pages.extend(_save_pages(im.copy(), cache, start + i, _dpi_of(im)))
    return pages


def load_folder(folder: Path, cache: Path) -> list[PageImage]:
    pages: list[PageImage] = []
    for n, f in enumerate(folder_images(folder), start=1):
        for p in load_images(f, cache, start=n):
            pages.append(p)
    return pages


def arrange_cover(pages: list[PageImage], cache: Path) -> tuple[list[PageImage], str | None]:
    """Erste Aufnahme als Einband (Vorder- und Rückdeckel nebeneinander, kaum Text)?
    Dann am Buchrücken teilen: Vorderdeckel an den Anfang, Rückdeckel ans Ende."""
    from quellenuebersetzer.pipeline.preprocess import is_cover_spread, split_cover

    if len(pages) < 2:
        return pages, None
    first = pages[0]
    candidates = [p for p in pages if p.number == first.number]
    if len(candidates) == 2:
        # bereits als Doppelseite geteilt – Einband nur, wenn beide Hälften fast textlos sind
        from quellenuebersetzer.pipeline.preprocess import load_gray, text_line_count

        if all(text_line_count(load_gray(p.path)) <= 4 for p in candidates):
            back, front = candidates
            rest = [p for p in pages if p.number != first.number]
            front.label, back.label = "Vorderdeckel", "Rückdeckel"
            return [front] + rest + [back], "Die erste Aufnahme wurde als Einband erkannt: Vorderdeckel am Anfang, Rückdeckel am Ende."
        return pages, None
    if not is_cover_spread(first.path):
        return pages, None
    front_path, back_path = split_cover(first.path, cache)
    from PIL import Image

    def page(path: Path, label: str) -> PageImage:
        with Image.open(path) as im:
            return PageImage(first.number, path, im.width, im.height, label, first.dpi)

    return ([page(front_path, "Vorderdeckel")] + pages[1:] + [page(back_path, "Rückdeckel")],
            "Die erste Aufnahme wurde als Einband erkannt: Vorderdeckel am Anfang, Rückdeckel am Ende.")


def renumber(pages: list[PageImage]) -> list[PageImage]:
    """Laufende, eindeutige Seitennummern; die Bezeichnung (z. B. „7a“) bleibt für die Anzeige erhalten."""
    for i, p in enumerate(pages, start=1):
        if not p.label:
            p.label = str(p.number)
        p.number = i
    return pages


def render_pdf(path: Path, cache: Path, page_indices: list[int] | None = None, split: bool = True) -> list[PageImage]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        indices = page_indices if page_indices is not None else range(len(pdf))
        pages: list[PageImage] = []
        for i in indices:
            bitmap = pdf[i].render(scale=RENDER_DPI / 72)
            pages.extend(_save_pages(bitmap.to_pil(), cache, i + 1, RENDER_DPI, split=split))
        return pages
    finally:
        pdf.close()


# --------------------------------------------------------------------------- PDF


def pdf_page_is_scan(page) -> bool:
    """Seite ist ein Scan, wenn sie (fast) nur aus einem Bild besteht – auch wenn eine OCR-Textebene existiert."""
    area = float(page.width * page.height) or 1.0
    img_area = sum(abs((i["x1"] - i["x0"]) * (i["bottom"] - i["top"])) for i in page.images)
    chars = len(page.chars)
    if img_area / area > 0.6:
        return True
    return chars < 20


def _pdf_page_blocks(page, number: int) -> list[Block]:
    blocks: list[Block] = []
    tables = page.find_tables()
    table_boxes = [t.bbox for t in tables]

    def in_table(obj) -> bool:
        cx, cy = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
        return any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in table_boxes)

    words = [w for w in page.extract_words(extra_attrs=["size"], keep_blank_chars=False) if not in_table(w)]
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) < 3:
            lines[-1].append(w)
        else:
            lines.append([w])

    sizes = [w["size"] for w in words] or [10]
    body = statistics.median(sizes)
    items: list[tuple[float, Block]] = []
    para: list[str] = []
    para_top = None
    prev_bottom = None
    prev_size = None

    def flush():
        nonlocal para, para_top
        if para:
            text = " ".join(para)
            text = re.sub(r"(\w)- (\w)", r"\1\2", text)  # Silbentrennung am Zeilenende
            kind = "ueberschrift" if prev_size and prev_size > body * 1.25 and len(text) < 200 else "absatz"
            items.append((para_top, Block(kind, escape_md(text), page=number)))
        para, para_top = [], None

    for line in lines:
        line.sort(key=lambda w: w["x0"])
        top = min(w["top"] for w in line)
        size = statistics.median(w["size"] for w in line)
        gap = top - prev_bottom if prev_bottom is not None else 0
        if para and (gap > size * 0.9 or (prev_size and abs(size - prev_size) > 1.5)):
            flush()
        if para_top is None:
            para_top = top
        para.append(" ".join(w["text"] for w in line))
        prev_bottom = max(w["bottom"] for w in line)
        prev_size = size
    flush()

    for t in tables:
        data = t.extract()
        if not data:
            continue
        n_cols = max(len(r) for r in data)
        cells = []
        for r, row in enumerate(data):
            for c, value in enumerate(row):
                if value is None:
                    continue  # Teil einer verbundenen Zelle
                cs = 1
                while c + cs < len(row) and row[c + cs] is None:
                    cs += 1
                cells.append(Cell(r, c, 1, cs, escape_md((value or "").replace("\n", " ")), header=(r == 0)))
        table = Table(len(data), n_cols, cells)
        items.append((t.bbox[1], Block("tabelle", table.to_html(), page=number)))

    items.sort(key=lambda it: it[0])
    return [b for _, b in items]


def ingest_pdf(path: Path, cache: Path) -> Ingested:
    import pdfplumber

    blocks: list[Block] = []
    scan_pages: list[int] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            if pdf_page_is_scan(page):
                scan_pages.append(i)
            else:
                blocks.extend(_pdf_page_blocks(page, i + 1))
        n_pages = len(pdf.pages)
    if len(scan_pages) > n_pages / 2:
        return _scan(render_pdf(path, cache), cache)
    if scan_pages:
        # gemischtes PDF: digitale Seiten direkt, Scanseiten als Bild (Seitennummern wie im PDF, nicht teilen)
        return Ingested("gemischt", blocks, render_pdf(path, cache, scan_pages, split=False))
    return Ingested("digital", blocks, [])


# --------------------------------------------------------------------------- DOCX


def _docx_table(tbl) -> Table:
    from docx.oxml.ns import qn

    rows = tbl._tbl.findall(qn("w:tr"))
    grid: list[list[dict]] = []
    for tr in rows:
        row, col = [], 0
        for tc in tr.findall(qn("w:tc")):
            pr = tc.find(qn("w:tcPr"))
            span, vmerge = 1, None
            if pr is not None:
                gs = pr.find(qn("w:gridSpan"))
                if gs is not None:
                    span = int(gs.get(qn("w:val"), 1))
                vm = pr.find(qn("w:vMerge"))
                if vm is not None:
                    vmerge = vm.get(qn("w:val"), "continue")
            text = "\n".join("".join(t.text or "" for t in p.iter(qn("w:t"))) for p in tc.findall(qn("w:p")))
            row.append({"col": col, "span": span, "vmerge": vmerge, "text": text.strip()})
            col += span
        grid.append(row)
    n_cols = max((sum(c["span"] for c in r) for r in grid), default=0)
    cells: list[Cell] = []
    open_cells: dict[int, Cell] = {}
    for r, row in enumerate(grid):
        for c in row:
            if c["vmerge"] == "continue" and c["col"] in open_cells:
                open_cells[c["col"]].rowspan += 1
                continue
            cell = Cell(r, c["col"], 1, c["span"], escape_md(c["text"].replace("\n", " ")), header=(r == 0))
            cells.append(cell)
            if c["vmerge"] == "restart":
                open_cells[c["col"]] = cell
            else:
                open_cells.pop(c["col"], None)
    return Table(len(grid), n_cols, cells)


def ingest_docx(path: Path) -> Ingested:
    import docx
    from docx.oxml.ns import qn

    d = docx.Document(str(path))
    blocks: list[Block] = []
    body = d.element.body
    tables = {t._tbl: t for t in d.tables}
    paragraphs = {p._p: p for p in d.paragraphs}
    for child in body.iterchildren():
        if child.tag == qn("w:p") and child in paragraphs:
            p = paragraphs[child]
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name or "").lower() if p.style is not None else ""
            kind = "ueberschrift" if style.startswith(("heading", "überschrift", "title", "titel")) else "absatz"
            blocks.append(Block(kind, escape_md(text)))
        elif child.tag == qn("w:tbl") and child in tables:
            blocks.append(Block("tabelle", _docx_table(tables[child]).to_html()))
    return Ingested("digital", blocks, [])


# --------------------------------------------------------------------------- Text


def ingest_text(path: Path) -> Ingested:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1250", "iso-8859-2"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    blocks = []
    for p in paras:
        # Markdown-Dateien: Überschriften behalten, sonst alles als Text maskieren – so können
        # eingebettete Bilder, Links oder HTML keine (Netz-)Ressourcen nachladen.
        m = re.match(r"^#{1,6}\s+(.*)", p) if path.suffix.lower() == ".md" else None
        if m and "\n" not in p:
            blocks.append(Block("ueberschrift", escape_md(m.group(1))))
        else:
            blocks.append(Block("absatz", escape_md(p)))
    return Ingested("digital", blocks, [])


def _scan(pages: list[PageImage], cache: Path) -> Ingested:
    pages, note = arrange_cover(pages, cache)
    return Ingested("scan", [], renumber(pages), [note] if note else [])


def ingest(path: Path, cache: Path) -> Ingested:
    if path.is_dir():
        return _scan(load_folder(path, cache), cache)
    ext = path.suffix.lower()
    if ext in PDF_EXT:
        return ingest_pdf(path, cache)
    if ext in DOCX_EXT:
        return ingest_docx(path)
    if ext in TEXT_EXT:
        return ingest_text(path)
    if ext in IMAGE_EXT:
        return _scan(load_images(path, cache), cache)
    raise ValueError(f"Dateiformat wird nicht unterstützt: {path.suffix}")
