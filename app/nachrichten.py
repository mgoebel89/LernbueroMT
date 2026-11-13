"""Nachrichten (Stufe G4): Verlaeufe zwischen Lehrkraeften und einem Lernteam oder einem einzelnen Schueler.

  Teamverlauf      alle aktiven Mitglieder lesen und antworten, alle Lehrkraefte der Klasse lesen mit
  Einzelverlauf    nur der Schueler und die Lehrkraefte der Klasse
Schueler schreiben einander nicht direkt. Schreiben duerfen Lehrkraefte im Team der Klasse (Einsicht liest nur).
Gelesen-Stand je Verlauf und Leser: die hoechste gelesene Nachrichten-id (Tabelle gelesen).
"""
from . import db, klassen, teams

MAX_TEXT = 2000


class NachrichtFehler(Exception):
    pass


def _text(wert):
    text = str(wert or "").replace("\r\n", "\n").strip()
    if not text:
        raise NachrichtFehler("Die Nachricht ist leer.")
    if len(text) > MAX_TEXT:
        raise NachrichtFehler("Die Nachricht ist zu lang (höchstens %d Zeichen)." % MAX_TEXT)
    return text


def verlauf_schluessel(team_id=None, schueler_id=None):
    return "t%d" % team_id if team_id else "s%d" % schueler_id


def _gelesen_setzen(con, verlauf, leser):
    hoechste = con.execute("SELECT MAX(id) FROM nachricht WHERE %s = ?" % ("team_id" if verlauf[0] == "t" else "schueler_id"),
                           (int(verlauf[1:]),)).fetchone()[0] or 0
    con.execute("INSERT INTO gelesen (verlauf, leser, zeit) VALUES (?, ?, ?) ON CONFLICT (verlauf, leser) DO UPDATE SET zeit = excluded.zeit",
                (verlauf, leser, str(hoechste)))


def _gelesen_bis(con, verlauf, leser):
    z = con.execute("SELECT zeit FROM gelesen WHERE verlauf = ? AND leser = ?", (verlauf, leser)).fetchone()
    try:
        return int(z[0]) if z else 0
    except ValueError:
        return 0


def _nachrichten(con, team_id=None, schueler_id=None, grenze=200):
    spalte, wert = ("team_id", team_id) if team_id else ("schueler_id", schueler_id)
    zeilen = con.execute("SELECT n.*, l.name AS lk_name, s.vorname, s.nachname FROM nachricht n LEFT JOIN lehrkraft l ON l.id = n.von_lehrkraft "
                         "LEFT JOIN schueler s ON s.id = n.von_schueler WHERE n.%s = ? ORDER BY n.id DESC LIMIT ?" % spalte, (wert, grenze)).fetchall()
    return [{"id": z["id"], "zeit": z["zeit"], "text": z["text"], "von_art": "lehrkraft" if z["von_lehrkraft"] else "schueler",
             "von_id": z["von_lehrkraft"] or z["von_schueler"], "von": z["lk_name"] or "%s %s" % (z["vorname"], z["nachname"])}
            for z in reversed(zeilen)]


def _team_aktiv_mitglied(con, schueler_id, team_id):
    return con.execute("SELECT 1 FROM lernteam t JOIN lernteam_mitglied m ON m.team_id = t.id WHERE t.id = ? AND t.status = 'aktiv' "
                       "AND m.schueler_id = ? AND m.status = 'aktiv'", (team_id, schueler_id)).fetchone() is not None


# --- Lehrkraft ---

def _ziel_lk(con, konto, team_id=None, schueler_id=None, recht="lesen"):
    if team_id:
        t = con.execute("SELECT * FROM lernteam WHERE id = ?", (team_id,)).fetchone()
        if t is None:
            raise NachrichtFehler("Dieses Team gibt es nicht.")
        rolle = klassen.pruefen(con, t["klasse_id"], konto, recht)
        return t["klasse_id"], rolle, t
    s = con.execute("SELECT * FROM schueler WHERE id = ?", (schueler_id,)).fetchone()
    if s is None:
        raise NachrichtFehler("Diesen Schüler gibt es nicht.")
    rolle = klassen.pruefen(con, s["klasse_id"], konto, recht)
    return s["klasse_id"], rolle, s


