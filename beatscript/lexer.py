"""
BeatScript — Analizador Léxico (Etapa 1)
========================================
Compilador de lenguaje de composición musical → MIDI

Responsabilidad:
    Convierte el código fuente BeatScript (texto plano) en una secuencia
    de tokens que el parser consumirá en la Etapa 2. Detecta y acumula
    errores léxicos sin detener el escaneo, permitiendo reportar todos
    los errores de una sola pasada.

Tokens reconocidos (13 tipos):
    TEMPO_KW       Keyword 'tempo'          → define BPM
    VOLUME_KW      Keyword 'volume'         → define volumen MIDI (0-127)
    INSTRUMENT_KW  Keyword 'instrument'     → selecciona instrumento
    TRACK_KW       Keyword 'track'          → inicia una pista musical
    REPEAT_KW      Keyword 'repeat'         → repite un bloque N veces
    CHORD_KW       Keyword 'chord'          → define un acorde
    REST           Keyword 'rest'           → silencio musical
    NOTE           Nota musical             → [A-G][#b]?[0-9], ej: C4, D#3, Eb5
    DURATION       Duración de nota         → negra|blanca|corchea|...
    INSTR_NAME     Nombre de instrumento    → piano|guitar|violin|...
    NUMBER         Entero positivo          → [0-9]+
    IDENTIFIER     Nombre libre de track    → [a-zA-Z_][a-zA-Z0-9_]*
    LBRACE         Llave de apertura        → {
    RBRACE         Llave de cierre          → }

Flujo interno:
    tokenize(source) → build_lexer() → PLY construye AFD → escaneo lineal O(n)
    → por cada lexema: intentar reglas en orden de prioridad → emitir token
    → si carácter inválido: t_error() → acumular en error_list → skip(1) → continuar
"""

import ply.lex as lex

# ---------------------------------------------------------------------------
# 1. PALABRAS RESERVADAS
#    Diccionario que mapea el literal del lexema al tipo de token que representa.
#    t_IDENTIFIER consulta este diccionario después de capturar cualquier
#    identificador: si el valor está aquí, el tipo cambia de IDENTIFIER al
#    tipo correspondiente. Esto permite tratar keywords e instrumentos con
#    la misma regex que los nombres de usuario.
# ---------------------------------------------------------------------------

RESERVED: dict[str, str] = {
    # Comandos
    "tempo"       : "TEMPO_KW",
    "instrument"  : "INSTRUMENT_KW",
    "track"       : "TRACK_KW",
    "repeat"      : "REPEAT_KW",
    "chord"       : "CHORD_KW",
    "rest"        : "REST",
    "volume"      : "VOLUME_KW",
    "pan"         : "PAN_KW",
    "transpose"   : "TRANSPOSE_KW",
    "compas"      : "COMPAS_KW",
    "acento"      : "ACCENT_KW",

# Duraciones musicales (¡AQUÍ AGREGAMOS LAS NUEVAS!)
    "redonda"           : "DURATION",
    "redonda_punto"     : "DURATION",
    "blanca"            : "DURATION",
    "blanca_punto"      : "DURATION",
    "negra"             : "DURATION",
    "negra_punto"       : "DURATION",
    "corchea"           : "DURATION",
    "corchea_punto"     : "DURATION",
    "semicorchea"       : "DURATION",
    "semicorchea_punto" : "DURATION",
    "fusa"              : "DURATION",
    "semifusa"          : "DURATION",

    # Instrumentos MIDI — cuerdas
    "piano"       : "INSTR_NAME",
    "violin"      : "INSTR_NAME",
    "viola"       : "INSTR_NAME",
    "cello"       : "INSTR_NAME",
    "contrabass"  : "INSTR_NAME",
    "harp"        : "INSTR_NAME",

    # Instrumentos MIDI — vientos madera
    "flute"       : "INSTR_NAME",
    "piccolo"     : "INSTR_NAME",
    "recorder"    : "INSTR_NAME",
    "oboe"        : "INSTR_NAME",
    "clarinet"    : "INSTR_NAME",
    "bassoon"     : "INSTR_NAME",
    "saxophone"   : "INSTR_NAME",

    # Instrumentos MIDI — vientos metal
    "trumpet"     : "INSTR_NAME",
    "trombone"    : "INSTR_NAME",
    "frenchhorn"  : "INSTR_NAME",
    "tuba"        : "INSTR_NAME",

    # Instrumentos MIDI — percusión melódica
    "marimba"     : "INSTR_NAME",
    "vibraphone"  : "INSTR_NAME",
    "xylophone"   : "INSTR_NAME",
    "celesta"     : "INSTR_NAME",
    "drums"       : "INSTR_NAME",

    # Instrumentos MIDI — cuerdas pulsadas / folk
    "guitar"      : "INSTR_NAME",
    "bass"        : "INSTR_NAME",
    "banjo"       : "INSTR_NAME",
    "sitar"       : "INSTR_NAME",
    "harpsichord" : "INSTR_NAME",

    # Instrumentos MIDI — teclados y otros
    "organ"       : "INSTR_NAME",
    "accordion"   : "INSTR_NAME",
    "harmonica"   : "INSTR_NAME",
}

