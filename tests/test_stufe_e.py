"""Tests fuer Stufe E: Gelingensnachweise (Bereitmeldung mit Kann-Liste, Freischalten, Pruefungstermin, Ergebnis, Versuche)."""
import datetime
import unittest
from unittest import mock

from app import db, klassen, lernplan, nachweise, pakete, rueckmeldung as rm, termine
from test_stufe_d import Basis, D, HEUTE


class Nachweise(Basis):
    def setUp(self):
        super().setUp()
        c = self.con
        with db.transaktion(c):
            self.nm = pakete.nachweis_anlegen(c, self.gob, self.pid, {"art": "moodle", "ergebnis": "punkte", "max_punkte": 40, "frist": "2026-12-03",
                                                                     "moodle_link": "https://moodle.example/mod/quiz/view.php?id=1"})
            self.nf = pakete.nachweis_anlegen(c, self.gob, self.pid, {"art": "fachgespraech", "ergebnis": "note", "titel": "Pneumatik"})
            with mock.patch.object(db, "heute", return_value=HEUTE):
                self.zf = termine.zeitfenster_anlegen(c, self.gob, self.k, {"art": "pruefung", "von": "10:15", "bis": "11:15", "dauer": 15, "puffer": 5,
                                                                           "woechentlich": True, "gueltig_von": "2026-11-05", "gueltig_bis": "2026-12-17"})["zeitfenster"]
        self.alle_kann = {self.k1: 3, self.k2: 4}

    def nw(self, nid, s=None):
        z = lernplan.zustand(self.con, s or self.lena, HEUTE)
        return next(n for p in z["pakete"] for n in p["nachweise"] if n["id"] == nid)

    def test_bereit_braucht_ganze_kann_liste(self):
        n = self.nw(self.nm)
        self.assertEqual((n["status"], n["kann_gesamt"], n["kann_nachher"], n["darf_bereit"]), ("offen", 2, 0, True))
        with self.assertRaisesRegex(nachweise.NachweisFehler, "alle Kann-Aussagen"):
            nachweise.bereit_melden(self.con, self.lena, self.nm, {self.k1: 3}, HEUTE)
        with db.transaktion(self.con):
            nachweise.bereit_melden(self.con, self.lena, self.nm, self.alle_kann, HEUTE)
        n = self.nw(self.nm)
        self.assertEqual((n["status"], n["kann_nachher"], n["darf_bereit"], n["aktuell"]["nr"]), ("bereit", 2, False, 1))
        with self.assertRaisesRegex(nachweise.NachweisFehler, "schon bereit"):
            nachweise.bereit_melden(self.con, self.lena, self.nm, self.alle_kann, HEUTE)
        liste = nachweise.bereit_liste(self.con, self.sch)
        self.assertEqual([(b["name"], b["art"], b["darf"]) for b in liste], [("Lena Krämer", "moodle", True)])
        self.assertFalse(nachweise.bereit_liste(self.con, self.kl)[0]["darf"])
        self.assertEqual(nachweise.zaehler(self.con, self.gob), 1)
        m = lernplan.matrix(self.con, self.k, heute=HEUTE)
        self.assertEqual(m["spalten"][-1]["typ"], "nachweis")
        self.assertEqual((m["zeilen"][0]["zellen"][-2]["status"], m["zeilen"][0]["zellen"][-2]["text"]), ("gn-bereit", "B"))

    def test_moodle_freischalten_ergebnis_nicht_dann_gelungen(self):
        with db.transaktion(self.con):
            vid = nachweise.bereit_melden(self.con, self.lena, self.nm, self.alle_kann, HEUTE)
        with self.assertRaises(klassen.KeinZugriff):
            nachweise.freischalten(self.con, self.kl, vid)
        with db.transaktion(self.con):
            nachweise.freischalten(self.con, self.sch, vid)
        self.assertEqual(self.nw(self.nm)["status"], "frei")
        v = rm.vorlage(self.con, self.sch, self.lena["id"], versuch_id=vid, heute=HEUTE)
        self.assertEqual([k["kuerzel"] for k in v["kann"]], ["K1", "K2"])            # ganze Kann-Liste des Pakets
        self.assertEqual((v["nachweis"]["ergebnis"], v["nachweis"]["max_punkte"]), ("punkte", 40))
        basis = {"schueler_id": self.lena["id"], "versuch_id": vid, "text": "Zylinderkräfte noch einmal üben."}
        with self.assertRaisesRegex(rm.RueckmeldungFehler, "Ergebnis wählen"):
            rm.speichern(self.con, self.sch, basis, freigeben=True, heute=HEUTE)
        with self.assertRaisesRegex(rm.RueckmeldungFehler, "neue Frist"):
            rm.speichern(self.con, self.sch, dict(basis, ergebnis="nicht"), freigeben=True, heute=HEUTE)
        with self.assertRaisesRegex(rm.RueckmeldungFehler, "Punkte"):
            rm.speichern(self.con, self.sch, dict(basis, ergebnis="nicht", punkte=41), heute=HEUTE)
        with db.transaktion(self.con):
            rm.speichern(self.con, self.sch, dict(basis, ergebnis="nicht", punkte="17,5", neue_frist="2026-11-19",
                                                  empfehlungen=[{"aufgabe_id": self.z1}]), freigeben=True, heute=HEUTE)
        n = self.nw(self.nm)
        self.assertEqual((n["status"], n["wirksam"], n["eigene_frist"], n["darf_bereit"]), ("nicht", "2026-11-19", True, True))
        self.assertEqual((n["versuche"][0]["punkte"], n["versuche"][0]["text"]), (17.5, "Zylinderkräfte noch einmal üben."))
        self.assertEqual(rm.fuer_schueler(self.con, self.lena)["rueckmeldungen"][0]["ergebnis"], "nicht")
        self.assertEqual(lernplan.zustand(self.con, self.lena, HEUTE)["pakete"][0]["kann"][0]["lehrkraft"], None)
        # ohne Sperre wieder bereit, zweiter Versuch gelingt
        with db.transaktion(self.con):
            vid2 = nachweise.bereit_melden(self.con, self.lena, self.nm, self.alle_kann, HEUTE)
            nachweise.freischalten(self.con, self.gob, vid2)
            rm.speichern(self.con, self.gob, {"schueler_id": self.lena["id"], "versuch_id": vid2, "ergebnis": "gelungen", "punkte": 36,
                                              "kann": {str(self.k1): 4}}, freigeben=True, heute=HEUTE)
        n = self.nw(self.nm)
        self.assertEqual((n["status"], n["eigene_frist"], [v["nr"] for v in n["versuche"]]), ("gelungen", False, [2, 1]))
        with self.assertRaisesRegex(nachweise.NachweisFehler, "schon gelungen"):
            nachweise.bereit_melden(self.con, self.lena, self.nm, self.alle_kann, HEUTE)
        with self.assertRaisesRegex(rm.RueckmeldungFehler, "abgeschlossen"):
            rm.speichern(self.con, self.gob, {"schueler_id": self.lena["id"], "versuch_id": vid2, "ergebnis": "gelungen"}, freigeben=True, heute=HEUTE)
        zelle = lernplan.matrix(self.con, self.k, heute=HEUTE)["zeilen"][0]["zellen"][-2]
        self.assertEqual((zelle["status"], zelle["text"]), ("gn-gelungen", "36"))
        arten = [e["art"] for e in lernplan.entscheidungen(self.con, self.lena["id"])[:3]]
        self.assertEqual(arten, ["nachweis_ergebnis", "rueckmeldung", "freigeschaltet"])

    def test_fachgespraech_termin_in_pruefungszeit(self):
        with self.assertRaisesRegex(termine.TerminFehler, "zuerst"):
            termine.buchen(self.con, self.lena, self.zf["id"], "2026-11-19", "10:15", "fachgespraech", {}, heute=HEUTE, jetzt_hhmm="09:00")
        with db.transaktion(self.con):
            vid = nachweise.bereit_melden(self.con, self.lena, self.nf, self.alle_kann, HEUTE)
        frei = termine.freie_plaetze(self.con, self.lena, "fachgespraech", heute=HEUTE, jetzt_hhmm="09:00")
        self.assertEqual(frei[0]["plaetze"], ["10:15", "10:35", "10:55"])
        self.assertEqual(termine.freie_plaetze(self.con, self.lena, "feedback", heute=HEUTE, jetzt_hhmm="09:00"), [])   # keine Sprechzeit
        with db.transaktion(self.con):
            tid = termine.buchen(self.con, self.lena, self.zf["id"], "2026-11-19", "10:35", "fachgespraech", {"versuch_id": vid},
                                 heute=HEUTE, jetzt_hhmm="09:00")
        n = self.nw(self.nf)
        self.assertEqual((n["status"], n["aktuell"]["termin"]["beginn"]), ("termin", "10:35"))
        with self.assertRaisesRegex(termine.TerminFehler, "schon einen Termin"):
            termine.buchen(self.con, self.lena, self.zf["id"], "2026-11-26", "10:15", "fachgespraech", {"versuch_id": vid}, heute=HEUTE, jetzt_hhmm="09:00")
        self.assertEqual(termine.termine_schueler(self.con, self.lena, HEUTE)[0]["anlass"], "Gelingensnachweis Pneumatik · Elektropneumatik")
        heute_lk = termine.termine_heute(self.con, self.gob, D(2026, 11, 19))
        self.assertEqual(heute_lk[0]["nachweis_id"], self.nf)
        v = rm.vorlage(self.con, self.gob, self.lena["id"], termin_id=tid, heute=HEUTE)       # aus dem Termin geoeffnet
        self.assertEqual(v["nachweis"]["versuch"]["id"], vid)
        with self.assertRaisesRegex(nachweise.NachweisFehler, "Freischalten gibt es nur"):
            nachweise.freischalten(self.con, self.gob, vid)
        with db.transaktion(self.con):
            termine.absagen_schueler(self.con, self.lena, tid, HEUTE)
        self.assertEqual(self.nw(self.nf)["status"], "bereit")                                # Versuch bleibt, Termin neu buchen
        with db.transaktion(self.con):
            tid2 = termine.buchen(self.con, self.lena, self.zf["id"], "2026-11-26", "10:15", "fachgespraech", {"versuch_id": vid},
                                  heute=HEUTE, jetzt_hhmm="09:00")
            nachweise.zurueckziehen(self.con, self.lena, vid, HEUTE)                          # nimmt den Termin mit
        self.assertEqual(self.nw(self.nf)["status"], "offen")
        self.assertIsNotNone(self.con.execute("SELECT abgesagt FROM termin WHERE id = ?", (tid2,)).fetchone()[0])
        # Note als Ergebnis
        with db.transaktion(self.con):
            vid3 = nachweise.bereit_melden(self.con, self.lena, self.nf, self.alle_kann, HEUTE)
        with self.assertRaisesRegex(rm.RueckmeldungFehler, "Note"):
            rm.speichern(self.con, self.gob, {"schueler_id": self.lena["id"], "versuch_id": vid3, "ergebnis": "gelungen", "note": "sehr gut"}, heute=HEUTE)
        with db.transaktion(self.con):
            rm.speichern(self.con, self.gob, {"schueler_id": self.lena["id"], "versuch_id": vid3, "ergebnis": "gelungen", "note": "2+"},
                         freigeben=True, heute=HEUTE)
        self.assertEqual(self.nw(self.nf)["versuche"][0]["note"], "2+")
        self.assertEqual([p["id"] for p in nachweise.fuer_lehrkraft(self.con, self.kl, self.lena["id"], HEUTE)["pakete"]], [self.pid])


if __name__ == "__main__":
    unittest.main()
