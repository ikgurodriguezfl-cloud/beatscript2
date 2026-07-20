"""
BeatScript — Generador de Código de Tres Direcciones (Etapa 4)
================================================================
Traduce el AST (ya validado por semantic.py, cero errores) a TAC
representado como cuádruplos (operador, arg1, arg2, resultado).

Diseño:
    - Cada track genera su propia rutina TAC independiente, con su
      propio namespace de temporales y etiquetas (prefijado con el
      nombre del track). TAC modela un único flujo de control y los
      tracks corren en paralelo entre sí, así que no pueden compartir
      una sola rutina.
    - secuencia no se traduce dentro de ninguna rutina — se resuelve
      aparte, como una tabla de "scheduling": el offset de arranque
      (valor inicial de t) de cada rutina. Ese offset SÍ se calcula
      como constante en tiempo de compilación (duración fija de cada
      track, igual que en semantic.py), independientemente de que el
      avance de t dentro de la rutina se deje sin plegar.
    - No se pliega ninguna constante: ni el cálculo de pitch (letra +
      octava + alteración + transposición), ni el avance de tiempo, ni
      los saltos de repeat. Cada operación se emite explícitamente.
      Plegarlas es trabajo de una fase de optimización posterior
      (propagación de constantes + desenrollado de loops), no de esta.

Convención de cuádruplos:
    MOV   dst, src            →  dst = src            (arg1=src, result=dst)
    ADD   dst, a, b           →  dst = a + b
    SUB   dst, a, b           →  dst = a - b
    MUL   dst, a, b           →  dst = a * b
    MIN   dst, a, b           →  dst = min(a, b)
    LT    dst, a, b           →  dst = (a < b)
    LABEL L                   →  define la etiqueta L
    GOTO  L                   →  salta a L
    IFFALSE cond, L           →  salta a L si cond es falso
    PARAM x                   →  apila x como argumento
    CALL  f, n                →  llama a f consumiendo los últimos n PARAM

Rutinas de biblioteca invocadas con CALL (son las que producen efecto
real sobre el MIDI final, ver midi_gen.py):
    emit_note(pitch, dur, vel, chan, time)
    set_tempo(bpm, time)
    set_program(prog, chan, time)
    set_pan(pan, chan, time)
"""

from beatscript.parser import (
    Program, Tempo, Volume, Pan, Compas, Instrument,
    Track, Note, Rest, Chord, Repeat, Transpose, Accent, Sequence
)
from beatscript.midi_gen import NOTE_SEMITONES, DURATION_BEATS, INSTRUMENT_PROGRAM


# ── Representación del TAC ────────────────────────────────────────────

class Quad:
    """Un cuádruplo: (operador, arg1, arg2, resultado)."""
    _slots_ = ("op", "arg1", "arg2", "result")

    def __init__(self, op, arg1=None, arg2=None, result=None):
        self.op, self.arg1, self.arg2, self.result = op, arg1, arg2, result

    def __repr__(self):
        fmt = lambda x: "_" if x is None else str(x)
        return f"({self.op}, {fmt(self.arg1)}, {fmt(self.arg2)}, {fmt(self.result)})"


class Routine:
    """Una rutina TAC independiente: un track, o el prólogo global."""
    def __init__(self, name: str):
        self.name = name
        self.quads: list[Quad] = []

    def emit(self, op, arg1=None, arg2=None, result=None):
        self.quads.append(Quad(op, arg1, arg2, result))
        return result


class _NameSupply:
    """Genera nombres únicos de temporales/etiquetas por prefijo."""
    def __init__(self):
        self._n = {}

    def new(self, prefix: str) -> str:
        self._n[prefix] = self._n.get(prefix, 0) + 1
        return f"{prefix}{self._n[prefix]}"


def _events_duration(events: list) -> float:
    """
    Duración total en beats de una lista de eventos del AST.
    Réplica local de la misma lógica de semantic.py — se necesita aquí
    para calcular offsets de arranque de 'secuencia' como constantes,
    independientemente de cómo se represente el avance de t en el TAC.
    """
    total = 0.0
    for event in events:
        if isinstance(event, (Note, Rest, Chord)):
            total += DURATION_BEATS.get(event.duration, 1.0)
        elif isinstance(event, Repeat):
            total += _events_duration(event.events) * event.count
        elif isinstance(event, (Transpose, Accent)):
            total += _events_duration(event.events)
    return total


# ── Generador principal ────────────────────────────────────────────────

