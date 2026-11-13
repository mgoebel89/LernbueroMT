"""Lernteams (Stufe G, ersetzt die Zweierteams aus 0.6).

Team-Modus je Paket, Wahlgruppe oder Aufgabe (eine Einstellung an der Aufgabe gilt vor der Gruppe, die vor dem Paket):
  einzeln   jeder arbeitet allein (Vorgabe)
  frei      Schueler duerfen sich zusammentun, muessen aber nicht
  pflicht   Schueler finden sich bis zu einem Stichtag; wer dann allein ist, teilt die Lehrkraft zu
  vorgabe   die Lehrkraft setzt die Teams
  stamm     es gelten die Stammteams der Klasse (ueber mehrere Pakete)
Ein Lernteam gehoert zu der Ebene, an der der Modus steht (bereich paket | gruppe | aufgabe, "Einheit"), Stammteams haben
bereich 'stamm' und die Klasse als Bezug. Groesse min..max je Einheit; die Lehrkraft darf beim Zuteilen ueberschreiten.

Selbst finden (frei, pflicht): Ein Schueler gruendet ein Team "nur auf Einladung" oder "offen zum Beitreten", laedt
Mitschueler ein (jeder bestaetigt selbst) oder tritt einem offenen Team bei. Verlassen nur mit Zustimmung der Lehrkraft
(Austrittswunsch). Vorgegebene Teams und Stammteams aendert nur die Lehrkraft.

Gemeinsam: Plan und Wahl der abgedeckten Aufgaben (jede Aenderung gilt fuer alle), Fertigmeldung (einer meldet, alle
bestaetigen, app/rueckmeldung.py), der Teil "An das ganze Team" der Rueckmeldung, Nachrichtenverlauf, Teamtermin.
Je Person: Kann-Liste, Farben, eigener Teil der Rueckmeldung, Empfehlungen, Gelingensnachweis.
Schueler sehen die Namen ihrer Klasse beim Finden und von offenen Teams die Mitglieder, sonst nur ihr eigenes Team.
"""
import datetime

from . import db, klassen, unterrichtstage as ut

MODI = ("einzeln", "frei", "pflicht", "vorgabe", "stamm")
SELBST = ("frei", "pflicht")
MODUS_TEXT = {"einzeln": "einzeln", "frei": "Team frei", "pflicht": "Team Pflicht", "vorgabe": "vorgegebene Teams", "stamm": "Stammteams"}
MAX_GROESSE = 8
EINZELN = {"modus": "einzeln", "bereich": None, "bezug_id": None, "min": None, "max": None, "stichtag": None}
TAG = datetime.timedelta(days=1)


class TeamFehler(Exception):
    pass


def _name(con, sid):
    z = con.execute("SELECT vorname, nachname FROM schueler WHERE id = ?", (sid,)).fetchone()
    return "%s %s" % (z[0], z[1]) if z else "?"


def _schueler(con, sid):
    return con.execute("SELECT * FROM schueler WHERE id = ?", (sid,)).fetchone()


def schluessel(bereich, bezug_id):
    return "%s:%s" % (bereich, bezug_id)


# --- Einstellung im Paket-Editor ---

def einstellung_pruefen(d, ebene):
    """Werte fuer team_modus, team_min, team_max, team_stichtag aus d. Leer/None = wie uebergeordnet (beim Paket: einzeln)."""
    modus = d.get("team_modus") or None
    if modus is not None and modus not in MODI:
        raise TeamFehler("Unbekannter Team-Modus.")
    if modus in (None, "einzeln", "stamm"):
        return {"team_modus": modus if (modus or ebene != "paket") else None, "team_min": None, "team_max": None, "team_stichtag": None}

    def zahl(name, vorgabe):
        wert = d.get(name)
        if wert in (None, ""):
            return vorgabe
        try:
            wert = int(wert)
        except (TypeError, ValueError):
            raise TeamFehler("Bitte die Teamgröße als Zahl angeben.")
        if not 1 <= wert <= MAX_GROESSE:
            raise TeamFehler("Teamgröße: 1 bis %d." % MAX_GROESSE)
        return wert
    mi = zahl("team_min", 2)
    ma = zahl("team_max", max(mi, 3))
    if ma < mi:
        raise TeamFehler("Die größte Teamgröße liegt unter der kleinsten.")
    stichtag = None
    if modus == "pflicht" and d.get("team_stichtag"):
        try:
            stichtag = ut.datum(d["team_stichtag"]).isoformat()
        except ut.TageFehler:
            raise TeamFehler("Ungültiger Stichtag.")
    return {"team_modus": modus, "team_min": mi, "team_max": ma, "team_stichtag": stichtag}


def konfig(z):
    """Team-Einstellung einer Zeile (paket, wahlgruppe, aufgabe) fuer die Oberflaeche, None = wie uebergeordnet."""
    if z is None or not z["team_modus"]:
        return None
    return {"modus": z["team_modus"], "min": z["team_min"], "max": z["team_max"], "stichtag": z["team_stichtag"],
            "text": MODUS_TEXT[z["team_modus"]]}


