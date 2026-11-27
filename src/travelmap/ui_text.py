"""Central editable catalog for text shown by the command line interface."""

from __future__ import annotations

import re

_TEXTS: dict[str, str] = {
    "\nPaused. Validated progress and originals are preserved.": (
        "\nPaused. Validated progress and originals are preserved."
    ),
    "\r": "\r",
    "\u001b[": "\u001b[",
    "\u001b[2K": "\u001b[2K",
    "\u001b[?25h": "\u001b[?25h",
    "\u001b[?25l": "\u001b[?25l",
    " ": " ",
    "  ": "  ",
    "   |   Next: ": "   |   Next: ",
    (
        "{0}: scan incomplete; displayed matches are a lower bound. Use a smaller folder and "
        "inspect again."
    ): (
        "{0}: scan incomplete; displayed matches are a lower bound. Use a smaller folder and "
        "inspect again."
    ),
    " (": " (",
    " (back cancels)": " (back cancels)",
    " (latitude, longitude)": " (latitude, longitude)",
    " -> ": " -> ",
    " / ": " / ",
    " = ": " = ",
    " MiB limit.": " MiB limit.",
    (
        " MiB. Use smaller country/subcountry extracts or fewer optional layers; planet "
        "extracts are unsupported."
    ): (
        " MiB. Use smaller country/subcountry extracts or fewer optional layers; planet "
        "extracts are unsupported."
    ),
    " Validated prior results are preserved; correct the stated cause and retry.": (
        " Validated prior results are preserved; correct the stated cause and retry."
    ),
    " and recheck.": " and recheck.",
    " approximate.": " approximate.",
    " connections. Visits/routes remain visible and are never removed from the journey.": (
        " connections. Visits/routes remain visible and are never removed from the journey."
    ),
    " connections; first: ": " connections; first: ",
    " entries; found ": " entries; found ",
    " field in ": " field in ",
    " folder at ": " folder at ",
    " geometry type.": " geometry type.",
    " geometry.": " geometry.",
    " has an empty boundary name.": " has an empty boundary name.",
    " has invalid coordinates.": " has invalid coordinates.",
    " has missing nodes/invalid geometry; select a complete extract.": (
        " has missing nodes/invalid geometry; select a complete extract."
    ),
    " has no geometry.": " has no geometry.",
    " line candidates retained separately.": " line candidates retained separately.",
    " matching files": " matching files",
    " metres (None means unknown).": " metres (None means unknown).",
    " mm ": " mm ",
    " mm, ": " mm, ",
    " mm; projection ": " mm; projection ",
    " must be bounded text.": " must be bounded text.",
    " must contain at most 64 nonempty class names.": (
        " must contain at most 64 nonempty class names."
    ),
    " of ": " of ",
    " open routes.": " open routes.",
    " open.": " open.",
    " ready, ": " ready, ",
    " remain open.": " remain open.",
    " resolved routes; ": " resolved routes; ",
    " route keys affected by this correction. Poster output will need refreshing.": (
        " route keys affected by this correction. Poster output will need refreshing."
    ),
    " routes saved; ": " routes saved; ",
    " saved route entries need rechecking.": " saved route entries need rechecking.",
    " shapefile. Re-download the correct polygon archive.": (
        " shapefile. Re-download the correct polygon archive."
    ),
    " stops. Choose View trip stops to see them.": " stops. Choose View trip stops to see them.",
    " stops; ": " stops; ",
    " to ": " to ",
    " total, ": " total, ",
    " usable cached features.": " usable cached features.",
    " using ": " using ",
    " validated Point markers are not route lines; ": (
        " validated Point markers are not route lines; "
    ),
    " vertices": " vertices",
    " visits and ": " visits and ",
    " · ": " · ",
    " × ": " × ",
    " — ": " — ",
    ")": ")",
    "). Select compatible vectors.": "). Select compatible vectors.",
    ", ": ", ",
    ", margins ": ", margins ",
    ", then recheck; or skip/pause.": ", then recheck; or skip/pause.",
    "--file": "--file",
    "--path": "--path",
    "--shell": "--shell",
    "--start-at": "--start-at",
    "-m": "-m",
    ".": ".",
    ". ": ". ",
    ". Check disk space and permissions; retry.": ". Check disk space and permissions; retry.",
    ". Check disk space/permissions and retry.": ". Check disk space/permissions and retry.",
    ". Check folder permissions, then retry.": ". Check folder permissions, then retry.",
    ". Check folder permissions/disk space, choose another destination, or pause.": (
        ". Check folder permissions/disk space, choose another destination, or pause."
    ),
    ". Check permissions and recheck.": ". Check permissions and recheck.",
    ". Check permissions/re-download and recheck.": ". Check permissions/re-download and recheck.",
    ". Check the affected entity/input and retry.": ". Check the affected entity/input and retry.",
    ". Choose ": ". Choose ",
    (
        ". Copy it here, choose another path in the optional config, or use ordinary "
        "manual-route files."
    ): (
        ". Copy it here, choose another path in the optional config, or use ordinary "
        "manual-route files."
    ),
    ". Correct and recheck.": ". Correct and recheck.",
    ". Correct country selection.": ". Correct country selection.",
    ". Correct the export, choose another file, or recheck.": (
        ". Correct the export, choose another file, or recheck."
    ),
    ". Correct the export.": ". Correct the export.",
    ". Download covering extracts and recheck.": ". Download covering extracts and recheck.",
    (
        ". Include neighboring regions along the journeys; stop countries do not certify "
        "route coverage."
    ): (
        ". Include neighboring regions along the journeys; stop countries do not certify "
        "route coverage."
    ),
    (
        ". Manual geometry takes precedence; poster/distance refresh, unrelated routes "
        "remain. Distance: "
    ): (
        ". Manual geometry takes precedence; poster/distance refresh, unrelated routes "
        "remain. Distance: "
    ),
    ". Re-download and recheck.": ". Re-download and recheck.",
    ". Re-download the full archive; CRS will not be guessed.": (
        ". Re-download the full archive; CRS will not be guessed."
    ),
    ". Re-download the official ZIP.": ". Re-download the official ZIP.",
    ". Re-export a supported local file and recheck.": (
        ". Re-export a supported local file and recheck."
    ),
    ". Repair that field or remove the optional TOML to use saved/default settings.": (
        ". Repair that field or remove the optional TOML to use saved/default settings."
    ),
    ". Repair the local file and recheck.": ". Repair the local file and recheck.",
    ". Restore the folder or select another workspace.": (
        ". Restore the folder or select another workspace."
    ),
    ". Select a compatible named layer.": ". Select a compatible named layer.",
    ". Select a complete regional snapshot.": ". Select a complete regional snapshot.",
    ". Select compatible local data.": ". Select compatible local data.",
    (
        ". Source envelopes omit country components. Supply covering country/regional "
        "extracts and recheck; complete boundaries and selected detail are not silently "
        "cropped."
    ): (
        ". Source envelopes omit country components. Supply covering country/regional "
        "extracts and recheck; complete boundaries and selected detail are not silently "
        "cropped."
    ),
    ". Use schema version 1.": ". Use schema version 1.",
    "/": "/",
    "/back": "/back",
    ": ": ": ",
    ": HTML page, not map data. Download the actual ZIP or .osm.pbf dataset and recheck.": (
        ": HTML page, not map data. Download the actual ZIP or .osm.pbf dataset and recheck."
    ),
    ": PBF processing failed: ": ": PBF processing failed: ",
    ": a line needs at least two vertices.": ": a line needs at least two vertices.",
    ": cannot read data: ": ": cannot read data: ",
    ": cannot read file: ": ": cannot read file: ",
    ": changed during preparation. Recheck after copying finishes.": (
        ": changed during preparation. Recheck after copying finishes."
    ),
    ": checked ": ": checked ",
    ": conflicting same-version objects; use current snapshot extracts.": (
        ": conflicting same-version objects; use current snapshot extracts."
    ),
    ": country boundary does not cover stop.": ": country boundary does not cover stop.",
    ": exceeds ": ": exceeds ",
    ": exceeds 8 MiB. Export a smaller trip and recheck.": (
        ": exceeds 8 MiB. Export a smaller trip and recheck."
    ),
    ": exceeds one million vertices per feature.": ": exceeds one million vertices per feature.",
    ": exceeds the ": ": exceeds the ",
    ": expected Feature object.": ": expected Feature object.",
    ": expected GeoJSON Feature.": ": expected GeoJSON Feature.",
    ": expected a JSON object.": ": expected a JSON object.",
    ": expected a regular local file.": ": expected a regular local file.",
    ": expected a regular map cache.": ": expected a regular map cache.",
    ": expected one stop Point coordinate.": ": expected one stop Point coordinate.",
    ": feature ": ": feature ",
    ": file changed while hashing; retry.": ": file changed while hashing; retry.",
    ": history PBFs are unsupported; select a current snapshot.": (
        ": history PBFs are unsupported; select a current snapshot."
    ),
    ": incomplete/unreadable boundary archive: ": ": incomplete/unreadable boundary archive: ",
    ": invalid coordinates: ": ": invalid coordinates: ",
    ": invalid country boundary; select compatible data.": (
        ": invalid country boundary; select compatible data."
    ),
    ": invalid route export: ": ": invalid route export: ",
    ": invalid selected boundary geometry; recheck compatible map data.": (
        ": invalid selected boundary geometry; recheck compatible map data."
    ),
    ": invalid selected boundary geometry; select compatible boundaries.": (
        ": invalid selected boundary geometry; select compatible boundaries."
    ),
    ": invalid selected country geometry; select compatible data.": (
        ": invalid selected country geometry; select compatible data."
    ),
    ": label priority must be a nonnegative integer.": (
        ": label priority must be a nonnegative integer."
    ),
    ": line needs 2–10,000 vertices.": ": line needs 2–10,000 vertices.",
    ": map cache exceeds 8 GiB.": ": map cache exceeds 8 GiB.",
    ": missing ": ": missing ",
    ": missing CRS. Re-export with explicit CRS metadata; do not guess it.": (
        ": missing CRS. Re-export with explicit CRS metadata; do not guess it."
    ),
    ": missing boundary name column (": ": missing boundary name column (",
    ": missing companions ": ": missing companions ",
    ": missing geometry/properties.": ": missing geometry/properties.",
    ": missing properties or geometry.": ": missing properties or geometry.",
    ": missing source entity ledger.": ": missing source entity ledger.",
    ": more than 10,000 vertices. Export a simpler line.": (
        ": more than 10,000 vertices. Export a simpler line."
    ),
    ": node ": ": node ",
    ": non-finite or out-of-range WGS84 coordinates.": (
        ": non-finite or out-of-range WGS84 coordinates."
    ),
    ": output exists. Choose a new name or explicitly confirm replacement.": (
        ": output exists. Choose a new name or explicitly confirm replacement."
    ),
    ": physical size must be at most 50 mm.": ": physical size must be at most 50 mm.",
    ": planet extracts are unsupported. Download country/subcountry PBFs.": (
        ": planet extracts are unsupported. Download country/subcountry PBFs."
    ),
    (
        ": preparation staging exceeds 16 GiB. Free workspace disk or reduce selected "
        "classes; no re-download is needed."
    ): (
        ": temporary map data exceeded the 16 GiB safety limit. Enable fewer map classes in "
        "config.toml and retry. Valid downloads can be reused."
    ),
    ": prepared integrity check failed. Recheck.": ": prepared integrity check failed. Recheck.",
    ": raw entity exceeds one million references.": ": raw entity exceeds one million references.",
    ": return to routing for local files/acquisition; no direct line is invented.": (
        ": return to routing for local files/acquisition; no direct line is invented."
    ),
    ": select a regular local file, not a link.": ": select a regular local file, not a link.",
    ": sends ": ": sends ",
    ": serialized feature exceeds supported size.": ": serialized feature exceeds supported size.",
    ": size limit exceeded. Choose a smaller extract.": (
        ": size limit exceeded. Choose a smaller extract."
    ),
    ": supported advanced vectors are SHP, GPKG or GeoJSON.": (
        ": supported advanced vectors are SHP, GPKG or GeoJSON."
    ),
    (
        ": this recorded mode has no default provider profile. Any acquired road route would "
        "be an approximation; recorded mode is retained."
    ): (
        ": this recorded mode has no default provider profile. Any acquired road route would "
        "be an approximation; recorded mode is retained."
    ),
    ": too many water members.": ": too many water members.",
    ": unreadable PBF header: ": ": unreadable PBF header: ",
    ": unreadable vector/CRS transformation: ": ": unreadable vector/CRS transformation: ",
    ": unsupported ": ": unsupported ",
    ": unsupported geometry or feature_type.": ": unsupported geometry or feature_type.",
    ": use a portable workspace-relative file path.": (
        ": use a portable workspace-relative file path."
    ),
    (
        ": use plain font-family names, letters/numbers/spaces/hyphens/commas; no markup or "
        "resources."
    ): (
        ": use plain font-family names, letters/numbers/spaces/hyphens/commas; no markup or "
        "resources."
    ),
    ": use workspace-relative file paths.": ": use workspace-relative file paths.",
    ": water assembly failed: ": ": water assembly failed: ",
    ": way exceeds one million vertices.": ": way exceeds one million vertices.",
    (
        ": worker resident memory exceeds 3 GiB. Reduce selected classes or use a machine "
        "with the documented resources; valid downloads need no re-download."
    ): (
        ": map preparation exceeded the 3 GiB memory safety limit. Enable fewer map classes "
        "in config.toml and retry. Valid downloads can be reused."
    ),
    "; ": "; ",
    "; approximate routes: ": "; approximate routes: ",
    "; explicit metadata matches": "; explicit metadata matches",
    "; export separate LineStrings.": "; export separate LineStrings.",
    "; labels ": "; labels ",
    "; last: ": "; last: ",
    "; originals and prior artwork are protected.": "; originals and prior artwork are protected.",
    "; prior source: ": "; prior source: ",
    "; recorded mode is unchanged.": "; recorded mode is unchanged.",
    "; resolved sources: ": "; resolved sources: ",
    "; stop markers ": "; stop markers ",
    "; use a complete extract.": "; use a complete extract.",
    "; water ": "; water ",
    "A": "A",
    "A journey route is the line you travelled, separate from background roads.": (
        "A journey route is the line you travelled, separate from background roads."
    ),
    "A workspace is a folder where TravelMap keeps its files together.": (
        "A workspace is a folder where TravelMap keeps its files together."
    ),
    "Accept an itinerary before choosing displayed countries.": (
        "Accept an itinerary before choosing displayed countries."
    ),
    (
        "Accept an itinerary first so map preparation can use its extent. Return to the "
        "itinerary step."
    ): (
        "Accept an itinerary first so map preparation can use its extent. Return to the "
        "itinerary step."
    ),
    "Accept and continue": "Accept and continue",
    (
        "Accept the ready-made design to continue. Customize is optional and shows each "
        "current value."
    ): (
        "Accept the ready-made design to continue. Customize is optional and shows each "
        "current value."
    ),
    (
        "Acquisition sends selected endpoint coordinates to OpenRouteService. A key is used "
        "only in this session; it is never saved."
    ): (
        "Acquisition sends selected endpoint coordinates to OpenRouteService. A key is used "
        "only in this session; it is never saved."
    ),
    "Actual expanded archive bytes exceed the declared limit.": (
        "Actual expanded archive bytes exceed the declared limit."
    ),
    "Add your own routes": "Add your own routes",
    "Add your own routes?": "Add your own routes?",
    "Advanced vector ": "Advanced vector ",
    "Advanced vector layer must be text.": "Advanced vector layer must be text.",
    "Advanced vector path must name a local file.": "Advanced vector path must name a local file.",
    "Advanced vectors require a supported kind and local path.": (
        "Advanced vectors require a supported kind and local path."
    ),
    "All numeric settings must be finite.": "All numeric settings must be finite.",
    "All routes are ready.": "All routes are ready.",
    "Allow approximate route merging": "Allow approximate route merging",
    "Ambiguous 180-degree geographic edge; select compatible geometry.": (
        "Ambiguous 180-degree geographic edge; select compatible geometry."
    ),
    "Ambiguous water-hole ownership; correct the relation.": (
        "Ambiguous water-hole ownership; correct the relation."
    ),
    "Apply this country filter": "Apply this country filter",
    "Archive entry exceeds 128 MiB. Choose a smaller supported dataset.": (
        "Archive entry exceeds 128 MiB. Choose a smaller supported dataset."
    ),
    "Archive exceeds 256 entries. Re-download the supported boundary ZIP.": (
        "Archive exceeds 256 entries. Re-download the supported boundary ZIP."
    ),
    "Archive expansion exceeds 256 MiB. Choose a smaller supported dataset.": (
        "Archive expansion exceeds 256 MiB. Choose a smaller supported dataset."
    ),
    "Archive file/directory collision. Re-download the official ZIP.": (
        "Archive file/directory collision. Re-download the official ZIP."
    ),
    "Arrival: ": "Arrival: ",
    "Assign ": "Assign ",
    "Assign this line to the connection": "Assign this line to the connection",
    "Assignments exceed 8 MiB. Use simpler routes; prior assignments are preserved.": (
        "Assignments exceed 8 MiB. Use simpler routes; prior assignments are preserved."
    ),
    "At most eight route-color variants are supported.": (
        "At most eight route-color variants are supported."
    ),
    "Available unresolved journeys:": "Available unresolved journeys:",
    "Back": "Back",
    "Back to stops": "Back to stops",
    (
        "Background roads/water are required. Download the regional Geofabrik .osm.pbf "
        "described above, copy it into the destination and choose Continue."
    ): (
        "Background roads/water are required. Download the regional Geofabrik .osm.pbf "
        "described above, copy it into the destination and choose Continue."
    ),
    "Broken segment reference or sequence: connections must follow visit order.": (
        "Broken segment reference or sequence: connections must follow visit order."
    ),
    "Cached data exceeds feature/vertex limits; reprepare selected classes.": (
        "Cached data exceeds feature/vertex limits; reprepare selected classes."
    ),
    "Cannot check ": "Cannot check ",
    "Cannot preserve existing artwork for this batch. Choose a new filename.": (
        "Cannot preserve existing artwork for this batch. Choose a new filename."
    ),
    "Cannot save ": "Cannot save ",
    "Cannot write ": "Cannot write ",
    "Change countries": "Change countries",
    "Change design: ": "Change design: ",
    "Change filename": "Change filename",
    "Change title": "Change title",
    "Change transport": "Change transport",
    "Changes saved.": "Changes saved.",
    "Check for the optional download": "Check for the optional download",
    "Checked folder: ": "Checked folder: ",
    "Checking downloads and preparing boundaries, roads and water.": (
        "Checking downloads and preparing boundaries, roads and water."
    ),
    "Choose Continue, Help, Back, or Save and exit.": (
        "Choose Continue, Help, Back, or Save and exit."
    ),
    "Choose a connection for an explicit kilometre override:": (
        "Choose a connection for an explicit kilometre override:"
    ),
    "Choose a displayed action.": "Choose a displayed action.",
    "Choose a displayed connection number.": "Choose a displayed connection number.",
    "Choose a folder you can write to, preferably outside the downloaded program folder.": (
        "Choose a folder you can write to, preferably outside the downloaded program folder."
    ),
    "Choose a new filename": "Choose a new filename",
    "Choose a number": "Choose a number",
    "Choose a number from 1 to ": "Choose a number from 1 to ",
    "Choose a number, help or pause": "Choose a number, help or pause",
    "Choose a plain .svg filename.": "Choose a plain .svg filename.",
    "Choose a plain .svg filename. For PDF, export SVG then use your editor’s PDF export.": (
        "Choose a plain .svg filename. For PDF, export SVG then use your editor’s PDF export."
    ),
    "Choose a recorded mode for color/dash styling:": (
        "Choose a recorded mode for color/dash styling:"
    ),
    "Choose a route file": "Choose a route file",
    "Choose a route file:": "Choose a route file:",
    "Choose a recent folder, or go back.": "Choose a recent folder, or go back.",
    "Choose a recent workspace or another folder.": "Choose a recent workspace or another folder.",
    "Choose from recent folders": "Choose from recent folders",
    "Choose another folder": "Choose another folder",
    "Use this folder, choose another, or get help.": (
        "Use this folder, choose another, or get help."
    ),
    "Use the suggested folder": "Use the suggested folder",
    "Help with workspaces": "Help with workspaces",
    "Pause": "Pause",
    "Recent folders:": "Recent folders:",
    "Use default folder": "Use default folder",
    "Use most recent folder": "Use most recent folder",
    "Choose a setting category:": "Choose a setting category:",
    "Choose a step": "Choose a step",
    "Choose a subset": "Choose a subset",
    "Choose a supported transport mode.": "Choose a supported transport mode.",
    "Choose a value to change (mm = physical page size; opacity 0–1; colors #RRGGBB):": (
        "Choose a value to change (mm = physical page size; opacity 0–1; colors #RRGGBB):"
    ),
    "Choose another file": "Choose another file",
    "Choose displayed unresolved numbers exactly once, all, or pause.": (
        "Choose displayed unresolved numbers exactly once, all, or pause."
    ),
    "Choose each country or region crossed by your trip.": (
        "Choose each country or region crossed by your trip."
    ),
    "Choose explicitly for this connection:": "Choose explicitly for this connection:",
    "Choose one of the displayed actions.": "Choose one of the displayed actions.",
    "Choose one of the displayed numbers, or pause.": (
        "Choose one of the displayed numbers, or pause."
    ),
    "Choose one route line:": "Choose one route line:",
    "Choose recognized boundary names. Unknown: ": "Choose recognized boundary names. Unknown: ",
    ("Choose the intended file or trip by number. Nothing is merged. Pause preserves your work."): (
        "Choose the intended file or trip by number. Nothing is merged. Pause preserves your work."
    ),
    "Choose transport": "Choose transport",
    "Choose yes or no.": "Choose yes or no.",
    "Choose your poster design": "Choose your poster design",
    "Chosen projection cannot represent all trip coordinates. Choose auto projection.": (
        "Chosen projection cannot represent all trip coordinates. Choose auto projection."
    ),
    "Colliding archive entries: ": "Colliding archive entries: ",
    "Colours use six hexadecimal digits; physical sizes are millimetres.": (
        "Colours use six hexadecimal digits; physical sizes are millimetres."
    ),
    "Complete your routes": "Complete your routes",
    "Configured advanced route cache is missing: ": "Configured advanced route cache is missing: ",
    "Connection ": "Connection ",
    "Connection number": "Connection number",
    "Continue": "Continue",
    "Continue to poster design?": "Continue to poster design?",
    "Continue without state/province borders": "Continue without state/province borders",
    "Coordinate needs longitude, latitude and optional altitude.": (
        "Coordinate needs longitude, latitude and optional altitude."
    ),
    "Coordinate outside WGS84 longitude/latitude range.": (
        "Coordinate outside WGS84 longitude/latitude range."
    ),
    "Coordinate values must be finite numbers.": "Coordinate values must be finite numbers.",
    ("Copy country boundaries into the map-data folder, then choose Displayed countries again."): (
        "Copy country boundaries into the map-data folder, then choose Displayed countries again."
    ),
    "Copy the .kml file into:": "Copy the .kml file into:",
    "Copy the downloads into:": "Copy the downloads into:",
    (
        "Copy the optional Natural Earth Admin 1 States/Provinces polygon ZIP, then choose "
        "Continue at this stage."
    ): (
        "Copy the optional Natural Earth Admin 1 States/Provinces polygon ZIP, then choose "
        "Continue at this stage."
    ),
    "Copy these files into the folder above, then choose Continue.": (
        "Copy these files into the folder above, then choose Continue."
    ),
    "Corrupt map cache; rebuild it.": "Corrupt map cache; rebuild it.",
    "Country boundaries (required):": "Country boundaries (required):",
    (
        "Country boundaries are required. Download the Natural Earth Admin 0 Countries ZIP "
        "described above, copy it into the destination and choose Continue."
    ): (
        "Country boundaries are required. Download the Natural Earth Admin 0 Countries ZIP "
        "described above, copy it into the destination and choose Continue."
    ),
    (
        "Country catalog exceeds 4,096 boundaries or two million vertices. Select the "
        "supported Natural Earth country dataset."
    ): (
        "Country catalog exceeds 4,096 boundaries or two million vertices. Select the "
        "supported Natural Earth country dataset."
    ),
    "Country filter hides background land around ": "Country filter hides background land around ",
    "Country names, separated by commas (for example Argentina, Chile)": (
        "Country names, separated by commas (for example Argentina, Chile)"
    ),
    "Country selection must contain valid boundary IDs.": (
        "Country selection must contain valid boundary IDs."
    ),
    "Country selection saved. Continue in Map data to refresh affected layers.": (
        "Country selection saved. Continue in Map data to refresh affected layers."
    ),
    "Country view": "Country view",
    (
        "Country/source provenance exceeds the 1 MiB selection budget. Use fewer source "
        "artifacts or corrected data requiring fewer repairs; completed caches and the prior "
        "selection are preserved."
    ): (
        "Country/source provenance exceeds the 1 MiB selection budget. Use fewer source "
        "artifacts or corrected data requiring fewer repairs; completed caches and the prior "
        "selection are preserved."
    ),
    "Country: ": "Country: ",
    "Coverage incomplete for whole displayed countries: ": (
        "Coverage incomplete for whole displayed countries: "
    ),
    "Coverage incomplete: ": "Coverage incomplete: ",
    "Create a travel poster from your trip, one step at a time.": (
        "Create a travel poster from your trip, one step at a time."
    ),
    "Create your poster": "Create your poster",
    "Created: ": "Created: ",
    "Customize design": "Customize design",
    "Cycling approximation": "Cycling approximation",
    (
        "Cycling/walking are offered only for genuine route-not-found failures; "
        "quota/auth/server errors have their own recovery. Local files or pause are always "
        "available."
    ): (
        "Cycling/walking are offered only for genuine route-not-found failures; "
        "quota/auth/server errors have their own recovery. Local files or pause are always "
        "available."
    ),
    "Dash patterns use supported modes and positive numbers separated by spaces (mm).": (
        "Dash patterns use supported modes and positive numbers separated by spaces (mm)."
    ),
    "Dash/gap lengths in mm (space-separated), or remove": (
        "Dash/gap lengths in mm (space-separated), or remove"
    ),
    (
        "Default design requires country boundaries, background roads and water. "
        "State/province boundaries are optional. Journey routes are prepared separately."
    ): (
        "Default design requires country boundaries, background roads and water. "
        "State/province boundaries are optional. Journey routes are prepared separately."
    ),
    ("Direct policy must be error or direct; direct lines still require explicit confirmation."): (
        "Direct policy must be error or direct; direct lines still require explicit confirmation."
    ),
    "Displayed complete countries: ": "Displayed complete countries: ",
    "Displayed countries": "Displayed countries",
    "Distance/duration must be nonnegative finite numbers with recognized units.": (
        "Distance/duration must be nonnegative finite numbers with recognized units."
    ),
    "Download countries. Keep the ZIP intact: ": "Download countries. Keep the ZIP intact: ",
    "Download country boundaries and regional roads/water.": (
        "Download country boundaries and regional roads/water."
    ),
    "Download states and provinces (polygons). Keep the ZIP intact.": (
        "Download states and provinces (polygons). Keep the ZIP intact."
    ),
    "Download the .osm.pbf files, including regions between stops.": (
        "Download the .osm.pbf files, including regions between stops."
    ),
    "Driving approximation": "Driving approximation",
    "Duplicate JSON field ": "Duplicate JSON field ",
    "Duplicate cache records. Choose a collection with unique segment records.": (
        "Duplicate cache records. Choose a collection with unique segment records."
    ),
    "Duplicate explicit placemark IDs. Give each feature a unique ID.": (
        "Duplicate explicit placemark IDs. Give each feature a unique ID."
    ),
    "Duplicate explicit visit IDs. Give each visit a unique ID.": (
        "Duplicate explicit visit IDs. Give each visit a unique ID."
    ),
    "Each dash/gap must be >0 and <=50 mm.": "Each dash/gap must be >0 and <=50 mm.",
    (
        "Each line and named connection are selected explicitly; originals are preserved. "
        "Missing distance can be overridden later."
    ): (
        "Each line and named connection are selected explicitly; originals are preserved. "
        "Missing distance can be overridden later."
    ),
    "Edits are saved separately and originals stay unchanged. Accept continues to Map data.": (
        "Edits are saved separately and originals stay unchanged. Accept continues to Map data."
    ),
    "Effective settings saved. Compatible routes and map layers remain available.": (
        "Effective settings saved. Compatible routes and map layers remain available."
    ),
    "Empty itinerary: export at least one Point stop.": (
        "Empty itinerary: export at least one Point stop."
    ),
    "Enter a value, /back, or /exit to save and exit.": (
        "Enter a value, /back, or /exit to save and exit."
    ),
    "Enter connection numbers separated by spaces, all, or pause": (
        "Enter connection numbers separated by spaces, all, or pause"
    ),
    "Enter every visit number exactly once, in the desired order.": (
        "Enter every visit number exactly once, in the desired order."
    ),
    "Existing artwork: ": "Existing artwork: ",
    "Existing files require a new name or explicit replacement.": (
        "Existing files require a new name or explicit replacement."
    ),
    "Exited. No new workspace was selected.": "Exited. No new workspace was selected.",
    "Expected 1–1,000 route/marker features. Export a smaller collection.": (
        "Expected 1–1,000 route/marker features. Export a smaller collection."
    ),
    "Expected KML 2.2 namespace. Export a KML 2.2 file.": (
        "Expected KML 2.2 namespace. Export a KML 2.2 file."
    ),
    "Expected a GeoJSON object.": "Expected a GeoJSON object.",
    "Expected at most 5,000 features. Export a smaller trip.": (
        "Expected at most 5,000 features. Export a smaller trip."
    ),
    "Expected normalized GeoJSON FeatureCollection.": (
        "Expected normalized GeoJSON FeatureCollection."
    ),
    "Expected one provider route.": "Expected one provider route.",
    "Expected provider LineString.": "Expected provider LineString.",
    "Export": "Export",
    "Export SVG": "Export SVG",
    (
        "Export WGS84 GeoJSON from your recorder or route planner, copy it into the folder "
        "above, then recheck."
    ): (
        "Export WGS84 GeoJSON from your recorder or route planner, copy it into the folder "
        "above, then recheck."
    ),
    (
        "Export writes an editable SVG with millimetre page size and named layers. All data "
        "is local; no routing request or download happens here."
    ): (
        "Export writes an editable SVG with millimetre page size and named layers. All data "
        "is local; no routing request or download happens here."
    ),
    "Export your trip as a KML file.": "Export your trip as a KML file.",
    "Export/copy route files into: ": "Export/copy route files into: ",
    "Feature ": "Feature ",
    (
        "Files located. This is a filename check; their contents, formats, trip meaning and "
        "map coverage have not been validated."
    ): (
        "Files located. This is a filename check; their contents, formats, trip meaning and "
        "map coverage have not been validated."
    ),
    "Find all matching routes": "Find all matching routes",
    "First time? Choose Workspace. We will guide you through the steps.": (
        "First time? Choose Workspace. We will guide you through the steps."
    ),
    "First time? Choose Workspace. We will guide you through all seven steps.": (
        "First time? Choose Workspace. We will guide you through all seven steps."
    ),
    "Fonts: installed name with generic serif/sans-serif fallback.": (
        "Fonts: installed name with generic serif/sans-serif fallback."
    ),
    "Geographic polygon hole is outside its exterior.": (
        "Geographic polygon hole is outside its exterior."
    ),
    "Help": "Help",
    "Hidden key input is unavailable. Use a regular terminal or local route files.": (
        "Hidden key input is unavailable. Use a regular terminal or local route files."
    ),
    (
        "I will explain each task and wait while you complete it. Your files stay local. A "
        "routing key is requested only if you explicitly choose to acquire missing routes."
    ): (
        "I will explain each task and wait while you complete it. Your files stay local. A "
        "routing key is requested only if you explicitly choose to acquire missing routes."
    ),
    "Import available places?": "Import available places?",
    "Import supported places": "Import supported places",
    "In your trip app, choose Export or Download, then KML.": (
        "In your trip app, choose Export or Download, then KML."
    ),
    "Include state/province borders?": "Include state/province borders?",
    "Incomplete cached water relation assembly.": "Incomplete cached water relation assembly.",
    "Independent colors, widths, opacities and fonts": (
        "Independent colors, widths, opacities and fonts"
    ),
    "Invalid ": "Invalid ",
    "Invalid cached boundary code.": "Invalid cached boundary code.",
    "Invalid cached boundary parent metadata.": "Invalid cached boundary parent metadata.",
    "Invalid cached boundary validation state.": "Invalid cached boundary validation state.",
    "Invalid cached entity ledger.": "Invalid cached entity ledger.",
    "Invalid cached feature class.": "Invalid cached feature class.",
    "Invalid cached feature metadata/version.": "Invalid cached feature metadata/version.",
    "Invalid cached feature name.": "Invalid cached feature name.",
    "Invalid cached feature types, size or vertex count.": (
        "Invalid cached feature types, size or vertex count."
    ),
    "Invalid cached geometry; recheck map data.": "Invalid cached geometry; recheck map data.",
    "Invalid cached vertices/count or geographic envelopes.": (
        "Invalid cached vertices/count or geographic envelopes."
    ),
    "Invalid cached water repair metadata.": "Invalid cached water repair metadata.",
    "Invalid geodesic water area; disable area filtering and retry.": (
        "Invalid geodesic water area; disable area filtering and retry."
    ),
    "Invalid inner cannot establish water-hole ownership.": (
        "Invalid inner cannot establish water-hole ownership."
    ),
    "Invalid original water repair record.": "Invalid original water repair record.",
    "Invalid orphaned cache envelopes.": "Invalid orphaned cache envelopes.",
    "Invalid outer cannot establish water-hole ownership.": (
        "Invalid outer cannot establish water-hole ownership."
    ),
    "Invalid projected water geometry; disable simplification or change projection.": (
        "Invalid projected water geometry; disable simplification or change projection."
    ),
    "Invalid source coverage envelope.": "Invalid source coverage envelope.",
    "Invalid/empty ": "Invalid/empty ",
    "Itinerary accepted.": "Itinerary accepted.",
    "JSON depth exceeds 32. Export a smaller, simpler trip.": (
        "JSON depth exceeds 32. Export a smaller, simpler trip."
    ),
    (
        "Journey geometry comes from assigned files, valid embedded lines or matching "
        "provider caches first."
    ): (
        "Journey geometry comes from assigned files, valid embedded lines or matching "
        "provider caches first."
    ),
    "Keep these countries": "Keep these countries",
    (
        "Keeping the workspace outside the program folder means replacing the downloaded "
        "code later will not remove your trip files."
    ): (
        "Keeping the workspace outside the program folder means replacing the downloaded "
        "code later will not remove your trip files."
    ),
    "Layers: country boundaries; roads ": "Layers: country boundaries; roads ",
    "Leave this terminal open while you copy files, then choose Continue.": (
        "Leave this terminal open while you copy files, then choose Continue."
    ),
    "Lists: comma-separated values; empty means none. Booleans: yes/no.": (
        "Lists: comma-separated values; empty means none. Booleans: yes/no."
    ),
    "Local files/pause": "Local files/pause",
    "Located: ": "Located: ",
    "Location: ": "Location: ",
    (
        "Login/register at https://account.heigit.org/ and copy an API key from your account "
        "dashboard. You may use local files or pause instead. Credentials stay in memory for "
        "this session."
    ): (
        "Login/register at https://account.heigit.org/ and copy an API key from your account "
        "dashboard. You may use local files or pause instead. Credentials stay in memory for "
        "this session."
    ),
    "Malformed wrapped water polygon needs corrected source topology.": (
        "Malformed wrapped water polygon needs corrected source topology."
    ),
    (
        "Manual assignments contain unsupported schema or too many records. Repair/reselect "
        "the assignment file."
    ): (
        "Manual assignments contain unsupported schema or too many records. Repair/reselect "
        "the assignment file."
    ),
    "Map cache changed during export; recheck data.": (
        "Map cache changed during export; recheck data."
    ),
    "Map cache changed during validation; retry.": "Map cache changed during validation; retry.",
    "Map cache directory must not be a link.": "Map cache directory must not be a link.",
    "Map data": "Map data",
    "Map data will be rechecked if needed.": "Map data will be rechecked if needed.",
    "Map layers and advanced routing/projection": "Map layers and advanced routing/projection",
    "Map worker": "Map worker",
    "Map-data folder exceeds 1,000 entries. Use a smaller trip folder and recheck.": (
        "Map-data folder exceeds 1,000 entries. Use a smaller trip folder and recheck."
    ),
    "Margins must leave at least 20 mm of usable page area.": (
        "Margins must leave at least 20 mm of usable page area."
    ),
    (
        "Minimum water area in square kilometres: 0 disables filtering; 1 omits areas "
        "smaller than 1 km². Uses original geodesic area, subtracting holes. Water lines and "
        "cached geometry remain unchanged."
    ): (
        "Minimum water area in square kilometres: 0 disables filtering; 1 omits areas "
        "smaller than 1 km². Uses original geodesic area, subtracting holes. Water lines and "
        "cached geometry remain unchanged."
    ),
    "Missing KML Document. Export a supported itinerary.": (
        "Missing KML Document. Export a supported itinerary."
    ),
    "Missing cached boundary name.": "Missing cached boundary name.",
    "Missing country boundaries: download Natural Earth Admin 0 Countries ZIP into ": (
        "Missing country boundaries: download Natural Earth Admin 0 Countries ZIP into "
    ),
    "Missing or duplicate ExtendedData field name.": (
        "Missing or duplicate ExtendedData field name."
    ),
    (
        "Missing roads/water: download country/regional .osm.pbf extracts or configure all "
        "three advanced layers."
    ): (
        "Missing roads/water: download country/regional .osm.pbf extracts or configure all "
        "three advanced layers."
    ),
    "Missing water member osm:way:": "Missing water member osm:way:",
    "Mode color #RRGGBB, or remove": "Mode color #RRGGBB, or remove",
    "Mode colors require a supported transport mode.": (
        "Mode colors require a supported transport mode."
    ),
    "More than 100,000 vertices. Export a simpler trip.": (
        "More than 100,000 vertices. Export a simpler trip."
    ),
    "More than 5,000 placemarks. Export a smaller trip.": (
        "More than 5,000 placemarks. Export a smaller trip."
    ),
    "More than 500,000 route vertices. Export a smaller/simpler collection.": (
        "More than 500,000 route vertices. Export a smaller/simpler collection."
    ),
    "More than 512 water repairs; select a corrected source.": (
        "More than 512 water repairs; select a corrected source."
    ),
    (
        "Nearby merging approximates route shape within the configured page-space tolerance; "
        "default is disabled."
    ): (
        "Nearby merging approximates route shape within the configured page-space tolerance; "
        "default is disabled."
    ),
    "Nearby-route tolerance must be >0 and <=5 mm on the page.": (
        "Nearby-route tolerance must be >0 and <=5 mm on the page."
    ),
    "Nested archives are unsupported. Download the boundary dataset ZIP directly.": (
        "Nested archives are unsupported. Download the boundary dataset ZIP directly."
    ),
    "New .svg filename": "New .svg filename",
    "Next": "Next",
    "Next up:": "Next up:",
    "Next stop: ": "Next stop: ",
    "No LineString routes found. Export a line route, not only point markers.": (
        "No LineString routes found. Export a line route, not only point markers."
    ),
    "No connections": "No connections",
    "No country coordinates available for framing.": (
        "No country coordinates available for framing."
    ),
    "No matching unresolved journeys in this subset. Choose another subset or local files.": (
        "No matching unresolved journeys in this subset. Choose another subset or local files."
    ),
    "No route files yet. Copy a .geojson/.json route into ": (
        "No route files yet. Copy a .geojson/.json route into "
    ),
    (
        "No supported background roads intersect selected countries. Select covering "
        "extracts or road classes."
    ): (
        "No supported background roads intersect selected countries. Select covering "
        "extracts or road classes."
    ),
    "No unassigned itinerary lines are available.": "No unassigned itinerary lines are available.",
    "No validated prepared map layers are currently available.": (
        "No validated prepared map layers are currently available."
    ),
    "No workspace was selected; no folder or resume command was created.": (
        "No workspace was selected; no folder or resume command was created."
    ),
    "Normalized result exceeds 8 MiB. Export a smaller trip.": (
        "Normalized result exceeds 8 MiB. Export a smaller trip."
    ),
    "Normalized trip exceeds 5,000 features. Export a smaller trip.": (
        "Normalized trip exceeds 5,000 features. Export a smaller trip."
    ),
    "Notes: ": "Notes: ",
    "Numeric sizes: mm; padding: percent.": "Numeric sizes: mm; padding: percent.",
    "Once you’ve copied the files, choose Continue below.": (
        "Once you’ve copied the files, choose Continue below."
    ),
    (
        "Only SVG export is supported. Open the SVG in an editor and export PDF there for printing."
    ): (
        "Only SVG export is supported. Open the SVG in an editor and export PDF there for printing."
    ),
    "Onward transport connects each stop to the next.": (
        "Onward transport connects each stop to the next."
    ),
    "Open Help for download links and instructions.": (
        "Open Help to see where and how to download the map data."
    ),
    (
        "Open in a browser to view or Inkscape/Illustrator to edit; use that editor’s PDF "
        "export for printing."
    ): (
        "Open in a browser to view or Inkscape/Illustrator to edit; use that editor’s PDF "
        "export for printing."
    ),
    (
        "Open in a browser/viewer, or Inkscape/Illustrator for independently editable "
        "layers. Export PDF from the editor for physical-size printing."
    ): (
        "Open in a browser/viewer, or Inkscape/Illustrator for independently editable "
        "layers. Export PDF from the editor for physical-size printing."
    ),
    "Open: ": "Open: ",
    ("Optional state/province boundaries absent. Explicitly choose reduced detail to continue."): (
        "Optional state/province boundaries absent. Explicitly choose reduced detail to continue."
    ),
    "Optional: add route lines exported as GeoJSON (.geojson or .json).": (
        "Optional: add route lines exported as GeoJSON (.geojson or .json)."
    ),
    "Optional: copy GeoJSON route files into:": "Optional: copy GeoJSON route files into:",
    "Other existing files/folders: ": "Other existing files/folders: ",
    "Output and incomplete distance": "Output and incomplete distance",
    "Output appeared during export. Choose a new filename or confirm replacement.": (
        "Output appeared during export. Choose a new filename or confirm replacement."
    ),
    "Output: ": "Output: ",
    (
        "Override unknown kilometres/days, remove subtitle fields, or set "
        "output.incomplete_distance=subtotal to label a partial total."
    ): (
        "Override unknown kilometres/days, remove subtitle fields, or set "
        "output.incomplete_distance=subtotal to label a partial total."
    ),
    "Own routes": "Own routes",
    "Page width/height must be 50–2,000 mm.": "Page width/height must be 50–2,000 mm.",
    "Page, title and subtitle": "Page, title and subtitle",
    "Page/margins leave too little room for the map; increase page dimensions.": (
        "Page/margins leave too little room for the map; increase page dimensions."
    ),
    "Page/margins must leave more than 60 mm for title and map.": (
        "Page/margins must leave more than 60 mm for title and map."
    ),
    "Partial run only; prior artwork restored. Completed new posters: ": (
        "Partial run only; prior artwork restored. Completed new posters: "
    ),
    "Partial run; earlier existing artwork is protected. Completed new posters: ": (
        "Partial run; earlier existing artwork is protected. Completed new posters: "
    ),
    "Paused. Any completed folders and your existing files were kept.": (
        "Paused. Any completed folders and your existing files were kept."
    ),
    "Paused. No existing files were changed.": "Paused. No existing files were changed.",
    "Paused. No workspace changes were discarded.": "Paused. No workspace changes were discarded.",
    "Paused. No workspace was selected or changed.": (
        "Paused. No workspace was selected or changed."
    ),
    "Paused. Validated workspace files are kept.": "Paused. Validated workspace files are kept.",
    ("Polar winding geometry is unsupported by this projection; select compatible boundaries."): (
        "Polar winding geometry is unsupported by this projection; select compatible boundaries."
    ),
    "Positive kilometres, or remove": "Positive kilometres, or remove",
    "Positive trip days, or remove": "Positive trip days, or remove",
    "Poster design": "Poster design",
    "Poster settings require acceptance before export.": (
        "Poster settings require acceptance before export."
    ),
    "Prepare boundaries before reviewing a country filter.": (
        "Prepare boundaries before reviewing a country filter."
    ),
    (
        "Prepared data exceeds five million features or 100 million vertices; reduce "
        "selected classes."
    ): (
        "Prepared data exceeds five million features or 100 million vertices; reduce "
        "selected classes."
    ),
    "Prepared output exceeds 64 MiB. Use smaller extracts or fewer layers.": (
        "Prepared output exceeds 64 MiB. Use smaller extracts or fewer layers."
    ),
    "Prepared selection changed; recheck map data.": (
        "Prepared selection changed; recheck map data."
    ),
    (
        "Preparing whole-country map data. The first run can take a long time; counters show "
        "activity."
    ): (
        "Preparing whole-country map data. The first run can take a long time; counters show "
        "activity."
    ),
    "Press Enter to continue": "Press Enter to continue",
    "Previous": "Previous",
    "Previous: ": "Previous: ",
    "Previously not found by the service: ": "Previously not found by the service: ",
    "Previously validated local layers (source changes are rechecked on preparation):": (
        "Previously validated local layers (source changes are rechecked on preparation):"
    ),
    "Progress saved. You can resume this step later.": (
        "Progress saved. You can resume this step later."
    ),
    "Projection auto needs no CRS choice. Text is inert.": (
        "Projection auto needs no CRS choice. Text is inert."
    ),
    "Projection cannot represent a journey coordinate; choose auto projection.": (
        "Projection cannot represent a journey coordinate; choose auto projection."
    ),
    "Projection produced a non-finite coordinate. Choose auto projection and retry.": (
        "Projection produced a non-finite coordinate. Choose auto projection and retry."
    ),
    (
        "Provider account: https://account.heigit.org/ ; sign in/register yourself, open the "
        "dashboard/API keys, create/copy a key."
    ): (
        "Provider account: https://account.heigit.org/ ; sign in/register yourself, open the "
        "dashboard/API keys, create/copy a key."
    ),
    "Provider destination: ": "Provider destination: ",
    "Provider limits: https://openrouteservice.org/restrictions/": (
        "Provider limits: https://openrouteservice.org/restrictions/"
    ),
    "Put files here:": "Put files here:",
    "Python: ": "Python: ",
    "Ready to export ": "Ready to export ",
    "Recommended Geofabrik country/subcountry extracts: ": (
        "Recommended Geofabrik country/subcountry extracts: "
    ),
    "Recommended Geofabrik country/subcountry regions for these stops: ": (
        "Recommended Geofabrik country/subcountry regions for these stops: "
    ),
    "Remove an assignment": "Remove an assignment",
    "Remove this assignment": "Remove this assignment",
    "Removing this assignment restores any available itinerary or saved route.": (
        "Removing this assignment restores any available itinerary or saved route."
    ),
    "Reorder stops": "Reorder stops",
    "Reorder uses every visit number once; mode changes one connection.": (
        "Reorder stops lets you move one stop before/after another, or to the start/end, "
        "with a preview. Confirm each move, then choose Finish reordering. Mode changes one "
        "connection."
    ),
    "Replace the existing file": "Replace the existing file",
    "Replacement requires a regular existing SVG, not a link/directory.": (
        "Replacement requires a regular existing SVG, not a link/directory."
    ),
    "Request delay must be 0–60 seconds.": "Request delay must be 0–60 seconds.",
    "Request pacing must be 0–60 seconds.": "Request pacing must be 0–60 seconds.",
    (
        "Resolved routes exceed 500,000 total vertices. Use simpler route exports or a "
        "smaller trip; saved successes are preserved."
    ): (
        "Resolved routes exceed 500,000 total vertices. Use simpler route exports or a "
        "smaller trip; saved successes are preserved."
    ),
    "Resume in ": "Resume in ",
    "Resume this step: ": "Resume this step: ",
    "Resume: run the workspace command again and choose this folder.": (
        "Resume: run the workspace command again and choose this folder."
    ),
    "Retry uses existing valid routes/layers; no reacquisition is required.": (
        "Retry uses existing valid routes/layers; no reacquisition is required."
    ),
    "Return to the stop list?": "Return to the stop list?",
    "Returning? Choose the step you want to revisit.": (
        "Returning? Choose the step you want to revisit."
    ),
    "Reused: ": "Reused: ",
    "Reverse the imported line": "Reverse the imported line",
    "Review your itinerary": "Review your itinerary",
    "Roads and water (required):": "Roads and water (required):",
    "Route assignment saved.": "Route assignment saved.",
    "Route endpoints mismatch by more than 5 km. Choose the correct route or segment.": (
        "Route endpoints mismatch by more than 5 km. Choose the correct route or segment."
    ),
    "Route folder scan incomplete. Use a smaller folder and recheck.": (
        "Route folder scan incomplete. Use a smaller folder and recheck."
    ),
    "Route has invalid WGS84 coordinates; export finite longitude/latitude pairs.": (
        "Route has invalid WGS84 coordinates; export finite longitude/latitude pairs."
    ),
    "Route line needs 2–100,000 vertices. Export a smaller valid LineString.": (
        "Route line needs 2–100,000 vertices. Export a smaller valid LineString."
    ),
    "Route record endpoints are stale.": "Route record endpoints are stale.",
    "Route record requires recorded mode and explicit approximation status.": (
        "Route record requires recorded mode and explicit approximation status."
    ),
    "Route source must be recognized.": "Route source must be recognized.",
    "Routes": "Routes",
    "Routes: ": "Routes: ",
    "Routing avoid features: highways, tollways, ferries, fords or steps; no duplicates.": (
        "Routing avoid features: highways, tollways, ferries, fords or steps; no duplicates."
    ),
    "Routing preference must be recommended, fastest or shortest.": (
        "Routing preference must be recommended, fastest or shortest."
    ),
    "Routing profiles must map supported recorded modes to supported profiles.": (
        "Routing profiles must map supported recorded modes to supported profiles."
    ),
    "Routing service finished: ": "Routing service finished: ",
    "SQLite lacks the required memory/schema safeguards.": (
        "SQLite lacks the required memory/schema safeguards."
    ),
    (
        "SVG exceeds 2 GiB. Reduce visible layers/classes; preserve detail rather than "
        "silently simplifying it."
    ): (
        "SVG exceeds 2 GiB. Reduce visible layers/classes; preserve detail rather than "
        "silently simplifying it."
    ),
    "SVG filename in the output folder": "SVG filename in the output folder",
    "SVG: ": "SVG: ",
    "Save and exit": "Save and exit",
    "Saved changes restored.": "Loaded your previously saved itinerary.",
    "Saved route choices are malformed. Repair route-choices.json and recheck.": (
        "Saved route choices are malformed. Repair route-choices.json and recheck."
    ),
    "Scale bar uses 1–20 segments.": "Scale bar uses 1–20 segments.",
    (
        "Scan incomplete: only the first 1,000 entries were checked. Use a smaller folder "
        "for this trip; files not observed cannot be counted as present."
    ): (
        "Scan incomplete: only the first 1,000 entries were checked. Use a smaller folder "
        "for this trip; files not observed cannot be counted as present."
    ),
    "Segments must connect each adjacent ordered visit.": (
        "Segments must connect each adjacent ordered visit."
    ),
    "Select a regular file, not a link or directory.": (
        "Select a regular file, not a link or directory."
    ),
    "Select a stop for details": "Select a stop for details",
    "Select one country boundary source; remove the competing advanced setting or ZIP.": (
        "Select one country boundary source; remove the competing advanced setting or ZIP."
    ),
    "Select the named journey. Ambiguous matches are never assigned automatically:": (
        "Select the named journey. Ambiguous matches are never assigned automatically:"
    ),
    "Send these coordinates to OpenRouteService": "Send these coordinates to OpenRouteService",
    "Sequence metadata must be complete positive integers.": (
        "Sequence metadata must be complete positive integers."
    ),
    "Sequences must be unique and consecutive starting at 1.": (
        "Sequences must be unique and consecutive starting at 1."
    ),
    "Set a connection distance": "Set a connection distance",
    "Set trip duration": "Set trip duration",
    "Single-stop trip has no connection assignments.": (
        "Single-stop trip has no connection assignments."
    ),
    "Some items cannot be imported. Use the supported places or choose another export.": (
        "Some items cannot be imported. Use the supported places or choose another export."
    ),
    (
        "Stage note could not be saved; use the resume command below. Validated prior "
        "results remain."
    ): (
        "Stage note could not be saved; use the resume command below. Validated prior "
        "results remain."
    ),
    "Start another trip: ": "Start another trip: ",
    "Start with country/subcountry extracts for: ": "Start with country/subcountry extracts for: ",
    "State/province borders (optional):": "State/province borders (optional):",
    "State/province borders are optional. Countries, roads and water will still appear.": (
        "State/province borders are optional. Countries, roads and water will still appear."
    ),
    "Step ": "Step ",
    "Still needed: ": "Still needed: ",
    "Stops ": "Stops ",
    (
        "Stops alone cannot prove coverage between them. Include neighboring regions crossed "
        "by the trip; coverage must be checked again after routes are resolved."
    ): (
        "Stops alone cannot prove coverage between them. Include neighboring regions crossed "
        "by the trip; coverage must be checked again after routes are resolved."
    ),
    "Straight lines approximate these connections. Travel distance will be unknown.": (
        "Straight lines approximate these connections. Travel distance will be unknown."
    ),
    "Style changes do not refetch routes. Advanced config.toml remains supported.": (
        "Style changes do not refetch routes. Advanced config.toml remains supported."
    ),
    "Style transport modes": "Style transport modes",
    "Subtitle fields are {total_km} and {total_days}; other text is literal.": (
        "Subtitle fields are {total_km} and {total_days}; other text is literal."
    ),
    "Subtitle: ": "Subtitle: ",
    "Suggested folder: ": "Suggested folder: ",
    "Supported Python versions are 3.12, 3.13 and 3.14.": (
        "Supported Python versions are 3.12, 3.13 and 3.14."
    ),
    "TRAVELMAP": "TRAVELMAP",
    "The input location is no longer a regular workspace folder: ": (
        "The input location is no longer a regular workspace folder: "
    ),
    (
        "The interactive guide explains what to copy and download, then waits for you. You "
        "can also return later using the command below."
    ): (
        "The interactive guide explains what to copy and download, then waits for you. You "
        "can also return later using the command below."
    ),
    "The map data needs updating for this country/layer selection. Returning to Map data.": (
        "The map data needs updating for this country/layer selection. Returning to Map data."
    ),
    (
        "The poster shows complete selected countries, including unvisited regions. Use "
        "Displayed countries to review/change them; extra downloads do not add countries to "
        "the view."
    ): (
        "The poster shows complete selected countries, including unvisited regions. Use "
        "Displayed countries to review/change them; extra downloads do not add countries to "
        "the view."
    ),
    "This check used no routing key, external service or workspace files.": (
        "This check used no routing key, external service or workspace files."
    ),
    "This export contains separate candidate trips. Choose one:": (
        "This export contains separate candidate trips. Choose one:"
    ),
    "This file already exists": "This file already exists",
    "This folder already has content: ": "This folder already has content: ",
    (
        "This line has no plausible itinerary endpoints within 5 km. Choose another "
        "file/line or export the correct route; no assignment changed."
    ): (
        "This line has no plausible itinerary endpoints within 5 km. Choose another "
        "file/line or export the correct route; no assignment changed."
    ),
    "This line runs in reverse. Reverse the imported copy to match your journey.": (
        "This line runs in reverse. Reverse the imported copy to match your journey."
    ),
    "Transport mode: ": "Transport mode: ",
    "Transport: ": "Transport: ",
    "TravelMap ": "TravelMap ",
    "TravelMap installation check": "TravelMap installation check",
    "TravelMap: ": "TravelMap: ",
    (
        "Trip exceeds 1,000 routing connections. Export a smaller trip; existing cached "
        "routes are preserved."
    ): (
        "Trip exceeds 1,000 routing connections. Export a smaller trip; existing cached "
        "routes are preserved."
    ),
    "Trip needs a nonempty title.": "Trip needs a nonempty title.",
    "Trip title": "Trip title",
    "Trip: ": "Trip: ",
    "Try again": "Try again",
    (
        "Type reduced to explicitly omit internal state/province borders, or pause while you "
        "download the optional ZIP."
    ): (
        "Type reduced to explicitly omit internal state/province borders, or pause while you "
        "download the optional ZIP."
    ),
    "Unable to project the selected trip. Choose auto projection and retry.": (
        "Unable to project the selected trip. Choose auto projection and retry."
    ),
    "Unavailable projection. Use auto or a locally supported EPSG/ESRI/PROJ definition.": (
        "Unavailable projection. Use auto or a locally supported EPSG/ESRI/PROJ definition."
    ),
    "Unexpected map cache schema; rebuild this cache.": (
        "Unexpected map cache schema; rebuild this cache."
    ),
    "Unknown displayed countries: ": "Unknown displayed countries: ",
    "Unresolved ": "Unresolved ",
    "Unsafe XML declaration. Export KML without DOCTYPE or ENTITY.": (
        "Unsafe XML declaration. Export KML without DOCTYPE or ENTITY."
    ),
    "Unsafe archive entry ": "Unsafe archive entry ",
    "Unsafe archive path ": "Unsafe archive path ",
    "Unsafe map cache directory.": "Unsafe map cache directory.",
    (
        "Unsupported CRS. Re-export WGS84 longitude/latitude GeoJSON; do not swap coordinate order."
    ): (
        "Unsupported CRS. Re-export WGS84 longitude/latitude GeoJSON; do not swap coordinate order."
    ),
    "Unsupported GeoJSON schema version: ": "Unsupported GeoJSON schema version: ",
    "Unsupported map cache schema/version.": "Unsupported map cache schema/version.",
    "Unsupported map layer.": "Unsupported map layer.",
    "Unsupported placemarks: ": "Unsupported placemarks: ",
    "Unsupported prepared geometry; recheck map data.": (
        "Unsupported prepared geometry; recheck map data."
    ),
    "Unsupported route record version.": "Unsupported route record version.",
    "Unsupported transport mode ": "Unsupported transport mode ",
    "Unsupported water geometry for simplification.": (
        "Unsupported water geometry for simplification."
    ),
    "Unsupported water member role; correct the relation.": (
        "Unsupported water member role; correct the relation."
    ),
    "Use a .kml file, not a compressed .kmz. Keep the original as a backup.": (
        "Use a .kml file, not a compressed .kmz. Keep the original as a backup."
    ),
    "Use a line from the itinerary": "Use a line from the itinerary",
    (
        "Use a location with space for your regional map downloads. You can return to this "
        "folder for another session."
    ): (
        "Use a location with space for your regional map downloads. You can return to this "
        "folder for another session."
    ),
    "Use country/regional extracts; large continent files are unsupported.": (
        "Use country/regional extracts; large continent files are unsupported."
    ),
    "Use straight lines for these connections": "Use straight lines for these connections",
    "Use ↑/↓, then Enter.": "Use ↑/↓, then Enter.",
    "View stops and connections": "View stops and connections",
    "View stops shows your stops in order; select one for details.": (
        "View stops shows your stops in order; select one for details."
    ),
    "View trip stops": "View trip stops",
    "Visit numbers in new order, separated by spaces": (
        "Visit numbers in new order, separated by spaces"
    ),
    "Walking approximation": "Walking approximation",
    "Water area filtering requires polygon geometry.": (
        "Water area filtering requires polygon geometry."
    ),
    "Water member rings are incomplete; use a complete extract.": (
        "Water member rings are incomplete; use a complete extract."
    ),
    "Water relation dependency record is missing.": "Water relation dependency record is missing.",
    "Water relation exceeds one million member vertices.": (
        "Water relation exceeds one million member vertices."
    ),
    "Water relation has no outer ring or exceeds vertex limits.": (
        "Water relation has no outer ring or exceeds vertex limits."
    ),
    "Water repair produced non-polygon remnants; correct the source to preserve all detail.": (
        "Water repair produced non-polygon remnants; correct the source to preserve all detail."
    ),
    "Water simplification cannot retain this feature; disable it and retry.": (
        "Water simplification cannot retain this feature; disable it and retry."
    ),
    "Water simplification changed line components; disable it.": (
        "Water simplification changed line components; disable it."
    ),
    "Water simplification changed polygon components/holes; disable it.": (
        "Water simplification changed polygon components/holes; disable it."
    ),
    "Water simplification tolerance must be >0 and <=1 mm.": (
        "Water simplification tolerance must be >0 and <=1 mm."
    ),
    (
        "Water simplification uses millimetres on the finished page, preserves polygon "
        "topology and keeps original cached geometry. Turn it off for full detail."
    ): (
        "Water simplification uses millimetres on the finished page, preserves polygon "
        "topology and keeps original cached geometry. Turn it off for full detail."
    ),
    "Water way has no complete outer ring.": "Water way has no complete outer ring.",
    "Welcome to TravelMap's guided poster workflow.": (
        "Welcome to TravelMap's guided poster workflow."
    ),
    "What would you like to do?": "What would you like to do?",
    "Where would you like to start?": "Where would you like to start?",
    "Which connection?": "Which connection?",
    "Which itinerary file should I import?": "Which itinerary file should I import?",
    "Which manual assignment should be removed?": "Which manual assignment should be removed?",
    "Which routes should the routing service find?": (
        "Which routes should the routing service find?"
    ),
    "Workspace": "Workspace",
    "Workspace commands are available.": "Workspace commands are available.",
    "Workspace folder path": "Workspace folder path",
    "Workspace operation failed: ": "Workspace operation failed: ",
    "Workspace ready.": "Workspace ready.",
    (
        "Workspace status: incomplete; missing {0}. Use workspace setup to create the "
        "missing folders."
    ): (
        "Workspace status: incomplete; missing {0}. Use workspace setup to create the "
        "missing folders."
    ),
    "Workspace status: needs repair: ": "Workspace status: needs repair: ",
    "Workspace status: ready": "Workspace status: ready",
    "Workspace status: unmarked; this read-only check has not adopted it": (
        "Workspace status: unmarked; this read-only check has not adopted it"
    ),
    "Workspace: ": "Workspace: ",
    "XML exceeds depth 32 or 50,000 elements. Export a smaller trip.": (
        "XML exceeds depth 32 or 50,000 elements. Export a smaller trip."
    ),
    "You can review the stops and transport modes before accepting.": (
        "You can review the stops and transport modes before accepting."
    ),
    "Your existing files are kept. Setup creates only the named TravelMap folders.": (
        "Your existing files are kept. Setup creates only the named TravelMap folders."
    ),
    "Your itinerary": "Your itinerary",
    "Your trip has ": "Your trip has ",
    "ZIP must contain one supported Natural Earth ": (
        "ZIP must contain one supported Natural Earth "
    ),
    "a command argument contains an unsupported control character": (
        "a command argument contains an unsupported control character"
    ),
    "a conflicting workspace marker appeared at ": "a conflicting workspace marker appeared at ",
    "accept": "accept",
    "activity": "activity",
    "all": "all",
    "another": "another",
    "approximate": "approximate",
    "arrival_date": "arrival_date",
    "assign": "assign",
    "auth": "auth",
    "back": "back",
    "cannot create ": "cannot create ",
    "cannot create workspace ": "cannot create workspace ",
    "cannot inspect ": "cannot inspect ",
    "cannot read workspace marker: ": "cannot read workspace marker: ",
    "cannot remove owned workspace check ": "cannot remove owned workspace check ",
    "cannot write workspace folder ": "cannot write workspace folder ",
    "change": "change",
    "config.toml exceeds 1 MiB.": "config.toml exceeds 1 MiB.",
    "config.toml: ": "config.toml: ",
    "connection": "connection",
    "coordinates": "coordinates",
    "could not load configuration ": "could not load configuration ",
    "could not resolve workspace path: ": "could not resolve workspace path: ",
    (
        "could not safely publish the workspace marker; this filesystem may not support "
        "no-overwrite links. Choose a supported local NTFS, APFS or ext4 folder, or retry "
        "after repair. Details: "
    ): (
        "could not safely publish the workspace marker; this filesystem may not support "
        "no-overwrite links. Choose a supported local NTFS, APFS or ext4 folder, or retry "
        "after repair. Details: "
    ),
    "count": "count",
    "countries": "countries",
    "country": "country",
    "customize": "customize",
    "days": "days",
    "destination": "destination",
    "destination_id": "destination_id",
    "direct": "direct",
    "distance override segment sequences must be positive": (
        "distance override segment sequences must be positive"
    ),
    "distance overrides must be positive finite kilometres": (
        "distance overrides must be positive finite kilometres"
    ),
    "distance_m": "distance_m",
    "done": "done",
    "embedded": "embedded",
    "enabled": "enabled",
    "enabled_layers must select roads, water_lines or water_areas.": (
        "enabled_layers must select roads, water_lines or water_areas."
    ),
    "export": "export",
    "filename": "filename",
    "filter": "filter",
    "g": "g",
    "height_mm": "height_mm",
    "help": "help",
    "id": "id",
    "inspect": "inspect",
    "invalid": "invalid",
    "invalid configuration ": "invalid configuration ",
    "invalid sequence": "invalid sequence",
    "keep": "keep",
    "kilometres": "kilometres",
    "label": "label",
    "length": "length",
    "map": "map",
    "map-settings.json: ": "map-settings.json: ",
    "map-settings.json: use schema_version 1.": "map-settings.json: use schema_version 1.",
    "map-settings.json: vectors must contain at most 16 local sources.": (
        "map-settings.json: vectors must contain at most 16 local sources."
    ),
    "margin_mm": "margin_mm",
    "menu": "menu",
    "metadata": "metadata",
    "mode": "mode",
    "mode-style": "mode-style",
    "must be a six-digit hexadecimal color": "must be a six-digit hexadecimal color",
    "name": "name",
    "new": "new",
    "none": "none",
    "notes": "notes",
    "open-output": "open-output",
    "orientation": "orientation",
    "origin": "origin",
    "origin_id": "origin_id",
    "osm:relation:": "osm:relation:",
    "pause": "pause",
    "phase": "phase",
    "processing": "processing",
    "projection": "projection",
    "properties": "properties",
    "recheck": "recheck",
    "reduced": "reduced",
    "remove": "remove",
    "reorder": "reorder",
    "replace": "replace",
    "reverse": "reverse",
    "roads": "roads",
    "route_colors entries must be six-digit hexadecimal colors": (
        "route_colors entries must be six-digit hexadecimal colors"
    ),
    "route_colors must be unique": "route_colors must be unique",
    "route_colors_by_mode keys must not be empty": "route_colors_by_mode keys must not be empty",
    "route_colors_by_mode values must be six-digit hexadecimal colors": (
        "route_colors_by_mode values must be six-digit hexadecimal colors"
    ),
    "routing avoid features must be unique": "routing avoid features must be unique",
    "routing modes must be unique": "routing modes must be unique",
    "run": "run",
    "send": "send",
    "sequence": "sequence",
    "settings": "settings",
    "show_place_labels": "show_place_labels",
    "show_stop_markers": "show_stop_markers",
    "skip": "skip",
    "source": "source",
    "stops": "stops",
    "supported": "supported",
    "title": "title",
    "transport_mode": "transport_mode",
    "travelmap": "travelmap",
    "type": "type",
    "unsupported routing avoid features: ": "unsupported routing avoid features: ",
    "unsupported shell: ": "unsupported shell: ",
    "water": "water",
    "width_mm": "width_mm",
    (
        "workspace contains unrelated files; inspect it and explicitly choose adopt existing "
        "before adding TravelMap folders: "
    ): (
        "workspace contains unrelated files; inspect it and explicitly choose adopt existing "
        "before adding TravelMap folders: "
    ),
    "workspace entry is not a safe folder: ": "workspace entry is not a safe folder: ",
    "workspace folder is missing: ": "workspace folder is missing: ",
    "workspace marker exceeds the 64 KiB size limit": (
        "workspace marker exceeds the 64 KiB size limit"
    ),
    "workspace marker is not a supported TravelMap layout: ": (
        "workspace marker is not a supported TravelMap layout: "
    ),
    "workspace marker is not supported: ": "workspace marker is not supported: ",
    "workspace marker is not valid UTF-8 JSON": "workspace marker is not valid UTF-8 JSON",
    "workspace marker must be a regular file": "workspace marker must be a regular file",
    "workspace marker was not complete after publication": (
        "workspace marker was not complete after publication"
    ),
    "workspace path contains a Windows-reserved name or character; choose another folder": (
        "workspace path contains a Windows-reserved name or character; choose another folder"
    ),
    "workspace path contains a control or invisible character; choose a printable path": (
        "workspace path contains a control or invisible character; choose a printable path"
    ),
    "workspace path is empty; choose a folder path": (
        "workspace path is empty; choose a folder path"
    ),
    "–": "–",
    "—": "—",
    "Step {step} / {total} · {name}": "Step {step} / {total} · {name}",
    "Previous: {previous}   |   Next: {following}": "Previous: {previous}   |   Next: {following}",
    "{minutes}m{seconds:02d}s | {message}": "{minutes}m{seconds:02d}s | {message}",
    "{minutes}m {seconds:02d}s elapsed | {message} | Ctrl+C to pause": (
        "{minutes}m {seconds:02d}s elapsed | {message} | Ctrl+C to pause"
    ),
    "{0}: {1}: {2}": "{0}: {1}: {2}",
    "{0}/{1}: missing CRS. Re-export with explicit CRS metadata; do not guess it.": (
        "{0}/{1}: missing CRS. Re-export with explicit CRS metadata; do not guess it."
    ),
    "{0}: missing boundary name column ({1}). Select compatible vectors.": (
        "{0}: missing boundary name column ({1}). Select compatible vectors."
    ),
    "{0}: missing {1} field in {2}. Select a compatible named layer.": (
        "{0}: missing {1} field in {2}. Select a compatible named layer."
    ),
    "{0}: feature {1} has no geometry.": "{0}: feature {1} has no geometry.",
    "{0}: feature {1} has an empty boundary name.": "{0}: feature {1} has an empty boundary name.",
    "{0}/{1}: unreadable vector/CRS transformation: {2}. Select compatible local data.": (
        "{0}/{1}: unreadable vector/CRS transformation: {2}. Select compatible local data."
    ),
    "{0}: history PBFs are unsupported; select a current snapshot.": (
        "{0}: history PBFs are unsupported; select a current snapshot."
    ),
    "{0}: unreadable PBF header: {1}. Select a complete regional snapshot.": (
        "{0}: unreadable PBF header: {1}. Select a complete regional snapshot."
    ),
    "{0}: node {1} has invalid coordinates.": "{0}: node {1} has invalid coordinates.",
    "{0}: raw entity exceeds one million references.": (
        "{0}: raw entity exceeds one million references."
    ),
    "{0}: way exceeds one million vertices.": "{0}: way exceeds one million vertices.",
    "{0}: {1} has missing nodes/invalid geometry; select a complete extract.": (
        "{0}: {1} has missing nodes/invalid geometry; select a complete extract."
    ),
    "{0}: {1}: water assembly failed: {2}": "{0}: {1}: water assembly failed: {2}",
    "{0}: PBF processing failed: {1}. Check the affected entity/input and retry.": (
        "{0}: PBF processing failed: {1}. Check the affected entity/input and retry."
    ),
    "{0}: missing source entity ledger.": "{0}: missing source entity ledger.",
    "{0}: invalid selected boundary geometry; select compatible boundaries.": (
        "{0}: invalid selected boundary geometry; select compatible boundaries."
    ),
    "osm:relation:{0}: too many water members.": "osm:relation:{0}: too many water members.",
    "{0}: skipped water polygons with nested relations ({1} total, first osm:relation:{2}).": (
        "{0}: skipped water polygons with nested relations ({1} total, first osm:relation:{2})."
    ),
    "Missing water member osm:way:{0}; use a complete extract.": (
        "Missing water member osm:way:{0}; use a complete extract."
    ),
    "{0}: physical size must be at most 50 mm.": "{0}: physical size must be at most 50 mm.",
    (
        "{0}: use plain font-family names, letters/numbers/spaces/hyphens/commas; no markup "
        "or resources."
    ): (
        "{0}: use plain font-family names, letters/numbers/spaces/hyphens/commas; no markup "
        "or resources."
    ),
    "{0}: use a portable workspace-relative file path.": (
        "{0}: use a portable workspace-relative file path."
    ),
    "{0}: use workspace-relative file paths.": "{0}: use workspace-relative file paths.",
    (
        "config.toml: {0}. Repair that field or remove the optional TOML to use "
        "saved/default settings."
    ): (
        "config.toml: {0}. Repair that field or remove the optional TOML to use "
        "saved/default settings."
    ),
    (
        "Country filter hides background land around {0} visits and {1} connections. "
        "Visits/routes remain visible and are never removed from the journey."
    ): (
        "Country filter hides background land around {0} visits and {1} connections. "
        "Visits/routes remain visible and are never removed from the journey."
    ),
    "{0} = {1}": "{0} = {1}",
    "Poster title: {0}. Page: {1} × {2} mm, {3}, margins {4} mm. Projection: {5}.": (
        "Poster title: {0}. Page: {1} × {2} mm, {3}, margins {4} mm. Projection: {5}."
    ),
    "Ready to export {0} ({1} × {2} mm {3}).": "Ready to export {0} ({1} × {2} mm {3}).",
    "Output: {0}; resolved sources: {1}; approximate routes: {2}.": (
        "Output: {0}; resolved sources: {1}; approximate routes: {2}."
    ),
    ("Exporting poster {0} of {1} (route color {2}); originals and prior artwork are protected."): (
        "Exporting poster {0} of {1} (route color {2}); originals and prior artwork are protected."
    ),
    "{0}: expected a regular local file.": "{0}: expected a regular local file.",
    "{0}: exceeds the {1} MiB limit.": "{0}: exceeds the {1} MiB limit.",
    "{0}: expected a JSON object.": "{0}: expected a JSON object.",
    "{0}: {1}. Repair the local file and recheck.": "{0}: {1}. Repair the local file and recheck.",
    "Cannot save {0}: {1}. Check disk space/permissions and retry.": (
        "Cannot save {0}: {1}. Check disk space/permissions and retry."
    ),
    "{0}: select a regular local file, not a link.": (
        "{0}: select a regular local file, not a link."
    ),
    (
        "{0}: exceeds {1} MiB. Use smaller country/subcountry extracts or fewer optional "
        "layers; planet extracts are unsupported."
    ): (
        "{0}: exceeds {1} MiB. Use smaller country/subcountry extracts or fewer optional "
        "layers; planet extracts are unsupported."
    ),
    "{0}: HTML page, not map data. Download the actual ZIP or .osm.pbf dataset and recheck.": (
        "{0}: HTML page, not map data. Download the actual ZIP or .osm.pbf dataset and recheck."
    ),
    "{0}: size limit exceeded. Choose a smaller extract.": (
        "{0}: size limit exceeded. Choose a smaller extract."
    ),
    "{0}: cannot read data: {1}. Check permissions/re-download and recheck.": (
        "{0}: cannot read data: {1}. Check permissions/re-download and recheck."
    ),
    "{0}: file changed while hashing; retry.": "{0}: file changed while hashing; retry.",
    "Unsafe archive entry {0}. Re-download the official ZIP.": (
        "Unsafe archive entry {0}. Re-download the official ZIP."
    ),
    "Unsafe archive path {0}. Re-download the official ZIP.": (
        "Unsafe archive path {0}. Re-download the official ZIP."
    ),
    "Colliding archive entries: {0}. Re-download the official ZIP.": (
        "Colliding archive entries: {0}. Re-download the official ZIP."
    ),
    (
        "ZIP must contain one supported Natural Earth {0} shapefile. Re-download the correct "
        "polygon archive."
    ): (
        "ZIP must contain one supported Natural Earth {0} shapefile. Re-download the correct "
        "polygon archive."
    ),
    "{0}: missing companions {1}. Re-download the full archive; CRS will not be guessed.": (
        "{0}: missing companions {1}. Re-download the full archive; CRS will not be guessed."
    ),
    "{0}: incomplete/unreadable boundary archive: {1}. Re-download and recheck.": (
        "{0}: incomplete/unreadable boundary archive: {1}. Re-download and recheck."
    ),
    "map-settings.json: {0} must contain at most 64 nonempty class names.": (
        "map-settings.json: {0} must contain at most 64 nonempty class names."
    ),
    "Advanced vector {0} must be bounded text.": "Advanced vector {0} must be bounded text.",
    "{0}: planet extracts are unsupported. Download country/subcountry PBFs.": (
        "{0}: planet extracts are unsupported. Download country/subcountry PBFs."
    ),
    "{0}: supported advanced vectors are SHP, GPKG or GeoJSON.": (
        "{0}: supported advanced vectors are SHP, GPKG or GeoJSON."
    ),
    "{0} Validated prior results are preserved; correct the stated cause and retry.": (
        "{0} Validated prior results are preserved; correct the stated cause and retry."
    ),
    "{0}: changed during preparation. Recheck after copying finishes.": (
        "{0}: changed during preparation. Recheck after copying finishes."
    ),
    "{0}: prepared integrity check failed. Recheck.": (
        "{0}: prepared integrity check failed. Recheck."
    ),
    "{0}: invalid selected boundary geometry; recheck compatible map data.": (
        "{0}: invalid selected boundary geometry; recheck compatible map data."
    ),
    "{0}: invalid country boundary; select compatible data.": (
        "{0}: invalid country boundary; select compatible data."
    ),
    "Coverage incomplete: {0}: country boundary does not cover stop.": (
        "Coverage incomplete: {0}: country boundary does not cover stop."
    ),
    "{0}: invalid selected country geometry; select compatible data.": (
        "{0}: invalid selected country geometry; select compatible data."
    ),
    "{0}: {1}": "{0}: {1}",
    "{0}: output exists. Choose a new name or explicitly confirm replacement.": (
        "{0}: output exists. Choose a new name or explicitly confirm replacement."
    ),
    (
        "Cannot write {0}: {1}. Check folder permissions/disk space, choose another "
        "destination, or pause."
    ): (
        "Cannot write {0}: {1}. Check folder permissions/disk space, choose another "
        "destination, or pause."
    ),
    "{0}: {1} usable cached features.": "{0}: {1} usable cached features.",
    "Your trip has {0} stops. Choose View trip stops to see them.": (
        "Your trip has {0} stops. Choose View trip stops to see them."
    ),
    (
        "{0} / {1}: worker resident memory exceeds 3 GiB. Reduce selected classes or use a "
        "machine with the documented resources; valid downloads need no re-download."
    ): (
        "{0} / {1}: map preparation exceeded the 3 GiB memory safety limit. Enable fewer map "
        "classes in config.toml and retry. Valid downloads can be reused."
    ),
    (
        "{0} / {1}: preparation staging exceeds 16 GiB. Free workspace disk or reduce "
        "selected classes; no re-download is needed."
    ): (
        "{0} / {1}: temporary map data exceeded the 16 GiB safety limit. Enable fewer map "
        "classes in config.toml and retry. Valid downloads can be reused."
    ),
    "unsupported shell: {0}": "unsupported shell: {0}",
    "\u001b[{0}A": "\u001b[{0}A",
    "{0}. {1}{2}": "{0}. {1}{2}",
    "Choose a number from 1 to {0}.": "Choose a number from 1 to {0}.",
    "{0}: cannot read file: {1}. Check permissions and recheck.": (
        "{0}: cannot read file: {1}. Check permissions and recheck."
    ),
    "{0}: exceeds 8 MiB. Export a smaller trip and recheck.": (
        "{0}: exceeds 8 MiB. Export a smaller trip and recheck."
    ),
    "Duplicate JSON field {0}. Correct the export.": (
        "Duplicate JSON field {0}. Correct the export."
    ),
    "{0}: more than 10,000 vertices. Export a simpler line.": (
        "{0}: more than 10,000 vertices. Export a simpler line."
    ),
    "{0}: invalid coordinates: {1}. Correct and recheck.": (
        "{0}: invalid coordinates: {1}. Correct and recheck."
    ),
    "{0}: expected one stop Point coordinate.": "{0}: expected one stop Point coordinate.",
    "{0}: a line needs at least two vertices.": "{0}: a line needs at least two vertices.",
    "Unsupported GeoJSON schema version: {0}. Use schema version 1.": (
        "Unsupported GeoJSON schema version: {0}. Use schema version 1."
    ),
    "Feature {0}: expected Feature object.": "Feature {0}: expected Feature object.",
    "Feature {0}: missing properties or geometry.": "Feature {0}: missing properties or geometry.",
    "Feature {0}: missing {1}. Correct and recheck.": (
        "Feature {0}: missing {1}. Correct and recheck."
    ),
    "Feature {0}: label priority must be a nonnegative integer.": (
        "Feature {0}: label priority must be a nonnegative integer."
    ),
    "Feature {0}: line needs 2–10,000 vertices.": "Feature {0}: line needs 2–10,000 vertices.",
    "Feature {0}: unsupported geometry or feature_type.": (
        "Feature {0}: unsupported geometry or feature_type."
    ),
    "Unsupported transport mode {0}. Choose {1}.": "Unsupported transport mode {0}. Choose {1}.",
    "{0}: {1}. Correct the export, choose another file, or recheck.": (
        "{0}: {1}. Correct the export, choose another file, or recheck."
    ),
    "Cannot save {0}: {1}. Check disk space and permissions; retry.": (
        "Cannot save {0}: {1}. Check disk space and permissions; retry."
    ),
    "TravelMap {0}": "TravelMap {0}",
    "Python: {0} ({1})": "Python: {0} ({1})",
    "TravelMap: {0}": "TravelMap: {0}",
    "Workspace operation failed: {0}": "Workspace operation failed: {0}",
    "workspace marker is not supported: {0}": "workspace marker is not supported: {0}",
    "Suggested folder: {0}": "Suggested folder: {0}",
    "This folder already has content: {0}": "This folder already has content: {0}",
    "Workspace: {0}": "Workspace: {0}",
    "Workspace status: needs repair: {0}": "Workspace status: needs repair: {0}",
    "{0}: checked {1} entries; found {2} matching files": (
        "{0}: checked {1} entries; found {2} matching files"
    ),
    "  {0}": "  {0}",
    "  {0}: {1}": "  {0}: {1}",
    "Resume in {0}: {1}": "Resume in {0}: {1}",
    "{0}: expected a regular map cache.": "{0}: expected a regular map cache.",
    "{0}: map cache exceeds 8 GiB.": "{0}: map cache exceeds 8 GiB.",
    "Invalid/empty {0} geometry type.": "Invalid/empty {0} geometry type.",
    "{0}: exceeds one million vertices per feature.": (
        "{0}: exceeds one million vertices per feature."
    ),
    "{0}: non-finite or out-of-range WGS84 coordinates.": (
        "{0}: non-finite or out-of-range WGS84 coordinates."
    ),
    "Invalid {0} geometry.": "Invalid {0} geometry.",
    "{0}: conflicting same-version objects; use current snapshot extracts.": (
        "{0}: conflicting same-version objects; use current snapshot extracts."
    ),
    "{0}: serialized feature exceeds supported size.": (
        "{0}: serialized feature exceeds supported size."
    ),
    "Feature {0}: expected GeoJSON Feature.": "Feature {0}: expected GeoJSON Feature.",
    "Feature {0}: missing geometry/properties.": "Feature {0}: missing geometry/properties.",
    "Feature {0}: unsupported {1}; export separate LineStrings.": (
        "Feature {0}: unsupported {1}; export separate LineStrings."
    ),
    "{0}: invalid route export: {1}. Re-export a supported local file and recheck.": (
        "{0}: invalid route export: {1}. Re-export a supported local file and recheck."
    ),
    ("{0} validated Point markers are not route lines; {1} line candidates retained separately."): (
        "{0} validated Point markers are not route lines; {1} line candidates retained separately."
    ),
    "{0}: {1} -> {2}, {3} vertices": "{0}: {1} -> {2}, {3} vertices",
    (
        "Assign {0} / {1} to {2}; prior source: {3}. Manual geometry takes precedence; "
        "poster/distance refresh, unrelated routes remain. Distance: {4} metres (None means "
        "unknown)."
    ): (
        "Assign {0} / {1} to {2}; prior source: {3}. Manual geometry takes precedence; "
        "poster/distance refresh, unrelated routes remain. Distance: {4} metres (None means "
        "unknown)."
    ),
    "Cannot check {0}: {1}. Check folder permissions, then retry.": (
        "Cannot check {0}: {1}. Check folder permissions, then retry."
    ),
    "Routes: {0} total, {1} ready, {2} open.": "Routes: {0} total, {1} ready, {2} open.",
    "{0} saved route entries need rechecking.": "{0} saved route entries need rechecking.",
    "Previously not found by the service: {0} open routes.": (
        "Previously not found by the service: {0} open routes."
    ),
    ": sends {0} using {1}; recorded mode is unchanged.": (
        ": sends {0} using {1}; recorded mode is unchanged."
    ),
    "Routing service finished: {0} routes saved; {1} remain open.": (
        "Routing service finished: {0} routes saved; {1} remain open."
    ),
    "{0}. {1}": "{0}. {1}",
    "Trip: {0}": "Trip: {0}",
    "{0} stops; {1} connections; first: {2}; last: {3}": (
        "{0} stops; {1} connections; first: {2}; last: {3}"
    ),
    "{0} ({1})": "{0} ({1})",
    "Stops {0}–{1} of {2} · {3}": "Stops {0}–{1} of {2} · {3}",
    "Location: {0}, {1} (latitude, longitude)": "Location: {0}, {1} (latitude, longitude)",
    "Connection {0}": "Connection {0}",
    "{0} route keys affected by this correction. Poster output will need refreshing.": (
        "{0} route keys affected by this correction. Poster output will need refreshing."
    ),
    "cannot create workspace {0}: {1}": "cannot create workspace {0}: {1}",
    "workspace marker is not a supported TravelMap layout: {0}": (
        "workspace marker is not a supported TravelMap layout: {0}"
    ),
    (
        "workspace contains unrelated files; inspect it and explicitly choose adopt existing "
        "before adding TravelMap folders: {0}"
    ): (
        "workspace contains unrelated files; inspect it and explicitly choose adopt existing "
        "before adding TravelMap folders: {0}"
    ),
    "cannot create {0} folder at {1}: {2}": "cannot create {0} folder at {1}: {2}",
    "a conflicting workspace marker appeared at {0}": (
        "a conflicting workspace marker appeared at {0}"
    ),
    (
        "could not safely publish the workspace marker; this filesystem may not support "
        "no-overwrite links. Choose a supported local NTFS, APFS or ext4 folder, or retry "
        "after repair. Details: {0}"
    ): (
        "could not safely publish the workspace marker; this filesystem may not support "
        "no-overwrite links. Choose a supported local NTFS, APFS or ext4 folder, or retry "
        "after repair. Details: {0}"
    ),
    "could not resolve workspace path: {0}": "could not resolve workspace path: {0}",
    "cannot read workspace marker: {0}": "cannot read workspace marker: {0}",
    "cannot inspect {0}: {1}": "cannot inspect {0}: {1}",
    "workspace entry is not a safe folder: {0}": "workspace entry is not a safe folder: {0}",
    "workspace folder is missing: {0}": "workspace folder is missing: {0}",
    "cannot write workspace folder {0}: {1}": "cannot write workspace folder {0}: {1}",
    "cannot remove owned workspace check {0}: {1}": "cannot remove owned workspace check {0}: {1}",
    "unsupported routing avoid features: {0}": "unsupported routing avoid features: {0}",
    "could not load configuration {0}: {1}": "could not load configuration {0}: {1}",
    "invalid configuration {0}: {1}": "invalid configuration {0}: {1}",
    "Back to export": "Back to export",
    "Choices cleared. Missing routes can now be acquired or supplied locally.": (
        "Choices cleared. Missing routes can now be acquired or supplied locally."
    ),
    "Choose Continue without state/province borders, Help, Back, or Save and exit.": (
        "Choose Continue without state/province borders, Help, Back, or Save and exit."
    ),
    "Choose Continue, Review/undo straight-line choices, Back, or Save and exit.": (
        "Choose Continue, Review/undo straight-line choices, Back, or Save and exit."
    ),
    "Choose a displayed country or action.": "Choose a displayed country or action.",
    "Choose a folder to open, or a new folder to create. A new location will be confirmed.": (
        "Choose a folder to open, or a new folder to create. A new location will be confirmed."
    ),
    "Choose a plain .svg filename, for example my-trip.svg, without a folder path.": (
        "Choose a plain .svg filename, for example my-trip.svg, without a folder path."
    ),
    "Choose displayed countries": "Choose displayed countries",
    "Choose one of the displayed numbers, back, or pause.": (
        "Choose one of the displayed numbers, back, or pause."
    ),
    "Comma-separated country codes/identities, or clear. Map data offers selection by name.": (
        "Comma-separated country codes/identities, or clear. Map data offers selection by name."
    ),
    "Comma-separated values. Type clear for an empty list.": (
        "Comma-separated values. Type clear for an empty list."
    ),
    "Connection distances": "Connection distances",
    "Current {0}: {1}": "Current {0}: {1}",
    "Download the Admin 1 states/provinces polygon ZIP and keep it intact:": (
        "Download the Admin 1 states/provinces polygon ZIP and keep it intact:"
    ),
    "Enter a filename such as my-trip.svg. Back cancels this edit.": (
        "Enter a filename such as my-trip.svg. Back cancels this edit."
    ),
    "Enter connection numbers separated by spaces, or all": (
        "Enter connection numbers separated by spaces, or all"
    ),
    "Enter text. Type clear for an empty value.": "Enter text. Type clear for an empty value.",
    "Enter yes or no.": "Enter yes or no.",
    "Enter: return · keep open while working": "Enter: return · keep open while working",
    (
        "Export WGS84 GeoJSON from your recorder or route planner, copy it into the folder "
        "above, then choose Choose a route file."
    ): (
        "Export WGS84 GeoJSON from your recorder or route planner, copy it into the folder "
        "above, then choose Choose a route file."
    ),
    "Info {0}/{1} · PgUp/PgDn · i: full info": "Info {0}/{1} · PgUp/PgDn · i: full info",
    "Input instructions": "Input instructions",
    "Installed font names; example: Georgia, serif.": (
        "Installed font names; example: Georgia, serif."
    ),
    "Margin in mm: at least 0 and below {0}; leave room for the title and map.": (
        "Margin in mm: at least 0 and below {0}; leave room for the title and map."
    ),
    "Nearby merging approximates route shape within the page tolerance.": (
        "Nearby merging approximates route shape within the page tolerance."
    ),
    "New workspace folder: {0}": "New workspace folder: {0}",
    "Optional borders add state/province outlines inside each country.": (
        "Optional borders add state/province outlines inside each country."
    ),
    "Options {0}–{1}/{2}{3}{4}": "Options {0}–{1}/{2}{3}{4}",
    "Output: {0}": "Output: {0}",
    "Page size: 50–2,000 mm. Example: 594.": "Page size: 50–2,000 mm. Example: 594.",
    "Page {0}/{1} · ↑/↓: pages": "Page {0}/{1} · ↑/↓: pages",
    "Paused. No folder was created.": "Paused. No folder was created.",
    "Returned to export. Prior artwork is preserved.": (
        "Returned to export. Prior artwork is preserved."
    ),
    "Search part of a country name (empty shows all)": (
        "Search part of a country name (empty shows all)"
    ),
    "Search: {0}; {1} matches. Search with an empty value shows all.": (
        "Search: {0}; {1} matches. Search with an empty value shows all."
    ),
    "Select at least one country, or go Back without changes.": (
        "Select at least one country, or go Back without changes."
    ),
    "Selected option": "Selected option",
    "Six-digit hexadecimal color; example: #A33F35.": (
        "Six-digit hexadecimal color; example: #A33F35."
    ),
    "Square kilometres; 0 keeps all water areas. Water lines are unaffected.": (
        "Square kilometres; 0 keeps all water areas. Water lines are unaffected."
    ),
    "Task information": "Task information",
    "Text with optional {total_km} and {total_days} fields. Type clear to omit it.": (
        "Text with optional {total_km} and {total_days} fields. Type clear to omit it."
    ),
    "That filename already exists. Choose a different name, or go Back.": (
        "That filename already exists. Choose a different name, or go Back."
    ),
    "Then choose Check for the optional download, or Continue without borders.": (
        "Then choose Check for the optional download, or Continue without borders."
    ),
    "Undo straight-line choices for {0} connections.": (
        "Undo straight-line choices for {0} connections."
    ),
    "Use auto, or a locally supported projection such as EPSG:3857.": (
        "Use auto, or a locally supported projection such as EPSG:3857."
    ),
    "Use selected countries applies changes. Back or exit discards this selection edit.": (
        "Use selected countries applies changes. Back or exit discards this selection edit."
    ),
    "Use straight lines for {0} connections:": "Use straight lines for {0} connections:",
    "Use visit numbers separated by spaces, for example 2 1 3.": (
        "Use visit numbers separated by spaces, for example 2 1 3."
    ),
    "Use ↑/↓, then Enter. d: full choice": "Use ↑/↓, then Enter. d: full choice",
    "Valid saved service routes and local assignments are kept and checked again.": (
        "Valid saved service routes and local assignments are kept and checked again."
    ),
    "View connection distances": "View connection distances",
    "Water simplification preserves topology and original cached geometry.": (
        "Water simplification preserves topology and original cached geometry."
    ),
    "Without them, countries, roads, water and journey routes still appear.": (
        "Without them, countries, roads, water and journey routes still appear."
    ),
    "Workspace-relative local paths; lists use commas. Type clear to remove.": (
        "Workspace-relative local paths; lists use commas. Type clear to remove."
    ),
    (
        "map.routing.unreachable is set to direct. Confirm before replacing unfound routes "
        "with straight lines; distances remain unknown."
    ): (
        "map.routing.unreachable is set to direct. Confirm before replacing unfound routes "
        "with straight lines; distances remain unknown."
    ),
    "{0} connections need updated routes after this correction.": (
        "{0} connections need updated routes after this correction."
    ),
    "{0} countries selected. Choose a country to toggle it.": (
        "{0} countries selected. Choose a country to toggle it."
    ),
    "{0} route(s) skipped because their recorded mode is not enabled in map.routing.modes.": (
        "{0} route(s) skipped because their recorded mode is not enabled in map.routing.modes."
    ),
    "{0} routes use approximate straight lines; distance is unknown.": (
        "{0} routes use approximate straight lines; distance is unknown."
    ),
    "{0} · Ctrl-C: save and exit": "{0} · Ctrl-C: save and exit",
    "Back without changes": "Back without changes",
    "Search countries": "Search countries",
    "Use selected countries": "Use selected countries",
    "Create this workspace": "Create this workspace",
    "Create TravelMap folders at this location?": "Create TravelMap folders at this location?",
    "Review/undo straight-line choices": "Review/undo straight-line choices",
    "Undo these straight-line choices": "Undo these straight-line choices",
    "Use straight lines for all open connections": "Use straight lines for all open connections",
    "Current visit order: {0}": "Current visit order: {0}",
    (
        "Distance unknown for {0} connections. Use Set a connection distance or Customize "
        "design to change the subtitle."
    ): (
        "Distance unknown for {0} connections. Use Set a connection distance or Customize "
        "design to change the subtitle."
    ),
    "Trip duration unavailable. Use Set trip duration or edit the subtitle.": (
        "Trip duration unavailable. Use Set trip duration or edit the subtitle."
    ),
    "Enter a positive whole number, for example 14, or remove.": (
        "Enter a positive whole number, for example 14, or remove."
    ),
    "Enter positive kilometres, for example 23.5, or remove.": (
        "Enter positive kilometres, for example 23.5, or remove."
    ),
    "Enter a six-digit color, for example #A33F35, or remove.": (
        "Enter a six-digit color, for example #A33F35, or remove."
    ),
    "Enter dash/gap lengths >0 and <=50 mm, for example 2 1, or remove.": (
        "Enter dash/gap lengths >0 and <=50 mm, for example 2 1, or remove."
    ),
    "The selected workspace path is a file: {0}. Choose a folder rather than a file.": (
        "The selected workspace path is a file: {0}. Choose a folder rather than a file."
    ),
    (
        "No route files yet. Copy a .geojson/.json route into {0}, then choose Choose a "
        "route file; or Continue / Save and exit."
    ): (
        "No route files yet. Copy a .geojson/.json route into {0}, then choose Choose a "
        "route file; or Continue / Save and exit."
    ),
    "Coordinate values must be finite numbers within numeric range.": (
        "Coordinate values must be finite numbers within numeric range."
    ),
    "Distance/duration exceeds the supported numeric range.": (
        "Distance/duration exceeds the supported numeric range."
    ),
    "Distance/duration must be finite numbers.": "Distance/duration must be finite numbers.",
    "Trip exceeds 1,000 routing connections. Use a smaller trip.": (
        "Trip exceeds 1,000 routing connections. Use a smaller trip."
    ),
    "The route choice does not belong to the current itinerary.": (
        "The route choice does not belong to the current itinerary."
    ),
    "Done: ": "Done: ",
    "! ": "! ",
    "Error: ": "Error: ",
    "  · ": "  · ",
    "Activity: {0} updates · i: details": "Activity: {0} updates · i: details",
    "Type a value · /back · /exit": "Type a value · /back · /exit",
    "Value": "Value",
    "Working · {minutes}m{seconds:02d}s | {message}": (
        "Working · {minutes}m{seconds:02d}s | {message}"
    ),
    "Working · {minutes}m {seconds:02d}s elapsed | {message} | Ctrl+C to pause": (
        "Working · {minutes}m {seconds:02d}s elapsed | {message} | Ctrl+C to pause"
    ),
    "Use plain text without color or highlighting.": (
        "Disable color; keep bold headings and selection emphasis on capable terminals."
    ),
    "Enter decimal degrees as latitude, longitude. South and west use negative numbers.": (
        "You can view the stop and choose a new location at https://www.openstreetmap.org. "
        "Enter decimal degrees as latitude, longitude. South and west use negative numbers."
    ),
    "Only this stop changes; affected routes and map coverage will be checked again.": (
        "Only this stop changes; affected routes and map coverage will be checked again."
    ),
    "New latitude, longitude (example: -54.85, -68.58)": (
        "New latitude, longitude (example: -54.85, -68.58)"
    ),
    "save": "save",
    "Save these stop coordinates": "Save these stop coordinates",
    "How would you like to resolve this uncovered stop?": (
        "How would you like to resolve this uncovered stop?"
    ),
    "Correct this stop's coordinates": "Correct this stop's coordinates",
    "Add or replace country boundary files": "Add or replace country boundary files",
    "Check country coverage again": "Check country coverage again",
    "Back to Map data": "Back to Map data",
    "Stop coordinates saved; checking country coverage again.": (
        "Stop coordinates saved; checking country coverage again."
    ),
    "Choose a displayed recovery action.": "Choose a displayed recovery action.",
    "Supply a country boundary GeoJSON, SHP, GPKG or intact Natural Earth country ZIP.": (
        "Supply a country boundary GeoJSON, SHP, GPKG or intact Natural Earth country ZIP."
    ),
    "OSM roads/water files do not supply country boundary polygons.": (
        "OSM roads/water files do not supply country boundary polygons."
    ),
    "Country boundary file path (Back cancels)": "Country boundary file path (Back cancels)",
    "Country boundary source added; checking coverage again.": (
        "Country boundary source added; checking coverage again."
    ),
    "That source is already selected; checking it again.": (
        "That source is already selected; checking it again."
    ),
    "Checking which map files are available in your workspace.": (
        "Checking which map files are available in your workspace."
    ),
    "No state/province border file was found. These internal borders are optional.": (
        "No state/province border file was found. These internal borders are optional."
    ),
    "Continuing without them keeps your other selected map layers and journey routes.": (
        "Continuing without them keeps your other selected map layers and journey routes."
    ),
    (
        "No state/province border file found. Open Help for download instructions, or choose "
        "Continue without state/province borders."
    ): (
        "No state/province border file found. Open Help for download instructions, or choose "
        "Continue without state/province borders."
    ),
    "Skipping this file keeps your other selected map layers and journey routes.": (
        "Skipping this file keeps your other selected map layers and journey routes."
    ),
    ("Then choose Check for the optional download, or Continue without state/province borders."): (
        "Then choose Check for the optional download, or Continue without state/province borders."
    ),
    (
        "Choose Continue without state/province borders, Check for the optional download, "
        "Help, Back, or Save and exit."
    ): (
        "Choose Continue without state/province borders, Check for the optional download, "
        "Help, Back, or Save and exit."
    ),
    "State/province border file found; it will be checked during preparation.": (
        "State/province border file found; it will be checked during preparation."
    ),
    "Preparing map layers for the selected countries from your local files.": (
        "Preparing map layers for the selected countries from your local files."
    ),
    "The first run may take a while. Unchanged prepared data is reused when available.": (
        "The first run may take a while. Unchanged prepared data is reused when available."
    ),
    "Map data prepared and selected; originals preserved. No routes or poster generated.": (
        "Map data prepared and selected; originals preserved. No routes or poster generated."
    ),
    "Combined neighboring extracts; entity winners resolved before geographic filtering.": (
        "Combined neighboring extracts; entity winners resolved before geographic filtering."
    ),
    "Reusing combined prepared layers.": "Reusing combined prepared layers.",
    (
        "Advanced vector feature bounds do not certify complete country coverage. All "
        "supplied detail is retained; review the full-country preview."
    ): (
        "Advanced vector feature bounds do not certify complete country coverage. All "
        "supplied detail is retained; review the full-country preview."
    ),
    "Your existing files are kept. Setup adds TravelMap folders and workspace metadata.": (
        "Your existing files are kept. Setup adds TravelMap folders and workspace metadata."
    ),
    "Export your trip as a KML file, or use a file you already exported.": (
        "Export your trip as a KML file, or use a file you already exported."
    ),
    (
        "Leave this terminal open while you copy files. Choose Continue when the files are "
        "in place."
    ): (
        "Leave this terminal open while you copy files. Choose Continue when the files are "
        "in place."
    ),
    "Review the stops and transport modes before choosing Accept and continue.": (
        "Review the stops and transport modes before choosing Accept and continue."
    ),
    "Add country boundaries and regional roads/water, or reuse your existing downloads.": (
        "Add country boundaries and regional roads/water, or reuse your existing downloads."
    ),
    (
        "The listed items cannot be imported. Import supported places to continue without "
        "them, or Save and exit to check your export."
    ): (
        "The listed items cannot be imported. Import supported places to continue without "
        "them, or Save and exit to check your export."
    ),
    "Itinerary edits saved. Choose Accept and continue when your review is finished.": (
        "Itinerary edits saved. Choose Accept and continue when your review is finished."
    ),
    (
        "Edits are saved as you make them, separately from your original file. Accept and "
        "continue uses this itinerary for the next steps and continues to Map data."
    ): (
        "Edits are saved as you make them, separately from your original file. Accept and "
        "continue uses this itinerary for the next steps and continues to Map data."
    ),
    (
        "The poster shows complete selected countries, including unvisited regions. Choose "
        "Displayed countries to review/change them after adding country boundaries; extra "
        "downloads do not add countries to the view."
    ): (
        "The poster shows complete selected countries, including unvisited regions. Choose "
        "Displayed countries to review/change them after adding country boundaries; extra "
        "downloads do not add countries to the view."
    ),
    "Saved map layers from the previous preparation; current files will be rechecked:": (
        "Saved map layers from the previous preparation; current files will be rechecked:"
    ),
    "Countries covering stops in the previous preparation: ": (
        "Countries covering stops in the previous preparation: "
    ),
    "Choose Continue to check your map files.": "Choose Continue to check your map files.",
    "Choose Continue to select and review your itinerary.": (
        "Choose Continue to select and review your itinerary."
    ),
    "Optional: add or replace journey routes": "Optional: add or replace journey routes",
    (
        "Use this step to supply your own route lines, even if your itinerary already "
        "includes routes."
    ): (
        "Use this step to supply your own route lines, even if your itinerary already "
        "includes routes."
    ),
    "Choose Continue to keep the current routes.": "Choose Continue to keep the current routes.",
    "The next step checks whether any connections still need a route.": (
        "The next step checks whether any connections still need a route."
    ),
    "Export your route lines as GeoJSON (.geojson or .json).": (
        "Export your route lines as GeoJSON (.geojson or .json)."
    ),
    "Complete any missing routes between your stops.": (
        "Complete any missing routes between your stops."
    ),
    "Use local route files, the routing service, or approximate straight lines.": (
        "Use local route files, the routing service, or approximate straight lines."
    ),
    (
        "For an API key, sign in or register at https://account.heigit.org/, then create and "
        "copy a key from your dashboard."
    ): (
        "For an API key, sign in or register at https://account.heigit.org/, then create and "
        "copy a key from your dashboard."
    ),
    "Paste it at the hidden prompt. The key is used only for this session.": (
        "Paste it at the hidden prompt. The key is used only for this session."
    ),
    "Leave the key blank, type /back, or press Ctrl-C to return to Routes.": (
        "Leave the key blank, type /back, or press Ctrl-C to return to Routes."
    ),
    "No request sent. Returned to Routes.": "No request sent. Returned to Routes.",
    "Design choices for your poster.": "Design choices for your poster.",
    "Current configuration:": "Current configuration:",
    "Reload config file": "Reload config file",
    "Config file: ": "Config file: ",
    "Edit this file in a text editor, save it, then choose Reload config file.": (
        "Edit this file in a text editor, save it, then choose Reload config file."
    ),
    "You can create this optional TOML file, then choose Reload config file.": (
        "You can create this optional TOML file, then choose Reload config file."
    ),
    "Open Help for an example. Menu changes are saved separately.": (
        "Open Help for an example. Menu changes are saved separately."
    ),
    "config.toml paths must resolve inside the trip workspace.": (
        "config.toml paths must resolve inside the trip workspace."
    ),
    "Config file loaded. Review the design, then choose Accept and continue.": (
        "Config file loaded. Review the design, then choose Accept and continue."
    ),
    "Create and save config.toml at the displayed path first.": (
        "Create and save config.toml at the displayed path first."
    ),
    "Current design kept. Correct the file, then choose Reload config file.": (
        "Current design kept. Correct the file, then choose Reload config file."
    ),
    "Create a TOML file with only the settings you want to override, for example:": (
        "Create a TOML file with only the settings you want to override, for example:"
    ),
    '[poster]\ntitle = "My trip"': '[poster]\ntitle = "My trip"',
    "Omitted values use the default design; menu edits are saved separately.": (
        "Omitted values use the default design; menu edits are saved separately."
    ),
    "Save the file, choose Reload config file, then review and accept the design.": (
        "Save the file, choose Reload config file, then review and accept the design."
    ),
    "Checking your routes, design and map data before export.": (
        "Checking your routes, design and map data before export."
    ),
    "When the checks finish, you can export your poster as an editable SVG.": (
        "When the checks finish, you can export your poster as an editable SVG."
    ),
    "Recheck map data": "Recheck map data",
    "Recheck routes and map data": "Recheck routes and map data",
    "Map files and settings are unchanged; reusing prepared map data.": (
        "Map files and settings are unchanged; reusing prepared map data."
    ),
    "Choose Recheck map data to run full validation again.": (
        "Recheck map data is optional; it repeats full validation even when files are unchanged."
    ),
    "Change the design using the options below or edit the config file.": (
        "Change the design using the options below or edit the config file."
    ),
    "Save the file, then choose Reload config file to apply your edits.": (
        "Save the file, then choose Reload config file to apply your edits."
    ),
    "Create this optional TOML file, save it, then choose Reload config file.": (
        "Create this optional TOML file, save it, then choose Reload config file."
    ),
    "Omitted values use the default design.": "Omitted values use the default design.",
    "Current filename: ": "Current filename: ",
    "Change filename ({0})": "Change filename ({0})",
    "Export complete.": "Export complete.",
    "What would you like to do next?": "What would you like to do next?",
    "Close TravelMap": "Close TravelMap",
    "Back to Poster design": "Back to Poster design",
    "Choose Close TravelMap or Back to Poster design.": (
        "Choose Close TravelMap or Back to Poster design."
    ),
    "Map islands: {0}. {1} included; {2} excluded; {3} trip-protected.": (
        "Map islands: {0}. {1} included; {2} excluded; {3} trip-protected."
    ),
    "Offshore selection: {0} comparisons; {1} transient coordinates.": (
        "Offshore selection: {0} comparisons; {1} transient coordinates."
    ),
    (
        "Yes includes all islands. No keeps the mainland, islands within 12 nautical miles, "
        "trip locations, connected cross-border land and whole islands fitting the map. "
        "Archipelagic countries are outside the current filtering scope."
    ): (
        "Yes includes all islands. No keeps the mainland, islands within 12 nautical miles, "
        "trip locations, connected cross-border land and whole islands fitting the map. "
        "Archipelagic countries are outside the current filtering scope."
    ),
    "Set only one of map.boundaries.country_ids and country_codes.": (
        "Set only one of map.boundaries.country_ids and country_codes."
    ),
    "config.toml must be a regular file inside the workspace.": (
        "config.toml must be a regular file inside the workspace."
    ),
    "config.toml must not be a symlink.": "config.toml must not be a symlink.",
    "To change these settings, edit and save config.toml, then choose Reload config file.": (
        "To change these settings, edit and save config.toml, then choose Reload config file."
    ),
    "Map sources must use workspace-relative local paths.": (
        "Map sources must use workspace-relative local paths."
    ),
    "config.toml is missing. Restore it or create it from the documented defaults.": (
        "config.toml is missing. Restore it or create it from the documented defaults."
    ),
    "Move legacy map sources inside the workspace before migration.": (
        "Move legacy map sources inside the workspace before migration."
    ),
    "Edit and save config.toml, then choose Reload config file to review your changes.": (
        "Edit and save config.toml, then choose Reload config file to review your changes."
    ),
    (
        "Use map.boundaries.country_ids or country_codes for displayed countries; [] uses "
        "trip countries."
    ): (
        "Use map.boundaries.country_ids or country_codes for displayed countries; [] uses "
        "trip countries."
    ),
    "Use map.distance.segment_overrides_km for connection distances in kilometres.": (
        "Use map.distance.segment_overrides_km for connection distances in kilometres."
    ),
    ("Use map.distance.travel_days_override for total days; remove it to calculate from dates."): (
        "Use map.distance.travel_days_override for total days; remove it to calculate from dates."
    ),
    (
        "Update stop dates in Your itinerary. The poster title is configured separately from "
        "the trip title."
    ): (
        "Update stop dates in Your itinerary. The poster title is configured separately from "
        "the trip title."
    ),
    (
        "Use poster.subtitle to change the subtitle, or output.incomplete_distance = "
        '"subtotal" for a partial distance.'
    ): (
        "Use poster.subtitle to change the subtitle, or output.incomplete_distance = "
        '"subtotal" for a partial distance.'
    ),
    '[map.distance]\ntravel_days_override = 14\nsegment_overrides_km = { "1" = 125.5 }': (
        '[map.distance]\ntravel_days_override = 14\nsegment_overrides_km = { "1" = 125.5 }'
    ),
    "Style changes reuse compatible routes and prepared map layers.": (
        "Style changes reuse compatible routes and prepared map layers."
    ),
    "config.previous-settings.toml already exists; preserve or rename it before migration.": (
        "config.previous-settings.toml already exists; preserve or rename it before migration."
    ),
    "Config file changed. Choose Reload config file and review it before accepting.": (
        "Config file changed. Choose Reload config file and review it before accepting."
    ),
    (
        "The poster shows complete selected countries, including unvisited regions. Choose "
        "Displayed countries to review their IDs after adding country boundaries; extra "
        "downloads do not add countries to the view."
    ): (
        "The poster shows complete selected countries, including unvisited regions. Choose "
        "Displayed countries to review their IDs after adding country boundaries; extra "
        "downloads do not add countries to the view."
    ),
    ("Change map.boundaries.country_ids or country_codes in config.toml, then recheck map data."): (
        "Change map.boundaries.country_ids or country_codes in config.toml, then recheck map data."
    ),
    "Available country IDs:": "Available country IDs:",
    (
        "Copy boundary downloads into map-data, or configure map.boundaries.country_path in "
        "config.toml."
    ): (
        "Copy boundary downloads into map-data, or configure map.boundaries.country_path in "
        "config.toml."
    ),
    "For multiple boundary sources, add entries to map.sources in config.toml.": (
        "For multiple boundary sources, add entries to map.sources in config.toml."
    ),
    "Use workspace-relative paths and country polygons, not OSM roads/water extracts.": (
        "Use workspace-relative paths and country polygons, not OSM roads/water extracts."
    ),
    (
        "Stop kept as entered. Country-boundary acceptance does not certify road, water or "
        "route coverage."
    ): (
        "Stop kept as entered. Country-boundary acceptance does not certify road, water or "
        "route coverage."
    ),
    "Recheck map data before keeping this stop.": "Recheck map data before keeping this stop.",
    (
        "Trip duration unavailable. Update stop dates in Your itinerary or set "
        "map.distance.travel_days_override in config.toml; Accept and continue keeps "
        "duration unavailable."
    ): (
        "Trip duration unavailable. Update stop dates in Your itinerary, or set the trip "
        "duration in Poster design (Step 6) via config.toml. Use "
        "map.distance.travel_days_override; Accept and continue keeps duration unavailable."
    ),
    "Enter YYYY-MM-DD, or clear to leave this date unavailable.": (
        "Enter YYYY-MM-DD, or clear to leave this date unavailable."
    ),
    (
        "Choose Update stop dates to correct arrival dates; poster settings are edited in "
        "config.toml."
    ): (
        "Choose Update stop dates to correct arrival dates; poster settings are edited in "
        "config.toml."
    ),
    "Enter a valid calendar date as YYYY-MM-DD, for example 2026-06-12.": (
        "Enter a valid calendar date as YYYY-MM-DD, for example 2026-06-12."
    ),
    "The poster title is set separately in config.toml.": (
        "The poster title is set separately in config.toml."
    ),
    "Countries: {0}": "Countries: {0}",
    "State/province borders: {0}": "State/province borders: {0}",
    (
        "Previous CLI settings were preserved in {0}. Compare them with config.toml before "
        "accepting the design."
    ): (
        "Previous CLI settings were preserved in {0}. Compare them with config.toml before "
        "accepting the design."
    ),
    (
        "config.toml is now authoritative. Previous CLI settings were preserved in {0}. "
        "Review that file and copy desired values into config.toml."
    ): (
        "config.toml is now authoritative. Previous CLI settings were preserved in {0}. "
        "Review that file and copy desired values into config.toml."
    ),
    "config.toml: {0}. Correct the file, save, and reload it.": (
        "config.toml: {0}. Correct the file, save, and reload it."
    ),
    "Routes and map data were rechecked.": "Routes and map data were rechecked.",
    "Exporting your poster; originals and prior artwork are protected.": (
        "Exporting your poster; originals and prior artwork are protected."
    ),
    "Partial run only; prior artwork restored. Completed new posters: {0}": (
        "Partial run only; prior artwork restored. Completed new posters: {0}"
    ),
    "Partial run; earlier existing artwork is protected. Completed new posters: {0}": (
        "Partial run; earlier existing artwork is protected. Completed new posters: {0}"
    ),
    "/back: Back": "/back: Back",
    "/exit: Save and exit": "/exit: Save and exit",
    "Type a value": "Type a value",
    (
        "Choose an item by number. Back returns to the previous screen; Save and exit "
        "preserves your work."
    ): (
        "Choose an item by number. Back returns to the previous screen; Save and exit "
        "preserves your work."
    ),
    "Choose one of the displayed numbers, Back, or Save and exit.": (
        "Choose one of the displayed numbers, Back, or Save and exit."
    ),
    "Session-only OpenRouteService API key (hidden): ": (
        "Session-only OpenRouteService API key (hidden): "
    ),
    "Type /exit to save and exit.": "Type /exit to save and exit.",
    "Ctrl-C: save and exit": "Ctrl-C: save and exit",
    "Ctrl-C: save & exit": "Ctrl-C: save & exit",
    "Enter/Esc: return": "Enter/Esc: return",
    "↑/↓ Enter · d: full": "↑/↓ Enter · d: full",
    "i: info / folder": "i: info / folder",
    "i: full info": "i: full info",
    "/exit: Save & exit": "/exit: Save & exit",
    "Working · {minutes}m {seconds:02d}s elapsed | {message}": (
        "Working · {minutes}m {seconds:02d}s elapsed | {message}"
    ),
    "Processed events: {processed:,} | Stored features: {stored:,} | {phase} {source}": (
        "Processed events: {processed:,} | Stored features: {stored:,} | {phase} {source}"
    ),
    "{minutes}m {seconds:02d}s | {message}": "{minutes}m {seconds:02d}s | {message}",
    "Worker resident memory is above 1.5 GiB; continuing within the 3 GiB supervised limit.": (
        "Map preparation is using more than 1.5 GiB of memory. It can continue up to the 3 "
        "GiB safety limit."
    ),
    "Process monitoring unavailable; reported work counters remain visible.": (
        "Memory use and processing activity cannot be checked. Reported progress remains "
        "visible; use Ctrl-C to pause if needed."
    ),
    (
        "Possible stall: measured work/CPU has not advanced for five minutes. You can pause "
        "with Ctrl+C; elapsed time alone does not stop this job."
    ): (
        "No processing activity has been detected for five minutes. The job may be stalled. "
        "Use Ctrl-C to pause, or wait; there is no time limit."
    ),
    "Page {page}/{pages} · ↑/↓: pages · c: copy": "Page {page}/{pages} · ↑/↓: pages · c: copy",
    "{page}/{pages} ↑/↓ · c: copy": "{page}/{pages} ↑/↓ · c: copy",
    "Checking saved map layers.": "Checking saved map layers.",
    "Checking map files and settings.": "Checking map files and settings.",
    "Rechecking map file contents and prepared layers.": (
        "Rechecking map file contents and prepared layers."
    ),
    "Checking country boundaries and stop coverage.": (
        "Checking country boundaries and stop coverage."
    ),
    "Checking {0}: reading file contents.": "Checking {0}: reading file contents.",
    "Continue checks for changes. Recheck map data repeats full validation (optional).": (
        "Continue checks for changes and reuses valid results. Recheck map data repeats full "
        "validation (optional)."
    ),
    "Checking route coverage.": "Checking route coverage.",
    "Finalizing prepared map layers.": "Finalizing prepared map layers.",
    "Faulty stop": "Faulty stop",
    "Previous stop": "Previous stop",
    "Next stop": "Next stop",
    "date missing": "date missing",
    "Showing stops with date warnings and their immediate neighbors.": (
        "Showing stops with date warnings and their immediate neighbors."
    ),
    (
        "Reliable day count unavailable: dates are missing, invalid or contradictory. Order "
        "and supplied dates are preserved. Set the trip duration in Poster design (Step 6)."
    ): (
        "Reliable day count unavailable: dates are missing, invalid or contradictory. Order "
        "and supplied dates are preserved. Update stop dates in Your itinerary, or set the "
        "trip duration in Poster design (Step 6) via config.toml."
    ),
    "Visit {number}: {label}": "Visit {number}: {label}",
    "visit {number} ({name})": "visit {number} ({name})",
    "Choose a stop to move, or Finish reordering to return to itinerary review.": (
        "Choose a stop to move, or Finish reordering to return to itinerary review."
    ),
    "Finish reordering": "Finish reordering",
    "Which stop would you like to move?": "Which stop would you like to move?",
    "Where should {stop} go?": "Where should {stop} go?",
    "Before another stop": "Before another stop",
    "After another stop": "After another stop",
    "Move to start": "Move to start",
    "Move to end": "Move to end",
    "Choose a displayed move action.": "Choose a displayed move action.",
    "Which stop should it be placed next to?": "Which stop should it be placed next to?",
    "Move {stop} before {target}?": "Move {stop} before {target}?",
    "Move {stop} after {target}?": "Move {stop} after {target}?",
    "Move {stop} to the start?": "Move {stop} to the start?",
    "Move {stop} to the end?": "Move {stop} to the end?",
    "This stop is already in that position.": "This stop is already in that position.",
    "New order near the moved stop:": "New order near the moved stop:",
    "Changed connections to check: {count}.": "Changed connections to check: {count}.",
    "At least two stops are needed to reorder your itinerary.": (
        "At least two stops are needed to reorder your itinerary."
    ),
    "Stop move saved. Move another stop or choose Finish reordering.": (
        "Stop move saved. Move another stop or choose Finish reordering."
    ),
    "Day count: {days}.": "Day count: {days}.",
    "Undeclared connections default to driving (car). Inspect and correct before routing.": (
        "Connections without a transport mode use driving (car). You can change this in Your "
        "itinerary if needed."
    ),
    "Continue to Poster design?": "Continue to Poster design?",
    "Continue to optional own routes?": "Continue to optional own routes?",
    "All routes are ready. Adding your own routes is optional.": (
        "All routes are ready. Adding your own routes is optional."
    ),
    "Use your own files for missing routes, or return to Routes to review other options.": (
        "Use your own files for missing routes, or return to Routes to review other options."
    ),
    "Own routes — add recorded routes (optional)": "Own routes — add recorded routes (optional)",
    "Routes — fill in missing journey routes": "Routes — fill in missing journey routes",
}
_TEMPLATES: list[tuple[re.Pattern[str], str]] = []
for _source, _replacement in _TEXTS.items():
    if not re.search(r"\{\d+\}", _source):
        continue
    _parts = re.split(r"(\{\d+\})", _source)
    _pattern = (
        "^"
        + "".join(
            "(.+?)" if re.fullmatch(r"\{\d+\}", _part) else re.escape(_part) for _part in _parts
        )
        + "$"
    )
    _TEMPLATES.append((re.compile(_pattern), _replacement))
_TEMPLATES.sort(key=lambda item: len(item[0].pattern), reverse=True)


def text(source: str) -> str:
    """Return the editable UI copy for an English source phrase."""
    exact = _TEXTS.get(source)
    if exact is not None:
        return exact
    for pattern, replacement in _TEMPLATES:
        match = pattern.fullmatch(source)
        if match:
            try:
                return replacement.format(*match.groups())
            except (IndexError, KeyError, ValueError):
                return source
    return source
