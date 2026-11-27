"""Validated segment resolution and bounded, explicitly authorized provider acquisition."""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from travelmap import itinerary
from travelmap.mapdata import atomic_json, read_json
from travelmap.reporting import report_feedback
from travelmap.workspace import plan_workspace

MAX_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 1000
MAX_VERTICES = 100_000
MAX_TOTAL_VERTICES = 500_000
ENDPOINT_TOLERANCE_M = 5000
PROVIDER = "https://api.heigit.org/openrouteservice/v2/directions"
# Keep the original cache identity across the address change for the same service.
PROVIDER_CACHE_NAMESPACE = "https://api.openrouteservice.org/v2/directions"
PROFILES = ("driving-car", "cycling-regular", "foot-walking")


class RouteError(ValueError):
    """Expected route validation failure; messages never include provider bodies."""


class RouteLimitError(RouteError):
    """A total processing limit must stop resolution rather than trigger acquisition."""


class ProviderError(RouteError):
    def __init__(self, category: str) -> None:
        self.category = category
        messages = {
            "not-found": (
                "No route found for these coordinates. Try selected cycling/walking, "
                "local files, or pause."
            ),
            "auth": (
                "Provider authentication failed. Check your key/account; "
                "use local files or pause. Changing transport will not fix "
                "authentication."
            ),
            "quota": (
                "Provider quota/rate limit reached. Wait for the account "
                "limit to reset, use local files, or pause. Saved successes "
                "remain."
            ),
            "length": (
                "Provider route-length/parameter restriction. Check "
                "https://openrouteservice.org/restrictions/; "
                "supply local geometry or pause."
            ),
            "connection": (
                "Provider connection/server failure. Check connectivity and "
                "retry explicitly later, supply local files, or pause."
            ),
            "invalid": (
                "Provider returned an invalid/oversized result. No unchecked "
                "route was saved. Retry explicitly, use local files, or pause."
            ),
        }
        super().__init__(messages.get(category, messages["invalid"]))


def line(coordinates: Any) -> list[list[float]]:
    if not isinstance(coordinates, list) or not 2 <= len(coordinates) <= MAX_VERTICES:
        raise RouteError("Route line needs 2–100,000 vertices. Export a smaller valid LineString.")
    result = []
    try:
        for coordinate in coordinates:
            result.append(itinerary.coordinate(coordinate)[:2])
    except ValueError as exc:
        raise RouteError(
            "Route has invalid WGS84 coordinates; export finite longitude/latitude pairs."
        ) from exc
    return result


def metric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise RouteError(
            "Distance/duration must be nonnegative finite numbers with recognized units."
        )
    try:
        number = float(value)
    except OverflowError:
        raise RouteError("Distance/duration exceeds the supported numeric range.") from None
    if not math.isfinite(number):
        raise RouteError("Distance/duration must be finite numbers.")
    return number


