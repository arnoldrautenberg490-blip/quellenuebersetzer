# Phase 0 – Gesamtempfehlung zur Freigabe (Stand 2026-10-16)

Grundlage: Einzelberichte 01–05 in diesem Ordner. Alle genannten Bausteine sind kostenlos, ohne Konto nutzbar und
mit offener Lizenz weitergebbar, sofern nicht anders vermerkt.

## 1. Modellpaket je Hardwarestufe

Kernidee: **Gemma 4 übernimmt Übersetzung UND Bildprüfung** (es kann Bilder lesen). Dazu kommt das kleine
Spezialmodell **GLM-OCR** für Texterkennung und Tabellen. So bleiben die Downloads pro Stufe übersichtlich.

| Stufe | Grafikspeicher | Übersetzung + Bildprüfung | Texterkennung/Tabellen | Ampel |
|---|---|---|---|---|
| 1 | ≥ 24 GB | `gemma4:31b-it-qat` (19 GB) | `glm-ocr` (2,7 GB) + Tesseract | 🟢 optimal |
| 2 | 16 GB | `gemma4:12b-it-q8_0` (13 GB) | `glm-ocr` + Tesseract | 🟢 optimal für Druck, 🟡 Handschrift |
| 3 | 12 GB | `gemma4:12b-it-qat` (7,2 GB) | `glm-ocr` + Tesseract | 🟡 eingeschränkt |
| 4 | 8 GB | `gemma4:e4b-it-qat` (6,1 GB) | `glm-ocr` + Tesseract | 🟡 eingeschränkt, Handschrift 🔴 |
| 5 | ohne passende GPU | `translategemma:4b` / `gemma4:e2b` (CPU, langsam) | Tesseract | 🔴 nur Notbetrieb für sauberen Druck |

Alternativen, die im Vergleichstest gegen Gemma 4 antreten: **Qwen3.5** (9b/27b, Apache-2.0),
**EuroLLM-22B** (Apache-2.0), **TranslateGemma** (Gemma-Lizenz; stark, aber nur 2K Eingabe und ohne Strukturerhalt).

Ausgeschlossen wegen Lizenz: Hunyuan-MT (gilt nicht in der EU), Tower+ (nicht kommerziell), NLLB (nicht kommerziell),
Chandra OCR, Surya, Marker (eingeschränkte Modelllizenzen), CHURRO (nur Forschung).

**Wichtig:** Für Polnisch→Deutsch und für historisches Polnisch gibt es keine veröffentlichten Benchmarks.
Die endgültige Modellwahl erfolgt nach einem eigenen Vergleichstest (Abschnitt 6).

## 2. Lesen nach Quellenart

| Quellenart | Ablauf | Erwartung |
|---|---|---|
| Sauberer Druck / Schreibmaschine | Bildaufbereitung → Tesseract `pol` (mit Wort-Konfidenz) + GLM-OCR → zeilenweiser Abgleich → nur strittige Zeilen an Gemma 4 mit Bildausschnitt | sehr gut |
| Alter Druck / Fraktur | Tesseract `frak2021+pol` (UB Mannheim) + Gemma 4 als zweite Lesung → Abweichungen **markieren statt ersetzen** | gut, mit Markierungen |
| Tabellen | Docling (Seitenaufbau, Tabellenraster) → GLM-OCR „Table Recognition“ → HTML-Tabelle im Markdown (verbundene Zellen bleiben erhalten) → Tesseract als Zahlenkontrolle, Plausibilitätsprüfung | gut, schwierige Tabellen mit Markierungen |
| Handschrift | Zeilenzerlegung → Gemma 4 liest zeilenweise mit Seitenkontext → Doppellesung + Wahrscheinlichkeiten (logprobs) → Markierung | **Rohfassung**, Nachkorrektur nötig |

Leitregeln aus der Forschung (ICDAR 2026): Sprachmodelle korrigieren sauberen Text zu stark → das Sprachmodell darf
nur strittige Wörter ersetzen, Längenprüfung, im Zweifel Rückfall auf den Tesseract-Text.

## 3. Handschrift – ehrliche Einordnung

- Allgemeine Modelle verlesen bei schwieriger historischer Handschrift heute noch 30–55 % der Zeichen; bei sauberer
  Schrift des 19./20. Jh. deutlich weniger. Gute Werte (3–8 %) erst nach Training auf eigene Bestände.
