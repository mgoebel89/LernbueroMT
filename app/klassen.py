"""Klassen, Team und Einsicht, Schueler mit persoenlichem Zugangscode.

Zugriff je Klasse:
  team      volle Rechte (Schueler, Codes, Pakete, Rueckmeldungen, weitere Lehrkraefte eintragen)
  einsicht  sieht Plan, Verlauf, Kann-Listen, Rueckmeldungen und Ergebnisse, aendert nichts, sieht keine Zugangscodes
  admin     (ohne eigene Zuordnung) sieht nur Name und Lehrkraefte der Klasse und darf Lehrkraefte zuordnen,
            damit eine Klasse nie ohne Team bleibt; Schuelerdaten sieht ein Admin nur als Team oder mit Einsicht.

Zugangscode: 8 Zeichen ohne leicht verwechselbare (kein I, L, O, 0, 1), angezeigt als K7Q4-M2XD. Der QR-Code fuehrt
auf http://<container>/s/K7Q4M2XD. Ein neuer Code macht den alten sofort ungueltig.
"""
import re
import secrets

from . import db

CODE_ZEICHEN = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE = re.compile(r"[A-HJKMNP-Z2-9]{8}")
ROLLEN = ("team", "einsicht")
EINSCHAETZER = ("smiley", "zahl")


class KlassenFehler(Exception):
    """Fehler mit einer Meldung, die direkt in der Oberflaeche erscheinen darf."""


class KeinZugriff(Exception):
    """Die Lehrkraft darf das nicht (wird zu HTTP 403)."""


def _text(wert, name, mindestens=1, hoechstens=60):
    wert = re.sub(r"\s+", " ", str(wert or "")).strip()
    if not mindestens <= len(wert) <= hoechstens:
        raise KlassenFehler("%s: bitte %d bis %d Zeichen." % (name, mindestens, hoechstens))
    return wert


# --- Zugangscodes ---

def neuer_code(con):
    while True:
        code = "".join(secrets.choice(CODE_ZEICHEN) for _ in range(8))
        if not con.execute("SELECT 1 FROM schueler WHERE code = ?", (code,)).fetchone():
            return code


def code_anzeigen(code):
    return code[:4] + "-" + code[4:]


def code_normalisieren(text):
    """'k7q4-m2xd ' -> 'K7Q4M2XD' oder None, wenn es kein gueltiger Code sein kann."""
    code = re.sub(r"[^A-Za-z0-9]", "", str(text or "")).upper()
    return code if CODE.fullmatch(code) else None


# --- Zugriff ---

def zugriff(con, klasse_id, konto):
    zeile = con.execute("SELECT rolle FROM klasse_lehrkraft WHERE klasse_id = ? AND lehrkraft_id = ?",
                        (klasse_id, konto["id"])).fetchone()
    if zeile:
        return zeile["rolle"]
    if konto["rolle"] == "admin":
        return "admin"
    return None


def _klasse(con, klasse_id):
    zeile = con.execute("SELECT * FROM klasse WHERE id = ?", (klasse_id,)).fetchone()
    if zeile is None:
        raise KlassenFehler("Diese Klasse gibt es nicht.")
    return zeile


def pruefen(con, klasse_id, konto, recht="lesen"):
    """recht: lesen (Team, Einsicht) | aendern (Team) | zuordnen (Team, Admin). Rueckgabe: Rolle."""
    _klasse(con, klasse_id)
    rolle = zugriff(con, klasse_id, konto)
    erlaubt = {"lesen": ("team", "einsicht"), "aendern": ("team",), "zuordnen": ("team", "admin")}[recht]
    if rolle not in erlaubt:
        raise KeinZugriff("Dafür fehlt Ihnen das Recht in dieser Klasse.")
    return rolle


def _lehrkraefte(con, klasse_id):
    zeilen = con.execute("SELECT l.id, l.kuerzel, l.name, kl.rolle FROM klasse_lehrkraft kl JOIN lehrkraft l ON l.id = kl.lehrkraft_id "
                         "WHERE kl.klasse_id = ? ORDER BY l.name", (klasse_id,)).fetchall()
    return {r: [{"id": z["id"], "kuerzel": z["kuerzel"], "name": z["name"]} for z in zeilen if z["rolle"] == r] for r in ROLLEN}


def _klasse_daten(con, zeile, rolle):
    lk = _lehrkraefte(con, zeile["id"])
    anzahl = con.execute("SELECT COUNT(*) FROM schueler WHERE klasse_id = ? AND aktiv = 1", (zeile["id"],)).fetchone()[0]
    return {"id": zeile["id"], "name": zeile["name"], "schuljahr": zeile["schuljahr"], "moodle_kurs": zeile["moodle_kurs"],
            "einschaetzer": zeile["einschaetzer"], "archiviert": bool(zeile["archiviert"]), "rolle": rolle,
            "team": lk["team"], "einsicht": lk["einsicht"], "anzahl_schueler": anzahl}


