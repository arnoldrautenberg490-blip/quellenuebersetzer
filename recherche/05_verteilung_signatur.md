# Phase 0 – Verteilung, Signatur, Bausteine (Stand 2026-10-16)

## Empfehlung
1. **Hauptweg:** PyInstaller onedir ohne UPX + Inno Setup per Benutzer (`PrivilegesRequired=lowest`), Build über GitHub Actions, Antrag SignPath Foundation.
2. Bausteine zur Laufzeit von offiziellen GitHub-Releases laden, SHA-256 prüfen → wir verteilen keine Fremd-Binärdateien (Lizenz einfacher, z. B. Pandoc GPL).
3. **Microsoft Store (MSIX)** optional als Pilot – einziger Weg ganz ohne SmartScreen, aber Policy-Risiko.

## Microsoft Store
- Registrierung kostenlos für Einzelentwickler (seit 10.09.2025), Ausweis + Selfie.
- MSIX: Microsoft signiert kostenlos; EXE/MSI im Store: Entwickler muss selbst mit CA-Zertifikat signieren (10.2.9) → kein kostenloser Weg.
- Risiken: Policy 10.2.2 (nachgeladener Code), 11.16 (KI-Inhalte offenlegen + Meldefunktion), Dateivirtualisierung/Kindprozesse.
- Deinstallation entfernt virtualisierte AppData; vorher existierende Ordner (z. B. `~/.ollama`) bleiben.
- Automatisierung: `msstore` CLI + GitHub Action nach erster manueller Einreichung.

## SignPath Foundation (signpath.org/terms)
- OSI-Lizenz, aktiv gepflegt, bereits veröffentlicht, MFA, Rollen Author/Reviewer/Approver, reproduzierbarer CI-Build, manuelle Freigabe je Signatur, Seite „Code signing policy“, Datenschutzhinweis, Deinstallation; Fremd-Binärdateien nicht signieren.
- Annahme nach Ermessen; neues Ein-Personen-Projekt evtl. schlechtere Chancen.
- SmartScreen: auch signiert anfangs Warnung, Reputation wächst; Smart App Control (Win 11) blockiert unsignierte Dateien.
- Alternativen kostenpflichtig (Azure Artifact Signing ~9,99 $/Monat, nur USA/CA für Einzelpersonen; OV 150–300 $/Jahr).

## Paketierung
- onefile + UPX = meiste Fehlalarme; onedir ohne UPX + Versionsinfo + Signatur deutlich besser.
- Nuitka: Einzelberichte weniger Treffer, bei PySide6 aufwendiger.
- Embedded Python (python.org, PSF-signierte python.exe) / Briefcase: gute AV-Option, mehr Eigenarbeit.
- Vor Release VirusTotal; Fehlalarme an microsoft.com/en-us/wdsi/filesubmission.

## Inno Setup
- `PrivilegesRequired=lowest`, `DefaultDirName={localappdata}\Programs\<App>`, Eintrag in HKCU/Apps & Features, kein UAC.
- `[UninstallDelete]` nur feste eigene Unterordner (`runtime`, `models`, `cache`), keine Wildcards.
- Ggf. `~/.ollama` entfernen, falls von uns angelegt (prüfen).

## Bausteine
| Baustein | Version | Paket | Lizenz | Hinweise |
|---|---|---|---|---|
| Ollama | v0.40.5 (14.10.2026) | `ollama-windows-amd64.zip` | MIT | `ollama serve` einbettbar; `OLLAMA_HOST=127.0.0.1:<eigener Port>`, `OLLAMA_MODELS`, `OLLAMA_NO_CLOUD=1`; ZIP vermutlich ohne Updater; Telemetrie-Abschaltung undokumentiert |
| Tesseract | **5.5.3** (Upstream 24.07.2026; UB-Mannheim-Wiki verlinkt `tesseract-ocr-w64-setup-5.5.3.20260724.exe` – selbst geprüft 16.10.2026; GitHub-Releases von UB Mannheim enden bei 5.4.0, Download-Ort für Phase 2 festlegen) | NSIS-Installer, per 7-Zip entpackbar; Alternative conda-forge | Apache-2.0 | keine Prüfsumme in API → selbst festlegen |
| Pandoc | 3.12.1 (08.10.2026) | `pandoc-3.12.1-windows-x86_64.zip` | GPL-2.0+ | zur Laufzeit laden statt mitliefern |
| Typst | 0.15.1 (17.07.2026) | `typst-x86_64-pc-windows-msvc.zip` | Apache-2.0 | eine EXE |
| Kraken | 7.1.1 | – | Apache-2.0 | kein natives Windows → optional/weglassen |

## Offen
SignPath-Annahme; Store-Prüfung mit Nachladen; Ollama-Reste in `~/.ollama`; Tesseract-Version klären.
