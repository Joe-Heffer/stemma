"""Basic backbeat: kick on 1 and 3, snare on 2 and 4, eighth-note hats."""

KICK, SNARE, HAT = 36, 38, 42


def build(ctx):
    for bar in ctx.bars():
        for beat in (0, 2):
            ctx.add(KICK, bar + beat, 0.25, 110)
        for beat in (1, 3):
            ctx.add(SNARE, bar + beat, 0.25, 100)
        for eighth in range(8):
            ctx.add(HAT, bar + eighth / 2, 0.1, 80 if eighth % 2 else 95)
    ctx.humanise(timing=0.005, velocity=5)
