# Quellenübersetzer

**Historische Quellen lesen und übersetzen – vollständig auf dem eigenen Rechner.**

Ein kostenloses, quelloffenes Windows-Programm für Historikerinnen und Historiker. Es liest gedruckte,
maschinenschriftliche und handschriftliche Quellen sowie Tabellen (auch aus Scans), übersetzt sie
– zunächst **Polnisch → Deutsch** – und erzeugt **DOCX, PDF und EPUB**. Unsichere Lesungen,
Bedeutungswandel und Begriffe der Zeit werden markiert und in Fußnoten erläutert.

- **Datenschutz:** Dokumente verlassen den Rechner nie. Während der Verarbeitung ist die
  Verarbeitungsumgebung technisch vom Netz abgeschottet (siehe unten). Keine Konten, keine Telemetrie.
- **Keine Kosten:** Alle Bausteine und Modelle sind frei. Es gibt keine Abonnements.
- **Einfach:** Drei Fragen beantworten, „Installieren“ klicken, danach Datei hineinziehen und „Übersetzen“.

> ⚠ Maschinelle Übersetzung – besonders bei historischen und entlegenen Quellen – ersetzt keine
> qualifizierte menschliche Übersetzung. **Handschriften** maschinell zu lesen ist nach heutigem Stand
> der Technik chronisch unzuverlässig; das Ergebnis ist immer eine Rohfassung.

## Installation

1. `Quellenuebersetzer-Setup-x.y.z.exe` herunterladen (Seite „Releases“) und starten.
   Keine Administratorrechte nötig. Falls Windows „Der Computer wurde durch Windows geschützt“ meldet:
   „Weitere Informationen“ → „Trotzdem ausführen“.
2. Im Programm Quellenart, Sprache und Zeitraum ankreuzen.
3. Der Installationsplan zeigt, was für diesen Rechner passt (Ampel, „Optimal: Ja/Nein“).
   Ein Klick auf „Installieren“ lädt alles Nötige (je nach Grafikkarte 5–25 GB).

Empfohlen: NVIDIA-Grafikkarte mit 24 GB Grafikspeicher (bestmögliche Stufe). Ab 8 GB läuft das
Programm mit kleineren Modellen; ohne geeignete Grafikkarte nur im langsamen Notbetrieb.

## Funktionsweise

| Schritt | Werkzeuge |
|---|---|
| Einlesen | PDF (Textebene oder Scan), DOCX, Bilder, Text |
| Lesen (Druck) | Bildaufbereitung → Tesseract mit Wort-Sicherheit + GLM-OCR als Zweitlesung → Abgleich; strittige Stellen entscheidet Gemma 4 anhand des Bildausschnitts – im Zweifel wird markiert, nicht ersetzt |
| Lesen (Fraktur) | Tesseract `frak2021` + Zweitlesung, Abweichungen werden immer markiert |
| Tabellen | Gitterlinien → Zellraster (auch verbundene Zellen) → zellweises Lesen, Summenprüfung |
| Handschrift | Zeilenzerlegung → zeilenweises Lesen durch Gemma 4 mit Seitenkontext + Zweitlesung + Token-Wahrscheinlichkeiten |
| Übersetzung | Gemma 4 mit Zeitraum-Angabe, Glossar und historischen Wörterbüchern (Wiktionary, Gloger); jede Antwort wird auf Vollständigkeit und Struktur geprüft |
| Ausgabe | Pandoc + Typst: DOCX, PDF, EPUB mit farbigen Markierungen, Fußnoten und Verzeichnis |

Markierungen: **A** Lesung unsicher (orange) · **B1** Bedeutungswandel (blau) · **B2** Begriff der Zeit (grün).

### Seitengetreue Ausgabe (Standard)

