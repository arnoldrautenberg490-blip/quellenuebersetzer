import numpy as np
import pytest
from PIL import Image, ImageDraw

from quellenuebersetzer.config import Paths
from quellenuebersetzer.pipeline import markup
from quellenuebersetzer.pipeline.document import PageImage
from quellenuebersetzer.pipeline.reading import PageReader, parse_table_output, segment_lines
from quellenuebersetzer.pipeline.preprocess import binarize, load_gray
from quellenuebersetzer.pipeline.tables import Cell, Table, detect_ruled_tables
from quellenuebersetzer.profile import SourceKind
from quellenuebersetzer.runtime.tesseract import Tesseract

from conftest import make_handwriting_like, make_text_page


def test_detect_ruled_table_with_merged_cell(tmp_path):
    img = Image.new("L", (1600, 1000), 255)
    d = ImageDraw.Draw(img)
    x0, y0, cw, rh = 100, 100, 400, 150
    for r in range(4):  # waagrechte Linien
        d.line([(x0, y0 + r * rh), (x0 + 3 * cw, y0 + r * rh)], fill=0, width=4)
    for c in range(4):  # senkrechte Linien; erste Zeile: Zelle über Spalte 2+3 verbunden
        top = y0 + rh if c == 2 else y0
        d.line([(x0 + c * cw, top), (x0 + c * cw, y0 + 3 * rh)], fill=0, width=4)
    tables = detect_ruled_tables(np.array(img))
    assert len(tables) == 1
    t = tables[0]
    assert (t.n_rows, t.n_cols) == (3, 3)
    merged = [c for c in t.cells if c.colspan == 2]
    assert len(merged) == 1 and merged[0].row == 0 and merged[0].col == 1


def test_sum_check_detects_mismatch():
    t = Table(3, 2, [Cell(0, 0, markdown="A"), Cell(0, 1, markdown="2"), Cell(1, 0, markdown="B"),
                     Cell(1, 1, markdown="3"), Cell(2, 0, markdown="Razem"), Cell(2, 1, markdown="6")])
    assert any("Summe" in i for i in t.plausibility())
    t.cells[-1].markdown = "5"
    assert not t.plausibility()


def test_parse_model_table_output_html_and_pipe():
    t = parse_table_output("<table><tr><th colspan='2'>A</th></tr><tr><td>1</td><td>2</td></tr></table>")
    assert t and t.n_cols == 2 and t.cells[0].colspan == 2
    p = parse_table_output("| a | b |\n|---|---|\n| 1 | 2 |")
    assert p and p.n_rows == 2


def test_segment_lines_counts_lines(tmp_path):
    path = make_handwriting_like(tmp_path / "hs.png", n_lines=6)
    boxes = segment_lines(binarize(load_gray(path)))
    assert len(boxes) == 6


def test_read_print_page_with_real_tesseract(tmp_path, tess_root):
    page_path = make_text_page(tmp_path / "seite.png")
    reader = PageReader(SourceKind.DRUCK, Tesseract(Paths(tess_root)), ["pol"], None, None)
    res = reader.read(PageImage(1, page_path))
    text = " ".join(markup.strip_marks(b.markdown) for b in res.blocks)
    assert "Starosta" in text and "młynarzy" in text
    tables = [b for b in res.blocks if b.kind == "tabelle"]
    assert len(tables) == 1
    assert "Bronowice" in tables[0].markdown and "Razem" in tables[0].markdown
    assert not tables[0].note, tables[0].note  # Summen stimmen
    headings = [b for b in res.blocks if b.kind == "ueberschrift"]
    assert headings and "PRZYWILEJ" in headings[0].markdown


def test_spread_is_split_at_gutter_and_single_page_is_not(tmp_path):
    from PIL import Image, ImageDraw

    from conftest import SAMPLE_PL, font
    from quellenuebersetzer.pipeline.preprocess import split_spread

    spread = Image.new("L", (3600, 2400), 240)
    d = ImageDraw.Draw(spread)
    d.rectangle([0, 0, 3600, 60], fill=10)  # schwarzer Scannerrand oben
    for x in range(1740, 1860):  # Schatten im Bundsteg
        d.line([(x, 60), (x, 2400)], fill=int(120 + abs(x - 1800)))
    for i in range(18):
        line = SAMPLE_PL[i % len(SAMPLE_PL)]
        d.text((200, 200 + i * 110), line, font=font(size=46), fill=20)
        d.text((1950, 200 + i * 110), line, font=font(size=46), fill=20)
    src = tmp_path / "doppelseite.png"
    spread.save(src)
    parts = split_spread(src, tmp_path, 7)
    assert [label for _, label in parts] == ["7a", "7b"]
    left = Image.open(parts[0][0])
    assert 1500 < left.width < 1850 and left.height < 2400  # geteilt und Rand oben entfernt

    from conftest import make_text_page

    single = make_text_page(tmp_path / "einzel.png", with_table=False)
    assert [label for _, label in split_spread(single, tmp_path, 3)] == ["3"]


