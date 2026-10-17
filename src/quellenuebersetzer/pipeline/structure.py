"""Stufe B der Seitenaufbau-Erkennung: Entscheidung aus Modell und Merkmalsebenen.

Das Layoutmodell sagt, *was* wo ist (auf einem verkleinerten Bild). Die Merkmalsebenen aus ``features``
(volle Auflösung, Farbe) sagen, wo die Grenzen *genau* verlaufen. Regeln führen beides zusammen –
kein Signal entscheidet allein:

1. Kästen (Rahmen oder Hintergrundfarbe) werden zu eigenen Textflüssen. Ein Modellbereich, der über eine
   Kastengrenze reicht, wird dort geteilt; ein Kasten ohne Modellbereich bekommt einen eigenen.
2. Linienraster werden zu Tabellen – auch gestrichelte, die das Modell für Text hält.
3. Ein Textbereich über eine echte Spaltenlücke (senkrechter Weißraum über die ganze Höhe) wird geteilt.
4. Zusammenlegen nur innerhalb desselben Textflusses; Überlappungen auflösen.
5. Lesereihenfolge: ein Kasten ist eine Einheit im Seitenfluss und wird in sich gelesen.
"""

from __future__ import annotations

from dataclasses import asdict

import cv2
import numpy as np

from quellenuebersetzer.pipeline.features import PageFeatures, Panel
from quellenuebersetzer.runtime.layout import (
    MARGIN_KINDS,
    Region,
    _trim,
    _xy_cut,
    merge_lines,
    resolve_overlaps,
)

TEXT_SPLIT_KINDS = {"absatz", "fussnote", "randnotiz"}
FIGURE_KINDS = {"abbildung", "formel"}


