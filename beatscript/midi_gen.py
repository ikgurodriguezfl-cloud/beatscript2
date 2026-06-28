"""Generacion MIDI para BeatScript."""

from midiutil import MIDIFile

NOTE_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

DURATION_BEATS = {
    "redonda": 4.0,
    "blanca": 2.0,
    "negra": 1.0,
    "corchea": 0.5,
    "semicorchea": 0.25,
    "fusa": 0.125,
    "semifusa": 0.0625,
}

INSTRUMENT_PROGRAM = {
    "piano": 0,
    "violin": 40,
    "viola": 41,
    "cello": 42,
    "contrabass": 43,
    "harp": 46,
    "flute": 73,
    "piccolo": 72,
    "recorder": 74,
    "oboe": 68,
    "clarinet": 71,
    "bassoon": 70,
    "saxophone": 65,
    "trumpet": 56,
    "trombone": 57,
    "frenchhorn": 60,
    "tuba": 58,
    "marimba": 12,
    "vibraphone": 11,
    "xylophone": 13,
    "celesta": 8,
    "drums": 0,
    "guitar": 25,
    "bass": 32,
    "banjo": 105,
    "sitar": 104,
    "harpsichord": 6,
    "organ": 19,
    "accordion": 21,
    "harmonica": 22,
}


def note_to_midi(note_str: str) -> int:
    s = note_str.upper()
    letter = s[0]
    rest = s[1:]
    if rest and rest[0] in ("#", "B") and len(rest) > 1:
        alt, octave = rest[0], int(rest[1])
    else:
        alt, octave = "", int(rest[0])
    pitch = NOTE_SEMITONES[letter] + (octave + 1) * 12
    if alt == "#":
        pitch += 1
    if alt == "B":
        pitch -= 1
    return pitch


def _collect_block(tokens: list, start: int):
    depth, end = 1, start
    while end < len(tokens) and depth > 0:
        if tokens[end].type == "LBRACE":
            depth += 1
        elif tokens[end].type == "RBRACE":
            depth -= 1
        end += 1
    return tokens[start:end - 1], end


def _count_tracks(token_groups: list[list]) -> int:
    count = 0
    for tokens in token_groups:
        tracks = sum(1 for tok in tokens if tok.type == "TRACK_KW")
        count += tracks if tracks else 1
    return max(1, count)


def _next_channel(track_index: int) -> int:
    channel = track_index % 15
    return channel if channel < 9 else channel + 1


