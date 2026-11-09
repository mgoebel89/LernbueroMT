"""Gelingensnachweise (Stufe E).

Ablauf (Konzept Fassung 2):
  - Der Schueler meldet sich "bereit". Dabei schaetzt er ALLE Kann-Aussagen des Pakets "nachher" ein (Pflicht).
    Jede Bereitmeldung ist ein Versuch; alle Versuche bleiben sichtbar.
  - Moodle-Test: die Lehrkraft schaltet den Test in Moodle frei und bestaetigt das hier ("in Moodle freigeschaltet").
    Praktische Pruefung und Fachgespraech: der Schueler bucht einen Termin in einer Pruefungszeit (app/termine.py).
  - Das Ergebnis schreibt die Lehrkraft im Fenster "Rueckmeldung" (Entwurf, Diktat, Kann-Einschaetzung, Empfehlungen):
    gelungen oder noch nicht gelungen, wahlweise mit Punkten oder Note. Die Freigabe schliesst den Versuch ab.
  - Bei "noch nicht gelungen" gilt eine neue Frist (Vorgabe: der uebernaechste Unterrichtstag), dazu wahlweise
    Empfehlungen. Eine Sperre gibt es nicht: der Schueler darf sich jederzeit wieder bereit melden.
"""
from . import db, klassen, unterrichtstage as ut

OFFEN = ("bereit", "frei")
ART_TEXT = {"moodle": "Moodle-Test", "praxis": "Praktische Prüfung", "fachgespraech": "Fachgespräch"}


class NachweisFehler(Exception):
    pass


def _nachweis(con, nachweis_id):
    return con.execute("SELECT n.*, p.klasse_id, p.titel AS paket, p.freigabe, p.archiviert, p.frist AS paket_frist FROM nachweis n "
                       "JOIN paket p ON p.id = n.paket_id WHERE n.id = ?", (nachweis_id,)).fetchone()


def nachweis_titel(n):
    return ART_TEXT[n["art"]] + (" · " + n["titel"] if n["titel"] else "") + " · " + n["paket"]


def _frist(con, n, schueler_id):
    """(wirksame Frist fuer den Schueler, eigene Frist ja/nein): eigene Frist nach "noch nicht" vor Nachweis- vor Paketfrist."""
    eigen = con.execute("SELECT frist FROM nachweis_frist WHERE schueler_id = ? AND nachweis_id = ?", (schueler_id, n["id"])).fetchone()
    frist = eigen[0] if eigen else (n["frist"] or n["paket_frist"])
    return (ut.wirksame_frist(con, n["klasse_id"], frist)[0] if frist else None), bool(eigen)


def _termin(con, termin_id):
    if not termin_id:
        return None
    t = con.execute("SELECT t.*, l.name AS lehrkraft FROM termin t JOIN zeitfenster z ON z.id = t.zeitfenster_id "
                    "JOIN lehrkraft l ON l.id = z.lehrkraft_id WHERE t.id = ? AND t.abgesagt IS NULL", (termin_id,)).fetchone()
    return {"id": t["id"], "datum": t["datum"], "beginn": t["beginn"], "ende": t["ende"], "art": t["art"], "lehrkraft": t["lehrkraft"]} if t else None


def versuch_daten(con, v):
    von = con.execute("SELECT name FROM lehrkraft WHERE id = ?", (v["ergebnis_von"],)).fetchone() if v["ergebnis_von"] else None
    rm = con.execute("SELECT id, text, freigegeben FROM rueckmeldung WHERE versuch_id = ? AND freigegeben IS NOT NULL ORDER BY id DESC LIMIT 1",
                     (v["id"],)).fetchone()
    return {"id": v["id"], "nachweis_id": v["nachweis_id"], "nr": v["nr"], "bereit": v["bereit"], "status": v["status"], "frei": v["frei"],
            "termin": _termin(con, v["termin_id"]), "ergebnis_zeit": v["ergebnis_zeit"], "ergebnis_von": von[0] if von else None,
            "punkte": v["punkte"], "note": v["note"], "neue_frist": v["neue_frist"],
            "rueckmeldung_id": rm["id"] if rm else None, "text": rm["text"] if rm else ""}


def versuche(con, schueler_id, nachweis_id):
    return [versuch_daten(con, v) for v in con.execute(
        "SELECT * FROM versuch WHERE schueler_id = ? AND nachweis_id = ? AND status != 'zurueckgezogen' ORDER BY nr DESC",
        (schueler_id, nachweis_id))]


