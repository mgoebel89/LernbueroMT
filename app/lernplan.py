"""Lernplan der Schueler (Stufe C): Planen ueber die Unterrichtstage, Wahl in Wahlgruppen, Tagesabschluss mit Ampel je
Aufgabe ("heute bearbeitet" = das Ist), Kann-Liste vorher, und die Sicht der Lehrkraft (Klassenmatrix, Schuelerplan).

Grundsaetze (Konzept Fassung 2):
  - Spalten sind die Unterrichtstage der Klasse. Vergangene Tage lassen sich nicht mehr umplanen (sonst stimmt Plan
    gegen Ist nicht), Ferien und Ausfalltage nicht planen.
  - Sichtbar sind freigegebene Pakete (Freigabe heute oder frueher, nicht archiviert). Zusatzaufgaben sieht ein Schueler
    erst, wenn sie ihm empfohlen werden (Stufe D).
  - Wahlgruppe "waehle 1 von 3": waehlen tauscht bei einer Wahl die bisherige aus; abwaehlen geht bis "fertig gemeldet"
    (Stufe D) und nimmt die kuenftige Planung der Aufgabe mit.
  - Faellt ein Tag aus, wird nichts automatisch verschoben: der Schueler wird gefragt; die Verschiebung traegt dann
    grund = "ausfall" und zaehlt nicht als eigene.
  - Stand je Tag und Aufgabe als Farbe nach dem Zeitplan (g im Zeitplan, y knapp, schaffe ich bis zur Frist,
    r nicht im Zeitplan, brauche Hilfe oder einen neuen Plan): direkt im Raster fuer heute und die Unterrichtstage der
    letzten 7 Tage (markieren) oder ueber den Tagesabschluss. Jede laufende Aufgabe braucht mindestens einmal pro Woche
    eine Farbe.
Jede Aenderung landet zusaetzlich im Ereignisprotokoll.
"""
import datetime

from . import db, nachweise, pakete, teams, termine, unterrichtstage as ut, zeitplan

TAG = datetime.timedelta(days=1)
AMPELN = ("g", "y", "r")
AMPEL_ALT_TAGE = 7
MARKIEREN_TAGE = 7       # so weit zurueck darf der Schueler den Stand im Raster nachtragen


class PlanFehler(Exception):
    pass


def _heute(heute):
    return heute or db.heute()


def sichtbare_pakete(con, klasse_id, heute=None):
    h = _heute(heute).isoformat()
    return con.execute("SELECT * FROM paket WHERE klasse_id = ? AND archiviert = 0 AND freigabe IS NOT NULL AND freigabe <= ? "
                       "ORDER BY freigabe, titel", (klasse_id, h)).fetchall()


def _alle_aufgaben(s):
    """Aus pakete.struktur: alle Aufgaben (ohne Zusatz) in Anzeigereihenfolge."""
    aus = []
    for e in s["ablauf"]:
        aus += [e] if e["typ"] == "aufgabe" else e["aufgaben"]
    return aus


def kann_werte(con, schueler_id):
    """{(kann_id, aufgabe_id, art): (stufe, zeit)}; aufgabe_id 0 = Paket-Ebene (Bereitmeldung, Gelingensnachweis)."""
    return {(z[0], z[1], z[2]): (z[3], z[4]) for z in con.execute(
        "SELECT kann_id, aufgabe_id, art, stufe, zeit FROM kann_einschaetzung WHERE schueler_id = ?", (schueler_id,))}


def kann_wert(werte, kann_id, art, aufgabe_id=None):
    """Stufe je Aufgabe; ohne aufgabe_id die Paket-Ebene: der Paketwert, sonst der juengste Wert aus den Aufgaben."""
    if aufgabe_id:
        w = werte.get((kann_id, aufgabe_id, art))
        return w[0] if w else None
    if (kann_id, 0, art) in werte:
        return werte[(kann_id, 0, art)][0]
    kandidaten = [v for (k, a, t), v in werte.items() if k == kann_id and t == art]
    return max(kandidaten, key=lambda v: v[1])[0] if kandidaten else None


def kann_speichern(con, schueler_id, kann_id, aufgabe_id, art, stufe, wer=""):
    con.execute("INSERT INTO kann_einschaetzung (schueler_id, kann_id, aufgabe_id, art, stufe, zeit, wer) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (schueler_id, kann_id, aufgabe_id, art) DO UPDATE SET stufe = excluded.stufe, zeit = excluded.zeit, wer = excluded.wer",
                (schueler_id, kann_id, aufgabe_id or 0, art, stufe, db.jetzt(), wer))


def kann_vorher_fehlt(con, schueler_id, aufgabe_id):
    """Kann-Aussagen der Aufgabe ohne Einschaetzung "vorher" (fuer diese Aufgabe)."""
    return [z[0] for z in con.execute(
        "SELECT ka.kann_id FROM kann_aufgabe ka JOIN kann_aussage k ON k.id = ka.kann_id WHERE ka.aufgabe_id = ? AND k.aktiv = 1 "
        "AND NOT EXISTS (SELECT 1 FROM kann_einschaetzung e WHERE e.schueler_id = ? AND e.kann_id = ka.kann_id AND e.aufgabe_id = ? AND e.art = 'vorher')",
        (aufgabe_id, schueler_id, aufgabe_id))]


VORHER_FEHLT = "Bitte schätze zuerst die Kann-Liste „vorher“ für %s ein."


def vorher_pflicht(con, schueler_id, aufgabe_id, kuerzel, fehler=None):
    """Wer mit einer Aufgabe anfaengt (planen, als bearbeitet markieren, Tag abschliessen, fertig melden), braucht vorher
    die Einschaetzung "vorher" fuer alle ihre Kann-Aussagen, auch fuer Aussagen, die die Lehrkraft spaeter verknuepft hat."""
    if kann_vorher_fehlt(con, schueler_id, aufgabe_id):
        raise (fehler or PlanFehler)(VORHER_FEHLT % kuerzel)