def tokens_to_midi_documents(token_groups: list[list], output_path: str = "output.mid") -> str:
    """Mezcla varios programas BeatScript en un solo MIDI con pistas paralelas."""
    midi = MIDIFile(_count_tracks(token_groups))
    tempo = 120
    next_track = 0

    def add_pan(track: int, channel: int, time: float, value: int):
        midi.addControllerEvent(track, channel, time, 10, max(0, min(127, value)))

    def process(tok_list: list, track: int, channel: int, time: float,
                program: int, velocity: int, pan: int, transpose: int = 0):
        j = 0
        while j < len(tok_list):
            tok = tok_list[j]

            if tok.type == "VOLUME_KW":
                if j + 1 < len(tok_list) and tok_list[j + 1].type == "NUMBER":
                    velocity = max(0, min(127, tok_list[j + 1].value))
                    j += 2
                    continue

            elif tok.type == "PAN_KW":
                if j + 1 < len(tok_list) and tok_list[j + 1].type == "NUMBER":
                    pan = max(0, min(127, tok_list[j + 1].value))
                    add_pan(track, channel, time, pan)
                    j += 2
                    continue

            elif tok.type == "TEMPO_KW":
                if j + 1 < len(tok_list) and tok_list[j + 1].type == "NUMBER":
                    midi.addTempo(track, time, tok_list[j + 1].value)
                    j += 2
                    continue

            elif tok.type == "INSTRUMENT_KW":
                if j + 1 < len(tok_list) and tok_list[j + 1].type == "INSTR_NAME":
                    program = INSTRUMENT_PROGRAM.get(tok_list[j + 1].value, 0)
                    midi.addProgramChange(track, channel, time, program)
                    j += 2
                    continue

            elif tok.type == "TRACK_KW":
                k = j + 1
                while k < len(tok_list) and tok_list[k].type != "LBRACE":
                    k += 1
                if k < len(tok_list):
                    block, end = _collect_block(tok_list, k + 1)
                    time = process(block, track, channel, time, program, velocity, pan, transpose)[0]
                    j = end
                    continue

            elif tok.type == "REPEAT_KW":
                n, k = 1, j + 1
                if k < len(tok_list) and tok_list[k].type == "NUMBER":
                    n = tok_list[k].value
                    k += 1
                while k < len(tok_list) and tok_list[k].type != "LBRACE":
                    k += 1
                if k < len(tok_list):
                    block, end = _collect_block(tok_list, k + 1)
                    for _ in range(n):
                        time, program, velocity, pan = process(
                            block, track, channel, time, program, velocity, pan, transpose
                        )
                    j = end
                    continue

            elif tok.type == "TRANSPOSE_KW":
                amount, k = 0, j + 1
                if k < len(tok_list) and tok_list[k].type == "NUMBER":
                    amount = tok_list[k].value
                    k += 1
                while k < len(tok_list) and tok_list[k].type != "LBRACE":
                    k += 1
                if k < len(tok_list):
                    block, end = _collect_block(tok_list, k + 1)
                    time, program, velocity, pan = process(
                        block, track, channel, time, program, velocity, pan, transpose + amount
                    )
                    j = end
                    continue

            elif tok.type == "ACCENT_KW":
                accent_velocity, k = None, j + 1
                if k < len(tok_list) and tok_list[k].type == "NUMBER":
                    accent_velocity = max(0, min(127, tok_list[k].value))
                    k += 1
                while k < len(tok_list) and tok_list[k].type != "LBRACE":
                    k += 1
                if k < len(tok_list):
                    block, end = _collect_block(tok_list, k + 1)
                    boosted_velocity = accent_velocity if accent_velocity is not None else min(127, velocity + 20)
                    time, program, _, pan = process(
                        block, track, channel, time, program, boosted_velocity, pan, transpose
                    )
                    j = end
                    continue

            elif tok.type == "CHORD_KW":
                k = j + 1
                while k < len(tok_list) and tok_list[k].type != "LBRACE":
                    k += 1
                if k < len(tok_list):
                    block, end = _collect_block(tok_list, k + 1)
                    notes = [b.value for b in block if b.type == "NOTE"]
                    dur_tok = next((b for b in reversed(block) if b.type == "DURATION"), None)
                    dur = DURATION_BEATS.get(dur_tok.value, 1.0) if dur_tok else 1.0
                    for note in notes:
                        pitch = note_to_midi(note) + transpose
                        if 0 <= pitch <= 127:
                            midi.addNote(track, channel, pitch, time, dur, velocity)
                    time += dur
                    j = end
                    continue

            elif tok.type == "NOTE":
                dur = 1.0
                if j + 1 < len(tok_list) and tok_list[j + 1].type == "DURATION":
                    dur = DURATION_BEATS.get(tok_list[j + 1].value, 1.0)
                    j += 1
                pitch = note_to_midi(tok.value) + transpose
                if 0 <= pitch <= 127:
                    midi.addNote(track, channel, pitch, time, dur, velocity)
                time += dur

            elif tok.type == "REST":
                dur = 1.0
                if j + 1 < len(tok_list) and tok_list[j + 1].type == "DURATION":
                    dur = DURATION_BEATS.get(tok_list[j + 1].value, 1.0)
                    j += 1
                time += dur

            j += 1
        return time, program, velocity, pan

    for tokens in token_groups:
        j = 0
        doc_program = 0
        doc_velocity = 80
        doc_pan = 64
        doc_has_track = any(tok.type == "TRACK_KW" for tok in tokens)

        while j < len(tokens):
            tok = tokens[j]
            if tok.type == "TEMPO_KW" and j + 1 < len(tokens) and tokens[j + 1].type == "NUMBER":
                tempo = tokens[j + 1].value
                j += 2
                continue
            if tok.type == "COMPAS_KW" and j + 2 < len(tokens):
                j += 3
                continue
            if tok.type == "INSTRUMENT_KW" and j + 1 < len(tokens) and tokens[j + 1].type == "INSTR_NAME":
                doc_program = INSTRUMENT_PROGRAM.get(tokens[j + 1].value, 0)
                j += 2
                continue
            if tok.type == "VOLUME_KW" and j + 1 < len(tokens) and tokens[j + 1].type == "NUMBER":
                doc_velocity = max(0, min(127, tokens[j + 1].value))
                j += 2
                continue
            if tok.type == "PAN_KW" and j + 1 < len(tokens) and tokens[j + 1].type == "NUMBER":
                doc_pan = max(0, min(127, tokens[j + 1].value))
                j += 2
                continue

            if tok.type == "TRACK_KW":
                k = j + 1
                while k < len(tokens) and tokens[k].type != "LBRACE":
                    k += 1
                if k < len(tokens):
                    block, end = _collect_block(tokens, k + 1)
                    track = next_track
                    channel = _next_channel(track)
                    midi.addTempo(track, 0, tempo)
                    midi.addProgramChange(track, channel, 0, doc_program)
                    add_pan(track, channel, 0, doc_pan)
                    process(block, track, channel, 0.0, doc_program, doc_velocity, doc_pan)
                    next_track += 1
                    j = end
                    continue

            j += 1

        if not doc_has_track:
            track = next_track
            channel = _next_channel(track)
            midi.addTempo(track, 0, tempo)
            midi.addProgramChange(track, channel, 0, doc_program)
            add_pan(track, channel, 0, doc_pan)
            process(tokens, track, channel, 0.0, doc_program, doc_velocity, doc_pan)
            next_track += 1

    with open(output_path, "wb") as f:
        midi.writeFile(f)

    return output_path


def tokens_to_midi(tokens: list, output_path: str = "output.mid") -> str:
    return tokens_to_midi_documents([tokens], output_path)
