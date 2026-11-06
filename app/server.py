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

from . import VERSION, db, klassen, konten, moodle, pdf, qr, updates

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
                    daten = self.body() if methode == "POST" else {}
                    return funktion(self, con, daten, *treffer.groups())
            if methode == "POST":
                self.body()
            raise Fehler(404, "Nicht gefunden.")
        except Fehler as f:
            self.antwort(f.status, {"fehler": f.meldung})
        except klassen.KeinZugriff as f:
            self.antwort(403, {"fehler": str(f)})
        except (konten.KontoFehler, klassen.KlassenFehler, moodle.MoodleFehler, qr.QrFehler, updates.UpdateFehler) as f:
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
    h.antwort(200, {"konto": k, "version": VERSION, "update": updates.kurz() if k["rolle"] == "admin" else None})


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


ROUTEN = [(m, re.compile(p), f) for m, p, f in [
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
]]


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
    if code:
        print("Noch kein Konto: Einrichtung unter /einrichtung, Code mit  lernbuero einrichtungscode", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