# --- Klassen ---

def liste(con, konto, archiv=False):
    if konto["rolle"] == "admin":
        zeilen = con.execute("SELECT * FROM klasse WHERE archiviert = ? ORDER BY schuljahr DESC, name", (1 if archiv else 0,))
    else:
        zeilen = con.execute("SELECT k.* FROM klasse k JOIN klasse_lehrkraft kl ON kl.klasse_id = k.id "
                             "WHERE kl.lehrkraft_id = ? AND k.archiviert = ? ORDER BY k.schuljahr DESC, k.name",
                             (konto["id"], 1 if archiv else 0))
    return [_klasse_daten(con, z, zugriff(con, z["id"], konto)) for z in zeilen.fetchall()]


def anlegen(con, konto, name, schuljahr="", moodle_kurs=""):
    name = _text(name, "Name der Klasse", 2, 40)
    schuljahr = _text(schuljahr, "Schuljahr", 0, 12)
    moodle_kurs = _text(moodle_kurs, "Moodle-Kurs", 0, 80)
    cur = con.execute("INSERT INTO klasse (name, schuljahr, moodle_kurs, erstellt) VALUES (?, ?, ?, ?)",
                      (name, schuljahr, moodle_kurs, db.jetzt()))
    kid = cur.lastrowid
    con.execute("INSERT INTO klasse_lehrkraft (klasse_id, lehrkraft_id, rolle) VALUES (?, ?, 'team')", (kid, konto["id"]))
    db.ereignis(con, kid, None, "lehrkraft", konto["kuerzel"], "klasse_angelegt", name=name)
    return holen(con, konto, kid)


def aendern(con, konto, klasse_id, daten):
    pruefen(con, klasse_id, konto, "aendern")
    felder = {}
    if "name" in daten:
        felder["name"] = _text(daten["name"], "Name der Klasse", 2, 40)
    if "schuljahr" in daten:
        felder["schuljahr"] = _text(daten["schuljahr"], "Schuljahr", 0, 12)
    if "moodle_kurs" in daten:
        felder["moodle_kurs"] = _text(daten["moodle_kurs"], "Moodle-Kurs", 0, 80)
    if "einschaetzer" in daten:
        if daten["einschaetzer"] not in EINSCHAETZER:
            raise KlassenFehler("Unbekannte Darstellung.")
        felder["einschaetzer"] = daten["einschaetzer"]
    if "archiviert" in daten:
        felder["archiviert"] = 1 if daten["archiviert"] else 0
    for spalte, wert in felder.items():
        con.execute("UPDATE klasse SET %s = ? WHERE id = ?" % spalte, (wert, klasse_id))
    if felder:
        db.ereignis(con, klasse_id, None, "lehrkraft", konto["kuerzel"], "klasse_geaendert", **felder)
    return holen(con, konto, klasse_id)


def lehrkraft_setzen(con, konto, klasse_id, lehrkraft_id, rolle):
    """rolle: team | einsicht | None (entfernen). Eine Klasse behaelt immer mindestens eine Lehrkraft im Team."""
    pruefen(con, klasse_id, konto, "zuordnen")
    l = con.execute("SELECT id, kuerzel, name, gesperrt FROM lehrkraft WHERE id = ?", (lehrkraft_id,)).fetchone()
    if l is None:
        raise KlassenFehler("Dieses Konto gibt es nicht.")
    if rolle is not None and rolle not in ROLLEN:
        raise KlassenFehler("Unbekannte Rolle.")
    alt = con.execute("SELECT rolle FROM klasse_lehrkraft WHERE klasse_id = ? AND lehrkraft_id = ?",
                      (klasse_id, lehrkraft_id)).fetchone()
    if alt and alt["rolle"] == "team" and rolle != "team":
        team = con.execute("SELECT COUNT(*) FROM klasse_lehrkraft WHERE klasse_id = ? AND rolle = 'team'", (klasse_id,)).fetchone()[0]
        if team <= 1:
            raise KlassenFehler("Die Klasse braucht mindestens eine Lehrkraft im Team.")
    if rolle is None:
        con.execute("DELETE FROM klasse_lehrkraft WHERE klasse_id = ? AND lehrkraft_id = ?", (klasse_id, lehrkraft_id))
    else:
        con.execute("INSERT INTO klasse_lehrkraft (klasse_id, lehrkraft_id, rolle) VALUES (?, ?, ?) "
                    "ON CONFLICT (klasse_id, lehrkraft_id) DO UPDATE SET rolle = excluded.rolle", (klasse_id, lehrkraft_id, rolle))
    db.ereignis(con, klasse_id, None, "lehrkraft", konto["kuerzel"], "lehrkraft_zugeordnet", kuerzel=l["kuerzel"], rolle=rolle)


