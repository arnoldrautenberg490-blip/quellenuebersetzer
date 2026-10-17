# Lastenheft – Lokaler Quellenübersetzer (Arbeitstitel)

Stand: 2026-10-16 · Verbindliche Grundlage für alle Phasen. Änderungen nur nach Absprache.

---

## 1. Ziel

Ein eigenständiges Windows-Programm für Historiker ohne technische Vorkenntnisse, das historische
Quellen (Druck, Tabellen, Handschrift) **vollständig lokal** ausliest und übersetzt – zunächst
**Polnisch → Deutsch**, modular erweiterbar auf weitere Sprachen.

Das Programm wird frei weitergegeben, funktioniert ohne Cloud-Dienst, ohne Konto und ohne jeden
Bezug zu Claude/Anthropic. Installation und Bedienung wie bei einem Spiel: herunterladen, ausführen, fertig.

## 2. Unverhandelbare Grundregeln

1. **Datenschutz:** Verarbeitete Inhalte verlassen niemals den Rechner. Keine Online-Übersetzung,
   kein Online-Nachschlagen von Wörtern, keine Telemetrie, keine Absturzberichte nach außen.
   Netzwerkzugriff ausschließlich in Installation und manueller Update-Prüfung.
2. **Keine Kosten:** Kein Baustein darf einmalige oder laufende Kosten verursachen oder ein Konto
   erfordern (weder für Entwickler noch für Nutzer). Keine kostenpflichtigen Zertifikate.
3. **Kein Aufwand für den Auftraggeber:** Bau, Signatur und Veröffentlichung laufen automatisiert.
4. **Keine Echtdaten in der Entwicklung:** Getestet wird nur mit selbst erzeugtem Material und
   gemeinfreien Scans (z. B. Polona) mit vorhandenen Transkriptionen. Echte Quellen sieht die
   Entwicklung nie.
5. **Quelltext öffentlich** unter offener Lizenz; bevorzugt Bausteine mit offenen, weitergabefähigen Lizenzen.
6. **Kein überflüssiger Klick.**

## 3. Bedienablauf

```
1. Profil ankreuzen  →  2. Systemprüfung + Plan  →  3. Ein Klick  →  4. Pfad einfügen  →  5. Ergebnis
   Quellenart            Ampel: optimal/                „Installieren“    Datei oder Ordner    PDF/EPUB/DOCX
   Sprache               eingeschränkt/ungeeignet                         (auch Drag & Drop)   „Ordner öffnen“
   Zeitraum              Download-Größe, Dauer
```

- **Profil:** Quellenart (sauberer Druck · alter Druck/Fraktur · Schreibmaschine · Handschrift · Tabellen),
  Sprache, Zeitraum. Mehrfachauswahl möglich, später erweiterbar – dann nur fehlende Bausteine nachladen.
- **Ampel:** 🟢 optimal · 🟡 eingeschränkt (kleinere Variante, Hinweis auf Qualität) · 🔴 ungeeignet (mit Begründung).
- **Stapelverarbeitung:** Ein Ordnerpfad verarbeitet alle enthaltenen Dateien.
- **Zielformate** per Häkchen, Auswahl wird gemerkt.
- **Kontrollansicht** (Bildausschnitt neben Lesung, unsichere Stellen hervorgehoben): optional,
  bei Handschrift standardmäßig an.

## 4. Systemprüfung

Betriebssystem/Version, Grafikkarte und Grafikspeicher, Treiberversion, Arbeitsspeicher, freier
Speicherplatz (vor dem Download), Pfadprobleme (Sonderzeichen, OneDrive, Pfadlänge), vorhandene
Installationen (z. B. Ollama). Ergebnis bestimmt die Hardwarestufe und die Modellauswahl.

## 5. Lese-Pipeline (Quelle → Markdown)

