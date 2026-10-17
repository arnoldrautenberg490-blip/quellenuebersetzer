"""Ein winziger Ersatz für die Ollama-API, um die Abläufe ohne echte Modelle zu testen."""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WORDS = {
    "akta": "Akten", "miasta": "der Stadt", "krakowa": "Krakau", "z": "aus", "roku": "dem Jahr",
    "starosta": "Starost", "grodowy": "Burg-", "zatwierdził": "bestätigte", "przywilej": "das Privileg",
    "dla": "für", "cechu": "die Zunft", "młynarzy": "der Müller", "i": "und", "nakazał": "ordnete an",
    "aby": "dass", "każdy": "jede", "młyn": "Mühle", "płacił": "zahle", "dwa": "zwei", "złote": "Złoty",
    "rocznie": "jährlich", "świadkowie": "Zeugen", "razem": "Summe", "miejscowość": "Ort", "młyny": "Mühlen",
}


def fake_translate(text: str) -> str:
    def word(m: re.Match) -> str:
        w = m.group(0)
        return WORDS.get(w.lower(), w)

    # Tags und HTML unverändert lassen, nur Textteile „übersetzen“
    parts = re.split(r"(<[^>]+>)", text)
    return "".join(p if p.startswith("<") else re.sub(r"[^\W\d_]+", word, p) for p in parts)


class Handler(BaseHTTPRequestHandler):
    calls: list[str] = []

    def log_message(self, *args):  # still
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/version":
            self._send({"version": "0.0-test"})
        elif self.path == "/api/tags":
            self._send({"models": []})
        else:
            self.send_error(404)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = data.get("messages", [])
        last = msgs[-1]["content"] if msgs else ""
        system = msgs[0]["content"] if msgs and msgs[0]["role"] == "system" else ""
        if last.startswith("Text Recognition:"):
            Handler.calls.append("ocr")
            content = ""
        elif "choice" in json.dumps(data.get("format") or {}):
            Handler.calls.append("judge")
            content = json.dumps({"choice": 1, "reading": "", "certain": 0.9})
        elif "You translate historical" in system:
            Handler.calls.append("translate")
            user = [m for m in msgs if m["role"] == "user"][0]["content"]
            src = user[user.rfind("Translate "):].split(":\n", 1)[1]
            ids = re.findall(r"- (a_\d+): (.*)", user)
            translation = fake_translate(src)
            terms = []
            if "Starost" in translation and "<a_" not in translation.split("Starost")[0][-6:]:
                translation = translation.replace("Starost", "<b2_1>Starost</b2_1>", 1)
                terms.append({"id": "b2_1", "original": "starosta", "explanation": "königlicher Amtsträger", "evidence": ""})
            content = json.dumps({
                "translation": translation,
                "readings": [{"id": i, "translations": [fake_translate(x.strip()) for x in alts.split("|")]} for i, alts in ids],
                "terms": terms,
            }, ensure_ascii=False)
        elif "palaeographer" in last:
            Handler.calls.append("htr")
            content = "Akta miasta Krakowa"
        else:
            Handler.calls.append("other")
            content = "Dzień dobry → Guten Tag"
        self._send({"message": {"role": "assistant", "content": content}, "done": True})


class FakeOllama:
    def __init__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        Handler.calls = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()

    @property
    def calls(self):
        return Handler.calls
