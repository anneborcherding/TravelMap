"""Typed poster configuration and TOML loading."""

import re
import tomllib
from math import isfinite
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from travelmap.itinerary import TransportMode


class ConfigValidationError(ValueError):
    """Raised when a poster configuration cannot be read or validated."""


class PosterSettings(BaseModel):
    """Physical poster settings in millimetres."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str
    subtitle: str | None = None
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    margin_mm: float = Field(default=0, ge=0)
    orientation: Literal["portrait", "landscape"] = "portrait"
    design: Literal["standard", "reference"] = "standard"
    title_case: Literal["preserve", "uppercase"] | None = None
    title_position: Literal["top", "bottom"] | None = None


class BoundarySettings(BaseModel):
    """Optional local Natural Earth boundary sources."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    country_path: Path | None = None
    country_codes: tuple[str, ...] | None = None
    country_ids: tuple[str, ...] | None = None
    admin1_path: Path | None = None
    country_layer: str | None = None
    admin1_layer: str | None = None


class RoutingSettings(BaseModel):
    """Route acquisition and local-cache rendering behavior."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    enabled: bool = False
    api_key_env: str = "OPENROUTESERVICE_API_KEY"
    profiles: dict[str, str] = Field(
        default_factory=lambda: {
            "bus": "driving-car",
            "car": "driving-car",
            "walk": "foot-walking",
        }
    )
    cache: Path | None = None
    modes: tuple[TransportMode, ...] = (
        TransportMode.BUS,
        TransportMode.CAR,
        TransportMode.TRAIN,
        TransportMode.WALK,
    )
    unreachable: Literal["error", "direct"] = "error"
    preference: Literal["fastest", "shortest", "recommended"] = "recommended"
    avoid_features: tuple[str, ...] = ()
    request_delay_s: float = Field(default=2.0, ge=0)
    merge_nearby_routes: bool = False
    nearby_route_merge_tolerance_mm: float = Field(default=0.1, gt=0)

    @field_validator("api_key_env")
    @classmethod
    def validate_api_key_env(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("api_key_env must be a valid environment variable name")
        return value

    @field_validator("modes")
    @classmethod
    def validate_modes(cls, value: tuple[TransportMode, ...]) -> tuple[TransportMode, ...]:
        if len(value) != len(set(value)):
            raise ValueError("routing modes must be unique")
        return value

    @field_validator("avoid_features")
    @classmethod
    def validate_avoid_features(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        allowed = {"highways", "tollways", "ferries", "fords", "steps"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unsupported routing avoid features: {', '.join(unknown)}")
        if len(value) != len(set(value)):
            raise ValueError("routing avoid features must be unique")
        return value


class RoadSettings(BaseModel):
    """Local OpenStreetMap road layer settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    enabled: bool = False
    paths: tuple[Path, ...] = ()
    layer: str = "lines"
    highway_classes: tuple[str, ...] = (
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
    )


class WaterSettings(BaseModel):
    """Local OpenStreetMap water layer settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    enabled: bool = False
    paths: tuple[Path, ...] = ()
    line_layer: str = "water_lines"
    area_layer: str = "water_areas"
    line_classes: tuple[str, ...] = ("river", "canal")
    area_classes: tuple[str, ...] = ("water", "lake", "reservoir", "river", "pond", "basin")
    min_area_km2: float = Field(default=1, ge=0, le=1_000_000)
    simplify_geometry: bool = True
    simplify_tolerance_mm: float = Field(default=0.1, gt=0, le=1)


class DistanceSettings(BaseModel):
    """Manual distances that supplement route-cache distances in poster subtitles."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    segment_overrides_km: dict[int, float] = Field(default_factory=dict)
    travel_days_override: int | None = Field(default=None, gt=0, strict=True)

    @field_validator("segment_overrides_km")
    @classmethod
    def validate_segment_overrides(cls, value: dict[int, float]) -> dict[int, float]:
        """Require positive, finite distances for positive segment sequence numbers."""

        for sequence, distance_km in value.items():
            if sequence <= 0:
                raise ValueError("distance override segment sequences must be positive")
            if not isfinite(distance_km) or distance_km <= 0:
                raise ValueError("distance overrides must be positive finite kilometres")
        return value