def holen(con, konto, klasse_id):
    zeile = _klasse(con, klasse_id)
    rolle = zugriff(con, klasse_id, konto)
    if rolle is None:
        raise KeinZugriff("Diese Klasse gehört nicht zu Ihren Klassen.")
    daten = _klasse_daten(con, zeile, rolle)
    if rolle in ("team", "einsicht"):
        daten["schueler"] = [_schueler_daten(z, mit_code=rolle == "team") for z in con.execute(
            "SELECT * FROM schueler WHERE klasse_id = ? ORDER BY aktiv DESC, nachname, vorname", (klasse_id,))]
    return daten


# --- Schueler ---

def _schueler_daten(zeile, mit_code):
    d = {"id": zeile["id"], "vorname": zeile["vorname"], "nachname": zeile["nachname"], "aktiv": bool(zeile["aktiv"])}
    if mit_code:
        d["code"] = code_anzeigen(zeile["code"])
    return d


def _schueler(con, klasse_id, schueler_id):
    zeile = con.execute("SELECT * FROM schueler WHERE id = ? AND klasse_id = ?", (schueler_id, klasse_id)).fetchone()
    if zeile is None:
        raise KlassenFehler("Diesen Schüler gibt es in der Klasse nicht.")
    return zeile


def schueler_einfuegen(con, klasse_id, vorname, nachname):
    vorname = _text(vorname, "Vorname", 1, 60)
    nachname = _text(nachname, "Nachname", 1, 60)
    cur = con.execute("INSERT INTO schueler (klasse_id, vorname, nachname, code, erstellt) VALUES (?, ?, ?, ?, ?)",
                      (klasse_id, vorname, nachname, neuer_code(con), db.jetzt()))
    return cur.lastrowid


def schueler_anlegen(con, konto, klasse_id, vorname, nachname):
    pruefen(con, klasse_id, konto, "aendern")
    sid = schueler_einfuegen(con, klasse_id, vorname, nachname)
    db.ereignis(con, klasse_id, sid, "lehrkraft", konto["kuerzel"], "schueler_angelegt", name="%s %s" % (vorname, nachname))
    return _schueler_daten(_schueler(con, klasse_id, sid), mit_code=True)


def schueler_aendern(con, konto, klasse_id, schueler_id, daten):
    pruefen(con, klasse_id, konto, "aendern")
    s = _schueler(con, klasse_id, schueler_id)
    name = "%s %s" % (s["vorname"], s["nachname"])
    if "vorname" in daten or "nachname" in daten:
        vorname = _text(daten.get("vorname", s["vorname"]), "Vorname", 1, 60)
        nachname = _text(daten.get("nachname", s["nachname"]), "Nachname", 1, 60)
        con.execute("UPDATE schueler SET vorname = ?, nachname = ? WHERE id = ?", (vorname, nachname, schueler_id))
        db.ereignis(con, klasse_id, schueler_id, "lehrkraft", konto["kuerzel"], "schueler_umbenannt",
                    alt=name, name="%s %s" % (vorname, nachname))
    if "aktiv" in daten:
        con.execute("UPDATE schueler SET aktiv = ? WHERE id = ?", (1 if daten["aktiv"] else 0, schueler_id))
        db.ereignis(con, klasse_id, schueler_id, "lehrkraft", konto["kuerzel"],
                    "schueler_aktiv" if daten["aktiv"] else "schueler_archiviert", name=name)
    if daten.get("code_neu"):
        con.execute("UPDATE schueler SET code = ? WHERE id = ?", (neuer_code(con), schueler_id))
        db.ereignis(con, klasse_id, schueler_id, "lehrkraft", konto["kuerzel"], "code_erneuert", name=name)
    return _schueler_daten(_schueler(con, klasse_id, schueler_id), mit_code=True)


def schueler_liste(con, klasse_id, nur_aktiv=True):
    sql = "SELECT * FROM schueler WHERE klasse_id = ?" + (" AND aktiv = 1" if nur_aktiv else "") + " ORDER BY nachname, vorname"
    return con.execute(sql, (klasse_id,)).fetchall()


def per_code(con, code):
    """Schueler zum Code (aktiv, Klasse nicht archiviert) mit Klassenangaben, oder None."""
    code = code_normalisieren(code)
    if code is None:
        return None
    return con.execute("SELECT s.id, s.vorname, s.nachname, s.klasse_id, k.name AS klasse, k.einschaetzer "
                       "FROM schueler s JOIN klasse k ON k.id = s.klasse_id "
                       "WHERE s.code = ? AND s.aktiv = 1 AND k.archiviert = 0", (code,)).fetchone()
