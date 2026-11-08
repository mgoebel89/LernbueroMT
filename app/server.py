"""Webserver: HTTPS fuer den Lehrerbereich (Port 443). HTTP (Port 80) bedient nur die Schuelerseiten (/s/<Code>, die
Startseite zum Code-Eingeben), ihre Schnittstelle, /static und das Stammzertifikat: Schuelergeraete haben das Zertifikat
nicht, der QR-Code soll ohne Warnung aufgehen. Alles andere leitet nach HTTPS um (Bauweise wie im TrackingDRS).

Ohne Zertifikat (oder mit LERNBUERO_OHNE_TLS=1 zum lokalen Testen) laeuft die ganze Seite ueber HTTP.
Umgebungsvariablen: LERNBUERO_DATEN, LERNBUERO_TLS_DIR, LERNBUERO_HTTPS_PORT, LERNBUERO_HTTP_PORT, LERNBUERO_BIND,
LERNBUERO_OHNE_TLS.

Alle Aenderungen laufen ueber POST mit JSON und dem Kopf X-Lernbuero: 1 (Schutz vor fremden Formularen).
Lehrkraefte melden sich per Cookie an, Schueler nur ueber ihren Code in der Adresse.
"""
import json
import mimetypes
import os
import re
import socket
import ssl
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import datetime
import time

from . import (VERSION, db, diktat, kalender, klassen, konten, lernplan, moodle, nachweise, pakete, pdf, qr, rueckmeldung, teams,
               termine, unterrichtstage, updates, zeitplan)

BASIS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASIS, "web")
DATEN_DIR = os.environ.get("LERNBUERO_DATEN", "/var/lib/lernbuero")
TLS_DIR = os.environ.get("LERNBUERO_TLS_DIR", os.path.join(DATEN_DIR, "tls"))
HTTPS_PORT = int(os.environ.get("LERNBUERO_HTTPS_PORT", "443"))
HTTP_PORT = int(os.environ.get("LERNBUERO_HTTP_PORT", "80"))
BIND = os.environ.get("LERNBUERO_BIND", "0.0.0.0")
OHNE_TLS = os.environ.get("LERNBUERO_OHNE_TLS") == "1"

COOKIE = "lbmt"
KOPF = "X-Lernbuero"
MAX_BODY = 4 * 1024 * 1024   # Moodle-Teilnehmerliste als Text
SEITEN = {"/anmelden": "anmelden.html", "/lehrer": "lehrer.html", "/einrichtung": "einrichtung.html", "/code": "start.html"}
STATISCH = re.compile(r"/static/([a-z0-9_-]+\.(css|js|svg|png|ico))")
SCHUELER_SEITE = re.compile(r"/s/[A-Za-z0-9-]{8,9}")
# was ueber HTTP erreichbar ist, wenn HTTPS laeuft
SCHUELER_PFADE = re.compile(r"/|/code|/s/[A-Za-z0-9-]{8,9}|/api/s/[A-Za-z0-9-]{8,9}(/[a-z0-9/_-]*)?"
                            r"|/static/[a-z0-9_-]+\.(css|js|svg|png|ico)|/ca\.crt")
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")

SPERRE = konten.Sperre()            # Passwort-Raten im Lehrerbereich
CODE_SPERRE = konten.Sperre()       # Code-Raten auf den Schuelerseiten


class Fehler(Exception):
    def __init__(self, status, meldung):
        super().__init__(meldung)
        self.status = status
        self.meldung = meldung


def _ganzzahl(wert):
    try:
        return int(wert)
    except (TypeError, ValueError):
        raise Fehler(400, "Ungültige Angabe.")


