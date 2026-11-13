"""Ausgaben als PDF (Stufe F), mit dem kleinen PDF-Schreiber aus app/pdf.py:

  Lernstand-Bericht je Schueler (A4 hoch): Kennzahlen aus dem Verlauf, je Paket die Aufgaben mit Stand und Frist, die
  Kann-Liste als kleine Tabelle (vorher, nachher, Lehrkraft), Gelingensnachweise mit allen Versuchen, Empfehlungen;
  danach alle freigegebenen Rueckmeldungen mit Verfasser. Entwuerfe stehen nie im Bericht.
  Berichte aller Schueler einer Klasse in einem PDF (z. B. vor dem Loeschen einer archivierten Klasse).
  Klassenuebersicht (A4 quer): die Klassenmatrix je Paket mit Stand, Ampel, offenen Empfehlungen und Hinweis.
"""
import datetime

from . import db, lernplan, pdf, unterrichtstage as ut, verlauf

MM = pdf.MM
TEXT = (0.11, 0.14, 0.2)
LEISE = pdf.LEISE
BLAU = pdf.BLAU
LINIE = (0.8, 0.82, 0.86)
HELL = (0.91, 0.95, 0.98)
STUFEN = ["muss viel üben", "brauche Hilfe", "meist allein", "kann es perfekt"]
STATUS_TEXT = {"offen": "offen", "geplant": "geplant", "arbeit": "in Arbeit", "fertig": "fertig gemeldet", "angenommen": "angenommen",
               "ueberarbeiten": "überarbeiten"}
# Farben der Klassenuebersicht wie in der Oberflaeche (Fuellung, Schrift)
ZELLE = {"offen": (None, LEISE, "-"), "geplant": ((0.91, 0.95, 0.98), BLAU, "geplant"), "arbeit": ((0.353, 0.663, 0.839), (1, 1, 1), "Arbeit"),
         "fertig": ((0.973, 0.706, 0.259), TEXT, "fertig"), "angenommen": ((0.624, 0.706, 0), TEXT, "OK"),
         "ueberarbeiten": ((0.992, 0.945, 0.863), (0.48, 0.31, 0), "überarb."), "fehlt": (None, (0.83, 0, 0.37), "Wahl?"),
         "gn-offen": (None, LEISE, "-"), "gn-bereit": ((0.482, 0.31, 0.627), (1, 1, 1), "bereit"),
         "gn-frei": ((0.482, 0.31, 0.627), (1, 1, 1), "frei"), "gn-termin": ((0.482, 0.31, 0.627), (1, 1, 1), "Termin"),
         "gn-gelungen": ((0.624, 0.706, 0), TEXT, "gelungen"), "gn-nicht": ((0.984, 0.91, 0.94), (0.83, 0, 0.37), "noch nicht")}
AMPEL = {"g": (0.624, 0.706, 0), "y": (0.973, 0.706, 0.259), "r": (0.83, 0, 0.37)}


def _tag(iso):
    if not iso:
        return ""
    d = datetime.date.fromisoformat(iso[:10])
    return "%s %s" % (ut.TAGE[d.weekday()], d.strftime("%d.%m.%Y"))


def _stufe(wert):
    return "%d %s" % (wert, STUFEN[wert - 1]) if wert else "-"


