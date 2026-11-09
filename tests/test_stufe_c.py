"""Tests fuer Stufe C: Lernplan der Schueler (Planen, Wahl, Ausfall, Tagesabschluss, Kann vorher) und Klassenmatrix."""
import datetime
import json
import shutil
import tempfile
import unittest

from app import db, klassen, konten, lernplan, pakete, unterrichtstage as ut

D = datetime.date
HEUTE = D(2026, 11, 5)   # Donnerstag KW 45 (ungerade)


class Plan(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.con = db.oeffnen(self.ordner)
        c = self.con
        with db.transaktion(c):
            self.gob = konten.anlegen(c, "gob", "Matthias Göbel", "admin", "geheim123", vorlaeufig=False)
            self.k = klassen.anlegen(c, self.gob, "BSMT 24a", "2026/27")["id"]
            ut.regel_anlegen(c, self.gob, self.k, {"wochentag": 0, "von": "07:45", "bis": "13:00", "gueltig_von": "2026-08-01", "gueltig_bis": "2027-07-31"})
            ut.regel_anlegen(c, self.gob, self.k, {"wochentag": 3, "rhythmus": "ungerade", "von": "07:45", "bis": "11:15",
                                                   "gueltig_von": "2026-08-01", "gueltig_bis": "2027-07-31"})
            ut.besonders_anlegen(c, self.gob, self.k, {"art": "ausfall", "von": "2026-11-16", "grund": "Zwischenprüfung"})
            self.pid = pakete.anlegen(c, self.gob, self.k, "Elektropneumatik", "LF 4")
            pakete.aendern(c, self.gob, self.pid, {"freigabe": "2026-11-02", "frist": "2026-12-03"})
            self.p1 = pakete.aufgabe_anlegen(c, self.gob, self.pid, {"titel": "Schaltzeichen", "frist": "2026-11-05"})
            self.p2 = pakete.aufgabe_anlegen(c, self.gob, self.pid, {"titel": "Zylinderkräfte", "frist": "2026-11-19"})
            self.ga = pakete.gruppe_anlegen(c, self.gob, self.pid, {"waehlen": 1, "frist": "2026-11-23"})
            self.a1 = pakete.aufgabe_anlegen(c, self.gob, self.pid, {"art": "wahl", "wahlgruppe_id": self.ga, "titel": "Stempel"})
            self.a2 = pakete.aufgabe_anlegen(c, self.gob, self.pid, {"art": "wahl", "wahlgruppe_id": self.ga, "titel": "Sortierweiche"})
            self.z1 = pakete.aufgabe_anlegen(c, self.gob, self.pid, {"art": "zusatz", "titel": "Übung"})
            self.k1 = pakete.kann_anlegen(c, self.gob, self.pid, {"text": "Schaltzeichen lesen", "aufgaben": [self.p1]})
            entwurf = pakete.anlegen(c, self.gob, self.k, "Noch nicht frei")
            pakete.aufgabe_anlegen(c, self.gob, entwurf, {"titel": "Geheim"})
            sid = klassen.schueler_anlegen(c, self.gob, self.k, "Lena", "Krämer")["id"]
            klassen.schueler_anlegen(c, self.gob, self.k, "Jonas", "Weber")
        self.lena = c.execute("SELECT * FROM schueler WHERE id = ?", (sid,)).fetchone()

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def z(self):
        return lernplan.zustand(self.con, self.lena, HEUTE)

    def zeile(self, z, aid):
        return next(r for p in z["pakete"] for r in p["zeilen"] if r["typ"] == "aufgabe" and r["id"] == aid)

    def test_sichtbar_und_spalten(self):
        z = self.z()
        self.assertEqual([p["titel"] for p in z["pakete"]], ["Elektropneumatik"])          # Entwurf nicht sichtbar
        ids = [r.get("id") for r in z["pakete"][0]["zeilen"] if r["typ"] == "aufgabe"]
        self.assertNotIn(self.z1, ids)                                                      # Zusatz nur auf Empfehlung
        self.assertEqual(z["spalten"][0]["datum"], "2026-11-02")                            # ab der Freigabe
        self.assertEqual({s["datum"]: s["status"] for s in z["spalten"]}["2026-11-16"], "ausfall")
        self.assertEqual(self.zeile(z, self.p1)["kann_stand"], "vorher")             # Kann-Liste vorher fehlt noch
        self.assertEqual(self.zeile(z, self.p2)["kann_stand"], "keine")
        self.assertEqual(self.zeile(z, self.p2)["wirksam"], "2026-11-19")

    def test_planen_regeln(self):
        with db.transaktion(self.con):
            lernplan.planen(self.con, self.lena, self.p2, hinzu=["2026-11-05", "2026-11-09"], heute=HEUTE)
        self.assertEqual(self.zeile(self.z(), self.p2)["status"], "geplant")
        for falsch, text in ((["2026-11-02"], "Vergangene"), (["2026-11-16"], "kein Unterricht"), (["2026-11-12"], "kein Unterricht")):
            with self.assertRaisesRegex(lernplan.PlanFehler, text):
                lernplan.planen(self.con, self.lena, self.p2, hinzu=falsch, heute=HEUTE)
        with self.assertRaisesRegex(lernplan.PlanFehler, "zuerst"):
            lernplan.planen(self.con, self.lena, self.a1, hinzu=["2026-11-09"], heute=HEUTE)
        with self.assertRaises(lernplan.PlanFehler):
            lernplan.planen(self.con, self.lena, self.z1, hinzu=["2026-11-09"], heute=HEUTE)
        with db.transaktion(self.con):
            lernplan.planen(self.con, self.lena, self.p2, hinzu=["2026-11-23"], weg=["2026-11-09"], heute=HEUTE)
        r = self.zeile(self.z(), self.p2)
        self.assertEqual(r["plan"], ["2026-11-05", "2026-11-23"])
        self.assertTrue(r["plant_nach_frist"])
        arten = [e["art"] for e in lernplan.entscheidungen(self.con, self.lena["id"])]
        self.assertEqual(arten, ["plan", "plan_neu", "schueler_angelegt"])

    def test_wahl_tauscht_und_abwahl_nimmt_planung_mit(self):
        with db.transaktion(self.con):
            lernplan.waehlen(self.con, self.lena, self.a1, heute=HEUTE)
            lernplan.planen(self.con, self.lena, self.a1, hinzu=["2026-11-09", "2026-11-19"], heute=HEUTE)
            lernplan.waehlen(self.con, self.lena, self.a2, heute=HEUTE)       # tauscht A1 gegen A2
        z = self.z()
        gruppe = next(r for r in z["pakete"][0]["zeilen"] if r["typ"] == "gruppe")
        self.assertEqual(gruppe["gewaehlt"], ["A2"])
        self.assertEqual(self.zeile(z, self.a1)["plan"], [])
        e = lernplan.entscheidungen(self.con, self.lena["id"])
        self.assertEqual([x["art"] for x in e[:3]], ["gewaehlt", "abgewaehlt", "plan_neu"])
        self.assertEqual(e[1]["daten"]["weg"], ["2026-11-09", "2026-11-19"])

    def test_ausfall_verschieben(self):
        with db.transaktion(self.con):
            lernplan.planen(self.con, self.lena, self.p2, hinzu=["2026-11-09"], heute=HEUTE)
            self.con.execute("INSERT INTO plan (schueler_id, aufgabe_id, datum) VALUES (?, ?, '2026-11-16')", (self.lena["id"], self.p2))
        z = self.z()
        self.assertEqual([(h["kuerzel"], h["datum"]) for h in z["hinweise"]["ausfall"]], [("P2", "2026-11-16")])
        with db.transaktion(self.con):
            self.assertEqual(lernplan.ausfall_verschieben(self.con, self.lena, HEUTE), 1)
        self.assertEqual(self.zeile(self.z(), self.p2)["plan"], ["2026-11-09", "2026-11-19"])
        self.assertEqual(lernplan.entscheidungen(self.con, self.lena["id"])[0]["daten"]["grund"], "ausfall")

    def test_tagesabschluss_ist_und_ampel(self):
        with db.transaktion(self.con):
            lernplan.tag_abschliessen(self.con, self.lena, [{"aufgabe_id": self.p1, "ampel": "g"}, {"aufgabe_id": self.p2, "ampel": "y"}], HEUTE)
            lernplan.tag_abschliessen(self.con, self.lena, [{"aufgabe_id": self.p2, "ampel": "r",
                                                          "problem": {"gruende": ["schwer"], "hilfe": ["frist"]}}], HEUTE)   # ueberschreibt heute
        z = self.z()
        self.assertEqual(z["abgeschlossen"][:10], db.jetzt()[:10])
        self.assertEqual(self.zeile(z, self.p1)["status"], "offen")
        self.assertEqual((self.zeile(z, self.p2)["status"], self.zeile(z, self.p2)["ampel"]), ("arbeit", "r"))
        with self.assertRaisesRegex(lernplan.PlanFehler, "kein Unterrichtstag"):
            lernplan.tag_abschliessen(self.con, self.lena, [], D(2026, 11, 6))
        with self.assertRaisesRegex(lernplan.PlanFehler, "Ampel"):
            lernplan.tag_abschliessen(self.con, self.lena, [{"aufgabe_id": self.p2}], HEUTE)
        # eine Woche spaeter ohne neue Ampel: Erinnerung
        spaeter = lernplan.zustand(self.con, self.lena, D(2026, 11, 16))
        self.assertEqual([h["kuerzel"] for h in spaeter["hinweise"]["ampel_alt"]], ["P2"])

    def test_kann_vorher(self):
        with self.assertRaisesRegex(lernplan.PlanFehler, "Kann-Liste"):          # erst vorher, dann planen
            lernplan.planen(self.con, self.lena, self.p1, hinzu=["2026-11-09"], heute=HEUTE)
        with self.assertRaisesRegex(lernplan.PlanFehler, "gehört nicht"):
            lernplan.kann_einschaetzen(self.con, self.lena, self.k1, 2, heute=HEUTE, aufgabe_id=self.p2)
        with db.transaktion(self.con):
            lernplan.kann_einschaetzen(self.con, self.lena, self.k1, 2, heute=HEUTE, aufgabe_id=self.p1)
            lernplan.planen(self.con, self.lena, self.p1, hinzu=["2026-11-09"], heute=HEUTE)
        z = self.z()
        self.assertEqual(z["pakete"][0]["kann"][0]["vorher"], 2)
        r = self.zeile(z, self.p1)
        self.assertEqual((r["kann_liste"][0]["vorher"], r["kann_stand"]), (2, "arbeit"))
        with self.assertRaises(lernplan.PlanFehler):
            lernplan.kann_einschaetzen(self.con, self.lena, self.k1, 5, heute=HEUTE, aufgabe_id=self.p1)

    def test_matrix(self):
        with db.transaktion(self.con):
            lernplan.kann_einschaetzen(self.con, self.lena, self.k1, 2, heute=HEUTE, aufgabe_id=self.p1)
            lernplan.planen(self.con, self.lena, self.p1, hinzu=["2026-11-05"], heute=HEUTE)
            lernplan.tag_abschliessen(self.con, self.lena, [{"aufgabe_id": self.p1, "ampel": "y"}], HEUTE)
            lernplan.waehlen(self.con, self.lena, self.a2, heute=HEUTE)
            lernplan.planen(self.con, self.lena, self.a2, hinzu=["2026-11-30"], heute=HEUTE)   # nach der Gruppenfrist
        m = lernplan.matrix(self.con, self.k, heute=HEUTE)
        self.assertEqual([s["kuerzel"] for s in m["spalten"]], ["P1", "P2", "A"])
        lena, jonas = m["zeilen"][0], m["zeilen"][1]
        self.assertEqual([(z["status"], z["text"]) for z in lena["zellen"]], [("arbeit", "P1"), ("offen", "P2"), ("geplant", "A2")])
        self.assertEqual(lena["ampel"], "y")
        self.assertEqual(lena["hinweis"], "plant A2 nach der Frist")
        self.assertEqual(jonas["hinweis"], "Wahlgruppe A noch nicht gewählt")


if __name__ == "__main__":
    unittest.main()
