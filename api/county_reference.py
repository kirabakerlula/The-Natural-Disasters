"""Download county boundaries and match earthquake/fire locations to FIPS."""

import pandas as pd
import requests
from shapely.geometry import Point, shape
# Shapely turns boundaries into polygons and checks whether they cover a point.

def load_county_reference():
    """Download California's 2024 county boundaries as GeoJSON."""

    url = (
        "https://tigerweb.geo.census.gov/arcgis/rest/services/"
        "TIGERweb/tigerWMS_ACS2024/MapServer/82/query"
    )
    params = {
        "where": "STATE = '06'",
        "outFields": "GEOID,NAME,STATE,COUNTY",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }

    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()
    county_geojson = response.json()

    # Check that all 58 counties were returned.
    if len(county_geojson.get("features", [])) != 58:
        raise ValueError("Expected 58 California counties.")

    return county_geojson


def find_earthquake_county(latitude, longitude, county_geojson):
    """Return county name and FIPS when exactly one county matches."""

    if pd.isna(latitude) or pd.isna(longitude):
        return None, None

    # Shapely uses longitude first, then latitude.
    point = Point(longitude, latitude)
    matches = []

    for county in county_geojson["features"]:
        # Convert each boundary once and reuse it in memory.
        if "boundary" not in county:
            county["boundary"] = shape(county["geometry"])

        boundary = county["boundary"]
        if boundary.covers(point):
            county_name = county["properties"]["NAME"].replace(" County", "")
            county_fips = county["properties"]["GEOID"]
            matches.append((county_name, county_fips))

    if len(matches) == 1:
        return matches[0]

    return None, None


def find_fire_county(county_name, county_geojson):
    """Return the official county name and FIPS from a fire's county name."""

    if type(county_name) != str:
        return None, None

    # Remove extra spaces and standardize the county name.
    county_name = county_name.strip().lower()
    county_name = county_name.replace(" county, california", "")
    county_name = county_name.replace(" county", "")

    for county in county_geojson["features"]:
        reference_name = county["properties"]["NAME"].replace(" County", "")
        if reference_name.lower() == county_name:
            county_fips = county["properties"]["GEOID"]
            return reference_name, county_fips

    return None, None