# ---------------------------------------------------------------------------
# 2. LISTA DE TIPOS DE TOKENS
#    PLY exige que exista una tupla llamada exactamente 'tokens' que liste
#    todos los tipos de token que el lexer puede producir. Si un tipo no
#    aparece aquí, PLY lanza error al construir el lexer.
# ---------------------------------------------------------------------------

tokens = (
    "TEMPO_KW",
    "INSTRUMENT_KW",
    "TRACK_KW",
    "REPEAT_KW",
    "CHORD_KW",
    "REST",
    "VOLUME_KW",
    "PAN_KW",
    "TRANSPOSE_KW",
    "COMPAS_KW",
    "ACCENT_KW",
    "NOTE",
    "DURATION",
    "INSTR_NAME",
    "NUMBER",
    "IDENTIFIER",
    "LBRACE",
    "RBRACE",
)

# ---------------------------------------------------------------------------
# 3. REGLAS LÉXICAS
#
#    PLY aplica las reglas en este orden de prioridad:
#      1. Funciones (def t_NOMBRE): ordenadas por posición en el archivo.
#         La primera definida tiene mayor prioridad.
#      2. Strings (t_NOMBRE = r"..."): ordenadas por longitud de la regex.
#         La regex más larga tiene mayor prioridad.
#
#    CRÍTICO: t_NOTE DEBE definirse ANTES que t_IDENTIFIER en el archivo.
#    Motivo: la regex de IDENTIFIER ([a-zA-Z_][a-zA-Z0-9_]*) también casa
#    con "C4" (C es letra, 4 es dígito válido tras el primer carácter).
#    Si IDENTIFIER tuviera mayor prioridad, "C4" sería IDENTIFIER en vez
#    de NOTE, rompiendo el análisis léxico de notas musicales.
# ---------------------------------------------------------------------------

# --- Tokens de un solo carácter (string rules) ---------------
# Se definen como strings porque no requieren lógica adicional.
# El { se escapa con \ porque en regex { inicia un cuantificador.
t_LBRACE = r"\{"
t_RBRACE = r"\}"

# --- Nota musical (función = alta prioridad) -----------------
# Regex: [A-Ga-g][#b]?[0-9]
#
# Autómata:
#   q0 --[A-Ga-g]--> q1 --[#b]--> q2 --[0-9]--> q3 (ACCEPT)
#   q0                q1 --[0-9]-------------->  q3 (ACCEPT)
#
# Ejemplos válidos:  C4  D#3  Eb5  G0  Bb4  F#7
# Ejemplos inválidos: C  D#  bass  B (sin octava)
def t_NOTE(t):
    r"[A-Ga-g][#b]?[0-9]"
    # Normaliza a mayúsculas para que c4, C4 y C4 sean equivalentes
    # y el resto del pipeline trabaje con un formato uniforme.
    t.value = t.value.upper()   # c4 → C4, eb3 → EB3
    return t


# --- Número entero -------------------------------------------
# Regex: [0-9]+
#
# Autómata:
#   q0 --[0-9]--> q1* --[0-9]--> q1* (bucle, * = estado final)
def t_NUMBER(t):
    r"[0-9]+"
    # Convierte el string a entero para que el parser y el generador MIDI
    # operen directamente con el valor numérico sin conversiones adicionales.
    t.value = int(t.value)
    return t


# --- Identificador / Palabra reservada ----------------------
# Regex: [a-zA-Z_][a-zA-Z0-9_]*
#
# Autómata:
#   q0 --[a-zA-Z_]--> q1* --[a-zA-Z0-9_]--> q1* (bucle)
#
# Después de capturar el lexema se consulta la tabla RESERVED;
# si existe, se sustituye el tipo; si no, queda como IDENTIFIER.
def t_IDENTIFIER(t):
    r"[a-zA-Z_][a-zA-Z0-9_]*"
    # Consulta el diccionario RESERVED en minúsculas para ser case-insensitive:
    # "TEMPO", "Tempo" y "tempo" se tratan igual.
    # Si la palabra está en RESERVED → cambia el tipo al tipo correspondiente.
    # Si no está → queda como IDENTIFIER (nombre libre del usuario).
    # Las palabras reservadas se almacenan en minúsculas; los identificadores
    # conservan la capitalización original del usuario.
    token_type = RESERVED.get(t.value.lower(), "IDENTIFIER")
    t.type  = token_type
    t.value = t.value.lower() if token_type != "IDENTIFIER" else t.value
    return t


