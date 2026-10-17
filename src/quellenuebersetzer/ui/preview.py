"""Blätterbare Vorschau – zeigt jede Seite in ihrer jeweiligen Stufe: Aufbau erkannt → gelesen → übersetzt.

Phase 1 (Seitenaufbau des ganzen Dokuments) füllt die Vorschau sofort mit allen Seiten; man kann das
erkannte Layout durchblättern, bevor Text gelesen oder übersetzt wird.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from quellenuebersetzer.ui.widgets import button, frame, label

STAGE_TEXT = {0: "Aufbau erkannt", 1: "gelesen – wird übersetzt …", 2: "übersetzt"}


@dataclass
class PreviewPage:
    name: str
    number: int
    original: Path
    layout: Path | None = None
    translated: Path | None = None
    stage: int = 0  # 0 Aufbau, 1 gelesen, 2 übersetzt


class ImageLabel(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(420)
        self.path: Path | None = None
        self.setToolTip("Doppelklick öffnet die Seite groß")
        self._pix: QPixmap | None = None

    def show_image(self, path: Path | None) -> None:
        self.path = path
        self._pix = QPixmap(str(path)) if path and path.exists() else None
        self._rescale()

    def _rescale(self) -> None:
        if not self._pix or self._pix.isNull():
            self.clear()
            return
        self.setPixmap(self._pix.scaled(self.width() - 4, max(200, self.height() - 4),
                                        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def mouseDoubleClickEvent(self, e):
        if self.path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))


class PreviewPanel(QWidget):
    MODES = (("uebersetzung", "Übersetzung"), ("original", "Original"), ("aufbau", "Aufbau"),
             ("beide", "Nebeneinander"))

    def __init__(self):
        super().__init__()
        self.pages: list[PreviewPage] = []
        self.index = -1
        self.total = 0
        self.follow = True  # der jeweils neuesten Seite folgen, bis der Nutzer selbst blättert
        self.mode = "uebersetzung"

        box, lay = frame(margins=14)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)

        head = QHBoxLayout()
        self.title = label("Vorschau", "h2", wrap=False)
        head.addWidget(self.title)
        head.addStretch(1)
        self.mode_group = QButtonGroup(self)
        for key, text in self.MODES:
            b = button(text, "chip", checkable=True)
            b.setProperty("mode", key)
            b.setChecked(key == self.mode)
            self.mode_group.addButton(b)
            head.addWidget(b)
        self.mode_group.buttonClicked.connect(self._mode_changed)
        lay.addLayout(head)
        self.stage_label = label("", "small")
        lay.addWidget(self.stage_label)

        images = QHBoxLayout()
        self.left = ImageLabel()
        self.right = ImageLabel()
        images.addWidget(self.left, 1)
        images.addWidget(self.right, 1)
        lay.addLayout(images, 1)

        nav = QHBoxLayout()
        self.prev_btn: QPushButton = button("◀  Zurück")
        self.prev_btn.clicked.connect(lambda: self._go(self.index - 1))
        self.next_btn: QPushButton = button("Weiter  ▶")
        self.next_btn.clicked.connect(lambda: self._go(self.index + 1))
        self.position = label("", "muted", wrap=False)
        nav.addWidget(self.prev_btn)
        nav.addStretch(1)
        nav.addWidget(self.position)
        nav.addStretch(1)
        nav.addWidget(self.next_btn)
        lay.addLayout(nav)
        self.setVisible(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ------------------------------------------------------------------ Daten
    def clear(self) -> None:
        self.pages.clear()
        self.index = -1
        self.total = 0
        self.follow = True
        self.setVisible(False)

    def update_page(self, name: str, number: int, total: int, original: Path, *, layout: Path | None = None,
                    translated: Path | None = None, stage: int = 0) -> None:
        """Seite hinzufügen oder auf eine höhere Stufe heben (Aufbau → gelesen → übersetzt)."""
        if total:
            self.total = total
        page = next((p for p in self.pages if p.number == number), None)
        if page is None:
            page = PreviewPage(name, number, original)
            self.pages.append(page)
            self.pages.sort(key=lambda p: p.number)
        page.layout = layout or page.layout
        page.translated = translated or page.translated
        page.stage = max(page.stage, stage)
        self.setVisible(True)
        pos = self.pages.index(page)
        if self.index < 0 or (self.follow and stage == 0):
            self.index = pos  # in Phase 1 der wachsenden Seitenliste folgen
        elif self.follow and stage > 0:
            self.index = pos  # später: der gerade bearbeiteten Seite folgen
        self._show()

    # Kompatibilität zu früheren Aufrufen
    def add_page(self, name: str, number: int, total: int, original: Path, translated: Path | None) -> None:
        self.update_page(name, number, total, original, translated=translated, stage=2 if translated else 1)

    # ------------------------------------------------------------------ Anzeige
    def _go(self, i: int) -> None:
        if 0 <= i < len(self.pages):
            self.index = i
            self.follow = False
            self._show()

    def _mode_changed(self, btn) -> None:
        self.mode = btn.property("mode")
        self._show()

    def _current_image(self, p: PreviewPage) -> Path:
        if self.mode == "original":
            return p.original
        if self.mode == "aufbau":
            return p.layout or p.original
        # „Übersetzung“: zeigt den jeweils weitesten Stand der Seite
        return p.translated or (p.layout if p.stage == 0 and p.layout else p.original)

    def _show(self) -> None:
        if not self.pages:
            return
        p = self.pages[self.index]
        if self.mode == "beide":
            self.left.setVisible(True)
            self.right.setVisible(True)
            self.left.show_image(p.original)
            self.right.show_image(p.translated or p.layout or p.original)
        else:
            self.left.setVisible(True)
            self.right.setVisible(False)
            self.left.show_image(self._current_image(p))
        name = p.name if not p.name.isdigit() else f"Seite {p.name}"
        self.title.setText(f"Vorschau – {name}")
        self.stage_label.setText(f"Stand dieser Seite: {STAGE_TEXT[p.stage]}")
        self._update_position()

    def _update_position(self) -> None:
        n = len(self.pages)
        read = sum(1 for p in self.pages if p.stage >= 1)
        done = sum(1 for p in self.pages if p.stage >= 2)
        total = self.total or n
        self.position.setText(f"Seite {self.index + 1} von {n} · Aufbau {n}/{total} · gelesen {read} · übersetzt {done}")
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < n - 1)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Left:
            self._go(self.index - 1)
        elif e.key() == Qt.Key.Key_Right:
            self._go(self.index + 1)
        else:
            super().keyPressEvent(e)
