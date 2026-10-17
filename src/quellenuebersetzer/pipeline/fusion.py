"""Abgleich zweier unabhängiger Lesungen und Markierung unsicherer Stellen (Kategorie A).

Leitregeln (nach ICDAR 2026 HIPE-OCRepair):
- Stimmen zwei unabhängige Leser überein, gilt die Stelle als sicher.
- Ein Sprachmodell darf nur abweichende Stellen entscheiden, nie frei umformulieren.
- Unplausibel lange/kurze Zweitlesungen (Halluzination) werden verworfen.
- Im Zweifel wird markiert, nicht ersetzt.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

from rapidfuzz.distance import Levenshtein

from quellenuebersetzer.pipeline.markup import escape_md, mark_reading
from quellenuebersetzer.runtime.tesseract import Line

CONF_OK = 85.0
CONF_LOW = 60.0
CONF_SECOND = 70.0  # darunter wird eine Zweitlesung eingeholt (Druck/Schreibmaschine)
LENGTH_RATIO = (0.35, 2.8)

_PUNCT = "„“”\"'‚‘’«».,;:!?()[]{}<>—–-"
_COMPARE_MAP = str.maketrans({"ſ": "s", "ꝛ": "r", "ı": "i", "ȷ": "j", "­": ""})

Judge = Callable[[list[str]], tuple[int, str, float]]  # Optionen → (Wahl, Lesung, Sicherheit)


def norm_token(token: str) -> str:
    t = unicodedata.normalize("NFC", token).translate(_COMPARE_MAP).strip(_PUNCT).casefold()
    return t


@dataclass
class FusedLine:
    markdown: str
    marks: int = 0
    words: int = 0
    text_plain: str = ""
    notes: list[str] = field(default_factory=list)


def _emit_plain(tokens: list[str]) -> str:
    return " ".join(escape_md(t) for t in tokens)


def fuse_line(
    tline: Line,
    other_text: str | None,
    judge: Judge | None = None,
    strict: bool = False,
) -> FusedLine:
    """Verschmilzt die Tesseract-Lesung einer Zeile mit einer zweiten Lesung.

    ``strict``: Abweichungen werden immer markiert (alter Druck), auch wenn der Schiedsrichter sicher ist.
    """
    t_tokens = [w.text for w in tline.words]
    confs = [w.conf for w in tline.words]
    t_text = " ".join(t_tokens)

    if other_text is not None:
        other_text = " ".join(other_text.split())
        ratio = len(other_text) / max(1, len(t_text))
        if not other_text or not (LENGTH_RATIO[0] <= ratio <= LENGTH_RATIO[1]):
            other_text = None

    if other_text is None:
        return _single_reader(t_tokens, confs)

    o_tokens = other_text.split()
    a = [norm_token(t) for t in t_tokens]
    b = [norm_token(t) for t in o_tokens]
    if a == b:
        return FusedLine(_emit_plain(t_tokens), 0, len(t_tokens), t_text)

    opcodes = Levenshtein.opcodes(a, b)
    decision: tuple[int, str, float] | None = None
    if judge is not None:
        decision = judge([t_text, other_text])

    out: list[str] = []
    marks = 0
    for op in opcodes:
        tag, i1, i2, j1, j2 = op.tag, op.src_start, op.src_end, op.dest_start, op.dest_end
        seg_t, seg_o = t_tokens[i1:i2], o_tokens[j1:j2]
        if tag == "equal":
            out.append(_emit_plain(seg_t))
            continue
        seg_conf = min(confs[i1:i2]) if i2 > i1 else 0.0
        t_str, o_str = " ".join(seg_t), " ".join(seg_o)

        if decision is not None and decision[0] in (0, 1):
            choice, _, certain = decision
            primary, secondary = (t_str, o_str) if choice == 0 else (o_str, t_str)
            if certain >= 0.85 and not strict:
                if primary:
                    out.append(_emit_plain(primary.split()))
                continue
            confidence = certain * 0.8
        else:
            # ohne Schiedsspruch: bei hoher Tesseract-Sicherheit dessen Lesung, sonst die Zweitlesung
            if seg_t and seg_conf >= CONF_OK:
                primary, secondary = t_str, o_str
                confidence = seg_conf / 100 * 0.7
            else:
                primary, secondary = (o_str, t_str) if seg_o else (t_str, o_str)
                confidence = 0.5 if seg_o else seg_conf / 100 * 0.5
        if not primary:
            # nur ein Leser hat hier etwas gesehen → als fragliche Ergänzung markieren
            out.append(mark_reading(secondary, [secondary, "(nichts)"], min(confidence, 0.4)))
        else:
            out.append(mark_reading(primary, [primary, secondary or "(nichts)"], confidence))
        marks += 1

    md = " ".join(p for p in out if p)
    return FusedLine(md, marks, len(t_tokens), t_text)


def _single_reader(tokens: list[str], confs: list[float]) -> FusedLine:
    out, marks = [], 0
    for tok, conf in zip(tokens, confs):
        if conf < CONF_LOW:
            out.append(mark_reading(tok, [tok], conf / 100))
            marks += 1
        else:
            out.append(escape_md(tok))
    return FusedLine(" ".join(out), marks, len(tokens), " ".join(tokens))


def mark_by_confidence(words: list[tuple[str, float]], threshold: float = 0.5) -> tuple[str, int]:
    """Für Lesungen mit Token-Wahrscheinlichkeiten (Handschrift): unsichere Wörter markieren."""
    out, marks = [], 0
    for word, prob in words:
        if "[?]" in word:
            out.append(mark_reading(word, [word], 0.0))
            marks += 1
        elif prob < threshold:
            out.append(mark_reading(word, [word], prob))
            marks += 1
        else:
            out.append(escape_md(word))
    return " ".join(out), marks


def join_lines(lines: list[str]) -> str:
    """Zeilen eines Absatzes verbinden; Worttrennung am Zeilenende auflösen (nur bei unmarkiertem Wortende)."""
    text = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if text and re.search(r"[A-Za-zÀ-ž]\\?[-¬⸗]$", text) and re.match(r"[a-zà-ž]", ln):
            text = re.sub(r"\\?[-¬⸗]$", "", text) + ln
        elif text:
            text += " " + ln
        else:
            text = ln
    return text
