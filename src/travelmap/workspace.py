"""Path planning and safe local setup for a reusable TravelMap workspace."""

import json
import os
import re
import stat
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WORKSPACE_MARKER_KIND = "travelmap-workspace"
WORKSPACE_LAYOUT_VERSION = 1
MAX_MARKER_BYTES = 64 * 1024
MAX_DIRECTORY_ENTRIES = 1_000
EXAMPLE_NAMES_PER_DIRECTORY = 5
MAX_RECENT_WORKSPACES = 5
MAX_RECENT_WORKSPACES_BYTES = 16 * 1024
INPUT_SUFFIXES = {
    "input": frozenset({".kml", ".geojson", ".json"}),
    "map-data": frozenset({".zip", ".osm.pbf", ".gpkg", ".shp"}),
    "manual-routes": frozenset({".geojson", ".json"}),
}
MANAGED_DIRECTORIES = ("input", "map-data", "manual-routes", "cache", "output", ".travelmap")


class WorkspaceError(ValueError):
    """Expected workspace path, marker, permission or filesystem failure."""


class WorkspacePathError(WorkspaceError):
    """The requested workspace root is invalid or not a directory."""


class WorkspaceConflictError(WorkspaceError):
    """A known workspace entry conflicts with the required layout."""


class WorkspaceMarkerError(WorkspaceError):
    """An existing workspace marker is unsupported, unsafe or unreadable."""


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """Known paths under one explicitly selected workspace root."""

    root: Path
    input_dir: Path
    map_data_dir: Path
    manual_routes_dir: Path
    cache_dir: Path
    output_dir: Path
    metadata_dir: Path
    manifest_file: Path


@dataclass(frozen=True, slots=True)
class WorkspaceInspection:
    """Read-only marker, layout and bounded candidate-file summary."""

    paths: WorkspacePaths
    root_exists: bool
    marker_status: str
    existing_directories: tuple[str, ...]
    missing_directories: tuple[str, ...]
    conflict: str | None
    candidate_counts: tuple[tuple[str, int], ...]
    candidate_examples: tuple[tuple[str, tuple[str, ...]], ...]
    scanned_entries: tuple[tuple[str, int], ...]
    truncated_directories: tuple[str, ...]
    unrelated_root_entries: tuple[str, ...]

    @property
    def is_ready(self) -> bool:
        """Whether the marker and all required managed directories are valid."""

        return (
            self.marker_status == "valid" and not self.missing_directories and self.conflict is None
        )


@dataclass(frozen=True, slots=True)
class WorkspaceSetupResult:
    """Reported effects of a completed or interrupted workspace setup."""

    paths: WorkspacePaths
    created_directories: tuple[str, ...]
    reused_directories: tuple[str, ...]
    marker_committed: bool
    config_migration: Path | None = None


def default_workspace_path(home: Path | None = None) -> Path:
    """Return the documented candidate workspace location."""

    return (home or Path.home()) / "TravelMap" / "trips" / "default"


def recent_workspaces_path() -> Path:
    """Return the per-user location used for the recent-workspace list."""

    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "TravelMap" / "recent-workspaces.json"
    if sys.platform == "darwin":
        return (
            Path.home() / "Library" / "Application Support" / "TravelMap" / "recent-workspaces.json"
        )
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "travelmap" / "recent-workspaces.json"


def load_recent_workspaces() -> list[Path]:
    """Read at most five valid absolute paths from the user-level history file."""

    path = recent_workspaces_path()
    try:
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > MAX_RECENT_WORKSPACES_BYTES
        ):
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != 1
        or not isinstance(raw.get("paths"), list)
    ):
        return []
    result: list[Path] = []
    seen: set[str] = set()
    for value in raw["paths"]:
        if not isinstance(value, str) or not Path(value).is_absolute():
            continue
        try:
            resolved = resolve_workspace_path(value)
        except WorkspacePathError:
            continue
        identity = os.path.normcase(str(resolved))
        if identity not in seen:
            seen.add(identity)
            result.append(resolved)
        if len(result) == MAX_RECENT_WORKSPACES:
            break
    return result


