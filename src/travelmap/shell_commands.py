"""Build literal, copyable commands for supported terminal shells."""

import shlex
import sys
from enum import StrEnum
from pathlib import Path


class CommandFormatError(ValueError):
    """Raised when an argument cannot be represented safely in a displayed command."""


class ShellKind(StrEnum):
    """Terminal grammar used for a displayed command."""

    POSIX = "posix"
    POWERSHELL = "powershell"


def shell_for_platform(platform: str) -> ShellKind:
    """Choose the documented default shell family without inspecting shell variables."""

    return ShellKind.POWERSHELL if platform == "nt" else ShellKind.POSIX


def format_command(executable: Path, args: tuple[str, ...], shell: ShellKind) -> str:
    """Quote each fixed argument for one shell; never execute the displayed command."""

    tokens = (str(executable), *args)
    if any(_contains_command_control(token) for token in tokens):
        raise CommandFormatError("a command argument contains an unsupported control character")
    if shell is ShellKind.POSIX:
        return " ".join(shlex.quote(token) for token in tokens)
    if shell is ShellKind.POWERSHELL:
        executable_token = _powershell_expression(tokens[0])
        arguments = " ".join(_powershell_expression(token) for token in tokens[1:])
        suffix = "" if not arguments else f" {arguments}"
        return f"& {executable_token}{suffix}"
    raise CommandFormatError(f"unsupported shell: {shell!r}")


def travelmap_command(args: tuple[str, ...], shell: ShellKind) -> str:
    """Keep the active environment, including source-only runs, in follow-up commands."""
    executable = Path(sys.executable).absolute()
    command = format_command(executable, args, shell)
    # Source runs need an absolute import path when resumed from a different directory.
    source = Path(__file__).absolute().parents[1]
    if source.name == "src" and (source.parent / "pyproject.toml").is_file():
        if _contains_command_control(str(source)):
            raise CommandFormatError("the source import path contains a control character")
        if shell is ShellKind.POSIX:
            return f"PYTHONPATH={shlex.quote(str(source))} {command}"
        return format_command(
            executable,
            (
                "-c",
                "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); "
                "runpy.run_module('travelmap',run_name='__main__')",
                str(source),
                *args[2:],
            ),
            shell,
        )
    return command


def _contains_command_control(value: str) -> bool:
    return any(character in value for character in ("\x00", "\r", "\n"))


def _powershell_expression(value: str) -> str:
    """Encode literal PowerShell arguments, avoiding smart quote delimiters in source text."""

    pieces: list[str] = []
    ordinary: list[str] = []

    def flush_ordinary() -> None:
        if ordinary:
            pieces.append("'" + "".join(ordinary).replace("'", "''") + "'")
            ordinary.clear()

    smart_quotes = {
        "\u2018": "[char]0x2018",
        "\u2019": "[char]0x2019",
        "\u201c": "[char]0x201C",
        "\u201d": "[char]0x201D",
    }
    for character in value:
        character_expression = smart_quotes.get(character)
        if character_expression is None:
            ordinary.append(character)
        else:
            flush_ordinary()
            pieces.append(character_expression)
    flush_ordinary()
    if not pieces:
        return "''"
    return pieces[0] if len(pieces) == 1 else "(" + " + ".join(pieces) + ")"
