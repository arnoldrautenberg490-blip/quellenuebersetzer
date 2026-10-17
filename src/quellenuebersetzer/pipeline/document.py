"""Datenmodell einer gelesenen Quelle."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Block:
    """Ein Abschnitt in Markdown (mit Markierungen). ``kind``: absatz | ueberschrift | tabelle | randnotiz."""

    kind: str
    markdown: str
    page: int = 0
    bbox: tuple[int, int, int, int] | None = None
    note: str = ""


@dataclass
class PageImage:
    number: int
    path: Path  # aufbereitetes Seitenbild im Cache (ASCII-Pfad)
    width: int = 0
    height: int = 0
    label: str = ""  # Seitenbezeichnung, z. B. „7a“ bei geteilten Doppelseiten
    dpi: float = 300.0

    @property
    def name(self) -> str:
        return self.label or str(self.number)


@dataclass
class SourceDocument:
    source: Path
    title: str
    origin: str  # digital | scan
    kind: str  # Quellenart (SourceKind.value)
    blocks: list[Block] = field(default_factory=list)
    pages: list[PageImage] = field(default_factory=list)
    readers: list[str] = field(default_factory=list)  # verwendete Lesewerkzeuge
    stats: dict[str, int] = field(default_factory=dict)

    def to_markdown(self) -> str:
        parts = []
        current_page = None
        for b in self.blocks:
            if self.origin == "scan" and b.page != current_page:
                current_page = b.page
                label = next((p.name for p in self.pages if p.number == b.page), str(b.page))
                parts.append(f"<!-- Seite {label} -->")
            if b.kind == "ueberschrift":
                parts.append(f"## {b.markdown}")
            elif b.kind == "randnotiz":
                parts.append("> *Randnotiz:* " + b.markdown.replace("\n", "\n> "))
            else:
                parts.append(b.markdown)
        return "\n\n".join(parts).strip() + "\n"
