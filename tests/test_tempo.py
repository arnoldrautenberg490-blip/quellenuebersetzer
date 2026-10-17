"""Beschleunigung: mehrere Kerne, zwei Übersetzungsströme, überlapptes Lesen und Übersetzen."""

import json
import re
import threading
import time

import pytest

from quellenuebersetzer.pipeline.layout_doc import LayoutDocument, LPage, LRegion
from quellenuebersetzer.pipeline.layout_translate import LayoutTranslator
from quellenuebersetzer.pipeline.parallel import pmap
from quellenuebersetzer.pipeline.translate import Translator
from quellenuebersetzer.runtime.ollama import ChatResult


class EchoClient:
    """„Übersetzt“ deterministisch (unabhängig von der Reihenfolge der Anfragen) und zählt Gleichzeitigkeit."""

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.stats = {}

    def chat(self, model, messages, **kw):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        text = messages[-1]["content"].rsplit(":\n", 1)[-1]
        de = re.sub(r"Tekst strony", "Text der Seite", text)
        return ChatResult(json.dumps({"translation": de, "readings": [], "terms": []}, ensure_ascii=False), [])


def _doc(n_pages: int, per_page: int = 2) -> LayoutDocument:
    pages = []
    for n in range(1, n_pages + 1):
        regs = [LRegion(f"s{n}b{k}", "ueberschrift" if k == 1 else "absatz", (0, k * 10, 10, k * 10 + 5), k,
                        f"Tekst strony {n}, część {k}.") for k in range(1, per_page + 1)]
        pages.append(LPage(n, 100, 100, 300, "bg", regs, read=True))
    return LayoutDocument("q", "Q", "druck", ".", pages)


def test_pmap_keeps_order_uses_threads_and_reports_errors():
    seen = set()

    def work(x):
        seen.add(threading.get_ident())
        time.sleep(0.01)
        return x * 2

    assert list(pmap(work, range(20), 4)) == [x * 2 for x in range(20)]
    assert len(seen) > 1
    with pytest.raises(ValueError):
        list(pmap(lambda x: (_ for _ in ()).throw(ValueError("x")) if x == 3 else x, range(6), 3))


def test_two_streams_translate_everything_concurrently_and_in_page_order():
    doc = _doc(6)
    client = EchoClient()
    done = []
    lt = LayoutTranslator(doc, Translator(client, "m", "Polish", "18. Jh.", (1700, 1799)),
                          on_page_done=lambda p: done.append(p.number), streams=2)
    lt.translate_pages(doc.pages)
    assert client.max_active == 2  # wirklich gleichzeitig
    assert all(r.target_md.startswith("Text der Seite") for p in doc.pages for r in p.regions)
    assert done == [1, 2, 3, 4, 5, 6]


def test_blockwise_translation_waits_for_unread_pages():
    """Überlappung: Seiten werden erst gemeldet, wenn sie gelesen und übersetzt sind – in Reihenfolge."""
    doc = _doc(4)
    for p in doc.pages[2:]:
        p.read = False
        for r in p.regions:
            r.source_md = ""  # noch nicht gelesen
    done = []
    lt = LayoutTranslator(doc, Translator(EchoClient(0), "m", "Polish", "18. Jh.", (1700, 1799)),
                          on_page_done=lambda p: done.append(p.number))
    lt.translate_pages(doc.pages[:2])
    assert done == [1, 2]
    for p in doc.pages[2:]:  # nächster Block gelesen
        p.read = True
        for k, r in enumerate(p.regions, start=1):
            r.source_md = f"Tekst strony {p.number}, część {k}."
    lt.translate_pages(doc.pages[2:])
    assert done == [1, 2, 3, 4]


def test_stream_measurement_picks_two_only_when_really_faster():
    from quellenuebersetzer.pipeline import tempo

    class Service:
        def __init__(self):
            self.tuning = {"OLLAMA_NUM_PARALLEL": "1"}

        def stop(self):
            pass

        def start(self, offline=True):
            pass

    class Gpu:  # serielle Grafikkarte: gleichzeitige Anfragen warten aufeinander
        def __init__(self, serial):
            self.lock = threading.Lock() if serial else None

        def chat(self, *a, **kw):
            if self.lock:
                with self.lock:
                    time.sleep(0.1)
            else:
                time.sleep(0.1)

    svc = Service()
    assert tempo.measure_streams(svc, Gpu(serial=True), "m")[0] == 1
    assert svc.tuning["OLLAMA_NUM_PARALLEL"] == "1"
    assert tempo.measure_streams(svc, Gpu(serial=False), "m")[0] == 2
    assert svc.tuning["OLLAMA_NUM_PARALLEL"] == "2"
