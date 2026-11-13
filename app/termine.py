"""Hilfe-Reihe, Sprech- und Pruefungszeiten, Feedbacktermine (Stufe D).

Hilfe-Knopf: Der Schueler tippt "Ich brauche Hilfe" und steht sofort in der Reihe, die alle Lehrkraefte der Klasse
sehen. Er sieht nur seinen Platz ("Du bist Nr. 2"), keine Namen. "Erledigt" (durch eine Lehrkraft) gilt fuer alle.
Nur an Unterrichtstagen mit Lehrkraft; an Tagen "ohne Lehrkraft" ist der Knopf gesperrt. Die Reihe gilt fuer den Tag.

Zeitfenster je Lehrkraft und Klasse, zwei feste Arten:
  sprech    Sprechzeit, nur Feedbackgespraeche
  pruefung  Pruefungszeit, nur Fachgespraech und praktische Pruefung (Buchung mit Stufe E)
Je Fenster Beginn, Ende, Termindauer x und Puffer y; Tage woechentlich (gueltig von bis) oder einzeln gewaehlt.
Termine entstehen nur an Tagen, an denen der Unterricht der Klasse mit Lehrkraft stattfindet (nicht bei Ausfall,
Ferien, "ohne Lehrkraft").

Feedback: Der Schueler gibt den Anlass an (Aufgabe, Paket oder allgemein), hat hoechstens einen offenen Termin und
kann bis zum Vortag selbst absagen. Andere Schueler sieht er nur als "belegt" (eigentlich: gar nicht, der Platz fehlt).

Gespraechstermin: Aus "Zu pruefen" traegt die Lehrkraft dem Schueler einen Termin aus ihrer eigenen Sprechzeit ein
("Gespraech noetig", mit Hinweis). Das ist ein Pflichttermin: absagen oder verlegen koennen nur Lehrkraefte; er zaehlt
nicht als der eine offene Feedbacktermin des Schuelers.

Teamtermin (Stufe G): Ein Mitglied eines Lernteams bucht in einer Sprechzeit fuer das ganze Team (je Mitglied eine
Terminzeile mit team_id); er zaehlt als der eine offene Feedbacktermin jedes Mitglieds, absagen kann jedes Mitglied bis
zum Vortag (fuer alle). Die Lehrkraft kann einen Teamtermin aus ihrer Sprechzeit eintragen (Pflichttermin).

Dienstkalender (Stufe F): Ein Termin mit Uhrzeit im Dienstkalender der Lehrkraft sperrt die Plaetze ihrer Zeitfenster,
mit denen er sich ueberschneidet (grau, nicht buchbar). Schon gebuchte Termine bleiben und werden als Ueberschneidung
gezeigt. Beim Anlegen eines Zeitfensters warnt das Tool vor Ueberschneidungen.
"""
import datetime
import json
import re

from . import db, kalender, klassen, teams, unterrichtstage as ut

TAG = datetime.timedelta(days=1)
ARTEN = {"sprech": "Sprechzeit", "pruefung": "Prüfungszeit"}
TERMINARTEN = {"feedback": "sprech", "fachgespraech": "pruefung", "praxis": "pruefung"}
VORAUS_TAGE = 35          # so weit voraus kann ein Schueler buchen
MAX_EINZELTAGE = 40


class TerminFehler(Exception):
    pass


