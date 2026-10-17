# Fehlalarm eines Virenscanners melden (kostenlos)

Programme, die mit PyInstaller gebaut sind, werden gelegentlich fälschlich als verdächtig eingestuft.
Der automatische Bau übersetzt den Programmstarter deshalb selbst aus dem Quellcode (häufigste Ursache).
Meldet Microsoft Defender trotzdem etwas, so wird der Fehlalarm gemeldet – Microsoft prüft die Datei und
nimmt die Erkennung zurück, meist innerhalb weniger Tage.

## Microsoft Defender

1. Seite <https://www.microsoft.com/en-us/wdsi/filesubmission> öffnen (Microsoft-Konto nötig, kostenlos).
2. **Submit as:** „Software developer“.
3. **Product:** „Microsoft Defender Antivirus (Windows 10/11)“.
4. **File:** die betroffene Datei (Setup.exe bzw. `Quellenuebersetzer.exe`) hochladen.
5. **What do you believe this file is?** „Incorrectly detected as malware/malicious“.
6. **Detection name:** genau so, wie Defender ihn anzeigt (z. B. `Trojan:Win32/Wacatac…`).
7. **Additional information** (Vorlage):

```
Quellenuebersetzer is a free, open-source (GPL-3.0) Windows application that reads and translates
historical documents locally. Source code and the automated build that produced this file:
https://github.com/arnoldrautenberg490-blip/quellenuebersetzer (GitHub Actions workflow "Bauen").
The executable is built with PyInstaller (bootloader compiled from source in the public workflow)
and packaged with Inno Setup. SHA-256 of the file is published next to the download (SHA256.txt).
The detection is a false positive; please re-evaluate.
```

## Andere Virenscanner

Die meisten Hersteller haben ein eigenes Formular („false positive“). Eine Übersicht über die Erkennung
aller gängigen Scanner liefert VirusTotal (<https://www.virustotal.com>) – dort nur die **veröffentlichte**
Setup.exe hochladen, niemals Dokumente oder verarbeitete Daten.
