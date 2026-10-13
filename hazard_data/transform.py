"""Clean raw USGS/CAL FIRE JSON, add county FIPS, and summarize by county.

Call transform_usgs() or transform_calfire() after a successful API request.
Both return DataFrames. HTTP requests, GCS uploads, and Census joins belong
to the caller. Unassigned events stay in the output with null county FIPS.
"""

import json
import math

import pandas as pd

from .county_reference import CountyIndex, normalize_county_name


def _clean_events(frame, id_column, start_date, end_date):
    """Keep valid IDs/dates, the last supplied record per ID, and inclusive UTC days."""
    start = pd.to_datetime(start_date, utc=True, errors="coerce")
    end = pd.to_datetime(end_date, utc=True, errors="coerce") if end_date is not None else None
    if pd.isna(start) or (end is not None and pd.isna(end)):
        raise ValueError("Provide valid start and end dates")
    start = start.normalize()
    end = end.normalize() if end is not None else None
    if end is not None and end < start:
        raise ValueError("end_date must be on or after start_date")
    valid_ids = frame[id_column].notna() & frame[id_column].astype(str).str.strip().ne("")
    frame = frame.loc[valid_ids].copy()
    frame[id_column] = frame[id_column].astype(str).str.strip()
    frame = frame.drop_duplicates(id_column, keep="last").copy()
    days = pd.to_datetime(frame["date"], utc=True, errors="coerce", format="mixed").dt.normalize()
    keep = days.notna() & days.ge(start)
    if end is not None:
        keep &= days.le(end)
    frame = frame.loc[keep].copy()
    frame["date"] = days.loc[keep].dt.strftime("%Y-%m-%d")
    frame["year_month"] = days.loc[keep].dt.strftime("%Y-%m")
    return frame.reset_index(drop=True)


def _numbers(series, minimum=None, maximum=None):
    """Convert numeric strings; invalid, infinite, or out-of-range values become null."""
    values = pd.to_numeric(series, errors="coerce")
    valid = values.notna() & values.abs().ne(float("inf"))
    if minimum is not None:
        valid &= values.ge(minimum)
    if maximum is not None:
        valid &= values.le(maximum)
    return values.where(valid)


def transform_usgs(raw_data, county_geojson, *, start_date="2016-01-01",
                   end_date=None, min_magnitude=4.0):
    """Return one row per earthquake; county is determined by the epicenter.

    Input is a USGS GeoJSON FeatureCollection and the loaded county reference.
    Invalid IDs/dates/magnitudes are excluded. Unmatched locations remain in
    the output with county_match_status explaining why assignment failed.
    """
    if (not isinstance(raw_data, dict) or raw_data.get("type") != "FeatureCollection"
            or "error" in raw_data or not isinstance(raw_data.get("features"), list)):
        raise ValueError("USGS input must be a successful GeoJSON FeatureCollection")
    features = raw_data["features"]
    metadata = raw_data.get("metadata") or {}
    if (not isinstance(metadata, dict) or metadata.get("status", 200) != 200
            or metadata.get("count", len(features)) != len(features)):
        raise ValueError("USGS metadata reports a failed or inconsistent response")
    min_magnitude = float(min_magnitude)
    if not math.isfinite(min_magnitude):
        raise ValueError("min_magnitude must be finite")

    # 1. Extract source fields. USGS coordinate order is longitude, latitude, depth.
    rows = []
    for feature in features:
        if (not isinstance(feature, dict) or feature.get("type") != "Feature"
                or not isinstance(feature.get("properties"), dict)):
            raise ValueError("USGS features must contain properties")
        properties = feature["properties"]
        geometry = feature.get("geometry")
        coordinates = [None, None, None]
        if geometry is not None:
            if (not isinstance(geometry, dict) or geometry.get("type") != "Point"
                    or not isinstance(geometry.get("coordinates"), list)
                    or len(geometry["coordinates"]) < 2):
                raise ValueError("USGS geometry must be a Point with longitude/latitude")
            coordinates = geometry["coordinates"]
        rows.append({"earthquake_id": feature.get("id"), "date": properties.get("time"),
                     "place": properties.get("place"), "magnitude": properties.get("mag"),
                     "longitude": coordinates[0], "latitude": coordinates[1],
                     "depth": coordinates[2] if len(coordinates) > 2 else None})
    frame = pd.DataFrame(rows, columns=["earthquake_id", "date", "place", "magnitude",
                                        "latitude", "longitude", "depth"])

    # 2. Clean dates/numbers. USGS timestamps are milliseconds since the Unix epoch.
    frame["date"] = pd.to_datetime(_numbers(frame["date"]), unit="ms", utc=True, errors="coerce")
    frame = _clean_events(frame, "earthquake_id", start_date, end_date)
    for column, limits in {"magnitude": (None, None), "latitude": (-90, 90),
                           "longitude": (-180, 180), "depth": (None, None)}.items():
        frame[column] = _numbers(frame[column], *limits)
    frame = frame.loc[frame["magnitude"].ge(min_magnitude)].reset_index(drop=True)

    # 3. Attach county FIPS; keep offshore, outside, or ambiguous points unassigned.
    index = CountyIndex(county_geojson)
    assignments = []
    for row in frame.itertuples():
        county, status = index.locate(row.latitude, row.longitude)
        assignments.append({"county_fips": county["county_fips"] if county else None,
                            "county_name": county["county_name"] if county else None,
                            "county_match_status": status})
    for column in ["county_fips", "county_name", "county_match_status"]:
        frame[column] = pd.Series([item[column] for item in assignments], dtype="string")
    return frame


