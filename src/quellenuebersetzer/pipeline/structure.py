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

import numpy as np

from quellenuebersetzer.pipeline.features import PageFeatures, Panel
from quellenuebersetzer.runtime.layout import (
    MARGIN_KINDS,
    Region,
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


def _assign_containers(regions: list[Region], boxes: dict[str, Panel], ink: np.ndarray) -> list[Region]:
    out: list[Region] = []
    for r in regions:
        if r.kind in FIGURE_KINDS or r.kind == "tabelle":
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
        if r.container or r.kind not in ("absatz", "kopfzeile", "fusszeile", "randnotiz"):
            continue
        narrow = r.box[2] - r.box[0] < 0.25 * w
        outside = r.box[2] <= bx0 + tol or r.box[0] >= bx1 - tol
        if narrow and outside:
            r.kind = "randnotiz"
        elif r.kind == "kopfzeile" and r.box[3] > top + tol:
            r.kind = "absatz"
        elif r.kind == "fusszeile" and r.box[1] < bottom - tol:
            r.kind = "absatz"
        elif r.kind == "randnotiz" and not outside:
            r.kind = "absatz"


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


def build(raw: list[Region], feats: PageFeatures, ink: np.ndarray) -> tuple[list[Region], list[dict]]:
    """Endgültige Bereiche und Kästen (Dekorationen) einer Seite."""
    w, h = feats.width, feats.height
    scale = w / 2480.0
    figures = [r for r in raw if r.kind in FIGURE_KINDS]

    # 1. Kästen: Flächen, die nicht Abbildung und nicht Tabellenraster sind
    boxes: dict[str, Panel] = {}
    grids: list[Panel] = []
    for p in feats.panels:
        if any(_iou(p.box, f.box) > 0.4 or (_inter(p.box, f.box) and _area(_inter(p.box, f.box)) > 0.7 * _area(p.box))
               for f in figures):
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

    # 3. Textbereiche an Kastengrenzen teilen und Kästen zuordnen
    regions = _assign_containers(regions, boxes, ink)
    for kid, p in boxes.items():
        if not any(r.container == kid for r in regions):
            pad = max(4, p.stroke_px * 2)
            inner = (p.box[0] + pad, p.box[1] + pad, p.box[2] - pad, p.box[3] - pad)
            found = _shrink_to_ink(inner, ink)
            if found or p.dark:
                regions.append(Region("absatz", found or inner, 0.5, 10_000, kid))

    # 4. Spalten: Textbereiche über einer durchgehenden senkrechten Lücke teilen
    split: list[Region] = []
    for r in regions:
        if r.kind in TEXT_SPLIT_KINDS:
            parts = split_columns(r.box, ink, scale)
            if len(parts) > 1:
                split.extend(Region(r.kind, b, r.score, r.order + i * 0.01, r.container)
                             for i, b in enumerate(parts))
                continue
        split.append(r)

    # 5. Zusammenlegen (nur im selben Fluss), Überlappungen auflösen, Lage am Rand, Reihenfolge
    regions = resolve_overlaps(merge_lines(split))
    _margin_rules(regions, w, h)
    regions = _read_order(regions, boxes)
    decorations = []
    for kid, p in boxes.items():
        d = asdict(p)
        d["id"] = kid
        d["box"] = list(p.box)
        decorations.append(d)
    return regions, decorations