def _einheit(a, g, p, klasse_id):
    """Wirksame Einheit einer Aufgabe (Zeilen aufgabe, wahlgruppe oder None, paket)."""
    if a["art"] == "zusatz":
        return dict(EINZELN)
    for ebene, z in (("aufgabe", a), ("gruppe", g), ("paket", p)):
        if z is None or not z["team_modus"]:
            continue
        modus = z["team_modus"]
        if modus == "einzeln":
            return dict(EINZELN)
        if modus == "stamm":
            return {"modus": "stamm", "bereich": "stamm", "bezug_id": klasse_id, "min": None, "max": None, "stichtag": None}
        return {"modus": modus, "bereich": ebene, "bezug_id": z["id"], "min": z["team_min"], "max": z["team_max"], "stichtag": z["team_stichtag"]}
    return dict(EINZELN)


def einheit(con, aufgabe_id):
    a = con.execute("SELECT * FROM aufgabe WHERE id = ?", (aufgabe_id,)).fetchone()
    if a is None:
        return dict(EINZELN)
    p = con.execute("SELECT * FROM paket WHERE id = ?", (a["paket_id"],)).fetchone()
    g = con.execute("SELECT * FROM wahlgruppe WHERE id = ?", (a["wahlgruppe_id"],)).fetchone() if a["wahlgruppe_id"] else None
    return _einheit(a, g, p, p["klasse_id"])


def _stichtag_vorgabe(con, p):
    """Ohne eigenen Stichtag bei Team-Pflicht: eine Woche nach der (wirksamen) Freigabe des Pakets."""
    if not p["freigabe"]:
        return None
    return (ut.datum(p["freigabe"]) + 7 * TAG).isoformat()


def einheiten_paket(con, p):
    """{schluessel: Einheit mit titel und aufgaben} fuer alle Aufgaben des Pakets, die nicht einzeln bearbeitet werden."""
    gruppen = {g["id"]: g for g in con.execute("SELECT * FROM wahlgruppe WHERE paket_id = ? AND aktiv = 1", (p["id"],))}
    aus = {}
    for a in con.execute("SELECT * FROM aufgabe WHERE paket_id = ? AND aktiv = 1 AND art != 'zusatz' ORDER BY pos, id", (p["id"],)).fetchall():
        g = gruppen.get(a["wahlgruppe_id"])
        e = _einheit(a, g, p, p["klasse_id"])
        if e["bereich"] is None:
            continue
        k = schluessel(e["bereich"], e["bezug_id"])
        if k not in aus:
            if e["bereich"] == "paket":
                titel = "ganzes Paket " + p["titel"]
            elif e["bereich"] == "gruppe":
                titel = "Wahlgruppe %s%s" % (g["buchstabe"], " · " + g["titel"] if g["titel"] else "")
            elif e["bereich"] == "aufgabe":
                titel = "%s %s" % (a["kuerzel"], a["titel"])
            else:
                titel = "Stammteams der Klasse"
            if e["modus"] == "pflicht" and not e["stichtag"]:
                e["stichtag"] = _stichtag_vorgabe(con, p)
            aus[k] = dict(e, schluessel=k, titel=titel, paket_id=p["id"], paket=p["titel"], aufgaben=[], kuerzel=[], modus_text=MODUS_TEXT[e["modus"]])
        aus[k]["aufgaben"].append(a["id"])
        aus[k]["kuerzel"].append(a["kuerzel"] if e["bereich"] != "stamm" else "%s (%s)" % (a["kuerzel"], p["titel"]))
    return aus


def abgedeckte_aufgaben(con, t):
    """Aufgaben-ids, fuer die ein Lernteam gilt."""
    if t["bereich"] == "aufgabe":
        return [t["bezug_id"]]
    if t["bereich"] == "stamm":
        pakete = con.execute("SELECT * FROM paket WHERE klasse_id = ? AND archiviert = 0", (t["bezug_id"],)).fetchall()
    elif t["bereich"] == "gruppe":
        pakete = con.execute("SELECT p.* FROM paket p JOIN wahlgruppe g ON g.paket_id = p.id WHERE g.id = ?", (t["bezug_id"],)).fetchall()
    else:
        pakete = con.execute("SELECT * FROM paket WHERE id = ?", (t["bezug_id"],)).fetchall()
    k = schluessel(t["bereich"], t["bezug_id"])
    ids = []
    for p in pakete:
        e = einheiten_paket(con, p).get(k)
        if e:
            ids += e["aufgaben"]
    return ids


def _einheit_zeile(con, bereich, bezug_id):
    """(paket, Konfiguration der Einheit, titel); Konfiguration der Ebene selbst, nicht vererbt."""
    if bereich == "paket":
        p = con.execute("SELECT * FROM paket WHERE id = ?", (bezug_id,)).fetchone()
        if p is None:
            raise TeamFehler("Dieses Paket gibt es nicht.")
        return p, konfig(p), "ganzes Paket " + p["titel"]
    if bereich == "gruppe":
        g = con.execute("SELECT * FROM wahlgruppe WHERE id = ? AND aktiv = 1", (bezug_id,)).fetchone()
        if g is None:
            raise TeamFehler("Diese Wahlgruppe gibt es nicht.")
        p = con.execute("SELECT * FROM paket WHERE id = ?", (g["paket_id"],)).fetchone()
        return p, konfig(g), "Wahlgruppe %s%s" % (g["buchstabe"], " · " + g["titel"] if g["titel"] else "")
    if bereich == "aufgabe":
        a = con.execute("SELECT * FROM aufgabe WHERE id = ? AND aktiv = 1", (bezug_id,)).fetchone()
        if a is None:
            raise TeamFehler("Diese Aufgabe gibt es nicht.")
        p = con.execute("SELECT * FROM paket WHERE id = ?", (a["paket_id"],)).fetchone()
        return p, konfig(a) if a["art"] != "zusatz" else None, "%s %s" % (a["kuerzel"], a["titel"])
    if bereich == "stamm":
        return None, {"modus": "stamm", "min": None, "max": None, "stichtag": None, "text": MODUS_TEXT["stamm"]}, "Stammteams der Klasse"
    raise TeamFehler("Unbekannter Bereich.")


