"""
BeatScript — Generador MIDI (Etapa 4)
======================================
Interpreta la lista de tokens producida por el lexer y genera un archivo
MIDI binario (.mid) reproducible con cualquier reproductor de audio.

Responsabilidad:
    Recibe directamente los tokens (no el AST) y los recorre con un índice
    secuencial, manteniendo un tiempo acumulado 't' en beats. Cada tipo de
    token produce una acción sobre el objeto MIDIFile:
        - TEMPO_KW    → actualiza el tempo (BPM)
        - VOLUME_KW   → actualiza la velocidad (velocity) de las notas
        - INSTRUMENT_KW → cambia el programa MIDI del canal
        - TRACK_KW    → extrae y procesa el bloque { } del track
        - REPEAT_KW   → extrae el bloque y lo procesa N veces seguidas
        - CHORD_KW    → agrega varias notas en el mismo instante 't'
        - NOTE        → agrega una nota y avanza 't' por su duración
        - REST        → avanza 't' sin agregar nota (silencio)

Tablas de conversión:
    NOTE_SEMITONES   → letra de nota → semitonos desde Do
    DURATION_BEATS   → nombre de duración → beats (negra = 1.0)
    INSTRUMENT_PROGRAM → nombre de instrumento → número de programa MIDI General
"""

from midiutil import MIDIFile

# Semitonos desde Do (C) para cada nota de la escala occidental.
# Usado por note_to_midi() para calcular el número MIDI de la nota.
NOTE_SEMITONES = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}

# Duración en beats de cada valor de duración musical de BeatScript.
# La negra (1.0) es la unidad base. Todos los demás son múltiplos o fracciones.
DURATION_BEATS = {
    'redonda':     4.0,
    'blanca':      2.0,
    'negra':       1.0,
    'corchea':     0.5,
    'semicorchea': 0.25,
    'fusa':        0.125,
    'semifusa':    0.0625,
}

# Mapeo de nombre de instrumento BeatScript → número de programa MIDI General (GM).
# El estándar MIDI General define 128 programas (0-127). Los números aquí
# corresponden a instrumentos GM ampliamente compatibles con reproductores MIDI.
INSTRUMENT_PROGRAM = {
    # Cuerdas
    'piano':       0,
    'violin':     40,
    'viola':      41,
    'cello':      42,
    'contrabass': 43,
    'harp':       46,
    # Vientos madera
    'flute':      73,
    'piccolo':    72,
    'recorder':   74,
    'oboe':       68,
    'clarinet':   71,
    'bassoon':    70,
    'saxophone':  65,
    # Vientos metal
    'trumpet':    56,
    'trombone':   57,
    'frenchhorn': 60,
    'tuba':       58,
    # Percusión melódica
    'marimba':    12,
    'vibraphone': 11,
    'xylophone':  13,
    'celesta':     8,
    'drums':       0,
    # Cuerdas pulsadas / folk
    'guitar':     25,
    'bass':       32,
    'banjo':     105,
    'sitar':     104,
    'harpsichord': 6,
    # Teclados y otros
    'organ':      19,
    'accordion':  21,
    'harmonica':  22,
}


def note_to_midi(note_str: str) -> int:
    """
    Convierte una nota en formato BeatScript a su número MIDI equivalente.

    Fórmula: pitch = semitonos_de_la_letra + (octava + 1) * 12 ± alteración
    El +1 en la octava ajusta al estándar MIDI donde C4 = 60 (Do central).

    Args:
        note_str: Nota en formato BeatScript, ej: 'C4', 'D#3', 'EB5'.
                  Siempre en mayúsculas (normalizado por t_NOTE en el lexer).

    Returns:
        Número MIDI entero (0-127). C4=60, A4=69, C5=72.

    Ejemplos:
        note_to_midi('C4') → 60
        note_to_midi('A4') → 69
        note_to_midi('D#3') → 51
    """
    s = note_str.upper()
    letter = s[0]
    rest   = s[1:]
    # Detecta si hay alteración: el segundo carácter es # o B con dígito después
    if rest and rest[0] in ('#', 'B') and len(rest) > 1:
        alt, octave = rest[0], int(rest[1])
    else:
        alt, octave = '', int(rest[0])
    pitch = NOTE_SEMITONES[letter] + (octave + 1) * 12
    if alt == '#': pitch += 1   # Sostenido: sube un semitono
    if alt == 'B': pitch -= 1   # Bemol: baja un semitono
    return pitch


def _collect_block(tokens: list, start: int):
    """
    Extrae los tokens contenidos dentro de un bloque { } de BeatScript.

    Soporta bloques anidados (ej: track con repeat dentro) mediante un
    contador de profundidad: depth sube con LBRACE y baja con RBRACE.
    El bloque termina cuando depth llega a 0.

    Args:
        tokens: Lista completa de tokens del programa.
        start:  Índice del primer token DENTRO del bloque (después del LBRACE).

    Returns:
        Tupla (block_tokens, next_index) donde:
            block_tokens → lista de tokens dentro del bloque (sin las llaves)
            next_index   → índice del primer token después del RBRACE de cierre
    """
    depth, end = 1, start
    while end < len(tokens) and depth > 0:
        if   tokens[end].type == 'LBRACE': depth += 1
        elif tokens[end].type == 'RBRACE': depth -= 1
        end += 1
    return tokens[start:end - 1], end


