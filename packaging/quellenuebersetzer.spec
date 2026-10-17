# PyInstaller-Bauanleitung. Aufruf aus dem Projektordner:
#   python -m PyInstaller --noconfirm --clean packaging/quellenuebersetzer.spec
#
# Ordner-Variante (kein Ein-Datei-Programm) und ohne UPX: deutlich weniger Fehlalarme von Virenscannern.

from pathlib import Path

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src" / "quellenuebersetzer"

block_cipher = None

a = Analysis(
    [str(ROOT / "packaging" / "start.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(SRC / "resources"), "quellenuebersetzer/resources")],
    hiddenimports=[],
    excludes=[
        "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtSql", "PySide6.QtTest", "matplotlib", "IPython",
        "pytest",
    ],
    noarchive=False,
)
# Nicht benötigte Teile entfernen (Video, 3D, QML, Software-OpenGL, fremdsprachige Qt-Übersetzungen)
_DROP = ("opengl32sw.dll", "qt6quick", "qt6qml", "qt6pdf", "qt6virtualkeyboard", "opencv_videoio_ffmpeg", "qt6opengl")


def _keep(entry):
    name = entry[0].replace("\\", "/").lower()
    base = name.rsplit("/", 1)[-1]
    if any(base.startswith(d) for d in _DROP):
        return False
    if "/translations/" in name and not (base.endswith("_de.qm") or base.endswith("_en.qm")):
        return False
    return True


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Quellenuebersetzer",
    icon=str(SRC / "resources" / "icon.ico"),
    version=str(ROOT / "packaging" / "versionsinfo.txt"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Quellenuebersetzer")
