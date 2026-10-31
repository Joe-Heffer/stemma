"""``stemma`` command-line interface."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from importlib import resources
from pathlib import Path

from . import __version__
from .errors import StemmaError
from .paths import repo_root, track_dir


def _spec(slug: str):
    from .spec import load

    d = track_dir(slug)
    if not d.is_dir():
        raise StemmaError(f"no track {slug!r} under {d.parent}")
    return load(d)


def _print(obj) -> None:
    print(json.dumps(obj, indent=2))


def _step(name: str):
    print(f"== {name}", file=sys.stderr)


def cmd_new(a) -> None:
    dest = track_dir(a.slug)
    if dest.exists():
        raise StemmaError(f"{dest} already exists")
    template = resources.files("stemma").joinpath("templates/track")
    with resources.as_file(template) as src:
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
    title = a.title or a.slug.replace("-", " ").title()
    for f in (dest / "track.yaml", dest / "notes.md"):
        f.write_text(f.read_text().replace("{{title}}", title).replace("{{slug}}", a.slug))
    (dest / "midi").mkdir(exist_ok=True)
    (dest / "patches").mkdir(exist_ok=True)
    print(f"created {dest.relative_to(repo_root())}")


def cmd_validate(a) -> None:
    spec = _spec(a.slug)
    _print({"track": spec.slug, "valid": True, "bars": spec.total_bars,
            "seconds": round(spec.duration, 2),
            "sections": [{"name": s.name, "start_bar": s.start_bar, "bars": s.bars}
                         for s in spec.sections]})


def cmd_midi(a) -> None:
    from .midi import build

    _print(build(_spec(a.slug), a.part))


def cmd_render(a) -> None:
    from .render import render

    _print(render(_spec(a.slug), a.part, a.section, a.force))


def cmd_mix(a) -> None:
    from .mix import mix

    _print(mix(_spec(a.slug), a.section))


def cmd_master(a) -> None:
    from .master import master

    _print(master(_spec(a.slug), a.section))


def cmd_score(a) -> None:
    from .score import score

    _print(score(_spec(a.slug), a.section, a.part, a.format))


def cmd_analyse(a) -> None:
    from .analyse import analyse, analyse_file

    if a.file:
        _print(analyse_file(Path(a.file)))
        return
    if not a.slug:
        raise StemmaError("give a track slug or --file")
    _print(analyse(_spec(a.slug), a.section, a.stem))


def cmd_all(a) -> None:
    from .analyse import analyse
    from .master import master
    from .midi import build
    from .mix import mix
    from .render import render

    spec = _spec(a.slug)
    t0 = time.time()
    _step("midi")
    midi_report = build(spec)
    _step("render")
    render_report = render(spec, None, a.section, a.force)
    _step("mix")
    mix_report = mix(spec, a.section)
    _step("master")
    master_report = master(spec, a.section)
    _step("analyse")
    report = analyse(spec, a.section)
    _print({"midi": midi_report, "render": render_report, "mix": mix_report,
            "master": master_report, "analysis": report,
            "elapsed_s": round(time.time() - t0, 1)})


def cmd_doctor(a) -> None:
    from . import sounds
    from .fx import pedalboard_available
    from .render.external import TOOLS

    tools = {name: shutil.which(exe) for name, exe in TOOLS.items()}
    tools["ffmpeg"] = shutil.which("ffmpeg")
    tools["sox"] = shutil.which("sox")
    tools["lilypond"] = shutil.which("lilypond")
    from importlib.metadata import version
    found = {}
    for name in sounds.manifest():
        try:
            found[name] = str(sounds.resolve(name))
        except StemmaError:
            found[name] = None
    _print({"stemma": __version__, "root": str(repo_root()), "tools": tools,
            "pedalboard": pedalboard_available(), "music21": version("music21"),
            "sounds": found})


def cmd_sounds(a) -> None:
    from . import sounds

    if a.action == "list":
        _print(sounds.manifest())
    else:
        for name in a.names or list(sounds.manifest()):
            print(sounds.fetch(name))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stemma", description=__doc__)
    p.add_argument("--version", action="version", version=f"stemma {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, fn, help_, slug=True):
        s = sub.add_parser(name, help=help_)
        if slug:
            s.add_argument("slug")
        s.set_defaults(func=fn)
        return s

    s = add("new", cmd_new, "scaffold a track from the template")
    s.add_argument("--title")
    add("validate", cmd_validate, "validate track.yaml against the schema")
    s = add("midi", cmd_midi, "build MIDI parts from generators")
    s.add_argument("--part")
    s = add("render", cmd_render, "render parts to WAV stems")
    s.add_argument("--part")
    s.add_argument("--section")
    s.add_argument("--force", action="store_true", help="ignore the render cache")
    for name, fn, h in (("mix", cmd_mix, "mix stems to a stereo mixdown"),
                        ("master", cmd_master, "loudness-normalise and limit the mix")):
        s = add(name, fn, h)
        s.add_argument("--section")
    s = add("score", cmd_score, "write sheet music: MusicXML, LilyPond and PDF")
    s.add_argument("--part")
    s.add_argument("--section")
    s.add_argument("--format", nargs="+", choices=["musicxml", "ly", "pdf"],
                   help="override score.formats from the spec")
    s = sub.add_parser("analyse", aliases=["analyze"], help="print analysis JSON")
    s.add_argument("slug", nargs="?")
    s.add_argument("--section")
    s.add_argument("--stem", help="analyse one stem only")
    s.add_argument("--file", help="analyse any audio file")
    s.set_defaults(func=cmd_analyse)
    s = add("all", cmd_all, "midi, render, mix, master and analyse")
    s.add_argument("--section")
    s.add_argument("--force", action="store_true")
    add("doctor", cmd_doctor, "report installed tools and sounds", slug=False)
    s = add("sounds", cmd_sounds, "list or fetch shared sounds", slug=False)
    s.add_argument("action", choices=["list", "fetch"])
    s.add_argument("names", nargs="*")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except StemmaError as e:
        print(f"stemma: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
