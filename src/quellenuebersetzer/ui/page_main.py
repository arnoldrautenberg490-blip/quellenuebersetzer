"""Hauptfenster für den Alltag: Pfad einfügen (oder hineinziehen) → Übersetzen → Ergebnis öffnen."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QRadioButton,
    QVBoxLayout,
)

from quellenuebersetzer.config import APP_NAME
from quellenuebersetzer.pipeline.export import FORMATS
from quellenuebersetzer.pipeline.ingest import SUPPORTED, iter_sources
from quellenuebersetzer.pipeline.runner import Event
from quellenuebersetzer.planner import HANDWRITING_WARNING
from quellenuebersetzer.profile import Profile, SourceKind
from quellenuebersetzer.ui.preview import PreviewPanel
from quellenuebersetzer.ui.widgets import Page, button, frame, label, message_box


def clean_path(text: str) -> str:
    """Kopierte Pfade bereinigen: Anführungszeichen (»Als Pfad kopieren«), file://-Adressen, Leerzeichen."""
    t = text.strip().strip('"').strip("'").strip()
    if t.lower().startswith("file:///"):
        t = QUrl(t).toLocalFile()
    return os.path.expandvars(t)


class DropZone(QFrame):
    dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(150)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = label("⇣", wrap=False)
        icon.setStyleSheet("font-size: 30pt;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon)
        t = label("Datei oder Ordner hierher ziehen", wrap=False)
        t.setStyleSheet("font-size: 13pt; font-weight: 600;")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        s = label("PDF, Word (DOCX), Bilder (JPG, PNG, TIFF) oder Textdateien", "small", wrap=False)
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(s)

    def _set_hover(self, on: bool) -> None:
        self.setProperty("hover", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._set_hover(True)

    def dragLeaveEvent(self, e):
        self._set_hover(False)

    def dropEvent(self, e):
        self._set_hover(False)
        urls = e.mimeData().urls()
        if urls:
            self.dropped.emit(urls[0].toLocalFile())


class MainPage(Page):
    start = Signal(list, object, list, bool, str)  # Quellen, SourceKind, Formate, prüfen, Darstellung
    cancel = Signal()
    open_settings = Signal()

    def __init__(self, profile: Profile, formats: list[str], last_kind: str | None, review_mode: str,
                 layout: str = "faksimile"):
        super().__init__()
        self.profile = profile
        self.review_mode = review_mode
        b = self.body

        head = QHBoxLayout()
        head.addWidget(label(APP_NAME, "title"))
        head.addStretch(1)
        badge = label("●  Offline – Ihre Dokumente verlassen diesen Rechner nicht", "badge", wrap=False)
        head.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        settings = button("Einstellungen", "link")
        settings.clicked.connect(self.open_settings.emit)
        head.addWidget(settings, 0, Qt.AlignmentFlag.AlignVCenter)
        b.addLayout(head)

        # Quelle
        self.drop = DropZone()
        self.drop.dropped.connect(self.set_path)
        b.addWidget(self.drop)
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("… oder hier den Pfad einfügen (Strg+V), z. B. C:\\Archiv\\Akten 1785")
        self.path_edit.textChanged.connect(self._path_changed)
        row.addWidget(self.path_edit, 1)
        browse_file = button("Datei wählen …")
        browse_file.clicked.connect(self._browse_file)
        browse_dir = button("Ordner wählen …")
        browse_dir.clicked.connect(self._browse_dir)
        row.addWidget(browse_file)
        row.addWidget(browse_dir)
        b.addLayout(row)
        self.path_info = label("", "small")
        b.addWidget(self.path_info)

        # Schriftart der Quelle (nur wenn mehrere im Profil). Tabellen sind keine eigene Wahl: Die Seitenaufbau-
        # Erkennung findet sie in jedem Dokument – eine Seite kann also Fließtext UND Tabellen enthalten.
        self.kind_group = QButtonGroup(self)
        self.kind_box, kl = frame(margins=14)
        kl.addWidget(label("Die Schrift dieser Quelle ist:", "muted"))
        krow = QHBoxLayout()
        script_kinds = [k for k in profile.kinds if k != SourceKind.TABELLEN] or [SourceKind.DRUCK]
        for kind in script_kinds:
            rb = QRadioButton(kind.label)
            rb.setProperty("kind", kind.value)
            self.kind_group.addButton(rb)
            krow.addWidget(rb)
            if kind.value == last_kind:
                rb.setChecked(True)
        if not self.kind_group.checkedButton() and self.kind_group.buttons():
            self.kind_group.buttons()[0].setChecked(True)
        krow.addStretch(1)
        kl.addLayout(krow)
        kl.addWidget(label("Tabellen, Abbildungen, Randnotizen und Fußnoten werden auf jeder Seite automatisch erkannt.",
                           "small"))
        self.kind_box.setVisible(len(script_kinds) > 1)
        self.kind_group.buttonToggled.connect(lambda *_: self._kind_changed())
        b.addWidget(self.kind_box)

        self.hw_banner = message_box("warning", "Handschrift", HANDWRITING_WARNING)
        b.addWidget(self.hw_banner)

        # Formate und Prüfung
        opts, ol = frame(margins=14)
        frow = QHBoxLayout()
        frow.addWidget(label("Ergebnis als:", "muted", wrap=False))
        self.format_boxes: dict[str, QCheckBox] = {}
        for key, (name, _ext) in FORMATS.items():
            cb = QCheckBox(name)
            cb.setChecked(key in formats)
            self.format_boxes[key] = cb
            frow.addWidget(cb)
        frow.addStretch(1)
        ol.addLayout(frow)
        lrow = QHBoxLayout()
        lrow.addWidget(label("Darstellung:", "muted", wrap=False))
        self.layout_group = QButtonGroup(self)
        for key, text, tip in (
            ("faksimile", "Seitengetreu – Faksimile",
             "Die Originalseite bleibt als Hintergrund erhalten; der Text wird an derselben Stelle durch die Übersetzung ersetzt."),
            ("neusatz", "Seitengetreu – Neusatz",
             "Gleiche Anordnung wie im Original auf weißer Seite; Abbildungen werden übernommen."),
            ("fliesstext", "Fließtext", "Fortlaufender Text ohne Seitenaufbau – am leichtesten weiterzubearbeiten."),
        ):
            rb = QRadioButton(text)
            rb.setToolTip(tip)
            rb.setProperty("layout", key)
            rb.setChecked(key == layout)
            self.layout_group.addButton(rb)
            lrow.addWidget(rb)
        lrow.addStretch(1)
        ol.addLayout(lrow)
        ol.addWidget(label("Seitengetreu gilt für PDF und Word; E-Book und Markdown sind immer Fließtext. "
                           "Word-Quellen werden direkt in der Datei übersetzt.", "small"))
        self.review_box = QCheckBox("Umschrift vor der Übersetzung prüfen und korrigieren")
        ol.addWidget(self.review_box)
        b.addWidget(opts)

        # Fortschritt
        self.progress_box, pl = frame()
        self.file_label = label("")
        self.file_label.setStyleSheet("font-weight: 600; font-size: 12pt;")
        pl.addWidget(self.file_label)
        self.step_label = label("", "muted")
        pl.addWidget(self.step_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        pl.addWidget(self.bar)
        self.progress_box.setVisible(False)
        b.addWidget(self.progress_box)

        self.preview = PreviewPanel()
        b.addWidget(self.preview)

        self.results = QListWidget()
        self.results.setVisible(False)
        self.results.setMinimumHeight(140)
        self.results.itemDoubleClicked.connect(self._open_item)
        b.addWidget(self.results)
        b.addStretch(1)

        self.open_folder = button("Ergebnisordner öffnen")
        self.open_folder.setVisible(False)
        self.open_folder.clicked.connect(self._open_folder)
        self.cancel_button = button("Abbrechen")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel.emit)
        self.start_button = button("Übersetzen", "primary")
        self.start_button.setMinimumWidth(220)
        self.start_button.clicked.connect(self._start)
        self.footer.addWidget(self.open_folder)
        self.footer.addStretch(1)
        self.footer.addWidget(self.cancel_button)
        self.footer.addWidget(self.start_button)

        self._sources: list[Path] = []
        self._last_output: Path | None = None
        self._kind_changed()
        self._path_changed()

    # ------------------------------------------------------------------ Eingaben
    def current_kind(self) -> SourceKind:
        btn = self.kind_group.checkedButton()
        return SourceKind(btn.property("kind")) if btn else SourceKind.DRUCK

    def _kind_changed(self) -> None:
        hw = self.current_kind() == SourceKind.HANDSCHRIFT
        self.hw_banner.setVisible(hw)
        default_review = self.review_mode == "immer" or (self.review_mode == "auto" and hw)
        self.review_box.setChecked(default_review)

    def set_path(self, path: str) -> None:
        self.path_edit.setText(path)

    def _browse_file(self) -> None:
        patterns = " ".join(f"*{e}" for e in sorted(SUPPORTED))
        path, _ = QFileDialog.getOpenFileName(self, "Quelle wählen", "", f"Quellen ({patterns})")
        if path:
            self.set_path(path)

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Ordner mit Quellen wählen")
        if path:
            self.set_path(path)

    def _path_changed(self) -> None:
        raw = clean_path(self.path_edit.text())
        self._sources = []
        if not raw:
            self.path_info.setText("")
        else:
            p = Path(raw)
            if not p.exists():
                self.path_info.setText("⚠  Dieser Pfad wurde nicht gefunden.")
            else:
                self._sources = iter_sources(p)
                if not self._sources:
                    self.path_info.setText("⚠  Hier wurden keine unterstützten Dateien gefunden.")
                elif p.is_dir():
                    books = sum(1 for x in self._sources if x.is_dir())
                    extra = f" – davon {books} Ordner mit Seitenbildern, je als ein Dokument" if books else ""
                    self.path_info.setText(f"✓  {len(self._sources)} Quelle(n) gefunden{extra}.")
                else:
                    self.path_info.setText(f"✓  {p.name}")
                if "onedrive" in str(p).lower():
                    self.path_info.setText(self.path_info.text() + "  Hinweis: Der Ordner wird mit OneDrive "
                                           "synchronisiert – die Ergebnisse landen ebenfalls dort.")
        self.start_button.setEnabled(bool(self._sources))

    def formats(self) -> list[str]:
        return [k for k, cb in self.format_boxes.items() if cb.isChecked()]

    def _start(self) -> None:
        if not self._sources:
            return
        self.results.clear()
        self.results.setVisible(False)
        self.open_folder.setVisible(False)
        btn = self.layout_group.checkedButton()
        layout = btn.property("layout") if btn else "faksimile"
        self.start.emit(self._sources, self.current_kind(), self.formats(), self.review_box.isChecked(), layout)

    # ------------------------------------------------------------------ Ablauf
    def set_running(self, running: bool) -> None:
        self.start_button.setVisible(not running)
        self.cancel_button.setVisible(running)
        self.progress_box.setVisible(running or self.results.count() > 0)
        for w in (self.drop, self.path_edit, self.kind_box, *self.format_boxes.values(), self.review_box,
                  *self.layout_group.buttons()):
            w.setEnabled(not running)
        if running:
            self.preview.clear()
            self.bar.setValue(0)
            self.file_label.setText("Vorbereitung …")
            self.step_label.setText("")

    def on_event(self, ev: Event) -> None:
        if ev.kind == "seite_aufbau" and len(ev.outputs) == 2:
            self.preview.update_page(ev.message, ev.index, ev.total, ev.outputs[0], layout=ev.outputs[1], stage=0)
            return
        if ev.kind == "seite_gelesen" and ev.outputs:
            self.preview.update_page(ev.message, ev.index, ev.total, ev.outputs[0], stage=1)
            return
        if ev.kind == "seite_fertig" and len(ev.outputs) == 2:
            self.preview.update_page(ev.message, ev.index, ev.total, ev.outputs[0], translated=ev.outputs[1], stage=2)
            return
        if ev.kind == "datei":
            self.preview.clear()  # Vorschau zeigt die Seiten der aktuellen Datei
            self.file_label.setText(f"Datei {ev.index} von {ev.total}: {ev.file}")
            self.bar.setValue(0)
        elif ev.kind == "schritt":
            self.step_label.setText(ev.message)
            if ev.fraction:
                self.bar.setValue(int(ev.fraction * 1000))
        elif ev.kind == "fertig":
            self.bar.setValue(1000)
            for out in ev.outputs:
                if out.suffix.lower() in (".docx", ".pdf", ".epub") or (
                    out.suffix == ".md" and not any(o.suffix != ".md" for o in ev.outputs)
                ):
                    item = QListWidgetItem(f"✓  {out.name}")
                    item.setData(Qt.ItemDataRole.UserRole, str(out))
                    item.setToolTip("Doppelklick zum Öffnen")
                    self.results.addItem(item)
                    self._last_output = out.parent
            self.results.setVisible(True)
        elif ev.kind == "hinweis":
            self._add_note("ℹ", ev.message)
        elif ev.kind == "fehler":
            self._add_note("⚠", (f"{ev.file}: " if ev.file else "") + ev.message)
        elif ev.kind == "alles_fertig":
            self.file_label.setText(ev.message)
            self.step_label.setText("Doppelklick auf ein Ergebnis öffnet es.")

    def _add_note(self, symbol: str, text: str) -> None:
        item = QListWidgetItem(f"{symbol}  {text}")
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.results.addItem(item)
        self.results.setVisible(True)

    def finished(self) -> None:
        self.set_running(False)
        self.open_folder.setVisible(self._last_output is not None)

    def _open_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_folder(self) -> None:
        if self._last_output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_output)))