def _stand(con, schueler_id, klasse_id=None):
    """Plan, Ist, Wahl, letzte Meldung je Aufgabe (ohne zurueckgezogene), eigene Fristen ("ueberarbeiten bis") und
    freigegebene Empfehlungen des Schuelers."""
    plan, ist = {}, {}
    for z in con.execute("SELECT aufgabe_id, datum FROM plan WHERE schueler_id = ?", (schueler_id,)):
        plan.setdefault(z[0], set()).add(z[1])
    for z in con.execute("SELECT aufgabe_id, datum, ampel FROM ist WHERE schueler_id = ?", (schueler_id,)):
        ist.setdefault(z[0], {})[z[1]] = z[2]
    wahl = {z[0] for z in con.execute("SELECT aufgabe_id FROM wahl WHERE schueler_id = ?", (schueler_id,))}
    meld = {}
    for z in con.execute("SELECT * FROM meldung WHERE schueler_id = ? AND status != 'zurueckgezogen' ORDER BY id", (schueler_id,)):
        meld[z["aufgabe_id"]] = {"id": z["id"], "status": z["status"], "zeit": z["zeit"], "entschieden": z["entschieden"],
                                 "bestaetigt": z["bestaetigt"]}
    if klasse_id is None:
        klasse_id = con.execute("SELECT klasse_id FROM schueler WHERE id = ?", (schueler_id,)).fetchone()[0]
    sfrist = {}
    for z in con.execute("SELECT aufgabe_id, frist FROM schueler_frist WHERE schueler_id = ?", (schueler_id,)):
        sfrist[z[0]] = ut.wirksame_frist(con, klasse_id, z[1])[0]
    emp = {}
    for z in con.execute("SELECT e.*, l.name AS verfasser FROM empfehlung e JOIN lehrkraft l ON l.id = e.verfasser_id "
                         "WHERE e.schueler_id = ? AND e.freigegeben IS NOT NULL AND e.entfernt IS NULL ORDER BY e.id", (schueler_id,)):
        emp.setdefault(z["aufgabe_id"], []).append(empfehlung_kurz(con, klasse_id, z))
    return {"plan": plan, "ist": ist, "wahl": wahl, "meld": meld, "sfrist": sfrist, "emp": emp}


def empfehlung_kurz(con, klasse_id, z):
    return {"id": z["id"], "aufgabe_id": z["aufgabe_id"], "verbindlich": bool(z["verbindlich"]), "frist": z["frist"],
            "wirksam": ut.wirksame_frist(con, klasse_id, z["frist"])[0] if z["frist"] else None, "hinweis": z["hinweis"],
            "verfasser": z["verfasser"], "freigegeben": z["freigegeben"], "erledigt": z["erledigt"]}


def kann_stand(r):
    """keine | vorher (vorher fehlt) | arbeit | nachher (fertig gemeldet, nachher fehlt) | fertig | bewertet (Lehrkraft da)."""
    liste = r.get("kann_liste") or []
    if not liste:
        return "keine"
    if any(k["lehrkraft"] for k in liste) and all(k["nachher"] for k in liste):
        return "bewertet"
    if r["status"] in ("fertig", "angenommen"):
        return "fertig" if all(k["nachher"] for k in liste) else "nachher"
    if any(not k["vorher"] for k in liste):
        return "vorher"
    return "arbeit"


MELDESTATUS = {"offen": "fertig", "angenommen": "angenommen", "ueberarbeiten": "ueberarbeiten"}
LAUFEND = ("arbeit", "ueberarbeiten")


def _ampel_alt(status, letzte_ampel, meldung, heute):
    """Laufende Aufgabe ohne Ampel seit ueber einer Woche. Bei "ueberarbeiten" zaehlt die Woche ab der Entscheidung."""
    if status not in LAUFEND:
        return False
    bezug = letzte_ampel or ""
    if status == "ueberarbeiten" and meldung and meldung["entschieden"]:
        bezug = max(bezug, meldung["entschieden"][:10])
    return bool(bezug) and bezug < (heute - AMPEL_ALT_TAGE * TAG).isoformat()


def aufgaben_status(a, st, heute):
    """offen | geplant | arbeit | fertig (gemeldet, noch nicht geprueft) | angenommen | ueberarbeiten; dazu die fuer den
    Schueler wirksame Frist (eigene Frist bei "ueberarbeiten", sonst die der Aufgabe), ueber_frist (Frist vorbei ohne
    fertig) und plant_nach_frist."""
    tage_plan, tage_ist = st["plan"].get(a["id"], set()), st["ist"].get(a["id"], {})
    status = "arbeit" if tage_ist else "geplant" if tage_plan else "offen"
    m = st["meld"].get(a["id"])
    if m:
        status = MELDESTATUS[m["status"]]
    frist = st["sfrist"].get(a["id"]) or a.get("wirksam")
    if a.get("art") == "zusatz":   # Zusatzaufgaben haben nur die Frist einer verbindlichen Empfehlung
        frist = next((e["wirksam"] for e in st["emp"].get(a["id"], []) if e["verbindlich"] and not e["erledigt"]), None)
    letzte_ampel = max(tage_ist) if tage_ist else None
    erledigt = status in ("fertig", "angenommen")
    return {"status": status, "frist_schueler": frist, "eigene_frist": a["id"] in st["sfrist"],
            "ueber_frist": bool(frist and frist < heute.isoformat() and not erledigt),
            "plant_nach_frist": bool(frist and tage_plan and max(tage_plan) > frist and not erledigt),
            "ampel": tage_ist[letzte_ampel] if letzte_ampel else None, "ampel_datum": letzte_ampel,
            "ampel_alt": _ampel_alt(status, letzte_ampel, m, heute),
            "meldung": m}


