"""Seitengetreuer Satz der Übersetzung als PDF (Typst): Faksimile oder Neusatz.

Faksimile: Originalseite als Hintergrund, Textflächen retuschiert (Papier, Linien, Abbildungen bleiben),
           Übersetzung an derselben Stelle.
Neusatz:   weiße Seite, gleiche Anordnung, Abbildungen als Ausschnitte.

Passt der (meist längere) deutsche Text nicht in den Originalbereich, wird die Schrift schrittweise
verkleinert (bis 55 % der Originalgröße); Markierungen erscheinen als hochgestellte Ziffern, ihre
Erläuterungen gesammelt im Anhang „Anmerkungen“.
"""

from __future__ import annotations

import html
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from quellenuebersetzer.netguard import offline_env
from quellenuebersetzer.pipeline.fitting import expand_boxes, fit_text
from quellenuebersetzer.pipeline import markup
from quellenuebersetzer.pipeline.layout_doc import HEADING_KINDS, IMAGE_KINDS, LayoutDocument, LPage, LRegion
from quellenuebersetzer.planner import GENERAL_DISCLAIMER, HANDWRITING_WARNING

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
COLORS = {"a": "#b35c00", "b1": "#3b5ba9", "b2": "#2f7d6d"}
MIN_SCALE = 0.55


# --------------------------------------------------------------------------- Anmerkungen


def note_text(mark: markup.Mark) -> str:
    a = mark.attrs
    if a.get("hinweis"):
        return a["hinweis"]
    if mark.category == "a":
        if a.get("unleserlich"):
            return "Unleserliche Stelle."
        orig = [x for x in a.get("lesarten", "").split("|") if x]
        de = [x for x in a.get("lesarten_de", "").split("|") if x]
        parts = [f"„{o}“" + (f" ({de[i]})" if i < len(de) and de[i] != o else "") for i, o in enumerate(orig)]
        txt = "Lesung unsicher"
        if a.get("sicher"):
            try:
                txt += f" (Sicherheit etwa {round(float(a['sicher']) * 100)} %)"
            except ValueError:
                pass
        if len(parts) > 1:
            return txt + ". Mögliche Lesarten: " + " · ".join(parts) + "."
        return txt + (f". Gelesen: {parts[0]}." if parts else ".")
    head = "Bedeutungswandel" if mark.category == "b1" else "Begriff der Zeit"
    txt = head + (f": „{a['original']}“" if a.get("original") else "")
    if mark.category == "b1":
        if a.get("damals"):
            txt += f" – damals: {a['damals']}"
        if a.get("heute"):
            txt += f"; heute: {a['heute']}"
    if a.get("erkl"):
        txt += f". {a['erkl']}"
    if a.get("beleg"):
        txt += f" (Beleg: {a['beleg']})"
    return txt if txt.endswith((".", ")")) else txt + "."


@dataclass
class Notes:
    items: list[tuple[str, int, str]] = field(default_factory=list)  # (Seitenbezeichnung, Nr., Text)
    page: str = ""
    counter: int = 0
    shortened: list[tuple[str, str]] = field(default_factory=list)  # (Seitenbezeichnung, vollständiger Text)

    def add(self, mark: markup.Mark) -> int:
        self.counter += 1
        self.items.append((self.page, self.counter, note_text(mark)))
        return self.counter


# --------------------------------------------------------------------------- Typst-Inhalt


def _tstr(text: str) -> str:
    """Klartext als Typst-String (keine Markup-Deutung)."""
    return '#"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _plain(md: str) -> str:
    t = markup.unescape_md(md)
    return _tstr(t) if t else ""


def md_to_typst(md: str, notes: Notes) -> str:
    """Text mit Markdown-Spans → Typst-Inhalt (Markierungen farbig + hochgestellte Anmerkungsnummer)."""
    out, pos = [], 0
    for start, end, mark in markup.find_marks(md):
        out.append(_plain(md[pos:start]))
        out.append(_mark_typst(mark, _tstr(mark.text), notes))
        pos = end
    out.append(_plain(md[pos:]))
    return "".join(out)


def _mark_typst(mark: markup.Mark, inner: str, notes: Notes) -> str:
    color = COLORS[mark.category]
    dash = {"a": '"dotted"', "b1": "none", "b2": '"dashed"'}[mark.category]
    n = notes.add(mark)
    return (f'#underline(stroke: (paint: rgb("{color}"), thickness: 0.6pt, dash: {dash}), offset: 1.5pt)'
            f'[#text(fill: rgb("{color}"))[{inner}]]#super[{n}]')


