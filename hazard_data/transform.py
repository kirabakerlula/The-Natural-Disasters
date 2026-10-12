"""Transform collected hazard records into county-level tables.

No network calls, CSV inputs, Census demographics, or FEMA data are required by
this module. Call transform_usgs() or transform_calfire() with response.json()
and a Census GeoJSON county reference. Each returns a cleaned DataFrame; its
attrs['issues'] contains audit records that must be stored separately if needed.
Call transform_raw_hazards() when both source responses are available to create
the county summary. Existing CSV snapshots are supported by transform_hazards()
and the separate command-line runner. FIPS is always a five-character string.

Earthquakes are assigned only when their epicenter is covered by exactly one
county polygon. Offshore/outside points and boundary ambiguities stay unassigned.
Wildfires use the affected counties named by CAL FIRE, not its internal IDs or
the incident's single coordinate. Multi-county fires count once per county;
county counts therefore must not be summed to obtain statewide event counts.
Zeros describe the supplied snapshot, not guaranteed historical coverage.

Reading guide for API integration:
    1. Start with transform_usgs() / transform_calfire() near the end of this file.
    2. Use dataframe_records() to convert their DataFrames to JSON-safe records.
    3. Read transform_raw_hazards() if both raw sources are available for a summary.
    4. The earlier sections are the shared implementation used by those functions.

Load the geographic reference with county_reference.load_county_reference().
This module handles transformation only; callers handle HTTP, GCS, and scheduling.
"""

import ast
import json
import math
from dataclasses import dataclass

import pandas as pd
from shapely.geometry import Point, shape
from shapely.strtree import STRtree


# SECTION 1: Result bundle returned when transforming both sources together.
@dataclass
class HazardTables:
    """Five related tables, with different row meanings.

    earthquakes: one row per retained earthquake, including unassigned events.
    wildfire_events: one row per retained fire, including unassigned events.
    wildfire_counties: one row per fire/matched county, for county aggregation.
    county_summary: one row per reference county, ready for a Census FIPS join.
    issues: audit rows describing rejected values, exclusions, or missing matches.
    """
    earthquakes: pd.DataFrame
    wildfire_events: pd.DataFrame
    wildfire_counties: pd.DataFrame
    county_summary: pd.DataFrame
    issues: pd.DataFrame


# SECTION 2: County lookup and validation helpers, shared by both sources.
# The reference contains geographic boundaries/FIPS, not Census demographics.
def _county_name(value: str) -> str:
    """Normalize county labels so suffixes, spaces, and case do not break joins."""
    return " ".join(value.removesuffix(" County, California").removesuffix(" County").split()).casefold()


class CountyIndex:
    """Index official polygons and names, retaining FIPS leading zeroes."""

    def __init__(self, geojson: dict):
        self.counties = []
        self.geometries = []
        self.by_name = {}
        for feature in geojson["features"]:
            properties = feature["properties"]
            code = str(properties["GEOID"])
            if len(code) != 5 or not code.isdigit() or not code.startswith("06"):
                raise ValueError(f"Invalid California county FIPS: {code}")
            name = properties["NAME"].removesuffix(" County")
            geometry = shape(feature["geometry"])
            if geometry.is_empty or not geometry.is_valid:
                raise ValueError(f"Invalid county polygon: {name}")
            key = _county_name(name)
            if key in self.by_name or any(c["county_fips"] == code for c in self.counties):
                raise ValueError(f"Duplicate reference county: {name}")
            record = {"county_fips": code, "county_name": name}
            self.by_name[key] = record
            self.counties.append(record)
            self.geometries.append(geometry)
        if not self.counties:
            raise ValueError("No county polygons provided")
        self.tree = STRtree(self.geometries)

    def locate(self, latitude, longitude):
        """Return one county or an explicit reason why assignment failed."""
        if not _valid_coordinates(latitude, longitude):
            return None, "invalid_coordinates"
        # A spatial index finds county polygons covering the earthquake epicenter.
        matches = self.tree.query(Point(float(longitude), float(latitude)), predicate="covered_by")
        if len(matches) == 0:
            return None, "outside_county_boundaries"
        if len(matches) > 1:
            return None, "ambiguous_county_boundary"
        return self.counties[int(matches[0])], "matched"


