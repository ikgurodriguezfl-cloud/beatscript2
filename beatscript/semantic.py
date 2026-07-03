"""
BeatScript — Analizador Semántico (Etapa 3)
============================================
Pass 1 (_collect_tracks): registra todos los tracks en la tabla de
    símbolos sin importar su posición ni anidamiento.
Pass 2 (_visit_program):  recorre en orden de ejecución, arrastrando
    contexto (velocity, transpose), y valida todo lo demás.
"""

from beatscript.parser import (
    Program, Tempo, Volume, Pan, Compas, Instrument,
    Track, Note, Rest, Chord, Repeat, Transpose, Accent, Sequence
)
from beatscript.midi_gen import note_to_midi, DURATION_BEATS

MIDI_MIN, MIDI_MAX                 = 0, 127
MIDI_AUDIBLE_MIN, MIDI_AUDIBLE_MAX = 21, 108     # A0–C8, piano de 88 teclas
TEMPO_MIN, TEMPO_MAX               = 20, 300
VALID_DENOMINATORS                 = {1, 2, 4, 8, 16, 32}


def _calc_events_duration(events: list) -> float:
    """Duración total en beats de una lista de eventos del AST (recursivo)."""
    total = 0.0
    for event in events:
        if isinstance(event, (Note, Rest, Chord)):
            total += DURATION_BEATS.get(event.duration, 1.0)
        elif isinstance(event, Repeat):
            total += _calc_events_duration(event.events) * event.count
        elif isinstance(event, (Transpose, Accent)):
            total += _calc_events_duration(event.events)
        # Volume, Pan, Instrument no avanzan el tiempo
    return total

