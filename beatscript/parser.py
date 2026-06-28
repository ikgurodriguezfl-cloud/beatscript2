"""
BeatScript — Analizador Sintáctico (Etapa 2)
=============================================
Parser recursivo descendente → Árbol Sintáctico (AST)

Gramática (Notación EBNF):
  programa    ::= (sentencia)*
  sentencia   ::= tempo | volume | pan | instrument | track | repeat | chord | transpose
  tempo       ::= 'tempo' numero
  volume      ::= 'volume' numero
  pan         ::= 'pan' numero
  instrument  ::= 'instrument' instr_name
  track       ::= 'track' identificador '{' (evento)* '}'
  chord       ::= 'chord' '{' NOTE+ DURATION '}'
  transpose   ::= 'transpose' numero '{' (evento)* '}'
  evento      ::= nota duracion | rest duracion | chord | pan | repeat numero '{' (evento)* '}' | transpose
  nota        ::= NOTE
  rest        ::= 'rest'
  duracion    ::= DURATION
  instr_name  ::= INSTR_NAME
  identificador ::= IDENTIFIER
  numero      ::= NUMBER
"""

import os as _os
import difflib
from beatscript.lexer import RESERVED

# 0. UTILIDADES DE SUGERENCIAS

def _get_suggestions_for_word(word, keywords_dict=None, cutoff=0.6, max_suggestions=3):
    """
    Encuentra palabras reservadas similares al texto dado usando difflib.

    Args:
        word:            La palabra para la cual buscar sugerencias.
        keywords_dict:   Diccionario de palabras reservadas (default: RESERVED del lexer).
        cutoff:          Umbral de similitud (0.0–1.0, default: 0.6).
        max_suggestions: Número máximo de sugerencias a retornar.

    Returns:
        Lista de palabras sugeridas, ordenadas por similitud.
    """
    if keywords_dict is None:
        keywords_dict = RESERVED

    candidates = list(keywords_dict.keys())
    suggestions = difflib.get_close_matches(
        word.lower(),
        candidates,
        n=max_suggestions,
        cutoff=cutoff,
    )
    return suggestions


# 1. CLASES DE NODOS DEL AST

class ASTNode:
    """Clase base para todos los nodos del árbol sintáctico."""
    def __repr__(self):
        return f"<{self.__class__.__name__}>"


class Program(ASTNode):
    """Nodo raíz del programa."""
    def __init__(self):
        self.statements = []  # Lista de sentencias globales


class Tempo(ASTNode):
    """Sentencia: tempo <número>"""
    def __init__(self, bpm):
        self.bpm = bpm

    def __repr__(self):
        return f"Tempo({self.bpm})"


class Volume(ASTNode):
    """Sentencia: volume <número>"""
    def __init__(self, level):
        self.level = level

    def __repr__(self):
        return f"Volume({self.level})"


class Compas(ASTNode):
    """Sentencia: compas <numerador> <denominador>"""
    def __init__(self, numerator, denominator):
        self.numerator = numerator
        self.denominator = denominator

    def __repr__(self):
        return f"Compas({self.numerator}/{self.denominator})"


class Pan(ASTNode):
    """Sentencia/Evento: pan <numero>"""
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"Pan({self.value})"


class Instrument(ASTNode):
    """Sentencia: instrument <nombre>"""
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"Instrument({self.name})"


class Track(ASTNode):
    """Sentencia: track <nombre> { eventos }"""
    def __init__(self, name, events):
        self.name = name
        self.events = events  # Lista de Note, Rest, Chord, Repeat

    def __repr__(self):
        return f"Track({self.name})"


class Note(ASTNode):
    """Evento: <nota> <duración>"""
    def __init__(self, pitch, duration):
        self.pitch = pitch      # "C4", "D#3", "Eb5", etc.
        self.duration = duration  # "negra", "blanca", etc.

    def __repr__(self):
        return f"Note({self.pitch} {self.duration})"


class Rest(ASTNode):
    """Evento: rest <duración>"""
    def __init__(self, duration):
        self.duration = duration

    def __repr__(self):
        return f"Rest({self.duration})"


class Chord(ASTNode):
    """
    Sentencia/Evento: chord { NOTE+ DURATION }

    Representa un acorde: varias notas tocadas simultáneamente
    con una duración compartida al final del bloque.

    Ejemplo BeatScript:
        chord {
            C4 E4 G4 blanca
        }
    """
    def __init__(self, notes, duration):
        self.notes = notes        # Lista de strings de pitch ["C4", "E4", "G4"]
        self.duration = duration  # Duración compartida: "blanca", "negra", etc.

    def __repr__(self):
        return f"Chord({'+'.join(self.notes)} {self.duration})"


class Repeat(ASTNode):
    """Evento/Sentencia: repeat <número> { eventos }"""
    def __init__(self, count, events):
        self.count = count
        self.events = events  # Lista de eventos o sentencias a repetir

    def __repr__(self):
        return f"Repeat({self.count})"