def html_inner_to_typst(inner: str, notes: Notes) -> str:
    out, pos = [], 0
    for m in markup.HTML_SPAN_RE.finditer(inner):
        out.append(_tstr(html.unescape(re.sub(r"<[^>]+>", "", inner[pos:m.start()]))))
        attrs = {k: html.unescape(v) for k, v in re.findall(r'([\w-]+)="([^"]*)"', m.group("attrs") or "")}
        text = html.unescape(re.sub(r"<[^>]+>", "", m.group("text")))
        out.append(_mark_typst(markup.Mark(m.group("cat"), text, attrs), _tstr(text), notes))
        pos = m.end()
    out.append(_tstr(html.unescape(re.sub(r"<[^>]+>", "", inner[pos:]))))
    return "".join(x for x in out if x != '#""')


def table_to_typst(table_html: str, notes: Notes) -> str:
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", table_html, re.S | re.I)
    cells_out, n_cols = [], 0
    occupied: set[tuple[int, int]] = set()
    for r, row in enumerate(rows):
        c = 0
        for m in re.finditer(r"<(t[dh])\b([^>]*)>(.*?)</t[dh]>", row, re.S | re.I):
            while (r, c) in occupied:
                c += 1
            rs = int((re.search(r'rowspan="(\d+)"', m.group(2)) or [0, 1])[1])
            cs = int((re.search(r'colspan="(\d+)"', m.group(2)) or [0, 1])[1])
            for dr in range(rs):
                for dc in range(cs):
                    occupied.add((r + dr, c + dc))
            body = html_inner_to_typst(m.group(3), notes)
            if m.group(1).lower() == "th":
                body = f"#strong[{body}]"
            cells_out.append(f"table.cell(colspan: {cs}, rowspan: {rs})[{body}]")
            c += cs
            n_cols = max(n_cols, c)
    if not cells_out:
        return ""
    return (f"#table(columns: {n_cols}, stroke: 0.5pt + rgb(\"#6b6255\"), inset: 3pt, align: left + horizon, "
            + ", ".join(cells_out) + ")")


# --------------------------------------------------------------------------- Faksimile-Hintergrund


