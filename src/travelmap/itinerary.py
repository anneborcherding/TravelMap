"""Bounded offline itinerary import and deterministic normalized persistence."""

import copy
import hashlib
import io
import json
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from travelmap.reporting import Notice

MAX_BYTES = 8 * 1024 * 1024
MAX_FEATURES = 5000
MAX_VERTICES = 100000
MODES = ("air", "bus", "car", "ferry", "train", "walk")
K = "{http://www.opengis.net/kml/2.2}"


class TransportMode(StrEnum):
    AIR = "air"
    BUS = "bus"
    CAR = "car"
    FERRY = "ferry"
    TRAIN = "train"
    WALK = "walk"


class ImportError(ValueError):
    """An actionable input error, never a provider failure."""


def read_bytes(path: Path) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise ImportError("Select a regular file, not a link or directory.")
        with path.open("rb") as stream:
            content = stream.read(MAX_BYTES + 1)
    except OSError as exc:
        raise ImportError(
            f"{path.name}: cannot read file: {exc}. Check permissions and recheck."
        ) from exc
    if len(content) > MAX_BYTES:
        raise ImportError(f"{path.name}: exceeds 8 MiB. Export a smaller trip and recheck.")
    return content


def decode_json(content: bytes) -> Any:
    text = content.decode("utf-8-sig")
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 32:
                raise ImportError("JSON depth exceeds 32. Export a smaller, simpler trip.")
        elif char in "]}":
            depth -= 1

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ImportError(f"Duplicate JSON field {key!r}. Correct the export.")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=pairs)


def coordinate(values: Any) -> list[float]:
    if not isinstance(values, (list, tuple)) or len(values) not in (2, 3):
        raise ImportError("Coordinate needs longitude, latitude and optional altitude.")
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) for v in values):
        raise ImportError("Coordinate values must be finite numbers.")
    try:
        finite = all(math.isfinite(value) for value in values)
    except OverflowError:
        finite = False
    if not finite:
        raise ImportError("Coordinate values must be finite numbers within numeric range.")
    if not -180 <= values[0] <= 180 or not -90 <= values[1] <= 90:
        raise ImportError("Coordinate outside WGS84 longitude/latitude range.")
    return list(values)


def feature(kind: str, properties: dict[str, Any], coordinates: Any) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"feature_type": kind, **properties},
        "geometry": {
            "type": "Point" if kind == "stop" else "LineString",
            "coordinates": coordinates,
        },
    }


def text(node: ET.Element, name: str) -> str:
    child = node.find(K + name)
    return (child.text or "").strip() if child is not None else ""


def fields(node: ET.Element) -> dict[str, str]:
    result = {}
    for item in node.findall(K + "ExtendedData/" + K + "Data"):
        key = item.get("name")
        if not key or key in result:
            raise ImportError("Missing or duplicate ExtendedData field name.")
        result[key] = text(item, "value")
    for item in node.findall(K + "ExtendedData/" + K + "SchemaData/" + K + "SimpleData"):
        key = item.get("name")
        if not key or key in result:
            raise ImportError("Missing or duplicate ExtendedData field name.")
        result[key] = (item.text or "").strip()
    return result


def sequence(features: list[dict[str, Any]]) -> str:
    supplied = [f["properties"].get("sequence") for f in features]
    if any(v is not None for v in supplied):
        try:
            if any(
                isinstance(v, bool) or not re.fullmatch(r"[1-9][0-9]*", str(v)) for v in supplied
            ):
                raise ValueError("invalid sequence")
            values = [int(str(v)) for v in supplied]
        except (ValueError, TypeError) as exc:
            raise ImportError("Sequence metadata must be complete positive integers.") from exc
        if sorted(values) != list(range(1, len(features) + 1)):
            raise ImportError("Sequences must be unique and consecutive starting at 1.")
        for f, value in zip(features, values, strict=False):
            f["properties"]["sequence"] = value
        features.sort(key=lambda f: f["properties"]["sequence"])
        return "explicit sequence metadata"
    for index, f in enumerate(features, 1):
        f["properties"]["sequence"] = index
    return "document order"


