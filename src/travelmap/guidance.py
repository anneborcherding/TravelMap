"""Interactive instructions for collecting local trip inputs; never downloads or parses GIS."""

import os
import stat
from enum import StrEnum
from pathlib import Path

import typer

from travelmap.itinerary_guidance import import_interactively, view_stops
from travelmap.mapdata_guidance import (
    accepted_trip,
    choose_countries,
    prepare_interactively,
    show_status,
)
from travelmap.shell_commands import ShellKind, travelmap_command
from travelmap.terminal import (
    STEP_NAMES,
    MessageKind,
    Navigation,
    action_prompt,
    choose_number,
    emit,
    inert_text,
    restore_overview,
    screen,
    show_choice_prompt,
    wait_for_reading,
    working,
)
from travelmap.workspace import MAX_DIRECTORY_ENTRIES, WorkspaceError, plan_workspace

COUNTRIES_URL = (
    "https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/"
)
STATES_URL = (
    "https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-1-states-provinces/"
)
OSM_URL = "https://download.geofabrik.de/"
COUNTRIES_ZIP = "ne_10m_admin_0_countries.zip"
STATES_ZIP = "ne_10m_admin_1_states_provinces.zip"


class Step(StrEnum):
    """Stable names for choosing a starting point and safely resuming."""

    WORKSPACE = "workspace"
    ITINERARY = "itinerary"
    MAP_DATA = "map-data"
    ROUTING = "routing"
    MANUAL_ROUTES = "manual-routes"
    SETTINGS = "settings"
    EXPORT = "export"


STEPS = tuple(Step)
LABELS = (
    "Workspace — choose a folder for your trip",
    "Your itinerary — import and review your stops",
    "Map data — download the background map",
    "Routes — fill in missing journey routes",
    "Own routes — add recorded routes (optional)",
    "Poster design — choose the look of your map",
    "Export — create your SVG poster",
    "Save and exit",
)


def select_step(*, open_routes: bool = False) -> Step | None:
    """Keep invalid choices at the menu without selecting a hidden default."""

    choices = tuple(
        (step, label)
        for step, label in zip(STEPS, LABELS[:-1], strict=True)
        if step is not Step.MANUAL_ROUTES or open_routes
    )
    labels = tuple(label for _, label in choices) + (LABELS[-1],)
    screen()
    emit("Create a travel poster from your trip, one step at a time.")
    emit()
    emit("First time? Choose Workspace. We will guide you through the steps.")
    emit("Returning? Choose the step you want to revisit.")
    while True:
        answer = show_choice_prompt(
            "Where would you like to start?",
            labels,
            default=1,
            cancel_index=len(labels) - 1,
            cancel_label="Save and exit",
            pause_index=len(labels) - 1,
        )
        try:
            selection = choose_number(answer, len(labels), default=1)
        except ValueError as exc:
            emit(str(exc), kind=MessageKind.ERROR)
            continue
        return choices[selection - 1][0] if selection <= len(choices) else None


def _previous_step(step: Step) -> Step:
    if step is Step.SETTINGS:
        return Step.ROUTING
    return STEPS[max(0, STEPS.index(step) - 1)]


def _candidate_names(directory: Path) -> tuple[tuple[str, ...], bool]:
    """Bound an immediate directory scan and count only regular, non-redirected files."""

    names: list[str] = []
    try:
        folder_info = directory.lstat()
        if not stat.S_ISDIR(folder_info.st_mode) or (
            getattr(folder_info, "st_file_attributes", 0) & 0x400
        ):
            raise WorkspaceError(
                "The input location is no longer a regular workspace folder: "
                + inert_text(str(directory))
                + ". Restore the folder or select another workspace."
            )
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_DIRECTORY_ENTRIES:
                    return tuple(sorted(names)), True
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode) and not (
                    getattr(info, "st_file_attributes", 0) & 0x400
                ):
                    names.append(entry.name)
    except OSError as exc:
        raise WorkspaceError(
            f"Cannot check {inert_text(str(directory))}: {inert_text(str(exc))}. "
            "Check folder permissions, then retry."
        ) from exc
    return tuple(sorted(names)), False