class Transpose(ASTNode):
    """Evento/Sentencia: transpose <semitonos> { eventos }"""
    def __init__(self, semitones, events):
        self.semitones = semitones
        self.events = events

    def __repr__(self):
        return f"Transpose({self.semitones})"


class Accent(ASTNode):
    """Evento/Sentencia: acento [velocidad] { eventos }"""
    def __init__(self, velocity, events):
        self.velocity = velocity
        self.events = events

    def __repr__(self):
        return f"Accent({self.velocity if self.velocity is not None else 'auto'})"


# 2. PARSER RECURSIVO DESCENDENTE

class BeatScriptParser:
    """Parser que convierte tokens en un árbol sintáctico (AST)."""

    def __init__(self, tokens, source_code=""):
        """
        Inicializa el parser.

        Args:
            tokens:      Lista de objetos token (con atributos: type, value, lineno, lexpos).
            source_code: Código fuente original; se usa para calcular columnas en errores.
        """
        self.tokens = tokens
        self.source_code = source_code  # Necesario para calcular columnas
        self.pos = 0        # Posición actual en la lista de tokens
        self.errors = []    # Errores de sintaxis encontrados

    # CÁLCULO DE COLUMNA (igual al _find_column del lexer)

    def _get_column(self, token):
        """
        Calcula la columna (1-indexada) del token dentro de su línea.
        Retorna '?' si no hay código fuente disponible.
        """
        if not self.source_code or not hasattr(token, "lexpos"):
            return "?"
        line_start = self.source_code.rfind("\n", 0, token.lexpos) + 1
        return token.lexpos - line_start + 1

    # MÉTODOS DE NAVEGACIÓN

    def _current_token(self):
        """Retorna el token actual sin avanzar."""
        if self._is_at_end():
            return None
        return self.tokens[self.pos]

    def _peek_token(self, offset=1):
        """Retorna el token N posiciones adelante."""
        pos = self.pos + offset
        if pos >= len(self.tokens):
            return None
        return self.tokens[pos]

    def _advance(self):
        """Avanza al siguiente token."""
        if not self._is_at_end():
            self.pos += 1

    def _synchronize(self, sync_tokens):
        """
        Recuperación de errores en Modo Pánico (Panic Mode).

        Descarta tokens uno a uno hasta encontrar uno cuyo tipo esté dentro
        de sync_tokens (token de sincronización seguro) o hasta llegar al
        final del archivo. Al retornar, el parser reanuda el análisis desde
        un punto limpio evitando errores en cascada.

        Args:
            sync_tokens: Lista o set de tipos de token seguros para reanudar
                         el análisis (inicio de sentencia o cierre de bloque).
        """
        sync_set = set(sync_tokens)
        while not self._is_at_end():
            if self._current_token().type in sync_set:
                return
            self._advance()

    def _is_at_end(self):
        """Verifica si hemos llegado al final de los tokens."""
        return self.pos >= len(self.tokens)

    def _check(self, token_type):
        """Verifica si el token actual es del tipo especificado."""
        current = self._current_token()
        return current is not None and current.type == token_type

    def _consume(self, token_type, message=None):
        """Consume un token del tipo especificado o genera un error sintáctico."""
        if self._check(token_type):
            token = self._current_token()
            self._advance()
            return token

        current = self._current_token()
        error_msg = (
            message or
            f"Se esperaba '{token_type}', "
            f"se encontró '{current.type if current else 'EOF'}'"
        )
        if current:
            self._add_error_with_suggestions(current, error_msg)
        else:
            self._add_error(f"Fin de archivo inesperado — {error_msg}")

        return None

    # REGISTRO DE ERRORES

    def _add_error_with_suggestions(self, token, base_message):
        """
        Registra un error sintáctico con el formato estándar:
        [ERROR SINTÁCTICO] Línea X, Col Y: <mensaje>

        Si el token es un IDENTIFIER similar a una palabra reservada,
        agrega una sugerencia útil al mensaje.
        """
        col = self._get_column(token)
        error_line = f"[ERROR SINTÁCTICO] Línea {token.lineno}, Col {col}: {base_message}"

        # Buscar palabras reservadas parecidas si el token es un IDENTIFIER
        if token.type == "IDENTIFIER":
            suggestions = _get_suggestions_for_word(
                token.value, cutoff=0.6, max_suggestions=2
            )
            if suggestions:
                sugerencia = " | ".join(f"'{s}'" for s in suggestions)
                error_line += f"\n   💡 Sugerencia: ¿Quisiste decir {sugerencia}?"

        self.errors.append(error_line)

    def _add_error(self, message, token=None):
        """
        Registra un error sintáctico con el formato estándar:
        [ERROR SINTÁCTICO] Línea X, Col Y: <mensaje>

        Si se proporciona un token, extrae su línea y columna.
        Si no hay token (caso EOF u otro), omite la posición.
        """
        if token is not None:
            col = self._get_column(token)
            self.errors.append(
                f"[ERROR SINTÁCTICO] Línea {token.lineno}, Col {col}: {message}"
            )
        else:
            self.errors.append(f"[ERROR SINTÁCTICO] {message}")

    # PUNTO DE ENTRADA

    def parse(self):
        """
        Parsea el programa completo y retorna el AST.

        Returns:
            Program: Árbol sintáctico del programa.
        """
        program = Program()

        while not self._is_at_end():
            stmt = self._parse_statement()
            if stmt:
                program.statements.append(stmt)

        return program

    # SENTENCIAS (nivel superior)

    def _parse_statement(self):
        """Parsea una sentencia principal: tempo, volume, pan, instrument, track, chord, repeat, transpose."""
        current = self._current_token()

        if current is None:
            return None

        if self._check("TEMPO_KW"):
            return self._parse_tempo()
        elif self._check("VOLUME_KW"):
            return self._parse_volume()
        elif self._check("COMPAS_KW"):
            return self._parse_compas()
        elif self._check("PAN_KW"):
            return self._parse_pan()
        elif self._check("INSTRUMENT_KW"):
            return self._parse_instrument()
        elif self._check("TRACK_KW"):
            return self._parse_track()
        elif self._check("CHORD_KW"):
            return self._parse_chord()
        elif self._check("REPEAT_KW"):
            return self._parse_repeat_statement()
        elif self._check("TRANSPOSE_KW"):
            return self._parse_transpose_statement()
        elif self._check("ACCENT_KW"):
            return self._parse_accent_statement()
        else:
            # Token inesperado: reportar error con columna y sugerencias
            if current.type == "IDENTIFIER":
                suggestions = _get_suggestions_for_word(current.value, cutoff=0.5)
                if suggestions:
                    sugerencia = " | ".join(f"'{s}'" for s in suggestions)
                    self._add_error(
                        f"'{current.value}' no es una palabra reservada válida.\n"
                        f"   💡 Sugerencia: ¿Quisiste decir {sugerencia}?",
                        token=current,
                    )
                else:
                    self._add_error(
                        f"'{current.value}' no es una palabra reservada válida.",
                        token=current,
                    )
            else:
                self._add_error(
                    f"Token inesperado: '{current.type}' con valor '{current.value}'",
                    token=current,
                )
            self._synchronize({
                "TEMPO_KW", "VOLUME_KW", "INSTRUMENT_KW",
                "TRACK_KW", "REPEAT_KW", "PAN_KW", "TRANSPOSE_KW", "COMPAS_KW", "ACCENT_KW",
            })
            return None

    def _parse_tempo(self):
        """Parsea: tempo <número>"""
        self._consume("TEMPO_KW")
        num_token = self._consume("NUMBER", "Se esperaba un número después de 'tempo'")

        if num_token:
            return Tempo(num_token.value)
        return None

    def _parse_volume(self):
        """Parsea: volume <número>"""
        self._consume("VOLUME_KW")
        num_token = self._consume("NUMBER", "Se esperaba un número después de 'volume'")

        if num_token:
            return Volume(num_token.value)
        return None

    def _parse_compas(self):
        """Parsea: compas <numerador> <denominador>"""
        self._consume("COMPAS_KW")
        numerator = self._consume("NUMBER", "Se esperaba el numerador despues de 'compas'")
        denominator = self._consume("NUMBER", "Se esperaba el denominador despues del numerador")

        if numerator and denominator:
            return Compas(numerator.value, denominator.value)
        return None

    def _parse_pan(self):
        """Parsea: pan <numero>"""
        self._consume("PAN_KW")
        num_token = self._consume("NUMBER", "Se esperaba un numero despues de 'pan'")

        if num_token:
            return Pan(num_token.value)
        return None

    def _parse_instrument(self):
        """Parsea: instrument <nombre_instrumento>"""
        self._consume("INSTRUMENT_KW")
        instr_token = self._consume("INSTR_NAME", "Se esperaba un nombre de instrumento")

        if instr_token:
            return Instrument(instr_token.value)
        return None

    def _parse_track(self):
        """Parsea: track <identificador> { <eventos> }"""
        self._consume("TRACK_KW")
        name_token = self._consume("IDENTIFIER", "Se esperaba un nombre de track")
        self._consume("LBRACE", "Se esperaba '{'")

        events = []
        while not self._check("RBRACE") and not self._is_at_end():
            event = self._parse_event()
            if event:
                events.append(event)

        self._consume("RBRACE", "Se esperaba '}'")

        if name_token:
            return Track(name_token.value, events)
        return None

    def _parse_chord(self):
        """
        Parsea: chord { NOTE+ DURATION }

        Un acorde es un bloque que contiene una o más notas seguidas
        de una única duración compartida por todas ellas.

        Ejemplo:
            chord { C4 E4 G4 blanca }
        """
        kw_token = self._current_token()  # Guardar token 'chord' para errores
        self._consume("CHORD_KW")
        self._consume("LBRACE", "Se esperaba '{' después de 'chord'")

        # Leer todas las notas hasta encontrar una duración o '}'
        notas = []
        while self._check("NOTE") and not self._is_at_end():
            note_token = self._consume("NOTE")
            if note_token:
                notas.append(note_token.value)

        # La duración va al final, compartida por todas las notas
        duration_token = self._consume(
            "DURATION", "Se esperaba una duración al final del acorde"
        )
        self._consume("RBRACE", "Se esperaba '}'")

        if not notas and kw_token:
            self._add_error(
                "El acorde debe contener al menos una nota antes de la duración.",
                token=kw_token,
            )
            return None

        if duration_token:
            return Chord(notas, duration_token.value)
        return None

    def _parse_repeat_statement(self):
        """Parsea repeat a nivel de sentencia: repeat <número> { <sentencias> }"""
        self._consume("REPEAT_KW")
        count_token = self._consume("NUMBER", "Se esperaba un número después de 'repeat'")
        self._consume("LBRACE", "Se esperaba '{'")

        statements = []
        while not self._check("RBRACE") and not self._is_at_end():
            stmt = self._parse_statement()
            if stmt:
                statements.append(stmt)

        self._consume("RBRACE", "Se esperaba '}'")

        if count_token:
            return Repeat(count_token.value, statements)
        return None

    def _parse_transpose_statement(self):
        """Parsea transpose a nivel de sentencia: transpose <numero> { <sentencias> }"""
        self._consume("TRANSPOSE_KW")
        semitones_token = self._consume("NUMBER", "Se esperaba un numero despues de 'transpose'")
        self._consume("LBRACE", "Se esperaba '{'")

        statements = []
        while not self._check("RBRACE") and not self._is_at_end():
            stmt = self._parse_statement()
            if stmt:
                statements.append(stmt)

        self._consume("RBRACE", "Se esperaba '}'")

        if semitones_token:
            return Transpose(semitones_token.value, statements)
        return None

    def _parse_accent_statement(self):
        """Parsea acento a nivel de sentencia: acento [numero] { <sentencias> }"""
        self._consume("ACCENT_KW")
        velocity_token = None
        if self._check("NUMBER"):
            velocity_token = self._consume("NUMBER")
        self._consume("LBRACE", "Se esperaba '{' despues de 'acento'")

        statements = []
        while not self._check("RBRACE") and not self._is_at_end():
            stmt = self._parse_statement()
            if stmt:
                statements.append(stmt)

        self._consume("RBRACE", "Se esperaba '}'")
        return Accent(velocity_token.value if velocity_token else None, statements)

    # EVENTOS (dentro de tracks)

    def _parse_event(self):
        """Parsea un evento dentro de un track: nota, rest, chord, pan, repeat o transpose."""
        current = self._current_token()

        if current is None:
            return None

        if self._check("NOTE"):
            return self._parse_note()
        elif self._check("REST"):
            return self._parse_rest()
        elif self._check("CHORD_KW"):
            return self._parse_chord()
        elif self._check("PAN_KW"):
            return self._parse_pan()
        elif self._check("REPEAT_KW"):
            return self._parse_repeat_event()
        elif self._check("TRANSPOSE_KW"):
            return self._parse_transpose_event()
        elif self._check("ACCENT_KW"):
            return self._parse_accent_event()
        else:
            # Token inesperado: reportar error con columna y sugerencias
            if current.type == "IDENTIFIER":
                suggestions = _get_suggestions_for_word(current.value, cutoff=0.5)
                if suggestions:
                    sugerencia = " | ".join(f"'{s}'" for s in suggestions)
                    self._add_error(
                        f"'{current.value}' no es válido en este contexto.\n"
                        f"   💡 Sugerencia: ¿Quisiste decir {sugerencia}?",
                        token=current,
                    )
                else:
                    self._add_error(
                        f"'{current.value}' no es válido en este contexto.\n"
                    f"   (Esperado: nota musical, 'rest', 'chord', 'pan', 'repeat', 'transpose' o 'acento')",
                        token=current,
                    )
            else:
                self._add_error(
                    f"Evento inesperado: '{current.type}' con valor '{current.value}'",
                    token=current,
                )
            self._synchronize({
                "NOTE", "REST", "REPEAT_KW", "TRANSPOSE_KW", "ACCENT_KW", "PAN_KW", "RBRACE",
            })
            return None

    def _parse_note(self):
        """Parsea: <nota> <duración>"""
        note_token = self._consume("NOTE")
        duration_token = self._consume(
            "DURATION", "Se esperaba una duración después de la nota"
        )

        if note_token and duration_token:
            return Note(note_token.value, duration_token.value)
        return None

    def _parse_rest(self):
        """Parsea: rest <duración>"""
        self._consume("REST")
        duration_token = self._consume(
            "DURATION", "Se esperaba una duración después de 'rest'"
        )

        if duration_token:
            return Rest(duration_token.value)
        return None

    def _parse_repeat_event(self):
        """Parsea repeat a nivel de evento: repeat <número> { <eventos> }"""
        self._consume("REPEAT_KW")
        count_token = self._consume("NUMBER", "Se esperaba un número después de 'repeat'")
        self._consume("LBRACE", "Se esperaba '{'")

        events = []
        while not self._check("RBRACE") and not self._is_at_end():
            event = self._parse_event()
            if event:
                events.append(event)

        self._consume("RBRACE", "Se esperaba '}'")

        if count_token:
            return Repeat(count_token.value, events)
        return None

    def _parse_transpose_event(self):
        """Parsea transpose a nivel de evento: transpose <numero> { <eventos> }"""
        self._consume("TRANSPOSE_KW")
        semitones_token = self._consume("NUMBER", "Se esperaba un numero despues de 'transpose'")
        self._consume("LBRACE", "Se esperaba '{'")

        events = []
        while not self._check("RBRACE") and not self._is_at_end():
            event = self._parse_event()
            if event:
                events.append(event)

        self._consume("RBRACE", "Se esperaba '}'")

        if semitones_token:
            return Transpose(semitones_token.value, events)
        return None

    def _parse_accent_event(self):
        """Parsea acento a nivel de evento: acento [numero] { <eventos> }"""
        self._consume("ACCENT_KW")
        velocity_token = None
        if self._check("NUMBER"):
            velocity_token = self._consume("NUMBER")
        self._consume("LBRACE", "Se esperaba '{' despues de 'acento'")

        events = []
        while not self._check("RBRACE") and not self._is_at_end():
            event = self._parse_event()
            if event:
                events.append(event)

        self._consume("RBRACE", "Se esperaba '}'")
        return Accent(velocity_token.value if velocity_token else None, events)