1. **Bildaufbereitung:** Begradigung, Kontrast, Entrauschen.
2. **Layoutanalyse:** Fließtext, Tabelle, Randnotiz, Kopfzeile, Abbildung.
3. **Lesen nach Quellenart (Hybrid):**
   - *Sauberer Druck:* Tesseract mit Wort-Konfidenz; nur unsichere Stellen per Bildausschnitt
     an Vision-LLM zur Korrektur.
   - *Alter Druck/Fraktur:* Tesseract (Spezialmodell) und Vision-LLM unabhängig, wortweiser Abgleich,
     Schiedsentscheidung oder Markierung.
   - *Tabellen:* Strukturerkennung (Raster, verbundene Zellen) + zellweises Lesen + Gegenprobe
     als Ganzes + Plausibilitätsprüfung (Zellenzahl, Summen, Zahlenformate).
   - *Handschrift:* Zeilensegmentierung (z. B. Kraken) + zeilenweises Lesen durch Vision-LLM mit
     Seitenkontext + Doppellesung; später optional Training auf bestimmte Hände.
4. **Abgleich und Markierung** → Markdown (Original).

Born-digital-Dokumente (PDF mit Textebene, DOCX) werden direkt mit Struktur übernommen.

**Grundsatz:** Diplomatische Umschrift – Schreibweise, Abkürzungen, Fehler unverändert. Nie
modernisieren, nie erfinden; im Zweifel markieren.

## 6. Unsicherheiten und Kommentar

| Kategorie | Bedeutung | Behandlung |
|---|---|---|
| **A – Lesung** | Was steht da? (Scan mehrdeutig) | Alle Lesarten mit Wahrscheinlichkeit; abweichende Lesarten werden mitübersetzt |
| **B1 – Bedeutungswandel** | Wort hatte damals andere Bedeutung | Übersetzung mit historischer Bedeutung, Fußnote nennt historische und heutige Bedeutung – *prüfbedürftig* |
| **B2 – Zeitbegriff** | Amt, Stand, Maß, Münze, Rechtsbegriff ohne Entsprechung | Originalbegriff bleibt, Fußnote erklärt – *erklärend* |

- Darstellung im Markdown als Pandoc-Spans mit Attributen, z. B.
  `[Starost]{.b2 erkl="…"}`, `[Mühle]{.a lesarten="Mühle|Mauer" sicher="0.6"}`.
- In PDF/DOCX: Fußnoten (Standard), einheitliche Farben und Symbole je Kategorie; Randbemerkungen als spätere Option.
  In EPUB: antippbare Anmerkungen.
- Am Dokumentende: **Verzeichnis aller markierten Stellen**, getrennt nach A, B1, B2.

## 7. Übersetzung (Markdown Original → Markdown Deutsch)

- Lokales LLM (über Ollama, eigener Port, nur localhost), Modell je Hardwarestufe.
- Abschnittsweise mit Kontext, Struktur (Tabellen, Überschriften, Fußnoten) bleibt erhalten.
- Zeitraumbezogene Anweisungen; Namen, Orte, Daten unverändert.
- **Historische Wörterbücher offline** als Grundlage für B1/B2 (Polnisch: frei verfügbare, z. B. Linde,
  Słownik warszawski – Lizenzen in Phase 0 prüfen).
- **Glossar:** lokal, wächst durch Bestätigungen/Korrekturen des Nutzers, exportier- und teilbar.

## 8. Ausgabe

- Beide Markdown-Fassungen (Original, Deutsch) bleiben erhalten.
- Umwandlung mit Pandoc (+ Typst für PDF) in **PDF, EPUB, DOCX**; optional zweispaltig Original/Übersetzung.
- Tabellen müssen in allen Formaten sauber übertragen werden.

## 9. Modularität

Sprachen, Lesemodelle, Übersetzungsmodelle und Wörterbücher sind Bausteine mit Manifest
(Sprache, Zeitraum, Größe, Lizenz, Quelle, Prüfsumme, Hardwarebedarf). Neue Bausteine ohne Codeänderung ergänzbar.
Auswahl von Sprache und Zeitraum lädt passende Wörterbücher automatisch mit.

## 10. Installation, Verteilung, Deinstallation

