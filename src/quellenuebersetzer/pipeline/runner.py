"""Ablaufsteuerung: verarbeitet eine Datei oder einen ganzen Ordner von der Quelle bis zum fertigen Dokument."""

from __future__ import annotations

import hashlib
import queue
import shutil
import threading
import time
import traceback
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from quellenuebersetzer import netguard
from quellenuebersetzer.catalog import Catalog
from quellenuebersetzer.config import Paths, Settings
from quellenuebersetzer.pipeline import ingest as ingest_mod
from quellenuebersetzer.pipeline import layout_docx, layout_render, markup
from quellenuebersetzer.pipeline.document import Block, SourceDocument
from quellenuebersetzer.pipeline.export import FORMATS, DocMeta, Exporter, ExportError, build_document
from quellenuebersetzer.pipeline.layout_doc import LayoutDocument
from quellenuebersetzer.pipeline.layout_reading import LayoutReader
from quellenuebersetzer.pipeline import pruefbericht, tempo
from quellenuebersetzer.pipeline.layout_translate import LayoutTranslator, needs_refinement
from quellenuebersetzer.pipeline.parallel import cpu_workers, pmap
from quellenuebersetzer.pipeline.pagegeom import common_size
from quellenuebersetzer.pipeline.lexicon import Glossary, Lexicon
from quellenuebersetzer.pipeline.readers import GlmOcr, VisionJudge
from quellenuebersetzer.pipeline.reading import PageReader
from quellenuebersetzer.pipeline.translate import Translator
from quellenuebersetzer.profile import PERIOD_BY_KEY, Profile, SourceKind
from quellenuebersetzer.runtime.layout import LayoutDetector
from quellenuebersetzer.runtime.ollama import OllamaClient, OllamaService
from quellenuebersetzer.runtime.tesseract import Tesseract

PAGE_BATCH = 12  # Seiten je Durchgang (begrenzt den Speicherbedarf bei großen Bänden)
OVERLAP_BLOCK = 20  # Seiten je Block beim überlappten Lesen und Übersetzen
STREAM_TEST_PAGES = 20  # ab dieser Seitenzahl wird einmalig gemessen, ob zwei Übersetzungen gleichzeitig lohnen


@dataclass
class Event:
    kind: str  # datei | schritt | fortschritt | hinweis | fertig | fehler | alles_fertig
    message: str = ""
    file: str = ""
    index: int = 0
    total: int = 0
    fraction: float = 0.0
    outputs: list[Path] = field(default_factory=list)


LAYOUT_MODES = {
    "faksimile": "Seitengetreu – Faksimile (Originalseite als Hintergrund)",
    "neusatz": "Seitengetreu – Neusatz (gleiche Anordnung, weiße Seite)",
    "fliesstext": "Fließtext (ohne Seitenaufbau)",
}


@dataclass
class JobOptions:
    kind: SourceKind
    formats: list[str]
    review: bool
    output_root: Path | None = None  # None → neben der Quelle
    layout: str = "faksimile"  # faksimile | neusatz | fliesstext


@dataclass
class FileResult:
    source: Path
    ok: bool
    outputs: list[Path] = field(default_factory=list)
    marks: int = 0
    words: int = 0
    message: str = ""


ReviewFn = Callable[[SourceDocument, str], "str | None"]  # gibt bestätigtes Markdown zurück oder None (überspringen)
EmitFn = Callable[[Event], None]


class Cancelled(Exception):
    pass


@contextmanager
def keep_awake():
    """Verhindert während der Verarbeitung den Ruhezustand (Bildschirm darf ausgehen) – z. B. Bücher über Nacht."""
    if sys.platform != "win32":
        yield
        return
    import ctypes

    es_continuous, es_system_required = 0x80000000, 0x00000001
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)
        yield
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous)


def cleanup_stale_books(paths: Paths, days: int = 30) -> None:
    """Nicht abgeschlossene Zwischenstände nach einer Frist entfernen (Datenschutz)."""
    base = paths.cache / "buecher"
    if not base.exists():
        return
    limit = time.time() - days * 86400
    for d in base.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < limit:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 2:
        return "1 Minute"
    if minutes < 90:
        return f"{minutes} Minuten"
    return f"{minutes / 60:.1f} Stunden".replace(".", ",")


REFINE_FACTOR = 3.0  # vorsichtige Annahme: großes Modell braucht je Abschnitt etwa dreimal so lange


class Restzeit:
    """Restzeit aus dem gemessenen Durchsatz DIESES Laufs: Wanduhr (Lesen und Übersetzen zusammen) je
    übersetztem Bereich mal noch offene Bereiche des ganzen Buchs. Unabhängig vom Fortschrittsbalken –
    der schnelle Seitenaufbau und beim Fortsetzen schon erledigte Seiten verfälschen die Schätzung nicht."""

    MIN_DONE = 10
    MIN_SECONDS = 60.0

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.start: float | None = None
        self.done0 = 0

    def begin(self, done: int) -> None:
        self.start, self.done0 = self.clock(), done

    def estimate(self, done: int, remaining: int, extra_units: float = 0.0) -> float | None:
        """``extra_units``: zusätzliche Arbeit in „Bereichen zum gemessenen Tempo“ (z. B. Überarbeitung)."""
        if self.start is None:
            return None
        n, elapsed = done - self.done0, self.clock() - self.start
        if n < self.MIN_DONE or elapsed < self.MIN_SECONDS:
            return None
        return elapsed / n * (max(0, remaining) + max(0.0, extra_units))