# 3. FUNCIÓN DE UTILIDAD PARA CONVERTIR AST A REPRESENTACIÓN DE TABLA

def ast_to_table_rows(node, parent_id=""):
    """
    Convierte un nodo AST a una lista de tuplas para insertar en un Treeview.

    Args:
        node:      Nodo AST a convertir.
        parent_id: ID del nodo padre en el Treeview.

    Returns:
        Lista de tuplas (parent_id, node_id, valores, tag).
        tag: "expandable" si tiene hijos, "leaf" si es hoja.
    """
    rows = []

    if isinstance(node, Program):
        for stmt in node.statements:
            rows.extend(ast_to_table_rows(stmt, parent_id))

    elif isinstance(node, Tempo):
        rows.append((parent_id, f"Tempo {node.bpm}", ("Tempo", "Comando", f"{node.bpm} BPM"), "leaf"))

    elif isinstance(node, Volume):
        rows.append((parent_id, f"Volume {node.level}", ("Volume", "Comando", f"{node.level}"), "leaf"))

    elif isinstance(node, Compas):
        rows.append((parent_id, f"Compas {node.numerator}/{node.denominator}", ("Compas", "Comando", f"{node.numerator}/{node.denominator}"), "leaf"))

    elif isinstance(node, Pan):
        rows.append((parent_id, f"Pan {node.value}", ("Pan", "Comando", f"{node.value}"), "leaf"))

    elif isinstance(node, Instrument):
        rows.append((parent_id, f"Instrument {node.name}", ("Instrument", "Declaración", node.name), "leaf"))

    elif isinstance(node, Track):
        track_id = f"Track {node.name}"
        rows.append((parent_id, track_id, ("Track", "Declaración", node.name), "expandable"))
        for event in node.events:
            rows.extend(ast_to_table_rows(event, track_id))

    elif isinstance(node, Note):
        rows.append((parent_id, f"Note {node.pitch}", ("Nota", "Evento", f"{node.pitch} ({node.duration})"), "leaf"))

    elif isinstance(node, Rest):
        rows.append((parent_id, f"Rest {node.duration}", ("Silencio", "Evento", node.duration), "leaf"))

    elif isinstance(node, Chord):
        notas_str = " + ".join(node.notes)
        chord_id = f"Chord {notas_str}"
        rows.append((parent_id, chord_id, ("Chord", "Evento", f"{notas_str} ({node.duration})"), "leaf"))

    elif isinstance(node, Repeat):
        repeat_id = f"Repeat {node.count}"
        rows.append((parent_id, repeat_id, ("Repeat", "Control", f"{node.count}x"), "expandable"))
        for event in node.events:
            rows.extend(ast_to_table_rows(event, repeat_id))

    elif isinstance(node, Transpose):
        transpose_id = f"Transpose {node.semitones}"
        rows.append((parent_id, transpose_id, ("Transpose", "Control", f"+{node.semitones} semitonos"), "expandable"))
        for event in node.events:
            rows.extend(ast_to_table_rows(event, transpose_id))

    elif isinstance(node, Accent):
        accent_id = f"Accent {node.velocity if node.velocity is not None else 'auto'}"
        value = f"{node.velocity}" if node.velocity is not None else "+20"
        rows.append((parent_id, accent_id, ("Acento", "Control", value), "expandable"))
        for event in node.events:
            rows.extend(ast_to_table_rows(event, accent_id))

    return rows


