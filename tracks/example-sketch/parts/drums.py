"""Four-on-the-floor kit with offbeat hats, backbeat snare and clap, and a fill.

GM numbers: 36 kick, 38 snare, 39 clap, 42 closed hat, 46 open hat, 49 crash.
"""

KICK, SNARE, CLAP, HAT, OPEN_HAT, CRASH = 36, 38, 39, 42, 46, 49

# 16th-note hat accents for one bar: strong on the off-beat eighths.
HAT_VEL = [60, 45, 95, 45] * 4


def build(ctx):
    last_groove_bar = ctx.bars("groove")[-1]
    for bar in ctx.bars():
        section = ctx.section_at(bar).name
        i = ctx.bar_in_section(bar)

        # Kick: every beat, except the final bar which is a single hit.
        if section == "outro" and i == 3:
            ctx.add(KICK, bar, 0.5, 118)
            ctx.add(CRASH, bar, 1, 100)
            continue
        for beat in range(4):
            ctx.add(KICK, bar + beat, 0.25, 116 if beat == 0 else 108)

        if section == "intro":
            for beat in range(4):
                ctx.add(HAT, bar + beat + 0.5, 0.1, 85)
            if i >= 2:
                for beat in (1, 3):
                    ctx.add(CLAP, bar + beat, 0.25, 90)
            continue

        if section == "groove" and i == 0:
            ctx.add(CRASH, bar, 1, 95)

        # Backbeat: snare layered with clap; a ghost snare before beat 4.
        for beat in (1, 3):
            ctx.add(SNARE, bar + beat, 0.25, 104)
            ctx.add(CLAP, bar + beat, 0.25, 84)
        if section == "groove" and bar != last_groove_bar:
            ctx.add(SNARE, bar + 2.75, 0.1, 42)

        # Hats: 16ths in the groove, eighths in the outro; open hat on the last off-beat.
        if section == "groove":
            for s in range(16):
                if s == 14 and i % 2 == 1:
                    ctx.add(OPEN_HAT, bar + 3.5, 0.25, 88)
                    continue
                ctx.add(HAT, bar + s / 4, 0.05, HAT_VEL[s])
        else:
            for beat in range(4):
                ctx.add(HAT, bar + beat + 0.5, 0.1, 80)

        # Fill: 16th snares across beats 3 and 4 of the last groove bar, crescendo.
        if bar == last_groove_bar:
            for s in range(8):
                ctx.add(SNARE, bar + 2 + s / 4, 0.1, 60 + s * 8)

    ctx.humanise(timing=0.004, velocity=4)