class TACGenerator:
    """
    Genera TAC a partir del AST de BeatScript.

    Uso:
        prologue, routines, schedule = TACGenerator(ast).generate()
    """

    def __init__(self, ast: Program):
        self.ast = ast
        self.names = _NameSupply()
        self.prologue = Routine("_global")
        self.routines: list[Routine] = []
        self._track_nodes = {}   # nombre de track -> nodo Track (para duración/schedule)

    # ── Punto de entrada ──────────────────────────────────

    def generate(self):
        """
        Devuelve (prologue, routines, schedule):
            prologue:  Routine con el/los set_tempo global(es)
            routines:  lista de Routine, una por track, en orden de aparición
            schedule:  dict {nombre_de_track: offset_inicial_en_beats}
        """
        defaults = {"program": 0, "velocity": 80, "pan": 64}
        sequences = []

        for stmt in self.ast.statements:
            if isinstance(stmt, Tempo):
                self.prologue.emit("PARAM", stmt.bpm)
                self.prologue.emit("PARAM", 0.0)
                self.prologue.emit("CALL", "set_tempo", 2)

            elif isinstance(stmt, Instrument):
                defaults["program"] = INSTRUMENT_PROGRAM.get(stmt.name, 0)

            elif isinstance(stmt, Volume):
                defaults["velocity"] = stmt.level

            elif isinstance(stmt, Pan):
                defaults["pan"] = stmt.value

            elif isinstance(stmt, Track):
                self._track_nodes[stmt.name] = stmt
                routine = self._generate_track(stmt, dict(defaults))
                self.routines.append(routine)

            elif isinstance(stmt, Sequence):
                sequences.append(stmt)
            # Compas: metadata de métrica, no genera TAC ejecutable.

        schedule = self._build_schedule(sequences)
        return self.prologue, self.routines, schedule

    # ── Scheduling de 'secuencia' ─────────────────────────

    def _build_schedule(self, sequences: list) -> dict:
        """
        Offset de arranque (en beats) de cada track:
        - Referenciado en 'secuencia': arranca cuando termina el grupo anterior.
        - Fuera de toda 'secuencia': arranca en 0.0 (paralelo desde el inicio).
        """
        schedule = {name: 0.0 for name in self._track_nodes}
        for seq in sequences:
            offset = 0.0
            for names, is_parallel, _lineno in seq.groups:
                group_end = offset
                for name in names:
                    node = self._track_nodes.get(name)
                    if node is None:
                        continue   # referencia inválida, ya reportada por semantic.py
                    schedule[name] = offset
                    group_end = max(group_end, offset + _events_duration(node.events))
                offset = group_end
        return schedule

    # ── Generación de una rutina de track ────────────────

    def _generate_track(self, node: Track, defaults: dict) -> Routine:
        r = Routine(node.name)
        ns = f"{node.name}_"

        t_var      = ns + "t"
        vel_var    = ns + "vel"
        prog_var   = ns + "prog"
        pan_var    = ns + "pan"
        transp_var = ns + "transp"
        chan_const = 0

        r.emit("MOV", 0.0,                  None, t_var)
        r.emit("MOV", defaults["velocity"], None, vel_var)
        r.emit("MOV", defaults["program"],  None, prog_var)
        r.emit("MOV", defaults["pan"],      None, pan_var)
        r.emit("MOV", 0,                    None, transp_var)

        r.emit("PARAM", prog_var); r.emit("PARAM", chan_const); r.emit("PARAM", t_var)
        r.emit("CALL", "set_program", 3)

        r.emit("PARAM", pan_var); r.emit("PARAM", chan_const); r.emit("PARAM", t_var)
        r.emit("CALL", "set_pan", 3)

        ctx = {"t": t_var, "vel": vel_var, "prog": prog_var, "pan": pan_var,
               "transp": transp_var, "chan": chan_const, "ns": ns}
        for event in node.events:
            self._gen_event(r, event, ctx)
        return r

    # ── Despachador de eventos ────────────────────────────

    def _gen_event(self, r: Routine, node, ctx: dict):
        if isinstance(node, Note):          self._gen_note(r, node, ctx)
        elif isinstance(node, Rest):        self._gen_rest(r, node, ctx)
        elif isinstance(node, Chord):       self._gen_chord(r, node, ctx)
        elif isinstance(node, Repeat):      self._gen_repeat(r, node, ctx)
        elif isinstance(node, Transpose):   self._gen_transpose(r, node, ctx)
        elif isinstance(node, Accent):      self._gen_accent(r, node, ctx)
        elif isinstance(node, Volume):
            r.emit("MOV", node.level, None, ctx["vel"])
        elif isinstance(node, Pan):
            r.emit("MOV", node.value, None, ctx["pan"])
            r.emit("PARAM", ctx["pan"]); r.emit("PARAM", ctx["chan"]); r.emit("PARAM", ctx["t"])
            r.emit("CALL", "set_pan", 3)
        elif isinstance(node, Instrument):
            prog = INSTRUMENT_PROGRAM.get(node.name, 0)
            r.emit("MOV", prog, None, ctx["prog"])
            r.emit("PARAM", ctx["prog"]); r.emit("PARAM", ctx["chan"]); r.emit("PARAM", ctx["t"])
            r.emit("CALL", "set_program", 3)

    # ── Cálculo de pitch (sin plegar aritmética) ──────────

    def _gen_pitch(self, r: Routine, pitch_str: str, ctx: dict) -> str:
        s = pitch_str.upper()
        letter = s[0]
        rest = s[1:]
        if rest and rest[0] in ("#", "B") and len(rest) > 1:
            alt, octave = rest[0], int(rest[1])
        else:
            alt, octave = "", int(rest[0])

        semis = NOTE_SEMITONES[letter]
        t_oct  = self.names.new(ctx["ns"] + "oct")
        r.emit("ADD", octave, 1, t_oct)
        t_mul  = self.names.new(ctx["ns"] + "mul")
        r.emit("MUL", t_oct, 12, t_mul)
        t_base = self.names.new(ctx["ns"] + "pitch")
        r.emit("ADD", semis, t_mul, t_base)

        if alt == "#":
            t_alt = self.names.new(ctx["ns"] + "pitch")
            r.emit("ADD", t_base, 1, t_alt)
            t_base = t_alt
        elif alt == "B":
            t_alt = self.names.new(ctx["ns"] + "pitch")
            r.emit("SUB", t_base, 1, t_alt)
            t_base = t_alt

        t_final = self.names.new(ctx["ns"] + "pitch")
        r.emit("ADD", t_base, ctx["transp"], t_final)
        return t_final

    # ── Eventos individuales ──────────────────────────────

    def _gen_note(self, r: Routine, node: Note, ctx: dict):
        pitch_t = self._gen_pitch(r, node.pitch, ctx)
        dur = DURATION_BEATS.get(node.duration, 1.0)
        r.emit("PARAM", pitch_t); r.emit("PARAM", dur)
        r.emit("PARAM", ctx["vel"]); r.emit("PARAM", ctx["chan"]); r.emit("PARAM", ctx["t"])
        r.emit("CALL", "emit_note", 5)
        r.emit("ADD", ctx["t"], dur, ctx["t"])

    def _gen_rest(self, r: Routine, node: Rest, ctx: dict):
        dur = DURATION_BEATS.get(node.duration, 1.0)
        r.emit("ADD", ctx["t"], dur, ctx["t"])

    def _gen_chord(self, r: Routine, node: Chord, ctx: dict):
        dur = DURATION_BEATS.get(node.duration, 1.0)
        for pitch in node.notes:
            pitch_t = self._gen_pitch(r, pitch, ctx)
            r.emit("PARAM", pitch_t); r.emit("PARAM", dur)
            r.emit("PARAM", ctx["vel"]); r.emit("PARAM", ctx["chan"]); r.emit("PARAM", ctx["t"])
            r.emit("CALL", "emit_note", 5)
        r.emit("ADD", ctx["t"], dur, ctx["t"])

    def _gen_repeat(self, r: Routine, node: Repeat, ctx: dict):
        i_var  = self.names.new(ctx["ns"] + "i")
        cond   = self.names.new(ctx["ns"] + "cond")
        l_cond = self.names.new(ctx["ns"] + "Lcond")
        l_end  = self.names.new(ctx["ns"] + "Lend")

        r.emit("MOV", 0, None, i_var)
        r.emit("LABEL", l_cond)
        r.emit("LT", i_var, node.count, cond)
        r.emit("IFFALSE", cond, l_end)
        for event in node.events:
            self._gen_event(r, event, ctx)
        r.emit("ADD", i_var, 1, i_var)
        r.emit("GOTO", l_cond)
        r.emit("LABEL", l_end)

    def _gen_transpose(self, r: Routine, node: Transpose, ctx: dict):
        r.emit("ADD", ctx["transp"], node.semitones, ctx["transp"])
        for event in node.events:
            self._gen_event(r, event, ctx)
        r.emit("SUB", ctx["transp"], node.semitones, ctx["transp"])

    def _gen_accent(self, r: Routine, node: Accent, ctx: dict):
        save = self.names.new(ctx["ns"] + "save_vel")
        r.emit("MOV", ctx["vel"], None, save)
        if node.velocity is not None:
            r.emit("MOV", node.velocity, None, ctx["vel"])
        else:
            boosted = self.names.new(ctx["ns"] + "vel")
            r.emit("ADD", ctx["vel"], 20, boosted)
            clamped = self.names.new(ctx["ns"] + "vel")
            r.emit("MIN", boosted, 127, clamped)
            r.emit("MOV", clamped, None, ctx["vel"])
        for event in node.events:
            self._gen_event(r, event, ctx)
        r.emit("MOV", save, None, ctx["vel"])


