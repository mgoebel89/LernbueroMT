"""Fertig melden, Pruefen, Rueckmeldung und Empfehlungen (Stufe D).

Ablauf (Konzept Fassung 2):
  - Der Schueler meldet eine Aufgabe "fertig" und schaetzt dabei die Kann-Aussagen dieser Aufgabe "nachher" ein.
    Die Meldung landet bei allen Lehrkraeften der Klasse im Eingang "Zu pruefen".
  - Nach dem Gespraech schreibt (oder diktiert) eine Lehrkraft aus dem Team die Rueckmeldung, setzt ihre Einschaetzung
    der Kann-Aussagen daneben, entscheidet "angenommen" oder "ueberarbeiten bis <Frist>" und empfiehlt bei Bedarf
    Aufgaben zum Wiederholen oder Vertiefen, je Empfehlung freiwillig oder verbindlich mit Frist.
  - Bis "Freigeben" ist alles ein Entwurf, den nur der Verfasser sieht. Danach sieht der Schueler Text, Einschaetzung
    und Empfehlungen; Team und Einsicht sehen alles mit dem Namen des Verfassers.
  - Bei "ueberarbeiten" gilt fuer den Schueler die neue Frist (Vorgabe: der uebernaechste Unterrichtstag). Er darf sich
    jederzeit wieder fertig melden, eine Sperre gibt es nicht.
"""
import datetime
import re

from . import db, klassen, lernplan, nachweise, teams, termine, unterrichtstage as ut

TAG = datetime.timedelta(days=1)
MAX_TEXT = 6000
MAX_EMPFEHLUNGEN = 12


class RueckmeldungFehler(Exception):
    pass


def _datum_oder_none(wert, feld):
    if not wert:
        return None
    try:
        return ut.datum(wert, feld).isoformat()
    except ut.TageFehler as f:
        raise RueckmeldungFehler(str(f))


def _stufe(wert):
    try:
        wert = int(wert)
    except (TypeError, ValueError):
        raise RueckmeldungFehler("Bitte eine Stufe von 1 bis 4 wählen.")
    if not 1 <= wert <= 4:
        raise RueckmeldungFehler("Bitte eine Stufe von 1 bis 4 wählen.")
    return wert


def _id(wert, feld="Angabe"):
    try:
        return int(wert)
    except (TypeError, ValueError):
        raise RueckmeldungFehler("Ungültige %s." % feld)


def _aufgabe(con, aufgabe_id):
    return con.execute("SELECT a.*, p.klasse_id, p.titel AS paket_titel, p.freigabe, p.archiviert FROM aufgabe a "
                       "JOIN paket p ON p.id = a.paket_id WHERE a.id = ?", (aufgabe_id,)).fetchone()


def _kann_der_aufgabe(con, aufgabe_id):
    return con.execute("SELECT k.* FROM kann_aussage k JOIN kann_aufgabe ka ON ka.kann_id = k.id "
                       "WHERE ka.aufgabe_id = ? AND k.aktiv = 1 ORDER BY k.pos, k.id", (aufgabe_id,)).fetchall()


def neue_frist_vorschlag(con, klasse_id, heute=None):
    """Vorgabe fuer "ueberarbeiten bis": der uebernaechste Unterrichtstag."""
    heute = heute or db.heute()
    tage = ut.unterrichtstage(con, klasse_id, heute + TAG, heute + 120 * TAG)
    return tage[1]["datum"] if len(tage) > 1 else (tage[0]["datum"] if tage else (heute + 14 * TAG).isoformat())


# --- Schueler ---

def _log_s(con, schueler, art, **daten):
    db.ereignis(con, schueler["klasse_id"], schueler["id"], "schueler", "Schüler", art, **daten)


def fertig_melden(con, schueler, aufgabe_id, kann=None, heute=None):
    """kann: {kann_id: stufe} fuer ALLE Kann-Aussagen der Aufgabe (Einschaetzung "nachher")."""
    heute = heute or db.heute()
    a = lernplan._aufgabe_sichtbar(con, schueler, aufgabe_id, heute)
    if a["art"] == "wahl" and not con.execute("SELECT 1 FROM wahl WHERE schueler_id = ? AND aufgabe_id = ?",
                                              (schueler["id"], aufgabe_id)).fetchone():
        raise RueckmeldungFehler("Wähle die Aufgabe zuerst.")
    letzte = con.execute("SELECT status FROM meldung WHERE schueler_id = ? AND aufgabe_id = ? AND status != 'zurueckgezogen' "
                         "ORDER BY id DESC LIMIT 1", (schueler["id"], aufgabe_id)).fetchone()
    if letzte and letzte[0] == "offen":
        raise RueckmeldungFehler("%s ist schon fertig gemeldet." % a["kuerzel"])
    if letzte and letzte[0] == "angenommen":
        raise RueckmeldungFehler("%s ist schon angenommen." % a["kuerzel"])
    werte = {}
    for k in _kann_der_aufgabe(con, aufgabe_id):
        roh = (kann or {}).get(str(k["id"]), (kann or {}).get(k["id"]))
        if roh is None:
            raise RueckmeldungFehler("Bitte schätze zuerst alle Kann-Aussagen dieser Aufgabe ein.")
        werte[k["id"]] = (_stufe(roh), k["kuerzel"])
    for kid, (stufe, _) in werte.items():
        con.execute("INSERT INTO kann_einschaetzung (schueler_id, kann_id, art, stufe, zeit) VALUES (?, ?, 'nachher', ?, ?) "
                    "ON CONFLICT (schueler_id, kann_id, art) DO UPDATE SET stufe = excluded.stufe, zeit = excluded.zeit",
                    (schueler["id"], kid, stufe, db.jetzt()))
    mid = con.execute("INSERT INTO meldung (schueler_id, aufgabe_id, zeit) VALUES (?, ?, ?)",
                      (schueler["id"], aufgabe_id, db.jetzt())).lastrowid
    _log_s(con, schueler, "fertig", aufgabe_id=aufgabe_id, kuerzel=a["kuerzel"], meldung_id=mid,
           kann=[{"kuerzel": k, "stufe": s} for s, k in werte.values()])
    # Teamaufgabe: einer meldet fuer beide (die Kann-Einschaetzung bleibt je Person)
    p = teams.partner(con, schueler["id"], aufgabe_id)
    if p is not None:
        letzte_p = con.execute("SELECT status FROM meldung WHERE schueler_id = ? AND aufgabe_id = ? AND status != 'zurueckgezogen' "
                               "ORDER BY id DESC LIMIT 1", (p["id"], aufgabe_id)).fetchone()
        if not (letzte_p and letzte_p[0] in ("offen", "angenommen")):
            pid = con.execute("INSERT INTO meldung (schueler_id, aufgabe_id, zeit, gruppe) VALUES (?, ?, ?, ?)",
                              (p["id"], aufgabe_id, db.jetzt(), mid)).lastrowid
            con.execute("UPDATE meldung SET gruppe = ? WHERE id = ?", (mid, mid))
            db.ereignis(con, p["klasse_id"], p["id"], "schueler", "Schüler", "fertig", aufgabe_id=aufgabe_id, kuerzel=a["kuerzel"],
                        meldung_id=pid, team="%s %s" % (schueler["vorname"], schueler["nachname"]))
    return mid


