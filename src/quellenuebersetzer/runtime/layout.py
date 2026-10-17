"""Seitenaufbau-Erkennung mit PP-DocLayoutV3 (Apache-2.0) über ONNX Runtime – lokal, ohne PyTorch.

Liefert für jede Seite Bereiche mit Art, Rahmen und Lesereihenfolge. Vor- und Nachverarbeitung
folgen der Referenzumsetzung (Größe 800×800, Werte 0–1, Sigmoid, Top-K, Zeiger-Stimmen für die Reihenfolge).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from quellenuebersetzer.config import Paths

INPUT_SIZE = 800
_RUN_LOCK = threading.Lock()
_SESSION_LOCK = threading.Lock()
MODEL_FILE = "pp_doclayoutv3.onnx"

# Modellklassen → Bereichsarten des Programms
ID2KIND = {
    0: "absatz",  # abstract
    1: "absatz",  # algorithm
    2: "randnotiz",  # aside_text
    3: "abbildung",  # chart
    4: "absatz",  # content (Inhaltsverzeichnis)
    5: "formel", 6: "titel", 7: "bildunterschrift", 8: "fusszeile", 9: "fusszeile", 10: "fussnote",
    11: "formel", 12: "kopfzeile", 13: "kopfzeile", 14: "abbildung", 15: "formel", 16: "seitenzahl",
    17: "ueberschrift", 18: "absatz", 19: "absatz", 20: "abbildung", 21: "tabelle", 22: "absatz",
    23: "absatz", 24: "fussnote",
}
TEXT_KINDS = {"absatz", "titel", "ueberschrift", "randnotiz", "bildunterschrift", "fussnote", "kopfzeile",
              "fusszeile", "seitenzahl"}


@dataclass
class Region:
    kind: str
    box: tuple[int, int, int, int]  # x0, y0, x1, y1 in Pixeln des Seitenbildes
    score: float
    order: int
    container: str = ""  # Kasten, in dem der Bereich liegt (eigener Textfluss)
    style: str = ""  # grobe Gestaltung (Hintergrund, Schriftfarbe) – nur Gleiches wird zusammengelegt

    @property
    def is_text(self) -> bool:
        return self.kind in TEXT_KINDS

    @property
    def area(self) -> int:
        return max(0, self.box[2] - self.box[0]) * max(0, self.box[3] - self.box[1])


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return (1.0 / (1.0 + np.exp(-np.clip(x.astype(np.float64), -60, 60)))).astype(np.float32)


def _order_ranks(order_logits: np.ndarray) -> np.ndarray:
    scores = _sigmoid(order_logits)
    votes = np.triu(scores, 1).sum(axis=0) + np.tril(1.0 - scores.T, -1).sum(axis=0)
    pointers = np.argsort(votes, kind="stable")
    ranks = np.empty_like(pointers)
    ranks[pointers] = np.arange(len(pointers))
    return ranks


def _iou(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


class LayoutDetector:
    def __init__(self, paths: Paths, threshold: float = 0.45):
        self.model = paths.runtime / "layout" / MODEL_FILE
        self.threshold = threshold
        self._session = None

    @property
    def available(self) -> bool:
        """Datei vorhanden und vollständig (Größe laut Katalog) – schnelle Prüfung ohne Laden."""
        if not self.model.is_file():
            return False
        try:
            from quellenuebersetzer.catalog import load_catalog

            spec = load_catalog().components["layout"].files[0]
            return self.model.stat().st_size == spec.size
        except (KeyError, OSError):
            return True

    def ready(self) -> bool:
        """Lässt sich das Modell tatsächlich laden? (beschädigte Datei → False statt Absturz)"""
        if not self.available:
            return False
        try:
            self._get_session()
            return True
        except Exception:  # noqa: BLE001 – jede Ladestörung führt zum Rückfall auf den Fließtext-Weg
            self._session = None
            return False

    def _get_session(self):
        with _SESSION_LOCK:
            return self._load_session()

    def _load_session(self):
        if self._session is None:
            import onnxruntime as ort

            so = ort.SessionOptions()
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            # bewusst auf dem Prozessor: die Grafikkarte bleibt frei für die Sprachmodelle
            self._session = ort.InferenceSession(str(self.model), so, providers=["CPUExecutionProvider"])
        return self._session

    def detect(self, image: np.ndarray) -> list[Region]:
        """``image``: Graustufen- oder RGB-Seitenbild. Ergebnis nach Lesereihenfolge sortiert."""
        regions = self.detect_raw(image)
        h, w = image.shape[:2]
        return reading_order(resolve_overlaps(merge_lines(regions)), w, h)

    def detect_raw(self, image: np.ndarray) -> list[Region]:
        """Rohbereiche des Modells (nur Doppelungen entfernt) – die Zusammenführung macht ``structure``.

        ``image`` sollte das Farbbild (RGB) sein: das Modell ist auf Farbseiten trainiert, farbige Kästen
        und Rubriken sind in Graustufen kaum noch zu unterscheiden.
        """
        rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB) if image.ndim == 2 else image
        h, w = rgb.shape[:2]
        x = cv2.resize(rgb, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_CUBIC)
        x = (x.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
        session = self._get_session()
        with _RUN_LOCK:  # das Modell nutzt bereits alle Kerne – parallele Seiten warten hier kurz aufeinander
            logits, boxes, order_logits = session.run(
                ["logits", "pred_boxes", "order_logits"], {"pixel_values": x}
            )
        return self._post(logits[0], boxes[0], order_logits[0], w, h)

    def _post(self, logits, pred_boxes, order_logits, w, h) -> list[Region]:
        n_q, n_c = logits.shape
        scores = _sigmoid(logits).reshape(-1)
        top = np.argpartition(-scores, n_q - 1)[:n_q]
        top = top[np.argsort(-scores[top], kind="stable")]
        keep = scores[top] >= self.threshold
        top = top[keep]
        ranks = _order_ranks(order_logits)
        regions: list[Region] = []
        for idx in top:
            q, c = int(idx // n_c), int(idx % n_c)
            cx, cy, bw, bh = pred_boxes[q]
            box = (
                int(max(0, (cx - bw / 2) * w)), int(max(0, (cy - bh / 2) * h)),
                int(min(w, (cx + bw / 2) * w)), int(min(h, (cy + bh / 2) * h)),
            )
            if box[2] - box[0] < 4 or box[3] - box[1] < 4:
                continue
            region = Region(ID2KIND.get(c, "absatz"), box, float(scores[idx]), int(ranks[q]))
            # dieselbe Abfrage kann mehrere Klassen tragen; doppelte Rahmen zusammenfassen
            if any(_iou(region.box, r.box) > 0.8 for r in regions):
                continue
            regions.append(region)
        return regions


# --------------------------------------------------------------------------- Nachbearbeitung

MARGIN_KINDS = {"kopfzeile", "fusszeile", "seitenzahl", "fussnote", "randnotiz"}


SOLID_KINDS = {"abbildung", "formel", "tabelle"}


def _inter(a, b) -> tuple[int, int, int, int] | None:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _area(b) -> int:
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _trim(box, obstacle):
    """Schneidet ``box`` an ``obstacle`` ab – an der Seite, die am wenigsten Fläche kostet."""
    x0, y0, x1, y1 = box
    ox0, oy0, ox1, oy1 = obstacle
    candidates = [
        (x0, y0, x1, oy0),  # oberhalb des Hindernisses behalten
        (x0, oy1, x1, y1),  # unterhalb
        (x0, y0, ox0, y1),  # links
        (ox1, y0, x1, y1),  # rechts
    ]
    valid = [c for c in candidates if c[2] - c[0] > 8 and c[3] - c[1] > 8]
    return max(valid, key=_area) if valid else None


def resolve_overlaps(regions: list[Region]) -> list[Region]:
    """Keine Überlappungen im Seitenaufbau: Text fließt um Abbildungen/Tabellen, nie liegt Text auf Text.

    - Text fast ganz in einer Abbildung (z. B. Beschriftung im Stich) gehört zum Bild und entfällt als Textbereich.
    - Teilweise Überlappung mit Abbildung/Tabelle: Textbereich wird am Rand des Hindernisses abgeschnitten.
    - Überlappende Textbereiche: der kleinere wird am größeren abgeschnitten (bzw. entfällt, wenn er darin liegt).
    """
    solids = [r for r in regions if r.kind in SOLID_KINDS]
    texts = sorted((r for r in regions if r.kind not in SOLID_KINDS), key=lambda r: -r.area)
    # Abbildungen/Tabellen untereinander: die kleinere in der größeren entfällt
    kept_solids: list[Region] = []
    for r in sorted(solids, key=lambda r: -r.area):
        if any((i := _inter(r.box, k.box)) and _area(i) > 0.7 * r.area for k in kept_solids):
            continue
        kept_solids.append(r)
    kept_texts: list[Region] = []
    for r in texts:
        box = r.box
        for obstacle in kept_solids + kept_texts:
            inter = _inter(box, obstacle.box)
            if not inter:
                continue
            if _area(inter) > 0.6 * _area(box):
                box = None  # liegt (fast) ganz im Hindernis
                break
            box = _trim(box, obstacle.box)
            if box is None:
                break
        if box is not None:
            r.box = box
            kept_texts.append(r)
    return kept_solids + kept_texts


def merge_lines(regions: list[Region], line_px: float | None = None) -> list[Region]:
    """Untereinander liegende Textzeilen derselben Spalte zu einem Absatz zusammenführen.

    ``line_px``: typische Zeilenhöhe der Seite – dann darf der Abstand höchstens etwa eine Zeile betragen
    (sonst richtet er sich nach der Bereichshöhe, und weit getrennte Absätze würden vereinigt).
    """
    out: list[Region] = []
    for r in sorted(regions, key=lambda r: (r.box[1], r.box[0])):
        merged = False
        if r.kind in ("absatz", "randnotiz"):
            for o in out:
                if o.kind != r.kind or o.container != r.container or o.style != r.style:
                    continue
                line_h = line_px or min(r.box[3] - r.box[1], o.box[3] - o.box[1])
                gap = r.box[1] - o.box[3]
                # gleiche Spalte = linker UND rechter Rand stimmen überein; breitere oder schmalere Elemente
                # (spaltenübergreifende Kästen, Überschriften) werden nie mit einer Spalte vereinigt.
                # Randspalten sind flatternd gesetzt: dort genügt der gemeinsame linke Rand.
                same_left = abs(r.box[0] - o.box[0]) < line_h * 1.5
                same_column = same_left and (r.kind == "randnotiz" or abs(r.box[2] - o.box[2]) < line_h * 1.5)
                if same_column and -line_h * 0.3 <= gap <= line_h * 0.6:
                    o.box = (min(o.box[0], r.box[0]), o.box[1], max(o.box[2], r.box[2]), max(o.box[3], r.box[3]))
                    o.order = min(o.order, r.order)
                    merged = True
                    break
        if not merged:
            out.append(Region(r.kind, r.box, r.score, r.order, r.container, r.style))
    return out


def _xy_cut(items: list[Region], depth: int = 0) -> list[Region]:
    """Rekursiver XY-Cut: zuerst an waagrechten Lücken (oben → unten), dann an senkrechten (links → rechts)."""
    if len(items) <= 1 or depth > 30:
        return items
    for axis in (1, 0):  # 1 = y (Zeilenbänder), 0 = x (Spalten)
        spans = sorted((r.box[axis], r.box[axis + 2]) for r in items)
        cuts, end = [], spans[0][1]
        for a, b in spans[1:]:
            if a > end:
                cuts.append((end + a) / 2)
            end = max(end, b)
        if cuts:
            groups: list[list[Region]] = [[] for _ in range(len(cuts) + 1)]
            for r in items:
                center = (r.box[axis] + r.box[axis + 2]) / 2
                groups[sum(center > c for c in cuts)].append(r)
            return [x for g in groups if g for x in _xy_cut(g, depth + 1)]
    return sorted(items, key=lambda r: r.order)


def reading_order(regions: list[Region], w: int, h: int) -> list[Region]:
    """Lesereihenfolge: Kopfzeile → Haupttext (XY-Cut) → Randnotizen → Fußnoten → Fußzeile/Seitenzahl."""
    head = [r for r in regions if r.kind == "kopfzeile"]
    side = [r for r in regions if r.kind == "randnotiz"]
    foot = [r for r in regions if r.kind == "fussnote"]
    tail = [r for r in regions if r.kind in ("fusszeile", "seitenzahl")]
    main = [r for r in regions if r.kind not in MARGIN_KINDS]
    ordered = (sorted(head, key=lambda r: r.box[1]) + _xy_cut(main) + sorted(side, key=lambda r: r.box[1])
               + sorted(foot, key=lambda r: r.box[1]) + sorted(tail, key=lambda r: r.box[1]))
    for i, r in enumerate(ordered):
        r.order = i
    return ordered