def titel(con, bereich, bezug_id):
    try:
        return _einheit_zeile(con, bereich, bezug_id)[2]
    except TeamFehler:
        return "?"


# --- Teams und Mitglieder ---

def team_von(con, schueler_id, bereich, bezug_id):
    return con.execute("SELECT t.* FROM lernteam t JOIN lernteam_mitglied m ON m.team_id = t.id WHERE t.status = 'aktiv' AND t.bereich = ? "
                       "AND t.bezug_id = ? AND m.schueler_id = ? AND m.status = 'aktiv'", (bereich, bezug_id, schueler_id)).fetchone()


def team_fuer_aufgabe(con, schueler_id, aufgabe_id):
    e = einheit(con, aufgabe_id)
    return team_von(con, schueler_id, e["bereich"], e["bezug_id"]) if e["bereich"] else None


def mitglieder(con, team_id, status=("aktiv",)):
    return con.execute("SELECT m.*, s.vorname, s.nachname, s.aktiv AS schueler_aktiv, s.klasse_id FROM lernteam_mitglied m "
                       "JOIN schueler s ON s.id = m.schueler_id WHERE m.team_id = ? AND m.status IN (%s) ORDER BY m.seit, m.rowid"
                       % ",".join("?" * len(status)), (team_id,) + tuple(status)).fetchall()


def teamkollegen(con, schueler_id, aufgabe_id):
    """Die anderen aktiven Mitglieder (Schuelerzeilen) im Team dieser Aufgabe; leer ohne Team."""
    t = team_fuer_aufgabe(con, schueler_id, aufgabe_id)
    if t is None:
        return []
    return [s for s in (_schueler(con, m["schueler_id"]) for m in mitglieder(con, t["id"]) if m["schueler_id"] != schueler_id)
            if s is not None and s["aktiv"]]


def _team(con, team_id):
    t = con.execute("SELECT * FROM lernteam WHERE id = ? AND status = 'aktiv'", (team_id,)).fetchone()
    if t is None:
        raise TeamFehler("Dieses Team gibt es nicht (mehr).")
    return t


def _mitglied(con, team_id, schueler_id):
    return con.execute("SELECT * FROM lernteam_mitglied WHERE team_id = ? AND schueler_id = ?", (team_id, schueler_id)).fetchone()


def _belegt(con, team_id, mit_einladungen=True):
    status = "('aktiv', 'eingeladen')" if mit_einladungen else "('aktiv')"
    return con.execute("SELECT COUNT(*) FROM lernteam_mitglied m JOIN schueler s ON s.id = m.schueler_id WHERE m.team_id = ? AND s.aktiv = 1 "
                       "AND m.status IN " + status, (team_id,)).fetchone()[0]


def _mitglied_setzen(con, team_id, schueler_id, status, eingeladen_von=None, grund=None):
    jetzt = db.jetzt()
    if _mitglied(con, team_id, schueler_id) is None:
        con.execute("INSERT INTO lernteam_mitglied (team_id, schueler_id, status, eingeladen_von, seit) VALUES (?, ?, ?, ?, ?)",
                    (team_id, schueler_id, status, eingeladen_von, jetzt))
    elif status == "raus":
        con.execute("UPDATE lernteam_mitglied SET status = 'raus', ende = ?, ende_grund = ?, austritt_grund = NULL, austritt_zeit = NULL "
                    "WHERE team_id = ? AND schueler_id = ?", (jetzt, grund, team_id, schueler_id))
    else:
        con.execute("UPDATE lernteam_mitglied SET status = ?, eingeladen_von = COALESCE(?, eingeladen_von), seit = ?, ende = NULL, ende_grund = NULL, "
                    "austritt_grund = NULL, austritt_zeit = NULL WHERE team_id = ? AND schueler_id = ?", (status, eingeladen_von, jetzt, team_id, schueler_id))


def _name_team(con, t):
    if t["name"]:
        return t["name"]
    m = mitglieder(con, t["id"])
    return "Team " + m[0]["vorname"] if m else "Team"


