; Inno-Setup-Skript für den Quellenübersetzer.
; Bau: ISCC.exe packaging\setup.iss   (erwartet das PyInstaller-Ergebnis in build\dist\Quellenuebersetzer)
;
; - Installation nur für den aktuellen Benutzer, ohne Administratorrechte
; - Eintrag unter „Apps & Features“ mit vollständiger Deinstallation (inkl. heruntergeladener Modelle)

#define AppName "Quellenübersetzer"
#define AppId "Quellenuebersetzer"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6C1E3D2A-7B4F-4E9A-9C21-5A0F2B7D8E11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Quellenübersetzer (freie Software)
AppPublisherURL=https://github.com/arnoldrautenberg490-blip/quellenuebersetzer
AppSupportURL=https://github.com/arnoldrautenberg490-blip/quellenuebersetzer/issues
DefaultDirName={localappdata}\Programs\{#AppId}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=..\build\setup
OutputBaseFilename=Quellenuebersetzer-Setup-{#AppVersion}
SetupIconFile=..\src\quellenuebersetzer\resources\icon.ico
UninstallDisplayIcon={app}\Quellenuebersetzer.exe
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
CloseApplications=yes
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} – Einrichtung

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Messages]
de.WelcomeLabel2=Dieses Programm liest und übersetzt historische Quellen vollständig auf Ihrem Rechner.%n%nIhre Dokumente verlassen das Gerät nicht. Nach der Installation führt Sie ein kurzer Assistent durch die Einrichtung.%n%nAlle Bestandteile sind kostenlos und quelloffen.
de.FinishedLabel=Die Installation ist abgeschlossen. Der {#AppName} startet jetzt und richtet beim ersten Mal die passenden Sprachmodelle für Ihren Rechner ein.

[Tasks]
Name: "desktopicon"; Description: "Verknüpfung auf dem Desktop anlegen"; Flags: checkedonce

[Files]
Source: "..\build\dist\Quellenuebersetzer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LIZENZ.txt"; Flags: ignoreversion
Source: "..\packaging\LIESMICH.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\Quellenuebersetzer.exe"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\Quellenuebersetzer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Quellenuebersetzer.exe"; Description: "{#AppName} jetzt starten"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Entfernt Modelle, Wörterbücher und Hilfsprogramme; sichert vorher Glossar und Korrekturen in „Dokumente“.
Filename: "{app}\Quellenuebersetzer.exe"; Parameters: "--daten-entfernen"; Flags: runhidden waituntilterminated; RunOnceId: "DatenEntfernen"

[UninstallDelete]
; Sicherheitsnetz, falls das Programm selbst nicht mehr startet (nur der eigene, fest benannte Datenordner).
Type: filesandordirs; Name: "{localappdata}\{#AppId}"
Type: filesandordirs; Name: "{app}"
