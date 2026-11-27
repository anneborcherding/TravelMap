"""Bounded SQLite/WKB map caches with exact schemas and validated streaming readers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from shapely import from_wkb, get_coordinates, to_wkb
from shapely.geometry import mapping

from travelmap import geography

MIB = 1024 * 1024
MAX_DB_BYTES = 8 * 1024 * MIB
MAX_BLOB = 64 * MIB
MAX_PROPERTIES = 64 * 1024
MAX_VERTICES = 100_000_000
MAX_FEATURES = 5_000_000
MAX_FEATURE_VERTICES = 1_000_000
LAYERS = ("countries", "admin1", "roads", "water_lines", "water_areas")
SCHEMA = (
    (
        "CREATE TABLE features (layer TEXT NOT NULL, identity TEXT NOT NUL"
        "L, version INTEGER NOT NULL, properties TEXT NOT NULL, geometry B"
        "LOB NOT NULL, vertices INTEGER NOT NULL, PRIMARY KEY(layer,identi"
        "ty)) WITHOUT ROWID"
    ),
    (
        "CREATE TABLE envelopes (layer TEXT NOT NULL, identity TEXT NOT NU"
        "LL, part INTEGER NOT NULL, west REAL NOT NULL, south REAL NOT NUL"
        "L, east REAL NOT NULL, north REAL NOT NULL, PRIMARY KEY(layer,ide"
        "ntity,part)) WITHOUT ROWID"
    ),
    (
        "CREATE TABLE entities (identity TEXT PRIMARY KEY, version INTEGER"
        " NOT NULL, visible INTEGER NOT NULL, digest TEXT NOT NULL, eligib"
        "ility INTEGER NOT NULL) WITHOUT ROWID"
    ),
    "CREATE TABLE pending (identity TEXT PRIMARY KEY) WITHOUT ROWID",
    "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID",
)


def connect(path: Path, *, create: bool = False) -> sqlite3.Connection:
    """Open only local caches, with bounded SQLite allocation and safe schema mode."""
    if path.is_symlink() or (not create and not path.is_file()):
        raise ValueError(f"{path.name}: expected a regular map cache.")
    if path.exists() and path.stat().st_size > MAX_DB_BYTES:
        raise ValueError(f"{path.name}: map cache exceeds 8 GiB.")
    db = sqlite3.connect(path if create else path.resolve().as_uri() + "?mode=ro", uri=not create)
    db.execute("PRAGMA trusted_schema=OFF")
    db.execute("PRAGMA temp_store=MEMORY")
    db.execute("PRAGMA hard_heap_limit=268435456")
    db.execute("PRAGMA cache_size=-32768")
    db.execute("PRAGMA mmap_size=0")
    if (
        db.execute("PRAGMA temp_store").fetchone()[0] != 2
        or db.execute("PRAGMA hard_heap_limit").fetchone()[0] != 256 * MIB
        or db.execute("PRAGMA trusted_schema").fetchone()[0] != 0
    ):
        db.close()
        raise ValueError("SQLite lacks the required memory/schema safeguards.")
    db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_BLOB + MAX_PROPERTIES + 4096)
    db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 16 * 1024)
    if hasattr(db, "setconfig") and hasattr(sqlite3, "SQLITE_DBCONFIG_DEFENSIVE"):
        db.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
    if create:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA max_page_count=2097152")
        for sql in SCHEMA:
            db.execute(sql)
        db.execute("PRAGMA application_id=1414352976")
        db.execute("PRAGMA user_version=2")
    else:
        if (
            db.execute("PRAGMA application_id").fetchone()[0] != 1414352976
            or db.execute("PRAGMA user_version").fetchone()[0] != 2
        ):
            db.close()
            raise ValueError("Unsupported map cache schema/version.")
        actual = {r[0] for r in db.execute("SELECT sql FROM sqlite_schema WHERE sql IS NOT NULL")}
        if actual != set(SCHEMA):
            db.close()
            raise ValueError("Unexpected map cache schema; rebuild this cache.")
        allowed = {
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
            sqlite3.SQLITE_PRAGMA,
            sqlite3.SQLITE_RECURSIVE,
        }
        db.set_authorizer(
            lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY
        )
    return db


def geometry_info(
    geom: Any, layer: str, *, catalog_invalid: bool = False
) -> tuple[int, list[list[float]]]:
    """Validate actual geometry, coordinate ranges and per-feature complexity."""
    allowed = (
        ("LineString", "MultiLineString")
        if layer in ("roads", "water_lines")
        else ("Polygon", "MultiPolygon")
    )
    if geom.is_empty or geom.geom_type not in allowed:
        raise ValueError(f"Invalid/empty {layer} geometry type.")
    coords = get_coordinates(geom)
    count = len(coords)
    if count > MAX_FEATURE_VERTICES:
        raise ValueError(f"{layer}: exceeds one million vertices per feature.")
    if not (
        (coords[:, 0] >= -180)
        & (coords[:, 0] <= 180)
        & (coords[:, 1] >= -90)
        & (coords[:, 1] <= 90)
    ).all():
        raise ValueError(f"{layer}: non-finite or out-of-range WGS84 coordinates.")
    if catalog_invalid and layer in ("countries", "admin1", "water_areas"):
        return count, [list(geom.bounds)]
    # The global catalog may contain polar boundaries; only selected geographic operations
    # require the supported unwrapped representation for those components.
    if layer in ("countries", "admin1") and (geom.bounds[1] <= -89.99 or geom.bounds[3] >= 89.99):
        if not geom.is_valid:
            raise ValueError(f"Invalid {layer} geometry.")
        return count, [list(geom.bounds)]
    if not all(part.is_valid for part in geography.components(geom)):
        raise ValueError(f"Invalid {layer} geometry.")
    return count, geography.envelopes(geom)


class Store:
    """One streaming store; database transactions bound retained Python state."""

    def __init__(self, path: Path, *, create: bool = False) -> None:
        self.path = path
        self.db = connect(path, create=create)
        self.count = 0
        self.vertices = 0
        self.pending_bytes = 0
        self.operations = 0

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *args: Any) -> None:
        if args[0] is None:
            self.db.commit()
        self.db.close()

    def flush(self, size: int = 0) -> None:
        self.operations += 1
        self.pending_bytes += size
        if self.operations >= 1000 or self.pending_bytes >= 8 * MIB:
            self.db.commit()
            self.operations = self.pending_bytes = 0

    def entity(
        self, identity: str, version: int, visible: bool, digest: str, eligibility: int
    ) -> None:
        current = self.db.execute(
            "SELECT version,digest FROM entities WHERE identity=?", (identity,)
        ).fetchone()
        if current and current[0] == version and current[1] != digest:
            raise ValueError(
                f"{identity}: conflicting same-version objects; use current snapshot extracts."
            )
        self.db.execute(
            (
                "INSERT INTO entities VALUES(?,?,?,?,?) ON CONFLICT(identity) DO U"
                "PDATE SET version=excluded.version,visible=excluded.visible,diges"
                "t=excluded.digest,eligibility=excluded.eligibility WHERE excluded"
                ".version>entities.version"
            ),
            (identity, version, int(visible), digest, eligibility),
        )
        self.flush()

    def add(self, layer: str, identity: str, geom: Any, properties: dict[str, Any]) -> None:
        count, boxes = geometry_info(
            geom, layer, catalog_invalid=properties.get("geometry_state") == "invalid"
        )
        blob = to_wkb(geom)
        props = json.dumps(properties, sort_keys=True, allow_nan=False)
        if len(blob) > MAX_BLOB or len(props.encode()) > MAX_PROPERTIES:
            raise ValueError(f"{identity}: serialized feature exceeds supported size.")
        version = properties.get("version", 0)
        old = self.db.execute(
            "SELECT version,vertices FROM features WHERE layer=? AND identity=?", (layer, identity)
        ).fetchone()
        if old and old[0] > version:
            return
        self.count += int(old is None)
        self.vertices += count - (old[1] if old else 0)
        if self.count > MAX_FEATURES or self.vertices > MAX_VERTICES:
            raise ValueError(
                "Prepared data exceeds five million features or 100 million vertices; "
                "reduce selected classes."
            )
        self.db.execute(
            "INSERT OR REPLACE INTO features VALUES(?,?,?,?,?,?)",
            (layer, identity, version, props, blob, count),
        )
        self.db.execute("DELETE FROM envelopes WHERE layer=? AND identity=?", (layer, identity))
        self.db.executemany(
            "INSERT INTO envelopes VALUES(?,?,?,?,?,?,?)",
            [(layer, identity, i, *bounds) for i, bounds in enumerate(boxes)],
        )
        self.flush(len(blob) + len(props))


def read_features(db: sqlite3.Connection, layer: str | None = None) -> Iterator[dict[str, Any]]:
    """Check serialized lengths before fetching/decoding each bounded row."""
    sql = (
        "SELECT layer,identity,version,vertices,typeof(geometry),length(ge"
        "ometry),typeof(properties),length(CAST(properties AS BLOB)) FROM "
        "features"
    )
    params: tuple[Any, ...] = ()
    if layer is not None:
        sql += " WHERE layer=?"
        params = (layer,)
    sql += " ORDER BY layer,identity"
    for kind, identity, version, vertices, blobtype, bloblen, proptype, proplen in db.execute(
        sql, params
    ):
        if (
            kind not in LAYERS
            or not isinstance(identity, str)
            or len(identity) > 1024
            or not isinstance(version, int)
            or version < 0
            or not isinstance(vertices, int)
            or not 0 < vertices <= MAX_FEATURE_VERTICES
            or blobtype != "blob"
            or not 0 < bloblen <= MAX_BLOB
            or proptype != "text"
            or not 0 < proplen <= MAX_PROPERTIES
        ):
            raise ValueError("Invalid cached feature types, size or vertex count.")
        props, blob = db.execute(
            "SELECT properties,geometry FROM features WHERE layer=? AND identity=?",
            (kind, identity),
        ).fetchone()
        from travelmap.itinerary import decode_json

        properties = decode_json(props.encode())
        if not isinstance(properties, dict) or properties.get("version", 0) != version:
            raise ValueError("Invalid cached feature metadata/version.")
        repair = properties.get("geometry_repair")
        if repair is not None and (
            kind != "water_areas"
            or not isinstance(repair, dict)
            or repair.get("method") != "shapely.make_valid"
            or repair.get("result_type") not in ("Polygon", "MultiPolygon")
            or any(
                type(repair.get(field)) is not int or not 0 < repair[field] <= MAX_FEATURE_VERTICES
                for field in ("original_vertices", "repaired_vertices")
            )
            or repair.get("repaired_vertices") != vertices
        ):
            raise ValueError("Invalid cached water repair metadata.")
        if (
            kind == "water_areas"
            and properties.get("geometry_state") == "invalid"
            and properties.get("geometry_role") != "repair_original"
        ):
            raise ValueError("Invalid original water repair record.")
        name = properties.get("name")
        if name is not None and (not isinstance(name, str) or len(name) > 4096):
            raise ValueError("Invalid cached feature name.")
        if kind in ("countries", "admin1"):
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Missing cached boundary name.")
            code = properties.get("code")
            if code is not None and (not isinstance(code, str) or len(code) > 128):
                raise ValueError("Invalid cached boundary code.")
            if properties.get("geometry_state") not in (None, "invalid"):
                raise ValueError("Invalid cached boundary validation state.")
            for field in ("country_code", "country_name"):
                if properties.get(field) is not None and (
                    not isinstance(properties[field], str) or len(properties[field]) > 4096
                ):
                    raise ValueError("Invalid cached boundary parent metadata.")
        else:
            field = {"roads": "highway", "water_lines": "waterway", "water_areas": "water_type"}[
                kind
            ]
            if (
                not isinstance(properties.get(field), str)
                or not properties[field].strip()
                or len(properties[field]) > 128
            ):
                raise ValueError("Invalid cached feature class.")
        geom = from_wkb(blob)
        count, boxes = geometry_info(
            geom, kind, catalog_invalid=properties.get("geometry_state") == "invalid"
        )
        actual = [
            list(row)
            for row in db.execute(
                "SELECT west,south,east,north FROM envelopes "
                "WHERE layer=? AND identity=? ORDER BY part",
                (kind, identity),
            )
        ]
        if count != vertices or actual != boxes:
            raise ValueError("Invalid cached vertices/count or geographic envelopes.")
        yield {
            "type": "Feature",
            "id": identity,
            "geometry": dict(mapping(geom)),
            "properties": properties,
            "layer": kind,
            "vertices": count,
        }


def validate(
    path: Path, report: Callable[[str], None] = lambda _: None
) -> dict[str, dict[str, int]]:
    """Validate every row, including unvisited features; hashes alone do not certify content."""
    db = connect(path)
    result: dict[str, dict[str, int]] = {}
    try:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Corrupt map cache; rebuild it.")
        total_vertices = 0
        for index, feature in enumerate(read_features(db), 1):
            total_vertices += feature["vertices"]
            if index > MAX_FEATURES or total_vertices > MAX_VERTICES:
                raise ValueError(
                    "Cached data exceeds feature/vertex limits; reprepare selected classes."
                )
            stats = result.setdefault(feature["layer"], {"count": 0})
            stats["count"] += 1
            if index % 1000 == 0:
                report(f"Validating map cache: {index:,} features checked.")
        for index, (identity, version, visible, digest, eligibility) in enumerate(
            db.execute("SELECT * FROM entities"), 1
        ):
            if index % 10000 == 0:
                report(f"Validating entity ledger: {index:,} versions checked.")
            if (
                not isinstance(identity, str)
                or not identity.startswith(("osm:way:", "osm:relation:"))
                or len(identity) > 128
                or not isinstance(version, int)
                or version < 0
                or visible not in (0, 1)
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or not isinstance(eligibility, int)
                or not 0 <= eligibility <= 7
            ):
                raise ValueError("Invalid cached entity ledger.")
        if db.execute("SELECT count(*) FROM pending").fetchone()[0]:
            raise ValueError("Incomplete cached water relation assembly.")
        extra = db.execute(
            "SELECT count(*) FROM envelopes e LEFT JOIN features f ON e.layer="
            "f.layer AND e.identity=f.identity WHERE f.identity IS NULL"
        ).fetchone()[0]
        if extra:
            raise ValueError("Invalid orphaned cache envelopes.")
        return result
    finally:
        db.close()


def features(path: Path, layer: str) -> Iterator[dict[str, Any]]:
    db = connect(path)
    try:
        yield from read_features(db, layer)
    finally:
        db.close()


def entity_digest(obj: Any) -> str:
    """Canonical raw-content identity used for deterministic equal-version diagnostics."""
    tags = sorted((t.k, t.v) for t in obj.tags)
    refs = (
        [n.ref for n in obj.nodes]
        if obj.is_way()
        else [(m.type, m.ref, m.role) for m in obj.members]
    )
    return hashlib.sha256(
        json.dumps([tags, refs, obj.visible], separators=(",", ":")).encode()
    ).hexdigest()