def _min(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def _hhmm(minuten):
    return "%02d:%02d" % (minuten // 60, minuten % 60)


def _jetzt_hhmm():
    return db.jetzt()[11:16]


def _tag_der_klasse(con, klasse_id, d):
    t = ut.tage(con, klasse_id, d, d)
    return t[0] if t else None


# --- Hilfe-Reihe ---

def _hilfe_offen(con, klasse_id, datum):
    return con.execute("SELECT * FROM hilfe WHERE klasse_id = ? AND datum = ? AND ende IS NULL ORDER BY id", (klasse_id, datum)).fetchall()


def hilfe_stand(con, schueler, heute=None):
    heute = heute or db.heute()
    t = _tag_der_klasse(con, schueler["klasse_id"], heute)
    erlaubt = bool(t and t["status"] == "unterricht")
    grund = "" if erlaubt else ("heute ohne Lehrkraft" if t and t["status"] == "ohne" else "heute kein Lernbüro")
    offen = _hilfe_offen(con, schueler["klasse_id"], heute.isoformat())
    eigen = next((i for i, h in enumerate(offen) if h["schueler_id"] == schueler["id"]), None)
    return {"erlaubt": erlaubt, "grund": grund, "offen": eigen is not None, "platz": eigen + 1 if eigen is not None else None,
            "seit": offen[eigen]["zeit"] if eigen is not None else None,
            "aufgabe_id": offen[eigen]["aufgabe_id"] if eigen is not None else None}


def hilfe_rufen(con, schueler, aufgabe_id=None, heute=None):
    heute = heute or db.heute()
    st = hilfe_stand(con, schueler, heute)
    if not st["erlaubt"]:
        raise TerminFehler("Der Hilfe-Knopf geht nur im Lernbüro mit Lehrkraft (%s)." % st["grund"])
    if st["offen"]:
        return st
    if aufgabe_id is not None:
        a = con.execute("SELECT a.kuerzel, p.klasse_id FROM aufgabe a JOIN paket p ON p.id = a.paket_id WHERE a.id = ?", (aufgabe_id,)).fetchone()
        if a is None or a["klasse_id"] != schueler["klasse_id"]:
            aufgabe_id = None
    con.execute("INSERT INTO hilfe (schueler_id, klasse_id, aufgabe_id, datum, zeit) VALUES (?, ?, ?, ?, ?)",
                (schueler["id"], schueler["klasse_id"], aufgabe_id, heute.isoformat(), db.jetzt()))
    db.ereignis(con, schueler["klasse_id"], schueler["id"], "schueler", "Schüler", "hilfe", aufgabe_id=aufgabe_id)
    return hilfe_stand(con, schueler, heute)


def hilfe_zurueckziehen(con, schueler, heute=None):
    heute = heute or db.heute()
    n = con.execute("UPDATE hilfe SET ende = ?, ende_art = 'zurueckgezogen' WHERE schueler_id = ? AND datum = ? AND ende IS NULL",
                    (db.jetzt(), schueler["id"], heute.isoformat())).rowcount
    if n:
        db.ereignis(con, schueler["klasse_id"], schueler["id"], "schueler", "Schüler", "hilfe_zurueck")
    return hilfe_stand(con, schueler, heute)


def hilfe_reihe(con, konto, heute=None):
    """Offene Hilfe-Meldungen von heute in allen Klassen der Lehrkraft (Team und Einsicht), in der Reihenfolge des Eingangs."""
    heute = heute or db.heute()
    aus = []
    for h in con.execute("SELECT h.*, s.vorname, s.nachname, k.name AS klasse, kl.rolle, a.kuerzel, a.titel FROM hilfe h "
                         "JOIN schueler s ON s.id = h.schueler_id JOIN klasse k ON k.id = h.klasse_id "
                         "JOIN klasse_lehrkraft kl ON kl.klasse_id = h.klasse_id AND kl.lehrkraft_id = ? "
                         "LEFT JOIN aufgabe a ON a.id = h.aufgabe_id WHERE h.datum = ? AND h.ende IS NULL ORDER BY h.id",
                         (konto["id"], heute.isoformat())):
        aus.append({"id": h["id"], "zeit": h["zeit"], "schueler_id": h["schueler_id"], "name": "%s %s" % (h["vorname"], h["nachname"]),
                    "klasse_id": h["klasse_id"], "klasse": h["klasse"], "kuerzel": h["kuerzel"], "titel": h["titel"], "darf": h["rolle"] == "team"})
    return aus


def hilfe_erledigt(con, konto, hilfe_id):
    h = con.execute("SELECT * FROM hilfe WHERE id = ?", (hilfe_id,)).fetchone()
    if h is None:
        raise TerminFehler("Diese Hilfe-Meldung gibt es nicht.")
    klassen.pruefen(con, h["klasse_id"], konto, "aendern")
    if h["ende"] is None:
        con.execute("UPDATE hilfe SET ende = ?, ende_art = 'erledigt', ende_von = ? WHERE id = ?", (db.jetzt(), konto["id"], hilfe_id))
        db.ereignis(con, h["klasse_id"], h["schueler_id"], "lehrkraft", konto["kuerzel"], "hilfe_erledigt")


# --- Zeitfenster ---

def _zahl(wert, name, von, bis):
    try:
        wert = int(wert)
    except (TypeError, ValueError):
        raise TerminFehler("Bitte %s als Zahl angeben." % name)
    if not von <= wert <= bis:
        raise TerminFehler("%s: bitte %d bis %d Minuten." % (name, von, bis))
    return wert


def _fenster_daten(con, z):
    tage = json.loads(z["tage"] or "[]")
    l = con.execute("SELECT kuerzel, name FROM lehrkraft WHERE id = ?", (z["lehrkraft_id"],)).fetchone()
    return {"id": z["id"], "klasse_id": z["klasse_id"], "lehrkraft_id": z["lehrkraft_id"], "lehrkraft": l["name"], "kuerzel": l["kuerzel"],
            "art": z["art"], "art_text": ARTEN[z["art"]], "von": z["von"], "bis": z["bis"], "dauer": z["dauer"], "puffer": z["puffer"],
            "woechentlich": z["wochentag"] is not None, "wochentag": z["wochentag"],
            "tag": ut.TAGE[z["wochentag"]] if z["wochentag"] is not None else None,
            "gueltig_von": z["gueltig_von"], "gueltig_bis": z["gueltig_bis"], "tage": tage,
            "plaetze_je_tag": len(plaetze(z))}


def plaetze(z):
    """[(beginn, ende)] eines Tages: x Minuten Termin, dann y Minuten Puffer, solange der Termin ins Fenster passt."""
    aus, t, ende = [], _min(z["von"]), _min(z["bis"])
    while t + z["dauer"] <= ende:
        aus.append((_hhmm(t), _hhmm(t + z["dauer"])))
        t += z["dauer"] + z["puffer"]
    return aus


def _kalendertage(z, von, bis):
    """Tage des Fensters zwischen von und bis (date), noch ohne Blick auf den Unterricht."""
    if z["wochentag"] is not None:
        a = max(von, ut.datum(z["gueltig_von"]))
        b = min(bis, ut.datum(z["gueltig_bis"]))
        aus, d = [], a
        while d <= b:
            if d.weekday() == z["wochentag"]:
                aus.append(d)
            d += TAG
        return aus
    return [ut.datum(x) for x in json.loads(z["tage"] or "[]") if von.isoformat() <= x <= bis.isoformat()]


def fenstertage(con, z, von, bis):
    """[(datum, tag)] an denen das Fenster wirklich gilt: Unterricht der Klasse mit Lehrkraft."""
    aus = []
    for d in _kalendertage(z, von, bis):
        t = _tag_der_klasse(con, z["klasse_id"], d)
        aus.append((d, t))
    return aus


def zeitfenster_liste(con, konto, klasse_id):
    klassen.pruefen(con, klasse_id, konto, "lesen")
    return [_fenster_daten(con, z) for z in con.execute(
        "SELECT * FROM zeitfenster WHERE klasse_id = ? AND aktiv = 1 ORDER BY art, COALESCE(wochentag, 9), von", (klasse_id,))]


def _ueberschneidungen(con, konto, neu, ausser=None):
    """Warnungen: eigene aktive Zeitfenster (alle Klassen), die sich an einem gemeinsamen Tag zeitlich ueberschneiden."""
    heute = db.heute()
    bis = heute + 200 * TAG
    eigene_tage = {d.isoformat() for d in _kalendertage(neu, heute, bis)}
    warnungen = []
    for z in con.execute("SELECT z.*, k.name AS klasse FROM zeitfenster z JOIN klasse k ON k.id = z.klasse_id "
                         "WHERE z.lehrkraft_id = ? AND z.aktiv = 1 AND z.id IS NOT ?", (konto["id"], ausser)).fetchall():
        if not (_min(z["von"]) < _min(neu["bis"]) and _min(neu["von"]) < _min(z["bis"])):
            continue
        gemeinsam = sorted(eigene_tage & {d.isoformat() for d in _kalendertage(z, heute, bis)})
        if gemeinsam:
            warnungen.append("Überschneidung mit Ihrer %s %s–%s (%s), z. B. am %s" % (
                ARTEN[z["art"]], z["von"], z["bis"], z["klasse"], ut.TAGE[ut.datum(gemeinsam[0]).weekday()] + " " +
                ut.datum(gemeinsam[0]).strftime("%d.%m.")))
    return warnungen


def _dienst_warnung(con, konto, z, tage):
    """Warnung, wenn Termine des eigenen Dienstkalenders in das neue Zeitfenster fallen (Tage mit Unterricht)."""
    treffer = []
    for d, t in tage:
        if t is None or t["status"] != "unterricht":
            continue
        titel = kalender.kollision(z["von"], z["bis"], kalender.dienst_belegt(con, konto["id"], d))
        if titel:
            treffer.append((d, titel))
    if not treffer:
        return None
    d, titel = treffer[0]
    return "Überschneidung mit Ihrem Dienstkalender: %s am %s%s. Diese Plätze sind nicht buchbar." % (
        titel, ut.TAGE[d.weekday()] + " " + d.strftime("%d.%m."), " und an %d weiteren Tagen" % (len(treffer) - 1) if len(treffer) > 1 else "")


def _fenster_pruefen(d):
    art = d.get("art")
    if art not in ARTEN:
        raise TerminFehler("Bitte Sprechzeit oder Prüfungszeit wählen.")
    try:
        von, bis = ut.uhrzeit(d.get("von"), "den Beginn"), ut.uhrzeit(d.get("bis"), "das Ende")
    except ut.TageFehler as f:
        raise TerminFehler(str(f))
    if _min(bis) <= _min(von):
        raise TerminFehler("Das Ende muss nach dem Beginn liegen.")
    dauer = _zahl(d.get("dauer"), "Termindauer", 5, 120)
    puffer = _zahl(d.get("puffer") or 0, "Puffer", 0, 60)
    if dauer > _min(bis) - _min(von):
        raise TerminFehler("Ein Termin passt nicht in das Zeitfenster.")
    werte = {"art": art, "von": von, "bis": bis, "dauer": dauer, "puffer": puffer, "wochentag": None, "gueltig_von": None,
             "gueltig_bis": None, "tage": "[]"}
    try:
        if d.get("woechentlich", True):
            a = ut.datum(d.get("gueltig_von"), "den ersten Tag")
            b = ut.datum(d.get("gueltig_bis"), "den letzten Tag")
            if b < a:
                raise TerminFehler("Der letzte Tag liegt vor dem ersten.")
            if (b - a).days > 400:
                raise TerminFehler("Höchstens etwa ein Schuljahr auf einmal.")
            werte.update(wochentag=a.weekday(), gueltig_von=a.isoformat(), gueltig_bis=b.isoformat())
        else:
            tage = sorted({ut.datum(x, "die Tage").isoformat() for x in (d.get("tage") or [])})
            if not tage:
                raise TerminFehler("Bitte mindestens einen Tag wählen.")
            if len(tage) > MAX_EINZELTAGE:
                raise TerminFehler("Höchstens %d einzelne Tage." % MAX_EINZELTAGE)
            werte["tage"] = json.dumps(tage)
    except ut.TageFehler as f:
        raise TerminFehler(str(f))
    return werte


def zeitfenster_anlegen(con, konto, klasse_id, d):
    klassen.pruefen(con, klasse_id, konto, "aendern")
    w = _fenster_pruefen(d)
    warnungen = _ueberschneidungen(con, konto, w)
    zid = con.execute("INSERT INTO zeitfenster (klasse_id, lehrkraft_id, art, von, bis, dauer, puffer, wochentag, gueltig_von, gueltig_bis, "
                      "tage, erstellt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (klasse_id, konto["id"], w["art"], w["von"], w["bis"], w["dauer"], w["puffer"], w["wochentag"], w["gueltig_von"],
                       w["gueltig_bis"], w["tage"], db.jetzt())).lastrowid
    z = con.execute("SELECT * FROM zeitfenster WHERE id = ?", (zid,)).fetchone()
    heute = db.heute()
    tage = fenstertage(con, z, heute, heute + 200 * TAG)
    if tage and not any(t and t["status"] == "unterricht" for _, t in tage):
        warnungen.append("An keinem dieser Tage hat die Klasse Unterricht mit Lehrkraft: dort entstehen keine Termine.")
    elif any(t is None for _, t in tage):
        warnungen.append("An einigen Tagen hat die Klasse keinen Unterricht: dort entstehen keine Termine.")
    dienst = _dienst_warnung(con, konto, z, tage)
    if dienst:
        warnungen.append(dienst)
    db.ereignis(con, klasse_id, None, "lehrkraft", konto["kuerzel"], "zeitfenster_angelegt", zeitfenster_id=zid, fensterart=w["art"])
    return {"zeitfenster": _fenster_daten(con, z), "warnungen": warnungen}


def zeitfenster_entfernen(con, konto, zid):
    z = con.execute("SELECT * FROM zeitfenster WHERE id = ? AND aktiv = 1", (zid,)).fetchone()
    if z is None:
        raise TerminFehler("Dieses Zeitfenster gibt es nicht.")
    klassen.pruefen(con, z["klasse_id"], konto, "aendern")
    if z["lehrkraft_id"] != konto["id"]:
        raise TerminFehler("Nur die eigene Sprech- oder Prüfungszeit lässt sich entfernen.")
    heute = db.heute().isoformat()
    ids = [z0[0] for z0 in con.execute("SELECT id FROM termin WHERE zeitfenster_id = ? AND abgesagt IS NULL AND datum >= ?", (zid, heute))]
    abgesagt = con.execute("UPDATE termin SET abgesagt = ?, abgesagt_von = ? WHERE zeitfenster_id = ? AND abgesagt IS NULL AND datum >= ?",
                           (db.jetzt(), "lehrkraft:" + konto["kuerzel"], zid, heute)).rowcount
    _versuche_loesen(con, ids)
    con.execute("UPDATE zeitfenster SET aktiv = 0 WHERE id = ?", (zid,))
    db.ereignis(con, z["klasse_id"], None, "lehrkraft", konto["kuerzel"], "zeitfenster_entfernt", zeitfenster_id=zid, abgesagt=abgesagt)
    return abgesagt


def _versuche_loesen(con, termin_ids):
    """Ein abgesagter Pruefungstermin: der Versuch bleibt "bereit", der Schueler bucht neu."""
    con.executemany("UPDATE versuch SET termin_id = NULL WHERE termin_id = ?", [(t,) for t in termin_ids])


def _gebucht(con, zid, datum):
    """{beginn: Termin}; ein Teamgespraech (zwei Schueler, ein Platz) zeigt beide Namen."""
    aus = {}
    for z in con.execute("SELECT t.*, s.vorname, s.nachname FROM termin t JOIN schueler s ON s.id = t.schueler_id "
                         "WHERE t.zeitfenster_id = ? AND t.datum = ? AND t.abgesagt IS NULL ORDER BY t.id", (zid, datum)):
        if z["beginn"] in aus:
            erster = dict(aus[z["beginn"]])
            erster["nachname"] = erster["nachname"] + " + " + z["vorname"] + " " + z["nachname"]
            aus[z["beginn"]] = erster
        else:
            aus[z["beginn"]] = z
    return aus


def _anlass_text(con, t):
    if t["nachweis_id"]:
        n = con.execute("SELECT n.titel, p.titel AS paket FROM nachweis n JOIN paket p ON p.id = n.paket_id WHERE n.id = ?",
                        (t["nachweis_id"],)).fetchone()
        if n:
            return "Gelingensnachweis " + (n["titel"] + " · " if n["titel"] else "") + n["paket"]
    if t["anlass_aufgabe_id"]:
        a = con.execute("SELECT kuerzel, titel FROM aufgabe WHERE id = ?", (t["anlass_aufgabe_id"],)).fetchone()
        if a:
            return "%s %s" % (a[0], a[1])
    if t["anlass_paket_id"]:
        p = con.execute("SELECT titel FROM paket WHERE id = ?", (t["anlass_paket_id"],)).fetchone()
        if p:
            return "Paket " + p[0]
    return t["anlass_text"] or "allgemein"


def belegung(con, konto, klasse_id, von=None, tage=21):
    """Fuer die Seite "Zeitfenster": je Tag und Fenster die Plaetze (frei, gebucht mit Name und Anlass, Puffer)."""
    klassen.pruefen(con, klasse_id, konto, "lesen")
    von = von or db.heute()
    bis = von + tage * TAG
    aus = []
    for z in con.execute("SELECT * FROM zeitfenster WHERE klasse_id = ? AND aktiv = 1", (klasse_id,)).fetchall():
        eigen = z["lehrkraft_id"] == konto["id"]
        for d, t in fenstertage(con, z, von, bis):
            if t is None:
                continue
            gebucht = _gebucht(con, z["id"], d.isoformat())
            belegt = kalender.dienst_belegt(con, z["lehrkraft_id"], d)
            zeilen = []
            for i, (b, e) in enumerate(plaetze(z)):
                g = gebucht.get(b)
                dienst = kalender.kollision(b, e, belegt)
                zeilen.append({"beginn": b, "ende": e, "termin": {"id": g["id"], "name": "%s %s" % (g["vorname"], g["nachname"]),
                               "schueler_id": g["schueler_id"], "art": g["art"], "anlass": _anlass_text(con, g)} if g else None,
                               "dienst": (dienst if eigen else "Dienstkalender") if dienst else None})
                if z["puffer"] and i < len(plaetze(z)) - 1:
                    zeilen.append({"beginn": e, "ende": _hhmm(_min(e) + z["puffer"]), "puffer": True})
            aus.append({"datum": d.isoformat(), "tag": t["tag"], "status": t["status"], "grund": t["grund"],
                        "zeitfenster": _fenster_daten(con, z), "plaetze": zeilen})
    aus.sort(key=lambda x: (x["datum"], x["zeitfenster"]["von"]))
    return aus


def termine_heute(con, konto, heute=None):
    """Gebuchte Termine von heute in den eigenen Zeitfenstern."""
    heute = (heute or db.heute()).isoformat()
    aus = []
    for t in con.execute("SELECT t.*, s.vorname, s.nachname, s.klasse_id, k.name AS klasse, z.art AS fensterart FROM termin t "
                         "JOIN zeitfenster z ON z.id = t.zeitfenster_id JOIN schueler s ON s.id = t.schueler_id JOIN klasse k ON k.id = s.klasse_id "
                         "WHERE z.lehrkraft_id = ? AND t.datum = ? AND t.abgesagt IS NULL AND k.archiviert = 0 ORDER BY t.beginn", (konto["id"], heute)):
        aus.append({"id": t["id"], "beginn": t["beginn"], "ende": t["ende"], "art": t["art"], "schueler_id": t["schueler_id"],
                    "name": "%s %s" % (t["vorname"], t["nachname"]), "klasse_id": t["klasse_id"], "klasse": t["klasse"],
                    "anlass": _anlass_text(con, t), "anlass_aufgabe_id": t["anlass_aufgabe_id"], "nachweis_id": t["nachweis_id"],
                    "rueckmeldung": bool(con.execute("SELECT 1 FROM rueckmeldung WHERE termin_id = ? AND freigegeben IS NOT NULL", (t["id"],)).fetchone()),
                    "team_id": t["team_id"]})
    zusammen, ergebnis = {}, []   # Teamtermin: eine Zeile fuer das ganze Team
    for e in aus:
        k = (e["team_id"], e["beginn"]) if e["team_id"] else None
        if k and k in zusammen:
            zusammen[k]["name"] += ", " + e["name"].split(" ")[0]
            continue
        if k:
            zusammen[k] = e
            e["name"] = e["name"].split(" ")[0]
        ergebnis.append(e)
    return ergebnis


def absagen_lehrkraft(con, konto, termin_id):
    t = con.execute("SELECT t.*, z.klasse_id FROM termin t JOIN zeitfenster z ON z.id = t.zeitfenster_id WHERE t.id = ?", (termin_id,)).fetchone()
    if t is None or t["abgesagt"]:
        raise TerminFehler("Diesen Termin gibt es nicht (mehr).")
    klassen.pruefen(con, t["klasse_id"], konto, "aendern")
    for x in _gleiche_termine(con, t):
        con.execute("UPDATE termin SET abgesagt = ?, abgesagt_von = ? WHERE id = ?", (db.jetzt(), "lehrkraft:" + konto["kuerzel"], x["id"]))
        _versuche_loesen(con, [x["id"]])
        db.ereignis(con, t["klasse_id"], x["schueler_id"], "lehrkraft", konto["kuerzel"], "termin_abgesagt", datum=t["datum"], beginn=t["beginn"])


# --- Schueler: buchen und absagen ---

def freie_plaetze(con, schueler, art="feedback", heute=None, jetzt_hhmm=None, lehrkraft_id=None):
    """[{datum, tag, zeitfenster_id, lehrkraft, plaetze: [beginn, ...]}] fuer die naechsten Wochen (heute nur spaetere Plaetze).
    lehrkraft_id: nur die Fenster dieser Lehrkraft (Gespraechstermin aus "Zu pruefen")."""
    heute = heute or db.heute()
    jetzt_hhmm = jetzt_hhmm or _jetzt_hhmm()
    fensterart = TERMINARTEN[art]
    aus = []
    for z in con.execute("SELECT * FROM zeitfenster WHERE klasse_id = ? AND aktiv = 1 AND art = ? AND (? IS NULL OR lehrkraft_id = ?)",
                         (schueler["klasse_id"], fensterart, lehrkraft_id, lehrkraft_id)).fetchall():
        l = con.execute("SELECT name FROM lehrkraft WHERE id = ?", (z["lehrkraft_id"],)).fetchone()
        for d, t in fenstertage(con, z, heute, heute + VORAUS_TAGE * TAG):
            if t is None or t["status"] != "unterricht":
                continue
            gebucht = _gebucht(con, z["id"], d.isoformat())
            belegt = kalender.dienst_belegt(con, z["lehrkraft_id"], d)
            frei = [b for b, e in plaetze(z) if b not in gebucht and (d > heute or b > jetzt_hhmm) and not kalender.kollision(b, e, belegt)]
            if frei:
                aus.append({"datum": d.isoformat(), "tag": t["tag"], "zeitfenster_id": z["id"], "lehrkraft": l[0], "dauer": z["dauer"], "plaetze": frei})
    aus.sort(key=lambda x: (x["datum"], x["plaetze"][0]))
    return aus


def termine_schueler(con, schueler, heute=None):
    heute = (heute or db.heute()).isoformat()
    aus = []
    for t in con.execute("SELECT t.*, l.name AS lehrkraft FROM termin t JOIN zeitfenster z ON z.id = t.zeitfenster_id "
                         "JOIN lehrkraft l ON l.id = z.lehrkraft_id WHERE t.schueler_id = ? AND t.datum >= ? ORDER BY t.datum, t.beginn",
                         (schueler["id"], heute)):
        if t["abgesagt"] and not t["abgesagt_von"].startswith("lehrkraft"):
            continue
        aus.append({"id": t["id"], "datum": t["datum"], "beginn": t["beginn"], "ende": t["ende"], "art": t["art"], "lehrkraft": t["lehrkraft"],
                    "anlass": _anlass_text(con, t), "abgesagt": t["abgesagt"], "von_lehrkraft_abgesagt": bool(t["abgesagt"]),
                    "pflicht": bool(t["pflicht"]), "hinweis": t["hinweis"], "absagen_bis": (ut.datum(t["datum"]) - TAG).isoformat(),
                    "darf_absagen": t["datum"] > heute and not t["abgesagt"] and not t["pflicht"]})
    return aus


def buchen(con, schueler, zeitfenster_id, datum, beginn, art="feedback", anlass=None, heute=None, jetzt_hhmm=None):
    """Feedback: anlass {aufgabe_id} | {paket_id} | {text} (allgemein), nur in Sprechzeiten.
    Fachgespraech / praktische Pruefung: anlass {versuch_id} (bereit gemeldet), nur in Pruefungszeiten."""
    heute = heute or db.heute()
    jetzt_hhmm = jetzt_hhmm or _jetzt_hhmm()
    if art not in TERMINARTEN:
        raise TerminFehler("Unbekannte Terminart.")
    anlass = anlass if isinstance(anlass, dict) else {}
    versuch = None
    if art != "feedback":
        try:
            versuch = con.execute("SELECT v.*, n.art AS nachweisart, n.paket_id FROM versuch v JOIN nachweis n ON n.id = v.nachweis_id "
                                  "WHERE v.id = ? AND v.schueler_id = ?", (int(anlass.get("versuch_id")), schueler["id"])).fetchone()
        except (TypeError, ValueError):
            versuch = None
        if versuch is None or versuch["status"] != "bereit" or versuch["nachweisart"] != art:
            raise TerminFehler("Melde dich zuerst für diesen Gelingensnachweis bereit.")
        if versuch["termin_id"] and con.execute("SELECT 1 FROM termin WHERE id = ? AND abgesagt IS NULL", (versuch["termin_id"],)).fetchone():
            raise TerminFehler("Für diesen Gelingensnachweis hast du schon einen Termin. Sage ihn ab, wenn du einen anderen willst.")
    z = con.execute("SELECT * FROM zeitfenster WHERE id = ? AND aktiv = 1", (zeitfenster_id,)).fetchone()
    if z is None or z["klasse_id"] != schueler["klasse_id"] or z["art"] != TERMINARTEN[art]:
        raise TerminFehler("Feedbackgespräche gibt es nur in einer Sprechzeit deiner Klasse." if art == "feedback"
                           else "Fachgespräch und praktische Prüfung gibt es nur in einer Prüfungszeit deiner Klasse.")
    try:
        d = ut.datum(datum)
    except ut.TageFehler:
        raise TerminFehler("Ungültiger Tag.")
    if d < heute or d > heute + VORAUS_TAGE * TAG or (d == heute and str(beginn) <= jetzt_hhmm):
        raise TerminFehler("Dieser Termin lässt sich nicht (mehr) buchen.")
    if d not in [x for x, t in fenstertage(con, z, d, d) if t and t["status"] == "unterricht"]:
        raise TerminFehler("An diesem Tag gibt es keine %s." % ARTEN[z["art"]])
    platz = next(((b, e) for b, e in plaetze(z) if b == beginn), None)
    if platz is None:
        raise TerminFehler("Diesen Platz gibt es nicht.")
    personen = [schueler]
    team = None
    if art == "feedback" and anlass.get("team_id"):
        try:
            team = con.execute("SELECT t.* FROM lernteam t JOIN lernteam_mitglied m ON m.team_id = t.id WHERE t.id = ? AND t.status = 'aktiv' "
                               "AND m.schueler_id = ? AND m.status = 'aktiv'", (int(anlass["team_id"]), schueler["id"])).fetchone()
        except (TypeError, ValueError):
            team = None
        if team is None:
            raise TerminFehler("In diesem Team bist du nicht.")
        personen = [con.execute("SELECT * FROM schueler WHERE id = ?", (m["schueler_id"],)).fetchone() for m in teams.mitglieder(con, team["id"])]
        personen = [p for p in personen if p["aktiv"]]
    for p in personen if art == "feedback" else []:
        if con.execute("SELECT 1 FROM termin WHERE schueler_id = ? AND art = 'feedback' AND pflicht = 0 AND abgesagt IS NULL AND (datum > ? OR "
                       "(datum = ? AND ende > ?))", (p["id"], heute.isoformat(), heute.isoformat(), jetzt_hhmm)).fetchone():
            raise TerminFehler("Du hast schon einen offenen Feedbacktermin. Sage ihn ab, wenn du einen anderen willst." if p["id"] == schueler["id"]
                               else "%s hat schon einen offenen Feedbacktermin." % p["vorname"])
    if beginn in _gebucht(con, z["id"], d.isoformat()) or kalender.kollision(platz[0], platz[1], kalender.dienst_belegt(con, z["lehrkraft_id"], d)):
        raise TerminFehler("Dieser Platz ist gerade vergeben worden. Bitte einen anderen wählen.")
    aufgabe_id = paket_id = None
    text = re.sub(r"\s+", " ", str(anlass.get("text") or "")).strip()[:200]
    if versuch:
        paket_id, text = versuch["paket_id"], ""
    elif team is not None:
        td = teams.team_daten(con, team)
        text = "Team: %s (%s)" % (", ".join(m["vorname"] for m in td["mitglieder"] if m["status"] == "aktiv"), td["titel"])
    elif anlass.get("aufgabe_id"):
        a = con.execute("SELECT a.id, a.paket_id, p.klasse_id FROM aufgabe a JOIN paket p ON p.id = a.paket_id WHERE a.id = ?",
                        (int(anlass["aufgabe_id"]),)).fetchone()
        if a is None or a["klasse_id"] != schueler["klasse_id"]:
            raise TerminFehler("Diese Aufgabe gibt es in deinem Plan nicht.")
        aufgabe_id, paket_id = a["id"], a["paket_id"]
    elif anlass.get("paket_id"):
        p = con.execute("SELECT id FROM paket WHERE id = ? AND klasse_id = ?", (int(anlass["paket_id"]), schueler["klasse_id"])).fetchone()
        if p is None:
            raise TerminFehler("Dieses Paket gibt es nicht.")
        paket_id = p["id"]
    elif not text:
        raise TerminFehler("Bitte den Anlass angeben: eine Aufgabe, ein Paket oder kurz, worum es geht.")
    tid = None
    for p in personen:
        neu = con.execute("INSERT INTO termin (zeitfenster_id, schueler_id, datum, beginn, ende, art, anlass_aufgabe_id, anlass_paket_id, "
                          "anlass_text, nachweis_id, gebucht, team_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (z["id"], p["id"], d.isoformat(), platz[0], platz[1], art, aufgabe_id, paket_id, text,
                           versuch["nachweis_id"] if versuch else None, db.jetzt(), team["id"] if team else None)).lastrowid
        tid = tid or neu
        db.ereignis(con, schueler["klasse_id"], p["id"], "schueler", "Schüler", "termin_gebucht", datum=d.isoformat(), beginn=platz[0],
                    terminart=art, aufgabe_id=aufgabe_id, team=bool(team))
    if versuch:
        con.execute("UPDATE versuch SET termin_id = ? WHERE id = ?", (tid, versuch["id"]))
    return tid


