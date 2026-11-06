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
"""
import datetime
import json
import re

from . import db, klassen, unterrichtstage as ut

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
    abgesagt = con.execute("UPDATE termin SET abgesagt = ?, abgesagt_von = ? WHERE zeitfenster_id = ? AND abgesagt IS NULL AND datum >= ?",
                           (db.jetzt(), "lehrkraft:" + konto["kuerzel"], zid, heute)).rowcount
    con.execute("UPDATE zeitfenster SET aktiv = 0 WHERE id = ?", (zid,))
    db.ereignis(con, z["klasse_id"], None, "lehrkraft", konto["kuerzel"], "zeitfenster_entfernt", zeitfenster_id=zid, abgesagt=abgesagt)
    return abgesagt


def _gebucht(con, zid, datum):
    return {z["beginn"]: z for z in con.execute(
        "SELECT t.*, s.vorname, s.nachname FROM termin t JOIN schueler s ON s.id = t.schueler_id "
        "WHERE t.zeitfenster_id = ? AND t.datum = ? AND t.abgesagt IS NULL", (zid, datum))}


def _anlass_text(con, t):
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
        for d, t in fenstertage(con, z, von, bis):
            if t is None:
                continue
            gebucht = _gebucht(con, z["id"], d.isoformat())
            zeilen = []
            for i, (b, e) in enumerate(plaetze(z)):
                g = gebucht.get(b)
                zeilen.append({"beginn": b, "ende": e, "termin": {"id": g["id"], "name": "%s %s" % (g["vorname"], g["nachname"]),
                               "schueler_id": g["schueler_id"], "art": g["art"], "anlass": _anlass_text(con, g)} if g else None})
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
                         "WHERE z.lehrkraft_id = ? AND t.datum = ? AND t.abgesagt IS NULL ORDER BY t.beginn", (konto["id"], heute)):
        aus.append({"id": t["id"], "beginn": t["beginn"], "ende": t["ende"], "art": t["art"], "schueler_id": t["schueler_id"],
                    "name": "%s %s" % (t["vorname"], t["nachname"]), "klasse_id": t["klasse_id"], "klasse": t["klasse"],
                    "anlass": _anlass_text(con, t), "anlass_aufgabe_id": t["anlass_aufgabe_id"],
                    "rueckmeldung": bool(con.execute("SELECT 1 FROM rueckmeldung WHERE termin_id = ? AND freigegeben IS NOT NULL", (t["id"],)).fetchone())})
    return aus


def absagen_lehrkraft(con, konto, termin_id):
    t = con.execute("SELECT t.*, z.klasse_id FROM termin t JOIN zeitfenster z ON z.id = t.zeitfenster_id WHERE t.id = ?", (termin_id,)).fetchone()
    if t is None or t["abgesagt"]:
        raise TerminFehler("Diesen Termin gibt es nicht (mehr).")
    klassen.pruefen(con, t["klasse_id"], konto, "aendern")
    con.execute("UPDATE termin SET abgesagt = ?, abgesagt_von = ? WHERE id = ?", (db.jetzt(), "lehrkraft:" + konto["kuerzel"], termin_id))
    db.ereignis(con, t["klasse_id"], t["schueler_id"], "lehrkraft", konto["kuerzel"], "termin_abgesagt", datum=t["datum"], beginn=t["beginn"])


# --- Schueler: buchen und absagen ---

def freie_plaetze(con, schueler, art="feedback", heute=None, jetzt_hhmm=None):
    """[{datum, tag, zeitfenster_id, lehrkraft, plaetze: [beginn, ...]}] fuer die naechsten Wochen (heute nur spaetere Plaetze)."""
    heute = heute or db.heute()
    jetzt_hhmm = jetzt_hhmm or _jetzt_hhmm()
    fensterart = TERMINARTEN[art]
    aus = []
    for z in con.execute("SELECT * FROM zeitfenster WHERE klasse_id = ? AND aktiv = 1 AND art = ?", (schueler["klasse_id"], fensterart)).fetchall():
        l = con.execute("SELECT name FROM lehrkraft WHERE id = ?", (z["lehrkraft_id"],)).fetchone()
        for d, t in fenstertage(con, z, heute, heute + VORAUS_TAGE * TAG):
            if t is None or t["status"] != "unterricht":
                continue
            gebucht = _gebucht(con, z["id"], d.isoformat())
            frei = [b for b, _ in plaetze(z) if b not in gebucht and (d > heute or b > jetzt_hhmm)]
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
                    "absagen_bis": (ut.datum(t["datum"]) - TAG).isoformat(), "darf_absagen": t["datum"] > heute and not t["abgesagt"]})
    return aus


def buchen(con, schueler, zeitfenster_id, datum, beginn, art="feedback", anlass=None, heute=None, jetzt_hhmm=None):
    """anlass: {aufgabe_id} | {paket_id} | {text} (allgemein)."""
    heute = heute or db.heute()
    jetzt_hhmm = jetzt_hhmm or _jetzt_hhmm()
    if art != "feedback":
        raise TerminFehler("Fachgespräch und praktische Prüfung bucht man mit dem Gelingensnachweis.")
    z = con.execute("SELECT * FROM zeitfenster WHERE id = ? AND aktiv = 1", (zeitfenster_id,)).fetchone()
    if z is None or z["klasse_id"] != schueler["klasse_id"] or z["art"] != TERMINARTEN[art]:
        raise TerminFehler("Feedbackgespräche gibt es nur in einer Sprechzeit deiner Klasse.")
    try:
        d = ut.datum(datum)
    except ut.TageFehler:
        raise TerminFehler("Ungültiger Tag.")
    if d < heute or d > heute + VORAUS_TAGE * TAG or (d == heute and str(beginn) <= jetzt_hhmm):
        raise TerminFehler("Dieser Termin lässt sich nicht (mehr) buchen.")
    if d not in [x for x, t in fenstertage(con, z, d, d) if t and t["status"] == "unterricht"]:
        raise TerminFehler("An diesem Tag gibt es keine Sprechzeit.")
    platz = next(((b, e) for b, e in plaetze(z) if b == beginn), None)
    if platz is None:
        raise TerminFehler("Diesen Platz gibt es nicht.")
    if con.execute("SELECT 1 FROM termin WHERE schueler_id = ? AND art = 'feedback' AND abgesagt IS NULL AND (datum > ? OR "
                            "(datum = ? AND ende > ?))", (schueler["id"], heute.isoformat(), heute.isoformat(), jetzt_hhmm)).fetchone():
        raise TerminFehler("Du hast schon einen offenen Feedbacktermin. Sage ihn ab, wenn du einen anderen willst.")
    if beginn in _gebucht(con, z["id"], d.isoformat()):
        raise TerminFehler("Dieser Platz ist gerade vergeben worden. Bitte einen anderen wählen.")
    anlass = anlass if isinstance(anlass, dict) else {}
    aufgabe_id = paket_id = None
    text = re.sub(r"\s+", " ", str(anlass.get("text") or "")).strip()[:200]
    if anlass.get("aufgabe_id"):
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
    tid = con.execute("INSERT INTO termin (zeitfenster_id, schueler_id, datum, beginn, ende, art, anlass_aufgabe_id, anlass_paket_id, "
                      "anlass_text, gebucht) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (z["id"], schueler["id"], d.isoformat(), platz[0], platz[1], art, aufgabe_id, paket_id, text, db.jetzt())).lastrowid
    db.ereignis(con, schueler["klasse_id"], schueler["id"], "schueler", "Schüler", "termin_gebucht", datum=d.isoformat(), beginn=platz[0],
                terminart=art, aufgabe_id=aufgabe_id)
    return tid


def absagen_schueler(con, schueler, termin_id, heute=None):
    heute = heute or db.heute()
    t = con.execute("SELECT * FROM termin WHERE id = ? AND schueler_id = ? AND abgesagt IS NULL", (termin_id, schueler["id"])).fetchone()
    if t is None:
        raise TerminFehler("Diesen Termin gibt es nicht (mehr).")
    if t["datum"] <= heute.isoformat():
        raise TerminFehler("Absagen geht nur bis zum Vortag. Bitte sprich deine Lehrkraft an.")
    con.execute("UPDATE termin SET abgesagt = ?, abgesagt_von = 'schueler' WHERE id = ?", (db.jetzt(), termin_id))
    db.ereignis(con, schueler["klasse_id"], schueler["id"], "schueler", "Schüler", "termin_abgesagt", datum=t["datum"], beginn=t["beginn"])
