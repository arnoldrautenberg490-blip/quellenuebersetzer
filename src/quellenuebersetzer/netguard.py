"""Netzwerksperre während der Dokumentverarbeitung.

Solange eine Verarbeitung läuft, sind im Programmprozess nur Verbindungen zum eigenen
Rechner (127.0.0.1 / ::1) erlaubt – das ist die lokale Modell-Laufzeit. Jeder andere
Verbindungsversuch, gleich aus welcher Bibliothek, wird blockiert und protokolliert.
So ist technisch ausgeschlossen, dass Inhalte unbemerkt nach außen gelangen.

Die Bausteine Ollama, Tesseract, Pandoc und Typst laufen als eigene Prozesse. Ollama ist
auf 127.0.0.1 gebunden und mit OLLAMA_NO_CLOUD betrieben; Tesseract, Pandoc und Typst
werden ausschließlich mit lokalen Dateien aufgerufen (Pandoc mit ``--sandbox``).
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from contextlib import contextmanager

_LOCK = threading.Lock()
_DEPTH = 0
_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_ORIGINAL_CREATE_CONNECTION = socket.create_connection

blocked_attempts: list[str] = []


class NetworkBlocked(ConnectionError):
    pass


def _is_local(host) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return False


def _check(address) -> None:
    if not (isinstance(address, tuple) and address):
        return  # AF_UNIX-Pfade u. ä. sind lokal
    host = address[0]
    if not _is_local(host):
        blocked_attempts.append(str(host))
        raise NetworkBlocked(f"Verbindung nach außen blockiert ({host}). Während der Verarbeitung ist das Netzwerk gesperrt.")


def _guarded_connect(self, address):
    _check(address)
    return _ORIGINAL_CONNECT(self, address)


def _guarded_connect_ex(self, address):
    _check(address)
    return _ORIGINAL_CONNECT_EX(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if host is not None and not _is_local(host if not isinstance(host, bytes) else host.decode()):
        blocked_attempts.append(str(host))
        raise NetworkBlocked(f"Namensauflösung blockiert ({host}). Während der Verarbeitung ist das Netzwerk gesperrt.")
    return _ORIGINAL_GETADDRINFO(host, *args, **kwargs)


def _guarded_create_connection(address, *args, **kwargs):
    _check(address)
    return _ORIGINAL_CREATE_CONNECTION(address, *args, **kwargs)


# Tote lokale Adresse (Port 9 = „discard“, dort lauscht niemand): Programme, die Proxy-Variablen beachten
# (Ollama/Go, Typst, Pandoc), können darüber keine Verbindung nach außen aufbauen.
BLACKHOLE_PROXY = "http://127.0.0.1:9"


def offline_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Umgebung für Hilfsprozesse während der Verarbeitung: nur der eigene Rechner ist erreichbar."""
    import os

    env = dict(base if base is not None else os.environ)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[key] = BLACKHOLE_PROXY
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost,::1"
    return env


def is_active() -> bool:
    return _DEPTH > 0


@contextmanager
def offline():
    """Kontext, in dem nur lokale Verbindungen möglich sind (verschachtelbar, prozessweit)."""
    global _DEPTH
    with _LOCK:
        _DEPTH += 1
        if _DEPTH == 1:
            socket.socket.connect = _guarded_connect
            socket.socket.connect_ex = _guarded_connect_ex
            socket.getaddrinfo = _guarded_getaddrinfo
            socket.create_connection = _guarded_create_connection
    try:
        yield
    finally:
        with _LOCK:
            _DEPTH -= 1
            if _DEPTH == 0:
                socket.socket.connect = _ORIGINAL_CONNECT
                socket.socket.connect_ex = _ORIGINAL_CONNECT_EX
                socket.getaddrinfo = _ORIGINAL_GETADDRINFO
                socket.create_connection = _ORIGINAL_CREATE_CONNECTION
