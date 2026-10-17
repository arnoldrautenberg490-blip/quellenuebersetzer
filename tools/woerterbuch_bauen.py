"""Baut die lokalen Wörterbuchdatenbanken (SQLite) aus frei lizenzierten Quellen.

  python tools/woerterbuch_bauen.py wiktionary <kaikki.org-dictionary-Polish.jsonl> <ziel.sqlite>
  python tools/woerterbuch_bauen.py gloger <cache-ordner> <ziel.sqlite>

Quellen:
- Wiktionary (englische Ausgabe), Polnisch-Einträge, aufbereitet von kaikki.org/wiktextract – CC BY-SA 4.0
- Zygmunt Gloger, Encyklopedja staropolska ilustrowana (1900–1903), gemeinfrei; Transkription
  pl.wikisource.org – CC BY-SA 4.0

Format siehe ``quellenuebersetzer/pipeline/lexicon.py``. Läuft nur bei der Entwicklung, nicht beim Nutzer.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Quellenuebersetzer-Woerterbuchbau/0.1 (https://github.com/arnoldrautenberg490-blip/quellenuebersetzer)"

HIST_TAGS = {"obsolete", "archaic", "historical", "dated", "rare", "literary", "dialectal", "regional"}
PERIOD_TAGS = {("Middle", "Polish"): "Mittelpolnisch (ca. 1500–1750)", ("Old", "Polish"): "Altpolnisch (bis ca. 1500)"}
TAG_DE = {"obsolete": "veraltet", "archaic": "archaisch", "historical": "historisch", "dated": "altmodisch",
          "rare": "selten", "literary": "gehoben", "dialectal": "mundartlich", "regional": "regional"}
B2_CATEGORY_HINTS = re.compile(
    r"units of measure|currenc|coins|nobility|titles|occupations|government|law|offices|military ranks|"
    r"historical|feudalism|heraldry|weights|measures|taxation|church|ecclesiastical|religion", re.I)


def _new_db(path: Path, meta: dict[str, str]) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = sqlite3.connect(str(path))
    con.executescript("""
        create table meta(key text primary key, value text);
        create table forms(form text not null, lemma text not null);
        create table entries(lemma text not null, sense text, tags text, period text, category text);
    """)
    con.executemany("insert into meta values (?,?)", meta.items())
    return con


def _finish(con: sqlite3.Connection) -> None:
    con.executescript("""
        create index forms_form on forms(form);
        create index entries_lemma on entries(lemma);
    """)
    con.commit()
    con.execute("vacuum")
    con.close()


# --------------------------------------------------------------------------- Wiktionary


def build_wiktionary(jsonl: Path, out: Path) -> None:
    con = _new_db(out, {
        "id": "pl-wiktionary", "label": "Wiktionary (Polnisch)",
        "license": "CC BY-SA 4.0", "attribution": "Wiktionary-Autorinnen und -Autoren; aufbereitet mit wiktextract (kaikki.org)",
    })
    form_rows: set[tuple[str, str]] = set()
    kept = 0
    for line in jsonl.open(encoding="utf-8"):
        d = json.loads(line)
        word = d.get("word", "")
        if not word or d.get("lang_code") != "pl":
            continue
        lemma = word.lower()
        senses = d.get("senses", [])
        # Flexionsformen → Grundform
        for s in senses:
            for fo in s.get("form_of", []) + s.get("alt_of", []):
                if fo.get("word"):
                    form_rows.add((lemma, fo["word"].lower()))
        if any("form-of" in s.get("tags", []) for s in senses):
            continue
        for f in d.get("forms", []):
            form = (f.get("form") or "").lower()
            if form and " " not in form and form != "-" and not set(f.get("tags", [])) & {"table-tags", "inflection-template"}:
                form_rows.add((form, lemma))
        form_rows.add((lemma, lemma))

        rows = []
        any_hist = False
        has_modern = False
        for s in senses:
            gloss = "; ".join(s.get("glosses", []))[:400]
            if not gloss:
                continue
            tags = set(s.get("tags", []))
            raw = s.get("tags", [])
            period = ""
            for (a, b), label in PERIOD_TAGS.items():
                if a in raw and b in raw:
                    period = label
            hist = sorted(tags & HIST_TAGS)
            cats = " ".join(c if isinstance(c, str) else c.get("name", "") for c in s.get("categories", []))
            topics = " ".join(s.get("topics", []))
            category = ""
            if "historical" in tags or (hist and B2_CATEGORY_HINTS.search(cats + " " + topics)):
                category = "b2"
            elif hist or period:
                category = "b1"
            if category:
                any_hist = True
            else:
                has_modern = True
            rows.append((lemma, gloss, ", ".join(TAG_DE[t] for t in hist), period, category))
        if not any_hist:
            continue
        # B1 nur, wenn es daneben eine heutige Bedeutung gibt (sonst ist das Wort einfach veraltet → B2-artig)
        fixed = []
        for lem, gloss, tags, period, cat in rows:
            if cat == "b1" and not has_modern:
                cat = "b2"
            fixed.append((lem, gloss, tags, period, cat))
        con.executemany("insert into entries values (?,?,?,?,?)", fixed)
        kept += 1
    kept_lemmas = {r[0] for r in con.execute("select distinct lemma from entries")}
    # nur Formen behalten, die zu einem Stichwort mit historischer Kennzeichnung führen
    con.executemany("insert into forms values (?,?)", sorted(fr for fr in form_rows if fr[1] in kept_lemmas))
    _finish(con)
    print(f"Wiktionary: {kept} Stichwörter mit historischer Kennzeichnung, {len(form_rows)} Formen → {out}")


# --------------------------------------------------------------------------- Gloger


def _api(params: dict) -> dict:
    url = "https://pl.wikisource.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"API nicht erreichbar: {params}")


def _clean_html(t: str) -> str:
    t = re.sub(r"<style.*?</style>|<table.*?</table>", " ", t, flags=re.S)
    t = re.sub(r'<span[^>]*class="[^"]*pagenum[^"]*"[^>]*>.*?</span>', " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(re.sub(r"\s+", " ", t)).strip()
    t = re.sub(r"\[\s*\d+\s*\]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _strip_header(text: str, head: str) -> str:
    """Entfernt den Wikisource-Kopf („Dane tekstu … Encyklopedia staropolska (tom IV) - Stichwort“) genau am Stichwort."""
    marker = f") - {head}"
    idx = text.rfind(marker, 0, 600)
    if idx >= 0:
        return text[idx + len(marker):].strip()
    m = re.search(r"Indeks stron\s*›+\s*", text[:600])
    return text[m.end():].strip() if m else text


def build_gloger(cache: Path, out: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    titles: list[str] = []
    cont = {}
    while True:
        d = _api({"action": "query", "list": "allpages", "apprefix": "Encyklopedia staropolska/", "aplimit": 500, **cont})
        titles += [p["title"] for p in d["query"]["allpages"]]
        if "continue" not in d:
            break
        cont = {"apcontinue": d["continue"]["apcontinue"]}
    print(f"Gloger: {len(titles)} Einträge")
    con = _new_db(out, {
        "id": "pl-gloger", "label": "Gloger, Encyklopedja staropolska (1900–1903)",
        "license": "gemeinfrei; Transkription Wikisource CC BY-SA 4.0",
        "attribution": "Zygmunt Gloger; Wikisource-Bearbeiterinnen und -Bearbeiter (pl.wikisource.org)",
    })
    for i, title in enumerate(titles, start=1):
        head = title.split("/", 1)[1]
        cfile = cache / (re.sub(r"[^\w-]", "_", head)[:80] + ".txt")
        if cfile.exists():
            raw = cfile.read_text(encoding="utf-8")
        else:
            d = _api({"action": "parse", "page": title, "prop": "text"})
            raw = _clean_html(d.get("parse", {}).get("text", ""))
            cfile.write_text(raw, encoding="utf-8")  # Rohtext zwischenspeichern, Kopf erst beim Bau entfernen
            time.sleep(0.25)
        text = _strip_header(raw, head)
        if i % 200 == 0:
            print(f"  {i}/{len(titles)}", flush=True)
        if not text or len(text) < 20 or head.lower().startswith("indeks"):
            continue
        lemma = head.split("(")[0].strip().lower()
        con.execute("insert into entries values (?,?,?,?,?)", (lemma, text[:1500], "Gloger", "Altpolen", "b2"))
        con.execute("insert into forms values (?,?)", (lemma, lemma))
        for part in re.split(r"[,;]| i ", lemma):  # Doppelstichwörter
            part = part.strip()
            if part and part != lemma and " " not in part:
                con.execute("insert into forms values (?,?)", (part, lemma))
    _finish(con)
    print(f"Gloger fertig → {out}")


if __name__ == "__main__":
    kind, src, dst = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    {"wiktionary": build_wiktionary, "gloger": build_gloger}[kind](src, dst)
