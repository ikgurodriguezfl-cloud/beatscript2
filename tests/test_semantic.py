import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from beatscript.lexer import tokenize
from beatscript.parser import BeatScriptParser
from beatscript.semantic import SemanticAnalyzer


def _analyze(source: str):
    tokens, _ = tokenize(source, collect_errors=True)
    parser = BeatScriptParser(tokens, source_code=source)
    ast = parser.parse()
    analyzer = SemanticAnalyzer(ast)
    errors, warnings = analyzer.analyze()
    return ast, errors, warnings


class TestErroresSemanticos(unittest.TestCase):
    def test_acorde_vacio(self):
        _, errors, _ = _analyze("chord { negra }\n")
        combined = " ".join(errors).lower()
        self.assertIn("14", combined)

    def test_track_vacio(self):
        _, errors, warnings = _analyze("track intro { }\n")
        combined = " ".join(errors + warnings).lower()
        self.assertIn("15", combined)

    def test_track_duplicado(self):
        source = (
            "track intro { C4 negra }\n"
            "track intro { E4 negra }\n"
        )
        _, errors, _ = _analyze(source)
        combined = " ".join(errors).lower()
        self.assertIn("16", combined)

    def test_programa_sin_salida_audible(self):
        _, errors, _ = _analyze("tempo 120\ninstrument piano\npan 64\n")
        combined = " ".join(errors).lower()
        self.assertIn("17", combined)

    def test_redefinicion_tempo_sin_efecto(self):
        _, _, warnings = _analyze("tempo 120\ntempo 80\ntempo 200\ntrack t { C4 negra }\n")
        combined = " ".join(warnings).lower()
        self.assertIn("18", combined)

    def test_repeat_con_un_solo_repeticion(self):
        _, _, warnings = _analyze("repeat 1 { C4 negra }\n")
        combined = " ".join(warnings).lower()
        self.assertIn("27", combined)

    def test_instrumento_sin_track_posterior(self):
        _, _, warnings = _analyze("instrument violin\ninstrument piano\ninstrument trumpet\ntrack t { C4 negra }\n")
        combined = " ".join(warnings).lower()
        self.assertIn("19", combined)

    def test_acorde_con_punto_sin_compas(self):
        _, _, warnings = _analyze("chord { C4 E4 G4 negra_punto }\n")
        combined = " ".join(warnings).lower()
        self.assertIn("20", combined)

    def test_track_referenciado_inexistente_en_secuencia(self):
        _, errors, _ = _analyze(
            "track melodia { C4 negra }\n"
            "secuencia { (melodia, bajo), melodia }\n"
        )
        combined = " ".join(errors).lower()
        self.assertIn("21", combined)

    def test_track_no_referenciado_en_secuencia(self):
        _, _, warnings = _analyze(
            "track melodia { C4 negra }\n"
            "track bajo { C3 negra }\n"
            "track puente { F4 negra }\n"
            "secuencia { melodia, bajo }\n"
        )
        combined = " ".join(warnings).lower()
        self.assertIn("22", combined)

    def test_secuencia_vacia(self):
        _, _, warnings = _analyze("track melodia { C4 negra }\nsecuencia { }\n")
        combined = " ".join(warnings).lower()
        self.assertIn("23", combined)

    def test_track_repetido_en_grupo_paralelo(self):
        _, _, warnings = _analyze(
            "track melodia { C4 negra }\n"
            "secuencia { (melodia, melodia, melodia) }\n"
        )
        combined = " ".join(warnings).lower()
        self.assertIn("24", combined)

    def test_track_fuera_de_secuencia_desproporcionado(self):
        _, _, warnings = _analyze(
            "track fondo { repeat 100 { C2 redonda } }\n"
            "track melodia { C4 negra }\n"
            "secuencia { melodia }\n"
        )
        combined = " ".join(warnings).lower()
        self.assertIn("25", combined)

    def test_grupo_paralelo_con_un_solo_track(self):
        _, _, warnings = _analyze(
            "track melodia { C4 negra }\n"
            "track bajo { C3 negra }\n"
            "secuencia { (melodia), bajo }\n"
        )
        combined = " ".join(warnings).lower()
        self.assertIn("26", combined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
