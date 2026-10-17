"""Download mit Ersatzadressen: unerreichbarer Server → nächste Adresse, nur bei passender Prüfsumme."""

import hashlib
import urllib.error

import pytest

from quellenuebersetzer.install import downloader


def _fake(monkeypatch, files: dict[str, bytes], calls: list[str]):
    def once(url, part, size, progress, should_cancel):
        calls.append(url)
        if url not in files:
            raise urllib.error.URLError("Verbindung abgelehnt")
        part.write_bytes(files[url])

    monkeypatch.setattr(downloader, "_download_once", once)
    monkeypatch.setattr(downloader.time, "sleep", lambda s: None)


def test_unreachable_source_falls_back_to_mirror(tmp_path, monkeypatch):
    data = b"Schriftmodell"
    calls: list[str] = []
    _fake(monkeypatch, {"https://kopie/x": data}, calls)
    out = downloader.download("https://original/x", tmp_path / "x", hashlib.sha256(data).hexdigest(),
                              mirrors=["https://kopie/x"])
    assert out.read_bytes() == data
    assert calls[0] == "https://original/x" and calls[-1] == "https://kopie/x"
    assert calls.count("https://original/x") == 2  # kurz erneut versucht, dann weiter zur Ersatzadresse


def test_mirror_with_wrong_checksum_is_rejected(tmp_path, monkeypatch):
    calls: list[str] = []
    _fake(monkeypatch, {"https://kopie/x": b"falsch"}, calls)
    with pytest.raises(downloader.DownloadError):
        downloader.download("https://original/x", tmp_path / "x", hashlib.sha256(b"echt").hexdigest(),
                            mirrors=["https://kopie/x"])
    assert not (tmp_path / "x").exists()


def test_all_sources_unreachable_raises(tmp_path, monkeypatch):
    calls: list[str] = []
    _fake(monkeypatch, {}, calls)
    with pytest.raises(downloader.DownloadError):
        downloader.download("https://a/x", tmp_path / "x", "0" * 64, mirrors=["https://b/x"], retries=2)
    assert calls == ["https://a/x"] * 2 + ["https://b/x"] * 3
