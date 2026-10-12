"""Offline tests using synthetic rectangles, not real county boundaries."""

import unittest

import pandas as pd

from hazard_data.county_reference import validate_reference
from hazard_data.transform import transform_hazards


def reference():
    def county(code, name, west, east):
        return {"type": "Feature", "properties": {"GEOID": code, "NAME": name + " County"},
                "geometry": {"type": "Polygon", "coordinates": [
                    [[west, 35], [east, 35], [east, 37], [west, 37], [west, 35]]
                ]}}
    return {"type": "FeatureCollection", "features": [
        county("06001", "Alameda", -123, -122), county("06003", "Alpine", -122, -121)]}


def earthquakes(records=None):
    return pd.DataFrame(records or [], columns=["earthquake_id", "date", "latitude", "longitude", "magnitude"])


def wildfires(records=None):
    return pd.DataFrame(records or [], columns=["fire_id", "date", "counties", "latitude", "longitude"])


class HazardTransformTests(unittest.TestCase):
    def test_spatial_assignment_outside_and_shared_boundary(self):
        eq = earthquakes([
            ["inside", "2024-01-01", 36, -122.5, 4.2],
            ["outside", "2024-01-01", 36, -120, 4.3],
            ["boundary", "2024-01-01", 36, -122, 4.4],
            ["bad", "2024-01-01", 0, 0, 4.5],
        ])
        result = transform_hazards(eq, wildfires(), reference())
        events = result.earthquakes.set_index("earthquake_id")
        self.assertEqual(events.loc["inside", "county_fips"], "06001")
        self.assertEqual(events.loc["outside", "county_match_status"], "outside_county_boundaries")
        self.assertEqual(events.loc["boundary", "county_match_status"], "ambiguous_county_boundary")
        self.assertEqual(events.loc["bad", "county_match_status"], "invalid_coordinates")
        self.assertEqual(len(events), 4)  # unassigned events are retained
        self.assertEqual(result.county_summary["earthquake_count"].sum(), 1)

    def test_multicounty_counting_uses_names_and_preserves_event_identity(self):
        fires = wildfires([
            ["both", "2024-01-01", "['Alameda', 'Alpine', 'Alameda']", 0, 0],
            ["mixed", "2024-01-01", ["Alameda", "Mexico"], 36, -122.5],
            ["outside", "2024-01-01", ["State of Oregon"], 36, -122.5],
            ["missing", "2024-01-01", "[]", 36, -122.5],
        ])
        fires["county_ids"] = ["wrong", "wrong", "wrong", "wrong"]
        result = transform_hazards(earthquakes(), fires, reference())
        summary = result.county_summary.set_index("county_fips")
        self.assertEqual(summary.loc["06001", "wildfire_count"], 2)
        self.assertEqual(summary.loc["06003", "wildfire_count"], 1)
        self.assertEqual(len(result.wildfire_counties), 3)
        self.assertEqual(result.wildfire_counties["fire_id"].nunique(), 2)
        self.assertEqual(len(result.wildfire_events), 4)
        self.assertEqual(result.wildfire_events.set_index("fire_id").loc["mixed", "county_match_status"], "partially_matched")

    def test_duplicate_ids_are_not_counted_twice_and_last_update_wins(self):
        eq = earthquakes([
            ["same", "2024-01-01", 36, -122.5, 4.2],
            ["same", "2024-01-01", 36, -122.5, 5.2],
        ])
        fires = wildfires([
            ["samefire", "2024-01-01", ["Alameda"], 36, -122.5],
            ["samefire", "2024-01-01", ["Alpine"], 36, -121.5],
        ])
        result = transform_hazards(eq, fires, reference())
        summary = result.county_summary.set_index("county_fips")
        self.assertEqual(summary.loc["06001", "earthquake_count"], 1)
        self.assertEqual(summary.loc["06001", "max_earthquake_magnitude"], 5.2)
        self.assertEqual(summary.loc["06001", "wildfire_count"], 0)
        self.assertEqual(summary.loc["06003", "wildfire_count"], 1)
        self.assertEqual((result.issues["issue"] == "duplicate_event_id").sum(), 2)

    def test_utc_day_filter_includes_end_day_and_audits_bad_dates(self):
        eq = earthquakes([
            ["end", "2024-12-31T23:59:59Z", 36, -122.5, 4.2],
            ["next", "2025-01-01", 36, -122.5, 4.2],
            ["bad", "not a date", 36, -122.5, 4.2],
            ["small", "2024-01-01", 36, -122.5, 3.9],
        ])
        result = transform_hazards(eq, wildfires(), reference(), start_date="2024-01-01", end_date="2024-12-31")
        self.assertEqual(result.earthquakes["earthquake_id"].tolist(), ["end"])
        self.assertEqual(set(result.issues["issue"]), {"outside_requested_period", "invalid_date", "below_minimum_magnitude"})

    def test_empty_successful_snapshots_keep_county_grid_and_null_magnitude(self):
        result = transform_hazards(earthquakes(), wildfires(), reference())
        self.assertEqual(result.county_summary["county_fips"].tolist(), ["06001", "06003"])
        self.assertEqual(result.county_summary["earthquake_count"].sum(), 0)
        self.assertTrue(result.county_summary["max_earthquake_magnitude"].isna().all())

    def test_bad_county_list_is_reported_not_executed(self):
        result = transform_hazards(earthquakes(), wildfires([
            ["bad", "2024-01-01", "[not-valid]", 36, -122.5],
        ]), reference())
        self.assertIn("invalid_county_list", result.issues["issue"].tolist())
        self.assertEqual(len(result.wildfire_events), 1)

    def test_schema_and_period_errors_raise(self):
        with self.assertRaises(ValueError):
            transform_hazards(pd.DataFrame(), wildfires(), reference())
        with self.assertRaises(ValueError):
            transform_hazards(earthquakes(), wildfires(), reference(), start_date="2025-01-01", end_date="2024-01-01")

    def test_partial_reference_download_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_reference(reference())
        with self.assertRaises(ValueError):
            validate_reference({"error": {"code": 500}})

    def test_missing_id_and_nonfinite_magnitude_are_audited(self):
        eq = earthquakes([
            [None, "2024-01-01", 36, -122.5, 4.2],
            ["infinite", "2024-01-01", 36, -122.5, float("inf")],
        ])
        result = transform_hazards(eq, wildfires(), reference())
        self.assertEqual(len(result.earthquakes), 0)
        self.assertEqual(set(result.issues["issue"]), {"missing_event_id", "invalid_magnitude"})

    def test_missing_period_and_pretransformed_input_raise(self):
        with self.assertRaises(ValueError):
            transform_hazards(earthquakes(), wildfires(), reference(), start_date="NaT")
        eq = earthquakes()
        eq["county_fips"] = pd.Series(dtype="string")
        with self.assertRaises(ValueError):
            transform_hazards(eq, wildfires(), reference())


if __name__ == "__main__":
    unittest.main()