class Blatt:
    """Fliesstext und Tabellen mit Seitenumbruch."""

    def __init__(self, quer=False, rand=16):
        self.groesse = pdf.A4_QUER if quer else pdf.A4
        self.rand = rand * MM
        self.breite = self.groesse[0] - 2 * self.rand
        self.seiten = []
        self.neue_seite()

    def neue_seite(self):
        self.seite = pdf.Seite(self.groesse)
        self.seiten.append(self.seite)
        self.y = self.groesse[1] - self.rand

    def platz(self, hoehe):
        if self.y - hoehe < self.rand + 8 * MM:
            self.neue_seite()
            return True
        return False

    def abstand(self, mm):
        self.y -= mm * MM

    def text(self, s, groesse=9.5, fett=False, farbe=TEXT, einzug=0, zeilenhoehe=1.35):
        for zeile in pdf.umbrechen(s, groesse, self.breite - einzug, fett):
            self.platz(groesse * zeilenhoehe)
            self.y -= groesse * zeilenhoehe
            self.seite.text(self.rand + einzug, self.y + groesse * 0.25, zeile, groesse, fett, farbe)

    def ueberschrift(self, s, groesse=12.5):
        self.platz(groesse * 3.2)
        self.abstand(3)
        self.y -= groesse * 1.3
        self.seite.rechteck(self.rand, self.y + groesse * 0.2, 2.2 * MM, groesse * 0.75, BLAU)
        self.seite.text(self.rand + 4 * MM, self.y + groesse * 0.2, pdf.kuerzen(s, groesse, self.breite - 4 * MM, True), groesse, True, TEXT)
        self.abstand(1.5)

    def tabelle(self, spalten, zeilen, groesse=8.3, kopf=True):
        """spalten: [(Titel, Anteil)], zeilen: [[Zelle]]; Zelle = Text oder {text, fett, farbe, fuellung}."""
        summe = sum(a for _, a in spalten)
        breiten = [self.breite * a / summe for _, a in spalten]
        lh = groesse * 1.3
        innen = 1.6 * MM

        def zeile_zeichnen(zellen, ist_kopf=False):
            teile = []
            for z, b in zip(zellen, breiten):
                z = z if isinstance(z, dict) else {"text": z}
                fett = z.get("fett", ist_kopf)
                teile.append((z, pdf.umbrechen(z.get("text", ""), groesse - (0.6 if ist_kopf else 0), b - 2 * innen, fett), fett))
            hoehe = max(len(t[1]) for t in teile) * lh + 2 * innen * 0.8
            umbruch = self.platz(hoehe)
            if umbruch and kopf and not ist_kopf:
                zeile_zeichnen([t for t, _ in spalten], True)
            x = self.rand
            for (z, linien, fett), b in zip(teile, breiten):
                if ist_kopf:
                    self.seite.rechteck(x, self.y - hoehe, b, hoehe, HELL)
                elif z.get("fuellung"):
                    self.seite.rechteck(x + 0.6, self.y - hoehe + 0.6, b - 1.2, hoehe - 1.2, z["fuellung"])
                for i, l in enumerate(linien):
                    self.seite.text(x + innen, self.y - innen * 0.8 - (i + 1) * lh + groesse * 0.3, l, groesse - (0.6 if ist_kopf else 0),
                                    fett, BLAU if ist_kopf else z.get("farbe", TEXT))
                x += b
            self.y -= hoehe
            self.seite.linie(self.rand, self.y, self.rand + self.breite, self.y, LINIE, 0.5)

        if kopf:
            self.platz(lh * 4)
            zeile_zeichnen([t for t, _ in spalten], True)
        for z in zeilen:
            zeile_zeichnen(z)
        self.abstand(2)

    def fertig(self, fuss, titel):
        n = len(self.seiten)
        for i, s in enumerate(self.seiten, 1):
            s.linie(self.rand, self.rand - 2 * MM, self.groesse[0] - self.rand, self.rand - 2 * MM, LINIE, 0.5)
            s.text(self.rand, self.rand - 6 * MM, pdf.kuerzen(fuss, 7.5, self.breite - 30 * MM), 7.5, farbe=LEISE)
            seite = "Seite %d von %d" % (i, n)
            s.text(self.groesse[0] - self.rand - pdf.textbreite(seite, 7.5), self.rand - 6 * MM, seite, 7.5, farbe=LEISE)
        return pdf.dokument(self.seiten, titel)


# --- Lernstand-Bericht ---

def _schueler(con, schueler_id):
    return con.execute("SELECT s.*, k.name AS klasse, k.schuljahr FROM schueler s JOIN klasse k ON k.id = s.klasse_id WHERE s.id = ?",
                       (schueler_id,)).fetchone()


