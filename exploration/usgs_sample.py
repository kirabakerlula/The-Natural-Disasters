import requests
import pandas as pd


# USGS Earthquake API
url = "https://earthquake.usgs.gov/fdsnws/event/1/query"

# For now, we only request a small sample
params = {
    "format": "geojson",
    "starttime": "2025-01-01",
    "endtime": "2025-01-31",
    "minmagnitude": 4.0,
    "minlatitude": 24.4,
    "maxlatitude": 49.4,
    "minlongitude": -125.0,
    "maxlongitude": -66.9,
}


response = requests.get(url, params=params)

print("Status code:", response.status_code)

data = response.json()

rows = []

for feature in data["features"]:
    properties = feature["properties"]
    coordinates = feature["geometry"]["coordinates"]

    rows.append({
        "earthquake_id": feature["id"],
        "time": properties["time"],
        "place": properties["place"],
        "magnitude": properties["mag"],
        "longitude": coordinates[0],
        "latitude": coordinates[1],
        "depth": coordinates[2],
    })


df = pd.DataFrame(rows)

df["time"] = pd.to_datetime(
    df["time"],
    unit="ms",
    utc=True
)

df["date"] = df["time"].dt.date
df["year_month"] = df["time"].dt.strftime("%Y-%m")

print("\nFirst 5 rows:")
print(df.head())

print("\nNumber of rows and columns:")
print(df.shape)

print("\nColumns:")
print(df.columns.tolist())

print("\nMissing values:")
print(df.isna().sum())

print("\nSelected columns:")
print(
    df[
        [
            "earthquake_id",
            "date",
            "year_month",
            "place",
            "magnitude",
            "latitude",
            "longitude",
            "depth"
        ]
    ].head()
)

selected_columns = [
    "earthquake_id",
    "date",
    "year_month",
    "place",
    "magnitude",
    "latitude",
    "longitude",
    "depth"
]

sample_df = df[selected_columns]

sample_df.to_csv(
    "usgs_earthquake_sample.csv",
    index=False
)

print("\nSaved sample data to usgs_earthquake_sample.csv")