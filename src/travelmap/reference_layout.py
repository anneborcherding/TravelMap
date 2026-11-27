"""Physical reference layout, geodesic scale sizing and bounded route linework."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from pyproj import Geod, Transformer
from shapely import get_num_coordinates
from shapely.geometry import GeometryCollection, LineString
from shapely.ops import snap, unary_union

if TYPE_CHECKING:
    from travelmap.geography import Frame

MAX_SNAP_WORK = 100_000_000
MAX_ROUTE_VERTICES = 500_000
MAX_UNION_VERTICES = 2_000_000


def viewport(page: dict[str, Any], scale: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return the page-space map rectangle for the chosen physical design."""
    width, height = float(page["width_mm"]), float(page["height_mm"])
    if (page["orientation"] == "landscape" and width < height) or (
        page["orientation"] == "portrait" and width > height
    ):
        width, height = height, width
    margin = float(page["margin_mm"])
    design = page.get("design", "standard")
    title_position = page.get("title_position") or ("bottom" if design == "reference" else "top")
    if title_position == "bottom":
        footer = 50 if scale.get("enabled") and scale.get("position") == "footer-center" else 30
        return margin, margin, width - 2 * margin, height - 2 * margin - footer
    return margin, margin + 28, width - 2 * margin, height - 2 * margin - 48


def footer_positions(frame: Frame, scale: dict[str, Any]) -> tuple[float, float, float]:
    """Return reference scale top and title/subtitle baselines in millimeters."""
    bottom = frame.top + frame.height
    footer_scale = scale["enabled"] and scale["position"] == "footer-center"
    title_y = bottom + (38 if footer_scale else 18)
    return bottom + 16, title_y, title_y + 7


def scale_width(
    frame: Frame, distance_km: float, x_mm: float, y_mm: float, direction: int
) -> float | None:
    """Measure a projected horizontal displacement by WGS84 geodesic distance.

    Like FirstDraft, this measures at the map-bottom midpoint for a centered footer,
    before centering the resulting bar. It is a local scale, not a global guarantee.
    """
    inverse = Transformer.from_crs(frame.projection.target_crs, "EPSG:4326", always_xy=True)
    x = frame.cx + (x_mm - frame.left - frame.width / 2) / frame.scale
    y = frame.cy - (y_mm - frame.top - frame.height / 2) / frame.scale
    edge_x = frame.cx + direction * frame.width / (2 * frame.scale)
    start = inverse.transform(x, y)
    end = inverse.transform(edge_x, y)
    if not all(math.isfinite(v) for v in (*start, *end)):
        return None
    geod = Geod(ellps="WGS84")
    maximum = geod.inv(*start, *end)[2]
    target = distance_km * 1000
    if not math.isfinite(maximum) or maximum < target:
        return None
    low, high = 0.0, 1.0
    for _ in range(48):
        middle = (low + high) / 2
        candidate = inverse.transform(x + (edge_x - x) * middle, y)
        distance = geod.inv(*start, *candidate)[2]
        if not math.isfinite(distance):
            return None
        if distance < target:
            low = middle
        else:
            high = middle
    return abs(edge_x - x) * high * frame.scale


def _nearby_references(
    line: LineString, previous: Sequence[Any], tolerance: float
) -> tuple[list[Any], int]:
    """Keep prior routes whose envelopes can contain a snap target.

    A prior route whose envelope is disjoint from the source envelope expanded by
    the snap tolerance cannot contribute any reference vertex within tolerance.
    Retaining whole routes and their order preserves GEOS's coordinate traversal.
    """
    west, south, east, north = line.bounds
    pad = tolerance + max(1e-12, max(abs(v) for v in (west, south, east, north)) * 1e-14)
    west, south, east, north = west - pad, south - pad, east + pad, north + pad
    selected = []
    work = 0
    for route in previous:
        work += 1
        rw, rs, re, rn = route.bounds
        if rw <= east and re >= west and rs <= north and rn >= south:
            selected.append(route)
            work += int(get_num_coordinates(route))
            west, south, east, north = min(west, rw), min(south, rs), max(east, re), max(north, rn)
    return selected, work


def merge_routes(lines: Sequence[LineString], tolerance_mm: float | None) -> Any:
    """Snap later page-space lines to previously snapped lines, then dissolve.

    Charge repeated reference construction against a cumulative coordinate budget.
    Canonical route coordinates and metrics are never changed by this operation.
    """
    if sum(int(get_num_coordinates(line)) for line in lines) > MAX_ROUTE_VERTICES:
        raise ValueError("Route drawing exceeds 500,000 vertices; use simpler route inputs.")
    snapped: list[LineString] = []
    work = 0
    snapped_vertices = 0
    for line in lines:
        result = line
        if tolerance_mm is not None:
            candidates, filter_work = _nearby_references(line, snapped, tolerance_mm)
            work += filter_work + int(get_num_coordinates(line))
            if work > MAX_SNAP_WORK:
                raise ValueError(
                    "Route snapping work budget exceeded; disable nearby merging "
                    "or simplify routes."
                )
            reference = GeometryCollection(candidates)
            result = line if reference.is_empty else snap(line, reference, tolerance_mm)
            if result.geom_type != "LineString":
                raise ValueError("Route snapping produced unsupported linework; disable merging.")
        snapped_vertices += int(get_num_coordinates(result))
        if snapped_vertices > MAX_UNION_VERTICES:
            raise ValueError("Route snapping output exceeds two million vertices; disable merging.")
        snapped.append(result)
    combined = unary_union(snapped)
    if get_num_coordinates(combined) > MAX_UNION_VERTICES:
        raise ValueError("Route union exceeds two million vertices; use simpler routes.")
    return combined