def _kann_paket(werte, kann_id):
    """Paket-Ebene fuer den Bericht: vorher = die frueheste Einschaetzung, nachher und Lehrkraft = die juengste."""
    def wahl(art, erste):
        k = [v for (kid, _, a), v in werte.items() if kid == kann_id and a == art]
        if not k:
            return None
        return (min if erste else max)(k, key=lambda v: v[1])[0]
    return wahl("vorher", True), wahl("nachher", False), wahl("lehrkraft", False)


def _aufgabe_stand(r):
    st = STATUS_TEXT.get(r["status"], r["status"])
    if r["status"] == "ueberarbeiten" and r.get("wirksam"):
        st += " bis " + _tag(r["wirksam"])[3:9]
    if r.get("ueber_frist"):
        st += " (Frist überschritten)"
    return st


def lernstand_seiten(con, schueler_id, blatt, heute=None):
    """Schreibt den Bericht eines Schuelers in blatt (ab einer neuen Seite)."""
    heute = heute or db.heute()
    s = _schueler(con, schueler_id)
    z = lernplan.zustand(con, s, heute)
    ereignisse = verlauf._ereignisse(con, s["id"])
    kz, _, _, _, _ = verlauf.kennzahlen_und_marken(con, s, ereignisse, heute)
    werte = lernplan.kann_werte(con, s["id"])
    team = ", ".join(r[0] for r in con.execute("SELECT l.name FROM klasse_lehrkraft kl JOIN lehrkraft l ON l.id = kl.lehrkraft_id "
                                               "WHERE kl.klasse_id = ? AND kl.rolle = 'team' ORDER BY l.name", (s["klasse_id"],)))
    # Kopf
    blatt.seite.rechteck(blatt.rand, blatt.y - 1.2 * MM, 10 * MM, 1.4 * MM, BLAU)
    blatt.abstand(6)
    blatt.text("Lernstand-Bericht", 9, True, BLAU)
    blatt.text("%s %s" % (s["vorname"], s["nachname"]), 17, True)
    blatt.text(" · ".join(x for x in [s["klasse"], "Schuljahr " + s["schuljahr"] if s["schuljahr"] else "", "Stand " + _tag(heute.isoformat()),
                                      "Lehrkräfte: " + team if team else ""] if x), 9, farbe=LEISE)
    blatt.abstand(3)
    p = kz["plan"]
    v = kz["verschiebungen"]
    e = kz["empfehlungen"]
    blatt.tabelle([("Plan eingehalten", 1), ("Verschiebungen", 1), ("Wahlwechsel", 1), ("Empfehlungen", 1), ("Hilfe gerufen", 0.7)], [[
        "%d von %d Unterrichtstagen%s" % (p["eingehalten"], p["tage"], ", %d teilweise" % p["teilweise"] if p["teilweise"] else ""),
        "%d%s%s" % (v["eigen"], " (" + v["text"] + ")" if v["text"] else "", ", dazu %d durch Ausfall" % v["ausfall"] if v["ausfall"] else ""),
        "%d%s" % (kz["wahlwechsel"]["anzahl"], " (" + kz["wahlwechsel"]["text"] + ")" if kz["wahlwechsel"]["text"] else ""),
        "%d (%d eingeplant, %d erledigt, %d offen)" % (e["anzahl"], e["eingeplant"], e["erledigt"], e["offen"]) if e["anzahl"] else "keine",
        "%d-mal" % kz["hilfe"]]], groesse=8)
    if not z["pakete"]:
        blatt.text("Noch kein freigegebenes Lernpaket.", 9.5, farbe=LEISE)
    for paket in z["pakete"]:
        blatt.ueberschrift(paket["titel"] + (" · " + paket["lernfeld"] if paket["lernfeld"] else ""))
        if paket["frist"] and paket["frist"].get("wirksam"):
            blatt.text("Paket-Frist " + _tag(paket["frist"]["wirksam"]), 8.5, farbe=LEISE)
        zeilen = []
        for r in paket["zeilen"]:
            if r["typ"] == "gruppe":
                zeilen.append([{"text": "Wahl %s" % r["buchstabe"], "fett": True, "farbe": BLAU},
                               {"text": (r["titel"] + " · " if r["titel"] else "") + "wähle %d von %d" % (r["waehlen"], r["anzahl"]), "farbe": BLAU},
                               {"text": "gewählt: " + ", ".join(r["gewaehlt"]) if r["gewaehlt"] else "noch nicht gewählt", "farbe": BLAU}, "", ""])
                continue
            if r["typ"] != "aufgabe" or (r["art"] == "wahl" and not r["gewaehlt"]):
                continue
            art = {"pflicht": "Pflicht", "wahl": "Wahl", "zusatz": "Empfehlung"}[r["art"]]
            zeilen.append([{"text": r["kuerzel"], "fett": True}, r["titel"] + " (" + art + ")", _aufgabe_stand(r),
                           _tag(r["wirksam"])[:9] if r.get("wirksam") else "-", str(len(r["ist"])) if r["ist"] else "-"])
        if zeilen:
            blatt.tabelle([("Kürzel", 0.6), ("Aufgabe", 3.2), ("Stand", 1.9), ("Frist", 1), ("Tage bearbeitet", 0.9)], zeilen)
        if paket["kann"]:
            kann = []
            for k in paket["kann"]:
                vorher, nachher, lk = _kann_paket(werte, k["id"])
                kann.append([{"text": k["kuerzel"], "fett": True}, k["text"], _stufe(vorher), _stufe(nachher),
                             {"text": _stufe(lk), "fett": bool(lk and nachher and abs(lk - nachher) >= 2)}])
            blatt.text("Kann-Liste (Selbsteinschätzung vorher und nachher, Einschätzung der Lehrkraft)", 8.5, True, LEISE)
            blatt.tabelle([("", 0.5), ("Ich kann ...", 3.4), ("vorher", 1.2), ("nachher", 1.2), ("Lehrkraft", 1.2)], kann, groesse=8)
        for n in paket["nachweise"]:
            titel = "Gelingensnachweis: %s%s" % (n["art_text"], " · " + n["titel"] if n["titel"] else "")
            frist = (" · Frist " + _tag(n["wirksam"]) + (" (neu)" if n["eigene_frist"] else "")) if n["wirksam"] and not n["gelungen"] else ""
            blatt.text(titel + frist, 9, True)
            erledigte = [x for x in n["versuche"] if x["status"] in ("gelungen", "nicht")]
            for x in reversed(erledigte):
                erg = "gelungen" if x["status"] == "gelungen" else "noch nicht gelungen"
                if x["punkte"] is not None:
                    erg += " (%s%s Punkte)" % (("%g" % x["punkte"]).replace(".", ","), "/%d" % n["max_punkte"] if n["max_punkte"] else "")
                elif x["note"]:
                    erg += " (Note %s)" % x["note"]
                blatt.text("%d. Versuch, %s: %s%s" % (x["nr"], _tag(x["ergebnis_zeit"]), erg, ", " + x["ergebnis_von"] if x["ergebnis_von"] else ""),
                           8.5, einzug=4 * MM)
                if x["text"]:
                    blatt.text(x["text"], 8.5, farbe=LEISE, einzug=8 * MM)
            if n["aktuell"]:
                blatt.text("%d. Versuch: bereit gemeldet am %s" % (n["aktuell"]["nr"], _tag(n["aktuell"]["bereit"])), 8.5, einzug=4 * MM)
            if not n["versuche"]:
                blatt.text("noch nicht bereit gemeldet", 8.5, farbe=LEISE, einzug=4 * MM)
        emp = [(r, x) for r in paket["zeilen"] if r["typ"] == "aufgabe" for x in r.get("empfehlungen") or []]
        if emp:
            blatt.text("Empfehlungen", 8.5, True, LEISE)
            for r, x in emp:
                blatt.text("%s %s: %s%s%s" % (r["kuerzel"], r["titel"], "verbindlich bis " + _tag(x["wirksam"] or x["frist"]) if x["verbindlich"] else "freiwillig",
                                              " · " + x["hinweis"] if x["hinweis"] else "", " · erledigt" if x["erledigt"] else ""), 8.5, einzug=4 * MM)
    rm = con.execute("SELECT r.*, l.name AS verfasser, a.kuerzel, a.titel AS aufgabe, p.titel AS paket FROM rueckmeldung r "
                     "JOIN lehrkraft l ON l.id = r.verfasser_id LEFT JOIN aufgabe a ON a.id = r.aufgabe_id LEFT JOIN paket p ON p.id = r.paket_id "
                     "WHERE r.schueler_id = ? AND r.freigegeben IS NOT NULL ORDER BY r.freigegeben", (s["id"],)).fetchall()
    blatt.ueberschrift("Rückmeldungen")
    if not rm:
        blatt.text("Noch keine Rückmeldung.", 9, farbe=LEISE)
    for r in rm:
        bezug = ("%s %s" % (r["kuerzel"], r["aufgabe"])) if r["kuerzel"] else ("Gelingensnachweis " + r["paket"] if r["versuch_id"] and r["paket"]
                                                                              else "Paket " + r["paket"] if r["paket"] else "Feedback")
        entscheidung = {"angenommen": "angenommen", "ueberarbeiten": "überarbeiten bis " + _tag(r["neue_frist"])}.get(r["entscheidung"], "")
        if r["ergebnis"]:
            entscheidung = "gelungen" if r["ergebnis"] == "gelungen" else "noch nicht gelungen"
        blatt.platz(30)
        blatt.text("%s · %s · %s%s" % (_tag(r["freigegeben"]), r["verfasser"], bezug, " · " + entscheidung if entscheidung else ""), 8.8, True)
        if r["text"]:
            blatt.text(r["text"], 8.8, einzug=4 * MM)
        blatt.abstand(1.5)
    return "%s %s · %s" % (s["vorname"], s["nachname"], s["klasse"])


