"""Pfade und gespeicherte Einstellungen.

Alle Daten des Programms liegen unter einem einzigen Wurzelordner, damit die
Deinstallation sie vollständig entfernen kann. Der Ordner wird bewusst so
gewählt, dass sein Pfad nur ASCII-Zeichen enthält – einige Bausteine
(Tesseract, ältere DLLs) scheitern an Umlauten im Pfad.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "Quellenübersetzer"
APP_ID = "Quellenuebersetzer"

# Eigener Port, damit ein bereits installiertes Ollama (Standard 11434) nicht gestört wird.
OLLAMA_PORT = 11535

# Unterordner, die zur Laufzeit befüllt werden. Die Deinstallation entfernt genau diese.
DATA_SUBDIRS = ("runtime", "models", "dict", "cache", "logs")


def _is_ascii(text: str) -> bool:
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _short_path(path: str) -> str | None:
    """8.3-Kurzpfad unter Windows (enthält nur ASCII), sofern verfügbar."""
    if sys.platform != "win32":
        return None
    buf = ctypes.create_unicode_buffer(32768)
    n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf))
    if n and _is_ascii(buf.value):
        return buf.value
    return None


def data_root() -> Path:
    """Wurzelordner für alle Programmdaten (ASCII-Pfad)."""
    override = os.environ.get("QUE_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    if _is_ascii(base):
        return Path(base) / APP_ID
    short = _short_path(base)
    if short:
        return Path(short) / APP_ID
    drive = os.environ.get("SystemDrive", "C:")
    return Path(drive + "\\") / f"{APP_ID}-Daten"


def resources_dir() -> Path:
    """Mitgelieferte Ressourcen (auch im PyInstaller-Paket)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "quellenuebersetzer" / "resources"
    return Path(__file__).parent / "resources"


class Paths:
    def __init__(self, root: Path | None = None):
        self.root = root or data_root()

    @property
    def runtime(self) -> Path:
        return self.root / "runtime"

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def dicts(self) -> Path:
        return self.root / "dict"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def settings_file(self) -> Path:
        return self.root / "settings.json"

    @property
    def manifest_file(self) -> Path:
        return self.root / "installiert.json"

    @property
    def glossary_file(self) -> Path:
        return self.root / "glossar.sqlite"

    @property
    def corrections(self) -> Path:
        """Vom Nutzer bestätigte Lesungen (Grundlage für späteres Training)."""
        return self.root / "korrekturen"

    def ensure(self) -> None:
        for sub in DATA_SUBDIRS:
            (self.root / sub).mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    profile: dict | None = None
    formats: list[str] = field(default_factory=lambda: ["docx", "pdf"])
    review_mode: str = "auto"  # auto | immer | nie
    last_source_kind: str | None = None
    last_path: str = ""
    theme: str = "system"  # system | hell | dunkel
    setup_complete: bool = False
    main_model: str = ""
    ocr_model: str = ""
    tier: str = ""
    mode: str = "schnell"  # schnell | gruendlich
    layout: str = "faksimile"  # faksimile | neusatz | fliesstext
    gpu_name: str = ""
    vram_gb: float = 0.0

    @classmethod
    def load(cls, paths: Paths) -> "Settings":
        try:
            data = json.loads(paths.settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, paths: Paths) -> None:
        paths.root.mkdir(parents=True, exist_ok=True)
        tmp = paths.settings_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(paths.settings_file)
