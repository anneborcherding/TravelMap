"""Semantic feedback that also supports existing plain-text report callbacks."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from travelmap.ui_text import text


def progress_label(
    message: str, elapsed_seconds: float, *, show_pause_hint: bool, compact: bool = False
) -> str:
    """Format elapsed work consistently; callers escape their activity text."""
    minutes, seconds = divmod(max(0, int(elapsed_seconds)), 60)
    template = (
        "{minutes}m {seconds:02d}s | {message}"
        if compact
        else "Working · {minutes}m {seconds:02d}s elapsed | {message}"
    )
    if show_pause_hint:
        template += " | Ctrl-C to pause"
    return text(template).format(minutes=minutes, seconds=seconds, message=message)


class ReportKind(StrEnum):
    NOTICE = "notice"
    WARNING = "warning"
    RESULT = "result"
    SUCCESS = "success"


class Notice(str):
    """A retained informational message that does not request user action."""


def feedback_kind(message: str) -> ReportKind:
    return ReportKind.NOTICE if isinstance(message, Notice) else ReportKind.WARNING


def restore_feedback(messages: object, notice_indices: object) -> list[str]:
    """Restore explicit message roles after an export worker's JSON handoff."""
    if (
        not isinstance(messages, list)
        or not all(isinstance(message, str) for message in messages)
        or not isinstance(notice_indices, list)
        or any(type(index) is not int or not 0 <= index < len(messages) for index in notice_indices)
        or len(set(notice_indices)) != len(notice_indices)
    ):
        raise ValueError("Invalid export feedback roles.")
    notices = set(notice_indices)
    return [
        Notice(message) if index in notices else message for index, message in enumerate(messages)
    ]


@dataclass(frozen=True)
class Reporter:
    """Keep routine progress separate from feedback the caller must retain."""

    progress: Callable[[str], None]
    feedback: Callable[[str, ReportKind], None]

    def __call__(self, message: str) -> None:
        self.progress(message)


def report_feedback(
    report: Callable[[str], None], message: str, kind: ReportKind = ReportKind.WARNING
) -> None:
    """Preserve semantic roles where supported; plain log consumers receive every message."""
    if isinstance(report, Reporter):
        report.feedback(message, kind)
    else:
        report(message)
