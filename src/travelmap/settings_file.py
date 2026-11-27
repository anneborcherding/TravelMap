"""Readable TOML serialization and atomic, no-overwrite settings-file creation."""

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

_OPTIONAL_EXAMPLES = {
    "subtitle": '"{total_km} km • {total_days} days"',
    "title_case": '"uppercase"',
    "title_position": '"bottom"',
    "title_font_size_mm": "12",
    "subtitle_font_size_mm": "4",
    "title_subtitle_gap_mm": "10",
    "country_path": '"map-data/countries.gpkg"',
    "admin1_path": '"map-data/states.gpkg"',
    "country_codes": '["ARG", "CHL"]',
    "country_ids": '["ARG", "CHL"]',
    "country_layer": '"countries"',
    "admin1_layer": '"admin1"',
    "cache": '"manual-routes/routes.geojson"',
    "travel_days_override": "14",
    "color": '"#263238"',
}


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{ "
            + ", ".join(
                f"{json.dumps(str(key))} = {_value(item)}"
                for key, item in value.items()
                if item is not None
            )
            + " }"
        )
    raise ValueError("Unsupported settings-file value.")


def dumps(settings: dict[str, Any]) -> str:
    """Serialize validated settings, commenting examples for unset optional values."""
    lines = [
        "# TravelMap settings. Edit this file, save, then choose Reload config file.",
        "# poster.title is independent of the itinerary title.",
        "# Sizes are millimetres; distances are kilometres; colors use #RRGGBB.",
        '# Set style.route_colors to ["#A33F35", "#3F6F66"] to compare route colors.',
        "# Export saves one SVG per color. An empty list uses style.route.",
        "# Commented optional values are examples, not active settings.",
        "# Remove travel_days_override to calculate duration from itinerary dates.",
        "# country_ids/country_codes: omit or [] to select countries containing stops.",
        "# Use only one of country_ids and country_codes. Paths stay inside this workspace.",
        "# Never put API keys here; api_key_env is an environment-variable name only.",
    ]

    def section(raw: dict[str, Any], path: tuple[str, ...]) -> None:
        lines.extend(
            [
                "",
                "["
                + ".".join(
                    part if re.fullmatch(r"[A-Za-z0-9_-]+", part) else json.dumps(part)
                    for part in path
                )
                + "]",
            ]
        )
        for key, value in raw.items():
            if isinstance(value, dict):
                continue
            if value is None:
                example = _OPTIONAL_EXAMPLES.get(key, '"optional value"')
                lines.append(f"# {key} = {example}")
            else:
                lines.append(f"{key} = {_value(value)}")
        for key, value in raw.items():
            if isinstance(value, dict):
                section(value, (*path, str(key)))

    for key, value in settings.items():
        section(value, (key,))
    return "\n".join(lines) + "\n"


def publish_new(path: Path, content: str) -> bool:
    """Publish a complete UTF-8 file without replacing an existing file or symlink."""
    if path.is_symlink():
        raise ValueError(f"Settings file must not be a symlink: {path}")
    if path.exists():
        return False
    if len(content.encode("utf-8")) > 1024**2:
        raise ValueError("Settings file exceeds 1 MiB; reduce large text or source lists.")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".config-", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink():
                raise ValueError(f"Settings file must not be a symlink: {path}") from None
            return False
        return True
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