def stand(con, schueler, n, kann, heute):
    """Ein Nachweis aus Sicht des Schuelers. n: Nachweis aus pakete.struktur (mit paket), kann: Kann-Liste des Pakets
    im Schuelerstand (mit "nachher")."""
    zeile = _nachweis(con, n["id"])
    frist, eigen = _frist(con, zeile, schueler["id"])
    vs = versuche(con, schueler["id"], n["id"])
    aktuell = next((v for v in vs if v["status"] in OFFEN), None)
    gelungen = any(v["status"] == "gelungen" for v in vs)
    return {"id": n["id"], "titel": n["titel"], "art": n["art"], "art_text": ART_TEXT[n["art"]], "ergebnis": zeile["ergebnis"],
            "max_punkte": zeile["max_punkte"], "moodle_link": zeile["moodle_link"], "frist": n["frist"], "wirksam": frist, "eigene_frist": eigen,
            "ueber_frist": bool(frist and frist < heute.isoformat() and not gelungen and not aktuell),
            "kann_gesamt": len(kann), "kann_nachher": sum(1 for k in kann if k.get("nachher")),
            "versuche": vs, "aktuell": aktuell, "gelungen": gelungen, "darf_bereit": not gelungen and not aktuell,
            "status": "gelungen" if gelungen else (("termin" if aktuell["termin"] else aktuell["status"]) if aktuell
                                                     else (vs[0]["status"] if vs else "offen"))}


# --- Schueler ---

def bereit_melden(con, schueler, nachweis_id, kann=None, heute=None):
    """kann: {kann_id: stufe} fuer ALLE Kann-Aussagen des Pakets (Einschaetzung "nachher")."""
    heute = heute or db.heute()
    n = _nachweis(con, nachweis_id)
    if (n is None or not n["aktiv"] or n["klasse_id"] != schueler["klasse_id"] or n["archiviert"] or not n["freigabe"]
            or n["freigabe"] > heute.isoformat()):
        raise NachweisFehler("Diesen Gelingensnachweis gibt es in deinem Plan nicht.")
    alle = con.execute("SELECT * FROM versuch WHERE schueler_id = ? AND nachweis_id = ? AND status != 'zurueckgezogen'",
                       (schueler["id"], nachweis_id)).fetchall()
    if any(v["status"] == "gelungen" for v in alle):
        raise NachweisFehler("Dieser Gelingensnachweis ist schon gelungen.")
    if any(v["status"] in OFFEN for v in alle):
        raise NachweisFehler("Du bist schon bereit gemeldet.")
    werte = {}
    for k in con.execute("SELECT * FROM kann_aussage WHERE paket_id = ? AND aktiv = 1 ORDER BY pos, id", (n["paket_id"],)).fetchall():
        roh = (kann or {}).get(str(k["id"]), (kann or {}).get(k["id"]))
        try:
            stufe = int(roh)
        except (TypeError, ValueError):
            raise NachweisFehler("Bitte schätze zuerst alle Kann-Aussagen ein.")
        if not 1 <= stufe <= 4:
            raise NachweisFehler("Bitte eine Stufe von 1 bis 4 wählen.")
        werte[k["id"]] = (stufe, k["kuerzel"])
    from . import lernplan   # erst hier: lernplan nutzt dieses Modul
    jetzt = db.jetzt()
    for kid, (stufe, _) in werte.items():   # Paket-Ebene (aufgabe_id 0)
        lernplan.kann_speichern(con, schueler["id"], kid, 0, "nachher", stufe)
    nr = (con.execute("SELECT MAX(nr) FROM versuch WHERE schueler_id = ? AND nachweis_id = ?", (schueler["id"], nachweis_id)).fetchone()[0] or 0) + 1
    vid = con.execute("INSERT INTO versuch (schueler_id, nachweis_id, nr, bereit) VALUES (?, ?, ?, ?)",
                      (schueler["id"], nachweis_id, nr, jetzt)).lastrowid
    db.ereignis(con, schueler["klasse_id"], schueler["id"], "schueler", "Schüler", "bereit", nachweis_id=nachweis_id, versuch=nr,
                nachweisart=n["art"], paket=n["paket"], kann=[{"kuerzel": k, "stufe": s} for s, k in werte.values()])
    return vid


