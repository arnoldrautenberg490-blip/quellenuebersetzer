"""Führt einen Installationsplan aus."""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from quellenuebersetzer.catalog import Catalog, Component
from quellenuebersetzer.config import Paths
from quellenuebersetzer.install.downloader import Cancelled, download
from quellenuebersetzer.install.manifest import Entry, Manifest
from quellenuebersetzer.install.verify import reconcile, write_marker
from quellenuebersetzer.planner import Plan, PlanItem
from quellenuebersetzer.runtime.ollama import OllamaService


@dataclass
class Progress:
    step: int
    steps: int
    label: str
    done: int = 0
    total: int = 0
    status: str = ""

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else 0.0


ProgressFn = Callable[[Progress], None]


class InstallError(Exception):
    pass


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _safe_extract_zip(archive: Path, target: Path, strip_top_dir: bool) -> None:
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        prefix = ""
        if strip_top_dir:
            tops = {n.split("/", 1)[0] for n in zf.namelist()}
            if len(tops) == 1:
                prefix = tops.pop() + "/"
        for name in names:
            rel = name[len(prefix):] if prefix and name.startswith(prefix) else name
            if not rel:
                continue
            dest = (target / rel).resolve()
            if root not in dest.parents and dest != root:
                raise InstallError(f"Ungültiger Pfad im Archiv: {name}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)


class Installer:
    def __init__(self, paths: Paths, catalog: Catalog, manifest: Manifest, service: OllamaService):
        self.paths = paths
        self.catalog = catalog
        self.manifest = manifest
        self.service = service
        self.cancel_requested = False

    @property
    def downloads(self) -> Path:
        return self.paths.cache / "downloads"

    def cancel(self) -> None:
        self.cancel_requested = True

    def _should_cancel(self) -> bool:
        return self.cancel_requested

    # ------------------------------------------------------------------ Ablauf
    def run(self, plan: Plan, progress: ProgressFn) -> None:
        self.paths.ensure()
        reconcile(self.paths, self.catalog, self.manifest)  # bereits Vorhandenes nicht erneut laden
        todo = plan.to_install
        # Modelle zuletzt: sie brauchen die laufende Ollama-Instanz.
        todo.sort(key=lambda i: {"component": 0, "tessdata": 1, "dictionary": 2, "model": 3}[i.kind])
        steps = len(todo)
        for n, item in enumerate(todo, start=1):
            if self.cancel_requested:
                raise Cancelled()
            report = Progress(n, steps, item.label)
            progress(report)

            def on_bytes(done: int, total: int, status: str = "", _r=report) -> None:
                _r.done, _r.total, _r.status = done, total, status
                progress(_r)

            if item.kind == "component":
                if self.manifest.has("component", item.id, self.catalog.components[item.id].files[0].sha256):
                    continue
                self._install_component(self.catalog.components[item.id], on_bytes)
            elif item.kind == "tessdata":
                self._install_tessdata(item, on_bytes)
            elif item.kind == "dictionary":
                self._install_dictionary(item, on_bytes)
            elif item.kind == "model":
                self._install_model(item, on_bytes)
        shutil.rmtree(self.downloads, ignore_errors=True)

    # ------------------------------------------------------------------ Komponenten
    def _fetch(self, comp: Component, on_bytes) -> list[Path]:
        total = comp.download_size
        offset = 0
        files = []
        for f in comp.files:
            base = offset
            files.append(
                download(
                    f.url, self.downloads / f.name, f.sha256, f.size,
                    progress=lambda d, _t, b=base: on_bytes(b + d, total),
                    should_cancel=self._should_cancel,
                )
            )
            offset += f.size
        return files

    def _install_component(self, comp: Component, on_bytes) -> None:
        for dep in comp.requires:
            if not self.manifest.has("component", dep, self.catalog.components[dep].files[0].sha256):
                self._install_component(self.catalog.components[dep], on_bytes)
        files = self._fetch(comp, on_bytes)
        target = self.paths.root / comp.target
        if target.exists():
            shutil.rmtree(target)
        if comp.install == "zip":
            _safe_extract_zip(files[0], target, comp.strip_top_dir)
        elif comp.install == "sevenzip":
            self._install_sevenzip(files, target)
        elif comp.install == "file":
            target.mkdir(parents=True, exist_ok=True)
            for f, spec in zip(files, comp.files):
                shutil.copy2(f, target / spec.name)
        elif comp.install == "nsis":
            self._extract_with_7z(files[0], target)
            shutil.rmtree(target / "$PLUGINSDIR", ignore_errors=True)
            for leftover in target.glob("*uninstall*.exe"):
                leftover.unlink(missing_ok=True)
        else:
            raise InstallError(f"Unbekannte Installationsart: {comp.install}")
        if not (self.paths.root / comp.check).exists():
            raise InstallError(f"{comp.label}: Installation unvollständig ({comp.check} fehlt).")
        write_marker(self.paths, comp)
        self.manifest.add(Entry(comp.id, "component", comp.files[0].sha256, [comp.target]))

    def _install_sevenzip(self, files: list[Path], target: Path) -> None:
        """7zr.exe (nur 7z-Format) entpackt das 7-Zip-Paket, das dann auch NSIS-Installer öffnen kann."""
        seven_zr, setup = files
        target.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            [str(seven_zr), "x", "-y", f"-o{target}", str(setup)],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        if r.returncode != 0:
            raise InstallError("Die Entpackhilfe konnte nicht eingerichtet werden.")
        for extra in ("7zFM.exe", "7zG.exe", "Uninstall.exe", "7-zip.chm", "Lang"):
            p = target / extra
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)

    def _extract_with_7z(self, archive: Path, target: Path) -> None:
        seven = self.paths.runtime / "7zip" / "7z.exe"
        target.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            [str(seven), "x", "-y", f"-o{target}", str(archive)],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        if r.returncode != 0:
            raise InstallError(f"Entpacken von {archive.name} fehlgeschlagen.")

    # ------------------------------------------------------------------ Daten
    def _install_tessdata(self, item: PlanItem, on_bytes) -> None:
        spec = self.catalog.tessdata[item.id]
        tessdir = self.paths.runtime / "tesseract" / "tessdata"
        tessdir.mkdir(parents=True, exist_ok=True)
        dest = tessdir / spec.name
        download(spec.url, dest, spec.sha256, spec.size, progress=on_bytes, should_cancel=self._should_cancel,
                 mirrors=spec.mirrors)
        rel = dest.relative_to(self.paths.root).as_posix()
        self.manifest.add(Entry(item.id, "tessdata", spec.sha256, [rel]))

    def _install_dictionary(self, item: PlanItem, on_bytes) -> None:
        for pack in self.catalog.languages.values():
            for d in pack.dictionaries:
                if d.id == item.id and d.available:
                    dest = self.paths.dicts / d.file
                    download(d.url, dest, d.sha256, d.size, progress=on_bytes, should_cancel=self._should_cancel)
                    self.manifest.add(Entry(d.id, "dictionary", d.sha256, [dest.relative_to(self.paths.root).as_posix()]))
                    return
        raise InstallError(f"Wörterbuch {item.id} ist nicht verfügbar.")

    def _install_model(self, item: PlanItem, on_bytes) -> None:
        self.service.start(offline=False)  # einziger Fall mit Netzzugang der Laufzeit: Modell-Download
        self.service.client.pull(item.id, progress=on_bytes, should_cancel=self._should_cancel)
        self.manifest.add(Entry(item.id, "model"))


