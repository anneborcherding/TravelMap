"""Bounded terminal messages with explicit roles and an optional visual hierarchy."""

import itertools
import os
import shutil
import sys
import threading
import time
import unicodedata
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import click
import typer

from travelmap.reporting import Reporter, ReportKind, progress_label
from travelmap.ui_text import text


def inert_text(value: str) -> str:
    """Escape controls and direction overrides so imported text cannot alter the display."""

    result: list[str] = []
    for character in value:
        codepoint = ord(character)
        category = unicodedata.category(character)
        if category in {"Cc", "Cf", "Cs", "Co", "Cn"}:
            result.append(f"\\u{codepoint:04x}")
        else:
            result.append(character)
    return "".join(result)


STEP_NAMES = (
    text("Workspace"),
    text("Your itinerary"),
    text("Map data"),
    text("Routes"),
    text("Own routes"),
    text("Poster design"),
    text("Export"),
)
BANNER = r"""       /\        /\
      /  \  /\  /  \
     /    \/  \/    \
   o . . o . . o . . X
        TRAVELMAP"""


def interactive_display() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("TERM") != "dumb"


class MessageKind(StrEnum):
    INFO = "info"
    RESULT = "result"
    ACTIVITY = "activity"
    SUCCESS = "success"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"
    QUESTION = "question"
    HEADING = "heading"
    HINT = "hint"
    SELECTED = "selected"
    BRAND = "brand"


@dataclass(frozen=True)
class Message:
    value: str
    kind: MessageKind = MessageKind.INFO
    suffix: str = ""


_workspace = ""
_intro_pending = False
_step: int | None = None
_pending: list[Message] = []
_body_rows = 0
_color_enabled = True
_status_width = 0
_screen_output = False
_status_lock = threading.RLock()


@dataclass
class _WorkingState:
    started: float = field(default_factory=time.monotonic)
    frames: Iterator[str] = field(default_factory=lambda: itertools.cycle("|/-\\"))
    message: str | None = None
    stopped: threading.Event = field(default_factory=threading.Event)


_working: _WorkingState | None = None


def _working_label(state: _WorkingState) -> str:
    return (
        next(state.frames)
        + " "
        + progress_label(
            state.message or "",
            time.monotonic() - state.started,
            show_pause_hint=False,
            compact=shutil.get_terminal_size((80, 24)).columns < 60,
        )
    )


@contextmanager
def working() -> Iterator[None]:
    """Animate reported activity between callbacks, stopping before returning to the caller."""
    global _working
    if _working is not None or not interactive_display():
        yield
        return
    state = _WorkingState()
    _working = state

    def heartbeat() -> None:
        while not state.stopped.wait(0.25):
            with _status_lock:
                if not interactive_display():
                    state.message = None
                elif state.message is not None:
                    _draw_activity(_working_label(state))

    thread = threading.Thread(target=heartbeat, name="travelmap-progress", daemon=True)
    thread.start()
    try:
        yield
    finally:
        state.stopped.set()
        thread.join()
        clear_status()
        _working = None


def set_color(enabled: bool) -> None:
    global _color_enabled
    _color_enabled = enabled


def colors_enabled(*, err: bool = False) -> bool:
    return _color_enabled and not os.environ.get("NO_COLOR") and styles_enabled(err=err)


def styles_enabled(*, err: bool = False) -> bool:
    """Monochrome retains emphasis, but logs and dumb terminals never receive SGR codes."""
    stream = sys.stderr if err else sys.stdout
    return os.environ.get("TERM") != "dumb" and stream.isatty()


def _message_stderr(kind: MessageKind, *, err: bool = False) -> bool:
    """Live screens use stdout; plain/direct diagnostics use stderr."""
    return not (_screen_output and interactive_display()) and (
        err or kind in (MessageKind.WARNING, MessageKind.ERROR)
    )