def remember_recent_workspace(root: Path) -> None:
    """Move a selected workspace to the front of the bounded per-user history."""

    try:
        selected = resolve_workspace_path(root)
        identity = os.path.normcase(str(selected))
        paths = [selected] + [
            path for path in load_recent_workspaces() if os.path.normcase(str(path)) != identity
        ]
        destination = recent_workspaces_path()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            return
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=".recent-workspaces-",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(
                    {
                        "schema_version": 1,
                        "paths": [str(path) for path in paths[:MAX_RECENT_WORKSPACES]],
                    },
                    stream,
                    ensure_ascii=True,
                    sort_keys=True,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except (OSError, WorkspaceError):
        # Recent-path storage is optional and must not interrupt workspace setup.
        return


def resolve_workspace_path(value: str | Path, *, cwd: Path | None = None) -> Path:
    """Resolve a literal user path, expanding only a leading home shorthand."""

    raw = str(value)
    if not raw.strip():
        raise WorkspacePathError("workspace path is empty; choose a folder path")
    if any(_is_forbidden_path_character(character) for character in raw):
        raise WorkspacePathError(
            "workspace path contains a control or invisible character; choose a printable path"
        )
    if os.name == "nt" and _has_invalid_windows_component(raw):
        raise WorkspacePathError(
            "workspace path contains a Windows-reserved name or character; choose another folder"
        )
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (cwd or Path.cwd()) / candidate
    try:
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        message = f"could not resolve workspace path: {inert_path(candidate)}"
        raise WorkspacePathError(message) from exc


def plan_workspace(root: Path) -> WorkspacePaths:
    """Construct the stable child paths without accessing the filesystem."""

    return WorkspacePaths(
        root=root,
        input_dir=root / "input",
        map_data_dir=root / "map-data",
        manual_routes_dir=root / "manual-routes",
        cache_dir=root / "cache",
        output_dir=root / "output",
        metadata_dir=root / ".travelmap",
        manifest_file=root / ".travelmap" / "workspace.json",
    )


def inspect_workspace(root: Path) -> WorkspaceInspection:
    """Inspect a workspace without creating paths or following managed child links."""

    canonical_root = _existing_root(root)
    paths = plan_workspace(canonical_root)
    root_exists = canonical_root.exists()
    existing: list[str] = []
    missing: list[str] = []
    conflict: str | None = None
    for name in MANAGED_DIRECTORIES:
        child = canonical_root / name
        try:
            info = child.lstat()
        except FileNotFoundError:
            missing.append(name)
            continue
        except OSError as exc:
            conflict = f"cannot inspect {inert_path(child)}: {inert_text(str(exc))}"
            break
        if not stat.S_ISDIR(info.st_mode) or _is_reparse(info):
            conflict = f"{inert_path(child)} exists but is not a safe workspace folder"
            break
        existing.append(name)

    marker_status = "missing"
    if conflict is None and ".travelmap" in existing:
        marker_status = _read_marker(paths.manifest_file)

    candidate_counts: dict[str, int] = {}
    candidate_examples: dict[str, tuple[str, ...]] = {}
    scanned_entries: dict[str, int] = {}
    truncated: list[str] = []
    for directory_name in ("input", "map-data", "manual-routes", "cache", "output"):
        directory = canonical_root / directory_name
        if directory_name not in existing:
            continue
        suffixes = INPUT_SUFFIXES.get(directory_name, frozenset())
        try:
            with os.scandir(directory) as entries:
                batch: list[os.DirEntry[str]] = []
                for entry in entries:
                    if len(batch) > MAX_DIRECTORY_ENTRIES:
                        break
                    batch.append(entry)
        except OSError as exc:
            if conflict is None:
                conflict = f"cannot inspect {inert_path(directory)}: {inert_text(str(exc))}"
            continue
        was_truncated = len(batch) > MAX_DIRECTORY_ENTRIES
        checked = batch[:MAX_DIRECTORY_ENTRIES]
        names = sorted(entry.name for entry in checked)
        matches = [name for name in names if _has_supported_suffix(name, suffixes)]
        scanned_entries[directory_name] = len(checked)
        candidate_counts[directory_name] = len(matches)
        candidate_examples[directory_name] = tuple(matches[:EXAMPLE_NAMES_PER_DIRECTORY])
        if was_truncated:
            truncated.append(directory_name)

    managed = set(MANAGED_DIRECTORIES)
    unrelated: tuple[str, ...] = ()
    if root_exists:
        try:
            with os.scandir(canonical_root) as entries:
                sampled: list[str] = []
                for entry in entries:
                    if len(sampled) > MAX_DIRECTORY_ENTRIES:
                        break
                    if entry.name not in managed:
                        sampled.append(entry.name)
                unrelated = tuple(
                    sorted(sampled[:MAX_DIRECTORY_ENTRIES])[:EXAMPLE_NAMES_PER_DIRECTORY]
                )
        except OSError as exc:
            if conflict is None:
                conflict = f"cannot inspect {inert_path(canonical_root)}: {inert_text(str(exc))}"
    return WorkspaceInspection(
        paths=paths,
        root_exists=root_exists,
        marker_status=marker_status,
        existing_directories=tuple(existing),
        missing_directories=tuple(missing),
        conflict=conflict,
        candidate_counts=tuple(sorted(candidate_counts.items())),
        candidate_examples=tuple(sorted(candidate_examples.items())),
        scanned_entries=tuple(sorted(scanned_entries.items())),
        truncated_directories=tuple(truncated),
        unrelated_root_entries=unrelated,
    )


def ensure_workspace(root: Path, *, adopt_existing: bool = False) -> WorkspaceSetupResult:
    """Create missing known paths and publish a marker without overwriting user data."""

    paths = plan_workspace(_existing_root(root))
    try:
        paths.root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WorkspacePathError(
            f"cannot create workspace {inert_path(paths.root)}: {inert_text(str(exc))}"
        ) from exc
    _require_directory(paths.root, "workspace root")
    before = inspect_workspace(paths.root)
    if before.conflict is not None:
        raise WorkspaceConflictError(before.conflict)
    if before.marker_status == "invalid":
        raise WorkspaceMarkerError(
            "workspace marker is not a supported TravelMap layout: "
            f"{inert_path(paths.manifest_file)}"
        )
    has_content = (
        bool(before.existing_directories)
        or bool(before.unrelated_root_entries)
        or any(count > 0 for _, count in before.candidate_counts)
    )
    if before.marker_status == "missing" and has_content and not adopt_existing:
        raise WorkspaceConflictError(
            "workspace contains unrelated files; inspect it and explicitly choose adopt existing "
            f"before adding TravelMap folders: {inert_path(paths.root)}"
        )

    created: list[str] = []
    reused: list[str] = []
    for name in MANAGED_DIRECTORIES:
        directory = paths.root / name
        if _safe_existing_directory(directory):
            reused.append(name)
            continue
        try:
            directory.mkdir()
        except FileExistsError:
            _require_directory(directory, name)
            reused.append(name)
        except OSError as exc:
            raise WorkspaceError(
                f"cannot create {name} folder at {inert_path(directory)}: {inert_text(str(exc))}"
            ) from exc
        else:
            created.append(name)
        _require_directory(directory, name)
        _check_write_capability(directory)

    marker_status = _read_marker(paths.manifest_file)
    committed = marker_status != "valid"
    if committed:
        try:
            _publish_marker(paths.manifest_file)
        except FileExistsError:
            if _read_marker(paths.manifest_file) != "valid":
                raise WorkspaceConflictError(
                    f"a conflicting workspace marker appeared at {inert_path(paths.manifest_file)}"
                ) from None
        except OSError as exc:
            raise WorkspaceError(
                "could not safely publish the workspace marker; this filesystem may not support "
                "no-overwrite links. Choose a supported local NTFS, APFS or ext4 folder, or retry "
                f"after repair. Details: {inert_text(str(exc))}"
            ) from exc
        committed = _read_marker(paths.manifest_file) == "valid"
        if not committed:
            raise WorkspaceMarkerError("workspace marker was not complete after publication")
    from travelmap import poster_settings

    try:
        migration = poster_settings.ensure_file(paths.root)
    except (ValueError, OSError) as exc:
        raise WorkspaceError(f"Could not prepare config.toml: {inert_text(str(exc))}") from exc
    return WorkspaceSetupResult(
        paths=paths,
        created_directories=tuple(created),
        reused_directories=tuple(reused),
        marker_committed=committed,
        config_migration=migration,
    )


def inert_text(value: str) -> str:
    """Return foreign filesystem/error text without terminal controls or bidi overrides."""

    pieces: list[str] = []
    for character in value:
        if _is_forbidden_path_character(character):
            pieces.append(f"\\u{ord(character):04x}")
        else:
            pieces.append(character)
    return "".join(pieces)


def inert_path(path: Path) -> str:
    """Format a filesystem path as inert text."""

    return inert_text(str(path))


def _existing_root(root: Path) -> Path:
    try:
        return root.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise WorkspacePathError(f"could not resolve workspace path: {inert_path(root)}") from exc


def _read_marker(path: Path) -> str:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        message = f"cannot inspect workspace marker: {inert_text(str(exc))}"
        raise WorkspaceMarkerError(message) from exc
    if not stat.S_ISREG(info.st_mode) or _is_reparse(info):
        raise WorkspaceMarkerError("workspace marker must be a regular file")
    try:
        with path.open("rb") as marker:
            raw = marker.read(MAX_MARKER_BYTES + 1)
    except OSError as exc:
        raise WorkspaceMarkerError(f"cannot read workspace marker: {inert_text(str(exc))}") from exc
    if len(raw) > MAX_MARKER_BYTES:
        raise WorkspaceMarkerError("workspace marker exceeds the 64 KiB size limit")
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateMarkerKey, RecursionError) as exc:
        raise WorkspaceMarkerError("workspace marker is not valid UTF-8 JSON") from exc
    if not isinstance(decoded, dict):
        return "invalid"
    if (
        type(decoded.get("schema_version")) is not int
        or decoded.get("schema_version") != 1
        or decoded.get("kind") != WORKSPACE_MARKER_KIND
        or type(decoded.get("layout_version")) is not int
        or decoded.get("layout_version") != WORKSPACE_LAYOUT_VERSION
    ):
        return "invalid"
    return "valid"


