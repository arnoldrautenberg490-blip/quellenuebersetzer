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
- Ersatzadressen für Downloads (gleiche Prüfsumme Pflicht): Fraktur-Modell frak2021 kommt zuerst aus der
  Veröffentlichung „modelle“ des Projekts, dann vom Server der UB Mannheim (dieser war zeitweise nicht erreichbar).

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
- Restzeit aus dem gemessenen Tempo des laufenden Durchgangs (Wanduhr je übersetztem Abschnitt × offene
  Abschnitte des ganzen Buchs, bei „Gründlich“ inklusive Überarbeitung); vorher war sie chronisch zu niedrig
  (schneller Seitenaufbau und beim Fortsetzen erledigte Seiten verzerrten die Hochrechnung).

## Ausgabe
- Ergebnisse lassen sich auch auf ein anderes Laufwerk speichern (USB-Stick, D:) – vorher brach das Verschieben
  aus dem Arbeitsordner dort ab.
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

## Beschleunigung für ganze Bücher (17.10.2026)
- **Mehrere Prozessorkerne:** Entzerren, Seitenaufbau und Texterkennung laufen seitenweise parallel
  (etwa die Hälfte der logischen Kerne, höchstens 6).
- **Weniger Rechenaufwand beim Lesen:** kantenerhaltende Glättung statt der sehr teuren Rauschunterdrückung
  (3,4 s je Seite) und ganze Tabellen in einem Tesseract-Aufruf statt einem Aufruf je Zelle; Zellen ohne
  zugeordnetes Wort werden einzeln nachgelesen. Gleiche Lesequalität an der Testsammlung
  (Wörter 99,9 %, Tabellenzellen 99,4 %).
  Gemessen (10 Seiten, Entwicklungsrechner): Seitenaufbau + Texterkennung **94 s → 25 s**.
- **Lesen und Übersetzen überlappt:** Nach dem Seitenaufbau des ganzen Buchs liest der Prozessor Block für
  Block (20 Seiten) voraus, während die Grafikkarte den vorigen Block zweitliest und übersetzt.
  Mit eingeschalteter Prüfung der Umschrift bleibt der bisherige Ablauf (dort muss erst alles gelesen sein).
- **Zwei Übersetzungen gleichzeitig**, nur wenn auf dem jeweiligen Rechner gemessen schneller (Schwelle: höchstens
  80 % der Zeit): einmalige automatische Messung beim ersten Buch ab 20 Seiten (Ergebnis gespeichert, nach jeder
  Neueinrichtung neu) und im Leistungstest. Das Buch wird dann in zwei zusammenhängende Hälften je Block geteilt.
  Auf dem Entwicklungsrechner ohne Grafikkarte: kein Gewinn (17,8 s gegen 16,1 s) → bleibt aus.
- Zeitprotokoll nennt jetzt Kerne, Überlappung und Zahl gleichzeitiger Übersetzungen.

## Praxistest Gedenkbuch-Seiten: helle Pläne, senkrechte Titel, fremde Schriften (18.10.2026)
Befunde an zwei eingesandten Seiten und Ursachen:
- **Heller Plan als Text:** „Zeichnung oder Text“ zählte nur dunkle Linienzüge; ein blasser Plan (grauer Grund,
  weiße Straßen, See) fiel durch, Plangrund und See wurden zu „Kästen“. → Zusätzlich Farbvielfalt und Schriftdichte
  (Pläne: Dichte ≤ 0,03, Text/Tabellen ≥ 0,15); Farbflächen in einer Abbildung bleiben Teil des Bildes.
- **Senkrechte Titel:** nicht erkannt oder waagrecht zu Zeichenmüll gelesen. → Hohe, schmale Bereiche werden in
  beide Richtungen gedreht gelesen; es gilt die Lesung mit echten Wörtern. Kurze gedrehte Titel sind Ortsnamen:
  das Original bleibt stehen, darunter (in der Schreibrichtung) klein „(deutsche Namensform)“, falls es eine gibt –
  im Prüfbericht als Einschätzung des Sprachmodells gekennzeichnet. Längere gedrehte Texte werden gedreht gesetzt.
- **Fette große Schrift wurde beschädigt:** Die Hintergrund-Ebnung hielt dicke Titelstriche für Hintergrund
  (Fenster 21 px). → Fenster 61 px – auch fette Titel bleiben vollständig (Lesesicherheit „Kraków“ 55 % → 96 %).
- **Übersehene Stellen:** Was das Layoutmodell gar nicht meldet, wird eingesammelt – als Text, gedrehter Titel
  oder Bild; im Neusatz geht nichts verloren.
- **Unlesbares** wird im Faksimile nicht mehr übermalt (Original bleibt sichtbar), im Neusatz als Ausschnitt gezeigt.
- **Eingebettete Zwischenüberschriften** („HISTORIA … • Text …“) werden nicht mehr mitten im Wort abgeschnitten.
- **Seitenleisten:** Teile mit gleichem linkem Rand werden zusammengeführt; „Fußnoten“ weit oben auf der Seite
  sind Randnotizen; Farbflächen ohne Schrift (Daumenregister) erzeugen keinen Textblock.