def _gleiche_termine(con, t):
    """Ein Teamtermin besteht aus einer Zeile je Mitglied: alle Zeilen desselben Teams zur selben Zeit."""
    if not t["team_id"]:
        return [t]
    return con.execute("SELECT * FROM termin WHERE team_id = ? AND zeitfenster_id = ? AND datum = ? AND beginn = ? AND abgesagt IS NULL",
                       (t["team_id"], t["zeitfenster_id"], t["datum"], t["beginn"])).fetchall()


def teamtermin_plaetze(con, konto, team_id, heute=None, jetzt_hhmm=None):
    t = con.execute("SELECT * FROM lernteam WHERE id = ? AND status = 'aktiv'", (team_id,)).fetchone()
    if t is None:
        raise TerminFehler("Dieses Team gibt es nicht (mehr).")
    klassen.pruefen(con, t["klasse_id"], konto, "aendern")
    m = teams.mitglieder(con, team_id)
    if not m:
        raise TerminFehler("Das Team hat keine Mitglieder.")
    s = con.execute("SELECT * FROM schueler WHERE id = ?", (m[0]["schueler_id"],)).fetchone()
    return freie_plaetze(con, s, "feedback", heute, jetzt_hhmm, lehrkraft_id=konto["id"])


def teamtermin_eintragen(con, konto, team_id, zeitfenster_id, datum, beginn, hinweis="", heute=None, jetzt_hhmm=None):
    """Die Lehrkraft traegt dem ganzen Team einen Termin aus ihrer Sprechzeit ein (Pflichttermin)."""
    heute = heute or db.heute()
    jetzt_hhmm = jetzt_hhmm or _jetzt_hhmm()
    t = con.execute("SELECT * FROM lernteam WHERE id = ? AND status = 'aktiv'", (team_id,)).fetchone()
    if t is None:
        raise TerminFehler("Dieses Team gibt es nicht (mehr).")
    klassen.pruefen(con, t["klasse_id"], konto, "aendern")
    z = con.execute("SELECT * FROM zeitfenster WHERE id = ? AND aktiv = 1", (zeitfenster_id,)).fetchone()
    if z is None or z["klasse_id"] != t["klasse_id"] or z["art"] != "sprech" or z["lehrkraft_id"] != konto["id"]:
        raise TerminFehler("Bitte einen Platz aus Ihrer Sprechzeit in dieser Klasse wählen.")
    try:
        d = ut.datum(datum)
    except ut.TageFehler:
        raise TerminFehler("Ungültiger Tag.")
    if d < heute or (d == heute and str(beginn) <= jetzt_hhmm):
        raise TerminFehler("Dieser Platz liegt in der Vergangenheit.")
    if d not in [x for x, tag in fenstertage(con, z, d, d) if tag and tag["status"] == "unterricht"]:
        raise TerminFehler("An diesem Tag gibt es keine Sprechzeit.")
    platz = next(((b, e) for b, e in plaetze(z) if b == beginn), None)
    if platz is None:
        raise TerminFehler("Diesen Platz gibt es nicht.")
    if beginn in _gebucht(con, z["id"], d.isoformat()):
        raise TerminFehler("Dieser Platz ist schon vergeben.")
    dienst = kalender.kollision(platz[0], platz[1], kalender.dienst_belegt(con, konto["id"], d))
    if dienst:
        raise TerminFehler("Zu dieser Zeit steht in Ihrem Dienstkalender: %s." % dienst)
    daten = teams.team_daten(con, t)
    text = "Team: %s (%s)" % (", ".join(m["vorname"] for m in daten["mitglieder"] if m["status"] == "aktiv"), daten["titel"])
    hinweis = re.sub(r"\s+", " ", str(hinweis or "")).strip()[:200]
    tid = None
    for m in teams.mitglieder(con, team_id):
        neu = con.execute("INSERT INTO termin (zeitfenster_id, schueler_id, datum, beginn, ende, art, anlass_text, gebucht, pflicht, hinweis, team_id) "
                          "VALUES (?, ?, ?, ?, ?, 'feedback', ?, ?, 1, ?, ?)",
                          (z["id"], m["schueler_id"], d.isoformat(), platz[0], platz[1], text, db.jetzt(), hinweis, team_id)).lastrowid
        tid = tid or neu
        db.ereignis(con, t["klasse_id"], m["schueler_id"], "lehrkraft", konto["kuerzel"], "teamtermin", datum=d.isoformat(), beginn=platz[0])
    return tid


