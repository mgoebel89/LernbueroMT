"""Zweierteams.

Die Lehrkraft erlaubt im Paket-Editor "zu zweit" je Aufgabe oder fuer das ganze Paket (dann ein Partner fuer alle
Aufgaben ausser Zusatzaufgaben). Ein Schueler laedt einen Mitschueler ein, der bestaetigt; die Lehrkraft sieht alle
Teams, kann selbst Teams bilden und sie aufloesen.

Gemeinsam im Team: der Plan der Teamaufgaben (jede Aenderung gilt fuer beide), die Wahl in einer Wahlgruppe, die
Fertigmeldung (einer meldet fuer beide) und die Rueckmeldung mit der Entscheidung. Je Person: Kann-Einschaetzung,
Farbmarkierung, Empfehlungen; der Gelingensnachweis bleibt immer Einzelleistung.
Schueler sehen nur die Namen ihrer Klasse beim Einladen und den Namen ihres Partners.
"""
from . import db, klassen

BEREICHE = ("aufgabe", "paket")


class TeamFehler(Exception):
    pass


def _name(con, sid):
    z = con.execute("SELECT vorname, nachname FROM schueler WHERE id = ?", (sid,)).fetchone()
    return "%s %s" % (z[0], z[1]) if z else "?"


def _schueler(con, sid):
    return con.execute("SELECT * FROM schueler WHERE id = ?", (sid,)).fetchone()


def _bezug(con, bereich, bezug_id):
    """(paket, aufgabe oder None) mit Pruefung, ob dort zu zweit erlaubt ist."""
    if bereich == "paket":
        p = con.execute("SELECT * FROM paket WHERE id = ?", (bezug_id,)).fetchone()
        if p is None or not p["team"]:
            raise TeamFehler("Dieses Paket ist nicht für Zweierteams freigegeben.")
        return p, None
    if bereich == "aufgabe":
        a = con.execute("SELECT * FROM aufgabe WHERE id = ? AND aktiv = 1", (bezug_id,)).fetchone()
        if a is None:
            raise TeamFehler("Diese Aufgabe gibt es nicht.")
        p = con.execute("SELECT * FROM paket WHERE id = ?", (a["paket_id"],)).fetchone()
        if a["art"] == "zusatz" or not a["team"]:
            raise TeamFehler("Diese Aufgabe ist nicht für Zweierteams freigegeben.")
        if p["team"]:
            raise TeamFehler("Im Paket gilt ein Team für alle Aufgaben. Bitte das Paket-Team wählen.")
        return p, a
    raise TeamFehler("Unbekannter Bereich.")


def titel(con, bereich, bezug_id):
    if bereich == "paket":
        p = con.execute("SELECT titel FROM paket WHERE id = ?", (bezug_id,)).fetchone()
        return "ganzes Paket " + (p[0] if p else "?")
    a = con.execute("SELECT kuerzel, titel FROM aufgabe WHERE id = ?", (bezug_id,)).fetchone()
    return "%s %s" % (a[0], a[1]) if a else "?"


def _offen(con, sid, bereich, bezug_id):
    return con.execute("SELECT * FROM team WHERE bereich = ? AND bezug_id = ? AND status IN ('eingeladen', 'aktiv') AND (a_id = ? OR b_id = ?)",
                       (bereich, bezug_id, sid, sid)).fetchone()


def abgedeckte_aufgaben(con, t):
    if t["bereich"] == "aufgabe":
        return [t["bezug_id"]]
    return [z[0] for z in con.execute("SELECT id FROM aufgabe WHERE paket_id = ? AND aktiv = 1 AND art != 'zusatz'", (t["bezug_id"],))]


def partner(con, schueler_id, aufgabe_id):
    """Partner (Schuelerzeile) fuer diese Aufgabe in einem aktiven Team, sonst None."""
    a = con.execute("SELECT a.id, a.paket_id, a.art FROM aufgabe a WHERE a.id = ?", (aufgabe_id,)).fetchone()
    if a is None or a["art"] == "zusatz":
        return None
    t = con.execute("SELECT * FROM team WHERE status = 'aktiv' AND (a_id = ? OR b_id = ?) AND "
                    "((bereich = 'aufgabe' AND bezug_id = ?) OR (bereich = 'paket' AND bezug_id = ?)) ORDER BY id DESC LIMIT 1",
                    (schueler_id, schueler_id, a["id"], a["paket_id"])).fetchone()
    if t is None:
        return None
    s = _schueler(con, t["b_id"] if t["a_id"] == schueler_id else t["a_id"])
    return s if s is not None and s["aktiv"] else None


