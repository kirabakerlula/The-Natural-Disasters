# Download California FEMA disaster declarations and FEMA housing aid,
# clean them, save them locally, and upload them to our GCS bucket.

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
# Housing aid per disaster, county and zip code, for home owners and renters
OWNERS_URL = "https://www.fema.gov/api/open/v2/HousingAssistanceOwners"
RENTERS_URL = "https://www.fema.gov/api/open/v2/HousingAssistanceRenters"

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

AID_COLUMNS = [
    "validRegistrations",         # people who applied
    "approvedForFemaAssistance",  # people who were approved
    "totalApprovedIhpAmount",     # dollars approved
]


def get_data(url, key):
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
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        page = response.json()[key]
        records += page
        print(f"{key}: got {len(records)} records so far")
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


def add_aid(df, owner_records, renter_records):
    # Owners and renters together, only for the disasters we kept,
    # added up over zip codes -> one row per disaster + county.
    aid = pd.concat([pd.DataFrame(owner_records),
                     pd.DataFrame(renter_records)])
    aid = aid[aid["disasterNumber"].isin(df["disasterNumber"])]
    aid = aid.groupby(["disasterNumber", "county"])[AID_COLUMNS].sum()
    aid = aid.reset_index()

    # Both datasets write counties the same way, e.g. "Butte (County)".
    # "left" keeps counties that were declared but got no housing aid.
    df = df.merge(aid, how="left",
                  left_on=["disasterNumber", "designatedArea"],
                  right_on=["disasterNumber", "county"])
    df = df.drop(columns="county")
    df[AID_COLUMNS] = df[AID_COLUMNS].fillna(0)

    # How each area was treated (blank when nobody applied)
    df["approval_rate"] = (df["approvedForFemaAssistance"]
                           / df["validRegistrations"])
    df["dollars_per_applicant"] = (df["totalApprovedIhpAmount"]
                                   / df["validRegistrations"])
    return df


def save_json(records, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records))
    print(f"Saved {len(records)} raw records to {path}")


def upload(path):
    bucket = storage.Client().bucket(BUCKET_NAME)
    bucket.blob(str(path)).upload_from_filename(path)
    print(f"Uploaded to gs://{BUCKET_NAME}/{path}")


def main():
    records = get_data(URL, "DisasterDeclarationsSummaries")
    owners = get_data(OWNERS_URL, "HousingAssistanceOwners")
    renters = get_data(RENTERS_URL, "HousingAssistanceRenters")

    raw_path = Path("data/raw/fema/fema_declarations_ca.json")
    owners_path = Path("data/raw/fema/housing_assistance_owners_ca.json")
    renters_path = Path("data/raw/fema/housing_assistance_renters_ca.json")
    save_json(records, raw_path)
    save_json(owners, owners_path)
    save_json(renters, renters_path)

    df = clean_data(records)
    df = add_aid(df, owners, renters)

    clean_path = Path("data/processed/fema_declarations_ca_clean.csv")
    clean_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(clean_path, index=False)
    print(f"Saved {len(df)} clean rows to {clean_path}")

    for path in [raw_path, owners_path, renters_path, clean_path]:
        upload(path)


if __name__ == "__main__":
    main()