def zurueckziehen(con, schueler, meldung_id):
    m = con.execute("SELECT m.*, a.kuerzel FROM meldung m JOIN aufgabe a ON a.id = m.aufgabe_id WHERE m.id = ? AND m.schueler_id = ?",
                    (meldung_id, schueler["id"])).fetchone()
    if m is None or m["status"] != "offen":
        raise RueckmeldungFehler("Diese Meldung lässt sich nicht mehr zurückziehen.")
    ids = [meldung_id]
    if m["gruppe"]:   # Teammeldung: fuer beide zurueckziehen
        ids = [z[0] for z in con.execute("SELECT id FROM meldung WHERE gruppe = ? AND status = 'offen'", (m["gruppe"],))]
    for i in ids:
        z = con.execute("SELECT * FROM meldung WHERE id = ?", (i,)).fetchone()
        con.execute("UPDATE meldung SET status = 'zurueckgezogen', entschieden = ? WHERE id = ?", (db.jetzt(), i))
        db.ereignis(con, schueler["klasse_id"], z["schueler_id"], "schueler", "Schüler", "fertig_zurueck", aufgabe_id=m["aufgabe_id"], kuerzel=m["kuerzel"])


def fuer_schueler(con, schueler):
    """Freigegebene Rueckmeldungen mit Empfehlungen (neueste zuerst) und die Zahl der ungelesenen."""
    aus = []
    for r in con.execute("SELECT r.*, l.name AS verfasser FROM rueckmeldung r JOIN lehrkraft l ON l.id = r.verfasser_id "
                         "WHERE r.schueler_id = ? AND r.freigegeben IS NOT NULL ORDER BY r.freigegeben DESC", (schueler["id"],)).fetchall():
        aus.append(_rueckmeldung_daten(con, r, schueler["klasse_id"]))
    lose = [lernplan.empfehlung_kurz(con, schueler["klasse_id"], z) | _aufgabe_kurz(con, z["aufgabe_id"]) for z in con.execute(
        "SELECT e.*, l.name AS verfasser FROM empfehlung e JOIN lehrkraft l ON l.id = e.verfasser_id WHERE e.schueler_id = ? "
        "AND e.rueckmeldung_id IS NULL AND e.freigegeben IS NOT NULL AND e.entfernt IS NULL ORDER BY e.id DESC", (schueler["id"],))]
    return {"rueckmeldungen": aus, "empfehlungen": lose, "ungelesen": sum(1 for r in aus if not r["gelesen"])}


def gelesen(con, schueler):
    con.execute("UPDATE rueckmeldung SET gelesen = ? WHERE schueler_id = ? AND freigegeben IS NOT NULL AND gelesen IS NULL",
                (db.jetzt(), schueler["id"]))


def empfehlung_erledigt(con, schueler, empfehlung_id, erledigt=True):
    e = con.execute("SELECT e.*, a.kuerzel FROM empfehlung e JOIN aufgabe a ON a.id = e.aufgabe_id WHERE e.id = ? AND e.schueler_id = ? "
                    "AND e.freigegeben IS NOT NULL AND e.entfernt IS NULL", (empfehlung_id, schueler["id"])).fetchone()
    if e is None:
        raise RueckmeldungFehler("Diese Empfehlung gibt es nicht.")
    con.execute("UPDATE empfehlung SET erledigt = ? WHERE id = ?", (db.jetzt() if erledigt else None, empfehlung_id))
    _log_s(con, schueler, "empfehlung_erledigt" if erledigt else "empfehlung_offen", aufgabe_id=e["aufgabe_id"], kuerzel=e["kuerzel"])


# --- Lehrkraft ---

def _schueler_lk(con, konto, schueler_id, recht="lesen"):
    s = con.execute("SELECT s.*, k.name AS klasse FROM schueler s JOIN klasse k ON k.id = s.klasse_id WHERE s.id = ?",
                    (schueler_id,)).fetchone()
    if s is None:
        raise RueckmeldungFehler("Diesen Schüler gibt es nicht.")
    klassen.pruefen(con, s["klasse_id"], konto, recht)
    return s


def _aufgabe_kurz(con, aufgabe_id):
    a = _aufgabe(con, aufgabe_id) if aufgabe_id else None
    if a is None:
        return {"aufgabe": None}
    return {"aufgabe": {"id": a["id"], "kuerzel": a["kuerzel"], "titel": a["titel"], "art": a["art"], "zusatz_art": a["zusatz_art"],
                        "moodle_link": a["moodle_link"], "paket_id": a["paket_id"], "paket": a["paket_titel"]}}