def style_text(value: str, kind: MessageKind = MessageKind.INFO, *, err: bool = False) -> str:
    """Style already bounded, inert content; redirected output stays plain."""
    colored = colors_enabled(err=err)
    emphasized = kind in (
        MessageKind.QUESTION,
        MessageKind.HEADING,
        MessageKind.SELECTED,
        MessageKind.ERROR,
    )
    if not colored and (not emphasized or not styles_enabled(err=err)):
        return value
    colors = {
        MessageKind.ACTIVITY: "bright_black",
        MessageKind.HINT: "bright_black",
        MessageKind.NOTICE: "bright_black",
        MessageKind.BRAND: "cyan",
        MessageKind.QUESTION: "cyan",
        MessageKind.SUCCESS: "green",
        MessageKind.WARNING: "yellow",
        MessageKind.ERROR: "red",
    }
    return (
        click.style(
            value,
            fg=colors.get(kind) if colored else None,
            bold=True if emphasized else None,
            # Bold and dim share ANSI reset 22; dim=False would cancel bold.
            dim=True
            if colored and kind in (MessageKind.ACTIVITY, MessageKind.HINT, MessageKind.NOTICE)
            else None,
            reverse=True if kind is MessageKind.SELECTED else None,
        )
        if kind is not MessageKind.INFO
        else value
    )


def _print_line(
    value: str, kind: MessageKind = MessageKind.INFO, *, nl: bool = True, err: bool = False
) -> None:
    err = _message_stderr(kind, err=err)
    typer.echo(style_text(value, kind, err=err), nl=nl, err=err, color=styles_enabled(err=err))


def _message_text(message: Message) -> str:
    prefixes = {
        MessageKind.ACTIVITY: "  · ",
        MessageKind.SUCCESS: "Done: ",
        MessageKind.WARNING: "! ",
        MessageKind.ERROR: "Error: ",
    }
    return text(prefixes.get(message.kind, "")) + inert_text(text(message.value))


def _message_lines(messages: Sequence[Message], width: int) -> list[tuple[str, MessageKind]]:
    return [
        (part, message.kind)
        for message in messages
        for part in _wrap(_message_text(message), width)
    ]


def _overview(messages: Sequence[Message]) -> list[Message]:
    """Prioritize actionable feedback in bounded menus; details retain emission order."""
    important = [m for m in messages if m.kind in (MessageKind.ERROR, MessageKind.WARNING)]
    other = [
        m
        for m in messages
        if m.kind not in (MessageKind.ERROR, MessageKind.WARNING, MessageKind.ACTIVITY)
    ]
    return important + other


def clear_status() -> None:
    """Erase transient work without retaining it in the screen history."""
    global _status_width
    with _status_lock:
        if _working is not None:
            _working.message = None
        if _status_width:
            if interactive_display():
                click.echo("\r" + " " * _status_width + "\r", nl=False)
            _status_width = 0


def set_screen_output(enabled: bool) -> None:
    """Declare a guided screen session without treating direct TTY commands as screens."""
    global _screen_output, _intro_pending
    clear_status()
    _screen_output = enabled
    if not enabled:
        _pending.clear()
        _intro_pending = False


def activity(message: str, *, preformatted: bool = False) -> None:
    """Replace one gray status line, or append a plain line in logs."""
    value = " ".join(inert_text(text(message)).split())
    with _status_lock:
        if _working is not None:
            # Supervised workers already animate their own elapsed/counter labels.
            managed = not preformatted and interactive_display()
            if managed and _working.message is None:
                _working.started = time.monotonic()
            _working.message = value if managed else None
            if managed:
                value = _working_label(_working)
        _draw_activity(value)


def _draw_activity(value: str) -> None:
    """Draw an inert status value while holding the shared status lock."""
    global _status_width
    if not interactive_display():
        _status_width = 0
        typer.echo(value)
        return
    width = max(1, shutil.get_terminal_size((80, 24)).columns - 1)
    value = _short(value, width)
    padding = max(0, min(_status_width, width) - _width(value))
    click.echo(
        "\r" + style_text(value + " " * padding, MessageKind.ACTIVITY),
        nl=False,
        color=styles_enabled(),
    )
    _status_width = _width(value)


