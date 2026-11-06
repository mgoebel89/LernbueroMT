"""QR-Code ohne Zusatzpakete (Byte-Modus, Fehlerkorrektur M, Version 1 bis 10), nach dem Verfahren der Norm
ISO/IEC 18004 in der bekannten Umsetzung von Project Nayuki (MIT-Lizenz) nachgebaut.

  matrix("http://lernbuero/s/K7Q4M2XD") -> Liste von Zeilen, True = dunkles Modul
  svg(text) -> SVG-Text mit 4 Modulen Ruhezone

Fuer die Zugangscodes reicht das reichlich: eine Adresse mit IP und Code hat rund 30 Zeichen (Version 3).
"""

# Fehlerkorrektur M: Korrektur-Codewoerter je Block und Anzahl Bloecke fuer Version 1..10
ECC_JE_BLOCK = (None, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26)
BLOECKE = (None, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5)
FORMAT_M = 0   # Kennbits der Stufe M im Formatfeld
MAX_VERSION = 10


class QrFehler(Exception):
    pass


# --- Reed-Solomon im Koerper GF(256) mit dem Polynom 0x11D ---

def _mal(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def rs_teiler(grad):
    ergebnis = [0] * (grad - 1) + [1]
    wurzel = 1
    for _ in range(grad):
        for j in range(grad):
            ergebnis[j] = _mal(ergebnis[j], wurzel)
            if j + 1 < grad:
                ergebnis[j] ^= ergebnis[j + 1]
        wurzel = _mal(wurzel, 0x02)
    return ergebnis


def rs_rest(daten, teiler):
    ergebnis = [0] * len(teiler)
    for b in daten:
        faktor = b ^ ergebnis.pop(0)
        ergebnis.append(0)
        for i, koeff in enumerate(teiler):
            ergebnis[i] ^= _mal(koeff, faktor)
    return ergebnis


# --- Groessen ---

def _roh_module(version):
    ergebnis = (16 * version + 128) * version + 64
    if version >= 2:
        n = version // 7 + 2
        ergebnis -= (25 * n - 10) * n - 55
        if version >= 7:
            ergebnis -= 36
    return ergebnis


def _daten_codewoerter(version):
    return _roh_module(version) // 8 - ECC_JE_BLOCK[version] * BLOECKE[version]


def _ausrichtung(version):
    if version == 1:
        return []
    n = version // 7 + 2
    schritt = (version * 8 + n * 3 + 5) // (n * 4 - 4) * 2
    groesse = version * 4 + 17
    ergebnis = [6]
    pos = groesse - 7
    for _ in range(n - 1):
        ergebnis.insert(1, pos)
        pos -= schritt
    return ergebnis


def format_bits(maske, stufe=FORMAT_M):
    daten = stufe << 3 | maske
    rest = daten
    for _ in range(10):
        rest = (rest << 1) ^ ((rest >> 9) * 0x537)
    return (daten << 10 | rest) ^ 0x5412


def _bit(x, i):
    return (x >> i) & 1 != 0


class _Symbol:
    def __init__(self, version):
        self.version = version
        self.n = version * 4 + 17
        self.modul = [[False] * self.n for _ in range(self.n)]
        self.fest = [[False] * self.n for _ in range(self.n)]

    def setzen(self, x, y, dunkel):
        self.modul[y][x] = dunkel
        self.fest[y][x] = True

    def muster(self):
        n = self.n
        for i in range(n):
            self.setzen(6, i, i % 2 == 0)
            self.setzen(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self.setzen(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = _ausrichtung(self.version)
        letzte = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == letzte) or (i == letzte and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.setzen(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.format(0)
        if self.version >= 7:
            rest = self.version
            for _ in range(12):
                rest = (rest << 1) ^ ((rest >> 11) * 0x1F25)
            bits = self.version << 12 | rest
            for i in range(18):
                b = _bit(bits, i)
                a, c = n - 11 + i % 3, i // 3
                self.setzen(a, c, b)
                self.setzen(c, a, b)

    def format(self, maske):
        bits = format_bits(maske)
        n = self.n
        for i in range(6):
            self.setzen(8, i, _bit(bits, i))
        self.setzen(8, 7, _bit(bits, 6))
        self.setzen(8, 8, _bit(bits, 7))
        self.setzen(7, 8, _bit(bits, 8))
        for i in range(9, 15):
            self.setzen(14 - i, 8, _bit(bits, i))
        for i in range(8):
            self.setzen(n - 1 - i, 8, _bit(bits, i))
        for i in range(8, 15):
            self.setzen(8, n - 15 + i, _bit(bits, i))
        self.setzen(8, n - 8, True)

    def codewoerter(self, daten):
        n, i = self.n, 0
        rechts = n - 1
        while rechts >= 1:
            if rechts == 6:
                rechts = 5
            for v in range(n):
                for j in range(2):
                    x = rechts - j
                    aufwaerts = ((rechts + 1) & 2) == 0
                    y = n - 1 - v if aufwaerts else v
                    if not self.fest[y][x] and i < len(daten) * 8:
                        self.modul[y][x] = _bit(daten[i >> 3], 7 - (i & 7))
                        i += 1
            rechts -= 2

    def maskieren(self, maske):
        bedingung = (lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
                     lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
                     lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
                     lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0)[maske]
        for y in range(self.n):
            for x in range(self.n):
                if not self.fest[y][x] and bedingung(x, y):
                    self.modul[y][x] = not self.modul[y][x]

    def strafe(self):
        """Bewertung nach den vier Regeln der Norm (vereinfacht bei Regel 3): kleiner ist besser."""
        n, m = self.n, self.modul
        punkte = 0
        linien = [m[y] for y in range(n)] + [[m[y][x] for y in range(n)] for x in range(n)]
        for linie in linien:
            lauf, farbe = 0, None
            for z in linie:
                if z == farbe:
                    lauf += 1
                else:
                    if lauf >= 5:
                        punkte += lauf - 2
                    farbe, lauf = z, 1
            if lauf >= 5:
                punkte += lauf - 2
            text = "".join("1" if z else "0" for z in linie)
            punkte += 40 * (("0000" + text).count("00001011101") + (text + "0000").count("10111010000"))
        for y in range(n - 1):
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    punkte += 3
        dunkel = sum(sum(1 for z in zeile if z) for zeile in m)
        gesamt = n * n
        k = (abs(dunkel * 20 - gesamt * 10) + gesamt - 1) // gesamt - 1
        return punkte + max(0, k) * 10


def _bits_anhaengen(bits, wert, laenge):
    for i in reversed(range(laenge)):
        bits.append((wert >> i) & 1)


def matrix(text):
    daten = text.encode("utf-8")
    for version in range(1, MAX_VERSION + 1):
        laenge_bits = 8 if version <= 9 else 16
        kapazitaet = _daten_codewoerter(version) * 8
        if 4 + laenge_bits + len(daten) * 8 <= kapazitaet:
            break
    else:
        raise QrFehler("Der Text ist zu lang für den QR-Code.")
    bits = []
    _bits_anhaengen(bits, 0b0100, 4)
    _bits_anhaengen(bits, len(daten), laenge_bits)
    for b in daten:
        _bits_anhaengen(bits, b, 8)
    bits += [0] * min(4, kapazitaet - len(bits))
    bits += [0] * (-len(bits) % 8)
    woerter = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    fuell = 0xEC
    while len(woerter) < kapazitaet // 8:
        woerter.append(fuell)
        fuell ^= 0xEC ^ 0x11

    # Fehlerkorrektur je Block, dann verschraenken
    anzahl, ecc = BLOECKE[version], ECC_JE_BLOCK[version]
    roh = _roh_module(version) // 8
    kurze = anzahl - roh % anzahl
    kurz_laenge = roh // anzahl
    teiler = rs_teiler(ecc)
    bloecke, k = [], 0
    for i in range(anzahl):
        teil = woerter[k:k + kurz_laenge - ecc + (0 if i < kurze else 1)]
        k += len(teil)
        rest = rs_rest(teil, teiler)
        if i < kurze:
            teil = teil + [0]
        bloecke.append(teil + rest)
    folge = []
    for i in range(len(bloecke[0])):
        for j, block in enumerate(bloecke):
            if i != kurz_laenge - ecc or j >= kurze:
                folge.append(block[i])

    sym = _Symbol(version)
    sym.muster()
    sym.codewoerter(folge)
    beste, beste_strafe = 0, None
    for maske in range(8):
        sym.maskieren(maske)
        sym.format(maske)
        s = sym.strafe()
        if beste_strafe is None or s < beste_strafe:
            beste, beste_strafe = maske, s
        sym.maskieren(maske)
    sym.maskieren(beste)
    sym.format(beste)
    return sym.modul


def svg(text, rand=4):
    m = matrix(text)
    n = len(m) + 2 * rand
    pfad = "".join("M%d %dh1v1h-1z" % (x + rand, y + rand) for y, zeile in enumerate(m) for x, z in enumerate(zeile) if z)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" shape-rendering="crispEdges">'
            '<rect width="%d" height="%d" fill="#fff"/><path d="%s" fill="#000"/></svg>' % (n, n, n, n, pfad))