def metres(left: list[float], right: list[float]) -> float:
    a, b = math.radians(left[1]), math.radians(right[1])
    delta_lat = b - a
    delta_lon = math.radians(right[0] - left[0])
    hav = math.sin(delta_lat / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(delta_lon / 2) ** 2
    return 6371008.8 * 2 * math.asin(min(1.0, math.sqrt(max(0, hav))))


def endpoints(trip: dict[str, Any], segment: dict[str, Any]) -> list[list[float]]:
    stops = {
        s["properties"]["id"]: s["geometry"]["coordinates"][:2]
        for s in itinerary.parts(trip, "stop")
    }
    p = segment["properties"]
    return [stops[p["origin_id"]], stops[p["destination_id"]]]


def segment_key(trip: dict[str, Any], segment: dict[str, Any]) -> str:
    p = segment["properties"]
    data = [p["origin_id"], p["destination_id"], endpoints(trip, segment), p["transport_mode"]]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def settings(root: Path) -> dict[str, Any]:
    if (root / "config.toml").exists() or (
        plan_workspace(root).metadata_dir / "file-settings-version.json"
    ).exists():
        from travelmap import flow, poster_settings

        accepted = plan_workspace(root).metadata_dir / "itinerary.geojson"
        trip = (
            itinerary.load(accepted)[1][0][0]
            if accepted.exists()
            else {"metadata": {"name": root.name}}
        )
        flow.sync_settings(root, poster_settings.load(root, trip))
    path = plan_workspace(root).metadata_dir / "routing-settings.json"
    raw: dict[str, Any] = read_json(path, MAX_BYTES) if path.exists() else {}
    result: dict[str, Any] = {
        "enabled": raw.get("enabled", True),
        "api_key_env": raw.get("api_key_env", "OPENROUTESERVICE_API_KEY"),
        "preference": raw.get("preference", "recommended"),
        "avoid_features": raw.get("avoid_features", []),
        "request_delay_s": raw.get("request_delay_s", 2.0),
        "profiles": raw.get("profiles", {}),
        "modes": raw.get("modes", ["bus", "car", "train", "walk"]),
        "direct_policy": raw.get("direct_policy", "error"),
        "cache": raw.get("cache"),
    }
    if not isinstance(result["enabled"], bool):
        raise RouteError("Routing enabled must be a boolean.")
    if not isinstance(result["api_key_env"], str) or not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*", result["api_key_env"]
    ):
        raise RouteError("Routing API key setting must name an environment variable.")
    if result["preference"] not in ("recommended", "fastest", "shortest"):
        raise RouteError("Routing preference must be recommended, fastest or shortest.")
    avoid = result["avoid_features"]
    if (
        not isinstance(avoid, list)
        or any(v not in ("highways", "tollways", "ferries", "fords", "steps") for v in avoid)
        or len(avoid) != len(set(avoid))
    ):
        raise RouteError(
            "Routing avoid features: highways, tollways, ferries, fords or steps; no duplicates."
        )
    delay = metric(result["request_delay_s"])
    if delay is None or delay > 60:
        raise RouteError("Request pacing must be 0–60 seconds.")
    profiles = result["profiles"]
    if not isinstance(profiles, dict) or any(
        k not in itinerary.MODES or v not in PROFILES for k, v in profiles.items()
    ):
        raise RouteError(
            "Routing profiles must map supported recorded modes to supported profiles."
        )
    modes = result["modes"]
    if (
        not isinstance(modes, list)
        or any(mode not in itinerary.MODES for mode in modes)
        or len(modes) != len(set(modes))
    ):
        raise RouteError("Routing modes must be distinct supported transport modes.")
    cache = result["cache"]
    if cache is not None and (
        not isinstance(cache, str)
        or Path(cache).is_absolute()
        or ".." in Path(cache).parts
        or "://" in cache
    ):
        raise RouteError("Route cache must be a workspace-relative local file.")
    if result["direct_policy"] not in ("error", "direct"):
        raise RouteError(
            "Direct policy must be error or direct; direct lines still "
            "require explicit confirmation."
        )
    return result


def profile_for(segment: dict[str, Any], opts: dict[str, Any]) -> str | None:
    mode = segment["properties"]["transport_mode"]
    if mode not in opts["modes"]:
        return None
    value = opts["profiles"].get(mode, {"car": "driving-car", "walk": "foot-walking"}.get(mode))
    return str(value) if value is not None else None


def cache_key(
    trip: dict[str, Any], segment: dict[str, Any], profile: str, opts: dict[str, Any]
) -> str:
    value = [
        segment_key(trip, segment),
        profile,
        opts["preference"],
        sorted(opts["avoid_features"]),
        PROVIDER_CACHE_NAMESPACE,
    ]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def valid_record(record: Any, expected: list[list[float]]) -> dict[str, Any]:
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise RouteError("Unsupported route record version.")
    if record.get("endpoints") != expected:
        raise RouteError("Route record endpoints are stale.")
    if record.get("recorded_mode") not in itinerary.MODES or not isinstance(
        record.get("approximate"), bool
    ):
        raise RouteError("Route record requires recorded mode and explicit approximation status.")
    coords = line(record.get("coordinates"))
    if max(metres(coords[0], expected[0]), metres(coords[-1], expected[1])) > ENDPOINT_TOLERANCE_M:
        raise RouteError(
            "Route endpoints mismatch by more than 5 km. Choose the correct route or segment."
        )
    for key in ("distance_m", "duration_s"):
        metric(record.get(key))
    if record.get("source") not in ("manual", "embedded", "provider", "direct", "zero"):
        raise RouteError("Route source must be recognized.")
    return record


def record_for(
    trip: dict[str, Any],
    segment: dict[str, Any],
    coordinates: list[list[float]],
    source: str,
    profile: str | None = None,
    distance_m: float | None = None,
    duration_s: float | None = None,
    **extra: Any,
) -> dict[str, Any]:
    p = segment["properties"]
    result = {
        "schema_version": 1,
        "segment_key": segment_key(trip, segment),
        "origin": p["origin_id"],
        "destination": p["destination_id"],
        "recorded_mode": p["transport_mode"],
        "endpoints": endpoints(trip, segment),
        "coordinates": coordinates,
        "source": source,
        "profile": profile,
        "distance_m": distance_m,
        "duration_s": duration_s,
        "approximate": source == "direct",
        **extra,
    }
    return valid_record(result, endpoints(trip, segment))


