from quellenuebersetzer.pipeline import fusion, markup
from quellenuebersetzer.runtime.tesseract import Line, Word


def _line(words_confs):
    words = [Word(w, c, (i * 10, 0, i * 10 + 9, 10)) for i, (w, c) in enumerate(words_confs)]
    return Line(words, (0, 0, 100, 10), 1, 1)


def test_mark_roundtrip():
    md = "Der " + markup.mark_reading("Mühle", ["Mühle", "Mauer"], 0.6) + " stand [hier]."
    marks = markup.find_marks(md)
    assert len(marks) == 1
    assert marks[0][2].attrs["lesarten"] == "Mühle|Mauer"
    assert markup.strip_marks(md) == "Der Mühle stand [hier]."


def test_tags_roundtrip_markdown_and_html():
    md = "A " + markup.mark_reading("x*y", ["x*y", "xy"], 0.5) + " B"
    tagged = markup.to_tags(md)
    assert "<a_1>" in tagged.text and tagged.marks["a_1"].text == "x*y"
    back = markup.from_tags(tagged.text, tagged.marks)
    assert markup.find_marks(back)[0][2].attrs["lesarten"] == "x*y|xy"

    cell = markup.markdown_cell_to_html("3 " + markup.mark_reading("<5>", ["<5>", "6"], 0.4))
    assert '<span class="a"' in cell and "&lt;5&gt;" in cell
    t = markup.to_tags(cell, html=True)
    assert t.marks["a_1"].text == "<5>"
    assert markup.from_tags(t.text, t.marks, html=True).count('<span class="a"') == 1


def test_attribute_quotes_are_neutralised():
    md = markup.mark_reading('a"b', ['a"b'], 0.1)
    assert markup.find_marks(md), md


def test_fusion_agreement_is_unmarked():
    res = fusion.fuse_line(_line([("Starosta", 50), ("grodowy", 40)]), "Starosta grodowy")
    assert res.marks == 0 and res.markdown == "Starosta grodowy"


def test_fusion_disagreement_is_marked_with_both_readings():
    res = fusion.fuse_line(_line([("Starosta", 95), ("grodawy", 40)]), "Starosta grodowy")
    assert res.marks == 1
    attrs = markup.find_marks(res.markdown)[0][2].attrs
    assert set(attrs["lesarten"].split("|")) == {"grodowy", "grodawy"}


def test_fusion_confident_judge_resolves_for_print_but_not_strict():
    judge = lambda opts: (1, opts[1], 0.95)
    res = fusion.fuse_line(_line([("młyn", 70), ("pIacił", 40)]), "młyn płacił", judge)
    assert res.marks == 0 and "płacił" in res.markdown
    strict = fusion.fuse_line(_line([("młyn", 70), ("pIacił", 40)]), "młyn płacił", judge, strict=True)
    assert strict.marks == 1


def test_fusion_rejects_hallucinated_second_reading():
    res = fusion.fuse_line(_line([("dwa", 90), ("złote", 90)]), "dwa złote " + "i jeszcze bardzo długi wymyślony tekst " * 3)
    assert res.marks == 0 and res.markdown == "dwa złote"


def test_single_reader_marks_low_confidence():
    res = fusion.fuse_line(_line([("dwa", 95), ("zł0te", 30)]), None)
    assert res.marks == 1


def test_long_s_is_not_a_difference():
    res = fusion.fuse_line(_line([("ſtaroſta", 80)]), "starosta")
    assert res.marks == 0


def test_join_lines_dehyphenates():
    assert fusion.join_lines(["przy-", "wilej dla"]) == "przywilej dla"
    assert fusion.join_lines(["Kraków -", "Warszawa"]) == "Kraków - Warszawa"
