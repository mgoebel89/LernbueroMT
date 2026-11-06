"""Syntax der Skripte in web/ pruefen (ohne Node.js). Braucht das Python-Paket esprima, sonst wird uebersprungen:
    python -m pip install esprima
"""
import pathlib
import unittest

try:
    import esprima
except ImportError:
    esprima = None

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"


@unittest.skipIf(esprima is None, "esprima fehlt (python -m pip install esprima)")
class WebSyntax(unittest.TestCase):
    def test_skripte(self):
        for datei in sorted(WEB.glob("*.js")):
            with self.subTest(datei=datei.name):
                esprima.parseScript(datei.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
