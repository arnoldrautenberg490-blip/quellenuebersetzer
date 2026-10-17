"""Übersetzung eines Seitenmodells – gestückelt nach der Struktur des ganzen Dokuments.

Weil der Seitenaufbau des gesamten Dokuments vorab feststeht, werden aufeinanderfolgende Absätze
(auch über Spalten- und Seitengrenzen hinweg) zu zusammenhängenden Abschnitten gebündelt (bis etwa
``CHUNK_CHARS`` Zeichen) – aber nur innerhalb desselben Textflusses: Kastentext wird nie mit dem
umgebenden Text gebündelt, ebenso wenig Absätze mit anderer Schriftfarbe oder Fettdruck. Überschriften, Tabellen und Bildunterschriften beginnen neue Abschnitte;
Kopf-/Fußzeilen, Randnotizen und Fußnoten werden eigenständig übersetzt, ohne den Textfluss zu unterbrechen.

Innerhalb eines Abschnitts trennen Marken ``<split_1/>``, ``<split_2/>`` … die Bereiche; nach der
Übersetzung wird der Text daran wieder auf die Bereiche verteilt. Fehlt eine Marke, wird der Abschnitt
sicher Bereich für Bereich übersetzt. Gleiche Texte außerhalb des Fließtexts (Kolumnentitel) nur einmal.

Vorteile: mehr Zusammenhang für das Modell (bessere Übersetzung) und deutlich weniger Anfragen (schneller).
"""

from __future__ import annotations

import re
from typing import Callable

from quellenuebersetzer.pipeline import markup
from quellenuebersetzer.pipeline.layout_doc import HEADING_KINDS, LayoutDocument, LRegion
from quellenuebersetzer.pipeline.translate import Segment, Translator

CHUNK_CHARS = 1800
FLOW_KINDS = {"absatz"}
MARGIN_KINDS = {"kopfzeile", "fusszeile", "seitenzahl", "fussnote", "randnotiz"}
SPLIT_RE = re.compile(r"<split_(\d+)/>")


def _segment_kind(r: LRegion) -> str:
    if r.kind == "tabelle":
        return "tabelle"
    if r.kind in HEADING_KINDS:
        return "ueberschrift"
    if r.kind == "randnotiz":
        return "randnotiz"
    return "text"


def same_flow(a: LRegion, b: LRegion) -> bool:
    """Gehören zwei Absätze zum selben Textfluss? Kasten und Seitentext, andere Farbe oder Fettdruck: nein."""
    return (a.container == b.container and a.color == b.color and a.bold == b.bold
            and not a.issues and not b.issues)


def build_units(regions: list[LRegion], chunk_chars: int = CHUNK_CHARS) -> list[list[LRegion]]:
    """Abschnitte für die Übersetzung: zusammenhängender Fließtext gebündelt, alles andere einzeln."""
    units: list[list[LRegion]] = []
    current: list[LRegion] = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            units.append(current)
        current, size = [], 0

    for r in regions:
        if r.kind in FLOW_KINDS:
            if current and (size + len(r.source_md) > chunk_chars or not same_flow(current[-1], r)):
                flush()
            current.append(r)
            size += len(r.source_md)
        elif r.kind in MARGIN_KINDS:
            units.append([r])  # eigenständig, unterbricht den Textfluss nicht
        else:
            flush()  # Überschrift, Tabelle, Bildunterschrift: neuer Abschnitt
            units.append([r])
    flush()
    return units


def split_parts(text: str, n_markers: int) -> list[str] | None:
    """Übersetzung an den Marken aufteilen – nur, wenn alle Marken genau einmal und in Reihenfolge vorkommen."""
    found = [int(m) for m in SPLIT_RE.findall(text)]
    if found != list(range(1, n_markers + 1)):
        return None
    parts = [p.strip() for p in SPLIT_RE.split(text)[::2]]  # Ziffern-Gruppen des Musters überspringen
    return parts if len(parts) == n_markers + 1 and all(parts) else None


def balanced(unit: list[LRegion], parts: list[str], low: float = 0.45, high: float = 2.6) -> bool:
    """Passt jeder übersetzte Teil in der Länge zu seinem Originalbereich?"""
    for r, part in zip(unit, parts):
        src = len(markup.strip_marks(r.source_md))
        if src < 40:
            continue  # bei sehr kurzen Bereichen ist das Verhältnis wenig aussagekräftig
        ratio = len(markup.strip_marks(part)) / src
        if not low <= ratio <= high:
            return False
    return True


