import json

from quellenuebersetzer.pipeline import markup
from quellenuebersetzer.pipeline.tables import Cell, Table
from quellenuebersetzer.pipeline.translate import Segment, Translator, split_segments
from quellenuebersetzer.runtime.ollama import ChatResult


class ScriptedClient:
    """Liefert vorgegebene Antworten nacheinander und merkt sich die Anfragen."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []

    def chat(self, model, messages, **kw):
        self.requests.append(messages)
        a = self.answers.pop(0) if self.answers else {"translation": "", "readings": [], "terms": []}
        return ChatResult(a if isinstance(a, str) else json.dumps(a, ensure_ascii=False), [])


def _tr(client):
    return Translator(client, "m", "Polish", "18. Jahrhundert", (1700, 1799))


def test_untranslated_answer_is_retried():
    c = ScriptedClient([
        {"translation": "Przywilej cechowy młynarzy", "readings": [], "terms": []},
        {"translation": "Zunftprivileg der Müller", "readings": [], "terms": []},
    ])
    out = _tr(c).translate_segment(Segment("ueberschrift", "Przywilej cechowy młynarzy"))
    assert out == "Zunftprivileg der Müller" and len(c.requests) == 1 or "untranslated" in json.dumps(c.requests[-1])


def test_missing_reading_tag_triggers_retry_and_readings_are_kept():
    src = "każdy " + markup.mark_reading("młyn", ["młyn", "mur"], 0.5) + " płacił"
    c = ScriptedClient([
        {"translation": "jede Mühle zahlte", "readings": [], "terms": []},  # Tag fehlt
        {"translation": "jede <a_1>Mühle</a_1> zahlte", "readings": [{"id": "a_1", "translations": ["Mühle", "Mauer"]}],
         "terms": []},
    ])
    out = _tr(c).translate_segment(Segment("text", src))
    mk = markup.find_marks(out)[0][2]
    assert mk.text == "Mühle" and mk.attrs["lesarten_de"] == "Mühle|Mauer" and mk.attrs["lesarten"] == "młyn|mur"
    assert "exactly once" in c.requests[-1][-1]["content"]


def test_b2_term_is_marked_with_evidence_flag():
    c = ScriptedClient([{
        "translation": "Der <b2_1>Starost</b2_1> bestätigte das Privileg.", "readings": [],
        "terms": [{"id": "b2_1", "original": "starosta", "explanation": "königlicher Amtsträger", "evidence": ""}],
    }])
    out = _tr(c).translate_segment(Segment("text", "Starosta zatwierdził przywilej."))
    mk = markup.find_marks(out)[0][2]
    assert mk.category == "b2" and mk.attrs["original"] == "starosta" and "ohne Wörterbuchbeleg" in mk.attrs["beleg"]


def test_table_fallback_translates_cells_with_column_context():
    table = Table(2, 2, [Cell(0, 0, markdown="Miejscowość", header=True), Cell(0, 1, markdown="Złote", header=True),
                         Cell(1, 0, markdown="Bronowice"), Cell(1, 1, markdown="6")]).to_html()
    broken = {"translation": "<table><tr><td>kaputt</td></tr></table>", "readings": [], "terms": []}
    cells = [{"translation": "Ort", "readings": [], "terms": []}, {"translation": "Złoty", "readings": [], "terms": []},
             {"translation": "Bronowice", "readings": [], "terms": []}]
    c = ScriptedClient([broken, broken] + cells)
    out = _tr(c).translate_segment(Segment("tabelle", table))
    assert "<th>Ort</th>" in out and "<th>Złoty</th>" in out and "<td>6</td>" in out
    second_cell_prompt = c.requests[3][-1]["content"]
    assert "Miejscowość | Złote" in second_cell_prompt and 'column "Złote"' in second_cell_prompt


def test_split_segments_roundtrip_kinds():
    md = "<!-- Seite 1 -->\n\n## Titel\n\n> *Randnotiz:* am Rand\n\nText.\n\n<table>\n<tr><td>a</td></tr>\n</table>\n"
    kinds = [s.kind for s in split_segments(md)]
    assert kinds == ["roh", "ueberschrift", "randnotiz", "text", "tabelle"]


def test_malformed_and_excessive_marks_are_rejected_then_cleaned():
    src = "Akta miasta Krakowa z roku 1785. Starosta grodowy zatwierdził przywilej."
    bad = {"translation": "Die <b2_N1>Akten</b2_N1> der Stadt <b2_N2>Krakau</b2_N2> (Krakowa) aus dem Jahr 1785.",
           "readings": [], "terms": []}
    c = ScriptedClient([bad, bad, {"translation": "Akten der Stadt Krakau aus dem Jahr 1785. Der Starost bestätigte das Privileg."}])
    out = _tr(c).translate_segment(Segment("text", src))
    feedback = c.requests[1][-1]["content"]
    assert "Malformed tags" in feedback and "parenthetical" in feedback
    assert "<b2_N" not in out and "b2_" not in out  # Rückfall ohne Rohzeichen


def test_untranslated_table_header_is_detected():
    from quellenuebersetzer.pipeline.translate import _header_untranslated

    src = "<table>\n<tr><th>Miejscowość</th><th>Młyny</th></tr>\n<tr><td>Bronowice</td><td>3</td></tr>\n</table>"
    assert _header_untranslated(src, src)
    assert not _header_untranslated(src, src.replace("Miejscowość", "Ort").replace("Młyny", "Mühlen"))


def _ldoc(*regions):
    from quellenuebersetzer.pipeline.layout_doc import LayoutDocument, LPage, LRegion

    page = LPage(1, 1000, 1400, 300, "bg.png", [LRegion(f"s1b{i}", k, (0, i * 10, 10, i * 10 + 5), i, src)
                                                for i, (k, src) in enumerate(regions)])
    return LayoutDocument("x", "x", "druck", ".", [page])


def test_consecutive_paragraphs_are_translated_as_one_unit_and_split_back():
    from quellenuebersetzer.pipeline.layout_translate import translate_layout

    doc = _ldoc(("absatz", "Starosta grodowy zatwierdził"), ("kopfzeile", "Kronika"),
                ("absatz", "przywilej dla cechu."), ("absatz", "Świadkowie byli obecni."))
    c = ScriptedClient([
        {"translation": "Chronik", "readings": [], "terms": []},  # Kopfzeile eigenständig
        {"translation": "Der Burgstarost bestätigte <split_1/> das Privileg der Zunft. <split_2/> Zeugen waren anwesend.",
         "readings": [], "terms": []},
    ])
    translate_layout(doc, _tr(c))
    r = doc.pages[0].regions
    assert r[0].target_md == "Der Burgstarost bestätigte" and r[2].target_md == "das Privileg der Zunft."
    assert r[3].target_md == "Zeugen waren anwesend." and r[1].target_md == "Chronik"
    assert len(c.requests) == 2  # drei Absätze in EINER Anfrage
    assert "<split_2/>" in c.requests[1][-1]["content"]


def test_lost_marker_is_retried_then_falls_back_and_running_heads_are_cached():
    from quellenuebersetzer.pipeline.layout_translate import translate_layout

    doc = _ldoc(("kopfzeile", "Kronika miasta"), ("absatz", "Starosta grodowy zatwierdził"),
                ("absatz", "przywilej dla cechu."), ("kopfzeile", "Kronika miasta"))
    lost = {"translation": "Der Starost bestätigte das Privileg der Zunft.", "readings": [], "terms": []}
    c = ScriptedClient([
        {"translation": "Stadtchronik", "readings": [], "terms": []},
        lost, lost, lost,  # Marke fehlt: zweiter Versuch, dann vereinfachter Rückfall des Übersetzers
        {"translation": "Der Starost bestätigte", "readings": [], "terms": []},
        {"translation": "das Privileg der Zunft.", "readings": [], "terms": []},
    ])
    translate_layout(doc, _tr(c))
    r = doc.pages[0].regions
    assert r[1].target_md == "Der Starost bestätigte" and r[2].target_md == "das Privileg der Zunft."
    assert r[3].target_md == "Stadtchronik"  # Kolumnentitel nur einmal übersetzt
    assert "same order" in c.requests[2][-1]["content"]  # Rückmeldung an das Modell beim zweiten Versuch


def test_units_break_at_headings_and_respect_size():
    from quellenuebersetzer.pipeline.layout_translate import build_units

    doc = _ldoc(("absatz", "a" * 1000), ("absatz", "b" * 1000), ("ueberschrift", "Rozdział II"),
                ("absatz", "c" * 100), ("tabelle", "<table></table>"), ("absatz", "d" * 100))
    units = build_units(doc.pages[0].regions)
    assert [[r.kind for r in u] for u in units] == [["absatz"], ["absatz"], ["ueberschrift"], ["absatz"],
                                                     ["tabelle"], ["absatz"]]


def test_pages_are_reported_in_order_when_finished():
    from quellenuebersetzer.pipeline.layout_doc import LayoutDocument, LPage, LRegion
    from quellenuebersetzer.pipeline.layout_translate import translate_layout

    pages = [LPage(n, 100, 100, 300, "bg", [LRegion(f"s{n}b1", "absatz", (0, 0, 1, 1), 0, f"Tekst strony {n}.")])
             for n in (1, 2, 3)]
    pages.append(LPage(4, 100, 100, 300, "bg", [LRegion("s4b1", "abbildung", (0, 0, 1, 1), 0)]))
    doc = LayoutDocument("x", "x", "druck", ".", pages)
    c = ScriptedClient([{"translation": f"Text der Seite {n}.", "readings": [], "terms": []} for n in (1, 2, 3)])
    done = []
    translate_layout(doc, _tr(c), on_page_done=lambda p: done.append(p.number))
    assert done == [1, 2, 3, 4]


def test_changed_table_numbers_are_rejected():
    table = Table(2, 2, [Cell(0, 0, markdown="Miejscowość", header=True), Cell(0, 1, markdown="Złote", header=True),
                         Cell(1, 0, markdown="Bronowice"), Cell(1, 1, markdown="6")]).to_html()
    invented = {"translation": table.replace("Miejscowość", "Ort").replace("Złote", "Złoty").replace(">6<", ">60<"),
                "readings": [], "terms": []}
    correct = {"translation": table.replace("Miejscowość", "Ort").replace("Złote", "Złoty"), "readings": [], "terms": []}
    c = ScriptedClient([invented, correct])
    out = _tr(c).translate_segment(Segment("tabelle", table))
    assert ">6<" in out and ">60<" not in out
    assert "Numbers changed in table cells [4]" in c.requests[1][-1]["content"]


def test_changed_years_in_text_are_rejected():
    c = ScriptedClient([
        {"translation": "Akten der Stadt Krakau aus dem Jahr 1758.", "readings": [], "terms": []},
        {"translation": "Akten der Stadt Krakau aus dem Jahr 1785.", "readings": [], "terms": []},
    ])
    out = _tr(c).translate_segment(Segment("text", "Akta miasta Krakowa z roku 1785."))
    assert "1785" in out and "Numbers" in c.requests[1][-1]["content"]