# ── Conversión a tripletas ──────────────────────────────────────────────

class TripleRef:
    """Referencia posicional a otra tripleta (sustituye al nombre del resultado)."""
    _slots_ = ("index",)
    def __init__(self, index): self.index = index
    def __repr__(self): return f"({self.index})"


def quads_to_triples(quads: list) -> list:
    """
    Convierte cuádruplos a tripletas (operador, arg1, arg2), sin campo
    de resultado explícito. Toda referencia a una variable se reemplaza
    por un TripleRef al índice de la instrucción que la definió MÁS
    RECIENTEMENTE — no simplemente "la primera" — porque variables como
    t/vel/transp/i se reasignan varias veces a lo largo de una rutina,
    a diferencia de un temporal de un solo uso.
    """
    last_def = {}
    triples = []

    def resolve(arg):
        if isinstance(arg, str) and arg in last_def:
            return TripleRef(last_def[arg])
        return arg

    for idx, q in enumerate(quads):
        if q.op in ("LABEL", "GOTO"):
            triples.append((q.op, q.arg1, None))
        elif q.op == "IFFALSE":
            triples.append((q.op, resolve(q.arg1), q.arg2))   # arg2 es etiqueta
        elif q.op in ("PARAM",):
            triples.append((q.op, resolve(q.arg1), None))
        elif q.op == "CALL":
            triples.append((q.op, q.arg1, q.arg2))            # nombre de función, aridad
        else:
            triples.append((q.op, resolve(q.arg1), resolve(q.arg2)))

        if q.result is not None:
            last_def[q.result] = idx

    return triples


