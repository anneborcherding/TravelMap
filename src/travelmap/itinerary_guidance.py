"""Inspectable itinerary selection and corrections, before any route acquisition."""

import copy
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from travelmap import duration
from travelmap import itinerary as domain
from travelmap.reporting import feedback_kind
from travelmap.terminal import (
    MessageKind,
    Navigation,
    action_prompt,
    confirm_action,
    edit_input,
    emit,
    inert_text,
    restore_overview,
    screen,
    show_choice_prompt,
    wait_for_reading,
)
from travelmap.ui_text import text as ui_text
from travelmap.workspace import plan_workspace


def echo(value: Any, *, kind: MessageKind = MessageKind.INFO) -> None:
    emit(inert_text(str(value)), kind=kind)


def choose(
    labels: Sequence[str],
    question: str,
    *,
    default: int = 1,
    back_index: int | None = None,
    pause_index: int | None = None,
    highlighted_indices: Sequence[int] = (),
) -> int | None:
    """Select data by index; callers identify any navigation items already in their menu."""
    navigation = []
    if back_index is None:
        back_index = len(labels)
        navigation.append(("back", "Back"))
    if pause_index is None:
        pause_index = len(labels) + len(navigation)
        navigation.append(("pause", "Save and exit"))
    options = tuple(labels) + tuple(label for _, label in navigation)
    while True:
        answer = (
            show_choice_prompt(
                question,
                options,
                default=default,
                cancel_index=back_index,
                pause_index=pause_index,
                highlighted_indices=highlighted_indices,
            )
            .strip()
            .casefold()
        )
        if answer in ("pause", "/exit", "save and exit"):
            raise Navigation("pause")
        if answer in ("back", "/back"):
            return None
        if answer == "help" and not any(label.casefold() == "help" for label in options):
            echo(
                "Choose an item by number. Back returns to the previous screen; "
                "Save and exit preserves your work."
            )
            continue
        try:
            selected = int(answer) - 1
        except ValueError:
            selected = next(
                (index for index, label in enumerate(options) if answer == label.casefold()), -1
            )
        if 0 <= selected < len(options):
            if selected >= len(labels):
                action = navigation[selected - len(labels)][0]
                if action == "pause":
                    raise Navigation("pause")
                return None
            return selected
        if answer == "menu":
            return None  # Retain the legacy Back alias when this menu has no Menu action.
        echo("Choose one of the displayed numbers, Back, or Save and exit.", kind=MessageKind.ERROR)


def summary(trip: dict[str, Any], inspect: bool = False) -> None:
    stops, segments = domain.parts(trip, "stop"), domain.parts(trip, "segment")
    echo(f"Trip: {trip['metadata']['name']}")
    echo(
        f"{len(stops)} stops; {len(segments)} connections; "
        f"first: {stops[0]['properties']['name']}; last: "
        f"{stops[-1]['properties']['name']}"
    )
    modes = Counter(s["properties"]["transport_mode"] for s in segments)
    echo(
        "Transport: "
        + (", ".join(f"{mode} ({count})" for mode, count in modes.items()) or "No connections")
    )
    days = duration.assess(trip).days
    if days is not None:
        echo(ui_text("Day count: {days}.").format(days=days))
    for warning in domain.warnings(trip):
        echo(warning, kind=MessageKind(feedback_kind(warning).value))
    if inspect:
        for index, label in enumerate(stop_labels(trip), 1):
            echo(f"{index}. {label}")


def stop_labels(trip: dict[str, Any]) -> list[str]:
    """Readable stops in itinerary order, with outgoing transport when available."""
    outgoing = {
        s["properties"]["origin_id"]: s["properties"]["transport_mode"]
        for s in domain.parts(trip, "segment")
    }
    labels = []
    for stop in domain.parts(trip, "stop"):
        p = stop["properties"]
        label = str(p["name"])
        if p.get("arrival_date"):
            label += " · " + str(p["arrival_date"])
        if p["id"] in outgoing:
            label += " · onward: " + str(outgoing[p["id"]])
        labels.append(label)
    return labels


