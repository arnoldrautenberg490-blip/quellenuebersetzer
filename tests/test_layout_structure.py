"""Layouterkennung: Merkmalsebenen, Zusammenführung, Gestaltung, Prüfbericht – und Qualitätsschranken.

Die Qualitätsschranken laufen Ende-zu-Ende (Layoutmodell + Tesseract) an Seiten der Testsammlung
(tests/sammlung.py) und messen am Ergebnis, nicht an vorgegebenen Rahmen.
"""

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

import sammlung
from quellenuebersetzer.pipeline import features, pruefbericht
from quellenuebersetzer.pipeline.layout_doc import LayoutDocument, LPage, LRegion
from quellenuebersetzer.pipeline.layout_reading import garbage_ratio, is_artifact
from quellenuebersetzer.pipeline.layout_translate import build_units
from quellenuebersetzer.pipeline.structure import split_columns
from quellenuebersetzer.pipeline.tables import table_from_rules


def _bgr(page) -> np.ndarray:
    return cv2.cvtColor(np.asarray(page.image), cv2.COLOR_RGB2BGR)


# --------------------------------------------------------------------------- Merkmalsebenen


@pytest.mark.parametrize("name", ["tabelle_gestrichelt", "tabelle_gepunktet"])
def test_dashed_and_dotted_rules_are_lines_not_text(name):
    page = sammlung.build(name)
    feats = features.analyse(_bgr(page))
    table = next(b for b in page.blocks if b.kind == "tabelle")
    x0, y0, x1, y1 = table.box
    hs = [r for r in feats.rules if r.orient == "h" and y0 - 10 <= r.pos <= y1 + 10]
    assert len(hs) == table.table["rows"] + 1  # jede Zeilenlinie gefunden, keine zusätzliche
    assert all(r.style != "solid" for r in hs if y0 + 10 < r.pos < y1 - 10)
    # Fließtext erzeugt keine Linien
    for b in page.blocks:
        if b.kind == "absatz":
            assert not feats.rules_in(b.box), b.box


def test_light_and_dark_boxes_are_found_with_colour_and_frame():
    feats = features.analyse(_bgr(sammlung.build("kasten_dunkel")))
    dark = [p for p in feats.panels if p.dark]
    framed = [p for p in feats.panels if p.dash == "dashed"]
    assert len(dark) == 1 and dark[0].fill
    assert len(framed) == 1
    feats = features.analyse(_bgr(sammlung.build("kasten_hell", aged=True)))
    assert any(p.fill and p.stroke and p.dash == "solid" for p in feats.panels)


def test_columns_are_split_at_a_gutter_but_not_at_word_spaces():
    page = sammlung.build("zweispaltig")
    color = _bgr(page)
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    feats = features.analyse(color)
    ink = features.text_ink(gray, feats)
    c1, c2 = [b for b in page.blocks if b.flow in ("spalte1", "spalte2")]
    both = (c1.box[0], min(c1.box[1], c2.box[1]), c2.box[2], max(c1.box[3], c2.box[3]))
    parts = split_columns(both, ink, 1.0)
    assert len(parts) == 2
    assert parts[0][2] <= c2.box[0] and parts[1][0] >= c1.box[2]
    assert split_columns(c1.box, ink, 1.0) == [c1.box] or len(split_columns(c1.box, ink, 1.0)) == 1


def test_table_from_rules_completes_missing_outer_lines_and_merges_cells():
    from quellenuebersetzer.pipeline.features import Rule

    box = (0, 0, 300, 200)
    rules = [Rule("h", 0, 100, 300, 102, "dashed", 2, "#000000"),
             Rule("v", 150, 100, 152, 200, "dotted", 2, "#000000")]  # obere Zeile ohne Trennlinie → verbunden
    t = table_from_rules(box, rules, tol=6)
    assert t is not None and t.n_rows == 2 and t.n_cols == 2
    top = [c for c in t.cells if c.row == 0]
    assert len(top) == 1 and top[0].colspan == 2
    assert not any(c.header for c in t.cells)  # Kopfzeile nie nur wegen der Position


