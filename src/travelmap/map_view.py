"""Bounded, transient offshore selection shared by preparation, readiness and export."""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pyproj import Geod, Transformer
from shapely import get_coordinates, get_num_coordinates, normalize
from shapely.affinity import translate
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
    mapping,
    shape,
)
from shapely.geometry.polygon import orient
from shapely.ops import nearest_points, transform
from shapely.strtree import STRtree
from shapely.validation import explain_validity

from travelmap import geography, itinerary

RULE_VERSION = 1
ZONE_METRES = 22_224.0
DISTANCE_TOLERANCE_M = 1.0
MAX_COMPONENTS = 20_000
MAX_COORDINATES = 2_000_000
MAX_COMPONENT_COORDINATES = 100_000
MAX_COMPARISONS = 200_000
MAX_ROUTE_COORDINATES = 500_000
GEOD = Geod(ellps="WGS84")


class ViewError(ValueError):
    """Invalid or excessive geometry, with previous artifacts left intact."""


@dataclass
class Budget:
    comparisons: int = 0
    samples: int = 0
    report: Callable[[str], None] = lambda _: None
    last_report: float = 0

    def compare(self) -> None:
        self.comparisons += 1
        if time.monotonic() - self.last_report >= 5:
            self.report(
                f"Offshore selection: {self.comparisons:,} comparisons; "
                f"{self.samples:,} transient coordinates."
            )
            self.last_report = time.monotonic()
        if self.comparisons > MAX_COMPARISONS:
            raise ViewError(
                "Offshore selection exceeds 200,000 comparisons; use simpler boundaries."
            )

    def sample(self, count: int) -> None:
        self.samples += count
        if self.samples > MAX_COORDINATES:
            raise ViewError(
                "Offshore proximity exceeds two million samples; use simpler boundaries."
            )


@dataclass
class Component:
    country: str
    identifier: str
    geometry: Any
    feature: dict[str, Any]
    reason: str = "excluded"


def country_id(feature: dict[str, Any]) -> str:
    code = feature["properties"].get("code")
    return str(code) if code and code != "-99" else str(feature["id"])


def _aligned(geometry: Any, longitude: float) -> Any:
    shift = round((longitude - geometry.centroid.x) / 360) * 360
    return translate(geometry, xoff=shift) if shift else geometry


def _densify(line: Any, budget: Budget) -> Any:
    """Transient geodesic coastline segments, at most 2 km long."""
    if line.geom_type == "MultiLineString":
        return MultiLineString([_densify(part, budget) for part in line.geoms])
    coordinates = list(line.coords)
    output = [coordinates[0]]
    for a, b in zip(coordinates, coordinates[1:], strict=False):
        distance = GEOD.inv(a[0], a[1], b[0], b[1])[2]
        count = max(0, math.ceil(distance / 2000) - 1)
        budget.sample(count + 1)
        if count:
            points = GEOD.npts(a[0], a[1], b[0], b[1], count)
            for x, y in points:
                x += round((output[-1][0] - x) / 360) * 360
                output.append((x, y))
        x, y = b[:2]
        x += round((output[-1][0] - x) / 360) * 360
        output.append((x, y))
    return LineString(output)


def _coastal_distance(main_coast: Any, island_coast: Any, budget: Budget) -> float:
    # All candidate points lie in one half-degree tile plus the 22 km search zone.
    # Local AEQD scale distortion is under the 1 m classification tolerance;
    # refine the closest pair around its midpoint for the final WGS84 measurement.
    a, b = nearest_points(main_coast, island_coast)
    lon, lat = (a.x + b.x) / 2, (a.y + b.y) / 2
    distance = math.inf
    for _ in range(4):
        budget.compare()
        project = Transformer.from_crs(
            4326,
            f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m",
            always_xy=True,
        )
        inverse = Transformer.from_crs(project.target_crs, 4326, always_xy=True)
        left, right = (
            transform(project.transform, main_coast),
            transform(project.transform, island_coast),
        )
        if not all(math.isfinite(v) for v in (*left.bounds, *right.bounds)):
            raise ViewError("Offshore proximity cannot project this coastline; use full inclusion.")
        p, q = nearest_points(left, right)
        aa, bb = inverse.transform(p.x, p.y), inverse.transform(q.x, q.y)
        updated = float(GEOD.inv(*aa, *bb)[2])
        if abs(updated - distance) < 0.001:
            return updated
        distance = updated
        lon = aa[0] + ((bb[0] - aa[0] + 180) % 360 - 180) / 2
        lat = (aa[1] + bb[1]) / 2
    return distance