def _rueckmeldung_daten(con, r, klasse_id):
    kann = [{"kann_id": z["kann_id"], "kuerzel": z["kuerzel"], "text": z["text"], "stufe": z["stufe"]} for z in con.execute(
        "SELECT rk.kann_id, rk.stufe, k.kuerzel, k.text FROM rueckmeldung_kann rk JOIN kann_aussage k ON k.id = rk.kann_id "
        "WHERE rk.rueckmeldung_id = ? ORDER BY k.pos, k.id", (r["id"],))]
    emp = [lernplan.empfehlung_kurz(con, klasse_id, z) | _aufgabe_kurz(con, z["aufgabe_id"]) for z in con.execute(
        "SELECT e.*, l.name AS verfasser FROM empfehlung e JOIN lehrkraft l ON l.id = e.verfasser_id "
        "WHERE e.rueckmeldung_id = ? AND e.entfernt IS NULL ORDER BY e.id", (r["id"],))]
    paket = con.execute("SELECT titel FROM paket WHERE id = ?", (r["paket_id"],)).fetchone() if r["paket_id"] else None
    return {"id": r["id"], "schueler_id": r["schueler_id"], "verfasser_id": r["verfasser_id"], "verfasser": r["verfasser"],
            "meldung_id": r["meldung_id"], "termin_id": r["termin_id"], **_aufgabe_kurz(con, r["aufgabe_id"]),
            "paket_id": r["paket_id"], "paket": paket[0] if paket else None, "text": r["text"], "entscheidung": r["entscheidung"],
            "neue_frist": r["neue_frist"], "erstellt": r["erstellt"], "geaendert": r["geaendert"], "freigegeben": r["freigegeben"],
            "gelesen": r["gelesen"], "kann": kann, "empfehlungen": emp, "versuch_id": r["versuch_id"], "ergebnis": r["ergebnis"],
            "punkte": r["punkte"], "note": r["note"], "nachweis": _nachweis_kurz(con, r["versuch_id"])}


def _nachweis_kurz(con, versuch_id):
    if not versuch_id:
        return None
    v = con.execute("SELECT * FROM versuch WHERE id = ?", (versuch_id,)).fetchone()
    n = nachweise._nachweis(con, v["nachweis_id"])
    return {"id": n["id"], "titel": nachweise.nachweis_titel(n), "art": n["art"], "ergebnis": n["ergebnis"], "max_punkte": n["max_punkte"],
            "moodle_link": n["moodle_link"], "paket_id": n["paket_id"], "versuch": nachweise.versuch_daten(con, v)}


def _sichtbare_klassen(con, konto):
    return [z[0] for z in con.execute("SELECT klasse_id FROM klasse_lehrkraft kl JOIN klasse k ON k.id = kl.klasse_id "
                                      "WHERE kl.lehrkraft_id = ? AND k.archiviert = 0", (konto["id"],))]


def eingang(con, konto):
    """Offene Meldungen aller Klassen, in denen die Lehrkraft im Team oder mit Einsicht ist, aelteste zuerst."""
    ids = _sichtbare_klassen(con, konto)
    if not ids:
        return []
    platz = ",".join("?" * len(ids))
    aus = []
    for m in con.execute("SELECT m.*, s.vorname, s.nachname, s.klasse_id, k.name AS klasse, a.kuerzel, a.titel, p.titel AS paket "
                         "FROM meldung m JOIN schueler s ON s.id = m.schueler_id JOIN klasse k ON k.id = s.klasse_id "
                         "JOIN aufgabe a ON a.id = m.aufgabe_id JOIN paket p ON p.id = a.paket_id "
                         "WHERE m.status = 'offen' AND s.aktiv = 1 AND s.klasse_id IN (%s) ORDER BY m.zeit" % platz, ids).fetchall():
        kann = [{"kuerzel": z["kuerzel"], "stufe": z["stufe"]} for z in con.execute(
            "SELECT k.kuerzel, e.stufe FROM kann_aufgabe ka JOIN kann_aussage k ON k.id = ka.kann_id "
            "LEFT JOIN kann_einschaetzung e ON e.kann_id = k.id AND e.schueler_id = ? AND e.art = 'nachher' "
            "WHERE ka.aufgabe_id = ? AND k.aktiv = 1 ORDER BY k.pos", (m["schueler_id"], m["aufgabe_id"]))]
        entwurf = con.execute("SELECT id FROM rueckmeldung WHERE meldung_id = ? AND verfasser_id = ? AND freigegeben IS NULL",
                              (m["id"], konto["id"])).fetchone()
        aus.append({"meldung_id": m["id"], "zeit": m["zeit"], "schueler_id": m["schueler_id"], "name": "%s %s" % (m["vorname"], m["nachname"]),
                    "klasse_id": m["klasse_id"], "klasse": m["klasse"], "aufgabe_id": m["aufgabe_id"], "kuerzel": m["kuerzel"],
                    "titel": m["titel"], "paket": m["paket"], "kann": kann, "entwurf_id": entwurf[0] if entwurf else None,
                    "gespraech": termine.gespraech(con, m["id"]), "gruppe": m["gruppe"],
                    "darf": klassen.zugriff(con, m["klasse_id"], konto) == "team"})
    # Teammeldungen: ein Eintrag fuer beide, der Partner haengt daran
    haupt, ergebnis = {}, []
    for e in aus:
        if e["gruppe"] and e["gruppe"] in haupt:
            haupt[e["gruppe"]].setdefault("partner", []).append(e)
            haupt[e["gruppe"]]["name"] += " + " + e["name"]
            continue
        if e["gruppe"]:
            haupt[e["gruppe"]] = e
        ergebnis.append(e)
    return ergebnis


