from quellenuebersetzer.pipeline import markup
from quellenuebersetzer.ui import review_text

MD = (
    "<!-- Seite 1 -->\n\n## PRZYWILEJ\n\n"
    "Starosta " + markup.mark_reading("grodowy", ["grodowy", "grodawy"], 0.5) + " płacił 2 \\* złote "
    + markup.mark_reading("rocznie", ["rocznie"], 0.4) + ".\n"
)


def test_roundtrip_unchanged():
    text, marks = review_text.to_editor(MD)
    assert "⟦grodowy⟧¹" in text and "── Seite 1 ──" in text and "{.a" not in text
    assert review_text.from_editor(text, marks) == MD


def test_resolving_a_mark_removes_it():
    text, marks = review_text.to_editor(MD)
    text = text.replace("⟦grodowy⟧¹", "grodowy")
    out = review_text.from_editor(text, marks)
    found = markup.find_marks(out)
    assert len(found) == 1 and found[0][2].text == "rocznie"


def test_corrected_text_inside_mark_is_kept():
    text, marks = review_text.to_editor(MD)
    out = review_text.from_editor(text.replace("⟦grodowy⟧¹", "⟦grodzki⟧¹"), marks)
    mk = markup.find_marks(out)[0][2]
    assert mk.text == "grodzki" and mk.attrs["lesarten"] == "grodowy|grodawy"


def test_benchmark_transcript_core_ignores_frame():
    from quellenuebersetzer import beispiel
    from quellenuebersetzer.pipeline.export import DocMeta, build_document
    from quellenuebersetzer.ui.workers import _core, transcript_core

    body = "<!-- Seite 1 -->\n\n## PRZYWILEJ CECHOWY\n\n" + "\n\n".join(beispiel.TEXT) + "\n\n<table><tr><td>Miejscowość</td></tr></table>\n"
    doc = build_document(body, DocMeta("t", "t.png", "Polnisch", "18. Jh.", "Druck", ["m"], False), translated=False)
    core = transcript_core(doc)
    assert core.startswith(_core("PRZYWILEJ CECHOWY Akta miasta"))
    assert "quelle" not in core and "verwendete" not in core
