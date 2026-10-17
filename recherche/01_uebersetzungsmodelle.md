# Phase 0 – Übersetzungsmodelle PL→DE (Stand 2026-10-16)

## Empfehlung je Hardwarestufe (Ollama-Tags)

| VRAM | Primär | Größe | Alternative |
|---|---|---|---|
| ≥24 GB | `gemma4:31b-it-qat` | 19 GB | `translategemma:27b` (17 GB); EuroLLM-22B-Instruct-2512 (GGUF, HF) |
| 16 GB | `gemma4:12b-it-q8_0` | 13 GB | `gemma4:26b-a4b-it-qat` (MoE, CPU-Offload); `translategemma:12b` |
| 12 GB | `gemma4:12b-it-qat` | 7,2 GB | `translategemma:12b` (8,1 GB); `qwen3.5:9b-q4_K_M` |
| 8 GB | `gemma4:e4b-it-qat` | 6,1 GB | `translategemma:4b` (3,3 GB) |
| CPU/≤6 GB | `translategemma:4b` | 3,3 GB | `gemma4:e2b-it-qat` (4,3 GB) |

Tatsächlicher VRAM-Bedarf ca. 1–3 GB über Dateigröße (KV-Cache); `num_ctx` 8–16K.

## Kernaussagen
- **Gemma 4** (Apache 2.0, 02.04.2026): beste Allround-Wahl, 256K Kontext, voraussichtlich beste Strukturtreue (Tabellen/Spans/JSON – ungetestet). Lizenz: HF verlinkt zusätzlich „Gemma 4 license terms“ → Wortlaut vor Auslieferung prüfen.
- **TranslateGemma** (Gemma ToU, auf Gemma 3): deutlich besser als Gemma 3 bei EN→PL (MetricX WMT24++: 27B 4,14 vs. 5,17). Aber: nur 2K Eingabekontext, starres Prompt-Format, kein Struktur-/JSON-Erhalt. Weitergabe erlaubt mit Prohibited-Use-Policy-Hinweis.
- **EuroLLM-22B-2512** (Apache 2.0): laut Hersteller auf Gemma-3-27B-Niveau; kein verifiziertes Ollama-Tag.
- **Qwen3.5** (Apache 2.0): Alternative, Thinking abschalten.
- **Bielik v3 11B** (Apache 2.0): stark im Polnischen – ggf. Zweitmodell zur Normalisierung alter Texte.

## Ausgeschlossen
- Hunyuan-MT / HY-MT1.5: Lizenz gilt nicht in EU/UK/KR.
- Tower+: CC BY-NC-SA.
- NLLB: nicht-kommerziell; NLLB/MADLAD satzweise ohne Formaterhalt.
- Llama, Mistral, Seed-X, PLLuM: Lizenzen nicht geprüft.

## Offene Punkte
- Kein PL→DE-Benchmark, kein Benchmark für historisches Polnisch → eigenes Testset (gemeinfreie Quellen) mit Gemma 4 31B/12B, TranslateGemma, EuroLLM vergleichen.
- Geschwindigkeiten unbelegt.

## Quellen
ollama.com/library/translategemma · ollama.com/library/gemma4/tags · ollama.com/library/qwen3.5/tags ·
huggingface.co/google/translategemma-12b-it · huggingface.co/google/gemma-4-31B-it · arxiv.org/pdf/2601.09012 ·
huggingface.co/utter-project/EuroLLM-22B-Instruct-2512 · arxiv.org/pdf/2602.05879 · arxiv.org/pdf/2508.14909 ·
huggingface.co/speakleash/bielik-11b-v3.0-instruct · arxiv.org/pdf/2608.12343
