"""Syncopated root-and-fifth bass on i-VI-III-VII (Am F C G), one chord per bar.

Roots are chosen in the octave nearest the previous root, kept between E1 and
A2 so the line stays out of the kick's way and does not get muddy.
"""

PROGRESSION = [0, 5, 2, 6]  # scale degrees: A, F, C, G in A minor
LOW, HIGH = 28, 45  # E1 .. A2

# (beat, interval above root in semitones, length in beats, velocity)
GROOVE = [(0, 0, 0.7, 110), (0.75, 0, 0.25, 80), (1.5, 7, 0.4, 92), (2, 0, 0.7, 104),
          (2.75, 12, 0.25, 86), (3.5, 7, 0.4, 94)]
SPARSE = [(0, 0, 1.4, 104), (1.5, 0, 0.4, 84), (3, 7, 0.9, 90)]


def nearest_root(pc_note: int, previous: int | None) -> int:
    options = [n for n in range(LOW, HIGH + 1) if n % 12 == pc_note % 12]
    if previous is None:
        return options[0]
    return min(options, key=lambda n: abs(n - previous))


def build(ctx):
    prev = None
    for bar in ctx.bars():
        section = ctx.section_at(bar).name
        i = ctx.bar_in_section(bar)
        chord_index = int(bar // ctx.beats_per_bar) % 4
        root = nearest_root(ctx.scale.degree(PROGRESSION[chord_index], octave=1), prev)
        prev = root
        if section == "intro":
            if i >= 2:
                for beat, iv, length, vel in SPARSE:
                    ctx.add(root + iv, bar + beat, length, vel)
        elif section == "groove":
            lift = 6 if i >= 4 else 0  # second time through pushes a little harder
            for beat, iv, length, vel in GROOVE:
                ctx.add(root + iv, bar + beat, length, vel + lift)
        else:  # outro: long roots, ending on a held A
            if i < 3:
                ctx.add(root, bar, 3.5, 96 - 6 * i)
            else:
                ctx.add(33, bar, 3.0, 100)
    ctx.humanise(timing=0.003, velocity=3)
