"""Word-Quellen seitengetreu übersetzen: Der Text wird direkt in einer Kopie der Datei ersetzt.

Absatzformate, Tabellen, Bilder, Kopf- und Fußzeilen, Seitenränder und Umbrüche bleiben erhalten.
Innerhalb eines Absatzes übernimmt der übersetzte Text die Zeichenformatierung des ersten Textlaufs
(unterschiedliche Formatierungen innerhalb eines Absatzes können dabei vereinheitlicht werden).
Markierte Begriffe erhalten die Formatvorlagen der Markierungen und eine hochgestellte Anmerkungsnummer;
die Erläuterungen stehen im Anhang „Anmerkungen“ am Ende.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Callable

from docx import Document
from docx.oxml.ns import qn

from quellenuebersetzer.pipeline import markup
from quellenuebersetzer.pipeline.layout_render import Notes
from quellenuebersetzer.pipeline.markup import escape_md
from quellenuebersetzer.pipeline.translate import Segment, Translator
from quellenuebersetzer.planner import GENERAL_DISCLAIMER

STYLE_NAMES = {"a": "Lesung unsicher", "b1": "Bedeutungswandel", "b2": "Begriff der Zeit"}


def _paragraphs(doc) -> list:
    """Alle Absätze: Haupttext, Tabellenzellen (auch verschachtelt), Kopf- und Fußzeilen."""
    seen, out = set(), []

    def add(p):
        if id(p._p) not in seen:
            seen.add(id(p._p))
            out.append(p)

    def walk_tables(tables):
        for t in tables:
            for row in t.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        add(p)
                    walk_tables(cell.tables)

    for p in doc.paragraphs:
        add(p)
    walk_tables(doc.tables)
    for section in doc.sections:
        for part in (section.header, section.footer):
            for p in part.paragraphs:
                add(p)
            walk_tables(part.tables)
    return out


def _ensure_styles(doc) -> dict[str, str]:
    from docx.enum.style import WD_STYLE_TYPE
    from docx.shared import RGBColor

    colors = {"a": "B35C00", "b1": "3B5BA9", "b2": "2F7D6D"}
    ids = {}
    for cat, name in STYLE_NAMES.items():
        try:
            st = doc.styles[name]
        except KeyError:
            st = doc.styles.add_style(name, WD_STYLE_TYPE.CHARACTER)
            st.font.color.rgb = RGBColor.from_string(colors[cat])
            st.font.underline = True
        ids[cat] = st.style_id
    return ids


def _replace_text(paragraph, md: str, notes: Notes, style_ids: dict[str, str]) -> None:
    runs = [r for r in paragraph.runs if r.text]
    if not runs:
        return
    template = runs[0]._r
    for r in runs:
        r._r.getparent().remove(r._r)

    def new_run(text: str, style: str | None = None, superscript: bool = False):
        r = copy.deepcopy(template)
        for t in r.findall(qn("w:t")):
            r.remove(t)
        rpr = r.find(qn("w:rPr"))
        if rpr is None:
            rpr = r.makeelement(qn("w:rPr"), {})
            r.insert(0, rpr)
        if style:
            el = rpr.makeelement(qn("w:rStyle"), {qn("w:val"): style})
            rpr.insert(0, el)
        if superscript:
            rpr.append(rpr.makeelement(qn("w:vertAlign"), {qn("w:val"): "superscript"}))
        t = r.makeelement(qn("w:t"), {"{http://www.w3.org/XML/1998/namespace}space": "preserve"})
        t.text = text
        r.append(t)
        paragraph._p.append(r)

    pos = 0
    for start, end, mark in markup.find_marks(md):
        if start > pos:
            new_run(markup.unescape_md(md[pos:start]))
        new_run(mark.text, style_ids.get(mark.category))
        new_run(str(notes.add(mark)), superscript=True)
        pos = end
    if pos < len(md):
        new_run(markup.unescape_md(md[pos:]))


def translate_docx(src: Path, out: Path, tr: Translator, progress: Callable[[int, int], None] | None = None) -> Path:
    doc = Document(str(src))
    style_ids = _ensure_styles(doc)
    notes = Notes(page="–")
    paragraphs = [p for p in _paragraphs(doc) if p.text.strip()]
    cache: dict[str, str] = {}
    previous = None
    for i, p in enumerate(paragraphs, start=1):
        if progress:
            progress(i, len(paragraphs))
        source = escape_md(p.text.strip())
        if source in cache:
            target = cache[source]
        else:
            style = (p.style.name or "").lower() if p.style is not None else ""
            kind = "ueberschrift" if style.startswith(("heading", "überschrift", "title", "titel")) else "text"
            target = tr.translate_segment(Segment(kind, source), previous)
            cache[source] = target
            previous = (p.text.strip(), markup.strip_marks(target))
        _replace_text(p, target, notes, style_ids)

    doc.add_page_break()
    doc.add_paragraph().add_run("Hinweis: ").bold = True
    doc.paragraphs[-1].add_run(GENERAL_DISCLAIMER)
    if notes.items:
        doc.add_paragraph().add_run("Anmerkungen").bold = True
        for _page, n, text in notes.items:
            doc.add_paragraph(f"Anm. {n}: {text}")
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out
