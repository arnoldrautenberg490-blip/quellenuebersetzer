"""Quellenübersetzer – lokales Lesen und Übersetzen historischer Quellen.

Alle Verarbeitung findet auf dem eigenen Rechner statt. Netzwerkzugriff gibt es
ausschließlich im Installations- und Update-Teil (``quellenuebersetzer.install``).
"""

__version__ = "0.1.0"


def build_stamp() -> str:
    """Bauzeitpunkt der installierten Fassung (beim Bau geschrieben), sonst „Entwicklungsstand“."""
    from pathlib import Path

    try:
        return (Path(__file__).parent / "resources" / "baustempel.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return "Entwicklungsstand"