# --------------------------------------------------------------------------- Text und Prüfungen


def test_artifacts_and_garbage_are_recognised():
    assert is_artifact("-----") and is_artifact("....") and is_artifact("|") and is_artifact("~~")
    assert not is_artifact("–") and not is_artifact("§") and not is_artifact("1785")
    assert garbage_ratio("poTmmjnnmm7mm nnn mmm mnpm gmp") > 0.5
    assert garbage_ratio("Starosta grodowy zatwierdził przywilej 1785 r.") == 0.0


def test_box_text_is_never_bundled_with_surrounding_text():
    a = LRegion("a", "absatz", (0, 0, 10, 10), 0, "Tekst przed ramką.")
    b = LRegion("b", "absatz", (0, 20, 10, 30), 1, "Tekst w ramce.", container="k1")
    c = LRegion("c", "absatz", (0, 40, 10, 50), 2, "Tekst po ramce.")
    d = LRegion("d", "absatz", (0, 60, 10, 70), 3, "Dalszy tekst.")
    units = build_units([a, b, c, d])
    assert [[r.id for r in u] for u in units] == [["a"], ["b"], ["c", "d"]]


def test_report_flags_residue_and_diagnosis_contains_no_text(tmp_path):
    r1 = LRegion("s1b1", "absatz", (0, 0, 100, 50), 0, "Starosta zatwierdził przywilej.",
                 "Der Starost zatwierdził das Privileg.")
    r2 = LRegion("s1b2", "absatz", (0, 60, 100, 90), 1, "Krótki tekst.", "Kurzer Text.")
    page = LPage(1, 1000, 1400, 300, "x.png", [r1, r2])
    doc = LayoutDocument("q", "Quelle", "druck", str(tmp_path), [page])
    pruefbericht.check_translation(doc)
    rows = pruefbericht.summary(doc)
    assert rows[0][1] == "rot" and any("Ausgangssprache" in i for i in rows[0][2])
    diag = pruefbericht.write_diagnose(doc, tmp_path / "d.json").read_text(encoding="utf-8")
    for word in ("Starosta", "Privileg", "Krótki", "Kurzer"):
        assert word not in diag


def test_neusatz_draws_boxes_with_fill_and_frame(tmp_path):
    from quellenuebersetzer.pipeline.layout_render import build_typst

    r = LRegion("s1b1", "absatz", (120, 120, 800, 300), 0, "Tekst", "Text", container="k1", line_px=40)
    page = LPage(1, 1000, 1400, 300, "x.png", [r],
                 decorations=[{"id": "k1", "box": [100, 100, 900, 400], "fill": "#202d4e", "stroke": "#000000",
                               "dash": "dashed", "stroke_px": 4, "dark": True}])
    doc = LayoutDocument("q", "Quelle", "druck", str(tmp_path), [page])
    src = build_typst(doc, faksimile=False, translated=True, handwriting=False, title="T", appendix=False)
    assert 'fill: rgb("#202d4e")' in src and 'dash: "dashed"' in src


# --------------------------------------------------------------------------- Qualitätsschranken (Ende-zu-Ende)


@pytest.mark.parametrize("name,aged", [("kasten_dunkel", False), ("tabelle_gestrichelt", True),
                                       ("zweispaltig", True), ("tabelle_linien", False),
                                       ("spaltenuebergreifend", True), ("farbige_bloecke", False),
                                       ("tabelle_zebra", True), ("tabelle_mehrzeilig", True),
                                       ("tabelle_spalten", True), ("tabelle_im_kasten", False),
                                       ("farbflaechen", False), ("farbflaechen", True),
                                       ("stadtplan", False), ("stadtplan", True),
                                       ("heller_plan", True), ("seitenleiste", False), ("seitenleiste", True)])
