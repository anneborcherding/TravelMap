"""Offline map-data planning, safe extraction, cache validation and worker orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from travelmap.itinerary import decode_json, parts
from travelmap.reporting import ReportKind, report_feedback
from travelmap.workspace import MAX_DIRECTORY_ENTRIES, plan_workspace

MIB = 1024 * 1024
MAX_VECTOR_BYTES = 64 * MIB
PBF_WARNING_BYTES = 512 * MIB
TOTAL_INPUT_WARNING_BYTES = 1024 * MIB
MAX_ENTRIES = 256
MAX_EXPANDED_BYTES = 256 * MIB
MAX_ENTRY_BYTES = 128 * MIB
MAX_OUTPUT_BYTES = 64 * MIB
PREPARATION_VERSION = 2
COUNTRIES = "ne_10m_admin_0_countries.zip"
ADMIN1 = "ne_10m_admin_1_states_provinces.zip"
DEFAULT_HIGHWAYS = (
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
    "residential",
    "unclassified",
)
DEFAULT_WATER_LINES = ("river", "canal")
DEFAULT_WATER_AREAS = ("water", "lake", "reservoir", "river", "pond", "basin")


class MapDataError(ValueError):
    """Expected local data/resource/preparation failure with recovery guidance."""


class CountryCoverageError(MapDataError):
    """A stop is outside every supplied country polygon; retain its identity for recovery."""

    def __init__(self, stop_id: str, name: str) -> None:
        self.stop_id = stop_id
        self.review_signature: str | None = None
        super().__init__(
            f"Coverage incomplete: {name}: country boundary does not cover stop. "
            "The coordinate may be inaccurate or the supplied boundaries incomplete."
        )


def read_json(path: Path, limit: int = MAX_OUTPUT_BYTES) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise MapDataError(f"{path.name}: expected a regular local file.")
        with path.open("rb") as stream:
            content = stream.read(limit + 1)
        if len(content) > limit:
            raise MapDataError(f"{path.name}: exceeds the {limit // MIB} MiB limit.")
        result = decode_json(content)
        if not isinstance(result, dict):
            raise MapDataError(f"{path.name}: expected a JSON object.")
        return result
    except (OSError, UnicodeError, ValueError) as exc:
        raise MapDataError(f"{path.name}: {exc}. Repair the local file and recheck.") from exc


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    content = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )
    if len(content) > MAX_OUTPUT_BYTES:
        raise MapDataError("Prepared output exceeds 64 MiB. Use smaller extracts or fewer layers.")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise MapDataError(
            f"Cannot save {path.name}: {exc}. Check disk space/permissions and retry."
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def digest(path: Path, limit: int | None, report: Callable[[str], None] = lambda _: None) -> str:
    if path.is_symlink() or not path.is_file():
        raise MapDataError(f"{path.name}: select a regular local file, not a link.")
    if limit is not None and path.stat().st_size > limit:
        raise MapDataError(
            f"{path.name}: exceeds {limit // MIB} MiB. Use smaller "
            f"country/subcountry extracts or fewer optional "
            f"layers; planet extracts are unsupported."
        )
    memo = _hashes.get()
    signature = file_identity(path)
    if memo is not None:
        existing = memo.get((str(path), limit))
        if existing is not None and existing[0] == signature:
            return existing[1]
    value = hashlib.sha256()
    size = 0
    last = time.monotonic()
    report(f"Checking {path.name}: reading file contents.")
    try:
        with path.open("rb") as stream:
            prefix = stream.read(512)
            if prefix.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                raise MapDataError(
                    f"{path.name}: HTML page, not map data. Download "
                    f"the actual ZIP or .osm.pbf dataset and recheck."
                )
            value.update(prefix)
            size += len(prefix)
            while chunk := stream.read(MIB):
                size += len(chunk)
                if limit is not None and size > limit:
                    raise MapDataError(
                        f"{path.name}: size limit exceeded. Choose a smaller extract."
                    )
                if size > signature[2]:
                    raise MapDataError(f"{path.name}: file changed while hashing; retry.")
                value.update(chunk)
                if time.monotonic() - last >= 5:
                    report(f"Checking {path.name}: {size // MIB} MiB read.")
                    last = time.monotonic()
    except OSError as exc:
        raise MapDataError(
            f"{path.name}: cannot read data: {exc}. Check permissions/re-download and recheck."
        ) from exc
    result = value.hexdigest()
    if file_identity(path) != signature:
        raise MapDataError(f"{path.name}: file changed while hashing; retry.")
    if memo is not None:
        memo[(str(path), limit)] = (signature, result)
    return result


def extract_boundary(archive: Path, destination: Path, kind: str) -> Path:
    """Validate the whole inventory before writing into an owned preparation folder."""
    try:
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            if len(entries) > MAX_ENTRIES:
                raise MapDataError(
                    "Archive exceeds 256 entries. Re-download the supported boundary ZIP."
                )
            seen: set[str] = set()
            total = 0
            for entry in entries:
                name = entry.filename
                path = PurePosixPath(name)
                mode = entry.external_attr >> 16
                if (
                    not name
                    or "\\" in name
                    or "\x00" in name
                    or path.is_absolute()
                    or any(part in ("..", "") for part in path.parts)
                    or ":" in name
                    or name.startswith("/")
                    or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                    or entry.flag_bits & 1
                ):
                    raise MapDataError(
                        f"Unsafe archive entry {name!r}. Re-download the official ZIP."
                    )
                if any(part in (".", "..") for part in name.rstrip("/").split("/")):
                    raise MapDataError(
                        f"Unsafe archive path {name!r}. Re-download the official ZIP."
                    )
                folded = path.as_posix().rstrip("/").casefold()
                if folded in seen:
                    raise MapDataError(
                        f"Colliding archive entries: {name!r}. Re-download the official ZIP."
                    )
                seen.add(folded)
                if entry.file_size > MAX_ENTRY_BYTES:
                    raise MapDataError(
                        "Archive entry exceeds 128 MiB. Choose a smaller supported dataset."
                    )
                total += entry.file_size
                if total > MAX_EXPANDED_BYTES:
                    raise MapDataError(
                        "Archive expansion exceeds 256 MiB. Choose a smaller supported dataset."
                    )
                if path.suffix.lower() in (".zip", ".tar", ".gz", ".7z"):
                    raise MapDataError(
                        "Nested archives are unsupported. Download the boundary dataset "
                        "ZIP directly."
                    )
            file_names = {
                PurePosixPath(e.filename).as_posix().casefold() for e in entries if not e.is_dir()
            }
            for entry in entries:
                if any(
                    parent.as_posix().casefold() in file_names
                    for parent in PurePosixPath(entry.filename).parents
                    if parent.as_posix() != "."
                ):
                    raise MapDataError(
                        "Archive file/directory collision. Re-download the official ZIP."
                    )
            for entry in entries:
                target = destination.joinpath(*PurePosixPath(entry.filename).parts)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                expanded = 0
                with source.open(entry) as incoming, target.open("xb") as outgoing:
                    while chunk := incoming.read(MIB):
                        expanded += len(chunk)
                        if expanded > min(entry.file_size, MAX_ENTRY_BYTES):
                            raise MapDataError(
                                "Actual expanded archive bytes exceed the declared limit."
                            )
                        outgoing.write(chunk)
            shapefiles = sorted(destination.rglob("*.shp"))
            expected = "admin_0_countries" if kind == "countries" else "admin_1_states_provinces"
            matches = [p for p in shapefiles if expected in p.stem.lower()]
            if len(matches) != 1:
                raise MapDataError(
                    f"ZIP must contain one supported Natural Earth {expected} "
                    f"shapefile. Re-download the correct polygon archive."
                )
            selected = matches[0]
            names = {p.name.casefold() for p in selected.parent.iterdir()}
            missing = [
                suffix
                for suffix in (".shx", ".dbf", ".prj")
                if selected.with_suffix(suffix).name.casefold() not in names
            ]
            if missing:
                raise MapDataError(
                    f"{selected.name}: missing companions {', '.join(missing)}. "
                    f"Re-download the full archive; CRS will not be "
                    f"guessed."
                )
            return selected
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise MapDataError(
            f"{archive.name}: incomplete/unreadable boundary "
            f"archive: {exc}. Re-download and recheck."
        ) from exc


def extent(trip: dict[str, Any]) -> list[float]:
    coords = [s["geometry"]["coordinates"] for s in parts(trip, "stop")]
    xs, ys = [c[0] for c in coords], [c[1] for c in coords]
    return [
        max(-180, min(xs) - 2),
        max(-90, min(ys) - 2),
        min(180, max(xs) + 2),
        min(90, max(ys) + 2),
    ]


def settings_for(root: Path, *, from_config: bool = True) -> dict[str, Any]:
    if from_config and (
        (root / "config.toml").exists()
        or (plan_workspace(root).metadata_dir / "file-settings-version.json").exists()
    ):
        from travelmap import flow, itinerary, poster_settings

        accepted = plan_workspace(root).metadata_dir / "itinerary.geojson"
        trip = (
            itinerary.load(accepted)[1][0][0]
            if accepted.exists()
            else {"metadata": {"name": root.name}}
        )
        flow.sync_settings(root, poster_settings.load(root, trip))
    path = plan_workspace(root).metadata_dir / "map-settings.json"
    defaults: dict[str, Any] = {
        "highway_classes": list(DEFAULT_HIGHWAYS),
        "water_line_classes": list(DEFAULT_WATER_LINES),
        "water_area_classes": list(DEFAULT_WATER_AREAS),
        "include_admin1": True,
        "vectors": [],
        "country_ids": [],
        "enabled_layers": ["roads", "water_lines", "water_areas"],
    }
    if not path.exists():
        return defaults
    raw = read_json(path, MIB)
    if raw.get("schema_version") != 1:
        raise MapDataError("map-settings.json: use schema_version 1.")
    for key in ("highway_classes", "water_line_classes", "water_area_classes"):
        if key in raw:
            values = raw[key]
            if (
                not isinstance(values, list)
                or len(values) > 64
                or any(not isinstance(v, str) or not v.strip() or len(v) > 100 for v in values)
            ):
                raise MapDataError(
                    f"map-settings.json: {key} must contain at most 64 nonempty class names."
                )
            defaults[key] = sorted(set(values))
    ids = raw.get("country_ids", [])
    if (
        not isinstance(ids, list)
        or len(ids) > 256
        or any(not isinstance(v, str) or not v or len(v) > 128 for v in ids)
    ):
        raise MapDataError("Country selection must contain valid boundary IDs.")
    defaults["country_ids"] = sorted(set(ids))
    enabled = raw.get("enabled_layers", defaults["enabled_layers"])
    if (
        not isinstance(enabled, list)
        or any(layer not in ("roads", "water_lines", "water_areas") for layer in enabled)
        or len(enabled) > 3
    ):
        raise MapDataError("enabled_layers must select roads, water_lines or water_areas.")
    defaults["enabled_layers"] = sorted(set(enabled))
    vectors = raw.get("vectors", [])
    if not isinstance(vectors, list) or len(vectors) > 16:
        raise MapDataError("map-settings.json: vectors must contain at most 16 local sources.")
    for item in vectors:
        if not isinstance(item, dict) or item.get("kind") not in (
            "countries",
            "admin1",
            "roads",
            "water_lines",
            "water_areas",
        ):
            raise MapDataError("Advanced vectors require a supported kind and local path.")
        if not isinstance(item.get("path"), str) or "://" in item["path"]:
            raise MapDataError("Advanced vector path must name a local file.")
        if item.get("layer") is not None and not isinstance(item["layer"], str):
            raise MapDataError("Advanced vector layer must be text.")
        for field in ("attribution", "licence"):
            if item.get(field) is not None and (
                not isinstance(item[field], str) or len(item[field]) > 4096
            ):
                raise MapDataError(f"Advanced vector {field} must be bounded text.")
    include_admin1 = raw.get("include_admin1", True)
    if not isinstance(include_admin1, bool):
        raise MapDataError("include_admin1 must be a boolean.")
    defaults["include_admin1"] = include_admin1
    defaults["vectors"] = vectors
    return defaults


def discover(root: Path, settings: dict[str, Any]) -> list[dict[str, Any]]:
    folder = plan_workspace(root).map_data_dir
    names: list[Path] = []
    with os.scandir(folder) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_DIRECTORY_ENTRIES:
                raise MapDataError(
                    "Map-data folder exceeds 1,000 entries. Use a smaller trip folder and recheck."
                )
            if entry.is_file(follow_symlinks=False):
                names.append(Path(entry.path))
    sources = []
    for path in sorted(names):
        lowered = path.name.lower()
        if lowered in (COUNTRIES, ADMIN1):
            sources.append(
                {"path": str(path), "kind": "countries" if lowered == COUNTRIES else "admin1"}
            )
        elif lowered.endswith(".osm.pbf"):
            if "planet" in lowered:
                raise MapDataError(
                    f"{path.name}: planet extracts are unsupported. "
                    f"Download country/subcountry PBFs."
                )
            sources.append({"path": str(path), "kind": "osm"})
    for item in settings["vectors"]:
        path = Path(item["path"])
        if not path.is_absolute():
            path = folder / path
        supported = {".shp", ".gpkg", ".geojson", ".json"}
        if item["kind"] in {"countries", "admin1"}:
            supported.add(".zip")
        if path.suffix.lower() not in supported:
            raise MapDataError(
                f"{path.name}: use SHP, GPKG or GeoJSON; boundaries also accept Natural Earth ZIPs."
            )
        sources.append({**item, "path": str(path)})
    pbfs = [s for s in sources if s["kind"] == "osm"]
    if len(pbfs) > 8:
        raise MapDataError("Use at most eight regional PBFs. Remove unused extracts and recheck.")
    return sources


def active_sources(sources: list[dict[str, Any]], settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Include boundaries and sources needed by visible background layers."""
    enabled = settings["enabled_layers"]
    return [
        source
        for source in sources
        if (
            source["kind"] == "countries"
            or (source["kind"] == "admin1" and settings.get("include_admin1", True))
        )
        or (source["kind"] == "osm" and enabled)
        or source["kind"] in enabled
    ]


