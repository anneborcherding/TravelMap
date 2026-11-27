"""Shared prerequisite/readiness checks and truthful final export guidance."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer

from travelmap import itinerary, mapdata, poster_settings, render, routes
from travelmap.mapdata_guidance import accepted_trip
from travelmap.reporting import feedback_kind
from travelmap.shell_commands import ShellKind
from travelmap.terminal import (
    MessageKind,
    Navigation,
    action_prompt,
    edit_input,
    emit,
    inert_text,
    restore_overview,
    wait_for_reading,
    working,
)
from travelmap.terminal import (
    report_activity as activity,
)
from travelmap.workspace import plan_workspace


def echo(message: str, *, kind: MessageKind = MessageKind.INFO) -> None:
    emit(inert_text(message), kind=kind)


def source_current(root: Path) -> bool:
    paths = plan_workspace(root)
    path = paths.metadata_dir / "itinerary-source.json"
    if not path.exists():
        return accepted_trip(root) is not None
    try:
        raw = mapdata.read_json(path, mapdata.MIB)
        filename = raw["filename"]
        if not isinstance(filename, str) or Path(filename).name != filename:
            return False
        content = itinerary.read_bytes(paths.input_dir / filename)
        return bool(itinerary.source_key(content, raw["candidate"]) == raw["source_key"])
    except (ValueError, KeyError, TypeError):
        return False


def _sync_derived(path: Path, payload: dict[str, Any]) -> None:
    """Regenerate disposable settings metadata from the validated file when necessary."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"{path.name}: expected a regular local metadata file.")
    try:
        prior = mapdata.read_json(path, mapdata.MIB) if path.exists() else None
    except ValueError:
        prior = None
    if prior != payload:
        mapdata.atomic_json(path, payload)


def sync_settings(root: Path, current: dict[str, Any]) -> None:
    paths = plan_workspace(root)
    m = current["map"]
    routing = m["routing"]
    raw = {
        "schema_version": 1,
        "enabled": routing["enabled"],
        "api_key_env": routing["api_key_env"],
        "preference": routing["preference"],
        "avoid_features": routing["avoid_features"],
        "request_delay_s": routing["request_delay_s"],
        "profiles": routing["profiles"],
        "modes": routing["modes"],
        "direct_policy": routing["unreachable"],
        "cache": routing["cache"],
    }
    path = paths.metadata_dir / "routing-settings.json"
    _sync_derived(path, raw)
    data = {
        "schema_version": 1,
        "highway_classes": m["roads"]["highway_classes"],
        "water_line_classes": m["water"]["line_classes"],
        "water_area_classes": m["water"]["area_classes"],
        "enabled_layers": sorted(
            (["roads"] if m["roads"]["enabled"] else [])
            + (["water_lines", "water_areas"] if m["water"]["enabled"] else [])
        ),
    }
    map_path = paths.metadata_dir / "map-settings.json"
    data["country_ids"] = (
        m["boundaries"].get("country_ids") or m["boundaries"]["country_codes"] or []
    )
    data["include_admin1"] = m["show_state_borders"]
    configured = []
    for kind, key, layer_key in (
        ("countries", "country_path", "country_layer"),
        ("admin1", "admin1_path", "admin1_layer"),
    ):
        if m["boundaries"][key]:
            configured.append(
                {
                    "kind": kind,
                    "path": os.path.relpath(root / m["boundaries"][key], paths.map_data_dir),
                    "layer": m["boundaries"][layer_key],
                }
            )
    for kind, section, layer_key in (
        ("roads", "roads", "layer"),
        ("water_lines", "water", "line_layer"),
        ("water_areas", "water", "area_layer"),
    ):
        for value in m[section]["paths"]:
            configured.append(
                {
                    "kind": kind,
                    "path": os.path.relpath(root / value, paths.map_data_dir),
                    "layer": m[section][layer_key],
                }
            )
    data["vectors"] = configured + [
        {**source, "path": os.path.relpath(root / source["path"], paths.map_data_dir)}
        for source in m["sources"]
    ]
    # Explicit sources may supplement the same path with attribution; include each layer once.
    unique = {}
    for source in data["vectors"]:
        identity = (source["kind"], source["path"], source.get("layer"))
        unique[identity] = source
    data["vectors"] = list(unique.values())
    _sync_derived(map_path, data)