def test_quality_gate_on_hard_pages(tmp_path, tess_root, name, aged):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from layout_messen import measure_page

    from quellenuebersetzer.config import Paths
    from quellenuebersetzer.pipeline.document import PageImage
    from quellenuebersetzer.pipeline.layout_reading import LayoutReader
    from quellenuebersetzer.profile import SourceKind
    from quellenuebersetzer.runtime.layout import LayoutDetector
    from quellenuebersetzer.runtime.tesseract import Tesseract

    det = LayoutDetector(Paths(tess_root))
    if not det.available:
        pytest.skip("Seitenaufbau-Modell nicht in der Testumgebung")
    page = sammlung.build(name, aged)
    cv2.imencode(".png", _bgr(page))[1].tofile(str(tmp_path / "hintergrund-0001.png"))
    reader = LayoutReader(SourceKind.DRUCK, Tesseract(Paths(tess_root)), ["pol"], None, None, detector=det,
                          workdir=tmp_path, extra_scripts=["heb", "yid", "rus"])
    lp = reader.read_regions([reader.detect_page(PageImage(1, tmp_path / "hintergrund-0001.png"))])[0]
    m = measure_page(page, lp, 0.0)
    assert m["bloecke"][0] == m["bloecke"][1]
    assert m["mischung"] == 0 and m["artefakte"] == 0 and m["erfunden"] == 0 and m["ueberlappung"] == 0
    assert m["ueberlappung_aufbau"] == 0  # jeder Bereich eigenständig, auch nach dem Sicherheitsnetz
    assert m["woerter"][0] >= 0.98 * m["woerter"][1]
    if m["tabellen"][2]:
        assert m["tabellen"][1] == m["tabellen"][2] and m["zellen"][0] >= 0.95 * m["zellen"][1]
    if m["gestaltung"][1]:
        assert m["gestaltung"][0] >= 0.9 * m["gestaltung"][1]


def test_wider_or_narrower_blocks_are_never_merged_with_a_column():
    from quellenuebersetzer.runtime.layout import Region, merge_lines

    def column():
        return Region("absatz", (100, 100, 1000, 500), 0.9, 0)

    wide_below = Region("absatz", (100, 520, 2000, 800), 0.9, 1)  # spaltenübergreifend, links bündig
    narrow_below = Region("absatz", (100, 520, 600, 800), 0.9, 1)
    same_below = Region("absatz", (102, 520, 998, 800), 0.9, 1)
    far_below = Region("absatz", (100, 700, 1000, 900), 0.9, 1)  # Absatzabstand größer als eine Zeile
    assert len(merge_lines([column(), wide_below], line_px=40)) == 2
    assert len(merge_lines([column(), narrow_below], line_px=40)) == 2
    assert len(merge_lines([column(), same_below], line_px=40)) == 1
    assert len(merge_lines([column(), far_below], line_px=40)) == 2


def test_model_box_spanning_heading_and_columns_is_split():
    """Ein Rechteck aus Spalten, breitem Farbkasten, Überschrift und wieder Spalten wird an jedem
    Strukturwechsel geteilt – kein Teil enthält zwei Blöcke."""
    from quellenuebersetzer.pipeline.structure import split_structure

    page = sammlung.build("spaltenuebergreifend")
    color = _bgr(page)
    feats = features.analyse(color)
    ink = features.text_ink(cv2.cvtColor(color, cv2.COLOR_BGR2GRAY), feats)
    parts = split_structure((240, 240, 2240, 1900), ink, color, 1.0)
    flows = ("spalte1a", "spalte2a", "kasten1", "zwischen", "spalte1b", "spalte2b")
    truth = {b.flow: b.box for b in page.blocks if b.flow in flows and b.kind != "kasten"}

    def inside(p, b):
        return p[0] <= (b[0] + b[2]) / 2 <= p[2] and p[1] <= (b[1] + b[3]) / 2 <= p[3]

    for flow, box in truth.items():
        hits = [p for p in parts if inside(p, box)]
        assert len(hits) == 1, flow
        assert [f for f, b in truth.items() if inside(hits[0], b)] == [flow]