def emit(message: Any = "", *, err: bool = False, kind: MessageKind = MessageKind.INFO) -> None:
    """Keep current-task messages available when its next menu redraws."""
    global _intro_pending
    value = str(message)
    if kind is MessageKind.ACTIVITY:
        activity(value)
        return
    clear_status()
    if err and kind is MessageKind.INFO:
        kind = MessageKind.ERROR
    err = _message_stderr(kind, err=err)
    # Announce the task after completion/error feedback, independently of that feedback.
    if _intro_pending and value.strip() and kind in (MessageKind.INFO, MessageKind.ACTIVITY):
        _intro_pending = False
        emit("Next up:", kind=MessageKind.QUESTION)
    messages = [
        Message(inert_text(line), kind if line else MessageKind.INFO)
        for line in text(value).split("\n")
    ]
    if _screen_output and interactive_display():
        _pending.extend(messages)
    content = "\n".join(style_text(_message_text(item), item.kind, err=err) for item in messages)
    typer.echo(content, err=err, color=styles_enabled(err=err))


def _report_feedback(message: str, kind: ReportKind) -> None:
    emit(message, kind=MessageKind(kind.value))


# Domain callbacks keep their callable contract while carrying durable feedback roles.
report_activity = Reporter(activity, _report_feedback)


def refresh(*, reserved_rows: int = 5) -> None:
    global _body_rows
    clear_status()
    if not interactive_display():
        return
    set_screen_output(True)
    messages = list(_pending)
    _pending.clear()
    size = shutil.get_terminal_size((80, 24))
    width = max(1, size.columns - 1)
    header = _menu_header(width, size.lines)
    wrapped = _message_lines(_overview(messages), width)
    available = max(1, size.lines - len(header) - reserved_rows)
    if len(wrapped) > available:
        show_details("Input instructions", messages)
        wrapped = wrapped[:available]
    click.clear()
    _print_header(header)
    _body_rows = len(wrapped)
    for line, kind in wrapped:
        _print_line(line, kind)


def screen(step: int | None = None, *, workspace: str | None = None) -> None:
    """Replace the current step in a terminal; keep redirected output readable."""
    global _step, _body_rows, _workspace, _intro_pending, _screen_output
    clear_status()
    _screen_output = True
    _intro_pending = step is not None
    if workspace is not None:
        _workspace = inert_text(workspace)
    elif step in (None, 1):
        _workspace = ""
    _step = step
    _body_rows = 0
    _pending.clear()
    if interactive_display():
        click.clear()
        size = shutil.get_terminal_size((80, 24))
        _print_header(_menu_header(max(1, size.columns - 1), size.lines))
        return
    width = shutil.get_terminal_size((80, 24)).columns
    _print_line(BANNER if width >= 64 else "TRAVELMAP", MessageKind.BRAND)
    if step is not None:
        typer.echo()
        _print_header(
            [
                Message(
                    text("Step {step} / {total} · {name}").format(
                        step=step, total=len(STEP_NAMES), name=STEP_NAMES[step - 1]
                    ),
                    MessageKind.HEADING,
                    _workspace_suffix(),
                )
            ]
        )
        typer.echo()
    typer.echo()


def restore_overview(step: int, workspace: str) -> None:
    """Restore a parent screen, retaining actionable feedback from its nested action."""
    feedback = [
        message
        for message in _pending
        if message.kind
        in (
            MessageKind.RESULT,
            MessageKind.SUCCESS,
            MessageKind.NOTICE,
            MessageKind.WARNING,
            MessageKind.ERROR,
        )
    ]
    screen(step, workspace=workspace)
    _pending.extend(feedback)
    if not interactive_display():
        return
    for message in feedback:
        _print_line(_message_text(message), message.kind)


def wait_for_reading() -> None:
    if interactive_display():
        show_details("Help", _pending)


def _width(value: str) -> int:
    return sum(
        0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in "WF" else 1
        for char in value
    )


def _wrap(value: str, width: int) -> list[str]:
    lines = []
    line = ""
    for char in value:
        if line and _width(line + char) > width:
            space = line.rfind(" ")
            if space > 0 and char != " ":
                lines.append(line[:space].rstrip())
                line = line[space + 1 :]
            else:
                lines.append(line.rstrip())
                line = ""
            if not line and char == " ":
                continue
        line += char
    lines.append(line)
    return lines


def _short(value: str, width: int) -> str:
    value = text(value)
    if _width(value) <= width:
        return value
    result = ""
    for char in value:
        if _width(result + char) > max(0, width - 1):
            break
        result += char
    return result + "…"


