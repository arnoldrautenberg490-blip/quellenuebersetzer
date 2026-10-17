"""Hauptfenster: verbindet Einrichtung, Alltag und Dialoge."""

from __future__ import annotations

import shutil

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QStackedWidget

from quellenuebersetzer.catalog import load_catalog
from quellenuebersetzer.config import APP_NAME, Paths, Settings, resources_dir
from quellenuebersetzer.install.manifest import Manifest
from quellenuebersetzer.install.verify import reconcile
from quellenuebersetzer.install.uninstall import launch_program_uninstaller, remove_all_data
from quellenuebersetzer.pipeline.runner import JobOptions
from quellenuebersetzer.planner import build_plan
from quellenuebersetzer.profile import PERIOD_BY_KEY, LANGUAGE_BY_CODE, Profile
from quellenuebersetzer.runtime.ollama import OllamaService, tuning_for
from quellenuebersetzer.ui import theme
from quellenuebersetzer.ui.dialogs import BenchmarkDialog, ReviewDialog, SettingsDialog, UninstallDialog
from quellenuebersetzer.ui.page_main import MainPage
from quellenuebersetzer.ui.pages_setup import CheckingPage, InstallPage, PlanPage, ProfilePage
from quellenuebersetzer.ui.workers import (
    BenchmarkWorker,
    DetectWorker,
    InstallWorker,
    JobWorker,
    ReviewBridge,
    StartupCheckWorker,
)