def nearby(mainland: Any, island: Any, budget: Budget, coast: Any = None) -> bool:
    """WGS84 proximity over bounded local coastline tiles, not just source vertices."""
    budget.compare()
    island = _aligned(island, mainland.centroid.x)
    if mainland.intersects(island):
        return True
    if coast is None:
        coast = _densify(mainland.boundary, budget)
    # Densify before spatial pruning: a long geodesic edge may bow poleward beyond
    # the source-vertex envelope. Keep these samples transient, never in artwork.
    island_coast = _densify(island.boundary, budget)
    west, south, east, north = island_coast.bounds
    latitude = (ZONE_METRES + DISTANCE_TOLERANCE_M) / 110_000
    for row in range(math.floor(south * 2), math.floor(north * 2) + 1):
        low = row / 2
        poleward = min(90, max(abs(low), abs(low + 0.5)) + latitude)
        longitude = min(180, latitude / max(math.cos(math.radians(poleward)), 1e-8))
        for column in range(math.floor(west * 2), math.floor(east * 2) + 1):
            budget.compare()
            left = column / 2
            tile = box(left, low, left + 0.5, low + 0.5)
            island_piece = island_coast.intersection(tile)
            if island_piece.is_empty:
                continue
            window = box(
                left - longitude,
                max(-90, low - latitude),
                left + 0.5 + longitude,
                min(90, low + 0.5 + latitude),
            )
            main_piece = coast.intersection(window)
            if main_piece.is_empty:
                continue
            if _coastal_distance(main_piece, island_piece, budget) <= (
                ZONE_METRES + DISTANCE_TOLERANCE_M
            ):
                return True
    return False


def _components(features: list[dict[str, Any]]) -> list[Component]:
    result: dict[tuple[str, str], Component] = {}
    total = 0
    for feature in features:
        # Check aggregate geometry size before materializing coordinates/index copies.
        geometry = shape(feature["geometry"])
        count = int(get_num_coordinates(geometry))
        total += count
        if total > MAX_COORDINATES:
            raise ViewError("Offshore boundaries exceed two million coordinates; use simpler data.")
        coords = get_coordinates(geometry)
        if any(not math.isfinite(v) for c in coords for v in c):
            raise ViewError("Country geometry contains non-finite coordinates; recheck boundaries.")
        if any(not -180 <= c[0] <= 180 or not -90 <= c[1] <= 90 for c in coords):
            raise ViewError("Country coordinates must be WGS84 longitude/latitude.")
        country = country_id(feature)
        for part in geography.components(geometry):
            if len(result) >= MAX_COMPONENTS:
                raise ViewError("Offshore boundaries exceed 20,000 components; use simpler data.")
            if part.geom_type != "Polygon" or part.is_empty or not part.is_valid:
                raise ViewError("Invalid country polygon; supply compatible boundaries.")
            if get_num_coordinates(part) > MAX_COMPONENT_COORDINATES:
                raise ViewError("Country component exceeds 100,000 coordinates; use simpler data.")
            # Canonicalize the periodic window and ring ordering for stable identities.
            part = _aligned(part, 0)
            identifier = hashlib.sha256(normalize(part).wkb).hexdigest()
            result.setdefault((country, identifier), Component(country, identifier, part, feature))
    return [result[key] for key in sorted(result)]


