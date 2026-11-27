"""Guided terminal commands for verifying an install and preparing local workspaces."""

import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Iterable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, NoReturn

import click
import typer
from typer.core import TyperCommand, TyperGroup

from travelmap import __version__
from travelmap.guidance import Step, run_guidance, select_step
from travelmap.shell_commands import ShellKind, shell_for_platform, travelmap_command
from travelmap.terminal import (
    MessageKind,
    Navigation,
    choose_number,
    emit,
    inert_text,
    screen,
    set_color,
    set_screen_output,
    show_choice_prompt,
    styles_enabled,
    text_input,
    wait_for_reading,
)
from travelmap.ui_text import text as ui_text
from travelmap.workspace import (
    WorkspaceError,
    WorkspaceInspection,
    WorkspaceMarkerError,
    WorkspaceSetupResult,
    default_workspace_path,
    ensure_workspace,
    inert_path,
    inspect_workspace,
    load_recent_workspaces,
    remember_recent_workspace,
    resolve_workspace_path,
)

# Recent Typer versions vendor Click and expose a separate public exception hierarchy.
_TYPER_CLI_ERROR: type[Exception] = getattr(typer, "TyperException", click.ClickException)


class _HelpFormatter(click.HelpFormatter):
    def write_dl(
        self, rows: Iterable[tuple[str, str]], col_max: int = 30, col_spacing: int = 2
    ) -> None:
        if self.width >= 60:
            super().write_dl(rows, col_max, col_spacing)
            return
        # Stacking leaves room for descriptions and long enum metavars on small screens.
        for label, description in rows:
            self.write_text(label)
            if description:
                with self.indentation():
                    self.write_text(description)
            self.write_paragraph()


def _plain_help(command: TyperCommand | TyperGroup, ctx: Any) -> str:
    # Typer supports external and vendored Click types. Their formatter protocol is
    # compatible, but their nominal types differ across the supported dependency range.
    width = max(1, min(ctx.make_formatter().width, shutil.get_terminal_size().columns - 1))
    formatter: Any = _HelpFormatter(width=width)
    command.format_help(ctx, formatter)
    return str(formatter.getvalue()).rstrip("\n")


class _HelpCommand(TyperCommand):
    def get_help(self, ctx: Any) -> str:
        return _plain_help(self, ctx)


class _HelpGroup(TyperGroup):
    def get_help(self, ctx: Any) -> str:
        return _plain_help(self, ctx)


app = typer.Typer(
    name="travelmap",
    help="Generate an editable SVG travel poster from validated local trip/map inputs.",
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=False,
    cls=_HelpGroup,
    rich_markup_mode=None,
)


_CLI_ROOT_VERSION_FLAG_OPTION = typer.Option(
    False,
    "--version",
    help="Show the installed version without inspecting or changing a workspace.",
)
_CLI_ROOT_NO_COLOR_OPTION = typer.Option(
    False,
    "--no-color",
    "--monochrome",
    help=ui_text("Use plain text without color or highlighting."),
)
_RUN_PATH_OPTION = typer.Option(None, "--path", help="Folder for this trip's workspace.")
_RUN_START_AT_OPTION = typer.Option(
    None, "--start-at", help="Starting step; omit to choose from the step menu."
)
_RUN_SHELL_OPTION = typer.Option(None, "--shell", help="Shell for resume commands.")
_OPEN_OUTPUT_FILE_OPTION = typer.Option(
    ..., "--file", help="Existing SVG to open in your default viewer."
)
_WORKSPACE_PATH_OPTION = typer.Option(
    None, "--path", help="Workspace folder. A relative path is based on the current folder."
)
_WORKSPACE_SHELL_OPTION = typer.Option(
    None, "--shell", help="Shell for copyable commands: posix or powershell."
)
_WORKSPACE_INSPECT_ONLY_OPTION = typer.Option(
    False, "--inspect", help="Read-only workspace inspection; never create or repair files."
)
_WORKSPACE_NON_INTERACTIVE_OPTION = typer.Option(
    False, "--non-interactive", help="Use only the explicit --path; do not show prompts."
)
_WORKSPACE_ADOPT_EXISTING_OPTION = typer.Option(
    False,
    "--adopt-existing",
    help="Explicitly allow a compatible unmarked folder to become a workspace.",
)


