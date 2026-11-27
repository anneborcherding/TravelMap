# Edit your poster settings

On the first run, TravelMap creates `config.toml` in the working folder when it sets up your
trip workspace. The new file contains the built-in defaults. Edit it in a
text editor, save, and choose **Reload config file** in Poster design. Review the values,
then choose **Accept and continue**. Map data reads changes when you choose Continue or
Recheck map data. There are no CLI settings editors.

The file is authoritative. Internal JSON records accepted snapshots, validation, caches and
route decisions. Those records cannot override your file. Compatible broader caches remain
reusable without adding unwanted countries, sources or display classes.

## Common changes

| Setting | Purpose |
| --- | --- |
| `poster.title`, `poster.subtitle` | Poster text; independent of the itinerary title |
| `poster.width_mm`, `height_mm`, `margin_mm` | Physical page dimensions in millimetres |
| `poster.design` | `standard` or `reference`; configure associated framing/style values explicitly |
| `map.projection`, `map.framing` | Coordinate projection and country/stop framing |
| `map.boundaries.country_ids` or `country_codes` | Displayed countries; configure one filter |
| `map.show_state_borders` | Include optional state/province borders; requires an Admin 1 source |
| `map.roads.enabled`, `map.water.enabled` | Background layers. Roads are disabled and water is enabled by default. |
| `map.roads.highway_classes`, `map.water.line_classes`, `area_classes` | Requested feature classes |
| `map.water.min_area_km2`, `simplify_tolerance_mm` | Water detail; originals remain cached |
| `map.distance.travel_days_override` | Positive whole-number total days; omit/comment to use itinerary dates |
| `map.distance.segment_overrides_km` | Positive kilometres keyed by connection sequence number |
| `map.routing` | Default profiles, provider preferences and pacing; API-key variable name only |
| `style` | Colors, widths, fonts and per-mode colors/dash patterns |
| `style.title_font_size_mm`, `style.subtitle_font_size_mm` | Optional font sizes in millimetres, greater than 0 and at most 50 |
| `style.title_subtitle_gap_mm` | Optional distance between the text baselines in millimetres, greater than 0 and at most 50 |
| `output.incomplete_distance` | `omit` or `subtotal` for incomplete distance information |

Colors use `#RRGGBB`. Dash patterns are strings of dash/gap lengths in millimetres.
Generated commented settings are examples and are inactive. TOML has no `null`; remove or
comment an optional override to reset it. The full [default example](../examples/config.toml)
shows every populated section. Omitted values use built-in defaults rather than old CLI edits.

Omit both font sizes to use the design defaults. Standard uses 12 mm for the title and
4 mm for the subtitle. Reference uses 10 mm and 3 mm. The default title-to-subtitle
distance is 10 mm for top titles and 7 mm for bottom titles. Set `title_subtitle_gap_mm`
to move the subtitle relative to the title. Font sizes and baseline spacing are independent.

Use `style.water_line`, `style.water_area`, `style.water_line_opacity`, and
`style.water_area_opacity` to style water. TravelMap exports SVG and uses OpenRouteService
when you choose to acquire routes automatically.

If you are upgrading an existing workspace, delete `raster_dpi` and `format` from
`[output]`, `water` and `water_opacity` from `[style]`, and `provider` from `[map.routing]`
in `config.toml`. Keep your other settings, then reload and accept the design again.
For a workspace that still uses pre-TOML settings, use the previous TravelMap version to
generate `config.toml` from the saved settings before making these edits.

Example edits within the existing sections (do not duplicate table headings):

```toml
[poster]
title = "Our journey"
subtitle = "{total_km} km • {total_days} days"

[map.boundaries]
country_codes = ["ARG", "CHL"]

[map.distance]
travel_days_override = 14

[map.distance.segment_overrides_km]
"1" = 125.5

[style.route_colors_by_mode]
car = "#A33F35"

[style.route_dash_patterns]
ferry = "2 1"
```

Update stop arrival dates in **Your itinerary → Update stop dates**. With missing, invalid or
out-of-order dates, the choices focus on flagged stops and their immediate previous/next
neighbors. Faulty stops are marked `!` and shown in bold yellow; monochrome terminals retain
bold and the marker. Neighboring stops use ordinary menu styling; shared neighbors appear once.
If there are no date warnings, all stops remain available. The list is reassessed each time
it opens. Date edits are saved separately from the original input and leave an explicit
configured duration override unchanged. To calculate duration from dates again, remove/comment
`travel_days_override`. Date warnings name both Update stop dates and Poster design (Step 6)
as recovery paths; duration changes in Step 6 still use the config file.

## Countries and local sources

**Map data → Displayed countries** shows current countries and available IDs without changing
them. Set the filter in `[map.boundaries]`; omit it or use `[]` for countries containing trip
stops. An extra downloaded country does not automatically add it to the displayed selection.
If your stops lie outside a selected boundary, review the file or correct the itinerary;
acknowledging a boundary mismatch does not bypass route/background coverage checks.

Normal Natural Earth ZIPs and regional `.osm.pbf` extracts are discovered in `map-data/`.
Configure special sources through `country_path`, `admin1_path`, road/water `paths`, or
additional `sources` under the existing `[map]` section:

```toml
[map]
sources = [
  { kind = "countries", path = "map-data/extra-countries.geojson", attribution = "Local survey", licence = "CC BY 4.0" },
]
```

Supported kinds: `countries`, `admin1`, `roads`, `water_lines`, `water_areas`. An optional `layer`
selects a layer in a multi-layer file. Paths are workspace-relative and must stay inside it.
Set `show_state_borders = true` under `[map]` to require and include the Admin 1 layer.
Disabling it omits those borders without a separate CLI choice. Configure at most 16 vector-source entries in total across `sources` and the source-path
settings. Source and country changes require map-data rechecking; compatible route data is reused.

## Reload, acceptance and migration

Invalid edits keep the previously displayed design, with an error explaining the field to fix.
They cannot be accepted or exported. Changing the file during review requires another reload.
Export still checks current effective settings against the accepted signature and validates inputs.

Setup never overwrites an existing `config.toml` or replaces it through a symlink. For an old
workspace without one, setup generates the file from saved settings and map/routing metadata.
When an existing file had hidden CLI overrides, its text/comments remain intact and the old
settings are preserved in `config.previous-settings.toml`. Review the reported migration file
and copy desired values into `config.toml`. Keep it as a record until you have reviewed the design.

If you delete an established configuration, restore it from your backup or recreate it from
the default example; TravelMap does not silently restore old metadata. Never store an API key
in TOML. Routing credentials remain session-only or come from the named environment variable.
