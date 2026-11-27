"""File-based poster configuration, review, and acceptance."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import tomllib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from travelmap import duration, itinerary, mapdata, routes
from travelmap.config import PosterConfig, parse_config
from travelmap.manual_routes import names_for
from travelmap.reporting import Notice, feedback_kind
from travelmap.terminal import (
    MessageKind,
    action_prompt,
    confirm_action,
    emit,
    inert_text,
    restore_overview,
    show_details,
    wait_for_reading,
)
from travelmap.workspace import plan_workspace


class SettingsError(ValueError):
    """Invalid local non-secret poster settings."""


def preset(trip: dict[str, Any]) -> dict[str, Any]:
    return {
        "poster": {
            "title": trip["metadata"]["name"],
            "subtitle": "{total_km} km • {total_days} days",
            "title_case": None,
            "title_position": None,
            "width_mm": 594,
            "height_mm": 841,
            "margin_mm": 50,
            "orientation": "portrait",
        },
        "map": {
            "projection": "auto",
            "include_offshore_components": False,
            "padding_percent": 8,
            "show_country_borders": True,
            "show_stop_markers": False,
            "show_place_labels": False,
            "routing": {
                "enabled": True,
                "unreachable": "error",
                "merge_nearby_routes": False,
                "profiles": {"car": "driving-car", "walk": "foot-walking"},
            },
            "roads": {"enabled": False, "highway_classes": list(mapdata.DEFAULT_HIGHWAYS)},
            "water": {
                "enabled": True,
                "min_area_km2": 1,
                "simplify_geometry": True,
                "simplify_tolerance_mm": 0.1,
                "line_classes": list(mapdata.DEFAULT_WATER_LINES),
                "area_classes": list(mapdata.DEFAULT_WATER_AREAS),
            },
        },
        "style": {
            "background": "#F7F4EE",
            "land": "#DDD5C7",
            "border": "#5E5953",
            "route": "#A33F35",
            "stop": "#263238",
            "label": "#263238",
            "road": "#47433D",
            "route_width_mm": 0.6,
            "stop_radius_mm": 1.8,
            "font_family": "Source Sans 3",
            "title_font_family": "Cormorant Garamond",
            "boundary_width_mm": 0.3,
        },
        "output": {"incomplete_distance": "omit"},
    }


def reference_preset(current: dict[str, Any]) -> dict[str, Any]:
    """Apply the regional design while retaining trip metrics and source choices."""
    updated = copy.deepcopy(current)
    updated["poster"].update(
        design="reference",
        title="Argentina & Chile",
        subtitle="{total_km} km on land • {total_days} days",
        title_case="uppercase",
        title_position="bottom",
    )
    updated["map"].update(
        projection="ESRI:102033",
        framing="stops",
        fill_land=False,
        padding_percent=8,
        show_country_borders=True,
        show_stop_markers=False,
        show_place_labels=False,
    )
    updated["map"]["roads"]["enabled"] = False
    updated["map"]["water"].update(
        enabled=True,
        min_area_km2=1,
        line_classes=["river", "canal"],
        area_classes=list(mapdata.DEFAULT_WATER_AREAS),
        simplify_geometry=True,
        simplify_tolerance_mm=0.1,
    )
    updated["map"]["routing"].update(
        merge_nearby_routes=True,
        nearby_route_merge_tolerance_mm=0.1,
    )
    updated["map"]["scale"].update(
        enabled=True,
        distance_km=1000,
        segments=4,
        position="footer-center",
        height_mm=3,
        inset_mm=8,
        caption="",
        color=None,
        number_position="bottom",
    )
    updated["style"].update(
        background="#F7F4EE",
        border="#5E5953",
        route="#A33F35",
        water_line="#747A77",
        water_area="#D4D5CF",
        water_width_mm=0.2,
        water_line_opacity=0.45,
        water_area_opacity=1,
        route_width_mm=0.6,
        route_opacity=1,
        boundary_width_mm=0.3,
        font_family="Source Sans 3",
        title_font_family="Cormorant Garamond",
        label="#263238",
        stop="#263238",
        route_colors=[],
        route_colors_by_mode={},
        route_dash_patterns={},
    )
    return validate(updated)


def validate(raw: dict[str, Any]) -> dict[str, Any]:
    def check(value: Any) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            raise SettingsError("All numeric settings must be finite.")
        if isinstance(value, dict):
            for item in value.values():
                check(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                check(item)

    check(raw)
    try:
        config = PosterConfig.model_validate(raw)
    except ValidationError as exc:
        errors = [
            ".".join(str(p) for p in e["loc"]) + ": " + e["msg"]
            for e in exc.errors(include_input=False, include_url=False)
        ]
        raise SettingsError("; ".join(errors)) from None
    result = config.model_dump(mode="json")
    page = result["poster"]
    if not 50 <= page["width_mm"] <= 2000 or not 50 <= page["height_mm"] <= 2000:
        raise SettingsError("Page width/height must be 50–2,000 mm.")
    if 2 * page["margin_mm"] >= min(page["width_mm"], page["height_mm"]) - 20:
        raise SettingsError("Margins must leave at least 20 mm of usable page area.")
    if max(page["width_mm"], page["height_mm"]) - 2 * page["margin_mm"] <= 60:
        raise SettingsError("Page/margins must leave more than 60 mm for title and map.")
    if result["map"]["routing"]["request_delay_s"] > 60:
        raise SettingsError("Request delay must be 0–60 seconds.")
    if result["map"]["scale"]["segments"] > 20:
        raise SettingsError("Scale bar uses 1–20 segments.")
    for name, value in result["style"].items():
        if name.endswith("_mm") and value is not None and value > 50:
            raise SettingsError(f"{name}: physical size must be at most 50 mm.")
    for field in ("font_family", "title_font_family"):
        if not re.fullmatch(r"[A-Za-z0-9 ,\-]{1,150}", result["style"][field]):
            raise SettingsError(
                f"{field}: use plain font-family names, letters/numbers/spaces/hyphens/commas; "
                f"no markup or resources."
            )
    for mode, pattern in result["style"]["route_dash_patterns"].items():
        if mode not in itinerary.MODES or not re.fullmatch(
            r"\d+(?:\.\d+)?(?:[ ,]+\d+(?:\.\d+)?)*", pattern
        ):
            raise SettingsError(
                "Dash patterns use supported modes and positive numbers separated by spaces (mm)."
            )
        if any(float(v) <= 0 or float(v) > 50 for v in re.split("[ ,]+", pattern)):
            raise SettingsError("Each dash/gap must be >0 and <=50 mm.")
    if any(mode not in itinerary.MODES for mode in result["style"]["route_colors_by_mode"]):
        raise SettingsError("Mode colors require a supported transport mode.")
    if len(result["style"]["route_colors"]) > 8:
        raise SettingsError("At most eight route-color variants are supported.")
    projection = result["map"]["projection"]
    if projection != "auto":
        try:
            from pyproj import CRS, network

            network.set_network_enabled(False)  # type: ignore[attr-defined]
            CRS.from_user_input(projection)
        except Exception:
            raise SettingsError(
                "Unavailable projection. Use auto or a locally supported EPSG/ESRI/PROJ definition."
            ) from None
    for token in re.findall(r"\{([^{}]+)\}", page["subtitle"] or ""):
        if token not in ("total_km", "total_days"):
            raise SettingsError(
                "Subtitle fields are {total_km} and {total_days}; other text is literal."
            )
    for section, keys in (
        (result["map"]["boundaries"], ("country_path", "admin1_path")),
        (result["map"]["routing"], ("cache",)),
    ):
        for key in keys:
            value = section[key]
            if value is not None and (
                Path(value).is_absolute() or ".." in Path(value).parts or "://" in value
            ):
                raise SettingsError(f"{key}: use a portable workspace-relative file path.")
    for section in ("roads", "water"):
        if any(
            Path(p).is_absolute() or ".." in Path(p).parts or "://" in p
            for p in result["map"][section]["paths"]
        ):
            raise SettingsError(f"{section}: use workspace-relative file paths.")
    for source in result["map"]["sources"]:
        path = source["path"]
        if Path(path).is_absolute() or ".." in Path(path).parts or "://" in path:
            raise SettingsError("Map sources must use workspace-relative local paths.")
    boundaries = result["map"]["boundaries"]
    if boundaries["country_ids"] and boundaries["country_codes"]:
        raise SettingsError("Set only one of map.boundaries.country_ids and country_codes.")
    if result["map"]["routing"]["nearby_route_merge_tolerance_mm"] > 5:
        raise SettingsError("Nearby-route tolerance must be >0 and <=5 mm on the page.")
    return result


def _legacy_settings(root: Path, trip: dict[str, Any]) -> dict[str, Any]:
    """Collect settings from the old metadata files once, before TOML becomes authoritative."""
    paths = plan_workspace(root)
    saved = paths.metadata_dir / "poster-settings.json"
    if saved.exists():
        raw_settings = mapdata.read_json(saved, mapdata.MIB)
    else:
        raw_settings = preset(trip)
        # Write these defaults explicitly while retaining the fallback for existing TOML files.
        raw_settings["poster"].update(title_case="uppercase", title_position="bottom")
        raw_settings["style"]["land"] = raw_settings["style"]["background"]
    settings = validate(raw_settings)
    map_path = paths.metadata_dir / "map-settings.json"
    if map_path.exists():
        old = mapdata.settings_for(root, from_config=False)
        boundaries = settings["map"]["boundaries"]
        if not (boundaries["country_ids"] or boundaries["country_codes"]):
            boundaries["country_ids"] = old["country_ids"] or None
        for item in old["vectors"]:
            path = (paths.map_data_dir / item["path"]).resolve()
            try:
                relative = path.relative_to(root.resolve()).as_posix()
            except ValueError:
                raise SettingsError(
                    "Move legacy map sources inside the workspace before migration."
                ) from None
            source = {
                key: item[key] for key in ("kind", "layer", "attribution", "licence") if key in item
            }
            source["path"] = relative
            if source not in settings["map"]["sources"]:
                settings["map"]["sources"].append(source)
        if not saved.exists():
            for key, section, field in (
                ("highway_classes", "roads", "highway_classes"),
                ("water_line_classes", "water", "line_classes"),
                ("water_area_classes", "water", "area_classes"),
            ):
                settings["map"][section][field] = old[key]
            settings["map"]["roads"]["enabled"] = "roads" in old["enabled_layers"]
            settings["map"]["water"]["enabled"] = bool(
                set(old["enabled_layers"]) & {"water_lines", "water_areas"}
            )
    routing_path = paths.metadata_dir / "routing-settings.json"
    if routing_path.exists() and not saved.exists():
        old_routing = mapdata.read_json(routing_path, mapdata.MIB)
        for key in settings["map"]["routing"]:
            old_key = "direct_policy" if key == "unreachable" else key
            if old_key in old_routing:
                settings["map"]["routing"][key] = old_routing[old_key]
    prepared = (
        mapdata.read_json(paths.metadata_dir / "map-data.json")
        if (paths.metadata_dir / "map-data.json").exists()
        else {}
    )
    if "show_state_borders" not in raw_settings["map"]:
        settings["map"]["show_state_borders"] = bool(
            settings["map"]["boundaries"]["admin1_path"] or "admin1" in prepared.get("layers", {})
        )
    return validate(settings)


def ensure_file(root: Path, trip: dict[str, Any] | None = None) -> Path | None:
    """Create defaults or migrate legacy settings without overwriting user-authored TOML."""
    from travelmap.settings_file import dumps, publish_new

    source = root / "config.toml"
    if source.is_symlink() or (source.exists() and not source.is_file()):
        raise SettingsError("config.toml must be a regular file inside the workspace.")
    paths = plan_workspace(root)
    receipt = paths.metadata_dir / "file-settings-version.json"
    if trip is None:
        accepted = paths.metadata_dir / "itinerary.geojson"
        trip = (
            itinerary.load(accepted)[1][0][0]
            if accepted.exists()
            else {"metadata": {"name": root.name}}
        )
    if not source.exists():
        if receipt.exists():
            raise SettingsError(
                "config.toml is missing. Restore it or create it from the documented defaults."
            )
        publish_new(source, dumps(_legacy_settings(root, trip)))
    migration: Path | None = None
    if not receipt.exists():
        binding = paths.metadata_dir / "config-source.json"
        saved = paths.metadata_dir / "poster-settings.json"
        if saved.exists() and binding.exists():
            content = itinerary.read_bytes(source)
            if mapdata.read_json(binding).get("sha256") == hashlib.sha256(content).hexdigest():
                effective = _legacy_settings(root, trip)
                configured = load(root, trip)
                if effective != configured:
                    migration = root / "config.previous-settings.toml"
                    if not publish_new(migration, dumps(effective)) and migration.read_text(
                        "utf-8"
                    ) != dumps(effective):
                        raise SettingsError(
                            "config.previous-settings.toml already exists; preserve or "
                            "rename it before migration."
                        )
        mapdata.atomic_json(
            receipt,
            {"schema_version": 1, "previous_settings": migration.name if migration else None},
        )
    return migration


def load(root: Path, trip: dict[str, Any]) -> dict[str, Any]:
    """Read requested settings only from TOML plus built-in defaults, never saved snapshots."""
    source = root / "config.toml"
    if source.is_symlink():
        raise SettingsError("config.toml must not be a symlink.")
    if not source.exists():
        # Only old workspaces can bootstrap; a deleted authoritative file must be restored.
        ensure_file(root, trip)
    try:
        content = itinerary.read_bytes(source)
        if len(content) > mapdata.MIB:
            raise SettingsError("config.toml exceeds 1 MiB.")
        raw = tomllib.loads(content.decode("utf-8"))
        config = parse_config(raw, source.parent, defaults=preset(trip), source=str(source))
        settings = config.model_dump(mode="json")
        _make_paths_workspace_relative(settings, root)
        return validate(settings)
    except (ValueError, UnicodeError) as exc:
        raise SettingsError(f"config.toml: {exc}. Correct the file, save, and reload it.") from exc


def _make_paths_workspace_relative(settings: dict[str, Any], root: Path) -> None:
    """Keep resolved local paths portable and confined to the workspace."""

    root_path = root.resolve()

    def relative(value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return Path(value).resolve().relative_to(root_path).as_posix()
        except ValueError:
            raise SettingsError(
                "config.toml paths must resolve inside the trip workspace."
            ) from None

    for source in settings["map"]["sources"]:
        source["path"] = relative(source["path"])
    boundaries = settings["map"]["boundaries"]
    for key in ("country_path", "admin1_path"):
        boundaries[key] = relative(boundaries[key])
    routing = settings["map"]["routing"]
    routing["cache"] = relative(routing["cache"])
    for section in ("roads", "water"):
        settings["map"][section]["paths"] = [
            relative(value) for value in settings["map"][section]["paths"]
        ]


def save(root: Path, settings: dict[str, Any]) -> None:
    paths = plan_workspace(root)
    mapdata.atomic_json(paths.metadata_dir / "poster-settings.json", validate(settings))


def signature(settings: dict[str, Any]) -> str:
    style = settings["style"].copy()
    # Keep prior acceptance signatures valid when these settings use layout defaults.
    for key in ("title_font_size_mm", "subtitle_font_size_mm", "title_subtitle_gap_mm"):
        if style.get(key) is None:
            style.pop(key, None)
    settings = {**settings, "style": style}
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def font_sizes(settings: dict[str, Any]) -> tuple[float, float]:
    """Return the effective title and subtitle sizes in millimetres."""
    reference = settings["poster"].get("design", "standard") == "reference"
    style = settings["style"]
    return (
        style.get("title_font_size_mm") or (10 if reference else 12),
        style.get("subtitle_font_size_mm") or (3 if reference else 4),
    )


def metric_text(
    trip: dict[str, Any], resolved: dict[str, dict[str, Any]], settings: dict[str, Any]
) -> tuple[str, list[str]]:
    warnings = []
    subtitle_template = settings["poster"]["subtitle"] or ""
    total = 0.0
    missing = []
    overrides = settings["map"]["distance"]["segment_overrides_km"]
    for segment in itinerary.parts(trip, "segment"):
        sequence = segment["properties"]["sequence"]
        override = overrides.get(str(sequence), overrides.get(sequence))
        distance = resolved.get(routes.segment_key(trip, segment), {}).get("distance_m")
        if override is not None:
            total += float(override)
        elif distance is not None:
            total += distance / 1000
        else:
            missing.append(names_for(trip, segment))
    if missing:
        message = (
            f"Distance unknown for {len(missing)} connections. "
            "Edit map.distance.segment_overrides_km or poster.subtitle in config.toml, then reload."
        )
        warnings.append(
            message
            if "{total_km}" in subtitle_template
            and settings["output"]["incomplete_distance"] != "subtotal"
            else Notice(message)
        )
    if not missing:
        km = f"{total:,.0f}"
    elif settings["output"]["incomplete_distance"] == "subtotal":
        km = f"{total:,.0f} km known; incomplete"
    else:
        km = "distance unavailable"
    assessment = duration.assess(trip, settings["map"]["distance"]["travel_days_override"])
    days = assessment.days
    if assessment.source == "unavailable":
        warnings.extend(
            message if "{total_days}" in subtitle_template else Notice(message)
            for message in duration.warnings(trip, assessment)
        )
    subtitle = settings["poster"]["subtitle"] or ""
    subtitle = subtitle.replace("{total_km} km", f"{km} km" if not missing else km)
    subtitle = subtitle.replace("{total_days} days", f"{days} days" if days else "days unavailable")
    subtitle = subtitle.replace("{total_km}", km).replace(
        "{total_days}", str(days) if days else "days unavailable"
    )
    return subtitle, warnings


def echo(message: str, *, kind: MessageKind = MessageKind.INFO) -> None:
    emit(inert_text(message), kind=kind)


def preview_filter(root: Path, trip: dict[str, Any], settings: dict[str, Any]) -> bool:
    codes = (
        settings["map"]["boundaries"].get("country_ids")
        or settings["map"]["boundaries"]["country_codes"]
    )
    if not codes:
        return True
    selected = mapdata.inspect_prepared(root)
    if not selected:
        raise SettingsError("Prepare boundaries before reviewing a country filter.")
    from shapely.geometry import Point, shape

    countries = (
        mapdata.countries_from_records(
            plan_workspace(root).cache_dir / "map-data", selected["sources"]
        )
        if selected.get("schema_version") == 2
        else list(mapdata.iter_layer(root, selected, "countries"))
    )
    excluded = set()
    for stop in itinerary.parts(trip, "stop"):
        point = Point(stop["geometry"]["coordinates"][:2])
        from travelmap import geography

        if not any(
            mapdata.country_identity(f) in codes and geography.covers(shape(f["geometry"]), point)
            for f in countries
        ):
            excluded.add(stop["properties"]["id"])
    affected = sum(
        s["properties"]["origin_id"] in excluded or s["properties"]["destination_id"] in excluded
        for s in itinerary.parts(trip, "segment")
    )
    echo(
        f"Country filter hides background land around {len(excluded)} "
        f"visits and {affected} connections. Visits/routes "
        f"remain visible and are never removed from the "
        f"journey."
    )
    return bool(confirm_action("filter", "Apply this country filter").strip().lower() == "filter")


def view_distances(
    trip: dict[str, Any], resolved: dict[str, dict[str, Any]], settings: dict[str, Any]
) -> None:
    overrides = settings["map"]["distance"]["segment_overrides_km"]
    lines = []
    for segment in itinerary.parts(trip, "segment"):
        sequence = str(segment["properties"]["sequence"])
        record = resolved.get(routes.segment_key(trip, segment), {})
        distance = record.get("distance_m")
        kilometres = overrides.get(sequence)
        if kilometres is None and distance is not None:
            kilometres = distance / 1000
        value = "distance unknown" if kilometres is None else f"{kilometres:g} km"
        lines.append(names_for(trip, segment) + ": " + value)
    show_details("Connection distances", lines)


def run_settings(root: Path, trip: dict[str, Any], resolved: dict[str, dict[str, Any]]) -> str:
    current = load(root, trip)
    reviewed_content = itinerary.read_bytes(root / "config.toml")
    last_action = "accept"
    first_overview = True
    while True:
        if not first_overview:
            restore_overview(6, str(root))
        first_overview = False
        echo("Current configuration:")
        page = current["poster"]
        echo(
            f"Poster title: {page['title']}. Page: {page['width_mm']} "
            f"× {page['height_mm']} mm, {page['orientation']}, "
            f"margins {page['margin_mm']} mm. Projection: {current['map']['projection']}."
        )
        subtitle, warnings = metric_text(trip, resolved, current)
        echo("Subtitle: " + subtitle)
        title_size, subtitle_size = font_sizes(current)
        echo(f"Font sizes: title {title_size:g} mm, subtitle {subtitle_size:g} mm.")
        assessment = duration.assess(trip, current["map"]["distance"]["travel_days_override"])
        if assessment.source == "override":
            echo(f"Trip duration: {assessment.days} days (explicit override).")
            warnings.extend(Notice(message) for message in duration.warnings(trip, assessment))
        elif assessment.source == "dates":
            echo(f"Trip duration: {assessment.days} days (from stop dates).")
        echo(
            "Layers: country boundaries; roads "
            + ("shown" if current["map"]["roads"]["enabled"] else "hidden")
            + "; water "
            + ("shown" if current["map"]["water"]["enabled"] else "hidden")
            + "; stop markers "
            + ("shown" if current["map"]["show_stop_markers"] else "hidden")
            + "; labels "
            + ("shown" if current["map"]["show_place_labels"] else "hidden")
        )
        countries = current["map"]["boundaries"]
        selected = countries["country_ids"] or countries["country_codes"]
        echo("Countries: " + (", ".join(selected) if selected else "automatic from trip stops"))
        echo(
            "State/province borders: "
            + ("shown" if current["map"]["show_state_borders"] else "hidden")
        )
        migration_receipt = plan_workspace(root).metadata_dir / "file-settings-version.json"
        if (
            migration_receipt.exists()
            and mapdata.read_json(migration_receipt).get("previous_settings")
            == "config.previous-settings.toml"
        ):
            previous = root / "config.previous-settings.toml"
            if previous.is_file():
                echo(
                    "Previous CLI settings were preserved in "
                    + str(previous)
                    + ". Compare them with config.toml before accepting the design.",
                    kind=MessageKind.WARNING,
                )
        for warning in warnings:
            echo(warning, kind=MessageKind(feedback_kind(warning).value))
        emit()
        echo("To change these settings, edit and save config.toml, then choose Reload config file.")
        echo("Config file: " + str(root / "config.toml"))
        answer = (
            action_prompt(
                "Choose your poster design",
                (
                    ("accept", "Accept and continue"),
                    ("reload", "Reload config file"),
                    ("distances", "View connection distances"),
                    ("help", "Help"),
                    ("back", "Back"),
                    ("pause", "Save and exit"),
                ),
                default=last_action,
                preserve_order=True,
            )
            .strip()
            .lower()
        )
        last_action = answer
        if answer in ("back", "menu", "pause"):
            return str(answer)
        if answer == "reload":
            try:
                if not (root / "config.toml").is_file():
                    raise SettingsError("Create and save config.toml at the displayed path first.")
                updated = load(root, trip)
            except (ValueError, OSError) as exc:
                echo(str(exc), kind=MessageKind.ERROR)
                echo("Current design kept. Correct the file, then choose Reload config file.")
            else:
                current = updated
                reviewed_content = itinerary.read_bytes(root / "config.toml")
                echo(
                    "Config file loaded. Review the design, then choose Accept and continue.",
                    kind=MessageKind.SUCCESS,
                )
        elif answer == "distances":
            view_distances(trip, resolved, current)
        elif answer == "help":
            echo(
                "Edit and save config.toml, then choose Reload config file to review your changes."
            )
            echo("Colours use six hexadecimal digits; physical sizes are millimetres.")
            echo(
                "Use map.boundaries.country_ids or country_codes for displayed countries; "
                "[] uses trip countries."
            )
            echo("Use map.distance.segment_overrides_km for connection distances in kilometres.")
            echo(
                "Use map.distance.travel_days_override for total days; remove it to "
                "calculate from dates."
            )
            echo(
                "Update stop dates in Your itinerary. The poster title is configured "
                "separately from the trip title."
            )
            echo(
                "Use poster.subtitle to change the subtitle, or output.incomplete_distance "
                '= "subtotal" for a partial distance.'
            )
            echo("Config file: " + str(root / "config.toml"))
            echo(
                '[map.distance]\ntravel_days_override = 14\nsegment_overrides_km = { "1" = 125.5 }'
            )
            echo("Style changes reuse compatible routes and prepared map layers.")
            wait_for_reading()
        elif answer == "accept":
            try:
                latest_content = itinerary.read_bytes(root / "config.toml")
                latest = load(root, trip)
            except (ValueError, OSError) as exc:
                echo(str(exc), kind=MessageKind.ERROR)
                continue
            if latest_content != reviewed_content or latest != current:
                echo(
                    "Config file changed. Choose Reload config file and review it before "
                    "accepting.",
                    kind=MessageKind.WARNING,
                )
                continue
            codes = current["map"]["boundaries"]["country_codes"]
            if codes:
                prepared_selection = mapdata.inspect_prepared(root)
                review_key = hashlib.sha256(
                    json.dumps(
                        [
                            codes,
                            itinerary.parts(trip, "stop"),
                            prepared_selection["key"] if prepared_selection else None,
                        ],
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                review_path = plan_workspace(root).metadata_dir / "filter-review.json"
                reviewed = (
                    mapdata.read_json(review_path).get("key") if review_path.exists() else None
                )
                if reviewed != review_key:
                    if not preview_filter(root, trip, current):
                        continue
                    mapdata.atomic_json(review_path, {"key": review_key})
            save(root, current)
            mapdata.atomic_json(
                plan_workspace(root).metadata_dir / "settings-accepted.json",
                {"signature": signature(current)},
            )
            echo(
                "Effective settings saved. Compatible routes and map layers remain available.",
                kind=MessageKind.SUCCESS,
            )
            return "done"
        else:
            echo("Choose one of the displayed actions.", kind=MessageKind.ERROR)
