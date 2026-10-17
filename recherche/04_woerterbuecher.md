# Phase 0 – Historische polnische Wörterbücher und Testmaterial (Stand 2026-10-16)

[B] belegt · [U] unsicher

## Ressourcen
| Ressource | Zeitraum | Format | Lizenz | Download | Eignung |
|---|---|---|---|---|---|
| Wikisłownik (kaikki/wiktextract) | modern, Marker „daw.“/„przest.“ | JSONL (2026-09-01) [B] | CC BY-SA + GFDL | kaikki.org/plwiktionary | hoch |
| Słowosieć/plWordNet 4.2 | modern | XML/ZIP 407 MB [B] | Princeton-artig, frei weitergebbar inkl. kommerziell, Hinweis Pflicht [B] | clarin-pl.eu/dspace/handle/11321/891 | mittel (Vergleichsbasis) |
| Linde 1807–14 / 1854–61 | ~1500–1800 | Scans BSB/IA; OCR (UW, Bień) DjVu/PDF-A [B] | gemeinfrei | archive.org/details/10810665bsb | mittel–hoch (Aufbereitung) |
| Słownik wileński 1861 | 19. Jh. | nur Scans | gemeinfrei | Polona/IA | gering–mittel |
| Słownik warszawski 1900–27 | ~1500–1900 | DjVu mit OCR [B] | gemeinfrei [U] | szukajwslownikach.uw.edu.pl/slownik-warszawski | hoch nach Aufbereitung |
| SPXVI (16. Jh.) | 16. Jh. | Online/PDF | teils CC BY 4.0 auf RCIN [B], Website unklar | spxvi.edu.pl | mittel (Lizenz anfragen) |
| eSXVII (1601–1772) | 17./18. Jh. | nur Online-Abfrage | unklar → geschützt | sxvii.pl | gering |
| Słownik staropolski, Doroszewski, Urzędnicy | – | – | geschützt | – | nicht mitliefern |
| **Gloger, Encyklopedja staropolska** (1900–03) | Altpolen | Wikisource, korrekturgelesen [B] | gemeinfrei; Transkription CC BY-SA | pl.wikisource.org/wiki/Encyklopedia_staropolska | **hoch** (B2-Glossar) |
| Wikidata (Einheiten, Ämter) | – | SPARQL/JSON | CC0 [U] | query.wikidata.org | mittel |
| Bandtkie 1806 (pl–de), Mrongovius 1823/1854 (de–pl) | 18./19. Jh. | Scans + Google-OCR [B] | gemeinfrei | archive.org: bub_gb_woYCAAAAQAAJ, bub_gb_GRkOAAAAIAAJ, dokadnyniemiecko00mron | mittel–hoch (Fraktur) |

## Mitinstallieren (Reihenfolge)
1. Wikisłownik-JSONL (B1-Hinweise über „daw.“/„przest.“)
2. Gloger → Hauptglossar B2
3. Słowosieć 4.2 (moderne Vergleichsbedeutungen)
4. Słownik warszawski + Linde (selbst aufbereitet, größter historischer Nutzen)
5. Bandtkie/Mrongovius (zeitgenössische deutsche Entsprechungen)
6. optional Wikidata-Auszug

Nur als Online-Verweis/Anfrage: eSXVII, SPXVI, Słownik staropolski, Doroszewski.

## Testmaterial mit Ground Truth
- **PolEval 2021 OCR-Korrektur:** 979 Bücher (1791–1998), ~69.000 Seiten, OCR + Wikisource-Transkription [B]; Lizenz „frei“, genau prüfen [U]. github.com/poleval/2021-ocr-correction
- **Wikisource pl** (Namensraum „Strona:“ mit Scan + Transkription) [B]
- IMPACT GT Polnisch (1570–1756): überwiegend CC BY-NC-SA → nur intern testen
- KorBa (17./18. Jh.): Lizenz unklar
- Polona: Gemeinfreies frei zugänglich, Download z. B. via pypolona; Nutzungsbedingungen prüfen
