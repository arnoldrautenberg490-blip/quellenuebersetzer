"""Gestaltung: ruhige Archiv-/Bibliotheksanmutung, heller und dunkler Modus."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Tokens:
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_text: str
    good: str
    warn: str
    bad: str
    bad_bg: str
    warn_bg: str
    good_bg: str
    mark_a: str
    mark_b1: str
    mark_b2: str


LIGHT = Tokens(
    bg="#F4EFE6", surface="#FBF8F2", surface_alt="#EFE8DA", border="#D8CCB6",
    text="#2A2620", text_muted="#6E665A",
    accent="#1F3A5F", accent_hover="#2B4E7D", accent_text="#FFFFFF",
    good="#2E6B3F", warn="#9A6A00", bad="#A33A2B",
    bad_bg="#F8E6E2", warn_bg="#F7EFD9", good_bg="#E4EFE3",
    mark_a="#B35C00", mark_b1="#3B5BA9", mark_b2="#2F7D6D",
)

DARK = Tokens(
    bg="#1B1A18", surface="#24221F", surface_alt="#2D2A26", border="#3D3933",
    text="#ECE6DA", text_muted="#A69E90",
    accent="#7FA3D6", accent_hover="#9DBBE4", accent_text="#14202F",
    good="#7CC08E", warn="#E0B654", bad="#E58A7B",
    bad_bg="#3A2522", warn_bg="#3A321F", good_bg="#223225",
    mark_a="#F0A050", mark_b1="#93AEEB", mark_b2="#7CC7B5",
)

SERIF = "Georgia"
SANS = "Segoe UI"


def is_dark_system() -> bool:
    app = QApplication.instance()
    if app is None:
        return False
    try:
        from PySide6.QtCore import Qt

        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return app.palette().color(QPalette.ColorRole.Window).lightness() < 128


def tokens_for(mode: str) -> Tokens:
    if mode == "dunkel":
        return DARK
    if mode == "hell":
        return LIGHT
    return DARK if is_dark_system() else LIGHT


def stylesheet(t: Tokens) -> str:
    from quellenuebersetzer.config import resources_dir

    check = (resources_dir() / "ui" / ("haken-dunkel.svg" if t is DARK else "haken.svg")).as_posix()
    dot = (resources_dir() / "ui" / ("punkt-dunkel.svg" if t is DARK else "punkt.svg")).as_posix()
    return f"""
* {{ font-family: "{SANS}"; font-size: 11pt; color: {t.text}; }}
QMainWindow, QDialog, QWidget#Page {{ background: {t.bg}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-family: "{SERIF}"; font-size: 24pt; color: {t.accent}; }}
QLabel[role="h2"] {{ font-family: "{SERIF}"; font-size: 15pt; color: {t.text}; margin-top: 6px; }}
QLabel[role="muted"] {{ color: {t.text_muted}; }}
QLabel[role="small"] {{ color: {t.text_muted}; font-size: 9.5pt; }}
QLabel[role="badge"] {{ color: {t.good}; background: {t.good_bg}; border-radius: 11px; padding: 3px 10px; font-size: 9.5pt; }}

QFrame[role="card"] {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px; }}
QFrame[role="warning"] {{ background: {t.bad_bg}; border: 1px solid {t.bad}; border-radius: 10px; }}
QFrame[role="warning"] QLabel {{ color: {t.text}; }}
QFrame[role="caution"] {{ background: {t.warn_bg}; border: 1px solid {t.warn}; border-radius: 10px; }}
QFrame[role="ok"] {{ background: {t.good_bg}; border: 1px solid {t.good}; border-radius: 10px; }}

QPushButton {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px;
    padding: 9px 18px; min-height: 22px;
}}
QPushButton:hover {{ background: {t.surface_alt}; }}
QPushButton:disabled {{ color: {t.text_muted}; background: {t.surface_alt}; }}
QPushButton[role="primary"] {{
    background: {t.accent}; color: {t.accent_text}; border: none; font-size: 12.5pt; font-weight: 600;
    padding: 12px 28px;
}}
QPushButton[role="primary"]:hover {{ background: {t.accent_hover}; }}
QPushButton[role="primary"]:disabled {{ background: {t.border}; color: {t.text_muted}; }}
QPushButton[role="danger"] {{ background: {t.bad}; color: #FFFFFF; border: none; font-weight: 600; }}
QPushButton[role="link"] {{ background: transparent; border: none; color: {t.accent}; padding: 4px 6px; text-decoration: underline; }}

QPushButton[role="choice"] {{
    text-align: left; padding: 14px 16px; background: {t.surface}; border: 1.5px solid {t.border}; border-radius: 10px;
}}
QPushButton[role="choice"]:checked {{ border: 2px solid {t.accent}; background: {t.surface_alt}; }}
QPushButton[role="chip"] {{ border-radius: 16px; padding: 7px 16px; background: {t.surface}; border: 1.5px solid {t.border}; }}
QPushButton[role="chip"]:checked {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QTableWidget {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px; padding: 8px 10px;
    selection-background-color: {t.accent}; selection-color: {t.accent_text};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 1.5px solid {t.accent}; }}
QComboBox QAbstractItemView {{ background: {t.surface}; border: 1px solid {t.border}; }}
QHeaderView::section {{ background: {t.surface_alt}; border: none; padding: 6px; font-weight: 600; }}

QCheckBox {{ spacing: 10px; padding: 4px 0; }}
QCheckBox::indicator {{ width: 20px; height: 20px; border-radius: 5px; border: 1.5px solid {t.border}; background: {t.surface}; }}
QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; image: url("{check}"); }}
QRadioButton {{ spacing: 10px; padding: 4px 8px 4px 0; }}
QRadioButton::indicator {{ width: 18px; height: 18px; border-radius: 11px; border: 1.5px solid {t.text_muted}; background: {t.surface}; }}
QRadioButton::indicator:checked {{ border: 1.5px solid {t.accent}; background: {t.accent}; image: url("{dot}"); }}

QProgressBar {{ background: {t.surface_alt}; border: none; border-radius: 6px; height: 12px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 6px; }}

QFrame#DropZone {{ background: {t.surface}; border: 2px dashed {t.border}; border-radius: 14px; }}
QFrame#DropZone[hover="true"] {{ border-color: {t.accent}; background: {t.surface_alt}; }}
QListWidget {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px; padding: 4px; }}
QListWidget::item {{ padding: 6px; border-bottom: 1px solid {t.surface_alt}; }}
QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def apply(app: QApplication, mode: str = "system") -> Tokens:
    t = tokens_for(mode)
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(t.bg))
    pal.setColor(QPalette.ColorRole.Base, QColor(t.surface))
    pal.setColor(QPalette.ColorRole.Text, QColor(t.text))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(t.text))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(t.accent))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t.accent_text))
    app.setPalette(pal)
    app.setFont(QFont(SANS, 11))
    app.setStyleSheet(stylesheet(t))
    return t
