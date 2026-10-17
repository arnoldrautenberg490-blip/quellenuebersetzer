"""Misst die Layouterkennung an der Testsammlung (tests/sammlung.py) – Phase 1 und 2, ohne Übersetzung.

Aufruf:  python tools/layout_messen.py <Datenwurzel mit runtime/> [Ergebnis.json] [--seiten name,name]

Kennzahlen je Seite (Ziele in Klammern):
  Blöcke     erkannte Blöcke des Lösungsblatts (Überlappung IoU ≥ 0,5)                       (≥ 95 %)
  Art        davon mit richtiger Art                                                       (≥ 95 %)
  Mischung   erkannte Bereiche, deren Zeilen aus zwei Textflüssen stammen (Spalte, Kasten …) (0)
  Wörter     wiedergefundene Wörter / doppelt gelesene Wörter                               (≥ 98 % / 0)
  Artefakte  Zeichenfolgen ohne Buchstaben/Ziffern (z. B. „----“, „....“, „|“)              (0)
  Erfunden   Fußnoten/Seitenzahlen/Randnotizen/Kopfzeilen ohne Gegenstück, falsche Kopfzeilen (0)
  Tabellen   gefunden · Raster richtig · Zellen richtig gelesen                            (100 %)
  Gestaltung Schriftfarbe, Fettdruck, Hintergrund und Rahmen getroffen                       (≥ 90 %)
  Reihenfolge richtig geordnete Blockpaare im Haupttext                                    (≥ 95 %)
  Überlappung sich überschneidende Textrahmen nach dem Einpassen                           (0)
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from collections import Counter
from html.parser import HTMLParser
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import sammlung  # noqa: E402

KIND_OK = {
    "absatz": {"absatz"}, "titel": {"titel", "ueberschrift"}, "ueberschrift": {"ueberschrift", "titel"},
    "tabelle": {"tabelle"}, "fussnote": {"fussnote"}, "seitenzahl": {"seitenzahl", "fusszeile"},
    "randnotiz": {"randnotiz"}, "bildunterschrift": {"bildunterschrift"}, "abbildung": {"abbildung", "formel"},
    "kopfzeile": {"kopfzeile"},
}
STRUCT_KINDS = {"fussnote", "seitenzahl", "randnotiz", "kopfzeile", "fusszeile"}
MAIN_EXCLUDE = {"kopfzeile", "fussnote", "seitenzahl", "randnotiz", "abbildung", "kasten", "dekor"}


def iou(a, b) -> float:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def contains(box, pt, pad=12) -> bool:
    return box[0] - pad <= pt[0] <= box[2] + pad and box[1] - pad <= pt[1] <= box[3] + pad


def norm(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def plain(md: str) -> str:
    from quellenuebersetzer.pipeline import markup

    return markup.unescape_md(markup.strip_marks(md))


class _Grid(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.cell = [], None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            a = dict(attrs)
            self.cell = {"text": "", "th": tag == "th", "cs": int(a.get("colspan") or 1)}

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.rows[-1].append(self.cell)
            self.cell = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data


def table_grid(html: str) -> list[list[dict]]:
    p = _Grid()
    p.feed(plain(html) if "<table" not in html else html)
    return p.rows


def color_close(a: str, b: str, tol: int = 90) -> bool:
    if not a or not b:
        return False
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return sum((x - y) ** 2 for x, y in zip(ca, cb)) ** 0.5 < tol


# --------------------------------------------------------------------------- Messung einer Seite


def measure_page(page: sammlung.Page, lpage, seconds: float) -> dict:
    from quellenuebersetzer.pipeline.fitting import expand_boxes

    truth = page.blocks
    regions = lpage.regions
    deco = getattr(lpage, "decorations", []) or []
    res: dict = {"seite": page.name, "sekunden": round(seconds, 1)}

    # Blöcke und Arten (Kästen gegen erkannte Kästen, alles andere gegen Bereiche)
    t_blocks = [b for b in truth if b.kind not in ("dekor",)]
    found = kind_ok = 0
    best_region: dict[str, object] = {}
    for b in t_blocks:
        if b.kind == "kasten":
            cand = [(iou(b.box, tuple(d["box"])), d) for d in deco]
            score = max((s for s, _ in cand), default=0)
            if score >= 0.5:
                found += 1
                kind_ok += 1
            continue
        cand = sorted(((iou(b.box, r.box), r) for r in regions), key=lambda x: -x[0])
        if cand and cand[0][0] >= 0.5:
            found += 1
            best_region[b.id] = cand[0][1]
            if cand[0][1].kind in KIND_OK.get(b.kind, {b.kind}):
                kind_ok += 1
    res["bloecke"] = (found, len(t_blocks))
    res["art"] = (kind_ok, found)

    # Mischung: Zeilen eines erkannten Bereichs aus mehreren Textflüssen
    text_truth = [b for b in truth if b.kind not in ("kasten", "dekor", "abbildung")]

    def flow_of(pt):
        hits = [b for b in text_truth if contains(b.box, pt)]
        hits.sort(key=lambda b: (b.box[2] - b.box[0]) * (b.box[3] - b.box[1]))
        return hits[0].flow if hits else None

    mixed = 0
    region_flows: dict[str, Counter] = {}
    for r in regions:
        if r.kind in ("abbildung", "formel"):
            continue
        flows = Counter()
        for x0, y0, x1, y1 in r.erase_boxes or []:
            f = flow_of(((x0 + x1) / 2, (y0 + y1) / 2))
            if f:
                flows[f] += 1
        region_flows[r.id] = flows
        if len(flows) >= 2:
            mixed += 1
    res["mischung"] = mixed

    # Wörter
    t_words = Counter(norm(w) for b in text_truth for w in b.words if norm(w))
    o_tokens = []
    for r in regions:
        if not r.source_md:
            continue
        if r.kind == "tabelle":
            text = " ".join(c["text"] for row in table_grid(r.source_md) for c in row)
        else:
            text = plain(r.source_md)
        o_tokens += text.split()
    o_words = Counter(norm(w) for w in o_tokens if norm(w))
    hit = sum(min(n, o_words[w]) for w, n in t_words.items())
    dup = sum(max(0, o_words[w] - n) for w, n in t_words.items())
    res["woerter"] = (hit, sum(t_words.values()))
    res["doppelt"] = dup
    res["artefakte"] = sum(1 for t in o_tokens if not re.search(r"[\w]", t) and t not in ("–", "—", "-"))

    # Erfundene Strukturen
    invented = 0
    for r in regions:
        if r.kind in STRUCT_KINDS:
            ok = any(iou(r.box, b.box) > 0.2 and r.kind in KIND_OK.get(b.kind, {b.kind}) | {b.kind}
                     for b in truth)
            invented += 0 if ok else 1
    # Kopfzeilen in Tabellen
    header_wrong = 0
    tables = [b for b in truth if b.kind == "tabelle"]
    t_found = t_grid = 0
    cells_ok = cells_all = 0
    for b in tables:
        cand = [r for r in regions if r.kind == "tabelle" and iou(r.box, b.box) >= 0.3]
        cells_all += sum(len(row) for row in b.table["cells"])
        if not cand:
            continue
        t_found += 1
        grid = table_grid(cand[0].source_md)
        has_th = any(c["th"] for row in grid for c in row)
        if has_th != b.table["header"]:
            header_wrong += 1
        if len(grid) == b.table["rows"] and all(sum(c["cs"] for c in row) == b.table["cols"] for row in grid):
            t_grid += 1
            for tr, gr in zip(b.table["cells"], grid):
                for tv, gc in zip(tr, gr):
                    cells_ok += norm(tv) == norm(gc["text"])
    res["erfunden"] = invented + header_wrong
    res["kopfzeile_falsch"] = header_wrong
    res["tabellen"] = (t_found, t_grid, len(tables))
    res["zellen"] = (cells_ok, cells_all)

    # Gestaltung
    st_ok = st_all = 0
    for b in truth:
        r = best_region.get(b.id)
        if b.color:
            st_all += 1
            st_ok += bool(r and color_close(r.color, b.color))
        if b.bold:
            st_all += 1
            st_ok += bool(r and r.bold)
        if b.kind == "kasten":
            d = max(deco, key=lambda d: iou(b.box, tuple(d["box"])), default=None)
            if d is not None and iou(b.box, tuple(d["box"])) < 0.5:
                d = None
            if b.bg:
                st_all += 1
                st_ok += bool(d and color_close(d.get("fill", ""), b.bg, 60))
            if b.frame:
                st_all += 1
                st_ok += bool(d and d.get("stroke"))
    res["gestaltung"] = (st_ok, st_all)

    # Reihenfolge im Haupttext: Bereich mit den meisten Zeilen des Blocks zählt
    main = [b for b in truth if b.order >= 0 and b.kind not in MAIN_EXCLUDE]
    pos = {r.id: i for i, r in enumerate(regions)}
    rank = {}
    for b in main:
        owner = max(region_flows.items(), key=lambda kv: kv[1].get(b.flow, 0), default=(None, Counter()))
        if owner[0] and owner[1].get(b.flow, 0) > 0:
            rank[b.id] = pos[owner[0]]
    pairs = good = 0
    for a, b in combinations([b for b in main if b.id in rank], 2):
        if rank[a.id] == rank[b.id]:
            continue
        pairs += 1
        good += (rank[a.id] < rank[b.id]) == (a.order < b.order)
    res["reihenfolge"] = (good, pairs)

    # Überlappungen nach dem Einpassen
    boxes = expand_boxes(regions, lpage.height_px, decorations=deco)
    ov = 0
    for a, b in combinations([r for r in regions if r.is_text or r.kind == "tabelle"], 2):
        ba, bb = boxes[a.id], boxes[b.id]
        if min(ba[2], bb[2]) - max(ba[0], bb[0]) > 0 and min(ba[3], bb[3]) - max(ba[1], bb[1]) > 0:
            ov += 1
    res["ueberlappung"] = ov
    res["bereiche"] = [{"art": r.kind, "box": list(r.box)} for r in regions]
    return res


# --------------------------------------------------------------------------- Ablauf


def pct(t) -> str:
    a, b = t
    return f"{100 * a / b:5.1f} %" if b else "   –   "


def summarize(results: list[dict]) -> dict:
    def tot(key, idx=None):
        vals = [r[key] for r in results]
        if idx is None:
            return sum(vals)
        return (sum(v[0] for v in vals), sum(v[idx] for v in vals))

    return {
        "Blöcke erkannt": pct(tot("bloecke", 1)),
        "Art richtig": pct(tot("art", 1)),
        "Bereiche mit Vermischung": tot("mischung"),
        "Wörter wiedergefunden": pct(tot("woerter", 1)),
        "Wörter doppelt": tot("doppelt"),
        "Artefakte": tot("artefakte"),
        "Erfundene Strukturen": tot("erfunden"),
        "Tabellen gefunden": pct((sum(r["tabellen"][0] for r in results), sum(r["tabellen"][2] for r in results))),
        "Tabellenraster richtig": pct((sum(r["tabellen"][1] for r in results), sum(r["tabellen"][2] for r in results))),
        "Tabellenzellen richtig": pct(tot("zellen", 1)),
        "Gestaltung getroffen": pct(tot("gestaltung", 1)),
        "Reihenfolge richtig": pct(tot("reihenfolge", 1)),
        "Überlappungen": tot("ueberlappung"),
        "Sekunden je Seite": round(sum(r["sekunden"] for r in results) / max(1, len(results)), 1),
    }


def main() -> None:
    import cv2
    import numpy as np

    from quellenuebersetzer.config import Paths
    from quellenuebersetzer.pipeline.document import PageImage
    from quellenuebersetzer.pipeline.layout_reading import LayoutReader
    from quellenuebersetzer.profile import SourceKind
    from quellenuebersetzer.runtime.layout import LayoutDetector
    from quellenuebersetzer.runtime.tesseract import Tesseract

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only = None
    if "--seiten" in sys.argv:
        only = set(sys.argv[sys.argv.index("--seiten") + 1].split(","))
        args = [a for a in args if a != sys.argv[sys.argv.index("--seiten") + 1]]
    root = Path(args[0])
    out = Path(args[1]) if len(args) > 1 else None
    paths = Paths(root)
    det = LayoutDetector(paths)
    if not det.available:
        sys.exit("Seitenaufbau-Modell fehlt in der Datenwurzel.")
    results = []
    names = [n for n in sammlung.PAGE_TYPES if not only or n in only]
    for aged in (False, True):
        for name in names:
            page = sammlung.build(name, aged)
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                # Seitenbild direkt als aufbereiteten Hintergrund ablegen: gemessen wird die Layouterkennung,
                # nicht die Entzerrung (sonst verschöben sich die Rahmen des Lösungsblatts)
                bgr = cv2.cvtColor(np.asarray(page.image), cv2.COLOR_RGB2BGR)
                cv2.imencode(".png", bgr)[1].tofile(str(work / "hintergrund-0001.png"))
                reader = LayoutReader(SourceKind.DRUCK, Tesseract(paths), ["pol"], None, None, detector=det,
                                      workdir=work)
                t0 = time.perf_counter()
                lp = reader.detect_page(PageImage(1, work / "hintergrund-0001.png"))
                lp = reader.read_regions([lp])[0]
                res = measure_page(page, lp, time.perf_counter() - t0)
            results.append(res)
            print(f"{res['seite']:<26} Blöcke {pct(res['bloecke'])}  Misch {res['mischung']}  "
                  f"Wörter {pct(res['woerter'])}  Art. {res['artefakte']:>3}  Erf. {res['erfunden']}  "
                  f"Tab {res['tabellen'][1]}/{res['tabellen'][2]}  Zellen {pct(res['zellen'])}  "
                  f"Gest {pct(res['gestaltung'])}  Reihenf {pct(res['reihenfolge'])}  Überl {res['ueberlappung']}  "
                  f"{res['sekunden']} s", flush=True)
    summary = summarize(results)
    print("\nGesamt:")
    for k, v in summary.items():
        print(f"  {k:<26} {v}")
    if out:
        out.write_text(json.dumps({"gesamt": summary, "seiten": results}, ensure_ascii=False, indent=1),
                       encoding="utf-8")


if __name__ == "__main__":
    main()
