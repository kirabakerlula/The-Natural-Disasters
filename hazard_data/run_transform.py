"""Run a local transformation check against previously collected CSV snapshots.

From the repository root:
    python -m hazard_data.run_transform --earthquakes PATH --wildfires PATH

For scheduled collection, call transform_usgs()/transform_calfire() immediately
after response.json(), or transform_raw_hazards() when both responses are ready.
This runner only checks old CSV snapshots; it does not collect hazard data or
deploy services. Generated tables and boundary caches live under ignored data/;
do not commit them.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .county_reference import BOUNDARY_URL, BOUNDARY_YEAR, load_county_reference
from .transform import transform_hazards


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--earthquakes", required=True, type=Path)
    parser.add_argument("--wildfires", required=True, type=Path)
    parser.add_argument("--start-date", default="2016-01-01")
    parser.add_argument("--end-date", help="Inclusive UTC date; omitted keeps all supplied dates")
    parser.add_argument("--boundary-cache", type=Path,
                        default=Path("data/reference/ca_counties_2024.geojson"))
    parser.add_argument("--refresh-boundaries", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/hazards"))
    parser.add_argument("--census-lookup", type=Path,
                        help="Optional Census table: validate FIPS/name compatibility, without joining demographics")
    args = parser.parse_args()
    earthquakes = pd.read_csv(args.earthquakes, dtype={"earthquake_id": "string"})
    wildfires = pd.read_csv(args.wildfires, dtype={"fire_id": "string"})
    boundaries = load_county_reference(args.boundary_cache, refresh=args.refresh_boundaries)
    tables = transform_hazards(earthquakes, wildfires, boundaries,
                              start_date=args.start_date, end_date=args.end_date)
    census_check = None
    if args.census_lookup:
        census = pd.read_csv(args.census_lookup, dtype={"FIPS": "string"})
        counties = census.loc[census["FIPS"].str.fullmatch(r"06\d{3}", na=False)]
        expected = set(tables.county_summary["county_fips"])
        if counties["FIPS"].duplicated().any() or set(counties["FIPS"]) != expected:
            raise ValueError("Census FIPS must contain the same 58 unique California counties")
        official_names = tables.county_summary.set_index("county_fips")["county_name"]
        for row in counties.to_dict("records"):
            if row["Name"] != official_names[row["FIPS"]] + " County, California":
                raise ValueError(f"Census county name disagrees with FIPS {row['FIPS']}")
        census_check = "58 county names and FIPS match; statewide row excluded; no demographics joined"
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_start_date": args.start_date,
        "requested_end_date": args.end_date,
        "boundary_vintage": BOUNDARY_YEAR,
        "boundary_url": BOUNDARY_URL,
        "boundary_cache_sha256": hashlib.sha256(args.boundary_cache.read_bytes()).hexdigest(),
        "input_snapshots": {
            "usgs": {"path": str(args.earthquakes), "rows": len(earthquakes),
                     "sha256": hashlib.sha256(args.earthquakes.read_bytes()).hexdigest()},
            "calfire": {"path": str(args.wildfires), "rows": len(wildfires),
                        "sha256": hashlib.sha256(args.wildfires.read_bytes()).hexdigest()},
        },
        "retained_date_ranges": {
            source: {"min": frame["date"].min() if len(frame) else None,
                     "max": frame["date"].max() if len(frame) else None}
            for source, frame in [("usgs", tables.earthquakes), ("calfire", tables.wildfire_events)]
        },
        "counts": {
            "earthquake_events": len(tables.earthquakes),
            "earthquake_events_assigned": int(tables.earthquakes["county_fips"].notna().sum()),
            "wildfire_events": len(tables.wildfire_events),
            "wildfire_events_assigned": int(tables.wildfire_events["matched_county_count"].gt(0).sum()),
            "wildfire_event_county_pairs": len(tables.wildfire_counties),
            "county_summary_rows": len(tables.county_summary),
        },
        "issues_by_type": tables.issues["issue"].value_counts().to_dict(),
        "census_compatibility_check": census_check,
        "interpretation": [
            "A wildfire is counted once in each named affected California county.",
            "Do not sum county wildfire counts to obtain a statewide unique event count.",
            "Unassigned events stay in event tables and issues, not county aggregates.",
            "Zero means no matched events in the supplied snapshot, not verified absence of disasters.",
            "Maximum magnitude is null when no earthquake is assigned.",
            "Recent-year snapshots may be partial; no annualized rates are calculated.",
            "These tables contain no FEMA measures or Census demographic values.",
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in vars(tables).items():
        frame.to_csv(args.output_dir / f"{name}.csv", index=False)
    # JSON retains FIPS strings and serializes missing magnitude as null.
    tables.county_summary.to_json(args.output_dir / "county_summary.json",
                                 orient="records", indent=2)
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": str(args.output_dir), "counts": metadata["counts"],
                      "issues_by_type": metadata["issues_by_type"],
                      "census_compatibility_check": census_check}, indent=2))


if __name__ == "__main__":
    main()