def view_stops(trip: dict[str, Any], *, step: int = 2) -> None:
    """Browse a bounded stop list; keep individual details out of the overview."""
    stops = domain.parts(trip, "stop")
    labels = stop_labels(trip)
    page = 0
    page_size = 5
    while True:
        screen(step)
        start = page * page_size
        end = min(start + page_size, len(stops))
        echo(f"Stops {start + 1}–{end} of {len(stops)} · {trip['metadata']['name']}")
        echo("Onward transport connects each stop to the next.")
        choices = [(str(i + 1), f"{i + 1}. {labels[i]}") for i in range(start, end)]
        if end < len(stops):
            choices.append(("next", "Next stops"))
        if page:
            choices.append(("previous", "Previous stops"))
        choices += [("back", "Back"), ("pause", "Save and exit")]
        answer = action_prompt("Select a stop for details", choices, default=str(start + 1))
        if answer == "back":
            return
        if answer == "pause":
            raise Navigation("pause")
        if answer == "next" and end < len(stops):
            page += 1
        elif answer == "previous" and page:
            page -= 1
        elif answer in {str(i + 1) for i in range(start, end)}:
            index = int(answer) - 1
            screen(step)
            stop = stops[index]
            p = stop["properties"]
            echo(f"{index + 1}. {p['name']}")
            if p.get("arrival_date"):
                echo("Arrival: " + str(p["arrival_date"]))
            if p.get("country") and p["country"] != "Unknown":
                echo("Country: " + str(p["country"]))
            if p.get("notes"):
                echo("Notes: " + str(p["notes"]))
            lon, lat = stop["geometry"]["coordinates"][:2]
            echo(f"Location: {lat:g}, {lon:g} (latitude, longitude)")
            if index + 1 < len(stops):
                echo("Next stop: " + str(stops[index + 1]["properties"]["name"]))
            choice = action_prompt(
                "Return to the stop list?",
                (
                    ("back", "Back to stops"),
                    ("pause", "Save and exit"),
                ),
                default="back",
            )
            if choice == "pause":
                raise Navigation("pause")


def import_interactively(root: Path, names: Sequence[str]) -> str:
    """Return true only after a validated itinerary has been explicitly accepted."""
    paths = plan_workspace(root)
    while True:
        selected = choose(names, "Which itinerary file should I import?") if len(names) > 1 else 0
        if selected is None:
            return "back"
        path = paths.input_dir / names[selected]
        content, candidates = domain.load(path)
        candidate = (
            choose(
                [t["metadata"]["name"] for t, _ in candidates],
                "This export contains separate candidate trips. Choose one:",
            )
            if len(candidates) > 1
            else 0
        )
        if candidate is None:
            continue
        trip, unsupported = candidates[candidate]
        if unsupported:
            echo("Unsupported placemarks: " + ", ".join(unsupported))
            echo(
                "The listed items cannot be imported. Import supported places to continue "
                "without them, or Save and exit to check your export."
            )
            if (
                action_prompt(
                    "Import available places?",
                    (("supported", "Import supported places"), ("pause", "Save and exit")),
                    default="pause",
                )
                .strip()
                .lower()
                != "supported"
            ):
                return "pause"
        key = domain.source_key(content, candidate)
        corrected = paths.metadata_dir / f"itinerary-{key}.geojson"
        if corrected.exists():
            trip = domain.load(corrected)[1][0][0]
            echo("Saved changes restored.", kind=MessageKind.SUCCESS)
        accepted = paths.metadata_dir / "itinerary.geojson"
        last_action = "accept"
        first_overview = True
        moving_stops = False
        while True:
            if not first_overview:
                restore_overview(2, str(root))
            first_overview = False
            if moving_stops:
                answer = "reorder"
            else:
                summary(trip)
                answer = (
                    action_prompt(
                        "Review your itinerary",
                        (
                            ("accept", "Accept and continue"),
                            ("inspect", "View stops and connections"),
                            ("reorder", "Reorder stops"),
                            ("mode", "Change transport"),
                            ("title", "Change title"),
                            ("dates", "Update stop dates"),
                            ("another", "Choose another file"),
                            ("help", "Help"),
                            ("back", "Back"),
                            ("pause", "Save and exit"),
                        ),
                        default=last_action,
                    )
                    .strip()
                    .lower()
                )
            last_action = answer
            if answer in ("pause", "back", "menu"):
                return str(answer)
            if answer == "another":
                break
            if answer == "inspect":
                view_stops(trip)
                screen(2)
                continue
            if answer == "help":
                echo("View stops shows your stops in order; select one for details.")
                echo(
                    "Choose Update stop dates to correct arrival dates; "
                    "poster settings are edited in config.toml."
                )
                emit()
                echo("Reorder uses every visit number once; mode changes one connection.")
                emit()
                echo(
                    "Edits are saved as you make them, separately from your original file. "
                    "Accept and continue uses this itinerary for the next steps and continues "
                    "to Map data."
                )
                wait_for_reading()
                continue
            if answer == "accept":
                domain.write_json(accepted, trip)
                domain.write_json(
                    paths.metadata_dir / "itinerary-source.json",
                    {
                        "schema_version": 1,
                        "filename": path.name,
                        "candidate": candidate,
                        "source_key": key,
                    },
                )
                echo("Itinerary accepted.", kind=MessageKind.SUCCESS)
                return "done"
            edited = correct_itinerary(trip, answer)
            if edited is None:
                moving_stops = False
                if answer == "reorder":
                    last_action = "accept"
                continue
            echo(
                f"{len(domain.route_keys(edited) - domain.route_keys(trip))} "
                "connections need updated routes after this correction."
            )
            domain.write_json(corrected, edited)
            trip = edited
            moving_stops = answer == "reorder"
            echo(
                "Stop move saved. Move another stop or choose Finish reordering."
                if moving_stops
                else (
                    "Itinerary edits saved. Choose Accept and continue "
                    "when your review is finished."
                ),
                kind=MessageKind.SUCCESS,
            )