def zurueckziehen(con, schueler, versuch_id, heute=None):
    heute = heute or db.heute()
    v = con.execute("SELECT * FROM versuch WHERE id = ? AND schueler_id = ?", (versuch_id, schueler["id"])).fetchone()
    if v is None or v["status"] not in OFFEN:
        raise NachweisFehler("Diese Bereitmeldung lässt sich nicht mehr zurückziehen.")
    t = _termin(con, v["termin_id"])
    if t and t["datum"] <= heute.isoformat():
        raise NachweisFehler("Dein Termin ist heute. Bitte sprich deine Lehrkraft an.")
    if t:
        con.execute("UPDATE termin SET abgesagt = ?, abgesagt_von = 'schueler' WHERE id = ?", (db.jetzt(), t["id"]))
    con.execute("UPDATE versuch SET status = 'zurueckgezogen', termin_id = NULL WHERE id = ?", (versuch_id,))
    db.ereignis(con, schueler["klasse_id"], schueler["id"], "schueler", "Schüler", "bereit_zurueck", nachweis_id=v["nachweis_id"], versuch=v["nr"])


def offener_versuch(con, schueler_id, nachweis_id):
    return con.execute("SELECT * FROM versuch WHERE schueler_id = ? AND nachweis_id = ? AND status IN ('bereit', 'frei') ORDER BY id DESC LIMIT 1",
                       (schueler_id, nachweis_id)).fetchone()


# --- Lehrkraft ---

def _versuch_lk(con, konto, versuch_id, recht="lesen"):
    v = con.execute("SELECT v.*, s.klasse_id, s.vorname, s.nachname FROM versuch v JOIN schueler s ON s.id = v.schueler_id WHERE v.id = ?",
                    (versuch_id,)).fetchone()
    if v is None:
        raise NachweisFehler("Diesen Versuch gibt es nicht.")
    klassen.pruefen(con, v["klasse_id"], konto, recht)
    return v


def freischalten(con, konto, versuch_id, frei=True):
    """Moodle-Test: "in Moodle freigeschaltet" bestaetigen (oder zuruecknehmen)."""
    v = _versuch_lk(con, konto, versuch_id, "aendern")
    n = _nachweis(con, v["nachweis_id"])
    if n["art"] != "moodle":
        raise NachweisFehler("Freischalten gibt es nur beim Moodle-Test.")
    if v["status"] not in OFFEN:
        raise NachweisFehler("Dieser Versuch ist schon abgeschlossen.")
    con.execute("UPDATE versuch SET status = ?, frei = ?, frei_von = ? WHERE id = ?",
                ("frei", db.jetzt(), konto["id"], versuch_id) if frei else ("bereit", None, None, versuch_id))
    db.ereignis(con, v["klasse_id"], v["schueler_id"], "lehrkraft", konto["kuerzel"], "freigeschaltet" if frei else "freischaltung_zurueck",
                nachweis_id=v["nachweis_id"], versuch=v["nr"])


def ergebnis_anwenden(con, konto, s, versuch_id, ergebnis, punkte, note, neue_frist, jetzt):
    """Von der Freigabe der Rueckmeldung aufgerufen: schliesst den Versuch ab."""
    v = con.execute("SELECT * FROM versuch WHERE id = ?", (versuch_id,)).fetchone()
    con.execute("UPDATE versuch SET status = ?, ergebnis_zeit = ?, ergebnis_von = ?, punkte = ?, note = ?, neue_frist = ? WHERE id = ?",
                ("gelungen" if ergebnis == "gelungen" else "nicht", jetzt, konto["id"], punkte, note, neue_frist, versuch_id))
    if ergebnis == "gelungen":
        con.execute("DELETE FROM nachweis_frist WHERE schueler_id = ? AND nachweis_id = ?", (s["id"], v["nachweis_id"]))
    else:
        con.execute("INSERT INTO nachweis_frist (schueler_id, nachweis_id, frist) VALUES (?, ?, ?) "
                    "ON CONFLICT (schueler_id, nachweis_id) DO UPDATE SET frist = excluded.frist", (s["id"], v["nachweis_id"], neue_frist))
    db.ereignis(con, s["klasse_id"], s["id"], "lehrkraft", konto["kuerzel"], "nachweis_ergebnis", nachweis_id=v["nachweis_id"], versuch=v["nr"],
                ergebnis=ergebnis, punkte=punkte, note=note, neue_frist=neue_frist)