# ── Utilidades de presentación (para Treeview u otra tabla) ────────────

def quads_to_table_rows(quads: list) -> list:
    """Filas (num, operador, arg1, arg2, resultado) para mostrar en una tabla."""
    fmt = lambda x: "" if x is None else str(x)
    return [(i, q.op, fmt(q.arg1), fmt(q.arg2), fmt(q.result)) for i, q in enumerate(quads)]


def triples_to_table_rows(triples: list) -> list:
    """Filas (num, operador, arg1, arg2) para mostrar en una tabla."""
    fmt = lambda x: "" if x is None else str(x)
    return [(i, op, fmt(a1), fmt(a2)) for i, (op, a1, a2) in enumerate(triples)]


def format_quads(quads: list) -> str:
    lines = [f"{i:>3}: ({q.op}, {q.arg1}, {q.arg2}, {q.result})" for i, q in enumerate(quads)]
    return "\n".join(lines)


def format_triples(triples: list) -> str:
    lines = [f"{i:>3}: ({op}, {a1}, {a2})" for i, (op, a1, a2) in enumerate(triples)]
    return "\n".join(lines)


# ── Código de tres direcciones en notación lineal (x = y op z) ─────────
# Esta es la representación "de libro de texto" del código intermedio:
# una instrucción por línea, con a lo más un operador del lado derecho.
# Distinta de los cuádruplos/tripletas de arriba, que son solo formas
# tabulares equivalentes pensadas para mostrarse en un Treeview.

_BIN_SYMBOL = {"ADD": "+", "SUB": "-", "MUL": "*"}


def quad_to_statement(q: Quad) -> str:
    """Convierte un único cuádruplo a su instrucción de tres direcciones."""
    if q.op == "MOV":
        return f"{q.result} = {q.arg1}"
    if q.op in _BIN_SYMBOL:
        return f"{q.result} = {q.arg1} {_BIN_SYMBOL[q.op]} {q.arg2}"
    if q.op == "MIN":
        return f"{q.result} = min({q.arg1}, {q.arg2})"
    if q.op == "LT":
        return f"{q.result} = {q.arg1} < {q.arg2}"
    if q.op == "LABEL":
        return f"{q.arg1}:"
    if q.op == "GOTO":
        return f"goto {q.arg1}"
    if q.op == "IFFALSE":
        return f"if not {q.arg1} goto {q.arg2}"
    if q.op == "PARAM":
        return f"param {q.arg1}"
    if q.op == "CALL":
        return f"call {q.arg1}, {q.arg2}"
    return f"{q.op} {q.arg1}, {q.arg2}, {q.result}"


def quads_to_code_lines(quads: list) -> list:
    """Lista de (num, instrucción_texto) para mostrar en una vista tipo editor."""
    return [(i, quad_to_statement(q)) for i, q in enumerate(quads)]


def format_code(quads: list) -> str:
    """Bloque de texto con el código de tres direcciones en notación lineal."""
    lines = [f"{i:>3}:  {quad_to_statement(q)}" for i, q in enumerate(quads)]
    return "\n".join(lines)