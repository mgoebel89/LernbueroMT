"""Datenbank (SQLite): Verbindung, Schema-Migrationen, Zeit und Ereignisprotokoll.

Grundsatz wie im TrackingDRS: Jede Entscheidung landet zusaetzlich als Zeile in `ereignis` (nur anhaengen, nie aendern).
Daraus entstehen spaeter Verlauf, Plan gegen Ist und der Stand je Unterrichtstag. Die uebrigen Tabellen halten den
aktuellen Stand.
"""
import datetime
import json
import os
import sqlite3

try:
    from zoneinfo import ZoneInfo
    ZONE = ZoneInfo("Europe/Berlin")
except Exception:   # Windows ohne tzdata (lokales Testen): Ortszeit des Rechners
    ZONE = None

DATEINAME = "lernbuero.sqlite"


def jetzt():
    """Aktuelle Zeit in Berlin als ISO-Text ohne Zeitzone, sekundengenau (so steht sie in der Datenbank)."""
    t = datetime.datetime.now(ZONE) if ZONE else datetime.datetime.now()
    return t.replace(tzinfo=None, microsecond=0).isoformat()


def heute():
    return datetime.date.fromisoformat(jetzt()[:10])


def verbinden(pfad):
    con = sqlite3.connect(pfad, timeout=10, isolation_level=None)   # Autocommit; Transaktionen mit transaktion()
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 10000")
    return con


