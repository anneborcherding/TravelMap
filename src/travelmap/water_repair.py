"""Bounded member storage and explicitly reported repair of malformed water polygons."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from shapely import from_wkb, get_num_coordinates, make_valid
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon
from shapely.ops import linemerge

from travelmap import mapstore


class Members:
    """Keep selected relation dependencies on disk until area assembly finishes."""

    def __init__(self, staging: Path) -> None:
        self.path = staging / "water-members.sqlite"
        self.store = mapstore.Store(self.path, create=True)

    def relation(self, relation: Any) -> None:
        refs = [(member.ref, member.role) for member in relation.members if member.type == "w"]
        self.store.db.execute(
            "INSERT OR REPLACE INTO metadata VALUES(?,?)",
            (
                f"relation:{relation.id}",
                json.dumps(
                    {
                        "members": refs,
                        "version": relation.version,
                        "name": relation.tags.get("name"),
                        "water_type": relation.tags.get("water")
                        or (
                            "reservoir" if relation.tags.get("landuse") == "reservoir" else "water"
                        ),
                    }
                ),
            ),
        )
        self.store.db.executemany(
            "INSERT OR IGNORE INTO metadata VALUES(?,?)",
            [(f"way:{identity}", "") for identity, _ in refs],
        )
        self.store.flush()

    def way(self, way: Any, factory: Any, *, selected: bool = False) -> None:
        if (
            selected
            or self.store.db.execute(
                "SELECT 1 FROM metadata WHERE key=?", (f"way:{way.id}",)
            ).fetchone()
        ):
            geom = from_wkb(factory.create_linestring(way))
            self.store.add(
                "water_lines",
                f"osm:way:{way.id}",
                geom,
                {"waterway": "relation_member", "version": way.version},
            )

    def rings(self, refs: list[tuple[int, str]]) -> list[list[tuple[float, float]]]:
        lines = []
        total = 0
        for identity, _ in refs:
            row = self.store.db.execute(
                "SELECT geometry,vertices FROM features WHERE layer='water_lines' AND identity=?",
                (f"osm:way:{identity}",),
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"Missing water member osm:way:{identity}; use a complete extract."
                )
            total += row[1]
            if total > mapstore.MAX_FEATURE_VERTICES:
                raise ValueError("Water relation exceeds one million member vertices.")
            lines.append(from_wkb(row[0]))
        if not lines:
            return []
        merged = linemerge(MultiLineString(lines))
        parts = [merged] if isinstance(merged, LineString) else list(merged.geoms)
        if any(not line.is_closed for line in parts):
            raise ValueError("Water member rings are incomplete; use a complete extract.")
        return [[(float(c[0]), float(c[1])) for c in line.coords] for line in parts]

    def original(self, area: Any) -> Any:
        if area.from_way():
            rings = self.rings([(area.orig_id(), "outer")])
            if len(rings) != 1:
                raise ValueError("Water way has no complete outer ring.")
            return Polygon(rings[0])
        row = self.store.db.execute(
            "SELECT value FROM metadata WHERE key=?", (f"relation:{area.orig_id()}",)
        ).fetchone()
        if row is None:
            raise ValueError("Water relation dependency record is missing.")
        refs = json.loads(row[0])["members"]
        if any(role not in ("outer", "inner", "") for _, role in refs):
            raise ValueError("Unsupported water member role; correct the relation.")
        total = 0
        for identity, _ in refs:
            member = self.store.db.execute(
                "SELECT vertices FROM features WHERE layer='water_lines' AND identity=?",
                (f"osm:way:{identity}",),
            ).fetchone()
            if member is None:
                raise ValueError(
                    f"Missing water member osm:way:{identity}; use a complete extract."
                )
            total += member[0]
            if total > mapstore.MAX_FEATURE_VERTICES:
                raise ValueError("Water relation exceeds one million member vertices.")
        outers = self.rings([(identity, role) for identity, role in refs if role != "inner"])
        inners = self.rings([(identity, role) for identity, role in refs if role == "inner"])
        total = sum(len(ring) for ring in outers + inners)
        if total > mapstore.MAX_FEATURE_VERTICES or not outers:
            raise ValueError("Water relation has no outer ring or exceeds vertex limits.")
        polygons = [Polygon(ring) for ring in outers]
        for polygon in polygons:
            guard(polygon)
        ownership = [make_valid(polygon) for polygon in polygons]
        if any(region.geom_type not in ("Polygon", "MultiPolygon") for region in ownership):
            raise ValueError("Invalid outer cannot establish water-hole ownership.")
        holes: list[list[Any]] = [[] for _ in polygons]
        for ring in inners:
            inner = Polygon(ring)
            guard(inner)
            inner_region = make_valid(inner)
            if inner_region.geom_type not in ("Polygon", "MultiPolygon"):
                raise ValueError("Invalid inner cannot establish water-hole ownership.")
            owners = (
                [0]
                if len(ownership) == 1
                else [i for i, region in enumerate(ownership) if region.covers(inner_region)]
            )
            if len(owners) != 1:
                raise ValueError("Ambiguous water-hole ownership; correct the relation.")
            holes[owners[0]].append(ring)
        result = [Polygon(ring, holes[i]) for i, ring in enumerate(outers)]
        return result[0] if len(result) == 1 else MultiPolygon(result)

    def pending(self, identity: str) -> tuple[Any, dict[str, Any]]:
        number = int(identity.split(":")[-1])
        row = self.store.db.execute(
            "SELECT value FROM metadata WHERE key=?", (f"relation:{number}",)
        ).fetchone()
        if row is None:
            raise ValueError("Water relation dependency record is missing.")
        record = json.loads(row[0])
        geometry = self.original(SimpleNamespace(from_way=lambda: False, orig_id=lambda: number))
        return geometry, {
            "water_type": record["water_type"],
            "version": record["version"],
            "name": record["name"],
            "geometry_assembly": "complete-member fallback",
        }

    def close(self) -> None:
        self.store.db.close()
        self.path.unlink(missing_ok=True)


def guard(geom: Any) -> None:
    """Check bounded original polygon input before native repair/ownership operations."""
    mapstore.geometry_info(geom, "water_areas", catalog_invalid=True)
    if geom.bounds[2] - geom.bounds[0] > 180:
        raise ValueError("Malformed wrapped water polygon needs corrected source topology.")


def repair(geom: Any) -> tuple[Any, dict[str, Any] | None]:
    """Leave valid geometry untouched; repair only named invalid polygon topology."""
    try:
        mapstore.geometry_info(geom, "water_areas")
        return geom, None
    except ValueError:
        # Validate size/XY before invoking a topology repair. Invalid catalog mode deliberately
        # bypasses topology only, retaining the per-feature/range checks.
        guard(geom)
    result = make_valid(geom)
    if result.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(
            "Water repair produced non-polygon remnants; correct the source to preserve all detail."
        )
    mapstore.geometry_info(result, "water_areas")
    noncontained = 0
    for polygon in [geom] if geom.geom_type == "Polygon" else geom.geoms:
        outer = Polygon(polygon.exterior)
        guard(outer)
        region = make_valid(outer)
        for ring in polygon.interiors:
            hole = Polygon(ring)
            guard(hole)
            if not region.covers(make_valid(hole)):
                noncontained += 1
    return result, {
        "method": "shapely.make_valid",
        "original_vertices": int(get_num_coordinates(geom)),
        "repaired_vertices": int(get_num_coordinates(result)),
        "result_type": result.geom_type,
        "noncontained_source_holes": noncontained,
    }
