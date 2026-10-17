"""Hintergrundarbeiten (Systemprüfung, Installation, Verarbeitung) – die Oberfläche bleibt bedienbar."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from quellenuebersetzer.catalog import Catalog
from quellenuebersetzer.config import Paths, Settings
from quellenuebersetzer.hardware import detect
from quellenuebersetzer.install.downloader import Cancelled as DownloadCancelled
from quellenuebersetzer.install.installer import Installer, Progress, self_test
from quellenuebersetzer.install.manifest import Manifest
from quellenuebersetzer.pipeline.runner import Event, Job, JobOptions
from quellenuebersetzer.planner import Plan
from quellenuebersetzer.profile import Profile
from quellenuebersetzer.runtime.ollama import OllamaService


class DetectWorker(QThread):
    done = Signal(object)  # SystemInfo

    def __init__(self, paths: Paths):
        super().__init__()
        self.paths = paths

    def run(self) -> None:
        self.done.emit(detect(self.paths.root))


class StartupCheckWorker(QThread):
    """Programmstart: Hardware erfassen, Installation abgleichen, Plan für Fehlendes erstellen."""

    done = Signal(object, object)  # SystemInfo, Plan

    def __init__(self, paths: Paths, catalog: Catalog, profile: Profile, settings: Settings):
        super().__init__()
        self.paths, self.catalog, self.profile, self.settings = paths, catalog, profile, settings

    def run(self) -> None:
        from quellenuebersetzer.install.verify import reconcile
        from quellenuebersetzer.planner import build_plan

        info = detect(self.paths.root)
        manifest = Manifest(self.paths)
        reconcile(self.paths, self.catalog, manifest)
        plan = build_plan(self.profile, info, self.catalog, manifest, self.settings.mode, self.settings.tier or None)
        self.done.emit(info, plan)


class InstallWorker(QThread):
    progress = Signal(object)  # Progress
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, paths: Paths, catalog: Catalog, plan: Plan, service: OllamaService):
        super().__init__()
        self.paths = paths
        self.plan = plan
        self.service = service
        self.installer = Installer(paths, catalog, Manifest(paths), service)

    def cancel(self) -> None:
        self.installer.cancel()

    def run(self) -> None:
        try:
            self.installer.run(self.plan, self.progress.emit)
            self.progress.emit(Progress(len(self.plan.to_install), len(self.plan.to_install), "Funktionstest", status="läuft"))
            ok, msg = self_test(self.paths, self.service, self.plan.main_model)
            if ok:
                self.finished_ok.emit(msg)
            else:
                self.failed.emit(f"Der abschließende Funktionstest ist fehlgeschlagen: {msg}")
        except (DownloadCancelled, InterruptedError):
            self.failed.emit("Die Installation wurde abgebrochen. Beim nächsten Versuch wird an derselben Stelle fortgesetzt.")
        except Exception as exc:  # noqa: BLE001 – für den Nutzer verständlich melden
            self.failed.emit(f"Die Installation ist fehlgeschlagen: {exc}")


class ReviewBridge(QObject):
    """Übergibt die Umschrift zur Prüfung an die Oberfläche und wartet auf die Antwort."""

    request = Signal(object, str)

    def __init__(self):
        super().__init__()
        self._event = threading.Event()
        self._result: str | None = None

    def ask(self, doc, md: str) -> str | None:
        self._event.clear()
        self._result = None
        self.request.emit(doc, md)
        self._event.wait()
        return self._result

    def answer(self, result: str | None) -> None:
        self._result = result
        self._event.set()


class JobWorker(QThread):
    event = Signal(object)  # Event
    finished_all = Signal(object)  # list[FileResult]

    def __init__(self, paths: Paths, catalog: Catalog, settings: Settings, profile: Profile,
                 options: JobOptions, sources: list[Path], service: OllamaService, bridge: ReviewBridge):
        super().__init__()
        self.sources = sources
        self.bridge = bridge
        self.job = Job(paths, catalog, settings, profile, options, emit=self.event.emit,
                       review=bridge.ask if options.review else None, service=service)

    def cancel(self) -> None:
        self.job.cancel()
        self.bridge.answer(None)

    def run(self) -> None:
        try:
            results = self.job.run(self.sources)
        except Exception as exc:  # noqa: BLE001
            self.event.emit(Event("fehler", f"Die Verarbeitung konnte nicht starten: {exc}"))
            results = []
        self.finished_all.emit(results)


class BenchmarkWorker(QThread):
    """Leistungstest mit der eingebauten, erfundenen Beispielseite."""

    status = Signal(str)
    result = Signal(str, str)  # Bericht, Ergebnisordner

    def __init__(self, paths: Paths, catalog: Catalog, settings: Settings, service: OllamaService):
        super().__init__()
        self.paths = paths
        self.catalog = catalog
        self.settings = settings
        self.service = service

    def run(self) -> None:
        import time

        from rapidfuzz.distance import Levenshtein

        from quellenuebersetzer import beispiel
        from quellenuebersetzer.install.uninstall import documents_dir
        from quellenuebersetzer.profile import SourceKind

        out = documents_dir() / "Quellenübersetzer-Leistungstest"
        src = beispiel.make_page(self.paths.cache / "leistungstest" / "Beispielseite.png")
        profile = Profile([SourceKind.DRUCK], "pl", ["18jh"])
        times: dict[str, float] = {}
        t0 = time.time()
        last = {"phase": "Lesen", "t": t0}

        def emit(ev: Event) -> None:
            if ev.kind != "schritt":
                return
            self.status.emit(ev.message)
            if ev.message.startswith("Übersetzung"):
                phase = "Übersetzung"
            elif ev.message.startswith("Dokumente"):
                phase = "Ausgabe"
            else:
                phase = last["phase"]
            if phase != last["phase"]:
                times[last["phase"]] = time.time() - last["t"]
                last.update(phase=phase, t=time.time())

        job = Job(self.paths, self.catalog, self.settings, profile,
                  JobOptions(SourceKind.DRUCK, ["docx", "pdf"], review=False, output_root=out),
                  emit=emit, service=self.service)
        try:
            res = job.run([src])[0]
        except Exception as exc:  # noqa: BLE001
            self.result.emit(f"Der Leistungstest ist fehlgeschlagen: {exc}", "")
            return
        times[last["phase"]] = time.time() - last["t"]
        if not res.ok:
            self.result.emit(f"Der Leistungstest ist fehlgeschlagen: {res.message}", "")
            return
        md = next(p for p in res.outputs if p.name.endswith("Umschrift.md")).read_text(encoding="utf-8")
        cer = Levenshtein.normalized_distance(transcript_core(md), _core(beispiel.EXPECTED)) * 100
        lines = [
            f"Gesamtdauer für die Beispielseite: {time.time() - t0:.0f} Sekunden",
            *(f"   {k}: {v:.0f} s" for k, v in times.items()),
            f"Lesefehler (Zeichenfehlerrate, sauberer Druck): {cer:.1f} %",
            f"Markierte unsichere Stellen: {res.marks}",
            f"Modelle: {self.settings.main_model}, {self.settings.ocr_model}",
        ]
        # Zwei Übersetzungen gleichzeitig? Auf dieser Grafikkarte messen und das Ergebnis übernehmen
        from quellenuebersetzer.pipeline import tempo

        self.status.emit("Messung: zwei Übersetzungen gleichzeitig …")
        try:
            model = self.settings.draft_model or self.settings.main_model
            streams, seq, par = tempo.measure_streams(self.service, self.service.client, model)
            self.settings.translate_streams = streams
            self.settings.save(self.paths)
            lines.append(f"Zwei Übersetzungen gleichzeitig: nacheinander {seq:.0f} s, gleichzeitig {par:.0f} s → "
                         + ("wird genutzt" if streams == 2 else "lohnt sich auf dieser Grafikkarte nicht"))
        except Exception as exc:  # noqa: BLE001 – Messung ist nur eine Optimierung
            lines.append(f"Messung „zwei Übersetzungen gleichzeitig“ nicht möglich: {exc}")
        from quellenuebersetzer.pipeline.parallel import cpu_workers

        lines.append(f"Seiten gleichzeitig beim Lesen (Prozessorkerne): {cpu_workers()}")
        self.result.emit("\n".join(lines), str(out))


def transcript_core(md: str) -> str:
    """Nur den gelesenen Text einer Umschrift (ohne Kopf, Kästen, Verzeichnis, Markup) als Buchstabenfolge."""
    import re

    from quellenuebersetzer.pipeline import markup

    body = md.split("# Verzeichnis der markierten Stellen")[0]
    body = re.sub(r"^---.*?---", " ", body, flags=re.S)
    body = re.sub(r":::.*?:::", " ", body, flags=re.S)
    body = re.sub(r"<!--.*?-->|<[^>]+>", " ", body)
    return _core(markup.unescape_md(markup.strip_marks(body)))


def _core(text: str) -> str:
    """Nur Buchstaben und Ziffern vergleichen (Satzzeichen- und Leerraumunterschiede ignorieren)."""
    return "".join(ch for ch in text.lower() if ch.isalnum())
