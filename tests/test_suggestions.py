"""
test_suggestions.py — Pruebas del sistema de sugerencias difflib
================================================================
Verifica que cuando el usuario escribe una palabra reservada con typo,
el parser genere sugerencias útiles mediante difflib.get_close_matches.

Criterio rúbrica: 2.3 — Manejo de errores sintácticos con mensajes útiles

Ejecutar:
    python -m unittest beatscript.tests.test_suggestions -v
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from beatscript.lexer import tokenize
from beatscript.parser import BeatScriptParser


def _parse(source: str):
    tokens, _ = tokenize(source, collect_errors=True)
    parser = BeatScriptParser(tokens, source_code=source)
    ast = parser.parse()
    return ast, parser.errors


class TestSugerenciasDifflib(unittest.TestCase):
    """Sistema de sugerencias: typos en palabras reservadas → difflib."""

    def test_typo_tempo(self):
        """'tempp' → sugerencia 'tempo'."""
        _, errors = _parse("tempp 120\n")
        self.assertGreater(len(errors), 0)
        self.assertIn("tempo", " ".join(errors).lower())

    def test_typo_instrument(self):
        """'instrumento' → sugerencia 'instrument'."""
        _, errors = _parse("instrumento piano\n")
        self.assertGreater(len(errors), 0)
        self.assertIn("instrument", " ".join(errors).lower())

    def test_typo_track(self):
        """'traack' → sugerencia 'track'."""
        _, errors = _parse("traack melodia { C4 negra }\n")
        self.assertGreater(len(errors), 0)
        self.assertIn("track", " ".join(errors).lower())

    def test_typo_repeat_dentro_de_track(self):
        """'repet' dentro de un track → sugerencia 'repeat'."""
        source = "track t { repet 2 { C4 negra } }\n"
        _, errors = _parse(source)
        self.assertGreater(len(errors), 0)
        # 'repet' es suficientemente parecido a 'repeat' (cutoff 0.6)
        combined = " ".join(errors).lower()
        self.assertIn("repeat", combined)

    def test_typo_volume(self):
        """'volumen' → sugerencia 'volume'."""
        _, errors = _parse("volumen 100\n")
        self.assertGreater(len(errors), 0)
        self.assertIn("volume", " ".join(errors).lower())

    def test_codigo_correcto_sin_sugerencias(self):
        """Código completamente válido no genera ninguna sugerencia."""
        source = "tempo 120\nvolume 80\ninstrument piano\n"
        _, errors = _parse(source)
        self.assertEqual(len(errors), 0,
            msg="Código válido no debería producir errores ni sugerencias.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