@pytest.mark.parametrize("name", list(sammlung.PAGE_TYPES))
def test_layout_regions_never_overlap(tmp_path, tess_root, name):
    from quellenuebersetzer.config import Paths
    from quellenuebersetzer.pipeline.document import PageImage
    from quellenuebersetzer.pipeline.layout_reading import LayoutReader
    from quellenuebersetzer.profile import SourceKind
    from quellenuebersetzer.runtime.layout import LayoutDetector

    det = LayoutDetector(Paths(tess_root))
    if not det.available:
        pytest.skip("Seitenaufbau-Modell nicht in der Testumgebung")
    page = sammlung.build(name, aged=True)
    cv2.imencode(".png", _bgr(page))[1].tofile(str(tmp_path / "hintergrund-0001.png"))
    reader = LayoutReader(SourceKind.DRUCK, None, ["pol"], None, None, detector=det, workdir=tmp_path)
    lp = reader.detect_page(PageImage(1, tmp_path / "hintergrund-0001.png"))
    boxes = [r.box for r in lp.regions]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert min(a[2], b[2]) <= max(a[0], b[0]) or min(a[3], b[3]) <= max(a[1], b[1]), (a, b)


def test_zebra_bands_give_row_boundaries_but_text_does_not():
    from quellenuebersetzer.pipeline.preprocess import binarize, enhance
    from quellenuebersetzer.pipeline.tables import shading_cuts

    for aged in (False, True):
        page = sammlung.build("tabelle_zebra", aged)
        t = next(b for b in page.blocks if b.kind == "tabelle")
        x0, y0, x1, y1 = t.box
        sub = _bgr(page)[y0:y1, x0:x1]
        ink = binarize(enhance(cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY))) < 128
        cuts = [y0 + c for c in shading_cuts(sub, ink, 0, 40)]
        expected = [y0 + 78 * i for i in range(1, t.table["rows"])]
        assert len(cuts) == len(expected) and all(abs(a - b) <= 4 for a, b in zip(cuts, expected))
    # Fließtext ohne Hinterlegung: keine Bänder
    page = sammlung.build("zweispaltig")
    b = next(b for b in page.blocks if b.flow == "spalte1")
    sub = _bgr(page)[b.box[1]:b.box[3], b.box[0]:b.box[2]]
    ink = binarize(enhance(cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY))) < 128
    assert shading_cuts(sub, ink, 0, 40) == []


def test_multiline_cell_stays_one_row_but_uniform_band_is_split():
    from quellenuebersetzer.pipeline.tables import split_rows_in_band
    from quellenuebersetzer.runtime.tesseract import Word

    def w(x, y):
        return Word("x", 95, (x, y, x + 50, y + 30))

    # Band 0–200, Spalten an 0|300|600: links zwei Zeilen (umbrochene Zelle), rechts eine → eine Tabellenzeile
    assert split_rows_in_band([w(10, 20), w(10, 60), w(320, 20)], 0, 200, [0, 300, 600], 30) == []
    # alle Spalten zwei Zeilen auf gleicher Höhe → zwei Tabellenzeilen in einem Farbband
    cuts = split_rows_in_band([w(10, 20), w(10, 80), w(320, 21), w(320, 79)], 0, 200, [0, 300, 600], 30)
    assert len(cuts) == 1 and 40 < cuts[0] < 100


def test_shading_inside_a_table_is_not_a_box_and_a_cut_off_column_is_added():
    from quellenuebersetzer.pipeline.features import Panel
    from quellenuebersetzer.pipeline.structure import _reconcile_tables
    from quellenuebersetzer.runtime.layout import Region

    table = Region("tabelle", (250, 520, 1850, 1140), 0.9, 0)
    stripe = Panel((260, 600, 1840, 680), "#e8ecf4")  # Zebrazeile in der Tabelle
    cut_column = Panel((1768, 520, 2144, 1144), "#ebe1ca")  # vom Modell abgeschnittene hinterlegte Spalte
    real_box = Panel((250, 1300, 2230, 1700), "#eee4f2")  # Kasten unterhalb
    regions = [table]
    boxes = {"k1": stripe, "k2": cut_column, "k3": real_box}
    _reconcile_tables(regions, boxes, 3508)
    assert list(boxes) == ["k3"]
    assert table.box[2] == 2144


