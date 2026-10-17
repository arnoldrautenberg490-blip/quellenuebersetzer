"""Restlose Entfernung aller Programmdaten – auf Wunsch mit Sicherung der eigenen Arbeit."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from quellenuebersetzer.config import APP_ID, Paths


def folder_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


def documents_dir() -> Path:
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5 (Eigene Dokumente, auch bei umgeleitetem Ordner)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:
                return Path(buf.value)
        except OSError:
            pass
    return Path.home() / "Documents"


def backup_user_work(paths: Paths) -> Path | None:
    """Sichert Glossar und Korrekturen in »Dokumente«, bevor gelöscht wird."""
    items = [p for p in (paths.glossary_file, paths.corrections) if p.exists()]
    if not items:
        return None
    dest = documents_dir() / f"{APP_ID}-Sicherung-{time.strftime('%Y-%m-%d_%H%M')}"
    dest.mkdir(parents=True, exist_ok=True)
    for p in items:
        if p.is_dir():
            shutil.copytree(p, dest / p.name, dirs_exist_ok=True)
        else:
            shutil.copy2(p, dest / p.name)
    return dest


def _kill_own_ollama(paths: Paths) -> None:
    """Beendet nur die programmeigene Ollama-Instanz (erkennbar am Pfad), nie eine fremde."""
    try:
        import psutil
    except ImportError:
        return
    own = (paths.runtime / "ollama").resolve()
    for proc in psutil.process_iter(["exe"]):
        try:
            exe = proc.info.get("exe")
            if exe and own in Path(exe).resolve().parents:
                proc.terminate()
                proc.wait(timeout=10)
        except (psutil.Error, OSError):
            continue


def remove_all_data(paths: Paths, backup: bool = True) -> Path | None:
    backup_dir = backup_user_work(paths) if backup else None
    _kill_own_ollama(paths)
    root = paths.root
    if root.exists():
        # Sicherheitsnetz: nur einen Ordner löschen, der eindeutig uns gehört.
        explicit = os.environ.get("QUE_DATA_DIR")
        if APP_ID.lower() not in root.name.lower() and not (explicit and Path(explicit) == root):
            raise RuntimeError(f"Unerwarteter Datenordner, Löschen abgebrochen: {root}")
        for attempt in range(5):
            try:
                shutil.rmtree(root)
                break
            except OSError:
                time.sleep(1 + attempt)
        else:
            shutil.rmtree(root, ignore_errors=True)
    return backup_dir


def program_uninstaller() -> Path | None:
    """Pfad zum Inno-Setup-Deinstallationsprogramm (nur in der installierten Fassung vorhanden)."""
    if not getattr(sys, "frozen", False):
        return None
    candidates = sorted(Path(sys.executable).parent.glob("unins*.exe"))
    return candidates[0] if candidates else None


def launch_program_uninstaller() -> bool:
    unins = program_uninstaller()
    if not unins:
        return False
    subprocess.Popen([str(unins), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], close_fds=True)
    return True
