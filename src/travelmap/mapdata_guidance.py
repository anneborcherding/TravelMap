"""File-configured map preparation, read-only country review, and trip-data recovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from travelmap import itinerary, mapdata
from travelmap.terminal import MessageKind, action_prompt, emit, inert_text, working
from travelmap.terminal import report_activity as activity
from travelmap.workspace import plan_workspace


def echo(message: str, *, kind: MessageKind = MessageKind.INFO) -> None:
    emit(inert_text(message), kind=kind)


def accepted_trip(root: Path) -> dict[str, Any] | None:
    path = plan_workspace(root).metadata_dir / "itinerary.geojson"
    if not path.exists():
        return None
    return itinerary.load(path)[1][0][0]


def show_status(root: Path) -> None:
    activity("Checking saved map layers.")
    current = mapdata.inspect_prepared(root, activity)
    if current:
        echo("Saved map layers from the previous preparation; current files will be rechecked:")
        for name, info in current["layers"].items():
            echo(f"{name}: {info['count']} cached features.")
        names = sorted(
            {name for values in current.get("stop_countries", {}).values() for name in values}
        )
        if names:
            emit()
            echo("Countries covering stops in the previous preparation: " + ", ".join(names))
    else:
        echo("No validated prepared map layers are currently available.")
    trip = accepted_trip(root)
    if trip:
        emit()
        stops = itinerary.parts(trip, "stop")
        countries = sorted(
            {s["properties"]["country"] for s in stops if s["properties"]["country"] != "Unknown"}
        )
        if countries:
            echo("Start with country/subcountry extracts for: " + ", ".join(countries))
        echo(f"Your trip has {len(stops)} stops. Choose View trip stops to see them.")
    emit()
    echo(
        "Default design requires country boundaries, background roads "
        "and water. State/province boundaries are optional. Journey "
        "routes are prepared separately."
    )
    echo(
        "The poster shows complete selected countries, including unvisited regions. "
        "Choose Displayed countries to review their IDs after adding country boundaries; "
        "extra downloads do not add countries to the view."
    )
    emit()
    echo(
        "Stops alone cannot prove coverage between them. Include "
        "neighboring regions crossed by the trip; coverage must be "
        "checked again after routes are resolved."
    )


@working()
def prepare_interactively(root: Path, *, force: bool = False) -> bool | None:
    from travelmap.itinerary_guidance import edit_stop_coordinates, save_accepted_correction

    activity(
        "Rechecking map file contents and prepared layers."
        if force
        else "Checking map files and settings."
    )
    trip = accepted_trip(root)
    if trip is not None:
        from travelmap import flow, poster_settings

        flow.sync_settings(root, poster_settings.load(root, trip))
    if not force and trip is not None and mapdata.preparation_unchanged(root, trip):
        echo(
            "Map files and settings are unchanged; reusing prepared map data.",
            kind=MessageKind.SUCCESS,
        )
        echo("Choose Recheck map data to run full validation again.")
        return True
    while True:
        try:
            return (
                _prepare_interactively(root, force=True) if force else _prepare_interactively(root)
            )
        except mapdata.CountryCoverageError as exc:
            echo(str(exc), kind=MessageKind.ERROR)
            trip = accepted_trip(root)
            if trip is None:
                raise
            stop = next(
                s for s in itinerary.parts(trip, "stop") if s["properties"]["id"] == exc.stop_id
            )
            lon, lat = stop["geometry"]["coordinates"][:2]
            echo(f"Stop coordinates: latitude {lat:g}, longitude {lon:g}.")
            answer = action_prompt(
                "How would you like to resolve this uncovered stop?",
                (
                    ("keep", "Keep this stop as entered"),
                    ("coordinates", "Correct this stop's coordinates"),
                    ("countries", "Review displayed countries"),
                    ("files", "Add or replace country boundary files"),
                    ("retry", "Check country coverage again"),
                    ("back", "Back to Map data"),
                    ("pause", "Save and exit"),
                ),
                default="back",
            )
            if answer == "keep":
                from travelmap import boundary_review

                if exc.review_signature is None:
                    echo("Recheck map data before keeping this stop.", kind=MessageKind.ERROR)
                    continue
                boundary_review.accept(root, trip, exc.review_signature, exc.stop_id)
                echo(
                    "Stop kept as entered. Country-boundary acceptance does not certify "
                    "road, water or route coverage.",
                    kind=MessageKind.SUCCESS,
                )
            elif answer == "countries":
                choose_countries(root)
            elif answer == "coordinates":
                edited = edit_stop_coordinates(trip, exc.stop_id)
                if edited is not None:
                    save_accepted_correction(root, edited)
                    echo(
                        "Stop coordinates saved; checking country coverage again.",
                        kind=MessageKind.SUCCESS,
                    )
            elif answer == "files":
                add_country_source(root)
            elif answer == "back":
                return None
            elif answer == "pause":
                return False
            elif answer != "retry":
                echo("Choose a displayed recovery action.", kind=MessageKind.ERROR)


def _prepare_interactively(root: Path, *, force: bool = False) -> bool | None:
    trip = accepted_trip(root)
    if trip is None:
        raise mapdata.MapDataError(
            "Accept an itinerary first so map preparation can use its "
            "extent. Return to the itinerary step."
        )
    echo("Checking which map files are available in your workspace.", kind=MessageKind.ACTIVITY)
    settings = mapdata.settings_for(root)
    sources = mapdata.discover(root, settings)
    kinds = {s["kind"] for s in sources}
    if "countries" not in kinds:
        raise mapdata.MapDataError(
            "Country boundaries are required. Download the Natural Earth "
            "Admin 0 Countries ZIP described above, copy it into the "
            "destination and choose Continue."
        )
    if "osm" not in kinds and not set(settings["enabled_layers"]) <= kinds:
        recommended = mapdata.recommend_regions(root, trip, activity)
        if recommended:
            echo(
                "Recommended Geofabrik country/subcountry extracts: "
                + ", ".join(recommended)
                + (
                    ". Include neighboring regions along the journeys; "
                    "stop countries do not certify route coverage."
                )
            )
        raise mapdata.MapDataError(
            "Background roads/water are required. Download the regional "
            "Geofabrik .osm.pbf described above, copy it into the destination "
            "and choose Continue."
        )
    from travelmap import poster_settings

    current = poster_settings.load(root, trip)
    reduced = not current["map"]["show_state_borders"]
    if not reduced and "admin1" not in kinds:
        raise mapdata.MapDataError(
            "State/province borders are enabled in config.toml, but their source is missing. "
            "Add the Admin 1 download or set map.show_state_borders = false, then recheck."
        )
    sizes = [(source, Path(source["path"]).stat().st_size) for source in sources]
    total_bytes = sum(size for _, size in sizes)
    oversized = [
        Path(source["path"]).name
        for source, size in sizes
        if source["kind"] == "osm" and size > mapdata.PBF_WARNING_BYTES
    ]
    if total_bytes > mapdata.TOTAL_INPUT_WARNING_BYTES or oversized:
        if total_bytes > mapdata.TOTAL_INPUT_WARNING_BYTES:
            echo("Combined map inputs exceed 1 GiB.", kind=MessageKind.WARNING)
        for name in oversized:
            echo(f"{name} exceeds 512 MiB.", kind=MessageKind.WARNING)
        echo("Large map inputs can take longer and use more memory and disk space.")
        answer = action_prompt(
            "Prepare map data with these files?",
            (("proceed", "Prepare map data"), ("back", "Back"), ("pause", "Save and exit")),
            default="back",
        )
        if answer != "proceed":
            return False if answer == "pause" else None
    from travelmap import flow, routes

    resolved, _ = routes.resolve(root, trip, activity)
    bounds = flow.route_extent_trip(trip, resolved)["extent"]
    mapdata.prepare(
        root, trip, reduced_detail=reduced, report=activity, bounds_override=bounds, force=force
    )
    return True


def choose_countries(root: Path) -> None:
    """Review/change country framing by names without requiring configuration editing."""
    trip = accepted_trip(root)
    if trip is None:
        raise mapdata.MapDataError("Accept an itinerary before choosing displayed countries.")
    settings = mapdata.settings_for(root)
    sources = [s for s in mapdata.discover(root, settings) if s["kind"] == "countries"]
    if not sources:
        raise mapdata.MapDataError(
            "Copy country boundaries into the map-data folder, "
            "then choose Displayed countries again."
        )
    cache = plan_workspace(root).cache_dir / "map-data"
    cache.mkdir(exist_ok=True)
    with mapdata.verification_operation():
        records = [
            mapdata.prepare_source(cache, source, settings, [-180, -90, 180, 90], activity)
            for source in sources
        ]
        activity("Checking country boundaries and stop coverage.")
        catalog = mapdata.countries_from_records(cache, records)
    # This menu previews a selection only; preparation separately requires explicit
    # acceptance for each mismatch before it can produce usable map data.
    stop_ids = {stop["properties"]["id"] for stop in itinerary.parts(trip, "stop")}
    try:
        chosen, _ = mapdata.selected_countries(
            catalog, trip, settings["country_ids"], accepted_stop_ids=stop_ids
        )
    except mapdata.MapDataError as exc:
        echo(str(exc), kind=MessageKind.WARNING)
        chosen = []
    echo(
        "Displayed complete countries: "
        + ", ".join(sorted({f["properties"]["name"] for f in chosen}))
    )
    echo(
        "Change map.boundaries.country_ids or country_codes in config.toml, then recheck map data."
    )
    echo("Available country IDs:")
    names = {
        (mapdata.country_identity(feature), str(feature["properties"]["name"]))
        for feature in catalog
    }
    for identity, name in sorted(names, key=lambda item: item[1].casefold()):
        echo(identity + ": " + name)
    from travelmap.terminal import wait_for_reading

    wait_for_reading()


def add_country_source(root: Path) -> bool:
    """Explain file-based source recovery without editing configuration from the CLI."""
    echo(
        "Copy boundary downloads into map-data, or configure map.boundaries.country_path in "
        "config.toml."
    )
    echo("For multiple boundary sources, add entries to map.sources in config.toml.")
    echo("Use workspace-relative paths and country polygons, not OSM roads/water extracts.")
    echo("Config file: " + str(root / "config.toml"))
    from travelmap.terminal import wait_for_reading

    wait_for_reading()
    return False