def senden_lk(con, konto, text, team_id=None, schueler_id=None):
    if not team_id and not schueler_id:
        raise NachrichtFehler("Bitte ein Team oder einen Schüler wählen.")
    klasse_id, _, ziel = _ziel_lk(con, konto, team_id, schueler_id, "aendern")
    if team_id and ziel["status"] != "aktiv":
        raise NachrichtFehler("Dieses Team ist aufgelöst.")
    nid = con.execute("INSERT INTO nachricht (klasse_id, team_id, schueler_id, von_lehrkraft, text, zeit) VALUES (?, ?, ?, ?, ?, ?)",
                      (klasse_id, team_id or None, None if team_id else schueler_id, konto["id"], _text(text), db.jetzt())).lastrowid
    _gelesen_setzen(con, verlauf_schluessel(team_id, schueler_id), "l%d" % konto["id"])
    return nid


def verlauf_lk(con, konto, team_id=None, schueler_id=None):
    klasse_id, rolle, ziel = _ziel_lk(con, konto, team_id, schueler_id)
    if team_id:
        kopf = {"art": "team", "team": teams.team_daten(con, ziel, lehrkraft=True), "titel": teams.team_daten(con, ziel)["name"],
                "unter": teams.titel(con, ziel["bereich"], ziel["bezug_id"]), "aktiv": ziel["status"] == "aktiv"}
    else:
        kopf = {"art": "schueler", "schueler_id": ziel["id"], "titel": "%s %s" % (ziel["vorname"], ziel["nachname"]), "unter": "nur dieser Schüler",
                "aktiv": bool(ziel["aktiv"])}
    _gelesen_setzen(con, verlauf_schluessel(team_id, schueler_id), "l%d" % konto["id"])
    return dict(kopf, klasse_id=klasse_id, darf=rolle == "team", team_id=team_id, nachrichten=_nachrichten(con, team_id, schueler_id))


def _sichtbare_klassen(con, konto):
    return [z[0] for z in con.execute("SELECT kl.klasse_id FROM klasse_lehrkraft kl JOIN klasse k ON k.id = kl.klasse_id "
                                      "WHERE kl.lehrkraft_id = ? AND k.archiviert = 0", (konto["id"],))]


def liste_lk(con, konto):
    """Alle Verlaeufe mit mindestens einer Nachricht in den Klassen der Lehrkraft, neueste zuerst."""
    ids = _sichtbare_klassen(con, konto)
    if not ids:
        return []
    aus = []
    platz = ",".join("?" * len(ids))
    for z in con.execute("SELECT team_id, schueler_id, MAX(id) AS letzte, klasse_id FROM nachricht WHERE klasse_id IN (%s) "
                         "GROUP BY team_id, schueler_id ORDER BY letzte DESC" % platz, ids).fetchall():
        v = verlauf_schluessel(z["team_id"], z["schueler_id"])
        bis = _gelesen_bis(con, v, "l%d" % konto["id"])
        spalte, wert = ("team_id", z["team_id"]) if z["team_id"] else ("schueler_id", z["schueler_id"])
        ungelesen = con.execute("SELECT COUNT(*) FROM nachricht WHERE %s = ? AND id > ? AND von_schueler IS NOT NULL" % spalte, (wert, bis)).fetchone()[0]
        n = con.execute("SELECT n.*, l.name AS lk_name, s.vorname FROM nachricht n LEFT JOIN lehrkraft l ON l.id = n.von_lehrkraft "
                        "LEFT JOIN schueler s ON s.id = n.von_schueler WHERE n.id = ?", (z["letzte"],)).fetchone()
        k = con.execute("SELECT name FROM klasse WHERE id = ?", (z["klasse_id"],)).fetchone()
        if z["team_id"]:
            t = con.execute("SELECT * FROM lernteam WHERE id = ?", (z["team_id"],)).fetchone()
            d = teams.team_daten(con, t)
            titel, unter = d["name"], d["titel"] + " · " + ", ".join(m["vorname"] for m in d["mitglieder"] if m["status"] == "aktiv")
        else:
            s = con.execute("SELECT vorname, nachname FROM schueler WHERE id = ?", (z["schueler_id"],)).fetchone()
            titel, unter = "%s %s" % (s[0], s[1]), "nur dieser Schüler"
        aus.append({"team_id": z["team_id"], "schueler_id": z["schueler_id"], "klasse_id": z["klasse_id"], "klasse": k[0], "titel": titel, "unter": unter,
                    "letzte": {"zeit": n["zeit"], "text": n["text"][:120], "von": n["lk_name"] or n["vorname"]}, "ungelesen": ungelesen})
    return aus