def _valid_coordinates(latitude, longitude):
    try:
        lat, lon = float(latitude), float(longitude)
        return (math.isfinite(lat) and math.isfinite(lon) and
                -90 <= lat <= 90 and -180 <= lon <= 180 and lat != 0 and lon != 0)
    except (ValueError, TypeError):
        return False


def _parse_counties(value):
    """Accept raw lists or old CSV list strings; remove repeated county names."""
    if isinstance(value, (list, tuple)):
        names = list(value)
    elif value is None or (isinstance(value, float) and math.isnan(value)):
        names = []
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            names = []
        elif text.startswith("["):
            names = ast.literal_eval(text)
            if not isinstance(names, list):
                raise ValueError("Expected a county list")
        else:
            names = [text]
    else:
        raise ValueError("Unsupported county value")
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError("County names must be nonempty strings")
    return list(dict.fromkeys(name.strip() for name in names))


# SECTION 3: Shared transformation engine. Input is normalized collector tables.
# API callers normally use the raw-JSON entry points in Section 5 instead.
def transform_hazards(earthquakes: pd.DataFrame, wildfires: pd.DataFrame,
                      county_geojson: dict, *, start_date="2016-01-01",
                      end_date=None, min_magnitude=4.0) -> HazardTables:
    """Clean independently, assign FIPS, then join county aggregates one-to-one.

    Dates are UTC, inclusive at the day level. end_date=None retains all supplied
    dates; the collection schedule controls freshness. Duplicate IDs keep the
    last supplied record (a refreshed snapshot can update an incident). Invalid
    IDs/dates and out-of-period records are reported. Unassigned events remain
    in event tables, but do not enter county aggregates. Successful, complete
    collector snapshots must be passed; collection failures must raise upstream.
    """
    # 3a. Build the county lookup and validate the requested UTC date window.
    index = CountyIndex(county_geojson)
    issues = []
    start = pd.to_datetime(start_date, utc=True)
    end = pd.to_datetime(end_date, utc=True) if end_date else None
    if pd.isna(start) or (end is not None and pd.isna(end)):
        raise ValueError("Requested dates must be valid")
    start = start.normalize()
    end = end.normalize() if end is not None else None
    if end is not None and end < start:
        raise ValueError("end_date must not precede start_date")
    min_magnitude = float(min_magnitude)
    if not math.isfinite(min_magnitude):
        raise ValueError("min_magnitude must be finite")

    def issue(source, event_id, reason, detail=""):
        issues.append({"source": source, "event_id": str(event_id),
                       "issue": reason, "detail": str(detail)})

    def clean(frame, source, id_column, required):
        """Shared cleaning: required fields, IDs, last-record deduplication, dates."""
        if not frame.columns.is_unique:
            raise ValueError(f"{source} has duplicate column names")
        reserved = {"county_fips", "county_name", "county_match_status", "matched_county_count"}
        if reserved.intersection(frame.columns):
            raise ValueError(f"{source} already has transformation fields; pass collector records")
        missing = set(required) - set(frame.columns)
        if missing:
            raise ValueError(f"{source} missing columns: {sorted(missing)}")
        frame = frame.copy()
        valid_ids = frame[id_column].notna() & frame[id_column].astype(str).str.strip().ne("")
        for row in frame.loc[~valid_ids].to_dict("records"):
            issue(source, row[id_column], "missing_event_id")
        frame = frame.loc[valid_ids].copy()
        frame[id_column] = frame[id_column].astype(str).str.strip()
        for event_id in frame.loc[frame.duplicated(id_column, keep="last"), id_column]:
            issue(source, event_id, "duplicate_event_id", "kept last supplied record")
        frame = frame.drop_duplicates(id_column, keep="last").copy()
        dates = pd.to_datetime(frame["date"], utc=True, errors="coerce", format="mixed")
        for event_id in frame.loc[dates.isna(), id_column]:
            issue(source, event_id, "invalid_date")
        days = dates.dt.normalize()
        in_period = dates.notna() & days.ge(start)
        if end is not None:
            in_period &= days.le(end)
        for event_id in frame.loc[dates.notna() & ~in_period, id_column]:
            issue(source, event_id, "outside_requested_period")
        frame = frame.loc[in_period].copy()
        frame["date"] = days.loc[in_period].dt.strftime("%Y-%m-%d")
        frame["year_month"] = days.loc[in_period].dt.strftime("%Y-%m")
        return frame.reset_index(drop=True)

    # 3b. Clean earthquake IDs/dates; coerce numeric fields and audit bad values.
    eq = clean(earthquakes, "usgs", "earthquake_id",
               ["earthquake_id", "date", "latitude", "longitude", "magnitude"])
    def numeric_fields(frame, source, id_column, limits):
        """Convert numbers; replace invalid/out-of-range values with missing values."""
        for column, (minimum, maximum) in limits.items():
            if column not in frame:
                continue
            original = frame[column]
            numbers = pd.to_numeric(original, errors="coerce")
            valid = numbers.map(lambda value: pd.notna(value) and math.isfinite(value))
            if minimum is not None:
                valid &= numbers.ge(minimum)
            if maximum is not None:
                valid &= numbers.le(maximum)
            for event_id in frame.loc[original.notna() & ~valid, id_column]:
                issue(source, event_id, "invalid_numeric_field", column)
            frame[column] = numbers.where(valid)

    numeric_fields(eq, "usgs", "earthquake_id", {
        "latitude": (-90, 90), "longitude": (-180, 180), "depth": (None, None)})
    eq["magnitude"] = pd.to_numeric(eq["magnitude"], errors="coerce")
    magnitude_valid = eq["magnitude"].map(lambda x: pd.notna(x) and math.isfinite(x))
    for event_id in eq.loc[~magnitude_valid, "earthquake_id"]:
        issue("usgs", event_id, "invalid_magnitude")
    for event_id in eq.loc[magnitude_valid & eq["magnitude"].lt(min_magnitude), "earthquake_id"]:
        issue("usgs", event_id, "below_minimum_magnitude")
    eq = eq.loc[magnitude_valid & eq["magnitude"].ge(min_magnitude)].copy()
    # 3c. Assign earthquake FIPS from coordinates. Keep unmatched events for audit.
    assignments = []
    for row in eq.to_dict("records"):
        county, status = index.locate(row["latitude"], row["longitude"])
        assignments.append({"county_fips": county["county_fips"] if county else None,
                            "county_name": county["county_name"] if county else None,
                            "county_match_status": status})
        if county is None:
            issue("usgs", row["earthquake_id"], status)
    eq = eq.reset_index(drop=True)
    for column in ["county_fips", "county_name", "county_match_status"]:
        eq[column] = pd.Series([a[column] for a in assignments], dtype="string")

    # 3d. Clean fires and map every affected county name to its official FIPS.
    # CountyIds are CAL FIRE's internal identifiers and are never used as FIPS.
    fires = clean(wildfires, "calfire", "fire_id", ["fire_id", "date", "counties"])
    numeric_fields(fires, "calfire", "fire_id", {
        "latitude": (-90, 90), "longitude": (-180, 180),
        "acres_burned": (0, None), "percent_contained": (0, 100),
        "structures_destroyed": (0, None)})
    expanded = []
    statuses, county_counts = [], []
    for row in fires.to_dict("records"):
        event_id = row["fire_id"]
        if "latitude" in row and "longitude" in row and not _valid_coordinates(row["latitude"], row["longitude"]):
            issue("calfire", event_id, "invalid_coordinates", "county names used for assignment")
        try:
            names = _parse_counties(row["counties"])
        except (ValueError, SyntaxError):
            issue("calfire", event_id, "invalid_county_list", row["counties"])
            statuses.append("invalid_county_list")
            county_counts.append(0)
            continue
        matched = {}
        unknown = []
        for name in names:
            county = index.by_name.get(_county_name(name))
            if county:
                matched[county["county_fips"]] = county
            else:
                unknown.append(name)
                issue("calfire", event_id, "unmatched_county_name", name)
        if not names:
            issue("calfire", event_id, "missing_county")
        statuses.append("partially_matched" if matched and unknown else
                        "matched" if matched else "unassigned")
        county_counts.append(len(matched))
        # One incident can affect several counties; retain its identity in each row.
        for county in matched.values():
            expanded.append({**row, **county})
    fires["county_match_status"] = pd.Series(statuses, dtype="string")
    fires["matched_county_count"] = county_counts
    fire_counties = pd.DataFrame(expanded, columns=[*wildfires.columns,
        *([] if "year_month" in wildfires.columns else ["year_month"]),
        "county_fips", "county_name"])

    # 3e. Count unique events per county, then join the two aggregates by FIPS.
    # Keep every reference county. No matched earthquake means null max magnitude.
    summary = pd.DataFrame(index.counties).sort_values("county_fips").reset_index(drop=True)
    assigned = eq.loc[eq["county_fips"].notna()]
    eq_stats = assigned.groupby("county_fips", as_index=False).agg(
        earthquake_count=("earthquake_id", "nunique"),
        max_earthquake_magnitude=("magnitude", "max"))
    fire_stats = fire_counties.groupby("county_fips", as_index=False).agg(
        wildfire_count=("fire_id", "nunique"))
    summary = summary.merge(eq_stats, on="county_fips", how="left", validate="one_to_one")
    summary = summary.merge(fire_stats, on="county_fips", how="left", validate="one_to_one")
    for column in ["earthquake_count", "wildfire_count"]:
        summary[column] = summary[column].fillna(0).astype("int64")
    return HazardTables(eq, fires, fire_counties, summary,
                        pd.DataFrame(issues, columns=["source", "event_id", "issue", "detail"]))