def kml_candidates(content: bytes, filename: str) -> list[tuple[dict[str, Any], list[str]]]:
    decoded = content.decode("utf-8-sig")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", decoded, re.I):
        raise ImportError("Unsafe XML declaration. Export KML without DOCTYPE or ENTITY.")
    depth = count = 0
    parser = ET.iterparse(io.StringIO(decoded), events=("start", "end"))
    for event, _node in parser:
        if event == "start":
            depth += 1
            count += 1
            if depth > 32 or count > 50000:
                raise ImportError("XML exceeds depth 32 or 50,000 elements. Export a smaller trip.")
        else:
            depth -= 1
    root = cast(ET.Element, parser.root)  # type: ignore[attr-defined]
    if root.tag != K + "kml":
        raise ImportError("Expected KML 2.2 namespace. Export a KML 2.2 file.")
    document = root.find(K + "Document")
    if document is None:
        raise ImportError("Missing KML Document. Export a supported itinerary.")
    all_marks = list(document.iter(K + "Placemark"))
    if len(all_marks) > MAX_FEATURES:
        raise ImportError("More than 5,000 placemarks. Export a smaller trip.")
    explicit_ids = [mark.get("id") for mark in all_marks if mark.get("id")]
    if len(explicit_ids) != len(set(explicit_ids)):
        raise ImportError("Duplicate explicit placemark IDs. Give each feature a unique ID.")
    positions = {id(mark): index for index, mark in enumerate(all_marks, 1)}

    def groups(node: ET.Element) -> list[ET.Element]:
        children = [
            child
            for child in node.findall(K + "Folder")
            if any(m.find(K + "Point") is not None for m in child.iter(K + "Placemark"))
        ]
        if len(children) > 1 and not node.findall(K + "Placemark"):
            return children
        if len(children) == 1 and not node.findall(K + "Placemark"):
            return groups(children[0])
        return [node]

    candidates = []
    for node in groups(document):
        stops, segments, unassigned, unsupported = [], [], [], []
        for mark in node.iter(K + "Placemark"):
            label = text(mark, "name") or f"Stop {positions[id(mark)]}"
            data = fields(mark)
            geometries = [
                child
                for child in mark
                if child.tag
                in {K + g for g in ("Point", "LineString", "Polygon", "MultiGeometry", "Model")}
                or child.tag.endswith("Track")
            ]
            if len(geometries) != 1 or geometries[0].tag not in (K + "Point", K + "LineString"):
                unsupported.append(label)
                continue
            geometry = geometries[0]
            raw = text(geometry, "coordinates").split()
            if len(raw) > 10000:
                raise ImportError(f"{label}: more than 10,000 vertices. Export a simpler line.")
            try:
                coords = [coordinate([float(v) for v in item.split(",")]) for item in raw]
            except (ValueError, ImportError) as exc:
                raise ImportError(
                    f"{label}: invalid coordinates: {exc}. Correct and recheck."
                ) from exc
            props: dict[str, Any] = {
                "name": label,
                "notes": data.get("note") or text(mark, "description") or None,
                "custom": data,
            }
            if data.get("sequence"):
                props["sequence"] = data["sequence"]
            if geometry.tag == K + "Point":
                if len(coords) != 1 or data.get("feature_type", "stop") != "stop":
                    raise ImportError(f"{label}: expected one stop Point coordinate.")
                arrival = data.get("arrival_date")
                timestamp = mark.find(K + "TimeStamp")
                if not arrival and timestamp is not None:
                    arrival = text(timestamp, "when")
                description = text(mark, "description")
                match = re.search(
                    r"\b(\d{1,2})(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(\d{4})\b",
                    description,
                    re.I,
                )
                if not arrival and match:
                    months = (
                        "jan",
                        "feb",
                        "mar",
                        "apr",
                        "may",
                        "jun",
                        "jul",
                        "aug",
                        "sep",
                        "oct",
                        "nov",
                        "dec",
                    )
                    month = months.index(match[2].lower()) + 1
                    arrival = f"{int(match[3]):04d}-{month:02d}-{int(match[1]):02d}"
                props.update(
                    id=data.get("id") or mark.get("id") or f"visit-{positions[id(mark)]}",
                    country=data.get("country") or "Unknown",
                    arrival_date=arrival,
                    label_priority=int(data["label_priority"])
                    if data.get("label_priority")
                    else None,
                )
                stops.append(feature("stop", props, coords[0]))
            else:
                if len(coords) < 2:
                    raise ImportError(f"{label}: a line needs at least two vertices.")
                if (
                    data.get("feature_type") == "segment"
                    or data.get("origin_id")
                    or data.get("destination_id")
                ):
                    props.update(
                        origin_id=data.get("origin_id"),
                        destination_id=data.get("destination_id"),
                        transport_mode=data.get("transport_mode", "car").lower(),
                        mode_assumed=not bool(data.get("transport_mode")),
                        embedded_geometry=True,
                    )
                    segments.append(feature("segment", props, coords))
                else:
                    unassigned.append(feature("unassigned", props, coords))
        order = sequence(stops)
        if segments:
            sequence(segments)
        trip = {
            "type": "FeatureCollection",
            "metadata": {
                "schema_version": 1,
                "name": text(node, "name") or text(document, "name") or Path(filename).stem,
                "notes": text(node, "description") or None,
                "custom": fields(document),
                "order_source": order,
            },
            "features": stops + segments + unassigned,
        }
        validate(trip, generate=True)
        candidates.append((trip, unsupported))
    return candidates