- **Verteilung:** Microsoft Store (MSIX, kostenlos von Microsoft signiert – Machbarkeit in Phase 0 prüfen)
  und signierte `Setup.exe` (Inno Setup, Signatur über SignPath Foundation für Open Source),
  bereitgestellt über GitHub Releases. Zusätzlich **Offline-Paket** (USB/Netzlaufwerk).
- **Automatisierung:** Bau, Tests, Signatur und Release über GitHub Actions – kein manueller Aufwand pro Version.
- **Portabel:** Alle Bausteine und Modelle in einem Programmordner (ASCII-Pfad), `OLLAMA_MODELS` dorthin.
- **Installations-Manifest:** Nur selbst Installiertes wird entfernt; Vorhandenes bleibt unangetastet.
- **Deinstallation mit einem Klick** (im Programm und unter „Apps & Features“), Anzeige des freiwerdenden Speichers.
- Möglichst **ohne Admin-Rechte**; keine Skripte (PowerShell/Batch) während der Installation.
- Downloads nur von offiziellen Quellen, bevorzugt herstellersignierte Binärdateien, Prüfsummenkontrolle,
  Fortsetzen nach Abbruch.
- **Robustheit gegen Fehlalarme:** kein Onefile-Build, kein UPX, vollständige Versionsinfos,
  Meldung an das Defender-Fehlalarmportal vor Releases.
- **Rückfallebene ohne Signatur:** bebilderte Anleitung zur SmartScreen-Meldung.
- **Updates:** nur auf Knopfdruck, nie automatisch.
- Lizenzhinweise aller Bausteine unter „Über das Programm“.

## 11. Gestaltung

- Seriös, ruhig, an Archiv/Bibliothek angelehnt: warme Papiertöne, Tintenblau als Akzent.
- Serifenschrift für Überschriften, gut lesbare serifenlose Schrift für die Bedienung, große Schriftgrößen und Klickflächen.
- Heller und dunkler Modus, guter Kontrast. Einheitliche Farben/Symbole für A, B1, B2 in Programm und Dokumenten.
- Alle Texte auf Deutsch, ohne Fachjargon.
- **Entwürfe der Hauptbildschirme** (Profil, Installationsplan, Hauptfenster, Kontrollansicht) vor der Umsetzung zur Abstimmung.
- Eigener Programmname und Logo (Vorschläge mit den Entwürfen).

## 12. Technische Grundlage (vorläufig)

Python, PySide6 (Qt), Ollama, Tesseract, Layout-/Tabellenmodell (Docling/PaddleOCR/Surya – Phase 0),
Kraken, Pandoc, Typst. Endgültige Auswahl nach Phase 0.

## 12a. Warnhinweise (ergänzt 2026-10-16)

- **Handschrift:** deutlicher, nicht übersehbarer Warnhinweis – bei der Profilauswahl, im Installationsplan, vor
  jeder Verarbeitung und im Kopf jedes erzeugten Dokuments: Maschinelles Lesen historischer Handschrift ist nach
  aktuellem Stand der Technik chronisch unzuverlässig; das Ergebnis ist eine Rohfassung und ersetzt keine
  qualifizierte menschliche Transkription und Übersetzung.
- **Alle Dokumente:** Hinweis im Dokumentkopf, dass maschinelle Übersetzung – besonders bei historischen und
  entlegenen Quellen – keine qualifizierte menschliche Übersetzung ersetzt.

## 12b. Weitere Festlegungen (2026-10-16)

