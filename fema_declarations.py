# Download California FEMA disaster declarations, clean them,
# save them locally, and upload them to our GCS bucket.

import json
import os
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from google.cloud import storage

load_dotenv()  # reads GCS_BUCKET from .env
BUCKET_NAME = os.environ["GCS_BUCKET"]

URL = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"

# These tribal areas have county code "000" in FEMA's data,
# so we look up which county each one is in.
TRIBAL_AREAS = {
    "Hopland Rancheria (Indian Reservation)": "06045",      # Mendocino
    "Morongo Indian Reservation": "06065",                  # Riverside
    "Rohnerville Rancheria (Indian Reservation)": "06023",  # Humboldt
}

COLUMNS = [
    "id", "femaDeclarationString", "disasterNumber", "state", "declarationType",
    "declarationDate", "incidentType", "declarationTitle",
    "incidentBeginDate", "incidentEndDate",
    "ihProgramDeclared", "iaProgramDeclared", "paProgramDeclared", "hmProgramDeclared",
    "fipsStateCode", "fipsCountyCode", "designatedArea",
]


def get_data():
    # The API gives at most 1000 rows at a time, so keep asking
    # for the next 1000 until we get fewer than that back.
    records = []
    skip = 0
    while True:
        params = {
            "$filter": "state eq 'CA'",
            "$top": 1000,
            "$skip": skip,
            "$orderby": "id",
        }
        response = requests.get(URL, params=params, timeout=60)
        response.raise_for_status()
        page = response.json()["DisasterDeclarationsSummaries"]
        records += page
        print(f"Got {len(records)} records so far")
        if len(page) < 1000:
            break
        skip += 1000
    return records


def clean_data(records):
    df = pd.DataFrame(records)[COLUMNS]

    for col in ["declarationDate", "incidentBeginDate", "incidentEndDate"]:
        df[col] = pd.to_datetime(df[col], utc=True)

    # Keep fires and earthquakes from 2016 onward
    df = df.drop_duplicates(subset="id")
    df = df[df["declarationDate"].dt.year >= 2016]
    df = df[df["incidentType"].isin(["Fire", "Earthquake"])]

    # Build a 5-digit county code, e.g. "06" + "037" = "06037" (Los Angeles)
    state = df["fipsStateCode"].astype(str).str.zfill(2)
    county = df["fipsCountyCode"].astype(str).str.zfill(3)
    df["county_fips"] = state + county

    # County "000" means a tribal area, so swap in the real county
    df["is_tribal_area"] = county == "000"
    tribal_counties = df["designatedArea"].map(TRIBAL_AREAS)
    df.loc[df["is_tribal_area"], "county_fips"] = tribal_counties

    return df.sort_values("declarationDate")


def upload(path):
    bucket = storage.Client().bucket(BUCKET_NAME)
    bucket.blob(str(path)).upload_from_filename(path)
    print(f"Uploaded to gs://{BUCKET_NAME}/{path}")


def main():
    records = get_data()

    raw_path = Path("data/raw/fema/fema_declarations_ca.json")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(records))
    print(f"Saved {len(records)} raw records to {raw_path}")

    df = clean_data(records)
    clean_path = Path("data/processed/fema_declarations_ca_clean.csv")
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(clean_path, index=False)
    print(f"Saved {len(df)} clean rows to {clean_path}")

    upload(raw_path)
    upload(clean_path)


if __name__ == "__main__":
    main()