class Handler(BaseHTTPRequestHandler):
    server_version = "LernbueroMT"
    sys_version = ""
    timeout = 30
    protocol_version = "HTTP/1.1"
    nur_schueler = False   # True: HTTP-Port neben HTTPS, nur Schuelerpfade

    # --- Hilfen ---

    def _kopfzeilen(self, status, typ, laenge, extra=()):
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(laenge))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")   # der Zugangscode steht in der Adresse
        self.send_header("Content-Security-Policy", CSP)
        for name, wert in extra:
            self.send_header(name, wert)
        self.end_headers()

    def antwort(self, status, inhalt, typ="application/json; charset=utf-8", extra=(), cache=False):
        if not isinstance(inhalt, bytes):
            inhalt = json.dumps(inhalt, ensure_ascii=False).encode("utf-8")
        extra = list(extra) + ([] if cache else [("Cache-Control", "no-store")])
        self._kopfzeilen(status, typ, len(inhalt), extra)
        if self.command != "HEAD":
            self.wfile.write(inhalt)

    def umleiten(self, ziel):
        self._kopfzeilen(303, "text/plain; charset=utf-8", 0, [("Location", ziel), ("Cache-Control", "no-store")])

    def datei(self, pfad, typ=None):
        try:
            with open(pfad, "rb") as f:
                inhalt = f.read()
        except OSError:
            return self.antwort(404, {"fehler": "Nicht gefunden."})
        typ = typ or (mimetypes.guess_type(pfad)[0] or "application/octet-stream")
        if typ.startswith("text/") or typ in ("application/javascript", "image/svg+xml"):
            typ += "; charset=utf-8"
        self.antwort(200, inhalt, typ)

    def herunterladen(self, inhalt, typ, dateiname):
        name = urllib.parse.quote(dateiname)
        self.antwort(200, inhalt, typ, extra=[("Content-Disposition", "attachment; filename*=UTF-8''%s" % name)])

    def body(self):
        """JSON-Inhalt einer POST-Anfrage. Liest immer den ganzen Inhalt (sonst bricht die Verbindung ab)."""
        laenge = _ganzzahl(self.headers.get("Content-Length") or 0)
        if laenge > MAX_BODY:
            raise Fehler(413, "Die Anfrage ist zu groß.")
        roh = self.rfile.read(laenge) if laenge else b""
        if self.headers.get(KOPF) != "1":
            raise Fehler(403, "Anfrage abgelehnt.")
        if not roh:
            return {}
        try:
            daten = json.loads(roh.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise Fehler(400, "Ungültige Daten.")
        if not isinstance(daten, dict):
            raise Fehler(400, "Ungültige Daten.")
        return daten

    def abfrage(self, name, vorgabe=None):
        werte = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get(name)
        return werte[0] if werte else vorgabe

    def cookie(self):
        for teil in (self.headers.get("Cookie") or "").split(";"):
            name, _, wert = teil.strip().partition("=")
            if name == COOKIE:
                return wert
        return None

    def cookie_setzen(self, wert, max_age):
        sicher = "; Secure" if getattr(self.server, "ist_tls", False) else ""
        return ("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d%s" % (COOKIE, wert, max_age, sicher))

    def adresse(self):
        return self.client_address[0]

    def host(self):
        host = (self.headers.get("Host") or "").strip()
        host = host[1:host.index("]")] if host.startswith("[") and "]" in host else host.split(":")[0]
        return host if re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host) else socket.gethostname()

    def konto(self, con, pflicht=True, vorlaeufig_ok=False):
        k = konten.sitzung_pruefen(con, self.cookie())
        if k is None:
            if pflicht:
                raise Fehler(401, "Bitte anmelden.")
            return None
        if k["pw_vorlaeufig"] and not vorlaeufig_ok:
            raise Fehler(403, "Bitte zuerst ein eigenes Passwort festlegen.")
        return k

    # --- Verteilung ---

    def do_GET(self):
        self._verteilen("GET")

    def do_HEAD(self):
        self._verteilen("GET")

    def do_POST(self):
        self._verteilen("POST")

    def zu_https(self, methode):
        """Lehrerpfade auf dem HTTP-Port: GET nach HTTPS umleiten, POST ablehnen (Passwoerter nie unverschluesselt)."""
        laenge = _ganzzahl(self.headers.get("Content-Length") or 0)
        if 0 < laenge <= MAX_BODY:
            self.rfile.read(laenge)
        if methode == "POST" or laenge > MAX_BODY:
            return self.antwort(403, {"fehler": "Bitte die Seite über https:// aufrufen."})
        port = "" if HTTPS_PORT == 443 else ":%d" % HTTPS_PORT
        self._kopfzeilen(301, "text/plain; charset=utf-8", 0,
                         [("Location", "https://%s%s%s" % (self.host(), port, self.path if self.path.startswith("/") else "/"))])

    def _verteilen(self, methode):
        pfad = urllib.parse.urlsplit(self.path).path
        if self.nur_schueler and not SCHUELER_PFADE.fullmatch(pfad):
            try:
                return self.zu_https(methode)
            except Fehler as f:
                return self.antwort(f.status, {"fehler": f.meldung})
        con = None
        try:
            con = db.verbinden(self.server.db_pfad)
            if methode == "GET" and not pfad.startswith("/api/"):
                return self.seite(con, pfad)
            for m, muster, funktion in ROUTEN:
                treffer = muster.fullmatch(pfad)
                if m == methode and treffer:
                    daten = self.body() if methode == "POST" and funktion not in ROH else {}
                    return funktion(self, con, daten, *treffer.groups())
            if methode == "POST":
                self.body()
            raise Fehler(404, "Nicht gefunden.")
        except Fehler as f:
            self.antwort(f.status, {"fehler": f.meldung})
        except klassen.KeinZugriff as f:
            self.antwort(403, {"fehler": str(f)})
        except (konten.KontoFehler, klassen.KlassenFehler, moodle.MoodleFehler, qr.QrFehler, updates.UpdateFehler,
                unterrichtstage.TageFehler, kalender.KalenderFehler, pakete.PaketFehler, lernplan.PlanFehler,
                rueckmeldung.RueckmeldungFehler, termine.TerminFehler, diktat.DiktatFehler,
                nachweise.NachweisFehler, teams.TeamFehler, zeitplan.ZeitplanFehler) as f:
            self.antwort(400, {"fehler": str(f)})
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError, socket.timeout):
            pass
        except Exception as f:   # unerwartet: protokollieren, aber nichts Internes verraten
            print("FEHLER %s %s: %r" % (methode, _ohne_code(pfad), f), file=sys.stderr, flush=True)
            try:
                self.antwort(500, {"fehler": "Interner Fehler. Bitte später noch einmal versuchen."})
            except OSError:
                pass
        finally:
            if con is not None:
                con.close()

    def seite(self, con, pfad):
        if pfad == "/":
            if self.nur_schueler:
                return self.datei(os.path.join(WEB_DIR, "start.html"), "text/html")
            if konten.sitzung_pruefen(con, self.cookie()):
                return self.umleiten("/lehrer")
            return self.umleiten("/einrichtung" if not konten.hat_konten(con) else "/anmelden")
        if pfad in SEITEN:
            return self.datei(os.path.join(WEB_DIR, SEITEN[pfad]), "text/html")
        if SCHUELER_SEITE.fullmatch(pfad):
            return self.datei(os.path.join(WEB_DIR, "schueler.html"), "text/html")
        treffer = STATISCH.fullmatch(pfad)
        if treffer:
            return self.datei(os.path.join(WEB_DIR, treffer.group(1)))
        if pfad == "/ca.crt":
            return self.datei(os.path.join(TLS_DIR, "ca.crt"), "application/x-x509-ca-cert")
        raise Fehler(404, "Nicht gefunden.")

    def log_message(self, fmt, *args):   # keine Zugriffsprotokolle (Zugangscodes stehen in der Adresse)
        pass


def _ohne_code(pfad):
    return re.sub(r"/s/[A-Za-z0-9-]+", "/s/…", pfad)


# --- Anmeldung und Konten ---

def api_status(h, con, daten):
    h.antwort(200, {"version": VERSION, "eingerichtet": konten.hat_konten(con)})


def api_einrichtung(h, con, daten):
    wartezeit = SPERRE.wartezeit(h.adresse())
    if wartezeit:
        raise Fehler(429, "Zu viele Fehlversuche. Bitte %d Sekunden warten." % wartezeit)
    with db.transaktion(con):
        try:
            konto = konten.einrichten(con, daten.get("code"), daten.get("kuerzel"), daten.get("name"), daten.get("passwort"))
        except konten.KontoFehler as f:
            if "Einrichtungscode" in str(f):
                SPERRE.fehlversuch(h.adresse())
            raise
    print("Einrichtung: erstes Admin-Konto %s angelegt" % konto["kuerzel"], flush=True)
    wert, _ = konten.anmelden(con, konto["kuerzel"], daten.get("passwort"))
    h.antwort(200, {"konto": konto}, extra=[h.cookie_setzen(wert, konten.SITZUNG_S)])


def api_anmelden(h, con, daten):
    wartezeit = SPERRE.wartezeit(h.adresse())
    if wartezeit:
        raise Fehler(429, "Zu viele Fehlversuche. Bitte %d Sekunden warten." % wartezeit)
    try:
        wert, konto = konten.anmelden(con, daten.get("kuerzel"), daten.get("passwort"))
    except konten.KontoFehler:
        dauer = SPERRE.fehlversuch(h.adresse())
        print("Anmeldung fehlgeschlagen: %s von %s%s" % ((daten.get("kuerzel") or "")[:12], h.adresse(),
              ", gesperrt fuer %d s" % dauer if dauer else ""), flush=True)
        raise
    SPERRE.erfolg(h.adresse())
    h.antwort(200, {"konto": konto}, extra=[h.cookie_setzen(wert, konten.SITZUNG_S)])


def api_abmelden(h, con, daten):
    konten.abmelden(con, h.cookie())
    h.antwort(200, {"ok": True}, extra=[h.cookie_setzen("", 0)])


def api_ich(h, con, daten):
    k = h.konto(con, vorlaeufig_ok=True)
    h.antwort(200, {"konto": k, "version": VERSION, "update": updates.kurz() if k["rolle"] == "admin" else None,
                    "zu_pruefen": rueckmeldung.zaehler(con, k), "nachweise": nachweise.zaehler(con, k)})