# --- Comentarios (ignorados, no generan token) ---------------
# Regex: #[^\n]*
def t_COMMENT(t):
    r"\#[^\n]*"
    # Los comentarios no generan token: la función no retorna nada,
    # por lo que PLY descarta el lexema silenciosamente.
    pass


# --- Saltos de línea (tracking de número de línea) -----------
def t_newline(t):
    r"\n+"
    # Incrementa el contador de líneas en tantas unidades como saltos haya.
    # No retorna token → el salto de línea se descarta pero lineno queda actualizado
    # para que los mensajes de error indiquen la línea correcta.
    t.lexer.lineno += len(t.value)


# --- Caracteres ignorados (espacios, tabs, retorno de carro) ----
# PLY omite estos caracteres sin generar token ni llamar a t_error.
t_ignore = " \t\r"


# --- Manejo de errores léxicos -------------------------------
def t_error(t):
    """
    Manejador de errores léxicos invocado automáticamente por PLY cuando
    ninguna regla casa con el carácter actual.

    Comportamiento:
        1. Calcula la columna exacta del carácter problemático.
        2. Construye un mensaje de error contextual usando _ERROR_HINTS.
        3. Si el lexer tiene 'error_list' (modo collect_errors=True), acumula
           el error en esa lista para reportarlo al final junto con los demás.
           Si no, lo imprime directamente (modo debug/standalone).
        4. Llama a skip(1) para avanzar un carácter y continuar el escaneo,
           evitando que un solo error detenga todo el análisis léxico.
    """
    col  = _find_column(t.lexer.lexdata, t)
    char = t.value[0]
    msg  = _build_error_msg(char, t.lineno, col)
    if hasattr(t.lexer, "error_list"):
        t.lexer.error_list.append({"line": t.lineno, "col": col, "char": char, "msg": msg})
    else:
        print(msg)
    t.lexer.skip(1)  # Salta el carácter inválido y continúa el escaneo


# ---------------------------------------------------------------------------
# 4. UTILIDADES
# ---------------------------------------------------------------------------

# Diccionario de mensajes de error contextuales por carácter.
# Cubre los símbolos que los usuarios de otros lenguajes suelen intentar usar
# en BeatScript (operadores, delimitadores, etc.) con sugerencias específicas.
# Si el carácter no está en este diccionario, se usa un mensaje genérico.
_ERROR_HINTS: dict[str, str] = {
    "@":  "El símbolo '@' no pertenece al alfabeto de BeatScript.",
    "!":  "El operador '!' no existe en BeatScript.",
    "$":  "El símbolo '$' no es válido.",
    "%":  "El símbolo '%' no es válido.",
    "^":  "El símbolo '^' no es válido.",
    "&":  "El símbolo '&' no es válido.",
    "*":  "Para repetir bloques usa: repeat N { ... }",
    "(":  "Paréntesis no válido — los bloques se delimitan con { }",
    ")":  "Paréntesis no válido — los bloques se delimitan con { }",
    "[":  "Corchete no válido — los bloques se delimitan con { }",
    "]":  "Corchete no válido — los bloques se delimitan con { }",
    ";":  "El ';' no es necesario — cada instrucción va en su propia línea.",
    ":":  "El ':' no es válido en BeatScript.",
    '"':  "Las cadenas de texto no son válidas en BeatScript.",
    "'":  "Las cadenas de texto no son válidas en BeatScript.",
    "+":  "El operador '+' no existe en BeatScript.",
    "-":  "El operador '-' no existe — los valores negativos no son válidos.",
    "=":  "El operador '=' no existe en BeatScript.",
    "<":  "El operador '<' no existe en BeatScript.",
    ">":  "El operador '>' no existe en BeatScript.",
    ",":  "Separa notas con espacios, no con comas: C4 E4 G4 blanca",
    ".":  "El '.' no es válido — BeatScript no usa decimales.",
    "/":  "Para comentarios usa '#', no '/' ni '//'.",
    "\\":  "El '\\' no es válido en BeatScript.",
    "|":  "El '|' no es válido en BeatScript.",
    "~":  "El '~' no es válido en BeatScript.",
    "?":  "El '?' no es válido en BeatScript.",
}


