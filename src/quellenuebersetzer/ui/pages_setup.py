"""Einrichtung: Profil → Systemprüfung und Plan → Installation."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from quellenuebersetzer.config import APP_NAME
from quellenuebersetzer.hardware import SystemInfo
from quellenuebersetzer.install.installer import Progress
from quellenuebersetzer.planner import HANDWRITING_WARNING, Light, Plan, estimate_minutes, format_bytes
from quellenuebersetzer.profile import LANGUAGES, PERIODS, Profile, SourceKind
from quellenuebersetzer.ui.widgets import Page, button, clear_layout, frame, hrow, label, message_box

KIND_SYMBOLS = {
    SourceKind.DRUCK: "📖",
    SourceKind.ALTDRUCK: "📜",
    SourceKind.SCHREIBMASCHINE: "⌨",
    SourceKind.HANDSCHRIFT: "✒",
    SourceKind.TABELLEN: "▦",
}


class ProfilePage(Page):
    submitted = Signal(object)  # Profile

    def __init__(self, profile: Profile | None = None, first_run: bool = True):
        super().__init__()
        self.kind_buttons: dict[SourceKind, QPushButton] = {}
        self.period_buttons: dict[str, QPushButton] = {}

        self.body.addWidget(label(f"Willkommen beim {APP_NAME}" if first_run else "Quellenprofil ändern", "title"))
        self.body.addWidget(label(
            "Dieses Programm liest und übersetzt historische Quellen vollständig auf Ihrem Rechner. "
            "Ihre Dokumente verlassen das Gerät nicht. Beantworten Sie drei kurze Fragen – "
            "danach wird alles Nötige automatisch eingerichtet.", "muted"))

        # 1. Quellenart
        self.body.addWidget(label("1  Welche Quellen haben Sie?", "h2"))
        self.body.addWidget(label("Mehrfachauswahl möglich.", "small"))
        grid = QGridLayout()
        grid.setSpacing(10)
        for i, kind in enumerate(SourceKind):
            b = button(f"{KIND_SYMBOLS[kind]}   {kind.label}\n      {kind.hint}", "choice", checkable=True)
            b.setMinimumHeight(64)
            b.toggled.connect(self._changed)
            self.kind_buttons[kind] = b
            grid.addWidget(b, i // 2, i % 2)
        self.body.addLayout(grid)

        self.hw_warning = message_box("warning", "Wichtiger Hinweis zu Handschriften", HANDWRITING_WARNING)
        self.hw_warning.setVisible(False)
        self.body.addWidget(self.hw_warning)

        # 2. Sprache
        self.body.addWidget(label("2  In welcher Sprache sind die Quellen?", "h2"))
        self.language = QComboBox()
        for lang in LANGUAGES:
            self.language.addItem(lang.label, lang.code)
        self.language.setMaximumWidth(320)
        self.body.addWidget(self.language)
        self.body.addWidget(label("Übersetzt wird ins Deutsche. Weitere Ausgangssprachen folgen.", "small"))

        # 3. Zeitraum
        self.body.addWidget(label("3  Aus welcher Zeit stammen sie?", "h2"))
        self.body.addWidget(label("Mehrfachauswahl möglich. Der Zeitraum bestimmt die historischen Wörterbücher "
                                  "und wie Begriffe gedeutet werden.", "small"))
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for p in PERIODS:
            b = button(p.label, "chip", checkable=True)
            b.toggled.connect(self._changed)
            self.period_buttons[p.key] = b
            chips.addWidget(b)
        chips.addStretch(1)
        self.body.addLayout(chips)
        self.body.addStretch(1)

        self.next_button = button("Rechner prüfen  →", "primary")
        self.next_button.clicked.connect(self._submit)
        self.hint = label("Bitte mindestens eine Quellenart und einen Zeitraum wählen.", "small")
        self.footer.addWidget(self.hint)
        self.footer.addStretch(1)
        self.footer.addWidget(self.next_button)

        if profile:
            for k in profile.kinds:
                self.kind_buttons[k].setChecked(True)
            for p in profile.periods:
                if p in self.period_buttons:
                    self.period_buttons[p].setChecked(True)
            idx = self.language.findData(profile.language)
            if idx >= 0:
                self.language.setCurrentIndex(idx)
        self._changed()

    def profile(self) -> Profile:
        return Profile(
            kinds=[k for k, b in self.kind_buttons.items() if b.isChecked()],
            language=self.language.currentData(),
            periods=[k for k, b in self.period_buttons.items() if b.isChecked()],
        )

    def _changed(self, *_args) -> None:
        p = self.profile()
        self.hw_warning.setVisible(p.has_handwriting)
        self.next_button.setEnabled(p.is_valid)
        self.hint.setVisible(not p.is_valid)

    def _submit(self) -> None:
        if self.profile().is_valid:
            self.submitted.emit(self.profile())


class CheckingPage(Page):
    def __init__(self, title: str = "Ihr Rechner wird geprüft …",
                 text: str = "Grafikkarte, Arbeitsspeicher und freier Speicherplatz werden ermittelt."):
        super().__init__()
        self.body.addStretch(1)
        self.body.addWidget(label(title, "title"), alignment=Qt.AlignmentFlag.AlignHCenter)
        self.body.addWidget(label(text, "muted"), alignment=Qt.AlignmentFlag.AlignHCenter)
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setMaximumWidth(420)
        self.body.addWidget(bar, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.body.addStretch(2)


class PlanPage(Page):
    back = Signal()
    install = Signal(object)  # Plan
    mode_changed = Signal(str)

    def __init__(self, title: str = "Ihr Installationsplan"):
        super().__init__()
        self.page_title = title
        self.plan: Plan | None = None
        self.back_button = button("←  Zurück")
        self.back_button.clicked.connect(self.back.emit)
        self.install_button = button("Installieren", "primary")
        self.install_button.clicked.connect(lambda: self.plan and self.install.emit(self.plan))
        self.footer.addWidget(self.back_button)
        self.footer.addStretch(1)
        self.footer.addWidget(self.install_button)

    def show_plan(self, plan: Plan, info: SystemInfo) -> None:
        self.plan = plan
        self.clear_body()
        b = self.body
        b.addWidget(label(self.page_title, "title"))
        if self.page_title != "Ihr Installationsplan":
            b.addWidget(label("Seit der letzten Einrichtung fehlen Bausteine oder es gibt neue Versionen. "
                              "Es wird nur das Fehlende geladen; alles Vorhandene bleibt erhalten.", "muted"))

        # Gesamturteil
        role = {Light.GRUEN: "ok", Light.GELB: "caution", Light.ROT: "warning"}[plan.overall]
        optimal = "Ja" if plan.hardware_optimal else "Nein"
        head = f"{plan.overall.symbol}  Optimal für diesen Rechner: {optimal}"
        f, lay = frame(role)
        t = label(head)
        t.setStyleSheet("font-size: 14pt; font-weight: 700;")
        lay.addWidget(t)
        lay.addWidget(label(f"Ausstattungsstufe {plan.tier.number} von {plan.tier_count} – {plan.tier.label}"))
        if not plan.hardware_optimal and not plan.blockers:
            lay.addWidget(label("Die bestmögliche Stufe benötigt eine NVIDIA-Grafikkarte mit 24 GB Grafikspeicher. "
                                "Das Programm funktioniert trotzdem – mit kleineren Modellen.", "small"))
        b.addWidget(f)

        # Modus (nur bei Stufen mit Wahlmöglichkeit)
        if plan.tier.gruendlich:
            f, lay = frame()
            lay.addWidget(label("Wie soll übersetzt werden?", "h2"))
            group = QButtonGroup(f)
            for key, title, text in (
                ("schnell", "Schnell", "Kleineres Sprachmodell, läuft fast ganz auf der Grafikkarte. Ordentliche "
                 "Qualität, gut zum Ausprobieren und für größere Mengen."),
                ("gruendlich", "Gründlich", "Das schnelle Modell übersetzt alles, ein größeres Modell (aufgeteilt auf "
                 "Grafikkarte und Arbeitsspeicher) überarbeitet die schwierigen Stellen: Tabellen, unsichere "
                 "Lesungen, Begriffe der Zeit. Bessere Übersetzung, langsamer – gut für Bücher über Nacht."),
            ):
                rb = QRadioButton(title)
                rb.setStyleSheet("font-weight: 600;")
                rb.setChecked(plan.mode == key)
                rb.toggled.connect(lambda on, k=key: on and k != plan.mode and self.mode_changed.emit(k))
                group.addButton(rb)
                lay.addWidget(rb)
                hint = label(text, "muted")
                hint.setContentsMargins(30, 0, 0, 6)
                lay.addWidget(hint)
            lay.addWidget(label("Der Modus lässt sich später unter Einstellungen ändern.", "small"))
            b.addWidget(f)

        # Rechner
        gpu = info.best_gpu
        gpu_txt = f"{gpu.name} ({gpu.vram_gb:.0f} GB)" if gpu else "keine erkannt"
        f, lay = frame()
        lay.addWidget(label("Ihr Rechner", "h2"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        for r, (k, v) in enumerate([
            ("Betriebssystem", info.os_name), ("Grafikkarte", gpu_txt),
            ("Arbeitsspeicher", f"{info.ram_gb:.0f} GB"), ("Freier Speicherplatz", f"{info.free_disk_gb:.0f} GB"),
        ]):
            grid.addWidget(label(k, "muted"), r, 0)
            grid.addWidget(label(v), r, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        b.addWidget(f)

        # Je Quellenart
        f, lay = frame()
        lay.addWidget(label("Was Sie erwarten können", "h2"))
        for a in plan.assessments:
            row = QHBoxLayout()
            sym = QLabel(a.light.symbol)
            sym.setFixedWidth(26)
            row.addWidget(sym, 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(0)
            name = label(a.kind.label)
            name.setStyleSheet("font-weight: 600;")
            col.addWidget(name)
            col.addWidget(label(a.text, "muted"))
            row.addLayout(col, 1)
            lay.addLayout(row)
        b.addWidget(f)

        for w in plan.warnings:
            b.addWidget(message_box("warning", "Handschriften: bitte unbedingt beachten", w))
        for blk in plan.blockers:
            b.addWidget(message_box("warning", "Installation nicht möglich", blk))
        for n in plan.notes:
            b.addWidget(message_box("caution", "Hinweis", n))

        # Bausteine
        f, lay = frame()
        lay.addWidget(label("Was installiert wird", "h2"))
        todo = plan.to_install
        if not todo:
            lay.addWidget(label("Alles ist bereits installiert.", "muted"))
        for item in plan.items:
            row = QHBoxLayout()
            state = ("✓ " + item.note) if item.note == "mitgeliefert" else ("✓ vorhanden" if item.installed else format_bytes(item.size))
            name = label(item.label)
            row.addWidget(name, 1)
            row.addWidget(label(state, "muted"))
            lay.addLayout(row)
        total = plan.download_bytes
        summary = label(
            f"Download insgesamt: {format_bytes(total)} · Dauer etwa {estimate_minutes(total)} Minuten "
            f"(bei 50 Mbit/s) · benötigter Speicherplatz etwa {format_bytes(plan.disk_needed_bytes)}"
        )
        summary.setStyleSheet("font-weight: 600; margin-top: 6px;")
        lay.addWidget(summary)
        lay.addWidget(label("Alle Bausteine sind kostenlos und quelloffen. Sie werden direkt von den offiziellen "
                            "Quellen geladen und vor der Verwendung auf Echtheit geprüft (Prüfsumme). "
                            "Alles wird in einem einzigen Ordner abgelegt und lässt sich mit einem Klick wieder entfernen.",
                            "small"))
        b.addWidget(f)
        b.addStretch(1)

        self.install_button.setEnabled(plan.can_install)
        self.install_button.setText(("Ergänzen" if self.page_title != "Ihr Installationsplan" else "Installieren")
                                    if todo else "Weiter")


class InstallPage(Page):
    cancel = Signal()
    finished = Signal()
    retry = Signal()

    def __init__(self, title: str = "Einrichtung läuft"):
        super().__init__()
        self.body.addWidget(label(title, "title"))
        self.body.addWidget(label("Sie können den Rechner währenddessen weiter benutzen. Bei einem Abbruch "
                                  "(z. B. Internet weg) wird beim nächsten Start an derselben Stelle fortgesetzt.", "muted"))
        f, lay = frame()
        self.step_label = label("Vorbereitung …")
        self.step_label.setStyleSheet("font-size: 12.5pt; font-weight: 600;")
        lay.addWidget(self.step_label)
        self.item_bar = QProgressBar()
        self.item_bar.setRange(0, 1000)
        lay.addWidget(self.item_bar)
        self.detail = label("", "small")
        lay.addWidget(self.detail)
        lay.addSpacing(8)
        lay.addWidget(label("Gesamtfortschritt", "muted"))
        self.total_bar = QProgressBar()
        self.total_bar.setRange(0, 1000)
        lay.addWidget(self.total_bar)
        self.body.addWidget(f)
        self.result_holder = QVBoxLayout()
        self.body.addLayout(self.result_holder)
        self.body.addStretch(1)

        self.cancel_button = button("Abbrechen")
        self.cancel_button.clicked.connect(self.cancel.emit)
        self.done_button = button("Los geht's  →", "primary")
        self.done_button.clicked.connect(self.finished.emit)
        self.done_button.setVisible(False)
        self.retry_button = button("Erneut versuchen", "primary")
        self.retry_button.clicked.connect(self.retry.emit)
        self.retry_button.setVisible(False)
        self.footer.addWidget(self.cancel_button)
        self.footer.addStretch(1)
        self.footer.addWidget(self.retry_button)
        self.footer.addWidget(self.done_button)

    def reset(self) -> None:
        clear_layout(self.result_holder)
        self.cancel_button.setVisible(True)
        self.cancel_button.setEnabled(True)
        self.done_button.setVisible(False)
        self.retry_button.setVisible(False)
        self.item_bar.setValue(0)
        self.total_bar.setValue(0)
        self.step_label.setText("Vorbereitung …")
        self.detail.setText("")

    def on_progress(self, p: Progress) -> None:
        self.step_label.setText(f"Schritt {p.step} von {p.steps}: {p.label}")
        self.item_bar.setValue(int(p.fraction * 1000))
        if p.total:
            self.detail.setText(f"{format_bytes(p.done)} von {format_bytes(p.total)}")
        else:
            self.detail.setText(p.status or "")
        overall = ((p.step - 1) + p.fraction) / max(1, p.steps)
        self.total_bar.setValue(int(overall * 1000))

    def on_done(self, msg: str) -> None:
        self.total_bar.setValue(1000)
        self.item_bar.setValue(1000)
        self.step_label.setText("Einrichtung abgeschlossen")
        self.detail.setText("")
        self.result_holder.addWidget(message_box("ok", "Alles bereit", msg + " Sie können jetzt Quellen übersetzen."))
        self.cancel_button.setVisible(False)
        self.done_button.setVisible(True)

    def on_failed(self, msg: str) -> None:
        self.result_holder.addWidget(message_box("warning", "Einrichtung nicht abgeschlossen", msg))
        self.cancel_button.setVisible(False)
        self.retry_button.setVisible(True)