def _region_counts(pages) -> tuple[int, int]:
    """(übersetzte, noch offene) Bereiche; ungelesene Seiten zählen mit allen übersetzbaren Bereichen."""
    done = remaining = 0
    for p in pages:
        for r in p.regions:
            if not r.translatable:
                continue
            if r.target_md:
                done += 1
            elif r.source_md.strip() or not p.read:
                remaining += 1
    return done, remaining


def period_label(profile: Profile) -> str:
    labels = [PERIOD_BY_KEY[k].label for k in profile.periods if k in PERIOD_BY_KEY]
    return ", ".join(labels) if labels else "unbekannt"


def output_dir_for(source: Path, options: JobOptions, paths: Paths) -> Path:
    if options.output_root:
        base = options.output_root
    else:
        base = source.parent / ingest_mod.OUTPUT_DIR_NAME
    target = base / source.stem
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".schreibtest"
        probe.write_bytes(b"")
        probe.unlink()
        return target
    except OSError:
        from quellenuebersetzer.install.uninstall import documents_dir

        fallback = documents_dir() / "Quellenübersetzer" / source.stem
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


class Job:
    def __init__(
        self,
        paths: Paths,
        catalog: Catalog,
        settings: Settings,
        profile: Profile,
        options: JobOptions,
        emit: EmitFn,
        review: ReviewFn | None = None,
        client: OllamaClient | None = None,
        service: OllamaService | None = None,
    ):
        self.paths = paths
        self.catalog = catalog
        self.settings = settings
        self.profile = profile
        self.options = options
        self.emit = emit
        self.review = review
        self.service = service
        self.client = client or OllamaClient()
        self.cancelled = False
        self.lang = catalog.languages[profile.language]
        self.period = period_label(profile)

    def cancel(self) -> None:
        self.cancelled = True

    def _check(self) -> None:
        if self.cancelled:
            raise Cancelled()

    # ------------------------------------------------------------------ Bausteine
    def _readers(self) -> tuple[Tesseract | None, GlmOcr | None, VisionJudge | None]:
        tess = Tesseract(self.paths)
        glm = GlmOcr(self.client, self.settings.ocr_model) if self.settings.ocr_model else None
        judge = VisionJudge(self.client, self.settings.main_model, self.lang.name_en) if self.settings.main_model else None
        return (tess if tess.available else None), glm, judge

    def _lexicon(self) -> Lexicon:
        files = [d.path(self.paths.dicts) for d in self.lang.dictionaries if set(d.periods) & set(self.profile.periods)]
        return Lexicon(files)

    # ------------------------------------------------------------------ Ablauf
    def run(self, sources: list[Path]) -> list[FileResult]:
        results: list[FileResult] = []
        with netguard.offline(), keep_awake():
            if self.service is not None:
                self.emit(Event("schritt", "Lokale Modell-Laufzeit wird gestartet"))
                self.service.start(offline=True)
            lexicon = self._lexicon()
            glossary = Glossary(self.paths.glossary_file)
            try:
                for i, src in enumerate(sources, start=1):
                    if self.cancelled:
                        break
                    self.emit(Event("datei", src.name, src.name, i, len(sources)))
                    try:
                        res = self._process(src, lexicon, glossary, i, len(sources))
                    except Cancelled:
                        results.append(FileResult(src, False, message="abgebrochen"))
                        break
                    except Exception as exc:  # noqa: BLE001 – Fehler einer Datei darf den Stapel nicht beenden
                        (self.paths.logs).mkdir(parents=True, exist_ok=True)
                        with (self.paths.logs / "fehler.log").open("a", encoding="utf-8") as fh:
                            fh.write(f"{time.ctime()} {type(exc).__name__}\n{_safe_traceback(exc)}\n")
                        res = FileResult(src, False, message=_friendly_error(exc))
                        self.emit(Event("fehler", res.message, src.name, i, len(sources)))
                    results.append(res)
            finally:
                lexicon.close()
                glossary.close()
        self.emit(Event("alles_fertig", f"{sum(r.ok for r in results)} von {len(sources)} Dateien fertig"))
        return results

    def _book_dir(self, src: Path) -> Path:
        """Fester Arbeitsordner je Quelle und Einstellungen – erlaubt das Fortsetzen nach einer Unterbrechung."""
        try:
            stat = src.stat()
            stamp = f"{stat.st_mtime_ns}-{stat.st_size}"
        except OSError:
            stamp = "0"
        key = "|".join([str(src.resolve()), stamp, self.options.layout, self.options.kind.value,
                        self.settings.main_model, self.settings.ocr_model])
        return self.paths.cache / "buecher" / hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

    def _process(self, src: Path, lexicon: Lexicon, glossary: Glossary, index: int, total: int) -> FileResult:
        # Fester Arbeitsordner (Fortsetzen möglich) für alles, was gescannt sein kann; Word-Dateien brauchen keinen.
        book = src.suffix.lower() != ".docx"
        job_cache = self._book_dir(src) if book else self.paths.cache / "jobs" / uuid.uuid4().hex[:12]
        job_cache.mkdir(parents=True, exist_ok=True)
        keep = False

        started = time.time()
        self.phase_times = {}

        def step(msg: str, frac: float = 0.0, rest: float | None | bool = None) -> None:
            """``rest``: eigene Restzeit in Sekunden, ``False`` = keine anzeigen, ``None`` = aus dem Balken."""
            self._check()
            elapsed = time.time() - started
            if rest is None and 0.03 < frac < 0.98 and elapsed > 20:
                rest = elapsed * (1 - frac) / frac
            if rest:
                msg += f" · noch etwa {_duration(rest)}"
            self.emit(Event("schritt", msg, src.name, index, total, frac))

        try:
            step("Datei wird eingelesen")
            layout = self.options.layout != "fliesstext"
            if layout and src.suffix.lower() == ".docx":
                return self._process_docx_inplace(src, lexicon, glossary, step, index, total)
            ing = ingest_mod.ingest(src, job_cache)
            for note in ing.notes:
                self.emit(Event("hinweis", note, src.name, index, total))
            if layout and src.suffix.lower() == ".pdf" and ing.origin != "scan":
                # seitengetreu: auch digitale PDF-Seiten werden als Bild gelesen (sauberer Text, kaum Fehler)
                ing = ingest_mod._scan(ingest_mod.render_pdf(src, job_cache), job_cache)
            kind = self.options.kind if ing.pages else SourceKind.DRUCK
            # Seitenaufbau zuerst – bei jedem Scan, auch für Fließtext: genauere Texterkennung je Bereich,
            # richtige Lesereihenfolge, Abbildungen werden nicht „gelesen“.
            detector_ready = bool(ing.pages) and LayoutDetector(self.paths).ready()
            if (layout or ing.origin == "scan") and ing.pages and detector_ready:
                keep = True  # bei Abbruch bleibt der Zwischenstand für das Fortsetzen erhalten
                result = self._process_layout(src, ing, kind, lexicon, glossary, step, job_cache, index, total)
                keep = not result.ok and result.message not in ("Übersprungen",
                                                                "In der Datei wurde kein Text gefunden.")
                return result
            if layout and ing.pages:
                self.emit(Event("hinweis", "Die Seitenaufbau-Erkennung fehlt oder ist beschädigt – diese Datei wird als "
                                           "Fließtext ausgegeben. Beim nächsten Programmstart wird sie repariert.",
                                src.name, index, total))
            doc = SourceDocument(src, src.stem, ing.origin, kind.value, list(ing.blocks), list(ing.pages))

            if ing.pages:
                tess, glm, judge = self._readers()
                reader = PageReader(
                    kind, tess, self._tess_langs(kind), glm, judge, self.period,
                    status=lambda m: step(m),
                )
                pages = ing.pages
                for start in range(0, len(pages), PAGE_BATCH):
                    batch = pages[start:start + PAGE_BATCH]
                    step(f"Seiten {batch[0].number}–{batch[-1].number} von {len(pages)} werden gelesen",
                         start / max(1, len(pages)) * 0.5)
                    for page, res in zip(batch, reader.read_pages(batch)):
                        doc.blocks.extend(res.blocks)
                        doc.stats["marks"] = doc.stats.get("marks", 0) + res.marks
                        doc.stats["words"] = doc.stats.get("words", 0) + res.words
                        for note in res.notes:
                            self.emit(Event("hinweis", f"Seite {page.number}: {note}", src.name, index, total))
                doc.blocks.sort(key=lambda b: b.page)  # digitale Seiten und Scanseiten (gemischte PDFs)
                doc.readers = [r for r in (tess and "Tesseract", glm and glm.model, judge and judge.model) if r]

            original_md = doc.to_markdown()
            if not original_md.strip():
                return FileResult(src, False, message="In der Datei wurde kein Text gefunden.")

            if self.review and self.options.review:
                step("Warte auf Prüfung der Umschrift")
                reviewed = self.review(doc, original_md)
                if reviewed is None:
                    return FileResult(src, False, message="Übersprungen")
                if reviewed != original_md:
                    self._save_correction(doc, reviewed)
                original_md = reviewed

            translator = self._translator(lexicon, glossary, step)
            step("Übersetzung beginnt", 0.5)
            german_md = translator.translate_markdown(
                original_md,
                progress=lambda i, n: step(f"Übersetzung: Abschnitt {i} von {n}", 0.5 + 0.45 * i / max(1, n)),
            )
            if translator.stats.fallbacks:
                self.emit(Event("hinweis", f"{translator.stats.fallbacks} Abschnitt(e) mit vereinfachter Übersetzung – im Dokument gekennzeichnet.", src.name, index, total))

            step("Dokumente werden erzeugt", 0.95)
            outputs = self._write_outputs(src, doc, original_md, german_md)
            self.emit(Event("fertig", "Fertig", src.name, index, total, 1.0, outputs))
            return FileResult(src, True, outputs, doc.stats.get("marks", 0), doc.stats.get("words", 0))
        finally:
            self._log_times(src, time.time() - started)
            if not keep:
                shutil.rmtree(job_cache, ignore_errors=True)  # Seitenbilder sofort entfernen (Datenschutz)

    # ------------------------------------------------------------------ Seitengetreu
    def _translator(self, lexicon: Lexicon, glossary: Glossary, step, model: str = "") -> Translator:
        return Translator(
            self.client, model or self.settings.main_model, self.lang.name_en, self.period, self.profile.year_range(),
            lexicon=lexicon if lexicon.available else None, glossary=glossary, periods=self.profile.periods,
            extra_hints=self.lang.prompt.get("historische_hinweise", []), status=lambda m: step(m),
        )

    def _translation_streams(self, model: str, n_pages: int, step) -> int:
        """Zwei Übersetzungen gleichzeitig nur, wenn auf diesem Rechner gemessen schneller (einmalig, ohne Klick)."""
        streams = self.settings.translate_streams
        if streams == 0 and self.service is not None and n_pages >= STREAM_TEST_PAGES:
            step("Einmalige Messung: Lohnen zwei Übersetzungen gleichzeitig auf dieser Grafikkarte?")
            try:
                streams, seq, par = tempo.measure_streams(self.service, self.client, model)
            except Exception as exc:  # noqa: BLE001 – Messung ist nur eine Optimierung
                self._log_error(exc)
                return 1
            self.settings.translate_streams = streams
            self.settings.save(self.paths)
            how = "zwei Übersetzungen gleichzeitig" if streams == 2 else "eine Übersetzung nach der anderen"
            self.emit(Event("hinweis", f"Messung abgeschlossen (nacheinander {seq:.0f} s, gleichzeitig {par:.0f} s): "
                                       f"künftig {how}."))
        return max(1, streams)

    def _process_layout(self, src: Path, ing, kind: SourceKind, lexicon: Lexicon, glossary: Glossary, step,
                        job_cache: Path, index: int, total: int) -> FileResult:
        tess, glm, judge = self._readers()
        reader = LayoutReader(kind, tess, self._tess_langs(kind), glm, judge, self.period,
                              status=lambda m: step(m), detector=LayoutDetector(self.paths), workdir=job_cache,
                              workers=cpu_workers(), extra_scripts=self.lang.tesseract.get("nachlesen", []))
        state = job_cache / "stand.json"
        from quellenuebersetzer import __version__, build_stamp

        fassung = f"{__version__} ({build_stamp()})"
        ldoc = LayoutDocument(str(src), src.stem, kind.value, str(job_cache), programm=fassung)
        if state.exists():
            try:
                ldoc = LayoutDocument.load(state)
                ldoc.workdir = str(job_cache)
                if ldoc.programm != fassung:
                    # Zwischenstand einer anderen Programmfassung: nicht übernehmen (sonst bliebe z. B. ein mit
                    # der alten Fassung erkannter Seitenaufbau bestehen)
                    raise ValueError("andere Programmfassung")
                done_regions = sum(1 for p in ldoc.pages for r in p.regions if r.target_md)
                read_pages = sum(1 for p in ldoc.pages if p.read)
                self.emit(Event("hinweis", f"Unterbrochene Verarbeitung wird fortgesetzt: Aufbau von {len(ldoc.pages)} "
                                           f"von {len(ing.pages)} Seiten erkannt, {read_pages} Seiten gelesen, "
                                           f"{done_regions} Bereiche übersetzt.", src.name, index, total))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                if "Programmfassung" in str(exc):
                    self.emit(Event("hinweis", "Das Programm wurde aktualisiert – der gespeicherte Zwischenstand "
                                               "wird verworfen und der Seitenaufbau neu erkannt.", src.name, index, total))
                # nur die Dateien des alten Seitenaufbaus entfernen – die eingelesenen Seitenbilder bleiben
                for pattern in ("stand.json", "hintergrund-*.png", "abbildung-*.png", "kasten-*.png",
                                "faksimile-*.jpg", "satz-*", "vorschau-*"):
                    for old in job_cache.glob(pattern):
                        old.unlink(missing_ok=True)
                ldoc = LayoutDocument(str(src), src.stem, kind.value, str(job_cache), programm=fassung)
        preview_dir = self.paths.cache / "vorschau"
        shutil.rmtree(preview_dir, ignore_errors=True)
        n_total = len(ing.pages)

        # ---- Phase 1: Seitenaufbau des GANZEN Dokuments (schnell; danach steht das Ziellayout fest)
        t_layout = time.time()
        known = {p.number for p in ldoc.pages}
        for p in ldoc.pages:  # beim Fortsetzen: bekannte Seiten sofort zeigen
            self._preview_layout(ldoc, p, preview_dir, src, index, n_total)
        todo = [p for p in ing.pages if p.number not in known]
        # 1a: alle Seiten entzerren (Seite finden, Perspektive, Schräglage, Wölbung) – mehrere Seiten gleichzeitig …
        workers = reader.workers
        sizes = []
        for i, size in enumerate(pmap(reader.prepare_page, todo, workers), start=1):
            self._check()
            step(f"Phase 1 von 3 – Seiten entzerren: {i} von {len(todo)}", 0.04 * i / max(1, len(todo)), False)
            sizes.append(size)
        # … dann ein gemeinsames Normalformat für das ganze Dokument festlegen
        if ldoc.target_size is None and not known:
            target = common_size(sizes)
            ldoc.target_size = list(target) if target else None
        target_size = tuple(ldoc.target_size) if ldoc.target_size else None
        reports = reader.geometry_reports.values()
        fixed = sum(1 for r in reports if r.cropped or abs(r.deskew_deg) >= 0.2 or r.dewarp_px >= 3)
        if fixed:
            worst = max((r.dewarp_px for r in reports), default=0)
            self.emit(Event("hinweis", f"{fixed} Seite(n) entzerrt (Rand, Schräglage, Wölbung bis {worst:.0f} Pixel)"
                                       + (f"; einheitliches Seitenformat {target_size[0]}×{target_size[1]} Pixel."
                                          if target_size else "."), src.name, index, total))
        # 1b: Seitenaufbau auf den aufbereiteten Seiten erkennen (mehrere Seiten gleichzeitig)
        for i, lp in enumerate(pmap(lambda pg: reader.detect_page(pg, target_size), todo, workers), start=1):
            self._check()
            step(f"Phase 1 von 3 – Seitenaufbau: Seite {lp.name} ({len(known) + i} von {n_total})",
                 0.04 + 0.04 * (len(known) + i) / max(1, n_total), False)
            ldoc.pages.append(lp)
            ldoc.pages.sort(key=lambda x: x.number)
            if i % 5 == 0 or i == len(todo):
                ldoc.save(state)
            self._preview_layout(ldoc, lp, preview_dir, src, index, n_total)
        self.phase_times["aufbau"] = time.time() - t_layout
        self.phase_times["kerne"] = workers
        self.emit(Event("hinweis", f"Seitenaufbau erkannt: {layout_render.layout_summary(ldoc)}.", src.name, index, total))

        # ---- Übersetzer vorbereiten
        staged = (self.settings.mode == "gruendlich" and bool(self.settings.draft_model)
                  and self.settings.draft_model != self.settings.main_model)
        if staged:
            # gestaffelt gründlich: schnelles Modell für alles, großes Modell nur für schwierige Abschnitte
            translator = self._translator(lexicon, glossary, step, self.settings.draft_model)
            refiner = self._translator(lexicon, glossary, step, self.settings.main_model)
        else:
            translator, refiner = self._translator(lexicon, glossary, step), None

        typst = self.paths.runtime / "typst" / "typst.exe"
        n_pages = len(ldoc.pages)
        preview_failed = []
        save_lock = threading.Lock()

        def save() -> None:
            with save_lock:
                ldoc.save(state)

        def page_done(page) -> None:
            """Fertig übersetzte Seite sofort als Vorschau anzeigen (blätterbar im Hauptfenster)."""
            if not typst.exists() or preview_failed:
                return
            try:
                original, translated = layout_render.render_preview(
                    ldoc, page, typst, preview_dir, faksimile=self.options.layout != "neusatz")
            except Exception as exc:  # noqa: BLE001 – Vorschau darf die Verarbeitung nie aufhalten
                preview_failed.append(exc)
                self._log_error(exc)
                self.emit(Event("hinweis", "Die Vorschau der Übersetzung konnte nicht erstellt werden "
                                           "(Details im Fehlerprotokoll). Die Verarbeitung läuft weiter.",
                                src.name, index, total))
                return
            self.emit(Event("seite_fertig", page.name, src.name, page.number, n_pages,
                            outputs=[original, translated]))

        restzeit = Restzeit()
        refine_rest = Restzeit()

        def refine_share() -> float:
            if not staged or not lt.units:
                return 0.0
            return sum(needs_refinement(u, t) for u, t in zip(lt.units, lt.troubled)) / len(lt.units)

        def tr_progress(label: str, base: float, span: float, where: str = ""):
            def progress(i: int, n: int) -> None:
                if i % 10 == 0:
                    save()  # Zwischenstand für das Fortsetzen
                done, remaining = _region_counts(ldoc.pages)
                extra = refine_share() * REFINE_FACTOR * (done + remaining)
                rest = restzeit.estimate(done, remaining, extra)
                step(f"{label}: Abschnitt {i} von {n}{where}", base + span * i / max(1, n),
                     rest if rest is not None else False)
            return progress

        def refine_progress(i: int, n: int) -> None:
            if i == 1:
                refine_rest.begin(0)
            rest = refine_rest.estimate(i - 1, n - i + 1)
            step(f"Überarbeitung schwieriger Abschnitte (großes Modell): Abschnitt {i} von {n}",
                 0.9 + 0.02 * i / max(1, n), rest if rest is not None else False)

        streams = self._translation_streams(translator.model, n_pages, step)
        lt = LayoutTranslator(ldoc, translator, on_page_done=page_done, streams=streams)
        already_translating = any(r.target_md for p in ldoc.pages for r in p.regions)
        review = bool(self.review and self.options.review) and not already_translating
        unread = [p for p in ldoc.pages if not p.read]
        for p in ldoc.pages:
            if p.read:
                self._preview_read(ldoc, p, preview_dir, src, index)
        t_read = time.time()
        read_seconds = translate_seconds = 0.0
        restzeit.begin(_region_counts(ldoc.pages)[0])

        if review:
            # ---- Phase 2 komplett, dann Prüfung der Umschrift, dann Phase 3 (Prüfung braucht den ganzen Text)
            for start in range(0, len(unread), PAGE_BATCH):
                self._check()
                batch = unread[start:start + PAGE_BATCH]
                done_before = n_total - len(unread) + start
                step(f"Phase 2 von 3 – Texterkennung: Seiten {batch[0].name}–{batch[-1].name} von {n_total}",
                     0.08 + 0.42 * done_before / max(1, n_total), False)
                reader.read_regions(batch)
                save()
                for p in batch:
                    self._preview_read(ldoc, p, preview_dir, src, index)
            read_seconds = time.time() - t_read
            if not any(r.source_md.strip() for p in ldoc.pages for r in p.regions):
                return FileResult(src, False, message="In der Datei wurde kein Text gefunden.")
            step("Warte auf Prüfung der Umschrift")
            md_ids = ldoc.flow_markdown(with_ids=True)
            preview = SourceDocument(src, src.stem, "scan", kind.value, [], list(ing.pages))
            reviewed = self.review(preview, md_ids)
            if reviewed is None:
                return FileResult(src, False, message="Übersprungen")
            if reviewed != md_ids:
                ldoc.apply_reviewed(reviewed)
                self._save_correction(preview, reviewed)
            save()
            t0 = time.time()
            restzeit.begin(_region_counts(ldoc.pages)[0])  # Wartezeit der Prüfung zählt nicht mit
            lt.translate_pages(ldoc.pages, tr_progress("Phase 3 von 3 – Übersetzung", 0.5, 0.42))
            translate_seconds = time.time() - t0
        else:
            # ---- Phase 2 und 3 überlappt: Der Prozessor liest Block für Block voraus, während die Grafikkarte
            # den vorigen Block zweitliest und übersetzt (der Seitenaufbau des ganzen Buchs steht schon fest).
            t0 = time.time()
            lt.translate_pages([p for p in ldoc.pages if p.read],
                               tr_progress("Übersetzung bereits gelesener Seiten", 0.08, 0.02))
            translate_seconds += time.time() - t0
            blocks = [unread[i:i + OVERLAP_BLOCK] for i in range(0, len(unread), OVERLAP_BLOCK)]
            analysed: queue.Queue = queue.Queue(maxsize=1)
            stop = threading.Event()
            analyse_seconds = [0.0]

            def hand_over(item) -> bool:
                while not stop.is_set():
                    try:
                        analysed.put(item, timeout=0.5)
                        return True
                    except queue.Full:
                        continue
                return False

            def produce() -> None:
                try:
                    for block in blocks:
                        t = time.time()
                        works = reader.analyse_pages(block)
                        analyse_seconds[0] += time.time() - t
                        if not hand_over((block, works)):
                            return
                    hand_over((None, None))
                except BaseException as exc:  # noqa: BLE001 – im Hauptablauf melden
                    hand_over((exc, None))

            producer = threading.Thread(target=produce, name="Texterkennung", daemon=True)
            producer.start()
            pages_done = n_total - len(unread)
            try:
                while True:
                    try:
                        block, works = analysed.get(timeout=1.0)
                    except queue.Empty:
                        self._check()
                        continue
                    if block is None:
                        break
                    if isinstance(block, BaseException):
                        raise block
                    self._check()
                    done, remaining = _region_counts(ldoc.pages)
                    rest = restzeit.estimate(done, remaining, refine_share() * REFINE_FACTOR * (done + remaining))
                    step(f"Phase 2 von 3 – Zweitlesung: Seiten {block[0].name}–{block[-1].name} von {n_total}",
                         0.08 + 0.84 * pages_done / max(1, n_total), rest if rest is not None else False)
                    t = time.time()
                    reader.finish_pages(works)
                    read_seconds += time.time() - t
                    save()
                    for p in block:
                        self._preview_read(ldoc, p, preview_dir, src, index)
                    base = 0.08 + 0.84 * pages_done / max(1, n_total)
                    t = time.time()
                    lt.translate_pages(block, tr_progress(
                        "Phase 3 von 3 – Übersetzung", base, 0.84 * len(block) / max(1, n_total),
                        f" (Seiten {block[0].name}–{block[-1].name} von {n_total})"))
                    translate_seconds += time.time() - t
                    pages_done += len(block)
                    save()
            finally:
                stop.set()
                producer.join(timeout=60)
            read_seconds += analyse_seconds[0]
            self.phase_times["ueberlappt"] = True
            if not any(r.source_md.strip() for p in ldoc.pages for r in p.regions):
                return FileResult(src, False, message="In der Datei wurde kein Text gefunden.")
        self.phase_times["lesen"] = read_seconds
        self.phase_times["seiten"] = len(unread)
        self.phase_times["lesen_und_uebersetzen"] = time.time() - t_read
        ldoc.readers = [r for r in (tess and "Tesseract", glm and glm.model, judge and judge.model) if r]

        if refiner:
            t0 = time.time()
            self.phase_times["ueberarbeitet"] = lt.refine(
                refiner, refine_progress)
            translate_seconds += time.time() - t0
        self.phase_times["uebersetzen"] = translate_seconds
        self.phase_times["stroeme"] = streams
        self.phase_times["bereiche"] = sum(1 for p in ldoc.pages for r in p.regions if r.translatable)
        self.phase_times["wiederholungen"] = translator.stats.retries + (refiner.stats.retries if refiner else 0)
        self.phase_times["reparaturen"] = translator.stats.repairs + (refiner.stats.repairs if refiner else 0)
        pruefbericht.check_translation(ldoc)
        save()
        if translator.stats.fallbacks:
            self.emit(Event("hinweis", f"{translator.stats.fallbacks} Bereich(e) mit vereinfachter Übersetzung "
                                       "– im Dokument gekennzeichnet.", src.name, index, total))
        step("Seiten werden gesetzt", 0.92, False)
        outputs = self._write_layout_outputs(src, ldoc, kind)
        rows = pruefbericht.summary(ldoc)
        red = [name for name, l, _ in rows if l == "rot"]
        yellow = [name for name, l, _ in rows if l == "gelb"]
        if red or yellow:
            text = f"Prüfbericht: {len(red)} Seite(n) mit Fehlern, {len(yellow)} zu prüfen"
            if red:
                text += f" (Fehler auf S. {', '.join(red[:8])}{' …' if len(red) > 8 else ''})"
            self.emit(Event("hinweis", text + " – Einzelheiten in der Datei „Prüfbericht“.", src.name, index, total))
        self.emit(Event("fertig", "Fertig", src.name, index, total, 1.0, outputs))
        marks = sum(len(markup.find_marks(r.source_md)) for p in ldoc.pages for r in p.regions)
        return FileResult(src, True, outputs, marks, 0)

    def _write_layout_outputs(self, src: Path, ldoc: LayoutDocument, kind: SourceKind) -> list[Path]:
        out_dir = output_dir_for(src, self.options, self.paths)
        work = Path(ldoc.workdir)
        handwriting = kind == SourceKind.HANDSCHRIFT
        meta = DocMeta(src.stem, src.name, self.lang.label, self.period, kind.label, self._models(), handwriting)
        faksimile = self.options.layout == "faksimile"
        typst = self.paths.runtime / "typst" / "typst.exe"
        outputs: list[Path] = []

        flow_only = self.options.layout == "fliesstext"
        images = [r.image for p in ldoc.pages for r in p.regions if r.image]
        if images:
            img_dir = out_dir / "Abbildungen"
            img_dir.mkdir(exist_ok=True)
            for name in images:
                shutil.copy2(work / name, img_dir / name)
        outputs.append(pruefbericht.write_report(ldoc, out_dir / f"{src.stem} – Prüfbericht.txt", src.stem))
        # Diagnose ohne Inhalt (nur Rahmen, Arten, Sicherheit) – darf zur Fehlersuche weitergegeben werden
        pruefbericht.write_diagnose(ldoc, out_dir / f"{src.stem} – Diagnose ohne Inhalt.json")
        exporter = Exporter(self.paths)
        for label, translated in (("Umschrift", False), ("Übersetzung", True)):
            flow = build_document(ldoc.flow_markdown(translated=translated), meta, translated=translated)
            md_path = out_dir / f"{src.stem} – {label}.md"
            md_path.write_text(flow.replace("](abbildung-", "](Abbildungen/abbildung-"), encoding="utf-8")
            outputs.append(md_path)
            stem = f"{src.stem} – {label}"
            # Die Umschrift immer als Neusatz: ein Faksimile der Umschrift wäre nur das Original selbst.
            fak = faksimile and translated
            if flow_only:
                tmp_md = work / "fliesstext.md"  # Abbildungen liegen im Arbeitsordner
                tmp_md.write_text(flow, encoding="utf-8")
                for fmt in self.options.formats:
                    try:
                        outputs.append(exporter.convert(tmp_md, fmt, out_dir / f"{stem}{FORMATS[fmt][1]}"))
                    except (ExportError, KeyError) as exc:
                        self.emit(Event("hinweis", str(exc), src.name))
                continue
            try:
                if "pdf" in self.options.formats:
                    outputs.append(layout_render.render_pdf(ldoc, out_dir / f"{stem}.pdf", typst, faksimile=fak,
                                                            translated=translated, handwriting=handwriting, title=stem))
                if "docx" in self.options.formats:
                    outputs.append(layout_docx.build_docx(ldoc, out_dir / f"{stem}.docx", faksimile=fak,
                                                          translated=translated, handwriting=handwriting, title=stem))
            except (RuntimeError, OSError) as exc:
                self.emit(Event("hinweis", str(exc), src.name))
            if "epub" in self.options.formats:
                tmp_md = work / "fliesstext.md"  # Abbildungen liegen im Arbeitsordner
                tmp_md.write_text(flow, encoding="utf-8")
                try:
                    outputs.append(exporter.convert(tmp_md, "epub", out_dir / f"{stem}.epub"))
                except ExportError as exc:
                    self.emit(Event("hinweis", str(exc), src.name))
        return outputs

    def _process_docx_inplace(self, src: Path, lexicon: Lexicon, glossary: Glossary, step, index: int,
                              total: int) -> FileResult:
        from quellenuebersetzer.pipeline.docx_inplace import translate_docx

        translator = self._translator(lexicon, glossary, step)
        out_dir = output_dir_for(src, self.options, self.paths)
        step("Word-Dokument wird übersetzt (Formatierung bleibt erhalten)", 0.1)
        out = translate_docx(src, out_dir / f"{src.stem} – Übersetzung.docx", translator,
                             progress=lambda i, n: step(f"Übersetzung: Absatz {i} von {n}", 0.1 + 0.85 * i / max(1, n)))
        self.emit(Event("fertig", "Fertig", src.name, index, total, 1.0, [out]))
        return FileResult(src, True, [out])

    def _preview_layout(self, ldoc: LayoutDocument, page, preview_dir: Path, src: Path, index: int, n_total: int) -> None:
        """Erkannten Seitenaufbau sofort in der Vorschau zeigen (blätterbar, bevor Text gelesen wird)."""
        try:
            aufbau = layout_render.layout_preview(ldoc, page, preview_dir)
            original = layout_render.original_preview(ldoc, page, preview_dir)
        except Exception as exc:  # noqa: BLE001
            self._log_error(exc)
            return
        self.emit(Event("seite_aufbau", page.name, src.name, page.number, n_total, outputs=[original, aufbau]))

    def _preview_read(self, ldoc: LayoutDocument, page, preview_dir: Path, src: Path, index: int) -> None:
        """Gelesene Seite sofort in der Vorschau zeigen (als Original, bis die Übersetzung fertig ist)."""
        try:
            original = layout_render.original_preview(ldoc, page, preview_dir)
        except Exception as exc:  # noqa: BLE001
            self._log_error(exc)
            return
        self.emit(Event("seite_gelesen", page.name, src.name, page.number, 0, outputs=[original]))

    def _log_error(self, exc: BaseException) -> None:
        try:
            self.paths.logs.mkdir(parents=True, exist_ok=True)
            with (self.paths.logs / "fehler.log").open("a", encoding="utf-8") as fh:
                fh.write(f"{time.ctime()} {type(exc).__name__}\n{_safe_traceback(exc)}\n")
        except OSError:
            pass

    def _log_times(self, src: Path, seconds: float) -> None:
        """Zeitprotokoll ohne Inhalte und ohne Dateinamen – zeigt, wo die Zeit bleibt."""
        try:
            self.paths.logs.mkdir(parents=True, exist_ok=True)
            from quellenuebersetzer import __version__, build_stamp

            lines = [f"{time.ctime()} | Version {__version__} ({build_stamp()}) | Quelle *{src.suffix.lower() or '(Ordner)'}"
                     f" | Darstellung {self.options.layout}"
                     f" | Schrift {self.options.kind.value} | Modus {self.settings.mode} | gesamt {seconds:.0f} s"]
            pt = getattr(self, "phase_times", {})
            if pt.get("aufbau") is not None:
                lines.append(f"  Seitenaufbau: {pt['aufbau']:.0f} s ({pt.get('kerne', 1)} Seiten gleichzeitig)")
            if pt.get("lesen_und_uebersetzen") is not None:
                lines.append(f"  Lesen und Übersetzen zusammen: {pt['lesen_und_uebersetzen']:.0f} s"
                             + (" (überlappt)" if pt.get("ueberlappt") else " (nacheinander)")
                             + f", {pt.get('stroeme', 1)} Übersetzung(en) gleichzeitig")
            if pt.get("seiten"):
                lines.append(f"  Lesen: {pt.get('lesen', 0):.0f} s für {pt['seiten']} Seite(n) "
                             f"= {pt.get('lesen', 0) / pt['seiten']:.0f} s/Seite")
            if pt.get("bereiche"):
                lines.append(f"  Übersetzen: {pt.get('uebersetzen', 0):.0f} s für {pt['bereiche']} Bereiche, "
                             f"{pt.get('wiederholungen', 0)} zweite Versuche, "
                             f"{pt.get('reparaturen', 0)} ohne Neuanfrage repariert"
                             + (f", {pt['ueberarbeitet']} Abschnitte vom großen Modell überarbeitet"
                                if pt.get("ueberarbeitet") is not None else ""))
            for model, st in self.client.stats.items():
                tok_in = st["eingabe"] / st["eingabe_s"] if st["eingabe_s"] else 0
                tok_out = st["ausgabe"] / st["ausgabe_s"] if st["ausgabe_s"] else 0
                lines.append(f"  {model}: {st['anfragen']} Anfragen, {st['sekunden']:.0f} s, "
                             f"Eingabe {tok_in:.0f} Token/s, Ausgabe {tok_out:.1f} Token/s, Laden {st['laden_s']:.0f} s")
            with (self.paths.logs / "zeiten.log").open("a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            self.client.stats.clear()
        except OSError:
            pass

    def _tess_langs(self, kind: SourceKind) -> list[str]:
        langs = self.lang.tesseract_langs_for(kind.value)
        return langs + [l for l in self.lang.tesseract.get("zusatz", []) if l != "osd" and l not in langs]

    def _models(self) -> list[str]:
        return [m for m in dict.fromkeys([self.settings.ocr_model, self.settings.draft_model, self.settings.main_model]) if m]

    def _write_outputs(self, src: Path, doc: SourceDocument, original_md: str, german_md: str) -> list[Path]:
        out_dir = output_dir_for(src, self.options, self.paths)
        handwriting = doc.kind == SourceKind.HANDSCHRIFT.value
        kind_label = SourceKind(doc.kind).label if doc.origin != "digital" else "Digitales Dokument"
        meta = DocMeta(src.stem, src.name, self.lang.label, self.period, kind_label, self._models(), handwriting)
        outputs = []
        files = {
            "Umschrift": build_document(original_md, meta, translated=False),
            "Übersetzung": build_document(german_md, meta, translated=True),
        }
        exporter = Exporter(self.paths)
        work = self.paths.cache / "export"
        work.mkdir(parents=True, exist_ok=True)
        for label, content in files.items():
            md_path = out_dir / f"{src.stem} – {label}.md"
            md_path.write_text(content, encoding="utf-8")
            outputs.append(md_path)
            tmp_md = work / "dokument.md"  # Pandoc arbeitet im ASCII-Pfad
            tmp_md.write_text(content, encoding="utf-8")
            for fmt in self.options.formats:
                if fmt not in FORMATS:
                    continue
                try:
                    outputs.append(exporter.convert(tmp_md, fmt, out_dir / f"{src.stem} – {label}{FORMATS[fmt][1]}"))
                except ExportError as exc:
                    self.emit(Event("hinweis", str(exc), src.name))
            tmp_md.unlink(missing_ok=True)
        return outputs

    def _save_correction(self, doc: SourceDocument, reviewed: str) -> None:
        """Vom Nutzer korrigierte Umschrift + Seitenbilder als Grundlage für späteres Training (nur lokal)."""
        if doc.origin == "digital" or not doc.pages:
            return
        dest = self.paths.corrections / time.strftime("%Y%m%d-%H%M%S")
        try:
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "umschrift.md").write_text(reviewed, encoding="utf-8")
            (dest / "quellenart.txt").write_text(doc.kind, encoding="utf-8")
            for p in doc.pages:
                shutil.copy2(p.path, dest / p.path.name)
        except OSError:
            pass


def _safe_traceback(exc: BaseException) -> str:
    """Traceback nur mit Code-Stellen – ohne Variableninhalte (die Textteile enthalten könnten)."""
    frames = traceback.extract_tb(exc.__traceback__)
    return "".join(f"  {f.filename}:{f.lineno} in {f.name}\n" for f in frames)


def _friendly_error(exc: Exception) -> str:
    from quellenuebersetzer.runtime.ollama import OllamaError
    from quellenuebersetzer.runtime.tesseract import TesseractError

    if isinstance(exc, OllamaError):
        return "Die lokale Modell-Laufzeit hat nicht geantwortet. Bitte das Programm neu starten."
    if isinstance(exc, TesseractError):
        return "Die Texterkennung ist fehlgeschlagen. Ist die Datei ein lesbares Bild?"
    if isinstance(exc, (OSError, PermissionError)):
        return "Die Datei konnte nicht gelesen oder das Ergebnis nicht gespeichert werden (Zugriffsrechte?)."
    if isinstance(exc, ValueError):
        return str(exc)
    return "Unerwarteter Fehler. Details stehen in der Protokolldatei (ohne Textinhalte)."