def test_model_table_covering_a_whole_box_yields_to_the_inner_table():
    from quellenuebersetzer.pipeline.features import Panel
    from quellenuebersetzer.pipeline.structure import _reconcile_tables
    from quellenuebersetzer.runtime.layout import Region

    whole = Region("tabelle", (255, 688, 2219, 1478), 0.48, 0)
    inner = Region("tabelle", (262, 904, 1539, 1373), 0.51, 1)
    regions = [whole, inner]
    _reconcile_tables(regions, {"k1": Panel((260, 648, 2232, 1501), "#ead9b3", "#ae9972", "solid", 6)}, 3508)
    assert regions == [inner]


@pytest.mark.parametrize("aged", [False, True])
def test_color_blocks_of_any_shape_and_position_are_found(aged):
    """Randabfallendes Band, aneinanderstoßende Blöcke (Rot | Grün), abgerundeter Block, Block bis zur Seitenecke."""
    page = sammlung.build("farbflaechen", aged)
    panels = features.analyse(_bgr(page)).panels
    truth = [b for b in page.blocks if b.kind == "kasten"]

    def iou(a, b):
        ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
        inter = ix * iy
        return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)

    for t in truth:
        best = max(panels, key=lambda p: iou(p.box, t.box))
        assert iou(best.box, t.box) > 0.85, t.flow
        assert best.dark == (t.flow in ("band", "rot", "gruen", "ecke")), t.flow  # helle Schrift gemessen
    # kein Rechteck, das Rot und Grün zusammenfasst
    assert not any(p.box[0] < 1000 and p.box[2] > 1500 and 700 < p.box[1] < 800 for p in panels)


def test_white_text_colour_is_measured_from_letter_cores():
    from quellenuebersetzer.pipeline.typography import ink_color

    img = np.zeros((60, 200, 3), np.uint8)
    img[:] = (45, 50, 190)  # Rot (BGR)
    ink = np.zeros((60, 200), np.uint8)
    for x in range(10, 190, 12):
        img[15:45, x:x + 4] = (255, 255, 255)  # weiße Striche
        img[15:45, x + 4:x + 6] = (150, 150, 220)  # vermischte Kantenpixel
        ink[15:45, x:x + 6] = 1
    col = ink_color(img, ink)
    r, g, b = (int(col[i:i + 2], 16) for i in (1, 3, 5))
    assert min(r, g, b) > 230  # weiß, nicht rosa


@pytest.mark.parametrize("aged", [False, True])
def test_map_stays_an_image_even_if_the_model_calls_it_text(aged):
    """Stadtplan mit Straßennamen: auch wenn das Modell ihn als Absatz meldet, bleibt er Abbildung;
    ein Park (Farbfläche) im Plan macht ihn nicht zu Text."""
    from quellenuebersetzer.pipeline import structure
    from quellenuebersetzer.runtime.layout import Region

    page = sammlung.build("stadtplan", aged)
    color = _bgr(page)
    feats = features.analyse(color)
    ink = features.text_ink(cv2.cvtColor(color, cv2.COLOR_BGR2GRAY), feats)
    plan = next(b for b in page.blocks if b.kind == "abbildung").box
    text = next(b for b in page.blocks if b.flow == "text1").box
    for kind in ("absatz", "abbildung"):
        raw = [Region(kind, plan, 0.9, 1), Region("absatz", text, 0.9, 0)]
        regions, _deco = structure.build(raw, feats, ink, color)
        inside = [r for r in regions if r.box[1] >= plan[1] - 10 and r.box[3] <= plan[3] + 10]
        assert [r.kind for r in inside] == ["abbildung"], (kind, [(r.kind, r.box) for r in inside])
        assert any(r.kind == "absatz" and r.box[3] < plan[1] for r in regions)  # Text darüber bleibt Text