def api_passwort(h, con, daten):
    k = h.konto(con, vorlaeufig_ok=True)
    with db.transaktion(con):
        konten.passwort_aendern(con, k["id"], daten.get("alt"), daten.get("neu"))
    wert = konten.sitzung_erzeugen(con, k["id"])   # alte Anmeldungen sind jetzt ungueltig, diese bleibt
    h.antwort(200, {"konto": konten.holen(con, k["id"])}, extra=[h.cookie_setzen(wert, konten.SITZUNG_S)])


def _admin(h, con):
    k = h.konto(con)
    if k["rolle"] != "admin":
        raise Fehler(403, "Nur für Admins.")
    return k


def api_lehrkraefte(h, con, daten):
    h.konto(con)
    h.antwort(200, {"lehrkraefte": konten.liste(con)})


def api_lehrkraft_anlegen(h, con, daten):
    a = _admin(h, con)
    with db.transaktion(con):
        neu = konten.anlegen(con, daten.get("kuerzel"), daten.get("name"), daten.get("rolle") or "lehrkraft", daten.get("passwort"))
    print("Konto %s angelegt von %s" % (neu["kuerzel"], a["kuerzel"]), flush=True)
    h.antwort(200, {"lehrkraft": neu})


def api_lehrkraft_aendern(h, con, daten, lid):
    a = _admin(h, con)
    lid = _ganzzahl(lid)
    with db.transaktion(con):
        k = konten.aendern(con, lid, name=daten.get("name"), rolle=daten.get("rolle"), gesperrt=daten.get("gesperrt"))
        if daten.get("passwort"):
            konten.passwort_setzen(con, lid, daten["passwort"], vorlaeufig=True)
    print("Konto %s geaendert von %s" % (k["kuerzel"], a["kuerzel"]), flush=True)
    h.antwort(200, {"lehrkraft": konten.holen(con, lid)})


# --- Klassen ---

def api_klassen(h, con, daten):
    k = h.konto(con)
    h.antwort(200, {"klassen": klassen.liste(con, k, archiv=h.abfrage("archiv") == "1")})


