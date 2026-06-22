import unittest
import sys
import os

# Asegurar que la raíz del proyecto esté en el path (por si se ejecuta directo)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from beatscript.lexer import tokenize
from beatscript.parser import (
    BeatScriptParser,
    Program,
    Track,
    Note,
    Tempo,
)


# Clase base con helper para construir el pipeline Lexer → Parser

class BeatScriptParserTestCase(unittest.TestCase):
    """Clase base con utilidades comunes para todos los tests del parser."""

    def _parse(self, source: str):
        """
        Ejecuta el pipeline completo: tokenize → BeatScriptParser.parse().

        Retorna:
            (ast, errors, tokens)  — para que cada test pueda inspeccionar
                                     el resultado con granularidad.
        """
        tokens, lex_errors = tokenize(source, collect_errors=True)
        parser = BeatScriptParser(tokens, source_code=source)
        ast = parser.parse()
        return ast, parser.errors, tokens


# TEST 1 — Integración exitosa (Lexer → Parser)

class TestIntegracionExitosa(BeatScriptParserTestCase):
    """
    Prueba que el pipeline completo Lexer → Parser funcione de extremo a
    extremo con código fuente válido.

    Criterios de aceptación:
    - parser.errors debe estar vacío (sin errores sintácticos).
    - El resultado es una instancia de Program (nodo raíz del AST).
    - El AST contiene exactamente las sentencias que el código describe.
    """

    def test_pipeline_lexer_parser_sin_errores(self):
        """Código fuente válido produce un AST correcto y sin errores."""
        source = (
            "tempo 120\n"
            "track melodia {\n"
            "    C4 negra\n"
            "    D4 blanca\n"
            "}\n"
        )

        ast, errors, _ = self._parse(source)

        # ── Sin errores sintácticos ──────────────────────────────────────
        self.assertEqual(
            len(errors), 0,
            msg=f"Se esperaban 0 errores pero se encontraron {len(errors)}:\n"
                + "\n".join(errors),
        )

        # ── El resultado es un AST (Program) válido ──────────────────────
        self.assertIsInstance(
            ast, Program,
            msg="Se esperaba que parse() retornara un objeto Program.",
        )

        # ── El programa contiene 2 sentencias: Tempo y Track ─────────────
        self.assertEqual(
            len(ast.statements), 2,
            msg=f"Se esperaban 2 sentencias (Tempo + Track), "
                f"se encontraron {len(ast.statements)}.",
        )

        # ── Primera sentencia: Tempo con bpm=120 ─────────────────────────
        tempo_node = ast.statements[0]
        self.assertIsInstance(tempo_node, Tempo)
        self.assertEqual(tempo_node.bpm, 120)

        # ── Segunda sentencia: Track 'melodia' con 2 notas ───────────────
        track_node = ast.statements[1]
        self.assertIsInstance(track_node, Track)
        self.assertEqual(track_node.name, "melodia")
        self.assertEqual(len(track_node.events), 2)

        # ── Notas dentro del track ────────────────────────────────────────
        nota_c4 = track_node.events[0]
        self.assertIsInstance(nota_c4, Note)
        self.assertEqual(nota_c4.pitch, "C4")
        self.assertEqual(nota_c4.duration, "negra")

        nota_d4 = track_node.events[1]
        self.assertIsInstance(nota_d4, Note)
        self.assertEqual(nota_d4.pitch, "D4")
        self.assertEqual(nota_d4.duration, "blanca")


# TEST 2 — Modo Pánico (Recuperación de Errores)