def test_graphic_share_separates_drawings_from_text():
    from quellenuebersetzer.pipeline.structure import graphic_share

    page = sammlung.build("stadtplan")
    color = _bgr(page)
    ink = features.text_ink(cv2.cvtColor(color, cv2.COLOR_BGR2GRAY), features.analyse(color))
    plan = next(b for b in page.blocks if b.kind == "abbildung").box
    text = next(b for b in page.blocks if b.flow == "text1").box
    assert graphic_share(plan, ink, 40) > 0.6
    assert graphic_share(text, ink, 40) < 0.05


# --------------------------------------------------------------------------- gedrehte Titel, Namensformen, Unlesbares


def _rotated_title_doc(tmp_path, caption=""):
    from quellenuebersetzer.pipeline.layout_doc import LayoutDocument, LPage, LRegion

    page = sammlung.build("seitenleiste")
    cv2.imencode(".png", _bgr(page))[1].tofile(str(tmp_path / "hintergrund-0001.png"))
    title = LRegion("s1b1", "titel", (183, 245, 303, 814), 0, "Kraków", "Kraków", line_px=103, rotation=90,
                    keep_original=True, caption=caption)
    text = LRegion("s1b2", "absatz", (631, 258, 2222, 541), 1, "Tekst.", "Text.", line_px=40, lines=5)
    lp = LPage(1, 2480, 3508, 300, "hintergrund-0001.png", [title, text], read=True)
    return LayoutDocument("q", "Q", "druck", str(tmp_path), [lp])


def test_place_name_gets_german_form_but_is_not_translated():
    from quellenuebersetzer.pipeline.layout_doc import LayoutDocument, LPage, LRegion
    from quellenuebersetzer.pipeline.layout_translate import LayoutTranslator
    from quellenuebersetzer.pipeline.translate import Translator
    from quellenuebersetzer.runtime.ollama import ChatResult

    class Client:
        def __init__(self):
            self.prompts = []

        def chat(self, model, messages, **kw):
            self.prompts.append(messages[-1]["content"])
            return ChatResult('{"german": "Krakau"}', [])

    title = LRegion("s1b1", "titel", (0, 0, 50, 300), 0, "Kraków", rotation=90, keep_original=True)
    doc = LayoutDocument("q", "Q", "druck", ".", [LPage(1, 100, 400, 300, "x", [title], read=True)])
    client = Client()
    LayoutTranslator(doc, Translator(client, "m", "Polish", "20. Jh.", (1900, 1999))).translate_pages(doc.pages)
    assert title.caption == "(Krakau)" and title.target_md == "Kraków"  # Original bleibt, Ergänzung kommt
    assert len(client.prompts) == 1 and "exonym" in client.prompts[0]
    assert any("Einschätzung des Sprachmodells" in i for i in title.issues)


def test_invented_or_identical_place_names_are_rejected():
    from quellenuebersetzer.pipeline.translate import Translator
    from quellenuebersetzer.runtime.ollama import ChatResult

    class Client:
        def __init__(self, answer):
            self.answer = answer

        def chat(self, model, messages, **kw):
            return ChatResult(self.answer, [])

    assert Translator(Client('{"german": "Kodeń"}'), "m", "Polish", "", (1900, 1999)).german_place_name("Kodeń") == ""
    assert Translator(Client('{"german": ""}'), "m", "Polish", "", (1900, 1999)).german_place_name("Kodeń") == ""
    assert Translator(Client("kein JSON"), "m", "Polish", "", (1900, 1999)).german_place_name("Kodeń") == ""


