"""Isolated bounded GIS readers. Invoked only by the offline preparation controller."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from travelmap import mapdata as data


class Collector:
    """Stream full-source geometries and entity versions into owned SQLite storage."""

    def __init__(self, staging: Path, bounds: list[float]) -> None:
        from travelmap.mapstore import Store

        self.staging = staging
        self.store = Store(staging / "features.sqlite", create=True)
        self.layers: dict[str, dict[str, Any]] = {}
        self.objects = 0
        self.last = 0.0
        self.label = "Local map data"
        self.phase = "Opening"
        self.repairs: list[dict[str, Any]] = []
        self.repair_originals: Any = None
        self.nested_water_count = 0
        self.first_nested_water_id: int | None = None

    def progress(self, activity: str, force: bool = False) -> None:
        if force or time.monotonic() - self.last >= 1:
            snapshot = {
                "activity": activity,
                "sequence": self.objects + self.store.count,
                "source": self.label,
                "phase": self.phase,
            }
            if not activity.startswith("Validating"):
                snapshot.update({"scanned": self.objects, "retained": self.store.count})
            data.atomic_json(
                self.staging / "progress.json",
                snapshot,
            )
            self.last = time.monotonic()

    def tick(self, label: str) -> None:
        self.objects += 1
        self.phase = (
            "Read/assemble"
            if label.startswith("Reading")
            else "Water relations"
            if label.startswith("Selecting water")
            else "Winner index"
            if label.startswith("Resolving")
            else "Select features"
        )
        self.progress(
            f"{label}: {self.objects:,} callbacks scanned, {self.store.count:,} features retained."
        )

    def add(self, layer: str, identity: str, geometry: Any, properties: dict[str, Any]) -> None:
        self.layers.setdefault(layer, {})
        try:
            if layer == "water_areas":
                from travelmap import mapstore, water_repair

                original = geometry
                geometry, repaired = water_repair.repair(geometry)
                if repaired:
                    if len(self.repairs) >= 512:
                        raise ValueError("More than 512 water repairs; select a corrected source.")
                    if self.repair_originals is None:
                        self.repair_originals = mapstore.Store(
                            self.staging / "repair-originals.sqlite", create=True
                        )
                    self.repair_originals.add(
                        layer,
                        identity,
                        original,
                        {
                            **properties,
                            "geometry_state": "invalid",
                            "geometry_role": "repair_original",
                        },
                    )
                    properties = {**properties, "geometry_repair": repaired}
                    self.repairs.append({"id": identity, **repaired})
                    self.progress(
                        f"Repaired water polygon {identity} in {self.label}: "
                        f"{repaired['original_vertices']:,} original -> "
                        f"{repaired['repaired_vertices']:,} vertices ({repaired['result_type']}).",
                        force=True,
                    )
            self.store.add(layer, identity, geometry, properties)
        except ValueError as exc:
            raise data.MapDataError(f"{self.label}: {identity}: {exc}") from exc


def _valid_readiness_handoff(request: dict[str, Any]) -> bool:
    """Trust only a parent token that matches current inputs and a successful receipt."""
    from travelmap import validation_reuse

    key = request.get("readiness_key")
    token = request.get("readiness_token")
    if not isinstance(key, str) or not isinstance(token, dict):
        return False
    root = Path(request["root"])
    try:
        actual = validation_reuse.readiness_key(
            root,
            request["trip"],
            request["resolved"],
            request["settings"],
            request["selection"],
        )
    except (KeyError, TypeError, ValueError):
        return False
    return (
        actual == key
        and validation_reuse.readiness_matches(root, key)
        and validation_reuse.readiness_token(root, key) == token
    )


def vector(
    path: Path,
    kind: str,
    layer: str | None,
    settings: dict[str, Any],
    collector: Collector,
    source_hash: str,
) -> list[list[float]]:
    import fiona  # type: ignore[import-untyped]
    from fiona.transform import transform_geom  # type: ignore[import-untyped]
    from shapely.geometry import shape

    names = ("ADMIN", "NAME", "name") if kind == "countries" else ("NAME_1", "NAME", "name")
    classes = {
        "roads": ("highway", settings["highway_classes"]),
        "water_lines": ("waterway", settings["water_line_classes"]),
        "water_areas": ("water_type", settings["water_area_classes"]),
    }
    kwargs: dict[str, Any] = {"enabled_drivers": ["ESRI Shapefile", "GPKG", "GeoJSON"]}
    if layer is not None:
        kwargs["layer"] = layer
    extent: list[float] | None = None
    try:
        with (
            fiona.Env(PROJ_NETWORK="OFF", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"),
            fiona.open(path, **kwargs) as source,
        ):
            if not source.crs:
                raise data.MapDataError(
                    f"{path.name}/{layer or kind}: missing CRS. Re-export "
                    f"with explicit CRS metadata; do not guess it."
                )
            schema = source.schema["properties"]
            name_column = next((name for name in names if name in schema), None)
            if kind in ("countries", "admin1") and name_column is None:
                raise data.MapDataError(
                    f"{path.name}: missing boundary name column ({', '.join(names)}). "
                    f"Select compatible vectors."
                )
            if kind in classes and classes[kind][0] not in schema:
                raise data.MapDataError(
                    f"{path.name}: missing {classes[kind][0]} field "
                    f"in {layer or kind}. Select a compatible named "
                    f"layer."
                )
            for index, item in enumerate(source):
                collector.tick(f"Reading {path.name}")
                props = dict(item["properties"])
                if kind in classes and props.get(classes[kind][0]) not in classes[kind][1]:
                    continue
                geom = item["geometry"]
                if geom is None:
                    raise data.MapDataError(f"{path.name}: feature {index} has no geometry.")
                transformed = shape(
                    transform_geom(source.crs, "EPSG:4326", geom, antimeridian_cutting=True)
                )
                if kind not in ("countries", "admin1") and not transformed.is_empty:
                    bounds = list(transformed.bounds)
                    extent = (
                        bounds
                        if extent is None
                        else [
                            min(extent[0], bounds[0]),
                            min(extent[1], bounds[1]),
                            max(extent[2], bounds[2]),
                            max(extent[3], bounds[3]),
                        ]
                    )
                if kind in ("countries", "admin1"):
                    name = props[name_column]
                    code_columns = (
                        ("ISO_A3", "ADM0_A3", "iso_a3", "code")
                        if kind == "countries"
                        else ("GID_1", "ISO_3166_2", "iso_3166_2", "adm1_code", "code")
                    )
                    code = next(
                        (props[c] for c in code_columns if props.get(c) and props[c] != "-99"),
                        None,
                    )
                    missing_name = not isinstance(name, str) or not name.strip()
                    if missing_name:
                        if kind != "admin1" or not isinstance(code, str) or not code.strip():
                            raise data.MapDataError(
                                f"{path.name}: feature {index} has an empty boundary name."
                            )
                        name = code
                        collector.progress(
                            f"Boundary catalog: unnamed administrative boundary {code}; "
                            "using its source code as the display label, geometry retained.",
                            force=True,
                        )
                    canonical = {
                        "name": name,
                        "code": code,
                    }
                    if missing_name:
                        canonical["name_origin"] = "source_code"
                    if kind == "admin1":
                        canonical["country_code"] = next(
                            (
                                props[c]
                                for c in ("adm0_a3", "ADM0_A3", "GID_0", "ISO_A3")
                                if props.get(c) and props[c] != "-99"
                            ),
                            None,
                        )
                        canonical["country_name"] = next(
                            (props[c] for c in ("admin", "ADMIN", "COUNTRY") if props.get(c)), None
                        )
                    from travelmap import geography

                    polar = transformed.bounds[1] <= -89.99 or transformed.bounds[3] >= 89.99
                    try:
                        valid = (
                            transformed.is_valid
                            if polar
                            else all(g.is_valid for g in geography.components(transformed))
                        )
                    except ValueError:
                        valid = False
                    if not valid:
                        canonical["geometry_state"] = "invalid"
                        collector.progress(
                            f"Boundary catalog: {name} has invalid geometry; "
                            "it cannot be selected without correction.",
                            force=True,
                        )
                else:
                    field = classes[kind][0]
                    canonical = {field: props[field], "name": props.get("name")}
                collector.add(
                    kind, f"vector:{source_hash}:{kind}:{item.id}", transformed, canonical
                )
    except data.MapDataError:
        raise
    except Exception as exc:
        raise data.MapDataError(
            f"{path.name}/{layer or kind}: unreadable vector/CRS "
            f"transformation: {exc}. Select compatible local "
            f"data."
        ) from exc
    return [extent] if extent is not None else []


def water_type(tags: Any) -> str | None:
    return tags.get("water") or (
        "reservoir"
        if tags.get("landuse") == "reservoir"
        else "water"
        if tags.get("natural") == "water"
        else None
    )


def osm(
    path: Path, settings: dict[str, Any], collector: Collector
) -> tuple[list[list[float]], dict[str, str]]:
    import osmium
    from shapely import from_wkb

    from travelmap import water_repair
    from travelmap.mapstore import MAX_FEATURE_VERTICES, entity_digest

    factory = osmium.geom.WKBFactory()
    members = water_repair.Members(collector.staging)
    bounds = [180.0, 90.0, -180.0, -90.0]
    node_count = 0
    coverage: list[list[float]] = []
    try:
        with osmium.io.Reader(str(path), osmium.osm.osm_entity_bits.NOTHING) as reader:
            header = reader.header()
            if header.has_multiple_object_versions:
                raise data.MapDataError(
                    f"{path.name}: history PBFs are unsupported; select a current snapshot."
                )
            region = header.box()
            if region.valid():
                coverage = [
                    [
                        region.bottom_left.lon,
                        region.bottom_left.lat,
                        region.top_right.lon,
                        region.top_right.lat,
                    ]
                ]
            metadata = {
                "generator": header.get("generator"),
                "replication_timestamp": header.get("osmosis_replication_timestamp"),
            }
    except Exception as exc:
        raise data.MapDataError(
            f"{path.name}: unreadable PBF header: {exc}. Select a complete regional snapshot."
        ) from exc

    class WaterCandidates:
        def relation(self, relation: Any) -> bool:
            collector.tick(f"Selecting water relations in {path.name}")
            eligible = (
                relation.visible
                and relation.tags.get("type") in ("multipolygon", "boundary")
                and water_type(relation.tags) in settings["water_area_classes"]
            )
            if not eligible:
                return True
            if len(relation.members) > MAX_FEATURE_VERTICES:
                raise ValueError(f"osm:relation:{relation.id}: too many water members.")
            if any(member.type == "r" for member in relation.members):
                # Keep the raw entity in the main pass so a newer unsupported version
                # still supersedes older geometry from overlapping extracts.
                collector.nested_water_count += 1
                if collector.first_nested_water_id is None:
                    collector.first_nested_water_id = relation.id
                return True
            members.relation(relation)
            collector.store.db.execute(
                "INSERT OR IGNORE INTO pending VALUES(?)", (f"osm:relation:{relation.id}",)
            )
            collector.store.flush()
            return False

    index = collector.staging / "node-locations.idx"
    try:
        area_tags = [("natural", "water"), ("landuse", "reservoir")]
        area_tags.extend(("water", kind) for kind in settings["water_area_classes"])
        area_filter = osmium.filter.TagFilter(*area_tags)
        area_filter.enable_for(osmium.osm.osm_entity_bits.AREA)
        processor = (
            osmium.FileProcessor(str(path))
            .with_locations(f"sparse_file_array,{index}")
            .with_areas(WaterCandidates())
            .with_filter(area_filter)
        )
        for obj in processor:
            collector.tick(f"Reading/assembling {path.name}")
            if isinstance(obj, osmium.osm.Node):
                if not obj.visible:
                    continue
                if not obj.location.valid():
                    raise data.MapDataError(f"{path.name}: node {obj.id} has invalid coordinates.")
                node_count += 1
                x, y = obj.location.lon, obj.location.lat
                bounds[0], bounds[1] = min(bounds[0], x), min(bounds[1], y)
                bounds[2], bounds[3] = max(bounds[2], x), max(bounds[3], y)
                continue
            if isinstance(obj, osmium.osm.Area):
                kind = water_type(obj.tags)
                if kind not in settings["water_area_classes"]:
                    continue
                identity = f"osm:{'way' if obj.from_way() else 'relation'}:{obj.orig_id()}"
                try:
                    geom = from_wkb(factory.create_multipolygon(obj))
                except RuntimeError:
                    geom = members.original(obj)
                properties: dict[str, Any] = {
                    "water_type": kind,
                    "version": obj.version,
                    "name": obj.tags.get("name"),
                }
                collector.add(
                    "water_areas",
                    identity,
                    geom,
                    properties,
                )
                collector.store.db.execute("DELETE FROM pending WHERE identity=?", (identity,))
                continue
            if not isinstance(obj, (osmium.osm.Way, osmium.osm.Relation)):
                continue
            identity = f"osm:{'way' if obj.is_way() else 'relation'}:{obj.id}"
            references = obj.nodes if isinstance(obj, osmium.osm.Way) else obj.members
            if len(references) > MAX_FEATURE_VERTICES:
                raise data.MapDataError(f"{identity}: raw entity exceeds one million references.")
            highway, waterway = obj.tags.get("highway"), obj.tags.get("waterway")
            eligibility = (
                int(highway in settings["highway_classes"])
                | (int(waterway in settings["water_line_classes"]) << 1)
                | (int(water_type(obj.tags) in settings["water_area_classes"]) << 2)
            )
            collector.store.entity(
                identity, obj.version, obj.visible, entity_digest(obj), eligibility
            )
            if isinstance(obj, osmium.osm.Way) and obj.visible:
                members.way(obj, factory, selected=bool(eligibility & 4) and obj.is_closed())
            if not isinstance(obj, osmium.osm.Way) or not obj.visible or not eligibility & 3:
                continue
            if len(obj.nodes) > MAX_FEATURE_VERTICES:
                raise data.MapDataError(f"{identity}: way exceeds one million vertices.")
            try:
                geom = from_wkb(factory.create_linestring(obj))
            except Exception as exc:
                raise data.MapDataError(
                    f"{path.name}: {identity} has missing nodes/invalid geometry; "
                    "select a complete extract."
                ) from exc
            if eligibility & 1:
                collector.add(
                    "roads",
                    identity,
                    geom,
                    {"highway": highway, "version": obj.version, "name": obj.tags.get("name")},
                )
            if eligibility & 2:
                collector.add(
                    "water_lines",
                    identity,
                    geom,
                    {"waterway": waterway, "version": obj.version, "name": obj.tags.get("name")},
                )
        for (identity,) in collector.store.db.execute("SELECT identity FROM pending"):
            try:
                geom, properties = members.pending(identity)
                collector.add("water_areas", identity, geom, properties)
            except ValueError as exc:
                raise data.MapDataError(
                    f"{path.name}: {identity}: water assembly failed: {exc}"
                ) from exc
            collector.store.db.execute("DELETE FROM pending WHERE identity=?", (identity,))
            collector.progress(f"Recovered {identity} from complete water members.", force=True)
    except data.MapDataError:
        raise
    except Exception as exc:
        raise data.MapDataError(
            f"{path.name}: PBF processing failed: {exc}. Check the affected entity/input and retry."
        ) from exc
    finally:
        members.close()
    for kind in ("roads", "water_lines", "water_areas"):
        collector.layers.setdefault(kind, {})
    return coverage or ([bounds] if node_count else []), metadata


def execute(staging: Path) -> None:
    request = data.read_json(staging / "request.json", data.MAX_OUTPUT_BYTES)
    if request.get("action") == "view":
        from travelmap import map_view, poster_settings

        def view_progress(message: str) -> None:
            data.atomic_json(staging / "progress.json", {"activity": message})

        view_progress("Selecting displayed country components")
        view = map_view.select(
            request["countries"],
            request["trip"],
            request["resolved"],
            poster_settings.validate(request["settings"]),
            view_progress,
        )
        data.atomic_json(
            staging / "manifest.json",
            {
                "summary": view.summary(),
                "counts": view.metadata["counts"],
                "include_offshore_components": view.metadata["include_offshore_components"],
                "journey_expanded_frame": view.metadata["journey_expanded_frame"],
                "coverage_errors": (
                    []
                    if request.get("readiness_key") is not None
                    and _valid_readiness_handoff(request)
                    else view.coverage_errors(
                        request["selection"], request["trip"], request["resolved"]
                    )
                ),
            },
        )
        return
    if request.get("action") == "export":
        from travelmap import render
        from travelmap.reporting import Notice

        def report(message: str) -> None:
            data.atomic_json(staging / "progress.json", {"activity": message})

        with (staging / "poster.svg").open("wb") as stream:
            warnings = render.render_svg_to(
                stream,
                Path(request["root"]),
                request["trip"],
                request["resolved"],
                request["settings"],
                request["selection"],
                request.get("route_color"),
                report,
                request.get("readiness_key"),
                request.get("readiness_token"),
            )
            if request.get("readiness_token") is not None and not _valid_readiness_handoff(request):
                raise data.MapDataError("Readiness changed during rendering; retry preflight.")
            stream.flush()
            os.fsync(stream.fileno())
        data.atomic_json(
            staging / "manifest.json",
            {
                "warnings": warnings,
                "notice_indices": [
                    i for i, message in enumerate(warnings) if isinstance(message, Notice)
                ],
                "readiness_key": request.get("readiness_key"),
                "readiness_token": request.get("readiness_token"),
            },
        )
        return
    if request.get("action") == "validate":
        from travelmap import mapstore

        def progress(message: str) -> None:
            data.atomic_json(staging / "progress.json", {"activity": message})

        counts = mapstore.validate(Path(request["database"]), progress)
        data.atomic_json(staging / "manifest.json", {"layers": counts})
        return
    if request.get("action") == "combine":
        combine(staging, request)
        return
    source = request["source"]
    path = Path(source["path"])
    kind = source["kind"]
    collector = Collector(staging, request["extent"])
    collector.label = path.name
    collector.progress(f"Opening {path.name}", force=True)
    source_hash = request["key"]
    metadata: dict[str, str] = {}
    if kind == "osm":
        coverage, metadata = osm(path, request["settings"], collector)
        attribution = {
            "source": "OpenStreetMap / Geofabrik",
            "text": "© OpenStreetMap contributors",
            "licence": "ODbL 1.0",
            "url": "https://www.openstreetmap.org/copyright",
        }
    else:
        selected = path
        if path.suffix.lower() == ".zip":
            extraction = staging / "extracted"
            extraction.mkdir()
            selected = data.extract_boundary(path, extraction, kind)
            for version_file in sorted(extraction.rglob("*VERSION*")):
                if version_file.is_file() and version_file.stat().st_size <= 65536:
                    metadata[version_file.name] = version_file.read_text(
                        encoding="utf-8", errors="replace"
                    )
        coverage = vector(
            selected, kind, source.get("layer"), request["settings"], collector, source_hash
        )
        attribution = {
            "source": "Natural Earth" if path.suffix.lower() == ".zip" else path.name,
            "text": source.get(
                "attribution",
                "Made with Natural Earth"
                if path.suffix.lower() == ".zip"
                else f"Local vector: {path.name}; verify source licence before publishing",
            ),
            "licence": "Public domain"
            if path.suffix.lower() == ".zip"
            else source.get("licence", "Owner-supplied; verify licence"),
            "url": "https://www.naturalearthdata.com/about/terms-of-use/"
            if path.suffix.lower() == ".zip"
            else "",
        }
        collector.layers.setdefault(kind, {})
    from travelmap import mapstore

    collector.store.db.commit()
    collector.store.db.close()
    layers = mapstore.validate(
        staging / "features.sqlite", lambda message: collector.progress(message)
    )
    for name in collector.layers:
        layers.setdefault(name, {"count": 0})
    database_hash = data.digest(staging / "features.sqlite", mapstore.MAX_DB_BYTES)
    repair_summary = None
    if collector.repairs:
        collector.repair_originals.db.commit()
        collector.repair_originals.db.close()
        repair_database = staging / "repair-originals.sqlite"
        mapstore.validate(repair_database)
        repair_summary = {
            "count": len(collector.repairs),
            "objects": collector.repairs,
            "database_sha256": data.digest(repair_database, mapstore.MAX_DB_BYTES),
        }
    data.atomic_json(
        staging / "manifest.json",
        {
            "schema_version": 2,
            "key": request["key"],
            "database_sha256": database_hash,
            "layers": layers,
            "coverage": coverage,
            "attribution": attribution,
            "provenance": request["provenance"],
            "source_version": metadata,
            "geometry_repairs": repair_summary,
            "omitted_nested_water_relations": {
                "count": collector.nested_water_count,
                "first_id": collector.first_nested_water_id,
            },
        },
    )
    for child in ("node-locations.idx", "request.json", "progress.json"):
        (staging / child).unlink(missing_ok=True)
    import shutil

    shutil.rmtree(staging / "extracted", ignore_errors=True)


def combine(staging: Path, request: dict[str, Any]) -> None:
    """Reduce all entity versions on disk before class/spatial eligibility."""
    from shapely.geometry import shape

    from travelmap import geography, mapstore

    collector = Collector(staging, [-180, -90, 180, 90])
    collector.label = "Country background"
    countries = request["countries"]
    settings = request.get("settings") or {
        field: sorted(
            {
                value
                for record in request["records"]
                for value in record["provenance"].get("classes", {}).get(field, [])
            }
        )
        for field in ("highway_classes", "water_line_classes", "water_area_classes")
    }
    shapes = [shape(feature["geometry"]) for feature in countries]
    region = geography.Region(shapes)
    country_ids = {feature["id"] for feature in countries}
    country_codes = {f["properties"].get("code") for f in countries if f["properties"].get("code")}
    country_names = {f["properties"]["name"] for f in countries}
    with mapstore.Store(staging / "winners.sqlite", create=True) as winners:
        for record in sorted(request["records"], key=lambda r: r["key"]):
            db = mapstore.connect(Path(record["database"]))
            try:
                for identity, version, visible, digest, mask in db.execute(
                    "SELECT * FROM entities ORDER BY identity"
                ):
                    collector.tick("Resolving overlapping entity versions")
                    previous = winners.db.execute(
                        "SELECT value FROM metadata WHERE key=?", (identity,)
                    ).fetchone()
                    rank = min(record["provenance"]["hashes"].values())
                    value = [version, record["key"], visible, digest, mask, rank]
                    if previous:
                        old = json.loads(previous[0])
                        if old[0] == version and old[3] != digest:
                            collector.progress(
                                f"Equal-version overlap conflict: {identity}; "
                                "deterministic source winner."
                            )
                        if old[0] > version or (old[0] == version and old[5] <= rank):
                            continue
                    winners.db.execute(
                        "INSERT OR REPLACE INTO metadata VALUES(?,?)", (identity, json.dumps(value))
                    )
                    winners.flush()
            finally:
                db.close()
        winners.db.commit()
        for record in request["records"]:
            db = mapstore.connect(Path(record["database"]))
            try:
                for feature in mapstore.read_features(db):
                    collector.tick("Selecting whole-country background features")
                    kind, identity = feature["layer"], feature["id"]
                    if kind in ("roads", "water_lines", "water_areas") and kind not in settings.get(
                        "enabled_layers", ("roads", "water_lines", "water_areas")
                    ):
                        continue
                    field = {
                        "roads": "highway_classes",
                        "water_lines": "water_line_classes",
                        "water_areas": "water_area_classes",
                    }.get(kind)
                    if field:
                        attribute = {
                            "roads": "highway",
                            "water_lines": "waterway",
                            "water_areas": "water_type",
                        }[kind]
                        if feature["properties"].get(attribute) not in settings[field]:
                            continue
                    if identity.startswith("osm:"):
                        row = winners.db.execute(
                            "SELECT value FROM metadata WHERE key=?", (identity,)
                        ).fetchone()
                        if row is None:
                            raise data.MapDataError(f"{identity}: missing source entity ledger.")
                        winner = json.loads(row[0])
                        bit = {"roads": 1, "water_lines": 2, "water_areas": 4}[kind]
                        if (
                            winner[1] != record["key"]
                            or not winner[2]
                            or not winner[4] & bit
                            or winner[0] != feature["properties"]["version"]
                        ):
                            continue
                    geom = shape(feature["geometry"])
                    if kind == "countries":
                        include = identity in country_ids
                    elif (
                        kind == "admin1"
                        and feature["properties"].get("country_code")
                        and country_codes
                    ):
                        include = feature["properties"]["country_code"] in country_codes
                    elif kind == "admin1" and feature["properties"].get("country_name"):
                        include = feature["properties"]["country_name"] in country_names
                    else:
                        include = region.intersects(geom)
                    if include:
                        if feature["properties"].get("geometry_state") == "invalid":
                            raise data.MapDataError(
                                f"{feature['properties'].get('name', identity)}: "
                                "invalid selected boundary geometry; select compatible boundaries."
                            )
                        collector.add(kind, identity, geom, feature["properties"])
            finally:
                db.close()
    collector.store.db.commit()
    collector.store.db.close()
    layers = mapstore.validate(
        staging / "features.sqlite", lambda message: collector.progress(message)
    )
    for record in request["records"]:
        for kind in record["layers"]:
            layers.setdefault(kind, {"count": 0})
    if "roads" in settings.get(
        "enabled_layers", ("roads", "water_lines", "water_areas")
    ) and not layers.get("roads", {}).get("count"):
        raise data.MapDataError(
            "No supported background roads intersect selected countries. Selec"
            "t covering extracts or road classes."
        )
    (staging / "winners.sqlite").unlink()
    data.atomic_json(
        staging / "manifest.json",
        {
            "schema_version": 2,
            "key": request["key"],
            "database_sha256": data.digest(staging / "features.sqlite", mapstore.MAX_DB_BYTES),
            "layers": layers,
        },
    )
    for child in ("request.json", "progress.json"):
        (staging / child).unlink(missing_ok=True)


def main() -> int:
    staging = Path(sys.argv[1])
    os.environ["PROJ_NETWORK"] = "OFF"
    try:
        execute(staging)
        return 0
    except Exception as exc:
        data.atomic_json(staging / "error.json", {"error": str(exc)[:4000]})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
