"""Markierungen im Markdown (Pandoc-Spans) und ihre Umwandlung für die Übersetzung.

Kategorien:
  A  – Lesung unsicher         ``[Mühle]{.a lesarten="Mühle|Mauer" sicher="0.60"}``
  B1 – Bedeutungswandel        ``[Gemach]{.b1 damals="…" heute="…" beleg="…"}``
  B2 – Begriff der Zeit        ``[Starost]{.b2 erkl="…" beleg="…"}``

Für das Sprachmodell werden die Spans in einfache Tags ``<a1>…</a1>`` übersetzt, deren
Attribute separat verwaltet werden. Sprachmodelle erhalten solche Tags deutlich
zuverlässiger als Pandoc-Syntax.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CATEGORIES = ("a", "b1", "b2")

CATEGORY_LABELS = {
    "a": "Lesung unsicher",
    "b1": "Bedeutungswandel",
    "b2": "Begriff der Zeit",
}

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]<>#|~^$])")


def escape_md(text: str) -> str:
    """Maskiert Zeichen, die Markdown/Pandoc sonst als Syntax lesen würde."""
    return _MD_SPECIAL.sub(r"\\\1", text)


def unescape_md(text: str) -> str:
    return re.sub(r"\\([\\`*_{}\[\]<>#|~^$])", r"\1", text)


def _attr_value(value: str) -> str:
    # Anführungszeichen und Zeilenumbrüche würden das Attribut beenden.
    return value.replace("\\", "/").replace('"', "″").replace("\n", " ").strip()


@dataclass
class Mark:
    category: str
    text: str
    attrs: dict[str, str] = field(default_factory=dict)

    def to_markdown(self) -> str:
        attrs = " ".join(f'{k}="{_attr_value(v)}"' for k, v in self.attrs.items() if v not in (None, ""))
        return f"[{escape_md(self.text)}]{{.{self.category}{(' ' + attrs) if attrs else ''}}}"


def mark_reading(text: str, readings: list[str], confidence: float) -> str:
    """Kategorie A: unsichere Lesung mit allen Lesarten (wahrscheinlichste zuerst)."""
    uniq = list(dict.fromkeys(r for r in readings if r is not None))
    return Mark("a", text, {"lesarten": "|".join(uniq), "sicher": f"{confidence:.2f}"}).to_markdown()


def mark_illegible(n_chars: int | None = None) -> str:
    return Mark("a", "[unleserlich]", {"lesarten": "", "sicher": "0.00", "unleserlich": "ja"}).to_markdown()


# --------------------------------------------------------------------------- Parsen

# [Text]{.klasse key="wert" …} – Text darf maskierte Klammern enthalten.
SPAN_RE = re.compile(
    r"\[(?P<text>(?:\\.|[^\]\\])*)\]\{\.(?P<cat>a|b1|b2)(?P<attrs>(?:\s+[\w-]+=\"[^\"]*\")*)\s*\}"
)
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def find_marks(markdown: str) -> list[tuple[int, int, Mark]]:
    out = []
    for m in SPAN_RE.finditer(markdown):
        attrs = dict(_ATTR_RE.findall(m.group("attrs") or ""))
        out.append((m.start(), m.end(), Mark(m.group("cat"), unescape_md(m.group("text")), attrs)))
    return out


def strip_marks(markdown: str) -> str:
    """Entfernt alle Markierungen und behält nur den Text."""
    return SPAN_RE.sub(lambda m: m.group("text"), markdown)


# --------------------------------------------------------------------------- HTML (in Tabellen)

# In Tabellenzellen (HTML-Tabellen im Markdown) werden Markierungen als HTML-Spans geschrieben;
# der Export-Filter liest sie mit Pandocs HTML-Leser ein.
HTML_SPAN_RE = re.compile(
    r'<span class="(?P<cat>a|b1|b2)"(?P<attrs>(?:\s+[\w-]+="[^"]*")*)\s*>(?P<text>.*?)</span>', re.S
)


def html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def html_unescape(text: str) -> str:
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")


def mark_to_html(mark: Mark, inner_html: str | None = None) -> str:
    attrs = "".join(
        f' {k}="{html_escape(_attr_value(v))}"' for k, v in mark.attrs.items() if v not in (None, "")
    )
    inner = inner_html if inner_html is not None else html_escape(mark.text)
    return f'<span class="{mark.category}"{attrs}>{inner}</span>'


def markdown_cell_to_html(cell_md: str) -> str:
    """Zellinhalt (Text mit Markdown-Spans) → HTML-Fragment."""
    out, pos = [], 0
    for start, end, mark in find_marks(cell_md):
        out.append(html_escape(unescape_md(cell_md[pos:start])))
        out.append(mark_to_html(mark))
        pos = end
    out.append(html_escape(unescape_md(cell_md[pos:])))
    return "".join(out)


# --------------------------------------------------------------------------- Tags für das LLM

TAG_RE = re.compile(r"<(?P<id>(?:a|b1|b2)_\d+)>(?P<text>.*?)</(?P=id)>", re.S)


@dataclass
class Tagged:
    text: str
    marks: dict[str, Mark]  # id → Markierung (mit Originalattributen)
    html: bool = False


def to_tags(text: str, html: bool = False) -> Tagged:
    """Ersetzt Markierungen durch nummerierte Tags. ``html=True`` für HTML-Tabellenblöcke."""
    marks: dict[str, Mark] = {}
    counters = {c: 0 for c in CATEGORIES}
    regex = HTML_SPAN_RE if html else SPAN_RE

    def repl(m: re.Match) -> str:
        cat = m.group("cat")
        counters[cat] += 1
        tid = f"{cat}_{counters[cat]}"
        attrs = {k: (html_unescape(v) if html else v) for k, v in _ATTR_RE.findall(m.group("attrs") or "")}
        raw = m.group("text")
        marks[tid] = Mark(cat, html_unescape(raw) if html else unescape_md(raw), attrs)
        return f"<{tid}>{raw}</{tid}>"

    return Tagged(regex.sub(repl, text), marks, html)


def tag_ids(text: str) -> list[str]:
    return [m.group("id") for m in TAG_RE.finditer(text)]


def from_tags(text: str, marks: dict[str, Mark], html: bool = False) -> str:
    """Wandelt Tags zurück in Spans; ``marks`` liefert die (ggf. übersetzten) Attribute."""

    def repl(m: re.Match) -> str:
        mark = marks.get(m.group("id"))
        inner = m.group("text")
        if mark is None:
            return inner
        if html:
            return mark_to_html(mark, inner)
        attrs = " ".join(f'{k}="{_attr_value(v)}"' for k, v in mark.attrs.items() if v not in (None, ""))
        return f"[{inner}]{{.{mark.category}{(' ' + attrs) if attrs else ''}}}"

    return TAG_RE.sub(repl, text)