class DuplicateMarkerKey(ValueError):
    """Internal signal used to reject duplicate keys in workspace JSON."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateMarkerKey(key)
        value[key] = item
    return value


def _publish_marker(marker_path: Path) -> None:
    content = (
        json.dumps(
            {
                "schema_version": 1,
                "kind": WORKSPACE_MARKER_KIND,
                "layout_version": WORKSPACE_LAYOUT_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".workspace-", suffix=".tmp", dir=marker_path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as marker:
            marker.write(content)
            marker.flush()
            os.fsync(marker.fileno())
        os.link(temporary, marker_path, follow_symlinks=False)
        temporary.unlink()
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _safe_existing_directory(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise WorkspaceError(f"cannot inspect {inert_path(path)}: {inert_text(str(exc))}") from exc
    if not stat.S_ISDIR(info.st_mode) or _is_reparse(info):
        raise WorkspaceConflictError(f"workspace entry is not a safe folder: {inert_path(path)}")
    return True


def _require_directory(path: Path, label: str) -> None:
    if not _safe_existing_directory(path):
        raise WorkspaceConflictError(f"workspace folder is missing: {inert_text(label)}")


def _check_write_capability(directory: Path) -> None:
    probe_path: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=".travelmap-write-check-", dir=directory)
        probe_path = Path(name)
        os.close(descriptor)
    except OSError as exc:
        raise WorkspaceError(
            f"cannot write workspace folder {inert_path(directory)}: {inert_text(str(exc))}"
        ) from exc
    finally:
        if probe_path is not None:
            try:
                probe_path.unlink()
            except OSError as exc:
                raise WorkspaceError(
                    f"cannot remove owned workspace check {inert_path(probe_path)}: "
                    f"{inert_text(str(exc))}"
                ) from exc


def _is_reparse(info: os.stat_result) -> bool:
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & reparse_attribute)


def _has_supported_suffix(filename: str, suffixes: frozenset[str]) -> bool:
    lowered = filename.lower()
    return any(lowered.endswith(suffix) for suffix in suffixes)


def _is_forbidden_path_character(character: str) -> bool:
    return unicodedata.category(character) in {"Cc", "Cf", "Cs", "Co", "Cn"}


def _has_invalid_windows_component(value: str) -> bool:
    """Reject common Win32-invalid characters, trailing dots/spaces and device names."""

    _, tail = os.path.splitdrive(value)
    if any(character in '<>:"|?*' for character in tail):
        return True
    reserved = re.compile(r"(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$")
    components = re.split(r"[\\/]", tail)
    return any(
        component.endswith((".", " ")) or bool(reserved.fullmatch(component))
        for component in components
        if component
    )