def self_test(paths: Paths, service: OllamaService, model: str) -> tuple[bool, str]:
    """Kurzer Funktionstest nach der Installation mit einem eingebauten Beispielsatz."""
    tess = paths.runtime / "tesseract" / "tesseract.exe"
    if not tess.exists():
        return False, "Texterkennung fehlt."
    r = subprocess.run([str(tess), "--list-langs"], capture_output=True, text=True,
                       env={**os.environ, "TESSDATA_PREFIX": str(tess.parent / "tessdata")},
                       creationflags=_NO_WINDOW)
    if "pol" not in r.stdout:
        return False, "Polnisches Schriftmodell der Texterkennung fehlt."
    try:
        service.start(offline=True)  # Funktionstest bereits im abgeschotteten Betrieb
        res = service.client.chat(
            model,
            [{"role": "user", "content": "Übersetze ins Deutsche und antworte nur mit der Übersetzung: Dzień dobry."}],
            num_ctx=1024, num_predict=40,
        )
    except Exception as exc:  # noqa: BLE001 – Selbsttest meldet jeden Fehler verständlich
        return False, f"Sprachmodell antwortet nicht: {exc}"
    if "tag" not in res.text.lower():
        return False, f"Unerwartete Antwort des Sprachmodells: {res.text[:80]}"
    return True, "Alle Bausteine funktionieren."
