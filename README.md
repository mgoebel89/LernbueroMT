# Lernbüro MT

Offener Unterricht, ohne den Überblick zu verlieren: ein Container für die Schule. Lehrkräfte stellen Lernpakete aus
Moodle-Aufgaben zusammen, Schülerinnen und Schüler planen daraus ihren eigenen Weg über die Unterrichtstage, schätzen
sich mit Kann-Listen ein und melden sich für Gelingensnachweise bereit. Entwickelt für die Mechatronik an der
David-Roentgen-Schule Neuwied. Das abgestimmte Konzept steht in [KONZEPT.html](KONZEPT.html) (Fassung 2).

Jede Entscheidung ist ein Eintrag mit Zeitstempel. Plan, Ist, Verschiebungen und der Stand an jedem Unterrichtstag
werden daraus berechnet. Inhalte, Abgaben und Tests bleiben in Moodle.

## Stand

| Stufe | Inhalt | Stand |
|---|---|---|
| A | Grundgerüst: Installation, Lehrkraft-Konten, HTTPS für den Lehrerbereich, HTTP für die Schülerseiten, Firewall, Update und Sicherung aus dem Lehrerbereich; Klassen mit Team und Einsicht; Moodle-Teilnehmerliste mit Zuordnungstabelle; Zugangscodes, QR-Codes und QR-Karten als PDF; Schülerseite mit der Symbol-Leiste | gebaut (0.1.1) |
| B | Unterrichtstage als Regeln (Wochentag, jede/gerade/ungerade KW), Ferien aus dem Schulkalender-Abo oder von Hand, „fällt aus“ und „findet statt, ohne Sie“; Paket-Editor mit Pflichtaufgaben, Wahlgruppen, Zusatzaufgaben, Kann-Liste, Gelingensnachweis, Fristen (Aufgabe vor Gruppe vor Paket, rutschen auf den nächsten Unterrichtstag), Freigabe ab einem Unterrichtstag, Kopieren in eine Klasse oder als eigene Vorlage | gebaut (0.2.0) |
| C | Lernplan der Schüler: Raster über die Unterrichtstage (antippen oder Balken ziehen, vergangene Tage gesperrt), Moodle-Link am Aufgabennamen, Wahl und Abwahl in Wahlgruppen, Frage bei Ausfall (verschieben zählt nicht als eigene Verschiebung), Heute mit „Tag abschließen“ (bearbeitet + Ampel je Aufgabe, Erinnerung nach einer Woche), Kann-Liste vorher; Lehrkraft: Klassenmatrix mit Ampel und Hinweisen, Schülerseite mit Plan und Entscheidungen | gebaut (0.3.0) |
| D | Fertig melden mit Kann-Aussagen „nachher“, Eingang „Zu prüfen“, Rückmeldung mit Ihrer Einschätzung daneben, Entscheidung angenommen / überarbeiten bis (eigene Frist), Empfehlungen freiwillig oder verbindlich (Zusatzaufgaben nur auf Empfehlung), Entwurf nur für den Verfasser; Hilfe-Knopf live mit Platz in der Reihe; Sprech- und Prüfungszeiten mit Dauer und Puffer, Feedbacktermine mit Anlass (einer offen, Absage bis Vortag); „Gespräch nötig“ aus „Zu prüfen“ als Pflichttermin aus der eigenen Sprechzeit (0.5.1); Farbmarkierung je Tag und Aufgabe im Plan nach dem Zeitplan, Planen nur über „Plan bearbeiten“ (0.5.1); „Jetzt“-Spalte in der Übersicht; Diktat im Rückmeldungsfenster (Whisper „small“ im Container, Aufnahme danach gelöscht, Fachwörter des Pakets als Vorgabe) | gebaut (0.4.1) |
| E | Gelingensnachweise: „Ich bin bereit“ mit der ganzen Kann-Liste „nachher“, jede Bereitmeldung ein Versuch (alle bleiben sichtbar); Moodle-Test mit „in Moodle freigeschaltet“, Fachgespräch und praktische Prüfung mit Termin in der Prüfungszeit; Ergebnis im Rückmeldungsfenster (Diktat, Kann-Einschätzung, Empfehlungen): gelungen / noch nicht gelungen, wahlweise Punkte oder Note, bei „noch nicht“ neue Frist ohne Sperre; Bereit-Liste („Nachweise“, „Jetzt“-Spalte), GN-Spalten in der Klassenmatrix | gebaut (0.5.0) |
| 0.6 | Zweierteams je Aufgabe oder ganzes Paket (Einladung mit Bestätigung, Lehrkraft kann bilden und auflösen; gemeinsam Plan, Wahl, Fertigmeldung, Rückmeldung; je Person Farben, Kann-Liste, Empfehlungen, Gelingensnachweis); Handy und Tablet hochkant: Plan als Seite mit 4 Unterrichtstagen zum Blättern, Planungsblatt mit allen Tagen je Aufgabe | gebaut (0.6.0) |
| F | Kalender (Dienstkalender, Halbjahr), Verlauf, Lernstand-Bericht und Klassenübersicht als PDF, Archiv | geplant |

## Installation (Proxmox VE)