def tokens_to_midi(tokens: list, output_path: str = "output.mid") -> str:
    """
    Convierte la lista de tokens BeatScript en un archivo MIDI binario.

    Recorre los tokens secuencialmente con un índice j y un tiempo acumulado
    t (en beats). El estado musical (tempo, programa, velocity) se mantiene
    en variables de la función externa y se actualiza con nonlocal dentro
    de la función anidada process().

    Args:
        tokens:      Lista de LexToken producida por tokenize().
        output_path: Ruta donde se escribirá el archivo .mid resultante.

    Returns:
        La ruta absoluta del archivo .mid generado.
    """
    midi     = MIDIFile(1)   # 1 pista MIDI
    track    = 0             # Índice de pista (siempre 0 en este compilador)
    channel  = 0             # Canal MIDI (0-15; 0 es el canal estándar melódico)
    tempo    = 120           # BPM por defecto si el código no define 'tempo'
    program  = 0             # Programa MIDI por defecto (piano acústico = 0)
    velocity = 80            # Volumen por defecto (0-127)
    midi.addTempo(track, 0, tempo)
    midi.addProgramChange(track, channel, 0, program)

    def process(tok_list: list, t: float) -> float:
        """
        Procesa una lista de tokens y escribe las notas en el objeto MIDI.

        Se llama recursivamente para manejar bloques anidados (track, repeat).
        Actualiza las variables de estado (tempo, program, velocity) del
        ámbito exterior usando nonlocal.

        Args:
            tok_list: Sublista de tokens a procesar (bloque completo o programa).
            t:        Tiempo de inicio en beats para el primer evento.

        Returns:
            El tiempo acumulado t después de procesar todos los tokens.
        """
        nonlocal tempo, program, velocity
        j = 0
        while j < len(tok_list):
            tok = tok_list[j]

            # volume N → actualiza velocity (clampeado a rango MIDI 0-127)
            if tok.type == 'VOLUME_KW':
                if j + 1 < len(tok_list) and tok_list[j + 1].type == 'NUMBER':
                    velocity = max(0, min(127, tok_list[j + 1].value))
                    j += 2; continue

            # tempo N → actualiza BPM en el archivo MIDI en el tiempo actual
            elif tok.type == 'TEMPO_KW':
                if j + 1 < len(tok_list) and tok_list[j + 1].type == 'NUMBER':
                    tempo = tok_list[j + 1].value
                    midi.addTempo(track, t, tempo)
                    j += 2; continue

            # instrument NAME → cambia el programa MIDI del canal en tiempo t
            elif tok.type == 'INSTRUMENT_KW':
                if j + 1 < len(tok_list) and tok_list[j + 1].type == 'INSTR_NAME':
                    program = INSTRUMENT_PROGRAM.get(tok_list[j + 1].value, 0)
                    midi.addProgramChange(track, channel, t, program)
                    j += 2; continue

            # track NAME { ... } → extrae el bloque y lo procesa recursivamente
            elif tok.type == 'TRACK_KW':
                k = j + 1
                # Avanza hasta encontrar el LBRACE de apertura del track
                while k < len(tok_list) and tok_list[k].type != 'LBRACE':
                    k += 1
                if k < len(tok_list):
                    block, end = _collect_block(tok_list, k + 1)
                    t = process(block, t)
                    j = end; continue

            # repeat N { ... } → extrae el bloque y lo procesa N veces seguidas
            elif tok.type == 'REPEAT_KW':
                n, k = 1, j + 1
                if k < len(tok_list) and tok_list[k].type == 'NUMBER':
                    n = tok_list[k].value; k += 1
                while k < len(tok_list) and tok_list[k].type != 'LBRACE':
                    k += 1
                if k < len(tok_list):
                    block, end = _collect_block(tok_list, k + 1)
                    for _ in range(n):
                        t = process(block, t)   # Cada iteración parte desde t actualizado
                    j = end; continue

            # chord { NOTE... DURATION } → agrega todas las notas en el mismo t
            elif tok.type == 'CHORD_KW':
                k = j + 1
                while k < len(tok_list) and tok_list[k].type != 'LBRACE':
                    k += 1
                if k < len(tok_list):
                    block, end = _collect_block(tok_list, k + 1)
                    chord_notes = [b.value for b in block if b.type == 'NOTE']
                    # El último DURATION del bloque es la duración compartida del acorde
                    dur_tok = next((b for b in reversed(block) if b.type == 'DURATION'), None)
                    dur = DURATION_BEATS.get(dur_tok.value, 1.0) if dur_tok else 1.0
                    for note in chord_notes:
                        midi.addNote(track, channel, note_to_midi(note), t, dur, velocity)
                    t += dur   # Avanza t una sola vez (todas las notas son simultáneas)
                    j = end; continue

            # NOTE [DURATION] → agrega la nota y avanza t por su duración
            elif tok.type == 'NOTE':
                dur = 1.0   # Duración por defecto si no viene DURATION después
                if j + 1 < len(tok_list) and tok_list[j + 1].type == 'DURATION':
                    dur = DURATION_BEATS.get(tok_list[j + 1].value, 1.0)
                    j += 1
                try:
                    midi.addNote(track, channel, note_to_midi(tok.value), t, dur, 80)
                except Exception:
                    pass   # Ignora notas con valores MIDI fuera de rango
                t += dur

            # rest [DURATION] → silencio: solo avanza t, no agrega nota
            elif tok.type == 'REST':
                dur = 1.0
                if j + 1 < len(tok_list) and tok_list[j + 1].type == 'DURATION':
                    dur = DURATION_BEATS.get(tok_list[j + 1].value, 1.0)
                    j += 1
                t += dur   # El tiempo avanza igual que con una nota, pero sin sonido

            j += 1
        return t

    process(tokens, 0.0)   # Procesa el programa completo desde t=0

    with open(output_path, 'wb') as f:
        midi.writeFile(f)

    return output_path
