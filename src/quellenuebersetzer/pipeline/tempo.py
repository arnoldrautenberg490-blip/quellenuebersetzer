"""Messung: Schafft die Grafikkarte zwei Übersetzungsanfragen gleichzeitig schneller als nacheinander?

Zwei gleichzeitige Anfragen brauchen doppelten Zwischenspeicher. Passt das nicht mehr in den Grafikspeicher,
lagert die Laufzeit aus und es wird *langsamer* – deshalb wird gemessen statt geraten: einmal pro Rechner
(Ergebnis in den Einstellungen), automatisch beim ersten größeren Buch oder im Leistungstest.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from quellenuebersetzer.pipeline.readers import MAIN_CTX
from quellenuebersetzer.runtime.ollama import OllamaClient, OllamaService

# Erfundene Absätze ähnlicher Länge (verschieden, damit kein Zwischenspeicher das Ergebnis verfälscht)
SAMPLES = [
    "Rada miejska postanowiła, że każdy kupiec przybywający na jarmark zapłaci od wozu dwa grosze, "
    "a od beczki soli jeden grosz, zaś pieniądze te mają być obrócone na naprawę mostu i bramy miejskiej.",
    "Starosta grodowy nakazał, aby młynarze z okolicznych wsi stawili się w zamku w dzień świętego Marcina "
    "i złożyli przysięgę, że będą mleć zboże uczciwie i nie będą pobierać więcej niż dwunastą miarę.",
    "Proboszcz parafii skarżył się przed sądem, że dziedzic folwarku od trzech lat nie oddaje dziesięciny "
    "snopowej, a kmiecie z tej wsi odmawiają mesznego, tłumacząc się nieurodzajem i ciężką pańszczyzną.",
    "Wójt wraz z ławnikami spisał w księdze miejskiej, że czeladnik szewski zobowiązał się służyć mistrzowi "
    "przez trzy lata, a mistrz ma go żywić, odziewać i nauczyć rzemiosła według zwyczaju cechowego.",
    "Wojewoda zwołał szlachtę na sejmik do kościoła farnego, gdzie odczytano listy królewskie o poborze "
    "i postanowiono wybrać posłów, którzy mieli bronić praw ziemi przed możnymi panami i duchowieństwem.",
]
GAIN_NEEDED = 0.8  # gleichzeitig muss höchstens 80 % der Zeit von nacheinander brauchen


def _ask(client: OllamaClient, model: str, text: str) -> None:
    client.chat(model, [{"role": "user", "content": f"Translate into German:\n{text}"}],
                num_ctx=MAIN_CTX, num_predict=160, temperature=0.0, think=None)


def _restart(service: OllamaService, parallel: int) -> None:
    service.tuning = {**service.tuning, "OLLAMA_NUM_PARALLEL": str(parallel)}
    service.stop()
    service.start(offline=True)


def measure_streams(service: OllamaService, client: OllamaClient, model: str) -> tuple[int, float, float]:
    """→ (empfohlene Zahl gleichzeitiger Übersetzungen 1|2, Sekunden nacheinander, Sekunden gleichzeitig).

    Die Laufzeit läuft danach mit der empfohlenen Einstellung.
    """
    _restart(service, 2)
    try:
        _ask(client, model, SAMPLES[0])  # Modell laden
        t0 = time.perf_counter()
        _ask(client, model, SAMPLES[1])
        _ask(client, model, SAMPLES[2])
        sequential = time.perf_counter() - t0
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(lambda s: _ask(client, model, s), SAMPLES[3:5]))
        parallel = time.perf_counter() - t0
    except Exception:
        _restart(service, 1)
        raise
    streams = 2 if parallel < GAIN_NEEDED * sequential else 1
    if streams == 1:
        _restart(service, 1)
    return streams, sequential, parallel
