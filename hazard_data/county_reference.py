"""Download and cache Census county boundaries; no reference data is bundled.

The 2024 boundary vintage matches the team's ACS 2020-2024 geography.
This reference supplies geographic identifiers, not demographic observations.
"""

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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