def preparation_current(
    root: Path,
    trip: dict[str, Any],
    resolved: dict[str, dict[str, Any]] | None = None,
    *,
    force: bool = False,
) -> bool:
    selected = mapdata.inspect_prepared(root)
    if not selected:
        return False
    settings = mapdata.settings_for(root)
    sources = mapdata.discover(root, settings)
    sources = mapdata.active_sources(sources, settings)
    if selected.get("schema_version") != 2:
        return False  # Readable old trip-cropped caches do not fulfill full-country readiness.
    if not set(settings["enabled_layers"]) <= set(
        selected.get("enabled_layers", ["roads", "water_lines", "water_areas"])
    ):
        return False
    if settings["country_ids"] and settings["country_ids"] != selected.get("country_ids"):
        return False
    fingerprints = [
        mapdata.source_fingerprint(source, settings, [-180, -90, 180, 90], activity, root, force)
        for source in sources
    ]
    # A broader prepared source remains usable; requested classes always stay file-authoritative.
    prepared_sources = [
        record
        for record in selected["sources"]
        if mapdata.active_sources([record["provenance"]["source"]], settings)
    ]
    remaining = list(prepared_sources)
    for key, provenance in fingerprints:
        for index, record in enumerate(remaining):
            prior = record["provenance"]
            if key == record.get("request_key", record["key"]) or (
                prior.get("version") == provenance.get("version")
                and prior.get("vector_identity_version")
                == provenance.get("vector_identity_version")
                and prior.get("source") == provenance.get("source")
                and prior.get("hashes") == provenance.get("hashes")
                and all(
                    set(values) <= set(prior.get("classes", {}).get(field, []))
                    for field, values in provenance["classes"].items()
                )
            ):
                remaining.pop(index)
                break
        else:
            return False
    if remaining:
        return False
    cache_root = plan_workspace(root).cache_dir / "map-data"
    for source_record in prepared_sources:
        directory = source_record.get("directory")
        source_key = source_record.get("key")
        if (
            not isinstance(directory, str)
            or Path(directory).name != directory
            or not isinstance(source_key, str)
        ):
            return False
        verified_source = mapdata.cached(cache_root / directory, source_key, activity)
        if (
            verified_source is None
            or verified_source.get("layers") != source_record.get("layers")
            or verified_source.get("database_sha256") != source_record.get("database_sha256")
        ):
            return False

    def source_labels(source: dict[str, Any]) -> tuple[str, str, str]:
        return (
            Path(source["path"]).name,
            str(source.get("attribution")),
            str(source.get("licence")),
        )

    source_matches = sorted(source_labels(source) for source in sources) == sorted(
        source_labels(r["provenance"]["source"]) for r in prepared_sources
    )
    if not source_matches:
        return False
    readiness_reused = False
    if resolved is not None and not force:
        from travelmap import validation_reuse

        try:
            settings_for_readiness = poster_settings.load(root, trip)
            readiness_input = validation_reuse.readiness_key(
                root, trip, resolved, settings_for_readiness, selected
            )
            readiness_reused = validation_reuse.readiness_result(root, readiness_input) is not None
        except (KeyError, TypeError, ValueError):
            readiness_reused = False
    if not readiness_reused:
        try:
            activity("Checking country boundaries and stop coverage.")
            mapdata.review_prepared_countries(root, trip, selected)
        except mapdata.MapDataError:
            return False
    return True


def route_readiness(
    root: Path, trip: dict[str, Any], resolved: dict[str, dict[str, Any]]
) -> list[str]:
    from shapely.geometry import LineString

    from travelmap import geography

    selected = mapdata.inspect_prepared(root)
    if not selected:
        return ["Required prepared map layers are absent/corrupt; recheck map data."]
    from travelmap import map_view, validation_reuse

    settings = poster_settings.load(root, trip)
    try:
        key = validation_reuse.readiness_key(root, trip, resolved, settings, selected)
    except (KeyError, TypeError, ValueError) as exc:
        return [f"Cannot validate current route and map readiness: {exc}"]
    cached = validation_reuse.readiness_result(root, key)
    if cached is not None:
        activity("Reusing successful route and map readiness checks.")
        echo(
            map_view.summary_from_metadata(
                {
                    "counts": cached["counts"],
                    "include_offshore_components": cached["include_offshore"],
                    "journey_expanded_frame": cached["journey_expanded_frame"],
                }
            )
        )
        if "unknown_coverage" in cached["warning_codes"]:
            echo(
                "Source coverage is unknown for one or more enabled background layers.",
                kind=MessageKind.WARNING,
            )
        return []
    receipt_snapshot = validation_reuse.receipt_snapshot(root)
    covered = geography.coverage_geometry(selected.get("coverage_envelopes", []))
    country_features = list(mapdata.iter_layer(root, selected, "countries"))
    display = mapdata.display_check(
        root, country_features, trip, resolved, settings, selected, activity
    )
    errors = list(display["coverage_errors"])
    echo(display["summary"])
    warning_codes = []
    if (
        settings["map"]["roads"]["enabled"] or settings["map"]["water"]["enabled"]
    ) and selected.get("coverage_check") == "unknown":
        warning_codes.append("unknown_coverage")
        echo(
            "Source coverage is unknown for one or more enabled background layers.",
            kind=MessageKind.WARNING,
        )
    activity("Checking route coverage.")
    for segment in itinerary.parts(trip, "segment"):
        record = resolved.get(routes.segment_key(trip, segment))
        if record is None:
            continue
        line = LineString(record["coordinates"])
        background_enabled = (
            settings["map"]["roads"]["enabled"] or settings["map"]["water"]["enabled"]
        )
        if (
            background_enabled
            and selected.get("coverage_check") != "unknown"
            and not geography.covered_by(covered, line)
        ):
            errors.append(
                f"Connection {segment['properties']['sequence']}: "
                f"route crosses an uncovered source envelope; download "
                f"neighboring regional extracts and recheck."
            )
    if not errors and receipt_snapshot is not None:
        if display.get("journey_expanded_frame"):
            warning_codes.append("journey_expands_frame")
        validation_reuse.save_readiness(
            root,
            key,
            {name: display["counts"][name] for name in ("included", "excluded", "trip")},
            display["include_offshore_components"],
            display["journey_expanded_frame"],
            warning_codes,
            lambda: validation_reuse.readiness_key(root, trip, resolved, settings, selected),
            expected_receipt=receipt_snapshot,
        )
    return errors