class TestModoPanico(BeatScriptParserTestCase):
    """
    Prueba que el parser detecte un error sintáctico DENTRO de un track,
    active el Modo Pánico para descartar los tokens problemáticos, y luego
    retome el análisis correctamente procesando la siguiente nota válida.

    El error inyectado: una nota seguida de NUMBER (ej. C4 99) en vez de
    DURATION (ej. C4 negra).  El parser detectará 1 error y, tras sincronizar,
    procesará la nota siguiente (D4 corchea) sin problema.

    Criterios de aceptación:
    - parser.errors contiene EXACTAMENTE 1 error.
    - El track resultante tiene al menos 1 Note válida (D4) después del error.
    """

    def test_recuperacion_modo_panico_dentro_de_track(self):
        """Un error dentro de un track genera 1 error y el parser se recupera."""
        # C4 sin duración: el parser consume NOTE y luego busca DURATION,
        # pero encuentra D4 (tipo NOTE). Genera exactamente 1 error de "Se
        # esperaba DURATION", sincroniza en D4 (Modo Pánico) y la procesa.
        source = (
            "track test {\n"
            "    C4\n"          # ← error intencional: nota sin duración
            "    D4 corchea\n"  # ← debe procesarse correctamente tras la recuperación
            "}\n"
        )

        ast, errors, _ = self._parse(source)

        # ── Exactamente 1 error registrado ───────────────────────────────
        self.assertEqual(
            len(errors), 1,
            msg=f"Se esperaba exactamente 1 error (Modo Pánico), "
                f"pero se encontraron {len(errors)}:\n" + "\n".join(errors),
        )

        # ── El mensaje menciona el problema de duración ───────────────────
        combined_err = errors[0].lower()
        self.assertTrue(
            "duration" in combined_err or "duraci" in combined_err,
            msg=f"El error debería mencionar que se esperaba una duración.\n"
                f"Error registrado: {errors[0]}",
        )

        # ── El AST fue producido (no None) ────────────────────────────────
        self.assertIsInstance(ast, Program)

        # ── El track existe en el AST ─────────────────────────────────────
        self.assertEqual(len(ast.statements), 1)
        track_node = ast.statements[0]
        self.assertIsInstance(track_node, Track)
        self.assertEqual(track_node.name, "test")

        # ── La nota válida D4 fue procesada correctamente ─────────────────
        notas_validas = [
            e for e in track_node.events
            if isinstance(e, Note) and e.pitch == "D4"
        ]
        self.assertGreaterEqual(
            len(notas_validas), 1,
            msg="La nota D4 debería haberse recuperado tras el Modo Pánico, "
                "pero no aparece en el AST.",
        )
        self.assertEqual(notas_validas[0].duration, "corchea")


# TEST 3 — Error Estructural (EOF Inesperado / Llave sin cerrar)

class TestEOFInesperado(BeatScriptParserTestCase):
    """
    Prueba que el parser detecte y reporte el error cuando el archivo
    termina abruptamente sin cerrar la llave '}' de un track.

    Criterios de aceptación:
    - parser.errors NO está vacío (hay al menos 1 error).
    - El mensaje del error menciona: 'EOF', 'fin de archivo', '}',
      o 'RBRACE' (cualquier indicación de la llave faltante).
    - El parser NO lanza excepción (termina de forma controlada).
    """

    def test_error_eof_falta_llave_cierre(self):
        """El parser reporta error cuando falta el '}' de cierre de un track."""
        source = (
            "track incompleto {\n"
            "    E4 negra\n"
            # ← falta el '}' de cierre
        )

        # El parser no debe lanzar excepción — debe manejar el EOF internamente
        try:
            ast, errors, _ = self._parse(source)
        except Exception as exc:
            self.fail(
                f"El parser lanzó una excepción inesperada al encontrar EOF: {exc}"
            )

        # ── Debe haberse registrado al menos 1 error ──────────────────────
        self.assertGreater(
            len(errors), 0,
            msg="Se esperaba al menos 1 error por EOF/llave sin cerrar, "
                "pero el parser no reportó ninguno.",
        )

        # ── El mensaje del error debe indicar el problema estructural ─────
        # Acepta cualquier variante: '}', 'RBRACE', 'EOF', 'fin de archivo'
        combined = " ".join(errors).lower()
        indicadores = ["}", "rbrace", "eof", "fin de archivo", "inesperado"]
        encontrado = any(ind in combined for ind in indicadores)

        self.assertTrue(
            encontrado,
            msg=f"El mensaje de error debería mencionar '}}'  o EOF.\n"
                f"Errores registrados:\n" + "\n".join(errors),
        )

        # ── El AST sigue siendo un Program (parser no rompe el objeto) ────
        self.assertIsInstance(
            ast, Program,
            msg="Incluso con EOF, parse() debe retornar un objeto Program.",
        )