def validate(trip: dict[str, Any], generate: bool = False) -> dict[str, Any]:
    if not isinstance(trip, dict) or trip.get("type") != "FeatureCollection":
        raise ImportError("Expected normalized GeoJSON FeatureCollection.")
    metadata = trip.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("schema_version") != 1:
        raise ImportError(
            f"Unsupported GeoJSON schema version: {metadata!r}. Use schema version 1."
        )
    if not isinstance(metadata.get("name"), str) or not metadata["name"].strip():
        raise ImportError("Trip needs a nonempty title.")
    features = trip.get("features")
    if not isinstance(features, list) or len(features) > MAX_FEATURES:
        raise ImportError("Expected at most 5,000 features. Export a smaller trip.")
    stops: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    unassigned: list[dict[str, Any]] = []
    total = 0
    for index, f in enumerate(features, 1):
        if not isinstance(f, dict) or f.get("type") != "Feature":
            raise ImportError(f"Feature {index}: expected Feature object.")
        props, geom = f.get("properties"), f.get("geometry")
        if not isinstance(props, dict) or not isinstance(geom, dict):
            raise ImportError(f"Feature {index}: missing properties or geometry.")
        kind = props.get("feature_type")
        if kind == "stop" and geom.get("type") == "Point":
            coordinate(geom.get("coordinates"))
            for key in ("id", "name", "country"):
                if not isinstance(props.get(key), str) or not props[key].strip():
                    raise ImportError(f"Feature {index}: missing {key}. Correct and recheck.")
            priority = props.get("label_priority")
            if priority is not None and (
                isinstance(priority, bool) or not isinstance(priority, int) or priority < 0
            ):
                raise ImportError(f"Feature {index}: label priority must be a nonnegative integer.")
            stops.append(f)
            total += 1
        elif kind in ("segment", "unassigned") and geom.get("type") == "LineString":
            coords = geom.get("coordinates")
            if not isinstance(coords, list) or not 2 <= len(coords) <= 10000:
                raise ImportError(f"Feature {index}: line needs 2–10,000 vertices.")
            for coord in coords:
                coordinate(coord)
            total += len(coords)
            (segments if kind == "segment" else unassigned).append(f)
        else:
            raise ImportError(f"Feature {index}: unsupported geometry or feature_type.")
    if total > MAX_VERTICES:
        raise ImportError("More than 100,000 vertices. Export a simpler trip.")
    if not stops:
        raise ImportError("Empty itinerary: export at least one Point stop.")
    sequence(stops)
    ids = [s["properties"]["id"] for s in stops]
    if len(ids) != len(set(ids)):
        raise ImportError("Duplicate explicit visit IDs. Give each visit a unique ID.")
    if generate and not segments:
        segments = connections(stops, [])
    sequence(segments)
    if len(segments) != len(stops) - 1:
        raise ImportError("Segments must connect each adjacent ordered visit.")
    for seg, left, right in zip(segments, stops, stops[1:], strict=False):
        p = seg["properties"]
        if (p.get("origin_id"), p.get("destination_id")) != (
            left["properties"]["id"],
            right["properties"]["id"],
        ):
            raise ImportError(
                "Broken segment reference or sequence: connections must follow visit order."
            )
        if p.get("transport_mode") not in MODES:
            raise ImportError(
                f"Unsupported transport mode {p.get('transport_mode')!r}. "
                f"Choose {', '.join(MODES)}."
            )
    trip["features"] = stops + segments + unassigned
    if len(trip["features"]) > MAX_FEATURES:
        raise ImportError("Normalized trip exceeds 5,000 features. Export a smaller trip.")
    return trip


