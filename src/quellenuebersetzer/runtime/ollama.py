"""Eigene, lokal gebundene Ollama-Instanz und ein schlanker Client dafür.

Ollama lauscht ausschließlich auf 127.0.0.1 und einem eigenen Port. Cloud-Funktionen
sind abgeschaltet. Auch das Ollama-Benutzerverzeichnis (Schlüssel, Einstellungen) wird
in den Programmordner umgelenkt, damit die Deinstallation nichts zurücklässt.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from quellenuebersetzer.config import OLLAMA_PORT, Paths


class OllamaError(Exception):
    pass


@dataclass
class TokenLogprob:
    token: str
    logprob: float


@dataclass
class ChatResult:
    text: str
    logprobs: list[TokenLogprob]


class OllamaClient:
    def __init__(self, host: str = "127.0.0.1", port: int = OLLAMA_PORT, timeout: float = 900):
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Ollama darf nur lokal angesprochen werden.")
        self.base = f"http://{host}:{port}"
        self.timeout = timeout
        # Laufzeitmessung je Modell (ohne Inhalte): Anfragen, Sekunden, Eingabe-/Ausgabe-Token
        self.stats: dict[str, dict[str, float]] = {}

    # ------------------------------------------------------------------ intern
    def _request(self, path: str, payload: dict | None = None, timeout: float | None = None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET"
        )
        return urllib.request.urlopen(req, timeout=timeout or self.timeout)

    def _stream(self, path: str, payload: dict) -> Iterator[dict]:
        with self._request(path, payload) as resp:
            for line in resp:
                line = line.strip()
                if line:
                    msg = json.loads(line)
                    if "error" in msg:
                        raise OllamaError(msg["error"])
                    yield msg

    # ------------------------------------------------------------------ API
    def is_up(self) -> bool:
        try:
            with self._request("/api/version", timeout=2) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def list_models(self) -> list[str]:
        with self._request("/api/tags", timeout=10) as resp:
            return [m["name"] for m in json.load(resp).get("models", [])]

    def pull(self, model: str, progress: Callable[[int, int, str], None] | None = None,
             should_cancel: Callable[[], bool] | None = None) -> None:
        """Lädt ein Modell. Ollama prüft dabei die Prüfsummen aller Teile selbst."""
        layers: dict[str, tuple[int, int]] = {}
        for msg in self._stream("/api/pull", {"model": model, "stream": True}):
            if should_cancel and should_cancel():
                raise InterruptedError()
            digest = msg.get("digest")
            if digest and msg.get("total"):
                layers[digest] = (msg.get("completed", 0), msg["total"])
            if progress:
                done = sum(c for c, _ in layers.values())
                total = sum(t for _, t in layers.values())
                progress(done, total, msg.get("status", ""))
            if msg.get("status") == "success":
                return
        raise OllamaError(f"Modell {model} konnte nicht vollständig geladen werden.")

    def delete(self, model: str) -> None:
        req = urllib.request.Request(
            self.base + "/api/delete", data=json.dumps({"model": model}).encode(), method="DELETE",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=60).close()
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise

    def chat(
        self,
        model: str,
        messages: list[dict],
        *,
        temperature: float = 0.0,
        num_ctx: int = 8192,
        num_predict: int | None = None,
        json_schema: dict | None = None,
        logprobs: bool = False,
        top_logprobs: int = 0,
        think: bool | None = False,
        seed: int = 42,
        repeat_penalty: float | None = None,
    ) -> ChatResult:
        options = {"temperature": temperature, "num_ctx": num_ctx, "seed": seed}
        if num_predict:
            options["num_predict"] = num_predict
        if repeat_penalty:
            options["repeat_penalty"] = repeat_penalty
        payload: dict = {"model": model, "messages": messages, "stream": False, "options": options, "keep_alive": "10m"}
        if think is not None:
            payload["think"] = think
        if json_schema is not None:
            payload["format"] = json_schema
        if logprobs:
            payload["logprobs"] = True
            if top_logprobs:
                payload["top_logprobs"] = top_logprobs
        started = time.time()
        try:
            with self._request("/api/chat", payload) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            raise OllamaError(f"Modell {model}: {exc.code} {body}") from exc
        except urllib.error.URLError as exc:
            raise OllamaError(f"Die lokale Modell-Laufzeit antwortet nicht ({exc.reason}).") from exc
        st = self.stats.setdefault(model, {"anfragen": 0, "sekunden": 0.0, "eingabe": 0, "ausgabe": 0,
                                           "eingabe_s": 0.0, "ausgabe_s": 0.0, "laden_s": 0.0})
        st["anfragen"] += 1
        st["sekunden"] += time.time() - started
        st["eingabe"] += data.get("prompt_eval_count") or 0
        st["ausgabe"] += data.get("eval_count") or 0
        st["eingabe_s"] += (data.get("prompt_eval_duration") or 0) / 1e9
        st["ausgabe_s"] += (data.get("eval_duration") or 0) / 1e9
        st["laden_s"] += (data.get("load_duration") or 0) / 1e9
        lp = [TokenLogprob(t.get("token", ""), float(t.get("logprob", 0.0))) for t in data.get("logprobs") or []]
        return ChatResult(text=data.get("message", {}).get("content", ""), logprobs=lp)

    @staticmethod
    def image_message(prompt: str, images: list[bytes], role: str = "user") -> dict:
        return {"role": role, "content": prompt, "images": [base64.b64encode(i).decode("ascii") for i in images]}


def tuning_for(gpu_name: str, vram_gb: float) -> dict[str, str]:
    """Laufzeit-Einstellungen passend zur Grafikkarte (automatisch, ohne Zutun des Nutzers).

    - RTX-Karten (Tensor-Kerne): Flash Attention und komprimierter Zwischenspeicher → mehr Kontext, weniger Speicher.
      Auf GTX-Karten bleibt beides aus (dort teils langsamer oder nicht stabil).
    - Ab 16 GB: Lese- und Übersetzungsmodell bleiben gleichzeitig geladen (kein Umladen).
    - Ab 12 GB: zwei Anfragen parallel.
    """
    t: dict[str, str] = {"OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_NUM_PARALLEL": "1"}
    name = (gpu_name or "").upper()
    if "RTX" in name and vram_gb >= 8:
        t["OLLAMA_FLASH_ATTENTION"] = "1"
        t["OLLAMA_KV_CACHE_TYPE"] = "q8_0"
    if vram_gb >= 16:
        t["OLLAMA_MAX_LOADED_MODELS"] = "2"
    if vram_gb >= 12:
        t["OLLAMA_NUM_PARALLEL"] = "2"
    return t


class OllamaService:
    """Startet und beendet die programmeigene Ollama-Instanz."""

    def __init__(self, paths: Paths, tuning: dict[str, str] | None = None):
        self.tuning = tuning or {}
        self.paths = paths
        self.exe = paths.runtime / "ollama" / "ollama.exe"
        self.home = paths.runtime / "ollama-home"
        self.proc: subprocess.Popen | None = None
        self.mode: str | None = None  # "offline" (Verarbeitung) | "online" (Modell-Download)
        self.client = OllamaClient()

    @property
    def installed(self) -> bool:
        return self.exe.exists()

    def environment(self, offline: bool = True) -> dict[str, str]:
        from quellenuebersetzer.netguard import offline_env

        # Offline: alle ausgehenden Verbindungen der Laufzeit laufen ins Leere, nur 127.0.0.1 ist erreichbar.
        env = offline_env() if offline else dict(os.environ)
        env.update(
            {
                "OLLAMA_HOST": f"127.0.0.1:{OLLAMA_PORT}",
                "OLLAMA_MODELS": str(self.paths.models),
                "OLLAMA_NO_CLOUD": "1",
                "OLLAMA_KEEP_ALIVE": "10m",
                "OLLAMA_MAX_LOADED_MODELS": "1",
                "OLLAMA_NUM_PARALLEL": "1",
                **self.tuning,
                # Schlüssel und Einstellungen von Ollama landen im Programmordner, nicht in %USERPROFILE%\.ollama
                "USERPROFILE": str(self.home),
                "HOME": str(self.home),
            }
        )
        env.pop("OLLAMA_DEBUG", None)
        return env

    def start(self, timeout: float = 60, offline: bool = True) -> None:
        """Startet die Laufzeit. ``offline=False`` nur für das Herunterladen von Modellen."""
        wanted = "offline" if offline else "online"
        if self.client.is_up():
            if self.proc is not None and self.mode == wanted:
                return
            # anderer Modus oder fremd gestartete Instanz (z. B. aus einer früheren Sitzung) → neu starten
            self.stop()
            self._stop_leftovers()
        if not self.installed:
            raise OllamaError("Die Modell-Laufzeit ist nicht installiert.")
        self.home.mkdir(parents=True, exist_ok=True)
        self.paths.models.mkdir(parents=True, exist_ok=True)
        self.paths.logs.mkdir(parents=True, exist_ok=True)
        log = (self.paths.logs / "ollama.log").open("ab")
        self.proc = subprocess.Popen(
            [str(self.exe), "serve"],
            env=self.environment(offline),
            cwd=str(self.exe.parent),
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.mode = wanted
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.client.is_up():
                return
            if self.proc.poll() is not None:
                raise OllamaError("Die Modell-Laufzeit hat sich unerwartet beendet. Details: logs/ollama.log")
            time.sleep(0.5)
        raise OllamaError("Die Modell-Laufzeit startet nicht. Details: logs/ollama.log")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.mode = None

    def _stop_leftovers(self) -> None:
        """Beendet programmeigene Ollama-Prozesse (erkennbar am Pfad), nie fremde Installationen."""
        import psutil

        own = self.exe.parent.resolve()
        for proc in psutil.process_iter(["exe"]):
            try:
                exe = proc.info.get("exe")
                if exe and own in Path(exe).resolve().parents:
                    proc.terminate()
                    proc.wait(timeout=10)
            except (psutil.Error, OSError):
                continue
        deadline = time.time() + 10
        while self.client.is_up() and time.time() < deadline:
            time.sleep(0.3)
