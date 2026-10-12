"""Offline raw-response tests using source field names and synthetic counties."""

import copy
import json
import unittest

import pandas as pd

from hazard_data.transform import (
    dataframe_records, transform_calfire, transform_raw_hazards, transform_usgs,
)
from test_hazard_transform import reference


def usgs_feature(event_id="eq-1", date="2024-01-02T00:30:00Z", coordinates=None):
    return {"type": "Feature", "id": event_id,
            "properties": {"time": int(pd.Timestamp(date).timestamp() * 1000),
                           "mag": 4.6, "place": "Example place label"},
            "geometry": {"type": "Point", "coordinates": coordinates or [-122.5, 36, 7.5]}}


def usgs_response(features=None):
    features = [] if features is None else features
    return {"type": "FeatureCollection", "metadata": {"status": 200, "count": len(features)},
            "features": features}


def fire_record(event_id="fire-1", counties=None):
    return {"UniqueId": event_id, "Name": "Example fire", "Started": "2024-01-02T01:30:00Z",
            "Counties": ["Alameda", "Alpine"] if counties is None else counties,
            "CountyIds": [1, 2], "Latitude": "36", "Longitude": "-122.5",
            "AcresBurned": "125.5", "PercentContained": "95", "StructuresDestroyed": "2"}


class RawHazardTransformTests(unittest.TestCase):
    def test_usgs_epoch_milliseconds_coordinate_order_and_fips(self):
        raw = usgs_response([usgs_feature()])
        before = copy.deepcopy(raw)
        frame = transform_usgs(raw, reference())
        row = frame.iloc[0]
        self.assertEqual(row["date"], "2024-01-02")
        self.assertEqual(row["year_month"], "2024-01")
        self.assertEqual(row["latitude"], 36)
        self.assertEqual(row["longitude"], -122.5)
        self.assertEqual(row["depth"], 7.5)
        self.assertEqual(row["county_fips"], "06001")
        self.assertEqual(row["place"], "Example place label")
        self.assertEqual(raw, before)
        self.assertEqual(frame.attrs["issues"], [])

    def test_usgs_invalid_time_and_null_geometry_are_audited(self):
        invalid_time = usgs_feature("bad-time")
        invalid_time["properties"]["time"] = "not milliseconds"
        no_geometry = usgs_feature("no-geometry")
        no_geometry["geometry"] = None
        frame = transform_usgs(usgs_response([invalid_time, no_geometry]), reference())
        self.assertEqual(frame["earthquake_id"].tolist(), ["no-geometry"])
        self.assertTrue(pd.isna(frame.iloc[0]["county_fips"]))
        self.assertEqual({issue["issue"] for issue in frame.attrs["issues"]},
                         {"invalid_date", "invalid_coordinates"})

    def test_usgs_malformed_failed_or_inconsistent_responses_raise(self):
        inputs = [None, {}, {"error": "failed"},
                  {"type": "FeatureCollection", "features": {}},
                  {**usgs_response(), "metadata": {"status": 500, "count": 0}},
                  {**usgs_response(), "metadata": {"status": 200, "count": 1}},
                  usgs_response([{"type": "Feature", "properties": None}])]
        wrong_geometry = usgs_feature()
        wrong_geometry["geometry"]["type"] = "LineString"
        inputs.append(usgs_response([wrong_geometry]))
        for raw in inputs:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                transform_usgs(raw, reference())

    def test_fire_output_is_event_county_with_numeric_fields_and_no_input_mutation(self):
        raw = {"Incidents": [fire_record()]}
        before = copy.deepcopy(raw)
        frame = transform_calfire(raw, reference())
        self.assertEqual(frame["county_fips"].tolist(), ["06001", "06003"])
        self.assertEqual(frame["fire_id"].nunique(), 1)
        self.assertEqual(frame["matched_county_count"].tolist(), [2, 2])
        self.assertEqual(frame["acres_burned"].tolist(), [125.5, 125.5])
        self.assertEqual(frame["percent_contained"].tolist(), [95, 95])
        self.assertEqual(frame["structures_destroyed"].tolist(), [2, 2])
        self.assertEqual(frame["county_ids"].tolist(), [[1, 2], [1, 2]])
        self.assertEqual(raw, before)

    def test_fire_unknown_county_and_invalid_numbers_preserved_as_null(self):
        fire = fire_record(counties=["Unknown County"])
        fire.update(AcresBurned=-1, PercentContained=101, StructuresDestroyed="bad")
        frame = transform_calfire({"Incidents": [fire]}, reference())
        self.assertEqual(len(frame), 1)
        self.assertTrue(pd.isna(frame.iloc[0]["county_fips"]))
        self.assertEqual(frame.iloc[0]["county_match_status"], "unassigned")
        self.assertEqual(frame.iloc[0]["matched_county_count"], 0)
        records = dataframe_records(frame)
        for field in ["county_fips", "acres_burned", "percent_contained", "structures_destroyed"]:
            self.assertIsNone(records[0][field])
        self.assertEqual(sum(issue["issue"] == "invalid_numeric_field"
                             for issue in frame.attrs["issues"]), 3)
        json.dumps(records, allow_nan=False)

    def test_fire_combined_yearly_incidents_deduplicate_last_update(self):
        first = fire_record(counties=["Alameda"])
        latest = fire_record(counties=["Alpine"])
        latest["AcresBurned"] = 200
        frame = transform_calfire([first, latest], reference())
        self.assertEqual(frame["county_fips"].tolist(), ["06003"])
        self.assertEqual(frame["acres_burned"].tolist(), [200])
        self.assertEqual(frame.attrs["issues"][0]["issue"], "duplicate_event_id")

    def test_calfire_missing_incidents_is_not_an_empty_success(self):
        for raw in [None, {}, {"error": "failed"}, {"Incidents": None},
                    {"Incidents": {}}, {"Incidents": [None]}]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                transform_calfire(raw, reference())

    def test_empty_successful_raw_snapshots_and_json_null_magnitude(self):
        tables = transform_raw_hazards(usgs_response(), {"Incidents": []}, reference())
        self.assertEqual(len(tables.county_summary), 2)
        self.assertTrue(transform_usgs(usgs_response(), reference()).empty)
        self.assertTrue(transform_calfire({"Incidents": []}, reference()).empty)
        records = dataframe_records(tables.county_summary)
        self.assertEqual(records[0]["county_fips"], "06001")
        self.assertEqual(records[0]["earthquake_count"], 0)
        self.assertIsNone(records[0]["max_earthquake_magnitude"])
        json.dumps(records, allow_nan=False)

    def test_raw_join_matches_independent_outputs_without_double_counting(self):
        raw_eq = usgs_response([usgs_feature(), usgs_feature("outside", coordinates=[-120, 36, 5])])
        raw_fire = {"Incidents": [fire_record()]}
        tables = transform_raw_hazards(raw_eq, raw_fire, reference())
        eq = transform_usgs(raw_eq, reference())
        fire = transform_calfire(raw_fire, reference())
        self.assertEqual(dataframe_records(eq), dataframe_records(tables.earthquakes))
        self.assertEqual(tables.county_summary["earthquake_count"].sum(), 1)
        self.assertEqual(tables.county_summary["wildfire_count"].tolist(), [1, 1])
        self.assertEqual(fire["fire_id"].nunique(), len(tables.wildfire_events))
        self.assertFalse(fire.duplicated(["fire_id", "county_fips"]).any())
        self.assertEqual(dataframe_records(fire)[0]["counties"], ["Alameda", "Alpine"])


if __name__ == "__main__":
    unittest.main()
