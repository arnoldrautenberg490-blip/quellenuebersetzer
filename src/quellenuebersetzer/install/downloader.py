"""Downloads mit Fortsetzen nach Abbruch und SHA-256-Prüfung."""

from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from quellenuebersetzer import __version__

ProgressFn = Callable[[int, int], None]  # (erhalten, gesamt)

_CHUNK = 1024 * 1024
_USER_AGENT = f"Quellenuebersetzer/{__version__} (+https://github.com/arnoldrautenberg490-blip/quellenuebersetzer)"


class DownloadError(Exception):
    pass


class Cancelled(Exception):
    pass


def _hash_file(path: Path, hasher) -> None:
    with path.open("rb") as fh:
        while block := fh.read(_CHUNK):
            hasher.update(block)


def download(
    url: str,
    dest: Path,
    sha256: str,
    size: int | None = None,
    progress: ProgressFn | None = None,
    should_cancel: Callable[[], bool] | None = None,
    retries: int = 4,
    mirrors: tuple[str, ...] | list[str] = (),
) -> Path:
    """Lädt ``url`` nach ``dest``. Bereits vorhandene, korrekte Dateien werden nicht erneut geladen.

    Ist eine Adresse nicht erreichbar, werden die ``mirrors`` der Reihe nach versucht; angenommen wird nur
    eine Datei mit der erwarteten Prüfsumme."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    expected = sha256.lower()

    if dest.exists():
        h = hashlib.sha256()
        _hash_file(dest, h)
        if h.hexdigest() == expected:
            if progress:
                progress(dest.stat().st_size, dest.stat().st_size)
            return dest
        dest.unlink()

    part = dest.with_name(dest.name + ".part")
    sources = [url, *mirrors]
    for k, source in enumerate(sources):
        try:
            _fetch_with_retries(source, part, size, progress, should_cancel, retries if k == len(sources) - 1 else 1)
            break
        except DownloadError:
            if k == len(sources) - 1:
                raise

    h = hashlib.sha256()
    _hash_file(part, h)
    if h.hexdigest() != expected:
        part.unlink(missing_ok=True)
        raise DownloadError(
            f"Prüfsumme stimmt nicht für {dest.name}. Die Datei wurde verworfen (möglicherweise beschädigt)."
        )
    part.replace(dest)
    return dest


def _fetch_with_retries(url, part: Path, size, progress, should_cancel, retries: int) -> None:
    attempt = 0
    while True:
        attempt += 1
        try:
            _download_once(url, part, size, progress, should_cancel)
            return
        except Cancelled:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 416:
                part.unlink(missing_ok=True)  # Teildatei ungültig → von vorn
            if attempt > retries:
                raise DownloadError(f"Download fehlgeschlagen: {url} ({exc})") from exc
            time.sleep(min(30, 2**attempt))


def _download_once(url, part: Path, size, progress, should_cancel) -> None:
    have = part.stat().st_size if part.exists() else 0
    if size and have == size:
        return
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    if have:
        req.add_header("Range", f"bytes={have}-")
    with urllib.request.urlopen(req, timeout=60) as resp:
        if have and resp.status != 206:
            have = 0  # Server unterstützt kein Fortsetzen
        total = size or (int(resp.headers.get("Content-Length", 0)) + have)
        mode = "ab" if have else "wb"
        with part.open(mode) as fh:
            received = have
            while True:
                if should_cancel and should_cancel():
                    raise Cancelled()
                block = resp.read(_CHUNK)
                if not block:
                    break
                fh.write(block)
                received += len(block)
                if progress:
                    progress(received, total)