def load_assignments(root: Path) -> dict[str, Any]:
    path = plan_workspace(root).metadata_dir / "manual-assignments.json"
    raw: dict[str, Any] = (
        read_json(path, MAX_BYTES) if path.exists() else {"schema_version": 1, "assignments": {}}
    )
    if (
        raw.get("schema_version") != 1
        or not isinstance(raw.get("assignments"), dict)
        or len(raw["assignments"]) > MAX_RECORDS
    ):
        raise RouteError(
            "Manual assignments contain unsupported schema or too many "
            "records. Repair/reselect the assignment file."
        )
    return raw


def assignment_current(root: Path, record: dict[str, Any], trip: dict[str, Any]) -> bool:
    if record.get("source_file") == "@itinerary":
        index = record.get("source_candidate")
        candidates = itinerary.parts(trip, "unassigned")
        if not isinstance(index, int) or not 0 <= index < len(candidates):
            return False
        current = hashlib.sha256(
            json.dumps(line(candidates[index]["geometry"]["coordinates"]), sort_keys=True).encode()
        ).hexdigest()
    else:
        value = record.get("source_file")
        if not isinstance(value, str) or Path(value).is_absolute() or ".." in Path(value).parts:
            return False
        source = root / value
        try:
            current = hashlib.sha256(itinerary.read_bytes(source)).hexdigest()
        except ValueError:
            return False
    return current == record.get("source_hash")