class transaktion:
    """with transaktion(con): ... -> BEGIN IMMEDIATE / COMMIT, bei Fehler ROLLBACK."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, art, wert, spur):
        self.con.execute("COMMIT" if art is None else "ROLLBACK")
        return False


MIGRATIONEN = [
    # 1: Grundgeruest (Stufe A): Konten, Klassen mit Team und Einsicht, Schueler mit Zugangscode, Ereignisse
    """
    CREATE TABLE einstellung (schluessel TEXT PRIMARY KEY, wert TEXT NOT NULL);
    CREATE TABLE lehrkraft (
        id INTEGER PRIMARY KEY,
        kuerzel TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        rolle TEXT NOT NULL CHECK (rolle IN ('admin', 'lehrkraft')),
        pw TEXT NOT NULL,
        pw_vorlaeufig INTEGER NOT NULL DEFAULT 1,
        gesperrt INTEGER NOT NULL DEFAULT 0,
        stand INTEGER NOT NULL DEFAULT 1,
        erstellt TEXT NOT NULL);
    CREATE TABLE abgemeldet (signatur TEXT PRIMARY KEY, ablauf INTEGER NOT NULL);
    CREATE TABLE klasse (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        schuljahr TEXT NOT NULL DEFAULT '',
        moodle_kurs TEXT NOT NULL DEFAULT '',
        einschaetzer TEXT NOT NULL DEFAULT 'smiley' CHECK (einschaetzer IN ('smiley', 'zahl')),
        archiviert INTEGER NOT NULL DEFAULT 0,
        erstellt TEXT NOT NULL);
    CREATE TABLE klasse_lehrkraft (
        klasse_id INTEGER NOT NULL REFERENCES klasse(id) ON DELETE CASCADE,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id),
        rolle TEXT NOT NULL CHECK (rolle IN ('team', 'einsicht')),
        PRIMARY KEY (klasse_id, lehrkraft_id));
    CREATE TABLE schueler (
        id INTEGER PRIMARY KEY,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id) ON DELETE CASCADE,
        vorname TEXT NOT NULL,
        nachname TEXT NOT NULL,
        code TEXT NOT NULL UNIQUE,
        aktiv INTEGER NOT NULL DEFAULT 1,
        erstellt TEXT NOT NULL);
    CREATE INDEX schueler_klasse ON schueler (klasse_id);
    CREATE TABLE ereignis (
        id INTEGER PRIMARY KEY,
        zeit TEXT NOT NULL,
        klasse_id INTEGER REFERENCES klasse(id) ON DELETE CASCADE,
        schueler_id INTEGER REFERENCES schueler(id) ON DELETE CASCADE,
        wer_art TEXT NOT NULL CHECK (wer_art IN ('lehrkraft', 'schueler', 'system')),
        wer TEXT NOT NULL,
        art TEXT NOT NULL,
        daten TEXT NOT NULL DEFAULT '{}');
    CREATE INDEX ereignis_klasse ON ereignis (klasse_id, id);
    CREATE INDEX ereignis_schueler ON ereignis (schueler_id, id);
    """,
    # 2: Unterrichtstage und Lernpakete (Stufe B). Datum als ISO-Text, Uhrzeit als HH:MM. Nichts wird geloescht, was
    # Schueler schon sehen koennten: Regeln, Tage, Aufgaben werden deaktiviert (aktiv = 0).
    """
    CREATE TABLE unterrichtsregel (
        id INTEGER PRIMARY KEY,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id) ON DELETE CASCADE,
        wochentag INTEGER NOT NULL CHECK (wochentag BETWEEN 0 AND 6),
        rhythmus TEXT NOT NULL DEFAULT 'jede' CHECK (rhythmus IN ('jede', 'gerade', 'ungerade')),
        von TEXT NOT NULL,
        bis TEXT NOT NULL,
        gueltig_von TEXT NOT NULL,
        gueltig_bis TEXT NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1,
        erstellt TEXT NOT NULL);
    CREATE TABLE tag_besonders (
        id INTEGER PRIMARY KEY,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id) ON DELETE CASCADE,
        von TEXT NOT NULL,
        bis TEXT NOT NULL,
        art TEXT NOT NULL CHECK (art IN ('ausfall', 'ohne')),
        grund TEXT NOT NULL,
        wer TEXT NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1,
        erstellt TEXT NOT NULL);
    CREATE TABLE ferien (
        id INTEGER PRIMARY KEY,
        von TEXT NOT NULL,
        bis TEXT NOT NULL,
        name TEXT NOT NULL,
        quelle TEXT NOT NULL DEFAULT 'hand' CHECK (quelle IN ('hand', 'abo')),
        aktiv INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE kalender_abo (
        id INTEGER PRIMARY KEY,
        art TEXT NOT NULL CHECK (art IN ('dienst', 'schule')),
        lehrkraft_id INTEGER REFERENCES lehrkraft(id),
        url TEXT NOT NULL,
        versuch TEXT,
        stand TEXT,
        fehler TEXT,
        anzahl INTEGER NOT NULL DEFAULT 0);
    CREATE UNIQUE INDEX kalender_abo_wer ON kalender_abo (art, COALESCE(lehrkraft_id, 0));
    CREATE TABLE kalender_termin (
        abo_id INTEGER NOT NULL REFERENCES kalender_abo(id) ON DELETE CASCADE,
        beginn TEXT NOT NULL,
        ende TEXT NOT NULL,
        ganztags INTEGER NOT NULL DEFAULT 0,
        titel TEXT NOT NULL,
        ort TEXT NOT NULL DEFAULT '');
    CREATE INDEX kalender_termin_zeit ON kalender_termin (abo_id, beginn);
    CREATE TABLE paket (
        id INTEGER PRIMARY KEY,
        klasse_id INTEGER REFERENCES klasse(id) ON DELETE CASCADE,
        besitzer_id INTEGER REFERENCES lehrkraft(id),
        titel TEXT NOT NULL,
        lernfeld TEXT NOT NULL DEFAULT '',
        freigabe TEXT,
        frist TEXT,
        archiviert INTEGER NOT NULL DEFAULT 0,
        aus_paket_id INTEGER,
        erstellt TEXT NOT NULL);
    CREATE INDEX paket_klasse ON paket (klasse_id);
    CREATE TABLE wahlgruppe (
        id INTEGER PRIMARY KEY,
        paket_id INTEGER NOT NULL REFERENCES paket(id) ON DELETE CASCADE,
        buchstabe TEXT NOT NULL,
        titel TEXT NOT NULL DEFAULT '',
        waehlen INTEGER NOT NULL DEFAULT 1,
        frist TEXT,
        pos INTEGER NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE aufgabe (
        id INTEGER PRIMARY KEY,
        paket_id INTEGER NOT NULL REFERENCES paket(id) ON DELETE CASCADE,
        kuerzel TEXT NOT NULL,
        titel TEXT NOT NULL,
        art TEXT NOT NULL CHECK (art IN ('pflicht', 'wahl', 'zusatz')),
        wahlgruppe_id INTEGER REFERENCES wahlgruppe(id),
        zusatz_art TEXT CHECK (zusatz_art IN ('vertiefung', 'wiederholung')),
        frist TEXT,
        moodle_link TEXT NOT NULL DEFAULT '',
        voraussetzung_id INTEGER REFERENCES aufgabe(id),
        pos INTEGER NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1,
        erstellt TEXT NOT NULL);
    CREATE INDEX aufgabe_paket ON aufgabe (paket_id);
    CREATE TABLE kann_aussage (
        id INTEGER PRIMARY KEY,
        paket_id INTEGER NOT NULL REFERENCES paket(id) ON DELETE CASCADE,
        kuerzel TEXT NOT NULL,
        text TEXT NOT NULL,
        pos INTEGER NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE kann_aufgabe (
        kann_id INTEGER NOT NULL REFERENCES kann_aussage(id) ON DELETE CASCADE,
        aufgabe_id INTEGER NOT NULL REFERENCES aufgabe(id) ON DELETE CASCADE,
        PRIMARY KEY (kann_id, aufgabe_id));
    CREATE TABLE nachweis (
        id INTEGER PRIMARY KEY,
        paket_id INTEGER NOT NULL REFERENCES paket(id) ON DELETE CASCADE,
        titel TEXT NOT NULL DEFAULT '',
        art TEXT NOT NULL CHECK (art IN ('moodle', 'praxis', 'fachgespraech')),
        ergebnis TEXT NOT NULL DEFAULT 'gelungen' CHECK (ergebnis IN ('gelungen', 'punkte', 'note')),
        max_punkte INTEGER,
        frist TEXT,
        moodle_link TEXT NOT NULL DEFAULT '',
        pos INTEGER NOT NULL,
        aktiv INTEGER NOT NULL DEFAULT 1)
    """,
    # 3: Lernplan der Schueler (Stufe C). Aktueller Stand in plan/wahl/ist/abschluss/kann_einschaetzung, jede Aenderung
    # zusaetzlich als Ereignis (Verlauf und Stand je Unterrichtstag in Stufe F).
    """
    CREATE TABLE plan (
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        aufgabe_id INTEGER NOT NULL REFERENCES aufgabe(id) ON DELETE CASCADE,
        datum TEXT NOT NULL,
        PRIMARY KEY (schueler_id, aufgabe_id, datum));
    CREATE TABLE wahl (
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        aufgabe_id INTEGER NOT NULL REFERENCES aufgabe(id) ON DELETE CASCADE,
        zeit TEXT NOT NULL,
        PRIMARY KEY (schueler_id, aufgabe_id));
    CREATE TABLE ist (
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        aufgabe_id INTEGER NOT NULL REFERENCES aufgabe(id) ON DELETE CASCADE,
        datum TEXT NOT NULL,
        ampel TEXT NOT NULL CHECK (ampel IN ('g', 'y', 'r')),
        PRIMARY KEY (schueler_id, aufgabe_id, datum));
    CREATE TABLE abschluss (
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        datum TEXT NOT NULL,
        zeit TEXT NOT NULL,
        PRIMARY KEY (schueler_id, datum));
    CREATE TABLE kann_einschaetzung (
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        kann_id INTEGER NOT NULL REFERENCES kann_aussage(id) ON DELETE CASCADE,
        art TEXT NOT NULL CHECK (art IN ('vorher', 'nachher', 'lehrkraft')),
        stufe INTEGER NOT NULL CHECK (stufe BETWEEN 1 AND 4),
        zeit TEXT NOT NULL,
        wer TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (schueler_id, kann_id, art))
    """,
    # 4: Melden, Rueckmeldung, Empfehlungen, Hilfe-Reihe, Sprech- und Pruefungszeiten (Stufe D)
    """
    CREATE TABLE meldung (
        id INTEGER PRIMARY KEY,
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        aufgabe_id INTEGER NOT NULL REFERENCES aufgabe(id) ON DELETE CASCADE,
        zeit TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'offen' CHECK (status IN ('offen', 'angenommen', 'ueberarbeiten', 'zurueckgezogen')),
        entschieden TEXT,
        entschieden_von INTEGER REFERENCES lehrkraft(id));
    CREATE INDEX meldung_schueler ON meldung (schueler_id, aufgabe_id);
    CREATE TABLE schueler_frist (
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        aufgabe_id INTEGER NOT NULL REFERENCES aufgabe(id) ON DELETE CASCADE,
        frist TEXT NOT NULL,
        grund TEXT NOT NULL DEFAULT 'ueberarbeiten',
        PRIMARY KEY (schueler_id, aufgabe_id));
    CREATE TABLE rueckmeldung (
        id INTEGER PRIMARY KEY,
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        verfasser_id INTEGER NOT NULL REFERENCES lehrkraft(id),
        meldung_id INTEGER REFERENCES meldung(id) ON DELETE SET NULL,
        termin_id INTEGER,
        aufgabe_id INTEGER REFERENCES aufgabe(id) ON DELETE SET NULL,
        paket_id INTEGER REFERENCES paket(id) ON DELETE SET NULL,
        text TEXT NOT NULL DEFAULT '',
        entscheidung TEXT CHECK (entscheidung IN ('angenommen', 'ueberarbeiten')),
        neue_frist TEXT,
        erstellt TEXT NOT NULL,
        geaendert TEXT NOT NULL,
        freigegeben TEXT,
        gelesen TEXT);
    CREATE INDEX rueckmeldung_schueler ON rueckmeldung (schueler_id);
    CREATE TABLE rueckmeldung_kann (
        rueckmeldung_id INTEGER NOT NULL REFERENCES rueckmeldung(id) ON DELETE CASCADE,
        kann_id INTEGER NOT NULL REFERENCES kann_aussage(id) ON DELETE CASCADE,
        stufe INTEGER NOT NULL CHECK (stufe BETWEEN 1 AND 4),
        PRIMARY KEY (rueckmeldung_id, kann_id));
    CREATE TABLE empfehlung (
        id INTEGER PRIMARY KEY,
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        aufgabe_id INTEGER NOT NULL REFERENCES aufgabe(id) ON DELETE CASCADE,
        rueckmeldung_id INTEGER REFERENCES rueckmeldung(id) ON DELETE CASCADE,
        verfasser_id INTEGER NOT NULL REFERENCES lehrkraft(id),
        verbindlich INTEGER NOT NULL DEFAULT 0,
        frist TEXT,
        hinweis TEXT NOT NULL DEFAULT '',
        erstellt TEXT NOT NULL,
        freigegeben TEXT,
        erledigt TEXT,
        entfernt TEXT);
    CREATE INDEX empfehlung_schueler ON empfehlung (schueler_id);
    CREATE TABLE hilfe (
        id INTEGER PRIMARY KEY,
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id) ON DELETE CASCADE,
        aufgabe_id INTEGER REFERENCES aufgabe(id) ON DELETE SET NULL,
        datum TEXT NOT NULL,
        zeit TEXT NOT NULL,
        ende TEXT,
        ende_art TEXT CHECK (ende_art IN ('erledigt', 'zurueckgezogen')),
        ende_von INTEGER REFERENCES lehrkraft(id));
    CREATE INDEX hilfe_klasse ON hilfe (klasse_id, datum);
    CREATE TABLE zeitfenster (
        id INTEGER PRIMARY KEY,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id) ON DELETE CASCADE,
        lehrkraft_id INTEGER NOT NULL REFERENCES lehrkraft(id),
        art TEXT NOT NULL CHECK (art IN ('sprech', 'pruefung')),
        von TEXT NOT NULL,
        bis TEXT NOT NULL,
        dauer INTEGER NOT NULL,
        puffer INTEGER NOT NULL DEFAULT 0,
        wochentag INTEGER,
        gueltig_von TEXT,
        gueltig_bis TEXT,
        tage TEXT NOT NULL DEFAULT '[]',
        aktiv INTEGER NOT NULL DEFAULT 1,
        erstellt TEXT NOT NULL);
    CREATE INDEX zeitfenster_klasse ON zeitfenster (klasse_id);
    CREATE TABLE termin (
        id INTEGER PRIMARY KEY,
        zeitfenster_id INTEGER NOT NULL REFERENCES zeitfenster(id) ON DELETE CASCADE,
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        datum TEXT NOT NULL,
        beginn TEXT NOT NULL,
        ende TEXT NOT NULL,
        art TEXT NOT NULL CHECK (art IN ('feedback', 'fachgespraech', 'praxis')),
        anlass_aufgabe_id INTEGER REFERENCES aufgabe(id) ON DELETE SET NULL,
        anlass_paket_id INTEGER REFERENCES paket(id) ON DELETE SET NULL,
        anlass_text TEXT NOT NULL DEFAULT '',
        nachweis_id INTEGER,
        gebucht TEXT NOT NULL,
        abgesagt TEXT,
        abgesagt_von TEXT);
    CREATE INDEX termin_platz ON termin (zeitfenster_id, datum, beginn)
    """,
    # 5: Gelingensnachweise (Stufe E). Ein Versuch je Bereitmeldung; das Ergebnis schreibt die Lehrkraft ueber eine
    # Rueckmeldung (Entwurf, Diktat, Kann-Einschaetzung, Empfehlungen), die den Versuch bei der Freigabe abschliesst.
    """
    CREATE TABLE versuch (
        id INTEGER PRIMARY KEY,
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        nachweis_id INTEGER NOT NULL REFERENCES nachweis(id) ON DELETE CASCADE,
        nr INTEGER NOT NULL,
        bereit TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'bereit' CHECK (status IN ('bereit', 'frei', 'gelungen', 'nicht', 'zurueckgezogen')),
        frei TEXT,
        frei_von INTEGER REFERENCES lehrkraft(id),
        termin_id INTEGER REFERENCES termin(id) ON DELETE SET NULL,
        ergebnis_zeit TEXT,
        ergebnis_von INTEGER REFERENCES lehrkraft(id),
        punkte REAL,
        note TEXT,
        neue_frist TEXT);
    CREATE INDEX versuch_schueler ON versuch (schueler_id, nachweis_id);
    CREATE TABLE nachweis_frist (
        schueler_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        nachweis_id INTEGER NOT NULL REFERENCES nachweis(id) ON DELETE CASCADE,
        frist TEXT NOT NULL,
        PRIMARY KEY (schueler_id, nachweis_id));
    ALTER TABLE rueckmeldung ADD COLUMN versuch_id INTEGER REFERENCES versuch(id) ON DELETE SET NULL;
    ALTER TABLE rueckmeldung ADD COLUMN ergebnis TEXT;
    ALTER TABLE rueckmeldung ADD COLUMN punkte REAL;
    ALTER TABLE rueckmeldung ADD COLUMN note TEXT
    """,
    # 6: Gespraechstermin aus "Zu pruefen": die Lehrkraft traegt den Termin ein (Pflicht, nur Lehrkraefte sagen ab)
    """
    ALTER TABLE termin ADD COLUMN pflicht INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE termin ADD COLUMN meldung_id INTEGER REFERENCES meldung(id) ON DELETE SET NULL;
    ALTER TABLE termin ADD COLUMN hinweis TEXT NOT NULL DEFAULT ''
    """,
    # 7: Zweierteams. Die Lehrkraft erlaubt "zu zweit" je Aufgabe oder fuers ganze Paket; ein Team gilt fuer eine Aufgabe
    # (bereich 'aufgabe') oder alle Aufgaben eines Pakets (bereich 'paket'). Gemeinsam: Plan, Fertigmeldung (gruppe),
    # Rueckmeldung und Entscheidung; je Person: Kann-Einschaetzung, Farbmarkierung, Empfehlungen, Gelingensnachweis.
    """
    ALTER TABLE aufgabe ADD COLUMN team INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE paket ADD COLUMN team INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE meldung ADD COLUMN gruppe INTEGER;
    CREATE TABLE team (
        id INTEGER PRIMARY KEY,
        klasse_id INTEGER NOT NULL REFERENCES klasse(id) ON DELETE CASCADE,
        bereich TEXT NOT NULL CHECK (bereich IN ('aufgabe', 'paket')),
        bezug_id INTEGER NOT NULL,
        a_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        b_id INTEGER NOT NULL REFERENCES schueler(id) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK (status IN ('eingeladen', 'aktiv', 'aufgeloest')),
        erstellt TEXT NOT NULL,
        bestaetigt TEXT,
        ende TEXT,
        ende_von TEXT);
    CREATE INDEX team_bezug ON team (bereich, bezug_id)
    """,
]


def migrieren(con):
    """Bringt das Schema auf den neuesten Stand (PRAGMA user_version = Anzahl angewandter Migrationen).
    Ein Eintrag als Tupel (OHNE_FK, sql) baut eine Tabelle neu auf: dafuer ist die Fremdschluessel-Pruefung kurz aus,
    danach muss PRAGMA foreign_key_check leer sein, sonst wird alles zurueckgerollt."""
    stand = con.execute("PRAGMA user_version").fetchone()[0]
    for nummer in range(stand, len(MIGRATIONEN)):
        eintrag = MIGRATIONEN[nummer]
        ohne_fk = isinstance(eintrag, tuple)
        sql = eintrag[1] if ohne_fk else eintrag
        if ohne_fk:
            con.execute("PRAGMA foreign_keys = OFF")
        con.execute("BEGIN IMMEDIATE")
        try:
            for befehl in sql.split(";"):
                if befehl.strip():
                    con.execute(befehl)
            if ohne_fk and con.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Migration %d: Fremdschluessel verletzt" % (nummer + 1))
            con.execute("PRAGMA user_version = %d" % (nummer + 1))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            if ohne_fk:
                con.execute("PRAGMA foreign_keys = ON")


def pfad(daten_dir):
    return os.path.join(daten_dir, DATEINAME)


def oeffnen(daten_dir):
    """Datenbank im Datenordner oeffnen und migrieren."""
    os.makedirs(daten_dir, exist_ok=True)
    con = verbinden(pfad(daten_dir))
    con.execute("PRAGMA journal_mode = WAL")
    migrieren(con)
    return con


def ereignis(con, klasse_id, schueler_id, wer_art, wer, art, **daten):
    """Haengt ein Ereignis an. wer_art: lehrkraft | schueler | system, wer: Kuerzel bzw. 'Schüler'."""
    con.execute("INSERT INTO ereignis (zeit, klasse_id, schueler_id, wer_art, wer, art, daten) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (jetzt(), klasse_id, schueler_id, wer_art, wer, art, json.dumps(daten, ensure_ascii=False)))


def einstellung(con, schluessel, vorgabe=None):
    zeile = con.execute("SELECT wert FROM einstellung WHERE schluessel = ?", (schluessel,)).fetchone()
    return zeile[0] if zeile else vorgabe


def einstellung_setzen(con, schluessel, wert):
    con.execute("INSERT INTO einstellung (schluessel, wert) VALUES (?, ?) "
                "ON CONFLICT (schluessel) DO UPDATE SET wert = excluded.wert", (schluessel, wert))
