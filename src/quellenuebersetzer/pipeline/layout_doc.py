"""Seitenmodell für die Layoutkopie: Seiten → Bereiche mit Position, Art, Schriftmerkmalen, Text und Übersetzung."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from quellenuebersetzer.pipeline.markup import escape_md

# Bereichsarten, deren Text gelesen und übersetzt wird
TEXT_KINDS = {"absatz", "titel", "ueberschrift", "randnotiz", "bildunterschrift", "fussnote", "kopfzeile",
              "fusszeile", "seitenzahl"}
IMAGE_KINDS = {"abbildung", "formel"}
HEADING_KINDS = {"titel", "ueberschrift"}

KIND_LABELS = {
    "absatz": "Absatz", "titel": "Titel", "ueberschrift": "Überschrift", "randnotiz": "Randnotiz",
    "bildunterschrift": "Bildunterschrift", "fussnote": "Fußnote", "kopfzeile": "Kopfzeile", "fusszeile": "Fußzeile",
    "seitenzahl": "Seitenzahl", "tabelle": "Tabelle", "abbildung": "Abbildung", "formel": "Formel",
}


@dataclass
class LRegion:
    id: str
    kind: str
    box: tuple[int, int, int, int]  # x0, y0, x1, y1 in Pixeln der (begradigten) Seite
    order: int
    source_md: str = ""  # gelesener Text: Markdown mit Markierungen; Tabellen: HTML
    target_md: str = ""  # Übersetzung (gleiches Format)
    line_px: float = 0.0  # mittlere Zeilenhöhe in Pixeln (→ Schriftgröße)
    lines: int = 0
    align: str = "left"  # left | center | right | justify
    bold: bool = False
    italic: bool = False
    spaced: bool = False  # Sperrsatz
    color: str = ""  # Schriftfarbe (Hex), leer = übliche dunkle Schrift
    stroke: float = 0.0  # gemessene Strichstärke (für „fett“ im Vergleich zur Seite)
    image: str = ""  # Bildausschnitt (Abbildungen), Dateiname im Arbeitsordner
    erase_boxes: list[tuple[int, int, int, int]] = field(default_factory=list)  # Textflächen fürs Faksimile
    container: str = ""  # Kasten (Kennung in ``LPage.decorations``), leer = Seitenfluss
    conf: float = -1.0  # mittlere Lesesicherheit 0–100 (-1 = unbekannt)
    issues: list[str] = field(default_factory=list)  # Hinweise für den Prüfbericht

    @property
    def is_text(self) -> bool:
        return self.kind in TEXT_KINDS

    @property
    def translatable(self) -> bool:
        return (self.is_text and self.kind != "seitenzahl") or self.kind == "tabelle"


@dataclass
class LPage:
    number: int
    width_px: int
    height_px: int
    dpi: float
    background: str  # begradigtes Seitenbild (Dateiname im Arbeitsordner)
    regions: list[LRegion] = field(default_factory=list)
    label: str = ""  # Seitenbezeichnung, z. B. „7a“ oder „Vorderdeckel“
    read: bool = False  # Texterkennung abgeschlossen (Phase 2)
    decorations: list[dict] = field(default_factory=list)  # Kästen: id, box, fill, stroke, dash, stroke_px, dark
    issues: list[str] = field(default_factory=list)  # Hinweise zur ganzen Seite für den Prüfbericht

    def decoration(self, kid: str) -> dict | None:
        return next((d for d in self.decorations if d.get("id") == kid), None)

    @property
    def name(self) -> str:
        return self.label or str(self.number)

    @property
    def width_mm(self) -> float:
        return self.width_px / self.dpi * 25.4

    @property
    def height_mm(self) -> float:
        return self.height_px / self.dpi * 25.4


@dataclass
class LayoutDocument:
    source: str
    title: str
    kind: str
    workdir: str  # Arbeitsordner mit Seitenbildern und Ausschnitten
    pages: list[LPage] = field(default_factory=list)
    readers: list[str] = field(default_factory=list)
    target_size: list[int] | None = None  # einheitliches Seitenformat (Pixel) nach der Aufbereitung

    # ------------------------------------------------------------------ Fließtext (für Markdown, EPUB, Prüfung)
    def flow_markdown(self, translated: bool = False, with_ids: bool = False) -> str:
        parts: list[str] = []
        for page in self.pages:
            parts.append(f"<!-- Seite {page.name} -->")
            for r in page.regions:
                text = r.target_md if translated else r.source_md
                if with_ids and r.translatable:
                    parts.append(f"<!-- B {r.id} {r.kind} -->")
                if r.kind in IMAGE_KINDS:
                    if r.image and not with_ids:
                        parts.append(f"![]({r.image})")
                    continue
                if not text.strip():
                    continue
                if with_ids:
                    parts.append(text)  # Art steht in der Bereichsmarke; keine Präfixe (sicherer Rückweg)
                    continue
                if r.kind == "tabelle":
                    parts.append(text)
                elif r.kind in HEADING_KINDS:
                    parts.append("## " + text.replace("\n", " "))
                elif r.kind == "randnotiz":
                    parts.append("> *Randnotiz:* " + text.replace("\n", "\n> "))
                elif r.kind == "fussnote":
                    parts.append("> *Fußnote:* " + text.replace("\n", "\n> "))
                elif r.kind == "bildunterschrift":
                    parts.append("*" + text.strip() + "*" if not text.strip().startswith("[") else text)
                elif r.kind in ("kopfzeile", "fusszeile", "seitenzahl"):
                    if with_ids:
                        parts.append(text)
                    continue  # im Fließtext entbehrlich
                else:
                    parts.append(text)
        return "\n\n".join(parts).strip() + "\n"

    def apply_reviewed(self, md_with_ids: str) -> None:
        """Übernimmt eine (vom Nutzer korrigierte) Fließtextfassung mit Bereichsmarken zurück in die Bereiche."""
        import re

        chunks = re.split(r"<!-- B (\S+)(?: \S+)? -->", md_with_ids)
        by_id = {r.id: r for p in self.pages for r in p.regions}
        for i in range(1, len(chunks), 2):
            rid, body = chunks[i], chunks[i + 1]
            body = re.sub(r"<!-- Seite \S+ -->", "", body).strip()
            r = by_id.get(rid)
            if r is None:
                continue
            r.source_md = body

    # ------------------------------------------------------------------ Speichern (Buchmodus: Fortsetzen)
    def save(self, path: Path) -> None:
        def plain(o):  # NumPy-Zahlen aus der Bildverarbeitung → normale Zahlen
            return o.item() if hasattr(o, "item") else str(o)

        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, default=plain), encoding="utf-8")
        tmp.replace(path)  # atomar: ein Absturz beim Speichern hinterlässt keinen halben Zwischenstand

    @classmethod
    def load(cls, path: Path) -> "LayoutDocument":
        data = json.loads(path.read_text(encoding="utf-8"))
        pages = []
        for p in data.pop("pages"):
            regs = [LRegion(**{**r, "box": tuple(r["box"]), "erase_boxes": [tuple(b) for b in r.get("erase_boxes", [])]})
                    for r in p.pop("regions")]
            pages.append(LPage(**p, regions=regs))
        return cls(**data, pages=pages)


def plain_heading(text: str) -> str:
    return escape_md(text)