def _spalten(con, klasse_id, strukturen, heute):
    """Unterrichtstage (mit Ferien und Ausfall) fuer das Raster: ab der fruehesten Freigabe (hoechstens 8 Wochen zurueck)
    bis eine Woche nach der spaetesten Frist, mindestens 8 Wochen voraus, hoechstens 30 Wochen."""
    von = heute - 56 * TAG
    freigaben = [ut.datum(s["freigabe"]["datum"]) for s in strukturen if s.get("freigabe")]
    if freigaben:
        von = max(von, min(freigaben))
    fristen = [x["wirksam"] for s in strukturen for x in _alle_aufgaben(s) + s["nachweise"] + [s["frist"]] if x.get("wirksam")]
    bis = max([heute + 56 * TAG] + [ut.datum(f) + 7 * TAG for f in fristen])
    bis = min(bis, von + 210 * TAG)
    return ut.tage(con, klasse_id, von, bis)


def zustand(con, schueler, heute=None):
    """Alles fuer die Schuelerseite: Spalten, Pakete mit Aufgaben, Stand, Hinweise, Tagesabschluss, Kann-Liste vorher.
    schueler: Zeile mit id, klasse_id (z. B. aus klassen.per_code)."""
    heute = _heute(heute)
    sid, kid = schueler["id"], schueler["klasse_id"]
    zeilen_p = sichtbare_pakete(con, kid, heute)
    strukturen = [pakete.struktur(con, p) for p in zeilen_p]
    st_alle = _stand(con, sid, kid)
    plan, ist, wahl = st_alle["plan"], st_alle["ist"], st_alle["wahl"]
    spalten = _spalten(con, kid, strukturen, heute)
    status_tag = {t["datum"]: t for t in spalten}
    kw = kann_werte(con, sid)
    aus = []
    hinweise = {"ausfall": [], "ampel_alt": []}
    ts = teams.stand_schueler(con, schueler)
    probleme = zeitplan.fuer_schueler(con, sid)
    einheiten = {}
    for p_zeile in zeilen_p:
        for k, e in teams.einheiten_paket(con, p_zeile).items():
            if k in einheiten:
                einheiten[k]["kuerzel"] += e["kuerzel"]
                continue
            einheiten[k] = {"schluessel": k, "bereich": e["bereich"], "bezug_id": e["bezug_id"], "modus": e["modus"], "modus_text": e["modus_text"],
                            "min": e["min"], "max": e["max"], "stichtag": e["stichtag"], "titel": e["titel"], "kuerzel": list(e["kuerzel"]),
                            "selbst": e["modus"] in teams.SELBST, "team": ts["teams"].get(k)}
    einheit_von = {}
    for p_zeile in zeilen_p:
        for k, e in teams.einheiten_paket(con, p_zeile).items():
            for aid in e["aufgaben"]:
                einheit_von[aid] = k
    for s in strukturen:
        pk = "stamm:%d" % kid if s["team"] and s["team"]["modus"] == "stamm" else "paket:%d" % s["id"] if s["team"] and s["team"]["modus"] != "einzeln" else None
        paket = {"id": s["id"], "titel": s["titel"], "lernfeld": s["lernfeld"], "frist": s["frist"], "zeilen": [],
                 "einheit": pk if pk in einheiten else None,
                 "kann": [], "nachweise": [{"id": n["id"], "titel": n["titel"], "art": n["art"], "frist": n["frist"], "wirksam": n["wirksam"]}
                                         for n in s["nachweise"]]}

        kann_text = {k["id"]: k for k in s["kann"]}

        def kann_liste(a):
            """Die Kann-Liste dieser Aufgabe: vorher, nachher und Lehrkraft je Aufgabe."""
            return [{"id": kid, "kuerzel": kann_text[kid]["kuerzel"], "text": kann_text[kid]["text"],
                     "vorher": kann_wert(kw, kid, "vorher", a["id"]), "nachher": kann_wert(kw, kid, "nachher", a["id"]),
                     "lehrkraft": kann_wert(kw, kid, "lehrkraft", a["id"])} for kid in a["kann"] if kid in kann_text]

        def zeile(a, gruppe=None):
            st = aufgaben_status(a, st_alle, heute)
            gewaehlt = a["art"] != "wahl" or a["id"] in wahl
            for d in sorted(plan.get(a["id"], ())):
                t = status_tag.get(d)
                if gewaehlt and d >= heute.isoformat() and t and t["status"] in ("ausfall", "ferien"):
                    hinweise["ausfall"].append({"aufgabe_id": a["id"], "kuerzel": a["kuerzel"], "titel": a["titel"], "datum": d,
                                                "grund": t["grund"], "status": t["status"]})
            if gewaehlt and st["ampel_alt"]:
                hinweise["ampel_alt"].append({"aufgabe_id": a["id"], "kuerzel": a["kuerzel"], "titel": a["titel"]})
            return {"typ": "aufgabe", "id": a["id"], "kuerzel": a["kuerzel"], "titel": a["titel"], "art": a["art"],
                    "moodle_link": a["moodle_link"], "frist": a["frist"], "wirksam": st["frist_schueler"], "gewaehlt": gewaehlt,
                    "wahlgruppe_id": a["wahlgruppe_id"], "plan": sorted(plan.get(a["id"], ())), "ist": ist.get(a["id"], {}),
                    "kann": a["kann"], "empfehlungen": st_alle["emp"].get(a["id"], []), "zusatz_art": a.get("zusatz_art"),
                    "kann_liste": kann_liste(a), "probleme": probleme.get(a["id"], {}), "einheit": einheit_von.get(a["id"]),
                    "team": ts["teams"].get(einheit_von.get(a["id"])) if a["id"] in einheit_von else None, **st}

        for e in s["ablauf"]:
            if e["typ"] == "aufgabe":
                paket["zeilen"].append(zeile(e))
            else:
                gewaehlte = [a["kuerzel"] for a in e["aufgaben"] if a["id"] in wahl]
                gk = None
                if e["team"] and e["team"]["modus"] != "einzeln":
                    gk = "stamm:%d" % kid if e["team"]["modus"] == "stamm" else "gruppe:%d" % e["id"]
                paket["zeilen"].append({"typ": "gruppe", "id": e["id"], "buchstabe": e["buchstabe"], "titel": e["titel"],
                                        "waehlen": e["waehlen"], "anzahl": len(e["aufgaben"]), "gewaehlt": gewaehlte,
                                        "frist": e["frist"], "wirksam": e["wirksam"], "einheit": gk if gk in einheiten else None})
                paket["zeilen"] += [zeile(a, e) for a in e["aufgaben"]]
        empfohlen = [a for a in s["zusatz"] if a["id"] in st_alle["emp"]]
        if empfohlen:   # Zusatzaufgaben nur, wenn sie empfohlen sind: eigene Zeilen "Empfohlen fuer dich"
            paket["zeilen"].append({"typ": "empfohlen", "anzahl": len(empfohlen)})
            paket["zeilen"] += [zeile(a) for a in empfohlen]
        for k in s["kann"]:
            paket["kann"].append({"id": k["id"], "kuerzel": k["kuerzel"], "text": k["text"], "aufgaben_kuerzel": k["aufgaben_kuerzel"],
                                  "aufgaben": k["aufgaben"], "vorher": kann_wert(kw, k["id"], "vorher"),
                                  "nachher": kann_wert(kw, k["id"], "nachher"), "lehrkraft": kann_wert(kw, k["id"], "lehrkraft")})
        paket["nachweise"] = [nachweise.stand(con, schueler, n, paket["kann"], heute) for n in s["nachweise"]]
        for zeile_ in paket["zeilen"]:
            if zeile_["typ"] == "aufgabe":
                zeile_["kann_stand"] = kann_stand(zeile_)
        aus.append(paket)
    heute_tag = next((t for t in ut.tage(con, kid, heute, heute)), None)
    abgeschlossen = con.execute("SELECT zeit FROM abschluss WHERE schueler_id = ? AND datum = ?", (sid, heute.isoformat())).fetchone()
    bestaetigen = []
    for m in con.execute("SELECT m.*, a.kuerzel, a.titel FROM meldung m JOIN aufgabe a ON a.id = m.aufgabe_id WHERE m.schueler_id = ? "
                         "AND m.status = 'offen' AND m.bestaetigt IS NULL AND m.gruppe IS NOT NULL", (sid,)).fetchall():
        gruppe = con.execute("SELECT m.schueler_id, m.bestaetigt, s.vorname, s.nachname FROM meldung m JOIN schueler s ON s.id = m.schueler_id "
                             "WHERE m.gruppe = ? AND m.status = 'offen' ORDER BY m.id", (m["gruppe"],)).fetchall()
        von = next((g for g in gruppe if g["schueler_id"] != sid and g["bestaetigt"]), None)
        bestaetigen.append({"meldung_id": m["id"], "aufgabe_id": m["aufgabe_id"], "kuerzel": m["kuerzel"], "titel": m["titel"],
                            "von": "%s %s" % (von["vorname"], von["nachname"]) if von else "dein Team",
                            "mitglieder": [{"name": "%s %s" % (g["vorname"], g["nachname"]), "ich": g["schueler_id"] == sid,
                                            "bestaetigt": bool(g["bestaetigt"])} for g in gruppe]})
    return {"heute": heute.isoformat(), "heute_tag": heute_tag, "abgeschlossen": abgeschlossen[0] if abgeschlossen else None,
            "spalten": spalten, "pakete": aus, "hinweise": hinweise, "einladungen": ts["einladungen"], "einheiten": einheiten,
            "bestaetigen": bestaetigen}