- **Seitenaufbau-Erkennung** (PP-DocLayoutV3, Apache-2.0, lokal über ONNX Runtime): Absätze, Spalten, Titel,
  Tabellen, Abbildungen, Bildunterschriften, Randnotizen, Fußnoten, Kopf-/Fußzeilen, Seitenzahlen samt
  Lesereihenfolge (zusätzlich XY-Cut). Text außerhalb erkannter Bereiche fängt ein Tesseract-Sicherheitsnetz auf.
- **Faksimile:** Originalseite als Hintergrund, die Schrift wird retuschiert, die Übersetzung steht an derselben
  Stelle. **Neusatz:** gleiche Anordnung auf weißer Seite. Beides als **PDF** (Typst) und **Word** (positionierte
  Rahmen, schwebende Tabellen). Längerer deutscher Text wird durch behutsame Schriftverkleinerung eingepasst.
- Sätze über Spalten-/Seitengrenzen werden gemeinsam übersetzt und wieder verteilt; Kolumnentitel nur einmal.
- **Word-Quellen** werden direkt in der Datei übersetzt (Formatvorlagen, Tabellen, Bilder bleiben).
- **Doppelseiten** (aufgeschlagenes Buch auf einem Scan) werden am Bundsteg geteilt, Scannerränder entfernt.
  Ein **Ordner mit Seitenbildern** gilt als ein Dokument (natürliche Sortierung: Scan2 vor Scan10).
- **Einband:** Zeigt die erste Aufnahme Rück- und Vorderdeckel nebeneinander (Querformat, kaum Text), wird sie am
  Buchrücken geteilt: Vorderdeckel an den Anfang, Rückdeckel ans Ende.
- **Vorschau:** Jede fertig übersetzte Seite erscheint sofort im Hauptfenster – blätterbar, als Übersetzung,
  Original oder nebeneinander.
- **Buchmodus:** kein Ruhezustand während der Verarbeitung; Zwischenstand wird laufend gespeichert und nach
  einer Unterbrechung automatisch fortgesetzt (Zwischenstände werden nach Abschluss gelöscht, sonst nach 30 Tagen).

### Netzabschottung

- Im Programmprozess sind während der Verarbeitung nur Verbindungen zu `127.0.0.1` möglich
  (`netguard.offline()`), jeder andere Versuch wird blockiert.
- Die Hilfsprozesse (Ollama, Tesseract, Pandoc, Typst) laufen mit einer Umgebung, in der ausgehende
  Verbindungen ins Leere laufen; Ollama zusätzlich nur auf `127.0.0.1` und mit `OLLAMA_NO_CLOUD=1`.
- Netzzugang gibt es nur bei der Installation (Download der Bausteine mit SHA-256-Prüfung) und bei der
  Update-Prüfung auf Knopfdruck. Der Rechner selbst darf während der Verarbeitung online bleiben.

## Entwicklung

```
python -m venv .venv && .venv\Scripts\pip install -e .[dev]
.venv\Scripts\python tools\testumgebung.py C:\Temp\qtest     # Tesseract, Pandoc, Typst für Tests
set QUE_TEST_ROOT=C:\Temp\qtest && .venv\Scripts\python -m pytest
.venv\Scripts\python -m quellenuebersetzer                    # Programm starten
```

Bau: `python -m PyInstaller packaging/quellenuebersetzer.spec`, danach `ISCC packaging/setup.iss`.
Der automatische Bau (`.github/workflows/bauen.yml`) erledigt beides und veröffentlicht bei einem
Versions-Tag (`v0.1.0`) die `Setup.exe`.

Neue Sprachen: Datei unter `src/quellenuebersetzer/resources/catalog/sprachen/` anlegen (Vorlage `pl.json`),
Wörterbücher mit `tools/woerterbuch_bauen.py` erzeugen.

Testmaterial ist ausschließlich synthetisch oder gemeinfrei. **Niemals echte Quellen in dieses Projekt legen.**

## Lizenz

GNU General Public License 3.0 oder später. Lizenzen der Bausteine: siehe „Über das Programm“ im Programm.
