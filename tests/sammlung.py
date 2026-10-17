"""Testsammlung für die Layouterkennung: synthetische Seiten mit Lösungsblatt.

Jede Seite wird deterministisch erzeugt (gleiches Ergebnis bei jedem Lauf) und liefert neben dem Bild
die „Wahrheit“: Blöcke mit Art, Rahmen, Wörtern, Lesereihenfolge, Textfluss und Gestaltung,
Tabellen mit Zellraster und Kopfzeile sowie grafische Elemente, die *nicht* als Text gelesen werden dürfen.

Alle Texte sind erfunden (polnische Wörter in zufälliger Folge) – es gibt keine echten Quellen im Projekt.
Jede Seite gibt es sauber und gealtert (Vergilbung, ungleichmäßige Belichtung, blasse Schrift, Rauschen,
Unschärfe). Die Geometrie bleibt unverändert, damit die Rahmen des Lösungsblatts gültig bleiben.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
W, H = 2480, 3508  # A4 bei 300 dpi
PAPER = (246, 242, 234)
INK = (28, 24, 22)

WORDS = (
    "starosta grodowy zatwierdził przywilej dla cechu młynarzy nakazał każdy młyn płacił dwa złote rocznie "
    "miasto rada wójt ławnicy sąd kościół parafia klasztor dobra ziemskie dziedzic folwark wieś karczma "
    "podatek czynsz dziesięcina kupiec rzemieślnik mieszczanin szlachcic chłop pańszczyzna dzień tydzień "
    "zboże żyto pszenica owies jęczmień beczka korzec łan włóka morga sól piwo miód wosk sukno płótno "
    "pieniądze grosz talar dukat rachunek rejestr księga akta dokument pieczęć podpis świadek przysięga "
    "wojewoda kasztelan biskup proboszcz pisarz burmistrz cech mistrz czeladnik uczeń warsztat jarmark "
    "targ droga rzeka most brzeg łąka las pole ogród dom ulica rynek brama mur wieża zamek dwór"
).split()


def font(size: int, bold: bool = False, italic: bool = False, family: str = "times") -> ImageFont.FreeTypeFont:
    names = {
        "times": {(0, 0): "times.ttf", (1, 0): "timesbd.ttf", (0, 1): "timesi.ttf", (1, 1): "timesbi.ttf"},
        "georgia": {(0, 0): "georgia.ttf", (1, 0): "georgiab.ttf", (0, 1): "georgiai.ttf", (1, 1): "georgiaz.ttf"},
        "arial": {(0, 0): "arial.ttf", (1, 0): "arialbd.ttf", (0, 1): "ariali.ttf", (1, 1): "arialbi.ttf"},
    }[family]
    return ImageFont.truetype(str(FONTS / names[(int(bold), int(italic))]), size)


def hexcolor(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(c) for c in rgb)


@dataclass
class TBlock:
    id: str
    kind: str  # absatz | titel | ueberschrift | randnotiz | fussnote | seitenzahl | kopfzeile | bildunterschrift
    #            | tabelle | abbildung | kasten | dekor
    box: tuple[int, int, int, int]
    flow: str = ""  # Textfluss (Spalte, Kasten, Rand …): Text verschiedener Flüsse darf nie vermischt werden
    words: list[str] = field(default_factory=list)
    order: int = -1  # Lesereihenfolge im Haupttext (-1 = außerhalb)
    color: str = ""  # Schriftfarbe, leer = normale dunkle Schrift
    bold: bool = False
    bg: str = ""  # Hintergrundfarbe (Kasten)
    frame: str = ""  # solid | dashed | dotted
    table: dict | None = None  # rows, cols, header, cells, lines


@dataclass
class Page:
    name: str
    image: Image.Image
    blocks: list[TBlock]

    def truth(self) -> dict:
        from dataclasses import asdict

        return {"name": self.name, "size": [W, H], "blocks": [asdict(b) for b in self.blocks]}


class Canvas:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.img = Image.new("RGB", (W, H), PAPER)
        self.d = ImageDraw.Draw(self.img)
        self.blocks: list[TBlock] = []
        self.order = 0

    def words(self, n: int) -> list[str]:
        ws = [self.rng.choice(WORDS) for _ in range(n)]
        ws[0] = ws[0].capitalize()
        return ws

    def add(self, block: TBlock, main: bool = True) -> TBlock:
        if main:
            block.order = self.order
            self.order += 1
        block.id = block.id or f"b{len(self.blocks) + 1}"
        self.blocks.append(block)
        return block

    # ------------------------------------------------------------------ Text
    def paragraph(self, x: int, y: int, width: int, n_words: int, size: int = 42, flow: str = "", kind: str = "absatz",
                  bold: bool = False, color=INK, main: bool = True, words: list[str] | None = None,
                  leading: float = 1.4, align: str = "left") -> TBlock:
        f = font(size, bold)
        words = words or self.words(n_words)
        lines, cur = [], []
        for w in words:
            trial = " ".join(cur + [w])
            if cur and f.getlength(trial) > width:
                lines.append(cur)
                cur = [w]
            else:
                cur.append(w)
        if cur:
            lines.append(cur)
        step = int(size * leading)
        x1 = x
        for i, ln in enumerate(lines):
            text = " ".join(ln)
            lx = x + (width - f.getlength(text)) / 2 if align == "center" else x
            self.d.text((lx, y + i * step), text, font=f, fill=color)
            x1 = max(x1, int(lx + f.getlength(text)))
        top = y + int(size * 0.18)
        box = (x if align != "center" else int(min(x + (width - f.getlength(" ".join(l))) / 2 for l in lines)),
               top, x1, y + (len(lines) - 1) * step + int(size * 1.02))
        return self.add(TBlock("", kind, box, flow or kind, words, color="" if color == INK else hexcolor(color),
                               bold=bold), main=main)

    # ------------------------------------------------------------------ Linien
    def hline(self, x0: int, x1: int, y: int, style: str = "solid", width: int = 3, color=INK) -> None:
        if style == "solid":
            self.d.line([(x0, y), (x1, y)], fill=color, width=width)
            return
        dash, gap = {"dashed": (16, 10), "dotted": (3, 9), "faint": (40, 22)}[style]
        x = x0
        while x < x1:
            self.d.line([(x, y), (min(x1, x + dash), y)], fill=color, width=width)
            x += dash + gap

    def vline(self, x: int, y0: int, y1: int, style: str = "solid", width: int = 3, color=INK) -> None:
        if style == "solid":
            self.d.line([(x, y0), (x, y1)], fill=color, width=width)
            return
        dash, gap = {"dashed": (16, 10), "dotted": (3, 9), "faint": (40, 22)}[style]
        y = y0
        while y < y1:
            self.d.line([(x, y), (x, min(y1, y + dash))], fill=color, width=width)
            y += dash + gap

    def rect(self, box, style: str, width: int = 3, color=INK) -> None:
        x0, y0, x1, y1 = box
        self.hline(x0, x1, y0, style, width, color)
        self.hline(x0, x1, y1, style, width, color)
        self.vline(x0, y0, y1, style, width, color)
        self.vline(x1, y0, y1, style, width, color)

    # ------------------------------------------------------------------ Kasten
    def box(self, box, bg, frame: str = "", frame_color=INK, flow: str = "kasten") -> TBlock:
        if bg:
            self.d.rectangle(box, fill=bg)
        if frame:
            self.rect(box, frame, 4, frame_color)
        return self.add(TBlock("", "kasten", box, flow, bg=hexcolor(bg) if bg else "", frame=frame), main=False)

    # ------------------------------------------------------------------ Tabelle
    def table(self, x: int, y: int, col_w: list[int], rows: list[list[str]], lines: str, header: bool,
              header_style: str = "bold", size: int = 38, row_h: int = 78, shading: str = "") -> TBlock:
        """lines: solid | dashed | dotted | faint | horizontal | none; header_style: bold | shaded | rule;
        shading: "" | zebra (jede zweite Zeile hinterlegt) | columns (jede zweite Spalte hinterlegt).
        Zellen mit „\\n“ werden mehrzeilig gesetzt (die Zeile wird entsprechend höher)."""
        n_rows, n_cols = len(rows), len(col_w)
        xs = [x]
        for w in col_w:
            xs.append(xs[-1] + w)
        step = int(size * 1.25)
        heights = [row_h + step * (max(v.count("\n") for v in row)) for row in rows]
        ys = [y]
        for hgt in heights:
            ys.append(ys[-1] + hgt)
        tint = (232, 236, 244)
        if shading == "zebra":
            for r in range(n_rows):
                if r % 2 == 1:
                    self.d.rectangle([xs[0], ys[r], xs[-1], ys[r + 1]], fill=tint)
        elif shading == "columns":
            for c in range(n_cols):
                if c % 2 == 1:
                    self.d.rectangle([xs[c], ys[0], xs[c + 1], ys[-1]], fill=tint)
        if header and header_style == "shaded":
            self.d.rectangle([xs[0], ys[0], xs[-1], ys[1]], fill=(215, 222, 232))
        if lines in ("solid", "dashed", "dotted", "faint"):
            color = (150, 140, 128) if lines == "faint" else INK
            for yy in ys:
                self.hline(xs[0], xs[-1], yy, lines, 3, color)
            for xx in xs:
                self.vline(xx, ys[0], ys[-1], lines, 3, color)
        elif lines == "horizontal":
            for yy in (ys[0], ys[-1]):
                self.hline(xs[0], xs[-1], yy, "solid", 3)
            for yy in ys[1:-1]:
                self.hline(xs[0], xs[-1], yy, "dotted", 3)
        if header and header_style == "rule":
            self.hline(xs[0], xs[-1], ys[1] - 2, "solid", 7)
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                f = font(size, bold=header and r == 0 and header_style == "bold")
                for k, part in enumerate(val.split("\n")):
                    self.d.text((xs[c] + 20, ys[r] + (row_h - size) // 2 - 4 + k * step), part, font=f, fill=INK)
        cells = [[v.replace("\n", " ") for v in row] for row in rows]
        words = [w for row in cells for v in row for w in v.split()]
        t = {"rows": n_rows, "cols": n_cols, "header": header, "cells": cells, "lines": lines}
        return self.add(TBlock("", "tabelle", (xs[0], ys[0], xs[-1], ys[-1]), f"tabelle{len(self.blocks) + 1}", words,
                               table=t))

    def table_rows(self, n_rows: int, n_cols: int, header: bool) -> list[list[str]]:
        rows = []
        if header:
            rows.append([self.rng.choice(WORDS).capitalize() for _ in range(n_cols)])
        while len(rows) < n_rows:
            row = [self.rng.choice(WORDS).capitalize() + " " + self.rng.choice(WORDS)]
            row += [str(self.rng.randint(2, 480)) for _ in range(n_cols - 1)]
            rows.append(row)
        return rows

    # ------------------------------------------------------------------ Sonstiges
    def figure(self, box) -> TBlock:
        x0, y0, x1, y1 = box
        self.d.rectangle(box, outline=(60, 55, 50), width=5)
        for k in range(0, x1 - x0 - 40, 16):
            self.d.line([(x0 + 20 + k, y0 + 20), (x0 + 20 + k // 2, y1 - 20)], fill=(110, 100, 90), width=3)
        self.d.ellipse([x0 + (x1 - x0) // 3, y0 + (y1 - y0) // 4, x0 + 2 * (x1 - x0) // 3, y0 + 3 * (y1 - y0) // 4],
                       outline=(40, 35, 30), width=8)
        return self.add(TBlock("", "abbildung", box, "abbildung"), main=False)

    def ornament(self, x0: int, x1: int, y: int) -> TBlock:
        """Schmucklinie (Wellen und Rauten) – Grafik, darf nicht als Zeichen gelesen werden."""
        for x in range(x0, x1, 24):
            self.d.arc([x, y - 8, x + 24, y + 8], 0, 180, fill=INK, width=3)
        mid = (x0 + x1) // 2
        self.d.polygon([(mid, y - 18), (mid + 18, y), (mid, y + 18), (mid - 18, y)], fill=INK)
        return self.add(TBlock("", "dekor", (x0, y - 20, x1, y + 20), "dekor"), main=False)

    def page(self, name: str) -> Page:
        return Page(name, self.img, self.blocks)


# --------------------------------------------------------------------------- Seitentypen


def p_zweispaltig(c: Canvas) -> None:
    c.paragraph(250, 230, 1980, 0, 34, "kopf", "kopfzeile", main=False, words="Kronika miasta tom drugi".split())
    c.paragraph(250, 380, 1980, 0, 76, "titel", "titel", bold=True, words="O młynach i cechach miejskich".split(),
                align="center")
    c.paragraph(250, 600, 960, 150, 42, "spalte1")
    c.paragraph(1270, 600, 960, 150, 42, "spalte2")  # schmale Spaltenlücke (60 px ≈ 5 mm)
    c.hline(250, 800, 3120, "solid", 2)
    c.paragraph(250, 3150, 1980, 14, 32, "fuss", "fussnote", main=False,
                words=["¹"] + c.words(13))
    c.paragraph(1220, 3330, 100, 0, 34, "seite", "seitenzahl", main=False, words=["17"])


def p_dreispaltig(c: Canvas) -> None:
    c.paragraph(250, 260, 1980, 0, 60, "titel", "ueberschrift", bold=True, words="Rejestr podatków z dóbr ziemskich".split())
    for i in range(3):
        c.paragraph(250 + i * 680, 450, 620, 130, 38, f"spalte{i + 1}")  # Lücke 60 px
    c.paragraph(1220, 3330, 100, 0, 34, "seite", "seitenzahl", main=False, words=["18"])


def p_kasten_hell(c: Canvas) -> None:
    c.paragraph(250, 250, 1980, 0, 56, "titel", "ueberschrift", bold=True, color=(165, 30, 25),
                words="Rozdział trzeci o jarmarkach".split())
    c.paragraph(250, 420, 1980, 70, 42, "text")
    # heller, gerahmter Infokasten dicht unter dem Absatz
    k = c.box((250, 1000, 2230, 1720), (250, 238, 190), "solid", (120, 90, 30), flow="kasten1")
    c.paragraph(310, 1050, 1860, 0, 46, "kasten1", "ueberschrift", bold=True,
                words="Przypis o miarach zboża".split())
    c.paragraph(310, 1150, 1860, 70, 40, "kasten1")
    c.paragraph(250, 1790, 1980, 90, 42, "text2")
    c.paragraph(250, 2600, 1980, 0, 46, "titel2", "ueberschrift", bold=True, color=(30, 60, 140),
                words="Targi i drogi handlowe".split())
    c.paragraph(250, 2710, 1980, 50, 42, "text3")
    del k


def p_kasten_dunkel(c: Canvas) -> None:
    c.paragraph(250, 250, 1980, 80, 42, "text")
    c.box((250, 950, 2230, 1550), (32, 45, 78), "", flow="kasten1")
    c.paragraph(320, 1000, 1840, 0, 50, "kasten1", "ueberschrift", bold=True, color=(250, 248, 240),
                words="Ważne postanowienia rady".split())
    c.paragraph(320, 1110, 1840, 60, 42, "kasten1", color=(245, 242, 232))
    c.paragraph(250, 1620, 1980, 60, 42, "text2")
    c.box((400, 2250, 2080, 2900), (228, 228, 224), "dashed", flow="kasten2")
    c.paragraph(460, 2300, 1560, 70, 40, "kasten2")
    c.paragraph(250, 2980, 1980, 25, 42, "text3")


def p_tabelle_linien(c: Canvas) -> None:
    c.paragraph(250, 250, 1980, 40, 42, "text")
    c.table(250, 600, [700, 420, 420, 420], c.table_rows(8, 4, True), "solid", True, "shaded")
    c.paragraph(250, 1400, 1980, 60, 42, "text2")


def p_tabelle_gestrichelt(c: Canvas) -> None:
    c.paragraph(250, 250, 1980, 40, 42, "text")
    c.table(250, 600, [760, 400, 400, 400], c.table_rows(9, 4, False), "dashed", False)
    c.paragraph(250, 1450, 1980, 60, 42, "text2")


def p_tabelle_gepunktet(c: Canvas) -> None:
    c.paragraph(250, 250, 1980, 40, 42, "text")
    c.table(250, 600, [760, 400, 400, 400], c.table_rows(9, 4, True), "horizontal", True, "bold")
    c.paragraph(250, 1450, 1980, 40, 42, "text2")
    c.table(250, 1900, [760, 500, 500], c.table_rows(6, 3, False), "faint", False)


def p_tabelle_ohne_linien(c: Canvas) -> None:
    c.paragraph(250, 250, 1980, 40, 42, "text")
    c.table(250, 600, [760, 420, 420, 420], c.table_rows(9, 4, True), "none", True, "rule")
    c.paragraph(250, 1450, 1980, 60, 42, "text2")


def p_marginalien(c: Canvas) -> None:
    c.paragraph(600, 250, 1630, 110, 42, "text")
    c.paragraph(150, 300, 360, 0, 32, "rand1", "randnotiz", main=False, words="Por. akta z roku 1612".split())
    c.paragraph(150, 900, 360, 0, 32, "rand2", "randnotiz", main=False, words="Nota pisarza".split())
    c.ornament(600, 2230, 1300)
    c.figure((800, 1400, 2030, 2300))
    c.paragraph(800, 2340, 1230, 0, 34, "unterschrift", "bildunterschrift", words="Ryc. 2. Młyn wodny pod miastem".split())
    c.paragraph(600, 2520, 1630, 60, 42, "text2")


def p_gemischt(c: Canvas) -> None:
    c.paragraph(250, 230, 1980, 0, 64, "titel", "ueberschrift", bold=True, words="Sprawy cechowe".split())
    c.paragraph(250, 420, 950, 120, 40, "spalte1")
    c.box((1280, 420, 2230, 1200), (222, 236, 222), "solid", (40, 90, 40), flow="kasten1")
    c.paragraph(1330, 460, 850, 55, 38, "kasten1")
    c.paragraph(1280, 1260, 950, 60, 40, "spalte2")
    c.table(250, 2000, [700, 400, 400], c.table_rows(5, 3, True), "solid", True, "bold")
    c.paragraph(250, 2500, 1980, 50, 40, "text3")


def p_spaltenuebergreifend(c: Canvas) -> None:
    """Zwei Spalten, dazwischen ein breiter farbiger Kasten ohne Rahmen und eine Zwischenüberschrift über beide
    Spalten, darunter wieder zwei Spalten – breitere Elemente dürfen nie mit einer Spalte verschmelzen."""
    c.paragraph(250, 250, 960, 45, 40, "spalte1a")
    c.paragraph(1270, 250, 960, 45, 40, "spalte2a")
    c.box((250, 700, 2230, 1150), (226, 236, 248), "", flow="kasten1")  # zartes Blau, kein Rahmen
    c.paragraph(300, 740, 1880, 60, 40, "kasten1")
    c.paragraph(250, 1210, 1980, 0, 50, "zwischen", "ueberschrift", bold=True, color=(150, 40, 30),
                words="Rejestr młynów i karczem".split())
    c.paragraph(250, 1330, 960, 70, 40, "spalte1b")
    c.paragraph(1270, 1330, 960, 70, 40, "spalte2b")
    c.paragraph(250, 2050, 960, 60, 40, "spalte1c")
    c.box((1270, 2050, 2000, 2500), (250, 236, 200), "", flow="kasten2")  # schmaler als die Spalte
    c.paragraph(1310, 2090, 650, 30, 36, "kasten2")


def p_farbige_bloecke(c: Canvas) -> None:
    """Eng gesetzte Blöcke, die sich nur durch Farbe unterscheiden: farbige Unterüberschrift direkt über dem
    Fließtext, getönte Bänder über die ganze Breite direkt unter und über Spaltentext."""
    c.paragraph(250, 250, 1980, 0, 46, "titel", "ueberschrift", bold=True, color=(30, 70, 150),
                words="Przywileje miejskie".split())
    c.paragraph(250, 330, 1980, 60, 40, "text1")  # direkt darunter, normaler Zeilenabstand
    c.box((250, 760, 2230, 1060), (238, 228, 242), "", flow="band1")
    c.paragraph(300, 790, 1880, 40, 40, "band1")
    c.paragraph(250, 1080, 960, 60, 40, "spalte1")
    c.paragraph(1270, 1080, 960, 60, 40, "spalte2")
    c.box((250, 1700, 2230, 1950), (230, 240, 226), "", flow="band2")
    c.paragraph(300, 1730, 1880, 30, 40, "band2")
    c.paragraph(250, 1970, 1980, 50, 40, "text2", color=(120, 30, 30))  # ganzer Absatz in Rot


def p_tabelle_zebra(c: Canvas) -> None:
    """Tabelle ohne Linien, jede zweite Zeile zart hinterlegt, Kopfzeile fett."""
    c.paragraph(250, 250, 1980, 40, 42, "text")
    c.table(250, 600, [760, 420, 420, 420], c.table_rows(9, 4, True), "none", True, "bold", shading="zebra")
    c.paragraph(250, 1450, 1980, 40, 42, "text2")


def p_tabelle_mehrzeilig(c: Canvas) -> None:
    """Zellen mit Zeilenumbruch: oben mit Zebrastreifen, unten nur mit waagrechten Linien – je Zelle ein Inhalt."""
    c.paragraph(250, 250, 1980, 30, 42, "text")
    rows = c.table_rows(6, 3, True)
    for r in (1, 3, 4):
        rows[r][0] = rows[r][0] + "\n" + c.rng.choice(WORDS) + " " + c.rng.choice(WORDS)
    c.table(250, 520, [900, 450, 450], rows, "none", True, "bold", shading="zebra")
    rows2 = c.table_rows(5, 3, False)
    for r in (0, 2):
        rows2[r][0] = rows2[r][0] + "\n" + c.rng.choice(WORDS)
    c.table(250, 1700, [900, 450, 450], rows2, "horizontal", False)


def p_tabelle_spalten(c: Canvas) -> None:
    """Tabelle ohne Linien mit hinterlegten Spalten und nur hinterlegter Kopfzeile darüber."""
    c.paragraph(250, 250, 1980, 30, 42, "text")
    c.table(250, 520, [700, 400, 400, 400], c.table_rows(8, 4, False), "none", False, shading="columns")
    c.table(250, 1450, [700, 500, 500], c.table_rows(6, 3, True), "none", True, "shaded")


def p_tabelle_im_kasten(c: Canvas) -> None:
    """Tabelle ohne Linien in einem farbigen Kasten, darüber Kastentext."""
    c.paragraph(250, 250, 1980, 40, 42, "text")
    c.box((250, 650, 2230, 1500), (238, 232, 214), "solid", (120, 100, 60), flow="kasten1")
    c.paragraph(310, 690, 1860, 25, 40, "kasten1")
    c.table(310, 900, [700, 380, 380], c.table_rows(6, 3, True), "none", True, "bold")
    c.paragraph(250, 1580, 1980, 40, 42, "text2")


PAGE_TYPES = {
    "zweispaltig": p_zweispaltig,
    "dreispaltig": p_dreispaltig,
    "kasten_hell": p_kasten_hell,
    "kasten_dunkel": p_kasten_dunkel,
    "tabelle_linien": p_tabelle_linien,
    "tabelle_gestrichelt": p_tabelle_gestrichelt,
    "tabelle_gepunktet": p_tabelle_gepunktet,
    "tabelle_ohne_linien": p_tabelle_ohne_linien,
    "marginalien": p_marginalien,
    "gemischt": p_gemischt,
    "spaltenuebergreifend": p_spaltenuebergreifend,
    "farbige_bloecke": p_farbige_bloecke,
    "tabelle_zebra": p_tabelle_zebra,
    "tabelle_mehrzeilig": p_tabelle_mehrzeilig,
    "tabelle_spalten": p_tabelle_spalten,
    "tabelle_im_kasten": p_tabelle_im_kasten,
}


# --------------------------------------------------------------------------- Alterung (ohne Geometrieänderung)


def age(img: Image.Image, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    a = np.asarray(img).astype(np.float32)
    paper = np.array(PAPER, np.float32)
    a = paper + (a - paper) * 0.72  # blassere Schrift und Farben
    a *= np.array([1.0, 0.95, 0.84], np.float32)  # Vergilbung
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    light = 1.0 - 0.22 * (((xx - W * 0.8) / W) ** 2 + ((yy - H * 0.2) / H) ** 2)  # ungleichmäßige Belichtung
    a *= light[..., None]
    a += rng.normal(0, 7, a.shape).astype(np.float32)
    out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    from PIL import ImageFilter

    return out.filter(ImageFilter.GaussianBlur(0.9))


def build(name: str, aged: bool = False) -> Page:
    seed = sum(ord(ch) for ch in name) * 7919
    c = Canvas(seed)
    PAGE_TYPES[name](c)
    page = c.page(name + ("_alt" if aged else ""))
    if aged:
        page.image = age(page.image, seed)
        for b in page.blocks:  # Farben im Lösungsblatt wie das Bild altern lassen (ohne Belichtung)
            b.color, b.bg = aged_color(b.color), aged_color(b.bg)
    return page


def aged_color(hexcolor: str) -> str:
    if not hexcolor:
        return hexcolor
    c = [int(hexcolor[i:i + 2], 16) for i in (1, 3, 5)]
    c = [p + (v - p) * 0.72 for v, p in zip(c, PAPER)]
    c = [v * f for v, f in zip(c, (1.0, 0.95, 0.84))]
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, v))) for v in c)


def collection(aged: bool = True) -> list[Page]:
    pages = [build(n) for n in PAGE_TYPES]
    if aged:
        pages += [build(n, aged=True) for n in PAGE_TYPES]
    return pages
