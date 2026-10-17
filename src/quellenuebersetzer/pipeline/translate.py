"""Übersetzung Markdown (Original) → Markdown (Deutsch) mit Erhalt der Struktur und Markierungen.

- Lesungsunsicherheiten (A) werden mitübersetzt: jede Lesart erhält eine deutsche Entsprechung.
- Bedeutungswandel (B1) und Begriffe der Zeit (B2) markiert das Modell, gestützt auf lokale
  Wörterbuchauszüge und das Glossar. Ohne Wörterbuchbeleg wird das ausdrücklich vermerkt.
- Jede Antwort wird geprüft (Tags vollständig, Tabellenstruktur gleich, Länge plausibel);
  bei Fehlern folgt ein zweiter Versuch, danach eine vorsichtige Rückfallstrategie.
  Inhalte werden nie stillschweigend weggelassen.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

from quellenuebersetzer.pipeline import markup
from quellenuebersetzer.pipeline.lexicon import Glossary, Lexicon, LexEntry
from quellenuebersetzer.runtime.ollama import OllamaClient, OllamaError

NO_EVIDENCE = "Einschätzung des Sprachmodells, ohne Wörterbuchbeleg"
EXAMPLE_EXPLANATION = ("königlicher Amtsträger, der einen Burgbezirk (starostwo) verwaltete und dort Gericht hielt")

_SCHEMA = {
    "type": "object",
    "properties": {
        "translation": {"type": "string"},
        "readings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "translations": {"type": "array", "items": {"type": "string"}}},
                "required": ["id", "translations"],
            },
        },
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "original": {"type": "string"},
                    "then": {"type": "string"},
                    "now": {"type": "string"},
                    "explanation": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["id", "original", "explanation"],
            },
        },
    },
    "required": ["translation", "readings", "terms"],
}


@dataclass
class Segment:
    kind: str  # text | ueberschrift | randnotiz | tabelle | roh
    source: str  # Inhalt ohne Präfix (## / > *Randnotiz:*)


@dataclass
class TranslationStats:
    segments: int = 0
    retries: int = 0
    repairs: int = 0  # ohne neue Anfrage behobene Antworten
    fallbacks: int = 0
    b1: int = 0
    b2: int = 0
    problems: list[str] = field(default_factory=list)


_RANDNOTIZ = "> *Randnotiz:* "


def split_segments(md: str) -> list[Segment]:
    segs: list[Segment] = []
    for block in re.split(r"\n\s*\n", md.strip()):
        b = block.strip()
        if not b:
            continue
        if b.startswith("<!--"):
            segs.append(Segment("roh", b))
        elif b.lower().startswith("<table"):
            segs.append(Segment("tabelle", b))
        elif b.startswith("## "):
            segs.append(Segment("ueberschrift", b[3:]))
        elif b.startswith(_RANDNOTIZ):
            segs.append(Segment("randnotiz", b[len(_RANDNOTIZ):].replace("\n> ", "\n")))
        else:
            segs.append(Segment("text", b))
    return segs


def join_segments(segs: list[tuple[Segment, str]]) -> str:
    out = []
    for seg, text in segs:
        if seg.kind == "ueberschrift":
            out.append("## " + text)
        elif seg.kind == "randnotiz":
            out.append("> *Randnotiz:* " + text.replace("\n", "\n> "))
        else:
            out.append(text)
    return "\n\n".join(out).strip() + "\n"


def _table_signature(html: str) -> tuple:
    rows = re.findall(r"<tr\b", html, re.I)
    cells = re.findall(r"<t[dh]\b[^>]*>", html, re.I)
    spans = [re.sub(r"\s+", "", c.lower().replace("<th", "<td")) for c in cells]
    return (len(rows), tuple(spans))


class Translator:
    def __init__(
        self,
        client: OllamaClient,
        model: str,
        source_language: str,
        period_label: str,
        year_range: tuple[int, int],
        lexicon: Lexicon | None = None,
        glossary: Glossary | None = None,
        periods: list[str] | None = None,
        extra_hints: list[str] | None = None,
        status: Callable[[str], None] | None = None,
    ):
        self.client = client
        self.model = model
        self.lang = source_language
        self.period_label = period_label
        self.years = year_range
        self.lexicon = lexicon
        self.glossary = glossary
        self.periods = periods or []
        self.hints = extra_hints or []
        self.status = status or (lambda _m: None)
        self.stats = TranslationStats()
        self._think_supported: bool | None = None

    # ------------------------------------------------------------------ Prompt
    def system_prompt(self) -> str:
        y0, y1 = self.years
        hints = "\n".join(f"- {h}" for h in self.hints)
        return f"""You translate historical {self.lang} sources into German for professional historians.