def route_extent_trip(trip: dict[str, Any], resolved: dict[str, dict[str, Any]]) -> dict[str, Any]:
    "Pass a separate framing extent; never alter user visit identities or normalized itinerary."
    coords = [c for record in resolved.values() for c in record["coordinates"]]
    bounds = mapdata.extent(trip)
    if coords:
        bounds = [
            max(-180, min(bounds[0], min(c[0] for c in coords) - 2)),
            max(-90, min(bounds[1], min(c[1] for c in coords) - 2)),
            min(180, max(bounds[2], max(c[0] for c in coords) + 2)),
            min(90, max(bounds[3], max(c[1] for c in coords) + 2)),
        ]
    return {"extent": bounds}


def default_stage(root: Path) -> str:
    paths = plan_workspace(root)
    saved = paths.metadata_dir / "flow-state.json"
    if saved.exists():
        try:
            value = mapdata.read_json(saved, mapdata.MIB).get("stage")
            if value in ("itinerary", "map-data", "manual-routes", "routing", "settings", "export"):
                return str(value)
        except ValueError:
            pass
    if not source_current(root):
        return "itinerary"
    trip = accepted_trip(root)
    if trip is None:
        return "itinerary"
    if not preparation_current(root, trip):
        return "map-data"
    if routes.resolve(root, trip)[1]:
        return "manual-routes"
    if not (paths.metadata_dir / "poster-settings.json").exists():
        return "settings"
    return "export"


def record_stage(root: Path, stage: str) -> None:
    mapdata.atomic_json(
        plan_workspace(root).metadata_dir / "flow-state.json", {"schema_version": 1, "stage": stage}
    )


def input_filename(folder: Path, question: str, *, must_be_new: bool = False) -> str | None:
    while True:
        echo("Output folder: " + str(folder))
        echo("Enter a filename such as my-trip.svg. Back cancels this edit.")
        answer = edit_input(question)
        if answer is None:
            return None
        name = answer.strip()
        if (
            Path(name).name != name
            or any(c in name for c in ("/", "\\", ":"))
            or Path(name).suffix.lower() != ".svg"
        ):
            echo(
                "Choose a plain .svg filename, for example my-trip.svg, without a folder path.",
                kind=MessageKind.ERROR,
            )
            continue
        if must_be_new and (folder / name).exists():
            echo(
                "That filename already exists. Choose a different name, or go Back.",
                kind=MessageKind.ERROR,
            )
            continue
        return name