class ScaleSettings(BaseModel):
    """Optional physical scale bar drawn in the map viewport or poster footer."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    enabled: bool = False
    distance_km: float = Field(default=100, gt=0)
    segments: int = Field(default=4, ge=1)
    position: Literal["bottom-left", "bottom-right", "top-left", "top-right", "footer-center"] = (
        "bottom-left"
    )
    inset_mm: float = Field(default=8, ge=0)
    height_mm: float = Field(default=3, gt=0)
    caption: str = "SCALE • APPROXIMATE"
    color: str | None = None
    number_position: Literal["top", "bottom"] = "bottom"

    @field_validator("color")
    @classmethod
    def validate_optional_color(cls, value: str | None) -> str | None:
        """Validate an optional color overriding all scale foreground elements."""

        if value is not None and not _HEX_COLOR.fullmatch(value):
            raise ValueError("must be a six-digit hexadecimal color")
        return value


class VectorSourceSettings(BaseModel):
    """Additional local map sources, including migrated source attribution."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["countries", "admin1", "roads", "water_lines", "water_areas"]
    path: Path
    layer: str | None = None
    attribution: str | None = Field(default=None, max_length=4096)
    licence: str | None = Field(default=None, max_length=4096)


class MapSettings(BaseModel):
    """Projection and map-layer settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    projection: str
    framing: Literal["countries", "stops"] = "countries"
    fill_land: bool = Field(default=True, strict=True)
    include_offshore_components: bool = Field(default=False, strict=True)
    padding_percent: float = Field(default=0, ge=0, le=100)
    show_state_borders: bool = Field(default=False, strict=True)
    sources: tuple[VectorSourceSettings, ...] = Field(default=(), max_length=16)
    show_country_borders: bool = True
    show_stop_markers: bool = True
    show_place_labels: bool = True
    boundaries: BoundarySettings = Field(default_factory=BoundarySettings)
    routing: RoutingSettings = Field(default_factory=RoutingSettings)
    roads: RoadSettings = Field(default_factory=RoadSettings)
    water: WaterSettings = Field(default_factory=WaterSettings)
    distance: DistanceSettings = Field(default_factory=DistanceSettings)
    scale: ScaleSettings = Field(default_factory=ScaleSettings)


_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class StyleSettings(BaseModel):
    """Colors and physical stroke sizes for the initial renderer."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    background: str
    land: str
    road: str = "#C8C8C8"
    road_width_mm: float = Field(default=0.15, gt=0)
    road_opacity: float = Field(default=0.7, ge=0, le=1)
    water_line: str = "#747A77"
    water_area: str = "#D4D5CF"
    water_width_mm: float = Field(default=0.2, gt=0)
    water_line_opacity: float = Field(default=0.45, ge=0, le=1)
    water_area_opacity: float = Field(default=1.0, ge=0, le=1)
    border: str
    route: str
    route_colors: tuple[str, ...] = ()
    stop: str
    label: str
    route_width_mm: float = Field(gt=0)
    stop_radius_mm: float = Field(gt=0)
    route_opacity: float = Field(default=1, ge=0, le=1)
    font_family: str
    title_font_family: str
    title_font_size_mm: float | None = Field(default=None, gt=0, le=50, strict=True)
    subtitle_font_size_mm: float | None = Field(default=None, gt=0, le=50, strict=True)
    title_subtitle_gap_mm: float | None = Field(default=None, gt=0, le=50, strict=True)
    boundary_width_mm: float = Field(default=0.15, gt=0)
    route_dash_patterns: dict[str, str] = Field(default_factory=dict)
    route_colors_by_mode: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "background", "land", "road", "water_line", "water_area", "border", "route", "stop", "label"
    )
    @classmethod
    def validate_color(cls, value: str) -> str:
        if not _HEX_COLOR.fullmatch(value):
            raise ValueError("must be a six-digit hexadecimal color")
        return value

    @field_validator("route_colors")
    @classmethod
    def validate_route_colors(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Validate optional, distinct route colors used for SVG variants."""

        if len(value) != len(set(value)):
            raise ValueError("route_colors must be unique")
        for color in value:
            if not _HEX_COLOR.fullmatch(color):
                raise ValueError("route_colors entries must be six-digit hexadecimal colors")
        return value

    @field_validator("route_colors_by_mode")
    @classmethod
    def validate_route_colors_by_mode(cls, value: dict[str, str]) -> dict[str, str]:
        """Validate optional route colors keyed by transport mode."""

        for mode, color in value.items():
            if not mode.strip():
                raise ValueError("route_colors_by_mode keys must not be empty")
            if not _HEX_COLOR.fullmatch(color):
                raise ValueError("route_colors_by_mode values must be six-digit hexadecimal colors")
        return value


class OutputSettings(BaseModel):
    """Settings for poster export."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    incomplete_distance: Literal["omit", "subtotal"] = "omit"


class PosterConfig(BaseModel):
    """Complete validated poster configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    poster: PosterSettings
    map: MapSettings
    style: StyleSettings
    output: OutputSettings


def load_config(path: Path, defaults: dict[str, Any] | None = None) -> PosterConfig:
    """Load and validate a UTF-8 TOML poster configuration."""

    try:
        with path.open("rb") as config_file:
            raw = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigValidationError(f"could not load configuration {path}: {exc}") from exc
    return parse_config(raw, path.parent, defaults=defaults, source=str(path))


def parse_config(
    raw: dict[str, Any],
    base_path: Path,
    *,
    defaults: dict[str, Any] | None = None,
    source: str = "configuration",
) -> PosterConfig:
    """Validate TOML values, filling omitted keys from defaults and resolving paths."""

    if defaults is not None:
        raw = _merge(defaults, raw)
    try:
        config = PosterConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigValidationError(f"invalid configuration {source}: {exc}") from exc
    return _resolve_paths(config, base_path)


def _merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Merge nested configuration sections while preserving strict unknown-key checks."""

    result = {
        key: value.copy() if isinstance(value, dict) else value for key, value in base.items()
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_paths(config: PosterConfig, base_path: Path) -> PosterConfig:
    """Resolve configured filesystem paths relative to the configuration file."""

    boundaries = config.map.boundaries
    resolved_boundaries = boundaries.model_copy(
        update={
            "country_path": _resolve_path(boundaries.country_path, base_path),
            "admin1_path": _resolve_path(boundaries.admin1_path, base_path),
        }
    )
    routing = config.map.routing
    resolved_routing = routing.model_copy(update={"cache": _resolve_path(routing.cache, base_path)})
    roads = config.map.roads
    resolved_roads = roads.model_copy(update={"paths": _resolve_path_tuple(roads.paths, base_path)})
    water = config.map.water
    resolved_water = water.model_copy(update={"paths": _resolve_path_tuple(water.paths, base_path)})
    resolved_map = config.map.model_copy(
        update={
            "sources": tuple(
                source.model_copy(update={"path": _resolve_path(source.path, base_path)})
                for source in config.map.sources
            ),
            "boundaries": resolved_boundaries,
            "routing": resolved_routing,
            "roads": resolved_roads,
            "water": resolved_water,
        }
    )
    return config.model_copy(update={"map": resolved_map})


def _resolve_path(path: Path | None, base_path: Path) -> Path | None:
    """Resolve one optional path without requiring the target to exist."""

    if path is None or path.is_absolute():
        return path
    return (base_path / path).resolve()


def _resolve_path_tuple(paths: tuple[Path, ...], base_path: Path) -> tuple[Path, ...]:
    """Resolve a collection of paths relative to a configuration directory."""

    return tuple(path if path.is_absolute() else (base_path / path).resolve() for path in paths)