def _status_meldung(con, sid, aufgabe_id):
    z = con.execute("SELECT status FROM meldung WHERE schueler_id = ? AND aufgabe_id = ? AND status != 'zurueckgezogen' ORDER BY id DESC LIMIT 1",
                    (sid, aufgabe_id)).fetchone()
    return z[0] if z else None


def _pruefen_paar(con, klasse_id, a_id, b_id, bereich, bezug_id):
    if a_id == b_id:
        raise TeamFehler("Bitte einen anderen Schüler wählen.")
    for sid in (a_id, b_id):
        s = _schueler(con, sid)
        if s is None or s["klasse_id"] != klasse_id or not s["aktiv"]:
            raise TeamFehler("Diesen Schüler gibt es in der Klasse nicht.")
        t = _offen(con, sid, bereich, bezug_id)
        if t:
            raise TeamFehler("%s ist dafür schon in einem Team oder eingeladen." % _name(con, sid))
    if bereich == "aufgabe":
        for sid in (a_id, b_id):
            if _status_meldung(con, sid, bezug_id) in ("offen", "angenommen"):
                raise TeamFehler("%s hat die Aufgabe schon fertig gemeldet." % _name(con, sid))


def _log(con, t, art, wer_art, wer, **daten):
    for sid, anderer in ((t["a_id"], t["b_id"]), (t["b_id"], t["a_id"])):
        db.ereignis(con, t["klasse_id"], sid, wer_art, wer, art, team_id=t["id"], bereich=t["bereich"], bezug=titel(con, t["bereich"], t["bezug_id"]),
                    partner=_name(con, anderer), **daten)


def _aktivieren(con, t, heute):
    """Gemeinsamer Stand: Wahl angleichen (die des Einladenden zaehlt), Plaene der Teamaufgaben zusammenfuehren."""
    from . import lernplan
    a, b = _schueler(con, t["a_id"]), _schueler(con, t["b_id"])
    ids = abgedeckte_aufgaben(con, t)
    for aid in ids:
        x = con.execute("SELECT * FROM aufgabe WHERE id = ?", (aid,)).fetchone()
        if x["art"] != "wahl":
            continue
        hat = {sid: bool(con.execute("SELECT 1 FROM wahl WHERE schueler_id = ? AND aufgabe_id = ?", (sid, aid)).fetchone()) for sid in (a["id"], b["id"])}
        quelle, ziel = (a, b) if hat[a["id"]] else (b, a) if hat[b["id"]] else (None, None)
        if quelle is not None and not hat[ziel["id"]]:
            try:
                lernplan.waehlen(con, ziel, aid, True, heute, spiegeln=False)
            except lernplan.PlanFehler:
                pass
    for aid in ids:
        plaene = {sid: {z[0] for z in con.execute("SELECT datum FROM plan WHERE schueler_id = ? AND aufgabe_id = ? AND datum >= ?",
                                                    (sid, aid, heute.isoformat()))} for sid in (a["id"], b["id"])}
        for s, fehlt in ((a, plaene[b["id"]] - plaene[a["id"]]), (b, plaene[a["id"]] - plaene[b["id"]])):
            if fehlt:
                try:
                    lernplan.planen(con, s, aid, hinzu=sorted(fehlt), grund="team", heute=heute, spiegeln=False)
                except lernplan.PlanFehler:
                    pass


# --- Schueler ---

def mitschueler(con, schueler):
    return [{"id": z["id"], "name": "%s %s" % (z["vorname"], z["nachname"])} for z in con.execute(
        "SELECT * FROM schueler WHERE klasse_id = ? AND aktiv = 1 AND id != ? ORDER BY vorname, nachname", (schueler["klasse_id"], schueler["id"]))]