# TEST 4 — Programa complejo: repeat + chord + múltiples tracks  (3.3)

class TestCasosComplejos(BeatScriptParserTestCase):
    """
    Criterio 3.3 — Manejo de casos complejos y estructuras anidadas.

    Verifica que el pipeline Lexer → Parser maneje correctamente:
    - chord con múltiples notas dentro de un track
    - repeat anidado dentro de un track
    - múltiples tracks en el mismo programa
    - tempo + volume + instrument globales previos
    """

    def test_programa_completo_con_repeat_chord_multitracks(self):
        """Pipeline completo con chord, repeat y dos tracks — sin errores."""
        source = (
            "tempo 120\n"
            "volume 80\n"
            "instrument piano\n"
            "track melodia {\n"
            "    C4 negra\n"
            "    chord { C4 E4 G4 blanca }\n"
            "    repeat 2 {\n"
            "        D4 corchea\n"
            "        E4 corchea\n"
            "    }\n"
            "}\n"
            "track bajo {\n"
            "    C3 blanca\n"
            "    rest negra\n"
            "}\n"
        )

        ast, errors, _ = self._parse(source)

        # Sin errores en programa complejo
        self.assertEqual(
            len(errors), 0,
            msg="Programa complejo no debería generar errores:\n" + "\n".join(errors),
        )
        self.assertIsInstance(ast, Program)

        # 5 sentencias: Tempo, Volume, Instrument, Track('melodia'), Track('bajo')
        self.assertEqual(len(ast.statements), 5,
            msg=f"Se esperaban 5 sentencias, encontradas: {len(ast.statements)}")

        # Track 'melodia' tiene 3 eventos: Note, Chord, Repeat
        from beatscript.parser import Chord, Repeat, Rest
        melodia = ast.statements[3]
        self.assertIsInstance(melodia, Track)
        self.assertEqual(melodia.name, "melodia")
        self.assertEqual(len(melodia.events), 3)
        self.assertIsInstance(melodia.events[0], Note)
        self.assertIsInstance(melodia.events[1], Chord)
        self.assertIsInstance(melodia.events[2], Repeat)

        # Chord tiene 3 notas y duración 'blanca'
        chord_node = melodia.events[1]
        self.assertEqual(chord_node.notes, ["C4", "E4", "G4"])
        self.assertEqual(chord_node.duration, "blanca")

        # Repeat x2 tiene 2 eventos internos
        repeat_node = melodia.events[2]
        self.assertEqual(repeat_node.count, 2)
        self.assertEqual(len(repeat_node.events), 2)

        # Track 'bajo' tiene Note + Rest
        bajo = ast.statements[4]
        self.assertIsInstance(bajo, Track)
        self.assertEqual(bajo.name, "bajo")
        self.assertEqual(len(bajo.events), 2)
        self.assertIsInstance(bajo.events[1], Rest)

    def test_chord_con_notas_alteradas(self):
        """Chord con sostenidos y bemoles no genera errores."""
        source = "track t { chord { C#4 Eb4 G4 negra } }\n"
        ast, errors, _ = self._parse(source)

        self.assertEqual(len(errors), 0,
            msg="Chord con alteraciones no debería dar error:\n" + "\n".join(errors))

        from beatscript.parser import Chord
        track = ast.statements[0]
        chord_node = track.events[0]
        self.assertIsInstance(chord_node, Chord)
        self.assertIn("C#4", chord_node.notes)
        self.assertIn("EB4", chord_node.notes)   # normalizado a mayúsculas

    def test_repeat_global_top_level(self):
        """repeat a nivel global (fuera de track) es válido."""
        source = (
            "repeat 3 {\n"
            "    tempo 120\n"
            "}\n"
        )
        ast, errors, _ = self._parse(source)

        from beatscript.parser import Repeat
        self.assertEqual(len(errors), 0,
            msg="repeat global no debería dar error:\n" + "\n".join(errors))
        self.assertIsInstance(ast.statements[0], Repeat)
        self.assertEqual(ast.statements[0].count, 3)


