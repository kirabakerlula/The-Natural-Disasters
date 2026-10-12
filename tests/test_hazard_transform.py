"""Offline behavior tests with synthetic adjacent county rectangles."""

import unittest

import pandas as pd

from hazard_data.county_reference import CountyIndex, validate_reference
from hazard_data.transform import summarize_hazards, transform_calfire, transform_usgs


def reference():
    def county(code, name, west, east):
        return {"type": "Feature", "properties": {"GEOID": code, "NAME": name + " County"},
                "geometry": {"type": "Polygon", "coordinates": [
                    [[west, 35], [east, 35], [east, 37], [west, 37], [west, 35]]
                ]}}
    return {"type": "FeatureCollection", "features": [
        county("06001", "Alameda", -123, -122), county("06003", "Alpine", -122, -121)]}


def earthquake(event_id, date="2024-01-01", latitude=36, longitude=-122.5, magnitude=4.2):
    try:
        timestamp = pd.Timestamp(date).value // 1_000_000
    except (ValueError, TypeError):
        timestamp = None
    return {"type": "Feature", "id": event_id, "properties": {"time": timestamp, "mag": magnitude},
            "geometry": {"type": "Point", "coordinates": [longitude, latitude, 5]}}


def earthquakes(features=None, **options):
    return transform_usgs({"type": "FeatureCollection", "features": features or []}, reference(), **options)


def fire(event_id, counties, date="2024-01-01"):
    return {"UniqueId": event_id, "Started": date, "Counties": counties}


def wildfires(incidents=None, **options):
    return transform_calfire({"Incidents": incidents or []}, reference(), **options)


class HazardTransformTests(unittest.TestCase):
    def test_spatial_assignment_outside_and_shared_boundary(self):
        events = earthquakes([
            earthquake("inside"), earthquake("outside", longitude=-120),
            earthquake("boundary", longitude=-122), earthquake("bad", latitude=0, longitude=0),
        ]).set_index("earthquake_id")
        self.assertEqual(events.loc["inside", "county_fips"], "06001")
        self.assertEqual(events.loc["outside", "county_match_status"], "outside_county_boundaries")
        self.assertEqual(events.loc["boundary", "county_match_status"], "ambiguous_county_boundary")
        self.assertEqual(events.loc["bad", "county_match_status"], "invalid_coordinates")
        self.assertEqual(len(events), 4)
        summary = summarize_hazards(events.reset_index(), wildfires(), reference())
        self.assertEqual(summary["earthquake_count"].sum(), 1)

    def test_multicounty_names_and_unassigned_event_retention(self):
        events = wildfires([
            fire("both", ["Alameda", "Alpine", "Alameda"]),
            fire("mixed", ["Alameda", "Mexico"]), fire("outside", ["Oregon"]), fire("missing", []),
        ])
        summary = summarize_hazards(earthquakes(), events, reference()).set_index("county_fips")
        self.assertEqual(summary.loc["06001", "wildfire_count"], 2)
        self.assertEqual(summary.loc["06003", "wildfire_count"], 1)
        self.assertEqual(events["fire_id"].nunique(), 4)
        self.assertEqual(events["county_fips"].notna().sum(), 3)
        self.assertEqual(events.set_index("fire_id").loc["mixed", "county_match_status"], "partially_matched")

    def test_duplicate_ids_keep_last_supplied_record(self):
        eq = earthquakes([earthquake("same", magnitude=4.2), earthquake("same", magnitude=5.2)])
        fires = wildfires([fire("samefire", ["Alameda"]), fire("samefire", ["Alpine"])])
        summary = summarize_hazards(eq, fires, reference()).set_index("county_fips")
        self.assertEqual(summary.loc["06001", "earthquake_count"], 1)
        self.assertEqual(summary.loc["06001", "max_earthquake_magnitude"], 5.2)
        self.assertEqual(summary.loc["06001", "wildfire_count"], 0)
        self.assertEqual(summary.loc["06003", "wildfire_count"], 1)

    def test_utc_end_day_invalid_dates_and_magnitude_filter(self):
        events = earthquakes([
            earthquake("end", "2024-12-31T23:59:59Z"), earthquake("next", "2025-01-01"),
            earthquake("bad", "not a date"), earthquake("small", magnitude=3.9),
        ], start_date="2024-01-01", end_date="2024-12-31")
        self.assertEqual(events["earthquake_id"].tolist(), ["end"])

    def test_empty_collections_keep_county_grid_and_null_magnitude(self):
        summary = summarize_hazards(earthquakes(), wildfires(), reference())
        self.assertEqual(summary["county_fips"].tolist(), ["06001", "06003"])
        self.assertEqual(summary["earthquake_count"].sum(), 0)
        self.assertTrue(summary["max_earthquake_magnitude"].isna().all())

    def test_malformed_county_list_is_retained_as_unassigned(self):
        events = wildfires([fire("bad", "[not-valid]")])
        self.assertEqual(events.iloc[0]["county_match_status"], "invalid_county_list")
        self.assertTrue(pd.isna(events.iloc[0]["county_fips"]))

    def test_invalid_date_window_raises(self):
        for options in [{"start_date": "2025-01-01", "end_date": "2024-01-01"},
                        {"start_date": "NaT"}, {"end_date": "NaT"}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                earthquakes(**options)

    def test_partial_or_duplicate_county_reference_raises(self):
        with self.assertRaises(ValueError):
            validate_reference(reference())
        with self.assertRaises(ValueError):
            validate_reference({"error": {"code": 500}})
        duplicate = reference()
        duplicate["features"].append(duplicate["features"][0])
        with self.assertRaises(ValueError):
            CountyIndex(duplicate)

    def test_missing_id_and_nonfinite_magnitude_are_excluded(self):
        events = earthquakes([earthquake(None), earthquake("infinite", magnitude=float("inf"))])
        self.assertTrue(events.empty)
        with self.assertRaises(ValueError):
            earthquakes(min_magnitude=float("nan"))

    def test_fire_utc_dates_and_normalized_county_names(self):
        events = wildfires([fire("offset", [" ALAMEDA COUNTY, CALIFORNIA "],
                                "2024-12-31T20:00:00-08:00")],
                          start_date="2025-01-01", end_date="2025-01-01")
        self.assertEqual(events.iloc[0]["date"], "2025-01-01")
        self.assertEqual(events.iloc[0]["county_fips"], "06001")


if __name__ == "__main__":
    unittest.main()