# --- Aenderungen durch den Schueler ---

def _aufgabe_sichtbar(con, schueler, aufgabe_id, heute):
    a = con.execute("SELECT a.*, p.klasse_id, p.freigabe, p.archiviert FROM aufgabe a JOIN paket p ON p.id = a.paket_id "
                    "WHERE a.id = ? AND a.aktiv = 1", (aufgabe_id,)).fetchone()
    if a is None or a["klasse_id"] != schueler["klasse_id"] or a["archiviert"] or not a["freigabe"] or a["freigabe"] > heute.isoformat():
        raise PlanFehler("Diese Aufgabe gibt es in deinem Plan nicht.")
    if a["art"] == "zusatz" and not con.execute(
            "SELECT 1 FROM empfehlung WHERE schueler_id = ? AND aufgabe_id = ? AND freigegeben IS NOT NULL AND entfernt IS NULL",
            (schueler["id"], aufgabe_id)).fetchone():
        raise PlanFehler("Zusatzaufgaben gibt es erst, wenn sie dir empfohlen werden.")
    return a


def _log(con, schueler, art, **daten):
    db.ereignis(con, schueler["klasse_id"], schueler["id"], "schueler", "Schüler", art, **daten)


def planen(con, schueler, aufgabe_id, hinzu=(), weg=(), grund=None, heute=None, spiegeln=True):
    """Tage zur Planung einer Aufgabe hinzufuegen oder wegnehmen. grund 'ausfall': Umplanung wegen eines Ausfalltags."""
    heute = _heute(heute)
    a = _aufgabe_sichtbar(con, schueler, aufgabe_id, heute)
    if a["art"] == "wahl" and not con.execute("SELECT 1 FROM wahl WHERE schueler_id = ? AND aufgabe_id = ?",
                                              (schueler["id"], aufgabe_id)).fetchone():
        raise PlanFehler("Wähle die Aufgabe zuerst.")
    hinzu, weg = sorted(set(hinzu or ())), sorted(set(weg or ()))
    if len(hinzu) + len(weg) > 200:
        raise PlanFehler("Zu viele Tage auf einmal.")
    tage = {}
    for d in hinzu + weg:
        ut.datum(d)
    if hinzu or weg:
        alle = hinzu + weg
        tage = {t["datum"]: t for t in ut.tage(con, schueler["klasse_id"], ut.datum(min(alle)), ut.datum(max(alle)))}
    for d in hinzu + weg:
        if d < heute.isoformat():
            raise PlanFehler("Vergangene Tage lassen sich nicht mehr umplanen.")
    for d in hinzu:
        t = tage.get(d)
        if t is None:
            raise PlanFehler("Am %s ist kein Unterricht." % d)
        if not ut.findet_statt(t):
            raise PlanFehler("Am %s ist kein Unterricht (%s)." % (d, t["grund"]))
    vorher = {z[0] for z in con.execute("SELECT datum FROM plan WHERE schueler_id = ? AND aufgabe_id = ?", (schueler["id"], aufgabe_id))}
    if hinzu and grund is None:   # Ausfall und Teampartner: der Plan wird mitgeschoben, die Pflicht kommt beim Partner spaeter
        vorher_pflicht(con, schueler["id"], aufgabe_id, a["kuerzel"])
    neu = [d for d in hinzu if d not in vorher]
    raus = [d for d in weg if d in vorher]
    con.executemany("INSERT OR IGNORE INTO plan (schueler_id, aufgabe_id, datum) VALUES (?, ?, ?)", [(schueler["id"], aufgabe_id, d) for d in neu])
    con.executemany("DELETE FROM plan WHERE schueler_id = ? AND aufgabe_id = ? AND datum = ?", [(schueler["id"], aufgabe_id, d) for d in raus])
    if neu or raus:
        daten = {"aufgabe_id": aufgabe_id, "kuerzel": a["kuerzel"], "hinzu": neu, "weg": raus}
        if grund in ("ausfall", "team"):
            daten["grund"] = grund
        erstes = not vorher and neu
        _log(con, schueler, "plan_neu" if erstes else "plan", **daten)
        for p in (teams.teamkollegen(con, schueler["id"], aufgabe_id) if spiegeln else []):   # Teamaufgabe: der Plan gilt fuer alle
            try:
                planen(con, p, aufgabe_id, hinzu=neu, weg=raus, grund="team", heute=heute, spiegeln=False)
            except PlanFehler:
                pass
    return neu, raus