def ungelesen_lk(con, konto):
    return sum(v["ungelesen"] for v in liste_lk(con, konto))


# --- Schueler ---

def senden_schueler(con, schueler, text, team_id=None):
    if team_id:
        if not _team_aktiv_mitglied(con, schueler["id"], team_id):
            raise NachrichtFehler("In diesem Team bist du nicht.")
        nid = con.execute("INSERT INTO nachricht (klasse_id, team_id, von_schueler, text, zeit) VALUES (?, ?, ?, ?, ?)",
                          (schueler["klasse_id"], team_id, schueler["id"], _text(text), db.jetzt())).lastrowid
    else:
        nid = con.execute("INSERT INTO nachricht (klasse_id, schueler_id, von_schueler, text, zeit) VALUES (?, ?, ?, ?, ?)",
                          (schueler["klasse_id"], schueler["id"], schueler["id"], _text(text), db.jetzt())).lastrowid
    _gelesen_setzen(con, verlauf_schluessel(team_id, None if team_id else schueler["id"]), "s%d" % schueler["id"])
    return nid


def _verlaeufe_schueler(con, schueler):
    """[(team_id oder None, titel, unter)]: der eigene Verlauf und die aktiven Teams."""
    aus = [(None, "Du und deine Lehrkraft", "nur du und deine Lehrkräfte")]
    for t in con.execute("SELECT t.* FROM lernteam t JOIN lernteam_mitglied m ON m.team_id = t.id WHERE t.status = 'aktiv' AND m.schueler_id = ? "
                         "AND m.status = 'aktiv' ORDER BY t.id", (schueler["id"],)).fetchall():
        d = teams.team_daten(con, t, schueler["id"])
        aus.append((t["id"], d["name"] + " · " + d["titel"], "mit " + (d["partner"] or "niemandem")))
    return aus


def fuer_schueler(con, schueler):
    verlaeufe = []
    for team_id, titel, unter in _verlaeufe_schueler(con, schueler):
        v = verlauf_schluessel(team_id, schueler["id"])
        bis = _gelesen_bis(con, v, "s%d" % schueler["id"])
        nachrichten = _nachrichten(con, team_id, None if team_id else schueler["id"])
        for n in nachrichten:
            n["ich"] = n["von_art"] == "schueler" and n["von_id"] == schueler["id"]
        verlaeufe.append({"team_id": team_id, "titel": titel, "unter": unter, "nachrichten": nachrichten,
                          "ungelesen": sum(1 for n in nachrichten if n["id"] > bis and not n["ich"])})
    return {"verlaeufe": verlaeufe, "ungelesen": sum(v["ungelesen"] for v in verlaeufe)}


def ungelesen_schueler(con, schueler):
    zahl = 0
    for team_id, _, _ in _verlaeufe_schueler(con, schueler):
        v = verlauf_schluessel(team_id, schueler["id"])
        spalte, wert = ("team_id", team_id) if team_id else ("schueler_id", schueler["id"])
        zahl += con.execute("SELECT COUNT(*) FROM nachricht WHERE %s = ? AND id > ? AND (von_schueler IS NULL OR von_schueler != ?)" % spalte,
                            (wert, _gelesen_bis(con, v, "s%d" % schueler["id"]), schueler["id"])).fetchone()[0]
    return zahl


def gelesen_schueler(con, schueler):
    for team_id, _, _ in _verlaeufe_schueler(con, schueler):
        _gelesen_setzen(con, verlauf_schluessel(team_id, schueler["id"]), "s%d" % schueler["id"])
