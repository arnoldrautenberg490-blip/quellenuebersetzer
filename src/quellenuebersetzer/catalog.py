"""Bausteinkatalog: welche Komponenten, Modelle, Sprachdaten und Wörterbücher es gibt.

Der Katalog ist reine Datenbeschreibung (JSON). Neue Sprachen werden ergänzt, indem
man unter ``resources/catalog/sprachen/`` eine weitere Datei anlegt – ohne Codeänderung.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from quellenuebersetzer.config import resources_dir


@dataclass
class FileSpec:
    url: str
    sha256: str
    size: int
    name: str
    mirrors: tuple[str, ...] = ()  # Ersatzadressen derselben Datei (gleiche Prüfsumme)


@dataclass
class Component:
    id: str
    label: str
    purpose: str
    license: str
    license_url: str
    files: list[FileSpec]
    install: str
    target: str
    check: str
    requires: list[str] = field(default_factory=list)
    strip_top_dir: bool = False

    @property
    def download_size(self) -> int:
        return sum(f.size for f in self.files)


@dataclass
class Model:
    tag: str
    label: str
    size: int
    vram_gb: float
    license: str
    vision: bool


@dataclass
class Tier:
    key: str
    min_vram_gb: float
    main: str
    ocr: str
    label: str
    number: int
    quality: int = 3  # 1 = beste … 5 = Notbetrieb
    gruendlich: dict | None = None  # optionaler Modus „Gründlich“: {"main", "min_ram_gb", "quality"}


@dataclass
class Dictionary:
    id: str
    label: str
    purpose: str
    periods: list[str]
    license: str
    attribution: str
    file: str
    url: str | None
    sha256: str | None
    size: int | None
    bundled: bool = False  # liegt dem Programm bei (resources/woerterbuecher)

    @property
    def available(self) -> bool:
        return self.bundled or bool(self.url and self.sha256)

    def path(self, dict_dir: Path) -> Path:
        """Heruntergeladene Fassung bevorzugen, sonst die mitgelieferte."""
        downloaded = dict_dir / self.file
        if downloaded.exists() or not self.bundled:
            return downloaded
        return resources_dir() / "woerterbuecher" / self.file


@dataclass
class LanguagePack:
    code: str
    label: str
    name_en: str
    tesseract: dict[str, list[str]]
    prompt: dict
    dictionaries: list[Dictionary]

    def tesseract_langs_for(self, kind: str) -> list[str]:
        return list(self.tesseract.get(kind, []))


@dataclass
class Catalog:
    components: dict[str, Component]
    tessdata: dict[str, FileSpec]
    tessdata_license: dict[str, str]
    models: dict[str, Model]
    tiers: list[Tier]
    languages: dict[str, LanguagePack]

    def tier_for_vram(self, vram_gb: float) -> Tier:
        for tier in self.tiers:
            if vram_gb >= tier.min_vram_gb:
                return tier
        return self.tiers[-1]

    @property
    def best_tier(self) -> Tier:
        return self.tiers[0]


def _load_language(path: Path) -> LanguagePack:
    data = json.loads(path.read_text(encoding="utf-8"))
    tess = {k: v for k, v in data.get("tesseract", {}).items() if not k.startswith("_")}
    return LanguagePack(
        code=data["code"],
        label=data["label"],
        name_en=data.get("name_en", data["label"]),
        tesseract=tess,
        prompt=data.get("prompt", {}),
        dictionaries=[Dictionary(**d) for d in data.get("dictionaries", [])],
    )


@lru_cache(maxsize=4)
def load_catalog(base: Path | None = None) -> Catalog:
    base = base or resources_dir() / "catalog"
    data = json.loads((base / "bausteine.json").read_text(encoding="utf-8"))

    components = {}
    for cid, c in data["components"].items():
        components[cid] = Component(
            id=cid,
            label=c["label"],
            purpose=c.get("purpose", ""),
            license=c["license"],
            license_url=c.get("license_url", ""),
            files=[FileSpec(**f) for f in c["files"]],
            install=c["install"],
            target=c["target"],
            check=c["check"],
            requires=c.get("requires", []),
            strip_top_dir=c.get("strip_top_dir", False),
        )

    tessdata, tess_lic = {}, {}
    for name, spec in data["tessdata"].items():
        if name.startswith("_"):
            continue
        tessdata[name] = FileSpec(url=spec["url"], sha256=spec["sha256"], size=spec["size"], name=f"{name}.traineddata",
                                  mirrors=tuple(spec.get("mirrors", ())))
        tess_lic[name] = spec.get("license", "")

    models = {tag: Model(tag=tag, **m) for tag, m in data["models"].items()}
    tiers = [Tier(number=i + 1, **t) for i, t in enumerate(data["tiers"])]
    languages = {}
    for p in sorted((base / "sprachen").glob("*.json")):
        pack = _load_language(p)
        languages[pack.code] = pack

    return Catalog(components, tessdata, tess_lic, models, tiers, languages)