- **Hebräisch, Jiddisch, Russisch:** zusätzliche Schriftmodelle (zusammen 22 MB). Unsichere oder verdächtige
  Wörter werden Wort für Wort in der Schrift übernommen, in der sie am sichersten gelesen werden
  („KpakoB“ → „Краков“, „rp“ → „קודן“); eine fremde Schrift gewinnt nur, wenn das Wort überwiegend aus ihren
  Buchstaben besteht. Wörter in diesen Schriften bleiben in der Übersetzung unverändert.
- Testsammlung um „heller Plan“ und „Seitenleiste“ (senkrechter Titel, Namensformen in drei Schriften,
  eingebettete Überschrift, Randmarke) erweitert: 36 Seiten, alle Kennzahlen unverändert gut.
  An den eingesandten Seiten (aus der Aufbau-Ansicht zurückgerechnet, mit Resten der Einzeichnungen):
  Pläne als Bild, beide senkrechten Titel als Ortsnamen erkannt, Tabelle und Koordinaten richtig gelesen.

## Praxistest: Stadtpläne als Bild statt als Text (17.10.2026)
- Ursache: Die Regel „einfarbige Fläche mit Textzeilen ist kein Bild“ griff schon, wenn eine kleine Farbfläche
  (z. B. ein Park) *in* einer Abbildung lag – der ganze Plan wurde dann als Text gelesen.
- Diese Umwandlung gilt nur noch, wenn die Farbfläche die ganze Abbildung ausmacht und keine Zeichnung enthält.
- Neues Merkmal „Zeichnung oder Text“: Anteil der Schwärzung in großen zusammenhängenden Linienzügen
  (Straßen, Flüsse, Umrisse). Text liegt an allen Testseiten bei 0, Pläne und Bilder bei 0,8–1,0; ab 0,35
  bleibt ein Bereich Bild – auch wenn das Layoutmodell ihn für Text hält.
- Neue Testseite „Stadtplan“ (Straßen, Park, Fluss, gedrehte Straßennamen, Bildunterschrift): vorher auf der
  gealterten Fassung als Zeichenmüll gelesen, jetzt Abbildung; übrige Sammlung unverändert.

## Praxistest mit Testbild: Kasten mit weißer Schrift (17.10.2026)
- Am eingesandten Bild (Fließtext, darunter türkisgrauer Kasten mit weißer Schrift und runden Ecken) trennt der
  aktuelle Stand den Kasten richtig ab und liest die weiße Schrift. Der Praxislauf zeigte ihn noch verschmolzen.
- **Wahrscheinliche Ursache:** Der Buchmodus setzte einen Zwischenstand fort, dessen Seitenaufbau mit einer älteren
  Fassung erkannt worden war. Zwischenstände gelten jetzt nur noch für die Fassung, die sie erzeugt hat; nach einem
  Update wird der Seitenaufbau neu erkannt (mit Hinweis).
- **Baustempel:** Version und Bauzeitpunkt stehen in „Über das Programm“, im Zeitprotokoll und in der Diagnose –
  so ist eindeutig, welche Fassung lief.
- Die Farbflächen-Erkennung arbeitet unabhängig von der Bildauflösung (geprüft ab 500 Pixel Seitenbreite).

## Praxistest: farbige Blöcke mit weißer Schrift (17.10.2026)
Ursachen: Kästen wurden nur über vier gerade Kanten gefunden – Blöcke bis zum Seitenrand, mit abgerundeten
Ecken oder direkt an einem andersfarbigen Block fielen durch. „Helle Schrift“ wurde nur bei sehr dunklem Grund
angenommen, weiße Schrift auf Rot, Grün oder Grau wurde nicht gelesen (an der neuen Testseite fehlten 18 % der
Wörter). Die Schriftfarbe wurde mit den Randpixeln der Buchstaben gemittelt (Weiß auf Rot wurde Rosa).

- **Farbflächen werden über die Farbe erkannt, nicht über Kanten:** Schrift herausfiltern, Bild in einheitliche
  Flächen zerlegen, jede vom Papier abweichende Fläche ist ein Block – jede Form und Lage.
- **Helle oder dunkle Schrift wird je Fläche gemessen.** Einfarbige Flächen mit Textzeilen, die das Modell für
  Abbildungen hält, werden gelesen. Der Randstreifen umgerechneter Flächen erzeugt keine Zeichen mehr.
- **Schriftfarbe aus den Kernen der Buchstaben;** deutlich größere Schrift in kurzen Bereichen gilt als Überschrift;
  allein stehende Zeichen ohne Buchstaben nur mit Beleg.
- Neue Testseite „Farbflächen“: Blöcke 50 % → 100 %, Wörter 82 % → 100 %, Gestaltung 18 % → 100 %.
  Gesamte Sammlung (30 Seiten): Gestaltung 93 % → 98,8 %, 0 Artefakte, keine Verschlechterung an anderer Stelle.