# TEST 5 — Errores léxicos propagados al pipeline  (3.4)

class TestErroresLexicos(BeatScriptParserTestCase):
    """
    Criterio 3.4 — Pruebas de casos de error léxico y su propagación.

    Verifica que caracteres inválidos generen mensajes descriptivos
    y que el lexer los reporte con línea y columna correctas.
    """

    def test_caracter_invalido_arroba(self):
        """El símbolo '@' genera error léxico con mensaje descriptivo."""
        from beatscript.lexer import tokenize
        source = "tempo @120\n"
        tokens, errors = tokenize(source, collect_errors=True)

        self.assertGreater(len(errors), 0,
            msg="Se esperaba al menos 1 error léxico por el carácter '@'.")

        combined = " ".join(str(e) for e in errors).lower()
        # El mensaje debe mencionar el carácter o dar contexto
        self.assertTrue(
            "@" in combined or "caracter" in combined or "símbolo" in combined
            or "no reconocido" in combined or "no pertenece" in combined,
            msg=f"El error léxico debería mencionar '@'. Errores: {errors}",
        )

    def test_caracter_invalido_punto_y_coma(self):
        """El ';' genera error léxico con sugerencia de no usarlo."""
        from beatscript.lexer import tokenize
        source = "tempo 120;\n"
        tokens, errors = tokenize(source, collect_errors=True)

        self.assertGreater(len(errors), 0,
            msg="Se esperaba al menos 1 error léxico por el carácter ';'.")

    def test_error_lexico_incluye_linea(self):
        """El mensaje de error léxico incluye el número de línea."""
        from beatscript.lexer import tokenize
        source = "tempo 120\n@invalido\n"
        tokens, errors = tokenize(source, collect_errors=True)

        self.assertGreater(len(errors), 0)
        # El error está en la línea 2
        err = errors[0]
        linea_info = str(err.get("line", err)) if isinstance(err, dict) else str(err)
        self.assertIn("2", linea_info,
            msg=f"El error debería mencionar la línea 2. Error: {err}")

    def test_multiples_errores_lexicos_no_detiene_el_lexer(self):
        """El lexer continúa tras múltiples caracteres inválidos."""
        from beatscript.lexer import tokenize
        source = "@ $ % tempo 120\n"
        tokens, errors = tokenize(source, collect_errors=True)

        # 3 errores (uno por cada carácter inválido)
        self.assertGreaterEqual(len(errors), 3,
            msg="Se esperaban al menos 3 errores léxicos (uno por símbolo).")

        # El lexer igual reconoció 'tempo' y '120'
        tipos = [t.type for t in tokens]
        self.assertIn("TEMPO_KW", tipos,
            msg="El lexer debe seguir reconociendo tokens válidos tras los errores.")
        self.assertIn("NUMBER", tipos)


# TEST 6 — Errores en chord y repeat  (3.4 — casos de error estructurales)

