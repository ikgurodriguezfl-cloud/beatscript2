import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from beatscript.lexer import tokenize

# =============================================================
# Utilidad de aserción
# =============================================================

PASS = 0
FAIL = 0


def assert_tokens(source: str, expected_types: list, label: str = ""):
    global PASS, FAIL
    tokens = tokenize(source)
    actual = [t.type for t in tokens]
    tag    = f" [{label}]" if label else ""
    if actual == expected_types:
        print(f"  [OK]  PASS{tag}: {source!r}")
        PASS += 1
    else:
        print(f"  [!!] FAIL{tag}: {source!r}")
        print(f"       Esperado : {expected_types}")
        print(f"       Obtenido : {actual}")
        FAIL += 1


def assert_values(source: str, expected_values: list, label: str = ""):
    global PASS, FAIL
    tokens = tokenize(source)
    actual = [t.value for t in tokens]
    tag    = f" [{label}]" if label else ""
    if actual == expected_values:
        print(f"  [OK]  PASS{tag}: valores de {source!r}")
        PASS += 1
    else:
        print(f"  [!!] FAIL{tag}: valores de {source!r}")
        print(f"       Esperado : {expected_values}")
        print(f"       Obtenido : {actual}")
        FAIL += 1


def section(title: str):
    print(f"\n{'-'*55}")
    print(f"  TEST: {title}")
    print(f"{'-'*55}")


# =============================================================
# SUITE DE PRUEBAS
# =============================================================

def test_keywords():
    section("Palabras reservadas (keywords)")
    assert_tokens("tempo",      ["TEMPO_KW"])
    assert_tokens("instrument", ["INSTRUMENT_KW"])
    assert_tokens("track",      ["TRACK_KW"])
    assert_tokens("repeat",     ["REPEAT_KW"])
    assert_tokens("chord",      ["CHORD_KW"])
    assert_tokens("rest",       ["REST"])


def test_tempo_declaration():
    section("Declaración de tempo")
    assert_tokens("tempo 120",  ["TEMPO_KW", "NUMBER"])
    assert_tokens("tempo 60",   ["TEMPO_KW", "NUMBER"])
    assert_tokens("tempo 200",  ["TEMPO_KW", "NUMBER"])
    # El valor numérico debe ser int
    assert_values("tempo 120",  ["tempo", 120])


def test_instrument_declaration():
    section("Selección de instrumento")
    assert_tokens("instrument piano",      ["INSTRUMENT_KW", "INSTR_NAME"])
    assert_tokens("instrument guitar",     ["INSTRUMENT_KW", "INSTR_NAME"])
    assert_tokens("instrument violin",     ["INSTRUMENT_KW", "INSTR_NAME"])
    assert_tokens("instrument drums",      ["INSTRUMENT_KW", "INSTR_NAME"])
    assert_tokens("instrument saxophone",  ["INSTRUMENT_KW", "INSTR_NAME"])
    assert_tokens("instrument cello",      ["INSTRUMENT_KW", "INSTR_NAME"])


def test_notes_natural():
    section("Notas naturales (sin alteración)")
    for note in ["C4", "D4", "E4", "F4", "G4", "A4", "B4"]:
        assert_tokens(note, ["NOTE"], label=note)
    # Octavas extremas
    assert_tokens("C0", ["NOTE"])
    assert_tokens("B8", ["NOTE"])


def test_notes_sharp():
    section("Notas con sostenido (#)")
    assert_tokens("C#4", ["NOTE"])
    assert_tokens("D#3", ["NOTE"])
    assert_tokens("F#5", ["NOTE"])
    assert_tokens("G#2", ["NOTE"])
    assert_tokens("A#4", ["NOTE"])


def test_notes_flat():
    section("Notas con bemol (b)")
    assert_tokens("Eb5",  ["NOTE"])
    assert_tokens("Bb4",  ["NOTE"])
    assert_tokens("Ab3",  ["NOTE"])
    assert_tokens("Db4",  ["NOTE"])
    assert_tokens("Gb2",  ["NOTE"])


def test_notes_normalized():
    section("Normalización de notas (minúsculas → mayúsculas)")
    tokens = tokenize("c4 d#3 eb5")
    values = [t.value for t in tokens]
    assert values == ["C4", "D#3", "EB5"], f"Esperado ['C4','D#3','EB5'], obtenido {values}"
    print(f"  [OK]  PASS: c4 d#3 eb5 -> {values}")
    global PASS; PASS += 1


def test_notes_no_octave():
    section("Sin octava → NO debe ser NOTE (cae a IDENTIFIER)")
    assert_tokens("C",  ["IDENTIFIER"], label="C sin octava")
    assert_tokens("D#", ["IDENTIFIER"], label="D# sin octava — D matchea NOTE? no, falta dígito")


def test_durations():
    section("Duraciones musicales")
    durations = [
        "redonda", "blanca", "negra",
        "corchea", "semicorchea", "fusa", "semifusa"
    ]
    for d in durations:
        assert_tokens(d, ["DURATION"], label=d)


def test_note_with_duration():
    section("Nota + duración")
    assert_tokens("C4 negra",    ["NOTE", "DURATION"])
    assert_tokens("D#4 blanca",  ["NOTE", "DURATION"])
    assert_tokens("Eb3 corchea", ["NOTE", "DURATION"])
    assert_tokens("G4 redonda",  ["NOTE", "DURATION"])