# SECTION 4: Raw source adapters. Validate JSON shape and standardize field names.
# These adapters extract records; Section 3 performs cleaning and county matching.
_USGS_COLUMNS = ["earthquake_id", "date", "place", "magnitude", "latitude", "longitude", "depth"]
_CALFIRE_FIELDS = {
    "fire_id": "UniqueId", "date": "Started", "name": "Name",
    "location": "Location", "counties": "Counties", "county_ids": "CountyIds",
    "latitude": "Latitude", "longitude": "Longitude", "acres_burned": "AcresBurned",
    "percent_contained": "PercentContained", "structures_destroyed": "StructuresDestroyed",
}


def _usgs_records(raw_data):
    """Extract USGS features; read [longitude, latitude, depth] and epoch milliseconds."""
    if (not isinstance(raw_data, dict) or raw_data.get("type") != "FeatureCollection"
            or "error" in raw_data or not isinstance(raw_data.get("features"), list)):
        raise ValueError("USGS response must be a successful GeoJSON FeatureCollection with features")
    features = raw_data["features"]
    metadata = raw_data.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise ValueError("USGS metadata must be an object")
        status = metadata.get("status")
        if status is not None and status != 200:
            raise ValueError(f"USGS response reports unsuccessful status: {status}")
        if "count" in metadata and metadata["count"] != len(features):
            raise ValueError("USGS metadata count disagrees with supplied features")
    rows = []
    for feature in features:
        if (not isinstance(feature, dict) or feature.get("type") != "Feature"
                or not isinstance(feature.get("properties"), dict)):
            raise ValueError("USGS features must be GeoJSON Feature objects with properties")
        properties = feature["properties"]
        geometry = feature.get("geometry")
        coordinates = [None, None, None]
        if geometry is not None:
            if (not isinstance(geometry, dict) or geometry.get("type") != "Point"
                    or not isinstance(geometry.get("coordinates"), list)
                    or len(geometry["coordinates"]) < 2):
                raise ValueError("USGS geometry must be a Point with longitude/latitude coordinates")
            coordinates = geometry["coordinates"]
        rows.append({"earthquake_id": feature.get("id"), "date": properties.get("time"),
                     "place": properties.get("place"), "magnitude": properties.get("mag"),
                     "longitude": coordinates[0], "latitude": coordinates[1],
                     "depth": coordinates[2] if len(coordinates) > 2 else None})
    frame = pd.DataFrame(rows, columns=_USGS_COLUMNS)
    # USGS time is milliseconds since the Unix epoch, not a date string or nanoseconds.
    timestamps = pd.to_numeric(frame["date"], errors="coerce")
    frame["date"] = pd.to_datetime(timestamps, unit="ms", utc=True, errors="coerce")
    return frame


