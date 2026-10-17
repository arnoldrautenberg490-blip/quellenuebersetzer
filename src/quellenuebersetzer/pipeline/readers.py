"""Lesemodelle über die lokale Modell-Laufzeit: GLM-OCR (Text, Tabellen) und Gemma 4 (Schiedsrichter, Handschrift)."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

import numpy as np

from quellenuebersetzer.pipeline.preprocess import encode_png
from quellenuebersetzer.runtime.ollama import OllamaClient, OllamaError, TokenLogprob

# Eine feste Kontextgröße je Modell: Ollama lädt ein Modell neu, sobald sich num_ctx ändert.
MAIN_CTX = 8192
OCR_CTX = 8192

_DIPLOMATIC_RULES = (
    "Transcribe diplomatically: reproduce spelling, abbreviations, punctuation, capitalisation and errors "
    "exactly as written. Never modernise, never normalise, never complete words that are not visible. "
    "If a character or word cannot be read, write [?] in its place. Output only the transcription."
)


@dataclass
class Reading:
    text: str
    logprobs: list[TokenLogprob]

    def word_confidences(self) -> list[tuple[str, float]]:
        """Wahrscheinlichkeit je Wort (Minimum über die Tokens des Wortes)."""
        return words_with_confidence(self.text, self.logprobs)


def words_with_confidence(text: str, logprobs: list[TokenLogprob]) -> list[tuple[str, float]]:
    words = text.split()
    joined = "".join(t.token for t in logprobs)
    offset = joined.find(text) if text else -1
    if not logprobs or offset < 0:
        return [(w, 1.0) for w in words]  # keine Zuordnung möglich → keine Aussage
    spans = []
    pos = -offset
    for t in logprobs:
        spans.append((pos, pos + len(t.token), math.exp(t.logprob)))
        pos += len(t.token)
    out = []
    for m in re.finditer(r"\S+", text):
        probs = [p for s, e, p in spans if s < m.end() and e > m.start()]
        out.append((m.group(), min(probs) if probs else 1.0))
    return out


class GlmOcr:
    def __init__(self, client: OllamaClient, model: str):
        self.client = client
        self.model = model

    def _ask(self, prompt: str, png: bytes, num_predict: int = 2048) -> str:
        msg = OllamaClient.image_message(prompt, [png])
        res = self.client.chat(self.model, [msg], num_ctx=OCR_CTX, num_predict=num_predict, think=None, repeat_penalty=1.05)
        return res.text.strip()

    def text(self, image: np.ndarray) -> str:
        # Zeilen/Zellen sind kurz: Antwortlänge begrenzen (verhindert minutenlange Wiederholungsschleifen)
        return _clean_ocr(self._ask("Text Recognition:", encode_png(image, max_side=2200), num_predict=400))

    def table(self, image: np.ndarray) -> str:
        return self.table_png(encode_png(image, max_side=2200))

    def table_png(self, png: bytes) -> str:
        return self._ask("Table Recognition:", png, num_predict=4096)


def _clean_ocr(text: str) -> str:
    text = re.sub(r"^```\w*\n?|```$", "", text.strip())
    return text.strip()


class VisionJudge:
    """Gemma 4 als Schiedsrichter zwischen zwei Lesungen und als Leser für Handschrift."""

    def __init__(self, client: OllamaClient, model: str, language_label: str = "Polish"):
        self.client = client
        self.model = model
        self.language = language_label

    def decide(self, line_image: np.ndarray, options: list[str]) -> tuple[int, str, float]:
        """Liefert (gewählte Option oder -1, Lesung, Sicherheit 0–1)."""
        schema = {
            "type": "object",
            "properties": {
                "choice": {"type": "integer"},
                "reading": {"type": "string"},
                "certain": {"type": "number"},
            },
            "required": ["choice", "reading", "certain"],
        }
        listed = "\n".join(f"{i + 1}: {o}" for i, o in enumerate(options))
        prompt = (
            f"The image shows one line from a historical {self.language} document. Two OCR engines read it as:\n"
            f"{listed}\n\nLook only at the image. Which reading matches the image exactly, character by character? "
            "Answer with choice = 1 or 2, or 0 if neither is exact; reading = the exact text of the line as you see it "
            "(diplomatic, do not modernise); certain = your confidence between 0 and 1. Do not guess: if parts are "
            "unreadable, use [?] there and lower certain."
        )
        msg = OllamaClient.image_message(prompt, [encode_png(line_image, max_side=1600)])
        try:
            res = self.client.chat(self.model, [msg], json_schema=schema, num_ctx=MAIN_CTX, num_predict=300)
            data = json.loads(res.text)
            choice = int(data.get("choice", 0)) - 1
            return (choice if 0 <= choice < len(options) else -1, str(data.get("reading", "")), float(data.get("certain", 0)))
        except (OllamaError, ValueError, TypeError):
            return -1, "", 0.0

    def transcribe_line(self, line_image: np.ndarray, page_thumb: np.ndarray | None, previous: str = "",
                        period: str = "") -> Reading:
        prompt = (
            f"You are an expert palaeographer for historical {self.language} handwriting{(' of the ' + period) if period else ''}. "
            "The LAST image is one single line of handwriting. "
            + ("The first image shows the whole page for context only. " if page_thumb is not None else "")
            + (f'The previous line read: "{previous}". ' if previous else "")
            + "Transcribe ONLY the single line in the last image. "
            + _DIPLOMATIC_RULES
        )
        images = ([encode_png(page_thumb, max_side=1024)] if page_thumb is not None else []) + [
            encode_png(line_image, max_side=1800)
        ]
        res = self.client.chat(
            self.model, [OllamaClient.image_message(prompt, images)],
            num_ctx=MAIN_CTX, num_predict=200, logprobs=True, repeat_penalty=1.1,
        )
        text = _clean_ocr(res.text).split("\n")[0].strip()
        return Reading(text, res.logprobs)

    def transcribe_region(self, image: np.ndarray, period: str = "") -> Reading:
        prompt = (
            f"Transcribe this region of a historical {self.language} document{(' of the ' + period) if period else ''}, "
            "line by line, keeping line breaks. " + _DIPLOMATIC_RULES
        )
        res = self.client.chat(
            self.model, [OllamaClient.image_message(prompt, [encode_png(image, max_side=2000)])],
            num_ctx=MAIN_CTX, num_predict=1500, logprobs=True, repeat_penalty=1.1,
        )
        return Reading(_clean_ocr(res.text), res.logprobs)