def ausfall_verschieben(con, schueler, heute=None):
    """Alle kuenftigen Planungen auf Ausfall- oder Ferientagen auf den naechsten freien Unterrichtstag schieben
    (grund 'ausfall', zaehlt nicht als eigene Verschiebung). Rueckgabe: Anzahl verschobener Tage."""
    heute = _heute(heute)
    z = zustand(con, schueler, heute)
    anzahl = 0
    for h in z["hinweise"]["ausfall"]:
        belegt = {r[0] for r in con.execute("SELECT datum FROM plan WHERE schueler_id = ? AND aufgabe_id = ?", (schueler["id"], h["aufgabe_id"]))}
        naechste = [t["datum"] for t in ut.unterrichtstage(con, schueler["klasse_id"], ut.datum(h["datum"]) + TAG, ut.datum(h["datum"]) + 120 * TAG)
                    if t["datum"] not in belegt]
        planen(con, schueler, h["aufgabe_id"], hinzu=naechste[:1], weg=[h["datum"]], grund="ausfall", heute=heute)
        anzahl += 1
    return anzahl


def ausfall_entfernen(con, schueler, heute=None):
    """'Selbst neu planen': die Planungen auf Ausfalltagen wegnehmen, der Schueler plant dann selbst."""
    heute = _heute(heute)
    z = zustand(con, schueler, heute)
    for h in z["hinweise"]["ausfall"]:
        planen(con, schueler, h["aufgabe_id"], weg=[h["datum"]], grund="ausfall", heute=heute)
    return len(z["hinweise"]["ausfall"])