@pytest.mark.parametrize("faksimile", [True, False])
def test_rotated_title_keeps_original_and_caption_is_set_rotated(tmp_path, tess_root, faksimile):
    from quellenuebersetzer.config import Paths
    from quellenuebersetzer.pipeline import layout_docx, layout_render

    doc = _rotated_title_doc(tmp_path, "(Krakau)")
    src = layout_render.build_typst(doc, faksimile, True, False, "T", appendix=False)
    assert "(Krakau)" in src and "rotate(-90deg" in src
    assert ('original-s1b1.png' in src) != faksimile  # Neusatz: Original als Ausschnitt, Faksimile: Hintergrund
    typst = Paths(tess_root).runtime / "typst" / "typst.exe"
    if typst.exists():
        layout_render.render_pdf(doc, tmp_path / "out.pdf", typst, faksimile=faksimile, title="T")
        assert (tmp_path / "out.pdf").stat().st_size > 1000
    out = layout_docx.build_docx(doc, tmp_path / "out.docx", faksimile=faksimile, title="T")
    import zipfile

    xml = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
    assert 'w:textDirection w:val="btLr"' in xml and "(Krakau)" in xml


def test_illegible_region_is_not_painted_over_in_facsimile(tmp_path):
    from quellenuebersetzer.pipeline.layout_render import erase_text

    doc = _rotated_title_doc(tmp_path)
    page = doc.pages[0]
    page.regions[0].keep_original = True
    erase_text(tmp_path / page.background, page, tmp_path / "f.jpg")
    before = cv2.imread(str(tmp_path / page.background))
    after = cv2.imread(str(tmp_path / "f.jpg"))
    x0, y0, x1, y1 = page.regions[0].box
    diff = np.abs(before[y0:y1, x0:x1].astype(int) - after[y0:y1, x0:x1].astype(int)).mean()
    assert diff < 6  # Original unverändert (nur JPEG-Rauschen)
    x0, y0, x1, y1 = page.regions[1].box
    assert np.abs(before[y0:y1, x0:x1].astype(int) - after[y0:y1, x0:x1].astype(int)).mean() > 6  # Text retuschiert


@pytest.mark.parametrize("aged", [False, True])
def test_pale_map_stays_an_image_even_with_colour_areas_inside(aged):
    """Heller Plan (grauer Grund, weiße Straßen, See) – auch wenn das Modell ihn als Absatz meldet."""
    from quellenuebersetzer.pipeline import structure
    from quellenuebersetzer.runtime.layout import Region

    page = sammlung.build("heller_plan", aged)
    color = _bgr(page)
    feats = features.analyse(color)
    ink = features.text_ink(cv2.cvtColor(color, cv2.COLOR_BGR2GRAY), feats)
    plan = next(b for b in page.blocks if b.kind == "abbildung").box
    for kind in ("absatz", "abbildung"):
        raw = [Region(kind, plan, 0.9, 0)] + [Region("absatz", b.box, 0.9, 1) for b in page.blocks
                                              if b.flow in ("spalte1", "spalte2")]
        regions, deco = structure.build(raw, feats, ink, color)
        inside = [r for r in regions if r.box[1] >= plan[1] - 10 and r.box[3] <= plan[3] + 10]
        assert [r.kind for r in inside] == ["abbildung"], (kind, [(r.kind, r.box) for r in inside])
        assert not any(d["box"][1] >= plan[1] - 10 and d["box"][3] <= plan[3] + 10 for d in deco)


def test_footnote_high_on_the_page_is_not_a_footnote():
    from quellenuebersetzer.pipeline.structure import _margin_rules
    from quellenuebersetzer.runtime.layout import Region

    body = Region("absatz", (600, 200, 2200, 3000), 0.9, 0)
    side = Region("fussnote", (100, 900, 400, 1000), 0.6, 1)  # Seitenleiste, vom Modell als Fußnote gemeldet
    low = Region("fussnote", (600, 3100, 2200, 3200), 0.8, 2)
    _margin_rules([body, side, low], 2480, 3508)
    assert side.kind == "randnotiz" and low.kind == "fussnote"


