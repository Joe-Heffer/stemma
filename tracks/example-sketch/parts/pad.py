"""Sustained pad chords with close voice leading (common tones held).

Am (A3 C4 E4) -> F (A3 C4 F4) -> C (G3 C4 E4) -> G (G3 B3 D4)
"""

VOICINGS = [["A3", "C4", "E4"], ["A3", "C4", "F4"], ["G3", "C4", "E4"], ["G3", "B3", "D4"]]


def build(ctx):
    for bar in ctx.bars("groove", "outro"):
        section = ctx.section_at(bar).name
        i = ctx.bar_in_section(bar)
        if section == "outro" and i == 3:
            ctx.chord(["A3", "C4", "E4"], bar, 4, 70)
            continue
        chord = VOICINGS[int(bar // ctx.beats_per_bar) % 4]
        vel = 64 if section == "groove" and i < 4 else 72
        ctx.chord(chord, bar, ctx.beats_per_bar, vel)
