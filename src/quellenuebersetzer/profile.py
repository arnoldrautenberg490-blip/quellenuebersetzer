"""Das Quellenprofil: was der Historiker vor sich hat."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class SourceKind(str, Enum):
    DRUCK = "druck"
    ALTDRUCK = "altdruck"
    SCHREIBMASCHINE = "schreibmaschine"
    HANDSCHRIFT = "handschrift"
    TABELLEN = "tabellen"

    @property
    def label(self) -> str:
        return _KIND_LABELS[self][0]

    @property
    def hint(self) -> str:
        return _KIND_LABELS[self][1]


_KIND_LABELS = {
    SourceKind.DRUCK: ("Sauberer Druck", "Bücher, Zeitungen, Akten in moderner Druckschrift"),
    SourceKind.ALTDRUCK: ("Alter Druck / Fraktur", "Drucke vor ca. 1850, gebrochene Schriften"),
    SourceKind.SCHREIBMASCHINE: ("Schreibmaschine", "Maschinenschriftliche Akten, Durchschläge"),
    SourceKind.HANDSCHRIFT: ("Handschrift", "Briefe, Protokolle, Kirchenbücher, Akten"),
    SourceKind.TABELLEN: ("Tabellen", "Listen, Register, Statistiken, Rechnungen"),
}


@dataclass(frozen=True)
class Period:
    key: str
    label: str
    start: int
    end: int


PERIODS: tuple[Period, ...] = (
    Period("vor1500", "vor 1500", 1000, 1499),
    Period("16jh", "16. Jahrhundert", 1500, 1599),
    Period("17jh", "17. Jahrhundert", 1600, 1699),
    Period("18jh", "18. Jahrhundert", 1700, 1799),
    Period("19jh", "19. Jahrhundert", 1800, 1899),
    Period("1900_1945", "1900–1945", 1900, 1945),
    Period("nach1945", "nach 1945", 1946, 2100),
)

PERIOD_BY_KEY = {p.key: p for p in PERIODS}


@dataclass
class Language:
    code: str  # ISO 639-1
    label: str
    available: bool = True


LANGUAGES: tuple[Language, ...] = (Language("pl", "Polnisch"),)
LANGUAGE_BY_CODE = {lang.code: lang for lang in LANGUAGES}

TARGET_LANGUAGE = "de"


@dataclass
class Profile:
    kinds: list[SourceKind] = field(default_factory=list)
    language: str = "pl"
    periods: list[str] = field(default_factory=list)

    @property
    def has_handwriting(self) -> bool:
        return SourceKind.HANDSCHRIFT in self.kinds

    @property
    def is_valid(self) -> bool:
        return bool(self.kinds) and bool(self.periods) and self.language in LANGUAGE_BY_CODE

    def year_range(self) -> tuple[int, int]:
        ps = [PERIOD_BY_KEY[k] for k in self.periods if k in PERIOD_BY_KEY]
        if not ps:
            return (1500, 2000)
        return (min(p.start for p in ps), max(p.end for p in ps))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kinds"] = [k.value for k in self.kinds]
        return d

    @classmethod
    def from_dict(cls, data: dict | None) -> "Profile":
        if not data:
            return cls()
        kinds = []
        for k in data.get("kinds", []):
            try:
                kinds.append(SourceKind(k))
            except ValueError:
                pass
        return cls(
            kinds=kinds,
            language=data.get("language", "pl"),
            periods=[p for p in data.get("periods", []) if p in PERIOD_BY_KEY],
        )
