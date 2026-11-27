"""Shared, transient dateline predicates; original geographic coordinates stay untouched."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from shapely.affinity import translate
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union


class Projection:
    """Preserve a common longitude window even with an explicit geographic CRS."""

    def __init__(self, transformer: Any, center: float) -> None:
        self.transformer = transformer
        self.center = center
        self.target_crs = transformer.target_crs
        self.period = (
            2 * math.pi / self.target_crs.axis_info[0].unit_conversion_factor
            if self.target_crs.is_geographic
            else 0
        )
        self.target_center = transformer.transform(center, 0)[0] if self.period else 0

    def transform(self, x: float, y: float) -> tuple[float, float]:
        if self.target_crs.is_geographic:
            x = self.center + (x - self.center + 180) % 360 - 180
        result_x, result_y = self.transformer.transform(x, y)
        if self.period:
            result_x = (
                self.target_center
                + (result_x - self.target_center + self.period / 2) % self.period
                - self.period / 2
            )
        return float(result_x), float(result_y)


@dataclass(frozen=True)
class Frame:
    """One physical viewport transform shared by readiness and SVG serialization."""

    projection: Any
    page_width: float
    page_height: float
    left: float
    top: float
    width: float
    height: float
    scale: float
    cx: float
    cy: float

    def point(self, coordinate: Any) -> tuple[float, float]:
        x, y = self.projection.transform(coordinate[0], coordinate[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(
                "Projection cannot represent a journey coordinate; choose auto projection."
            )
        return (
            self.left + self.width / 2 + (x - self.cx) * self.scale,
            self.top + self.height / 2 - (y - self.cy) * self.scale,
        )

    def contains(self, coordinate: Any) -> bool:
        x, y = self.point(coordinate)
        return (
            self.left - 1e-8 <= x <= self.left + self.width + 1e-8
            and self.top - 1e-8 <= y <= self.top + self.height + 1e-8
        )


def fit_frame(
    projection: Any,
    projected: list[list[float]],
    page: dict[str, Any],
    padding_percent: float,
    scale_settings: dict[str, Any] | None = None,
) -> Frame:
    width, height = page["width_mm"], page["height_mm"]
    if (page["orientation"] == "landscape" and width < height) or (
        page["orientation"] == "portrait" and width > height
    ):
        width, height = height, width
    from travelmap.reference_layout import viewport

    left, top, vw, vh = viewport(page, scale_settings or {})
    if min(vw, vh) <= 10:
        raise ValueError(
            "Page/margins leave too little room for the map; increase page dimensions."
        )
    xs, ys = [c[0] for c in projected], [c[1] for c in projected]
    minimum = (
        1000 / projection.target_crs.axis_info[0].unit_conversion_factor
        if projection.target_crs.is_projected
        else 0.01
    )
    if page.get("design", "standard") == "reference":
        minimum = 1.0  # FirstDraft's stop-extent floor in the explicit target CRS.
    sx, sy = max(max(xs) - min(xs), minimum), max(max(ys) - min(ys), minimum)
    pad = padding_percent / 100
    scale = min(vw / (sx * (1 + 2 * pad)), vh / (sy * (1 + 2 * pad)))
    return Frame(
        projection,
        width,
        height,
        left,
        top,
        vw,
        vh,
        scale,
        (min(xs) + max(xs)) / 2,
        (min(ys) + max(ys)) / 2,
    )


def _ring(coords: Any) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for x, y, *_ in coords:
        if result:
            # Shift the original coordinate by whole turns. Computing prev + modular
            # delta can erase small, representable segments through cancellation.
            x += round((result[-1][0] - x) / 360) * 360
            delta = x - result[-1][0]
            if abs(abs(delta) - 180) < 1e-10:
                raise ValueError(
                    "Ambiguous 180-degree geographic edge; select compatible geometry."
                )
        result.append((x, y))
    if coords[0] == coords[-1] and abs(result[0][0] - result[-1][0]) > 1e-8:
        raise ValueError(
            "Polar winding geometry is unsupported by this projection; "
            "select compatible boundaries."
        )
    return result


def components(geometry: Any) -> list[Any]:
    """Unwrap individual components and align holes with their exterior."""
    if geometry.is_empty:
        return []
    if geometry.geom_type.startswith("Multi") or geometry.geom_type == "GeometryCollection":
        return [part for child in geometry.geoms for part in components(child)]
    if geometry.bounds[2] - geometry.bounds[0] < 180:
        return [geometry]
    if geometry.geom_type == "LineString":
        return [LineString(_ring(geometry.coords))]
    if geometry.geom_type == "Polygon":
        shell = Polygon(_ring(geometry.exterior.coords))
        holes = []
        for interior in geometry.interiors:
            ring = Polygon(_ring(interior.coords))
            shift = round((shell.centroid.x - ring.centroid.x) / 360) * 360
            ring = translate(ring, xoff=shift)
            if not shell.covers(ring):
                raise ValueError("Geographic polygon hole is outside its exterior.")
            holes.append(list(ring.exterior.coords))
        return [Polygon(shell.exterior.coords, holes)]
    return [geometry]


def intersects(left: Any, right: Any) -> bool:
    """Test intersections in aligned component longitude windows."""
    for a in components(left):
        for b in components(right):
            shift = round((a.centroid.x - b.centroid.x) / 360) * 360
            if a.intersects(b if shift == 0 else translate(b, xoff=shift)):
                return True
    return False


class Region:
    """Prepare periodic component indexes once for country-scale background selection."""

    def __init__(self, geometries: list[Any]) -> None:
        from shapely.strtree import STRtree

        self.geometries = geometries
        parts = [part for geom in geometries for part in components(geom)]
        self.tree = STRtree(
            [
                translate(part, xoff=shift) if shift else part
                for part in parts
                for shift in (-360, 0, 360)
            ]
        )

    def intersects(self, geometry: Any, compare: Callable[[], None] | None = None) -> bool:
        for part in components(geometry):
            if part.bounds[2] - part.bounds[0] > 360:
                return any(intersects(g, geometry) for g in self.geometries)
            shift = round(part.centroid.x / 360) * 360
            candidate = translate(part, xoff=-shift) if shift else part
            if compare is None:
                if len(self.tree.query(candidate, predicate="intersects")):
                    return True
            else:
                for index in self.tree.query(candidate):
                    compare()
                    if candidate.intersects(self.tree.geometries[int(index)]):
                        return True
        return False

    def intersection(self, geometry: Any) -> Any:
        """Clip in aligned longitude windows without merging the whole country per feature."""
        from shapely import prepare
        from shapely.geometry import GeometryCollection, MultiLineString, MultiPolygon

        polygonal = geometry.geom_type in ("Polygon", "MultiPolygon")
        clipped = []
        for part in components(geometry):
            shift = round(part.centroid.x / 360) * 360
            candidate = translate(part, xoff=-shift) if shift else part
            indices = self.tree.query(candidate)
            regions = [self.tree.geometries[int(i)] for i in indices]
            for region in regions:
                prepare(region)
            if any(region.covers(candidate) for region in regions):
                clipped.append(candidate)
                continue
            if not regions:
                continue
            result = candidate.intersection(unary_union(regions))
            for piece in components(result):
                if (polygonal and piece.geom_type == "Polygon") or (
                    not polygonal and piece.geom_type == "LineString"
                ):
                    clipped.append(piece)
        if not clipped:
            return GeometryCollection()
        if len(clipped) == 1:
            return clipped[0]
        return MultiPolygon(clipped) if polygonal else MultiLineString(clipped)


def covered_by(regions: Any, geometry: Any, *, tolerance: float = 0) -> bool:
    """Cover every unwrapped component with a union of aligned region copies."""
    regions_ = list(regions.geoms) if hasattr(regions, "geoms") else [regions]
    for part in components(geometry):
        aligned = []
        for region in regions_:
            shift = round((part.centroid.x - region.centroid.x) / 360) * 360
            aligned.append(region if shift == 0 else translate(region, xoff=shift))
        union = unary_union(aligned)
        if tolerance:
            union = union.buffer(tolerance)
        if not union.covers(part):
            return False
    return True


def covers(left: Any, right: Any) -> bool:
    """Point/line/polygon coverage by geographic polygons."""
    return covered_by(unary_union(components(left)), right)


def coverage_geometry(envelopes: list[list[float]]) -> Any:
    """Preserve declared wide or wrapping intervals instead of guessing shorter arcs."""
    strips = []
    for west, south, east, north in envelopes:
        if not all(math.isfinite(c) for c in (west, south, east, north)) or not (
            -90 <= south <= north <= 90 and -180 <= west <= 180 and -180 <= east <= 180
        ):
            raise ValueError("Invalid source coverage envelope.")
        intervals = [(west, east)] if west <= east else [(west, 180), (-180, east)]
        for start, end in intervals:
            while start < end:
                next_ = min(start + 90, end)
                strips.append(box(start, south, next_, north))
                start = next_
    # Keep strips separate: union can erase vertices that preserve a wide directed interval.
    from shapely.geometry import GeometryCollection

    return GeometryCollection(strips)


def envelopes(geometry: Any) -> list[list[float]]:
    """Canonical index boxes for all unwrapped geographic components."""
    result = []
    for component in components(geometry):
        west, south, east, north = component.bounds
        shift = math.floor((west + 180) / 360) * 360
        west, east = west - shift, east - shift
        if east <= 180:
            result.append([west, south, east, north])
        else:
            result.extend([[west, south, 180, north], [-180, south, east - 360, north]])
    return result


def circular_center(coords: Any) -> tuple[float, float]:
    """Deterministic center of the minimum circular longitude span and latitude span."""
    longitudes = sorted(set(float(c[0]) % 360 for c in coords))
    if not longitudes:
        raise ValueError("No country coordinates available for framing.")
    gaps = [
        ((longitudes[(i + 1) % len(longitudes)] - x) % 360, i) for i, x in enumerate(longitudes)
    ]
    _, i = max(gaps)
    start = longitudes[(i + 1) % len(longitudes)]
    span = (longitudes[i] - start) % 360
    lon = (start + span / 2 + 180) % 360 - 180
    lat = (min(c[1] for c in coords) + max(c[1] for c in coords)) / 2
    return lon, lat


def projection(
    trip: dict[str, Any],
    resolved: dict[str, dict[str, Any]],
    settings: dict[str, Any],
    country_features: list[dict[str, Any]] | None = None,
) -> tuple[Any, list[list[float]]]:
    from pyproj import CRS, Transformer, network

    from travelmap import itinerary

    network.set_network_enabled(False)  # type: ignore[attr-defined]
    coords = [s["geometry"]["coordinates"][:2] for s in itinerary.parts(trip, "stop")]
    stop_framing = settings["map"].get("framing", "countries") == "stops"
    if not stop_framing:
        coords += [c for record in resolved.values() for c in record["coordinates"]]
    if country_features and not stop_framing:
        from shapely import get_coordinates
        from shapely.geometry import shape

        coords += [
            list(c)
            for feature in country_features
            for c in get_coordinates(shape(feature["geometry"]))
        ]
        lon, lat = circular_center(coords)
    else:
        lon = math.degrees(
            math.atan2(
                sum(math.sin(math.radians(c[0])) for c in coords),
                sum(math.cos(math.radians(c[0])) for c in coords),
            )
        )
        lat = sum(c[1] for c in coords) / len(coords)
    selected = settings["map"]["projection"]
    if selected == "auto":
        selected = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m"
    try:
        crs = CRS.from_user_input(selected)
        transform = Projection(Transformer.from_crs("EPSG:4326", crs, always_xy=True), lon)
        projected = [list(transform.transform(*c)) for c in coords]
        if any(not all(math.isfinite(v) for v in c) for c in projected):
            raise ValueError(
                "Chosen projection cannot represent all trip coordinates. Choose auto projection."
            )
    except ValueError:
        raise
    except Exception:
        raise ValueError(
            "Unable to project the selected trip. Choose auto projection and retry."
        ) from None
    return transform, projected