def waehlen(con, schueler, aufgabe_id, gewaehlt=True, heute=None, spiegeln=True):
    heute = _heute(heute)
    a = _aufgabe_sichtbar(con, schueler, aufgabe_id, heute)
    if a["art"] != "wahl":
        raise PlanFehler("Das ist keine Wahlaufgabe.")
    g = con.execute("SELECT * FROM wahlgruppe WHERE id = ?", (a["wahlgruppe_id"],)).fetchone()
    andere = [z[0] for z in con.execute("SELECT w.aufgabe_id FROM wahl w JOIN aufgabe a ON a.id = w.aufgabe_id "
                                        "WHERE w.schueler_id = ? AND a.wahlgruppe_id = ? AND a.aktiv = 1", (schueler["id"], g["id"]))]
    if gewaehlt:
        if aufgabe_id in andere:
            return
        if len(andere) >= g["waehlen"]:
            if g["waehlen"] != 1:
                raise PlanFehler("Du hast schon %d gewählt. Wähle erst eine ab." % g["waehlen"])
            waehlen(con, schueler, andere[0], False, heute, spiegeln)   # "1 von 3": die bisherige wird getauscht
        con.execute("INSERT INTO wahl (schueler_id, aufgabe_id, zeit) VALUES (?, ?, ?)", (schueler["id"], aufgabe_id, db.jetzt()))
        _log(con, schueler, "gewaehlt", aufgabe_id=aufgabe_id, kuerzel=a["kuerzel"], gruppe=g["buchstabe"])
        for p in (teams.teamkollegen(con, schueler["id"], aufgabe_id) if spiegeln else []):   # Team: alle waehlen dieselbe Aufgabe
            try:
                waehlen(con, p, aufgabe_id, True, heute, spiegeln=False)
            except PlanFehler:
                pass
    else:
        if aufgabe_id not in andere:
            return
        if con.execute("SELECT 1 FROM meldung WHERE schueler_id = ? AND aufgabe_id = ? AND status IN ('offen', 'angenommen')",
                       (schueler["id"], aufgabe_id)).fetchone():
            raise PlanFehler("%s ist schon fertig gemeldet. Abwählen geht nur bis zum Fertigmelden." % a["kuerzel"])
        kuenftig = [z[0] for z in con.execute("SELECT datum FROM plan WHERE schueler_id = ? AND aufgabe_id = ? AND datum >= ?",
                                              (schueler["id"], aufgabe_id, heute.isoformat()))]
        con.execute("DELETE FROM plan WHERE schueler_id = ? AND aufgabe_id = ? AND datum >= ?", (schueler["id"], aufgabe_id, heute.isoformat()))
        con.execute("DELETE FROM wahl WHERE schueler_id = ? AND aufgabe_id = ?", (schueler["id"], aufgabe_id))
        _log(con, schueler, "abgewaehlt", aufgabe_id=aufgabe_id, kuerzel=a["kuerzel"], gruppe=g["buchstabe"], weg=kuenftig)
        teams.bei_abwahl(con, schueler, aufgabe_id)            # ein Team nur fuer diese Aufgabe verlaesst der Schueler
        for p in (teams.teamkollegen(con, schueler["id"], aufgabe_id) if spiegeln else []):   # Team: alle waehlen mit ab
            try:
                waehlen(con, p, aufgabe_id, False, heute, spiegeln=False)
            except PlanFehler:
                pass


def tag_abschliessen(con, schueler, eintraege, heute=None):
    """eintraege: [{aufgabe_id, ampel}] = heute bearbeitet. Nur am Unterrichtstag; ueberschreibt den heutigen Abschluss."""
    heute = _heute(heute)
    tag = next(iter(ut.tage(con, schueler["klasse_id"], heute, heute)), None)
    if tag is None or not ut.findet_statt(tag):
        raise PlanFehler("Heute ist kein Unterrichtstag.")
    werte = {}
    for e in eintraege or []:
        try:
            aid = int(e.get("aufgabe_id"))
        except (TypeError, ValueError, AttributeError):
            raise PlanFehler("Ungültige Aufgabe.")
        if e.get("ampel") not in AMPELN:
            raise PlanFehler("Bitte für jede bearbeitete Aufgabe die Ampel wählen.")
        a = _aufgabe_sichtbar(con, schueler, aid, heute)
        if a["art"] == "wahl" and not con.execute("SELECT 1 FROM wahl WHERE schueler_id = ? AND aufgabe_id = ?", (schueler["id"], aid)).fetchone():
            raise PlanFehler("Wähle die Aufgabe zuerst.")
        vorher_pflicht(con, schueler["id"], aid, a["kuerzel"])
        if e["ampel"] == "r":
            try:
                problem = zeitplan.pruefen(e.get("problem"))
            except zeitplan.ZeitplanFehler as f:
                raise PlanFehler("%s: %s" % (a["kuerzel"], f))
        else:
            problem = None
        werte[aid] = (e["ampel"], a["kuerzel"], problem)
    d = heute.isoformat()
    for z in con.execute("SELECT aufgabe_id FROM ist WHERE schueler_id = ? AND datum = ? AND ampel = 'r'", (schueler["id"], d)).fetchall():
        if not (z[0] in werte and werte[z[0]][0] == "r"):
            zeitplan.aufheben(con, schueler["id"], z[0], d)
    con.execute("DELETE FROM ist WHERE schueler_id = ? AND datum = ?", (schueler["id"], d))
    con.executemany("INSERT INTO ist (schueler_id, aufgabe_id, datum, ampel) VALUES (?, ?, ?, ?)",
                    [(schueler["id"], aid, d, w[0]) for aid, w in werte.items()])
    con.execute("INSERT INTO abschluss (schueler_id, datum, zeit) VALUES (?, ?, ?) ON CONFLICT (schueler_id, datum) DO UPDATE SET zeit = excluded.zeit",
                (schueler["id"], d, db.jetzt()))
    for aid, w in werte.items():
        if w[2]:
            _nicht_im_zeitplan(con, schueler, aid, w[1], d, w[2], heute)
    _log(con, schueler, "tagesabschluss", datum=d, bearbeitet=[{"aufgabe_id": aid, "kuerzel": w[1], "ampel": w[0]} for aid, w in werte.items()])


def _nicht_im_zeitplan(con, schueler, aufgabe_id, kuerzel, datum, problem, heute=None):
    """Rot: Grund und Hilfe speichern; "Erklaerung jetzt" stellt den Schueler in die Hilfe-Reihe (wenn heute moeglich)."""
    p = zeitplan.speichern(con, schueler, aufgabe_id, datum, problem)
    _log(con, schueler, "zeitplan_rot", aufgabe_id=aufgabe_id, kuerzel=kuerzel, datum=datum, beschreibung=zeitplan.text(p))
    if "jetzt" in p["hilfe"]:
        try:
            termine.hilfe_rufen(con, schueler, aufgabe_id, heute)
        except termine.TerminFehler:
            pass