def needs_refinement(unit: list[LRegion], troubled: bool) -> bool:
    """Schwierige Abschnitte für den zweiten Durchgang mit dem großen Modell („gestaffelt gründlich“):
    Tabellen, unsichere Lesungen, markierte Begriffe, Abschnitte mit Korrekturen oder Rückfall."""
    if troubled:
        return True
    for r in unit:
        if r.kind == "tabelle":
            return True
        if any(m.category == "a" for _s, _e, m in markup.find_marks(r.source_md)):
            return True
        if any(m.category in ("b1", "b2") or m.attrs.get("hinweis") for _s, _e, m in markup.find_marks(r.target_md)):
            return True
    return False


def translate_layout(doc: LayoutDocument, tr: Translator, progress: Callable[[int, int], None] | None = None,
                     on_page_done: Callable[[object], None] | None = None,
                     refine: Translator | None = None) -> None:
    """Übersetzt alle Bereiche. Mit ``refine`` (gestaffelt gründlich) übersetzt ``tr`` (schnelles Modell) alles,
    danach ``refine`` (großes Modell) nur die schwierigen Abschnitte – mit einem einzigen Modellwechsel."""
    regions = [r for p in doc.pages for r in p.regions
               if r.translatable and r.source_md.strip() and not r.target_md]
    for r in regions:
        if markup.unescape_md(markup.strip_marks(r.source_md)).strip() == "[unleserlich]":
            r.target_md = r.source_md  # unlesbarer Bereich: nichts zu übersetzen (steht im Prüfbericht)
    regions = [r for r in regions if not r.target_md]
    reported: set[int] = set()

    def report_finished_pages() -> None:
        if not on_page_done:
            return
        for p in doc.pages:
            if p.number in reported:
                continue
            todo = [r for r in p.regions if r.translatable and r.source_md.strip()]
            if all(r.target_md for r in todo):
                reported.add(p.number)
                on_page_done(p)
            else:
                break  # Seiten in Reihenfolge melden

    def translate_unit(unit: list[LRegion], t: Translator, previous, cache) -> tuple[str, str] | None:
        if len(unit) > 1:
            joined = " ".join(
                f"{r.source_md.strip()} <split_{k}/>" if k < len(unit) else r.source_md.strip()
                for k, r in enumerate(unit, start=1)
            )
            parts = split_parts(t.translate_segment(Segment("text", joined), previous), len(unit) - 1)
            if parts and not balanced(unit, parts):
                parts = None  # Sätze über die Marken verschoben → ein Bereich bekäme zu viel/zu wenig Text
            if parts:
                for r, part in zip(unit, parts):
                    r.target_md = part
                return markup.strip_marks(unit[-1].source_md), markup.strip_marks(unit[-1].target_md)
            # Rückfall: Bereich für Bereich
        for r in unit:
            key = (r.kind, r.source_md)
            if r.kind not in FLOW_KINDS and key in cache:
                r.target_md = cache[key]
                continue
            r.target_md = t.translate_segment(Segment(_segment_kind(r), r.source_md), previous)
            if r.kind in FLOW_KINDS:
                previous = (markup.strip_marks(r.source_md), markup.strip_marks(r.target_md))
            else:
                cache[key] = r.target_md
        return previous

    report_finished_pages()
    units = build_units(regions)
    total = len(units)
    cache: dict[tuple[str, str], str] = {}
    previous: tuple[str, str] | None = None
    troubled: list[bool] = []
    for i, unit in enumerate(units, start=1):
        if progress:
            progress(i, total)
        before = tr.stats.retries + tr.stats.fallbacks
        previous = translate_unit(unit, tr, previous, cache)
        troubled.append(tr.stats.retries + tr.stats.fallbacks > before)
        report_finished_pages()
    report_finished_pages()
    if refine is None:
        return
    # zweiter Durchgang: großes Modell nur für die schwierigen Abschnitte
    hard = [k for k, unit in enumerate(units) if needs_refinement(unit, troubled[k])]
    flow_prev = {}
    last = None
    for k, unit in enumerate(units):
        flow_prev[k] = last
        if unit[-1].kind in FLOW_KINDS and unit[-1].target_md:
            last = (markup.strip_marks(unit[-1].source_md), markup.strip_marks(unit[-1].target_md))
    refine_cache: dict[tuple[str, str], str] = {}
    for n, k in enumerate(hard, start=1):
        if progress:
            progress(total + n, total + len(hard))
        unit = units[k]
        old = [r.target_md for r in unit]
        try:
            translate_unit(unit, refine, flow_prev[k], refine_cache)
        except Exception:  # noqa: BLE001 – z. B. Speichermangel: der Entwurf des schnellen Modells bleibt erhalten
            for r, t in zip(unit, old):
                r.target_md = t
            refine.stats.problems.append("Zweiter Durchgang fehlgeschlagen – Entwurf beibehalten.")
            continue
        for r, t in zip(unit, old):
            if not r.target_md.strip():
                r.target_md = t
        if on_page_done:
            for p in doc.pages:
                if any(r in p.regions for r in unit):
                    on_page_done(p)
