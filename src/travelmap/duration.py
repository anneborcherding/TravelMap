"""Shared duration assessment without inventing dates or changing itinerary data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from travelmap import itinerary


@dataclass(frozen=True)
class DurationAssessment:
    """Inclusive duration and stop IDs requiring review; names remain presentation data."""

    days: int | None
    source: Literal["dates", "override", "unavailable"]
    missing_ids: tuple[str, ...]
    invalid_ids: tuple[str, ...]
    order_ids: tuple[str, ...]


def assess(trip: dict[str, Any], override: int | None = None) -> DurationAssessment:
    """Require complete ordered dates unless the user explicitly overrides trip length."""
    if override is not None and (type(override) is not int or override <= 0):
        raise ValueError("Trip duration must be a positive whole number of days.")
    missing, invalid, order = [], [], []
    dates = []
    previous = None
    stops = itinerary.parts(trip, "stop")
    for stop in stops:
        properties = stop["properties"]
        identifier = str(properties["id"])
        raw = properties.get("arrival_date")
        if raw is None or raw == "":
            missing.append(identifier)
            continue
        try:
            if not isinstance(raw, str):
                raise ValueError("Invalid date")
            value = date.fromisoformat(raw)
        except ValueError:
            invalid.append(identifier)
            continue
        if previous is not None and value < previous:
            order.append(identifier)
        dates.append(value)
        previous = value
    days = None
    source: Literal["dates", "override", "unavailable"] = "unavailable"
    if override is not None:
        days, source = override, "override"
    elif dates and not (missing or invalid or order):
        days, source = (dates[-1] - dates[0]).days + 1, "dates"
    return DurationAssessment(days, source, tuple(missing), tuple(invalid), tuple(order))


def warnings(trip: dict[str, Any], assessment: DurationAssessment) -> list[str]:
    """Describe issues by stop name for inert terminal output, never SVG metadata."""
    names = {
        str(s["properties"]["id"]): str(s["properties"]["name"])
        for s in itinerary.parts(trip, "stop")
    }
    result = []
    for identifiers, label in (
        (assessment.missing_ids, "Missing arrival dates"),
        (assessment.invalid_ids, "Invalid arrival dates"),
        (assessment.order_ids, "Arrival dates earlier than the preceding dated stop"),
    ):
        if identifiers:
            result.append(label + ": " + ", ".join(names[i] for i in identifiers) + ".")
    if assessment.source == "unavailable":
        result.append(
            "Trip duration unavailable. Update stop dates in Your itinerary or set "
            "map.distance.travel_days_override in config.toml; "
            "Accept and continue keeps duration unavailable."
        )
    return result


def review_stop_ids(trip: dict[str, Any], assessment: DurationAssessment) -> tuple[str, ...]:
    """Return date-issue stops with one itinerary neighbor on either side.

    With no date issues, retain all stops so users can still edit valid dates.
    """
    stops = itinerary.parts(trip, "stop")
    issue_ids = set(assessment.missing_ids + assessment.invalid_ids + assessment.order_ids)
    if not issue_ids:
        return tuple(str(stop["properties"]["id"]) for stop in stops)
    issue_indices = {
        index for index, stop in enumerate(stops) if str(stop["properties"]["id"]) in issue_ids
    }
    visible_indices = {
        neighbor
        for index in issue_indices
        for neighbor in range(max(0, index - 1), min(len(stops), index + 2))
    }
    return tuple(
        str(stop["properties"]["id"])
        for index, stop in enumerate(stops)
        if index in visible_indices
    )
