"""Kleine Bausteine für eine einheitliche Oberfläche."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def label(text: str, role: str | None = None, wrap: bool = True, selectable: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    lbl.setTextFormat(Qt.TextFormat.PlainText if "<" not in text else Qt.TextFormat.RichText)
    if selectable:
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


def button(text: str, role: str | None = None, checkable: bool = False) -> QPushButton:
    b = QPushButton(text)
    if role:
        b.setProperty("role", role)
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def frame(role: str = "card", margins: int = 18, spacing: int = 8) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setProperty("role", role)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(margins, margins - 2, margins, margins - 2)
    lay.setSpacing(spacing)
    return f, lay


def message_box(role: str, title: str, text: str) -> QFrame:
    """Hinweis- (caution), Warn- (warning) oder Erfolgskasten (ok)."""
    f, lay = frame(role, margins=16, spacing=4)
    symbol = {"warning": "⚠", "caution": "ℹ", "ok": "✓"}.get(role, "")
    t = label(f"{symbol}  {title}" if symbol else title)
    t.setStyleSheet("font-weight: 700; font-size: 11.5pt;")
    lay.addWidget(t)
    if text:
        lay.addWidget(label(text))
    return f


def hrow(*widgets, stretch_first: bool = False, spacing: int = 10) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(spacing)
    for i, w in enumerate(widgets):
        if w is None:
            row.addStretch(1)
        elif isinstance(w, QWidget):
            row.addWidget(w, 1 if (stretch_first and i == 0) else 0)
        else:
            row.addLayout(w)
    return row


class Page(QWidget):
    """Seite mit zentrierter Spalte (max. Breite) und Bildlauf."""

    MAX_WIDTH = 900

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        h = QHBoxLayout(holder)
        h.setContentsMargins(24, 28, 24, 28)
        column = QWidget()
        column.setMaximumWidth(self.MAX_WIDTH)
        column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.body = QVBoxLayout(column)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(14)
        h.addStretch(1)
        h.addWidget(column, 100)
        h.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)
        # feste Fußleiste für die Hauptaktion (immer sichtbar)
        self.footer_widget = QWidget()
        self.footer = QHBoxLayout(self.footer_widget)
        self.footer.setContentsMargins(24, 10, 24, 18)
        outer.addWidget(self.footer_widget)

    def clear_body(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                _clear_layout(item.layout())


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def clear_layout(layout) -> None:
    _clear_layout(layout)