def _choice_label(value: str) -> str:
    return inert_text(text(value))


def _print_choice(value: str, *, selected: bool = False, highlighted: bool = False) -> None:
    """Highlight flagged data without treating a menu option as a stderr diagnostic."""
    kind = (
        MessageKind.WARNING
        if highlighted
        else MessageKind.SELECTED
        if selected
        else MessageKind.INFO
    )
    content = style_text(value, kind)
    if highlighted and styles_enabled():
        content = click.style(content, bold=True, reverse=True if selected else None)
    typer.echo(content, color=styles_enabled())


def _workspace_suffix() -> str:
    return " · " + _workspace if _workspace else ""


def _menu_header(width: int, rows: int) -> list[Message]:
    # The redraw must retain the art; small terminals reserve these rows for the task and menu.
    wide = width >= 63  # Callers reserve the terminal's last column to avoid automatic wrapping.
    banner = [
        Message(line, MessageKind.BRAND)
        for line in (BANNER.splitlines() if wide and rows >= 24 else ["TRAVELMAP"])
    ]
    if _step is None:
        return banner
    lines = [
        Message(
            f"Step {_step} / {len(STEP_NAMES)} · {STEP_NAMES[_step - 1]}",
            MessageKind.HEADING,
            _workspace_suffix(),
        )
    ]
    if rows >= 20 and wide:
        lines = banner + lines
    # At eight rows the menu needs this row to retain its step heading without scrolling.
    if rows >= 10:
        lines.append(Message(""))
    return [
        Message(
            _short(line.value, width),
            line.kind,
            _short(line.suffix, width - _width(line.value))
            if line.suffix and width > _width(line.value)
            else "",
        )
        for line in lines
    ]


def _print_header(header: Sequence[Message]) -> None:
    for line in header:
        if line.suffix:
            content = style_text(line.value, line.kind) + style_text(line.suffix, MessageKind.HINT)
            typer.echo(content, color=styles_enabled())
        else:
            _print_line(line.value, line.kind)


def show_details(title: str, lines: Sequence[str | Message]) -> None:
    """Page full task text or a focused label without depending on scrollback."""
    clear_status()
    messages = [line if isinstance(line, Message) else Message(line) for line in lines]
    if not interactive_display():
        for message in messages:
            _print_line(_message_text(message), message.kind)
        return
    set_screen_output(True)
    page = 0
    while True:
        size = shutil.get_terminal_size((80, 24))
        width = max(1, size.columns - 1)
        wrapped = _message_lines(messages, width) or [("", MessageKind.INFO)]
        count = max(1, size.lines - 4)
        pages = (len(wrapped) + count - 1) // count
        page = min(page, pages - 1)
        click.clear()
        # Keep parent orientation in the pager's previously unused fourth reserved row.
        _print_header(
            [line for line in _menu_header(width, size.lines) if line.kind is MessageKind.HEADING]
        )
        _print_line(_short(inert_text(title), width), MessageKind.HEADING)
        for line, kind in wrapped[page * count : (page + 1) * count]:
            _print_line(line, kind)
        page_hint = text("Page {page}/{pages} · ↑/↓: pages · c: copy").format(
            page=page + 1, pages=pages
        )
        if _width(page_hint) > width:
            page_hint = text("{page}/{pages} ↑/↓ · c: copy").format(page=page + 1, pages=pages)
        _print_line(_short(page_hint, width), MessageKind.HINT)
        return_hint = text("Enter: return · keep open while working")
        if _width(return_hint) > width:
            return_hint = text("Enter/Esc: return")
        _print_line(_short(return_hint, width), MessageKind.HINT, nl=False)
        key = click.getchar()
        if key in ("\r", "\n", "\x1b", "b"):
            typer.echo()
            return
        if key in ("\x1b[B", "\x1b[6~", "\x1bOB"):
            page = min(pages - 1, page + 1)
        elif key in ("\x1b[A", "\x1b[5~", "\x1bOA"):
            page = max(0, page - 1)
        elif key == "c":
            # Native soft wrapping preserves spaces and shell tokens when copying. This
            # explicitly requested view may scroll; the bounded pager resumes afterwards.
            click.clear()
            for message in messages:
                _print_line(_message_text(message), message.kind)
            _print_line(text("Enter/Esc: return"), MessageKind.HINT, nl=False)
            while click.getchar() not in ("\r", "\n", "\x1b", "b"):
                pass
            typer.echo()


