"""
test_ast_visual.py — Pruebas de la representación visual del AST
=================================================================
Verifica que ast_to_tree_string produzca una cadena de texto bien
formada y con el contenido esperado para un programa válido.

Criterio rúbrica: 2.4 — Generación del árbol de sintaxis (AST)

Ejecutar:
    python -m unittest beatscript.tests.test_ast_visual -v
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from beatscript.lexer import tokenize
from beatscript.parser import BeatScriptParser, ast_to_tree_string


class TestASTVisual(unittest.TestCase):
    """Representación textual del AST con ast_to_tree_string."""

    def _build_ast(self, source: str):
        tokens, _ = tokenize(source, collect_errors=True)
        parser = BeatScriptParser(tokens, source_code=source)
        ast = parser.parse()
        self.assertEqual(parser.errors, [],
            msg="Código de prueba no debería generar errores:\n" + "\n".join(parser.errors))
        return ast

    def test_ast_to_string_no_vacio(self):
        """ast_to_tree_string retorna un string no vacío para un programa válido."""
        source = "tempo 120\ntrack t { C4 negra }\n"
        ast = self._build_ast(source)
        result = ast_to_tree_string(ast)

        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0,
            msg="ast_to_tree_string no debería retornar cadena vacía.")

    def test_ast_contiene_program(self):
        """La cadena del AST menciona 'Program' como nodo raíz."""
        source = "tempo 120\n"
        ast = self._build_ast(source)
        result = ast_to_tree_string(ast)
        self.assertIn("Program", result)

    def test_ast_contiene_tempo(self):
        """El AST textual menciona el BPM correcto."""
        source = "tempo 90\n"
        ast = self._build_ast(source)
        result = ast_to_tree_string(ast)
        self.assertIn("90", result)

    def test_ast_contiene_track_y_notas(self):
        """El AST textual incluye nombre del track y notas."""
        source = "track coro { C4 negra D4 blanca }\n"
        ast = self._build_ast(source)
        result = ast_to_tree_string(ast)

        self.assertIn("coro", result)
        self.assertIn("C4", result)
        self.assertIn("negra", result)
        self.assertIn("D4", result)
        self.assertIn("blanca", result)

    def test_ast_programa_complejo(self):
        """Programa con repeat y chord produce AST textual sin errores."""
        source = (
            "tempo 120\n"
            "instrument violin\n"
            "track melodia {\n"
            "    C4 negra\n"
            "    chord { C4 E4 G4 blanca }\n"
            "    repeat 2 { F4 corchea G4 corchea }\n"
            "}\n"
        )
        ast = self._build_ast(source)
        result = ast_to_tree_string(ast)

        self.assertIn("melodia", result)
        self.assertIn("C4", result)
        self.assertIn("blanca", result)
        self.assertGreater(result.count("\n"), 5,
            msg="El árbol de un programa complejo debe tener múltiples líneas.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