def bereit_liste(con, konto):
    """Offene Versuche aller Klassen der Lehrkraft (Team und Einsicht), aelteste zuerst."""
    aus = []
    for v in con.execute("SELECT v.*, s.vorname, s.nachname, s.klasse_id, k.name AS klasse, kl.rolle FROM versuch v "
                         "JOIN schueler s ON s.id = v.schueler_id JOIN klasse k ON k.id = s.klasse_id "
                         "JOIN klasse_lehrkraft kl ON kl.klasse_id = s.klasse_id AND kl.lehrkraft_id = ? "
                         "WHERE v.status IN ('bereit', 'frei') AND s.aktiv = 1 AND k.archiviert = 0 ORDER BY v.bereit", (konto["id"],)).fetchall():
        n = _nachweis(con, v["nachweis_id"])
        entwurf = con.execute("SELECT id FROM rueckmeldung WHERE versuch_id = ? AND verfasser_id = ? AND freigegeben IS NULL",
                              (v["id"], konto["id"])).fetchone()
        aus.append({"versuch_id": v["id"], "nr": v["nr"], "bereit": v["bereit"], "status": v["status"], "frei": v["frei"],
                    "termin": _termin(con, v["termin_id"]), "schueler_id": v["schueler_id"], "name": "%s %s" % (v["vorname"], v["nachname"]),
                    "klasse_id": v["klasse_id"], "klasse": v["klasse"], "nachweis_id": n["id"], "art": n["art"], "art_text": ART_TEXT[n["art"]],
                    "titel": n["titel"], "paket": n["paket"], "moodle_link": n["moodle_link"], "darf": v["rolle"] == "team",
                    "entwurf_id": entwurf[0] if entwurf else None})
    return aus


def fuer_lehrkraft(con, konto, schueler_id, heute=None):
    """Alle Gelingensnachweise der sichtbaren Pakete mit allen Versuchen (Schuelerseite der Lehrkraft)."""
    from . import lernplan   # erst hier: lernplan nutzt dieses Modul
    heute = heute or db.heute()
    s = con.execute("SELECT * FROM schueler WHERE id = ?", (schueler_id,)).fetchone()
    if s is None:
        raise NachweisFehler("Diesen Schüler gibt es nicht.")
    rolle = klassen.pruefen(con, s["klasse_id"], konto, "lesen")
    z = lernplan.zustand(con, s, heute)
    return {"darf": rolle == "team", "pakete": [{"id": p["id"], "titel": p["titel"], "nachweise": p["nachweise"]} for p in z["pakete"] if p["nachweise"]]}


def matrix_zelle(con, schueler_id, n, heute):
    vs = con.execute("SELECT * FROM versuch WHERE schueler_id = ? AND nachweis_id = ? AND status != 'zurueckgezogen' ORDER BY nr DESC",
                     (schueler_id, n["id"])).fetchall()
    if not vs:
        return {"status": "offen", "text": "–", "versuch_id": None}
    if any(v["status"] == "gelungen" for v in vs):
        g = next(v for v in vs if v["status"] == "gelungen")
        text = ("%g" % g["punkte"]) if g["punkte"] is not None else (g["note"] or "✓")
        return {"status": "gelungen", "text": text, "versuch_id": g["id"]}
    v = vs[0]
    if v["status"] in OFFEN:
        termin = _termin(con, v["termin_id"])
        return {"status": "termin" if termin else v["status"], "text": "T" if termin else {"bereit": "B", "frei": "M"}[v["status"]],
                "versuch_id": v["id"]}
    return {"status": "nicht", "text": "✗" + (str(len(vs)) if len(vs) > 1 else ""), "versuch_id": v["id"]}


def zaehler(con, konto):
    return con.execute("SELECT COUNT(*) FROM versuch v JOIN schueler s ON s.id = v.schueler_id JOIN klasse k ON k.id = s.klasse_id "
                       "JOIN klasse_lehrkraft kl ON kl.klasse_id = s.klasse_id AND kl.lehrkraft_id = ? "
                       "WHERE v.status IN ('bereit', 'frei') AND s.aktiv = 1 AND k.archiviert = 0", (konto["id"],)).fetchone()[0]