# 4. FUNCIÓN DE UTILIDAD PARA VISUALIZACIÓN TIPO ÁRBOL

def ast_to_tree_string(node, indent="", is_last=True):
    """
    Convierte un nodo AST a una representación visual estilo árbol de directorios.

    Usa caracteres Unicode:
        ├── rama intermedia
        └── última rama
        │   línea vertical de continuación

    Args:
        node:    Nodo AST a convertir.
        indent:  Espaciado acumulado (para recursión).
        is_last: Si es el último elemento en su nivel.

    Returns:
        String con la representación visual del árbol.
    """
    lines = []

    if isinstance(node, Program):
        lines.append("Program")
        statements = node.statements
        for i, stmt in enumerate(statements):
            is_last_stmt = (i == len(statements) - 1)
            extension = "    " if is_last_stmt else "│   "
            connector = "└── " if is_last_stmt else "├── "
            tree_str = ast_to_tree_string(stmt, indent + extension, is_last_stmt)
            lines.append(indent + connector + tree_str)

    elif isinstance(node, Tempo):
        return f"Tempo: {node.bpm} BPM"

    elif isinstance(node, Volume):
        return f"Volume: {node.level}"

    elif isinstance(node, Compas):
        return f"Compas: {node.numerator}/{node.denominator}"

    elif isinstance(node, Pan):
        return f"Pan: {node.value}"

    elif isinstance(node, Instrument):
        return f"Instrument: {node.name}"

    elif isinstance(node, Track):
        lines.append(f"Track '{node.name}'")
        events = node.events
        for i, event in enumerate(events):
            is_last_event = (i == len(events) - 1)
            extension = "    " if is_last_event else "│   "
            connector = "└── " if is_last_event else "├── "
            tree_str = ast_to_tree_string(event, indent + extension, is_last_event)
            lines.append(indent + connector + tree_str)

    elif isinstance(node, Note):
        return f"Nota: {node.pitch} ({node.duration})"

    elif isinstance(node, Rest):
        return f"Silencio ({node.duration})"

    elif isinstance(node, Chord):
        lines.append(f"Chord ({node.duration})")
        for i, pitch in enumerate(node.notes):
            is_last_note = (i == len(node.notes) - 1)
            connector = "└── " if is_last_note else "├── "
            lines.append(indent + connector + pitch)

    elif isinstance(node, Repeat):
        lines.append(f"Repeat x{node.count}")
        events = node.events
        for i, event in enumerate(events):
            is_last_event = (i == len(events) - 1)
            extension = "    " if is_last_event else "│   "
            connector = "└── " if is_last_event else "├── "
            tree_str = ast_to_tree_string(event, indent + extension, is_last_event)
            lines.append(indent + connector + tree_str)

    elif isinstance(node, Transpose):
        lines.append(f"Transpose +{node.semitones}")
        events = node.events
        for i, event in enumerate(events):
            is_last_event = (i == len(events) - 1)
            extension = "    " if is_last_event else "â”‚   "
            connector = "└── " if is_last_event else "├── "
            tree_str = ast_to_tree_string(event, indent + extension, is_last_event)
            lines.append(indent + connector + tree_str)

    elif isinstance(node, Accent):
        label = node.velocity if node.velocity is not None else "+20"
        lines.append(f"Acento {label}")
        events = node.events
        for i, event in enumerate(events):
            is_last_event = (i == len(events) - 1)
            extension = "    " if is_last_event else "│   "
            connector = "└── " if is_last_event else "├── "
            tree_str = ast_to_tree_string(event, indent + extension, is_last_event)
            lines.append(indent + connector + tree_str)

    return "\n".join(lines) if lines else str(node)