@app.callback()
def cli_root(
    ctx: typer.Context,
    version_flag: bool = _CLI_ROOT_VERSION_FLAG_OPTION,
    no_color: bool = _CLI_ROOT_NO_COLOR_OPTION,
) -> None:
    """Print the version when requested; otherwise leave the selected command in charge."""

    set_screen_output(False)
    ctx.call_on_close(lambda: set_screen_output(False))
    set_color(not no_color)
    if no_color or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        # App roles choose their own colors; Click prompts may retain monochrome emphasis.
        ctx.color = styles_enabled()
    if version_flag:
        emit(f"TravelMap {installed_version()}")
        raise typer.Exit(code=0)
    if ctx.invoked_subcommand is None:
        _run_guided(None, None, None)


@app.command(cls=_HelpCommand)
def run(
    path: Path | None = _RUN_PATH_OPTION,
    start_at: Step | None = _RUN_START_AT_OPTION,
    shell: ShellKind | None = _RUN_SHELL_OPTION,
) -> None:
    """Follow the complete guided workflow from local inputs to SVG export."""

    _run_guided(path, shell, start_at)


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _run_guided(path: Path | None, shell: ShellKind | None, start_at: Step | None) -> None:
    if not _is_interactive():
        _fail(
            "The guided run needs an interactive terminal for step choices and done/recheck "
            "input. For scripted workspace creation, use workspace --path PATH --non-interactive.",
            code=2,
        )
    set_screen_output(True)
    selected_shell = shell or shell_for_platform(os.name)
    emit("Welcome to TravelMap's guided poster workflow.")
    emit(
        "I will explain each task and wait while you complete it. Your files stay local. "
        "A routing key is requested only if you explicitly choose to acquire missing routes."
    )
    step: Step | None
    if start_at is not None:
        step = start_at
    elif path is not None:
        from travelmap.flow import default_stage

        try:
            step = Step(default_stage(resolve_workspace_path(path)))
        except (ValueError, OSError):
            step = Step.ITINERARY
    else:
        step = select_step()
    if step is None:
        emit("Paused. No workspace was selected or changed.")
        return
    root = (
        _run_interactive(shell=selected_shell)
        if path is None
        else _choose_root(
            resolve_workspace_path(path),
            shell=selected_shell,
            initially_adopt=False,
            interactive=True,
        )
    )
    while root is not None:
        if not run_guidance(root, step, selected_shell):
            return
        root = _run_interactive(shell=selected_shell)
        step = Step.ITINERARY