def lernstand(con, schueler_id, heute=None):
    blatt = Blatt()
    fuss = lernstand_seiten(con, schueler_id, blatt, heute)
    return blatt.fertig("Lernbüro MT · Lernstand-Bericht · " + fuss, "Lernstand-Bericht " + fuss)


def lernstand_klasse(con, klasse_id, heute=None, nur_aktiv=True):
    """Berichte aller Schueler einer Klasse in einem PDF, jeder ab einer neuen Seite; die Fusszeile zaehlt je Schueler."""
    k = con.execute("SELECT name FROM klasse WHERE id = ?", (klasse_id,)).fetchone()
    seiten = []
    for s in con.execute("SELECT id FROM schueler WHERE klasse_id = ?%s ORDER BY nachname, vorname" % (" AND aktiv = 1" if nur_aktiv else ""),
                         (klasse_id,)).fetchall():
        blatt = Blatt()
        fuss = lernstand_seiten(con, s["id"], blatt, heute)
        n = len(blatt.seiten)
        for i, seite in enumerate(blatt.seiten, 1):
            seite.linie(blatt.rand, blatt.rand - 2 * MM, blatt.groesse[0] - blatt.rand, blatt.rand - 2 * MM, LINIE, 0.5)
            seite.text(blatt.rand, blatt.rand - 6 * MM, pdf.kuerzen("Lernbüro MT · Lernstand-Bericht · " + fuss, 7.5, blatt.breite - 30 * MM), 7.5, farbe=LEISE)
            t = "Seite %d von %d" % (i, n)
            seite.text(blatt.groesse[0] - blatt.rand - pdf.textbreite(t, 7.5), blatt.rand - 6 * MM, t, 7.5, farbe=LEISE)
        seiten += blatt.seiten
    if not seiten:
        seiten.append(pdf.Seite())
    return pdf.dokument(seiten, "Lernstand-Berichte " + k["name"])