class SemanticAnalyzer:
    def __init__(self, ast: Program):
        self.ast = ast
        self.errors = []
        self.warnings = []
        self._symbols = {
            "tracks": {},                  # nombre -> {node, empty, referenced, duration}
            "instrument_count": 0,
            "has_audible_output": False,
            "compas_declared": False,
            "global_velocity": 80,
            "sequence_exists": False,
            "sequence_refs": set(),
            "sequence_total_duration": 0.0,
        }

    def analyze(self):
        self._collect_tracks(self.ast)     # Pass 1
        self._visit_program(self.ast)      # Pass 2
        self._check_global_invariants()    # Post-checks
        return self.errors, self.warnings
    
    def _statement_plays_something(self, stmt) -> bool:
        """True si stmt ES o CONTIENE (anidado) un Track o Sequence."""
        if isinstance(stmt, (Track, Sequence)):
            return True
        if isinstance(stmt, (Repeat, Transpose, Accent)):
            return any(self._statement_plays_something(s) for s in stmt.events)
        return False

    # ── Reporte ──────────────────────────────────────────
    def _loc(self, node) -> str:
        if node is None:
            return ""
        lineno = node if isinstance(node, int) else getattr(node, "lineno", None)
        return f"Línea {lineno}: " if lineno else ""

    def _error(self, code: int, message: str, node=None):
        self.errors.append(f"[ERROR SEMÁNTICO #{code:02d}] {self._loc(node)}{message}")

    def _warning(self, code: int, message: str, node=None):
        self.warnings.append(f"[ADVERTENCIA SEMÁNTICA #{code:02d}] {self._loc(node)}{message}")

    # ── Pass 1: tabla de símbolos ────────────────────────

    def _collect_tracks(self, node, multiplier=1):
        if isinstance(node, Program):
            for stmt in node.statements:
                self._collect_tracks(stmt, multiplier)
        elif isinstance(node, Track):
            self._register_track(node, multiplier)
        elif isinstance(node, Repeat):
            for event in node.events:
                self._collect_tracks(event, multiplier * max(node.count, 0))
        elif isinstance(node, (Transpose, Accent)):
            for event in node.events:
                self._collect_tracks(event, multiplier)

    def _register_track(self, node: Track, multiplier: int = 1):
        if node.name in self._symbols["tracks"]:
            self._error(16, f"Track '{node.name}' está declarado más de una vez; los "
                            f"nombres de track deben ser únicos.", node)
            return
        empty = len(node.events) == 0
        self._symbols["tracks"][node.name] = {
            "node": node, "empty": empty, "referenced": False,
            "duration": _calc_events_duration(node.events) * multiplier,
        }
        if empty:
            self._warning(15, f"Track '{node.name}' está vacío y no producirá ninguna nota.", node)
        else:
            self._symbols["has_audible_output"] = True

    # ── Pass 2: validación en orden de ejecución ─────────

    def _visit_program(self, node: Program):
        context = {"velocity": self._symbols["global_velocity"], "transpose": 0}
        pending_tempo = None
        pending_instrument = None

        for stmt in node.statements:
            if isinstance(stmt, Tempo):
                self._visit_tempo(stmt)
                if pending_tempo is not None:
                    self._warning(18,
                        f"tempo {pending_tempo.bpm} es sobreescrito por tempo "
                        f"{stmt.bpm} sin que ningún track haya sonado con el "
                        f"valor anterior.", pending_tempo)
                pending_tempo = stmt

            elif isinstance(stmt, Instrument):
                self._visit_instrument(stmt)
                if pending_instrument is not None:
                    self._warning(19,
                        f"instrument '{pending_instrument.name}' es "
                        f"sobreescrito por instrument '{stmt.name}' sin que "
                        f"ningún track haya sonado con el anterior.", pending_instrument)
                pending_instrument = stmt

            else:
                self._visit(stmt, context)
                if self._statement_plays_something(stmt):
                    pending_tempo = None
                    pending_instrument = None
    def _visit(self, node, context):
        if isinstance(node, Tempo):          self._visit_tempo(node)
        elif isinstance(node, Instrument):   self._visit_instrument(node)
        elif isinstance(node, Volume):       self._visit_volume(node, context)
        elif isinstance(node, Pan):          self._visit_pan(node)
        elif isinstance(node, Compas):       self._visit_compas(node)
        elif isinstance(node, Track):        self._visit_track(node, context)
        elif isinstance(node, Sequence):     self._visit_sequence(node)
        elif isinstance(node, Note):         self._visit_note(node, context)
        elif isinstance(node, Chord):        self._visit_chord(node, context)
        elif isinstance(node, Repeat):       self._visit_repeat(node, context)
        elif isinstance(node, Transpose):    self._visit_transpose(node, context)
        elif isinstance(node, Accent):       self._visit_accent(node, context)

    def _visit_tempo(self, node: Tempo):
        if not (TEMPO_MIN <= node.bpm <= TEMPO_MAX):
            self._error(1,
                f"tempo {node.bpm} fuera de rango musical válido "
                f"({TEMPO_MIN}-{TEMPO_MAX} BPM).", node)

    def _visit_volume(self, node: Volume, context: dict):
        if not (0 <= node.level <= 127):
            self._error(2, f"volume {node.level} fuera del rango MIDI válido (0-127).", node)
        else:
            context["velocity"] = node.level
            self._symbols["global_velocity"] = node.level

    def _visit_pan(self, node: Pan):
        if not (0 <= node.value <= 127):
            self._error(3, f"pan {node.value} fuera del rango MIDI válido (0-127).", node)

    def _visit_compas(self, node: Compas):
        if node.numerator == 0:
            self._error(12,
                f"compas {node.numerator}/{node.denominator}: el numerador "
                f"no puede ser cero.", node)
        if node.denominator not in VALID_DENOMINATORS:
            self._error(11,
                f"compas {node.numerator}/{node.denominator}: el denominador "
                f"debe ser potencia de 2 "
                f"({', '.join(str(v) for v in sorted(VALID_DENOMINATORS))}).", node)
        self._symbols["compas_declared"] = True

    def _visit_instrument(self, node: Instrument):
        self._symbols["instrument_count"] += 1

    def _visit_track(self, node: Track, context: dict):
        track_context = dict(context)
        for event in node.events:
            self._visit(event, track_context)

    def _check_pitch(self, pitch: str, context: dict, node=None):
        try:
            base_val = note_to_midi(pitch)
        except Exception:
            return
        transpose = context.get("transpose", 0)
        midi_val = base_val + transpose

        if not (MIDI_MIN <= midi_val <= MIDI_MAX):
            if transpose != 0:
                self._error(8,
                    f"transpose {transpose:+d} convierte '{pitch}' "
                    f"(MIDI {base_val}) en MIDI {midi_val}, fuera del rango "
                    f"válido (0-127).", node)
            else:
                self._error(9,
                    f"nota '{pitch}' produce valor MIDI {midi_val}, fuera "
                    f"del rango válido (0-127).", node)
        elif not (MIDI_AUDIBLE_MIN <= midi_val <= MIDI_AUDIBLE_MAX):
            self._warning(10,
                f"nota '{pitch}' (MIDI {midi_val}) fuera del rango "
                f"perceptible por el oído humano "
                f"({MIDI_AUDIBLE_MIN}-{MIDI_AUDIBLE_MAX}).", node)

    def _visit_note(self, node: Note, context: dict):
        self._check_pitch(node.pitch, context, node)

    def _visit_chord(self, node: Chord, context: dict):
        if len(node.notes) == 0:
            self._error(14, "chord sin notas: debe contener al menos dos notas.", node)
            return
        if len(node.notes) == 1:
            self._warning(13,
                f"chord con una sola nota '{node.notes[0]}'; un acorde "
                f"requiere dos o más notas simultáneas.", node)
        if "_punto" in node.duration and not self._symbols["compas_declared"]:
            self._warning(20,
                f"chord usa duración '{node.duration}' pero no hay 'compas' "
                f"declarado antes; el valor real con punto es ambiguo.", node)
        for pitch in node.notes:
            self._check_pitch(pitch, context, node)

    def _visit_repeat(self, node: Repeat, context: dict):
        if node.count == 0:
            self._warning(6, "repeat 0 — el bloque nunca se ejecutará; es código muerto.", node)
            return
        for event in node.events:
            self._visit(event, context)

    def _visit_transpose(self, node: Transpose, context: dict):
        if node.semitones == 0:
            self._warning(7,
                "transpose 0 no produce ningún cambio; es idéntico a omitir "
                "la instrucción.", node)
        new_context = dict(context)
        new_context["transpose"] = context.get("transpose", 0) + node.semitones
        for event in node.events:
            self._visit(event, new_context)

    def _visit_accent(self, node: Accent, context: dict):
        if node.velocity is not None and not (0 <= node.velocity <= 127):
            self._error(4, f"acento {node.velocity}: velocity fuera del rango MIDI válido (0-127).", node)

        current = context.get("velocity", self._symbols["global_velocity"])
        effective = node.velocity if node.velocity is not None else min(127, current + 20)
        if effective <= current:
            label = node.velocity if node.velocity is not None else "(auto +20)"
            self._warning(5,
                f"acento {label}: la velocity resultante ({effective}) no "
                f"supera el volume actual ({current}); no producirá énfasis "
                f"audible.", node)

        accent_context = dict(context)
        accent_context["velocity"] = min(127, effective)
        for event in node.events:
            self._visit(event, accent_context)

    def _visit_sequence(self, node: Sequence):
        if len(node.groups) == 0:
            self._warning(23, "secuencia { } está vacía y no producirá ninguna salida.", node)
            return

        self._symbols["sequence_exists"] = True
        declared = self._symbols["tracks"]

        for i, (names, is_parallel, _lineno) in enumerate(node.groups, 1):
            if is_parallel and len(names) == 1:
                self._warning(26,
                    f"el grupo paralelo en la posición {i} de secuencia "
                    f"contiene un solo track ('{names[0]}'); los paréntesis "
                    f"son innecesarios.", node)

            seen = set()
            for name in names:
                if name not in declared:
                    self._error(21,
                        f"track '{name}' referenciado en secuencia pero "
                        f"nunca fue declarado.", node)
                    continue
                if name in seen:
                    self._warning(24,
                        f"track '{name}' aparece más de una vez en el mismo "
                        f"grupo paralelo de secuencia.", node)
                else:
                    seen.add(name)
                    declared[name]["referenced"] = True
                    self._symbols["sequence_refs"].add(name)

        self._symbols["sequence_total_duration"] = sum(
            max((declared[n]["duration"] for n in names if n in declared), default=0.0)
            for names, _, _ in node.groups
        )
        self._symbols["has_audible_output"] = True

    # ── Invariantes globales ──────────────────────────────

    def _check_global_invariants(self):
        if not self._symbols["has_audible_output"]:
            self._error(17,
                "el programa no contiene ningún track con notas; el MIDI "
                "generado estaría vacío.")

        if self._symbols["sequence_exists"]:
            for name, info in self._symbols["tracks"].items():
                if not info["referenced"] and not info["empty"]:
                    self._warning(22,
                        f"track '{name}' está declarado pero nunca es "
                        f"referenciado en secuencia; no producirá salida.", info["node"])

            seq_duration = self._symbols["sequence_total_duration"]
            if seq_duration > 0:
                for name, info in self._symbols["tracks"].items():
                    if name in self._symbols["sequence_refs"] or info["empty"]:
                        continue
                    if info["duration"] > seq_duration * 2:
                        self._warning(25,
                            f"track '{name}' corre fuera de secuencia desde "
                            f"t=0 con duración {info['duration']:.2f} beats, "
                            f"más del doble de la secuencia completa "
                            f"({seq_duration:.2f} beats).", info["node"])