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
> **In der Praxis nicht bestätigt:** Mit dem aktuellen Code treten Überlappungen, erfundene bzw.
> unvollständige Tabellen und verlorene Gestaltung weiterhin auf. Die folgenden Änderungen bestanden nur
> synthetische Einzeltests; sie werden im Zuge der Layout-Überarbeitung gemessen und nachgebessert.

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

## Überarbeitung der Layouterkennung (17.10.2026)
Ursachen der Fehler im Code: Das Layoutmodell bekam nur ein Graubild (Farbe ging verloren), die Feinheiten
gingen bei der Verkleinerung auf 800 × 800 Pixel verloren, das Schwarzweißbild wurde einmal für die ganze Seite
erzeugt (helle Schrift auf dunklem Grund unlesbar), nur durchgezogene Linien wurden erkannt, die erste
Tabellenzeile galt immer als Kopf, Randtext wurde nach Lage zur „Randnotiz“, Fehler liefen still durch.

- **Zweistufige Erkennung:** Stufe A erfasst Merkmale in voller Auflösung und Farbe (Linien jeder Art –
  durchgezogen, gestrichelt, gepunktet, blass, lückenhaft –, Kästen mit Hintergrundfarbe und Rahmen,
  Spaltenlücken); das Layoutmodell bekommt das Farbbild. Stufe B entscheidet mit Regeln aus allen Signalen.
- **Kästen** sind eigene Textflüsse: nie mit Umgebungstext vermischt oder gemeinsam übersetzt; Hintergrund und
  Rahmen erscheinen im Neusatz (PDF und Word); Text bleibt beim Einpassen im Kasten.
- **Spalten** werden an echten Lücken getrennt; Linienraster werden zu Tabellen, auch wenn das Modell dort Text sieht.
- **Texterkennung je Block:** hinterlegte Flächen werden umgerechnet (auch helle Schrift auf dunklem Grund),
  Linien vor dem Lesen entfernt, zweite Bildvariante bei schlechter Sicherheit, Zeichenfolgen ohne
  Buchstaben/Ziffern verworfen.
- **Nichts erfinden:** Tabellenkopf nur bei Fettdruck, Hinterlegung oder kräftigerer Linie; Fußnote nur mit
  Verweiszeichen oder Trennlinie; Seitenzahl nur, wenn sie wie eine aussieht; Randnotiz/Kopfzeile nach Lage zum Haupttext.
- **Fehler sichtbar:** Prüfbericht mit Ampel je Seite (eigene Datei und Anhang in PDF/Word): unlesbare Bereiche
  (markiert statt übersetzt), geringe Lesesicherheit, nachträglich aufgefangener Text, Tabellenlücken, Reste der
  Ausgangssprache. Zusätzlich „Diagnose ohne Inhalt“ (nur Rahmen, Arten, Sicherheit – kein Text, kein Bild).
- **Testsammlung** (`tests/sammlung.py`, 10 Seitentypen sauber und gealtert, mit Lösungsblatt) und
  **Messwerkzeug** (`tools/layout_messen.py`). Ergebnis an diesen 20 Seiten:

  | Kennzahl | vorher | nachher |
  |---|---|---|
  | Blöcke erkannt | 89,6 % | 100 % |
  | Wörter wiedergefunden | 95,1 % | 99,9 % |
  | Artefakte („----“, „....“) | 102 | 0 |
  | Tabellenraster richtig | 16,7 % | 100 % |
  | Tabellenzellen richtig | 20,8 % | 99,7 % |
  | Gestaltung getroffen | 44,4 % | 91,7 % |
  | Erfundene Strukturen (Kopfzeilen, Randnotizen …) | 1 | 0 |
  | Vermischte Bereiche / Überlappungen | 0 / 0 | 0 / 0 |

  Einschränkung: Das sind synthetische Seiten. Echte Scans sind schwieriger; als behoben gilt etwas erst nach
  dem Praxistest (die Diagnose ohne Inhalt hilft dabei).

## Übersetzungsbeschleunigung (17.10.2026)
- **Kleine Fehler ohne Neuanfrage reparieren:** überzählige, fehlerhafte oder unerklärte Markierungen werden
  lokal entfernt, statt die ganze Antwort neu erzeugen zu lassen (früher oft zweiter Versuch und Rückfall).
- **Gleichbleibende Anweisung vorn:** alle festen Regeln (auch zu den Abschnittsmarken) stehen im unveränderlichen
  Teil, den die Modell-Laufzeit wiederverwendet; die Anfrage selbst ist kürzer.
- **„Gründlich“ arbeitet gestaffelt:** Das schnelle Modell übersetzt alles, das große überarbeitet nur schwierige
  Abschnitte (Tabellen, unsichere Lesungen, markierte Begriffe, Abschnitte mit Korrekturen) – ein einziger
  Modellwechsel. Das schnelle Modell wird dafür mitinstalliert. Fällt der zweite Durchgang aus, bleibt der Entwurf.
- Kopierte Beispiel-Erläuterungen und doppelte Erläuterungen werden verworfen (nichts Erfundenes als Beleg).
- Gemessen mit echtem Modell (Gemma 4 E2B, Entwicklungsrechner ohne Grafikkarte, 6 Sätze, alt → neu):
  245 s → 147 s (−40 %), Antwort-Token 2857 → 1571, zweite Versuche 4 → 0, Rückfälle 2 → 0.
  Kleine Stichprobe; die Zahlen vom Gaming-PC (Zeitprotokoll) stehen noch aus.
- **Verworfen nach Messung:** gebündelte Zweitlesung (auf dem Prozessor langsamer: 60 s statt 32 s) und
  Erläuterungen direkt aus dem Wörterbuch (falsche Wortbedeutungen, nicht deutsch, kein Zeitgewinn).

## Fehlerbehebung: Speicher nach dem Beenden der Modell-Laufzeit (17.10.2026)
- Beim Beenden blieben die Modellprozesse (`llama-server`) als Waisen zurück und belegten mehrere Gigabyte
  Arbeitsspeicher – nach einigen Läufen konnte der Speicher volllaufen (Verlangsamung, Abbrüche).
  Jetzt wird der ganze Prozessbaum beendet; beim Start werden Reste früherer Sitzungen beseitigt
  (nur programmeigene, am Installationspfad erkannt).

## Qualitätssicherung
- 95 automatische Tests (synthetische Testdokumente, echter Tesseract/Pandoc/Typst, nachgebildete Modell-Laufzeit),
  darunter Ende-zu-Ende-Qualitätsschranken der Layouterkennung an schwierigen Seiten der Testsammlung.
- Tests mit echten Modellen auf dem Entwicklungsrechner (ohne Grafikkarte): Gemma 4 E2B und 12B.
- Setup.exe mehrfach installiert, gestartet und rückstandslos deinstalliert.

## Offen
- Praxistest der Übersetzungsqualität und Geschwindigkeit auf dem Gaming-PC (Zeitprotokoll erbeten).
- Mac-Fassung (zurückgestellt), GitHub-Veröffentlichung und kostenlose Signatur (noch nicht begonnen).