- Kraken läuft unter Windows nicht nativ → **nicht** als Pflichtbaustein. Zeilenzerlegung wird in Phase 3 nativ gelöst
  (klassische Bildverarbeitung bzw. Docling-Layout; bei Bedarf ein kleines, selbst trainiertes Modell).
- **Ausbaustufe „Eigene Bestände lernen“:** Korrigierte Seiten aus der Kontrollansicht werden gesammelt; ab ca.
  1.000–2.000 Zeilen kann das Programm lokal ein angepasstes Lesemodell trainieren (LoRA-Feintuning, 12–24 GB).

## 4. Wörterbücher (Polnisch, automatisch mitinstalliert)

| Baustein | Zweck | Lizenz |
|---|---|---|
| Wikisłownik (aufbereitet) | Grundwörterbuch, Kennzeichnungen „veraltet“ → Hinweise auf B1 | CC BY-SA |
| Gloger, *Encyklopedja staropolska* (Wikisource) | Hauptglossar B2: Ämter, Stände, Maße, Münzen, Recht | gemeinfrei / CC BY-SA |
| Słowosieć 4.2 | heutige Bedeutungen als Vergleich | frei, Hinweispflicht |
| Słownik warszawski, Linde | historische Bedeutungen (von mir aus den OCR-Fassungen aufbereitet) | gemeinfrei |
| Bandtkie 1806, Mrongovius | zeitgenössische deutsche Entsprechungen (spätere Ausbaustufe, Fraktur-OCR) | gemeinfrei |

Nicht mitlieferbar (geschützt/ungeklärt): eSXVII, SPXVI, Słownik staropolski, Doroszewski. Ggf. später Anfrage bei IJP PAN.
Die Wörterbuch-Aufbereitung übernimmt die Entwicklung einmalig; Nutzer laden das fertige Paket.

## 5. Verteilung

- **Hauptweg:** PyInstaller (Ordner-Variante, ohne UPX) + Inno Setup pro Benutzer (kein Admin, Eintrag in „Apps & Features“),
  automatischer Bau über GitHub Actions, Veröffentlichung über GitHub Releases.
- **Bausteine zur Laufzeit** von offiziellen Quellen mit SHA-256-Prüfung: Ollama 0.40.5 (ZIP, eigener Port,
  `OLLAMA_NO_CLOUD=1`), Tesseract 5.5.3, Pandoc 3.12.1, Typst 0.15.1, Modelle über Ollama.
- **Signatur:** Antrag bei SignPath Foundation, sobald eine erste Version veröffentlicht ist (Voraussetzung dort).
  Bis dahin: bebilderte Anleitung zur SmartScreen-Meldung. Hinweis: Jede signierte Version braucht eine Freigabe
  (ein Klick des Maintainers).
- **Microsoft Store:** optional später als Pilot (kostenlos, keine SmartScreen-Warnung, aber Prüfungsrisiko wegen Nachladens).
- **Datenschutz-Test im Bau:** Verarbeitung läuft im automatischen Test mit gesperrtem Netzwerk; jeder Verbindungsversuch
  lässt den Bau scheitern (deckt auch undokumentierte Telemetrie ab).

## 6. Vergleichstest vor der endgültigen Modellwahl

- Material: PolEval 2021 (Druck 1791–1998 mit Transkription), Wikisource-pl-Seiten mit Scan, Gloger.
- Gemessen: Lesefehler (CER) je Werkzeugkombination; Übersetzungsqualität und Strukturtreue (Tabellen, Markierungen) je Modell.
- **Einschränkung:** Dieser Entwicklungsrechner hat keine NVIDIA-Grafikkarte (Intel Iris Xe, 16 GB RAM). Kleine
  Modelle teste ich hier; für die großen Modelle liefere ich ein fertiges Testprogramm, das auf dem Gaming-PC mit
  einem Doppelklick läuft und nur Zahlen ausgibt.

## 7. Offene Risiken

- Polnisch-Qualität von GLM-OCR unbelegt → Vergleichstest; Ersatz: PaddleOCR-VL-1.5 (Apache-2.0).
- Gemma-4-Lizenz: Apache-2.0 laut mehreren Quellen; zusätzlicher Verweis auf „Gemma 4 license terms“ → vor Auslieferung Wortlaut prüfen.
- Ollama: mögliche Reste in `%USERPROFILE%\.ollama` → in Phase 2 testen und bei Deinstallation mit entfernen.
- SignPath-Annahme eines neuen Ein-Personen-Projekts ungewiss.
- Handschrift bleibt anfangs Rohfassung.