def _arrow_choice(
    question: str,
    choices: Sequence[str],
    default: int | None,
    *,
    cancel_index: int | None = None,
    cancel_label: str = "Back",
    preserve_order: bool = False,
    instructions_first: bool = False,
    highlighted_indices: Sequence[int] = (),
) -> int:
    """Draw a bounded menu, restoring the cursor even on interruption."""
    set_screen_output(True)
    messages = list(_pending)
    _pending.clear()
    selected = (default or 1) - 1
    body_page = 0
    reading_instructions = instructions_first
    highlighted = frozenset(highlighted_indices)
    typer.echo("\x1b[?25l", nl=False)
    try:
        while True:
            size = shutil.get_terminal_size((80, 24))
            width = max(1, size.columns - 1)
            header = _menu_header(width, size.lines)
            exit_hint = text("Ctrl-C: save and exit")
            if _width(exit_hint) > width:
                exit_hint = text("Ctrl-C: save & exit")
            footer = ([text(f"Esc: {cancel_label}")] if cancel_index is not None else []) + [
                exit_hint
            ]
            joined = " · ".join(footer)
            footer = (
                [joined]
                if _width(joined) <= width
                else [line for hint in footer for line in _wrap(hint, width)]
            )
            body = _message_lines(messages if preserve_order else _overview(messages), width)
            body_count = max(
                0, min(len(body), (size.lines - len(header) - 8 - (len(footer) - 1)) // 2)
            )
            instruction_pages = 0
            if instructions_first:
                # Put the complete instructions above the choices when they fit.
                # Otherwise give them their own pages ahead of the choice screen.
                if len(body) <= max(0, size.lines - len(header) - 6 - len(footer)):
                    body_count = len(body)
                else:
                    instruction_rows = max(1, size.lines - len(header) - 1)
                    instruction_pages = (len(body) + instruction_rows - 1) // instruction_rows
                    if reading_instructions:
                        body_page = min(body_page, instruction_pages - 1)
                        click.clear()
                        _print_header(header)
                        offset = body_page * instruction_rows
                        for line, kind in body[offset : offset + instruction_rows]:
                            _print_line(line, kind)
                        next_label = "choices" if body_page + 1 == instruction_pages else "more"
                        _print_line(
                            _short(f"{body_page + 1}/{instruction_pages} ↓ {next_label}", width),
                            MessageKind.HINT,
                            nl=False,
                        )
                        key = click.getchar()
                        if key in ("\x1b[B", "\x1bOB", "\xe0P", "\x00P", "\x1b[6~", "\r", "\n"):
                            body_page += 1
                            reading_instructions = body_page < instruction_pages
                        elif key in ("\x1b[A", "\x1bOA", "\xe0H", "\x00H", "\x1b[5~"):
                            body_page = max(0, body_page - 1)
                        elif key == "\x1b" and cancel_index is not None:
                            return cancel_index
                        continue
                    body_count = 0
            body_pages = max(1, (len(body) + body_count - 1) // body_count) if body_count else 1
            menu_body_page = min(body_page, body_pages - 1)
            more_info = len(body) > body_count
            show_info = more_info or bool(_workspace)
            # Keep one choice and the complete footer; sacrifice the divider first.
            divider = size.lines > len(header) + body_count + int(show_info) + 4 + len(footer)
            count = min(
                len(choices),
                max(
                    1,
                    size.lines
                    - len(header)
                    - body_count
                    - 3
                    - len(footer)
                    - int(show_info)
                    - int(divider),
                ),
            )
            first = max(0, min(selected - count // 2, len(choices) - count))
            click.clear()
            _print_header(header)
            for line, kind in body[menu_body_page * body_count : (menu_body_page + 1) * body_count]:
                _print_line(line, kind)
            if show_info:
                info_hint = f"Info {menu_body_page + 1}/{body_pages} · PgUp/PgDn · i: full info"
                if _width(info_hint) > width:
                    info_hint = "i: info / folder" if _workspace else "i: full info"
                if instruction_pages:
                    info_hint = "PgUp: instructions · i: full info"
                    if _width(info_hint) > width:
                        info_hint = "PgUp: instructions"
                elif instructions_first:
                    info_hint = "i: info / folder"
                _print_line(
                    _short(info_hint, width),
                    MessageKind.HINT,
                )
            if divider:
                _print_line("─" * width, MessageKind.HINT)
            _print_line(_short("? " + inert_text(text(question)), width), MessageKind.QUESTION)
            keys_hint = text("Use ↑/↓, then Enter. d: full choice")
            if _width(keys_hint) > width:
                keys_hint = text("↑/↓ Enter · d: full")
            _print_line(_short(keys_hint, width), MessageKind.HINT)
            before = " ↑ more" if first else ""
            after = " ↓ more" if first + count < len(choices) else ""
            range_hint = f"Options {first + 1}–{first + count}/{len(choices)}{before}{after}"
            if _width(range_hint) > width:
                range_hint = f"{first + 1}–{first + count}/{len(choices)}"
            _print_line(_short(range_hint, width), MessageKind.HINT)
            for index in range(first, first + count):
                label = _choice_label(choices[index])
                marked = "! " if index in highlighted else ""
                line = ("> " if index == selected else "  ") + marked + label
                _print_choice(
                    _short(line, width),
                    selected=index == selected,
                    highlighted=index in highlighted,
                )
            for index, hint in enumerate(footer):
                _print_line(hint, MessageKind.HINT, nl=index < len(footer) - 1)
            key = click.getchar()
            if key in ("\x1b[A", "\x1bOA", "\xe0H", "\x00H"):
                selected = (selected - 1) % len(choices)
            elif key in ("\x1b[B", "\x1bOB", "\xe0P", "\x00P"):
                selected = (selected + 1) % len(choices)
            elif key in ("\r", "\n"):
                return selected
            elif key == "\x1b" and cancel_index is not None:
                return cancel_index
            elif key == "d":
                show_details(
                    "Selected option",
                    [inert_text(text(question)), _choice_label(choices[selected])],
                )
            elif key == "i":
                context = [Message(_workspace, MessageKind.HINT)] if _workspace else []
                if _step is not None:
                    context.insert(
                        0,
                        Message(
                            f"Step {_step} / {len(STEP_NAMES)} · {STEP_NAMES[_step - 1]}",
                            MessageKind.HEADING,
                        ),
                    )
                show_details("Task information", [*context, inert_text(text(question)), *messages])
            elif key == "\x1b[6~":
                body_page = min(body_pages - 1, menu_body_page + 1)
            elif key == "\x1b[5~":
                if instruction_pages:
                    body_page = instruction_pages - 1
                    reading_instructions = True
                else:
                    body_page = max(0, menu_body_page - 1)
    finally:
        typer.echo("\x1b[?25h")


def _navigation_hint(*, back: bool, pause: bool) -> str:
    hints = []
    if back:
        hints.append(text("/back: Back"))
    if pause:
        hints.append(text("/exit: Save and exit"))
    return " · ".join(hints)


def show_choice_prompt(
    question: str,
    choices: tuple[str, ...],
    *,
    default: int | None,
    cancel_index: int | None = None,
    cancel_label: str = "Back",
    pause_index: int | None = None,
    highlighted_indices: Sequence[int] = (),
) -> str:
    clear_status()
    if interactive_display():
        return str(
            _arrow_choice(
                question,
                choices,
                default,
                cancel_index=cancel_index,
                cancel_label=cancel_label,
                highlighted_indices=highlighted_indices,
            )
            + 1
        )
    typer.echo()
    _print_line("? " + inert_text(text(question)), MessageKind.QUESTION)
    typer.echo()
    highlighted = frozenset(highlighted_indices)
    for index, choice in enumerate(choices, start=1):
        marked = "! " if index - 1 in highlighted else ""
        _print_choice(
            f"{index}. {marked}{_choice_label(choice)}", highlighted=index - 1 in highlighted
        )
    back_available = cancel_index is not None and cancel_index != pause_index
    hint = _navigation_hint(back=back_available, pause=pause_index is not None)
    if hint:
        _print_line(hint, MessageKind.HINT)
    answer = str(
        typer.prompt(text("Choose a number"), default=str(default) if default is not None else None)
    )
    token = answer.strip().casefold()
    if back_available and token in ("back", "/back"):
        assert cancel_index is not None
        return str(cancel_index + 1)
    if pause_index is not None and token in ("pause", "/exit", "save and exit"):
        return str(pause_index + 1)
    return answer


def action_prompt(
    question: str,
    choices: Sequence[tuple[str, str]],
    *,
    default: str = "help",
    preserve_order: bool = False,
    instructions_first: bool = False,
) -> str:
    """Use arrow menus on terminals and named actions for plain input streams."""
    clear_status()
    if interactive_display():
        keys = [key for key, _ in choices]
        index = keys.index(default) + 1 if default in keys else 1
        cancel_key = "back" if "back" in keys else "pause" if "pause" in keys else None
        cancel_index = keys.index(cancel_key) if cancel_key is not None else None
        return keys[
            _arrow_choice(
                question,
                [label for _, label in choices],
                index,
                cancel_index=cancel_index,
                cancel_label="Back" if cancel_key == "back" else "Save and exit",
                preserve_order=preserve_order,
                instructions_first=instructions_first,
            )
        ]
    typer.echo()
    typer.echo(" · ".join(f"{key}: {text(label)}" for key, label in choices))
    keys = [key for key, _ in choices]
    hint = _navigation_hint(back="back" in keys, pause="pause" in keys)
    if hint:
        _print_line(hint, MessageKind.HINT)
    answer = (
        str(
            typer.prompt(
                style_text("? " + inert_text(text(question)), MessageKind.QUESTION), default=default
            )
        )
        .strip()
        .lower()
    )
    if answer == "/back" and "back" in keys:
        return "back"
    if answer in ("/exit", "save and exit") and "pause" in keys:
        return "pause"
    return answer


class Navigation(Exception):
    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(action)


def confirm_action(action: str, label: str, *, default: str = "back") -> str:
    result = action_prompt(
        label, ((action, label), ("back", "Back"), ("pause", "Save and exit")), default=default
    )
    if result == "pause":
        raise Navigation("pause")
    return result


def choose_number(answer: str, count: int, *, default: int | None = None) -> int:
    """Validate a one-based menu answer, raising an error suitable for an in-place reprompt."""

    if not answer.strip() and default is not None:
        return default
    try:
        selection = int(answer)
    except ValueError as exc:
        raise ValueError(f"Choose a number from 1 to {count}.") from exc
    if not 1 <= selection <= count:
        raise ValueError(f"Choose a number from 1 to {count}.")
    return selection


def text_input(question: str, *, default: str | None = None) -> str:
    clear_status()
    label = "? " + inert_text(text(question))
    if interactive_display():
        size = shutil.get_terminal_size((80, 24))
        width = max(1, size.columns - 1)
        questions = _wrap(label, width)
        hint = text("Type a value") + " · " + _navigation_hint(back=True, pause=True)
        hints = (
            [hint] if _width(hint) <= width else [text("/back: Back"), text("/exit: Save & exit")]
        )
        hints = [line for hint in hints for line in _wrap(hint, width)]
        refresh(reserved_rows=len(questions) + len(hints) + 2)
        _print_line("─" * width, MessageKind.HINT)
        for line in questions:
            _print_line(line, MessageKind.QUESTION)
        for hint in hints:
            _print_line(hint, MessageKind.HINT)
        label = text("Value")
    else:
        _print_line(_navigation_hint(back=True, pause=True), MessageKind.HINT)
    answer = str(
        typer.prompt(style_text(label, MessageKind.QUESTION), default=default, show_default=False)
    )
    if answer.strip().lower() in ("/back", "/exit"):
        raise Navigation("back" if answer.strip().lower() == "/back" else "pause")
    return answer


def edit_input(question: str, *, default: str | None = None) -> str | None:
    """Cancel a nested edit locally; exit still reaches the workflow controller."""
    try:
        answer = text_input(question, default=default if default is not None else "")
    except Navigation as nav:
        if nav.action != "back":
            raise
        return None
    if answer.strip().lower() == "back":
        return None
    if answer.strip().lower() == "pause":
        raise Navigation("pause")
    return answer