def test_rest_with_duration():
    section("Silencio (rest) + duración")
    assert_tokens("rest negra",       ["REST", "DURATION"])
    assert_tokens("rest semicorchea", ["REST", "DURATION"])


def test_numbers():
    section("Números enteros")
    assert_tokens("120", ["NUMBER"])
    assert_tokens("2",   ["NUMBER"])
    assert_tokens("0",   ["NUMBER"])
    # El valor debe ser int, no string
    toks = tokenize("120")
    assert toks[0].value == 120 and isinstance(toks[0].value, int)
    print("  [OK]  PASS: valor de '120' es int(120)")
    global PASS; PASS += 1


def test_identifiers():
    section("Identificadores (nombres de track, etc.)")
    assert_tokens("melody",   ["IDENTIFIER"])
    assert_tokens("coro",     ["IDENTIFIER"])
    assert_tokens("my_track", ["IDENTIFIER"])
    assert_tokens("Track1",   ["IDENTIFIER"])
    # 'bass' es INSTR_NAME, no IDENTIFIER
    assert_tokens("bass",     ["INSTR_NAME"])


def test_braces():
    section("Delimitadores { }")
    assert_tokens("{", ["LBRACE"])
    assert_tokens("}", ["RBRACE"])
    assert_tokens("{}", ["LBRACE", "RBRACE"])


def test_track_block():
    section("Bloque track completo")
    source = "track melody {"
    assert_tokens(source, ["TRACK_KW", "IDENTIFIER", "LBRACE"])


def test_repeat_block():
    section("Bloque repeat")
    assert_tokens("repeat 2 {", ["REPEAT_KW", "NUMBER", "LBRACE"])
    assert_tokens("repeat 4 {", ["REPEAT_KW", "NUMBER", "LBRACE"])


def test_chord_block():
    section("Bloque chord")
    assert_tokens("chord {",        ["CHORD_KW", "LBRACE"])
    # Acorde con múltiples notas
    assert_tokens("C4 E4 G4 blanca", ["NOTE", "NOTE", "NOTE", "DURATION"])


def test_comments_ignored():
    section("Comentarios (deben ignorarse)")
    assert_tokens("# esto es un comentario", [])
    assert_tokens("# comentario\ntempo 120", ["TEMPO_KW", "NUMBER"])
    assert_tokens("tempo 120 # inline",      ["TEMPO_KW", "NUMBER"])


def test_multiline_program():
    section("Programa multi-línea completo")
    source = """\
tempo 120
instrument piano
track melody {
    C4 negra
    D4 negra
    E4 blanca
}
repeat 2 {
    G4 negra
}
"""
    expected = [
        "TEMPO_KW", "NUMBER",
        "INSTRUMENT_KW", "INSTR_NAME",
        "TRACK_KW", "IDENTIFIER", "LBRACE",
        "NOTE", "DURATION",
        "NOTE", "DURATION",
        "NOTE", "DURATION",
        "RBRACE",
        "REPEAT_KW", "NUMBER", "LBRACE",
        "NOTE", "DURATION",
        "RBRACE",
    ]
    assert_tokens(source, expected, label="programa completo")


def test_line_numbers():
    section("Tracking de números de línea")
    source = "tempo 120\ninstrument piano\ntrack melody {"
    tokens = tokenize(source)
    # tempo está en línea 1, instrument en 2, track en 3
    assert tokens[0].lineno == 1, f"tempo debería ser línea 1, es {tokens[0].lineno}"
    assert tokens[2].lineno == 2, f"instrument debería ser línea 2, es {tokens[2].lineno}"
    assert tokens[4].lineno == 3, f"track debería ser línea 3, es {tokens[4].lineno}"
    print("  [OK]  PASS: numeros de linea correctos")
    global PASS; PASS += 1


def test_debug_mode():
    section("Modo debug (tabla visual)")
    source = "tempo 120\nC4 negra"
    print("  → Ejecutando tokenize(..., debug=True):")
    tokenize(source, debug=True)
    print("  [OK]  PASS: tabla impresa sin errores")
    global PASS; PASS += 1


# =============================================================
# RUNNER
# =============================================================

if __name__ == "__main__":
    print("=" * 55)
    print("  PRUEBAS DEL ANALIZADOR LEXICO - BeatScript")
    print("=" * 55)

    test_keywords()
    test_tempo_declaration()
    test_instrument_declaration()
    test_notes_natural()
    test_notes_sharp()
    test_notes_flat()
    test_notes_normalized()
    test_notes_no_octave()
    test_durations()
    test_note_with_duration()
    test_rest_with_duration()
    test_numbers()
    test_identifiers()
    test_braces()
    test_track_block()
    test_repeat_block()
    test_chord_block()
    test_comments_ignored()
    test_multiline_program()
    test_line_numbers()
    test_debug_mode()

    print(f"\n{'=' * 55}")
    print(f"  RESULTADO FINAL")
    print(f"{'=' * 55}")
    total = PASS + FAIL
    print(f"  Pasaron : {PASS}/{total}")
    print(f"  Fallaron: {FAIL}/{total}")
    if FAIL == 0:
        print("  Estado  : TODOS LOS TESTS PASARON")
    else:
        print("  Estado  : HAY FALLOS — revisar lexer.py")
    print("=" * 55)
