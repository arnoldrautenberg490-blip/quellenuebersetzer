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
                                       ("tabelle_spalten", True), ("tabelle_im_kasten", False)])
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
                          workdir=tmp_path)
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