def einladen(con, schueler, bereich, bezug_id, partner_id, heute=None):
    heute = heute or db.heute()
    if bereich not in BEREICHE:
        raise TeamFehler("Unbekannter Bereich.")
    p, a = _bezug(con, bereich, bezug_id)
    if p["klasse_id"] != schueler["klasse_id"] or not p["freigabe"] or p["freigabe"] > heute.isoformat() or p["archiviert"]:
        raise TeamFehler("Das gibt es in deinem Plan nicht.")
    if a is not None and a["art"] == "wahl" and not con.execute("SELECT 1 FROM wahl WHERE schueler_id = ? AND aufgabe_id = ?",
                                                                 (schueler["id"], a["id"])).fetchone():
        raise TeamFehler("Wähle die Aufgabe zuerst.")
    _pruefen_paar(con, schueler["klasse_id"], schueler["id"], partner_id, bereich, bezug_id)
    tid = con.execute("INSERT INTO team (klasse_id, bereich, bezug_id, a_id, b_id, status, erstellt) VALUES (?, ?, ?, ?, ?, 'eingeladen', ?)",
                      (schueler["klasse_id"], bereich, bezug_id, schueler["id"], partner_id, db.jetzt())).lastrowid
    _log(con, con.execute("SELECT * FROM team WHERE id = ?", (tid,)).fetchone(), "team_eingeladen", "schueler", "Schüler")
    return tid


def antworten(con, schueler, team_id, annehmen, heute=None):
    """Eingeladener: annehmen oder ablehnen. Einladender: (annehmen=False) die Einladung zurueckziehen."""
    heute = heute or db.heute()
    t = con.execute("SELECT * FROM team WHERE id = ? AND status = 'eingeladen'", (team_id,)).fetchone()
    if t is None or schueler["id"] not in (t["a_id"], t["b_id"]):
        raise TeamFehler("Diese Einladung gibt es nicht (mehr).")
    if annehmen:
        if schueler["id"] != t["b_id"]:
            raise TeamFehler("Annehmen kann nur der Eingeladene.")
        _bezug(con, t["bereich"], t["bezug_id"])
        con.execute("UPDATE team SET status = 'aktiv', bestaetigt = ? WHERE id = ?", (db.jetzt(), team_id))
        t = con.execute("SELECT * FROM team WHERE id = ?", (team_id,)).fetchone()
        _aktivieren(con, t, heute)
        _log(con, t, "team_aktiv", "schueler", "Schüler")
    else:
        con.execute("UPDATE team SET status = 'aufgeloest', ende = ?, ende_von = ? WHERE id = ?",
                    (db.jetzt(), "abgelehnt" if schueler["id"] == t["b_id"] else "zurueckgezogen", team_id))
        _log(con, t, "team_abgelehnt" if schueler["id"] == t["b_id"] else "team_zurueck", "schueler", "Schüler")


def _team_daten(con, t, sicht_id=None):
    d = {"id": t["id"], "bereich": t["bereich"], "bezug_id": t["bezug_id"], "titel": titel(con, t["bereich"], t["bezug_id"]),
         "status": t["status"], "erstellt": t["erstellt"], "bestaetigt": t["bestaetigt"],
         "a": {"id": t["a_id"], "name": _name(con, t["a_id"])}, "b": {"id": t["b_id"], "name": _name(con, t["b_id"])}}
    if sicht_id is not None:
        anderer = t["b_id"] if t["a_id"] == sicht_id else t["a_id"]
        d.update(partner=_name(con, anderer), eingeladen_von_mir=t["a_id"] == sicht_id)
    return d


def stand_schueler(con, schueler):
    """Teams und offene Einladungen eines Schuelers: {aufgabe: {id: team}, paket: {id: team}, einladungen: [an mich]}."""
    aus = {"aufgabe": {}, "paket": {}, "einladungen": []}
    for t in con.execute("SELECT * FROM team WHERE status IN ('eingeladen', 'aktiv') AND (a_id = ? OR b_id = ?) ORDER BY id",
                         (schueler["id"], schueler["id"])).fetchall():
        d = _team_daten(con, t, schueler["id"])
        aus[t["bereich"]][t["bezug_id"]] = d
        if t["status"] == "eingeladen" and t["b_id"] == schueler["id"]:
            aus["einladungen"].append(d)
    return aus


# --- Lehrkraft ---