def absagen_schueler(con, schueler, termin_id, heute=None):
    heute = heute or db.heute()
    t = con.execute("SELECT * FROM termin WHERE id = ? AND schueler_id = ? AND abgesagt IS NULL", (termin_id, schueler["id"])).fetchone()
    if t is None:
        raise TerminFehler("Diesen Termin gibt es nicht (mehr).")
    if t["pflicht"]:
        raise TerminFehler("Diesen Termin hat deine Lehrkraft eingetragen. Absagen oder verlegen geht nur über sie.")
    if t["datum"] <= heute.isoformat():
        raise TerminFehler("Absagen geht nur bis zum Vortag. Bitte sprich deine Lehrkraft an.")
    for x in _gleiche_termine(con, t):   # Teamtermin: gilt fuer alle
        con.execute("UPDATE termin SET abgesagt = ?, abgesagt_von = 'schueler' WHERE id = ?", (db.jetzt(), x["id"]))
        _versuche_loesen(con, [x["id"]])
        db.ereignis(con, schueler["klasse_id"], x["schueler_id"], "schueler", "Schüler", "termin_abgesagt", datum=t["datum"], beginn=t["beginn"])


# --- Gespraechstermin aus "Zu pruefen" ---

def _meldung_lk(con, konto, meldung_id, recht="aendern"):
    m = con.execute("SELECT m.*, s.klasse_id, s.vorname, s.nachname, a.kuerzel FROM meldung m JOIN schueler s ON s.id = m.schueler_id "
                    "JOIN aufgabe a ON a.id = m.aufgabe_id WHERE m.id = ?", (meldung_id,)).fetchone()
    if m is None:
        raise TerminFehler("Diese Meldung gibt es nicht.")
    klassen.pruefen(con, m["klasse_id"], konto, recht)
    return m


