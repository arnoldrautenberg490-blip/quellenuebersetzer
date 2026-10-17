"""Schnellprüfung der Installation: Was ist vorhanden und korrekt, was fehlt oder ist veraltet?

- Programme (Ollama, Tesseract, Pandoc, Typst, 7-Zip): Prüfdatei vorhanden + Kennmarke mit passender Version.
- Einzeldateien (Seitenaufbau-Modell, Schriftmodelle, Wörterbücher): Größe und SHA-256 (Ergebnis wird je
  Datei zwischengespeichert, damit der Start schnell bleibt).
- Sprachmodelle: direkt in Ollamas Verzeichnis (Manifest + alle Teile), ohne Ollama zu starten.

``reconcile`` gleicht danach das Verzeichnis der Installationen ab: Korrekt Vorhandenes wird übernommen
(kein erneuter Download), Fehlendes oder Beschädigtes wird ausgetragen und damit neu installiert.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from quellenuebersetzer.catalog import Catalog, Component, FileSpec
from quellenuebersetzer.config import Paths
from quellenuebersetzer.install.manifest import Entry, Manifest

MARKER = ".baustein.json"


# --------------------------------------------------------------------------- Prüfsummen mit Zwischenspeicher


class HashCache:
    def __init__(self, paths: Paths):
        self.file = paths.root / "pruefsummen.json"
        try:
            self.data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.dirty = False

    def sha256(self, path: Path) -> str:
        st = path.stat()
        key = str(path)
        stamp = f"{st.st_size}-{st.st_mtime_ns}"
        cached = self.data.get(key)
        if cached and cached.get("stamp") == stamp:
            return cached["sha256"]
        h = hashlib.sha256()
        with path.open("rb") as fh:
            while block := fh.read(1024 * 1024):
                h.update(block)
        self.data[key] = {"stamp": stamp, "sha256": h.hexdigest()}
        self.dirty = True
        return self.data[key]["sha256"]

    def save(self) -> None:
        if self.dirty:
            try:
                self.file.parent.mkdir(parents=True, exist_ok=True)
                self.file.write_text(json.dumps(self.data), encoding="utf-8")
            except OSError:
                pass


def file_ok(path: Path, spec: FileSpec | None, hashes: HashCache, sha256: str | None = None, size: int | None = None) -> bool:
    sha256 = sha256 or (spec.sha256 if spec else None)
    size = size if size is not None else (spec.size if spec else None)
    try:
        if not path.is_file():
            return False
        if size and path.stat().st_size != size:
            return False  # z. B. halb kopiert oder abgebrochen
        return not sha256 or hashes.sha256(path) == sha256.lower()
    except OSError:
        return False


# --------------------------------------------------------------------------- Kennmarken für entpackte Programme


def write_marker(paths: Paths, comp: Component) -> None:
    from quellenuebersetzer import __version__

    target = paths.root / comp.target
    (target / MARKER).write_text(json.dumps({"id": comp.id, "sha256": comp.files[0].sha256, "programm": __version__}),
                                 encoding="utf-8")


def component_ok(paths: Paths, comp: Component, manifest: Manifest, hashes: HashCache) -> bool:
    target = paths.root / comp.target
    if not (paths.root / comp.check).exists():
        return False
    if comp.install == "file":
        return all(file_ok(target / f.name, f, hashes) for f in comp.files)
    try:
        marker = json.loads((target / MARKER).read_text(encoding="utf-8"))
        return marker.get("sha256") == comp.files[0].sha256
    except (OSError, ValueError):
        # ältere Installationen ohne Kennmarke: dem Verzeichnis der Installationen vertrauen
        return manifest.has("component", comp.id, comp.files[0].sha256)


# --------------------------------------------------------------------------- Sprachmodelle (Ollama-Verzeichnis)


def model_ok(paths: Paths, tag: str) -> bool:
    name, _, version = tag.partition(":")
    version = version or "latest"
    manifest_file = paths.models / "manifests" / "registry.ollama.ai" / "library" / name / version
    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    layers = data.get("layers", []) + ([data["config"]] if data.get("config") else [])
    for layer in layers:
        digest = str(layer.get("digest", "")).replace(":", "-")
        blob = paths.models / "blobs" / digest
        try:
            if not blob.is_file() or (layer.get("size") and blob.stat().st_size != layer["size"]):
                return False
        except OSError:
            return False
    return bool(layers)


# --------------------------------------------------------------------------- Abgleich


def reconcile(paths: Paths, catalog: Catalog, manifest: Manifest) -> list[str]:
    """Bringt das Verzeichnis der Installationen in Einklang mit dem tatsächlichen Zustand."""
    notes: list[str] = []
    hashes = HashCache(paths)

    for comp in catalog.components.values():
        ok = component_ok(paths, comp, manifest, hashes)
        listed = manifest.has("component", comp.id, comp.files[0].sha256)
        if ok and not listed:
            manifest.add(Entry(comp.id, "component", comp.files[0].sha256, [comp.target]))
            notes.append(f"{comp.label}: vorhanden, übernommen.")
        elif not ok and manifest.entries.get(Manifest.key("component", comp.id)):
            manifest.remove("component", comp.id)
            notes.append(f"{comp.label}: fehlt oder ist veraltet/beschädigt – wird neu installiert.")

    tessdir = paths.runtime / "tesseract" / "tessdata"
    for name, spec in catalog.tessdata.items():
        path = tessdir / spec.name
        ok = file_ok(path, spec, hashes)
        listed = manifest.has("tessdata", name, spec.sha256)
        if ok and not listed:
            manifest.add(Entry(name, "tessdata", spec.sha256, [path.relative_to(paths.root).as_posix()]))
        elif not ok and manifest.entries.get(Manifest.key("tessdata", name)):
            manifest.remove("tessdata", name)
            notes.append(f"Schriftmodell „{name}“ fehlt oder ist beschädigt – wird neu geladen.")

    for pack in catalog.languages.values():
        for d in pack.dictionaries:
            if d.bundled or not d.available:
                continue
            path = paths.dicts / d.file
            ok = file_ok(path, None, hashes, d.sha256, d.size)
            if ok and not manifest.has("dictionary", d.id, d.sha256):
                manifest.add(Entry(d.id, "dictionary", d.sha256, [path.relative_to(paths.root).as_posix()]))
            elif not ok and manifest.entries.get(Manifest.key("dictionary", d.id)):
                manifest.remove("dictionary", d.id)

    for tag in catalog.models:
        ok = model_ok(paths, tag)
        listed = Manifest.key("model", tag) in manifest.entries
        if ok and not listed:
            manifest.add(Entry(tag, "model"))
        elif not ok and listed:
            manifest.remove("model", tag)
            notes.append(f"Sprachmodell {tag} fehlt oder ist unvollständig – wird neu geladen.")

    hashes.save()
    return notes
