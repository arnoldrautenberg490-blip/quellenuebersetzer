# Phase 0 – OCR, Layout, Tabellen (Stand 2026-10-16)

[B] = Primärquelle geprüft · [S] = sekundär/abgeleitet

## OCR-VLMs
| Modell | Benchmark | Lizenz | Lokal | Bewertung |
|---|---|---|---|---|
| **GLM-OCR** 0.9B | OmniDocBench v1.5 94,62; olmOCR-Bench 75,2 [B] | MIT (+PP-DocLayoutV3 Apache) [B] | `glm-ocr` (1,8–2,7 GB), Prompts „Text Recognition:“/„Table Recognition:“ [B] | Erste Wahl für Ollama; Polnisch undokumentiert |
| **PaddleOCR-VL-1.5** 0.9B | OmniDocBench 94,5; starke Tabellen [B] | Apache-2.0 [B] | GGUF/llama.cpp [B], Windows unklar | stark bei Tabellen |
| **Qwen3.5** (Vision integriert) | – | Apache-2.0 [S] | `qwen3.5:9b` / `:27b` [B] | Generalist für Abgleich/Korrektur |
| **Gemma 4** | anekdotisch etwas schwächer bei OCR | Apache-2.0 [S] | `gemma4:12b` / `:26b` [B] | Alternative |
| Chandra OCR 2 | Polnisch 91,5 %, Tabellen 92,1 [B] | OpenRAIL-M modifiziert [B] | kein Ollama | Lizenz → nicht mitliefern |
| olmOCR 2, dots.mocr, LightOnOCR-2, DeepSeek-OCR | 82–84 olmOCR-Bench [S] | div. | meist vLLM | nachrangig |

## Layout/Tabellen
- PP-StructureV3 (Apache-2.0): 23 Layoutklassen, SLANeXt, HTML mit rowspan/colspan; Windows-GPU ungetestet.
- **Docling** (MIT, v2.140.0): TableFormer, Tesseract-Anbindung, VLM-Pipelines; gut per pip unter Windows [S].
- Surya/Marker: Gewichtslizenz OpenRAIL-M (5-Mio-$-Grenze), Marker GPL → nicht mitliefern.

## Tesseract
- 5.5.3 (24.07.2026), UB-Mannheim-Installer; portabel per Entpacken + `TESSDATA_PREFIX` (testen). Apache-2.0.
- Modelle: `pol` (tessdata_best), `deu_latf`, `script/Fraktur`, UB Mannheim `frak2021`, `Fraktur_5000000`, `german_print`. Kein polnisches Fraktur-Modell → `frak2021+pol` testen.
- Kraken/Calamari/OCR-D: Linux-zentriert.

## OCR+LLM-Fusion – Belege
- ICDAR 2026 HIPE-OCRepair (arXiv 2607.08143): LLMs überkorrigieren sauberen Text; bewährt: Judge-and-Retry (42 %→6 % verdächtige Korrekturen), Routing nach Fehlerrate, Längenprüfung 0,35–2,8×, Rückfall auf OCR.
- MDPI Information 17/8 (2025): direkte multimodale Transkription > OCR + LLM-Nachkorrektur.
- Muster: zeilenweiser Levenshtein-Abgleich Tesseract↔VLM; Übereinstimmung = sicher; sonst Konfidenz (<~70) / Widerspruch → markieren; LLM darf nur ausgerichtete Tokens ersetzen (Edit-Budget, Wörterbuchcheck).

## Empfehlung je Quellenart
- **Moderner Druck/Schreibmaschine:** OpenCV → Tesseract `pol` (TSV-Konfidenz) + `glm-ocr` → Abgleich → unsichere Zeilen an `qwen3.5:9b` mit Crop. 3–8 GB VRAM.
- **Alter Druck/Fraktur:** Tesseract `frak2021+pol` + `qwen3.5`/`gemma4` als Zweitlesung; Abweichungen markieren statt ersetzen. 8–20 GB.
- **Tabellen:** Docling/PP-StructureV3 (Raster) → `glm-ocr` „Table Recognition:“ bzw. PaddleOCR-VL-1.5 → HTML-Tabelle im Markdown (verbundene Zellen); Tesseract als Zahlenkontrolle. 3–6 GB.

## Offen
Polnisch-Qualität GLM-OCR/PaddleOCR-VL testen; Lizenzen Qwen3.5/Gemma 4 auf HF bestätigen; PP-StructureV3 Windows-GPU testen.
