"""Erzeugt resources/export/referenz.docx: Pandocs Standardvorlage + eigene Formatvorlagen.

Aufruf: python tools/referenz_docx_bauen.py <pfad/zu/pandoc.exe>
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_UNDERLINE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

OUT = Path(__file__).resolve().parents[1] / "src" / "quellenuebersetzer" / "resources" / "export" / "referenz.docx"

# Farben wie in der Programmoberfläche (siehe ui/theme.py)
COLORS = {
    "Lesung unsicher": ("B35C00", WD_UNDERLINE.DOTTED),
    "Bedeutungswandel": ("3B5BA9", WD_UNDERLINE.SINGLE),
    "Begriff der Zeit": ("2F7D6D", WD_UNDERLINE.DASH),
}


def _shade(paragraph_style, fill: str, border: str) -> None:
    ppr = paragraph_style.element.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    ppr.append(shd)
    bdr = OxmlElement("w:pBdr")
    for side in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "8")
        el.set(qn("w:space"), "6")
        el.set(qn("w:color"), border)
        bdr.append(el)
    ppr.append(bdr)


def main(pandoc: str) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = subprocess.run([pandoc, "--print-default-data-file", "reference.docx"], capture_output=True, check=True).stdout
    OUT.write_bytes(data)
    doc = Document(str(OUT))
    styles = doc.styles

    for name, (color, underline) in COLORS.items():
        st = styles.add_style(name, WD_STYLE_TYPE.CHARACTER)
        st.font.color.rgb = RGBColor.from_string(color)
        st.font.underline = underline

    seite = styles.add_style("Seitenangabe", WD_STYLE_TYPE.CHARACTER)
    seite.font.color.rgb = RGBColor.from_string("7A746A")
    seite.font.size = Pt(9)

    for name, fill, border in (("Hinweis", "F6F1E7", "B9AE98"), ("Warnung", "FBE9E6", "B3402F")):
        st = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = styles["Normal"] if "Normal" in [s.name for s in styles] else None
        st.font.size = Pt(10)
        _shade(st, fill, border)
    styles["Warnung"].font.bold = True

    for base in ("Normal", "Body Text", "First Paragraph", "Compact"):
        try:
            styles[base].font.name = "Cambria"
        except KeyError:
            pass
    doc.save(str(OUT))
    print("geschrieben:", OUT)


if __name__ == "__main__":
    main(sys.argv[1])
