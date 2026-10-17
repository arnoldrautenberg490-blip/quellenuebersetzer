"""Lokale Wörterbücher (SQLite) und das Glossar des Nutzers.

Wörterbuchformat (von ``tools/woerterbuch_bauen.py`` erzeugt):

  meta(key, value)                       – id, label, license, attribution
  forms(form TEXT, lemma TEXT)           – Flexionsformen → Grundform (kleingeschrieben)
  entries(lemma TEXT, sense TEXT, tags TEXT, period TEXT, category TEXT)
      tags: z. B. "veraltet", "historisch", "Amt", "Maß", "Münze"
      category: "" | "b1" | "b2"   (Vorschlag aus der Aufbereitung)

Alle Abfragen laufen lokal; es gibt keinen Online-Zugriff.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

_WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


@dataclass
class LexEntry:
    word: str  # Form im Text
    lemma: str
    sense: str
    tags: str
    period: str
    category: str
    source: str


class Lexicon:
    def __init__(self, files: list[Path]):
        self.dbs: list[tuple[str, sqlite3.Connection]] = []
        for f in files:
            if not f.exists():
                continue
            con = sqlite3.connect(f"file:{f.as_posix()}?mode=ro", uri=True, check_same_thread=False)
            label = f.stem
            try:
                row = con.execute("select value from meta where key='label'").fetchone()
                if row:
                    label = row[0]
            except sqlite3.Error:
                pass
            self.dbs.append((label, con))

    @property
    def available(self) -> bool:
        return bool(self.dbs)

    def lookup_text(self, text: str, limit_per_word: int = 3, max_words: int = 40) -> list[LexEntry]:
        """Wörterbucheinträge mit historischer Kennzeichnung für die Wörter eines Abschnitts."""
        if not self.dbs:
            return []
        words = list(dict.fromkeys(w.lower() for w in _WORD_RE.findall(text)))
        found: list[LexEntry] = []
        seen: set[tuple[str, str]] = set()
        for label, con in self.dbs:
            for w in words:
                lemmas = [r[0] for r in con.execute("select lemma from forms where form=? limit 3", (w,))] or [w]
                for lemma in lemmas:
                    rows = con.execute(
                        "select lemma, sense, tags, period, category from entries "
                        "where lemma=? and (category='b2' or tags<>'') limit ?",
                        (lemma, limit_per_word),
                    ).fetchall()
                    for lem, sense, tags, period, cat in rows:
                        key = (lem, sense[:40])
                        if key in seen:
                            continue
                        seen.add(key)
                        found.append(LexEntry(w, lem, sense, tags or "", period or "", cat or "", label))
                if len({e.word for e in found}) >= max_words:
                    return found
        return found

    def close(self) -> None:
        for _, con in self.dbs:
            con.close()


@dataclass
class GlossaryEntry:
    term: str
    translation: str
    note: str
    category: str  # "" | b1 | b2
    period: str


class Glossary:
    """Vom Nutzer bestätigte Übersetzungen und Erklärungen. Bleibt lokal; exportierbar."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(path), check_same_thread=False)
        self.con.execute(
            "create table if not exists glossar (term text not null, translation text, note text, "
            "category text default '', period text default '', updated real, primary key(term, period))"
        )
        self.con.commit()

    def add(self, entry: GlossaryEntry) -> None:
        self.con.execute(
            "insert or replace into glossar values (?,?,?,?,?,?)",
            (entry.term.strip().lower(), entry.translation, entry.note, entry.category, entry.period, time.time()),
        )
        self.con.commit()

    def remove(self, term: str, period: str = "") -> None:
        self.con.execute("delete from glossar where term=? and period=?", (term.lower(), period))
        self.con.commit()

    def all(self) -> list[GlossaryEntry]:
        rows = self.con.execute("select term, translation, note, category, period from glossar order by term")
        return [GlossaryEntry(*r) for r in rows]

    def matches(self, text: str, periods: list[str]) -> list[GlossaryEntry]:
        low = text.lower()
        out = []
        for e in self.all():
            if e.period and periods and e.period not in periods:
                continue
            if re.search(r"(?<!\w)" + re.escape(e.term), low):
                out.append(e)
        return out

    def close(self) -> None:
        self.con.close()
