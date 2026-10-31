"""The agent skills in .claude/skills/ must parse and only use real CLI commands."""

import argparse
import re
from pathlib import Path

import pytest
import yaml

from stemma.cli import build_parser

SKILLS = Path(__file__).resolve().parent.parent / ".claude" / "skills"
SKILL_FILES = sorted(SKILLS.glob("*/SKILL.md"))
# `uv run stemma <command> …` or `` `stemma <command> …` ``, up to the end of the line
# or the closing backtick. Prose such as "stemma adds" is not matched.
COMMAND_RE = re.compile(r"(?:uv run |`)stemma (?P<cmd>[a-z]+)\b(?P<rest>[^\n`|]*)")


def subcommands() -> dict[str, set[str]]:
    """Each subcommand of the CLI and the long options it accepts."""
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return {name: {opt for action in p._actions for opt in action.option_strings
                   if opt.startswith("--")}
            for name, p in sub.choices.items()}


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    return yaml.safe_load(text.split("---\n", 2)[1])


def test_skills_exist():
    assert SKILL_FILES, "no skills found under .claude/skills/"


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_frontmatter(path):
    meta = frontmatter(path)
    assert meta["name"] == path.parent.name
    assert len(meta["description"]) > 40


@pytest.mark.parametrize("path", sorted(SKILLS.glob("*/*.md")), ids=lambda p: p.parent.name)
def test_commands_and_flags_exist(path):
    commands = subcommands()
    for m in COMMAND_RE.finditer(path.read_text()):
        cmd = m["cmd"]
        assert cmd in commands, f"{path.name}: unknown command `stemma {cmd}`"
        for flag in re.findall(r"(?<![\w-])--[a-z][a-z-]*", m["rest"]):
            assert flag in commands[cmd] | {"--help"}, (
                f"{path.name}: `stemma {cmd}` has no option {flag}")


@pytest.mark.parametrize("path", sorted(SKILLS.glob("*/*.md")), ids=lambda p: p.parent.name)
def test_links_resolve(path):
    for target in re.findall(r"\]\(([^)#:]+)\)", path.read_text()):
        assert (path.parent / target).is_file(), f"{path.name}: broken link {target}"