## Tabellen: Hinterlegungen, mehrzeilige Zellen, Tabellen in Kästen (17.10.2026)
Ist-Stand an vier neuen Testseiten (je sauber und gealtert): Mehrzeilige Zellen wurden zu mehreren
Tabellenzeilen (0 % richtig), Zebrastreifen und hinterlegte Spalten galten als „Kästen“, eine Tabelle in
einem Kasten wurde auf der gealterten Seite zu Fließtext.

- **Zeilen aus Farbbändern oder waagrechten Linien:** Bei Tabellen ohne senkrechte Linien bestimmen
  Zebrazeilen oder Zeilenlinien die Tabellenzeilen – eine umbrochene Zelle bleibt eine Zelle. Ein Band wird
  nur geteilt, wenn alle Spalten gleich viele Textzeilen auf gleicher Höhe haben.
- **Spalten aus hinterlegten Spalten oder Wortlücken;** eine Grenze gilt nur, wenn kein Wort sie überquert.
- **Hinterlegungen in einer Tabelle sind keine Kästen;** eine vom Modell abgeschnittene hinterlegte Spalte wird
  der Tabelle zugeschlagen; meldet das Modell einen ganzen Kasten als Tabelle, gilt die kleinere Tabelle darin.
- **Hintergrund-Ebnung vor der Texterkennung:** Papier, Tönungen und Schatten werden herausgerechnet (11 ms je
  Seite); an Kanten hinterlegter Zeilen entsteht kein „Schmutz“ mehr, der Kopfzeilen verschluckte.
- Ergebnis an allen 28 Testseiten: Tabellenraster 16/16 richtig (vorher 13/16), Tabellenzellen 99,7 %,
  keine Verschlechterung an anderer Stelle.

## Praxistest: überlappende und verschmolzene Blöcke (17.10.2026)
Ursachen: Beim Zusammenlegen genügte ein gleicher *linker* Rand – ein spaltenübergreifender Block wurde mit
Spalte 1 vereinigt, das breite Rechteck dann mit allem darunter (Kettenreaktion bis zur ganzen Seite).
Geteilt wurde nur an durchgehenden senkrechten Lücken; Wechsel von Breite oder Farbe innerhalb eines
Modellbereichs blieben unbemerkt. Teilweise überlappende Bilder/Tabellen und das Sicherheitsnetz konnten
Überlappungen hinterlassen. Blass getönte Flächen ohne Rahmen wurden nicht als Kasten erkannt.

- **Jedes Textelement gehört zu genau einem Block:** feste Prüfung am Ende von Phase 1 und nach dem
  Sicherheitsnetz in Phase 2 (dort notfalls zeilenweise, an bestehenden Bereichen beschnitten).
- **Breitere oder schmalere Elemente bleiben eigene Blöcke:** Zusammenlegen nur bei gleichem linkem *und*
  rechtem Rand, gleicher Gestaltung und Abstand höchstens etwa einer Zeile. Jeder Textbereich wird zeilenweise
  geprüft und bei einem Wechsel von Breite, Spaltenaufteilung, Hintergrund- oder Schriftfarbe geteilt.
- **Farbige Blöcke:** blasse Tönungen werden erkannt; die Kastenfarbe wird nur aus schriftfreien Pixeln bestimmt
  und mit dem Papier direkt daneben verglichen (keine Scheinkästen durch Vergilbung oder Schatten).
- Testsammlung um zwei Seitentypen erweitert (spaltenübergreifende Kästen/Überschriften, farbige Blöcke);
  neue Kennzahl „Überlappungen im Aufbau“. Ergebnis an allen 24 Seiten: Blöcke 99,3 %, Reihenfolge 100 %,
  0 Vermischungen, 0 Überlappungen. Offen: ein sehr blasses Band auf einer gealterten Seite wird nicht als
  Kasten erkannt (sein Text bleibt trotzdem ein eigener Block, nur der Hintergrund fehlt im Neusatz).

## Fehlerbehebung: Speicher nach dem Beenden der Modell-Laufzeit (17.10.2026)
- Beim Beenden blieben die Modellprozesse (`llama-server`) als Waisen zurück und belegten mehrere Gigabyte
  Arbeitsspeicher – nach einigen Läufen konnte der Speicher volllaufen (Verlangsamung, Abbrüche).
  Jetzt wird der ganze Prozessbaum beendet; beim Start werden Reste früherer Sitzungen beseitigt
  (nur programmeigene, am Installationspfad erkannt).

## Qualitätssicherung
- 161 automatische Tests (synthetische Testdokumente, echter Tesseract/Pandoc/Typst, nachgebildete Modell-Laufzeit),
  darunter Ende-zu-Ende-Qualitätsschranken der Layouterkennung an schwierigen Seiten der Testsammlung.
- Tests mit echten Modellen auf dem Entwicklungsrechner (ohne Grafikkarte): Gemma 4 E2B und 12B.
- Setup.exe mehrfach installiert, gestartet und rückstandslos deinstalliert.

## Offen
- Praxistest der Übersetzungsqualität und Geschwindigkeit auf dem Gaming-PC (Zeitprotokoll erbeten).
- Mac-Fassung (zurückgestellt), GitHub-Veröffentlichung und kostenlose Signatur (noch nicht begonnen).