def team_daten(con, t, sicht_id=None, lehrkraft=False):
    alle = mitglieder(con, t["id"], ("aktiv", "eingeladen"))
    d = {"id": t["id"], "name": _name_team(con, t), "bereich": t["bereich"], "bezug_id": t["bezug_id"], "schluessel": schluessel(t["bereich"], t["bezug_id"]),
         "titel": titel(con, t["bereich"], t["bezug_id"]), "offen": bool(t["offen"]), "quelle": t["quelle"], "erstellt": t["erstellt"],
         "mitglieder": [{"id": m["schueler_id"], "name": "%s %s" % (m["vorname"], m["nachname"]), "vorname": m["vorname"], "status": m["status"],
                         "austritt": m["austritt_grund"] if (lehrkraft or m["schueler_id"] == sicht_id) else None,
                         "austritt_zeit": m["austritt_zeit"] if lehrkraft else None}
                        for m in alle if m["schueler_aktiv"]]}
    d["anzahl"] = sum(1 for m in d["mitglieder"] if m["status"] == "aktiv")
    if sicht_id is not None:
        ich = next((m for m in d["mitglieder"] if m["id"] == sicht_id), None)
        d["ich"] = ich["status"] if ich else None
        d["partner"] = ", ".join(m["name"] for m in d["mitglieder"] if m["id"] != sicht_id and m["status"] == "aktiv")
    return d


def _log(con, t, art, wer_art, wer, **daten):
    namen = [m for m in mitglieder(con, t["id"], ("aktiv", "eingeladen"))]
    for m in namen:
        db.ereignis(con, t["klasse_id"], m["schueler_id"], wer_art, wer, art, team_id=t["id"], bereich=t["bereich"],
                    bezug=titel(con, t["bereich"], t["bezug_id"]),
                    partner=", ".join("%s %s" % (x["vorname"], x["nachname"]) for x in namen if x["schueler_id"] != m["schueler_id"]), **daten)


