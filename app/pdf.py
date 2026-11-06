"""Kleiner PDF-Schreiber ohne Zusatzpakete (wie im TrackingDRS): Seiten mit Text (Helvetica aus den PDF-Grundschriften,
WinAnsi) und Rechtecken. Daraus die QR-Karten der Schueler: A4 hochkant, 2 x 5 Karten im Format 85 x 54 mm.
"""
from . import klassen, qr

MM = 72 / 25.4
A4 = (595.28, 841.89)
ERSATZ = {"✓": "OK", "→": "->", "…": "...", "–": "-", "„": '"', "“": '"', "”": '"', " ": " ", " ": " "}

# Zeichenbreiten von Helvetica (1/1000 em) fuer die haeufigsten Zeichen; der Rest gilt als 556
_BREITE = {" ": 278, "-": 333, ".": 278, ",": 278, ":": 278, "/": 278, "(": 333, ")": 333, "i": 222, "l": 222, "j": 222,
           "f": 278, "t": 278, "r": 333, "I": 278, "J": 500, "m": 833, "w": 722, "M": 833, "W": 944, "s": 500, "c": 500,
           "k": 500, "v": 500, "x": 500, "y": 500, "z": 500, "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611,
           "G": 778, "H": 722, "K": 667, "L": 556, "N": 722, "O": 778, "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611,
           "U": 722, "V": 667, "X": 667, "Y": 667, "Z": 611, "ä": 556, "ö": 556, "ü": 556, "ß": 611, "Ä": 667, "Ö": 778,
           "Ü": 722}


def _ersetzen(s):
    s = str(s or "")
    for a, b in ERSATZ.items():
        s = s.replace(a, b)
    return s


def _pdf_text(s):
    roh = _ersetzen(s).encode("cp1252", errors="replace")
    return roh.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def textbreite(s, groesse, fett=False):
    faktor = 1.06 if fett else 1.0
    return sum(_BREITE.get(c, 556) for c in _ersetzen(s)) * groesse / 1000 * faktor


def kuerzen(s, groesse, breite, fett=False):
    s = _ersetzen(s)
    if textbreite(s, groesse, fett) <= breite:
        return s
    while s and textbreite(s + "...", groesse, fett) > breite:
        s = s[:-1]
    return s.rstrip() + "..."


class Seite:
    def __init__(self):
        self.teile = []

    def text(self, x, y, s, groesse=10, fett=False, farbe=(0.11, 0.14, 0.2)):
        self.teile.append(b"BT %.3f %.3f %.3f rg /%s %.1f Tf %.2f %.2f Td (" % (farbe + (b"F2" if fett else b"F1", groesse, x, y))
                          + _pdf_text(s) + b") Tj ET")

    def rechteck(self, x, y, b, h, farbe=(0, 0, 0)):
        self.teile.append(b"%.3f %.3f %.3f rg %.3f %.3f %.3f %.3f re f" % (farbe + (x, y, b, h)))

    def rahmen(self, x, y, b, h, farbe=(0.8, 0.82, 0.86), gestrichelt=True, staerke=0.6):
        strich = b"[3 2] 0 d " if gestrichelt else b"[] 0 d "
        self.teile.append(b"%.3f %.3f %.3f RG %.2f w " % (farbe + (staerke,)) + strich + b"%.3f %.3f %.3f %.3f re S" % (x, y, b, h))

    def qr(self, x, y, kante, text):
        """QR-Code mit Ruhezone; (x, y) = linke untere Ecke, kante = Breite inklusive Ruhezone."""
        m = qr.matrix(text)
        n = len(m) + 8
        modul = kante / n
        self.rechteck(x, y, kante, kante, (1, 1, 1))
        for zy, zeile in enumerate(m):
            zx = 0
            while zx < len(zeile):   # Laeufe dunkler Module als ein Rechteck (kleinere Datei)
                if zeile[zx]:
                    start = zx
                    while zx < len(zeile) and zeile[zx]:
                        zx += 1
                    self.rechteck(x + (start + 4) * modul, y + kante - (zy + 5) * modul, (zx - start) * modul + 0.02, modul + 0.02)
                else:
                    zx += 1

    def inhalt(self):
        return b"\n".join(self.teile)


def dokument(seiten, titel="Lernbüro MT"):
    objekte = []

    def obj(inhalt):
        objekte.append(inhalt)
        return len(objekte)

    katalog = obj(None)
    seiten_obj = obj(None)
    f1 = obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kinder = []
    for s in seiten:
        daten = s.inhalt()
        strom = obj(b"<< /Length %d >>\nstream\n" % len(daten) + daten + b"\nendstream")
        kinder.append(obj(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R "
                          b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>" % (seiten_obj, A4[0], A4[1], strom, f1, f2)))
    objekte[katalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % seiten_obj
    objekte[seiten_obj - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kinder), len(kinder))
    info = obj(b"<< /Title (" + _pdf_text(titel) + b") /Producer (Lernbuero MT) >>")
    aus = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    lagen = []
    for i, inhalt in enumerate(objekte, 1):
        lagen.append(len(aus))
        aus += b"%d 0 obj\n" % i + inhalt + b"\nendobj\n"
    xref = len(aus)
    aus += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objekte) + 1)
    for lage in lagen:
        aus += b"%010d 00000 n \n" % lage
    aus += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objekte) + 1, katalog, info, xref)
    return bytes(aus)


BLAU = (0, 0.388, 0.612)
LEISE = (0.365, 0.404, 0.475)


def qr_karten(klasse, schueler, adresse):
    """klasse: Name, schueler: Zeilen (vorname, nachname, code), adresse: z. B. 'http://192.168.7.3'.
    Rueckgabe: PDF als Bytes."""
    b, h = 85 * MM, 54 * MM
    links = (A4[0] - 2 * b) / 2
    oben = A4[1] - (A4[1] - 5 * h) / 2
    seiten = []
    for nr, s in enumerate(schueler):
        if nr % 10 == 0:
            seite = Seite()
            seiten.append(seite)
        spalte, zeile = nr % 2, (nr % 10) // 2
        x, y = links + spalte * b, oben - (zeile + 1) * h
        seite.rahmen(x, y, b, h)
        url = "%s/s/%s" % (adresse.rstrip("/"), s["code"])
        kante = 40 * MM
        seite.qr(x + 5 * MM, y + (h - kante) / 2, kante, url)
        tx = x + 48 * MM
        breite = b - 50 * MM
        seite.rechteck(tx, y + h - 11 * MM, 6 * MM, 1.2 * MM, BLAU)
        seite.text(tx, y + h - 17 * MM, kuerzen(s["vorname"], 12, breite, True), 12, True)
        seite.text(tx, y + h - 22.5 * MM, kuerzen(s["nachname"], 12, breite, True), 12, True)
        seite.text(tx, y + h - 28.5 * MM, kuerzen(klasse + " · Lernbüro MT", 8, breite), 8, farbe=LEISE)
        seite.text(tx, y + 15 * MM, "Mit der Kamera scannen,", 7, farbe=LEISE)
        seite.text(tx, y + 11.5 * MM, "im Schulnetz.", 7, farbe=LEISE)
        seite.text(tx, y + 6 * MM, klassen.code_anzeigen(s["code"]), 11, True, BLAU)
    if not seiten:
        seiten.append(Seite())
    return dokument(seiten, "QR-Karten " + klasse)
