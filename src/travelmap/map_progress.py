"""Factual long-job status with interactive animation and portable worker supervision."""

from __future__ import annotations

import itertools
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil

from travelmap.reporting import ReportKind, progress_label, report_feedback
from travelmap.terminal import (
    activity,
    clear_status,
    inert_text,
    interactive_display,
)
from travelmap.ui_text import text as ui_text

MAX_RSS = 3 * 1024**3
MAX_STAGING = 16 * 1024**3


class Status:
    """Keep animation transient and plain logs readable."""

    def __init__(self, report: Callable[[str], None]) -> None:
        self.report = report
        self.started = time.monotonic()
        self.last = 0.0
        self.message = ui_text("Opening local data")
        self.frames = itertools.cycle("|/-\\")
        self.animated = interactive_display()

    def update(self, message: str | None = None, *, force: bool = False) -> None:
        if message is not None:
            self.message = inert_text(ui_text(message))
        now = time.monotonic()
        status_text = progress_label(
            self.message,
            now - self.started,
            show_pause_hint=not self.animated,
            compact=self.animated and shutil.get_terminal_size().columns < 60,
        )
        if self.animated:
            activity(next(self.frames) + " " + status_text, preformatted=True)
        elif force or now - self.last >= 5:
            self.report(status_text)
        if force or now - self.last >= 5:
            self.last = now

    def finish(self) -> None:
        clear_status()


def monitor(
    process: subprocess.Popen[Any],
    staging: Path,
    read: Callable[[], dict[str, Any]],
    report: Callable[[str], None],
) -> None:
    """No total timeout; sample native memory, work and liveness independently."""
    status = Status(report)
    try:
        probe = psutil.Process(process.pid)
    except psutil.NoSuchProcess:
        status.finish()
        process.wait()
        return
    previous: Any = None
    last_work = time.monotonic()
    last_check = 0.0
    warned = False
    memory_warned = False
    try:
        while process.poll() is None:
            try:
                snapshot = read()
            except (ValueError, OSError):
                snapshot = {}
            now = time.monotonic()
            if now - last_check >= 1:
                last_check = now
                try:
                    rss = probe.memory_info().rss
                    if rss > 1536 * 1024**2 and not memory_warned:
                        status.finish()
                        report_feedback(
                            report,
                            ui_text(
                                "Worker resident memory is above 1.5 GiB; "
                                "continuing within the 3 GiB supervised limit."
                            ),
                            ReportKind.NOTICE,
                        )
                        memory_warned = True
                    cpu = probe.cpu_times()
                    state = (snapshot.get("sequence"), cpu.user, cpu.system)
                    if rss > MAX_RSS:
                        raise ValueError(
                            f"{snapshot.get('source', 'Map worker')} / "
                            f"{snapshot.get('phase', snapshot.get('activity', 'processing'))}: "
                            "worker resident memory exceeds 3 GiB. Reduce selected classes or "
                            "use a machine with the documented resources; valid downloads need"
                            " no re-download."
                        )
                    if state != previous:
                        last_work = now
                        warned = False
                    previous = state
                except psutil.NoSuchProcess:
                    break
                except psutil.AccessDenied:
                    if not warned:
                        report_feedback(
                            report,
                            ui_text(
                                "Process monitoring unavailable; "
                                "reported work counters remain visible."
                            ),
                        )
                        warned = True
                size = 0
                for path in staging.rglob("*"):
                    try:
                        if path.is_file() and not path.is_symlink():
                            size += path.stat().st_size
                    except FileNotFoundError:
                        pass  # Atomic progress publication can remove its own temporary file.
                if size > MAX_STAGING:
                    raise ValueError(
                        f"{snapshot.get('source', 'Map worker')} / "
                        f"{snapshot.get('phase', snapshot.get('activity', 'processing'))}: "
                        "preparation staging exceeds 16 GiB. Free workspace disk or reduce"
                        " selected classes; no re-download is needed."
                    )
                if now - last_work > 300 and not warned:
                    report_feedback(
                        report,
                        ui_text(
                            "Possible stall: measured work/CPU has not advanced for five minut"
                            "es. You can pause with Ctrl+C; elapsed time alone does not stop t"
                            "his job."
                        ),
                    )
                    warned = True
            activity = snapshot.get("activity")
            processed = snapshot.get("scanned")
            stored = snapshot.get("retained", 0)
            if type(processed) is int and processed >= 0 and type(stored) is int and stored >= 0:
                label = inert_text(str(snapshot.get("source", "Local data")))
                if status.animated:
                    label = label if len(label) <= 18 else label[:7] + "..." + label[-8:]
                # The source counter includes callbacks across multiple processing phases;
                # it is not a count of distinct features or a completion percentage.
                activity = ui_text(
                    "Processed events: {processed:,} | Stored features: {stored:,} | "
                    "{phase} {source}"
                ).format(
                    phase=inert_text(str(snapshot.get("phase", "Read"))),
                    source=label,
                    processed=processed,
                    stored=stored,
                )
            elif (
                status.animated
                and activity
                and activity.startswith("Validating")
                and snapshot.get("source")
            ):
                label = inert_text(str(snapshot["source"]))
                label = label if len(label) <= 18 else label[:7] + "..." + label[-8:]
                activity = f"Validate {label} | {activity.split(':', 1)[-1].strip()}"
            status.update(activity)
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                pass
    finally:
        status.finish()
