"""Clean earthquake and fire data and add county FIPS. 
County boundaries are downloaded once when this module is imported."""

import json
import io
import pandas as pd
from county_reference import (
    find_earthquake_county,
    find_fire_county,
    load_county_reference,
)

# Download county boundaries once and reuse them.
COUNTY_GEOJSON = load_county_reference()


def transform_usgs(
    raw_data,
    county_geojson=None,
    start_date="2016-01-01",
    end_date=None,
    min_magnitude=4.0,
):
    """Clean USGS raw JSON and return one row per earthquake.
    Leave county fields empty if no county matches."""

    # Read earthquake fields from the raw JSON.
    # USGS coordinates are longitude, latitude, then depth.
    columns = [
        "earthquake_id", "date", "place", "magnitude",
        "latitude", "longitude", "depth",
    ]
    rows = []
    for feature in raw_data["features"]:
        properties = feature["properties"]
        coordinates = [None, None, None]
        if feature.get("geometry") is not None:
            coordinates = feature["geometry"]["coordinates"]

        depth = None
        if len(coordinates) > 2:
            depth = coordinates[2]

        rows.append({
            "earthquake_id": feature.get("id"),
            "date": properties.get("time"),
            "place": properties.get("place"),
            "magnitude": properties.get("mag"),
            "latitude": coordinates[1],
            "longitude": coordinates[0],
            "depth": depth,
        })
    df = pd.DataFrame(rows, columns=columns)

    # Convert USGS time from milliseconds to UTC.
    df["date"] = pd.to_numeric(df["date"], errors="coerce")
    df["date"] = pd.to_datetime(
        df["date"], unit="ms", utc=True, errors="coerce"
    )

    # Remove earthquakes without IDs or valid dates.
    df = df.dropna(subset=["earthquake_id", "date"])

    # For duplicate IDs, keep the last record in the input.
    df = df.drop_duplicates(subset=["earthquake_id"], keep="last")
    df = df.copy()
    df["year_month"] = df["date"].dt.strftime("%Y-%m")
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    # Keep events between the start and end dates, including both dates.
    df = df[df["date"] >= start_date].copy()
    if end_date is not None:
        df = df[df["date"] <= end_date].copy()

    # Convert values to numbers. Values that cannot be read become missing.
    numeric_columns = ["magnitude", "latitude", "longitude", "depth"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

        # Set positive and negative infinity to missing.
        df.loc[df[column] == float("inf"), column] = None
        df.loc[df[column] == -float("inf"), column] = None

    # Set coordinates outside the allowed range to missing.
    df.loc[df["latitude"] < -90, "latitude"] = None
    df.loc[df["latitude"] > 90, "latitude"] = None
    df.loc[df["longitude"] < -180, "longitude"] = None
    df.loc[df["longitude"] > 180, "longitude"] = None

    # Keep earthquakes at or above the minimum magnitude.
    df = df[df["magnitude"] >= min_magnitude].copy()

    # Use the downloaded boundaries if none are provided.
    if county_geojson is None:
        county_geojson = COUNTY_GEOJSON

    # Start with empty county fields. Fill them when a county matches.
    df["county_name"] = None
    df["county_fips"] = None

    # index is the table row label, not the earthquake ID.
    for index in df.index:
        latitude = df.loc[index, "latitude"]
        longitude = df.loc[index, "longitude"]
        county_name, county_fips = find_earthquake_county(
            latitude, longitude, county_geojson
        )
        df.loc[index, "county_name"] = county_name
        df.loc[index, "county_fips"] = county_fips

    return df


def transform_calfire(
    raw_data,
    county_geojson=None,
    start_date="2016-01-01",
    end_date=None,
):
    """Create a separate row for each county affected by a fire.
    If no county matches, keep one row with empty county fields.
    Acres burned is the total for the fire, not for each county."""

    if county_geojson is None:
        county_geojson = COUNTY_GEOJSON

    # Read the incident list from an API response or a combined yearly list.
    if type(raw_data) == dict:
        incidents = raw_data["Incidents"]
    else:
        incidents = raw_data

    # Read fire fields from the raw JSON.
    columns = [
        "fire_id", "date", "name", "location", "counties", "county_ids",
        "latitude", "longitude", "acres_burned", "percent_contained",
        "structures_destroyed",
    ]
    rows = []
    for incident in incidents:
        rows.append({
            "fire_id": incident.get("UniqueId"),
            "date": incident.get("Started"),
            "name": incident.get("Name"),
            "location": incident.get("Location"),
            "counties": incident.get("Counties"),
            "county_ids": incident.get("CountyIds"),
            "latitude": incident.get("Latitude"),
            "longitude": incident.get("Longitude"),
            "acres_burned": incident.get("AcresBurned"),
            "percent_contained": incident.get("PercentContained"),
            "structures_destroyed": incident.get("StructuresDestroyed"),
        })
    df = pd.DataFrame(rows, columns=columns)

    # Convert dates to UTC. Dates that cannot be read become missing.
    df["date"] = pd.to_datetime(
        df["date"], utc=True, errors="coerce", format="mixed"
    )

    # Remove fires without valid dates.
    df = df.dropna(subset=["date"])
    df = df.copy()
    df["year_month"] = df["date"].dt.strftime("%Y-%m")
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    # Keep fires between the start and end dates, including both dates.
    df = df[df["date"] >= start_date].copy()
    if end_date is not None:
        df = df[df["date"] <= end_date].copy()

    # Convert values to numbers. Values that cannot be read become missing.
    numeric_columns = [
        "latitude", "longitude", "acres_burned",
        "percent_contained", "structures_destroyed",
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

        # Set positive and negative infinity to missing.
        df.loc[df[column] == float("inf"), column] = None
        df.loc[df[column] == -float("inf"), column] = None

    # Set values outside the allowed range to missing.
    df.loc[df["latitude"] < -90, "latitude"] = None
    df.loc[df["latitude"] > 90, "latitude"] = None
    df.loc[df["longitude"] < -180, "longitude"] = None
    df.loc[df["longitude"] > 180, "longitude"] = None
    df.loc[df["acres_burned"] < 0, "acres_burned"] = None
    df.loc[df["percent_contained"] < 0, "percent_contained"] = None
    df.loc[df["percent_contained"] > 100, "percent_contained"] = None
    df.loc[df["structures_destroyed"] < 0, "structures_destroyed"] = None

    # Remove fires without IDs. For duplicate IDs, keep the last input record.
    df = df.dropna(subset=["fire_id"])
    df = df.drop_duplicates(subset=["fire_id"], keep="last")
    df = df.copy()

    # A fire can affect several counties. Create a row for each matched county.
    rows = []
    for fire in df.to_dict("records"):
        counties = fire["counties"]
        if type(counties) != list:
            counties = []

        county_found = False
        for county in counties:
            county_name, county_fips = find_fire_county(county, county_geojson)
            if county_fips is not None:
                row = fire.copy()
                row["county_name"] = county_name
                row["county_fips"] = county_fips
                rows.append(row)
                county_found = True

        # If no county matches, keep the fire with empty county fields.
        if county_found == False:
            row = fire.copy()
            row["county_name"] = None
            row["county_fips"] = None
            rows.append(row)

    columns = list(df.columns)
    columns.append("county_name")
    columns.append("county_fips")
    result = pd.DataFrame(rows, columns=columns)

    # Keep one row for each fire and county combination.
    result = result.drop_duplicates(subset=["fire_id", "county_fips"])
    return result


def summarize_hazards(earthquake_csv, wildfire_csv, county_geojson=None):
    """Create one row for each county.
    Count the earthquakes and fires in that county.
    Find the largest earthquake magnitude in that county.."""

    # convert from csvs to dataframes
    earthquakes = pd.read_csv(io.BytesIO(earthquake_csv), dtype={"county_fips": "string"})
    wildfires = pd.read_csv(io.BytesIO(wildfire_csv), dtype={"county_fips": "string"})

    if county_geojson is None:
        county_geojson = COUNTY_GEOJSON

    # Count each event ID once per county.
    rows = []
    for county in county_geojson["features"]:
        county_fips = county["properties"]["GEOID"]
        county_name = county["properties"]["NAME"].replace(" County", "")

        # Select the earthquakes and fires assigned to this county.
        county_earthquakes = earthquakes[
            earthquakes["county_fips"] == county_fips
        ]
        county_fires = wildfires[wildfires["county_fips"] == county_fips]

        rows.append({
            "county_fips": county_fips,
            "county_name": county_name,
            "earthquake_count": county_earthquakes["earthquake_id"].nunique(),
            "max_earthquake_magnitude": county_earthquakes["magnitude"].max(),
            "wildfire_count": county_fires["fire_id"].nunique(),
        })

    summary = pd.DataFrame(rows)

    # Sort the county rows by FIPS.
    summary = summary.sort_values("county_fips")
    
    return summary