def _groups(parts: list[Component], budget: Budget) -> list[list[int]]:
    """Exact cross-border connected components with periodic index pruning."""
    geometries = [translate(p.geometry, xoff=s) for p in parts for s in (-360, 0, 360)]
    tree = STRtree(geometries)
    parent = list(range(len(parts)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, part in enumerate(parts):
        for index in tree.query(part.geometry):
            budget.compare()
            j = int(index) // 3
            if j <= i or parts[j].country == part.country:
                continue
            if part.geometry.intersects(geometries[int(index)]):
                a, b = root(i), root(j)
                parent[max(a, b)] = min(a, b)
    groups: dict[int, list[int]] = {}
    for i in range(len(parts)):
        groups.setdefault(root(i), []).append(i)
    return list(groups.values())


def _dimension(geometry: Any, polygonal: bool) -> Any:
    """Keep the original dimension in projected coordinates after clipping.

    ``geography.components`` unwraps longitude windows, so it must only be used
    before projection. These intersections are already in projected coordinates.
    """
    wanted = "Polygon" if polygonal else "LineString"
    if geometry.geom_type == wanted or geometry.is_empty:
        return geometry
    if hasattr(geometry, "geoms"):
        pieces = [part for child in geometry.geoms for part in _dimension_parts(child, wanted)]
        if not pieces:
            return GeometryCollection()
        return MultiPolygon(pieces) if polygonal else MultiLineString(pieces)
    return GeometryCollection()


def _dimension_parts(geometry: Any, wanted: str) -> list[Any]:
    """Recursively collect projected clipping results of the requested type."""
    if geometry.geom_type == wanted:
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [part for child in geometry.geoms for part in _dimension_parts(child, wanted)]
    return []


def _project_geometry(geometry: Any, projection: Any, context: str = "map layer") -> Any:
    """Project bounded input and reject invalid/nonfinite display geometry."""
    result = transform(projection.transform, geometry)
    if any(not math.isfinite(v) for c in get_coordinates(result) for v in c):
        raise ViewError(
            "Projection cannot represent selected map geometry; choose auto projection."
        )
    if not result.is_empty and not result.is_valid:
        raise ViewError(
            f"Invalid projected geometry in {context}: {explain_validity(result)}. "
            f"Projection: {projection.target_crs.to_string()}; "
            f"input type: {geometry.geom_type}; "
            f"input validity: {explain_validity(geometry)}; "
            f"input longitude/latitude bounds: {geometry.bounds}. "
            "Choose another projection or recheck the stated source geometry."
        )
    return result


@dataclass
class ProjectedFootprint:
    """Country mask clipped in the actual projected rectangle, as in FirstDraft."""

    geometry: Any
    frame: geography.Frame
    inverse: Any

    def clip(self, geometry: Any, context: str = "map layer") -> Any:
        projected = _project_geometry(geometry, self.frame.projection, context)
        clipped = _dimension(
            projected.intersection(self.geometry), geometry.geom_type in ("Polygon", "MultiPolygon")
        )
        if get_num_coordinates(clipped) > 1_000_000:
            raise ViewError("Projected clipping exceeds one million vertices; reduce layers.")
        return transform(self.inverse.transform, clipped)


def _reference_footprint(
    countries: list[dict[str, Any]], frame: geography.Frame
) -> tuple[list[dict[str, Any]], ProjectedFootprint]:
    """Produce visible countries and a shared mask without changing source features."""
    west = frame.cx - frame.width / (2 * frame.scale)
    east = frame.cx + frame.width / (2 * frame.scale)
    south = frame.cy - frame.height / (2 * frame.scale)
    north = frame.cy + frame.height / (2 * frame.scale)
    rectangle = box(west, south, east, north)
    inverse = Transformer.from_crs(frame.projection.target_crs, 4326, always_xy=True)
    geographic_window = _reference_geographic_window(west, south, east, north, inverse)
    try:
        window_region = (
            geography.Region([geographic_window]) if geographic_window is not None else None
        )
    except ValueError:
        window_region = None
    visible = []
    projected_parts = []
    vertices = 0
    for feature in countries:
        source_geometry = shape(feature["geometry"])
        if window_region is not None:
            if not window_region.intersects(source_geometry):
                continue
            source_geometry = window_region.intersection(source_geometry)
            if source_geometry.is_empty:
                continue
        projected = _project_geometry(
            source_geometry, frame.projection, f"country {country_id(feature)}"
        )
        clipped = _dimension(projected.intersection(rectangle), True)
        if clipped.is_empty:
            continue
        vertices += int(get_num_coordinates(clipped))
        if vertices > MAX_COORDINATES:
            raise ViewError(
                "Projected countries exceed two million vertices; use simpler boundaries."
            )
        projected_parts.append(clipped)
        visible.append({**feature, "geometry": mapping(transform(inverse.transform, clipped))})
    from shapely.ops import unary_union

    mask = unary_union(projected_parts)
    if get_num_coordinates(mask) > MAX_COORDINATES:
        raise ViewError(
            "Projected country union exceeds two million vertices; use simpler boundaries."
        )
    return visible, ProjectedFootprint(mask, frame, inverse)


def _reference_geographic_window(
    west: float, south: float, east: float, north: float, inverse: Any
) -> Any | None:
    """Approximate the inverse-projected viewport for safe pre-projection clipping."""
    steps = 128
    corners = ((west, south), (east, south), (east, north), (west, north))
    coordinates: list[tuple[float, float]] = []
    try:
        for index, start in enumerate(corners):
            end = corners[(index + 1) % len(corners)]
            for step in range(steps):
                fraction = step / steps
                x = start[0] + (end[0] - start[0]) * fraction
                y = start[1] + (end[1] - start[1]) * fraction
                longitude, latitude = inverse.transform(x, y)
                if not math.isfinite(longitude) or not math.isfinite(latitude):
                    return None
                if coordinates:
                    longitude += round((coordinates[-1][0] - longitude) / 360) * 360
                coordinates.append((longitude, latitude))
        footprint = Polygon(coordinates)
        if footprint.is_empty or not footprint.is_valid:
            return None
        # This small geographic cushion makes the sampled inverse edge conservative;
        # final clipping still uses the exact projected rectangle.
        footprint = footprint.buffer(0.02)
        if footprint.is_empty or not footprint.is_valid:
            return None
        return footprint
    except (OverflowError, ValueError):
        return None


@dataclass
class MapView:
    countries: list[dict[str, Any]]
    frame: geography.Frame
    metadata: dict[str, Any]
    region: geography.Region
    clipped_vertices: int = 0
    background_enabled: bool = True
    projected_footprint: ProjectedFootprint | None = None

    def clip(self, geometry: Any, context: str = "map layer") -> Any:
        """Clip background only; routes never pass through this method."""
        if get_num_coordinates(geometry) > 1_000_000:
            raise ViewError("Background exceeds one million vertices; use simpler layers.")
        clipped = (
            self.projected_footprint.clip(geometry, context)
            if self.projected_footprint
            else self.region.intersection(geometry)
        )
        count = int(get_num_coordinates(clipped))
        self.clipped_vertices += count
        if self.clipped_vertices > 100_000_000:
            raise ViewError("Display clipping exceeds 100 million total vertices; reduce layers.")
        if count > 1_000_000:
            raise ViewError("Display clipping exceeds one million vertices; use simpler layers.")
        return clipped

    def coverage_errors(
        self, selection: dict[str, Any], trip: dict[str, Any], resolved: dict[str, dict[str, Any]]
    ) -> list[str]:
        if (
            not self.background_enabled
            or selection.get("coverage_check") == "unknown"
            or not selection.get("enabled_layers")
        ):
            return []
        covered = geography.coverage_geometry(selection.get("coverage_envelopes", []))
        missing = sum(
            not geography.covered_by(covered, shape(f["geometry"])) for f in self.countries
        )
        errors = []
        if missing:
            errors.append(
                f"Coverage incomplete for {missing} displayed country components. "
                "Supply covering extracts and recheck map data."
            )
        geometries: list[Any] = [
            Point(s["geometry"]["coordinates"][:2]) for s in itinerary.parts(trip, "stop")
        ]
        geometries.extend(
            LineString(r["coordinates"]) for r in resolved.values() if len(r["coordinates"]) > 1
        )
        if any(not geography.covered_by(covered, g) for g in geometries):
            errors.append(
                "Trip crosses an uncovered source envelope; download covering "
                "regional extracts and recheck map data."
            )
        return errors

    def summary(self) -> str:
        return summary_from_metadata(self.metadata)


def summary_from_metadata(metadata: dict[str, Any]) -> str:
    """Render a current-language summary from bounded readiness receipt fields."""
    counts = metadata["counts"]
    mode = (
        "all offshore components"
        if metadata["include_offshore_components"]
        else "12-nautical-mile mainland zone, trip and connected land; islands fitting the map"
    )
    summary = (
        f"Map islands: {mode}. {counts['included']} included; "
        f"{counts['excluded']} excluded; {counts['trip']} trip-protected."
    )
    if metadata["journey_expanded_frame"]:
        summary += (
            " Journeys extend beyond the displayed-country frame; "
            "review displayed countries and source coverage."
        )
    return summary


def select(
    features: list[dict[str, Any]],
    trip: dict[str, Any],
    resolved: dict[str, dict[str, Any]],
    settings: dict[str, Any],
    report: Callable[[str], None] = lambda _: None,
) -> MapView:
    budget = Budget(report=report)
    parts = _components(features)
    include_all = settings["map"].get("include_offshore_components", False)
    by_country: dict[str, list[Component]] = {}
    for part in parts:
        by_country.setdefault(part.country, []).append(part)
    trip_coords = [s["geometry"]["coordinates"][:2] for s in itinerary.parts(trip, "stop")]
    if sum(len(r["coordinates"]) for r in resolved.values()) > MAX_ROUTE_COORDINATES:
        raise ViewError("Trip exceeds 500,000 route coordinates; use simpler routes.")
    journeys: list[Any] = [Point(c) for c in trip_coords]
    journeys.extend(
        LineString(r["coordinates"]) for r in resolved.values() if len(r["coordinates"]) > 1
    )
    trip_region = geography.Region(journeys)
    for country_parts in by_country.values():
        mainland = min(
            country_parts,
            key=lambda p: (
                -abs(GEOD.geometry_area_perimeter(orient(p.geometry, sign=1))[0]),
                p.identifier,
            ),
        )
        coast = None if include_all else _densify(mainland.geometry.boundary, budget)
        for part in country_parts:
            if include_all:
                part.reason = "all"
            elif part is mainland:
                part.reason = "mainland"
            elif trip_region.intersects(part.geometry, budget.compare):
                part.reason = "trip"
            elif nearby(mainland.geometry, part.geometry, budget, coast):
                part.reason = "proximity"
    groups = _groups(parts, budget) if not include_all else [[i] for i in range(len(parts))]
    for group in groups:
        if any(parts[i].reason != "excluded" for i in group):
            for i in group:
                if parts[i].reason == "excluded":
                    parts[i].reason = "cross_border"

    def feature_for(part: Component) -> dict[str, Any]:
        # Source coordinates are retained in a periodic longitude window for dateline
        # serialization. Geographic predicates already support that window.
        return {**part.feature, "geometry": mapping(part.geometry)}

    base = [feature_for(p) for p in parts if p.reason != "excluded"]
    project, projected = geography.projection(trip, resolved, settings, base)
    frame = geography.fit_frame(
        project,
        projected,
        settings["poster"],
        settings["map"]["padding_percent"],
        settings["map"]["scale"],
    )
    if settings["map"].get("framing", "countries") == "stops" and any(
        not frame.contains(c) for record in resolved.values() for c in record["coordinates"]
    ):
        raise ViewError(
            "Resolved routes extend outside the stop-fitted map. Set map.framing to countries "
            "or increase map padding before exporting; journey geometry was preserved."
        )
    for group in groups:
        if any(parts[i].reason != "excluded" for i in group):
            continue
        fits = True
        for i in group:
            for c in get_coordinates(parts[i].geometry):
                budget.sample(1)
                x, y = frame.point(c)
                if not (
                    frame.left - 1e-8 <= x <= frame.left + frame.width + 1e-8
                    and frame.top - 1e-8 <= y <= frame.top + frame.height + 1e-8
                ):
                    fits = False
                    break
            if not fits:
                break
        if fits:
            for i in group:
                parts[i].reason = "frame"
    countries = [feature_for(p) for p in parts if p.reason != "excluded"]
    projected_footprint = None
    if settings["poster"].get("design", "standard") == "reference":
        countries, projected_footprint = _reference_footprint(countries, frame)
    counts = {
        key: sum(p.reason == key for p in parts)
        for key in ("all", "mainland", "trip", "proximity", "cross_border", "frame", "excluded")
    }
    counts["included"] = len(parts) - counts["excluded"]
    # Preserve country-review guidance even though complete journeys now expand the
    # actual frame instead of being clipped to a country-only viewport.
    country_frame = None
    if base:
        country_points = [
            list(project.transform(*c)) for f in base for c in get_coordinates(shape(f["geometry"]))
        ]
        country_frame = geography.fit_frame(
            project,
            country_points,
            settings["poster"],
            settings["map"]["padding_percent"],
            settings["map"]["scale"],
        )
    expanded = country_frame is not None and any(
        not country_frame.contains(c) for r in resolved.values() for c in r["coordinates"]
    )
    metadata = {
        "journey_expanded_frame": expanded,
        "framing": settings["map"].get("framing", "countries"),
        "design": settings["poster"].get("design", "standard"),
        "visible_components": len(countries),
        "rule_version": RULE_VERSION,
        "include_offshore_components": include_all,
        "counts": counts,
        "components": [
            {"country": p.country, "component": p.identifier, "reason": p.reason} for p in parts
        ],
        "projection": project.target_crs.to_string(),
        "projected_bounds": [
            frame.cx - frame.width / (2 * frame.scale),
            frame.cy - frame.height / (2 * frame.scale),
            frame.cx + frame.width / (2 * frame.scale),
            frame.cy + frame.height / (2 * frame.scale),
        ],
    }
    return MapView(
        countries,
        frame,
        metadata,
        geography.Region([shape(f["geometry"]) for f in countries]),
        background_enabled=(
            settings["map"]["roads"]["enabled"] or settings["map"]["water"]["enabled"]
        ),
        projected_footprint=projected_footprint,
    )