def connections(
    stops: list[dict[str, Any]], previous: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    lookup = {
        (s["properties"]["origin_id"], s["properties"]["destination_id"]): s for s in previous
    }
    result = []
    for index, (left, right) in enumerate(zip(stops, stops[1:], strict=False), 1):
        pair = left["properties"]["id"], right["properties"]["id"]
        seg = copy.deepcopy(lookup.get(pair))
        if seg is None:
            seg = feature(
                "segment",
                {
                    "origin_id": pair[0],
                    "destination_id": pair[1],
                    "transport_mode": "car",
                    "mode_assumed": True,
                },
                [left["geometry"]["coordinates"], right["geometry"]["coordinates"]],
            )
        seg["properties"]["sequence"] = index
        result.append(seg)
    return result


def parts(trip: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [f for f in trip["features"] if f["properties"]["feature_type"] == kind]


def reorder(trip: dict[str, Any], indices: list[int]) -> None:
    stops = parts(trip, "stop")
    if sorted(indices) != list(range(1, len(stops) + 1)):
        raise ImportError("Enter every visit number exactly once, in the desired order.")
    stops = [stops[i - 1] for i in indices]
    for index, stop in enumerate(stops, 1):
        stop["properties"]["sequence"] = index
    old = parts(trip, "segment")
    new = connections(stops, old)
    kept = {(s["properties"]["origin_id"], s["properties"]["destination_id"]) for s in new}
    extra = parts(trip, "unassigned")
    for s in old:
        if (s["properties"]["origin_id"], s["properties"]["destination_id"]) not in kept and not s[
            "properties"
        ].get("mode_assumed"):
            orphan = copy.deepcopy(s)
            orphan["properties"]["feature_type"] = "unassigned"
            extra.append(orphan)
    trip["features"] = stops + new + extra
    trip["metadata"]["order_source"] = "user correction"
    validate(trip)


def warnings(trip: dict[str, Any]) -> list[str]:
    result = []
    dates: list[date | None] = []
    for stop in parts(trip, "stop"):
        raw = stop["properties"].get("arrival_date")
        try:
            dates.append(date.fromisoformat(raw) if raw else None)
        except (ValueError, TypeError):
            dates.append(None)
            result.append(
                f"{stop['properties']['name']}: invalid calendar "
                f"date {raw!r}; correct the export and recheck."
            )
    if not all(dates) or any(a > b for a, b in zip(dates, dates[1:], strict=False) if a and b):
        result.append(
            "Reliable day count unavailable: dates are missing, "
            "invalid or contradictory. Order and supplied dates "
            "are preserved. Set the trip duration in Poster design (Step 6)."
        )
    if any(s["properties"].get("mode_assumed") for s in parts(trip, "segment")):
        result.append(
            Notice(
                "Undeclared connections default to driving (car). "
                "Inspect and correct before routing."
            )
        )
    if parts(trip, "unassigned"):
        result.append(
            Notice(
                f"{len(parts(trip, 'unassigned'))} unassigned lines "
                f"available to assign in Own routes (Step 5)."
            )
        )
    return result


def route_keys(trip: dict[str, Any]) -> set[tuple[Any, ...]]:
    stops = {s["properties"]["id"]: s["geometry"]["coordinates"][:2] for s in parts(trip, "stop")}
    return {
        tuple(
            stops[s["properties"]["origin_id"]]
            + stops[s["properties"]["destination_id"]]
            + [s["properties"]["transport_mode"]]
        )
        for s in parts(trip, "segment")
    }


def load(path: Path) -> tuple[bytes, list[tuple[dict[str, Any], list[str]]]]:
    try:
        content = read_bytes(path)
        if path.suffix.lower() == ".kml":
            return content, kml_candidates(content, path.name)
        return content, [(validate(decode_json(content)), [])]
    except (ET.ParseError, UnicodeError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise ImportError(
            f"{path.name}: {exc}. Correct the export, choose another file, or recheck."
        ) from exc


def write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise ImportError("Normalized result exceeds 8 MiB. Export a smaller trip.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise ImportError(
            f"Cannot save {path.name}: {exc}. Check disk space and permissions; retry."
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def source_key(content: bytes, candidate: int) -> str:
    return hashlib.sha256(content + str(candidate).encode()).hexdigest()