def move_stop(trip: dict[str, Any]) -> dict[str, Any] | None:
    """Preview one confirmed move; the itinerary review saves it before offering another."""
    stops = domain.parts(trip, "stop")
    if len(stops) < 2:
        echo("At least two stops are needed to reorder your itinerary.")
        return None
    labels = [
        ui_text("Visit {number}: {label}").format(number=index + 1, label=label)
        for index, label in enumerate(stop_labels(trip))
    ]
    while True:
        echo("Choose a stop to move, or Finish reordering to return to itinerary review.")
        selected = choose(
            [*labels, ui_text("Finish reordering")], "Which stop would you like to move?"
        )
        if selected is None or selected == len(stops):
            return None
        moving = ui_text("visit {number} ({name})").format(
            number=selected + 1, name=stops[selected]["properties"]["name"]
        )
        while True:
            placement = action_prompt(
                ui_text("Where should {stop} go?").format(stop=moving),
                (
                    ("before", "Before another stop"),
                    ("after", "After another stop"),
                    ("start", "Move to start"),
                    ("end", "Move to end"),
                    ("back", "Back"),
                    ("pause", "Save and exit"),
                ),
                default="back",
            )
            if placement == "back":
                break
            if placement == "pause":
                raise Navigation("pause")
            if placement not in {"before", "after", "start", "end"}:
                echo("Choose a displayed move action.", kind=MessageKind.ERROR)
                continue
            order = [index + 1 for index in range(len(stops)) if index != selected]
            if placement in {"before", "after"}:
                target = choose(
                    [labels[index - 1] for index in order],
                    "Which stop should it be placed next to?",
                )
                if target is None:
                    continue
                target_number = order[target]
                destination = ui_text("visit {number} ({name})").format(
                    number=target_number, name=stops[target_number - 1]["properties"]["name"]
                )
                question = ui_text(
                    "Move {stop} before {target}?"
                    if placement == "before"
                    else "Move {stop} after {target}?"
                ).format(stop=moving, target=destination)
                position = target + int(placement == "after")
            else:
                position = 0 if placement == "start" else len(order)
                question = ui_text(
                    "Move {stop} to the start?"
                    if placement == "start"
                    else "Move {stop} to the end?"
                ).format(stop=moving)
            order.insert(position, selected + 1)
            if order == list(range(1, len(stops) + 1)):
                echo("This stop is already in that position.")
                continue
            edited = copy.deepcopy(trip)
            domain.reorder(edited, order)
            preview = domain.parts(edited, "stop")
            first, end = max(0, position - 1), min(len(preview), position + 2)
            echo("New order near the moved stop:")
            if first:
                echo("…")
            for index in range(first, end):
                echo(
                    f"{index + 1}. {preview[index]['properties']['name']}",
                    kind=MessageKind.SELECTED if index == position else MessageKind.INFO,
                )
            if end < len(preview):
                echo("…")
            echo(
                ui_text("Changed connections to check: {count}.").format(
                    count=len(domain.route_keys(edited) - domain.route_keys(trip))
                )
            )
            if confirm_action("move", question) == "move":
                return edited
            break