def markieren(con, schueler, aufgabe_id, datum, ampel, heute=None, problem=None):
    """Farbe (g/y/r) einer Aufgabe an einem Tag setzen, ampel None = Markierung entfernen. Nur heute und Unterrichtstage
    der letzten 7 Tage; ein markierter Tag zaehlt als "bearbeitet" (Ist)."""
    heute = _heute(heute)
    a = _aufgabe_sichtbar(con, schueler, aufgabe_id, heute)
    if a["art"] == "wahl" and not con.execute("SELECT 1 FROM wahl WHERE schueler_id = ? AND aufgabe_id = ?", (schueler["id"], aufgabe_id)).fetchone():
        raise PlanFehler("Wähle die Aufgabe zuerst.")
    if ampel not in AMPELN + (None,):
        raise PlanFehler("Ungültige Farbe.")
    if ampel:
        vorher_pflicht(con, schueler["id"], aufgabe_id, a["kuerzel"])
    d = ut.datum(datum)
    if d > heute or d < heute - MARKIEREN_TAGE * TAG:
        raise PlanFehler("Markieren geht für heute und die letzten %d Tage." % MARKIEREN_TAGE)
    tag = next(iter(ut.tage(con, schueler["klasse_id"], d, d)), None)
    if tag is None or not ut.findet_statt(tag):
        raise PlanFehler("Am %s war kein Unterricht." % d.strftime("%d.%m."))
    if ampel == "r":
        try:
            zeitplan.pruefen(problem)
        except zeitplan.ZeitplanFehler as f:
            raise PlanFehler(str(f))
    if ampel:
        con.execute("INSERT INTO ist (schueler_id, aufgabe_id, datum, ampel) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (schueler_id, aufgabe_id, datum) DO UPDATE SET ampel = excluded.ampel",
                    (schueler["id"], aufgabe_id, d.isoformat(), ampel))
    else:
        con.execute("DELETE FROM ist WHERE schueler_id = ? AND aufgabe_id = ? AND datum = ?", (schueler["id"], aufgabe_id, d.isoformat()))
    _log(con, schueler, "markiert", aufgabe_id=aufgabe_id, kuerzel=a["kuerzel"], datum=d.isoformat(), ampel=ampel)
    if ampel == "r":
        _nicht_im_zeitplan(con, schueler, aufgabe_id, a["kuerzel"], d.isoformat(), problem, heute)
    else:
        zeitplan.aufheben(con, schueler["id"], aufgabe_id, d.isoformat())


def kann_einschaetzen(con, schueler, kann_id, stufe, art="vorher", heute=None, aufgabe_id=None):
    """Einschaetzung je Aufgabe: "vorher" (vor dem Anfangen, aendern bis zum Fertigmelden) oder "nachher" (nur fuer eine
    fertig gemeldete Aufgabe, z. B. als Teampartner nachtragen); aufgabe_id muss mit der Kann-Aussage verknuepft sein."""
    heute = _heute(heute)
    try:
        stufe = int(stufe)
    except (TypeError, ValueError):
        raise PlanFehler("Bitte eine Stufe von 1 bis 4 wählen.")
    if not 1 <= stufe <= 4 or art not in ("vorher", "nachher"):
        raise PlanFehler("Bitte eine Stufe von 1 bis 4 wählen.")
    k = con.execute("SELECT k.*, p.klasse_id, p.freigabe, p.archiviert FROM kann_aussage k JOIN paket p ON p.id = k.paket_id "
                    "WHERE k.id = ? AND k.aktiv = 1", (kann_id,)).fetchone()
    if k is None or k["klasse_id"] != schueler["klasse_id"] or k["archiviert"] or not k["freigabe"] or k["freigabe"] > heute.isoformat():
        raise PlanFehler("Diese Kann-Aussage gibt es in deinem Plan nicht.")
    try:
        aufgabe_id = int(aufgabe_id)
    except (TypeError, ValueError):
        raise PlanFehler("Bitte die Aufgabe angeben.")
    a = _aufgabe_sichtbar(con, schueler, aufgabe_id, heute)
    if not con.execute("SELECT 1 FROM kann_aufgabe WHERE kann_id = ? AND aufgabe_id = ?", (kann_id, aufgabe_id)).fetchone():
        raise PlanFehler("Diese Kann-Aussage gehört nicht zu %s." % a["kuerzel"])
    if art == "nachher" and not con.execute("SELECT 1 FROM meldung WHERE schueler_id = ? AND aufgabe_id = ? AND status IN ('offen', 'angenommen')",
                                            (schueler["id"], aufgabe_id)).fetchone():
        raise PlanFehler("„Nachher“ schätzt du ein, wenn %s fertig gemeldet ist." % a["kuerzel"])
    kann_speichern(con, schueler["id"], kann_id, aufgabe_id, art, stufe)
    _log(con, schueler, "kann_" + art, kann_id=kann_id, kuerzel=k["kuerzel"], aufgabe=a["kuerzel"], stufe=stufe)


# --- Sicht der Lehrkraft ---

