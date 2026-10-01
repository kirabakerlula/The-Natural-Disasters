"""FEMA disaster declarations (California): fetch -> save RAW -> clean -> save PROCESSED.

Source: OpenFEMA DisasterDeclarationsSummaries v2 (no API key needed).
Each row is one *county* (designated area) within a declaration, so a single
disaster usually produces many rows.

Run directly:  python fema_declarations.py
Or import:     from fema_declarations import run
"""
import json
import logging
import time
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
STATE = "CA"
START_YEAR = 2016
# Matches our integration goal. Set to None to keep every incident type.
INCIDENT_TYPES = ["Earthquake", "Fire"]
PAGE_SIZE = 1000  # OpenFEMA's max records per request

RAW_DIR = Path("data/raw/fema")
PROCESSED_DIR = Path("data/processed")

KEEP_COLUMNS = [
    "id", "femaDeclarationString", "disasterNumber", "state", "declarationType",
    "declarationDate", "incidentType", "declarationTitle",
    "incidentBeginDate", "incidentEndDate",
    "ihProgramDeclared", "iaProgramDeclared", "paProgramDeclared", "hmProgramDeclared",
    "fipsStateCode", "fipsCountyCode", "designatedArea",
]


def fetch_page(skip: int, retries: int = 3) -> list[dict]:
    """Fetch one page of California declarations. Retries with exponential backoff."""
    params = {
        "$filter": f"state eq '{STATE}'",
        "$top": PAGE_SIZE,
        "$skip": skip,
        "$orderby": "id",  # stable order so paging doesn't skip or repeat rows
    }
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(BASE_URL, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()["DisasterDeclarationsSummaries"]
        except (requests.RequestException, KeyError, ValueError) as exc:
            logger.warning("FEMA skip=%d attempt %d/%d failed: %s", skip, attempt, retries, exc)
            if attempt == retries:
                logger.error("Giving up on FEMA skip=%d", skip)
                raise
            time.sleep(2 ** attempt)


def fetch_all() -> list[dict]:
    """Page through the API until a short page signals the end."""
    records, skip = [], 0
    while True:
        page = fetch_page(skip)
        records.extend(page)
        logger.info("Fetched %d records so far", len(records))
        if len(page) < PAGE_SIZE:
            break
        skip += PAGE_SIZE
    return records


def save_raw(records: list[dict]) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / "fema_declarations_ca.json"
    path.write_text(json.dumps(records))
    logger.info("Saved raw -> %s (%d records)", path, len(records))
    return path


def clean(records: list[dict], start_year: int = START_YEAR) -> pd.DataFrame:
    df = pd.DataFrame(records)
    df = df[[c for c in KEEP_COLUMNS if c in df.columns]].copy()

    for col in ["declarationDate", "incidentBeginDate", "incidentEndDate"]:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    df = df.drop_duplicates(subset="id")
    df = df[df["declarationDate"].dt.year >= start_year]
    if INCIDENT_TYPES:
        df = df[df["incidentType"].isin(INCIDENT_TYPES)]

    # 5-digit county FIPS (state 2 + county 3), e.g. "06037" = Los Angeles County.
    # County code "000" means a tribal area or statewide row, not a real county,
    # so we leave county_fips empty there to avoid bad joins with Census data.
    state = df["fipsStateCode"].astype(str).str.zfill(2)
    county = df["fipsCountyCode"].astype(str).str.zfill(3)
    df["county_fips"] = (state + county).where(county != "000")

    return df.sort_values("declarationDate").reset_index(drop=True)


def run(start_year: int = START_YEAR) -> pd.DataFrame:
    records = fetch_all()
    if not records:
        raise RuntimeError("No FEMA data collected")
    save_raw(records)

    df = clean(records, start_year)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / "fema_declarations_ca_clean.csv"
    df.to_csv(out, index=False)
    logger.info("Saved processed -> %s (%d rows)", out, len(df))
    return df


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run()