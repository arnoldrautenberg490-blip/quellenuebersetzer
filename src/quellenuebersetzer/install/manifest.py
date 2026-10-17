"""Verzeichnis aller Bausteine, die *dieses Programm* installiert hat.

Die Deinstallation entfernt ausschließlich, was hier verzeichnet ist (plus die
festen Datenordner). Bereits vorher vorhandene Software bleibt unangetastet.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from quellenuebersetzer.config import Paths


@dataclass
class Entry:
    id: str
    kind: str  # component | tessdata | model | dictionary
    sha256: str = ""
    paths: list[str] = field(default_factory=list)  # relativ zu Paths.root
    installed_at: float = field(default_factory=time.time)


class Manifest:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.entries: dict[str, Entry] = {}
        self._load()

    @staticmethod
    def key(kind: str, id_: str) -> str:
        return f"{kind}:{id_}"

    def _load(self) -> None:
        try:
            raw = json.loads(self.paths.manifest_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for k, v in raw.get("entries", {}).items():
            self.entries[k] = Entry(**v)

    def save(self) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        tmp = self.paths.manifest_file.with_suffix(".tmp")
        payload = {"version": 1, "entries": {k: asdict(v) for k, v in self.entries.items()}}
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.paths.manifest_file)

    def add(self, entry: Entry) -> None:
        self.entries[self.key(entry.kind, entry.id)] = entry
        self.save()

    def remove(self, kind: str, id_: str) -> None:
        self.entries.pop(self.key(kind, id_), None)
        self.save()

    def has(self, kind: str, id_: str, sha256: str | None = None) -> bool:
        entry = self.entries.get(self.key(kind, id_))
        if not entry:
            return False
        if sha256 and entry.sha256 and entry.sha256 != sha256:
            return False  # andere Version → neu installieren
        return all((self.paths.root / p).exists() for p in entry.paths) if entry.paths else True

    def all_paths(self) -> list[Path]:
        out = []
        for e in self.entries.values():
            out.extend(self.paths.root / p for p in e.paths)
        return out
