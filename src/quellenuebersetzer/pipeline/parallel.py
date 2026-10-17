"""Seitenweise Arbeit auf mehrere Prozessorkerne verteilen.

Threads genügen: OpenCV, ONNX Runtime und die Tesseract-Aufrufe (eigene Prozesse) geben die Python-Sperre frei.
Ergebnisse kommen in der Reihenfolge der Eingabe; es werden nur wenige Seiten im Voraus bearbeitet,
damit der Speicherbedarf begrenzt bleibt und ein Abbruch schnell greift.
"""

from __future__ import annotations

import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Iterator, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def cpu_workers(limit: int = 6) -> int:
    """Anzahl paralleler Seiten: etwa die Hälfte der logischen Kerne (Rest für Oberfläche und Modell-Laufzeit)."""
    return max(1, min(limit, (os.cpu_count() or 2) // 2))


def pmap(fn: Callable[[T], R], items: Iterable[T], workers: int) -> Iterator[R]:
    """Wie ``map``, aber mit ``workers`` Threads; höchstens ``2 × workers`` Aufgaben gleichzeitig unterwegs."""
    if workers <= 1:
        for item in items:
            yield fn(item)
        return
    ex = ThreadPoolExecutor(max_workers=workers)
    try:
        it = iter(items)
        pending = deque()
        for item in it:
            pending.append(ex.submit(fn, item))
            if len(pending) >= 2 * workers:
                break
        while pending:
            result = pending.popleft().result()
            nxt = next(it, _END)
            if nxt is not _END:
                pending.append(ex.submit(fn, nxt))
            yield result
    finally:
        ex.shutdown(wait=True, cancel_futures=True)


_END = object()
