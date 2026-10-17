"""Zusammenstellen der Ergebnisdokumente und Umwandlung nach DOCX, PDF und EPUB (Pandoc + Typst)."""

from __future__ import annotations

import datetime as dt
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from quellenuebersetzer.config import Paths, resources_dir
from quellenuebersetzer.netguard import offline_env
from quellenuebersetzer.pipeline import markup
from quellenuebersetzer.planner import GENERAL_DISCLAIMER, HANDWRITING_WARNING

FORMATS = {
    "docx": ("Word (DOCX)", ".docx"),
    "pdf": ("PDF", ".pdf"),
    "epub": ("E-Book (EPUB)", ".epub"),
}

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ExportError(Exception):
    pass


@dataclass
class DocMeta:
    title: str
    source_name: str
    source_language: str
    period_label: str
    kind_label: str
    models: list[str]
    handwriting: bool


def _yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def front_matter(meta: DocMeta, subtitle: str) -> str:
    today = dt.date.today().strftime("%d.%m.%Y")
    return "\n".join([
        "---",
        f"title: {_yaml_str(meta.title)}",
        f"subtitle: {_yaml_str(subtitle)}",
        f"date: {_yaml_str(today)}",
        "lang: de-DE",
        "margin:",
        "  x: 2.4cm",
        "  y: 2.2cm",
        "---",
        "",
    ])


def notice_blocks(meta: DocMeta, translated: bool) -> str:
    parts = []
    if meta.handwriting:
        parts.append("::: warnung\n**Warnhinweis Handschrift:** " + markup.escape_md(HANDWRITING_WARNING) + "\n:::")
    info = [
        f"**Quelle:** {markup.escape_md(meta.source_name)} · **Sprache:** {meta.source_language} · "
        f"**Zeitraum:** {meta.period_label} · **Quellenart:** {meta.kind_label}\\",
        f"**Verwendete lokale Modelle:** {markup.escape_md(', '.join(meta.models)) or '–'}",
        "",
        markup.escape_md(GENERAL_DISCLAIMER) if translated else markup.escape_md(
            "Maschinell erstellte Umschrift. Markierte Stellen bitte am Original prüfen."
        ),
        "",
        "Markierungen: orange gepunktet = Lesung unsicher · blau = Bedeutungswandel · grün gestrichelt = Begriff der Zeit. "
        "Erläuterungen in den Fußnoten und im Verzeichnis am Ende.",
    ]
    parts.append("::: hinweis\n" + "\n".join(info) + "\n:::")
    return "\n\n".join(parts) + "\n\n"


def marks_index(md: str) -> str:
    """Verzeichnis aller markierten Stellen, nach Kategorie, mit Seitenangabe."""
    entries: dict[str, list[str]] = {"a": [], "b1": [], "b2": []}
    page = None
    for block in re.split(r"\n\s*\n", md):
        m = re.match(r"<!--\s*Seite\s+(\S+)\s*-->", block.strip())
        if m:
            page = m.group(1)
            continue
        found = [(mk.category, mk.text, mk.attrs) for _, _, mk in markup.find_marks(block)]
        for hm in markup.HTML_SPAN_RE.finditer(block):
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', hm.group("attrs") or ""))
            found.append((hm.group("cat"), markup.html_unescape(re.sub(r"<[^>]+>", "", hm.group("text"))),
                          {k: markup.html_unescape(v) for k, v in attrs.items()}))
        for cat, text, attrs in found:
            where = f"S. {page}: " if page else ""
            if cat == "a":
                if attrs.get("hinweis"):
                    line = attrs["hinweis"]
                else:
                    readings = [r for r in attrs.get("lesarten", "").split("|") if r]
                    de = [r for r in attrs.get("lesarten_de", "").split("|") if r]
                    alts = " · ".join(
                        f"„{o}“" + (f" ({de[i]})" if i < len(de) and de[i] != o else "") for i, o in enumerate(readings)
                    )
                    conf = attrs.get("sicher")
                    line = f"*{text}* – {alts or 'unleserlich'}" + (f" (etwa {round(float(conf) * 100)} %)" if conf else "")
            elif cat == "b1":
                line = f"*{text}* – „{attrs.get('original', '')}“: damals {attrs.get('damals', '?')}; heute {attrs.get('heute', '?')}"
            else:
                line = f"*{text}* – „{attrs.get('original', '')}“: {attrs.get('erkl', '')}"
            entries[cat].append(f"- {where}{line}")
    if not any(entries.values()):
        return ""
    out = ["", "# Verzeichnis der markierten Stellen", ""]
    for cat in ("a", "b1", "b2"):
        if entries[cat]:
            out += [f"## {markup.CATEGORY_LABELS[cat]} ({len(entries[cat])})", ""] + entries[cat] + [""]
    return "\n".join(out)


