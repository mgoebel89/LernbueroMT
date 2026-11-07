"""Tests fuer Stufe D: Fertig melden, Rueckmeldung mit Entscheidung, Empfehlungen, Hilfe-Reihe, Zeitfenster und Feedbacktermine."""
import datetime
import shutil
import tempfile
import unittest
from unittest import mock

from app import db, klassen, konten, lernplan, pakete, rueckmeldung as rm, termine, unterrichtstage as ut

D = datetime.date
HEUTE = D(2026, 11, 5)   # Donnerstag KW 45 (ungerade)


class Basis(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        c = self.con
        with db.transaktion(c):
            self.gob = konten.anlegen(c, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.sch = konten.anlegen(c, "sch", "Anna Schmidt", "lehrkraft", "geheim123", vorlaeufig=False)
            self.kl = konten.anlegen(c, "kl", "Klara Leitung", "lehrkraft", "geheim123", vorlaeufig=False)
            self.k = klassen.anlegen(c, self.gob, "BSMT 24a", "2026/27")["id"]
            klassen.lehrkraft_setzen(c, self.gob, self.k, self.sch["id"], "team")
            klassen.lehrkraft_setzen(c, self.gob, self.k, self.kl["id"], "einsicht")
            ut.regel_anlegen(c, self.gob, self.k, {"wochentag": 0, "von": "07:45", "bis": "13:00", "gueltig_von": "2026-08-01", "gueltig_bis": "2027-07-31"})
            ut.regel_anlegen(c, self.gob, self.k, {"wochentag": 3, "von": "07:45", "bis": "11:15", "gueltig_von": "2026-08-01", "gueltig_bis": "2027-07-31"})
            ut.besonders_anlegen(c, self.gob, self.k, {"art": "ausfall", "von": "2026-11-16", "grund": "Zwischenprüfung"})
            ut.besonders_anlegen(c, self.gob, self.k, {"art": "ohne", "von": "2026-11-12", "grund": "Fortbildung"})
            self.pid = pakete.anlegen(c, self.gob, self.k, "Elektropneumatik", "LF 4")
            pakete.aendern(c, self.gob, self.pid, {"freigabe": "2026-11-02", "frist": "2026-12-03"})
            self.p1 = pakete.aufgabe_anlegen(c, self.gob, self.pid, {"titel": "Schaltzeichen", "frist": "2026-11-05"})
            self.p2 = pakete.aufgabe_anlegen(c, self.gob, self.pid, {"titel": "Zylinderkräfte", "frist": "2026-11-19"})
            self.ga = pakete.gruppe_anlegen(c, self.gob, self.pid, {"waehlen": 1})
            self.a1 = pakete.aufgabe_anlegen(c, self.gob, self.pid, {"art": "wahl", "wahlgruppe_id": self.ga, "titel": "Stempel"})
            self.z1 = pakete.aufgabe_anlegen(c, self.gob, self.pid, {"art": "zusatz", "zusatz_art": "wiederholung", "titel": "Übung Betätigung"})
            self.k1 = pakete.kann_anlegen(c, self.gob, self.pid, {"text": "Schaltzeichen lesen", "aufgaben": [self.p1]})
            self.k2 = pakete.kann_anlegen(c, self.gob, self.pid, {"text": "Wegeventile benennen", "aufgaben": [self.p1, self.a1]})
            sid = klassen.schueler_anlegen(c, self.gob, self.k, "Lena", "Krämer")["id"]
            sid2 = klassen.schueler_anlegen(c, self.gob, self.k, "Jonas", "Weber")["id"]
        self.lena = c.execute("SELECT * FROM schueler WHERE id = ?", (sid,)).fetchone()
        self.jonas = c.execute("SELECT * FROM schueler WHERE id = ?", (sid2,)).fetchone()

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def zeile(self, aid, s=None, heute=HEUTE):
        z = lernplan.zustand(self.con, s or self.lena, heute)
        return next(r for p in z["pakete"] for r in p["zeilen"] if r["typ"] == "aufgabe" and r["id"] == aid)


class Rueckmeldung(Basis):
    def melden(self, kann=None):
        with db.transaktion(self.con):
            return rm.fertig_melden(self.con, self.lena, self.p1, kann if kann is not None else {self.k1: 3, self.k2: 2}, HEUTE)

    def test_fertig_melden_braucht_alle_kann_aussagen(self):
        with self.assertRaisesRegex(rm.RueckmeldungFehler, "alle Kann-Aussagen"):
            rm.fertig_melden(self.con, self.lena, self.p1, {self.k1: 3}, HEUTE)
        mid = self.melden()
        self.assertEqual(self.zeile(self.p1)["status"], "fertig")
        self.assertFalse(self.zeile(self.p1)["ueber_frist"])           # Frist 05.11. war heute, gemeldet zaehlt
        with self.assertRaisesRegex(rm.RueckmeldungFehler, "schon fertig"):
            self.melden()
        nachher = {z[0]: z[1] for z in self.con.execute("SELECT kann_id, stufe FROM kann_einschaetzung WHERE art = 'nachher'")}
        self.assertEqual(nachher, {self.k1: 3, self.k2: 2})
        ein = rm.eingang(self.con, self.sch)
        self.assertEqual([(e["meldung_id"], e["kuerzel"], e["darf"]) for e in ein], [(mid, "P1", True)])
        self.assertFalse(rm.eingang(self.con, self.kl)[0]["darf"])     # Einsicht sieht, darf nicht
        self.assertEqual(rm.zaehler(self.con, self.gob), 1)
        with db.transaktion(self.con):
            rm.zurueckziehen(self.con, self.lena, mid)
        self.assertEqual(self.zeile(self.p1)["status"], "offen")
        self.assertEqual(rm.eingang(self.con, self.sch), [])

    def test_entwurf_nur_fuer_verfasser_dann_freigabe_ueberarbeiten(self):
        mid = self.melden()
        v = rm.vorlage(self.con, self.sch, self.lena["id"], meldung_id=mid, heute=HEUTE)
        self.assertEqual([k["kuerzel"] for k in v["kann"]], ["K1", "K2"])
        self.assertEqual(v["kann"][1]["nachher"], 2)
        self.assertEqual(v["frist_vorschlag"], "2026-11-12")           # uebernaechster Unterrichtstag (Mo 09., Do 12.)
        self.assertIn(self.z1, [a["id"] for a in v["auswahl"]])       # Zusatzaufgaben sind empfehlbar
        daten = {"schueler_id": self.lena["id"], "meldung_id": mid, "text": "Betätigungsarten üben.", "kann": {str(self.k2): 1},
                 "entscheidung": "ueberarbeiten", "neue_frist": "2026-11-12",
                 "empfehlungen": [{"aufgabe_id": self.z1, "verbindlich": True, "frist": "2026-11-19"}]}
        with db.transaktion(self.con):
            rid = rm.speichern(self.con, self.sch, daten, heute=HEUTE)
        # Entwurf: Schueler sieht nichts, Kollegen sehen ihn nicht, Zusatzaufgabe noch unsichtbar
        self.assertEqual(rm.fuer_schueler(self.con, self.lena)["rueckmeldungen"], [])
        self.assertEqual(rm.fuer_lehrkraft(self.con, self.gob, self.lena["id"])["rueckmeldungen"], [])
        self.assertEqual(len(rm.fuer_lehrkraft(self.con, self.sch, self.lena["id"])["rueckmeldungen"]), 1)
        self.assertEqual(rm.vorlage(self.con, self.sch, self.lena["id"], meldung_id=mid, heute=HEUTE)["entwurf"]["id"], rid)
        self.assertIsNone(rm.vorlage(self.con, self.gob, self.lena["id"], meldung_id=mid, heute=HEUTE)["entwurf"])
        with self.assertRaises(lernplan.PlanFehler):
            lernplan.planen(self.con, self.lena, self.z1, hinzu=["2026-11-09"], heute=HEUTE)
        with self.assertRaises(klassen.KeinZugriff):
            rm.speichern(self.con, self.kl, dict(daten, id=None), heute=HEUTE)
        with db.transaktion(self.con):
            rm.speichern(self.con, self.sch, dict(daten, id=rid), freigeben=True, heute=HEUTE)
        r = self.zeile(self.p1)
        self.assertEqual((r["status"], r["wirksam"], r["eigene_frist"]), ("ueberarbeiten", "2026-11-12", True))
        # Ampel-Erinnerung erst eine Woche nach der Entscheidung, nicht sofort
        self.assertEqual(lernplan.zustand(self.con, self.lena, D.fromisoformat(db.jetzt()[:10]))["hinweise"]["ampel_alt"], [])
        spaeter = D.fromisoformat(db.jetzt()[:10]) + datetime.timedelta(days=8)
        self.assertEqual([h["kuerzel"] for h in lernplan.zustand(self.con, self.lena, spaeter)["hinweise"]["ampel_alt"]], ["P1"])
        sicht = rm.fuer_schueler(self.con, self.lena)
        self.assertEqual(sicht["ungelesen"], 1)
        self.assertEqual(sicht["rueckmeldungen"][0]["verfasser"], "Anna Schmidt")
        self.assertEqual(sicht["rueckmeldungen"][0]["empfehlungen"][0]["aufgabe"]["kuerzel"], "Z1")
        z = lernplan.zustand(self.con, self.lena, HEUTE)
        self.assertIn({"typ": "empfohlen", "anzahl": 1}, z["pakete"][0]["zeilen"])
        zz = self.zeile(self.z1)
        self.assertEqual((zz["wirksam"], zz["empfehlungen"][0]["verbindlich"]), ("2026-11-19", True))
        self.assertEqual(next(k for k in z["pakete"][0]["kann"] if k["id"] == self.k2)["lehrkraft"], 1)
        with db.transaktion(self.con):
            lernplan.planen(self.con, self.lena, self.z1, hinzu=["2026-11-09"], heute=HEUTE)
            rm.gelesen(self.con, self.lena)
        self.assertEqual(rm.fuer_schueler(self.con, self.lena)["ungelesen"], 0)
        lk = rm.fuer_lehrkraft(self.con, self.kl, self.lena["id"])      # Einsicht sieht Freigegebenes mit Urheber
        self.assertEqual(lk["empfehlungen"][0]["eingeplant"], ["2026-11-09"])
        self.assertFalse(lk["darf"])
        m = lernplan.matrix(self.con, self.k, heute=HEUTE)
        self.assertEqual(m["zeilen"][0]["empfehlungen"], 1)
        self.assertEqual(m["zeilen"][0]["zellen"][0]["status"], "ueberarbeiten")
        # wieder fertig melden ohne Sperre, dann annehmen: alte Empfehlungen der Aufgabe bleiben (andere Aufgabe)
        with db.transaktion(self.con):
            mid2 = rm.fertig_melden(self.con, self.lena, self.p1, {self.k1: 4, self.k2: 3}, HEUTE)
            rm.speichern(self.con, self.gob, {"schueler_id": self.lena["id"], "meldung_id": mid2, "entscheidung": "angenommen"},
                         freigeben=True, heute=HEUTE)
        self.assertEqual(self.zeile(self.p1)["status"], "angenommen")
        self.assertFalse(self.zeile(self.p1)["eigene_frist"])
        arten = [e["art"] for e in lernplan.entscheidungen(self.con, self.lena["id"])[:4]]
        self.assertEqual(arten, ["rueckmeldung", "fertig", "plan_neu", "rueckmeldung"])

    def test_freigabe_braucht_entscheidung_und_frist(self):
        mid = self.melden()
        basis = {"schueler_id": self.lena["id"], "meldung_id": mid, "text": "gut"}
        with self.assertRaisesRegex(rm.RueckmeldungFehler, "entscheiden"):
            rm.speichern(self.con, self.sch, basis, freigeben=True, heute=HEUTE)
        with self.assertRaisesRegex(rm.RueckmeldungFehler, "neue Frist"):
            rm.speichern(self.con, self.sch, dict(basis, entscheidung="ueberarbeiten"), freigeben=True, heute=HEUTE)
        with self.assertRaisesRegex(rm.RueckmeldungFehler, "verbindliche"):
            rm.speichern(self.con, self.sch, dict(basis, empfehlungen=[{"aufgabe_id": self.z1, "verbindlich": True}]), heute=HEUTE)

    def test_abwaehlen_nach_fertig_gesperrt_und_freie_empfehlung(self):
        with db.transaktion(self.con):
            lernplan.waehlen(self.con, self.lena, self.a1, heute=HEUTE)
            rm.fertig_melden(self.con, self.lena, self.a1, {self.k2: 3}, HEUTE)
        with self.assertRaisesRegex(lernplan.PlanFehler, "fertig gemeldet"):
            lernplan.waehlen(self.con, self.lena, self.a1, False, heute=HEUTE)
        with db.transaktion(self.con):
            eid = rm.empfehlung_anlegen(self.con, self.sch, self.lena["id"], {"aufgabe_id": self.p2, "hinweis": "Seite 3"}, heute=HEUTE)
        with self.assertRaisesRegex(rm.RueckmeldungFehler, "schon empfohlen"):
            rm.empfehlung_anlegen(self.con, self.sch, self.lena["id"], {"aufgabe_id": self.p2}, heute=HEUTE)
        self.assertEqual(self.zeile(self.p2)["empfehlungen"][0]["hinweis"], "Seite 3")
        self.assertEqual(rm.fuer_schueler(self.con, self.lena)["empfehlungen"][0]["aufgabe"]["kuerzel"], "P2")
        with db.transaktion(self.con):
            rm.empfehlung_erledigt(self.con, self.lena, eid)
        self.assertTrue(self.zeile(self.p2)["empfehlungen"][0]["erledigt"])
        with db.transaktion(self.con):
            rm.empfehlung_entfernen(self.con, self.sch, eid)
        self.assertEqual(self.zeile(self.p2)["empfehlungen"], [])


class Hilfe(Basis):
    def test_reihe(self):
        with db.transaktion(self.con):
            termine.hilfe_rufen(self.con, self.jonas, heute=HEUTE)
            st = termine.hilfe_rufen(self.con, self.lena, self.p2, heute=HEUTE)
            termine.hilfe_rufen(self.con, self.lena, heute=HEUTE)        # doppelt tippen schadet nicht
        self.assertEqual((st["offen"], st["platz"]), (True, 2))
        reihe = termine.hilfe_reihe(self.con, self.kl, HEUTE)
        self.assertEqual([(h["name"], h["kuerzel"], h["darf"]) for h in reihe], [("Jonas Weber", None, False), ("Lena Krämer", "P2", False)])
        with self.assertRaises(klassen.KeinZugriff):
            termine.hilfe_erledigt(self.con, self.kl, reihe[0]["id"])
        with db.transaktion(self.con):
            termine.hilfe_erledigt(self.con, self.sch, reihe[0]["id"])
        self.assertEqual(termine.hilfe_stand(self.con, self.lena, HEUTE)["platz"], 1)
        with db.transaktion(self.con):
            termine.hilfe_zurueckziehen(self.con, self.lena, HEUTE)
        self.assertEqual(termine.hilfe_reihe(self.con, self.gob, HEUTE), [])
        self.assertEqual(termine.hilfe_reihe(self.con, self.gob, D(2026, 11, 9)), [])

    def test_gesperrt_ohne_lehrkraft_und_ausserhalb(self):
        st = termine.hilfe_stand(self.con, self.lena, D(2026, 11, 12))
        self.assertEqual((st["erlaubt"], st["grund"]), (False, "heute ohne Lehrkraft"))
        with self.assertRaisesRegex(termine.TerminFehler, "ohne Lehrkraft"):
            termine.hilfe_rufen(self.con, self.lena, heute=D(2026, 11, 12))
        self.assertFalse(termine.hilfe_stand(self.con, self.lena, D(2026, 11, 6))["erlaubt"])


class Zeitfenster(Basis):
    def setUp(self):
        super().setUp()
        with db.transaktion(self.con), mock.patch.object(db, "heute", return_value=HEUTE):
            e = termine.zeitfenster_anlegen(self.con, self.gob, self.k, {"art": "sprech", "von": "09:30", "bis": "10:30", "dauer": 10, "puffer": 5,
                                                                        "woechentlich": True, "gueltig_von": "2026-11-05", "gueltig_bis": "2026-12-17"})
        self.zf = e["zeitfenster"]
        self.warn = e["warnungen"]

    def test_plaetze_und_ueberschneidung(self):
        self.assertEqual(self.zf["plaetze_je_tag"], 4)       # 09:30, 09:45, 10:00, 10:15
        self.assertEqual(self.zf["tag"], "Do")
        self.assertEqual(self.warn, [])
        with db.transaktion(self.con), mock.patch.object(db, "heute", return_value=HEUTE):
            e = termine.zeitfenster_anlegen(self.con, self.gob, self.k, {"art": "pruefung", "von": "10:15", "bis": "11:15", "dauer": 15, "puffer": 5,
                                                                        "woechentlich": False, "tage": ["2026-11-19", "2026-12-10"]})
        self.assertEqual(len(e["warnungen"]), 1)
        self.assertIn("Überschneidung", e["warnungen"][0])
        with self.assertRaisesRegex(termine.TerminFehler, "passt nicht"):
            termine.zeitfenster_anlegen(self.con, self.gob, self.k, {"art": "sprech", "von": "09:00", "bis": "09:05", "dauer": 10,
                                                                    "gueltig_von": "2026-11-05", "gueltig_bis": "2026-11-30"})
        with self.assertRaises(klassen.KeinZugriff):
            termine.zeitfenster_anlegen(self.con, self.kl, self.k, {"art": "sprech", "von": "09:00", "bis": "10:00", "dauer": 10,
                                                                   "gueltig_von": "2026-11-05", "gueltig_bis": "2026-11-30"})

    def test_buchen_regeln(self):
        frei = termine.freie_plaetze(self.con, self.lena, heute=HEUTE, jetzt_hhmm="09:40")
        tage = [f["datum"] for f in frei]
        self.assertEqual(tage[:3], ["2026-11-05", "2026-11-19", "2026-11-26"])   # 12.11. ohne Lehrkraft: keine Termine
        self.assertEqual(frei[0]["plaetze"], ["09:45", "10:00", "10:15"])         # heute nur spaetere
        with self.assertRaisesRegex(termine.TerminFehler, "Anlass"):
            termine.buchen(self.con, self.lena, self.zf["id"], "2026-11-19", "09:30", heute=HEUTE, jetzt_hhmm="09:40")
        with self.assertRaisesRegex(termine.TerminFehler, "keine Sprechzeit"):
            termine.buchen(self.con, self.lena, self.zf["id"], "2026-11-12", "09:30", anlass={"text": "x"}, heute=HEUTE, jetzt_hhmm="09:40")
        with db.transaktion(self.con):
            tid = termine.buchen(self.con, self.lena, self.zf["id"], "2026-11-19", "09:45", anlass={"aufgabe_id": self.p2}, heute=HEUTE, jetzt_hhmm="09:40")
        with self.assertRaisesRegex(termine.TerminFehler, "schon einen offenen"):
            termine.buchen(self.con, self.lena, self.zf["id"], "2026-11-26", "09:45", anlass={"text": "x"}, heute=HEUTE, jetzt_hhmm="09:40")
        with self.assertRaisesRegex(termine.TerminFehler, "vergeben"):
            termine.buchen(self.con, self.jonas, self.zf["id"], "2026-11-19", "09:45", anlass={"text": "Frage"}, heute=HEUTE, jetzt_hhmm="09:40")
        frei_jonas = termine.freie_plaetze(self.con, self.jonas, heute=HEUTE, jetzt_hhmm="09:40")
        self.assertEqual(next(f for f in frei_jonas if f["datum"] == "2026-11-19")["plaetze"], ["09:30", "10:00", "10:15"])
        meine = termine.termine_schueler(self.con, self.lena, HEUTE)
        self.assertEqual((meine[0]["anlass"], meine[0]["darf_absagen"]), ("P2 Zylinderkräfte", True))
        with self.assertRaisesRegex(termine.TerminFehler, "Vortag"):
            termine.absagen_schueler(self.con, self.lena, tid, D(2026, 11, 19))
        bel = termine.belegung(self.con, self.gob, self.k, von=D(2026, 11, 19), tage=1)
        self.assertEqual([p["termin"]["name"] for p in bel[0]["plaetze"] if p.get("termin")], ["Lena Krämer"])
        self.assertEqual(sum(1 for p in bel[0]["plaetze"] if p.get("puffer")), 3)
        self.assertEqual([t["name"] for t in termine.termine_heute(self.con, self.gob, D(2026, 11, 19))], ["Lena Krämer"])
        # Rueckmeldung aus dem Termin: Anlass P2, ohne Meldung keine Entscheidung
        v = rm.vorlage(self.con, self.gob, self.lena["id"], termin_id=tid, heute=HEUTE)
        self.assertEqual((v["aufgabe"]["kuerzel"], v["meldung"]), ("P2", None))
        with db.transaktion(self.con):
            termine.absagen_schueler(self.con, self.lena, tid, HEUTE)
            termine.buchen(self.con, self.lena, self.zf["id"], "2026-11-26", "09:30", anlass={"paket_id": self.pid}, heute=HEUTE, jetzt_hhmm="09:40")
        # Lehrkraft entfernt das Fenster: kuenftige Termine werden abgesagt, der Schueler sieht das
        with db.transaktion(self.con), mock.patch.object(db, "heute", return_value=HEUTE):
            self.assertEqual(termine.zeitfenster_entfernen(self.con, self.gob, self.zf["id"]), 1)
        meine = termine.termine_schueler(self.con, self.lena, HEUTE)
        self.assertEqual([(t["anlass"], t["von_lehrkraft_abgesagt"]) for t in meine], [("Paket Elektropneumatik", True)])


class Gespraech(Basis):
    def test_pflichttermin_aus_zu_pruefen(self):
        with db.transaktion(self.con), mock.patch.object(db, "heute", return_value=HEUTE):
            zf = termine.zeitfenster_anlegen(self.con, self.gob, self.k, {"art": "sprech", "von": "09:30", "bis": "10:30", "dauer": 10, "puffer": 5,
                                                                         "gueltig_von": "2026-11-05", "gueltig_bis": "2026-12-17"})["zeitfenster"]
            termine.zeitfenster_anlegen(self.con, self.sch, self.k, {"art": "sprech", "von": "11:00", "bis": "11:30", "dauer": 10,
                                                                    "gueltig_von": "2026-11-05", "gueltig_bis": "2026-12-17"})
            mid = rm.fertig_melden(self.con, self.lena, self.p1, {self.k1: 3, self.k2: 2}, HEUTE)
        plaetze = termine.gespraech_plaetze(self.con, self.gob, mid, HEUTE, "09:00")
        self.assertEqual({p["zeitfenster_id"] for p in plaetze}, {zf["id"]})                 # nur die eigene Sprechzeit
        with self.assertRaises(klassen.KeinZugriff):
            termine.gespraech_eintragen(self.con, self.kl, mid, zf["id"], "2026-11-19", "09:30", heute=HEUTE, jetzt_hhmm="09:00")
        with db.transaktion(self.con):
            termine.gespraech_eintragen(self.con, self.gob, mid, zf["id"], "2026-11-19", "09:30", "Bring die Rechnung mit", HEUTE, "09:00")
        self.assertEqual((rm.eingang(self.con, self.gob)[0]["gespraech"]["beginn"]), "09:30")
        with self.assertRaisesRegex(termine.TerminFehler, "schon ein Gespräch"):
            termine.gespraech_eintragen(self.con, self.gob, mid, zf["id"], "2026-11-26", "09:30", heute=HEUTE, jetzt_hhmm="09:00")
        t = termine.termine_schueler(self.con, self.lena, HEUTE)[0]
        self.assertEqual((t["pflicht"], t["darf_absagen"], t["hinweis"], t["anlass"]), (True, False, "Bring die Rechnung mit", "P1 Schaltzeichen"))
        with self.assertRaisesRegex(termine.TerminFehler, "Lehrkraft eingetragen"):
            termine.absagen_schueler(self.con, self.lena, t["id"], HEUTE)
        with db.transaktion(self.con):   # zaehlt nicht als der eine offene Feedbacktermin
            termine.buchen(self.con, self.lena, zf["id"], "2026-11-26", "09:45", anlass={"text": "Frage"}, heute=HEUTE, jetzt_hhmm="09:00")
        v = rm.vorlage(self.con, self.gob, self.lena["id"], termin_id=t["id"], heute=HEUTE)   # am Termin: Meldung gleich dabei
        self.assertEqual(v["meldung"]["id"], mid)
        with db.transaktion(self.con):
            termine.absagen_lehrkraft(self.con, self.gob, t["id"])
        self.assertIsNone(rm.eingang(self.con, self.gob)[0]["gespraech"])


class Markieren(Basis):
    def test_farbe_heute_und_letzte_woche(self):
        with db.transaktion(self.con):
            lernplan.markieren(self.con, self.lena, self.p2, "2026-11-05", "g", HEUTE)
            lernplan.markieren(self.con, self.lena, self.p2, "2026-11-02", "y", HEUTE)
            lernplan.markieren(self.con, self.lena, self.p2, "2026-11-05", "r", HEUTE)        # umfaerben
        r = self.zeile(self.p2)
        self.assertEqual((r["ist"], r["status"], r["ampel"]), ({"2026-11-02": "y", "2026-11-05": "r"}, "arbeit", "r"))
        with db.transaktion(self.con):
            lernplan.markieren(self.con, self.lena, self.p2, "2026-11-05", None, HEUTE)       # leer
        self.assertEqual(self.zeile(self.p2)["ist"], {"2026-11-02": "y"})
        with self.assertRaisesRegex(lernplan.PlanFehler, "letzten 7"):
            lernplan.markieren(self.con, self.lena, self.p2, "2026-10-26", "g", HEUTE)
        with self.assertRaisesRegex(lernplan.PlanFehler, "letzten 7"):
            lernplan.markieren(self.con, self.lena, self.p2, "2026-11-09", "g", HEUTE)        # Zukunft
        with self.assertRaisesRegex(lernplan.PlanFehler, "kein Unterricht"):
            lernplan.markieren(self.con, self.lena, self.p2, "2026-11-04", "g", HEUTE)
        with self.assertRaisesRegex(lernplan.PlanFehler, "zuerst"):
            lernplan.markieren(self.con, self.lena, self.a1, "2026-11-05", "g", HEUTE)
        self.assertEqual(lernplan.entscheidungen(self.con, self.lena["id"])[0]["art"], "markiert")


class Diktat(Basis):
    def test_ohne_whisper_und_fachwoerter(self):
        from app import diktat
        with mock.patch.object(diktat, "UMGEBUNG", self.ordner + "/gibtsnicht"):
            self.assertFalse(diktat.stand(self.ordner)["verfuegbar"])
            with self.assertRaisesRegex(diktat.DiktatFehler, "nicht eingerichtet"):
                diktat.erkennen(self.ordner, b"x", "audio/webm")
        w = diktat.fachwoerter(self.con, self.pid)
        self.assertIn("Zylinderkräfte", w)
        self.assertIn("Wegeventile benennen", w)
        self.assertEqual(diktat.fachwoerter(self.con, None), "")


if __name__ == "__main__":
    unittest.main()
