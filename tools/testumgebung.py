"""Richtet eine Testumgebung mit echtem Tesseract, Pandoc und Typst ein (für pytest und den automatischen Bau).

  python tools/testumgebung.py <zielordner>
  danach: set QUE_TEST_ROOT=<zielordner> und pytest
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quellenuebersetzer.catalog import load_catalog  # noqa: E402
from quellenuebersetzer.config import Paths  # noqa: E402
from quellenuebersetzer.install.installer import Installer  # noqa: E402
from quellenuebersetzer.install.manifest import Manifest  # noqa: E402
from quellenuebersetzer.planner import PlanItem  # noqa: E402
from quellenuebersetzer.runtime.ollama import OllamaService  # noqa: E402


def main(root: Path) -> None:
    paths = Paths(root)
    paths.ensure()
    catalog = load_catalog()
    manifest = Manifest(paths)
    inst = Installer(paths, catalog, manifest, OllamaService(paths))
    for cid in ("tesseract", "pandoc", "typst"):
        if not manifest.has("component", cid):
            inst._install_component(catalog.components[cid], lambda *_: None)
        print("bereit:", cid)
    for lang in ("pol", "frak2021", "lat", "deu"):
        inst._install_tessdata(PlanItem("tessdata", lang, lang, 0, ""), lambda *_: None)
    print("Testumgebung:", root)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