def _calfire_records(raw_data):
    """Rename CAL FIRE fields from an Incidents response or combined incident list."""
    if isinstance(raw_data, dict):
        if "error" in raw_data or "Incidents" not in raw_data:
            raise ValueError("CAL FIRE response must contain a successful Incidents list")
        incidents = raw_data["Incidents"]
    else:
        incidents = raw_data
    if not isinstance(incidents, list) or any(not isinstance(item, dict) for item in incidents):
        raise ValueError("CAL FIRE input must be an Incidents response or a list of incident objects")
    return pd.DataFrame([{column: item.get(field) for column, field in _CALFIRE_FIELDS.items()}
                         for item in incidents], columns=list(_CALFIRE_FIELDS))


# SECTION 5: Public entry points for API integration. Start reading here.
def transform_raw_hazards(usgs_raw: dict, calfire_raw, county_geojson: dict, *,
                          start_date="2016-01-01", end_date=None,
                          min_magnitude=4.0) -> HazardTables:
    """Transform both raw source responses and produce one summary row per county.

    USGS input is the response.json() GeoJSON FeatureCollection. CAL FIRE input
    is response.json() containing Incidents, or the combined list of incidents
    from successful yearly requests. Call response.raise_for_status() upstream;
    a missing response is not equivalent to an empty successful collection.
    This function checks response shape, not whether every requested year or
    page was collected. The collector must enforce complete acquisition.
    """
    return transform_hazards(_usgs_records(usgs_raw), _calfire_records(calfire_raw),
                             county_geojson, start_date=start_date, end_date=end_date,
                             min_magnitude=min_magnitude)


