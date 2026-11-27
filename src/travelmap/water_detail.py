"""Explicit topology-preserving water simplification in physical page coordinates."""

from __future__ import annotations

from collections.abc import Callable
from math import isfinite
from typing import Any

from pyproj import Geod
from shapely import get_num_coordinates
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, mapping, shape

from travelmap.mapstore import MAX_FEATURE_VERTICES


def simplify_on_page(
    geometry: dict[str, Any],
    point: Callable[[Any], tuple[float, float]],
    tolerance_mm: float,
) -> tuple[dict[str, Any], int, int]:
    """Retain every feature, polygon component and hole; leave cached WGS84 data intact."""
    if not isfinite(tolerance_mm) or not 0 < tolerance_mm <= 1:
        raise ValueError("Water simplification tolerance must be >0 and <=1 mm.")
    kind = geometry["type"]
    coords = geometry["coordinates"]
    projected: Any
    if kind == "LineString":
        projected = [point(c) for c in coords]
    elif kind in ("MultiLineString", "Polygon"):
        projected = [[point(c) for c in ring] for ring in coords]
    elif kind == "MultiPolygon":
        projected = [[[point(c) for c in ring] for ring in polygon] for polygon in coords]
    else:
        raise ValueError("Unsupported water geometry for simplification.")
    original = shape({"type": kind, "coordinates": projected})
    original_count = int(get_num_coordinates(original))
    if not original.is_valid or original.is_empty or original_count > MAX_FEATURE_VERTICES:
        raise ValueError(
            "Invalid projected water geometry; disable simplification or change projection."
        )
    simplified = original.simplify(tolerance_mm, preserve_topology=True)
    # GEOS unwraps singleton multi-geometries even when no component was removed.
    if kind == "MultiPolygon" and isinstance(simplified, Polygon):
        simplified = MultiPolygon([simplified])
    elif kind == "MultiLineString" and isinstance(simplified, LineString):
        simplified = MultiLineString([simplified])
    result_count = int(get_num_coordinates(simplified))
    if (
        simplified.is_empty
        or not simplified.is_valid
        or simplified.geom_type != kind
        or not 0 < result_count <= original_count
    ):
        raise ValueError("Water simplification cannot retain this feature; disable it and retry.")
    if isinstance(original, (Polygon, MultiPolygon)) and isinstance(
        simplified, (Polygon, MultiPolygon)
    ):
        before = [original] if isinstance(original, Polygon) else list(original.geoms)
        after = [simplified] if isinstance(simplified, Polygon) else list(simplified.geoms)
        if len(before) != len(after) or any(
            len(a.interiors) != len(b.interiors) for a, b in zip(before, after, strict=True)
        ):
            raise ValueError("Water simplification changed polygon components/holes; disable it.")
    if isinstance(original, MultiLineString) and isinstance(simplified, MultiLineString):
        if len(original.geoms) != len(simplified.geoms):
            raise ValueError("Water simplification changed line components; disable it.")
    return dict(mapping(simplified)), original_count, result_count


_GEOD = Geod(ellps="WGS84")


def area_km2(geometry: dict[str, Any]) -> float:
    """Geodesic area of original WGS84 water, subtracting holes regardless of winding."""
    kind = geometry["type"]
    if kind not in ("Polygon", "MultiPolygon"):
        raise ValueError("Water area filtering requires polygon geometry.")
    polygons = [geometry["coordinates"]] if kind == "Polygon" else geometry["coordinates"]
    total = 0.0
    for polygon in polygons:
        areas = []
        for ring in polygon:
            area, _ = _GEOD.polygon_area_perimeter([c[0] for c in ring], [c[1] for c in ring])
            areas.append(abs(area))
        net = areas[0] - sum(areas[1:])
        if not isfinite(net) or net < 0:
            raise ValueError("Invalid geodesic water area; disable area filtering and retry.")
        total += net
    return total / 1_000_000
