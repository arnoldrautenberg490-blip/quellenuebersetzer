"""Programmstart."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def main() -> None:
    from quellenuebersetzer.config import APP_ID, APP_NAME, Paths, Settings

    paths = Paths()

    # Aufruf durch das Deinstallationsprogramm (Inno Setup): Daten entfernen, Glossar sichern, ohne Oberfläche.
    if "--daten-entfernen" in sys.argv:
        from quellenuebersetzer.install.uninstall import remove_all_data

        try:
            remove_all_data(paths, backup="--ohne-sicherung" not in sys.argv)
        except Exception:  # noqa: BLE001 – die Deinstallation darf nie mit einem Fehlerfenster hängen bleiben
            import tempfile
            import traceback

            with open(Path(tempfile.gettempdir()) / f"{APP_ID}-deinstallation.log", "a", encoding="utf-8") as fh:
                fh.write(traceback.format_exc())
        return

    # Startprüfung für den automatischen Bau: alle Module und Ressourcen laden, dann beenden.
    if "--pruefen" in sys.argv:
        _smoke_test()
        return

    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)  # eigenes Taskleistensymbol

    from PySide6.QtWidgets import QApplication

    from quellenuebersetzer.ui import theme
    from quellenuebersetzer.ui.main_window import MainWindow

    paths.ensure()
    # Reste abgebrochener Verarbeitungen (Seitenbilder) sofort entfernen – Datenschutz.
    shutil.rmtree(paths.cache / "jobs", ignore_errors=True)
    shutil.rmtree(paths.cache / "export", ignore_errors=True)
    shutil.rmtree(paths.cache / "vorschau", ignore_errors=True)
    from quellenuebersetzer.pipeline.runner import cleanup_stale_books

    cleanup_stale_books(paths)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ID)
    settings = Settings.load(paths)
    tokens = theme.apply(app, settings.theme)
    win = MainWindow(paths, settings, tokens)
    win.show()
    sys.exit(app.exec())


def _smoke_test() -> None:
    import importlib
    import pkgutil

    import quellenuebersetzer
    from quellenuebersetzer.catalog import load_catalog
    from quellenuebersetzer.config import resources_dir

    for mod in pkgutil.walk_packages(quellenuebersetzer.__path__, "quellenuebersetzer."):
        importlib.import_module(mod.name)
    cat = load_catalog()
    assert cat.tiers and "pl" in cat.languages
    for f in ("export/markierungen.lua", "export/referenz.docx", "export/epub.css", "icon.png", "ui/haken.svg"):
        assert (resources_dir() / f).exists(), f
    import cv2, pypdfium2, pdfplumber, docx, rapidfuzz, onnxruntime  # noqa: F401,E401
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["pruefen", "-platform", "offscreen"])
    from quellenuebersetzer.ui import theme

    theme.apply(app, "hell")
    print("Startprüfung bestanden")


if __name__ == "__main__":
    main()
