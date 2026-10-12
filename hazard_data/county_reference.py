"""Download and cache Census county boundaries; no reference data is bundled.

The 2024 boundary vintage matches the team's ACS 2020-2024 geography.
This reference supplies geographic identifiers, not demographic observations.
"""

import json
import math
import os
import tempfile
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

BOUNDARY_YEAR = 2024
BOUNDARY_LAYER = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/"
    "TIGERweb/tigerWMS_ACS2024/MapServer/82"
)
BOUNDARY_URL = BOUNDARY_LAYER + "/query?" + urlencode({
    "where": "STATE='06'",
    "outFields": "GEOID,NAME,STATE,COUNTY",
    "returnGeometry": "true",
    "outSR": "4326",
    "f": "geojson",
})


def validate_reference(document: dict) -> None:
    """Reject incomplete downloads before they can replace a working cache."""
    if document.get("error") or document.get("exceededTransferLimit"):
        raise ValueError(f"Incomplete Census response: {document.get('error')}")
    if document.get("type") != "FeatureCollection":
        raise ValueError("County reference must be a GeoJSON FeatureCollection")
    features = document.get("features", [])
    codes = [str(f["properties"]["GEOID"]) for f in features]
    if len(features) != 58 or len(set(codes)) != 58:
        raise ValueError("Expected exactly 58 unique California counties")
    if any(len(c) != 5 or not c.isdigit() or not c.startswith("06") for c in codes):
        raise ValueError("Reference contains invalid California county FIPS")
    if any(f["properties"].get("STATE") != "06" or not f.get("geometry") for f in features):
        raise ValueError("Reference contains non-California or missing geometry")


def load_county_reference(cache_path: str | Path, *, refresh: bool = False) -> dict:
    """Return validated boundaries, downloading them on the first run.

    A download failure raises an exception; it must not produce a zero-count
    dataset. A valid local cache allows subsequent runs without this download.
    """
    cache_path = Path(cache_path)
    if cache_path.exists() and not refresh:
        document = json.loads(cache_path.read_text(encoding="utf-8"))
        validate_reference(document)
        return document
    request = Request(BOUNDARY_URL, headers={"User-Agent": "DSAI692-Hazard-Transform/1.0"})
    with urlopen(request, timeout=120) as response:
        document = json.load(response)
    validate_reference(document)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache_path.parent,
                                         delete=False) as output:
            temporary = Path(output.name)
            json.dump(document, output)
        os.replace(temporary, cache_path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return document


def normalize_county_name(value):
    """Normalize county labels before mapping CAL FIRE names to FIPS."""
    value = value.strip().casefold().removesuffix(" county, california").removesuffix(" county")
    return " ".join(value.split())


class CountyIndex:
    """Use names for fire counties and polygon coverage for earthquake epicenters."""

    def __init__(self, geojson):
        if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
            raise ValueError("County reference must be a GeoJSON FeatureCollection")
        self.counties, self.by_name, polygons = [], {}, []
        for feature in geojson["features"]:
            code = str(feature["properties"]["GEOID"])
            name = feature["properties"]["NAME"].removesuffix(" County")
            polygon = shape(feature["geometry"])
            if (len(code) != 5 or not code.isdigit() or not code.startswith("06")
                    or polygon.is_empty or not polygon.is_valid):
                raise ValueError("Reference has an invalid FIPS or polygon")
            key = normalize_county_name(name)
            if key in self.by_name or any(c["county_fips"] == code for c in self.counties):
                raise ValueError("Reference has duplicate counties")
            county = {"county_fips": code, "county_name": name}
            self.counties.append(county)
            self.by_name[key] = county
            polygons.append(polygon)
        if not polygons:
            raise ValueError("County reference is empty")
        self.tree = STRtree(polygons)

    def locate(self, latitude, longitude):
        """Return a county only when exactly one polygon covers the point."""
        try:
            lat, lon = float(latitude), float(longitude)
        except (TypeError, ValueError):
            return None, "invalid_coordinates"
        if not (math.isfinite(lat) and math.isfinite(lon)
                and -90 <= lat <= 90 and -180 <= lon <= 180 and lat != 0 and lon != 0):
            return None, "invalid_coordinates"
        matches = self.tree.query(Point(lon, lat), predicate="covered_by")
        if len(matches) == 0:
            return None, "outside_county_boundaries"
        if len(matches) > 1:
            return None, "ambiguous_county_boundary"
        return self.counties[int(matches[0])], "matched"
