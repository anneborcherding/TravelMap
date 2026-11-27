"""Input-bound acceptance of stops outside supplied country boundaries."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from travelmap import itinerary
from travelmap.workspace import plan_workspace

_VERSION = 1
_HASH = re.compile(r"[0-9a-f]{64}")
_MAX_RECEIPT_BYTES = 256 * 1024


def signature(trip: dict[str, Any], records: list[dict[str, Any]], ids: list[str]) -> str:
    """Bind a review to accepted trip content, validated boundary content and selection."""
    itinerary.validate(trip)
    sources = sorted(
        (record["key"], record.get("database_sha256"))
        for record in records
        if "countries" in record["layers"]
    )
    payload = [_VERSION, trip, sources, sorted(set(ids))]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def accepted(root: Path, trip: dict[str, Any], current_signature: str) -> set[str]:
    """Read a bounded validated receipt; a changed context has no accepted mismatches."""
    from travelmap.mapdata import MapDataError, read_json

    path = plan_workspace(root).metadata_dir / "boundary-review.json"
    if not path.exists():
        return set()
    raw = read_json(path, _MAX_RECEIPT_BYTES)
    values = raw.get("stop_ids")
    digest = raw.get("signature")
    known = {stop["properties"]["id"] for stop in itinerary.parts(trip, "stop")}
    if (
        set(raw) != {"schema_version", "signature", "stop_ids"}
        or type(raw.get("schema_version")) is not int
        or raw["schema_version"] != _VERSION
        or not isinstance(digest, str)
        or _HASH.fullmatch(digest) is None
        or not isinstance(values, list)
        or len(values) > itinerary.MAX_FEATURES
        or any(not isinstance(value, str) or len(value) > 1000 for value in values)
        or len(set(values)) != len(values)
    ):
        raise MapDataError("Invalid boundary review. Remove boundary-review.json and review again.")
    # Unknown IDs from a previous valid itinerary are stale context, not a bypass.
    if digest != current_signature:
        return set()
    if not set(values) <= known:
        raise MapDataError("Boundary review refers to unknown stops. Review the itinerary again.")
    return set(values)


def accept(root: Path, trip: dict[str, Any], current_signature: str, stop_id: str) -> None:
    """Persist only an explicit keep decision for a known stop in the current context."""
    from travelmap.mapdata import MapDataError, atomic_json

    if (
        _HASH.fullmatch(current_signature) is None
        or not isinstance(stop_id, str)
        or len(stop_id) > 1000
        or stop_id not in {stop["properties"]["id"] for stop in itinerary.parts(trip, "stop")}
    ):
        raise MapDataError("Boundary review no longer matches this itinerary; recheck map data.")
    values = accepted(root, trip, current_signature) | {stop_id}
    payload = {
        "schema_version": _VERSION,
        "signature": current_signature,
        "stop_ids": sorted(values),
    }
    if len(json.dumps(payload, ensure_ascii=False).encode()) > _MAX_RECEIPT_BYTES:
        raise MapDataError("Boundary review exceeds 256 KiB. Use shorter stop identifiers.")
    atomic_json(
        plan_workspace(root).metadata_dir / "boundary-review.json",
        payload,
    )


def receipt_identity(root: Path) -> dict[str, Any] | None:
    """Include receipt contents in reuse hints so removal or edits cannot bypass review."""
    from travelmap.mapdata import read_json

    path = plan_workspace(root).metadata_dir / "boundary-review.json"
    return read_json(path, _MAX_RECEIPT_BYTES) if path.exists() else None