def entwuerfe(con, konto):
    return [{"id": r["id"], "schueler_id": r["schueler_id"], "name": "%s %s" % (r["vorname"], r["nachname"]), "klasse_id": r["klasse_id"],
             "geaendert": r["geaendert"], "meldung_id": r["meldung_id"], **_aufgabe_kurz(con, r["aufgabe_id"])}
            for r in con.execute("SELECT r.*, s.vorname, s.nachname, s.klasse_id FROM rueckmeldung r JOIN schueler s ON s.id = r.schueler_id "
                                 "WHERE r.verfasser_id = ? AND r.freigegeben IS NULL AND r.meldung_id IS NULL AND r.versuch_id IS NULL "
                                 "ORDER BY r.geaendert DESC",
                                 (konto["id"],))]


def _kann_stand(con, schueler_id, kann_zeilen, entwurf_id=None):
    werte = {}
    for z in con.execute("SELECT kann_id, art, stufe FROM kann_einschaetzung WHERE schueler_id = ?", (schueler_id,)):
        werte[(z[0], z[1])] = z[2]
    entwurf = {z[0]: z[1] for z in con.execute("SELECT kann_id, stufe FROM rueckmeldung_kann WHERE rueckmeldung_id = ?",
                                               (entwurf_id,))} if entwurf_id else {}
    return [{"kann_id": k["id"], "kuerzel": k["kuerzel"], "text": k["text"], "vorher": werte.get((k["id"], "vorher")),
             "nachher": werte.get((k["id"], "nachher")), "lehrkraft": entwurf.get(k["id"], werte.get((k["id"], "lehrkraft")))}
            for k in kann_zeilen]


def vorlage(con, konto, schueler_id, meldung_id=None, termin_id=None, rueckmeldung_id=None, aufgabe_id=None, versuch_id=None, heute=None,
            mit_partner=True):
    """Alles fuer das Fenster "Rueckmeldung": Schueler, Anlass (Meldung, Termin oder frei), Kann-Aussagen mit Schueler-
    und Lehrkraft-Einschaetzung, vorhandener Entwurf der Lehrkraft, waehlbare Aufgaben fuer Empfehlungen, Fristvorschlag."""
    heute = heute or db.heute()
    s = _schueler_lk(con, konto, schueler_id, "lesen")
    darf = klassen.zugriff(con, s["klasse_id"], konto) == "team"
    entwurf = None
    if rueckmeldung_id:
        r = con.execute("SELECT r.*, l.name AS verfasser FROM rueckmeldung r JOIN lehrkraft l ON l.id = r.verfasser_id "
                        "WHERE r.id = ? AND r.schueler_id = ?", (rueckmeldung_id, schueler_id)).fetchone()
        if r is None or (r["freigegeben"] is None and r["verfasser_id"] != konto["id"]):
            raise RueckmeldungFehler("Diese Rückmeldung gibt es nicht.")
        entwurf = r
        meldung_id, termin_id, aufgabe_id, versuch_id = r["meldung_id"], r["termin_id"], r["aufgabe_id"], r["versuch_id"]
    meldung = None
    if meldung_id:
        meldung = con.execute("SELECT * FROM meldung WHERE id = ? AND schueler_id = ?", (meldung_id, schueler_id)).fetchone()
        if meldung is None:
            raise RueckmeldungFehler("Diese Meldung gibt es nicht.")
        aufgabe_id = meldung["aufgabe_id"]
    termin = None
    paket_id = entwurf["paket_id"] if entwurf else None
    if termin_id:
        termin = con.execute("SELECT * FROM termin WHERE id = ? AND schueler_id = ?", (termin_id, schueler_id)).fetchone()
        if termin is None:
            raise RueckmeldungFehler("Diesen Termin gibt es nicht.")
        aufgabe_id = aufgabe_id or termin["anlass_aufgabe_id"]
        paket_id = paket_id or termin["anlass_paket_id"]
        if not versuch_id and termin["nachweis_id"]:   # Pruefungstermin: der Versuch dazu
            z = con.execute("SELECT id FROM versuch WHERE termin_id = ?", (termin["id"],)).fetchone()
            versuch_id = z[0] if z else None
        if not meldung and aufgabe_id:   # Termin zu einer Aufgabe, die gerade fertig gemeldet ist: dann gleich mit entscheiden
            meldung = con.execute("SELECT * FROM meldung WHERE schueler_id = ? AND aufgabe_id = ? AND status = 'offen' ORDER BY id DESC LIMIT 1",
                                  (schueler_id, aufgabe_id)).fetchone()
    versuch = None
    if versuch_id:
        versuch = con.execute("SELECT * FROM versuch WHERE id = ? AND schueler_id = ?", (versuch_id, schueler_id)).fetchone()
        if versuch is None:
            raise RueckmeldungFehler("Diesen Versuch gibt es nicht.")
        paket_id = nachweise._nachweis(con, versuch["nachweis_id"])["paket_id"]
        aufgabe_id = None
    if entwurf is None and darf:
        bedingung, werte = (("versuch_id = ?", (versuch["id"],)) if versuch else ("meldung_id = ?", (meldung["id"],)) if meldung
                            else ("termin_id = ?", (termin_id,)) if termin_id else (None, None))
        if bedingung:
            entwurf = con.execute("SELECT r.*, l.name AS verfasser FROM rueckmeldung r JOIN lehrkraft l ON l.id = r.verfasser_id WHERE "
                                  + bedingung + " AND r.verfasser_id = ? AND r.freigegeben IS NULL", werte + (konto["id"],)).fetchone()
    a = _aufgabe(con, aufgabe_id) if aufgabe_id else None
    if a is not None and a["klasse_id"] != s["klasse_id"]:
        raise RueckmeldungFehler("Diese Aufgabe gehört nicht zur Klasse des Schülers.")
    if a is not None:
        paket_id = a["paket_id"]
        kann_zeilen = _kann_der_aufgabe(con, a["id"])
    elif paket_id:
        kann_zeilen = con.execute("SELECT * FROM kann_aussage WHERE paket_id = ? AND aktiv = 1 ORDER BY pos, id", (paket_id,)).fetchall()
    else:
        kann_zeilen = []
    # waehlbare Aufgaben fuer Empfehlungen: alle aktiven Aufgaben der sichtbaren Pakete der Klasse, auch Zusatzaufgaben
    auswahl = []
    for p in lernplan.sichtbare_pakete(con, s["klasse_id"], heute):
        for x in con.execute("SELECT * FROM aufgabe WHERE paket_id = ? AND aktiv = 1 ORDER BY CASE art WHEN 'zusatz' THEN 1 ELSE 0 END, pos, id",
                             (p["id"],)):
            auswahl.append({"id": x["id"], "kuerzel": x["kuerzel"], "titel": x["titel"], "art": x["art"], "zusatz_art": x["zusatz_art"],
                            "paket_id": p["id"], "paket": p["titel"],
                            "kann": [z[0] for z in con.execute("SELECT k.kuerzel FROM kann_aufgabe ka JOIN kann_aussage k ON k.id = ka.kann_id "
                                                               "WHERE ka.aufgabe_id = ? AND k.aktiv = 1 ORDER BY k.pos", (x["id"],))]})
    daten = _rueckmeldung_daten(con, entwurf, s["klasse_id"]) if entwurf else None
    return {"schueler": {"id": s["id"], "vorname": s["vorname"], "nachname": s["nachname"], "klasse_id": s["klasse_id"], "klasse": s["klasse"]},
            "darf": darf, "meldung": {"id": meldung["id"], "zeit": meldung["zeit"], "status": meldung["status"],
                                      "gespraech": termine.gespraech(con, meldung["id"])} if meldung else None,
            "termin": {"id": termin["id"], "datum": termin["datum"], "beginn": termin["beginn"], "anlass_text": termin["anlass_text"]} if termin else None,
            **_aufgabe_kurz(con, a["id"] if a else None), "paket_id": paket_id,
            "kann": _kann_stand(con, schueler_id, kann_zeilen, entwurf["id"] if entwurf and not entwurf["freigegeben"] else None),
            "entwurf": daten, "auswahl": auswahl, "frist_vorschlag": neue_frist_vorschlag(con, s["klasse_id"], heute),
            "einschaetzer": con.execute("SELECT einschaetzer FROM klasse WHERE id = ?", (s["klasse_id"],)).fetchone()[0],
            "nachweis": _nachweis_kurz(con, versuch["id"]) if versuch else None,
            "partner": _partner_vorlagen(con, konto, meldung, heute) if mit_partner and meldung is not None else []}


