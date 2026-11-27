"""Explicit coordinate disclosure, secret-safe key input and batch route recovery."""

from __future__ import annotations

import getpass
import itertools
import os
import shutil
import time
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

from travelmap import itinerary, routes
from travelmap.itinerary_guidance import choose
from travelmap.manual_routes import names_for, run_manual
from travelmap.mapdata import atomic_json, read_json
from travelmap.reporting import progress_label
from travelmap.terminal import (
    MessageKind,
    Navigation,
    action_prompt,
    activity,
    clear_status,
    confirm_action,
    edit_input,
    emit,
    inert_text,
    interactive_display,
    restore_overview,
    style_text,
    wait_for_reading,
)
from travelmap.ui_text import text
from travelmap.workspace import plan_workspace


def echo(value: str, *, kind: MessageKind = MessageKind.INFO) -> None:
    emit(inert_text(value), kind=kind)


class RouteProgress:
    """Keep interactive acquisition updates on one terminal line."""

    def __init__(self, report: Callable[[str], None]) -> None:
        self.report = report
        self.started = time.monotonic()
        self.last_report = 0.0
        self.frames = itertools.cycle("|/-\\")
        self.interactive = interactive_display()
        self.visible = False

    def update(self, message: str, *, force: bool = False) -> None:
        message = inert_text(message)
        now = time.monotonic()
        label = progress_label(
            message,
            now - self.started,
            show_pause_hint=not self.interactive,
            compact=self.interactive and shutil.get_terminal_size().columns < 60,
        )
        if self.interactive:
            activity(f"{next(self.frames)} {label}", preformatted=True)
            self.visible = True
        elif force or now - self.last_report >= 5:
            self.report(label)
            self.last_report = now

    def finish(self) -> None:
        if not self.interactive or not self.visible:
            return
        clear_status()
        self.visible = False


def read_secret(env_name: str = "OPENROUTESERVICE_API_KEY") -> str | None:
    configured = os.environ.get(env_name)
    if configured:
        return configured
    clear_status()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass(
                style_text(
                    "? " + inert_text(text("Session-only OpenRouteService API key (hidden): ")),
                    MessageKind.QUESTION,
                    err=True,
                )
            )
        if value.strip().lower() in ("", "back", "/back"):
            return None
        if value.strip().lower() == "/exit":
            raise Navigation("pause")
        return value
    except KeyboardInterrupt:
        return None
    except (getpass.GetPassWarning, EOFError, OSError):
        echo("Hidden key input is unavailable. Use a regular terminal or local route files.")
        return None


def select_subset(
    segments: list[dict[str, Any]], trip: dict[str, Any]
) -> list[dict[str, Any]] | None:
    lookup = {s["properties"]["sequence"]: s for s in segments}
    while True:
        echo("Available unresolved journeys:")
        for segment in segments:
            echo(names_for(trip, segment))
        value = edit_input("Enter connection numbers separated by spaces, or all", default="all")
        if value is None:
            return None
        answer = value.strip().lower()
        if answer == "all":
            return segments
        try:
            indices = [int(v) for v in answer.split()]
            if (
                not indices
                or len(indices) != len(set(indices))
                or any(v not in lookup for v in indices)
            ):
                raise ValueError
            return [lookup[v] for v in indices]
        except ValueError:
            echo(
                "Choose displayed unresolved numbers exactly once, all, or pause.",
                kind=MessageKind.ERROR,
            )


def undo_approximations(root: Path, trip: dict[str, Any], segments: list[dict[str, Any]]) -> None:
    selected = select_subset(segments, trip)
    if selected is None:
        return
    echo(f"Undo straight-line choices for {len(selected)} connections.")
    echo("Valid saved service routes and local assignments are kept and checked again.")
    if confirm_action("undo", "Undo these straight-line choices") == "undo":
        routes.clear_choices(root, [routes.segment_key(trip, s) for s in selected])
        echo(
            "Choices cleared. Missing routes can now be acquired or supplied locally.",
            kind=MessageKind.SUCCESS,
        )