def _build_error_msg(char: str, line: int, col: int) -> str:
    """
    Construye el mensaje de error léxico con formato estándar.

    Busca en _ERROR_HINTS un mensaje específico para el carácter.
    Si no existe, usa un mensaje genérico de 'no pertenece al alfabeto'.

    Args:
        char: El carácter inválido encontrado por el lexer.
        line: Número de línea donde ocurrió el error (1-indexado).
        col:  Número de columna donde ocurrió el error (1-indexado).

    Returns:
        String con el mensaje de error formateado, listo para mostrar.
    """
    hint = _ERROR_HINTS.get(char, f"'{char}' no pertenece al alfabeto de BeatScript.")
    return f"[ERROR LÉXICO] Línea {line}, Col {col}: carácter '{char}' no reconocido — {hint}"


def _find_column(source: str, token) -> int:
    """
    Calcula la columna (1-indexada) de un token dentro de su línea.

    Usa token.lexpos (índice absoluto en el string fuente) y busca
    el último salto de línea antes de esa posición para obtener
    el inicio de la línea actual. La diferencia da la columna relativa.

    Args:
        source: Código fuente completo como string.
        token:  Objeto LexToken con atributo lexpos.

    Returns:
        Número de columna (entero, base 1).
    """
    line_start = source.rfind("\n", 0, token.lexpos) + 1
    return token.lexpos - line_start + 1


def build_lexer() -> lex.Lexer:
    """
    Construye y retorna el objeto lexer de PLY.

    PLY realiza introspección del módulo actual buscando todas las
    variables y funciones con el patrón t_NOMBRE, compila las reglas
    en expresiones regulares y construye un único AFD combinado.

    Returns:
        Objeto lex.Lexer listo para recibir input.
    """
    return lex.lex()


def tokenize(source_code: str, *, debug: bool = False, collect_errors: bool = False):
    """
    Punto de entrada público del analizador léxico.

    Construye el lexer, escanea el código fuente completo y retorna
    los tokens producidos. Los errores léxicos se acumulan en una lista
    interna del lexer (error_list) en vez de lanzar excepciones, lo que
    permite continuar el escaneo después de cada carácter inválido y
    reportar todos los errores de una sola pasada.

    Args:
        source_code:    Texto del programa BeatScript a tokenizar.
        debug:          Si True, imprime la tabla de tokens en consola
                        con formato visual (útil para depuración).
        collect_errors: Si True, retorna una tupla (tokens, errores).
                        Si False (default), retorna solo la lista de tokens.

    Returns:
        Lista de LexToken si collect_errors=False.
        Tupla (list[LexToken], list[dict]) si collect_errors=True,
        donde cada dict tiene: {'line', 'col', 'char', 'msg'}.
    """
    errors = []
    lx = build_lexer()
    lx.error_list = errors   # t_error acumula aquí en vez de imprimir
    lx.input(source_code)

    result = list(lx)        # Materializa el generador — escanea todo el código

    if debug:
        _print_token_table(result, source_code)

    if collect_errors:
        return result, errors
    return result


def _print_token_table(token_list: list, source: str = "") -> None:
    """
    Imprime la tabla de tokens en consola con formato visual alineado.
    Solo se llama cuando tokenize() recibe debug=True.
    Muestra: número, tipo, valor, línea y columna de cada token.
    """
    W = 68
    print("\n" + "=" * W)
    print(f"{'TABLA DE TOKENS — BeatScript Lexer':^{W}}")
    print("=" * W)
    print(f"{'#':<5} {'TIPO':<18} {'VALOR':<20} {'LÍNEA':<7} {'COL'}")
    print("-" * W)
    for i, tok in enumerate(token_list, 1):
        col = _find_column(source, tok) if source else "-"
        print(f"{i:<5} {tok.type:<18} {str(tok.value):<20} {tok.lineno:<7} {col}")
    print("=" * W)
    print(f"  Total: {len(token_list)} tokens")
    print("=" * W + "\n")


# 5. DEMO — ejecución directa

if __name__ == "__main__":
    SAMPLE = """\
# ---- Ejemplo completo BeatScript ----
tempo 120

instrument piano

track melody {
    C4 negra
    D4 negra
    E4 blanca
    F4 corchea
    rest corchea
}

repeat 2 {
    G4 negra
    A4 corchea
    Bb4 semicorchea
}

chord {
    C4 E4 G4 blanca
}
"""
    print("Código fuente:")
    print("-" * 50)
    print(SAMPLE)

    tokenize(SAMPLE, debug=True)
