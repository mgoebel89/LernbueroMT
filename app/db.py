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