# --- Klassenuebersicht ---

def klassenuebersicht(con, klasse_id, paket_id=None, heute=None):
    """Klassenmatrix als PDF, A4 quer. paket_id None: alle Pakete der Klasse (nicht archiviert), je Paket ab neuer Seite."""
    heute = heute or db.heute()
    k = con.execute("SELECT name, schuljahr FROM klasse WHERE id = ?", (klasse_id,)).fetchone()
    ids = [paket_id] if paket_id else [p["id"] for p in con.execute(
        "SELECT id FROM paket WHERE klasse_id = ? AND archiviert = 0 ORDER BY COALESCE(freigabe, '9999'), titel", (klasse_id,))]
    blatt = Blatt(quer=True, rand=12)
    erstes = True
    for pid in ids or [None]:
        m = lernplan.matrix(con, klasse_id, pid, heute)
        if not erstes:
            blatt.neue_seite()
        erstes = False
        blatt.seite.rechteck(blatt.rand, blatt.y - 1.2 * MM, 10 * MM, 1.4 * MM, BLAU)
        blatt.abstand(6)
        blatt.text("Klassenübersicht · %s%s · Stand %s" % (k["name"], " · " + k["schuljahr"] if k["schuljahr"] else "", _tag(heute.isoformat())), 9, True, BLAU)
        if not m["paket"]:
            blatt.text("Noch kein Paket.", 12, True)
            continue
        blatt.text(m["paket"]["titel"] + ("" if m["paket"]["freigabe"] else " (Entwurf)"), 15, True)
        blatt.abstand(2)
        def spaltenkopf(sp):
            if sp["typ"] == "gruppe":
                return "%s Wahl %d/%d" % (sp["kuerzel"], sp.get("waehlen", 1), sp.get("anzahl", 0))
            if sp["typ"] == "nachweis":
                return "GN " + {"moodle": "Test", "praxis": "Praxis", "fachgespraech": "Gespräch"}.get(sp.get("art"), "")
            return "%s %s" % (sp["kuerzel"], (sp["titel"] or "")[:14])
        kopf = [("Schüler", 3.2)] + [(spaltenkopf(sp), 1.25) for sp in m["spalten"]] + [("Ampel", 0.8), ("Emp.", 0.6), ("Hinweis", 3.4)]
        zeilen = []
        for r in m["zeilen"]:
            zellen = [{"text": r["name"] + (" (Team: " + ", ".join(r["teams"]) + ")" if r.get("teams") else ""), "fett": True}]
            for c in r["zellen"]:
                fuellung, farbe, text = ZELLE.get(c["status"], (None, TEXT, c["status"]))
                if c.get("gruppe") and not c.get("nachweis") and c["status"] != "fehlt":
                    text = c["text"] + " " + text
                if c.get("ueber_frist"):
                    text += " !"
                zellen.append({"text": text, "fuellung": fuellung, "farbe": farbe, "fett": c["status"] in ("fertig", "fehlt")})
            zellen.append({"text": {"g": "grün", "y": "gelb", "r": "rot"}.get(r["ampel"], "-"), "fuellung": AMPEL.get(r["ampel"]),
                           "farbe": (1, 1, 1) if r["ampel"] == "r" else TEXT})
            zellen.append(str(r["empfehlungen"]) if r["empfehlungen"] else "-")
            zellen.append({"text": r["hinweis"] or "-", "farbe": (0.83, 0, 0.37) if r["hinweis"] and r["hinweis"] != "noch nichts geplant" else LEISE})
            zeilen.append(zellen)
        blatt.tabelle(kopf, zeilen, groesse=7.6)
        blatt.text("Stand je Aufgabe: - offen · geplant · Arbeit = in Arbeit · fertig = fertig gemeldet · OK = angenommen · überarb. = überarbeiten · "
                   "Wahl? = Wahlgruppe noch nicht gewählt · ! = Frist überschritten. GN = Gelingensnachweis (bereit, frei, Termin, gelungen, noch nicht). "
                   "Ampel = schlechteste Farbe der laufenden Aufgaben, Emp. = offene Empfehlungen.", 7.2, farbe=LEISE)
    return blatt.fertig("Lernbüro MT · Klassenübersicht · %s" % k["name"], "Klassenübersicht " + k["name"])