def source_fingerprint(
    source: dict[str, Any],
    settings: dict[str, Any],
    bounds: list[float],
    report: Callable[[str], None],
    workspace_root: Path | None = None,
    force: bool = False,
) -> tuple[str, dict[str, Any]]:
    from travelmap import validation_reuse

    path = Path(source["path"])
    limit = None if source["kind"] == "osm" else MAX_VECTOR_BYTES
    component_paths = [path]
    if path.suffix.lower() == ".shp":
        component_paths.extend(path.with_suffix(suffix) for suffix in (".shx", ".dbf", ".prj"))
    config = {
        "source": source,
        "settings": {
            key: sorted(value) for key, value in settings.items() if key.endswith("_classes")
        },
        "version": PREPARATION_VERSION,
        "bounds": bounds,
    }
    config_sha256 = hashlib.sha256(
        json.dumps(config, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()
    source_id = validation_reuse.source_identifier(path)
    identities = validation_reuse.file_snapshot(component_paths)
    receipt_snapshot = (
        validation_reuse.receipt_snapshot(workspace_root) if workspace_root is not None else None
    )
    saved_hashes = (
        validation_reuse.source_result(workspace_root, source_id, config_sha256, component_paths)
        if workspace_root is not None and identities is not None and not force
        else None
    )
    if saved_hashes is not None:
        hashes = dict(zip((item.name for item in component_paths), saved_hashes, strict=True))
        report("Reusing successful source fingerprints from workspace metadata.")
    else:
        hashes = {
            component.name: digest(
                component,
                limit if component == path else MAX_VECTOR_BYTES,
                report,
            )
            for component in component_paths
        }
        after = validation_reuse.file_snapshot(component_paths)
        if identities is not None and after != identities:
            raise MapDataError(f"{path.name}: changed while it was being checked; retry.")
        if workspace_root is not None and identities is not None and receipt_snapshot is not None:
            validation_reuse.save_source_result(
                workspace_root,
                source_id,
                config_sha256,
                component_paths,
                list(hashes.values()),
                identities,
                expected_receipt=receipt_snapshot,
            )
    payload = {
        "version": PREPARATION_VERSION,
        "source": source,
        "hashes": hashes,
        "classes": {
            k: sorted(v)
            for k, v in settings.items()
            if k.endswith("_classes")
            and (
                source["kind"] == "osm"
                or k
                == {
                    "roads": "highway_classes",
                    "water_lines": "water_line_classes",
                    "water_areas": "water_area_classes",
                }.get(source["kind"])
            )
        },
    }
    if source["kind"] != "osm":
        payload["vector_identity_version"] = 3 if source["kind"] == "admin1" else 2
    identity = dict(
        payload,
        source={"kind": source["kind"], "layer": source.get("layer")},
        hashes=sorted(hashes.values()),
    )
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return key, payload


def cached(directory: Path, key: str, report: Callable[[str], None]) -> dict[str, Any] | None:
    manifest = directory / "manifest.json"
    if not manifest.exists() or directory.is_symlink():
        return None
    try:
        from travelmap import validation_reuse

        manifest_snapshot = validation_reuse.file_snapshot([manifest])
        if manifest_snapshot is None:
            return None
        result = read_json(manifest, MIB)
        if validation_reuse.file_snapshot([manifest]) != manifest_snapshot:
            return None
        if result.get("key") != key or not isinstance(result.get("layers"), dict):
            return None
        if result.get("schema_version") == 2:
            from travelmap import mapstore

            database = directory / "features.sqlite"
            database_sha256 = result.get("database_sha256")
            if (
                not isinstance(database_sha256, str)
                or len(database_sha256) != 64
                or any(char not in "0123456789abcdef" for char in database_sha256)
            ):
                return None
            repairs = result.get("geometry_repairs")
            if repairs:
                if not isinstance(repairs, dict) or not isinstance(repairs.get("objects"), list):
                    return None
                repair_hash = repairs.get("database_sha256")
                repair_count = repairs.get("count")
                if (
                    not isinstance(repair_hash, str)
                    or len(repair_hash) != 64
                    or any(char not in "0123456789abcdef" for char in repair_hash)
                    or not isinstance(repair_count, int)
                    or isinstance(repair_count, bool)
                    or not 0 < repair_count <= 512
                    or len(repairs["objects"]) != repair_count
                ):
                    return None
            original_database = directory / "repair-originals.sqlite" if repairs else None
            if validation_reuse.has_sidecars(database) or (
                original_database is not None and validation_reuse.has_sidecars(original_database)
            ):
                report_feedback(
                    report,
                    "A prepared SQLite store has journal sidecars. Stop other workspace users, "
                    "preserve the files and recover the store before retrying.",
                )
                return None
            # Repair originals have independent identities, manifest digests and counts.
            evidence = validation_reuse.store_result(
                database,
                manifest,
                original_database,
                database_sha256,
                repairs.get("database_sha256") if isinstance(repairs, dict) else None,
            )
            actual, repair_counts = evidence if evidence is not None else (None, None)
            reused = actual is not None
            receipt_snapshot = validation_reuse.receipt_snapshot(directory.parents[2])
            if not reused:
                database_identity = file_identity(database)
                if digest(database, mapstore.MAX_DB_BYTES, report) != database_sha256:
                    return None
                actual = validate_store(database, report)
                if file_identity(database) != database_identity:
                    return None
            assert actual is not None
            for kind, info in result["layers"].items():
                if (
                    kind not in mapstore.LAYERS
                    or info.get("count") != actual.get(kind, {"count": 0})["count"]
                ):
                    return None
            if set(actual) - set(result["layers"]):
                return None
            if repairs:
                count = repairs.get("count")
                assert isinstance(count, int)
                assert original_database is not None
                if reused:
                    if repair_counts != {"water_areas": {"count": count}}:
                        return None
                else:
                    original_identity = file_identity(original_database)
                    if digest(original_database, mapstore.MAX_DB_BYTES, report) != repairs.get(
                        "database_sha256"
                    ):
                        return None
                    repair_counts = validate_store(original_database, report)
                    if (
                        repair_counts != {"water_areas": {"count": count}}
                        or file_identity(original_database) != original_identity
                    ):
                        return None
            if validation_reuse.has_sidecars(database) or (
                original_database is not None and validation_reuse.has_sidecars(original_database)
            ):
                report_feedback(
                    report,
                    "A prepared SQLite store gained journal sidecars during validation. "
                    "Preserve the files, recover the store and retry.",
                )
                return None
            if reused:
                report("Reusing successful map integrity checks from workspace metadata.")
            if not reused and receipt_snapshot is not None:
                validation_reuse.save_store_result(
                    database,
                    manifest,
                    original_database,
                    actual,
                    database_sha256,
                    repair_counts,
                    repairs.get("database_sha256") if isinstance(repairs, dict) else None,
                    expected_receipt=receipt_snapshot,
                )
        else:
            for name, info in result["layers"].items():
                if (
                    name not in ("countries", "admin1", "roads", "water_lines", "water_areas")
                    or digest(directory / f"{name}.geojson", MAX_OUTPUT_BYTES, report)
                    != info["sha256"]
                ):
                    return None
        if validation_reuse.file_snapshot([manifest]) != manifest_snapshot:
            return None
        return result
    except (MapDataError, KeyError, TypeError, ValueError):
        return None


def run_worker(
    request: dict[str, Any], staging: Path, report: Callable[[str], None]
) -> dict[str, Any]:
    atomic_json(staging / "request.json", request)
    env = os.environ.copy()
    env.pop("OPENROUTESERVICE_API_KEY", None)
    env.update(
        PROJ_NETWORK="OFF",
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS="",
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
    )
    # Explicit package path also supports source-tree launches and temporary working folders.
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    process = subprocess.Popen(
        [sys.executable, "-m", "travelmap.mapdata_worker", str(staging)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        from travelmap.map_progress import monitor

        monitor(process, staging, lambda: read_json(staging / "progress.json", MIB), report)
        if process.returncode != 0:
            error = staging / "error.json"
            message = (
                read_json(error, MIB).get("error")
                if error.exists()
                else "Worker stopped (resource or reader failure)."
            )
            raise MapDataError(
                f"{message} Validated prior results are preserved; "
                "correct the stated cause and retry."
            )
        return read_json(staging / "manifest.json", MIB)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def display_check(
    root: Path,
    countries: list[dict[str, Any]],
    trip: dict[str, Any],
    resolved: dict[str, dict[str, Any]],
    settings: dict[str, Any],
    selection: dict[str, Any],
    report: Callable[[str], None] = lambda _: None,
    readiness_key: str | None = None,
) -> dict[str, Any]:
    """Supervise native display selection; keep complete source caches independent."""
    with tempfile.TemporaryDirectory(prefix=".view-", dir=plan_workspace(root).cache_dir) as temp:
        return run_worker(
            {
                "action": "view",
                "root": str(root),
                "countries": countries,
                "trip": trip,
                "resolved": resolved,
                "settings": settings,
                "selection": selection,
                "readiness_key": readiness_key,
            },
            Path(temp),
            report,
        )


def prepare_source(
    cache: Path,
    source: dict[str, Any],
    settings: dict[str, Any],
    bounds: list[float],
    report: Callable[[str], None],
) -> dict[str, Any]:
    path = Path(source["path"])
    workspace_root = cache.parents[2]
    key, provenance = source_fingerprint(source, settings, bounds, report, workspace_root)
    directory = cache / key
    record = cached(directory, key, report)
    if record is None:
        # Prefer already prepared supersets; membership is filtered after winner reduction.
        for candidate in sorted(cache.iterdir()):
            if (
                not candidate.is_dir()
                or candidate.is_symlink()
                or candidate.name.startswith((".", "combined-"))
            ):
                continue
            try:
                manifest = read_json(candidate / "manifest.json", MIB)
                prior = manifest.get("provenance", {})
                prior_source = prior.get("source", {})
                compatible = (
                    prior.get("version") == PREPARATION_VERSION
                    and prior.get("vector_identity_version")
                    == provenance.get("vector_identity_version")
                    and prior_source.get("kind") == source["kind"]
                    and prior_source.get("layer") == source.get("layer")
                    and sorted(prior.get("hashes", {}).values())
                    == sorted(provenance["hashes"].values())
                    and all(
                        set(values) <= set(prior.get("classes", {}).get(field, []))
                        for field, values in provenance["classes"].items()
                    )
                )
                if compatible:
                    record = cached(candidate, manifest["key"], report)
                    if record is not None:
                        directory = candidate
                        break
            except (ValueError, KeyError, OSError, TypeError):
                continue
    if record is not None:
        report(f"Reusing {path.name}: validated cached layers.")
    else:
        report(f"Rebuilding {path.name}: changed/missing source or preparation settings.")
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=cache) as temporary:
            staging = Path(temporary)
            request = {
                "key": key,
                "source": source,
                "provenance": provenance,
                "settings": settings,
                "extent": bounds,
            }
            record = run_worker(request, staging, report)
            # Recheck source identity before publishing a completed derived result.
            if source_fingerprint(source, settings, bounds, report, workspace_root)[0] != key:
                raise MapDataError(
                    f"{path.name}: changed during preparation. Recheck after copying finishes."
                )
            validated = cached(staging, key, report)
            if validated is None:
                raise MapDataError(f"{path.name}: prepared integrity check failed. Recheck.")
            if directory.exists():
                # Preserve an old corrupt cache for inspection; publish under a fresh directory.
                directory = cache / (key + "-" + uuid4().hex)
            os.replace(staging, directory)
        record = validated
    result = {**record, "directory": directory.name, "request_key": key}
    omitted = result.get("omitted_nested_water_relations")
    if (
        isinstance(omitted, dict)
        and type(omitted.get("count")) is int
        and omitted["count"] > 0
        and type(omitted.get("first_id")) is int
    ):
        report_feedback(
            report,
            f"{path.name}: skipped water polygons with nested relations "
            f"({omitted['count']:,} total, first osm:relation:{omitted['first_id']}).",
            ReportKind.WARNING,
        )
    if result.get("geometry_repairs"):
        report_feedback(
            report,
            f"{path.name}: {result['geometry_repairs']['count']:,} water repairs; "
            "originals retained in the source cache.",
            ReportKind.NOTICE,
        )
        for repair in result["geometry_repairs"]["objects"]:
            report_feedback(
                report,
                f"Repaired water polygon {repair['id']} in {path.name}: "
                f"{repair['original_vertices']:,} -> {repair['repaired_vertices']:,} vertices "
                f"({repair['result_type']}).",
                ReportKind.NOTICE,
            )
            if repair.get("noncontained_source_holes"):
                report_feedback(
                    report,
                    f"{repair['id']}: {repair['noncontained_source_holes']} source holes cross "
                    "or lie beyond their outer polygon; reported repair reinterprets invalid "
                    "topology. Original geometry is retained.",
                )
    result["provenance"] = {**provenance, "classes": record["provenance"]["classes"]}
    attribution = dict(record["attribution"])
    for field, target in (("attribution", "text"), ("licence", "licence")):
        if source.get(field) is not None:
            attribution[target] = source[field]
    if source["kind"] != "osm" and path.suffix.lower() != ".zip":
        attribution["source"] = path.name
    result["attribution"] = attribution
    return result


def validate_store(database: Path, report: Callable[[str], None]) -> dict[str, Any]:
    """Native cache decoding runs under the same supervision as preparation."""
    signature = file_identity(database)
    verified = _verification.get()
    existing = verified.get(str(database)) if verified is not None else None
    if existing is not None and existing.identity == signature:
        return existing.counts
    with tempfile.TemporaryDirectory(prefix=".validate-", dir=database.parent.parent) as temp:
        result = run_worker({"action": "validate", "database": str(database)}, Path(temp), report)
    if file_identity(database) != signature:
        raise MapDataError("Map cache changed during validation; retry.")
    if verified is not None:
        verified[str(database)] = VerifiedStore(signature, result["layers"])
    return dict(result["layers"])


def file_identity(path: Path) -> tuple[int, int, int, int, int]:
    stat_ = path.stat()
    return stat_.st_dev, stat_.st_ino, stat_.st_size, stat_.st_mtime_ns, stat_.st_ctime_ns


@dataclass(frozen=True)
class VerifiedStore:
    """Content validation handle shared only within one uninterrupted operation."""

    identity: tuple[int, int, int, int, int]
    counts: dict[str, Any]


_verification: ContextVar[dict[str, VerifiedStore] | None] = ContextVar(
    "map_verification", default=None
)
_hashes: ContextVar[
    dict[tuple[str, int | None], tuple[tuple[int, int, int, int, int], str]] | None
] = ContextVar("map_hashes", default=None)


@contextmanager
def verification_operation() -> Iterator[None]:
    """Do not carry verified handles over external waits or between operations."""
    token = _verification.set({})
    hash_token = _hashes.set({})
    try:
        yield
    finally:
        _verification.reset(token)
        _hashes.reset(hash_token)


def iter_layer(root: Path, selection: dict[str, Any], layer: str) -> Iterator[dict[str, Any]]:
    from travelmap import mapstore

    if layer not in mapstore.LAYERS:
        raise MapDataError("Unsupported map layer.")
    name = selection["directory"]
    if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
        raise MapDataError("Unsafe map cache directory.")
    folder = plan_workspace(root).cache_dir / "map-data" / name
    if folder.is_symlink():
        raise MapDataError("Map cache directory must not be a link.")
    if selection.get("schema_version") == 2:
        for feature in mapstore.features(folder / "features.sqlite", layer):
            if feature["properties"].get("geometry_state") == "invalid":
                raise MapDataError(
                    f"{feature['properties'].get('name', feature['id'])}: "
                    "invalid selected boundary geometry; recheck compatible map data."
                )
            yield feature
    else:
        yield from read_json(folder / f"{layer}.geojson")["features"]


def countries_from_records(cache: Path, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from travelmap import mapstore

    countries: list[dict[str, Any]] = []
    vertices = 0
    for record in records:
        if "countries" in record["layers"]:
            for feature in mapstore.features(
                cache / record["directory"] / "features.sqlite", "countries"
            ):
                vertices += feature["vertices"]
                if len(countries) >= 4096 or vertices > 2_000_000:
                    raise MapDataError(
                        "Country catalog exceeds 4,096 boundaries or two million vertices. "
                        "Select the supported Natural Earth country dataset."
                    )
                countries.append(feature)
    return countries


def country_identity(feature: dict[str, Any]) -> str:
    code = feature["properties"].get("code")
    return str(code) if code and code != "-99" else str(feature["id"])


def selected_countries(
    countries: list[dict[str, Any]],
    trip: dict[str, Any],
    ids: list[str],
    accepted_stop_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    from shapely.geometry import Point, shape

    from travelmap import geography

    catalog: dict[str, list[dict[str, Any]]] = {}
    for feature in countries:
        catalog.setdefault(country_identity(feature), []).append(feature)
    missing = set(ids) - set(catalog)
    if missing:
        raise MapDataError(
            "Unknown displayed countries: "
            + ", ".join(sorted(missing))
            + ". Correct country selection."
        )
    names = {}
    accepted_stop_ids = accepted_stop_ids or set()
    recommended = set()
    for stop in parts(trip, "stop"):
        point = Point(stop["geometry"]["coordinates"][:2])
        containing = []
        for feature in countries:
            if ids and country_identity(feature) not in ids:
                continue
            geometry = shape(feature["geometry"])
            if not geometry.bounds[1] <= point.y <= geometry.bounds[3]:
                continue
            if geography.covers(geometry, point):
                if feature["properties"].get("geometry_state") == "invalid":
                    raise MapDataError(
                        f"{feature['properties']['name']}: invalid country boundary; "
                        "select compatible data."
                    )
                if feature["properties"]["name"] not in containing:
                    containing.append(feature["properties"]["name"])
                recommended.add(country_identity(feature))
        names[stop["properties"]["id"]] = containing
        if not containing and stop["properties"]["id"] not in accepted_stop_ids:
            raise CountryCoverageError(stop["properties"]["id"], stop["properties"]["name"])
    chosen = set(ids) if ids else recommended
    for key in chosen:
        for feature in catalog[key]:
            if feature["properties"].get("geometry_state") == "invalid":
                raise MapDataError(
                    f"{feature['properties']['name']}: invalid selected country geometry; "
                    "select compatible data."
                )
    return [feature for key in sorted(chosen) for feature in catalog[key]], names


def reviewed_countries(
    root: Path,
    countries: list[dict[str, Any]],
    trip: dict[str, Any],
    ids: list[str],
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Apply only explicit mismatch decisions bound to verified country-source content."""
    from travelmap import boundary_review

    signature = boundary_review.signature(trip, records, ids)
    accepted = boundary_review.accepted(root, trip, signature)
    try:
        chosen, names = selected_countries(countries, trip, ids, accepted)
    except CountryCoverageError as exc:
        exc.review_signature = signature
        raise
    if not chosen:
        raise MapDataError(
            "Choose displayed countries explicitly: no accepted stop is covered by the "
            "supplied boundaries. Keep decisions do not choose a country automatically."
        )
    return chosen, names


def review_prepared_countries(
    root: Path,
    trip: dict[str, Any],
    selection: dict[str, Any],
    ids: list[str] | None = None,
) -> None:
    """Recheck mismatch decisions before readiness/export using validated source records."""
    if selection.get("schema_version") != 2:
        return  # Legacy fixture/cache validation remains owned by its existing path.
    effective_ids = settings_for(root)["country_ids"] if ids is None else ids
    cache = plan_workspace(root).cache_dir / "map-data"
    records = selection["sources"]
    countries = countries_from_records(cache, records)
    chosen, _ = reviewed_countries(root, countries, trip, effective_ids, records)
    if sorted({country_identity(feature) for feature in chosen}) != sorted(
        selection["country_ids"]
    ):
        raise MapDataError("Displayed countries changed in config.toml. Recheck map data.")


def _quick_file_identity(path: Path) -> list[int]:
    """Reject redirected paths before using filesystem metadata as a reuse hint."""
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise MapDataError("Redirected paths require full map validation.")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise MapDataError("Map reuse requires regular files.")
    return list(file_identity(path))


def _quick_inputs(root: Path, trip: dict[str, Any]) -> dict[str, Any]:
    settings = settings_for(root)
    sources = active_sources(discover(root, settings), settings)
    identities = {}
    for source in sources:
        path = Path(source["path"])
        files = [path]
        if path.suffix.lower() == ".shp":
            files.extend(path.with_suffix(suffix) for suffix in (".shx", ".dbf", ".prj"))
        for item in files:
            identities[str(item)] = _quick_file_identity(item)
    from travelmap import boundary_review, map_view, poster_settings, routes

    poster = poster_settings.load(root, trip)
    resolved, _ = routes.resolve(root, trip)
    view_inputs = {
        "rule_version": map_view.RULE_VERSION,
        "page": {
            key: value
            for key, value in poster["poster"].items()
            if key not in ("title", "subtitle")
        },
        "projection": poster["map"]["projection"],
        "framing": poster["map"]["framing"],
        "scale": poster["map"]["scale"],
        "padding_percent": poster["map"]["padding_percent"],
        "include_offshore_components": poster["map"]["include_offshore_components"],
        "routes": {key: record["coordinates"] for key, record in resolved.items()},
    }
    return {
        "display_sha256": hashlib.sha256(
            json.dumps(view_inputs, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        "preparation_version": PREPARATION_VERSION,
        "trip_sha256": hashlib.sha256(
            json.dumps(trip, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        "settings": settings,
        "sources": sources,
        "boundary_review": boundary_review.receipt_identity(root),
        "files": identities,
    }


def _quick_outputs(root: Path) -> dict[str, Any]:
    paths = plan_workspace(root)
    selection_path = paths.metadata_dir / "map-data.json"
    identity = _quick_file_identity(selection_path)
    selection = read_json(selection_path, MIB)
    if selection.get("schema_version") != 2:
        raise MapDataError("Older selections require full map validation.")
    sources = selection.get("sources")
    if (
        not isinstance(sources, list)
        or len(sources) > 32
        or any(not isinstance(source, dict) for source in sources)
    ):
        raise MapDataError("Invalid prepared source list.")
    directories = [selection.get("directory"), *(source.get("directory") for source in sources)]
    files = {str(selection_path): identity}
    for name in directories:
        if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
            raise MapDataError("Unsafe map cache directory.")
        directory = paths.cache_dir / "map-data" / name
        with os.scandir(directory) as entries:
            count = 0
            for entry in entries:
                count += 1
                if count > MAX_ENTRIES:
                    raise MapDataError("Map cache needs full validation.")
                path = Path(entry.path)
                files[str(path)] = _quick_file_identity(path)
        for required in ("manifest.json", "features.sqlite"):
            if str(directory / required) not in files:
                raise MapDataError("Map cache is incomplete.")
    return {"selection": selection, "files": files}


def preparation_unchanged(root: Path, trip: dict[str, Any]) -> bool:
    """Use a prior successful preparation's metadata hint; never certify file contents."""
    receipt = plan_workspace(root).metadata_dir / "map-reuse.json"
    if not receipt.exists():
        return False
    try:
        saved = read_json(receipt, 4 * MIB)
        return (
            saved.get("schema_version") == 1
            and saved.get("inputs") == _quick_inputs(root, trip)
            and saved.get("outputs") == _quick_outputs(root)
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def prepare(
    root: Path,
    trip: dict[str, Any],
    *,
    reduced_detail: bool,
    report: Callable[[str], None] = lambda _: None,
    bounds_override: list[float] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    receipt = plan_workspace(root).metadata_dir / "map-reuse.json"
    # Invalidate the hint before checking: an interrupted/failed recheck must not revive it.
    atomic_json(receipt, {"schema_version": 1})
    if force:
        from travelmap import validation_reuse

        # A full Step 3 recheck must also invalidate compatible superset caches, not
        # only the currently selected directory. Keep prior files/artwork intact.
        if not validation_reuse.revoke_export_scope(root, None, None):
            raise MapDataError(
                "Full recheck could not revoke prior successes; resolve the receipt lock and retry."
            )
    try:
        before = _quick_inputs(root, trip)
    except (OSError, ValueError):
        before = None
    with verification_operation():
        selection = _prepare(root, trip, reduced_detail=reduced_detail, report=report)
    if before is not None:
        try:
            after = _quick_inputs(root, trip)
            outputs = _quick_outputs(root)
        except (OSError, ValueError, KeyError, TypeError):
            pass  # Successful preparation remains usable even without a metadata shortcut.
        else:
            if before == after:
                atomic_json(receipt, {"schema_version": 1, "inputs": after, "outputs": outputs})
    return selection


def _prepare(
    root: Path, trip: dict[str, Any], *, reduced_detail: bool, report: Callable[[str], None]
) -> dict[str, Any]:
    paths = plan_workspace(root)
    settings = settings_for(root)
    sources = discover(root, settings)
    sources = active_sources(sources, settings)
    kinds = {s["kind"] for s in sources}
    if "countries" not in kinds:
        raise MapDataError(
            "Missing country boundaries: download Natural Earth Admin 0 Countries ZIP into "
            + str(paths.map_data_dir)
            + " and recheck."
        )
    if "osm" not in kinds and not set(settings["enabled_layers"]) <= kinds:
        raise MapDataError(
            "Missing roads/water: download country/regional .osm.pbf extracts "
            "or configure all three advanced layers."
        )
    if "admin1" not in kinds and not reduced_detail:
        raise MapDataError(
            "Optional state/province boundaries absent. "
            "Explicitly choose reduced detail to continue."
        )
    report("Preparing map layers for the selected countries from your local files.")
    report("The first run may take a while. Unchanged prepared data is reused when available.")
    cache = paths.cache_dir / "map-data"
    cache.mkdir(exist_ok=True)
    records = []
    chosen: list[dict[str, Any]] = []
    stop_countries: dict[str, Any] = {}
    countries_remaining = sum(source["kind"] == "countries" for source in sources)
    # Check the union of supplied boundaries before processing roads and water.
    for source in sorted(sources, key=lambda s: s["kind"] != "countries"):
        source_record = prepare_source(cache, source, settings, [-180, -90, 180, 90], report)
        records.append(source_record)
        if source["kind"] == "countries":
            countries_remaining -= 1
        if source["kind"] == "countries" and countries_remaining == 0:
            report("Checking country boundaries and stop coverage.")
            catalog = countries_from_records(cache, records)
            chosen, stop_countries = reviewed_countries(
                root, catalog, trip, settings["country_ids"], records
            )
    ids = sorted({country_identity(f) for f in chosen})
    key = hashlib.sha256(
        json.dumps(
            {
                "sources": sorted(r["key"] for r in records),
                "countries": ids,
                "enabled_layers": settings["enabled_layers"],
                "reduced": reduced_detail,
                "classes": {k: sorted(v) for k, v in settings.items() if k.endswith("_classes")},
                "attributions": [r["attribution"] for r in records],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    directory = cache / ("combined-" + key)
    record = cached(directory, key, report)
    if record is None:
        with tempfile.TemporaryDirectory(prefix=".combine-", dir=cache) as temp:
            staging = Path(temp)
            record = run_worker(
                {
                    "action": "combine",
                    "key": key,
                    "records": [
                        {**r, "database": str(cache / r["directory"] / "features.sqlite")}
                        for r in records
                    ],
                    "countries": chosen,
                    "settings": settings,
                },
                staging,
                report,
            )
            if directory.exists():
                directory = cache / ("combined-" + key + "-" + uuid4().hex)
            os.replace(staging, directory)
        report(
            "Combined neighboring extracts; entity winners resolved before geographic filtering."
        )
    else:
        report("Reusing combined prepared layers.")
    from shapely.geometry import Point, shape

    from travelmap import geography

    coverage = [bounds for r in records for bounds in r.get("coverage", [])]
    covered = geography.coverage_geometry(coverage)
    has_osm = any(r["provenance"]["source"]["kind"] == "osm" for r in records)
    if not has_osm and settings["enabled_layers"]:
        report(
            "Advanced vector feature bounds do not certify complete country coverage. "
            "All supplied detail is retained; review the full-country preview."
        )
    missing = []
    for stop in parts(trip, "stop"):
        if not geography.covered_by(covered, Point(stop["geometry"]["coordinates"][:2])):
            missing.append(
                stop["properties"]["name"] + ": outside available road/water source envelopes"
            )
    if missing and has_osm:
        raise MapDataError(
            "Coverage incomplete: "
            + "; ".join(missing)
            + ". Download covering extracts and recheck."
        )
    from travelmap import poster_settings, routes

    resolved, _ = routes.resolve(root, trip)
    # Only displayed components require coverage. The complete combined cache remains
    # independent of the trip and page; readiness/export recompute the transient view.
    display_coverage = {
        "coverage_check": "envelopes" if has_osm else "unknown",
        "coverage_envelopes": coverage,
        "enabled_layers": settings["enabled_layers"],
    }
    display = display_check(
        root, chosen, trip, resolved, poster_settings.load(root, trip), display_coverage, report
    )
    uncovered = display["coverage_errors"]
    if uncovered:
        raise MapDataError("; ".join(uncovered))
    report("Finalizing prepared map layers.")
    bounds = [
        min(shape(f["geometry"]).bounds[i] for f in chosen)
        if i < 2
        else max(shape(f["geometry"]).bounds[i] for f in chosen)
        for i in range(4)
    ]
    selection = {
        "schema_version": 2,
        "preparation_version": PREPARATION_VERSION,
        "directory": directory.name,
        "key": key,
        "database_sha256": record["database_sha256"],
        "layers": record["layers"],
        "sources": records,
        "extent": bounds,
        "country_ids": ids,
        "stop_countries": stop_countries,
        "coverage_envelopes": coverage,
        "country_coverage_warnings": uncovered,
        "coverage_check": "envelopes" if has_osm else "unknown",
        "enabled_layers": settings["enabled_layers"],
        "reduced_detail": reduced_detail,
        "coverage_limits": "Source envelopes do not certify complete road/water or route coverage.",
    }
    if len(json.dumps(selection, ensure_ascii=False, allow_nan=False).encode()) > MIB:
        raise MapDataError(
            "Country/source provenance exceeds the 1 MiB selection budget. "
            "Use fewer source artifacts or corrected data requiring fewer repairs; "
            "completed caches and the prior selection are preserved."
        )
    atomic_json(paths.metadata_dir / "map-data.json", selection)
    report_feedback(
        report,
        "Displayed whole countries: " + ", ".join(f["properties"]["name"] for f in chosen),
        ReportKind.RESULT,
    )
    for source_record in records:
        for layer, info in source_record["layers"].items():
            report_feedback(
                report,
                f"{layer}: {info['count']:,} prepared features from "
                f"{Path(source_record['provenance']['source']['path']).name}.",
                ReportKind.RESULT,
            )
    report_feedback(report, display["summary"], ReportKind.RESULT)
    report_feedback(
        report,
        "Map data prepared and selected; originals preserved. No routes or poster generated.",
        ReportKind.SUCCESS,
    )
    return selection


def inspect_prepared(
    root: Path, report: Callable[[str], None] = lambda _: None, *, force: bool = False
) -> dict[str, Any] | None:
    path = plan_workspace(root).metadata_dir / "map-data.json"
    if not path.exists():
        return None
    try:
        selection = read_json(path, MIB)
        if (
            selection.get("schema_version") not in (1, 2)
            or not isinstance(selection.get("sources"), list)
            or len(selection["sources"]) > 32
        ):
            return None
        name = selection["directory"]
        if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
            return None
        directory = plan_workspace(root).cache_dir / "map-data" / name
        if force:
            from travelmap import validation_reuse

            if not validation_reuse.revoke_store(directory / "features.sqlite"):
                report_feedback(
                    report,
                    "Full recheck could not revoke prior validation; resolve the receipt lock "
                    "and retry.",
                )
                return None
        record = cached(directory, selection["key"], report)
        if not record or selection.get("layers") != record.get("layers"):
            return None
        if selection.get("schema_version") == 2 and selection.get("database_sha256") != record.get(
            "database_sha256"
        ):
            return None
        if force and selection.get("schema_version") == 2:
            for source_record in selection["sources"]:
                source_directory = source_record.get("directory")
                source_key = source_record.get("key")
                if (
                    not isinstance(source_directory, str)
                    or Path(source_directory).name != source_directory
                    or not isinstance(source_key, str)
                ):
                    return None
                validated_source = cached(
                    plan_workspace(root).cache_dir / "map-data" / source_directory,
                    source_key,
                    report,
                )
                if (
                    validated_source is None
                    or validated_source.get("layers") != source_record.get("layers")
                    or validated_source.get("database_sha256")
                    != source_record.get("database_sha256")
                ):
                    return None
        return selection
    except (ValueError, KeyError, TypeError):
        return None


def recommend_regions(root: Path, trip: dict[str, Any], report: Callable[[str], None]) -> list[str]:
    settings = settings_for(root)
    sources = [s for s in discover(root, settings) if s["kind"] == "countries"]
    if not sources:
        return []
    cache = plan_workspace(root).cache_dir / "map-data"
    cache.mkdir(exist_ok=True)
    records = [
        prepare_source(cache, source, settings, [-180, -90, 180, 90], report) for source in sources
    ]
    report("Checking country boundaries and stop coverage.")
    _, names = reviewed_countries(
        root, countries_from_records(cache, records), trip, settings["country_ids"], records
    )
    return sorted({name for values in names.values() for name in values})