def resolve(
    root: Path, trip: dict[str, Any], report: Callable[[str], None] = lambda _: None
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    opts = settings(root)
    assignments = load_assignments(root)["assignments"]
    configured_cache: list[dict[str, Any]] = []
    if opts["cache"]:
        cache_path = plan_workspace(root).root / opts["cache"]
        if cache_path.is_file():
            from travelmap.manual_routes import candidates

            _, configured_cache, _ = candidates(cache_path)
        else:
            report_feedback(report, f"Configured route cache is missing: {cache_path}")
    choices = load_choices(root)["profiles"]
    results: dict[str, dict[str, Any]] = {}
    retained_vertices = 0

    def retain(key: str, record: dict[str, Any]) -> None:
        nonlocal retained_vertices
        retained_vertices += len(record["coordinates"])
        if retained_vertices > MAX_TOTAL_VERTICES:
            raise RouteLimitError(
                "Resolved routes exceed 500,000 total vertices. "
                "Use simpler route exports or a smaller trip; saved "
                "successes are preserved."
            )
        results[key] = record

    unresolved = []
    if len(itinerary.parts(trip, "segment")) > MAX_RECORDS:
        raise RouteError(
            "Trip exceeds 1,000 routing connections. Export "
            "a smaller trip; existing cached routes are preserved."
        )
    for segment in itinerary.parts(trip, "segment"):
        key = segment_key(trip, segment)
        expected = endpoints(trip, segment)
        manual = assignments.get(key)
        if manual:
            try:
                if assignment_current(root, manual, trip):
                    retain(key, valid_record(manual, expected))
                    continue
                report_feedback(
                    report,
                    f"Connection {segment['properties']['sequence']}: "
                    f"changed manual source; recheck/reassign. Other "
                    f"routes remain reusable.",
                )
            except RouteLimitError:
                raise
            except RouteError:
                report_feedback(
                    report, "Invalid manual assignment excluded; choose a valid local route."
                )
        p = segment["properties"]
        if (
            p.get("embedded_geometry")
            or (not p.get("mode_assumed") and p.get("custom", {}).get("feature_type") == "segment")
            or ("mode_assumed" not in p)
        ):
            try:
                retain(
                    key,
                    record_for(
                        trip,
                        segment,
                        line(segment["geometry"]["coordinates"]),
                        "embedded",
                        distance_m=metric(p.get("distance_m")),
                        duration_s=metric(p.get("duration_s")),
                    ),
                )
                continue
            except RouteLimitError:
                raise
            except RouteError:
                report_feedback(
                    report,
                    f"Connection {p['sequence']}: embedded line invalid "
                    f"or mismatching; local/acquired repair required.",
                )
        if expected[0] == expected[1]:
            retain(key, record_for(trip, segment, expected, "zero", distance_m=0, duration_s=0))
            continue
        configured = _configured_cache_match(trip, segment, configured_cache)
        if configured is not None:
            coordinates = configured["coordinates"]
            if configured["orientation"] == "reverse":
                coordinates = list(reversed(coordinates))
            retain(
                key,
                record_for(
                    trip,
                    segment,
                    coordinates,
                    "manual",
                    profile=configured["profile"],
                    distance_m=configured["distance_m"],
                    duration_s=configured["duration_s"],
                    source_file=opts["cache"],
                ),
            )
            continue
        chosen = choices.get(key, profile_for(segment, opts))
        if chosen == "direct":
            retain(key, record_for(trip, segment, expected, "direct"))
            continue
        if chosen in PROFILES:
            provider_key = cache_key(trip, segment, chosen, opts)
            cached = plan_workspace(root).cache_dir / "routes" / (provider_key + ".json")
            if cached.exists():
                try:
                    record = read_json(cached, MAX_BYTES)
                    if (
                        record.get("cache_key") == provider_key
                        and record.get("segment_key") == key
                        and record.get("profile") == chosen
                        and record.get("source") == "provider"
                    ):
                        retain(key, valid_record(record, expected))
                        continue
                except RouteLimitError:
                    raise
                except (ValueError, TypeError):
                    report_feedback(
                        report,
                        f"Connection {p['sequence']}: stale/invalid provider cache excluded.",
                    )
        unresolved.append(segment)
    return results, unresolved


def _configured_cache_match(
    trip: dict[str, Any],
    segment: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Match a configured GeoJSON cache record to one segment by sequence and endpoints."""

    if not candidates:
        return None
    from travelmap.manual_routes import matches

    p = segment["properties"]
    matching = []
    for candidate in candidates:
        if candidate["mode"] is not None and candidate["mode"] != p["transport_mode"]:
            continue
        if candidate["sequence"] is not None and candidate["sequence"] != p["sequence"]:
            continue
        orientation = matches(trip, segment, candidate["coordinates"])
        if orientation is not None:
            matching.append({**candidate, "orientation": orientation})
    if len(matching) == 1:
        return matching[0]
    if matching:
        return None
    # Sequence identifiers can differ between itinerary exporters. Endpoint geometry
    # remains a safe fallback when exactly one configured route fits this connection.
    for candidate in candidates:
        if candidate["mode"] is not None and candidate["mode"] != p["transport_mode"]:
            continue
        orientation = matches(trip, segment, candidate["coordinates"])
        if orientation is not None:
            matching.append({**candidate, "orientation": orientation})
    return matching[0] if len(matching) == 1 else None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def fetch(
    trip: dict[str, Any],
    segment: dict[str, Any],
    profile: str,
    opts: dict[str, Any],
    secret: str,
    opener: Any = None,
    report: Callable[[str], None] = lambda _: None,
) -> dict[str, Any]:
    if profile not in PROFILES or not secret.strip() or "\r" in secret or "\n" in secret:
        raise ProviderError("auth")
    selected_endpoints = endpoints(trip, segment)
    if metres(*selected_endpoints) > 6_000_000:
        raise ProviderError("length")
    payload = {
        "coordinates": selected_endpoints,
        "units": "m",
        "preference": opts["preference"],
        "instructions": False,
    }
    if opts["avoid_features"]:
        payload["options"] = {"avoid_features": opts["avoid_features"]}
    request = urllib.request.Request(
        f"{PROVIDER}/{profile}/geojson",
        data=json.dumps(payload).encode(),
        headers={"Authorization": secret, "Content-Type": "application/json"},
        method="POST",
    )
    transport = opener or urllib.request.build_opener(NoRedirect()).open
    started = time.monotonic()
    try:
        with transport(request, timeout=8) as response:
            content = bytearray()
            while True:
                chunk = response.read(min(65536, MAX_BYTES + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > MAX_BYTES or time.monotonic() - started > 30:
                    raise ProviderError("invalid")
                report(
                    f"Connection {segment['properties']['sequence']}: "
                    f"receiving route, {len(content)} bytes checked."
                )
    except urllib.error.HTTPError as exc:
        code = None
        try:
            error = itinerary.decode_json(exc.read(8193))
            detail = error.get("error") if isinstance(error, dict) else None
            code = detail.get("code") if isinstance(detail, dict) else None
        except (OSError, http.client.HTTPException, UnicodeError, ValueError):
            pass
        category = (
            "auth"
            if exc.code in (401, 403)
            else "quota"
            if exc.code == 429
            else "length"
            if exc.code == 413 or code == 2004
            else "not-found"
            if code in (2009, 2010)
            else "connection"
            if exc.code >= 500
            else "invalid"
        )
        raise ProviderError(category) from None
    except ProviderError:
        raise
    except (OSError, urllib.error.URLError, http.client.HTTPException, UnicodeError):
        raise ProviderError("connection") from None
    try:
        raw = itinerary.decode_json(bytes(content))
    except (UnicodeError, ValueError):
        raise ProviderError("invalid") from None
    try:
        features = raw.get("features") if isinstance(raw, dict) else None
        if (
            not isinstance(raw, dict)
            or raw.get("type") != "FeatureCollection"
            or not isinstance(features, list)
            or len(features) != 1
        ):
            raise RouteError("Expected one provider route.")
        feature = features[0]
        if not isinstance(feature, dict):
            raise RouteError("Expected provider Feature object.")
        geometry = feature.get("geometry")
        properties = feature.get("properties", {})
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            raise RouteError("Expected provider LineString.")
        if not isinstance(properties, dict):
            raise RouteError("Expected provider properties object.")
        summary = properties.get("summary", {})
        if not isinstance(summary, dict):
            raise RouteError("Expected provider distance/duration object.")
        result = record_for(
            trip,
            segment,
            line(geometry.get("coordinates")),
            "provider",
            profile,
            metric(summary.get("distance")),
            metric(summary.get("duration")),
            cache_key=cache_key(trip, segment, profile, opts),
            attribution={
                "text": "Route: openrouteservice / © OpenStreetMap contributors",
                "licence": "ODbL / provider terms",
                "url": "https://openrouteservice.org/",
            },
        )
        return result
    except (RouteError, itinerary.ImportError):
        raise ProviderError("invalid") from None


def save_provider(root: Path, record: dict[str, Any]) -> None:
    folder = plan_workspace(root).cache_dir / "routes"
    folder.mkdir(exist_ok=True)
    atomic_json(folder / (record["cache_key"] + ".json"), record)


def load_choices(root: Path) -> dict[str, Any]:
    path = plan_workspace(root).metadata_dir / "route-choices.json"
    raw: dict[str, Any] = (
        read_json(path, MAX_BYTES) if path.exists() else {"schema_version": 1, "profiles": {}}
    )
    profiles = raw.get("profiles")
    if (
        raw.get("schema_version") != 1
        or not isinstance(profiles, dict)
        or len(profiles) > MAX_RECORDS
        or any(
            not isinstance(key, str) or value not in (*PROFILES, "direct")
            for key, value in profiles.items()
        )
    ):
        raise RouteError(
            "Saved route choices are malformed. Repair route-choices.json and recheck."
        )
    return raw


def save_choice(root: Path, key: str, profile: str, *, trip: dict[str, Any] | None = None) -> None:
    if profile not in (*PROFILES, "direct"):
        raise RouteError("Choose a supported routing profile or an explicit straight line.")
    path = plan_workspace(root).metadata_dir / "route-choices.json"
    raw = load_choices(root)
    if key not in raw["profiles"] and len(raw["profiles"]) >= MAX_RECORDS:
        if trip is not None:
            segments = itinerary.parts(trip, "segment")
            if len(segments) > MAX_RECORDS:
                raise RouteError("Trip exceeds 1,000 routing connections. Use a smaller trip.")
            current_keys = {segment_key(trip, segment) for segment in segments}
            if key not in current_keys:
                raise RouteError("The route choice does not belong to the current itinerary.")
            # Reclaim only obsolete strategies when capacity is exhausted; geometry caches stay.
            raw["profiles"] = {
                saved_key: value
                for saved_key, value in raw["profiles"].items()
                if saved_key in current_keys
            }
        if len(raw["profiles"]) >= MAX_RECORDS:
            raise RouteError("Too many saved route choices. Use a smaller trip.")
    raw["profiles"][key] = profile
    atomic_json(path, raw)


def clear_choices(root: Path, keys: list[str]) -> None:
    """Undo selected strategies while preserving manual assignments and provider caches."""
    raw = load_choices(root)
    for key in keys:
        raw["profiles"].pop(key, None)
    atomic_json(plan_workspace(root).metadata_dir / "route-choices.json", raw)