@app.command("open-output", cls=_HelpCommand)
def open_output(
    file: Path = _OPEN_OUTPUT_FILE_OPTION,
) -> None:
    """Open one existing local SVG using literal process arguments."""
    if not file.is_file() or file.suffix.lower() != ".svg":
        _fail("Choose an existing .svg output file.", code=2)
    path = file.resolve()
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen(
                [opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
    except OSError:
        _fail(
            "No desktop viewer is available. Open this SVG in a browser, Inkscape or Illustrator: "
            + str(path),
            code=2,
        )


@app.command(cls=_HelpCommand)
def doctor() -> None:
    """Check the installed command and Python runtime without touching local data."""

    emit("TravelMap installation check", kind=MessageKind.HEADING)
    emit(f"Python: {platform.python_version()} ({platform.python_implementation()})")
    if not (3, 12) <= sys.version_info[:2] < (3, 15):
        emit("Supported Python versions are 3.12, 3.13 and 3.14.", err=True)
        raise typer.Exit(code=1)
    emit(f"TravelMap: {installed_version()}")
    emit("Workspace commands are available.", kind=MessageKind.SUCCESS)
    emit("This check used no routing key, external service or workspace files.")


@app.command(cls=_HelpCommand)
def workspace(
    path: Path | None = _WORKSPACE_PATH_OPTION,
    shell: ShellKind | None = _WORKSPACE_SHELL_OPTION,
    inspect_only: bool = _WORKSPACE_INSPECT_ONLY_OPTION,
    non_interactive: bool = _WORKSPACE_NON_INTERACTIVE_OPTION,
    adopt_existing: bool = _WORKSPACE_ADOPT_EXISTING_OPTION,
) -> None:
    """Choose, inspect or prepare one local TravelMap workspace."""

    if inspect_only and adopt_existing:
        _fail("--inspect is read-only and cannot be combined with --adopt-existing", code=2)
    selected_shell = shell or shell_for_platform(os.name)
    if non_interactive or not _is_interactive():
        if path is None:
            _fail(
                "workspace needs a folder path without terminal input; "
                "rerun with --path PATH or use an interactive terminal",
                code=2,
            )
        resolved = resolve_workspace_path(path)
        _run_without_prompts(
            resolved,
            shell=selected_shell,
            inspect_only=inspect_only,
            adopt_existing=adopt_existing,
        )
        return
    if inspect_only:
        if path is None:
            _fail("read-only inspection needs an explicit --path PATH", code=2)
        _print_inspection(inspect_workspace(resolve_workspace_path(path)))
        return
    set_screen_output(True)
    if path is None:
        root = _run_interactive(shell=selected_shell)
    else:
        root = _choose_root(
            resolve_workspace_path(path),
            shell=selected_shell,
            initially_adopt=adopt_existing,
            interactive=True,
        )
    while root is not None:
        if not run_guidance(root, Step.ITINERARY, selected_shell):
            return
        root = _run_interactive(shell=selected_shell)


def main() -> None:
    """Run Typer without tracebacks for expected CLI and filesystem failures."""

    try:
        exit_code = app(standalone_mode=False)
        # Click returns handled Exit codes instead of raising when standalone mode is off.
        if isinstance(exit_code, int):
            raise SystemExit(exit_code)
    except typer.Exit as exc:
        raise SystemExit(exc.exit_code) from None
    except KeyboardInterrupt:
        emit("Paused. Validated workspace files are kept.")
        raise SystemExit(130) from None
    except typer.Abort:
        emit("Paused. No workspace changes were discarded.")
        raise SystemExit(130) from None
    except WorkspaceError as exc:
        emit(inert_text(str(exc)), err=True)
        raise SystemExit(1) from None
    except OSError as exc:
        emit(f"Workspace operation failed: {inert_text(str(exc))}", err=True)
        raise SystemExit(1) from None
    except (click.ClickException, _TYPER_CLI_ERROR) as exc:
        emit(inert_text(str(exc)), err=True)
        raise SystemExit(2) from None


def installed_version() -> str:
    """Prefer installed metadata and support direct source checkout use."""

    try:
        return version("travelmap")
    except PackageNotFoundError:
        return __version__


def _run_without_prompts(
    root: Path,
    *,
    shell: ShellKind,
    inspect_only: bool,
    adopt_existing: bool,
) -> None:
    inspection = inspect_workspace(root)
    if inspect_only:
        _print_inspection(inspection)
        if inspection.conflict:
            raise typer.Exit(code=1)
        return
    if inspection.conflict:
        _fail(inspection.conflict, code=1)
    if inspection.marker_status == "invalid":
        raise WorkspaceMarkerError(
            f"workspace marker is not supported: {inert_path(inspection.paths.manifest_file)}"
        )
    has_content = (
        bool(inspection.existing_directories)
        or bool(inspection.unrelated_root_entries)
        or any(count > 0 for _, count in inspection.candidate_counts)
    )
    if inspection.marker_status == "missing" and has_content and not adopt_existing:
        _fail(
            "workspace already contains files; inspect it first, then rerun with "
            "--adopt-existing if you want to add TravelMap folders",
            code=2,
        )
    result = ensure_workspace(root, adopt_existing=adopt_existing)
    remember_recent_workspace(result.paths.root)
    _print_ready(result, shell)


def _run_interactive(*, shell: ShellKind) -> Path | None:
    while True:
        try:
            return _workspace_interactive(shell=shell)
        except Navigation as nav:
            if nav.action == "pause":
                emit("Exited. No new workspace was selected.")
                return None


def _workspace_interactive(*, shell: ShellKind) -> Path | None:
    default_path = default_workspace_path().resolve()
    while True:
        screen(1)
        recent = load_recent_workspaces()
        choices: tuple[str, ...]
        if recent:
            emit("Recent folders:")
            for index, candidate in enumerate(recent, start=1):
                emit(f"{index}. {inert_path(candidate)}")
            choices = (
                "Use most recent folder",
                "Choose from recent folders",
                "Choose another folder",
                "Use default folder",
                "Help with workspaces",
                "Pause",
            )
            default = 1
        else:
            emit(f"Suggested folder: {inert_path(default_path)}")
            choices = (
                "Use the suggested folder",
                "Choose another folder",
                "Help with workspaces",
                "Pause",
            )
            default = 1
        try:
            choice = _prompt_choice(
                "Choose a recent workspace or another folder."
                if recent
                else "Use this folder, choose another, or get help.",
                choices,
                default=default,
            )
        except ValueError as exc:
            emit(inert_text(str(exc)), err=True)
            continue
        if recent and choice == 1:
            return _choose_root(recent[0], shell=shell, initially_adopt=False, interactive=True)
        if recent and choice == 2:
            selected = _prompt_choice(
                "Choose a recent folder, or go back.",
                tuple(inert_path(candidate) for candidate in recent) + ("Back",),
                default=1,
            )
            if selected <= len(recent):
                return _choose_root(
                    recent[selected - 1], shell=shell, initially_adopt=False, interactive=True
                )
            continue
        choose_another = 3 if recent else 2
        help_choice = 5 if recent else 3
        pause_choice = 6 if recent else 4
        if choice == pause_choice:
            emit("No workspace was selected; no folder or resume command was created.")
        elif choice == help_choice:
            _workspace_help()
            wait_for_reading()
        elif choice == choose_another:
            candidate = _prompt_path()
            return _choose_root(candidate, shell=shell, initially_adopt=False, interactive=True)
        else:
            candidate = default_path
            return _choose_root(candidate, shell=shell, initially_adopt=False, interactive=True)
        if choice == pause_choice:
            return None


def _prompt_path() -> Path:
    emit("Choose a folder to open, or a new folder to create. A new location will be confirmed.")
    while True:
        answer = text_input("Workspace folder path")
        try:
            return resolve_workspace_path(answer)
        except WorkspaceError as exc:
            emit(inert_text(str(exc)), err=True)


def _choose_root(
    root: Path,
    *,
    shell: ShellKind,
    initially_adopt: bool,
    interactive: bool = False,
) -> Path | None:
    try:
        return _choose_root_once(
            root,
            shell=shell,
            initially_adopt=initially_adopt,
            interactive=interactive,
        )
    except WorkspaceError as exc:
        if not interactive:
            raise
        emit(inert_text(str(exc)), err=True)
        choice = _prompt_choice(
            "What would you like to do?",
            ("Choose another folder", "Retry this folder", "Help", "Pause"),
            default=1,
        )
        if choice == 1:
            return _run_interactive(shell=shell)
        elif choice == 2:
            return _choose_root(
                root, shell=shell, initially_adopt=initially_adopt, interactive=True
            )
        elif choice == 3:
            _workspace_help()
            return _choose_root(
                root, shell=shell, initially_adopt=initially_adopt, interactive=True
            )
        else:
            emit("Paused. Any completed folders and your existing files were kept.")
            _print_resume(root, shell)
            return None


def _choose_root_once(
    root: Path,
    *,
    shell: ShellKind,
    initially_adopt: bool,
    interactive: bool,
) -> Path | None:
    if root.is_file():
        raise WorkspaceError(
            f"The selected workspace path is a file: {inert_path(root)}. "
            "Choose a folder rather than a file."
        )
    if interactive and not root.exists():
        emit(f"New workspace folder: {inert_path(root)}")
        choice = _prompt_choice(
            "Create TravelMap folders at this location?",
            ("Create this workspace", "Choose another folder", "Pause"),
            default=2,
        )
        if choice == 2:
            return _run_interactive(shell=shell)
        if choice == 3:
            emit("Paused. No folder was created.")
            return None
    inspection = inspect_workspace(root)
    if inspection.conflict:
        raise WorkspaceError(inspection.conflict)
    adoption = initially_adopt
    has_content = (
        bool(inspection.existing_directories)
        or bool(inspection.unrelated_root_entries)
        or any(count > 0 for _, count in inspection.candidate_counts)
    )
    if inspection.marker_status == "missing" and has_content and not adoption:
        emit(f"This folder already has content: {inert_path(root)}")
        _print_inspection(inspection)
        try:
            choice = _prompt_choice(
                "Add TravelMap folders while keeping these files?",
                (
                    "Choose another folder",
                    "Adopt this folder and keep its files",
                    "Help",
                    "Pause",
                ),
                default=1,
            )
        except ValueError as exc:
            emit(inert_text(str(exc)), err=True)
            return _choose_root(root, shell=shell, initially_adopt=False, interactive=interactive)
        if choice == 4:
            emit("Paused. No existing files were changed.")
            _print_resume(root, shell)
            return None
        if choice == 3:
            _workspace_help()
            return _choose_root(root, shell=shell, initially_adopt=False, interactive=interactive)
        if choice == 1:
            return _run_interactive(shell=shell)
        adoption = True
    result = ensure_workspace(root, adopt_existing=adoption)
    remember_recent_workspace(result.paths.root)
    _print_config_migration(result)
    emit("Workspace ready.", kind=MessageKind.SUCCESS)
    return result.paths.root


def _prompt_choice(question: str, choices: tuple[str, ...], *, default: int | None) -> int:
    cancel_index = (
        choices.index("Back")
        if "Back" in choices
        else (choices.index("Pause") if "Pause" in choices else None)
    )
    labels = tuple("Save and exit" if label == "Pause" else label for label in choices)
    while True:
        answer = show_choice_prompt(
            question,
            labels,
            default=default,
            cancel_index=cancel_index,
            cancel_label="Back" if "Back" in choices else "Save and exit",
            pause_index=choices.index("Pause") if "Pause" in choices else None,
        )
        try:
            return choose_number(answer, len(choices), default=default)
        except ValueError as exc:
            emit(inert_text(str(exc)), err=True)


def _workspace_help() -> None:
    emit("A workspace is a folder where TravelMap keeps its files together.")
    emit("Choose a folder you can write to, preferably outside the downloaded program folder.")
    emit()
    emit("Your existing files are kept. Setup adds TravelMap folders and workspace metadata.")
    emit(
        "Keeping the workspace outside the program folder means replacing the downloaded code "
        "later will not remove your trip files."
    )
    emit()
    emit(
        "Use a location with space for your regional map downloads. You can return to this "
        "folder for another session."
    )


def _print_inspection(inspection: WorkspaceInspection) -> None:
    emit(f"Workspace: {inert_path(inspection.paths.root)}")
    if inspection.is_ready:
        emit("Workspace status: ready")
    elif inspection.conflict:
        emit(
            f"Workspace status: needs repair: {inert_text(inspection.conflict)}",
            kind=MessageKind.WARNING,
        )
    elif inspection.marker_status == "missing":
        emit("Workspace status: unmarked; this read-only check has not adopted it")
    elif inspection.missing_directories:
        missing = ", ".join(inspection.missing_directories)
        emit(
            "Workspace status: incomplete; missing "
            + missing
            + ". Use workspace setup to create the missing folders.",
            kind=MessageKind.WARNING,
        )
    for directory, checked in inspection.scanned_entries:
        count = dict(inspection.candidate_counts).get(directory, 0)
        emit(f"{directory}: checked {checked} entries; found {count} matching files")
        for name in dict(inspection.candidate_examples).get(directory, ()):
            emit(f"  {inert_text(name)}")
        if directory in inspection.truncated_directories:
            emit(
                f"{directory}: scan incomplete; displayed matches are a lower bound. "
                "Use a smaller folder and inspect again.",
                kind=MessageKind.WARNING,
            )
    if inspection.unrelated_root_entries:
        entries = ", ".join(inert_text(name) for name in inspection.unrelated_root_entries)
        emit("Other existing files/folders: " + entries)


def _print_config_migration(setup: WorkspaceSetupResult) -> None:
    if setup.config_migration is not None:
        emit(
            "config.toml is now authoritative. Previous CLI settings were preserved in "
            + str(setup.config_migration)
            + ". Review that file and copy desired values into config.toml.",
            kind=MessageKind.WARNING,
        )


def _print_ready(setup: WorkspaceSetupResult, shell: ShellKind) -> None:
    paths = setup.paths
    _print_config_migration(setup)
    emit("Workspace ready.", kind=MessageKind.SUCCESS)
    emit(f"Workspace: {inert_path(paths.root)}")
    emit("Created: " + (", ".join(setup.created_directories) or "none"))
    emit("Reused: " + (", ".join(setup.reused_directories) or "none"))
    emit()
    emit("Put files here:")
    for directory, explanation in (
        (paths.input_dir, "KML itineraries"),
        (paths.map_data_dir, "map-data downloads"),
        (paths.manual_routes_dir, "your own GeoJSON route files"),
        (paths.cache_dir, "reusable data created by TravelMap"),
        (paths.output_dir, "finished SVG posters"),
    ):
        emit(f"  {explanation}: {inert_path(directory)}")
    emit(
        "The interactive guide explains what to copy and download, then waits for you. "
        "You can also return later using the command below."
    )
    _print_resume(paths.root, shell)


def _print_resume(root: Path, shell: ShellKind) -> None:
    args = ("-m", "travelmap", "run", "--path", str(root), "--shell", shell.value)
    try:
        command = travelmap_command(args, shell)
    except ValueError:
        emit("Resume: run the workspace command again and choose this folder.")
        return
    emit()
    emit(f"Resume in {shell.value}: {command}")


def _fail(message: str, *, code: int) -> NoReturn:
    emit(inert_text(message), err=True)
    raise typer.Exit(code=code)