def transform_calfire(raw_data, county_geojson, *, start_date="2016-01-01", end_date=None):
    """Return one row per fire/affected county, or one null-county row if unassigned.

    Input is an Incidents response or a combined list of yearly incident objects.
    County names determine FIPS; CountyIds are internal identifiers. AcresBurned
    describes the whole event and must not be summed across its county rows.
    """
    if isinstance(raw_data, dict):
        if "error" in raw_data or "Incidents" not in raw_data:
            raise ValueError("CAL FIRE response must contain a successful Incidents list")
        incidents = raw_data["Incidents"]
    else:
        incidents = raw_data
    if not isinstance(incidents, list) or any(not isinstance(item, dict) for item in incidents):
        raise ValueError("CAL FIRE input must be a list of incident objects")

    # 1. Rename source fields and clean events before expanding their counties.
    fields = {"fire_id": "UniqueId", "date": "Started", "name": "Name",
              "location": "Location", "counties": "Counties", "county_ids": "CountyIds",
              "latitude": "Latitude", "longitude": "Longitude", "acres_burned": "AcresBurned",
              "percent_contained": "PercentContained", "structures_destroyed": "StructuresDestroyed"}
    frame = pd.DataFrame([{column: item.get(field) for column, field in fields.items()}
                          for item in incidents], columns=list(fields))
    frame = _clean_events(frame, "fire_id", start_date, end_date)
    for column, limits in {"latitude": (-90, 90), "longitude": (-180, 180),
                           "acres_burned": (0, None), "percent_contained": (0, 100),
                           "structures_destroyed": (0, None)}.items():
        frame[column] = _numbers(frame[column], *limits)

    # 2. Map affected county names. Deduplicate FIPS within each event.
    index = CountyIndex(county_geojson)
    rows = []
    for row in frame.to_dict("records"):
        names = row["counties"] if row["counties"] is not None else []
        matched, unknown = {}, []
        valid_list = isinstance(names, list) and all(isinstance(n, str) and n.strip() for n in names)
        if valid_list:
            for name in names:
                county = index.by_name.get(normalize_county_name(name))
                if county:
                    matched[county["county_fips"]] = county
                else:
                    unknown.append(name)
        status = ("invalid_county_list" if not valid_list else
                  "partially_matched" if matched and unknown else
                  "matched" if matched else "unassigned")
        row.update(county_match_status=status, matched_county_count=len(matched))
        # No matched county: retain the event rather than silently losing it.
        counties = list(matched.values()) or [{"county_fips": None, "county_name": None}]
        rows.extend({**row, **county} for county in counties)
    result = pd.DataFrame(rows, columns=[*frame.columns, "county_match_status",
                                        "matched_county_count", "county_fips", "county_name"])
    for column in ["county_fips", "county_name", "county_match_status"]:
        result[column] = result[column].astype("string")
    return result


def summarize_hazards(earthquakes, wildfires, county_geojson):
    """Summarize the two cleaned outputs into one row per county for a Census join.

    Counts use unique event IDs. Unassigned events do not enter county totals.
    Zero means no matched events in the supplied data, not verified absence.
    """
    summary = pd.DataFrame(CountyIndex(county_geojson).counties).sort_values("county_fips")
    eq = earthquakes.loc[earthquakes["county_fips"].notna()]
    fire = wildfires.loc[wildfires["county_fips"].notna()]
    eq_stats = eq.groupby("county_fips", as_index=False).agg(
        earthquake_count=("earthquake_id", "nunique"),
        max_earthquake_magnitude=("magnitude", "max"))
    fire_stats = fire.groupby("county_fips", as_index=False).agg(wildfire_count=("fire_id", "nunique"))
    summary = summary.merge(eq_stats, on="county_fips", how="left", validate="one_to_one")
    summary = summary.merge(fire_stats, on="county_fips", how="left", validate="one_to_one")
    for column in ["earthquake_count", "wildfire_count"]:
        summary[column] = summary[column].fillna(0).astype("int64")
    return summary.reset_index(drop=True)


def dataframe_records(frame):
    """Convert a DataFrame to JSON-safe records, preserving FIPS strings and nulls."""
    return json.loads(frame.to_json(orient="records", date_format="iso"))