def explain_step(root: Path, step: Step, *, detailed: bool = False) -> None:
    """Print a complete task, exact destination and source links for the selected stage."""

    paths = plan_workspace(root)
    if step is Step.ITINERARY:
        emit("Export your trip as a KML file, or use a file you already exported.")
        emit()
        emit("Copy the .kml file into:")
        emit(inert_text(str(paths.input_dir)))
        if detailed:
            emit()
            emit("In your trip app, choose Export or Download, then KML.")
            emit("Use a .kml file, not a compressed .kmz. Keep the original as a backup.")
            emit()
            emit("Review the stops and transport modes before choosing Accept and continue.")
    elif step is Step.MAP_DATA:
        emit("Add country boundaries and regional roads/water, or reuse your existing downloads.")
        if not detailed:
            emit("Open Help for download links and instructions.")
        emit("Continue checks for changes. Recheck map data repeats full validation (optional).")
        emit()
        emit("Copy the downloads into:")
        emit(inert_text(str(paths.map_data_dir)))
        if detailed:
            emit()
            emit("Country boundaries (required):")
            emit(COUNTRIES_URL)
            emit("Download countries. Keep the ZIP intact: " + COUNTRIES_ZIP)
            emit()
            emit("Roads and water (required):")
            emit(OSM_URL)
            emit("Choose each country or region crossed by your trip.")
            emit("Download the .osm.pbf files, including regions between stops.")
            emit()
            emit("State/province borders (optional):")
            emit(STATES_URL)
            emit("Download states and provinces (polygons). Keep the ZIP intact.")
            emit("Use country/regional extracts; large continent files are unsupported.")
            emit()
            show_status(root)
    else:
        emit("Optional: copy GeoJSON route files into:")
        emit(inert_text(str(paths.manual_routes_dir)))
    if detailed:
        emit()
        emit(
            "Leave this terminal open while you copy files. "
            "Choose Continue when the files are in place."
        )


def check_files(root: Path, step: Step) -> bool:
    """Check presence only; never promote candidates to validated itineraries or map layers."""

    paths = plan_workspace(root)
    directory = {
        Step.ITINERARY: paths.input_dir,
        Step.MAP_DATA: paths.map_data_dir,
        Step.MANUAL_ROUTES: paths.manual_routes_dir,
    }[step]
    names, truncated = _candidate_names(directory)
    lowered = {name.lower() for name in names}
    if step is Step.ITINERARY:
        matches = tuple(
            name for name in names if name.lower().endswith((".kml", ".geojson", ".json"))
        )
        missing = [] if matches else ["an itinerary file ending in .kml"]
    elif step is Step.MAP_DATA:
        matches = tuple(name for name in names if name.lower().endswith((".osm.pbf", ".zip")))
        missing = [] if COUNTRIES_ZIP in lowered else [COUNTRIES_ZIP]
        if not any(name.lower().endswith(".osm.pbf") for name in names):
            missing.append("at least one country/subcountry .osm.pbf extract")
    else:
        matches = tuple(name for name in names if name.lower().endswith((".geojson", ".json")))
        missing = [] if matches else ["a .geojson or GeoJSON .json route file (or type 'skip')"]
    if step is not Step.ITINERARY:
        emit("Checked folder: " + inert_text(str(directory)))
        for name in matches[:5]:
            emit("Located: " + inert_text(name), kind=MessageKind.ACTIVITY)
    if truncated:
        emit(
            "Scan incomplete: only the first 1,000 entries were checked. Use a smaller "
            "folder for this trip; files not observed cannot be counted as present.",
            kind=MessageKind.WARNING,
        )
        return False
    if missing:
        emit("Still needed: " + "; ".join(missing), kind=MessageKind.WARNING)
        emit("Copy these files into the folder above, then choose Continue.")
        return False
    if step is not Step.ITINERARY:
        emit(
            "Files located. This is a filename check; their contents, formats, trip meaning "
            "and map coverage have not been validated."
        )
    return True