def test_folder_of_images_is_one_document_in_natural_order(tmp_path):
    from quellenuebersetzer.pipeline.ingest import ingest, iter_sources

    from conftest import make_text_page

    book = tmp_path / "Akte 1785"
    book.mkdir()
    for n in (1, 2, 10):
        make_text_page(book / f"scan{n}.png", with_table=False, size=(1240, 1754))
    (tmp_path / "brief.docx").write_bytes(b"")  # einzelne Datei daneben
    units = iter_sources(tmp_path)
    assert book in units and len(units) == 2
    ing = ingest(book, tmp_path / "cache")
    assert [p.number for p in ing.pages] == [1, 2, 3]
    assert [p.label for p in ing.pages] == ["1", "2", "3"]
    assert ing.pages[2].path.name.startswith("seite-0003")


def make_cover_spread(path):
    from PIL import Image, ImageDraw

    from conftest import font

    img = Image.new("RGB", (3400, 2400), (238, 234, 226))  # Scannerunterlage
    d = ImageDraw.Draw(img)
    d.rectangle([150, 120, 1640, 2280], fill=(96, 62, 38))  # Rückdeckel (links)
    d.rectangle([1640, 110, 1760, 2290], fill=(70, 44, 26))  # Buchrücken
    d.rectangle([1760, 120, 3250, 2280], fill=(96, 62, 38))  # Vorderdeckel (rechts)
    d.rectangle([2050, 500, 2960, 760], outline=(210, 180, 120), width=8)
    d.text((2130, 580), "KRONIKA", font=font(size=110), fill=(215, 185, 125))
    img.save(path)
    return path


def test_cover_spread_is_split_and_ordered(tmp_path):
    from quellenuebersetzer.pipeline.ingest import ingest

    from conftest import make_text_page

    book = tmp_path / "Band"
    book.mkdir()
    make_cover_spread(book / "scan01.png")
    make_text_page(book / "scan02.png", with_table=False, size=(1240, 1754))
    make_text_page(book / "scan03.png", with_table=False, size=(1240, 1754))
    ing = ingest(book, tmp_path / "cache")
    assert [p.label for p in ing.pages] == ["Vorderdeckel", "2", "3", "Rückdeckel"]
    assert [p.number for p in ing.pages] == [1, 2, 3, 4]
    assert ing.notes and "Einband" in ing.notes[0]
    front = ing.pages[0]
    assert 1300 < front.width < 1900  # am Buchrücken geteilt


def test_two_text_pages_are_not_mistaken_for_cover(tmp_path):
    from quellenuebersetzer.pipeline.ingest import arrange_cover
    from quellenuebersetzer.pipeline.document import PageImage

    from conftest import make_text_page

    p1 = make_text_page(tmp_path / "a.png", with_table=False, size=(1240, 1754))
    p2 = make_text_page(tmp_path / "b.png", with_table=False, size=(1240, 1754))
    pages = [PageImage(1, p1, 1240, 1754), PageImage(2, p2, 1240, 1754)]
    out, note = arrange_cover(pages, tmp_path)
    assert out == pages and note is None


def test_overlapping_regions_are_resolved():
    from quellenuebersetzer.runtime.layout import Region, resolve_overlaps

    img = Region("abbildung", (100, 100, 600, 500), 0.9, 0)
    caption_inside = Region("absatz", (150, 400, 400, 450), 0.8, 1)  # Beschriftung im Stich
    text_into_image = Region("absatz", (100, 450, 1000, 800), 0.8, 2)  # ragt von unten ins Bild
    text_a = Region("absatz", (700, 100, 1000, 300), 0.8, 3)
    text_b = Region("absatz", (700, 250, 1000, 400), 0.8, 4)  # überlappt text_a
    out = resolve_overlaps([img, caption_inside, text_into_image, text_a, text_b])
    boxes = {r.order: r.box for r in out}
    assert 1 not in boxes  # gehört zum Bild
    assert boxes[2][1] >= 500  # unterhalb des Bildes abgeschnitten
    from itertools import combinations

    for a, b in combinations(out, 2):
        x0, y0 = max(a.box[0], b.box[0]), max(a.box[1], b.box[1])
        x1, y1 = min(a.box[2], b.box[2]), min(a.box[3], b.box[3])
        assert x1 <= x0 or y1 <= y0, (a, b)  # keine Überlappung mehr


