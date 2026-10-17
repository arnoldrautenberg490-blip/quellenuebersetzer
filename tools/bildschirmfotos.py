"""Erzeugt Bildschirmfotos der wichtigsten Seiten mit Beispieldaten (für Abstimmung und Dokumentation).

Aufruf: python tools/bildschirmfotos.py <zielordner> [hell|dunkel]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from quellenuebersetzer.catalog import load_catalog  # noqa: E402
from quellenuebersetzer.config import Paths  # noqa: E402
from quellenuebersetzer.hardware import Gpu, SystemInfo  # noqa: E402
from quellenuebersetzer.install.installer import Progress  # noqa: E402
from quellenuebersetzer.install.manifest import Manifest  # noqa: E402
from quellenuebersetzer.pipeline.document import PageImage, SourceDocument  # noqa: E402
from quellenuebersetzer.pipeline.runner import Event  # noqa: E402
from quellenuebersetzer.planner import build_plan  # noqa: E402
from quellenuebersetzer.profile import Profile, SourceKind  # noqa: E402
from quellenuebersetzer.ui import theme  # noqa: E402
from quellenuebersetzer.ui.dialogs import ReviewDialog  # noqa: E402
from quellenuebersetzer.ui.page_main import MainPage  # noqa: E402
from quellenuebersetzer.ui.pages_setup import InstallPage, PlanPage, ProfilePage  # noqa: E402


def main(out: Path, mode: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    tokens = theme.apply(app, mode)
    tmp = out / "_daten"
    paths = Paths(tmp)
    size = (1080, 860)

    def shot(widget, name):
        widget.resize(*size)
        widget.grab().save(str(out / f"{name}-{mode}.png"))

    profile = Profile([SourceKind.DRUCK, SourceKind.TABELLEN, SourceKind.HANDSCHRIFT], "pl", ["18jh", "19jh"])
    p = ProfilePage(profile)
    shot(p, "1-profil")

    info = SystemInfo("Windows 11", 26100, 15.9, 412.0, [Gpu("NVIDIA GeForce GTX 1660 Ti", "NVIDIA", 6.0, "566.36")],
                      "Intel Core i7", 6)
    plan = build_plan(profile, info, load_catalog(), Manifest(paths))
    pp = PlanPage()
    pp.show_plan(plan, info)
    shot(pp, "2-plan")

    ip = InstallPage()
    ip.on_progress(Progress(5, 9, "Modell-Laufzeit (Ollama 0.40.5)", 612_000_000, 1_471_226_485))
    shot(ip, "3-installation")

    mp = MainPage(profile, ["docx", "pdf"], "druck", "auto")
    mp.path_edit.setText(str(Path(__file__).resolve().parents[1] / "tests"))
    mp.set_running(True)
    mp.on_event(Event("datei", "", "Akte 1785.pdf", 2, 5))
    mp.on_event(Event("schritt", "Seiten 1–12 von 48 werden gelesen", fraction=0.18))
    mp.on_event(Event("fertig", outputs=[Path("Akte 1784 – Übersetzung.docx"), Path("Akte 1784 – Übersetzung.pdf")]))
    mp.on_event(Event("hinweis", "Seite 7: Tabelle ohne Gitterlinien aus dem Bild gelesen – Werte bitte prüfen."))
    shot(mp, "4-hauptfenster")

    sample = (
        "<!-- Seite 1 -->\n\n## PRZYWILEJ CECHOWY\n\n"
        "Starosta grodowy zatwierdził przywilej dla cechu "
        '[młynarzy]{.a lesarten="młynarzy|mlynarzy" sicher="0.55"} i nakazał, aby każdy '
        '[młyn]{.a lesarten="młyn|mur" sicher="0.48"} płacił dwa złote rocznie.\n'
    )
    tmp.mkdir(parents=True, exist_ok=True)
    page_img = tmp / "seite.png"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from conftest import make_text_page  # noqa: E402

    make_text_page(page_img)
    doc = SourceDocument(page_img, "Akte", "scan", "druck", pages=[PageImage(1, page_img)])
    rd = ReviewDialog(doc, sample, tokens)
    rd.resize(1300, 820)
    rd.grab().save(str(out / f"5-kontrollansicht-{mode}.png"))
    print("gespeichert in", out)


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "hell")
