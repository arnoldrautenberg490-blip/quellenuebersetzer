# Änderungen – Quellenübersetzer

Stand: 17.10.2026 · Version 0.1.0 (in Entwicklung, noch nicht veröffentlicht)

## Grundlagen und Planung
- Lastenheft mit allen Vorgaben (`LASTENHEFT.md`), laufend ergänzt.
- Recherche zum Stand der Technik (`recherche/`): Übersetzungsmodelle, Texterkennung/Tabellen,
  Handschrift, polnische Wörterbücher, Verteilung/Signatur, Seitenaufbau-Erkennung.
- Lizenz GPL-3.0; nur kostenlose, frei weitergebbare Bausteine; keine Konten, keine Telemetrie.

## Einrichtung und Installation
- Profil mit drei Fragen (Quellenart, Sprache, Zeitraum), Systemprüfung, Installationsplan mit Ampel
  und „Optimal: Ja/Nein“, Installation mit einem Klick.
- Hardwarestufen 1–6; eigene Stufe für 6-GB-Grafikkarten (GTX 1660 Ti) mit Modus „Schnell“ (Gemma 4 E4B)
  und „Gründlich“ (Gemma 4 12B, Grafikkarte + Arbeitsspeicher).
- Portable Bausteine mit SHA-256-Prüfung und Fortsetzen nach Abbruch: Ollama, Tesseract (+ Schriftmodelle
  Polnisch, Fraktur, Latein, Deutsch), Pandoc, Typst, Seitenaufbau-Modell PP-DocLayoutV3, 7-Zip-Entpackhilfe.
- Automatische Laufzeit-Abstimmung je Grafikkarte (Flash Attention nur auf RTX, parallele Anfragen ab 12 GB).
- Startprüfung bei jedem Programmstart: Vorhandenes wird erkannt und übernommen (Kennmarken, Prüfsummen,
  Ollama-Verzeichnis), Fehlendes/Beschädigtes/Veraltetes automatisch und ohne Klick ergänzt.
- Deinstallation mit einem Klick (im Programm und unter „Apps & Features“), Sicherung von Glossar und
  Korrekturen in „Dokumente“; Setup.exe ohne Administratorrechte (Inno Setup).

## Datenschutz
- Netzwerksperre im Programmprozess während der Verarbeitung (nur 127.0.0.1).
- Hilfsprozesse (Ollama, Tesseract, Pandoc, Typst) laufen abgeschottet (Proxy ins Leere, OLLAMA_NO_CLOUD);
  der Rechner selbst darf online bleiben.
- Seitenbilder und Zwischenstände nur lokal, nach Abschluss gelöscht (spätestens nach 30 Tagen);
  Protokolle ohne Textinhalte und ohne Dateinamen.

## Einlesen
- PDF (Text oder Scan), Word, Bilder, Text; Ordner mit Seitenbildern = ein Dokument (natürliche Sortierung).
- Doppelseiten werden am Bundsteg geteilt, Scannerränder entfernt.
- Einband (Vorder- und Rückdeckel auf der ersten Aufnahme) wird erkannt und eingeordnet.
- Word-Quellen werden im seitengetreuen Modus direkt in der Datei übersetzt.

## Phase 1 – Seitengeometrie und Seitenaufbau (für das ganze Dokument zuerst)
- Entzerrung: Seite vom Hintergrund lösen, Perspektive, Schräglage, Wölbung der Zeilen glätten.
- Einheitliches Seitenformat für alle Seiten eines Dokuments.
- Seitenaufbau-Erkennung (Absatz, Titel, Tabelle, Abbildung, Bildunterschrift, Randnotiz, Fußnote,
  Kopf-/Fußzeile, Seitenzahl) mit Lesereihenfolge (XY-Cut); Überlappungen werden aufgelöst
  (Text fließt um Bilder, nie Text auf Text).

## Phase 2 – Texterkennung je Bereich
- Tesseract mit Wort-Sicherheit + GLM-OCR als Zweitlesung bei unsicheren Zeilen; Abgleich und Markierung
  (Kategorie A); Schiedsrichter (Gemma 4 mit Bildausschnitt) nur bei altem Druck/Fraktur.
- Tabellen mit Gitter zellweise (verbundene Zellen, Summenprüfung), ohne Gitter über GLM-OCR.
- Handschrift: Zeilenzerlegung, zeilenweises Lesen, Doppellesung, Token-Wahrscheinlichkeiten;
  deutlicher Warnhinweis an allen Stellen.
- Sicherheitsnetz: Text außerhalb erkannter Bereiche geht nicht verloren.

## Phase 3 – Übersetzung
- Gemma 4 mit Zeitraum, Glossar und historischen Wörterbüchern (Wiktionary: 11.800 historisch gekennzeichnete
  Stichwörter; Gloger, Encyklopedja staropolska: 3.006 Einträge) – beide mitgeliefert.