def _zusammenfuehren(con, t, heute):
    """Gemeinsamer Stand fuer alle aktiven Mitglieder: dieselbe Wahl in Wahlgruppen (die des aeltesten Mitglieds zaehlt)
    und die Vereinigung der kuenftigen Plaene der abgedeckten Aufgaben, die noch niemand fertig gemeldet hat."""
    from . import lernplan
    ms = [_schueler(con, m["schueler_id"]) for m in mitglieder(con, t["id"])]
    ms = [s for s in ms if s is not None and s["aktiv"]]
    if len(ms) < 2:
        return
    ids = abgedeckte_aufgaben(con, t)
    aufgaben = {a["id"]: a for a in con.execute("SELECT * FROM aufgabe WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)} if ids else {}
    gruppen = {}
    for aid, a in aufgaben.items():
        if a["art"] == "wahl":
            gruppen.setdefault(a["wahlgruppe_id"], []).append(aid)
    for gid, aids in gruppen.items():
        gewaehlt = None
        for s in ms:
            z = con.execute("SELECT aufgabe_id FROM wahl WHERE schueler_id = ? AND aufgabe_id IN (%s) ORDER BY zeit" % ",".join("?" * len(aids)),
                            (s["id"],) + tuple(aids)).fetchone()
            if z:
                gewaehlt = z[0]
                break
        if gewaehlt is None:
            continue
        for s in ms:
            try:
                lernplan.waehlen(con, s, gewaehlt, True, heute, spiegeln=False)
            except lernplan.PlanFehler:
                pass
    for aid in aufgaben:
        if con.execute("SELECT 1 FROM meldung WHERE aufgabe_id = ? AND status IN ('offen', 'angenommen') AND schueler_id IN (%s)"
                       % ",".join("?" * len(ms)), (aid,) + tuple(s["id"] for s in ms)).fetchone():
            continue
        plaene = {s["id"]: {z[0] for z in con.execute("SELECT datum FROM plan WHERE schueler_id = ? AND aufgabe_id = ? AND datum >= ?",
                                                       (s["id"], aid, heute.isoformat()))} for s in ms}
        alle = set().union(*plaene.values())
        for s in ms:
            fehlt = alle - plaene[s["id"]]
            if fehlt:
                try:
                    lernplan.planen(con, s, aid, hinzu=sorted(fehlt), grund="team", heute=heute, spiegeln=False)
                except lernplan.PlanFehler:
                    pass


# --- Schueler ---

def _sichtbar(con, schueler, bereich, bezug_id, heute):
    """Einheit, in der sich der Schueler selbst ein Team suchen darf: (paket, konfig, titel)."""
    p, k, t = _einheit_zeile(con, bereich, bezug_id)
    if bereich == "stamm" or k is None or k["modus"] not in SELBST:
        raise TeamFehler("Hier bildet deine Lehrkraft die Teams." if k and k["modus"] in ("vorgabe", "stamm")
                         else "Diese Aufgabe bearbeitest du allein.")
    if p["klasse_id"] != schueler["klasse_id"] or not p["freigabe"] or p["freigabe"] > heute.isoformat() or p["archiviert"]:
        raise TeamFehler("Das gibt es in deinem Plan nicht.")
    if bereich == "aufgabe":
        a = con.execute("SELECT * FROM aufgabe WHERE id = ?", (bezug_id,)).fetchone()
        if a["art"] == "wahl" and not con.execute("SELECT 1 FROM wahl WHERE schueler_id = ? AND aufgabe_id = ?", (schueler["id"], bezug_id)).fetchone():
            raise TeamFehler("Wähle die Aufgabe zuerst.")
    return p, k, t


def _frei_fuer(con, sid, bereich, bezug_id, klasse_id):
    s = _schueler(con, sid)
    if s is None or s["klasse_id"] != klasse_id or not s["aktiv"]:
        raise TeamFehler("Diesen Schüler gibt es in der Klasse nicht.")
    if team_von(con, sid, bereich, bezug_id):
        raise TeamFehler("%s ist dafür schon in einem Team." % _name(con, sid))
    return s


def _einladungen_ablehnen(con, sid, bereich, bezug_id, grund):
    """Wer einem Team beitritt, lehnt die uebrigen Einladungen fuer dieselbe Einheit ab."""
    for z in con.execute("SELECT m.team_id FROM lernteam_mitglied m JOIN lernteam t ON t.id = m.team_id WHERE m.schueler_id = ? AND m.status = 'eingeladen' "
                         "AND t.bereich = ? AND t.bezug_id = ? AND t.status = 'aktiv'", (sid, bereich, bezug_id)).fetchall():
        _mitglied_setzen(con, z[0], sid, "raus", grund=grund)


def gruenden(con, schueler, bereich, bezug_id, offen=False, einladen=(), heute=None):
    heute = heute or db.heute()
    p, k, _ = _sichtbar(con, schueler, bereich, bezug_id, heute)
    if team_von(con, schueler["id"], bereich, bezug_id):
        raise TeamFehler("Du bist dafür schon in einem Team.")
    ids = []
    for x in einladen or []:
        try:
            x = int(x)
        except (TypeError, ValueError):
            raise TeamFehler("Ungültige Einladung.")
        if x != schueler["id"] and x not in ids:
            ids.append(x)
    if 1 + len(ids) > k["max"]:
        raise TeamFehler("Ein Team hat hier höchstens %d Personen." % k["max"])
    for x in ids:
        _frei_fuer(con, x, bereich, bezug_id, schueler["klasse_id"])
    tid = con.execute("INSERT INTO lernteam (klasse_id, bereich, bezug_id, offen, quelle, erstellt) VALUES (?, ?, ?, ?, 'schueler', ?)",
                      (schueler["klasse_id"], bereich, bezug_id, 1 if offen else 0, db.jetzt())).lastrowid
    _mitglied_setzen(con, tid, schueler["id"], "aktiv")
    _einladungen_ablehnen(con, schueler["id"], bereich, bezug_id, "eigenes Team")
    for x in ids:
        _mitglied_setzen(con, tid, x, "eingeladen", eingeladen_von=schueler["id"])
    t = con.execute("SELECT * FROM lernteam WHERE id = ?", (tid,)).fetchone()
    _log(con, t, "team_gegruendet", "schueler", "Schüler", offen=bool(offen))
    return tid


def einladen(con, schueler, team_id, ids, heute=None):
    heute = heute or db.heute()
    t = _team(con, team_id)
    m = _mitglied(con, team_id, schueler["id"])
    if m is None or m["status"] != "aktiv":
        raise TeamFehler("Einladen kann nur, wer im Team ist.")
    _, k, _ = _sichtbar(con, schueler, t["bereich"], t["bezug_id"], heute)
    neu = []
    for x in ids or []:
        try:
            x = int(x)
        except (TypeError, ValueError):
            raise TeamFehler("Ungültige Einladung.")
        alt = _mitglied(con, team_id, x)
        if x != schueler["id"] and x not in neu and not (alt and alt["status"] in ("aktiv", "eingeladen")):
            neu.append(x)
    if not neu:
        raise TeamFehler("Bitte jemanden zum Einladen wählen.")
    if _belegt(con, team_id) + len(neu) > k["max"]:
        raise TeamFehler("Ein Team hat hier höchstens %d Personen (mit offenen Einladungen)." % k["max"])
    for x in neu:
        _frei_fuer(con, x, t["bereich"], t["bezug_id"], t["klasse_id"])
        _mitglied_setzen(con, team_id, x, "eingeladen", eingeladen_von=schueler["id"])
    _log(con, t, "team_eingeladen", "schueler", "Schüler", eingeladen=[_name(con, x) for x in neu])


def beitreten(con, schueler, team_id, heute=None):
    heute = heute or db.heute()
    t = _team(con, team_id)
    _, k, _ = _sichtbar(con, schueler, t["bereich"], t["bezug_id"], heute)
    alt = _mitglied(con, team_id, schueler["id"])
    if not t["offen"] and not (alt and alt["status"] == "eingeladen"):
        raise TeamFehler("Diesem Team trittst du nur auf Einladung bei.")
    if team_von(con, schueler["id"], t["bereich"], t["bezug_id"]):
        raise TeamFehler("Du bist dafür schon in einem Team.")
    if _belegt(con, team_id, mit_einladungen=False) >= k["max"]:
        raise TeamFehler("Das Team ist schon voll.")
    _mitglied_setzen(con, team_id, schueler["id"], "aktiv")
    _einladungen_ablehnen(con, schueler["id"], t["bereich"], t["bezug_id"], "anderes Team")
    _zusammenfuehren(con, t, heute)
    _log(con, t, "team_beigetreten", "schueler", "Schüler", name=_name(con, schueler["id"]))


def antworten(con, schueler, team_id, annehmen, heute=None):
    """Einladung annehmen (= beitreten) oder ablehnen."""
    m = _mitglied(con, team_id, schueler["id"])
    if m is None or m["status"] != "eingeladen":
        raise TeamFehler("Diese Einladung gibt es nicht (mehr).")
    if annehmen:
        return beitreten(con, schueler, team_id, heute)
    t = _team(con, team_id)
    _mitglied_setzen(con, team_id, schueler["id"], "raus", grund="abgelehnt")
    _log(con, t, "team_abgelehnt", "schueler", "Schüler", name=_name(con, schueler["id"]))


def offen_setzen(con, schueler, team_id, offen):
    t = _team(con, team_id)
    m = _mitglied(con, team_id, schueler["id"])
    if m is None or m["status"] != "aktiv" or t["quelle"] != "schueler":
        raise TeamFehler("Das kann nur ein Mitglied eines selbst gegründeten Teams.")
    con.execute("UPDATE lernteam SET offen = ? WHERE id = ?", (1 if offen else 0, team_id))


def austritt_anfragen(con, schueler, team_id, grund):
    t = _team(con, team_id)
    m = _mitglied(con, team_id, schueler["id"])
    if m is None or m["status"] != "aktiv":
        raise TeamFehler("Du bist nicht in diesem Team.")
    _, k, _ = _einheit_zeile(con, t["bereich"], t["bezug_id"])
    if t["quelle"] != "schueler" or not k or k["modus"] not in SELBST:
        raise TeamFehler("Dieses Team hat deine Lehrkraft gebildet. Sprich sie an, wenn du wechseln möchtest.")
    grund = " ".join(str(grund or "").split())[:300]
    if len(grund) < 3:
        raise TeamFehler("Bitte schreib kurz, warum du das Team verlassen möchtest.")
    con.execute("UPDATE lernteam_mitglied SET austritt_grund = ?, austritt_zeit = ? WHERE team_id = ? AND schueler_id = ?",
                (grund, db.jetzt(), team_id, schueler["id"]))
    db.ereignis(con, t["klasse_id"], schueler["id"], "schueler", "Schüler", "team_austritt_wunsch", team_id=t["id"], grund=grund,
                bezug=titel(con, t["bereich"], t["bezug_id"]))


def austritt_zurueck(con, schueler, team_id):
    con.execute("UPDATE lernteam_mitglied SET austritt_grund = NULL, austritt_zeit = NULL WHERE team_id = ? AND schueler_id = ?",
                (team_id, schueler["id"]))


def stand_schueler(con, schueler):
    """{teams: {schluessel: team}, einladungen: [Teams, in die ich eingeladen bin]}."""
    aus = {"teams": {}, "einladungen": []}
    for t in con.execute("SELECT t.*, m.status AS mein_status FROM lernteam t JOIN lernteam_mitglied m ON m.team_id = t.id "
                         "WHERE t.status = 'aktiv' AND m.schueler_id = ? AND m.status IN ('aktiv', 'eingeladen') ORDER BY t.id",
                         (schueler["id"],)).fetchall():
        d = team_daten(con, t, schueler["id"])
        if t["mein_status"] == "aktiv":
            aus["teams"][d["schluessel"]] = d
        else:
            aus["einladungen"].append(d)
    return aus


def finden(con, schueler, bereich, bezug_id, heute=None):
    """Fuer das Team-Blatt: offene Teams mit freien Plaetzen und Mitschueler ohne Team in dieser Einheit."""
    heute = heute or db.heute()
    _, k, t = _sichtbar(con, schueler, bereich, bezug_id, heute)
    offen = []
    im_team = set()
    for x in con.execute("SELECT * FROM lernteam WHERE bereich = ? AND bezug_id = ? AND status = 'aktiv' AND klasse_id = ?",
                         (bereich, bezug_id, schueler["klasse_id"])).fetchall():
        for m in mitglieder(con, x["id"]):
            im_team.add(m["schueler_id"])
        if x["offen"] and _belegt(con, x["id"], mit_einladungen=False) < k["max"]:
            d = team_daten(con, x, schueler["id"])
            d["mitglieder"] = [m for m in d["mitglieder"] if m["status"] == "aktiv"]
            offen.append(d)
    frei = [{"id": z["id"], "name": "%s %s" % (z["vorname"], z["nachname"])} for z in con.execute(
        "SELECT * FROM schueler WHERE klasse_id = ? AND aktiv = 1 AND id != ? ORDER BY vorname, nachname", (schueler["klasse_id"], schueler["id"]))
        if z["id"] not in im_team]
    return {"titel": t, "konfig": k, "offen": offen, "frei": frei}


# --- Lehrkraft ---

def _einheit_lk(con, klasse_id, bereich, bezug_id):
    p, k, t = _einheit_zeile(con, bereich, bezug_id)
    if bereich == "stamm":
        if bezug_id != klasse_id:
            raise TeamFehler("Das gehört nicht zu dieser Klasse.")
    elif p["klasse_id"] != klasse_id:
        raise TeamFehler("Das gehört nicht zu dieser Klasse.")
    if k is None or k["modus"] == "einzeln":
        raise TeamFehler("Dort ist kein Team-Modus eingestellt.")
    return k, t


def uebersicht(con, konto, klasse_id, heute=None):
    """Alle Einheiten der Klasse mit Teams, Einladungen, Austrittswuenschen, wartenden Fertigmeldungen und "ohne Team"."""
    heute = heute or db.heute()
    rolle = klassen.pruefen(con, klasse_id, konto, "lesen")
    schueler = [{"id": z["id"], "name": "%s %s" % (z["vorname"], z["nachname"])} for z in con.execute(
        "SELECT * FROM schueler WHERE klasse_id = ? AND aktiv = 1 ORDER BY nachname, vorname", (klasse_id,))]
    einheiten = {}
    stamm = {"modus": "stamm", "bereich": "stamm", "bezug_id": klasse_id, "schluessel": schluessel("stamm", klasse_id), "titel": "Stammteams der Klasse",
             "modus_text": MODUS_TEXT["stamm"], "aufgaben": [], "kuerzel": [], "min": None, "max": None, "stichtag": None, "paket": None}
    for p in con.execute("SELECT * FROM paket WHERE klasse_id = ? AND archiviert = 0 ORDER BY COALESCE(freigabe, '9999'), titel", (klasse_id,)).fetchall():
        for k, e in einheiten_paket(con, p).items():
            if e["bereich"] == "stamm":
                stamm["aufgaben"] += e["aufgaben"]
                stamm["kuerzel"] += e["kuerzel"]
            else:
                einheiten[k] = e
    liste = list(einheiten.values()) + [stamm]
    for e in liste:
        teams = []
        im_team = set()
        for t in con.execute("SELECT * FROM lernteam WHERE bereich = ? AND bezug_id = ? AND status = 'aktiv' AND klasse_id = ? ORDER BY id",
                             (e["bereich"], e["bezug_id"], klasse_id)).fetchall():
            d = team_daten(con, t, lehrkraft=True)
            im_team |= {m["id"] for m in d["mitglieder"] if m["status"] == "aktiv"}
            d["wartet"] = wartende_meldungen(con, t)
            teams.append(d)
        e["teams"] = teams
        e["ohne_team"] = [s for s in schueler if s["id"] not in im_team]
        e["stichtag_vorbei"] = bool(e.get("stichtag") and e["stichtag"] < heute.isoformat())
        e["austritte"] = sum(1 for d in teams for m in d["mitglieder"] if m["austritt"])
    return {"einheiten": liste, "schueler": schueler, "darf": rolle == "team"}


def wartende_meldungen(con, t):
    """Fertigmeldungen des Teams, die noch auf Bestaetigung warten: [{kuerzel, wartet: [Namen]}]."""
    aus = []
    ids = abgedeckte_aufgaben(con, t)
    if not ids:
        return aus
    ms = [m["schueler_id"] for m in mitglieder(con, t["id"])]
    if not ms:
        return aus
    for z in con.execute("SELECT DISTINCT m.gruppe, a.kuerzel FROM meldung m JOIN aufgabe a ON a.id = m.aufgabe_id WHERE m.status = 'offen' "
                         "AND m.gruppe IS NOT NULL AND m.aufgabe_id IN (%s) AND m.schueler_id IN (%s)" % (",".join("?" * len(ids)), ",".join("?" * len(ms))),
                         tuple(ids) + tuple(ms)).fetchall():
        offen = [_name(con, x[0]) for x in con.execute("SELECT schueler_id FROM meldung WHERE gruppe = ? AND status = 'offen' AND bestaetigt IS NULL",
                                                        (z["gruppe"],))]
        if offen:
            aus.append({"kuerzel": z["kuerzel"], "wartet": offen})
    return aus


def bilden(con, konto, klasse_id, bereich, bezug_id, schueler_ids, name="", heute=None):
    """Die Lehrkraft bildet ein Team (sofort aktiv). Wer schon in einem Team der Einheit ist, wechselt."""
    heute = heute or db.heute()
    klassen.pruefen(con, klasse_id, konto, "aendern")
    _einheit_lk(con, klasse_id, bereich, bezug_id)
    ids = []
    for x in schueler_ids or []:
        try:
            x = int(x)
        except (TypeError, ValueError):
            raise TeamFehler("Ungültige Auswahl.")
        if x not in ids:
            ids.append(x)
    if not ids:
        raise TeamFehler("Bitte mindestens einen Schüler wählen.")
    for x in ids:
        s = _schueler(con, x)
        if s is None or s["klasse_id"] != klasse_id or not s["aktiv"]:
            raise TeamFehler("Diesen Schüler gibt es in der Klasse nicht.")
    name = " ".join(str(name or "").split())[:40]
    tid = con.execute("INSERT INTO lernteam (klasse_id, bereich, bezug_id, name, quelle, erstellt) VALUES (?, ?, ?, ?, 'lehrkraft', ?)",
                      (klasse_id, bereich, bezug_id, name, db.jetzt())).lastrowid
    for x in ids:
        _umsetzen(con, konto, tid, x, bereich, bezug_id)
    t = con.execute("SELECT * FROM lernteam WHERE id = ?", (tid,)).fetchone()
    _zusammenfuehren(con, t, heute)
    _log(con, t, "team_gebildet", "lehrkraft", konto["kuerzel"])
    return tid


def _umsetzen(con, konto, team_id, sid, bereich, bezug_id):
    alt = team_von(con, sid, bereich, bezug_id)
    if alt is not None and alt["id"] != team_id:
        _mitglied_setzen(con, alt["id"], sid, "raus", grund="umgesetzt")
        _leer_aufloesen(con, alt, konto)
    _einladungen_ablehnen(con, sid, bereich, bezug_id, "von der Lehrkraft zugeteilt")
    _mitglied_setzen(con, team_id, sid, "aktiv")


def _leer_aufloesen(con, t, konto):
    if _belegt(con, t["id"], mit_einladungen=False) == 0:
        con.execute("UPDATE lernteam SET status = 'aufgeloest', ende = ?, ende_von = ? WHERE id = ?", (db.jetzt(), "lehrkraft:" + konto["kuerzel"], t["id"]))


def mitglied_aendern(con, konto, team_id, schueler_id, aktion, heute=None):
    """aktion: hinzu (zuteilen, auch ueber die Groesse hinaus; wechselt aus einem anderen Team) | entfernen."""
    heute = heute or db.heute()
    t = _team(con, team_id)
    klassen.pruefen(con, t["klasse_id"], konto, "aendern")
    s = _schueler(con, schueler_id)
    if s is None or s["klasse_id"] != t["klasse_id"]:
        raise TeamFehler("Diesen Schüler gibt es in der Klasse nicht.")
    if aktion == "hinzu":
        _umsetzen(con, konto, team_id, schueler_id, t["bereich"], t["bezug_id"])
        _zusammenfuehren(con, t, heute)
        _log(con, t, "team_zugeteilt", "lehrkraft", konto["kuerzel"], name=_name(con, schueler_id))
    elif aktion == "entfernen":
        _log(con, t, "team_entfernt", "lehrkraft", konto["kuerzel"], name=_name(con, schueler_id))
        _mitglied_setzen(con, team_id, schueler_id, "raus", grund="Lehrkraft")
        _leer_aufloesen(con, t, konto)
    else:
        raise TeamFehler("Unbekannte Aktion.")


def austritt_entscheiden(con, konto, team_id, schueler_id, zustimmen):
    t = _team(con, team_id)
    klassen.pruefen(con, t["klasse_id"], konto, "aendern")
    m = _mitglied(con, team_id, schueler_id)
    if m is None or m["status"] != "aktiv" or not m["austritt_grund"]:
        raise TeamFehler("Dieser Austrittswunsch ist nicht (mehr) offen.")
    if zustimmen:
        _log(con, t, "team_austritt", "lehrkraft", konto["kuerzel"], name=_name(con, schueler_id), grund=m["austritt_grund"])
        _mitglied_setzen(con, team_id, schueler_id, "raus", grund="Austritt")
        _leer_aufloesen(con, t, konto)
    else:
        con.execute("UPDATE lernteam_mitglied SET austritt_grund = NULL, austritt_zeit = NULL WHERE team_id = ? AND schueler_id = ?", (team_id, schueler_id))
        db.ereignis(con, t["klasse_id"], schueler_id, "lehrkraft", konto["kuerzel"], "team_austritt_abgelehnt", team_id=t["id"],
                    bezug=titel(con, t["bereich"], t["bezug_id"]))


def aufloesen(con, konto, team_id):
    t = _team(con, team_id)
    klassen.pruefen(con, t["klasse_id"], konto, "aendern")
    _log(con, t, "team_aufgeloest", "lehrkraft", konto["kuerzel"])
    con.execute("UPDATE lernteam SET status = 'aufgeloest', ende = ?, ende_von = ? WHERE id = ?", (db.jetzt(), "lehrkraft:" + konto["kuerzel"], team_id))
    con.execute("UPDATE lernteam_mitglied SET status = 'raus', ende = ?, ende_grund = 'aufgelöst' WHERE team_id = ? AND status != 'raus'",
                (db.jetzt(), team_id))


def bei_abwahl(con, schueler, aufgabe_id):
    """Wahlaufgabe abgewaehlt: ein Team genau fuer diese Aufgabe verlaesst der Schueler."""
    t = team_von(con, schueler["id"], "aufgabe", aufgabe_id)
    if t is not None:
        _log(con, t, "team_verlassen", "schueler", "Schüler", name=_name(con, schueler["id"]), grund="abgewählt")
        _mitglied_setzen(con, t["id"], schueler["id"], "raus", grund="abgewählt")
        if _belegt(con, t["id"], mit_einladungen=False) == 0:
            con.execute("UPDATE lernteam SET status = 'aufgeloest', ende = ?, ende_von = 'abgewählt' WHERE id = ?", (db.jetzt(), t["id"]))


def matrix_hinweise(con, klasse_id, paket_id):
    """{schueler_id: ["Team A: Paul B., Nico W.", ...]} fuer die Teams, die im Paket gelten (mit Stammteams)."""
    p = con.execute("SELECT * FROM paket WHERE id = ?", (paket_id,)).fetchone()
    if p is None:
        return {}
    aus = {}
    for e in einheiten_paket(con, p).values():
        for t in con.execute("SELECT * FROM lernteam WHERE bereich = ? AND bezug_id = ? AND status = 'aktiv'", (e["bereich"], e["bezug_id"])).fetchall():
            ms = mitglieder(con, t["id"])
            was = "Stammteam" if e["bereich"] == "stamm" else "Paket" if e["bereich"] == "paket" else ", ".join(e["kuerzel"]) if e["bereich"] == "gruppe" else e["kuerzel"][0]
            for m in ms:
                andere = ["%s %s." % (x["vorname"], x["nachname"][:1]) for x in ms if x["schueler_id"] != m["schueler_id"]]
                if andere:
                    aus.setdefault(m["schueler_id"], []).append("%s mit %s" % (was, ", ".join(andere)))
    return aus