def _partner_vorlagen(con, konto, meldung, heute):
    """Teammeldung: die Vorlagen der anderen Teammitglieder (gemeinsamer Text und Entscheidung, Kann und Empfehlungen je Person)."""
    if not meldung["gruppe"]:
        return []
    aus = []
    for m in con.execute("SELECT * FROM meldung WHERE gruppe = ? AND id != ? AND status != 'zurueckgezogen'", (meldung["gruppe"], meldung["id"])).fetchall():
        v = vorlage(con, konto, m["schueler_id"], meldung_id=m["id"], heute=heute, mit_partner=False)
        aus.append({k: v[k] for k in ("schueler", "meldung", "kann", "entwurf")})
    return aus


def _empfehlungen_pruefen(con, klasse_id, liste, heute):
    if not isinstance(liste, list) or len(liste) > MAX_EMPFEHLUNGEN:
        raise RueckmeldungFehler("Höchstens %d Empfehlungen auf einmal." % MAX_EMPFEHLUNGEN)
    aus, gesehen = [], set()
    for e in liste:
        if not isinstance(e, dict):
            raise RueckmeldungFehler("Ungültige Empfehlung.")
        aid = _id(e.get("aufgabe_id"), "Aufgabe")
        a = _aufgabe(con, aid)
        if a is None or not a["aktiv"] or a["klasse_id"] != klasse_id or a["archiviert"]:
            raise RueckmeldungFehler("Diese Aufgabe lässt sich nicht empfehlen.")
        if aid in gesehen:
            raise RueckmeldungFehler("%s ist doppelt empfohlen." % a["kuerzel"])
        gesehen.add(aid)
        verbindlich = bool(e.get("verbindlich"))
        frist = _datum_oder_none(e.get("frist"), "die Frist der Empfehlung")
        if verbindlich and not frist:
            raise RueckmeldungFehler("Eine verbindliche Empfehlung (%s) braucht eine Frist." % a["kuerzel"])
        if frist and frist < heute.isoformat():
            raise RueckmeldungFehler("Die Frist für %s liegt in der Vergangenheit." % a["kuerzel"])
        hinweis = re.sub(r"\s+", " ", str(e.get("hinweis") or "")).strip()[:160]
        aus.append((aid, 1 if verbindlich else 0, frist, hinweis, a["kuerzel"]))
    return aus