def print_resume(root: Path, step: Step, shell: ShellKind) -> None:
    command = travelmap_command(
        (
            "-m",
            "travelmap",
            "run",
            "--path",
            str(root),
            "--start-at",
            step.value,
            "--shell",
            shell.value,
        ),
        shell,
    )
    emit("Resume this step: " + command)


def _pause(root: Path, step: Step, shell: ShellKind) -> None:
    """Exit neutrally, confirming saved progress only after the stage note is written."""
    from travelmap import flow

    emit("Paused. Validated progress and originals are preserved.")
    try:
        flow.record_stage(root, step.value)
    except (ValueError, OSError):
        emit(
            "Stage note could not be saved; use the resume command "
            "below. Validated prior results remain.",
            kind=MessageKind.WARNING,
        )
    else:
        emit("Progress saved. You can resume this step later.", kind=MessageKind.RESULT)
    print_resume(root, step, shell)


@working()
def run_guidance(root: Path, start: Step, shell: ShellKind) -> bool:
    """Integrate validated domains while preserving local recovery and exact-stage resume."""
    from travelmap import flow, poster_settings, routes
    from travelmap.manual_routes import run_manual
    from travelmap.routing_guidance import run_routing

    step: Step = Step.ITINERARY if start is Step.WORKSPACE else start
    completion = "Workspace ready." if start is Step.WORKSPACE else ""
    redirected = False
    try:
        while True:
            try:
                notice = ""
                trip = accepted_trip(root)
                if trip is not None:
                    flow.sync_settings(root, poster_settings.load(root, trip))
                if step is not Step.ITINERARY and (trip is None or not flow.source_current(root)):
                    notice = "Your itinerary needs review. Returning to Your itinerary."
                    step = Step.ITINERARY
                if step in (Step.MANUAL_ROUTES, Step.SETTINGS, Step.EXPORT) and trip is not None:
                    resolved, missing = routes.resolve(root, trip)
                    if step is Step.MANUAL_ROUTES:
                        if not missing:
                            step = Step.SETTINGS
                    elif missing:
                        notice = "Some routes are missing. Returning to Routes."
                        step = Step.ROUTING
                flow.record_stage(root, step.value)
                if redirected:
                    restore_overview(STEPS.index(step) + 1, str(root))
                    redirected = False
                else:
                    screen(STEPS.index(step) + 1, workspace=str(root))
                if completion:
                    emit(completion, kind=MessageKind.SUCCESS)
                    completion = ""
                    emit()
                if notice:
                    emit(notice, kind=MessageKind.WARNING)
                if step in (Step.ITINERARY, Step.MAP_DATA):
                    first_overview = True
                    while True:
                        if not first_overview:
                            restore_overview(STEPS.index(step) + 1, str(root))
                        first_overview = False
                        explain_step(root, step)
                        answer = action_prompt(
                            "Choose Continue to check your map files."
                            if step is Step.MAP_DATA
                            else "Choose Continue to select and review your itinerary.",
                            (
                                ("done", "Continue"),
                                *(
                                    (("recheck", "Recheck map data"),)
                                    if step is Step.MAP_DATA
                                    else ()
                                ),
                                *((("stops", "View trip stops"),) if step is Step.MAP_DATA else ()),
                                *(
                                    (("countries", "Displayed countries"),)
                                    if step is Step.MAP_DATA
                                    else ()
                                ),
                                ("help", "Help"),
                                ("back", "Back"),
                                ("pause", "Save and exit"),
                            ),
                            default="done",
                            instructions_first=True,
                        )
                        if answer in {"done", "recheck"}:
                            try:
                                if step is Step.MAP_DATA:
                                    prepared = (
                                        prepare_interactively(root, force=True)
                                        if answer == "recheck"
                                        else prepare_interactively(root)
                                    )
                                    if prepared is None:
                                        continue
                                    answer = "done" if prepared else "pause"
                                    break
                                if check_files(root, step):
                                    names, _ = _candidate_names(plan_workspace(root).input_dir)
                                    candidates = tuple(
                                        n
                                        for n in names
                                        if n.lower().endswith((".kml", ".geojson", ".json"))
                                    )
                                    answer = import_interactively(root, candidates)
                                    break
                            except (WorkspaceError, ValueError, OSError) as exc:
                                emit(inert_text(str(exc)), kind=MessageKind.ERROR)
                        elif answer == "countries" and step is Step.MAP_DATA:
                            try:
                                choose_countries(root)
                            except (ValueError, OSError) as exc:
                                emit(inert_text(str(exc)), kind=MessageKind.ERROR)
                        elif answer == "stops" and step is Step.MAP_DATA:
                            assert trip is not None
                            view_stops(trip, step=3)
                        elif answer == "help":
                            screen(STEPS.index(step) + 1, workspace=str(root))
                            explain_step(root, step, detailed=True)
                            wait_for_reading()
                        elif answer in {"back", "menu", "pause", "quit", "exit"}:
                            break
                        else:
                            emit("Choose Continue, Help, Back, or Save and exit.")
                elif step is Step.MANUAL_ROUTES:
                    assert trip is not None
                    answer = run_manual(root, trip)
                    if answer == "skip":
                        answer = "done"
                elif step is Step.ROUTING:
                    assert trip is not None
                    answer = run_routing(root, trip)
                elif step is Step.SETTINGS:
                    assert trip is not None
                    answer = poster_settings.run_settings(root, trip, resolved)
                    if answer == "done":
                        flow.sync_settings(root, poster_settings.load(root, trip))
                        if routes.resolve(root, trip)[1]:
                            answer = "routing"
                else:
                    assert trip is not None
                    answer = flow.export_interactively(root, trip, shell)
                    if answer == "done":
                        return False
                if answer in {"pause", "quit", "exit"}:
                    _pause(root, step, shell)
                    return False
                if answer in {"back", "menu"}:
                    selected = (
                        _previous_step(step)
                        if answer == "back"
                        else select_step(
                            open_routes=trip is not None
                            and flow.source_current(root)
                            and bool(routes.resolve(root, trip)[1])
                        )
                    )
                    if selected is None:
                        print_resume(root, step, shell)
                        return False
                    if selected is Step.WORKSPACE:
                        return True
                    step = selected
                elif answer in {"map-data", "routing", "settings"}:
                    redirected = True
                    step = Step(answer)
                else:
                    completion = (
                        ""
                        if step is Step.MANUAL_ROUTES
                        else STEP_NAMES[STEPS.index(step)] + " complete."
                    )
                    redirected = True
                    step = STEPS[STEPS.index(step) + 1]
            except Navigation as nav:
                if nav.action == "back":
                    if step is Step.ITINERARY:
                        return True
                    step = _previous_step(step)
                    flow.record_stage(root, step.value)
                else:
                    _pause(root, step, shell)
                    return False
            except (WorkspaceError, ValueError, OSError) as exc:
                emit(inert_text(str(exc)), kind=MessageKind.ERROR)
                answer = action_prompt(
                    "What would you like to do?",
                    (
                        ("recheck", "Try again"),
                        ("menu", "Choose a step"),
                        ("pause", "Save and exit"),
                    ),
                    default="recheck",
                )
                if answer == "menu":
                    selected = select_step()
                    if selected is Step.WORKSPACE:
                        return True
                    if selected is not None:
                        step = selected
                elif answer != "recheck":
                    print_resume(root, step, shell)
                    return False
    except (KeyboardInterrupt, typer.Abort):
        _pause(root, step, shell)
        raise typer.Exit(130) from None
