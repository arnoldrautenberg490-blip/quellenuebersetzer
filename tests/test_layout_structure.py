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
                                       ("zweispaltig", True), ("tabelle_linien", False)])
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
    assert m["woerter"][0] >= 0.98 * m["woerter"][1]
    if m["tabellen"][2]:
        assert m["tabellen"][1] == m["tabellen"][2] and m["zellen"][0] >= 0.95 * m["zellen"][1]
    if m["gestaltung"][1]:
        assert m["gestaltung"][0] >= 0.9 * m["gestaltung"][1]