def api_klasse_anlegen(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        neu = klassen.anlegen(con, k, daten.get("name"), daten.get("schuljahr"), daten.get("moodle_kurs"))
    h.antwort(200, {"klasse": neu})


def api_klasse(h, con, daten, kid):
    h.antwort(200, {"klasse": klassen.holen(con, h.konto(con), _ganzzahl(kid))})


def api_klasse_aendern(h, con, daten, kid):
    k = h.konto(con)
    with db.transaktion(con):
        neu = klassen.aendern(con, k, _ganzzahl(kid), daten)
    h.antwort(200, {"klasse": neu})


def api_klasse_lehrkraft(h, con, daten, kid):
    k = h.konto(con)
    kid = _ganzzahl(kid)
    with db.transaktion(con):
        klassen.lehrkraft_setzen(con, k, kid, _ganzzahl(daten.get("lehrkraft_id")), daten.get("rolle"))
    h.antwort(200, {"klasse": klassen.holen(con, k, kid) if klassen.zugriff(con, kid, k) else None})


def api_schueler_anlegen(h, con, daten, kid):
    k = h.konto(con)
    with db.transaktion(con):
        s = klassen.schueler_anlegen(con, k, _ganzzahl(kid), daten.get("vorname"), daten.get("nachname"))
    h.antwort(200, {"schueler": s})


def api_schueler_aendern(h, con, daten, kid, sid):
    k = h.konto(con)
    with db.transaktion(con):
        s = klassen.schueler_aendern(con, k, _ganzzahl(kid), _ganzzahl(sid), daten)
    h.antwort(200, {"schueler": s})


def _moodle_abgleich(con, kid, daten):
    eintraege, art = moodle.lesen(daten.get("datei"))
    vorhandene = klassen.schueler_liste(con, kid, nur_aktiv=False)
    return moodle.abgleich(vorhandene, eintraege), art


def api_moodle_vorschau(h, con, daten, kid):
    k = h.konto(con)
    kid = _ganzzahl(kid)
    klassen.pruefen(con, kid, k, "aendern")
    zeilen, art = _moodle_abgleich(con, kid, daten)
    h.antwort(200, {"format": art, "zeilen": zeilen})


def api_moodle_uebernehmen(h, con, daten, kid):
    """Uebernimmt die Datei: legt alle neuen Schueler an, macht archivierte wieder aktiv und archiviert nur die
    ausdruecklich angekreuzten, die nicht mehr in Moodle stehen."""
    k = h.konto(con)
    kid = _ganzzahl(kid)
    archivieren = {_ganzzahl(i) for i in daten.get("archivieren") or []}
    with db.transaktion(con):
        klassen.pruefen(con, kid, k, "aendern")
        zeilen, art = _moodle_abgleich(con, kid, daten)
        zaehler = {"neu": 0, "reaktiviert": 0, "archiviert": 0}
        for z in zeilen:
            if z["aktion"] == "neu":
                sid = klassen.schueler_einfuegen(con, kid, z["vorname"] or "-", z["nachname"])
                db.ereignis(con, kid, sid, "lehrkraft", k["kuerzel"], "schueler_angelegt",
                            name="%s %s" % (z["vorname"], z["nachname"]), quelle="moodle")
                zaehler["neu"] += 1
            elif z["aktion"] == "reaktivieren":
                klassen.schueler_aendern(con, k, kid, z["schueler_id"], {"aktiv": True})
                zaehler["reaktiviert"] += 1
            elif z["aktion"] == "fehlt" and z["schueler_id"] in archivieren:
                klassen.schueler_aendern(con, k, kid, z["schueler_id"], {"aktiv": False})
                zaehler["archiviert"] += 1
        db.ereignis(con, kid, None, "lehrkraft", k["kuerzel"], "moodle_import", format=art, **zaehler)
    h.antwort(200, {"ergebnis": zaehler, "klasse": klassen.holen(con, k, kid)})


def _schueler_adresse(h, con):
    eigen = db.einstellung(con, "schueler_adresse")
    if eigen:
        return eigen.rstrip("/")
    port = "" if HTTP_PORT == 80 else ":%d" % HTTP_PORT
    return "http://%s%s" % (h.host(), port)


def api_qr_karten(h, con, daten, kid):
    k = h.konto(con)
    kid = _ganzzahl(kid)
    klassen.pruefen(con, kid, k, "aendern")
    klasse = con.execute("SELECT name FROM klasse WHERE id = ?", (kid,)).fetchone()["name"]
    nur = h.abfrage("schueler")
    liste = klassen.schueler_liste(con, kid)
    if nur:
        liste = [s for s in liste if s["id"] == _ganzzahl(nur)]
    inhalt = pdf.qr_karten(klasse, liste, _schueler_adresse(h, con))
    h.herunterladen(inhalt, "application/pdf", "QR-Karten %s.pdf" % klasse)


def api_qr_svg(h, con, daten, kid, sid):
    k = h.konto(con)
    kid = _ganzzahl(kid)
    klassen.pruefen(con, kid, k, "aendern")
    s = con.execute("SELECT code FROM schueler WHERE id = ? AND klasse_id = ?", (_ganzzahl(sid), kid)).fetchone()
    if s is None:
        raise Fehler(404, "Nicht gefunden.")
    url = "%s/s/%s" % (_schueler_adresse(h, con), s["code"])
    h.antwort(200, qr.svg(url).encode("utf-8"), "image/svg+xml; charset=utf-8", extra=[("X-Adresse", url)])


# --- Unterrichtstage (Stufe B) ---

def _zeitraum(h, vor=14, nach=84):
    heute = db.heute()
    von = h.abfrage("von") or (heute - datetime.timedelta(days=vor)).isoformat()
    bis = h.abfrage("bis") or (heute + datetime.timedelta(days=nach)).isoformat()
    von, bis = unterrichtstage.datum(von), unterrichtstage.datum(bis)
    if (bis - von).days > 400:
        raise Fehler(400, "Höchstens 400 Tage auf einmal.")
    return von, bis


def api_tage(h, con, daten, kid):
    k = h.konto(con)
    kid = _ganzzahl(kid)
    klassen.pruefen(con, kid, k, "lesen")
    von, bis = _zeitraum(h)
    h.antwort(200, {"regeln": unterrichtstage.regeln(con, kid), "besondere": unterrichtstage.besondere(con, kid, von.isoformat()),
                    "tage": unterrichtstage.tage(con, kid, von, bis), "heute": db.heute().isoformat(),
                    "schuljahr": [d.isoformat() for d in unterrichtstage.schuljahr_grenzen()]})


def api_regel_anlegen(h, con, daten, kid):
    k = h.konto(con)
    with db.transaktion(con):
        unterrichtstage.regel_anlegen(con, k, _ganzzahl(kid), daten)
    api_tage(h, con, {}, kid)


def api_regel_aendern(h, con, daten, kid, rid):
    k = h.konto(con)
    with db.transaktion(con):
        unterrichtstage.regel_aendern(con, k, _ganzzahl(kid), _ganzzahl(rid), daten)
    api_tage(h, con, {}, kid)


def api_besonders_anlegen(h, con, daten, kid):
    k = h.konto(con)
    with db.transaktion(con):
        unterrichtstage.besonders_anlegen(con, k, _ganzzahl(kid), daten)
    api_tage(h, con, {}, kid)


def api_besonders_entfernen(h, con, daten, kid, bid):
    k = h.konto(con)
    with db.transaktion(con):
        unterrichtstage.besonders_entfernen(con, k, _ganzzahl(kid), _ganzzahl(bid))
    api_tage(h, con, {}, kid)


def api_ferien(h, con, daten):
    h.konto(con)
    h.antwort(200, {"ferien": unterrichtstage.ferien_liste(con, (db.heute() - datetime.timedelta(days=60)).isoformat()),
                    "schulkalender": kalender.abo_status(con, "schule"),
                    "stichwoerter": db.einstellung(con, "schulkalender_stichwoerter", kalender.STICHWOERTER),
                    "pakete_da": kalender.icalendar is not None})


def api_ferien_anlegen(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        unterrichtstage.ferien_anlegen(con, k, daten)
    api_ferien(h, con, {})


def api_ferien_entfernen(h, con, daten, fid):
    k = h.konto(con)
    with db.transaktion(con):
        unterrichtstage.ferien_entfernen(con, k, _ganzzahl(fid))
    api_ferien(h, con, {})


def api_schulkalender(h, con, daten):
    _admin(h, con)
    if "stichwoerter" in daten:
        woerter = ", ".join(w.strip() for w in str(daten["stichwoerter"] or "").split(",") if w.strip())[:300]
        db.einstellung_setzen(con, "schulkalender_stichwoerter", woerter or kalender.STICHWOERTER)
    if daten.get("url"):
        kalender.abo_setzen(con, "schule", None, daten["url"])
    elif daten.get("abrufen"):
        kalender.abrufen(con, "schule")
    api_ferien(h, con, {})


def api_schulkalender_entfernen(h, con, daten):
    _admin(h, con)
    kalender.abo_entfernen(con, "schule", None)
    api_ferien(h, con, {})


# --- Lernpakete (Stufe B) ---

def api_pakete(h, con, daten, kid):
    h.antwort(200, {"pakete": pakete.liste(con, h.konto(con), _ganzzahl(kid))})


def api_vorlagen(h, con, daten):
    h.antwort(200, {"vorlagen": pakete.vorlagen(con, h.konto(con))})


def api_paket_anlegen(h, con, daten):
    k = h.konto(con)
    kid = daten.get("klasse_id")
    with db.transaktion(con):
        pid = pakete.anlegen(con, k, _ganzzahl(kid) if kid is not None else None, daten.get("titel"), daten.get("lernfeld"))
    h.antwort(200, {"paket": pakete.holen(con, k, pid)})


def api_paket(h, con, daten, pid):
    h.antwort(200, {"paket": pakete.holen(con, h.konto(con), _ganzzahl(pid))})


def _paket_schritt(funktion):
    """POST-Schnittstelle, die etwas am Paket aendert und das ganze Paket zurueckgibt."""
    def api(h, con, daten, pid, *ids):
        k = h.konto(con)
        pid = _ganzzahl(pid)
        with db.transaktion(con):
            funktion(con, k, pid, *[_ganzzahl(i) for i in ids], daten)
        h.antwort(200, {"paket": pakete.holen(con, k, pid)})
    return api


def api_paket_kopieren(h, con, daten, pid):
    k = h.konto(con)
    ziel = daten.get("ziel_klasse_id")
    with db.transaktion(con):
        neu = pakete.kopieren(con, k, _ganzzahl(pid), _ganzzahl(ziel) if ziel is not None else None, daten.get("titel"))
    h.antwort(200, {"paket": pakete.holen(con, k, neu)})


# --- Einstellungen, Sicherung, Update ---

def api_einstellungen(h, con, daten):
    _admin(h, con)
    h.antwort(200, {"schueler_adresse": db.einstellung(con, "schueler_adresse", ""),
                    "vorschlag": "http://%s%s" % (h.host(), "" if HTTP_PORT == 80 else ":%d" % HTTP_PORT)})


def api_einstellungen_aendern(h, con, daten):
    _admin(h, con)
    adresse = (daten.get("schueler_adresse") or "").strip().rstrip("/")
    if adresse and not re.fullmatch(r"https?://[A-Za-z0-9.-]{1,253}(:\d{1,5})?", adresse):
        raise Fehler(400, "Bitte eine Adresse wie http://192.168.7.3 oder http://lernbuero angeben.")
    with db.transaktion(con):
        if adresse:
            db.einstellung_setzen(con, "schueler_adresse", adresse)
        else:
            con.execute("DELETE FROM einstellung WHERE schluessel = 'schueler_adresse'")
    api_einstellungen(h, con, {})


def api_sicherung(h, con, daten):
    _admin(h, con)
    pfad = updates.sicherung(con)
    try:
        with open(pfad, "rb") as f:
            inhalt = f.read()
    finally:
        os.remove(pfad)
    h.herunterladen(inhalt, "application/zip", "lernbuero-sicherung-%s.zip" % db.jetzt()[:10])


def api_update(h, con, daten):
    _admin(h, con)
    h.antwort(200, updates.stand(DATEN_DIR))


def api_update_anfordern(h, con, daten):
    a = _admin(h, con)
    updates.anfordern(DATEN_DIR, daten.get("art"))
    print("Update (%s) angefordert von %s" % (daten.get("art"), a["kuerzel"]), flush=True)
    h.antwort(200, updates.stand(DATEN_DIR))


def api_update_sicherung(h, con, daten, name):
    _admin(h, con)
    with open(updates.sicherung_pfad(DATEN_DIR, name), "rb") as f:
        h.herunterladen(f.read(), "application/zip", name)


# --- Schuelerseiten (ueber den Code in der Adresse) ---

def _schueler(h, con, code):
    wartezeit = CODE_SPERRE.wartezeit(h.adresse())
    if wartezeit:
        raise Fehler(429, "Zu viele falsche Codes. Bitte %d Sekunden warten." % wartezeit)
    s = klassen.per_code(con, code)
    if s is None:
        CODE_SPERRE.fehlversuch(h.adresse())
        raise Fehler(404, "Diesen Code gibt es nicht (mehr). Bitte bei der Lehrkraft eine neue Karte holen.")
    CODE_SPERRE.erfolg(h.adresse())
    return s


def api_schueler_ich(h, con, daten, code):
    s = _schueler(h, con, code)
    h.antwort(200, {"vorname": s["vorname"], "nachname": s["nachname"], "klasse": s["klasse"],
                    "einschaetzer": s["einschaetzer"], "code": klassen.code_anzeigen(klassen.code_normalisieren(code))})


def _schueler_alles(con, s):
    """Der ganze Stand der Schuelerseite: Plan, Hilfe-Knopf, Termine, Zahl der neuen Rueckmeldungen."""
    z = lernplan.zustand(con, s)
    z["hilfe"] = termine.hilfe_stand(con, s)
    z["termine"] = termine.termine_schueler(con, s)
    z["ungelesen"] = rueckmeldung.fuer_schueler(con, s)["ungelesen"]
    return z


def api_schueler_plan(h, con, daten, code):
    h.antwort(200, _schueler_alles(con, _schueler(h, con, code)))


def _schueler_schritt(funktion):
    """POST der Schuelerseite: aendert etwas am eigenen Plan und gibt den ganzen Stand zurueck."""
    def api(h, con, daten, code):
        s = _schueler(h, con, code)
        with db.transaktion(con):
            funktion(con, s, daten)
        h.antwort(200, _schueler_alles(con, s))
    return api


def api_schueler_hilfe(h, con, daten, code):
    h.antwort(200, termine.hilfe_stand(con, _schueler(h, con, code)))


def api_schueler_rueckmeldungen(h, con, daten, code):
    h.antwort(200, rueckmeldung.fuer_schueler(con, _schueler(h, con, code)))


def api_schueler_plaetze(h, con, daten, code):
    s = _schueler(h, con, code)
    art = h.abfrage("art", "feedback")
    if art not in termine.TERMINARTEN:
        raise Fehler(400, "Ungültige Art.")
    h.antwort(200, {"plaetze": termine.freie_plaetze(con, s, art)})


def _optional_id(daten, name):
    return _ganzzahl(daten.get(name)) if daten.get(name) not in (None, "") else None


def _ganzzahl_feld(daten, name):
    return _ganzzahl(daten.get(name))


SCHUELER_SCHRITTE = {
    "plan": lambda con, s, d: lernplan.planen(con, s, _ganzzahl_feld(d, "aufgabe_id"), d.get("hinzu") or [], d.get("weg") or []),
    "wahl": lambda con, s, d: lernplan.waehlen(con, s, _ganzzahl_feld(d, "aufgabe_id"), bool(d.get("gewaehlt", True))),
    "ausfall": lambda con, s, d: (lernplan.ausfall_verschieben if d.get("aktion") == "verschieben" else lernplan.ausfall_entfernen)(con, s),
    "abschluss": lambda con, s, d: lernplan.tag_abschliessen(con, s, d.get("eintraege") or []),
    "kann": lambda con, s, d: lernplan.kann_einschaetzen(con, s, _ganzzahl_feld(d, "kann_id"), d.get("stufe")),
    "fertig": lambda con, s, d: rueckmeldung.fertig_melden(con, s, _ganzzahl_feld(d, "aufgabe_id"), rueckmeldung.json_kann(d.get("kann"))),
    "fertig_zurueck": lambda con, s, d: rueckmeldung.zurueckziehen(con, s, _ganzzahl_feld(d, "meldung_id")),
    "gelesen": lambda con, s, d: rueckmeldung.gelesen(con, s),
    "empfehlung": lambda con, s, d: rueckmeldung.empfehlung_erledigt(con, s, _ganzzahl_feld(d, "empfehlung_id"), bool(d.get("erledigt", True))),
    "hilfe": lambda con, s, d: (termine.hilfe_zurueckziehen(con, s) if d.get("aktion") == "zurueck"
                                else termine.hilfe_rufen(con, s, _optional_id(d, "aufgabe_id"))),
    "termin": lambda con, s, d: termine.buchen(con, s, _ganzzahl_feld(d, "zeitfenster_id"), d.get("datum"), str(d.get("beginn") or ""),
                                               d.get("art") or "feedback", d.get("anlass")),
    "termin_absagen": lambda con, s, d: termine.absagen_schueler(con, s, _ganzzahl_feld(d, "termin_id")),
    "team": lambda con, s, d: teams.einladen(con, s, d.get("bereich"), _ganzzahl_feld(d, "bezug_id"), _ganzzahl_feld(d, "partner_id")),
    "team_antwort": lambda con, s, d: teams.antworten(con, s, _ganzzahl_feld(d, "team_id"), bool(d.get("annehmen"))),
    "markieren": lambda con, s, d: lernplan.markieren(con, s, _ganzzahl_feld(d, "aufgabe_id"), d.get("datum"), d.get("ampel") or None,
                                                      problem=d.get("problem")),
    "bereit": lambda con, s, d: nachweise.bereit_melden(con, s, _ganzzahl_feld(d, "nachweis_id"), rueckmeldung.json_kann(d.get("kann"))),
    "bereit_zurueck": lambda con, s, d: nachweise.zurueckziehen(con, s, _ganzzahl_feld(d, "versuch_id")),
}


# --- Lehrkraft: Jetzt, Rueckmeldung, Empfehlungen, Zeitfenster (Stufe D) ---

def api_jetzt(h, con, daten):
    k = h.konto(con)
    h.antwort(200, {"hilfe": termine.hilfe_reihe(con, k), "termine": termine.termine_heute(con, k),
                    "eingang": rueckmeldung.eingang(con, k), "entwuerfe": rueckmeldung.entwuerfe(con, k),
                    "bereit": nachweise.bereit_liste(con, k), "zeitplan": zeitplan.liste_lk(con, k)})


def api_hilfe_erledigt(h, con, daten, hid):
    k = h.konto(con)
    with db.transaktion(con):
        termine.hilfe_erledigt(con, k, _ganzzahl(hid))
    h.antwort(200, {"hilfe": termine.hilfe_reihe(con, k)})


def api_rueckmeldung_vorlage(h, con, daten):
    k = h.konto(con)

    def zahl(n):
        return _ganzzahl(h.abfrage(n)) if h.abfrage(n) else None
    h.antwort(200, rueckmeldung.vorlage(con, k, _ganzzahl(h.abfrage("schueler")), meldung_id=zahl("meldung"), termin_id=zahl("termin"),
                                        rueckmeldung_id=zahl("rueckmeldung"), aufgabe_id=zahl("aufgabe"), versuch_id=zahl("versuch")))


def api_rueckmeldung_speichern(h, con, daten):
    k = h.konto(con)
    with db.transaktion(con):
        if daten.get("personen"):
            rid = rueckmeldung.speichern_team(con, k, daten, freigeben=bool(daten.get("freigeben")))
        else:
            rid = rueckmeldung.speichern(con, k, daten, freigeben=bool(daten.get("freigeben")))
    h.antwort(200, {"id": rid, "freigegeben": bool(daten.get("freigeben"))})


def api_rueckmeldung_verwerfen(h, con, daten, rid):
    k = h.konto(con)
    with db.transaktion(con):
        rueckmeldung.verwerfen(con, k, _ganzzahl(rid))
    h.antwort(200, {"ok": True})


def _schueler_der_klasse(con, kid, sid):
    s = con.execute("SELECT id FROM schueler WHERE id = ? AND klasse_id = ?", (_ganzzahl(sid), _ganzzahl(kid))).fetchone()
    if s is None:
        raise Fehler(404, "Diesen Schüler gibt es in der Klasse nicht.")
    return s["id"]


def api_schueler_rueckmeldungen_lk(h, con, daten, kid, sid):
    k = h.konto(con)
    h.antwort(200, rueckmeldung.fuer_lehrkraft(con, k, _schueler_der_klasse(con, kid, sid)))


def api_empfehlung_anlegen(h, con, daten, kid, sid):
    k = h.konto(con)
    s = _schueler_der_klasse(con, kid, sid)
    with db.transaktion(con):
        rueckmeldung.empfehlung_anlegen(con, k, s, daten)
    h.antwort(200, rueckmeldung.fuer_lehrkraft(con, k, s))


def api_empfehlung_entfernen(h, con, daten, eid):
    k = h.konto(con)
    with db.transaktion(con):
        rueckmeldung.empfehlung_entfernen(con, k, _ganzzahl(eid))
    h.antwort(200, {"ok": True})


def api_zeitfenster(h, con, daten, kid):
    k = h.konto(con)
    kid = _ganzzahl(kid)
    h.antwort(200, {"zeitfenster": termine.zeitfenster_liste(con, k, kid), "belegung": termine.belegung(con, k, kid),
                    "rolle": klassen.zugriff(con, kid, k)})


def api_zeitfenster_anlegen(h, con, daten, kid):
    k = h.konto(con)
    with db.transaktion(con):
        e = termine.zeitfenster_anlegen(con, k, _ganzzahl(kid), daten)
    h.antwort(200, e)


def api_zeitfenster_entfernen(h, con, daten, zid):
    k = h.konto(con)
    with db.transaktion(con):
        n = termine.zeitfenster_entfernen(con, k, _ganzzahl(zid))
    h.antwort(200, {"abgesagt": n})


def api_versuch_frei(h, con, daten, vid):
    k = h.konto(con)
    with db.transaktion(con):
        nachweise.freischalten(con, k, _ganzzahl(vid), bool(daten.get("frei", True)))
    h.antwort(200, {"bereit": nachweise.bereit_liste(con, k)})


def api_schueler_nachweise_lk(h, con, daten, kid, sid):
    k = h.konto(con)
    h.antwort(200, nachweise.fuer_lehrkraft(con, k, _schueler_der_klasse(con, kid, sid)))


def api_gespraech_plaetze(h, con, daten, mid):
    k = h.konto(con)
    h.antwort(200, {"plaetze": termine.gespraech_plaetze(con, k, _ganzzahl(mid))})


def api_gespraech_eintragen(h, con, daten, mid):
    k = h.konto(con)
    with db.transaktion(con):
        termine.gespraech_eintragen(con, k, _ganzzahl(mid), _ganzzahl(daten.get("zeitfenster_id")), daten.get("datum"),
                                    str(daten.get("beginn") or ""), daten.get("hinweis") or "")
    h.antwort(200, {"gespraech": termine.gespraech(con, _ganzzahl(mid))})


def api_mitschueler(h, con, daten, code):
    h.antwort(200, {"mitschueler": teams.mitschueler(con, _schueler(h, con, code))})


def api_teams(h, con, daten, kid):
    k = h.konto(con)
    paket = h.abfrage("paket")
    h.antwort(200, teams.liste_klasse(con, k, _ganzzahl(kid), _ganzzahl(paket) if paket else None))


def api_team_bilden(h, con, daten, kid):
    k = h.konto(con)
    with db.transaktion(con):
        teams.bilden(con, k, _ganzzahl(kid), daten.get("bereich"), _ganzzahl(daten.get("bezug_id")), _ganzzahl(daten.get("a_id")),
                     _ganzzahl(daten.get("b_id")))
    h.antwort(200, {"ok": True})


def api_team_aufloesen(h, con, daten, tid):
    k = h.konto(con)
    with db.transaktion(con):
        teams.aufloesen(con, k, _ganzzahl(tid))
    h.antwort(200, {"ok": True})


def api_zeitplan_gesehen(h, con, daten, pid):
    k = h.konto(con)
    with db.transaktion(con):
        zeitplan.gesehen(con, k, _ganzzahl(pid))
    h.antwort(200, {"zeitplan": zeitplan.liste_lk(con, k)})


def api_zeitplan_verlauf(h, con, daten, kid, sid):
    k = h.konto(con)
    h.antwort(200, {"eintraege": zeitplan.verlauf(con, k, _schueler_der_klasse(con, kid, sid))})


def api_diktat_stand(h, con, daten):
    h.konto(con)
    h.antwort(200, diktat.stand(DATEN_DIR))


def api_diktat(h, con, daten):
    """Aufnahme als Rohdaten (audio/webm, audio/mp4 ...), nicht als JSON. Die Aufnahme wird nach dem Erkennen geloescht."""
    laenge = _ganzzahl(h.headers.get("Content-Length") or 0)
    if laenge > diktat.MAX_BYTES:
        raise Fehler(413, "Die Aufnahme ist zu lang. Bitte in mehreren Teilen diktieren.")
    roh = h.rfile.read(laenge) if laenge else b""
    if h.headers.get(KOPF) != "1":
        raise Fehler(403, "Anfrage abgelehnt.")
    h.konto(con)
    paket = h.abfrage("paket")
    vorgabe = diktat.fachwoerter(con, _ganzzahl(paket)) if paket else ""
    con.close()   # das Erkennen dauert: die Datenbank solange nicht offen halten
    h.antwort(200, diktat.erkennen(DATEN_DIR, roh, h.headers.get("Content-Type"), vorgabe))


def api_termin_absagen(h, con, daten, tid):
    k = h.konto(con)
    with db.transaktion(con):
        termine.absagen_lehrkraft(con, k, _ganzzahl(tid))
    h.antwort(200, {"ok": True})


def api_matrix(h, con, daten, kid):
    k = h.konto(con)
    kid = _ganzzahl(kid)
    klassen.pruefen(con, kid, k, "lesen")
    paket = h.abfrage("paket")
    h.antwort(200, lernplan.matrix(con, kid, _ganzzahl(paket) if paket else None))


def api_schuelerplan(h, con, daten, kid, sid):
    k = h.konto(con)
    kid = _ganzzahl(kid)
    klassen.pruefen(con, kid, k, "lesen")
    s = con.execute("SELECT * FROM schueler WHERE id = ? AND klasse_id = ?", (_ganzzahl(sid), kid)).fetchone()
    if s is None:
        raise Fehler(404, "Diesen Schüler gibt es in der Klasse nicht.")
    h.antwort(200, {"schueler": {"id": s["id"], "vorname": s["vorname"], "nachname": s["nachname"], "aktiv": bool(s["aktiv"])},
                    "einschaetzer": con.execute("SELECT einschaetzer FROM klasse WHERE id = ?", (kid,)).fetchone()[0],
                    "plan": lernplan.zustand(con, s), "entscheidungen": lernplan.entscheidungen(con, s["id"])})


ROUTEN = [(m, re.compile(p), f) for m, p, f in [
    ("GET", r"/api/s/([A-Za-z0-9-]{8,9})/plan", api_schueler_plan),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/plan", _schueler_schritt(SCHUELER_SCHRITTE["plan"])),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/wahl", _schueler_schritt(SCHUELER_SCHRITTE["wahl"])),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/ausfall", _schueler_schritt(SCHUELER_SCHRITTE["ausfall"])),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/abschluss", _schueler_schritt(SCHUELER_SCHRITTE["abschluss"])),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/kann", _schueler_schritt(SCHUELER_SCHRITTE["kann"])),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/fertig", _schueler_schritt(SCHUELER_SCHRITTE["fertig"])),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/fertig/zurueck", _schueler_schritt(SCHUELER_SCHRITTE["fertig_zurueck"])),
    ("GET", r"/api/s/([A-Za-z0-9-]{8,9})/rueckmeldungen", api_schueler_rueckmeldungen),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/rueckmeldungen/gelesen", _schueler_schritt(SCHUELER_SCHRITTE["gelesen"])),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/empfehlung", _schueler_schritt(SCHUELER_SCHRITTE["empfehlung"])),
    ("GET", r"/api/s/([A-Za-z0-9-]{8,9})/hilfe", api_schueler_hilfe),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/hilfe", _schueler_schritt(SCHUELER_SCHRITTE["hilfe"])),
    ("GET", r"/api/s/([A-Za-z0-9-]{8,9})/plaetze", api_schueler_plaetze),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/termin", _schueler_schritt(SCHUELER_SCHRITTE["termin"])),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/termin/absagen", _schueler_schritt(SCHUELER_SCHRITTE["termin_absagen"])),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/markieren", _schueler_schritt(SCHUELER_SCHRITTE["markieren"])),
    ("GET", r"/api/s/([A-Za-z0-9-]{8,9})/mitschueler", api_mitschueler),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/team", _schueler_schritt(SCHUELER_SCHRITTE["team"])),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/team/antwort", _schueler_schritt(SCHUELER_SCHRITTE["team_antwort"])),
    ("GET", r"/api/klassen/(\d+)/teams", api_teams),
    ("POST", r"/api/klassen/(\d+)/teams", api_team_bilden),
    ("POST", r"/api/teams/(\d+)/aufloesen", api_team_aufloesen),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/bereit", _schueler_schritt(SCHUELER_SCHRITTE["bereit"])),
    ("POST", r"/api/s/([A-Za-z0-9-]{8,9})/bereit/zurueck", _schueler_schritt(SCHUELER_SCHRITTE["bereit_zurueck"])),
    ("POST", r"/api/versuche/(\d+)/frei", api_versuch_frei),
    ("GET", r"/api/klassen/(\d+)/schueler/(\d+)/nachweise", api_schueler_nachweise_lk),
    ("GET", r"/api/meldungen/(\d+)/plaetze", api_gespraech_plaetze),
    ("POST", r"/api/meldungen/(\d+)/gespraech", api_gespraech_eintragen),
    ("POST", r"/api/zeitplan/(\d+)/gesehen", api_zeitplan_gesehen),
    ("GET", r"/api/klassen/(\d+)/schueler/(\d+)/zeitplan", api_zeitplan_verlauf),
    ("GET", r"/api/jetzt", api_jetzt),
    ("POST", r"/api/hilfe/(\d+)/erledigt", api_hilfe_erledigt),
    ("GET", r"/api/rueckmeldung/vorlage", api_rueckmeldung_vorlage),
    ("POST", r"/api/rueckmeldung", api_rueckmeldung_speichern),
    ("POST", r"/api/rueckmeldung/(\d+)/verwerfen", api_rueckmeldung_verwerfen),
    ("GET", r"/api/klassen/(\d+)/schueler/(\d+)/rueckmeldungen", api_schueler_rueckmeldungen_lk),
    ("POST", r"/api/klassen/(\d+)/schueler/(\d+)/empfehlungen", api_empfehlung_anlegen),
    ("POST", r"/api/empfehlungen/(\d+)/entfernen", api_empfehlung_entfernen),
    ("GET", r"/api/klassen/(\d+)/zeitfenster", api_zeitfenster),
    ("POST", r"/api/klassen/(\d+)/zeitfenster", api_zeitfenster_anlegen),
    ("POST", r"/api/zeitfenster/(\d+)/entfernen", api_zeitfenster_entfernen),
    ("POST", r"/api/termine/(\d+)/absagen", api_termin_absagen),
    ("GET", r"/api/diktat", api_diktat_stand),
    ("POST", r"/api/diktat", api_diktat),
    ("GET", r"/api/klassen/(\d+)/matrix", api_matrix),
    ("GET", r"/api/klassen/(\d+)/schueler/(\d+)/plan", api_schuelerplan),
    ("GET", r"/api/status", api_status),
    ("POST", r"/api/einrichtung", api_einrichtung),
    ("POST", r"/api/anmelden", api_anmelden),
    ("POST", r"/api/abmelden", api_abmelden),
    ("GET", r"/api/ich", api_ich),
    ("POST", r"/api/passwort", api_passwort),
    ("GET", r"/api/lehrkraefte", api_lehrkraefte),
    ("POST", r"/api/lehrkraefte", api_lehrkraft_anlegen),
    ("POST", r"/api/lehrkraefte/(\d+)", api_lehrkraft_aendern),
    ("GET", r"/api/klassen", api_klassen),
    ("POST", r"/api/klassen", api_klasse_anlegen),
    ("GET", r"/api/klassen/(\d+)", api_klasse),
    ("POST", r"/api/klassen/(\d+)", api_klasse_aendern),
    ("POST", r"/api/klassen/(\d+)/lehrkraft", api_klasse_lehrkraft),
    ("POST", r"/api/klassen/(\d+)/schueler", api_schueler_anlegen),
    ("POST", r"/api/klassen/(\d+)/schueler/(\d+)", api_schueler_aendern),
    ("POST", r"/api/klassen/(\d+)/moodle/vorschau", api_moodle_vorschau),
    ("POST", r"/api/klassen/(\d+)/moodle/uebernehmen", api_moodle_uebernehmen),
    ("GET", r"/api/klassen/(\d+)/qr-karten\.pdf", api_qr_karten),
    ("GET", r"/api/klassen/(\d+)/schueler/(\d+)/qr\.svg", api_qr_svg),
    ("GET", r"/api/einstellungen", api_einstellungen),
    ("POST", r"/api/einstellungen", api_einstellungen_aendern),
    ("GET", r"/api/sicherung\.zip", api_sicherung),
    ("GET", r"/api/update", api_update),
    ("POST", r"/api/update", api_update_anfordern),
    ("GET", r"/api/update/sicherung/(vor-update-[0-9_-]+\.zip)", api_update_sicherung),
    ("GET", r"/api/s/([A-Za-z0-9-]{8,9})", api_schueler_ich),
    ("GET", r"/api/klassen/(\d+)/tage", api_tage),
    ("POST", r"/api/klassen/(\d+)/regeln", api_regel_anlegen),
    ("POST", r"/api/klassen/(\d+)/regeln/(\d+)", api_regel_aendern),
    ("POST", r"/api/klassen/(\d+)/besonders", api_besonders_anlegen),
    ("POST", r"/api/klassen/(\d+)/besonders/(\d+)/entfernen", api_besonders_entfernen),
    ("GET", r"/api/ferien", api_ferien),
    ("POST", r"/api/ferien", api_ferien_anlegen),
    ("POST", r"/api/ferien/(\d+)/entfernen", api_ferien_entfernen),
    ("POST", r"/api/schulkalender", api_schulkalender),
    ("POST", r"/api/schulkalender/entfernen", api_schulkalender_entfernen),
    ("GET", r"/api/klassen/(\d+)/pakete", api_pakete),
    ("GET", r"/api/vorlagen", api_vorlagen),
    ("POST", r"/api/pakete", api_paket_anlegen),
    ("GET", r"/api/pakete/(\d+)", api_paket),
    ("POST", r"/api/pakete/(\d+)", _paket_schritt(pakete.aendern)),
    ("POST", r"/api/pakete/(\d+)/aufgaben", _paket_schritt(pakete.aufgabe_anlegen)),
    ("POST", r"/api/pakete/(\d+)/aufgaben/(\d+)", _paket_schritt(pakete.aufgabe_aendern)),
    ("POST", r"/api/pakete/(\d+)/gruppen", _paket_schritt(pakete.gruppe_anlegen)),
    ("POST", r"/api/pakete/(\d+)/gruppen/(\d+)", _paket_schritt(pakete.gruppe_aendern)),
    ("POST", r"/api/pakete/(\d+)/kann", _paket_schritt(pakete.kann_anlegen)),
    ("POST", r"/api/pakete/(\d+)/kann/(\d+)", _paket_schritt(pakete.kann_aendern)),
    ("POST", r"/api/pakete/(\d+)/nachweise", _paket_schritt(pakete.nachweis_anlegen)),
    ("POST", r"/api/pakete/(\d+)/nachweise/(\d+)", _paket_schritt(pakete.nachweis_aendern)),
    ("POST", r"/api/pakete/(\d+)/kopieren", api_paket_kopieren),
]]