def correct_itinerary(trip: dict[str, Any], action: str) -> dict[str, Any] | None:
    """Retry an invalid correction at its prompt, leaving the original trip intact."""
    while True:
        edited = copy.deepcopy(trip)
        try:
            if action == "reorder":
                return move_stop(trip)
            elif action == "mode":
                segments = domain.parts(edited, "segment")
                number = choose(
                    [connection_label(trip, segment) for segment in segments], "Which connection?"
                )
                if number is None:
                    return None
                selected_mode = choose(domain.MODES, "Choose transport")
                if selected_mode is None:
                    continue
                segments[number]["properties"]["transport_mode"] = domain.MODES[selected_mode]
                segments[number]["properties"]["mode_assumed"] = False
            elif action == "dates":
                stops = domain.parts(edited, "stop")
                assessment = duration.assess(edited)
                issue_ids = set(
                    assessment.missing_ids + assessment.invalid_ids + assessment.order_ids
                )
                review_ids = set(duration.review_stop_ids(edited, assessment))
                visible = [
                    (index, stop)
                    for index, stop in enumerate(stops)
                    if str(stop["properties"]["id"]) in review_ids
                ]
                labels = []
                for index, stop in visible:
                    roles = []
                    if str(stop["properties"]["id"]) in issue_ids:
                        roles.append(ui_text("Faulty stop"))
                    else:
                        if (
                            index + 1 < len(stops)
                            and str(stops[index + 1]["properties"]["id"]) in issue_ids
                        ):
                            roles.append(ui_text("Previous stop"))
                        if index > 0 and str(stops[index - 1]["properties"]["id"]) in issue_ids:
                            roles.append(ui_text("Next stop"))
                    prefix = " / ".join(roles) + ": " if roles else ""
                    labels.append(
                        prefix
                        + str(stop["properties"]["name"])
                        + " · "
                        + str(stop["properties"].get("arrival_date") or ui_text("date missing"))
                    )
                if issue_ids:
                    echo("Showing stops with date warnings and their immediate neighbors.")
                highlighted = [
                    index
                    for index, (_, stop) in enumerate(visible)
                    if str(stop["properties"]["id"]) in issue_ids
                ]
                selected = choose(
                    labels,
                    "Choose a stop to update its arrival date:",
                    highlighted_indices=highlighted,
                )
                if selected is None:
                    return None
                return edit_stop_date(edited, visible[selected][1]["properties"]["id"])
            elif action == "title":
                echo("Current trip title: " + str(trip["metadata"]["name"]))
                title = edit_input("Trip title", default=str(trip["metadata"]["name"]))
                if title is None:
                    return None
                edited["metadata"]["name"] = title.strip()
                echo("The poster title is set separately in config.toml.")
            else:
                echo("Choose a displayed action.", kind=MessageKind.ERROR)
                return None
            domain.validate(edited)
            return edited
        except (ValueError, domain.ImportError) as exc:
            echo(exc, kind=MessageKind.ERROR)


def connection_label(trip: dict[str, Any], segment: dict[str, Any]) -> str:
    stops = {s["properties"]["id"]: s["properties"]["name"] for s in domain.parts(trip, "stop")}
    properties = segment["properties"]
    return (
        f"Connection {properties['sequence']}: {stops[properties['origin_id']]} → "
        f"{stops[properties['destination_id']]} ({properties['transport_mode']})"
    )


