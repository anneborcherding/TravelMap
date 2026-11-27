"""Deterministic inert layered SVG from validated local map and route data."""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, BinaryIO

from travelmap import itinerary, mapdata, poster_settings, routes
from travelmap.reporting import Notice, restore_feedback
from travelmap.terminal import inert_text
from travelmap.workspace import plan_workspace

SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)


class ExportError(ValueError):
    """Expected export/readiness error with named recovery."""


def number(value: float) -> str:
    if not math.isfinite(value):
        raise ExportError(
            "Projection produced a non-finite coordinate. Choose auto projection and retry."
        )
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def node(parent: Any, tag: str, **attrs: Any) -> Any:
    return ET.SubElement(
        parent,
        "{" + SVG + "}" + tag,
        {key.replace("_", "-"): str(value) for key, value in sorted(attrs.items())},
    )


def projection(
    trip: dict[str, Any],
    resolved: dict[str, dict[str, Any]],
    settings: dict[str, Any],
    country_features: list[dict[str, Any]] | None = None,
) -> tuple[Any, list[list[float]]]:
    from travelmap.geography import projection as project

    try:
        return project(trip, resolved, settings, country_features)
    except ValueError as exc:
        raise ExportError(str(exc)) from exc


def render_svg_to(
    stream: BinaryIO,
    root: Path,
    trip: dict[str, Any],
    resolved: dict[str, dict[str, Any]],
    settings: dict[str, Any],
    selection: dict[str, Any],
    route_color: str | None = None,
    report: Callable[[str], None] = lambda _: None,
    readiness_key: str | None = None,
    readiness_token: dict[str, str] | None = None,
) -> list[str]:
    from shapely import get_num_coordinates
    from shapely.geometry import LineString, mapping, shape
    from shapely.ops import transform as transform_geometry
    from shapely.ops import unary_union

    from travelmap import duration, reference_layout

    itinerary.validate(trip)
    settings = poster_settings.validate(settings)
    for segment in itinerary.parts(trip, "segment"):
        key = routes.segment_key(trip, segment)
        if key not in resolved:
            raise ExportError(
                "Unresolved "
                + str(segment["properties"]["sequence"])
                + (": return to routing for local files/acquisition; no direct line is invented.")
            )
        routes.valid_record(resolved[key], routes.endpoints(trip, segment))
    from travelmap import validation_reuse

    reuse_readiness = False
    if readiness_key is not None:
        try:
            reuse_readiness = (
                validation_reuse.readiness_key(root, trip, resolved, settings, selection)
                == readiness_key
                and validation_reuse.readiness_matches(root, readiness_key)
                and validation_reuse.readiness_token(root, readiness_key) == readiness_token
                and readiness_token is not None
            )
        except (KeyError, TypeError, ValueError):
            reuse_readiness = False
    if selection.get("schema_version") == 2 and not reuse_readiness:
        mapdata.review_prepared_countries(
            root,
            trip,
            selection,
            settings["map"]["boundaries"].get("country_ids")
            or settings["map"]["boundaries"]["country_codes"]
            or None,
        )
    country_features = list(mapdata.iter_layer(root, selection, "countries"))
    from travelmap import map_view

    view = map_view.select(country_features, trip, resolved, settings, report)
    coverage_errors = [] if reuse_readiness else view.coverage_errors(selection, trip, resolved)
    if coverage_errors:
        raise ExportError("; ".join(coverage_errors))
    report(view.summary())
    frame = view.frame
    transform = frame.projection
    page, style, map_ = settings["poster"], settings["style"], settings["map"]
    width, height = frame.page_width, frame.page_height
    margin = page["margin_mm"]
    left, top = frame.left, frame.top
    viewport_width, viewport_height = frame.width, frame.height
    scale = frame.scale
    page_point = frame.point
    reference = page.get("design", "standard") == "reference"
    title_case = page.get("title_case") or ("uppercase" if reference else "preserve")
    title_position = page.get("title_position") or ("bottom" if reference else "top")
    title_bottom = title_position == "bottom"

    def path_geometry(geom: dict[str, Any], already_page: bool = False) -> str:
        kind = geom["type"]
        coordinates = geom["coordinates"]
        if kind == "LineString":
            rings = [coordinates]
        elif kind == "MultiLineString":
            rings = coordinates
        elif kind == "Polygon":
            rings = coordinates
        elif kind == "MultiPolygon":
            rings = [ring for polygon in coordinates for ring in polygon]
        else:
            raise ExportError("Unsupported prepared geometry; recheck map data.")
        values = []
        for ring in rings:
            points = ring if already_page else [page_point(c) for c in ring]
            if not points:
                continue
            values.append("M " + " L ".join(number(p[0]) + "," + number(p[1]) for p in points))
            if kind in ("Polygon", "MultiPolygon"):
                values.append("Z")
        return " ".join(values)

    document = ET.Element(
        "{" + SVG + "}svg",
        {
            "width": number(width) + "mm",
            "height": number(height) + "mm",
            "viewBox": f"0 0 {number(width)} {number(height)}",
            "version": "1.1",
        },
    )
    metadata = node(document, "metadata")
    provenance = []
    for source in selection["sources"]:
        provenance.append(
            {
                "source": Path(source["provenance"]["source"]["path"]).name,
                "hashes": source["provenance"]["hashes"],
                "version": source.get("source_version", {}),
                "attribution": source["attribution"],
                "geometry_repairs": source.get("geometry_repairs"),
            }
        )
    for record in resolved.values():
        if record.get("attribution"):
            provenance.append({"route_attribution": record["attribution"]})
    metadata.text = json.dumps(
        {
            "application": "TravelMap",
            "settings_signature": poster_settings.signature(settings),
            "display_settings": {
                "design": page.get("design", "standard"),
                "title_case": title_case,
                "title_position": title_position,
                "framing": map_.get("framing", "countries"),
                "fill_land": map_.get("fill_land", True),
            },
            "duration_source": duration.assess(
                trip, map_["distance"]["travel_days_override"]
            ).source,
            "map_selection": view.metadata,
            "background_layers": {
                "roads": map_["roads"]["enabled"],
                "water": map_["water"]["enabled"],
            },
            "water_detail": {
                "min_area_km2": map_["water"]["min_area_km2"],
                "line_classes": map_["water"]["line_classes"],
                "area_classes": map_["water"]["area_classes"],
                "simplify_geometry": map_["water"]["simplify_geometry"],
                "simplify_tolerance_mm": map_["water"]["simplify_tolerance_mm"],
            },
            "sources": provenance,
            "coverage_limits": selection.get("coverage_limits"),
            "approximate_routes": sum(r["approximate"] for r in resolved.values()),
            "nearby_route_merging": map_["routing"]["merge_nearby_routes"],
            "nearby_route_merge_tolerance_mm": map_["routing"]["nearby_route_merge_tolerance_mm"],
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    definitions = node(document, "defs")
    clip = node(definitions, "clipPath", id="map-viewport")
    node(
        clip,
        "rect",
        x=number(left),
        y=number(top),
        width=number(viewport_width),
        height=number(viewport_height),
    )
    background = node(document, "g", id="background")
    node(
        background,
        "rect",
        x="0",
        y="0",
        width=number(width),
        height=number(height),
        fill=style["background"],
    )
    written = 0

    def write(chunk: bytes) -> None:
        nonlocal written
        written += len(chunk)
        if written > 2 * 1024**3:
            raise ExportError(
                "SVG exceeds 2 GiB. Reduce visible layers/classes; preserve detail"
                " rather than silently simplifying it."
            )
        stream.write(chunk)

    opening = ET.tostring(document, encoding="utf-8").split(b">", 1)[0] + b">"
    write(b'<?xml version="1.0" encoding="utf-8"?>\n' + opening)
    for child in list(document):
        write(ET.tostring(child, encoding="utf-8"))
        document.remove(child)
    last = time.monotonic()
    rendered = 0
    water_stats: dict[str, dict[str, int]] = {}
    layer_order = (
        ([("land", "land")] if map_.get("fill_land", True) else [])
        + [
            ("admin1", "admin1"),
            ("roads", "roads"),
            ("water_lines", "water-lines"),
            ("water_areas", "water-areas"),
            ("countries", "boundaries"),
        ]
        if reference
        else [
            ("countries", "boundaries"),
            ("admin1", "admin1"),
            ("roads", "roads"),
            ("water_areas", "water-areas"),
            ("water_lines", "water-lines"),
        ]
    )

    if not map_.get("show_state_borders", False):
        layer_order = [(kind, layer) for kind, layer in layer_order if kind != "admin1"]

    def page_transform(x: float, y: float, z: float | None = None) -> tuple[float, float]:
        return frame.point((x, y))

    reference_boundaries = []
    if reference and map_["show_country_borders"]:
        boundaries = []
        vertex_count = 0
        for feature in view.countries:
            polygon = transform_geometry(page_transform, shape(feature["geometry"]))
            vertex_count += int(get_num_coordinates(polygon))
            if vertex_count > map_view.MAX_COORDINATES:
                raise ExportError("Country boundaries exceed two million vertices; reduce detail.")
            boundaries.append(polygon.boundary)
        combined_boundaries = unary_union(boundaries)
        if get_num_coordinates(combined_boundaries) > map_view.MAX_COORDINATES:
            raise ExportError("Country boundary union exceeds two million vertices; reduce detail.")
        if not combined_boundaries.is_empty:
            reference_boundaries = [{"geometry": mapping(combined_boundaries), "properties": {}}]
    for kind, group_name in layer_order:
        source_kind = "countries" if kind == "land" else kind
        group = node(document, "g", id=group_name, clip_path="url(#map-viewport)")
        group_open = ET.tostring(group, encoding="utf-8")[:-3] + b">"
        write(group_open)
        document.remove(group)
        if source_kind not in selection["layers"]:
            write(b"</g>")
            continue
        if (
            kind == "roads"
            and not map_["roads"]["enabled"]
            or kind.startswith("water")
            and not map_["water"]["enabled"]
        ):
            write(b"</g>")
            continue
        features = (
            iter(reference_boundaries)
            if kind == "countries" and reference
            else iter(view.countries)
            if source_kind == "countries"
            else mapdata.iter_layer(root, selection, source_kind)
        )
        for feature in features:
            if (
                kind == "countries"
                and selection.get("schema_version") != 2
                and map_["boundaries"]["country_codes"]
                and feature["properties"].get("code") not in map_["boundaries"]["country_codes"]
            ):
                continue
            class_field = {
                "roads": "highway",
                "water_lines": "waterway",
                "water_areas": "water_type",
            }.get(kind)
            if class_field is not None:
                allowed = (
                    map_["roads"]["highway_classes"]
                    if kind == "roads"
                    else map_["water"]["line_classes"]
                    if kind == "water_lines"
                    else map_["water"]["area_classes"]
                )
                if feature["properties"].get(class_field) not in allowed:
                    continue
            geom = shape(feature["geometry"])
            if geom.is_empty:
                raise ExportError("Invalid cached geometry; recheck map data.")
            if source_kind != "countries":
                geom = view.clip(geom, f"{kind} feature {feature.get('id', 'unknown')}")
                if geom.is_empty:
                    continue
            attrs = {}
            if kind in ("countries", "admin1", "land"):
                attrs = {
                    "fill": style["land"]
                    if kind == "land"
                    or (kind == "countries" and not reference and map_.get("fill_land", True))
                    else "none",
                    "stroke": style["border"]
                    if map_["show_country_borders"] and kind != "land"
                    else "none",
                    "stroke_width": number(style["boundary_width_mm"]),
                    "fill_rule": "evenodd",
                }
                if reference:
                    attrs.update(stroke_linecap="round", stroke_linejoin="round")
            elif kind == "roads":
                attrs = {
                    "fill": "none",
                    "stroke": style["road"],
                    "stroke_width": number(style["road_width_mm"]),
                    "opacity": number(style["road_opacity"]),
                }
            elif kind == "water_lines":
                attrs = {
                    "fill": "none",
                    "stroke": style["water_line"],
                    "stroke_width": number(style["water_width_mm"]),
                    "opacity": number(style["water_line_opacity"]),
                }
            else:
                attrs = {
                    "fill": style["water_area"],
                    "stroke": "none",
                    "opacity": number(style["water_area_opacity"]),
                    "fill_rule": "evenodd",
                }
            geometry = mapping(geom)
            already_page = kind == "countries" and reference
            if kind.startswith("water") and (
                map_["water"]["simplify_geometry"] or map_["water"]["min_area_km2"] > 0
            ):
                from travelmap.water_detail import area_km2, simplify_on_page

                before = int(get_num_coordinates(geom))
                stats = water_stats.setdefault(
                    kind,
                    {
                        "features": 0,
                        "filtered_features": 0,
                        "filtered_vertices": 0,
                        "original_vertices": 0,
                        "output_vertices": 0,
                    },
                )
                stats["original_vertices"] += before
                try:
                    if kind == "water_areas" and map_["water"]["min_area_km2"] > 0:
                        if area_km2(geometry) < map_["water"]["min_area_km2"]:
                            stats["filtered_features"] += 1
                            stats["filtered_vertices"] += before
                            if time.monotonic() - last >= 5:
                                report(
                                    f"Export: {rendered} rendered; "
                                    f"{stats['filtered_features']} small water areas filtered."
                                )
                                last = time.monotonic()
                            continue
                    after = before
                    if map_["water"]["simplify_geometry"]:
                        geometry, before, after = simplify_on_page(
                            geometry, page_point, map_["water"]["simplify_tolerance_mm"]
                        )
                        already_page = True
                except ValueError as exc:
                    raise ExportError(f"{feature['id']}: {exc}") from exc
                stats["features"] += 1
                stats["output_vertices"] += after
            element = node(group, "path", d="PATH_CONTENT", **attrs)
            prefix, suffix = ET.tostring(element, encoding="utf-8").split(b"PATH_CONTENT", 1)
            write(prefix)
            kind_ = geometry["type"]
            coordinates = geometry["coordinates"]
            rings = (
                [coordinates]
                if kind_ == "LineString"
                else [ring for polygon in coordinates for ring in polygon]
                if kind_ == "MultiPolygon"
                else coordinates
            )
            for ring in rings:
                for index, c in enumerate(ring):
                    x, y = c if already_page else page_point(c)
                    write((("M " if index == 0 else " L ") + number(x) + "," + number(y)).encode())
                if kind_ in ("Polygon", "MultiPolygon"):
                    write(b"Z")
                write(b" ")
            write(suffix)
            group.remove(element)
            rendered += 1
            if time.monotonic() - last >= 5:
                report(f"Export: {rendered} background features rendered.")
                last = time.monotonic()
        write(b"</g>")
    if water_stats:
        detail = node(document, "metadata", id="water-detail")
        detail.text = json.dumps(water_stats, sort_keys=True)
        for layer, stats in water_stats.items():
            report(
                f"Water detail / {layer}: {stats['original_vertices']:,} -> "
                f"{stats['output_vertices']:,} vertices at "
                f"{map_['water']['simplify_tolerance_mm']} mm; "
                f"{stats['features']:,} retained; {stats['filtered_features']:,} filtered "
                f"below {map_['water']['min_area_km2']} km². Original caches retained."
            )
    route_group = node(document, "g", id="routes", clip_path="url(#map-viewport)")
    by_style: dict[tuple[str, str], list[Any]] = {}
    for segment in itinerary.parts(trip, "segment"):
        record = resolved[routes.segment_key(trip, segment)]
        mode = segment["properties"]["transport_mode"]
        color = style["route_colors_by_mode"].get(mode, route_color or style["route"])
        dash = style["route_dash_patterns"].get(
            mode, {"air": "3 2", "ferry": "2 1", "train": "1 1"}.get(mode, "")
        )
        coords = [page_point(c) for c in record["coordinates"]]
        if all(c == coords[0] for c in coords):
            continue
        by_style.setdefault((color, dash), []).append(LineString(coords))
    from shapely.geometry import mapping

    for (color, dash), lines in sorted(by_style.items()):
        try:
            combined = reference_layout.merge_routes(
                lines,
                map_["routing"]["nearby_route_merge_tolerance_mm"]
                if map_["routing"]["merge_nearby_routes"]
                else None,
            )
        except ValueError as exc:
            raise ExportError(str(exc)) from exc
        attrs = {
            "fill": "none",
            "stroke": color,
            "stroke_width": number(style["route_width_mm"]),
            "opacity": number(style["route_opacity"]),
            "stroke_linecap": "round",
            "stroke_linejoin": "round",
        }
        if dash:
            attrs["stroke_dasharray"] = dash
        node(
            route_group,
            "path",
            d=path_geometry(dict(mapping(combined)), already_page=True),
            **attrs,
        )
    stops_group = node(document, "g", id="stops", clip_path="url(#map-viewport)")
    labels = node(
        document,
        "g",
        id="labels",
        font_family=style["font_family"] + ", Arial, sans-serif",
        fill=style["label"],
    )
    label_stops = sorted(
        itinerary.parts(trip, "stop"),
        key=lambda s: (
            s["properties"].get("label_priority") is None,
            -(s["properties"].get("label_priority") or 0),
            s["properties"]["sequence"],
        ),
    )
    for stop in label_stops:
        x, y = page_point(stop["geometry"]["coordinates"])
        if map_["show_stop_markers"]:
            node(
                stops_group,
                "circle",
                cx=number(x),
                cy=number(y),
                r=number(style["stop_radius_mm"]),
                fill=style["stop"],
            )
        if map_["show_place_labels"]:
            label = node(
                labels,
                "text",
                x=number(x + style["stop_radius_mm"] + 1),
                y=number(y - 1),
                font_size="3.5",
            )
            label.text = inert_text(stop["properties"]["name"])
    title = node(document, "g", id="title", fill=style["label"])
    title_size, subtitle_size = poster_settings.font_sizes(settings)
    if title_bottom:
        _, title_y, subtitle_y = reference_layout.footer_positions(frame, map_["scale"])
    else:
        title_y, subtitle_y = margin + 12, margin + 22
    title_subtitle_gap = style.get("title_subtitle_gap_mm")
    if title_subtitle_gap is not None:
        subtitle_y = title_y + title_subtitle_gap
    heading = node(
        title,
        "text",
        x=number(width / 2),
        y=number(title_y),
        text_anchor="middle",
        font_family=style["title_font_family"] + (", serif" if reference else ", Georgia, serif"),
        font_size=f"{title_size:g}",
        **({"letter_spacing": "0.7"} if reference else {}),
    )
    heading.text = inert_text(page["title"].upper() if title_case == "uppercase" else page["title"])
    subtitle, warnings = poster_settings.metric_text(trip, resolved, settings)
    sub = node(
        title,
        "text",
        x=number(width / 2),
        y=number(subtitle_y),
        text_anchor="middle",
        font_family=(
            style["title_font_family"] + ", serif"
            if reference
            else style["font_family"] + ", Arial, sans-serif"
        ),
        font_size=f"{subtitle_size:g}",
    )
    sub.text = inert_text(subtitle)
    scale_group = node(document, "g", id="scale")
    bar = map_["scale"]
    if title_bottom:
        document.remove(title)
        document.append(title)
    if reference and bar["enabled"]:
        _reference_scale(scale_group, frame, bar, style, warnings)
        document.remove(scale_group)
        document.insert(list(document).index(title), scale_group)
    elif bar["enabled"]:
        # Auto projection uses metres; explicit projected CRS unit factors are accounted for.
        factor = transform.target_crs.axis_info[0].unit_conversion_factor
        length = (
            bar["distance_km"] * 1000 / factor * scale
            if transform.target_crs.is_projected
            else float("inf")
        )
        if (
            not math.isfinite(length)
            or length + 2 * bar["inset_mm"] > viewport_width
            or bar["height_mm"] > 10
        ):
            warnings.append(
                "Approximate scale bar omitted: cannot fit this page/projection. "
                "Reduce distance/height or disable it."
            )
        else:
            position = bar["position"]
            inset = bar["inset_mm"]
            x = (
                width / 2 - length / 2
                if position == "footer-center"
                else left + inset
                if position.endswith("left")
                else left + viewport_width - inset - length
            )
            y = (
                top + inset
                if position.startswith("top")
                else top + viewport_height + 8
                if position == "footer-center" and title_bottom
                else height - margin - 8
                if position == "footer-center"
                else top + viewport_height - inset - bar["height_mm"]
            )
            for i in range(bar["segments"]):
                node(
                    scale_group,
                    "rect",
                    x=number(x + length * i / bar["segments"]),
                    y=number(y),
                    width=number(length / bar["segments"]),
                    height=number(bar["height_mm"]),
                    fill=(bar["color"] or style["border"]) if i % 2 == 0 else style["background"],
                    stroke=bar["color"] or style["border"],
                    stroke_width="0.2",
                )
            label = node(
                scale_group,
                "text",
                x=number(x + length / 2),
                y=number(y - 2 if bar["number_position"] == "top" else y + bar["height_mm"] + 4),
                text_anchor="middle",
                font_size="3",
                font_family=style["font_family"] + ", Arial, sans-serif",
                fill=bar["color"] or style["label"],
            )
            label.text = f"{bar['distance_km']:g} km {inert_text(bar['caption'])}"
            warnings.append(
                Notice("Scale bar is approximate: projected scale varies across the map.")
            )
    if reference and not bar["enabled"]:
        document.remove(scale_group)
        document.insert(list(document).index(title), scale_group)
    if map_["routing"]["merge_nearby_routes"]:
        warnings.append(
            Notice(
                "Nearby route merging approximates linework within the explicitly "
                "selected page-space tolerance."
            )
        )
    for child in document:
        write(ET.tostring(child, encoding="utf-8"))
    write(b"</svg>")
    report(
        f"Export rendered {rendered:,} background features "
        f"and {len(resolved)} resolved connections."
    )
    return warnings


def _reference_scale(
    group: Any, frame: Any, bar: dict[str, Any], style: dict[str, Any], warnings: list[str]
) -> None:
    """Draw reference scale labels and outline using locally geodesic width."""
    from travelmap.reference_layout import footer_positions, scale_width

    footer = bar["position"] == "footer-center"
    inset = bar["inset_mm"]
    anchor_x = (
        frame.page_width / 2
        if footer
        else frame.left + frame.width - inset
        if bar["position"].endswith("right")
        else frame.left + inset
    )
    y = (
        footer_positions(frame, bar)[0]
        if footer
        else frame.top + inset
        if bar["position"].startswith("top")
        else frame.top + frame.height - inset
    )
    direction = -1 if bar["position"].endswith("right") else 1
    length = scale_width(
        frame, bar["distance_km"], anchor_x, frame.top + frame.height if footer else y, direction
    )
    if length is None or bar["height_mm"] > 10:
        warnings.append(
            "Reference scale omitted: cannot fit this page/projection; reduce distance."
        )
        return
    x = anchor_x - length / 2 if footer else anchor_x - length if direction < 0 else anchor_x
    if x < frame.left + inset or x + length > frame.left + frame.width - inset:
        warnings.append("Reference scale omitted: cannot fit map width; reduce distance or inset.")
        return
    foreground = bar["color"] or style["border"]
    text_color = bar["color"] or style["label"]
    # FirstDraft applies these to the complete surveyor-rule group, including
    # segment edges and label strokes, rather than only the outside rectangle.
    group.set("stroke", foreground)
    group.set("stroke-width", number(style["boundary_width_mm"]))
    group.set("font-family", style["font_family"] + ", sans-serif")
    group.set("fill", text_color)
    label_y = y - 3 if bar["number_position"] == "top" else y + bar["height_mm"] + 3
    caption = node(
        group,
        "text",
        x=number(frame.page_width / 2 if footer else x),
        y=number(y - 8 if bar["number_position"] == "top" else y - 2),
        font_size="2.5",
        letter_spacing="0.25",
        text_anchor="middle" if footer else "start",
        font_family=style["font_family"] + ", sans-serif",
        fill=text_color,
    )
    caption.text = inert_text(bar["caption"])
    for index in range(bar["segments"]):
        node(
            group,
            "rect",
            x=number(x + index * length / bar["segments"]),
            y=number(y),
            width=number(length / bar["segments"]),
            height=number(bar["height_mm"]),
            fill=foreground if index % 2 == 0 else style["background"],
        )
    node(
        group,
        "path",
        d=f"M {number(x)} {number(y)} H {number(x + length)} "
        f"V {number(y + bar['height_mm'])} H {number(x)} Z",
        fill="none",
        stroke=foreground,
        stroke_width=number(style["boundary_width_mm"]),
    )
    for index in range(bar["segments"] + 1):
        label = node(
            group,
            "text",
            x=number(x + index * length / bar["segments"]),
            y=number(label_y),
            font_size="2.5",
            text_anchor="middle",
            font_family=style["font_family"] + ", sans-serif",
            fill=text_color,
        )
        label.text = number(index * bar["distance_km"] / bar["segments"]) + (
            " km" if index == bar["segments"] else ""
        )
    warnings.append(Notice("Scale bar is local: projected scale varies across the map."))


def svg_bytes(
    root: Path,
    trip: dict[str, Any],
    resolved: dict[str, dict[str, Any]],
    settings: dict[str, Any],
    selection: dict[str, Any],
    route_color: str | None = None,
    report: Callable[[str], None] = lambda _: None,
) -> tuple[bytes, list[str]]:
    """Small-fixture compatibility adapter; production export writes a streamed file."""
    from io import BytesIO

    stream = BytesIO()
    warnings = render_svg_to(stream, root, trip, resolved, settings, selection, route_color, report)
    return stream.getvalue(), warnings


def export_svg(
    path: Path,
    root: Path,
    trip: dict[str, Any],
    resolved: dict[str, dict[str, Any]],
    settings: dict[str, Any],
    selection: dict[str, Any],
    route_color: str | None = None,
    report: Callable[[str], None] = lambda _: None,
    replace: bool = False,
    readiness_token: dict[str, str] | None = None,
) -> list[str]:
    """Supervise native cache consumption/export, then atomically publish completed artwork."""
    from travelmap import validation_reuse

    paths = plan_workspace(root)
    from travelmap.mapdata_guidance import accepted_trip

    def accepted_inputs_match() -> bool:
        try:
            current_trip = accepted_trip(root)
            current_settings = poster_settings.load(root, trip)
            accepted_path = paths.metadata_dir / "settings-accepted.json"
            accepted = mapdata.read_json(accepted_path, mapdata.MIB)
            current_resolved, missing = routes.resolve(root, trip, report)
        except (OSError, ValueError, KeyError, TypeError):
            return False
        return (
            current_trip == trip
            and not missing
            and current_resolved == resolved
            and poster_settings.signature(current_settings) == poster_settings.signature(settings)
            and accepted.get("signature") == poster_settings.signature(current_settings)
        )

    if not accepted_inputs_match():
        raise ExportError("Trip, routes or accepted design changed; return to Export and recheck.")
    control_paths = [
        paths.metadata_dir / name
        for name in (
            "itinerary.geojson",
            "poster-settings.json",
            "settings-accepted.json",
            "map-settings.json",
            "map-data.json",
            "boundary-review.json",
            "manual-assignments.json",
            "route-choices.json",
            "routing-settings.json",
            "validation-reuse.json",
        )
    ]
    # The file is authoritative even before derived metadata has been reloaded.
    # Watch it through publication so an external edit cannot publish stale artwork.
    control_paths.append(root / "config.toml")
    route_options = routes.settings(root)
    if route_options.get("cache"):
        control_paths.append(root / route_options["cache"])
    for record in resolved.values():
        source_file = record.get("source_file")
        if isinstance(source_file, str) and source_file != "@itinerary":
            control_paths.append(root / source_file)
        cache_key = record.get("cache_key")
        if isinstance(cache_key, str):
            control_paths.append(paths.cache_dir / "routes" / f"{cache_key}.json")
    control_snapshot = validation_reuse.optional_file_snapshot(control_paths)
    if control_snapshot is None:
        raise ExportError("A route or settings file is redirected; recheck the workspace.")
    with mapdata.verification_operation():
        checked = mapdata.inspect_prepared(root, report)
        if not checked or checked["key"] != selection["key"]:
            raise ExportError("Prepared selection changed; recheck map data.")
        if (
            not accepted_inputs_match()
            or validation_reuse.optional_file_snapshot(control_paths) != control_snapshot
        ):
            raise ExportError("Trip, routes or design changed before rendering; retry preflight.")
        readiness_key = readiness_token.get("input_sha256") if readiness_token is not None else None
        if readiness_token is not None:
            current_key = validation_reuse.readiness_key(root, trip, resolved, settings, checked)
            if (
                current_key != readiness_key
                or not validation_reuse.readiness_matches(root, current_key)
                or validation_reuse.readiness_token(root, current_key) != readiness_token
            ):
                raise ExportError("Route or map readiness changed; return to Export and recheck.")
        source_records = mapdata.discover(root, mapdata.settings_for(root))
        source_paths: list[Path] = []
        for source in source_records:
            source_path = Path(source["path"])
            source_paths.append(source_path)
            if source_path.suffix.lower() == ".shp":
                source_paths.extend(
                    source_path.with_suffix(suffix) for suffix in (".shx", ".dbf", ".prj")
                )
        source_snapshot = validation_reuse.file_snapshot(source_paths)
        if source_snapshot is None:
            raise ExportError("A source path is redirected or unavailable; recheck map data.")
        store_names = [selection.get("directory")]
        source_entries = selection.get("sources")
        if not isinstance(source_entries, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("directory"), str)
            for item in source_entries
        ):
            raise ExportError("Prepared source selection is malformed; recheck map data.")
        store_names.extend(item["directory"] for item in source_entries)
        if any(not isinstance(name, str) for name in store_names):
            raise ExportError("Prepared selection contains an invalid store identifier.")
        store_paths: list[Path] = []
        repair_paths: list[Path] = []
        watched_databases: list[Path] = []
        for store_name in sorted({name for name in store_names if isinstance(name, str)}):
            if Path(store_name).name != store_name or store_name in {".", ".."}:
                raise ExportError("Prepared selection contains an unsafe store path.")
            store_directory = paths.cache_dir / "map-data" / store_name
            watched_databases.append(store_directory / "features.sqlite")
            store_paths.extend(
                (store_directory / "features.sqlite", store_directory / "manifest.json")
            )
            repair_paths.append(store_directory / "repair-originals.sqlite")
        if any(
            validation_reuse.has_sidecars(database)
            for database in (*watched_databases, *repair_paths)
        ):
            raise ExportError("A prepared SQLite store has journal sidecars; recover it and retry.")
        store_snapshot = validation_reuse.file_snapshot(store_paths)
        repair_snapshot = validation_reuse.optional_file_snapshot(repair_paths)
        if store_snapshot is None or repair_snapshot is None:
            raise ExportError("A prepared store changed path; recheck map data.")
        database = paths.cache_dir / "map-data" / selection["directory"] / "features.sqlite"
        identity = mapdata.file_identity(database) if database.exists() else None
        repair_database = database.with_name("repair-originals.sqlite")
        repair_identity = (
            mapdata.file_identity(repair_database) if repair_database.exists() else None
        )
        if validation_reuse.has_sidecars(database) or validation_reuse.has_sidecars(
            repair_database
        ):
            raise ExportError("Map cache has SQLite journal sidecars; recover it and retry.")
        with tempfile.TemporaryDirectory(prefix=".export-", dir=paths.cache_dir) as temp:
            staging = Path(temp)
            result = mapdata.run_worker(
                {
                    "action": "export",
                    "root": str(root),
                    "trip": trip,
                    "resolved": resolved,
                    "settings": settings,
                    "selection": selection,
                    "route_color": route_color,
                    "readiness_key": readiness_key,
                    "readiness_token": readiness_token,
                },
                staging,
                report,
            )
            try:
                feedback = restore_feedback(
                    result.get("warnings"), result.get("notice_indices", [])
                )
            except ValueError as exc:
                raise ExportError(str(exc)) from exc
            if (
                result.get("readiness_key") != readiness_key
                or result.get("readiness_token") != readiness_token
            ):
                raise ExportError("Export worker did not confirm the current readiness token.")
            if (
                (mapdata.file_identity(database) if database.exists() else None) != identity
                or (mapdata.file_identity(repair_database) if repair_database.exists() else None)
                != repair_identity
                or validation_reuse.has_sidecars(database)
                or validation_reuse.has_sidecars(repair_database)
                or validation_reuse.file_snapshot(source_paths) != source_snapshot
                or validation_reuse.file_snapshot(store_paths) != store_snapshot
                or validation_reuse.optional_file_snapshot(repair_paths) != repair_snapshot
                or any(
                    validation_reuse.has_sidecars(database)
                    for database in (*watched_databases, *repair_paths)
                )
            ):
                raise ExportError("Map cache changed during export; recheck data.")
            if readiness_token is not None:
                current_key = validation_reuse.readiness_key(
                    root, trip, resolved, settings, checked
                )
                if (
                    current_key != readiness_key
                    or validation_reuse.readiness_token(root, current_key) != readiness_token
                ):
                    raise ExportError("Validated inputs changed during export; retry preflight.")

            def current_inputs_match() -> bool:
                if (
                    (mapdata.file_identity(database) if database.exists() else None) != identity
                    or (
                        mapdata.file_identity(repair_database) if repair_database.exists() else None
                    )
                    != repair_identity
                    or validation_reuse.has_sidecars(database)
                    or validation_reuse.has_sidecars(repair_database)
                    or validation_reuse.file_snapshot(source_paths) != source_snapshot
                    or validation_reuse.file_snapshot(store_paths) != store_snapshot
                    or validation_reuse.optional_file_snapshot(repair_paths) != repair_snapshot
                    or any(
                        validation_reuse.has_sidecars(database)
                        for database in (*watched_databases, *repair_paths)
                    )
                    or validation_reuse.optional_file_snapshot(control_paths) != control_snapshot
                ):
                    return False
                if readiness_token is None:
                    return True
                latest_key = validation_reuse.readiness_key(root, trip, resolved, settings, checked)
                return (
                    latest_key == readiness_key
                    and validation_reuse.readiness_token(root, latest_key) == readiness_token
                )

            def guard() -> AbstractContextManager[None]:
                if readiness_token is None:
                    return validation_reuse.snapshot_guard(current_inputs_match)
                return validation_reuse.publication_guard(
                    root, readiness_token, current_inputs_match
                )

            try:
                write_svg(path, staging / "poster.svg", replace, guard)
            except ValueError as exc:
                raise ExportError(str(exc)) from exc
        return feedback


def write_svg(
    path: Path,
    content: bytes | Path,
    replace: bool = False,
    publish_guard: Callable[[], AbstractContextManager[None]] | None = None,
) -> None:
    if path.suffix.lower() != ".svg":
        raise ExportError(
            "Only SVG export is supported. Open the SVG in an editor "
            "and export PDF there for printing."
        )
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.exists() and not replace:
            raise ExportError(
                f"{path.name}: output exists. Choose a new name or explicitly confirm replacement."
            )
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            if isinstance(content, Path):
                import shutil

                with content.open("rb") as source:
                    shutil.copyfileobj(source, stream, 1024 * 1024)
            else:
                stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

        def publish() -> None:
            if replace:
                os.replace(temporary, path)
            else:
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    raise ExportError(
                        "Output appeared during export. Choose a new filename or confirm "
                        "replacement."
                    ) from None

        if publish_guard is None:
            publish()
        else:
            with publish_guard():
                publish()
    except OSError as exc:
        raise ExportError(
            f"Cannot write {path.name}: {exc}. Check folder "
            f"permissions/disk space, choose another destination, "
            f"or pause."
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class OutputBatch:
    """Retain existing artwork through an incomplete multi-variant replacement run."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.backups: dict[Path, Path] = {}
        self.completed = False
        self.temporary: Any = None

    def __enter__(self) -> OutputBatch:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix=".export-backup-", dir=self.directory)
        return self

    def protect(self, path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise ExportError("Replacement requires a regular existing SVG, not a link/directory.")
        backup = Path(self.temporary.name) / str(len(self.backups))
        try:
            os.link(path, backup)
        except OSError as exc:
            raise ExportError(
                "Cannot preserve existing artwork for this batch. Choose a new filename."
            ) from exc
        self.backups[path] = backup

    def commit(self) -> None:
        self.completed = True

    def __exit__(self, *args: Any) -> None:
        try:
            if not self.completed:
                for path, backup in self.backups.items():
                    os.replace(backup, path)
        finally:
            self.temporary.cleanup()
