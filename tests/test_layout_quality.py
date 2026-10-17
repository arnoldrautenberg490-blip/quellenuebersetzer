"""Qualität der Layoutkopie: Einpassen (Zeilenabstand vor Schriftgröße), Gestaltung, keine Überschneidungen."""

import pytest
from PIL import Image, ImageDraw

from conftest import SAMPLE_PL, font
from quellenuebersetzer.pipeline.fitting import LEADING_MIN, LEADING_NORMAL, expand_boxes, fit_text
from quellenuebersetzer.pipeline.layout_doc import LRegion

TEXT_PL = "Starosta grodowy zatwierdził przywilej dla cechu młynarzy i nakazał, aby każdy młyn płacił dwa złote rocznie."
TEXT_DE = ("Der Burgstarost bestätigte das Privileg für die Zunft der Müller und ordnete an, dass jede Mühle "
           "jährlich zwei Złoty zahle, und zwar pünktlich zum Martinstag des laufenden Jahres.")


def test_fitting_reduces_leading_before_font_size():
    # Höhe so gewählt, dass der Text bei normalem Zeilenabstand knapp nicht passt
    loose = fit_text(TEXT_DE, (0, 0, 200, 400), 11.0)
    assert loose.leading == LEADING_NORMAL and loose.size == 11.0 and not loose.truncated
    from quellenuebersetzer.pipeline.fitting import lines_needed

    n = lines_needed(TEXT_DE.split(), 200, 11.0, False, False, 0.0)
    tight = fit_text(TEXT_DE, (0, 0, 200, n * 11.0 * 1.06), 11.0)
    assert tight.size == 11.0 and LEADING_MIN <= tight.leading < LEADING_NORMAL  # erst Zeilenabstand


def test_text_that_cannot_fit_is_shortened_not_overflowing():
    fit = fit_text(TEXT_DE * 6, (0, 0, 120, 30), 11.0)
    assert fit.truncated and fit.text_md.endswith("\\[…\\]")
    assert fit.size >= 11.0 * 0.6 - 0.01


def test_boxes_grow_into_free_space_but_never_into_next_block():
    a = LRegion("a", "absatz", (100, 100, 900, 200), 0, "x")
    b = LRegion("b", "absatz", (100, 260, 900, 400), 1, "x")
    img = LRegion("c", "abbildung", (100, 700, 900, 1000), 2)
    boxes = expand_boxes([a, b, img], page_h_px=1400)
    assert boxes["a"][3] <= 260 and boxes["a"][3] > 200  # wächst bis kurz vor b
    assert boxes["b"][3] <= 700  # nie in die Abbildung
    assert boxes["c"] == img.box


def _styled_page(path):
    img = Image.new("RGB", (1700, 1200), (246, 242, 234))
    d = ImageDraw.Draw(img)
    d.text((150, 100), "ROZDZIAŁ PIERWSZY", font=font("timesbd.ttf", 60), fill=(170, 30, 25))  # rote Rubrik
    for i in range(6):
        d.text((150, 260 + i * 70), SAMPLE_PL[i % 4], font=font(size=42), fill=(25, 22, 20))
    d.text((150, 760), "O młynach i cechach", font=font("timesbd.ttf", 48), fill=(25, 22, 20))  # fett
    img.save(path)
    return path


def test_color_and_bold_are_measured(tmp_path):
    import cv2
    import numpy as np

    from quellenuebersetzer.pipeline.preprocess import binarize, enhance
    from quellenuebersetzer.pipeline.typography import bold_flags, measure

    color = cv2.imread(str(_styled_page(tmp_path / "s.png")))
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    binary = binarize(enhance(gray))
    boxes = {"rubrik": (140, 90, 900, 170), "text": (140, 250, 1500, 690), "fett": (140, 750, 900, 820)}
    line_px = {"rubrik": 60, "text": 42, "fett": 48}
    styles = {k: measure(color[y0:y1, x0:x1], binary[y0:y1, x0:x1], line_px[k]) for k, (x0, y0, x1, y1) in boxes.items()}
    assert styles["rubrik"].color  # farbig erkannt
    r, g, b = (int(styles["rubrik"].color[i:i + 2], 16) for i in (1, 3, 5))
    assert r > g + 40 and r > b + 40  # rot
    assert not styles["text"].color  # normale Schrift bleibt ohne Farbe
    flags = bold_flags([styles["text"].stroke, styles["text"].stroke * 1.02, styles["fett"].stroke])
    assert flags == [False, False, True]


def test_rendered_layout_has_no_overlapping_text(tmp_path, tess_root):
    """Seitengetreues PDF: alle Textrahmen einer Seite sind überschneidungsfrei."""
    from itertools import combinations

    from conftest import make_mixed_page
    from quellenuebersetzer.config import Paths
    from quellenuebersetzer.pipeline.document import PageImage
    from quellenuebersetzer.pipeline.layout_reading import LayoutReader
    from quellenuebersetzer.profile import SourceKind
    from quellenuebersetzer.runtime.layout import LayoutDetector
    from quellenuebersetzer.runtime.tesseract import Tesseract

    det = LayoutDetector(Paths(tess_root))
    if not det.available:
        pytest.skip("Seitenaufbau-Modell nicht in der Testumgebung")
    reader = LayoutReader(SourceKind.DRUCK, Tesseract(Paths(tess_root)), ["pol"], None, None, detector=det,
                          workdir=tmp_path)
    page = reader.read_layout([PageImage(1, make_mixed_page(tmp_path / "m.png"))])[0]
    boxes = expand_boxes(page.regions, page.height_px)
    for a, b in combinations(page.regions, 2):
        ba, bb = boxes[a.id], boxes[b.id]
        overlap_w = min(ba[2], bb[2]) - max(ba[0], bb[0])
        overlap_h = min(ba[3], bb[3]) - max(ba[1], bb[1])
        assert overlap_w <= 0 or overlap_h <= 0, (a.kind, ba, b.kind, bb)
