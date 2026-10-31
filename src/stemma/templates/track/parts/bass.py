"""Root notes of i-VI-III-VII, one chord per bar, in eighths."""


def build(ctx):
    degrees = [0, 5, 2, 6]
    for i, bar in enumerate(ctx.bars()):
        root = ctx.scale.degree(degrees[i % 4], octave=1)
        for eighth in range(8):
            ctx.add(root, bar + eighth / 2, 0.4, 100 if eighth % 2 == 0 else 85)