def transform_usgs(raw_data: dict, county_geojson: dict, *, start_date="2016-01-01",
                   end_date=None, min_magnitude=4.0) -> pd.DataFrame:
    """Return one row per earthquake, ready for serialization and GCS upload.

    Pass the raw USGS GeoJSON response and the already loaded county reference.
    Coordinates determine FIPS; the free-text place label does not filter events.
    Unassigned events retain a null county_fips and an explicit match status.
    Dates are UTC days, the date window includes both endpoints, and magnitude
    defaults to >=4.0. attrs['issues'] lists dropped/invalid/unassigned records.
    These enriched rows must not be passed to transform_hazards() again.
    """
    # Reuse the shared engine with an empty fire input; return only earthquake rows.
    # The temporary fire counts are not a collected dataset and are not returned.
    tables = transform_raw_hazards(raw_data, {"Incidents": []}, county_geojson,
                                  start_date=start_date, end_date=end_date,
                                  min_magnitude=min_magnitude)
    result = tables.earthquakes
    result.attrs["issues"] = tables.issues.to_dict("records")
    result.attrs["row_grain"] = "one earthquake event"
    return result


def transform_calfire(raw_data, county_geojson: dict, *, start_date="2016-01-01",
                      end_date=None) -> pd.DataFrame:
    """Return one row per wildfire/affected county; retain unassigned fires.

    Input is a CAL FIRE Incidents response or a combined list of incident objects
    from successful yearly responses. County names map to FIPS; CountyIds are
    preserved for traceability but are not FIPS. A multi-county event has multiple
    rows with the same fire_id. An unassigned event has one row with null FIPS.
    Event-wide acres_burned is repeated, not divided among counties: neither
    summing it across rows nor treating it as county acreage is valid.
    attrs['issues'] contains audit records. Use dataframe_records() for JSON;
    DataFrame attrs are not automatically included in uploaded table records.
    """
    # Reuse the shared engine with an empty earthquake input; return only fire rows.
    tables = transform_raw_hazards({"type": "FeatureCollection", "features": []},
                                  raw_data, county_geojson,
                                  start_date=start_date, end_date=end_date)
    assignments = tables.wildfire_counties[["fire_id", "county_fips", "county_name"]]
    # Left join expands matched fires and keeps one null-county row for unmatched fires.
    result = tables.wildfire_events.merge(assignments, on="fire_id", how="left",
                                         validate="one_to_many")
    for column in ["county_fips", "county_name"]:
        result[column] = result[column].astype("string")
    result.attrs["issues"] = tables.issues.to_dict("records")
    result.attrs["row_grain"] = "one wildfire per affected county; one null-county row if unassigned"
    return result


# SECTION 6: Serialization helper used before the caller uploads records to GCS.
def dataframe_records(frame: pd.DataFrame) -> list[dict]:
    """Return JSON-safe records: string FIPS, list counties, and null missing values.

    Unlike to_dict('records'), this converts pandas NA/NaN to JSON null. Audit
    records in frame.attrs['issues'] must be serialized separately by the caller.
    """
    return json.loads(frame.to_json(orient="records", date_format="iso"))