def _area(b) -> int:
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _inter(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _iou(a, b) -> float:
    i = _inter(a, b)
    if not i:
        return 0.0
    return _area(i) / (_area(a) + _area(b) - _area(i))


def _shrink_to_ink(box, ink: np.ndarray, min_px: int = 12):
    x0, y0, x1, y1 = box
    sub = ink[y0:y1, x0:x1]
    if sub.size == 0 or not sub.any():
        return None
    ys, xs = np.nonzero(sub)
    out = (x0 + int(xs.min()), y0 + int(ys.min()), x0 + int(xs.max()) + 1, y0 + int(ys.max()) + 1)
    if out[2] - out[0] < min_px or out[3] - out[1] < min_px // 2:
        return None
    return out


def _subtract(box, hole):
    """Teile von ``box`` außerhalb von ``hole`` (oben, unten, links, rechts)."""
    x0, y0, x1, y1 = box
    hx0, hy0, hx1, hy1 = hole
    parts = []
    if hy0 > y0:
        parts.append((x0, y0, x1, min(y1, hy0)))
    if hy1 < y1:
        parts.append((x0, max(y0, hy1), x1, y1))
    my0, my1 = max(y0, hy0), min(y1, hy1)
    if my1 > my0:
        if hx0 > x0:
            parts.append((x0, my0, min(x1, hx0), my1))
        if hx1 < x1:
            parts.append((max(x0, hx1), my0, x1, my1))
    return [p for p in parts if p[2] > p[0] and p[3] > p[1]]


def _text_rows(sub: np.ndarray) -> list[tuple[int, int]]:
    rows = sub.any(axis=1)
    edges = np.flatnonzero(np.diff(np.concatenate([[0], rows.astype(np.int8), [0]])))
    return [(int(a), int(b)) for a, b in zip(edges[0::2], edges[1::2]) if b - a >= 3]


def split_columns(box, ink: np.ndarray, scale: float) -> list[tuple[int, int, int, int]]:
    """Teilt einen Textbereich an senkrechten Lücken, die über die ganze Höhe gehen (Spaltenzwischenraum)."""
    x0, y0, x1, y1 = box
    sub = ink[y0:y1, x0:x1] > 0
    if sub.size == 0:
        return [box]
    rows = _text_rows(sub)
    if len(rows) < 3:
        return [box]  # einzelne Zeilen: Wortabstände würden wie Spaltenlücken aussehen
    row_h = float(np.median([b - a for a, b in rows]))
    counts = sub.sum(axis=0)
    empty = counts <= max(1, int(0.004 * sub.shape[0]))
    edges = np.flatnonzero(np.diff(np.concatenate([[0], empty.astype(np.int8), [0]])))
    min_gap = max(int(18 * scale), int(0.6 * row_h))
    min_side = int(3 * row_h)
    cuts = []
    for a, b in zip(edges[0::2], edges[1::2]):
        if a == 0 or b >= sub.shape[1] or b - a < min_gap:
            continue
        cuts.append((int(a), int(b)))
    if not cuts:
        return [box]
    pieces, start = [], 0
    for a, b in cuts:
        pieces.append((start, a))
        start = b
    pieces.append((start, sub.shape[1]))
    if any(e - s < min_side for s, e in pieces):
        return [box]
    out = []
    for s, e in pieces:
        trimmed = _shrink_to_ink((x0 + s, y0, x0 + e, y1), ink)
        if trimmed:
            out.append(trimmed)
    return out or [box]


# --------------------------------------------------------------------------- Strukturwechsel innerhalb eines Bereichs


def _lab_median(pixels: np.ndarray) -> np.ndarray | None:
    if pixels.size == 0:
        return None
    px = pixels.reshape(-1, 3)
    if len(px) > 4000:
        px = px[:: len(px) // 4000]
    lab = cv2.cvtColor(np.median(px, axis=0).astype(np.uint8).reshape(1, 1, 3), cv2.COLOR_BGR2LAB)
    return lab[0, 0].astype(float)


def _row_info(sub_ink: np.ndarray, sub_color: np.ndarray, a: int, b: int, min_gap: int) -> dict:
    band = sub_ink[a:b] > 0
    cols = band.any(axis=0)
    xs = np.flatnonzero(cols)
    x0, x1 = int(xs[0]), int(xs[-1]) + 1
    inner = ~cols[x0:x1]
    edges = np.flatnonzero(np.diff(np.concatenate([[0], inner.astype(np.int8), [0]])))
    gaps = [(x0 + int(s), x0 + int(e)) for s, e in zip(edges[0::2], edges[1::2]) if e - s >= min_gap]
    color_band = sub_color[a:b]
    return {"a": a, "b": b, "x0": x0, "x1": x1, "gaps": gaps,
            "bg": _lab_median(color_band[~band]), "ink": _lab_median(color_band[band])}


def _differs(lab1, lab2, limit: float) -> bool:
    return lab1 is not None and lab2 is not None and float(np.linalg.norm(lab1 - lab2)) > limit


def split_structure(box, ink: np.ndarray, color: np.ndarray | None, scale: float) -> list[tuple[int, int, int, int]]:
    """Teilt einen Textbereich dort waagrecht, wo sich die Struktur ändert – Breite, Spaltenaufteilung,
    Hintergrundfarbe oder Schriftfarbe –, und danach jede Gruppe an echten Spaltenlücken.

    So bleibt ein breiterer Kasten, eine spaltenübergreifende Überschrift oder ein farbiger Block immer ein
    eigener Block, auch wenn das Layoutmodell ihn mit einer Spalte zu einem Rechteck zusammengefasst hat.
    """
    x0, y0, x1, y1 = box
    sub_ink = ink[y0:y1, x0:x1]
    if sub_ink.size == 0 or color is None:
        return split_columns(box, ink, scale)
    sub_color = color[y0:y1, x0:x1]
    rows = _text_rows(sub_ink > 0)
    if len(rows) < 2:
        return split_columns(box, ink, scale)
    row_h = float(np.median([b - a for a, b in rows]))
    min_gap = max(int(18 * scale), int(0.6 * row_h))
    tol = max(int(2.5 * row_h), int(0.05 * (x1 - x0)))
    infos = [_row_info(sub_ink, sub_color, a, b, min_gap) for a, b in rows]

    def gap_at(info: dict, center: int) -> bool:
        return any(s - min_gap <= center <= e + min_gap for s, e in info["gaps"])

    gaps_between = [b["a"] - a["b"] for a, b in zip(infos, infos[1:])]
    med_gap = float(np.median(gaps_between)) if gaps_between else 0.0
    heights = [r["b"] - r["a"] for r in infos]

    def new_style_line(i: int) -> bool:
        """Beginnt hier sichtbar etwas Neues? (größerer Abstand oder andere Schriftgröße)"""
        gap_before = infos[i]["a"] - infos[i - 1]["b"]
        h_prev, h_now = heights[i - 1], heights[i]
        return gap_before > 1.6 * max(1.0, med_gap) or max(h_prev, h_now) > 1.25 * max(1, min(h_prev, h_now))

    groups: list[list[dict]] = [[infos[0]]]
    for i, info in enumerate(infos[1:], start=1):
        grp = groups[-1]
        gx0 = int(np.median([r["x0"] for r in grp]))
        gx1 = max(r["x1"] for r in grp)
        common = [(s + e) // 2 for s, e in grp[0]["gaps"] if all(gap_at(r, (s + e) // 2) for r in grp)]
        change = (
            _differs(info["bg"], grp[-1]["bg"], 6.0)  # andere Hintergrundfarbe
            # andere Schriftfarbe – nur mit Abstand oder Größenwechsel (eine in den Text eingebettete farbige
            # Zwischenüberschrift bleibt beim Absatz, statt mitten im Wort abgeschnitten zu werden)
            or (_differs(info["ink"], grp[-1]["ink"], 30.0) and new_style_line(i))
            # breiter als die Gruppe (rechts erst ab einem Viertel mehr – kurze erste Zeilen sind normal)
            or info["x0"] < gx0 - tol or info["x1"] > gx1 + max(tol, (gx1 - gx0) // 4)
            or info["x0"] > gx0 + tol  # links eingerückt bzw. zentriert schmaler (z. B. Überschrift)
            # Spaltenlücke der Gruppe wird überquert oder nur eine Seite ist belegt
            or any(not gap_at(info, c) or info["x1"] <= c or info["x0"] >= c for c in common)
        )
        if not change and not common and info["gaps"] and i + 1 < len(infos):
            # neue Spaltenlücke, die auch in der nächsten Zeile besteht → hier beginnt ein mehrspaltiger Teil
            nxt = infos[i + 1]
            centers = [(s + e) // 2 for s, e in info["gaps"]]
            change = any(gap_at(nxt, c) and not any(gap_at(r, c) for r in grp) for c in centers)
        if change:
            groups.append([info])
        else:
            grp.append(info)
    out: list[tuple[int, int, int, int]] = []
    for grp in groups:
        gbox = (x0 + min(r["x0"] for r in grp), y0 + grp[0]["a"], x0 + max(r["x1"] for r in grp), y0 + grp[-1]["b"])
        out.extend(split_columns(gbox, ink, scale))
    return out or [box]


def style_key(box, ink: np.ndarray, color: np.ndarray | None) -> str:
    """Grobe Gestaltung eines Bereichs (Hintergrund, Schriftfarbe) – nur Gleiches wird zusammengelegt."""
    if color is None:
        return ""
    x0, y0, x1, y1 = box
    band = ink[y0:y1, x0:x1] > 0
    sub = color[y0:y1, x0:x1]
    parts = []
    # nur der Hintergrund: eine in den Text eingebettete farbige Zwischenüberschrift darf mit ihrem Absatz
    # zusammengelegt werden (gleiche Ränder sind ohnehin Bedingung); andere Hinterlegung trennt immer
    for lab, step in ((_lab_median(sub[~band]), 20),):
        if lab is None:
            parts.append("-")
            continue
        chroma = float(np.hypot(lab[1] - 128, lab[2] - 128))
        hue = int(np.degrees(np.arctan2(lab[2] - 128, lab[1] - 128)) // 45) if chroma > 12 else -1
        parts.append(f"{int(lab[0] // step)}:{hue}")
    return "|".join(parts)


def ensure_disjoint(regions: list[Region]) -> list[Region]:
    """Garantie: kein Bereich überlappt einen anderen. Der kleinere wird am größeren beschnitten;
    liegt er (fast) ganz darin, entfällt er (sein Inhalt gehört dann zum größeren)."""
    kept: list[Region] = []
    for r in sorted(regions, key=lambda r: -_area(r.box)):
        box = r.box
        for k in kept:
            inter = _inter(box, k.box)
            if not inter:
                continue
            if _area(inter) > 0.6 * _area(box):
                box = None
                break
            box = _trim(box, k.box)
            if box is None:
                break
        if box is not None:
            r.box = box
            kept.append(r)
    return sorted(kept, key=lambda r: r.order)


def graphic_share(box, ink: np.ndarray, line_h: float) -> float:
    """Anteil der Schwärzung in großen zusammenhängenden Linienzügen (Straßen, Flüsse, Umrisse, Schraffuren).

    Text besteht aus vielen kleinen, getrennten Zeichen; eine Karte oder Zeichnung aus langen, verbundenen
    Linien. Liegt viel Schwärzung in Zusammenhängen, die weit größer sind als eine Zeile, ist es ein Bild.
    """
    x0, y0, x1, y1 = box
    sub = (ink[y0:y1, x0:x1] > 0).astype(np.uint8)
    total = int(sub.sum())
    if total < 200:
        return 0.0
    n, _labels, stats, _ = cv2.connectedComponentsWithStats(sub, connectivity=8)
    big = 0
    for i in range(1, n):
        bw, bh, area = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT], stats[i, cv2.CC_STAT_AREA]
        # groß UND dünn verzweigt (Linienzug); große gefüllte Buchstaben eines Titels zählen nicht
        if ((bw > 5 * line_h and bh > 1.5 * line_h) or bh > 5 * line_h) and area < 0.25 * bw * bh:
            big += int(area)
    return big / total


def _char_like(box, ink: np.ndarray, line_h: float) -> int:
    """Zahl der zeichengroßen Zusammenhänge (Buchstaben) in einem Bereich."""
    x0, y0, x1, y1 = box
    sub = (ink[y0:y1, x0:x1] > 0).astype(np.uint8)
    if sub.size == 0:
        return 0
    n, _l, stats, _ = cv2.connectedComponentsWithStats(sub, connectivity=8)
    hs, ws = stats[1:, cv2.CC_STAT_HEIGHT], stats[1:, cv2.CC_STAT_WIDTH]
    return int(((hs >= 0.25 * line_h) & (hs <= 1.6 * line_h) & (ws <= 2.0 * line_h)).sum())


def color_variety(box, color: np.ndarray | None) -> float:
    """Anteil der Fläche, der nicht die vorherrschende Farbe hat (Schrift herausgefiltert).

    Ein Textblock – auch ein farbiger Kasten – ist bis auf die Schrift einfarbig (nahe 0); ein Plan hat
    Straßen, Wasser, Grünflächen, Symbole (deutlich darüber).
    """
    if color is None:
        return 0.0
    x0, y0, x1, y1 = box
    sub = color[y0:y1, x0:x1]
    if sub.size == 0:
        return 0.0
    f = max(1, round(sub.shape[1] / 300))
    small = cv2.resize(sub, None, fx=1 / f, fy=1 / f, interpolation=cv2.INTER_AREA)
    if min(small.shape[:2]) < 10:
        return 0.0
    smooth = cv2.medianBlur(cv2.medianBlur(small, 7), 7)
    lab = cv2.cvtColor(smooth, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    dominant = np.median(lab, axis=0)
    return float((np.linalg.norm(lab - dominant, axis=1) > 12).mean())


def is_drawing(box, ink: np.ndarray, color: np.ndarray | None, line_h: float) -> bool:
    """Zeichnung, Karte oder Plan statt Text: große Linienzüge oder viele Farbflächen bei geringer Schriftdichte."""
    if graphic_share(box, ink, line_h) > 0.35:
        return True
    area = max(1, _area(box))
    density = _char_like(box, ink, line_h) * line_h * line_h / area  # Text ≥ 0,15, Pläne ≤ 0,03
    return color_variety(box, color) > 0.22 and density < 0.08


def _crop_ink(ink: np.ndarray, box) -> np.ndarray:
    x0, y0, x1, y1 = box
    return ink[y0:y1, x0:x1] > 0


def _assign_containers(regions: list[Region], boxes: dict[str, Panel], ink: np.ndarray) -> list[Region]:
    out: list[Region] = []
    for r in regions:
        if r.kind in FIGURE_KINDS or r.kind == "tabelle":
            # Tabellen und Abbildungen werden nie geteilt – liegen sie in einem Kasten, gehören sie zu ihm
            for kid, p in boxes.items():
                inter = _inter(r.box, p.box)
                if inter and _area(inter) > 0.85 * _area(r.box):
                    r.container = kid
                    break
            out.append(r)
            continue
        pending = [r]
        for kid, p in boxes.items():
            nxt = []
            for q in pending:
                if q.container:
                    nxt.append(q)
                    continue
                inter = _inter(q.box, p.box)
                share = _area(inter) / max(1, _area(q.box)) if inter else 0.0
                if share > 0.85:
                    q.box = inter
                    q.container = kid
                    nxt.append(q)
                elif share > 0.03:
                    # über die Kastengrenze: innen und außen getrennt weiterführen
                    inside = _shrink_to_ink(inter, ink)
                    if inside:
                        nxt.append(Region(q.kind, inside, q.score, q.order, kid))
                    for part in _subtract(q.box, p.box):
                        trimmed = _shrink_to_ink(part, ink)
                        if trimmed:
                            nxt.append(Region(q.kind, trimmed, q.score, q.order, ""))
                else:
                    nxt.append(q)
            pending = nxt
        out.extend(pending)
    return out


def _margin_rules(regions: list[Region], w: int, h: int) -> None:
    """Lage entscheidet mit: schmaler Text neben dem Haupttext ist eine Randnotiz;
    eine Kopfzeile steht über, eine Fußzeile unter dem Haupttext – sonst ist es gewöhnlicher Text."""
    body = [r for r in regions if r.kind in ("absatz", "tabelle") and not r.container
            and r.box[2] - r.box[0] > 0.3 * w]
    if not body:
        return
    bx0, bx1 = min(r.box[0] for r in body), max(r.box[2] for r in body)
    top, bottom = min(r.box[1] for r in body), max(r.box[3] for r in body)
    tol = int(0.01 * w)
    for r in regions:
        if r.container or r.kind not in ("absatz", "kopfzeile", "fusszeile", "randnotiz", "fussnote"):
            continue
        narrow = r.box[2] - r.box[0] < 0.25 * w
        outside = r.box[2] <= bx0 + tol or r.box[0] >= bx1 - tol
        if r.kind == "fussnote":
            if r.box[1] > 0.6 * h:
                continue  # Fußnoten stehen im unteren Teil der Seite
            r.kind = "randnotiz" if narrow and outside else "absatz"
            continue
        if narrow and outside:
            r.kind = "randnotiz"
        elif r.kind == "kopfzeile" and r.box[3] > top + tol:
            r.kind = "absatz"
        elif r.kind == "fusszeile" and r.box[1] < bottom - tol:
            r.kind = "absatz"
        elif r.kind == "randnotiz" and not outside:
            r.kind = "absatz"


def _reconcile_tables(regions: list[Region], boxes: dict[str, Panel], page_h: int) -> None:
    """Hinterlegungen in oder an einer Tabelle sind Teil der Tabelle, keine Kästen.

    - Ein Streifen ganz in einer Tabelle (Zebrazeile, hinterlegte Spalte, Kopfzeile) ist kein Kasten.
    - Eine hinterlegte Fläche, die eine Tabelle seitlich anschneidet und dieselbe Höhe hat, ist eine
      abgeschnittene hinterlegte Spalte: Die Tabelle wird um sie erweitert.
    - Meldet das Modell einen ganzen Kasten als Tabelle und darin eine kleinere Tabelle, gilt die kleinere;
      der Kasten bleibt Kasten (mit seinem übrigen Text).
    """
    tables = [r for r in regions if r.kind == "tabelle"]
    for t in list(tables):
        inner = [o for o in tables if o is not t and (i := _inter(o.box, t.box)) and _area(i) > 0.7 * _area(o.box)]
        if inner and any(_iou(t.box, p.box) > 0.7 for p in boxes.values()):
            regions.remove(t)
            tables.remove(t)
    tol = max(8, int(0.01 * page_h))
    for kid, p in list(boxes.items()):
        for t in tables:
            inter = _inter(p.box, t.box)
            if not inter:
                continue
            if _area(inter) > 0.8 * _area(p.box):
                del boxes[kid]  # Streifen in der Tabelle
                break
            same_rows = p.box[1] >= t.box[1] - tol and p.box[3] <= t.box[3] + tol
            if same_rows and _area(inter) < 0.8 * _area(t.box):
                t.box = (min(t.box[0], p.box[0]), t.box[1], max(t.box[2], p.box[2]), t.box[3])
                del boxes[kid]  # angeschnittene hinterlegte Spalte
                break


def _read_order(regions: list[Region], boxes: dict[str, Panel]) -> list[Region]:
    head = [r for r in regions if r.kind == "kopfzeile" and not r.container]
    side = [r for r in regions if r.kind == "randnotiz" and not r.container]
    foot = [r for r in regions if r.kind == "fussnote" and not r.container]
    tail = [r for r in regions if r.kind in ("fusszeile", "seitenzahl") and not r.container]
    main = [r for r in regions if r.kind not in MARGIN_KINDS and not r.container]
    members: dict[str, list[Region]] = {}
    for r in regions:
        if r.container:
            members.setdefault(r.container, []).append(r)
    pseudo = {kid: Region("absatz", boxes[kid].box, 1.0, min(m.order for m in ms), "@" + kid)
              for kid, ms in members.items()}
    ordered_main: list[Region] = []
    for r in _xy_cut(main + list(pseudo.values())):
        if r.container.startswith("@"):
            ordered_main.extend(_xy_cut(members[r.container[1:]]))
        else:
            ordered_main.append(r)
    ordered = (sorted(head, key=lambda r: r.box[1]) + ordered_main + sorted(side, key=lambda r: r.box[1])
               + sorted(foot, key=lambda r: r.box[1]) + sorted(tail, key=lambda r: r.box[1]))
    for i, r in enumerate(ordered):
        r.order = i
    return ordered


def build(raw: list[Region], feats: PageFeatures, ink: np.ndarray,
          color: np.ndarray | None = None) -> tuple[list[Region], list[dict]]:
    """Endgültige Bereiche und Kästen (Dekorationen) einer Seite."""
    w, h = feats.width, feats.height
    scale = w / 2480.0
    # Zeichnungen und Karten, die das Modell für Text hält, bleiben Bilder (große Linienzüge statt Zeichen)
    row_hs = [b - a for r in raw if r.kind in TEXT_SPLIT_KINDS
              for a, b in _text_rows(_crop_ink(ink, r.box))]
    line_h = float(np.median(row_hs)) if row_hs else 40.0 * scale
    for r in raw:
        if (r.kind not in FIGURE_KINDS and r.kind != "tabelle" and _area(r.box) > (6 * line_h) ** 2
                and is_drawing(r.box, ink, color, line_h)):
            r.kind = "abbildung"
    figures = [r for r in raw if r.kind in FIGURE_KINDS]

    # 1. Kästen: Flächen, die nicht Abbildung und nicht Tabellenraster sind
    boxes: dict[str, Panel] = {}
    grids: list[Panel] = []
    for p in feats.panels:
        hits = [f for f in figures if _iou(p.box, f.box) > 0.4
                or (_inter(p.box, f.box) and _area(_inter(p.box, f.box)) > 0.7 * _area(p.box))]
        whole = [f for f in hits if _iou(p.box, f.box) > 0.6]  # die Farbfläche IST die „Abbildung“
        if (whole and len(whole) == len(hits) and p.source == "farbe" and p.fill
                and len(_text_rows(_crop_ink(ink, p.box))) >= 2
                and not any(is_drawing(f.box, ink, color, line_h) for f in whole)):
            # einfarbiger Textkasten ist kein Bild, auch wenn das Modell es meint
            for f in whole:
                f.kind = "absatz"
            figures = [f for f in figures if f not in whole]
            hits = []
        if hits:
            continue
        if p.grid:
            grids.append(p)
            continue
        if _shrink_to_ink(p.box, ink) is None and not p.dark:
            continue  # leerer Rahmen
        boxes[f"k{len(boxes) + 1}"] = p

    # 2. Linienraster → Tabellen (auch wenn das Modell dort Text sieht)
    regions = [Region(r.kind, r.box, r.score, r.order) for r in raw]
    for g in grids:
        tables = [r for r in regions if r.kind == "tabelle" and _iou(r.box, g.box) > 0.2]
        if tables:
            tables[0].box = g.box
            for extra in tables[1:]:
                regions.remove(extra)
        else:
            regions.append(Region("tabelle", g.box, 1.0, min((r.order for r in regions), default=0)))
        regions = [r for r in regions if r.kind == "tabelle" or r.kind in FIGURE_KINDS
                   or not _inter(r.box, g.box) or _area(_inter(r.box, g.box)) < 0.5 * _area(r.box)]

    # 2b. Tabellen und Flächen abstimmen
    _reconcile_tables(regions, boxes, h)

    # 3. Textbereiche an Kastengrenzen teilen und Kästen zuordnen
    regions = _assign_containers(regions, boxes, ink)
    for kid, p in boxes.items():
        if not any(r.container == kid for r in regions):
            pad = max(4, p.stroke_px * 2)
            inner = (p.box[0] + pad, p.box[1] + pad, p.box[2] - pad, p.box[3] - pad)
            found = _shrink_to_ink(inner, ink)
            if (found and _char_like(found, ink, line_h) >= 5 and len(_text_rows(_crop_ink(ink, found))) >= 1
                    and found[2] - found[0] >= 2 * line_h):
                regions.append(Region("absatz", found, 0.5, 10_000, kid))

    # 4. Struktur: an Wechseln von Breite, Spaltenaufteilung und Farbe waagrecht teilen, dann an Spaltenlücken
    split: list[Region] = []
    for r in regions:
        if r.kind in TEXT_SPLIT_KINDS:
            parts = split_structure(r.box, ink, color, scale)
            if len(parts) > 1:
                split.extend(Region(r.kind, b, r.score, r.order + i * 0.01, r.container)
                             for i, b in enumerate(parts))
                continue
        split.append(r)

    # 5. Zusammenlegen (nur gleiche Breite, gleicher Fluss, gleiche Gestaltung), Überlappungen auflösen,
    #    Lage am Rand, Reihenfolge
    for r in split:
        r.style = style_key(r.box, ink, color) if r.kind == "absatz" else r.kind
    row_hs = [b - a for r in split if r.kind == "absatz"
              for a, b in _text_rows(ink[r.box[1]:r.box[3], r.box[0]:r.box[2]] > 0)]
    line_px = float(np.median(row_hs)) * 1.6 if row_hs else None  # Zeilenhöhe samt Durchschuss
    regions = ensure_disjoint(resolve_overlaps(merge_lines(split, line_px)))
    _margin_rules(regions, w, h)
    # Randnotizen entstehen teils erst durch die Lage – ihre Teile jetzt zusammenführen
    regions = ensure_disjoint(merge_lines(regions, line_px))
    regions = _read_order(regions, boxes)
    decorations = []
    for kid, p in boxes.items():
        d = asdict(p)
        d["id"] = kid
        d["box"] = list(p.box)
        decorations.append(d)
    return regions, decorations