def run_routing(root: Path, trip: dict[str, Any], opener: Any = None) -> str:
    opts = routes.settings(root)
    secret: str | None = None
    error_path = plan_workspace(root).metadata_dir / "route-errors.json"
    errors = (
        read_json(error_path, routes.MAX_BYTES).get("errors", {}) if error_path.exists() else {}
    )
    last_request = 0.0
    try:
        first_overview = True
        while True:
            if not first_overview:
                restore_overview(4, str(root))
            first_overview = False
            echo("Complete any missing routes between your stops.")
            echo("Use local route files, the routing service, or approximate straight lines.")
            resolution_notes: list[str] = []
            resolved, missing = routes.resolve(root, trip, resolution_notes.append)
            total_routes = len(itinerary.parts(trip, "segment"))
            echo(f"Routes: {total_routes} total, {len(resolved)} ready, {len(missing)} open.")
            source_labels = {
                "manual": "your route file",
                "embedded": "itinerary line",
                "provider": "saved routing-service result",
                "direct": "approximate straight line",
                "zero": "same location",
            }
            for segment in itinerary.parts(trip, "segment"):
                record = resolved.get(routes.segment_key(trip, segment))
                status = f"ready ({source_labels[record['source']]})" if record else "needs a route"
                echo(f"{names_for(trip, segment)}: {status}")
            approximations = [
                s
                for s in itinerary.parts(trip, "segment")
                if resolved.get(routes.segment_key(trip, s), {}).get("source") == "direct"
            ]
            if approximations:
                echo(
                    f"{len(approximations)} routes use approximate straight lines; "
                    "distance is unknown."
                )
            if resolution_notes:
                for note in resolution_notes:
                    echo(note, kind=MessageKind.WARNING)
            if not missing:
                echo("All routes are ready.", kind=MessageKind.SUCCESS)
                if interactive_display() or approximations:
                    answer = action_prompt(
                        "Continue to Poster design?",
                        (
                            ("done", "Continue"),
                            *(
                                ((("review", "Review/undo straight-line choices"),))
                                if approximations
                                else ()
                            ),
                            ("back", "Back"),
                            ("pause", "Save and exit"),
                        ),
                        default="done",
                    )
                    if answer == "review":
                        undo_approximations(root, trip, approximations)
                        continue
                    if answer in ("done", "back", "pause"):
                        return answer
                    echo(
                        "Choose Continue, Review/undo straight-line choices, "
                        "Back, or Save and exit."
                    )
                    continue
                return "done"
            not_found = [
                s for s in missing if errors.get(routes.segment_key(trip, s)) == "not-found"
            ]
            if not_found:
                echo(f"Previously not found by the service: {len(not_found)} open routes.")
            actions = []
            options = []

            if opts["enabled"]:
                actions.append("acquire")
                options.append("Find open routes with routing service")
            actions.extend(("local", "direct"))
            options.extend(
                (
                    "Supply local route files",
                    "Use approximate straight lines",
                )
            )
            if not_found and opts["enabled"]:
                actions.extend(("retry-cycling", "retry-walking"))
                options.extend(
                    (
                        "Cycling retry for route-not-found journeys",
                        "Walking retry for route-not-found journeys",
                    )
                )
            if approximations:
                actions.append("review")
                options.append("Review/undo straight-line choices")
            actions.extend(("help", "back", "menu", "pause"))
            options.extend(("Help", "Back", "Menu", "Save and exit"))
            chosen = choose(
                options,
                "Complete your routes",
                back_index=actions.index("back"),
                pause_index=actions.index("pause"),
            )
            if chosen is None:
                return "back"
            action = actions[chosen]
            if action == "pause":
                return "pause"
            if action == "back":
                return "back"
            if action == "menu":
                return "menu"
            if action == "review":
                undo_approximations(root, trip, approximations)
                continue
            if action == "help":
                echo(
                    "Journey geometry comes from assigned files, valid embedded lines or "
                    "matching provider caches first."
                )
                emit()
                echo(
                    "Acquisition sends selected endpoint coordinates to OpenRouteService. A key "
                    "is used only in this session; it is never saved."
                )
                emit()
                echo(
                    "Cycling/walking are offered only for genuine route-not-found failures; "
                    "quota/auth/server errors have their own recovery. Local files or pause are "
                    "always available."
                )
                emit()
                echo(
                    "Provider account: https://account.heigit.org/ ; sign in/register yourself, "
                    "open the dashboard/API keys, create/copy a key."
                )
                emit()
                echo("Provider limits: https://openrouteservice.org/restrictions/")
                wait_for_reading()
                continue
            if action == "local":
                outcome = run_manual(root, trip, step=4)
                if outcome in ("pause", "menu"):
                    return outcome
                continue
            retry_not_found = action in ("retry-cycling", "retry-walking")
            candidates = not_found if retry_not_found else missing
            excluded = []
            if action in ("acquire", "retry-cycling", "retry-walking"):
                excluded = [
                    s for s in candidates if s["properties"]["transport_mode"] not in opts["modes"]
                ]
                candidates = [
                    s for s in candidates if s["properties"]["transport_mode"] in opts["modes"]
                ]
            if excluded:
                echo(
                    f"{len(excluded)} route(s) skipped because their recorded mode is not "
                    "enabled in map.routing.modes."
                )
            targets = candidates
            if (
                action in ("acquire", "retry-cycling", "retry-walking", "direct")
                and len(candidates) > 1
            ):
                scope = choose(
                    (
                        "Use straight lines for all open connections"
                        if action == "direct"
                        else "Find all matching routes",
                        "Choose a subset",
                        "Back",
                    ),
                    "Which connections should use this route strategy?",
                    back_index=2,
                )
                if scope is None or scope == 2:
                    continue
                if scope == 1:
                    selected = select_subset(candidates, trip)
                    if selected is None:
                        continue
                    targets = selected
            if not targets:
                echo(
                    "No matching unresolved journeys in this subset. Choose another "
                    "subset or local files."
                )
                continue
            if action == "direct":
                echo(f"Use straight lines for {len(targets)} connections:")
                for segment in targets:
                    echo(names_for(trip, segment))
                echo(
                    "Straight lines approximate these connections. Travel distance will be unknown."
                )
                if (
                    confirm_action("direct", "Use straight lines for these connections")
                    .strip()
                    .lower()
                    == "direct"
                ):
                    for segment in targets:
                        routes.save_choice(
                            root, routes.segment_key(trip, segment), "direct", trip=trip
                        )
                continue
            selected_profiles = {}
            profiles_cancelled = False
            for segment in targets:
                key = routes.segment_key(trip, segment)
                profile = (
                    "cycling-regular"
                    if action == "retry-cycling"
                    else "foot-walking"
                    if action == "retry-walking"
                    else routes.profile_for(segment, opts)
                )
                if profile is None:
                    echo(
                        names_for(trip, segment)
                        + (
                            ": this recorded mode has no default provider profile. Any "
                            "acquired road route would be an approximation; recorded "
                            "mode is retained."
                        )
                    )
                    approximation = choose(
                        (
                            "Driving approximation",
                            "Cycling approximation",
                            "Walking approximation",
                            "Local files/pause",
                        ),
                        "Choose explicitly for this connection:",
                    )
                    if approximation is None or approximation == 3:
                        profiles_cancelled = True
                        break
                    profile = routes.PROFILES[approximation]
                selected_profiles[key] = profile
            if profiles_cancelled:
                continue
            emit()
            echo("Provider destination: " + routes.PROVIDER)
            for segment in targets:
                echo(
                    names_for(trip, segment)
                    + (
                        f": sends {routes.endpoints(trip, segment)} using "
                        f"{selected_profiles[routes.segment_key(trip, segment)]}; "
                        f"recorded mode is unchanged."
                    )
                )
            emit()
            if (
                confirm_action("send", "Send these coordinates to OpenRouteService", default="send")
                .strip()
                .lower()
                != "send"
            ):
                continue
            if secret is None:
                echo(
                    "For an API key, sign in or register at https://account.heigit.org/, "
                    "then create and copy a key from your dashboard."
                )
                echo("Paste it at the hidden prompt. The key is used only for this session.")
                echo("Leave the key blank, type /back, or press Ctrl-C to return to Routes.")
                echo("Type /exit to save and exit.")
                secret = read_secret(opts["api_key_env"])
            if secret is None:
                echo("No request sent. Returned to Routes.")
                continue
            completed = len(resolved)
            batch_succeeded = 0
            failures: list[tuple[dict[str, Any], str]] = []
            progress = RouteProgress(lambda message: echo(message, kind=MessageKind.ACTIVITY))
            try:
                for index, segment in enumerate(targets, start=1):
                    key = routes.segment_key(trip, segment)
                    profile = selected_profiles[key]
                    while (
                        last_request and time.monotonic() - last_request < opts["request_delay_s"]
                    ):
                        wait = opts["request_delay_s"] - (time.monotonic() - last_request)
                        progress.update(
                            f"Waiting between requests; {completed} routes ready, "
                            f"{total_routes - completed} open."
                        )
                        time.sleep(min(1, wait))
                    progress.update(
                        f"Request {index} of {len(targets)}: {names_for(trip, segment)}",
                        force=True,
                    )
                    last_request = time.monotonic()
                    try:
                        assert secret is not None
                        record = routes.fetch(
                            trip, segment, profile, opts, secret, opener, progress.update
                        )
                        routes.save_provider(root, record)
                        routes.save_choice(root, key, profile, trip=trip)
                        errors.pop(key, None)
                        completed += 1
                        batch_succeeded += 1
                        progress.update(
                            f"Saved route {batch_succeeded} of {len(targets)}; "
                            f"{total_routes - completed} routes open.",
                            force=True,
                        )
                    except routes.ProviderError as exc:
                        errors[key] = exc.category
                        failures.append((segment, str(exc)))
                        progress.update(f"{names_for(trip, segment)}: {exc}", force=True)
                        if exc.category == "auth":
                            secret = None
                        atomic_json(error_path, {"schema_version": 1, "errors": errors})
                        if exc.category != "not-found":
                            break
                    atomic_json(error_path, {"schema_version": 1, "errors": errors})
            finally:
                progress.finish()
            for segment, message in failures:
                echo(names_for(trip, segment) + ": " + message, kind=MessageKind.ERROR)
            echo(
                f"Routing service finished: {batch_succeeded} routes saved; "
                f"{total_routes - completed} remain open."
            )
            failed_routes = [segment for segment, _ in failures]
            not_found_routes = [
                segment
                for segment in failed_routes
                if errors.get(routes.segment_key(trip, segment)) == "not-found"
            ]
            if not_found_routes and opts["direct_policy"] == "direct":
                echo(
                    "map.routing.unreachable is set to direct. Confirm before replacing "
                    "unfound routes with straight lines; distances remain unknown."
                )
                if (
                    confirm_action("direct", "Use straight lines for routes not found")
                    .strip()
                    .lower()
                    == "direct"
                ):
                    for segment in not_found_routes:
                        routes.save_choice(
                            root, routes.segment_key(trip, segment), "direct", trip=trip
                        )
    finally:
        secret = None