def liste_klasse(con, konto, klasse_id, paket_id=None):
    klassen.pruefen(con, klasse_id, konto, "lesen")
    teams = []
    for t in con.execute("SELECT * FROM team WHERE klasse_id = ? AND status IN ('eingeladen', 'aktiv') ORDER BY id", (klasse_id,)).fetchall():
        if paket_id is not None:
            pid = t["bezug_id"] if t["bereich"] == "paket" else (con.execute("SELECT paket_id FROM aufgabe WHERE id = ?", (t["bezug_id"],)).fetchone() or [None])[0]
            if pid != paket_id:
                continue
        teams.append(_team_daten(con, t))
    moeglich = []
    pakete = con.execute("SELECT * FROM paket WHERE klasse_id = ? AND archiviert = 0" + (" AND id = ?" if paket_id else ""),
                         (klasse_id, paket_id) if paket_id else (klasse_id,)).fetchall()
    for p in pakete:
        if p["team"]:
            moeglich.append({"bereich": "paket", "bezug_id": p["id"], "titel": "ganzes Paket " + p["titel"]})
        else:
            moeglich += [{"bereich": "aufgabe", "bezug_id": a["id"], "titel": "%s %s" % (a["kuerzel"], a["titel"])} for a in con.execute(
                "SELECT * FROM aufgabe WHERE paket_id = ? AND aktiv = 1 AND team = 1 AND art != 'zusatz' ORDER BY pos", (p["id"],))]
    schueler = [{"id": z["id"], "name": "%s %s" % (z["vorname"], z["nachname"])} for z in con.execute(
        "SELECT * FROM schueler WHERE klasse_id = ? AND aktiv = 1 ORDER BY nachname, vorname", (klasse_id,))]
    return {"teams": teams, "moeglich": moeglich, "schueler": schueler, "darf": klassen.zugriff(con, klasse_id, konto) == "team"}


def bilden(con, konto, klasse_id, bereich, bezug_id, a_id, b_id, heute=None):
    """Die Lehrkraft bildet ein Team (sofort aktiv)."""
    heute = heute or db.heute()
    klassen.pruefen(con, klasse_id, konto, "aendern")
    if bereich not in BEREICHE:
        raise TeamFehler("Unbekannter Bereich.")
    p, _ = _bezug(con, bereich, bezug_id)
    if p["klasse_id"] != klasse_id:
        raise TeamFehler("Das gehört nicht zu dieser Klasse.")
    _pruefen_paar(con, klasse_id, a_id, b_id, bereich, bezug_id)
    jetzt = db.jetzt()
    tid = con.execute("INSERT INTO team (klasse_id, bereich, bezug_id, a_id, b_id, status, erstellt, bestaetigt) VALUES (?, ?, ?, ?, ?, 'aktiv', ?, ?)",
                      (klasse_id, bereich, bezug_id, a_id, b_id, jetzt, jetzt)).lastrowid
    t = con.execute("SELECT * FROM team WHERE id = ?", (tid,)).fetchone()
    _aktivieren(con, t, heute)
    _log(con, t, "team_gebildet", "lehrkraft", konto["kuerzel"])
    return tid


def aufloesen(con, konto, team_id):
    t = con.execute("SELECT * FROM team WHERE id = ? AND status IN ('eingeladen', 'aktiv')", (team_id,)).fetchone()
    if t is None:
        raise TeamFehler("Dieses Team gibt es nicht (mehr).")
    klassen.pruefen(con, t["klasse_id"], konto, "aendern")
    _beenden(con, t, "lehrkraft:" + konto["kuerzel"])
    _log(con, t, "team_aufgeloest", "lehrkraft", konto["kuerzel"])


def _beenden(con, t, von):
    con.execute("UPDATE team SET status = 'aufgeloest', ende = ?, ende_von = ? WHERE id = ?", (db.jetzt(), von, t["id"]))


def bei_abwahl(con, schueler, aufgabe_id):
    """Wahlaufgabe abgewaehlt: ein Team genau fuer diese Aufgabe endet."""
    t = _offen(con, schueler["id"], "aufgabe", aufgabe_id)
    if t is not None:
        _beenden(con, t, "abgewaehlt")
        _log(con, t, "team_aufgeloest", "schueler", "Schüler", grund="abgewählt")


def matrix_hinweise(con, klasse_id, paket_id):
    """{schueler_id: ["P2 mit Jonas Weber", ...]} fuer die aktiven Teams eines Pakets."""
    aus = {}
    for t in con.execute("SELECT * FROM team WHERE klasse_id = ? AND status = 'aktiv'", (klasse_id,)).fetchall():
        if t["bereich"] == "paket":
            if t["bezug_id"] != paket_id:
                continue
            was = "Paket"
        else:
            a = con.execute("SELECT kuerzel, paket_id FROM aufgabe WHERE id = ?", (t["bezug_id"],)).fetchone()
            if a is None or a["paket_id"] != paket_id:
                continue
            was = a["kuerzel"]
        for sid, anderer in ((t["a_id"], t["b_id"]), (t["b_id"], t["a_id"])):
            aus.setdefault(sid, []).append("%s mit %s" % (was, _name(con, anderer)))
    return aus