def make_distorted_scan(path):
    """Erfundene Buchseite, absichtlich verzerrt wie ein Archivscan: gewölbt, schräg, trapezförmig, dunkler Grund."""
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw

    from conftest import SAMPLE_PL, font

    w, h = 1600, 2300
    page = Image.new("L", (w, h), 238)
    d = ImageDraw.Draw(page)
    for i in range(22):
        d.text((140, 160 + i * 88), SAMPLE_PL[i % len(SAMPLE_PL)], font=font(size=44), fill=25)
    arr = np.array(page)
    # Wölbung zum Bundsteg (rechts): Zeilen sinken nach rechts hin ab
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    curl = 45 * (xs / w) ** 3
    arr = cv2.remap(arr, xs, ys - curl, cv2.INTER_LINEAR, borderValue=238)
    # auf dunklen Hintergrund, schräg und trapezförmig
    canvas = np.full((2700, 2100), 45, np.uint8)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[230, 160], [1850, 230], [1900, 2560], [180, 2490]])
    m = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(arr, m, (2100, 2700), borderValue=45)
    mask = cv2.warpPerspective(np.full_like(arr, 255), m, (2100, 2700))
    canvas[mask > 0] = warped[mask > 0]
    cv2.imwrite(str(path), cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR))
    return path


def test_distorted_archive_scan_is_straightened(tmp_path):
    import cv2
    import numpy as np

    from quellenuebersetzer.pipeline.pagegeom import _text_lines, normalize_geometry

    path = make_distorted_scan(tmp_path / "verzerrt.png")
    color = cv2.imread(str(path))

    def max_bend(gray):
        bends = []
        for pts in _text_lines(gray):
            c = np.polyfit(pts[:, 0], pts[:, 1], 2)
            fit = np.polyval(c, pts[:, 0])
            bends.append(fit.max() - fit.min())
        return float(np.median(bends))

    before = max_bend(cv2.cvtColor(color, cv2.COLOR_BGR2GRAY))
    fixed, report = normalize_geometry(color)
    after = max_bend(cv2.cvtColor(fixed, cv2.COLOR_BGR2GRAY))
    assert report.cropped  # Hintergrund entfernt
    h, w = fixed.shape[:2]
    assert abs(w / h - 1600 / 2300) < 0.05  # Seitenverhältnis wiederhergestellt
    assert after < before * 0.35, (before, after)  # Zeilen deutlich gerader


def test_gridless_table_is_built_from_ocr_words_only(tmp_path, tess_root):
    """Tabelle ohne Linien: Inhalte stammen ausschließlich aus der Texterkennung – nichts wird erfunden."""
    import re as _re

    from conftest import make_mixed_page
    from quellenuebersetzer.pipeline.layout_reading import LayoutReader
    from quellenuebersetzer.runtime.layout import LayoutDetector

    det = LayoutDetector(Paths(tess_root))
    if not det.available:
        pytest.skip("Seitenaufbau-Modell nicht in der Testumgebung")
    page = make_mixed_page(tmp_path / "misch.png")
    reader = LayoutReader(SourceKind.DRUCK, Tesseract(Paths(tess_root)), ["pol"], None, None, detector=det,
                          workdir=tmp_path)
    lp = reader.read_layout([PageImage(1, page)])[0]
    table = next(r for r in lp.regions if r.kind == "tabelle")
    cells = [_re.sub(r"<[^>]+>", "", c).strip() for c in _re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", table.source_md)]
    assert cells[:3] == ["Miejscowość", "Młyny", "Złote"], cells
    assert "Bronowice" in cells and "Razem" in cells and "10" in cells
    expected = {"Miejscowość", "Młyny", "Złote", "Bronowice", "3", "6", "Krowodrza", "2", "4", "Razem", "5", "10"}
    assert {c for c in cells if c} <= expected  # keine zusätzlichen, erfundenen Inhalte
