"""Aufruf der portablen Tesseract-Installation mit Wort-Konfidenzen (TSV)."""

from __future__ import annotations

import csv
import io
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from quellenuebersetzer.config import Paths

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class TesseractError(Exception):
    pass


@dataclass
class Word:
    text: str
    conf: float  # 0–100
    bbox: tuple[int, int, int, int]


@dataclass
class Line:
    words: list[Word]
    bbox: tuple[int, int, int, int]
    block: int
    par: int

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def min_conf(self) -> float:
        return min((w.conf for w in self.words), default=0.0)

    @property
    def height(self) -> int:
        return self.bbox[3] - self.bbox[1]


@dataclass
class OcrPage:
    lines: list[Line] = field(default_factory=list)


class Tesseract:
    def __init__(self, paths: Paths):
        self.exe = paths.runtime / "tesseract" / "tesseract.exe"
        self.tessdata = paths.runtime / "tesseract" / "tessdata"

    @property
    def available(self) -> bool:
        return self.exe.exists()

    def languages(self) -> list[str]:
        return sorted(p.stem for p in self.tessdata.glob("*.traineddata"))

    def run_tsv(self, image: np.ndarray, langs: list[str], psm: int = 3) -> OcrPage:
        import cv2

        ok, buf = cv2.imencode(".png", image)
        if not ok:
            raise TesseractError("Bild konnte nicht kodiert werden.")
        langs = [l for l in langs if (self.tessdata / f"{l}.traineddata").exists()] or ["pol"]
        from quellenuebersetzer.netguard import offline_env

        env = {**offline_env(), "TESSDATA_PREFIX": str(self.tessdata), "OMP_THREAD_LIMIT": "4"}
        cmd = [str(self.exe), "stdin", "stdout", "-l", "+".join(langs), "--psm", str(psm),
               "-c", "preserve_interword_spaces=1", "tsv"]
        r = subprocess.run(cmd, input=buf.tobytes(), capture_output=True, env=env, creationflags=_NO_WINDOW, timeout=600)
        if r.returncode != 0:
            # Fehlermeldung ohne Textinhalte weitergeben
            raise TesseractError(f"Texterkennung fehlgeschlagen (Code {r.returncode}).")
        return parse_tsv(r.stdout.decode("utf-8", "replace"))


def parse_tsv(tsv: str) -> OcrPage:
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    lines: dict[tuple[int, int, int], list[Word]] = {}
    for row in reader:
        try:
            if int(row["level"]) != 5:
                continue
            text = row["text"]
            conf = float(row["conf"])
        except (KeyError, ValueError, TypeError):
            continue
        if not text or not text.strip() or conf < 0:
            continue
        x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
        key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        lines.setdefault(key, []).append(Word(text.strip(), conf, (x, y, x + w, y + h)))
    page = OcrPage()
    for (block, par, _), words in lines.items():
        x0 = min(w.bbox[0] for w in words)
        y0 = min(w.bbox[1] for w in words)
        x1 = max(w.bbox[2] for w in words)
        y1 = max(w.bbox[3] for w in words)
        page.lines.append(Line(words, (x0, y0, x1, y1), block, par))
    page.lines.sort(key=lambda l: (l.block, l.par, l.bbox[1]))
    return page
