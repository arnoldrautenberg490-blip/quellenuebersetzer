"""Dialoge: Kontrollansicht, Glossar, Einstellungen, Deinstallation, Über das Programm."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPixmap, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from quellenuebersetzer import __version__
from quellenuebersetzer.catalog import Catalog
from quellenuebersetzer.config import APP_NAME, Paths
from quellenuebersetzer.install.uninstall import folder_size
from quellenuebersetzer.pipeline.document import SourceDocument
from quellenuebersetzer.pipeline.lexicon import Glossary, GlossaryEntry
from quellenuebersetzer.planner import HANDWRITING_WARNING, format_bytes
from quellenuebersetzer.ui import review_text
from quellenuebersetzer.ui.theme import Tokens
from quellenuebersetzer.ui.widgets import button, frame, label, message_box


# --------------------------------------------------------------------------- Kontrollansicht


class MarkHighlighter(QSyntaxHighlighter):
    """Hebt ⟦unsichere Stellen⟧ farbig hervor und blendet Seitenmarken dezent ein."""

    def __init__(self, doc, tokens: Tokens, marks):
        super().__init__(doc)
        self.marks = marks
        self.fmt = {}
        for cat, color in (("a", tokens.mark_a), ("b1", tokens.mark_b1), ("b2", tokens.mark_b2)):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            f.setFontWeight(QFont.Weight.DemiBold)
            bg = QColor(color)
            bg.setAlpha(38)
            f.setBackground(bg)
            self.fmt[cat] = f
        self.fmt_muted = QTextCharFormat()
        self.fmt_muted.setForeground(QColor(tokens.text_muted))

    def highlightBlock(self, text: str) -> None:
        if review_text.EDITOR_PAGE_RE.match(text) or text.lstrip().startswith("<"):
            self.setFormat(0, len(text), self.fmt_muted)
        for m in review_text.EDITOR_MARK_RE.finditer(text):
            idx = int(m.group("num").translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789"))) - 1
            cat = self.marks[idx].category if 0 <= idx < len(self.marks) else "a"
            self.setFormat(m.start(), m.end() - m.start(), self.fmt[cat])


class ReviewDialog(QDialog):
    """Seitenbild links, Umschrift rechts. Unsichere Stellen sind farbig hervorgehoben."""

    def __init__(self, doc: SourceDocument, md: str, tokens: Tokens, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Umschrift prüfen – {doc.source.name}")
        self.resize(1400, 900)
        self.result_md: str | None = None
        self.original_md = md
        editor_text, self.marks = review_text.to_editor(md)
        self.editor_start = editor_text
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.addWidget(label("Umschrift prüfen", "h2"))
        lay.addWidget(label(
            "Korrigieren Sie die Umschrift rechts direkt im Text. Unsicher gelesene Stellen stehen in "
            "⟦Doppelklammern⟧; die Liste darunter zeigt die möglichen Lesarten. Ist eine Stelle geklärt, "
            "korrigieren Sie das Wort und löschen die Klammern samt Hochzahl. Bleibt die Klammer stehen, "
            "wird die Stelle auch in der Übersetzung als unsicher gekennzeichnet.", "muted"))
        if doc.kind == "handschrift":
            lay.addWidget(message_box("warning", "Handschrift", HANDWRITING_WARNING))

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.page_list = QComboBox()
        for p in doc.pages:
            self.page_list.addItem(f"Seite {p.number}", str(p.path))
        self.page_list.currentIndexChanged.connect(self._show_page)
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(self.page_list, 1)
        for text, factor in (("−", 0.8), ("+", 1.25)):
            zb = button(text)
            zb.setFixedWidth(44)
            zb.clicked.connect(lambda _=False, f=factor: self._zoom(f))
            zoom_row.addWidget(zb)
        ll.addLayout(zoom_row)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        scroll = QScrollArea()
        scroll.setWidget(self.image)
        scroll.setWidgetResizable(False)
        ll.addWidget(scroll, 1)
        self.scale = 0.5
        if doc.pages:
            split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.editor = QPlainTextEdit(editor_text)
        self.editor.setStyleSheet("font-family: Cambria; font-size: 13pt;")
        self.highlighter = MarkHighlighter(self.editor.document(), tokens, self.marks)
        self.highlighter.rehighlight()
        rl.addWidget(self.editor, 3)
        rl.addWidget(label(f"Unsichere Stellen ({len(self.marks)}) – anklicken springt zur Stelle", "small"))
        self.mark_list = QListWidget()
        for i, mk in enumerate(self.marks, start=1):
            self.mark_list.addItem(review_text.describe(mk, i))
        self.mark_list.currentRowChanged.connect(self._jump_to_mark)
        rl.addWidget(self.mark_list, 1)
        split.addWidget(right)
        split.setSizes([650, 750])
        lay.addWidget(split, 1)

        row = QHBoxLayout()
        skip = button("Diese Datei überspringen")
        skip.clicked.connect(self.reject)
        ok = button("Übernehmen und übersetzen", "primary")
        ok.clicked.connect(self._accept)
        row.addWidget(skip)
        row.addStretch(1)
        row.addWidget(ok)
        lay.addLayout(row)
        self._show_page()

    def _jump_to_mark(self, row: int) -> None:
        target = f"⟧{review_text.sup(row + 1)}"
        text = self.editor.toPlainText()
        pos = text.find(target)
        if pos < 0:
            return
        start = text.rfind("⟦", 0, pos)
        cursor = self.editor.textCursor()
        cursor.setPosition(max(0, start))
        cursor.setPosition(pos + len(target), cursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _show_page(self, *_):
        path = self.page_list.currentData()
        if not path:
            return
        pm = QPixmap(path)
        if not pm.isNull():
            self.image.setPixmap(pm.scaledToWidth(int(pm.width() * self.scale), Qt.TransformationMode.SmoothTransformation))
            self.image.adjustSize()

    def _zoom(self, factor: float) -> None:
        self.scale = max(0.15, min(2.0, self.scale * factor))
        self._show_page()

    def _accept(self) -> None:
        text = self.editor.toPlainText()
        self.result_md = self.original_md if text == self.editor_start else review_text.from_editor(text, self.marks)
        self.accept()


# --------------------------------------------------------------------------- Glossar


class GlossaryDialog(QDialog):
    COLS = ("Begriff (Original)", "Übersetzung", "Anmerkung", "Kategorie", "Zeitraum")
    CATS = {"": "–", "b1": "Bedeutungswandel", "b2": "Begriff der Zeit"}

    def __init__(self, paths: Paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Glossar")
        self.resize(1000, 640)
        self.glossary = Glossary(paths.glossary_file)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.addWidget(label("Ihr Glossar", "h2"))
        lay.addWidget(label("Einträge hier werden bei jeder Übersetzung verbindlich verwendet. Das Glossar bleibt "
                            "auf diesem Rechner; Sie können es exportieren und an Kolleginnen und Kollegen weitergeben.", "muted"))
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, slot in (("Neuer Eintrag", self._add_row), ("Eintrag löschen", self._delete_row),
                           ("Importieren (CSV) …", self._import), ("Exportieren (CSV) …", self._export)):
            b = button(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        save = button("Speichern und schließen", "primary")
        save.clicked.connect(self._save)
        row.addWidget(save)
        lay.addLayout(row)
        for e in self.glossary.all():
            self._add_row(e)

    def _add_row(self, entry: GlossaryEntry | None = None) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        e = entry if isinstance(entry, GlossaryEntry) else GlossaryEntry("", "", "", "", "")
        for c, val in enumerate((e.term, e.translation, e.note)):
            self.table.setItem(r, c, QTableWidgetItem(val))
        cat = QComboBox()
        for k, v in self.CATS.items():
            cat.addItem(v, k)
        cat.setCurrentIndex(max(0, cat.findData(e.category)))
        self.table.setCellWidget(r, 3, cat)
        self.table.setItem(r, 4, QTableWidgetItem(e.period))

    def _delete_row(self) -> None:
        for idx in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(idx)

    def _rows(self) -> list[GlossaryEntry]:
        out = []
        for r in range(self.table.rowCount()):
            def txt(c):
                it = self.table.item(r, c)
                return it.text().strip() if it else ""
            if not txt(0):
                continue
            out.append(GlossaryEntry(txt(0), txt(1), txt(2), self.table.cellWidget(r, 3).currentData(), txt(4)))
        return out

    def _save(self) -> None:
        for e in self.glossary.all():
            self.glossary.remove(e.term, e.period)
        for e in self._rows():
            self.glossary.add(e)
        self.accept()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Glossar exportieren", "Glossar.csv", "CSV (*.csv)")
        if path:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(["begriff", "uebersetzung", "anmerkung", "kategorie", "zeitraum"])
                for e in self._rows():
                    w.writerow([e.term, e.translation, e.note, e.category, e.period])

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Glossar importieren", "", "CSV (*.csv)")
        if not path:
            return
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                self._add_row(GlossaryEntry(row.get("begriff", ""), row.get("uebersetzung", ""), row.get("anmerkung", ""),
                                            row.get("kategorie", ""), row.get("zeitraum", "")))

    def done(self, r):
        self.glossary.close()
        super().done(r)


# --------------------------------------------------------------------------- Deinstallation


class UninstallDialog(QDialog):
    def __init__(self, paths: Paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Alles entfernen")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.addWidget(label("Programm und alle Daten entfernen", "h2"))
        size = folder_size(paths.root)
        lay.addWidget(label(
            f"Entfernt werden alle Sprachmodelle, Wörterbücher und Hilfsprogramme ({format_bytes(size)}) sowie das "
            "Programm selbst. Ihre übersetzten Dokumente bleiben erhalten – sie liegen bei Ihren Quellen."))
        self.backup = QCheckBox("Mein Glossar und meine Korrekturen vorher in »Dokumente« sichern")
        self.backup.setChecked(True)
        lay.addWidget(self.backup)
        row = QHBoxLayout()
        cancel = button("Abbrechen")
        cancel.clicked.connect(self.reject)
        go = button("Alles entfernen", "danger")
        go.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addStretch(1)
        row.addWidget(go)
        lay.addLayout(row)


# --------------------------------------------------------------------------- Einstellungen / Über


class SettingsDialog(QDialog):
    change_profile = Signal()
    uninstall = Signal()
    theme_changed = Signal(str)
    benchmark = Signal()

    def __init__(self, paths: Paths, catalog: Catalog, settings, profile_text: str, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(label("Einstellungen", "h2"))

        f, fl = frame()
        fl.addWidget(label("Quellenprofil", "muted"))
        fl.addWidget(label(profile_text))
        b = button("Profil ändern …")
        b.clicked.connect(lambda: (self.accept(), self.change_profile.emit()))
        fl.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(f)

        f, fl = frame()
        fl.addWidget(label("Modelle", "muted"))
        fl.addWidget(label(f"Übersetzung und Prüfung: {settings.main_model or '–'}\nTexterkennung: {settings.ocr_model or '–'} und Tesseract"))
        lay.addWidget(f)

        f, fl = frame()
        row = QHBoxLayout()
        row.addWidget(label("Darstellung", "muted"), 1)
        theme = QComboBox()
        for key, text in (("system", "wie Windows"), ("hell", "hell"), ("dunkel", "dunkel")):
            theme.addItem(text, key)
        theme.setCurrentIndex(max(0, theme.findData(settings.theme)))
        theme.currentIndexChanged.connect(lambda: self.theme_changed.emit(theme.currentData()))
        row.addWidget(theme)
        fl.addLayout(row)
        lay.addWidget(f)

        row = QHBoxLayout()
        gl = button("Glossar bearbeiten …")
        gl.clicked.connect(lambda: GlossaryDialog(paths, self).exec())
        upd = button("Nach Updates suchen")
        upd.clicked.connect(self._check_updates)
        about = button("Über das Programm")
        about.clicked.connect(lambda: AboutDialog(catalog, self).exec())
        bench = button("Leistungstest")
        bench.setToolTip("Verarbeitet eine eingebaute, erfundene Beispielseite und misst Dauer und Lesegenauigkeit.")
        bench.clicked.connect(lambda: (self.accept(), self.benchmark.emit()))
        row.addWidget(bench)
        row.addWidget(gl)
        row.addWidget(upd)
        row.addWidget(about)
        row.addStretch(1)
        lay.addLayout(row)
        self.update_label = label("", "small")
        lay.addWidget(self.update_label)

        row = QHBoxLayout()
        un = button("Alles entfernen …", "danger")
        un.clicked.connect(lambda: (self.accept(), self.uninstall.emit()))
        close = button("Schließen", "primary")
        close.clicked.connect(self.accept)
        row.addWidget(un)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)

    def _check_updates(self) -> None:
        from quellenuebersetzer.install import update

        self.update_label.setText("Prüfe …")
        self.repaint()
        info = update.check()
        if info.error:
            self.update_label.setText(info.error)
        elif info.newer:
            self.update_label.setText(f"Neue Version {info.latest} verfügbar (installiert: {info.current}). "
                                      f"<a href='{info.url}'>Zur Download-Seite</a>")
            self.update_label.setTextFormat(Qt.TextFormat.RichText)
            self.update_label.setOpenExternalLinks(True)
        else:
            self.update_label.setText(f"Sie haben die aktuelle Version ({info.current}).")


class AboutDialog(QDialog):
    def __init__(self, catalog: Catalog, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Über {APP_NAME}")
        self.resize(760, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.addWidget(label(APP_NAME, "title"))
        lay.addWidget(label(f"Version {__version__} · freie Software unter der GNU General Public License 3.0 oder später", "muted"))
        lay.addWidget(label(
            "Liest und übersetzt historische Quellen vollständig auf dem eigenen Rechner. Während der Verarbeitung "
            "ist jede Netzwerkverbindung nach außen technisch gesperrt. Es gibt keine Telemetrie und keine Konten."))
        lay.addWidget(label("Verwendete Bausteine und Lizenzen", "h2"))
        lst = QListWidget()
        for c in catalog.components.values():
            lst.addItem(f"{c.label} – {c.license}  ({c.license_url})")
        for tag, m in catalog.models.items():
            lst.addItem(f"Modell {m.label} [{tag}] – {m.license}")
        for name, lic in catalog.tessdata_license.items():
            lst.addItem(f"Tesseract-Schriftmodell {name} – {lic}")
        for pack in catalog.languages.values():
            for d in pack.dictionaries:
                lst.addItem(f"Wörterbuch {d.label} – {d.license}; {d.attribution}")
        lst.addItem("Python, PySide6/Qt (LGPL-3.0), OpenCV (Apache-2.0), pypdfium2 (Apache-2.0/BSD), pdfplumber (MIT), "
                    "python-docx (MIT), RapidFuzz (MIT), NumPy (BSD), Pillow (MIT-CMU), psutil (BSD)")
        lay.addWidget(lst, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = button("Schließen", "primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)


class BenchmarkDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Leistungstest")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.addWidget(label("Leistungstest", "h2"))
        lay.addWidget(label("Eine eingebaute, erfundene Beispielseite (Druck mit Tabelle) wird gelesen, übersetzt "
                            "und als DOCX und PDF ausgegeben. Es werden keine eigenen Dokumente verwendet.", "muted"))
        self.status = label("Wird vorbereitet …")
        lay.addWidget(self.status)
        self.report = label("", selectable=True)
        lay.addWidget(self.report)
        row = QHBoxLayout()
        self.open_btn = button("Ergebnis öffnen")
        self.open_btn.setVisible(False)
        self.close_btn = button("Schließen", "primary")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        row.addWidget(self.open_btn)
        row.addStretch(1)
        row.addWidget(self.close_btn)
        lay.addLayout(row)

    def on_result(self, text: str, folder: str) -> None:
        self.status.setText("Fertig.")
        self.report.setText(text)
        self.close_btn.setEnabled(True)
        if folder:
            self.open_btn.setVisible(True)
            self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
