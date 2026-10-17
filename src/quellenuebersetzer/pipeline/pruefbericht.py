"""Prüfbericht: Fehler sichtbar machen statt still durchlaufen zu lassen.

Je Seite eine Ampel und eine Liste von Hinweisen:
  rot   – unlesbare Bereiche, Reste der Ausgangssprache, Tabellen mit Lücken
  gelb  – geringe Lesesicherheit, nachträglich aufgenommener Text, gekürzte Bereiche
  grün  – keine Hinweise

Dazu ein **Diagnosebericht ohne Inhalt** (nur Rahmen, Bereichsarten, Sicherheit, Zeichenzahlen, Hinweisarten):
Er enthält keinen Text und kein Bild der Quelle und kann gefahrlos zur Fehlersuche weitergegeben werden.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from quellenuebersetzer.pipeline import markup
from quellenuebersetzer.pipeline.layout_doc import KIND_LABELS, LayoutDocument, LPage

POLISH_ONLY = set("ąćęłńśźżĄĆĘŁŃŚŹŻ")
RED = ("unlesbar", "Ausgangssprache", "Lücken", "überlappende Zellen", "unvollständig")


def _plain(md: str) -> str:
    if "<t" in md:
        md = re.sub(r"<[^>]+>", " ", md)
    return markup.unescape_md(markup.strip_marks(md))


def residue(source_md: str, target_md: str) -> list[str]:
    """Wörter der Ausgangssprache in der Übersetzung (polnische Sonderzeichen, kleingeschrieben).

    Großgeschriebene Wörter gelten als Namen und bleiben unbeanstandet.
    """
    src = set(_plain(source_md).lower().split())
    out = []
    for tok in _plain(target_md).split():
        word = re.sub(r"[^\w]", "", tok)
        if len(word) < 3 or word[0].isupper():
            continue
        if set(word) & POLISH_ONLY or (len(word) >= 6 and word.lower() in src and not word.isdigit()):
            out.append(word)
    return out


def check_translation(doc: LayoutDocument) -> None:
    """Nach der Übersetzung: Reste der Ausgangssprache und unübersetzte Tabellenzellen als Hinweise eintragen."""
    for p in doc.pages:
        for r in p.regions:
            if not r.translatable or not r.target_md or not r.source_md.strip():
                continue
            r.issues = [i for i in r.issues if "Ausgangssprache" not in i]
            left = residue(r.source_md, r.target_md)
            if left:
                r.issues.append(f"Reste der Ausgangssprache in der Übersetzung ({len(left)} Wort/Wörter) – prüfen.")


def page_issues(page: LPage) -> list[str]:
    out = list(page.issues)
    for n, r in enumerate(page.regions, start=1):
        for issue in r.issues:
            out.append(f"Bereich {n} ({KIND_LABELS.get(r.kind, r.kind)}): {issue}")
    return out


def light(issues: list[str]) -> str:
    issues = [i for i in issues if "Hinweis:" not in i]  # reine Hinweise (z. B. ergänzte Namensform) zählen nicht
    if any(any(k in i for k in RED) for i in issues):
        return "rot"
    return "gelb" if issues else "grün"


def summary(doc: LayoutDocument, shortened: dict[str, int] | None = None) -> list[tuple[str, str, list[str]]]:
    """[(Seitenbezeichnung, Ampel, Hinweise)] für alle Seiten."""
    rows = []
    for p in doc.pages:
        issues = page_issues(p)
        if shortened and shortened.get(p.name):
            issues.append(f"{shortened[p.name]} Bereich(e) gekürzt – vollständiger Text im Anhang.")
        rows.append((p.name, light(issues), issues))
    return rows


def report_text(doc: LayoutDocument, title: str) -> str:
    rows = summary(doc)
    counts = {k: sum(1 for _, l, _ in rows if l == k) for k in ("grün", "gelb", "rot")}
    lines = [f"Prüfbericht – {title}", "",
             f"Seiten: {len(rows)} · ohne Hinweise: {counts['grün']} · prüfen: {counts['gelb']} · "
             f"Fehler: {counts['rot']}", "",
             "Rot = unlesbare Stellen, Reste der Ausgangssprache oder Tabellen mit Lücken.",
             "Gelb = geringe Lesesicherheit oder nachträglich aufgenommener Text.", ""]
    for name, l, issues in rows:
        if not issues:
            continue
        lines.append(f"Seite {name} [{l}]")
        lines.extend(f"  – {i}" for i in issues)
        lines.append("")
    if not any(issues for _, _, issues in rows):
        lines.append("Keine Auffälligkeiten gefunden.")
    return "\n".join(lines).rstrip() + "\n"


def write_report(doc: LayoutDocument, path: Path, title: str) -> Path:
    path.write_text(report_text(doc, title), encoding="utf-8")
    return path


def _issue_kind(text: str) -> str:
    for key, kind in (("unlesbar", "unlesbar"), ("Lesesicherheit", "unsicher"), ("Ausgangssprache", "rest"),
                      ("außerhalb", "aufgefangen"), ("Lücken", "tabelle_luecken"), ("überlappende", "tabelle_ueberlappung"),
                      ("Summe", "summe"), ("unvollständig", "unvollstaendig")):
        if key in text:
            return kind
    return "sonstig"


def diagnose(doc: LayoutDocument) -> dict:
    """Strukturdaten ohne Inhalt: keine Texte, keine Bilder, keine Dateinamen."""
    pages = []
    for p in doc.pages:
        pages.append({
            "seite": p.number,
            "groesse": [p.width_px, p.height_px],
            "kaesten": [{"box": d["box"], "hinterlegt": bool(d.get("fill")), "dunkel": bool(d.get("dark")),
                         "rahmen": d.get("dash") or ""} for d in p.decorations],
            "seitenhinweise": [_issue_kind(i) for i in p.issues],
            "bereiche": [{
                "art": r.kind, "box": list(r.box), "kasten": r.container, "zeilen": r.lines,
                "zeichen": len(_plain(r.source_md)), "zeichen_de": len(_plain(r.target_md)),
                "sicherheit": round(r.conf, 1), "fett": r.bold, "farbig": bool(r.color),
                "hinweise": [_issue_kind(i) for i in r.issues],
            } for r in p.regions],
        })
    from quellenuebersetzer import __version__, build_stamp

    return {"format": 1, "programm": f"{__version__} ({build_stamp()})", "seiten": pages}


def write_diagnose(doc: LayoutDocument, path: Path) -> Path:
    path.write_text(json.dumps(diagnose(doc), ensure_ascii=False, indent=1), encoding="utf-8")
    return path
