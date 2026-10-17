import zipfile

import pytest

from quellenuebersetzer.config import Paths
from quellenuebersetzer.pipeline import markup
from quellenuebersetzer.pipeline.export import DocMeta, Exporter, build_document, marks_index
from quellenuebersetzer.pipeline.tables import Cell, Table

BODY = (
    "<!-- Seite 1 -->\n\n## Zunftprivileg\n\n"
    "Der " + markup.Mark("b2", "Starost", {"original": "starosta", "erkl": "königlicher Amtsträger", "beleg": "Gloger"}).to_markdown()
    + " bestätigte das Privileg der Müllerzunft und ordnete an, dass jede "
    + markup.Mark("a", "Mühle", {"lesarten": "młyn|mur", "lesarten_de": "Mühle|Mauer", "sicher": "0.60"}).to_markdown()
    + " jährlich zwei Złoty zahlt. Das "
    + markup.Mark("b1", "Gemach", {"original": "komnata", "damals": "Wohnraum", "heute": "Ruhe", "erkl": "", "beleg": "Linde"}).to_markdown()
    + " blieb unberührt.\n\n"
    + Table(3, 3, [
        Cell(0, 0, markdown="Ort", header=True), Cell(0, 1, 1, 2, markdown="Abgaben", header=True),
        Cell(1, 0, markdown="Bronowice"), Cell(1, 1, markdown="3"),
        Cell(1, 2, markdown=markup.mark_reading("6", ["6", "8"], 0.5)),
        Cell(2, 0, markdown="Summe"), Cell(2, 1, markdown="3"), Cell(2, 2, markdown="6"),
    ]).to_html()
    + "\n\n<!-- Seite 2 -->\n\nZeugen: Jan Kowalski.\n"
)

META = DocMeta("Testquelle", "test.png", "Polnisch", "18. Jahrhundert", "Sauberer Druck", ["gemma4:12b-it-qat"], True)


def test_index_lists_all_categories_with_pages():
    idx = marks_index(BODY)
    assert "Lesung unsicher (2)" in idx  # eine im Text, eine in der Tabelle
    assert "Bedeutungswandel (1)" in idx and "Begriff der Zeit (1)" in idx
    assert "S. 1:" in idx


def test_document_contains_warnings():
    doc = build_document(BODY, META, translated=True)
    assert "Warnhinweis Handschrift" in doc
    assert "ersetzt keine qualifizierte menschliche Übersetzung" in doc
    assert "aus dem Polnischen" in doc


@pytest.mark.parametrize("fmt", ["docx", "pdf", "epub"])
def test_export_formats(tmp_path, tess_root, fmt):
    exporter = Exporter(Paths(tess_root))
    if not exporter.available:
        pytest.skip("Pandoc nicht installiert")
    md = tmp_path / "dok.md"
    md.write_text(build_document(BODY, META, translated=True), encoding="utf-8")
    out = exporter.convert(md, fmt, tmp_path / "Ergebnis – Übersetzung" / f"dok.{fmt}")
    assert out.exists() and out.stat().st_size > 1000
    if fmt == "docx":
        with zipfile.ZipFile(out) as z:
            xml = z.read("word/document.xml").decode("utf-8")
            notes = z.read("word/footnotes.xml").decode("utf-8")
        assert "Bronowice" in xml and 'w:gridSpan w:val="2"' in xml  # Tabelle mit verbundener Zelle
        assert "Mögliche Lesarten" in notes and "Begriff der Zeit" in notes and "Bedeutungswandel" in notes
        assert "[S. 1]" in xml
    if fmt == "epub":
        with zipfile.ZipFile(out) as z:
            html = " ".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xhtml"))
        assert "mark-a" in html and "colspan" in html
