"""Lead melody: a two-bar call over Am-F answered over C-G, played twice.

Chord tones fall on strong beats; passing notes move by step. The second answer
climbs to G5 to lift into the outro, then the lead rests on A4.
"""

# (beat within the four-bar phrase, note, length in beats, velocity)
CALL = [
    (0, "E5", 1.0, 100), (1, "C5", 0.5, 84), (1.5, "D5", 0.5, 88), (2, "E5", 1.5, 96),
    (3.5, "D5", 0.5, 82),
    (4, "C5", 1.0, 94), (5, "A4", 1.0, 86), (6, "C5", 1.5, 90), (7.5, "B4", 0.5, 78),
]
ANSWER_1 = [
    (8, "G4", 0.5, 88), (8.5, "C5", 0.5, 90), (9, "E5", 1.0, 98), (10, "D5", 0.5, 86),
    (10.5, "C5", 0.5, 84), (11, "D5", 1.0, 92),
    (12, "D5", 1.5, 94), (13.5, "B4", 0.5, 80), (14, "G4", 1.0, 86), (15, "B4", 1.0, 90),
]
ANSWER_2 = [
    (8, "G4", 0.5, 92), (8.5, "C5", 0.5, 94), (9, "E5", 1.0, 104), (10, "G5", 0.5, 98),
    (10.5, "E5", 0.5, 92), (11, "D5", 1.0, 98),
    (12, "D5", 1.0, 100), (13, "E5", 1.0, 104), (14, "G5", 1.5, 110), (15.5, "E5", 0.5, 96),
]


def build(ctx):
    groove = ctx.section("groove")
    start = groove.start_bar * ctx.beats_per_bar
    for rep, answer in enumerate((ANSWER_1, ANSWER_2)):
        offset = start + rep * 16
        for beat, pitch, length, vel in CALL + answer:
            # Slight legato: hold each note a touch past its written length.
            ctx.add(pitch, offset + beat, length * 0.95, vel + 4 * rep)
    outro = ctx.section("outro").start_bar * ctx.beats_per_bar
    ctx.add("A4", outro, 3.0, 88)
    ctx.humanise(timing=0.006, velocity=4)