- Markierungen A (Lesung unsicher), B1 (Bedeutungswandel), B2 (Begriff der Zeit) mit Erläuterung und Beleg.
- Gestückelte Übersetzung: zusammenhängende Absätze gebündelt, Rückverteilung über Marken, sicherer Rückfall.
- Prüfung jeder Antwort (Vollständigkeit, Tags, Tabellenstruktur, Länge, keine Klammer-Erklärungen,
  sparsame Markierungen) mit zweitem Versuch; Endreinigung gegen Platzhalter-Reste.
- Begrenzte Antwortlänge, feste Kontextgröße je Modell (kein Neuladen).

## Ausgabe
- Seitengetreu als PDF (Typst) und Word (positionierte Rahmen): Faksimile (Original als Hintergrund,
  Schrift retuschiert) oder Neusatz; Schrift wird bei längerem deutschem Text behutsam eingepasst;
  Anmerkungen und Hinweise im Anhang.
- Fließtext als DOCX, PDF, EPUB (Pandoc) mit Fußnoten und Verzeichnis der markierten Stellen.
- Umschrift und Übersetzung jeweils getrennt; Abbildungen im Ordner „Abbildungen“.

## Oberfläche
- Ruhige Gestaltung (Papiertöne, Tintenblau), heller und dunkler Modus, eigenes Programmsymbol.
- Hauptfenster: Datei/Ordner hineinziehen oder Pfad einfügen, Formate per Mehrfachauswahl,
  Darstellung (Faksimile / Neusatz / Fließtext), Schriftart der Quelle (Tabellen werden automatisch erkannt).
- Blätterbare Vorschau: jede Seite in ihrer Stufe (Aufbau → gelesen → übersetzt), Original/Aufbau/nebeneinander.
- Fortschritt in drei Phasen mit Restzeit; Buchmodus (kein Ruhezustand, Fortsetzen nach Unterbrechung).
- Kontrollansicht der Umschrift mit lesbaren Markierungen ⟦…⟧ und Liste der Lesarten.
- Einstellungen: Profil/Modus ändern, Darstellung, Glossar (Import/Export), Leistungstest, Update-Prüfung
  auf Knopfdruck, Über das Programm (Lizenzen), „Alles entfernen“.

## Fehlerbehebungen aus dem Praxistest auf dem Gaming-PC
- Seitenaufbau-Modell wurde nach Neuinstallation nicht geladen → Startprüfung mit automatischer Ergänzung.
- Sehr langsame Verarbeitung → Schiedsrichter nur bei Fraktur, weniger Zweitlesungen, kein Neuladen der
  Modelle, Antwortlängen begrenzt, gebündelte Übersetzung, Zeitprotokoll (`logs/zeiten.log`).
- Vorschau erschien nicht → Seiten erscheinen ab Phase 1; Fehler werden gemeldet statt verschluckt.
- „Text und Tabellen“ nicht wählbar → Tabellen werden immer automatisch erkannt.
- Verzerrte Doppelscans → Entzerrung und einheitliches Format in Phase 1.
- Bilder hinter dem Text → Überlappungen im Seitenaufbau werden aufgelöst.

## Nachbesserung nach Durchsicht der Übersetzungen (17.10.2026)
- **Keine erfundenen Tabelleninhalte mehr:** Tabellen ohne Linien werden aus den Wortpositionen der
  Texterkennung aufgebaut; das Lesemodell liest nur noch einzelne unsichere Zellen gegen (kein „Ablesen“
  ganzer Tabellen mehr). Ohne erkennbare Tabellenstruktur wird der Bereich als Text gelesen.
- **Zahlenprüfung:** Zahlen, Jahreszahlen und Beträge müssen in der Übersetzung exakt erhalten bleiben –
  bei Tabellen Zelle für Zelle; sonst zweiter Versuch bzw. zellweise Übersetzung.
- **Gestaltung wird übernommen:** Schriftfarbe (z. B. rote Rubriken), Fettdruck (Strichstärke), Kursive
  (Neigung) und Sperrsatz werden am Scan gemessen und in PDF und Word wiedergegeben.
- **Keine Überschneidungen:** Text wächst zuerst in freien Raum, dann wird der Zeilenabstand verringert,
  dann die Laufweite, erst dann die Schrift (bis 60 %); notfalls Kürzung mit […] und vollständiger Text
  im Anhang. Berechnung gemeinsam für PDF und Word (gleiche Schrift Times New Roman).
- Gebündelte Übersetzung: jeder Teil muss in der Länge zu seinem Bereich passen, sonst Bereich für Bereich.
- Akzente über Großbuchstaben (Ü, Ś, Ż) werden nicht mehr abgeschnitten (PDF und Word).

## Qualitätssicherung
- 78 automatische Tests (synthetische Testdokumente, echter Tesseract/Pandoc/Typst, nachgebildete Modell-Laufzeit).
- Tests mit echten Modellen auf dem Entwicklungsrechner (ohne Grafikkarte): Gemma 4 E2B und 12B.
- Setup.exe mehrfach installiert, gestartet und rückstandslos deinstalliert.

## Offen
- Praxistest der Übersetzungsqualität und Geschwindigkeit auf dem Gaming-PC (Zeitprotokoll erbeten).
- Mac-Fassung (zurückgestellt), GitHub-Veröffentlichung und kostenlose Signatur (noch nicht begonnen).