def speichern(con, konto, d, freigeben=False, heute=None):
    """Entwurf anlegen oder aendern; mit freigeben=True sofort fuer den Schueler sichtbar machen.
    d: schueler_id, id (Entwurf), meldung_id, termin_id, aufgabe_id, paket_id, text, entscheidung, neue_frist,
       kann {kann_id: stufe}, empfehlungen [{aufgabe_id, verbindlich, frist, hinweis}]"""
    heute = heute or db.heute()
    s = _schueler_lk(con, konto, _id(d.get("schueler_id"), "Schüler"), "aendern")
    rid = d.get("id")
    alt = None
    if rid:
        alt = con.execute("SELECT * FROM rueckmeldung WHERE id = ? AND schueler_id = ?", (_id(rid), s["id"])).fetchone()
        if alt is None or alt["verfasser_id"] != konto["id"]:
            raise RueckmeldungFehler("Diesen Entwurf gibt es nicht.")
        if alt["freigegeben"]:
            raise RueckmeldungFehler("Diese Rückmeldung ist schon freigegeben.")
    meldung_id = alt["meldung_id"] if alt else (_id(d["meldung_id"], "Meldung") if d.get("meldung_id") else None)
    termin_id = alt["termin_id"] if alt else (_id(d["termin_id"], "Termin") if d.get("termin_id") else None)
    aufgabe_id = alt["aufgabe_id"] if alt else (_id(d["aufgabe_id"], "Aufgabe") if d.get("aufgabe_id") else None)
    paket_id = alt["paket_id"] if alt else (_id(d["paket_id"], "Paket") if d.get("paket_id") else None)
    versuch_id = alt["versuch_id"] if alt else (_id(d["versuch_id"], "Versuch") if d.get("versuch_id") else None)
    versuch = None
    if versuch_id:
        versuch = con.execute("SELECT * FROM versuch WHERE id = ? AND schueler_id = ?", (versuch_id, s["id"])).fetchone()
        if versuch is None:
            raise RueckmeldungFehler("Diesen Versuch gibt es nicht.")
        paket_id, aufgabe_id, meldung_id = nachweise._nachweis(con, versuch["nachweis_id"])["paket_id"], None, None
    meldung = None
    if meldung_id:
        meldung = con.execute("SELECT * FROM meldung WHERE id = ? AND schueler_id = ?", (meldung_id, s["id"])).fetchone()
        if meldung is None:
            raise RueckmeldungFehler("Diese Meldung gibt es nicht.")
        aufgabe_id = meldung["aufgabe_id"]
    if termin_id and not con.execute("SELECT 1 FROM termin WHERE id = ? AND schueler_id = ?", (termin_id, s["id"])).fetchone():
        raise RueckmeldungFehler("Diesen Termin gibt es nicht.")
    a = _aufgabe(con, aufgabe_id) if aufgabe_id else None
    if aufgabe_id and (a is None or a["klasse_id"] != s["klasse_id"]):
        raise RueckmeldungFehler("Diese Aufgabe gehört nicht zur Klasse des Schülers.")
    if a is not None:
        paket_id = a["paket_id"]
    if paket_id and not con.execute("SELECT 1 FROM paket WHERE id = ? AND klasse_id = ?", (paket_id, s["klasse_id"])).fetchone():
        raise RueckmeldungFehler("Dieses Paket gehört nicht zur Klasse des Schülers.")
    text = str(d.get("text") or "").replace("\r\n", "\n").strip()
    if len(text) > MAX_TEXT:
        raise RueckmeldungFehler("Der Text ist zu lang (höchstens %d Zeichen)." % MAX_TEXT)
    entscheidung = d.get("entscheidung") or None
    if entscheidung not in (None, "angenommen", "ueberarbeiten"):
        raise RueckmeldungFehler("Ungültige Entscheidung.")
    if entscheidung and not meldung:
        raise RueckmeldungFehler("Eine Entscheidung gibt es nur zu einer fertig gemeldeten Aufgabe.")
    ergebnis = d.get("ergebnis") or None
    if ergebnis not in (None, "gelungen", "nicht"):
        raise RueckmeldungFehler("Ungültiges Ergebnis.")
    if ergebnis and not versuch:
        raise RueckmeldungFehler("Ein Ergebnis gibt es nur zu einem Gelingensnachweis.")
    punkte = note = None
    if versuch:
        n = nachweise._nachweis(con, versuch["nachweis_id"])
        if n["ergebnis"] == "punkte" and d.get("punkte") not in (None, ""):
            try:
                punkte = float(str(d["punkte"]).replace(",", "."))
            except ValueError:
                raise RueckmeldungFehler("Bitte die Punkte als Zahl angeben.")
            if not 0 <= punkte <= (n["max_punkte"] or 1000):
                raise RueckmeldungFehler("Punkte: 0 bis %s." % n["max_punkte"])
        if n["ergebnis"] == "note" and d.get("note") not in (None, ""):
            note = re.sub(r"\s+", "", str(d["note"]))[:5]
            if not re.fullmatch(r"[1-6][+-]?|[1-6],\d", note):
                raise RueckmeldungFehler("Note wie 2, 2+ oder 2,3 angeben.")
    neue_frist = _datum_oder_none(d.get("neue_frist"), "die neue Frist") if entscheidung == "ueberarbeiten" or ergebnis == "nicht" else None
    kann_erlaubt = {k["id"] for k in (_kann_der_aufgabe(con, a["id"]) if a else con.execute(
        "SELECT id FROM kann_aussage WHERE paket_id = ? AND aktiv = 1", (paket_id,)).fetchall() if paket_id else [])}
    kann = {}
    for kid, stufe in (d.get("kann") or {}).items():
        kid = _id(kid, "Kann-Aussage")
        if kid not in kann_erlaubt:
            raise RueckmeldungFehler("Diese Kann-Aussage gehört nicht zur Rückmeldung.")
        if stufe not in (None, ""):
            kann[kid] = _stufe(stufe)
    empfehlungen = _empfehlungen_pruefen(con, s["klasse_id"], d.get("empfehlungen") or [], heute)
    if freigeben:
        if meldung and meldung["status"] == "offen" and not entscheidung:
            raise RueckmeldungFehler("Bitte entscheiden: angenommen oder überarbeiten.")
        if meldung and meldung["status"] != "offen" and entscheidung:
            raise RueckmeldungFehler("Über diese Meldung ist schon entschieden (oder sie wurde zurückgezogen).")
        if entscheidung == "ueberarbeiten" and not neue_frist:
            raise RueckmeldungFehler("Bitte eine neue Frist für die Überarbeitung setzen.")
        if neue_frist and neue_frist < heute.isoformat():
            raise RueckmeldungFehler("Die neue Frist liegt in der Vergangenheit.")
        if versuch and versuch["status"] not in nachweise.OFFEN:
            raise RueckmeldungFehler("Dieser Versuch ist schon abgeschlossen (oder zurückgezogen).")
        if versuch and not ergebnis:
            raise RueckmeldungFehler("Bitte das Ergebnis wählen: gelungen oder noch nicht gelungen.")
        if ergebnis == "nicht" and not neue_frist:
            raise RueckmeldungFehler("Bitte eine neue Frist setzen.")
        if not text and not empfehlungen and not entscheidung and not ergebnis:
            raise RueckmeldungFehler("Die Rückmeldung ist leer.")
    jetzt = db.jetzt()
    if alt:
        rid = alt["id"]
        con.execute("UPDATE rueckmeldung SET text = ?, entscheidung = ?, neue_frist = ?, ergebnis = ?, punkte = ?, note = ?, geaendert = ? "
                    "WHERE id = ?", (text, entscheidung, neue_frist, ergebnis, punkte, note, jetzt, rid))
    else:
        rid = con.execute("INSERT INTO rueckmeldung (schueler_id, verfasser_id, meldung_id, termin_id, aufgabe_id, paket_id, text, "
                          "entscheidung, neue_frist, erstellt, geaendert, versuch_id, ergebnis, punkte, note) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (s["id"], konto["id"], meldung["id"] if meldung else None, termin_id, aufgabe_id, paket_id, text,
                           entscheidung, neue_frist, jetzt, jetzt, versuch_id, ergebnis, punkte, note)).lastrowid
    con.execute("DELETE FROM rueckmeldung_kann WHERE rueckmeldung_id = ?", (rid,))
    con.executemany("INSERT INTO rueckmeldung_kann (rueckmeldung_id, kann_id, stufe) VALUES (?, ?, ?)", [(rid, k, v) for k, v in kann.items()])
    con.execute("DELETE FROM empfehlung WHERE rueckmeldung_id = ? AND freigegeben IS NULL", (rid,))
    con.executemany("INSERT INTO empfehlung (schueler_id, aufgabe_id, rueckmeldung_id, verfasser_id, verbindlich, frist, hinweis, erstellt) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [(s["id"], e[0], rid, konto["id"], e[1], e[2], e[3], jetzt) for e in empfehlungen])
    if freigeben:
        _freigeben(con, konto, s, rid, meldung, a, entscheidung, neue_frist, kann, empfehlungen, jetzt)
        if versuch:
            nachweise.ergebnis_anwenden(con, konto, s, versuch["id"], ergebnis, punkte, note, neue_frist, jetzt)
    return rid


def speichern_team(con, konto, d, freigeben=False, heute=None):
    """Rueckmeldung zu einer Teammeldung: gemeinsamer Text, gemeinsame Entscheidung, je Person Kann und Empfehlungen.
    d["personen"]: [{schueler_id, id (Entwurf), meldung_id, kann, empfehlungen}]"""
    personen = d.get("personen")
    if not isinstance(personen, list) or not 1 <= len(personen) <= 2:
        raise RueckmeldungFehler("Ungültige Teamrückmeldung.")
    gruppen = set()
    for p in personen:
        m = con.execute("SELECT gruppe FROM meldung WHERE id = ?", (_id(p.get("meldung_id"), "Meldung"),)).fetchone()
        if m is None:
            raise RueckmeldungFehler("Diese Meldung gibt es nicht.")
        gruppen.add(m[0] or p.get("meldung_id"))
    if len(gruppen) != 1:
        raise RueckmeldungFehler("Die Meldungen gehören nicht zu einem Team.")
    ids = []
    for p in personen:
        dd = {k: v for k, v in d.items() if k != "personen"}
        dd.update(schueler_id=p.get("schueler_id"), id=p.get("id"), meldung_id=p.get("meldung_id"), kann=p.get("kann") or {},
                  empfehlungen=p.get("empfehlungen") or [])
        ids.append(speichern(con, konto, dd, freigeben, heute))
    return ids


def _freigeben(con, konto, s, rid, meldung, a, entscheidung, neue_frist, kann, empfehlungen, jetzt):
    con.execute("UPDATE rueckmeldung SET freigegeben = ? WHERE id = ?", (jetzt, rid))
    con.execute("UPDATE empfehlung SET freigegeben = ? WHERE rueckmeldung_id = ?", (jetzt, rid))
    for kid, stufe in kann.items():
        con.execute("INSERT INTO kann_einschaetzung (schueler_id, kann_id, art, stufe, zeit, wer) VALUES (?, ?, 'lehrkraft', ?, ?, ?) "
                    "ON CONFLICT (schueler_id, kann_id, art) DO UPDATE SET stufe = excluded.stufe, zeit = excluded.zeit, wer = excluded.wer",
                    (s["id"], kid, stufe, jetzt, konto["kuerzel"]))
    if entscheidung:
        con.execute("UPDATE meldung SET status = ?, entschieden = ?, entschieden_von = ? WHERE id = ?",
                    (entscheidung, jetzt, konto["id"], meldung["id"]))
        if entscheidung == "ueberarbeiten":
            con.execute("INSERT INTO schueler_frist (schueler_id, aufgabe_id, frist) VALUES (?, ?, ?) "
                        "ON CONFLICT (schueler_id, aufgabe_id) DO UPDATE SET frist = excluded.frist", (s["id"], a["id"], neue_frist))
        else:
            con.execute("DELETE FROM schueler_frist WHERE schueler_id = ? AND aufgabe_id = ?", (s["id"], a["id"]))
            # fruehere Empfehlungen genau dieser Aufgabe sind damit erledigt
            con.execute("UPDATE empfehlung SET erledigt = ? WHERE schueler_id = ? AND aufgabe_id = ? AND erledigt IS NULL "
                        "AND freigegeben IS NOT NULL AND rueckmeldung_id IS NOT ?", (jetzt, s["id"], a["id"], rid))
    db.ereignis(con, s["klasse_id"], s["id"], "lehrkraft", konto["kuerzel"], "rueckmeldung", rueckmeldung_id=rid,
                aufgabe_id=a["id"] if a else None, kuerzel=a["kuerzel"] if a else None, entscheidung=entscheidung,
                neue_frist=neue_frist, empfehlungen=[{"kuerzel": e[4], "verbindlich": bool(e[1]), "frist": e[2]} for e in empfehlungen])


def verwerfen(con, konto, rid):
    r = con.execute("SELECT * FROM rueckmeldung WHERE id = ?", (rid,)).fetchone()
    if r is None or r["verfasser_id"] != konto["id"] or r["freigegeben"]:
        raise RueckmeldungFehler("Diesen Entwurf gibt es nicht.")
    con.execute("DELETE FROM rueckmeldung WHERE id = ?", (rid,))


def empfehlung_anlegen(con, konto, schueler_id, d, heute=None):
    """Empfehlung ohne Gespraechstext (z. B. aus der Schuelerseite): sofort freigegeben."""
    heute = heute or db.heute()
    s = _schueler_lk(con, konto, schueler_id, "aendern")
    e = _empfehlungen_pruefen(con, s["klasse_id"], [d], heute)[0]
    if con.execute("SELECT 1 FROM empfehlung WHERE schueler_id = ? AND aufgabe_id = ? AND freigegeben IS NOT NULL AND entfernt IS NULL "
                   "AND erledigt IS NULL", (s["id"], e[0])).fetchone():
        raise RueckmeldungFehler("%s ist schon empfohlen." % e[4])
    jetzt = db.jetzt()
    eid = con.execute("INSERT INTO empfehlung (schueler_id, aufgabe_id, verfasser_id, verbindlich, frist, hinweis, erstellt, freigegeben) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (s["id"], e[0], konto["id"], e[1], e[2], e[3], jetzt, jetzt)).lastrowid
    db.ereignis(con, s["klasse_id"], s["id"], "lehrkraft", konto["kuerzel"], "empfehlung", aufgabe_id=e[0], kuerzel=e[4],
                verbindlich=bool(e[1]), frist=e[2])
    return eid


def empfehlung_entfernen(con, konto, eid):
    e = con.execute("SELECT e.*, a.kuerzel FROM empfehlung e JOIN aufgabe a ON a.id = e.aufgabe_id WHERE e.id = ? AND e.entfernt IS NULL",
                    (eid,)).fetchone()
    if e is None:
        raise RueckmeldungFehler("Diese Empfehlung gibt es nicht.")
    s = _schueler_lk(con, konto, e["schueler_id"], "aendern")
    con.execute("UPDATE empfehlung SET entfernt = ? WHERE id = ?", (db.jetzt(), eid))
    db.ereignis(con, s["klasse_id"], s["id"], "lehrkraft", konto["kuerzel"], "empfehlung_entfernt", aufgabe_id=e["aufgabe_id"], kuerzel=e["kuerzel"])


def fuer_lehrkraft(con, konto, schueler_id):
    """Rueckmeldungen eines Schuelers fuer Team und Einsicht: alle freigegebenen (mit Verfasser) und die eigenen Entwuerfe;
    dazu alle Empfehlungen mit Stand (eingeplant, erledigt) und die Kann-Liste mit Schueler- und Lehrkraft-Sicht."""
    s = _schueler_lk(con, konto, schueler_id, "lesen")
    rm = [_rueckmeldung_daten(con, r, s["klasse_id"]) for r in con.execute(
        "SELECT r.*, l.name AS verfasser FROM rueckmeldung r JOIN lehrkraft l ON l.id = r.verfasser_id WHERE r.schueler_id = ? "
        "AND (r.freigegeben IS NOT NULL OR r.verfasser_id = ?) ORDER BY COALESCE(r.freigegeben, r.geaendert) DESC", (s["id"], konto["id"]))]
    plan = {}
    for z in con.execute("SELECT aufgabe_id, datum FROM plan WHERE schueler_id = ?", (s["id"],)):
        plan.setdefault(z[0], []).append(z[1])
    emp = []
    for z in con.execute("SELECT e.*, l.name AS verfasser FROM empfehlung e JOIN lehrkraft l ON l.id = e.verfasser_id "
                         "WHERE e.schueler_id = ? AND e.freigegeben IS NOT NULL AND e.entfernt IS NULL ORDER BY e.id DESC", (s["id"],)):
        eintrag = lernplan.empfehlung_kurz(con, s["klasse_id"], z) | _aufgabe_kurz(con, z["aufgabe_id"])
        eintrag["eingeplant"] = sorted(d for d in plan.get(z["aufgabe_id"], []) if d >= z["freigegeben"][:10])
        emp.append(eintrag)
    return {"rueckmeldungen": rm, "empfehlungen": emp, "darf": klassen.zugriff(con, s["klasse_id"], konto) == "team"}


def zaehler(con, konto):
    ids = _sichtbare_klassen(con, konto)
    if not ids:
        return 0
    return con.execute("SELECT COUNT(*) FROM meldung m JOIN schueler s ON s.id = m.schueler_id WHERE m.status = 'offen' AND s.aktiv = 1 "
                       "AND s.klasse_id IN (%s)" % ",".join("?" * len(ids)), ids).fetchone()[0]


def json_kann(wert):
    """Kann-Werte aus dem JSON: {"12": 3} oder [{"kann_id": 12, "stufe": 3}]."""
    if isinstance(wert, list):
        return {str(x.get("kann_id")): x.get("stufe") for x in wert if isinstance(x, dict)}
    return wert if isinstance(wert, dict) else {}