def erase_text(background: Path, page: LPage, out: Path) -> Path:
    """Retuschiert die Textflächen (nur die Schrift, nicht Linien oder Abbildungen) aus dem Originalscan."""
    data = np.fromfile(str(background), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mask = np.zeros(gray.shape, np.uint8)
    for r in page.regions:
        if r.kind in IMAGE_KINDS or not r.target_md:
            continue
        for x0, y0, x1, y1 in r.erase_boxes or [r.box]:
            pad = max(3, int((y1 - y0) * 0.12))
            x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
            x1, y1 = min(gray.shape[1], x1 + pad), min(gray.shape[0], y1 + pad)
            sub = gray[y0:y1, x0:x1]
            if sub.size == 0:
                continue
            # Schrift = hebt sich vom Grund ab (dunkel auf Papier, hell auf dunklem Kasten);
            # weiche Buchstabenränder großzügig mitnehmen
            if np.median(sub) < 110:
                ground = np.percentile(sub, 15)
                spread = max(12.0, float(np.percentile(sub, 95) - ground) * 0.18)
                ink = (sub > ground + spread).astype(np.uint8) * 255
            else:
                paper = np.percentile(sub, 85)
                spread = max(12.0, float(paper - np.percentile(sub, 5)) * 0.18)
                ink = (sub < paper - spread).astype(np.uint8) * 255
            k = max(5, int((y1 - y0) * 0.06)) | 1
            ink = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
            mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], ink)
    if mask.any():
        scale = 0.5 if max(img.shape) > 2500 else 1.0  # Retusche halb aufgelöst (schneller), Ergebnis hochskaliert
        small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        small_mask = cv2.resize(mask, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
        filled = cv2.inpaint(small, small_mask, 5, cv2.INPAINT_TELEA)
        filled = cv2.resize(filled, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_CUBIC)
        img = np.where(mask[..., None] > 0, filled, img)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    buf.tofile(str(out))
    return out


# --------------------------------------------------------------------------- Seitensatz

PREAMBLE = r'''
#set text(font: ("Times New Roman", "Libertinus Serif"), lang: "de", hyphenate: false)
#set par(spacing: 0.3em)
#let placed(w, h, size, lead, track, al, wt, st, col, body) = move(dy: -0.35 * size,
  block(width: w, height: h + 0.35 * size, clip: true, inset: (top: 0.35 * size), {
    // Luft oben: Akzente über Versalien (Ü, Ś, Ż) ragen über den am Scan gemessenen Rahmen hinaus
    set text(size: size, weight: wt, style: st, tracking: track, fill: col)
    set par(leading: lead, justify: al == "justify")
    align(if al == "center" { center } else if al == "right" { right } else { left }, body)
  }))
'''


def _pt(px: float, dpi: float) -> float:
    return px / dpi * 72.0


def _region_typst(r: LRegion, page: LPage, notes: Notes, faksimile: bool, box_px=None) -> str:
    x0, y0, x1, y1 = box_px or r.box
    dpi = page.dpi
    dx, dy, w, h = _pt(x0, dpi), _pt(y0, dpi), _pt(x1 - x0, dpi), _pt(y1 - y0, dpi)
    place = f"#place(top + left, dx: {dx:.2f}pt, dy: {dy:.2f}pt)"
    if r.kind in IMAGE_KINDS:
        if faksimile or not r.image:
            return ""  # im Faksimile ist die Abbildung Teil des Hintergrunds
        return f'{place}[#image("{r.image}", width: {w:.2f}pt, height: {h:.2f}pt, fit: "stretch")]'
    text = r.target_md or r.source_md
    if not text.strip():
        return ""
    bold = r.bold or r.kind in HEADING_KINDS
    weight = '"bold"' if bold else '"regular"'
    style = '"italic"' if r.italic else '"normal"'
    fill = f'rgb("{r.color}")' if r.color else 'rgb("#1e1b17")'
    if r.kind == "tabelle":
        body = table_to_typst(text, notes)
        if not body:
            return ""
        return (f'{place}[#placed({w:.2f}pt, {h:.2f}pt, 9pt, 0.2em, 0em, "left", "regular", "normal", '
                f'rgb("#1e1b17"), [{body}])]')
    base = max(5.0, min(40.0, _pt(r.line_px or (y1 - y0), dpi) * 0.92))
    fit = fit_text(text, (dx, dy, w, h), base, bold, r.italic, r.spaced)
    if fit.truncated:
        notes.shortened.append((page.name, text))
    body = md_to_typst(fit.text_md, notes)
    if not body:
        return ""
    lead = max(0.05, fit.leading - 0.662) * fit.size  # Typst: Abstand zwischen Zeilen ab Versalhöhe
    return (f'{place}[#placed({w:.2f}pt, {h:.2f}pt, {fit.size:.2f}pt, {lead:.2f}pt, {fit.tracking:.3f}em, '
            f'"{r.align}", {weight}, {style}, {fill}, [{body}])]')


def decoration_typst(d: dict, page: LPage) -> str:
    """Kasten im Neusatz: Hintergrundfarbe und Rahmen wie im Original."""
    x0, y0, x1, y1 = d["box"]
    dpi = page.dpi
    fill = f'rgb("{d["fill"]}")' if d.get("fill") else "none"
    stroke = "none"
    if d.get("stroke"):
        thick = max(0.4, _pt(d.get("stroke_px") or 3, dpi))
        stroke = f'(paint: rgb("{d["stroke"]}"), thickness: {thick:.2f}pt, dash: "{d.get("dash") or "solid"}")'
    return (f"#place(top + left, dx: {_pt(x0, dpi):.2f}pt, dy: {_pt(y0, dpi):.2f}pt)"
            f"[#rect(width: {_pt(x1 - x0, dpi):.2f}pt, height: {_pt(y1 - y0, dpi):.2f}pt, fill: {fill}, "
            f"stroke: {stroke})]")


def build_typst(doc: LayoutDocument, faksimile: bool, translated: bool, handwriting: bool, title: str,
                appendix: bool = True) -> str:
    notes = Notes()
    parts = [PREAMBLE]
    work = Path(doc.workdir)
    for page in doc.pages:
        notes.page = page.name
        w_pt, h_pt = _pt(page.width_px, page.dpi), _pt(page.height_px, page.dpi)
        bg = ""
        if faksimile:
            name = f"faksimile-{page.number:04d}{'-de' if translated else '-pl'}.jpg"
            if translated and not (work / name).exists():  # einmal retuschieren, für Vorschau und Enddokument
                erase_text(work / page.background, page, work / name)
            else:
                name = page.background
            bg = f', background: image("{name}", width: 100%, height: 100%)'
        parts.append(f"#page(width: {w_pt:.2f}pt, height: {h_pt:.2f}pt, margin: 0pt{bg})[")
        if not faksimile:
            parts.extend(decoration_typst(d, page) for d in page.decorations)
        if translated or not faksimile:
            boxes = expand_boxes(page.regions, page.height_px, decorations=page.decorations)
            for r in page.regions:
                if not translated:
                    r = LRegion(**{**r.__dict__, "target_md": r.source_md})
                parts.append(_region_typst(r, page, notes, faksimile, boxes.get(r.id)))
        parts.append("]")
    if not appendix:
        return "\n".join(p for p in parts if p)
    # Anhang: Hinweise und Anmerkungen (Fließsatz, Format der letzten Seite)
    last = doc.pages[-1] if doc.pages else None
    w_pt = _pt(last.width_px, last.dpi) if last else 595
    h_pt = _pt(last.height_px, last.dpi) if last else 842
    parts.append(f'#set page(width: {w_pt:.2f}pt, height: {h_pt:.2f}pt, margin: 2cm)')
    parts.append("#set text(size: 9.5pt)")
    parts.append(f"#heading(level: 1)[{_tstr(title)}]")
    if handwriting:
        parts.append(f'#block(fill: rgb("#fbe9e6"), stroke: 0.8pt + rgb("#b3402f"), inset: 8pt, radius: 3pt)'
                     f'[#strong[{_tstr("Warnhinweis Handschrift: ")}]{_tstr(HANDWRITING_WARNING)}]')
    parts.append(f'#block(fill: rgb("#f6f1e7"), stroke: 0.8pt + rgb("#b9ae98"), inset: 8pt, radius: 3pt)[{_tstr(GENERAL_DISCLAIMER)}]')
    if translated:
        from quellenuebersetzer.pipeline import pruefbericht

        rows = [(n, l, i) for n, l, i in pruefbericht.summary(doc) if i]
        if rows:
            parts.append(f"#heading(level: 2)[{_tstr('Prüfbericht')}]")
            parts.append(_tstr("Seiten mit Auffälligkeiten (rot = Fehler, gelb = prüfen). Alle übrigen Seiten "
                               "ohne Hinweise.") + "\n")
            for name, l, issues in rows:
                col = "#b3402f" if l == "rot" else "#b38600"
                parts.append(f'#block[#text(fill: rgb("{col}"))[#strong[{_tstr(f"S. {name} ({l})")}]]]')
                parts.extend(f"- {_tstr(i)}" for i in issues)
    if notes.shortened:
        parts.append(f"#heading(level: 2)[{_tstr('Vollständiger Text gekürzter Bereiche')}]")
        parts.append(_tstr("Diese Bereiche passten auch bei engem Satz nicht vollständig auf ihre Seite "
                           "und sind dort mit […] gekürzt.") + "\n")
        for page_label, md in notes.shortened:
            parts.append(f"#block[#strong[{_tstr(f'S. {page_label}: ')}]{md_to_typst(md, Notes())}]")
    if notes.items:
        parts.append(f"#heading(level: 2)[{_tstr('Anmerkungen')}]")
        parts.append(_tstr("Orange gepunktet = Lesung unsicher · blau = Bedeutungswandel · grün gestrichelt = Begriff der Zeit.") + "\n")
        for page_label, n, text in notes.items:
            parts.append(f"- {_tstr(f'S. {page_label}, Anm. {n}: {text}')}")
    return "\n".join(p for p in parts if p)


def render_pdf(doc: LayoutDocument, out: Path, typst: Path, faksimile: bool = True, translated: bool = True,
               handwriting: bool = False, title: str = "") -> Path:
    work = Path(doc.workdir)
    src = work / ("satz-de.typ" if translated else "satz-pl.typ")
    src.write_text(build_typst(doc, faksimile, translated, handwriting, title or doc.title), encoding="utf-8")
    tmp = work / ("satz-de.pdf" if translated else "satz-pl.pdf")
    r = subprocess.run([str(typst), "compile", "--root", str(work), str(src), str(tmp)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=offline_env(), creationflags=_NO_WINDOW, timeout=1800)
    if r.returncode != 0 or not tmp.exists():
        msg = " ".join(r.stderr.strip().splitlines()[:3])[:400]
        raise RuntimeError(f"Seitengetreues PDF konnte nicht gesetzt werden: {msg}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    tmp.replace(out)
    return out


def original_preview(doc: LayoutDocument, page: LPage, out_dir: Path) -> Path:
    """Verkleinertes Originalbild einer gelesenen Seite für die Vorschau."""
    out_dir.mkdir(parents=True, exist_ok=True)
    original = out_dir / f"original-{page.number:04d}.jpg"
    if not original.exists():
        data = np.fromfile(str(Path(doc.workdir) / page.background), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        scale = 1100 / max(img.shape[:2])
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
        buf.tofile(str(original))
    return original


def render_preview(doc: LayoutDocument, page: LPage, typst: Path, out_dir: Path, faksimile: bool) -> tuple[Path, Path]:
    """Vorschaubilder einer fertig übersetzten Seite: (Original, Übersetzung) als PNG in niedriger Auflösung."""
    work = Path(doc.workdir)
    original = original_preview(doc, page, out_dir)
    single = LayoutDocument(doc.source, doc.title, doc.kind, doc.workdir, [page])
    src = work / f"vorschau-{page.number:04d}.typ"
    src.write_text(build_typst(single, faksimile, True, False, "", appendix=False), encoding="utf-8")
    translated = out_dir / f"uebersetzung-{page.number:04d}.png"
    ppi = max(40, min(110, int(1100 / max(1.0, page.height_px / page.dpi))))
    r = subprocess.run([str(typst), "compile", "--root", str(work), "--format", "png", "--ppi", str(ppi), str(src),
                        str(translated)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=offline_env(), creationflags=_NO_WINDOW, timeout=300)
    src.unlink(missing_ok=True)
    if r.returncode != 0 or not translated.exists():
        msg = " ".join(r.stderr.strip().splitlines()[:2])[:300]
        raise RuntimeError(f"Vorschau konnte nicht gesetzt werden: {msg}")
    return original, translated


# --------------------------------------------------------------------------- Vorschau des erkannten Seitenaufbaus

LAYOUT_COLORS = {
    "absatz": (59, 91, 169), "titel": (31, 58, 95), "ueberschrift": (31, 58, 95), "tabelle": (47, 125, 109),
    "abbildung": (179, 92, 0), "formel": (179, 92, 0), "bildunterschrift": (150, 110, 30),
    "randnotiz": (140, 60, 140), "fussnote": (120, 120, 120), "kopfzeile": (120, 120, 120),
    "fusszeile": (120, 120, 120), "seitenzahl": (120, 120, 120),
}


def layout_preview(doc: LayoutDocument, page: LPage, out_dir: Path) -> Path:
    """Seitenbild mit farbig umrahmten, beschrifteten Bereichen und Lesereihenfolge."""
    import os

    from PIL import Image, ImageDraw, ImageFont

    from quellenuebersetzer.pipeline.layout_doc import KIND_LABELS

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"aufbau-{page.number:04d}.jpg"
    with Image.open(Path(doc.workdir) / page.background) as im:
        scale = 1100 / max(im.size)
        img = im.convert("RGB").resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    img = Image.blend(img, Image.new("RGB", img.size, (255, 255, 255)), 0.35)  # Seite aufhellen, Rahmen betonen
    d = ImageDraw.Draw(img, "RGBA")
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    try:
        font = ImageFont.truetype(str(fonts / "segoeui.ttf"), 13)
    except OSError:
        font = ImageFont.load_default()
    for dec in page.decorations:  # erkannte Kästen (eigene Textflüsse)
        x0, y0, x1, y1 = (int(v * scale) for v in dec["box"])
        d.rectangle([x0 - 3, y0 - 3, x1 + 3, y1 + 3], outline=(150, 60, 150, 255), width=3)
        tw = d.textlength("Kasten", font=font)
        d.rectangle([x1 - tw - 6, y1 + 3, x1 + 3, y1 + 18], fill=(150, 60, 150, 230))
        d.text((x1 - tw - 3, y1 + 3), "Kasten", fill=(255, 255, 255), font=font)
    for n, r in enumerate(page.regions, start=1):
        color = LAYOUT_COLORS.get(r.kind, (59, 91, 169))
        x0, y0, x1, y1 = (int(v * scale) for v in r.box)
        d.rectangle([x0, y0, x1, y1], outline=color + (255,), width=2, fill=color + (28,))
        tag = f"{n} {KIND_LABELS.get(r.kind, r.kind)}"
        tw = d.textlength(tag, font=font)
        ty = max(0, y0 - 16)
        d.rectangle([x0, ty, x0 + tw + 6, ty + 15], fill=color + (230,))
        d.text((x0 + 3, ty), tag, fill=(255, 255, 255), font=font)
    img.save(out, quality=85)
    return out


def layout_summary(doc: LayoutDocument) -> str:
    from collections import Counter

    counts = Counter(r.kind for p in doc.pages for r in p.regions)
    parts = [f"{len(doc.pages)} Seiten"]
    for kind, word in (("tabelle", "Tabellen"), ("abbildung", "Abbildungen"), ("ueberschrift", "Überschriften"),
                       ("randnotiz", "Randnotizen"), ("fussnote", "Fußnoten")):
        if counts.get(kind):
            parts.append(f"{counts[kind]} {word}")
    return ", ".join(parts)