Auf dem Proxmox-Host in der Shell des Knotens (das Repo muss dafür öffentlich sein):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/mgoebel89/LernbueroMT/main/proxmox/lernbuero.sh)"
```

Das Skript legt einen unprivilegierten Ubuntu-24.04-Container an (Vorschlag 4 Kerne, 6 GB RAM, 16 GB Platte, für die
Spracherkennung ab Stufe D) und installiert Lernbüro MT. Am Ende zeigt es die Adresse und den Einrichtungscode. Im
Browser `https://<container>/einrichtung` öffnen und das erste Admin-Konto anlegen.

Ohne Proxmox, in einem vorhandenen Ubuntu-24.04- oder Debian-12-System als root:

```bash
git clone https://github.com/mgoebel89/LernbueroMT /opt/lernbuero && bash /opt/lernbuero/deploy/install.sh
```

**HTTPS:** Der Container stellt sich sein Zertifikat mit einer eigenen kleinen Zertifizierungsstelle aus (wie im
TrackingDRS). Damit der Browser nicht warnt, das Stammzertifikat von `http://<container>/ca.crt` auf den Lehrer-Geräten
installieren. Die Zertifizierungsstelle darf nur für das Netz des Containers ausstellen.

**Schülerseiten über HTTP:** Die Schülergeräte haben das Stammzertifikat nicht. Deshalb bedient Port 80 nur die
Schülerseiten: die Startseite zum Code-Eingeben (`/`), den Plan (`/s/<Code>`) und ihre Schnittstelle. Alles andere
leitet nach HTTPS um bzw. wird abgelehnt (Passwörter gehen nie unverschlüsselt). Der QR-Code auf der Karte führt auf
`http://<container>/s/<Code>`; die Adresse lässt sich unter *Einstellungen* festlegen (z. B. ein DNS-Name statt der IP).

**Zugangscodes:** 8 Zeichen ohne leicht verwechselbare (kein I, L, O, 0, 1), angezeigt als `K7Q4-M2XD`. Ein neuer Code
macht den alten sofort ungültig. Falsche Codes bremsen wie falsche Passwörter (nach fünf Fehlern eine Minute Pause).

## Betrieb

| Befehl (im Container) | Wirkung |
|---|---|
| `lernbuero-update` | neuesten Stand holen und neu installieren, Daten bleiben |
| `lernbuero sicherung` | Sicherung (ZIP) nach `/var/lib/lernbuero/sicherungen` |
| `lernbuero einrichtungscode` | Code für die erste Einrichtung zeigen |
| `lernbuero konten` | Lehrkraft-Konten auflisten |
| `lernbuero passwort <kürzel>` | vorläufiges Passwort setzen und Konto entsperren |
| `journalctl -u lernbuero -f` | Protokoll der Webseite |

Daten: `/var/lib/lernbuero` (SQLite-Datenbank, Zertifikate, Sicherungen). Programm: `/opt/lernbuero` (gehört root).

**Update ohne Konsole:** Unter *Einstellungen* sehen Admins die installierte Version und ob es auf GitHub eine neuere
gibt. *Jetzt aktualisieren* legt erst eine Sicherung an (die letzten fünf bleiben) und führt dann `lernbuero-update`
aus. Der Webdienst selbst darf nichts installieren: Er legt nur eine Anfrage-Datei in `/var/lib/lernbuero/update` ab,
systemd startet daraufhin `lernbuero-selbstupdate` als root.

## Rechte je Klasse

| Rolle | darf |
|---|---|
| Team | alles in der Klasse: Schüler, Zugangscodes, Moodle-Import, später Pakete, Rückmeldungen, Empfehlungen; weitere Lehrkräfte eintragen |
| Einsicht | alles lesen, nichts ändern, keine Zugangscodes (z. B. Klassenleitung) |
| Admin ohne Zuordnung | Name und Lehrkräfte der Klasse sehen und zuordnen, keine Schülerdaten |

Eine Klasse behält immer mindestens eine Lehrkraft im Team.

## Moodle-Teilnehmerliste

In Moodle: Kurs → Teilnehmer/innen → alle auswählen → „Herunterladen als CSV“ (oder JSON). Gelesen wird dasselbe
Format wie im Lehrerkalender (drs-lxc): CSV mit Kopfzeile (Vorname, Nachname, …), eine Liste `Nachname;Vorname` oder
JSON. Trainer/innen werden übersprungen, gespeichert werden nur Vor- und Nachname. Vor dem Schreiben zeigt eine
Zuordnungstabelle, wer behalten, neu angelegt oder wieder aktiv wird; wer nicht mehr in Moodle steht, wird nur auf
ausdrücklichen Wunsch archiviert.

## Entwicklung

Python 3.11 oder neuer. QR-Codes und PDF schreibt das Programm selbst; für das Schulkalender-Abo `icalendar` und `recurring-ical-events` (im Container `python3-icalendar`, `python3-recurring-ical-events`, die Installation holt sie; ohne sie läuft alles andere weiter). Im Repo-Ordner:

```bash
python -m unittest discover -s tests
```

```bash
python tests/dev_server.py 8471
```

Der Testserver läuft ohne TLS auf `http://127.0.0.1:8471`, Lehrerbereich und Schülerseiten auf demselben Port, Daten in
`.dev-daten`. Für die Syntaxprüfung der Skripte in `web/` optional `python -m pip install esprima`.