@working()
def export_interactively(root: Path, trip: dict[str, Any], shell: ShellKind) -> str:
    echo("When the checks finish, you can export your poster as an editable SVG.")
    activity("Checking your routes, design and map data before export.")
    paths = plan_workspace(root)
    resolved, missing = routes.resolve(root, trip, activity)
    if missing:
        return "routing"
    current = poster_settings.load(root, trip)
    accepted = paths.metadata_dir / "settings-accepted.json"
    if not accepted.exists() or mapdata.read_json(accepted).get(
        "signature"
    ) != poster_settings.signature(current):
        echo("Poster settings require acceptance before export.", kind=MessageKind.WARNING)
        return "settings"
    sync_settings(root, current)
    with mapdata.verification_operation():
        if not preparation_current(root, trip, resolved):
            echo(
                "The map data needs updating for this country/layer selection. "
                "Returning to Map data.",
                kind=MessageKind.WARNING,
            )
            return "map-data"
        readiness_errors = route_readiness(root, trip, resolved)
        selected = mapdata.inspect_prepared(root)
    for error in readiness_errors:
        echo(error, kind=MessageKind.ERROR)
    if readiness_errors:
        return "map-data"
    if selected is None:
        return "map-data"
    from travelmap import validation_reuse

    readiness_input = validation_reuse.readiness_key(root, trip, resolved, current, selected)
    readiness_token = validation_reuse.readiness_token(root, readiness_input)
    preferences = paths.metadata_dir / "export-preferences.json"
    filename = "travel-map.svg"
    if preferences.exists():
        saved = mapdata.read_json(preferences, mapdata.MIB).get("filename")
        if isinstance(saved, str) and Path(saved).name == saved and saved.endswith(".svg"):
            filename = saved
    output = paths.output_dir / filename
    counts: dict[str, int] = {}
    for record in resolved.values():
        counts[record["source"]] = counts.get(record["source"], 0) + 1
    last_action = "export"
    first_overview = True
    while True:
        if not first_overview:
            restore_overview(7, str(root))
        first_overview = False
        page = current["poster"]
        echo(
            f"Ready to export {page['title']} ({page['width_mm']} × {page['height_mm']} "
            f"mm {page['orientation']})."
        )
        labels = {
            "direct": "straight-line routes",
            "provider": "service routes",
            "manual": "local routes",
            "embedded": "itinerary routes",
            "zero": "same-location connections",
        }
        echo("Current filename: " + output.name)
        echo(f"Output: {output}")
        echo(
            "Routes: " + ", ".join(f"{count} {labels[source]}" for source, count in counts.items())
        )
        _, warnings = poster_settings.metric_text(trip, resolved, current)
        for warning in warnings:
            echo(warning, kind=MessageKind(feedback_kind(warning).value))
        answer = (
            action_prompt(
                "Create your poster",
                (
                    ("export", "Export SVG"),
                    ("recheck", "Recheck routes and map data"),
                    ("filename", f"Change filename ({output.name})"),
                    ("distances", "View connection distances"),
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
        if answer in ("back", "menu", "pause"):
            return str(answer)
        if answer == "filename":
            name = input_filename(paths.output_dir, "SVG filename in the output folder")
            if name is not None:
                output = paths.output_dir / name
                mapdata.atomic_json(preferences, {"filename": name})
            continue
        if answer == "recheck":
            activity(
                "Rechecking map integrity, source freshness, country review and route coverage."
            )
            selection_path = paths.metadata_dir / "map-data.json"
            try:
                saved_selection = mapdata.read_json(selection_path, mapdata.MIB)
                store_names = [saved_selection["directory"]]
                store_names.extend(source["directory"] for source in saved_selection["sources"])
                source_settings = mapdata.settings_for(root)
                source_records = mapdata.active_sources(
                    mapdata.discover(root, source_settings), source_settings
                )
                source_paths = []
                for source in source_records:
                    source_path = Path(source["path"])
                    source_paths.append(source_path)
                    if source_path.suffix.lower() == ".shp":
                        source_paths.extend(
                            source_path.with_suffix(suffix) for suffix in (".shx", ".dbf", ".prj")
                        )
            except (OSError, ValueError, KeyError, TypeError):
                echo("Map selection needs repair before a full recheck.", kind=MessageKind.ERROR)
                return "map-data"
            if any(
                not isinstance(name, str) or Path(name).name != name for name in store_names
            ) or not validation_reuse.revoke_export_scope(root, store_names, source_paths):
                echo(
                    "Full recheck could not revoke prior successes; resolve the receipt lock "
                    "and retry.",
                    kind=MessageKind.ERROR,
                )
                return "export"
            with mapdata.verification_operation():
                selected = mapdata.inspect_prepared(root, activity, force=True)
                if selected is None:
                    echo(
                        "The full map recheck did not complete. Recheck Map data and retry.",
                        kind=MessageKind.ERROR,
                    )
                    return "map-data"
                if not preparation_current(root, trip, resolved, force=True):
                    echo(
                        "Map sources changed or need preparation. Returning to Map data.",
                        kind=MessageKind.WARNING,
                    )
                    return "map-data"
                readiness_errors = route_readiness(root, trip, resolved)
            for error in readiness_errors:
                echo(error, kind=MessageKind.ERROR)
            if readiness_errors:
                return "map-data"
            readiness_input = validation_reuse.readiness_key(
                root, trip, resolved, current, selected
            )
            readiness_token = validation_reuse.readiness_token(root, readiness_input)
            echo("Routes and map data were rechecked.", kind=MessageKind.SUCCESS)
            continue
        if answer == "distances":
            poster_settings.view_distances(trip, resolved, current)
            continue
        if answer == "help":
            echo(
                "Export writes an editable SVG with millimetre page size and named layers. All "
                "data is local; no routing request or download happens here."
            )
            emit()
            echo(
                "Open in a browser to view or Inkscape/Illustrator to edit; use that editor’s "
                "PDF export for printing."
            )
            emit()
            echo("Existing files require a new name or explicit replacement.")
            wait_for_reading()
            continue
        if answer != "export":
            echo("Choose a displayed action.", kind=MessageKind.ERROR)
            continue
        colors = current["style"]["route_colors"] or [current["style"]["route"]]
        completed: list[Path] = []
        existing_targets: set[Path] = set()
        try:
            with render.OutputBatch(paths.output_dir) as batch:
                for index, color in enumerate(colors, 1):
                    target = (
                        output
                        if len(colors) == 1
                        else output.with_name(output.stem + f"-{index}-{color[1:].lower()}.svg")
                    )
                    replace = False
                    if target.exists():
                        echo("Existing artwork: " + str(target))
                        choice = (
                            action_prompt(
                                "This file already exists",
                                (
                                    ("new", "Choose a new filename"),
                                    ("replace", "Replace the existing file"),
                                    ("back", "Back to export"),
                                    ("pause", "Save and exit"),
                                ),
                                default="new",
                            )
                            .strip()
                            .lower()
                        )
                        if choice == "new":
                            name = input_filename(
                                paths.output_dir, "New .svg filename", must_be_new=True
                            )
                            if name is None:
                                raise Navigation("back")
                            target = paths.output_dir / name
                            if len(colors) == 1:
                                output = target
                                mapdata.atomic_json(preferences, {"filename": name})
                        elif choice == "replace":
                            replace = True
                        elif choice == "back":
                            raise Navigation("back")
                        else:
                            if completed:
                                echo(
                                    "Partial run; earlier existing artwork is protected. "
                                    "Completed new posters: "
                                    + ", ".join(
                                        str(p) for p in completed if p not in existing_targets
                                    )
                                )
                            return "pause"
                    if len(colors) == 1:
                        activity(
                            "Exporting your poster; originals and prior artwork are protected."
                        )
                    else:
                        activity(
                            f"Exporting poster {index} of {len(colors)} (route color {color}); "
                            "originals and prior artwork are protected."
                        )
                    if replace:
                        batch.protect(target)
                        existing_targets.add(target)
                    warnings = render.export_svg(
                        target,
                        root,
                        trip,
                        resolved,
                        current,
                        selected,
                        color,
                        activity,
                        replace,
                        readiness_token,
                    )
                    completed.append(target)
                    for warning in warnings:
                        echo(warning, kind=MessageKind(feedback_kind(warning).value))
                mapdata.atomic_json(
                    paths.metadata_dir / "last-export.json",
                    {
                        "schema_version": 1,
                        "outputs": [str(p.relative_to(root)) for p in completed],
                        "settings_signature": poster_settings.signature(current),
                    },
                )
                batch.commit()
            record_stage(root, "export")
            break
        except Navigation as nav:
            if nav.action != "back":
                raise
            echo("Returned to export. Prior artwork is preserved.")
        except (ValueError, OSError) as exc:
            echo(str(exc), kind=MessageKind.ERROR)
            if completed:
                echo(
                    "Partial run only; prior artwork restored. Completed new posters: "
                    + ", ".join(str(p) for p in completed if p not in existing_targets)
                )
            echo("Retry uses existing valid routes/layers; no reacquisition is required.")

    restore_overview(7, str(root))
    echo("Export complete.", kind=MessageKind.SUCCESS)
    for path in completed:
        echo("SVG: " + str(path), kind=MessageKind.RESULT)
    while True:
        try:
            answer = action_prompt(
                "What would you like to do next?",
                (("close", "Close TravelMap"), ("back", "Back to Poster design")),
                default="close",
                preserve_order=True,
                instructions_first=True,
            )
        except (KeyboardInterrupt, typer.Abort):
            return "done"
        if answer in {"close", "/exit"}:
            return "done"
        if answer == "back":
            return "settings"
        echo("Choose Close TravelMap or Back to Poster design.", kind=MessageKind.WARNING)
