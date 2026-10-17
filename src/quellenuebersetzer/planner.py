"""Aus Profil + Systemprüfung wird ein Installationsplan mit Ampel."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from quellenuebersetzer.catalog import Catalog, Tier
from quellenuebersetzer.hardware import SystemInfo
from quellenuebersetzer.install.manifest import Manifest
from quellenuebersetzer.profile import Profile, SourceKind


class Light(IntEnum):
    GRUEN = 0
    GELB = 1
    ROT = 2

    @property
    def symbol(self) -> str:
        return ("🟢", "🟡", "🔴")[self]

    @property
    def word(self) -> str:
        return ("optimal", "eingeschränkt", "nicht geeignet")[self]


HANDWRITING_WARNING = (
    "Maschinelles Lesen historischer Handschrift ist nach dem heutigen Stand der Technik "
    "chronisch unzuverlässig. Das Ergebnis ist immer nur eine Rohfassung mit Fehlern, "
    "auch an Stellen, die nicht markiert sind. Es ersetzt keine qualifizierte menschliche "
    "Transkription und Übersetzung."
)

GENERAL_DISCLAIMER = (
    "Maschinelle Übersetzung – besonders bei historischen und entlegenen Quellen – ersetzt "
    "keine qualifizierte menschliche Übersetzung. Markierte Stellen bitte am Original prüfen."
)

# Geschätzter Platzbedarf nach dem Entpacken im Verhältnis zur Downloadgröße.
_EXTRACT_FACTOR = {"ollama": 2.5}
_DEFAULT_EXTRACT_FACTOR = 4.0
_RESERVE_BYTES = 3 * 1024**3


@dataclass
class PlanItem:
    kind: str  # component | tessdata | model | dictionary
    id: str
    label: str
    size: int
    license: str
    installed: bool = False
    note: str = ""


@dataclass
class KindAssessment:
    kind: SourceKind
    light: Light
    text: str


MODES = {"schnell": "Schnell", "gruendlich": "Gründlich"}


@dataclass
class Plan:
    tier: Tier
    hardware_optimal: bool
    overall: Light
    items: list[PlanItem]
    assessments: list[KindAssessment]
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    disk_needed_bytes: int = 0
    mode: str = "schnell"
    main_model: str = ""
    tier_count: int = 5

    @property
    def to_install(self) -> list[PlanItem]:
        return [i for i in self.items if not i.installed]

    @property
    def download_bytes(self) -> int:
        return sum(i.size for i in self.to_install)

    @property
    def can_install(self) -> bool:
        return not self.blockers


def _assess(kind: SourceKind, quality: int) -> KindAssessment:
    n = quality
    if kind in (SourceKind.DRUCK, SourceKind.SCHREIBMASCHINE):
        if n <= 3:
            return KindAssessment(kind, Light.GRUEN, "Zuverlässige Erkennung mit Gegenprüfung.")
        if n == 4:
            return KindAssessment(kind, Light.GELB, "Gute Erkennung, kleineres Prüfmodell.")
        return KindAssessment(kind, Light.GELB, "Funktioniert, aber sehr langsam (ohne Grafikkarte).")
    if kind == SourceKind.TABELLEN:
        if n <= 3:
            return KindAssessment(kind, Light.GRUEN, "Tabellen mit Gitterstruktur werden zellweise gelesen.")
        return KindAssessment(kind, Light.GELB, "Einfache Tabellen gut, komplexe Tabellen mit mehr Markierungen.")
    if kind == SourceKind.ALTDRUCK:
        if n <= 2:
            return KindAssessment(kind, Light.GRUEN, "Doppelte Lesung, Abweichungen werden markiert.")
        if n <= 4:
            return KindAssessment(kind, Light.GELB, "Doppelte Lesung mit kleinerem Modell, mehr Markierungen.")
        return KindAssessment(kind, Light.GELB, "Nur einfache Lesung, langsam, viele Markierungen.")
    # Handschrift: nie „optimal“
    if n == 1:
        return KindAssessment(kind, Light.GELB, "Bestmögliche Rohfassung auf diesem Rechner – trotzdem unzuverlässig.")
    if n <= 3:
        return KindAssessment(kind, Light.GELB, "Rohfassung mit deutlich mehr Fehlern als auf stärkeren Rechnern.")
    return KindAssessment(kind, Light.ROT, "Für Handschrift nicht empfohlen: Ergebnisse wären überwiegend unbrauchbar.")


def build_plan(profile: Profile, info: SystemInfo, catalog: Catalog, manifest: Manifest, mode: str = "schnell",
               tier_key: str | None = None) -> Plan:
    tier = next((t for t in catalog.tiers if t.key == tier_key), None) or catalog.tier_for_vram(info.usable_vram_gb)
    items: list[PlanItem] = []
    blockers: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []

    main_model, quality = tier.main, tier.quality
    if not tier.gruendlich:
        mode = "schnell"
    elif mode == "gruendlich":
        if info.ram_gb + 0.5 >= tier.gruendlich.get("min_ram_gb", 16):
            main_model, quality = tier.gruendlich["main"], tier.gruendlich.get("quality", quality)
            if info.ram_gb < 24:
                notes.append("Modus „Gründlich“: Das Sprachmodell wird zwischen Grafikkarte und Arbeitsspeicher "
                             "aufgeteilt. Bitte während der Verarbeitung keine großen Programme (Spiele, viele "
                             "Browserfenster) nebenher laufen lassen.")
        else:
            mode = "schnell"
            notes.append(f"Für den Modus „Gründlich“ werden mindestens {tier.gruendlich.get('min_ram_gb', 16)} GB "
                         f"Arbeitsspeicher benötigt (vorhanden: {info.ram_gb:.0f} GB). Es wird „Schnell“ verwendet.")

    def add_component(cid: str) -> None:
        if any(i.kind == "component" and i.id == cid for i in items):
            return
        comp = catalog.components[cid]
        for dep in comp.requires:
            add_component(dep)
        items.append(
            PlanItem(
                "component",
                cid,
                comp.label,
                comp.download_size,
                comp.license,
                installed=manifest.has("component", cid, comp.files[0].sha256),
                note=comp.purpose,
            )
        )

    for cid in ("ollama", "tesseract", "pandoc", "typst", "layout"):
        add_component(cid)

    lang = catalog.languages.get(profile.language)
    if lang is None:
        blockers.append("Für die gewählte Sprache gibt es noch kein Sprachpaket.")
    else:
        wanted: list[str] = []
        for kind in profile.kinds:
            for t in lang.tesseract_langs_for(kind.value):
                if t not in wanted:
                    wanted.append(t)
        for t in lang.tesseract.get("zusatz", []):
            if t not in wanted:
                wanted.append(t)
        for t in wanted:
            spec = catalog.tessdata[t]
            items.append(
                PlanItem(
                    "tessdata",
                    t,
                    f"Schriftmodell „{t}“ für die Texterkennung",
                    spec.size,
                    catalog.tessdata_license.get(t, ""),
                    installed=manifest.has("tessdata", t, spec.sha256),
                )
            )

        for d in lang.dictionaries:
            if not set(d.periods) & set(profile.periods):
                continue
            if d.bundled:
                items.append(PlanItem("dictionary", d.id, d.label, 0, d.license, True, "mitgeliefert"))
            elif d.available:
                items.append(
                    PlanItem("dictionary", d.id, d.label, d.size or 0, d.license, manifest.has("dictionary", d.id, d.sha256), d.purpose)
                )
            else:
                notes.append(f"Wörterbuch „{d.label}“ wird in einer späteren Version nachgeliefert.")

    for tag in dict.fromkeys((main_model, tier.ocr)):
        m = catalog.models[tag]
        items.append(PlanItem("model", tag, m.label, m.size, m.license, manifest.has("model", tag)))

    # --- Blocker und Hinweise
    if not info.os_supported:
        blockers.append("Benötigt wird Windows 10 (Version 22H2) oder Windows 11.")
    if info.ram_gb < 8:
        blockers.append(f"Mindestens 8 GB Arbeitsspeicher nötig (vorhanden: {info.ram_gb:.0f} GB).")

    to_install = [i for i in items if not i.installed]
    disk = _RESERVE_BYTES
    for i in to_install:
        factor = 1.0 if i.kind in ("model", "tessdata", "dictionary") else _EXTRACT_FACTOR.get(i.id, _DEFAULT_EXTRACT_FACTOR)
        disk += int(i.size * factor)
    if info.free_disk_gb * 1024**3 < disk:
        blockers.append(
            f"Zu wenig freier Speicherplatz: benötigt etwa {disk / 1024**3:.0f} GB, frei sind {info.free_disk_gb:.0f} GB."
        )

    gpu = info.best_gpu
    if info.driver_too_old and gpu:
        notes.append(
            f"Der Grafikkartentreiber ({gpu.driver}) ist zu alt. Nach einer Treiber-Aktualisierung "
            "(nvidia.de → Treiber) kann eine bessere Stufe genutzt werden."
        )
    elif gpu and not gpu.is_nvidia:
        notes.append(f"Keine NVIDIA-Grafikkarte gefunden ({gpu.name}). Die Modelle laufen auf dem Prozessor und sind langsam.")
    elif not gpu:
        notes.append("Keine Grafikkarte erkannt. Die Modelle laufen auf dem Prozessor und sind langsam.")
    if info.existing_ollama:
        notes.append("Ein bereits installiertes Ollama wurde gefunden. Es bleibt unverändert; dieses Programm nutzt eine eigene Kopie.")

    assessments = [_assess(k, quality) for k in profile.kinds]
    if profile.has_handwriting:
        warnings.append(HANDWRITING_WARNING)

    overall = Light.ROT if blockers else max((a.light for a in assessments), default=Light.GRUEN)
    return Plan(
        tier=tier,
        hardware_optimal=tier.number == 1 and not blockers,
        overall=overall,
        items=items,
        assessments=assessments,
        blockers=blockers,
        notes=notes,
        warnings=warnings,
        disk_needed_bytes=disk,
        mode=mode,
        main_model=main_model,
        tier_count=len(catalog.tiers),
    )


def format_bytes(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.1f} GB".replace(".", ",")
    if n >= 1024**2:
        return f"{n / 1024**2:.0f} MB"
    return f"{max(n, 0) / 1024:.0f} KB"


def estimate_minutes(download_bytes: int, mbit_per_s: float = 50.0) -> int:
    seconds = download_bytes * 8 / (mbit_per_s * 1_000_000)
    return max(1, round(seconds / 60))