def test_other_scripts_are_read_word_by_word(tmp_path, tess_root):
    """Namensformen in Jiddisch, Hebräisch, Russisch in einer polnischen Seitenleiste."""
    from quellenuebersetzer.config import Paths
    from quellenuebersetzer.pipeline import markup
    from quellenuebersetzer.pipeline.document import PageImage
    from quellenuebersetzer.pipeline.layout_reading import LayoutReader
    from quellenuebersetzer.profile import SourceKind
    from quellenuebersetzer.runtime.layout import LayoutDetector
    from quellenuebersetzer.runtime.tesseract import Tesseract

    det = LayoutDetector(Paths(tess_root))
    tess = Tesseract(Paths(tess_root))
    if not det.available or not (tess.tessdata / "heb.traineddata").exists():
        pytest.skip("Seitenaufbau-Modell oder Schriftmodelle nicht in der Testumgebung")
    page = sammlung.build("seitenleiste")
    cv2.imencode(".png", _bgr(page))[1].tofile(str(tmp_path / "hintergrund-0001.png"))
    reader = LayoutReader(SourceKind.DRUCK, tess, ["pol", "lat", "deu"], None, None, detector=det, workdir=tmp_path,
                          extra_scripts=["heb", "yid", "rus"])
    lp = reader.read_regions([reader.detect_page(PageImage(1, tmp_path / "hintergrund-0001.png"))])[0]
    text = " ".join(markup.unescape_md(markup.strip_marks(r.source_md)) for r in lp.regions)
    for word in ("קראקע", "קרקוב", "Краков", "Kraków"):
        assert word in text, word
    title = next(r for r in lp.regions if r.rotation)
    assert title.keep_original and title.rotation == 90


def test_vertical_title_missed_by_the_model_is_collected(tmp_path, tess_root):
    """Vollständigkeit: Meldet das Layoutmodell den senkrechten Titel gar nicht, wird er eingesammelt."""
    from quellenuebersetzer.config import Paths
    from quellenuebersetzer.pipeline.document import PageImage
    from quellenuebersetzer.pipeline.layout_reading import LayoutReader
    from quellenuebersetzer.profile import SourceKind
    from quellenuebersetzer.runtime.layout import LayoutDetector
    from quellenuebersetzer.runtime.tesseract import Tesseract

    det = LayoutDetector(Paths(tess_root))
    if not det.available:
        pytest.skip("Seitenaufbau-Modell nicht in der Testumgebung")
    page = sammlung.build("seitenleiste")
    cv2.imencode(".png", _bgr(page))[1].tofile(str(tmp_path / "hintergrund-0001.png"))
    reader = LayoutReader(SourceKind.DRUCK, Tesseract(Paths(tess_root)), ["pol", "lat", "deu"], None, None,
                          detector=det, workdir=tmp_path)
    lp = reader.detect_page(PageImage(1, tmp_path / "hintergrund-0001.png"))
    lp.regions = [r for r in lp.regions if r.box[2] > 400 or r.box[1] > 820]  # Titel „übersehen“
    lp = reader.read_regions([lp])[0]
    titles = [r for r in lp.regions if r.rotation]
    assert len(titles) == 1 and "Kraków" in titles[0].source_md and titles[0].keep_original


def test_rotated_capitals_read_horizontally_do_not_beat_real_words():
    from quellenuebersetzer.pipeline.layout_reading import _rotation_wins
    from quellenuebersetzer.runtime.tesseract import Line, Word

    def line(*words):
        return Line([Word(t, c, (0, 0, 1, 1)) for t, c in words], (0, 0, 1, 1), 0, 0)

    horizontal = [line(("m", 65), ("O", 89), ("E", 76), ("N", 94), ("Te", 87), ("Ui", 88), ("AS", 56))]
    rotated = [line(("Jeziorzany", 72), ("(Łysobyki)", 68))]
    assert _rotation_wins(rotated, horizontal)
    assert not _rotation_wins(horizontal, rotated)
    assert not _rotation_wins([line(("Ab", 99))], [])  # keine echten Wörter
