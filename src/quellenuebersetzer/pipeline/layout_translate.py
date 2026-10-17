"""Übersetzung eines Seitenmodells – gestückelt nach der Struktur des ganzen Dokuments.

Weil der Seitenaufbau des gesamten Dokuments vorab feststeht, werden aufeinanderfolgende Absätze
(auch über Spalten- und Seitengrenzen hinweg) zu zusammenhängenden Abschnitten gebündelt (bis etwa
``CHUNK_CHARS`` Zeichen). Überschriften, Tabellen und Bildunterschriften beginnen neue Abschnitte;
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
            if current and size + len(r.source_md) > chunk_chars:
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


def translate_layout(doc: LayoutDocument, tr: Translator, progress: Callable[[int, int], None] | None = None,
                     on_page_done: Callable[[object], None] | None = None) -> None:
    regions = [r for p in doc.pages for r in p.regions
               if r.translatable and r.source_md.strip() and not r.target_md]
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

    report_finished_pages()
    cache: dict[tuple[str, str], str] = {}
    previous: tuple[str, str] | None = None
    units = build_units(regions)
    for i, unit in enumerate(units, start=1):
        if progress:
            progress(i, len(units))
        if len(unit) > 1:
            joined = " ".join(
                f"{r.source_md.strip()} <split_{k}/>" if k < len(unit) else r.source_md.strip()
                for k, r in enumerate(unit, start=1)
            )
            parts = split_parts(tr.translate_segment(Segment("text", joined), previous), len(unit) - 1)
            if parts:
                for r, part in zip(unit, parts):
                    r.target_md = part
                previous = (markup.strip_marks(unit[-1].source_md), markup.strip_marks(unit[-1].target_md))
                report_finished_pages()
                continue
            # Rückfall: Bereich für Bereich
        for r in unit:
            key = (r.kind, r.source_md)
            if r.kind not in FLOW_KINDS and key in cache:
                r.target_md = cache[key]
                continue
            r.target_md = tr.translate_segment(Segment(_segment_kind(r), r.source_md), previous)
            if r.kind in FLOW_KINDS:
                previous = (markup.strip_marks(r.source_md), markup.strip_marks(r.target_md))
            else:
                cache[key] = r.target_md
        report_finished_pages()
    report_finished_pages()