class MainWindow(QMainWindow):
    def __init__(self, paths: Paths, settings: Settings, tokens: theme.Tokens):
        super().__init__()
        self.paths = paths
        self.settings = settings
        self.tokens = tokens
        self.catalog = load_catalog()
        self.service = OllamaService(paths, tuning=tuning_for(settings.gpu_name, settings.vram_gb))
        self.bridge = ReviewBridge()
        self.bridge.request.connect(self._review)
        self.job_worker: JobWorker | None = None
        self.install_worker: InstallWorker | None = None
        self.detect_worker: DetectWorker | None = None
        self.profile = Profile.from_dict(settings.profile)

        self.setWindowTitle(APP_NAME)
        icon = resources_dir() / "icon.png"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.resize(1080, 860)
        self.setMinimumSize(820, 640)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        if settings.setup_complete and self.profile.is_valid and settings.main_model:
            self._startup_check()
        else:
            self.show_profile(first_run=True)

    def _startup_check(self) -> None:
        """Schnellprüfung: fehlt etwas oder ist veraltet (z. B. nach einem Update)? Dann nur das ergänzen."""
        self._set_page(CheckingPage("Bausteine werden geprüft …",
                                    "Es wird nur nachinstalliert, was fehlt oder sich geändert hat."))
        self.check_worker = StartupCheckWorker(self.paths, self.catalog, self.profile, self.settings)
        self.check_worker.done.connect(self._startup_checked)
        self.check_worker.start()

    def _startup_checked(self, info, plan) -> None:
        self.system_info = info
        if plan.to_install and plan.can_install:
            self._install(plan, auto=True)  # Fehlendes ohne Rückfrage ergänzen
        elif plan.to_install:
            page = PlanPage(title="Ergänzung nötig")
            page.back.connect(self.show_main)
            page.install.connect(self._install)
            page.mode_changed.connect(lambda m: self._show_plan(info, m))
            page.show_plan(plan, info)
            self._set_page(page)
        else:
            self.show_main()

    # ------------------------------------------------------------------ Navigation
    def _set_page(self, page) -> None:
        old = self.stack.currentWidget()
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        if old is not None:
            self.stack.removeWidget(old)
            old.deleteLater()

    def show_profile(self, first_run: bool = False) -> None:
        page = ProfilePage(self.profile if self.profile.kinds else None, first_run=first_run)
        page.submitted.connect(self._profile_submitted)
        self._set_page(page)

    def _profile_submitted(self, profile: Profile) -> None:
        self.profile = profile
        self.settings.profile = profile.to_dict()
        self.settings.save(self.paths)
        self._set_page(CheckingPage())
        self.detect_worker = DetectWorker(self.paths)
        self.detect_worker.done.connect(self._show_plan)
        self.detect_worker.start()

    def _show_plan(self, info, mode: str | None = None) -> None:
        self.system_info = info
        manifest = Manifest(self.paths)
        reconcile(self.paths, self.catalog, manifest)
        plan = build_plan(self.profile, info, self.catalog, manifest, mode or self.settings.mode)
        page = PlanPage()
        page.back.connect(lambda: self.show_profile(first_run=not self.settings.setup_complete))
        page.install.connect(self._install)
        page.mode_changed.connect(lambda m: self._show_plan(info, m))
        page.show_plan(plan, info)
        self._set_page(page)

    def _install(self, plan, auto: bool = False) -> None:
        """``auto``: Ergänzung beim Programmstart – ohne Klick, danach direkt ins Hauptfenster."""
        if not plan.to_install:
            self._installed(plan)
            return
        page = InstallPage("Fehlende Bausteine werden ergänzt" if auto else "Einrichtung läuft")
        self._set_page(page)
        self.install_worker = InstallWorker(self.paths, self.catalog, plan, self.service)
        self.install_worker.progress.connect(page.on_progress)

        def finished(msg: str) -> None:
            self._installed(plan, show_main=False)
            page.on_done(msg)
            if auto:
                QTimer.singleShot(1500, self.show_main)

        self.install_worker.finished_ok.connect(finished)
        self.install_worker.failed.connect(page.on_failed)
        page.cancel.connect(self.install_worker.cancel)
        page.finished.connect(self.show_main)
        page.retry.connect(lambda: self._install(plan))
        self.install_worker.start()

    def _installed(self, plan, show_main: bool = True) -> None:
        self.settings.main_model = plan.main_model
        self.settings.ocr_model = plan.tier.ocr
        self.settings.tier = plan.tier.key
        self.settings.mode = plan.mode
        gpu = self.system_info.best_gpu if getattr(self, "system_info", None) else None
        if gpu:
            self.settings.gpu_name, self.settings.vram_gb = gpu.name, self.system_info.usable_vram_gb
        self.service.tuning = tuning_for(self.settings.gpu_name, self.settings.vram_gb)
        self.settings.setup_complete = True
        self.settings.save(self.paths)
        if show_main:
            self.show_main()

    def show_main(self) -> None:
        page = MainPage(self.profile, self.settings.formats, self.settings.last_source_kind, self.settings.review_mode,
                        self.settings.layout)
        page.start.connect(self._start_job)
        page.cancel.connect(self._cancel_job)
        page.open_settings.connect(self._open_settings)
        if self.settings.last_path:
            page.set_path(self.settings.last_path)
        self._set_page(page)

    # ------------------------------------------------------------------ Verarbeitung
    def _start_job(self, sources, kind, formats, review, layout) -> None:
        page: MainPage = self.stack.currentWidget()
        self.settings.formats = formats
        self.settings.layout = layout
        self.settings.last_source_kind = kind.value
        self.settings.last_path = page.path_edit.text()
        self.settings.save(self.paths)
        options = JobOptions(kind, formats, review, layout=layout)
        self.job_worker = JobWorker(self.paths, self.catalog, self.settings, self.profile, options, sources,
                                    self.service, self.bridge)
        self.job_worker.event.connect(page.on_event)
        self.job_worker.finished_all.connect(lambda _r: page.finished())
        page.set_running(True)
        self.job_worker.start()

    def _cancel_job(self) -> None:
        if self.job_worker and self.job_worker.isRunning():
            self.job_worker.cancel()

    def _review(self, doc, md: str) -> None:
        dlg = ReviewDialog(doc, md, self.tokens, self)
        accepted = dlg.exec()
        self.bridge.answer(dlg.result_md if accepted else None)

    # ------------------------------------------------------------------ Einstellungen
    def _profile_text(self) -> str:
        kinds = ", ".join(k.label for k in self.profile.kinds)
        periods = ", ".join(PERIOD_BY_KEY[p].label for p in self.profile.periods if p in PERIOD_BY_KEY)
        lang = LANGUAGE_BY_CODE.get(self.profile.language)
        return f"{kinds} · {lang.label if lang else self.profile.language} · {periods}"

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.paths, self.catalog, self.settings, self._profile_text(), self)
        dlg.change_profile.connect(lambda: self.show_profile(first_run=False))
        dlg.uninstall.connect(self._uninstall)
        dlg.theme_changed.connect(self._change_theme)
        dlg.benchmark.connect(self._benchmark)
        dlg.exec()

    def _benchmark(self) -> None:
        if self.job_worker and self.job_worker.isRunning():
            QMessageBox.information(self, APP_NAME, "Bitte warten, bis die laufende Verarbeitung abgeschlossen ist.")
            return
        dlg = BenchmarkDialog(self)
        self.bench_worker = BenchmarkWorker(self.paths, self.catalog, self.settings, self.service)
        self.bench_worker.status.connect(dlg.status.setText)
        self.bench_worker.result.connect(dlg.on_result)
        self.bench_worker.start()
        dlg.exec()

    def _change_theme(self, mode: str) -> None:
        self.settings.theme = mode
        self.settings.save(self.paths)
        self.tokens = theme.apply(QApplication.instance(), mode)

    def _uninstall(self) -> None:
        dlg = UninstallDialog(self.paths, self)
        if not dlg.exec():
            return
        self.service.stop()
        try:
            backup = remove_all_data(self.paths, backup=dlg.backup.isChecked())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, f"Nicht alle Daten konnten entfernt werden: {exc}")
            return
        text = "Alle Daten wurden entfernt."
        if backup:
            text += f"\n\nIhr Glossar und Ihre Korrekturen wurden gesichert in:\n{backup}"
        if launch_program_uninstaller():
            text += "\n\nDas Programm selbst wird jetzt deinstalliert."
        QMessageBox.information(self, APP_NAME, text)
        QApplication.instance().quit()

    # ------------------------------------------------------------------ Beenden
    def closeEvent(self, event) -> None:
        busy = (self.job_worker and self.job_worker.isRunning()) or (self.install_worker and self.install_worker.isRunning())
        if busy:
            answer = QMessageBox.question(
                self, APP_NAME, "Es läuft gerade eine Verarbeitung oder Installation. Wirklich beenden?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if self.job_worker:
                self.job_worker.cancel()
                self.job_worker.wait(5000)
            if self.install_worker:
                self.install_worker.cancel()
                self.install_worker.wait(5000)
        self.service.stop()
        shutil.rmtree(self.paths.cache / "jobs", ignore_errors=True)
        event.accept()
