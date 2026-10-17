"""Update-Prüfung – nur auf ausdrücklichen Knopfdruck, nie automatisch.

Es wird ausschließlich die öffentliche Versionsliste auf GitHub abgefragt; es werden keine
Daten über den Nutzer, den Rechner oder Dokumente übertragen.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from quellenuebersetzer import __version__, netguard

REPO = "arnoldrautenberg490-blip/quellenuebersetzer"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"


@dataclass
class UpdateInfo:
    current: str
    latest: str | None
    url: str
    newer: bool
    error: str = ""


def _parse(v: str) -> tuple[int, ...]:
    out = []
    for part in v.lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out)


def check() -> UpdateInfo:
    if netguard.is_active():
        return UpdateInfo(__version__, None, RELEASES_URL, False, "Während einer Verarbeitung ist das Netzwerk gesperrt.")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Quellenuebersetzer-Updatepruefung"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except Exception as exc:  # noqa: BLE001 – jede Störung ergibt eine verständliche Meldung
        return UpdateInfo(__version__, None, RELEASES_URL, False, f"Keine Verbindung zur Versionsliste ({type(exc).__name__}).")
    latest = data.get("tag_name", "")
    return UpdateInfo(__version__, latest, data.get("html_url", RELEASES_URL), _parse(latest) > _parse(__version__))