def edit_stop_coordinates(trip: dict[str, Any], stop_id: str) -> dict[str, Any] | None:
    """Edit one stop without changing the original itinerary or embedded route lines."""
    stop = next(s for s in domain.parts(trip, "stop") if s["properties"]["id"] == stop_id)
    lon, lat = stop["geometry"]["coordinates"][:2]
    echo(f"Stop: {stop['properties']['name']}")
    echo(f"Current latitude, longitude: {lat:g}, {lon:g}")
    echo("Enter decimal degrees as latitude, longitude. South and west use negative numbers.")
    echo("Only this stop changes; affected routes and map coverage will be checked again.")
    while True:
        raw = edit_input("New latitude, longitude (example: -54.85, -68.58)")
        if raw is None:
            return None
        try:
            values = raw.replace(",", " ").split()
            if len(values) != 2:
                raise ValueError("Enter exactly two numbers: latitude, longitude.")
            latitude, longitude = (float(value) for value in values)
            coordinates = domain.coordinate([longitude, latitude])
            edited = copy.deepcopy(trip)
            stops = {s["properties"]["id"]: s for s in domain.parts(edited, "stop")}
            # Generated straight connections follow corrected endpoints; imported lines stay intact.
            for segment in domain.parts(edited, "segment"):
                props = segment["properties"]
                endpoints = [
                    stops[props[key]]["geometry"]["coordinates"]
                    for key in ("origin_id", "destination_id")
                ]
                if (
                    stop_id in (props["origin_id"], props["destination_id"])
                    and segment["geometry"]["coordinates"] == endpoints
                ):
                    segment["geometry"]["coordinates"] = [
                        coordinates
                        if props[key] == stop_id
                        else stops[props[key]]["geometry"]["coordinates"]
                        for key in ("origin_id", "destination_id")
                    ]
            stops[stop_id]["geometry"]["coordinates"] = coordinates
            domain.validate(edited)
        except (ValueError, domain.ImportError) as exc:
            echo(str(exc), kind=MessageKind.ERROR)
            continue
        echo(f"New latitude, longitude: {latitude:g}, {longitude:g}")
        if confirm_action("save", "Save these stop coordinates") == "save":
            return edited
        return None


def edit_stop_date(trip: dict[str, Any], stop_id: str) -> dict[str, Any] | None:
    """Edit one arrival date on a copy, preserving routes and explicit duration overrides."""
    from datetime import date

    stop = next(s for s in domain.parts(trip, "stop") if s["properties"]["id"] == stop_id)
    echo(f"Stop: {stop['properties']['name']}")
    echo("Current arrival date: " + str(stop["properties"].get("arrival_date") or "missing"))
    echo("Enter YYYY-MM-DD, or clear to leave this date unavailable.")
    while True:
        raw = edit_input("Arrival date (YYYY-MM-DD), or clear")
        if raw is None:
            return None
        try:
            value = (
                None
                if raw.strip().lower() == "clear"
                else date.fromisoformat(raw.strip()).isoformat()
            )
        except ValueError:
            echo(
                "Enter a valid calendar date as YYYY-MM-DD, for example 2026-06-12.",
                kind=MessageKind.ERROR,
            )
            continue
        edited = copy.deepcopy(trip)
        selected = next(s for s in domain.parts(edited, "stop") if s["properties"]["id"] == stop_id)
        selected["properties"]["arrival_date"] = value
        domain.validate(edited)
        if confirm_action("save", "Save this arrival date") == "save":
            return edited
        return None


def save_accepted_correction(root: Path, trip: dict[str, Any]) -> None:
    """Persist the accepted correction and the copy restored on reimport."""
    from travelmap.mapdata import MIB, read_json

    domain.validate(trip)
    paths = plan_workspace(root)
    source = read_json(paths.metadata_dir / "itinerary-source.json", MIB)
    key = source.get("source_key")
    if (
        source.get("schema_version") != 1
        or not isinstance(key, str)
        or not re.fullmatch(r"[0-9a-f]{64}", key)
    ):
        raise domain.ImportError(
            "Invalid itinerary source metadata. Reimport and accept the itinerary first."
        )
    domain.write_json(paths.metadata_dir / f"itinerary-{key}.geojson", trip)
    domain.write_json(paths.metadata_dir / "itinerary.geojson", trip)