def gespraech(con, meldung_id):
    """Der eingetragene, nicht abgesagte Gespraechstermin zu einer Meldung (oder None)."""
    t = con.execute("SELECT t.*, l.name AS lehrkraft FROM termin t JOIN zeitfenster z ON z.id = t.zeitfenster_id "
                    "JOIN lehrkraft l ON l.id = z.lehrkraft_id WHERE t.meldung_id = ? AND t.abgesagt IS NULL ORDER BY t.id DESC LIMIT 1",
                    (meldung_id,)).fetchone()
    return {"id": t["id"], "datum": t["datum"], "beginn": t["beginn"], "ende": t["ende"], "lehrkraft": t["lehrkraft"], "hinweis": t["hinweis"]} if t else None


def gespraech_plaetze(con, konto, meldung_id, heute=None, jetzt_hhmm=None):
    """Freie Plaetze in den eigenen Sprechzeiten der Lehrkraft in der Klasse des Schuelers."""
    m = _meldung_lk(con, konto, meldung_id)
    s = con.execute("SELECT * FROM schueler WHERE id = ?", (m["schueler_id"],)).fetchone()
    return freie_plaetze(con, s, "feedback", heute, jetzt_hhmm, lehrkraft_id=konto["id"])


def gespraech_eintragen(con, konto, meldung_id, zeitfenster_id, datum, beginn, hinweis="", heute=None, jetzt_hhmm=None):
    heute = heute or db.heute()
    jetzt_hhmm = jetzt_hhmm or _jetzt_hhmm()
    m = _meldung_lk(con, konto, meldung_id)
    if m["status"] != "offen":
        raise TerminFehler("Über diese Meldung ist schon entschieden.")
    if gespraech(con, meldung_id):
        raise TerminFehler("Für diese Meldung ist schon ein Gespräch eingetragen. Sagen Sie es zuerst ab, um es zu verlegen.")
    z = con.execute("SELECT * FROM zeitfenster WHERE id = ? AND aktiv = 1", (zeitfenster_id,)).fetchone()
    if z is None or z["klasse_id"] != m["klasse_id"] or z["art"] != "sprech" or z["lehrkraft_id"] != konto["id"]:
        raise TerminFehler("Bitte einen Platz aus Ihrer Sprechzeit in dieser Klasse wählen.")
    try:
        d = ut.datum(datum)
    except ut.TageFehler:
        raise TerminFehler("Ungültiger Tag.")
    if d < heute or (d == heute and str(beginn) <= jetzt_hhmm):
        raise TerminFehler("Dieser Platz liegt in der Vergangenheit.")
    if d not in [x for x, t in fenstertage(con, z, d, d) if t and t["status"] == "unterricht"]:
        raise TerminFehler("An diesem Tag gibt es keine Sprechzeit.")
    platz = next(((b, e) for b, e in plaetze(z) if b == beginn), None)
    if platz is None:
        raise TerminFehler("Diesen Platz gibt es nicht.")
    if beginn in _gebucht(con, z["id"], d.isoformat()):
        raise TerminFehler("Dieser Platz ist schon vergeben.")
    dienst = kalender.kollision(platz[0], platz[1], kalender.dienst_belegt(con, konto["id"], d))
    if dienst:
        raise TerminFehler("Zu dieser Zeit steht in Ihrem Dienstkalender: %s." % dienst)
    hinweis = re.sub(r"\s+", " ", str(hinweis or "")).strip()[:200]
    tid = con.execute("INSERT INTO termin (zeitfenster_id, schueler_id, datum, beginn, ende, art, anlass_aufgabe_id, anlass_paket_id, "
                      "anlass_text, gebucht, pflicht, meldung_id, hinweis) "
                      "SELECT ?, ?, ?, ?, ?, 'feedback', a.id, a.paket_id, '', ?, 1, ?, ? FROM aufgabe a WHERE a.id = ?",
                      (z["id"], m["schueler_id"], d.isoformat(), platz[0], platz[1], db.jetzt(), meldung_id, hinweis, m["aufgabe_id"])).lastrowid
    db.ereignis(con, m["klasse_id"], m["schueler_id"], "lehrkraft", konto["kuerzel"], "gespraech", datum=d.isoformat(), beginn=platz[0],
                kuerzel=m["kuerzel"], meldung_id=meldung_id)
    if m["gruppe"]:   # Teammeldung: dasselbe Gespraech fuer den Partner
        for pm in con.execute("SELECT * FROM meldung WHERE gruppe = ? AND id != ? AND status = 'offen'", (m["gruppe"], meldung_id)).fetchall():
            if gespraech(con, pm["id"]):
                continue
            con.execute("INSERT INTO termin (zeitfenster_id, schueler_id, datum, beginn, ende, art, anlass_aufgabe_id, anlass_paket_id, "
                        "anlass_text, gebucht, pflicht, meldung_id, hinweis) "
                        "SELECT ?, ?, ?, ?, ?, 'feedback', a.id, a.paket_id, '', ?, 1, ?, ? FROM aufgabe a WHERE a.id = ?",
                        (z["id"], pm["schueler_id"], d.isoformat(), platz[0], platz[1], db.jetzt(), pm["id"], hinweis, pm["aufgabe_id"]))
            db.ereignis(con, m["klasse_id"], pm["schueler_id"], "lehrkraft", konto["kuerzel"], "gespraech", datum=d.isoformat(), beginn=platz[0],
                        kuerzel=m["kuerzel"], meldung_id=pm["id"])
    return tid