def build_document(body_md: str, meta: DocMeta, translated: bool) -> str:
    # „Polnisch“ → „aus dem Polnischen“
    subtitle = f"Maschinelle Übersetzung aus dem {meta.source_language}en" if translated else "Maschinelle Umschrift"
    return front_matter(meta, subtitle) + notice_blocks(meta, translated) + body_md.strip() + "\n" + marks_index(body_md)


class Exporter:
    def __init__(self, paths: Paths):
        self.pandoc = paths.runtime / "pandoc" / "pandoc.exe"
        self.typst = paths.runtime / "typst" / "typst.exe"
        res = resources_dir() / "export"
        self.lua = res / "markierungen.lua"
        self.css = res / "epub.css"
        self.reference = res / "referenz.docx"
        self.tmp = paths.cache / "export"

    @property
    def available(self) -> bool:
        return self.pandoc.exists()

    def convert(self, markdown_file: Path, fmt: str, dest: Path) -> Path:
        if fmt not in FORMATS:
            raise ExportError(f"Unbekanntes Format: {fmt}")
        if not self.pandoc.exists():
            raise ExportError("Die Dokumentumwandlung (Pandoc) ist nicht installiert.")
        self.tmp.mkdir(parents=True, exist_ok=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Pandoc und Typst arbeiten im ASCII-Cache; das Ergebnis wird danach verschoben (Umlaute in Zielpfaden).
        tmp_out = self.tmp / f"ausgabe{FORMATS[fmt][1]}"
        tmp_out.unlink(missing_ok=True)
        cmd = [
            str(self.pandoc), str(markdown_file),
            "--from", "markdown+raw_html+bracketed_spans+fenced_divs-implicit_figures-markdown_in_html_blocks",
            "--lua-filter", str(self.lua),
            "--resource-path", str(markdown_file.parent),
            "-o", str(tmp_out),
        ]
        has_images = "![](" in markdown_file.read_text(encoding="utf-8")
        if fmt != "epub" and not has_images:
            # Pandoc liest nur die angegebenen lokalen Dateien (EPUB braucht das Stylesheet, Abbildungen ihre
            # Bilddateien – das sind ausschließlich eigene Ausschnitte im Arbeitsordner).
            # In jedem Fall gilt die Netzabschottung über die Prozessumgebung.
            cmd.append("--sandbox")
        if fmt == "docx":
            cmd += ["--reference-doc", str(self.reference)]
        elif fmt == "epub":
            cmd += ["--to", "epub3", "--css", str(self.css), "--split-level=1"]
        elif fmt == "pdf":
            if not self.typst.exists():
                raise ExportError("Der PDF-Satz (Typst) ist nicht installiert.")
            cmd += [
                "--pdf-engine", str(self.typst),
                "-V", "papersize=a4", "-V", "mainfont=Libertinus Serif", "-V", "fontsize=11pt",
            ]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=offline_env(), creationflags=_NO_WINDOW, timeout=900)
        if r.returncode != 0 or not tmp_out.exists():
            # nur die Fehlerzeilen, keine Dokumentinhalte
            msg = " ".join(r.stderr.strip().splitlines()[-2:])[:300]
            raise ExportError(f"{FORMATS[fmt][0]} konnte nicht erzeugt werden: {msg}")
        if dest.exists():
            dest.unlink()
        shutil.move(str(tmp_out), str(dest))  # auch auf ein anderes Laufwerk (USB-Stick, D:)
        return dest
