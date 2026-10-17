"""Lesbare Darstellung der Umschrift in der Kontrollansicht – und zurück.

Im Editor erscheinen unsichere Stellen als ``⟦młyn⟧¹`` statt der Pandoc-Syntax. Die Hochzahl verweist auf
die Liste der Lesarten unter dem Editor. Entfernt der Nutzer die Klammern, gilt die Stelle als geklärt und
die Markierung entfällt; bleibt sie stehen, wird sie (mit ggf. korrigiertem Text) beibehalten.
"""

from __future__ import annotations

import re

from quellenuebersetzer.pipeline import markup

_SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_UNSUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
EDITOR_MARK_RE = re.compile(r"⟦(?P<text>[^⟧]*)⟧(?P<num>[⁰¹²³⁴⁵⁶⁷⁸⁹]+)")
PAGE_RE = re.compile(r"^<!--\s*Seite\s+(\S+)\s*-->$", re.M)
EDITOR_PAGE_RE = re.compile(r"^── Seite (\S+) ──$", re.M)
REGION_RE = re.compile(r"^<!-- B (\S+) (\S+) -->$", re.M)
EDITOR_REGION_RE = re.compile(r"^── (.+?) · (\S+) ──$", re.M)


def sup(n: int) -> str:
    return str(n).translate(_SUP)


def to_editor(md: str) -> tuple[str, list[markup.Mark]]:
    marks: list[markup.Mark] = []

    def repl(m: re.Match) -> str:
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group("attrs") or ""))
        mark = markup.Mark(m.group("cat"), markup.unescape_md(m.group("text")), attrs)
        marks.append(mark)
        return f"⟦{mark.text}⟧{sup(len(marks))}"

    text = markup.SPAN_RE.sub(repl, md)
    text = PAGE_RE.sub(lambda m: f"── Seite {m.group(1)} ──", text)
    text = REGION_RE.sub(lambda m: f"── {_kind_label(m.group(2))} · {m.group(1)} ──", text)
    return _soft_unescape(text), marks


def from_editor(text: str, marks: list[markup.Mark]) -> str:
    text = EDITOR_PAGE_RE.sub(lambda m: f"<!-- Seite {m.group(1)} -->", text)
    labels = {v: k for k, v in _labels().items()}
    text = EDITOR_REGION_RE.sub(lambda m: f"<!-- B {m.group(2)} {labels.get(m.group(1), 'absatz')} -->", text)
    out, pos = [], 0
    for m in EDITOR_MARK_RE.finditer(text):
        out.append(_soft_escape(text[pos:m.start()]))
        idx = int(m.group("num").translate(_UNSUP)) - 1
        inner = m.group("text")
        if 0 <= idx < len(marks):
            orig = marks[idx]
            out.append(markup.Mark(orig.category, inner, dict(orig.attrs)).to_markdown())
        else:
            out.append(_soft_escape(inner))
        pos = m.end()
    out.append(_soft_escape(text[pos:]))
    return "".join(out)


# Maskierungen nur für Zeichen auflösen, die im Fließtext harmlos sind; HTML-Tabellen bleiben unberührt.
_SOFT = re.compile(r"\\([*_\[\]#~^$`\\])")


def _soft_unescape(text: str) -> str:
    return _SOFT.sub(r"\1", text)


def _soft_escape(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        prefix = next((p for p in _PREFIXES if stripped.startswith(p)), None)
        if prefix:
            lines.append(prefix + _escape_plain(stripped[len(prefix):]))
        elif stripped.startswith(("<table", "<tr", "</table", "<!--", "![](")):
            lines.append(line)
        else:
            lines.append(_escape_plain(line))
    return "\n".join(lines)


_PREFIXES = ("## ", "> *Randnotiz:* ", "> *Fußnote:* ", "> ")


def _escape_plain(s: str) -> str:
    return re.sub(r"([\\`*_\[\]#~^$])", r"\\\1", s)


def describe(mark: markup.Mark, n: int) -> str:
    if mark.attrs.get("unleserlich"):
        return f"{sup(n)}  unleserliche Stelle"
    readings = [r for r in mark.attrs.get("lesarten", "").split("|") if r]
    conf = mark.attrs.get("sicher")
    pct = f" · Sicherheit etwa {round(float(conf) * 100)} %" if conf else ""
    if len(readings) > 1:
        return f"{sup(n)}  {' / '.join(readings)}{pct}"
    return f"{sup(n)}  {readings[0] if readings else mark.text} (unsicher){pct}"


def _labels() -> dict[str, str]:
    from quellenuebersetzer.pipeline.layout_doc import KIND_LABELS

    return KIND_LABELS


def _kind_label(kind: str) -> str:
    return _labels().get(kind, kind)