ROH = {api_diktat}   # lesen ihren Inhalt selbst (kein JSON)


# --- HTTP neben HTTPS: nur die Schuelerseiten ---

class SchuelerHandler(Handler):
    nur_schueler = True


class TLSServer(ThreadingHTTPServer):
    """HTTPS. Der TLS-Handschlag laeuft im Thread der Anfrage, nicht in der Annahmeschleife: ein Client, der die
    Verbindung oeffnet und dann nichts schickt, haelt so niemanden auf."""
    daemon_threads = True
    ist_tls = True

    def __init__(self, adresse, handler, kontext, db_pfad):
        super().__init__(adresse, handler)
        self.kontext = kontext
        self.db_pfad = db_pfad

    def finish_request(self, request, client_address):
        request.settimeout(Handler.timeout)
        try:
            tls = self.kontext.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):   # z.B. Browser lehnt das Zertifikat ab
            return
        try:
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            # nur die Schreibrichtung schliessen und den Rest noch lesen: ein hartes Schliessen mit ungelesenen Daten
            # schickt ein RST, und der Browser verwirft dann womoeglich die schon gesendete Antwort
            try:
                tls.shutdown(socket.SHUT_WR)
                tls.settimeout(1.0)
                while tls.recv(4096):
                    pass
            except (OSError, ssl.SSLError):
                pass
            tls.close()


class HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    ist_tls = False

    def __init__(self, adresse, handler, db_pfad=None):
        super().__init__(adresse, handler)
        self.db_pfad = db_pfad


def takt(db_pfad):
    """Jede Minute: faellige Kalender-Abos holen (alle 30 Minuten je Abo)."""
    while True:
        con = None
        try:
            con = db.verbinden(db_pfad)
            kalender.faellige_abrufen(con)
        except Exception as f:
            print("FEHLER Takt: %r" % f, file=sys.stderr, flush=True)
        finally:
            if con is not None:
                con.close()
        time.sleep(60)


def tls_kontext():
    zert, schluessel = os.path.join(TLS_DIR, "server.crt"), os.path.join(TLS_DIR, "server.key")
    if not (os.path.exists(zert) and os.path.exists(schluessel)):
        return None
    kontext = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    kontext.minimum_version = ssl.TLSVersion.TLSv1_2
    kontext.load_cert_chain(zert, schluessel)
    return kontext


def main():
    con = db.oeffnen(DATEN_DIR)
    code = konten.einrichtungscode(con)
    con.close()
    db_pfad = db.pfad(DATEN_DIR)
    kontext = None if OHNE_TLS else tls_kontext()
    if kontext is None:
        if not OHNE_TLS:
            print("HTTPS aus: kein Zertifikat in %s (lernbuero-tls). Alles laeuft ueber HTTP." % TLS_DIR, flush=True)
        server = HTTPServer((BIND, HTTP_PORT), Handler, db_pfad)
        print("Lernbuero MT %s auf http://%s:%d" % (VERSION, BIND, HTTP_PORT), flush=True)
    else:
        server = TLSServer((BIND, HTTPS_PORT), Handler, kontext, db_pfad)
        schueler = HTTPServer((BIND, HTTP_PORT), SchuelerHandler, db_pfad)
        threading.Thread(target=schueler.serve_forever, daemon=True).start()
        print("Lernbuero MT %s auf https://%s:%d (http :%d fuer die Schuelerseiten)" % (VERSION, BIND, HTTPS_PORT, HTTP_PORT),
              flush=True)
    threading.Thread(target=takt, args=(db_pfad,), daemon=True).start()
    if code:
        print("Noch kein Konto: Einrichtung unter /einrichtung, Code mit  lernbuero einrichtungscode", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
