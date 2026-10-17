# Phase 0 – Handschrift (HTR) lokal (Stand 2026-10-16)

## Kernaussagen
- **Kraken 7.1.1 / Party: nur Linux/macOS** – unter Windows nur via WSL2 (Admin, Virtualisierung → für Zielgruppe ungeeignet als Pflichtbaustein).
- **Allgemeine VLMs zero-shot sind bei Handschrift schwach:** OmniHandwritingOCR (arXiv 2608.18586): Qwen3-VL-8B CER ≈ 35 % (mittel) / 57 % (schwer), Gemma-3-27B ≈ 56/73 %. Schätzung für poln. Handschrift 16.–19. Jh.: 10–30 % CER (unbelegt).
- **Feintuning hilft massiv:** mit ~1.000–3.000 eigenen GT-Zeilen realistisch 3–8 % CER (Transkribus-Niveau; Transkribus „Polski Wieszcz“ 7,37 %).
- CHURRO (Qwen2.5-VL-3B, sehr gut auf hist. Dokumenten) – Lizenz qwen-research → ausgeschlossen.
- Kein offenes polnisches Kraken-Modell; McCATMuS (Zenodo 13788177, 16.–21. Jh. generisch) bester Startpunkt; UB Mannheim Kurrent (Zenodo 7933463).
- Kein offener polnischer Handschrift-GT-Datensatz verifiziert. Kurrent-GT: Schweizer Bundesratsprotokolle (boris.unibe.ch/157474).

## Segmentierung nativ unter Windows
- YOLO (Ultralytics, AGPL-3.0) für Zeilen-Boxen – nativ, aber Gewichte selbst trainieren; AGPL erzwingt AGPL fürs Programm (für OSS akzeptabel).
- Loghi: nur Docker.
- Zu prüfen: Alternativen ohne WSL (ONNX-Export von Kraken-Segmentierer, Layoutmodelle aus OCR-Recherche, VLM-Grounding mit Bounding-Boxes).

## Konfidenz
- Ollama `/api/chat` unterstützt `logprobs`/`top_logprobs` (seit ~v0.12.11).
- Methoden: Wort-min-logprob, Doppellesung (zwei Modelle/Prompts) + Levenshtein-Abgleich, CTC-Konfidenz als drittes Votum, Halluzinationsfilter (Zeilenlänge vs. Breite, Wiederholungsschleifen).

## Pipeline-Vorschlag
| Baustein | Werkzeug | Lizenz | VRAM |
|---|---|---|---|
| Segmentierung | nativ (zu klären) / Kraken via WSL2 optional | – | 2–4 GB |
| VLM-Lesung | Qwen3-VL-8B; Gemma 4 26B-A4B/31B | Apache-2.0 | 8–24 GB |
| Konfidenz | Logprobs + 2–3 Lesungen | eigen | – |
| Später | LoRA-Feintuning Qwen3-VL auf eigener GT | Apache-2.0 | 12–24 GB |

## Konsequenz für das Produkt
Handschrift ist zero-shot nur mittelmäßig → ehrliche Ampel „Handschrift: Rohtranskription, Nachkorrektur nötig“; Kontrollansicht Pflicht; Ausbaustufe „eigenes Modell trainieren“ aus korrigierten Seiten (lokales Feintuning) einplanen.