# 5. ÁRBOL DE DERIVACIÓN VISUAL CON GRAPHVIZ

def generate_visual_tree(ast_root, output_filename="parse_tree"):
    """
    Genera un Árbol de Derivación visual usando Graphviz y lo guarda como PNG.

    El árbol muestra explícitamente:
      - Nodos internos (rectángulos): reglas gramaticales aplicadas.
      - Nodos hoja (elipses): tokens terminales con su tipo y valor.

    Esto lo convierte en un árbol de derivación real, más informativo que
    un AST puro, ideal para presentaciones académicas.

    Args:
        ast_root:        Nodo raíz del AST (objeto Program).
        output_filename: Nombre base del archivo de salida (sin extensión).

    Returns:
        Ruta absoluta del archivo PNG generado.

    Raises:
        ImportError: Si el paquete Python 'graphviz' no está instalado.
        graphviz.backend.ExecutableNotFound: Si el binario 'dot' de Graphviz
            no está en el PATH del sistema.
    """
    import graphviz  # pip install graphviz  (requiere también el binario de Graphviz)

    # En Windows, Python no siempre hereda el PATH actualizado del sistema.
    # Inyectamos las rutas de instalación más comunes de Graphviz directamente.
    if _os.name == "nt":
        for _candidato in [
            r"C:\Program Files\Graphviz\bin",
            r"C:\Program Files (x86)\Graphviz\bin",
        ]:
            if _os.path.isfile(_os.path.join(_candidato, "dot.exe")):
                _os.environ["PATH"] = _candidato + _os.pathsep + _os.environ.get("PATH", "")
                break

    #  Configuración del grafo 
    dot = graphviz.Digraph(
        name="BeatScript_ParseTree",
        comment="BeatScript — Árbol de Derivación",
        graph_attr={
            "rankdir": "TB",           # De arriba hacia abajo
            "bgcolor": "#1e1e2e",      # Fondo oscuro (acorde con el IDE)
            "fontname": "Helvetica",
            "nodesep": "0.45",         # Separación horizontal entre nodos hermanos
            "ranksep": "0.65",         # Separación vertical entre niveles
            "splines": "ortho",        # Aristas en ángulo recto (más limpio)
            "label": "BeatScript — Árbol de Derivación",
            "labelloc": "t",           # Título arriba del grafo
            "fontcolor": "#90caf9",
            "fontsize": "14",
        },
        node_attr={
            "fontname": "Helvetica",
            "fontsize": "10",
            "style": "filled,rounded",
            "penwidth": "0",           # Sin borde visible (el color lo delimita)
        },
        edge_attr={
            "color": "#546e7a",
            "arrowsize": "0.65",
            "penwidth": "1.3",
        },
    )

    # Contador global para IDs únicos de nodos
    _uid = [0]

    def uid():
        _uid[0] += 1
        return f"n{_uid[0]}"

    #  Helpers: tipos de nodos 

    def nodo_regla(etiqueta, color="#283593"):
        """Nodo interno — representa una regla gramatical (rectángulo)."""
        nid = uid()
        dot.node(nid, label=etiqueta, shape="box",
                 fillcolor=color, fontcolor="white")
        return nid

    def nodo_terminal(tipo_token, valor_token, color="#37474f"):
        """Nodo hoja — representa un token terminal (elipse)."""
        nid = uid()
        dot.node(nid,
                 label=f"{tipo_token}\n'{valor_token}'",
                 shape="ellipse",
                 fillcolor=color,
                 fontcolor="#cfd8dc")
        return nid

    def nodo_lista(etiqueta):
        """Nodo contenedor de listas (eventos, sentencias) — rombo."""
        nid = uid()
        dot.node(nid, label=etiqueta, shape="diamond",
                 fillcolor="#004d40", fontcolor="white")
        return nid

    def arco(padre, hijo):
        dot.edge(padre, hijo)

    # Visitores recursivos 

    def visitar(node):
        """Despacha al visitante correcto según el tipo de nodo."""
        if isinstance(node, Program):    return _v_programa(node)
        if isinstance(node, Tempo):      return _v_tempo(node)
        if isinstance(node, Volume):     return _v_volume(node)
        if isinstance(node, Compas):     return _v_compas(node)
        if isinstance(node, Pan):        return _v_pan(node)
        if isinstance(node, Instrument): return _v_instrument(node)
        if isinstance(node, Track):      return _v_track(node)
        if isinstance(node, Note):       return _v_note(node)
        if isinstance(node, Rest):       return _v_rest(node)
        if isinstance(node, Chord):      return _v_chord(node)
        if isinstance(node, Repeat):     return _v_repeat(node)
        if isinstance(node, Transpose):  return _v_transpose(node)
        if isinstance(node, Accent):     return _v_accent(node)
        return None

    def _v_programa(node):
        # Nodo raíz con forma especial (doble octágono)
        nid = uid()
        dot.node(nid, label="programa",
                 shape="doubleoctagon",
                 fillcolor="#0d47a1",
                 fontcolor="white",
                 fontsize="12",
                 style="filled")
        for stmt in node.statements:
            hijo = visitar(stmt)
            if hijo:
                arco(nid, hijo)
        return nid

    def _v_tempo(node):
        # sentencia → TEMPO_KW  NUMBER
        nid = nodo_regla("sentencia\ntempo", "#4527a0")
        arco(nid, nodo_terminal("TEMPO_KW",  "tempo",      "#6a1b9a"))
        arco(nid, nodo_terminal("NUMBER",    str(node.bpm), "#37474f"))
        return nid

    def _v_volume(node):
        # sentencia → VOLUME_KW  NUMBER
        nid = nodo_regla("sentencia\nvolume", "#4527a0")
        arco(nid, nodo_terminal("VOLUME_KW", "volume",       "#6a1b9a"))
        arco(nid, nodo_terminal("NUMBER",    str(node.level), "#37474f"))
        return nid

    def _v_compas(node):
        nid = nodo_regla("sentencia\ncompas", "#4527a0")
        arco(nid, nodo_terminal("COMPAS_KW", "compas", "#6a1b9a"))
        arco(nid, nodo_terminal("NUMBER", str(node.numerator), "#37474f"))
        arco(nid, nodo_terminal("NUMBER", str(node.denominator), "#37474f"))
        return nid

    def _v_pan(node):
        # sentencia/evento â†’ PAN_KW NUMBER
        nid = nodo_regla("sentencia\npan", "#4527a0")
        arco(nid, nodo_terminal("PAN_KW", "pan", "#6a1b9a"))
        arco(nid, nodo_terminal("NUMBER", str(node.value), "#37474f"))
        return nid

    def _v_instrument(node):
        # sentencia → INSTRUMENT_KW  INSTR_NAME
        nid = nodo_regla("sentencia\ninstrument", "#4527a0")
        arco(nid, nodo_terminal("INSTRUMENT_KW", "instrument", "#6a1b9a"))
        arco(nid, nodo_terminal("INSTR_NAME",    node.name,    "#1565c0"))
        return nid

    def _v_track(node):
        # sentencia → TRACK_KW  IDENTIFIER  LBRACE  eventos  RBRACE
        nid = nodo_regla(f"sentencia\ntrack", "#1a237e")
        arco(nid, nodo_terminal("TRACK_KW",   "track",    "#283593"))
        arco(nid, nodo_terminal("IDENTIFIER", node.name,  "#1565c0"))
        arco(nid, nodo_terminal("LBRACE",     "{",        "#455a64"))

        # Nodo contenedor de eventos
        ev_nid = nodo_lista(f"eventos\n({len(node.events)})")
        arco(nid, ev_nid)
        for event in node.events:
            hijo = visitar(event)
            if hijo:
                arco(ev_nid, hijo)

        arco(nid, nodo_terminal("RBRACE", "}", "#455a64"))
        return nid

    def _v_note(node):
        # evento → NOTE  DURATION
        nid = nodo_regla("evento\nnota", "#1b5e20")
        arco(nid, nodo_terminal("NOTE",     node.pitch,    "#2e7d32"))
        arco(nid, nodo_terminal("DURATION", node.duration, "#388e3c"))
        return nid

    def _v_rest(node):
        # evento → REST  DURATION
        nid = nodo_regla("evento\nrest", "#33691e")
        arco(nid, nodo_terminal("REST",     "rest",        "#558b2f"))
        arco(nid, nodo_terminal("DURATION", node.duration, "#388e3c"))
        return nid

    def _v_chord(node):
        # evento → CHORD_KW  LBRACE  NOTE+  DURATION  RBRACE
        nid = nodo_regla("evento\nchord", "#004d40")
        arco(nid, nodo_terminal("CHORD_KW", "chord", "#00695c"))
        arco(nid, nodo_terminal("LBRACE",   "{",     "#455a64"))
        for pitch in node.notes:
            arco(nid, nodo_terminal("NOTE", pitch, "#2e7d32"))
        arco(nid, nodo_terminal("DURATION", node.duration, "#388e3c"))
        arco(nid, nodo_terminal("RBRACE",   "}",           "#455a64"))
        return nid

    def _v_repeat(node):
        # sentencia/evento → REPEAT_KW  NUMBER  LBRACE  cuerpo  RBRACE
        nid = nodo_regla("repeat", "#bf360c")
        arco(nid, nodo_terminal("REPEAT_KW", "repeat",        "#d84315"))
        arco(nid, nodo_terminal("NUMBER",    str(node.count), "#37474f"))
        arco(nid, nodo_terminal("LBRACE",    "{",             "#455a64"))

        # Nodo contenedor del cuerpo del repeat
        body_nid = nodo_lista(f"cuerpo\n({len(node.events)})")
        arco(nid, body_nid)
        for event in node.events:
            hijo = visitar(event)
            if hijo:
                arco(body_nid, hijo)

        arco(nid, nodo_terminal("RBRACE", "}", "#455a64"))
        return nid

    def _v_transpose(node):
        # sentencia/evento â†’ TRANSPOSE_KW NUMBER LBRACE cuerpo RBRACE
        nid = nodo_regla("transpose", "#4e342e")
        arco(nid, nodo_terminal("TRANSPOSE_KW", "transpose", "#6d4c41"))
        arco(nid, nodo_terminal("NUMBER", str(node.semitones), "#37474f"))
        arco(nid, nodo_terminal("LBRACE", "{", "#455a64"))

        body_nid = nodo_lista(f"cuerpo\n({len(node.events)})")
        arco(nid, body_nid)
        for event in node.events:
            hijo = visitar(event)
            if hijo:
                arco(body_nid, hijo)

        arco(nid, nodo_terminal("RBRACE", "}", "#455a64"))
        return nid

    def _v_accent(node):
        nid = nodo_regla("acento", "#880e4f")
        arco(nid, nodo_terminal("ACCENT_KW", "acento", "#ad1457"))
        if node.velocity is not None:
            arco(nid, nodo_terminal("NUMBER", str(node.velocity), "#37474f"))
        arco(nid, nodo_terminal("LBRACE", "{", "#455a64"))

        body_nid = nodo_lista(f"cuerpo\n({len(node.events)})")
        arco(nid, body_nid)
        for event in node.events:
            hijo = visitar(event)
            if hijo:
                arco(body_nid, hijo)

        arco(nid, nodo_terminal("RBRACE", "}", "#455a64"))
        return nid

    #  Construir el grafo completo 
    visitar(ast_root)

    # Guardar PNG en la raíz del proyecto (carpeta que contiene al paquete beatscript)
    proyecto_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    ruta_base = _os.path.join(proyecto_dir, output_filename)

    # dot.render() crea "<ruta_base>.png" y elimina el .gv intermedio (cleanup=True)
    ruta_png = dot.render(filename=ruta_base, format="png", cleanup=True)
    return _os.path.abspath(ruta_png)