class TestErroresEstructurales(BeatScriptParserTestCase):
    """
    Criterio 3.4 — Pruebas de errores en construcciones chord y repeat.
    Valida que el parser detecte y reporte errores específicos en cada
    construcción, con mensajes claros.
    """

    def test_chord_sin_llave_apertura(self):
        """chord sin '{' genera error sintáctico."""
        source = "chord C4 E4 G4 blanca\n"
        ast, errors, _ = self._parse(source)

        self.assertGreater(len(errors), 0,
            msg="chord sin '{' debería generar error sintáctico.")

    def test_chord_vacio_sin_notas(self):
        """chord con solo duración (sin notas) genera error."""
        source = "track t { chord { blanca } }\n"
        ast, errors, _ = self._parse(source)

        self.assertGreater(len(errors), 0,
            msg="chord sin notas debería generar al menos 1 error.")

    def test_repeat_sin_numero(self):
        """repeat sin número de repeticiones genera error sintáctico."""
        source = "repeat { C4 negra }\n"
        ast, errors, _ = self._parse(source)

        self.assertGreater(len(errors), 0,
            msg="repeat sin número debería generar error sintáctico.")

    def test_error_sintactico_incluye_linea_y_columna(self):
        """Los mensajes de error sintáctico contienen [Línea X, Col Y]."""
        source = (
            "tempo 120\n"
            "track test {\n"
            "    C4\n"          # error: nota sin duración — línea 3
            "}\n"
        )
        ast, errors, _ = self._parse(source)

        self.assertGreater(len(errors), 0)
        primer_error = errors[0]

        # El mensaje debe tener referencia a línea y columna
        tiene_linea = "línea" in primer_error.lower() or "linea" in primer_error.lower()
        tiene_col   = "col" in primer_error.lower()

        self.assertTrue(tiene_linea,
            msg=f"El error sintáctico debe mencionar la línea.\nError: {primer_error}")
        self.assertTrue(tiene_col,
            msg=f"El error sintáctico debe mencionar la columna.\nError: {primer_error}")

    def test_multiples_errores_con_recuperacion(self):
        """Múltiples errores en un programa no detienen el parser (Modo Pánico)."""
        source = (
            "track t1 {\n"
            "    C4\n"        # error 1: sin duración
            "    D4\n"        # error 2: sin duración
            "    E4 negra\n"  # válido — debe procesarse
            "}\n"
        )
        ast, errors, _ = self._parse(source)

        # El parser reportó errores pero NO lanzó excepción
        self.assertIsInstance(ast, Program)

        # Al menos 2 errores registrados
        self.assertGreaterEqual(len(errors), 2,
            msg=f"Se esperaban ≥2 errores, encontrados: {len(errors)}")

        # E4 negra debe estar en el AST (el Modo Pánico lo procesó)
        track = ast.statements[0]
        self.assertIsInstance(track, Track)
        notas_e4 = [e for e in track.events if isinstance(e, Note) and e.pitch == "E4"]
        self.assertGreaterEqual(len(notas_e4), 1,
            msg="E4 negra debería estar en el AST tras la recuperación de múltiples errores.")


# TEST 7 — Mensajes de error con sugerencias difflib  (2.3 + 3.4)

class TestSugerenciasParser(BeatScriptParserTestCase):
    """
    Valida que el parser genere sugerencias útiles cuando el usuario
    escribe una palabra reservada con typo (usa difflib internamente).
    """

    def test_sugerencia_para_tempo_mal_escrito(self):
        """'tempp' genera sugerencia '¿Quisiste decir tempo?'"""
        source = "tempp 120\n"
        ast, errors, _ = self._parse(source)

        self.assertGreater(len(errors), 0)
        combined = " ".join(errors).lower()
        self.assertIn("tempo", combined,
            msg=f"Debería sugerir 'tempo' para 'tempp'.\nErrores: {errors}")

    def test_sugerencia_para_track_mal_escrito(self):
        """'traack' genera sugerencia '¿Quisiste decir track?'"""
        source = "traack melodia { C4 negra }\n"
        ast, errors, _ = self._parse(source)

        self.assertGreater(len(errors), 0)
        combined = " ".join(errors).lower()
        self.assertIn("track", combined,
            msg=f"Debería sugerir 'track' para 'traack'.\nErrores: {errors}")

    def test_codigo_valido_sin_sugerencias(self):
        """Código correcto no genera ningún error ni sugerencia."""
        source = "tempo 90\nvolume 70\ninstrument violin\n"
        ast, errors, _ = self._parse(source)

        self.assertEqual(len(errors), 0,
            msg="Código válido no debería generar sugerencias/errores.")


# ===========================================================================
# Punto de entrada
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