- Zielformate: **Mehrfachauswahl** (PDF, EPUB, DOCX in beliebiger Kombination); Markdown wird immer mitgespeichert.
- Lizenz des Programms: **GPL-3.0-or-later**.
- Entwicklung auf dem Entwicklungsrechner (ohne NVIDIA-GPU); Erprobung der großen Modelle auf dem Gaming-PC.
- Phase-0-Ergebnisse: `recherche/00_EMPFEHLUNG.md` (freigegeben).
- **Netzwerk (Klarstellung):** Der Rechner darf während der Verarbeitung online sein. Die
  *Verarbeitungsumgebung* hat keinen Netzzugang: Im Programmprozess sind nur Verbindungen zu
  127.0.0.1 erlaubt (Netzwerksperre); Ollama, Tesseract, Pandoc und Typst laufen mit einer Umgebung,
  in der ausgehende Verbindungen ins Leere laufen (Proxy auf eine tote lokale Adresse), Ollama
  zusätzlich mit `OLLAMA_NO_CLOUD=1` und nur auf 127.0.0.1. Netzzugang hat die Laufzeit nur beim
  Herunterladen der Modelle während der Installation.

## 12c. Layoutkopie (ergänzt 2026-10-16, Vorrang vor der Mac-Fassung)

- Ziel: Seite für Seite eine Übersetzung mit dem Aufbau des Originals – mindestens als **PDF und Word**.
  Gleiche Seitengröße; Überschriften, Spalten, Absätze, Tabellen, Abbildungen, Bildunterschriften,
  Randnotizen, Fußnoten, Kopf-/Fußzeilen an derselben Stelle; nur der Text übersetzt.
- Seitenaufbau-Erkennung (Bereiche mit Art, Position, Lesereihenfolge, Schriftmerkmalen) als eigener lokaler Baustein.
- Übersetzung im Zusammenhang über Spalten- und Seitengrenzen; Rückverteilung auf die Bereiche über Bereichsmarken.
- Darstellungen: **Faksimile** (Originalscan als Hintergrund, Textflächen retuschiert; Standard) und **Neusatz**
  (weiße Seite, gleiche Anordnung, Abbildungen ausgeschnitten).
- Längerer deutscher Text: Schrift im Bereich behutsam verkleinern (mit Mindestgröße).
- Word: positionierte Textrahmen auf festen Seiten (eingeschränkte Bearbeitbarkeit vom Auftraggeber akzeptiert).
- Word-Quellen: Übersetzung direkt in der Datei (Formatierung bleibt erhalten).

- Seitenaufbau-Erkennung läuft bei jedem Scan zuerst (auch für Fließtext); Texterkennung danach je Bereich.
- Einband: erste Aufnahme mit Vorder- und Rückdeckel wird am Buchrücken geteilt (Vorderdeckel an den Anfang,
  Rückdeckel ans Ende); Doppelseiten werden am Bundsteg geteilt.
- Fortschritt als blätterbare Vorschau fertig übersetzter Seiten (Übersetzung / Original / nebeneinander).

## 12d. Zielhardware des Auftraggebers (2026-10-16)

- Gaming-PC mit **6 GB Grafikspeicher** → eigene Stufe mit Modus „Schnell“ (Gemma 4 E4B) und „Gründlich“
  (Gemma 4 12B, aufgeteilt auf Grafikkarte und Arbeitsspeicher, ab 16 GB RAM).
- Buchmodus: Verarbeitung über Nacht, kein Ruhezustand, Fortsetzen nach Unterbrechung.
- Beschleunigung je Stufe automatisch (parallele Anfragen, Überlappung CPU/GPU, Bündeln kurzer Abschnitte).

## 13. Phasen

| Phase | Inhalt |
|---|---|
| 0 | Recherche: Übersetzungs- und Vision-Modelle, Tabellen, Handschrift, polnische Wörterbücher, portable Bausteine, Store/MSIX, SignPath, Build-Werkzeuge → Empfehlung zur Freigabe |
| 1 | Grundgerüst, Profile, Systemprüfung, Ampel; Gestaltungsentwürfe |
| 2 | Installation, Manifest, Selbsttest, Deinstallation |
| 3 | Lese-Pipeline → Markdown |
| 4 | Übersetzung, Wörterbücher, Glossar, Kategorien A/B1/B2 |
| 5 | Ausgabe PDF/EPUB/DOCX mit Fußnoten und Verzeichnis |
| 6 | Oberfläche, Paketierung, CI/CD, Signatur, Veröffentlichung |
