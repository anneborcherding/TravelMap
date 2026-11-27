"""Bounded persistent evidence for successful prepared-store validation."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

MAX_RECEIPT_BYTES = 4 * 1024 * 1024
STORE_RULE_VERSION = 1
READINESS_RULE_VERSION = 2
RECEIPT_NAME = "validation-reuse.json"


def _identity(path: Path) -> list[int] | None:
    """Return a safe regular-file identity without following symlinks."""
    try:
        current = path
        while current != current.parent:
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                return None
            current = current.parent
        info = path.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _sidecars_absent(database: Path) -> bool:
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            Path(str(database) + suffix).lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return False
        return False
    return True


def has_sidecars(database: Path) -> bool:
    return not _sidecars_absent(database)


def _receipt_path(database: Path) -> Path:
    # <workspace>/cache/map-data/<store>/features.sqlite
    return database.parents[3] / ".travelmap" / RECEIPT_NAME


def _workspace_receipt(root: Path) -> Path:
    return root / ".travelmap" / RECEIPT_NAME


def _safe_identities(paths: list[Path]) -> list[list[int]] | None:
    values = [_identity(path) for path in paths]
    if any(value is None for value in values):
        return None
    return [value for value in values if value is not None]


def file_snapshot(paths: list[Path]) -> list[list[int]] | None:
    """Return identities for paths discovered by the current caller."""
    return _safe_identities(paths)


def optional_file_snapshot(paths: list[Path]) -> list[list[Any]] | None:
    """Snapshot expected controls, retaining missing-file sentinels safely."""
    values: list[list[str | list[int] | None]] = []
    for path in paths:
        try:
            path.lstat()
        except FileNotFoundError:
            values.append([source_identifier(path), None])
            continue
        except OSError:
            return None
        identity = _identity(path)
        if identity is None:
            return None
        values.append([source_identifier(path), identity])
    return values


def receipt_snapshot(root: Path) -> list[list[Any]] | None:
    """Capture receipt state before validation so later revocation wins over stale work."""
    return optional_file_snapshot([_workspace_receipt(root)])


def source_identifier(path: Path) -> str:
    locator = os.path.normcase(os.path.abspath(path))
    return hashlib.sha256(locator.encode("utf-8", errors="surrogateescape")).hexdigest()


def revoke_sources(root: Path, paths: list[Path]) -> bool:
    """Atomically remove prior source successes before a forced freshness check."""
    receipt = _workspace_receipt(root)
    lock = receipt.with_name(receipt.name + ".lock")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        return False
    temporary: Path | None = None
    try:
        os.write(lock_fd, str(uuid4()).encode("ascii"))
        os.close(lock_fd)
        if not receipt.exists():
            return True
        current = _decode(receipt)
        if current is None:
            return True
        sources = dict(current["sources"])
        for path in paths:
            sources.pop(source_identifier(path), None)
        generation = str(uuid4())
        current.update(sources=sources, readiness=None, generation=generation)
        encoded = json.dumps(current, sort_keys=True, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_RECEIPT_BYTES:
            return False
        with tempfile.NamedTemporaryFile(dir=receipt.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, receipt)
        temporary = None
        temporary = None
        temporary = None
        return True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        try:
            os.close(lock_fd)
        except OSError:
            pass
        try:
            lock.unlink()
        except OSError:
            pass


def source_result(
    root: Path, source_id: str, config_sha256: str, paths: list[Path]
) -> list[str] | None:
    identities = _safe_identities(paths)
    receipt = _decode(_workspace_receipt(root))
    if identities is None or receipt is None:
        return None
    item = receipt["sources"].get(source_id)
    if (
        not isinstance(item, dict)
        or set(item) != {"config_sha256", "dependencies", "content_sha256"}
        or item.get("config_sha256") != config_sha256
        or item.get("dependencies") != identities
    ):
        return None
    dependencies = item.get("dependencies")
    hashes = item.get("content_sha256")
    if (
        not isinstance(item.get("config_sha256"), str)
        or len(item["config_sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in item["config_sha256"])
        or not isinstance(dependencies, list)
        or not 1 <= len(dependencies) <= 4
        or any(
            not isinstance(identity_value, list)
            or len(identity_value) != 5
            or any(
                not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 2**64 - 1
                for value in identity_value
            )
            for identity_value in dependencies
        )
    ):
        return None
    hashes = item.get("content_sha256")
    if (
        not isinstance(hashes, list)
        or len(hashes) != len(paths)
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
            for value in hashes
        )
        or _safe_identities(paths) != identities
    ):
        return None
    return hashes


def save_source_result(
    root: Path,
    source_id: str,
    config_sha256: str,
    paths: list[Path],
    hashes: list[str],
    identities: list[list[int]],
    *,
    expected_receipt: list[list[Any]] | None = None,
) -> None:
    if len(paths) != len(hashes) or len(paths) != len(identities):
        return
    receipt = _workspace_receipt(root)
    lock = receipt.with_name(receipt.name + ".lock")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        return
    temporary: Path | None = None
    try:
        os.write(lock_fd, str(uuid4()).encode("ascii"))
        os.close(lock_fd)
        if expected_receipt is not None and receipt_snapshot(root) != expected_receipt:
            return
        current: dict[str, Any] | None = (
            _decode(receipt)
            if receipt.exists()
            else {
                "schema_version": 1,
                "generation": str(uuid4()),
                "sources": {},
                "stores": {},
                "readiness": None,
            }
        )
        if current is None or _safe_identities(paths) != identities:
            return
        current["sources"][source_id] = {
            "config_sha256": config_sha256,
            "dependencies": identities,
            "content_sha256": hashes,
        }
        if len(current["sources"]) > 32:
            return
        current["generation"] = str(uuid4())
        encoded = json.dumps(current, sort_keys=True, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_RECEIPT_BYTES:
            return
        with tempfile.NamedTemporaryFile(dir=receipt.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, receipt)
    except (OSError, TypeError, ValueError):
        return
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        try:
            os.close(lock_fd)
        except OSError:
            pass
        try:
            lock.unlink()
        except OSError:
            pass


def canonical_digest(value: Any) -> str:
    content = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def readiness_key(
    root: Path,
    trip: dict[str, Any],
    resolved: dict[str, dict[str, Any]],
    settings: dict[str, Any],
    selection: dict[str, Any],
) -> str:
    """Identify every accepted input consumed by boundary and coverage readiness."""
    from travelmap import boundary_review, itinerary, map_view, mapdata, reference_layout, routes
    from travelmap.workspace import plan_workspace

    itinerary.validate(trip)
    route_keys = []
    for segment in itinerary.parts(trip, "segment"):
        segment_key = routes.segment_key(trip, segment)
        record = resolved.get(segment_key)
        if record is None:
            raise ValueError("Cannot identify readiness with unresolved routes.")
        routes.valid_record(record, routes.endpoints(trip, segment))
        route_keys.append([segment_key, record["coordinates"]])
    page = {
        key: value
        for key, value in settings["poster"].items()
        if key not in {"title", "subtitle", "title_case"}
    }
    map_settings = json.loads(json.dumps(settings["map"], allow_nan=False))
    for field in ("routing", "distance"):
        map_settings.pop(field, None)
    for field in ("simplify_geometry", "simplify_tolerance_mm", "min_area_km2"):
        map_settings.get("water", {}).pop(field, None)
    geographic_trip = json.loads(json.dumps(trip, allow_nan=False))
    distance_fields = {
        "distance",
        "distance_m",
        "distance_km",
        "kilometres",
        "kilometers",
        "duration_s",
        "duration_days",
        "days",
    }
    for feature in geographic_trip.get("features", []):
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict):
            feature["properties"] = {
                key: value
                for key, value in feature["properties"].items()
                if key not in distance_fields
            }
    viewport = reference_layout.viewport(page, map_settings["scale"])
    paths = plan_workspace(root)
    sources = selection.get("sources")
    if not isinstance(sources, list) or len(sources) > 32:
        raise ValueError("Prepared selection has an invalid source list.")
    store_names = [selection.get("directory")]
    for item in sources:
        if not isinstance(item, dict) or not isinstance(item.get("directory"), str):
            raise ValueError("Prepared selection contains an invalid source record.")
        store_names.append(item["directory"])
    if any(
        not isinstance(name, str) or Path(name).name != name or name in {".", ".."}
        for name in store_names
    ):
        raise ValueError("Prepared selection contains an unsafe store locator.")
    store_snapshots = []
    for name in sorted({value for value in store_names if isinstance(value, str)}):
        directory = paths.cache_dir / "map-data" / name
        database = directory / "features.sqlite"
        manifest = directory / "manifest.json"
        repair = directory / "repair-originals.sqlite"
        if has_sidecars(database) or has_sidecars(repair):
            raise ValueError("SQLite journal sidecars disable readiness reuse.")
        db_identity = _identity(database)
        manifest_identity = _identity(manifest)
        repair_identity = _identity(repair)
        if db_identity is None or manifest_identity is None:
            raise ValueError("Prepared store is unavailable for readiness identity.")
        if manifest_identity[2] > 1024 * 1024:
            raise ValueError("Prepared manifest exceeds the readiness reuse limit.")
        try:
            with manifest.open("rb") as stream:
                manifest_content = stream.read(1024 * 1024 + 1)
        except OSError as exc:
            raise ValueError("Prepared manifest cannot be read safely.") from exc
        if len(manifest_content) > 1024 * 1024 or _identity(manifest) != manifest_identity:
            raise ValueError("Prepared manifest changed while it was checked.")
        store_snapshots.append(
            [
                name,
                db_identity,
                manifest_identity,
                hashlib.sha256(manifest_content).hexdigest(),
                repair_identity,
            ]
        )
    source_snapshots = []
    source_settings = mapdata.settings_for(root)
    for source in mapdata.active_sources(mapdata.discover(root, source_settings), source_settings):
        source_path = Path(source["path"])
        components = [source_path]
        if source_path.suffix.lower() == ".shp":
            components.extend(
                source_path.with_suffix(suffix) for suffix in (".shx", ".dbf", ".prj")
            )
        identities = _safe_identities(components)
        if identities is None:
            raise ValueError("A map source is unavailable for readiness identity.")
        source_snapshots.append([source_identifier(source_path), identities])
    # Trip geometry and geographic settings are projected above. Raw artwork/acceptance
    # snapshots would invalidate readiness for color/title/distance-only edits. Export
    # still checks current complete settings acceptance and snapshots all controls.
    control_limits = {
        "map-settings.json": 1024 * 1024,
        "map-data.json": 1024 * 1024,
        "boundary-review.json": 256 * 1024,
        "manual-assignments.json": 8 * 1024 * 1024,
        "route-choices.json": 8 * 1024 * 1024,
        "routing-settings.json": 1024 * 1024,
    }
    control_snapshots: list[list[str | list[int] | None]] = []
    for name, limit in control_limits.items():
        control = paths.metadata_dir / name
        identity = _identity(control)
        if identity is None:
            try:
                control.lstat()
            except FileNotFoundError:
                control_snapshots.append([source_identifier(control), None, None])
                continue
            raise ValueError("A readiness control file is redirected or unsupported.")
        if identity[2] > limit:
            raise ValueError("A readiness control file exceeds its reuse limit.")
        try:
            with control.open("rb") as stream:
                content = stream.read(limit + 1)
        except OSError as exc:
            raise ValueError("A readiness control file cannot be read safely.") from exc
        if len(content) > limit or _identity(control) != identity:
            raise ValueError("A readiness control file changed while it was checked.")
        control_snapshots.append(
            [source_identifier(control), identity, hashlib.sha256(content).hexdigest()]
        )
    payload = {
        "rule": READINESS_RULE_VERSION,
        "map_view_rule": map_view.RULE_VERSION,
        "trip": geographic_trip,
        "routes": route_keys,
        "page": page,
        "map": map_settings,
        "usable_viewport": viewport,
        "selection": selection,
        "store_snapshots": store_snapshots,
        "source_snapshots": source_snapshots,
        "control_snapshots": control_snapshots,
        "boundary_review": boundary_review.receipt_identity(root),
    }
    return canonical_digest(payload)


def readiness_result(root: Path, input_sha256: str) -> dict[str, Any] | None:
    receipt = _decode(_workspace_receipt(root))
    if receipt is None:
        return None
    item = receipt["readiness"]
    if (
        not isinstance(item, dict)
        or set(item)
        != {
            "input_sha256",
            "rule",
            "counts",
            "include_offshore",
            "journey_expanded_frame",
            "warning_codes",
        }
        or item.get("input_sha256") != input_sha256
        or type(item.get("rule")) is not int
        or item.get("rule") != READINESS_RULE_VERSION
    ):
        return None
    counts = item.get("counts")
    if (
        not isinstance(counts, dict)
        or set(counts) != {"included", "excluded", "trip"}
        or any(type(value) is not int or not 0 <= value <= 1_000_000 for value in counts.values())
        or type(item.get("include_offshore")) is not bool
        or type(item.get("journey_expanded_frame")) is not bool
        or not isinstance(item.get("warning_codes"), list)
        or len(item["warning_codes"]) > 64
        or any(
            code not in {"unknown_coverage", "journey_expands_frame"}
            for code in item["warning_codes"]
        )
    ):
        return None
    return item


def readiness_matches(root: Path, input_sha256: str) -> bool:
    return readiness_result(root, input_sha256) is not None


def save_readiness(
    root: Path,
    input_sha256: str,
    counts: dict[str, int],
    include_offshore: bool,
    journey_expanded_frame: bool,
    warning_codes: list[str],
    current_key: Callable[[], str] | None = None,
    *,
    expected_receipt: list[list[Any]] | None = None,
) -> str | None:
    """Persist successful readiness and return the new receipt generation."""
    path = _workspace_receipt(root)
    lock = path.with_name(path.name + ".lock")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        return None
    temporary: Path | None = None
    try:
        os.write(lock_fd, str(uuid4()).encode("ascii"))
        os.close(lock_fd)
        if expected_receipt is not None and receipt_snapshot(root) != expected_receipt:
            return None
        current: dict[str, Any] | None = (
            _decode(path)
            if path.exists()
            else {
                "schema_version": 1,
                "generation": str(uuid4()),
                "sources": {},
                "stores": {},
                "readiness": None,
            }
        )
        if current is None or current_key is not None and current_key() != input_sha256:
            return None
        current["readiness"] = {
            "input_sha256": input_sha256,
            "rule": READINESS_RULE_VERSION,
            "counts": counts,
            "include_offshore": include_offshore,
            "journey_expanded_frame": journey_expanded_frame,
            "warning_codes": warning_codes,
        }
        generation = str(uuid4())
        current["generation"] = generation
        encoded = json.dumps(current, sort_keys=True, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_RECEIPT_BYTES:
            return None
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if current_key is not None and current_key() != input_sha256:
            return None
        os.replace(temporary, path)
        temporary = None
        return generation
    except (OSError, TypeError, ValueError):
        return None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        try:
            os.close(lock_fd)
        except OSError:
            pass
        try:
            lock.unlink()
        except OSError:
            pass


def readiness_token(root: Path, input_sha256: str) -> dict[str, str] | None:
    receipt = _decode(_workspace_receipt(root))
    if receipt is None or readiness_result(root, input_sha256) is None:
        return None
    current = _decode(_workspace_receipt(root))
    if current is None or current["generation"] != receipt["generation"]:
        return None
    return {"input_sha256": input_sha256, "generation": receipt["generation"]}


@contextmanager
def publication_guard(
    root: Path,
    token: dict[str, str],
    check_current: Callable[[], bool] | None = None,
) -> Iterator[None]:
    """Hold the short receipt lock across final rename for receipt-derived work."""
    path = _workspace_receipt(root)
    lock = path.with_name(path.name + ".lock")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError as exc:
        raise ValueError("Validation receipt is busy; retry export.") from exc
    os.close(lock_fd)
    try:
        receipt = _decode(path)
        if (
            receipt is None
            or receipt["generation"] != token.get("generation")
            or readiness_result(root, token.get("input_sha256", "")) is None
        ):
            raise ValueError("Validated inputs changed; return to Export and recheck.")
        if check_current is not None and not check_current():
            raise ValueError("Validated files changed before publication; retry preflight.")
        yield
    finally:
        lock.unlink(missing_ok=True)


@contextmanager
def snapshot_guard(check_current: Callable[[], bool]) -> Iterator[None]:
    """Recheck cold operation-local dependencies immediately before publication."""
    if not check_current():
        raise ValueError("Validated files changed before publication; retry preflight.")
    yield


def _decode(path: Path) -> dict[str, Any] | None:
    identity = _identity(path)
    if identity is None or identity[2] > MAX_RECEIPT_BYTES:
        return None
    try:
        with path.open("rb") as stream:
            payload = json.loads(
                stream.read(MAX_RECEIPT_BYTES + 1),
                object_pairs_hook=_unique_object,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid number")),
            )
        required = {"schema_version", "generation", "stores"}
        allowed = required | {"sources", "readiness"}
        if not isinstance(payload, dict) or not required <= set(payload) <= allowed:
            return None
        if _depth(payload) > 16:
            return None
        if (
            not isinstance(payload["schema_version"], int)
            or isinstance(payload["schema_version"], bool)
            or payload["schema_version"] != 1
        ):
            return None
        try:
            uuid.UUID(payload["generation"])
        except (ValueError, TypeError, AttributeError):
            return None
        if not isinstance(payload["generation"], str):
            return None
        if not isinstance(payload["stores"], dict) or len(payload["stores"]) > 128:
            return None
        payload.setdefault("sources", {})
        payload.setdefault("readiness", None)
        if not isinstance(payload["sources"], dict) or len(payload["sources"]) > 32:
            return None
        if payload["readiness"] is not None and not isinstance(payload["readiness"], dict):
            return None
        if _identity(path) != identity:
            return None
        return payload
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        return None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _depth(value: Any, level: int = 0) -> int:
    if level > 16:
        return level
    if isinstance(value, dict):
        return max((_depth(item, level + 1) for item in value.values()), default=level)
    if isinstance(value, list):
        return max((_depth(item, level + 1) for item in value), default=level)
    return level


def store_result(
    database: Path,
    manifest: Path,
    repair: Path | None,
    database_sha256: str,
    repair_sha256: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    """Return previously verified counts when every current metadata identity matches."""
    if not _sidecars_absent(database) or repair is not None and not _sidecars_absent(repair):
        return None
    db_identity = _identity(database)
    manifest_identity = _identity(manifest)
    repair_identity = _identity(repair) if repair else None
    if (
        db_identity is None
        or manifest_identity is None
        or repair is not None
        and repair_identity is None
    ):
        return None
    try:
        if manifest_identity[2] > 1024 * 1024:
            return None
        with manifest.open("rb") as stream:
            manifest_content = stream.read(1024 * 1024 + 1)
        if len(manifest_content) > 1024 * 1024:
            return None
        manifest_digest = hashlib.sha256(manifest_content).hexdigest()
    except OSError:
        return None
    receipt = _decode(_receipt_path(database))
    if receipt is None:
        return None
    key = str(database.parent.name)
    item = receipt["stores"].get(key)
    expected = {
        "rule": STORE_RULE_VERSION,
        "database": db_identity,
        "manifest": manifest_identity,
        "manifest_sha256": manifest_digest,
        "database_sha256": database_sha256,
        "repair": repair_identity,
        "repair_sha256": repair_sha256,
    }
    if (
        not isinstance(item, dict)
        or set(item) != {*expected, "counts", "repair_counts"}
        or type(item.get("rule")) is not int
        or any(item.get(field) != value for field, value in expected.items())
    ):
        return None
    for identity_value in (item.get("database"), item.get("manifest"), item.get("repair")):
        if identity_value is None:
            continue
        if (
            not isinstance(identity_value, list)
            or len(identity_value) != 5
            or any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
                or value > 2**64 - 1
                for value in identity_value
            )
        ):
            return None
    manifest_hash = item.get("manifest_sha256")
    if (
        not isinstance(manifest_hash, str)
        or len(manifest_hash) != 64
        or any(char not in "0123456789abcdef" for char in manifest_hash)
    ):
        return None
    if (
        not isinstance(database_sha256, str)
        or len(database_sha256) != 64
        or any(char not in "0123456789abcdef" for char in database_sha256)
    ):
        return None
    counts = item.get("counts")
    if not isinstance(counts, dict) or len(counts) > 5:
        return None
    repair_counts = item.get("repair_counts")
    if repair_counts is not None and (
        not isinstance(repair_counts, dict)
        or any(
            not isinstance(name, str)
            or not isinstance(info, dict)
            or set(info) != {"count"}
            or type(info["count"]) is not int
            or not 0 <= info["count"] <= 5_000_000
            for name, info in repair_counts.items()
        )
    ):
        return None
    if (repair is None) != (repair_counts is None) or (repair is None) != (repair_sha256 is None):
        return None
    if any(
        not isinstance(name, str)
        or not isinstance(info, dict)
        or set(info) != {"count"}
        or not isinstance(info["count"], int)
        or isinstance(info["count"], bool)
        or not 0 <= info["count"] <= 5_000_000
        for name, info in counts.items()
    ):
        return None
    if (
        _identity(database) != db_identity
        or _identity(manifest) != manifest_identity
        or repair is not None
        and _identity(repair) != repair_identity
        or not _sidecars_absent(database)
        or repair is not None
        and not _sidecars_absent(repair)
    ):
        return None
    return counts, repair_counts


def save_store_result(
    database: Path,
    manifest: Path,
    repair: Path | None,
    counts: dict[str, Any],
    database_sha256: str,
    repair_counts: dict[str, Any] | None = None,
    repair_sha256: str | None = None,
    *,
    expected_receipt: list[list[Any]] | None = None,
) -> None:
    """Atomically record successful validation; contention or unsafe paths disable caching."""
    if (
        not _sidecars_absent(database)
        or repair is not None
        and not _sidecars_absent(repair)
        or (repair is None) != (repair_counts is None)
        or (repair is None) != (repair_sha256 is None)
    ):
        return
    db_identity = _identity(database)
    manifest_identity = _identity(manifest)
    repair_identity = _identity(repair) if repair else None
    if (
        db_identity is None
        or manifest_identity is None
        or repair is not None
        and repair_identity is None
    ):
        return
    try:
        with manifest.open("rb") as stream:
            manifest_bytes = stream.read(1024 * 1024 + 1)
        if len(manifest_bytes) > 1024 * 1024:
            return
    except OSError:
        return
    path = _receipt_path(database)
    lock = path.with_name(path.name + ".lock")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        return
    temporary: Path | None = None
    try:
        os.write(lock_fd, str(uuid4()).encode("ascii"))
        os.close(lock_fd)
        if expected_receipt is not None and optional_file_snapshot([path]) != expected_receipt:
            return
        current = _decode(path) if path.exists() else None
        if path.exists() and current is None:
            return
        stores = current["stores"] if current else {}
        stores[str(database.parent.name)] = {
            "rule": STORE_RULE_VERSION,
            "database": db_identity,
            "manifest": manifest_identity,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "database_sha256": database_sha256,
            "repair": repair_identity,
            "repair_sha256": repair_sha256,
            "counts": counts,
            "repair_counts": repair_counts,
        }
        payload = {
            "schema_version": 1,
            "generation": str(uuid4()),
            "sources": current["sources"] if current else {},
            "stores": stores,
            "readiness": current["readiness"] if current else None,
        }
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")
        if (
            len(encoded) > MAX_RECEIPT_BYTES
            or _identity(database) != db_identity
            or _identity(manifest) != manifest_identity
            or repair is not None
            and _identity(repair) != repair_identity
            or not _sidecars_absent(database)
            or repair is not None
            and not _sidecars_absent(repair)
        ):
            return
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except (OSError, TypeError, ValueError):
        return
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        try:
            lock.unlink()
        except OSError:
            pass


def revoke_store(database: Path) -> bool:
    """Revoke a store success before an explicit full recheck; never steal a lock."""
    path = _receipt_path(database)
    lock = path.with_name(path.name + ".lock")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        return False
    temporary: Path | None = None
    try:
        os.write(lock_fd, str(uuid4()).encode("ascii"))
        os.close(lock_fd)
        exists = path.exists()
        current: dict[str, Any] | None = (
            _decode(path)
            if exists
            else {
                "schema_version": 1,
                "generation": str(uuid4()),
                "sources": {},
                "stores": {},
                "readiness": None,
            }
        )
        if current is None:
            current = {
                "schema_version": 1,
                "generation": str(uuid4()),
                "sources": {},
                "stores": {},
                "readiness": None,
            }
        stores = dict(current["stores"])
        stores.pop(str(database.parent.name), None)
        payload = {
            "schema_version": 1,
            "generation": str(uuid4()),
            "sources": current["sources"],
            "stores": stores,
            "readiness": None,
        }
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_RECEIPT_BYTES:
            return False
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        return True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        try:
            os.close(lock_fd)
        except OSError:
            pass
        try:
            lock.unlink()
        except OSError:
            pass


def revoke_export_scope(
    root: Path, store_names: list[str] | None, source_paths: list[Path] | None
) -> bool:
    """Revoke selected successes atomically; None selects all workspace stores or sources."""
    path = _workspace_receipt(root)
    lock = path.with_name(path.name + ".lock")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except OSError:
        return False
    temporary: Path | None = None
    try:
        os.write(lock_fd, str(uuid4()).encode("ascii"))
        os.close(lock_fd)
        current: dict[str, Any] | None = (
            _decode(path)
            if path.exists()
            else {
                "schema_version": 1,
                "generation": str(uuid4()),
                "sources": {},
                "stores": {},
                "readiness": None,
            }
        )
        if current is None:
            current = {
                "schema_version": 1,
                "generation": str(uuid4()),
                "sources": {},
                "stores": {},
                "readiness": None,
            }
        stores = dict(current["stores"]) if store_names is not None else {}
        sources = dict(current["sources"]) if source_paths is not None else {}
        for name in store_names or []:
            stores.pop(name, None)
        for source_path in source_paths or []:
            sources.pop(source_identifier(source_path), None)
        current.update(generation=str(uuid4()), sources=sources, stores=stores, readiness=None)
        encoded = json.dumps(current, sort_keys=True, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_RECEIPT_BYTES:
            return False
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        return True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        try:
            os.close(lock_fd)
        except OSError:
            pass
        try:
            lock.unlink()
        except OSError:
            pass