The source dates from: {self.period_label} (about {y0}–{y1}).

Rules:
1. Translate faithfully and completely into fluent German. Never summarise, omit or add. Keep the order of sentences.
   Never put explanations, glosses or the original words in parentheses into the translation – explanations belong only into "terms".
2. Personal names keep their original spelling. Places: use the established German name if one exists
   (Kraków → Krakau, Warszawa → Warschau, Gdańsk → Danzig), otherwise the Polish nominative form.
   Words in Hebrew, Yiddish or Cyrillic script (e.g. other name forms of a place) stay unchanged.
   Numbers, dates and amounts stay unchanged. Currency names: złoty → Złoty, grosz → Groschen. Translate Latin or German passages too.
3. Tags like <a_1>…</a_1> mark uncertain readings. Every such tag must appear exactly once in your translation, wrapped
   around the German rendering of the enclosed words. For each, give the German translation of every listed alternative
   reading in "readings" (same order).
4. Keep Markdown escapes (e.g. \\* \\[). Tables: keep the HTML structure exactly (same rows, cells, rowspan/colspan, <span …>
   elements) and translate ALL cell texts including the header row; only names and numbers stay unchanged.
5. Translate words with the meaning they had in the source period, not today's meaning. Mark SPARINGLY – only the few
   words a historian must check. Most passages need no mark at all, rarely more than two.
   - Period terms without a modern German equivalent (offices like starosta or wojewoda, estates, ranks, units of measure,
     coins, legal and church terms) → wrap the German rendering in <b2_1>…</b2_1>, <b2_2>…</b2_2> and explain in "terms".
   - A word whose meaning in the period clearly differed from today's meaning → <b1_1>…</b1_1> with "then" and "now".
   - NEVER mark ordinary words (to pay, yearly, town, year, files, witness, mill, all, every), names or numbers.
   - The text inside a tag is always the German rendering (Starost, Privileg, Elle), never the Polish word;
     the Polish original goes only into "original". Every word of the source must appear in German.
   - Tag format is exactly category, underscore, number: <b2_1>, <b2_2>, <b1_1>. Numbers start at 1 in every answer.
   - "evidence": the dictionary excerpt you relied on, or empty if you rely on your own knowledge.
   - Dictionary excerpts are background information, NOT a list of words to mark.
6. Binding glossary entries must be used exactly.
   Markers <split_1/>, <split_2/> … separate consecutive passages of the page layout (paragraph, column or page
   boundaries – a sentence may continue across a marker). Keep every marker exactly once, in the same order, at the
   corresponding position of the translation.
7. Modern German standard orthography. All explanations in "terms" are written in German.
{('Language notes:' + chr(10) + hints) if hints else ''}
Example – source: "Starosta zatwierdził przywilej dla miasta Krakowa."
Answer: {{"translation": "Der <b2_1>Starost</b2_1> bestätigte das Privileg für die Stadt Krakau.", "readings": [],
"terms": [{{"id": "b2_1", "original": "starosta", "then": "", "now": "", "explanation": "{EXAMPLE_EXPLANATION}", "evidence": "Wiktionary: historisch"}}]}}

Answer only with JSON matching the schema."""

    def german_place_name(self, name: str) -> str:
        """Eingebürgerte deutsche Namensform eines Ortes (Kraków → Krakau) oder leer.

        Leer, wenn es keine gibt, das Modell unsicher ist oder sie gleich geschrieben wird – lieber nichts als
        ein erfundener Name.
        """
        plain = markup.unescape_md(markup.strip_marks(name)).strip()
        if not plain or len(plain.split()) > 6:
            return ""
        prompt = (f'Place name from a historical {self.lang} source: "{plain}". If there is a well-established '
                  "German name (exonym) in common use for this place (e.g. Kraków → Krakau, Gdańsk → Danzig, "
                  "Oświęcim → Auschwitz, Lwów → Lemberg), answer with it, keeping any second name in parentheses. "
                  "If none exists, if you are not sure, or if the German name is spelled the same, answer with an "
                  'empty string. Never invent a name. Answer only with JSON {"german": "..."}.')
        schema = {"type": "object", "properties": {"german": {"type": "string"}}, "required": ["german"]}
        try:
            res = self.client.chat(self.model, [{"role": "user", "content": prompt}], json_schema=schema,
                                   num_ctx=_main_ctx(), temperature=0.0, num_predict=60, think=None)
            german = str(json.loads(res.text).get("german", "")).strip()
        except (OllamaError, ValueError, TypeError):
            return ""
        def norm(t: str) -> str:
            return re.sub(r"\W", "", t.casefold())
        if (not german or norm(german) == norm(plain) or len(german.split()) > 6
                or re.search(r"[<>{}\[\]\\]", german)):
            return ""
        return german

    def _user_prompt(self, seg: Segment, tagged: markup.Tagged, previous: tuple[str, str] | None,
                     lex: list[LexEntry], gloss) -> str:
        parts = []
        if previous:
            parts.append(f"Context (previous passage, do not translate again):\nSOURCE: {previous[0][-600:]}\nGERMAN: {previous[1][-600:]}")
        if gloss:
            parts.append("Binding glossary:\n" + "\n".join(f"- {g.term} → {g.translation}" + (f" ({g.note})" if g.note else "") for g in gloss))
        if lex:
            lines = [f"- {e.word} (Grundform {e.lemma}) [{e.source}{'; ' + e.tags if e.tags else ''}{'; ' + e.period if e.period else ''}]: {e.sense[:300]}" for e in lex]
            parts.append("Dictionary excerpts (historical dictionaries, use as evidence):\n" + "\n".join(lines))
        a_marks = {k: v for k, v in tagged.marks.items() if v.category == "a"}
        if a_marks:
            listed = "\n".join(f"- {k}: " + " | ".join(v.attrs.get("lesarten", v.text).split("|")) for k, v in a_marks.items())
            parts.append("Uncertain readings (alternatives to translate in \"readings\"):\n" + listed)
        kind = {"tabelle": "an HTML table", "ueberschrift": "a heading", "randnotiz": "a marginal note",
                "zelle": "the content of one table cell (see context)"}.get(seg.kind, "a passage")
        parts.append(f"Translate {kind}:\n{tagged.text}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------ Aufruf
    def _chat(self, messages: list[dict], long: bool, source_chars: int = 2000) -> dict:
        from quellenuebersetzer.pipeline.readers import MAIN_CTX

        # Antwortlänge begrenzen: Übersetzung + Lesarten + Erläuterungen, großzügig bemessen
        limit = min(MAIN_CTX // 2, int(source_chars / 2.2) + 600)
        kwargs = dict(json_schema=_SCHEMA, num_ctx=MAIN_CTX, temperature=0.1, num_predict=limit)
        think = False if self._think_supported is not False else None
        try:
            res = self.client.chat(self.model, messages, think=think, **kwargs)
        except OllamaError as exc:
            if "think" in str(exc).lower() and think is not None:
                self._think_supported = False
                res = self.client.chat(self.model, messages, think=None, **kwargs)
            else:
                raise
        return json.loads(res.text)

    def _validate(self, seg: Segment, tagged: markup.Tagged, data: dict) -> list[str]:
        problems = []
        text = data.get("translation", "")
        if not text.strip():
            return ["Die Übersetzung ist leer."]
        expected_a = sorted(k for k, v in tagged.marks.items() if v.category == "a")
        found_a = sorted(i for i in markup.tag_ids(text) if i.startswith("a_"))
        if expected_a != found_a:
            problems.append(f"Tags for uncertain readings must appear exactly once each: expected {expected_a}, got {found_a}.")
        src_markers = re.findall(r"<split_\d+/>", tagged.text)
        if src_markers and re.findall(r"<split_\d+/>", text) != src_markers:
            problems.append("Keep every marker <split_n/> exactly once and in the same order.")
        if seg.kind == "tabelle" and _table_signature(text) != _table_signature(tagged.text):
            problems.append("The HTML table structure changed. Keep exactly the same rows, cells, rowspan and colspan.")
        elif seg.kind == "tabelle" and _header_untranslated(tagged.text, text):
            problems.append("The table header row was not translated. Translate all cell texts into German.")
        malformed = [t for t in re.findall(r"</?(?:a|b1|b2)[^>]*>", text) if not re.fullmatch(r"</?(?:a|b1|b2)_\d+>", t)]
        if malformed:
            problems.append(f"Malformed tags {sorted(set(malformed))[:4]}. Use exactly <b2_1>…</b2_1>, <b1_1>…</b1_1>, <a_1>…</a_1>.")
        b_ids = {i for i in markup.tag_ids(text) if i.startswith(("b1_", "b2_"))}
        term_ids = {t.get("id") for t in data.get("terms", []) if isinstance(t, dict)}
        n_words = len(re.findall(r"\w+", markup.strip_marks(seg.source)))
        if len(b_ids) > max(2, n_words // 12):
            problems.append("Far too many words are marked. Mark only the few period terms a historian must check; "
                            "never mark ordinary words.")
        elif b_ids - term_ids:
            problems.append(f"Every marked term needs an entry in \"terms\" (missing: {sorted(b_ids - term_ids)}).")
        if re.search(r"\([^)]*\)", text) and not re.search(r"\([^)]*\)", markup.strip_marks(seg.source)):
            problems.append("Do not add parenthetical explanations or original words to the translation; use \"terms\".")
        problems.extend(_number_problems(seg, tagged.text, text))
        src_plain = markup.strip_marks(seg.source)
        src_len = len(src_plain)
        if _untranslated(src_plain, markup.strip_marks(markup.from_tags(text, {}))):
            problems.append("The text was returned untranslated. Translate it into German.")
        ratio = len(text) / max(1, src_len)
        if src_len > 40 and not 0.5 <= ratio <= 3.0:
            problems.append("The translation length is implausible; translate completely without additions.")
        return problems

    def translate_segment(self, seg: Segment, previous: tuple[str, str] | None = None) -> str:
        if seg.kind == "roh":
            return seg.source
        html = seg.kind == "tabelle"
        tagged = markup.to_tags(seg.source, html=html)
        plain = markup.strip_marks(seg.source)
        lex = _select_lexicon(self.lexicon.lookup_text(re.sub(r"<[^>]+>", " ", plain))) if self.lexicon else []
        gloss = self.glossary.matches(plain, self.periods) if self.glossary else []
        messages = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": self._user_prompt(seg, tagged, previous, lex, gloss)},
        ]
        long = len(seg.source) > 3000
        self.stats.segments += 1
        data, problems = None, ["noch nicht übersetzt"]
        for attempt in range(2):
            try:
                data = self._chat(messages, long, len(seg.source))
                problems = self._validate(seg, tagged, data)
            except (ValueError, OllamaError) as exc:
                data, problems = None, [f"Invalid answer: {exc}"]
            if problems and data is not None:
                repaired = local_repair(seg, tagged, data, problems)
                if repaired is not None and not self._validate(seg, tagged, repaired):
                    data, problems = repaired, []
                    self.stats.repairs += 1
            if not problems:
                break
            self.stats.retries += 1
            if data is not None:
                messages += [
                    {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)},
                    {"role": "user", "content": "Your answer has problems:\n- " + "\n- ".join(problems) + "\nCorrect them and answer again with the full JSON."},
                ]
        if problems:
            return self._fallback(seg, tagged, previous, problems)
        return self._assemble(seg, tagged, data)

    def _assemble(self, seg: Segment, tagged: markup.Tagged, data: dict) -> str:
        html = seg.kind == "tabelle"
        text = data["translation"]
        marks = dict(tagged.marks)
        readings = {r.get("id"): r.get("translations", []) for r in data.get("readings", [])}
        for tid, mark in marks.items():
            if mark.category == "a":
                de = [t for t in readings.get(tid, []) if isinstance(t, str)]
                mark.attrs = {**mark.attrs, "lesarten_de": "|".join(de)}
        terms = {t.get("id"): t for t in data.get("terms", []) if isinstance(t, dict)}
        seen_explanations: set[str] = set()
        for tid in markup.tag_ids(text):
            if tid.startswith(("b1_", "b2_")):
                t = terms.get(tid)
                if not t:
                    continue  # Tag ohne Erklärung → wird beim Zurückwandeln entfernt
                cat = tid.split("_")[0]
                evidence = (t.get("evidence") or "").strip() or NO_EVIDENCE
                explanation = (t.get("explanation") or "").strip()
                # aus dem Beispiel kopiert oder für einen anderen Begriff schon verwendet → keine echte Erläuterung
                if explanation == EXAMPLE_EXPLANATION or explanation.lower() in seen_explanations:
                    continue  # Markierung wird beim Zurückwandeln entfernt (Text bleibt)
                seen_explanations.add(explanation.lower())
                attrs = {"original": t.get("original", ""), "erkl": explanation, "beleg": evidence}
                if cat == "b1":
                    attrs.update({"damals": t.get("then", ""), "heute": t.get("now", "")})
                    self.stats.b1 += 1
                else:
                    self.stats.b2 += 1
                marks[tid] = markup.Mark(cat, "", attrs)
        return _strip_stray_tags(markup.from_tags(text, marks, html=html))

    def _fallback(self, seg: Segment, tagged: markup.Tagged, previous, problems: list[str]) -> str:
        """Vorsichtige Rückfallstrategie: Tabellen zellweise, sonst ohne Markierungen mit Hinweis."""
        self.stats.fallbacks += 1
        self.stats.problems.append("; ".join(problems))
        if seg.kind == "tabelle":
            return self._translate_table_cells(seg.source, previous)
        plain_seg = Segment(seg.kind, markup.strip_marks(seg.source))
        try:
            data = self._chat(
                [{"role": "system", "content": self.system_prompt()},
                 {"role": "user", "content": self._user_prompt(plain_seg, markup.Tagged(plain_seg.source, {}), previous, [], [])}],
                long=len(seg.source) > 3000,
            )
            text = _strip_stray_tags(markup.from_tags(data.get("translation", ""), {}))  # alle Tags entfernen
        except (ValueError, OllamaError):
            text = ""
        note = markup.Mark("a", "[Hinweis]", {
            "lesarten": "",
            "sicher": "0.00",
            "hinweis": "Markierungen dieses Abschnitts konnten nicht in die Übersetzung übertragen werden – bitte das Original vergleichen.",
        }).to_markdown()
        if not text.strip():
            return note + " " + markup.escape_md("[Übersetzung fehlgeschlagen – Originaltext:] ") + seg.source
        return note + " " + text

    def _translate_table_cells(self, html: str, previous=None) -> str:
        """Rückfall für Tabellen: Zelle für Zelle – mit Spaltenköpfen und vorherigem Text als Zusammenhang."""
        cell_re = re.compile(r"(<t[dh]\b[^>]*>)(.*?)(</t[dh]>)", re.S | re.I)
        rows = re.findall(r"<tr\b.*?</tr>", html, re.S | re.I)
        headers = [markup.html_unescape(re.sub(r"<[^>]+>", "", c[1])).strip() for c in cell_re.findall(rows[0])] if rows else []
        before = previous[0][-300:] if previous else ""
        context = (f"Table with the column headers: {' | '.join(headers)}. "
                   + (f"The text before the table reads: {before}" if before else "")).strip()

        def translate_row(row_html: str) -> str:
            col = [0]

            def repl(m: re.Match) -> str:
                inner = m.group(2)
                header = headers[col[0]] if col[0] < len(headers) else ""
                col[0] += 1
                if not re.search(r"[^\W\d_]{2,}", markup.html_unescape(re.sub(r"<[^>]+>", "", inner))):
                    return m.group(0)  # Zahlen, leere Zellen
                ctx = context + (f" This cell is in the column \"{header}\"." if header else "")
                translated = self.translate_segment(Segment("zelle", _cell_to_md(inner)), (ctx, ""))
                return f"{m.group(1)}{markup.markdown_cell_to_html(translated)}{m.group(3)}"

            return cell_re.sub(repl, row_html)

        return re.sub(r"<tr\b.*?</tr>", lambda m: translate_row(m.group(0)), html, flags=re.S | re.I)

    # ------------------------------------------------------------------ Dokument
    def translate_markdown(self, md: str, progress: Callable[[int, int], None] | None = None) -> str:
        segs = split_segments(md)
        out: list[tuple[Segment, str]] = []
        previous = None
        total = len(segs)
        for i, seg in enumerate(segs, start=1):
            if progress:
                progress(i, total)
            de = self.translate_segment(seg, previous)
            out.append((seg, de))
            if seg.kind in ("text", "ueberschrift", "randnotiz"):
                previous = (markup.strip_marks(seg.source), markup.strip_marks(de))
        return join_segments(out)


_STRAY_TAG_RE = re.compile(r"</?(?:a|b1|b2)(?:_[^>]*)?>")


def _drop_tags(text: str, ids: set[str]) -> str:
    """Markierungs-Tags entfernen, Inhalt behalten."""
    for tid in ids:
        text = re.sub(rf"</?{re.escape(tid)}>", "", text)
    return text


def local_repair(seg: Segment, tagged: markup.Tagged, data: dict, problems: list[str]) -> dict | None:
    """Kleine Fehler ohne neue Modellanfrage beheben: überzählige, fehlerhafte oder unerklärte B-Markierungen
    werden entfernt (der übersetzte Text bleibt unverändert). Gibt None zurück, wenn das nicht reicht."""
    repairable = ("Far too many words are marked", "Every marked term needs", "Malformed tags")
    if not problems or not all(p.startswith(repairable) for p in problems):
        return None
    text = data.get("translation", "")
    text = re.sub(r"</?(?:b1|b2)(?!_\d+>)[^>]*>", "", text)  # fehlerhafte B-Tags
    terms = {t.get("id") for t in data.get("terms", []) if isinstance(t, dict)}
    b_ids = [i for i in dict.fromkeys(markup.tag_ids(text)) if i.startswith(("b1_", "b2_"))]
    text = _drop_tags(text, {i for i in b_ids if i not in terms})
    n_words = len(re.findall(r"\w+", markup.strip_marks(seg.source)))
    keep = [i for i in b_ids if i in terms][:max(1, min(2, n_words // 12))]
    text = _drop_tags(text, {i for i in b_ids if i not in keep})
    return {**data, "translation": text}


def _main_ctx() -> int:
    from quellenuebersetzer.pipeline.readers import MAIN_CTX

    return MAIN_CTX


def _strip_stray_tags(text: str) -> str:
    """Letzte Sicherung: nie Platzhalter-Tags des Modells im fertigen Dokument."""
    return _STRAY_TAG_RE.sub("", text)


def _select_lexicon(entries: list[LexEntry], limit_b2: int = 8, limit_other: int = 4) -> list[LexEntry]:
    """Wenige, gezielte Wörterbuchauszüge: Begriffe der Zeit zuerst, Bedeutungswandel nur sparsam."""
    b2 = [e for e in entries if e.category == "b2"]
    other = [e for e in entries if e.category != "b2" and any(t in e.tags for t in ("historisch", "veraltet", "archaisch"))]
    return b2[:limit_b2] + other[:limit_other]


def _header_untranslated(source_html: str, translated_html: str) -> bool:
    """Alle Kopfzellen (mit Wörtern) unverändert → Tabelle wurde nicht übersetzt."""
    def heads(h: str) -> list[str]:
        first = re.search(r"<tr\b.*?</tr>", h, re.S | re.I)
        cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", first.group(0), re.S | re.I) if first else []
        return [" ".join(re.sub(r"<[^>]+>", " ", c).split()).lower() for c in cells]

    src, dst = heads(source_html), heads(translated_html)
    wordy = [i for i, c in enumerate(src) if re.search(r"[^\W\d_]{4,}", c)]
    return len(wordy) >= 2 and len(src) == len(dst) and all(src[i] == dst[i] for i in wordy)


_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(text: str) -> list[str]:
    plain = re.sub(r"<[^>]+>", " ", text)
    return sorted(n.replace(",", ".") for n in _NUM_RE.findall(plain))


def _cells(html: str) -> list[str]:
    return re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", html, re.S | re.I)


def _number_problems(seg: Segment, source: str, translation: str) -> list[str]:
    """Zahlen, Jahreszahlen und Beträge müssen exakt erhalten bleiben (Schutz gegen erfundene Werte)."""
    if seg.kind == "tabelle":
        src_cells, dst_cells = _cells(source), _cells(translation)
        if len(src_cells) != len(dst_cells):
            return []  # Strukturfehler wird gesondert gemeldet
        bad = [i + 1 for i, (a, b) in enumerate(zip(src_cells, dst_cells)) if _numbers(a) != _numbers(b)]
        if bad:
            return [f"Numbers changed in table cells {bad[:6]}. Copy every number exactly as in the source cell."]
        return []
    if _numbers(source) != _numbers(translation):
        return ["Numbers, years or amounts were changed, added or dropped. Copy every number exactly as in the source."]
    return []


def _untranslated(source: str, translation: str) -> bool:
    """Ist die „Übersetzung“ praktisch der Ausgangstext? (Namen und Zahlen allein zählen nicht.)"""
    words = re.findall(r"[^\W\d_]{4,}", source)
    if len(words) < 2:
        return False
    norm = lambda t: " ".join(re.findall(r"\w+", t.lower()))  # noqa: E731
    return norm(source) == norm(translation)


def _cell_to_md(cell_html: str) -> str:
    """HTML-Zellinhalt (mit Spans) → Markdown mit Spans."""
    def repl(m: re.Match) -> str:
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group("attrs") or ""))
        mark = markup.Mark(m.group("cat"), markup.html_unescape(m.group("text")), {k: markup.html_unescape(v) for k, v in attrs.items()})
        return mark.to_markdown()

    out, pos = [], 0
    for m in markup.HTML_SPAN_RE.finditer(cell_html):
        out.append(markup.escape_md(markup.html_unescape(cell_html[pos:m.start()])))
        out.append(repl(m))
        pos = m.end()
    out.append(markup.escape_md(markup.html_unescape(cell_html[pos:])))
    return "".join(out)