def matrix(con, klasse_id, paket_id=None, heute=None):
    """Klassenmatrix: Schueler in Zeilen, Pflichtaufgaben und Wahlgruppen eines Pakets in Spalten."""
    heute = _heute(heute)
    sichtbar = sichtbare_pakete(con, klasse_id, heute)
    alle = con.execute("SELECT * FROM paket WHERE klasse_id = ? AND archiviert = 0 ORDER BY COALESCE(freigabe, '9999'), titel",
                       (klasse_id,)).fetchall()
    p = next((x for x in alle if x["id"] == paket_id), None) or (sichtbar[-1] if sichtbar else (alle[0] if alle else None))
    if p is None:
        return {"pakete": [], "paket": None, "spalten": [], "zeilen": []}
    s = pakete.struktur(con, p)
    spalten = []
    for e in s["ablauf"]:
        if e["typ"] == "aufgabe":
            spalten.append({"typ": "aufgabe", "id": e["id"], "kuerzel": e["kuerzel"], "titel": e["titel"], "wirksam": e["wirksam"]})
        else:
            spalten.append({"typ": "gruppe", "id": e["id"], "kuerzel": e["buchstabe"], "titel": e["titel"] or "Wahlgruppe " + e["buchstabe"],
                            "waehlen": e["waehlen"], "anzahl": len(e["aufgaben"]), "aufgaben": e["aufgaben"]})
    for n in s["nachweise"]:
        spalten.append({"typ": "nachweis", "id": n["id"], "kuerzel": "GN", "titel": nachweise.ART_TEXT[n["art"]] + (" · " + n["titel"] if n["titel"] else ""),
                        "art": n["art"]})
    zeilen = []
    kann_aktiv = {k["id"] for k in s["kann"]}
    team_hinweise = teams.matrix_hinweise(con, klasse_id, p["id"])
    rot_hinweise = zeitplan.offen_je_schueler(con, klasse_id)
    for sch in con.execute("SELECT * FROM schueler WHERE klasse_id = ? AND aktiv = 1 ORDER BY nachname, vorname", (klasse_id,)).fetchall():
        st_alle = _stand(con, sch["id"], klasse_id)
        wahl = st_alle["wahl"]
        kw = kann_werte(con, sch["id"])
        zellen, hinweise, ampeln, kann_hinweise = [], [], [], []
        for sp in spalten:
            if sp["typ"] == "nachweis":
                c = nachweise.matrix_zelle(con, sch["id"], sp, heute)
                zellen.append({"status": "gn-" + c["status"], "ueber_frist": False, "text": c["text"], "gruppe": True, "nachweis": True,
                               "versuch_id": c["versuch_id"], "aufgabe_id": None, "meldung_id": None})
                continue
            if sp["typ"] == "aufgabe":
                a = next(x for x in _alle_aufgaben(s) if x["id"] == sp["id"])
                st = aufgaben_status(a, st_alle, heute)
                zellen.append({"status": st["status"], "ueber_frist": st["ueber_frist"], "text": a["kuerzel"], "gruppe": False,
                               "aufgabe_id": a["id"], "meldung_id": st["meldung"]["id"] if st["meldung"] else None})
                if st["plant_nach_frist"]:
                    hinweise.append("plant %s nach der Frist" % a["kuerzel"])
            else:
                gewaehlt = [a for a in sp["aufgaben"] if a["id"] in wahl]
                if not gewaehlt:
                    zellen.append({"status": "fehlt", "ueber_frist": False, "text": "?", "gruppe": True, "aufgabe_id": None, "meldung_id": None})
                    hinweise.append("Wahlgruppe %s noch nicht gewählt" % sp["kuerzel"])
                    continue
                a = gewaehlt[0]
                st = aufgaben_status(a, st_alle, heute)
                zellen.append({"status": st["status"], "ueber_frist": st["ueber_frist"], "text": ", ".join(x["kuerzel"] for x in gewaehlt), "gruppe": True,
                               "aufgabe_id": a["id"], "meldung_id": st["meldung"]["id"] if st["meldung"] else None})
                if st["plant_nach_frist"]:
                    hinweise.append("plant %s nach der Frist" % a["kuerzel"])
            fehlt = _kann_fehlt(kw, a, kann_aktiv, st["status"])
            if fehlt:
                kann_hinweise.append("Kann-Liste %s fehlt (%s)" % (fehlt, a["kuerzel"]))
            if st["status"] in LAUFEND:
                if st["ampel_alt"]:
                    hinweise.append("Ampel %s älter als 1 Woche" % a["kuerzel"])
                else:
                    ampeln.append(st["ampel"])
        hinweise = rot_hinweise.get(sch["id"], []) + hinweise + kann_hinweise
        schlechteste = next((x for x in ("r", "y", "g") if x in ampeln), None)
        offen_emp = sum(1 for liste in st_alle["emp"].values() for e in liste if not e["erledigt"])
        zeilen.append({"id": sch["id"], "name": "%s %s" % (sch["vorname"], sch["nachname"]), "zellen": zellen, "ampel": schlechteste,
                       "empfehlungen": offen_emp, "teams": team_hinweise.get(sch["id"], []), "hinweise": hinweise,
                       "hinweis": hinweise[0] if hinweise else ("noch nichts geplant" if all(z["status"] in ("offen", "fehlt") for z in zellen if not z.get("nachweis")) else "")})
    return {"pakete": [{"id": x["id"], "titel": x["titel"], "freigabe": x["freigabe"]} for x in alle],
            "paket": {"id": p["id"], "titel": p["titel"], "freigabe": p["freigabe"]}, "spalten": [
                {k: v for k, v in sp.items() if k != "aufgaben"} for sp in spalten], "zeilen": zeilen}


def _kann_fehlt(kw, a, kann_aktiv, status):
    """Fuer die Klassenmatrix: 'vorher' (angefangen ohne vorher), 'nachher' (fertig gemeldet ohne nachher) oder None."""
    ids = [k for k in a["kann"] if k in kann_aktiv]
    if not ids or status == "offen":
        return None
    if status in ("fertig", "angenommen"):
        return "nachher" if any((k, a["id"], "nachher") not in kw for k in ids) else None
    return "vorher" if any((k, a["id"], "vorher") not in kw for k in ids) else None


def entscheidungen(con, schueler_id, grenze=200):
    """Die letzten Eintraege des Schuelers (fuer die Schuelerseite der Lehrkraft; der volle Verlauf kommt mit Stufe F)."""
    import json
    return [{"zeit": z["zeit"], "art": z["art"], "wer_art": z["wer_art"], "wer": z["wer"], "daten": json.loads(z["daten"])}
            for z in con.execute("SELECT * FROM ereignis WHERE schueler_id = ? ORDER BY id DESC LIMIT ?", (schueler_id, grenze))]
