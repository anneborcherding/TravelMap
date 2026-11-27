"""Bounded ordinary GeoJSON route candidates and explicit local assignment guidance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from travelmap import itinerary, routes
from travelmap.itinerary_guidance import choose
from travelmap.mapdata import atomic_json
from travelmap.terminal import (
    MessageKind,
    action_prompt,
    confirm_action,
    emit,
    inert_text,
    restore_overview,
    wait_for_reading,
)
from travelmap.workspace import plan_workspace


def echo(value: str, *, kind: MessageKind = MessageKind.INFO) -> None:
    emit(inert_text(value), kind=kind)


def candidates(path: Path) -> tuple[bytes, list[dict[str, Any]], int]:
    content = itinerary.read_bytes(path)
    try:
        raw = itinerary.decode_json(content)
        if not isinstance(raw, dict):
            raise routes.RouteError("Expected a GeoJSON object.")
        crs = raw.get("crs")
        if crs is not None and (
            not isinstance(crs, dict)
            or not isinstance(crs.get("properties"), dict)
            or crs.get("properties", {}).get("name")
            not in ("EPSG:4326", "urn:ogc:def:crs:OGC:1.3:CRS84", "urn:ogc:def:crs:EPSG::4326")
        ):
            raise routes.RouteError(
                "Unsupported CRS. Re-export WGS84 longitude/latitude GeoJSON; "
                "do not swap coordinate order."
            )
        features = (
            raw.get("features")
            if raw.get("type") == "FeatureCollection"
            else [raw]
            if raw.get("type") == "Feature"
            else [{"type": "Feature", "geometry": raw, "properties": {}}]
        )
        if not isinstance(features, list) or not 1 <= len(features) <= routes.MAX_RECORDS:
            raise routes.RouteError(
                "Expected 1–1,000 route/marker features. Export a smaller collection."
            )
        result = []
        markers = vertices = 0
        identities = set()
        metadata = raw.get("metadata", {})
        query = metadata.get("query", {}) if isinstance(metadata, dict) else {}
        units = query.get("units") if isinstance(query, dict) else None
        if (
            units is None
            and isinstance(metadata, dict)
            and isinstance(metadata.get("engine"), dict)
            and metadata.get("service") == "routing"
        ):
            units = "m"  # OpenRouteService's documented default units for a recognized response.
        for index, feature in enumerate(features, 1):
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise routes.RouteError(f"Feature {index}: expected GeoJSON Feature.")
            geom, props = feature.get("geometry"), feature.get("properties") or {}
            if not isinstance(geom, dict) or not isinstance(props, dict):
                raise routes.RouteError(f"Feature {index}: missing geometry/properties.")
            if geom.get("type") == "Point":
                itinerary.coordinate(geom.get("coordinates"))
                markers += 1
                continue
            if geom.get("type") != "LineString":
                raise routes.RouteError(
                    f"Feature {index}: unsupported {geom.get('type')!r}; "
                    f"export separate LineStrings."
                )
            coordinates = routes.line(geom.get("coordinates"))
            vertices += len(coordinates)
            if vertices > routes.MAX_TOTAL_VERTICES:
                raise routes.RouteError(
                    "More than 500,000 route vertices. Export a smaller/simpler collection."
                )
            identity = tuple(props.get(k) for k in ("sequence", "origin", "destination", "mode"))
            if all(isinstance(v, (str, int)) for v in identity):
                if identity in identities:
                    raise routes.RouteError(
                        "Duplicate cache records. Choose a collection with unique segment records."
                    )
                identities.add(identity)
            distance = routes.metric(props.get("distance_m"))
            duration = routes.metric(props.get("duration_s"))
            summary = props.get("summary", {})
            if isinstance(summary, dict) and units in ("m", "km", "mi"):
                value = routes.metric(summary.get("distance"))
                distance = (
                    value * {"m": 1, "km": 1000, "mi": 1609.344}[units]
                    if value is not None
                    else None
                )
                distance = routes.metric(distance)
                duration = routes.metric(summary.get("duration"))
            result.append(
                {
                    "label": str(props.get("name") or f"Line {index}"),
                    "coordinates": coordinates,
                    "distance_m": distance,
                    "duration_s": duration,
                    "sequence": props.get("sequence")
                    if isinstance(props.get("sequence"), int)
                    and not isinstance(props.get("sequence"), bool)
                    else None,
                    "mode": props.get("mode") if props.get("mode") in itinerary.MODES else None,
                    "origin": props.get("origin") or props.get("origin_id"),
                    "destination": props.get("destination") or props.get("destination_id"),
                    "profile": props.get("profile")
                    if props.get("profile") in routes.PROFILES
                    else None,
                }
            )
        if not result:
            raise routes.RouteError(
                "No LineString routes found. Export a line route, not only point markers."
            )
        return content, result, markers
    except (ValueError, TypeError, KeyError) as exc:
        raise routes.RouteError(
            f"{path.name}: invalid route export: {exc}. Re-export "
            f"a supported local file and recheck."
        ) from exc


def matches(
    trip: dict[str, Any], segment: dict[str, Any], coordinates: list[list[float]]
) -> str | None:
    left, right = routes.endpoints(trip, segment)
    if (
        max(routes.metres(left, coordinates[0]), routes.metres(right, coordinates[-1]))
        <= routes.ENDPOINT_TOLERANCE_M
    ):
        return "forward"
    if (
        max(routes.metres(left, coordinates[-1]), routes.metres(right, coordinates[0]))
        <= routes.ENDPOINT_TOLERANCE_M
    ):
        return "reverse"
    return None


def names_for(trip: dict[str, Any], segment: dict[str, Any]) -> str:
    stops = {s["properties"]["id"]: s["properties"]["name"] for s in itinerary.parts(trip, "stop")}
    p = segment["properties"]
    return (
        f"Connection {p['sequence']}: {stops[p['origin_id']]} "
        f"-> {stops[p['destination_id']]} ({p['transport_mode']})"
    )


def save_assignment(
    root: Path,
    trip: dict[str, Any],
    segment: dict[str, Any],
    candidate: dict[str, Any],
    source_file: str,
    source_hash: str,
    source_candidate: int,
    reverse: bool,
) -> None:
    coordinates = list(reversed(candidate["coordinates"])) if reverse else candidate["coordinates"]
    record = routes.record_for(
        trip,
        segment,
        coordinates,
        "manual",
        candidate.get("profile"),
        candidate.get("distance_m"),
        candidate.get("duration_s"),
        source_file=source_file,
        source_hash=source_hash,
        source_candidate=source_candidate,
    )
    raw = routes.load_assignments(root)
    raw["assignments"][routes.segment_key(trip, segment)] = record
    if len(json.dumps(raw, ensure_ascii=False).encode()) > routes.MAX_BYTES:
        raise routes.RouteError(
            "Assignments exceed 8 MiB. Use simpler routes; prior assignments are preserved."
        )
    atomic_json(plan_workspace(root).metadata_dir / "manual-assignments.json", raw)


def remove_assignment(root: Path, trip: dict[str, Any], segment: dict[str, Any]) -> None:
    raw = routes.load_assignments(root)
    raw["assignments"].pop(routes.segment_key(trip, segment), None)
    atomic_json(plan_workspace(root).metadata_dir / "manual-assignments.json", raw)


def run_manual(root: Path, trip: dict[str, Any], *, step: int = 5) -> str:
    """Offer optional file/embedded assignment; commit each confirmation."""
    paths = plan_workspace(root)
    first_overview = True
    while True:
        resolution_notes: list[str] = []
        resolved, missing = routes.resolve(root, trip, resolution_notes.append)
        if not missing:
            return "done"
        if not first_overview:
            restore_overview(step, str(root))
        first_overview = False
        echo("Add your own routes")
        echo("Choose Continue to keep the current routes.")
        for note in resolution_notes:
            echo(note, kind=MessageKind.WARNING)
        echo(
            f"Routes: {len(itinerary.parts(trip, 'segment'))} total, "
            f"{len(resolved)} ready, {len(missing)} open."
        )
        echo("Use your own files for missing routes, or return to Routes to review other options.")
        for segment in missing:
            echo(f"{names_for(trip, segment)}: needs a route")
        echo("Export your route lines as GeoJSON (.geojson or .json).")
        echo("Export/copy route files into: " + str(paths.manual_routes_dir))
        answer = (
            action_prompt(
                "Add your own routes?",
                (
                    ("skip", "Continue"),
                    ("recheck", "Choose a route file"),
                    ("embedded", "Use a line from the itinerary"),
                    ("remove", "Remove an assignment"),
                    ("help", "Help"),
                    ("back", "Back"),
                    ("pause", "Save and exit"),
                ),
                default="skip",
            )
            .strip()
            .lower()
        )
        if answer in ("done", "skip", "pause", "back", "menu"):
            return str(answer)
        if answer == "help":
            echo("A journey route is the line you travelled, separate from background roads.")
            emit()
            echo(
                "Export WGS84 GeoJSON from your recorder or route planner, copy it into the "
                "folder above, then choose Choose a route file."
            )
            emit()
            echo(
                "Each line and named connection are selected explicitly; originals are "
                "preserved. Missing distance can be overridden later."
            )
            wait_for_reading()
            continue
        if answer == "remove":
            segments = itinerary.parts(trip, "segment")
            if not segments:
                echo("Single-stop trip has no connection assignments.")
                continue
            selected = choose(
                [names_for(trip, s) for s in segments], "Which manual assignment should be removed?"
            )
            if selected is None:
                continue
            echo("Removing this assignment restores any available itinerary or saved route.")
            if confirm_action("remove", "Remove this assignment").strip().lower() == "remove":
                remove_assignment(root, trip, segments[selected])
            continue
        if answer not in ("recheck", "done", "embedded"):
            echo("Choose one of the displayed actions.", kind=MessageKind.ERROR)
            continue
        try:
            if answer == "embedded":
                embedded = itinerary.parts(trip, "unassigned")
                if not embedded:
                    echo("No unassigned itinerary lines are available.")
                    continue
                options: list[dict[str, Any]] = [
                    {
                        "label": str(f["properties"].get("name") or f"Embedded line {i + 1}"),
                        "coordinates": routes.line(f["geometry"]["coordinates"]),
                        "distance_m": None,
                        "duration_s": None,
                    }
                    for i, f in enumerate(embedded)
                ]
                source_file = "@itinerary"
            else:
                from travelmap.guidance import _candidate_names

                names, truncated = _candidate_names(paths.manual_routes_dir)
                if truncated:
                    raise routes.RouteError(
                        "Route folder scan incomplete. Use a smaller folder and recheck."
                    )
                files = [
                    paths.manual_routes_dir / n
                    for n in names
                    if n.lower().endswith((".geojson", ".json"))
                ]
                from travelmap.poster_settings import load as load_settings

                advanced = load_settings(root, trip)["map"]["routing"]["cache"]
                if advanced:
                    configured = root / advanced
                    if configured not in files:
                        if not configured.is_file():
                            echo(
                                "Configured advanced route cache is missing: "
                                + str(configured)
                                + (
                                    ". Copy it here, choose another path in the optional "
                                    "config, or use ordinary manual-route files."
                                )
                            )
                        else:
                            files.append(configured)
                if not files:
                    echo(
                        "No route files yet. Copy a .geojson/.json route into "
                        + str(paths.manual_routes_dir)
                        + ", then choose Choose a route file; or Continue / Save and exit."
                    )
                    continue
                selected = choose([str(p.relative_to(root)) for p in files], "Choose a route file:")
                if selected is None:
                    continue
                path = files[selected]
                content, options, markers = candidates(path)
                source_file = path.relative_to(root).as_posix()
                source_hash = hashlib.sha256(content).hexdigest()
                if markers:
                    echo(
                        f"{markers} validated Point markers are not route "
                        f"lines; {len(options)} line candidates retained "
                        f"separately."
                    )
            selected = choose(
                [
                    (
                        f"{o['label']}: {o['coordinates'][0]} -> {o['coordinates'][-1]}, "
                        f"{len(o['coordinates'])} vertices"
                    )
                    for o in options
                ],
                "Choose one route line:",
            )
            if selected is None:
                continue
            candidate = options[selected]
            if source_file == "@itinerary":
                source_hash = hashlib.sha256(
                    json.dumps(candidate["coordinates"], sort_keys=True).encode()
                ).hexdigest()
            segments = [
                s
                for s in itinerary.parts(trip, "segment")
                if matches(trip, s, candidate["coordinates"])
            ]
            if not segments:
                raise routes.RouteError(
                    "This line has no plausible itinerary endpoints within 5 "
                    "km. Choose another file/line or export the correct route; "
                    "no assignment changed."
                )
            chosen = choose(
                [
                    names_for(trip, s)
                    + " — "
                    + str(matches(trip, s, candidate["coordinates"]))
                    + (
                        "; explicit metadata matches"
                        if candidate.get("origin") == s["properties"]["origin_id"]
                        and candidate.get("destination") == s["properties"]["destination_id"]
                        else ""
                    )
                    for s in segments
                ],
                ("Select the named journey. Ambiguous matches are never assigned automatically:"),
            )
            if chosen is None:
                continue
            segment = segments[chosen]
            reverse = matches(trip, segment, candidate["coordinates"]) == "reverse"
            if reverse:
                echo("This line runs in reverse. Reverse the imported copy to match your journey.")
                if (
                    confirm_action("reverse", "Reverse the imported line").strip().lower()
                    != "reverse"
                ):
                    continue
            resolved, _ = routes.resolve(
                root, trip, lambda message: echo(message, kind=MessageKind.WARNING)
            )
            prior = resolved.get(routes.segment_key(trip, segment), {}).get("source", "unresolved")
            echo(
                f"Assign {source_file} / {candidate['label']} to "
                f"{names_for(trip, segment)}; prior source: {prior}. "
                f"Manual geometry takes precedence; poster/distance "
                f"refresh, unrelated routes remain. Distance: {candidate.get('distance_m')} "
                f"metres (None means unknown)."
            )
            if (
                confirm_action("assign", "Assign this line to the connection").strip().lower()
                != "assign"
            ):
                continue
            save_assignment(
                root, trip, segment, candidate, source_file, source_hash, selected, reverse
            )
            echo("Route assignment saved.", kind=MessageKind.SUCCESS)
        except (ValueError, OSError) as exc:
            echo(str(exc), kind=MessageKind.ERROR)
